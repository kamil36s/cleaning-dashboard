const MINUTE_MS = 60_000;

const DEFAULTS = Object.freeze({
  movementThreshold: 0.1,
  onsetSustainMinutes: 10,
  rhrWindowMinutes: 15,
  wakeLookbackMinutes: 15,
  wakeSustainMinutes: 20,
  minimumSleepMinutes: 30,
  heartRateJumpRatio: 0.15,
  restlessSpikeCount: 3,
});

function mean(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function toIso(time) {
  return new Date(time).toISOString();
}

/**
 * Cleans the BLE payload without changing its public shape. Invalid readings are
 * ignored and duplicate timestamps are replaced by the last reading received.
 */
export function normalizeSleepSamples(input) {
  if (!Array.isArray(input)) return [];

  const byTimestamp = new Map();
  input.forEach((sample) => {
    const time = Date.parse(sample?.timestamp);
    const bpm = Number(sample?.bpm);
    const movement = Number(sample?.movement);
    if (
      !Number.isFinite(time)
      || !Number.isFinite(bpm)
      || bpm < 30
      || bpm > 240
      || !Number.isFinite(movement)
      || movement < 0
    ) return;

    byTimestamp.set(time, {
      timestamp: toIso(time),
      time,
      bpm,
      movement,
    });
  });

  return Array.from(byTimestamp.values()).sort((a, b) => a.time - b.time);
}

function findSleepStart(samples, dailyAverageBpm, config) {
  let sequenceStart = -1;

  for (let index = 0; index < samples.length; index += 1) {
    const sample = samples[index];
    const isSleepLike = sample.bpm < dailyAverageBpm
      && sample.movement <= config.movementThreshold;

    if (!isSleepLike) {
      sequenceStart = -1;
      continue;
    }

    if (sequenceStart < 0) sequenceStart = index;
    const duration = sample.time - samples[sequenceStart].time;
    if (duration >= config.onsetSustainMinutes * MINUTE_MS) {
      return sequenceStart;
    }
  }

  return -1;
}

function previousWindow(samples, index, minutes) {
  const cutoff = samples[index].time - minutes * MINUTE_MS;
  const result = [];
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (samples[cursor].time < cutoff) break;
    result.unshift(samples[cursor]);
  }
  return result;
}

function isHeartRateSpike(samples, index, config) {
  const previous = previousWindow(samples, index, config.wakeLookbackMinutes);
  const baseline = mean(previous.map((sample) => sample.bpm));
  return Number.isFinite(baseline)
    && samples[index].bpm >= baseline * (1 + config.heartRateJumpRatio);
}

function hasMovementIncrease(samples, index, config) {
  const previous = previousWindow(samples, index, config.wakeLookbackMinutes);
  const baseline = mean(previous.map((sample) => sample.movement)) ?? 0;
  return samples[index].movement > config.movementThreshold
    && samples[index].movement > baseline;
}

function hasSustainedWakeMovement(samples, index, config) {
  const end = samples[index].time + config.wakeSustainMinutes * MINUTE_MS;
  const future = samples.slice(index).filter((sample) => sample.time <= end);
  if (future.length < 2) return true;
  const activeCount = future.filter(
    (sample) => sample.movement > config.movementThreshold,
  ).length;
  return activeCount / future.length >= 0.5;
}

function countGroupedSpikes(samples, startIndex, endIndex, config) {
  let count = 0;
  let lastSpikeTime = -Infinity;

  for (let index = Math.max(1, startIndex); index <= endIndex; index += 1) {
    if (!isHeartRateSpike(samples, index, config)) continue;
    if (samples[index].time - lastSpikeTime >= config.wakeLookbackMinutes * MINUTE_MS) {
      count += 1;
    }
    lastSpikeTime = samples[index].time;
  }

  return count;
}

