import { beforeEach, describe, expect, it } from "vitest";

import {
  buildWeeklyInsights,
  buildWeeklyWindows,
  initWeeklyInsights,
} from "../js/widget-weekly-insights.js";

const NOW = new Date(2026, 8, 23, 12, 0, 0);

function sleepSnapshot(day, hours) {
  return {
    day,
    payload: {
      sleep: {
        sessions: [{
          start: `${day}T00:00:00Z`,
          end: `${day}T${String(hours).padStart(2, "0")}:00:00Z`,
        }],
      },
    },
  };
}

describe("Weekly Insights widget", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("builds two adjacent seven-day windows", () => {
    expect(buildWeeklyWindows(NOW)).toEqual({
      current: { start: "2026-09-17", end: "2026-09-24" },
      previous: { start: "2026-09-10", end: "2026-09-17" },
    });
  });

  it("selects meaningful comparisons from real tracker history", () => {
    const result = buildWeeklyInsights({
      cleaning: {
        actions: [
          { doneAt: "2026-09-18T09:00:00" },
          { doneAt: "2026-09-19T09:00:00" },
          { doneAt: "2026-09-20T09:00:00" },
          { doneAt: "2026-09-22T09:00:00" },
          { doneAt: "2026-09-12T09:00:00" },
          { doneAt: "2026-09-14T09:00:00" },
        ],
      },
      reading: {
        log: {
          "2026-09-18": { total: 10 },
          "2026-09-21": { total: 20 },
          "2026-09-11": { total: 20 },
          "2026-09-13": { total: 20 },
        },
      },
      jobhunt: {
        jobs: [
          { createdAt: "2026-09-18", applicationStatus: "applied", application: { dateApplied: "2026-09-18", followUpDate: "2026-09-22" } },
          { createdAt: "2026-09-20", applicationStatus: "applied", application: { dateApplied: "2026-09-20" } },
          { createdAt: "2026-09-12", applicationStatus: "applied", application: { dateApplied: "2026-09-12" } },
        ],
      },
      aiUsage: {
        providers: [{ status: "connected", weekly: { remaining: 63 } }],
        history: [
          { checkedAt: "2026-09-18T10:00:00", weeklyBurn: 6 },
          { checkedAt: "2026-09-12T10:00:00", weeklyBurn: 10 },
        ],
      },
      steps: {
        daily: [
          { day: "2026-09-18", steps: 7000, filled: false },
          { day: "2026-09-19", steps: 5000, filled: false },
          { day: "2026-09-11", steps: 4500, filled: false },
          { day: "2026-09-12", steps: 5500, filled: false },
        ],
      },
      sleep: {
        snapshots: [
          sleepSnapshot("2026-09-18", 7),
          sleepSnapshot("2026-09-19", 7),
          sleepSnapshot("2026-09-11", 8),
          sleepSnapshot("2026-09-12", 8),
        ],
      },
    }, { now: NOW });

    expect(result.insights).toHaveLength(5);
    expect(result.insights.find((item) => item.key === "cleaning")).toMatchObject({
      current: 4,
      previous: 2,
      comparison: "+100%",
      tone: "positive",
    });
    expect(result.insights.find((item) => item.key === "reading")).toMatchObject({
      current: 30,
      previous: 40,
      comparison: "-25%",
      tone: "negative",
    });
    expect(result.summary).toContain("Cleaning led the week");
    expect(result.watch.map((item) => item.text).join(" ")).toContain("follow-up");
    expect(result.watch.map((item) => item.text).join(" ")).toContain("Reading dropped");
    expect(result.strongest.label).toBe("Biggest win");
  });

  it("does not invent cards when trackers have no comparable activity", () => {
    const result = buildWeeklyInsights({
      cleaning: { actions: [] },
      reading: { log: {} },
      jobhunt: { jobs: [] },
      aiUsage: { providers: [], history: [] },
      steps: { daily: [] },
      sleep: { snapshots: [] },
    }, { now: NOW });

    expect(result.insights).toEqual([]);
    expect(result.watch).toEqual([]);
    expect(result.summary).toContain("not enough comparable history");
  });

  it("renders a soft fallback when all APIs are unavailable", async () => {
    document.body.innerHTML = '<div id="weekly-insights-root"></div>';
    const root = document.getElementById("weekly-insights-root");
    const widget = initWeeklyInsights({
      root,
      loader: async () => { throw new Error("offline"); },
      schedule: false,
      now: () => NOW,
    });

    await widget.refreshPromise;

    expect(root.textContent).toContain("Weekly insights unavailable");
    expect(root.textContent).toContain("try again automatically");
    widget.destroy();
  });

  it("renders partial results when only one tracker has history", async () => {
    document.body.innerHTML = '<div id="weekly-insights-root"></div>';
    const root = document.getElementById("weekly-insights-root");
    const widget = initWeeklyInsights({
      root,
      loader: async () => ({
        availableSources: 1,
        sources: {
          reading: {
            log: {
              "2026-09-18": { total: 24 },
              "2026-09-12": { total: 12 },
            },
          },
        },
      }),
      schedule: false,
      now: () => NOW,
    });

    await widget.refreshPromise;

    expect(root.textContent).toContain("Reading");
    expect(root.textContent).toContain("24 pages read");
    expect(root.textContent).toContain("1 connected area");
    widget.destroy();
  });
});
