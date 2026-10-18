// Thin fetch wrappers. Every call returns parsed JSON or throws an ApiError with the server's message.

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

let onGraphDown = () => {};
export function setGraphDownHandler(fn) { onGraphDown = fn; }

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the WhyBase server.");
  }
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const err = (isJson && data.error) || { code: "error", message: String(data) };
    if (res.status === 503) onGraphDown(err.message);
    throw new ApiError(res.status, err.code, err.message);
  }
  return data;
}

export const api = {
  health: () => request("GET", "/api/health"),
  stats: () => request("GET", "/api/stats"),
  entities: () => request("GET", "/api/entities"),
  examples: () => request("GET", "/api/examples"),
  chat: (question) => request("POST", "/api/chat", { question }),
  stale: () => request("GET", "/api/stale"),
  review: (sourceId, oldId, by) => request("POST", `/api/stale/${encodeURIComponent(sourceId)}/review`, { old_id: oldId, by }),
  risk: () => request("GET", "/api/risk"),
  loadBearing: (limit = 5) => request("GET", `/api/load-bearing?limit=${limit}`),
  asOf: (system, date) => request("GET", `/api/as-of?system=${encodeURIComponent(system)}&date=${encodeURIComponent(date)}`),
  propose: (text, author) => request("POST", "/api/ingest/propose", { text, author: author || null }),
  confirm: (proposal) => request("POST", "/api/ingest/confirm", proposal),
  graph: (names) => request("POST", "/api/graph", { names }),
  graphAll: () => request("GET", "/api/graph/all"),
  query: (name) => request("GET", `/api/queries/${encodeURIComponent(name)}`),
  reset: () => request("POST", "/api/reset"),
};
