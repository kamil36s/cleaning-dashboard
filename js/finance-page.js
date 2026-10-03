import {
  fetchBudgetCategories,
  fetchBudgetImportHistory,
  fetchBudgetMerchants,
  fetchBudgetMerchantTypes,
  fetchBudgetReviewGroups,
  fetchBudgetReviewGroupTransactions,
  fetchBudgetRules,
  fetchBudgetTransactions,
  fetchBudgetAnalytics,
  fetchFinanceOverview,
  fetchFinanceResource,
  importBudgetCsvToServer,
  mutateFinanceResource,
  createBudgetMerchant,
  previewBudgetReviewGroup,
  applyBudgetReviewGroup,
  undoLatestBudgetReviewGroup,
  updateBudgetRule,
  deleteBudgetRule,
  previewBudgetRule,
  applyBudgetRule,
  previewBudgetImportRollback,
  rollbackBudgetImport,
  importFinanceReceipt,
  fetchFinanceReceipts,
  fetchFinanceReceipt,
  fetchFinanceReceiptSources,
  fetchReceiptProcessingHealth,
  reprocessFinanceReceipt,
  deleteFinanceReceipt,
  reprocessFinanceReceiptsNeedingOcr,
  updateFinanceReceiptMetadata,
  applyFinanceReceiptParseReview,
  matchFinanceReceipt,
  fetchReceiptItemReviewGroups,
  previewReceiptItemGroup,
  applyReceiptItemGroup,
  undoLatestReceiptItemGroup,
  fetchReceiptProductCategories,
  fetchReceiptProduct,
} from "./budget-api.js";
import { receiptMatchLabel, receiptProcessingExplanation, receiptProcessingLabel, receiptTotalLabel } from "./finance-receipt-ui.js";
import {
  chooseDefaultFinanceMonth,
  financePeriodOptions,
  onboardingVisibility,
  polishMonthLabel,
  hierarchicalCategoryOptions,
  reviewScopeLabel,
  reviewPreviewLines,
} from "./finance-ui.js";
import { createFinanceGuidedDialog } from "./finance-guided-dialog.js";
import { financeDateLabel, financeDateToIso } from "./finance-date.js";
import { financeImportAgeLabel, scheduleFinanceImportReminders } from "./finance-import-reminder.js";

const money = (value, currency = "PLN") => new Intl.NumberFormat("pl-PL", {
  style: "currency", currency, minimumFractionDigits: 2,
}).format(Number(value || 0));
const dateLabel = financeDateLabel;
const importDateTime = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "brak importu"
    : new Intl.DateTimeFormat("pl-PL", { dateStyle: "short", timeStyle: "short" }).format(date);
};
function setImportAge(targetId, account) {
  const target = document.getElementById(targetId);
  target.dataset.financeImportAge = account?.lastImportedAt || "";
  target.title = account?.lastImportedAt ? `Ostatni import: ${importDateTime(account.lastImportedAt)}` : "Brak importu";
  target.textContent = account?.lastImportedAt
    ? `Aktualizacja: ${financeImportAgeLabel(account.lastImportedAt)}` : "Brak importu";
}

function refreshImportAges() {
  document.querySelectorAll("[data-finance-import-age]").forEach((target) => {
    target.textContent = target.dataset.financeImportAge
      ? `Aktualizacja: ${financeImportAgeLabel(target.dataset.financeImportAge)}` : "Brak importu";
  });
  document.querySelectorAll(".finance-import-item").forEach((item) => {
    const importedAt = Date.parse(item.dataset.importedAt || "");
    item.classList.toggle("is-stale", !Number.isFinite(importedAt)
      || Date.now() - importedAt >= 7 * 24 * 60 * 60 * 1000);
  });
}
const $ = (id) => document.getElementById(id);
const node = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};
const empty = (text) => node("p", "finance-empty", text);
const emptyState = (title, detail, action, target) => {
  const box = node("div", "finance-empty-state");
  box.append(node("strong", "", title), node("p", "", detail));
  if (action && target) {
    const button = node("button", "finance-button", action);
    button.dataset.openView = target;
    box.append(button);
  }
  return box;
};

const currentMonth = new Date().toISOString().slice(0, 7);

const state = {
  view: "overview",
  month: currentMonth,
  transactionPage: 1,
  transactionHasMore: false,
  transactionOptionsLoaded: false,
  reviewScope: "selected_month",
  receiptProductCategories: [],
};

const viewTitles = {
  overview: ["Przegląd", "Sytuacja finansowa"], transactions: ["Historia", "Transakcje"],
  review: ["Klasyfikacja", "Przegląd danych"], receipts: ["Dowody zakupowe", "Paragony i produkty"], budgets: ["Plan", "Budżety"],
  recurring: ["Planowanie", "Cykliczne płatności"], goals: ["Oszczędzanie", "Cele finansowe"],
  analysis: ["Analiza", "Analiza finansowa"],
  reports: ["Historia", "Raport miesięczny"], settings: ["Konfiguracja", "Ustawienia"],
};

function setStatus(message, error = false) {
  const status = $("finance-status");
  status.textContent = message;
  status.classList.toggle("is-error", error);
  status.hidden = !message;
}

function progressRow(label, value, detail, percent) {
  const row = node("article", "finance-progress-row");
  const head = node("div");
  head.append(node("strong", "", label), node("span", "", value));
  const track = node("div", "finance-progress-track");
  const fill = node("i");
  fill.style.width = `${Math.max(0, Math.min(100, Number(percent || 0)))}%`;
  track.append(fill);
  row.append(head, track, node("small", "", detail));
  return row;
}

const chartColors = ["#59b8e8", "#ffad5b", "#b18bff", "#f2779d", "#73d39a", "#f2d46b", "#55c6be", "#e38f6c"];

function renderBreakdown(targetId, items, emptyLabel) {
  const target = $(targetId);
  const total = (items || []).reduce((sum, item) => sum + Number(item.amount || 0), 0);
  if (!total) return target.replaceChildren(node("small", "finance-breakdown-empty", emptyLabel));
  const displayed = items.length > 8
    ? [...items.slice(0, 7), { name: "Pozostałe", amount: items.slice(7).reduce((sum, item) => sum + item.amount, 0) }]
    : items;
  let boundary = 0;
  const segments = displayed.map((item, index) => {
    const start = boundary;
    boundary += item.amount / total * 100;
    return `${chartColors[index]} ${start}% ${boundary}%`;
  });
  const pie = node("div", "finance-breakdown-pie");
  pie.style.background = `conic-gradient(${segments.join(", ")})`;
  pie.setAttribute("role", "img");
  pie.setAttribute("aria-label", `Podział kwoty ${money(total)}`);
  const legend = node("div", "finance-breakdown-legend");
  displayed.forEach((item, index) => {
    const line = node("div", "finance-breakdown-item");
    const dot = node("i"); dot.style.background = chartColors[index];
    const label = node("span", "", item.name); label.title = item.name;
    const share = Number(item.amount) / total * 100;
    const values = node("div", "finance-breakdown-values");
    values.append(node("b", "", money(item.amount)),
      node("small", "", share > 0 && share < 0.1 ? "<0,1%" : `${new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(share)}%`));
    line.append(dot, label, values);
    legend.append(line);
  });
  target.replaceChildren(pie, legend);
}

function budgetRow(item, detail) {
  const row = progressRow(item.categoryId === null ? "Wydano z budżetu" : item.category,
    `${money(item.spent)} / ${money(item.limit)}`, detail, item.usedPercent);
  if (item.categoryId === null && item.freePerDay != null) {
    const summary = node("div", "finance-budget-metrics");
    const metric = (label, value, context, primary = false) => {
      const box = node("div", `finance-budget-metric${primary ? " is-primary" : ""}`);
      box.append(node("span", "", label), node("strong", "", money(value)));
      if (context) box.append(node("small", "", context));
      return box;
    };
    summary.append(
      metric("Do wydania", item.freeAfterScheduled, "po planach", true),
      metric("Na dzień", item.freePerDay, `${item.remainingDays} dni · po planach`, true),
      metric("Zaplanowane", item.plannedRemaining),
      metric(item.source === "monthly_inflows" ? "Wpływy / dzień" : "Budżet / dzień", item.dailyLimit),
    );
    row.append(summary);
  }
  return row;
}

function goalPeriod(title, subtitle, deposits, withdrawals, depositRate, withdrawalRate) {
  const section = node("section", "finance-goal-period");
  const heading = node("header");
  heading.append(node("strong", "", title), node("small", "", subtitle));
  const metrics = node("div", "finance-goal-period-metrics");
  const metric = (label, amount, rate) => {
    const item = node("div");
    item.append(node("span", "", label), node("strong", "", amount == null ? "—" : money(amount)),
      node("small", "", rate == null ? "brak danych o wpływach" : `${rate}% wpływów`));
    return item;
  };
  metrics.append(metric("Wpłacono", deposits, depositRate), metric("Wypłacono", withdrawals, withdrawalRate));
  section.append(heading, metrics);
  return section;
}

function renderUpcoming(items, target = $("finance-upcoming")) {
  if (!items?.length) return target.replaceChildren(empty("Brak potwierdzonych zdarzeń w tym okresie."));
  target.replaceChildren(...items.map((item) => {
    const row = node("article", "finance-list-row");
    const copy = node("div");
    copy.append(node("strong", "", item.name), node("small", "", `${dateLabel(item.date)} · ${item.kind}`));
    row.append(copy, node("b", item.kind === "salary" || item.kind === "income" ? "is-positive" : "", `${item.kind === "salary" || item.kind === "income" ? "+" : "−"}${money(item.amount)}`));
    return row;
  }));
}

