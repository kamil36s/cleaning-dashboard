import {
  EXERCISE_LIBRARY,
  STRENGTH_WORKOUTS,
  WARMUP_V1,
  workoutExercises,
} from "./live-workout-strength-data.js";

export const STRENGTH_STATES = Object.freeze({
  PRE_WORKOUT: "PRE_WORKOUT",
  WARMUP_INTRO: "WARMUP_INTRO",
  WARMUP_ACTIVE: "WARMUP_ACTIVE",
  EQUIPMENT_TRANSITION: "EQUIPMENT_TRANSITION",
  EXERCISE_INTRO: "EXERCISE_INTRO",
  SET_READY: "SET_READY",
  SET_ACTIVE: "SET_ACTIVE",
  SET_REVIEW: "SET_REVIEW",
  REST: "REST",
  SIDE_TRANSITION: "SIDE_TRANSITION",
  EXERCISE_COMPLETE: "EXERCISE_COMPLETE",
  PAUSED: "PAUSED",
  SESSION_REVIEW: "SESSION_REVIEW",
  SESSION_COMPLETE: "SESSION_COMPLETE",
});

export const STRENGTH_SCHEMA_VERSION = 1;

const clone = (value) => JSON.parse(JSON.stringify(value));

export function buildStrengthSequence(workoutId = "A", variant = "STANDARD", adjustments = {}) {
  const warmup = WARMUP_V1.map((exerciseId) => ({
    exerciseId,
    section: "warmup",
    plannedSets: 1,
    ...clone(EXERCISE_LIBRARY[exerciseId]),
  }));
  const main = workoutExercises(workoutId, variant).map((exercise) => {
    const patch = adjustments?.[exercise.id] || {};
    return {
      exerciseId: exercise.id,
      section: exercise.isCore ? "core" : "main",
      plannedSets: Math.max(0, Number(patch.sets ?? exercise.defaultSets) || 0),
      ...clone(exercise),
      ...clone(patch),
    };
  }).filter((item) => item.plannedSets > 0);
  return [...warmup, ...main];
}

export function createStrengthSessionState({
  workoutId = "A",
  variant = "STANDARD",
  planSessionId = null,
  planDate = null,
  preWorkout = {},
  adjustments = {},
  now = Date.now(),
} = {}) {
  const normalizedWorkoutId = workoutId === "B" ? "B" : "A";
  const workout = STRENGTH_WORKOUTS[normalizedWorkoutId];
  return {
    schemaVersion: STRENGTH_SCHEMA_VERSION,
    workoutId: normalizedWorkoutId,
    workoutLabel: workout.label,
    variant: variant === "LIGHT" ? "LIGHT" : "STANDARD",
    planSessionId,
    planDate,
    state: STRENGTH_STATES.PRE_WORKOUT,
    resumeState: null,
    startedAt: null,
    finishedAt: null,
    updatedAt: now,
    exerciseIndex: 0,
    setIndex: 0,
    side: null,
    setElapsed: 0,
    completedSideDuration: 0,
    countdownRemaining: null,
    restRemaining: null,
    sequence: buildStrengthSequence(normalizedWorkoutId, variant, adjustments),
    executions: [],
    skippedExercises: [],
    preWorkout: {
      legs: ["fresh", "slightly_tired", "very_tired"].includes(preWorkout.legs) ? preWorkout.legs : "fresh",
      energy: Math.max(1, Math.min(5, Number(preWorkout.energy) || 3)),
      sleep: preWorkout.sleep || null,
      reducedLegVolume: Boolean(preWorkout.reducedLegVolume),
    },
    timers: {
      totalElapsed: 0,
      activeExerciseTime: 0,
      restTime: 0,
      equipmentTransitionTime: 0,
      pausedTime: 0,
      tutorialTime: 0,
    },
    tutorialOpen: false,
    sessionRpe: null,
    notes: "",
  };
}

export function currentStrengthExercise(session) {
  return session?.sequence?.[session.exerciseIndex] || null;
}

export function strengthExercisePosition(session) {
  const current = currentStrengthExercise(session);
  if (!current) return { current: 0, total: 0, sectionCurrent: 0, sectionTotal: 0 };
  const training = session.sequence.filter((item) => item.section !== "warmup");
  if (current.section === "warmup") {
    const warmup = session.sequence.filter((item) => item.section === "warmup");
    return { current: session.exerciseIndex + 1, total: warmup.length, sectionCurrent: session.exerciseIndex + 1, sectionTotal: warmup.length };
  }
  const sectionIndex = training.findIndex((item) => item.exerciseId === current.exerciseId);
  return { current: sectionIndex + 1, total: training.length, sectionCurrent: sectionIndex + 1, sectionTotal: training.length };
}

