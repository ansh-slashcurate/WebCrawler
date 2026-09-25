"""IBM watsonx classification of already-extracted tender records against a
user's own tags - the only place an LLM is used in this project. Kept
strictly separate from crawl time: crawler/tender.py does structural
extraction with free local keywords only, and stores every record it finds
as classification="pending". This module is called once, later, by
webapi.py's POST /api/runs/{entity}/{run_id}/tenders/classify.

Credentials (WATSONX_API_KEY / WATSONX_PROJECT_ID / WATSONX_URL, optionally
WATSONX_MODEL_ID) come from the environment only (crawler/.env, loaded the
same way settings.py/webapi.py already load it) - never logged, never
returned by any API response, no Settings-page UI. Same "env var name only,
never the secret" convention this project already uses for
auth.json/YOUTUBE_API_KEY_ENV.

Uses LangChain's IBM integration (langchain-ibm's ChatWatsonx) rather than
the raw ibm-watsonx-ai SDK, so the prompt and its expected output are a
typed LangChain structured-output call instead of hand-rolled JSON parsing.
"""
import ast
import logging
import os
import time

from pydantic import BaseModel
from prompts.llm_prompt import Human_Prompt, System_Prompt

logger = logging.getLogger(__name__)

BATCH_SIZE = 8
# batches were being sent to watsonx one at a time, each a blocking call -
# for a bank with thousands of pending tenders (confirmed live: Bank of
# Maharashtra alone had 2318) that's hundreds of sequential round trips,
# each paying full model latency before the next even starts. LangChain's
# own Runnable.batch() sends up to this many requests concurrently through
# a thread pool instead - wall-clock time drops roughly in proportion to
# this number, network/rate-limit permitting. Override via
# WATSONX_CONCURRENCY in .env if watsonx's own rate limit needs it lower.
MAX_CONCURRENT_BATCHES = int(os.environ.get("WATSONX_CONCURRENCY", "5"))
# ibm/granite-3-8b-instruct isn't in this account's supported-model list
# (varies by watsonx plan/region) - meta-llama/llama-3-3-70b-instruct is a
# capable general instruct model that is. Override via WATSONX_MODEL_ID in
# .env if your account supports a different one.
DEFAULT_MODEL_ID = "meta-llama/llama-3-3-70b-instruct"
# WATSONX_APIKEY (no underscore before KEY) matches the ibm-watsonx-ai/
# langchain-ibm convention and crawler/.env - not WATSONX_API_KEY
REQUIRED_ENV_VARS = ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL")


class WatsonxConfigError(Exception):
    """Raised when a required WATSONX_* environment variable is missing."""


class TenderMatch(BaseModel):
    record_id: str
    matched_tags: list[str]
    reason: str


class BatchResult(BaseModel):
    results: list[TenderMatch]


def _require_env():
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise WatsonxConfigError(
            f"Missing environment variable(s) for watsonx: {', '.join(missing)} "
            "(set them in crawler/.env)"
        )


def _generation_params():
    """Optional PARAMS env var (crawler/.env) - a Python-dict-literal string
    like "{'decoding_method': 'greedy', 'max_new_tokens': 1000}", passed
    through to ChatWatsonx as its `params`. Not required - falls back to
    ChatWatsonx's own defaults if unset or unparsable."""
    raw = os.environ.get("PARAMS")
    if not raw:
        return None
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None


def _build_chain():
    # imported lazily so a deployment that never uses the Tenders/classify
    # feature doesn't need langchain-ibm installed/importable just to run
    # `uvicorn webapi:app` or a plain crawl
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_ibm import ChatWatsonx

    _require_env()
    model = ChatWatsonx(
        model_id=os.environ.get("WATSONX_MODEL_ID", DEFAULT_MODEL_ID),
        url=os.environ["WATSONX_URL"],
        apikey=os.environ["WATSONX_APIKEY"],
        project_id=os.environ["WATSONX_PROJECT_ID"],
        params=_generation_params(),
    )
    # role identifiers LangChain recognizes are "system"/"human"/"ai"/... -
    # not arbitrary labels like "system prompt"/"human prompt", which raise
    # at prompt-build time instead of at model-call time
    prompt = ChatPromptTemplate.from_messages([
        ("system", System_Prompt),
        ("human", Human_Prompt),
    ])
    return prompt | model.with_structured_output(BatchResult)


