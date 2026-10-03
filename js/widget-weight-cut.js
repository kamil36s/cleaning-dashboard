import { loadTimeSuffix, startLoadTimer } from "./load-timing.js";
import { openDatePopover } from "./date-popover.js";
import {
  generateCombinedDailyReport,
  generateStepsDailyReport,
  generateWeightDailyReport,
} from "./daily-report.js";
import { escapeHtml } from "./utils.js";
import { setDailyAchievement } from "./daily-achievements.js";
import { calculateMa7Stats, WEIGHT_MA_TARGET_KG } from "./weight-ma-stats.js";
import { liveWorkoutRuntimeUrl } from "./live-workout-runtime-api.js";
import {
  buildCardioCalorieChartSeries,
  buildCardioCaloriePeriodSeries,
  normalizeCyclingCalorieRanking,
  summarizeCardioCalorieTrend,
} from "./live-workout-ranking.js";

const STORAGE_KEY = "weightCut.tiles.v1";
const GOALS_STORAGE_KEY = "weightCut.goals.v1";
const MA_TARGET_STORAGE_KEY = "weightCut.maTarget.v1";
const DEFAULT_WEIGHT_GOALS = [89, 83, 79, 75, 69];
const WEIGHT_RATE_START_DAY = "2026-05-01";
const WEIGHT_MA_RATE_START_DAY = "2026-08-20";
const FALLBACK_WEIGHT_KG = 96.5;
const REALISTIC_WEIGHT_MIN_KG = 30;
const REALISTIC_WEIGHT_MAX_KG = 300;
const STEP_LENGTH_KM = 0.00075;
const WALK_KCAL_PER_KG_KM = 0.53;
const LIVE_WEIGHT_ENDPOINT = "/api/weight/latest";
const SIGNAL_ENDPOINT = "/api/weight/signal";
const HISTORY_ALL_VALUE = "all";
const HISTORY_DAY_OPTIONS = [30, 90, 180, 365];
const HISTORY_PERIOD_OPTIONS = {
  weekly: [91, 182],
  biweekly: [182, 365],
  monthly: [365, 730, 1095, HISTORY_ALL_VALUE],
};
const DEFAULT_HISTORY_DAYS = 30;
const DEFAULT_PERIOD_HISTORY_DAYS = {
  weekly: 91,
  biweekly: 365,
  monthly: 365,
};
const PERIOD_DAYS = {
  weekly: 7,
  biweekly: 14,
  monthly: 30,
};
const HISTORY_ENDPOINT = "/api/weight/history";
const EVENTS_ENDPOINT = "/api/weight/events";
const DELETE_EVENT_ENDPOINT = "/api/weight/events/delete";
const STATS_ENDPOINT = "/api/weight/stats";
const DASHBOARD_SUMMARY_ENDPOINT = "/api/weight/dashboard-summary";
const STEPS_HISTORY_ENDPOINT = "/api/steps/history";
const STEPS_EVENTS_ENDPOINT = "/api/steps/events";
const STEPS_STREAM_ENDPOINT = "/api/steps/stream";
const HEALTH_LATEST_ENDPOINT = "/api/health-connect/latest";
const UPSERT_STEPS_ENDPOINT = "/api/steps/events/upsert";
const DELETE_STEPS_ENDPOINT = "/api/steps/events/delete";
const CARDIO_RANKING_ENDPOINT = liveWorkoutRuntimeUrl("calorie-ranking");
const LIVE_POLL_MS = 2500;
const STEPS_POLL_MS = 60000;
const MONTH_SHORT_PL = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paz", "lis", "gru"];
const WEIGHT_CHART_ANNOTATIONS = [
  {
    type: "event",
    startDay: "2026-05-01",
    label: "Przeprowadzka + decyzja o powrocie do dawnej wagi",
  },
  {
    type: "range",
    startDay: "2026-07-13",
    endDay: "2026-07-18",
    label: "Wyjazd do Włoch",
  },
  {
    type: "range",
    startDay: "2026-08-04",
    endDay: "2026-08-09",
    label: "Brutal Assault",
  },
  {
    type: "event",
    startDay: "2026-08-20",
    label: "Zakup rowerka i początek treningów",
  },
];

const root = document.getElementById("weight-cut-root");

function todayIso(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function timestampDay(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : todayIso(date);
}

function addDaysIso(day, amount) {
  const date = new Date(`${day}T12:00:00`);
  if (Number.isNaN(date.getTime())) return todayIso();
  date.setDate(date.getDate() + amount);
  return todayIso(date);
}

function isoDateObject(day) {
  const date = new Date(`${day}T12:00:00`);
  return Number.isNaN(date.getTime()) ? new Date(`${todayIso()}T12:00:00`) : date;
}

function daysBetweenIso(startDay, endDay) {
  return Math.round((isoDateObject(endDay) - isoDateObject(startDay)) / 86400000);
}

function isSameOrAfterToday(day) {
  return day >= todayIso();
}

function readNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).trim().replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function realisticWeightKg(value) {
  const weightKg = readNumber(value);
  return Number.isFinite(weightKg)
    && weightKg >= REALISTIC_WEIGHT_MIN_KG
    && weightKg <= REALISTIC_WEIGHT_MAX_KG
    ? weightKg
    : null;
}

function loadMaTargetKg() {
  try {
    return realisticWeightKg(localStorage.getItem(MA_TARGET_STORAGE_KEY)) ?? WEIGHT_MA_TARGET_KG;
  } catch {
    return WEIGHT_MA_TARGET_KG;
  }
}

function saveMaTargetKg(value) {
  const target = realisticWeightKg(value);
  if (!Number.isFinite(target)) return null;
  const normalized = Math.round(target * 10) / 10;
  try {
    localStorage.setItem(MA_TARGET_STORAGE_KEY, String(normalized));
  } catch {}
  return normalized;
}

function normalizeGoalTargets(raw = DEFAULT_WEIGHT_GOALS) {
  const source = Array.isArray(raw) ? raw : DEFAULT_WEIGHT_GOALS;
  return Array.from(new Set(
    source
      .map((value) => readNumber(value))
      .filter((value) => Number.isFinite(value) && value > 0)
      .map((value) => Math.round(value * 10) / 10),
  )).sort((a, b) => b - a);
}

function loadGoalTargets() {
  try {
    const saved = JSON.parse(localStorage.getItem(GOALS_STORAGE_KEY) || "null");
    return normalizeGoalTargets(saved);
  } catch {
    return normalizeGoalTargets();
  }
}

function saveGoalTargets(nextTargets) {
  const normalized = normalizeGoalTargets(nextTargets);
  try {
    localStorage.setItem(GOALS_STORAGE_KEY, JSON.stringify(normalized));
  } catch {}
  return normalized;
}

function normalizeStore(raw = {}) {
  const days = raw && typeof raw === "object" && raw.days ? raw.days : {};
  return {
    weightKg: realisticWeightKg(raw?.weightKg),
    days: Object.fromEntries(
      Object.entries(days).map(([date, day]) => [
        date,
        { steps: Math.max(0, Math.round(readNumber(day?.steps) || 0)) },
      ]),
    ),
  };
}

function loadStore() {
  try {
    return normalizeStore(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"));
  } catch {
    return normalizeStore();
  }
}

function saveStore(nextStore) {
  const normalized = normalizeStore(nextStore);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  } catch {}
  return normalized;
}

function formatKg(value) {
  return Number.isFinite(value) ? `${value.toFixed(2).replace(".", ",")} kg` : "-";
}

function formatDeltaCompact(value) {
  if (!Number.isFinite(value)) return "";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2).replace(".", ",")} kg`;
}

function formatSignedKg(value) {
  if (!Number.isFinite(value)) return "brak danych";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2).replace(".", ",")} kg`;
}

function formatRate(value) {
  if (!Number.isFinite(value)) return "brak danych";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2).replace(".", ",")} kg/tydz.`;
}

function formatInt(value) {
  return Math.round(Number(value) || 0).toLocaleString("pl-PL");
}

function formatAge(value) {
  if (!Number.isFinite(value)) return "";
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return `${seconds}s temu`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min temu`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} godz temu`;
  const days = Math.round(hours / 24);
  return `${days} dni temu`;
}

function formatShortDate(day) {
  const parts = String(day || "").split("-");
  if (parts.length !== 3) return "";
  const month = MONTH_SHORT_PL[Math.max(0, Math.min(11, Number(parts[1]) - 1))] || parts[1];
  return `${parts[2]} ${month}`;
}

function formatShortDateWithYear(day) {
  const parts = String(day || "").split("-");
  if (parts.length !== 3) return "";
  return `${formatShortDate(day)} ${parts[0]}`;
}

function formatGoalWeight(value) {
  if (!Number.isFinite(value)) return "";
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(".", ",");
}

function formatGoalDate(day) {
  const formatted = formatShortDateWithYear(day);
  return formatted.replace(/^0/, "");
}

function addMonthsClamped(date, amount) {
  const next = new Date(date);
  const originalDay = next.getDate();
  next.setDate(1);
  next.setMonth(next.getMonth() + amount);
  const lastDay = new Date(next.getFullYear(), next.getMonth() + 1, 0).getDate();
  next.setDate(Math.min(originalDay, lastDay));
  return next;
}

function diffMonthsDays(startDay, endDay) {
  const start = isoDateObject(startDay);
  const end = isoDateObject(endDay);
  if (end <= start) return { months: 0, days: 0 };

  let months = (end.getFullYear() - start.getFullYear()) * 12 + end.getMonth() - start.getMonth();
  if (addMonthsClamped(start, months) > end) months -= 1;

  const anchor = addMonthsClamped(start, Math.max(0, months));
  const days = Math.max(0, Math.round((end - anchor) / 86400000));
  return { months: Math.max(0, months), days };
}

function formatGoalDuration(duration) {
  if (!duration) return "brak danych";
  const months = Math.max(0, Math.round(duration.months || 0));
  const weeks = Math.floor(Math.max(0, Math.round(duration.days || 0)) / 7);
  if (!months && !weeks) return "poniżej tyg.";
  return [
    months ? `${months} mies.` : "",
    weeks ? `${weeks} tyg.` : "",
  ].filter(Boolean).join(" ");
}

function formatDateInputPl(day) {
  const parts = String(day || "").split("-");
  if (parts.length !== 3) return "";
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

function parseStepDayInput(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";

  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return raw;

  const numeric = raw.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/);
  if (numeric) {
    const day = numeric[1].padStart(2, "0");
    const month = numeric[2].padStart(2, "0");
    const year = numeric[3];
    const isoDay = `${year}-${month}-${day}`;
    const parsed = new Date(`${isoDay}T12:00:00`);
    if (!Number.isNaN(parsed.getTime()) && todayIso(parsed) === isoDay) return isoDay;
  }

  const named = raw.toLowerCase().match(/^(\d{1,2})\s+([a-ząćęłńóśźż]{3})\s+(\d{4})$/i);
  if (named) {
    const monthIndex = MONTH_SHORT_PL.indexOf(named[2]);
    if (monthIndex >= 0) {
      const day = named[1].padStart(2, "0");
      const month = String(monthIndex + 1).padStart(2, "0");
      const isoDay = `${named[3]}-${month}-${day}`;
      const parsed = new Date(`${isoDay}T12:00:00`);
      if (!Number.isNaN(parsed.getTime()) && todayIso(parsed) === isoDay) return isoDay;
    }
  }

  return "";
}

function formatDateRange(rows) {
  if (!rows.length) return "";
  const first = rows[0].periodStart || rows[0].day;
  const last = rows[rows.length - 1].periodEnd || rows[rows.length - 1].day;
  return `${formatShortDateWithYear(first)} - ${formatShortDateWithYear(last)}`;
}

function formatWeekRange(startDay, endDay) {
  if (!startDay || !endDay) return "";
  return `${formatShortDateWithYear(startDay)} - ${formatShortDateWithYear(endDay)}`;
}

function formatHistoryOption(days, mode = "daily") {
  if (days === HISTORY_ALL_VALUE) return "cały zakres";
  if (mode === "weekly") {
    if (days === 91) return "3 mies.";
    if (days === 182) return "6 mies.";
  }
  if (mode === "biweekly") {
    if (days === 182) return "6 mies.";
    if (days === 365) return "rok";
  }
  if (mode === "monthly") {
    if (days === 365) return "rok";
    if (days === 730) return "2 lata";
    if (days === 1095) return "3 lata";
  }
  return `${days} dni`;
}

function isAllHistoryRange(value) {
  return value === HISTORY_ALL_VALUE;
}

function isPeriodChartMode(mode = weightChartMode) {
  return mode !== "daily";
}

function getPeriodHistoryDays(mode = weightChartMode) {
  return periodHistoryDays[mode] || DEFAULT_PERIOD_HISTORY_DAYS[mode] || DEFAULT_HISTORY_DAYS;
}

function setPeriodHistoryDays(mode, days) {
  if (!DEFAULT_PERIOD_HISTORY_DAYS[mode]) return;
  periodHistoryDays = { ...periodHistoryDays, [mode]: days };
}

function getActiveHistoryDays() {
  return isPeriodChartMode() ? getPeriodHistoryDays() : historyDays;
}

function getActiveHistoryOptions() {
  return isPeriodChartMode() ? HISTORY_PERIOD_OPTIONS[weightChartMode] || [] : HISTORY_DAY_OPTIONS;
}

function getChartTitle() {
  if (weightChartMode === "weekly") return "Średnia tygodniowa";
  if (weightChartMode === "biweekly") return "Średnia 2-tygodniowa";
  if (weightChartMode === "monthly") return "Średnia miesięczna";
  return "Średnia dzienna";
}

function getChartHistoryUnit() {
  if (weightChartMode === "weekly") return "tyg.";
  if (weightChartMode === "biweekly") return "okr.";
  if (weightChartMode === "monthly") return "mies.";
  return "dni";
}

function getChartPointKind(point) {
  if (point.filled) return "dummy";
  if (weightChartMode === "weekly") return `${point.count} pom. / tydz.`;
  if (weightChartMode === "biweekly") return `${point.count} pom. / 2 tyg.`;
  if (weightChartMode === "monthly") return `${point.count} pom. / mies.`;
  return `${point.count} pom.`;
}

function isStepsPeriodChartMode(mode = stepsChartMode) {
  return mode !== "daily";
}

function getStepsPeriodHistoryDays(mode = stepsChartMode) {
  return stepsPeriodHistoryDays[mode] || DEFAULT_PERIOD_HISTORY_DAYS[mode] || DEFAULT_HISTORY_DAYS;
}

function setStepsPeriodHistoryDays(mode, days) {
  if (!DEFAULT_PERIOD_HISTORY_DAYS[mode]) return;
  stepsPeriodHistoryDays = { ...stepsPeriodHistoryDays, [mode]: days };
}

function getActiveStepsHistoryDays() {
  return isStepsPeriodChartMode() ? getStepsPeriodHistoryDays() : stepsHistoryDays;
}

function getActiveStepsHistoryOptions() {
  return isStepsPeriodChartMode() ? HISTORY_PERIOD_OPTIONS[stepsChartMode] || [] : HISTORY_DAY_OPTIONS;
}

function getStepsChartTitle() {
  if (stepsChartMode === "weekly") return "Kroki tygodniowe";
  if (stepsChartMode === "biweekly") return "Kroki 2-tygodniowe";
  if (stepsChartMode === "monthly") return "Kroki miesięczne";
  return "Kroki dzienne";
}

function getStepsChartHistoryUnit() {
  if (stepsChartMode === "weekly") return "tyg.";
  if (stepsChartMode === "biweekly") return "okr.";
  if (stepsChartMode === "monthly") return "mies.";
  return "dni";
}

function getStepsPointKind(point, weightKg) {
  if (point.filled) return "brak danych";
  const kcal = estimateStepKcal(point.steps, weightKg || FALLBACK_WEIGHT_KG);
  if (point.periodStart && point.periodEnd) {
    return `${formatInt(point.count)} dni z krokami | ~${formatInt(kcal)} kcal/dz.`;
  }
  return `~${formatInt(kcal)} kcal`;
}

function isCardioPeriodChartMode(mode = cardioChartMode) {
  return mode !== "daily";
}

function getCardioPeriodHistoryDays(mode = cardioChartMode) {
  return cardioPeriodHistoryDays[mode] || DEFAULT_PERIOD_HISTORY_DAYS[mode] || DEFAULT_HISTORY_DAYS;
}

function setCardioPeriodHistoryDays(mode, days) {
  if (!DEFAULT_PERIOD_HISTORY_DAYS[mode]) return;
  cardioPeriodHistoryDays = { ...cardioPeriodHistoryDays, [mode]: days };
}

function getActiveCardioHistoryDays() {
  return isCardioPeriodChartMode() ? getCardioPeriodHistoryDays() : cardioHistoryDays;
}

function getActiveCardioHistoryOptions() {
  return isCardioPeriodChartMode() ? HISTORY_PERIOD_OPTIONS[cardioChartMode] || [] : HISTORY_DAY_OPTIONS;
}

function getCardioChartTitle() {
  if (cardioChartMode === "weekly") return "Średnie kcal cardio · tydzień";
  if (cardioChartMode === "biweekly") return "Średnie kcal cardio · 2 tygodnie";
  if (cardioChartMode === "monthly") return "Średnie kcal cardio · miesiąc";
  return "Dzienne kcal cardio";
}

function getCardioDayCount() {
  const activeDays = getActiveCardioHistoryDays();
  if (!isAllHistoryRange(activeDays)) return Math.max(1, Math.round(Number(activeDays) || DEFAULT_HISTORY_DAYS));
  const firstDay = cardioRanking.map((day) => day.date).sort()[0];
  return firstDay ? Math.max(1, daysBetweenIso(firstDay, cardioChartEndDay) + 1) : DEFAULT_HISTORY_DAYS;
}

function rebuildCardioHistory() {
  const dayCount = getCardioDayCount();
  const rows = isCardioPeriodChartMode()
    ? buildCardioCaloriePeriodSeries(cardioRanking, {
      endDate: cardioChartEndDay,
      dayCount,
      periodDays: PERIOD_DAYS[cardioChartMode] || 7,
    })
    : buildCardioCalorieChartSeries(cardioRanking, {
      endDate: cardioChartEndDay,
      dayCount,
    });
  cardioHistory = rows.map((row) => ({ ...row, day: row.date }));
}

function getDailyReportDays(days, fallback = DEFAULT_HISTORY_DAYS) {
  return isAllHistoryRange(days) ? HISTORY_ALL_VALUE : Math.max(1, Math.round(readNumber(days) || fallback));
}

function maxDailyReportDays(...days) {
  if (days.some((day) => isAllHistoryRange(day))) return HISTORY_ALL_VALUE;
  return Math.max(...days.map((day) => Math.max(1, Math.round(readNumber(day) || DEFAULT_HISTORY_DAYS))));
}

function latestReportEnd(...days) {
  return days
    .filter((day) => /^\d{4}-\d{2}-\d{2}$/.test(String(day || "")))
    .sort((a, b) => b.localeCompare(a))[0] || todayIso();
}

function formatChartDay(day) {
  const date = new Date(`${day}T12:00:00`);
  if (Number.isNaN(date.getTime())) return day;
  const weekday = date.toLocaleDateString("pl-PL", { weekday: "short" });
  return `${weekday}, ${formatShortDateWithYear(day)}`;
}

function formatMeasurementTime(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";

  const today = new Date();
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const daysAgo = Math.round((startToday - startDate) / 86400000);
  const time = date.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });

  if (daysAgo === 0) return `dzisiaj, ${time}`;
  if (daysAgo === 1) return `wczoraj, ${time}`;
  return `${daysAgo} dni temu`;
}

function formatFullTimestamp(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return String(timestamp);
  const day = String(date.getDate()).padStart(2, "0");
  const month = MONTH_SHORT_PL[date.getMonth()];
  const time = date.toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${day} ${month} ${date.getFullYear()}, ${time}`;
}

