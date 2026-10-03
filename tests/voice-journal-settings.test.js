import { beforeEach, describe, expect, it } from "vitest";

import {
  VOICE_JOURNAL_SETTINGS_KEY,
  effectiveTranscriptionSettings,
  loadTranscriptionDefaults,
  parseTranscriptionSetting,
  presetTranscriptionSettings,
  saveTranscriptionDefaults,
  supportedTranscriptionSettings,
} from "../js/voice-journal-settings.js";

const CAPABILITIES = {
  supported: ["temperature", "beam_size", "initial_prompt", "word_timestamps", "fp16"],
  specs: {
    temperature: { type: "temperature", default: [0, 0.2], label: "Temperatura" },
    beam_size: { type: "integer", min: 1, max: 20, default: null, label: "Beam size" },
    initial_prompt: { type: "string", default: null, label: "Prompt" },
    word_timestamps: { type: "boolean", default: false, label: "Timestampy" },
    fp16: { type: "boolean", default: true, label: "FP16" },
  },
  presets: {
    balanced: { temperature: [0, 0.2], beam_size: null, initial_prompt: null, word_timestamps: false, fp16: true },
    quality: { temperature: 0, beam_size: 5, initial_prompt: null, word_timestamps: true, fp16: true },
  },
  recommendedPreset: "balanced",
};

describe("voice journal transcription settings", () => {
  beforeEach(() => localStorage.clear());

  it("uses only capabilities reported by the backend", () => {
    expect(supportedTranscriptionSettings(CAPABILITIES).map(([name]) => name)).toEqual([
      "temperature", "beam_size", "initial_prompt", "word_timestamps", "fp16",
    ]);
    expect(presetTranscriptionSettings(CAPABILITIES, "quality")).toEqual(expect.objectContaining({
      beam_size: 5,
      word_timestamps: true,
    }));
  });

  it("parses values and rejects invalid client-side ranges", () => {
    expect(parseTranscriptionSetting(CAPABILITIES.specs.temperature, "0, 0.2, 0.6")).toEqual([0, 0.2, 0.6]);
    expect(parseTranscriptionSetting(CAPABILITIES.specs.beam_size, "5")).toBe(5);
    expect(() => parseTranscriptionSetting(CAPABILITIES.specs.temperature, "1.5")).toThrow();
    expect(() => parseTranscriptionSetting(CAPABILITIES.specs.beam_size, "2.5")).toThrow();
  });

  it("saves filtered defaults and shows CPU fp16 as effectively disabled", () => {
    saveTranscriptionDefaults({
      preset: "custom",
      options: { temperature: 0, fp16: true, vad_filter: true },
    });
    expect(localStorage.getItem(VOICE_JOURNAL_SETTINGS_KEY)).toBeTruthy();
    const loaded = loadTranscriptionDefaults(CAPABILITIES);
    expect(loaded).toEqual({ preset: "custom", options: { temperature: 0, fp16: true } });

    expect(effectiveTranscriptionSettings(loaded.options, CAPABILITIES, {
      device: "cpu",
      cudaAvailable: false,
    })).toEqual(expect.objectContaining({ fp16: false, temperature: 0 }));
  });
});
