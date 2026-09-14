"""FastAPI control panel backend for rag_crawler.

Run from the crawler/ directory (same place you'd run `scrapy crawl` from -
it imports the crawler package the same way the spider itself does):

    uvicorn webapi:app --reload --port 8000

Endpoints:
    GET    /api/health                                  - Redis/Playwright/auth/settings status
    GET    /api/auth-domains                            - configured login/API-key domains
    POST   /api/auth-domains                            - add/update one domain's auth (form_login or api_token)
    DELETE /api/auth-domains/{domain}                   - remove one domain's auth
    GET  /api/entities                                 - entity slugs with output on disk
    GET  /api/runs?entity=<slug|default>                - run list for one entity/scope
    GET  /api/runs/{entity}/{run_id}                    - one run's summary + counts
    GET  /api/runs/{entity}/{run_id}/pages?offset&limit&q - paginated clean.jsonl
    GET  /api/runs/{entity}/{run_id}/blocked            - blocked.jsonl entries
    POST /api/crawls                                    - launch `scrapy crawl rag_crawler`
    GET  /api/crawls                                    - jobs launched this API session
    GET  /api/crawls/{token}                            - one job's live status + log tail

"entity" in the URL is a slug (crawler.pipelines.slugify output), or the
literal string "default" for crawls started without -a entity=.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# a `scrapy crawl` launched below (subprocess.Popen) inherits this process's
# environment, so .env needs loading here too, not just in crawler/settings.py -
# explicit rather than relying on that module's own load_dotenv() running as a
# side effect of the `from crawler import settings` import below. Never logs or
# returns the values it loads (see /api/health's youtube_api block) - only
# whether a given key ended up set.
load_dotenv(Path(__file__).resolve().parent / ".env")

from crawler import settings as scrapy_settings
from crawler.auth import load_auth_config, AuthProfile, AuthError
from crawler.pipelines import slugify

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
RUNS_DIR = BASE_DIR / "runs"  # per-launch seed files + captured stdout, not crawl output
AUTH_JSON_PATH = BASE_DIR / "auth.json"
RUN_ID_RE = re.compile(r"^\d{8}_\d{6}_\d+$")

app = FastAPI(title="rag_crawler control panel API")
app.add_middleware(
    CORSMiddleware,
    # Vite auto-increments past 5173 (5174, 5175, ...) whenever a previous dev
    # server is still holding the port, so a fixed origin list keeps going
    # stale - allow any localhost/127.0.0.1 dev port instead of chasing it.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

# token -> {process, log_path, started_at, entity_name, run_id (filled in once known)}
JOBS = {}


# ---------- health ----------

@app.get("/api/health")
def health():
    result = {}

    try:
        client = redis.from_url(scrapy_settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
        result["redis"] = {"ok": True, "url": scrapy_settings.REDIS_URL}
    except Exception as e:
        result["redis"] = {"ok": False, "url": scrapy_settings.REDIS_URL, "error": str(e)}

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        result["playwright"] = {"ok": os.path.exists(exe), "executable": exe}
    except Exception as e:
        result["playwright"] = {"ok": False, "error": str(e)}

    auth_path = BASE_DIR / "auth.json"
    if not auth_path.exists():
        result["auth"] = {"ok": True, "configured": False, "domains": []}
    else:
        try:
            profiles = load_auth_config(str(auth_path))
            result["auth"] = {
                "ok": True,
                "configured": True,
                "domains": [{"domain": d, "method": p.method} for d, p in profiles.items()],
            }
        except AuthError as e:
            result["auth"] = {"ok": False, "configured": True, "error": str(e)}

    # reports only whether the key ended up set (from .env or the real
    # environment) - never the value itself, same as the "auth" block above
    # never exposes any of its domains' actual tokens/passwords
    youtube_env_name = scrapy_settings.YOUTUBE_API_KEY_ENV
    result["youtube_api"] = {"configured": bool(os.environ.get(youtube_env_name)), "env_var": youtube_env_name}

    result["settings"] = {
        "redis_url": scrapy_settings.REDIS_URL,
        "closespider_pagecount": scrapy_settings.CLOSESPIDER_PAGECOUNT,
        "download_delay": scrapy_settings.DOWNLOAD_DELAY,
        "output_dir": str(OUTPUT_DIR),
    }
    return result


# ---------- auth domains (login / API key setup) ----------
#
# Managed the same way the file itself was always meant to be used (see
# crawler/auth.py): auth.json on disk only ever stores the METHOD and
# structure (login_url, field names, header name, ...) plus an env var NAME -
# never a raw secret. The actual username/password/token typed into the UI is
# kept in this running API process's environment only (os.environ, in
# memory) - it's never written to disk, and a `scrapy crawl` subprocess
# launched afterward inherits it like any other env var. Restarting the API
# process loses it, same as closing a terminal you'd exported it in.

def _load_auth_json_raw():
    if not AUTH_JSON_PATH.exists():
        return {}
    try:
        return json.loads(AUTH_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_auth_json_raw(data):
    AUTH_JSON_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _env_var_name(domain, suffix):
    domain_part = re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_").upper()
    return f"AUTH_{domain_part}_{suffix}"


class AuthDomainRequest(BaseModel):
    domain: str
    method: str  # "form_login" | "api_token"
    # form_login
    login_url: str | None = None
    username_field: str = "username"
    password_field: str = "password"
    username: str | None = None
    password: str | None = None
    # api_token
    header_name: str = "Authorization"
    token_format: str = "Bearer {token}"
    token: str | None = None


@app.get("/api/auth-domains")
def list_auth_domains():
    raw = _load_auth_json_raw()
    return [{"domain": d, "method": cfg.get("method")} for d, cfg in raw.items() if not d.startswith("_")]


@app.post("/api/auth-domains")
def upsert_auth_domain(req: AuthDomainRequest):
    domain = req.domain.strip()
    if not domain:
        raise HTTPException(400, "domain is required")

    if req.method == "api_token":
        if not req.token:
            raise HTTPException(400, "an API key/token is required")
        token_env = _env_var_name(domain, "TOKEN")
        os.environ[token_env] = req.token
        config = {
            "method": "api_token",
            "header_name": req.header_name or "Authorization",
            "token_format": req.token_format or "{token}",
            "token_env": token_env,
        }
    elif req.method == "form_login":
        if not req.login_url or not req.username or not req.password:
            raise HTTPException(400, "login_url, username and password are all required")
        username_env = _env_var_name(domain, "USERNAME")
        password_env = _env_var_name(domain, "PASSWORD")
        os.environ[username_env] = req.username
        os.environ[password_env] = req.password
        config = {
            "method": "form_login",
            "login_url": req.login_url,
            "username_field": req.username_field or "username",
            "password_field": req.password_field or "password",
            "username_env": username_env,
            "password_env": password_env,
        }
    else:
        raise HTTPException(400, f"unsupported method {req.method!r} - use 'form_login' or 'api_token'")

    try:
        AuthProfile(domain, config).validate()
    except AuthError as e:
        raise HTTPException(400, str(e)) from e

    raw = _load_auth_json_raw()
    raw[domain] = config
    _save_auth_json_raw(raw)

    return {"domain": domain, "method": req.method}


@app.delete("/api/auth-domains/{domain}")
def delete_auth_domain(domain: str):
    raw = _load_auth_json_raw()
    if domain in raw:
        del raw[domain]
        _save_auth_json_raw(raw)
    return {"ok": True}


# ---------- browsing existing runs ----------

def _entity_dirs():
    if not OUTPUT_DIR.exists():
        return []
    return sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir())


@app.get("/api/entities")
def list_entities():
    entities = []
    has_default_runs = False
    for d in _entity_dirs():
        if RUN_ID_RE.match(d.name):
            has_default_runs = True
            continue
        run_count = sum(1 for c in d.iterdir() if c.is_dir() and RUN_ID_RE.match(c.name))
        if run_count:
            entities.append({"slug": d.name, "run_count": run_count})
    if has_default_runs:
        run_count = sum(1 for d in _entity_dirs() if RUN_ID_RE.match(d.name))
        entities.insert(0, {"slug": "default", "run_count": run_count})
    return entities


def _entity_base_dir(entity):
    return OUTPUT_DIR if entity == "default" else OUTPUT_DIR / entity


def _count_lines(path):
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _read_summary(run_dir):
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@app.get("/api/runs")
def list_runs(entity: str = "default"):
    base = _entity_base_dir(entity)
    if not base.exists():
        return []
    run_dirs = sorted(
        (d for d in base.iterdir() if d.is_dir() and RUN_ID_RE.match(d.name)),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    runs = []
    for d in run_dirs:
        summary = _read_summary(d)
        runs.append({
            "run_id": d.name,
            "has_summary": summary is not None,
            "summary": summary,
        })
    return runs


@app.get("/api/runs/{entity}/{run_id}")
def run_detail(entity: str, run_id: str):
    run_dir = _entity_base_dir(entity) / run_id
    if not run_dir.is_dir():
        raise HTTPException(404, "run not found")
    return {
        "entity": entity,
        "run_id": run_id,
        "summary": _read_summary(run_dir),
        "pages_lines": _count_lines(run_dir / "pages.jsonl"),
        "clean_lines": _count_lines(run_dir / "clean.jsonl"),
        "blocked_lines": _count_lines(run_dir / "blocked.jsonl"),
    }


@app.get("/api/runs/{entity}/{run_id}/pages")
def run_pages(entity: str, run_id: str, offset: int = 0, limit: int = 20, q: str = ""):
    run_dir = _entity_base_dir(entity) / run_id
    clean_path = run_dir / "clean.jsonl"
    if not clean_path.exists():
        raise HTTPException(404, "clean.jsonl not found for this run")

    q_lower = q.lower().strip()
    matched = []
    with open(clean_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if q_lower and q_lower not in record.get("url", "").lower() \
                    and q_lower not in record.get("cleaned_content", "").lower():
                continue
            matched.append(record)

    total = len(matched)
    page = matched[offset:offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "items": page}


@app.get("/api/runs/{entity}/{run_id}/blocked")
def run_blocked(entity: str, run_id: str):
    run_dir = _entity_base_dir(entity) / run_id
    blocked_path = run_dir / "blocked.jsonl"
    if not blocked_path.exists():
        return []
    items = []
    with open(blocked_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


# ---------- launching crawls ----------

class CrawlRequest(BaseModel):
    seeds: list[str]
    entity: str | None = None
    aliases: str = ""
    context: str = ""
    max_depth: int = 2
    use_sitemap: bool = True
    max_irrelevant_streak: int = 2


@app.post("/api/crawls")
def start_crawl(req: CrawlRequest):
    seeds = [s.strip() for s in req.seeds if s.strip()]
    if not seeds:
        raise HTTPException(400, "at least one seed URL is required")

    # The spider deliberately uses one persistent Redis frontier. Launching a
    # second local crawl against it causes both processes to consume the same
    # queue and interleave their shared daily log, which made diagnosis and
    # shutdown recovery unreliable. This control plane runs one local crawl at
    # a time; distributed workers should use deliberately isolated queues.
    active_tokens = [token for token, job in JOBS.items() if job["process"].poll() is None]
    if active_tokens:
        raise HTTPException(409, "a crawl is already running; wait for it to finish before starting another")

    token = uuid.uuid4().hex[:12]
    job_dir = RUNS_DIR / token
    job_dir.mkdir(parents=True, exist_ok=True)

    seed_path = job_dir / "seed.txt"
    seed_path.write_text("\n".join(seeds) + "\n", encoding="utf-8")

    cmd = [
        sys.executable, "-m", "scrapy", "crawl", "rag_crawler",
        "-a", f"seeds={seed_path}",
        "-a", f"max_depth={req.max_depth}",
        "-a", f"use_sitemap={req.use_sitemap}",
        "-a", f"max_irrelevant_streak={req.max_irrelevant_streak}",
    ]
    if req.entity:
        cmd += ["-a", f"entity={req.entity}"]
        if req.aliases:
            cmd += ["-a", f"aliases={req.aliases}"]
        if req.context:
            cmd += ["-a", f"context={req.context}"]

    # fallback capture only, for a crash before Scrapy's own FileHandler is up -
    # the real source of truth is settings.LOG_FILE (see _todays_scrapy_log
    # below): on Windows a child's stdout redirected to a file can stay fully
    # buffered and never flush before exit, but Scrapy's own logging.FileHandler
    # does flush reliably, so that's what status polling actually reads from
    log_path = job_dir / "launch.log"
    log_file = open(log_path, "w", encoding="utf-8")
    launched_at = time.time()

    # settings.py now writes one log file per calendar day (LOG_FILE_APPEND),
    # shared by every crawl started that day, rather than a fresh file per
    # crawl - so "this job's log" is no longer "the newest file", it's
    # "whatever gets appended to today's file from this point on". Recording
    # the file's current size before launch lets status polling seek past
    # every earlier crawl's lines and read only this job's own output.
    scrapy_log_path = _todays_scrapy_log_path()
    scrapy_log_offset = scrapy_log_path.stat().st_size if scrapy_log_path.exists() else 0

    process = subprocess.Popen(
        cmd, cwd=str(BASE_DIR), stdout=log_file, stderr=subprocess.STDOUT, text=True,
    )

    JOBS[token] = {
        "process": process,
        "launched_at": launched_at,
        "log_file": log_file,
        "log_path": log_path,
        "scrapy_log_path": scrapy_log_path,
        "scrapy_log_offset": scrapy_log_offset,
        "entity_name": req.entity,
        "run_id": None,
    }
    return {"token": token}


def _todays_scrapy_log_path():
    """Must match settings.py's LOG_FILE naming exactly - one shared file per
    calendar day under logs/."""
    return BASE_DIR / "logs" / f"crawl_{datetime.datetime.now():%Y%m%d}.log"


def _job_status(token, job):
    returncode = job["process"].poll()
    status = "running" if returncode is None else ("finished" if returncode == 0 else "failed")

    scrapy_log_path = job.get("scrapy_log_path")
    if scrapy_log_path is not None and scrapy_log_path.exists():
        with open(scrapy_log_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(job["scrapy_log_offset"])
            log_text = f.read()
    elif job["log_path"].exists():
        log_text = job["log_path"].read_text(encoding="utf-8", errors="ignore")
    else:
        log_text = ""

    if job["run_id"] is None:
        m = re.search(r"(?:Starting new|Resuming previous) crawl run (\S+)", log_text)
        if m:
            job["run_id"] = m.group(1)

    entity_slug = slugify(job["entity_name"]) if job["entity_name"] else "default"
    tail = "\n".join(log_text.splitlines()[-200:])

    return {
        "token": token,
        "status": status,
        "returncode": returncode,
        "entity": entity_slug,
        "run_id": job["run_id"],
        "log_tail": tail,
    }


@app.get("/api/crawls")
def list_crawls():
    return [_job_status(token, job) for token, job in JOBS.items()]


@app.get("/api/crawls/{token}")
def crawl_status(token: str):
    job = JOBS.get(token)
    if not job:
        raise HTTPException(404, "unknown job token")
    return _job_status(token, job)
