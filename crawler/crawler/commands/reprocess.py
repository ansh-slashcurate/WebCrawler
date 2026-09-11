import argparse
import json
import os

import trafilatura
from scrapy.commands import ScrapyCommand

from crawler.pipelines import normalize_text, extract_tables, slugify, resolve_run_dir
from crawler.ytpipeline import (
    extract_video_details,
    extract_video_id,
    render_video_text,
    fetch_comments,
    CommentsDisabled,
    YoutubeApiError,
)

MIN_LENGTH = 50


class Command(ScrapyCommand):
    requires_project = True
    requires_crawler_process = False

    def short_desc(self):
        return (
            "Regenerate output/clean.jsonl from output/pages.jsonl by re-running "
            "extraction/normalization against the raw stored html/pdf text. Unlike "
            "the `clean` command (which only re-normalizes already-cleaned text and "
            "can't recover characters a buggy normalize_text already deleted), this "
            "re-derives cleaned_content from the original source."
        )

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        super().add_options(parser)
        parser.add_argument(
            "--min-length",
            type=int,
            default=MIN_LENGTH,
            help=f"drop records whose cleaned_content is shorter than this many characters, "
                 f"unless they have tables (default: {MIN_LENGTH})",
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
        in_path = os.path.join(output_dir, "pages.jsonl")
        out_path = os.path.join(output_dir, "clean.jsonl")

        if not os.path.exists(in_path):
            print(f"No input file at {in_path}")
            return

        # comments require a live API call (unlike everything else here, which
        # is re-derived offline from the stored html) - best-effort, skipped
        # with a note if no key is configured, rather than making the whole
        # command require one
        youtube_api_key = os.environ.get(self.settings.get("YOUTUBE_API_KEY_ENV", "YOUTUBE_API_KEY"))
        max_comments = self.settings.getint("YOUTUBE_MAX_COMMENTS", 50)
        if not youtube_api_key:
            print("No YouTube API key configured - video pages will be reprocessed without comments")

        kept = 0
        dropped = 0
        with open(in_path, "r", encoding="utf-8") as infile, \
                open(out_path, "w", encoding="utf-8") as outfile:
            for line in infile:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                html = record.get("html", "")
                url = record.get("url", "")

                # pages.jsonl doesn't persist is_pdf, so infer it the same way the
                # spider decides to take the PDF-extraction branch: URL extension
                # (the spider only takes that branch for application/pdf responses,
                # which on this crawl always had a .pdf URL - confirmed against
                # summary.json's stored/pdf count of 128)
                is_pdf = url.lower().endswith(".pdf")

                video_details = extract_video_details(html, url)
                comments = []
                if video_details is not None:
                    cleaned_content = normalize_text(render_video_text(video_details))
                    tables = []
                    video_id = extract_video_id(url)
                    if youtube_api_key and video_id:
                        try:
                            comments = fetch_comments(video_id, youtube_api_key, max_comments)
                        except CommentsDisabled:
                            comments = []
                        except YoutubeApiError as e:
                            print(f"Comment fetch failed for {url}: {e}")
                elif is_pdf:
                    cleaned_content = normalize_text(html)
                    tables = []
                else:
                    raw_content = trafilatura.extract(html, include_tables=False, favor_recall=True) or ""
                    cleaned_content = normalize_text(raw_content)
                    tables = extract_tables(html)

                if len(cleaned_content) < opts.min_length and not tables and not comments:
                    dropped += 1
                    continue

                clean_record = {
                    "url": url,
                    "cleaned_content": cleaned_content,
                    "tables": tables,
                    "comments": comments,
                    "source": record.get("source"),
                }
                if video_details is not None:
                    clean_record["video"] = video_details
                outfile.write(json.dumps(clean_record, ensure_ascii=False) + "\n")
                kept += 1

        print(f"Wrote {kept} record(s) to {out_path} (dropped {dropped} empty/short)")
