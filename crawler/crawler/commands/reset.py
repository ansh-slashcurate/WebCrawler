import argparse
import glob
import os

import redis
from scrapy.commands import ScrapyCommand

SPIDER_NAME = "rag_crawler"


class Command(ScrapyCommand):
    requires_project = True
    requires_crawler_process = False

    def short_desc(self):
        return "Clear crawl state (Redis frontier + dedup set) and output files for a fresh crawl"

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        super().add_options(parser)
        parser.add_argument(
            "--keep-output",
            action="store_true",
            help="don't delete output/*.jsonl files, only clear Redis state",
        )

    def run(self, args, opts):
        redis_url = self.settings.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(redis_url)
        deleted = client.delete(
            f"{SPIDER_NAME}:requests",
            f"{SPIDER_NAME}:dupefilter",
            "content_hashes",
        )
        print(f"Redis ({redis_url}): cleared {deleted} key(s)")

        if opts.keep_output:
            print("Output: kept (--keep-output)")
            return

        output_dir = self.settings.get("OUTPUT_DIR", "output")
        removed = 0
        for path in glob.glob(os.path.join(output_dir, "*.jsonl")):
            os.remove(path)
            removed += 1
        print(f"Output ({output_dir}/): removed {removed} file(s)")
