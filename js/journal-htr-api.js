const BASE = "/api/journal-htr";

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || response.statusText || "Błąd modułu HTR");
    error.code = payload.code || "api_error";
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function request(path, options = {}, fetchImpl = fetch) {
  return readJson(await fetchImpl(`${BASE}${path}`, { cache: "no-store", ...options }));
}

function jsonOptions(method, payload) {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

export const fetchHtrStatus = (refresh = false, fetchImpl = fetch) =>
  request(`/status${refresh ? "?refresh=1" : ""}`, {}, fetchImpl);
export const startHtrServer = (fetchImpl = fetch) =>
  request("/server/start", { method: "POST" }, fetchImpl);
export const stopHtrServer = (fetchImpl = fetch) =>
  request("/server/stop", { method: "POST" }, fetchImpl);
export const fetchHtrProjects = (fetchImpl = fetch) =>
  request("/projects", {}, fetchImpl);
export const fetchHtrPages = (projectId = "", fetchImpl = fetch) =>
  request(`/pages${projectId ? `?projectId=${encodeURIComponent(projectId)}` : ""}`, {}, fetchImpl);
export const fetchHtrLines = (filters = {}, fetchImpl = fetch) => {
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value !== "" && value !== null && value !== undefined)
  );
  return request(`/lines${query.size ? `?${query}` : ""}`, {}, fetchImpl);
};
export const fetchHtrDatasetStats = (fetchImpl = fetch) =>
  request("/dataset/stats", {}, fetchImpl);
export const fetchHtrDatasets = (fetchImpl = fetch) =>
  request("/datasets", {}, fetchImpl);
export const fetchHtrModels = (fetchImpl = fetch) =>
  request("/models", {}, fetchImpl);
export const fetchHtrJobs = (fetchImpl = fetch) =>
  request("/jobs", {}, fetchImpl);
export const fetchHtrJob = (id, fetchImpl = fetch) =>
  request(`/jobs/${encodeURIComponent(id)}`, {}, fetchImpl);

export const uploadHtrPages = (formData, fetchImpl = fetch) =>
  request("/upload", { method: "POST", body: formData }, fetchImpl);
export const createHtrProject = (payload, fetchImpl = fetch) =>
  request("/projects", jsonOptions("POST", payload), fetchImpl);
export const startHtrSegmentation = (payload, fetchImpl = fetch) =>
  request("/segment", jsonOptions("POST", payload), fetchImpl);
export const startHtrTranscription = (payload, fetchImpl = fetch) =>
  request("/transcribe", jsonOptions("POST", payload), fetchImpl);
export const syncHtrProvider = (fetchImpl = fetch) =>
  request("/sync", { method: "POST" }, fetchImpl);
export const rotateHtrPage = (id, angle, fetchImpl = fetch) =>
  request(`/pages/${encodeURIComponent(id)}/rotate`, jsonOptions("POST", { angle }), fetchImpl);
export const preprocessHtrPage = (id, payload, fetchImpl = fetch) =>
  request(`/pages/${encodeURIComponent(id)}/preprocess`, jsonOptions("POST", payload), fetchImpl);
export const reorderHtrPages = (pageIds, fetchImpl = fetch) =>
  request("/pages/reorder", jsonOptions("POST", { pageIds }), fetchImpl);
export const deleteHtrPage = (id, fetchImpl = fetch) =>
  request(`/pages/${encodeURIComponent(id)}?confirm=delete`, { method: "DELETE" }, fetchImpl);
export const updateHtrLine = (id, payload, fetchImpl = fetch) =>
  request(`/lines/${encodeURIComponent(id)}`, jsonOptions("PATCH", payload), fetchImpl);
export const mergeHtrLines = (lineId, otherLineId, fetchImpl = fetch) =>
  request(`/lines/${encodeURIComponent(lineId)}/merge`, jsonOptions("POST", { otherLineId }), fetchImpl);
export const createHtrDataset = (payload, fetchImpl = fetch) =>
  request("/datasets", jsonOptions("POST", payload), fetchImpl);
export const startHtrTraining = (payload, fetchImpl = fetch) =>
  request("/training/jobs", jsonOptions("POST", payload), fetchImpl);
export const activateHtrModel = (id, fetchImpl = fetch) =>
  request(`/models/${encodeURIComponent(id)}/activate`, { method: "POST" }, fetchImpl);
export const archiveHtrModel = (id, fetchImpl = fetch) =>
  request(`/models/${encodeURIComponent(id)}/archive`, { method: "POST" }, fetchImpl);
export const deleteHtrModel = (id, fetchImpl = fetch) =>
  request(`/models/${encodeURIComponent(id)}?confirm=delete`, { method: "DELETE" }, fetchImpl);
export const cancelHtrModelTraining = (id, fetchImpl = fetch) =>
  request(`/models/${encodeURIComponent(id)}/cancel-training`, { method: "POST" }, fetchImpl);
export const cancelHtrJob = (id, fetchImpl = fetch) =>
  request(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }, fetchImpl);
export const exportHtrToJournal = (payload, fetchImpl = fetch) =>
  request("/export", jsonOptions("POST", payload), fetchImpl);
