export const AI_USAGE_PLANS = Object.freeze([
  { id: "plus", name: "ChatGPT Plus", multiplier: 1, baseMonthlyUsd: 20 },
  { id: "pro5", name: "ChatGPT Pro 5X", multiplier: 5, baseMonthlyUsd: 100 },
  { id: "pro20", name: "ChatGPT Pro 20X", multiplier: 20, baseMonthlyUsd: 200 },
]);

const finite = (value) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

function localDayStart(timestamp) {
  const date = new Date(timestamp);
  date.setHours(0, 0, 0, 0);
  return date;
}

export function estimateExhaustion({
  remaining,
  burnPercent,
  activeSeconds,
  resetAt,
  sampleCount = 0,
  now = Date.now(),
} = {}) {
  const remainingQuota = finite(remaining);
  const burn = finite(burnPercent);
  const active = finite(activeSeconds);
  if (remainingQuota == null || burn == null || burn <= 0 || active == null || active <= 0) {
    return { status: "not_enough_data", confidence: "not_enough_data" };
  }

  const activeHours = active / 3600;
  const burnPerActiveHour = burn / activeHours;
  if (!Number.isFinite(burnPerActiveHour) || burnPerActiveHour <= 0) {
    return { status: "not_enough_data", confidence: "not_enough_data" };
  }

  const activeHoursLeft = Math.max(0, remainingQuota / burnPerActiveHour);
  const resetTimestamp = Date.parse(resetAt || "");
  const resetHours = Number.isFinite(resetTimestamp) ? Math.max(0, (resetTimestamp - now) / 3_600_000) : null;
  let status = "not_enough_data";
  if (resetHours != null) {
    if (activeHoursLeft <= resetHours * 0.8) status = "likely_to_hit_limit";
    else if (activeHoursLeft <= resetHours) status = "at_risk";
    else status = "safe_until_reset";
  }

  const confidence = active >= 7200 && sampleCount >= 4
    ? "high"
    : active >= 1800 && sampleCount >= 2
      ? "medium"
      : "low";
  return { status, confidence, activeHoursLeft, burnPerActiveHour, resetHours };
}

export function sessionRate(item, sessions, windowKey, { since = null } = {}) {
  const burnKey = windowKey === "fiveHour" ? "five_hour_burn" : "weekly_burn";
  const limit = windowKey === "fiveHour" ? 5 : 12;
  const sinceTimestamp = Date.parse(since || "");
  const relevant = (sessions || [])
    .filter((session) => session.provider === item?.provider && session.group === item?.group)
    .filter((session) => !Number.isFinite(sinceTimestamp) || Date.parse(session.session_start || "") >= sinceTimestamp)
    .filter((session) => finite(session[burnKey]) > 0 && finite(session.duration_seconds) > 0)
    .slice(0, limit);
  return {
    burnPercent: relevant.reduce((sum, session) => sum + finite(session[burnKey]), 0),
    activeSeconds: relevant.reduce((sum, session) => sum + finite(session.duration_seconds), 0),
    sampleCount: relevant.length,
  };
}

function planIdForName(planName) {
  const normalized = String(planName || "").toLowerCase();
  if (normalized.includes("20x")) return "pro20";
  if (normalized.includes("5x")) return "pro5";
  return "plus";
}

function fitForProjectedUsage(value) {
  if (!Number.isFinite(value)) return { risk: "UNKNOWN", fit: "Not enough data" };
  if (value > 100) return { risk: "HIGH", fit: "Too restrictive" };
  if (value >= 70) return { risk: "MEDIUM", fit: "Tight" };
  if (value >= 30) return { risk: "LOW", fit: "Likely sufficient" };
  return { risk: "VERY LOW", fit: "High headroom" };
}

export function simulatePlans({
  currentBurnPerActiveHour,
  currentPlanName = "ChatGPT Plus",
  vatRate = 0.23,
  usdPlnRate = 1,
  projectedWeeklyUsage = null,
  averageActiveHoursPerDay = null,
} = {}) {
  const currentRate = finite(currentBurnPerActiveHour);
  const currentPlanId = planIdForName(currentPlanName);
  const currentPlan = AI_USAGE_PLANS.find((plan) => plan.id === currentPlanId) || AI_USAGE_PLANS[0];
  const currentGross = currentPlan.baseMonthlyUsd * (1 + finite(vatRate));

  return AI_USAGE_PLANS.map((plan) => {
    const equivalentBurnPerHour = currentRate != null && currentRate > 0
      ? currentRate * currentPlan.multiplier / plan.multiplier
      : null;
    const activeHoursCapacity = equivalentBurnPerHour ? 100 / equivalentBurnPerHour : null;
    const estimatedDays = activeHoursCapacity && finite(averageActiveHoursPerDay) > 0
      ? activeHoursCapacity / finite(averageActiveHoursPerDay)
      : null;
    const scaledWeeklyUsage = finite(projectedWeeklyUsage) != null
      ? finite(projectedWeeklyUsage) * currentPlan.multiplier / plan.multiplier
      : null;
    const grossMonthlyUsd = plan.baseMonthlyUsd * (1 + finite(vatRate));
    return {
      ...plan,
      current: plan.id === currentPlanId,
      grossMonthlyUsd,
      grossMonthlyPln: grossMonthlyUsd * finite(usdPlnRate),
      grossDeltaUsd: grossMonthlyUsd - currentGross,
      grossDeltaPln: (grossMonthlyUsd - currentGross) * finite(usdPlnRate),
      equivalentBurnPerHour,
      activeHoursCapacity,
      estimatedDays,
      projectedWeeklyUsage: scaledWeeklyUsage,
      ...fitForProjectedUsage(scaledWeeklyUsage),
    };
  });
}

