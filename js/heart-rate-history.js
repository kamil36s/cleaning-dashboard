import {
  DAILY_HR_ZONES,
  SPORTS_HR_ZONES,
  buildWorkoutWindows,
  calculateHrZoneDistribution,
  getHrZone,
  isTimestampInWorkout,
} from "./hr-zones.js";
import { liveWorkoutRuntimeUrl } from "./live-workout-runtime-api.js";

const API_URL = "/api/live-workout/heart-rate-history";
const WORKOUT_HISTORY_URL = `${liveWorkoutRuntimeUrl("history")}?limit=200`;
const WORKOUT_SESSION_URL = liveWorkoutRuntimeUrl("session");
const STREAM_URL = liveWorkoutRuntimeUrl("stream");
const DAILY_SAMPLE_LIMIT = 100000;
const TABLE_ROW_LIMIT = 1000;
const RECENT_ARCHIVE_LIMIT = 5000;
const RECENT_ARCHIVE_LOOKBACK_MS = 60 * 1000;
const ARCHIVE_SYNC_INTERVAL_MS = 15 * 1000;
const LIVE_ARCHIVE_MATCH_TOLERANCE_MS = 30 * 1000;
const LIVE_RENDER_INTERVAL_MS = 2 * 1000;
const CHART_GAP_MS = 5 * 60 * 1000;
const RING_PHASE_GAP_MS = 7 * 60 * 1000;
const FLATLINE_DURATION_MS = 60 * 1000;
const FLATLINE_MIN_SAMPLES = 45;
const FLATLINE_MAX_GAP_MS = 60 * 1000;
const FLATLINE_MAX_RANGE_BPM = 2;
const FLATLINE_MAX_STDDEV_BPM = .35;
const FLATLINE_MAX_CHANGE_RATIO = .03;
const FLATLINE_MIN_DOMINANT_RATIO = .98;
const MIN_CHART_WINDOW_MS = 60 * 1000;
const STREAM_BREAK_MS = 30 * 1000;
const MIN_STREAM_SAMPLES = 5;
const VALID_STATUSES = new Set(["ready", "running", "paused", "finished"]);
const WORKOUT_PRESENTATION = {
  cardio: {
    label: "Cardio z planu",
    color: "#f59e0b",
    fill: "rgba(245,158,11,.075)",
  },
  strength: {
    label: "Trening siłowy",
    color: "#e879f9",
    fill: "rgba(232,121,249,.075)",
  },
  walk: {
    label: "Sesja spacerowa",
    color: "#22c55e",
    fill: "rgba(34,197,94,.075)",
  },
};

const elements = {
  day: document.getElementById("hr-history-day"),
  previousDay: document.getElementById("hr-history-previous-day"),
  nextDay: document.getElementById("hr-history-next-day"),
  today: document.getElementById("hr-history-today"),
  refresh: document.getElementById("hr-history-refresh"),
  chart: document.getElementById("hr-history-chart"),
  chartDay: document.getElementById("hr-history-chart-day"),
  liveIndicator: document.getElementById("hr-history-live-indicator"),
  liveLabel: document.getElementById("hr-history-live-label"),
  chartWindow: document.getElementById("hr-history-chart-window"),
  workoutPeriods: document.getElementById("hr-history-workout-periods"),
  ringPeriods: document.getElementById("hr-history-ring-periods"),
  chartEmpty: document.getElementById("hr-history-chart-empty"),
  chartTooltip: document.getElementById("hr-history-chart-tooltip"),
  tooltipTime: document.getElementById("hr-history-tooltip-time"),
  tooltipBpm: document.getElementById("hr-history-tooltip-bpm"),
  tooltipSource: document.getElementById("hr-history-tooltip-source"),
  tooltipMode: document.getElementById("hr-history-tooltip-mode"),
  tooltipZone: document.getElementById("hr-history-tooltip-zone"),
  tooltipDescription: document.getElementById("hr-history-tooltip-description"),
  zoneLegend: document.getElementById("hr-history-zone-legend"),
  zoomOut: document.getElementById("hr-history-zoom-out"),
  zoomIn: document.getElementById("hr-history-zoom-in"),
  fitData: document.getElementById("hr-history-fit-data"),
  fullDay: document.getElementById("hr-history-full-day"),
  latestBpm: document.getElementById("hr-history-latest-bpm"),
  latestTime: document.getElementById("hr-history-latest-time"),
  latestZone: document.getElementById("hr-history-latest-zone"),
  latestCard: document.getElementById("hr-history-latest-card"),
  average: document.getElementById("hr-history-average"),
  averageZone: document.getElementById("hr-history-average-zone"),
  averageCard: document.getElementById("hr-history-average-card"),
  sportsAverage: document.getElementById("hr-history-sports-average"),
  sportsAverageZone: document.getElementById("hr-history-sports-average-zone"),
  sportsAverageCard: document.getElementById("hr-history-sports-average-card"),
  range: document.getElementById("hr-history-range"),
  rangeZone: document.getElementById("hr-history-range-zone"),
  rangeCard: document.getElementById("hr-history-range-card"),
  dailyPie: document.getElementById("hr-history-daily-pie"),
  dailyPieTotal: document.getElementById("hr-history-daily-pie-total"),
  dailyPieLegend: document.getElementById("hr-history-daily-pie-legend"),
  sportsPie: document.getElementById("hr-history-sports-pie"),
  sportsPieTotal: document.getElementById("hr-history-sports-pie-total"),
  sportsPieLegend: document.getElementById("hr-history-sports-pie-legend"),
  count: document.getElementById("hr-history-count"),
  successRate: document.getElementById("hr-history-success-rate"),
  dayCoverage: document.getElementById("hr-history-day-coverage"),
  dayCoverageNote: document.getElementById("hr-history-day-coverage-note"),
  packetLoss: document.getElementById("hr-history-packet-loss"),
  packetLossNote: document.getElementById("hr-history-packet-loss-note"),
  status: document.getElementById("hr-history-status"),
  rawDetails: document.querySelector(".hr-history-raw-details"),
  rows: document.getElementById("hr-history-rows"),
  empty: document.getElementById("hr-history-empty"),
  tableSummary: document.getElementById("hr-history-table-summary"),
};

const timestampFormatter = new Intl.DateTimeFormat("pl-PL", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  fractionalSecondDigits: 3,
  timeZoneName: "short",
});

const dayHeadingFormatter = new Intl.DateTimeFormat("pl-PL", {
  weekday: "long",
  year: "numeric",
  month: "long",
  day: "numeric",
});

const pad2 = (value) => String(value).padStart(2, "0");

function renderZoneLegend() {
  if (!elements.zoneLegend) return;
  elements.zoneLegend.replaceChildren();
  [
    { title: "Tryb codzienny · poza treningiem", zones: DAILY_HR_ZONES },
    { title: "Tryb sportowy · trening · maxHR 190", zones: SPORTS_HR_ZONES },
  ].forEach(({ title, zones }) => {
    const group = document.createElement("section");
    group.className = "hr-history-zone-legend-group";
    const heading = document.createElement("strong");
    heading.textContent = title;
    const items = document.createElement("div");
    items.className = "hr-history-zone-legend-items";
    zones.forEach((zone) => {
      const chip = document.createElement("span");
      chip.className = "hr-history-zone-chip";
      chip.style.setProperty("--hr-zone-color", zone.color);
      chip.textContent = `${zone.range} · ${zone.label}`;
      chip.tabIndex = 0;
      chip.title = zone.description || `${zone.label} — strefa sportowa dla maxHR 190.`;
      items.appendChild(chip);
    });
    group.append(heading, items);
    elements.zoneLegend.appendChild(group);
  });
}

export function localDayKey(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function dateFromDayKey(dayKey) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dayKey || ""))) return null;
  const [year, month, day] = dayKey.split("-").map(Number);
  const date = new Date(year, month - 1, day, 12);
  if (
    date.getFullYear() !== year
    || date.getMonth() !== month - 1
    || date.getDate() !== day
  ) return null;
  return date;
}

