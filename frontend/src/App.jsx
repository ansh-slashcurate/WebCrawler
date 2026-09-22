import { useState } from "react";
import { Routes, Route, Navigate, NavLink, useLocation, useNavigate } from "react-router-dom";
import ConnectionsPanel from "./components/ConnectionsPanel";
import NewCrawlForm from "./components/NewCrawlForm";
import LiveJobs from "./components/LiveJobs";
import RunsBrowser from "./components/RunsBrowser";
import AuthManager from "./components/AuthManager";
import TendersPage from "./components/TendersPage";
import BankSitesPanel from "./components/BankSitesPanel";
import { IconGrid, IconLayers, IconLock, IconSettings, IconFileText } from "./components/icons";

const NAV_ITEMS = [
  { path: "/dashboard", label: "Dashboard", icon: IconGrid },
  { path: "/runs", label: "Runs", icon: IconLayers },
  { path: "/tenders", label: "Tenders", icon: IconFileText },
  { path: "/auth", label: "Authentication", icon: IconLock },
  { path: "/settings", label: "Settings", icon: IconSettings },
];

const PAGE_META = {
  "/dashboard": { title: "Dashboard", description: "Launch crawls and monitor live jobs." },
  "/runs": { title: "Runs", description: "Browse crawled pages by entity and run." },
  "/tenders": { title: "Tenders", description: "Crawl bank tender/procurement pages and classify RFPs against your tags." },
  "/auth": { title: "Authentication", description: "Manage per-domain login/API-key credentials." },
  "/settings": { title: "Settings", description: "Manage system connections and saved bank sites." },
};

function NavButton({ to, icon: Icon, children }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors ${
          isActive
            ? "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
            : "text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-900"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon className={`h-4 w-4 shrink-0 ${isActive ? "text-blue-600 dark:text-blue-400" : "text-slate-400 dark:text-slate-500"}`} />
          {children}
        </>
      )}
    </NavLink>
  );
}

export default function App() {
  const [jobTokens, setJobTokens] = useState([]);
  const location = useLocation();
  const navigate = useNavigate();

  const handleLaunched = (token) => {
    setJobTokens((prev) => [...prev, token]);
  };

  const openRunFromJob = (entity, runId) => {
    navigate(`/runs/${encodeURIComponent(entity)}/${encodeURIComponent(runId)}`);
  };

  const useSiteAsTenderSeed = (url, name) => {
    navigate("/tenders", { state: { prefillSeed: { url, name } } });
  };

  const topPath = "/" + (location.pathname.split("/")[1] || "dashboard");
  const meta = PAGE_META[topPath] || PAGE_META["/dashboard"];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      {/* soft brand-blue glow behind the top of the page - subtle SaaS touch, not a hard block of color */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-x-0 top-0 -z-10 h-72 bg-gradient-to-b from-blue-100/60 to-transparent dark:from-blue-950/30"
      />

      <div className="flex">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white/60 px-4 py-5 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-950/40 sm:flex">
          <div className="mb-6 flex items-center gap-2.5 px-1">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white shadow-sm shadow-blue-600/30">
              R
            </div>
            <div>
              <div className="text-sm font-semibold leading-tight text-slate-900 dark:text-slate-100">Slashcurates Crawler</div>
              <div className="text-[11px] leading-tight text-slate-400 dark:text-slate-500">Admin panel</div>
            </div>
          </div>

          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <NavButton key={item.path} to={item.path} icon={item.icon}>
                {item.label}
              </NavButton>
            ))}
          </nav>
        </aside>

        <main className="mx-auto min-w-0 w-full max-w-6xl flex-1 px-5 py-6 sm:px-8">
          <header className="mb-6">
            <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">{meta.title}</h1>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{meta.description}</p>
          </header>

          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />

            <Route
              path="/dashboard"
              element={
                <div className="space-y-6">
                  <NewCrawlForm onLaunched={handleLaunched} />
                  <LiveJobs tokens={jobTokens} onOpenRun={openRunFromJob} />
                </div>
              }
            />

            <Route path="/runs" element={<RunsBrowser />} />
            <Route path="/runs/:entity" element={<RunsBrowser />} />
            <Route path="/runs/:entity/:runId" element={<RunsBrowser />} />

            <Route path="/tenders" element={<TendersPage prefillSeed={location.state?.prefillSeed} />} />

            <Route path="/auth" element={<AuthManager />} />

            <Route
              path="/settings"
              element={
                <div className="space-y-6">
                  <ConnectionsPanel />
                  <BankSitesPanel onUseSite={useSiteAsTenderSeed} />
                </div>
              }
            />

            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