function renderOverview(data) {
  scheduleFinanceImportReminders(data.accountImports);
  $("finance-import-freshness").replaceChildren(...(data.accountImports || []).map((account) => {
    const ageDays = account.lastImportedAt
      ? Math.floor((Date.now() - Date.parse(account.lastImportedAt)) / 86400000) : Infinity;
    const item = node("div", `finance-import-item${ageDays >= 7 ? " is-stale" : ""}`);
    item.dataset.importedAt = account.lastImportedAt || "";
    item.append(node("strong", "", account.role === "main" ? "Konto główne" : account.name),
      node("span", "", `Import: ${importDateTime(account.lastImportedAt)}`),
      node("small", "", account.latestTransactionDate ? `Operacje do ${dateLabel(account.latestTransactionDate)}` : "Brak operacji"));
    return item;
  }));
  const safe = data.safeToSpend;
  setImportAge("finance-main-updated", data.accountImports?.find((account) => account.role === "main"));
  $("finance-liquid").textContent = data.availableBalance == null ? "—" : money(data.availableBalance);
  $("finance-safe").textContent = data.freeBalance == null ? "—" : money(data.freeBalance);
  $("finance-safe-daily").textContent = data.mainAccountName
    ? `${data.mainAccountName} · saldo z importu · po płatnościach do ${dateLabel(safe.horizonDate)}`
    : "Wybierz konto główne w Ustawieniach";
  const safeSetup = $("finance-safe-setup");
  safeSetup.hidden = safe.configured;
  if (!safe.configured) {
    safeSetup.replaceChildren(
      node("strong", "", "Skonfiguruj Safe-to-spend"),
      node("p", "", "Wskaż konto główne. Dodatkowy bufor jest opcjonalny; zaplanowane płatności odejmujemy automatycznie."),
      ...safe.setup.map((item) => node("span", item.complete ? "is-complete" : "", `${item.complete ? "✓" : "○"} ${item.label}`)),
    );
    const button = node("button", "finance-button", "Przejdź do konfiguracji");
    button.dataset.openView = "settings";
    safeSetup.append(button);
  }
  $("finance-expenses").textContent = money(data.expenses);
  $("finance-income").textContent = money(data.income);
  $("finance-net").textContent = money(data.remainingFromIncome);
  renderBreakdown("finance-expense-breakdown", data.expenseCategories, "Brak opłaconych wydatków");
  renderBreakdown("finance-income-breakdown", data.incomeSources, "Brak wpływów");
  const emergencyGoal = data.goals?.find((goal) => goal.kind === "emergency_fund" && goal.primary)
    || data.goals?.find((goal) => goal.kind === "emergency_fund");
  setImportAge("finance-savings-updated", data.accountImports?.find((account) => account.id === emergencyGoal?.linkedAccountId)
    || data.accountImports?.find((account) => account.role === "savings"));
  $("finance-savings").textContent = emergencyGoal ? money(emergencyGoal.allocated) : "—";
  $("finance-savings-rate").textContent = emergencyGoal
    ? `${emergencyGoal.progressPercent}% · cel ${money(emergencyGoal.target)}`
    : "Dodaj poduszkę bezpieczeństwa w Celach";
  const savingsProgress = $("finance-savings-progress");
  const percent = Math.max(0, Math.min(100, Number(emergencyGoal?.progressPercent || 0)));
  savingsProgress.parentElement.hidden = !emergencyGoal;
  savingsProgress.style.width = `${percent}%`;
  savingsProgress.parentElement.setAttribute("aria-valuenow", String(percent));
  const freshness = data.freshness;
  $("finance-freshness").textContent = freshness.latestTransactionDate
    ? `Dane do ${dateLabel(freshness.latestTransactionDate)} · ${freshness.status}` : "Brak transakcji";
  $("finance-period-context").textContent = freshness.latestTransactionDate
    ? `Wybrany okres: ${polishMonthLabel(state.month)}${state.month !== currentMonth ? " · widok historyczny" : ""} · dane do ${dateLabel(freshness.latestTransactionDate)}`
    : `Wybrany okres: ${polishMonthLabel(state.month)} · brak danych`;
  renderUpcoming(data.upcoming);
  $("finance-budget-preview").replaceChildren(...(data.budgets?.length
    ? data.budgets.slice(0, 4).map((item) => budgetRow(item, `${item.source === "monthly_inflows" ? `${item.sourceDate ? `Wypłata z ${polishMonthLabel(item.sourceDate.slice(0, 7))} + ` : ""}wpływy miesiąca · ` : ""}wykorzystano ${item.usedPercent}%`))
    : [emptyState("Nie masz jeszcze limitów", "Budżet określa maksymalne wydatki w miesiącu.", "Ustaw pierwszy budżet", "budgets")]));
  $("finance-goal-preview").replaceChildren(...(data.goals?.length
    ? data.goals.slice(0, 3).map((goal) => progressRow(goal.name, `${goal.progressPercent}%`, `Pozostało ${money(goal.remaining)}${goal.estimatedCompletionDate ? ` · ${dateLabel(goal.estimatedCompletionDate)}` : ""}`, goal.progressPercent))
    : [emptyState("Nie masz jeszcze celu", "Cel śledzi wyłącznie jawnie przydzielone środki.", "Dodaj cel", "goals")]));
  $("finance-goal-month").replaceChildren(...(data.goals?.length ? [
    goalPeriod("Wybrany miesiąc", polishMonthLabel(state.month), data.goalDeposits,
      data.goalWithdrawals, data.goalDepositRate, data.goalWithdrawalRate),
  ] : []));
  const maxTrend = Math.max(1, ...(data.trends || []).map((item) => Math.max(item.expenses, item.income)));
  $("finance-trends").replaceChildren(...(data.trends?.length ? data.trends.map((item) => {
    const column = node("article");
    const bars = node("div", "finance-trend-bars");
    const expense = node("i", "is-expense"); expense.style.height = `${Math.max(3, item.expenses / maxTrend * 100)}%`;
    const income = node("i", "is-income"); income.style.height = `${Math.max(3, item.income / maxTrend * 100)}%`;
    bars.append(expense, income); column.append(bars, node("small", "", item.month)); return column;
  }) : [empty("Brak historii.")]));
  $("finance-insights").replaceChildren(...(data.insights?.length ? data.insights.map((item) => {
    const card = node("article", `finance-insight is-${item.severity}`);
    card.append(node("strong", "", item.title), node("p", "", item.reason), node("small", "", item.period));
    if (item.target) { const button = node("button", "", "Przejdź"); button.dataset.openView = item.target; card.append(button); }
    return card;
  }) : [empty("Brak deterministycznych alertów.")]));
}

async function loadOnboarding() {
  const data = await fetchFinanceResource("onboarding");
  const dismissed = localStorage.getItem("finance-onboarding-dismissed-v1") === "1";
  const visibility = onboardingVisibility(dismissed, data.completed, data.total);
  const panel = $("finance-onboarding");
  panel.hidden = visibility.hidden;
  $("finance-onboarding-items").replaceChildren(...data.items.map((item, index) => {
    const button = node("button", `finance-onboarding-item${item.complete ? " is-complete" : ""}`);
    button.type = "button";
    button.dataset.openView = item.target;
    button.append(node("span", "", item.complete ? "✓" : String(index + 1)), node("strong", "", item.title), node("small", "", item.why));
    return button;
  }));
  const guided = node("button", "finance-onboarding-item");
  guided.type = "button";
  guided.dataset.openView = "review";
  guided.append(node("span", "", "?"), node("strong", "", "Nie znasz kategorii?"), node("small", "", "Kliknij „Pomóż mi ustalić” w Przeglądzie. System zada kilka prostych pytań."));
  $("finance-onboarding-items").append(guided);
}

async function loadOverview() {
  const referenceDate = state.month === currentMonth ? new Date().toISOString().slice(0, 10) : `${state.month}-17`;
  const [data, quality] = await Promise.all([
    fetchFinanceOverview({ referenceDate }),
    fetchFinanceResource("data-quality", { month: state.month }),
    loadOnboarding(),
  ]);
  renderOverview(data);
  const review = quality.reviewModel.allHistory;
  $("finance-review-count").textContent = review.groups ? String(review.groups) : "";
  $("finance-review-count").title = `${review.groups} grup w całej historii (${review.transactions} transakcji)`;
  const receipts = quality.receipts || {};
  $("finance-receipt-count").textContent = receipts.needsMatch || receipts.unknownProducts ? String((receipts.needsMatch || 0) + (receipts.unknownProducts || 0)) : "";
}

async function loadTransactions() {
  if (!state.transactionOptionsLoaded) {
    const [accounts, categories, merchants, types] = await Promise.all([fetchFinanceResource("accounts"), fetchBudgetCategories(), fetchBudgetMerchants(), fetchBudgetMerchantTypes()]);
    const fill = (id, label, items, text) => { const select = $(id); select.replaceChildren(new Option(label, ""), ...items.map((item) => new Option(text(item), item.id))); };
    fill("finance-tx-account", "Wszystkie konta", accounts, (item) => item.displayLabel);
    fill("finance-tx-category", "Wszystkie kategorie", categories, (item) => item.parentName ? `${item.parentName} / ${item.name}` : item.name);
    fill("finance-tx-merchant", "Wszystkie miejsca", merchants, (item) => item.canonicalName);
    fill("finance-tx-type", "Wszystkie typy miejsc", types, (item) => item.name);
    state.transactionOptionsLoaded = true;
  }
  const filters = {
    page: state.transactionPage, limit: 40, text: $("finance-tx-search").value,
    transactionKind: $("finance-tx-kind").value, dateFrom: financeDateToIso($("finance-tx-from").value),
    dateTo: financeDateToIso($("finance-tx-to").value), sort: $("finance-tx-sort").value,
    accountId: $("finance-tx-account").value, categoryId: $("finance-tx-category").value,
    merchantId: $("finance-tx-merchant").value, merchantTypeId: $("finance-tx-type").value,
    amountMin: $("finance-tx-min").value, amountMax: $("finance-tx-max").value,
  };
  const result = await fetchBudgetTransactions(filters);
  const exportQuery = new URLSearchParams(Object.entries(filters).filter(([key, value]) => key !== "page" && key !== "limit" && value));
  $("finance-tx-export").href = `/api/budget/export/transactions.csv?${exportQuery}`;
  state.transactionHasMore = result.hasMore;
  const table = $("finance-transactions");
  const head = node("div", "finance-table-row is-head");
  ["Data", "Miejsce / opis", "Kategoria", "Rodzaj", "Konto", "Kwota"].forEach((label) => head.append(node("span", "", label)));
  const rows = result.transactions.map((item) => {
    const row = node("details", "finance-table-row");
    const summary = node("summary");
    summary.append(node("span", "", dateLabel(item.date)), node("strong", "", item.merchant || item.description),
      node("span", "", item.category || "Bez kategorii"), node("span", "", item.transactionKind || "—"),
      node("span", "", item.accountDisplay || "Konto"), node("b", item.amount >= 0 ? "is-positive" : "", money(item.amount)));
    const detail = node("p", "finance-transaction-detail", `${item.description} · źródło kategorii: ${item.classification?.categorySource || "brak"}`);
    if (item.receipt) {
      const receipt = node("button", "finance-receipt-badge", "Paragon ✓");
      receipt.type = "button";
      receipt.addEventListener("click", (event) => { event.preventDefault(); openReceiptDetail(item.receipt.id); });
      detail.append(" · ", receipt);
    }
    row.append(summary, detail);
    return row;
  });
  table.replaceChildren(head, ...(rows.length ? rows : [empty("Brak transakcji dla filtrów.")]));
  $("finance-tx-page").textContent = `Strona ${result.page} · ${result.total} operacji`;
  $("finance-tx-prev").disabled = state.transactionPage <= 1;
  $("finance-tx-next").disabled = !result.hasMore;
}

function confirmReviewPreview(preview, labels) {
  const lines = reviewPreviewLines(preview, labels);
  if (preview.rememberMechanism) lines.push(preview.rememberMechanism === "merchant_default"
    ? "Na przyszłość: kategoria domyślna miejsca (bez zbędnej reguły)."
    : "Na przyszłość: ścisła reguła dokładnego opisu.");
  const dialog = $("finance-review-preview");
  if (!dialog?.showModal) return Promise.resolve(globalThis.confirm?.(lines.join("\n")) ?? false);
  $("finance-review-preview-body").replaceChildren(...lines.map((line, index) => node(index ? "p" : "strong", "", line)));
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}