function findWakeIndex(samples, sleepStartIndex, config) {
  const earliestWake = samples[sleepStartIndex].time
    + config.minimumSleepMinutes * MINUTE_MS;

  for (let index = sleepStartIndex + 1; index < samples.length; index += 1) {
    if (samples[index].time < earliestWake) continue;
    if (
      isHeartRateSpike(samples, index, config)
      && hasMovementIncrease(samples, index, config)
      && hasSustainedWakeMovement(samples, index, config)
    ) return index;
  }

  return samples.length - 1;
}

function calculateRhr(samples, startIndex, endIndex, config) {
  const durationMs = config.rhrWindowMinutes * MINUTE_MS;
  const minimumCoverageMs = durationMs * 0.8;
  let best = null;

  for (let start = startIndex; start <= endIndex; start += 1) {
    const windowEnd = samples[start].time + durationMs;
    if (windowEnd > samples[endIndex].time) break;

    const windowSamples = [];
    for (let cursor = start; cursor <= endIndex; cursor += 1) {
      if (samples[cursor].time > windowEnd) break;
      windowSamples.push(samples[cursor]);
    }

    const coverage = windowSamples.at(-1)?.time - windowSamples[0]?.time;
    if (windowSamples.length < 2 || coverage < minimumCoverageMs) continue;

    const averageBpm = mean(windowSamples.map((sample) => sample.bpm));
    if (!best || averageBpm < best.averageBpm) {
      best = {
        averageBpm,
        startTime: windowSamples[0].time,
        endTime: windowSamples.at(-1).time,
        sampleCount: windowSamples.length,
      };
    }
  }

  // Sparse devices may publish less often than every 15 minutes. In that case
  // retain a useful estimate and explicitly mark it as a fallback.
  if (!best) {
    const lowest = samples.slice(startIndex, endIndex + 1)
      .reduce((result, sample) => (!result || sample.bpm < result.bpm ? sample : result), null);
    return lowest ? {
      averageBpm: lowest.bpm,
      startTime: lowest.time,
      endTime: lowest.time,
      sampleCount: 1,
      isFallback: true,
    } : null;
  }

  return { ...best, isFallback: false };
}

export function createSleepInsight(analysis, restlessSpikeCount = DEFAULTS.restlessSpikeCount) {
  if (!analysis?.hasSleep) return "Za mało danych, aby ocenić regenerację.";
  if (!Number.isFinite(analysis.rhr) || !Number.isFinite(analysis.rhrAt)) {
    return "Sen zarejestrowany, ale za mało próbek tętna do oceny regeneracji.";
  }
  if (analysis.spikeCount >= restlessSpikeCount) {
    return "W nocy wystąpiło kilka wyraźnych skoków tętna.";
  }
  if (analysis.rhrAt <= analysis.sleepMidpoint) {
    return "Najniższe RHR pojawiło się w pierwszej połowie nocy.";
  }
  return "Najniższe RHR pojawiło się w drugiej połowie nocy.";
}

const WARSAW_CLOCK_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Warsaw",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function nightClockMinutes(value) {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return null;
  const parts = WARSAW_CLOCK_FORMATTER.formatToParts(new Date(time));
  const part = (type) => Number(parts.find((item) => item.type === type)?.value);
  const hour = part("hour");
  const minute = part("minute");
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null;
  const minutes = hour * 60 + minute;
  // Noon is the seam so that 23:50 and 00:10 remain 20 minutes apart.
  return minutes < 12 * 60 ? minutes + 24 * 60 : minutes;
}

function typicalClock(values) {
  const center = median(values);
  if (!Number.isFinite(center)) return { minutes: null, variabilityMinutes: null };
  const variability = mean(values.map((value) => Math.abs(value - center)));
  return {
    minutes: Math.round(center) % (24 * 60),
    variabilityMinutes: Math.round(variability),
  };
}

/**
 * Produces history-level statistics without changing or reclassifying any
 * source session. Device windows remain the source of truth for every night.
 */
