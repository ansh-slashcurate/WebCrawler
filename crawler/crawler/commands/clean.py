import argparse
import json
import os

from scrapy.commands import ScrapyCommand

from crawler.pipelines import normalize_text, slugify, resolve_run_dir

MIN_LENGTH = 50


class Command(ScrapyCommand):
    requires_project = True
    requires_crawler_process = False

    def short_desc(self):
        return (
            "Backfill: re-normalize output/clean.jsonl and drop empty/short pages "
            "into a separate file. New crawls are already normalized by "
            "NormalizationPipeline - this is only needed for pre-existing rows."
        )

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        super().add_options(parser)
        parser.add_argument(
            "--min-length",
            type=int,
            default=MIN_LENGTH,
            help=f"drop records whose cleaned_content is shorter than this many characters (default: {MIN_LENGTH})",
        )
        parser.add_argument(
            "--entity",
            default=None,
            help="operate on output/<entity-slug>/ instead of output/ "
                 "(must match the -a entity= used to crawl)",
        )
        parser.add_argument(
            "--run",
            default=None,
            help="operate on a specific run id under output/[<entity-slug>/] "
                 "(default: the most recently modified run)",
        )

    def run(self, args, opts):
        output_dir = self.settings.get("OUTPUT_DIR", "output")
        if opts.entity:
            output_dir = os.path.join(output_dir, slugify(opts.entity))
        output_dir = resolve_run_dir(output_dir, opts.run)
        in_path = os.path.join(output_dir, "clean.jsonl")
        out_path = os.path.join(output_dir, "clean_normalized.jsonl")

        if not os.path.exists(in_path):
            print(f"No input file at {in_path}")
            return

        kept = 0
        dropped = 0
        with open(in_path, "r", encoding="utf-8") as infile, \
                open(out_path, "w", encoding="utf-8") as outfile:
            for line in infile:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                text = normalize_text(record.get("cleaned_content", ""))
                if len(text) < opts.min_length:
                    dropped += 1
                    continue
                record["cleaned_content"] = text
                outfile.write(json.dumps(record, ensure_ascii=False) + "\n")
                kept += 1

        print(f"Wrote {kept} record(s) to {out_path} (dropped {dropped} empty/short)")