function estimateStepKcal(steps, weightKg) {
  const distanceKm = steps * STEP_LENGTH_KM;
  return Math.round(distanceKm * weightKg * WALK_KCAL_PER_KG_KM);
}

function normalizeLiveWeight(payload) {
  const weightKg = realisticWeightKg(payload?.weight_kg);
  if (!payload?.ok || !Number.isFinite(weightKg)) return null;
  return {
    weightKg,
    timestamp: payload.timestamp || null,
    rssi: Number.isFinite(Number(payload.rssi)) ? Number(payload.rssi) : null,
    signalPercent: Number.isFinite(Number(payload.signal_percent)) ? Number(payload.signal_percent) : null,
    stable: payload.stable !== false,
  };
}

function normalizeSignal(payload) {
  if (!payload?.ok) return null;
  const rssi = Number(payload.rssi);
  const signalPercent = Number(payload.signal_percent);
  return {
    timestamp: payload.timestamp || null,
    rssi: Number.isFinite(rssi) ? rssi : null,
    signalPercent: Number.isFinite(signalPercent) ? Math.max(0, Math.min(100, Math.round(signalPercent))) : null,
    ageSeconds: Number.isFinite(Number(payload.age_seconds)) ? Number(payload.age_seconds) : null,
  };
}

function normalizeHistory(payload) {
  const rows = Array.isArray(payload?.daily) ? payload.daily : [];
  return rows
    .map((row) => ({
      day: String(row.day || ""),
      avgWeightKg: realisticWeightKg(row.avg_weight_kg),
      count: Math.max(0, Math.round(readNumber(row.count) || 0)),
      filled: row.filled === true,
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day) && Number.isFinite(row.avgWeightKg));
}

function normalizeEvents(payload) {
  const rows = Array.isArray(payload?.events) ? payload.events : [];
  return rows
    .map((row) => ({
      timestamp: String(row.timestamp || ""),
      weightKg: realisticWeightKg(row.weight_kg),
      rssi: row.rssi === null || row.rssi === undefined || row.rssi === ""
        ? null
        : Number.isFinite(Number(row.rssi))
          ? Number(row.rssi)
          : null,
      type: row.type || "",
      unit: row.unit || "kg",
    }))
    .filter((row) => row.timestamp && Number.isFinite(row.weightKg));
}

function interpolatedWeightForDate(points, targetDate) {
  if (!points.length) return null;

  let previousPoint = null;
  let nextPoint = null;
  const targetTime = targetDate.getTime();

  for (const point of points) {
    const pointTime = point.date.getTime();
    if (pointTime === targetTime) return point.avgWeightKg;
    if (pointTime < targetTime) {
      previousPoint = point;
    } else {
      nextPoint = point;
      break;
    }
  }

  if (previousPoint && nextPoint) {
    const totalDays = Math.max(1, (nextPoint.date - previousPoint.date) / 86400000);
    const elapsedDays = (targetDate - previousPoint.date) / 86400000;
    return previousPoint.avgWeightKg + (nextPoint.avgWeightKg - previousPoint.avgWeightKg) * (elapsedDays / totalDays);
  }
  if (previousPoint) return previousPoint.avgWeightKg;
  if (nextPoint) return nextPoint.avgWeightKg;
  return null;
}

function buildPeriodWeightHistory(events, limitDays, endDay, periodDays = 7) {
  const end = isoDateObject(endDay);
  const today = isoDateObject(todayIso());
  if (end > today) end.setTime(today.getTime());
  const normalizedEvents = events
    .map((event) => {
      const day = String(event.timestamp || "").slice(0, 10);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(event.weightKg)) return null;
      return { ...event, day, date: isoDateObject(day) };
    })
    .filter(Boolean);
  const dailyGroups = new Map();
  normalizedEvents.forEach((event) => {
    const group = dailyGroups.get(event.day) || { day: event.day, date: event.date, weights: [] };
    group.weights.push(event.weightKg);
    dailyGroups.set(event.day, group);
  });
  const dailyAverages = Array.from(dailyGroups.values()).map((group) => ({
    day: group.day,
    date: group.date,
    avgWeightKg: group.weights.reduce((sum, value) => sum + value, 0) / group.weights.length,
    count: group.weights.length,
  })).sort((a, b) => a.date - b.date);
  const dailyByDay = new Map(dailyAverages.map((item) => [item.day, item]));
  const firstDataDate = dailyAverages[0]?.date || null;
  const allRange = isAllHistoryRange(limitDays);
  const spanDays = firstDataDate
    ? Math.max(periodDays, Math.floor((end - firstDataDate) / 86400000) + 1)
    : periodDays;
  const periods = allRange
    ? Math.max(1, Math.ceil(spanDays / periodDays))
    : Math.max(1, Math.round((limitDays || periodDays) / periodDays));

  const rows = [];
  for (let index = periods - 1; index >= 0; index -= 1) {
    const periodEnd = new Date(end);
    periodEnd.setDate(end.getDate() - index * periodDays);
    const periodStart = new Date(periodEnd);
    periodStart.setDate(periodEnd.getDate() - (periodDays - 1));
    const periodStartIso = todayIso(periodStart);
    const periodEndIso = todayIso(periodEnd);
    const periodValues = [];
    let realCount = 0;

    for (let offset = 0; offset < periodDays; offset += 1) {
      const currentDate = new Date(periodStart);
      currentDate.setDate(periodStart.getDate() + offset);
      if (allRange && firstDataDate && currentDate < firstDataDate) continue;
      const currentDay = todayIso(currentDate);
      const realDay = dailyByDay.get(currentDay);

      if (realDay) {
        periodValues.push(realDay.avgWeightKg);
        realCount += realDay.count;
        continue;
      }

      const interpolated = interpolatedWeightForDate(dailyAverages, currentDate);
      if (Number.isFinite(interpolated)) periodValues.push(interpolated);
    }

    if (!periodValues.length) continue;
    const avgWeightKg = periodValues.reduce((sum, value) => sum + value, 0) / periodValues.length;
    const labelStartIso = allRange && firstDataDate && periodStart < firstDataDate
      ? todayIso(firstDataDate)
      : periodStartIso;
    rows.push({
      day: periodEndIso,
      periodStart: labelStartIso,
      periodEnd: periodEndIso,
      avgWeightKg: Math.round(avgWeightKg * 100) / 100,
      count: realCount,
      filled: realCount === 0,
      rangeLabel: formatWeekRange(labelStartIso, periodEndIso),
    });
  }
  return rows;
}