def _format_tags(tags):
    return "\n".join(f"- {t['name']}: {t.get('description') or '(no description)'}" for t in tags)


def _truncate(text, limit=200):
    """Keeps a long description from blowing up batch token usage - the
    title/tags/dates already carry most of the classification signal, this
    is just extra context, not the field that needs to be exact."""
    if not text or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _format_tenders(batch):
    lines = []
    for record_id, record in batch:
        snippet = " | ".join(
            filter(None, [
                record.get("title"),
                record.get("office"),
                _truncate(record.get("description")),
                record.get("reference_no"),
                record.get("closing_date"),
            ])
        )
        lines.append(f"- record_id={record_id}: {snippet or '(no details extracted)'}")
    return "\n".join(lines)


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _apply_batch_result(batch_ids, valid_tag_names, parsed):
    by_id = {m.record_id: m for m in parsed.results}
    results = {}
    matched_count = 0
    for record_id in batch_ids:
        match = by_id.get(record_id)
        # the prompt requires exact tag names copied verbatim, but a model
        # can still hallucinate/paraphrase one - drop anything that isn't a
        # real configured tag rather than let a near-miss like "AI" silently
        # stand in for "AI RFP" and break the UI's exact-match tag filter
        matched = [t for t in (match.matched_tags if match else []) if t in valid_tag_names]
        if matched:
            matched_count += 1
        results[record_id] = {
            "classification": "done",
            "matched_tags": matched,
            "reason": match.reason if match else "",
        }
    return results, matched_count


def classify_batch(records, tags):
    """records: list of tender-record dicts. tags: list of {"name",
    "description"} dicts (already filtered to the enabled/selected ones by
    the caller). Returns {str(index into records): {"classification":
    "done"|"error", "matched_tags": [...], "reason": str}} - one entry per
    input record. Batches run concurrently (see MAX_CONCURRENT_BATCHES); a
    batch that fails (bad response, timeout, rate limit) is caught per-batch
    and marked "error" instead of raising, so one bad LLM call can't lose
    every other batch's results."""
    if not tags or not records:
        return {}

    chain = _build_chain()
    indexed = [(str(i), record) for i, record in enumerate(records)]
    valid_tag_names = {t["name"] for t in tags}
    model_id = os.environ.get("WATSONX_MODEL_ID", DEFAULT_MODEL_ID)

    batches = list(_chunks(indexed, BATCH_SIZE))
    inputs = [
        {"tags": _format_tags(tags), "tenders": _format_tenders(batch)}
        for batch in batches
    ]

    logger.info(
        "watsonx classify: %d record(s) in %d batch(es), up to %d concurrent, model=%s, tags=%s",
        len(records), len(batches), MAX_CONCURRENT_BATCHES, model_id, sorted(valid_tag_names),
    )
    started = time.monotonic()
    # return_exceptions=True: a failed batch comes back as an Exception
    # object in its slot instead of aborting every other (already in
    # flight, or not yet started) batch's results
    batch_outputs = chain.batch(
        inputs, config={"max_concurrency": MAX_CONCURRENT_BATCHES}, return_exceptions=True,
    )
    logger.info(
        "watsonx classify: all %d batch(es) done in %.2fs",
        len(batches), time.monotonic() - started,
    )

    results = {}
    for batch_num, (batch, output) in enumerate(zip(batches, batch_outputs), start=1):
        batch_ids = [record_id for record_id, _ in batch]
        if isinstance(output, Exception):
            logger.error("watsonx classify: batch %d/%d FAILED - %s", batch_num, len(batches), output)
            for record_id in batch_ids:
                results[record_id] = {"classification": "error", "matched_tags": [], "reason": str(output)[:200]}
            continue

        batch_results, batch_matched = _apply_batch_result(batch_ids, valid_tag_names, output)
        results.update(batch_results)
        logger.info(
            "watsonx classify: batch %d/%d - %d/%d matched a tag",
            batch_num, len(batches), batch_matched, len(batch_ids),
        )

    return results
