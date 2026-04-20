import asyncio
import logging
import random
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from hashlib import md5
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from scrapers.dedup import dedup_cache
from scrapers.playwright_fetcher import playwright_fetcher

logger = logging.getLogger(__name__)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]


class Item(BaseModel):
    title: str
    price: float | None
    currency: str = "INR"
    product_url: str
    image_url: str | None = None
    source_platform: str
    keyword: str
    raw: dict[str, Any] = Field(default_factory=dict)
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    product_hash: str | None = None

    @field_validator("title", "product_url", "source_platform", "keyword")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


def normalize_title(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def product_hash_for(title: str, source_platform: str) -> str:
    normalized = normalize_title(title)
    return md5(f"{normalized}{source_platform}".encode("utf-8")).hexdigest()


class BaseScraper(ABC):
    name: str
    base_url: str
    requires_js: bool = False

    def __init__(self):
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": "https://www.google.com/",
        }

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _fetch_http(self, url: str) -> str:
        headers = dict(self.headers)
        headers["User-Agent"] = random.choice(USER_AGENTS)
        async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=35) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 429 and response.headers.get("Retry-After"):
                await asyncio.sleep(min(int(response.headers["Retry-After"]), 15))
                raise httpx.HTTPStatusError("Retry after", request=response.request, response=response)
            response.raise_for_status()
            return response.text

    async def fetch(self, url: str) -> str:
        if self.requires_js:
            return await playwright_fetcher.fetch(url)

        try:
            html = await self._fetch_http(url)
            if self._suspiciously_empty(html):
                return await playwright_fetcher.fetch(url)
            return html
        except Exception:
            logger.info("%s falling back to Playwright for %s", self.name, url)
            return await playwright_fetcher.fetch(url)

    @abstractmethod
    def build_search_url(self, keyword: str, page: int = 1) -> str:
        raise NotImplementedError

    @abstractmethod
    def parse(self, html: str, keyword: str) -> list[Item]:
        raise NotImplementedError

    async def run(self, keywords: list[str], pages: int = 2) -> list[Item]:
        collected: list[Item] = []
        for keyword in keywords:
            for page in range(1, pages + 1):
                url = self.build_search_url(keyword, page)
                if await dedup_cache.seen(url):
                    continue

                html = await self.fetch(url)
                items = self.parse(html, keyword)
                for item in items:
                    item.source_platform = item.source_platform or self.name
                    item.product_hash = item.product_hash or product_hash_for(item.title, item.source_platform)
                collected.extend(items)
                await dedup_cache.mark_seen(url)

        return self._dedupe_items(collected)

    def normalize_price(self, raw: str | float | int | None) -> float | None:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)

        text = str(raw)
        text = text.replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("INR", "")
        text = re.sub(r"[^\d.,]", "", text)
        if not text:
            return None
        if "," in text:
            text = text.replace(",", "")
        if text.endswith(".00"):
            text = text[:-3]
        try:
            value = float(text)
        except ValueError:
            return None
        return value if value > 0 else None

    def _dedupe_items(self, items: list[Item]) -> list[Item]:
        deduped: dict[tuple[str, str], Item] = {}
        for item in items:
            deduped[(item.source_platform, item.product_url)] = item
        return list(deduped.values())

    def _suspiciously_empty(self, html: str) -> bool:
        text = (html or "").strip().lower()
        return len(text) < 600 or "enable javascript" in text or "captcha" in text
