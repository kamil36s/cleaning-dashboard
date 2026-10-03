const RING_HISTORY_ENDPOINT = "/api/ring/history?limit=10000";
const HEALTH_CONNECT_HISTORY_ENDPOINT = "/api/health-connect/history";
const HEALTH_CONNECT_LATEST_ENDPOINT = "/api/health-connect/latest";
const MINIMUM_NIGHT_MINUTES = 30;
const HOUR_MS = 60 * 60 * 1000;

function timestamp(value) {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function validWindow(start, end) {
  const startTime = timestamp(start);
  const endTime = timestamp(end);
  return startTime !== null && endTime !== null && endTime > startTime
    ? { startTime, endTime }
    : null;
}

function isAwakeStage(stage, kind) {
  if (kind === "ring") return String(stage?.stage || "").toLowerCase() === "awake";
  return [1, 3].includes(Number(stage?.type));
}

function movementAt(time, stages, kind) {
  const stage = (stages || []).find((candidate) => {
    const start = timestamp(candidate?.startUtc ?? candidate?.start);
    const end = timestamp(candidate?.endUtc ?? candidate?.end);
    return start !== null && end !== null && time >= start && time <= end;
  });
  return stage && isAwakeStage(stage, kind) ? 1 : 0;
}

function normalizeHeartRate(records, stages, kind) {
  return (Array.isArray(records) ? records : []).map((record) => {
    const valueTimestamp = record?.timestampUtc ?? record?.time ?? record?.timestamp;
    const time = timestamp(valueTimestamp);
    return {
      timestamp: valueTimestamp,
      bpm: Number(record?.bpm),
      movement: time === null ? 0 : movementAt(time, stages, kind),
      manufacturer: record?.manufacturer,
      model: record?.model,
      dataOrigin: record?.dataOrigin ?? record?.data_origin,
    };
  });
}

function withinWindow(records, startTime, endTime) {
  return records.filter((record) => {
    const time = timestamp(record.timestamp);
    return time !== null && time >= startTime && time <= endTime;
  });
}

function watchName(records = []) {
  const identified = records.find((record) => record?.manufacturer || record?.model);
  const name = [identified?.manufacturer, identified?.model].filter(Boolean).join(" ").trim();
  return name || "Smartwatch · Health Connect";
}

function warsawParts(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type) => parts.find((item) => item.type === type)?.value || "";
  return {
    day: `${part("year")}-${part("month")}-${part("day")}`,
    hour: Number(part("hour")),
  };
}

function warsawDay(value) {
  return warsawParts(value)?.day || "";
}

/**
 * A night is assigned to the day on which the user wakes up. Before-midnight
 * partial snapshots are therefore kept with the following morning instead of
 * appearing as a second, short night on the previous day.
 */
export function sleepNightKey(start, end) {
  const startTime = timestamp(start);
  const startParts = warsawParts(startTime);
  if (startTime === null || !startParts) return warsawDay(end);
  if (startParts.hour >= 18) return warsawDay(startTime + 12 * HOUR_MS);
  return warsawDay(end) || startParts.day;
}

/**
 * Older parser versions anchored some cross-midnight records a day too late.
 * The created-at check also catches their before-midnight partial snapshots.
 */
export function normalizeRingSleepWindow(night = {}) {
  const window = validWindow(night.sleepStartUtc, night.sleepEndUtc);
  if (!window) return null;
  const sleepDate = String(night.sleepDate || "");
  const createdTime = timestamp(night.createdAt);
  const recordedInFuture = createdTime !== null
    && window.startTime - createdTime > 12 * HOUR_MS;
  const crossMidnightLegacyShift = sleepDate
    && warsawDay(window.startTime) === sleepDate
    && warsawDay(window.endTime) !== sleepDate;
  const shiftMs = recordedInFuture || crossMidnightLegacyShift ? -24 * HOUR_MS : 0;
  return {
    startTime: window.startTime + shiftMs,
    endTime: window.endTime + shiftMs,
    start: new Date(window.startTime + shiftMs).toISOString(),
    end: new Date(window.endTime + shiftMs).toISOString(),
    shiftMs,
  };
}

function shiftStages(stages, shiftMs) {
  return (Array.isArray(stages) ? stages : []).map((stage) => {
    if (!shiftMs) return stage;
    const shifted = { ...stage };
    ["startUtc", "endUtc"].forEach((key) => {
      const value = timestamp(stage?.[key]);
      if (value !== null) shifted[key] = new Date(value + shiftMs).toISOString();
    });
    return shifted;
  });
}

