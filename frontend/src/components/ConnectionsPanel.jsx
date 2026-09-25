import { useEffect, useState } from "react";
import { api } from "../api";
import StatusDot from "./StatusDot";
import { Card, CardHeader, Button, Badge } from "./ui";
import { IconRefresh, IconLayers } from "./icons";

export default function ConnectionsPanel() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  // Max pages per crawl (CLOSESPIDER_PAGECOUNT override, see /api/settings) -
  // loaded/saved separately from health, which is a pure read-only status
  // poll and shouldn't also own writing user config
  const [pageCap, setPageCap] = useState("");
  const [savedPageCap, setSavedPageCap] = useState(null);
  const [savingPageCap, setSavingPageCap] = useState(false);
  const [pageCapError, setPageCapError] = useState(null);

  const load = () => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        setError(null);
      })
      .catch((e) => setError(e.message));
  };

  const loadSettings = () => {
    api
      .settings()
      .then((s) => {
        setPageCap(String(s.max_pages_per_crawl));
        setSavedPageCap(s.max_pages_per_crawl);
      })
      .catch((e) => setPageCapError(e.message));
  };

  useEffect(() => {
    load();
    loadSettings();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  const handleSavePageCap = async (e) => {
    e.preventDefault();
    const parsed = Number(pageCap);
    if (!Number.isInteger(parsed) || parsed < 1) {
      setPageCapError("Enter a whole number of at least 1.");
      return;
    }
    setSavingPageCap(true);
    setPageCapError(null);
    try {
      const s = await api.updateSettings({ max_pages_per_crawl: parsed });
      setSavedPageCap(s.max_pages_per_crawl);
    } catch (err) {
      setPageCapError(err.message);
    } finally {
      setSavingPageCap(false);
    }
  };

  const pageCapDirty = savedPageCap !== null && String(savedPageCap) !== pageCap;

  return (
    <Card>
      <CardHeader
        title="Connections"
        icon={IconLayers}
        action={
          <Button variant="ghost" size="sm" onClick={load}>
            <IconRefresh className="h-3.5 w-3.5" />
            Refresh
          </Button>
        }
      />

      <div className="p-5">
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Can't reach the API — is <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">uvicorn webapi:app</code> running? ({error})
          </p>
        )}

        {health && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-x-6 gap-y-2.5">
              <StatusDot ok={health.redis.ok} label={`Redis (${health.redis.url})`} />
              <StatusDot ok={health.playwright.ok} label="Playwright / Chromium" />
              <StatusDot
                ok={health.auth.ok}
                label={
                  health.auth.configured
                    ? `Auth config (${health.auth.domains?.length ?? 0} domain${health.auth.domains?.length === 1 ? "" : "s"})`
                    : "Auth config (none — unauthenticated crawls only)"
                }
              />
              {health.youtube_api && (
                <span className="inline-flex items-center gap-1.5 text-sm text-slate-700 dark:text-slate-300">
                  <Badge tone={health.youtube_api.configured ? "success" : "default"}>
                    {health.youtube_api.configured ? "Configured" : "Not set"}
                  </Badge>
                  YouTube API ({health.youtube_api.env_var})
                </span>
              )}
            </div>

            {health.auth.configured && health.auth.ok && health.auth.domains.length > 0 && (
              <ul className="flex flex-wrap gap-2 text-xs">
                {health.auth.domains.map((d) => (
                  <li key={d.domain}>
                    <Badge>
                      {d.domain} <span className="text-slate-400 dark:text-slate-500">· {d.method}</span>
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            {health.auth.configured && !health.auth.ok && (
              <p className="text-xs text-red-600 dark:text-red-400">{health.auth.error}</p>
            )}

            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
              <div>
                <dt className="uppercase tracking-wide text-slate-400 dark:text-slate-500">Max pages per crawl</dt>
                <dd className="mt-1.5">
                  <form onSubmit={handleSavePageCap} className="flex items-center gap-1.5">
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={pageCap}
                      onChange={(e) => setPageCap(e.target.value)}
                      className="w-20 rounded-md border border-slate-300 bg-white px-2 py-1 font-mono text-xs text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/15 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
                    />
                    <button
                      type="submit"
                      disabled={savingPageCap || !pageCapDirty}
                      className="rounded-md px-2 py-1 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-40 dark:text-blue-400 dark:hover:bg-blue-900/20"
                    >
                      {savingPageCap ? "Saving…" : "Save"}
                    </button>
                  </form>
                  {pageCapError && <p className="mt-1 text-red-600 dark:text-red-400">{pageCapError}</p>}
                </dd>
              </div>
              <div>
                <dt className="uppercase tracking-wide text-slate-400 dark:text-slate-500">Download delay</dt>
                <dd className="mt-1.5 py-1 font-mono text-slate-700 dark:text-slate-300">{health.settings.download_delay}s</dd>
              </div>
            </dl>
          </div>
        )}
      </div>
    </Card>
  );
}
