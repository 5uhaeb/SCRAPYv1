import re
import json
import time
import random
from datetime import datetime, timezone

import requests
from supabase_db import upsert_products
from profiles import PROFILES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}

def sleep_polite(a=1.2, b=2.5):
    time.sleep(random.uniform(a, b))

def fetch(url: str, timeout=40) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text

def normalize(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("-", " ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def assign_keyword(title: str, keywords: list[str]):
    t = normalize(title)
    t_join = t.replace(" ", "")

    for kw in keywords:
        k = normalize(kw)
        k_join = k.replace(" ", "")
        tokens = [tok for tok in k.split() if len(tok) >= 2]

        if k and k in t:
            return kw
        if k_join and k_join in t_join:
            return kw

        hits = sum(1 for tok in tokens if tok in t)
        if len(tokens) >= 3 and hits >= 2:
            return kw
        if len(tokens) <= 2 and hits == len(tokens):
            return kw
    return None

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

def run_scrape(profile_name: str, url: str, keywords: list[str], json_out: str = "scraped.json"):
    if profile_name not in PROFILES:
        raise ValueError(f"Unknown profile '{profile_name}'. Available: {list(PROFILES.keys())}")

    profile = PROFILES[profile_name]
    platform = profile["platform"]
    parser = profile["parser"]

    print(f"\n[SCRAPE] platform={platform}")
    print("Fetching:", url)
    html = fetch(url)
    rows = parser(html, base_url=url)

    print("Parsed rows:", len(rows))

    matched = []
    for r in rows:
        kw = assign_keyword(r.get("title", ""), keywords)
        if kw:
            matched.append({
                "product_url": r["product_url"],
                "platform": platform,
                "keyword": kw,
                "title": r.get("title"),
                "price": r.get("price"),
                "rating": None,
                "reviews_count": None,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })

    total_json = append_json(json_out, matched)
    print("Updated JSON:", json_out, "| Total unique in JSON:", total_json)

    saved = upsert_products(matched)
    print(f"Total matched this run: {len(matched)} | Saved/Upserted: {saved}")
    return matched