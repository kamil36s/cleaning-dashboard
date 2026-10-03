import { addDashboardNotification, removeDashboardNotifications } from "./dashboard-notifications-store.js";

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
let reminderTimer;

export function financeImportAgeLabel(lastImportedAt, now = new Date()) {
  const importedAt = Date.parse(lastImportedAt || "");
  if (!Number.isFinite(importedAt)) return "brak importu";
  const elapsed = Math.max(0, now.getTime() - importedAt);
  if (elapsed < 5 * MINUTE_MS) return "teraz";
  if (elapsed < HOUR_MS) return `${Math.floor(elapsed / MINUTE_MS)} min temu`;
  if (elapsed < DAY_MS) return `${Math.floor(elapsed / HOUR_MS)} godz. temu`;
  if (elapsed < 2 * DAY_MS) return "wczoraj";
  return `${Math.floor(elapsed / DAY_MS)} dni temu`;
}

export function remindAboutFinanceImports(accounts, now = new Date()) {
  for (const account of accounts || []) {
    const importedAt = Date.parse(account.lastImportedAt || "");
    const weeks = Number.isFinite(importedAt)
      ? Math.floor(Math.max(0, now.getTime() - importedAt) / WEEK_MS)
      : 1;
    const id = `finance-import:${account.id}:${account.lastImportedAt || "none"}:${weeks}`;
    removeDashboardNotifications((item) => item.id.startsWith(`finance-import:${account.id}:`)
      && (weeks < 1 || item.id !== id));
    if (weeks < 1) continue;
    addDashboardNotification({
      id,
      category: "Finanse",
      title: `Zrób nowy import: ${account.name}`,
      message: account.lastImportedAt
        ? `Od ostatniego importu konta minęło co najmniej ${weeks * 7} dni.`
        : "To konto nie ma jeszcze importu.",
      targetId: "budget-card",
    });
  }
}

export function scheduleFinanceImportReminders(accounts, now = new Date()) {
  clearTimeout(reminderTimer);
  reminderTimer = undefined;
  remindAboutFinanceImports(accounts, now);
  const nextDelays = (accounts || []).map((account) => {
    const importedAt = Date.parse(account.lastImportedAt || "");
    if (!Number.isFinite(importedAt)) return Infinity;
    const elapsed = Math.max(0, now.getTime() - importedAt);
    return importedAt + (Math.floor(elapsed / WEEK_MS) + 1) * WEEK_MS - now.getTime();
  });
  const nextDelay = Math.min(...nextDelays);
  if (Number.isFinite(nextDelay)) {
    reminderTimer = setTimeout(() => scheduleFinanceImportReminders(accounts), Math.max(0, nextDelay));
  }
}
