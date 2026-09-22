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

from crawler.ytpipeline import render_video_text
from crawler.tender import extract_tender_records


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


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def resolve_run_dir(output_dir, run_id=None):
    """Resolve an (already entity-scoped, if applicable) output dir down to one
    run's subfolder: the given run_id, or otherwise whichever run subfolder was
    modified most recently. Used by the reprocess/export_txt/clean commands so
    they operate on one crawl's files instead of guessing a fixed filename."""
    if run_id:
        return os.path.join(output_dir, run_id)
    if os.path.isdir(output_dir):
        run_dirs = [d for d in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, d))]
        if run_dirs:
            latest = max(run_dirs, key=lambda d: os.path.getmtime(os.path.join(output_dir, d)))
            return os.path.join(output_dir, latest)
    return output_dir


def normalize_text(text: str) -> str:
    # drop well-formed leftover HTML tags trafilatura missed
    text = re.sub(r"<[^>]*>", "", text)
    # drop broken tag remnants that lost their opening '<' (e.g. "NDS-OMli>"
    # from a stray <li> merged into the preceding word during extraction)
    text = re.sub(rf"([A-Za-z])(?:{BROKEN_TAG_NAMES})>", r"\1", text)
    # de-obfuscate emails before stripping punctuation below
    text = text.replace("[at]", "@").replace("[dot]", ".")
    text = text.replace("|", " ")
    text = text.replace("-", " ")
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
        # scope the dedup set per entity AND per run (spider.run_id, assigned in
        # WebsiteSpider._init_run): per-entity so a page stored while crawling
        # entity A isn't wrongly treated as a duplicate of entity B's crawl; per-run
        # so a later re-crawl gets a genuinely fresh, complete snapshot instead of
        # having everything unchanged silently dropped as a "duplicate" of the
        # first-ever run. A resumed (not fresh) run reuses the same run_id, so
        # dedup still works correctly across a crash/restart of the same run.
        scope = getattr(spider, "run_scope", None) or "default"
        run_id = getattr(spider, "run_id", None)
        self.hash_set_key = f"content_hashes:{scope}:{run_id}" if run_id else f"content_hashes:{scope}"

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        content_hash = hashlib.sha256(adapter["html"].encode("utf-8")).hexdigest()

        # SADD returns 0 if the member already existed - atomic, so two
        # workers hashing the same content at the same instant can't both
        # think they're first.
        is_new = self.client.sadd(self.hash_set_key, content_hash)
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

        # YoutubePipeline (runs before this one) already parsed video details
        # from the page HTML and set this field for a recognized YouTube
        # video URL - nothing left to extract here besides turning it to text
        video_details = adapter.get("youtube_video")
        if video_details is not None:
            cleaned_content = normalize_text(render_video_text(video_details))
            tables = []
        elif adapter.get("is_pdf"):
            # the spider already extracted plain text from the PDF - there's
            # no HTML markup here, so trafilatura/table extraction don't apply
            cleaned_content = normalize_text(html)
            tables = []
        else:
            # tables are extracted separately (below) as structured data, so
            # they don't get linearized into prose and mangled by normalize_text.
            # favor_recall=True: the default precision-favoring extraction drops
            # card/grid-style content (e.g. a team/staff directory entry) as
            # boilerplate even though it's real content worth keeping in the corpus
            raw_content = trafilatura.extract(html, include_tables=False, favor_recall=True) or ""
            cleaned_content = normalize_text(raw_content)
            tables = extract_tables(html)

        # comments (also set by YoutubePipeline, [] for every non-video page)
        comments = adapter.get("comments") or []

        if not cleaned_content and not tables and not comments:
            spider.crawler.stats.inc_value("dropped/empty")
            raise DropItem(f"No extractable content: {adapter.get('url')}")

        if tables:
            spider.crawler.stats.inc_value("tables/pages_with_tables")
            spider.crawler.stats.inc_value("tables/total_tables", count=len(tables))

        adapter["cleaned_content"] = cleaned_content
        adapter["tables"] = tables
        adapter["comments"] = comments
        return item


# tender/RFP extraction pipeline - only active in tender_mode (see
# crawler.spiders.crawler.WebsiteSpider + crawler.tender). Structural
# extraction only, unfiltered: every record found is attached with
# classification="pending" - a later, separate step (webapi.py's /classify
# endpoint + crawler.watsonx_client) decides relevance against a user's own
# tags. Never raises DropItem - a page with zero tender records found on it
# may still be a perfectly ordinary page worth keeping.
class TenderExtractionPipeline:
    def process_item(self, item, spider):
        if not getattr(spider, "tender_mode", False):
            return item

        adapter = ItemAdapter(item)
        records = extract_tender_records(adapter.get("html", ""), adapter.get("url"))
        if records:
            adapter["tender_records"] = records
        return item


