const MS_PER_DAY = 86400000;
const DEFAULT_BASELINE_KCAL = 2200;
const MIN_HISTORY_DAYS = 5;
const MIN_ESTIMATED_KCAL = 800;
const MAX_ESTIMATED_KCAL = 6000;

function readNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).trim().replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function isIsoDay(day) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(day || ""));
}

function dayTime(day) {
  const parsed = new Date(`${day}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed.getTime();
}

function addDaysIso(day, amount) {
  const time = dayTime(day);
  if (!Number.isFinite(time)) return "";
  const date = new Date(time);
  date.setDate(date.getDate() + amount);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const currentDay = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${currentDay}`;
}

function daysBetween(startDay, endDay) {
  const startTime = dayTime(startDay);
  const endTime = dayTime(endDay);
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime)) return 0;
  return Math.round((endTime - startTime) / MS_PER_DAY);
}

function median(values) {
  const sorted = values
    .map(readNumber)
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2) return sorted[middle];
  return (sorted[middle - 1] + sorted[middle]) / 2;
}

function normalizeDay(row) {
  const manualCalories = readNumber(row?.manualCalories ?? row?.caloriesManual);
  const estimatedCalories = readNumber(row?.estimatedCalories ?? row?.caloriesEstimated);
  const weightKg = readNumber(row?.weightKg ?? row?.avgWeightKg);
  const steps = readNumber(row?.steps);
  return {
    ...row,
    day: String(row?.day || row?.date || ""),
    manualCalories: Number.isFinite(manualCalories) && manualCalories > 0 ? Math.round(manualCalories) : null,
    estimatedCalories: Number.isFinite(estimatedCalories) && estimatedCalories > 0 ? Math.round(estimatedCalories) : null,
    goalKcal: Math.max(0, Math.round(readNumber(row?.goalKcal ?? row?.goal_kcal) || DEFAULT_BASELINE_KCAL)),
    weightKg: Number.isFinite(weightKg) ? weightKg : null,
    steps: Number.isFinite(steps) && row?.stepsFilled !== true ? Math.max(0, Math.round(steps)) : null,
    ignored: row?.ignored === true || row?.caloriesSource === "ignored" || row?.calories_source === "ignored",
  };
}

function manualHistoryBefore(days, startDay, windowDays) {
  const fromDay = addDaysIso(startDay, -windowDays);
  return days
    .filter((day) => day.day >= fromDay && day.day < startDay && Number.isFinite(day.manualCalories))
    .map((day) => day.manualCalories);
}

function medianManualCaloriesBefore(days, startDay, windowDays) {
  const values = manualHistoryBefore(days, startDay, windowDays);
  return values.length >= MIN_HISTORY_DAYS ? median(values) : null;
}

function manualHistoryCount(days, startDay) {
  return Math.max(
    manualHistoryBefore(days, startDay, 14).length,
    manualHistoryBefore(days, startDay, 30).length,
  );
}

function medianStepsBefore(days, startDay, windowDays) {
  const fromDay = addDaysIso(startDay, -windowDays);
  const values = days
    .filter((day) => day.day >= fromDay && day.day < startDay && Number.isFinite(day.steps) && day.steps > 0)
    .map((day) => day.steps);
  return values.length >= MIN_HISTORY_DAYS ? median(values) : null;
}

function lastWeightBefore(days, startDay) {
  return [...days]
    .filter((day) => day.day < startDay && Number.isFinite(day.weightKg))
    .sort((a, b) => b.day.localeCompare(a.day))[0] || null;
}

function firstWeightAfter(days, endDay) {
  return [...days]
    .filter((day) => day.day > endDay && Number.isFinite(day.weightKg))
    .sort((a, b) => a.day.localeCompare(b.day))[0] || null;
}

function lastWeightInside(block) {
  return [...block]
    .filter((day) => Number.isFinite(day.weightKg))
    .sort((a, b) => b.day.localeCompare(a.day))[0] || null;
}

function weightTrendBefore(days, startDay, weightBefore) {
  if (!weightBefore) return 0;
  const targetDay = addDaysIso(startDay, -7);
  const prior = [...days]
    .filter((day) => day.day <= targetDay && day.day < weightBefore.day && Number.isFinite(day.weightKg))
    .sort((a, b) => b.day.localeCompare(a.day))[0]
    || [...days]
      .filter((day) => day.day < weightBefore.day && Number.isFinite(day.weightKg))
      .sort((a, b) => b.day.localeCompare(a.day))[0];
  if (!prior) return 0;
  const elapsedDays = Math.max(1, daysBetween(prior.day, weightBefore.day));
  return (weightBefore.weightKg - prior.weightKg) / elapsedDays;
}

