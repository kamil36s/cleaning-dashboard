import { describe, expect, it } from "vitest";

import {
  audioRangeForItem,
  confidenceState,
  correctionReviewItems,
  correctedTranscript,
  exportCorrection,
  isTextEditingTarget,
  normalizeCorrectionData,
  restoreAllCorrections,
  updateCorrectionItem,
} from "../js/voice-journal-corrections.js";

const entry = {
  engine: "faster-whisper",
  transcript: "Ala ma kota",
  rawTranscript: "Ala ma kota",
  transcriptionData: {
    engine: "faster-whisper",
    segments: [{
      id: "s1", start: 2, end: 5, text: "Ala ma kota", originalText: "Ala ma kota",
      words: [
        { id: "w1", text: "Ala", start: 2, end: 2.5, probability: 0.8 },
        { id: "w2", text: "ma", start: 2.6, end: 3, probability: 0.6 },
        { id: "w3", text: "kota", start: null, end: null, probability: null },
      ],
    }],
  },
};

describe("voice journal corrections", () => {
  it("opens legacy segments without word timestamps", () => {
    const data = normalizeCorrectionData({ transcriptSegments: [{ start: 0, end: 1, text: "Stary wpis" }] });
    expect(data.segments[0].words).toEqual([]);
    expect(data.segments[0].correctedText).toBe("Stary wpis");
  });

  it("marks low confidence and keeps unavailable confidence neutral", () => {
    expect(confidenceState(0.4)).toBe("danger");
    expect(confidenceState(0.6)).toBe("warning");
    expect(confidenceState(null)).toBe("unknown");
  });

  it("uses word timestamps with one second of audio context and segment fallback", () => {
    expect(audioRangeForItem({ start: 2, end: 2.5 }, { start: 1, end: 5 })).toEqual({ start: 1, end: 3.5 });
    expect(audioRangeForItem({ start: null, end: null }, { start: 4, end: 7 })).toEqual({ start: 3, end: 8 });
  });

  it("edits without changing source text and records before/after history", () => {
    const data = normalizeCorrectionData(entry);
    const result = updateCorrectionItem(data, "w2", "correct", "miała", "2026-01-01T00:00:00Z");
    const word = result.data.segments[0].words[1];
    expect(word.originalText).toBe("ma");
    expect(word.correctedText).toBe("miała");
    expect(word.probability).toBe(0.6);
    expect(result.historyItem).toMatchObject({ previousValue: "ma", newValue: "miała", targetId: "w2" });
  });

  it("restores originals and filters review items", () => {
    let data = normalizeCorrectionData(entry);
    data = updateCorrectionItem(data, "w2", "unintelligible", "[niezrozumiałe]").data;
    expect(correctionReviewItems(data, {}, "unintelligible")).toHaveLength(1);
    const restored = restoreAllCorrections(data).data;
    expect(restored.segments[0].words[1].correctedText).toBe("ma");
    expect(restored.segments[0].words[1].correctionStatus).toBe("original");
  });

  it("exports corrected TXT, JSON, SRT and VTT", () => {
    const data = updateCorrectionItem(normalizeCorrectionData(entry), "s1", "correct", "Ala miała kota").data;
    expect(correctedTranscript(data)).toBe("Ala miała kota");
    expect(exportCorrection(data, [], "txt", "corrected")).toBe("Ala miała kota");
    expect(JSON.parse(exportCorrection(data, [], "json", "corrected")).segments[0].originalText).toBe("Ala ma kota");
    expect(exportCorrection(data, [], "srt", "corrected")).toContain("00:00:02,000 --> 00:00:05,000");
    expect(exportCorrection(data, [], "vtt", "corrected")).toMatch(/^WEBVTT/);
  });

  it("recognizes text-editing targets so shortcuts do not intercept typing", () => {
    document.body.innerHTML = `<textarea></textarea><button></button>`;
    expect(isTextEditingTarget(document.querySelector("textarea"))).toBe(true);
    expect(isTextEditingTarget(document.querySelector("button"))).toBe(false);
  });
});
