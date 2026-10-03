import { describe, expect, it } from "vitest";
import {
  createRingSleepDataset,
  createRingSleepDatasets,
  createWatchSleepDataset,
  createWatchSleepDatasets,
  mergeSleepDatasets,
  normalizeRingSleepWindow,
  selectLatestSleepDataset,
  sleepNightKey,
} from "../js/sleep-api.js";

describe("sleep data sources", () => {
  it("corrects legacy ring nights anchored one day after their real start", () => {
    const window = normalizeRingSleepWindow({
      sleepDate: "2026-09-03",
      sleepStartUtc: "2026-09-03T20:28:00Z",
      sleepEndUtc: "2026-09-04T04:29:00Z",
    });

    expect(window.start).toBe("2026-09-02T20:28:00.000Z");
    expect(window.end).toBe("2026-09-03T04:29:00.000Z");
  });

  it("uses the most complete ring snapshot and labels its source", () => {
    const dataset = createRingSleepDataset({
      sleep: [
        {
          sleepDate: "2026-09-03",
          sleepStartUtc: "2026-09-03T20:28:00Z",
          sleepEndUtc: "2026-09-03T21:10:00Z",
          totalMinutes: 42,
          createdAt: "2026-09-02T23:10:00Z",
        },
        {
          sleepDate: "2026-09-03",
          sleepStartUtc: "2026-09-03T20:28:00Z",
          sleepEndUtc: "2026-09-04T04:04:00Z",
          totalMinutes: 456,
          createdAt: "2026-09-03T06:04:00Z",
        },
      ],
      heartRate: [
        { timestampUtc: "2026-09-03T00:00:00Z", bpm: 54 },
      ],
    });

    expect(dataset.sourceLabel).toBe("COLMI Ring");
    expect(dataset.heartRateSource).toBe("COLMI Ring");
    expect(dataset.sleepWindow.totalMinutes).toBe(456);
    expect(dataset.samples).toHaveLength(1);
  });

  it("adapts the latest Health Connect sleep session as watch data", () => {
    const dataset = createWatchSleepDataset({
      snapshot: {
        payload: {
          heart_rate: { samples: [{ time: "2026-09-02T23:00:00Z", bpm: 57 }] },
          sleep: {
            sessions: [{
              start: "2026-09-02T22:00:00Z",
              end: "2026-09-03T06:00:00Z",
              stages: [],
            }],
          },
        },
      },
    });

    expect(dataset.sourceKind).toBe("watch");
    expect(dataset.sourceLabel).toContain("Smartwatch");
    expect(dataset.sleepWindow.totalMinutes).toBe(480);
    expect(dataset.samples).toHaveLength(1);
  });

  it("chooses the source containing the newest completed night", () => {
    const selected = selectLatestSleepDataset([
      { sourceKind: "watch", sleepWindow: { end: "2026-09-02T06:00:00Z" } },
      { sourceKind: "ring", sleepWindow: { end: "2026-09-03T06:00:00Z" } },
    ]);

    expect(selected.sourceKind).toBe("ring");
  });

  it("keeps every ring night while merging before-midnight partial snapshots", () => {
    const datasets = createRingSleepDatasets({
      sleep: [
        {
          sleepDate: "2026-09-04",
          sleepStartUtc: "2026-09-03T20:06:00Z",
          sleepEndUtc: "2026-09-04T04:03:00Z",
          totalMinutes: 477,
          createdAt: "2026-09-04T06:17:00Z",
        },
        {
          sleepDate: "2026-09-04",
          sleepStartUtc: "2026-09-04T20:40:00Z",
          sleepEndUtc: "2026-09-04T21:52:00Z",
          totalMinutes: 72,
          createdAt: "2026-09-05T06:18:00Z",
        },
        {
          sleepDate: "2026-09-05",
          sleepStartUtc: "2026-09-04T20:40:00Z",
          sleepEndUtc: "2026-09-05T04:28:00Z",
          totalMinutes: 468,
          createdAt: "2026-09-05T06:28:00Z",
        },
      ],
    });

    expect(datasets).toHaveLength(2);
    expect(datasets.map((dataset) => dataset.nightKey)).toEqual(["2026-09-05", "2026-09-04"]);
    expect(datasets.map((dataset) => dataset.sleepWindow.totalMinutes)).toEqual([468, 477]);
  });

  it("deduplicates Health Connect snapshots and prefers the watch for the same night", () => {
    const watches = createWatchSleepDatasets({
      snapshots: [
        {
          received_at: "2026-09-05T07:00:00Z",
          payload: {
            heart_rate: { samples: [] },
            sleep: { sessions: [{
              start: "2026-09-04T21:00:00Z",
              end: "2026-09-05T05:00:00Z",
              manufacturer: "Xiaomi",
              model: "Watch",
              stages: [],
            }] },
          },
        },
        {
          received_at: "2026-09-05T07:15:00Z",
          payload: {
            heart_rate: { samples: [] },
            sleep: { sessions: [{
              start: "2026-09-04T21:00:00Z",
              end: "2026-09-05T05:00:00Z",
              manufacturer: "Xiaomi",
              model: "Watch",
              stages: [],
            }] },
          },
        },
      ],
    });
    const ring = [{
      id: "2026-09-05-ring",
      nightKey: "2026-09-05",
      sourceKind: "ring",
      sourceLabel: "COLMI Ring",
      heartRateSource: "COLMI Ring",
      sleepWindow: {
        start: "2026-09-04T20:40:00Z",
        end: "2026-09-05T04:28:00Z",
        totalMinutes: 468,
      },
      samples: [{ timestamp: "2026-09-05T00:00:00Z", bpm: 55, movement: 0 }],
    }];
    const merged = mergeSleepDatasets(ring, watches);

    expect(watches).toHaveLength(1);
    expect(watches[0].sourceLabel).toBe("Xiaomi Watch");
    expect(merged[0].sourceKind).toBe("watch");
    expect(merged[0].heartRateSource).toContain("COLMI Ring");
    expect(merged[0].samples).toHaveLength(1);
  });

  it("assigns a before-midnight partial session to the following morning", () => {
    expect(sleepNightKey("2026-09-04T20:40:00Z", "2026-09-04T21:52:00Z"))
      .toBe("2026-09-05");
  });
});
