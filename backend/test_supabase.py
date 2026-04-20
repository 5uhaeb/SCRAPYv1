from datetime import datetime, timezone

from supabase_db import upsert_products


def main():
    sample = [
        {
            "product_url": "https://example.com/test-product-1",
            "source_platform": "manual_smoke",
            "keyword": "test",
            "title": "Test Product",
            "price": 999,
            "currency": "INR",
            "scraped_at": datetime.now(timezone.utc),
        }
    ]

    n = upsert_products(sample)
    print("Inserted/Updated:", n)


if __name__ == "__main__":
    main()
