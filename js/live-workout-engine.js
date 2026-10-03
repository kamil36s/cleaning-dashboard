export const HR_ZONE_CONFIG = Object.freeze([
  { key: "light", id: "Z1", label: "Regeneracja", from: .5, to: .6, color: "#3b82f6", load: 1 },
  { key: "intensive", id: "Z2", label: "Baza tlenowa", from: .6, to: .7, color: "#10b981", load: 2 },
  { key: "aerobic", id: "Z3", label: "Tempo", from: .7, to: .8, color: "#f59e0b", load: 3 },
  { key: "anaerobic", id: "Z4", label: "Próg / anaerobowa", from: .8, to: .9, color: "#f97316", load: 4 },
  { key: "vo2max", id: "Z5", label: "VO₂ Max", from: .9, to: 1.01, color: "#ef4444", load: 5 },
]);

const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;

export const DEFAULT_INDOOR_CYCLING_CALIBRATION = 0.71;

export function resolveMaxHr({ ageYears = 30, maxHr = null } = {}) {
  const configured = finite(maxHr, 0);
  if (configured >= 100 && configured <= 240) return Math.round(configured);
  return Math.max(100, Math.min(240, Math.round(220 - finite(ageYears, 30))));
}

export function calculateHeartRateZones(profile = {}) {
  const maxHr = resolveMaxHr(profile);
  return HR_ZONE_CONFIG.map((zone, index) => ({
    ...zone,
    min: Math.ceil(maxHr * zone.from),
    max: index === HR_ZONE_CONFIG.length - 1 ? maxHr : Math.ceil(maxHr * zone.to) - 1,
  }));
}

export function calculateCaloriesPerSecond({
  heartRate,
  weightKg,
  ageYears,
  sex = "male",
  maxHr,
  bmrKcal = 1800,
} = {}) {
  const hr = finite(heartRate, 0);
  const weight = Math.max(30, finite(weightKg, 75));
  const age = Math.max(14, finite(ageYears, 30));
  const resolvedMaxHr = resolveMaxHr({ ageYears: age, maxHr });
  const restingPerMinute = Math.max(0, finite(bmrKcal, 1800)) / 1440;
  if (hr < resolvedMaxHr * .5) return restingPerMinute / 60;
  const perMinute = sex === "female"
    ? (-20.4022 + .4472 * hr - .1263 * weight + .074 * age) / 4.184
    : (-55.0969 + .6309 * hr + .1988 * weight + .2017 * age) / 4.184;
  return Math.max(restingPerMinute, perMinute, 0) / 60;
}

export function calculateIndoorCyclingCaloriesPerSecond(profile = {}, calibrationFactor = DEFAULT_INDOOR_CYCLING_CALIBRATION) {
  const factor = Math.max(.45, Math.min(.95, finite(calibrationFactor, DEFAULT_INDOOR_CYCLING_CALIBRATION)));
  return calculateCaloriesPerSecond(profile) * factor;
}

export function deriveIndoorCyclingCalibration(sessions = [], profile = {}) {
  const samples = sessions
    .filter((session) => (
      session?.status === "finished"
      && /xiaomi|mi fitness/i.test(String(session?.source || ""))
      && finite(session?.active_calories, 0) > 0
      && finite(session?.duration_seconds, 0) >= 5 * 60
      && finite(session?.avg_hr, 0) >= 50
    ))
    .map((session) => {
      const durationSeconds = finite(session.duration_seconds, 0);
      const keytelCalories = calculateCaloriesPerSecond({ ...profile, heartRate: finite(session.avg_hr, 0) }) * durationSeconds;
      return {
        actualCalories: finite(session.active_calories, 0),
        keytelCalories,
      };
    })
    .filter((sample) => sample.keytelCalories > 0);
  if (samples.length < 3) {
    return { factor: DEFAULT_INDOOR_CYCLING_CALIBRATION, sampleCount: samples.length, calibrated: false, meanAbsoluteError: null };
  }
  const numerator = samples.reduce((sum, sample) => sum + sample.keytelCalories * sample.actualCalories, 0);
  const denominator = samples.reduce((sum, sample) => sum + sample.keytelCalories ** 2, 0);
  const factor = Math.max(.45, Math.min(.95, denominator ? numerator / denominator : DEFAULT_INDOOR_CYCLING_CALIBRATION));
  const meanAbsoluteError = samples.reduce((sum, sample) => (
    sum + Math.abs(sample.actualCalories - sample.keytelCalories * factor)
  ), 0) / samples.length;
  return {
    factor,
    sampleCount: samples.length,
    calibrated: true,
    meanAbsoluteError,
  };
}

