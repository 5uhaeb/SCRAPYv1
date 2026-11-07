"""Best-effort, public-page Buyhatke verification.

Buyhatke does not document a public history API for this use case. We read only
visible/structured public page data and never manufacture historical points.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

ALLOWED_STORES = {"amazon.in", "flipkart.com", "croma.com", "vijaysales.com", "reliancedigital.in"}


def _price(value) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match and float(match.group()) > 0 else None


def _capacities(title: str) -> set[str]:
    return {f"{amount}{unit.lower()}" for amount, unit in re.findall(r"\b(\d+)\s*(GB|TB)\b", title, re.I)}


def buyhatke_url(product_url: str) -> str | None:
    parsed = urlsplit(product_url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme != "https" or host not in ALLOWED_STORES or parsed.username or parsed.password:
        return None
    if parsed.port not in (None, 443):
        return None
    return "https://buyhatke.com/" + product_url


def _objects(value):
    if isinstance(value, list):
        for part in value:
            yield from _objects(part)
    elif isinstance(value, dict):
        yield value
        for key in ("@graph", "itemListElement", "item"):
            if key in value:
                yield from _objects(value[key])


def parse_public_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {"price": None, "history": [], "title": None}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            nodes = _objects(json.loads(script.string or script.get_text()))
            for node in nodes:
                types = node.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if "Product" not in types:
                    continue
                result["title"] = node.get("name")
                offers = node.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict):
                    currency = offers.get("priceCurrency", "INR")
                    if currency == "INR":
                        result["price"] = _price(offers.get("price") or offers.get("lowPrice"))
        except (ValueError, TypeError, AttributeError):
            continue
    # A chart is useful only when its public markup includes explicit dated prices.
    for row in soup.select("[data-date][data-price]"):
        date = row.get("data-date", "")
        price = _price(row.get("data-price"))
        try:
            observed = datetime.fromisoformat(date.replace("Z", "+00:00"))
        except ValueError:
            continue
        if price and 2000 <= observed.year <= datetime.now(timezone.utc).year:
            result["history"].append({"scraped_at": observed.isoformat(), "price": price, "source": "buyhatke"})
    result["history"] = sorted(result["history"], key=lambda point: point["scraped_at"])
    return result


async def verify_listing(item, client: httpx.AsyncClient) -> dict:
    url = buyhatke_url(item.product_url)
    if not url:
        return {"status": "unsupported", "price": None, "history": [], "url": None}
    try:
        response = await client.get(url, follow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("No public product page")
        page = parse_public_page(response.text)
        if not page["title"] or fuzz.token_sort_ratio(str(page["title"]).lower(), item.title.lower()) < 75 or (
            _capacities(str(page["title"])) and _capacities(item.title)
            and not _capacities(str(page["title"])) & _capacities(item.title)
        ):
            return {"status": "unavailable", "price": None, "history": [], "url": url}
        price = page["price"]
        if price is None and not page["history"]:
            state = "unavailable"
        elif price is None or item.price is None:
            state = "history_only"
        else:
            state = "matched" if abs(float(item.price) - price) / max(float(item.price), price) <= 0.03 else "different"
        return {"status": state, "price": price, "history": page["history"], "url": url}
    except (httpx.HTTPError, ValueError):
        return {"status": "unavailable", "price": None, "history": [], "url": url}


async def verify_listings(items, limit: int = 24) -> list[dict]:
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "Mozilla/5.0 (compatible; PriceIntelligence/1.0)"}) as client:
        async def one(item):
            async with semaphore:
                return await verify_listing(item, client)
        return await asyncio.gather(*(one(item) for item in items[:limit]))
