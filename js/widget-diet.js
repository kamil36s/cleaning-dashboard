import { formatLoadedAt, loadTimeSuffix, startLoadTimer } from "./load-timing.js";
import { openDatePopover } from "./date-popover.js";
import {
  generateCombinedDailyReport,
  generateDietDailyReport,
} from "./daily-report.js";
import { estimateMissingCalories } from "./diet-estimation.js";
import { escapeHtml } from "./utils.js";

const DIET_DAYS_ENDPOINT = "/api/diet/days";
const DIET_HISTORY_ENDPOINT = "/api/diet/history";
const UPSERT_DIET_MEAL_ENDPOINT = "/api/diet/meals/upsert";
const DELETE_DIET_MEAL_ENDPOINT = "/api/diet/meals/delete";
const UPSERT_DIET_ESTIMATES_ENDPOINT = "/api/diet/estimates/upsert";
const DELETE_DIET_ESTIMATES_ENDPOINT = "/api/diet/estimates/delete";
const IGNORE_DIET_DAY_ENDPOINT = "/api/diet/days/ignore";
const WEIGHT_HISTORY_ENDPOINT = "/api/weight/history";
const STEPS_HISTORY_ENDPOINT = "/api/steps/history";
const DEFAULT_DIET_GOAL_KCAL = 2200;
const DIET_HISTORY_DAYS = 30;
const ESTIMATION_LOOKBACK_DAYS = 30;
const ESTIMATION_CONTEXT_DAYS = 1095;
const HISTORY_ALL_VALUE = "all";
const HISTORY_DAY_OPTIONS = [30, 90, 180, 365];
const HISTORY_PERIOD_OPTIONS = {
  weekly: [91, 182],
  biweekly: [182, 365],
  monthly: [365, 730, 1095, HISTORY_ALL_VALUE],
};
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
const DIET_POLL_MS = 60000;
const MONTH_SHORT_PL = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paz", "lis", "gru"];
const calorieLevels = [
  {
    label: "Za nisko",
    min: null,
    max: 1599,
    color: "#14B8A6",
  },
  {
    label: "Mocny deficyt",
    min: 1600,
    max: 1999,
    color: "#22C55E",
  },
  {
    label: "Cel redukcji",
    min: 2000,
    max: 2299,
    color: "#84CC16",
  },
  {
    label: "Kontrolowany zapas",
    min: 2300,
    max: 2499,
    color: "#F59E0B",
  },
  {
    label: "Luźny dzień",
    min: 2500,
    max: 2799,
    color: "#F97316",
  },
  {
    label: "Poza planem",
    min: 2800,
    max: null,
    color: "#EF4444",
  },
];

const root = document.getElementById("diet-root");

let selectedDay = todayIso();
let dietDays = [];
let dietHistory = [];
let goalKcal = DEFAULT_DIET_GOAL_KCAL;
let status = "loading";
let lastSignature = "";
let editingMealId = null;
let lastLoadMs = null;
let lastLoadedAt = null;
let dietChartEndDay = todayIso();
let dietHistoryDays = DIET_HISTORY_DAYS;
let dietChartMode = "daily";
let dietPeriodHistoryDays = { ...DEFAULT_PERIOD_HISTORY_DAYS };
let showDietMovingAverage = true;
let mealNameDraft = "";
let mealKcalDraft = "";
let lastDietError = "";
let topUpIdeasOpen = false;

function normalizeMealQuery(value) {
  return String(value || "")
    .trim()
    .toLocaleLowerCase("pl-PL")
    .replaceAll("ł", "l")
    .replaceAll("Ł", "l")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ");
}

export function normalizeMealDraft(value) {
  return String(value || "").toLocaleLowerCase("pl-PL");
}

function normalizeMealName(value) {
  return String(value || "").trim().replace(/\s+/g, " ").toLocaleLowerCase("pl-PL");
}