export function shiftDayKey(dayKey, offset) {
  const date = dateFromDayKey(dayKey);
  if (!date) return localDayKey();
  date.setDate(date.getDate() + Number(offset || 0));
  return localDayKey(date);
}

export function localDayRange(dayKey) {
  const date = dateFromDayKey(dayKey) || dateFromDayKey(localDayKey());
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const end = new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1).getTime() - 1;
  return { start, end };
}

export function formatHeartRateTimestamp(value) {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp)) return "—";
  return timestampFormatter.format(new Date(timestamp));
}

export function summarizeHeartRateSamples(samples = []) {
  const summary = samples.reduce((result, sample) => {
    const value = Number(sample?.heart_rate);
    if (!Number.isFinite(value)) return result;
    result.count += 1;
    result.total += value;
    result.minimum = Math.min(result.minimum, value);
    result.maximum = Math.max(result.maximum, value);
    return result;
  }, { count: 0, total: 0, minimum: Infinity, maximum: -Infinity });
  if (!summary.count) {
    return { count: 0, average: null, minimum: null, maximum: null };
  }
  return {
    count: summary.count,
    average: Math.round(summary.total / summary.count),
    minimum: summary.minimum,
    maximum: summary.maximum,
  };
}

export function summarizeHeartRateSamplesByMode(samples = [], workoutWindows = []) {
  const daily = [];
  const sports = [];
  samples.forEach((sample) => {
    const timestamp = Number(sample?.timestamp);
    const heartRate = Number(sample?.heart_rate);
    if (!Number.isFinite(timestamp) || !Number.isFinite(heartRate)) return;
    (isTimestampInWorkout(timestamp, workoutWindows) ? sports : daily).push(sample);
  });
  return {
    daily: summarizeHeartRateSamples(daily),
    sports: summarizeHeartRateSamples(sports),
  };
}

function compareHeartRateSamples(left, right) {
  return Number(right?.timestamp || 0) - Number(left?.timestamp || 0)
    || Number(right?.received_at || 0) - Number(left?.received_at || 0)
    || Number(right?.id || 0) - Number(left?.id || 0);
}

function telemetryKey(sample) {
  return [
    Number(sample?.timestamp),
    Number(sample?.heart_rate),
    String(sample?.status || "").trim().toLowerCase(),
  ].join("|");
}

function storedTelemetryKey(sample) {
  return `${telemetryKey(sample)}|${Number(sample?.received_at)}`;
}

export function isSmartRingHeartRateSample(sample) {
  const source = String(sample?.source || sample?.payload?.source || "").toLowerCase();
  return source === "smart_ring" || source === "colmi-ring";
}

function heartRateSourceLabel(sample) {
  return isSmartRingHeartRateSample(sample)
    ? String(sample?.source_label || "COLMI Ring")
    : String(sample?.source_label || "Smartwatch");
}

export function applySmartwatchPriority(samples = []) {
  const smartwatchMinutes = new Set(samples
    .filter((sample) => !isSmartRingHeartRateSample(sample))
    .map((sample) => Math.floor(Number(sample?.timestamp) / 60000))
    .filter(Number.isFinite));
  return samples.filter((sample) => (
    !isSmartRingHeartRateSample(sample)
    || !smartwatchMinutes.has(Math.floor(Number(sample?.timestamp) / 60000))
  ));
}

export function buildSmartRingOnlyPhases(samples = [], maximumGapMs = RING_PHASE_GAP_MS) {
  const ordered = samples
    .filter((sample) => Number.isFinite(Number(sample?.timestamp)))
    .slice()
    .sort((left, right) => Number(left.timestamp) - Number(right.timestamp));
  const phases = [];
  let active = null;
  ordered.forEach((sample) => {
    if (!isSmartRingHeartRateSample(sample)) {
      if (active) phases.push(active);
      active = null;
      return;
    }
    const timestamp = Number(sample.timestamp);
    if (!active || timestamp - active.end > maximumGapMs) {
      if (active) phases.push(active);
      active = { start: timestamp, end: timestamp, sampleCount: 1 };
      return;
    }
    active.end = timestamp;
    active.sampleCount += 1;
  });
  if (active) phases.push(active);
  return phases;
}

export function createLiveHeartRateSample(payload, receivedAt = Date.now()) {
  const timestamp = Number(payload?.timestamp);
  const heartRate = Number(payload?.heart_rate);
  const status = String(payload?.status || "").trim().toLowerCase();
  const received = Number(receivedAt);
  if (
    !Number.isInteger(timestamp)
    || timestamp <= 0
    || !Number.isInteger(heartRate)
    || heartRate < 30
    || heartRate > 240
    || !VALID_STATUSES.has(status)
    || !Number.isFinite(received)
    || received <= 0
  ) return null;
  return {
    timestamp,
    heart_rate: heartRate,
    status,
    received_at: Math.round(received),
    payload: { ...payload },
    source: "smartwatch",
    source_label: "Smartwatch",
    __live: true,
  };
}

export function mergeArchivedHeartRateSamples(existingSamples = [], archivedSamples = []) {
  const existing = Array.isArray(existingSamples) ? existingSamples : [];
  const archived = Array.isArray(archivedSamples)
    ? archivedSamples.slice().sort(compareHeartRateSamples)
    : [];
  const liveSamples = [];
  const liveByTelemetry = new Map();
  const storedSamples = [];
  const storedById = new Map();
  const storedByTelemetry = new Map();

  const registerStoredSample = (sample, index) => {
    const sampleId = Number(sample?.id);
    if (Number.isInteger(sampleId) && !storedById.has(sampleId)) {
      storedById.set(sampleId, index);
    }
    const sampleKey = storedTelemetryKey(sample);
    if (!storedByTelemetry.has(sampleKey)) storedByTelemetry.set(sampleKey, index);
  };

  existing.forEach((sample) => {
    if (sample?.__live) {
      const index = liveSamples.length;
      liveSamples.push(sample);
      const key = telemetryKey(sample);
      const candidates = liveByTelemetry.get(key) || [];
      candidates.push(index);
      liveByTelemetry.set(key, candidates);
      return;
    }
    const index = storedSamples.length;
    storedSamples.push(sample);
    registerStoredSample(sample, index);
  });

  const consumedLiveSamples = new Set();

  archived.forEach((sample) => {
    const receivedAt = Number(sample?.received_at);
    let bestLiveIndex = -1;
    let bestDistance = Number.POSITIVE_INFINITY;
    (liveByTelemetry.get(telemetryKey(sample)) || []).forEach((index) => {
      if (consumedLiveSamples.has(index)) return;
      const candidate = liveSamples[index];
      const distance = Math.abs(Number(candidate.received_at) - receivedAt);
      if (Number.isFinite(distance) && distance < bestDistance) {
        bestDistance = distance;
        bestLiveIndex = index;
      }
    });
    if (bestLiveIndex >= 0 && bestDistance <= LIVE_ARCHIVE_MATCH_TOLERANCE_MS) {
      consumedLiveSamples.add(bestLiveIndex);
    }

    const sampleId = Number(sample?.id);
    const storedIndex = Number.isInteger(sampleId)
      ? storedById.get(sampleId)
      : storedByTelemetry.get(storedTelemetryKey(sample));
    if (storedIndex !== undefined) {
      storedSamples[storedIndex] = sample;
      registerStoredSample(sample, storedIndex);
    } else {
      const index = storedSamples.length;
      storedSamples.push(sample);
      registerStoredSample(sample, index);
    }
  });

  const next = liveSamples.filter((_sample, index) => !consumedLiveSamples.has(index))
    .concat(storedSamples);
  return applySmartwatchPriority(next.sort(compareHeartRateSamples));
}

