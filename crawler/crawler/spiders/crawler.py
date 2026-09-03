import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.http import XmlResponse
from scrapy.utils.gz import gunzip, gzip_magic_number
from scrapy.utils.sitemap import Sitemap, sitemap_urls_from_robots
from crawler.items import PageItems
from crawler.pipelines import format_duration, utc_timestamp
from urllib.parse import urlparse
import datetime
import io
import time
import trafilatura
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from scrapy_playwright.page import PageMethod

PLAYWRIGHT_WAIT = [PageMethod("wait_for_load_state", "networkidle")]

class WebsiteSpider(scrapy.Spider):

    name = "rag_crawler"

    def __init__(self, seeds ="seed.txt",max_depth = 2, use_sitemap=True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_depth = int(max_depth)
        self.use_sitemap = str(use_sitemap).lower() not in ("false", "0", "no")

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
            deny_extensions=[".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"],
        )

        # domains confirmed (by an earlier page on that domain) to need
        # playwright - subsequent pages on that domain skip straight to it
        self.js_domains = set()

        self.crawl_start_time = time.time()

    def closed(self, reason):
        # called automatically when the spider finishes (Scrapy spider_closed signal)
        total_elapsed = time.time() - self.crawl_start_time
        self.logger.info("Crawl finished (%s). Total time: %s", reason, format_duration(total_elapsed))

    def _extract_pdf_text(self, url, body):
        try:
            reader = PdfReader(io.BytesIO(body))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except (PdfReadError, ValueError) as e:
            self.logger.warning("Failed to extract PDF text from %s: %s", url, e)
            return ""

    def start_requests(self):
        # fetch plain first; parse() escalates to playwright only if the
        # plain fetch turns out to have no extractable content
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, meta={"depth": 0, "start_time": time.time(), "source": "seed"})

        if not self.use_sitemap:
            return

        # link-following from the seeds can miss pages nothing links to;
        # sitemaps (declared in robots.txt, or at the conventional /sitemap.xml
        # location) give a second, independent source of URLs for full coverage
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
            for entry in sitemap:
                loc = entry.get("loc")
                if not loc or urlparse(loc).netloc not in self.allowed_domains:
                    continue
                found += 1
                yield scrapy.Request(loc, callback=self.parse, meta={"depth": 0, "start_time": time.time(), "source": "sitemap"})
            self.logger.info("Sitemap %s contributed %d URL(s)", response.url, found)

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

        if "application/pdf" in content_type:
            pdf_text = self._extract_pdf_text(response.url, response.body)
            if pdf_text:
                yield PageItems(
                    url=response.url,
                    html=pdf_text,
                    depth=depth,
                    crawledAt=utc_timestamp(),
                    is_pdf=True,
                    source=source,
                )
            return

        # skipping other binary files (images, docs, etc.)
        if "text/html" not in content_type:
            return

        domain = urlparse(response.url).netloc

        # plain HTTP fetch produced no real content and we haven't already
        # tried playwright on this URL -> escalate, and remember that this
        # whole domain needs playwright so future pages skip the plain try
        if not response.meta.get("playwright") and not trafilatura.extract(response.text):
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

        # scrolling more pages basically doing pagination
        for link in self.link_extractor.extract_links(response):
            self.logger.info("Found link %s (depth=%d) on %s", link.url, depth + 1, response.url)
            link_domain = urlparse(link.url).netloc
            if link_domain in self.js_domains:
                yield scrapy.Request(
                    link.url,
                    callback=self.parse,
                    meta={
                        "depth": depth + 1,
                        "playwright": True,
                        "playwright_page_methods": PLAYWRIGHT_WAIT,
                        "start_time": time.time(),
                        "source": "link",
                    },
                )
            else:
                yield scrapy.Request(
                    link.url,
                    callback=self.parse,
                    meta={"depth": depth + 1, "start_time": time.time(), "source": "link"}
                )