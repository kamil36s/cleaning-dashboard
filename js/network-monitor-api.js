const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);

function normalizeBase(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

export function getNetworkApiBase() {
  const htmlBase = document.documentElement?.dataset?.networkApiBase;
  const bodyBase = document.body?.dataset?.networkApiBase;
  const winBase = window.__NETWORK_MONITOR_CONFIG__?.apiBase;
  const envBase = import.meta?.env?.VITE_NETWORK_API_BASE;
  const defaultBase = LOCAL_HOSTS.has(window.location.hostname)
    ? "http://127.0.0.1:8765"
    : "";

  return (
    normalizeBase(winBase) ||
    normalizeBase(htmlBase) ||
    normalizeBase(bodyBase) ||
    normalizeBase(envBase) ||
    defaultBase
  );
}

async function parseJsonSafe(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

export async function getNetworkJson(path) {
  const apiBase = getNetworkApiBase();
  const response = await fetch(`${apiBase}${path}`, { cache: "no-store" });
  if (!response.ok) {
    const payload = await parseJsonSafe(response);
    throw new Error(payload?.error || `API error ${response.status}`);
  }
  return response.json();
}

export async function postNetworkJson(path, body = {}) {
  const apiBase = getNetworkApiBase();
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await parseJsonSafe(response);
    throw new Error(payload?.error || `API error ${response.status}`);
  }
  return response.json();
}

export async function fetchNetworkDevices() {
  const payload = await getNetworkJson("/api/network/devices");
  return Array.isArray(payload) ? payload : Array.isArray(payload?.devices) ? payload.devices : [];
}

export async function fetchNetworkSummary() {
  return getNetworkJson("/api/network/summary");
}

export async function fetchNetworkDeviceNames() {
  const payload = await getNetworkJson("/api/network/device-names");
  return payload?.names && typeof payload.names === "object" ? payload.names : {};
}

export async function fetchNetworkDeviceProfiles() {
  const payload = await getNetworkJson("/api/network/device-profiles");
  return payload?.profiles && typeof payload.profiles === "object" ? payload.profiles : {};
}

export async function fetchNetworkDeviceHistory(deviceKey, day) {
  const params = new URLSearchParams();
  if (deviceKey === "__all__") {
    params.set("scope", "all");
  } else if (deviceKey) {
    params.set("device_key", deviceKey);
  }
  if (day) params.set("day", day);
  const payload = await getNetworkJson(`/api/network/history?${params.toString()}`);
  return payload?.device && typeof payload.device === "object" ? payload.device : null;
}

export async function saveNetworkDeviceName(mac, name) {
  return postNetworkJson("/api/network/device-names", { mac, name });
}

export async function saveNetworkDeviceProfile({ mac, name, category, owner }) {
  return postNetworkJson("/api/network/device-profiles", {
    mac,
    name,
    category,
    owner,
  });
}
