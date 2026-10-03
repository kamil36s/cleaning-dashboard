import { describe, expect, it, vi } from "vitest";
import {
  LIVE_WORKOUT_LEARNING_STORAGE_KEY,
  LiveWorkoutLearningEngine,
  learningSamplesAsCalibration,
  loadLiveWorkoutLearningSamples,
  saveLiveWorkoutLearningSample,
} from "../js/live-workout-adaptive-calibration.js";
import { buildCalibrationModel, recommendRpmForLevel } from "../js/live-workout-calibration.js";

function feedThreeMinutes(engine, { level = 8, rpm = 80, heartRate = 130, sessionId = "session-1" } = {}) {
  let accepted = null;
  for (let second = 0; second <= 180; second += 1) {
    accepted = engine.ingest({
      timestamp: second * 1000,
      sessionId,
      sessionElapsedSeconds: 600 + second,
      level,
      rpm: typeof rpm === "function" ? rpm(second) : rpm,
      heartRate: typeof heartRate === "function" ? heartRate(second) : heartRate,
      active: true,
      signalFresh: true,
    }) || accepted;
  }
  return accepted;
}

describe("LiveWorkoutLearningEngine", () => {
  it("accepts a stable three-minute HR/RPM window", () => {
    const onSample = vi.fn();
    const engine = new LiveWorkoutLearningEngine({ minimumSessionSeconds: 0, onSample });
    const sample = feedThreeMinutes(engine);

    expect(sample).toMatchObject({ level: 8, averageRpm: 80, averageHr: 130, context: "steady", sessionPhase: "early", source: "live-training-context-v2" });
    expect(sample.durationSeconds).toBeGreaterThanOrEqual(117);
    expect(onSample).toHaveBeenCalledOnce();
    expect(engine.points.length).toBeGreaterThan(170);
  });

  it("ignores brief stops and spikes, but rejects a genuinely chaotic cadence", () => {
    const tolerantEngine = new LiveWorkoutLearningEngine({ minimumSessionSeconds: 0 });
    const tolerant = feedThreeMinutes(tolerantEngine, {
      rpm: (second) => second % 37 === 0 ? 0 : second % 41 === 0 ? 125 : 80 + (second % 5) - 2,
    });
    expect(tolerant).toMatchObject({ context: "steady" });
    expect(tolerant.averageRpm).toBeCloseTo(80, 0);
    expect(tolerant.transientFraction).toBeGreaterThan(0);

    const engine = new LiveWorkoutLearningEngine({ minimumSessionSeconds: 0 });
    const unstable = feedThreeMinutes(engine, { rpm: (second) => second % 2 ? 60 : 100 });
    expect(unstable).toBeNull();
  });

  it("classifies rising HR with a lower model weight and resets after a resistance change", () => {
    const engine = new LiveWorkoutLearningEngine({ minimumSessionSeconds: 0 });
    const rising = feedThreeMinutes(engine, { heartRate: (second) => 100 + second * 0.1 });
    expect(rising).toMatchObject({ context: "rising" });
    expect(rising.weight).toBeLessThan(0.2);

    engine.resetWindow();
    for (let second = 0; second < 100; second += 1) {
      engine.ingest({ timestamp: 500_000 + second * 1000, sessionElapsedSeconds: 700, level: 8, rpm: 80, heartRate: 130 });
    }
    expect(engine.points.length).toBeGreaterThan(90);
    engine.setLevel(7);
    expect(engine.points).toHaveLength(0);
  });
});

describe("adaptive calibration persistence and model", () => {
  it("persists a sample and adds it to a fixed-level RPM recommendation", () => {
    const values = new Map();
    const storage = {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    };
    const sample = feedThreeMinutes(new LiveWorkoutLearningEngine({ minimumSessionSeconds: 0 }));
    saveLiveWorkoutLearningSample(sample, storage);
    expect(values.has(LIVE_WORKOUT_LEARNING_STORAGE_KEY)).toBe(true);
    expect(loadLiveWorkoutLearningSamples(storage)).toHaveLength(1);
    saveLiveWorkoutLearningSample({ ...sample, id: "second-window", timestamp: sample.timestamp + 180_000, averageHr: 132 }, storage);
    expect(loadLiveWorkoutLearningSamples(storage)).toMatchObject([{ observationCount: 2, averageHr: 131 }]);

    const calibration = {
      id: "initial",
      dataPoints: [{ level: 8, averageRpm: 80, averageHr: 130 }],
    };
    const model = buildCalibrationModel([calibration, learningSamplesAsCalibration(loadLiveWorkoutLearningSamples(storage))]);
    expect(model).toMatchObject({ calibrationCount: 1, adaptivePointCount: 1 });
    expect(model.curve[0]).toMatchObject({ level: 8, calibrationSampleCount: 1, adaptiveSampleCount: 1 });
    const recommendation = recommendRpmForLevel(model, 125, 8);
    expect(recommendation).toMatchObject({ level: 8, targetHr: 125 });
    expect(recommendRpmForLevel(model, 125, 7)).toBeNull();
  });
});
