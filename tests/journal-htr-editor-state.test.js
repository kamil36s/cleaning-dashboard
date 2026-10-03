import { describe, expect, it } from "vitest";
import { shouldRenderCorrectionAfterRefresh } from "../js/journal-htr-editor-state.js";

describe("Journal HTR correction draft", () => {
  it("does not rerender an editor containing an unsaved transcription", () => {
    expect(shouldRenderCorrectionAfterRefresh({
      unsavedLine: true,
      trainingInProgress: true,
    })).toBe(false);
  });

  it("allows server refresh after the correction has been saved", () => {
    expect(shouldRenderCorrectionAfterRefresh({
      unsavedLine: false,
      trainingInProgress: true,
    })).toBe(true);
  });
});
