export const PAGE_TOTALS_STORAGE_KEY = "dashboard.synchrobook.page-totals.v1";

export function normalizeTotalPages(value) {
  const pages = Number(value);
  return Number.isInteger(pages) && pages >= 1 && pages <= 99999 ? pages : null;
}

export function currentPageAtTime(currentTime, duration, totalPages) {
  const current = Number(currentTime);
  const totalDuration = Number(duration);
  const pages = normalizeTotalPages(totalPages);
  if (!Number.isFinite(current) || !Number.isFinite(totalDuration) || totalDuration <= 0 || pages == null) return null;
  const progress = Math.min(1, Math.max(0, current / totalDuration));
  return Math.min(pages, Math.max(1, Math.ceil(progress * pages)));
}

export function loadPageTotals(storage = globalThis.localStorage) {
  try {
    const parsed = JSON.parse(storage?.getItem(PAGE_TOTALS_STORAGE_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).flatMap(([bookId, value]) => {
        const pages = normalizeTotalPages(value);
        return bookId && pages != null ? [[bookId, pages]] : [];
      }),
    );
  } catch {
    return {};
  }
}

export function savePageTotals(pageTotals, storage = globalThis.localStorage) {
  try {
    storage?.setItem(PAGE_TOTALS_STORAGE_KEY, JSON.stringify(pageTotals));
  } catch {
    // The counter still works for this session when browser storage is unavailable.
  }
}
