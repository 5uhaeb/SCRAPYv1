import os
from typing import Any

import httpx
from dotenv import load_dotenv

from mongodb_db import add_watch as save_watch
from mongodb_db import last_price, watchlist_matches

load_dotenv()

DROP_THRESHOLD = 0.05


async def evaluate_price_alerts(items: list[Any]) -> list[dict[str, Any]]:
    alerts = []
    for item in items:
        row = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        price = row.get("price")
        product_hash = row.get("product_hash")
        if price is None or not product_hash:
            continue

        previous = _last_price(product_hash)
        watch_matches = _watchlist_matches(product_hash, float(price))
        if previous and previous > 0:
            drop = (previous - float(price)) / previous
            if drop >= DROP_THRESHOLD:
                alerts.append(
                    {
                        "kind": "price_drop",
                        "product_hash": product_hash,
                        "title": row.get("title"),
                        "old_price": previous,
                        "new_price": float(price),
                        "drop_pct": round(drop * 100, 2),
                        "product_url": row.get("product_url"),
                    }
                )

        for watch in watch_matches:
            alerts.append(
                {
                    "kind": "target_price",
                    "product_hash": product_hash,
                    "title": row.get("title"),
                    "target_price": watch.get("target_price"),
                    "new_price": float(price),
                    "product_url": row.get("product_url"),
                    "chat_id": watch.get("chat_id"),
                }
            )

    sent = []
    for alert in alerts:
        if await send_telegram_alert(alert):
            sent.append(alert)
    return sent


async def send_telegram_alert(alert: dict[str, Any]) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    default_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    chat_id = alert.get("chat_id") or default_chat_id
    if not token or not chat_id:
        return False

    text = _format_alert(alert)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        )
        return response.status_code < 400


def add_watch(product_hash: str, target_price: float, chat_id: str | None = None) -> dict[str, Any]:
    return save_watch(product_hash, target_price, chat_id)


def _last_price(product_hash: str) -> float | None:
    return last_price(product_hash)


def _watchlist_matches(product_hash: str, price: float) -> list[dict[str, Any]]:
    return watchlist_matches(product_hash, price)


def _format_alert(alert: dict[str, Any]) -> str:
    title = alert.get("title") or alert.get("product_hash")
    url = alert.get("product_url") or ""
    if alert.get("kind") == "target_price":
        return (
            f"Target price hit: {title}\n"
            f"Now: INR {alert['new_price']:,.0f} | Target: INR {float(alert['target_price']):,.0f}\n"
            f"{url}"
        )
    return (
        f"Price drop: {title}\n"
        f"Was: INR {alert['old_price']:,.0f} | Now: INR {alert['new_price']:,.0f} "
        f"({alert['drop_pct']}% down)\n{url}"
    )
