import { describe, expect, it } from "vitest";
import { deriveCyclingSpeedKmh, virtualWalkDistanceKm } from "../js/live-workout-distance.js";

describe("cycling distance fallback", () => {
  it("uses heart rate when CSC speed and cadence are missing", () => {
    expect(deriveCyclingSpeedKmh({
      measuredSpeedKmh: null,
      cadenceRpm: null,
      heartRate: 135,
      maxHeartRate: 180,
    })).toMatchObject({ source: "heart_rate_virtual_distance_v1" });
  });

  it("respects an explicit fresh zero cadence", () => {
    expect(deriveCyclingSpeedKmh({
      cadenceRpm: 0,
      heartRate: 135,
      maxHeartRate: 180,
    })).toMatchObject({ speedKmh: 0, source: "cadence_virtual_distance_v1" });
  });
});

describe("Santiago distance for virtual walks", () => {
  it("uses only credited steps at 0.75 metres per step", () => {
    expect(virtualWalkDistanceKm(1575)).toBeCloseTo(1.18125);
    expect(virtualWalkDistanceKm(0)).toBe(0);
  });
});
