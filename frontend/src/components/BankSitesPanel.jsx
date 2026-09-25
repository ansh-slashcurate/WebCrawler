import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, CardHeader, Button, Badge, Spinner, EmptyState, inputClass, labelClass } from "./ui";
import { IconLayers, IconTrash, IconArrowRight, IconExternalLink } from "./icons";

// Deterministic per-bank color so the same bank always gets the same avatar
// tone across reloads, without storing anything - just a hash of its name.
const AVATAR_TONES = [
  "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300",
];

function avatarTone(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_TONES[hash % AVATAR_TONES.length];
}

export default function BankSitesPanel({ onUseSite }) {
  const [sites, setSites] = useState(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    api.bankSites().then(setSites).catch((e) => setError(e.message));
  };

  useEffect(load, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !url.trim()) {
      setError("Name and URL are both required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.addBankSite({ name: name.trim(), url: url.trim() });
      setName("");
      setUrl("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await api.deleteBankSite(id);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <Card>
      <CardHeader title="Saved bank sites" icon={IconLayers} action={sites?.length > 0 && <Badge>{sites.length}</Badge>} />
      <div className="p-5">
        <form
          onSubmit={handleSubmit}
          className="mb-5 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3.5 dark:border-slate-800 dark:bg-slate-800/30 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
        >
          <div>
            <label className={labelClass}>Bank name</label>
            <input className={inputClass} placeholder="HDFC Bank" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className={labelClass}>Site URL</label>
            <input className={inputClass} placeholder="https://www.hdfcbank.com/" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <Button type="submit" disabled={submitting} size="md">
            {submitting ? "Adding…" : "Add"}
          </Button>
        </form>

        {error && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

        {sites === null && (
          <div className="flex items-center gap-2 py-6 text-sm text-slate-500 dark:text-slate-400">
            <Spinner className="h-4 w-4" />
            Loading…
          </div>
        )}
        {sites?.length === 0 && (
          <EmptyState icon={IconLayers} title="No saved bank sites yet" description="Add one above to start crawling its tenders." />
        )}

        <div className="space-y-1">
          {sites?.map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-3 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
            >
              <span
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${avatarTone(s.name)}`}
              >
                {s.name.trim().charAt(0).toUpperCase() || "?"}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-slate-800 dark:text-slate-200">{s.name}</div>
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  title={s.url}
                  className="inline-flex max-w-full items-center gap-1 text-xs text-slate-400 hover:text-blue-600 hover:underline dark:text-slate-500 dark:hover:text-blue-400"
                >
                  <span className="truncate">{s.url}</span>
                  <IconExternalLink className="h-3 w-3 shrink-0" />
                </a>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {onUseSite && (
                  <Button variant="secondary" size="sm" onClick={() => onUseSite(s.url, s.name)}>
                    Use as seed
                    <IconArrowRight className="h-3.5 w-3.5" />
                  </Button>
                )}
                <Button variant="danger" size="sm" onClick={() => handleDelete(s.id)}>
                  <IconTrash className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
