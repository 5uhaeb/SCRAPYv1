import asyncio
import json
import logging
import random
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

import extruct
from selectolax.parser import HTMLParser, Node

from scrapers.base import BaseScraper, BlockedError, Item, product_hash_for
from scrapers.dedup import dedup_cache

logger = logging.getLogger(__name__)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


class FlipkartScraper(BaseScraper):
    name = "flipkart"
    base_url = "https://www.flipkart.com"
    requires_js = True
    max_products = 40
    stock_block_patterns = (
        "currently unavailable",
        "out of stock",
        "sold out",
        "notify me",
    )
    title_skip_patterns = (
        "currently unavailable",
        "add to compare",
        "out of stock",
        "sold out",
        "notify me",
        "ratings",
        "reviews",
        "₹",
        "â‚¹",
    )

    def build_search_url(self, keyword: str, page: int = 1) -> str:
        return f"{self.base_url}/search?q={quote_plus(keyword)}&page={page}"

    async def fetch(self, url: str) -> str:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                extra_http_headers={"accept-language": "en-IN,en;q=0.9"},
            )
            page = await context.new_page()
            try:
                async def route_handler(route):
                    if route.request.resource_type in {"font", "image", "media"}:
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", route_handler)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except PlaywrightTimeoutError as exc:
                    html = await page.content()
                    if html and await self._products_rendered(page):
                        return html
                    path = self._save_debug_html(html)
                    raise BlockedError(f"Flipkart navigation timed out for {url}; saved HTML to {path}") from exc
                await asyncio.sleep(random.uniform(2, 5))
                if not await self._products_rendered(page):
                    html = await page.content()
                    path = self._save_debug_html(html)
                    raise BlockedError(f"Flipkart products did not render; saved HTML to {path}")
                return await page.content()
            finally:
                await context.close()
                await browser.close()

    async def _products_rendered(self, page) -> bool:
        selectors = [
            "div[data-id]",
            "a[href*='/p/']",
            "script[type='application/ld+json']",
        ]
        for selector in selectors:
            try:
                await page.wait_for_selector(selector, timeout=5000)
                return True
            except Exception:
                continue
        return False

    async def run(
        self,
        keywords: list[str],
        pages: int = 2,
        force: bool = False,
        mark_immediately: bool = True,
    ) -> list[Item]:
        collected: list[Item] = []
        self.last_fetched_urls = []
        for keyword in keywords:
            keyword_items: list[Item] = []
            fetched_urls: list[str] = []
            for page in range(1, pages + 1):
                if page > 1:
                    await asyncio.sleep(random.uniform(3, 7))

                url = self.build_search_url(keyword, page)
                if not force and await dedup_cache.seen(url):
                    continue

                items: list[Item] = []
                for attempt in range(2):
                    try:
                        html = await self.fetch(url)
                        self.last_fetched_urls.append(url)
                        items = self.parse(html, keyword)
                        break
                    except BlockedError as exc:
                        logger.warning("%s", exc)
                        if attempt == 0:
                            await asyncio.sleep(random.uniform(3, 7))
                        else:
                            continue

                keyword_items.extend(items)
                if items:
                    fetched_urls.append(url)

            keyword_items = self.apply_relevance_filters(keyword_items, keyword)
            for item in keyword_items:
                item.product_hash = item.product_hash or product_hash_for(item.title, item.source_platform)
            collected.extend(keyword_items)
            if mark_immediately:
                for url in fetched_urls:
                    await dedup_cache.mark_seen(url, ttl=900)

        return self._dedupe_items(collected)

    def parse(self, html: str, keyword: str) -> list[Item]:
        for parser in (self.parse_jsonld, self.parse_structural):
            items = parser(html, keyword)
            if items:
                return items[: self.max_products]

        path = self._save_debug_html(html)
        raise BlockedError(f"Flipkart parse returned no products; saved HTML to {path}")

    def parse_jsonld(self, html: str, keyword: str) -> list[Item]:
        data = extruct.extract(
            html,
            base_url=self.base_url,
            syntaxes=["json-ld"],
            uniform=True,
        )
        products: list[dict[str, Any]] = []
        for entry in data.get("json-ld", []):
            for node in self._flatten(entry):
                if self._type_is(node, "ItemList"):
                    products.extend(self._products_from_item_list(node))
                elif self._type_is(node, "Product"):
                    products.append(node)

        items = []
        seen = set()
        for product in products:
            item = self._item_from_product(product, keyword)
            if not item or item.product_url in seen:
                continue
            seen.add(item.product_url)
            items.append(item)
            if len(items) >= self.max_products:
                break
        return items

    def parse_structural(self, html: str, keyword: str) -> list[Item]:
        tree = HTMLParser(html)
        items: list[Item] = []
        seen = set()
        for anchor in tree.css("a[href*='/p/']"):
            href = anchor.attributes.get("href")
            if not href:
                continue
            product_url = urljoin(self.base_url, href)
            if product_url in seen:
                continue

            container = self._nearest_product_container(anchor)
            if self._is_out_of_stock(container):
                continue
            title = self._title_from_anchor(anchor)
            price = self._price_near(anchor, container)
            if not title or len(title) <= 10 or price is None:
                continue

            image = self._image_near(anchor, container)
            items.append(
                Item(
                    title=title,
                    price=price,
                    product_url=product_url,
                    image_url=urljoin(self.base_url, image) if image else None,
                    source_platform=self.name,
                    keyword=keyword,
                    raw={"source": "structural_css"},
                )
            )
            seen.add(product_url)
            if len(items) >= self.max_products:
                break
        return items

    def normalize_price(self, raw: str | float | int | None) -> float | None:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        match = re.search(r"(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)", str(raw), flags=re.IGNORECASE)
        return super().normalize_price(match.group(1)) if match else None

    def _item_from_product(self, product: dict[str, Any], keyword: str) -> Item | None:
        title = product.get("name") or product.get("title")
        offers = product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = product.get("price") or offers.get("price") or offers.get("lowPrice")
        product_url = product.get("url") or offers.get("url")
        if not title or not product_url:
            return None

        image = product.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl")

        return Item(
            title=str(title).strip(),
            price=self.normalize_price(price),
            currency=str(offers.get("priceCurrency") or product.get("priceCurrency") or "INR").upper(),
            product_url=urljoin(self.base_url, str(product_url)),
            image_url=urljoin(self.base_url, str(image)) if image else None,
            source_platform=self.name,
            keyword=keyword,
            raw={"source": "jsonld", "product": product},
        )

    def _products_from_item_list(self, item_list: dict[str, Any]) -> list[dict[str, Any]]:
        products = []
        for entry in item_list.get("itemListElement") or []:
            for node in self._flatten(entry):
                if self._type_is(node, "Product"):
                    products.append(node)
                elif isinstance(node.get("item"), dict) and self._type_is(node["item"], "Product"):
                    products.append(node["item"])
        return products

    def _flatten(self, value: Any) -> list[dict[str, Any]]:
        out = []
        if isinstance(value, list):
            for item in value:
                out.extend(self._flatten(item))
        elif isinstance(value, dict):
            out.append(value)
            if value.get("@graph"):
                out.extend(self._flatten(value["@graph"]))
            if value.get("item"):
                out.extend(self._flatten(value["item"]))
            if value.get("itemListElement"):
                out.extend(self._flatten(value["itemListElement"]))
        return out

    def _type_is(self, node: dict[str, Any], expected: str) -> bool:
        value = node.get("@type") or node.get("type")
        if isinstance(value, list):
            return any(str(item).lower() == expected.lower() for item in value)
        return str(value).lower() == expected.lower()

    def _nearest_product_container(self, node: Node) -> Node:
        current = node
        for _ in range(6):
            if current.parent is None:
                break
            current = current.parent
            text = current.text(separator=" ")
            if "₹" in text or current.css_first("img"):
                return current
        return node

    def clean_title(self, raw: str | None) -> str | None:
        title = self._clean_text(raw or "")
        title = re.sub(r"^\d+\.?\s*", "", title)
        title = re.sub(
            r"\b\d(?:\.\d)?\s+[\d,]+\s+Ratings?\s*&\s*[\d,]+\s+Reviews?.*$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        title = re.sub(r"\b\d(?:\.\d)?\s+[\d,]+\s+Ratings?.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\b\d+%\s*off\b.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\bsave\s*(?:₹|â‚¹|rs\.?)\s*[\d,]+.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\bupto\s*(?:₹|â‚¹|rs\.?)\s*[\d,]+.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\b(exchange|bank)\s+offer.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\.{3,}$", "", title).strip()
        title = self._clean_text(title)
        if any(pattern in title.lower() for pattern in self.title_skip_patterns):
            return None
        if len(title) > 150:
            title = title[:150].rstrip()
        if len(title) < 10 or not re.search(r"[A-Za-z]", title):
            return None
        return title

    def _title_from_anchor(self, anchor: Node) -> str | None:
        img = anchor.css_first("img[alt]")
        if img:
            title = self.clean_title(img.attributes.get("alt"))
            if title:
                return title

        text = self._clean_text(anchor.text(separator=" "))
        if self._looks_clean_title(text):
            return self.clean_title(text)

        for node in anchor.css("*"):
            text = self._clean_text(node.text(separator=" "))
            if self._looks_clean_title(text):
                return self.clean_title(text)
        return None

    def _price_near(self, anchor: Node, container: Node) -> float | None:
        for node in [anchor, container]:
            price = self._first_price(node.text(separator=" "))
            if price is not None:
                return price
        current = container
        for _ in range(3):
            if current.parent is None:
                break
            current = current.parent
            price = self._first_price(current.text(separator=" "))
            if price is not None:
                return price
        return None

    def _first_price(self, text: str) -> float | None:
        match = re.search(r"(?:₹|â‚¹)\s*([\d,]+(?:\.\d+)?)", text or "")
        return self.normalize_price(match.group(1)) if match else None

    def _image_near(self, anchor: Node, container: Node) -> str | None:
        for node in [anchor, container]:
            img = node.css_first("img")
            if img:
                return img.attributes.get("src") or img.attributes.get("data-src")
        return None

    def _clean_text(self, value: str) -> str:
        return " ".join((value or "").split()).strip()

    def _looks_clean_title(self, value: str) -> bool:
        text = self._clean_text(value)
        lowered = text.lower()
        if len(text) < 20 or len(text) > 200:
            return False
        if any(pattern in lowered for pattern in self.title_skip_patterns):
            return False
        if re.search(r"\b\d(?:\.\d)?\s+[\d,]+\s+Ratings?\b", text, flags=re.IGNORECASE):
            return False
        return bool(re.search(r"[A-Za-z]", text))

    def _is_out_of_stock(self, node: Node) -> bool:
        text = self._clean_text(node.text(separator=" ")).lower()
        return any(pattern in text for pattern in self.stock_block_patterns)

    def _save_debug_html(self, html: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        path = Path(tempfile.gettempdir()) / f"blocked_{self.name}_{timestamp}.html"
        path.write_text(html or "", encoding="utf-8")
        return str(path)
