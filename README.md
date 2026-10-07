# SCRAPYv1

A Python product-price tracker with a FastAPI API and static dashboard. It normalizes store listings, stores observations in MongoDB, and compares prices across stores.

## What it does

- Runs asynchronous scrape jobs with polling, timeouts and bounded concurrency.
- Parses JSON-LD and store HTML; uses Playwright when browser rendering is needed.
- Stores current listings, price history and target-price watches.
- Groups likely equivalent products with Rapidfuzz and sends optional Telegram alerts.
- Includes fixture tests and a six-hour GitHub Actions schedule.

Six adapters are registered. Registration does not guarantee current store compatibility: selectors, stock availability and blocking can change. GSMArena is a specifications source, not a normal shopping price source.

## Stack and architecture

FastAPI, Pydantic, HTTPX, Requests, BeautifulSoup, selectolax, Playwright, MongoDB/PyMongo and Rapidfuzz. The optional Streamlit dashboard has separate dependencies.

```text
Static frontend / scheduler -> FastAPI -> site adapter -> normalized listing
                                                -> MongoDB products + history
                                                -> optional Telegram alert
```

`backend/api.py` owns HTTP routes and job state. `backend/scrapers/` holds the shared parsing/fetching code and distinct site adapters. `mongodb_db.py` owns persistence and indexes; `alerts.py` checks prior prices before new observations are saved. URL deduplication uses a MongoDB TTL collection. Redis and Supabase are not current runtime dependencies.

## Run locally

Use Python 3.13 (the version used by CI), then from the repository root:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
Copy-Item .env.example backend/.env
backend/.venv/Scripts/python -m playwright install chromium
cd backend
.venv/Scripts/python -m uvicorn api:app --reload
```

On macOS/Linux use `backend/.venv/bin/python` and `cp .env.example backend/.env` instead. In a second terminal, run `python -m http.server 3000 --directory frontend` from the root and open http://localhost:3000. API docs are at http://127.0.0.1:8000/docs.

## Environment

| Variable | Purpose |
| --- | --- |
| `MONGODB_URI` | Server-only Atlas connection string; required for persistence |
| `MONGODB_DB` | Dedicated database, default `scrapyv1` |
| `VERCEL_FRONTEND_ORIGIN` | Additional allowed frontend origin |
| `SCRAPE_API_KEY` | Protects scrape starts when set; always required for legacy scrapes and watch writes |
| `PUBLIC_SCRAPE_ENABLED` | Set `true` to allow throttled public scrape starts alongside the operator key; defaults to `false` |
| `PUBLIC_SCRAPE_SHARED_COOLDOWN` | Set `true` behind Render's proxy to share the public cooldown across callers without trusting supplied forwarding headers |
| `PUBLIC_SCRAPE_COOLDOWN_SECONDS` | Public scrape cooldown, default 30 |
| `MAX_CONCURRENT_JOBS` | Process job limit, default 2 |
| `SCRAPER_TIMEOUT_SECONDS` | Per-adapter timeout, default 420; 0 disables it |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional Telegram delivery settings |

Never put operator keys in static assets. Private API requests send `x-api-key`; the public browser demo uses the throttled public scrape mode. Proxy headers must be trusted by the server, rather than taken directly from arbitrary callers.

## API and tests

`POST /v2/scrape` and `/v2/scrape/all` return 202 with a job ID. Poll `GET /v2/scrape/{id}`. Product reads use `/v2/products`, `/cheapest`, `/compare` and `/{hash}/history`; `POST /v2/watch` is operator-protected. The deprecated `/scrape` contract remains for existing callers, with an operator key and restricted GSMArena URLs.

```powershell
cd backend
.venv/Scripts/python -m pytest -q
```

Tests cover fixture parsing, prices, relevance, matching, API validation/access control and alert logic without calling stores, MongoDB or Telegram.

## Deployment and limits

Render's blueprint builds `backend/Dockerfile`, including Chromium and its system libraries. It runs as a non-root user and listens on `PORT`. Root `/` is process liveness; `/health` reports dependency flags. Vercel serves `frontend/` through the existing static configuration. The deployed frontend API address is defined once in `frontend/index.html`; update it there if hosting changes.

Set GitHub Actions variable `SCRAPE_API_URL` and secret `SCRAPE_API_KEY` for scheduled scraping. The workflow fails on HTTP errors, failed jobs or polling timeout. The test workflow runs pytest on pushes and pull requests.

Job metadata and cooldowns are process-local: run one API worker. Recent completed jobs are bounded, and a restart removes job status. Products persist independently. Product/history writes are not a single transaction, title changes can fragment hashes, and comparison matching is approximate. Live store reliability, Telegram delivery and Docker runtime must be checked in the deployment environment; local tests do not prove them.

For the optional dashboard, install `pip install -r requirements-dashboard.txt` from the root, then run `streamlit run dashboard.py`. Its requirements include the backend parsers plus three visualization packages. Keep this tool local or behind operator access: it can run scrapers and write to MongoDB. Legacy CLI scripts and the one-time Supabase JSON importer remain available; keep backups and import history only once.

## Engineering lessons

- Browser rendering and static parsing need separate timeout/resource handling.
- Dedup should follow successful persistence, so failed writes can be retried.
- Async endpoints must not block on synchronous database drivers.
- Mock and fixture tests catch parser and authorization regressions without depending on live stores.
