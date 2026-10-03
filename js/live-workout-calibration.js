export const CALIBRATION_STORAGE_KEY = "liveWorkout.calibrations.v1";

export const DEFAULT_CALIBRATION_CONFIG = Object.freeze({
  baselineSeconds: 60,
  warmupSeconds: 180,
  stepSeconds: 180,
  cooldownSeconds: 120,
  targetRpm: 80,
  toleranceRpm: 4,
});

const ZONE_NAMES = {
  Z1: "Active Recovery",
  Z2: "LISS / Aerobic",
  Z3: "Tempo",
  Z4: "Threshold",
  Z5: "VO2max",
};

function mean(values) {
  const valid = values.filter(Number.isFinite);
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
}

function weightedMean(items, valueSelector, weightSelector = (item) => item.weight) {
  const valid = items
    .map((item) => ({ value: Number(valueSelector(item)), weight: Math.max(0.01, Number(weightSelector(item)) || 1) }))
    .filter((item) => Number.isFinite(item.value));
  const totalWeight = valid.reduce((sum, item) => sum + item.weight, 0);
  return totalWeight ? valid.reduce((sum, item) => sum + item.value * item.weight, 0) / totalWeight : null;
}

function standardDeviation(values) {
  const average = mean(values);
  if (average == null) return null;
  const variance = mean(values.map((value) => (value - average) ** 2));
  return variance == null ? null : Math.sqrt(variance);
}

function slopePerMinute(samples) {
  if (samples.length < 2) return null;
  const start = samples[0].timestamp;
  const points = samples.map((sample) => ({ x: (sample.timestamp - start) / 60_000, y: sample.heartRate }));
  const meanX = mean(points.map((point) => point.x));
  const meanY = mean(points.map((point) => point.y));
  const denominator = points.reduce((sum, point) => sum + (point.x - meanX) ** 2, 0);
  if (!denominator) return null;
  return points.reduce((sum, point) => sum + (point.x - meanX) * (point.y - meanY), 0) / denominator;
}

