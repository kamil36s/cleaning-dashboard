import { describe, expect, it } from "vitest";

import {
  exerciseSeries,
  lineChartSvg,
  recoveryScore,
  weeklySetBuckets,
} from "../js/strength-visuals.js";

describe("Strength visual data adapters", () => {
  it("builds exercise progress from real comparable sessions", () => {
    const history = [
      { exercise_id: "curl", session_id: "one", completed_at: Date.parse("2026-09-01T10:00:00Z"), reps: 8, quality: 1 },
      { exercise_id: "curl", session_id: "one", completed_at: Date.parse("2026-09-01T10:03:00Z"), reps: 7, quality: 1 },
      { exercise_id: "curl", session_id: "two", completed_at: Date.parse("2026-09-08T10:00:00Z"), reps: 10, quality: 1 },
      { exercise_id: "press", session_id: "three", completed_at: Date.parse("2026-09-08T11:00:00Z"), reps: 99, quality: 1 },
    ];

    expect(exerciseSeries(history, "curl", "total").map((item) => item.value)).toEqual([15, 10]);
    expect(exerciseSeries(history, "curl", "max").map((item) => item.value)).toEqual([8, 10]);
    expect(exerciseSeries(history, "curl", "weight")).toEqual([]);
  });

  it("uses only saved quality sets in the four-week chart", () => {
    const reference = Date.parse("2026-09-11T12:00:00Z");
    const history = [
      { completed_at: Date.parse("2026-09-10T10:00:00Z"), quality: 1 },
      { completed_at: Date.parse("2026-09-10T11:00:00Z"), quality: 0 },
      { completed_at: Date.parse("2026-09-03T10:00:00Z"), quality: 1 },
    ];

    expect(weeklySetBuckets(history, reference).map((item) => item.sets)).toEqual([0, 0, 1, 1]);
  });

  it("labels recovery as an explicit heuristic and keeps empty charts intentional", () => {
    expect(recoveryScore([{ status: "green" }, { status: "yellow" }, { status: "red" }])).toBe(63);
    expect(lineChartSvg([], { label: "Exact weight" })).toContain("Za mało porównywalnych danych");
    expect(lineChartSvg([], { label: "Exact weight" })).not.toMatch(/<polyline/);
  });
});