export function filterUnwornHeartRateSamples(
  samples = [],
  {
    minimumDurationMs = FLATLINE_DURATION_MS,
    minimumSamples = FLATLINE_MIN_SAMPLES,
    maximumGapMs = FLATLINE_MAX_GAP_MS,
  } = {},
) {
  const indexed = samples
    .map((sample, index) => ({ sample, index, timestamp: Number(sample?.timestamp) }))
    .filter((item) => Number.isFinite(item.timestamp))
    .sort((left, right) => left.timestamp - right.timestamp);
  const rejected = new Set();
  let run = [];
  let exactRun = [];
  let runMinimum = null;
  let runMaximum = null;
  const finishExactRun = () => {
    if (!exactRun.length) return;
    const duration = exactRun.at(-1).timestamp - exactRun[0].timestamp;
    const distinctTimestamps = new Set(exactRun.map((item) => item.timestamp)).size;
    if (duration >= minimumDurationMs && distinctTimestamps >= minimumSamples) {
      exactRun.forEach((item) => rejected.add(item.index));
    }
  };
  const finishRun = () => {
    if (!run.length) return;
    const duration = run.at(-1).timestamp - run[0].timestamp;
    const distinctTimestamps = new Set(run.map((item) => item.timestamp)).size;
    const heartRates = run.map((item) => Number(item.sample?.heart_rate));
    const counts = new Map();
    let total = 0;
    let totalSquares = 0;
    let changes = 0;
    heartRates.forEach((heartRate, index) => {
      counts.set(heartRate, (counts.get(heartRate) || 0) + 1);
      total += heartRate;
      totalSquares += heartRate * heartRate;
      if (index && heartRate !== heartRates[index - 1]) changes += 1;
    });
    const average = total / heartRates.length;
    const variance = Math.max(0, totalSquares / heartRates.length - average * average);
    const dominantRatio = Math.max(...counts.values()) / heartRates.length;
    const changeRatio = changes / Math.max(1, heartRates.length - 1);
    if (
      duration >= minimumDurationMs
      && distinctTimestamps >= minimumSamples
      && runMaximum - runMinimum <= FLATLINE_MAX_RANGE_BPM
      && Math.sqrt(variance) <= FLATLINE_MAX_STDDEV_BPM
      && changeRatio <= FLATLINE_MAX_CHANGE_RATIO
      && dominantRatio >= FLATLINE_MIN_DOMINANT_RATIO
    ) {
      run.forEach((item) => rejected.add(item.index));
    }
  };

  indexed.forEach((item) => {
    const previousExact = exactRun.at(-1);
    const exactGap = previousExact ? item.timestamp - previousExact.timestamp : 0;
    if (
      previousExact
      && (
        Number(item.sample?.heart_rate) !== Number(previousExact.sample?.heart_rate)
        || exactGap < 0
        || exactGap > maximumGapMs
      )
    ) {
      finishExactRun();
      exactRun = [];
    }
    exactRun.push(item);
    const previous = run.at(-1);
    const gap = previous ? item.timestamp - previous.timestamp : 0;
    if (
      previous
      && (
        gap < 0
        || gap > maximumGapMs
        || Math.max(runMaximum, Number(item.sample?.heart_rate))
          - Math.min(runMinimum, Number(item.sample?.heart_rate)) > FLATLINE_MAX_RANGE_BPM
      )
    ) {
      finishRun();
      run = [];
      runMinimum = null;
      runMaximum = null;
    }
    run.push(item);
    const heartRate = Number(item.sample?.heart_rate);
    runMinimum = runMinimum === null ? heartRate : Math.min(runMinimum, heartRate);
    runMaximum = runMaximum === null ? heartRate : Math.max(runMaximum, heartRate);
  });
  finishExactRun();
  finishRun();
  return samples.filter((_sample, index) => !rejected.has(index));
}

export function downsampleHeartRatePoints(points = [], maximumPoints = 2400) {
  const safeMaximum = Math.max(4, Math.floor(Number(maximumPoints) || 2400));
  if (points.length <= safeMaximum) return points;
  const ringPoints = points.filter(isSmartRingHeartRateSample);
  if (ringPoints.length && ringPoints.length <= safeMaximum - 4) {
    const smartwatchPoints = points.filter((point) => !isSmartRingHeartRateSample(point));
    const sampledSmartwatch = downsampleHeartRatePoints(
      smartwatchPoints,
      safeMaximum - ringPoints.length,
    );
    return sampledSmartwatch.concat(ringPoints)
      .sort((left, right) => Number(left?.timestamp) - Number(right?.timestamp));
  }
  const bucketCount = Math.max(1, Math.floor((safeMaximum - 2) / 2));
  const bucketSize = Math.ceil((points.length - 2) / bucketCount);
  const sampled = [points[0]];
  for (let start = 1; start < points.length - 1; start += bucketSize) {
    const bucket = points.slice(start, Math.min(points.length - 1, start + bucketSize));
    let minimum = bucket[0];
    let maximum = bucket[0];
    bucket.forEach((point) => {
      if (point.bpm < minimum.bpm) minimum = point;
      if (point.bpm > maximum.bpm) maximum = point;
    });
    if (minimum === maximum) sampled.push(minimum);
    else if (minimum.timestamp < maximum.timestamp) sampled.push(minimum, maximum);
    else sampled.push(maximum, minimum);
  }
  sampled.push(points.at(-1));
  return sampled;
}