function confidenceFor(details) {
  if (
    details.missingDays === 1
    && details.hasWeightBefore
    && details.hasWeightAfter
    && details.hasEnoughManualCalories
    && details.hasUsableSteps
    && Math.abs(details.weightSurprise || 0) <= 1.5
  ) {
    return "high";
  }

  if (
    details.missingDays <= 3
    && details.hasWeightBefore
    && details.hasWeightAfter
    && details.hasEnoughManualCalories
    && Math.abs(details.weightSurprise || 0) <= 1.5
  ) {
    return "medium";
  }

  return "low";
}

function estimateBlock(block, days) {
  const n = block.length;
  const startDay = block[0].day;
  const endDay = block[block.length - 1].day;
  const baselineCalories = medianManualCaloriesBefore(days, startDay, 14)
    ?? medianManualCaloriesBefore(days, startDay, 30)
    ?? block[0].goalKcal
    ?? DEFAULT_BASELINE_KCAL;
  const enoughManualCalories = manualHistoryCount(days, startDay) >= MIN_HISTORY_DAYS;
  const weightBefore = lastWeightBefore(days, startDay);
  const weightAfter = firstWeightAfter(days, endDay) || lastWeightInside(block);
  let dailyTrend = 0;
  let weightSurprise = 0;
  let weightAdjustment = 0;

  if (weightBefore && weightAfter) {
    dailyTrend = weightTrendBefore(days, startDay, weightBefore);
    const expectedWeight = weightBefore.weightKg + dailyTrend * n;
    weightSurprise = weightAfter.weightKg - expectedWeight;
    weightAdjustment = clamp(2000 * weightSurprise, -1500, 5000);
  }

  const baselineSteps = medianStepsBefore(days, startDay, 14) ?? medianStepsBefore(days, startDay, 30);
  const knownStepDays = block.filter((day) => Number.isFinite(day.steps));
  const hasUsableSteps = Number.isFinite(baselineSteps) && knownStepDays.length >= Math.ceil(n / 2);
  let stepsAdjustment = 0;
  if (hasUsableSteps) {
    const actualSteps = knownStepDays.reduce((sum, day) => sum + day.steps, 0);
    const expectedSteps = baselineSteps * n;
    stepsAdjustment = clamp((actualSteps - expectedSteps) * 0.045, -800, 1200);
  }

  const total = n * baselineCalories + weightAdjustment + stepsAdjustment;
  const perDay = Math.round(clamp(total / n, MIN_ESTIMATED_KCAL, MAX_ESTIMATED_KCAL));
  const confidence = confidenceFor({
    missingDays: n,
    hasWeightBefore: Boolean(weightBefore),
    hasWeightAfter: Boolean(weightAfter),
    hasEnoughManualCalories: enoughManualCalories,
    hasUsableSteps,
    weightSurprise,
  });

  return block.map((day) => ({
    day: day.day,
    date: day.day,
    estimatedCalories: perDay,
    caloriesSource: "estimated",
    estimateConfidence: confidence,
    estimateReason: "Estimated from median logged calories, recent weight trend, weight deviation and steps correction.",
    estimateComponents: {
      baselineCalories: Math.round(baselineCalories),
      weightAdjustment: Math.round(weightAdjustment),
      stepsAdjustment: Math.round(stepsAdjustment),
      dailyTrendKg: Number(dailyTrend.toFixed(4)),
      weightSurpriseKg: Number(weightSurprise.toFixed(3)),
      baselineSteps: Number.isFinite(baselineSteps) ? Math.round(baselineSteps) : null,
      knownStepDays: knownStepDays.length,
    },
  }));
}

export function estimateMissingCalories(days, options = {}) {
  const startDay = String(options.startDay || "");
  const endDay = String(options.endDay || "");
  const today = String(options.today || new Date().toISOString().slice(0, 10));
  if (!isIsoDay(startDay) || !isIsoDay(endDay)) return [];

  const normalizedDays = (Array.isArray(days) ? days : [])
    .map(normalizeDay)
    .filter((day) => isIsoDay(day.day))
    .sort((a, b) => a.day.localeCompare(b.day));
  const targetDays = normalizedDays.filter((day) => (
    day.day >= startDay
    && day.day <= endDay
    && day.day < today
    && !Number.isFinite(day.manualCalories)
    && day.ignored !== true
  ));

  const blocks = [];
  let currentBlock = [];
  targetDays.forEach((day) => {
    const previous = currentBlock[currentBlock.length - 1];
    if (!previous || daysBetween(previous.day, day.day) === 1) {
      currentBlock.push(day);
      return;
    }
    if (currentBlock.length) blocks.push(currentBlock);
    currentBlock = [day];
  });
  if (currentBlock.length) blocks.push(currentBlock);

  return blocks.flatMap((block) => estimateBlock(block, normalizedDays));
}
