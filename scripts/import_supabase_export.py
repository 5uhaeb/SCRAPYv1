"""Import Supabase JSON exports into MongoDB.

Export each Supabase table as JSON, then run:
  python scripts/import_supabase_export.py --products products.json \
    --history price_history.json --watchlist watchlist.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from mongodb_db import _collection, _serialize_row, add_watch, ensure_indexes  # noqa: E402
from pymongo import UpdateOne  # noqa: E402


def load_rows(path: str | None) -> list[dict]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("data") or payload.get("rows") or []
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return payload


def parse_dates(row: dict) -> dict:
    result = dict(row)
    for key in ("scraped_at", "created_at", "updated_at"):
        if isinstance(result.get(key), str):
            try:
                result[key] = datetime.fromisoformat(result[key].replace("Z", "+00:00"))
            except ValueError:
                pass
    result.pop("id", None)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Supabase JSON exports into MongoDB")
    parser.add_argument("--products")
    parser.add_argument("--history")
    parser.add_argument("--watchlist")
    args = parser.parse_args()
    ensure_indexes()

    products = [_serialize_row(row) for row in load_rows(args.products)]
    if products:
        operations = [
            UpdateOne(
                {"source_platform": row.get("source_platform"), "product_url": row["product_url"]},
                {"$set": row},
                upsert=True,
            )
            for row in products
            if row.get("product_url")
        ]
        if operations:
            _collection("products").bulk_write(operations, ordered=False)

    history = [parse_dates(row) for row in load_rows(args.history)]
    if history:
        _collection("price_history").insert_many(history, ordered=False)

    watches = load_rows(args.watchlist)
    for row in watches:
        add_watch(row["product_hash"], float(row["target_price"]), row.get("chat_id"))

    print(f"Imported {len(products)} products, {len(history)} prices, and {len(watches)} watches.")


if __name__ == "__main__":
    main()
