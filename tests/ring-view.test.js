import { describe, expect, it } from "vitest";
import {
  batteryPresentation, capabilityLabel, connectionPresentation, consolidateSleepNights, formatDuration, normalizeActivityRecords,
  heartRateZone, normalizeRingCalories, sanitizeHeartRateRecords,
} from "../js/ring-view.js";

describe("COLMI Ring view model", () => {
  it("renders an honest first-run state without mock values", () => {
    const result = connectionPresentation({
      collector: { status: "disconnected", bleDependencyAvailable: true },
      device: null,
    });
    expect(result.kind).toBe("empty");
    expect(result.title).toContain("Brak połączonego");
    expect(result.action).toBe("Skanuj ring");
    expect(result.copy).not.toMatch(/\d+%/);
  });

  it("keeps experimental and planned capabilities distinct", () => {
    expect(capabilityLabel("experimental")).toBe("eksperymentalne");
    expect(capabilityLabel("planned")).toBe("zaplanowane");
  });

  it("formats sleep duration without inventing a value", () => {
    expect(formatDuration(437)).toBe("7 h 17 min");
    expect(formatDuration(null)).toBe("—");
  });

  it("keeps the most complete snapshot when one ring night grows during sync", () => {
    const result = consolidateSleepNights([
      { sleepDate: "2026-09-03", sleepEndUtc: "2026-09-02T23:10:00Z", totalMinutes: 42 },
      { sleepDate: "2026-09-03", sleepEndUtc: "2026-09-03T06:04:00Z", totalMinutes: 456 },
      { sleepDate: "2026-09-02", sleepEndUtc: "2026-09-02T05:40:00Z", totalMinutes: 430 },
    ]);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ sleepDate: "2026-09-03", totalMinutes: 456 });
  });

  it("prefers a newer snapshot over a longer stale night copied after midnight", () => {
    const result = consolidateSleepNights([
      {
        sleepDate: "2026-09-04",
        sleepStartUtc: "2026-09-03T20:28:00Z",
        sleepEndUtc: "2026-09-04T04:29:00Z",
        totalMinutes: 481,
        createdAt: "2026-09-03T22:03:23Z",
      },
      {
        sleepDate: "2026-09-04",
        sleepStartUtc: "2026-09-03T20:06:00Z",
        sleepEndUtc: "2026-09-04T04:03:00Z",
        totalMinutes: 477,
        createdAt: "2026-09-04T06:17:05Z",
      },
    ]);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      sleepStartUtc: "2026-09-03T20:06:00Z",
      totalMinutes: 477,
    });
  });

  it("presents battery level, charging state and missing data for the sidebar", () => {
    expect(batteryPresentation({ batteryPercentage: 82 }, "connected")).toMatchObject({
      percentage: 82,
      value: "82%",
      label: "Bateria",
      level: "good",
    });
    expect(batteryPresentation({ batteryPercentage: 12 }, "disconnected")).toMatchObject({
      label: "Ostatni odczyt",
      level: "critical",
    });
    expect(batteryPresentation({ batteryPercentage: 51, charging: true }, "connected")).toMatchObject({
      value: "51% ⚡",
      label: "Ładowanie",
      level: "charging",
    });
    expect(batteryPresentation(null)).toMatchObject({ available: false, level: "unknown" });
  });

  it("keeps a realtime measurement presented as an active connection", () => {
    const result = connectionPresentation({
      collector: { status: "measuring", bleDependencyAvailable: true },
      device: { advertisedName: "COLMI R10", batteryPercentage: 81 },
    });
    expect(result.kind).toBe("connected");
    expect(result.action).toBeNull();
  });

  it("presents the Android bridge as the active BLE owner", () => {
    const result = connectionPresentation({
      collector: { status: "phone-bridge", bleDependencyAvailable: true },
      device: { advertisedName: "COLMI R10", batteryPercentage: 80 },
    });
    expect(result.kind).toBe("connected");
    expect(result.copy).toContain("Telefon");
    expect(result.action).toBeNull();
  });

  it("drops BLE error sentinels masquerading as heart rate", () => {
    const result = sanitizeHeartRateRecords([
      { timestampUtc: "2026-09-02T12:00:00Z", bpm: 72 },
      { timestampUtc: "2026-09-02T12:01:00Z", bpm: 238 },
    ]);
    expect(result.map((item) => item.bpm)).toEqual([72]);
  });

  it("normalizes legacy calorie scale and keeps one reading per activity slot", () => {
    expect(normalizeRingCalories(15510)).toBeCloseTo(15.51);
    expect(normalizeRingCalories(400)).toBeCloseTo(4);
    const result = normalizeActivityRecords([
      { timestampUtc: "2026-09-02T10:00:00Z", sourceSlot: 48, steps: 15, caloriesKcal: 400 },
      { timestampUtc: "2026-09-02T10:00:00Z", sourceSlot: 48, steps: 557, caloriesKcal: 15510 },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ steps: 557, caloriesKcal: 15.51 });
  });

  it("uses the requested daily HR zone palette at every boundary", () => {
    expect([59, 60, 85, 86, 100, 101, 120, 121].map((bpm) => heartRateZone(bpm).color)).toEqual([
      "#3b82f6", "#22c55e", "#22c55e", "#eab308", "#eab308", "#f97316", "#f97316", "#ef4444",
    ]);
  });
});
