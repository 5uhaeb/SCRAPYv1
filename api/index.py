"""
Vercel Serverless API – self-contained so that Vercel can bundle it
without needing parent-directory imports.
"""

import os
import re
import json
import time
import random
from typing import List, Optional
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client

# ── Supabase client ──────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL or SUPABASE_KEY not set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def upsert_products(products: list) -> int:
    if not products:
        return 0
    dedup = {}
    for p in products:
        url = p.get("product_url")
        if not url:
            continue
        dedup[url] = p
    final = list(dedup.values())
    for p in final:
        if "scraped_at" in p and hasattr(p["scraped_at"], "isoformat"):
            p["scraped_at"] = p["scraped_at"].isoformat()
    get_supabase().table("products").upsert(final).execute()
    return len(final)


# ── Helpers ──────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def fetch(url: str, timeout=30) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 403:
            return None
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None


def clean_price(txt: str):
    if not txt:
        return None
    m = re.search(r"₹\s*([\d,]+)", txt)
    raw = m.group(1) if m else None
    if not raw:
        m2 = re.search(r"(\d[\d,]{3,})", txt)
        raw = m2.group(1) if m2 else None
    if not raw:
        return None
    try:
        val = int(raw.replace(",", ""))
    except Exception:
        return None
    if val < 500 or val > 500000:
        return None
    return val


def normalize(s: str) -> str:
    s = (s or "").lower().replace("-", " ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_matches_keyword(title: str, keyword: str) -> bool:
    t = normalize(title)
    k = normalize(keyword)
    if not k:
        return False
    if k in t:
        return True
    if k.replace(" ", "") in t.replace(" ", ""):
        return True
    return False


# ── VijaySales scraper ───────────────────────────────────────────────────────

VS_BASE = "https://www.vijaysales.com"


def vs_get_category_url(keyword: str) -> str:
    k = normalize(keyword)
    if "iphone" in k:
        return f"{VS_BASE}/c/iphones"
    return f"{VS_BASE}/c/mobiles"


def vs_parse_category(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    links = soup.select("a[href*='/p/']")
    seen = set()
    for a in links:
        href = a.get("href")
        if not href:
            continue
        product_url = urljoin(VS_BASE, href)
        if product_url in seen:
            continue
        seen.add(product_url)
        title = a.get_text(" ", strip=True)
        parent = a.find_parent()
        parent_text = parent.get_text(" ", strip=True) if parent else title
        if not title:
            title = parent_text
        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 5:
            continue
        price = clean_price(parent_text)
        items.append({
            "product_url": product_url,
            "title": title[:250],
            "price": price,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })
    return items


def scrape_vijaysales(keywords: list) -> dict:
    matched = []
    for kw in keywords:
        url = vs_get_category_url(kw)
        html = fetch(url)
        if not html:
            continue
        rows = vs_parse_category(html)
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


# ── Webscraper.io scraper ────────────────────────────────────────────────────

WS_BASE = "https://webscraper.io/test-sites/e-commerce/allinone"
WS_CATEGORIES = [
    f"{WS_BASE}/computers/laptops",
    f"{WS_BASE}/computers/tablets",
    f"{WS_BASE}/phones/touch",
]


def ws_scrape_category(url: str, pages: int = 5) -> list:
    out = []
    for page in range(1, pages + 1):
        page_url = f"{url}?page={page}"
        r = requests.get(page_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.thumbnail")
        if not cards:
            break
        for c in cards:
            title_el = c.select_one("a.title")
            price_el = c.select_one("h4.price")
            reviews_el = c.select_one("p.pull-right")
            title = (title_el.get("title") if title_el else None) or ""
            href = title_el.get("href") if title_el else None
            product_url = f"https://webscraper.io{href}" if href else None
            price_text = price_el.get_text(strip=True) if price_el else None
            price_nums = re.findall(r"\d+", (price_text or "").replace(",", ""))
            price = int("".join(price_nums)) if price_nums else None
            reviews_text = (reviews_el.get_text(strip=True) if reviews_el else "") or ""
            rev_nums = re.findall(r"\d+", reviews_text.replace(",", ""))
            reviews_count = int("".join(rev_nums)) if rev_nums else None
            if product_url and title.strip():
                out.append({
                    "product_url": product_url,
                    "platform": "webscraper_ecom",
                    "keyword": "",
                    "title": title.strip(),
                    "price": price,
                    "rating": None,
                    "reviews_count": reviews_count,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                })
    return out


def scrape_webscraper(keywords: list, pages: int) -> dict:
    all_rows = []
    for cu in WS_CATEGORIES:
        all_rows.extend(ws_scrape_category(cu, pages=pages))
    final = []
    for kw in keywords:
        k = kw.lower().strip()
        for r in all_rows:
            if k in r.get("title", "").lower():
                r2 = dict(r)
                r2["keyword"] = kw
                final.append(r2)
    saved = upsert_products(final)
    return {"message": f"Webscraper: {len(final)} products matched, {saved} saved to DB"}


# ── GSMArena scraper ─────────────────────────────────────────────────────────

def scrape_gsmarena(url: str, keywords: list) -> dict:
    html = fetch(url)
    if not html:
        raise HTTPException(status_code=502, detail="Could not fetch GSMArena page")
    soup = BeautifulSoup(html, "html.parser")
    items = []
    cards = soup.select("div.makers ul li a")
    if not cards:
        cards = soup.select("div.section-body ul li a")
    for a in cards:
        href = a.get("href")
        if not href:
            continue
        product_url = urljoin(url, href)
        title = a.get_text(" ", strip=True)
        if not title:
            strong = a.select_one("strong")
            title = strong.get_text(" ", strip=True) if strong else None
        if not title:
            continue
        items.append({"product_url": product_url, "title": title[:250], "price": None})

    matched = []
    for r in items:
        t = normalize(r.get("title", ""))
        t_join = t.replace(" ", "")
        for kw in keywords:
            k = normalize(kw)
            k_join = k.replace(" ", "")
            if (k and k in t) or (k_join and k_join in t_join):
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
                break

    saved = upsert_products(matched)
    return {"message": f"GSMArena: {len(matched)} products matched, {saved} saved to DB"}


# ── FastAPI App ──────────────────────────────────────────────────────────────

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
            return scrape_vijaysales(keywords)
        elif site == "webscraper":
            return scrape_webscraper(keywords, req.pages)
        elif site == "gsmarena":
            if not req.url or not req.url.strip():
                raise HTTPException(status_code=400, detail="GSMArena URL is required")
            return scrape_gsmarena(req.url.strip(), keywords)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported site: {site}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
