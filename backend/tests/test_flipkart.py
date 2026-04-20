from pathlib import Path

import pytest

from scrapers.base import BlockedError
from scrapers.sites.flipkart import FlipkartScraper


def test_parse_jsonld_extracts_item_list_products():
    html = Path("tests/fixtures/flipkart_iphone.html").read_text(encoding="utf-8")

    items = FlipkartScraper().parse_jsonld(html, "iphone 15")

    assert len(items) == 2
    assert items[0].title == "Apple iPhone 15 (128 GB, Black)"
    assert items[0].price == 58999.0
    assert items[0].product_url == "https://www.flipkart.com/apple-iphone-15-black/p/itmabc"
    assert items[1].price == 59999.0


def test_parse_structural_extracts_product_cards():
    html = """
    <html>
      <body>
        <div data-id="abc">
          <a href="/apple-iphone-15-black/p/itmabc">
            <div>Apple iPhone 15 (128 GB, Black)</div>
            <img src="https://img.example/black.jpg" />
          </a>
          <div><span>Deal price</span><strong>₹58,999</strong></div>
        </div>
      </body>
    </html>
    """

    items = FlipkartScraper().parse_structural(html, "iphone 15")

    assert len(items) == 1
    assert items[0].title == "Apple iPhone 15 (128 GB, Black)"
    assert items[0].price == 58999.0
    assert items[0].product_url == "https://www.flipkart.com/apple-iphone-15-black/p/itmabc"
    assert items[0].image_url == "https://img.example/black.jpg"


def test_parse_empty_raises_blocked_error():
    with pytest.raises(BlockedError):
        FlipkartScraper().parse("<html><body>No products</body></html>", "iphone 15")
