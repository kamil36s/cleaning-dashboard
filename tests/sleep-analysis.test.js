import { describe, expect, it } from "vitest";
import {
  analyzeSleepData,
  analyzeSleepHistory,
  normalizeSleepSamples,
} from "../js/sleep-analysis.js";

const MINUTE_MS = 60_000;

function sampleSeries({ lateMinimum = false, spikes = [] } = {}) {
  const start = Date.parse("2026-09-02T21:30:00Z");
  return Array.from({ length: 109 }, (_, index) => {
    const minutes = index * 5;
    const awake = minutes < 30 || minutes >= 510;
    let bpm = awake ? 78 : lateMinimum
      ? 64 - Math.min(12, Math.floor((minutes - 30) / 35))
      : 58 + Math.min(8, Math.floor((minutes - 30) / 70));
    let movement = awake ? 2 : 0;
    if (spikes.includes(minutes)) {
      bpm = 82;
      movement = 1;
    }
    return {
      timestamp: new Date(start + minutes * MINUTE_MS).toISOString(),
      bpm,
      movement,
    };
  });
}

describe("sleep analysis", () => {
  it("normalizes, sorts and rejects invalid BLE readings", () => {
    const result = normalizeSleepSamples([
      { timestamp: "bad", bpm: 60, movement: 0 },
      { timestamp: "2026-09-03T00:05:00Z", bpm: 62, movement: 0 },
      { timestamp: "2026-09-03T00:00:00Z", bpm: 61, movement: 0 },
      { timestamp: "2026-09-03T00:00:00Z", bpm: 59, movement: 0 },
    ]);

    expect(result).toHaveLength(2);
    expect(result[0].bpm).toBe(59);
    expect(result[1].bpm).toBe(62);
  });

  it("detects sleep, wake time and the lowest 15-minute RHR window", () => {
    const result = analyzeSleepData(sampleSeries());

    expect(result.hasSleep).toBe(true);
    expect(result.sleepStart).toBe("2026-09-02T22:00:00.000Z");
    expect(result.wakeTime).toBe("2026-09-03T06:00:00.000Z");
    expect(result.durationMinutes).toBe(480);
    expect(result.rhr).toBe(58);
    expect(result.rhrWindow.sampleCount).toBe(4);
    expect(result.insight).toBe("Najniższe RHR pojawiło się w pierwszej połowie nocy.");
  });

  it("warns when the minimum RHR appears in the second half of sleep", () => {
    const result = analyzeSleepData(sampleSeries({ lateMinimum: true }));

    expect(result.rhrAt).toBeGreaterThan(result.sleepMidpoint);
    expect(result.insight).toBe("Najniższe RHR pojawiło się w drugiej połowie nocy.");
  });

  it("prioritizes the restless-sleep insight after multiple grouped spikes", () => {
    const result = analyzeSleepData(sampleSeries({ spikes: [120, 240, 360] }));

    expect(result.spikeCount).toBeGreaterThanOrEqual(3);
    expect(result.insight).toBe("W nocy wystąpiło kilka wyraźnych skoków tętna.");
  });

  it("uses a trusted device sleep window even when heart-rate samples are missing", () => {
    const result = analyzeSleepData([], {
      sleepWindow: {
        start: "2026-09-02T20:28:00Z",
        end: "2026-09-03T06:04:00Z",
        totalMinutes: 456,
      },
    });

    expect(result.hasSleep).toBe(true);
    expect(result.durationMinutes).toBe(456);
    expect(result.rhr).toBeNull();
    expect(result.insight).toContain("za mało próbek tętna");
  });

  it("summarizes duration, regularity and recent history without changing source windows", () => {
    const datasets = Array.from({ length: 14 }, (_, index) => {
      const start = Date.parse("2026-08-31T21:00:00Z") + index * 24 * 60 * MINUTE_MS;
      const durationMinutes = index < 7 ? 420 : 480;
      return {
        sleepWindow: {
          start: new Date(start).toISOString(),
          end: new Date(start + durationMinutes * MINUTE_MS).toISOString(),
          totalMinutes: durationMinutes,
        },
        samples: [],
      };
    });

    const result = analyzeSleepHistory(datasets);

    expect(result.nights).toBe(14);
    expect(result.averageDurationMinutes).toBe(450);
    expect(result.targetShare).toBe(100);
    expect(result.typicalStartMinutes).toBe(23 * 60);
    expect(result.typicalWakeMinutes).toBe(6 * 60 + 30);
    expect(result.regularityMinutes).toBe(15);
    expect(result.durationTrendMinutes).toBe(60);
    expect(result.recentNightCount).toBe(7);
  });
});
