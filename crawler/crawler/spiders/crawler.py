import scrapy
from scrapy.linkextractors import LinkExtractor
from crawler.items import PageItems
from urllib.parse import urlparse
import datetime
import trafilatura
from scrapy_playwright.page import PageMethod

PLAYWRIGHT_WAIT = [PageMethod("wait_for_load_state", "networkidle")]

class WebsiteSpider(scrapy.Spider):

    name = "rag_crawler"

    def __init__(self, seeds ="seed.txt",max_depth = 2, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_depth = int(max_depth)

        with open(seeds, "r", encoding = "utf-8") as f:
            self.start_urls = [line.strip() for line in f if line.strip()]

        self.allowed_domains = list({url.split("/")[2] for url in self.start_urls})

        self.link_extractor = LinkExtractor(
            allow_domains=self.allowed_domains,
            unique=True,
            canonicalize=True,
            deny_extensions=[".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"],
        )

        # domains confirmed (by an earlier page on that domain) to need
        # playwright - subsequent pages on that domain skip straight to it
        self.js_domains = set()

    def start_requests(self):
        # fetch plain first; parse() escalates to playwright only if the
        # plain fetch turns out to have no extractable content
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, meta={"depth": 0})

    # Parsing response
    def parse(self, response):

        # skipping binary files
        content_type = response.headers.get("Content-Type", b"").decode(errors="ignore")
        print(f"Content-Type: {content_type}")
        if "text/html" not in content_type:
            return

        depth = response.meta.get("depth", 0)

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
                },
            )
            return

        yield PageItems(
            url = response.url,
            html = response.text,
            depth = depth,
            crawledAt = datetime.datetime.utcnow().isoformat(),
        )

        if depth >= self.max_depth:
            return

        # scrolling more pages basically doing pagination
        for link in self.link_extractor.extract_links(response):
            link_domain = urlparse(link.url).netloc
            if link_domain in self.js_domains:
                yield scrapy.Request(
                    link.url,
                    callback=self.parse,
                    meta={
                        "depth": depth + 1,
                        "playwright": True,
                        "playwright_page_methods": PLAYWRIGHT_WAIT,
                    },
                )
            else:
                yield scrapy.Request(
                    link.url,
                    callback=self.parse,
                    meta={"depth": depth + 1}
                )