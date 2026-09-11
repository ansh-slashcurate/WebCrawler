import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Card, CardHeader, Button, Spinner, inputClass, labelClass } from "./ui";
import { IconPlay } from "./icons";

export default function NewCrawlForm({ onLaunched }) {
  const [seeds, setSeeds] = useState("");
  const [entity, setEntity] = useState("");
  const [aliases, setAliases] = useState("");
  const [context, setContext] = useState("");
  const [maxDepth, setMaxDepth] = useState(2);
  const [useSitemap, setUseSitemap] = useState(true);
  const [error, setError] = useState(null);

  // "idle" -> "starting" (POST in flight) -> "crawling" (polling until done) -> "idle"
  const [phase, setPhase] = useState("idle");
  const pollTimer = useRef(null);

  useEffect(() => () => clearTimeout(pollTimer.current), []);

  const pollUntilDone = (token) => {
    const poll = async () => {
      try {
        const status = await api.crawlStatus(token);
        if (status.status === "running") {
          pollTimer.current = setTimeout(poll, 1500);
          return;
        }
        if (status.status === "failed") {
          setError("Crawl failed - check the log file under logs/ for details.");
        }
        setPhase("idle");
      } catch (err) {
        if (err.status === 404) {
          // API restarted mid-crawl - nothing left to poll for
          setPhase("idle");
          return;
        }
        // transient failure - keep waiting instead of getting stuck
        pollTimer.current = setTimeout(poll, 3000);
      }
    };
    poll();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const seedList = seeds.split("\n").map((s) => s.trim()).filter(Boolean);
    const entityName = entity.trim();

    if (seedList.length === 0) {
      setError("At least one seed URL is required.");
      return;
    }

    setPhase("starting");
    setError(null);
    try {
      const { token } = await api.startCrawl({
        seeds: seedList,
        entity: entityName || null,
        aliases: aliases.trim(),
        context: context.trim(),
        max_depth: Number(maxDepth),
        use_sitemap: useSitemap,
      });
      onLaunched(token);
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
      <CardHeader title="New crawl" icon={IconPlay} />
      <form onSubmit={handleSubmit} className="p-5">
        <fieldset disabled={busy} className="space-y-4">
          <div>
            <label className={labelClass}>Seed URLs (one per line)</label>
            <textarea
              className={`${inputClass} h-24 font-mono`}
              placeholder={"https://example.com/"}
              value={seeds}
              onChange={(e) => setSeeds(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={labelClass}>Entity (optional)</label>
              <input className={inputClass} placeholder="John Smith" value={entity} onChange={(e) => setEntity(e.target.value)} />
            </div>
            <div>
              <label className={labelClass}>Aliases</label>
              <input
                className={inputClass}
                placeholder="J. Smith, Johnny Smith"
                value={aliases}
                onChange={(e) => setAliases(e.target.value)}
                disabled={busy || !entity.trim()}
              />
            </div>
            <div>
              <label className={labelClass}>Context</label>
              <input
                className={inputClass}
                placeholder="CFO, Acme Corp"
                value={context}
                onChange={(e) => setContext(e.target.value)}
                disabled={busy || !entity.trim()}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-6">
            <div>
              <label className={labelClass}>Max depth</label>
              <input
                type="number"
                min={0}
                className={`${inputClass} w-20`}
                value={maxDepth}
                onChange={(e) => setMaxDepth(e.target.value)}
              />
            </div>
            <label className="flex items-center gap-2 pt-5 text-sm text-slate-600 dark:text-slate-300">
              <input
                type="checkbox"
                checked={useSitemap}
                onChange={(e) => setUseSitemap(e.target.checked)}
                disabled={busy}
                className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500/30 dark:border-slate-600 dark:bg-slate-800"
              />
              Use sitemap discovery
            </label>
          </div>
        </fieldset>

        {error && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <Button type="submit" disabled={busy} className="mt-5">
          {busy ? <Spinner /> : <IconPlay className="h-4 w-4" />}
          {phase === "starting" ? "Starting…" : phase === "crawling" ? "Crawling…" : "Start crawl"}
        </Button>
      </form>
    </Card>
  );
}
