import asyncio

import pytest
from fastapi.testclient import TestClient

import api
import alerts


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SCRAPE_API_KEY", "test-operator-key")
    api.JOBS.clear()
    api.SCRAPE_REQUESTS.clear()
    return TestClient(api.app)


def test_legacy_scrapes_and_watch_mutations_require_operator_key(client):
    assert client.post("/scrape", json={"site": "gsmarena", "keywords": ["samsung"]}).status_code == 401
    assert client.post("/v2/watch", json={"product_hash": "test", "target_price": 100}).status_code == 401
    assert client.post("/v2/scrape", json={"sites": ["flipkart"], "keywords": ["phone"]}).status_code == 401


@pytest.mark.parametrize("url", ["http://127.0.0.1", "https://gsmarena.com.evil.invalid", "https://user:pass@www.gsmarena.com/", "https://www.gsmarena.com:8443/"])
def test_legacy_url_cannot_fetch_arbitrary_hosts(client, monkeypatch, url):
    monkeypatch.setattr(api, "run_scrape", lambda *args: pytest.fail("must not make a network request"))
    response = client.post("/scrape", headers={"x-api-key": "test-operator-key"}, json={"site": "gsmarena", "keywords": ["samsung"], "url": url})
    assert response.status_code == 400


def test_public_cooldown_cannot_be_bypassed_with_forwarded_header(client, monkeypatch):
    monkeypatch.delenv("SCRAPE_API_KEY")
    monkeypatch.setattr(api, "_start_job", lambda *args: {"job_id": "test"})
    body = {"sites": ["flipkart"], "keywords": ["phone"]}
    assert client.post("/v2/scrape", json=body, headers={"x-forwarded-for": "one"}).status_code == 202
    assert client.post("/v2/scrape", json=body, headers={"x-forwarded-for": "two"}).status_code == 429


def test_database_errors_are_not_returned_to_clients(client, monkeypatch):
    def fail(*args):
        raise RuntimeError("mongodb://private-user:private-password@db.invalid")
    monkeypatch.setattr(api, "list_products", fail)
    response = client.get("/v2/products")
    assert response.status_code == 503
    assert "private-password" not in response.text


def test_keyword_and_price_validation(client):
    assert client.post("/v2/scrape", json={"sites": ["flipkart"], "keywords": ["phone"] * 11}, headers={"x-api-key": "test-operator-key"}).status_code == 422
    assert client.post("/v2/watch", json={"product_hash": "", "target_price": 100}, headers={"x-api-key": "test-operator-key"}).status_code == 422


def test_price_drop_uses_prior_price_and_sends_watch_alert(monkeypatch):
    monkeypatch.setattr(alerts, "last_price", lambda _: 100)
    monkeypatch.setattr(alerts, "watchlist_matches", lambda *args: [{"target_price": 90, "chat_id": "test-chat"}])
    sent = []
    async def send(alert):
        sent.append(alert)
        return True
    monkeypatch.setattr(alerts, "send_telegram_alert", send)
    result = asyncio.run(alerts.evaluate_price_alerts([{"product_hash": "test", "price": 80, "title": "Phone"}]))
    assert [alert["kind"] for alert in result] == ["price_drop", "target_price"]
    assert sent[0]["drop_pct"] == 20
    assert sent[1]["chat_id"] == "test-chat"
