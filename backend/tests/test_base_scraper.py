import httpx
import asyncio

from scrapers.base import BaseScraper, Item


class DummyScraper(BaseScraper):
    name = "dummy"
    base_url = "https://example.com"

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return f"{self.base_url}/search?q={keyword}&page={page}"

    def parse(self, html: str, keyword: str) -> list[Item]:
        return [
            Item(
                title="Example Product",
                price=100,
                product_url="https://example.com/p/1",
                source_platform=self.name,
                keyword=keyword,
                raw={"html": html},
            )
        ]


def test_fetch_retries_httpx(monkeypatch):
    scraper = DummyScraper()
    calls = {"count": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            calls["count"] += 1
            request = httpx.Request("GET", url)
            if calls["count"] == 1:
                raise httpx.ConnectError("temporary", request=request)
            return httpx.Response(200, text="<html><body>ok product content enough to avoid fallback</body></html>", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    html = asyncio.run(scraper._fetch_http("https://example.com"))

    assert calls["count"] == 2
    assert "ok product" in html


def test_run_uses_dedup_cache(monkeypatch):
    scraper = DummyScraper()
    seen_urls = set()

    async def fake_seen(url):
        return url in seen_urls

    async def fake_mark_seen(url, ttl=3600):
        seen_urls.add(url)

    monkeypatch.setattr("scrapers.base.dedup_cache.seen", fake_seen)
    monkeypatch.setattr("scrapers.base.dedup_cache.mark_seen", fake_mark_seen)
    async def fake_fetch(url):
        return "<html>ok</html>"

    monkeypatch.setattr(scraper, "fetch", fake_fetch)

    first = asyncio.run(scraper.run(["iphone"], pages=1))
    second = asyncio.run(scraper.run(["iphone"], pages=1))

    assert len(first) == 1
    assert second == []
    assert first[0].product_hash


def test_run_force_bypasses_dedup_cache(monkeypatch):
    scraper = DummyScraper()

    async def fake_seen(url):
        return True

    async def fake_mark_seen(url, ttl=3600):
        raise AssertionError("force should not mark skipped URLs in this test")

    async def fake_fetch(url):
        return "<html>ok</html>"

    monkeypatch.setattr("scrapers.base.dedup_cache.seen", fake_seen)
    monkeypatch.setattr("scrapers.base.dedup_cache.mark_seen", fake_mark_seen)
    monkeypatch.setattr(scraper, "fetch", fake_fetch)

    items = asyncio.run(scraper.run(["iphone"], pages=1, force=True, mark_immediately=False))

    assert len(items) == 1
    assert scraper.last_fetched_urls == ["https://example.com/search?q=iphone&page=1"]
