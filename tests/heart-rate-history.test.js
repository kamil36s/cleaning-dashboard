import { describe, expect, it } from "vitest";

import {
  applySmartwatchPriority,
  analyzeHeartRateTelemetry,
  buildHeartRateChartModel,
  buildSmartRingOnlyPhases,
  createLiveHeartRateSample,
  downsampleHeartRatePoints,
  filterUnwornHeartRateSamples,
  fitHeartRateDataRange,
  formatHeartRateTimestamp,
  localDayRange,
  mergeArchivedHeartRateSamples,
  shiftDayKey,
  summarizeHeartRateSamples,
  summarizeHeartRateSamplesByMode,
  workoutPresentation,
  zoomHeartRateRange,
} from "../js/heart-rate-history.js";

describe("heart-rate history helpers", () => {
  it("summarizes every loaded transmission", () => {
    expect(summarizeHeartRateSamples([
      { heart_rate: 100 },
      { heart_rate: 130 },
      { heart_rate: 130 },
    ])).toEqual({
      count: 3,
      average: 120,
      minimum: 100,
      maximum: 130,
    });
  });

  it("summarizes daily and sports samples separately", () => {
    const workoutWindows = [{ actualStart: 2000, actualEnd: 4000 }];

    expect(summarizeHeartRateSamplesByMode([
      { timestamp: 1000, heart_rate: 80 },
      { timestamp: 2000, heart_rate: 140 },
      { timestamp: 3000, heart_rate: 160 },
      { timestamp: 5000, heart_rate: 100 },
    ], workoutWindows)).toEqual({
      daily: { count: 2, average: 90, minimum: 80, maximum: 100 },
      sports: { count: 2, average: 150, minimum: 140, maximum: 160 },
    });
  });

  it("assigns distinct chart styles to cardio, strength and walking sessions", () => {
    const cardio = workoutPresentation({ workoutType: "indoor_cycling", planId: "plan-30" });
    const strength = workoutPresentation({ workoutType: "strength" });
    const walk = workoutPresentation({ workoutType: "virtual_walk" });

    expect(cardio).toMatchObject({ key: "cardio", label: "Cardio z planu" });
    expect(strength).toMatchObject({ key: "strength", label: "Trening siłowy" });
    expect(walk).toMatchObject({ key: "walk", label: "Sesja spacerowa" });
    expect(new Set([cardio.color, strength.color, walk.color]).size).toBe(3);
    expect(workoutPresentation({ planId: "free-ride" })).toMatchObject({
      key: "cardio",
      label: "Cardio dodatkowe",
      color: cardio.color,
    });
  });

  it("formats a stored epoch timestamp with millisecond precision", () => {
    const formatted = formatHeartRateTimestamp(1_777_000_000_123);

    expect(formatted).toContain("123");
    expect(formatted).not.toBe("—");
  });

  it("builds a full-day chart model in chronological order", () => {
    const range = localDayRange("2026-08-24");
    const model = buildHeartRateChartModel([
      { timestamp: range.start + 18 * 60 * 60 * 1000, heart_rate: 150 },
      { timestamp: range.start + 6 * 60 * 60 * 1000, heart_rate: 90 },
    ], range.start, range.end);

    expect(model.points.map((point) => point.bpm)).toEqual([90, 150]);
    expect(model.points[0].x).toBeCloseTo(.25, 3);
    expect(model.points[1].x).toBeCloseTo(.75, 3);
    expect(model.minimum).toBeLessThan(90);
    expect(model.maximum).toBeGreaterThan(150);
  });

  it("moves between calendar days", () => {
    expect(shiftDayKey("2026-08-24", -1)).toBe("2026-08-23");
    expect(shiftDayKey("2026-08-31", 1)).toBe("2026-09-01");
  });

  it("fits the default chart window around the available data", () => {
    const day = localDayRange("2026-08-24");
    const first = day.start + 13 * 60 * 60 * 1000;
    const last = first + 30 * 60 * 1000;
    const fitted = fitHeartRateDataRange([
      { timestamp: first },
      { timestamp: last },
    ], day.start, day.end);

    expect(fitted.start).toBeLessThan(first);
    expect(fitted.end).toBeGreaterThan(last);
    expect(fitted.end - fitted.start).toBeLessThan(day.end - day.start);
  });

  it("zooms around the middle of the visible time range", () => {
    const day = localDayRange("2026-08-24");
    const initial = {
      start: day.start + 8 * 60 * 60 * 1000,
      end: day.start + 12 * 60 * 60 * 1000,
    };
    const zoomed = zoomHeartRateRange(initial, .5, day.start, day.end);

    expect(zoomed.end - zoomed.start).toBeCloseTo((initial.end - initial.start) / 2, 0);
    expect((zoomed.start + zoomed.end) / 2).toBe((initial.start + initial.end) / 2);
  });

  it("reports archive integrity, day coverage and inferred packet loss", () => {
    const day = localDayRange("2026-08-24");
    const valid = (offset, heartRate = 100) => ({
      timestamp: day.start + offset,
      received_at: day.start + offset + 200,
      heart_rate: heartRate,
      status: "running",
      payload: { heart_rate: heartRate },
    });
    const analysis = analyzeHeartRateTelemetry([
      valid(0),
      valid(1000),
      valid(2000),
      valid(4000),
      valid(5000),
      valid(6000, 999),
    ], day.start, day.end);

    expect(analysis.successful).toBe(5);
    expect(analysis.successPercent).toBeCloseTo(83.33, 1);
    expect(analysis.coveredSeconds).toBe(5);
    expect(analysis.lostPackets).toBe(1);
    expect(analysis.lossPercent).toBeCloseTo(16.67, 1);
    expect(analysis.gapCount).toBe(1);
    expect(analysis.streamCount).toBe(1);
  });

  it("normalizes valid SSE telemetry into a temporary live sample", () => {
    expect(createLiveHeartRateSample({
      timestamp: 1_777_000_000_123,
      heart_rate: 87,
      status: "RUNNING",
      cadence_rpm: 82,
    }, 1_777_000_000_456)).toMatchObject({
      timestamp: 1_777_000_000_123,
      heart_rate: 87,
      status: "running",
      received_at: 1_777_000_000_456,
      __live: true,
      payload: { cadence_rpm: 82 },
    });
    expect(createLiveHeartRateSample({
      timestamp: 1_777_000_000_123,
      heart_rate: 999,
      status: "running",
    })).toBeNull();
  });

  it("replaces an optimistic SSE sample with the exact archived record", () => {
    const timestamp = 1_777_000_000_123;
    const live = createLiveHeartRateSample({
      timestamp,
      heart_rate: 92,
      status: "running",
    }, timestamp + 800);
    const archived = {
      id: 41,
      timestamp,
      heart_rate: 92,
      status: "running",
      received_at: timestamp + 600,
      payload: { raw: "preserved by backend" },
    };

    expect(mergeArchivedHeartRateSamples([live], [archived])).toEqual([archived]);
  });

  it("keeps separate archived transmissions even when their HR timestamps match", () => {
    const first = {
      id: 41,
      timestamp: 1_777_000_000_123,
      heart_rate: 92,
      status: "running",
      received_at: 1_777_000_000_600,
      payload: {},
    };
    const second = { ...first, id: 42, received_at: 1_777_000_001_600 };

    expect(mergeArchivedHeartRateSamples([], [first, second])).toHaveLength(2);
  });

  it("merges a full high-frequency day without quadratic archive scans", () => {
    const start = 1_777_000_000_000;
    const archived = Array.from({ length: 30_000 }, (_value, index) => ({
      id: index + 1,
      timestamp: start + index * 1000,
      received_at: start + index * 1000 + 100,
      heart_rate: 60 + (index % 70),
      status: "ready",
      payload: {},
      source: "smartwatch",
    }));

    const merged = mergeArchivedHeartRateSamples([], archived);

    expect(merged).toHaveLength(archived.length);
    expect(merged[0].id).toBe(archived.length);
    expect(merged.at(-1).id).toBe(1);
  }, 1000);

  it("always prefers smartwatch data over COLMI samples from the same minute", () => {
    const minute = 1_777_000_020_000;
    const ring = {
      id: "ring-1",
      timestamp: minute + 5_000,
      heart_rate: 71,
      source: "smart_ring",
    };
    const watch = {
      id: 42,
      timestamp: minute + 48_000,
      heart_rate: 74,
      source: "smartwatch",
    };

    expect(applySmartwatchPriority([ring, watch])).toEqual([watch]);
  });

  it("finds the starts and ends of ring-only collection phases", () => {
    const start = 1_777_000_000_000;
    const ring = (minutes) => ({
      timestamp: start + minutes * 60_000,
      heart_rate: 70,
      source: "smart_ring",
    });

    expect(buildSmartRingOnlyPhases([
      ring(0),
      ring(1),
      { timestamp: start + 2 * 60_000, heart_rate: 73, source: "smartwatch" },
      ring(3),
      ring(4),
    ])).toEqual([
      { start, end: start + 60_000, sampleCount: 2 },
      { start: start + 3 * 60_000, end: start + 4 * 60_000, sampleCount: 2 },
    ]);
  });

  it("removes a confirmed exact flatline but keeps short or naturally changing HR", () => {
    const start = 1_777_000_000_000;
    const flatline = Array.from({ length: 361 }, (_value, index) => ({
      timestamp: start + index * 1000,
      heart_rate: 78,
    }));
    const natural = Array.from({ length: 361 }, (_value, index) => ({
      timestamp: start + 10 * 60 * 1000 + index * 1000,
      heart_rate: 76 + (index % 5),
    }));
    const shortStable = Array.from({ length: 30 }, (_value, index) => ({
      timestamp: start + 20 * 60 * 1000 + index * 1000,
      heart_rate: 82,
    }));

    const filtered = filterUnwornHeartRateSamples([...natural, ...flatline, ...shortStable]);

    expect(filtered).toHaveLength(natural.length + shortStable.length);
    expect(filtered.some((sample) => sample.timestamp === flatline[0].timestamp)).toBe(false);
  });

  it("treats short transmission gaps and tiny sensor jitter as one unworn stream", () => {
    const start = 1_777_000_000_000;
    const sparseFlatline = Array.from({ length: 91 }, (_value, index) => ({
      timestamp: start + index * 10_000,
      heart_rate: index === 45 ? 79 : 78,
    }));
    const human = Array.from({ length: 600 }, (_value, index) => ({
      timestamp: start + 20 * 60 * 1000 + index * 1000,
      heart_rate: 68 + ((index * 7) % 19),
    }));

    const filtered = filterUnwornHeartRateSamples([...sparseFlatline, ...human]);

    expect(filtered).toEqual(human);
  });

  it("downsamples the chart while preserving endpoints and bucket extremes", () => {
    const points = Array.from({ length: 1000 }, (_value, index) => ({
      timestamp: index,
      bpm: index === 501 ? 190 : 80 + (index % 3),
    }));

    const sampled = downsampleHeartRatePoints(points, 100);

    expect(sampled.length).toBeLessThanOrEqual(100);
    expect(sampled[0]).toBe(points[0]);
    expect(sampled.at(-1)).toBe(points.at(-1));
    expect(sampled.some((point) => point.bpm === 190)).toBe(true);
  });

  it("keeps sparse COLMI points while downsampling dense smartwatch data", () => {
    const start = 1_777_000_000_000;
    const smartwatch = Array.from({ length: 30_000 }, (_value, index) => ({
      timestamp: start + index * 1000,
      bpm: 70 + (index % 40),
      source: "smartwatch",
    }));
    const ring = Array.from({ length: 100 }, (_value, index) => ({
      timestamp: start + index * 5 * 60_000,
      bpm: 60 + (index % 20),
      source: "smart_ring",
    }));

    const sampled = downsampleHeartRatePoints(
      [...smartwatch, ...ring].sort((left, right) => left.timestamp - right.timestamp),
      2400,
    );

    expect(sampled.length).toBeLessThanOrEqual(2400);
    expect(sampled.filter((point) => point.source === "smart_ring")).toEqual(ring);
  });
});
