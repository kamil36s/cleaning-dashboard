import { fetchFinanceBills, mutateFinanceResource } from "./budget-api.js";

const STORAGE_KEY = "todo-bills-v1";
const DAY_MS = 24 * 60 * 60 * 1000;
const BILL_CATEGORIES = new Set(["Mieszkanie", "Raty", "Subskrypcje"]);

export const BILLS_STORE_CHANGED_EVENT = "bills:store-changed";
export const BILLS_FORECAST_END_MONTH = "2027-04";

function pad(value) {
  return String(value).padStart(2, "0");
}

function toIsoDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function parseIsoDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function addDays(value, days) {
  const date = parseIsoDate(value);
  if (!date) return "";
  date.setDate(date.getDate() + days);
  return toIsoDate(date);
}

function monthKey(year, monthIndex) {
  return `${year}-${pad(monthIndex + 1)}`;
}

function monthlyBills({
  idPrefix,
  name,
  provider,
  category,
  amountCents,
  startYear,
  startMonth,
  count,
  dueDay,
  kind,
  note,
}) {
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(startYear, startMonth - 1 + index, dueDay);
    const due = toIsoDate(date);
    let reminderFrom = addDays(due, -7);
    if (kind === "rent") {
      const previousMonthLastDay = new Date(date.getFullYear(), date.getMonth(), 0);
      previousMonthLastDay.setDate(previousMonthLastDay.getDate() - 1);
      reminderFrom = toIsoDate(previousMonthLastDay);
    }
    const month = monthKey(date.getFullYear(), date.getMonth());
    return {
      id: `${idPrefix}-${month}`,
      name,
      provider,
      category,
      amountCents,
      due,
      month,
      reminderFrom,
      kind,
      note,
    };
  });
}

function fixedBill({ id, name, provider, category, amountCents, due, kind, note }) {
  return {
    id,
    name,
    provider,
    category,
    amountCents,
    due,
    month: due.slice(0, 7),
    reminderFrom: addDays(due, -7),
    kind,
    note,
  };
}

const rentBills = monthlyBills({
  idPrefix: "rent",
  name: "Najem + czynsz administracyjny",
  provider: "Mieszkanie",
  category: "Mieszkanie",
  amountCents: 257825,
  startYear: 2026,
  startMonth: 8,
  count: 9,
  dueDay: 5,
  kind: "rent",
  note: "Umowa do 30.04.2027 · płatne z góry; przypomnienie od przedostatniego dnia poprzedniego miesiąca",
});

const playBills = monthlyBills({
  idPrefix: "play-internet",
  name: "Internet",
  provider: "Play",
  category: "Mieszkanie",
  amountCents: 7699,
  startYear: 2026,
  startMonth: 8,
  count: 9,
  dueDay: 22,
  kind: "utility",
});

const gasBills = [
  ["2026-10-16", 21138],
  ["2026-12-16", 21138],
  ["2027-02-16", 21516],
  ["2027-04-16", 20381],
].map(([due, amountCents], index) => fixedBill({
  id: `orlen-gaz-${index + 1}`,
  name: "Gaz",
  provider: "PGNiG / ORLEN",
  category: "Mieszkanie",
  amountCents,
  due,
  kind: "utility",
}));

const tauronBills = [
  ["2026-09-21", 13511],
  ["2026-10-20", 13899],
  ["2026-11-20", 13511],
  ["2026-12-21", 13899],
].map(([due, amountCents], index) => fixedBill({
  id: `tauron-prad-${index + 1}`,
  name: "Prąd",
  provider: "Tauron",
  category: "Mieszkanie",
  amountCents,
  due,
  kind: "utility",
}));

const allegroBills = [
  ["2026-10-12", "1 z 2 rat"],
  ["2026-11-10", "2 z 2 rat"],
].map(([due, note], index) => fixedBill({
  id: `allegro-pay-rower-${index + 1}`,
  name: "Rower stacjonarny",
  provider: "Allegro Pay",
  category: "Raty",
  amountCents: 19450,
  due,
  kind: "installment",
  note,
}));

const santanderBills = monthlyBills({
  idPrefix: "santander-piano",
  name: "Pianino cyfrowe",
  provider: "Santander — rata",
  category: "Raty",
  amountCents: 14720,
  startYear: 2026,
  startMonth: 9,
  count: 12,
  dueDay: 11,
  kind: "installment",
}).map((bill, index) => ({ ...bill, note: `Rata ${index + 4} z 15` }));

