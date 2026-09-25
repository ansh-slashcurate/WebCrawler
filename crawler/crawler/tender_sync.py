"""webapi.py-side classification step for a finished tender crawl's
tenders.jsonl, plus the pipeline event log both this and watsonx_client
write to.

Deliberately NOT imported by crawler/spiders/crawler.py or crawler/pipelines.py:
the crawl subprocess stays fully disk-based and Postgres-free (see
crawler/db.py's docstring) - this module runs from webapi.py only, after a
crawl has already finished. It does still read tender TAGS from Postgres
(crawler.models.TenderTag) - those are small, admin-edited config, same as
bank_sites/users, unlike the tenders themselves. Tender records and their
classification stay in tenders.jsonl end to end (self-hosted deploys and
this project's crawl/extraction code being reused directly by a separate
RAG project both favor the tender data path staying disk-only, with no
SQLAlchemy/Postgres dependency, the same as pages.jsonl/clean.jsonl).

Pipeline debugging events (every LLM call, classify start-finish, failures)
go to a log FILE, not a database table - and the SAME file the crawl
subprocess itself already writes to (logs/crawl_<date>.log, one shared file
per calendar day - see crawler/settings.py's LOG_FILE), as one JSON line per
event interleaved with Scrapy's own plain-text lines, rather than a second,
separate log file for this one extra step. settings.py's own LOG_FILE
comment already documents that two processes appending to this file at the
exact same moment can interleave lines - an accepted, known tradeoff at this
project's scale, not something newly introduced here.
"""
import datetime
import json
import logging
from pathlib import Path

from crawler import watsonx_client
from crawler.db import SessionLocal
from crawler.models import TenderTag

logger = logging.getLogger(__name__)

# crawler/ - the same directory webapi.py/settings.py resolve BASE_DIR/LOG_DIR
# from, so this lands on the exact same file crawler/settings.py's LOG_FILE
# points the crawl subprocess at, regardless of the working directory the
# API process happens to be run from
_BASE_DIR = Path(__file__).resolve().parent.parent
_LOG_DIR = _BASE_DIR / "logs"


def _crawl_log_path(day=None):
    """Must match crawler/settings.py's LOG_FILE naming exactly - one file
    shared by the crawl subprocess and this module, per calendar day."""
    return _LOG_DIR / f"crawl_{(day or datetime.datetime.now()):%Y%m%d}.log"


def log_event(run_id, entity_slug, level, event, message, details=None):
    """Appends one JSON line to today's shared logs/crawl_<date>.log
    (interleaved with the crawl subprocess's own plain-text lines - see this
    module's docstring) and mirrors it through the ordinary Python logger
    for live console/uvicorn visibility. A logging failure must never break
    the actual pipeline work it's describing, so a file-write error here is
    caught and only logged locally, never raised."""
    log_fn = {"error": logger.error, "warning": logger.warning}.get(level, logger.info)
    log_fn("[%s/%s] %s: %s", entity_slug, run_id, event, message)

    entry = {
        "ts": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "level": level, "run_id": run_id, "entity_slug": entity_slug,
        "event": event, "message": message, "details": details,
    }
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_crawl_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed to write pipeline log entry for event %r (run %s)", event, run_id)


def read_recent_events(run_id, entity_slug=None, limit=100):
    """Reads this run's pipeline log entries back out of the shared daily
    crawl log file(s) log_event writes into - scans today's file and
    yesterday's too, in case a long-running or late-night run straddles
    midnight. Non-JSON lines (the crawl subprocess's own plain-text log
    lines, sharing this same file) are silently skipped. Returns up to
    `limit` entries, oldest first."""
    entries = []
    for days_ago in (0, 1):
        path = _crawl_log_path(datetime.datetime.now() - datetime.timedelta(days=days_ago))
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("run_id") != run_id:
                continue
            if entity_slug and entry.get("entity_slug") != entity_slug:
                continue
            entries.append(entry)

    entries.sort(key=lambda e: e.get("ts", ""))
    return entries[-limit:]


def tenders_jsonl_path(base_output_dir, entity_slug, run_id):
    base = Path(base_output_dir)
    if entity_slug and entity_slug != "default":
        base = base / entity_slug
    return base / run_id / "tenders.jsonl"


def _load_enabled_tags(tag_ids=None):
    db = SessionLocal()
    try:
        query = db.query(TenderTag).filter(TenderTag.enabled.is_(True))
        if tag_ids:
            query = query.filter(TenderTag.id.in_(tag_ids))
        return [{"name": t.name, "description": t.description} for t in query.all()]
    finally:
        db.close()


def classify_pending_records(base_output_dir, entity_slug, run_id, tag_ids=None):
    """Classifies every "pending" record in this run's tenders.jsonl against
    the given (or, if None, every enabled) tags, then rewrites the file in
    place with classification/matched_tags/reason filled in - the same
    atomic temp-file-then-rename approach the original (pre-DB) classify job
    used, so a mid-write crash can't leave tenders.jsonl half-written.
    Returns {"total", "done", "matched"} for progress reporting. Logs a
    pipeline event at start and at finish (or on failure) - per-batch LLM
    call detail is logged inside watsonx_client.classify_batch itself."""
    path = tenders_jsonl_path(base_output_dir, entity_slug, run_id)
    if not path.exists():
        log_event(run_id, entity_slug, "warning", "classify_skipped", f"No tenders.jsonl found at {path}")
        return {"total": 0, "done": 0, "matched": 0}

    try:
        tags = _load_enabled_tags(tag_ids)
        if not tags:
            log_event(run_id, entity_slug, "warning", "classify_skipped",
                      "No enabled tender tags to classify against")
            return {"total": 0, "done": 0, "matched": 0}

        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        pending_indices = [i for i, r in enumerate(records) if r.get("classification") == "pending"]
        if not pending_indices:
            return {"total": 0, "done": 0, "matched": 0}

        log_event(
            run_id, entity_slug, "info", "classify_started",
            f"Classifying {len(pending_indices)} pending tender(s) against {len(tags)} tag(s)",
            details={"tag_names": [t["name"] for t in tags], "record_count": len(pending_indices)},
        )

        results = watsonx_client.classify_batch([records[i] for i in pending_indices], tags)

        matched_count = 0
        for local_id, result in results.items():
            i = pending_indices[int(local_id)]
            records[i]["classification"] = result["classification"]
            records[i]["matched_tags"] = result["matched_tags"]
            records[i]["reason"] = result["reason"]
            if result["matched_tags"]:
                matched_count += 1

        tmp_path = path.with_name(path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp_path.replace(path)

        log_event(
            run_id, entity_slug, "info", "classify_finished",
            f"Classified {len(results)} tender(s), {matched_count} matched at least one tag",
            details={"done": len(results), "matched": matched_count},
        )
        return {"total": len(pending_indices), "done": len(results), "matched": matched_count}
    except Exception as e:
        log_event(run_id, entity_slug, "error", "classify_failed", str(e))
        raise
