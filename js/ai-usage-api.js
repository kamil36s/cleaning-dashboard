export async function fetchAiUsage(fetchImpl = globalThis.fetch, options = {}) {
  const params = new URLSearchParams();
  if (Number.isFinite(Number(options.historyHours))) params.set("historyHours", String(options.historyHours));
  if (Number.isFinite(Number(options.sessionLimit))) params.set("sessionLimit", String(options.sessionLimit));
  const query = params.size ? `?${params}` : "";
  const response = await fetchImpl(`/api/ai-usage${query}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`AI Usage HTTP ${response.status}`);
  return response.json();
}