export function analyzeSleepHistory(datasets, options = {}) {
  const targetMinMinutes = Number.isFinite(options.targetMinMinutes)
    ? options.targetMinMinutes
    : 7 * 60;
  const targetMaxMinutes = Number.isFinite(options.targetMaxMinutes)
    ? options.targetMaxMinutes
    : 9 * 60;
  const analyzed = (Array.isArray(datasets) ? datasets : []).map((dataset) => ({
    dataset,
    analysis: analyzeSleepData(dataset?.samples, { sleepWindow: dataset?.sleepWindow }),
  })).filter(({ analysis }) => analysis.hasSleep && Number.isFinite(analysis.durationMinutes));
  const chronological = analyzed.sort((left, right) => (
    Date.parse(left.analysis.sleepStart) - Date.parse(right.analysis.sleepStart)
  ));
  const durations = chronological.map(({ analysis }) => analysis.durationMinutes);
  const rhrs = chronological.map(({ analysis }) => analysis.rhr).filter(Number.isFinite);
  const startClock = typicalClock(chronological
    .map(({ analysis }) => nightClockMinutes(analysis.sleepStart))
    .filter(Number.isFinite));
  const wakeClock = typicalClock(chronological
    .map(({ analysis }) => nightClockMinutes(analysis.wakeTime))
    .filter(Number.isFinite));
  const targetNights = durations.filter(
    (duration) => duration >= targetMinMinutes && duration <= targetMaxMinutes,
  ).length;
  const longest = chronological.reduce((best, entry) => (
    !best || entry.analysis.durationMinutes > best.analysis.durationMinutes ? entry : best
  ), null);
  const recent = durations.slice(-7);
  const previous = durations.slice(Math.max(0, durations.length - 14), Math.max(0, durations.length - 7));
  const durationTrendMinutes = recent.length >= 3 && previous.length >= 3
    ? Math.round(mean(recent) - mean(previous))
    : null;
  const variabilityValues = [
    startClock.variabilityMinutes,
    wakeClock.variabilityMinutes,
  ].filter(Number.isFinite);

  return {
    nights: chronological.length,
    analyzed: chronological,
    averageDurationMinutes: durations.length ? Math.round(mean(durations)) : null,
    averageRhr: rhrs.length ? Math.round(mean(rhrs)) : null,
    rhrNights: rhrs.length,
    longest,
    targetNights,
    targetShare: durations.length ? Math.round((targetNights / durations.length) * 100) : null,
    typicalStartMinutes: startClock.minutes,
    typicalWakeMinutes: wakeClock.minutes,
    startVariabilityMinutes: startClock.variabilityMinutes,
    wakeVariabilityMinutes: wakeClock.variabilityMinutes,
    regularityMinutes: variabilityValues.length ? Math.round(mean(variabilityValues)) : null,
    recentAverageDurationMinutes: recent.length ? Math.round(mean(recent)) : null,
    recentNightCount: recent.length,
    durationTrendMinutes,
  };
}

/**
 * Detects one sleep interval and derives values used by the widget. The result
 * intentionally leaves room for future `hrv` and `stages` properties.
 */
