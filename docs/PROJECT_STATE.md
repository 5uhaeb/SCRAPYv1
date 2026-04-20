## 1. Current State (One Paragraph)

SCRAPYv1 is working end-to-end for the deployed Vercel frontend, Render FastAPI backend,
Supabase persistence, Upstash Redis dedup, async job polling, API-key-protected scrape
starts, and price history writes. The live, verified adapters are Flipkart and VijaySales;
Flipkart is the most stable current adapter after Playwright hardening, title cleanup,
out-of-stock skipping, keyword filtering, and price sanity filtering. The registered but not
fully verified adapters are Amazon.in, Croma, Reliance Digital, and GSMArena. The latest
commit is 709add5, locally verified with `python -m pytest` on 2026-04-20; the latest
deployment smoke evidence in this session verified frontend-to-backend scrape/results flow
before 709add5, so redeploy and smoke-test 709add5 before treating it as production-verified.

## 2. Architecture Snapshot

```text
                    GitHub Actions cron
                .github/workflows/scheduled_scrape.yml
                         POST /v2/scrape/all
                                  |
                                  v
+------------------+      +-----------------------------+      +------------------+
| Vercel frontend  | ---> | Render FastAPI backend      | ---> | Supabase Postgres |
| frontend/*.html  | CORS | api.py + Playwright/HTTPX   |      | products/history  |
+------------------+      +-----------------------------+      +------------------+
                                  |
                                  v
                         Upstash Redis dedup
                         scrapyv1:seen_urls:*

       Optional Streamlit dashboard
       dashboard.py -------------------------------> Supabase Postgres
```

| File | Responsibility |
|------|----------------|
| `backend/api.py` | FastAPI routes, API-key auth, async jobs, polling, timeouts |
| `backend/supabase_db.py` | Supabase client, products upsert, price_history insert |
| `backend/scrapers/base.py` | `Item`, `BaseScraper`, filters, price parsing, `BlockedError` |
| `backend/scrapers/playwright_fetcher.py` | Shared Playwright context for base JS fetches |
| `backend/scrapers/dedup.py` | Upstash Redis seen-url cache and health check |
| `backend/scrapers/sites/*.py` | Per-site adapters and parsing strategies |
| `frontend/index.html` | Static Vercel UI, job start/polling, results rendering |
| `.github/workflows/scheduled_scrape.yml` | Six-hour cron calling deployed `/v2/scrape/all` |

## 3. What Was Built (Chronological)

### Phase 0-2: Foundation (migrations, base scraper)

- commit 41e1c29 - async FastAPI v2 routes, matching, scheduling, alerts foundation.
- Added products dedup migration, price_history append-only table, and watchlist table.
- Added Supabase upsert on `(source_platform, product_url)` and price_history inserts.

### Phase 3-4: Multi-site adapters

- commit 41e1c29 - registered multi-site scraper framework and adapters.
- Added JSON-LD/microdata adapter path for reusable product extraction.
- Added adapters for VijaySales, Flipkart, Amazon.in, Croma, Reliance Digital, GSMArena.

### Phase 5-7: UI, scheduling, alerts

- commit fe48aa8 - frontend async scrape UI and job polling.
- commit cdb7f06 - Streamlit dashboard price history and comparison views.
- commit 88e9bae - README, pytest suite, and `scripts/add_site.py` scaffold CLI.
- commit 41e1c29 - GitHub Actions scheduled scrape and Telegram alert plumbing.

### Phase 8+: Production hardening

- commit eea646d - install Playwright for Render scrapes.
- commit 9460e2b - install Chromium system dependencies on Render.
- commit 02f563d - deploy backend with Docker for Playwright dependencies.
- commit 02c84d2 - add product `image_url` migration.
- commit 3513bd4 - force product `price` to numeric.
- commit 61cd8ff - support legacy `platform` column while migrating to `source_platform`.
- commit 81bd719 - add `force=true` and reduce Redis dedup poisoning risk.
- commit 4cff89f - Flipkart Playwright adapter with defensive parsing.
- commit bfc8665 - clean Flipkart titles and skip out-of-stock products.
- commit 888b214 - keyword and price sanity filters in `BaseScraper`.
- commit 0d11e9e - apply relevance filters to Flipkart custom run loop.
- commit 4551606 - filter Flipkart results per keyword instead of per page.
- commit f191f54 - harden Flipkart Playwright fetch on Render.
- commit e67b593 - apply cartoon-hybrid frontend design system.
- commit e93ef22 - fix Vercel-to-Render CORS and frontend API URL default.
- commit 5dc9bae - add per-scraper timeout and safer frontend defaults.
- commit 709add5 - soften timeout to 420s/disableable and add running status loader.

