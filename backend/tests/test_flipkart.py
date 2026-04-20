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


def test_clean_title_strips_numbering_prefix():
    assert FlipkartScraper().clean_title("1. Apple iPhone 15 (Blue, 128 GB)") == "Apple iPhone 15 (Blue, 128 GB)"


def test_clean_title_strips_rating_suffix():
    title = "Apple iPhone 15 (Blue, 128 GB) 4.6 2,74,016 Ratings & 9,564 Reviews"
    assert FlipkartScraper().clean_title(title) == "Apple iPhone 15 (Blue, 128 GB)"


def test_skip_card_marked_currently_unavailable():
    html = """
    <div data-id="oos">
      <a href="/apple-iphone-15-white/p/oos">
        <img alt="Apple iPhone 15 (White, 128 GB)" />
        <span>Currently unavailable</span>
      </a>
      <div>₹58,999</div>
    </div>
    """

    assert FlipkartScraper().parse_structural(html, "iphone 15") == []


def test_skip_card_with_notify_me_button():
    html = """
    <div data-id="oos">
      <a href="/apple-iphone-15-white/p/oos">
        <img alt="Apple iPhone 15 (White, 128 GB)" />
      </a>
      <button>Notify Me</button>
      <div>₹58,999</div>
    </div>
    """

    assert FlipkartScraper().parse_structural(html, "iphone 15") == []


def test_parse_structural_prefers_img_alt_over_card_text():
    html = Path("tests/fixtures/flipkart_iphone.html").read_text(encoding="utf-8")

    items = FlipkartScraper().parse_structural(html, "iphone 15")

    titles = [item.title for item in items]
    assert "Apple iPhone 15 (Blue, 128 GB)" in titles
    assert all("Add to Compare" not in title for title in titles)
    assert all("Currently unavailable" not in title for title in titles)


def test_clean_title_returns_none_for_pure_ui_text():
    assert FlipkartScraper().clean_title("Add to Compare") is None
