import { describe, expect, it } from "vitest";

import {
  FALLBACK_PLAN,
  buildWorkoutStreakometer,
  calculateDailyStepsGoal,
  calculateVirtualWalkSteps,
  calculateDailyWorkoutCaloriesAverage,
  creditIntervalProgress,
  formatWorkoutTime,
  getWorkoutDayDurationSeconds,
  getHeartRateZones,
  getIntervalAtElapsed,
  getIntervalAtProgress,
  getPlanMetrics,
  getWorkoutStreak,
  getWorkoutGuidance,
  getWorkoutZonePercent,
  getZoneForHeartRate,
  isWorkoutDayCompleted,
  isWorkoutDaySatisfied,
  isHeartRateInTarget,
  getVirtualWalkGuidance,
  parseCyclingCadenceMeasurement,
  summarizeWorkoutDay,
} from "../js/widget-live-workout.js";

describe("Live Workout HR zones", () => {
  it("builds five contiguous zones from maxHR", () => {
    expect(getHeartRateZones(190).map(({ id, min, max }) => ({ id, min, max }))).toEqual([
      { id: "Z1", min: 95, max: 113 },
      { id: "Z2", min: 114, max: 132 },
      { id: "Z3", min: 133, max: 151 },
      { id: "Z4", min: 152, max: 170 },
      { id: "Z5", min: 171, max: 190 },
    ]);
    expect(getZoneForHeartRate(165, 190).id).toBe("Z4");
  });

  it("checks the target band rather than only the assigned zone", () => {
    expect(isHeartRateInTarget(145, "aerobic", 190)).toBe(true);
    expect(isHeartRateInTarget(165, "aerobic", 190)).toBe(false);
  });
});

describe("Live Workout interval timeline", () => {
  it("moves to the next interval at an exact boundary", () => {
    expect(getIntervalAtElapsed(FALLBACK_PLAN, 0)).toMatchObject({ index: 0, remainingSeconds: 480 });
    expect(getIntervalAtElapsed(FALLBACK_PLAN, 480)).toMatchObject({
      index: 1,
      remainingSeconds: 300,
    });
  });

  it("marks the plan complete and formats timers", () => {
    expect(getIntervalAtElapsed(FALLBACK_PLAN, 45 * 60).complete).toBe(true);
    expect(formatWorkoutTime(125)).toBe("02:05");
  });

  it("zalicza wyłącznie aktywny etap i tylko w jego strefie celu", () => {
    const plan = { intervals: [
      { name: "Z1", duration_minutes: 1, target_zone: "light" },
      { name: "Z2", duration_minutes: 1, target_zone: "intensive" },
    ] };
    const outside = creditIntervalProgress(plan, [0, 0], "intensive", 30);
    expect(outside.progress).toEqual([0, 0]);
    expect(getIntervalAtProgress(plan, outside.progress)).toMatchObject({ index: 0, remainingSeconds: 60 });

    const firstDone = creditIntervalProgress(plan, outside.progress, "light", 60);
    expect(firstDone.progress).toEqual([60, 0]);
    expect(firstDone.completedIndices).toEqual([0]);
    expect(firstDone.current).toMatchObject({ index: 1, remainingSeconds: 60 });

    const allDone = creditIntervalProgress(plan, firstDone.progress, "intensive", 60);
    expect(allDone.current.complete).toBe(true);
  });

  it("przenosi nadmiar próbki tylko do kolejnego etapu o tej samej strefie", () => {
    const plan = { intervals: [
      { name: "A", duration_minutes: .1, target_zone: "light" },
      { name: "B", duration_minutes: .1, target_zone: "light" },
      { name: "C", duration_minutes: .1, target_zone: "aerobic" },
    ] };
    const result = creditIntervalProgress(plan, [5, 0, 0], "light", 5);
    expect(result.progress).toEqual([6, 4, 0]);
    expect(result.current).toMatchObject({ index: 1, remainingSeconds: 2 });
  });
});