const guidedDialog = createFinanceGuidedDialog({
  document,
  money,
  dateLabel,
  onOpenRecurring: () => openView("recurring"),
  onSubmit: async ({ group, result, mode, scope, month, session }) => {
    if (session.domain === "receipt_parse") {
      for (const decision of result.classification.receiptUpdates || []) {
        await applyFinanceReceiptParseReview(session.input.receipt.id, decision);
      }
      setStatus("Zapisano potwierdzone dane paragonu i ponowiono dopasowanie transakcji.");
      await loadReceipts();
      await openReceiptDetail(session.input.receipt.id, "Zapisano potwierdzone pola i odświeżono checklistę.");
      return { message: "Potwierdzone pola paragonu zostały zapisane." };
    }
    if (session.domain === "receipt_item") {
      const classification = {
        ...result.classification,
        canonicalName: result.classification.canonicalName || result.labels.product || group.rawName,
        remember: mode === "remember",
      };
      const preview = await previewReceiptItemGroup(group.id, classification);
      await applyReceiptItemGroup(group.id, classification);
      setStatus(`Sklasyfikowano ${preview.group.itemCount} pozycji paragonowych.`);
      await loadReceipts();
      if (group.receiptId) {
        await openReceiptDetail(group.receiptId, `Potwierdzono ${preview.group.itemCount} pozycji. Checklista jest aktualna.`);
      }
      return { message: `Potwierdzono ${preview.group.itemCount} ${preview.group.itemCount === 1 ? "pozycję" : "pozycje"} paragonu.` };
    }
    const payload = {
      scope,
      month,
      classification: result.classification,
      remember: mode === "remember",
      origin: "guided_review",
    };
    if (mode === "transaction") payload.targetTransactionId = group.guidedTransaction?.id || group.samples?.at(-1)?.id;
    const applied = await applyBudgetReviewGroup(group.id, { ...payload, confirm: true });
    const memoryText = mode === "remember"
      ? applied.rememberMechanism ? " Zapamiętano tę decyzję na przyszłość." : " Nie udało się utworzyć bezpiecznej reguły na przyszłość."
      : "";
    if (applied.applied === 0 && applied.rememberMechanism) {
      const message = "Bieżąca kategoria była już ustawiona. Zapamiętano ją dla przyszłych pasujących operacji; brakujące miejsce nadal pozostaje do uzupełnienia.";
      setStatus(`${message} Możesz cofnąć utworzoną regułę.`);
      void Promise.all([loadReview(), loadOverview(), state.view === "transactions" ? loadTransactions() : Promise.resolve()])
        .catch((error) => setStatus(error.message || "Zapisano zmianę, ale nie udało się odświeżyć widoku.", true));
      return { message: `${message} Lista odświeża się w tle.` };
    }
    const appliedScope = applied.applied === 1 ? "jednej transakcji" : `${applied.applied} transakcjach`;
    setStatus(`Zapisano klasyfikację w ${appliedScope}.${memoryText} Możesz cofnąć ostatnią zmianę grupową.`);
    if (mode !== "transaction" && !result.unresolvedFields.length) {
      [...document.querySelectorAll("[data-review-group-id]")]
        .find((item) => item.dataset.reviewGroupId === String(group.id))?.remove();
    }
    void Promise.all([loadReview(), loadOverview(), state.view === "transactions" ? loadTransactions() : Promise.resolve()])
      .catch((error) => setStatus(error.message || "Zapisano zmianę, ale nie udało się odświeżyć widoku.", true));
    return {
      message: `Zapisano ${applied.applied} ${applied.applied === 1 ? "transakcję" : "transakcje"}.${memoryText} Lista odświeża się w tle.`,
    };
  },
});

async function loadReview() {
  const quickClean = $("finance-review-quick")?.checked || false;
  const sort = $("finance-review-sort")?.value || "impact";
  const [data, rawCategories, merchants, merchantTypes] = await Promise.all([
    fetchBudgetReviewGroups({ scope: state.reviewScope, month: state.month, sort, quickClean }),
    fetchBudgetCategories(), fetchBudgetMerchants(), fetchBudgetMerchantTypes(),
  ]);
  const categories = hierarchicalCategoryOptions(rawCategories);
  const metrics = data.metrics;
  $("finance-review-count").textContent = metrics.allHistory.groups ? String(metrics.allHistory.groups) : "";
  $("finance-review-count").title = `${metrics.allHistory.groups} grup w całej historii (${metrics.allHistory.transactions} transakcji)`;
  $("finance-quality-chip").textContent = `${metrics.category.coveragePercent}% kategorii wymaganych · ${metrics.merchant.coveragePercent}% miejsc`;
  $("finance-review-progress").textContent = `Cała historia: ${metrics.allHistory.groups} grup · ${metrics.allHistory.transactions} transakcji`;
  $("finance-review-quality").replaceChildren(
    progressRow("Miejsca", `${metrics.merchant.coveragePercent}%`, `${metrics.merchant.recognized} rozpoznanych / ${metrics.merchant.relevant} istotnych`, metrics.merchant.coveragePercent),
    progressRow("Kategorie", `${metrics.category.coveragePercent}%`, `${metrics.category.categorized} sklasyfikowanych / ${metrics.category.required} wymagających kategorii`, metrics.category.coveragePercent),
    progressRow("Rodzaj", `${metrics.transactionKind.coveragePercent}%`, `${metrics.transactionKind.classified} sklasyfikowanych / ${metrics.transactionKind.total} wszystkich`, metrics.transactionKind.coveragePercent),
  );
  document.querySelectorAll("[data-review-scope]").forEach((button) => button.classList.toggle("is-active", button.dataset.reviewScope === state.reviewScope));
  const scopeText = reviewScopeLabel(state.reviewScope, polishMonthLabel(state.month));
  $("finance-review-scope-summary").replaceChildren(
    node("strong", "", scopeText),
    node("span", "", `${data.counts.groups} grup do przejrzenia · ${data.counts.transactions} transakcji`),
    node("span", "", `Szybkie porządki: ${data.quickClean.groups} grup · ${data.quickClean.transactions} transakcji`),
  );
  const issueLabels = { unknown_merchant: "nierozpoznane miejsce", missing_category: "brak wymaganej kategorii", missing_transaction_kind: "brak rodzaju", rule_conflict: "konflikt reguł", ambiguous_category_mapping: "niejednoznaczna stara kategoria" };
  const merchantByName = new Map(merchants.map((item) => [item.canonicalName.toLocaleLowerCase("pl"), item]));
  const categoryByLabel = new Map(categories.map((item) => [item.label.toLocaleLowerCase("pl"), item]));
  const cards = data.groups.map((group) => {
    const card = node("article", "finance-review-group");
    card.dataset.reviewGroupId = group.id;
    const head = node("header");
    const title = node("div");
    title.append(node("span", `finance-confidence is-${group.suggestion.confidence}`, group.suggestion.confidence), node("h3", "", group.displayName),
      node("p", "", `${group.transactionCount} transakcji · ${dateLabel(group.dateFrom)}–${dateLabel(group.dateTo)} · ${money(group.totalAbsoluteAmount)}`));
    head.append(title, node("span", "finance-review-reason", group.unresolvedFields.map((value) => issueLabels[value] || value).join(" · ")));
    const recognized = node("div", "finance-group-recognized");
    recognized.append(node("strong", "", "System rozpoznał"), node("span", "", `Miejsce: ${group.suggestion.merchant || "brak pewnego dopasowania"}`),
      node("span", "", `Sugerowana kategoria: ${group.suggestion.parentCategory ? `${group.suggestion.parentCategory} → ` : ""}${group.suggestion.category || "brak"}`));
    const evidence = node("div", "finance-review-evidence");
    evidence.append(node("strong", "", "Dlaczego"), ...(group.suggestion.evidence.length ? group.suggestion.evidence : ["Za mało spójnej historii do bezpiecznej sugestii."]).map((value) => node("span", "", `✓ ${value}`)));
    const form = node("div", "finance-group-form");
    const merchantInput = node("input"); merchantInput.type = "search"; merchantInput.placeholder = "Szukaj istniejącego miejsca"; merchantInput.value = group.suggestion.merchant || ""; merchantInput.setAttribute("list", `merchant-${group.id}`);
    const merchantList = node("datalist"); merchantList.id = `merchant-${group.id}`; merchants.forEach((item) => merchantList.append(new Option(item.canonicalName)));
    const categoryInput = node("input"); categoryInput.type = "search"; categoryInput.placeholder = "Szukaj kategorii lub podkategorii"; categoryInput.value = categories.find((item) => Number(item.id) === Number(group.suggestion.categoryId))?.label || ""; categoryInput.setAttribute("list", `category-${group.id}`);
    const categoryList = node("datalist"); categoryList.id = `category-${group.id}`; categories.forEach((item) => categoryList.append(new Option(item.label)));
    const kind = node("select");
    [["", "Rodzaj bez zmian"], ["expense", "Wydatek"], ["transfer", "Transfer wewnętrzny / zewnętrzny"], ["refund", "Zwrot"], ["income", "Dochód"], ["salary", "Wynagrodzenie"], ["saving", "Oszczędność"], ["cash", "Gotówka"], ["other", "Inne"]].forEach(([value, label]) => kind.append(new Option(label, value, false, value === (group.suggestion.transactionKind || ""))));
    const consequence = node("p", "finance-group-consequence", `Zmiana wypełni tylko brakujące pola w ${group.reviewTransactionCount} transakcjach. Istniejące klasyfikacje ręczne pozostaną bez zmian.`);
    const guided = node("button", "finance-button finance-guided-start", "Pomóż mi ustalić"); guided.type = "button";
    const apply = node("button", "finance-button", `Zastosuj do ${group.reviewTransactionCount} podobnych`); apply.type = "button";
    const remember = node("button", "finance-button is-quiet", "Zastosuj + zapamiętaj na przyszłość"); remember.type = "button";
    const createMerchant = node("button", "finance-button is-quiet", "Utwórz nowe miejsce"); createMerchant.type = "button";
    const submit = async (rememberFuture) => {
      const selectedMerchant = merchantByName.get(merchantInput.value.trim().toLocaleLowerCase("pl"));
      const selectedCategory = categoryByLabel.get(categoryInput.value.trim().toLocaleLowerCase("pl"));
      if (merchantInput.value.trim() && !selectedMerchant) { setStatus("Wybierz istniejące miejsce albo użyj „Utwórz nowe miejsce”.", true); return; }
      if (categoryInput.value.trim() && !selectedCategory) { setStatus("Wybierz kategorię z hierarchicznej listy.", true); return; }
      const classification = {};
      if (selectedMerchant) classification.merchantId = Number(selectedMerchant.id);
      if (selectedCategory) classification.categoryId = Number(selectedCategory.id);
      if (kind.value) classification.transactionKind = kind.value;
      const payload = { scope: state.reviewScope, month: state.month, classification, remember: rememberFuture };
      const preview = await previewBudgetReviewGroup(group.id, payload);
      const confirmed = await confirmReviewPreview(preview, { merchant: selectedMerchant?.canonicalName, category: selectedCategory?.label, transactionKind: kind.options[kind.selectedIndex]?.text });
      if (!confirmed) return;
      await applyBudgetReviewGroup(group.id, { ...payload, confirm: true });
      setStatus(`Zastosowano klasyfikację do ${preview.transactionCount} transakcji. Możesz cofnąć ostatnią zmianę grupową.`);
      await loadReview();
    };
    apply.addEventListener("click", () => submit(false)); remember.addEventListener("click", () => submit(true));
    guided.addEventListener("click", () => guidedDialog?.open({ group, categories: rawCategories, merchants, merchantTypes, scope: state.reviewScope, month: state.month }));
    createMerchant.addEventListener("click", async () => {
      const name = merchantInput.value.trim();
      if (!name || merchantByName.has(name.toLocaleLowerCase("pl"))) return;
      if (!(globalThis.confirm?.(`Utworzyć nowe kanoniczne miejsce „${name}”?`) ?? true)) return;
      await createBudgetMerchant({ canonicalName: name }); await loadReview();
    });
    form.append(merchantInput, merchantList, categoryInput, categoryList, kind, createMerchant, consequence, apply, remember);
    const details = node("details", "finance-group-details"); const summary = node("summary", "", `Zobacz ${group.transactionCount} transakcji`); const detailRows = node("div");
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.loaded) return;
      details.dataset.loaded = "1"; detailRows.replaceChildren(node("p", "", "Ładowanie transakcji…"));
      try {
        const transactions = await fetchBudgetReviewGroupTransactions(group.id);
        detailRows.replaceChildren(...transactions.map((item) => node("p", "", `${dateLabel(item.date)} · ${money(item.amount, item.currency)} · ${item.merchant || item.description} · ${item.parentCategory ? `${item.parentCategory} → ` : ""}${item.category || "bez kategorii"}`)));
      } catch (error) { delete details.dataset.loaded; detailRows.replaceChildren(node("p", "", error.message || "Nie udało się pobrać transakcji.")); }
    });
    details.append(summary, detailRows);
    card.append(head, recognized, evidence, guided, form, details); return card;
  });
  $("finance-review").replaceChildren(...(cards.length ? cards : [emptyState("Brak grup w tym zakresie", quickClean ? "Wyłącz Szybkie porządki, aby zobaczyć grupy bez silnej sugestii." : "Wszystkie transakcje w tym zakresie mają wystarczającą klasyfikację.")]));
}