export function estimateCaloriesFromZones(zoneSeconds = {}, profile = {}) {
  const zones = calculateHeartRateZones(profile);
  return zones.reduce((total, zone) => {
    const seconds = Math.max(0, finite(zoneSeconds[zone.key], 0));
    if (!seconds) return total;
    const representativeHeartRate = Math.round((zone.min + zone.max) / 2);
    return total + calculateCaloriesPerSecond({
      ...profile,
      heartRate: representativeHeartRate,
    }) * seconds;
  }, 0);
}

export function calculateTrimp(zoneSeconds = {}) {
  return HR_ZONE_CONFIG.reduce((total, zone) => (
    total + Math.max(0, finite(zoneSeconds[zone.key], 0)) / 60 * zone.load
  ), 0);
}

export function calculateZoneFulfillment(zoneSeconds = {}, targetMinutes = {}) {
  const details = Object.fromEntries(HR_ZONE_CONFIG.map((zone) => {
    const actualSeconds = Math.max(0, finite(zoneSeconds[zone.key], 0));
    const targetSeconds = Math.max(0, finite(targetMinutes[zone.key], 0) * 60);
    return [zone.key, {
      actualSeconds,
      targetSeconds,
      creditedSeconds: Math.min(actualSeconds, targetSeconds),
      deficitSeconds: Math.max(0, targetSeconds - actualSeconds),
      excessSeconds: Math.max(0, actualSeconds - targetSeconds),
    }];
  }));
  const values = Object.values(details);
  const plannedSeconds = values.reduce((sum, zone) => sum + zone.targetSeconds, 0);
  const actualSeconds = values.reduce((sum, zone) => sum + zone.actualSeconds, 0);
  const creditedSeconds = values.reduce((sum, zone) => sum + zone.creditedSeconds, 0);
  const excessSeconds = values.reduce((sum, zone) => sum + zone.excessSeconds, 0);
  return {
    zones: details,
    plannedSeconds,
    actualSeconds,
    creditedSeconds,
    deficitSeconds: Math.max(0, plannedSeconds - creditedSeconds),
    excessSeconds,
    progress: plannedSeconds ? Math.min(100, creditedSeconds / plannedSeconds * 100) : 0,
  };
}

export function getTargetZoneGuide(heartRate, targetZoneKey, profile = {}) {
  const zone = calculateHeartRateZones(profile).find((item) => item.key === targetZoneKey);
  const hr = finite(heartRate, NaN);
  if (!zone || !Number.isFinite(hr)) return { state: "waiting", delta: 0, label: "CZEKAM NA TĘTNO" };
  if (hr < zone.min) {
    const delta = Math.ceil(zone.min - hr);
    return { state: "faster", delta, label: `▲ PRZYSPIESZ (+${delta} BPM)` };
  }
  if (hr > zone.max) {
    const delta = Math.ceil(hr - zone.max);
    return { state: "slower", delta, label: `▼ ZWOLNIJ (-${delta} BPM)` };
  }
  return { state: "target", delta: 0, label: "✓ W STREFIE CELU" };
}

export function calculateSegmentLayout(intervals = []) {
  const total = intervals.reduce((sum, interval) => sum + Math.max(0, finite(interval.duration_minutes)), 0);
  return intervals.map((interval, index) => ({
    ...interval,
    segment: index === 0 ? "warmup" : index === intervals.length - 1 ? "cooldown" : "work",
    percent: total ? Math.max(0, finite(interval.duration_minutes)) / total * 100 : 0,
  }));
}
