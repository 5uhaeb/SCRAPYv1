import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL or Key not found in .env file")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def upsert_products(products: list[dict]) -> int:
    if not products:
        return 0

    # 1) Deduplicate by product_url to avoid Postgres "row a second time" error
    dedup = {}
    for p in products:
        url = p.get("product_url")
        if not url:
            continue
        dedup[url] = p  # keep latest occurrence

    final = list(dedup.values())

    # 2) Convert datetime to ISO string for timestamptz
    for p in final:
        if "scraped_at" in p and hasattr(p["scraped_at"], "isoformat"):
            p["scraped_at"] = p["scraped_at"].isoformat()

    supabase.table("products").upsert(final).execute()
    return len(final)