async function openProductDetail(productId) {
  const product = await fetchReceiptProduct(productId);
  const body = $("finance-receipt-detail-body");
  $("finance-receipt-detail-title").textContent = product.canonicalName;
  const facts = node("dl", "finance-product-facts");
  [["Marka", product.brand || "—"], ["EAN", product.barcode || "—"], ["Kategoria", product.productCategory || "—"],
    ["Zakupy", String(product.purchaseCount)], ["Ostatni zakup", dateLabel(product.lastPurchase)],
    ["Ostatnia cena", product.lastPrice == null ? "—" : money(product.lastPrice)]].forEach(([label, value]) => {
    facts.append(node("dt", "", label), node("dd", "", value));
  });
  const aliases = node("section", "finance-product-aliases");
  aliases.append(node("h3", "", "Aliasy sprzedawców"), ...(product.retailerAliases.length
    ? product.retailerAliases.map((item) => node("p", "", `${item.retailer_key}: ${item.raw_name}${item.retailer_code ? ` · ${item.retailer_code}` : ""}`))
    : [empty("Brak zapamiętanych aliasów.")]));
  const prices = node("section", "finance-product-prices");
  prices.append(node("h3", "", "Historia cen"), ...(product.priceHistory.length
    ? product.priceHistory.map((item) => node("p", "", `${dateLabel(item.date)} · ${item.retailer || "—"} · ${money(item.effectivePrice)} · ${item.quantity} ${item.unit}`))
    : [empty("Brak historii cen.")]));
  body.replaceChildren(facts, aliases, prices);
}

function renderReceiptHealth(target, health) {
  if (!target) return;
  const ocr = health?.serverOcr || {};
  const phoneOcrReady = Boolean(health?.androidOcrEvidence?.supported);
  const computerOcrReady = Boolean(ocr.available && ocr.polishAvailable);
  const stateText = computerOcrReady
    ? "OCR działa na telefonie i komputerze"
    : phoneOcrReady ? "OCR telefonu działa" : "Brak aktywnego OCR";
  const explanation = computerOcrReady
    ? "Zdjęcia mogą być odczytywane przez Android ML Kit lub lokalny Tesseract."
    : phoneOcrReady
      ? "Nowe skany z Androida są odczytywane przez ML Kit. Tesseract na komputerze jest opcjonalny i obecnie nie jest skonfigurowany."
      : "Dodaj tekstowy PDF albo skonfiguruj OCR na telefonie lub komputerze.";
  const counts = Object.entries(health?.receiptStates || {}).map(([key, value]) => `${key}: ${value}`).join(" · ");
  const capabilities = [
    `Telefon (ML Kit): ${phoneOcrReady ? "gotowy" : "brak"}`,
    `Komputer (Tesseract): ${computerOcrReady ? "gotowy" : "opcjonalny — nieskonfigurowany"}`,
    `Tekst PDF: ${health?.pdfTextExtraction?.available ? "dostępny" : "brak"}`,
    `Magazyn: ${health?.receiptStorage?.available && health?.receiptStorage?.writable ? "OK" : "problem"}`,
  ].join(" · ");
  target.replaceChildren(
    node("strong", phoneOcrReady || computerOcrReady ? "is-positive" : "", stateText),
    node("small", "", capabilities),
    node("small", "", explanation),
    ...(counts ? [node("small", "", counts)] : []),
  );
}

function buildReceiptPreview(receipt, sources) {
  const section = node("section", "finance-receipt-preview");
  section.append(node("h3", "", "Podgląd źródła"));
  if (!sources.length) {
    section.append(empty("Brak zapisanego źródła."));
    return section;
  }
  const tabs = node("div", "finance-receipt-source-tabs");
  const controls = node("div", "finance-receipt-preview-controls");
  const viewer = node("div", "finance-receipt-source-viewer");
  let zoom = 1;
  let currentSource = null;
  const applyZoom = () => {
    const media = viewer.querySelector("img");
    if (media) media.style.setProperty("--receipt-zoom", String(zoom));
  };
  const show = (source) => {
    currentSource = source;
    zoom = 1;
    if (source.mimeType.startsWith("image/")) {
      const image = node("img"); image.src = source.contentUrl; image.alt = `Podgląd ${source.filename}`;
      viewer.replaceChildren(image);
    } else if (source.mimeType === "application/pdf") {
      const frame = node("iframe"); frame.src = source.contentUrl; frame.title = `Podgląd ${source.filename}`;
      viewer.replaceChildren(frame);
    } else {
      const link = node("a", "finance-button is-quiet", "Otwórz zapisane źródło");
      link.href = source.contentUrl; link.target = "_blank"; link.rel = "noopener";
      viewer.replaceChildren(link);
    }
    applyZoom();
  };
  sources.forEach((source, index) => {
    const label = source.pageNumber ? `Strona ${source.pageNumber}` : source.sourceRole === "archive" ? "PDF" : source.filename;
    const button = node("button", "finance-button is-quiet", label); button.type = "button";
    button.addEventListener("click", () => show(source)); tabs.append(button);
    if (!index) show(source);
  });
  const fitWidth = node("button", "finance-button is-quiet", "Dopasuj szerokość"); fitWidth.type = "button";
  fitWidth.addEventListener("click", () => { zoom = 1; viewer.dataset.fit = "width"; applyZoom(); });
  const fitPage = node("button", "finance-button is-quiet", "Dopasuj stronę"); fitPage.type = "button";
  fitPage.addEventListener("click", () => { zoom = 1; viewer.dataset.fit = "page"; applyZoom(); });
  const minus = node("button", "finance-button is-quiet", "−"); minus.type = "button";
  minus.addEventListener("click", () => { zoom = Math.max(.5, zoom - .25); applyZoom(); });
  const plus = node("button", "finance-button is-quiet", "+"); plus.type = "button";
  plus.addEventListener("click", () => { zoom = Math.min(3, zoom + .25); applyZoom(); });
  const larger = node("button", "finance-button is-quiet", "Otwórz większy podgląd"); larger.type = "button";
  larger.addEventListener("click", () => { if (currentSource) globalThis.open?.(currentSource.contentUrl, "_blank", "noopener"); });
  controls.append(fitWidth, fitPage, minus, plus, larger);
  section.append(tabs, controls, viewer);
  return section;
}

function receiptFieldSourceLabel(source) {
  if (source === "manual" || source === "guided_review") return "potwierdzone ręcznie";
  if (source) return "odczytane automatycznie";
  return "brak potwierdzenia";
}

function receiptReviewGroup(receipt, item) {
  return {
    id: item.reviewGroupId,
    receiptId: receipt.id,
    retailerKey: receipt.retailerKey,
    rawName: item.interpretedName || item.rawName,
    itemCount: item.reviewGroupItemCount || 1,
    sampleItemId: item.id,
    samplePrice: item.effectivePrice,
    sourceLine: item.sourceLine,
    cropUrl: item.cropUrl,
    nameConfidence: item.nameConfidence,
    suggestion: {},
  };
}