export const SUBSCRIPTION_DEFINITIONS = Object.freeze([
  {
    id: "chatgpt",
    name: "ChatGPT",
    provider: "OpenAI",
    amountCents: 10000,
    dueDay: 17,
    overrides: {
      "2026-09": { amountCents: 48844, due: "2026-09-16" },
    },
  },
  { id: "cinema-city", name: "Cinema City Unlimited", provider: "Cinema City", amountCents: 5099, dueDay: 16 },
  { id: "spotify", name: "Spotify", provider: "Spotify", amountCents: 2699, dueDay: 8 },
  { id: "google-one", name: "Google One", provider: "Google", amountCents: 9799, dueDay: 4 },
  { id: "songsterr", name: "Songsterr", provider: "Songsterr", amountCents: 1999, dueDay: 19 },
  { id: "canal-plus", name: "Canal+", provider: "CANAL+", amountCents: 7900, dueDay: 29 },
  {
    id: "glovo-prime",
    name: "Glovo Prime",
    provider: "Glovo",
    amountCents: 1999,
    dueDay: 2,
    startMonth: "2026-09",
  },
]);

export const BILL_SCHEDULE = Object.freeze([
  ...rentBills,
  ...playBills,
  ...gasBills,
  ...tauronBills,
  ...allegroBills,
  ...santanderBills,
].sort((a, b) => a.due.localeCompare(b.due) || a.name.localeCompare(b.name)));

const DEFAULT_STATE = Object.freeze({
  paid: { "rent-2026-08": true },
  cancelledSubscriptions: {},
  customBills: [],
  notificationsEnabled: false,
});

let stateCache = null;
let localSnapshot = "";
let canonicalBillsCache = null;

function isValidIsoDate(value) {
  const date = parseIsoDate(value);
  return Boolean(date && toIsoDate(date) === value);
}

function normalizeCustomBill(raw) {
  const id = String(raw?.id || "");
  const name = String(raw?.name || "").trim().slice(0, 120);
  const provider = String(raw?.provider || "").trim().slice(0, 120);
  const category = BILL_CATEGORIES.has(raw?.category) ? raw.category : "Mieszkanie";
  const amountCents = Number(raw?.amountCents);
  const due = String(raw?.due || "");
  const recurrence = raw?.recurrence === "monthly" ? "monthly" : "once";
  const requestedEndMonth = String(raw?.endMonth || "");
  const endMonth = recurrence === "monthly"
    && /^\d{4}-(0[1-9]|1[0-2])$/.test(requestedEndMonth)
    && requestedEndMonth >= due.slice(0, 7)
    ? requestedEndMonth
    : "";

  if (!/^custom-[a-z0-9-]+$/i.test(id)) return null;
  if (!name || !Number.isInteger(amountCents) || amountCents <= 0) return null;
  if (!isValidIsoDate(due)) return null;

  return {
    id,
    name,
    provider,
    category,
    amountCents,
    due,
    recurrence,
    endMonth,
    automatic: Boolean(raw?.automatic),
  };
}

function normalizeState(raw) {
  const customBills = Array.isArray(raw?.customBills)
    ? raw.customBills.map(normalizeCustomBill).filter(Boolean)
    : [];
  const paid = raw?.paid && typeof raw.paid === "object" ? raw.paid : {};
  const cancelledSubscriptions = raw?.cancelledSubscriptions
    && typeof raw.cancelledSubscriptions === "object"
    ? raw.cancelledSubscriptions
    : {};
  const staticIds = new Set(BILL_SCHEDULE.map((bill) => bill.id));
  const subscriptionIds = new Set(SUBSCRIPTION_DEFINITIONS.map((subscription) => subscription.id));
  const customIds = customBills.map((bill) => bill.id);
  return {
    paid: Object.fromEntries(
      Object.entries(paid)
        .filter(([id, value]) => (
          staticIds.has(id)
          || /^subscription-[a-z0-9-]+-\d{4}-\d{2}$/.test(id)
          || customIds.some((customId) => (
            id === customId || new RegExp(`^${customId}-\\d{4}-\\d{2}$`).test(id)
          ))
        ) && Boolean(value))
        .map(([id]) => [id, true]),
    ),
    cancelledSubscriptions: Object.fromEntries(
      Object.entries(cancelledSubscriptions)
        .filter(([id, value]) => subscriptionIds.has(id) && Boolean(value))
        .map(([id]) => [id, true]),
    ),
    customBills,
    notificationsEnabled: Boolean(raw?.notificationsEnabled),
  };
}

function readLocalSnapshot() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function readLocalState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? normalizeState(JSON.parse(raw)) : normalizeState(DEFAULT_STATE);
  } catch {
    return normalizeState(DEFAULT_STATE);
  }
}

