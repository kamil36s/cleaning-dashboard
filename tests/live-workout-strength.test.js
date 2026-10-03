import { describe, expect, it } from "vitest";

import {
  EXERCISE_LIBRARY,
  STRENGTH_PLAN_SEED,
  STRENGTH_WORKOUTS,
  WARMUP_V1,
  classifyCalibrationSet,
  formatDumbbellLoad,
  isStrengthPlanEnabled,
  loadoutForWeight,
  normalizeStrengthPlan,
} from "../js/live-workout-strength-data.js";
import {
  STRENGTH_STATES,
  beginStrengthSession,
  createStrengthSessionState,
  currentStrengthExercise,
  markCurrentSetDone,
  pauseStrengthSession,
  prepareCurrentStrengthStep,
  saveCurrentSetReview,
  startCurrentSet,
  tickStrengthSession,
} from "../js/live-workout-strength-engine.js";

describe("Live Workout strength data", () => {
  it("keeps canonical exercises data-driven and uses the ergonomic warm-up order", () => {
    expect(Object.keys(EXERCISE_LIBRARY)).toHaveLength(26);
    expect(WARMUP_V1).toEqual([
      "march-in-place",
      "bodyweight-hip-hinge",
      "bodyweight-squat",
      "cat-cow",
      "quadruped-thoracic-rotation",
      "scapular-push-up",
      "dead-bug-breathing",
    ]);
    expect(STRENGTH_WORKOUTS.A.exerciseIds[0]).toBe("dumbbell-floor-press");
    expect(STRENGTH_WORKOUTS.B.exerciseIds).toContain("dumbbell-pullover-floor");
    expect(Object.values(EXERCISE_LIBRARY).every((item) => item.instructions.length && item.cues.length)).toBe(true);
  });

  it("models strength sessions independently, so one day can also contain cycling", () => {
    const sessions = normalizeStrengthPlan(STRENGTH_PLAN_SEED);
    expect(sessions.filter((item) => item.date === "2026-09-05")).toMatchObject([
      { workoutType: "strength", workoutId: "A", status: "planned" },
    ]);
    expect(sessions.find((item) => item.date === "2026-09-07")).toMatchObject({ workoutId: "B", workoutVariant: "LIGHT" });
  });

  it("allows the strength schedule to be disabled without deleting it", () => {
    expect(isStrengthPlanEnabled({ strengthPlanEnabled: false, strengthSessions: STRENGTH_PLAN_SEED })).toBe(false);
    expect(isStrengthPlanEnabled({ strengthSessions: STRENGTH_PLAN_SEED })).toBe(true);
  });

  it("always labels dumbbell count and honors a corrected handle weight", () => {
    expect(formatDumbbellLoad(7.5, 2)).toBe("2 × 7,5 kg");
    expect(formatDumbbellLoad(7.5, 1)).toBe("1 × 7,5 kg");
    expect(loadoutForWeight(7.5, { dumbbells: { estimatedHandleWeightKg: 2.3 } })).toMatchObject({ platesPerSide: [2.5], actualWeight: 7.3 });
  });

  it("classifies the provisional first load without changing it automatically", () => {
    expect(classifyCalibrationSet({ actualRir: 5, actualReps: 12, repMin: 8, targetRir: 3 })).toBe("TOO_LIGHT");
    expect(classifyCalibrationSet({ actualRir: 3, actualReps: 10, repMin: 8, targetRir: 3 })).toBe("GOOD");
    expect(classifyCalibrationSet({ actualRir: 1, actualReps: 7, repMin: 8, targetRir: 3 })).toBe("TOO_HEAVY");
  });
});

describe("strength session state machine", () => {
  it("moves a manual rep set through ready, active, review and records reps/RIR", () => {
    let session = createStrengthSessionState({ workoutId: "A" });
    session = beginStrengthSession(session, 1000);
    session = prepareCurrentStrengthStep(session);
    expect(session.state).toBe(STRENGTH_STATES.SET_READY);
    expect(currentStrengthExercise(session).exerciseId).toBe("march-in-place");

    session.exerciseIndex = WARMUP_V1.length;
    session = prepareCurrentStrengthStep(session);
    expect(session.state).toBe(STRENGTH_STATES.EQUIPMENT_TRANSITION);
    session.state = STRENGTH_STATES.SET_READY;
    session = startCurrentSet(session);
    expect(session.state).toBe(STRENGTH_STATES.SET_ACTIVE);
    session = tickStrengthSession(session, 12);
    session = markCurrentSetDone(session);
    expect(session.state).toBe(STRENGTH_STATES.SET_REVIEW);
    session = saveCurrentSetReview(session, { actualReps: 10, actualRir: 3, actualWeightPerDumbbellKg: 7.5 });
    expect(session.state).toBe(STRENGTH_STATES.REST);
    expect(session.executions.at(-1)).toMatchObject({ exerciseId: "dumbbell-floor-press", actualReps: 10, actualRir: 3, dumbbellCount: 2 });
  });

  it("actually counts down timed work and stops in review", () => {
    let session = createStrengthSessionState({ workoutId: "B" });
    session.startedAt = 1000;
    session.exerciseIndex = session.sequence.findIndex((item) => item.exerciseId === "long-lever-plank");
    session = prepareCurrentStrengthStep(session);
    session.state = STRENGTH_STATES.SET_READY;
    session = startCurrentSet(session);
    for (let index = 0; index < 6; index += 1) session = tickStrengthSession(session, 5);
    expect(session.state).toBe(STRENGTH_STATES.SET_REVIEW);
    expect(session.countdownRemaining).toBe(0);
  });

  it("adds both sides to the recorded duration for unilateral timed work", () => {
    let session = createStrengthSessionState({ workoutId: "B" });
    session.startedAt = 1000;
    session.exerciseIndex = session.sequence.findIndex((item) => item.exerciseId === "side-plank");
    session = prepareCurrentStrengthStep(session);
    session.state = STRENGTH_STATES.SET_READY;
    session = startCurrentSet(session);
    session = tickStrengthSession(session, 5);
    session = markCurrentSetDone(session);
    expect(session.state).toBe(STRENGTH_STATES.SIDE_TRANSITION);
    session = startCurrentSet(session);
    session = tickStrengthSession(session, 4);
    session = markCurrentSetDone(session);
    session = saveCurrentSetReview(session, {});
    expect(session.executions.at(-1).actualDuration).toBe(9);
  });

  it("keeps paused time separate from workout duration", () => {
    let session = createStrengthSessionState({ workoutId: "A" });
    session = beginStrengthSession(session, 1000);
    session = prepareCurrentStrengthStep(session);
    session = tickStrengthSession(session, 5);
    session = tickStrengthSession(session, 5);
    session = pauseStrengthSession(session);
    session = tickStrengthSession(session, 5);

    expect(session.timers.totalElapsed).toBe(10);
    expect(session.timers.pausedTime).toBe(5);
  });
});
