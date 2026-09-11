import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.http import XmlResponse
from scrapy.utils.gz import gunzip, gzip_magic_number
from scrapy.utils.sitemap import Sitemap, sitemap_urls_from_robots
from crawler.items import PageItems
from crawler.pipelines import format_duration, utc_timestamp, slugify
from crawler.entity import EntityQuery
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

PLAYWRIGHT_WAIT = [PageMethod("wait_for_load_state", "networkidle")]
# Cloudflare-style "checking your browser" interstitials are pure JS/timing
# based (no human action needed) but often take a few seconds longer than
# networkidle alone waits for - give them one retry with extra time before
# concluding the challenge is a real (non-auto-resolving) block.
PLAYWRIGHT_CHALLENGE_WAIT = PLAYWRIGHT_WAIT + [PageMethod("wait_for_timeout", 5000)]
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
# sitemap-discovered URLs (which bypass LinkExtractor entirely)
DENY_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")

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
                 auth_config="auth.json",
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_depth = int(max_depth)
        self.use_sitemap = str(use_sitemap).lower() not in ("false", "0", "no")

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
            deny_extensions=DENY_EXTENSIONS,
        )

        # domains confirmed (by an earlier page on that domain) to need
        # playwright - subsequent pages on that domain skip straight to it
        self.js_domains = set()

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

    def start_requests(self):
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

        yield from self._youtube_search_requests()

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
                found += 1
                meta = {"depth": 0, "start_time": time.time(), "source": "sitemap"}
                meta.update(self._auth_request_meta(loc_domain))
                yield scrapy.Request(loc, callback=self.parse, meta=meta)
            self.logger.info("Sitemap %s contributed %d URL(s), skipped %d non-HTML", response.url, found, skipped)

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

        domain = urlparse(response.url).netloc

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
                        **response.meta,
                        "playwright": True,
                        "playwright_page_methods": PLAYWRIGHT_CHALLENGE_WAIT,
                        "challenge_retry": True,
                        "start_time": time.time(),
                    },
                )
                return
            # still challenged after the retry - this needs real human
            # interaction (or isn't going to allow automated access at all),
            # so log it and move on instead of storing garbage or retrying forever
            self._log_blocked(response.url, challenge_reason, depth, source)
            return

        # plain HTTP fetch produced no real content and we haven't already
        # tried playwright on this URL -> escalate, and remember that this
        # whole domain needs playwright so future pages skip the plain try
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
            self.js_domains.add(domain)
            yield scrapy.Request(
                response.url,
                callback=self.parse,
                dont_filter=True,
                meta={
                    **response.meta,
                    "playwright": True,
                    "playwright_page_methods": PLAYWRIGHT_WAIT,
                    "start_time": time.time(),
                },
            )
            return

        yield PageItems(
            url = response.url,
            html = response.text,
            depth = depth,
            crawledAt = utc_timestamp(),
            source = source,
        )

        if depth >= self.max_depth:
            return

        # entity-focused pruning: once a branch has gone max_irrelevant_streak
        # pages in a row without mentioning the entity, stop following it even
        # though depth < max_depth - this is what keeps the crawl from walking
        # the whole site instead of just the entity-relevant parts of it
        irrelevant_streak = response.meta.get("irrelevant_streak", 0)
        if self.entity_query:
            _, page_relevant, _ = self.entity_query.score(extracted or "")
            irrelevant_streak = 0 if page_relevant else irrelevant_streak + 1
            if irrelevant_streak >= self.max_irrelevant_streak:
                self.logger.info(
                    "Pruning branch at %s (irrelevant_streak=%d >= %d)",
                    response.url, irrelevant_streak, self.max_irrelevant_streak,
                )
                return

        # scrolling more pages basically doing pagination
        for link in self.link_extractor.extract_links(response):
            if is_youtube_domain(link.url) and not is_youtube_video_url(link.url):
                # a YouTube page links to hundreds of site-chrome pages
                # (/about, /ads, /creators, /t/terms, /howyoutubeworks, ...)
                # that have nothing to do with video content - following
                # those wanders the crawl off into YouTube's corporate site
                # instead of more videos, burning CLOSESPIDER_PAGECOUNT on
                # pages an entity-focused video crawl never wanted
                continue

            self.logger.info("Found link %s (depth=%d) on %s", link.url, depth + 1, response.url)
            link_domain = urlparse(link.url).netloc

            child_meta = {"depth": depth + 1, "start_time": time.time(), "source": "link"}
            priority = 0
            if self.entity_query:
                child_meta["irrelevant_streak"] = irrelevant_streak
                # anchor text is a cheap, pre-fetch signal - links whose text
                # already mentions the entity get crawled before filler pages
                priority, _, _ = self.entity_query.score(link.text or "")

            auth_meta = self._auth_request_meta(link_domain)
            if auth_meta:
                # authenticated domain - always ride the same logged-in
                # playwright context, regardless of js_domains state
                yield scrapy.Request(link.url, callback=self.parse, priority=priority, meta={**child_meta, **auth_meta})
            elif link_domain in self.js_domains and not is_youtube_video_url(link.url):
                # a YouTube watch link always gets a plain-fetch attempt first
                # (see the extract_video_details call above) even if some
                # other page on this domain already forced js_domains - the
                # plain HTML is what reliably has the video's metadata JSON,
                # Playwright's rendered DOM is not
                yield scrapy.Request(
                    link.url,
                    callback=self.parse,
                    priority=priority,
                    meta={
                        **child_meta,
                        "playwright": True,
                        "playwright_page_methods": PLAYWRIGHT_WAIT,
                    },
                )
            else:
                yield scrapy.Request(
                    link.url,
                    callback=self.parse,
                    priority=priority,
                    meta=child_meta,
                )