export function analyzeSleepData(input, options = {}) {
  const config = { ...DEFAULTS, ...options };
  const samples = normalizeSleepSamples(input);
  const dailyAverageBpm = mean(samples.map((sample) => sample.bpm));
  const trustedStart = Date.parse(options?.sleepWindow?.start);
  const trustedEnd = Date.parse(options?.sleepWindow?.end);
  const hasTrustedWindow = Number.isFinite(trustedStart)
    && Number.isFinite(trustedEnd)
    && trustedEnd > trustedStart;

  if (hasTrustedWindow) {
    const sleepSamples = samples.filter(
      (sample) => sample.time >= trustedStart && sample.time <= trustedEnd,
    );
    const sleepStartIndex = samples.findIndex((sample) => sample.time >= trustedStart);
    let wakeIndex = -1;
    for (let index = samples.length - 1; index >= 0; index -= 1) {
      if (samples[index].time <= trustedEnd) {
        wakeIndex = index;
        break;
      }
    }
    const totalFromSource = Number(options.sleepWindow.totalMinutes);
    const durationMinutes = Number.isFinite(totalFromSource) && totalFromSource > 0
      ? Math.round(totalFromSource)
      : Math.round((trustedEnd - trustedStart) / MINUTE_MS);
    const rhrWindow = sleepStartIndex >= 0 && wakeIndex >= sleepStartIndex
      ? calculateRhr(samples, sleepStartIndex, wakeIndex, config)
      : null;
    const rhrAt = rhrWindow
      ? rhrWindow.startTime + (rhrWindow.endTime - rhrWindow.startTime) / 2
      : null;
    const spikeCount = sleepStartIndex >= 0 && wakeIndex >= sleepStartIndex
      ? countGroupedSpikes(samples, sleepStartIndex, wakeIndex, config)
      : 0;
    const analysis = {
      hasSleep: durationMinutes >= config.minimumSleepMinutes,
      samples,
      sleepSamples,
      dailyAverageBpm,
      sleepStart: toIso(trustedStart),
      wakeTime: toIso(trustedEnd),
      durationMinutes,
      sleepMidpoint: trustedStart + (trustedEnd - trustedStart) / 2,
      rhr: rhrWindow ? Math.round(rhrWindow.averageBpm) : null,
      rhrAt,
      rhrWindow: rhrWindow ? {
        start: toIso(rhrWindow.startTime),
        end: toIso(rhrWindow.endTime),
        sampleCount: rhrWindow.sampleCount,
        isFallback: rhrWindow.isFallback,
      } : null,
      spikeCount,
      trustedSleepWindow: true,
    };
    analysis.insight = createSleepInsight(analysis, config.restlessSpikeCount);
    return analysis;
  }

  if (samples.length < 3 || !Number.isFinite(dailyAverageBpm)) {
    return {
      hasSleep: false,
      samples,
      dailyAverageBpm,
      insight: createSleepInsight(null),
    };
  }

  const sleepStartIndex = findSleepStart(samples, dailyAverageBpm, config);
  if (sleepStartIndex < 0) {
    return {
      hasSleep: false,
      samples,
      dailyAverageBpm,
      insight: createSleepInsight(null),
    };
  }

  const wakeIndex = findWakeIndex(samples, sleepStartIndex, config);
  const sleepStartTime = samples[sleepStartIndex].time;
  const wakeTime = samples[wakeIndex].time;
  const durationMinutes = Math.max(0, Math.round((wakeTime - sleepStartTime) / MINUTE_MS));
  const sleepMidpoint = sleepStartTime + (wakeTime - sleepStartTime) / 2;
  const rhrWindow = calculateRhr(samples, sleepStartIndex, wakeIndex, config);
  const rhrAt = rhrWindow
    ? rhrWindow.startTime + (rhrWindow.endTime - rhrWindow.startTime) / 2
    : sleepStartTime;
  const spikeCount = countGroupedSpikes(samples, sleepStartIndex, wakeIndex, config);
  const sleepSamples = samples.slice(sleepStartIndex, wakeIndex + 1);

  const analysis = {
    hasSleep: durationMinutes >= config.minimumSleepMinutes,
    samples,
    sleepSamples,
    dailyAverageBpm,
    sleepStart: toIso(sleepStartTime),
    wakeTime: toIso(wakeTime),
    durationMinutes,
    sleepMidpoint,
    rhr: rhrWindow ? Math.round(rhrWindow.averageBpm) : null,
    rhrAt,
    rhrWindow: rhrWindow ? {
      start: toIso(rhrWindow.startTime),
      end: toIso(rhrWindow.endTime),
      sampleCount: rhrWindow.sampleCount,
      isFallback: rhrWindow.isFallback,
    } : null,
    spikeCount,
  };

  analysis.insight = createSleepInsight(analysis, config.restlessSpikeCount);
  return analysis;
}
