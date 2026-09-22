# Scrapy settings for crawler project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://docs.scrapy.org/en/latest/topics/settings.html
#     https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://docs.scrapy.org/en/latest/topics/spider-middleware.html

import os
import datetime
from dotenv import load_dotenv

# auth.py/Readme both describe secrets as coming from "a local, gitignored
# .env loaded before `scrapy crawl`" - this is what actually does that
# loading. Anchored to this file's own location (not the process's cwd) so it
# finds crawler/.env correctly regardless of which directory a command is
# invoked from. Only fills in variables not already set in the real
# environment (load_dotenv's default), so a value exported in the shell/CI
# still wins over the .env file.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BOT_NAME = "crawler"

SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"
COMMANDS_MODULE = "crawler.commands"

ADDONS = {}

# Write every crawl's log (including our per-page/link timing lines) to one
# file per calendar day under logs/, in addition to the console - every crawl
# started that day appends into the same file instead of each getting its own.
# LOG_FILE_APPEND must be set explicitly: this Scrapy version defaults LOG_FILE
# to overwrite ("w") mode, which would otherwise erase the day's earlier crawls
# every time a new one starts. (Two crawl processes writing concurrently at the
# exact same moment can still interleave their lines - fine for this project's
# scale, but worth knowing if you ever run entity crawls in true parallel.)
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"crawl_{datetime.datetime.now():%Y%m%d}.log")
LOG_FILE_APPEND = True
LOG_LEVEL = "INFO"
LOG_STDOUT = True

# Scrapy's default LogFormatter dumps the full item (including PageItems' raw
# html field) into "Scraped from"/"Dropped: ..." log lines - this swaps in a
# formatter that redacts html, since page source belongs in pages.jsonl, not the log
LOG_FORMATTER = "crawler.logformatter.CrawlerLogFormatter"


# Scrapy's default UA ("Scrapy/x.y (+https://scrapy.org)") self-identifies as
# a scraping library, which is an instant, trivial match for basic WAF
# blocklists before anything else about the request is even considered. This
# is a generic, current desktop Chrome UA instead - not impersonating any
# specific verified bot (that would fail a reverse-DNS check and is a
# different, more deceptive thing), just not gratuitously announcing "I am a
# scraper" the way a real browser wouldn't either. Kept for Playwright's own
# requests and as documentation of which Chrome build/OS this crawl presents
# as; the plain (non-Playwright) fetch path now goes through curl_cffi (see
# crawler.stealth_http, IMPERSONATE) instead of Scrapy's own HTTP client, and
# gets this same Chrome/124/Windows identity from there - a spoofed UA header
# alone (with no matching TLS handshake) is what curl_cffi actually fixes.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# By default Scrapy silently drops non-2xx responses before they reach the
# spider callback. Bot-challenge/block pages typically respond 403/429/503,
# so without this the spider would never even see them to detect and log -
# they'd just look like plain failed requests.
HTTPERROR_ALLOWED_CODES = [403, 429, 503]

# Concurrency and throttling settings
# Keep ordinary HTTP work parallel across domains, while the per-domain cap
# prevents either Scrapy or Playwright from hammering one host.
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1

# Disabled: the plain (non-Playwright) fetch path now runs through
# curl_cffi (see crawler.stealth_http), which keeps one real cookie jar per
# domain inside its own Session objects for session continuity. Scrapy's
# CookiesMiddleware knows nothing about that jar, so leaving it enabled would
# only add a second, stale, in-memory-per-run Cookie header on top of - or
# instead of - the one curl_cffi is actually maintaining. Playwright requests
# are unaffected: browser contexts already manage their own cookies.
COOKIES_ENABLED = False

# Disable Telnet Console (enabled by default)
#TELNETCONSOLE_ENABLED = False

# Override the default request headers:
#DEFAULT_REQUEST_HEADERS = {
#    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#    "Accept-Language": "en",
#}

