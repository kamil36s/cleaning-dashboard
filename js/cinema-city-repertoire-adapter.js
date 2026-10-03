const ENDPOINT = "/api/cinema-city/repertoire";

export async function fetchCinemaCityRepertoire(options = {}) {
  const response = await fetch(ENDPOINT, {
    cache: "no-store",
    signal: options.signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok !== true || !Array.isArray(payload?.events)) {
    const error = new Error(payload?.error || `cinema_repertoire_${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}
