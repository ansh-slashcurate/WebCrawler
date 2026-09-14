"""Download handler that keeps Playwright for browser-rendered requests
(meta["playwright"] = True - see spiders/crawler.py's escalation path) but
routes every other request through curl_cffi's Chrome impersonation
(crawler.stealth_http) instead of Twisted's plain HTTP/1.1 client. That plain
path is the crawl's first attempt at any URL, so giving it a real TLS
fingerprint from the start is what actually avoids tripping a CAPTCHA/bot
challenge, rather than only reacting to one after the fact via the existing
Playwright retry in parse().
"""

from scrapy.http import Request, Response
from scrapy.utils.defer import deferred_to_future
from scrapy_playwright.handler import ScrapyPlaywrightDownloadHandler
from twisted.internet.threads import deferToThread

from crawler.stealth_http import stealth_fetch


class StealthDownloadHandler(ScrapyPlaywrightDownloadHandler):
    async def download_request(self, request: Request) -> Response:
        if request.meta.get("playwright"):
            return await super().download_request(request)
        return await deferred_to_future(deferToThread(stealth_fetch, request))
