const ENTRIES_URL = "/api/journal/entries";

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = payload.error?.code || payload.code || "api_error";
    const error = new Error(code === "VERSION_CONFLICT"
      ? "Wpis zmienił się na innym urządzeniu. Twój szkic pozostaje w edytorze. Odśwież dane i porównaj zmiany przed ponownym zapisem."
      : payload.error?.message || payload.error || response.statusText || "Błąd API Dziennika");
    error.code = code;
    error.details = payload.error?.details;
    error.status = response.status;
    throw error;
  }
  return payload;
}

export async function fetchJournalEntries(fetchImpl = fetch) {
  const response = await fetchImpl(ENTRIES_URL, { cache: "no-store" });
  const payload = await readJson(response);
  return Array.isArray(payload.entries) ? payload.entries : [];
}

export async function fetchJournalContexts(dates, fetchImpl = fetch) {
  const response = await fetchImpl("/api/journal/context", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dates }),
  });
  const payload = await readJson(response);
  return payload.contexts && typeof payload.contexts === "object" ? payload.contexts : {};
}

export async function createJournalEntry(entry, fetchImpl = fetch) {
  const response = await fetchImpl(ENTRIES_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
  return readJson(response);
}

export async function updateJournalEntry(id, patch, fetchImpl = fetch) {
  const response = await fetchImpl(`${ENTRIES_URL}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return readJson(response);
}

export async function deleteJournalEntry(id, fetchImpl = fetch, expectedVersion) {
  const query = Number.isInteger(expectedVersion) ? `?expectedVersion=${expectedVersion}` : "";
  const response = await fetchImpl(`${ENTRIES_URL}/${encodeURIComponent(id)}${query}`, { method: "DELETE" });
  return readJson(response);
}

export async function publishVoiceJournalEntry(voiceJournalEntryId, fetchImpl = fetch) {
  const response = await fetchImpl(
    `/api/journal/publish/voice-journal/${encodeURIComponent(voiceJournalEntryId)}`,
    { method: "POST" },
  );
  return readJson(response);
}
