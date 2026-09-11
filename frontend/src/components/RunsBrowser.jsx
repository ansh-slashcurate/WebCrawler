import { useEffect, useState } from "react";
import { api } from "../api";
import RunDetail from "./RunDetail";
import { Card, Button, Badge, EmptyState } from "./ui";
import { IconArrowLeft, IconRefresh, IconLayers, IconAlertTriangle } from "./icons";

export default function RunsBrowser({ openTarget, onOpenHandled }) {
  const [entities, setEntities] = useState(null);
  const [selectedEntity, setSelectedEntity] = useState(null);
  const [runs, setRuns] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [error, setError] = useState(null);

  const loadEntities = () => {
    api.entities().then(setEntities).catch((e) => setError(e.message));
  };

  useEffect(loadEntities, []);

  // deep-link from a just-finished live job
  useEffect(() => {
    if (openTarget) {
      setSelectedEntity(openTarget.entity);
      setSelectedRun(openTarget.runId);
      onOpenHandled();
    }
  }, [openTarget, onOpenHandled]);

  useEffect(() => {
    if (selectedEntity && !selectedRun) {
      api.runs(selectedEntity).then(setRuns).catch((e) => setError(e.message));
    }
  }, [selectedEntity, selectedRun]);

  if (error) return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;

  if (selectedEntity && selectedRun) {
    return (
      <RunDetail
        entity={selectedEntity}
        runId={selectedRun}
        onBack={() => setSelectedRun(null)}
      />
    );
  }

  if (selectedEntity) {
    return (
      <div>
        <Button variant="ghost" size="sm" onClick={() => setSelectedEntity(null)} className="mb-4">
          <IconArrowLeft className="h-3.5 w-3.5" />
          All entities
        </Button>
        <h2 className="mb-4 font-mono text-lg font-semibold text-slate-900 dark:text-slate-100">{selectedEntity}</h2>
        {runs === null && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}
        {runs?.length === 0 && <EmptyState icon={IconLayers} title="No runs yet" />}
        <div className="space-y-2">
          {runs?.map((r) => (
            <button key={r.run_id} onClick={() => setSelectedRun(r.run_id)} className="block w-full text-left">
              <Card className="p-4 transition-colors hover:border-blue-300 dark:hover:border-blue-700">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-sm text-slate-800 dark:text-slate-200">{r.run_id}</span>
                  {r.has_summary ? (
                    <span className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                      <Badge tone="success">{r.summary.stored.total} stored</Badge>
                      {r.summary.fetched} fetched · {r.summary.total_time}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                      <IconAlertTriangle className="h-3.5 w-3.5" />
                      no summary (in progress / interrupted)
                    </span>
                  )}
                </div>
              </Card>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Entities</h2>
        <Button variant="ghost" size="sm" onClick={loadEntities}>
          <IconRefresh className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>
      {entities === null && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}
      {entities?.length === 0 && (
        <EmptyState icon={IconLayers} title="No crawl output on disk yet" description="Start one from the Dashboard tab." />
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {entities?.map((e) => (
          <button key={e.slug} onClick={() => setSelectedEntity(e.slug)} className="text-left">
            <Card className="p-4 transition-colors hover:border-blue-300 dark:hover:border-blue-700">
              <div className="font-mono text-sm font-medium text-slate-800 dark:text-slate-200">
                {e.slug === "default" ? "(no entity)" : e.slug}
              </div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {e.run_count} run{e.run_count === 1 ? "" : "s"}
              </div>
            </Card>
          </button>
        ))}
      </div>
    </div>
  );
}