function buildPeriodStepsHistory(rows, limitDays, endDay, periodDays = 7) {
  const end = isoDateObject(endDay);
  const today = isoDateObject(todayIso());
  if (end > today) end.setTime(today.getTime());

  const normalizedRows = rows
    .map((row) => {
      const day = String(row.day || "");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
      return {
        ...row,
        day,
        date: isoDateObject(day),
        steps: Math.max(0, Math.round(readNumber(row.steps) || 0)),
        normalSteps: Math.max(0, Math.round(readNumber(row.normalSteps ?? row.normal_steps ?? row.steps) || 0)),
        manualSteps: Math.max(0, Math.round(readNumber(row.manualSteps ?? row.manual_steps ?? (row.normalMode === "automatic" || row.normal_mode === "automatic" ? 0 : row.normalSteps ?? row.normal_steps ?? row.steps)) || 0)),
        automaticSteps: Math.max(0, Math.round(readNumber(row.automaticSteps ?? row.automatic_steps) || 0)),
        normalMode: row.normalMode || row.normal_mode || "manual",
        virtualSteps: Math.max(0, Math.round(readNumber(row.virtualSteps ?? row.virtual_steps) || 0)),
        filled: row.filled === true,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.date - b.date);
  const rowsByDay = new Map(normalizedRows.map((row) => [row.day, row]));
  const realRows = normalizedRows.filter((row) => !row.filled && row.steps > 0);
  const firstDataDate = realRows[0]?.date || null;
  const allRange = isAllHistoryRange(limitDays);
  const spanDays = firstDataDate
    ? Math.max(periodDays, Math.floor((end - firstDataDate) / 86400000) + 1)
    : periodDays;
  const periods = allRange
    ? Math.max(1, Math.ceil(spanDays / periodDays))
    : Math.max(1, Math.round((limitDays || periodDays) / periodDays));

  const periodRows = [];
  for (let index = periods - 1; index >= 0; index -= 1) {
    const periodEnd = new Date(end);
    periodEnd.setDate(end.getDate() - index * periodDays);
    const periodStart = new Date(periodEnd);
    periodStart.setDate(periodEnd.getDate() - (periodDays - 1));
    const periodStartIso = todayIso(periodStart);
    const periodEndIso = todayIso(periodEnd);
    const values = [];

    for (let offset = 0; offset < periodDays; offset += 1) {
      const currentDate = new Date(periodStart);
      currentDate.setDate(periodStart.getDate() + offset);
      if (allRange && firstDataDate && currentDate < firstDataDate) continue;
      const row = rowsByDay.get(todayIso(currentDate));
      if (row && !row.filled && row.steps > 0) values.push(row);
    }

    const labelStartIso = allRange && firstDataDate && periodStart < firstDataDate
      ? todayIso(firstDataDate)
      : periodStartIso;
    const avgSteps = values.length
      ? Math.round(values.reduce((sum, value) => sum + value.steps, 0) / values.length)
      : 0;
    const avgNormalSteps = values.length
      ? Math.round(values.reduce((sum, value) => sum + value.normalSteps, 0) / values.length)
      : 0;
    const avgVirtualSteps = values.length
      ? Math.round(values.reduce((sum, value) => sum + value.virtualSteps, 0) / values.length)
      : 0;
    const avgManualSteps = values.length
      ? Math.round(values.reduce((sum, value) => sum + (value.normalMode === "manual" ? value.manualSteps : 0), 0) / values.length)
      : 0;
    const avgAutomaticSteps = values.length
      ? Math.round(values.reduce((sum, value) => sum + (value.normalMode === "automatic" ? value.automaticSteps : 0), 0) / values.length)
      : 0;
    periodRows.push({
      day: periodEndIso,
      periodStart: labelStartIso,
      periodEnd: periodEndIso,
      steps: avgSteps,
      normalSteps: avgNormalSteps,
      manualSteps: avgManualSteps,
      automaticSteps: avgAutomaticSteps,
      normalMode: "period",
      virtualSteps: avgVirtualSteps,
      count: values.length,
      filled: values.length === 0,
      rangeLabel: formatWeekRange(labelStartIso, periodEndIso),
    });
  }
  return periodRows;
}

function stepsEventsToHistoryRows(events, endDay) {
  const end = isoDateObject(endDay);
  return events
    .map((event) => ({
      day: String(event.day || ""),
      steps: Math.max(0, Math.round(readNumber(event.steps) || 0)),
      normalSteps: Math.max(0, Math.round(readNumber(event.normalSteps ?? event.normal_steps ?? event.steps) || 0)),
      manualSteps: Math.max(0, Math.round(readNumber(event.manualSteps ?? event.manual_steps ?? (event.normalMode === "automatic" || event.normal_mode === "automatic" ? 0 : event.normalSteps ?? event.normal_steps ?? event.steps)) || 0)),
      automaticSteps: Math.max(0, Math.round(readNumber(event.automaticSteps ?? event.automatic_steps) || 0)),
      normalMode: event.normalMode || event.normal_mode || "manual",
      virtualSteps: Math.max(0, Math.round(readNumber(event.virtualSteps ?? event.virtual_steps) || 0)),
      filled: false,
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day) && isoDateObject(row.day) <= end)
    .sort((a, b) => a.day.localeCompare(b.day));
}

function normalizeStats(payload) {
  const stats = payload?.stats;
  if (!payload?.ok || !stats || typeof stats !== "object") return null;
  return stats;
}

function previousDeltaFromEvents(currentWeight, currentTimestamp, events) {
  const weightKg = readNumber(currentWeight);
  if (!Number.isFinite(weightKg) || !Array.isArray(events)) return null;

  const currentTime = Date.parse(currentTimestamp || "");
  for (const event of events) {
    const eventWeight = readNumber(event?.weightKg);
    if (!Number.isFinite(eventWeight)) continue;

    const eventTimestamp = String(event?.timestamp || "");
    const eventTime = Date.parse(eventTimestamp);
    const sameTimestamp = currentTimestamp && eventTimestamp === currentTimestamp;
    const sameInstant = Number.isFinite(currentTime) && Number.isFinite(eventTime) && eventTime === currentTime;
    const futureEvent = Number.isFinite(currentTime) && Number.isFinite(eventTime) && eventTime > currentTime;
    if (sameTimestamp || sameInstant || futureEvent) continue;

    return weightKg - eventWeight;
  }

  return null;
}

function normalizeStepHistory(payload) {
  const rows = Array.isArray(payload?.daily) ? payload.daily : [];
  return rows
    .map((row) => ({
      day: String(row.day || ""),
      steps: Math.max(0, Math.round(readNumber(row.steps) || 0)),
      normalSteps: Math.max(0, Math.round(readNumber(row.normal_steps ?? row.steps) || 0)),
      manualSteps: Math.max(0, Math.round(readNumber(row.manual_steps ?? (row.normal_mode === "automatic" ? 0 : row.normal_steps ?? row.steps)) || 0)),
      automaticSteps: Math.max(0, Math.round(readNumber(row.automatic_steps) || 0)),
      normalMode: row.normal_mode || "manual",
      virtualSteps: Math.max(0, Math.round(readNumber(row.virtual_steps) || 0)),
      filled: row.filled === true,
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day));
}

function normalizeStepEvents(payload) {
  const rows = Array.isArray(payload?.events) ? payload.events : [];
  return rows
    .map((row) => ({
      day: String(row.day || ""),
      steps: Math.max(0, Math.round(readNumber(row.steps) || 0)),
      source: row.source || "manual",
      normalSteps: Math.max(0, Math.round(readNumber(row.normal_steps ?? row.steps) || 0)),
      manualSteps: Math.max(0, Math.round(readNumber(row.manual_steps ?? (row.normal_mode === "automatic" ? 0 : row.normal_steps ?? row.steps)) || 0)),
      automaticSteps: Math.max(0, Math.round(readNumber(row.automatic_steps) || 0)),
      automaticAvailable: row.automatic_available === true,
      normalMode: row.normal_mode || "manual",
      virtualSteps: Math.max(0, Math.round(readNumber(row.virtual_steps) || 0)),
      sources: Array.isArray(row.sources) ? row.sources : [],
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day));
}

function stepsForDay(day) {
  const apiEvent = stepsEvents.find((event) => event.day === day);
  if (apiEvent) return apiEvent.manualSteps;
  return Math.max(0, Math.round(readNumber(store.days[day]?.steps) || 0));
}

function totalStepsForDay(day) {
  const apiEvent = stepsEvents.find((event) => event.day === day);
  if (apiEvent) return apiEvent.steps;
  return Math.max(0, Math.round(readNumber(store.days[day]?.steps) || 0));
}

function statClass(value) {
  if (!Number.isFinite(value)) return "";
  if (value < 0) return "is-down";
  if (value > 0) return "is-up";
  return "is-flat";
}

function goalTrendStatus(rate) {
  if (!Number.isFinite(rate)) return null;
  if (rate < -0.2) return "spadkowe";
  if (rate > 0.2) return "wzrostowe";
  return "stabilne";
}

function renderStatItem(label, value, className = "", extraClass = "") {
  return `
    <div class="weight-cut-stat ${extraClass}">
      <span>${label}</span>
      <strong class="${className}" title="${escapeHtml(String(value).replace(/<[^>]*>/g, " "))}">${value}</strong>
    </div>
  `;
}

function renderTrendIcon(trend) {
  const paths = {
    down: '<path d="M5 7.5 10 12.5 15 7.5" />',
    up: '<path d="m5 12.5 5-5 5 5" />',
    stable: '<path d="M4.5 10h11" />',
  };
  return `
    <svg class="weight-cut-ma-trend-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      ${paths[trend] || paths.stable}
    </svg>
  `;
}

function renderPanelToggle(id, panelId, label, expanded) {
  return `
    <button class="weight-cut-panel-toggle ${expanded ? "is-active" : ""}" id="${id}" type="button" aria-controls="${panelId}" aria-expanded="${expanded ? "true" : "false"}">
      ${label}
    </button>
  `;
}

function renderCollapsiblePanel(id, expanded, content, extraClass = "") {
  return `
    <div class="weight-cut-collapsible ${expanded ? "is-open" : ""} ${extraClass}" id="${id}" aria-hidden="${expanded ? "false" : "true"}" ${expanded ? "" : "inert"}>
      <div class="weight-cut-collapsible-inner">${content}</div>
    </div>
  `;
}

function formatDailyCalories(value) {
  if (!Number.isFinite(value)) return "brak danych";
  const rounded = Math.round(value);
  const sign = rounded > 0 ? "" : rounded < 0 ? "−" : "";
  return `${sign}${formatInt(Math.abs(rounded))} kcal/dzień`;
}

function formatMaEta(eta) {
  if (eta?.status === "done") return "cel osiągnięty";
  if (eta?.status === "future" && eta.day) return `około ${formatGoalDate(eta.day)}`;
  if (eta?.status === "no-loss") return "brak trendu spadkowego";
  return "brak danych";
}

function renderMaTargetControl() {
  return `
    <label class="weight-cut-ma-target">
      <span>Cel prognozy</span>
      <span class="weight-cut-ma-target-field">
        <input id="weight-cut-ma-target" type="number" min="${REALISTIC_WEIGHT_MIN_KG}" max="${REALISTIC_WEIGHT_MAX_KG}" step="0.1" inputmode="decimal" value="${formatGoalWeight(weightMaTargetKg).replace(",", ".")}" aria-label="Waga docelowa dla prognozy MA7" />
        <span>kg</span>
      </span>
    </label>
  `;
}

function renderMa7Panel(events) {
  const stats = calculateMa7Stats(events, {
    goalKg: weightMaTargetKg,
    rateStartDay: WEIGHT_MA_RATE_START_DAY,
  });
  if (!stats) {
    return `
      <section class="weight-cut-ma-panel" aria-labelledby="weight-cut-ma7-title">
        <div class="weight-cut-ma-panel-head">
          <span id="weight-cut-ma7-title">Statystyki MA7</span>
          ${renderMaTargetControl()}
        </div>
        <div class="weight-cut-stats-empty">Za mało danych do obliczenia MA7</div>
      </section>
    `;
  }

  const trendLabel = stats.trend === "down" ? "spadek" : stats.trend === "up" ? "wzrost" : "stabilnie";
  const trendValue = Number.isFinite(stats.trendDeltaKg) ? formatSignedKg(stats.trendDeltaKg) : "brak danych";
  const etaClass = stats.eta.status === "future" || stats.eta.status === "done" ? "is-down" : "is-flat";
  return `
    <section class="weight-cut-ma-panel" aria-labelledby="weight-cut-ma7-title">
      <div class="weight-cut-ma-panel-head">
        <span id="weight-cut-ma7-title">Statystyki MA7</span>
        <span>${formatShortDateWithYear(stats.day)}</span>
        ${renderMaTargetControl()}
      </div>
      <div class="weight-cut-ma-grid">
        ${renderStatItem("Bieżąca MA7", formatKg(stats.currentMa7Kg), "", "weight-cut-ma-stat weight-cut-ma-stat--current")}
        <div class="weight-cut-stat weight-cut-ma-stat weight-cut-ma-stat--trend">
          <span>Trend dzień do dnia</span>
          <strong class="${statClass(stats.trendDeltaKg)}">
            ${renderTrendIcon(stats.trend)}
            <span>${trendValue}</span>
          </strong>
          <small>${trendLabel}</small>
        </div>
        ${renderStatItem("Zmiana MA7 · 7 dni", formatSignedKg(stats.weeklyChangeKg), statClass(stats.weeklyChangeKg), "weight-cut-ma-stat")}
        ${renderStatItem("Tempo MA7 od 20 sierpnia", formatRate(stats.rateSinceStartKgPerWeek), statClass(stats.rateSinceStartKgPerWeek), "weight-cut-ma-stat")}
        ${renderStatItem("Deficyt z MA7", formatDailyCalories(stats.dailyDeficitKcal), statClass(stats.weeklyChangeKg), "weight-cut-ma-stat")}
        ${renderStatItem(`Dystans do celu ${formatGoalWeight(stats.goalKg)} kg`, formatSignedKg(stats.distanceToGoalKg), statClass(stats.distanceToGoalKg), "weight-cut-ma-stat")}
        ${renderStatItem(`Prognoza dojścia do ${formatGoalWeight(stats.goalKg)} kg`, formatMaEta(stats.eta), etaClass, "weight-cut-ma-stat weight-cut-ma-stat--eta")}
      </div>
      <div class="weight-cut-ma-explainer">
        <p><strong>Deficyt:</strong> zmiana MA7 z ostatnich 7 dni × 7500 kcal/kg ÷ 7. To orientacyjny średni bilans dzienny.</p>
        <p><strong>Prognoza do ${formatGoalWeight(stats.goalKg)} kg:</strong> ekstrapolacja tempa między obecną MA7 a MA7 sprzed 14 dni.</p>
      </div>
    </section>
  `;
}

function buildDailyGoalWeightPoints(events) {
  const groups = new Map();
  events.forEach((event) => {
    const day = String(event.timestamp || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(event.weightKg)) return;
    const group = groups.get(day) || { day, date: isoDateObject(day), weights: [] };
    group.weights.push(event.weightKg);
    groups.set(day, group);
  });
  return Array.from(groups.values())
    .map((group) => ({
      day: group.day,
      date: group.date,
      avgWeightKg: group.weights.reduce((sum, value) => sum + value, 0) / group.weights.length,
    }))
    .sort((a, b) => a.date - b.date);
}

function goalWeightOnDay(points, targetDay) {
  if (!points.length) return null;

  const targetDate = isoDateObject(targetDay);
  let previousPoint = null;
  let nextPoint = null;
  for (const point of points) {
    if (point.date.getTime() === targetDate.getTime()) return point.avgWeightKg;
    if (point.date < targetDate) {
      previousPoint = point;
    } else {
      nextPoint = point;
      break;
    }
  }

  if (!previousPoint || !nextPoint) return null;
  const totalDays = Math.max(1, Math.round((nextPoint.date - previousPoint.date) / 86400000));
  const elapsedDays = Math.round((targetDate - previousPoint.date) / 86400000);
  return previousPoint.avgWeightKg + (nextPoint.avgWeightKg - previousPoint.avgWeightKg) * (elapsedDays / totalDays);
}

function averageGoalWeightWindow(points, endDay, days = 7) {
  const values = [];
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const day = addDaysIso(endDay, -offset);
    const value = goalWeightOnDay(points, day);
    if (Number.isFinite(value)) values.push(value);
  }
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function buildGoalStatsSnapshot(events, snapshotDay) {
  const snapshotEvents = events
    .filter((event) => {
      const day = String(event.timestamp || "").slice(0, 10);
      return /^\d{4}-\d{2}-\d{2}$/.test(day) && day <= snapshotDay && Number.isFinite(event.weightKg);
    })
    .sort((a, b) => String(a.timestamp || "").localeCompare(String(b.timestamp || "")));
  const points = buildDailyGoalWeightPoints(snapshotEvents);
  const currentChangeWeight = averageGoalWeightWindow(points, snapshotDay, 7);
  if (!Number.isFinite(currentChangeWeight)) return null;

  const startWeight = goalWeightOnDay(points, WEIGHT_RATE_START_DAY);
  const daysSinceStart = daysBetweenIso(WEIGHT_RATE_START_DAY, snapshotDay);
  const rate = Number.isFinite(startWeight) && daysSinceStart > 0
    ? ((currentChangeWeight - startWeight) / daysSinceStart) * 7
    : null;

  return {
    current_weight_kg: Math.round(currentChangeWeight * 100) / 100,
    current_timestamp: `${snapshotDay}T12:00:00`,
    rates: {
      since_may_1_2026: {
        kg_per_week: rate,
        status: goalTrendStatus(rate),
      },
    },
  };
}

function calculateGoalProjection(targetKg, stats) {
  const currentWeight = readNumber(stats?.current_weight_kg);
  const ratePerWeek = readNumber(stats?.rates?.since_may_1_2026?.kg_per_week);
  const startDay = /^\d{4}-\d{2}-\d{2}$/.test(String(stats?.current_timestamp || "").slice(0, 10))
    ? String(stats.current_timestamp).slice(0, 10)
    : todayIso();

  if (!Number.isFinite(targetKg) || !Number.isFinite(currentWeight)) {
    return { status: "missing" };
  }

  if (currentWeight <= targetKg) {
    return {
      status: "done",
      day: startDay,
      duration: { months: 0, days: 0 },
    };
  }

  const ratePerDay = ratePerWeek / 7;
  const weightToGoal = targetKg - currentWeight;
  const daysToGoal = weightToGoal / ratePerDay;
  if (!Number.isFinite(daysToGoal) || daysToGoal < 0) {
    return { status: "no-trend" };
  }

  const wholeDays = Math.ceil(daysToGoal);
  const day = addDaysIso(startDay, wholeDays);
  return {
    status: "future",
    day,
    duration: diffMonthsDays(startDay, day),
  };
}

function renderGoalDelta(currentProjection, previousProjection) {
  if (!currentProjection?.day || !previousProjection?.day) return "";
  if (currentProjection.status !== "future" || previousProjection.status !== "future") return "";

  const deltaDays = daysBetweenIso(previousProjection.day, currentProjection.day);
  if (deltaDays === 0) return "";
  const weeks = Math.trunc(Math.abs(deltaDays) / 7);
  if (!weeks) return "";
  const label = `${deltaDays > 0 ? "+" : "-"}${weeks} ${weeks === 1 ? "tydz." : "tyg."}`;
  const className = deltaDays < 0 ? "is-faster" : "is-slower";
  return `<em class="weight-cut-goal-delta ${className}" title="Zmiana daty celu wzgledem wczorajszej projekcji">${escapeHtml(label)}</em>`;
}

function renderGoalProjection(targetKg, stats, previousStats) {
  const projection = calculateGoalProjection(targetKg, stats);
  const previousProjection = previousStats ? calculateGoalProjection(targetKg, previousStats) : null;
  const delta = renderGoalDelta(projection, previousProjection);
  if (projection.status === "missing") {
    return `<div class="weight-cut-goal-result"><strong>brak danych</strong><span>czekam na statystyki</span></div>`;
  }
  if (projection.status === "no-trend") {
    return `<div class="weight-cut-goal-result"><strong>brak trendu</strong><span>tempo nie prowadzi do celu</span></div>`;
  }
  if (projection.status === "done") {
    return `<div class="weight-cut-goal-result"><strong>osiągnięty</strong><span class="weight-cut-goal-sub">${formatGoalDuration(projection.duration)}${delta}</span></div>`;
  }
  return `
    <div class="weight-cut-goal-result">
      <strong>${escapeHtml(formatGoalDate(projection.day))}</strong>
      <span class="weight-cut-goal-sub">${escapeHtml(formatGoalDuration(projection.duration))}${delta}</span>
    </div>
  `;
}

function renderWeightGoals(stats) {
  const currentDay = String(stats?.current_timestamp || "").slice(0, 10);
  const currentStats = /^\d{4}-\d{2}-\d{2}$/.test(currentDay)
    ? buildGoalStatsSnapshot(weightEvents, currentDay)
    : null;
  const previousSnapshotDay = /^\d{4}-\d{2}-\d{2}$/.test(currentDay)
    ? addDaysIso(currentDay, -7)
    : addDaysIso(todayIso(), -7);
  const previousStats = buildGoalStatsSnapshot(weightEvents, previousSnapshotDay);
  const rows = weightGoalTargets.map((target, index) => `
    <div class="weight-cut-goal-row">
      <div class="weight-cut-goal-target">
        <strong>${escapeHtml(formatGoalWeight(target))}</strong>
        <span>kg</span>
      </div>
      ${renderGoalProjection(target, currentStats, previousStats)}
      <button class="weight-cut-goal-delete" type="button" data-delete-weight-goal-index="${index}" aria-label="Usuń cel" title="Usuń cel">&times;</button>
    </div>
  `).join("");

  return `
    <section class="weight-cut-goals" aria-label="Celownik">
      <div class="weight-cut-goals-head">
        <span>Celownik</span>
        <span>7 dni vs poprzednie 7</span>
      </div>
      <form class="weight-cut-goal-form" id="weight-cut-goal-form">
        <input id="weight-cut-goal-new" type="number" min="1" step="0.1" inputmode="decimal" placeholder="kg" aria-label="Nowy cel w kilogramach" />
        <button type="submit" title="Dodaj cel" aria-label="Dodaj cel">+</button>
      </form>
      <div class="weight-cut-goal-list">
        ${rows || `<div class="weight-cut-goals-empty">Brak celów</div>`}
      </div>
    </section>
  `;
}

function renderExtremeStatValue(weight, timestamp) {
  const day = formatShortDateWithYear(String(timestamp || "").slice(0, 10));
  return `${formatKg(readNumber(weight))}${day ? `<small>${escapeHtml(day)}</small>` : ""}`;
}

function renderPeriodChangeValue(period) {
  const change = readNumber(period?.change_kg);
  const startDay = formatShortDateWithYear(period?.start_day);
  const endDay = formatShortDateWithYear(period?.end_day);
  const range = startDay && endDay ? `${startDay} - ${endDay}` : "";
  return `${formatSignedKg(change)}${range ? `<small>${escapeHtml(range)}</small>` : ""}`;
}

function renderStatsPanel(stats) {
  const extremeChanges = stats?.extreme_changes || {};
  const extreme7 = extremeChanges.days_7 || {};
  const extreme30 = extremeChanges.days_30 || {};
  const sinceMay1 = readNumber(stats?.since_may_1_2026);
  const records = stats ? `
    <div class="weight-cut-records-grid">
      ${renderStatItem("Najszybszy spadek 7 dni", renderPeriodChangeValue(extreme7.loss), statClass(readNumber(extreme7.loss?.change_kg)))}
      ${renderStatItem("Najszybszy wzrost 7 dni", renderPeriodChangeValue(extreme7.gain), statClass(readNumber(extreme7.gain?.change_kg)))}
      <div class="weight-cut-record-pair">
        ${renderStatItem("Najwyższa", renderExtremeStatValue(stats.highest_weight_kg, stats.highest_timestamp))}
        ${renderStatItem("Najwyższa od 1 maja", renderExtremeStatValue(stats.highest_weight_kg_since_may_1_2026, stats.highest_timestamp_since_may_1_2026))}
      </div>
      ${renderStatItem("Najszybszy spadek 30 dni", renderPeriodChangeValue(extreme30.loss), statClass(readNumber(extreme30.loss?.change_kg)))}
      ${renderStatItem("Najszybszy wzrost 30 dni", renderPeriodChangeValue(extreme30.gain), statClass(readNumber(extreme30.gain?.change_kg)))}
      <div class="weight-cut-record-pair">
        ${renderStatItem("Najniższa", renderExtremeStatValue(stats.lowest_weight_kg, stats.lowest_timestamp))}
        ${renderStatItem("Najniższa od 1 maja", renderExtremeStatValue(stats.lowest_weight_kg_since_may_1_2026, stats.lowest_timestamp_since_may_1_2026))}
      </div>
    </div>
  ` : '<div class="weight-cut-stats-empty">Brak rekordów</div>';

  return `
    <div class="weight-cut-stats weight-cut-stats-inline">
      <div class="weight-cut-stats-head">
        <span>Statystyki wagi</span>
        <span>${stats ? `${formatInt(stats.measurement_count)} pom.` : "czekam na dane"}</span>
      </div>
      <div class="weight-cut-stats-layout">
        ${renderStatItem("Od 1 maja 2026", formatSignedKg(sinceMay1), statClass(sinceMay1), "weight-cut-stat--primary")}
        ${renderMa7Panel(weightEvents)}
      </div>
      <nav class="weight-cut-panel-nav" aria-label="Sekcje statystyk wagi">
        ${renderPanelToggle("weight-cut-goals-toggle", "weight-cut-goals-panel", "Celownik", weightGoalsExpanded)}
        ${renderPanelToggle("weight-cut-records-toggle", "weight-cut-records-panel", "Rekordy", weightRecordsExpanded)}
      </nav>
      ${renderCollapsiblePanel("weight-cut-goals-panel", weightGoalsExpanded, renderWeightGoals(stats))}
      ${renderCollapsiblePanel("weight-cut-records-panel", weightRecordsExpanded, records, "weight-cut-records")}
    </div>
  `;
}

function visibleWeightChartAnnotations(rows) {
  if (!rows.length) return [];
  const rangeStart = rows[0].periodStart || rows[0].day;
  const rangeEnd = rows[rows.length - 1].periodEnd || rows[rows.length - 1].day;
  return WEIGHT_CHART_ANNOTATIONS
    .map((annotation, index) => ({ ...annotation, marker: index + 1 }))
    .filter((annotation) => {
      const endDay = annotation.endDay || annotation.startDay;
      return annotation.startDay <= rangeEnd && endDay >= rangeStart;
    });
}

function renderWeightChartAnnotations(rows, { height, padX, padY, plotRight }) {
  if (!rows.length) return "";
  const rangeStart = rows[0].periodStart || rows[0].day;
  const rangeEnd = rows[rows.length - 1].periodEnd || rows[rows.length - 1].day;
  const rangeDays = Math.max(1, daysBetweenIso(rangeStart, rangeEnd));
  const plotWidth = plotRight - padX;
  const dayWidth = plotWidth / rangeDays;
  const xForDay = (day) => padX + (daysBetweenIso(rangeStart, day) / rangeDays) * plotWidth;
  const visible = visibleWeightChartAnnotations(rows);

  return visible.map((annotation) => {
    const startDay = annotation.startDay < rangeStart ? rangeStart : annotation.startDay;
    const endDay = (annotation.endDay || annotation.startDay) > rangeEnd
      ? rangeEnd
      : annotation.endDay || annotation.startDay;
    const startX = Math.max(padX, Math.min(plotRight, xForDay(startDay)));
    const endX = Math.max(startX, Math.min(plotRight, xForDay(endDay) + (annotation.type === "range" ? dayWidth : 0)));
    const markerX = annotation.type === "range" ? (startX + endX) / 2 : startX;
    const title = `${annotation.label} (${formatShortDateWithYear(annotation.startDay)}${annotation.endDay ? ` – ${formatShortDateWithYear(annotation.endDay)}` : ""})`;

    if (annotation.type === "range") {
      return `
        <g class="weight-cut-chart-annotation is-range">
          <rect x="${startX.toFixed(1)}" y="${padY}" width="${Math.max(2, endX - startX).toFixed(1)}" height="${height - padY * 2}" rx="3">
            <title>${escapeHtml(title)}</title>
          </rect>
          <line x1="${startX.toFixed(1)}" y1="${padY}" x2="${startX.toFixed(1)}" y2="${height - padY}" />
          <line x1="${endX.toFixed(1)}" y1="${padY}" x2="${endX.toFixed(1)}" y2="${height - padY}" />
          <circle class="weight-cut-chart-annotation-marker" cx="${markerX.toFixed(1)}" cy="12" r="7"><title>${escapeHtml(title)}</title></circle>
          <text class="weight-cut-chart-annotation-number" x="${markerX.toFixed(1)}" y="14.4" text-anchor="middle">${annotation.marker}</text>
        </g>
      `;
    }

    return `
      <g class="weight-cut-chart-annotation is-event">
        <line x1="${startX.toFixed(1)}" y1="19" x2="${startX.toFixed(1)}" y2="${height - padY}">
          <title>${escapeHtml(title)}</title>
        </line>
        <circle class="weight-cut-chart-annotation-marker" cx="${startX.toFixed(1)}" cy="12" r="7">
          <title>${escapeHtml(title)}</title>
        </circle>
        <text class="weight-cut-chart-annotation-number" x="${startX.toFixed(1)}" y="14.4" text-anchor="middle">${annotation.marker}</text>
      </g>
    `;
  }).join("");
}

function renderWeightChartAnnotationLegend(rows) {
  const visible = visibleWeightChartAnnotations(rows);
  if (!visible.length) return "";
  return `
    <div class="weight-cut-chart-annotation-legend" aria-label="Adnotacje na wykresie masy">
      ${visible.map((annotation) => {
        const date = annotation.endDay
          ? `${formatShortDate(annotation.startDay)} – ${formatShortDateWithYear(annotation.endDay)}`
          : formatShortDateWithYear(annotation.startDay);
        return `
          <div class="weight-cut-chart-annotation-legend-item ${annotation.type === "range" ? "is-range" : "is-event"}">
            <span class="weight-cut-chart-annotation-legend-marker" aria-hidden="true">${annotation.marker}</span>
            <span>
              <strong>${escapeHtml(date)}</strong>
              <small>${escapeHtml(annotation.label)}</small>
            </span>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderWeightChart(rows, showMovingAverage = true) {
  if (!rows.length) {
    return `<div class="weight-cut-chart-empty">Brak historii pomiarów</div>`;
  }

  const isPeriod = rows.some((row) => row.periodStart && row.periodEnd);
  const width = 640;
  const height = 180;
  const padX = 38;
  const padY = 24;
  const plotRight = width - 82;
  const values = rows.map((row) => row.avgWeightKg);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  let yMin = Math.floor(minValue);
  let yMax = Math.ceil(maxValue);
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }
  const denom = Math.max(1, rows.length - 1);
  const points = rows.map((row, index) => {
    const x = padX + (index / denom) * (plotRight - padX);
    const y = padY + ((yMax - row.avgWeightKg) / (yMax - yMin || 1)) * (height - padY * 2);
    return { ...row, x, y };
  });
  const movingAveragePoints = isPeriod ? [] : points.map((point, index) => {
    const windowRows = rows.slice(Math.max(0, index - 6), index + 1).filter((row) => !row.filled);
    if (!windowRows.length) return null;
    const avg = windowRows.reduce((sum, row) => sum + row.avgWeightKg, 0) / windowRows.length;
    const y = padY + ((yMax - avg) / (yMax - yMin || 1)) * (height - padY * 2);
    return { x: point.x, y };
  });
  const movingAveragePath = movingAveragePoints
    .map((point, index) => {
      if (!point) return "";
      return `${index === 0 || !movingAveragePoints[index - 1] ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    })
    .filter(Boolean)
    .join(" ");
  const segments = points.slice(1).map((point, index) => {
    const previous = points[index];
    const isFilled = point.filled || previous.filled;
    return {
      isFilled,
      x1: previous.x.toFixed(1),
      y1: previous.y.toFixed(1),
      x2: point.x.toFixed(1),
      y2: point.y.toFixed(1),
    };
  });
  const last = points[points.length - 1];
  const first = points[0];
  const topLabelY = padY + 4;
  const bottomLabelY = height - padY + 4;
  let currentLabelY = Math.min(height - padY - 10, Math.max(padY + 10, last.y));
  if (Math.abs(currentLabelY - topLabelY) < 18) currentLabelY = topLabelY + 20;
  if (Math.abs(currentLabelY - bottomLabelY) < 18) currentLabelY = bottomLabelY - 20;
  const annotations = renderWeightChartAnnotations(rows, { height, padX, padY, plotRight });

  return `
    <svg class="weight-cut-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Wykres średniej wagi dziennej">
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${padY}" x2="${plotRight}" y2="${padY}" />
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${height / 2}" x2="${plotRight}" y2="${height / 2}" />
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${height - padY}" x2="${plotRight}" y2="${height - padY}" />
      ${annotations}
      <text class="weight-cut-chart-scale" x="${plotRight + 10}" y="${topLabelY}">${yMax} kg</text>
      <text class="weight-cut-chart-scale is-current" x="${plotRight + 10}" y="${currentLabelY.toFixed(1)}">${last.avgWeightKg.toFixed(2).replace(".", ",")} kg</text>
      <text class="weight-cut-chart-scale" x="${plotRight + 10}" y="${bottomLabelY}">${yMin} kg</text>
      ${segments.map((segment) => `
        <line
          class="weight-cut-chart-line-segment ${segment.isFilled ? "is-filled" : ""}"
          x1="${segment.x1}"
          y1="${segment.y1}"
          x2="${segment.x2}"
          y2="${segment.y2}"
        />
      `).join("")}
      ${showMovingAverage && !isPeriod && movingAveragePath ? `
        <path class="weight-cut-chart-ma-line" d="${movingAveragePath}">
          <title>Średnia krocząca 7 dni - łagodzi pojedyncze skoki pomiarów.</title>
        </path>
      ` : ""}
      ${points.map((point) => `
        <circle
          class="weight-cut-chart-dot ${point.filled ? "is-filled" : ""}"
          cx="${point.x.toFixed(1)}"
          cy="${point.y.toFixed(1)}"
          r="${point.filled ? 3.2 : 4}"
          tabindex="0"
          data-chart-date="${escapeHtml(point.day)}"
          data-chart-day="${escapeHtml(point.rangeLabel || formatChartDay(point.day))}"
          data-chart-weight="${escapeHtml(formatKg(point.avgWeightKg))}"
          data-chart-kind="${escapeHtml(getChartPointKind(point))}"
        ></circle>
      `).join("")}
      <text class="weight-cut-chart-label" x="${padX}" y="${height - 5}">${formatShortDateWithYear(first.periodStart || first.day)}</text>
      <text class="weight-cut-chart-label" x="${plotRight}" y="${height - 5}" text-anchor="end">${formatShortDateWithYear(last.periodEnd || last.day)}</text>
    </svg>
    ${renderWeightChartAnnotationLegend(rows)}
  `;
}

function mixStepSourceColor(manualSteps, automaticSteps, virtualSteps) {
  const manual = Math.max(0, Number(manualSteps) || 0);
  const automatic = Math.max(0, Number(automaticSteps) || 0);
  const virtual = Math.max(0, Number(virtualSteps) || 0);
  const total = Math.max(1, manual + automatic + virtual);
  const colors = [[manual, [56, 189, 248]], [automatic, [52, 211, 153]], [virtual, [167, 139, 250]]];
  const mixed = [0, 1, 2].map((channel) => Math.round(
    colors.reduce((sum, [value, rgb]) => sum + value * rgb[channel], 0) / total,
  ));
  return `rgb(${mixed.join(", ")})`;
}

function renderStepsChart(rows, weightKg, showMovingAverage = true) {
  if (!rows.length) {
    return `<div class="weight-cut-chart-empty">Brak historii kroków</div>`;
  }

  const isPeriod = rows.some((row) => row.periodStart && row.periodEnd);
  const width = 640;
  const height = 150;
  const padX = 38;
  const padY = 20;
  const plotRight = width - 82;
  const maxSteps = Math.max(12000, Math.ceil(Math.max(...rows.map((row) => row.steps)) / 1000) * 1000);
  const denom = Math.max(1, rows.length - 1);
  const points = rows.map((row, index) => {
    const x = padX + (index / denom) * (plotRight - padX);
    const y = padY + ((maxSteps - row.steps) / maxSteps) * (height - padY * 2);
    const normalSteps = Math.min(row.steps, Math.max(0, Number(row.normalSteps ?? row.steps) || 0));
    const virtualSteps = Math.max(0, Number(row.virtualSteps) || 0);
    const manualSteps = row.normalMode === "automatic" ? 0 : Math.max(0, Number(row.manualSteps ?? normalSteps) || 0);
    const automaticSteps = row.normalMode === "manual" ? 0 : Math.max(0, Number(row.automaticSteps ?? normalSteps) || 0);
    return { ...row, normalSteps, manualSteps, automaticSteps, virtualSteps, sourceColor: mixStepSourceColor(manualSteps, automaticSteps, virtualSteps), x, y };
  });
  const movingAveragePoints = isPeriod ? [] : points.map((point, index) => {
    const windowRows = rows.slice(Math.max(0, index - 6), index + 1).filter((row) => !row.filled && row.steps > 0);
    if (!windowRows.length) return null;
    const avg = windowRows.reduce((sum, row) => sum + row.steps, 0) / windowRows.length;
    const y = padY + ((maxSteps - avg) / maxSteps) * (height - padY * 2);
    return { x: point.x, y };
  });
  const movingAveragePath = movingAveragePoints
    .map((point, index) => {
      if (!point) return "";
      return `${index === 0 || !movingAveragePoints[index - 1] ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    })
    .filter(Boolean)
    .join(" ");
  const segments = points.slice(1).map((point, index) => {
    const previous = points[index];
    const isFilled = point.filled || previous.filled;
    return {
      isFilled,
      x1: previous.x.toFixed(1),
      y1: previous.y.toFixed(1),
      x2: point.x.toFixed(1),
      y2: point.y.toFixed(1),
    };
  });
  const first = points[0];
  const last = points[points.length - 1];
  const latestKcal = estimateStepKcal(last.steps, weightKg || FALLBACK_WEIGHT_KG);
  const hasLatestSteps = last.steps > 0;
  const goalSteps = 10_000;
  const goalY = padY + ((maxSteps - goalSteps) / maxSteps) * (height - padY * 2);

  return `
    <svg class="weight-cut-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Wykres kroków dziennych">
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${padY}" x2="${plotRight}" y2="${padY}" />
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${height / 2}" x2="${plotRight}" y2="${height / 2}" />
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${height - padY}" x2="${plotRight}" y2="${height - padY}" />
      <line class="weight-cut-steps-goal" x1="${padX}" y1="${goalY.toFixed(1)}" x2="${plotRight}" y2="${goalY.toFixed(1)}" />
      <text class="weight-cut-steps-goal-label" x="${padX + 4}" y="${Math.max(12, goalY - 5).toFixed(1)}">CEL 10 000</text>
      <text class="weight-cut-chart-scale" x="${plotRight + 10}" y="${padY + 4}">${formatInt(maxSteps)}</text>
      ${hasLatestSteps ? `<text class="weight-cut-chart-scale is-current" x="${plotRight + 10}" y="${Math.max(padY + 10, Math.min(height - padY - 8, last.y)).toFixed(1)}">${formatInt(last.steps)}</text>` : ""}
      <text class="weight-cut-chart-scale" x="${plotRight + 10}" y="${height - padY + 4}">0</text>
      ${segments.map((segment) => `
        <line
          class="weight-cut-steps-line-segment ${segment.isFilled ? "is-filled" : ""}"
          x1="${segment.x1}"
          y1="${segment.y1}"
          x2="${segment.x2}"
          y2="${segment.y2}"
        />
      `).join("")}
      ${showMovingAverage && !isPeriod && movingAveragePath ? `
        <path class="weight-cut-chart-ma-line" d="${movingAveragePath}">
          <title>MA7 kroków - wygładza pojedyncze skoki aktywności.</title>
        </path>
      ` : ""}
      ${points.map((point) => `
        <circle
          class="weight-cut-steps-dot ${point.filled ? "is-filled" : point.steps >= 10000 ? "is-goal" : "is-under-goal"}"
          style="--step-source-color:${point.sourceColor}"
          cx="${point.x.toFixed(1)}"
          cy="${point.y.toFixed(1)}"
          r="${point.filled ? 3 : 4}"
          tabindex="0"
          data-chart-date="${escapeHtml(point.day)}"
          data-chart-day="${escapeHtml(point.rangeLabel || formatChartDay(point.day))}"
          data-chart-weight="${escapeHtml(`${formatInt(point.steps)} kroków łącznie`)}"
          data-chart-kind="${escapeHtml(`${getStepsPointKind(point, weightKg)} · ręczne ${formatInt(point.manualSteps)} · automatyczne ${formatInt(point.automaticSteps)} · spacerowe +${formatInt(point.virtualSteps)}`)}"
        ></circle>
      `).join("")}
      <text class="weight-cut-chart-label" x="${padX}" y="${height - 5}">${formatShortDateWithYear(first.periodStart || first.day)}</text>
      <text class="weight-cut-chart-label" x="${plotRight}" y="${height - 5}" text-anchor="end">${formatShortDateWithYear(last.periodEnd || last.day)}</text>
      ${hasLatestSteps ? `<text class="weight-cut-chart-label" x="${plotRight + 10}" y="${height - 5}">~${formatInt(latestKcal)} kcal</text>` : ""}
    </svg>
  `;
}

function renderCardioChart(rows, showMovingAverage = true) {
  if (!rows.length) {
    const message = cardioStatus === "error"
      ? "Runtime Live Workout jest niedostępny"
      : "Brak historii cardio w tym zakresie";
    return `<div class="weight-cut-chart-empty">${message}</div>`;
  }

  const isPeriod = rows.some((row) => row.periodStart && row.periodEnd);
  const width = 640;
  const height = 150;
  const padX = 38;
  const padY = 20;
  const plotRight = width - 82;
  const maxCalories = Math.max(100, Math.ceil(Math.max(...rows.map((row) => row.activeCalories)) / 100) * 100);
  const denom = Math.max(1, rows.length - 1);
  const points = rows.map((row, index) => ({
    ...row,
    x: padX + (index / denom) * (plotRight - padX),
    y: padY + ((maxCalories - row.activeCalories) / maxCalories) * (height - padY * 2),
  }));
  const linePath = points
    .map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
    .join(" ");
  const movingAveragePath = !isPeriod
    ? points.map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(1)} ${(
      padY + ((maxCalories - point.movingAverage) / maxCalories) * (height - padY * 2)
    ).toFixed(1)}`).join(" ")
    : "";
  const baseline = height - padY;
  const areaPath = `${linePath} L ${points.at(-1).x.toFixed(1)} ${baseline} L ${points[0].x.toFixed(1)} ${baseline} Z`;
  const first = points[0];
  const last = points.at(-1);
  const latestHasCalories = last.activeCalories > 0;
  const gradients = points.map((point, index) => {
    const cyclingPercent = point.activeCalories ? Math.max(0, Math.min(100, point.cyclingCalories / point.activeCalories * 100)) : 100;
    return `<linearGradient id="weight-cut-cardio-point-${index}"><stop offset="${cyclingPercent}%" stop-color="#fb7185"/><stop offset="${cyclingPercent}%" stop-color="#60a5fa"/></linearGradient>`;
  }).join("");

  return `
    <svg class="weight-cut-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Wykres aktywnych kalorii cardio">
      <defs>
        <linearGradient id="weight-cut-cardio-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fb7185" stop-opacity=".22"/><stop offset="1" stop-color="#fb7185" stop-opacity="0"/></linearGradient>
        ${gradients}
      </defs>
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${padY}" x2="${plotRight}" y2="${padY}" />
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${height / 2}" x2="${plotRight}" y2="${height / 2}" />
      <line class="weight-cut-chart-grid" x1="${padX}" y1="${baseline}" x2="${plotRight}" y2="${baseline}" />
      <path class="weight-cut-cardio-area" d="${areaPath}" />
      <path class="weight-cut-cardio-line" d="${linePath}" />
      ${showMovingAverage && !isPeriod && movingAveragePath ? `<path class="weight-cut-chart-ma-line" d="${movingAveragePath}"><title>MA7 kalorii cardio</title></path>` : ""}
      <text class="weight-cut-chart-scale" x="${plotRight + 10}" y="${padY + 4}">${formatInt(maxCalories)} kcal</text>
      ${latestHasCalories ? `<text class="weight-cut-chart-scale is-current is-cardio" x="${plotRight + 10}" y="${Math.max(padY + 10, Math.min(baseline - 8, last.y)).toFixed(1)}">${last.activeCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}</text>` : ""}
      <text class="weight-cut-chart-scale" x="${plotRight + 10}" y="${baseline + 4}">0</text>
      ${points.map((point, index) => {
        const cyclingPercent = point.activeCalories ? Math.round(point.cyclingCalories / point.activeCalories * 100) : 0;
        const walkingPercent = point.activeCalories ? 100 - cyclingPercent : 0;
        const kind = isPeriod
          ? `${point.activeDayCount}/${PERIOD_DAYS[cardioChartMode] || 7} aktywnych dni · rower ${point.cyclingCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal/dz. · spacer ${point.walkingCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal/dz.`
          : `rower / trening / Free Ride ${point.cyclingCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal (${cyclingPercent}%) · spacer ${point.walkingCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal (${walkingPercent}%)`;
        const value = `${point.activeCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} ${isPeriod ? "kcal/dzień" : "kcal"}`;
        return `<circle
          class="weight-cut-cardio-dot ${point.activeCalories > 0 ? "has-value" : "is-empty"}"
          cx="${point.x.toFixed(1)}"
          cy="${point.y.toFixed(1)}"
          r="${point.activeCalories > 0 ? 4 : 2.5}"
          fill="${point.activeCalories > 0 ? `url(#weight-cut-cardio-point-${index})` : "#3f3f46"}"
          tabindex="0"
          data-chart-date="${escapeHtml(point.day)}"
          data-chart-day="${escapeHtml(point.rangeLabel || (isPeriod ? formatWeekRange(point.periodStart, point.periodEnd) : formatChartDay(point.day)))}"
          data-chart-weight="${escapeHtml(value)}"
          data-chart-kind="${escapeHtml(kind)}"
        ></circle>`;
      }).join("")}
      <text class="weight-cut-chart-label" x="${padX}" y="${height - 5}">${formatShortDateWithYear(first.periodStart || first.day)}</text>
      <text class="weight-cut-chart-label" x="${plotRight}" y="${height - 5}" text-anchor="end">${formatShortDateWithYear(last.periodEnd || last.day)}</text>
    </svg>
  `;
}

function renderCardioInsights() {
  if (!cardioRanking.length) return "";
  const series = buildCardioCalorieChartSeries(cardioRanking, {
    endDate: cardioChartEndDay,
    dayCount: 14,
  });
  const trend = summarizeCardioCalorieTrend(series);
  const trendCopy = trend.direction === "up"
    ? `wzrost o ${Math.abs(trend.delta).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal względem tygodnia wcześniej`
    : trend.direction === "down"
      ? `spadek o ${Math.abs(trend.delta).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal względem tygodnia wcześniej`
      : "stabilnie względem tygodnia wcześniej";
  const regularityDelta = trend.recentActiveDays - trend.previousActiveDays;
  return `<div class="weight-cut-cardio-insights">
    <span data-trend="${trend.direction}"><small>TREND MA7</small><strong>${trend.latestMa7.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal/dzień</strong><b>${trendCopy}</b></span>
    <span><small>REGULARNOŚĆ · 7 DNI</small><strong>${trend.recentActiveDays}/7 dni</strong><b>${regularityDelta > 0 ? "+" : ""}${regularityDelta} vs poprzedni tydzień</b></span>
    <span><small>MIX · 7 DNI</small><strong>🚴 ${Math.round(trend.cyclingPercent)}% · 🚶 ${Math.round(trend.walkingPercent)}%</strong><b>udział w aktywnych kcal</b></span>
  </div>`;
}

let store = loadStore();
let weightGoalTargets = loadGoalTargets();
let weightMaTargetKg = loadMaTargetKg();
let dateKey = todayIso();
let liveWeight = null;
let scaleSignal = null;
let weightHistory = [];
let weightEvents = [];
let weightStats = null;
let weightRecordsExpanded = false;
let weightGoalsExpanded = false;
let stepsHistory = [];
let stepsEvents = [];
let healthSnapshot = null;
let historyOpen = false;
let historyStatus = "idle";
let stepsHistoryOpen = false;
let stepsHistoryStatus = "idle";
let stepsEditDay = todayIso();
let stepsEditValue = "";
let chartEndDay = todayIso();
let historyDays = DEFAULT_HISTORY_DAYS;
let weightChartMode = "daily";
let periodHistoryDays = { ...DEFAULT_PERIOD_HISTORY_DAYS };
let stepsChartEndDay = todayIso();
let stepsHistoryDays = DEFAULT_HISTORY_DAYS;
let stepsChartMode = "daily";
let stepsPeriodHistoryDays = { ...DEFAULT_PERIOD_HISTORY_DAYS };
let cardioRanking = [];
let cardioHistory = [];
let cardioChartEndDay = todayIso();
let cardioHistoryDays = DEFAULT_HISTORY_DAYS;
let cardioChartMode = "daily";
let cardioPeriodHistoryDays = { ...DEFAULT_PERIOD_HISTORY_DAYS };
let showMovingAverage = true;
let showStepsMovingAverage = true;
let showCardioMovingAverage = true;
let cardioStatus = "loading";
let liveStatus = "checking";
let lastLiveSignature = "";
let lastSignalSignature = "";
let lastHistorySignature = "";
let lastEventsSignature = "";
let lastStatsSignature = "";
let lastStepsHistorySignature = "";
let lastStepsEventsSignature = "";
let lastHealthSnapshotSignature = "";
let lastCardioHistorySignature = "";
let stepsRefreshTimer = null;
let livePollTimer = null;
let backgroundPollTimer = null;
let stepsStream = null;
let stepsStreamRetryTimer = null;
let weightPulseUntil = 0;
const loadTimings = {};

function setLoadTiming(key, ms) {
  if (Number.isFinite(ms)) loadTimings[key] = ms;
}

function renderLoadTimings() {
  const parts = [
    ["waga", loadTimings.live],
    ["historia", loadTimings.history],
    ["stats", loadTimings.stats],
    ["kroki", loadTimings.stepsHistory],
    ["cardio", loadTimings.cardio],
    ["health", loadTimings.health],
    ["sync", loadTimings.summary],
  ]
    .map(([label, ms]) => loadTimeSuffix(ms, label))
    .filter(Boolean);
  return parts.length ? `Load: ${parts.join(" · ")}` : "Load: czekam";
}

function healthMetricValue(snapshot, key, suffix = "") {
  const value = snapshot?.payload?.metrics?.[key];
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const number = Number(value);
  const formatted = Number.isInteger(number)
    ? formatInt(number)
    : number.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
  return `${formatted}${suffix}`;
}

function healthNestedValue(snapshot, path) {
  let value = snapshot?.payload;
  for (const key of path) value = value?.[key];
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("pl-PL", { maximumFractionDigits: 1 });
}

function renderHealthDebug(snapshot) {
  if (!snapshot) {
    return `
      <section class="weight-cut-health-debug">
        <div class="weight-cut-health-debug-head">
          <span>Health Connect debug</span>
          <span>brak snapshotu</span>
        </div>
        <div class="weight-cut-health-debug-empty">Kliknij Sync now w apce na telefonie.</div>
      </section>
    `;
  }

  const payload = snapshot.payload || {};
  const json = JSON.stringify(snapshot, null, 2);
  const rows = [
    ["Dzień", snapshot.day || payload.day || "-"],
    ["Odebrane", snapshot.received_at || "-"],
    ["Kroki", healthMetricValue(snapshot, "steps")],
    ["Aktywne kcal", healthMetricValue(snapshot, "active_calories_kcal", " kcal")],
    ["Dystans", healthMetricValue(snapshot, "distance_meters", " m")],
    ["Przewyższenie", healthMetricValue(snapshot, "elevation_gained_meters", " m")],
    ["Sen sesje", payload.sleep?.session_count ?? "-"],
    ["Ćwiczenia", payload.exercise?.session_count ?? "-"],
    ["HR próbki", payload.heart_rate?.sample_count ?? "-"],
    ["HR avg", healthNestedValue(snapshot, ["heart_rate", "avg_bpm"])],
    ["SpO2 próbki", payload.oxygen_saturation?.sample_count ?? "-"],
    ["Speed próbki", payload.speed?.sample_count ?? "-"],
  ];

  return `
    <section class="weight-cut-health-debug">
      <div class="weight-cut-health-debug-head">
        <span>Health Connect debug</span>
        <span>${escapeHtml(snapshot.received_at || "")}</span>
      </div>
      <div class="weight-cut-health-debug-grid">
        ${rows.map(([label, value]) => `
          <div>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
          </div>
        `).join("")}
      </div>
      <details class="weight-cut-health-debug-json">
        <summary>Surowy JSON</summary>
        <pre>${escapeHtml(json)}</pre>
      </details>
    </section>
  `;
}

function renderHistoryModal() {
  if (!historyOpen) return "";
  const body = weightEvents.length
    ? weightEvents.map((event) => `
        <div class="weight-cut-history-row">
          <div>
            <div class="weight-cut-history-weight">${formatKg(event.weightKg)}</div>
            <div class="weight-cut-history-time">${escapeHtml(formatFullTimestamp(event.timestamp))}</div>
            <div class="weight-cut-history-meta">${escapeHtml(event.type || "pomiar")}${event.rssi !== null ? ` | RSSI ${event.rssi}` : ""}</div>
          </div>
          <button class="weight-cut-history-delete" type="button" data-delete-weight-event="${escapeHtml(event.timestamp)}">Usuń</button>
        </div>
      `).join("")
    : `<div class="weight-cut-history-empty">${historyStatus === "loading" ? "Ładuję historię" : "Brak pomiarów"}</div>`;

  return `
    <div class="weight-cut-modal-backdrop" id="weight-cut-history-backdrop">
      <section class="weight-cut-modal" role="dialog" aria-modal="true" aria-labelledby="weight-cut-history-title">
        <header class="weight-cut-modal-head">
          <div>
            <div class="weight-cut-modal-title" id="weight-cut-history-title">Historia pomiarów</div>
            <div class="weight-cut-modal-meta">${weightEvents.length ? `${weightEvents.length} wpisów` : ""}</div>
          </div>
          <button class="weight-cut-modal-close" id="weight-cut-history-close" type="button" aria-label="Zamknij">&times;</button>
        </header>
        <div class="weight-cut-history-list">
          ${body}
        </div>
      </section>
    </div>
  `;
}

function renderStepsHistoryModal() {
  if (!stepsHistoryOpen) return "";
  const body = stepsEvents.length
    ? stepsEvents.map((event) => `
        <div class="weight-cut-history-row">
          <div>
            <div class="weight-cut-history-weight">${formatInt(event.steps)} kroków łącznie</div>
            <div class="weight-cut-history-time">${escapeHtml(formatShortDateWithYear(event.day))}</div>
            <div class="weight-cut-history-meta">~${formatInt(estimateStepKcal(event.steps, liveWeight?.weightKg || store.weightKg || FALLBACK_WEIGHT_KG))} kcal · ręczne: ${formatInt(event.manualSteps)}${event.automaticAvailable ? ` · automatyczne: ${formatInt(event.automaticSteps)}` : ""}${event.virtualSteps > 0 ? ` · <span class="is-virtual-steps">spacerowe: +${formatInt(event.virtualSteps)}</span>` : ""}</div>
          </div>
          ${event.manualSteps > 0 ? `<div class="weight-cut-history-actions">
            <button class="weight-cut-history-edit" type="button" data-edit-steps-day="${escapeHtml(event.day)}" data-edit-steps-value="${event.manualSteps}">Edytuj ręczne</button>
            <button class="weight-cut-history-delete" type="button" data-delete-steps-event="${escapeHtml(event.day)}">Usuń ręczne</button>
          </div>` : `<div class="weight-cut-history-source-lock">${event.automaticAvailable ? "Health Connect" : "Zapis z Live Workout"}</div>`}
        </div>
      `).join("")
    : `<div class="weight-cut-history-empty">${stepsHistoryStatus === "loading" ? "Ładuję historię" : "Brak wpisów kroków"}</div>`;

  return `
    <div class="weight-cut-modal-backdrop" id="weight-cut-steps-backdrop">
      <section class="weight-cut-modal weight-cut-steps-modal" role="dialog" aria-modal="true" aria-labelledby="weight-cut-steps-title">
        <header class="weight-cut-modal-head">
          <div>
            <div class="weight-cut-modal-title" id="weight-cut-steps-title">Historia kroków</div>
            <div class="weight-cut-modal-meta">${stepsEvents.length ? `${stepsEvents.length} wpisów` : ""}</div>
          </div>
          <button class="weight-cut-modal-close" id="weight-cut-steps-close" type="button" aria-label="Zamknij">&times;</button>
        </header>
        <form class="weight-cut-steps-form" id="weight-cut-steps-form">
          <label>
            <span>Dzień</span>
            <span class="weight-cut-date-picker">
              <input id="weight-cut-steps-form-day" type="text" inputmode="numeric" value="${escapeHtml(formatDateInputPl(stepsEditDay))}" placeholder="dd.mm.rrrr" autocomplete="off" />
              <input id="weight-cut-steps-form-day-native" class="weight-cut-native-date" type="date" value="${stepsEditDay}" tabindex="-1" aria-hidden="true" />
              <button class="weight-cut-date-picker-button" id="weight-cut-steps-calendar" type="button" title="Kalendarz">Kal.</button>
            </span>
          </label>
          <label>
            <span>Kroki</span>
            <input id="weight-cut-steps-form-value" type="number" min="0" step="1" inputmode="numeric" value="${escapeHtml(stepsEditValue)}" placeholder="0" />
          </label>
          <button class="weight-cut-history-open" type="submit">Zapisz</button>
        </form>
        <div class="weight-cut-history-list">
          ${body}
        </div>
      </section>
    </div>
  `;
}

function render() {
  if (!root) return;

  const latestStepDay = stepsHistory.length ? stepsHistory[stepsHistory.length - 1] : null;
  const todaySteps = totalStepsForDay(todayIso());
  const weightKg = liveWeight?.weightKg ?? store.weightKg;
  const isWeightPulse = Date.now() < weightPulseUntil;
  const estimateWeight = weightKg || FALLBACK_WEIGHT_KG;
  const stepsChartKcal = estimateStepKcal(latestStepDay?.steps || todaySteps, estimateWeight);
  const signal = scaleSignal || (liveWeight && liveWeight.rssi !== null ? {
    rssi: liveWeight.rssi,
    signalPercent: liveWeight.signalPercent,
    ageSeconds: null,
  } : null);
  const signalPercent = signal?.signalPercent;
  const signalAge = signal?.ageSeconds;
  const signalMeta = signal
    ? `Sygnał ${signalPercent ?? "-"}% (${signal.rssi ?? "-"} dBm${formatAge(signalAge) ? `, ${formatAge(signalAge)}` : ""})`
    : "Sygnał: czekam";
  const measurementTime = liveWeight?.timestamp ? formatMeasurementTime(liveWeight.timestamp) : "";
  const today = todayIso();
  const todayEvent = weightEvents.find((event) => timestampDay(event.timestamp) === today) || null;
  const todayMeasurement = timestampDay(liveWeight?.timestamp) === today ? liveWeight : todayEvent;
  const todayMeasurementTime = todayMeasurement?.timestamp
    ? new Date(todayMeasurement.timestamp).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })
    : "";
  setDailyAchievement("weight", todayMeasurement ? {
    state: "complete",
    value: formatKg(todayMeasurement.weightKg),
    detail: `${formatKg(todayMeasurement.weightKg)}${todayMeasurementTime ? ` · ${todayMeasurementTime}` : ""}`,
  } : liveStatus === "checking" ? {
    state: "loading",
    value: "—",
    detail: "Sprawdzam ostatni pomiar",
    eligible: false,
  } : {
    state: "pending",
    value: "Brak pomiaru",
    detail: "Brak dzisiejszego pomiaru",
  });
  setDailyAchievement("steps", {
    state: todaySteps >= 10000 ? "complete" : "pending",
    value: formatInt(todaySteps),
    detail: todaySteps >= 10000
      ? `Cel osiągnięty · ${formatInt(todaySteps)} kroków`
      : `Brakuje ${formatInt(10000 - todaySteps)} kroków do celu`,
    progress: (todaySteps / 10000) * 100,
  });
  const eventPreviousDelta = previousDeltaFromEvents(liveWeight?.weightKg, liveWeight?.timestamp, weightEvents);
  const previousDelta = Number.isFinite(eventPreviousDelta)
    ? eventPreviousDelta
    : readNumber(weightStats?.changes?.previous);
  const previousDeltaText = formatDeltaCompact(previousDelta);
  const activeHistoryDays = getActiveHistoryDays();
  const activeHistoryOptions = getActiveHistoryOptions();
  const chartTitle = getChartTitle();
  const chartHistoryUnit = getChartHistoryUnit();
  const allHistoryRange = isAllHistoryRange(activeHistoryDays);
  const activeStepsHistoryDays = getActiveStepsHistoryDays();
  const activeStepsHistoryOptions = getActiveStepsHistoryOptions();
  const stepsChartTitle = getStepsChartTitle();
  const stepsChartHistoryUnit = getStepsChartHistoryUnit();
  const allStepsHistoryRange = isAllHistoryRange(activeStepsHistoryDays);
  const activeCardioHistoryDays = getActiveCardioHistoryDays();
  const activeCardioHistoryOptions = getActiveCardioHistoryOptions();
  const cardioChartTitle = getCardioChartTitle();
  const allCardioHistoryRange = isAllHistoryRange(activeCardioHistoryDays);
  const canGoForward = !allHistoryRange && !isSameOrAfterToday(chartEndDay);
  const canStepsGoForward = !allStepsHistoryRange && !isSameOrAfterToday(stepsChartEndDay);
  const canCardioGoForward = !allCardioHistoryRange && !isSameOrAfterToday(cardioChartEndDay);
  const weightStatus = liveWeight
    ? ""
    : liveStatus === "offline"
      ? "Brak połączenia z lokalnym API"
      : liveStatus === "empty"
        ? "Wejdź na wagę, żeby złapać pomiar"
        : "Czekam na wagę";

  root.innerHTML = `
    <header class="weight-cut-tiles-head">
      <div class="title" id="weight-cut-title">
        <svg class="ico" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm2 4v8h10V8H7zm2 2h6v2H9v-2z" />
        </svg>
        <div>
          Redukcja
          <div class="meta">Podstawowe kafle dzienne</div>
        </div>
      </div>
      <label class="weight-cut-date">
        <span>Dzień</span>
        <input id="weight-cut-date" type="date" value="${dateKey}" />
      </label>
    </header>

    <div class="weight-cut-tiles-grid">
      <article class="weight-cut-tile weight-cut-weight-panel">
        <div class="weight-cut-weight-main">
          <div class="weight-cut-weight-reading">
            <div class="weight-cut-tile-label">Aktualna waga</div>
            <div class="weight-cut-tile-value ${isWeightPulse ? "is-updating" : ""}">
              ${formatKg(weightKg)}
              ${previousDeltaText ? `<span class="weight-cut-value-delta ${statClass(previousDelta)}">(${previousDeltaText})</span>` : ""}
            </div>
            ${measurementTime ? `<div class="weight-cut-measurement-time">${measurementTime}</div>` : ""}
            ${weightStatus ? `<div class="weight-cut-live-note">${weightStatus}</div>` : ""}
            <div class="weight-cut-signal ${isWeightPulse ? "is-updating" : ""}" title="${signalMeta}">
              <div class="weight-cut-signal-head">
                <span>${signalMeta}</span>
              </div>
              <div class="weight-cut-signal-track" aria-hidden="true">
                <span style="width:${Number.isFinite(signalPercent) ? signalPercent : 0}%"></span>
              </div>
            </div>
          </div>
          ${renderStatsPanel(weightStats)}
        </div>
      </article>

    </div>

    <section class="weight-cut-chart">
      <div class="weight-cut-chart-head">
        <div>
          <span>${chartTitle}</span>
          <span class="weight-cut-chart-range">${formatDateRange(weightHistory)}</span>
        </div>
        <div class="weight-cut-chart-actions">
          <button class="weight-cut-chart-nav" id="weight-cut-chart-prev" type="button" aria-label="Poprzedni zakres" ${allHistoryRange ? "disabled" : ""}>&lsaquo;</button>
          <button class="weight-cut-chart-nav" id="weight-cut-chart-next" type="button" aria-label="Następny zakres" ${canGoForward ? "" : "disabled"}>&rsaquo;</button>
          <select class="weight-cut-chart-zoom" id="weight-cut-chart-zoom" aria-label="Zakres wykresu">
            ${activeHistoryOptions.map((days) => `
              <option value="${days}" ${days === activeHistoryDays ? "selected" : ""}>${formatHistoryOption(days, weightChartMode)}</option>
            `).join("")}
          </select>
          <button class="weight-cut-ma-toggle ${weightChartMode === "daily" ? "is-active" : ""}" type="button" data-weight-chart-mode="daily" title="Jeden punkt to średnia z jednego dnia.">
            Dzień
          </button>
          <button class="weight-cut-ma-toggle ${weightChartMode === "weekly" ? "is-active" : ""}" type="button" data-weight-chart-mode="weekly" title="Jeden punkt to średnia z 7 dni.">
            Tydzień
          </button>
          <button class="weight-cut-ma-toggle ${weightChartMode === "biweekly" ? "is-active" : ""}" type="button" data-weight-chart-mode="biweekly" title="Jeden punkt to średnia z 14 dni.">
            2 tyg.
          </button>
          <button class="weight-cut-ma-toggle ${weightChartMode === "monthly" ? "is-active" : ""}" type="button" data-weight-chart-mode="monthly" title="Jeden punkt to średnia z 30 dni.">
            Miesiąc
          </button>
          <button class="weight-cut-ma-toggle ${weightChartMode === "daily" && showMovingAverage ? "is-active" : ""}" id="weight-cut-ma-toggle" type="button" ${weightChartMode === "daily" ? "" : "disabled"} title="${weightChartMode === "daily" ? "Średnia krocząca 7 dni - łagodzi pojedyncze skoki pomiarów." : "MA7 działa tylko w widoku dziennym."}">
            MA7
          </button>
          <button class="weight-cut-history-open" id="weight-cut-report" type="button" title="Pobierz raport dzienny wagi .txt">
            Raport
          </button>
          <button class="weight-cut-history-open" id="weight-cut-combined-report" type="button" title="Pobierz raport zbiorczy .txt">
            Zbiorczy
          </button>
          <button class="weight-cut-history-open" id="weight-cut-history-open" type="button">
            Historia${weightHistory.length ? ` | ${weightHistory.length} ${chartHistoryUnit}` : ""}
          </button>
        </div>
      </div>
      ${renderWeightChart(weightHistory, weightChartMode === "daily" && showMovingAverage)}
    </section>

    <section class="weight-cut-chart weight-cut-cardio-chart">
      <div class="weight-cut-chart-head">
        <div>
          <span>${cardioChartTitle}</span>
          <span class="weight-cut-chart-range">${formatDateRange(cardioHistory)}</span>
          <span class="weight-cut-cardio-legend"><i></i> łącznie cardio <b></b> MA7 · punkt: czerwony rower / niebieski spacer</span>
        </div>
        <div class="weight-cut-chart-actions">
          <button class="weight-cut-chart-nav" id="weight-cut-cardio-chart-prev" type="button" aria-label="Poprzedni zakres cardio" ${allCardioHistoryRange ? "disabled" : ""}>&lsaquo;</button>
          <button class="weight-cut-chart-nav" id="weight-cut-cardio-chart-next" type="button" aria-label="Następny zakres cardio" ${canCardioGoForward ? "" : "disabled"}>&rsaquo;</button>
          <select class="weight-cut-chart-zoom" id="weight-cut-cardio-chart-zoom" aria-label="Zakres wykresu cardio">
            ${activeCardioHistoryOptions.map((days) => `
              <option value="${days}" ${days === activeCardioHistoryDays ? "selected" : ""}>${formatHistoryOption(days, cardioChartMode)}</option>
            `).join("")}
          </select>
          <button class="weight-cut-ma-toggle ${cardioChartMode === "daily" ? "is-active" : ""}" type="button" data-cardio-chart-mode="daily" title="Jeden punkt to suma aktywnych kalorii cardio z jednego dnia.">
            Dzień
          </button>
          <button class="weight-cut-ma-toggle ${cardioChartMode === "weekly" ? "is-active" : ""}" type="button" data-cardio-chart-mode="weekly" title="Jeden punkt to średnia dzienna z 7 dni.">
            Tydzień
          </button>
          <button class="weight-cut-ma-toggle ${cardioChartMode === "biweekly" ? "is-active" : ""}" type="button" data-cardio-chart-mode="biweekly" title="Jeden punkt to średnia dzienna z 14 dni.">
            2 tyg.
          </button>
          <button class="weight-cut-ma-toggle ${cardioChartMode === "monthly" ? "is-active" : ""}" type="button" data-cardio-chart-mode="monthly" title="Jeden punkt to średnia dzienna z 30 dni.">
            Miesiąc
          </button>
          <button class="weight-cut-ma-toggle ${cardioChartMode === "daily" && showCardioMovingAverage ? "is-active" : ""}" id="weight-cut-cardio-ma-toggle" type="button" ${cardioChartMode === "daily" ? "" : "disabled"} title="${cardioChartMode === "daily" ? "MA7 kalorii cardio." : "MA7 działa tylko w widoku dziennym."}">
            MA7
          </button>
        </div>
      </div>
      ${renderCardioChart(cardioHistory, cardioChartMode === "daily" && showCardioMovingAverage)}
      ${renderCardioInsights()}
    </section>

    <section class="weight-cut-chart weight-cut-steps-chart">
      <div class="weight-cut-chart-head">
        <div>
          <span>${stepsChartTitle}</span>
          <span class="weight-cut-chart-range">${formatDateRange(stepsHistory)}${latestStepDay ? ` | ~${formatInt(stepsChartKcal)} kcal` : ""}</span>
          <span class="weight-cut-steps-legend"><i></i> ręczne <em></em> automatyczne <b></b> spacerowe · kolor punktu pokazuje proporcję · jasny = cel 10 000</span>
        </div>
        <div class="weight-cut-chart-actions">
          <button class="weight-cut-chart-nav" id="weight-cut-steps-chart-prev" type="button" aria-label="Poprzedni zakres kroków" ${allStepsHistoryRange ? "disabled" : ""}>&lsaquo;</button>
          <button class="weight-cut-chart-nav" id="weight-cut-steps-chart-next" type="button" aria-label="Następny zakres kroków" ${canStepsGoForward ? "" : "disabled"}>&rsaquo;</button>
          <select class="weight-cut-chart-zoom" id="weight-cut-steps-chart-zoom" aria-label="Zakres wykresu kroków">
            ${activeStepsHistoryOptions.map((days) => `
              <option value="${days}" ${days === activeStepsHistoryDays ? "selected" : ""}>${formatHistoryOption(days, stepsChartMode)}</option>
            `).join("")}
          </select>
          <button class="weight-cut-ma-toggle ${stepsChartMode === "daily" ? "is-active" : ""}" type="button" data-steps-chart-mode="daily" title="Jeden punkt to suma kroków z jednego dnia.">
            Dzień
          </button>
          <button class="weight-cut-ma-toggle ${stepsChartMode === "weekly" ? "is-active" : ""}" type="button" data-steps-chart-mode="weekly" title="Jeden punkt to średnia dzienna z 7 dni.">
            Tydzień
          </button>
          <button class="weight-cut-ma-toggle ${stepsChartMode === "biweekly" ? "is-active" : ""}" type="button" data-steps-chart-mode="biweekly" title="Jeden punkt to średnia dzienna z 14 dni.">
            2 tyg.
          </button>
          <button class="weight-cut-ma-toggle ${stepsChartMode === "monthly" ? "is-active" : ""}" type="button" data-steps-chart-mode="monthly" title="Jeden punkt to średnia dzienna z 30 dni.">
            Miesiąc
          </button>
          <button class="weight-cut-ma-toggle ${stepsChartMode === "daily" && showStepsMovingAverage ? "is-active" : ""}" id="weight-cut-steps-ma-toggle" type="button" ${stepsChartMode === "daily" ? "" : "disabled"} title="${stepsChartMode === "daily" ? "MA7 kroków - wygładza pojedyncze skoki aktywności." : "MA7 działa tylko w widoku dziennym."}">
            MA7
          </button>
          <button class="weight-cut-history-open" id="weight-cut-steps-report" type="button" title="Pobierz raport dzienny krokow .txt">
            Raport
          </button>
          <button class="weight-cut-history-open" id="weight-cut-steps-history-open" type="button">
            Historia${stepsHistory.length ? ` | ${stepsHistory.length} ${stepsChartHistoryUnit}` : ""}
          </button>
        </div>
      </div>
      ${renderStepsChart(stepsHistory, estimateWeight, stepsChartMode === "daily" && showStepsMovingAverage)}
    </section>

    ${renderHistoryModal()}
    ${renderStepsHistoryModal()}
    ${renderHealthDebug(healthSnapshot)}
    <footer class="hb-foot muted weight-cut-footer">${renderLoadTimings()}</footer>
  `;

  bindEvents();
}

function setWeightPanelExpanded(buttonId, panelId, expanded) {
  const button = document.getElementById(buttonId);
  const panel = document.getElementById(panelId);
  button?.classList.toggle("is-active", expanded);
  button?.setAttribute("aria-expanded", expanded ? "true" : "false");
  panel?.classList.toggle("is-open", expanded);
  panel?.setAttribute("aria-hidden", expanded ? "false" : "true");
  panel?.toggleAttribute("inert", !expanded);
}

function bindEvents() {
  document.getElementById("weight-cut-date")?.addEventListener("change", (event) => {
    dateKey = event.currentTarget.value || todayIso();
    render();
  });

  document.getElementById("weight-cut-report")?.addEventListener("click", () => {
    generateWeightDailyReport({
      days: getDailyReportDays(getActiveHistoryDays()),
      end: chartEndDay,
    }).catch((error) => console.error("Weight report failed", error));
  });

  document.getElementById("weight-cut-combined-report")?.addEventListener("click", () => {
    generateCombinedDailyReport({
      days: maxDailyReportDays(getActiveHistoryDays(), getActiveStepsHistoryDays()),
      end: latestReportEnd(chartEndDay, stepsChartEndDay),
    }).catch((error) => console.error("Combined report failed", error));
  });

  document.getElementById("weight-cut-steps-report")?.addEventListener("click", () => {
    generateStepsDailyReport({
      days: getDailyReportDays(getActiveStepsHistoryDays()),
      end: stepsChartEndDay,
    }).catch((error) => console.error("Steps report failed", error));
  });

  document.getElementById("weight-cut-history-open")?.addEventListener("click", () => {
    historyOpen = true;
    historyStatus = "loading";
    render();
    refreshEvents();
  });

  document.getElementById("weight-cut-steps-history-open")?.addEventListener("click", () => {
    stepsHistoryOpen = true;
    stepsHistoryStatus = "loading";
    stepsEditDay = dateKey || todayIso();
    stepsEditValue = stepsForDay(stepsEditDay) || "";
    render();
    refreshStepsEvents();
  });

  document.getElementById("weight-cut-records-toggle")?.addEventListener("click", () => {
    weightRecordsExpanded = !weightRecordsExpanded;
    setWeightPanelExpanded("weight-cut-records-toggle", "weight-cut-records-panel", weightRecordsExpanded);
  });

  document.getElementById("weight-cut-goals-toggle")?.addEventListener("click", () => {
    weightGoalsExpanded = !weightGoalsExpanded;
    setWeightPanelExpanded("weight-cut-goals-toggle", "weight-cut-goals-panel", weightGoalsExpanded);
  });

  const maTargetInput = document.getElementById("weight-cut-ma-target");
  const commitMaTarget = () => {
    const target = saveMaTargetKg(maTargetInput?.value);
    if (!Number.isFinite(target)) {
      if (maTargetInput instanceof HTMLInputElement) maTargetInput.value = String(weightMaTargetKg);
      return;
    }
    if (target === weightMaTargetKg) return;
    weightMaTargetKg = target;
    render();
  };
  maTargetInput?.addEventListener("change", commitMaTarget);
  maTargetInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    commitMaTarget();
  });

  document.getElementById("weight-cut-goal-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.getElementById("weight-cut-goal-new");
    const target = readNumber(input?.value);
    if (!Number.isFinite(target) || target <= 0) return;
    weightGoalTargets = saveGoalTargets([...weightGoalTargets, target]);
    render();
  });

  root.querySelectorAll("[data-delete-weight-goal-index]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const index = Math.max(0, Math.round(readNumber(event.currentTarget.dataset.deleteWeightGoalIndex) || 0));
      weightGoalTargets = saveGoalTargets(weightGoalTargets.filter((_, valueIndex) => valueIndex !== index));
      render();
    });
  });

  document.getElementById("weight-cut-chart-prev")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveHistoryDays())) return;
    chartEndDay = addDaysIso(chartEndDay, -getActiveHistoryDays());
    refreshHistory();
  });

  document.getElementById("weight-cut-chart-next")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveHistoryDays())) return;
    chartEndDay = addDaysIso(chartEndDay, getActiveHistoryDays());
    if (chartEndDay > todayIso()) chartEndDay = todayIso();
    refreshHistory();
  });

  document.getElementById("weight-cut-chart-zoom")?.addEventListener("change", (event) => {
    const fallbackDays = isPeriodChartMode() ? getPeriodHistoryDays() : DEFAULT_HISTORY_DAYS;
    const options = getActiveHistoryOptions();
    const rawValue = event.currentTarget.value;
    const nextDays = rawValue === HISTORY_ALL_VALUE
      ? HISTORY_ALL_VALUE
      : Math.max(1, Math.round(readNumber(rawValue) || fallbackDays));
    if (isPeriodChartMode()) {
      setPeriodHistoryDays(weightChartMode, options.includes(nextDays) ? nextDays : fallbackDays);
    } else {
      historyDays = options.includes(nextDays) ? nextDays : DEFAULT_HISTORY_DAYS;
    }
    refreshHistory();
  });

  document.querySelectorAll("[data-weight-chart-mode]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const nextMode = event.currentTarget.dataset.weightChartMode;
      if (nextMode !== "daily" && !PERIOD_DAYS[nextMode]) return;
      if (weightChartMode === nextMode) return;
      weightChartMode = nextMode;
      chartEndDay = todayIso();
      refreshHistory();
    });
  });

  document.getElementById("weight-cut-ma-toggle")?.addEventListener("click", () => {
    showMovingAverage = !showMovingAverage;
    render();
  });

  document.getElementById("weight-cut-cardio-chart-prev")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveCardioHistoryDays())) return;
    cardioChartEndDay = addDaysIso(cardioChartEndDay, -getActiveCardioHistoryDays());
    rebuildCardioHistory();
    render();
  });

  document.getElementById("weight-cut-cardio-chart-next")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveCardioHistoryDays())) return;
    cardioChartEndDay = addDaysIso(cardioChartEndDay, getActiveCardioHistoryDays());
    if (cardioChartEndDay > todayIso()) cardioChartEndDay = todayIso();
    rebuildCardioHistory();
    render();
  });

  document.getElementById("weight-cut-cardio-chart-zoom")?.addEventListener("change", (event) => {
    const fallbackDays = isCardioPeriodChartMode() ? getCardioPeriodHistoryDays() : DEFAULT_HISTORY_DAYS;
    const options = getActiveCardioHistoryOptions();
    const rawValue = event.currentTarget.value;
    const nextDays = rawValue === HISTORY_ALL_VALUE
      ? HISTORY_ALL_VALUE
      : Math.max(1, Math.round(readNumber(rawValue) || fallbackDays));
    if (isCardioPeriodChartMode()) {
      setCardioPeriodHistoryDays(cardioChartMode, options.includes(nextDays) ? nextDays : fallbackDays);
    } else {
      cardioHistoryDays = options.includes(nextDays) ? nextDays : DEFAULT_HISTORY_DAYS;
    }
    rebuildCardioHistory();
    render();
  });

  document.querySelectorAll("[data-cardio-chart-mode]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const nextMode = event.currentTarget.dataset.cardioChartMode;
      if (nextMode !== "daily" && !PERIOD_DAYS[nextMode]) return;
      if (cardioChartMode === nextMode) return;
      cardioChartMode = nextMode;
      cardioChartEndDay = todayIso();
      rebuildCardioHistory();
      render();
    });
  });

  document.getElementById("weight-cut-cardio-ma-toggle")?.addEventListener("click", () => {
    showCardioMovingAverage = !showCardioMovingAverage;
    render();
  });

  document.getElementById("weight-cut-steps-chart-prev")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveStepsHistoryDays())) return;
    stepsChartEndDay = addDaysIso(stepsChartEndDay, -getActiveStepsHistoryDays());
    refreshStepsHistory();
  });

  document.getElementById("weight-cut-steps-chart-next")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveStepsHistoryDays())) return;
    stepsChartEndDay = addDaysIso(stepsChartEndDay, getActiveStepsHistoryDays());
    if (stepsChartEndDay > todayIso()) stepsChartEndDay = todayIso();
    refreshStepsHistory();
  });

  document.getElementById("weight-cut-steps-chart-zoom")?.addEventListener("change", (event) => {
    const fallbackDays = isStepsPeriodChartMode() ? getStepsPeriodHistoryDays() : DEFAULT_HISTORY_DAYS;
    const options = getActiveStepsHistoryOptions();
    const rawValue = event.currentTarget.value;
    const nextDays = rawValue === HISTORY_ALL_VALUE
      ? HISTORY_ALL_VALUE
      : Math.max(1, Math.round(readNumber(rawValue) || fallbackDays));
    if (isStepsPeriodChartMode()) {
      setStepsPeriodHistoryDays(stepsChartMode, options.includes(nextDays) ? nextDays : fallbackDays);
    } else {
      stepsHistoryDays = options.includes(nextDays) ? nextDays : DEFAULT_HISTORY_DAYS;
    }
    refreshStepsHistory();
  });

  document.querySelectorAll("[data-steps-chart-mode]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const nextMode = event.currentTarget.dataset.stepsChartMode;
      if (nextMode !== "daily" && !PERIOD_DAYS[nextMode]) return;
      if (stepsChartMode === nextMode) return;
      stepsChartMode = nextMode;
      stepsChartEndDay = todayIso();
      refreshStepsHistory();
    });
  });

  document.getElementById("weight-cut-steps-ma-toggle")?.addEventListener("click", () => {
    showStepsMovingAverage = !showStepsMovingAverage;
    render();
  });

  document.getElementById("weight-cut-history-close")?.addEventListener("click", () => {
    historyOpen = false;
    render();
  });

  document.getElementById("weight-cut-history-backdrop")?.addEventListener("click", (event) => {
    if (event.target?.id === "weight-cut-history-backdrop") {
      historyOpen = false;
      render();
    }
  });

  document.getElementById("weight-cut-steps-close")?.addEventListener("click", () => {
    stepsHistoryOpen = false;
    render();
  });

  document.getElementById("weight-cut-steps-backdrop")?.addEventListener("click", (event) => {
    if (event.target?.id === "weight-cut-steps-backdrop") {
      stepsHistoryOpen = false;
      render();
    }
  });

  const stepDayInput = document.getElementById("weight-cut-steps-form-day");
  const stepDayNative = document.getElementById("weight-cut-steps-form-day-native");
  const openStepCalendar = () => {
    const anchor = document.querySelector(".weight-cut-date-picker");
    openDatePopover({
      anchor,
      selectedDay: stepsEditDay || todayIso(),
      parseInput: parseStepDayInput,
      textInput: stepDayInput,
      onSelect: (nextDay) => {
        stepsEditDay = nextDay || todayIso();
        if (stepDayInput instanceof HTMLInputElement) {
          stepDayInput.value = formatDateInputPl(stepsEditDay);
        }
        if (stepDayNative instanceof HTMLInputElement) {
          stepDayNative.value = stepsEditDay;
        }
      },
    });
  };

  stepDayInput?.addEventListener("click", openStepCalendar);
  document.getElementById("weight-cut-steps-calendar")?.addEventListener("click", openStepCalendar);
  stepDayNative?.addEventListener("change", () => {
    const nextDay = stepDayNative.value || todayIso();
    stepsEditDay = nextDay;
    if (stepDayInput instanceof HTMLInputElement) {
      stepDayInput.value = formatDateInputPl(nextDay);
    }
  });

  document.getElementById("weight-cut-steps-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const rawDay = document.getElementById("weight-cut-steps-form-day")?.value;
    const nativeDay = document.getElementById("weight-cut-steps-form-day-native")?.value;
    const day = parseStepDayInput(rawDay) || nativeDay || stepsEditDay || todayIso();
    const steps = Math.max(0, Math.round(readNumber(document.getElementById("weight-cut-steps-form-value")?.value) || 0));
    stepsEditDay = day;
    stepsEditValue = String(steps || "");
    saveSteps(day, steps);
  });

  root.querySelectorAll("[data-delete-weight-event]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteEvent(button.getAttribute("data-delete-weight-event"));
    });
  });

  root.querySelectorAll("[data-delete-steps-event]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteSteps(button.getAttribute("data-delete-steps-event"));
    });
  });

  root.querySelectorAll("[data-edit-steps-day]").forEach((button) => {
    button.addEventListener("click", () => {
      const day = button.getAttribute("data-edit-steps-day") || todayIso();
      const steps = Math.max(0, Math.round(readNumber(button.getAttribute("data-edit-steps-value")) || 0));
      stepsEditDay = day;
      stepsEditValue = String(steps || "");
      const dayInput = document.getElementById("weight-cut-steps-form-day");
      const dayNative = document.getElementById("weight-cut-steps-form-day-native");
      const valueInput = document.getElementById("weight-cut-steps-form-value");
      if (dayInput instanceof HTMLInputElement) dayInput.value = formatDateInputPl(day);
      if (dayNative instanceof HTMLInputElement) dayNative.value = day;
      if (valueInput instanceof HTMLInputElement) {
        valueInput.value = String(steps || "");
        valueInput.focus();
        valueInput.select();
      }
    });
  });

  root.querySelectorAll(".weight-cut-chart-dot, .weight-cut-cardio-dot, .weight-cut-steps-dot").forEach((dot) => {
    dot.addEventListener("click", selectChartDay);
    dot.addEventListener("mouseenter", showChartTooltip);
    dot.addEventListener("mousemove", moveChartTooltip);
    dot.addEventListener("mouseleave", hideChartTooltip);
    dot.addEventListener("focus", showChartTooltip);
    dot.addEventListener("blur", hideChartTooltip);
  });
}

