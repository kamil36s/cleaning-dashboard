import { describe, expect, it } from "vitest";
import {
  addDaysToInputDate,
  getBloodPressureDailyChartModel,
  getSevenDayAverages,
  getVisibleBloodPressureEntries,
  interpretBloodPressure,
  interpretPulse,
} from "../js/widget-blood-pressure.js";

describe("blood pressure interpretation", () => {
  it("uses the worse category when systolic and diastolic differ", () => {
    expect(interpretBloodPressure(132, 88).key).toBe("elevated");
    expect(interpretBloodPressure(128, 94).key).toBe("high");
  });

  it("marks urgent measurements at either urgent threshold", () => {
    expect(interpretBloodPressure(180, 80).key).toBe("urgent");
    expect(interpretBloodPressure(120, 120).key).toBe("urgent");
  });

  it("interprets resting pulse ranges", () => {
    expect(interpretPulse(49).label).toBe("niski puls");
    expect(interpretPulse(68).key).toBe("normal");
    expect(interpretPulse(101).key).toBe("elevated");
  });
});

describe("blood pressure averages", () => {
  it("computes seven day averages and medication groups", () => {
    const now = new Date("2026-06-22T15:00:00");
    const averages = getSevenDayAverages([
      {
        date: "2026-06-22",
        time: "14:00",
        systolic: 130,
        diastolic: 80,
        pulse: 70,
        tags: ["before-meds"],
      },
      {
        date: "2026-06-21",
        time: "10:00",
        systolic: 140,
        diastolic: 90,
        pulse: 80,
        tags: ["after-concerta"],
      },
      {
        date: "2026-06-10",
        time: "10:00",
        systolic: 160,
        diastolic: 100,
        pulse: 90,
        tags: ["after-bupropion"],
      },
    ], now);

    expect(averages.all).toEqual({
      count: 2,
      systolic: 135,
      diastolic: 85,
      pulse: 75,
    });
    expect(averages.beforeMeds.systolic).toBe(130);
    expect(averages.afterMeds.systolic).toBe(140);
  });
});

describe("blood pressure history list", () => {
  it("shows five entries until full history is requested", () => {
    const entries = Array.from({ length: 7 }, (_, index) => ({ id: String(index) }));

    expect(getVisibleBloodPressureEntries(entries).map((entry) => entry.id)).toEqual([
      "0",
      "1",
      "2",
      "3",
      "4",
    ]);
    expect(getVisibleBloodPressureEntries(entries, true)).toHaveLength(7);
  });
});

describe("blood pressure daily chart", () => {
  it("builds a selected-day chart with real time spacing", () => {
    const model = getBloodPressureDailyChartModel([
      {
        date: "2026-06-24",
        time: "12:00",
        systolic: 138,
        diastolic: 84,
        pulse: 71,
        tags: [],
      },
      {
        date: "2026-06-24",
        time: "08:00",
        systolic: 120,
        diastolic: 76,
        pulse: 69,
        tags: [],
      },
      {
        date: "2026-06-23",
        time: "09:00",
        systolic: 150,
        diastolic: 92,
        pulse: 80,
        tags: [],
      },
    ], "2026-06-24");

    expect(model.points).toHaveLength(2);
    expect(model.points[0].entry.time).toBe("08:00");
    expect(model.points[1].entry.time).toBe("12:00");
    expect(model.points[1].x).toBeGreaterThan(model.points[0].x);
    expect(model.points[0].statusColor).toBe("#22c55e");
    expect(model.points[1].statusColor).toBe("#eab308");
    expect(model.ticks.length).toBeGreaterThan(1);
  });

  it("groups close time labels so they do not overlap", () => {
    const model = getBloodPressureDailyChartModel([
      { date: "2026-06-24", time: "10:30", systolic: 120, diastolic: 76, pulse: 69, tags: [] },
      { date: "2026-06-24", time: "11:58", systolic: 138, diastolic: 84, pulse: 71, tags: [] },
      { date: "2026-06-24", time: "12:00", systolic: 150, diastolic: 90, pulse: 76, tags: [] },
      { date: "2026-06-24", time: "12:01", systolic: 136, diastolic: 82, pulse: 72, tags: [] },
      { date: "2026-06-24", time: "13:54", systolic: 128, diastolic: 78, pulse: 68, tags: [] },
    ], "2026-06-24");

    expect(model.timeLabels.map((label) => label.label)).toEqual([
      "10:30",
      "11:58-12:01",
      "13:54",
    ]);
    expect(model.timeLabels[1].isCluster).toBe(true);
  });

  it("moves chart dates by calendar days", () => {
    expect(addDaysToInputDate("2026-06-01", -1)).toBe("2026-05-31");
    expect(addDaysToInputDate("2026-06-30", 1)).toBe("2026-07-01");
  });
});
