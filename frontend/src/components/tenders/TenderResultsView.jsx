import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Card, CardHeader, Button, Badge, Spinner, EmptyState, inputClass, labelClass } from "../ui";
import {
  IconTable, IconSearch, IconArrowLeft, IconArrowRight, IconExternalLink, IconRefresh,
  IconFileText, IconChevronDown, IconAlertTriangle,
} from "../icons";

const PAGE_SIZE = 10;

const CLASSIFICATION_TONE = {
  pending: "default",
  done: "success",
  error: "danger",
};

function TenderRecordCard({ record }) {
  const status = record.classification || "pending";
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium text-slate-800 dark:text-slate-200">{record.title || "(untitled tender)"}</div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            {record.office && <span>Office: {record.office}</span>}
            {record.reference_no && <span>Ref: {record.reference_no}</span>}
            {record.published_date && <span>Published: {record.published_date}</span>}
            {record.closing_date && <span>Closing: {record.closing_date}</span>}
          </div>
          {record.description && record.description !== record.title && (
            <p className="mt-1.5 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{record.description}</p>
          )}
        </div>
        <Badge tone={CLASSIFICATION_TONE[status] || "default"}>{status}</Badge>
      </div>

      {record.matched_tags?.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {record.matched_tags.map((tag) => (
            <Badge key={tag} tone="blue">
              {tag}
            </Badge>
          ))}
        </div>
      )}
      {record.reason && <p className="mt-2 text-xs italic text-slate-400 dark:text-slate-500">{record.reason}</p>}

      <div className="mt-3 flex flex-wrap gap-3 text-xs">
        {(record.detail_url || record.source_url) && (
          <a
            href={record.detail_url || record.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
          >
            <IconExternalLink className="h-3.5 w-3.5" />
            View source
          </a>
        )}
        {record.document_links?.map((link, i) => (
          <a
            key={i}
            href={link}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
          >
            <IconExternalLink className="h-3.5 w-3.5" />
            Document {record.document_links.length > 1 ? i + 1 : ""}
          </a>
        ))}
      </div>
    </Card>
  );
}

const LOG_LEVEL_TONE = { error: "danger", warning: "warning", info: "default" };

