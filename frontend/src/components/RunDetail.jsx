import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, Button, Badge, EmptyState, inputClass } from "./ui";
import {
  IconArrowLeft,
  IconArrowRight,
  IconSearch,
  IconTable,
  IconVideo,
  IconMessageCircle,
  IconAlertTriangle,
} from "./icons";

const PAGE_SIZE = 10;

function CommentsSection({ comments }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-2.5">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
      >
        <IconMessageCircle className="h-3.5 w-3.5" />
        {expanded ? "Hide" : "Show"} {comments.length} comment{comments.length === 1 ? "" : "s"}
      </button>
      {expanded && (
        <ul className="mt-2 space-y-1.5 border-l-2 border-slate-200 pl-3 dark:border-slate-700">
          {comments.map((c, i) => (
            <li key={i} className="text-xs text-slate-600 dark:text-slate-400">
              <span className="font-semibold text-slate-700 dark:text-slate-300">{c.author || "Unknown"}</span>: {c.text}
              {typeof c.likes === "number" && c.likes > 0 && (
                <span className="ml-1 text-slate-400 dark:text-slate-500">({c.likes} likes)</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PageEntry({ p }) {
  const [expanded, setExpanded] = useState(false);
  const content = p.cleaned_content || "";
  // line-clamp-6 visually hides text past ~6 lines - only offer "Read more"
  // once there's actually enough content for that to hide something
  const isLong = content.length > 400;

  return (
    <Card className="p-4">
      <details>
        <summary className="cursor-pointer break-all text-sm font-medium text-slate-800 marker:content-none dark:text-slate-200">
          {p.url}
          {p.entity && (
            <Badge tone="blue" className="ml-2 align-middle">
              score {p.relevance_score}
            </Badge>
          )}
        </summary>

        {p.video && (
          <div className="mt-2.5 flex items-start gap-1.5 text-xs text-slate-500 dark:text-slate-400">
            <IconVideo className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-slate-500" />
            <span>
              <span className="font-semibold text-slate-700 dark:text-slate-300">{p.video.title}</span>
              {p.video.author && <span> — {p.video.author}</span>}
            </span>
          </div>
        )}

        <p className={`mt-2.5 text-sm leading-relaxed text-slate-600 dark:text-slate-400 ${expanded ? "" : "line-clamp-6"}`}>
          {content}
        </p>
        {isLong && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
          >
            {expanded ? "Show less" : "Read more"}
          </button>
        )}

        {p.tables?.length > 0 && (
          <p className="mt-2.5 flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
            <IconTable className="h-3.5 w-3.5" />
            {p.tables.length} table{p.tables.length === 1 ? "" : "s"} extracted
          </p>
        )}
        {p.comments?.length > 0 && <CommentsSection comments={p.comments} />}
      </details>
    </Card>
  );
}

function StatTile({ label, value, tone = "default" }) {
  const toneClass =
    tone === "danger"
      ? "text-red-600 dark:text-red-400"
      : tone === "success"
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-slate-900 dark:text-slate-100";
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 dark:border-slate-800 dark:bg-slate-900/60">
      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`font-mono text-lg font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

export default function RunDetail({ entity, runId, onBack }) {
  const [detail, setDetail] = useState(null);
  const [pages, setPages] = useState(null);
  const [blocked, setBlocked] = useState(null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("pages");
  const [error, setError] = useState(null);

  useEffect(() => {
    setOffset(0);
  }, [entity, runId, query]);

  useEffect(() => {
    api.runDetail(entity, runId).then(setDetail).catch((e) => setError(e.message));
  }, [entity, runId]);

  useEffect(() => {
    api
      .runPages(entity, runId, { offset, limit: PAGE_SIZE, q: query })
      .then(setPages)
      .catch((e) => setError(e.message));
  }, [entity, runId, offset, query]);

  useEffect(() => {
    if (tab === "blocked" && blocked === null) {
      api.runBlocked(entity, runId).then(setBlocked).catch((e) => setError(e.message));
    }
  }, [tab, entity, runId, blocked]);

  if (error) return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;
  if (!detail) return <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>;

  const s = detail.summary;

  return (
    <div>
      <Button variant="ghost" size="sm" onClick={onBack} className="mb-4">
        <IconArrowLeft className="h-3.5 w-3.5" />
        Back to runs
      </Button>

      <div className="mb-5 flex flex-wrap items-baseline gap-2">
        <h2 className="font-mono text-lg font-semibold text-slate-900 dark:text-slate-100">{runId}</h2>
        <span className="text-sm text-slate-500 dark:text-slate-400">entity: {entity}</span>
      </div>

      {!s && (
        <p className="mb-5 flex items-center gap-2 text-sm text-amber-600 dark:text-amber-400">
          <IconAlertTriangle className="h-4 w-4 shrink-0" />
          No summary.json yet — this run may still be in progress or was interrupted.
        </p>
      )}

      {s && (
        <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          <StatTile label="Duration" value={s.total_time} />
          <StatTile label="Fetched" value={s.fetched} />
          <StatTile label="Stored" value={s.stored.total} tone="success" />
          <StatTile label="Duplicate" value={s.dropped.duplicate} tone={s.dropped.duplicate ? "danger" : "default"} />
          <StatTile label="Empty" value={s.dropped.empty} tone={s.dropped.empty ? "danger" : "default"} />
          <StatTile label="Irrelevant" value={s.dropped.irrelevant} tone={s.dropped.irrelevant ? "danger" : "default"} />
          <StatTile label="Blocked" value={s.blocked} tone={s.blocked ? "danger" : "default"} />
        </div>
      )}

      <div className="mb-4 flex gap-6 border-b border-slate-200 text-sm dark:border-slate-800">
        <button
          onClick={() => setTab("pages")}
          className={`border-b-2 pb-2.5 font-medium transition-colors ${
            tab === "pages" ? "border-blue-600 text-blue-600 dark:text-blue-400" : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
          }`}
        >
          Pages ({detail.clean_lines})
        </button>
        <button
          onClick={() => setTab("blocked")}
          className={`border-b-2 pb-2.5 font-medium transition-colors ${
            tab === "blocked" ? "border-blue-600 text-blue-600 dark:text-blue-400" : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
          }`}
        >
          Blocked ({detail.blocked_lines})
        </button>
      </div>

      {tab === "pages" && (
        <div>
          <div className="relative mb-4 max-w-sm">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className={`${inputClass} pl-9`}
              placeholder="Search url / content…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {pages && pages.items.length === 0 && <EmptyState icon={IconSearch} title="No pages match" />}

          <div className="space-y-2">
            {pages?.items.map((p) => (
              <PageEntry key={p.url} p={p} />
            ))}
          </div>

          {pages && pages.total > PAGE_SIZE && (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <Button
                variant="secondary"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                <IconArrowLeft className="h-3.5 w-3.5" />
                Prev
              </Button>
              <span className="text-slate-500 dark:text-slate-400">
                {offset + 1}–{Math.min(offset + PAGE_SIZE, pages.total)} of {pages.total}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={offset + PAGE_SIZE >= pages.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
                <IconArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
      )}

      {tab === "blocked" && (
        <div className="space-y-2">
          {blocked?.length === 0 && <EmptyState icon={IconAlertTriangle} title="Nothing blocked in this run" />}
          {blocked?.map((b, i) => (
            <div key={i} className="rounded-lg border border-red-200 bg-red-50 p-3.5 text-sm dark:border-red-900/50 dark:bg-red-900/10">
              <p className="break-all font-medium text-red-800 dark:text-red-300">{b.url}</p>
              <p className="mt-1 text-xs text-red-600 dark:text-red-400">{b.reason}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
