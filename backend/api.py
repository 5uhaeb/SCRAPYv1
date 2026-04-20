import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from alerts import add_watch, evaluate_price_alerts
from matching import match_products
from scraper_common import run_scrape
from scrapers.dedup import dedup_cache
from scrapers.playwright_fetcher import playwright_fetcher
from scrapers.registry import SCRAPERS, get_scraper
from scrape_vijaysales import run as run_vijaysales
from scrape_webscraper_ecom import run as run_webscraper
from supabase_db import (
    cheapest_products,
    db_healthy,
    list_products,
    product_history,
    upsert_products,
)

load_dotenv()

app = FastAPI(title="SCRAPYv2 API")

frontend_origin = os.getenv("VERCEL_FRONTEND_ORIGIN")
allowed_origins = [
    origin
    for origin in [
        frontend_origin,
        "http://localhost:3000",
        "http://localhost:5173",
        "https://scrap-yv1.vercel.app",
        "https://scrapyv1.vercel.app",
    ]
    if origin
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    sites: list[str] = Field(default_factory=list)
    keywords: list[str]
    pages: int = Field(default=2, ge=1, le=10)
    force: bool = False


class LegacyScrapeRequest(BaseModel):
    site: str
    keywords: list[str]
    pages: int = Field(default=2, ge=1, le=10)
    url: str | None = None


class WatchRequest(BaseModel):
    product_hash: str
    target_price: float = Field(gt=0)
    chat_id: str | None = None


class Job(BaseModel):
    id: str
    status: Literal["queued", "running", "complete", "failed"]
    created_at: datetime
    updated_at: datetime
    sites: list[str]
    keywords: list[str]
    pages: int
    force: bool = False
    results: list[dict] = Field(default_factory=list)
    saved_count: int = 0
    alert_count: int = 0
    error: str | None = None


JOBS: dict[str, Job] = {}
SCRAPER_TIMEOUT_SECONDS = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "120"))


@app.on_event("shutdown")
async def shutdown():
    await playwright_fetcher.shutdown()


@app.get("/")
async def home():
    return {"message": "SCRAPYv2 API is running", "scrapers": sorted(SCRAPERS)}


@app.get("/scrapers")
@app.get("/v2/scrapers")
async def scrapers():
    return {"scrapers": sorted(SCRAPERS)}