describe("Live Workout explicit session coaching", () => {
  it("does not coach or count down before the user starts", () => {
    expect(getWorkoutGuidance(90, "aerobic", 190, false, false).label).toContain("KLIKNIJ START");
  });

  it("uses unambiguous uppercase pace commands", () => {
    expect(getWorkoutGuidance(120, "aerobic", 190, true, false).label).toBe("▲ PRZYSPIESZ (+13 BPM)");
    expect(getWorkoutGuidance(160, "aerobic", 190, true, false).label).toBe("▼ ZWOLNIJ (-9 BPM)");
    expect(getWorkoutGuidance(140, "aerobic", 190, true, false).label).toBe("✓ W STREFIE CELU");
    expect(getWorkoutGuidance(140, "aerobic", 190, true, true).label).toContain("TRENING NADMIAROWY");
  });

  it("links finished history to plan days", () => {
    const schedule = [
      { date: "2026-08-22", type: "base", duration: 42 },
      { date: "2026-08-23", type: "rest", duration: 0 },
    ];
    const history = [{ plan_date: "2026-08-22", status: "finished", duration_seconds: 2700 }];
    expect(getPlanMetrics(schedule, history)).toMatchObject({
      completedWorkouts: 1,
      plannedWorkouts: 1,
      plannedMinutes: 42,
      actualMinutes: 45,
      progress: 100,
    });
  });

  it("does not count a free ride as daily plan completion", () => {
    const schedule = [{ date: "2026-08-22", type: "base", duration: 42 }];
    const history = [{ plan_id: "free-ride", started_at: new Date("2026-08-22T12:00:00").getTime(), status: "finished", duration_seconds: 3600 }];
    expect(getPlanMetrics(schedule, history)).toMatchObject({ completedWorkouts: 0, actualMinutes: 0, progress: 0 });
  });

  it("does not count a virtual walk toward the 30-day plan", () => {
    const schedule = [{ date: "2026-08-22", type: "base", duration: 42 }];
    const history = [{ workout_type: "virtual_walk", plan_date: "2026-08-22", status: "finished", duration_seconds: 7200, plan_completed: true }];
    expect(getPlanMetrics(schedule, history)).toMatchObject({ completedWorkouts: 0, actualMinutes: 0, progress: 0 });
    expect(isWorkoutDayCompleted(schedule[0], history)).toBe(false);
  });

  it("treats a rest day as a satisfied daily goal without counting a workout", () => {
    const restDay = { date: "2026-08-23", type: "rest", duration: 0 };
    expect(isWorkoutDayCompleted(restDay)).toBe(false);
    expect(isWorkoutDaySatisfied(restDay)).toBe(true);
  });

  it("sums the actual duration of finished sessions for the selected workout day", () => {
    const workout = { date: "2026-08-22", type: "base", duration: 42 };
    const history = [
      { plan_date: workout.date, status: "finished", duration_seconds: 2400 },
      { plan_date: workout.date, status: "finished", duration_seconds: 300 },
      { plan_date: workout.date, status: "running", duration_seconds: 999 },
      { plan_id: "free-ride", plan_date: workout.date, status: "finished", duration_seconds: 600 },
      { workout_type: "virtual_walk", plan_date: workout.date, status: "finished", duration_seconds: 900 },
      { plan_date: "2026-08-21", status: "finished", duration_seconds: 1800 },
    ];

    expect(getWorkoutDayDurationSeconds(workout, history)).toBe(2700);
  });
});

describe("Live Workout virtual walk", () => {
  it("counts only active walking-zone time as virtual steps", () => {
    expect(calculateVirtualWalkSteps(60)).toBe(105);
    expect(calculateVirtualWalkSteps(90)).toBe(157);
  });

  it("shows the whole-day 10k goal including the current walking session", () => {
    expect(calculateDailyStepsGoal(1724, 276)).toEqual({
      total: 2000,
      goal: 10000,
      percent: 20,
      barPercent: 20,
    });
    const almostThere = calculateDailyStepsGoal(9970);
    expect(almostThere.percent).toBe(99);
    expect(almostThere.barPercent).toBeCloseTo(99.7);
    expect(calculateDailyStepsGoal(10000)).toEqual({
      total: 10000,
      goal: 10000,
      percent: 100,
      barPercent: 100,
    });
    expect(calculateDailyStepsGoal(9800, 700)).toMatchObject({ percent: 105, barPercent: 100 });
  });

  it("activates the guardrail only after more than 20 seconds above 125 BPM", () => {
    expect(getVirtualWalkGuidance(126, 20, true).state).toBe("slower");
    expect(getVirtualWalkGuidance(126, 20.1, true)).toMatchObject({ state: "danger" });
    expect(getVirtualWalkGuidance(110, 30, true).state).toBe("target");
  });

  it("parses crank revolutions from the Bluetooth CSC profile", () => {
    const makeMeasurement = (revolutions, eventTime) => {
      const buffer = new ArrayBuffer(5);
      const value = new DataView(buffer);
      value.setUint8(0, 0x02);
      value.setUint16(1, revolutions, true);
      value.setUint16(3, eventTime, true);
      return value;
    };
    const first = parseCyclingCadenceMeasurement(makeMeasurement(10, 1000));
    const second = parseCyclingCadenceMeasurement(makeMeasurement(11, 1768), first.crank);
    expect(second.rpm).toBeCloseTo(80, 4);
  });
});