function buildReceiptChecklist(receipt, targets) {
  const unresolved = new Set(receipt.parseReview?.unresolved || []);
  const resolvedItems = receipt.items.filter((item) => item.reviewState === "resolved").length;
  const checks = [
    {
      label: "Sprzedawca", value: receipt.retailer,
      detail: receiptFieldSourceLabel(receipt.fieldSources?.merchant),
      done: Boolean(receipt.retailerKey && receipt.retailer !== "Nierozpoznany sprzedawca"), action: targets.merchant,
    },
    {
      label: "Data zakupu", value: receipt.date ? dateLabel(receipt.date) : "Brak daty",
      detail: receiptFieldSourceLabel(receipt.fieldSources?.purchaseDate),
      done: Boolean(receipt.date && !unresolved.has("purchase_date")), action: targets.date,
    },
    {
      label: "Suma paragonu", value: receiptTotalLabel(receipt, money),
      detail: receiptFieldSourceLabel(receipt.fieldSources?.total),
      done: receipt.total != null && !unresolved.has("total"), action: targets.total,
    },
    {
      label: "Produkty", value: `${resolvedItems} z ${receipt.items.length} potwierdzonych`,
      detail: receipt.items.length ? "Każda pozycja powinna mieć kategorię" : "Nie odczytano pozycji",
      done: receipt.items.length > 0 && resolvedItems === receipt.items.length, action: targets.items,
    },
    {
      label: "Zgodność kwoty", value: receipt.validationState === "valid" || receipt.validationState === "valid_with_adjustments" ? "Suma się zgadza" : "Wymaga sprawdzenia",
      detail: receipt.validationDifference == null ? "Brak pełnego porównania" : `Różnica: ${money(receipt.validationDifference)}`,
      done: ["valid", "valid_with_adjustments"].includes(receipt.validationState), action: targets.validation,
    },
    {
      label: "Płatność bankowa", value: receipt.transactionId ? "Dopasowana" : "Niedopasowana",
      detail: receipt.transactionId ? "Paragon jest połączony z transakcją" : "Wybierz odpowiadającą transakcję",
      done: Boolean(receipt.transactionId), action: targets.match,
    },
  ];
  const section = node("section", "finance-receipt-checklist");
  const completed = checks.filter((item) => item.done).length;
  const header = node("header");
  const heading = node("div");
  heading.append(node("h3", "", completed === checks.length ? "Paragon kompletny" : "Co jeszcze trzeba potwierdzić?"),
    node("small", "", `${completed} z ${checks.length} elementów gotowych`));
  header.append(heading, node("span", `finance-receipt-completion${completed === checks.length ? " is-complete" : ""}`, `${completed}/${checks.length}`));
  const list = node("div", "finance-receipt-checks");
  checks.forEach((check) => {
    const row = node("article", `finance-receipt-check${check.done ? " is-confirmed" : " is-pending"}`);
    const mark = node("span", "finance-receipt-check-mark", check.done ? "✓" : "!");
    const copy = node("div");
    copy.append(node("strong", "", check.label), node("span", "", check.value), node("small", "", check.detail));
    const action = node("button", "finance-button is-quiet", check.done ? "Edytuj" : "Popraw");
    action.type = "button";
    action.addEventListener("click", check.action);
    row.append(mark, copy, action);
    list.append(row);
  });
  section.append(header, list);
  return section;
}

async function openReceiptDetail(receiptId, noticeText = "") {
  const categoryRequest = state.receiptProductCategories?.length
    ? Promise.resolve(state.receiptProductCategories)
    : fetchReceiptProductCategories();
  const [receipt, sources, productCategories] = await Promise.all([
    fetchFinanceReceipt(receiptId), fetchFinanceReceiptSources(receiptId), categoryRequest,
  ]);
  state.receiptProductCategories = productCategories;
  const dialog = $("finance-receipt-detail");
  const body = $("finance-receipt-detail-body");
  $("finance-receipt-detail-title").textContent = `${receipt.retailer} · ${receiptTotalLabel(receipt, money)}`;
  const summary = node("div", "finance-receipt-summary");
  const processingExplanation = receiptProcessingExplanation(receipt);
  summary.append(
    node("strong", "", `${dateLabel(receipt.date)} · ${receipt.sourceType.toUpperCase()}`),
    node("span", `finance-receipt-state is-${receipt.processingState}`, receiptProcessingLabel(receipt)),
    ...(processingExplanation ? [node("span", "", processingExplanation)] : []),
    node("span", "", `Walidacja: ${receipt.validationState}${receipt.validationDifference ? ` · różnica ${money(receipt.validationDifference)}` : ""}`),
    node("span", "", `${receiptMatchLabel(receipt)} (${receipt.matchState})`),
  );
  const actions = node("div", "finance-receipt-actions");
  const retry = node("button", "finance-button", "Przetwórz ponownie"); retry.type = "button";
  retry.addEventListener("click", async () => {
    retry.disabled = true;
    try { await reprocessFinanceReceipt(receipt.id); await openReceiptDetail(receipt.id); await loadReceipts(); }
    catch (error) { setStatus(error.message || "Ponowne przetwarzanie nie powiodło się.", true); }
    finally { retry.disabled = false; }
  });
  actions.append(retry);
  const remove = node("button", "finance-button is-quiet is-danger", "Usuń paragon");
  remove.type = "button";
  remove.addEventListener("click", async () => {
    const confirmed = globalThis.confirm?.(
      "Usunąć paragon i jego prywatne pliki? Transakcja bankowa pozostanie bez zmian. Tej operacji nie cofniesz w aplikacji.",
    );
    if (!confirmed) return;
    remove.disabled = true;
    try {
      await deleteFinanceReceipt(receipt.id);
      if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open");
      setStatus("Paragon usunięty. Transakcja bankowa pozostała bez zmian.");
      await loadReceipts();
    } catch (error) {
      remove.disabled = false;
      setStatus(error.message || "Nie udało się usunąć paragonu.", true);
    }
  });
  actions.append(remove);
  const openParseRepair = () => guidedDialog?.open({
    domain: "receipt_parse", receipt, group: receipt,
  });
  if (receipt.parseReview?.unresolved?.length) {
    const guidedRepair = node("button", "finance-button finance-guided-start", "Pomóż naprawić odczyt");
    guidedRepair.type = "button";
    guidedRepair.addEventListener("click", openParseRepair);
    actions.append(guidedRepair);
  }

  const metadata = node("section", "finance-receipt-metadata");
  metadata.append(node("h3", "", "Dane paragonu"), node("p", "finance-receipt-section-help", "Popraw wartości, które nie zgadzają się z podglądem po lewej."));
  const merchant = node("input"); merchant.value = receipt.retailerKey ? receipt.retailer : ""; merchant.placeholder = "Sprzedawca";
  const purchased = node("input"); purchased.type = "text"; purchased.inputMode = "numeric"; purchased.placeholder = "DD/MM/YYYY"; purchased.pattern = "\\d{2}/\\d{2}/\\d{4}"; purchased.value = receipt.date ? dateLabel(receipt.date) : "";
  const total = node("input"); total.type = "number"; total.step = "0.01"; total.min = "0"; total.value = receipt.total ?? ""; total.placeholder = "Suma PLN";
  const field = (label, input, source) => {
    const wrapper = node("label", "finance-receipt-field");
    wrapper.append(node("span", "", label), input, node("small", "", receiptFieldSourceLabel(source)));
    return wrapper;
  };
  const save = node("button", "finance-button", "Zapisz i odśwież"); save.type = "button";
  const saveStatus = node("span", "finance-receipt-save-status", ""); saveStatus.setAttribute("role", "status");
  save.addEventListener("click", async () => {
    save.disabled = true;
    save.textContent = "Zapisywanie…";
    saveStatus.textContent = "Aktualizuję checklistę…";
    try {
      const values = {};
      if (merchant.value.trim()) values.merchant = merchant.value.trim();
      if (purchased.value) {
        values.purchaseDate = financeDateToIso(purchased.value);
        if (!values.purchaseDate) throw new Error("Podaj datę w formacie DD/MM/YYYY.");
      }
      if (total.value !== "") values.total = total.value;
      await updateFinanceReceiptMetadata(receipt.id, values);
      setStatus("Zapisano dane paragonu i odświeżono status potwierdzeń.");
      await loadReceipts();
      await openReceiptDetail(receipt.id, "Zapisano dane paragonu. Checklista została odświeżona.");
    } catch (error) {
      save.disabled = false;
      save.textContent = "Zapisz i odśwież";
      saveStatus.textContent = "";
      setStatus(error.message || "Nie udało się zapisać danych paragonu.", true);
    }
  });
  metadata.append(
    field("Sprzedawca", merchant, receipt.fieldSources?.merchant),
    field("Data zakupu", purchased, receipt.fieldSources?.purchaseDate),
    field("Suma", total, receipt.fieldSources?.total),
    save, saveStatus,
  );

  const items = node("section", "finance-receipt-items");
  const itemHeader = node("header", "finance-receipt-items-header");
  const resolvedItemCount = receipt.items.filter((item) => item.reviewState === "resolved").length;
  itemHeader.append(node("h3", "", "Produkty z paragonu"), node("span", "finance-receipt-completion", `${resolvedItemCount}/${receipt.items.length}`));
  items.append(itemHeader);
  if (!receipt.items.length) items.append(empty("Nie odczytano jeszcze pozycji. Oryginał pozostaje dostępny w podglądzie."));
  receipt.items.forEach((item) => {
    const itemConfirmed = item.reviewState === "resolved";
    const row = node("article", `finance-list-row finance-receipt-item-row${itemConfirmed ? " is-confirmed" : " is-pending"}`);
    const copy = node("div");
    copy.append(node("strong", "", item.productName || item.interpretedName || item.rawName),
      node("small", "", `${item.quantity} ${item.unit} · ${item.productCategory || "produkt nierozpoznany"}${item.discount ? ` · rabat ${money(item.discount)}` : ""}`));
    const side = node("div", "finance-receipt-item-side");
    side.append(node("span", `finance-receipt-confirmation${itemConfirmed ? " is-confirmed" : " is-pending"}`, itemConfirmed ? "✓ Potwierdzone" : "! Do poprawy"),
      node("b", "", money(item.effectivePrice, receipt.currency)));
    if (item.productId) {
      const product = node("button", "finance-button is-quiet", "Produkt");
      product.type = "button"; product.addEventListener("click", () => openProductDetail(item.productId)); side.append(product);
    } else if (item.reviewGroupId) {
      const review = node("button", "finance-button finance-guided-start", "Ustal produkt");
      review.type = "button";
      review.addEventListener("click", () => guidedDialog?.open({
        domain: "receipt_item",
        group: receiptReviewGroup(receipt, item),
        productCategories,
      }));
      side.append(review);
    } else if (!itemConfirmed && receipt.parseReview?.unresolved?.length) {
      const repair = node("button", "finance-button is-quiet", "Popraw odczyt");
      repair.type = "button";
      repair.addEventListener("click", openParseRepair);
      side.append(repair);
    }
    row.append(copy, side); items.append(row);
  });
  const matchBox = node("section", "finance-receipt-match");
  if (!receipt.transactionId) {
    const match = await matchFinanceReceipt(receipt.id);
    matchBox.append(node("h3", "", match.state === "ambiguous" ? "Która płatność odpowiada temu paragonowi?" : "Dopasowanie transakcji"));
    if (!match.candidates.length) matchBox.append(empty("Nie znaleziono bezpiecznego kandydata."));
    match.candidates.forEach((candidate) => {
      const button = node("button", "finance-match-candidate");
      button.type = "button";
      const reasons = (candidate.evidence || []).map((value) => ({ amount_exact: "✓ ta sama kwota", date_exact: "✓ ta sama data", date_near: "✓ bliska data", retailer_exact: "✓ zgodny sprzedawca" }[value] || value)).join(" · ");
      button.append(node("strong", "", candidate.merchant), node("span", "", `${dateLabel(candidate.date)} · ${money(candidate.amount, candidate.currency)}`), node("small", "", reasons));
      button.addEventListener("click", async () => {
        await matchFinanceReceipt(receipt.id, candidate.transactionId);
        await loadReceipts();
        await openReceiptDetail(receipt.id, "Dopasowano płatność i odświeżono checklistę.");
      });
      matchBox.append(button);
    });
    const manualTitle = node("h3", "", "Wyszukaj inną transakcję");
    const search = node("input"); search.placeholder = "Opis lub sprzedawca";
    const searchButton = node("button", "finance-button is-quiet", "Szukaj"); searchButton.type = "button";
    const results = node("div", "finance-receipt-match-results");
    searchButton.addEventListener("click", async () => {
      const payload = await fetchBudgetTransactions({ page: 1, limit: 15, text: search.value, sort: "newest" });
      results.replaceChildren(...(payload.transactions || []).map((transaction) => {
        const button = node("button", "finance-match-candidate"); button.type = "button";
        button.append(node("strong", "", transaction.merchant || transaction.description), node("span", "", `${dateLabel(transaction.date)} · ${money(transaction.amount, transaction.currency)}`));
        button.addEventListener("click", async () => {
          await matchFinanceReceipt(receipt.id, transaction.id);
          await loadReceipts();
          await openReceiptDetail(receipt.id, "Dopasowano płatność i odświeżono checklistę.");
        });
        return button;
      }));
    });
    matchBox.append(manualTitle, search, searchButton, results);
  } else {
    matchBox.append(node("h3", "", "Płatność bankowa"), node("p", "finance-receipt-match-confirmed", "✓ Dopasowana ręcznie lub automatycznie. Transakcja bankowa pozostaje źródłem kwoty wydatku."));
  }
  const diagnostics = node("details", "finance-receipt-diagnostics");
  const quality = receipt.parserDiagnostics || {};
  diagnostics.append(node("summary", "", "Zaawansowane: jakość OCR i parsera"),
    node("p", "", `OCR: ${sources.find((source) => source.ocrProvenance)?.ocrProvenance || "brak"} · Linie: ${quality.ocrLines ?? "—"} · Kotwice fiskalne: ${quality.fiscalAnchors ?? "—"}`),
    node("p", "", `Pozycje: ${quality.itemsStrong ?? 0} mocne / ${quality.itemsWeak ?? 0} słabe · Suma: ${quality.totalConfidence || "unknown"} · Uzgodnienie: ${quality.reconciliation?.differenceMinor == null ? "brak" : money(quality.reconciliation.differenceMinor / 100)}`));
  const reveal = (element, focus = false) => () => {
    element?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    if (focus) element?.focus?.();
  };
  const checklist = buildReceiptChecklist(receipt, {
    merchant: reveal(merchant, true),
    date: reveal(purchased, true),
    total: reveal(total, true),
    items: reveal(items),
    validation: receipt.parseReview?.unresolved?.length ? openParseRepair : () => retry.click(),
    match: reveal(matchBox),
  });
  const right = node("div", "finance-receipt-detail-content");
  right.append(summary);
  if (noticeText) right.append(node("div", "finance-receipt-notice", `✓ ${noticeText}`));
  right.append(checklist, actions, metadata, items, matchBox, diagnostics);
  body.replaceChildren(buildReceiptPreview(receipt, sources), right);
  if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal(); else dialog.setAttribute("open", "");
}

