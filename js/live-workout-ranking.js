const EXCLUDED_WORKOUT_TYPES = new Set(["strength"]);

function localDateKey(timestamp) {
  const date = new Date(Number(timestamp));
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function roundCalories(value) {
  return Math.round((Math.max(0, Number(value) || 0) + Number.EPSILON) * 100) / 100;
}

export function normalizeCyclingCalorieRanking(days = []) {
  return (Array.isArray(days) ? days : [])
    .map((day) => {
      const activeCalories = roundCalories(day?.active_calories ?? day?.activeCalories);
      const walkingCalories = roundCalories(day?.walking_calories ?? day?.walkingCalories);
      const explicitCycling = day?.cycling_calories ?? day?.cyclingCalories;
      const cyclingCalories = roundCalories(explicitCycling == null ? activeCalories - walkingCalories : explicitCycling);
      return {
        date: String(day?.date || ""),
        activeCalories,
        cyclingCalories,
        walkingCalories,
        durationSeconds: Math.max(0, Number(day?.duration_seconds ?? day?.durationSeconds) || 0),
        sessionCount: Math.max(0, Math.round(Number(day?.session_count ?? day?.sessionCount) || 0)),
        cyclingSessionCount: Math.max(0, Math.round(Number(day?.cycling_session_count ?? day?.cyclingSessionCount) || 0)),
        walkingSessionCount: Math.max(0, Math.round(Number(day?.walking_session_count ?? day?.walkingSessionCount) || 0)),
      };
    })
    .filter((day) => /^\d{4}-\d{2}-\d{2}$/.test(day.date) && day.activeCalories > 0)
    .sort((left, right) => right.activeCalories - left.activeCalories || right.date.localeCompare(left.date))
    .map((day, index) => ({ ...day, position: index + 1 }));
}

export function buildCyclingCalorieRanking(sessions = []) {
  const grouped = new Map();
  (Array.isArray(sessions) ? sessions : []).forEach((session) => {
    if (session?.status !== "finished" || EXCLUDED_WORKOUT_TYPES.has(session?.workout_type)) return;
    const calories = Math.max(0, Number(session?.active_calories) || 0);
    const date = localDateKey(session?.started_at);
    if (!date || calories <= 0) return;
    const current = grouped.get(date) || {
      date,
      activeCalories: 0,
      cyclingCalories: 0,
      walkingCalories: 0,
      durationSeconds: 0,
      sessionCount: 0,
      cyclingSessionCount: 0,
      walkingSessionCount: 0,
    };
    current.activeCalories += calories;
    current.durationSeconds += Math.max(0, Number(session?.duration_seconds) || 0);
    current.sessionCount += 1;
    if (session?.workout_type === "virtual_walk") {
      current.walkingCalories += calories;
      current.walkingSessionCount += 1;
    } else {
      current.cyclingCalories += calories;
      current.cyclingSessionCount += 1;
    }
    grouped.set(date, current);
  });
  return normalizeCyclingCalorieRanking([...grouped.values()]);
}

export function buildCardioEfficiencyRanking(days = []) {
  return normalizeCyclingCalorieRanking(days)
    .filter((day) => day.durationSeconds > 0)
    .map((day) => ({
      ...day,
      caloriePosition: day.position,
      caloriesPerHour: roundCalories(day.activeCalories * 3600 / day.durationSeconds),
    }))
    .sort((left, right) => right.caloriesPerHour - left.caloriesPerHour
      || right.activeCalories - left.activeCalories
      || right.date.localeCompare(left.date))
    .map((day, index) => ({ ...day, position: index + 1 }));
}

export function calculateLiveCalorieRank(days = [], {
  date = localDateKey(Date.now()),
  liveCalories = 0,
  workoutType = "indoor_cycling",
} = {}) {
  const ranking = normalizeCyclingCalorieRanking(days);
  const storedToday = ranking.find((day) => day.date === date);
  const safeLiveCalories = Math.max(0, Number(liveCalories) || 0);
  const todayCalories = roundCalories((storedToday?.activeCalories || 0) + safeLiveCalories);
  const todayWalkingCalories = roundCalories((storedToday?.walkingCalories || 0) + (workoutType === "virtual_walk" ? safeLiveCalories : 0));
  const todayCyclingCalories = roundCalories((storedToday?.cyclingCalories || 0) + (workoutType === "virtual_walk" ? 0 : safeLiveCalories));
  const competitors = ranking.filter((day) => day.date !== date);
  const combined = [...competitors, {
    date,
    activeCalories: todayCalories,
    cyclingCalories: todayCyclingCalories,
    walkingCalories: todayWalkingCalories,
    sessionCount: (storedToday?.sessionCount || 0) + (safeLiveCalories > 0 ? 1 : 0),
    isToday: true,
  }].sort((left, right) => right.activeCalories - left.activeCalories || (left.isToday ? 1 : right.isToday ? -1 : right.date.localeCompare(left.date)));
  const position = combined.findIndex((day) => day.isToday) + 1;
  const next = position > 1 ? combined[position - 2] : null;
  const caloriesToNext = next ? roundCalories(Math.max(0.1, next.activeCalories - todayCalories + 0.1)) : 0;
  return {
    position,
    totalDays: combined.length,
    todayCalories,
    todayCyclingCalories,
    todayWalkingCalories,
    cyclingPercent: todayCalories ? todayCyclingCalories / todayCalories * 100 : 0,
    walkingPercent: todayCalories ? todayWalkingCalories / todayCalories * 100 : 0,
    next,
    caloriesToNext,
    isPersonalBest: position === 1 && todayCalories > 0,
  };
}

export function calorieRankTier(position) {
  const safePosition = Math.max(1, Math.round(Number(position) || 1));
  if (safePosition <= 3) return "podium";
  if (safePosition <= 10) return "top10";
  return "standard";
}

export function calorieRankMedal(position) {
  return ({ 1: "🥇", 2: "🥈", 3: "🥉" })[Number(position)] || "";
}

export function buildCardioCalorieChartSeries(days = [], { endDate, dayCount = 30 } = {}) {
  const ranking = normalizeCyclingCalorieRanking(days);
  const byDate = new Map(ranking.map((day) => [day.date, day]));
  const fallbackEnd = ranking.map((day) => day.date).sort().at(-1) || localDateKey(Date.now());
  const safeEnd = /^\d{4}-\d{2}-\d{2}$/.test(String(endDate || "")) ? String(endDate) : fallbackEnd;
  const count = Math.max(1, Math.min(3650, Math.round(Number(dayCount) || 30)));
  const cursor = new Date(`${safeEnd}T12:00:00`);
  cursor.setDate(cursor.getDate() - count + 1);
  const series = [];
  for (let index = 0; index < count; index += 1) {
    const date = localDateKey(cursor.getTime());
    const stored = byDate.get(date);
    series.push({
      date,
      activeCalories: stored?.activeCalories || 0,
      cyclingCalories: stored?.cyclingCalories || 0,
      walkingCalories: stored?.walkingCalories || 0,
      movingAverage: 0,
    });
    cursor.setDate(cursor.getDate() + 1);
  }
  return series.map((day, index) => ({
    ...day,
    movingAverage: roundCalories(
      series.slice(Math.max(0, index - 6), index + 1).reduce((sum, item) => sum + item.activeCalories, 0)
      / Math.min(7, index + 1),
    ),
  }));
}

export function buildCardioCaloriePeriodSeries(days = [], {
  endDate,
  dayCount = 91,
  periodDays = 7,
} = {}) {
  const safePeriodDays = Math.max(1, Math.min(365, Math.round(Number(periodDays) || 7)));
  const requestedDays = Math.max(safePeriodDays, Math.round(Number(dayCount) || safePeriodDays));
  const periodCount = Math.max(1, Math.round(requestedDays / safePeriodDays));
  const daily = buildCardioCalorieChartSeries(days, {
    endDate,
    dayCount: periodCount * safePeriodDays,
  });

  return Array.from({ length: periodCount }, (_, index) => {
    const period = daily.slice(index * safePeriodDays, (index + 1) * safePeriodDays);
    const divisor = Math.max(1, period.length);
    return {
      date: period.at(-1)?.date || "",
      periodStart: period[0]?.date || "",
      periodEnd: period.at(-1)?.date || "",
      activeCalories: roundCalories(period.reduce((sum, day) => sum + day.activeCalories, 0) / divisor),
      cyclingCalories: roundCalories(period.reduce((sum, day) => sum + day.cyclingCalories, 0) / divisor),
      walkingCalories: roundCalories(period.reduce((sum, day) => sum + day.walkingCalories, 0) / divisor),
      activeDayCount: period.filter((day) => day.activeCalories > 0).length,
      movingAverage: 0,
    };
  });
}

export function summarizeCardioCalorieTrend(series = []) {
  const safeSeries = Array.isArray(series) ? series : [];
  const recent = safeSeries.slice(-7);
  const previous = safeSeries.slice(-14, -7);
  const latestMa7 = roundCalories(safeSeries.at(-1)?.movingAverage || 0);
  const previousMa7 = roundCalories(safeSeries.at(-8)?.movingAverage || 0);
  const delta = roundCalories(latestMa7 - previousMa7);
  const changePercent = previousMa7 ? delta / previousMa7 * 100 : latestMa7 > 0 ? 100 : 0;
  const threshold = Math.max(5, previousMa7 * .05);
  const direction = delta > threshold ? "up" : delta < -threshold ? "down" : "stable";
  const recentActiveDays = recent.filter((day) => day.activeCalories > 0).length;
  const previousActiveDays = previous.filter((day) => day.activeCalories > 0).length;
  const recentCycling = recent.reduce((sum, day) => sum + Math.max(0, Number(day.cyclingCalories) || 0), 0);
  const recentWalking = recent.reduce((sum, day) => sum + Math.max(0, Number(day.walkingCalories) || 0), 0);
  const recentTotal = recentCycling + recentWalking;
  return {
    latestMa7,
    previousMa7,
    delta,
    changePercent,
    direction,
    recentActiveDays,
    previousActiveDays,
    cyclingPercent: recentTotal ? recentCycling / recentTotal * 100 : 0,
    walkingPercent: recentTotal ? recentWalking / recentTotal * 100 : 0,
  };
}
