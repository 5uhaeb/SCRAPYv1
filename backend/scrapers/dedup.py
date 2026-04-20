import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class RedisDedup:
    def __init__(self):
        self._client = None
        self._warned = False
        url = os.getenv("UPSTASH_REDIS_REST_URL")
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        if not url or not token:
            return

        try:
            from upstash_redis.asyncio import Redis

            self._client = Redis(url=url, token=token)
        except Exception as exc:
            logger.warning("Redis dedup disabled: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def seen(self, url: str) -> bool:
        if not self._client:
            self._log_missing()
            return False
        return bool(await self._client.exists(self._key(url)))

    async def mark_seen(self, url: str, ttl: int = 3600) -> None:
        if not self._client:
            self._log_missing()
            return
        await self._client.set(self._key(url), "1", ex=ttl)

    async def ping(self) -> bool:
        if not self._client:
            return False
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    def _key(self, url: str) -> str:
        return f"scrapyv1:seen_urls:{url}"

    def _log_missing(self) -> None:
        if not self._warned:
            logger.warning("Upstash Redis credentials missing; dedup cache is disabled.")
            self._warned = True


dedup_cache = RedisDedup()