function selectChartDay(event) {
  const day = event.currentTarget?.dataset?.chartDate || "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return;
  dateKey = day;
  hideChartTooltip();
  render();
}

function ensureChartTooltip() {
  let tooltip = document.getElementById("weight-cut-chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "weight-cut-chart-tooltip";
    tooltip.className = "weight-cut-chart-tooltip";
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function tooltipHtml(target) {
  const kind = target.dataset.chartKind || "";
  const kindText = kind === "dummy" ? "brak pomiaru" : kind;
  return `
    <div class="weight-cut-chart-tooltip-day">${escapeHtml(target.dataset.chartDay || "")}</div>
    <div class="weight-cut-chart-tooltip-weight">${escapeHtml(target.dataset.chartWeight || "")}</div>
    <div class="weight-cut-chart-tooltip-kind">${escapeHtml(kindText)}</div>
  `;
}

function positionChartTooltip(tooltip, x, y) {
  const gap = 12;
  const rect = tooltip.getBoundingClientRect();
  const nextX = Math.min(window.innerWidth - rect.width - 8, Math.max(8, x + gap));
  const nextY = Math.min(window.innerHeight - rect.height - 8, Math.max(8, y + gap));
  tooltip.style.left = `${nextX}px`;
  tooltip.style.top = `${nextY}px`;
}

function showChartTooltip(event) {
  const target = event.currentTarget;
  if (!(target instanceof SVGCircleElement)) return;
  const tooltip = ensureChartTooltip();
  tooltip.innerHTML = tooltipHtml(target);
  tooltip.classList.add("is-visible");
  const rect = target.getBoundingClientRect();
  positionChartTooltip(tooltip, rect.left + rect.width / 2, rect.top + rect.height / 2);
}

function moveChartTooltip(event) {
  const tooltip = document.getElementById("weight-cut-chart-tooltip");
  if (!tooltip?.classList.contains("is-visible")) return;
  positionChartTooltip(tooltip, event.clientX, event.clientY);
}

function hideChartTooltip() {
  document.getElementById("weight-cut-chart-tooltip")?.classList.remove("is-visible");
}

async function refreshLiveWeight() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const response = await fetch(LIVE_WEIGHT_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setLoadTiming("live", stopTimer());
    const nextLiveWeight = normalizeLiveWeight(payload);

    const previousTimestamp = liveWeight?.timestamp ?? null;
    liveStatus = nextLiveWeight ? "live" : "empty";
    liveWeight = nextLiveWeight;
    const measurementChanged = Boolean(
      nextLiveWeight?.timestamp && nextLiveWeight.timestamp !== previousTimestamp
    );
    if (nextLiveWeight) {
      if (previousTimestamp && measurementChanged) {
        weightPulseUntil = Date.now() + 1800;
      }
      store = saveStore({ ...store, weightKg: nextLiveWeight.weightKg });
      if (nextLiveWeight.rssi !== null) {
        scaleSignal = {
          timestamp: nextLiveWeight.timestamp,
          rssi: nextLiveWeight.rssi,
          signalPercent: nextLiveWeight.signalPercent,
          ageSeconds: null,
        };
      }
    }

    const signature = JSON.stringify({
      status: liveStatus,
      weight: liveWeight?.weightKg ?? null,
      timestamp: liveWeight?.timestamp ?? null,
      rssi: liveWeight?.rssi ?? null,
    });
    if (signature !== lastLiveSignature) {
      lastLiveSignature = signature;
      render();
      if (weightPulseUntil > Date.now()) {
        setTimeout(() => render(), Math.max(0, weightPulseUntil - Date.now()));
      }
      if (measurementChanged) {
        await Promise.all([refreshStats(), refreshHistory(), refreshEvents()]);
      }
    }
  } catch {
    liveStatus = "offline";
    const signature = JSON.stringify({ status: liveStatus });
    if (signature !== lastLiveSignature) {
      lastLiveSignature = signature;
      render();
    }
  }
}

async function refreshSignal() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const response = await fetch(SIGNAL_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setLoadTiming("signal", stopTimer());
    scaleSignal = normalizeSignal(payload);
  } catch {
    scaleSignal = null;
  }

  const signature = JSON.stringify({
    rssi: scaleSignal?.rssi ?? null,
    signalPercent: scaleSignal?.signalPercent ?? null,
    ageSeconds: scaleSignal?.ageSeconds ?? null,
  });
  if (signature !== lastSignalSignature) {
    lastSignalSignature = signature;
    render();
  }
}

