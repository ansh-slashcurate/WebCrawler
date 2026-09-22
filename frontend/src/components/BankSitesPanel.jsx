import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, CardHeader, Button, inputClass, labelClass } from "./ui";
import { IconLayers, IconTrash, IconArrowRight } from "./icons";

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
      <CardHeader title="Saved bank sites" icon={IconLayers} />
      <div className="p-5">
        <form onSubmit={handleSubmit} className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
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

        {sites === null && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}
        {sites?.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-400">No saved bank sites yet.</p>}
        <div className="space-y-2">
          {sites?.map((s) => (
            <div key={s.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-800 dark:text-slate-200">{s.name}</div>
                <div className="truncate text-xs text-slate-400 dark:text-slate-500">{s.url}</div>
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