function isBetterRingCandidate(candidate, current) {
  if (!current) return true;
  const candidateCreated = timestamp(candidate.night?.createdAt) || 0;
  const currentCreated = timestamp(current.night?.createdAt) || 0;
  if (candidateCreated !== currentCreated) return candidateCreated > currentCreated;
  const candidateMinutes = Number(candidate.night?.totalMinutes) || 0;
  const currentMinutes = Number(current.night?.totalMinutes) || 0;
  if (candidateMinutes !== currentMinutes) return candidateMinutes > currentMinutes;
  return candidate.window.endTime > current.window.endTime;
}

export function createRingSleepDatasets(history = {}) {
  const bestByNight = new Map();
  (Array.isArray(history?.sleep) ? history.sleep : []).forEach((night) => {
    const window = normalizeRingSleepWindow(night);
    if (!window) return;
    const nightKey = sleepNightKey(window.start, window.end);
    if (!nightKey) return;
    const candidate = { night, window };
    if (isBetterRingCandidate(candidate, bestByNight.get(nightKey))) {
      bestByNight.set(nightKey, candidate);
    }
  });

  return Array.from(bestByNight.entries()).map(([nightKey, { night, window }]) => {
    const stages = shiftStages(night.stages, window.shiftMs);
    const ringHeartRate = withinWindow(
      normalizeHeartRate(history?.heartRate, stages, "ring"),
      window.startTime,
      window.endTime,
    );
    const watchHeartRate = withinWindow(
      normalizeHeartRate(history?.watchHeartRateReference, stages, "ring"),
      window.startTime,
      window.endTime,
    );
    const useRingHeartRate = ringHeartRate.length > 0;
    const heartRateRecords = useRingHeartRate ? ringHeartRate : watchHeartRate;
    const heartRateSource = useRingHeartRate
      ? "COLMI Ring"
      : (watchHeartRate.length ? watchName(watchHeartRate) : "brak próbek");

    return {
      id: `${nightKey}-ring`,
      nightKey,
      sourceKind: "ring",
      sourceLabel: "COLMI Ring",
      sourceDetail: `Sen: COLMI Ring · tętno: ${heartRateSource}`,
      heartRateSource,
      recordedAt: night.createdAt || window.end,
      sleepWindow: {
        start: window.start,
        end: window.end,
        totalMinutes: Number(night.totalMinutes),
      },
      stages,
      samples: heartRateRecords,
    };
  }).sort((left, right) => (
    (timestamp(right.sleepWindow.end) || 0) - (timestamp(left.sleepWindow.end) || 0)
  ));
}

export function createRingSleepDataset(history = {}) {
  return createRingSleepDatasets(history)[0] || null;
}

function snapshotsFromResponse(response = {}) {
  if (Array.isArray(response?.snapshots)) return response.snapshots;
  if (response?.snapshot) return [response.snapshot];
  return response?.payload || response?.sleep ? [response] : [];
}

function watchDataset(snapshot, session) {
  const payload = snapshot?.payload || snapshot;
  const window = validWindow(session?.start, session?.end);
  if (!window) return null;
  const totalMinutes = Math.round((window.endTime - window.startTime) / 60_000);
  if (totalMinutes < MINIMUM_NIGHT_MINUTES) return null;
  const stages = Array.isArray(session.stages) ? session.stages : [];
  const normalizedHeartRate = normalizeHeartRate(payload?.heart_rate?.samples, stages, "watch");
  const heartRate = withinWindow(normalizedHeartRate, window.startTime, window.endTime);
  const sourceLabel = watchName([session, ...heartRate]);
  const nightKey = sleepNightKey(session.start, session.end);

  return {
    id: `${nightKey}-watch`,
    nightKey,
    sourceKind: "watch",
    sourceLabel,
    sourceDetail: `Sen: ${sourceLabel} · tętno: ${heartRate.length ? sourceLabel : "brak próbek"}`,
    heartRateSource: heartRate.length ? sourceLabel : "brak próbek",
    recordedAt: snapshot?.received_at || snapshot?.receivedAt || session.end,
    sleepWindow: {
      start: session.start,
      end: session.end,
      totalMinutes,
    },
    stages,
    samples: heartRate,
  };
}

function isBetterWatchCandidate(candidate, current) {
  if (!current) return true;
  const candidateMinutes = Number(candidate.sleepWindow?.totalMinutes) || 0;
  const currentMinutes = Number(current.sleepWindow?.totalMinutes) || 0;
  if (candidateMinutes !== currentMinutes) return candidateMinutes > currentMinutes;
  if (candidate.samples.length !== current.samples.length) {
    return candidate.samples.length > current.samples.length;
  }
  return (timestamp(candidate.recordedAt) || 0) > (timestamp(current.recordedAt) || 0);
}

