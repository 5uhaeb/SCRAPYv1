import sys
import os

# Ensure project root is in Python path for scraper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="SCRAPYv1 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    site: str
    keywords: List[str]
    pages: int = 2
    url: Optional[str] = None


@app.get("/api")
def home():
    return {"message": "Scraper API is running"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/scrape")
def scrape(req: ScrapeRequest):
    site = req.site.strip().lower()
    keywords = [k.strip() for k in req.keywords if k.strip()]

    if not keywords:
        raise HTTPException(status_code=400, detail="No keywords provided")

    try:
        if site == "vijaysales":
            return _scrape_vijaysales(keywords)
        elif site == "webscraper":
            return _scrape_webscraper(keywords, req.pages)
        elif site == "gsmarena":
            if not req.url or not req.url.strip():
                raise HTTPException(status_code=400, detail="GSMArena URL is required")
            return _scrape_gsmarena(req.url.strip(), keywords)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported site: {site}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Vijay Sales ──────────────────────────────────────────────────────────────

def _scrape_vijaysales(keywords: list):
    from scrape_vijaysales import (
        fetch, parse_category,
        get_category_url_for_keyword, title_matches_keyword,
    )
    from supabase_db import upsert_products

    matched = []
    for kw in keywords:
        url = get_category_url_for_keyword(kw)
        html = fetch(url)
        if not html:
            continue
        rows = parse_category(html)
        for r in rows:
            if title_matches_keyword(r["title"], kw):
                matched.append({
                    "product_url": r["product_url"],
                    "platform": "vijaysales",
                    "keyword": kw,
                    "title": r["title"],
                    "price": r["price"],
                    "rating": None,
                    "reviews_count": None,
                    "scraped_at": r["scraped_at"],
                })

    dedup = {r["product_url"]: r for r in matched}
    final = list(dedup.values())
    saved = upsert_products(final)
    return {"message": f"VijaySales: {len(final)} products matched, {saved} saved to DB"}


# ── Webscraper.io ────────────────────────────────────────────────────────────

def _scrape_webscraper(keywords: list, pages: int):
    from scrape_webscraper_ecom import scrape_category, match_keyword, CATEGORY_URLS
    from supabase_db import upsert_products

    all_rows = []
    for cu in CATEGORY_URLS:
        all_rows.extend(scrape_category(cu, pages=pages))

    final = []
    for kw in keywords:
        got = match_keyword(all_rows, kw)
        final.extend(got)

    saved = upsert_products(final)
    return {"message": f"Webscraper: {len(final)} products matched, {saved} saved to DB"}


# ── GSMArena ─────────────────────────────────────────────────────────────────

def _scrape_gsmarena(url: str, keywords: list):
    from scraper_common import fetch, assign_keyword
    from profiles import PROFILES
    from supabase_db import upsert_products
    from datetime import datetime, timezone

    profile = PROFILES.get("gsmarena")
    if not profile:
        raise HTTPException(status_code=500, detail="GSMArena profile not configured")

    html = fetch(url)
    rows = profile["parser"](html, base_url=url)

    matched = []
    for r in rows:
        kw = assign_keyword(r.get("title", ""), keywords)
        if kw:
            matched.append({
                "product_url": r["product_url"],
                "platform": "gsmarena",
                "keyword": kw,
                "title": r.get("title"),
                "price": r.get("price"),
                "rating": None,
                "reviews_count": None,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })

    saved = upsert_products(matched)
    return {"message": f"GSMArena: {len(matched)} products matched, {saved} saved to DB"}
