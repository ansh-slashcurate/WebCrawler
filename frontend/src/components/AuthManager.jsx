import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, CardHeader, Button, Badge, Eyebrow, inputClass, labelClass } from "./ui";
import { IconLock, IconTrash } from "./icons";

const EMPTY_FORM = {
  domain: "",
  method: "api_token",
  // api_token
  token: "",
  header_name: "Authorization",
  token_format: "Bearer {token}",
  // form_login
  login_url: "",
  username: "",
  password: "",
  username_field: "username",
  password_field: "password",
};

export default function AuthManager() {
  const [domains, setDomains] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = () => {
    api.authDomains().then(setDomains).catch((e) => setError(e.message));
  };

  useEffect(load, []);

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.domain.trim()) {
      setError("Domain is required (e.g. app.example.com).");
      return;
    }
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const payload =
        form.method === "api_token"
          ? {
              domain: form.domain.trim(),
              method: "api_token",
              token: form.token,
              header_name: form.header_name.trim() || "Authorization",
              token_format: form.token_format.trim() || "{token}",
            }
          : {
              domain: form.domain.trim(),
              method: "form_login",
              login_url: form.login_url.trim(),
              username: form.username,
              password: form.password,
              username_field: form.username_field.trim() || "username",
              password_field: form.password_field.trim() || "password",
            };
      await api.upsertAuthDomain(payload);
      setNotice(`Saved auth for ${form.domain.trim()}.`);
      setForm(EMPTY_FORM);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (domain) => {
    try {
      await api.deleteAuthDomain(domain);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-slate-500 dark:text-slate-400">
        For sites you already have legitimate access to — your own login, or an API key. Credentials are kept
        only in this API process's memory, never written to disk; <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">auth.json</code> stores
        just the method and an environment-variable name. Restarting the API means re-entering them here.
      </p>

      <Card>
        <CardHeader title="Add credentials" icon={IconLock} />
        <form onSubmit={handleSubmit} className="p-5">
          <div className="mb-4 flex gap-2">
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, method: "api_token" }))}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                form.method === "api_token"
                  ? "bg-blue-600 text-white shadow-sm"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              }`}
            >
              API key
            </button>
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, method: "form_login" }))}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                form.method === "form_login"
                  ? "bg-blue-600 text-white shadow-sm"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              }`}
            >
              Login (username &amp; password)
            </button>
          </div>

          <div className="space-y-3">
            <div>
              <label className={labelClass}>Domain</label>
              <input className={inputClass} placeholder="app.example.com" value={form.domain} onChange={set("domain")} />
            </div>

            {form.method === "api_token" ? (
              <>
                <div>
                  <label className={labelClass}>API key / token</label>
                  <input type="password" className={inputClass} value={form.token} onChange={set("token")} placeholder="sk_live_…" />
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className={labelClass}>Header name</label>
                    <input className={inputClass} value={form.header_name} onChange={set("header_name")} />
                  </div>
                  <div>
                    <label className={labelClass}>Header format</label>
                    <input className={inputClass} value={form.token_format} onChange={set("token_format")} />
                  </div>
                </div>
              </>
            ) : (
              <>
                <div>
                  <label className={labelClass}>Login page URL</label>
                  <input className={inputClass} placeholder="https://app.example.com/login" value={form.login_url} onChange={set("login_url")} />
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className={labelClass}>Username / email</label>
                    <input className={inputClass} value={form.username} onChange={set("username")} />
                  </div>
                  <div>
                    <label className={labelClass}>Password</label>
                    <input type="password" className={inputClass} value={form.password} onChange={set("password")} />
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className={labelClass}>Username field name</label>
                    <input className={inputClass} value={form.username_field} onChange={set("username_field")} />
                  </div>
                  <div>
                    <label className={labelClass}>Password field name</label>
                    <input className={inputClass} value={form.password_field} onChange={set("password_field")} />
                  </div>
                </div>
                <p className="text-xs text-slate-400 dark:text-slate-500">
                  Field names are the <code>name=</code> attributes on the login form's HTML inputs, not the values.
                </p>
              </>
            )}
          </div>

          {error && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>}
          {notice && <p className="mt-4 text-sm text-emerald-600 dark:text-emerald-400">{notice}</p>}

          <Button type="submit" disabled={submitting} className="mt-5">
            {submitting ? "Saving…" : "Save"}
          </Button>
        </form>
      </Card>

      <div>
        <Eyebrow>Configured domains</Eyebrow>
        <div className="mt-2 space-y-2">
          {domains === null && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}
          {domains?.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-400">None yet.</p>}
          {domains?.map((d) => (
            <Card key={d.domain} className="flex items-center justify-between p-3.5">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm text-slate-800 dark:text-slate-200">{d.domain}</span>
                <Badge>{d.method}</Badge>
              </div>
              <Button variant="danger" size="sm" onClick={() => handleDelete(d.domain)}>
                <IconTrash className="h-3.5 w-3.5" />
                Remove
              </Button>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
