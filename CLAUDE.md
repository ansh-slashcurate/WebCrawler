# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project layout

Two independent apps in one repo:

- `crawler/` — the actual crawler: a Scrapy project (`crawler/crawler/`) plus `webapi.py`, a FastAPI control-panel backend. Run all `scrapy`/`uvicorn`/`python` commands from inside `crawler/`, not the repo root.
- `frontend/` — a Vite + React 19 + Tailwind 4 control panel UI that talks to `webapi.py`.

## Commands

All from `crawler/` unless noted, with `.venv` activated (`crawler/.env` is auto-loaded by `settings.py` for secrets — never commit it).

```
scrapy crawl rag_crawler                                    # full-site crawl of seed.txt
scrapy crawl rag_crawler -a entity="John Smith"              # entity-focused crawl (see below)
scrapy crawl rag_crawler -a entity="John Smith" -a aliases="J. Smith,Johnny Smith" -a context="CFO,Acme Corp"
scrapy reset [--entity="John Smith"] [--keep-output]          # clear Redis frontier/dedup + output/**/*.jsonl
scrapy reprocess [--entity=...] [--run=<run_id>] [--min-length N]  # re-derive clean.jsonl from pages.jsonl after an extraction/normalization fix
scrapy export_txt [--entity=...] [--run=<run_id>]             # combine clean.jsonl into output/.../corpus.txt for RAG ingestion
scrapy clean [--entity=...] [--run=<run_id>]                  # backfill: re-normalize an existing clean.jsonl (doesn't re-extract; reprocess does)

# control panel (2 terminals)
uvicorn webapi:app --reload --port 8002       # from crawler/
cd frontend && npm install && npm run dev     # http://localhost:5173, talks to :8002

# frontend lint
cd frontend && npm run lint                   # oxlint
```

`reprocess`/`export_txt`/`clean` default to the most-recently-modified run under `output/[<entity-slug>/]`; pass `--run <run_id>` to target an older one. Requires a running Redis at `REDIS_URL` (`redis://localhost:6379/0` by default) — the request frontier and dedup filter both live there (`scrapy_redis`), not on local disk, so a crashed crawl resumes automatically on the next `scrapy crawl` instead of restarting.

There is no automated test suite in this repo currently.

## Architecture

### Crawl pipeline (Scrapy)

Single spider, `WebsiteSpider` (`crawler/spiders/crawler.py`, name `rag_crawler`). Key flow per URL:

