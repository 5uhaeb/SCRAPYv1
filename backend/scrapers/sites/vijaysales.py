import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper, Item
from scrapers.jsonld_adapter import JsonLdScraper


class VijaySalesScraper(BaseScraper):
    name = "vijaysales"
    base_url = "https://www.vijaysales.com"
    requires_js = True

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        url = f"{self.base_url}{self._category_path(keyword)}"
        return f"{url}?page={page}" if page > 1 else url

    def parse(self, html: str, keyword: str) -> list[Item]:
        jsonld_items = JsonLdScraper(self.name, self.base_url).parse(html, keyword)
        if jsonld_items:
            return jsonld_items

        tree = HTMLParser(html)
        items: list[Item] = []
        seen = set()
        for card in tree.css("div.product-card"):
            link = card.css_first("a.product-card__link[href], a[href*='/p/']")
            if not link:
                continue
            href = link.attributes.get("href")
            if not href:
                continue
            product_url = urljoin(self.base_url, href)
            if product_url in seen:
                continue
            seen.add(product_url)

            title_el = card.css_first(".product-card__title")
            title = self._clean_title(title_el.text(separator=" ") if title_el else link.text(separator=" "))
            if len(title) < 5:
                continue
            if not self._matches_keyword(title, keyword):
                continue

            image = None
            img = card.css_first("img")
            if img:
                image = img.attributes.get("src") or img.attributes.get("data-src")

            price_el = card.css_first("[data-price], .discountedPrice, .clp-price-wrapper, .product-card__price")
            price_source = price_el.attributes.get("data-price") if price_el and price_el.attributes.get("data-price") else None
            if not price_source:
                price_source = price_el.text(separator=" ") if price_el else card.text(separator=" ")

            items.append(
                Item(
                    title=title[:250],
                    price=self._extract_price(price_source),
                    product_url=product_url,
                    image_url=urljoin(self.base_url, image) if image else None,
                    source_platform=self.name,
                    keyword=keyword,
                    raw={"source": "css"},
                )
            )
        return items

    def _category_path(self, keyword: str) -> str:
        normalized = self._normalize(keyword)
        if "iphone" in normalized:
            return "/c/iphones"
        return "/c/mobiles"

    def _extract_price(self, raw: str | None) -> float | None:
        if not raw:
            return None
        match = re.search(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)", raw, flags=re.IGNORECASE)
        if match:
            return self.normalize_price(match.group(1))
        return self.normalize_price(raw)

    def _matches_keyword(self, title: str, keyword: str) -> bool:
        title_norm = self._normalize(title)
        keyword_norm = self._normalize(keyword)
        if not keyword_norm:
            return True
        if keyword_norm in title_norm:
            return True
        title_joined = title_norm.replace(" ", "")
        keyword_joined = keyword_norm.replace(" ", "")
        return keyword_joined in title_joined

    def _clean_title(self, raw: str) -> str:
        title = " ".join((raw or "").split())
        title = re.sub(r"^compare\s+", "", title, flags=re.IGNORECASE).strip()
        half = len(title) // 2
        if len(title) % 2 == 0 and title[:half].strip() == title[half:].strip():
            title = title[:half].strip()
        words = title.split()
        half_words = len(words) // 2
        if len(words) % 2 == 0 and words[:half_words] == words[half_words:]:
            title = " ".join(words[:half_words])
        return title

    def _normalize(self, value: str) -> str:
        text = (value or "").lower()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()