function todayIso(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDaysIso(day, amount) {
  const date = new Date(`${day}T12:00:00`);
  if (Number.isNaN(date.getTime())) return todayIso();
  date.setDate(date.getDate() + amount);
  return todayIso(date);
}

function daysBetweenIso(startDay, endDay) {
  const start = isoDateObject(startDay);
  const end = isoDateObject(endDay);
  return Math.max(0, Math.round((end - start) / 86400000));
}

function isoDateObject(day) {
  const date = new Date(`${day}T12:00:00`);
  return Number.isNaN(date.getTime()) ? new Date(`${todayIso()}T12:00:00`) : date;
}

function isSameOrAfterToday(day) {
  return day >= todayIso();
}

function readNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).trim().replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function formatInt(value) {
  return Math.round(Number(value) || 0).toLocaleString("pl-PL");
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

function isDietPeriodChartMode(mode = dietChartMode) {
  return mode !== "daily";
}

function getDietPeriodHistoryDays(mode = dietChartMode) {
  return dietPeriodHistoryDays[mode] || DEFAULT_PERIOD_HISTORY_DAYS[mode] || DIET_HISTORY_DAYS;
}

function setDietPeriodHistoryDays(mode, days) {
  if (!DEFAULT_PERIOD_HISTORY_DAYS[mode]) return;
  dietPeriodHistoryDays = { ...dietPeriodHistoryDays, [mode]: days };
}

function getActiveDietHistoryDays() {
  return isDietPeriodChartMode() ? getDietPeriodHistoryDays() : dietHistoryDays;
}

function getActiveDietHistoryOptions() {
  return isDietPeriodChartMode() ? HISTORY_PERIOD_OPTIONS[dietChartMode] || [] : HISTORY_DAY_OPTIONS;
}

function getDietChartTitle() {
  if (dietChartMode === "weekly") return "Kalorie tygodniowe";
  if (dietChartMode === "biweekly") return "Kalorie 2-tygodniowe";
  if (dietChartMode === "monthly") return "Kalorie miesięczne";
  return "Kalorie dzienne";
}

function getDietChartHistoryUnit() {
  if (dietChartMode === "weekly") return "tyg.";
  if (dietChartMode === "biweekly") return "okr.";
  if (dietChartMode === "monthly") return "mies.";
  return "dni";
}

function getDailyReportDays(days, fallback = DIET_HISTORY_DAYS) {
  return isAllHistoryRange(days) ? HISTORY_ALL_VALUE : Math.max(1, Math.round(readNumber(days) || fallback));
}

function formatDateInputPl(day) {
  const parts = String(day || "").split("-");
  if (parts.length !== 3) return "";
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

function parseDayInput(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";

  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;

  const numeric = raw.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/);
  if (!numeric) return "";

  const day = numeric[1].padStart(2, "0");
  const month = numeric[2].padStart(2, "0");
  const year = numeric[3];
  const isoDay = `${year}-${month}-${day}`;
  const parsed = new Date(`${isoDay}T12:00:00`);
  if (!Number.isNaN(parsed.getTime()) && todayIso(parsed) === isoDay) return isoDay;
  return "";
}

function makeMealId() {
  return `meal-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function getCalorieLevel(kcal) {
  return calorieLevels.find((level) => (
    (!Number.isFinite(level.min) || kcal >= level.min)
    && (!Number.isFinite(level.max) || kcal <= level.max)
  )) || calorieLevels[0];
}

function isManualDietRow(row) {
  return row?.caloriesSource === "manual" && Number(row?.mealCount) > 0 && Number(row?.totalKcal) > 0;
}

function isEstimatedDietRow(row) {
  return row?.caloriesSource === "estimated" && Number(row?.estimatedCalories) > 0;
}

function isIgnoredDietRow(row) {
  return row?.caloriesSource === "ignored" || row?.ignored === true;
}

function hasDietChartValue(row) {
  return !isIgnoredDietRow(row) && (
    isManualDietRow(row) || isEstimatedDietRow(row) || Number(row?.totalKcal) > 0 && row?.filled !== true
  );
}

function isMeasuredDietRow(row) {
  return isManualDietRow(row);
}

function normalizeEstimateComponents(value) {
  if (!value || typeof value !== "object") return null;
  return {
    baselineCalories: Math.round(readNumber(value.baselineCalories ?? value.baseline_calories) || 0),
    weightAdjustment: Math.round(readNumber(value.weightAdjustment ?? value.weight_adjustment) || 0),
    stepsAdjustment: Math.round(readNumber(value.stepsAdjustment ?? value.steps_adjustment) || 0),
    dailyTrendKg: readNumber(value.dailyTrendKg ?? value.daily_trend_kg),
    weightSurpriseKg: readNumber(value.weightSurpriseKg ?? value.weight_surprise_kg),
    baselineSteps: readNumber(value.baselineSteps ?? value.baseline_steps),
    knownStepDays: Math.round(readNumber(value.knownStepDays ?? value.known_step_days) || 0),
  };
}

function normalizeDay(row) {
  const meals = Array.isArray(row?.meals) ? row.meals : [];
  const manualTotal = Math.max(0, Math.round(readNumber(row?.total_kcal) || 0));
  const estimatedCalories = Math.max(0, Math.round(readNumber(row?.estimated_kcal ?? row?.estimatedCalories) || 0));
  const ignored = row?.calories_source === "ignored" || row?.caloriesSource === "ignored" || row?.ignored === true;
  const caloriesSource = meals.length && manualTotal > 0
    ? "manual"
    : ignored
      ? "ignored"
      : estimatedCalories > 0
      ? "estimated"
      : "missing";
  const totalKcal = caloriesSource === "estimated" ? estimatedCalories : manualTotal;
  return {
    day: String(row?.day || ""),
    goalKcal: Math.max(0, Math.round(readNumber(row?.goal_kcal) || goalKcal || DEFAULT_DIET_GOAL_KCAL)),
    totalKcal,
    manualCalories: meals.length && manualTotal > 0 ? manualTotal : null,
    estimatedCalories: estimatedCalories || null,
    caloriesSource,
    estimateConfidence: row?.estimate_confidence || row?.estimateConfidence || "",
    estimateReason: row?.estimate_reason || row?.estimateReason || "",
    estimateComponents: normalizeEstimateComponents(row?.estimate_components ?? row?.estimateComponents),
    ignored,
    ignoredAt: row?.ignored_at || row?.ignoredAt || "",
    remainingKcal: Math.round(readNumber(row?.remaining_kcal) ?? 0),
    meals: meals
      .map((meal) => ({
        id: String(meal.id || ""),
        name: normalizeMealName(meal.name),
        kcal: Math.max(0, Math.round(readNumber(meal.kcal) || 0)),
      }))
      .filter((meal) => meal.id && meal.name),
  };
}

function normalizeDietHistoryRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map((row) => {
      const totalKcal = Math.max(0, Math.round(readNumber(row.total_kcal ?? row.totalKcal) || 0));
      const mealCount = Math.max(0, Math.round(readNumber(row.meal_count ?? row.mealCount) || 0));
      const estimatedCalories = Math.max(0, Math.round(readNumber(row.estimated_kcal ?? row.estimatedCalories) || 0));
      const ignored = row.ignored === true || row.calories_source === "ignored" || row.caloriesSource === "ignored";
      const caloriesSource = row.calories_source || row.caloriesSource || (mealCount > 0 && totalKcal > 0 ? "manual" : estimatedCalories > 0 ? "estimated" : "missing");
      return {
        day: String(row.day || ""),
        totalKcal,
        mealCount,
        goalKcal: Math.max(0, Math.round(readNumber(row.goal_kcal ?? row.goalKcal) || goalKcal || DEFAULT_DIET_GOAL_KCAL)),
        manualCalories: caloriesSource === "manual" ? totalKcal : null,
        estimatedCalories: estimatedCalories || (caloriesSource === "estimated" ? totalKcal : null),
        caloriesSource,
        estimateConfidence: row.estimate_confidence || row.estimateConfidence || "",
        estimateReason: row.estimate_reason || row.estimateReason || "",
        estimateComponents: normalizeEstimateComponents(row.estimate_components ?? row.estimateComponents),
        ignored,
        ignoredAt: row.ignored_at || row.ignoredAt || "",
        filled: row.filled === true || caloriesSource !== "manual",
      };
    })
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day));
}

function dietDaysToHistoryRows(days, endDay) {
  const end = isoDateObject(endDay);
  return days
    .map((day) => ({
      day: String(day.day || ""),
      totalKcal: Math.max(0, Math.round(readNumber(day.totalKcal) || 0)),
      mealCount: Math.max(0, Math.round(readNumber(day.meals?.length ?? day.mealCount) || 0)),
      goalKcal: Math.max(0, Math.round(readNumber(day.goalKcal) || goalKcal || DEFAULT_DIET_GOAL_KCAL)),
      manualCalories: day.caloriesSource === "manual" ? Math.max(0, Math.round(readNumber(day.totalKcal) || 0)) : null,
      estimatedCalories: Math.max(0, Math.round(readNumber(day.estimatedCalories) || 0)) || null,
      caloriesSource: day.caloriesSource || "manual",
      estimateConfidence: day.estimateConfidence || "",
      estimateReason: day.estimateReason || "",
      estimateComponents: day.estimateComponents || null,
      ignored: isIgnoredDietRow(day),
      ignoredAt: day.ignoredAt || "",
      filled: day.caloriesSource !== "manual",
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day) && hasDietChartValue(row) && isoDateObject(row.day) <= end)
    .sort((a, b) => a.day.localeCompare(b.day));
}

function normalizeWeightHistoryRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map((row) => ({
      day: String(row.day || ""),
      weightKg: readNumber(row.avg_weight_kg ?? row.avgWeightKg ?? row.weightKg),
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day) && Number.isFinite(row.weightKg));
}

function normalizeStepsHistoryRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map((row) => ({
      day: String(row.day || ""),
      steps: Math.max(0, Math.round(readNumber(row.steps) || 0)),
      stepsFilled: row.filled === true,
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day));
}

function dailyRange(startDay, endDay) {
  const days = [];
  const total = daysBetweenIso(startDay, endDay);
  for (let offset = 0; offset <= total; offset += 1) {
    days.push(addDaysIso(startDay, offset));
  }
  return days;
}

function getEstimationWindow() {
  return { startDay: selectedDay, endDay: selectedDay };
}

function buildDietRowsForEstimation(startDay, endDay, weightRows, stepsRows) {
  const dietByDay = new Map(dietDays.map((day) => [day.day, day]));
  const weightByDay = new Map(weightRows.map((row) => [row.day, row]));
  const stepsByDay = new Map(stepsRows.map((row) => [row.day, row]));
  return dailyRange(startDay, endDay).map((day) => {
    const dietDay = dietByDay.get(day) || {};
    const weightDay = weightByDay.get(day) || {};
    const stepsDay = stepsByDay.get(day) || {};
    return {
      day,
      manualCalories: dietDay.caloriesSource === "manual" ? dietDay.totalKcal : null,
      estimatedCalories: dietDay.caloriesSource === "estimated" ? dietDay.estimatedCalories : null,
      ignored: isIgnoredDietRow(dietDay),
      goalKcal: dietDay.goalKcal || goalKcal || DEFAULT_DIET_GOAL_KCAL,
      weightKg: weightDay.weightKg,
      steps: stepsDay.steps,
      stepsFilled: stepsDay.stepsFilled,
    };
  });
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function buildPeriodDietHistory(rows, limitDays, endDay, periodDays = 7) {
  const end = isoDateObject(endDay);
  const today = isoDateObject(todayIso());
  if (end > today) end.setTime(today.getTime());

  const normalizedRows = rows
    .map((row) => {
      const day = String(row.day || "");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
      const totalKcal = Math.max(0, Math.round(readNumber(row.totalKcal) || 0));
      const mealCount = Math.max(0, Math.round(readNumber(row.mealCount) || 0));
      return {
        ...row,
        day,
        date: isoDateObject(day),
        totalKcal,
        mealCount,
        filled: row.filled === true || mealCount <= 0 || totalKcal <= 0,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.date - b.date);
  const rowsByDay = new Map(normalizedRows.map((row) => [row.day, row]));
  const realRows = normalizedRows.filter(hasDietChartValue);
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
    let mealCount = 0;
    let estimatedDayCount = 0;
    let manualDayCount = 0;

    for (let offset = 0; offset < periodDays; offset += 1) {
      const currentDate = new Date(periodStart);
      currentDate.setDate(periodStart.getDate() + offset);
      if (allRange && firstDataDate && currentDate < firstDataDate) continue;
      const row = rowsByDay.get(todayIso(currentDate));
      if (row && hasDietChartValue(row)) {
        values.push(row.totalKcal);
        mealCount += row.mealCount;
        if (isEstimatedDietRow(row)) estimatedDayCount += 1;
        if (isManualDietRow(row)) manualDayCount += 1;
      }
    }

    const labelStartIso = allRange && firstDataDate && periodStart < firstDataDate
      ? todayIso(firstDataDate)
      : periodStartIso;
    const avgKcal = values.length
      ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
      : 0;
    periodRows.push({
      day: periodEndIso,
      periodStart: labelStartIso,
      periodEnd: periodEndIso,
      totalKcal: avgKcal,
      mealCount,
      dayCount: values.length,
      estimatedDayCount,
      manualDayCount,
      caloriesSource: estimatedDayCount && !manualDayCount ? "estimated" : estimatedDayCount ? "mixed" : values.length ? "manual" : "missing",
      filled: values.length === 0,
      rangeLabel: formatWeekRange(labelStartIso, periodEndIso),
    });
  }
  return periodRows;
}

function selectedDayData() {
  return dietDays.find((day) => day.day === selectedDay) || {
    day: selectedDay,
    goalKcal,
    totalKcal: 0,
    remainingKcal: goalKcal,
    meals: [],
  };
}

function canEstimateSelectedDay(day = selectedDayData()) {
  return Boolean(
    day
    && /^\d{4}-\d{2}-\d{2}$/.test(day.day)
    && day.day < todayIso()
    && day.caloriesSource !== "manual"
    && !isIgnoredDietRow(day)
    && Number(day.meals?.length || 0) === 0,
  );
}

function getTopUpMealCounts(hour) {
  if (hour >= 21) return [1];
  if (hour >= 18) return [1, 2];
  if (hour >= 14) return [1, 2, 3];
  return [2, 3, 1];
}

function getTopUpTargetForCount(remainingKcal, mealCount, hour) {
  const remaining = Math.max(0, Math.round(readNumber(remainingKcal) || 0));
  if (hour >= 21) return Math.min(remaining, 650);
  if (hour >= 19 && mealCount === 1) return Math.min(remaining, 850);
  if (hour >= 17 && mealCount === 1) return Math.min(remaining, 1000);
  return remaining;
}

function describeTopUpTiming(hour, mealCount) {
  if (mealCount === 1) return "1 posi\u0142ek";
  if (mealCount === 2) return "2 posi\u0142ki";
  return `${mealCount} posi\u0142ki`;
}

function collectHistoricalMeals(days) {
  const mealsByName = new Map();
  (Array.isArray(days) ? days : []).forEach((day) => {
    const dayKey = String(day?.day || "");
    (Array.isArray(day?.meals) ? day.meals : []).forEach((meal) => {
      const name = normalizeMealName(meal?.name);
      const normalizedName = normalizeMealQuery(name);
      const kcal = Math.max(0, Math.round(readNumber(meal?.kcal) || 0));
      if (!name || !normalizedName || !kcal) return;
      const current = mealsByName.get(normalizedName) || {
        name,
        normalizedName,
        kcal,
        count: 0,
        latestDay: "",
      };
      current.count += 1;
      if (!current.latestDay || dayKey >= current.latestDay) {
        current.name = name;
        current.kcal = kcal;
        current.latestDay = dayKey;
      }
      mealsByName.set(normalizedName, current);
    });
  });

  return [...mealsByName.values()]
    .sort((a, b) => (
      b.count - a.count
      || b.latestDay.localeCompare(a.latestDay)
      || a.name.localeCompare(b.name, "pl")
    ));
}

function comboKey(meals) {
  return meals.map((meal) => meal.normalizedName).sort().join("|");
}

function scoreTopUpCombo(meals, target, maxKcal, hour) {
  const totalKcal = meals.reduce((sum, meal) => sum + meal.kcal, 0);
  const distance = Math.abs(target - totalKcal);
  const recency = meals.reduce((sum, meal) => sum + Number(meal.latestDay.replaceAll("-", "") || 0), 0) / Math.max(1, meals.length);
  const popularity = meals.reduce((sum, meal) => sum + meal.count, 0);
  const underBonus = totalKcal <= target ? 80 : 0;
  const lateLightBonus = hour >= 21 && totalKcal <= maxKcal ? 55 : 0;
  return underBonus + lateLightBonus + popularity * 11 + recency / 100000 - distance * 2.7;
}

function makeTopUpSuggestion(meals, remainingKcal, target, hour) {
  const totalKcal = meals.reduce((sum, meal) => sum + meal.kcal, 0);
  const leftAfter = Math.max(0, Math.round(remainingKcal - totalKcal));
  return {
    id: comboKey(meals),
    label: describeTopUpTiming(hour, meals.length),
    totalKcal,
    leftAfter,
    mealCount: meals.length,
    meals: meals.map(({ normalizedName, ...meal }) => meal),
    score: scoreTopUpCombo(meals, target, remainingKcal, hour),
  };
}

function chooseTopUpSuggestions(suggestions, mealCounts, limit) {
  const sorted = [...suggestions].sort((a, b) => b.score - a.score || b.totalKcal - a.totalKcal);
  if (mealCounts.length === 1) return sorted.slice(0, limit);

  const buckets = new Map();
  sorted.forEach((suggestion) => {
    const bucket = buckets.get(suggestion.mealCount) || [];
    bucket.push(suggestion);
    buckets.set(suggestion.mealCount, bucket);
  });

  const picked = [];
  const used = new Set();
  const preferredCounts = [1, 2].filter((mealCount) => mealCounts.includes(mealCount));
  const minimumPerPreferredCount = Math.min(4, Math.max(2, Math.floor(limit / 4)));

  preferredCounts.forEach((mealCount) => {
    const bucket = buckets.get(mealCount) || [];
    bucket.slice(0, minimumPerPreferredCount).forEach((suggestion) => {
      if (picked.length >= limit || used.has(suggestion.id)) return;
      picked.push(suggestion);
      used.add(suggestion.id);
    });
  });

  sorted.forEach((suggestion) => {
    if (picked.length >= limit || used.has(suggestion.id)) return;
    picked.push(suggestion);
    used.add(suggestion.id);
  });

  return picked.slice(0, limit);
}

export function buildCalorieTopUpSuggestions(days, remainingKcal, options = {}) {
  const remaining = Math.max(0, Math.round(readNumber(remainingKcal) || 0));
  if (!remaining) return [];

  const hour = Math.max(0, Math.min(23, Math.round(readNumber(options.hour) ?? new Date().getHours())));
  const limit = Math.max(1, Math.round(readNumber(options.limit) || 12));
  const mealCounts = getTopUpMealCounts(hour);
  const candidates = collectHistoricalMeals(days)
    .filter((meal) => meal.kcal <= remaining)
    .slice(0, 72);
  const suggestions = [];
  const seen = new Set();

  const pushCombo = (combo, target) => {
    const key = comboKey(combo);
    if (seen.has(key)) return;
    const totalKcal = combo.reduce((sum, meal) => sum + meal.kcal, 0);
    if (totalKcal <= 0 || totalKcal > remaining) return;
    seen.add(key);
    suggestions.push(makeTopUpSuggestion(combo, remaining, target, hour));
  };

  mealCounts.forEach((mealCount) => {
    const target = getTopUpTargetForCount(remaining, mealCount, hour);
    const maxForTiming = Math.min(remaining, Math.max(120, Math.round(target * 1.06)));
    const pool = candidates.filter((meal) => meal.kcal <= maxForTiming);

    if (mealCount === 1) {
      pool.forEach((meal) => pushCombo([meal], target));
      return;
    }

    if (mealCount === 2) {
      for (let first = 0; first < pool.length; first += 1) {
        for (let second = first + 1; second < pool.length; second += 1) {
          const combo = [pool[first], pool[second]];
          const totalKcal = combo[0].kcal + combo[1].kcal;
          if (totalKcal <= maxForTiming) pushCombo(combo, target);
        }
      }
      return;
    }

    const triplePool = pool.slice(0, 42);
    for (let first = 0; first < triplePool.length; first += 1) {
      for (let second = first + 1; second < triplePool.length; second += 1) {
        for (let third = second + 1; third < triplePool.length; third += 1) {
          const combo = [triplePool[first], triplePool[second], triplePool[third]];
          const totalKcal = combo[0].kcal + combo[1].kcal + combo[2].kcal;
          if (totalKcal <= maxForTiming) pushCombo(combo, target);
        }
      }
    }
  });

  return chooseTopUpSuggestions(suggestions, mealCounts, limit)
    .map(({ score, ...suggestion }) => suggestion);
}

export function buildMealSuggestions(query, days, limit = 6) {
  const normalizedQuery = normalizeMealQuery(query);
  if (normalizedQuery.length < 2) return [];

  const suggestionsByName = new Map();
  (Array.isArray(days) ? days : []).forEach((day) => {
    const dayKey = String(day?.day || "");
    (Array.isArray(day?.meals) ? day.meals : []).forEach((meal) => {
      const name = normalizeMealName(meal?.name);
      const normalizedName = normalizeMealQuery(name);
      const kcal = Math.max(0, Math.round(readNumber(meal?.kcal) || 0));
      if (!name || !normalizedName || !kcal) return;

      const current = suggestionsByName.get(normalizedName) || {
        name,
        normalizedName,
        kcal,
        count: 0,
        latestDay: "",
      };
      current.count += 1;
      if (!current.latestDay || dayKey >= current.latestDay) {
        current.name = name;
        current.kcal = kcal;
        current.latestDay = dayKey;
      }
      suggestionsByName.set(normalizedName, current);
    });
  });

  return [...suggestionsByName.values()]
    .map((suggestion) => {
      const startsWithQuery = suggestion.normalizedName.startsWith(normalizedQuery);
      const includesQuery = suggestion.normalizedName.includes(normalizedQuery);
      if (!startsWithQuery && !includesQuery) return null;
      return {
        ...suggestion,
        score: (startsWithQuery ? 1000 : 0) + suggestion.count * 12 + Number(suggestion.latestDay.replaceAll("-", "") || 0) / 100000,
      };
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name, "pl"))
    .slice(0, Math.max(1, limit))
    .map(({ score, normalizedName, ...suggestion }) => suggestion);
}

function findExactMealSuggestion(query) {
  const normalizedQuery = normalizeMealQuery(query);
  if (!normalizedQuery) return null;
  return buildMealSuggestions(query, dietDays, 12).find((suggestion) => normalizeMealQuery(suggestion.name) === normalizedQuery) || null;
}

function renderMealSuggestions(query) {
  const suggestions = buildMealSuggestions(query, dietDays);
  if (!suggestions.length) return "";

  return `
    <div class="diet-meal-suggestions" id="diet-meal-suggestions" role="listbox" aria-label="Sugestie posiłków">
      ${suggestions.map((suggestion) => `
        <button
          class="diet-meal-suggestion"
          type="button"
          role="option"
          data-meal-suggestion-name="${escapeHtml(suggestion.name)}"
          data-meal-suggestion-kcal="${suggestion.kcal}"
        >
          <span>${escapeHtml(suggestion.name)}</span>
          <strong>${formatInt(suggestion.kcal)} kcal</strong>
        </button>
      `).join("")}
    </div>
  `;
}

function formatCalorieRange(level) {
  if (!Number.isFinite(level.min)) return `0-${formatInt(level.max || 0)} kcal`;
  if (!Number.isFinite(level.max)) return `${formatInt(level.min)}+ kcal`;
  return `${formatInt(level.min)}-${formatInt(level.max)} kcal`;
}

function renderCalorieLegend() {
  return `
    <div class="diet-chart-legend" aria-label="Legenda poziomów kalorii">
      ${calorieLevels.map((level) => `
        <div
          class="diet-chart-legend-item"
          tabindex="0"
          data-diet-day="${escapeHtml(level.label)}"
          data-diet-kcal="${escapeHtml(formatCalorieRange(level))}"
          data-diet-level="${escapeHtml(level.label)}"
          data-diet-color="${escapeHtml(level.color)}"
          data-diet-meta=""
        >
          <span class="diet-chart-legend-swatch" style="background:${level.color}"></span>
          <span>${escapeHtml(level.label)}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function renderDietChart(rows, showMovingAverage = true) {
  const measuredRows = rows.filter(hasDietChartValue);
  if (!measuredRows.length) {
    return `<div class="diet-chart-empty">Brak danych do wykresu</div>`;
  }

  const isPeriod = rows.some((row) => row.periodStart && row.periodEnd);
  const width = 700;
  const height = 230;
  const padX = 56;
  const padY = 28;
  const plotRight = width - 112;
  const scaleX = plotRight + 18;
  const thresholdLines = calorieLevels
    .filter((level) => level.label === "Cel redukcji")
    .map(() => ({
      kcal: goalKcal,
      label: `${formatInt(goalKcal)} kcal`,
      color: "#84CC16",
    }));
  const visibleValues = [
    ...measuredRows.map((row) => row.totalKcal),
    ...thresholdLines.map((line) => line.kcal),
  ];
  const minValue = Math.min(...visibleValues);
  const maxValue = Math.max(...visibleValues);
  let yMin = Math.floor((minValue - 100) / 100) * 100;
  let yMax = Math.ceil((maxValue + 100) / 100) * 100;
  yMin = Math.max(0, yMin);
  if (yMin === yMax) {
    yMin = Math.max(0, yMin - 100);
    yMax += 100;
  }
  const yRange = Math.max(1, yMax - yMin);
  const yForKcal = (kcal) => padY + ((yMax - kcal) / yRange) * (height - padY * 2);
  const denom = Math.max(1, rows.length - 1);
  const measuredIndexes = rows
    .map((row, index) => (hasDietChartValue(row) ? index : -1))
    .filter((index) => index >= 0);
  const interpolatedKcalForIndex = (index) => {
    if (hasDietChartValue(rows[index])) return rows[index].totalKcal;
    const previousIndex = [...measuredIndexes].reverse().find((candidate) => candidate < index);
    const nextIndex = measuredIndexes.find((candidate) => candidate > index);
    if (Number.isFinite(previousIndex) && Number.isFinite(nextIndex)) {
      const previousKcal = rows[previousIndex].totalKcal;
      const nextKcal = rows[nextIndex].totalKcal;
      const progress = (index - previousIndex) / Math.max(1, nextIndex - previousIndex);
      return previousKcal + (nextKcal - previousKcal) * progress;
    }
    if (Number.isFinite(previousIndex)) return rows[previousIndex].totalKcal;
    if (Number.isFinite(nextIndex)) return rows[nextIndex].totalKcal;
    return yMin;
  };
  const points = rows.map((row, index) => {
    const filled = !isManualDietRow(row);
    const estimated = isEstimatedDietRow(row) || row.caloriesSource === "mixed";
    const displayKcal = interpolatedKcalForIndex(index);
    const x = padX + (index / denom) * (plotRight - padX);
    const y = yForKcal(displayKcal);
    return { ...row, filled, estimated, displayKcal, rowIndex: index, level: getCalorieLevel(displayKcal), x, y };
  });
  const movingAveragePoints = isPeriod ? [] : points.map((point) => {
    const windowRows = rows
      .slice(Math.max(0, point.rowIndex - 6), point.rowIndex + 1)
      .filter(hasDietChartValue);
    if (!windowRows.length) return null;
    const avg = windowRows.reduce((sum, row) => sum + row.totalKcal, 0) / windowRows.length;
    return { x: point.x, y: yForKcal(avg) };
  });
  const movingAveragePath = movingAveragePoints
    .map((point, index) => {
      if (!point) return "";
      return `${index === 0 || !movingAveragePoints[index - 1] ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    })
    .filter(Boolean)
    .join(" ");
  const thresholdLineViews = thresholdLines
    .filter((line) => line.kcal >= yMin && line.kcal <= yMax)
    .map((line) => ({
      ...line,
      y: yForKcal(line.kcal),
    }));
  const segments = points.slice(1).map((point, index) => {
    const previous = points[index];
    return {
      gradientId: `diet-calorie-segment-${index}`,
      empty: point.filled || previous.filled,
      x1: previous.x.toFixed(1),
      y1: previous.y.toFixed(1),
      x2: point.x.toFixed(1),
      y2: point.y.toFixed(1),
      fromColor: previous.level.color,
      toColor: point.level.color,
    };
  });
  const first = points[0];
  const last = points[points.length - 1];
  const rangeFirst = rows[0] || first;
  const rangeLast = rows[rows.length - 1] || last;
  const currentPoint = points.find((point) => point.day === todayIso() && hasDietChartValue(point))
    || [...points].reverse().find(hasDietChartValue)
    || last;
  const topLabelY = padY + 5;
  const bottomLabelY = height - padY + 5;
  let currentLabelY = Math.max(padY + 14, Math.min(height - padY - 10, currentPoint.y));
  if (Math.abs(currentLabelY - topLabelY) < 18) currentLabelY = topLabelY + 20;
  if (Math.abs(currentLabelY - bottomLabelY) < 18) currentLabelY = bottomLabelY - 20;
  return `
    <svg class="diet-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Wykres kalorii dziennych">
      <defs>
        ${segments.map((segment) => `
          <linearGradient
            id="${segment.gradientId}"
            gradientUnits="userSpaceOnUse"
            x1="${segment.x1}"
            y1="${segment.y1}"
            x2="${segment.x2}"
            y2="${segment.y2}"
          >
            <stop offset="0%" stop-color="${segment.fromColor}" />
            <stop offset="100%" stop-color="${segment.toColor}" />
          </linearGradient>
        `).join("")}
      </defs>
      <line class="diet-chart-grid" x1="${padX}" y1="${padY}" x2="${plotRight}" y2="${padY}" />
      <line class="diet-chart-grid" x1="${padX}" y1="${height / 2}" x2="${plotRight}" y2="${height / 2}" />
      <line class="diet-chart-grid" x1="${padX}" y1="${height - padY}" x2="${plotRight}" y2="${height - padY}" />
      ${thresholdLineViews.map((line) => `
        <line
          class="diet-chart-threshold"
          style="stroke:${line.color}"
          x1="${padX}"
          y1="${line.y.toFixed(1)}"
          x2="${plotRight}"
          y2="${line.y.toFixed(1)}"
        />
        <text class="diet-chart-threshold-label" x="${padX - 10}" y="${line.y.toFixed(1)}" text-anchor="end" dominant-baseline="middle" style="fill:${line.color}">${line.label}</text>
      `).join("")}
      <text class="diet-chart-scale" x="${scaleX}" y="${topLabelY}">${formatInt(yMax)} kcal</text>
      <text class="diet-chart-scale is-current" x="${scaleX}" y="${currentLabelY.toFixed(1)}">${formatInt(currentPoint.displayKcal ?? currentPoint.totalKcal)} kcal</text>
      <text class="diet-chart-scale" x="${scaleX}" y="${bottomLabelY}">${formatInt(yMin)} kcal</text>
      ${segments.map((segment) => `
        <line
          class="diet-chart-line ${segment.empty ? "is-empty" : ""}"
          style="stroke:url(#${segment.gradientId})"
          x1="${segment.x1}"
          y1="${segment.y1}"
          x2="${segment.x2}"
          y2="${segment.y2}"
        />
      `).join("")}
      ${showMovingAverage && !isPeriod && movingAveragePath ? `
        <path class="diet-chart-ma-line" d="${movingAveragePath}">
          <title>MA7 kalorii - wygładza pojedyncze skoki dnia.</title>
        </path>
      ` : ""}
      ${points.map((point) => `
        <circle
          class="diet-chart-dot ${point.filled ? "is-empty" : ""}"
          style="fill:${point.level.color};stroke:${point.level.color}"
          cx="${point.x.toFixed(1)}"
          cy="${point.y.toFixed(1)}"
          r="${point.filled ? 3 : 4}"
          tabindex="0"
          data-diet-date="${escapeHtml(point.day)}"
          data-diet-day="${escapeHtml(point.rangeLabel || formatShortDateWithYear(point.day))}"
          data-diet-kcal="${escapeHtml(point.estimated ? `~${formatInt(point.displayKcal)} kcal` : point.filled ? "brak danych / interpolacja" : `${formatInt(point.totalKcal)} kcal`)}"
          data-diet-level="${escapeHtml(point.estimated ? "EST / estymacja" : point.filled ? "Brak pomiaru" : point.level.label)}"
          data-diet-color="${escapeHtml(point.level.color)}"
          data-diet-estimate-meta="${escapeHtml(point.estimated ? `${point.estimateConfidence ? `confidence: ${point.estimateConfidence}. ` : ""}${point.estimateReason || "estymacja kalorii"}${point.periodStart && point.estimatedDayCount ? ` | ${formatInt(point.estimatedDayCount)} dni EST` : ""}` : "")}"
          data-diet-meta="${escapeHtml(point.filled ? "brak posiłków" : point.periodStart ? `${formatInt(point.dayCount || 0)} dni | ${formatInt(point.mealCount)} pos.` : `${formatInt(point.mealCount)} pos.`)}"
        ></circle>
      `).join("")}
      <text class="diet-chart-label" x="${padX}" y="${height - 5}">${formatShortDateWithYear(rangeFirst.periodStart || rangeFirst.day)}</text>
      <text class="diet-chart-label" x="${plotRight}" y="${height - 5}" text-anchor="end">${formatShortDateWithYear(rangeLast.periodEnd || rangeLast.day)}</text>
    </svg>
  `;
}

function renderMeals(day) {
  if (!day.meals.length) {
    return `<div class="diet-empty">${status === "loading" ? "Ładuję posiłki" : "Brak posiłków dla tego dnia"}</div>`;
  }

  return day.meals.map((meal) => `
    <div class="diet-meal-row">
      <div>
        <div class="diet-meal-name">${escapeHtml(meal.name)}</div>
        <div class="diet-meal-meta">${formatShortDateWithYear(day.day)}</div>
      </div>
      <div class="diet-meal-side">
        <strong>${formatInt(meal.kcal)} kcal</strong>
        <div class="diet-meal-actions">
          <button class="diet-edit" type="button" data-edit-meal="${escapeHtml(meal.id)}" data-edit-meal-name="${escapeHtml(meal.name)}" data-edit-meal-kcal="${meal.kcal}">Edytuj</button>
          <button class="diet-delete" type="button" data-delete-meal="${escapeHtml(meal.id)}">Usuń</button>
        </div>
      </div>
    </div>
  `).join("");
}

function renderTopUpIdeas(remaining) {
  if (!topUpIdeasOpen) return "";
  const safeRemaining = Math.max(0, Math.round(readNumber(remaining) || 0));
  if (!safeRemaining) {
    return `
      <section class="diet-top-up-panel" aria-live="polite">
        <div class="diet-section-head">
          <div>
            <span>Pomys\u0142y na dobicie</span>
            <small>cel jest ju\u017c domkni\u0119ty</small>
          </div>
        </div>
        <div class="diet-empty">Nie ma czego dobija\u0107 dla tego dnia.</div>
      </section>
    `;
  }

  const now = new Date();
  const suggestions = buildCalorieTopUpSuggestions(dietDays, safeRemaining, {
    hour: now.getHours(),
    limit: 14,
  });

  if (!suggestions.length) {
    return `
      <section class="diet-top-up-panel" aria-live="polite">
        <div class="diet-section-head">
          <div>
            <span>Pomys\u0142y na dobicie</span>
            <small>${formatInt(safeRemaining)} kcal zosta\u0142o</small>
          </div>
        </div>
        <div class="diet-empty">Za ma\u0142o historii, \u017ceby u\u0142o\u017cy\u0107 sensowne propozycje.</div>
      </section>
    `;
  }

  return `
    <section class="diet-top-up-panel" aria-live="polite">
      <div class="diet-section-head">
        <div>
          <span>Pomys\u0142y na dobicie</span>
          <small>${formatInt(safeRemaining)} kcal zosta\u0142o | teraz ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}</small>
        </div>
      </div>
      <div class="diet-top-up-grid">
        ${suggestions.map((suggestion) => `
          <article class="diet-top-up-card">
            <div class="diet-top-up-card-head">
              <span>${escapeHtml(suggestion.label)}</span>
              <strong>${formatInt(suggestion.totalKcal)} kcal</strong>
            </div>
            <small>${suggestion.leftAfter ? `zostanie ${formatInt(suggestion.leftAfter)} kcal` : "trafiasz w punkt"}</small>
            <div class="diet-top-up-meals">
              ${suggestion.meals.map((meal) => `
                <button
                  class="diet-top-up-meal"
                  type="button"
                  data-top-up-meal-name="${escapeHtml(meal.name)}"
                  data-top-up-meal-kcal="${meal.kcal}"
                  title="Wpisz ten posi\u0142ek do formularza"
                >
                  <span>${escapeHtml(meal.name)}</span>
                  <strong>${formatInt(meal.kcal)} kcal</strong>
                </button>
              `).join("")}
            </div>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function render() {
  if (!root) return;

  const day = selectedDayData();
  const remaining = day.goalKcal - day.totalKcal;
  const percent = day.goalKcal > 0 ? Math.min(140, Math.round((day.totalKcal / day.goalKcal) * 100)) : 0;
  const over = remaining < 0;
  const calorieLevel = getCalorieLevel(day.totalKcal);
  const activeDietHistoryDays = getActiveDietHistoryDays();
  const activeDietHistoryOptions = getActiveDietHistoryOptions();
  const dietChartTitle = getDietChartTitle();
  const dietChartHistoryUnit = getDietChartHistoryUnit();
  const allDietHistoryRange = isAllHistoryRange(activeDietHistoryDays);
  const canDietGoForward = !allDietHistoryRange && !isSameOrAfterToday(dietChartEndDay);
  const showEstimateActions = canEstimateSelectedDay(day);

  root.innerHTML = `
    <header class="diet-head">
      <div class="title" id="diet-title">
        <svg class="ico" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M7 2h2v9a3 3 0 0 1-2 2.83V22H5v-8.17A3 3 0 0 1 3 11V2h2v8h1V2h1v8h1V2zm8 0c3 1.6 5 4.55 5 8.25 0 2.74-1.22 4.69-3 5.42V22h-2V2z" />
        </svg>
        <div>
          Dieta
          <div class="meta">Posiłki, kcal i cel dzienny</div>
        </div>
      </div>
      <div class="diet-date-picker">
        <input id="diet-day-text" type="text" inputmode="numeric" value="${escapeHtml(formatDateInputPl(selectedDay))}" placeholder="dd.mm.rrrr" autocomplete="off" />
        <input id="diet-day-native" class="diet-native-date" type="date" value="${selectedDay}" tabindex="-1" aria-hidden="true" />
        <button id="diet-calendar" type="button" title="Kalendarz">Kal.</button>
      </div>
    </header>

    <div class="diet-tiles">
      <article class="diet-tile">
        <span>Kalorie</span>
        <strong style="color:${calorieLevel.color}">${formatInt(day.totalKcal)} kcal</strong>
        <em>
          <span class="diet-level-pill" style="--diet-level-color:${calorieLevel.color}">
            <span></span>${escapeHtml(calorieLevel.label)}
          </span>
        </em>
        <div class="diet-progress" aria-hidden="true"><span style="width:${percent}%;background:${calorieLevel.color}"></span></div>
      </article>
      <article class="diet-tile">
        <span>${over ? "Ponad cel" : "Zostało"}</span>
        <strong class="${over ? "is-over" : "is-fresh"}">${formatInt(Math.abs(remaining))} kcal</strong>
        <em>cel ${formatInt(day.goalKcal)} kcal</em>
        ${!over && remaining > 0 ? `
          <button
            class="diet-top-up-toggle ${topUpIdeasOpen ? "is-active" : ""}"
            id="diet-top-up-toggle"
            type="button"
            aria-expanded="${topUpIdeasOpen ? "true" : "false"}"
          >
            Pomys\u0142y na dobicie
          </button>
        ` : ""}
      </article>
      <article class="diet-tile">
        <span>Posiłki</span>
        <strong>${formatInt(day.meals.length)}</strong>
        <em>${formatShortDateWithYear(day.day)}</em>
      </article>
    </div>
    ${renderTopUpIdeas(remaining)}

    <section class="diet-chart">
      <div class="diet-section-head">
        <div>
          <span>${dietChartTitle}</span>
          <small>${formatDateRange(dietHistory)}</small>
        </div>
        <div class="weight-cut-chart-actions diet-chart-actions">
          <button class="weight-cut-chart-nav" id="diet-chart-prev" type="button" aria-label="Poprzedni zakres kalorii" ${allDietHistoryRange ? "disabled" : ""}>&lsaquo;</button>
          <button class="weight-cut-chart-nav" id="diet-chart-next" type="button" aria-label="Następny zakres kalorii" ${canDietGoForward ? "" : "disabled"}>&rsaquo;</button>
          <select class="weight-cut-chart-zoom" id="diet-chart-zoom" aria-label="Zakres wykresu kalorii">
            ${activeDietHistoryOptions.map((days) => `
              <option value="${days}" ${days === activeDietHistoryDays ? "selected" : ""}>${formatHistoryOption(days, dietChartMode)}</option>
            `).join("")}
          </select>
          <button class="weight-cut-ma-toggle ${dietChartMode === "daily" ? "is-active" : ""}" type="button" data-diet-chart-mode="daily" title="Jeden punkt to suma kalorii z jednego dnia.">
            Dzień
          </button>
          <button class="weight-cut-ma-toggle ${dietChartMode === "weekly" ? "is-active" : ""}" type="button" data-diet-chart-mode="weekly" title="Jeden punkt to średnia dzienna z 7 dni.">
            Tydzień
          </button>
          <button class="weight-cut-ma-toggle ${dietChartMode === "biweekly" ? "is-active" : ""}" type="button" data-diet-chart-mode="biweekly" title="Jeden punkt to średnia dzienna z 14 dni.">
            2 tyg.
          </button>
          <button class="weight-cut-ma-toggle ${dietChartMode === "monthly" ? "is-active" : ""}" type="button" data-diet-chart-mode="monthly" title="Jeden punkt to średnia dzienna z 30 dni.">
            Miesiąc
          </button>
          <button class="weight-cut-ma-toggle ${dietChartMode === "daily" && showDietMovingAverage ? "is-active" : ""}" id="diet-ma-toggle" type="button" ${dietChartMode === "daily" ? "" : "disabled"} title="${dietChartMode === "daily" ? "MA7 kalorii - wygładza pojedyncze skoki dnia." : "MA7 działa tylko w widoku dziennym."}">
            MA7
          </button>
          ${showEstimateActions ? `
            <button class="weight-cut-history-open" id="diet-day-ignore" type="button" title="Ignoruj wybrany dzie\u0144 w estymacjach i statystykach">
              Ignoruj dzie\u0144
            </button>
            <button class="weight-cut-history-open" id="diet-estimate-generate" type="button" title="Zr\u00f3b estymacj\u0119 dla wybranego dnia">
              Zr\u00f3b estymacj\u0119
            </button>
            <button class="weight-cut-history-open" id="diet-estimate-clear" type="button" title="Usu\u0144 estymacj\u0119 z wybranego dnia">
              Usu\u0144 estymacj\u0119
            </button>
          ` : ""}
          <button class="weight-cut-history-open" id="diet-report" type="button" title="Pobierz raport dzienny kalorii .txt">
            Raport
          </button>
          <button class="weight-cut-history-open" id="diet-combined-report" type="button" title="Pobierz raport zbiorczy .txt">
            Zbiorczy
          </button>
          <span class="weight-cut-history-open diet-chart-history-count">
            Historia${dietHistory.length ? ` | ${dietHistory.length} ${dietChartHistoryUnit}` : ""}
          </span>
        </div>
      </div>
      ${renderDietChart(dietHistory, dietChartMode === "daily" && showDietMovingAverage)}
      ${renderCalorieLegend()}
    </section>

    <section class="diet-editor">
      <div class="diet-section-head">
        <div>
          <span>Posiłki</span>
          <small>${formatShortDateWithYear(day.day)}</small>
        </div>
      </div>
      <form class="diet-form" id="diet-form">
        <div class="diet-meal-name-field">
          <input id="diet-meal-name" type="text" value="${escapeHtml(mealNameDraft)}" placeholder="nazwa posiłku" autocomplete="off" aria-autocomplete="list" aria-controls="diet-meal-suggestions" />
          ${renderMealSuggestions(mealNameDraft)}
        </div>
        <input id="diet-meal-kcal" type="number" min="0" step="1" inputmode="numeric" value="${escapeHtml(mealKcalDraft)}" placeholder="kcal" />
        <button id="diet-meal-submit" type="submit">${editingMealId ? "Zapisz" : "Dodaj"}</button>
      </form>
      <div class="diet-meal-list">
        ${renderMeals(day)}
      </div>
    </section>

    <footer class="hb-foot muted diet-footer">
      ${renderDietFooter()}
    </footer>
  `;

  bindEvents();
}

function renderDietFooter() {
  const loaded = lastLoadedAt ? formatLoadedAt(lastLoadedAt) : "—";
  const load = loadTimeSuffix(lastLoadMs);
  if (status === "error") {
    return `Błąd synchronizacji${lastDietError ? `: ${escapeHtml(lastDietError)}` : ""} · ostatnio: ${loaded}`;
  }
  const prefix = status === "loading" ? "Synchronizacja" : "Ostatnia synchronizacja";
  return `${prefix}: ${loaded}${load ? ` · ${load}` : ""}`;
}

function openCalendar() {
  const text = document.getElementById("diet-day-text");
  const anchor = document.querySelector(".diet-date-picker");
  openDatePopover({
    anchor,
    selectedDay,
    parseInput: parseDayInput,
    textInput: text,
    onSelect: updateSelectedDay,
  });
}

function updateSelectedDay(nextDay) {
  selectedDay = nextDay || todayIso();
  render();
}

function bindEvents() {
  const text = document.getElementById("diet-day-text");
  const native = document.getElementById("diet-day-native");

  text?.addEventListener("click", openCalendar);
  text?.addEventListener("change", () => {
    const nextDay = parseDayInput(text.value);
    if (nextDay) updateSelectedDay(nextDay);
  });
  document.getElementById("diet-calendar")?.addEventListener("click", openCalendar);
  native?.addEventListener("change", () => updateSelectedDay(native.value || todayIso()));

  document.getElementById("diet-top-up-toggle")?.addEventListener("click", () => {
    topUpIdeasOpen = !topUpIdeasOpen;
    render();
  });

  document.getElementById("diet-estimate-generate")?.addEventListener("click", () => {
    generateDietEstimates().catch((error) => {
      status = "error";
      lastDietError = error?.message || "nie uda\u0142o si\u0119 zrobi\u0107 estymacji";
      render();
      window.setTimeout(refreshDiet, 1200);
    });
  });

  document.getElementById("diet-estimate-clear")?.addEventListener("click", () => {
    clearDietEstimates().catch((error) => {
      status = "error";
      lastDietError = error?.message || "nie uda\u0142o si\u0119 usun\u0105\u0107 estymacji";
      render();
      window.setTimeout(refreshDiet, 1200);
    });
  });

  document.getElementById("diet-day-ignore")?.addEventListener("click", () => {
    ignoreDietDay().catch((error) => {
      status = "error";
      lastDietError = error?.message || "nie uda\u0142o si\u0119 zignorowa\u0107 dnia";
      render();
      window.setTimeout(refreshDiet, 1200);
    });
  });

  document.getElementById("diet-report")?.addEventListener("click", () => {
    generateDietDailyReport({
      days: getDailyReportDays(getActiveDietHistoryDays()),
      end: dietChartEndDay,
    }).catch((error) => console.error("Diet report failed", error));
  });

  document.getElementById("diet-combined-report")?.addEventListener("click", () => {
    generateCombinedDailyReport({
      days: getDailyReportDays(getActiveDietHistoryDays()),
      end: dietChartEndDay,
    }).catch((error) => console.error("Combined report failed", error));
  });

  document.getElementById("diet-chart-prev")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveDietHistoryDays())) return;
    dietChartEndDay = addDaysIso(dietChartEndDay, -getActiveDietHistoryDays());
    refreshDiet();
  });

  document.getElementById("diet-chart-next")?.addEventListener("click", () => {
    if (isAllHistoryRange(getActiveDietHistoryDays())) return;
    dietChartEndDay = addDaysIso(dietChartEndDay, getActiveDietHistoryDays());
    if (dietChartEndDay > todayIso()) dietChartEndDay = todayIso();
    refreshDiet();
  });

  document.getElementById("diet-chart-zoom")?.addEventListener("change", (event) => {
    const fallbackDays = isDietPeriodChartMode() ? getDietPeriodHistoryDays() : DIET_HISTORY_DAYS;
    const options = getActiveDietHistoryOptions();
    const rawValue = event.currentTarget.value;
    const nextDays = rawValue === HISTORY_ALL_VALUE
      ? HISTORY_ALL_VALUE
      : Math.max(1, Math.round(readNumber(rawValue) || fallbackDays));
    if (isDietPeriodChartMode()) {
      setDietPeriodHistoryDays(dietChartMode, options.includes(nextDays) ? nextDays : fallbackDays);
    } else {
      dietHistoryDays = options.includes(nextDays) ? nextDays : DIET_HISTORY_DAYS;
    }
    refreshDiet();
  });

  root.querySelectorAll("[data-diet-chart-mode]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const nextMode = event.currentTarget.dataset.dietChartMode;
      if (nextMode !== "daily" && !PERIOD_DAYS[nextMode]) return;
      if (dietChartMode === nextMode) return;
      dietChartMode = nextMode;
      dietChartEndDay = todayIso();
      refreshDiet();
    });
  });

  document.getElementById("diet-ma-toggle")?.addEventListener("click", () => {
    showDietMovingAverage = !showDietMovingAverage;
    render();
  });

  const mealNameInput = document.getElementById("diet-meal-name");
  const mealKcalInput = document.getElementById("diet-meal-kcal");
  if (mealNameInput instanceof HTMLInputElement) {
    mealNameInput.addEventListener("input", () => {
      const cursor = mealNameInput.selectionStart ?? mealNameInput.value.length;
      mealNameDraft = normalizeMealDraft(mealNameInput.value);
      if (mealNameInput.value !== mealNameDraft) {
        mealNameInput.value = mealNameDraft;
        if (Number.isFinite(cursor)) mealNameInput.setSelectionRange(cursor, cursor);
      }
      const exact = findExactMealSuggestion(mealNameInput.value);
      if (exact && mealKcalInput instanceof HTMLInputElement && !mealKcalDraft) {
        mealKcalDraft = String(exact.kcal);
        mealKcalInput.value = mealKcalDraft;
      }
      render();
      const nextInput = document.getElementById("diet-meal-name");
      if (nextInput instanceof HTMLInputElement) {
        nextInput.focus();
        const nextCursor = Math.min(cursor, nextInput.value.length);
        nextInput.setSelectionRange(nextCursor, nextCursor);
      }
    });
  }
  if (mealKcalInput instanceof HTMLInputElement) {
    mealKcalInput.addEventListener("input", () => {
      mealKcalDraft = mealKcalInput.value;
    });
  }

  root.querySelectorAll("[data-meal-suggestion-name]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => event.preventDefault());
    button.addEventListener("click", () => {
      const nameInput = document.getElementById("diet-meal-name");
      const kcalInput = document.getElementById("diet-meal-kcal");
      if (nameInput instanceof HTMLInputElement) {
        mealNameDraft = normalizeMealName(button.getAttribute("data-meal-suggestion-name"));
        nameInput.value = mealNameDraft;
        nameInput.focus();
      }
      if (kcalInput instanceof HTMLInputElement) {
        mealKcalDraft = String(Math.max(0, Math.round(readNumber(button.getAttribute("data-meal-suggestion-kcal")) || 0)) || "");
        kcalInput.value = mealKcalDraft;
      }
    });
  });

  root.querySelectorAll("[data-top-up-meal-name]").forEach((button) => {
    button.addEventListener("click", () => {
      const nameInput = document.getElementById("diet-meal-name");
      const kcalInput = document.getElementById("diet-meal-kcal");
      if (nameInput instanceof HTMLInputElement) {
        mealNameDraft = normalizeMealName(button.getAttribute("data-top-up-meal-name"));
        nameInput.value = mealNameDraft;
      }
      if (kcalInput instanceof HTMLInputElement) {
        mealKcalDraft = String(Math.max(0, Math.round(readNumber(button.getAttribute("data-top-up-meal-kcal")) || 0)) || "");
        kcalInput.value = mealKcalDraft;
        kcalInput.focus();
        kcalInput.select();
      }
    });
  });

  document.getElementById("diet-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const nameInput = document.getElementById("diet-meal-name");
    const kcalInput = document.getElementById("diet-meal-kcal");
    const name = normalizeMealName(nameInput?.value);
    const kcal = Math.max(0, Math.round(readNumber(kcalInput?.value) || 0));
    if (!name || !kcal) return;
    await saveMeal({ id: editingMealId || makeMealId(), day: selectedDay, name, kcal });
  });

  root.querySelectorAll("[data-edit-meal]").forEach((button) => {
    button.addEventListener("click", () => {
      editingMealId = button.getAttribute("data-edit-meal") || null;
      const nameInput = document.getElementById("diet-meal-name");
      const kcalInput = document.getElementById("diet-meal-kcal");
      const submit = document.getElementById("diet-meal-submit");
      if (nameInput instanceof HTMLInputElement) {
        mealNameDraft = normalizeMealName(button.getAttribute("data-edit-meal-name"));
        nameInput.value = mealNameDraft;
        nameInput.focus();
        nameInput.select();
      }
      if (kcalInput instanceof HTMLInputElement) {
        mealKcalDraft = String(Math.max(0, Math.round(readNumber(button.getAttribute("data-edit-meal-kcal")) || 0)) || "");
        kcalInput.value = mealKcalDraft;
      }
      if (submit instanceof HTMLButtonElement) submit.textContent = "Zapisz";
    });
  });

  root.querySelectorAll("[data-delete-meal]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteMeal(selectedDay, button.getAttribute("data-delete-meal"));
    });
  });

  root.querySelectorAll(".diet-chart-dot, .diet-chart-legend-item").forEach((target) => {
    if (target.classList.contains("diet-chart-dot")) {
      target.addEventListener("click", selectDietChartDay);
    }
    target.addEventListener("mouseenter", showTooltip);
    target.addEventListener("mousemove", moveTooltip);
    target.addEventListener("mouseleave", hideTooltip);
    target.addEventListener("focus", showTooltip);
    target.addEventListener("blur", hideTooltip);
  });
}

