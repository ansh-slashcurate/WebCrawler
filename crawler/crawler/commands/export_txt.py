import argparse
import json
import os
import re

from scrapy.commands import ScrapyCommand

from crawler.pipelines import slugify, resolve_run_dir

CLEAN_FILENAMES = ("clean_normalized.jsonl", "clean.jsonl")
PARAGRAPH_CHUNK_SIZE = 800


class Command(ScrapyCommand):
    requires_project = True
    requires_crawler_process = False

    def short_desc(self):
        return (
            "Export output/clean.jsonl (or clean_normalized.jsonl, if present) into "
            "a single combined RAG-ready .txt file"
        )

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        super().add_options(parser)
        parser.add_argument(
            "--in",
            dest="in_name",
            default=None,
            help="input filename under the run dir (default: clean_normalized.jsonl if "
                 "it exists, else clean.jsonl)",
        )
        parser.add_argument(
            "--out",
            dest="out_name",
            default="corpus.txt",
            help="output filename under the run dir (default: corpus.txt)",
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
                 "(default: the current directory if it already contains a clean "
                 "jsonl file, else the most recently modified run)",
        )

    def _resolve_run_dir(self, opts):
        # if the user has already cd'd into a run folder (or an entity/run folder),
        # just use it directly rather than re-deriving one from OUTPUT_DIR - that
        # let people run `scrapy export_txt` from wherever they're looking at the
        # crawl output instead of having to pass --entity/--run to point back at it
        if not opts.entity and not opts.run:
            cwd = os.getcwd()
            if any(os.path.exists(os.path.join(cwd, name)) for name in CLEAN_FILENAMES):
                return cwd

        output_dir = self.settings.get("OUTPUT_DIR", "output")
        if opts.entity:
            output_dir = os.path.join(output_dir, slugify(opts.entity))
        return resolve_run_dir(output_dir, opts.run)

    def _format_tables(self, tables):
        blocks = []
        for table in tables:
            lines = []
            for row in table:
                row_text = "; ".join(f"{k}: {v}" for k, v in row.items() if v)
                if row_text:
                    lines.append(row_text)
            if lines:
                blocks.append("\n".join(lines))
        return blocks

    def _format_comments(self, comments):
        lines = []
        for comment in comments:
            text = (comment.get("text") or "").strip()
            if not text:
                continue
            author = comment.get("author") or "Unknown"
            lines.append(f"{author}: {text}")
        return lines

    def _paragraphs(self, content, chunk_size=PARAGRAPH_CHUNK_SIZE):
        """Re-introduce paragraph breaks into content that normalize_text flattened
        to one long line. A single multi-thousand-character line per page has no
        internal structure for a RAG pipeline's text splitter to key off of, so it
        either gets embedded as one oversized/truncated chunk or split at an
        arbitrary character offset mid-sentence - both hurt retrieval quality in a
        way PDF/DOCX extraction (which keeps paragraph breaks) doesn't suffer from.
        """
        sentences = re.split(r"(?<=[.!?])\s+", content)
        paragraphs = []
        current = []
        current_len = 0
        for sentence in sentences:
            if not sentence:
                continue
            current.append(sentence)
            current_len += len(sentence) + 1
            if current_len >= chunk_size:
                paragraphs.append(" ".join(current))
                current = []
                current_len = 0
        if current:
            paragraphs.append(" ".join(current))
        return paragraphs

    def _render_record(self, record):
        """Render one page as self-contained, clearly-delimited text: a metadata
        header search tools can key off of, prose broken into real paragraphs, and
        table data visually separated from prose so a naive splitter doesn't blend
        the two. Returns None if the record has nothing worth exporting.
        """
        content = record.get("cleaned_content", "")
        table_blocks = self._format_tables(record.get("tables") or [])
        comment_lines = self._format_comments(record.get("comments") or [])
        if not content and not table_blocks and not comment_lines:
            return None

        parts = [f"URL: {record.get('url', '')}"]
        if record.get("entity"):
            parts.append(f"ENTITY: {record.get('entity')}")
        parts = ["\n".join(parts)]

        if content:
            parts.append("\n\n".join(self._paragraphs(content)))
        if table_blocks:
            parts.append("TABLE DATA:\n" + "\n\n".join(table_blocks))
        if comment_lines:
            parts.append("COMMENTS:\n" + "\n\n".join(comment_lines))

        return "\n\n".join(parts)

    def run(self, args, opts):
        output_dir = self._resolve_run_dir(opts)

        in_name = opts.in_name
        if not in_name:
            for name in CLEAN_FILENAMES:
                if os.path.exists(os.path.join(output_dir, name)):
                    in_name = name
                    break
            else:
                in_name = "clean.jsonl"

        in_path = os.path.join(output_dir, in_name)
        out_path = os.path.join(output_dir, opts.out_name)

        if not os.path.exists(in_path):
            print(f"No input file at {in_path}")
            return

        written = 0
        with open(in_path, "r", encoding="utf-8") as infile, \
                open(out_path, "w", encoding="utf-8") as outfile:
            for line in infile:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                rendered = self._render_record(record)
                if rendered is None:
                    continue

                outfile.write(rendered)
                outfile.write("\n\n" + ("=" * 80) + "\n\n")
                written += 1

        print(f"Read from {in_path}, wrote {written} record(s) to {out_path}")
