import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Card, CardHeader, Button, Spinner, inputClass, labelClass } from "../ui";
import { IconPlay } from "../icons";

const ALL_BANKS_VALUE = "__all__";

export default function TenderLaunchForm({ prefillSeed, onLaunched }) {
  const [seeds, setSeeds] = useState("");
  const [bank, setBank] = useState("");
  const [maxDepth, setMaxDepth] = useState(3);
  const [useSitemap, setUseSitemap] = useState(true);
  const [error, setError] = useState(null);

  const [bankSites, setBankSites] = useState([]);
  const [selectedBankId, setSelectedBankId] = useState("");

  // "idle" -> "starting" (POST in flight) -> "crawling" (polling until done) -> "idle"
  const [phase, setPhase] = useState("idle");
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
        } else if (status.status === "finished") {
          onLaunched?.(status);
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
          This only extracts tender records (heading, reference no., dates, links) - nothing gets classified or
          downloaded yet. Add tags and classify a finished run below.
        </p>

        {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <Button type="submit" disabled={busy} className="mt-4">
          {busy ? <Spinner /> : <IconPlay className="h-4 w-4" />}
          {phase === "starting" ? "Starting…" : phase === "crawling" ? "Crawling…" : "Start tender crawl"}
        </Button>
      </form>
    </Card>
  );
}