export function createWatchSleepDatasets(response = {}) {
  const bestByNight = new Map();
  snapshotsFromResponse(response).forEach((snapshot) => {
    const payload = snapshot?.payload || snapshot;
    const sessions = Array.isArray(payload?.sleep?.sessions) ? payload.sleep.sessions : [];
    sessions.forEach((session) => {
      const candidate = watchDataset(snapshot, session);
      if (!candidate?.nightKey) return;
      if (isBetterWatchCandidate(candidate, bestByNight.get(candidate.nightKey))) {
        bestByNight.set(candidate.nightKey, candidate);
      }
    });
  });
  return Array.from(bestByNight.values()).sort((left, right) => (
    (timestamp(right.sleepWindow.end) || 0) - (timestamp(left.sleepWindow.end) || 0)
  ));
}

export function createWatchSleepDataset(response = {}) {
  return createWatchSleepDatasets(response)[0] || null;
}

/**
 * A Health Connect sleep session proves that the watch recorded that night, so
 * it wins over the ring. Ring heart rate remains a useful fallback when Health
 * Connect contains the session but no watch BPM samples.
 */
export function mergeSleepDatasets(ringDatasets = [], watchDatasets = []) {
  const ringByNight = new Map(ringDatasets.map((dataset) => [dataset.nightKey, dataset]));
  const watchByNight = new Map(watchDatasets.map((dataset) => [dataset.nightKey, dataset]));
  const nightKeys = new Set([...ringByNight.keys(), ...watchByNight.keys()]);

  return Array.from(nightKeys).map((nightKey) => {
    const ring = ringByNight.get(nightKey);
    const watch = watchByNight.get(nightKey);
    if (!watch) return ring;
    if (!ring || watch.samples.length) return watch;
    return {
      ...watch,
      samples: ring.samples,
      heartRateSource: ring.samples.length ? "COLMI Ring (uzupełnienie)" : "brak próbek",
      sourceDetail: `Sen: ${watch.sourceLabel} · tętno: ${ring.samples.length ? "COLMI Ring (uzupełnienie)" : "brak próbek"}`,
    };
  }).filter(Boolean).sort((left, right) => (
    (timestamp(right?.sleepWindow?.end) || 0) - (timestamp(left?.sleepWindow?.end) || 0)
  ));
}

export function selectLatestSleepDataset(datasets = []) {
  return datasets
    .filter(Boolean)
    .sort((left, right) => {
      const endDifference = (timestamp(right?.sleepWindow?.end) || 0)
        - (timestamp(left?.sleepWindow?.end) || 0);
      if (endDifference) return endDifference;
      return Number(right?.sourceKind === "watch") - Number(left?.sourceKind === "watch");
    })[0] || null;
}

async function fetchJson(url, signal) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

async function fetchHealthHistory(signal) {
  try {
    return await fetchJson(HEALTH_CONNECT_HISTORY_ENDPOINT, signal);
  } catch (historyError) {
    if (signal?.aborted) throw historyError;
    return fetchJson(HEALTH_CONNECT_LATEST_ENDPOINT, signal);
  }
}

function latestHealthSync(response = {}) {
  if (response?.latestReceivedAt) return response.latestReceivedAt;
  return snapshotsFromResponse(response).reduce((latest, snapshot) => {
    const receivedAt = snapshot?.received_at || snapshot?.receivedAt;
    return (timestamp(receivedAt) || 0) > (timestamp(latest) || 0) ? receivedAt : latest;
  }, null);
}

export async function loadSleepHistoryData({ signal } = {}) {
  const [ringResult, watchResult] = await Promise.allSettled([
    fetchJson(RING_HISTORY_ENDPOINT, signal),
    fetchHealthHistory(signal),
  ]);
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");

  const ringDatasets = ringResult.status === "fulfilled"
    ? createRingSleepDatasets(ringResult.value)
    : [];
  const watchDatasets = watchResult.status === "fulfilled"
    ? createWatchSleepDatasets(watchResult.value)
    : [];
  const datasets = mergeSleepDatasets(ringDatasets, watchDatasets);
  if (datasets.length) {
    return {
      datasets,
      latest: datasets[0],
      sources: {
        ring: { available: ringDatasets.length > 0 },
        watch: {
          available: watchDatasets.length > 0,
          lastSync: watchResult.status === "fulfilled" ? latestHealthSync(watchResult.value) : null,
        },
      },
    };
  }

  const reasons = [ringResult, watchResult]
    .filter((result) => result.status === "rejected")
    .map((result) => String(result.reason?.message || result.reason));
  throw new Error(reasons.join(" · ") || "Brak nocy w danych ringa i Health Connect");
}

export async function loadLatestSleepData(options) {
  return (await loadSleepHistoryData(options)).latest;
}

export async function loadLatestSleepSamples(options) {
  return (await loadLatestSleepData(options)).samples;
}