async function refreshHistory() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    if (isPeriodChartMode()) {
      const response = await fetch(EVENTS_ENDPOINT, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      weightEvents = normalizeEvents(payload);
      historyStatus = "idle";
      weightHistory = buildPeriodWeightHistory(
        weightEvents,
        getPeriodHistoryDays(),
        chartEndDay,
        PERIOD_DAYS[weightChartMode] || 7,
      );
      const eventsSignature = JSON.stringify(weightEvents);
      if (eventsSignature !== lastEventsSignature) lastEventsSignature = eventsSignature;
    } else {
      const params = new URLSearchParams({
        days: String(historyDays),
        fill: "1",
        end: chartEndDay,
      });
      const response = await fetch(`${HISTORY_ENDPOINT}?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      weightHistory = normalizeHistory(payload);
    }
    setLoadTiming("history", stopTimer());
  } catch {
    weightHistory = [];
  }

  const signature = JSON.stringify({
    mode: weightChartMode,
    days: getActiveHistoryDays(),
    end: chartEndDay,
    rows: weightHistory,
  });
  if (signature !== lastHistorySignature) {
    lastHistorySignature = signature;
    render();
  }
}

async function refreshEvents() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const response = await fetch(EVENTS_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setLoadTiming("events", stopTimer());
    weightEvents = normalizeEvents(payload);
    historyStatus = "idle";
  } catch {
    historyStatus = "error";
  }

  const signature = JSON.stringify(weightEvents);
  if (signature !== lastEventsSignature || historyOpen) {
    lastEventsSignature = signature;
    render();
  }
}

async function refreshStats() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const response = await fetch(STATS_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setLoadTiming("stats", stopTimer());
    weightStats = normalizeStats(payload);
  } catch {
    weightStats = null;
  }

  const signature = JSON.stringify(weightStats);
  if (signature !== lastStatsSignature) {
    lastStatsSignature = signature;
    render();
  }
}

async function refreshStepsHistory() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const activeDays = getActiveStepsHistoryDays();
    let dailyRows = [];
    if (isAllHistoryRange(activeDays)) {
      const response = await fetch(STEPS_EVENTS_ENDPOINT, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      stepsEvents = normalizeStepEvents(payload);
      stepsHistoryStatus = "idle";
      dailyRows = stepsEventsToHistoryRows(stepsEvents, stepsChartEndDay);
    } else {
      const params = new URLSearchParams({
        days: String(activeDays),
        end: stepsChartEndDay,
      });
      const response = await fetch(`${STEPS_HISTORY_ENDPOINT}?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      dailyRows = normalizeStepHistory(payload);
    }
    setLoadTiming("stepsHistory", stopTimer());
    stepsHistory = isStepsPeriodChartMode()
      ? buildPeriodStepsHistory(dailyRows, activeDays, stepsChartEndDay, PERIOD_DAYS[stepsChartMode] || 7)
      : dailyRows;
  } catch {
    stepsHistory = [];
  }

  const signature = JSON.stringify({
    mode: stepsChartMode,
    days: getActiveStepsHistoryDays(),
    end: stepsChartEndDay,
    rows: stepsHistory,
  });
  if (signature !== lastStepsHistorySignature) {
    lastStepsHistorySignature = signature;
    render();
  }
}