function writeLocalState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    localSnapshot = readLocalSnapshot();
  } catch {}
}

function emitChanged() {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  window.dispatchEvent(new CustomEvent(BILLS_STORE_CHANGED_EVENT));
}

async function hydrateFromServer() {
  const payload = await fetchFinanceBills();
  const previous = JSON.stringify(canonicalBillsCache);
  canonicalBillsCache = Array.isArray(payload?.bills) ? payload.bills : [];
  const current = getBillsState();
  stateCache = { ...current, notificationsEnabled: Boolean(payload?.notificationsEnabled) };
  writeLocalState(stateCache);
  if (JSON.stringify(canonicalBillsCache) !== previous) emitChanged();
}

hydrateFromServer().catch(() => {});

export function getBillsState() {
  const snapshot = readLocalSnapshot();
  if (stateCache && snapshot === localSnapshot) return normalizeState(stateCache);
  stateCache = readLocalState();
  localSnapshot = snapshot;
  return normalizeState(stateCache);
}

function saveState(next) {
  stateCache = normalizeState(next);
  writeLocalState(stateCache);
  emitChanged();
  return getBillsState();
}

function syncCanonical(resource, payload) {
  mutateFinanceResource(resource, payload)
    .then(() => hydrateFromServer())
    .catch((error) => console.warn("bills store: canonical sync failed", error));
}

function buildSubscriptionBills(now = new Date()) {
  const baseStart = new Date(2026, 7, 1);
  const fixedScheduleEnd = new Date(2027, 7, 1);
  const currentMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  const start = currentMonth > fixedScheduleEnd
    ? new Date(now.getFullYear(), now.getMonth() - 1, 1)
    : baseStart;
  const rollingEnd = new Date(now.getFullYear(), now.getMonth() + 12, 1);
  const end = rollingEnd > fixedScheduleEnd ? rollingEnd : fixedScheduleEnd;
  const bills = [];

  for (const cursor = new Date(start); cursor <= end; cursor.setMonth(cursor.getMonth() + 1)) {
    const year = cursor.getFullYear();
    const monthIndex = cursor.getMonth();
    const month = monthKey(year, monthIndex);
    const lastDay = new Date(year, monthIndex + 1, 0).getDate();
    SUBSCRIPTION_DEFINITIONS.forEach((subscription) => {
      if (subscription.startMonth && month < subscription.startMonth) return;
      const dueDay = Math.min(subscription.dueDay, lastDay);
      const override = subscription.overrides?.[month];
      const due = override?.due || toIsoDate(new Date(year, monthIndex, dueDay));
      bills.push({
        id: `subscription-${subscription.id}-${month}`,
        subscriptionId: subscription.id,
        name: subscription.name,
        provider: subscription.provider,
        category: "Subskrypcje",
        amountCents: override?.amountCents || subscription.amountCents,
        due,
        month,
        reminderFrom: due,
        kind: "subscription",
        automatic: true,
      });
    });
  }
  return bills;
}

function buildCustomBills(now = new Date()) {
  const rollingEndDate = new Date(now.getFullYear(), now.getMonth() + 12, 1);
  const rollingEnd = monthKey(rollingEndDate.getFullYear(), rollingEndDate.getMonth());
  const defaultEndMonth = rollingEnd > BILLS_FORECAST_END_MONTH
    ? rollingEnd
    : BILLS_FORECAST_END_MONTH;
  const bills = [];

  getBillsState().customBills.forEach((definition) => {
    const common = {
      customId: definition.id,
      name: definition.name,
      provider: definition.provider,
      category: definition.category,
      amountCents: definition.amountCents,
      kind: "custom",
      automatic: definition.automatic,
    };

    if (definition.recurrence !== "monthly") {
      bills.push({
        ...common,
        id: definition.id,
        due: definition.due,
        month: definition.due.slice(0, 7),
        reminderFrom: addDays(definition.due, -7),
      });
      return;
    }

    const startDate = parseIsoDate(definition.due);
    const dueDay = startDate.getDate();
    const dueRollingEndDate = new Date(startDate.getFullYear(), startDate.getMonth() + 12, 1);
    const dueRollingEnd = monthKey(dueRollingEndDate.getFullYear(), dueRollingEndDate.getMonth());
    const endMonth = definition.endMonth
      || (dueRollingEnd > defaultEndMonth ? dueRollingEnd : defaultEndMonth);
    for (
      const cursor = new Date(startDate.getFullYear(), startDate.getMonth(), 1);
      monthKey(cursor.getFullYear(), cursor.getMonth()) <= endMonth;
      cursor.setMonth(cursor.getMonth() + 1)
    ) {
      const year = cursor.getFullYear();
      const monthIndex = cursor.getMonth();
      const month = monthKey(year, monthIndex);
      const lastDay = new Date(year, monthIndex + 1, 0).getDate();
      const due = toIsoDate(new Date(year, monthIndex, Math.min(dueDay, lastDay)));
      bills.push({
        ...common,
        id: `${definition.id}-${month}`,
        due,
        month,
        reminderFrom: addDays(due, -7),
      });
    }
  });

  return bills;
}

