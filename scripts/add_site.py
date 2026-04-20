import re
import sys
from pathlib import Path


TEMPLATE = '''from urllib.parse import quote_plus, urljoin

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper, Item
from scrapers.jsonld_adapter import JsonLdScraper


class {class_name}Scraper(BaseScraper):
    name = "{site_name}"
    base_url = "https://www.example.com"
    requires_js = False

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return f"{{self.base_url}}/search?q={{quote_plus(keyword)}}&page={{page}}"

    def parse(self, html: str, keyword: str) -> list[Item]:
        jsonld_items = JsonLdScraper(self.name, self.base_url).parse(html, keyword)
        if jsonld_items:
            return jsonld_items

        tree = HTMLParser(html)
        items: list[Item] = []
        # TODO: Replace these generic selectors with site-specific product cards.
        for card in tree.css("article, .product, [data-product]"):
            title_el = card.css_first("h2, h3, .title")
            link_el = card.css_first("a[href]")
            price_el = card.css_first(".price, [data-price]")
            if not title_el or not link_el:
                continue
            href = link_el.attributes.get("href")
            title = " ".join(title_el.text(separator=" ").split())
            if not href or not title:
                continue
            items.append(
                Item(
                    title=title,
                    price=self.normalize_price(price_el.text() if price_el else None),
                    product_url=urljoin(self.base_url, href),
                    source_platform=self.name,
                    keyword=keyword,
                    raw={{"source": "css"}},
                )
            )
        return items
'''


def snake_case(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    if not value or not re.match(r"^[a-z]", value):
        raise ValueError("Site name must start with a letter and contain letters, numbers, dashes, or underscores.")
    return value


def class_name(site_name: str) -> str:
    return "".join(part.capitalize() for part in site_name.split("_"))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/add_site.py myshop")
        return 1

    site_name = snake_case(sys.argv[1])
    target = Path("backend") / "scrapers" / "sites" / f"{site_name}.py"
    if target.exists():
        print(f"Refusing to overwrite existing adapter: {target}")
        return 1

    target.write_text(TEMPLATE.format(site_name=site_name, class_name=class_name(site_name)), encoding="utf-8")
    print(f"Created {target}")
    print("Register it in backend/scrapers/registry.py before use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
