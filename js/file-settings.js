const API_BASE = "/api/settings";
const KEEPALIVE_MAX_BYTES = 60 * 1024;

const canUseStorage = () => typeof window !== "undefined" && !!window.localStorage;
const canUseFetch = () => {
  if (typeof window === "undefined" || typeof fetch !== "function") return false;
  const protocol = window.location?.protocol || "";
  const host = window.location?.host || "";
  if (host === "localhost:3000") return false;
  return protocol === "http:" || protocol === "https:";
};

async function readJsonResponse(response, fallback = null) {
  const payload = typeof response?.json === "function"
    ? await response.json().catch(() => ({}))
    : {};
  if (!response?.ok || payload?.ok === false) {
    throw new Error(payload?.error || response?.statusText || "Settings API error");
  }
  return payload?.data === undefined ? fallback : payload.data;
}

export function readLocalSetting(storageKey, fallback = null) {
  if (!canUseStorage() || !storageKey) return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function writeLocalSetting(storageKey, value) {
  if (!canUseStorage() || !storageKey) return;
  try {
    if (value === null || value === undefined) {
      window.localStorage.removeItem(storageKey);
    } else {
      window.localStorage.setItem(storageKey, JSON.stringify(value));
    }
  } catch {}
}

export async function fetchFileSetting(name, fallback = null) {
  if (!canUseFetch()) return fallback;
  const response = await fetch(`${API_BASE}/${encodeURIComponent(name)}`, { cache: "no-store" });
  return readJsonResponse(response, fallback);
}

export async function saveFileSetting(name, value) {
  if (!canUseFetch()) return value;
  const body = JSON.stringify({ data: value });
  const bodyBytes = typeof TextEncoder === "function"
    ? new TextEncoder().encode(body).byteLength
    : body.length;
  const response = await fetch(`${API_BASE}/${encodeURIComponent(name)}`, {
    method: "POST",
    keepalive: bodyBytes <= KEEPALIVE_MAX_BYTES,
    headers: { "Content-Type": "application/json" },
    body,
  });
  return readJsonResponse(response, value);
}

export async function loadFileBackedSetting({
  name,
  storageKey,
  fallback = null,
  normalize = (value) => value,
  migrateLocal = true,
} = {}) {
  let serverValue = null;
  let hasServerValue = false;
  try {
    serverValue = await fetchFileSetting(name, null);
    hasServerValue = serverValue !== null && serverValue !== undefined;
  } catch {}

  if (hasServerValue) {
    const normalized = normalize(serverValue);
    writeLocalSetting(storageKey, normalized);
    return normalized;
  }

  const localValue = readLocalSetting(storageKey, null);
  if (localValue !== null && localValue !== undefined) {
    const normalized = normalize(localValue);
    if (migrateLocal) {
      saveFileSetting(name, normalized).catch(() => {});
    }
    return normalized;
  }

  return normalize(fallback);
}

export function saveFileBackedSetting({ name, storageKey, value } = {}) {
  writeLocalSetting(storageKey, value);
  saveFileSetting(name, value).catch(() => {});
  return value;
}
