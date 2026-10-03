import {
  applyBudgetRuleSuggestions,
  buildBudgetRuleSuggestions,
  DEFAULT_BUDGET_DATA,
  formatBudgetDate,
  formatBudgetMoney,
  getBudgetTransactionCategory,
  getBudgetTransactionPlace,
  normalizeBudgetData,
  normalizeBudgetText,
  summarizeBudgetData,
  updateBudgetTransaction,
} from "./budget.js";
import {
  classifyBudgetTransaction,
  createBudgetRule,
  fetchBudgetAnalytics,
  fetchBudgetCategories,
  fetchBudgetClassification,
  fetchBudgetReview,
  fetchBudgetServerData,
  importBudgetCsvToServer,
  migrateLegacyBudgetData,
  updateBudgetAnnotations,
  updateBudgetReview,
  updateBudgetSettings,
} from "./budget-api.js";

const STORAGE_KEY = "budgetWidget.csv.v1";

const fileInput = document.getElementById("budget-page-csv-input");
const resetBtn = document.getElementById("budget-page-reset");
const statusEl = document.getElementById("budget-page-status");
const tableEl = document.getElementById("budget-table");
const emptyEl = document.getElementById("budget-page-empty");
const searchInput = document.getElementById("budget-search");
const categoryFilter = document.getElementById("budget-category-filter");
const typeFilter = document.getElementById("budget-type-filter");
const onlyUncategorized = document.getElementById("budget-only-uncategorized");
const addCategoryBtn = document.getElementById("budget-add-category");
const addTypeBtn = document.getElementById("budget-add-type");
const newCategoryInput = document.getElementById("budget-new-category");
const newTypeInput = document.getElementById("budget-new-type");
const categoryDictionary = document.getElementById("budget-category-dictionary");
const typeDictionary = document.getElementById("budget-type-dictionary");
const editorEmpty = document.getElementById("budget-editor-empty");
const editorForm = document.getElementById("budget-editor-form");
const editorClearBtn = document.getElementById("budget-editor-clear");
const categoryOptions = document.getElementById("budget-category-options");
const typeOptions = document.getElementById("budget-type-options");
const merchantOptions = document.getElementById("budget-merchant-options");
const suggestionList = document.getElementById("budget-suggestion-list");
const suggestionEmpty = document.getElementById("budget-suggestion-empty");
const suggestionMeta = document.getElementById("budget-suggestions-meta");
const refreshSuggestionsBtn = document.getElementById("budget-refresh-suggestions");
const applySuggestionsBtn = document.getElementById("budget-apply-suggestions");
const selectAllSuggestionsBtn = document.getElementById("budget-select-all-suggestions");
const clearAllSuggestionsBtn = document.getElementById("budget-clear-all-suggestions");
const periodList = document.getElementById("budget-period-list");
const periodEmpty = document.getElementById("budget-period-empty");
const periodMeta = document.getElementById("budget-periods-meta");
const periodButtons = Array.from(document.querySelectorAll("[data-budget-period]"));
const backendCurrentBtn = document.getElementById("budget-period-current");
const backendLatestBtn = document.getElementById("budget-period-latest");
const reviewList = document.getElementById("budget-review-list");
const ruleForm = document.getElementById("budget-rule-form");
const ruleCategory = document.getElementById("budget-rule-category");

let budgetData = normalizeBudgetData(DEFAULT_BUDGET_DATA);
let defaultBudgetData = normalizeBudgetData(DEFAULT_BUDGET_DATA);
let selectedId = "";
let suggestionDrafts = [];
let periodMode = "day";
let selectedPeriodKey = "";
let budgetWriteQueue = Promise.resolve();
let backendPeriod = "current_month";

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function setStatus(value) {
  if (statusEl) statusEl.textContent = value;
}

function enqueueBudgetWrite(callback) {
  const result = budgetWriteQueue.then(callback, callback);
  budgetWriteQueue = result.catch(() => undefined);
  return result;
}

function readStoredBudgetData() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return normalizeBudgetData(parsed);
  } catch (err) {
    console.warn("budget page: failed to read local data", err);
    return null;
  }
}

async function saveBudgetAnnotations(transactionIds) {
  const wanted = new Set(transactionIds);
  const updates = budgetData.transactions
    .filter((transaction) => wanted.has(transaction.id))
    .map((transaction) => ({
      id: transaction.id,
      merchant: transaction.merchant,
      merchantType: transaction.merchantType,
      userCategory: transaction.userCategory,
      note: transaction.note,
    }));
  if (!updates.length) return;
  try {
    await enqueueBudgetWrite(() => updateBudgetAnnotations(updates));
    setStatus("Zapisano opis operacji.");
  } catch (err) {
    console.warn("budget page: failed to save annotations", err);
    setStatus("Nie udało się zapisać opisu operacji.");
  }
}

async function saveBudgetSettings() {
  try {
    const settings = { ...budgetData.settings };
    await enqueueBudgetWrite(() => updateBudgetSettings(settings));
    setStatus("Zapisano ustawienia budżetu.");
  } catch (err) {
    console.warn("budget page: failed to save settings", err);
    setStatus("Nie udało się zapisać ustawień budżetu.");
  }
}

async function loadDefaultBudgetData() {
  try {
    return await fetchBudgetServerData();
  } catch (err) {
    console.warn("budget page: failed to load server data", err);
    return normalizeBudgetData(DEFAULT_BUDGET_DATA);
  }
}

async function migrateStoredBudgetData(serverData) {
  const stored = readStoredBudgetData();
  if (!stored?.transactions.length) return serverData;
  if (serverData.transactions.length) {
    localStorage.removeItem(STORAGE_KEY);
    return serverData;
  }
  try {
    const saved = await migrateLegacyBudgetData(stored);
    localStorage.removeItem(STORAGE_KEY);
    setStatus("Przeniesiono budżet z pamięci przeglądarki do bezpiecznej bazy danych.");
    return saved;
  } catch (err) {
    console.warn("budget page: failed to migrate local data", err);
    setStatus("Nie udalo sie przeniesc cache do pliku. Pokazuje lokalna kopie awaryjnie.");
    return stored;
  }
}