# entity relevance pipeline - only active when the spider was started with
# an entity query (spider.entity_query); re-checks against cleaned_content
# (post-trafilatura, so no markup noise) rather than trusting the spider's
# own raw-text scoring, and is the actual gate on what reaches storage
class EntityRelevancePipeline:
    def process_item(self, item, spider):
        # tender_mode's relevance gate is the tag-classification step
        # instead of bank-name mentions - a pure tenders-listing table often
        # never repeats the bank's own name, so this pipeline's usual check
        # would silently drop pages whose tender_records TenderExtractionPipeline
        # (priority 160, runs just before this one) already extracted
        if getattr(spider, "tender_mode", False):
            return item

        entity_query = getattr(spider, "entity_query", None)
        if not entity_query:
            return item

        adapter = ItemAdapter(item)
        # a video's own title/description may not mention the entity even
        # when its comments do (or vice versa) - score against both so a
        # YouTube page isn't dropped just because the entity only came up in
        # the discussion, not the video's own metadata
        comments_text = " ".join(c.get("text", "") for c in (adapter.get("comments") or []))
        score_text = adapter.get("cleaned_content", "") + " " + comments_text
        score, is_relevant, matched = entity_query.score(score_text)

        if not is_relevant:
            spider.crawler.stats.inc_value("dropped/irrelevant")
            raise DropItem(f"Not relevant to entity '{entity_query.name}': {adapter.get('url')}")

        adapter["entity"] = entity_query.name
        adapter["relevance_score"] = score
        adapter["matched_terms"] = matched
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
        self.tenders_written = 0

    @classmethod
    def from_crawler(cls, crawler):
        return cls(output_dir=crawler.settings.get("OUTPUT_DIR", "output"))


    def open_spider(self, spider):
        # scope the output dir per entity (different entity crawls of the same
        # seeds don't intermix corpora) and per run (spider.run_id - a fresh run
        # gets its own folder so old retrieved content is never overwritten or
        # appended-over; a resumed run reuses the same folder/files)
        entity_query = getattr(spider, "entity_query", None)
        if entity_query:
            self.output_dir = os.path.join(self.output_dir, slugify(entity_query.name))
        run_id = getattr(spider, "run_id", None)
        if run_id:
            self.output_dir = os.path.join(self.output_dir, run_id)

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        out_path = os.path.join(self.output_dir, f"pages.jsonl")
        self.pages_lines_before = _count_lines(out_path)
        self.out_file = open(out_path, "a", encoding="utf-8")

        clean_path = os.path.join(self.output_dir, f"clean.jsonl")
        self.clean_lines_before = _count_lines(clean_path)
        self.clean_file = open(clean_path, "a", encoding="utf-8")

        tenders_path = os.path.join(self.output_dir, "tenders.jsonl")
        self.tenders_lines_before = _count_lines(tenders_path)
        self.tenders_file = open(tenders_path, "a", encoding="utf-8")


    def close_spider(self, spider):
        if self.out_file:
            self.out_file.close()
        if self.clean_file:
            self.clean_file.close()
        if self.tenders_file:
            self.tenders_file.close()

        self._write_summary(spider)

    def _write_summary(self, spider):
        out_path = os.path.join(self.output_dir, "pages.jsonl")
        clean_path = os.path.join(self.output_dir, "clean.jsonl")
        tenders_path = os.path.join(self.output_dir, "tenders.jsonl")

        # reconciliation: re-count each file from disk after closing (i.e.
        # flushing) it, and compare against what we intended to write this
        # run - catches silent data loss (a crash, a swallowed disk-full
        # error, ...) that "we logged it" alone wouldn't reveal
        pages_actual = _count_lines(out_path) - self.pages_lines_before
        clean_actual = _count_lines(clean_path) - self.clean_lines_before
        tenders_actual = _count_lines(tenders_path) - self.tenders_lines_before
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
            "tenders_jsonl": {
                "expected": self.tenders_written,
                "actual": tenders_actual,
                "ok": tenders_actual == self.tenders_written,
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
            "run_id": getattr(spider, "run_id", None),
            "finished_at": utc_timestamp(),
            "total_time": format_duration(total_seconds),
            "total_time_seconds": round(total_seconds, 2) if total_seconds is not None else None,
            "fetched": stats.get("response_received_count", 0),
            "stored": {
                "total": self.clean_written,
                "html": stats.get("stored/html", 0),
                "pdf": stats.get("stored/pdf", 0),
            },
            "tenders": self.tenders_written,
            "dropped": {
                "duplicate": stats.get("dropped/duplicate", 0),
                "empty": stats.get("dropped/empty", 0),
                "irrelevant": stats.get("dropped/irrelevant", 0),
            },
            "blocked": stats.get("blocked/pages", 0),
            "by_source": {
                "seed": stats.get("stored/source/seed", 0),
                "link": stats.get("stored/source/link", 0),
                "sitemap": stats.get("stored/source/sitemap", 0),
                "youtube_search": stats.get("stored/source/youtube_search", 0),
            },
            "tables": {
                "pages_with_tables": stats.get("tables/pages_with_tables", 0),
                "total_tables": stats.get("tables/total_tables", 0),
            },
            "youtube": {
                "videos_with_comments": stats.get("youtube/videos_with_comments", 0),
                "total_comments": stats.get("youtube/total_comments", 0),
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
            "comments": adapter.get("comments", []),
            "source": adapter.get("source"),
        }
        if adapter.get("entity") is not None:
            clean_record["entity"] = adapter.get("entity")
            clean_record["relevance_score"] = adapter.get("relevance_score")
            clean_record["matched_terms"] = adapter.get("matched_terms")
        if adapter.get("youtube_video") is not None:
            clean_record["video"] = adapter.get("youtube_video")
        self.clean_file.write(json.dumps(clean_record, ensure_ascii=False) + "\n")
        self.clean_written += 1

        for tender_record in adapter.get("tender_records") or []:
            self.tenders_file.write(json.dumps(tender_record, ensure_ascii=False) + "\n")
            self.tenders_written += 1
        spider.crawler.stats.inc_value("stored/tenders", count=len(adapter.get("tender_records") or []))

        if adapter.get("comments"):
            spider.crawler.stats.inc_value("youtube/videos_with_comments")
            spider.crawler.stats.inc_value("youtube/total_comments", count=len(adapter.get("comments")))

        source = adapter.get("source", "unknown")
        spider.crawler.stats.inc_value(f"stored/source/{source}")
        spider.crawler.stats.inc_value("stored/pdf" if adapter.get("is_pdf") else "stored/html")

        return item
