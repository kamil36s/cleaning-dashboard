const DAY_MS = 86_400_000;

export const WEIGHT_MA_WINDOW_DAYS = 7;
export const WEIGHT_MA_TARGET_KG = 83;
export const WEIGHT_KCAL_PER_KG = 7500;

function validIsoDay(value) {
  const day = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : "";
}

function dayTime(day) {
  return Date.parse(`${day}T00:00:00Z`);
}

function addDays(day, amount) {
  const timestamp = dayTime(day);
  if (!Number.isFinite(timestamp)) return "";
  return new Date(timestamp + amount * DAY_MS).toISOString().slice(0, 10);
}

export function aggregateDailyWeightEvents(events = []) {
  const groups = new Map();
  events.forEach((event) => {
    const day = validIsoDay(event?.timestamp || event?.day);
    const weightKg = Number(event?.weightKg ?? event?.weight_kg ?? event?.avgWeightKg ?? event?.avg_weight_kg);
    if (!day || !Number.isFinite(weightKg)) return;
    const group = groups.get(day) || [];
    group.push(weightKg);
    groups.set(day, group);
  });

  return Array.from(groups, ([day, weights]) => ({
    day,
    weightKg: weights.reduce((sum, weight) => sum + weight, 0) / weights.length,
  })).sort((a, b) => a.day.localeCompare(b.day));
}

export function interpolateDailyWeights(dailyWeights = []) {
  if (!dailyWeights.length) return [];
  const rows = [...dailyWeights].sort((a, b) => a.day.localeCompare(b.day));
  const firstDay = rows[0].day;
  const lastDay = rows[rows.length - 1].day;
  const known = new Map(rows.map((row) => [row.day, Number(row.weightKg)]));
  const result = [];
  let previous = rows[0];
  let nextIndex = 1;

  for (let day = firstDay; day && day <= lastDay; day = addDays(day, 1)) {
    if (known.has(day)) {
      previous = { day, weightKg: known.get(day) };
      while (nextIndex < rows.length && rows[nextIndex].day <= day) nextIndex += 1;
      result.push({ day, weightKg: previous.weightKg, interpolated: false });
      continue;
    }

    const next = rows[nextIndex];
    if (!previous || !next) continue;
    const totalDays = Math.max(1, (dayTime(next.day) - dayTime(previous.day)) / DAY_MS);
    const elapsedDays = (dayTime(day) - dayTime(previous.day)) / DAY_MS;
    const weightKg = previous.weightKg
      + (next.weightKg - previous.weightKg) * (elapsedDays / totalDays);
    result.push({ day, weightKg, interpolated: true });
  }

  return result;
}

export function calculateMovingAverageSeries(dailyWeights = [], windowDays = WEIGHT_MA_WINDOW_DAYS) {
  const window = Math.max(1, Math.round(Number(windowDays) || WEIGHT_MA_WINDOW_DAYS));
  return dailyWeights.map((row, index) => {
    if (index < window - 1) return { day: row.day, value: null };
    const values = dailyWeights.slice(index - window + 1, index + 1).map((item) => Number(item.weightKg));
    if (values.some((value) => !Number.isFinite(value))) return { day: row.day, value: null };
    return {
      day: row.day,
      value: values.reduce((sum, value) => sum + value, 0) / values.length,
    };
  });
}

export function calculateMa7Stats(events = [], options = {}) {
  const goalKg = Number.isFinite(Number(options.goalKg)) ? Number(options.goalKg) : WEIGHT_MA_TARGET_KG;
  const rateStartDay = validIsoDay(options.rateStartDay);
  const kcalPerKg = Number.isFinite(Number(options.kcalPerKg)) ? Number(options.kcalPerKg) : WEIGHT_KCAL_PER_KG;
  const stableThresholdKg = Number.isFinite(Number(options.stableThresholdKg))
    ? Math.max(0, Number(options.stableThresholdKg))
    : 0.01;
  const dailyWeights = interpolateDailyWeights(aggregateDailyWeightEvents(events));
  const series = calculateMovingAverageSeries(dailyWeights, WEIGHT_MA_WINDOW_DAYS);
  const current = [...series].reverse().find((row) => Number.isFinite(row.value));
  if (!current) return null;

  const byDay = new Map(series.map((row) => [row.day, row.value]));
  const previousValue = byDay.get(addDays(current.day, -1));
  const weekAgoValue = byDay.get(addDays(current.day, -7));
  const fortnightAgoValue = byDay.get(addDays(current.day, -14));
  const trendDeltaKg = Number.isFinite(previousValue) ? current.value - previousValue : null;
  const weeklyChangeKg = Number.isFinite(weekAgoValue) ? current.value - weekAgoValue : null;
  const dailyDeficitKcal = Number.isFinite(weeklyChangeKg) ? (-weeklyChangeKg * kcalPerKg) / 7 : null;
  const distanceToGoalKg = current.value - goalKg;
  const rateStartValue = rateStartDay ? byDay.get(rateStartDay) : null;
  const rateElapsedDays = rateStartDay ? (dayTime(current.day) - dayTime(rateStartDay)) / DAY_MS : null;
  const rateSinceStartKgPerWeek = Number.isFinite(rateStartValue) && Number.isFinite(rateElapsedDays) && rateElapsedDays > 0
    ? ((current.value - rateStartValue) / rateElapsedDays) * 7
    : null;
  const etaRateKgPerDay = Number.isFinite(fortnightAgoValue)
    ? (current.value - fortnightAgoValue) / 14
    : null;

  let eta = { status: "missing", day: null, rateKgPerDay: etaRateKgPerDay };
  if (distanceToGoalKg <= 0) {
    eta = { status: "done", day: current.day, rateKgPerDay: etaRateKgPerDay };
  } else if (Number.isFinite(etaRateKgPerDay) && etaRateKgPerDay < 0) {
    const daysToGoal = distanceToGoalKg / -etaRateKgPerDay;
    eta = {
      status: "future",
      day: addDays(current.day, Math.ceil(daysToGoal - 1e-9)),
      rateKgPerDay: etaRateKgPerDay,
    };
  } else if (Number.isFinite(etaRateKgPerDay)) {
    eta = { status: "no-loss", day: null, rateKgPerDay: etaRateKgPerDay };
  }

  return {
    day: current.day,
    currentMa7Kg: current.value,
    trendDeltaKg,
    trend: !Number.isFinite(trendDeltaKg) || Math.abs(trendDeltaKg) <= stableThresholdKg
      ? "stable"
      : trendDeltaKg < 0 ? "down" : "up",
    weeklyChangeKg,
    dailyDeficitKcal,
    distanceToGoalKg,
    goalKg,
    rateStartDay: rateStartDay || null,
    rateSinceStartKgPerWeek,
    eta,
  };
}
