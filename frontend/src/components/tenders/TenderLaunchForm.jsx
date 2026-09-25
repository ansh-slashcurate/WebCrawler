import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Card, CardHeader, Button, Spinner, inputClass, labelClass } from "../ui";
import { IconPlay, IconCheckCircle, IconXCircle } from "../icons";

const ALL_BANKS_VALUE = "__all__";

export default function TenderLaunchForm({ prefillSeed, onLaunched, onPipelineUpdate }) {
  const [seeds, setSeeds] = useState("");
  const [bank, setBank] = useState("");
  const [maxDepth, setMaxDepth] = useState(3);
  const [useSitemap, setUseSitemap] = useState(true);
  const [error, setError] = useState(null);

  const [bankSites, setBankSites] = useState([]);
  const [selectedBankId, setSelectedBankId] = useState("");

  // "idle" -> "starting" (POST in flight) -> "crawling" -> "pipeline" (crawl
  // done, sync/classify still running) -> "idle"
  const [phase, setPhase] = useState("idle");
  const [pipeline, setPipeline] = useState(null);
  const pollTimer = useRef(null);

  useEffect(() => () => clearTimeout(pollTimer.current), []);

  useEffect(() => {
    api.bankSites().then(setBankSites).catch(() => {});
  }, []);

  useEffect(() => {
    if (!prefillSeed) return;
    setSeeds(prefillSeed.url);
    setBank(prefillSeed.name || "");
    setSelectedBankId("");
  }, [prefillSeed]);

  const handleBankSelect = (e) => {
    const value = e.target.value;
    setSelectedBankId(value);
    if (value === "") return;
    if (value === ALL_BANKS_VALUE) {
      setSeeds(bankSites.map((s) => s.url).join("\n"));
      setBank("All banks");
      return;
    }
    const site = bankSites.find((s) => String(s.id) === value);
    if (site) {
      setSeeds(site.url);
      setBank(site.name);
    }
  };

  // once the crawl subprocess itself is "finished", tender_pipeline
  // (classify against every enabled tag) has just started server-side and
  // isn't done yet - keep polling until it reaches a terminal state too,
  // instead of calling the crawl alone "done"
  const pipelineSettled = (tp) =>
    !tp || ["done", "skipped_no_tags", "error"].includes(tp.classify_status);

  const pollUntilDone = (token) => {
    let launchedFired = false;
    const poll = async () => {
      try {
        const status = await api.crawlStatus(token);
        setPipeline(status.tender_pipeline);
        // lets TenderResultsView (a separate component with its own poll
        // loop, or none at all) know classification progressed, so it can
        // refetch once matches actually exist instead of showing the
        // zero-matches snapshot it fetched the moment the crawl itself
        // finished, forever
        onPipelineUpdate?.(status.tender_pipeline);

        if (status.status === "running") {
          pollTimer.current = setTimeout(poll, 1500);
          return;
        }
        if (status.status === "failed") {
          setError("Crawl failed - check the log file under logs/ for details.");
          setPhase("idle");
          return;
        }

        // status.status === "finished" from here on
        if (!launchedFired) {
          // jump the results view to this run right away - it has its own
          // "Reclassify"/pipeline-log affordances, it doesn't need to wait
          // for classification to finish before being useful to look at
          onLaunched?.(status);
          launchedFired = true;
        }
        if (!pipelineSettled(status.tender_pipeline)) {
          setPhase("pipeline");
          pollTimer.current = setTimeout(poll, 1500);
          return;
        }
        setPhase("idle");
      } catch (err) {
        if (err.status === 404) {
          setPhase("idle");
          return;
        }
        pollTimer.current = setTimeout(poll, 3000);
      }
    };
    poll();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const seedList = seeds.split("\n").map((s) => s.trim()).filter(Boolean);
    const bankName = bank.trim();

    if (seedList.length === 0) {
      setError("At least one seed URL is required.");
      return;
    }
    if (!bankName) {
      setError("Bank name is required - tenders are stored per bank.");
      return;
    }

    setPhase("starting");
    setPipeline(null);
    setError(null);
    try {
      const { token } = await api.startCrawl({
        seeds: seedList,
        entity: bankName,
        tender_mode: true,
        max_depth: Number(maxDepth),
        use_sitemap: useSitemap,
      });
      setPhase("crawling");
      pollUntilDone(token);
    } catch (err) {
      setError(err.message);
      setPhase("idle");
    }
  };

  const busy = phase !== "idle";

  return (
    <Card>
      <CardHeader title="New tender crawl" icon={IconPlay} />
      <form onSubmit={handleSubmit} className="p-5">
        <fieldset disabled={busy} className="space-y-4">
          <div>
            <label className={labelClass}>Bank (from saved sites)</label>
            <select className={inputClass} value={selectedBankId} onChange={handleBankSelect}>
              <option value="">Choose a saved bank…</option>
              {bankSites.length > 0 && <option value={ALL_BANKS_VALUE}>All banks ({bankSites.length})</option>}
              {bankSites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {bankSites.length === 0 && (
              <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
                No saved bank sites yet — add one on the Settings page, or paste a seed URL below.
              </p>
            )}
          </div>

          <div>
            <label className={labelClass}>Seed URL(s) (one per line)</label>
            <textarea
              className={`${inputClass} h-20 font-mono`}
              placeholder={"https://www.examplebank.com/"}
              value={seeds}
              onChange={(e) => setSeeds(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <label className={labelClass}>Bank name</label>
              <input className={inputClass} placeholder="HDFC Bank" value={bank} onChange={(e) => setBank(e.target.value)} />
            </div>
            <div>
              <label className={labelClass}>Max depth</label>
              <input
                type="number"
                min={0}
                className={inputClass}
                value={maxDepth}
                onChange={(e) => setMaxDepth(e.target.value)}
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input
              type="checkbox"
              checked={useSitemap}
              onChange={(e) => setUseSitemap(e.target.checked)}
              disabled={busy}
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500/30 dark:border-slate-600 dark:bg-slate-800"
            />
            Use sitemap discovery
          </label>
        </fieldset>

        <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
          Extracts tender records (title, office, dates, links - no documents downloaded), then automatically
          classifies them against your tender tags once the crawl finishes - no separate step needed.
        </p>

        {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <Button type="submit" disabled={busy} className="mt-4">
          {busy ? <Spinner /> : <IconPlay className="h-4 w-4" />}
          {phase === "starting" ? "Starting…" : phase === "crawling" ? "Crawling…" : phase === "pipeline" ? "Classifying…" : "Start tender crawl"}
        </Button>

        {(phase === "crawling" || phase === "pipeline" || pipeline) && (
          <PipelineStepper phase={phase} pipeline={pipeline} />
        )}
      </form>
    </Card>
  );
}

function Step({ state, label }) {
  // state: "pending" | "active" | "done" | "warning" | "error"
  const icon =
    state === "done" ? <IconCheckCircle className="h-3.5 w-3.5 text-emerald-500" /> :
    state === "error" ? <IconXCircle className="h-3.5 w-3.5 text-red-500" /> :
    state === "active" ? <Spinner className="h-3.5 w-3.5 text-blue-500" /> :
    <span className="h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-slate-600" />;
  const textTone =
    state === "pending" ? "text-slate-400 dark:text-slate-600" :
    state === "warning" ? "text-amber-600 dark:text-amber-400" :
    state === "error" ? "text-red-600 dark:text-red-400" :
    "text-slate-700 dark:text-slate-200";
  return (
    <span className={`inline-flex items-center gap-1.5 ${textTone}`}>
      {icon}
      {label}
    </span>
  );
}

// Crawling -> N tenders extracted -> Classifying (M/N) -> Done, K matched -
// each stage lights up as job["tender_pipeline"] (webapi.py's _job_status)
// advances, all from the one status poll TenderLaunchForm already runs.
function PipelineStepper({ phase, pipeline }) {
  const crawlState = phase === "crawling" || phase === "starting" ? "active" : "done";

  let extractState = "pending";
  let extractLabel = "Extracting";
  if (crawlState === "done") {
    if (!pipeline || pipeline.extract_status === "not_started" || pipeline.extract_status === "running") {
      extractState = "active";
    } else {
      extractState = "done";
      extractLabel = `${pipeline.tenders_extracted ?? 0} tender(s) extracted`;
    }
  }

  let classifyState = "pending";
  let classifyLabel = "Classifying";
  if (extractState === "done" && pipeline) {
    if (pipeline.classify_status === "running" || pipeline.classify_status === "not_started") {
      classifyState = "active";
      classifyLabel = pipeline.classify_total ? `Classifying (${pipeline.classify_done}/${pipeline.classify_total})` : "Classifying…";
    } else if (pipeline.classify_status === "done") {
      classifyState = "done";
      classifyLabel = `${pipeline.classify_matched} of ${pipeline.classify_total} matched a tag`;
    } else if (pipeline.classify_status === "skipped_no_tags") {
      classifyState = "warning";
      classifyLabel = "No enabled tags - add one to filter results";
    } else if (pipeline.classify_status === "error") {
      classifyState = "error";
      classifyLabel = `Classify failed: ${pipeline.classify_error || "unknown error"}`;
    }
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
      <Step state={crawlState} label="Crawling" />
      <span className="text-slate-300 dark:text-slate-700">→</span>
      <Step state={extractState} label={extractLabel} />
      <span className="text-slate-300 dark:text-slate-700">→</span>
      <Step state={classifyState} label={classifyLabel} />
    </div>
  );
}
