import { describe, expect, it } from "vitest";

import {
  habitMetrics,
  habitLifetimeSummary,
  habitPeriodSummary,
  normalizeHabitDataset,
  recentDateKeys,
  reorderHabits,
  resolvedValue,
  shiftDateKey,
  summarizeHabitsForDashboard,
  upsertPreviewMutation,
} from "../js/habits-app-model.js";

describe("habits app frontend model", () => {
  it("keeps a recorded 0 mg visible in the dashboard summary", () => {
    const habits = normalizeHabitDataset({ habits: [
      { id: 1, name: "Concerta/Atenza", type: 1, unit: "mg", points: [[Date.parse("2026-09-26T00:00:00Z"), 0]] },
    ] });
    const summary = summarizeHabitsForDashboard(habits, "2026-09-26");
    expect(summary.habits[0]).toMatchObject({ recorded: true, recordedZero: true, todayDisplay: "0 mg" });
    expect(summary.stats).toMatchObject({ doneToday: 0, missedToday: 1, totalActive: 1 });
  });
  it("normalizes Loop binary and numerical values", () => {
    const habits = normalizeHabitDataset({
      habits: [
        { id: 1, name: "Don't drink", type: 0, points: [[Date.parse("2026-08-25T00:00:00Z"), 2]] },
        { id: 2, name: "Pregabalin", type: 1, unit: "mg", points: [[Date.parse("2026-08-25T00:00:00Z"), 150000]] },
      ],
    });

    expect(habits[0]).toMatchObject({ name: "Don't drink", type: "binary", category: "lifestyle" });
    expect(habits[0].entries.get("2026-08-25")).toBe(2);
    expect(habits[1]).toMatchObject({ name: "Pregabalin", type: "numeric", unit: "mg" });
    expect(habits[1].entries.get("2026-08-25")).toBe(150);
  });

  it("builds stable UTC date windows across daylight-saving changes", () => {
    expect(shiftDateKey("2026-03-29", 1)).toBe("2026-03-30");
    expect(recentDateKeys("2026-04-02", 4)).toEqual([
      "2026-03-30",
      "2026-03-31",
      "2026-04-01",
      "2026-04-02",
    ]);
  });

  it("reorders habits and assigns stable positions for cross-device sync", () => {
    const reordered = reorderHabits([
      { id: "creatine", position: 0 },
      { id: "concerta", position: 8 },
      { id: "b-complex", position: 11 },
    ], "creatine", "b-complex");

    expect(reordered.map((habit) => habit.id)).toEqual(["concerta", "creatine", "b-complex"]);
    expect(reordered.map((habit) => habit.position)).toEqual([0, 1, 2]);
  });

  it("overlays queued local mutations and calculates streak metrics", () => {
    const [habit] = normalizeHabitDataset({
      habits: [{
        id: 7,
        name: "Meditation",
        type: 0,
        points: [
          [Date.parse("2026-08-22T00:00:00Z"), 2],
          [Date.parse("2026-08-23T00:00:00Z"), 2],
        ],
      }],
    });
    const mutations = upsertPreviewMutation([], {
      mutationId: "mutation-1",
      habitId: habit.id,
      habitName: habit.name,
      date: "2026-08-24",
      value: 2,
      updatedAt: "2026-08-24T12:00:00Z",
    });

    expect(resolvedValue(habit, "2026-08-24", mutations)).toBe(2);
    expect(habitMetrics(habit, "2026-08-24", mutations, 3)).toMatchObject({
      completed: 3,
      score: 100,
      currentStreak: 3,
      bestStreak: 3,
    });
  });

  it("summarizes binary success and numeric averages for a selected period", () => {
    const [binary, numeric] = normalizeHabitDataset({
      habits: [
        {
          id: 1,
          name: "Don't drink",
          type: 0,
          points: [
            [Date.parse("2026-08-23T00:00:00Z"), 2],
            [Date.parse("2026-08-24T00:00:00Z"), 0],
          ],
        },
        {
          id: 2,
          name: "Pregabalin",
          type: 1,
          unit: "mg",
          points: [
            [Date.parse("2026-08-23T00:00:00Z"), 300000],
            [Date.parse("2026-08-24T00:00:00Z"), 150000],
          ],
        },
      ],
    });

    expect(habitPeriodSummary(binary, "2026-08-24", [], 7)).toMatchObject({
      days: 7,
      recorded: 2,
      completed: 1,
      percent: 14,
    });
    expect(habitPeriodSummary(numeric, "2026-08-24", [], 7)).toMatchObject({
      recorded: 2,
      average: 225,
    });
    expect(habitLifetimeSummary(binary, "2026-08-24")).toMatchObject({
      startDate: "2026-08-23",
      elapsedDays: 1,
      days: 2,
      completed: 1,
      percent: 50,
    });
    expect(habitLifetimeSummary(numeric, "2026-08-24")).toMatchObject({
      startDate: "2026-08-23",
      average: 225,
    });
  });
});