export function listBills(now = new Date()) {
  if (canonicalBillsCache) {
    return canonicalBillsCache
      .map((bill) => ({ ...bill }))
      .sort((a, b) => a.due.localeCompare(b.due) || a.name.localeCompare(b.name));
  }
  const state = getBillsState();
  const subscriptionBills = buildSubscriptionBills(now)
    .filter((bill) => !state.cancelledSubscriptions[bill.subscriptionId]);
  return [...BILL_SCHEDULE, ...subscriptionBills, ...buildCustomBills(now)]
    .map((bill) => ({ ...bill, paid: Boolean(state.paid[bill.id]) }))
    .sort((a, b) => a.due.localeCompare(b.due) || a.name.localeCompare(b.name));
}

export function addCustomBill(values) {
  const generatedId = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const bill = normalizeCustomBill({ ...values, id: `custom-${generatedId}` });
  if (!bill) return null;
  const state = getBillsState();
  saveState({ ...state, customBills: [...state.customBills, bill] });
  canonicalBillsCache = null;
  syncCanonical("obligations", {
    name: bill.name,
    provider: bill.provider,
    group: bill.category,
    amountMinor: bill.amountCents,
    kind: "bill",
    cadence: bill.recurrence === "monthly" ? "monthly" : "once",
    startDate: bill.due,
    nextExpectedDate: bill.due,
    endDate: bill.endMonth ? `${bill.endMonth}-28` : null,
    dueDay: Number(bill.due.slice(-2)),
    automatic: bill.automatic,
    confirmed: true,
  });
  return bill;
}

export function removeCustomBill(id) {
  if (canonicalBillsCache?.some((bill) => bill.customId === id || bill.obligationId === id)) {
    canonicalBillsCache = canonicalBillsCache.filter((bill) => bill.customId !== id && bill.obligationId !== id);
    syncCanonical("deactivate-obligation", { id });
    emitChanged();
    return true;
  }
  const state = getBillsState();
  if (!state.customBills.some((bill) => bill.id === id)) return false;
  const paid = Object.fromEntries(
    Object.entries(state.paid).filter(([paidId]) => (
      paidId !== id && !paidId.startsWith(`${id}-`)
    )),
  );
  saveState({
    ...state,
    paid,
    customBills: state.customBills.filter((bill) => bill.id !== id),
  });
  return true;
}

export function setBillPaid(id, paid) {
  if (!listBills().some((bill) => bill.id === id)) return null;
  if (canonicalBillsCache) {
    canonicalBillsCache = canonicalBillsCache.map((bill) => bill.id === id ? { ...bill, paid: Boolean(paid) } : bill);
    syncCanonical("occurrence-status", { id, status: paid ? "paid" : "expected" });
    emitChanged();
    return listBills().find((bill) => bill.id === id) || null;
  }
  const state = getBillsState();
  const nextPaid = { ...state.paid };
  if (paid) nextPaid[id] = true;
  else delete nextPaid[id];
  saveState({ ...state, paid: nextPaid });
  return listBills().find((bill) => bill.id === id) || null;
}

export function cancelSubscription(subscriptionId) {
  if (canonicalBillsCache) {
    if (!canonicalBillsCache.some((bill) => bill.subscriptionId === subscriptionId || bill.obligationId === subscriptionId)) return false;
    canonicalBillsCache = canonicalBillsCache.filter((bill) => bill.subscriptionId !== subscriptionId && bill.obligationId !== subscriptionId);
    syncCanonical("deactivate-obligation", { id: subscriptionId });
    emitChanged();
    return true;
  }
  if (!SUBSCRIPTION_DEFINITIONS.some((subscription) => subscription.id === subscriptionId)) return false;
  const state = getBillsState();
  saveState({
    ...state,
    cancelledSubscriptions: {
      ...state.cancelledSubscriptions,
      [subscriptionId]: true,
    },
  });
  return true;
}

export function setBillsNotificationsEnabled(enabled) {
  const state = getBillsState();
  const next = saveState({ ...state, notificationsEnabled: Boolean(enabled) });
  syncCanonical("bills-notifications", { enabled: Boolean(enabled) });
  return next;
}

