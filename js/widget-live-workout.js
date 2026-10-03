import { loadFileBackedSetting, saveFileBackedSetting } from "./file-settings.js";
import { setDailyAchievement } from "./daily-achievements.js";
import {
  DEFAULT_INDOOR_CYCLING_CALIBRATION,
  HR_ZONE_CONFIG,
  calculateCaloriesPerSecond,
  calculateIndoorCyclingCaloriesPerSecond,
  calculateHeartRateZones,
  calculateSegmentLayout,
  calculateTrimp,
  calculateZoneFulfillment,
  deriveIndoorCyclingCalibration,
  estimateCaloriesFromZones,
  getTargetZoneGuide,
  resolveMaxHr,
} from "./live-workout-engine.js";
import { optimizeWorkoutPlan } from "./live-workout-plan-optimizer.js";
import {
  collectLocalStorage,
  downloadTextFile,
  exportWorkoutToTCX,
  importLocalStorageBackup,
  validateFullBackup,
} from "./live-workout-transfer.js";
import {
  CscBluetoothSensor,
  formatCscConnectionError,
  parseCscMeasurement,
} from "./live-workout-csc.js";
import {
  createExclusiveActionGate,
  enterElementFullscreen,
  isWorkoutSessionActive,
  pinWorkoutHudOpen,
  toggleElementFullscreen,
} from "./live-workout-controls.js";
import {
  CalibrationEngine,
  buildCalibrationModel,
  buildCalibrationZoneMap,
  clearCalibrations,
  getCalibrationResumePlan,
  loadCalibrations,
  recommendRpmForLevel,
  saveCalibration,
} from "./live-workout-calibration.js";
import {
  LIVE_WORKOUT_RESISTANCE_LEVEL_KEY,
  LiveWorkoutLearningEngine,
  clearLiveWorkoutLearningSamples,
  getWorkoutLearningPhase,
  learningSamplesAsCalibration,
  loadLiveWorkoutLearningSamples,
  saveLiveWorkoutLearningSample,
} from "./live-workout-adaptive-calibration.js";
import { AudioNotifier, CadenceMetronome } from "./live-workout-audio.js";
import {
  createCalibrationPanel,
  drawCalibrationChart,
  getCalibrationElements,
  renderCalibrationPanel,
} from "./live-workout-calibration-ui.js";
import {
  cloneStrengthPlan,
  isStrengthPlanEnabled,
  normalizeStrengthPlan,
} from "./live-workout-strength-data.js";
import { initStrengthTrainer, openStrengthTrainer } from "./live-workout-strength.js";
import { liveWorkoutRuntimeUrl } from "./live-workout-runtime-api.js";
import { fetchJourneyPostcards, journeyPostcardImageUrl } from "./live-workout-journey-api.js";
import { accumulateCyclingDistance, deriveCyclingSpeedKmh, virtualWalkDistanceKm } from "./live-workout-distance.js";
import { loadSantiagoJourneyEngine } from "./santiago-journey.js";
import {
  buildCyclingCalorieRanking,
  calculateLiveCalorieRank,
  calorieRankMedal,
  calorieRankTier,
  normalizeCyclingCalorieRanking,
} from "./live-workout-ranking.js";

const PLAN_ENDPOINT = liveWorkoutRuntimeUrl("plan");
const STREAM_ENDPOINT = liveWorkoutRuntimeUrl("stream");
const LATEST_TELEMETRY_ENDPOINT = liveWorkoutRuntimeUrl("latest");
const HISTORY_ENDPOINT = liveWorkoutRuntimeUrl("history");
const RANKING_ENDPOINT = liveWorkoutRuntimeUrl("calorie-ranking");
const SESSION_ENDPOINT = liveWorkoutRuntimeUrl("session");
const JOURNEY_ENDPOINT = liveWorkoutRuntimeUrl("journey/santiago");
const HISTORY_WINDOW_MS = 5 * 60 * 1000;
const TELEMETRY_FRESH_MS = 4000;
const SESSION_SNAPSHOT_KEY = "liveWorkout.activeSession.v2";
const PLAN_TRACKING_KEY = "liveWorkout.planTracking.v1";
const PROFILE_STORAGE_KEY = "liveWorkout.profile.v1";
const HISTORY_CACHE_KEY = "liveWorkout.historyCache.v1";
const PLAN_CACHE_KEY = "liveWorkout.planCache.v1";
const API_RETRY_DELAY_MS = 2000;
const LIVE_RPM_GAUGE_MAX = 130;
const LIVE_RPM_TARGET_TOLERANCE = 4;
export const CALORIE_AVERAGE_START_DATE = "2026-08-20";

export const DEFAULT_MAX_HR = 190;
export const ZONE_DEFINITIONS = HR_ZONE_CONFIG;
export const VIRTUAL_WALK_HR_MIN = 95;
export const VIRTUAL_WALK_HR_MAX = 120;
export const VIRTUAL_WALK_GUARDRAIL_HR = 125;
export const VIRTUAL_WALK_STEPS_PER_MINUTE = 105;

const escapeAchievementHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

export const WORKOUT_TYPE_LABELS = {
  recovery: "Regeneracja",
  base: "Baza tlenowa",
  tempo: "Tempo",
  intervals: "Interwały",
  long: "Długi trening",
  rest: "Odpoczynek",
  "free-ride": "FREE RIDE",
  virtual_walk: "Sesja Spacerowa",
  strength: "Trening siłowy",
};

export function getWorkoutGuidance(heartRate, targetZone, maxHr = DEFAULT_MAX_HR, active = false, complete = false, optional = false) {
  if (!active) return { key: "standby", label: "KLIKNIJ START, ABY ROZPOCZĄĆ PLAN" };
  if (complete) return { key: "extra", label: "PLAN WYKONANY · TRENING NADMIAROWY" };
  const guide = getTargetZoneGuide(heartRate, targetZone, { maxHr });
  if (optional && guide.state === "faster") return { key: "hold", label: "MOCNO, ALE BEZ FORSOWANIA Z5" };
  return { key: guide.state === "target" ? "hold" : guide.state, label: guide.label };
}

export function getPlanMetrics(schedule = [], history = []) {
  const planDates = new Set(schedule.map((workout) => workout.date));
  const completedDates = new Set(
    history
      .filter((session) => session?.status === "finished" && session?.plan_id !== "free-ride" && !["virtual_walk", "strength"].includes(session?.workout_type) && session?.plan_completed !== false)
      .map((session) => session.plan_date || new Date(Number(session.started_at)).toISOString().slice(0, 10))
      .filter((workoutDate) => planDates.has(workoutDate)),
  );
  const plannedMinutes = schedule.reduce((sum, workout) => sum + Number(workout.duration || 0), 0);
  const completed = schedule.filter((workout) => workout.type !== "rest" && completedDates.has(workout.date));
  const actualMinutes = history
    .filter((session) => session?.status === "finished" && session?.plan_id !== "free-ride" && !["virtual_walk", "strength"].includes(session?.workout_type))
    .filter((session) => planDates.has(session.plan_date || new Date(Number(session.started_at)).toISOString().slice(0, 10)))
    .reduce((sum, session) => sum + Number(session.duration_seconds || 0) / 60, 0);
  return {
    completedDates,
    completedWorkouts: completed.length,
    plannedWorkouts: schedule.filter((workout) => workout.type !== "rest").length,
    plannedMinutes,
    actualMinutes,
    progress: plannedMinutes ? Math.min(100, actualMinutes / plannedMinutes * 100) : 0,
  };
}

