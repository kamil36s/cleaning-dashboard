import { describe, expect, it, vi } from "vitest";
import {
  CALIBRATION_STORAGE_KEY,
  CalibrationEngine,
  buildCalibrationModel,
  buildCalibrationZoneMap,
  createCalibrationProtocol,
  getLiveCalibrationAdvice,
  getCalibrationResumePlan,
  loadCalibrations,
  recommendCalibrationSetting,
  saveCalibration,
} from "../js/live-workout-calibration.js";
import { AudioNotifier, CadenceMetronome } from "../js/live-workout-audio.js";
import {
  createCalibrationPanel,
  getCalibrationElements,
  renderCalibrationPanel,
} from "../js/live-workout-calibration-ui.js";

const readySignals = (heartRate = 100, cadenceRpm = 80) => ({
  hrAvailable: true,
  cadenceAvailable: true,
  heartRate,
  cadenceRpm,
});

describe("CalibrationEngine", () => {
  it("builds baseline, warmup, eight resistance steps, and cooldown", () => {
    const protocol = createCalibrationProtocol();
    expect(protocol).toHaveLength(11);
    expect(protocol.map((phase) => phase.kind)).toEqual([
      "baseline", "warmup", "step", "step", "step", "step", "step", "step", "step", "step", "cooldown",
    ]);
    expect(protocol.slice(2, 10).map((phase) => phase.level)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("counts baseline only while stationary and auto-pauses after signal loss", () => {
    const events = [];
    const engine = new CalibrationEngine({ baselineSeconds: 2, onEvent: (event) => events.push(event.type) });
    engine.start(readySignals(60, 20));
    engine.tick(1, readySignals(60, 20), 1000);
    expect(engine.snapshot()).toMatchObject({ phaseElapsed: 0, blockedReason: "stop-pedaling" });

    engine.tick(1, readySignals(60, 0), 2000);
    expect(engine.snapshot().phaseElapsed).toBe(1);
    engine.tick(1, { ...readySignals(60, 0), hrAvailable: false }, 3000);
    expect(engine.snapshot()).toMatchObject({ status: "paused", pauseReason: "signal" });
    expect(events).toContain("signal-lost");
  });

  it("calculates a stable steady-state point and can save a partial test", () => {
    const engine = new CalibrationEngine({ baselineSeconds: 1, warmupSeconds: 1, stepSeconds: 25 });
    let timestamp = 1000;
    engine.start(readySignals(60, 0));
    engine.tick(1, readySignals(60, 0), timestamp);
    timestamp += 1000;
    engine.tick(1, readySignals(90, 75), timestamp);

    for (let second = 0; second < 25; second += 1) {
      timestamp += 1000;
      engine.tick(1, readySignals(120, 80), timestamp);
    }

    const levelOne = engine.snapshot().results.find((result) => result.phaseId === "level-1");
    expect(levelOne).toMatchObject({ steadyHr: 120, steadyCadence: 80, steadyState: true });
    expect(levelOne.hrStdDev).toBe(0);

    const partial = engine.stopPartial();
    expect(partial.status).toBe("partial");
    expect(partial.dataPoints).toHaveLength(1);
    expect(partial.dataPoints[0]).toMatchObject({ level: 1, averageHr: 120 });
  });

  it("restarts an interrupted phase from zero when resumed", () => {
    const engine = new CalibrationEngine({ baselineSeconds: 1, warmupSeconds: 1, stepSeconds: 10 });
    engine.start(readySignals(60, 0));
    engine.tick(1, readySignals(60, 0), 1000);
    engine.tick(1, readySignals(90, 75), 2000);
    engine.tick(1, readySignals(120, 80), 3000);
    expect(engine.snapshot()).toMatchObject({ phase: { level: 1, kind: "step" }, phaseElapsed: 1 });

    engine.pause();
    engine.resume(readySignals(120, 80));
    expect(engine.snapshot()).toMatchObject({ status: "running", phaseElapsed: 0 });
    expect(engine.samples.some((sample) => sample.phaseId === "level-1")).toBe(false);
  });

  it("runs baseline and warmup again, then skips already completed saved levels", () => {
    const engine = new CalibrationEngine({
      baselineSeconds: 1,
      warmupSeconds: 1,
      resumeCompletedLevels: [1, 2, 3],
    });
    engine.start(readySignals(60, 0));
    engine.tick(1, readySignals(60, 0), 1000);
    expect(engine.snapshot().phase.kind).toBe("warmup");
    engine.tick(1, readySignals(90, 75), 2000);
    expect(engine.snapshot().phase).toMatchObject({ kind: "step", level: 4 });
    expect(engine.snapshot().phaseElapsed).toBe(0);
  });
});

describe("calibration persistence and model", () => {
  it("persists profiles and averages repeated level measurements", () => {
    const values = new Map();
    const storage = {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    };
    const first = { id: "one", timestamp: 1, dataPoints: [{ level: 1, averageHr: 100, averageRpm: 80 }, { level: 2, averageHr: 120, averageRpm: 80 }] };
    const second = { id: "two", timestamp: 2, dataPoints: [{ level: 1, averageHr: 104, averageRpm: 80 }, { level: 2, averageHr: 124, averageRpm: 80 }] };
    saveCalibration(first, storage);
    saveCalibration(second, storage);

    expect(values.has(CALIBRATION_STORAGE_KEY)).toBe(true);
    expect(loadCalibrations(storage)).toHaveLength(2);
    const model = buildCalibrationModel(loadCalibrations(storage));
    expect(model).toMatchObject({ calibrationCount: 2, pointCount: 4, referenceRpm: 80 });
    expect(model.curve.find((point) => point.level === 1).predictedHr).toBe(102);
  });

  it("maps HR zones and produces subtle live cadence corrections", () => {
    const model = buildCalibrationModel([{
      id: "one",
      dataPoints: [
        { level: 1, averageHr: 100, averageRpm: 80 },
        { level: 2, averageHr: 120, averageRpm: 80 },
        { level: 3, averageHr: 140, averageRpm: 80 },
      ],
    }]);
    const recommendation = recommendCalibrationSetting(model, 130);
    expect(recommendation.level).toBeGreaterThanOrEqual(1);
    expect(Math.abs(recommendation.predictedHr - 130)).toBeLessThan(2);

    const zones = buildCalibrationZoneMap(model, [{ id: "Z2", min: 114, max: 132 }]);
    expect(zones[0].recommendation).toBeTruthy();
    const advice = getLiveCalibrationAdvice({ model, targetHr: 130, currentHr: 120, currentCadence: 80, currentLevel: 2 });
    expect(advice.kind).toBe("faster");
    expect(advice.cadenceDelta).toBe(5);
  });

  it("does not use an unfinished step in the model and resumes at its beginning", () => {
    const partial = {
      id: "partial-one",
      status: "partial",
      config: { targetRpm: 80 },
      dataPoints: [
        { level: 1, averageHr: 105, averageRpm: 80, complete: true, partial: false },
        { level: 2, averageHr: 119, averageRpm: 80, complete: false, partial: true },
      ],
    };
    const plan = getCalibrationResumePlan([partial]);
    expect(plan).toMatchObject({ completedLevels: [1], nextLevel: 2 });
    expect(plan.dataPoints).toHaveLength(1);

    const model = buildCalibrationModel([partial]);
    expect(model.pointCount).toBe(1);
    expect(model.curve.map((point) => point.level)).toEqual([1]);
  });
});

describe("AudioNotifier", () => {
  it("uses Polish speech and throttles repeated cadence prompts", () => {
    const speak = vi.fn();
    const speechSynthesis = { speak, cancel: vi.fn(), getVoices: () => [] };
    class Utterance { constructor(text) { this.text = text; } }
    const notifier = new AudioNotifier({ speechSynthesis, Utterance });

    notifier.notifyCadence(70, 80, 4, 10_000);
    notifier.notifyCadence(70, 80, 4, 12_000);
    expect(speak).toHaveBeenCalledOnce();
    expect(speak.mock.calls[0][0]).toMatchObject({ text: "Zwiększ kadencję do 80 obrotów.", lang: "pl-PL" });
  });

  it("schedules 1:1 and 1:2 cadence rhythms at RPM-derived BPM", async () => {
    const oscillators = [];
    class FakeAudioContext {
      constructor() {
        this.currentTime = 0;
        this.state = "running";
        this.destination = {};
      }
      createOscillator() {
        const oscillator = {
          frequency: { setValueAtTime: vi.fn() },
          connect: vi.fn(),
          start: vi.fn(),
          stop: vi.fn(),
        };
        oscillators.push(oscillator);
        return oscillator;
      }
      createGain() {
        return {
          gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
          connect: vi.fn(),
        };
      }
    }
    const clearIntervalFn = vi.fn();
    const metronome = new CadenceMetronome({
      AudioContextClass: FakeAudioContext,
      setIntervalFn: vi.fn(() => 7),
      clearIntervalFn,
    });
    metronome.setRpm(80);
    await metronome.setEnabled(true);
    expect(metronome.bpm).toBe(160);
    expect(oscillators).toHaveLength(1);

    metronome.setMode("1:1");
    expect(metronome.bpm).toBe(80);
    metronome.context.currentTime = 0.8;
    metronome.schedule();
    expect(oscillators.length).toBeGreaterThan(1);

    await metronome.setEnabled(false);
    expect(clearIntervalFn).toHaveBeenCalledWith(7);
  });
});

describe("calibration panel", () => {
  it("renders diagnostics and the active resistance HUD inside Live Workout", () => {
    const panel = createCalibrationPanel(document);
    const elements = getCalibrationElements(panel);
    renderCalibrationPanel(elements, {
      snapshot: {
        status: "running",
        phase: { kind: "step", name: "Poziom 3", level: 3, durationSeconds: 180, targetRpm: 80, toleranceRpm: 4 },
        phaseNumber: 4,
        phaseCount: 10,
        phaseElapsed: 120,
        phaseRemaining: 60,
        totalRemaining: 900,
        pauseReason: null,
        signals: { hrAvailable: true, cadenceAvailable: true },
        results: [],
      },
      heartRate: 132,
      cadenceRpm: 81,
      hrReady: true,
      cadenceReady: true,
      model: null,
      calibrations: [],
      zones: [],
      advice: null,
    });

    expect(elements.hud.hidden).toBe(false);
    expect(elements.level.textContent).toBe("3");
    expect(elements.rpm.textContent).toBe("81");
    expect(elements.hr.textContent).toBe("132");
    expect(elements.rpmGuidance.textContent).toContain("76–84 RPM");
    expect(elements.curve.textContent).toContain("Poziom 8");
    expect(elements.curve.textContent).toContain("NIEZBADANY");
  });
});
