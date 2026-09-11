import { useEffect, useState } from "react";
import { api } from "../api";
import StatusDot from "./StatusDot";
import { Card, CardHeader, Button, Badge } from "./ui";
import { IconRefresh, IconLayers } from "./icons";

export default function ConnectionsPanel() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  const load = () => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        setError(null);
      })
      .catch((e) => setError(e.message));
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

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

            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400 sm:grid-cols-4">
              <div>
                <dt className="uppercase tracking-wide text-slate-400 dark:text-slate-500">Page cap</dt>
                <dd className="font-mono text-slate-700 dark:text-slate-300">{health.settings.closespider_pagecount}</dd>
              </div>
              <div>
                <dt className="uppercase tracking-wide text-slate-400 dark:text-slate-500">Download delay</dt>
                <dd className="font-mono text-slate-700 dark:text-slate-300">{health.settings.download_delay}s</dd>
              </div>
              <div className="col-span-2 sm:col-span-2">
                <dt className="uppercase tracking-wide text-slate-400 dark:text-slate-500">Output dir</dt>
                <dd className="truncate font-mono text-slate-700 dark:text-slate-300" title={health.settings.output_dir}>
                  {health.settings.output_dir}
                </dd>
              </div>
            </dl>
          </div>
        )}
      </div>
    </Card>
  );
}
