"""Scrapy's default LogFormatter pretty-prints the entire item on every
"Scraped from" (DEBUG) and "Dropped: ..." (WARNING - fires regardless of
LOG_LEVEL) message, including PageItems' full raw html field. That floods the
crawl log with page source instead of useful info - the html already lives in
pages.jsonl, so the log only needs to know a page was scraped/dropped and why."""

from scrapy.logformatter import LogFormatter


def _redact_html(item):
    html = item.get("html") if hasattr(item, "get") else None
    if not html:
        return item
    redacted = dict(item)
    redacted["html"] = f"<{len(html)} chars omitted - see pages.jsonl>"
    return redacted


def _drop_summary(item):
    """A dropped item never reaches pages.jsonl/clean.jsonl - it's discarded,
    not stored - so there's no reason for its extracted content
    (cleaned_content/tables/comments, potentially large for a YouTube page's
    comments) to end up in the log either. Keep only enough to identify what
    was dropped; the drop reason itself comes from `exception`, already part
    of Scrapy's "Dropped: ..." message."""
    getter = item.get if hasattr(item, "get") else lambda k, d=None: d
    return {"url": getter("url"), "source": getter("source"), "depth": getter("depth")}


class CrawlerLogFormatter(LogFormatter):
    def dropped(self, item, exception, response, spider):
        return super().dropped(_drop_summary(item), exception, response, spider)

    def scraped(self, item, response, spider):
        return super().scraped(_redact_html(item), response, spider)