function closestHeartRate(samples, elapsedSeconds) {
  if (!samples.length) return null;
  const closest = samples.reduce((best, sample) => (
    Math.abs(sample.phaseElapsed - elapsedSeconds) < Math.abs(best.phaseElapsed - elapsedSeconds) ? sample : best
  ));
  return Math.abs(closest.phaseElapsed - elapsedSeconds) <= 10 ? closest.heartRate : null;
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function createCalibrationProtocol(options = {}) {
  const config = { ...DEFAULT_CALIBRATION_CONFIG, ...options };
  const steps = Array.from({ length: 8 }, (_, index) => ({
    id: `level-${index + 1}`,
    kind: "step",
    name: `Poziom ${index + 1}`,
    level: index + 1,
    durationSeconds: config.stepSeconds,
    targetRpm: config.targetRpm,
    toleranceRpm: config.toleranceRpm,
  }));
  return [
    { id: "baseline", kind: "baseline", name: "Baseline i diagnostyka", level: 0, durationSeconds: config.baselineSeconds, targetRpm: 0, toleranceRpm: 5 },
    { id: "warmup", kind: "warmup", name: "Rozgrzewka", level: 1, durationSeconds: config.warmupSeconds, targetRpm: 75, toleranceRpm: 5 },
    ...steps,
    { id: "cooldown", kind: "cooldown", name: "Schłodzenie i HRR", level: 1, durationSeconds: config.cooldownSeconds, targetRpm: 70, toleranceRpm: 10 },
  ];
}

export class CalibrationEngine {
  constructor(options = {}) {
    const {
      onEvent,
      resumeCompletedLevels = [],
      resumeDataPoints = [],
      resumeSourceCalibrationId = null,
      ...configOptions
    } = options;
    this.config = { ...DEFAULT_CALIBRATION_CONFIG, ...configOptions };
    this.protocol = createCalibrationProtocol(this.config);
    this.onEvent = typeof onEvent === "function" ? onEvent : () => {};
    this.resumeCompletedLevels = new Set(
      (Array.isArray(resumeCompletedLevels) ? resumeCompletedLevels : [])
        .map(Number)
        .filter((level) => Number.isInteger(level) && level >= 1 && level <= 8),
    );
    this.resumeDataPoints = Array.isArray(resumeDataPoints)
      ? resumeDataPoints.map((point) => ({ ...point }))
      : [];
    this.resumeSourceCalibrationId = resumeSourceCalibrationId;
    this.reset();
  }

  reset() {
    this.status = "idle";
    this.phaseIndex = 0;
    this.phaseElapsed = 0;
    this.actualElapsed = 0;
    this.samples = [];
    this.phaseResults = [];
    this.pauseReason = null;
    this.blockedReason = null;
    this.signals = { hrAvailable: false, cadenceAvailable: false, heartRate: null, cadenceRpm: null };
    this.lastSampleAt = 0;
    this.countdownAnnouncedFor = null;
    this.result = null;
    this.onEvent({ type: "reset", snapshot: this.snapshot() });
    return this.snapshot();
  }

  currentPhase() {
    return this.protocol[this.phaseIndex] || null;
  }

  setSignals(signals = {}) {
    this.signals = { ...this.signals, ...signals };
    const missing = this.missingSignals();
    if (this.status === "running" && missing.length) {
      this.status = "paused";
      this.pauseReason = "signal";
      this.onEvent({ type: "signal-lost", missing, snapshot: this.snapshot() });
    }
    return missing;
  }

  missingSignals() {
    const missing = [];
    if (!this.signals.hrAvailable) missing.push("HR");
    if (!this.signals.cadenceAvailable) missing.push("CADENCE");
    return missing;
  }

  start(signals = this.signals) {
    if (!["idle", "completed", "partial"].includes(this.status)) return this.snapshot();
    if (this.status !== "idle") this.reset();
    this.setSignals(signals);
    const missing = this.missingSignals();
    this.status = missing.length ? "paused" : "running";
    this.pauseReason = missing.length ? "signal" : null;
    this.onEvent({ type: "started", phase: this.currentPhase(), missing, snapshot: this.snapshot() });
    if (missing.length) this.onEvent({ type: "signal-lost", missing, snapshot: this.snapshot() });
    return this.snapshot();
  }

  pause(reason = "manual") {
    if (this.status !== "running") return this.snapshot();
    this.status = "paused";
    this.pauseReason = reason;
    this.onEvent({ type: "paused", reason, snapshot: this.snapshot() });
    return this.snapshot();
  }

  resume(signals = this.signals, { restartCurrentPhase = true } = {}) {
    if (this.status !== "paused") return this.snapshot();
    this.setSignals(signals);
    const missing = this.missingSignals();
    if (missing.length) {
      this.pauseReason = "signal";
      this.onEvent({ type: "signal-lost", missing, snapshot: this.snapshot() });
      return this.snapshot();
    }
    const phase = this.currentPhase();
    if (restartCurrentPhase && phase && this.phaseElapsed > 0) {
      this.samples = this.samples.filter((sample) => sample.phaseId !== phase.id);
      this.phaseResults = this.phaseResults.filter((result) => result.phaseId !== phase.id);
      this.phaseElapsed = 0;
      this.blockedReason = null;
      this.lastSampleAt = 0;
      this.countdownAnnouncedFor = null;
      this.onEvent({ type: "phase-repeated", reason: "resume", phase, snapshot: this.snapshot() });
    }
    this.status = "running";
    this.pauseReason = null;
    this.onEvent({ type: "resumed", snapshot: this.snapshot() });
    return this.snapshot();
  }

  tick(deltaSeconds, signals = this.signals, timestamp = Date.now()) {
    this.setSignals(signals);
    if (this.status !== "running") return this.snapshot();
    const phase = this.currentPhase();
    const delta = clamp(Number(deltaSeconds) || 0, 0, 1);
    const stationaryBlocked = phase?.kind === "baseline" && Number(this.signals.cadenceRpm) > 5;
    this.blockedReason = stationaryBlocked ? "stop-pedaling" : null;
    if (stationaryBlocked) return this.snapshot();

    this.phaseElapsed += delta;
    this.actualElapsed += delta;
    if (timestamp - this.lastSampleAt >= 800) {
      const heartRate = Number(this.signals.heartRate);
      const cadenceRpm = Number(this.signals.cadenceRpm);
      if (Number.isFinite(heartRate) && Number.isFinite(cadenceRpm)) {
        this.samples.push({
          timestamp,
          phaseId: phase.id,
          phaseElapsed: this.phaseElapsed,
          heartRate,
          cadenceRpm,
          level: phase.level,
        });
        this.lastSampleAt = timestamp;
      }
    }

    const remaining = Math.max(0, phase.durationSeconds - this.phaseElapsed);
    if (remaining <= 10 && this.countdownAnnouncedFor !== phase.id) {
      this.countdownAnnouncedFor = phase.id;
      this.onEvent({ type: "countdown", seconds: 10, phase, nextPhase: this.protocol[this.phaseIndex + 1] || null, snapshot: this.snapshot() });
    }
    if (this.phaseElapsed >= phase.durationSeconds) this.advancePhase();
    return this.snapshot();
  }

  skipStep() {
    if (!["running", "paused"].includes(this.status)) return this.snapshot();
    this.finalizeCurrentPhase({ skipped: true });
    this.moveToNextPhase("skipped");
    return this.snapshot();
  }

  repeatStep() {
    if (!["running", "paused"].includes(this.status)) return this.snapshot();
    const phase = this.currentPhase();
    this.samples = this.samples.filter((sample) => sample.phaseId !== phase.id);
    this.phaseResults = this.phaseResults.filter((result) => result.phaseId !== phase.id);
    this.phaseElapsed = 0;
    this.blockedReason = null;
    this.lastSampleAt = 0;
    this.countdownAnnouncedFor = null;
    this.onEvent({ type: "phase-repeated", phase, snapshot: this.snapshot() });
    return this.snapshot();
  }

  advancePhase() {
    this.finalizeCurrentPhase();
    this.moveToNextPhase("completed");
  }

  moveToNextPhase(reason) {
    const previousPhase = this.currentPhase();
    if (this.phaseIndex >= this.protocol.length - 1) {
      this.finish("completed");
      return;
    }
    this.phaseIndex += 1;
    while (
      this.currentPhase()?.kind === "step"
      && this.resumeCompletedLevels.has(this.currentPhase().level)
    ) {
      const skippedPhase = this.currentPhase();
      this.onEvent({ type: "phase-skipped-existing", phase: skippedPhase, snapshot: this.snapshot() });
      this.phaseIndex += 1;
    }
    this.phaseElapsed = 0;
    this.blockedReason = null;
    this.lastSampleAt = 0;
    this.countdownAnnouncedFor = null;
    this.onEvent({ type: "phase-changed", reason, previousPhase, phase: this.currentPhase(), snapshot: this.snapshot() });
  }

  stopPartial() {
    if (!["running", "paused"].includes(this.status)) return this.result;
    this.finalizeCurrentPhase({ partial: true });
    return this.finish("partial");
  }

  finalizeCurrentPhase({ skipped = false, partial = false } = {}) {
    const phase = this.currentPhase();
    if (!phase || this.phaseResults.some((result) => result.phaseId === phase.id)) return;
    const samples = this.samples.filter((sample) => sample.phaseId === phase.id);
    const result = {
      phaseId: phase.id,
      kind: phase.kind,
      level: phase.level,
      targetRpm: phase.targetRpm,
      elapsedSeconds: this.phaseElapsed,
      skipped,
      partial,
      sampleCount: samples.length,
      averageHr: mean(samples.map((sample) => sample.heartRate)),
      averageCadence: mean(samples.map((sample) => sample.cadenceRpm)),
    };

    if (phase.kind === "step") {
      const steadyStart = Math.max(0, this.phaseElapsed - 60);
      const stabilityStart = Math.max(0, this.phaseElapsed - 45);
      const steady = samples.filter((sample) => sample.phaseElapsed >= steadyStart);
      const stability = samples.filter((sample) => sample.phaseElapsed >= stabilityStart);
      result.steadyHr = mean(steady.map((sample) => sample.heartRate));
      result.steadyCadence = mean(steady.map((sample) => sample.cadenceRpm));
      result.hrStdDev = standardDeviation(stability.map((sample) => sample.heartRate));
      result.hrSlopeBpmPerMin = slopePerMinute(stability);
      result.cadenceInBandPercent = steady.length
        ? steady.filter((sample) => Math.abs(sample.cadenceRpm - phase.targetRpm) <= phase.toleranceRpm).length / steady.length * 100
        : 0;
      const warnings = [];
      if (result.hrStdDev != null && result.hrStdDev > 5) warnings.push("high-hr-variability");
      if (result.hrSlopeBpmPerMin != null && result.hrSlopeBpmPerMin > 3) warnings.push("hr-still-rising");
      if (result.cadenceInBandPercent < 70) warnings.push("cadence-out-of-band");
      if (steady.length < 20) warnings.push("insufficient-steady-data");
      result.warnings = warnings;
      result.steadyState = warnings.length === 0;
    }
    this.phaseResults.push(result);
  }

  finish(status) {
    const peakHr = Math.max(0, ...this.samples.filter((sample) => sample.phaseId !== "cooldown").map((sample) => sample.heartRate));
    const cooldownSamples = this.samples.filter((sample) => sample.phaseId === "cooldown");
    const hrAt60 = closestHeartRate(cooldownSamples, 60);
    const hrAt120 = closestHeartRate(cooldownSamples, 120);
    const baseline = this.phaseResults.find((result) => result.kind === "baseline");
    const currentDataPoints = this.phaseResults
      .filter((result) => result.kind === "step" && !result.skipped && Number.isFinite(result.steadyHr))
      .map((result) => ({
        complete: !result.partial
          && !result.skipped
          && result.elapsedSeconds >= (this.protocol.find((phase) => phase.id === result.phaseId)?.durationSeconds || Infinity),
        level: result.level,
        targetRpm: result.targetRpm,
        averageRpm: result.steadyCadence,
        averageHr: result.steadyHr,
        hrStdDev: result.hrStdDev,
        hrSlopeBpmPerMin: result.hrSlopeBpmPerMin,
        cadenceInBandPercent: result.cadenceInBandPercent,
        steadyState: result.steadyState,
        warnings: result.warnings,
        partial: result.partial,
        usable: !result.partial && !result.skipped && !(result.warnings || []).includes("insufficient-steady-data"),
      }));
    const dataPointsByLevel = new Map(this.resumeDataPoints.map((point) => [Number(point.level), { ...point }]));
    currentDataPoints.forEach((point) => dataPointsByLevel.set(Number(point.level), point));
    const dataPoints = [...dataPointsByLevel.values()].sort((left, right) => Number(left.level) - Number(right.level));
    this.status = status;
    this.pauseReason = null;
    this.result = {
      version: 1,
      id: `calibration-${Date.now()}`,
      timestamp: Date.now(),
      status,
      replacesCalibrationId: this.resumeSourceCalibrationId || null,
      config: { ...this.config },
      restingHr: baseline?.averageHr ?? null,
      peakHr: peakHr || null,
      hrr: {
        hrAt60,
        hrAt120,
        drop60: peakHr && hrAt60 != null ? peakHr - hrAt60 : null,
        drop120: peakHr && hrAt120 != null ? peakHr - hrAt120 : null,
      },
      dataPoints,
      phaseResults: this.phaseResults.map((result) => ({ ...result })),
      durationSeconds: this.actualElapsed,
    };
    this.onEvent({ type: "finished", status, result: this.result, snapshot: this.snapshot() });
    return this.result;
  }

  snapshot(extra = {}) {
    const phase = this.currentPhase();
    const phaseRemaining = phase ? Math.max(0, phase.durationSeconds - this.phaseElapsed) : 0;
    const futureRemaining = this.protocol.slice(this.phaseIndex + 1)
      .filter((item) => item.kind !== "step" || !this.resumeCompletedLevels.has(item.level))
      .reduce((sum, item) => sum + item.durationSeconds, 0);
    return {
      status: this.status,
      phase,
      phaseIndex: this.phaseIndex,
      phaseNumber: this.phaseIndex,
      phaseCount: this.protocol.length - 1,
      phaseElapsed: this.phaseElapsed,
      phaseRemaining,
      totalRemaining: phaseRemaining + futureRemaining,
      actualElapsed: this.actualElapsed,
      pauseReason: this.pauseReason,
      blockedReason: this.blockedReason,
      signals: { ...this.signals },
      results: this.phaseResults.map((result) => ({ ...result })),
      result: this.result,
      ...extra,
    };
  }
}

export function loadCalibrations(storage = globalThis.localStorage) {
  try {
    const parsed = JSON.parse(storage?.getItem(CALIBRATION_STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item?.id && Array.isArray(item.dataPoints)) : [];
  } catch {
    return [];
  }
}

export function saveCalibration(calibration, storage = globalThis.localStorage) {
  const calibrations = loadCalibrations(storage).filter((item) => (
    item.id !== calibration.id && item.id !== calibration.replacesCalibrationId
  ));
  calibrations.unshift(calibration);
  storage?.setItem(CALIBRATION_STORAGE_KEY, JSON.stringify(calibrations.slice(0, 20)));
  return calibrations.slice(0, 20);
}

export function clearCalibrations(storage = globalThis.localStorage) {
  storage?.removeItem(CALIBRATION_STORAGE_KEY);
  return [];
}

export function getCalibrationResumePlan(calibrations = []) {
  const calibration = calibrations.find((item) => item?.status === "partial" && Array.isArray(item.dataPoints));
  if (!calibration) return null;
  const completedLevels = [...new Set(calibration.dataPoints
    .filter((point) => point.partial !== true && point.complete !== false && point.usable !== false)
    .map((point) => Number(point.level))
    .filter((level) => Number.isInteger(level) && level >= 1 && level <= 8))]
    .sort((left, right) => left - right);
  const remainingLevels = Array.from({ length: 8 }, (_, index) => index + 1)
    .filter((level) => !completedLevels.includes(level));
  return {
    calibrationId: calibration.id,
    config: { ...(calibration.config || {}) },
    dataPoints: calibration.dataPoints
      .filter((point) => completedLevels.includes(Number(point.level)))
      .map((point) => ({ ...point })),
    completedLevels,
    remainingLevels,
    nextLevel: remainingLevels[0] || null,
  };
}

export function buildCalibrationModel(calibrations = []) {
  const points = calibrations.flatMap((calibration) => (calibration?.dataPoints || []).map((point) => ({
    ...point,
    calibrationId: calibration.id,
  }))).filter((point) => (
    point.partial !== true
    && point.complete !== false
    && point.usable !== false
    &&
    Number.isFinite(Number(point.level))
    && Number.isFinite(Number(point.averageHr))
    && Number.isFinite(Number(point.averageRpm))
  ));
  if (!points.length) return null;

  const referenceRpm = weightedMean(points, (point) => point.averageRpm) || DEFAULT_CALIBRATION_CONFIG.targetRpm;
  const sensitivityCandidates = [];
  for (let index = 0; index < points.length; index += 1) {
    for (let other = index + 1; other < points.length; other += 1) {
      if (Number(points[index].level) !== Number(points[other].level)) continue;
      const rpmDelta = Number(points[index].averageRpm) - Number(points[other].averageRpm);
      if (Math.abs(rpmDelta) < 3) continue;
      sensitivityCandidates.push((Number(points[index].averageHr) - Number(points[other].averageHr)) / rpmDelta);
    }
  }
  const cadenceSensitivity = clamp(median(sensitivityCandidates) ?? 0.5, 0.1, 1.5);
  const cadenceSensitivityMeasured = sensitivityCandidates.length > 0;
  let previousHr = 0;
  const curve = Array.from({ length: 8 }, (_, index) => {
    const level = index + 1;
    const levelPoints = points.filter((point) => Number(point.level) === level);
    if (!levelPoints.length) return null;
    const normalizedHr = weightedMean(levelPoints, (point) => (
      Number(point.averageHr) + (referenceRpm - Number(point.averageRpm)) * cadenceSensitivity
    ));
    const predictedHr = Math.max(previousHr, normalizedHr);
    previousHr = predictedHr;
    return {
      level,
      predictedHr,
      referenceRpm,
      sampleCount: levelPoints.length,
      calibrationSampleCount: levelPoints.filter((point) => point.source !== "live-training").length,
      adaptiveSampleCount: levelPoints.filter((point) => point.source === "live-training").length,
      adaptiveObservationCount: levelPoints
        .filter((point) => point.source === "live-training")
        .reduce((sum, point) => sum + Math.max(1, Number(point.observationCount) || 1), 0),
      warningCount: levelPoints.filter((point) => point.steadyState === false).length,
    };
  }).filter(Boolean);

  return {
    version: 1,
    generatedAt: Date.now(),
    calibrationCount: calibrations.filter((calibration) => calibration?.kind !== "adaptive-training").length,
    pointCount: points.length,
    adaptivePointCount: points.filter((point) => point.source === "live-training").length,
    adaptiveObservationCount: points
      .filter((point) => point.source === "live-training")
      .reduce((sum, point) => sum + Math.max(1, Number(point.observationCount) || 1), 0),
    referenceRpm,
    cadenceSensitivity,
    cadenceSensitivityMeasured,
    cadenceSensitivitySampleCount: sensitivityCandidates.length,
    curve,
  };
}

export function predictCalibrationHr(model, level, rpm = model?.referenceRpm) {
  if (!model?.curve?.length) return null;
  const safeLevel = clamp(Number(level) || 1, 1, 8);
  const lower = [...model.curve].reverse().find((point) => point.level <= safeLevel) || model.curve[0];
  const upper = model.curve.find((point) => point.level >= safeLevel) || model.curve.at(-1);
  const span = upper.level - lower.level;
  const ratio = span ? (safeLevel - lower.level) / span : 0;
  const baseHr = lower.predictedHr + (upper.predictedHr - lower.predictedHr) * ratio;
  return baseHr + (Number(rpm) - model.referenceRpm) * model.cadenceSensitivity;
}

export function recommendCalibrationSetting(model, targetHr, options = {}) {
  if (!model) return null;
  const target = Number(targetHr);
  if (!Number.isFinite(target)) return null;
  const preferredRpm = clamp(Number(options.preferredRpm) || model.referenceRpm || 80, 60, 100);
  const candidates = [];
  const measuredLevels = new Set(model.curve.map((point) => point.level));
  const minimumMeasuredLevel = Math.min(...measuredLevels);
  const maximumMeasuredLevel = Math.max(...measuredLevels);
  const rpmCandidates = Array.from({ length: 41 }, (_, index) => index + 60);
  for (let level = minimumMeasuredLevel; level <= maximumMeasuredLevel; level += 1) {
    for (const rpm of rpmCandidates) {
      const predictedHr = predictCalibrationHr(model, level, rpm);
      if (predictedHr == null) continue;
      const estimated = !measuredLevels.has(level) || !model.cadenceSensitivityMeasured;
      const score = Math.abs(predictedHr - target) + Math.abs(rpm - preferredRpm) * 0.08 + (estimated ? 2 : 0);
      candidates.push({ level, rpm, predictedHr, score, estimated });
    }
  }
  candidates.sort((a, b) => a.score - b.score);
  return candidates[0] ? { ...candidates[0], targetHr: target } : null;
}

export function recommendRpmForLevel(model, targetHr, level, options = {}) {
  if (!model?.curve?.length) return null;
  const safeLevel = clamp(Number(level) || 1, 1, 8);
  const target = Number(targetHr);
  if (!Number.isFinite(target)) return null;
  const measuredLevel = model.curve.some((point) => point.level === safeLevel);
  if (!measuredLevel) return null;
  const minimumRpm = clamp(Number(options.minimumRpm) || 45, 35, 130);
  const maximumRpm = clamp(Number(options.maximumRpm) || 120, minimumRpm, 140);
  const preferredRpm = clamp(Number(options.preferredRpm) || model.referenceRpm || 80, minimumRpm, maximumRpm);
  const candidates = [];
  for (let rpm = minimumRpm; rpm <= maximumRpm; rpm += 1) {
    const predictedHr = predictCalibrationHr(model, safeLevel, rpm);
    if (predictedHr == null) continue;
    candidates.push({
      level: safeLevel,
      rpm,
      predictedHr,
      score: Math.abs(predictedHr - target) + Math.abs(rpm - preferredRpm) * 0.03,
    });
  }
  candidates.sort((left, right) => left.score - right.score);
  const best = candidates[0];
  if (!best) return null;
  const levelPoint = model.curve.find((point) => point.level === safeLevel);
  return {
    ...best,
    targetHr: target,
    estimated: !model.cadenceSensitivityMeasured,
    adaptiveSampleCount: levelPoint?.adaptiveSampleCount || 0,
    calibrationSampleCount: levelPoint?.calibrationSampleCount || 0,
  };
}

export function buildCalibrationZoneMap(model, zones = [], options = {}) {
  return zones.map((zone) => {
    const targetHr = Math.round((Number(zone.min) + Number(zone.max)) / 2);
    return {
      id: zone.id,
      name: ZONE_NAMES[zone.id] || zone.label,
      minHr: zone.min,
      maxHr: zone.max,
      targetHr,
      recommendation: options.level == null
        ? recommendCalibrationSetting(model, targetHr)
        : recommendRpmForLevel(model, targetHr, options.level),
    };
  });
}

export function getLiveCalibrationAdvice({ model, targetHr, currentHr, currentCadence, currentLevel }) {
  const recommendation = recommendCalibrationSetting(model, targetHr, { preferredRpm: currentCadence });
  if (!recommendation) return null;
  const hr = Number(currentHr);
  const cadence = Number(currentCadence);
  const level = Number(currentLevel);
  if (!Number.isFinite(hr) || !Number.isFinite(cadence)) {
    return { ...recommendation, kind: "setup", message: `Ustaw poziom ${recommendation.level} @ ${recommendation.rpm} RPM` };
  }
  if (Number.isFinite(level) && level !== recommendation.level && Math.abs(hr - targetHr) > 7) {
    return { ...recommendation, kind: "resistance", message: `Ustaw poziom ${recommendation.level} @ ${recommendation.rpm} RPM` };
  }
  const difference = Number(targetHr) - hr;
  if (Math.abs(difference) <= 3) {
    return { ...recommendation, kind: "hold", cadenceDelta: 0, message: `Trzymaj ${Math.round(cadence)} RPM · HR w celu` };
  }
  const rawCadenceDelta = clamp(Math.round(difference / Math.max(0.1, model.cadenceSensitivity)), -5, 5);
  const cadenceDelta = rawCadenceDelta > 0 ? Math.max(3, rawCadenceDelta) : Math.min(-3, rawCadenceDelta);
  const targetCadence = clamp(Math.round(cadence + cadenceDelta), 50, 110);
  return {
    ...recommendation,
    kind: cadenceDelta > 0 ? "faster" : "slower",
    cadenceDelta,
    targetCadence,
    message: cadenceDelta > 0
      ? `Zwiększ lekko do ${targetCadence} RPM`
      : `Zwolnij lekko do ${targetCadence} RPM`,
  };
}