async function loadReceipts() {
  const [receipts, groups, categories, quality, processingHealth] = await Promise.all([
    fetchFinanceReceipts({ status: $("finance-receipt-status").value }),
    fetchReceiptItemReviewGroups(),
    fetchReceiptProductCategories(),
    fetchFinanceResource("data-quality"),
    fetchReceiptProcessingHealth(),
  ]);
  state.receiptProductCategories = categories;
  const metrics = quality.receipts || {};
  $("finance-receipt-count").textContent = metrics.needsMatch || metrics.unknownProducts ? String((metrics.needsMatch || 0) + (metrics.unknownProducts || 0)) : "";
  $("finance-receipt-coverage").textContent = `${metrics.mixedRetailerCoveragePercent || 0}% wydatków mieszanych z paragonami`;
  renderReceiptHealth($("finance-receipt-health"), processingHealth);
  $("finance-receipt-metrics").replaceChildren(
    progressRow("Dopasowane", `${metrics.receiptMatchRate || 0}%`, `${metrics.matchedToTransactions || 0} z ${metrics.receiptsImported || 0} paragonów`, metrics.receiptMatchRate),
    progressRow("Pozycje", `${metrics.itemClassificationCoverage || 0}%`, `${metrics.itemsClassified || 0} z ${metrics.itemsParsed || 0} sklasyfikowanych`, metrics.itemClassificationCoverage),
    progressRow("Pokrycie zakupów mieszanych", `${metrics.mixedRetailerCoveragePercent || 0}%`, `${money(metrics.mixedRetailerSpendCovered || 0)} pokryte · ${money(metrics.mixedRetailerSpendUncovered || 0)} bez paragonu`, metrics.mixedRetailerCoveragePercent),
  );
  $("finance-receipts").replaceChildren(...(receipts.length ? receipts.map((receipt) => {
    const row = node("button", "finance-list-row finance-receipt-row"); row.type = "button";
    const copy = node("div");
    copy.append(node("strong", "", receipt.retailer), node("small", "", `${dateLabel(receipt.date)} · ${receipt.itemCount} pozycji · ${receipt.sourceType.toUpperCase()} · ${receiptProcessingLabel(receipt)}`));
    row.append(copy, node("b", "", receiptTotalLabel(receipt, money)), node("span", `finance-receipt-state is-${receipt.processingState}`, receiptMatchLabel(receipt)));
    row.addEventListener("click", () => openReceiptDetail(receipt.id).catch((error) => setStatus(error.message, true)));
    return row;
  }) : [emptyState("Brak paragonów", "Dodaj zdjęcie, PDF albo JSON. Wszystkie źródła korzystają z tego samego lokalnego pipeline’u.")]));
  $("finance-receipt-review").replaceChildren(...(groups.length ? groups.map((group) => {
    const card = node("article", "finance-list-row finance-receipt-review-row");
    const copy = node("div"); copy.append(node("strong", "", group.rawName), node("small", "", `${group.retailerKey || "sprzedawca"} · ${money(group.samplePrice ?? group.impact)} · ${group.itemCount} wystąpień`));
    if (group.sourceLine) copy.append(node("small", "", `OCR: ${group.sourceLine}`));
    const guided = node("button", "finance-button finance-guided-start", "Pomóż mi ustalić"); guided.type = "button";
    guided.addEventListener("click", () => guidedDialog?.open({ domain: "receipt_item", group, productCategories: categories }));
    card.append(copy, guided); return card;
  }) : [emptyState("Wszystkie pozycje są rozpoznane", "Nowe nierozpoznane nazwy pojawią się tutaj po imporcie.")]));
}

async function loadBudgets() {
  const referenceDate = state.month === currentMonth ? new Date().toISOString().slice(0, 10) : `${state.month}-17`;
  const [budgets, categories] = await Promise.all([fetchFinanceResource("budgets", { month: state.month, referenceDate }), fetchBudgetCategories()]);
  const select = $("finance-budget-category");
  select.replaceChildren(new Option("Budżet ogólny", ""), ...categories.map((item) => new Option(item.parentName ? `${item.parentName} / ${item.name}` : item.name, item.id)));
  await loadBudgetContext();
  $("finance-budgets").replaceChildren(...(budgets.length ? budgets.map((item) => budgetRow(item, `${item.source === "monthly_inflows" ? `${item.sourceDate ? `Wypłata AON z ${dateLabel(item.sourceDate)} + ` : ""}wpływy miesiąca · ` : ""}Pozostało ${money(item.remaining)} · prognoza ${money(item.projected)} · miesiąc ${item.elapsedPercent}%`)) : [emptyState("Nie masz jeszcze limitów", "Budżet pozwala ustalić maksymalne wydatki w miesiącu. Limit ogólny wystarczy na start; limity kategorii są opcjonalne.")]));
}

async function loadBudgetContext() {
  const categoryId = $("finance-budget-category").value;
  const suggestion = await fetchFinanceResource("budget-suggestion", { month: state.month, categoryId });
  const previous = suggestion.previousMonth
    ? `${polishMonthLabel(suggestion.previousMonth)}: ${money(suggestion.previousMonthSpending)}`
    : "Brak poprzedniego miesiąca z danymi";
  $("finance-budget-context").replaceChildren(
    ...(suggestion.salaryBudget ? [node("strong", "", `Wypłata AON na ${polishMonthLabel(state.month)}: ${money(suggestion.salaryBudget.amount)} (${dateLabel(suggestion.salaryBudget.sourceDate)}); limit ogólny obejmuje też inne wpływy.`)] : []),
    node("strong", "", `Średnie wydatki: ${money(suggestion.averageMonthly)} / miesiąc`),
    node("span", "", previous),
    node("span", "", suggestion.suggestedLimit ? `Sugestia startowa: ${money(suggestion.suggestedLimit)} — kliknij, aby użyć` : "Za mało historii do sugestii"),
  );
  if (suggestion.suggestedLimit) {
    const use = node("button", "finance-button is-quiet", "Użyj sugestii");
    use.type = "button";
    use.addEventListener("click", () => { $("finance-budget-limit").value = suggestion.suggestedLimit; });
    $("finance-budget-context").append(use);
  }
}

async function loadRecurring() {
  const [obligations, candidates, upcoming, planned] = await Promise.all([
    fetchFinanceResource("obligations", { active: true }), fetchFinanceResource("recurring-candidates"), fetchFinanceResource("upcoming", { days: 30 }), fetchFinanceResource("planned-items"),
  ]);
  $("finance-recurring-total").textContent = `${money(upcoming.filter((item) => !["income", "salary"].includes(item.kind)).reduce((sum, item) => sum + item.amount, 0))} / 30 dni`;
  $("finance-obligations").replaceChildren(...(obligations.length ? obligations.map((item) => {
    const row = node("article", "finance-list-row"); const copy = node("div");
    copy.append(node("strong", "", item.name), node("small", "", `${item.kind} · ${item.cadence} · następnie ${dateLabel(item.nextExpectedDate)}`));
    row.append(copy, node("b", "", money(item.amount))); return row;
  }) : [emptyState("Brak potwierdzonych zobowiązań", "Potwierdzone płatności wpływają na prognozę i Safe-to-spend. Dodaj je w formularzu powyżej.")]));
  $("finance-candidates").replaceChildren(...(candidates.length ? candidates.map((item) => {
    const row = node("article", "finance-list-row"); const copy = node("div");
    copy.append(node("strong", "", item.merchant), node("small", "", `${item.cadence} · ${item.evidence.occurrenceCount} wystąpień · mediana ${item.evidence.medianIntervalDays} dni · ${money(item.evidence.amountMin)}–${money(item.evidence.amountMax)}`));
    row.append(copy, node("span", "finance-candidate", "Kandydat")); return row;
  }) : [emptyState("Brak kandydatów", "Kandydat pojawi się po co najmniej trzech regularnych transakcjach. Nic nie jest potwierdzane automatycznie.")]));
  $("finance-planned-items").replaceChildren(...(planned.length ? planned.map((item) => {
    const row = node("article", "finance-list-row"); const copy = node("div");
    copy.append(node("strong", "", item.name), node("small", "", `${dateLabel(item.date)} · ${item.kind}${item.includeSafeToSpend ? " · w safe-to-spend" : ""}`));
    row.append(copy, node("b", "", money(item.amount))); return row;
  }) : [emptyState("Brak jednorazowych planów", "Dodaj przyszły wydatek, wpływ lub zobowiązanie oszczędnościowe formularzem powyżej.")]));
}

