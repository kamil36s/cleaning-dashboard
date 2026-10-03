const API_BASE = "/api/ring";

async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
        cache: "no-store",
        headers: options.body ? { "Content-Type": "application/json" } : undefined,
        ...options,
    });
    let payload;
    try {
        payload = await response.json();
    } catch (_) {
        payload = { error: `Backend zwrócił HTTP ${response.status}` };
    }
    if (!response.ok) {
        const error = new Error(payload.error || `Błąd HTTP ${response.status}`);
        error.code = payload.code || "ring_api_error";
        error.status = response.status;
        throw error;
    }
    return payload;
}

export const ringApi = {
    state: () => request("/state"),
    history: (limit = 2000) => request(`/history?limit=${encodeURIComponent(limit)}`),
    diagnostics: (limit = 100) => request(`/diagnostics?limit=${encodeURIComponent(limit)}`),
    presence: () => request("/presence", { method: "POST", body: "{}" }),
    scan: (timeoutSeconds = 8) => request("/scan", { method: "POST", body: JSON.stringify({ timeoutSeconds }) }),
    connect: (deviceId) => request("/connect", { method: "POST", body: JSON.stringify({ deviceId }) }),
    disconnect: () => request("/disconnect", { method: "POST", body: "{}" }),
    sync: () => request("/sync", { method: "POST", body: "{}" }),
};
