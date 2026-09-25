### Web Crawler

This File contains the code for webcrawler that will be used in rag

<!-- running command -->

scrapy crawl rag_crawler

## every crawl invocation gets its own output/[<entity-slug>/]<run_id>/ folder
## (pages.jsonl, clean.jsonl, summary.json, blocked.jsonl), so old retrieved
## content from a previous crawl is never overwritten or appended over. A
## crawl that crashed/stopped mid-way (the Redis frontier still has pending
## URLs) resumes into the SAME run_id/files; a crawl started after the
## previous one fully finished (or a brand new seed/entity) gets a fresh
## run_id. reprocess/export_txt/clean default to the most recently modified
## run - pass --run <run_id> to target an older one instead.

## for resetting the uncrawled urls from redis use, this also clears all run
## history (output/**/*.jsonl) for a fresh crawl

scrapy reset

## regenerate output/clean.jsonl from output/pages.jsonl (raw crawled html/pdf text)
## use this after any fix to the extraction/normalization logic in pipelines.py,
## since it re-derives cleaned_content from source instead of re-cleaning already-cleaned text

scrapy reprocess

## export output/clean.jsonl into a single combined output/corpus.txt for RAG
## ingestion, with each page's prose broken back into real paragraphs
## (clean.jsonl stores it as one flattened line) so a RAG text splitter has
## real chunk boundaries to work with, and tables/comments rendered in their
## own clearly-labeled sections instead of blended into the prose. Can also be
## run from inside an output/[<entity>/]<run>/ folder directly - it'll use
## that folder instead of needing --entity/--run.

scrapy export_txt

## entity-focused crawl: instead of crawling the whole seed site, only follow/keep
## pages relevant to a specific entity. Only "entity" is required - "aliases" and
## "context" are both optional:
##   - aliases: alternate names for the entity itself (e.g. a nickname or
##     abbreviated form). Widens what counts as a name match.
##   - context: terms that disambiguate the entity (e.g. from another person/
##     company with the same name), such as employer, role, or location. If any
##     context terms are given, a page must mention the name/alias AND at least
##     one context term to count as relevant. If none are given, a name/alias
##     match alone is enough.
##
## output/pages.jsonl, clean.jsonl, corpus_bank.txt, summary.json and the Redis dedup
## set are all scoped under output/<entity-slug>/ so different entity crawls of the
## same seeds never intermix.

# entity name only - no aliases/context needed
scrapy crawl rag_crawler -a entity="John Smith"

# entity name + aliases and/or context, all optional and independent of each other
scrapy crawl rag_crawler -a entity="John Smith" -a aliases="J. Smith,Johnny Smith" -a context="CFO,Acme Corp"

## pass --entity to reset/reprocess/export_txt/clean to point them at the same
## output/<entity-slug>/ directory instead of the shared output/ one, and --run
## to reprocess/export_txt/clean to target a specific run instead of the latest:

scrapy reset --entity="John Smith"
scrapy export_txt --entity="John Smith"
scrapy export_txt --entity="John Smith" --run=20260908_120000_12345

## YouTube video pages get special handling instead of the generic HTML
## extraction (a video's title/description/comments read as player-UI chrome
## to a generic extractor, not real content):
##   - title/channel/description/etc. are read straight out of the page's own
##     embedded metadata - free, no API key needed.
##   - comments need the official YouTube Data API v3 (commentThreads.list).
##     Set the YOUTUBE_API_KEY environment variable (get a free key from
##     Google Cloud Console) - without it, video pages are still crawled and
##     stored, just without comments (logged, not an error).
##   - a YouTube seed URL in seed.txt, combined with -a entity=, also runs a
##     YouTube keyword search for the entity name (search.list) to discover
##     more relevant videos, instead of relying only on whatever's linked
##     from that one seed video. Needs the same YOUTUBE_API_KEY.
##
## search.list costs 100 quota units/call vs 1 for comments/video-details, so
## on the standard 10,000/day free quota that's ~100 searches/day - fine for
## one search per entity crawl, not something to run per-page.

$env:YOUTUBE_API_KEY = "your-api-key-here"   # PowerShell; use export on macOS/Linux
scrapy crawl rag_crawler -a entity="John Smith"   # seed.txt includes a youtube.com URL

## crawling login/subscription-gated sites (only for sites you already have
## legitimate access to - this does not solve CAPTCHAs or bypass access
## controls you don't have valid credentials for)
##
## Copy crawler/auth.example.json to crawler/auth.json (gitignored - never
## commit it) and add an entry per domain (from seed.txt) needing auth. Four
## methods - pick whichever matches the site:
##   - storage_state:    reuse an already-authenticated session (cookies +
##                        localStorage) exported from a real browser or from
##                        a prior playwright_login run's save_storage_state.
##                        No login flow runs at all.
##   - form_login:        plain HTML <form method=post> login (no JS needed).
##   - playwright_login:  JS-rendered login (SPA/React) - driven via a real
##                        browser: fills the fields, clicks submit, waits for
##                        a post-login element. Can optionally save the
##                        resulting session so future runs skip straight to
##                        storage_state instead of logging in every time.
##   - api_token:         injects an Authorization/API-key header on every
##                        request to the domain - no login flow needed.
##
## auth.json only ever references environment VARIABLE NAMES for credentials/
## tokens, never the secret values themselves - set those in your shell (or a
## local, gitignored .env) before running `scrapy crawl`. See
## crawler/auth.example.json for the full schema of all four methods.

scrapy crawl rag_crawler   # auth_config defaults to auth.json if present

## control panel (React + Tailwind frontend, FastAPI backend)
##
## Lets you launch crawls, watch them run, browse results (connections status,
## entity/run browser, paginated clean.jsonl viewer, blocked.jsonl viewer),
## and configure per-domain login/API-key auth - all without touching the
## CLI or hand-editing auth.json. Two processes, run from two terminals:

# terminal 1 - API (from crawler/, same place you'd run `scrapy crawl` from)
pip install -r requirements.txt
uvicorn webapi:app --reload 

# terminal 2 - frontend
cd frontend
npm install
npm run dev   # opens on http://localhost:5173, talks to the API on :8002

## frontend/.env.example documents VITE_API_URL if your API runs on a
## different port - copy it to frontend/.env and adjust.


==================
# Also fixed for .exe(Essensic Dynamic web pages)