export function formatMoney(amountCents) {
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency: "PLN",
    minimumFractionDigits: 2,
  }).format(amountCents / 100);
}

export function formatBillDate(iso) {
  const date = parseIsoDate(iso);
  if (!date) return "";
  return new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
}

export function getBillStatus(bill, now = new Date()) {
  if (bill?.paid) {
    return { key: "paid", label: "Opłacone", days: null, daysLabel: "opłacone" };
  }
  const dueDate = parseIsoDate(bill?.due);
  if (!dueDate) return { key: "upcoming", label: "Zaplanowane", days: null, daysLabel: "" };
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((dueDate - today) / DAY_MS);
  let daysLabel;
  if (days < 0) daysLabel = `${Math.abs(days)} ${Math.abs(days) === 1 ? "dzień" : "dni"} po terminie`;
  else if (days === 0) daysLabel = "termin dzisiaj";
  else if (days === 1) daysLabel = "został 1 dzień";
  else daysLabel = `zostało ${days} dni`;

  if (bill.automatic) {
    return { key: "automatic", label: "Automatyczna", days, daysLabel };
  }

  if (days < 0) return { key: "overdue", label: "Po terminie", days, daysLabel };

  const reminderDate = parseIsoDate(bill.reminderFrom);
  const reminderActive = reminderDate ? today >= reminderDate : days <= 7;
  const critical = bill.kind === "rent" ? days <= 4 : days <= 3;
  if (critical) return { key: "critical", label: "Krytyczne", days, daysLabel };
  if (reminderActive) return { key: "attention", label: "Pora zapłacić", days, daysLabel };
  return { key: "upcoming", label: "Zaplanowane", days, daysLabel };
}

export function getMonthlyBillSummaries(bills = listBills()) {
  const groups = new Map();
  bills.forEach((bill) => {
    const summary = groups.get(bill.month) || {
      month: bill.month,
      plannedCents: 0,
      remainingCents: 0,
      paidCount: 0,
      totalCount: 0,
      categoryTotals: {
        Mieszkanie: 0,
        Raty: 0,
        Subskrypcje: 0,
      },
    };
    summary.plannedCents += bill.amountCents;
    if (summary.categoryTotals[bill.category] !== undefined) {
      summary.categoryTotals[bill.category] += bill.amountCents;
    }
    if (!bill.paid) summary.remainingCents += bill.amountCents;
    if (bill.paid) summary.paidCount += 1;
    summary.totalCount += 1;
    groups.set(bill.month, summary);
  });
  return [...groups.values()].sort((a, b) => a.month.localeCompare(b.month));
}

export function getTotalOutstandingCents(
  bills = listBills(),
  endMonth = BILLS_FORECAST_END_MONTH,
) {
  return bills.reduce((total, bill) => {
    if (bill.paid) return total;
    if (bill.month > endMonth) return total;
    return total + bill.amountCents;
  }, 0);
}

export function getAverageMonthlyPlannedCents(
  bills,
  startMonth,
  endMonth = BILLS_FORECAST_END_MONTH,
) {
  const summaries = getMonthlyBillSummaries(bills)
    .filter((summary) => summary.month >= startMonth && summary.month <= endMonth);
  if (!summaries.length) return 0;
  const total = summaries.reduce((sum, summary) => sum + summary.plannedCents, 0);
  return Math.round(total / summaries.length);
}

export function getAverageMonthlyRemainingCents(
  bills,
  startMonth,
  endMonth = BILLS_FORECAST_END_MONTH,
) {
  const summaries = getMonthlyBillSummaries(bills)
    .filter((summary) => summary.month >= startMonth && summary.month <= endMonth);
  if (!summaries.length) return 0;
  const total = summaries.reduce((sum, summary) => sum + summary.remainingCents, 0);
  return Math.round(total / summaries.length);
}

export function getBillsRequiringAttention(bills = listBills(), now = new Date()) {
  return bills
    .map((bill) => ({ bill, status: getBillStatus(bill, now) }))
    .filter(({ status }) => ["attention", "critical", "overdue"].includes(status.key))
    .sort((a, b) => a.bill.due.localeCompare(b.bill.due));
}

export function getNextUnpaidManualBill(bills = listBills(), now = new Date()) {
  return bills
    .filter((bill) => !bill.paid && !bill.automatic)
    .map((bill) => ({ bill, status: getBillStatus(bill, now) }))
    .filter(({ status }) => status.days >= 0)
    .sort((a, b) => a.bill.due.localeCompare(b.bill.due))[0] || null;
}
