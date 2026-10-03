import { describe, expect, it, vi } from "vitest";
import { CscBluetoothSensor } from "../js/live-workout-csc.js";
import {
  createExclusiveActionGate,
  enterElementFullscreen,
  isWorkoutSessionActive,
  pinWorkoutHudOpen,
  toggleElementFullscreen,
} from "../js/live-workout-controls.js";

describe("Live Workout independent controls", () => {
  it("can enter and exit fullscreen after a sensor connection failure", async () => {
    const sensorError = new Error("radio unavailable");
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => { throw sensorError; }) },
    });
    await expect(sensor.connect()).rejects.toBe(sensorError);
    expect(sensor.snapshot().status).toBe("disconnected");

    const element = {
      requestFullscreen: vi.fn(async () => { documentRef.fullscreenElement = element; }),
    };
    const documentRef = {
      fullscreenElement: null,
      exitFullscreen: vi.fn(async () => { documentRef.fullscreenElement = null; }),
    };

    await expect(toggleElementFullscreen(documentRef, element)).resolves.toBe(true);
    expect(element.requestFullscreen).toHaveBeenCalledWith({ navigationUI: "hide" });
    await expect(toggleElementFullscreen(documentRef, element)).resolves.toBe(false);
    expect(documentRef.exitFullscreen).toHaveBeenCalledOnce();
  });

  it("reports fullscreen capability errors without changing sensor state", async () => {
    const sensor = new CscBluetoothSensor({ bluetooth: {} });
    await expect(toggleElementFullscreen({ fullscreenElement: null }, {})).rejects.toThrow("pełnego ekranu");
    expect(sensor.snapshot().status).toBe("disconnected");
  });

  it("pins the HUD open for the whole running and paused session", () => {
    const classes = new Set();
    const body = { classList: { add: (name) => classes.add(name) } };
    const overlay = { hidden: true };

    expect(pinWorkoutHudOpen("running", overlay, body)).toBe(true);
    expect(overlay.hidden).toBe(false);
    expect(classes.has("live-workout-focus-open")).toBe(true);

    overlay.hidden = true;
    expect(pinWorkoutHudOpen("paused", overlay, body)).toBe(true);
    expect(overlay.hidden).toBe(false);
    expect(isWorkoutSessionActive("finished")).toBe(false);
  });

  it("enters real fullscreen on START without toggling it off", async () => {
    const element = {
      requestFullscreen: vi.fn(async () => { documentRef.fullscreenElement = element; }),
    };
    const documentRef = { fullscreenElement: null };

    await expect(enterElementFullscreen(documentRef, element)).resolves.toBe(true);
    await expect(enterElementFullscreen(documentRef, element)).resolves.toBe(true);
    expect(element.requestFullscreen).toHaveBeenCalledOnce();
  });

  it("serializes start, pause, finish and cancel controls into one action", async () => {
    let finishFirst;
    const firstAction = vi.fn(() => new Promise((resolve) => { finishFirst = resolve; }));
    const conflictingAction = vi.fn(async () => "cancelled");
    const busyStates = [];
    const gate = createExclusiveActionGate((busy) => busyStates.push(busy));

    const first = gate.run(firstAction);
    const conflicting = gate.run(conflictingAction);
    expect(gate.busy).toBe(true);
    expect(conflictingAction).not.toHaveBeenCalled();
    await Promise.resolve();
    finishFirst("finished");

    await expect(first).resolves.toBe("finished");
    await expect(conflicting).resolves.toBe("finished");
    expect(gate.busy).toBe(false);
    expect(busyStates).toEqual([true, false]);
  });

  it("unlocks all session actions after a failed request", async () => {
    const gate = createExclusiveActionGate();
    await expect(gate.run(async () => { throw new Error("offline"); })).rejects.toThrow("offline");
    expect(gate.busy).toBe(false);
    await expect(gate.run(async () => "retry-ok")).resolves.toBe("retry-ok");
  });
});