## 4. What's Working (Verified)

- Render `/health`: returned HTTP 200 on 2026-04-20 with DB and Redis true.
- `/v2/scrapers`: registered adapters were visible in the frontend and backend health data.
- API-key auth for `/v2/scrape`: local `.env` key successfully started Render jobs.
- Async polling: `/v2/scrape/{job_id}` returned running, complete, and failed states.
- Flipkart scrape: verified 2026-04-20 after hardening. `iphone 15` saved 12 rows and
  `samsung s24` saved 24 rows from Render jobs with no errors.
- Flipkart relevance filtering: verified 2026-04-20 on `oneplus 12`; low-price accessories
  were removed and minimum current row was a real OnePlus 12R at INR 33,160.
- Flipkart title cleanup: verified latest visible rows did not include "Currently
  unavailable" or "Add to Compare" text.
- VijaySales scrape through frontend: verified 2026-04-20 by UI result set for `iphone 16`,
  including VijaySales rows such as Apple iPhone 16 at INR 58,190.
- Supabase upsert + price_history: verified during smoke testing after `image_url` and
  service-role key fixes; products and price_history received rows.
- Frontend-to-backend flow: verified on Vercel UI 2026-04-20. API connected, protected scrape
  started, job completed, cheapest cards and scraped results table rendered.
- CORS for actual Vercel origin: fixed in e93ef22 by adding `https://scrap-yv1.vercel.app`.
- Local tests: `python -m pytest` passed 21 tests on 2026-04-20 after 709add5.

## 5. What's Broken or Fragile

- **709add5 deploy not smoke-verified**: tests pass locally, but latest commit still needs
  Render and Vercel deployment verification. Fix: deploy both and run one Flipkart scrape.
- **Amazon.in adapter**: implemented but unverified against live Amazon bot defenses. Fix:
  run isolated `amazon_in` smoke test, inspect block/CAPTCHA behavior, likely add Playwright.
- **Croma adapter**: implemented but not proven reliable; could return 0 silently if selectors
  drift or static HTML lacks product cards. Fix: add debug HTML capture and fixture test.
- **Reliance Digital adapter**: SPA path is registered with `requires_js=True`, but selectors
  are generic and unverified. Fix: inspect rendered HTML and add wait selectors.
- **VijaySales category URL builder**: uses `/c/iphones` for iPhone and `/c/mobiles` for
  other queries, not `/search/{keyword}`. Fix: confirm current site behavior and adjust.
- **VijaySales result pollution risk**: frontend cheapest cards showed an old VijaySales
  iPhone accessory for `iphone 17`. Fix: clean stale rows and strengthen adapter filtering.
- **Dedup ordering not fully centralized**: `BaseScraper.run()` can still mark seen inside
  adapter runs when `mark_immediately=True`; API path uses `mark_immediately=False`. Fix:
  move all marking to post-DB-save only and remove adapter-level early marking.
- **Redis namespace coarse**: all URLs use `scrapyv1:seen_urls:*` with one TTL. Fix: split
  search URLs and product URLs into separate namespaces and TTLs.
- **Cheapest endpoint is naive**: it orders by price for keyword match and can surface stale
  accessories from older rows. Fix: filter by recent `scraped_at` and apply price sanity.
- **Keyword filter weak on short/model tokens**: tokens under 4 chars are ignored, so
  `macbook air m3` only filters by `macbook`. Fix: add domain-specific model-token logic.

## 6. Known Limitations (Not Bugs)

- Render free tier can cold start slowly after inactivity.
- Playwright scrapes on Render are slower than static HTTPX scrapes.
- Per-scraper timeout defaults to 420 seconds; set `SCRAPER_TIMEOUT_SECONDS=0` to disable.
- Upstash Redis free tier has command limits; high-frequency cron can burn quota.
- Frontend read endpoints are public; only `/scrape*` endpoints require `x-api-key`.
- Telegram alerts are optional and assume env-based bot/chat config, not full user accounts.
- GSMArena has `apply_price_filter=False` because it is not a comparable e-commerce source.
- Product matching uses `rapidfuzz`, not embeddings; cross-site grouping is approximate.

