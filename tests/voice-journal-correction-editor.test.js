import { afterEach, describe, expect, it, vi } from "vitest";

import { createVoiceJournalCorrectionEditor } from "../js/voice-journal-correction-editor.js";

const entryWithWords = () => ({
  id: "entry-1",
  audioUrl: "/api/voice-journal/entries/entry-1/audio",
  transcript: "To test",
  transcriptionData: {
    engine: "openai-whisper",
    segments: [{
      id: "segment-1",
      start: 2,
      end: 4,
      text: "To test",
      words: [
        { id: "word-1", word: "To", start: 2, end: 2.4, probability: 0.82 },
        { id: "word-2", word: "test", start: 2.5, end: 3, probability: 0.31 },
      ],
    }],
  },
});

function mountEditor(entry, options = {}) {
  const editor = createVoiceJournalCorrectionEditor(entry, options);
  document.body.append(editor);
  editor.open = true;
  editor.dispatchEvent(new Event("toggle"));
  return editor;
}

describe("voice journal correction editor", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("colors words by confidence and saves a clicked word with tick", async () => {
    const entry = entryWithWords();
    const updateEntry = vi.fn(async (_id, patch) => ({ ...entry, ...patch }));
    const onTranscriptChange = vi.fn();
    const editor = mountEditor(entry, { updateEntry, onTranscriptChange });
    const audio = editor.querySelector("audio");
    vi.spyOn(audio, "play").mockResolvedValue();

    const lowConfidenceWord = editor.querySelector('[data-correction-id="word-2"]');
    expect(lowConfidenceWord.classList.contains("is-danger")).toBe(true);
    expect(lowConfidenceWord.querySelector("small").textContent).toBe("31%");

    lowConfidenceWord.click();
    const inlineEditor = editor.querySelector(".voice-journal-inline-editor");
    expect(inlineEditor.hidden).toBe(false);
    expect(inlineEditor.textContent).toContain("Confidence: 31%");
    const input = inlineEditor.querySelector("input");
    input.value = "próba";
    inlineEditor.querySelector(".voice-journal-inline-editor-save").click();

    await vi.waitFor(() => expect(updateEntry).toHaveBeenCalledOnce());
    const patch = updateEntry.mock.calls[0][1];
    const savedWord = patch.transcriptionData.segments[0].words[1];
    expect(savedWord.originalText).toBe("test");
    expect(savedWord.correctedText).toBe("próba");
    expect(savedWord.probability).toBe(0.31);
    expect(patch.transcript).toBe("To próba");
    expect(onTranscriptChange).toHaveBeenCalledWith(expect.objectContaining({
      transcript: "To próba",
      transcriptionData: patch.transcriptionData,
    }));
  });

  it("edits legacy segments and can request genuine word confidence", async () => {
    const legacyEntry = {
      id: "legacy-1",
      audioUrl: "/audio/legacy-1",
      transcriptSegments: [{ id: "segment-1", start: 0, end: 2, text: "Stary tekst" }],
    };
    const updateEntry = vi.fn(async (_id, patch) => ({ ...legacyEntry, ...patch }));
    const retranscribeEntry = vi.fn(async () => ({
      ...legacyEntry,
      transcriptionData: entryWithWords().transcriptionData,
    }));
    const editor = mountEditor(legacyEntry, { updateEntry, retranscribeEntry });

    expect(editor.querySelector(".voice-journal-confidence-callout").hidden).toBe(false);
    editor.querySelector(".voice-journal-segment-edit-trigger").click();
    expect(editor.querySelector(".voice-journal-inline-editor input").value).toBe("Stary tekst");

    editor.querySelector(".voice-journal-confidence-callout button").click();
    await vi.waitFor(() => expect(retranscribeEntry).toHaveBeenCalledWith(legacyEntry, expect.any(Function)));
    await vi.waitFor(() => expect(editor.querySelectorAll(".voice-journal-word")).toHaveLength(2));
    expect(editor.querySelector(".voice-journal-confidence-callout").hidden).toBe(true);
  });
});
