import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def _require_client():
    if not supabase:
        raise ValueError("Supabase URL or Key not found in environment")
    return supabase


def _serialize_row(product) -> dict:
    row = product.model_dump(mode="json") if hasattr(product, "model_dump") else dict(product)
    if "platform" in row and "source_platform" not in row:
        row["source_platform"] = row.pop("platform")
    if isinstance(row.get("scraped_at"), datetime):
        row["scraped_at"] = row["scraped_at"].isoformat()
    return row


def upsert_products(products: list[dict]) -> int:
    if not products:
        return 0
    client = _require_client()

    dedup = {}
    for p in products:
        row = _serialize_row(p)
        url = row.get("product_url")
        platform = row.get("source_platform")
        if not url:
            continue
        dedup[(platform, url)] = row

    final = list(dedup.values())
    if not final:
        return 0

    client.table("products").upsert(
        final,
        on_conflict="source_platform,product_url",
    ).execute()

    history = [
        {
            "product_hash": row.get("product_hash"),
            "price": row.get("price"),
            "currency": row.get("currency", "INR"),
            "scraped_at": row.get("scraped_at"),
            "source_platform": row.get("source_platform"),
        }
        for row in final
        if row.get("product_hash") and row.get("price") is not None
    ]
    if history:
        client.table("price_history").insert(history).execute()
    return len(final)


def list_products(keyword: str | None = None, platform: str | None = None, limit: int = 50, offset: int = 0):
    client = _require_client()
    query = client.table("products").select("*").order("scraped_at", desc=True).range(offset, offset + limit - 1)
    if keyword:
        query = query.ilike("keyword", f"%{keyword}%")
    if platform:
        query = query.eq("source_platform", platform)
    return query.execute().data or []


def cheapest_products(keyword: str, limit: int = 20):
    client = _require_client()
    query = (
        client.table("products")
        .select("*")
        .ilike("keyword", f"%{keyword}%")
        .not_.is_("price", "null")
        .order("price")
        .limit(limit)
    )
    return query.execute().data or []


def product_history(product_hash: str):
    client = _require_client()
    return (
        client.table("price_history")
        .select("*")
        .eq("product_hash", product_hash)
        .order("scraped_at")
        .execute()
        .data
        or []
    )


def db_healthy() -> bool:
    if not supabase:
        return False
    try:
        supabase.table("products").select("product_url").limit(1).execute()
        return True
    except Exception:
        return False