## 7. Environment State

| Variable | Required by | Set in |
|----------|-------------|--------|
| `SUPABASE_URL` | backend Supabase client | Render, `.env` locally |
| `SUPABASE_KEY` | backend Supabase client, should be service_role | Render, `.env` locally |
| `SCRAPE_API_KEY` | protected scrape endpoints, GitHub Actions | Render, GitHub secret, `.env` locally |
| `UPSTASH_REDIS_REST_URL` | Redis dedup | Render, `.env` locally |
| `UPSTASH_REDIS_REST_TOKEN` | Redis dedup | Render, `.env` locally |
| `VERCEL_FRONTEND_ORIGIN` | optional CORS override | Render optional; hardcoded origins exist |
| `SCRAPER_TIMEOUT_SECONDS` | optional per-scraper timeout control | Render optional |
| `TELEGRAM_BOT_TOKEN` | optional Telegram alerts | Render optional, currently unverified |
| `TELEGRAM_CHAT_ID` | optional Telegram alerts/watchlist default | Render optional, currently unverified |

`SCRAPE_API_URL` is a GitHub Actions variable, not a secret. It should point at
`https://scrapyv1.onrender.com`. The workflow falls back to
`https://scrapy-api.onrender.com`, which appears stale for the current Render service.

## 8. Database State

### products

- Expected columns: `id`, `source_platform`, `product_url`, `title`, `price`, `currency`,
  `image_url`, `keyword`, `product_hash`, `scraped_at`, `raw`.
- Legacy compatibility: some deployments may still have `platform`; migrations keep it
  nullable and backfilled from `source_platform`.
- UNIQUE index: `(source_platform, product_url)` where both values are not null.
- INDEX: `(keyword, source_platform, scraped_at DESC)`.
- `rating` and `reviews_count` are not present in repo migrations; verify in Supabase before
  relying on them.

### price_history

- Columns: `id`, `product_hash`, `price`, `currency`, `source_platform`, `scraped_at`.
- Append-only intent: one row per saved product per scrape/upsert cycle.
- INDEX: `(product_hash, scraped_at)`.

### watchlist

- Columns: `id`, `product_hash`, `chat_id`, `target_price`, `created_at`.
- Used by `/watch` and Telegram target-price alerts.

RLS/policy state is not visible from the repo. Operationally, backend writes use the Supabase
service_role key and products/price_history writes were verified after the key swap.

## 9. Resume Plan (Pick Up Here)

1. **Smoke-test latest 709add5 deployment** (10 min)
   - Deploy latest to Render and Vercel.
   - Run frontend scrape: `flipkart`, keyword `iphone 15`, pages `1`.
   - Expected: job completes, status loader stops, saved_count greater than 0.
   - Verify: Render `/health` returns 200 and Vercel badge says API connected.

2. **Fix GitHub Actions fallback URL** (5 min)
   - File: `.github/workflows/scheduled_scrape.yml`.
   - Change fallback from `https://scrapy-api.onrender.com` to
     `https://scrapyv1.onrender.com`.
   - Commit and push. Run workflow manually once.

3. **Clean stale accessory rows** (10 min)
   - In Supabase, inspect:
     `SELECT source_platform, keyword, title, price FROM products WHERE price < 10000;`
   - Delete clear accessories for phone keywords after confirming titles.
   - Do not delete `price_history` unless intentionally resetting historical data.

4. **Harden cheapest endpoint** (30 min)
   - File: `backend/supabase_db.py`.
   - In `cheapest_products`, filter to recent rows or add a sane minimum via median logic.
   - Add unit test with accessory row and real phone rows.
   - Smoke-test frontend cheapest cards for `iphone 16`.

5. **Diagnose VijaySales URL builder and filtering** (30-60 min)
   - File: `backend/scrapers/sites/vijaysales.py`.
   - Confirm whether `/search/{keyword}` works better than `/c/iphones` and `/c/mobiles`.
   - Add or update tests for `build_search_url` and accessory filtering.
   - Smoke-test `vijaysales` with `iphone 15`, pages `1`, `force=true`.

