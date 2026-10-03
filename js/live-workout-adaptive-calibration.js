export const LIVE_WORKOUT_LEARNING_STORAGE_KEY = "liveWorkout.adaptiveCalibration.v1";
export const LIVE_WORKOUT_RESISTANCE_LEVEL_KEY = "liveWorkout.currentResistanceLevel.v1";

const DEFAULTS = Object.freeze({
  analysisWindowSeconds: 120,
  retainedHistorySeconds: 360,
  minimumSessionSeconds: 480,
  minimumSamples: 55,
  minimumRpm: 40,
  maximumRpm: 130,
  minimumDataCoverage: 0.5,
  minimumCadenceCoverage: 0.65,
  maximumRobustRpmStdDev: 6.5,
  maximumSteadyHrStdDev: 5.5,
  maximumSteadyHrSlopeBpmPerMinute: 3.5,
  maximumSteadyHrDifference: 4,
  maximumTransitionHrStdDev: 10,
  maximumTransitionHrSlopeBpmPerMinute: 18,
  evaluationIntervalSeconds: 30,
  acceptanceIntervalSeconds: 90,
  sampleIntervalMs: 800,
  maximumStoredSamples: 600,
});

function mean(values) {
  const valid = values.filter(Number.isFinite);
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
}

function standardDeviation(values) {
  const average = mean(values);
  if (average == null) return null;
  return Math.sqrt(mean(values.map((value) => (value - average) ** 2)) || 0);
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((left, right) => left - right);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function robustValues(values, minimum, maximum) {
  const valid = values.map(Number).filter((value) => Number.isFinite(value) && value >= minimum && value <= maximum);
  const center = median(valid);
  if (center == null) return { valid, inliers: [], median: null, mad: null };
  const mad = median(valid.map((value) => Math.abs(value - center))) || 0;
  const threshold = Math.max(8, mad * 4.45);
  return {
    valid,
    inliers: valid.filter((value) => Math.abs(value - center) <= threshold),
    median: center,
    mad,
  };
}

function slopePerMinute(points, valueKey) {
  if (points.length < 2) return null;
  const start = points[0].timestamp;
  const xs = points.map((point) => (point.timestamp - start) / 60_000);
  const ys = points.map((point) => Number(point[valueKey]));
  const meanX = mean(xs);
  const meanY = mean(ys);
  const denominator = xs.reduce((sum, x) => sum + (x - meanX) ** 2, 0);
  if (!denominator) return null;
  return xs.reduce((sum, x, index) => sum + (x - meanX) * (ys[index] - meanY), 0) / denominator;
}

function validLevel(value) {
  const level = Number(value);
  return Number.isInteger(level) && level >= 1 && level <= 8 ? level : null;
}

export function getWorkoutLearningPhase(sessionElapsedSeconds = 0) {
  const elapsed = Math.max(0, Number(sessionElapsedSeconds) || 0);
  if (elapsed < 20 * 60) return "early";
  if (elapsed < 40 * 60) return "middle";
  return "late";
}

export function analyseWorkoutLearningWindow(points = [], options = {}, timestamp = points.at(-1)?.timestamp) {
  const config = { ...DEFAULTS, ...options };
  const now = Number(timestamp);
  if (!Number.isFinite(now)) return { usable: false, reason: "no-data", context: "waiting" };
  const windowStart = now - config.analysisWindowSeconds * 1000;
  const windowPoints = points.filter((point) => point.timestamp >= windowStart && point.timestamp <= now);
  const durationSeconds = windowPoints.length > 1
    ? (windowPoints.at(-1).timestamp - windowPoints[0].timestamp) / 1000
    : 0;
  const dataCoverage = Math.min(1, windowPoints.length / Math.max(1, config.analysisWindowSeconds));
  if (durationSeconds < config.analysisWindowSeconds - 3 || windowPoints.length < config.minimumSamples || dataCoverage < config.minimumDataCoverage) {
    return { usable: false, reason: "collecting", context: "waiting", durationSeconds, dataCoverage };
  }

  const cadence = robustValues(windowPoints.map((point) => point.rpm), config.minimumRpm, config.maximumRpm);
  const cadenceCoverage = cadence.valid.length / Math.max(1, windowPoints.length);
  const cadenceInlierCoverage = cadence.inliers.length / Math.max(1, windowPoints.length);
  if (cadenceCoverage < config.minimumCadenceCoverage || cadenceInlierCoverage < config.minimumCadenceCoverage) {
    return { usable: false, reason: "cadence-gaps", context: "waiting", durationSeconds, dataCoverage, cadenceCoverage, cadenceInlierCoverage };
  }

  const recentHr = windowPoints.filter((point) => point.timestamp >= now - 60_000);
  const earlierHr = windowPoints.filter((point) => point.timestamp >= now - 120_000 && point.timestamp < now - 60_000);
  const finalHalfHr = recentHr.filter((point) => point.timestamp >= now - 30_000);
  const firstHalfHr = recentHr.filter((point) => point.timestamp < now - 30_000);
  const recentHrAverage = mean(recentHr.map((point) => point.heartRate));
  const earlierHrAverage = mean(earlierHr.map((point) => point.heartRate));
  const finalHrAverage = mean(finalHalfHr.map((point) => point.heartRate));
  const recentHrStdDev = standardDeviation(recentHr.map((point) => point.heartRate));
  const hrSlopeBpmPerMin = slopePerMinute(recentHr, "heartRate");
  const firstHalfAverage = mean(firstHalfHr.map((point) => point.heartRate));
  const finalHalfAverage = mean(finalHalfHr.map((point) => point.heartRate));
  const halfMinuteDifference = firstHalfAverage == null || finalHalfAverage == null
    ? Infinity
    : finalHalfAverage - firstHalfAverage;
  const minuteHrDifference = earlierHrAverage == null || recentHrAverage == null
    ? Infinity
    : recentHrAverage - earlierHrAverage;
  const hrDirection = (hrSlopeBpmPerMin ?? 0) * 0.65 + (Number.isFinite(minuteHrDifference) ? minuteHrDifference : 0) * 0.35;
  const steady = Math.abs(hrSlopeBpmPerMin ?? Infinity) <= config.maximumSteadyHrSlopeBpmPerMinute
    && Math.abs(halfMinuteDifference) <= config.maximumSteadyHrDifference
    && recentHrStdDev <= config.maximumSteadyHrStdDev;
  const context = steady ? "steady" : hrDirection >= 0 ? "rising" : "falling";
  if (!steady && (
    recentHrStdDev > config.maximumTransitionHrStdDev
    || Math.abs(hrSlopeBpmPerMin ?? Infinity) > config.maximumTransitionHrSlopeBpmPerMinute
  )) {
    return { usable: false, reason: "hr-chaotic", context, durationSeconds, dataCoverage, cadenceCoverage, hrSlopeBpmPerMin, hrStdDev: recentHrStdDev };
  }

  const transitionLagSeconds = context === "falling" ? 35 : 20;
  const cadencePoints = steady
    ? windowPoints.filter((point) => point.timestamp >= now - 60_000)
    : windowPoints.filter((point) => (
      point.timestamp >= now - 120_000
      && point.timestamp <= now - transitionLagSeconds * 1000
    ));
  const contextualCadence = robustValues(cadencePoints.map((point) => point.rpm), config.minimumRpm, config.maximumRpm);
  const rpmValues = contextualCadence.inliers.length ? contextualCadence.inliers : cadence.inliers;
  const rpmStdDev = standardDeviation(rpmValues);
  if (rpmStdDev > config.maximumRobustRpmStdDev) {
    return { usable: false, reason: "cadence-variable", context, durationSeconds, dataCoverage, cadenceCoverage, rpmStdDev };
  }

  const averageRpm = mean(rpmValues);
  const averageHr = steady ? recentHrAverage : finalHrAverage;
  const rpmRange = Math.max(...rpmValues) - Math.min(...rpmValues);
  const transientFraction = 1 - cadence.inliers.length / Math.max(1, windowPoints.length);
  const baseWeight = steady ? 0.62 : 0.18;
  const quality = Math.max(0.45, Math.min(1,
    dataCoverage * cadenceInlierCoverage * (1 - Math.min(0.45, rpmStdDev / 20)),
  ));
  return {
    usable: true,
    reason: "accepted",
    context,
    durationSeconds,
    dataCoverage,
    cadenceCoverage,
    cadenceInlierCoverage,
    transientFraction,
    averageRpm,
    averageHr,
    rpmStdDev,
    rpmRange,
    hrStdDev: recentHrStdDev,
    hrSlopeBpmPerMin,
    minuteHrDifference,
    halfMinuteDifference,
    lagSeconds: steady ? 0 : transitionLagSeconds,
    weight: baseWeight * quality,
  };
}

export function loadLiveWorkoutLearningSamples(storage = globalThis.localStorage) {
  try {
    const parsed = JSON.parse(storage?.getItem(LIVE_WORKOUT_LEARNING_STORAGE_KEY) || "[]");
    return Array.isArray(parsed)
      ? parsed.filter((sample) => sample?.id && validLevel(sample.level) && Number.isFinite(Number(sample.averageRpm)) && Number.isFinite(Number(sample.averageHr)))
      : [];
  } catch {
    return [];
  }
}

export function saveLiveWorkoutLearningSample(sample, storage = globalThis.localStorage, maximumStoredSamples = DEFAULTS.maximumStoredSamples) {
  const samples = loadLiveWorkoutLearningSamples(storage);
  const matchingIndex = samples.findIndex((item) => (
    item.sessionId
    && item.sessionId === sample.sessionId
    && Number(item.level) === Number(sample.level)
    && (item.context || "steady") === (sample.context || "steady")
    && (item.sessionPhase || "early") === (sample.sessionPhase || "early")
    && Math.abs(Number(item.averageRpm) - Number(sample.averageRpm)) <= 2
  ));
  if (matchingIndex >= 0) {
    const previous = samples.splice(matchingIndex, 1)[0];
    const observations = Math.max(1, Number(previous.observationCount) || 1);
    const merge = (key) => {
      const previousValue = Number(previous[key]);
      const nextValue = Number(sample[key]);
      if (!Number.isFinite(previousValue)) return Number.isFinite(nextValue) ? nextValue : null;
      if (!Number.isFinite(nextValue)) return previousValue;
      return (previousValue * observations + nextValue) / (observations + 1);
    };
    samples.unshift({
      ...previous,
      timestamp: sample.timestamp,
      durationSeconds: Number(previous.durationSeconds || 0) + Number(sample.durationSeconds || 0),
      averageRpm: merge("averageRpm"),
      averageHr: merge("averageHr"),
      rpmStdDev: merge("rpmStdDev"),
      rpmRange: merge("rpmRange"),
      hrStdDev: merge("hrStdDev"),
      hrSlopeBpmPerMin: merge("hrSlopeBpmPerMin"),
      minuteHrDifference: merge("minuteHrDifference"),
      weight: merge("weight"),
      observationCount: observations + 1,
    });
  } else {
    samples.unshift({ ...sample, observationCount: 1 });
  }
  const limited = samples.slice(0, maximumStoredSamples);
  storage?.setItem(LIVE_WORKOUT_LEARNING_STORAGE_KEY, JSON.stringify(limited));
  return limited;
}

export function clearLiveWorkoutLearningSamples(storage = globalThis.localStorage) {
  storage?.removeItem(LIVE_WORKOUT_LEARNING_STORAGE_KEY);
  return [];
}

export function learningSamplesAsCalibration(samples = []) {
  if (!samples.length) return null;
  return {
    id: "live-workout-adaptive-learning",
    status: "adaptive",
    kind: "adaptive-training",
    timestamp: Math.max(...samples.map((sample) => Number(sample.timestamp) || 0)),
    dataPoints: samples.map((sample) => ({
      level: sample.level,
      targetRpm: sample.averageRpm,
      averageRpm: sample.averageRpm,
      averageHr: sample.averageHr,
      hrStdDev: sample.hrStdDev,
      hrSlopeBpmPerMin: sample.hrSlopeBpmPerMin,
      steadyState: (sample.context || "steady") === "steady",
      complete: true,
      usable: true,
      source: "live-training",
      sourceSampleId: sample.id,
      observationCount: Math.max(1, Number(sample.observationCount) || 1),
      context: sample.context || "steady",
      sessionPhase: sample.sessionPhase || "early",
      weight: sample.weight ?? 0.45,
    })),
  };
}

export class LiveWorkoutLearningEngine {
  constructor(options = {}) {
    this.config = { ...DEFAULTS, ...options };
    this.onSample = typeof options.onSample === "function" ? options.onSample : () => {};
    this.currentLevel = null;
    this.points = [];
    this.lastPointAt = 0;
    this.lastEvaluationAt = 0;
    this.lastAcceptedAt = 0;
    this.latestAnalysis = { usable: false, reason: "collecting", context: "waiting" };
  }

  resetWindow() {
    this.points = [];
    this.lastPointAt = 0;
    this.lastEvaluationAt = 0;
    this.lastAcceptedAt = 0;
    this.latestAnalysis = { usable: false, reason: "collecting", context: "waiting" };
  }

  setLevel(value) {
    const level = validLevel(value);
    if (level == null) return this.currentLevel;
    if (level !== this.currentLevel) this.resetWindow();
    this.currentLevel = level;
    return level;
  }

  ingest({
    timestamp = Date.now(),
    sessionId = null,
    sessionElapsedSeconds = 0,
    level = this.currentLevel,
    rpm,
    heartRate,
    active = true,
    signalFresh = true,
  } = {}) {
    const safeLevel = this.setLevel(level);
    const rpmNumber = Number(rpm);
    const safeRpm = Number.isFinite(rpmNumber) && rpmNumber >= this.config.minimumRpm && rpmNumber <= this.config.maximumRpm
      ? rpmNumber
      : null;
    const safeHeartRate = Number(heartRate);
    if (!active || safeLevel == null) {
      if (!active) this.resetWindow();
      return null;
    }
    if (!signalFresh || !Number.isFinite(safeHeartRate) || safeHeartRate < 40 || safeHeartRate > 230) return null;
    if (this.lastPointAt && timestamp - this.lastPointAt < this.config.sampleIntervalMs) return null;

    this.points.push({ timestamp, rpm: safeRpm, heartRate: safeHeartRate });
    this.lastPointAt = timestamp;
    this.points = this.points.filter((point) => point.timestamp >= timestamp - this.config.retainedHistorySeconds * 1000);
    if (Number(sessionElapsedSeconds) < this.config.minimumSessionSeconds) return null;
    if (this.lastEvaluationAt && timestamp - this.lastEvaluationAt < this.config.evaluationIntervalSeconds * 1000) return null;
    this.lastEvaluationAt = timestamp;
    const analysis = analyseWorkoutLearningWindow(this.points, this.config, timestamp);
    this.latestAnalysis = analysis;
    if (!analysis.usable) return null;
    if (this.lastAcceptedAt && timestamp - this.lastAcceptedAt < this.config.acceptanceIntervalSeconds * 1000) return null;
    this.lastAcceptedAt = timestamp;
    const sample = {
      id: `live-learning-${timestamp}-${safeLevel}`,
      timestamp,
      sessionId,
      sessionElapsedSeconds: Math.round(Number(sessionElapsedSeconds) || 0),
      sessionPhase: getWorkoutLearningPhase(sessionElapsedSeconds),
      level: safeLevel,
      durationSeconds: Math.round(analysis.durationSeconds),
      averageRpm: analysis.averageRpm,
      averageHr: analysis.averageHr,
      rpmStdDev: analysis.rpmStdDev,
      rpmRange: analysis.rpmRange,
      hrStdDev: analysis.hrStdDev,
      hrSlopeBpmPerMin: analysis.hrSlopeBpmPerMin,
      minuteHrDifference: analysis.minuteHrDifference,
      dataCoverage: analysis.dataCoverage,
      cadenceCoverage: analysis.cadenceCoverage,
      transientFraction: analysis.transientFraction,
      lagSeconds: analysis.lagSeconds,
      context: analysis.context,
      weight: analysis.weight,
      source: "live-training-context-v2",
    };
    this.onSample(sample);
    return sample;
  }

  snapshot() {
    const durationSeconds = this.points.length > 1
      ? (this.points.at(-1).timestamp - this.points[0].timestamp) / 1000
      : 0;
    return {
      level: this.currentLevel,
      durationSeconds,
      pointCount: this.points.length,
      analysis: { ...this.latestAnalysis },
    };
  }
}