function selectDietChartDay(event) {
  const day = event.currentTarget?.dataset?.dietDate || "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return;
  selectedDay = day;
  hideTooltip();
  render();
}

function ensureTooltip() {
  let tooltip = document.getElementById("diet-chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "diet-chart-tooltip";
    tooltip.className = "diet-chart-tooltip";
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function positionTooltip(tooltip, x, y) {
  const rect = tooltip.getBoundingClientRect();
  const left = Math.min(window.innerWidth - rect.width - 8, Math.max(8, x + 12));
  const top = Math.min(window.innerHeight - rect.height - 8, Math.max(8, y + 12));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function showTooltip(event) {
  const target = event.currentTarget;
  const tooltip = ensureTooltip();
  const meta = target.dataset.dietEstimateMeta || target.dataset.dietMeta || "";
  tooltip.innerHTML = `
    <div class="diet-tooltip-day">${escapeHtml(target.dataset.dietDay || "")}</div>
    <div class="diet-tooltip-kcal">${escapeHtml(target.dataset.dietKcal || "")}</div>
    <div class="diet-tooltip-level">
      <span style="background:${escapeHtml(target.dataset.dietColor || "")}"></span>
      ${escapeHtml(target.dataset.dietLevel || "")}
    </div>
    ${meta ? `<div class="diet-tooltip-meta">${escapeHtml(meta)}</div>` : ""}
  `;
  tooltip.classList.add("is-visible");
  const rect = target.getBoundingClientRect();
  positionTooltip(tooltip, rect.left + rect.width / 2, rect.top + rect.height / 2);
}

function moveTooltip(event) {
  const tooltip = document.getElementById("diet-chart-tooltip");
  if (!tooltip?.classList.contains("is-visible")) return;
  positionTooltip(tooltip, event.clientX, event.clientY);
}

function hideTooltip() {
  document.getElementById("diet-chart-tooltip")?.classList.remove("is-visible");
}

async function generateDietEstimates() {
  status = "loading";
  render();

  const { startDay, endDay } = getEstimationWindow();
  const contextStartDay = addDaysIso(startDay, -ESTIMATION_LOOKBACK_DAYS);
  const stepDays = Math.max(1, daysBetweenIso(contextStartDay, endDay) + 1);
  const [weightPayload, stepsPayload] = await Promise.all([
    fetchJson(`${WEIGHT_HISTORY_ENDPOINT}?${new URLSearchParams({ days: String(ESTIMATION_CONTEXT_DAYS) }).toString()}`),
    fetchJson(`${STEPS_HISTORY_ENDPOINT}?${new URLSearchParams({ days: String(stepDays), end: endDay }).toString()}`),
  ]);
  const weightRows = normalizeWeightHistoryRows(weightPayload.daily);
  const stepsRows = normalizeStepsHistoryRows(stepsPayload.daily);
  const estimationRows = buildDietRowsForEstimation(contextStartDay, endDay, weightRows, stepsRows);
  const estimates = estimateMissingCalories(estimationRows, {
    startDay,
    endDay,
    today: todayIso(),
  });

  const response = await fetch(UPSERT_DIET_ESTIMATES_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ estimates }),
  });
  if (!response.ok) throw new Error(`estymacja: HTTP ${response.status}`);
  await refreshDiet();
}