function uniqueLabels(labels) {
  const seen = new Set();
  const result = [];

  labels.forEach((label) => {
    const text = String(label || "").trim();
    const key = normalizeBudgetText(text);
    if (!key || seen.has(key)) return;
    seen.add(key);
    result.push(text);
  });

  return result.sort((a, b) => a.localeCompare(b, "pl"));
}

function getCategoryOptions() {
  return uniqueLabels(budgetData.settings.userCategories);
}

function getCategoryFilterOptions() {
  return uniqueLabels([
    ...budgetData.settings.userCategories,
    ...budgetData.transactions.map((transaction) => getBudgetTransactionCategory(transaction)),
  ]);
}

function getTypeOptions() {
  return uniqueLabels(budgetData.settings.merchantTypes);
}

function getTypeFilterOptions() {
  return uniqueLabels([
    ...budgetData.settings.merchantTypes,
    ...budgetData.transactions.map((transaction) => transaction.merchantType),
  ]);
}

function getMerchants() {
  return uniqueLabels(budgetData.transactions.map((transaction) => transaction.merchant));
}

function fillSelect(select, values, label = "Wszystkie") {
  if (!select) return;
  const current = select.value;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = label;
  select.appendChild(all);

  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });

  select.value = values.includes(current) ? current : "";
}

function fillDatalist(list, values) {
  if (!list) return;
  list.replaceChildren(
    ...values.map((value) => {
      const option = document.createElement("option");
      option.value = value;
      return option;
    }),
  );
}

function renderDictionaryList(container, values, kind) {
  if (!container) return;
  if (!values.length) {
    const empty = document.createElement("div");
    empty.className = "budget-dictionary-empty";
    empty.textContent = "Brak opcji w dropdownie.";
    container.replaceChildren(empty);
    return;
  }

  container.replaceChildren(
    ...values.map((value) => {
      const item = document.createElement("span");
      item.className = "budget-dictionary-chip";

      const label = document.createElement("span");
      label.textContent = value;

      const button = document.createElement("button");
      button.type = "button";
      button.dataset.action = "remove-dictionary-item";
      button.dataset.kind = kind;
      button.dataset.value = value;
      button.setAttribute("aria-label", `Usuń ${value}`);
      button.textContent = "x";

      item.append(label, button);
      return item;
    }),
  );
}

function syncDictionaries() {
  const categoryOptionsValues = getCategoryOptions();
  const typeOptionsValues = getTypeOptions();
  fillSelect(categoryFilter, getCategoryFilterOptions());
  fillSelect(typeFilter, getTypeFilterOptions());
  fillDatalist(categoryOptions, categoryOptionsValues);
  fillDatalist(typeOptions, typeOptionsValues);
  fillDatalist(merchantOptions, getMerchants());
  renderDictionaryList(categoryDictionary, categoryOptionsValues, "category");
  renderDictionaryList(typeDictionary, typeOptionsValues, "type");
}

function transactionMatchesFilters(transaction) {
  const search = normalizeBudgetText(searchInput?.value || "");
  const category = categoryFilter?.value || "";
  const type = typeFilter?.value || "";
  const ownCategory = getBudgetTransactionCategory(transaction);
  const place = getBudgetTransactionPlace(transaction);

  if (category && ownCategory !== category) return false;
  if (type && transaction.merchantType !== type) return false;
  if (onlyUncategorized?.checked && transaction.userCategory) return false;

  if (search) {
    const haystack = normalizeBudgetText([
      transaction.description,
      transaction.category,
      transaction.userCategory,
      transaction.merchant,
      transaction.merchantType,
      transaction.note,
      place,
    ].join(" "));
    if (!haystack.includes(search)) return false;
  }

  return true;
}

function getFilteredTransactions() {
  return budgetData.transactions.filter(transactionMatchesFilters);
}

function staleBudgetLabel(latestDate, now = new Date()) {
  if (!latestDate) return "";
  const timestamp = new Date(`${latestDate}T12:00:00`).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const days = Math.floor((now.getTime() - timestamp) / 86400000);
  return days > 14 ? `Dane nieaktualne (${days} dni)` : "";
}

function renderSummary() {
  const summary = summarizeBudgetData(budgetData);
  const hasRows = summary.rows > 0;
  const range = summary.range.from && summary.range.to
    ? `${formatBudgetDate(summary.range.from)} - ${formatBudgetDate(summary.range.to)}`
    : "CSV czeka na dane.";

  setText("budget-page-source", hasRows ? (summary.source.name || "Baza finansów") : "Brak importu");
  const stale = staleBudgetLabel(summary.range.to);
  setText("budget-page-range", hasRows ? `${summary.rows} operacji | ${range}${stale ? ` | ${stale}` : ""}` : range);
  setText("budget-page-balance", summary.latestBalance == null ? "-" : formatBudgetMoney(summary.latestBalance));
  setText("budget-page-spending", formatBudgetMoney(summary.totalSpending));
  setText("budget-page-income", formatBudgetMoney(summary.totalIncome));
  setText("budget-page-count", String(summary.transactionCount));
}

function createPill(text, className = "") {
  const pill = document.createElement("span");
  pill.className = `budget-page-pill ${className}`.trim();
  pill.textContent = text;
  return pill;
}

