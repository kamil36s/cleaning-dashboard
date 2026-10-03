export const CINEMA_CITY_STATS_PLACEHOLDER = Object.freeze({
  sheetName: "Cinema City Galeria Kazimierz",
  watchedMoviesColumn: "D",
  pricePerFilmColumn: "E",
  endpoint: "/api/cinema-city/monthly-stats",
});

export async function fetchCinemaCityMonthlyStats(options = {}) {
  const customAdapter = globalThis.CINEMA_CITY_MONTHLY_STATS_ADAPTER;
  if (typeof customAdapter === "function") {
    return customAdapter(options);
  }

  const endpoint = String(
    globalThis.CINEMA_CITY_MONTHLY_STATS_ENDPOINT ||
    CINEMA_CITY_STATS_PLACEHOLDER.endpoint ||
    "",
  ).trim();
  if (!endpoint) {
    return { configured: false };
  }

  const response = await fetch(endpoint, {
    cache: "no-store",
    signal: options.signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const error = new Error(payload?.error || `cinema_stats_${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return response.json();
}