async function clearDietEstimates() {
  status = "loading";
  render();

  const { startDay, endDay } = getEstimationWindow();
  const days = dailyRange(startDay, endDay);
  const response = await fetch(DELETE_DIET_ESTIMATES_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ days }),
  });
  if (!response.ok) throw new Error(`usuwanie estymacji: HTTP ${response.status}`);
  await refreshDiet();
}

async function ignoreDietDay() {
  status = "loading";
  render();

  const response = await fetch(IGNORE_DIET_DAY_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ days: [selectedDay] }),
  });
  if (!response.ok) throw new Error(`ignorowanie dnia: HTTP ${response.status}`);
  await refreshDiet();
}

async function refreshDiet() {
  if (!root) return;

  try {
    const stopTimer = startLoadTimer();
    const activeDays = getActiveDietHistoryDays();
    const historyUrl = isAllHistoryRange(activeDays)
      ? null
      : `${DIET_HISTORY_ENDPOINT}?${new URLSearchParams({
        days: String(activeDays),
        end: dietChartEndDay,
      }).toString()}`;
    const [daysResponse, historyResponse] = await Promise.all([
      fetch(DIET_DAYS_ENDPOINT, { cache: "no-store" }),
      historyUrl ? fetch(historyUrl, { cache: "no-store" }) : Promise.resolve(null),
    ]);
    if (!daysResponse.ok || (historyResponse && !historyResponse.ok)) throw new Error("Diet API failed");
    const daysPayload = await daysResponse.json();
    const historyPayload = historyResponse ? await historyResponse.json() : null;
    goalKcal = Math.max(0, Math.round(readNumber(daysPayload.goal_kcal) || DEFAULT_DIET_GOAL_KCAL));
    dietDays = Array.isArray(daysPayload.days) ? daysPayload.days.map(normalizeDay) : [];
    const dailyRows = historyPayload
      ? normalizeDietHistoryRows(historyPayload.daily)
      : dietDaysToHistoryRows(dietDays, dietChartEndDay);
    dietHistory = isDietPeriodChartMode()
      ? buildPeriodDietHistory(dailyRows, activeDays, dietChartEndDay, PERIOD_DAYS[dietChartMode] || 7)
      : dailyRows;
    lastLoadMs = stopTimer();
    lastLoadedAt = new Date();
    status = "idle";
    lastDietError = "";
  } catch (error) {
    status = "error";
    lastDietError = error?.message || "nieznany błąd";
  }

  const signature = JSON.stringify({
    goalKcal,
    dietDays,
    dietHistory,
    status,
    selectedDay,
    mode: dietChartMode,
    days: getActiveDietHistoryDays(),
    end: dietChartEndDay,
  });
  if (signature !== lastSignature) {
    lastSignature = signature;
    render();
  }
}

async function saveMeal(meal) {
  status = "loading";
  render();
  try {
    const response = await fetch(UPSERT_DIET_MEAL_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(meal),
    });
    if (!response.ok) throw new Error(`zapis posiłku: HTTP ${response.status}`);
    editingMealId = null;
    mealNameDraft = "";
    mealKcalDraft = "";
    await refreshDiet();
  } catch (error) {
    status = "error";
    lastDietError = error?.message || "nie udało się zapisać posiłku";
    render();
    window.setTimeout(refreshDiet, 1200);
  }
}

async function deleteMeal(day, id) {
  if (!day || !id) return;
  status = "loading";
  render();
  try {
    const response = await fetch(DELETE_DIET_MEAL_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ day, id }),
    });
    if (!response.ok) throw new Error(`usuwanie posiłku: HTTP ${response.status}`);
    if (editingMealId === id) editingMealId = null;
    await refreshDiet();
  } catch (error) {
    status = "error";
    lastDietError = error?.message || "nie udało się usunąć posiłku";
    render();
    window.setTimeout(refreshDiet, 1200);
  }
}

if (root) {
  render();
  refreshDiet();
  setInterval(refreshDiet, DIET_POLL_MS);
}