export function beginStrengthSession(session, now = Date.now()) {
  const next = clone(session);
  next.startedAt = next.startedAt || now;
  next.updatedAt = now;
  next.state = STRENGTH_STATES.WARMUP_INTRO;
  return next;
}

export function prepareCurrentStrengthStep(session) {
  const next = clone(session);
  const exercise = currentStrengthExercise(next);
  if (!exercise) {
    next.state = STRENGTH_STATES.SESSION_REVIEW;
    return next;
  }
  next.setElapsed = 0;
  next.completedSideDuration = 0;
  next.countdownRemaining = exercise.executionMode.startsWith("timed")
    ? Number(exercise.durationMin || exercise.durationMax || 30)
    : null;
  next.restRemaining = null;
  next.side = exercise.executionMode === "timed-per-side" ? "left" : null;
  next.state = exercise.section === "warmup"
    ? STRENGTH_STATES.SET_READY
    : STRENGTH_STATES.EQUIPMENT_TRANSITION;
  return next;
}

export function startCurrentSet(session) {
  const next = clone(session);
  const exercise = currentStrengthExercise(next);
  if (!exercise) return next;
  next.setElapsed = 0;
  if (exercise.executionMode.startsWith("timed")) {
    next.countdownRemaining = Number(exercise.durationMin || exercise.durationMax || 30);
  }
  next.state = exercise.section === "warmup"
    ? STRENGTH_STATES.WARMUP_ACTIVE
    : STRENGTH_STATES.SET_ACTIVE;
  return next;
}

export function markCurrentSetDone(session) {
  const next = clone(session);
  const exercise = currentStrengthExercise(next);
  if (!exercise) return next;
  if (exercise.executionMode === "timed-per-side" && next.side === "left") {
    next.completedSideDuration = Math.max(0, Number(next.setElapsed) || 0);
    next.side = "right";
    next.countdownRemaining = Number(exercise.durationMin || exercise.durationMax || 30);
    next.setElapsed = 0;
    next.state = STRENGTH_STATES.SIDE_TRANSITION;
    return next;
  }
  next.state = STRENGTH_STATES.SET_REVIEW;
  return next;
}

export function saveCurrentSetReview(session, review = {}) {
  const next = clone(session);
  const exercise = currentStrengthExercise(next);
  if (!exercise) return next;
  const timed = exercise.executionMode.startsWith("timed");
  const execution = {
    exerciseId: exercise.exerciseId,
    section: exercise.section,
    setNumber: next.setIndex + 1,
    plannedWeightPerDumbbellKg: exercise.weightPerDumbbellKg,
    actualWeightPerDumbbellKg: exercise.dumbbellCount ? Number(review.actualWeightPerDumbbellKg ?? exercise.weightPerDumbbellKg) : null,
    dumbbellCount: exercise.dumbbellCount,
    plannedRepMin: exercise.repMin,
    plannedRepMax: exercise.repMax,
    actualReps: timed ? null : Math.max(0, Number(review.actualReps ?? exercise.repMin) || 0),
    plannedDuration: timed ? Number(exercise.durationMin || 0) * (exercise.executionMode === "timed-per-side" ? 2 : 1) : null,
    actualDuration: timed ? Math.max(0, Number(review.actualDuration ?? (Number(next.completedSideDuration || 0) + Number(next.setElapsed || 0))) || 0) : Math.max(0, Number(next.setElapsed) || 0),
    targetRir: exercise.rirTarget,
    actualRir: review.actualRir == null || review.actualRir === "" ? null : Math.max(0, Number(review.actualRir) || 0),
    plannedRest: Number(exercise.restMin || 0),
    actualRest: null,
    skipped: Boolean(review.skipped),
    techniqueAccepted: review.techniqueAccepted !== false,
    timestamp: Date.now(),
  };
  next.executions.push(execution);

  if (exercise.section === "warmup") {
    return advanceToNextExercise(next);
  }
  if (next.setIndex + 1 < Number(exercise.plannedSets || 1)) {
    next.setIndex += 1;
    next.restRemaining = Number(exercise.restMin || 0);
    next.state = STRENGTH_STATES.REST;
    return next;
  }
  return advanceToNextExercise(next);
}