describe("Live Workout history", () => {
  it("converts stored zone seconds to a bounded session share", () => {
    const session = { duration_seconds: 600, zones: { aerobic: 180, vo2max: 900 } };
    expect(getWorkoutZonePercent(session, "aerobic")).toBe(30);
    expect(getWorkoutZonePercent(session, "vo2max")).toBe(100);
  });

  it("aggregates comparable daily workout totals and a duration-weighted HR average", () => {
    expect(summarizeWorkoutDay([
      { status: "finished", duration_seconds: 600, active_calories: 100, avg_hr: 100, max_hr: 120, training_load: 4, virtual_steps: 900, zones: { light: 500, intensive: 100 } },
      { status: "finished", duration_seconds: 1200, active_calories: 250, avg_hr: 130, max_hr: 170, training_load: 20, zones: { intensive: 400, aerobic: 800 } },
      { status: "running", duration_seconds: 999, active_calories: 999, avg_hr: 199, max_hr: 200, zones: { vo2max: 999 } },
    ])).toMatchObject({
      sessionCount: 2,
      durationSeconds: 1800,
      activeCalories: 350,
      averageHeartRate: 120,
      maxHeartRate: 170,
      trainingLoad: 24,
      virtualSteps: 900,
      totalZoneSeconds: 1800,
      zoneSeconds: { light: 500, intensive: 500, aerobic: 800, anaerobic: 0, vo2max: 0 },
    });
  });

  it("liczy dzienną średnią kcal od 20 sierpnia wraz z dniami bez treningu", () => {
    const session = (year, month, day, active_calories) => ({
      status: "finished",
      started_at: new Date(year, month - 1, day, 12).getTime(),
      active_calories,
    });
    const result = calculateDailyWorkoutCaloriesAverage([
      session(2026, 8, 19, 999),
      session(2026, 8, 20, 713),
      session(2026, 8, 21, 619),
      session(2026, 8, 22, 1208.4),
      { ...session(2026, 8, 23, 999), status: "running" },
    ], { now: new Date(2026, 7, 23, 18) });
    expect(result).toEqual({ totalCalories: 2540.4, dayCount: 4, averageCalories: 635.1 });
  });
});

describe("Live Workout dashboard streakometer", () => {
  it("zalicza plan po wykonaniu co najmniej 90% czasu i ignoruje FREE RIDE", () => {
    const workout = { date: "2026-08-22", type: "base", duration: 42 };
    expect(isWorkoutDayCompleted(workout, [
      { plan_date: workout.date, status: "finished", duration_seconds: 2268 },
    ])).toBe(true);
    expect(isWorkoutDayCompleted(workout, [
      { plan_id: "free-ride", plan_date: workout.date, status: "finished", duration_seconds: 3600 },
    ])).toBe(false);
  });

  it("honoruje jawny wynik etapów zamiast samego długiego czasu sesji", () => {
    const workout = { date: "2026-08-22", type: "base", duration: 42 };
    expect(isWorkoutDayCompleted(workout, [
      { plan_date: workout.date, status: "finished", duration_seconds: 5000, plan_completed: false },
    ])).toBe(false);
    expect(isWorkoutDayCompleted(workout, [
      { plan_date: workout.date, status: "finished", duration_seconds: 2000, plan_completed: true },
    ])).toBe(true);
  });

  it("liczy serię zaplanowanych sesji, pomija odpoczynek i nie karze za trwający dzień", () => {
    const schedule = [
      { date: "2026-08-22", type: "base", duration: 30 },
      { date: "2026-08-23", type: "rest", duration: 0 },
      { date: "2026-08-24", type: "tempo", duration: 30 },
      { date: "2026-08-25", type: "intervals", duration: 30 },
    ];
    const history = [
      { plan_date: "2026-08-22", status: "finished", duration_seconds: 1800 },
      { plan_date: "2026-08-24", status: "finished", duration_seconds: 1800 },
    ];
    expect(getWorkoutStreak(schedule, history, {}, "2026-08-25")).toBe(2);
  });

  it("pokazuje siedmiodniowe okno z ukończeniem, dniem bieżącym i planem naprzód", () => {
    const schedule = Array.from({ length: 8 }, (_, index) => ({
      date: `2026-08-${String(22 + index).padStart(2, "0")}`,
      type: index === 1 ? "rest" : "base",
      duration: 30,
    }));
    const days = buildWorkoutStreakometer(schedule, [
      { plan_date: "2026-08-22", status: "finished", duration_seconds: 1800 },
    ], {}, "2026-08-24");
    expect(days).toHaveLength(7);
    expect(days[0]).toMatchObject({ date: "2026-08-22", state: "completed" });
    expect(days[1]).toMatchObject({ date: "2026-08-23", type: "rest", state: "rest" });
    expect(days[2]).toMatchObject({ date: "2026-08-24", isToday: true, state: "planned" });
    expect(days[3]).toMatchObject({ date: "2026-08-25", state: "upcoming" });
  });
});
