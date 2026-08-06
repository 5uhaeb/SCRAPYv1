import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
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
from mongodb_db import (
    cheapest_products,
    db_healthy,
    list_products,
    product_history,
    upsert_products,
)

load_dotenv()

API_DESCRIPTION = """
## Product price intelligence API

SCRAPYv2 searches supported Indian e-commerce sites, normalizes product listings, stores
current prices and historical observations in MongoDB, and exposes comparison and alert APIs.

### Typical workflow

1. Call **GET `/v2/scrapers`** to discover supported site identifiers.
2. Submit **POST `/v2/scrape`** with one or more sites and keywords.
3. The API immediately returns `202 Accepted` with a `job_id` and `status_url`.
4. Poll **GET `/v2/scrape/{job_id}`** until the status becomes `complete` or `failed`.
5. Query saved data through `/v2/products`, `/cheapest`, `/compare`, or `/history`.

### Scrape access and limits

The hosted API is public. A client can start one scrape every **30 seconds**, and the service
runs at most **two jobs concurrently**. A `429` response means the cooldown is active or all
worker slots are busy. Private deployments may set `SCRAPE_API_KEY`; clients then send it in
the `x-api-key` header instead of using public throttling.

### Persistence and job lifetime

Products, price history, watchlists, and URL deduplication are stored in the shared MongoDB
cluster under the separate `scrapyv1` database. Product writes are idempotent by platform and
URL. Each successful observation appends a price-history record. Job status itself is held in
the running API process, so save the returned status URL and poll it promptly; a backend restart
clears completed job metadata but does not remove saved products or price history.

### Interactive usage

Expand an operation, select **Try it out**, enter its parameters or JSON body, and press
**Execute**. The consumer dashboard is available at
[scrap-yv1.vercel.app](https://scrap-yv1.vercel.app/).
"""

OPENAPI_TAGS = [
    {"name": "Service", "description": "Service discovery and operational health."},
    {"name": "Scraping", "description": "Start asynchronous scrape jobs and monitor their lifecycle."},
    {"name": "Products", "description": "Read normalized products, comparisons, and price history from MongoDB."},
    {"name": "Alerts", "description": "Create target-price watches used by Telegram price alerts."},
    {"name": "Legacy", "description": "Compatibility endpoint for older single-site clients."},
]

app = FastAPI(
    title="SCRAPYv2 Price Intelligence API",
    summary="Scrape, compare, and track e-commerce prices",
    description=API_DESCRIPTION,
    version="2.1.0",
    openapi_tags=OPENAPI_TAGS,
    contact={"name": "SCRAPYv2 source", "url": "https://github.com/5uhaeb/SCRAPYv1"},
    license_info={"name": "MIT", "identifier": "MIT"},
)

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
    sites: list[str] = Field(default_factory=list, description="Site identifiers returned by `/v2/scrapers`.", examples=[["vijaysales", "flipkart"]])
    keywords: list[str] = Field(description="Product search phrases. Blank strings are ignored.", examples=[["iphone 15", "samsung s24"]])
    pages: int = Field(default=2, ge=1, le=10, description="Maximum result pages to fetch per site and keyword.")
    force: bool = Field(default=False, description="Ignore the short-lived URL deduplication cache and fetch again.")


class LegacyScrapeRequest(BaseModel):
    site: str
    keywords: list[str]
    pages: int = Field(default=2, ge=1, le=10)
    url: str | None = None


class WatchRequest(BaseModel):
    product_hash: str = Field(description="Stable product hash returned by a product or scrape response.")
    target_price: float = Field(gt=0, description="Alert when the observed price is at or below this amount in INR.")
    chat_id: str | None = Field(default=None, description="Optional Telegram chat ID; the server default is used when omitted.")


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
SCRAPE_REQUESTS: dict[str, float] = {}
PUBLIC_SCRAPE_COOLDOWN_SECONDS = int(os.getenv("PUBLIC_SCRAPE_COOLDOWN_SECONDS", "30"))
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
# Long enough for slow Render Playwright runs; set to 0 to disable the safety cutoff.
SCRAPER_TIMEOUT_SECONDS = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "420"))


@app.on_event("shutdown")
async def shutdown():
    await playwright_fetcher.shutdown()


@app.get("/", tags=["Service"], summary="Describe the running API")
async def home():
    return {"message": "SCRAPYv2 API is running", "scrapers": sorted(SCRAPERS)}


@app.get("/scrapers", include_in_schema=False)
@app.get("/v2/scrapers", tags=["Service"], summary="List supported scraper identifiers", description="Returns the exact site names accepted by the `sites` field of scrape requests.")
async def scrapers():
    return {"scrapers": sorted(SCRAPERS)}


