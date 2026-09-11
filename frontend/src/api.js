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
};

export { API_BASE };
