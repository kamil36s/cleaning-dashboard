const BASE = "/api/mental-health";

async function request(path, options = {}, fetchImpl = globalThis.fetch) {
  const response = await fetchImpl(`${BASE}${path}`, {
    cache: "no-store",
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) throw new Error(payload?.error || `Mental Health HTTP ${response.status}`);
  return payload;
}

export const fetchMentalHealthOverview = (fetchImpl) => request("/overview", {}, fetchImpl);
export const fetchMentalHealthExport = (fetchImpl) => request("/export", {}, fetchImpl);

export const createAssessment = (payload, fetchImpl) => request("/assessments", {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const saveAssessmentDraft = (instrumentId, payload, fetchImpl) => request(`/drafts/${encodeURIComponent(instrumentId)}`, {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const createCheckin = (payload, fetchImpl) => request("/checkins", {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const createMentalHealthEvent = (payload, fetchImpl) => request("/events", {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const createCustomQuestionnaire = (payload, fetchImpl) => request("/custom-questionnaires", {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const updateAssessmentSchedule = (instrumentId, payload, fetchImpl) => request(`/schedules/${encodeURIComponent(instrumentId)}`, {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const updateMentalHealthSettings = (payload, fetchImpl) => request("/settings", {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const importMentalHealthData = (payload, fetchImpl) => request("/import", {
  method: "POST", body: JSON.stringify(payload),
}, fetchImpl);

export const deleteMentalHealthEntry = (kind, id, fetchImpl) => request(`/${kind}/${encodeURIComponent(id)}`, {
  method: "DELETE",
}, fetchImpl);

export const deleteAllMentalHealthData = (fetchImpl) => request("/all?confirm=delete", {
  method: "DELETE",
}, fetchImpl);

export const setAssessmentBaseline = (id, fetchImpl) => request(`/assessments/${encodeURIComponent(id)}/baseline`, {
  method: "POST", body: "{}",
}, fetchImpl);
