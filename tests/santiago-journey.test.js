import { describe, expect, it } from "vitest";
import { accumulateCyclingDistance, deriveCyclingSpeedKmh } from "../js/live-workout-distance.js";
import { createJourneyEngine } from "../js/santiago-journey.js";

const checkpoints = [
  { index: 1, name: "Kraków", routeDistanceKm: 0 },
  { index: 2, name: "A", routeDistanceKm: 50 },
  { index: 3, name: "B", routeDistanceKm: 120 },
  { index: 4, name: "C", routeDistanceKm: 190 },
  { index: 5, name: "Santiago de Compostela", routeDistanceKm: 200 },
];

const engine = createJourneyEngine({
  route: [[0, 0], [0, 1], [1, 1]],
  cumulativeKm: [0, 100, 200],
  checkpoints,
});

describe("Santiago journey engine", () => {
  it("adds committed and live distance", () => {
    expect(engine.getJourneyProgress(100, 5).distanceKm).toBe(105);
  });

  it("clamps start, endpoint, and overflow", () => {
    expect(engine.getPositionAtDistance(0)).toMatchObject({ distanceKm: 0, latitude: 0, longitude: 0 });
    expect(engine.getPositionAtDistance(200)).toMatchObject({ distanceKm: 200, latitude: 1, longitude: 1 });
    expect(engine.getPositionAtDistance(300)).toMatchObject({ distanceKm: 200, latitude: 1, longitude: 1 });
  });

  it("interpolates between route vertices", () => {
    expect(engine.getPositionAtDistance(50)).toMatchObject({ latitude: 0.5, longitude: 0 });
  });

  it("selects previous and next checkpoints", () => {
    expect(engine.getPreviousCheckpoint(105).name).toBe("A");
    expect(engine.getNextCheckpoint(105)).toMatchObject({ name: "B", distanceAwayKm: 15 });
  });

  it("detects no, one, and multiple crossings", () => {
    expect(engine.getCrossedCheckpoints(51, 119)).toEqual([]);
    expect(engine.getCrossedCheckpoints(100, 121).map((item) => item.name)).toEqual(["B"]);
    expect(engine.getCrossedCheckpoints(40, 195).map((item) => item.name)).toEqual(["A", "B", "C"]);
  });

  it("triggers variants at their association distance without presenting them as the next destination", () => {
    const variantEngine = createJourneyEngine({
      route: [[0, 0], [0, 1], [1, 1]],
      cumulativeKm: [0, 100, 200],
      checkpoints: [
        { id: "start", index: 1, originalIndex: 1, name: "Start", routeDistanceKm: 0 },
        { id: "rejoin", index: 2, originalIndex: 3, name: "Rejoin", routeDistanceKm: 100 },
        { id: "variant", index: 3, originalIndex: 2, name: "Variant", routeDistanceKm: 100, variantCheckpoint: true, associatedCheckpointId: "rejoin" },
        { id: "finish", index: 4, originalIndex: 4, name: "Finish", routeDistanceKm: 200 },
      ],
    });

    expect(variantEngine.getNextCheckpoint(99).name).toBe("Rejoin");
    expect(variantEngine.getNextCheckpoint(100).name).toBe("Finish");
    expect(variantEngine.getCrossedCheckpoints(99, 101).map((item) => item.name)).toEqual(["Rejoin", "Variant"]);
  });
});

describe("Live Workout distance source", () => {
  it("prefers measured speed and accumulates kilometers", () => {
    expect(deriveCyclingSpeedKmh({ measuredSpeedKmh: 24, cadenceRpm: 80 })).toEqual({ speedKmh: 24, source: "csc_speed" });
    expect(accumulateCyclingDistance(1, 30, { measuredSpeedKmh: 24 }).distanceKm).toBeCloseTo(1.033333, 5);
  });

  it("uses positive cadence instead of a conflicting zero speed field", () => {
    expect(deriveCyclingSpeedKmh({ measuredSpeedKmh: 0, cadenceRpm: 80 })).toEqual({
      speedKmh: 19.2,
      source: "cadence_virtual_distance_v1",
    });
    expect(deriveCyclingSpeedKmh({ measuredSpeedKmh: 0 })).toEqual({ speedKmh: 0, source: "csc_speed" });
  });

  it("uses the documented cadence model when speed is unavailable", () => {
    expect(deriveCyclingSpeedKmh({ cadenceRpm: 80 })).toEqual({ speedKmh: 19.2, source: "cadence_virtual_distance_v1" });
  });

  it("uses heart-rate intensity when neither CSC speed nor cadence is available", () => {
    expect(deriveCyclingSpeedKmh({ heartRate: 95, maxHeartRate: 190 })).toEqual({
      speedKmh: 8,
      source: "heart_rate_virtual_distance_v1",
    });
    expect(deriveCyclingSpeedKmh({ heartRate: 142.5, maxHeartRate: 190 })).toEqual({
      speedKmh: 19,
      source: "heart_rate_virtual_distance_v1",
    });
    expect(accumulateCyclingDistance(0, 5, { heartRate: 142.5, maxHeartRate: 190 }).distanceKm).toBeCloseTo(19 / 720, 6);
  });

  it("does not infer movement below Z1 and lets an explicit zero RPM override elevated BPM", () => {
    expect(deriveCyclingSpeedKmh({ heartRate: 90, maxHeartRate: 190 })).toEqual({
      speedKmh: 0,
      source: "heart_rate_virtual_distance_v1",
    });
    expect(deriveCyclingSpeedKmh({ cadenceRpm: 0, heartRate: 150, maxHeartRate: 190 })).toEqual({
      speedKmh: 0,
      source: "cadence_virtual_distance_v1",
    });
  });
});
