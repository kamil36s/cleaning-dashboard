const request = async (path, options = {}) => {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Strength API: ${response.status}`);
  return payload;
};

export const strengthApi = Object.freeze({
  dashboard: (week) => request(`/api/strength/dashboard${week ? `?week=${encodeURIComponent(week)}` : ""}`),
  exercises: () => request("/api/strength/exercises"),
  history: (limit = 200) => request(`/api/strength/history?limit=${limit}`),
  equipment: () => request("/api/strength/equipment"),
  settings: () => request("/api/strength/settings"),
  startSession: (payload) => request("/api/strength/sessions", { method: "POST", body: JSON.stringify(payload) }),
  completeSession: (id) => request(`/api/strength/sessions/${encodeURIComponent(id)}/complete`, { method: "POST", body: "{}" }),
  saveSet: (payload) => request("/api/strength/sets", { method: "POST", body: JSON.stringify(payload) }),
  saveEquipment: (items) => request("/api/strength/equipment", { method: "POST", body: JSON.stringify({ items }) }),
  reportRecovery: (muscleGroup, soreness) => request("/api/strength/recovery", { method: "POST", body: JSON.stringify({ muscleGroup, soreness }) }),
  saveSettings: (xp) => request("/api/strength/settings", { method: "POST", body: JSON.stringify({ xp }) }),
});
