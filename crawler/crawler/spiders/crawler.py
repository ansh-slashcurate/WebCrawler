import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.http import XmlResponse
from scrapy.utils.gz import gunzip, gzip_magic_number
from scrapy.utils.sitemap import Sitemap, sitemap_urls_from_robots
from crawler.items import PageItems
from crawler.pipelines import format_duration, utc_timestamp, slugify
from crawler.entity import EntityQuery
from crawler.tender import tender_page_score, looks_like_pagination_link
from crawler.aspnet_postback import find_next_page_postback, build_next_page_request
from crawler.liferay_api import (
    looks_like_liferay,
    find_tender_cx_bundle_url,
    find_headless_object_path,
    build_listing_url as build_liferay_listing_url,
    extract_records_from_api_response,
)
from crawler.challenge import detect_challenge
from crawler.auth import load_auth_config, AuthError
from crawler.ytpipeline import (
    extract_video_details,
    is_youtube_video_url,
    is_youtube_domain,
    render_video_text,
    search_videos,
    YoutubeApiError,
)
from urllib.parse import urlparse
import datetime
import json
import os
import time
import redis
import trafilatura
from scrapy_playwright.page import PageMethod

# Do not attach a PageMethod to ordinary rendered-page retries. In this
# scrapy-playwright version every PageMethod is followed internally by another
# ``page.wait_for_load_state()`` using the *load* state. News sites often never
# reach that state because ads and analytics keep resources open. The request's
# goto kwargs below use ``domcontentloaded`` instead, then capture the DOM.
PLAYWRIGHT_WAIT = ()
# Cloudflare-style "checking your browser" interstitials are pure JS/timing
# based (no human action needed). The retry uses the same DOM-ready navigation
# as other rendered requests; avoiding PageMethod also avoids its hidden full
# load-state wait (described above).
PLAYWRIGHT_CHALLENGE_WAIT = ()
# a plain (non-JS) fetch of a JS-rendered page (e.g. YouTube) often isn't
# literally empty - it still has the site-wide header/footer chrome baked into
# the static HTML, while the actual page content (video title/description,
# article body, ...) is added client-side. That's enough non-empty text to
# fool a check of "did trafilatura find *anything*", so the page silently gets
# scored/stored using only that boilerplate. Requiring at least this many
# extracted characters before treating the plain fetch as "done" makes a
# boilerplate-only result escalate to Playwright the same way a truly empty
# one already did.
MIN_EXTRACTED_CHARS = 200
# non-HTML file types we never want to fetch/extract - only HTML pages are
# handled. Used both for on-page link following (LinkExtractor) and for
# sitemap-discovered URLs (which bypass LinkExtractor entirely). Executables/
# installers/archives are the same "not HTML, fetch is wasted work" case as
# documents/images below, just easy to miss until one actually shows up - a
# real crawl hit a bank's UploadFile/.../nvda_2015.1.exe (a screen-reader
# installer linked from an accessibility page) and spent 5m50s downloading
# the whole binary before dropping it for having a non-HTML Content-Type.
DENY_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".msi", ".dmg", ".apk", ".zip", ".rar", ".7z", ".tar", ".gz",
)
# .exe is deliberately NOT in DENY_EXTENSIONS: unlike the types above, it
# isn't a reliable "definitely not HTML" signal - some sites (older ASP/
# ISAPI-style routing, common on legacy news/government/PSU portals) serve
# real HTML pages through a URL that literally ends in .exe, the extension
# being a request-handler artifact rather than a file type. Guessing from
# the URL alone would wrongly skip those pages. Instead these get a cheap
# HEAD preflight (_request_for_url below) that reads the real Content-Type
# before deciding to fetch the full page or skip it - catching a true binary
# (e.g. an installer .exe) without the multi-minute full-body download that
# blindly following it used to cost, while still crawling a genuine .exe-
# suffixed HTML page normally.
VERIFY_CONTENT_TYPE_EXTENSIONS = (".exe",)
# items per page requested from a discovered Liferay headless-object API
# (crawler.liferay_api) - independent of ASP.NET postback pagination's own
# page size (which the site controls, not us); here WE choose it, so a
# larger page means fewer round trips for the same MAX_TENDER_PAGES cap
LIFERAY_PAGE_SIZE = 50

