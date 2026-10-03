const ZONE_ORDER = ["light", "intensive", "aerobic", "anaerobic", "vo2max"];
const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;

export function calculateFatigue(loads = [], today = new Date()) {
  const end = new Date(today);
  end.setHours(23, 59, 59, 999);
  const start7 = new Date(end); start7.setDate(start7.getDate() - 6); start7.setHours(0, 0, 0, 0);
  const start28 = new Date(end); start28.setDate(start28.getDate() - 27); start28.setHours(0, 0, 0, 0);
  const dated = loads.map((item) => ({ at: new Date(item.date || item.started_at), load: Math.max(0, number(item.load ?? item.training_load)) }))
    .filter((item) => !Number.isNaN(item.at.getTime()) && item.at <= end);
  const acuteLoad = dated.filter((item) => item.at >= start7).reduce((sum, item) => sum + item.load, 0);
  const chronicLoad = dated.filter((item) => item.at >= start28).reduce((sum, item) => sum + item.load, 0) / 4;
  return { acuteLoad, chronicLoad, fatigueRatio: chronicLoad > 0 ? acuteLoad / chronicLoad : null };
}

function moveZoneMinutes(zones, fromKey, toKey, minutes) {
  const moved = Math.min(number(zones[fromKey]), Math.max(0, number(minutes)));
  zones[fromKey] = number(zones[fromKey]) - moved;
  zones[toKey] = number(zones[toKey]) + moved;
}

function reduceDuration(workout, fraction) {
  const factor = Math.max(0, 1 - fraction);
  workout.zones = Object.fromEntries(ZONE_ORDER.map((key) => [key, Math.round(number(workout.zones[key]) * factor)]));
  workout.duration = Object.values(workout.zones).reduce((sum, value) => sum + value, 0);
}

function recentCompletionScore(sessions = []) {
  const scores = sessions
    .filter((session) => session?.status === "finished")
    .slice(0, 3)
    .map((session) => {
      const plannedSeconds = number(session.planned_duration_minutes) * 60;
      const durationScore = plannedSeconds > 0
        ? Math.min(1.1, number(session.duration_seconds) / plannedSeconds)
        : null;
      const targets = session.target_zones || {};
      const targetSeconds = ZONE_ORDER.reduce((sum, key) => sum + number(targets[key]) * 60, 0);
      const zoneScore = targetSeconds > 0
        ? ZONE_ORDER.reduce((sum, key) => sum + Math.min(number(session.zones?.[key]), number(targets[key]) * 60), 0) / targetSeconds
        : null;
      const available = [durationScore, zoneScore].filter((value) => value != null);
      return available.length ? available.reduce((sum, value) => sum + value, 0) / available.length : null;
    })
    .filter((value) => value != null);
  return scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : null;
}

function addProgressiveOverload(workout, goal = "fitness") {
  const extraMinutes = Math.max(2, Math.round(number(workout.duration) * .06));
  if (workout.type === "recovery" || workout.type === "base" || workout.type === "long") {
    workout.zones[goal === "weight_loss" ? "intensive" : "aerobic"] += extraMinutes;
  } else {
    const thresholdMinutes = Math.max(1, Math.round(extraMinutes * .6));
    workout.zones.anaerobic += thresholdMinutes;
    workout.zones.aerobic += extraMinutes - thresholdMinutes;
  }
}

export function optimizeWorkoutPlan(workoutInput, context = {}) {
  const original = JSON.parse(JSON.stringify(workoutInput || {}));
  const workout = JSON.parse(JSON.stringify(workoutInput || {}));
  workout.zones = { light: 0, intensive: 0, aerobic: 0, anaerobic: 0, vo2max: 0, ...(workout.zones || {}) };
  const reasons = [];
  const fatigue = calculateFatigue(context.loads || [], context.today || new Date());
  const sleepScore = context.sleepScore == null ? null : number(context.sleepScore);
  const completionScore = recentCompletionScore(context.recentWorkouts || []);

  if (workout.type === "rest") {
    return {
      original,
      workout,
      changed: false,
      reason: "Dzień odpoczynku pozostaje bez zmian.",
      fatigue,
    };
  }

  const poorSleep = sleepScore != null && sleepScore < 50;
  const highSteps = number(context.steps) > 12000;
  const highFatigue = fatigue.fatigueRatio != null && fatigue.fatigueRatio > 1.3;

  if (poorSleep && (workout.type === "intervals" || number(workout.zones.anaerobic) + number(workout.zones.vo2max) > 0)) {
    const recoveryMinutes = Math.max(20, Math.min(40, Math.round(number(workout.duration) * .8)));
    workout.type = "recovery";
    workout.duration = recoveryMinutes;
    workout.zones = { light: recoveryMinutes, intensive: 0, aerobic: 0, anaerobic: 0, vo2max: 0 };
    reasons.push("krótki lub słabej jakości sen — mocny trening zamieniono na aktywną regenerację");
  } else {
    if (highSteps) {
      reduceDuration(workout, .15);
      reasons.push("ponad 12 000 kroków — czas skrócono o około 15%");
    }
    if (highFatigue) {
      moveZoneMinutes(workout.zones, "vo2max", "anaerobic", workout.zones.vo2max);
      moveZoneMinutes(workout.zones, "anaerobic", "aerobic", Math.ceil(number(workout.zones.anaerobic) / 2));
      reasons.push("wysokie obciążenie ostre względem 28-dniowej bazy — obniżono intensywność");
    }
    if (!poorSleep && !highSteps && !highFatigue && completionScore != null && completionScore >= .85) {
      addProgressiveOverload(workout, context.goal);
      reasons.push("ostatnie treningi zrealizowano co najmniej w 85% — dodano około 6% progresji");
    } else if (!highSteps && completionScore != null && completionScore < .65) {
      reduceDuration(workout, .1);
      reasons.push("ostatnie treningi miały niską realizację — objętość zmniejszono o około 10% przed kolejną progresją");
    }
  }

  if (context.goal === "weight_loss" && workout.type !== "rest") {
    moveZoneMinutes(workout.zones, "aerobic", "intensive", Math.ceil(number(workout.zones.aerobic) * .15));
    reasons.push("cel redukcji — część Z3 przeniesiono do bardziej powtarzalnej objętości Z2");
  } else if (number(context.weightTrendKg) < 0 && workout.type !== "rest") {
    moveZoneMinutes(workout.zones, "aerobic", "intensive", Math.ceil(number(workout.zones.aerobic) * .15));
    reasons.push("trend redukcji masy — zwiększono udział bazy tlenowej Z2");
  }
  workout.duration = Object.values(workout.zones).reduce((sum, value) => sum + number(value), 0);
  return {
    original,
    workout,
    changed: JSON.stringify(original) !== JSON.stringify(workout),
    reason: reasons.length ? `Adaptacja: ${reasons.join("; ")}.` : "Plan bez zmian — brak wiarygodnych przesłanek do korekty.",
    fatigue,
    completionScore,
  };
}