function renderTransactionRow(transaction) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = `budget-page-row ${transaction.amount < 0 ? "is-out" : "is-in"}`;
  row.dataset.id = transaction.id;
  if (transaction.id === selectedId) row.classList.add("is-selected");

  const date = document.createElement("div");
  date.className = "budget-page-date";
  date.textContent = formatBudgetDate(transaction.date) || "-";

  const main = document.createElement("div");
  main.className = "budget-page-row-main";

  const title = document.createElement("div");
  title.className = "budget-page-row-title";
  title.textContent = getBudgetTransactionPlace(transaction) || "Operacja";

  const meta = document.createElement("div");
  meta.className = "budget-page-row-meta";
  meta.append(
    createPill(getBudgetTransactionCategory(transaction), transaction.userCategory ? "is-user" : ""),
  );
  if (transaction.merchantType) meta.append(createPill(transaction.merchantType));
  if (transaction.category && transaction.category !== transaction.userCategory) {
    meta.append(createPill(transaction.category, "is-muted"));
  }
  if (transaction.note) meta.append(createPill("notatka", "is-note"));

  main.append(title, meta);

  const amount = document.createElement("div");
  amount.className = "budget-page-amount";
  amount.textContent = formatBudgetMoney(transaction.amount);

  row.append(date, main, amount);
  return row;
}

function renderTransactions() {
  if (!tableEl) return;
  const transactions = getFilteredTransactions();
  tableEl.replaceChildren(...transactions.map(renderTransactionRow));
  if (emptyEl) emptyEl.hidden = transactions.length > 0;
  setText("budget-page-table-meta", `${transactions.length} widocznych operacji`);
}

function parseIsoDateParts(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
  };
}

function dateFromIso(value) {
  const parts = parseIsoDateParts(value);
  if (!parts) return null;
  return new Date(parts.year, parts.month - 1, parts.day);
}

