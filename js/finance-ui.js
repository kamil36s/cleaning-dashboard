export function polishMonthLabel(month) {
  if (!/^\d{4}-\d{2}$/.test(String(month || ""))) return "—";
  const [year, monthNumber] = month.split("-").map(Number);
  return new Intl.DateTimeFormat("pl-PL", { month: "long", year: "numeric" })
    .format(new Date(year, monthNumber - 1, 1));
}

export function chooseDefaultFinanceMonth(currentMonth, latestTransactionDate) {
  const latestMonth = /^\d{4}-\d{2}-\d{2}$/.test(String(latestTransactionDate || ""))
    ? latestTransactionDate.slice(0, 7)
    : null;
  if (!latestMonth || latestMonth === currentMonth) return currentMonth;
  return latestMonth;
}

export function financePeriodOptions(selectedMonth, currentMonth, count = 24) {
  const months = new Set([selectedMonth, currentMonth].filter(Boolean));
  const anchor = /^\d{4}-\d{2}$/.test(selectedMonth) ? selectedMonth : currentMonth;
  if (anchor) {
    const [year, month] = anchor.split("-").map(Number);
    for (let offset = 0; offset < count; offset += 1) {
      const value = new Date(year, month - 1 - offset, 1);
      months.add(`${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}`);
    }
  }
  return [...months].sort().reverse().map((value) => ({ value, label: polishMonthLabel(value) }));
}

export function onboardingVisibility(dismissed, completed, total) {
  return { hidden: Boolean(dismissed), complete: total > 0 && completed === total };
}

export function hierarchicalCategoryOptions(categories = []) {
  const parents = new Map(categories.filter((item) => !item.parentId).map((item) => [Number(item.id), item.name]));
  return categories.map((item) => ({
    ...item,
    label: item.parentName || item.parentId
      ? `${item.parentName || parents.get(Number(item.parentId)) || "Inne"} → ${item.name}`
      : item.name,
  }));
}

export function reviewScopeLabel(scope, monthLabel) {
  return scope === "all_history" ? "Cała historia" : `Wybrany miesiąc: ${monthLabel}`;
}

export function reviewPreviewLines(preview, labels = {}) {
  const changes = preview?.changes || {};
  return [
    `${preview?.transactionCount || 0} transakcji zostanie zmienionych`,
    changes.merchant ? `Miejsce: brak → ${labels.merchant || "wybrane"} (${changes.merchant})` : null,
    changes.category ? `Kategoria: brak → ${labels.category || "wybrana"} (${changes.category})` : null,
    changes.taxonomyReview ? `Potwierdzenie istniejącego mapowania kategorii: ${changes.taxonomyReview}` : null,
    changes.transactionKind ? `Rodzaj: brak → ${labels.transactionKind || "wybrany"} (${changes.transactionKind})` : "Rodzaj transakcji: bez zmian",
    `Ręczne klasyfikacje nadpisane: ${preview?.manualClassificationsOverwritten || 0}`,
    "Kwoty historyczne zmienione: 0 zł",
  ].filter(Boolean);
}