export function aggregateBurnHistory(history, {
  provider,
  group,
  range = "today",
  now = Date.now(),
} = {}) {
  const end = now;
  let start;
  let buckets;
  if (range === "7d") {
    const today = localDayStart(now);
    start = new Date(today);
    start.setDate(start.getDate() - 6);
    buckets = Array.from({ length: 7 }, (_, index) => {
      const bucketStart = new Date(start);
      bucketStart.setDate(bucketStart.getDate() + index);
      const bucketEnd = new Date(bucketStart);
      bucketEnd.setDate(bucketEnd.getDate() + 1);
      return {
        start: bucketStart.getTime(),
        end: bucketEnd.getTime(),
        label: bucketStart.toLocaleDateString("en-GB", { weekday: "short" }),
        fiveHour: 0,
        weekly: 0,
      };
    });
  } else {
    const today = localDayStart(now);
    start = today;
    buckets = Array.from({ length: 24 }, (_, hour) => ({
      start: new Date(today.getFullYear(), today.getMonth(), today.getDate(), hour).getTime(),
      end: new Date(today.getFullYear(), today.getMonth(), today.getDate(), hour + 1).getTime(),
      label: String(hour).padStart(2, "0"),
      fiveHour: 0,
      weekly: 0,
    }));
  }

  (history || []).forEach((item) => {
    if (item.provider !== provider || item.group !== group) return;
    const timestamp = Date.parse(item.checkedAt || item.updatedAt || "");
    if (!Number.isFinite(timestamp) || timestamp < start.getTime() || timestamp > end) return;
    const bucket = buckets.find((candidate) => timestamp >= candidate.start && timestamp < candidate.end);
    if (!bucket) return;
    bucket.fiveHour += Math.max(0, finite(item.fiveHourBurn) || 0);
    bucket.weekly += Math.max(0, finite(item.weeklyBurn) || 0);
  });

  return buckets.map((bucket) => ({
    ...bucket,
    fiveHour: Math.round(bucket.fiveHour * 10) / 10,
    weekly: Math.round(bucket.weekly * 10) / 10,
  }));
}

export function buildQuotaSeries(history, {
  provider,
  group,
  windowKey,
  rangeHours = 24,
  now = Date.now(),
  planChanges = [],
} = {}) {
  const start = now - rangeHours * 3_600_000;
  const points = (history || [])
    .filter((item) => item.provider === provider && item.group === group)
    .map((item) => ({
      timestamp: Date.parse(item.checkedAt || item.updatedAt || ""),
      remaining: finite(item?.[windowKey]?.remaining),
      resetAt: item?.[windowKey]?.resetAt || null,
      status: item.status,
    }))
    .filter((item) => Number.isFinite(item.timestamp) && item.timestamp >= start && item.timestamp <= now)
    .filter((item) => item.remaining != null && ["connected", "stale"].includes(String(item.status || "").toLowerCase()))
    .sort((left, right) => left.timestamp - right.timestamp);

  const segments = [];
  const resets = [];
  const changes = (planChanges || [])
    .filter((change) => change?.provider === provider && change?.group === group)
    .map((change) => ({ ...change, timestamp: Date.parse(change.activatedAt || "") }))
    .filter((change) => Number.isFinite(change.timestamp))
    .sort((left, right) => left.timestamp - right.timestamp);
  let segment = [];
  points.forEach((point, index) => {
    const previous = points[index - 1];
    const crossedPlanChange = changes.some((change) => (
      previous
      && previous.timestamp < change.timestamp
      && point.timestamp >= change.timestamp
    ));
    const resetAtChanged = Boolean(
      previous?.resetAt
      && point.resetAt
      && previous.resetAt !== point.resetAt,
    );
    const reset = Boolean(previous && !crossedPlanChange && (
      point.remaining - previous.remaining >= 20
      || (point.remaining === 100 && previous.remaining < 100 && resetAtChanged)
    ));
    if (reset || crossedPlanChange) {
      if (segment.length) segments.push(segment);
      segment = [];
      if (reset) resets.push(point);
    }
    point.usedSincePrevious = previous && !reset && !crossedPlanChange
      ? Math.max(0, previous.remaining - point.remaining)
      : 0;
    segment.push(point);
  });
  if (segment.length) segments.push(segment);
  return { start, end: now, points, segments, resets, planChanges: changes };
}
