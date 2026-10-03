export const CADENCE_DISTANCE_KM_PER_REVOLUTION = 0.004;
export const HEART_RATE_DISTANCE_MIN_FRACTION = 0.5;
export const HEART_RATE_DISTANCE_MIN_SPEED_KMH = 8;
export const HEART_RATE_DISTANCE_MAX_SPEED_KMH = 30;
export const VIRTUAL_WALK_STEP_LENGTH_KM = 0.00075;

export function virtualWalkDistanceKm(steps) {
  return Math.max(0, Number(steps) || 0) * VIRTUAL_WALK_STEP_LENGTH_KM;
}

function finiteInRange(value, minimum, maximum) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= minimum && number <= maximum ? number : null;
}

export function deriveCyclingSpeedKmh({ measuredSpeedKmh, cadenceRpm, heartRate, maxHeartRate } = {}) {
  const measured = finiteInRange(measuredSpeedKmh, 0, 120);
  const cadence = finiteInRange(cadenceRpm, 0, 250);
  if (measured != null && measured > 0) return { speedKmh: measured, source: "csc_speed" };
  if (cadence != null) {
    return {
      speedKmh: cadence * CADENCE_DISTANCE_KM_PER_REVOLUTION * 60,
      source: "cadence_virtual_distance_v1",
    };
  }
  if (measured != null) return { speedKmh: measured, source: "csc_speed" };
  const bpm = finiteInRange(heartRate, 30, 240);
  const maxHr = finiteInRange(maxHeartRate, 100, 240);
  if (bpm == null || maxHr == null) return { speedKmh: 0, source: "unavailable" };
  const intensity = bpm / maxHr;
  if (intensity < HEART_RATE_DISTANCE_MIN_FRACTION) {
    return { speedKmh: 0, source: "heart_rate_virtual_distance_v1" };
  }
  const normalizedIntensity = Math.min(
    1,
    (intensity - HEART_RATE_DISTANCE_MIN_FRACTION) / (1 - HEART_RATE_DISTANCE_MIN_FRACTION),
  );
  return {
    speedKmh: HEART_RATE_DISTANCE_MIN_SPEED_KMH
      + normalizedIntensity * (HEART_RATE_DISTANCE_MAX_SPEED_KMH - HEART_RATE_DISTANCE_MIN_SPEED_KMH),
    source: "heart_rate_virtual_distance_v1",
  };
}

export function accumulateCyclingDistance(distanceKm, deltaSeconds, signals = {}) {
  const current = Math.max(0, Number(distanceKm) || 0);
  const seconds = Math.max(0, Math.min(5, Number(deltaSeconds) || 0));
  const speed = deriveCyclingSpeedKmh(signals);
  return {
    distanceKm: current + speed.speedKmh * seconds / 3600,
    ...speed,
  };
}
