const DEFAULT_RUNTIME_PORT = 8766;
const RUNTIME_OVERRIDE_KEY = "liveWorkout.runtimeBase.v1";

function configuredBase() {
  const globalOverride = String(globalThis.__TRAINING_RUNTIME_BASE__ || "").trim();
  if (globalOverride) return globalOverride;
  try {
    const stored = String(globalThis.localStorage?.getItem(RUNTIME_OVERRIDE_KEY) || "").trim();
    if (stored) return stored;
  } catch {}
  return "";
}

export function liveWorkoutRuntimeBase(locationLike = globalThis.location) {
  const override = configuredBase();
  if (override) return override.replace(/\/+$/, "");
  const locationHostname = locationLike?.hostname || "127.0.0.1";
  const hostname = ["localhost", "::1"].includes(locationHostname) ? "127.0.0.1" : locationHostname;
  // This dashboard is local-first. The runtime intentionally uses its own
  // process/port so a Vite or dashboard API restart cannot interrupt training.
  return `http://${hostname.includes(":") ? `[${hostname}]` : hostname}:${DEFAULT_RUNTIME_PORT}`;
}

export function liveWorkoutRuntimeUrl(path = "", locationLike = globalThis.location) {
  const suffix = String(path || "").startsWith("/") ? String(path) : `/${path}`;
  return `${liveWorkoutRuntimeBase(locationLike)}/api/live-workout${suffix === "/" ? "" : suffix}`;
}

export { DEFAULT_RUNTIME_PORT, RUNTIME_OVERRIDE_KEY };
