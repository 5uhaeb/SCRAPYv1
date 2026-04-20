# SCRAPYv2

SCRAPYv2 is a price-tracking scraper with a FastAPI backend, static Vercel frontend, Supabase storage, optional Streamlit dashboard, scheduled scraping, price history, and Telegram price-drop alerts.

## Architecture

```text
                 GitHub Actions cron
                         |
                         v
Vercel static UI --> FastAPI on Render -----> Supabase Postgres
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

Run the SQL in `backend/migrations/001_dedup.sql` in the Supabase SQL editor before scraping with v2 endpoints.

## Environment Variables

Copy `.env.example` to `.env` and set:

```env
SUPABASE_URL=
SUPABASE_KEY=
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
- Add Supabase, Upstash, Telegram, and `SCRAPE_API_KEY` env vars in Render.
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

Tests use fixtures and mocks only. They do not call real stores, Supabase, Redis, or Telegram.
