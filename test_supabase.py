from datetime import datetime
from supabase_db import upsert_products

sample = [{
    "product_url": "https://example.com/test-product-1",
    "platform": "amazon",
    "keyword": "test",
    "title": "Test Product",
    "price": 999,
    "rating": 4.2,
    "reviews_count": 123,
    "scraped_at": datetime.utcnow()
}]

n = upsert_products(sample)
print("Inserted/Updated:", n)