def require_scrape_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("SCRAPE_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.post("/scrape")
async def scrape_legacy(req: LegacyScrapeRequest):
    site = req.site.strip().lower()
    keywords = [keyword.strip() for keyword in req.keywords if keyword.strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="No keywords provided")

    try:
        if site == "vijaysales":
            results = await asyncio.to_thread(run_vijaysales, keywords, req.pages, "vijaysales_mobiles.json")
            message = f"VijaySales: {len(results)} products matched"
        elif site == "webscraper":
            results = await asyncio.to_thread(run_webscraper, keywords, req.pages)
            message = f"Webscraper: {len(results)} products matched"
        elif site == "gsmarena":
            if not req.url or not req.url.strip():
                raise HTTPException(status_code=400, detail="GSMArena URL is required")
            results = await asyncio.to_thread(run_scrape, "gsmarena", req.url.strip(), keywords, "scraped.json")
            message = f"GSMArena: {len(results)} products matched"
        else:
            raise HTTPException(status_code=400, detail="Unsupported site")
        return {"message": message, "products": results}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/v2/scrape", status_code=status.HTTP_202_ACCEPTED)
async def scrape(req: ScrapeRequest, _: None = Depends(require_scrape_api_key)):
    sites = [site.strip().lower() for site in req.sites if site.strip()]
    if not sites:
        raise HTTPException(status_code=400, detail="At least one site is required")
    return _start_job(sites, req.keywords, req.pages, req.force)


@app.post("/v2/scrape/all", status_code=status.HTTP_202_ACCEPTED)
async def scrape_all(req: ScrapeRequest, _: None = Depends(require_scrape_api_key)):
    return _start_job(list(SCRAPERS), req.keywords, req.pages, req.force)


@app.get("/v2/scrape/{job_id}")
async def scrape_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/products")
@app.get("/v2/products")
async def products(
    keyword: str | None = None,
    platform: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    try:
        return {"products": list_products(keyword, platform, limit, offset), "limit": limit, "offset": offset}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/products/cheapest")
@app.get("/v2/products/cheapest")
async def products_cheapest(keyword: str, limit: int = Query(default=20, ge=1, le=100)):
    try:
        return {"products": cheapest_products(keyword, limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/products/compare")
@app.get("/v2/products/compare")
async def products_compare(keyword: str, limit: int = Query(default=300, ge=1, le=1000)):
    try:
        rows = list_products(keyword=keyword, limit=limit, offset=0)
        groups = match_products(rows)
        return {"keyword": keyword, "groups": [group.as_dict() for group in groups]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/products/{product_hash}/history")
@app.get("/v2/products/{product_hash}/history")
async def products_history(product_hash: str):
    try:
        return {"product_hash": product_hash, "history": product_history(product_hash)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/watch")
@app.post("/v2/watch")
async def watch(req: WatchRequest):
    try:
        return {"watch": add_watch(req.product_hash, req.target_price, req.chat_id)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health():
    redis_ok = await dedup_cache.ping()
    return {
        "status": "ok",
        "db": db_healthy(),
        "redis": redis_ok,
        "playwright": playwright_fetcher.ready,
        "registered_scrapers": sorted(SCRAPERS),
    }


def _start_job(sites: list[str], keywords: list[str], pages: int, force: bool = False):
    keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="No keywords provided")

    try:
        normalized_sites = [get_scraper(site).name for site in sites]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    JOBS[job_id] = Job(
        id=job_id,
        status="queued",
        created_at=now,
        updated_at=now,
        sites=normalized_sites,
        keywords=keywords,
        pages=pages,
        force=force,
    )
    asyncio.create_task(_run_job(job_id))
    return {"job_id": job_id, "status_url": f"/v2/scrape/{job_id}"}


async def _run_job(job_id: str):
    job = JOBS[job_id]
    job.status = "running"
    job.updated_at = datetime.now(timezone.utc)
    try:
        scrapers = [get_scraper(site) for site in job.sites]
        results_by_site = await asyncio.gather(
            *(_run_scraper_with_timeout(scraper, job) for scraper in scrapers),
            return_exceptions=True,
        )

        all_items = []
        errors = []
        for site, result in zip(job.sites, results_by_site):
            if isinstance(result, Exception):
                if isinstance(result, TimeoutError):
                    errors.append(f"{site}: timed out after {SCRAPER_TIMEOUT_SECONDS}s")
                else:
                    errors.append(f"{site}: {result}")
            else:
                all_items.extend(result)

        alerts = []
        try:
            alerts = await evaluate_price_alerts(all_items)
        except Exception as exc:
            errors.append(f"alerts: {exc}")

        saved = await asyncio.to_thread(upsert_products, all_items)
        if saved > 0:
            for scraper in scrapers:
                for url in scraper.last_fetched_urls:
                    await dedup_cache.mark_seen(url, ttl=900)
        job.results = [item.model_dump(mode="json") for item in all_items]
        job.saved_count = saved
        job.alert_count = len(alerts)
        job.status = "complete" if not errors else "failed"
        job.error = "; ".join(errors) if errors else None
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
    finally:
        job.updated_at = datetime.now(timezone.utc)


async def _run_scraper_with_timeout(scraper, job: Job):
    return await asyncio.wait_for(
        scraper.run(
            job.keywords,
            pages=job.pages,
            force=job.force,
            mark_immediately=False,
        ),
        timeout=SCRAPER_TIMEOUT_SECONDS,
    )