function workoutSessionDate(session) {
  if (session?.plan_id === "free-ride" || session?.workout_type === "virtual_walk") return "";
  if (session?.plan_date) return session.plan_date;
  const timestamp = Number(session?.started_at);
  if (!Number.isFinite(timestamp)) return "";
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function isWorkoutDayCompleted(workout, history = [], statuses = {}) {
  if (!workout || workout.type === "rest") return false;
  if (statuses?.[workout.date] === "completed") return true;
  const plannedSeconds = Math.max(1, Number(workout.duration || 0) * 60);
  return history.some((session) => {
    if (session?.status !== "finished" || ["virtual_walk", "strength"].includes(session?.workout_type) || workoutSessionDate(session) !== workout.date) return false;
    if (session.plan_completed === true) return true;
    if (session.plan_completed === false) return false;
    return Number(session.duration_seconds || 0) >= plannedSeconds * .9;
  });
}

export function isWorkoutDaySatisfied(workout, history = [], statuses = {}) {
  return Boolean(workout) && (
    workout.type === "rest"
    || isWorkoutDayCompleted(workout, history, statuses)
  );
}

export function getWorkoutDayDurationSeconds(workout, history = []) {
  if (!workout?.date || workout.type === "rest") return 0;
  return history
    .filter((session) => session?.status === "finished" && session?.workout_type !== "strength" && workoutSessionDate(session) === workout.date)
    .reduce((sum, session) => sum + Math.max(0, Number(session.duration_seconds) || 0), 0);
}

export function getWorkoutStreak(schedule = [], history = [], statuses = {}, todayKey = "") {
  const eligible = schedule
    .filter((workout) => workout?.date && (!todayKey || workout.date <= todayKey))
    .sort((left, right) => left.date.localeCompare(right.date));
  let streak = 0;
  for (let index = eligible.length - 1; index >= 0; index -= 1) {
    const workout = eligible[index];
    if (workout.type === "rest") continue;
    const completed = isWorkoutDayCompleted(workout, history, statuses);
    if (workout.date === todayKey && !completed) continue;
    if (!completed) break;
    streak += 1;
  }
  return streak;
}

export function buildWorkoutStreakometer(schedule = [], history = [], statuses = {}, todayKey = "") {
  const ordered = schedule
    .filter((workout) => workout?.date)
    .sort((left, right) => left.date.localeCompare(right.date));
  const todayIndex = ordered.findIndex((workout) => workout.date === todayKey);
  const windowStart = todayIndex >= 0
    ? Math.max(0, Math.min(todayIndex - 6, ordered.length - 7))
    : Math.max(0, ordered.findIndex((workout) => workout.date > todayKey) - 6);
  return ordered
    .slice(windowStart, windowStart + 7)
    .map((workout) => ({
      date: workout.date,
      type: workout.type,
      isToday: workout.date === todayKey,
      state: todayKey && workout.date > todayKey
        ? "upcoming"
        : workout.type === "rest"
        ? "rest"
        : isWorkoutDayCompleted(workout, history, statuses)
          ? "completed"
          : statuses?.[workout.date] === "partial"
            ? "partial"
            : statuses?.[workout.date] === "skipped"
              ? "skipped"
              : "planned",
    }));
}

function polishWorkoutStreak(days) {
  const value = Math.max(0, Math.round(Number(days) || 0));
  return value === 1 ? "1 ukończony trening z rzędu" : `${value} ukończonych treningów z rzędu`;
}

export const FALLBACK_PLAN = {
  plan_title: "Indoor Endurance Builder",
  total_duration_minutes: 45,
  target_zones: { light: 23, intensive: 5, aerobic: 8, anaerobic: 6, vo2max: 3 },
  intervals: [
    { name: "Rozgrzewka", duration_minutes: 8, target_zone: "light" },
    { name: "Spokojne tempo", duration_minutes: 5, target_zone: "intensive" },
    { name: "Tempo aerobowe", duration_minutes: 8, target_zone: "aerobic" },
    { name: "Aktywna regeneracja", duration_minutes: 3, target_zone: "light" },
    { name: "Próg", duration_minutes: 6, target_zone: "anaerobic" },
    { name: "Aktywna regeneracja", duration_minutes: 3, target_zone: "light" },
    { name: "VO2 max", duration_minutes: 3, target_zone: "vo2max" },
    { name: "Schłodzenie", duration_minutes: 9, target_zone: "light" },
  ],
};

export const FREE_RIDE_PLAN = {
  plan_id: "free-ride",
  plan_title: "Free Ride · trening dodatkowy",
  total_duration_minutes: 0,
  target_zones: { light: 0, intensive: 0, aerobic: 0, anaerobic: 0, vo2max: 0 },
  intervals: [{ name: "Jazda dowolna", duration_minutes: 1440, target_zone: "intensive", optional: true }],
  current_workout: { date: null, type: "free-ride", duration: 0, purpose: "Trening dodatkowy po wykonaniu dziennego planu." },
};

export const VIRTUAL_WALK_PLAN = {
  plan_id: "virtual-walk",
  plan_title: "Sesja Spacerowa · Virtual Walk",
  total_duration_minutes: 0,
  target_zones: { light: 0, intensive: 0, aerobic: 0, anaerobic: 0, vo2max: 0 },
  intervals: [{ name: "Spacer regeneracyjny", duration_minutes: 1440, target_zone: "light", optional: true }],
  current_workout: { date: null, type: "virtual_walk", duration: 0, purpose: "Lekka sesja LISS/NEAT poza planem głównym." },
};

export function calculateVirtualWalkSteps(activeSeconds = 0) {
  return Math.max(0, Math.floor((Number(activeSeconds) || 0) / 60 * VIRTUAL_WALK_STEPS_PER_MINUTE));
}

export function calculateDailyStepsGoal(storedSteps = 0, currentSessionSteps = 0, goal = 10000) {
  const safeGoal = Math.max(1, Number(goal) || 10000);
  const total = Math.max(0, Number(storedSteps) || 0) + Math.max(0, Number(currentSessionSteps) || 0);
  const exactPercent = total / safeGoal * 100;
  return {
    total,
    goal: safeGoal,
    percent: Math.floor(exactPercent),
    barPercent: Math.min(100, exactPercent),
  };
}

export function parseCyclingCadenceMeasurement(value, previous = null) {
  try {
    const parsed = parseCscMeasurement(value, { crank: previous });
    const rpm = Number.isFinite(parsed.rpm) && parsed.rpm >= 0 && parsed.rpm <= 250 ? parsed.rpm : null;
    return { rpm, crank: parsed.crank || previous };
  } catch {
    return { rpm: null, crank: previous };
  }
}

export function getVirtualWalkGuidance(heartRate, highHrSeconds = 0, active = false) {
  if (!active) return { state: "standby", label: "KLIKNIJ SESJA SPACEROWA, ABY ZACZĄĆ" };
  const hr = Number(heartRate);
  if (!Number.isFinite(hr)) return { state: "waiting", label: "CZEKAM NA TĘTNO" };
  if (hr > VIRTUAL_WALK_GUARDRAIL_HR && Number(highHrSeconds) > 20) {
    return { state: "danger", label: "ZWOLNIJ! TO MA BYĆ REGENERACYJNY SPACER (Z1), NIE TRENING" };
  }
  if (hr < VIRTUAL_WALK_HR_MIN) return { state: "faster", label: `LEKKO PRZYSPIESZ (+${Math.ceil(VIRTUAL_WALK_HR_MIN - hr)} BPM)` };
  if (hr > VIRTUAL_WALK_HR_MAX) return { state: "slower", label: `ZWOLNIJ DO STREFY SPACEROWEJ (-${Math.ceil(hr - VIRTUAL_WALK_HR_MAX)} BPM)` };
  return { state: "target", label: "TEMPO SPACEROWE · KROKI SĄ NALICZANE" };
}

export function getHeartRateZones(maxHr = DEFAULT_MAX_HR) {
  return calculateHeartRateZones({ maxHr });
}

export function getZoneForHeartRate(heartRate, maxHr = DEFAULT_MAX_HR) {
  const zones = getHeartRateZones(maxHr);
  const bpm = Number(heartRate);
  if (!Number.isFinite(bpm)) return null;
  return zones.find((zone) => bpm <= zone.max) || zones[zones.length - 1];
}

export function isHeartRateInTarget(heartRate, targetZone, maxHr = DEFAULT_MAX_HR) {
  const bpm = Number(heartRate);
  const zone = getHeartRateZones(maxHr).find((item) => item.key === targetZone);
  return Boolean(zone && Number.isFinite(bpm) && bpm >= zone.min && bpm <= zone.max);
}

export function getIntervalAtElapsed(plan, elapsedSeconds = 0) {
  const intervals = Array.isArray(plan?.intervals) ? plan.intervals : [];
  if (!intervals.length) return null;
  const elapsed = Math.max(0, Number(elapsedSeconds) || 0);
  let cursor = 0;
  for (let index = 0; index < intervals.length; index += 1) {
    const interval = intervals[index];
    const durationSeconds = Math.max(0, Number(interval.duration_minutes) || 0) * 60;
    const end = cursor + durationSeconds;
    if (elapsed < end) {
      return {
        interval,
        index,
        elapsedInInterval: elapsed - cursor,
        remainingSeconds: Math.ceil(end - elapsed),
        next: intervals[index + 1] || null,
        complete: false,
      };
    }
    cursor = end;
  }
  return {
    interval: intervals[intervals.length - 1],
    index: intervals.length - 1,
    elapsedInInterval: 0,
    remainingSeconds: 0,
    next: null,
    complete: true,
  };
}

export function getIntervalAtProgress(plan, intervalProgressSeconds = []) {
  const intervals = Array.isArray(plan?.intervals) ? plan.intervals : [];
  if (!intervals.length) return null;
  for (let index = 0; index < intervals.length; index += 1) {
    const interval = intervals[index];
    const durationSeconds = Math.max(0, Number(interval.duration_minutes) || 0) * 60;
    const completedSeconds = Math.min(durationSeconds, Math.max(0, Number(intervalProgressSeconds[index]) || 0));
    if (completedSeconds < durationSeconds) {
      return {
        interval,
        index,
        elapsedInInterval: completedSeconds,
        remainingSeconds: Math.ceil(durationSeconds - completedSeconds),
        next: intervals[index + 1] || null,
        complete: false,
      };
    }
  }
  return {
    interval: intervals.at(-1),
    index: intervals.length - 1,
    elapsedInInterval: Math.max(0, Number(intervalProgressSeconds.at(-1)) || 0),
    remainingSeconds: 0,
    next: null,
    complete: true,
  };
}

export function creditIntervalProgress(plan, intervalProgressSeconds = [], actualZoneKey, deltaSeconds = 0) {
  const intervals = Array.isArray(plan?.intervals) ? plan.intervals : [];
  const progress = intervals.map((interval, index) => Math.min(
    Math.max(0, Number(interval.duration_minutes) || 0) * 60,
    Math.max(0, Number(intervalProgressSeconds[index]) || 0),
  ));
  const completedIndices = [];
  let remaining = Math.max(0, Number(deltaSeconds) || 0);
  let creditedSeconds = 0;
  while (remaining > 0) {
    const current = getIntervalAtProgress(plan, progress);
    if (!current || current.complete || current.interval.target_zone !== actualZoneKey) break;
    const requiredSeconds = Math.max(0, Number(current.interval.duration_minutes) || 0) * 60;
    const credited = Math.min(remaining, Math.max(0, requiredSeconds - progress[current.index]));
    if (credited <= 0) break;
    progress[current.index] += credited;
    remaining -= credited;
    creditedSeconds += credited;
    if (progress[current.index] >= Math.max(0, Number(current.interval.duration_minutes) || 0) * 60) {
      completedIndices.push(current.index);
    }
  }
  return {
    progress,
    creditedSeconds,
    completedIndices,
    current: getIntervalAtProgress(plan, progress),
  };
}

export function getLegacyIntervalProgress(plan, elapsedSeconds = 0) {
  let remaining = Math.max(0, Number(elapsedSeconds) || 0);
  return (plan?.intervals || []).map((interval) => {
    const required = Math.max(0, Number(interval.duration_minutes) || 0) * 60;
    const credited = Math.min(required, remaining);
    remaining -= credited;
    return credited;
  });
}

export function formatWorkoutTime(totalSeconds) {
  const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function getWorkoutZonePercent(session, zoneKey) {
  const duration = Math.max(0, Number(session?.duration_seconds) || 0);
  const seconds = Math.max(0, Number(session?.zones?.[zoneKey]) || 0);
  return duration ? Math.min(100, (seconds / duration) * 100) : 0;
}

export function summarizeWorkoutDay(sessions = []) {
  const finishedSessions = sessions.filter((session) => session?.status === "finished");
  const zoneSeconds = Object.fromEntries(ZONE_DEFINITIONS.map((zone) => [zone.key, 0]));
  let heartRateSeconds = 0;
  let weightedHeartRate = 0;

  const summary = finishedSessions.reduce((result, session) => {
    const durationSeconds = Math.max(0, Number(session?.duration_seconds) || 0);
    const averageHeartRate = Number(session?.avg_hr);
    result.durationSeconds += durationSeconds;
    result.activeCalories += Math.max(0, Number(session?.active_calories) || 0);
    result.trainingLoad += Math.max(0, Number(session?.training_load) || 0);
    result.maxHeartRate = Math.max(result.maxHeartRate, Math.max(0, Number(session?.max_hr) || 0));
    const storedVirtualSteps = Math.max(0, Number(session?.virtual_steps) || 0);
    const inferredVirtualSteps = session?.workout_type === "virtual_walk"
      ? calculateVirtualWalkSteps(session?.virtual_walk_active_seconds)
      : 0;
    result.virtualSteps += storedVirtualSteps || inferredVirtualSteps;
    if (Number.isFinite(averageHeartRate) && averageHeartRate > 0 && durationSeconds > 0) {
      heartRateSeconds += durationSeconds;
      weightedHeartRate += averageHeartRate * durationSeconds;
    }
    ZONE_DEFINITIONS.forEach((zone) => {
      zoneSeconds[zone.key] += Math.max(0, Number(session?.zones?.[zone.key]) || 0);
    });
    return result;
  }, {
    sessionCount: finishedSessions.length,
    durationSeconds: 0,
    activeCalories: 0,
    trainingLoad: 0,
    maxHeartRate: 0,
    virtualSteps: 0,
  });

  return {
    ...summary,
    averageHeartRate: heartRateSeconds ? Math.round(weightedHeartRate / heartRateSeconds) : 0,
    zoneSeconds,
    totalZoneSeconds: Object.values(zoneSeconds).reduce((sum, seconds) => sum + seconds, 0),
  };
}

export function formatWorkoutDate(timestamp) {
  const value = Number(timestamp);
  if (!Number.isFinite(value)) return "--";
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function calculateDailyWorkoutCaloriesAverage(
  history = [],
  { startDate = CALORIE_AVERAGE_START_DATE, now = new Date(), currentCalories = 0 } = {},
) {
  const [startYear, startMonth, startDay] = String(startDate).split("-").map(Number);
  const currentDate = now instanceof Date ? now : new Date(now);
  if (![startYear, startMonth, startDay].every(Number.isFinite) || Number.isNaN(currentDate.getTime())) {
    return { totalCalories: 0, dayCount: 0, averageCalories: 0 };
  }
  const startUtc = Date.UTC(startYear, startMonth - 1, startDay);
  const todayUtc = Date.UTC(currentDate.getFullYear(), currentDate.getMonth(), currentDate.getDate());
  if (todayUtc < startUtc) return { totalCalories: 0, dayCount: 0, averageCalories: 0 };
  const todayKey = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, "0")}-${String(currentDate.getDate()).padStart(2, "0")}`;
  const dayCount = Math.floor((todayUtc - startUtc) / 86_400_000) + 1;
  const historyCalories = history.reduce((sum, session) => {
    if (session?.status !== "finished") return sum;
    const timestamp = Number(session.started_at);
    if (!Number.isFinite(timestamp)) return sum;
    const date = new Date(timestamp);
    const dateKey = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    if (dateKey < startDate || dateKey > todayKey) return sum;
    return sum + Math.max(0, Number(session.active_calories) || 0);
  }, 0);
  const totalCalories = historyCalories + Math.max(0, Number(currentCalories) || 0);
  return {
    totalCalories,
    dayCount,
    averageCalories: dayCount ? totalCalories / dayCount : 0,
  };
}

function getWorkoutProfile() {
  let stored = {};
  try { stored = JSON.parse(window.localStorage?.getItem(PROFILE_STORAGE_KEY) || "{}"); } catch {}
  const legacyMaxHr = Number(window.localStorage?.getItem("liveWorkout.maxHr") || window.localStorage?.getItem("health.maxHr"));
  const profile = {
    sex: stored.sex === "female" ? "female" : "male",
    ageYears: Math.max(14, Math.min(100, Number(stored.ageYears) || 30)),
    weightKg: Math.max(30, Math.min(300, Number(stored.weightKg) || 75)),
    bmrKcal: Math.max(800, Math.min(4000, Number(stored.bmrKcal) || 1800)),
    maxHr: Number(stored.maxHr) || (Number.isFinite(legacyMaxHr) ? legacyMaxHr : null),
  };
  profile.maxHr = resolveMaxHr(profile);
  return profile;
}

function saveWorkoutProfile(profile) {
  window.localStorage?.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
  window.localStorage?.setItem("liveWorkout.maxHr", String(profile.maxHr));
}

function cloneFallbackPlan() {
  return JSON.parse(JSON.stringify(FALLBACK_PLAN));
}

function createFocusOverlay() {
  const overlay = document.createElement("div");
  overlay.className = "live-workout-focus";
  overlay.id = "live-workout-focus";
  overlay.hidden = true;
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", "live-workout-focus-title");
  overlay.innerHTML = `
    <div class="live-workout-focus-shell">
      <header class="live-workout-focus-header">
        <div>
          <div class="live-workout-focus-kicker">LIVE WORKOUT · INDOOR CYCLING</div>
          <h2 id="live-workout-focus-title">Ładowanie planu…</h2>
        </div>
        <div class="live-workout-focus-actions">
          <span class="live-workout-connection" data-live-connection>Łączenie…</span>
          <div class="live-workout-csc-header" data-live-csc-panel data-csc-status="disconnected">
            <i aria-hidden="true"></i>
            <span role="status" aria-live="polite"><b data-live-csc-badge>MAGENE CSC ROZŁĄCZONY</b></span>
            <button type="button" data-live-csc-connect data-live-cadence-connect>POŁĄCZ</button>
          </div>
          <button type="button" class="live-workout-session-btn is-calibration" data-live-calibration-open>KALIBRACJA ROWERKA</button>
          <button type="button" class="live-workout-session-btn is-start" data-live-session-action="start">START CYCLING</button>
          <button type="button" class="live-workout-session-btn is-walk" data-live-session-action="virtual-walk">START WALKING</button>
          <button type="button" class="live-workout-session-btn" data-live-session-action="pause" hidden>PAUZA</button>
          <button type="button" class="live-workout-session-btn" data-live-session-action="resume" hidden>WZNÓW</button>
          <button type="button" class="live-workout-session-btn is-finish" data-live-session-action="finish" hidden>ZAKOŃCZ</button>
          <button type="button" class="live-workout-session-btn is-cancel" data-live-session-action="cancel" hidden>ANULUJ SESJĘ</button>
          <button type="button" class="live-workout-session-btn is-fullscreen" data-live-fullscreen>PEŁNY EKRAN HUD</button>
          <a class="live-workout-reference-link" href="./live-workout.html">PLAN · HISTORIA · STRENGTH</a>
          <button type="button" class="live-workout-close" data-live-workout-close aria-label="Zamknij tryb Focus">Zamknij ×</button>
        </div>
      </header>
      <details class="live-workout-csc-diagnostics" data-live-csc-diagnostics>
        <summary>Diagnostyka połączenia Magene CSC</summary>
        <ol data-live-csc-diagnostic-entries></ol>
      </details>
      <div class="live-workout-guidance" data-live-guidance="standby">KLIKNIJ START, ABY ROZPOCZĄĆ PLAN</div>
      <div class="live-workout-segments" data-live-segments aria-label="Przebieg całego treningu"></div>
      <div class="live-workout-achievement" data-live-achievement hidden role="status" aria-live="assertive"></div>
      <div class="live-workout-learning-toast" data-live-learning-toast hidden role="status" aria-live="polite"></div>
      <div class="live-workout-focus-grid" data-live-workout-main>
        <main class="live-workout-stage">
          <section class="live-workout-hr-panel" data-live-feedback="neutral" aria-live="polite">
            <div class="live-workout-target-label" data-live-target>Oczekiwanie na plan…</div>
            <div class="live-workout-vitals-grid">
              <div class="live-workout-vital-hr">
                <span class="live-workout-vital-label">TĘTNO</span>
                <div class="live-workout-hr-row">
                  <span class="live-workout-heart" aria-hidden="true">♥</span>
                  <strong data-live-hr>--</strong>
                  <span>BPM</span>
                </div>
                <div class="live-workout-zone-now" data-live-zone-now>Brak danych z zegarka</div>
              </div>
              <div class="live-workout-cadence-hero" data-csc-status="disconnected">
                <span class="live-workout-vital-label">KADENCJA</span>
                <div><strong data-live-cadence>--</strong><span>RPM</span></div>
                <small data-live-csc-advice hidden></small>
              </div>
            </div>
            <div class="live-workout-learning-control" data-live-learning-control>
              <div>
                <span>AKTUALNY POZIOM OPORU · kliknij po zmianie manetki</span>
                <div class="live-workout-resistance-levels" data-live-resistance-levels>
                  ${Array.from({ length: 8 }, (_, index) => `<button type="button" data-live-resistance-level="${index + 1}">P${index + 1}</button>`).join("")}
                </div>
              </div>
              <div class="live-workout-rpm-recommendation">
                <div class="live-workout-rpm-recommendation-copy">
                  <span data-live-rpm-recommendation-zone>MODEL RPM</span>
                  <strong data-live-rpm-recommendation>-- RPM</strong>
                </div>
                <div class="live-workout-rpm-target-gauge" data-live-rpm-target-gauge data-state="idle" aria-label="Brak sugerowanego zakresu RPM">
                  <div class="live-workout-rpm-target-scale" aria-hidden="true">
                    <i class="is-target-band" data-live-rpm-target-band hidden></i>
                    <i class="is-current-needle" data-live-rpm-current-needle hidden></i>
                  </div>
                  <div class="live-workout-rpm-target-labels">
                    <span>0</span>
                    <b data-live-rpm-band-label>CEL --</b>
                    <span>${LIVE_RPM_GAUGE_MAX}</span>
                  </div>
                </div>
                <small data-live-learning-status>Uczenie rozpocznie się podczas treningu</small>
              </div>
            </div>
          </section>
          <section class="live-workout-timer-panel">
            <div>
              <span data-live-timer-label>Sesja jeszcze nie rozpoczęta</span>
              <strong data-live-interval>--</strong>
            </div>
            <time data-live-countdown>00:00</time>
            <div class="live-workout-next">Następny: <strong data-live-next>--</strong></div>
            <div class="live-workout-virtual-metrics" data-live-virtual-metrics hidden>
              <div class="is-primary"><span>WIRTUALNE KROKI</span><strong data-live-virtual-steps>+0</strong></div>
              <div><span>W STREFIE 95–120</span><strong data-live-virtual-active>00:00</strong></div>
              <div><span>POZA STREFĄ</span><strong data-live-virtual-outside>00:00</strong></div>
            </div>
            <div class="live-workout-realtime-metrics">
              <span class="has-workout-explanation" data-live-calories-help tabindex="0"><strong data-live-calories>0.0 kcal</strong><small>szacunek aktywnych kcal · ⓘ</small></span>
              <span class="has-workout-explanation" data-live-trimp-help tabindex="0"><strong data-live-trimp>0.0 pkt</strong><small>obciążenie strefowe · ⓘ</small></span>
              <span class="has-workout-explanation" data-live-time-help tabindex="0"><strong data-live-total-clock>00:00</strong><small data-live-total-clock-label>czas łączny</small></span>
            </div>
            <div class="live-workout-rank-live" data-live-rank hidden>
              <div><span>RANKING CARDIO</span><strong data-live-rank-position>—</strong></div>
              <div class="live-workout-rank-copy"><strong data-live-rank-target>Ładowanie rankingu…</strong><small data-live-rank-total></small></div>
              <div class="live-workout-rank-track" aria-hidden="true"><i data-live-rank-bar></i></div>
            </div>
          </section>
          <section class="live-workout-chart-panel" aria-label="Wykres tętna z ostatnich 5 minut">
            <div class="live-workout-section-head">
              <strong>Tętno · ostatnie 5 minut</strong>
              <span data-live-chart-target>Cel: -- BPM</span>
            </div>
            <canvas data-live-chart></canvas>
          </section>
        </main>
        <aside class="live-workout-zones-panel">
          <div class="live-workout-section-head">
            <div><strong>Realizacja stref</strong><span data-live-max-hr>maxHR 190</span></div>
            <span data-live-total-time>00:00</span>
          </div>
          <div class="live-workout-zone-list" data-live-zones></div>
          <div class="live-workout-plan-progress">
            <span data-live-plan-progress-label>Postęp planu</span>
            <strong data-live-plan-progress>0%</strong>
            <div><i data-live-plan-bar></i></div>
            <small data-live-daily-steps hidden></small>
          </div>
          <section class="live-workout-journey" data-live-journey data-state="loading" aria-live="polite">
            <header class="live-workout-journey-next">
              <div><span>NASTĘPNY CEL</span><strong data-live-journey-next>—</strong><small data-live-journey-next-meta></small></div>
              <b data-live-journey-next-distance>— km</b>
            </header>
            <div class="live-workout-journey-grid">
              <div class="is-ride"><span data-live-journey-activity>TA JAZDA</span><strong data-live-journey-ride>+0,0 km</strong><small data-live-journey-speed>Czekam na ruch</small></div>
              <div class="is-previous"><span>OSTATNI PUNKT</span><strong data-live-journey-previous>—</strong><small data-live-journey-previous-meta></small></div>
            </div>
            <div class="live-workout-journey-total">
              <div><span>KRAKÓW → SANTIAGO · CAŁA TRASA</span><strong data-live-journey-distance>Ładowanie podróży…</strong><b data-live-journey-percent>—</b></div>
              <div class="live-workout-journey-track" aria-hidden="true"><i data-live-journey-bar></i></div>
            </div>
            <details class="live-workout-journey-debug" data-live-journey-debug hidden>
              <summary>365 checkpointów · podgląd danych</summary>
              <div data-live-journey-checkpoints></div>
            </details>
          </section>
        </aside>
      </div>
      <section class="live-workout-plan-panel" aria-labelledby="live-workout-plan-title" hidden>
        <div class="live-workout-history-head">
          <div>
            <div class="live-workout-focus-kicker">PLAN 22.08–20.09.2026</div>
            <h3 id="live-workout-plan-title">Indoor Cycling · plan cardio</h3>
          </div>
          <div class="live-workout-plan-kpis" data-live-plan-kpis></div>
        </div>
        <div class="live-workout-adaptation" data-live-adaptation hidden></div>
        <div class="live-workout-load-warning" data-live-load-warning hidden></div>
        <div class="live-workout-week-volume" data-live-week-volume aria-label="Tygodniowa objętość planu"></div>
        <div class="live-workout-calendar" data-live-calendar></div>
        <article class="live-workout-day-detail" data-live-day-detail></article>
      </section>
      <section class="live-workout-history-panel" aria-labelledby="live-workout-history-title" hidden>
        <div class="live-workout-history-head">
          <div>
            <div class="live-workout-focus-kicker">DZIENNIK TRENINGOWY</div>
            <h3 id="live-workout-history-title">Historia indoor cycling</h3>
          </div>
          <div class="live-workout-transfer-actions">
            <button type="button" class="live-workout-history-refresh" data-live-profile-open>Profil obliczeń</button>
            <button type="button" class="live-workout-history-refresh" data-live-backup-export>Backup JSON</button>
            <button type="button" class="live-workout-history-refresh" data-live-backup-import>Import JSON</button>
            <input type="file" accept="application/json,.json" data-live-backup-file hidden>
            <button type="button" class="live-workout-history-refresh" data-live-history-refresh>Odśwież</button>
          </div>
        </div>
        <div class="live-workout-history-list" data-live-history-list>
          <div class="live-workout-history-empty">Ładowanie historii…</div>
        </div>
      </section>
      <dialog class="live-workout-profile-dialog" data-live-profile-dialog>
        <form method="dialog" data-live-profile-form>
          <header><strong>Profil obliczeń treningowych</strong><button value="cancel" aria-label="Zamknij">×</button></header>
          <label>Płeć biologiczna do wzoru Keytela<select name="sex"><option value="male">Mężczyzna</option><option value="female">Kobieta</option></select></label>
          <label>Wiek<input name="ageYears" type="number" min="14" max="100" required></label>
          <label>Waga [kg]<input name="weightKg" type="number" min="30" max="300" step="0.1" required></label>
          <label>HRmax<input name="maxHr" type="number" min="100" max="240" required></label>
          <label>BMR [kcal/dzień]<input name="bmrKcal" type="number" min="800" max="4000" required></label>
          <small>Profil jest lokalny. HRmax aktualizuje strefy od razu, a waga, wiek, płeć i BMR służą do kalkulacji kcal.</small>
          <footer><button value="cancel">Anuluj</button><button value="save" data-live-profile-save>Zapisz</button></footer>
        </form>
      </dialog>
    </div>`;
  document.body.appendChild(overlay);
  return overlay;
}

function buildZoneRows(container, zones) {
  container.replaceChildren(...zones.map((zone) => {
    const row = document.createElement("div");
    row.className = "live-workout-zone-row";
    row.dataset.zone = zone.key;
    row.style.setProperty("--zone-color", zone.color);
    row.innerHTML = `
      <div class="live-workout-zone-copy">
        <strong>${zone.id} · ${zone.label}</strong>
        <span>${zone.min}–${zone.max} BPM</span>
      </div>
      <div class="live-workout-zone-track"><i></i></div>
      <div class="live-workout-zone-time"><strong>00:00</strong><span>/ 0 min</span></div>`;
    return row;
  }));
}

function drawChart(canvas, samples, targetZone, maxHr, now = Date.now()) {
  if (!canvas || typeof canvas.getContext !== "function") return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 16, right: 18, bottom: 24, left: 40 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const minY = 50;
  const maxY = Math.max(200, maxHr + 5);
  const start = now - HISTORY_WINDOW_MS;
  const xFor = (at) => padding.left + ((at - start) / HISTORY_WINDOW_MS) * chartWidth;
  const yFor = (bpm) => padding.top + (1 - (bpm - minY) / (maxY - minY)) * chartHeight;

  ctx.clearRect(0, 0, width, height);
  ctx.font = "11px Inter, system-ui, sans-serif";
  ctx.fillStyle = "rgba(255,255,255,.42)";
  ctx.strokeStyle = "rgba(255,255,255,.08)";
  ctx.lineWidth = 1;
  [60, 100, 140, 180].forEach((bpm) => {
    const y = yFor(bpm);
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.fillText(String(bpm), 8, y + 4);
  });
  ctx.fillText("-5 min", padding.left, height - 5);
  ctx.fillText("teraz", width - padding.right - 30, height - 5);

  if (targetZone) {
    const target = Math.round((targetZone.min + targetZone.max) / 2);
    const y = yFor(target);
    ctx.save();
    ctx.setLineDash([8, 7]);
    ctx.strokeStyle = targetZone.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.restore();
  }

  const visible = samples.filter((sample) => sample.at >= start);
  if (!visible.length) return;
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  visible.slice(1).forEach((sample, index) => {
    const previous = visible[index];
    ctx.strokeStyle = getZoneForHeartRate(sample.heartRate, maxHr)?.color || "#ef4444";
    ctx.beginPath();
    ctx.moveTo(xFor(previous.at), yFor(previous.heartRate));
    ctx.lineTo(xFor(sample.at), yFor(sample.heartRate));
    ctx.stroke();
  });
  if (visible.length === 1) {
    ctx.fillStyle = "#fb7185";
    ctx.beginPath();
    ctx.arc(xFor(visible[0].at), yFor(visible[0].heartRate), 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

export function initLiveWorkoutWidget() {
  const card = document.getElementById("live-workout-card");
  const root = document.getElementById("live-workout-root");
  const openButton = document.getElementById("live-workout-open");
  if (!card || !root || !openButton) return null;
  const focusButton = document.getElementById("live-workout-focus-button")
    || (!openButton.matches("a[href]") ? openButton : null);

  const overlay = document.getElementById("live-workout-focus") || createFocusOverlay();
  const calibrationRoot = overlay.querySelector("[data-live-calibration]") || createCalibrationPanel(document);
  if (!calibrationRoot.isConnected) overlay.querySelector("[data-live-workout-main]")?.before(calibrationRoot);
  const calibrationElements = getCalibrationElements(calibrationRoot);
  const profile = getWorkoutProfile();
  let maxHr = profile.maxHr;
  let zones = getHeartRateZones(maxHr);
  root.innerHTML = `
    <div class="live-workout-widget-summary">
      <div class="live-workout-widget-plan-block">
        <span class="live-workout-widget-overline">DZISIEJSZY TRENING</span>
        <strong data-live-widget-plan>Ładowanie planu…</strong>
        <span data-live-widget-plan-meta></span>
        <div class="live-workout-widget-strength" data-live-widget-strength hidden>
          <span>STRENGTH</span>
          <strong data-live-widget-strength-title>Workout A</strong>
          <small data-live-widget-strength-meta>45–55 min · adaptacja</small>
        </div>
        <div class="live-workout-widget-current">
          <b data-live-widget-interval>Plan jest gotowy</b>
          <span data-live-widget-remaining>Start uruchamia odliczanie</span>
        </div>
      </div>
      <div class="live-workout-widget-monitor">
        <span class="live-workout-widget-overline">HR LIVE</span>
        <strong><b data-live-widget-monitor-hr>--</b><small>BPM</small></strong>
        <span data-live-widget-monitor-state>Czekam na zegarek</span>
        <em data-live-widget-zone>—</em>
      </div>
      <div class="live-workout-widget-goal">
        <span class="live-workout-widget-overline">REALIZACJA DNIA</span>
        <div class="live-workout-widget-goal-ring" data-live-widget-goal-ring role="progressbar" aria-label="Realizacja dzisiejszego treningu" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <b data-live-widget-goal-value>0%</b>
        </div>
      </div>
    </div>
    <div class="live-workout-widget-progress" aria-hidden="true"><i data-live-widget-progress-bar></i></div>
    <div class="live-workout-widget-calorie-average" data-live-widget-calorie-average title="Średnia kalendarzowa: suma aktywnych kcal ze wszystkich treningów od 20.08.2026 podzielona przez wszystkie dni od tej daty włącznie, również dni bez treningu.">
      <span>ŚREDNIA OD 20 SIERPNIA</span>
      <strong><b data-live-widget-calorie-average-value>--</b> kcal/dzień</strong>
      <small><b data-live-widget-calorie-average-total>-- kcal</b> łącznie · <b data-live-widget-calorie-average-days>-- dni</b></small>
    </div>
    <div class="live-workout-widget-rhythm">
      <div class="live-workout-widget-rhythm-head">
        <strong class="live-workout-widget-streak"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.8 2.5c.5 3.2-1.1 4.7-2.5 6.2-1.2 1.3-2.2 2.4-1.4 4.4.5-1.6 1.7-2.5 3-3.5 2-1.5 4.2-3.2 3.5-6.2 2.9 2.4 4.6 5.6 4.1 9.1-.6 4.6-4.1 8-8.6 8-4.8 0-8.4-3.4-8.4-8.1 0-3.8 2.3-7.1 5.8-9.5-.2 2.2.4 3.5 1.3 4.3.9-1.4 1.7-2.8 3.2-4.7Z" fill="currentColor"/></svg><span data-live-widget-streak>0 ukończonych treningów z rzędu</span></strong>
        <span data-live-widget-day-state>Plan oczekuje</span>
      </div>
      <div class="live-workout-widget-week" data-live-widget-week aria-label="Streakometer planu treningowego"></div>
    </div>
    <div class="live-workout-widget-session-actions">
      <button type="button" class="live-workout-widget-start" data-live-widget-start>START CYCLING</button>
      <button type="button" class="live-workout-widget-strength-start" data-live-widget-strength-start>START STRENGTH</button>
      <button type="button" class="live-workout-widget-walk" data-live-widget-walk>START WALKING</button>
    </div>
    <small class="live-workout-widget-last" data-live-widget-last>Ładowanie ostatniego treningu…</small>`;
  const state = {
    plan: cloneFallbackPlan(),
    planSource: "fallback",
    connected: false,
    sessionStatus: "ready",
    sessionId: null,
    externalSession: null,
    heartRate: null,
    lastTelemetryAt: 0,
    lastTelemetryTimestamp: null,
    elapsedSeconds: 0,
    intervalProgressSeconds: [],
    planCompletedAtElapsed: null,
    lastTickAt: performance.now(),
    samples: [],
    zoneSeconds: Object.fromEntries(zones.map((zone) => [zone.key, 0])),
    previousSample: null,
    history: [],
    historyLoading: true,
    calorieRanking: [],
    rankingLoaded: false,
    rankingLastPosition: null,
    selectedPlanDate: null,
    achievedZones: new Set(),
    achievedIntervals: new Set(),
    planAchievementShown: false,
    achievementTimer: null,
    achievementQueue: [],
    achievementActive: false,
    lastSnapshotAt: 0,
    planTracking: { statuses: {}, notes: {}, strengthSessions: cloneStrengthPlan() },
    activeCalories: 0,
    rawKeytelCalories: 0,
    calorieMethod: "indoor_cycling_mi_calibrated_v1",
    calorieCalibration: {
      factor: DEFAULT_INDOOR_CYCLING_CALIBRATION,
      sampleCount: 0,
      calibrated: false,
      meanAbsoluteError: null,
    },
    trainingLoad: 0,
    freeRideMode: false,
    virtualWalkMode: false,
    virtualWalkActiveSeconds: 0,
    virtualWalkOutsideSeconds: 0,
    virtualWalkHighHrSeconds: 0,
    cadenceRpm: null,
    telemetryCadenceRpm: null,
    cadenceSum: 0,
    cadenceSamples: 0,
    sensorSamples: [],
    cscSpeedKmh: null,
    telemetrySpeedKmh: null,
    distanceKm: 0,
    distanceSpeedKmh: 0,
    distanceSource: "unavailable",
    journeyStatus: "loading",
    journeyError: "",
    journeyEngine: null,
    journeyPostcards: new Map(),
    journeyCommittedDistanceKm: 0,
    journeyPreviousLiveDistanceKm: null,
    cscMode: null,
    cscStatus: "disconnected",
    cscSignalStale: false,
    cscDeviceName: null,
    cscReconnectAttempt: 0,
    cscRetryDelayMs: 0,
    calibrationOpen: false,
    calibrations: loadCalibrations(window.localStorage),
    learningSamples: loadLiveWorkoutLearningSamples(window.localStorage),
    calibrationModel: null,
    calibrationModelsByPhase: {},
    calibrationAdvisorZone: "Z2",
    calibrationAdvisorTargetHr: null,
    calibrationAdvisorLevel: Math.max(1, Math.min(8, Number(window.localStorage?.getItem(LIVE_WORKOUT_RESISTANCE_LEVEL_KEY)) || 8)),
    caloriesEstimated: false,
    regularPlan: null,
    adaptiveContext: { steps: null, sleepScore: null, weightTrendKg: null },
    todayStoredSteps: 0,
    optimizedPlan: null,
    adaptiveLoadedFor: "",
    sessionRestored: false,
  };
  let historyRetryTimer = null;
  let planRetryTimer = null;
  let streamReconnectTimer = null;
  let telemetryStream = null;
  let streamSuspended = false;
  let telemetryPollInFlight = false;
  let checkpointInFlight = false;
  let lastCheckpointAt = 0;
  let pendingStartRequestId = null;

  const elements = {
    title: overlay.querySelector("#live-workout-focus-title"),
    connection: overlay.querySelector("[data-live-connection]"),
    feedback: overlay.querySelector("[data-live-feedback]"),
    hr: overlay.querySelector("[data-live-hr]"),
    target: overlay.querySelector("[data-live-target]"),
    zoneNow: overlay.querySelector("[data-live-zone-now]"),
    interval: overlay.querySelector("[data-live-interval]"),
    countdown: overlay.querySelector("[data-live-countdown]"),
    timerLabel: overlay.querySelector("[data-live-timer-label]"),
    next: overlay.querySelector("[data-live-next]"),
    virtualMetrics: overlay.querySelector("[data-live-virtual-metrics]"),
    virtualSteps: overlay.querySelector("[data-live-virtual-steps]"),
    virtualActive: overlay.querySelector("[data-live-virtual-active]"),
    virtualOutside: overlay.querySelector("[data-live-virtual-outside]"),
    cadence: overlay.querySelector("[data-live-cadence]"),
    cadenceConnect: overlay.querySelector("[data-live-cadence-connect]"),
    cscPanel: overlay.querySelector("[data-live-csc-panel]"),
    cscHero: overlay.querySelector(".live-workout-cadence-hero"),
    cscBadge: overlay.querySelector("[data-live-csc-badge]"),
    cscDiagnosticEntries: overlay.querySelector("[data-live-csc-diagnostic-entries]"),
    cscAdvice: overlay.querySelector("[data-live-csc-advice]"),
    journey: overlay.querySelector("[data-live-journey]"),
    journeyDistance: overlay.querySelector("[data-live-journey-distance]"),
    journeyPercent: overlay.querySelector("[data-live-journey-percent]"),
    journeyBar: overlay.querySelector("[data-live-journey-bar]"),
    journeyRide: overlay.querySelector("[data-live-journey-ride]"),
    journeySpeed: overlay.querySelector("[data-live-journey-speed]"),
    journeyPrevious: overlay.querySelector("[data-live-journey-previous]"),
    journeyPreviousMeta: overlay.querySelector("[data-live-journey-previous-meta]"),
    journeyNext: overlay.querySelector("[data-live-journey-next]"),
    journeyNextMeta: overlay.querySelector("[data-live-journey-next-meta]"),
    journeyNextDistance: overlay.querySelector("[data-live-journey-next-distance]"),
    journeyDebug: overlay.querySelector("[data-live-journey-debug]"),
    journeyCheckpoints: overlay.querySelector("[data-live-journey-checkpoints]"),
    guidance: overlay.querySelector("[data-live-guidance]"),
    segments: overlay.querySelector("[data-live-segments]"),
    achievement: overlay.querySelector("[data-live-achievement]"),
    learningToast: overlay.querySelector("[data-live-learning-toast]"),
    learningControl: overlay.querySelector("[data-live-learning-control]"),
    resistanceLevels: overlay.querySelector("[data-live-resistance-levels]"),
    rpmRecommendationZone: overlay.querySelector("[data-live-rpm-recommendation-zone]"),
    rpmRecommendation: overlay.querySelector("[data-live-rpm-recommendation]"),
    rpmTargetGauge: overlay.querySelector("[data-live-rpm-target-gauge]"),
    rpmTargetBand: overlay.querySelector("[data-live-rpm-target-band]"),
    rpmCurrentNeedle: overlay.querySelector("[data-live-rpm-current-needle]"),
    rpmBandLabel: overlay.querySelector("[data-live-rpm-band-label]"),
    learningStatus: overlay.querySelector("[data-live-learning-status]"),
    chartTarget: overlay.querySelector("[data-live-chart-target]"),
    chart: overlay.querySelector("[data-live-chart]"),
    zoneList: overlay.querySelector("[data-live-zones]"),
    maxHr: overlay.querySelector("[data-live-max-hr]"),
    totalTime: overlay.querySelector("[data-live-total-time]"),
    totalClock: overlay.querySelector("[data-live-total-clock]"),
    totalClockLabel: overlay.querySelector("[data-live-total-clock-label]"),
    calories: overlay.querySelector("[data-live-calories]"),
    caloriesHelp: overlay.querySelector("[data-live-calories-help]"),
    calorieRank: overlay.querySelector("[data-live-rank]"),
    calorieRankPosition: overlay.querySelector("[data-live-rank-position]"),
    calorieRankTarget: overlay.querySelector("[data-live-rank-target]"),
    calorieRankTotal: overlay.querySelector("[data-live-rank-total]"),
    calorieRankBar: overlay.querySelector("[data-live-rank-bar]"),
    trimp: overlay.querySelector("[data-live-trimp]"),
    trimpHelp: overlay.querySelector("[data-live-trimp-help]"),
    timeHelp: overlay.querySelector("[data-live-time-help]"),
    planProgress: overlay.querySelector("[data-live-plan-progress]"),
    planProgressLabel: overlay.querySelector("[data-live-plan-progress-label]"),
    planBar: overlay.querySelector("[data-live-plan-bar]"),
    dailySteps: overlay.querySelector("[data-live-daily-steps]"),
    widgetPlan: root.querySelector("[data-live-widget-plan]"),
    widgetPlanMeta: root.querySelector("[data-live-widget-plan-meta]"),
    widgetStrength: root.querySelector("[data-live-widget-strength]"),
    widgetStrengthTitle: root.querySelector("[data-live-widget-strength-title]"),
    widgetStrengthMeta: root.querySelector("[data-live-widget-strength-meta]"),
    widgetMonitorHr: root.querySelector("[data-live-widget-monitor-hr]"),
    widgetMonitorState: root.querySelector("[data-live-widget-monitor-state]"),
    widgetZone: root.querySelector("[data-live-widget-zone]"),
    widgetGoalRing: root.querySelector("[data-live-widget-goal-ring]"),
    widgetGoalValue: root.querySelector("[data-live-widget-goal-value]"),
    widgetProgressBar: root.querySelector("[data-live-widget-progress-bar]"),
    widgetCalorieAverage: root.querySelector("[data-live-widget-calorie-average]"),
    widgetCalorieAverageValue: root.querySelector("[data-live-widget-calorie-average-value]"),
    widgetCalorieAverageTotal: root.querySelector("[data-live-widget-calorie-average-total]"),
    widgetCalorieAverageDays: root.querySelector("[data-live-widget-calorie-average-days]"),
    widgetStreak: root.querySelector("[data-live-widget-streak]"),
    widgetWeek: root.querySelector("[data-live-widget-week]"),
    widgetDayState: root.querySelector("[data-live-widget-day-state]"),
    widgetStart: root.querySelector("[data-live-widget-start]"),
    widgetStrengthStart: root.querySelector("[data-live-widget-strength-start]"),
    widgetWalk: root.querySelector("[data-live-widget-walk]"),
    widgetInterval: root.querySelector("[data-live-widget-interval]"),
    widgetRemaining: root.querySelector("[data-live-widget-remaining]"),
    widgetLast: root.querySelector("[data-live-widget-last]"),
    historyList: overlay.querySelector("[data-live-history-list]"),
    historyRefresh: overlay.querySelector("[data-live-history-refresh]"),
    planKpis: overlay.querySelector("[data-live-plan-kpis]"),
    weekVolume: overlay.querySelector("[data-live-week-volume]"),
    calendar: overlay.querySelector("[data-live-calendar]"),
    dayDetail: overlay.querySelector("[data-live-day-detail]"),
    loadWarning: overlay.querySelector("[data-live-load-warning]"),
    adaptation: overlay.querySelector("[data-live-adaptation]"),
    profileDialog: overlay.querySelector("[data-live-profile-dialog]"),
    profileForm: overlay.querySelector("[data-live-profile-form]"),
    profileOpen: overlay.querySelector("[data-live-profile-open]"),
    backupExport: overlay.querySelector("[data-live-backup-export]"),
    backupImport: overlay.querySelector("[data-live-backup-import]"),
    backupFile: overlay.querySelector("[data-live-backup-file]"),
    fullscreen: overlay.querySelector("[data-live-fullscreen]"),
    closeFocus: overlay.querySelector("[data-live-workout-close]"),
    calibrationOpen: overlay.querySelector("[data-live-calibration-open]"),
  };
  const journeyDebugEnabled = new URLSearchParams(window.location.search).get("journeyDebug") === "1";
  elements.journeyDebug.hidden = !journeyDebugEnabled;
  const sessionActionGate = createExclusiveActionGate((busy) => {
    overlay.querySelectorAll("[data-live-session-action]").forEach((button) => { button.disabled = busy; });
    elements.widgetStart.disabled = busy;
    elements.widgetWalk.disabled = busy;
  });
  buildZoneRows(elements.zoneList, zones);
  elements.maxHr.textContent = `maxHR ${maxHr}`;
  refreshCalibrationModel();
  state.calibrationAdvisorTargetHr = Math.round((zones[1].min + zones[1].max) / 2);

  const calibrationAudio = new AudioNotifier();
  const cadenceMetronome = new CadenceMetronome();
  let calibrationEngine = createCalibrationEngine();
  let learningToastTimer = null;
  const learningEngine = new LiveWorkoutLearningEngine({ onSample: handleLearningSample });
  learningEngine.setLevel(state.calibrationAdvisorLevel);

  const cscSensor = new CscBluetoothSensor({
    onStateChange(snapshot) {
      const changed = state.cscStatus !== snapshot.status || state.cscSignalStale !== Boolean(snapshot.stale);
      state.cscStatus = snapshot.status;
      state.cscMode = snapshot.mode;
      state.cscDeviceName = snapshot.deviceName;
      state.cscSpeedKmh = snapshot.speedKmh;
      state.cscSignalStale = Boolean(snapshot.stale);
      state.cscReconnectAttempt = Number(snapshot.reconnectAttempt) || 0;
      state.cscRetryDelayMs = Number(snapshot.retryDelayMs) || 0;
      if (snapshot.status === "disconnected") state.cadenceRpm = null;
      if (changed) recordCscSample("state", snapshot);
      render();
    },
    onMeasurement(measurement) {
      const rpm = measurement.rpm == null ? Number.NaN : Number(measurement.rpm);
      if (Number.isFinite(rpm) && rpm >= 0 && rpm <= 250) {
        state.cadenceRpm = rpm;
        if (!measurement.inactive && measurement.mode === "CADENCE" && !measurement.stale
          && measurement.parsed?.rpm != null && state.sessionStatus === "running") {
          state.cadenceSum += measurement.parsed.rpm;
          state.cadenceSamples += 1;
        }
      }
      const speedKmh = measurement.speedKmh == null ? Number.NaN : Number(measurement.speedKmh);
      if (Number.isFinite(speedKmh) && speedKmh >= 0 && speedKmh <= 120) state.cscSpeedKmh = speedKmh;
      recordCscSample("measurement", measurement);
      renderFocus();
    },
    onError(error) {
      showLearningToast("BŁĄD CZUJNIKA CSC", formatCscConnectionError(error), "error");
    },
    onDiagnostic(entries) {
      elements.cscDiagnosticEntries.replaceChildren(...entries.map((entry) => {
        const item = document.createElement("li");
        item.textContent = `${new Date(entry.at).toLocaleTimeString("pl-PL")} · ${entry.message}${entry.error ? ` ${entry.error}` : ""}`;
        return item;
      }));
    },
  });

  function recordCscSample(kind, snapshot = cscSensor.snapshot()) {
    if (!state.sessionId || !["running", "paused"].includes(state.sessionStatus)) return;
    state.sensorSamples.push({
      id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      timestamp: Date.now(),
      kind,
      status: snapshot.status,
      mode: snapshot.mode,
      stale: Boolean(snapshot.stale),
      rpm: Number.isFinite(snapshot.rpm) ? snapshot.rpm : null,
      speed_kmh: Number.isFinite(snapshot.speedKmh) ? snapshot.speedKmh : null,
      distance_km: state.distanceKm,
      distance_source: state.distanceSource,
      heart_rate: isFresh() ? state.heartRate : null,
    });
  }

  calibrationElements.advisorHr.value = String(state.calibrationAdvisorTargetHr);
  calibrationElements.advisorLevel.value = String(state.calibrationAdvisorLevel);

  function calibrationSignals(now = Date.now()) {
    const hrAvailable = isFresh(now);
    const cadenceAvailable = state.cscStatus === "connected" && state.cscMode === "CADENCE";
    return {
      hrAvailable,
      cadenceAvailable,
      heartRate: hrAvailable ? state.heartRate : null,
      cadenceRpm: cadenceAvailable && Number.isFinite(state.cadenceRpm) ? state.cadenceRpm : cadenceAvailable ? 0 : null,
    };
  }

  function createCalibrationEngine(config = {}) {
    return new CalibrationEngine({
      ...config,
      onEvent: handleCalibrationEvent,
    });
  }

  function handleCalibrationEvent(event) {
    if (event.type === "started" && !event.missing?.length) calibrationAudio.announcePhase(event.phase);
    if (event.type === "phase-changed") calibrationAudio.announcePhase(event.phase);
    if (event.type === "countdown") calibrationAudio.announceCountdown(event.nextPhase);
    if (event.type === "signal-lost") {
      calibrationAudio.announceSignalLost(event.missing);
      showAchievement("TEST KALIBRACYJNY WSTRZYMANY", `Brak sygnału: ${event.missing.join(" + ")}`);
    }
    if (event.type === "finished" && event.result) {
      try {
        state.calibrations = saveCalibration(event.result, window.localStorage);
        refreshCalibrationModel();
        showAchievement(
          event.status === "partial" ? "ZAPISANO CZĘŚCIOWĄ KALIBRACJĘ" : "KALIBRACJA UKOŃCZONA",
          `${event.result.dataPoints.length}/8 poziomów · ${event.result.hrr.drop60 == null ? "bez HRR60" : `HRR60 −${Math.round(event.result.hrr.drop60)} BPM`}`,
        );
      } catch (error) {
        showAchievement("NIE UDAŁO SIĘ ZAPISAĆ KALIBRACJI", error.message);
      }
    }
  }

  function advisorTargetHr() {
    if (state.calibrationAdvisorZone === "custom") return state.calibrationAdvisorTargetHr;
    const selected = zones.find((zone) => zone.id === state.calibrationAdvisorZone);
    return selected ? Math.round((selected.min + selected.max) / 2) : state.calibrationAdvisorTargetHr;
  }

  function refreshCalibrationModel() {
    const adaptiveCalibration = learningSamplesAsCalibration(state.learningSamples);
    state.calibrationModel = buildCalibrationModel(adaptiveCalibration
      ? [...state.calibrations, adaptiveCalibration]
      : state.calibrations);
    state.calibrationModelsByPhase = Object.fromEntries(["early", "middle", "late"].map((phase) => {
      const phaseCalibration = learningSamplesAsCalibration(
        state.learningSamples.filter((sample) => (sample.sessionPhase || "early") === phase),
      );
      return [phase, buildCalibrationModel(phaseCalibration
        ? [...state.calibrations, phaseCalibration]
        : state.calibrations)];
    }));
    return state.calibrationModel;
  }

  function workoutPhaseLabel(phase) {
    return phase === "early" ? "początek treningu" : phase === "middle" ? "środek treningu" : "późna część treningu";
  }

  function showLearningToast(title, detail, tone = "learning") {
    window.clearTimeout(learningToastTimer);
    elements.learningToast.dataset.tone = tone;
    elements.learningToast.innerHTML = `<strong>${title}</strong><span>${detail}</span>`;
    elements.learningToast.hidden = false;
    elements.learningToast.classList.remove("is-showing");
    void elements.learningToast.offsetWidth;
    elements.learningToast.classList.add("is-showing");
    learningToastTimer = window.setTimeout(() => {
      elements.learningToast.classList.remove("is-showing");
      elements.learningToast.hidden = true;
    }, 3200);
  }

  function handleLearningSample(sample) {
    try {
      state.learningSamples = saveLiveWorkoutLearningSample(sample, window.localStorage);
      refreshCalibrationModel();
      showLearningToast(
        "MODEL ZAPAMIĘTAŁ PRÓBKĘ",
        `P${sample.level} · ${Math.round(sample.averageRpm)} RPM · ${Math.round(sample.averageHr)} BPM · ${sample.context === "steady" ? "HR stabilne" : sample.context === "rising" ? "HR rosło" : "HR spadało"} · ${workoutPhaseLabel(sample.sessionPhase)}`,
      );
      render();
    } catch (error) {
      console.warn("Nie udało się zapisać próbki modelu Live Workout:", error);
    }
  }

  function setResistanceLevel(value, notify = true) {
    const level = Math.max(1, Math.min(8, Number(value) || 8));
    if (level === state.calibrationAdvisorLevel) return;
    state.calibrationAdvisorLevel = level;
    learningEngine.setLevel(level);
    calibrationElements.advisorLevel.value = String(level);
    window.localStorage?.setItem(LIVE_WORKOUT_RESISTANCE_LEVEL_KEY, String(level));
    if (notify) showLearningToast(`USTAWIONO P${level}`, "Okno uczenia zostało rozpoczęte od nowa dla nowego poziomu oporu.");
    render();
  }

  function currentCalibrationAdvice(now = Date.now(), targetHr = advisorTargetHr(), zoneLabel = "CEL") {
    const sessionPhase = getWorkoutLearningPhase(state.elapsedSeconds);
    const contextualModel = state.sessionStatus === "running"
      ? state.calibrationModelsByPhase[sessionPhase] || state.calibrationModel
      : state.calibrationModel;
    if (!contextualModel) return null;
    const recommendation = recommendRpmForLevel(
      contextualModel,
      targetHr,
      state.calibrationAdvisorLevel,
      { preferredRpm: Number.isFinite(state.cadenceRpm) ? state.cadenceRpm : contextualModel.referenceRpm },
    );
    if (!recommendation) return null;
    const currentRpm = state.cscMode === "CADENCE" && Number.isFinite(state.cadenceRpm) ? state.cadenceRpm : null;
    const difference = currentRpm == null ? 0 : recommendation.rpm - currentRpm;
    const learningContext = learningEngine.snapshot().analysis.context;
    const shouldWaitForHr = currentRpm != null && Number.isFinite(state.heartRate) && (
      (learningContext === "rising" && state.heartRate < targetHr - 3 && currentRpm >= recommendation.rpm - 5)
      || (learningContext === "falling" && state.heartRate > targetHr + 3 && currentRpm <= recommendation.rpm + 5)
    );
    const kind = shouldWaitForHr ? "hold" : currentRpm == null ? "setup" : difference > 3 ? "faster" : difference < -3 ? "slower" : "hold";
    const nearest = Math.abs(recommendation.predictedHr - Number(targetHr)) > 5
      ? ` · najbliżej ~${Math.round(recommendation.predictedHr)} BPM`
      : "";
    return {
      ...recommendation,
      kind,
      message: `${zoneLabel} · P${state.calibrationAdvisorLevel} · CEL ${recommendation.rpm} RPM${nearest}${recommendation.estimated ? " · EST." : ""}${state.sessionStatus === "running" ? ` · ${workoutPhaseLabel(sessionPhase).toUpperCase()}` : ""}${shouldWaitForHr ? " · HR JESZCZE DOCHODZI — UTRZYMAJ" : ""}`,
    };
  }

  function renderCalibration(now = Date.now()) {
    overlay.classList.toggle("is-calibration-open", state.calibrationOpen);
    calibrationRoot.hidden = !state.calibrationOpen;
    elements.calibrationOpen.textContent = state.calibrationOpen ? "KALIBRACJA OTWARTA" : "KALIBRACJA ROWERKA";
    if (!state.calibrationOpen) {
      cadenceMetronome.setRpm(0);
      return;
    }
    const signals = calibrationSignals(now);
    const calibrationSnapshot = calibrationEngine.snapshot();
    const configuredRpm = Math.max(60, Math.min(100, Number(calibrationElements.targetRpm.value) || 80));
    const metronomeRpm = ["running", "paused"].includes(calibrationSnapshot.status)
      ? calibrationSnapshot.status === "running" && calibrationSnapshot.phase?.kind !== "baseline"
        ? calibrationSnapshot.phase.targetRpm
        : 0
      : configuredRpm;
    cadenceMetronome.setRpm(metronomeRpm);
    calibrationElements.metronomeTempo.textContent = !cadenceMetronome.enabled
      ? "WYŁĄCZONY"
      : metronomeRpm > 0 ? `${cadenceMetronome.bpm} BPM` : "WYCISZONY";
    const zoneMap = state.calibrationModel
      ? buildCalibrationZoneMap(state.calibrationModel, zones, { level: state.calibrationAdvisorLevel })
      : [];
    renderCalibrationPanel(calibrationElements, {
      snapshot: calibrationSnapshot,
      heartRate: signals.heartRate,
      cadenceRpm: signals.cadenceRpm,
      hrReady: signals.hrAvailable,
      cadenceReady: signals.cadenceAvailable,
      cadenceStale: state.cscSignalStale,
      model: state.calibrationModel,
      calibrations: state.calibrations,
      zones: zoneMap,
      advice: currentCalibrationAdvice(now),
    });
    const resumePlan = getCalibrationResumePlan(state.calibrations);
    calibrationElements.resumeWrap.hidden = !resumePlan;
    if (resumePlan) {
      const completed = resumePlan.completedLevels.length
        ? `ukończone: P${resumePlan.completedLevels.join(", P")}`
        : "brak ukończonych poziomów";
      calibrationElements.resumeText.textContent = resumePlan.nextLevel
        ? `Kontynuuj zapisany test (${completed}). Po nowym baseline i rozgrzewce zaczniesz P${resumePlan.nextLevel} od 00:00.`
        : `Dokończ zapisany test (${completed}). Po baseline i rozgrzewce przejdziesz do schłodzenia.`;
      calibrationElements.start.textContent = calibrationElements.resumeSaved.checked
        ? resumePlan.nextLevel ? `KONTYNUUJ OD POZIOMU ${resumePlan.nextLevel}` : "DOKOŃCZ TEST"
        : "ROZPOCZNIJ NOWY TEST KALIBRACYJNY";
    } else {
      calibrationElements.start.textContent = "ROZPOCZNIJ TEST KALIBRACYJNY";
    }
    drawCalibrationChart(calibrationElements.chart, calibrationEngine.samples, maxHr);
  }

  function calorieExplanation() {
    const formula = profile.sex === "female"
      ? "(-20,4022 + 0,4472×HR − 0,1263×waga + 0,074×wiek) / 4,184"
      : "(-55,0969 + 0,6309×HR + 0,1988×waga + 0,2017×wiek) / 4,184";
    const calibration = state.calorieCalibration;
    const calibrationText = calibration.calibrated
      ? `Mnożnik ${calibration.factor.toFixed(3)} wyliczono metodą najmniejszych kwadratów z ${calibration.sampleCount} Twoich treningów Indoor Cycling z Mi Fitness; średni błąd na tych próbkach to około ${calibration.meanAbsoluteError.toFixed(0)} kcal.`
      : `Używany jest bezpieczny mnożnik startowy ${calibration.factor.toFixed(2)}; personalizacja włączy się po co najmniej 3 treningach Mi Fitness z czasem, kcal i średnim HR.`;
    return `SZACUNEK dla rowerka stacjonarnego, nie pomiar mocy. Najpierw liczony jest surowy wzór Keytela dla ${profile.sex === "female" ? "kobiet" : "mężczyzn"}: kcal/min = ${formula}, a następnie wynik jest korygowany personalnym mnożnikiem Mi Fitness. ${calibrationText} Profil: ${profile.weightKg.toFixed(1)} kg, ${profile.ageYears} lat, maxHR ${maxHr}. Surowy Keytel w tej sesji: ~${state.rawKeytelCalories.toFixed(1)} kcal; wynik po kalibracji: ~${state.activeCalories.toFixed(1)} kcal. Bez pomiaru watów pozostaje to estymacja.`;
  }

  const trainingLoadExplanation = "Obciążenie strefowe to prosty, jawny wskaźnik czasu × intensywności: minuty Z1×1 + Z2×2 + Z3×3 + Z4×4 + Z5×5. Przykład: 10 min w Z2 daje 20 pkt. To NIE jest EPOC ani firmowy Training Load Xiaomi/Garmin; służy do porównywania własnych sesji w tym dashboardzie.";

  function totalPlanSeconds() {
    if (state.freeRideMode || state.virtualWalkMode) return Number.POSITIVE_INFINITY;
    const intervalSeconds = (state.plan.intervals || []).reduce((sum, interval) => (
      sum + Math.max(0, Number(interval.duration_minutes) || 0) * 60
    ), 0);
    return Math.max(1, intervalSeconds || (Number(state.plan.total_duration_minutes) || 0) * 60);
  }

  function ensureIntervalProgress() {
    state.intervalProgressSeconds = (state.plan.intervals || []).map((interval, index) => Math.min(
      Math.max(0, Number(interval.duration_minutes) || 0) * 60,
      Math.max(0, Number(state.intervalProgressSeconds[index]) || 0),
    ));
    return state.intervalProgressSeconds;
  }

  function currentStage() {
    return getIntervalAtProgress(state.plan, ensureIntervalProgress());
  }

  function creditedPlanSeconds() {
    ensureIntervalProgress();
    return state.intervalProgressSeconds.reduce((sum, seconds) => sum + Math.max(0, Number(seconds) || 0), 0);
  }

  function postPlanSeconds() {
    if (state.freeRideMode || state.virtualWalkMode) return state.elapsedSeconds;
    if (state.planCompletedAtElapsed == null) return 0;
    return Math.max(0, state.elapsedSeconds - Number(state.planCompletedAtElapsed));
  }

  function dashboardPlan() {
    return (state.freeRideMode || state.virtualWalkMode) && state.regularPlan
      ? state.regularPlan
      : state.plan;
  }

  function dashboardSchedule(plan = dashboardPlan()) {
    const schedule = Array.isArray(plan?.schedule) ? plan.schedule : [];
    const currentWorkout = plan?.current_workout;
    if (!currentWorkout?.date) return schedule;
    return schedule.some((workout) => workout.date === currentWorkout.date)
      ? schedule.map((workout) => workout.date === currentWorkout.date ? { ...workout, ...currentWorkout } : workout)
      : [...schedule, currentWorkout];
  }

  function localDateKey(date = new Date()) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function dailyPlanCompleted() {
    const plan = dashboardPlan();
    return isWorkoutDaySatisfied(plan?.current_workout, state.history, state.planTracking.statuses);
  }

  function dailyPlanProgress(plan, workout) {
    if (!workout) return 0;
    if (workout.type === "rest") return 100;
    if (isWorkoutDayCompleted(workout, state.history, state.planTracking.statuses)) return 100;
    const plannedSeconds = Math.max(1, Number(workout.duration || plan?.total_duration_minutes || 0) * 60);
    const recordedSeconds = state.history
      .filter((session) => workoutSessionDate(session) === workout.date)
      .reduce((longest, session) => Math.max(longest, Number(session.duration_seconds || 0)), 0);
    const activeSeconds = !state.freeRideMode && !state.virtualWalkMode && state.plan.current_workout?.date === workout.date
      ? creditedPlanSeconds()
      : 0;
    return Math.min(100, Math.max(recordedSeconds, activeSeconds) / plannedSeconds * 100);
  }

  function renderWidgetWeek(days) {
    const stateLabels = {
      completed: "wykonany",
      partial: "częściowy",
      skipped: "pominięty",
      rest: "odpoczynek",
      upcoming: "nadchodzący",
      planned: "zaplanowany",
    };
    const stateMarks = { completed: "✓", partial: "½", skipped: "×", rest: "R", upcoming: "", planned: "•" };
    const fragment = document.createDocumentFragment();
    days.forEach((day) => {
      const date = new Date(`${day.date}T12:00:00`);
      const item = document.createElement("div");
      item.className = `live-workout-widget-week-day is-${day.state}`;
      item.classList.toggle("is-today", day.isToday);
      item.classList.toggle("is-rest-day", day.type === "rest");
      const fullDate = Number.isFinite(date.getTime())
        ? date.toLocaleDateString("pl-PL", { weekday: "long", day: "numeric", month: "long" })
        : day.date;
      item.setAttribute("aria-label", `${fullDate}: ${stateLabels[day.state] || day.state}`);

      const label = document.createElement("span");
      label.textContent = Number.isFinite(date.getTime())
        ? date.toLocaleDateString("pl-PL", { weekday: "narrow" }).replace(".", "")
        : "—";
      const dot = document.createElement("b");
      dot.textContent = stateMarks[day.state] || "";
      const dateNumber = document.createElement("small");
      dateNumber.textContent = Number.isFinite(date.getTime()) ? String(date.getDate()) : "—";
      item.append(label, dot, dateNumber);
      fragment.append(item);
    });
    elements.widgetWeek.replaceChildren(fragment);
  }

  function enterFreeRideMode() {
    if (state.freeRideMode) return;
    state.regularPlan = state.plan;
    state.plan = JSON.parse(JSON.stringify(FREE_RIDE_PLAN));
    state.freeRideMode = true;
  }

  function leaveFreeRideMode() {
    if (!state.freeRideMode) return;
    state.plan = state.regularPlan || cloneFallbackPlan();
    state.regularPlan = null;
    state.freeRideMode = false;
  }

  function enterVirtualWalkMode() {
    if (state.virtualWalkMode) return;
    state.regularPlan = state.plan;
    state.plan = JSON.parse(JSON.stringify(VIRTUAL_WALK_PLAN));
    state.virtualWalkMode = true;
  }

  function leaveVirtualWalkMode() {
    if (!state.virtualWalkMode) return;
    state.plan = state.regularPlan || cloneFallbackPlan();
    state.regularPlan = null;
    state.virtualWalkMode = false;
  }

  function isFresh(now = Date.now()) {
    return state.lastTelemetryAt > 0 && now - state.lastTelemetryAt <= TELEMETRY_FRESH_MS;
  }

  function effectiveStatus(now = Date.now()) {
    if (state.sessionStatus === "running") return "running";
    if (state.sessionStatus === "paused") return "paused";
    if (state.sessionStatus === "finished") return "finished";
    return "ready";
  }

  function journeyLiveDistance() {
    return state.journeyCommittedDistanceKm + state.distanceKm;
  }

  function activeDistanceSignals() {
    const cscFresh = state.cscStatus === "connected" && !state.cscSignalStale;
    const measuredSpeedKmh = cscFresh && state.cscMode === "SPEED"
      ? state.cscSpeedKmh
      : isFresh() ? state.telemetrySpeedKmh : null;
    const cadenceRpm = cscFresh && state.cscMode === "CADENCE" && Number.isFinite(state.cadenceRpm)
      ? state.cadenceRpm
      : isFresh() ? state.telemetryCadenceRpm : null;
    return {
      measuredSpeedKmh,
      cadenceRpm,
      heartRate: isFresh() ? state.heartRate : null,
      maxHeartRate: maxHr,
    };
  }

  function renderJourneyCheckpointList() {
    if (!journeyDebugEnabled || !state.journeyEngine || elements.journeyCheckpoints.dataset.ready === "1") return;
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>#</th><th>Miejsce</th><th>Kraj</th><th>km</th><th>Status</th></tr></thead>";
    const body = document.createElement("tbody");
    state.journeyEngine.checkpoints.forEach((checkpoint) => {
      const row = document.createElement("tr");
      const values = [
        checkpoint.index,
        checkpoint.variantCheckpoint ? `${checkpoint.name} · wariant` : checkpoint.name,
        checkpoint.country,
        Number(checkpoint.routeDistanceKm).toLocaleString("pl-PL", { maximumFractionDigits: 1 }),
        `${checkpoint.variantCheckpoint ? "wariant · " : ""}${Number(checkpoint.routeDistanceKm) <= journeyLiveDistance() ? "osiągnięty" : "przed Tobą"}`,
      ];
      values.forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.appendChild(cell);
      });
      body.appendChild(row);
    });
    table.appendChild(body);
    elements.journeyCheckpoints.replaceChildren(table);
    elements.journeyCheckpoints.dataset.ready = "1";
  }

  function renderJourney() {
    elements.journey.hidden = false;
    elements.journey.dataset.state = state.journeyStatus;
    elements.journey.querySelector("[data-live-journey-activity]").textContent = state.virtualWalkMode ? "TEN SPACER" : "TA JAZDA";
    elements.journeyRide.textContent = state.distanceKm < 1
      ? `+${Math.round(state.distanceKm * 1000).toLocaleString("pl-PL")} m`
      : `+${state.distanceKm.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 2 })} km`;
    const speed = state.virtualWalkMode
      ? { speedKmh: state.heartRate >= VIRTUAL_WALK_HR_MIN && state.heartRate <= VIRTUAL_WALK_HR_MAX && isFresh()
        ? virtualWalkDistanceKm(VIRTUAL_WALK_STEPS_PER_MINUTE * 60) : 0, source: "virtual_walk_steps_v1" }
      : deriveCyclingSpeedKmh(activeDistanceSignals());
    const speedSourceLabel = {
      csc_speed: "CSC",
      cadence_virtual_distance_v1: "RPM",
      heart_rate_virtual_distance_v1: "BPM · est.",
      virtual_walk_steps_v1: "kroki · est.",
    }[speed.source];
    elements.journeySpeed.textContent = speed.source === "unavailable"
      ? "Czekam na RPM lub BPM"
      : `${speed.speedKmh.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} km/h · ${speedSourceLabel}`;
    if (state.journeyStatus !== "ready" || !state.journeyEngine) {
      elements.journeyDistance.textContent = state.journeyStatus === "error" ? "Podróż niedostępna" : "Ładowanie podróży…";
      elements.journeyPercent.textContent = "—";
      elements.journeyBar.style.width = "0%";
      elements.journeyPrevious.textContent = "—";
      elements.journeyPreviousMeta.textContent = "";
      elements.journeyNext.textContent = "—";
      elements.journeyNextMeta.textContent = state.journeyStatus === "error" ? "Trening pozostaje dostępny" : "";
      elements.journeyNextDistance.textContent = "— km";
      return;
    }
    const progress = state.journeyEngine.getPositionAtDistance(journeyLiveDistance());
    const previous = state.journeyEngine.getPreviousCheckpoint(progress.distanceKm);
    const next = state.journeyEngine.getNextCheckpoint(progress.distanceKm);
    const percent = Math.min(100, progress.progress * 100);
    const complete = progress.remainingKm <= 0.005;
    elements.journey.dataset.state = complete ? "complete" : "ready";
    elements.journeyDistance.textContent = `${progress.distanceKm.toLocaleString("pl-PL", {
      minimumFractionDigits: progress.distanceKm < 10 ? 2 : 1,
      maximumFractionDigits: progress.distanceKm < 10 ? 2 : 1,
    })} / ${progress.routeDistanceKm.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} km`;
    elements.journeyPercent.textContent = `${percent.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%`;
    elements.journeyBar.style.width = `${percent}%`;
    elements.journeyPrevious.textContent = previous ? previous.name : "Kraków";
    elements.journeyPreviousMeta.textContent = previous
      ? `#${previous.index} · ${previous.country}`
      : "Polska";
    elements.journeyNext.textContent = next ? next.name : "Santiago de Compostela";
    elements.journeyNextDistance.textContent = complete
      ? "CEL OSIĄGNIĘTY"
      : `${next ? next.distanceAwayKm.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"} km`;
    elements.journeyNextMeta.textContent = complete
      ? "Hiszpania · podróż ukończona"
      : next
        ? `#${next.index} · ${next.country}`
        : "Hiszpania · podróż ukończona";
  }

  let journeyCrossingQueue = Promise.resolve();

  function detectJourneyCrossings() {
    if (state.journeyStatus !== "ready" || !state.journeyEngine) return;
    const current = journeyLiveDistance();
    if (state.journeyPreviousLiveDistanceKm == null) {
      state.journeyPreviousLiveDistanceKm = current;
      return;
    }
    const crossed = state.journeyEngine.getCrossedCheckpoints(state.journeyPreviousLiveDistanceKm, current);
    if (crossed.length) {
      journeyCrossingQueue = journeyCrossingQueue.then(async () => {
        // The postcard may have been replaced in another tab since this workout started.
        await refreshJourneyPostcards().catch(() => {});
        crossed.forEach((checkpoint) => {
          const postcard = state.journeyPostcards.get(checkpoint.id);
          showAchievement(
            checkpoint.name,
            `${checkpoint.country} · Podróż: ${Number(checkpoint.routeDistanceKm).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} km`,
            postcard
              ? {
                eyebrow: `NOWA POCZTÓWKA · PUNKT ${checkpoint.index} / 365`,
                tier: "postcard",
                imageUrl: journeyPostcardImageUrl(checkpoint.id, postcard.uploadedAt),
                durationMs: 10000,
              }
              : { eyebrow: `CHECKPOINT ${checkpoint.index} / 365`, tier: "checkpoint" },
          );
        });
      }).catch((error) => console.warn("Nie udało się pokazać punktu podróży:", error));
    }
    if (crossed.length) {
      elements.journeyCheckpoints.dataset.ready = "";
      renderJourneyCheckpointList();
    }
    state.journeyPreviousLiveDistanceKm = current;
  }

  async function refreshJourneyProgress() {
    const response = await fetch(JOURNEY_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || `HTTP ${response.status}`);
    const payload = await response.json();
    state.journeyCommittedDistanceKm = Math.max(0, Number(payload.committedDistanceKm) || 0);
    state.journeyPreviousLiveDistanceKm = journeyLiveDistance();
    elements.journeyCheckpoints.dataset.ready = "";
    renderJourneyCheckpointList();
  }

  async function loadJourney() {
    state.journeyStatus = "loading";
    renderJourney();
    try {
      const [engine, , postcards] = await Promise.all([
        loadSantiagoJourneyEngine(),
        refreshJourneyProgress(),
        fetchJourneyPostcards().catch(() => []),
      ]);
      state.journeyEngine = engine;
      state.journeyPostcards = new Map(postcards.map((item) => [item.checkpointId, item]));
      state.journeyStatus = "ready";
      state.journeyError = "";
      state.journeyPreviousLiveDistanceKm = journeyLiveDistance();
      renderJourneyCheckpointList();
    } catch (error) {
      state.journeyStatus = "error";
      state.journeyError = error?.message || "Podróż niedostępna";
    }
    renderJourney();
  }

  async function refreshJourneyPostcards() {
    const postcards = await fetchJourneyPostcards();
    state.journeyPostcards = new Map(postcards.map((item) => [item.checkpointId, item]));
  }

  function renderWidget(now = Date.now()) {
    const status = effectiveStatus(now);
    const current = state.freeRideMode || state.virtualWalkMode ? getIntervalAtElapsed(state.plan, state.elapsedSeconds) : currentStage();
    const plan = dashboardPlan();
    const workout = plan?.current_workout;
    const todayKey = localDateKey();
    const schedule = dashboardSchedule(plan);
    const strengthPlanEnabled = isStrengthPlanEnabled(state.planTracking);
    const strengthPlan = strengthPlanEnabled
      ? normalizeStrengthPlan(state.planTracking.strengthSessions || cloneStrengthPlan())
      : [];
    const strengthToday = strengthPlan.find((item) => item.date === todayKey);
    const strengthActual = strengthToday
      ? state.history.find((session) => session.status === "finished" && session.workout_type === "strength" && session.strength_data?.planSessionId === strengthToday.id)
      : null;
    const strengthLaunch = strengthToday && !strengthActual && strengthToday.status !== "skipped"
      ? strengthToday
      : strengthPlan
        .filter((item) => item.date >= todayKey && !["completed", "skipped"].includes(item.status))
        .sort((left, right) => left.date.localeCompare(right.date))[0]
        || { workoutId: "A", workoutVariant: "STANDARD", id: "", date: todayKey };
    const strengthStatus = strengthActual
      ? (strengthActual.strength_data?.summary?.partial ? "częściowy" : "wykonany")
      : strengthToday?.status || "planned";
    const completedToday = isWorkoutDaySatisfied(workout, state.history, state.planTracking.statuses);
    const dayProgress = Math.round(dailyPlanProgress(plan, workout));
    const achievementWorkout = schedule.find((item) => item?.date === todayKey)
      || (workout?.date === todayKey ? workout : null);
    const achievementCompleted = isWorkoutDaySatisfied(achievementWorkout, state.history, state.planTracking.statuses);
    const achievementProgress = Math.round(dailyPlanProgress(plan, achievementWorkout));
    setDailyAchievement("workout", !achievementWorkout ? {
      state: "neutral",
      value: "Brak planu",
      detail: "Nie zaplanowano treningu",
      eligible: false,
    } : achievementWorkout.type === "rest" ? {
      state: "complete",
      value: "Regeneracja",
      detail: "Dzisiaj bez obowiązkowej sesji",
      progress: 100,
    } : {
      state: achievementCompleted ? "complete" : "pending",
      value: WORKOUT_TYPE_LABELS[achievementWorkout.type] || achievementWorkout.name || "Trening",
      detail: `${Number(achievementWorkout.duration || plan?.total_duration_minutes || 0)} min`,
      progress: achievementProgress,
    });
    const fresh = isFresh(now);
    const currentZone = fresh ? getZoneForHeartRate(state.heartRate, maxHr) : null;
    const sessionActive = status === "running" || status === "paused";
    const externalStrengthActive = state.externalSession?.workout_type === "strength"
      && ["running", "paused"].includes(state.externalSession.status);
    const statusLabel = externalStrengthActive
      ? `Strength · ${state.externalSession.status === "paused" ? "pauza" : "w trakcie"}`
      : state.virtualWalkMode
        ? "SPACER"
      : state.freeRideMode
        ? "FREE RIDE"
        : status === "running"
          ? "W trakcie"
          : status === "paused"
            ? "Pauza"
            : completedToday
              ? "Ukończony"
              : status === "finished"
                ? "Zakończony"
                : "Gotowy";
    card.dataset.workoutStatus = externalStrengthActive ? state.externalSession.status : status;
    card.classList.toggle("is-goal-complete", completedToday);
    card.style.setProperty("--live-widget-zone-color", currentZone?.color || "#fb7185");
    card.querySelector("[data-live-widget-status]").textContent = statusLabel;
    elements.widgetPlan.textContent = WORKOUT_TYPE_LABELS[workout?.type] || plan?.plan_title || "Indoor cycling";
    elements.widgetPlanMeta.textContent = workout?.type === "rest"
      ? (workout.purpose || "Regeneracja zaplanowana na dzisiaj")
      : completedToday
        ? "Plan dnia wykonany · wybierz Sesję Spacerową albo Free Ride"
        : `${Number(workout?.duration || plan?.total_duration_minutes || 0)} min · ${workout?.purpose || `${plan?.intervals?.length || 0} interwałów`} · maxHR ${maxHr}`;
    elements.widgetStrength.hidden = !strengthToday;
    elements.widgetStrengthStart.hidden = sessionActive && !externalStrengthActive;
    elements.widgetStrengthStart.textContent = externalStrengthActive ? "WZNÓW STRENGTH" : "QUICK STRENGTH";
    if (strengthToday) {
      elements.widgetStrengthTitle.textContent = `Workout ${strengthToday.workoutId}${strengthToday.workoutVariant === "LIGHT" ? " · LIGHT" : ""}`;
      elements.widgetStrengthMeta.textContent = strengthStatus === "wykonany"
        ? "✓ Sesja ukończona"
        : strengthStatus === "częściowy"
          ? "½ Sesja częściowa"
          : strengthToday.status === "skipped"
            ? "× Sesja pominięta"
            : "45–55 min · rozgrzewka + FBW + core";
      elements.widgetStrengthStart.dataset.workoutId = strengthToday.workoutId;
      elements.widgetStrengthStart.dataset.workoutVariant = strengthToday.workoutVariant;
      elements.widgetStrengthStart.dataset.planSessionId = strengthToday.id;
      elements.widgetStrengthStart.dataset.planDate = strengthToday.date;
    }
    if (!externalStrengthActive) {
      elements.widgetStrengthStart.dataset.workoutId = strengthLaunch.workoutId;
      elements.widgetStrengthStart.dataset.workoutVariant = strengthLaunch.workoutVariant;
      elements.widgetStrengthStart.dataset.planSessionId = strengthLaunch.id;
      elements.widgetStrengthStart.dataset.planDate = strengthLaunch.date;
    }
    const lastWorkout = state.history.find((session) => session.status === "finished");
    elements.widgetLast.textContent = lastWorkout
      ? `Ostatni: ${formatWorkoutDate(lastWorkout.started_at)} · ${formatWorkoutTime(lastWorkout.duration_seconds)} · śr. ${lastWorkout.avg_hr ?? "--"} BPM`
      : "Brak zakończonych treningów";
    elements.widgetMonitorHr.textContent = fresh ? state.heartRate : "--";
    elements.widgetMonitorState.textContent = fresh ? "SYGNAŁ LIVE" : "BRAK ŚWIEŻEGO HR";
    elements.widgetZone.textContent = currentZone ? `${currentZone.id} · ${currentZone.label}` : "Zegarek nie nadaje";
    elements.widgetGoalRing.style.setProperty("--live-workout-goal-progress", `${dayProgress * 3.6}deg`);
    elements.widgetGoalRing.setAttribute("aria-valuenow", String(dayProgress));
    elements.widgetGoalRing.classList.toggle("is-complete", completedToday);
    elements.widgetGoalValue.textContent = workout?.type === "rest" ? "REST" : `${dayProgress}%`;
    elements.widgetProgressBar.style.width = `${dayProgress}%`;
    elements.widgetProgressBar.style.background = completedToday ? "#d4af37" : (currentZone?.color || "#fb7185");
    const activeSessionCalories = sessionActive ? state.activeCalories : 0;
    const calorieAverage = calculateDailyWorkoutCaloriesAverage(state.history, {
      now: new Date(now),
      currentCalories: activeSessionCalories,
    });
    elements.widgetCalorieAverageValue.textContent = Math.round(calorieAverage.averageCalories).toLocaleString("pl-PL");
    elements.widgetCalorieAverageTotal.textContent = `${Math.round(calorieAverage.totalCalories).toLocaleString("pl-PL")} kcal`;
    elements.widgetCalorieAverageDays.textContent = `${calorieAverage.dayCount} ${calorieAverage.dayCount === 1 ? "dzień" : "dni"}`;

    const streak = getWorkoutStreak(schedule, state.history, state.planTracking.statuses, todayKey);
    elements.widgetStreak.textContent = polishWorkoutStreak(streak);
    renderWidgetWeek(buildWorkoutStreakometer(schedule, state.history, state.planTracking.statuses, todayKey));
    elements.widgetDayState.textContent = completedToday
      ? "PLAN DNIA WYKONANY"
      : workout?.type === "rest"
        ? "DZIEŃ REGENERACJI"
        : sessionActive && !state.freeRideMode && !state.virtualWalkMode
          ? `W TRAKCIE · ${dayProgress}%`
          : `${dayProgress}% PLANU DNIA`;

    elements.widgetStart.hidden = status !== "ready" || externalStrengthActive;
    elements.widgetStart.textContent = completedToday ? "START FREE RIDE" : "START CYCLING";
    elements.widgetWalk.hidden = status !== "ready" || externalStrengthActive;
    elements.widgetInterval.textContent = externalStrengthActive
      ? `${state.externalSession.title || "Trening siłowy"} · ${state.externalSession.status === "paused" ? "PAUZA" : "W TRAKCIE"}`
      : sessionActive
      ? state.virtualWalkMode
          ? `SESJA SPACEROWA · +${calculateVirtualWalkSteps(state.virtualWalkActiveSeconds).toLocaleString("pl-PL")} KROKÓW`
        : state.freeRideMode
          ? "FREE RIDE · JAZDA DOWOLNA"
          : current?.interval?.name || "Trening"
      : completedToday
        ? "PLAN DNIA UKOŃCZONY"
        : workout?.type === "rest"
          ? "ODPOCZYNEK"
          : `Start: ${plan?.intervals?.[0]?.name || "trening"}`;
    elements.widgetRemaining.textContent = externalStrengthActive
      ? "Otwórz ponownie tryb Strength, aby kontynuować albo zakończyć sesję"
      : !sessionActive
      ? completedToday
        ? "Wybierz Sesję Spacerową albo Free Ride"
        : workout?.type === "rest"
          ? "Dzisiaj nie ma obowiązkowej sesji"
          : "Start uruchamia licznik i interwały"
      : state.virtualWalkMode
        ? `${formatWorkoutTime(state.virtualWalkActiveSeconds)} w celu · ${formatWorkoutTime(state.virtualWalkOutsideSeconds)} poza`
      : state.freeRideMode
        ? `${formatWorkoutTime(state.elapsedSeconds)} treningu dodatkowego`
        : status === "paused"
          ? `Pauza · ${formatWorkoutTime(current?.remainingSeconds || 0)} pozostało`
          : current?.complete
            ? `plan ukończony · ${formatWorkoutTime(postPlanSeconds())} jazdy swobodnej`
            : `${formatWorkoutTime(current?.remainingSeconds || 0)} do końca interwału`;
  }

  function renderFocus(now = Date.now()) {
    const current = state.freeRideMode || state.virtualWalkMode ? getIntervalAtElapsed(state.plan, state.elapsedSeconds) : currentStage();
    const targetZone = zones.find((zone) => zone.key === current?.interval?.target_zone) || zones[0];
    const currentZone = getZoneForHeartRate(state.heartRate, maxHr);
    const fresh = isFresh(now);
    const inTarget = fresh && isHeartRateInTarget(state.heartRate, targetZone.key, maxHr);
    const status = effectiveStatus(now);
    const sessionActive = status === "running" || status === "paused";
    pinWorkoutHudOpen(status, overlay, document.body);
    elements.closeFocus.hidden = sessionActive;
    const externallyManaged = state.externalSession?.workout_type === "strength"
      && ["running", "paused"].includes(state.externalSession.status);
    const freeRide = state.freeRideMode;
    const virtualWalk = state.virtualWalkMode;
    const completedDailyPlan = !sessionActive && dailyPlanCompleted();
    const planComplete = !freeRide && !virtualWalk && Boolean(current?.complete);
    const zoneFulfillment = calculateZoneFulfillment(state.zoneSeconds, state.plan.target_zones);
    const plannedSeconds = freeRide ? 0 : totalPlanSeconds();
    const completedPlanSeconds = freeRide ? 0 : creditedPlanSeconds();
    const outsideTargetSeconds = freeRide ? 0 : Math.max(0, state.elapsedSeconds - completedPlanSeconds - postPlanSeconds());
    const overtimeSeconds = postPlanSeconds();
    const targetMidpoint = Math.round((targetZone.min + targetZone.max) / 2);
    const guidance = getWorkoutGuidance(
      fresh ? state.heartRate : null,
      targetZone.key,
      maxHr,
      status === "running",
      planComplete,
      Boolean(current?.interval?.optional),
    );
    const virtualGuidance = getVirtualWalkGuidance(
      fresh ? state.heartRate : null,
      state.virtualWalkHighHrSeconds,
      status === "running",
    );
    const virtualSteps = calculateVirtualWalkSteps(state.virtualWalkActiveSeconds);
    renderJourney();

    elements.title.textContent = WORKOUT_TYPE_LABELS[state.plan.current_workout?.type] || state.plan.plan_title;
    elements.connection.textContent = state.connected ? (fresh ? "Sygnał live" : "Czekam na HR") : "SSE rozłączone";
    elements.connection.dataset.state = state.connected ? (fresh ? "live" : "waiting") : "offline";
    elements.hr.textContent = fresh ? String(state.heartRate) : "--";
    elements.feedback.style.setProperty("--workout-accent", fresh && currentZone ? currentZone.color : "#fb7185");
    elements.target.textContent = freeRide
      ? "FREE RIDE · BEZ STREFY DOCELOWEJ"
      : virtualWalk
        ? "SPACER REGENERACYJNY · CEL 95–120 BPM"
      : completedDailyPlan
        ? "PLAN DNIA UKOŃCZONY · AKTYWNOŚĆ DODATKOWA"
      : planComplete
        ? "PLAN WYKONANY · BEZ STREFY DOCELOWEJ"
      : sessionActive
      ? `${targetZone.id} · cel ${targetZone.min}–${targetZone.max} BPM`
      : `PODGLĄD HR · PLAN JESZCZE NIE WYSTARTOWAŁ`;
    elements.zoneNow.textContent = fresh && currentZone
      ? virtualWalk
        ? `${state.heartRate >= VIRTUAL_WALK_HR_MIN && state.heartRate <= VIRTUAL_WALK_HR_MAX ? "KROKI SĄ NALICZANE" : "CZAS POZA STREFĄ SPACEROWĄ"} · ${currentZone.id} ${currentZone.label}`
        : `${currentZone.id} · ${currentZone.label}${freeRide || planComplete ? " · jedź własnym tempem" : inTarget ? " · etap jest zaliczany" : " · etap czeka na docelową strefę"}`
      : "Brak świeżych danych z zegarka";
    elements.feedback.dataset.liveFeedback = virtualWalk
      ? (!fresh || status !== "running" ? "neutral" : virtualGuidance.state === "target" ? "target" : "warning")
      : freeRide || planComplete || !fresh || status !== "running" ? "neutral" : (inTarget ? "target" : "warning");
    elements.guidance.dataset.liveGuidance = completedDailyPlan ? "free" : virtualWalk ? virtualGuidance.state : freeRide || planComplete ? "free" : guidance.key;
    elements.guidance.textContent = status === "paused"
      ? "PAUZA"
      : completedDailyPlan
        ? "PLAN DNIA UKOŃCZONY · WYBIERZ SESJĘ SPACEROWĄ LUB FREE RIDE"
      : virtualWalk
        ? virtualGuidance.label
        : freeRide || planComplete ? "PLAN WYKONANY · JEDŹ WŁASNYM TEMPEM" : guidance.label;
    elements.timerLabel.textContent = !sessionActive
      ? completedDailyPlan ? "Dzisiejszy trening planowy jest ukończony" : "Sesja jeszcze nie rozpoczęta"
      : freeRide
        ? "Czas treningu dodatkowego"
        : virtualWalk
          ? "Czas sesji spacerowej"
        : planComplete
          ? "Jazda swobodna po planie"
          : `Etap ${Number(current?.index || 0) + 1}/${state.plan.intervals.length} · licznik działa tylko w celu`;
    elements.interval.textContent = !sessionActive
      ? completedDailyPlan ? "WYBIERZ DODATKOWĄ AKTYWNOŚĆ" : "Kliknij ZACZNIJ SESJĘ"
      : virtualWalk ? "WIRTUALNY SPACER" : freeRide ? "JAZDA DOWOLNA" : planComplete ? "TRENING SWOBODNY" : (current?.interval?.name || "--");
    elements.countdown.textContent = !sessionActive
      ? (freeRide || completedDailyPlan ? "00:00" : formatWorkoutTime(totalPlanSeconds()))
      : freeRide || virtualWalk
        ? formatWorkoutTime(state.elapsedSeconds)
        : planComplete
        ? `+${formatWorkoutTime(overtimeSeconds)}`
        : formatWorkoutTime(current?.remainingSeconds || 0);
    elements.next.textContent = virtualWalk ? "Lekko · bez długu regeneracyjnego" : completedDailyPlan ? "Sesja Spacerowa albo Free Ride" : freeRide || planComplete ? "Ty decydujesz o tempie i zakończeniu" : !sessionActive ? (state.plan.intervals[0]?.name || "--") : (current?.next?.name || "meta");
    elements.chartTarget.textContent = virtualWalk ? "Cel spaceru: 95–120 BPM" : sessionActive && !planComplete && !freeRide ? `Cel: ${targetMidpoint} BPM` : "Podgląd HR live";
    elements.totalTime.textContent = freeRide || virtualWalk
      ? formatWorkoutTime(state.elapsedSeconds)
      : planComplete
        ? `${formatWorkoutTime(plannedSeconds)} +${formatWorkoutTime(overtimeSeconds)}`
        : `${formatWorkoutTime(completedPlanSeconds)} / ${formatWorkoutTime(plannedSeconds)}`;
    elements.totalClock.textContent = formatWorkoutTime(state.elapsedSeconds);
    elements.totalClockLabel.textContent = virtualWalk
      ? `w celu ${formatWorkoutTime(state.virtualWalkActiveSeconds)} · poza ${formatWorkoutTime(state.virtualWalkOutsideSeconds)}`
      : freeRide
      ? "czas FREE RIDE"
      : planComplete
        ? `plan ${formatWorkoutTime(plannedSeconds)} · swobodnie +${formatWorkoutTime(overtimeSeconds)}`
        : `plan zaliczony ${formatWorkoutTime(completedPlanSeconds)} · poza celem ${formatWorkoutTime(outsideTargetSeconds)}`;
    elements.calories.textContent = `~${state.activeCalories.toFixed(1)} kcal`;
    const calorieRank = currentCalorieRank();
    elements.calorieRank.hidden = !sessionActive;
    if (sessionActive) {
      const medal = calorieRankMedal(calorieRank.position);
      elements.calorieRankPosition.textContent = `${medal ? `${medal} ` : ""}#${calorieRank.position} / ${calorieRank.totalDays}`;
      elements.calorieRankTarget.textContent = calorieRank.isPersonalBest
        ? "JESTEŚ LIDEREM · ŚRUBUJ REKORD!"
        : `BRAKUJE ${calorieRank.caloriesToNext.toFixed(1)} KCAL DO #${calorieRank.position - 1}`;
      elements.calorieRankTotal.textContent = `${calorieRank.todayCalories.toFixed(1)} kcal dzisiaj · rowerek ${Math.round(calorieRank.cyclingPercent)}% · spacer ${Math.round(calorieRank.walkingPercent)}%${calorieRank.next ? ` · przed Tobą ${calorieRank.next.activeCalories.toFixed(1)} kcal` : ""}`;
      const targetCalories = calorieRank.next?.activeCalories || Math.max(1, calorieRank.todayCalories);
      elements.calorieRankBar.style.width = `${Math.min(100, calorieRank.todayCalories / targetCalories * 100)}%`;
      elements.calorieRank.dataset.tier = calorieRankTier(calorieRank.position);
    }
    elements.trimp.textContent = `${state.trainingLoad.toFixed(1)} pkt`;
    elements.caloriesHelp.title = calorieExplanation();
    elements.caloriesHelp.setAttribute("aria-label", `${elements.calories.textContent}. ${calorieExplanation()}`);
    const currentLoadExplanation = virtualWalk
      ? "Sesja Spacerowa ma celowo symboliczne obciążenie: 0,25 pkt za minutę. Nie jest wliczana do realizacji planu cardio ani długu regeneracyjnego."
      : trainingLoadExplanation;
    elements.trimpHelp.title = currentLoadExplanation;
    elements.trimpHelp.setAttribute("aria-label", `${elements.trimp.textContent}. ${currentLoadExplanation}`);
    elements.timeHelp.title = virtualWalk
      ? "Wirtualne kroki naliczają się wyłącznie przy HR 95–120 BPM: 105 kroków za każdą pełną minutę w tej strefie."
      : freeRide
      ? "FREE RIDE nie ma limitu planu — cały czas jest treningiem dodatkowym."
      : `Każdy etap ma własny licznik. Odlicza się tylko wtedy, gdy faktyczne HR jest w strefie celu tego etapu. Czas poza celem nadal trafia do faktycznej strefy i czasu łącznego, ale nie uruchamia kolejnego etapu. Po zaliczeniu wszystkich etapów dalsza jazda jest swobodna.`;

    const progress = freeRide || virtualWalk ? 0 : Math.min(100, (completedPlanSeconds / totalPlanSeconds()) * 100);
    const dailyStepsGoal = calculateDailyStepsGoal(
      state.todayStoredSteps,
      virtualWalk && sessionActive ? virtualSteps : 0,
    );
    elements.planProgressLabel.textContent = virtualWalk ? "DZIENNY CEL 10 000 KROKÓW" : "Postęp planu";
    elements.planProgress.textContent = virtualWalk
      ? `${dailyStepsGoal.percent}%`
      : freeRide
      ? "FREE"
      : planComplete
        ? `100% · +${formatWorkoutTime(overtimeSeconds)}`
        : `${Math.round(progress)}%`;
    elements.planBar.style.width = `${virtualWalk ? dailyStepsGoal.barPercent : progress}%`;
    elements.planBar.classList.toggle("is-steps", virtualWalk);
    elements.dailySteps.hidden = !virtualWalk;
    elements.dailySteps.textContent = `Dzisiaj łącznie: ${Math.round(dailyStepsGoal.total).toLocaleString("pl-PL")} / 10 000 kroków · w tej sesji +${virtualSteps.toLocaleString("pl-PL")}`;
    elements.virtualMetrics.hidden = !virtualWalk;
    elements.virtualSteps.textContent = `+${virtualSteps.toLocaleString("pl-PL")}`;
    elements.virtualActive.textContent = formatWorkoutTime(state.virtualWalkActiveSeconds);
    elements.virtualOutside.textContent = formatWorkoutTime(state.virtualWalkOutsideSeconds);
    const cscConnected = state.cscStatus === "connected";
    const cscReconnecting = state.cscStatus === "reconnecting";
    const cscReadingVisible = cscConnected || cscReconnecting;
    elements.cscPanel.dataset.cscStatus = state.cscStatus;
    elements.cscPanel.dataset.cscMode = state.cscMode || "none";
    elements.cscHero.dataset.cscStatus = state.cscStatus;
    elements.cscHero.dataset.cscSignal = state.cscSignalStale ? "stale" : "fresh";
    elements.cscHero.title = state.cscSignalStale
      ? "Chwilowy brak świeżych danych CSC — wyświetlam ostatni poprawny pomiar."
      : "";
    elements.cscBadge.textContent = cscReconnecting
      ? `MAGENE CSC · ODZYSKIWANIE · PRÓBA ${state.cscReconnectAttempt} ${state.cscRetryDelayMs > 0
        ? `ZA ${Math.ceil(state.cscRetryDelayMs / 1000)} S` : "TRWA…"}`
      : state.cscStatus === "connecting"
        ? "MAGENE CSC · ŁĄCZENIE…"
        : cscConnected
          ? `MAGENE CSC POŁĄCZONY${state.cscDeviceName ? ` · ${state.cscDeviceName}` : ""}`
          : "MAGENE CSC ROZŁĄCZONY";
    elements.cadence.textContent = !cscReadingVisible || state.cscMode === "SPEED"
      ? "--"
      : Number.isFinite(state.cadenceRpm) ? String(Math.round(state.cadenceRpm)) : "0";
    const recommendationTargetHr = virtualWalk
      ? Math.round((VIRTUAL_WALK_HR_MIN + VIRTUAL_WALK_HR_MAX) / 2)
      : !freeRide && !planComplete
        ? targetMidpoint
        : advisorTargetHr();
    const recommendationZoneLabel = virtualWalk
      ? `SPACER ${VIRTUAL_WALK_HR_MIN}–${VIRTUAL_WALK_HR_MAX}`
      : !freeRide && !planComplete
        ? targetZone.id
        : state.calibrationAdvisorZone === "custom" ? "WŁASNY CEL" : state.calibrationAdvisorZone;
    const liveCalibrationAdvice = currentCalibrationAdvice(now, recommendationTargetHr, recommendationZoneLabel);
    elements.cscAdvice.hidden = state.calibrationOpen
      || !liveCalibrationAdvice
      || state.cscStatus !== "connected"
      || state.cscMode !== "CADENCE";
    elements.cscAdvice.textContent = liveCalibrationAdvice?.message || "";
    elements.cscAdvice.dataset.state = liveCalibrationAdvice?.kind || "idle";
    elements.learningControl.hidden = false;
    elements.resistanceLevels.querySelectorAll("[data-live-resistance-level]").forEach((button) => {
      const selected = Number(button.dataset.liveResistanceLevel) === state.calibrationAdvisorLevel;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    elements.rpmRecommendationZone.textContent = `${recommendationZoneLabel} · ŚRODEK ${recommendationTargetHr} BPM · P${state.calibrationAdvisorLevel}`;
    elements.rpmRecommendation.textContent = liveCalibrationAdvice
      ? `${liveCalibrationAdvice.rpm} RPM${liveCalibrationAdvice.estimated ? " · EST." : ""}`
      : "BRAK MODELU";
    const suggestedRpm = Number(liveCalibrationAdvice?.rpm);
    const hasSuggestedRpm = Number.isFinite(suggestedRpm) && suggestedRpm > 0;
    const suggestedRpmLow = hasSuggestedRpm
      ? Math.max(0, Math.round(suggestedRpm - LIVE_RPM_TARGET_TOLERANCE))
      : 0;
    const suggestedRpmHigh = hasSuggestedRpm
      ? Math.min(LIVE_RPM_GAUGE_MAX, Math.round(suggestedRpm + LIVE_RPM_TARGET_TOLERANCE))
      : 0;
    const currentRpm = Number(state.cadenceRpm);
    const hasCurrentRpm = cscConnected
      && state.cscMode === "CADENCE"
      && Number.isFinite(currentRpm)
      && currentRpm >= 0;
    elements.rpmTargetBand.hidden = !hasSuggestedRpm;
    elements.rpmTargetBand.style.left = `${suggestedRpmLow / LIVE_RPM_GAUGE_MAX * 100}%`;
    elements.rpmTargetBand.style.width = `${Math.max(0, suggestedRpmHigh - suggestedRpmLow) / LIVE_RPM_GAUGE_MAX * 100}%`;
    elements.rpmCurrentNeedle.hidden = !hasCurrentRpm;
    elements.rpmCurrentNeedle.style.left = `${Math.min(LIVE_RPM_GAUGE_MAX, Math.max(0, currentRpm || 0)) / LIVE_RPM_GAUGE_MAX * 100}%`;
    elements.rpmBandLabel.textContent = hasSuggestedRpm
      ? `CEL ${suggestedRpmLow}–${suggestedRpmHigh} RPM`
      : "CEL --";
    const rpmGaugeState = !hasSuggestedRpm
      ? "idle"
      : !hasCurrentRpm
        ? "waiting"
        : currentRpm < suggestedRpmLow
          ? "low"
          : currentRpm > suggestedRpmHigh
            ? "high"
            : "target";
    elements.rpmTargetGauge.dataset.state = rpmGaugeState;
    elements.rpmTargetGauge.setAttribute(
      "aria-label",
      hasSuggestedRpm
        ? `Sugerowany zakres ${suggestedRpmLow} do ${suggestedRpmHigh} RPM${hasCurrentRpm ? `, aktualnie ${Math.round(currentRpm)} RPM` : ", brak bieżącego odczytu"}`
        : "Brak sugerowanego zakresu RPM",
    );
    const learningSignalReady = cscConnected
      && state.cscMode === "CADENCE"
      && !state.cscSignalStale
      && fresh;
    const learningSnapshot = learningEngine.snapshot();
    const learningWindowSeconds = Math.min(120, learningSnapshot.durationSeconds);
    const learningContextLabel = learningSnapshot.analysis.context === "steady"
      ? "HR stabilne"
      : learningSnapshot.analysis.context === "rising"
        ? "HR rośnie"
        : learningSnapshot.analysis.context === "falling" ? "HR spada" : "zbieram dane";
    const learningReasonLabel = {
      "cadence-gaps": "za dużo przerw, ale historia nie została skasowana",
      "cadence-variable": "duża zmienność RPM — szukam lepszego fragmentu",
      "hr-chaotic": "HR zmienia się nieregularnie — obserwuję dalej",
      accepted: `${learningContextLabel} · okno nadaje się do modelu`,
    }[learningSnapshot.analysis.reason];
    elements.learningStatus.textContent = status !== "running"
      ? `Uczenie czeka na aktywną sesję · zapisano ${state.learningSamples.reduce((sum, sample) => sum + Math.max(1, Number(sample.observationCount) || 1), 0)} użytecznych odcinków`
      : !learningSignalReady
        ? "Uczenie czeka na świeże HR i RPM"
        : state.elapsedSeconds < 480
          ? `Rozgrzewka modelu · zbieranie ruszy za ${formatWorkoutTime(480 - state.elapsedSeconds)}`
          : learningWindowSeconds < 117
            ? `Analizuję każdą sekundę P${state.calibrationAdvisorLevel} · ${formatWorkoutTime(learningWindowSeconds)} / 02:00`
            : `${learningReasonLabel || learningContextLabel} · ${workoutPhaseLabel(getWorkoutLearningPhase(state.elapsedSeconds))} · skoki są odrzucane`;
    elements.cadenceConnect.textContent = state.cscStatus === "connecting"
      ? "ANULUJ ŁĄCZENIE"
      : cscReconnecting ? "WYBIERZ PONOWNIE" : cscConnected ? "ROZŁĄCZ" : "POŁĄCZ CSC";
    elements.cadenceConnect.disabled = false;
    const segmentLayout = calculateSegmentLayout(state.plan.intervals);
    elements.segments.innerHTML = segmentLayout.map((segment, index) => {
      const segmentSeconds = Math.max(0, Number(segment.duration_minutes) || 0) * 60;
      const segmentDone = Number(state.intervalProgressSeconds[index] || 0) >= segmentSeconds;
      return `
      <i class="${segmentDone ? "is-done" : index === (current?.index ?? -1) && sessionActive && !planComplete ? "is-current" : ""}"
         style="--segment-color:${zones.find((zone) => zone.key === segment.target_zone)?.color || "#777"};width:${segment.percent}%"
         title="${segment.name} · ${segmentDone ? "UKOŃCZONY" : index === current?.index ? `${formatWorkoutTime(current.remainingSeconds)} pozostało w strefie celu` : "oczekuje"}"><span>${segment.name}${segmentDone ? " ✓" : ""}</span></i>`;
    }).join("");

    zones.forEach((zone) => {
      const row = elements.zoneList.querySelector(`[data-zone="${zone.key}"]`);
      const spent = state.zoneSeconds[zone.key] || 0;
      const targetMinutes = Math.max(0, Number(state.plan.target_zones?.[zone.key]) || 0);
      const fulfillment = zoneFulfillment.zones[zone.key];
      const zoneProgress = targetMinutes ? Math.min(100, fulfillment.creditedSeconds / fulfillment.targetSeconds * 100) : 0;
      row.classList.toggle("is-current", fresh && currentZone?.key === zone.key);
      row.classList.toggle("has-excess", fulfillment.excessSeconds > 0);
      row.querySelector(".live-workout-zone-track i").style.width = `${zoneProgress}%`;
      row.querySelector(".live-workout-zone-time strong").textContent = formatWorkoutTime(spent);
      row.querySelector(".live-workout-zone-time span").textContent = fulfillment.excessSeconds > 0
        ? `/ ${targetMinutes} min · +${formatWorkoutTime(fulfillment.excessSeconds)}`
        : zone.key === "vo2max"
          ? `/ ≤ ${targetMinutes} min`
          : `/ ${targetMinutes} min`;
      row.title = targetMinutes > 0
        ? `${zone.id}: ${formatWorkoutTime(fulfillment.creditedSeconds)} zaliczone z ${formatWorkoutTime(fulfillment.targetSeconds)} planu${fulfillment.excessSeconds > 0 ? `; +${formatWorkoutTime(fulfillment.excessSeconds)} nadmiaru` : ""}. Czas jest przypisywany według faktycznego HR, niezależnie od zaplanowanego interwału.`
        : `${zone.id}: ${formatWorkoutTime(spent)} poza planem — cały ten czas jest nadmiarem.`;
    });

    overlay.querySelectorAll("[data-live-session-action]").forEach((button) => {
      const action = button.dataset.liveSessionAction;
      if (action === "start") button.textContent = dailyPlanCompleted() ? "START FREE RIDE" : "START CYCLING";
      if (action === "virtual-walk") button.textContent = "START WALKING";
      if (action === "finish") button.textContent = "ZAKOŃCZ";
      button.hidden = externallyManaged || !(
        (action === "start" && status === "ready")
        || (action === "virtual-walk" && status === "ready")
        || (action === "pause" && status === "running")
        || (action === "resume" && status === "paused")
        || (action === "finish" && sessionActive)
        || (action === "cancel" && sessionActive)
      );
    });

    const chartTargetZone = virtualWalk
      ? { min: VIRTUAL_WALK_HR_MIN, max: VIRTUAL_WALK_HR_MAX, color: "#3b82f6" }
      : sessionActive && !planComplete && !freeRide ? targetZone : null;
    if (!overlay.hidden) drawChart(elements.chart, state.samples, chartTargetZone, maxHr, now);
  }

  function render(now = Date.now()) {
    renderWidget(now);
    renderFocus(now);
    renderCalibration(now);
  }

  function historyDate(session) {
    if (session?.plan_id === FREE_RIDE_PLAN.plan_id || ["virtual_walk", "strength"].includes(session?.workout_type)) return "";
    if (session?.plan_date) return session.plan_date;
    const timestamp = Number(session?.started_at);
    if (!Number.isFinite(timestamp)) return "";
    const date = new Date(timestamp);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function actualSessionDate(session) {
    const timestamp = Number(session?.started_at);
    if (!Number.isFinite(timestamp)) return "bez-daty";
    const date = new Date(timestamp);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function planStatus(workout) {
    if (workout.type === "rest") return "rest";
    const actual = state.history.find((session) => session.status === "finished" && historyDate(session) === workout.date);
    if (actual) {
      if (actual.plan_completed === true) return "completed";
      if (actual.plan_completed === false) return "partial";
      const adherence = Number(actual.duration_seconds || 0) / Math.max(1, Number(workout.duration || 0) * 60);
      return adherence >= .9 ? "completed" : "partial";
    }
    return state.planTracking.statuses?.[workout.date] || "planned";
  }

  function savePlanTracking() {
    saveFileBackedSetting({
      name: "live-workout-plan",
      storageKey: PLAN_TRACKING_KEY,
      value: state.planTracking,
    });
  }

  async function loadPlanTracking() {
    state.planTracking = await loadFileBackedSetting({
      name: "live-workout-plan",
      storageKey: PLAN_TRACKING_KEY,
      fallback: { statuses: {}, notes: {}, strengthSessions: cloneStrengthPlan() },
      normalize: (value) => ({
        ...(value && typeof value === "object" ? value : {}),
        statuses: value?.statuses && typeof value.statuses === "object" ? value.statuses : {},
        notes: value?.notes && typeof value.notes === "object" ? value.notes : {},
        strengthSessions: normalizeStrengthPlan(value?.strengthSessions || cloneStrengthPlan()),
      }),
    });
    renderPlanOverview();
    renderWidget();
  }

  function renderPlanOverview() {
    const schedule = Array.isArray(state.plan.schedule) ? state.plan.schedule : [];
    if (!schedule.length) return;
    const today = new Date();
    const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    if (!state.selectedPlanDate) state.selectedPlanDate = schedule.some((item) => item.date === todayKey)
      ? todayKey
      : schedule[0].date;
    const completedDates = new Set(schedule.filter((workout) => planStatus(workout) === "completed").map((workout) => workout.date));
    const metrics = getPlanMetrics(schedule, state.history);
    metrics.completedWorkouts = schedule.filter((workout) => planStatus(workout) === "completed").length;
    const dayIndex = Math.max(0, schedule.findIndex((item) => item.date === todayKey));
    elements.planKpis.innerHTML = `
      <span><strong>Dzień ${dayIndex + 1}/${schedule.length}</strong><small>dzisiaj</small></span>
      <span><strong>${metrics.completedWorkouts}/${metrics.plannedWorkouts}</strong><small>ukończone</small></span>
      <span><strong>${Math.round(metrics.actualMinutes)}/${metrics.plannedMinutes} min</strong><small>wykonano / plan</small></span>
      <span><strong>${Math.round(metrics.progress)}%</strong><small>realizacja</small></span>`;

    const weeks = Array.isArray(state.plan.weeks) ? state.plan.weeks : [];
    const completedHistory = state.history.filter((session) => session.status === "finished");
    const highIntensityDates = schedule.filter((workout) => {
      const actual = completedHistory.find((session) => historyDate(session) === workout.date);
      if (!actual) return false;
      const highZoneSeconds = Number(actual.zones?.anaerobic || 0) + Number(actual.zones?.vo2max || 0);
      return workout.type === "intervals" || (Number(actual.duration_seconds) > 0 && highZoneSeconds / Number(actual.duration_seconds) >= .2);
    }).map((workout) => workout.date);
    const hasThreeHighDays = highIntensityDates.some((workoutDate, index) => {
      if (index < 2) return false;
      const first = new Date(`${highIntensityDates[index - 2]}T12:00:00`);
      const last = new Date(`${workoutDate}T12:00:00`);
      return Math.round((last - first) / 86400000) === 2;
    });
    const weeklyOverload = weeks.some((week) => {
      const actualMinutes = completedHistory
        .filter((session) => historyDate(session) >= week.start_date && historyDate(session) <= week.end_date)
        .reduce((sum, session) => sum + Number(session.duration_seconds || 0) / 60, 0);
      return actualMinutes > Number(week.planned_minutes) * 1.25;
    });
    const painMentioned = completedHistory.some((session) => /\b(ból|boli|pain)\b/i.test(String(session.notes || "")));
    elements.loadWarning.hidden = !(hasThreeHighDays || weeklyOverload || painMentioned);
    elements.loadWarning.textContent = "Obciążenie treningowe wyraźnie wzrosło. Rozważ lżejszą sesję przed dodaniem kolejnej wysokiej intensywności.";
    const maxWeek = Math.max(...weeks.map((week) => Number(week.planned_minutes) || 0), 1);
    const phaseDescriptions = {
      adaptacja: "Spokojne wejście w regularność i sprawdzenie tolerancji obciążenia.",
      "objętość": "Najwięcej powtarzalnej pracy, głównie Z2–Z3, wspierającej redukcję.",
      szczyt: "Największy bodziec planu, ale nadal kontrolowany przez zmęczenie i sen.",
      deload: "Celowe zmniejszenie objętości, żeby organizm przyswoił wcześniejszą pracę.",
      "domknięcie": "Krótki finał i ocena efektów przed kolejnym cyklem.",
    };
    elements.weekVolume.innerHTML = `<strong><span>Tygodniowa objętość</span><small>minuty treningu / tydzień</small></strong><div>${weeks.map((week) => `
      <span title="${week.theme}: ${week.planned_minutes} min. ${phaseDescriptions[String(week.theme).toLowerCase()] || "Etap bieżącego planu cardio."}">
        <div class="live-workout-week-bar"><b>${week.planned_minutes} min</b><i style="height:${Math.max(8, week.planned_minutes / maxWeek * 100)}%"></i></div>
        <small>${week.label}<em>${week.theme}</em></small>
      </span>`).join("")}</div>`;

    elements.calendar.replaceChildren(...weeks.map((week) => {
      const block = document.createElement("section");
      block.className = "live-workout-week";
      const days = schedule.filter((workout) => workout.date >= week.start_date && workout.date <= week.end_date);
      block.innerHTML = `<header><strong>${week.label} · ${week.theme}</strong><span>${week.planned_minutes} min</span></header><div></div>`;
      const daysContainer = block.querySelector("div");
      daysContainer.replaceChildren(...days.map((workout) => {
        const date = new Date(`${workout.date}T12:00:00`);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "live-workout-day";
        button.dataset.planDate = workout.date;
        button.classList.toggle("is-selected", workout.date === state.selectedPlanDate);
        button.classList.toggle("is-today", workout.date === todayKey);
        const workoutStatus = planStatus(workout);
        button.classList.toggle("is-completed", workoutStatus === "completed");
        button.classList.toggle("is-partial", workoutStatus === "partial");
        button.classList.toggle("is-skipped", workoutStatus === "skipped");
        button.classList.toggle("is-rest", workout.type === "rest");
        const workoutZones = zones.map((zone) => ({ zone, minutes: Number(workout.zones?.[zone.key]) || 0 }));
        const dominant = workout.type === "rest"
          ? null
          : workoutZones.reduce((best, item) => item.minutes > best.minutes ? item : best, workoutZones[0]);
        button.style.setProperty("--day-intensity-color", dominant?.zone.color || "#555");
        const zoneStrip = workout.type === "rest" ? "" : `<div class="live-workout-day-intensity" aria-label="Rozkład stref">${workoutZones.map(({ zone, minutes }) => (
          minutes > 0 ? `<i style="--zone-color:${zone.color};width:${minutes / Math.max(1, Number(workout.duration)) * 100}%" title="${zone.id}: ${minutes} min"></i>` : ""
        )).join("")}</div>`;
        button.title = workout.type === "rest"
          ? "Planowany odpoczynek"
          : `Dominująca intensywność: ${dominant.zone.id} · ${dominant.zone.label}. Kliknij, aby zobaczyć pełny rozkład stref.`;
        button.innerHTML = `<span>${new Intl.DateTimeFormat("pl-PL", { weekday: "short" }).format(date)}</span>
          <strong>${date.getDate()}</strong><b>${WORKOUT_TYPE_LABELS[workout.type]}</b>
          ${zoneStrip}<small>${workout.type === "rest" ? "REST" : `${workout.duration} min · głównie ${dominant.zone.id}`}</small>
          <i>${workoutStatus === "completed" ? "✓ Wykonany" : workoutStatus === "partial" ? "Częściowy" : workoutStatus === "skipped" ? "Pominięty" : workout.date === todayKey ? "Dzisiaj" : ""}</i>`;
        return button;
      }));
      return block;
    }));

    const selected = schedule.find((item) => item.date === state.selectedPlanDate) || schedule[0];
    const actual = state.history.find((item) => item.status === "finished" && historyDate(item) === selected.date);
    const total = Math.max(1, Number(selected.duration) || 0);
    const zoneBar = zones.map((zone) => {
      const minutes = Number(selected.zones?.[zone.key]) || 0;
      return `<i style="--zone-color:${zone.color};width:${minutes / total * 100}%" title="${zone.label}: ${minutes} min"></i>`;
    }).join("");
    const zoneRows = zones.filter((zone) => Number(selected.zones?.[zone.key]) > 0).map((zone) => {
      const minutes = Number(selected.zones[zone.key]);
      return `<span style="--zone-color:${zone.color}"><b>${zone.id} · ${zone.label}</b><strong>${minutes} min</strong><small>${Math.round(minutes / total * 100)}%</small></span>`;
    }).join("");
    const selectedStatus = planStatus(selected);
    const statusLabel = { completed: "UKOŃCZONY", partial: "CZĘŚCIOWY", skipped: "POMINIĘTY", rest: "ODPOCZYNEK", planned: "PLAN" }[selectedStatus];
    elements.dayDetail.innerHTML = `
      <header><div><span>${selected.date}</span><h4>${WORKOUT_TYPE_LABELS[selected.type]} · ${selected.duration} min</h4></div><b>${statusLabel}</b></header>
      <p>${selected.purpose}</p>
      ${selected.type === "rest" ? "" : `<div class="live-workout-target-bar">${zoneBar}</div><div class="live-workout-target-grid">${zoneRows}</div>`}
      ${actual ? `<footer><strong>CEL / WYKONANIE</strong><span>${selected.duration} min / ${Math.round(Number(actual.duration_seconds || 0) / 60)} min</span><span>Śr. HR ${actual.avg_hr ?? "--"} · Max HR ${actual.max_hr ?? "--"}</span></footer>` : selected.type === "rest" ? "" : `<footer class="live-workout-plan-status-actions"><strong>Status ręczny</strong><button type="button" data-plan-status="completed">Ukończony</button><button type="button" data-plan-status="partial">Częściowy</button><button type="button" data-plan-status="skipped">Pominięty</button><button type="button" data-plan-status="planned">Wyczyść</button></footer>`}`;
  }

  function showAchievement(title, detail, options = {}) {
    state.achievementQueue.push({
      title,
      detail,
      tier: options.tier || "standard",
      eyebrow: options.eyebrow || "ACHIEVEMENT ODBLOKOWANY",
      imageUrl: options.imageUrl || "",
      durationMs: Number(options.durationMs) || 0,
    });
    playNextAchievement();
  }

  function playNextAchievement() {
    if (state.achievementActive) return;
    const next = state.achievementQueue.shift();
    if (!next) return;
    state.achievementActive = true;
    window.clearTimeout(state.achievementTimer);
    elements.achievement.dataset.tier = next.tier;
    const particleCount = ["checkpoint", "postcard"].includes(next.tier) ? 0 : next.tier === "podium" ? 36 : next.tier === "top10" ? 26 : 18;
    const image = next.imageUrl ? `<img src="${escapeAchievementHtml(next.imageUrl)}" alt="" />` : "";
    elements.achievement.innerHTML = `${image}<div><span>${escapeAchievementHtml(next.eyebrow)}</span><strong>${escapeAchievementHtml(next.title)}</strong><small>${escapeAchievementHtml(next.detail)}</small></div>${Array.from({ length: particleCount }, (_, index) => `<i style="--particle:${index}"></i>`).join("")}`;
    elements.achievement.hidden = false;
    elements.achievement.classList.remove("is-showing");
    void elements.achievement.offsetWidth;
    elements.achievement.classList.add("is-showing");
    state.achievementTimer = window.setTimeout(() => {
      elements.achievement.classList.remove("is-showing");
      elements.achievement.hidden = true;
      state.achievementActive = false;
      playNextAchievement();
    }, next.durationMs || (next.tier === "checkpoint" ? 3600 : next.tier === "podium" ? 5600 : next.tier === "top10" ? 4800 : 4200));
  }

  function currentCalorieRank() {
    return calculateLiveCalorieRank(state.calorieRanking, {
      date: localDateKey(),
      liveCalories: ["running", "paused"].includes(state.sessionStatus) ? state.activeCalories : 0,
      workoutType: state.virtualWalkMode ? "virtual_walk" : "indoor_cycling",
    });
  }

  function checkCalorieRankAchievements() {
    if (state.sessionStatus !== "running" || state.activeCalories <= 0) return;
    const rank = currentCalorieRank();
    if (state.rankingLastPosition == null) {
      state.rankingLastPosition = rank.position;
      return;
    }
    if (rank.position >= state.rankingLastPosition) return;
    const tier = calorieRankTier(rank.position);
    const medal = calorieRankMedal(rank.position);
    const title = tier === "podium"
      ? `${medal} PODIUM · MIEJSCE #${rank.position}`
      : tier === "top10"
        ? `🔥 WBIJASZ DO TOP 10 · #${rank.position}`
        : `WYNIK POBITY · AWANS NA #${rank.position}`;
    const detail = rank.position === 1
      ? `${rank.todayCalories.toFixed(1)} kcal dzisiaj · nowy najlepszy dzień!`
      : `${rank.todayCalories.toFixed(1)} kcal dzisiaj · kolejny cel: #${rank.position - 1}`;
    showAchievement(title, detail, {
      tier,
      eyebrow: tier === "podium" ? "🏆 NOWY POZIOM RANKINGU" : tier === "top10" ? "TOP 10 ODBLOKOWANE" : "RYWAL POKONANY",
    });
    state.rankingLastPosition = rank.position;
  }

  function checkAchievements() {
    if (state.freeRideMode || state.virtualWalkMode) return;
    if (currentStage()?.complete && !state.planAchievementShown) {
      state.planAchievementShown = true;
      showAchievement("WSZYSTKIE ETAPY UKOŃCZONE", "Plan 100% · od teraz jedź swobodnie, bez strefy docelowej");
    }
  }

  function saveSessionSnapshot() {
    try {
      if (!state.sessionId || state.sessionStatus === "finished" || state.sessionStatus === "ready") {
        window.localStorage.removeItem(SESSION_SNAPSHOT_KEY);
        return;
      }
      window.localStorage.setItem(SESSION_SNAPSHOT_KEY, JSON.stringify({
        id: state.sessionId,
        status: state.sessionStatus,
        elapsedSeconds: state.elapsedSeconds,
        intervalProgressSeconds: state.intervalProgressSeconds,
        planCompletedAtElapsed: state.planCompletedAtElapsed,
        zoneSeconds: state.zoneSeconds,
        activeCalories: state.activeCalories,
        rawKeytelCalories: state.rawKeytelCalories,
        calorieMethod: state.calorieMethod,
        trainingLoad: state.trainingLoad,
        virtualWalkActiveSeconds: state.virtualWalkActiveSeconds,
        virtualWalkOutsideSeconds: state.virtualWalkOutsideSeconds,
        virtualWalkHighHrSeconds: state.virtualWalkHighHrSeconds,
        cadenceRpm: state.cadenceRpm,
        cadenceSum: state.cadenceSum,
        cadenceSamples: state.cadenceSamples,
        sensorSamples: state.sensorSamples,
        distanceKm: state.distanceKm,
      }));
    } catch {}
  }

  function sessionProgressPayload(action = "checkpoint") {
    return {
      action,
      session_id: state.sessionId,
      timestamp: Date.now(),
      elapsed_seconds: state.elapsedSeconds,
      zone_seconds: state.zoneSeconds,
      interval_progress_seconds: state.intervalProgressSeconds,
      plan_completed_at_elapsed: state.planCompletedAtElapsed,
      plan_completed: !state.freeRideMode && !state.virtualWalkMode && Boolean(currentStage()?.complete),
      active_calories: state.activeCalories,
      active_calories_keytel_raw: state.rawKeytelCalories,
      calorie_method: state.calorieMethod,
      calorie_calibration_factor: state.calorieCalibration.factor,
      training_load: state.trainingLoad,
      virtual_walk_active_seconds: state.virtualWalkActiveSeconds,
      virtual_walk_outside_seconds: state.virtualWalkOutsideSeconds,
      virtual_steps: calculateVirtualWalkSteps(state.virtualWalkActiveSeconds),
      cadence_rpm_avg: state.cadenceSamples ? state.cadenceSum / state.cadenceSamples : null,
      distance_km: state.distanceKm,
      sensor_samples: state.sensorSamples.slice(0, 100),
    };
  }

  async function checkpointSession({ keepalive = false } = {}) {
    if (!state.sessionId || !["running", "paused"].includes(state.sessionStatus) || checkpointInFlight) return;
    checkpointInFlight = true;
    try {
      recordCscSample("distance");
      const checkpointPayload = sessionProgressPayload();
      const response = await fetch(SESSION_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(checkpointPayload),
        keepalive,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const savedIds = new Set(checkpointPayload.sensor_samples.map((sample) => sample.id));
      state.sensorSamples = state.sensorSamples.filter((sample) => !savedIds.has(sample.id));
    } catch {
      // The runtime remains authoritative; the next periodic checkpoint retries.
    } finally {
      checkpointInFlight = false;
    }
  }

  function resetSessionCounters() {
    state.elapsedSeconds = 0;
    state.intervalProgressSeconds = (state.plan.intervals || []).map(() => 0);
    state.planCompletedAtElapsed = null;
    state.zoneSeconds = Object.fromEntries(zones.map((zone) => [zone.key, 0]));
    state.activeCalories = 0;
    state.rawKeytelCalories = 0;
    state.calorieMethod = "indoor_cycling_mi_calibrated_v1";
    state.trainingLoad = 0;
    state.virtualWalkActiveSeconds = 0;
    state.virtualWalkOutsideSeconds = 0;
    state.virtualWalkHighHrSeconds = 0;
    state.cadenceSum = 0;
    state.cadenceSamples = 0;
    state.sensorSamples = [];
    state.distanceKm = 0;
    state.distanceSpeedKmh = 0;
    state.distanceSource = "unavailable";
    state.journeyPreviousLiveDistanceKm = state.journeyCommittedDistanceKm;
    state.caloriesEstimated = true;
    state.previousSample = null;
    state.achievedZones.clear();
    state.achievedIntervals.clear();
    state.planAchievementShown = false;
  }

  async function controlSession(action) {
    if (["start", "virtual-walk"].includes(action) && ["running", "paused"].includes(calibrationEngine.status)) {
      throw new Error("Najpierw zatrzymaj i zapisz albo zresetuj aktywny test kalibracyjny.");
    }
    const shouldStartVirtualWalk = action === "virtual-walk";
    if (shouldStartVirtualWalk) await refreshTodaySteps();
    if (shouldStartVirtualWalk) enterVirtualWalkMode();
    const apiAction = shouldStartVirtualWalk ? "start" : action;
    if (apiAction === "start" && !pendingStartRequestId) {
      pendingStartRequestId = globalThis.crypto?.randomUUID?.() || `start-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    const shouldStartFreeRide = action === "start" && dailyPlanCompleted();
    if (shouldStartFreeRide) enterFreeRideMode();
    if (apiAction !== "start") recordCscSample("distance");
    const controlSensorSamples = apiAction === "start" ? [] : state.sensorSamples.slice(0, 100);
    suspendStream();
    let response;
    try {
      response = await fetch(SESSION_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: apiAction,
          request_id: apiAction === "start" ? pendingStartRequestId : undefined,
          session_id: apiAction === "start" ? undefined : state.sessionId,
          timestamp: Date.now(),
          title: state.virtualWalkMode ? "Sesja Spacerowa · Virtual Walk" : state.freeRideMode ? "Free Ride · trening dodatkowy" : `${WORKOUT_TYPE_LABELS[state.plan.current_workout?.type] || "Indoor cycling"} · plan cardio`,
          plan_id: state.plan.plan_id,
          plan_date: state.plan.current_workout?.date,
          planned_duration_minutes: state.freeRideMode || state.virtualWalkMode ? null : state.plan.total_duration_minutes,
          target_zones: state.plan.target_zones,
          workout_type: state.virtualWalkMode ? "virtual_walk" : "indoor_cycling",
          sub_type: state.virtualWalkMode ? "liss" : null,
          elapsed_seconds: state.elapsedSeconds,
          zone_seconds: state.zoneSeconds,
          interval_progress_seconds: state.intervalProgressSeconds,
          plan_completed_at_elapsed: state.planCompletedAtElapsed,
          plan_completed: !state.freeRideMode && !state.virtualWalkMode && Boolean(currentStage()?.complete),
          active_calories: state.activeCalories,
          active_calories_keytel_raw: state.rawKeytelCalories,
          calorie_method: state.calorieMethod,
          calorie_calibration_factor: state.calorieCalibration.factor,
          training_load: state.trainingLoad,
          virtual_walk_active_seconds: state.virtualWalkActiveSeconds,
          virtual_walk_outside_seconds: state.virtualWalkOutsideSeconds,
          virtual_steps: calculateVirtualWalkSteps(state.virtualWalkActiveSeconds),
          cadence_rpm_avg: state.cadenceSamples ? state.cadenceSum / state.cadenceSamples : null,
          distance_km: state.distanceKm,
          sensor_samples: controlSensorSamples,
        }),
      });
    } catch (error) {
      if (shouldStartFreeRide) leaveFreeRideMode();
      if (shouldStartVirtualWalk) leaveVirtualWalkMode();
      throw error;
    } finally {
      resumeStream();
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload?.session) {
      if (shouldStartFreeRide) leaveFreeRideMode();
      if (shouldStartVirtualWalk) leaveVirtualWalkMode();
      throw new Error(payload?.error || `HTTP ${response.status}`);
    }
    const session = payload.session;
    if (controlSensorSamples.length) {
      const savedIds = new Set(controlSensorSamples.map((sample) => sample.id));
      state.sensorSamples = state.sensorSamples.filter((sample) => !savedIds.has(sample.id));
    }
    if (apiAction === "start") pendingStartRequestId = null;
    const expectedWorkoutType = shouldStartVirtualWalk ? "virtual_walk" : "indoor_cycling";
    if (apiAction === "start" && session.workout_type !== expectedWorkoutType) {
      if (shouldStartFreeRide) leaveFreeRideMode();
      if (shouldStartVirtualWalk) leaveVirtualWalkMode();
      throw new Error("Inna sesja Live Workout jest już aktywna. Najpierw ją zakończ albo anuluj.");
    }
    state.externalSession = null;
    state.sessionId = session.id;
    state.sessionStatus = session.status;
    if (apiAction === "start") {
      resetSessionCounters();
      state.rankingLastPosition = !state.rankingLoaded ? null : currentCalorieRank().position;
      learningEngine.resetWindow();
      state.previousSample = Number.isInteger(state.heartRate)
        ? { at: Date.now(), heartRate: state.heartRate }
        : null;
      state.achievedZones.clear();
      state.planAchievementShown = false;
      showAchievement(
        state.virtualWalkMode ? "SESJA SPACEROWA ROZPOCZĘTA" : state.freeRideMode ? "FREE RIDE ROZPOCZĘTY" : "SESJA ROZPOCZĘTA",
        state.virtualWalkMode ? "Cel 95–120 BPM · 105 wirtualnych kroków za minutę w strefie" : state.freeRideMode ? "Dzisiejszy plan jest ukończony · jedź własnym tempem" : `${state.plan.total_duration_minutes} min · podążaj za komunikatami HR`,
      );
    } else if (action === "pause") {
      learningEngine.resetWindow();
      showAchievement("PAUZA", "Odliczanie i naliczanie stref zostały zatrzymane");
    } else if (action === "resume") {
      learningEngine.resetWindow();
      showAchievement("WRACAMY DO PLANU", "Odliczanie zostało wznowione");
    } else if (action === "finish") {
      learningEngine.resetWindow();
      const finishedFreeRide = state.freeRideMode;
      const finishedVirtualWalk = state.virtualWalkMode;
      const requiredStagesDone = Boolean(currentStage()?.complete);
      showAchievement(
        finishedVirtualWalk ? "SPACER ZAPISANY" : finishedFreeRide ? "FREE RIDE ZAPISANY" : requiredStagesDone ? "TRENING 100%" : "TRENING ZAPISANY",
        finishedVirtualWalk ? `+${calculateVirtualWalkSteps(state.virtualWalkActiveSeconds).toLocaleString("pl-PL")} wirtualnych kroków dodano do dzisiejszej sumy` : finishedFreeRide ? `${formatWorkoutTime(state.elapsedSeconds)} treningu dodatkowego` : requiredStagesDone ? "Wszystkie etapy ukończone po kolei" : `${formatWorkoutTime(creditedPlanSeconds())} zaliczonego planu · ${formatWorkoutTime(state.elapsedSeconds)} czasu łącznego`,
      );
      state.sessionId = null;
      state.sessionStatus = "ready";
      state.distanceKm = 0;
      if (finishedFreeRide) leaveFreeRideMode();
      if (finishedVirtualWalk) leaveVirtualWalkMode();
      state.history = [session, ...state.history.filter((item) => item.id !== session.id)];
      if (finishedFreeRide || finishedVirtualWalk) resetSessionCounters();
      state.rankingLastPosition = null;
      window.dispatchEvent(new CustomEvent("live-workout:history-changed"));
      window.setTimeout(loadHistory, 350);
      refreshJourneyProgress().then(render).catch(() => {
        state.journeyStatus = "error";
        state.journeyError = "Nie udało się odświeżyć postępu podróży";
        render();
      });
    } else if (action === "cancel") {
      learningEngine.resetWindow();
      const cancelledFreeRide = state.freeRideMode;
      const cancelledVirtualWalk = state.virtualWalkMode;
      state.sessionId = null;
      state.sessionStatus = "ready";
      if (cancelledFreeRide) leaveFreeRideMode();
      if (cancelledVirtualWalk) leaveVirtualWalkMode();
      resetSessionCounters();
      state.rankingLastPosition = null;
      showAchievement("SESJA ANULOWANA", "Nie zapisano jej w historii, planie ani krokach dziennych");
      window.setTimeout(loadHistory, 150);
    }
    saveSessionSnapshot();
    render();
    return session;
  }

  async function restoreSession() {
    try {
      const response = await fetch(SESSION_ENDPOINT, { cache: "no-store" });
      if (!response.ok) return;
      const { session } = await response.json();
      if (!session) {
        state.externalSession = null;
        render();
        return;
      }
      if (session.workout_type === "strength") {
        state.externalSession = session;
        render();
        return;
      }
      state.externalSession = null;
      if (session.plan_id === FREE_RIDE_PLAN.plan_id) enterFreeRideMode();
      if (session.plan_id === VIRTUAL_WALK_PLAN.plan_id || session.workout_type === "virtual_walk") enterVirtualWalkMode();
      state.sessionId = session.id;
      state.sessionStatus = session.status;
      state.elapsedSeconds = Number(session.duration_seconds || 0);
      let hasStoredIntervalProgress = Array.isArray(session.interval_progress_seconds) && session.interval_progress_seconds.length > 0;
      state.intervalProgressSeconds = hasStoredIntervalProgress ? session.interval_progress_seconds.map(Number) : [];
      state.planCompletedAtElapsed = session.plan_completed_at_elapsed == null ? null : Number(session.plan_completed_at_elapsed);
      state.zoneSeconds = { ...state.zoneSeconds, ...(session.zones || {}) };
      state.calorieMethod = session.calorie_method || "keytel_hr_profile";
      state.rawKeytelCalories = Number(session.active_calories_keytel_raw || (state.calorieMethod === "keytel_hr_profile" ? session.active_calories : 0) || 0);
      state.activeCalories = state.rawKeytelCalories > 0
        ? state.rawKeytelCalories * state.calorieCalibration.factor
        : Number(session.active_calories || 0);
      state.calorieMethod = "indoor_cycling_mi_calibrated_v1";
      state.caloriesEstimated = state.activeCalories > 0;
      state.trainingLoad = Number(session.training_load || 0);
      state.virtualWalkActiveSeconds = Number(session.virtual_walk_active_seconds || 0);
      state.virtualWalkOutsideSeconds = Number(session.virtual_walk_outside_seconds || 0);
      state.cadenceRpm = session.cadence_rpm_avg == null ? state.cadenceRpm : Number(session.cadence_rpm_avg);
      state.distanceKm = Math.max(0, Number(session.distance_km || 0));
      try {
        const snapshot = JSON.parse(window.localStorage.getItem(SESSION_SNAPSHOT_KEY) || "null");
        if (snapshot?.id === session.id) {
          state.elapsedSeconds = Math.max(state.elapsedSeconds, Number(snapshot.elapsedSeconds || 0));
          state.intervalProgressSeconds = (state.plan.intervals || []).map((interval, index) => Math.max(
            Number(state.intervalProgressSeconds[index] || 0),
            Number(snapshot.intervalProgressSeconds?.[index] || 0),
          ));
          hasStoredIntervalProgress ||= Array.isArray(snapshot.intervalProgressSeconds) && snapshot.intervalProgressSeconds.length > 0;
          if (snapshot.planCompletedAtElapsed != null) state.planCompletedAtElapsed = Number(snapshot.planCompletedAtElapsed);
          const snapshotRaw = Number(snapshot.rawKeytelCalories || (snapshot.calorieMethod ? 0 : snapshot.activeCalories) || 0);
          state.rawKeytelCalories = Math.max(state.rawKeytelCalories, snapshotRaw);
          state.activeCalories = state.rawKeytelCalories > 0
            ? state.rawKeytelCalories * state.calorieCalibration.factor
            : Math.max(state.activeCalories, Number(snapshot.activeCalories || 0));
          state.trainingLoad = Math.max(state.trainingLoad, Number(snapshot.trainingLoad || 0));
          state.virtualWalkActiveSeconds = Math.max(state.virtualWalkActiveSeconds, Number(snapshot.virtualWalkActiveSeconds || 0));
          state.virtualWalkOutsideSeconds = Math.max(state.virtualWalkOutsideSeconds, Number(snapshot.virtualWalkOutsideSeconds || 0));
          state.virtualWalkHighHrSeconds = Math.max(0, Number(snapshot.virtualWalkHighHrSeconds || 0));
          if (Number.isFinite(Number(snapshot.cadenceRpm))) state.cadenceRpm = Number(snapshot.cadenceRpm);
          state.cadenceSum = Math.max(state.cadenceSum, Number(snapshot.cadenceSum || 0));
          state.cadenceSamples = Math.max(state.cadenceSamples, Number(snapshot.cadenceSamples || 0));
          if (Array.isArray(snapshot.sensorSamples)) state.sensorSamples = snapshot.sensorSamples;
          state.distanceKm = Math.max(state.distanceKm, Number(snapshot.distanceKm || 0));
          zones.forEach((zone) => {
            state.zoneSeconds[zone.key] = Math.max(Number(state.zoneSeconds[zone.key] || 0), Number(snapshot.zoneSeconds?.[zone.key] || 0));
          });
        }
      } catch {}
      if (!hasStoredIntervalProgress && state.elapsedSeconds > 0 && !state.freeRideMode && !state.virtualWalkMode) {
        state.intervalProgressSeconds = getLegacyIntervalProgress(state.plan, state.elapsedSeconds);
        if (getIntervalAtProgress(state.plan, state.intervalProgressSeconds)?.complete) {
          state.planCompletedAtElapsed ??= totalPlanSeconds();
        }
      }
      if (state.elapsedSeconds > 0 && state.activeCalories <= 0) {
        state.rawKeytelCalories = estimateCaloriesFromZones(state.zoneSeconds, profile);
        state.activeCalories = state.rawKeytelCalories * state.calorieCalibration.factor;
        state.caloriesEstimated = state.activeCalories > 0;
      }
      ensureIntervalProgress();
      if (state.elapsedSeconds > 0 && state.trainingLoad <= 0) {
        state.trainingLoad = state.virtualWalkMode
          ? state.elapsedSeconds / 60 * .25
          : calculateTrimp(state.zoneSeconds);
      }
      state.journeyPreviousLiveDistanceKm = journeyLiveDistance();
      render();
    } catch {} finally {
      state.sessionRestored = true;
    }
  }

  function renderHistory() {
    if (state.historyLoading) {
      elements.historyList.innerHTML = '<div class="live-workout-history-empty">Ładowanie historii…</div>';
      return;
    }
    if (!state.history.length) {
      elements.historyList.innerHTML = '<div class="live-workout-history-empty">Historia jest jeszcze pusta.</div>';
      return;
    }

    const entries = state.history.slice(0, 30).map((session) => {
      const sessionId = String(session.id);
      const cardElement = document.createElement("article");
      cardElement.className = "live-workout-history-card";
      cardElement.dataset.historySessionPanel = sessionId;
      cardElement.hidden = true;
      cardElement.innerHTML = `
        <header class="live-workout-history-card-head">
          <div><strong data-history-title></strong><time data-history-date></time></div>
          <span data-history-status></span>
        </header>
        <div class="live-workout-history-metrics">
          <div><strong data-history-duration></strong><span>CZAS [MIN:SEK]</span></div>
          <div><strong data-history-calories></strong><span>AKTYWNE KCAL</span></div>
          <div><strong data-history-average></strong><span>ŚREDNIE TĘTNO</span></div>
          <div><strong data-history-maximum></strong><span>MAKSYMALNE TĘTNO</span></div>
        </div>
        <div class="live-workout-history-zones" data-history-zones></div>
        <div class="live-workout-history-effect">
          <div><span>Efekt aerobowy</span><strong data-history-aerobic></strong></div>
          <div><span>Efekt anaerobowy</span><strong data-history-anaerobic></strong></div>
          <div data-history-load-help><span data-history-load-label>Obciążenie strefowe</span><strong data-history-load></strong></div>
          <div data-history-recovery-help><span>Zalecana regeneracja</span><strong data-history-recovery></strong></div>
        </div>
        <div class="live-workout-history-walk" data-history-walk hidden>
          <div><span>Wirtualne kroki</span><strong data-history-walk-steps></strong></div>
          <div><span>W strefie 95–120 BPM</span><strong data-history-walk-target></strong></div>
          <div><span>Poza strefą</span><strong data-history-walk-outside></strong></div>
          <div><span>Średnia kadencja</span><strong data-history-walk-cadence></strong></div>
        </div>
        <footer><span data-history-source></span><span data-history-samples></span><div class="live-workout-history-actions"><button type="button" data-history-tcx>POBIERZ TCX</button><button type="button" class="is-delete" data-history-delete>USUŃ SESJĘ</button></div></footer>`;
      cardElement.querySelector("[data-history-title]").textContent = session.title || "Indoor cycling";
      cardElement.querySelector("[data-history-date]").textContent = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" }).format(new Date(Number(session.started_at)));
      cardElement.querySelector("[data-history-status]").textContent = session.status === "finished" ? "Zakończony" : "W trakcie";
      cardElement.querySelector("[data-history-duration]").textContent = formatWorkoutTime(session.duration_seconds);
      const dashboardCalories = ["keytel_hr_profile", "indoor_cycling_mi_calibrated_v1"].includes(session.calorie_method)
        || String(session.data_quality?.active_calories || "").startsWith("estimated_");
      const caloriesElement = cardElement.querySelector("[data-history-calories]");
      caloriesElement.textContent = session.active_calories != null ? `${dashboardCalories ? "~" : ""}${session.active_calories} kcal` : "-- kcal";
      caloriesElement.parentElement.title = dashboardCalories
        ? session.calorie_method === "indoor_cycling_mi_calibrated_v1"
          ? `Personalny szacunek dla rowerka stacjonarnego: surowy Keytel × ${Number(session.calorie_calibration_factor || DEFAULT_INDOOR_CYCLING_CALIBRATION).toFixed(3)}. Surowy wynik: ~${Number(session.active_calories_keytel_raw || 0).toFixed(1)} kcal. Mnożnik skalibrowano na treningach Mi Fitness.`
          : `Starszy, nieskalibrowany szacunek Keytela. Może być wyraźnie zawyżony; nowe sesje używają personalnej kalibracji Mi Fitness.`
        : "Wartość zaimportowana z Mi Fitness. Xiaomi opisuje ją jako estymację zależną od HR, czasu, intensywności, typu aktywności i danych profilu; dokładny wzór nie jest publikowany.";
      cardElement.querySelector("[data-history-average]").textContent = session.avg_hr != null ? `${session.avg_hr} BPM` : "-- BPM";
      cardElement.querySelector("[data-history-maximum]").textContent = session.max_hr != null ? `${session.max_hr} BPM` : "-- BPM";
      const virtualWalk = session.workout_type === "virtual_walk";
      const walkMetrics = cardElement.querySelector("[data-history-walk]");
      walkMetrics.hidden = !virtualWalk;
      if (virtualWalk) {
        const activeSeconds = Number(session.virtual_walk_active_seconds || 0);
        const outsideSeconds = Number(session.virtual_walk_outside_seconds || 0);
        const measuredSeconds = activeSeconds + outsideSeconds;
        cardElement.querySelector("[data-history-walk-steps]").textContent = `+${Math.round(Number(session.virtual_steps || calculateVirtualWalkSteps(activeSeconds))).toLocaleString("pl-PL")}`;
        cardElement.querySelector("[data-history-walk-target]").textContent = `${formatWorkoutTime(activeSeconds)} · ${measuredSeconds ? Math.round(activeSeconds / measuredSeconds * 100) : 0}%`;
        cardElement.querySelector("[data-history-walk-outside]").textContent = formatWorkoutTime(outsideSeconds);
        cardElement.querySelector("[data-history-walk-cadence]").textContent = session.cadence_rpm_avg == null ? "brak czujnika" : `${Math.round(Number(session.cadence_rpm_avg))} RPM`;
      }
      const effect = session.training_effect || {};
      cardElement.querySelector("[data-history-aerobic]").textContent = effect.aerobic != null
        ? `${effect.aerobic} ${effect.aerobic_label || ""}`.trim()
        : "--";
      cardElement.querySelector("[data-history-anaerobic]").textContent = effect.anaerobic != null
        ? `${effect.anaerobic} ${effect.anaerobic_label || ""}`.trim()
        : "--";
      const importedMiLoad = /xiaomi|mi fitness/i.test(String(session.source || "")) && session.data_quality?.training_effect === "screenshot";
      cardElement.querySelector("[data-history-load-label]").textContent = importedMiLoad ? "Training Load Mi" : "Obciążenie strefowe";
      cardElement.querySelector("[data-history-load]").textContent = session.training_load != null ? `${session.training_load} pkt` : "-- pkt";
      cardElement.querySelector("[data-history-load-help]").title = importedMiLoad
        ? "Wartość z Mi Fitness. Według Xiaomi Training Load bazuje głównie na EPOC, intensywności HR, poziomie sprawności i obciążeniu z dłuższego okresu. Nie jest bezpośrednio porównywalna z punktami strefowymi dashboardu."
        : trainingLoadExplanation;
      cardElement.querySelector("[data-history-recovery]").textContent = session.recovery_hours != null
        ? `${session.recovery_hours} h`
        : "--";
      const estimatedEffect = Boolean(effect.estimated || String(session.data_quality?.training_effect || "").startsWith("estimated_"));
      cardElement.querySelector("[data-history-aerobic]").parentElement.title = estimatedEffect
        ? "Estymacja dashboardu 0–5 z czasu w strefach. Ocenia bodziec tlenowy; nie jest kopią firmowego EPOC Xiaomi/Garmin."
        : "Wartość zaimportowana z Mi Fitness.";
      cardElement.querySelector("[data-history-anaerobic]").parentElement.title = estimatedEffect
        ? "Estymacja dashboardu 0–5. Najmocniej rośnie za czas w Z4 i Z5; krótkich sprintów bez danych mocy może nie ocenić idealnie."
        : "Wartość zaimportowana z Mi Fitness.";
      cardElement.querySelector("[data-history-recovery-help]").title = estimatedEffect
        ? "Estymacja regeneracji na podstawie obciążenia strefowego oraz efektu aerobowego i anaerobowego. To wskazówka treningowa, nie diagnoza medyczna."
        : "Wartość zaimportowana z Mi Fitness.";
      cardElement.querySelector("[data-history-source]").textContent = session.source || "Wear OS";
      cardElement.querySelector("[data-history-samples]").textContent = session.sample_count > 0
        ? `${session.sample_count} próbek HR`
        : "TCX bez próbek sekundowych";
      cardElement.querySelector("[data-history-tcx]").dataset.historyTcx = session.id;
      const deleteButton = cardElement.querySelector("[data-history-delete]");
      deleteButton.dataset.historyDelete = session.id;
      deleteButton.dataset.historyTitle = session.title || "Indoor cycling";
      deleteButton.hidden = session.status !== "finished";

      const zoneContainer = cardElement.querySelector("[data-history-zones]");
      zoneContainer.replaceChildren(...zones.map((zone) => {
        const row = document.createElement("div");
        row.style.setProperty("--zone-color", zone.color);
        row.innerHTML = `<span>${zone.id}</span><div><i></i></div><time></time>`;
        row.querySelector("i").style.width = `${getWorkoutZonePercent(session, zone.key)}%`;
        row.querySelector("time").textContent = formatWorkoutTime(session.zones?.[zone.key] || 0);
        return row;
      }));
      const summaryButton = document.createElement("button");
      summaryButton.type = "button";
      summaryButton.className = "live-workout-history-session";
      summaryButton.dataset.historySession = sessionId;
      summaryButton.setAttribute("aria-expanded", "false");
      summaryButton.innerHTML = `
        <span class="live-workout-history-session-time"></span>
        <span class="live-workout-history-session-copy"><strong></strong><small></small></span>
        <span class="live-workout-history-session-kcal"></span>
        <span class="live-workout-history-session-arrow" aria-hidden="true">⌄</span>`;
      summaryButton.querySelector(".live-workout-history-session-time").textContent = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" }).format(new Date(Number(session.started_at)));
      summaryButton.querySelector("strong").textContent = session.title || "Indoor cycling";
      summaryButton.querySelector("small").textContent = `${formatWorkoutTime(session.duration_seconds)} · ${session.avg_hr != null ? `${session.avg_hr} BPM` : "brak HR"}`;
      summaryButton.querySelector(".live-workout-history-session-kcal").textContent = session.active_calories != null ? `${dashboardCalories ? "~" : ""}${session.active_calories} kcal` : "-- kcal";
      return { session, cardElement, summaryButton };
    });
    const groups = new Map();
    entries.forEach((entry) => {
      const day = actualSessionDate(entry.session);
      if (!groups.has(day)) groups.set(day, []);
      groups.get(day).push(entry);
    });
    const daySections = [...groups.entries()].map(([day, dayEntries]) => {
      const section = document.createElement("section");
      section.className = "live-workout-history-day";
      section.dataset.historyDay = day;
      const dayDate = day === "bez-daty" ? null : new Date(`${day}T12:00:00`);
      const daySummary = summarizeWorkoutDay(dayEntries.map((entry) => entry.session));
      const dateMarkup = dayDate
        ? `<div class="live-workout-history-date">
            <strong>${new Intl.DateTimeFormat("pl-PL", { day: "2-digit" }).format(dayDate)}</strong>
            <div>
              <b>${new Intl.DateTimeFormat("pl-PL", { weekday: "long" }).format(dayDate)}</b>
              <time datetime="${day}">${new Intl.DateTimeFormat("pl-PL", { month: "long" }).format(dayDate)} <em>${dayDate.getFullYear()}</em></time>
            </div>
          </div>`
        : '<strong class="live-workout-history-date-undated">Treningi bez daty</strong>';
      const estimatedCalories = dayEntries.some(({ session }) => (
        ["keytel_hr_profile", "indoor_cycling_mi_calibrated_v1"].includes(session.calorie_method)
        || String(session.data_quality?.active_calories || "").startsWith("estimated_")
      ));
      const calorieText = `${estimatedCalories ? "~" : ""}${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 }).format(daySummary.activeCalories)} kcal`;
      const loadText = `${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 }).format(daySummary.trainingLoad)} pkt`;
      const zoneGradient = daySummary.totalZoneSeconds > 0
        ? `conic-gradient(${zones.map((zone, index) => {
          const before = zones.slice(0, index).reduce((sum, item) => sum + daySummary.zoneSeconds[item.key], 0);
          const start = before / daySummary.totalZoneSeconds * 100;
          const end = (before + daySummary.zoneSeconds[zone.key]) / daySummary.totalZoneSeconds * 100;
          return `${zone.color} ${start}% ${end}%`;
        }).join(", ")})`
        : "conic-gradient(#27272a 0 100%)";
      section.innerHTML = `
        <div class="live-workout-history-day-overview">
          <header class="live-workout-history-day-head">
            <div><span>DZIEŃ TRENINGOWY</span>${dateMarkup}</div>
            <b>${dayEntries.length} ${dayEntries.length === 1 ? "sesja" : "sesje"}</b>
          </header>
          <div class="live-workout-history-day-metrics">
            <div><span>CZAS ŁĄCZNIE</span><strong>${formatWorkoutTime(daySummary.durationSeconds)}</strong></div>
            <div><span>AKTYWNE KCAL</span><strong>${calorieText}</strong></div>
            <div><span>ŚREDNIE HR</span><strong>${daySummary.averageHeartRate ? `${daySummary.averageHeartRate} BPM` : "-- BPM"}</strong></div>
            <div><span>MAKSYMALNE HR</span><strong>${daySummary.maxHeartRate ? `${daySummary.maxHeartRate} BPM` : "-- BPM"}</strong></div>
            <div><span>OBCIĄŻENIE</span><strong>${loadText}</strong></div>
            ${daySummary.virtualSteps ? `<div class="is-walk"><span>WIRTUALNE KROKI</span><strong>+${Math.round(daySummary.virtualSteps).toLocaleString("pl-PL")}</strong></div>` : ""}
          </div>
          <div class="live-workout-history-day-zones">
            <div class="live-workout-history-day-donut" role="img" aria-label="Rozkład czasu dnia w strefach tętna" style="--history-zone-gradient: ${zoneGradient}">
              <div><strong>${formatWorkoutTime(daySummary.totalZoneSeconds)}</strong><span>W STREFACH</span></div>
            </div>
            <div class="live-workout-history-day-zone-legend">
              ${zones.map((zone) => {
                const percent = daySummary.totalZoneSeconds ? Math.round(daySummary.zoneSeconds[zone.key] / daySummary.totalZoneSeconds * 100) : 0;
                return `<span style="--zone-color: ${zone.color}"><i></i><b>${zone.id}</b><em>${percent}%</em><small>${formatWorkoutTime(daySummary.zoneSeconds[zone.key])}</small></span>`;
              }).join("")}
            </div>
          </div>
        </div>
        <div class="live-workout-history-session-strip" aria-label="Sesje tego dnia"></div>
        <div class="live-workout-history-day-details" aria-live="polite"></div>`;
      section.querySelector(".live-workout-history-session-strip").replaceChildren(...dayEntries.map((entry) => entry.summaryButton));
      section.querySelector(".live-workout-history-day-details").replaceChildren(...dayEntries.map((entry) => entry.cardElement));
      dayEntries.forEach(({ summaryButton }) => {
        summaryButton.addEventListener("pointerenter", () => {
          if (!section.dataset.historyPinned) activateHistorySession(section, summaryButton.dataset.historySession);
        });
        summaryButton.addEventListener("focus", () => activateHistorySession(section, summaryButton.dataset.historySession));
      });
      section.addEventListener("pointerleave", () => {
        if (section.dataset.historyPinned) activateHistorySession(section, section.dataset.historyPinned);
        else hideHistorySessionDetails(section);
      });
      return section;
    });
    elements.historyList.replaceChildren(...daySections);
  }

  function activateHistorySession(daySection, sessionId) {
    daySection.querySelectorAll("[data-history-session]").forEach((button) => {
      const active = button.dataset.historySession === String(sessionId);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-expanded", String(active));
    });
    daySection.querySelectorAll("[data-history-session-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.historySessionPanel !== String(sessionId);
    });
  }

  function hideHistorySessionDetails(daySection) {
    daySection.querySelectorAll("[data-history-session]").forEach((button) => {
      button.classList.remove("is-active");
      button.setAttribute("aria-expanded", "false");
    });
    daySection.querySelectorAll("[data-history-session-panel]").forEach((panel) => { panel.hidden = true; });
  }

  async function loadHistory() {
    state.historyLoading = true;
    renderHistory();
    elements.historyRefresh.disabled = true;
    try {
      const [response, rankingResponse] = await Promise.all([
        fetch(`${HISTORY_ENDPOINT}?limit=200`, { cache: "no-store" }),
        fetch(RANKING_ENDPOINT, { cache: "no-store" }).catch(() => null),
      ]);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      state.history = Array.isArray(payload?.sessions) ? payload.sessions : [];
      state.calorieRanking = rankingResponse?.ok
        ? normalizeCyclingCalorieRanking((await rankingResponse.json()).days)
        : buildCyclingCalorieRanking(state.history);
      state.rankingLoaded = true;
      if (["running", "paused"].includes(state.sessionStatus)) {
        state.rankingLastPosition = currentCalorieRank().position;
      }
      try { window.localStorage?.setItem(HISTORY_CACHE_KEY, JSON.stringify(state.history)); } catch {}
      if (historyRetryTimer) window.clearTimeout(historyRetryTimer);
      historyRetryTimer = null;
      state.calorieCalibration = deriveIndoorCyclingCalibration(state.history, profile);
      if (state.rawKeytelCalories > 0) {
        state.activeCalories = state.rawKeytelCalories * state.calorieCalibration.factor;
      }
    } catch {
      if (!state.history.length) {
        try {
          const cached = JSON.parse(window.localStorage?.getItem(HISTORY_CACHE_KEY) || "[]");
          if (Array.isArray(cached)) state.history = cached;
        } catch {}
      }
      if (!state.calorieRanking.length) state.calorieRanking = buildCyclingCalorieRanking(state.history);
      state.rankingLoaded = true;
      if (["running", "paused"].includes(state.sessionStatus)) {
        state.rankingLastPosition = currentCalorieRank().position;
      }
      if (!historyRetryTimer) {
        historyRetryTimer = window.setTimeout(() => {
          historyRetryTimer = null;
          loadHistory();
        }, API_RETRY_DELAY_MS);
      }
    } finally {
      state.historyLoading = false;
      elements.historyRefresh.disabled = false;
      renderHistory();
      renderPlanOverview();
      renderWidget();
      loadAdaptiveContext();
    }
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    return payload;
  }

  async function refreshTodaySteps() {
    try {
      const payload = await fetchJson("/api/steps/history?days=1");
      const todayKey = localDateKey();
      const row = payload?.daily?.find((item) => item.day === todayKey && !item.filled);
      state.todayStoredSteps = row ? Math.max(0, Number(row.steps) || 0) : 0;
    } catch {}
    return state.todayStoredSteps;
  }

  async function downloadWorkoutTcx(sessionId, button) {
    button.disabled = true;
    try {
      const session = await fetchJson(`${HISTORY_ENDPOINT}/${encodeURIComponent(sessionId)}`);
      const day = historyDate(session) || "trening";
      downloadTextFile(`indoor-cycling-${day}-${session.id}.tcx`, exportWorkoutToTCX(session), "application/vnd.garmin.tcx+xml;charset=utf-8");
      showAchievement("TCX GOTOWY", `${session.sample_count || 0} próbek HR zapisano w pliku`);
    } catch (error) {
      showAchievement("NIE UDAŁO SIĘ POBRAĆ TCX", error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function deleteWorkoutSession(sessionId, title, button) {
    const warning = `USUNĄĆ SESJĘ „${title}”?\n\nTej operacji nie można cofnąć. Usunięte zostaną zapis treningu i próbki HR.${title.includes("Spacerowa") ? " Powiązane wirtualne kroki zostaną odjęte od kroków dziennych; zwykłe kroki pozostaną bez zmian." : ""}`;
    if (!window.confirm(warning)) return;
    button.disabled = true;
    try {
      const result = await fetchJson(`${SESSION_ENDPOINT}/${encodeURIComponent(sessionId)}?confirm=delete`, { method: "DELETE" });
      showAchievement("SESJA USUNIĘTA", result.virtual_steps_removed > 0
        ? `Odjęto również ${Number(result.virtual_steps_removed).toLocaleString("pl-PL")} wirtualnych kroków`
        : "Wpis i próbki HR zostały trwale usunięte");
      state.adaptiveLoadedFor = "";
      await loadHistory();
    } catch (error) {
      showAchievement("NIE UDAŁO SIĘ USUNĄĆ SESJI", error.message);
      button.disabled = false;
    }
  }

  async function exportFullBackup() {
    elements.backupExport.disabled = true;
    try {
      const serverData = await fetchJson("/api/live-workout/backup");
      const backup = {
        kind: "cleaning-dashboard-full-backup",
        schemaVersion: 1,
        exportedAt: new Date().toISOString(),
        localStorage: collectLocalStorage(),
        ...serverData,
      };
      const day = new Date().toISOString().slice(0, 10);
      downloadTextFile(`cleaning-dashboard-backup-${day}.json`, JSON.stringify(backup, null, 2), "application/json;charset=utf-8");
      showAchievement("BACKUP GOTOWY", `${backup.workouts.length} treningów · ${backup.weightEvents.length} pomiarów wagi · ${backup.stepEvents.length} dni kroków`);
    } catch (error) {
      showAchievement("NIE UDAŁO SIĘ UTWORZYĆ BACKUPU", error.message);
    } finally {
      elements.backupExport.disabled = false;
    }
  }

  async function importFullBackupFile(file) {
    const backup = validateFullBackup(JSON.parse(await file.text()));
    if (state.sessionStatus !== "ready") throw new Error("Najpierw zakończ aktywną sesję treningową");
    const accepted = window.confirm(
      `Scalić backup z ${backup.exportedAt || "nieznanej daty"}?\n\nIstniejące wpisy zostaną zachowane, a pasujące ustawienia localStorage zaktualizowane.`,
    );
    if (!accepted) return;
    const result = await fetchJson("/api/live-workout/backup/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(backup),
    });
    const localCount = importLocalStorageBackup(backup, { merge: true });
    const merged = result.merged || {};
    showAchievement("BACKUP SCALONY", `${merged.workouts || 0} treningów · ${merged.weightEvents || 0} nowych wag · ${merged.stepEvents || 0} dni kroków · ${localCount} ustawień`);
    window.setTimeout(() => window.location.reload(), 1300);
  }

  function openProfileDialog() {
    const fields = elements.profileForm.elements;
    fields.namedItem("sex").value = profile.sex;
    fields.namedItem("ageYears").value = profile.ageYears;
    fields.namedItem("weightKg").value = profile.weightKg;
    fields.namedItem("maxHr").value = profile.maxHr;
    fields.namedItem("bmrKcal").value = profile.bmrKcal;
    elements.profileDialog.returnValue = "";
    elements.profileDialog.showModal();
  }

  function saveProfileFromDialog() {
    const data = new FormData(elements.profileForm);
    profile.sex = data.get("sex") === "female" ? "female" : "male";
    profile.ageYears = Math.max(14, Math.min(100, Number(data.get("ageYears")) || 30));
    profile.weightKg = Math.max(30, Math.min(300, Number(data.get("weightKg")) || 75));
    profile.maxHr = resolveMaxHr({ ageYears: profile.ageYears, maxHr: Number(data.get("maxHr")) });
    profile.bmrKcal = Math.max(800, Math.min(4000, Number(data.get("bmrKcal")) || 1800));
    state.calorieCalibration = deriveIndoorCyclingCalibration(state.history, profile);
    if (state.rawKeytelCalories > 0) state.activeCalories = state.rawKeytelCalories * state.calorieCalibration.factor;
    saveWorkoutProfile(profile);
    maxHr = profile.maxHr;
    zones = getHeartRateZones(maxHr);
    state.zoneSeconds = { ...Object.fromEntries(zones.map((zone) => [zone.key, 0])), ...state.zoneSeconds };
    buildZoneRows(elements.zoneList, zones);
    elements.maxHr.textContent = `maxHR ${maxHr}`;
    render();
    renderHistory();
    renderPlanOverview();
    showAchievement("PROFIL ZAPISANY", `HRmax ${maxHr} · ${profile.weightKg.toFixed(1)} kg`);
  }

  function applyExternalProfile(event) {
    const next = event.detail && typeof event.detail === "object" ? event.detail : getWorkoutProfile();
    Object.assign(profile, next);
    maxHr = resolveMaxHr(profile);
    profile.maxHr = maxHr;
    zones = getHeartRateZones(maxHr);
    state.zoneSeconds = { ...Object.fromEntries(zones.map((zone) => [zone.key, 0])), ...state.zoneSeconds };
    state.calorieCalibration = deriveIndoorCyclingCalibration(state.history, profile);
    buildZoneRows(elements.zoneList, zones);
    elements.maxHr.textContent = `maxHR ${maxHr}`;
    render();
  }

  function scaleIntervalsToZones(intervals, targetZones) {
    const originalTotals = Object.fromEntries(zones.map((zone) => [
      zone.key,
      intervals.filter((item) => item.target_zone === zone.key).reduce((sum, item) => sum + Number(item.duration_minutes || 0), 0),
    ]));
    const scaled = intervals.map((interval) => {
      const original = originalTotals[interval.target_zone] || 0;
      const target = Number(targetZones[interval.target_zone] || 0);
      return { ...interval, duration_minutes: original ? Number(interval.duration_minutes || 0) * target / original : 0 };
    }).filter((interval) => interval.duration_minutes > 0);
    const additions = [];
    zones.forEach((zone) => {
      if (Number(targetZones[zone.key]) > 0 && !scaled.some((item) => item.target_zone === zone.key)) {
        additions.push({ name: `Adaptacja · ${zone.label}`, duration_minutes: Number(targetZones[zone.key]), target_zone: zone.key });
      }
    });
    const cooldownIndex = scaled.length > 1 && scaled.at(-1)?.target_zone === "light" ? scaled.length - 1 : scaled.length;
    scaled.splice(cooldownIndex, 0, ...additions);
    return scaled;
  }

  async function loadAdaptiveContext() {
    if (!state.sessionRestored || !state.plan.current_workout || state.historyLoading) return;
    const adaptiveKey = `${state.plan.current_workout.date}:${state.history.length}`;
    if (state.adaptiveLoadedFor === adaptiveKey) return;
    state.adaptiveLoadedFor = adaptiveKey;
    try {
      const [stepsResponse, healthResponse, weightResponse, statsResponse] = await Promise.all([
        fetch("/api/steps/history?days=1", { cache: "no-store" }),
        fetch("/api/health-connect/latest", { cache: "no-store" }),
        fetch("/api/weight/latest", { cache: "no-store" }),
        fetch("/api/weight/stats", { cache: "no-store" }),
      ]);
      const [stepsPayload, healthPayload, weightPayload, statsPayload] = await Promise.all([
        stepsResponse.json().catch(() => ({})),
        healthResponse.json().catch(() => ({})),
        weightResponse.json().catch(() => ({})),
        statsResponse.json().catch(() => ({})),
      ]);
      const todayKey = new Date().toLocaleDateString("sv-SE");
      const stepsRow = stepsPayload?.daily?.find((row) => row.day === todayKey && !row.filled);
      state.todayStoredSteps = stepsRow ? Math.max(0, Number(stepsRow.steps) || 0) : 0;
      const healthSnapshot = healthPayload?.snapshot;
      let sleepScore = null;
      if (healthSnapshot?.day === todayKey) {
        const sleepSeconds = (healthSnapshot.payload?.sleep?.sessions || []).reduce((sum, session) => {
          const start = new Date(session.start).getTime();
          const end = new Date(session.end).getTime();
          return sum + (Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) / 1000 : 0);
        }, 0);
        if (sleepSeconds > 0) sleepScore = Math.min(100, Math.round(sleepSeconds / (8 * 3600) * 100));
      }
      if (Number.isFinite(Number(weightPayload?.weight_kg))) profile.weightKg = Number(weightPayload.weight_kg);
      state.adaptiveContext = {
        steps: stepsRow ? Number(stepsRow.steps) : null,
        sleepScore,
        weightTrendKg: statsPayload?.stats?.changes?.days_7 ?? null,
      };
      const planRelevantHistory = state.history.filter((session) => !["virtual_walk", "strength"].includes(session.workout_type));
      const loads = planRelevantHistory.map((session) => ({
        started_at: Number(session.started_at),
        // Jedna wspólna skala dla adaptacji. Importowany Training Load Mi jest EPOC,
        // a nasze punkty są czasem × strefa, więc nie wolno ich mieszać w jednym trendzie.
        load: calculateTrimp(session.zones || {}),
      }));
      const recentWorkouts = planRelevantHistory
        .filter((session) => session.status === "finished" && session.plan_id !== FREE_RIDE_PLAN.plan_id)
        .map((session) => {
          const scheduled = state.plan.schedule?.find((workout) => workout.date === historyDate(session));
          return {
            ...session,
            planned_duration_minutes: session.planned_duration_minutes ?? scheduled?.duration,
            target_zones: Object.keys(session.target_zones || {}).length ? session.target_zones : scheduled?.zones,
          };
        });
      state.optimizedPlan = optimizeWorkoutPlan(state.plan.current_workout, {
        ...state.adaptiveContext,
        goal: "weight_loss",
        loads,
        recentWorkouts,
      });
      elements.adaptation.hidden = false;
      const fatigue = state.optimizedPlan.fatigue || {};
      elements.adaptation.innerHTML = `<strong>AUTOMATYCZNA ADAPTACJA · CEL: REDUKCJA · BEZ AI</strong><span>${state.optimizedPlan.reason}</span><small>Kroki: ${state.adaptiveContext.steps ?? "brak"} · sen: ${state.adaptiveContext.sleepScore == null ? "brak aktualnych danych" : `${state.adaptiveContext.sleepScore}%`} · trend wagi 7 dni: ${state.adaptiveContext.weightTrendKg == null ? "brak" : `${Number(state.adaptiveContext.weightTrendKg).toFixed(2)} kg`} · porównywalne obciążenie strefowe 7 dni: ${Number(fatigue.acuteLoad || 0).toFixed(1)} pkt · baza 28 dni: ${Number(fatigue.chronicLoad || 0).toFixed(1)} pkt · realizacja ostatnich sesji: ${state.optimizedPlan.completionScore == null ? "brak" : `${Math.round(state.optimizedPlan.completionScore * 100)}%`}</small>`;
      const alreadyCompleted = isWorkoutDayCompleted(
        state.plan.current_workout,
        state.history,
        state.planTracking.statuses,
      );
      if (alreadyCompleted) {
        elements.adaptation.querySelector("span").textContent = "Dzisiejszy plan jest ukończony. Kolejna rozpoczęta sesja zostanie automatycznie zapisana jako FREE RIDE i nie zmieni realizacji planu dnia.";
      }
      if (state.optimizedPlan.changed && !alreadyCompleted && state.sessionStatus === "ready") {
        const optimized = state.optimizedPlan.workout;
        state.plan.intervals = scaleIntervalsToZones(state.plan.intervals, optimized.zones);
        state.plan.target_zones = optimized.zones;
        state.plan.total_duration_minutes = optimized.duration;
        state.plan.current_workout = { ...state.plan.current_workout, ...optimized, adapted: true };
        state.plan.schedule = state.plan.schedule.map((workout) => workout.date === state.plan.current_workout.date
          ? { ...workout, ...optimized, adapted: true }
          : workout);
        state.plan.weeks = state.plan.weeks.map((week) => ({
          ...week,
          planned_minutes: state.plan.schedule
            .filter((workout) => workout.date >= week.start_date && workout.date <= week.end_date)
            .reduce((sum, workout) => sum + Number(workout.duration || 0), 0),
        }));
        buildZoneRows(elements.zoneList, zones);
        render();
        renderPlanOverview();
      }
    } catch {
      elements.adaptation.hidden = true;
    }
  }

  function handleTelemetry(payload) {
    const heartRate = Number(payload?.heart_rate);
    if (!Number.isInteger(heartRate) || heartRate < 30 || heartRate > 240) return;
    const telemetryTimestamp = Number(payload?.timestamp);
    if (
      Number.isFinite(telemetryTimestamp)
      && telemetryTimestamp > 0
      && telemetryTimestamp === state.lastTelemetryTimestamp
    ) return;
    const now = Date.now();
    if (state.previousSample && state.sessionStatus === "running") {
      const delta = Math.min(5, Math.max(0, (now - state.previousSample.at) / 1000));
      const previousZone = getZoneForHeartRate(state.previousSample.heartRate, maxHr);
      if (previousZone) {
        state.zoneSeconds[previousZone.key] += delta;
        if (state.virtualWalkMode) {
          if (state.previousSample.heartRate >= VIRTUAL_WALK_HR_MIN && state.previousSample.heartRate <= VIRTUAL_WALK_HR_MAX) {
            state.virtualWalkActiveSeconds += delta;
          } else {
            state.virtualWalkOutsideSeconds += delta;
          }
          state.virtualWalkHighHrSeconds = state.previousSample.heartRate > VIRTUAL_WALK_GUARDRAIL_HR
            ? state.virtualWalkHighHrSeconds + delta
            : 0;
        } else if (!state.freeRideMode) {
          const allocation = creditIntervalProgress(state.plan, state.intervalProgressSeconds, previousZone.key, delta);
          state.intervalProgressSeconds = allocation.progress;
          allocation.completedIndices.forEach((index) => {
            if (state.achievedIntervals.has(index)) return;
            state.achievedIntervals.add(index);
            const interval = state.plan.intervals[index];
            const next = state.plan.intervals[index + 1];
            showAchievement(
              `ETAP ${index + 1}/${state.plan.intervals.length} UKOŃCZONY`,
              next ? `${interval.name} · aktywny: ${next.name}` : `${interval.name} · cały plan został zaliczony`,
            );
          });
          if (allocation.current?.complete && state.planCompletedAtElapsed == null) {
            state.planCompletedAtElapsed = state.elapsedSeconds;
          }
        }
      }
    }
    state.heartRate = heartRate;
    state.lastTelemetryTimestamp = Number.isFinite(telemetryTimestamp) && telemetryTimestamp > 0
      ? telemetryTimestamp
      : null;
    if (heartRate <= VIRTUAL_WALK_GUARDRAIL_HR) state.virtualWalkHighHrSeconds = 0;
    const cadenceRpm = payload?.cadence_rpm == null ? Number.NaN : Number(payload.cadence_rpm);
    if (Number.isFinite(cadenceRpm) && cadenceRpm >= 0 && cadenceRpm <= 250) {
      state.telemetryCadenceRpm = cadenceRpm;
      state.cadenceRpm = cadenceRpm;
      if (state.sessionStatus === "running") {
        state.cadenceSum += cadenceRpm;
        state.cadenceSamples += 1;
      }
    } else state.telemetryCadenceRpm = null;
    const speedKmh = payload?.speed_kmh == null ? Number.NaN : Number(payload.speed_kmh);
    state.telemetrySpeedKmh = Number.isFinite(speedKmh) && speedKmh >= 0 && speedKmh <= 120 ? speedKmh : null;
    state.lastTelemetryAt = now;
    state.previousSample = { at: now, heartRate };
    state.samples.push({ at: now, heartRate });
    state.samples = state.samples.filter((sample) => sample.at >= now - HISTORY_WINDOW_MS);
    learningEngine.ingest({
      timestamp: now,
      sessionId: state.sessionId,
      sessionElapsedSeconds: state.elapsedSeconds,
      level: state.calibrationAdvisorLevel,
      rpm: state.cadenceRpm,
      heartRate,
      active: state.sessionStatus === "running",
      signalFresh: state.cscStatus === "connected"
        && state.cscMode === "CADENCE"
        && !state.cscSignalStale,
    });
    if (state.sessionStatus === "running") checkAchievements();
    render(now);
  }

  function suspendStream() {
    streamSuspended = true;
    if (streamReconnectTimer) window.clearTimeout(streamReconnectTimer);
    streamReconnectTimer = null;
    telemetryStream?.close();
    telemetryStream = null;
  }

  function resumeStream() {
    streamSuspended = false;
    startStream();
  }

  function startStream() {
    if (streamSuspended || telemetryStream) return;
    if (typeof window.EventSource !== "function") {
      elements.connection.textContent = "SSE niedostępne";
      return;
    }
    const stream = new window.EventSource(STREAM_ENDPOINT);
    telemetryStream = stream;
    stream.onopen = () => {
      if (streamReconnectTimer) window.clearTimeout(streamReconnectTimer);
      streamReconnectTimer = null;
      state.connected = true;
      render();
      restoreSession();
    };
    stream.addEventListener("telemetry", (event) => {
      try {
        handleTelemetry(JSON.parse(event.data));
      } catch {}
    });
    stream.onerror = () => {
      state.connected = false;
      stream.close();
      if (telemetryStream === stream) telemetryStream = null;
      if (!streamSuspended && !streamReconnectTimer) {
        streamReconnectTimer = window.setTimeout(() => {
          streamReconnectTimer = null;
          startStream();
        }, 1500);
      }
      render();
    };
  }

  async function pollLatestTelemetry() {
    if (telemetryPollInFlight) return;
    telemetryPollInFlight = true;
    try {
      const response = await fetch(LATEST_TELEMETRY_ENDPOINT, { cache: "no-store" });
      if (!response.ok) return;
      const payload = (await response.json())?.telemetry;
      if (!payload) return;
      state.connected = true;
      handleTelemetry(payload);
    } catch {
      // SSE remains the primary transport; the next poll will retry.
    } finally {
      telemetryPollInFlight = false;
    }
  }

  async function loadPlan() {
    try {
      const response = await fetch(PLAN_ENDPOINT, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const plan = await response.json();
      if (!plan?.plan_title || !Array.isArray(plan.intervals) || !Array.isArray(plan.schedule)) {
        throw new Error("Niepełny plan");
      }
      state.plan = plan;
      state.planSource = "api";
      try { window.localStorage?.setItem(PLAN_CACHE_KEY, JSON.stringify(plan)); } catch {}
      if (planRetryTimer) window.clearTimeout(planRetryTimer);
      planRetryTimer = null;
    } catch {
      if (state.planSource !== "api") {
        try {
          const cached = JSON.parse(window.localStorage?.getItem(PLAN_CACHE_KEY) || "null");
          if (cached?.plan_title && Array.isArray(cached.intervals) && Array.isArray(cached.schedule)) {
            state.plan = cached;
            state.planSource = "cache";
          } else {
            state.plan = cloneFallbackPlan();
            state.planSource = "fallback";
          }
        } catch {
          state.plan = cloneFallbackPlan();
          state.planSource = "fallback";
        }
      }
      if (!planRetryTimer) {
        planRetryTimer = window.setTimeout(() => {
          planRetryTimer = null;
          loadPlan();
        }, API_RETRY_DELAY_MS);
      }
    }
    state.selectedPlanDate = state.plan.current_workout?.date || state.selectedPlanDate;
    render();
    renderPlanOverview();
    await restoreSession();
    loadAdaptiveContext();
  }

  function openFocus({ fullscreen = false } = {}) {
    if (state.externalSession?.workout_type === "strength" && ["running", "paused"].includes(state.externalSession.status)) {
      openStrengthTrainer();
      return;
    }
    overlay.hidden = false;
    document.body.classList.add("live-workout-focus-open");
    render();
    overlay.querySelector("[data-live-workout-close]")?.focus();
    if (fullscreen && document.fullscreenEnabled && document.fullscreenElement !== overlay) {
      enterElementFullscreen(document, overlay)
        .catch((error) => showAchievement("FULLSCREEN NIEDOSTĘPNY", `${error.message} HUD pozostaje otwarty.`));
    }
  }

  function closeFocus() {
    if (isWorkoutSessionActive(effectiveStatus())) {
      pinWorkoutHudOpen(effectiveStatus(), overlay, document.body);
      showAchievement("HUD TRENINGU POZOSTAJE OTWARTY", "Najpierw zakończ albo anuluj aktywną sesję.");
      return false;
    }
    if (document.fullscreenElement === overlay) document.exitFullscreen().catch(() => {});
    if (calibrationEngine.status === "running") calibrationEngine.pause("view-closed");
    state.calibrationOpen = false;
    cadenceMetronome.setRpm(0);
    overlay.hidden = true;
    document.body.classList.remove("live-workout-focus-open");
    (focusButton || openButton).focus();
    return true;
  }

  function syncFullscreenState() {
    const active = document.fullscreenElement === overlay;
    overlay.classList.toggle("is-hud-only", active);
    elements.fullscreen.textContent = active ? "WYJDŹ Z PEŁNEGO EKRANU" : "PEŁNY EKRAN HUD";
    elements.fullscreen.setAttribute("aria-pressed", String(active));
    renderFocus();
  }

  async function toggleHudFullscreen() {
    await toggleElementFullscreen(document, overlay);
  }

  async function toggleCscSensor() {
    if (state.cscStatus === "reconnecting") {
      cscSensor.disconnect();
      return cscSensor.connect();
    }
    if (["connecting", "connected"].includes(state.cscStatus)) {
      await cscSensor.disconnect();
      return;
    }
    await cscSensor.connect();
  }

  function openCalibrationMode() {
    openFocus();
    state.calibrationOpen = true;
    render();
  }

  function closeCalibrationMode() {
    if (calibrationEngine.status === "running") calibrationEngine.pause("view-closed");
    state.calibrationOpen = false;
    render();
  }

  function startCalibrationTest() {
    if (state.sessionStatus !== "ready") {
      showAchievement("KALIBRACJA NIEDOSTĘPNA", "Najpierw zakończ zwykłą sesję LIVE WORKOUT.");
      return;
    }
    const resumePlan = calibrationElements.resumeSaved.checked
      ? getCalibrationResumePlan(state.calibrations)
      : null;
    const targetRpm = Math.max(60, Math.min(100, Number(
      resumePlan?.config?.targetRpm ?? calibrationElements.targetRpm.value,
    ) || 80));
    const toleranceRpm = Math.max(2, Math.min(10, Number(
      resumePlan?.config?.toleranceRpm ?? calibrationElements.tolerance.value,
    ) || 4));
    const warmupSeconds = [180, 240, 300].includes(Number(calibrationElements.warmup.value))
      ? Number(calibrationElements.warmup.value)
      : 180;
    calibrationEngine = createCalibrationEngine({
      targetRpm,
      toleranceRpm,
      warmupSeconds,
      resumeCompletedLevels: resumePlan?.completedLevels || [],
      resumeDataPoints: resumePlan?.dataPoints || [],
      resumeSourceCalibrationId: resumePlan?.calibrationId || null,
    });
    calibrationEngine.start(calibrationSignals());
    render();
  }

  function handleCalibrationAction(action) {
    if (action === "pause") calibrationEngine.pause();
    if (action === "resume") calibrationEngine.resume(calibrationSignals());
    if (action === "skip") calibrationEngine.skipStep();
    if (action === "repeat") calibrationEngine.repeatStep();
    if (action === "partial") {
      if (!window.confirm("Zatrzymać test i zapisać zebrane dotąd poziomy jako częściową kalibrację?")) return;
      calibrationEngine.stopPartial();
    }
    if (action === "reset") {
      if (!window.confirm("Zresetować bieżący test? Niezapisane próbki zostaną usunięte.")) return;
      calibrationEngine.reset();
    }
    render();
  }

  function syncCalibrationAdvisor() {
    state.calibrationAdvisorZone = calibrationElements.advisorZone.value;
    if (state.calibrationAdvisorZone !== "custom") {
      const zone = zones.find((item) => item.id === state.calibrationAdvisorZone);
      if (zone) {
        state.calibrationAdvisorTargetHr = Math.round((zone.min + zone.max) / 2);
        calibrationElements.advisorHr.value = String(state.calibrationAdvisorTargetHr);
      }
    } else {
      state.calibrationAdvisorTargetHr = Math.max(70, Math.min(220, Number(calibrationElements.advisorHr.value) || 130));
    }
    setResistanceLevel(calibrationElements.advisorLevel.value, false);
    render();
  }

  focusButton?.addEventListener("click", openFocus);
  elements.calibrationOpen.addEventListener("click", openCalibrationMode);
  calibrationElements.close.addEventListener("click", closeCalibrationMode);
  calibrationElements.start.addEventListener("click", startCalibrationTest);
  calibrationElements.audio.addEventListener("change", () => calibrationAudio.setEnabled(calibrationElements.audio.checked));
  calibrationElements.metronome.addEventListener("change", async () => {
    try {
      await cadenceMetronome.setEnabled(calibrationElements.metronome.checked);
    } catch (error) {
      calibrationElements.metronome.checked = false;
      showAchievement("METRONOM NIEDOSTĘPNY", error.message);
    }
    render();
  });
  calibrationElements.metronomeMode.addEventListener("change", () => {
    cadenceMetronome.setMode(calibrationElements.metronomeMode.value);
    render();
  });
  calibrationElements.targetRpm.addEventListener("input", () => render());
  calibrationElements.resumeSaved.addEventListener("change", () => render());
  calibrationElements.reconnect.addEventListener("click", async () => {
    try {
      if (["connected", "reconnecting"].includes(state.cscStatus)) {
        cscSensor.disconnect();
      }
      await toggleCscSensor();
    } catch (error) {
      if (error?.name !== "AbortError") showLearningToast("SENSOR CSC NIEDOSTĘPNY", formatCscConnectionError(error), "error");
    }
  });
  calibrationRoot.addEventListener("click", (event) => {
    const action = event.target.closest("[data-cal-action]")?.dataset.calAction;
    if (action) handleCalibrationAction(action);
  });
  calibrationElements.advisorZone.addEventListener("change", syncCalibrationAdvisor);
  calibrationElements.advisorHr.addEventListener("change", () => {
    calibrationElements.advisorZone.value = "custom";
    syncCalibrationAdvisor();
  });
  calibrationElements.advisorLevel.addEventListener("change", syncCalibrationAdvisor);
  calibrationElements.clear.addEventListener("click", () => {
    if (!window.confirm("Usunąć wszystkie zapisane kalibracje rowerka?")) return;
    state.calibrations = clearCalibrations(window.localStorage);
    refreshCalibrationModel();
    render();
  });
  calibrationElements.clearLearning.addEventListener("click", () => {
    if (!window.confirm("Usunąć wszystkie stabilne próbki zebrane podczas treningów? Wyniki testów kalibracyjnych zostaną zachowane.")) return;
    state.learningSamples = clearLiveWorkoutLearningSamples(window.localStorage);
    learningEngine.resetWindow();
    refreshCalibrationModel();
    render();
  });
  elements.widgetStart.addEventListener("click", async () => {
    openFocus({ fullscreen: true });
    elements.widgetStart.disabled = true;
    try {
      await sessionActionGate.run(() => controlSession("start"));
    } catch (error) {
      showAchievement("NIE UDAŁO SIĘ WYSTARTOWAĆ", error.message);
    } finally {
      elements.widgetStart.disabled = false;
    }
  });
  elements.widgetWalk.addEventListener("click", async () => {
    openFocus({ fullscreen: true });
    elements.widgetWalk.disabled = true;
    try {
      await sessionActionGate.run(() => controlSession("virtual-walk"));
    } catch (error) {
      showAchievement("NIE UDAŁO SIĘ WYSTARTOWAĆ SPACERU", error.message);
    } finally {
      elements.widgetWalk.disabled = false;
    }
  });
  initStrengthTrainer();
  elements.widgetStrengthStart.addEventListener("click", () => {
    if (state.externalSession?.workout_type !== "strength") {
      window.location.href = "./live-workout.html#strength";
      return;
    }
    openStrengthTrainer({
      workoutId: elements.widgetStrengthStart.dataset.workoutId,
      variant: elements.widgetStrengthStart.dataset.workoutVariant,
      planSessionId: elements.widgetStrengthStart.dataset.planSessionId,
      planDate: elements.widgetStrengthStart.dataset.planDate,
    });
  });
  window.addEventListener("live-workout:history-changed", loadHistory);
  window.addEventListener("live-workout:session-changed", restoreSession);
  window.addEventListener("live-workout:profile-changed", applyExternalProfile);
  window.addEventListener("live-workout:postcards-changed", () => refreshJourneyPostcards().catch(() => {}));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) cscSensor.checkConnection();
  });
  elements.historyRefresh.addEventListener("click", loadHistory);
  elements.fullscreen.hidden = !document.fullscreenEnabled;
  elements.fullscreen.addEventListener("click", () => {
    toggleHudFullscreen().catch((error) => showAchievement("FULLSCREEN NIEDOSTĘPNY", error.message));
  });
  elements.cadenceConnect.addEventListener("click", () => {
    toggleCscSensor().catch((error) => {
      if (error?.name === "AbortError") return;
      showLearningToast("SENSOR CSC NIEDOSTĘPNY", formatCscConnectionError(error), "error");
    });
  });
  document.addEventListener("fullscreenchange", syncFullscreenState);
  elements.profileOpen.addEventListener("click", openProfileDialog);
  elements.profileDialog.addEventListener("close", () => {
    if (elements.profileDialog.returnValue === "save") saveProfileFromDialog();
  });
  elements.backupExport.addEventListener("click", exportFullBackup);
  elements.backupImport.addEventListener("click", () => elements.backupFile.click());
  elements.backupFile.addEventListener("change", async () => {
    const [file] = elements.backupFile.files || [];
    elements.backupFile.value = "";
    if (!file) return;
    elements.backupImport.disabled = true;
    try {
      await importFullBackupFile(file);
    } catch (error) {
      showAchievement("NIE UDAŁO SIĘ WCZYTAĆ BACKUPU", error.message);
    } finally {
      elements.backupImport.disabled = false;
    }
  });
  overlay.addEventListener("click", (event) => {
    if (event.target.closest("[data-live-workout-close]")) closeFocus();
    const resistanceButton = event.target.closest("[data-live-resistance-level]");
    if (resistanceButton) setResistanceLevel(resistanceButton.dataset.liveResistanceLevel);
    const tcxButton = event.target.closest("[data-history-tcx]");
    if (tcxButton) downloadWorkoutTcx(tcxButton.dataset.historyTcx, tcxButton);
    const deleteButton = event.target.closest("[data-history-delete]");
    if (deleteButton) deleteWorkoutSession(deleteButton.dataset.historyDelete, deleteButton.dataset.historyTitle, deleteButton);
    const historySessionButton = event.target.closest("[data-history-session]");
    if (historySessionButton) {
      const daySection = historySessionButton.closest("[data-history-day]");
      const sessionId = historySessionButton.dataset.historySession;
      if (daySection.dataset.historyPinned === sessionId) {
        delete daySection.dataset.historyPinned;
        hideHistorySessionDetails(daySection);
      } else {
        daySection.dataset.historyPinned = sessionId;
        activateHistorySession(daySection, sessionId);
      }
    }
    const sessionButton = event.target.closest("[data-live-session-action]");
    if (sessionButton) {
      const action = sessionButton.dataset.liveSessionAction;
      if (action === "cancel" && !window.confirm("ANULOWAĆ TĘ SESJĘ?\n\nCały jej czas, HR, kcal, realizacja stref i wirtualne kroki zostaną bezpowrotnie usunięte. Sesja nie pojawi się w historii.")) return;
      if (["start", "virtual-walk"].includes(action)) openFocus({ fullscreen: true });
      sessionButton.disabled = true;
      sessionActionGate.run(() => controlSession(action))
        .catch((error) => showAchievement("BŁĄD STEROWANIA SESJĄ", error.message))
        .finally(() => { sessionButton.disabled = false; });
    }
    const dayButton = event.target.closest("[data-plan-date]");
    if (dayButton) {
      state.selectedPlanDate = dayButton.dataset.planDate;
      renderPlanOverview();
    }
    const statusButton = event.target.closest("[data-plan-status]");
    if (statusButton && state.selectedPlanDate) {
      const status = statusButton.dataset.planStatus;
      const statuses = { ...(state.planTracking.statuses || {}) };
      if (status === "planned") delete statuses[state.selectedPlanDate];
      else statuses[state.selectedPlanDate] = status;
      state.planTracking = { ...state.planTracking, statuses };
      savePlanTracking();
      renderPlanOverview();
      renderWidget();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || overlay.hidden || document.fullscreenElement) return;
    if (state.calibrationOpen) closeCalibrationMode();
    else closeFocus();
  });
  window.addEventListener("resize", () => {
    if (!overlay.hidden) render();
  });
  window.addEventListener("pagehide", () => {
    saveSessionSnapshot();
    checkpointSession({ keepalive: true });
  });

  render();
  loadPlan();
  loadHistory();
  loadPlanTracking();
  loadJourney();
  startStream();
  pollLatestTelemetry();
  window.setInterval(pollLatestTelemetry, 1500);
  cscSensor.reconnectLast().catch(() => {});
  window.setInterval(() => {
    const tick = performance.now();
    const delta = Math.min(1, Math.max(0, (tick - state.lastTickAt) / 1000));
    state.lastTickAt = tick;
    if (state.sessionStatus === "running") {
      state.elapsedSeconds += delta;
      if (state.virtualWalkMode) {
        state.distanceKm = virtualWalkDistanceKm(calculateVirtualWalkSteps(state.virtualWalkActiveSeconds));
        state.distanceSource = "virtual_walk_steps_v1";
        state.distanceSpeedKmh = isFresh() && state.heartRate >= VIRTUAL_WALK_HR_MIN && state.heartRate <= VIRTUAL_WALK_HR_MAX
          ? virtualWalkDistanceKm(VIRTUAL_WALK_STEPS_PER_MINUTE * 60) : 0;
        detectJourneyCrossings();
      } else {
        const distance = accumulateCyclingDistance(state.distanceKm, delta, activeDistanceSignals());
        state.distanceKm = distance.distanceKm;
        state.distanceSpeedKmh = distance.speedKmh;
        state.distanceSource = distance.source;
        detectJourneyCrossings();
      }
      if (isFresh()) {
        const rawIncrement = calculateCaloriesPerSecond({ ...profile, heartRate: state.heartRate }) * delta;
        state.rawKeytelCalories += rawIncrement;
        state.activeCalories += calculateIndoorCyclingCaloriesPerSecond(
          { ...profile, heartRate: state.heartRate },
          state.calorieCalibration.factor,
        ) * delta;
        state.caloriesEstimated = true;
      }
      state.trainingLoad = state.virtualWalkMode
        ? state.elapsedSeconds / 60 * .25
        : calculateTrimp(state.zoneSeconds);
      checkCalorieRankAchievements();
      checkAchievements();
      if (Date.now() - state.lastSnapshotAt >= 1000) {
        state.lastSnapshotAt = Date.now();
        saveSessionSnapshot();
      }
      if (Date.now() - lastCheckpointAt >= 2000) {
        lastCheckpointAt = Date.now();
        checkpointSession();
      }
    }
    if (["running", "paused"].includes(calibrationEngine.status)) {
      const calibrationSnapshot = calibrationEngine.tick(delta, calibrationSignals(), Date.now());
      if (calibrationSnapshot.status === "running" && ["warmup", "step"].includes(calibrationSnapshot.phase?.kind)) {
        calibrationAudio.notifyCadence(
          state.cadenceRpm,
          calibrationSnapshot.phase.targetRpm,
          calibrationSnapshot.phase.toleranceRpm,
        );
      }
    }
    render();
  }, 250);

  return { state, handleTelemetry, openFocus, closeFocus };
}

if (typeof document !== "undefined") initLiveWorkoutWidget();
