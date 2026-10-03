function normalizedText(value) {
  return String(value || "").trim().toLocaleLowerCase("pl-PL");
}

function localDateKey(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const SORTERS = {
  newest: (left, right) => new Date(right.recordedAt).getTime() - new Date(left.recordedAt).getTime(),
  oldest: (left, right) => new Date(left.recordedAt).getTime() - new Date(right.recordedAt).getTime(),
  longest: (left, right) => Number(right.durationSeconds || 0) - Number(left.durationSeconds || 0),
  shortest: (left, right) => Number(left.durationSeconds || 0) - Number(right.durationSeconds || 0),
};

export function filterVoiceJournalEntries(entries, filters = {}) {
  const query = normalizedText(filters.query);
  const tag = normalizedText(filters.tag);
  const filtered = (Array.isArray(entries) ? entries : []).filter((entry) => {
    const recordedDate = localDateKey(entry.recordedAt);
    if (query && !normalizedText(
      `${entry.title || ""}\n${entry.originalFilename || ""}\n${entry.transcript || ""}\n${entry.rawTranscript || ""}`,
    ).includes(query)) return false;
    if (filters.dateFrom && recordedDate < filters.dateFrom) return false;
    if (filters.dateTo && recordedDate > filters.dateTo) return false;
    if (filters.entryCategory && entry.entryCategory !== filters.entryCategory) return false;
    if (tag && !(entry.tags || []).some((entryTag) => normalizedText(entryTag) === tag)) return false;
    if (filters.model && entry.model !== filters.model) return false;
    return true;
  });
  return filtered
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => (
      Number(Boolean(left.entry.journalPublication)) - Number(Boolean(right.entry.journalPublication))
      || (SORTERS[filters.sort] || SORTERS.newest)(left.entry, right.entry)
      || left.index - right.index
    ))
    .map(({ entry }) => entry);
}

export function voiceJournalFilterOptions(entries) {
  const tags = new Map();
  const models = new Set();
  (Array.isArray(entries) ? entries : []).forEach((entry) => {
    (entry.tags || []).forEach((tag) => {
      const text = String(tag || "").trim();
      const key = normalizedText(text);
      if (text && !tags.has(key)) tags.set(key, text);
    });
    if (entry.model) models.add(String(entry.model));
  });
  return {
    tags: Array.from(tags.values()).sort((left, right) => left.localeCompare(right, "pl")),
    models: Array.from(models).sort((left, right) => left.localeCompare(right, "pl")),
  };
}

export function hasActiveVoiceJournalFilters(filters = {}) {
  return Boolean(
    String(filters.query || "").trim()
    || filters.dateFrom
    || filters.dateTo
    || filters.entryCategory
    || filters.tag
    || filters.model
    || (filters.sort && filters.sort !== "newest")
  );
}