# Enable or disable spider middlewares
# See https://docs.scrapy.org/en/latest/topics/spider-middleware.html
#SPIDER_MIDDLEWARES = {
#    "crawler.middlewares.CrawlerSpiderMiddleware": 543,
#}

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
DOWNLOADER_MIDDLEWARES = {
    "crawler.middlewares.ApiTokenAuthMiddleware": 400,
}

# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
#EXTENSIONS = {
#    "scrapy.extensions.telnet.TelnetConsole": None,
#}

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
ITEM_PIPELINES = {
    "crawler.pipelines.ContentDedupPipeline": 100,
    "crawler.ytpipeline.YoutubePipeline": 120,
    "crawler.pipelines.NormalizationPipeline": 150,
    "crawler.pipelines.TenderExtractionPipeline": 160,
    "crawler.pipelines.EntityRelevancePipeline": 175,
    "crawler.pipelines.StoragePipeline": 200,
}

# name of the environment variable holding a YouTube Data API v3 key (never
# the key itself - same "config references an env var NAME" convention as
# auth.py). Used by crawler.ytpipeline for fetching comments and for the
# entity keyword search triggered by a YouTube seed URL. Comments/search are
# both skipped (logged, not fatal) when this isn't set.
YOUTUBE_API_KEY_ENV = "YOUTUBE_API_KEY"
# top-level comments fetched per video (paginated, 1 quota unit per 100)
YOUTUBE_MAX_COMMENTS = 100
# videos returned by one entity keyword search (search.list costs 100 quota
# units/call regardless of maxResults, so this is a single page, not paginated)
YOUTUBE_SEARCH_MAX_RESULTS = 25

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
#AUTOTHROTTLE_ENABLED = True
# The initial download delay
#AUTOTHROTTLE_START_DELAY = 5
# The maximum download delay to be set in case of high latencies
#AUTOTHROTTLE_MAX_DELAY = 60
# The average number of requests Scrapy should be sending in parallel to
# each remote server
#AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
# Enable showing throttling stats for every response received:
#AUTOTHROTTLE_DEBUG = False

# Enable and configure HTTP caching (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings
#HTTPCACHE_ENABLED = True
#HTTPCACHE_EXPIRATION_SECS = 0
#HTTPCACHE_DIR = "httpcache"
#HTTPCACHE_IGNORE_HTTP_CODES = []
#HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Set settings whose default value is deprecated to a future-proof value
FEED_EXPORT_ENCODING = "utf-8"

# Global cap: stop the crawl once this many pages have been scraped, so a
# misconfigured seed/domain can't run away indefinitely.
CLOSESPIDER_PAGECOUNT = 500

# Browser navigations should fail promptly; a page that cannot reach DOM-ready
# in 30 seconds is logged and skipped instead of serially stalling its domain.
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000
PLAYWRIGHT_DEFAULT_TIMEOUT = 10000
# Explicit resource bounds for browser-backed requests. This matters when
# several domains independently need a JavaScript retry.
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 2
PLAYWRIGHT_MAX_CONTEXTS = 4

# Redis-backed frontier: the pending-request queue and the seen-request
# dupefilter both live in Redis (same instance the ContentDedupPipeline
# already uses) instead of on local disk. This replaces JOBDIR - a crawl
# resumes automatically after a crash/restart because the frontier persists
# in Redis, and multiple spider processes can share/split the same queue.
REDIS_URL = "redis://localhost:6379/0"
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER_PERSIST = True

# StealthDownloadHandler still defers to Playwright for any request with
# meta["playwright"] = True (the escalation path in spiders/crawler.py); it
# only replaces what Playwright's own handler would otherwise fall back to
# for everything else - Twisted's plain HTTP/1.1 client - with a curl_cffi
# fetch impersonating Chrome's real TLS fingerprint (crawler.stealth_http).
DOWNLOAD_HANDLERS = {
    "http": "crawler.curl_cffi_handler.StealthDownloadHandler",
    "https": "crawler.curl_cffi_handler.StealthDownloadHandler",
}

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

PLAYWRIGHT_BROWSER_TYPE = "chromium"
