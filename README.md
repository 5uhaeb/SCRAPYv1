# SCRAPYv2

SCRAPYv2 is a price-tracking scraper with a FastAPI backend, static Vercel frontend, MongoDB storage, optional Streamlit dashboard, scheduled scraping, price history, and Telegram price-drop alerts.

## Architecture

```text
                 GitHub Actions cron
                         |
                         v
Vercel static UI --> FastAPI on Render -----> MongoDB Atlas
                         |                         |
                         |                         +--> products
                         |                         +--> price_history
                         |                         +--> watchlist
                         |
                         +--> Site adapters
                         |     vijaysales, flipkart, amazon_in,
                         |     croma, reliance_digital, gsmarena
                         |
                         +--> Upstash Redis dedup cache
                         +--> Playwright renderer for JS-heavy sites
                         +--> Telegram Bot API alerts
```

## Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn api:app --reload
```

MongoDB indexes are created automatically before the first write. Products use a unique `(source_platform, product_url)` index.

## Environment Variables

Copy `.env.example` to `.env` and set:

```env
MONGODB_URI=
MONGODB_DB=scrapyv1
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
VERCEL_FRONTEND_ORIGIN=
SCRAPE_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

`SCRAPE_API_KEY` protects only `/v2/scrape*` endpoints. Public GET endpoints stay open. Leave it unset for local development if you want scrape calls without a key.

## API

Legacy compatibility:

```http
POST /scrape
```

Accepts the old `{ "site": "vijaysales", "keywords": [...], "pages": 2 }` payload.

V2 async API:

```http
GET  /v2/scrapers
POST /v2/scrape
POST /v2/scrape/all
GET  /v2/scrape/{job_id}
GET  /v2/products
GET  /v2/products/cheapest?keyword=iphone+15
GET  /v2/products/compare?keyword=iphone+15
GET  /v2/products/{product_hash}/history
POST /v2/watch
```

## Add a New Adapter

Scaffold a new adapter:

```powershell
python scripts/add_site.py myshop
```

Then edit `backend/scrapers/sites/myshop.py` and register it in `backend/scrapers/registry.py`:

```python
from scrapers.sites.myshop import MyshopScraper

SCRAPERS = {
    "myshop": MyshopScraper,
}
```

Adapters usually subclass `BaseScraper`, implement `build_search_url()`, and use `JsonLdScraper` first before CSS fallbacks.

## Deployment

Render:

- Use `render.yaml`.
- Set `rootDir: backend`.
- Add MongoDB, Telegram, and `SCRAPE_API_KEY` env vars in Render. URL deduplication uses a MongoDB TTL collection.
- Start command: `uvicorn api:app --host 0.0.0.0 --port $PORT`.

Vercel:

- `vercel.json` serves `frontend/**` as static files.
- Set the Backend URL in the UI to your Render URL.
- If Render has `SCRAPE_API_KEY`, enter it in the UI when running scrapes.

GitHub Actions:

- Set repository secret `SCRAPE_API_KEY`.
- Set repository variable `SCRAPE_API_URL` to the deployed Render URL.
- Edit `backend/tracked_keywords.json` to change scheduled scrape keywords.

## Tests

```powershell
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Tests use fixtures and mocks only. They do not call real stores, MongoDB, or Telegram.

## Import existing Supabase data

Export `products`, `price_history`, and `watchlist` as JSON from Supabase, then run:

```bash
python scripts/import_supabase_export.py --products products.json --history price_history.json --watchlist watchlist.json
```

The importer is repeat-safe for products and watchlist entries. Price-history exports should be imported once.