async function refreshCardioHistory() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const response = await fetch(CARDIO_RANKING_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setLoadTiming("cardio", stopTimer());
    cardioRanking = normalizeCyclingCalorieRanking(payload?.days);
    cardioStatus = "idle";
    rebuildCardioHistory();
  } catch {
    cardioRanking = [];
    cardioHistory = [];
    cardioStatus = "error";
  }

  const signature = JSON.stringify({
    mode: cardioChartMode,
    days: getActiveCardioHistoryDays(),
    end: cardioChartEndDay,
    rows: cardioHistory,
    status: cardioStatus,
  });
  if (signature !== lastCardioHistorySignature) {
    lastCardioHistorySignature = signature;
    render();
  }
}

async function refreshStepsEvents() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const response = await fetch(STEPS_EVENTS_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setLoadTiming("stepsEvents", stopTimer());
    stepsEvents = normalizeStepEvents(payload);
    stepsHistoryStatus = "idle";
  } catch {
    stepsHistoryStatus = "error";
  }

  const signature = JSON.stringify(stepsEvents);
  if (signature !== lastStepsEventsSignature || stepsHistoryOpen) {
    lastStepsEventsSignature = signature;
    render();
  }
}

async function refreshHealthSnapshot() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const response = await fetch(HEALTH_LATEST_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setLoadTiming("health", stopTimer());
    healthSnapshot = payload?.ok ? payload.snapshot : null;
  } catch {
    healthSnapshot = null;
  }

  const signature = JSON.stringify(healthSnapshot);
  if (signature !== lastHealthSnapshotSignature) {
    lastHealthSnapshotSignature = signature;
    render();
  }
}