async function loadGoals() {
  const goals = await fetchFinanceResource("goals");
  $("finance-goals").replaceChildren(...(goals.length ? goals.map((goal) => {
    const card = node("article", `finance-goal-card${goal.primary ? " is-primary" : ""}`);
    const heading = node("header"); heading.append(node("div", "", goal.kind === "emergency_fund" ? "Fundusz bezpieczeństwa" : "Cel"), node("strong", "", goal.name));
    card.append(heading, progressRow("Postęp", `${money(goal.allocated)} / ${money(goal.target)}`, `Pozostało ${money(goal.remaining)}`, goal.progressPercent));
    const facts = node("dl");
    [["Wymagana wpłata", goal.requiredMonthlyContribution == null ? "—" : money(goal.requiredMonthlyContribution)], ["Plan miesięczny", money(goal.monthlyContribution)], ["Szacowane zakończenie", dateLabel(goal.estimatedCompletionDate)]].forEach(([key, value]) => { facts.append(node("dt", "", key), node("dd", "", value)); });
    card.append(facts); return card;
  }) : [emptyState("Utwórz pierwszy cel", "Cel pokazuje postęp, pozostałą kwotę oraz wymagane tempo. Przydział jest jawny i nie obejmuje automatycznie całego konta oszczędnościowego.")]));
}

async function loadAnalysis() {
  const referenceDate = state.month === currentMonth ? new Date().toISOString().slice(0, 10) : `${state.month}-17`;
  const data = await fetchFinanceOverview({ referenceDate });
  const averageRange = data.goalAverageFrom
    ? `${data.goalAverageMonths} mies. · z wybranym`
    : "Brak historii od maja 2026";
  const lifetimeRange = data.goalLifetimeFrom
    ? `${polishMonthLabel(data.goalLifetimeFrom)} · ${data.goalLifetimeMonths} mies.`
    : "Brak historii konta";
  $("finance-analysis-goal-periods").replaceChildren(...(data.goals?.length ? [
    goalPeriod("Wybrany miesiąc", polishMonthLabel(state.month), data.goalDeposits,
      data.goalWithdrawals, data.goalDepositRate, data.goalWithdrawalRate),
    goalPeriod("Średnio od maja 2026", averageRange, data.goalAverageDeposits,
      data.goalAverageWithdrawals, data.goalAverageDepositRate, data.goalAverageWithdrawalRate),
    goalPeriod("Średnio od początku", lifetimeRange, data.goalLifetimeDeposits,
      data.goalLifetimeWithdrawals, data.goalLifetimeDepositRate, data.goalLifetimeWithdrawalRate),
  ] : [empty("Brak celu oszczędnościowego.")]));
  const flow = $("finance-analysis-flow");
  flow.replaceChildren(...[
    ["Wpływy na miesiąc", data.income],
    ["Zapłacone", data.expenses],
    ["Z wpływów zostało", data.remainingFromIncome],
    ["Wpłacono na cel", data.goalDeposits],
  ].map(([label, amount]) => {
    const item = node("article");
    item.append(node("span", "", label), node("strong", "", money(amount)));
    return item;
  }));
}

async function loadReport() {
  const report = await fetchFinanceResource("report", { month: state.month });
  $("finance-report-title").textContent = polishMonthLabel(state.month);
  const metrics = node("div", "finance-report-metrics");
  [["Dochód", report.income], ["Wynagrodzenie", report.salary], ["Inny dochód", report.otherIncome], ["Zwroty", report.refunds], ["Wydatki", report.expenses], ["Oszczędności", report.savings], ["Transfery", report.transfers], ["Przepływ netto", report.netCashFlow], ["Subskrypcje", report.subscriptionCost]].forEach(([label, value]) => { const item = node("article"); item.append(node("span", "", label), node("strong", "", money(value))); metrics.append(item); });
  const lists = node("div", "finance-report-lists");
  [["Największe kategorie", report.topCategories], ["Największe miejsca", report.topMerchants]].forEach(([title, items]) => { const section = node("section", "finance-card"); section.append(node("h3", "", title)); if (!items.length) section.append(empty("Brak wydatków w tym okresie.")); items.forEach((item) => { const row = node("div", "finance-list-row"); row.append(node("span", "", item.name), node("b", "", money(item.amount))); section.append(row); }); lists.append(section); });
  $("finance-report").replaceChildren(metrics, lists);
}

async function loadSettings() {
  const [accounts, quality, rules, imports, categories, merchants, safe, bootstrap, processingHealth] = await Promise.all([
    fetchFinanceResource("accounts"), fetchFinanceResource("data-quality"), fetchBudgetRules(),
    fetchBudgetImportHistory(), fetchBudgetCategories(), fetchBudgetMerchants(),
    fetchFinanceResource("safe-to-spend", { referenceDate: `${state.month}-17` }),
    fetchFinanceResource("classification-bootstrap"),
    fetchReceiptProcessingHealth(),
  ]);
  renderReceiptHealth($("finance-receipt-health-settings"), processingHealth);
  $("finance-accounts").replaceChildren(...(accounts.length ? accounts.map((account) => {
    const row = node("article", "finance-list-row finance-account-row"); const copy = node("div");
    const label = node("input"); label.value = account.displayLabel; label.setAttribute("aria-label", "Nazwa konta");
    copy.append(label, node("small", "", `Saldo ${money(account.balance)}${account.main ? " · konto główne" : ""}`));
    const select = node("select"); [["spending", "Płynne"], ["savings", "Rezerwa"], ["excluded", "Wyłączone"]].forEach(([value, label]) => select.append(new Option(label, value, false, value === account.role)));
    const save = async (main = false) => mutateFinanceResource("account-role", { id: account.id, role: select.value, includeSafeToSpend: select.value === "spending", displayLabel: label.value, main });
    select.addEventListener("change", async () => { await save(); await loadSettings(); });
    label.addEventListener("change", async () => { await save(); await loadSettings(); });
    row.append(copy, select);
    if (account.role === "spending" && !account.main) {
      const chooseMain = node("button", "finance-button is-quiet", "Ustaw jako główne");
      chooseMain.type = "button";
      chooseMain.addEventListener("click", async () => { await save(true); await loadSettings(); });
      row.append(chooseMain);
    }
    return row;
  }) : [empty("Konta pojawią się po imporcie.")]));
  const reviewQuality = quality.reviewModel;
  const qualityItems = reviewQuality
    ? [["Miejsca (istotne)", reviewQuality.merchant.coveragePercent], ["Kategorie (wymagane)", reviewQuality.category.coveragePercent], ["Rodzaje transakcji (wszystkie)", reviewQuality.transactionKind.coveragePercent]]
    : [["Miejsca", quality.merchantCoveragePercent], ["Kategorie", quality.categoryCoveragePercent], ["Rodzaje transakcji", quality.transactionKindCoveragePercent]];
  $("finance-data-quality").replaceChildren(
    ...qualityItems.map(([label, percent]) => progressRow(label, `${percent}%`, "", percent)),
    node("small", "", reviewQuality
      ? `${reviewQuality.category.requiredMissing} faktycznie wymaga kategorii · surowo ${reviewQuality.category.rawMissing} pustych pól / ${reviewQuality.category.rawTotal} transakcji · ${reviewQuality.ruleConflicts} konfliktów`
      : `${quality.unknownMerchantCount} bez miejsca · ${quality.missingCategoryCount} bez kategorii · ${quality.activeRuleCount} aktywnych reguł · ${quality.ruleConflictCount} konfliktów`),
    node("small", "", `Bootstrap: ${quality.classificationBootstrap.defaultsCreated} bezpiecznych wartości domyślnych z ${quality.classificationBootstrap.patternsAnalyzed} wzorców; ${quality.classificationBootstrap.requiringReview} wymaga oceny.`),
  );
  if (quality.receipts) {
    $("finance-data-quality").append(
      progressRow("Paragony dopasowane", `${quality.receipts.receiptMatchRate}%`, `${quality.receipts.matchedToTransactions} dopasowanych · ${quality.receipts.needsMatch} wymaga decyzji`, quality.receipts.receiptMatchRate),
      progressRow("Pozycje paragonów", `${quality.receipts.itemClassificationCoverage}%`, `${quality.receipts.itemsClassified} sklasyfikowanych · ${quality.receipts.unknownProducts} nieznanych produktów`, quality.receipts.itemClassificationCoverage),
    );
    const receiptDrill = node("button", "finance-button is-quiet", "Otwórz paragony"); receiptDrill.dataset.openView = "receipts"; $("finance-data-quality").append(receiptDrill);
  }
  const drill = node("button", "finance-button is-quiet", "Przejdź do nierozpoznanych"); drill.dataset.openView = "review"; $("finance-data-quality").append(drill);
  $("finance-categories-summary").replaceChildren(
    (() => { const row = node("article", "finance-list-row"); row.append(node("span", "", "Aktywne kategorie i podkategorie"), node("b", "", String(categories.length))); return row; })(),
    node("small", "", "Taksonomia ma maksymalnie dwa poziomy. Rodzaj transakcji pozostaje osobnym polem."),
  );
  $("finance-merchants-summary").replaceChildren(
    (() => { const row = node("article", "finance-list-row"); row.append(node("span", "", "Rozpoznane miejsca"), node("b", "", String(merchants.length))); return row; })(),
    node("small", "", "Miejsca mieszane pozostają w szerokiej kategorii do czasu danych paragonowych."),
  );
  $("finance-bootstrap").replaceChildren(...bootstrap.slice(0, 8).map((item) => {
    const row = node("article", "finance-list-row");
    const copy = node("div");
    copy.append(node("strong", "", item.merchant), node("small", "", `${item.occurrenceCount} transakcji · ${item.reason}`));
    row.append(copy, node("span", item.decision === "merchant_default" ? "finance-candidate is-safe" : "finance-candidate", item.decision === "merchant_default" ? item.defaultCategory || "Domyślna" : "Do oceny"));
    return row;
  }), node("small", "", `Przeanalizowano ${bootstrap.length} miejsc. Automatyczny próg: minimum 3 wystąpienia i pełna zgodność historyczna.`));
  $("finance-safe-buffer").value = safe.safetyBuffer || "";
  $("finance-safe-breakdown").replaceChildren(
    ...[["Płynne środki", safe.liquidBalance], ["Zobowiązania", -safe.confirmedObligations], ["Plany", -(safe.plannedExpenses + safe.plannedSavingsCommitments)], ["Bufor", -safe.safetyBuffer]].map(([label, value]) => {
      const row = node("article", "finance-list-row"); row.append(node("span", "", label), node("b", "", money(value))); return row;
    }),
    node("strong", "finance-safe-result", `Wynik: ${money(safe.safeToSpend)}`),
  );
  $("finance-rules").replaceChildren(...(rules.length ? rules.map((rule) => {
    const row = node("article", "finance-list-row finance-rule-row"); const copy = node("div");
    const readable = `${rule.conditions.map((c) => `${c.field} ${c.operator} ${c.value_text ?? c.value_minor ?? ""}`).join(" i ")} → ${rule.actions.map((a) => `${a.field}: ${a.value_text ?? a.value_id ?? ""}`).join(", ")}`;
    copy.append(node("strong", "", rule.name), node("small", "", readable), node("small", "", rule.enabled ? `Włączona · priorytet ${rule.priority}` : "Wyłączona"));
    const actions = node("div", "finance-rule-actions");
    const actionButton = (label, handler, quiet = true) => { const button = node("button", `finance-button${quiet ? " is-quiet" : ""}`, label); button.addEventListener("click", handler); actions.append(button); };
    actionButton(rule.enabled ? "Wyłącz" : "Włącz", async () => { await updateBudgetRule(rule.id, { enabled: !rule.enabled }); await loadSettings(); });
    actionButton("Podgląd", async () => { const result = await previewBudgetRule(rule.id); setStatus(`Reguła „${rule.name}”: ${result.preview.matched} dopasowań, ${Object.values(result.preview.changes || {}).reduce((a, b) => a + b, 0)} zmian.`); });
    actionButton("Zastosuj", async () => { const result = await applyBudgetRule(rule.id); setStatus(`Zastosowano „${rule.name}” do ${result.apply.matched} dopasowań.`); }, false);
    actionButton("Edytuj", async () => { const name = globalThis.prompt?.("Nazwa reguły", rule.name); if (name && name !== rule.name) { await updateBudgetRule(rule.id, { name }); await loadSettings(); } });
    actionButton("Usuń", async () => { if (globalThis.confirm?.(`Usunąć regułę „${rule.name}”?`)) { await deleteBudgetRule(rule.id); await loadSettings(); } });
    row.append(copy, actions); return row;
  }) : [empty("Brak reguł. Twórz je z kolejki przeglądu.")]));
  $("finance-imports").replaceChildren(...(imports.length ? imports.map((item) => {
    const row = node("article", "finance-list-row"); const copy = node("div"); copy.append(node("strong", "", item.filename), node("small", "", `${item.dateFrom || item.date_from || "—"}–${item.dateTo || item.date_to || "—"} · ${item.status}`));
    const side = node("div", "finance-import-side"); side.append(node("span", "", `${item.acceptedCount ?? item.accepted_count ?? 0} nowych · ${item.duplicateCount ?? item.duplicate_count ?? 0} duplikatów`));
    if (item.status === "completed") { const rollback = node("button", "finance-button is-quiet", "Cofnij…"); rollback.addEventListener("click", async () => { const { preview } = await previewBudgetImportRollback(item.id); if (globalThis.confirm?.(`Cofnąć import? Usunięte: ${preview.deleted}, odłączone: ${preview.detached}, z adnotacjami: ${preview.annotated}.`)) { await rollbackBudgetImport(item.id); await loadSettings(); await loadOverview(); } }); side.append(rollback); }
    row.append(copy, side); return row;
  }) : [empty("Brak importów.")]));
}

