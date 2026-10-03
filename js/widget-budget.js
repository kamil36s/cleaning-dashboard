import { fetchFinanceOverview } from "./budget-api.js";
import { scheduleFinanceImportReminders } from "./finance-import-reminder.js";

const card = document.getElementById("budget-card");
const privacyToggle = document.getElementById("budget-privacy-toggle");
const money = (value) => new Intl.NumberFormat("pl-PL", {
  style: "currency", currency: "PLN", minimumFractionDigits: 2,
}).format(Number(value || 0));

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

if (card && privacyToggle) {
  card.classList.add("is-private");
  const updatePrivacy = () => {
    const visible = !card.classList.contains("is-private");
    privacyToggle.textContent = visible ? "Ukryj dane" : "Pokaż dane";
    privacyToggle.setAttribute("aria-pressed", String(visible));
    card.querySelectorAll(".budget-sensitive").forEach((element) => {
      element.setAttribute("aria-hidden", String(!visible));
    });
  };
  privacyToggle.addEventListener("click", () => {
    card.classList.toggle("is-private");
    updatePrivacy();
  });
  updatePrivacy();
}

function render(data) {
  scheduleFinanceImportReminders(data.accountImports);
  const safe = data.safeToSpend || {};
  setText("budget-safe-to-spend", money(safe.safeToSpend));
  setText("budget-safe-daily", `${money(safe.safePerDay)} dziennie · do ${safe.horizonDate || "końca miesiąca"}`);
  setText("budget-spending", money(data.expenses));
  setText("budget-net", money(data.remainingFromIncome ?? data.netCashFlow));
  setText("budget-savings", money(data.savings));
  setText("budget-savings-rate", data.savingsRate == null ? "brak stopy" : `${data.savingsRate}% dochodu`);
  setText("budget-upcoming", money(data.upcoming30Days));
  const freshness = data.freshness || {};
  setText("budget-source-meta", freshness.latestTransactionDate
    ? `Dane do ${freshness.latestTransactionDate} · ${freshness.status}`
    : "Brak zaimportowanych transakcji");

  const goal = (data.goals || []).find((item) => item.primary) || data.goals?.[0];
  const section = document.getElementById("budget-goal");
  if (section) section.hidden = !goal;
  if (goal) {
    setText("budget-goal-name", goal.name);
    setText("budget-goal-percent", `${goal.progressPercent}%`);
    setText("budget-goal-context", `${money(goal.allocated)} z ${money(goal.target)}`);
    const fill = document.getElementById("budget-goal-progress");
    if (fill) fill.style.width = `${Math.max(0, Math.min(100, goal.progressPercent))}%`;
  }
}

async function refresh() {
  if (!card) return;
  card.classList.add("is-loading");
  try {
    render(await fetchFinanceOverview());
  } catch (error) {
    console.warn("finance widget: failed to load overview", error);
    setText("budget-source-meta", "Nie udało się pobrać danych finansowych");
  } finally {
    card.classList.remove("is-loading");
  }
}

document.getElementById("budget-reset")?.addEventListener("click", refresh);
refresh();
