const BASE = "/api/feelings";

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `Feelings request failed (${response.status})`);
    error.code = payload.code || "feelings_request_failed";
    error.status = response.status;
    throw error;
  }
  return payload;
}

function queryString(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, value);
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

export const feelingsApi = {
  listCheckins: (filters) => request(`/checkins${queryString(filters)}`),
  getCheckin: (id) => request(`/checkins/${encodeURIComponent(id)}`),
  createCheckin: (payload) => request("/checkins", { method: "POST", body: JSON.stringify(payload) }),
  updateCheckin: (id, payload) => request(`/checkins/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteCheckin: (id) => request(`/checkins/${encodeURIComponent(id)}?confirm=delete`, { method: "DELETE" }),
  listEmotions: () => request("/emotions"),
  createEmotion: (payload) => request("/emotions", { method: "POST", body: JSON.stringify(payload) }),
  listTags: () => request("/tags"),
  createTag: (payload) => request("/tags", { method: "POST", body: JSON.stringify(payload) }),
  insights: (days) => request(`/insights${queryString({ days })}`),
  importData: (payload) => request("/import", { method: "POST", body: JSON.stringify(payload) }),
  exportUrl: (format) => `${BASE}/export?format=${encodeURIComponent(format)}`,
};

