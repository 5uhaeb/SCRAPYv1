from pathlib import Path

from scrapers.jsonld_adapter import JsonLdScraper


def test_jsonld_adapter_extracts_product():
    html = Path("tests/fixtures/product_jsonld.html").read_text(encoding="utf-8")

    items = JsonLdScraper("fixture_shop", "https://example.com").parse(html, "iphone 15")

    assert len(items) == 1
    assert items[0].title == "Apple iPhone 15 128GB Black"
    assert items[0].price == 69900.0
    assert items[0].currency == "INR"
    assert items[0].product_url == "https://example.com/product/iphone-15"
    assert items[0].source_platform == "fixture_shop"
