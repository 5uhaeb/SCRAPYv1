from urllib.parse import quote_plus, urljoin

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper, Item
from scrapers.jsonld_adapter import JsonLdScraper


class VijaySalesScraper(BaseScraper):
    name = "vijaysales"
    base_url = "https://www.vijaysales.com"
    requires_js = True

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        url = f"{self.base_url}/search/{quote_plus(keyword)}"
        return f"{url}?page={page}" if page > 1 else url

    def parse(self, html: str, keyword: str) -> list[Item]:
        jsonld_items = JsonLdScraper(self.name, self.base_url).parse(html, keyword)
        if jsonld_items:
            return jsonld_items

        tree = HTMLParser(html)
        items: list[Item] = []
        seen = set()
        for link in tree.css("a[href*='/p/']"):
            href = link.attributes.get("href")
            if not href:
                continue
            product_url = urljoin(self.base_url, href)
            if product_url in seen:
                continue
            seen.add(product_url)

            title = " ".join(link.text(separator=" ").split())
            parent_text = " ".join((link.parent.text(separator=" ") if link.parent else title).split())
            if not title:
                title = parent_text
            if len(title) < 5:
                continue

            image = None
            img = link.css_first("img")
            if img:
                image = img.attributes.get("src") or img.attributes.get("data-src")

            items.append(
                Item(
                    title=title[:250],
                    price=self.normalize_price(parent_text),
                    product_url=product_url,
                    image_url=urljoin(self.base_url, image) if image else None,
                    source_platform=self.name,
                    keyword=keyword,
                    raw={"source": "css"},
                )
            )
        return items