function refreshStepsNow() {
  return Promise.all([refreshStepsHistory(), refreshStepsEvents(), refreshHealthSnapshot()]);
}

function scheduleStepsRefresh(delay = 250) {
  if (document.hidden) return;
  if (stepsRefreshTimer) window.clearTimeout(stepsRefreshTimer);
  stepsRefreshTimer = window.setTimeout(() => {
    stepsRefreshTimer = null;
    refreshStepsNow();
  }, delay);
}

function startStepsStream() {
  if (!root || document.hidden || stepsStream || typeof EventSource === "undefined") return;
  try {
    const source = new EventSource(STEPS_STREAM_ENDPOINT);
    stepsStream = source;
    source.addEventListener("steps", () => scheduleStepsRefresh(50));
    source.onerror = () => {
      source.close();
      if (stepsStream === source) stepsStream = null;
      if (!document.hidden) {
        stepsStreamRetryTimer = window.setTimeout(() => {
          stepsStreamRetryTimer = null;
          startStepsStream();
        }, 10000);
      }
    };
  } catch {}
}

function stopStepsStream() {
  if (stepsStreamRetryTimer) window.clearTimeout(stepsStreamRetryTimer);
  stepsStreamRetryTimer = null;
  stepsStream?.close();
  stepsStream = null;
}

