import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Card, CardHeader, Button, Badge, Spinner, EmptyState, inputClass, labelClass } from "../ui";
import { IconTable, IconSearch, IconArrowLeft, IconArrowRight, IconExternalLink, IconRefresh } from "../icons";

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
            {record.reference_no && <span>Ref: {record.reference_no}</span>}
            {record.published_date && <span>Published: {record.published_date}</span>}
            {record.closing_date && <span>Closing: {record.closing_date}</span>}
          </div>
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

export default function TenderResultsView({ refreshKey }) {
  const [entities, setEntities] = useState(null);
  const [entity, setEntity] = useState("");
  const [runs, setRuns] = useState(null);
  const [runId, setRunId] = useState("");

  const [tags, setTags] = useState(null);
  const [selectedTagIds, setSelectedTagIds] = useState([]);

  const [items, setItems] = useState(null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");

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

  useEffect(() => {
    setOffset(0);
  }, [entity, runId, query]);

  useEffect(() => {
    if (!entity || !runId) {
      setItems(null);
    }
  }, [entity, runId]);

  const loadItems = () => {
    if (!entity || !runId) return;
    api
      .runTenders(entity, runId, { offset, limit: PAGE_SIZE, q: query })
      .then(setItems)
      .catch((e) => setError(e.message));
  };

  useEffect(loadItems, [entity, runId, offset, query]);

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
            <div className="mb-4 rounded-lg border border-slate-200 p-3.5 dark:border-slate-800">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Classify against tags
                </span>
                <Button size="sm" onClick={handleClassify} disabled={classifying || !tags?.length}>
                  {classifying ? <Spinner className="h-3.5 w-3.5" /> : <IconRefresh className="h-3.5 w-3.5" />}
                  {classifying ? "Classifying…" : "Classify pending"}
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

            <div className="relative mb-4 max-w-sm">
              <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className={`${inputClass} pl-9`}
                placeholder="Search title / reference no…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {items && items.items.length === 0 && <EmptyState icon={IconTable} title="No tender records match" />}

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
