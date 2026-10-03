const BASE_URL = "/api/timeline";

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || response.statusText || "Timeline API error");
    error.code = payload.code || "api_error";
    error.details = payload.details || [];
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function jsonRequest(url, method, body, fetchImpl = fetch) {
  return readJson(await fetchImpl(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function fetchTimeline(fetchImpl = fetch) {
  return readJson(await fetchImpl(BASE_URL, { cache: "no-store" }));
}

export async function fetchTimelineSummary(fetchImpl = fetch) {
  return readJson(await fetchImpl(`${BASE_URL}/summary`, { cache: "no-store" }));
}

export function createTimelineItem(item, fetchImpl = fetch) {
  return jsonRequest(`${BASE_URL}/items`, "POST", item, fetchImpl);
}

export function updateTimelineItem(id, patch, fetchImpl = fetch) {
  return jsonRequest(`${BASE_URL}/items/${encodeURIComponent(id)}`, "PATCH", patch, fetchImpl);
}

export async function deleteTimelineItem(id, fetchImpl = fetch) {
  return readJson(await fetchImpl(`${BASE_URL}/items/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

export function createTimelineCategory(category, fetchImpl = fetch) {
  return jsonRequest(`${BASE_URL}/categories`, "POST", category, fetchImpl);
}

export function updateTimelineCategory(id, patch, fetchImpl = fetch) {
  return jsonRequest(`${BASE_URL}/categories/${encodeURIComponent(id)}`, "PATCH", patch, fetchImpl);
}

export async function deleteTimelineCategory(id, moveTo = "", fetchImpl = fetch) {
  const query = moveTo ? `?moveTo=${encodeURIComponent(moveTo)}` : "";
  return readJson(await fetchImpl(`${BASE_URL}/categories/${encodeURIComponent(id)}${query}`, { method: "DELETE" }));
}

export function importTimeline(data, options = {}, fetchImpl = fetch) {
  return jsonRequest(`${BASE_URL}/import`, "POST", {
    data,
    mode: options.mode || "merge",
    conflict: options.conflict || "overwrite",
    dryRun: options.dryRun === true,
  }, fetchImpl);
}