function refreshBackgroundFallbackNow() {
  const requests = [refreshSignal(), refreshHistory(), refreshStats(), refreshStepsHistory(), refreshHealthSnapshot()];
  if (!isPeriodChartMode()) requests.push(refreshEvents());
  if (!isAllHistoryRange(getActiveStepsHistoryDays())) requests.push(refreshStepsEvents());
  return Promise.all(requests);
}

function applyBackgroundSummary(payload) {
  scaleSignal = normalizeSignal(payload?.signal);
  weightEvents = normalizeEvents(payload?.weight_events);
  weightStats = normalizeStats(payload?.weight_stats);
  historyStatus = "idle";

  weightHistory = isPeriodChartMode()
    ? buildPeriodWeightHistory(
      weightEvents,
      getPeriodHistoryDays(),
      chartEndDay,
      PERIOD_DAYS[weightChartMode] || 7,
    )
    : normalizeHistory(payload?.weight_history);

  stepsEvents = normalizeStepEvents(payload?.steps_events);
  stepsHistoryStatus = "idle";
  const activeStepsDays = getActiveStepsHistoryDays();
  const dailySteps = isAllHistoryRange(activeStepsDays)
    ? stepsEventsToHistoryRows(stepsEvents, stepsChartEndDay)
    : normalizeStepHistory(payload?.steps_history);
  stepsHistory = isStepsPeriodChartMode()
    ? buildPeriodStepsHistory(
      dailySteps,
      activeStepsDays,
      stepsChartEndDay,
      PERIOD_DAYS[stepsChartMode] || 7,
    )
    : dailySteps;

  healthSnapshot = payload?.health?.ok ? payload.health.snapshot : null;
  lastSignalSignature = JSON.stringify({
    rssi: scaleSignal?.rssi ?? null,
    signalPercent: scaleSignal?.signalPercent ?? null,
    ageSeconds: scaleSignal?.ageSeconds ?? null,
  });
  lastHistorySignature = JSON.stringify({
    mode: weightChartMode,
    days: getActiveHistoryDays(),
    end: chartEndDay,
    rows: weightHistory,
  });
  lastEventsSignature = JSON.stringify(weightEvents);
  lastStatsSignature = JSON.stringify(weightStats);
  lastStepsHistorySignature = JSON.stringify({
    mode: stepsChartMode,
    days: activeStepsDays,
    end: stepsChartEndDay,
    rows: stepsHistory,
  });
  lastStepsEventsSignature = JSON.stringify(stepsEvents);
  lastHealthSnapshotSignature = JSON.stringify(healthSnapshot);
  render();
}

async function refreshBackgroundNow() {
  try {
    const activeWeightDays = getActiveHistoryDays();
    const activeStepsDays = getActiveStepsHistoryDays();
    const params = new URLSearchParams({
      weight_days: String(isAllHistoryRange(activeWeightDays) ? DEFAULT_HISTORY_DAYS : activeWeightDays),
      weight_end: chartEndDay,
      weight_period: isPeriodChartMode() ? "1" : "0",
      steps_days: String(isAllHistoryRange(activeStepsDays) ? DEFAULT_HISTORY_DAYS : activeStepsDays),
      steps_end: stepsChartEndDay,
      steps_all: isAllHistoryRange(activeStepsDays) ? "1" : "0",
    });
    const stopTimer = startLoadTimer();
    const response = await fetch(`${DASHBOARD_SUMMARY_ENDPOINT}?${params.toString()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (!payload?.ok) throw new Error("Invalid dashboard summary");
    setLoadTiming("summary", stopTimer());
    applyBackgroundSummary(payload);
  } catch {
    await refreshBackgroundFallbackNow();
  }
}

function stopWidgetRefresh() {
  if (livePollTimer) window.clearInterval(livePollTimer);
  if (backgroundPollTimer) window.clearInterval(backgroundPollTimer);
  if (stepsRefreshTimer) window.clearTimeout(stepsRefreshTimer);
  livePollTimer = null;
  backgroundPollTimer = null;
  stepsRefreshTimer = null;
  stopStepsStream();
}

function startWidgetRefresh({ refresh = true } = {}) {
  if (!root || document.hidden) return;
  stopWidgetRefresh();
  if (refresh) {
    refreshLiveWeight();
    refreshBackgroundNow();
    refreshCardioHistory();
  }
  livePollTimer = window.setInterval(refreshLiveWeight, LIVE_POLL_MS);
  backgroundPollTimer = window.setInterval(() => {
    refreshBackgroundNow();
    refreshCardioHistory();
  }, STEPS_POLL_MS);
  startStepsStream();
}

function handleVisibilityChange() {
  if (document.hidden) stopWidgetRefresh();
  else startWidgetRefresh();
}

async function saveSteps(day, steps) {
  if (!day) return;
  stepsHistoryStatus = "loading";

  try {
    const response = await fetch(UPSERT_STEPS_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ day, steps, source: "manual" }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    stepsHistoryStatus = "idle";
    await refreshStepsNow();
  } catch {
    stepsHistoryStatus = "error";
    render();
  }
}

async function deleteSteps(day) {
  if (!day) return;
  stepsHistoryStatus = "loading";
  store = saveStore({
    ...store,
    days: Object.fromEntries(Object.entries(store.days || {}).filter(([key]) => key !== day)),
  });
  render();

  try {
    const response = await fetch(DELETE_STEPS_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ day }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    stepsHistoryStatus = "idle";
    await refreshStepsNow();
  } catch {
    stepsHistoryStatus = "error";
    render();
  }
}

async function deleteEvent(timestamp) {
  if (!timestamp) return;
  historyStatus = "loading";
  render();

  try {
    const response = await fetch(DELETE_EVENT_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ timestamp }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    weightEvents = normalizeEvents(payload);
    historyStatus = "idle";
    await Promise.all([refreshLiveWeight(), refreshHistory(), refreshEvents(), refreshStats()]);
  } catch {
    historyStatus = "error";
    render();
  }
}

render();
startWidgetRefresh();
document.addEventListener("visibilitychange", handleVisibilityChange);
window.addEventListener("pagehide", stopWidgetRefresh);
window.addEventListener("pageshow", (event) => {
  if (event.persisted) startWidgetRefresh();
});