function median(values) {
  if (!values.length) return null;
  const sorted = values.slice().sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function isSuccessfulArchiveSample(sample) {
  const timestamp = Number(sample?.timestamp);
  const receivedAt = Number(sample?.received_at);
  const heartRate = Number(sample?.heart_rate);
  const status = String(sample?.status || "").trim().toLowerCase();
  return Number.isInteger(timestamp)
    && timestamp > 0
    && Number.isFinite(receivedAt)
    && receivedAt > 0
    && Number.isInteger(heartRate)
    && heartRate >= 30
    && heartRate <= 240
    && VALID_STATUSES.has(status)
    && sample?.payload !== null
    && typeof sample?.payload === "object"
    && !Array.isArray(sample.payload);
}

export function analyzeHeartRateTelemetry(samples = [], dayStart, dayEnd) {
  const start = Number(dayStart);
  const end = Number(dayEnd);
  const dayDurationMs = Math.max(1, end - start + 1);
  const successfulSamples = samples.filter(isSuccessfulArchiveSample);
  const coveredSeconds = new Set(successfulSamples
    .map((sample) => Number(sample.timestamp))
    .filter((timestamp) => timestamp >= start && timestamp <= end)
    .map((timestamp) => Math.floor((timestamp - start) / 1000)));
  const successPercent = samples.length
    ? successfulSamples.length / samples.length * 100
    : null;
  const coveragePercent = coveredSeconds.size / (dayDurationMs / 1000) * 100;

  const timestamps = Array.from(new Set(successfulSamples
    .map((sample) => Number(sample.timestamp))
    .filter((timestamp) => timestamp >= start && timestamp <= end)))
    .sort((left, right) => left - right);
  const cadenceCandidates = timestamps
    .slice(1)
    .map((timestamp, index) => timestamp - timestamps[index])
    .filter((delta) => delta > 0 && delta <= STREAM_BREAK_MS);
  const cadenceMs = median(cadenceCandidates);

  let lostPackets = null;
  let lossPercent = null;
  let gapCount = 0;
  let streamCount = 0;
  if (cadenceMs && cadenceCandidates.length >= MIN_STREAM_SAMPLES - 1) {
    const streams = [];
    let stream = [];
    timestamps.forEach((timestamp) => {
      if (stream.length && timestamp - stream[stream.length - 1] > STREAM_BREAK_MS) {
        streams.push(stream);
        stream = [];
      }
      stream.push(timestamp);
    });
    if (stream.length) streams.push(stream);
    const activeStreams = streams.filter((items) => items.length >= MIN_STREAM_SAMPLES);
    streamCount = activeStreams.length;
    if (activeStreams.length) {
      lostPackets = 0;
      let receivedPackets = 0;
      activeStreams.forEach((items) => {
        receivedPackets += items.length;
        items.slice(1).forEach((timestamp, index) => {
          const missing = Math.max(0, Math.round((timestamp - items[index]) / cadenceMs) - 1);
          if (missing > 0) gapCount += 1;
          lostPackets += missing;
        });
      });
      const expectedPackets = receivedPackets + lostPackets;
      lossPercent = expectedPackets ? lostPackets / expectedPackets * 100 : 0;
    }
  }

  return {
    total: samples.length,
    successful: successfulSamples.length,
    successPercent,
    coveredSeconds: coveredSeconds.size,
    coveragePercent,
    cadenceMs,
    streamCount,
    gapCount,
    lostPackets,
    lossPercent,
  };
}

export function fitHeartRateDataRange(samples = [], dayStart, dayEnd) {
  const start = Number(dayStart);
  const end = Number(dayEnd);
  const timestamps = samples
    .map((sample) => Number(sample?.timestamp))
    .filter((timestamp) => Number.isFinite(timestamp) && timestamp >= start && timestamp <= end)
    .sort((left, right) => left - right);
  if (!timestamps.length) return { start, end };

  const first = timestamps[0];
  const last = timestamps[timestamps.length - 1];
  const dataDuration = Math.max(0, last - first);
  const padding = dataDuration
    ? Math.max(60 * 1000, Math.min(15 * 60 * 1000, dataDuration * .06))
    : 5 * 60 * 1000;
  let fittedStart = Math.max(start, first - padding);
  let fittedEnd = Math.min(end, last + padding);
  if (fittedEnd - fittedStart < MIN_CHART_WINDOW_MS) {
    const middle = (fittedStart + fittedEnd) / 2;
    fittedStart = Math.max(start, middle - MIN_CHART_WINDOW_MS / 2);
    fittedEnd = Math.min(end, fittedStart + MIN_CHART_WINDOW_MS);
    fittedStart = Math.max(start, fittedEnd - MIN_CHART_WINDOW_MS);
  }
  return { start: fittedStart, end: fittedEnd };
}

export function zoomHeartRateRange(range, factor, dayStart, dayEnd) {
  const start = Number(dayStart);
  const end = Number(dayEnd);
  const currentStart = Math.max(start, Number(range?.start) || start);
  const currentEnd = Math.min(end, Number(range?.end) || end);
  const middle = (currentStart + currentEnd) / 2;
  const nextDuration = Math.max(
    MIN_CHART_WINDOW_MS,
    Math.min(end - start, (currentEnd - currentStart) * Number(factor || 1)),
  );
  let nextStart = middle - nextDuration / 2;
  let nextEnd = middle + nextDuration / 2;
  if (nextStart < start) {
    nextEnd += start - nextStart;
    nextStart = start;
  }
  if (nextEnd > end) {
    nextStart -= nextEnd - end;
    nextEnd = end;
  }
  return { start: Math.max(start, nextStart), end: Math.min(end, nextEnd) };
}

export function buildHeartRateChartModel(samples = [], dayStart, dayEnd, maximumPoints = Infinity) {
  const start = Number(dayStart);
  const end = Number(dayEnd);
  const duration = Math.max(1, end - start);
  const allPoints = samples
    .map((sample) => ({
      timestamp: Number(sample?.timestamp),
      bpm: Number(sample?.heart_rate),
      source: sample?.source,
      sourceLabel: heartRateSourceLabel(sample),
    }))
    .filter((point) => Number.isFinite(point.timestamp)
      && Number.isFinite(point.bpm)
      && point.timestamp >= start
      && point.timestamp <= end)
    .sort((left, right) => left.timestamp - right.timestamp)
    .map((point) => ({
      ...point,
      x: Math.max(0, Math.min(1, (point.timestamp - start) / duration)),
    }));
  const points = Number.isFinite(maximumPoints)
    ? downsampleHeartRatePoints(allPoints, maximumPoints)
    : allPoints;

  if (!points.length) {
    return { points, minimum: 60, maximum: 180 };
  }

  const bounds = points.reduce((result, point) => ({
    minimum: Math.min(result.minimum, point.bpm),
    maximum: Math.max(result.maximum, point.bpm),
  }), { minimum: Infinity, maximum: -Infinity });
  let minimum = Math.max(30, Math.floor((bounds.minimum - 8) / 10) * 10);
  let maximum = Math.min(240, Math.ceil((bounds.maximum + 8) / 10) * 10);
  if (maximum - minimum < 20) {
    minimum = Math.max(30, minimum - 10);
    maximum = Math.min(240, maximum + 10);
  }
  return { points, minimum, maximum };
}

function selectedDayKey() {
  return dateFromDayKey(elements.day?.value) ? elements.day.value : localDayKey();
}

function buildRequestUrl({ from, to, limit = DAILY_SAMPLE_LIMIT } = {}) {
  const range = localDayRange(selectedDayKey());
  const url = new URL(API_URL, window.location.origin);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("from", String(Number.isFinite(Number(from)) ? Number(from) : range.start));
  url.searchParams.set("to", String(Number.isFinite(Number(to)) ? Number(to) : range.end));
  return url;
}

async function loadWorkoutState(signal) {
  const loadJson = async (url) => {
    const response = await fetch(url, { cache: "no-store", signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json().catch(() => ({}));
  };
  const [historyResult, activeResult] = await Promise.allSettled([
    loadJson(WORKOUT_HISTORY_URL),
    loadJson(WORKOUT_SESSION_URL),
  ]);
  const sessions = historyResult.status === "fulfilled" && Array.isArray(historyResult.value?.sessions)
    ? historyResult.value.sessions.slice()
    : [];
  const activeSession = activeResult.status === "fulfilled" ? activeResult.value?.session : null;
  if (activeSession && !sessions.some((session) => session?.id === activeSession.id)) {
    sessions.push(activeSession);
  }
  return {
    sessions,
    available: historyResult.status === "fulfilled" || activeResult.status === "fulfilled",
  };
}

function appendCell(row, label, className = "") {
  const cell = document.createElement("td");
  cell.dataset.label = label;
  if (className) cell.className = className;
  row.appendChild(cell);
  return cell;
}

function updateTableSummary(sampleCount) {
  if (!elements.tableSummary) return;
  elements.tableSummary.textContent = sampleCount > TABLE_ROW_LIMIT
    ? `${sampleCount} próbek · pokazuję najnowsze ${TABLE_ROW_LIMIT}`
    : `${sampleCount} próbek · rozwiń tabelę`;
}

function renderRows(samples) {
  const visibleSamples = samples.slice(0, TABLE_ROW_LIMIT);
  elements.rows.replaceChildren();
  elements.empty.hidden = visibleSamples.length > 0;
  updateTableSummary(samples.length);

  visibleSamples.forEach((sample) => {
    const row = document.createElement("tr");
    const recordedCell = appendCell(row, "Czas pomiaru", "hr-history-time");
    recordedCell.textContent = formatHeartRateTimestamp(sample.timestamp);

    const bpmCell = appendCell(row, "BPM", "hr-history-bpm");
    const bpm = document.createElement("strong");
    bpm.textContent = String(sample.heart_rate ?? "—");
    bpmCell.appendChild(bpm);

    const sourceCell = appendCell(row, "Źródło");
    const source = document.createElement("span");
    source.className = "hr-history-source-pill";
    source.dataset.source = isSmartRingHeartRateSample(sample) ? "ring" : "watch";
    source.textContent = heartRateSourceLabel(sample);
    sourceCell.appendChild(source);

    const statusCell = appendCell(row, "Status");
    const status = document.createElement("span");
    status.className = "hr-history-status-pill";
    status.textContent = String(sample.status || "—");
    statusCell.appendChild(status);

    const receivedCell = appendCell(row, "Odebrane", "hr-history-time");
    receivedCell.textContent = formatHeartRateTimestamp(sample.received_at);

    const payloadCell = appendCell(row, "Payload");
    const details = document.createElement("details");
    const detailsSummary = document.createElement("summary");
    const payload = document.createElement("pre");
    detailsSummary.textContent = "Pokaż JSON";
    payload.textContent = JSON.stringify(sample.payload ?? {}, null, 2);
    details.append(detailsSummary, payload);
    payloadCell.appendChild(details);
    elements.rows.appendChild(row);
  });
}

function applyVitalCardZone(card, primaryColor, secondaryColor = primaryColor) {
  if (!card) return;
  card.style.setProperty("--hr-zone-color", primaryColor || "#71717a");
  card.style.setProperty("--hr-zone-color-secondary", secondaryColor || primaryColor || "#71717a");
}

function formatZoneDuration(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000));
  if (totalSeconds >= 3600) {
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.round((totalSeconds % 3600) / 60);
    return `${hours} h ${minutes} min`;
  }
  if (totalSeconds >= 60) return `${Math.round(totalSeconds / 60)} min`;
  return `${totalSeconds} s`;
}

function renderPieMode(mode, pie, total, legend, label) {
  if (!pie || !total || !legend) return;
  const formatter = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  let cursor = 0;
  const segments = mode.zones
    .filter((zone) => zone.percent > 0)
    .map((zone) => {
      const start = cursor;
      cursor += zone.percent;
      return `${zone.color} ${start}% ${cursor}%`;
    });
  pie.style.background = segments.length
    ? `conic-gradient(${segments.join(", ")})`
    : "conic-gradient(#27272a 0 100%)";
  total.textContent = mode.totalMs ? formatZoneDuration(mode.totalMs) : "Brak danych";
  pie.setAttribute(
    "aria-label",
    mode.totalMs
      ? `${label}: ${mode.zones.map((zone) => `${zone.label} ${formatter.format(zone.percent)}%`).join(", ")}`
      : `${label}: brak danych`,
  );
  legend.replaceChildren();
  mode.zones.forEach((zone) => {
    const row = document.createElement("div");
    row.className = "hr-history-pie-legend-row";
    if (!zone.durationMs) row.classList.add("is-empty");
    row.style.setProperty("--hr-zone-color", zone.color);
    row.title = `${zone.range} · ${zone.label} · ${formatZoneDuration(zone.durationMs)}`;
    const dot = document.createElement("i");
    const name = document.createElement("span");
    name.textContent = zone.label;
    const value = document.createElement("strong");
    value.textContent = `${formatter.format(zone.percent)}%`;
    row.append(dot, name, value);
    legend.appendChild(row);
  });
}

function renderZoneTimeDistribution(samples, workoutWindows) {
  const distribution = calculateHrZoneDistribution(samples, workoutWindows);
  renderPieMode(
    distribution.daily,
    elements.dailyPie,
    elements.dailyPieTotal,
    elements.dailyPieLegend,
    "Tryb codzienny",
  );
  renderPieMode(
    distribution.sports,
    elements.sportsPie,
    elements.sportsPieTotal,
    elements.sportsPieLegend,
    "Tryb sportowy",
  );
}

function renderSummary(samples, workoutWindows = []) {
  const summary = summarizeHeartRateSamples(samples);
  const modeSummaries = summarizeHeartRateSamplesByMode(samples, workoutWindows);
  const latest = samples[0];
  const dayRange = localDayRange(selectedDayKey());
  const quality = analyzeHeartRateTelemetry(samples, dayRange.start, dayRange.end);
  const percentFormatter = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
  elements.count.textContent = String(samples.length);
  elements.average.textContent = modeSummaries.daily.average === null
    ? "—"
    : `${modeSummaries.daily.average} BPM`;
  elements.sportsAverage.textContent = modeSummaries.sports.average === null
    ? "—"
    : `${modeSummaries.sports.average} BPM`;
  elements.range.textContent = summary.minimum === null
    ? "—"
    : `${summary.minimum}–${summary.maximum}`;
  elements.latestBpm.textContent = latest ? `${latest.heart_rate} BPM` : "—";
  elements.latestTime.textContent = latest
    ? formatHeartRateTimestamp(latest.timestamp)
    : "Brak danych";
  const latestWorkoutActive = latest
    ? isTimestampInWorkout(latest.timestamp, workoutWindows)
    : false;
  const latestHrZone = latest ? getHrZone(latest.heart_rate, latestWorkoutActive) : null;
  elements.latestBpm.style.color = latestHrZone?.color || "";
  elements.latestBpm.title = latestHrZone?.description || latestHrZone?.label || "";
  elements.latestZone.textContent = latestHrZone
    ? `${latestWorkoutActive ? "Tryb sportowy" : "Tryb codzienny"} · ${latestHrZone.label} · ${heartRateSourceLabel(latest)}`
    : "Brak strefy";
  elements.latestZone.style.color = latestHrZone?.color || "";
  applyVitalCardZone(elements.latestCard, latestHrZone?.color);

  const numericSamples = samples.filter((sample) => Number.isFinite(Number(sample?.heart_rate)));
  const averageZone = modeSummaries.daily.average === null
    ? null
    : getHrZone(modeSummaries.daily.average, false);
  elements.averageZone.textContent = averageZone
    ? `Poza treningami · ${averageZone.label}`
    : "Brak danych poza treningami";
  elements.averageZone.style.color = averageZone?.color || "";
  elements.average.title = averageZone?.description || averageZone?.label || "";
  applyVitalCardZone(elements.averageCard, averageZone?.color);

  const sportsAverageZone = modeSummaries.sports.average === null
    ? null
    : getHrZone(modeSummaries.sports.average, true);
  elements.sportsAverageZone.textContent = sportsAverageZone
    ? `Aktywne treningi · ${sportsAverageZone.label}`
    : "Brak danych podczas treningu";
  elements.sportsAverageZone.style.color = sportsAverageZone?.color || "";
  elements.sportsAverage.title = sportsAverageZone?.description || sportsAverageZone?.label || "";
  applyVitalCardZone(elements.sportsAverageCard, sportsAverageZone?.color);

  const minimumSample = numericSamples.reduce((result, sample) => (
    !result || Number(sample.heart_rate) < Number(result.heart_rate) ? sample : result
  ), null);
  const maximumSample = numericSamples.reduce((result, sample) => (
    !result || Number(sample.heart_rate) > Number(result.heart_rate) ? sample : result
  ), null);
  const minimumZone = minimumSample
    ? getHrZone(minimumSample.heart_rate, isTimestampInWorkout(minimumSample.timestamp, workoutWindows))
    : null;
  const maximumZone = maximumSample
    ? getHrZone(maximumSample.heart_rate, isTimestampInWorkout(maximumSample.timestamp, workoutWindows))
    : null;
  elements.rangeZone.textContent = minimumZone && maximumZone
    ? `${minimumZone.label} → ${maximumZone.label}`
    : "minimum – maksimum";
  elements.range.title = minimumZone && maximumZone
    ? `Minimum: ${minimumZone.label}. Maksimum: ${maximumZone.label}.`
    : "";
  applyVitalCardZone(elements.rangeCard, minimumZone?.color, maximumZone?.color);

  elements.successRate.textContent = quality.successPercent === null
    ? "—"
    : `${percentFormatter.format(quality.successPercent)}%`;
  elements.dayCoverage.textContent = `${percentFormatter.format(quality.coveragePercent)}%`;
  elements.dayCoverageNote.textContent = `${quality.coveredSeconds.toLocaleString("pl-PL")} sekund z danymi`;
  if (quality.lostPackets === null) {
    elements.packetLoss.textContent = "—";
    elements.packetLossNote.textContent = "Potrzeba co najmniej 5 regularnych próbek";
  } else {
    elements.packetLoss.textContent = `${quality.lostPackets.toLocaleString("pl-PL")} · ${percentFormatter.format(quality.lossPercent)}%`;
    elements.packetLossNote.textContent = quality.streamCount
      ? `${quality.gapCount} luk · ${quality.streamCount} aktywnych serii · mediana ${Math.round(quality.cadenceMs)} ms`
      : "Brak serii spełniającej kryterium aktywnego przesyłu";
  }
  renderZoneTimeDistribution(samples, workoutWindows);
}

let chartSamples = [];
let chartRange = null;
let chartRangeMode = "fit";
let chartWorkoutWindows = [];
let chartRenderState = { points: [], width: 0, height: 0 };
let liveConnectionState = "connecting";
let liveWearState = "unknown";
let liveStream = null;
let liveRenderTimer = null;
let lastLiveRenderAt = 0;
let archiveSyncTimer = null;
let archiveSyncInFlight = false;

function formatChartTime(timestamp, includeSeconds = false) {
  const date = new Date(timestamp);
  const base = `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
  return includeSeconds ? `${base}:${pad2(date.getSeconds())}` : base;
}

export function workoutPresentation(window = {}) {
  const workoutType = String(window?.workoutType || window?.workout_type || "").toLowerCase();
  const planId = String(window?.planId || window?.plan_id || "").toLowerCase();
  if (workoutType === "strength") return { key: "strength", ...WORKOUT_PRESENTATION.strength };
  if (workoutType === "virtual_walk" || planId === "virtual-walk") {
    return { key: "walk", ...WORKOUT_PRESENTATION.walk };
  }
  if (planId === "free-ride") {
    return { key: "cardio", ...WORKOUT_PRESENTATION.cardio, label: "Cardio dodatkowe" };
  }
  return { key: "cardio", ...WORKOUT_PRESENTATION.cardio };
}

function renderWorkoutPeriods(windows) {
  if (!elements.workoutPeriods) return;
  elements.workoutPeriods.replaceChildren();
  elements.workoutPeriods.hidden = windows.length === 0;
  if (!windows.length) return;

  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const countLabel = windows.length === 1
    ? "1 sesja"
    : `${windows.length} ${windows.length >= 2 && windows.length <= 4 ? "sesje" : "sesji"}`;
  summary.textContent = `Treningi · ${countLabel} · ${formatChartTime(windows[0].actualStart)}–${formatChartTime(windows.at(-1).actualEnd)}`;
  summary.title = "Kliknij, aby zobaczyć typy oraz dokładne początki i końce treningów";

  const intervals = document.createElement("div");
  windows.forEach((window) => {
    const presentation = workoutPresentation(window);
    const item = document.createElement("span");
    const endLabel = window.isActive ? "w trakcie" : formatChartTime(window.actualEnd, true);
    const range = `${formatChartTime(window.actualStart, true)}–${endLabel}`;
    item.style.setProperty("--hr-period-color", presentation.color);
    item.textContent = `${presentation.label} · ${range}`;
    item.title = `${window.title || presentation.label}: ${range}`;
    intervals.appendChild(item);
  });
  details.append(summary, intervals);
  elements.workoutPeriods.append(details);
}

function renderSmartRingPeriods(samples) {
  if (!elements.ringPeriods) return;
  const phases = buildSmartRingOnlyPhases(samples);
  elements.ringPeriods.replaceChildren();
  elements.ringPeriods.hidden = phases.length === 0;
  if (!phases.length) return;
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const firstStart = formatChartTime(phases[0].start);
  const lastEnd = formatChartTime(phases.at(-1).end);
  const phaseCount = phases.length;
  const phaseLabel = phaseCount === 1
    ? "1 faza"
    : `${phaseCount} ${phaseCount >= 2 && phaseCount <= 4 ? "fazy" : "faz"}`;
  summary.textContent = `COLMI · ${phaseLabel} · ${firstStart}–${lastEnd}`;
  summary.title = "Kliknij, aby zobaczyć dokładne początki i końce faz COLMI";
  const intervals = document.createElement("div");
  phases.forEach((phase) => {
    const item = document.createElement("span");
    const range = phase.start === phase.end
      ? formatChartTime(phase.start)
      : `${formatChartTime(phase.start)}–${formatChartTime(phase.end)}`;
    item.textContent = `${range} · ${phase.sampleCount}`;
    item.title = `Faza pomiaru tylko przez COLMI Ring: ${range} (${phase.sampleCount} próbek)`;
    intervals.appendChild(item);
  });
  details.append(summary, intervals);
  elements.ringPeriods.append(details);
}

function setChartRange(nextRange) {
  const day = localDayRange(selectedDayKey());
  chartRange = {
    start: Math.max(day.start, Number(nextRange?.start) || day.start),
    end: Math.min(day.end, Number(nextRange?.end) || day.end),
  };
}

function chartFitPoints() {
  return [
    ...chartSamples,
    ...chartWorkoutWindows.flatMap((window) => [
      { timestamp: window.actualStart },
      { timestamp: window.actualEnd },
    ]),
  ];
}

function fitChartToData() {
  const day = localDayRange(selectedDayKey());
  chartRangeMode = "fit";
  setChartRange(fitHeartRateDataRange(chartFitPoints(), day.start, day.end));
  drawChart();
}

function showFullDay() {
  const day = localDayRange(selectedDayKey());
  chartRangeMode = "full";
  setChartRange(day);
  drawChart();
}

function zoomChart(factor) {
  const day = localDayRange(selectedDayKey());
  chartRangeMode = "manual";
  setChartRange(zoomHeartRateRange(chartRange, factor, day.start, day.end));
  drawChart();
}

function drawChart(samples = chartSamples) {
  const canvas = elements.chart;
  if (!(canvas instanceof HTMLCanvasElement)) return;
  chartSamples = samples;
  renderWorkoutPeriods(chartWorkoutWindows);
  renderSmartRingPeriods(samples);
  const day = localDayRange(selectedDayKey());
  if (!chartRange) setChartRange(fitHeartRateDataRange(chartFitPoints(), day.start, day.end));
  const width = Math.max(320, Math.round(canvas.clientWidth || 1200));
  const height = Math.max(240, Math.round(canvas.clientHeight || 320));
  const scale = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, width, height);

  const padding = { top: 24, right: 20, bottom: 36, left: 48 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const range = chartRange || day;
  const maximumPoints = Math.max(600, Math.min(2400, Math.round(width * 1.5)));
  const model = buildHeartRateChartModel(samples, range.start, range.end, maximumPoints);
  const yFor = (bpm) => padding.top
    + (1 - (bpm - model.minimum) / (model.maximum - model.minimum)) * plotHeight;
  const xFor = (ratio) => padding.left + ratio * plotWidth;
  const xForTimestamp = (timestamp) => xFor((timestamp - range.start) / (range.end - range.start));
  const visibleWorkoutWindows = chartWorkoutWindows.filter((window) => (
    window.actualEnd >= range.start && window.actualStart <= range.end
  ));
  const visibleRingPhases = buildSmartRingOnlyPhases(samples).filter((phase) => (
    phase.end >= range.start && phase.start <= range.end
  ));

  visibleRingPhases.forEach((phase) => {
    const x = xForTimestamp(Math.max(range.start, phase.start));
    const right = xForTimestamp(Math.min(range.end, phase.end));
    const phaseWidth = Math.max(2, right - x);
    context.fillStyle = "rgba(167,139,250,.045)";
    context.fillRect(x, padding.top, phaseWidth, plotHeight);
    context.fillStyle = "rgba(196,181,253,.55)";
    context.fillRect(x, padding.top, phaseWidth, 2);
    context.fillRect(x, padding.top, 1, 7);
    context.fillRect(x + phaseWidth - 1, padding.top, 1, 7);
  });

  visibleWorkoutWindows.forEach((window) => {
    const presentation = workoutPresentation(window);
    const visibleStart = Math.max(range.start, window.actualStart);
    const visibleEnd = Math.min(range.end, window.actualEnd);
    const x = xForTimestamp(visibleStart);
    const right = xForTimestamp(visibleEnd);
    context.fillStyle = presentation.fill;
    context.fillRect(x, padding.top, Math.max(1, right - x), plotHeight);
    context.fillStyle = presentation.color;
    context.globalAlpha = .78;
    context.fillRect(x, padding.top, Math.max(1, right - x), 2);
    context.globalAlpha = 1;
  });

  context.font = "11px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.fillStyle = "#8b8b91";
  context.strokeStyle = "rgba(255,255,255,.08)";
  context.lineWidth = 1;

  for (let index = 0; index <= 4; index += 1) {
    const ratio = index / 4;
    const y = padding.top + ratio * plotHeight;
    const value = Math.round(model.maximum - ratio * (model.maximum - model.minimum));
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
    context.fillText(String(value), 8, y + 4);
  }

  for (let index = 0; index <= 4; index += 1) {
    const ratio = index / 4;
    const x = xFor(ratio);
    const tickTimestamp = range.start + ratio * (range.end - range.start);
    context.beginPath();
    context.moveTo(x, padding.top);
    context.lineTo(x, height - padding.bottom);
    context.stroke();
    context.textAlign = index === 0 ? "left" : index === 4 ? "right" : "center";
    context.fillText(
      formatChartTime(tickTimestamp, range.end - range.start < 10 * 60 * 1000),
      x,
      height - 10,
    );
  }
  context.textAlign = "left";

  if (elements.chartWindow) {
    const includeSeconds = range.end - range.start < 10 * 60 * 1000;
    elements.chartWindow.textContent = `${formatChartTime(range.start, includeSeconds)}–${formatChartTime(range.end, includeSeconds)}`;
  }
  if (elements.zoomIn) elements.zoomIn.disabled = range.end - range.start <= MIN_CHART_WINDOW_MS + 1;
  if (elements.zoomOut) elements.zoomOut.disabled = range.start <= day.start && range.end >= day.end;

  elements.chartEmpty.hidden = model.points.length > 0;
  const renderPoints = model.points.map((point) => {
    const workoutActive = isTimestampInWorkout(point.timestamp, chartWorkoutWindows);
    return {
      ...point,
      workoutActive,
      zone: getHrZone(point.bpm, workoutActive),
      pixelX: xFor(point.x),
      pixelY: yFor(point.bpm),
    };
  });
  chartRenderState = { points: renderPoints, width, height, padding };

  context.lineWidth = 2.4;
  context.lineJoin = "round";
  context.lineCap = "round";
  let activeColor = null;
  let pathOpen = false;
  const strokeActivePath = () => {
    if (!pathOpen) return;
    context.strokeStyle = activeColor;
    context.stroke();
    pathOpen = false;
  };
  renderPoints.slice(1).forEach((point, index) => {
    const previous = renderPoints[index];
    if (point.timestamp - previous.timestamp > CHART_GAP_MS) {
      strokeActivePath();
      activeColor = null;
      return;
    }
    if (!pathOpen || activeColor !== point.zone.color) {
      strokeActivePath();
      activeColor = point.zone.color;
      context.beginPath();
      context.moveTo(previous.pixelX, previous.pixelY);
      pathOpen = true;
    }
    context.lineTo(point.pixelX, point.pixelY);
  });
  strokeActivePath();

  renderPoints.filter(isSmartRingHeartRateSample).forEach((point) => {
    context.beginPath();
    context.arc(point.pixelX, point.pixelY, 3.2, 0, Math.PI * 2);
    context.strokeStyle = "rgba(196,181,253,.8)";
    context.lineWidth = 1.2;
    context.stroke();
  });

  const latest = renderPoints.at(-1);
  if (latest) {
    context.beginPath();
    context.arc(latest.pixelX, latest.pixelY, 4.5, 0, Math.PI * 2);
    context.fillStyle = "#fff";
    context.fill();
    context.beginPath();
    context.arc(latest.pixelX, latest.pixelY, 2.7, 0, Math.PI * 2);
    context.fillStyle = latest.zone.color;
    context.fill();
  }
}

function hideChartTooltip() {
  if (elements.chartTooltip) elements.chartTooltip.hidden = true;
}

function showChartTooltip(event) {
  if (!elements.chartTooltip || !chartRenderState.points.length) return hideChartTooltip();
  const canvas = elements.chart;
  const rect = canvas.getBoundingClientRect();
  const pointerX = event.clientX - rect.left;
  const pointerY = event.clientY - rect.top;
  const nearest = chartRenderState.points.reduce((best, point) => {
    const distance = Math.hypot(point.pixelX - pointerX, point.pixelY - pointerY);
    return !best || distance < best.distance ? { point, distance } : best;
  }, null);
  if (!nearest || nearest.distance > 24) return hideChartTooltip();

  const { point } = nearest;
  elements.chartTooltip.style.setProperty("--hr-zone-color", point.zone.color);
  elements.tooltipTime.textContent = formatHeartRateTimestamp(point.timestamp);
  elements.tooltipBpm.textContent = `${point.bpm} BPM`;
  elements.tooltipSource.textContent = `Źródło · ${point.sourceLabel || "Smartwatch"}`;
  elements.tooltipMode.textContent = point.workoutActive
    ? "Tryb sportowy · aktywny trening"
    : "Tryb codzienny · poza treningiem";
  elements.tooltipZone.textContent = point.zone.label;
  elements.tooltipDescription.textContent = point.zone.description || "";
  elements.tooltipDescription.hidden = !point.zone.description;
  elements.chartTooltip.hidden = false;

  const tooltipWidth = Math.min(310, rect.width - 24);
  const left = Math.max(8, Math.min(rect.width - tooltipWidth - 8, pointerX + 16));
  const estimatedHeight = point.zone.description ? 150 : 92;
  const top = Math.max(8, Math.min(rect.height - estimatedHeight - 8, pointerY + 14));
  elements.chartTooltip.style.left = `${left}px`;
  elements.chartTooltip.style.top = `${top}px`;
}

function updateLiveIndicator() {
  if (!elements.liveIndicator || !elements.liveLabel) return;
  const state = selectedDayKey() === localDayKey()
    ? liveWearState === "off_wrist" ? "off_wrist" : liveConnectionState
    : "past";
  const labels = {
    live: "Na żywo",
    off_wrist: "Zegarek zdjęty",
    connecting: "Łączenie…",
    reconnecting: "Ponowne łączenie…",
    unsupported: "SSE niedostępne",
    past: "Archiwum",
  };
  elements.liveIndicator.dataset.state = state;
  elements.liveLabel.textContent = labels[state] || labels.connecting;
}

function setLiveConnectionState(state) {
  liveConnectionState = state;
  updateLiveIndicator();
}

function syncDayUi() {
  const dayKey = selectedDayKey();
  const date = dateFromDayKey(dayKey);
  const heading = dayHeadingFormatter.format(date);
  elements.chartDay.textContent = heading;
  elements.nextDay.disabled = dayKey >= localDayKey();
  document.title = `Historia HR — ${dayKey}`;
  const url = new URL(window.location.href);
  url.searchParams.set("day", dayKey);
  window.history.replaceState(window.history.state, "", url);
  updateLiveIndicator();
}

let activeRequest = null;

function extendActiveWorkoutWindow(sample) {
  const timestamp = Number(sample?.timestamp);
  const status = String(sample?.status || "").toLowerCase();
  const activeWindow = chartWorkoutWindows.find((window) => window.isActive);
  if (!activeWindow || !Number.isFinite(timestamp)) return false;
  activeWindow.actualEnd = Math.max(Number(activeWindow.actualEnd) || timestamp, timestamp);
  activeWindow.end = Math.max(Number(activeWindow.end) || timestamp, timestamp);
  if (status === "finished") activeWindow.isActive = false;
  return true;
}

function renderLiveView({ includeRows = false } = {}) {
  if (chartRangeMode === "fit") {
    const day = localDayRange(selectedDayKey());
    setChartRange(fitHeartRateDataRange(chartFitPoints(), day.start, day.end));
  }
  renderSummary(chartSamples, chartWorkoutWindows);
  if (includeRows) renderRows(chartSamples);
  drawChart();
  lastLiveRenderAt = performance.now();
}

function scheduleLiveRender({ immediate = false } = {}) {
  if (liveRenderTimer !== null) return;
  const elapsed = performance.now() - lastLiveRenderAt;
  const delay = immediate ? 0 : Math.max(0, LIVE_RENDER_INTERVAL_MS - elapsed);
  liveRenderTimer = window.setTimeout(() => {
    liveRenderTimer = null;
    renderLiveView();
  }, delay);
}

async function syncRecentArchiveAndWorkoutState() {
  if (archiveSyncInFlight || selectedDayKey() !== localDayKey()) return;
  archiveSyncInFlight = true;
  const requestedDay = selectedDayKey();
  const day = localDayRange(requestedDay);
  const latestTimestamp = Number(chartSamples[0]?.timestamp);
  const recentFrom = Math.max(
    day.start,
    Number.isFinite(latestTimestamp)
      ? latestTimestamp - RECENT_ARCHIVE_LOOKBACK_MS
      : Date.now() - RECENT_ARCHIVE_LOOKBACK_MS,
  );
  try {
    const [response, workoutState] = await Promise.all([
      fetch(buildRequestUrl({
        from: recentFrom,
        to: day.end,
        limit: RECENT_ARCHIVE_LIMIT,
      }), { cache: "no-store" }),
      loadWorkoutState(),
    ]);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    if (selectedDayKey() !== requestedDay) return;
    chartSamples = mergeArchivedHeartRateSamples(
      chartSamples,
      Array.isArray(payload?.samples) ? payload.samples : [],
    );
    if (workoutState.available) {
      chartWorkoutWindows = buildWorkoutWindows(workoutState.sessions, day.start, day.end);
    }
    renderLiveView({ includeRows: Boolean(document.querySelector(".hr-history-raw-details[open]")) });
  } catch {
    // The SSE view remains useful; the next periodic sync retries the archive metadata.
  } finally {
    archiveSyncInFlight = false;
  }
}

function handleLiveTelemetry(payload) {
  if (payload?.wear_state === "off_wrist") {
    liveWearState = "off_wrist";
    chartSamples = filterUnwornHeartRateSamples(chartSamples);
    updateLiveIndicator();
    scheduleLiveRender({ immediate: true });
    return;
  }
  const sample = createLiveHeartRateSample(payload);
  if (!sample || localDayKey(new Date(sample.timestamp)) !== selectedDayKey()) return;
  liveWearState = "worn";
  updateLiveIndicator();
  chartSamples = applySmartwatchPriority(compareHeartRateSamples(sample, chartSamples[0]) <= 0
    ? [sample, ...chartSamples]
    : [sample, ...chartSamples].sort(compareHeartRateSamples));
  const extendedWorkout = extendActiveWorkoutWindow(sample);
  const status = String(sample.status || "").toLowerCase();
  if ((!extendedWorkout && ["running", "paused"].includes(status)) || status === "finished") {
    syncRecentArchiveAndWorkoutState();
  }
  scheduleLiveRender();
}

function startLiveStream() {
  if (typeof window.EventSource !== "function") {
    setLiveConnectionState("unsupported");
    return;
  }
  liveStream?.close();
  setLiveConnectionState("connecting");
  liveStream = new window.EventSource(STREAM_URL);
  liveStream.onopen = () => setLiveConnectionState("live");
  liveStream.addEventListener("telemetry", (event) => {
    try {
      handleLiveTelemetry(JSON.parse(event.data));
    } catch {}
  });
  liveStream.onerror = () => setLiveConnectionState("reconnecting");
}

async function loadHistory() {
  const loadStartedAt = Date.now();
  activeRequest?.abort();
  activeRequest = new AbortController();
  syncDayUi();
  elements.refresh.disabled = true;
  elements.status.dataset.tone = "loading";
  elements.status.textContent = "Ładuję historię HR…";

  try {
    const [response, workoutState] = await Promise.all([
      fetch(buildRequestUrl(), {
        cache: "no-store",
        signal: activeRequest.signal,
      }),
      loadWorkoutState(activeRequest.signal),
    ]);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    const samples = filterUnwornHeartRateSamples(
      Array.isArray(payload?.samples) ? payload.samples : [],
    );
    const pendingLiveSamples = chartSamples.filter((sample) => (
      Number(sample.received_at) >= loadStartedAt
      && localDayKey(new Date(Number(sample.timestamp))) === selectedDayKey()
    ));
    chartSamples = mergeArchivedHeartRateSamples(pendingLiveSamples, samples);
    const day = localDayRange(selectedDayKey());
    chartWorkoutWindows = buildWorkoutWindows(workoutState.sessions, day.start, day.end);
    renderSummary(chartSamples, chartWorkoutWindows);
    if (elements.rawDetails?.open) renderRows(chartSamples);
    else {
      elements.rows.replaceChildren();
      elements.empty.hidden = chartSamples.length > 0;
      updateTableSummary(chartSamples.length);
    }
    chartRange = null;
    chartRangeMode = "fit";
    hideChartTooltip();
    drawChart(chartSamples);
    elements.status.dataset.tone = "ready";
    const tableNote = chartSamples.length > TABLE_ROW_LIMIT
      ? ` Tabela pokazuje najnowsze ${TABLE_ROW_LIMIT}.`
      : "";
    const ringSampleCount = chartSamples.filter(isSmartRingHeartRateSample).length;
    const sourceNote = ringSampleCount
      ? ` COLMI uzupełnił ${ringSampleCount} próbek w minutach bez danych smartwatcha.`
      : "";
    const workoutNote = workoutState.available
      ? ` Okna treningowe: ${chartWorkoutWindows.length}.`
      : " Nie udało się pobrać stanu treningów — zastosowano tylko tryb codzienny.";
    elements.status.textContent = chartSamples.length
      ? `Wczytano ${chartSamples.length} próbek z wybranego dnia.${sourceNote}${workoutNote}${tableNote}`
      : "Brak danych dla wybranego dnia.";
  } catch (error) {
    if (error?.name === "AbortError") return;
    chartWorkoutWindows = [];
    chartSamples = [];
    renderSummary([], []);
    renderRows([]);
    chartRange = null;
    hideChartTooltip();
    drawChart([]);
    elements.status.dataset.tone = "error";
    elements.status.textContent = `Nie udało się wczytać historii: ${String(error?.message || error)}`;
  } finally {
    elements.refresh.disabled = false;
    updateLiveIndicator();
  }
}

function selectDay(dayKey) {
  elements.day.value = dayKey;
  loadHistory();
}

elements.refresh?.addEventListener("click", loadHistory);
elements.day?.addEventListener("change", loadHistory);
elements.previousDay?.addEventListener("click", () => selectDay(shiftDayKey(selectedDayKey(), -1)));
elements.nextDay?.addEventListener("click", () => {
  if (!elements.nextDay.disabled) selectDay(shiftDayKey(selectedDayKey(), 1));
});
elements.today?.addEventListener("click", () => selectDay(localDayKey()));
elements.zoomIn?.addEventListener("click", () => zoomChart(.5));
elements.zoomOut?.addEventListener("click", () => zoomChart(2));
elements.fitData?.addEventListener("click", fitChartToData);
elements.fullDay?.addEventListener("click", showFullDay);
elements.chart?.addEventListener("pointermove", showChartTooltip);
elements.chart?.addEventListener("pointerleave", hideChartTooltip);
elements.rawDetails?.addEventListener("toggle", () => {
  if (elements.rawDetails.open) renderRows(chartSamples);
  else elements.rows.replaceChildren();
});

if (elements.rows) {
  renderZoneLegend();
  const requestedDay = new URLSearchParams(window.location.search).get("day");
  elements.day.value = dateFromDayKey(requestedDay) ? requestedDay : localDayKey();
  new ResizeObserver(() => drawChart()).observe(elements.chart);
  startLiveStream();
  archiveSyncTimer = window.setInterval(syncRecentArchiveAndWorkoutState, ARCHIVE_SYNC_INTERVAL_MS);
  window.addEventListener("pagehide", () => {
    liveStream?.close();
    if (archiveSyncTimer !== null) window.clearInterval(archiveSyncTimer);
    if (liveRenderTimer !== null) window.clearTimeout(liveRenderTimer);
  }, { once: true });
  loadHistory();
}
