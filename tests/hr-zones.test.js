import { describe, expect, it } from "vitest";

import {
  buildWorkoutWindows,
  calculateHrZoneDistribution,
  getHrZone,
  isTimestampInWorkout,
} from "../js/hr-zones.js";

describe("heart-rate zone modes", () => {
  it("uses the exact daily thresholds and descriptions", () => {
    expect(getHrZone(59, false)).toMatchObject({ color: "#1d4ed8", label: "Sen i głęboki relaks" });
    expect(getHrZone(60, false)).toMatchObject({ color: "#15803d", label: "Baza i komfort" });
    expect(getHrZone(86, false)).toMatchObject({ color: "#eab308", label: "Lekki ruch i pobudzenie" });
    expect(getHrZone(101, false)).toMatchObject({ color: "#f97316", label: "Wysoka aktywność lub silny stres" });
    expect(getHrZone(121, false)).toMatchObject({ color: "#b91c1c", label: "Alert / Trening" });
    expect(getHrZone(121, false).description).toContain("sygnał ostrzegawczy");
  });

  it("switches to sports zones during a workout", () => {
    expect(getHrZone(113, true)).toEqual({ color: "#1d4ed8", label: "Z1 - Regeneracja", description: null });
    expect(getHrZone(114, true)).toEqual({ color: "#15803d", label: "Z2 - Baza tlenowa", description: null });
    expect(getHrZone(133, true)).toEqual({ color: "#eab308", label: "Z3 - Tempo", description: null });
    expect(getHrZone(152, true)).toEqual({ color: "#f97316", label: "Z4 - Próg / anaerobowa", description: null });
    expect(getHrZone(171, true)).toEqual({ color: "#b91c1c", label: "Z5 - VO2 Max", description: null });
  });

  it("builds finished and active workout windows for the selected day", () => {
    const start = 1_000_000;
    const end = start + 86_400_000 - 1;
    const windows = buildWorkoutWindows([
      { id: "finished", started_at: start + 1000, ended_at: start + 5000, status: "finished" },
      { id: "active", workoutStartTime: start + 10_000, isWorkoutActive: true },
      { id: "outside", started_at: end + 1000, duration_seconds: 60, status: "finished" },
    ], start, end, start + 20_000);

    expect(windows).toHaveLength(2);
    expect(windows[0]).toMatchObject({ id: "finished", isActive: false });
    expect(windows[1]).toMatchObject({ id: "active", isActive: true, actualEnd: start + 20_000 });
    expect(isTimestampInWorkout(start + 3000, windows)).toBe(true);
    expect(isTimestampInWorkout(start + 8000, windows)).toBe(false);
  });

  it("keeps workout type metadata for chart presentation", () => {
    const start = 1_000_000;
    const windows = buildWorkoutWindows([{
      id: "walk",
      started_at: start + 1000,
      duration_seconds: 60,
      status: "finished",
      workout_type: "virtual_walk",
      plan_id: "virtual-walk",
    }], start, start + 86_400_000);

    expect(windows[0]).toMatchObject({ workoutType: "virtual_walk", planId: "virtual-walk" });
  });

  it("calculates separate time distributions for daily and sports modes", () => {
    const samples = [
      { timestamp: 0, heart_rate: 70 },
      { timestamp: 1000, heart_rate: 90 },
      { timestamp: 2000, heart_rate: 120 },
      { timestamp: 3000, heart_rate: 160 },
    ];
    const distribution = calculateHrZoneDistribution(samples, [{ actualStart: 2000, actualEnd: 4000 }]);

    expect(distribution.daily.totalMs).toBe(2000);
    expect(distribution.daily.zones.find((zone) => zone.label === "Baza i komfort")?.percent).toBe(50);
    expect(distribution.daily.zones.find((zone) => zone.label === "Lekki ruch i pobudzenie")?.percent).toBe(50);
    expect(distribution.sports.totalMs).toBe(2000);
    expect(distribution.sports.zones.find((zone) => zone.label === "Z2 - Baza tlenowa")?.percent).toBe(50);
    expect(distribution.sports.zones.find((zone) => zone.label === "Z4 - Próg / anaerobowa")?.percent).toBe(50);
  });
});