function isoFromDate(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function getWeekStartIso(value) {
  const date = dateFromIso(value);
  if (!date) return "";
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  return isoFromDate(date);
}

function addDays(iso, days) {
  const date = dateFromIso(iso);
  if (!date) return "";
  date.setDate(date.getDate() + days);
  return isoFromDate(date);
}

function getPeriodKey(date, mode) {
  if (mode === "month") return String(date || "").slice(0, 7);
  if (mode === "week") return getWeekStartIso(date);
  return String(date || "");
}

function formatPeriodLabel(key, mode) {
  if (!key) return "-";
  if (mode === "month") {
    const [year, month] = key.split("-").map(Number);
    return new Date(year, month - 1, 1).toLocaleDateString("pl-PL", {
      month: "long",
      year: "numeric",
    });
  }
  if (mode === "week") {
    return `${formatBudgetDate(key)} - ${formatBudgetDate(addDays(key, 6))}`;
  }
  return formatBudgetDate(key);
}

function formatPeriodChartLabel(key, mode) {
  if (!key) return "-";
  if (mode === "month") {
    const [year, month] = key.split("-").map(Number);
    return `${String(month).padStart(2, "0")}.${year}`;
  }
  if (mode === "week") {
    const start = formatBudgetDate(key).slice(0, 5);
    const end = formatBudgetDate(addDays(key, 6)).slice(0, 5);
    return `${start}-${end}`;
  }
  return formatBudgetDate(key).slice(0, 5);
}

function getPeriodDisplayLimit(mode) {
  const narrow = typeof window !== "undefined" && window.innerWidth <= 760;
  if (narrow) {
    if (mode === "day") return 7;
    if (mode === "week") return 6;
    return 6;
  }
  if (mode === "day") return 14;
  if (mode === "week") return 10;
  return 12;
}

function getDaysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

function getPeriodDayCount(period, mode) {
  if (!period?.key) return 1;
  if (mode === "day") return 1;
  if (mode === "week") return 7;
  const [year, month] = period.key.split("-").map(Number);
  const today = new Date();
  const isCurrentMonth = year === today.getFullYear() && month === today.getMonth() + 1;
  return isCurrentMonth ? today.getDate() : getDaysInMonth(year, month);
}

function getRangeDayCount(periods, mode) {
  if (!periods.length) return 1;
  if (mode === "day") return periods.length;
  if (mode === "week") return periods.length * 7;
  return periods.reduce((sum, period) => sum + getPeriodDayCount(period, mode), 0);
}

function getCurrentMonthAverage() {
  const today = new Date();
  const key = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const total = budgetData.transactions.reduce((sum, transaction) => {
    if (!isPeriodExpense(transaction) || !String(transaction.date || "").startsWith(key)) return sum;
    return sum + Math.abs(transaction.amount);
  }, 0);
  return total / Math.max(1, today.getDate());
}

function categoryMatches(category, patterns) {
  const normalized = normalizeBudgetText(category);
  return patterns.some((pattern) => normalized.includes(pattern));
}

function isPeriodExpense(transaction) {
  const category = getBudgetTransactionCategory(transaction);
  return transaction.amount < 0
    && !categoryMatches(category, budgetData.settings.ignoredCategories)
    && !categoryMatches(category, budgetData.settings.savingsCategories);
}

function addBreakdownValue(map, name, amount) {
  const label = String(name || "").trim() || "Bez opisu";
  map.set(label, (map.get(label) || 0) + amount);
}

function mapToSortedBreakdown(map) {
  return Array.from(map.entries())
    .map(([name, amount]) => ({ name, amount }))
    .sort((a, b) => b.amount - a.amount);
}

function buildPeriodInsights(mode) {
  const periods = new Map();

  budgetData.transactions.forEach((transaction) => {
    if (!isPeriodExpense(transaction)) return;
    const key = getPeriodKey(transaction.date, mode);
    if (!key) return;
    if (!periods.has(key)) {
      periods.set(key, {
        key,
        total: 0,
        count: 0,
        categories: new Map(),
        types: new Map(),
      });
    }
    const period = periods.get(key);
    const amount = Math.abs(transaction.amount);
    period.total += amount;
    period.count += 1;
    addBreakdownValue(period.categories, getBudgetTransactionCategory(transaction), amount);
    addBreakdownValue(period.types, transaction.merchantType || "Bez typu", amount);
  });

  return Array.from(periods.values())
    .map((period) => ({
      ...period,
      categories: mapToSortedBreakdown(period.categories),
      types: mapToSortedBreakdown(period.types),
    }))
    .sort((a, b) => b.key.localeCompare(a.key));
}

function getPeriodSummary(period) {
  return `${formatPeriodLabel(period.key, periodMode)} | ${formatBudgetMoney(period.total)} | ${period.count} operacji`;
}

function renderBreakdown(items, total) {
  const list = document.createElement("div");
  list.className = "budget-period-breakdown-list";

  items.slice(0, 7).forEach((item) => {
    const row = document.createElement("div");
    row.className = "budget-period-breakdown-row";

    const top = document.createElement("div");
    top.className = "budget-period-breakdown-top";

    const name = document.createElement("span");
    name.textContent = item.name;

    const amount = document.createElement("strong");
    amount.textContent = formatBudgetMoney(item.amount);

    const bar = document.createElement("div");
    bar.className = "budget-period-bar";
    const fill = document.createElement("div");
    fill.style.width = `${Math.max(3, Math.min(100, total > 0 ? (item.amount / total) * 100 : 0))}%`;
    bar.appendChild(fill);

    top.append(name, amount);
    row.append(top, bar);
    list.appendChild(row);
  });

  return list;
}

function renderPeriodCard(period) {
  const card = document.createElement("article");
  card.className = "budget-period-card";

  const head = document.createElement("div");
  head.className = "budget-period-card-head";

  const titleWrap = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = formatPeriodLabel(period.key, periodMode);
  const count = document.createElement("p");
  count.className = "meta";
  count.textContent = `${period.count} operacji`;
  titleWrap.append(title, count);

  const total = document.createElement("strong");
  total.className = "budget-period-total";
  total.textContent = formatBudgetMoney(period.total);

  head.append(titleWrap, total);

  const grids = document.createElement("div");
  grids.className = "budget-period-breakdowns";

  [
    { title: "Kategorie", items: period.categories },
    { title: "Typy miejsca", items: period.types },
  ].forEach((section) => {
    const column = document.createElement("section");
    column.className = "budget-period-breakdown";
    const heading = document.createElement("h4");
    heading.textContent = section.title;
    column.append(heading, renderBreakdown(section.items, period.total));
    grids.appendChild(column);
  });

  card.append(head, grids);
  return card;
}

function createPeriodStat(label, value) {
  const item = document.createElement("article");
  item.className = "budget-period-stat";

  const title = document.createElement("span");
  title.textContent = label;

  const amount = document.createElement("strong");
  amount.textContent = formatBudgetMoney(value);

  item.append(title, amount);
  return item;
}

function renderPeriods() {
  if (!periodList) return;
  periodButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.budgetPeriod === periodMode);
  });

  const periods = buildPeriodInsights(periodMode);
  if (!periods.some((period) => period.key === selectedPeriodKey)) {
    selectedPeriodKey = periods[0]?.key || "";
  }
  const visiblePeriods = periods.slice(0, getPeriodDisplayLimit(periodMode));
  const maxTotal = Math.max(...visiblePeriods.map((period) => period.total), 0);
  const selectedPeriod = periods.find((period) => period.key === selectedPeriodKey) || null;

  const stats = document.createElement("div");
  stats.className = "budget-period-stats";
  const visibleTotal = visiblePeriods.reduce((sum, period) => sum + period.total, 0);
  stats.append(
    createPeriodStat("Średnio dziennie w tym miesiącu", getCurrentMonthAverage()),
    createPeriodStat("Średnio dziennie w widoku", visibleTotal / Math.max(1, getRangeDayCount(visiblePeriods, periodMode))),
    createPeriodStat("Średnio dziennie w wybranym", selectedPeriod ? selectedPeriod.total / Math.max(1, getPeriodDayCount(selectedPeriod, periodMode)) : 0),
  );

  const chart = document.createElement("div");
  chart.className = "budget-period-chart";
  chart.style.setProperty("--budget-period-bars", String(Math.max(1, visiblePeriods.length)));
  chart.setAttribute("role", "list");
  chart.setAttribute("aria-label", "Wydatki według okresu");

  visiblePeriods.forEach((period) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "budget-period-bar-button";
    if (period.key === selectedPeriodKey) button.classList.add("is-active");
    button.dataset.periodKey = period.key;
    button.title = getPeriodSummary(period);
    button.setAttribute("role", "listitem");
    button.setAttribute("aria-label", getPeriodSummary(period));

    const amount = document.createElement("strong");
    amount.textContent = formatBudgetMoney(period.total);

    const track = document.createElement("span");
    track.className = "budget-period-bar-track";
    const fill = document.createElement("span");
    fill.style.height = `${Math.max(3, Math.min(100, maxTotal > 0 ? (period.total / maxTotal) * 100 : 0))}%`;
    track.appendChild(fill);

    const label = document.createElement("span");
    label.className = "budget-period-bar-label";
    label.textContent = formatPeriodChartLabel(period.key, periodMode);

    button.append(amount, track, label);
    chart.appendChild(button);
  });

  periodList.replaceChildren(stats, chart, ...(selectedPeriod ? [renderPeriodCard(selectedPeriod)] : []));
  if (periodEmpty) periodEmpty.hidden = periods.length > 0;
  if (periodMeta) {
    const total = periods.reduce((sum, period) => sum + period.total, 0);
    periodMeta.textContent = periods.length
      ? `${periods.length} okresów | ${formatBudgetMoney(total)} wydatków | pokazuję ostatnie ${visiblePeriods.length}`
      : "Wykres pokaże sumę wydatków dla wybranego zakresu.";
  }
}

function getSelectedTransaction() {
  return budgetData.transactions.find((transaction) => transaction.id === selectedId) || null;
}

