from urllib.parse import quote_plus, urljoin

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper, Item


class GSMArenaScraper(BaseScraper):
    name = "gsmarena"
    base_url = "https://www.gsmarena.com"
    requires_js = False
    apply_price_filter = False

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return f"{self.base_url}/results.php3?sQuickSearch=yes&sName={quote_plus(keyword)}"

    def parse(self, html: str, keyword: str) -> list[Item]:
        tree = HTMLParser(html)
        items: list[Item] = []
        for link in tree.css("div.makers ul li a, div.section-body ul li a"):
            href = link.attributes.get("href")
            if not href:
                continue
            title = " ".join(link.text(separator=" ").split())
            if not title:
                strong = link.css_first("strong")
                title = " ".join(strong.text(separator=" ").split()) if strong else ""
            if not title:
                continue
            img = link.css_first("img")
            image = img.attributes.get("src") if img else None
            items.append(
                Item(
                    title=title[:250],
                    price=None,
                    product_url=urljoin(self.base_url, href),
                    image_url=urljoin(self.base_url, image) if image else None,
                    source_platform=self.name,
                    keyword=keyword,
                    raw={"source": "gsmarena_list"},
                )
            )
        return items
