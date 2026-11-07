import asyncio
from types import SimpleNamespace

import httpx
from buyhatke import buyhatke_url, parse_public_page, verify_listing


def test_only_known_store_product_urls_are_sent_to_buyhatke():
    assert buyhatke_url("https://www.amazon.in/dp/B012345678") == "https://buyhatke.com/https://www.amazon.in/dp/B012345678"
    assert buyhatke_url("https://amazon.in.evil.example/dp/x") is None
    assert buyhatke_url("http://127.0.0.1/private") is None
    assert buyhatke_url("https://user:pass@flipkart.com/p/x") is None


def test_public_page_only_uses_explicit_product_price_and_dated_points():
    html = '''<script type="application/ld+json">{"@type":"Product","name":"Phone 15 128GB","offers":{"price":"69,999","priceCurrency":"INR"}}</script>
    <div data-date="2026-01-10" data-price="72000"></div><div data-price="1"></div>'''
    parsed = parse_public_page(html)
    assert parsed["price"] == 69999
    # A current structured offer does not imply a historical observation.
    assert parsed["history"] == [{"scraped_at": "2026-01-10T00:00:00", "price": 72000.0, "source": "buyhatke"}]


def test_unrelated_buyhatke_product_is_not_a_verification():
    html = '<script type="application/ld+json">{"@type":"Product","name":"Kitchen Mixer","offers":{"price":"69999","priceCurrency":"INR"}}</script>'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    async def check():
        async with httpx.AsyncClient(transport=transport) as client:
            item = SimpleNamespace(product_url="https://www.amazon.in/dp/B012345678", title="Phone 15 128GB", price=69999)
            return await verify_listing(item, client)
    result = asyncio.run(check())
    assert result["status"] == "unavailable"


def test_different_storage_variant_is_not_a_verification():
    html = '<script type="application/ld+json">{"@type":"Product","name":"Phone 15 256GB","offers":{"price":"69999","priceCurrency":"INR"}}</script>'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    async def check():
        async with httpx.AsyncClient(transport=transport) as client:
            item = SimpleNamespace(product_url="https://www.amazon.in/dp/B012345678", title="Phone 15 128GB", price=69999)
            return await verify_listing(item, client)
    assert asyncio.run(check())["status"] == "unavailable"
