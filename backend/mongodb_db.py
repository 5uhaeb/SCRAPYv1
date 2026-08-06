import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument, UpdateOne
from pymongo.collection import Collection

load_dotenv()


@lru_cache(maxsize=1)
def _require_client() -> MongoClient:
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise ValueError("MONGODB_URI is not configured")
    return MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)


def _database():
    name = os.getenv("MONGODB_DB", "scrapyv1")
    return _require_client()[name]


def _collection(name: str) -> Collection:
    return _database()[name]


def ensure_indexes() -> None:
    products = _collection("products")
    products.create_index(
        [("source_platform", ASCENDING), ("product_url", ASCENDING)],
        unique=True,
        name="uniq_platform_product_url",
    )
    products.create_index([("scraped_at", DESCENDING)], name="products_recent")
    products.create_index([("keyword", ASCENDING), ("price", ASCENDING)], name="products_keyword_price")
    history = _collection("price_history")
    history.create_index([("product_hash", ASCENDING), ("scraped_at", ASCENDING)], name="history_product_time")
    _collection("watchlist").create_index(
        [("product_hash", ASCENDING), ("chat_id", ASCENDING)],
        unique=True,
        name="uniq_watch_product_chat",
    )


def _serialize_row(product: Any) -> dict:
    row = product.model_dump(mode="json") if hasattr(product, "model_dump") else dict(product)
    if "platform" in row and "source_platform" not in row:
        row["source_platform"] = row.pop("platform")
    if row.get("source_platform") and "platform" not in row:
        row["platform"] = row["source_platform"]
    if isinstance(row.get("scraped_at"), str):
        parsed = row["scraped_at"].replace("Z", "+00:00")
        try:
            row["scraped_at"] = datetime.fromisoformat(parsed)
        except ValueError:
            row["scraped_at"] = datetime.now(timezone.utc)
    row.setdefault("scraped_at", datetime.now(timezone.utc))
    if isinstance(row.get("price"), float) and row["price"].is_integer():
        row["price"] = int(row["price"])
    row.pop("id", None)
    row.pop("_id", None)
    return row


def _json_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    if isinstance(result.get("_id"), ObjectId):
        result["id"] = str(result.pop("_id"))
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def upsert_products(products: list[dict]) -> int:
    if not products:
        return 0
    ensure_indexes()
    dedup: dict[tuple[str | None, str], dict] = {}
    for product in products:
        row = _serialize_row(product)
        url = row.get("product_url")
        if url:
            dedup[(row.get("source_platform"), url)] = row
    rows = list(dedup.values())
    if not rows:
        return 0

    operations = [
        UpdateOne(
            {"source_platform": row.get("source_platform"), "product_url": row["product_url"]},
            {"$set": row, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        for row in rows
    ]
    _collection("products").bulk_write(operations, ordered=False)
    history = [
        {
            "product_hash": row.get("product_hash"),
            "price": row.get("price"),
            "currency": row.get("currency", "INR"),
            "scraped_at": row.get("scraped_at"),
            "source_platform": row.get("source_platform"),
        }
        for row in rows
        if row.get("product_hash") and row.get("price") is not None
    ]
    if history:
        _collection("price_history").insert_many(history, ordered=False)
    return len(rows)


def list_products(keyword: str | None = None, platform: str | None = None, limit: int = 50, offset: int = 0):
    filters: dict[str, Any] = {}
    if keyword:
        filters["keyword"] = {"$regex": re.escape(keyword), "$options": "i"}
    if platform:
        filters["source_platform"] = platform
    cursor = _collection("products").find(filters).sort("scraped_at", DESCENDING).skip(offset).limit(limit)
    return [_json_row(row) for row in cursor]


def cheapest_products(keyword: str, limit: int = 20):
    filters = {"keyword": {"$regex": re.escape(keyword), "$options": "i"}, "price": {"$ne": None}}
    return [_json_row(row) for row in _collection("products").find(filters).sort("price", ASCENDING).limit(limit)]


def product_history(product_hash: str):
    cursor = _collection("price_history").find({"product_hash": product_hash}).sort("scraped_at", ASCENDING)
    return [_json_row(row) for row in cursor]


def add_watch(product_hash: str, target_price: float, chat_id: str | None = None) -> dict:
    ensure_indexes()
    resolved_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID") or "default"
    now = datetime.now(timezone.utc)
    row = _collection("watchlist").find_one_and_update(
        {"product_hash": product_hash, "chat_id": resolved_chat_id},
        {"$set": {"target_price": target_price, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return _json_row(row)


def last_price(product_hash: str) -> float | None:
    row = _collection("price_history").find_one(
        {"product_hash": product_hash, "price": {"$ne": None}},
        sort=[("scraped_at", DESCENDING)],
    )
    return float(row["price"]) if row else None


def watchlist_matches(product_hash: str, price: float) -> list[dict]:
    return [_json_row(row) for row in _collection("watchlist").find({"product_hash": product_hash, "target_price": {"$gte": price}})]


def db_healthy() -> bool:
    try:
        _require_client().admin.command("ping")
        return True
    except Exception:
        return False