6. **Post-save dedup cleanup** (30 min)
   - File: `backend/scrapers/base.py` and custom adapters.
   - Ensure `mark_seen()` only happens after successful DB upsert from `backend/api.py`.
   - Remove or avoid adapter-level `mark_immediately=True` paths where possible.
   - Split TTLs: search URLs 15 minutes, product URLs 1 hour.

7. **Croma isolated debug pass** (30-60 min)
   - Run `/v2/scrape` with `sites=["croma"]`, keyword `macbook`, pages `1`, `force=true`.
   - Check Render logs for parse count and BlockedError.
   - If 0 results, save blocked/debug HTML and create fixture-driven parser test.

8. **Reliance Digital isolated debug pass** (1-2 hours)
   - Run `/v2/scrape` with `sites=["reliance_digital"]`, keyword `iphone 15`.
   - Add Playwright wait selector for actual product card elements.
   - Add fixture test before changing broad selectors.

9. **Amazon.in adapter work** (4-8 hours)
   - Treat as the hardest remaining adapter.
   - Start with live HTML capture and Render logs.
   - If blocked, move to Playwright with realistic headers, locale, timezone, and slow rate.
   - Consider Product Advertising API if scraping is unreliable.

10. **Scraper run observability** (1-2 hours)
    - Add `scraper_runs` table: scraper, keyword, saved_count, errored, started_at,
      finished_at, error.
    - Write one row per scraper inside `_run_job`.
    - Expose `/v2/health/scrapers` with last-run status and seven-day success rates.

## 10. Open Questions / Decisions Needed

- Do we need residential proxies for Amazon, or should Amazon use the official Product
  Advertising API instead?
- Should GSMArena data live outside `products`, since it is spec/reference data and not a
  normal price source?
- Should the vanilla frontend remain single-file, or move to Alpine.js/HTMX for state?
- Is the Streamlit dashboard still worth maintaining now that the Vercel frontend works?
- When should cross-site matching move beyond `rapidfuzz` to embeddings or curated rules?
- Should cheapest comparisons ignore products older than a freshness window?

## 11. Gotchas (Painful Lessons)

- **Supabase anon key cannot write through restrictive RLS**: use service_role from the
  backend. If you see row-level security policy violations, the backend key is wrong.
- **Render can deploy the wrong entrypoint**: `render.yaml` should run the Docker backend
  serving `api.py`; stale `main.py` fixes previously caused confusion.
- **GitHub PAT needs workflow scope for `.github/workflows/**`**: otherwise push is rejected
  when workflow files change.
- **PowerShell curl quoting is easy to break**: use `Invoke-RestMethod` with a hashtable body
  or load `SCRAPE_API_KEY` from `.env` in a PowerShell script.
- **Vercel origin spelling matters for CORS**: actual app is `https://scrap-yv1.vercel.app`,
  not `https://scrapyv1.vercel.app`.
- **Flipkart class names are not stable**: prefer JSON-LD, `a[href*="/p/"]`, and `img[alt]`
  over obfuscated class names.
- **Flipkart `img[alt]` is the cleanest title source**: anchor/card text includes UI chrome
  such as "Add to Compare" and availability badges.
- **Flipkart Render timeouts are not always CAPTCHA**: slow navigation and blocked assets can
  look like scraper failure; block images/fonts/media and retry once.
- **Redis dedup is annoying during development**: use `force=true` for smoke tests after
  selector or schema fixes.
- **Dirty titles break price_history continuity**: clean titles before hashing, or the same
  product gets multiple `product_hash` values.
- **Cheapest cards can show old junk rows**: upserts do not delete products that filters now
  reject. Clean stale rows or filter cheapest by freshness/sanity.

## 12. Deploy Checklist

- [ ] `python -m pytest` passes locally.
- [ ] `git status` clean on `main`.
- [ ] Latest commit matches `origin/main`.
- [ ] Render env vars are present.
- [ ] Vercel has deployed `frontend/**` from latest commit.
- [ ] Supabase migrations are run if schema changed.
- [ ] After backend deploy: `GET /health` returns 200.
- [ ] After backend deploy: `GET /v2/scrapers` lists registered adapters.
- [ ] Smoke-test one known-good scraper with `force=true`.
- [ ] Check Vercel frontend badge says API connected.