def require_scrape_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("SCRAPE_API_KEY")
    if expected:
        if x_api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return

    running_jobs = sum(job.status in {"queued", "running"} for job in JOBS.values())
    if running_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="The scraper is busy. Try again shortly.")

    now = time.monotonic()
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    client_id = forwarded_for or (request.client.host if request.client else "unknown")
    last_request = SCRAPE_REQUESTS.get(client_id, 0)
    if now - last_request < PUBLIC_SCRAPE_COOLDOWN_SECONDS:
        retry_after = max(1, int(PUBLIC_SCRAPE_COOLDOWN_SECONDS - (now - last_request)))
        raise HTTPException(status_code=429, detail=f"Please wait {retry_after}s before starting another scrape.")
    SCRAPE_REQUESTS[client_id] = now


@app.post("/scrape", tags=["Legacy"], summary="Run a legacy synchronous scrape", deprecated=True)
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


@app.post("/v2/scrape", status_code=status.HTTP_202_ACCEPTED, tags=["Scraping"], summary="Start a scrape job", description="Queues an asynchronous scrape for selected sites. Use the returned `status_url` to monitor it. Public cooldown and concurrency limits apply.")
async def scrape(req: ScrapeRequest, _: None = Depends(require_scrape_api_key)):
    sites = [site.strip().lower() for site in req.sites if site.strip()]
    if not sites:
        raise HTTPException(status_code=400, detail="At least one site is required")
    return _start_job(sites, req.keywords, req.pages, req.force)


@app.post("/v2/scrape/all", status_code=status.HTTP_202_ACCEPTED, tags=["Scraping"], summary="Scrape every registered site", description="Queues all registered adapters for the supplied keywords. This is heavier than selecting individual sites.")
async def scrape_all(req: ScrapeRequest, _: None = Depends(require_scrape_api_key)):
    return _start_job(list(SCRAPERS), req.keywords, req.pages, req.force)


@app.get("/v2/scrape/{job_id}", tags=["Scraping"], summary="Get scrape job status", description="Returns lifecycle timestamps, normalized results, saved and alert counts, and any per-site error details. Poll until `complete` or `failed`.")
async def scrape_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/products", include_in_schema=False)
@app.get("/v2/products", tags=["Products"], summary="List saved products", description="Returns recently observed MongoDB products with optional case-insensitive keyword and exact platform filters. Use limit and offset for pagination.")
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


@app.get("/products/cheapest", include_in_schema=False)
@app.get("/v2/products/cheapest", tags=["Products"], summary="Find the cheapest matching products", description="Filters by keyword, excludes missing prices, and orders results from lowest to highest price.")
async def products_cheapest(keyword: str, limit: int = Query(default=20, ge=1, le=100)):
    try:
        return {"products": cheapest_products(keyword, limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/products/compare", include_in_schema=False)
@app.get("/v2/products/compare", tags=["Products"], summary="Compare equivalent products across platforms", description="Uses normalized titles and fuzzy matching to group likely equivalent listings across stores.")
async def products_compare(keyword: str, limit: int = Query(default=300, ge=1, le=1000)):
    try:
        rows = list_products(keyword=keyword, limit=limit, offset=0)
        groups = match_products(rows)
        return {"keyword": keyword, "groups": [group.as_dict() for group in groups]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/products/{product_hash}/history", include_in_schema=False)
@app.get("/v2/products/{product_hash}/history", tags=["Products"], summary="Get a product's price history", description="Returns all stored price observations for a product hash in chronological order.")
async def products_history(product_hash: str):
    try:
        return {"product_hash": product_hash, "history": product_history(product_hash)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/watch", include_in_schema=False)
@app.post("/v2/watch", tags=["Alerts"], summary="Create or update a target-price watch", description="Upserts a MongoDB watchlist entry. Telegram delivery requires bot and chat credentials on the backend.")
async def watch(req: WatchRequest):
    try:
        return {"watch": add_watch(req.product_hash, req.target_price, req.chat_id)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health", tags=["Service"], summary="Check service dependencies", description="Reports MongoDB connectivity, MongoDB-backed dedup availability, Playwright warm state, and registered scrapers.")
async def health():
    dedup_ok = await dedup_cache.ping()
    return {
        "status": "ok",
        "db": db_healthy(),
        "dedup": dedup_ok,
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
                    errors.append(
                        f"{site}: timed out after {SCRAPER_TIMEOUT_SECONDS}s; "
                        "increase SCRAPER_TIMEOUT_SECONDS or set it to 0 for no cutoff"
                    )
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
    run_coro = scraper.run(
        job.keywords,
        pages=job.pages,
        force=job.force,
        mark_immediately=False,
    )
    if SCRAPER_TIMEOUT_SECONDS <= 0:
        return await run_coro
    return await asyncio.wait_for(run_coro, timeout=SCRAPER_TIMEOUT_SECONDS)
