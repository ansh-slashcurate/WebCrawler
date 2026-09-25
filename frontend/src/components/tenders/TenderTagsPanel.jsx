import { useEffect, useState } from "react";
import { api } from "../../api";
import { Card, CardHeader, Button, Badge, inputClass, labelClass } from "../ui";
import { IconFileText, IconTrash } from "../icons";

export default function TenderTagsPanel() {
  const [tags, setTags] = useState(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    api.tenderTags().then(setTags).catch((e) => setError(e.message));
  };

  useEffect(load, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("A tag name is required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.addTenderTag({ name: name.trim(), description: description.trim(), enabled: true });
      setName("");
      setDescription("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await api.deleteTenderTag(id);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <Card>
      <CardHeader title="Tags (what you're looking for)" icon={IconFileText} />
      <div className="p-5">

        <form onSubmit={handleSubmit} className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
          <div>
            <label className={labelClass}>Tag name</label>
            <input className={inputClass} placeholder="AI RFP" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className={labelClass}>Description (hint for the model)</label>
            <input
              className={inputClass}
              placeholder="AI, machine learning, chatbots, GenAI platforms"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={submitting} size="md">
            {submitting ? "Adding…" : "Add"}
          </Button>
        </form>

        {error && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

        {tags === null && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}
        {tags?.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-400">No tags yet — add one above.</p>}
        <div className="flex flex-wrap gap-2">
          {tags?.map((t) => (
            <span key={t.id} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 py-1 pl-3 pr-1.5 text-xs dark:border-slate-800">
              <Badge tone="blue">{t.name}</Badge>
              {t.description && <span className="max-w-[16rem] truncate text-slate-500 dark:text-slate-400">{t.description}</span>}
              <button
                onClick={() => handleDelete(t.id)}
                className="rounded-full p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
              >
                <IconTrash className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      </div>
    </Card>
  );
}
