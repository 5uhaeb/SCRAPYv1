from typing import Any
from urllib.parse import urljoin

import extruct

from scrapers.base import BaseScraper, Item


class JsonLdScraper(BaseScraper):
    """Generic Product schema extractor for e-commerce pages."""

    name = "jsonld"
    base_url = ""
    requires_js = False

    def __init__(self, source_platform: str = "jsonld", base_url: str = ""):
        super().__init__()
        self.source_platform = source_platform
        self.base_url = base_url

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return self.base_url

    def parse(self, html: str, keyword: str) -> list[Item]:
        data = extruct.extract(
            html,
            base_url=self.base_url or None,
            syntaxes=["json-ld", "microdata"],
            uniform=True,
        )
        candidates = []
        for bucket in ("json-ld", "microdata"):
            for entry in data.get(bucket, []):
                candidates.extend(self._flatten(entry))

        items: list[Item] = []
        for entry in candidates:
            if not self._is_product(entry):
                continue
            item = self._entry_to_item(entry, keyword)
            if item:
                items.append(item)
        return items

    def _entry_to_item(self, entry: dict[str, Any], keyword: str) -> Item | None:
        title = entry.get("name") or entry.get("headline")
        if isinstance(title, list):
            title = title[0] if title else None
        if not title:
            return None

        offers = entry.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
        currency = offers.get("priceCurrency") or entry.get("priceCurrency") or "INR"
        product_url = entry.get("url") or offers.get("url")
        if not product_url:
            return None

        image = entry.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl")

        return Item(
            title=str(title).strip(),
            price=self.normalize_price(price),
            currency=str(currency or "INR").upper(),
            product_url=urljoin(self.base_url, str(product_url)),
            image_url=urljoin(self.base_url, str(image)) if image else None,
            source_platform=self.source_platform,
            keyword=keyword,
            raw=entry,
        )

    def _flatten(self, value: Any) -> list[dict[str, Any]]:
        out = []
        if isinstance(value, list):
            for item in value:
                out.extend(self._flatten(item))
        elif isinstance(value, dict):
            out.append(value)
            graph = value.get("@graph")
            if graph:
                out.extend(self._flatten(graph))
            items = value.get("itemListElement")
            if items:
                out.extend(self._flatten(items))
            item = value.get("item")
            if item:
                out.extend(self._flatten(item))
        return out

    def _is_product(self, entry: dict[str, Any]) -> bool:
        type_value = entry.get("@type") or entry.get("type")
        if isinstance(type_value, list):
            return any(str(item).lower() == "product" for item in type_value)
        return str(type_value).lower() == "product"
