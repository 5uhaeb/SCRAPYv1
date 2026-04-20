from urllib.parse import quote_plus, urljoin

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper, Item
from scrapers.jsonld_adapter import JsonLdScraper


class AmazonInScraper(BaseScraper):
    name = "amazon_in"
    base_url = "https://www.amazon.in"
    requires_js = False

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return f"{self.base_url}/s?k={quote_plus(keyword)}&page={page}"

    def parse(self, html: str, keyword: str) -> list[Item]:
        jsonld_items = JsonLdScraper(self.name, self.base_url).parse(html, keyword)
        if jsonld_items:
            return jsonld_items

        tree = HTMLParser(html)
        items: list[Item] = []
        for card in tree.css("div.s-result-item[data-component-type='s-search-result']"):
            title_el = card.css_first("h2 a span")
            link_el = card.css_first("h2 a[href]")
            price_el = card.css_first("span.a-price span.a-offscreen, span.a-price-whole")
            if not title_el or not link_el:
                continue
            href = link_el.attributes.get("href")
            title = " ".join(title_el.text(separator=" ").split())
            if not href or not title:
                continue
            img = card.css_first("img.s-image")
            image = img.attributes.get("src") if img else None
            items.append(
                Item(
                    title=title,
                    price=self.normalize_price(price_el.text() if price_el else None),
                    product_url=urljoin(self.base_url, href),
                    image_url=image,
                    source_platform=self.name,
                    keyword=keyword,
                    raw={"source": "css"},
                )
            )
        return items
