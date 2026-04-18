import re
import time
import random
import json
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from supabase_db import upsert_products

BASE = "https://www.vijaysales.com"
JSON_OUT = "vijaysales_mobiles.json"
DEFAULT_PAGES = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.google.com/",
}

def sleep_polite(a=1.5, b=3.0):
    time.sleep(random.uniform(a, b))

def fetch(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 403:
            print("Blocked with 403:", url)
            return None
        r.raise_for_status()
        return r.text
    except requests.RequestException as e:
        print("Fetch failed:", url, "|", e)
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
    except:
        return None
    if val < 1000 or val > 300000:
        return None
    return val

def normalize(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("-", " ")
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
    t_join = t.replace(" ", "")
    k_join = k.replace(" ", "")
    if k_join in t_join:
        return True
    return False

def append_json(filename: str, new_rows: list[dict]):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            old = json.load(f)
            if not isinstance(old, list):
                old = []
    except:
        old = []

    old.extend(new_rows)

    dedup = {}
    for r in old:
        url = r.get("product_url")
        if url:
            dedup[url] = r

    final = list(dedup.values())

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    return len(final)

def parse_category(html: str):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    links = soup.select("a[href*='/p/']")
    seen = set()

    for a in links:
        href = a.get("href")
        if not href:
            continue

        product_url = urljoin(BASE, href)
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

def get_category_url_for_keyword(keyword: str):
    k = normalize(keyword)
    if "iphone" in k:
        return f"{BASE}/c/iphones"
    return f"{BASE}/c/mobiles"

def run(keywords: list[str], pages: int = DEFAULT_PAGES, json_out: str = JSON_OUT):
    matched = []

    for kw in keywords:
        url = get_category_url_for_keyword(kw)
        print(f"\nFetching category for '{kw}': {url}")

        html = fetch(url)
        if not html:
            print("Could not fetch category page.")
            continue

        rows = parse_category(html)
        print("Parsed items:", len(rows))

        kw_rows = []
        for r in rows:
            if title_matches_keyword(r["title"], kw):
                kw_rows.append({
                    "product_url": r["product_url"],
                    "platform": "vijaysales",
                    "keyword": kw,
                    "title": r["title"],
                    "price": r["price"],
                    "rating": None,
                    "reviews_count": None,
                    "scraped_at": r["scraped_at"],
                })

        dedup = {r["product_url"]: r for r in kw_rows}
        final_kw_rows = list(dedup.values())

        print(f"Matched for '{kw}':", len(final_kw_rows))
        matched.extend(final_kw_rows)
        sleep_polite()

    total_in_json = append_json(json_out, matched)
    print("Updated JSON:", json_out, "| Total unique in JSON:", total_in_json)

    saved = upsert_products(matched)
    print(f"Total matched this run: {len(matched)} | Saved/Upserted: {saved}")

if __name__ == "__main__":
    user_input = input("Keywords: ").strip()
    if not user_input:
        print("No keywords entered. Exiting.")
        raise SystemExit(0)

    keywords = [k.strip() for k in user_input.split(",") if k.strip()]
    run(keywords, pages=DEFAULT_PAGES, json_out=JSON_OUT)