import asyncio
from datetime import datetime, timezone

import api
from scrapers.base import Item


def test_results_survive_store_and_database_failures(monkeypatch):
    async def run():
        now = datetime.now(timezone.utc)
        job = api.Job(id="progress", status="queued", created_at=now, updated_at=now,
                      sites=["good", "bad"], keywords=["phone"], pages=1)
        api.JOBS[job.id] = job

        class Adapter:
            last_fetched_urls = []
            def __init__(self, name):
                self.name = name
            async def run(self, *args, **kwargs):
                if self.name == "bad":
                    await asyncio.sleep(0.05)
                    assert len(job.results) == 1
                    raise RuntimeError("failed")
                return [Item(title="Phone", price=100, product_url="https://example.com/p", source_platform="good", keyword="phone")]

        async def checks(items):
            return []
        async def alerts(items):
            return []
        def fail_save(items):
            raise RuntimeError("database unavailable")
        monkeypatch.setattr(api, "get_scraper", Adapter)
        monkeypatch.setattr(api, "verify_listings", checks)
        monkeypatch.setattr(api, "evaluate_price_alerts", alerts)
        monkeypatch.setattr(api, "upsert_products", fail_save)
        await api._run_job(job.id)
        assert len(job.results) == 1
        assert job.results[0]["title"] == "Phone"
        assert job.status == "failed"
        assert "Price history could not be saved" in job.error
        api.JOBS.pop(job.id)
    asyncio.run(run())
