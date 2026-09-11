import { useState } from "react";
import ConnectionsPanel from "./components/ConnectionsPanel";
import NewCrawlForm from "./components/NewCrawlForm";
import LiveJobs from "./components/LiveJobs";
import RunsBrowser from "./components/RunsBrowser";
import AuthManager from "./components/AuthManager";
import { IconGrid, IconLayers, IconLock } from "./components/icons";

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: IconGrid },
  { id: "runs", label: "Runs", icon: IconLayers },
  { id: "auth", label: "Authentication", icon: IconLock },
];

const PAGE_META = {
  dashboard: { title: "Dashboard", description: "Launch crawls and check system connections." },
  runs: { title: "Runs", description: "Browse crawled pages by entity and run." },
  auth: { title: "Authentication", description: "Manage per-domain login/API-key credentials." },
};

function NavButton({ active, onClick, icon: Icon, children }) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors ${
        active
          ? "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
          : "text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-900"
      }`}
    >
      <Icon className={`h-4 w-4 shrink-0 ${active ? "text-blue-600 dark:text-blue-400" : "text-slate-400 dark:text-slate-500"}`} />
      {children}
    </button>
  );
}

export default function App() {
  const [view, setView] = useState("dashboard");
  const [jobTokens, setJobTokens] = useState([]);
  const [openTarget, setOpenTarget] = useState(null);

  const handleLaunched = (token) => {
    setJobTokens((prev) => [...prev, token]);
  };

  const openRunFromJob = (entity, runId) => {
    setOpenTarget({ entity, runId });
    setView("runs");
  };

  const meta = PAGE_META[view];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      {/* soft brand-blue glow behind the top of the page - subtle SaaS touch, not a hard block of color */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-x-0 top-0 -z-10 h-72 bg-gradient-to-b from-blue-100/60 to-transparent dark:from-blue-950/30"
      />

      <div className="mx-auto flex max-w-7xl">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white/60 px-4 py-5 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-950/40 sm:flex">
          <div className="mb-6 flex items-center gap-2.5 px-1">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white shadow-sm shadow-blue-600/30">
              R
            </div>
            <div>
              <div className="text-sm font-semibold leading-tight text-slate-900 dark:text-slate-100">RAG Crawler</div>
              <div className="text-[11px] leading-tight text-slate-400 dark:text-slate-500">control panel</div>
            </div>
          </div>

          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <NavButton key={item.id} active={view === item.id} onClick={() => setView(item.id)} icon={item.icon}>
                {item.label}
              </NavButton>
            ))}
          </nav>

          <div className="mt-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] leading-snug text-slate-400 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-500">
            Scrapy + Playwright backend, running locally.
          </div>
        </aside>

        <main className="min-w-0 flex-1 px-5 py-6 sm:px-8">
          <header className="mb-6">
            <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">{meta.title}</h1>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{meta.description}</p>
          </header>

          {view === "dashboard" && (
            <div className="space-y-6">
              <ConnectionsPanel />
              <NewCrawlForm onLaunched={handleLaunched} />
              <LiveJobs tokens={jobTokens} onOpenRun={openRunFromJob} />
            </div>
          )}

          {view === "runs" && (
            <RunsBrowser openTarget={openTarget} onOpenHandled={() => setOpenTarget(null)} />
          )}

          {view === "auth" && <AuthManager />}
        </main>
      </div>
    </div>
  );
}
