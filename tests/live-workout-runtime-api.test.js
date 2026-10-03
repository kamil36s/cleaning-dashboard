import { afterEach, describe, expect, it } from "vitest";
import {
  RUNTIME_OVERRIDE_KEY,
  liveWorkoutRuntimeBase,
  liveWorkoutRuntimeUrl,
} from "../js/live-workout-runtime-api.js";

describe("Live Workout runtime API boundary", () => {
  afterEach(() => localStorage.removeItem(RUNTIME_OVERRIDE_KEY));

  it("uses the dashboard host but the independent runtime port", () => {
    expect(liveWorkoutRuntimeBase({ hostname: "192.168.1.44" })).toBe("http://192.168.1.44:8766");
    expect(liveWorkoutRuntimeUrl("session", { hostname: "192.168.1.44" }))
      .toBe("http://192.168.1.44:8766/api/live-workout/session");
  });

  it("supports an explicit local override", () => {
    localStorage.setItem(RUNTIME_OVERRIDE_KEY, "http://training-box:9001/");
    expect(liveWorkoutRuntimeUrl("stream")).toBe("http://training-box:9001/api/live-workout/stream");
  });
});