const loaders = { overview: loadOverview, transactions: loadTransactions, review: loadReview, receipts: loadReceipts, budgets: loadBudgets, recurring: loadRecurring, goals: loadGoals, analysis: loadAnalysis, reports: loadReport, settings: loadSettings };

async function openView(view) {
  if (!loaders[view]) return;
  state.view = view;
  document.querySelectorAll("[data-finance-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.financeView === view));
  document.querySelectorAll("[data-finance-section]").forEach((section) => { const active = section.dataset.financeSection === view; section.hidden = !active; section.classList.toggle("is-active", active); });
  [$("finance-eyebrow").textContent, $("finance-view-title").textContent] = viewTitles[view];
  setStatus("Ładowanie…");
  try { await loaders[view](); setStatus(""); } catch (error) { console.error(error); setStatus(error.message || "Nie udało się załadować danych.", true); }
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-finance-view], [data-open-view]");
  if (target) openView(target.dataset.financeView || target.dataset.openView);
});
$("finance-refresh").addEventListener("click", () => openView(state.view));
$("finance-month").addEventListener("change", (event) => { state.month = event.target.value || state.month; openView(state.view); });
$("finance-current-month").addEventListener("click", () => { state.month = currentMonth; populatePeriodOptions(); openView(state.view); });
$("finance-help-toggle").addEventListener("click", () => {
  $("finance-help-panel").hidden = false;
  localStorage.removeItem("finance-onboarding-dismissed-v1");
  loadOnboarding();
});
$("finance-help-close").addEventListener("click", () => { $("finance-help-panel").hidden = true; });
$("finance-onboarding-dismiss").addEventListener("click", () => {
  localStorage.setItem("finance-onboarding-dismissed-v1", "1");
  $("finance-onboarding").hidden = true;
});
$("finance-tx-apply").addEventListener("click", () => { state.transactionPage = 1; loadTransactions(); });
$("finance-tx-prev").addEventListener("click", () => { if (state.transactionPage > 1) { state.transactionPage -= 1; loadTransactions(); } });
$("finance-tx-next").addEventListener("click", () => { if (state.transactionHasMore) { state.transactionPage += 1; loadTransactions(); } });
document.querySelectorAll("[data-review-scope]").forEach((button) => button.addEventListener("click", () => {
  state.reviewScope = button.dataset.reviewScope;
  loadReview().catch((error) => setStatus(error.message, true));
}));
$("finance-review-sort").addEventListener("change", () => loadReview().catch((error) => setStatus(error.message, true)));
$("finance-review-quick").addEventListener("change", () => loadReview().catch((error) => setStatus(error.message, true)));
$("finance-review-undo").addEventListener("click", async () => {
  if (!(globalThis.confirm?.("Cofnąć ostatnią zmianę grupową? Późniejsze ręczne zmiany zostaną zachowane.") ?? true)) return;
  try {
    const result = await undoLatestBudgetReviewGroup();
    setStatus(`Cofnięto klasyfikację ${result.restored} transakcji.`);
    await loadReview();
  } catch (error) { setStatus(error.message || "Nie udało się cofnąć zmiany.", true); }
});
$("finance-receipt-status").addEventListener("change", () => loadReceipts().catch((error) => setStatus(error.message, true)));
$("finance-receipt-undo").addEventListener("click", async () => {
  try {
    const result = await undoLatestReceiptItemGroup();
    setStatus(`Cofnięto klasyfikację ${result.restored} pozycji paragonowych.`);
    await loadReceipts();
  } catch (error) { setStatus(error.message || "Nie udało się cofnąć klasyfikacji.", true); }
});
$("finance-receipt-reprocess-all").addEventListener("click", async () => {
  const confirmed = globalThis.confirm?.("Ponownie przetworzyć wszystkie paragony wymagające OCR lub przeglądu? Identyfikatory, źródła i ręczne decyzje zostaną zachowane.") ?? true;
  if (!confirmed) return;
  try {
    const result = await reprocessFinanceReceiptsNeedingOcr();
    setStatus(`Ponownie przetworzono ${result.count} paragonów.`);
    await loadReceipts();
  } catch (error) { setStatus(error.message || "Ponowne przetwarzanie nie powiodło się.", true); }
});
$("finance-receipt-input").addEventListener("change", async (event) => {
  const file = event.target.files?.[0]; if (!file) return;
  setStatus("Importuję paragon lokalnie…");
  try {
    const receipt = await importFinanceReceipt(file);
    setStatus(receipt.duplicate ? "Ten paragon był już zaimportowany." : `Zaimportowano paragon: ${receiptProcessingLabel(receipt)}, ${receipt.itemCount} pozycji.`);
    await loadReceipts();
    await openReceiptDetail(receipt.id);
  } catch (error) { setStatus(error.message || "Import paragonu nie powiódł się.", true); }
  event.target.value = "";
});

$("finance-budget-form").addEventListener("submit", async (event) => {
  event.preventDefault(); await mutateFinanceResource("budgets", { month: state.month, categoryId: $("finance-budget-category").value || null, limit: $("finance-budget-limit").value });
  event.target.reset(); await loadBudgets();
});
$("finance-budget-category").addEventListener("change", loadBudgetContext);
$("finance-obligation-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const obligationDate = financeDateToIso($("finance-obligation-date").value); if (!obligationDate) return setStatus("Podaj datę w formacie DD/MM/YYYY.", true); await mutateFinanceResource("obligations", { name: $("finance-obligation-name").value, amount: $("finance-obligation-amount").value, startDate: obligationDate, nextExpectedDate: obligationDate, kind: $("finance-obligation-kind").value, cadence: $("finance-obligation-cadence").value, confirmed: true });
  event.target.reset(); await loadRecurring();
});
$("finance-plan-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const planDate = financeDateToIso($("finance-plan-date").value); if (!planDate) return setStatus("Podaj datę w formacie DD/MM/YYYY.", true); await mutateFinanceResource("planned-items", { name: $("finance-plan-name").value, amount: $("finance-plan-amount").value, date: planDate, kind: $("finance-plan-kind").value, includeSafeToSpend: $("finance-plan-safe").checked });
  event.target.reset(); $("finance-plan-safe").checked = true; await loadRecurring();
});
$("finance-goal-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const goalDate = $("finance-goal-date").value ? financeDateToIso($("finance-goal-date").value) : null; if ($("finance-goal-date").value && !goalDate) return setStatus("Podaj datę w formacie DD/MM/YYYY.", true); await mutateFinanceResource("goals", { name: $("finance-goal-name").value, target: $("finance-goal-target").value, allocated: $("finance-goal-allocated").value || 0, targetDate: goalDate, monthlyContribution: $("finance-goal-monthly").value || 0, kind: $("finance-goal-emergency").checked ? "emergency_fund" : "general", primary: $("finance-goal-emergency").checked });
  event.target.reset(); await loadGoals();
});
$("finance-safe-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await mutateFinanceResource("safe-settings", { buffer: $("finance-safe-buffer").value || 0 });
  await loadSettings();
});
$("finance-csv-input").addEventListener("change", async (event) => {
  const file = event.target.files?.[0]; if (!file) return;
  setStatus("Importuję CSV…");
  try { await importBudgetCsvToServer(file); setStatus("Import zakończony."); await loadOverview(); } catch (error) { setStatus(error.message || "Import nie powiódł się.", true); }
  event.target.value = "";
});

function populatePeriodOptions() {
  const select = $("finance-month");
  select.replaceChildren(...financePeriodOptions(state.month, currentMonth).map((item) => new Option(item.label, item.value)));
  select.value = state.month;
}

async function initializeFinancePage() {
  try {
    const payload = await fetchBudgetAnalytics("freshness", { referenceDate: new Date().toISOString().slice(0, 10) });
    const freshness = payload.data || payload;
    state.month = chooseDefaultFinanceMonth(currentMonth, freshness.latestTransactionDate);
  } catch (error) {
    console.warn("Finance period initialization failed", error);
  }
  populatePeriodOptions();
  await openView("overview");
}

initializeFinancePage();
setInterval(refreshImportAges, 60 * 1000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshImportAges(); });