// Debug aid, not a primary results view - collapsed by default. Backs onto
// logs/tender_pipeline_<date>.log (crawler/tender_sync.py), not a DB table,
// so this only ever reads it back through the API, never writes.
function PipelineLogPanel({ entity, runId }) {
  const [open, setOpen] = useState(false);
  const [logs, setLogs] = useState(null);
  const [error, setError] = useState(null);

  const load = () => {
    api.pipelineLogs(entity, runId).then(setLogs).catch((e) => setError(e.message));
  };

  useEffect(() => {
    if (open) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, entity, runId]);

  return (
    <div className="mb-4 rounded-lg border border-slate-200 dark:border-slate-800">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left"
      >
        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          <IconFileText className="h-3.5 w-3.5" />
          Pipeline log
        </span>
        <IconChevronDown className={`h-3.5 w-3.5 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-slate-100 p-3.5 dark:border-slate-800">
          {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
          {!error && logs?.length === 0 && (
            <p className="text-xs text-slate-400 dark:text-slate-500">
              No pipeline events logged for this run yet.
            </p>
          )}
          <div className="space-y-1.5">
            {logs?.map((log, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 whitespace-nowrap font-mono text-slate-400 dark:text-slate-600">
                  {log.ts?.replace(" UTC", "")}
                </span>
                <Badge tone={LOG_LEVEL_TONE[log.level] || "default"} className="shrink-0">
                  {log.event}
                </Badge>
                <span className="text-slate-600 dark:text-slate-300">{log.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TenderResultsView({ refreshKey, focusEntity, focusRunId, pipelineStatus }) {
  const [entities, setEntities] = useState(null);
  const [entity, setEntity] = useState("");
  const [runs, setRuns] = useState(null);
  const [runId, setRunId] = useState("");

  const [tags, setTags] = useState(null);
  const [selectedTagIds, setSelectedTagIds] = useState([]);

  const [items, setItems] = useState(null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  // false (default): only tenders that matched at least one tag - a
  // record's own matched_tags field in tenders.jsonl, via the `filtered`
  // query param on GET .../tenders. true: every extracted record, matched
  // or not.
  const [showAll, setShowAll] = useState(false);

  const [classifyJob, setClassifyJob] = useState(null);
  const [error, setError] = useState(null);
  const pollTimer = useRef(null);

  useEffect(() => () => clearTimeout(pollTimer.current), []);

  useEffect(() => {
    api.entities().then(setEntities).catch((e) => setError(e.message));
    api.tenderTags().then(setTags).catch((e) => setError(e.message));
  }, [refreshKey]);

  useEffect(() => {
    if (!entity) return;
    api.runs(entity).then(setRuns).catch((e) => setError(e.message));
  }, [entity, refreshKey]);

  // a just-finished crawl (TenderLaunchForm's onLaunched, via TendersPage)
  // jumps straight to its own results instead of leaving the previous
  // bank/run selected until the user re-picks it by hand
  useEffect(() => {
    if (focusEntity) setEntity(focusEntity);
    if (focusRunId) setRunId(focusRunId);
  }, [focusEntity, focusRunId]);

  useEffect(() => {
    setOffset(0);
  }, [entity, runId, query, showAll]);

  useEffect(() => {
    if (!entity || !runId) {
      setItems(null);
    }
  }, [entity, runId]);

  const loadItems = () => {
    if (!entity || !runId) return;
    api
      .runTenders(entity, runId, { offset, limit: PAGE_SIZE, q: query, filtered: !showAll })
      .then(setItems)
      .catch((e) => setError(e.message));
  };

  useEffect(loadItems, [entity, runId, offset, query, showAll]);

  // TenderLaunchForm's automatic classify pipeline runs in a separate poll
  // loop from this component's own - without this, a run this view jumped
  // to the moment its crawl finished (see the focusEntity/focusRunId effect
  // above) would show its zero-matches snapshot from before classification
  // even started, and never update once matches actually exist
  useEffect(() => {
    if (!pipelineStatus || pipelineStatus.classify_status === "not_started") return;
    if (entity !== focusEntity || runId !== focusRunId) return;
    loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineStatus?.classify_status, pipelineStatus?.classify_done]);

  const toggleTag = (id) => {
    setSelectedTagIds((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  };

  const pollClassify = (token) => {
    const poll = async () => {
      try {
        const status = await api.classifyStatus(token);
        setClassifyJob(status);
        if (status.status === "running") {
          pollTimer.current = setTimeout(poll, 1500);
          return;
        }
        loadItems();
        api.runs(entity).then(setRuns).catch(() => {});
      } catch (err) {
        setError(err.message);
      }
    };
    poll();
  };

  const handleClassify = async () => {
    setError(null);
    try {
      const { token } = await api.classifyTenders(entity, runId, selectedTagIds);
      setClassifyJob({ status: "running", total: 0, done: 0, matched: 0 });
      pollClassify(token);
    } catch (err) {
      setError(err.message);
    }
  };

  const classifying = classifyJob?.status === "running";

  return (
    <Card>
      <CardHeader title="Tender results" icon={IconTable} />
      <div className="p-5">
        {error && <p className="mb-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Bank</label>
            <select
              className={inputClass}
              value={entity}
              onChange={(e) => {
                setEntity(e.target.value);
                setRunId("");
              }}
            >
              <option value="">Select a bank…</option>
              {entities?.map((e) => (
                <option key={e.slug} value={e.slug}>
                  {e.slug}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelClass}>Run</label>
            <select className={inputClass} value={runId} onChange={(e) => setRunId(e.target.value)} disabled={!entity}>
              <option value="">Select a run…</option>
              {runs?.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} {r.has_summary ? `(${r.summary.tenders ?? 0} tenders)` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        {entity && runId && (
          <>
            <PipelineLogPanel entity={entity} runId={runId} />

            <div className="mb-4 rounded-lg border border-slate-200 p-3.5 dark:border-slate-800">
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Reclassify
                  </span>
                  <p className="text-xs text-slate-400 dark:text-slate-500">
                    New tenders are classified automatically once a crawl finishes - use this only to re-run it (e.g.
                    after adding a tag, or for tenders a resumed crawl added since).
                  </p>
                </div>
                <Button size="sm" variant="secondary" onClick={handleClassify} disabled={classifying || !tags?.length}>
                  {classifying ? <Spinner className="h-3.5 w-3.5" /> : <IconRefresh className="h-3.5 w-3.5" />}
                  {classifying ? "Classifying…" : "Reclassify"}
                </Button>
              </div>
              {!tags?.length && (
                <p className="text-xs text-slate-400 dark:text-slate-500">Add at least one tag above first.</p>
              )}
              <div className="flex flex-wrap gap-1.5">
                {tags?.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => toggleTag(t.id)}
                    className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                      selectedTagIds.includes(t.id)
                        ? "border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-500 dark:bg-blue-900/30 dark:text-blue-300"
                        : "border-slate-200 text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
                    }`}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
                {selectedTagIds.length === 0 ? "None selected - classifies against every enabled tag." : `${selectedTagIds.length} tag(s) selected.`}
              </p>
              {classifyJob && (
                <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  {classifyJob.status === "running" && "Classifying pending tenders…"}
                  {classifyJob.status === "finished" && `Done - ${classifyJob.done} classified, ${classifyJob.matched} matched a tag.`}
                  {classifyJob.status === "failed" && <span className="text-red-600 dark:text-red-400">Failed: {classifyJob.error}</span>}
                </p>
              )}
            </div>

            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="relative max-w-sm flex-1">
                <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  className={`${inputClass} pl-9`}
                  placeholder="Search title / office / reference no…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <div className="flex overflow-hidden rounded-lg border border-slate-200 text-xs font-medium dark:border-slate-700">
                <button
                  type="button"
                  onClick={() => setShowAll(false)}
                  className={`px-3 py-1.5 ${
                    !showAll
                      ? "bg-blue-600 text-white"
                      : "bg-white text-slate-600 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                  }`}
                >
                  Matched only
                </button>
                <button
                  type="button"
                  onClick={() => setShowAll(true)}
                  className={`px-3 py-1.5 ${
                    showAll
                      ? "bg-blue-600 text-white"
                      : "bg-white text-slate-600 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                  }`}
                >
                  All extracted
                </button>
              </div>
            </div>

            {items && items.items.length === 0 && (
              <EmptyState
                icon={!showAll ? IconAlertTriangle : IconTable}
                title={!showAll ? "No tenders have matched a tag yet" : "No tender records match"}
                description={
                  !showAll
                    ? "Classification may still be running, or nothing extracted so far matched your tags - switch to \"All extracted\" to see everything the crawl found."
                    : undefined
                }
              />
            )}

            <div className="space-y-2">
              {items?.items.map((r, i) => (
                <TenderRecordCard key={`${r.source_url}-${i}`} record={r} />
              ))}
            </div>

            {items && items.total > PAGE_SIZE && (
              <div className="mt-4 flex items-center gap-3 text-sm">
                <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                  <IconArrowLeft className="h-3.5 w-3.5" />
                  Prev
                </Button>
                <span className="text-slate-500 dark:text-slate-400">
                  {offset + 1}–{Math.min(offset + PAGE_SIZE, items.total)} of {items.total}
                </span>
                <Button variant="secondary" size="sm" disabled={offset + PAGE_SIZE >= items.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                  Next
                  <IconArrowRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}
          </>
        )}

        {entity && !runId && <p className="text-sm text-slate-500 dark:text-slate-400">Pick a run to see its tender records.</p>}
        {!entity && <p className="text-sm text-slate-500 dark:text-slate-400">Pick a bank to browse its tender crawl runs.</p>}
      </div>
    </Card>
  );
}
