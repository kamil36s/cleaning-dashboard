import { describe, expect, it } from "vitest";

import { estimateMissingCalories } from "../js/diet-estimation.js";

function manualDays() {
  return [
    ["2026-06-03", 2200],
    ["2026-06-04", 2200],
    ["2026-06-05", 2200],
    ["2026-06-06", 2200],
    ["2026-06-07", 2200],
  ].map(([day, manualCalories]) => ({ day, manualCalories, goalKcal: 2200 }));
}

describe("diet calorie estimation", () => {
  it("estimates a missing day from manual baseline, weight trend, and steps", () => {
    const estimates = estimateMissingCalories([
      { day: "2026-06-01", weightKg: 99, steps: 10000 },
      ...manualDays().map((day) => ({ ...day, steps: 10000 })),
      { day: "2026-06-08", weightKg: 100, steps: 10000 },
      { day: "2026-06-09", goalKcal: 2200, steps: 12000 },
      { day: "2026-06-10", weightKg: 101, steps: 10000 },
    ], {
      startDay: "2026-06-09",
      endDay: "2026-06-09",
      today: "2026-06-20",
    });

    expect(estimates).toHaveLength(1);
    expect(estimates[0]).toMatchObject({
      day: "2026-06-09",
      caloriesSource: "estimated",
      estimateConfidence: "high",
    });
    expect(estimates[0].estimatedCalories).toBeGreaterThan(3900);
    expect(estimates[0].estimateComponents.stepsAdjustment).toBe(90);
  });

  it("does not estimate manual days or the current unfinished day", () => {
    const estimates = estimateMissingCalories([
      ...manualDays(),
      { day: "2026-06-08", manualCalories: 2100, goalKcal: 2200 },
      { day: "2026-06-09", goalKcal: 2200 },
    ], {
      startDay: "2026-06-08",
      endDay: "2026-06-09",
      today: "2026-06-09",
    });

    expect(estimates).toEqual([]);
  });

  it("still estimates without weight or usable steps and marks confidence low", () => {
    const estimates = estimateMissingCalories([
      ...manualDays(),
      { day: "2026-06-08", goalKcal: 2300 },
      { day: "2026-06-09", goalKcal: 2300 },
    ], {
      startDay: "2026-06-08",
      endDay: "2026-06-09",
      today: "2026-06-20",
    });

    expect(estimates).toHaveLength(2);
    expect(estimates.every((estimate) => estimate.estimateConfidence === "low")).toBe(true);
    expect(estimates.every((estimate) => estimate.estimatedCalories === 2200)).toBe(true);
  });

  it("uses the calorie target fallback when manual history is too thin", () => {
    const estimates = estimateMissingCalories([
      { day: "2026-06-07", manualCalories: 2100, goalKcal: 2200 },
      { day: "2026-06-08", goalKcal: 2400 },
    ], {
      startDay: "2026-06-08",
      endDay: "2026-06-08",
      today: "2026-06-20",
    });

    expect(estimates).toHaveLength(1);
    expect(estimates[0].estimatedCalories).toBe(2400);
    expect(estimates[0].estimateConfidence).toBe("low");
  });

  it("does not estimate ignored days", () => {
    const estimates = estimateMissingCalories([
      ...manualDays(),
      { day: "2026-06-08", goalKcal: 2200, ignored: true },
    ], {
      startDay: "2026-06-08",
      endDay: "2026-06-08",
      today: "2026-06-20",
    });

    expect(estimates).toEqual([]);
  });
});
