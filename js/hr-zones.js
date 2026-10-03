export const HR_ZONE_COLORS = {
  blue: "#1d4ed8",
  green: "#15803d",
  yellow: "#eab308",
  orange: "#f97316",
  red: "#b91c1c",
};

export const DAILY_HR_ZONES = [
  {
    maximum: 59,
    range: "<60 BPM",
    color: HR_ZONE_COLORS.blue,
    label: "Sen i głęboki relaks",
    description: "To strefa zarezerwowana dla nocnego snu, popołudniowej drzemki, medytacji lub leżenia na kanapie po ciężkim dniu. (Uwaga: u wytrenowanych osób to może być wręcz standardowe tętno spoczynkowe w ciągu dnia).",
  },
  {
    maximum: 85,
    range: "60–85 BPM",
    color: HR_ZONE_COLORS.green,
    label: "Baza i komfort",
    description: "Złoty standard codziennego funkcjonowania. Siedzisz przy biurku, czytasz książkę, oglądasz film, pracujesz w skupieniu. Twoje serce pracuje miarowo i bez wysiłku.",
  },
  {
    maximum: 100,
    range: "86–100 BPM",
    color: HR_ZONE_COLORS.yellow,
    label: "Lekki ruch i pobudzenie",
    description: "Wchodzisz w tę strefę, gdy wstajesz zrobić kawę, spacerujesz po biurze, sprzątasz mieszkanie lub prowadzisz angażującą dyskusję. Może to też oznaczać lekki stres umysłowy.",
  },
  {
    maximum: 120,
    range: "101–120 BPM",
    color: HR_ZONE_COLORS.orange,
    label: "Wysoka aktywność lub silny stres",
    description: "Fizycznie to szybki marsz do autobusu, niesienie ciężkich zakupów czy wchodzenie po schodach na trzecie piętro. Emocjonalnie taki kolor może się zapalić podczas ataku paniki, dużej ekscytacji lub wystąpienia publicznego.",
  },
  {
    maximum: Infinity,
    range: ">120 BPM",
    color: HR_ZONE_COLORS.red,
    label: "Alert / Trening",
    description: "W zwykłym, biurowo-domowym życiu bez ćwiczeń, ten kolor powinien pojawiać się niezwykle rzadko (np. gdy dosłownie biegniesz do uciekającego pociągu). Jeśli widzisz czerwień pijąc herbatę na kanapie, jest to wyraźny sygnał ostrzegawczy od organizmu.",
  },
];

export const SPORTS_HR_ZONES = [
  { maximum: 113, range: "≤113 BPM", color: HR_ZONE_COLORS.blue, label: "Z1 - Regeneracja", description: null },
  { maximum: 132, range: "114–132 BPM", color: HR_ZONE_COLORS.green, label: "Z2 - Baza tlenowa", description: null },
  { maximum: 151, range: "133–151 BPM", color: HR_ZONE_COLORS.yellow, label: "Z3 - Tempo", description: null },
  { maximum: 170, range: "152–170 BPM", color: HR_ZONE_COLORS.orange, label: "Z4 - Próg / anaerobowa", description: null },
  { maximum: Infinity, range: "≥171 BPM", color: HR_ZONE_COLORS.red, label: "Z5 - VO2 Max", description: null },
];

export function getHrZone(currentHR, isWorkoutActive = false) {
  const heartRate = Number(currentHR);
  if (!Number.isFinite(heartRate)) {
    return { color: "#71717a", label: "Brak danych", description: null };
  }
  const zones = isWorkoutActive ? SPORTS_HR_ZONES : DAILY_HR_ZONES;
  const zone = zones.find((candidate) => heartRate <= candidate.maximum) || zones.at(-1);
  return {
    color: zone.color,
    label: zone.label,
    description: zone.description,
  };
}

export function buildWorkoutWindows(sessions = [], dayStart, dayEnd, now = Date.now()) {
  const rangeStart = Number(dayStart);
  const rangeEnd = Number(dayEnd);
  return sessions
    .map((session) => {
      const start = Number(session?.started_at ?? session?.workoutStartTime);
      const isActive = session?.isWorkoutActive === true
        || ["running", "paused"].includes(String(session?.status || "").toLowerCase());
      const explicitEnd = Number(session?.ended_at ?? session?.workoutEndTime);
      const durationEnd = start + Math.max(0, Number(session?.duration_seconds || 0)) * 1000;
      const end = Number.isFinite(explicitEnd) && explicitEnd >= start
        ? explicitEnd
        : isActive
          ? Math.max(start, Number(now))
          : durationEnd;
      if (!Number.isFinite(start) || !Number.isFinite(end) || end < rangeStart || start > rangeEnd) return null;
      return {
        id: String(session?.id || `${start}-${end}`),
        title: String(session?.title || "Trening"),
        workoutType: String(session?.workout_type || session?.workoutType || "indoor_cycling"),
        planId: String(session?.plan_id || session?.planId || ""),
        start: Math.max(rangeStart, start),
        end: Math.min(rangeEnd, Math.max(start, end)),
        actualStart: start,
        actualEnd: end,
        isActive,
      };
    })
    .filter(Boolean)
    .sort((left, right) => left.start - right.start);
}

export function isTimestampInWorkout(timestamp, windows = []) {
  const value = Number(timestamp);
  return Number.isFinite(value)
    && windows.some((window) => value >= Number(window?.actualStart ?? window?.start)
      && value <= Number(window?.actualEnd ?? window?.end));
}

function median(values) {
  if (!values.length) return null;
  const sorted = values.slice().sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function calculateHrZoneDistribution(samples = [], workoutWindows = [], maximumIntervalMs = 5000) {
  const intervalCap = Math.max(1, Number(maximumIntervalMs) || 5000);
  const points = samples
    .map((sample) => ({
      timestamp: Number(sample?.timestamp),
      heartRate: Number(sample?.heart_rate),
    }))
    .filter((sample) => Number.isFinite(sample.timestamp) && Number.isFinite(sample.heartRate))
    .sort((left, right) => left.timestamp - right.timestamp);
  const regularIntervals = points
    .slice(1)
    .map((point, index) => point.timestamp - points[index].timestamp)
    .filter((duration) => duration > 0 && duration <= intervalCap);
  const fallbackInterval = Math.min(intervalCap, median(regularIntervals) || 1000);
  const createMode = (zones) => ({
    totalMs: 0,
    zones: zones.map((zone) => ({
      color: zone.color,
      label: zone.label,
      range: zone.range,
      durationMs: 0,
      percent: 0,
    })),
  });
  const result = {
    daily: createMode(DAILY_HR_ZONES),
    sports: createMode(SPORTS_HR_ZONES),
  };

  points.forEach((point, index) => {
    const next = points[index + 1];
    const rawDuration = next ? next.timestamp - point.timestamp : fallbackInterval;
    const durationMs = Math.max(0, Math.min(intervalCap, rawDuration));
    if (!durationMs) return;
    const sportsMode = isTimestampInWorkout(point.timestamp, workoutWindows);
    const mode = sportsMode ? result.sports : result.daily;
    const zone = getHrZone(point.heartRate, sportsMode);
    const target = mode.zones.find((candidate) => candidate.label === zone.label);
    if (!target) return;
    target.durationMs += durationMs;
    mode.totalMs += durationMs;
  });

  Object.values(result).forEach((mode) => {
    mode.zones.forEach((zone) => {
      zone.percent = mode.totalMs ? zone.durationMs / mode.totalMs * 100 : 0;
    });
  });
  return result;
}
