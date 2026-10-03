export function startLoadTimer() {
  const startedAt = nowMs();
  return () => Math.max(0, nowMs() - startedAt);
}

export function formatLoadTime(ms) {
  const value = Number(ms);
  if (!Number.isFinite(value)) return "";
  if (value < 1000) return `${Math.max(1, Math.round(value))} ms`;
  if (value < 10000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.round(value / 1000)} s`;
}

export function formatLoadedAt(date = new Date()) {
  const value = date instanceof Date ? date : new Date(date);
  if (!Number.isFinite(value.getTime())) return "";
  return value.toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function loadTimeSuffix(ms, label = "load") {
  const text = formatLoadTime(ms);
  return text ? `${label} ${text}` : "";
}

function nowMs() {
  return globalThis.performance?.now ? globalThis.performance.now() : Date.now();
}