async function renderClassificationExplanation(transaction) {
  const target = document.getElementById("budget-classification-explanation");
  if (!target || !transaction) return;
  const fallback = transaction.classification || {};
  target.textContent = `Źródła: miejsce ${fallback.merchantSource || "-"}, kategoria ${fallback.categorySource || "-"}, rodzaj ${fallback.transactionKindSource || "-"}.`;
  try {
    const payload = await fetchBudgetClassification(transaction.id);
    if (transaction.id !== selectedId) return;
    const fields = payload.classification?.fields || [];
    target.textContent = fields.map((field) => {
      const rule = field.rule ? ` (reguła #${field.rule.id}: ${field.rule.name})` : "";
      return `${field.field}: ${field.source || "brak"}${rule}`;
    }).join(" · ");
  } catch {
    // The compatibility payload still provides source-level provenance.
  }
}

function renderEditor() {
  const transaction = getSelectedTransaction();
  if (!transaction) {
    if (editorEmpty) editorEmpty.hidden = false;
    if (editorForm) editorForm.hidden = true;
    return;
  }

  if (editorEmpty) editorEmpty.hidden = true;
  if (editorForm) {
    editorForm.hidden = false;
    editorForm.elements.merchant.value = transaction.merchant;
    editorForm.elements.userCategory.value = transaction.userCategory;
    editorForm.elements.merchantType.value = transaction.merchantType;
    editorForm.elements.transactionKind.value = transaction.transactionKind || "other";
    editorForm.elements.note.value = transaction.note;
  }

  setText("budget-editor-date", formatBudgetDate(transaction.date) || "-");
  setText("budget-editor-title", getBudgetTransactionPlace(transaction) || "Operacja");
  setText("budget-editor-original", transaction.description || transaction.category || "-");
  setText("budget-editor-amount", formatBudgetMoney(transaction.amount));
  renderClassificationExplanation(transaction);
}

