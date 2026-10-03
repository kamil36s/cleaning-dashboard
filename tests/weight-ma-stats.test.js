import { describe, expect, it } from "vitest";
import {
  aggregateDailyWeightEvents,
  calculateMa7Stats,
  calculateMovingAverageSeries,
  interpolateDailyWeights,
} from "../js/weight-ma-stats.js";

function event(day, weightKg, suffix = "08:00:00") {
  return { timestamp: `${day}T${suffix}`, weightKg };
}

function dateSeries(startDay, count, startWeight, dailyChange) {
  const start = Date.parse(`${startDay}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) => event(
    new Date(start + index * 86_400_000).toISOString().slice(0, 10),
    startWeight + index * dailyChange,
  ));
}

describe("weight MA7 statistics", () => {
  it("averages multiple measurements from the same day", () => {
    expect(aggregateDailyWeightEvents([
      event("2026-08-01", 90),
      event("2026-08-01", 92, "18:00:00"),
    ])).toEqual([{ day: "2026-08-01", weightKg: 91 }]);
  });

  it("interpolates missing calendar days before calculating MA7", () => {
    const dense = interpolateDailyWeights([
      { day: "2026-08-01", weightKg: 90 },
      { day: "2026-08-03", weightKg: 88 },
    ]);
    expect(dense).toEqual([
      { day: "2026-08-01", weightKg: 90, interpolated: false },
      { day: "2026-08-02", weightKg: 89, interpolated: true },
      { day: "2026-08-03", weightKg: 88, interpolated: false },
    ]);
    expect(calculateMovingAverageSeries(dense, 2).at(-1)?.value).toBe(88.5);
  });

  it("calculates trend, weekly pace, calorie deficit, distance and ETA", () => {
    const stats = calculateMa7Stats(dateSeries("2026-08-01", 30, 90, -0.1), {
      rateStartDay: "2026-08-20",
    });
    expect(stats.day).toBe("2026-08-30");
    expect(stats.currentMa7Kg).toBeCloseTo(87.4, 6);
    expect(stats.trend).toBe("down");
    expect(stats.trendDeltaKg).toBeCloseTo(-0.1, 6);
    expect(stats.weeklyChangeKg).toBeCloseTo(-0.7, 6);
    expect(stats.dailyDeficitKcal).toBeCloseTo(750, 6);
    expect(stats.distanceToGoalKg).toBeCloseTo(4.4, 6);
    expect(stats.rateSinceStartKgPerWeek).toBeCloseTo(-0.7, 6);
    expect(stats.eta).toMatchObject({ status: "future", day: "2026-10-13" });
  });

  it("does not forecast a target date without a falling 14-day trend", () => {
    const stats = calculateMa7Stats(dateSeries("2026-08-01", 30, 86, 0));
    expect(stats.trend).toBe("stable");
    expect(stats.eta).toMatchObject({ status: "no-loss", day: null });
  });
});
