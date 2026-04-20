from urllib.parse import quote_plus, urljoin

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper, Item
from scrapers.jsonld_adapter import JsonLdScraper


class RelianceDigitalScraper(BaseScraper):
    name = "reliance_digital"
    base_url = "https://www.reliancedigital.in"
    requires_js = True

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return f"{self.base_url}/search?q={quote_plus(keyword)}&page={page}"

    def parse(self, html: str, keyword: str) -> list[Item]:
        jsonld_items = JsonLdScraper(self.name, self.base_url).parse(html, keyword)
        if jsonld_items:
            return jsonld_items

        tree = HTMLParser(html)
        items: list[Item] = []
        for card in tree.css("div[class*='product'], li[class*='product']"):
            title_el = card.css_first("p[class*='title'], div[class*='title'], h3, h2")
            link_el = card.css_first("a[href]")
            price_el = card.css_first("span[class*='price'], div[class*='price']")
            if not title_el or not link_el:
                continue
            href = link_el.attributes.get("href")
            title = " ".join(title_el.text(separator=" ").split())
            if not href or not title or len(title) < 5:
                continue
            img = card.css_first("img")
            image = img.attributes.get("src") or img.attributes.get("data-src") if img else None
            items.append(
                Item(
                    title=title,
                    price=self.normalize_price(price_el.text() if price_el else None),
                    product_url=urljoin(self.base_url, href),
                    image_url=urljoin(self.base_url, image) if image else None,
                    source_platform=self.name,
                    keyword=keyword,
                    raw={"source": "css"},
                )
            )
        return items