function renderReviewItems(items) {
  if (!reviewList) return;
  const labels = {
    unknown_merchant: "Nieznane miejsce",
    missing_category: "Brak kategorii",
    missing_transaction_kind: "Brak rodzaju transakcji",
    rule_conflict: "Konflikt reguł",
    ambiguous_classification: "Niejednoznaczna klasyfikacja",
  };
  reviewList.replaceChildren(...items.map((item) => {
    const card = document.createElement("article");
    card.className = "budget-suggestion";
    card.dataset.transactionId = item.transactionId;
    card.dataset.issueType = item.issueType;
    const title = document.createElement("strong");
    title.textContent = labels[item.issueType] || item.issueType;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${formatBudgetDate(item.date)} · ${formatBudgetMoney(item.amount)}`;
    const ignore = document.createElement("button");
    ignore.type = "button";
    ignore.className = "budget-action budget-action--ghost";
    ignore.dataset.action = "ignore-review";
    ignore.textContent = "Ignoruj";
    card.append(title, meta, ignore);
    return card;
  }));
  setText("budget-review-meta", items.length ? `${items.length} otwartych pozycji` : "Brak otwartych pozycji.");
}

async function loadArchitecturePanel() {
  try {
    const [analytics, review, categories] = await Promise.all([
      fetchBudgetAnalytics("summary", { period: backendPeriod }),
      fetchBudgetReview("open"),
      fetchBudgetCategories(),
    ]);
    const summary = analytics.data || {};
    const period = analytics.period || {};
    setText("budget-backend-period", `${period.period_start || "-"} – ${period.period_end || "-"}`);
    setText("budget-backend-expenses", formatBudgetMoney(summary.expenses));
    setText("budget-backend-income", formatBudgetMoney(summary.totalIncome));
    setText("budget-backend-cashflow", formatBudgetMoney(summary.netCashFlow));
    setText("budget-architecture-meta", period.latest_transaction_date
      ? `Najnowsza transakcja: ${period.latest_transaction_date} · ${period.data_freshness?.status === "stale" ? "dane nieaktualne" : "dane aktualne"}`
      : "Brak transakcji.");
    renderReviewItems(review);
    if (ruleCategory) {
      const previous = ruleCategory.value;
      ruleCategory.replaceChildren(...categories.map((category) => {
        const option = document.createElement("option");
        option.value = String(category.id);
        option.textContent = category.parentId ? `↳ ${category.name}` : category.name;
        return option;
      }));
      if (categories.some((category) => String(category.id) === previous)) ruleCategory.value = previous;
    }
  } catch (err) {
    setText("budget-architecture-meta", err?.message || "Nie udało się wczytać usług klasyfikacji.");
  }
}

async function handleReviewClick(event) {
  const button = event.target.closest('[data-action="ignore-review"]');
  const card = button?.closest("[data-transaction-id]");
  if (!card) return;
  try {
    await updateBudgetReview(card.dataset.transactionId, card.dataset.issueType, "ignored");
    await loadArchitecturePanel();
  } catch (err) {
    setStatus(err?.message || "Nie udało się zaktualizować kolejki.");
  }
}

async function handleRuleSubmit(event) {
  event.preventDefault();
  const categoryId = Number(ruleCategory?.value);
  const kind = document.getElementById("budget-rule-kind")?.value || "";
  const actions = [{ field: "category", valueId: categoryId }];
  if (kind) actions.push({ field: "transaction_kind", value: kind });
  try {
    const payload = await createBudgetRule({
      name: document.getElementById("budget-rule-name")?.value || "",
      priority: 100,
      conditions: [{
        field: "normalized_description",
        operator: "contains",
        value: document.getElementById("budget-rule-description")?.value || "",
      }],
      actions,
      application: document.getElementById("budget-rule-existing")?.checked ? "existing_and_future" : "future_only",
    });
    setText("budget-rule-status", payload.application
      ? `Utworzono. Dopasowania: ${payload.application.matched}, zmienione: ${payload.application.changedTransactions}.`
      : "Utworzono regułę dla przyszłych importów.");
    ruleForm?.reset();
    budgetData = await fetchBudgetServerData();
    renderAll();
    await loadArchitecturePanel();
  } catch (err) {
    setText("budget-rule-status", err?.message || "Nie udało się utworzyć reguły.");
  }
}

function renderSuggestionCard(suggestion) {
  const card = document.createElement("article");
  card.className = "budget-suggestion";
  card.dataset.key = suggestion.key;

  const header = document.createElement("div");
  header.className = "budget-suggestion-header";

  const top = document.createElement("label");
  top.className = "budget-suggestion-check";

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = true;
  checkbox.dataset.field = "selected";

  const title = document.createElement("span");
  title.textContent = suggestion.merchant || suggestion.userCategory || "Propozycja";

  const count = document.createElement("strong");
  count.textContent = `${suggestion.applyCount} do uzupełnienia`;

  top.append(checkbox, title, count);

  const reject = document.createElement("button");
  reject.type = "button";
  reject.className = "budget-action budget-action--ghost";
  reject.dataset.action = "reject-suggestion";
  reject.textContent = "Odrzuć";

  const accept = document.createElement("button");
  accept.type = "button";
  accept.className = "budget-action";
  accept.dataset.action = "accept-suggestion";
  accept.textContent = "Akceptuj";

  const rowActions = document.createElement("div");
  rowActions.className = "budget-suggestion-row-actions";
  rowActions.append(accept, reject);

  header.append(top, rowActions);

  const fields = document.createElement("div");
  fields.className = "budget-suggestion-fields";

  [
    { label: "Miejsce", field: "merchant", value: suggestion.merchant, list: "budget-merchant-options" },
    { label: "Kategoria", field: "userCategory", value: suggestion.userCategory, list: "budget-category-options" },
    { label: "Typ", field: "merchantType", value: suggestion.merchantType, list: "budget-type-options" },
  ].forEach((config) => {
    const label = document.createElement("label");
    label.className = "budget-app-field";
    const labelText = document.createElement("span");
    labelText.textContent = config.label;
    const input = document.createElement("input");
    input.className = "budget-app-input";
    input.dataset.field = config.field;
    input.value = config.value || "";
    if (config.list) input.setAttribute("list", config.list);
    label.append(labelText, input);
    fields.appendChild(label);
  });

  const samples = document.createElement("div");
  samples.className = "budget-suggestion-samples";
  const source = suggestion.source === "learned" ? "nauczone z Twojej edycji" : "powtarzalny opis";
  samples.textContent = `${source} | ${suggestion.count} podobnych | ${suggestion.sampleDescriptions.join(" / ")}`;

  const transactionActions = document.createElement("div");
  transactionActions.className = "budget-suggestion-transaction-actions";

  const selectTransactions = document.createElement("button");
  selectTransactions.type = "button";
  selectTransactions.className = "budget-action budget-action--ghost";
  selectTransactions.dataset.action = "select-suggestion-transactions";
  selectTransactions.textContent = "Zaznacz transakcje";

  const clearTransactions = document.createElement("button");
  clearTransactions.type = "button";
  clearTransactions.className = "budget-action budget-action--ghost";
  clearTransactions.dataset.action = "clear-suggestion-transactions";
  clearTransactions.textContent = "Odznacz transakcje";

  transactionActions.append(selectTransactions, clearTransactions);

  const transactionList = document.createElement("div");
  transactionList.className = "budget-suggestion-transactions";

  suggestion.transactions.forEach((transaction) => {
    const row = document.createElement("label");
    row.className = `budget-suggestion-transaction ${transaction.canApply ? "" : "is-filled"}`.trim();

    const txCheckbox = document.createElement("input");
    txCheckbox.type = "checkbox";
    txCheckbox.dataset.field = "transaction";
    txCheckbox.dataset.id = transaction.id;
    txCheckbox.checked = transaction.canApply;
    txCheckbox.disabled = !transaction.canApply;

    const body = document.createElement("span");
    body.className = "budget-suggestion-transaction-body";

    const main = document.createElement("span");
    main.className = "budget-suggestion-transaction-main";
    main.textContent = transaction.description || transaction.merchant || "Operacja";

    const meta = document.createElement("span");
    meta.className = "budget-suggestion-transaction-meta";
    meta.textContent = [
      formatBudgetDate(transaction.date),
      formatBudgetMoney(transaction.amount),
      transaction.userCategory || transaction.category,
      transaction.merchant,
      transaction.merchantType,
    ].filter(Boolean).join(" | ");

    body.append(main, meta);
    row.append(txCheckbox, body);
    transactionList.appendChild(row);
  });

  card.append(header, fields, samples, transactionActions, transactionList);
  return card;
}

function renderSuggestions() {
  if (!suggestionList) return;
  suggestionDrafts = buildBudgetRuleSuggestions(budgetData);
  suggestionList.replaceChildren(...suggestionDrafts.map(renderSuggestionCard));
  if (suggestionEmpty) suggestionEmpty.hidden = suggestionDrafts.length > 0;
  if (suggestionMeta) {
    const total = suggestionDrafts.reduce((sum, suggestion) => sum + suggestion.applyCount, 0);
    suggestionMeta.textContent = suggestionDrafts.length
      ? `${suggestionDrafts.length} propozycji, ${total} pustych pól do uzupełnienia. Rozwiń listę pod propozycją i odznacz pojedyncze transakcje, jeśli nie pasują.`
      : "Program niczego nie zmieni bez zatwierdzenia.";
  }
}

function renderAll() {
  budgetData = normalizeBudgetData(budgetData);
  syncDictionaries();
  renderSummary();
  renderPeriods();
  renderTransactions();
  renderEditor();
  renderSuggestions();
}

function mergeLabel(list, value) {
  return uniqueLabels([...list, value]);
}

function removeLabel(list, value) {
  const key = normalizeBudgetText(value);
  return list.filter((entry) => normalizeBudgetText(entry) !== key);
}

function addCategory() {
  const value = String(newCategoryInput?.value || "").trim();
  if (!value) return;
  budgetData = normalizeBudgetData({
    ...budgetData,
    settings: {
      ...budgetData.settings,
      userCategories: mergeLabel(budgetData.settings.userCategories, value),
    },
  });
  newCategoryInput.value = "";
  saveBudgetSettings();
  renderAll();
}

function addType() {
  const value = String(newTypeInput?.value || "").trim();
  if (!value) return;
  budgetData = normalizeBudgetData({
    ...budgetData,
    settings: {
      ...budgetData.settings,
      merchantTypes: mergeLabel(budgetData.settings.merchantTypes, value),
    },
  });
  newTypeInput.value = "";
  saveBudgetSettings();
  renderAll();
}

function removeDictionaryItem(kind, value) {
  if (!value) return;
  budgetData = normalizeBudgetData({
    ...budgetData,
    settings: {
      ...budgetData.settings,
      userCategories: kind === "category"
        ? removeLabel(budgetData.settings.userCategories, value)
        : budgetData.settings.userCategories,
      merchantTypes: kind === "type"
        ? removeLabel(budgetData.settings.merchantTypes, value)
        : budgetData.settings.merchantTypes,
    },
  });
  saveBudgetSettings();
  renderAll();
}

function handleDictionaryClick(event) {
  const action = event.target.closest("[data-action]");
  if (!action || action.dataset.action !== "remove-dictionary-item") return;
  removeDictionaryItem(action.dataset.kind, action.dataset.value);
}

async function handleImport(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  try {
    setStatus("Wysyłam CSV do serwera...");
    budgetData = await importBudgetCsvToServer(file);
    localStorage.removeItem(STORAGE_KEY);
    selectedId = budgetData.transactions[0]?.id || "";
    renderAll();
    await loadArchitecturePanel();
  } catch (err) {
    setStatus(err?.message || "Nie udało się wczytać CSV.");
  } finally {
    event.target.value = "";
  }
}

async function handleReset() {
  localStorage.removeItem(STORAGE_KEY);
  try {
    budgetData = await fetchBudgetServerData();
  } catch (err) {
    setStatus(err?.message || "Nie udało się odświeżyć danych.");
    return;
  }
  selectedId = budgetData.transactions[0]?.id || "";
  setStatus("Odświeżono dane z serwera.");
  renderAll();
  await loadArchitecturePanel();
}

function handleTableClick(event) {
  const row = event.target.closest(".budget-page-row");
  if (!row) return;
  selectedId = row.dataset.id || "";
  renderTransactions();
  renderEditor();
}

async function handleEditorSubmit(event) {
  event.preventDefault();
  const transaction = getSelectedTransaction();
  if (!transaction || !editorForm) return;

  const updates = {
    merchant: editorForm.elements.merchant.value,
    userCategory: editorForm.elements.userCategory.value,
    merchantType: editorForm.elements.merchantType.value,
    transactionKind: editorForm.elements.transactionKind.value,
    note: editorForm.elements.note.value,
  };

  budgetData = updateBudgetTransaction(budgetData, transaction.id, updates);
  budgetData = normalizeBudgetData({
    ...budgetData,
    settings: {
      ...budgetData.settings,
      userCategories: mergeLabel(budgetData.settings.userCategories, updates.userCategory),
      merchantTypes: mergeLabel(budgetData.settings.merchantTypes, updates.merchantType),
    },
  });
  try {
    await classifyBudgetTransaction(transaction.id, {
      merchant: updates.merchant,
      category: updates.userCategory,
      merchantType: updates.merchantType,
      transactionKind: updates.transactionKind,
      note: updates.note,
    });
    await saveBudgetSettings();
    budgetData = await fetchBudgetServerData();
    setStatus("Zapisano ręczną klasyfikację.");
    renderAll();
    await loadArchitecturePanel();
  } catch (err) {
    setStatus(err?.message || "Nie udało się zapisać klasyfikacji.");
  }
}

function handleEditorClear() {
  const transaction = getSelectedTransaction();
  if (!transaction) return;
  budgetData = updateBudgetTransaction(budgetData, transaction.id, {
    merchant: "",
    userCategory: "",
    merchantType: "",
    note: "",
  });
  saveBudgetAnnotations([transaction.id]);
  renderAll();
}

function readSuggestionCards() {
  if (!suggestionList) return [];
  return Array.from(suggestionList.querySelectorAll(".budget-suggestion")).map((card) => {
    const base = suggestionDrafts.find((suggestion) => suggestion.key === card.dataset.key);
    const transactionIds = Array.from(card.querySelectorAll('[data-field="transaction"]'))
      .filter((input) => input.checked && !input.disabled)
      .map((input) => input.dataset.id)
      .filter(Boolean);
    return {
      ...base,
      selected: card.querySelector('[data-field="selected"]')?.checked === true,
      merchant: card.querySelector('[data-field="merchant"]')?.value.trim() || "",
      userCategory: card.querySelector('[data-field="userCategory"]')?.value.trim() || "",
      merchantType: card.querySelector('[data-field="merchantType"]')?.value.trim() || "",
      transactionIds,
      applyCount: transactionIds.length,
    };
  }).filter((suggestion) => suggestion?.key);
}

function readSuggestionCard(card) {
  if (!card) return null;
  const base = suggestionDrafts.find((suggestion) => suggestion.key === card.dataset.key);
  if (!base) return null;
  const transactionIds = Array.from(card.querySelectorAll('[data-field="transaction"]'))
    .filter((input) => input.checked && !input.disabled)
    .map((input) => input.dataset.id)
    .filter(Boolean);
  return {
    ...base,
    selected: true,
    merchant: card.querySelector('[data-field="merchant"]')?.value.trim() || "",
    userCategory: card.querySelector('[data-field="userCategory"]')?.value.trim() || "",
    merchantType: card.querySelector('[data-field="merchantType"]')?.value.trim() || "",
    transactionIds,
    applyCount: transactionIds.length,
  };
}

function applySelectedSuggestions() {
  const selected = readSuggestionCards().filter((suggestion) => suggestion.selected && suggestion.applyCount > 0);
  if (!selected.length) {
    setStatus("Nie zaznaczono żadnej propozycji.");
    return;
  }

  budgetData = applyBudgetRuleSuggestions(budgetData, selected);
  saveBudgetAnnotations(selected.flatMap((suggestion) => suggestion.transactionIds || []));
  renderAll();
  const applied = selected.reduce((sum, suggestion) => sum + suggestion.applyCount, 0);
  setStatus(`Zastosowano propozycje dla ${applied} operacji. Ręcznie uzupełnione pola zostały nietknięte.`);
}

function acceptSuggestion(card) {
  const suggestion = readSuggestionCard(card);
  if (!suggestion || suggestion.applyCount <= 0) {
    setStatus("Ta propozycja nie ma zaznaczonych transakcji do zmiany.");
    return;
  }

  budgetData = applyBudgetRuleSuggestions(budgetData, [suggestion]);
  saveBudgetAnnotations(suggestion.transactionIds || []);
  renderAll();
  setStatus(`Zaakceptowano propozycję "${suggestion.merchant || suggestion.userCategory || "bez nazwy"}" dla ${suggestion.applyCount} operacji.`);
}

function rejectSuggestion(key) {
  if (!key) return;
  budgetData = normalizeBudgetData({
    ...budgetData,
    settings: {
      ...budgetData.settings,
      rejectedSuggestionKeys: uniqueLabels([
        ...budgetData.settings.rejectedSuggestionKeys,
        key,
      ]),
    },
  });
  saveBudgetSettings();
  renderAll();
  setStatus("Odrzucono propozycję. Nie będzie pokazywana ponownie dla tego zestawu danych.");
}

function setSuggestionCardsChecked(checked) {
  if (!suggestionList) return;
  suggestionList.querySelectorAll('.budget-suggestion [data-field="selected"]').forEach((input) => {
    input.checked = checked;
  });
}

function setSuggestionTransactionsChecked(card, checked) {
  if (!card) return;
  card.querySelectorAll('[data-field="transaction"]').forEach((input) => {
    if (!input.disabled) input.checked = checked;
  });
}

function handleSuggestionClick(event) {
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const card = action.closest(".budget-suggestion");
  if (action.dataset.action === "reject-suggestion") {
    rejectSuggestion(card?.dataset.key || "");
    return;
  }
  if (action.dataset.action === "accept-suggestion") {
    acceptSuggestion(card);
    return;
  }
  if (action.dataset.action === "select-suggestion-transactions") {
    setSuggestionTransactionsChecked(card, true);
    return;
  }
  if (action.dataset.action === "clear-suggestion-transactions") {
    setSuggestionTransactionsChecked(card, false);
  }
}

function handlePeriodChartPick(event) {
  const button = event.target.closest("[data-period-key]");
  if (!button) return;
  selectedPeriodKey = button.dataset.periodKey || "";
  renderPeriods();
}

async function initBudgetPage() {
  defaultBudgetData = await migrateStoredBudgetData(await loadDefaultBudgetData());
  budgetData = defaultBudgetData;
  selectedId = budgetData.transactions[0]?.id || "";
  setStatus(budgetData.transactions.length ? "Gotowe do opisywania operacji." : "Zaimportuj CSV do lokalnej bazy finansów.");
  renderAll();
  await loadArchitecturePanel();

  fileInput?.addEventListener("change", handleImport);
  resetBtn?.addEventListener("click", handleReset);
  tableEl?.addEventListener("click", handleTableClick);
  editorForm?.addEventListener("submit", handleEditorSubmit);
  editorClearBtn?.addEventListener("click", handleEditorClear);
  addCategoryBtn?.addEventListener("click", addCategory);
  addTypeBtn?.addEventListener("click", addType);
  categoryDictionary?.addEventListener("click", handleDictionaryClick);
  typeDictionary?.addEventListener("click", handleDictionaryClick);
  refreshSuggestionsBtn?.addEventListener("click", renderSuggestions);
  applySuggestionsBtn?.addEventListener("click", applySelectedSuggestions);
  selectAllSuggestionsBtn?.addEventListener("click", () => setSuggestionCardsChecked(true));
  clearAllSuggestionsBtn?.addEventListener("click", () => setSuggestionCardsChecked(false));
  suggestionList?.addEventListener("click", handleSuggestionClick);
  reviewList?.addEventListener("click", handleReviewClick);
  ruleForm?.addEventListener("submit", handleRuleSubmit);
  backendCurrentBtn?.addEventListener("click", async () => {
    backendPeriod = "current_month";
    backendCurrentBtn.classList.add("is-active");
    backendLatestBtn?.classList.remove("is-active");
    await loadArchitecturePanel();
  });
  backendLatestBtn?.addEventListener("click", async () => {
    backendPeriod = "latest_data_month";
    backendLatestBtn.classList.add("is-active");
    backendCurrentBtn?.classList.remove("is-active");
    await loadArchitecturePanel();
  });
  periodList?.addEventListener("click", handlePeriodChartPick);
  periodList?.addEventListener("mouseover", handlePeriodChartPick);
  periodButtons.forEach((button) => {
    button.addEventListener("click", () => {
      periodMode = button.dataset.budgetPeriod || "day";
      selectedPeriodKey = "";
      renderPeriods();
    });
  });
  [searchInput, categoryFilter, typeFilter, onlyUncategorized].forEach((input) => {
    input?.addEventListener("input", renderTransactions);
    input?.addEventListener("change", renderTransactions);
  });
  window.addEventListener("resize", renderPeriods);
}

initBudgetPage();
