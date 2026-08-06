import asyncio
from datetime import datetime, timedelta, timezone

from mongodb_db import _collection, db_healthy


class MongoDedup:
    """Short-lived scrape URL deduplication stored in MongoDB."""

    def __init__(self):
        self._index_ready = False

    @property
    def enabled(self) -> bool:
        return db_healthy()

    def _ensure_index(self) -> None:
        if self._index_ready:
            return
        collection = _collection("scrape_dedup")
        collection.create_index("url", unique=True, name="uniq_scrape_url")
        collection.create_index("expires_at", expireAfterSeconds=0, name="expire_scrape_url")
        self._index_ready = True

    async def seen(self, url: str) -> bool:
        def query() -> bool:
            self._ensure_index()
            return _collection("scrape_dedup").find_one(
                {"url": url, "expires_at": {"$gt": datetime.now(timezone.utc)}},
                {"_id": 1},
            ) is not None

        try:
            return await asyncio.to_thread(query)
        except Exception:
            # Deduplication is an optimization and must never break a scrape.
            return False

    async def mark_seen(self, url: str, ttl: int = 3600) -> None:
        def write() -> None:
            self._ensure_index()
            _collection("scrape_dedup").update_one(
                {"url": url},
                {"$set": {"expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl)}},
                upsert=True,
            )

        try:
            await asyncio.to_thread(write)
        except Exception:
            return

    async def ping(self) -> bool:
        return await asyncio.to_thread(db_healthy)


dedup_cache = MongoDedup()