export function advanceToNextExercise(session) {
  const next = clone(session);
  next.exerciseIndex += 1;
  next.setIndex = 0;
  next.side = null;
  next.setElapsed = 0;
  next.completedSideDuration = 0;
  next.countdownRemaining = null;
  next.restRemaining = null;
  if (next.exerciseIndex >= next.sequence.length) {
    next.state = STRENGTH_STATES.SESSION_REVIEW;
    return next;
  }
  const following = currentStrengthExercise(next);
  next.state = following.section === "warmup"
    ? STRENGTH_STATES.SET_READY
    : STRENGTH_STATES.EQUIPMENT_TRANSITION;
  return next;
}

export function finishStrengthRest(session) {
  const next = clone(session);
  const previous = [...next.executions].reverse().find((item) => item.exerciseId === currentStrengthExercise(next)?.exerciseId);
  if (previous && previous.actualRest == null) previous.actualRest = Math.max(0, Number(previous.plannedRest || 0) - Math.max(0, Number(next.restRemaining || 0)));
  next.restRemaining = null;
  next.setElapsed = 0;
  next.state = STRENGTH_STATES.SET_READY;
  return next;
}

export function skipCurrentExercise(session) {
  const next = clone(session);
  const exercise = currentStrengthExercise(next);
  if (exercise) next.skippedExercises.push({ exerciseId: exercise.exerciseId, at: Date.now() });
  return advanceToNextExercise(next);
}

export function pauseStrengthSession(session) {
  if (!session || session.state === STRENGTH_STATES.PAUSED) return clone(session);
  const next = clone(session);
  next.resumeState = next.state;
  next.state = STRENGTH_STATES.PAUSED;
  return next;
}

export function resumeStrengthSession(session) {
  const next = clone(session);
  if (next.state === STRENGTH_STATES.PAUSED) {
    next.state = next.resumeState || STRENGTH_STATES.SET_READY;
    next.resumeState = null;
  }
  return next;
}

export function tickStrengthSession(session, deltaSeconds = 0) {
  const next = clone(session);
  const delta = Math.max(0, Math.min(5, Number(deltaSeconds) || 0));
  if (!next.startedAt || [STRENGTH_STATES.SESSION_COMPLETE].includes(next.state)) return next;
  if (next.state === STRENGTH_STATES.PAUSED) {
    next.timers.pausedTime += delta;
    return next;
  }
  next.timers.totalElapsed += delta;
  if (next.tutorialOpen) next.timers.tutorialTime += delta;
  if (next.state === STRENGTH_STATES.REST) {
    next.timers.restTime += delta;
    next.restRemaining = Math.max(0, Number(next.restRemaining || 0) - delta);
    return next.restRemaining <= 0 ? finishStrengthRest(next) : next;
  }
  if (next.state === STRENGTH_STATES.EQUIPMENT_TRANSITION) {
    next.timers.equipmentTransitionTime += delta;
    return next;
  }
  if ([STRENGTH_STATES.SET_ACTIVE, STRENGTH_STATES.WARMUP_ACTIVE].includes(next.state)) {
    next.timers.activeExerciseTime += delta;
    next.setElapsed += delta;
    if (next.countdownRemaining != null) {
      next.countdownRemaining = Math.max(0, Number(next.countdownRemaining) - delta);
      if (next.countdownRemaining <= 0) return markCurrentSetDone(next);
    }
  }
  return next;
}

export function summarizeStrengthSession(session) {
  const performed = session.executions.filter((item) => !item.skipped);
  const completedExercises = new Set(performed.map((item) => item.exerciseId));
  const trainingExercises = session.sequence.filter((item) => item.section !== "warmup");
  const trainingSets = performed.filter((item) => item.section !== "warmup");
  const actualRirs = trainingSets.map((item) => Number(item.actualRir)).filter(Number.isFinite);
  return {
    workoutId: session.workoutId,
    workoutLabel: session.workoutLabel,
    variant: session.variant,
    planSessionId: session.planSessionId,
    planDate: session.planDate,
    completedExercises: trainingExercises.filter((item) => completedExercises.has(item.exerciseId)).length,
    plannedExercises: trainingExercises.length,
    completedSets: trainingSets.length,
    plannedSets: trainingExercises.reduce((sum, item) => sum + Number(item.plannedSets || 0), 0),
    totalReps: trainingSets.reduce((sum, item) => sum + Number(item.actualReps || 0), 0),
    averageRir: actualRirs.length ? actualRirs.reduce((sum, value) => sum + value, 0) / actualRirs.length : null,
    partial: session.skippedExercises.length > 0 || trainingSets.length < trainingExercises.reduce((sum, item) => sum + Number(item.plannedSets || 0), 0),
    timers: { ...session.timers },
  };
}
