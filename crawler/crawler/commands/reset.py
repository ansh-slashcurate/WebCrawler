import argparse
import os
from pathlib import Path

import redis
from scrapy.commands import ScrapyCommand

from crawler.pipelines import slugify

SPIDER_NAME = "rag_crawler"


class Command(ScrapyCommand):
    requires_project = True
    requires_crawler_process = False

    def short_desc(self):
        return "Clear crawl state (Redis frontier + dedup set + run marker) and output files for a fresh crawl"

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        super().add_options(parser)
        parser.add_argument(
            "--keep-output",
            action="store_true",
            help="don't delete output/**/*.jsonl files, only clear Redis state",
        )
        parser.add_argument(
            "--entity",
            default=None,
            help="reset the entity-scoped dedup set / output/<entity-slug>/ dir "
                 "instead of the shared ones (must match the -a entity= used to crawl)",
        )

    def run(self, args, opts):
        redis_url = self.settings.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(redis_url)
        scope = slugify(opts.entity) if opts.entity else "default"

        # content_hashes is scoped per-run (content_hashes:<scope>:<run_id>), so
        # there's no single fixed key to delete - scan for every run under this
        # entity/scope instead
        keys = [f"{SPIDER_NAME}:requests", f"{SPIDER_NAME}:dupefilter", f"{SPIDER_NAME}:run_id:{scope}"]
        keys += list(client.scan_iter(match=f"content_hashes:{scope}:*"))
        deleted = client.delete(*keys) if keys else 0
        print(f"Redis ({redis_url}): cleared {deleted} key(s)")

        if opts.keep_output:
            print("Output: kept (--keep-output)")
            return

        output_dir = self.settings.get("OUTPUT_DIR", "output")
        if opts.entity:
            output_dir = os.path.join(output_dir, slugify(opts.entity))

        # each crawl run lives in its own output/<entity-slug>/<run_id>/ subfolder
        # (see WebsiteSpider._init_run) - this removes *.jsonl across ALL of them,
        # i.e. all run history for this scope, not just the latest one
        removed = 0
        for path in Path(output_dir).rglob("*.jsonl"):
            path.unlink()
            removed += 1
        print(f"Output ({output_dir}/): removed {removed} file(s) across all run(s)")