class WebsiteSpider(scrapy.Spider):

    name = "rag_crawler"

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        # runs after settings/crawler are attached to the spider but before
        # the engine opens it (i.e. before pipelines' open_spider), so
        # self.run_id is already available when ContentDedupPipeline and
        # StoragePipeline read it in their own open_spider hooks
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._init_run()
        return spider

    def _init_run(self):
        """Assigns this crawl a run_id used to scope its output folder and dedup
        set. A crawl that crashed/stopped mid-way (the Redis request frontier
        still has pending URLs) resumes into the SAME run_id/files. A crawl
        started after the previous one fully drained (or was never run) gets a
        fresh run_id, so its output lands in a new folder instead of silently
        appending onto - or being deduped against - old, unrelated content."""
        redis_url = self.settings.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(redis_url)
        scope = slugify(self.entity_query.name) if self.entity_query else "default"
        self.run_scope = scope
        run_key = f"{self.name}:run_id:{scope}"
        frontier_key = f"{self.name}:requests"
        dupefilter_key = f"{self.name}:dupefilter"

        if client.exists(frontier_key) and client.exists(run_key):
            self.run_id = client.get(run_key).decode("utf-8")
            self.logger.info("Resuming previous crawl run %s (frontier not empty)", self.run_id)
        else:
            self.run_id = f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
            client.set(run_key, self.run_id)
            # RFPDupeFilter's seen-URL set persists in Redis across separate
            # `scrapy crawl` invocations (that's what SCHEDULER_PERSIST is for
            # resuming a crashed run). But a genuinely fresh run needs to
            # re-visit every seed-reachable URL - otherwise pages already
            # fetched by an earlier run (of this entity, or a previous
            # non-entity crawl) get silently skipped as "already seen" here
            # too, and never even reach the entity-relevance check
            client.delete(dupefilter_key)
            self.logger.info("Starting new crawl run %s (cleared %s)", self.run_id, dupefilter_key)

    def __init__(self, seeds ="seed.txt",max_depth = 2, use_sitemap=True,
                 entity=None, aliases="", context="", max_irrelevant_streak=2,
                 auth_config="auth.json", tender_mode=False,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_depth = int(max_depth)
        self.use_sitemap = str(use_sitemap).lower() not in ("false", "0", "no")
        # bank tender/RFP mode (see crawler.tender + crawler.pipelines'
        # TenderExtractionPipeline) - structural extraction only, no LLM
        # here. Frontier pruning against the bank-name entity below is
        # skipped in this mode; see the link-following loop.
        self.tender_mode = str(tender_mode).lower() not in ("false", "0", "no")

        # per-domain auth (see crawler/auth.py) - entirely optional, a crawl
        # with no auth.json (or none present for a given domain) behaves
        # exactly like a plain unauthenticated crawl
        try:
            self.auth_config = load_auth_config(auth_config)
        except AuthError as e:
            raise ValueError(f"Invalid auth config ({auth_config}): {e}") from e
        if self.auth_config:
            self.logger.info(
                "Loaded auth config for domain(s): %s",
                ", ".join(f"{d} ({p.method})" for d, p in self.auth_config.items()),
            )

        # entity-focused mode: when set, the spider scores every page against
        # this query to prioritize/prune the frontier, and EntityRelevancePipeline
        # uses the same query to gate what actually gets stored. When entity is
        # not given, the crawl behaves exactly as before (full-site crawl).
        self.entity_query = None
        if entity:
            alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
            context_list = [c.strip() for c in context.split(",") if c.strip()]
            self.entity_query = EntityQuery(entity, alias_list, context_list)
            self.max_irrelevant_streak = int(max_irrelevant_streak)
            self.logger.info(
                "Entity-focused crawl: name=%r aliases=%s context=%s max_irrelevant_streak=%d",
                entity, alias_list, context_list, self.max_irrelevant_streak,
            )

        with open(seeds, "r", encoding = "utf-8") as f:
            self.start_urls = [line.strip() for line in f if line.strip()]

        self.allowed_domains = list({url.split("/")[2] for url in self.start_urls})

        # remember which scheme (http/https) each seed domain uses, so sitemap
        # discovery can build "<scheme>://<domain>/robots.txt" etc. correctly
        self.domain_scheme = {}
        for url in self.start_urls:
            parsed = urlparse(url)
            self.domain_scheme.setdefault(parsed.netloc, parsed.scheme)

        self.link_extractor = LinkExtractor(
            allow_domains=self.allowed_domains,
            unique=True,
            canonicalize=True,
            # LinkExtractor prepends its own "." to every entry internally
            # (scrapy.linkextractors.lxmlhtml: `{"." + e for e in ...}`), so
            # passing DENY_EXTENSIONS' dotted forms straight through (".pdf")
            # becomes "..pdf" and matches nothing - every PDF/image/Office-doc/
            # archive link was silently still being followed and fully
            # downloaded before parse()'s Content-Type check discarded it,
            # the same waste a real crawl hit for a 6-minute .exe download.
            # DENY_EXTENSIONS itself keeps its dots (used as-is against full
            # URL suffixes for the sitemap check below), stripped only here.
            deny_extensions=[e.lstrip(".") for e in DENY_EXTENSIONS],
        )

        self.crawl_start_time = time.time()

    def closed(self, reason):
        # called automatically when the spider finishes (Scrapy spider_closed signal)
        total_elapsed = time.time() - self.crawl_start_time
        self.logger.info("Crawl finished (%s). Total time: %s", reason, format_duration(total_elapsed))

    def _log_blocked(self, url, reason, depth, source):
        output_dir = self.settings.get("OUTPUT_DIR", "output")
        if self.entity_query:
            output_dir = os.path.join(output_dir, slugify(self.entity_query.name))
        output_dir = os.path.join(output_dir, self.run_id)
        os.makedirs(output_dir, exist_ok=True)

        record = {"url": url, "reason": reason, "depth": depth, "source": source, "detected_at": utc_timestamp()}
        with open(os.path.join(output_dir, "blocked.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        self.logger.warning("Blocked/challenge page skipped: %s (%s)", url, reason)
        self.crawler.stats.inc_value("blocked/pages")

    def _request_for_url(self, url, meta, priority=0):
        """Build the Request for a discovered URL (on-page link or sitemap
        entry) - an ordinary GET straight to parse() for most URLs, or (for
        VERIFY_CONTENT_TYPE_EXTENSIONS) a HEAD preflight first, so the real
        Content-Type decides whether to fetch it as a page or skip it,
        instead of guessing from the URL the way DENY_EXTENSIONS does for
        unambiguous binary types."""
        if url.lower().endswith(VERIFY_CONTENT_TYPE_EXTENSIONS):
            return scrapy.Request(
                url,
                method="HEAD",
                callback=self._handle_head_check,
                errback=self._head_check_failed,
                priority=priority,
                meta={**meta, "checked_url": url, "resolved_priority": priority},
            )
        return scrapy.Request(url, callback=self.parse, priority=priority, meta=meta)

    def _handle_head_check(self, response):
        """Callback for the HEAD preflight built by _request_for_url. Only
        ever skips a URL on a clean 2xx HEAD response whose Content-Type is
        confidently non-HTML - any other outcome falls back to a normal GET.
        Verified against a real site (PNB Bank) that returns 404 for HEAD on
        a URL that returns 200 for GET: trusting a non-2xx HEAD status as
        "not HTML" would wrongly skip a page that's actually there."""
        meta = dict(response.meta)
        url = meta.pop("checked_url")
        priority = meta.pop("resolved_priority", 0)

        if 200 <= response.status < 300:
            content_type = response.headers.get("Content-Type", b"").decode(errors="ignore")
            if "text/html" in content_type:
                meta["start_time"] = time.time()
                yield scrapy.Request(url, callback=self.parse, priority=priority, meta=meta)
                return
            self._log_blocked(
                url, f"non-html-via-head-check ({content_type or 'unknown'})",
                meta.get("depth", 0), meta.get("source", "link"),
            )
            return

        self.logger.debug(
            "HEAD check for %s returned status %d - falling back to GET", url, response.status,
        )
        meta["start_time"] = time.time()
        yield scrapy.Request(url, callback=self.parse, priority=priority, meta=meta)

    def _head_check_failed(self, failure):
        """The HEAD preflight itself failed (network error, server doesn't
        support HEAD, timeout, ...) - fall back to a normal GET rather than
        risk silently losing a real page over an unverifiable server quirk."""
        meta = dict(failure.request.meta)
        url = meta.pop("checked_url", failure.request.url)
        priority = meta.pop("resolved_priority", 0)
        self.logger.debug("HEAD check failed for %s (%s) - falling back to GET", url, failure.value)
        meta["start_time"] = time.time()
        yield scrapy.Request(url, callback=self.parse, priority=priority, meta=meta)

    @staticmethod
    def _playwright_retry_meta(previous_meta, page_methods):
        """Build bounded, one-off browser retry metadata.

        A failed plain response says something about that URL, not every URL
        on its host. ``dont_retry`` also prevents Scrapy's generic retry
        middleware from turning one slow browser navigation into several
        consecutive navigation timeouts.
        """
        return {
            **{key: value for key, value in previous_meta.items() if key != "download_latency"},
            "playwright": True,
            "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
            "playwright_page_methods": page_methods,
            "dont_retry": True,
            "start_time": time.time(),
        }

    def _auth_request_meta(self, domain):
        """Extra request meta needed to carry an authenticated session for this
        domain (see crawler/auth.py) - {} for domains with no auth config, or
        with api_token auth (handled transparently by ApiTokenAuthMiddleware
        instead, since it applies to every request with no per-request meta
        needed) or form_login (plain Scrapy cookies already carry the session
        automatically once the login flow below has run)."""
        profile = self.auth_config.get(domain)
        if not profile:
            return {}
        if profile.method == "storage_state":
            # loads an already-authenticated session (cookies + localStorage)
            # exported from a real browser/prior login - no login flow needed
            return {
                "playwright": True,
                "playwright_context": f"auth:{domain}",
                "playwright_context_kwargs": {"storage_state": profile.storage_state_path},
            }
        if profile.method == "playwright_login":
            # the login flow below already created + authenticated this named
            # context; reusing the same name here keeps every later request
            # to this domain inside that same logged-in browser context
            return {"playwright": True, "playwright_context": f"auth:{domain}"}
        return {}

    def _build_login_request(self, profile, domain, urls):
        if profile.method == "form_login":
            return scrapy.Request(
                profile.login_url,
                callback=self._form_login_step2,
                meta={"start_time": time.time(), "auth_profile": profile, "auth_domain": domain, "auth_urls": urls},
                errback=self._login_errback,
            )
        # playwright_login
        return scrapy.Request(
            profile.login_url,
            callback=self._playwright_login_complete,
            meta={
                "start_time": time.time(),
                "auth_profile": profile,
                "auth_domain": domain,
                "auth_urls": urls,
                "playwright": True,
                "playwright_context": f"auth:{domain}",
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod("fill", profile.username_selector, profile.username),
                    PageMethod("fill", profile.password_selector, profile.password),
                    PageMethod("click", profile.submit_selector),
                    PageMethod("wait_for_selector", profile.success_selector, timeout=15000),
                ],
            },
            errback=self._login_errback,
        )

    def _form_login_step2(self, response):
        profile = response.meta["auth_profile"]
        domain = response.meta["auth_domain"]
        urls = response.meta["auth_urls"]
        yield scrapy.FormRequest.from_response(
            response,
            formdata={profile.username_field: profile.username, profile.password_field: profile.password},
            callback=self._login_complete,
            meta={"start_time": time.time(), "auth_domain": domain, "auth_urls": urls},
            errback=self._login_errback,
        )

    def _login_complete(self, response):
        domain = response.meta["auth_domain"]
        urls = response.meta["auth_urls"]
        self.logger.info("Form login complete for %s (status %d) - starting crawl", domain, response.status)
        for url in urls:
            meta = {"depth": 0, "start_time": time.time(), "source": "seed"}
            meta.update(self._auth_request_meta(domain))
            yield scrapy.Request(url, callback=self.parse, meta=meta)

    async def _playwright_login_complete(self, response):
        profile = response.meta["auth_profile"]
        domain = response.meta["auth_domain"]
        urls = response.meta["auth_urls"]
        self.logger.info("Playwright login complete for %s - starting crawl", domain)

        page = response.meta.get("playwright_page")
        if page is not None:
            if profile.save_storage_state:
                # persist this session so a future run can reuse it via
                # method="storage_state" instead of logging in again
                await page.context.storage_state(path=profile.save_storage_state)
                self.logger.info("Saved authenticated session for %s to %s", domain, profile.save_storage_state)
            await page.close()

        for url in urls:
            meta = {"depth": 0, "start_time": time.time(), "source": "seed"}
            meta.update(self._auth_request_meta(domain))
            yield scrapy.Request(url, callback=self.parse, meta=meta)

    def _login_errback(self, failure):
        domain = failure.request.meta.get("auth_domain", failure.request.url)
        self.logger.error("Login failed for %s: %s - this domain will not be crawled", domain, failure.value)

    def _youtube_search_requests(self):
        """A YouTube seed URL + an entity-focused crawl also runs a YouTube
        keyword search for the entity name (official Data API v3 search.list)
        - discovering videos this way doesn't depend on what happens to be
        linked from whichever single seed video was given, the way pure
        link-following does. No-ops (with a logged reason) if there's no
        YouTube seed, no entity, or no API key configured."""
        if not self.entity_query or not any(is_youtube_domain(u) for u in self.start_urls):
            return

        env_name = self.settings.get("YOUTUBE_API_KEY_ENV", "YOUTUBE_API_KEY")
        api_key = os.environ.get(env_name)
        if not api_key:
            self.logger.warning(
                "YouTube seed + entity search needs the %s environment variable set - skipping YouTube keyword search",
                env_name,
            )
            return

        max_results = self.settings.getint("YOUTUBE_SEARCH_MAX_RESULTS", 25)
        try:
            video_ids = search_videos(self.entity_query.name, api_key, max_results)
        except YoutubeApiError as e:
            self.logger.warning("YouTube keyword search for %r failed: %s", self.entity_query.name, e)
            return

        self.logger.info("YouTube keyword search for %r found %d video(s)", self.entity_query.name, len(video_ids))
        for video_id in video_ids:
            url = f"https://www.youtube.com/watch?v={video_id}"
            yield scrapy.Request(
                url,
                callback=self.parse,
                dont_filter=True,
                meta={"depth": 0, "start_time": time.time(), "source": "youtube_search"},
            )

    async def start(self):
        # Scrapy >= 2.13 no longer calls a spider's start_requests() at all
        # (confirmed against the installed 2.18: there is no reference to
        # "start_requests" anywhere in scrapy's own runtime code, only in a
        # docstring showing the OLD convention) - it only calls this async
        # start() method, falling back to its own trivial default
        # (`Request(url, dont_filter=True)` per self.start_urls, no meta of
        # ours at all) if a spider doesn't define one. That silently skipped
        # every bit of setup below - auth handling, "source"/"start_time"
        # meta on the seed request itself (which tender_mode's postback/
        # Liferay-detection gating on source=="seed" depends on), sitemap
        # discovery, YouTube search - for every crawl, not just tender ones.
        # Confirmed live: a seed request's meta showed only
        # {"is_start_request": True, "depth": 0, ...} (fields Scrapy's own
        # middleware inject) with none of this method's own keys, and its
        # parse() log line read "via link" instead of "via seed".
        #
        # fetch plain first; parse() escalates to playwright only if the
        # plain fetch turns out to have no extractable content
        login_domains = {}
        for url in self.start_urls:
            domain = urlparse(url).netloc
            profile = self.auth_config.get(domain)
            if profile and profile.method in ("form_login", "playwright_login"):
                # login-gated: hold this URL until the login flow (below)
                # completes, instead of fetching it straight away
                login_domains.setdefault(domain, []).append(url)
            else:
                meta = {"depth": 0, "start_time": time.time(), "source": "seed"}
                meta.update(self._auth_request_meta(domain))
                yield scrapy.Request(url, callback=self.parse, meta=meta)

        for domain, urls in login_domains.items():
            yield self._build_login_request(self.auth_config[domain], domain, urls)

        # "yield from" a plain (sync) generator isn't valid syntax inside an
        # async def generator - delegate item-by-item instead
        for request in self._youtube_search_requests():
            yield request

        if not self.use_sitemap:
            return

        # link-following from the seeds can miss pages nothing links to;
        # sitemaps (declared in robots.txt, or at the conventional /sitemap.xml
        # location) give a second, independent source of URLs for full coverage.
        # (robots.txt/sitemap.xml themselves are fetched unauthenticated - they're
        # meant for search-engine discovery and are normally public even on
        # sites that gate the actual content; the pages they list still go
        # through _auth_request_meta in _parse_sitemap below)
        for domain in self.allowed_domains:
            scheme = self.domain_scheme.get(domain, "https")
            yield scrapy.Request(
                f"{scheme}://{domain}/robots.txt",
                callback=self._parse_sitemap,
                meta={"start_time": time.time()},
                errback=self._sitemap_errback,
            )
            yield scrapy.Request(
                f"{scheme}://{domain}/sitemap.xml",
                callback=self._parse_sitemap,
                meta={"start_time": time.time()},
                errback=self._sitemap_errback,
            )

    def _sitemap_errback(self, failure):
        self.logger.debug("Sitemap discovery request failed: %s", failure.value)

    def _get_sitemap_body(self, response):
        if isinstance(response, XmlResponse):
            return response.body
        if gzip_magic_number(response):
            try:
                return gunzip(response.body)
            except Exception:
                return None
        if response.url.endswith(".xml") or response.url.endswith(".xml.gz"):
            return response.body
        return None

    def _parse_sitemap(self, response):
        if response.url.endswith("/robots.txt"):
            for url in sitemap_urls_from_robots(response.body, base_url=response.url):
                yield scrapy.Request(url, callback=self._parse_sitemap, meta={"start_time": time.time()})
            return

        if response.status != 200:
            return

        body = self._get_sitemap_body(response)
        if not body:
            return

        try:
            sitemap = Sitemap(body)
        except Exception as e:
            self.logger.warning("Failed to parse sitemap %s: %s", response.url, e)
            return

        if sitemap.type == "sitemapindex":
            for entry in sitemap:
                loc = entry.get("loc")
                if loc:
                    yield scrapy.Request(loc, callback=self._parse_sitemap, meta={"start_time": time.time()})
        elif sitemap.type == "urlset":
            found = 0
            skipped = 0
            skipped_not_tender = 0
            for entry in sitemap:
                loc = entry.get("loc")
                if not loc:
                    continue
                loc_domain = urlparse(loc).netloc
                if loc_domain not in self.allowed_domains:
                    continue
                # sitemap-discovered URLs bypass LinkExtractor entirely, so
                # apply the same non-HTML extension filter here too
                if loc.lower().endswith(DENY_EXTENSIONS):
                    skipped += 1
                    self.logger.warning("Dropped: non-HTML sitemap entry: %s", loc)
                    continue
                # sitemap URLs also bypass the hard-scope tender filter that
                # ordinarily gates parse()'s link-following loop, since they
                # never go through LinkExtractor at all - confirmed live,
                # this let a tender crawl wander into hundreds of unrelated
                # same-domain pages (About Us, careers, policy PDFs, ...)
                # just because they happened to be listed in the site's
                # sitemap.xml, each counting against CLOSESPIDER_PAGECOUNT.
                # A sitemap entry has no anchor text to score, only its own
                # URL - same as a nav item's href often carrying the
                # "/procurement/tenders" keyword its visible text doesn't.
                if self.tender_mode and tender_page_score(loc) == 0 and not looks_like_pagination_link(None, loc):
                    skipped_not_tender += 1
                    continue
                found += 1
                meta = {"depth": 0, "start_time": time.time(), "source": "sitemap"}
                meta.update(self._auth_request_meta(loc_domain))
                yield self._request_for_url(loc, meta)
            self.logger.info(
                "Sitemap %s contributed %d URL(s), skipped %d non-HTML, skipped %d non-tender-related",
                response.url, found, skipped, skipped_not_tender,
            )

    # Parsing response
    def parse(self, response):

        # time taken to fetch this specific response (request -> response)
        start_time = response.meta.get("start_time")
        elapsed = time.time() - start_time if start_time else None
        crawled_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source = response.meta.get("source", "link")
        self.logger.info(
            "Crawled %s via %s at %s (took %s)",
            response.url, source, crawled_at, format_duration(elapsed),
        )

        content_type = response.headers.get("Content-Type", b"").decode(errors="ignore")
        print(f"Content-Type: {content_type}")

        depth = response.meta.get("depth", 0)

        # only HTML pages are handled now - PDFs and other binary files
        # (images, docs, etc.) are fetched-then-skipped, not extracted
        if "text/html" not in content_type:
            self.logger.warning("Dropped: non-HTML content (%s): %s", content_type or "unknown", response.url)
            return

        # bot-challenge/block page (Cloudflare, hCaptcha, reCAPTCHA, ...) -
        # check before anything else, so it never gets mistaken for real
        # content just because trafilatura managed to extract *some* text
        # from the interstitial page
        challenge_reason = detect_challenge(response.status, response.text)
        if challenge_reason:
            if not response.meta.get("challenge_retry"):
                # one retry via playwright with extra wait - covers
                # auto-resolving JS-only challenges (Cloudflare's "checking
                # your browser"), which need no human action, just time
                self.logger.info("Challenge detected at %s (%s) - retrying via playwright", response.url, challenge_reason)
                yield scrapy.Request(
                    response.url,
                    callback=self.parse,
                    dont_filter=True,
                    meta={
                        **self._playwright_retry_meta(response.meta, PLAYWRIGHT_CHALLENGE_WAIT),
                        "challenge_retry": True,
                    },
                )
                return
            # still challenged after the retry - this needs real human
            # interaction (or isn't going to allow automated access at all),
            # so log it and move on instead of storing garbage or retrying forever
            self._log_blocked(response.url, challenge_reason, depth, source)
            return

        # Plain HTTP fetch produced no real content and we have not already
        # tried Playwright on this URL -> escalate this URL only. A sparse
        # page must not make every later URL on the same host use a browser.
        # favor_recall: trafilatura's default (precision-favoring) extraction
        # drops card/grid-style content - e.g. a team/staff directory entry -
        # as boilerplate even though it's real content, which is exactly the
        # kind of page an entity-focused crawl most needs to see
        # YouTube's plain (un-rendered) server HTML already embeds the full
        # video metadata as JSON (ytInitialPlayerResponse) - Playwright
        # rendering isn't needed to get it, and is actively unreliable here:
        # once YouTube's own JS runs, it consumes that JSON and can mutate or
        # drop the script tag before page.content() is captured, so the same
        # code can succeed on one video and fail on the next in the same
        # crawl. Try the plain-HTML extraction first and only fall through to
        # the generic trafilatura/Playwright-escalation path if it comes back
        # empty (e.g. a genuinely unavailable/private video).
        video_details = extract_video_details(response.text, response.url)
        if video_details is not None:
            extracted = render_video_text(video_details)
        else:
            extracted = trafilatura.extract(response.text, favor_recall=True) or ""
        if video_details is None and not response.meta.get("playwright") and len(extracted) < MIN_EXTRACTED_CHARS:
            yield scrapy.Request(
                response.url,
                callback=self.parse,
                dont_filter=True,
                meta=self._playwright_retry_meta(response.meta, PLAYWRIGHT_WAIT),
            )
            return

        yield PageItems(
            url = response.url,
            html = response.text,
            depth = depth,
            crawledAt = utc_timestamp(),
            source = source,
        )

        # ASP.NET WebForms pagination (__doPostBack, confirmed live on PNB's
        # own tender listing) has no real href for page 2+, so it can't be
        # picked up by the ordinary LinkExtractor loop below at all - follow
        # it as its own postback request instead, independent of max_depth
        # (it's the same logical listing page, not a deeper link) and capped
        # by MAX_TENDER_PAGES so a pager that never reports "no next page"
        # can't chain forever.
        #
        # Only ever started from the listing's own canonical entry points
        # (the seed/sitemap fetch, or a page already inside this same
        # postback chain) - NEVER from source="link". Confirmed on a real
        # PNB crawl: the page's own "Skip to Main Content" accessibility
        # link resolves (fragment stripped) straight back to this exact
        # URL, and its anchor text/URL both score >0 on tender_page_score
        # (the URL literally contains "Tender.aspx"), so it passes the
        # hard-scope link filter below like any other tender-relevant link.
        # Without this guard, that single self-link caused every page
        # discovered as a "link" to start its own independent copy of the
        # ENTIRE pagination chain from page 1, roughly doubling every
        # extracted tender (confirmed: ~154 rows in tenders.jsonl for what
        # should have been ~77) and doubling classification time with it.
        if self.tender_mode and source in ("seed", "sitemap", "tender_pagination"):
            page_num = response.meta.get("tender_page", 1)
            max_pages = self.settings.getint("MAX_TENDER_PAGES", 15)
            if page_num < max_pages:
                event_target = find_next_page_postback(response)
                if event_target:
                    self.logger.info(
                        "Tender pagination: following postback to page %d on %s",
                        page_num + 1, response.url,
                    )
                    yield build_next_page_request(
                        response, event_target, callback=self.parse,
                        meta={
                            **response.meta, "tender_page": page_num + 1, "depth": depth,
                            "start_time": time.time(), "source": "tender_pagination",
                        },
                    )

        # some banks' tender listings have no server-rendered content at
        # all (confirmed live on Canara Bank: a Liferay CMS site whose
        # listing is fetched entirely client-side by a JS bundle from a
        # JSON API) - no column-matching heuristic over this page's HTML
        # can ever find rows that were never in the HTML to begin with.
        # Same source-scoping as the postback pagination above and for the
        # same reason: only ever started from the listing's own canonical
        # entry point, never from an ordinary followed link.
        if self.tender_mode and source in ("seed", "sitemap") and looks_like_liferay(response.text):
            bundle_url = find_tender_cx_bundle_url(response.text, response.url)
            if bundle_url:
                self.logger.info(
                    "Tender listing at %s looks client-rendered (Liferay) - fetching %s",
                    response.url, bundle_url,
                )
                yield scrapy.Request(
                    bundle_url, callback=self._parse_liferay_bundle,
                    meta={
                        "tender_listing_url": response.url, "depth": depth,
                        "start_time": time.time(), "source": "liferay_bundle",
                    },
                )

        if depth >= self.max_depth:
            return

        # entity-focused pruning: once a branch has gone max_irrelevant_streak
        # pages in a row without mentioning the entity, stop following it even
        # though depth < max_depth - this is what keeps the crawl from walking
        # the whole site instead of just the entity-relevant parts of it.
        # Skipped entirely in tender_mode: a bank's tenders subsection won't
        # keep repeating the bank's own name on every page, so this
        # heuristic doesn't apply there - tender crawls are bounded by
        # max_depth/CLOSESPIDER_PAGECOUNT only, same as a non-entity crawl.
        irrelevant_streak = response.meta.get("irrelevant_streak", 0)
        if self.entity_query and not self.tender_mode:
            _, page_relevant, _ = self.entity_query.score(extracted or "")
            irrelevant_streak = 0 if page_relevant else irrelevant_streak + 1
            if irrelevant_streak >= self.max_irrelevant_streak:
                self.logger.info(
                    "Pruning branch at %s (irrelevant_streak=%d >= %d)",
                    response.url, irrelevant_streak, self.max_irrelevant_streak,
                )
                return

        # scrolling more pages basically doing pagination
        tender_page = response.meta.get("tender_page", 1)
        tender_page_limit_hit = self.tender_mode and tender_page >= self.settings.getint("MAX_TENDER_PAGES", 15)
        for link in self.link_extractor.extract_links(response):
            if link.url == response.url:
                # a same-page "skip to content"/"back to top" anchor -
                # canonicalizes (fragment stripped) straight back to this
                # exact page. Re-queuing the page we're already parsing as
                # if it were newly discovered is never useful, and in
                # tender_mode specifically it was confirmed to double every
                # extracted tender by letting a page reached this way start
                # its own independent copy of the postback pagination chain
                # (see the tender_pagination block above)
                continue
            if is_youtube_domain(link.url) and not is_youtube_video_url(link.url):
                # a YouTube page links to hundreds of site-chrome pages
                # (/about, /ads, /creators, /t/terms, /howyoutubeworks, ...)
                # that have nothing to do with video content - following
                # those wanders the crawl off into YouTube's corporate site
                # instead of more videos, burning CLOSESPIDER_PAGECOUNT on
                # pages an entity-focused video crawl never wanted
                continue

            link_domain = urlparse(link.url).netloc
            is_pagination = self.tender_mode and looks_like_pagination_link(link.text, link.url)
            if is_pagination and tender_page_limit_hit:
                # capped the same way postback/Liferay pagination already
                # are (MAX_TENDER_PAGES) - without an independent cap here
                # too, removing this pagination hop's max_depth cost just
                # below would let it run unbounded except for the crawl's
                # own shared CLOSESPIDER_PAGECOUNT, competing with every
                # other page (detail pages, sitemap URLs) for that budget
                continue
            # a genuine <a href> pagination control (confirmed live: Bank of
            # Maharashtra paginates its listing this way, not via postback
            # or a JSON API) is the SAME logical listing, not a deeper page -
            # same reasoning as the dedicated postback/Liferay pagination
            # blocks above, which are already independent of max_depth.
            # Without this, max_depth=3 (the UI default) only ever reached
            # ~4 of a bank's paginated pages regardless of how many more
            # tenders existed beyond that, silently missing anything older.
            child_depth = depth if is_pagination else depth + 1
            self.logger.info("Found link %s (depth=%d) on %s", link.url, child_depth, response.url)

            child_meta = {"depth": child_depth, "start_time": time.time(), "source": "link"}
            if is_pagination:
                child_meta["tender_page"] = tender_page + 1
            priority = 0
            if self.entity_query and not self.tender_mode:
                child_meta["irrelevant_streak"] = irrelevant_streak
                # anchor text is a cheap, pre-fetch signal - links whose text
                # already mentions the entity get crawled before filler pages
                priority, _, _ = self.entity_query.score(link.text or "")
            if self.tender_mode:
                # hard scope, not just priority: a tender crawl only follows
                # links that read as tender/procurement-related (anchor text
                # + URL, since a nav item's href often carries the keyword
                # the visible text doesn't, e.g. "/procurement/tenders"), or
                # a same-page pagination control - never the rest of the
                # bank's site (About Us, NRI, Internet Banking, ...)
                tender_score = tender_page_score((link.text or "") + " " + link.url)
                if tender_score == 0 and not is_pagination:
                    continue
                # pagination gets crawled before individual detail pages, so
                # the listing's own page count (MAX_TENDER_PAGES-worthy
                # coverage) isn't starved by CLOSESPIDER_PAGECOUNT going to
                # detail pages first
                priority += tender_score + (5 if is_pagination else 0)

            auth_meta = self._auth_request_meta(link_domain)
            if auth_meta:
                # authenticated domain - always ride the same logged-in
                # Playwright context for the authenticated session
                yield self._request_for_url(link.url, {**child_meta, **auth_meta}, priority=priority)
            else:
                yield self._request_for_url(link.url, child_meta, priority=priority)

    def _parse_liferay_bundle(self, response):
        """Callback for the Liferay Client Extension bundle fetched from
        parse()'s tender_mode block above - finds the headless-object API
        path it calls for its paginated listing and starts fetching that."""
        listing_url = response.meta["tender_listing_url"]
        object_path = find_headless_object_path(response.text)
        if not object_path:
            self.logger.info(
                "Liferay bundle %s didn't reference a headless-object API - giving up on %s",
                response.url, listing_url,
            )
            return

        api_url = build_liferay_listing_url(listing_url, object_path, page=1, page_size=LIFERAY_PAGE_SIZE)
        self.logger.info("Liferay tender listing API discovered for %s: %s", listing_url, api_url)
        yield scrapy.Request(
            api_url, callback=self._parse_liferay_api_page,
            meta={
                "tender_listing_url": listing_url, "liferay_object_path": object_path,
                "liferay_page": 1, "depth": response.meta["depth"],
                "start_time": time.time(), "source": "liferay_api",
                # without this, curl_cffi's own Chrome-impersonation Accept
                # header (correct for a real page load, see stealth_http.py)
                # lists application/xml ahead of application/json, and
                # Liferay's content negotiation returns XML instead -
                # confirmed live against Canara Bank's own API
                "force_headers": {"Accept": "application/json"},
            },
        )

    def _parse_liferay_api_page(self, response):
        """Callback for one page of a discovered Liferay headless-object
        API - yields a PageItems with tender_records already attached
        (TenderExtractionPipeline skips re-extracting these from "html",
        which is this response's raw JSON, not markup - see its own
        docstring), then follows to the next page until either side of
        MAX_TENDER_PAGES/totalCount says to stop."""
        listing_url = response.meta["tender_listing_url"]
        page_num = response.meta["liferay_page"]
        records, total_count = extract_records_from_api_response(response.text, listing_url)

        yield PageItems(
            url=f"{listing_url}#liferay-page={page_num}",
            html=response.text,
            depth=response.meta["depth"],
            crawledAt=utc_timestamp(),
            source="liferay_api",
            tender_records=records,
            is_api_json=True,
        )

        max_pages = self.settings.getint("MAX_TENDER_PAGES", 15)
        fetched_so_far = page_num * LIFERAY_PAGE_SIZE
        if records and page_num < max_pages and fetched_so_far < total_count:
            api_url = build_liferay_listing_url(
                listing_url, response.meta["liferay_object_path"],
                page=page_num + 1, page_size=LIFERAY_PAGE_SIZE,
            )
            yield scrapy.Request(
                api_url, callback=self._parse_liferay_api_page,
                meta={**response.meta, "liferay_page": page_num + 1, "start_time": time.time()},
            )
