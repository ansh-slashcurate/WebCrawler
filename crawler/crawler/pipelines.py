# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import json
import datetime
import time
from collections import Counter
from pathlib import Path
import os
import re
import redis
import hashlib

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem
from lxml import etree, html as lxml_html
import trafilatura


BROKEN_TAG_NAMES = "li|ul|ol|div|span|p|br|strong|em|table|tr|td|a|h[1-6]"


def format_duration(seconds):
    """Turn a raw second count into a plain "1h 3m 8s" style string, so
    someone reading the logs/summary doesn't have to do the math themselves."""
    if seconds is None or seconds < 0:
        return "unknown"
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def utc_timestamp():
    """Plain 'YYYY-MM-DD HH:MM:SS UTC' - still sorts correctly like ISO 8601,
    but without the T separator/microseconds that make it read as code-only."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def normalize_text(text: str) -> str:
    # drop well-formed leftover HTML tags trafilatura missed
    text = re.sub(r"<[^>]*>", "", text)
    # drop broken tag remnants that lost their opening '<' (e.g. "NDS-OMli>"
    # from a stray <li> merged into the preceding word during extraction)
    text = re.sub(rf"([A-Za-z])(?:{BROKEN_TAG_NAMES})>", r"\1", text)
    # de-obfuscate emails before stripping punctuation below
    text = text.replace("[at]", "@").replace("[dot]", ".")
    text = text.replace("|", "")
    text = text.replace("-", "")
    # normalize all whitespace (including newlines) down to single spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _cell_text(cell):
    text = cell.text_content().replace("[at]", "@").replace("[dot]", ".")
    return re.sub(r"\s+", " ", text).strip()


def extract_tables(html_content):
    """Pull <table> elements out of raw HTML as structured data (a list of
    row dicts per table), kept separate from the prose text so generic text
    cleaning never touches table cells."""
    try:
        tree = lxml_html.fromstring(html_content)
    except (etree.ParserError, ValueError):
        return []

    tables = []
    for table_el in tree.xpath("//table"):
        trs = table_el.xpath(".//tr")
        if not trs:
            continue

        rows_cells = [[_cell_text(c) for c in tr.xpath("./th|./td")] for tr in trs]

        # the real tabular width is whichever cell-count is most common among
        # multi-cell rows; a row with a different width is a caption/section
        # title (e.g. one cell spanning the table) rather than real header/data
        widths = [len(cells) for cells in rows_cells if len(cells) > 1]
        if not widths:
            continue
        mode_width = Counter(widths).most_common(1)[0][0]

        headers = None
        rows = []
        for cells in rows_cells:
            if len(cells) != mode_width:
                continue
            if headers is None:
                headers = cells
                continue
            if not any(cells):
                continue
            rows.append(dict(zip(headers, cells)))

        if rows:
            tables.append(rows)

    return tables

class CrawlerPipeline:
    def process_item(self, item):
        return item

# content hashpipeline

class ContentDedupPipeline:
    def __init__(self, redis_url):
        self.redis_url = redis_url
        self.client = None
 
    @classmethod
    def from_crawler(cls, crawler):
        return cls(redis_url=crawler.settings.get("REDIS_URL", "redis://localhost:6379/0"))
 
    def open_spider(self, spider):
        self.client = redis.from_url(self.redis_url)
 
    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        content_hash = hashlib.sha256(adapter["html"].encode("utf-8")).hexdigest()

        # SADD returns 0 if the member already existed - atomic, so two
        # workers hashing the same content at the same instant can't both
        # think they're first.
        is_new = self.client.sadd("content_hashes", content_hash)
        if not is_new:
            spider.crawler.stats.inc_value("dropped/duplicate")
            raise DropItem(f"Duplicate content: {adapter['url']}")

        adapter["content_hash"] = content_hash
        return item


# extracts prose + tables from the raw html and normalizes the prose text,
# so cleaned_content is already RAG-ready by the time StoragePipeline writes it
class NormalizationPipeline:
    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        html = adapter.get("html", "")

        if adapter.get("is_pdf"):
            # the spider already extracted plain text from the PDF - there's
            # no HTML markup here, so trafilatura/table extraction don't apply
            cleaned_content = normalize_text(html)
            tables = []
        else:
            # tables are extracted separately (below) as structured data, so
            # they don't get linearized into prose and mangled by normalize_text
            raw_content = trafilatura.extract(html, include_tables=False) or ""
            cleaned_content = normalize_text(raw_content)
            tables = extract_tables(html)

        if not cleaned_content and not tables:
            spider.crawler.stats.inc_value("dropped/empty")
            raise DropItem(f"No extractable content: {adapter.get('url')}")

        if tables:
            spider.crawler.stats.inc_value("tables/pages_with_tables")
            spider.crawler.stats.inc_value("tables/total_tables", count=len(tables))

        adapter["cleaned_content"] = cleaned_content
        adapter["tables"] = tables
        return item


def _count_lines(path):
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


# storage pipeline
class StoragePipeline:
    def __init__(self,output_dir):
        self.output_dir = output_dir
        self.out_file = None
        self.pages_written = 0
        self.clean_written = 0

    @classmethod
    def from_crawler(cls, crawler):
        return cls(output_dir=crawler.settings.get("OUTPUT_DIR", "output"))


    def open_spider(self, spider):
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        out_path = os.path.join(self.output_dir, f"pages.jsonl")
        self.pages_lines_before = _count_lines(out_path)
        self.out_file = open(out_path, "a", encoding="utf-8")

        clean_path = os.path.join(self.output_dir, f"clean.jsonl")
        self.clean_lines_before = _count_lines(clean_path)
        self.clean_file = open(clean_path, "a", encoding="utf-8")


    def close_spider(self, spider):
        if self.out_file:
            self.out_file.close()
        if self.clean_file:
            self.clean_file.close()

        self._write_summary(spider)

    def _write_summary(self, spider):
        out_path = os.path.join(self.output_dir, "pages.jsonl")
        clean_path = os.path.join(self.output_dir, "clean.jsonl")

        # reconciliation: re-count each file from disk after closing (i.e.
        # flushing) it, and compare against what we intended to write this
        # run - catches silent data loss (a crash, a swallowed disk-full
        # error, ...) that "we logged it" alone wouldn't reveal
        pages_actual = _count_lines(out_path) - self.pages_lines_before
        clean_actual = _count_lines(clean_path) - self.clean_lines_before
        reconciliation = {
            "pages_jsonl": {
                "expected": self.pages_written,
                "actual": pages_actual,
                "ok": pages_actual == self.pages_written,
            },
            "clean_jsonl": {
                "expected": self.clean_written,
                "actual": clean_actual,
                "ok": clean_actual == self.clean_written,
            },
        }
        for name, result in reconciliation.items():
            if not result["ok"]:
                spider.logger.error(
                    "Output reconciliation FAILED for %s: expected %d new line(s), found %d - "
                    "some crawled data may be missing from disk",
                    name, result["expected"], result["actual"],
                )

        stats = spider.crawler.stats.get_stats()
        crawl_start_time = getattr(spider, "crawl_start_time", None)
        total_seconds = time.time() - crawl_start_time if crawl_start_time else None
        summary = {
            "finished_at": utc_timestamp(),
            "total_time": format_duration(total_seconds),
            "total_time_seconds": round(total_seconds, 2) if total_seconds is not None else None,
            "fetched": stats.get("response_received_count", 0),
            "stored": {
                "total": self.clean_written,
                "html": stats.get("stored/html", 0),
                "pdf": stats.get("stored/pdf", 0),
            },
            "dropped": {
                "duplicate": stats.get("dropped/duplicate", 0),
                "empty": stats.get("dropped/empty", 0),
            },
            "by_source": {
                "seed": stats.get("stored/source/seed", 0),
                "link": stats.get("stored/source/link", 0),
                "sitemap": stats.get("stored/source/sitemap", 0),
            },
            "tables": {
                "pages_with_tables": stats.get("tables/pages_with_tables", 0),
                "total_tables": stats.get("tables/total_tables", 0),
            },
            "reconciliation": reconciliation,
        }

        summary_path = os.path.join(self.output_dir, "summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        spider.logger.info("Crawl summary written to %s: %s", summary_path, json.dumps(summary))

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        record = {
            "url": adapter.get("url"),
            "html": adapter.get("html"),
            "depth": adapter.get("depth"),
            "crawledAt": adapter.get("crawledAt"),
            "content_hash": adapter.get("content_hash"),
            "source": adapter.get("source"),
        }
        self.out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.pages_written += 1

        clean_record = {
            "url": record["url"],
            "cleaned_content": adapter.get("cleaned_content", ""),
            "tables": adapter.get("tables", []),
            "source": adapter.get("source"),
        }
        self.clean_file.write(json.dumps(clean_record, ensure_ascii=False) + "\n")
        self.clean_written += 1

        source = adapter.get("source", "unknown")
        spider.crawler.stats.inc_value(f"stored/source/{source}")
        spider.crawler.stats.inc_value("stored/pdf" if adapter.get("is_pdf") else "stored/html")

        return item
