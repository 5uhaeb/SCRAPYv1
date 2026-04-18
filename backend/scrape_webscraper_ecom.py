import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from supabase_db import upsert_products

BASE = "https://webscraper.io/test-sites/e-commerce/allinone"

CATEGORY_URLS = [
    f"{BASE}/computers/laptops",
    f"{BASE}/computers/tablets",
    f"{BASE}/phones/touch",
]

HEADERS = {"User-Agent": "Mozilla/5.0"}

def clean_price(txt: str):
    if not txt:
        return None
    nums = re.findall(r"\d+", txt.replace(",", ""))
    return int("".join(nums)) if nums else None

def scrape_category(url: str, pages: int = 5) -> list[dict]:
    """Scrape a category with pagination: ?page=1,2,..."""
    out = []
    
    for page in range(1, pages + 1):
        page_url = f"{url}?page={page}"
        r = requests.get(page_url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.select("div.thumbnail")
        if not cards:
            break  # end pages

        for c in cards:
            title_el = c.select_one("a.title")
            price_el = c.select_one("h4.price")
            desc_el = c.select_one("p.description")
            reviews_el = c.select_one("p.pull-right")  # e.g., "8 reviews"

            title = (title_el.get("title") if title_el else None) or ""
            href = title_el.get("href") if title_el else None
            product_url = f"https://webscraper.io{href}" if href else None

            price = clean_price(price_el.get_text(strip=True) if price_el else None)

            desc = (desc_el.get_text(" ", strip=True) if desc_el else "") or ""
            reviews_text = (reviews_el.get_text(strip=True) if reviews_el else "") or ""
            reviews_count = clean_price(reviews_text)

            if product_url and title.strip():
                out.append({
                    "product_url": product_url,
                    "platform": "webscraper_ecom",
                    "keyword": "",  # filled later after matching
                    "title": title.strip(),
                    "price": price,
                    "rating": None,
                    "reviews_count": reviews_count,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "desc": desc,  # not stored in DB; used only for filtering
                })
    return out

def match_keyword(rows: list[dict], keyword: str) -> list[dict]:
    k = keyword.lower().strip()
    matched = []
    for r in rows:
        hay = (r.get("title", "") + " " + r.get("desc", "")).lower()
        if k in hay:
            r2 = dict(r)
            r2["keyword"] = keyword
            r2.pop("desc", None)  # remove extra field before saving
            matched.append(r2)
    return matched

def run(keywords: list[str], pages_per_cat: int = 5):
    # 1) collect all products from categories
    all_rows = []
    for cu in CATEGORY_URLS:
        all_rows.extend(scrape_category(cu, pages=pages_per_cat))

    print("Total products pulled from categories:", len(all_rows))

    # 2) keyword filter + save
    final = []
    for kw in keywords:
        got = match_keyword(all_rows, kw)
        print(f"{kw}: {len(got)} matched")
        final.extend(got)

    saved = upsert_products(final)
    print(f"Total matched: {len(final)} | Saved/Upserted: {saved}")
    return final

if __name__ == "__main__":
    run(["laptop", "tablet", "iphone"])