1. **Plain fetch first.** Every request starts through the ordinary (non-Playwright) download path — now `StealthDownloadHandler` (`curl_cffi_handler.py`), which impersonates a real Chrome TLS/JA4 fingerprint via `curl_cffi` (`stealth_http.py`) instead of Twisted's default client, specifically so a request isn't flagged before headers are even read. One `curl_cffi.Session` is kept per domain for cookie continuity.
2. **Challenge detection** (`challenge.py`) runs before any content extraction, on the raw response — a page must not be scored/stored just because it happens to contain extractable text if it's actually a Cloudflare/hCaptcha/DataDome/etc. interstitial. Markers are split into `_STRONG_CHALLENGE_MARKERS` (interstitial-only phrases, always trusted) and `_WEAK_CHALLENGE_MARKERS` (e.g. `g-recaptcha`, `hcaptcha.com` — these also show up as ordinary widget markup on real content pages, so they only count on a response under `_WEAK_MARKER_MAX_BODY_LEN` chars, thin enough to plausibly *be* the challenge itself).
3. **Playwright escalation** happens only when needed, and only for that one URL (`dont_retry=True`, `_playwright_retry_meta`): once on challenge detection (covers auto-resolving JS-only interstitials like Cloudflare's "checking your browser"), and once when the plain fetch's extracted text is under `MIN_EXTRACTED_CHARS` (covers client-rendered pages). A failed plain response never escalates every other URL on that host — only itself.
4. YouTube video URLs get special-cased extraction (`ytpipeline.py`) instead of generic trafilatura, since a video's title/description read as player-UI chrome to a generic extractor — parsed straight from the page's embedded metadata (no API key), with comments needing `YOUTUBE_API_KEY` (Data API v3). A YouTube seed + `-a entity=` also triggers a `search.list` keyword search for more relevant videos.
5. Item yields into the pipeline chain (`settings.ITEM_PIPELINES`, order matters — a `DropItem` anywhere in this chain means the page never reaches `pages.jsonl`/`clean.jsonl`):
   `ContentDedupPipeline` (100, sha256 of raw html against a Redis set, scoped per entity+run_id) → `YoutubePipeline` (120) → `NormalizationPipeline` (150, trafilatura extraction + `normalize_text` + table extraction → `cleaned_content`) → `EntityRelevancePipeline` (175, only active for entity crawls — re-scores against `cleaned_content` rather than trusting the spider's own pre-extraction score) → `StoragePipeline` (200, writes `pages.jsonl`/`clean.jsonl`, then a `summary.json` with a write-count reconciliation check on `close_spider`).

Extraction/normalization logic (trafilatura call + `normalize_text` + `extract_tables`) is intentionally duplicated between `NormalizationPipeline.process_item` (live crawl) and `commands/reprocess.py` (regenerate from already-crawled `pages.jsonl`) — a change to extraction must be made in both places, or `scrapy reprocess` keeps producing stale output. `commands/clean.py` only re-normalizes already-extracted text, so it doesn't need extraction changes.

### Output layout

Every crawl gets its own `output/[<entity-slug>/]<run_id>/` folder (`pages.jsonl` raw, `clean.jsonl` RAG-ready, `blocked.jsonl` challenge/block log, `summary.json`) so old content is never overwritten. `run_id` is assigned in `WebsiteSpider._init_run()`: a crawl that crashed mid-way (pending URLs still in the Redis frontier) resumes into the *same* `run_id`; a crawl started after the previous one fully drained gets a fresh one (and clears the Redis dupefilter, so it re-visits every seed-reachable URL rather than silently skipping pages an earlier, unrelated run already saw).

### Per-domain auth (`auth.py`, `auth.json` — gitignored, copy from `auth.example.json`)

Four methods, resolved per-domain and injected as request/context meta by `_auth_request_meta`/`_build_login_request` in the spider: `storage_state` (load an exported browser session, no login flow), `form_login` (two-hop GET+POST), `playwright_login` (drives a real browser through selectors, can persist `save_storage_state`), `api_token` (header injected on every request by `ApiTokenAuthMiddleware`, `middlewares.py`). `auth.json` only ever references environment variable *names* for secrets, never values — this is explicitly not a CAPTCHA/access-control bypass, only for sites the crawler already has legitimate credentials for.

### Entity-focused crawling (`entity.py`)

When `-a entity=` is passed, `EntityQuery` scores text against name/alias regexes plus optional context terms (context terms disambiguate a common name — if any are given, a page needs a name/alias hit *and* a context hit to count as relevant). Used twice, against different text: the spider scores raw extracted text pre-storage for frontier priority/pruning (stop following a branch after `max_irrelevant_streak` consecutive irrelevant pages, even if `max_depth` hasn't been hit), while `EntityRelevancePipeline` re-scores the fully cleaned `cleaned_content` as the actual storage gate.

### Control panel (`webapi.py` + `frontend/`)

FastAPI backend exposing crawl lifecycle (`POST /api/crawls` launches `scrapy crawl` as a subprocess, tracked by token), run/entity browsing (`/api/entities`, `/api/runs`, paginated `/api/runs/{entity}/{run}/pages`, `/api/runs/{entity}/{run}/blocked`), and auth-domain CRUD (`/api/auth-domains`, reads/writes `auth.json` and its referenced env-var names). The React frontend (`frontend/src/components/`) is a thin client over this API — `NewCrawlForm`/`LiveJobs` for launching/watching crawls, `RunsBrowser`/`RunDetail` for browsing output, `AuthManager` for auth.json, `ConnectionsPanel` for Redis/API health.
