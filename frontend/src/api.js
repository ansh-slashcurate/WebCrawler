const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    const err = new Error(detail || `${res.status} ${res.statusText}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  health: () => request("/api/health"),
  entities: () => request("/api/entities"),
  runs: (entity) => request(`/api/runs?entity=${encodeURIComponent(entity)}`),
  runDetail: (entity, runId) => request(`/api/runs/${encodeURIComponent(entity)}/${encodeURIComponent(runId)}`),
  runPages: (entity, runId, { offset = 0, limit = 20, q = "" } = {}) =>
    request(
      `/api/runs/${encodeURIComponent(entity)}/${encodeURIComponent(runId)}/pages?offset=${offset}&limit=${limit}&q=${encodeURIComponent(q)}`
    ),
  runBlocked: (entity, runId) => request(`/api/runs/${encodeURIComponent(entity)}/${encodeURIComponent(runId)}/blocked`),
  startCrawl: (payload) =>
    request("/api/crawls", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  crawls: () => request("/api/crawls"),
  crawlStatus: (token) => request(`/api/crawls/${encodeURIComponent(token)}`),
  authDomains: () => request("/api/auth-domains"),
  upsertAuthDomain: (payload) =>
    request("/api/auth-domains", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteAuthDomain: (domain) =>
    request(`/api/auth-domains/${encodeURIComponent(domain)}`, { method: "DELETE" }),

  settings: () => request("/api/settings"),
  updateSettings: (payload) =>
    request("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  // ---- Tenders page: saved bank sites, tags, per-run tender records, watsonx classify ----
  bankSites: () => request("/api/bank-sites"),
  addBankSite: (payload) =>
    request("/api/bank-sites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteBankSite: (id) => request(`/api/bank-sites/${encodeURIComponent(id)}`, { method: "DELETE" }),

  tenderTags: () => request("/api/tender-tags"),
  addTenderTag: (payload) =>
    request("/api/tender-tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTenderTag: (id) => request(`/api/tender-tags/${encodeURIComponent(id)}`, { method: "DELETE" }),

  runTenders: (entity, runId, { offset = 0, limit = 20, q = "", classification = "", tag = "", filtered = true } = {}) =>
    request(
      `/api/runs/${encodeURIComponent(entity)}/${encodeURIComponent(runId)}/tenders` +
        `?offset=${offset}&limit=${limit}&q=${encodeURIComponent(q)}` +
        `&classification=${encodeURIComponent(classification)}&tag=${encodeURIComponent(tag)}` +
        `&filtered=${filtered ? "true" : "false"}`
    ),
  classifyTenders: (entity, runId, tagIds) =>
    request(`/api/runs/${encodeURIComponent(entity)}/${encodeURIComponent(runId)}/tenders/classify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag_ids: tagIds && tagIds.length ? tagIds : null }),
    }),
  classifyStatus: (token) => request(`/api/tender-classify/${encodeURIComponent(token)}`),
  pipelineLogs: (entity, runId, limit = 100) =>
    request(`/api/runs/${encodeURIComponent(entity)}/${encodeURIComponent(runId)}/pipeline-logs?limit=${limit}`),
};

export { API_BASE };
