import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, Badge, Button, Eyebrow } from "./ui";
import { IconArrowRight } from "./icons";

const STATUS_TONE = {
  running: "warning",
  finished: "success",
  failed: "danger",
};

function JobCard({ token, onOpenRun }) {
  const [job, setJob] = useState(null);
  const [pollError, setPollError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer;

    const poll = async () => {
      try {
        const status = await api.crawlStatus(token);
        if (cancelled) return;
        setJob(status);
        setPollError(null);
        if (status.status === "running") {
          timer = setTimeout(poll, 1500);
        }
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404) {
          // the API restarted (in-memory job tracking doesn't survive that) -
          // genuinely nothing more to poll for
          setPollError("Lost track of this job (API restarted?) - check the Runs tab once it finishes.");
          return;
        }
        // transient failure (network hiccup, API mid-reload, ...) - keep
        // retrying instead of freezing the UI on stale "running" forever
        setPollError("Having trouble reaching the API, retrying…");
        timer = setTimeout(poll, 3000);
      }
    };
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [token]);

  if (!job && !pollError) return null;

  if (!job && pollError) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/10 dark:text-amber-300">
        {pollError}
      </div>
    );
  }

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge tone={STATUS_TONE[job.status]}>{job.status}</Badge>
          <span className="font-mono text-xs text-slate-500 dark:text-slate-400">{job.entity}</span>
          {job.run_id && <span className="font-mono text-xs text-slate-400 dark:text-slate-500">· {job.run_id}</span>}
          {pollError && <span className="text-xs text-amber-600 dark:text-amber-400">({pollError})</span>}
        </div>
        {job.status !== "running" && job.run_id && (
          <Button variant="ghost" size="sm" onClick={() => onOpenRun(job.entity, job.run_id)}>
            Browse results
            <IconArrowRight className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </Card>
  );
}

export default function LiveJobs({ tokens, onOpenRun }) {
  if (tokens.length === 0) return null;
  return (
    <div>
      <Eyebrow>Launched this session</Eyebrow>
      <div className="mt-2 space-y-2">
        {tokens
          .slice()
          .reverse()
          .map((token) => (
            <JobCard key={token} token={token} onOpenRun={onOpenRun} />
          ))}
      </div>
    </div>
  );
}
