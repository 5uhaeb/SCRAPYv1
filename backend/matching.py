import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from scrapers.base import Item


COLOR_WORDS = {
    "black",
    "white",
    "blue",
    "green",
    "red",
    "yellow",
    "pink",
    "purple",
    "silver",
    "gold",
    "grey",
    "gray",
    "graphite",
    "titanium",
    "natural",
    "midnight",
    "starlight",
}


@dataclass
class ProductGroup:
    normalized_title: str
    items: list[dict[str, Any]] = field(default_factory=list)
    min_price: float | None = None

    def add(self, item: Item | dict[str, Any]) -> None:
        row = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        self.items.append(row)
        price = row.get("price")
        if price is not None:
            price = float(price)
            self.min_price = price if self.min_price is None else min(self.min_price, price)

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalized_title": self.normalized_title,
            "min_price": self.min_price,
            "items": sorted(self.items, key=lambda row: float(row.get("price") or 10**18)),
        }


def normalize_title(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"\((?:renewed|refurbished|open box|unboxed)[^)]+\)", " ", text)
    text = re.sub(r"\b(?:renewed|refurbished|open box|unboxed)\b", " ", text)
    text = re.sub(r"\b\d+\s?(?:gb|tb|mb)\b", " ", text)
    text = re.sub(r"\b\d+\s?(?:mah|w|hz|inch|inches|cm)\b", " ", text)
    text = re.sub(r"\b(?:ram|rom|storage|ssd|hdd)\b", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [token for token in text.split() if token not in COLOR_WORDS]
    if "iphone" in tokens:
        tokens = [token for token in tokens if token != "apple"]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def match_products(items: list[Item | dict[str, Any]], threshold: int = 85) -> list[ProductGroup]:
    groups: list[ProductGroup] = []
    for item in items:
        title = item.title if hasattr(item, "title") else item.get("title", "")
        normalized = normalize_title(title)
        if not normalized:
            continue

        match = None
        best_score = 0
        for group in groups:
            score = fuzz.token_sort_ratio(normalized, group.normalized_title)
            if score >= threshold and score > best_score:
                match = group
                best_score = score

        if match is None:
            match = ProductGroup(normalized_title=normalized)
            groups.append(match)
        match.add(item)

    return sorted(groups, key=lambda group: group.min_price if group.min_price is not None else 10**18)
