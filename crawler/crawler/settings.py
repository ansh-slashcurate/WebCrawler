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
# scraper" the way a real browser wouldn't either. Only affects the plain
# (non-Playwright) fetch - once escalated to Playwright, the real launched
# Chromium browser already reports its own genuine UA regardless of this.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# By default Scrapy silently drops non-2xx responses before they reach the
# spider callback. Bot-challenge/block pages typically respond 403/429/503,
# so without this the spider would never even see them to detect and log -
# they'd just look like plain failed requests.
HTTPERROR_ALLOWED_CODES = [403, 429, 503]

# Concurrency and throttling settings
#CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1

# Disable cookies (enabled by default)
#COOKIES_ENABLED = False

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

# Playright default timeout 
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 60000

# Redis-backed frontier: the pending-request queue and the seen-request
# dupefilter both live in Redis (same instance the ContentDedupPipeline
# already uses) instead of on local disk. This replaces JOBDIR - a crawl
# resumes automatically after a crash/restart because the frontier persists
# in Redis, and multiple spider processes can share/split the same queue.
REDIS_URL = "redis://localhost:6379/0"
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER_PERSIST = True

DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

PLAYWRIGHT_BROWSER_TYPE = "chromium"