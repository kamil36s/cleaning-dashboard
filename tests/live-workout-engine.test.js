import { describe, expect, it } from "vitest";

import {
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
} from "../js/live-workout-engine.js";
import { calculateFatigue, optimizeWorkoutPlan } from "../js/live-workout-plan-optimizer.js";
import { exportWorkoutToTCX, importLocalStorageBackup, validateFullBackup } from "../js/live-workout-transfer.js";

describe("workout engine", () => {
  it("derives contiguous zones and an age fallback HRmax", () => {
    expect(resolveMaxHr({ ageYears: 30 })).toBe(190);
    expect(calculateHeartRateZones({ maxHr: 190 }).map(({ min, max }) => [min, max])).toEqual([
      [95, 113], [114, 132], [133, 151], [152, 170], [171, 190],
    ]);
  });

  it("calculates Keytel energy and uses BMR below 50% HRmax", () => {
    expect(calculateCaloriesPerSecond({ heartRate: 80, maxHr: 190, bmrKcal: 1440 })).toBeCloseTo(1 / 60, 6);
    expect(calculateCaloriesPerSecond({ heartRate: 150, weightKg: 80, ageYears: 30, sex: "male", maxHr: 190 })).toBeGreaterThan(.1);
    expect(estimateCaloriesFromZones({ light: 300, intensive: 120 }, { weightKg: 80, ageYears: 30, sex: "male", maxHr: 190 })).toBeGreaterThan(0);
  });

  it("kalibruje rowerek stacjonarny na niezależnych sesjach Mi Fitness", () => {
    const profile = { weightKg: 93.6, ageYears: 30, sex: "male", maxHr: 190 };
    const reference = [
      [2513, 301, 126], [1709, 302, 140], [2415, 317, 119],
      [2514, 443, 140], [522, 56, 121], [1258, 214, 151],
    ].map(([duration_seconds, active_calories, avg_hr]) => ({
      status: "finished", source: "Xiaomi Watch 2 · Mi Fitness", duration_seconds, active_calories, avg_hr,
    }));
    const calibration = deriveIndoorCyclingCalibration(reference, profile);
    expect(calibration).toMatchObject({ sampleCount: 6, calibrated: true });
    expect(calibration.factor).toBeCloseTo(.712, 2);
    expect(calibration.meanAbsoluteError).toBeLessThan(25);
    const raw = calculateCaloriesPerSecond({ ...profile, heartRate: 140 });
    expect(calculateIndoorCyclingCaloriesPerSecond({ ...profile, heartRate: 140 }, calibration.factor)).toBeCloseTo(raw * calibration.factor, 8);
  });

  it("calculates weighted zone load, target deltas and segment widths", () => {
    expect(calculateTrimp({ light: 60, intensive: 60, aerobic: 60 })).toBe(6);
    expect(getTargetZoneGuide(120, "aerobic", { maxHr: 190 }).label).toBe("▲ PRZYSPIESZ (+13 BPM)");
    expect(getTargetZoneGuide(140, "aerobic", { maxHr: 190 }).state).toBe("target");
    expect(calculateSegmentLayout([{ duration_minutes: 10 }, { duration_minutes: 30 }, { duration_minutes: 10 }]).map((item) => item.percent)).toEqual([20, 60, 20]);
  });

  it("credits actual HR zones up to a fixed plan and separates excess", () => {
    const result = calculateZoneFulfillment(
      { intensive: 8 * 60, aerobic: 14 * 60 },
      { intensive: 10, aerobic: 10 },
    );
    expect(result.plannedSeconds).toBe(20 * 60);
    expect(result.creditedSeconds).toBe(18 * 60);
    expect(result.excessSeconds).toBe(4 * 60);
    expect(result.deficitSeconds).toBe(2 * 60);
    expect(result.progress).toBe(90);
  });
});

describe("plan optimizer", () => {
  const workout = { type: "intervals", duration: 50, zones: { light: 8, intensive: 7, aerobic: 20, anaerobic: 12, vo2max: 3 } };

  it("compares 7-day load with the 28-day weekly baseline", () => {
    const today = new Date("2026-08-28T12:00:00");
    const loads = Array.from({ length: 28 }, (_, index) => ({ date: new Date(2026, 7, index + 1), load: 10 }));
    expect(calculateFatigue(loads, today)).toMatchObject({ acuteLoad: 70, chronicLoad: 70, fatigueRatio: 1 });
  });

  it("replaces a hard workout after poor sleep", () => {
    const result = optimizeWorkoutPlan(workout, { sleepScore: 40 });
    expect(result.workout.type).toBe("recovery");
    expect(result.workout.zones.light).toBeGreaterThan(0);
    expect(result.reason).toContain("sen");
  });

  it("reduces volume after a high-step day", () => {
    const result = optimizeWorkoutPlan(workout, { steps: 14000 });
    expect(result.workout.duration).toBeLessThan(50);
    expect(result.reason).toContain("12 000");
  });

  it("does not turn a scheduled rest day into a workout", () => {
    const rest = { type: "rest", duration: 0, zones: { light: 0, intensive: 0, aerobic: 0, anaerobic: 0, vo2max: 0 } };
    const result = optimizeWorkoutPlan(rest, { steps: 15000, sleepScore: 20, weightTrendKg: -1 });
    expect(result.changed).toBe(false);
    expect(result.workout.type).toBe("rest");
  });

  it("adds controlled progression after well-completed recent sessions", () => {
    const completed = {
      status: "finished",
      duration_seconds: 3000,
      planned_duration_minutes: 50,
      target_zones: workout.zones,
      zones: Object.fromEntries(Object.entries(workout.zones).map(([key, minutes]) => [key, minutes * 60])),
    };
    const result = optimizeWorkoutPlan(workout, { recentWorkouts: [completed, completed] });
    expect(result.workout.duration).toBeGreaterThan(50);
    expect(result.reason).toContain("progresji");
    expect(result.completionScore).toBeGreaterThanOrEqual(.85);
  });

  it("prioritizes Z2 when the explicit goal is weight reduction", () => {
    const result = optimizeWorkoutPlan(workout, { goal: "weight_loss" });
    expect(result.workout.zones.intensive).toBeGreaterThan(workout.zones.intensive);
    expect(result.workout.zones.aerobic).toBeLessThan(workout.zones.aerobic);
    expect(result.workout.duration).toBe(workout.duration);
    expect(result.reason).toContain("cel redukcji");
  });
});

describe("training transfer", () => {
  it("exports a Garmin-style biking TCX", () => {
    const xml = exportWorkoutToTCX({
      started_at: 1_777_000_000_000,
      duration_seconds: 60,
      active_calories: 12,
      samples: [{ timestamp: 1_777_000_000_000, heart_rate: 140 }],
    });
    expect(xml).toContain('<Activity Sport="Biking">');
    expect(xml).toContain("<Trackpoint>");
    expect(xml).toContain("<HeartRateBpm><Value>140</Value></HeartRateBpm>");
    expect(xml).toContain("<Calories>12</Calories>");
  });

  it("validates and imports local storage backup", () => {
    const storage = { data: new Map(), get length() { return this.data.size; }, key(index) { return [...this.data.keys()][index]; }, setItem(key, value) { this.data.set(key, value); }, clear() { this.data.clear(); } };
    const backup = { kind: "cleaning-dashboard-full-backup", schemaVersion: 1, localStorage: { a: "1" }, workouts: [] };
    expect(validateFullBackup(backup)).toBe(backup);
    expect(importLocalStorageBackup(backup, { storage })).toBe(1);
    expect(storage.data.get("a")).toBe("1");
  });
});
