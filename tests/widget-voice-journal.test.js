import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  detectedFileDateTime,
  formatVoiceJournalEta,
  groupVoiceJournalSegments,
  initVoiceJournalWidget,
  organizeVoiceJournalTranscript,
  stripVoiceJournalTimestamps,
  VOICE_JOURNAL_ACCEPT,
} from "../js/widget-voice-journal.js";

const HEALTH = {
  status: "ok",
  whisperVersion: "20240930",
  supportedModels: ["small", "medium", "turbo"],
  cachedModels: ["turbo"],
  supportedLanguages: ["auto", "pl"],
  supportedTasks: ["transcribe", "translate"],
  supportedDevices: ["auto", "cpu"],
  recommendedModel: "small",
  maxUploadBytes: 250 * 1024 * 1024,
  maxDurationSeconds: 90 * 60,
  transcriptionOptions: {
    supported: ["temperature", "fp16", "word_timestamps"],
    specs: {
      temperature: { type: "temperature", default: [0, 0.2], label: "Temperatura", tooltip: "Losowość." },
      fp16: { type: "boolean", default: true, label: "FP16", tooltip: "Tylko CUDA." },
      word_timestamps: { type: "boolean", default: true, label: "Timestampy słów", tooltip: "Czasy i confidence słów." },
    },
    presets: {
      fast: { temperature: 0, fp16: true, word_timestamps: false },
      balanced: { temperature: [0, 0.2], fp16: true, word_timestamps: true },
      quality: { temperature: 0, fp16: true, word_timestamps: true },
    },
    recommendedPreset: "balanced",
  },
  errors: [],
};

function mountWidget() {
  document.body.innerHTML = `
    <section class="card voice-journal">
      <div id="voice-journal-backend-pill"></div>
      <div id="voice-journal-root"></div>
    </section>
  `;
  return document.getElementById("voice-journal-root");
}

function optionValues(select) {
  return Array.from(select.options).map((option) => option.value);
}

describe("voice journal widget", () => {
  const controllers = [];

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    controllers.splice(0).forEach((controller) => controller?.dispose());
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("formats ETA as approximate and handles missing history", () => {
    expect(formatVoiceJournalEta({
      available: true,
      approximate: true,
      minSeconds: 75,
      maxSeconds: 150,
    })).toBe("ETA: około 1 min–3 min");
    expect(formatVoiceJournalEta({
      available: false,
      reason: "insufficient_history",
    })).toBe("ETA: brak wystarczających danych");
  });

  it("builds an editable organized version without changing dirty segments", () => {
    const segments = [
      { start: 0, end: 2, text: "Pierwsza myśl." },
      { start: 4, end: 6, text: "Druga myśl." },
    ];

    expect(organizeVoiceJournalTranscript(segments)).toBe("Pierwsza myśl.\n\nDruga myśl.");
    expect(segments[0].text).toBe("Pierwsza myśl.");
    expect(stripVoiceJournalTimestamps("[00:00] Pierwsza myśl.\n\n[01:02] Druga myśl."))
      .toBe("Pierwsza myśl.\n\nDruga myśl.");
  });

  it("groups word-sized Whisper segments into timestamped phrases", () => {
    const grouped = groupVoiceJournalSegments([
      { start: 18 * 60 + 31, end: 18 * 60 + 32, text: "związane z tym" },
      { start: 18 * 60 + 32, end: 18 * 60 + 33, text: "tu" },
      { start: 18 * 60 + 33, end: 18 * 60 + 34, text: "nie" },
      { start: 18 * 60 + 42, end: 18 * 60 + 43, text: "chcę" },
      { start: 18 * 60 + 44, end: 18 * 60 + 45, text: "to" },
      { start: 18 * 60 + 45, end: 18 * 60 + 46, text: "nie" },
      { start: 19 * 60 + 2, end: 19 * 60 + 3, text: "Nie wiem." },
    ]);

    expect(grouped.map((segment) => segment.text)).toEqual([
      "związane z tym tu nie",
      "chcę to nie",
      "Nie wiem.",
    ]);
    expect(grouped.map((segment) => segment.start)).toEqual([1111, 1122, 1142]);
  });

  it("shows only capabilities reported by the health endpoint", async () => {
    const root = mountWidget();
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([]),
      metadataReader: vi.fn().mockResolvedValue({ durationSeconds: 10 }),
    });
    controllers.push(controller);

    expect(optionValues(root.querySelector("#voice-journal-model"))).toEqual(["auto", "small", "medium", "turbo"]);
    expect(root.querySelector('#voice-journal-model option[value="small"]').textContent).toContain("wymaga pobrania");
    expect(optionValues(root.querySelector("#voice-journal-language"))).toEqual(["auto", "pl"]);
    expect(root.querySelector("#voice-journal-language").value).toBe("pl");
    expect(optionValues(root.querySelector("#voice-journal-task"))).toEqual(["transcribe", "translate"]);
    expect(optionValues(root.querySelector("#voice-journal-device"))).toEqual(["auto", "cpu"]);
    expect(root.querySelector("#voice-journal-device").textContent).not.toContain("CUDA");
    expect(document.getElementById("voice-journal-backend-pill").textContent).toBe("Backend OK");
    expect(root.querySelector("#voice-journal-health-text").textContent).toContain("Whisper 20240930");
    expect(root.querySelector("#voice-journal-health-text").textContent).toContain("250 MB i 90 min");
    expect(root.querySelector("#voice-journal-transcription-settings").hasAttribute("open")).toBe(false);
    expect(Array.from(root.querySelectorAll("[data-transcription-option]")).map((field) => field.dataset.transcriptionOption))
      .toEqual(["temperature", "fp16", "word_timestamps"]);
    expect(root.querySelector("#voice-journal-word-confidence-field").hidden).toBe(false);
    expect(root.querySelector("#voice-journal-word-confidence").checked).toBe(true);
    expect(root.querySelector("#voice-journal-settings-preview").textContent).toContain('"fp16": false');
    const temperature = root.querySelector('[data-transcription-option="temperature"]');
    temperature.value = "0.7";
    temperature.dispatchEvent(new Event("input", { bubbles: true }));
    root.querySelector("#voice-journal-settings-save").click();
    expect(localStorage.getItem("voiceJournalTranscriptionDefaultsV1")).toContain('"temperature":0.7');
    root.querySelector("#voice-journal-settings-restore").click();
    expect(temperature.value).toBe("0, 0.2");
  });

  it("shows selected file metadata and detected editable date", async () => {
    const root = mountWidget();
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([]),
      metadataReader: vi.fn().mockResolvedValue({ durationSeconds: 83 }),
    });
    controllers.push(controller);
    const file = new File([new Uint8Array(2048)], "notatka.m4a", {
      type: "audio/mp4",
      lastModified: new Date(2026, 6, 20, 7, 45).getTime(),
    });

    await controller.selectFile(file);

    expect(root.querySelector("#voice-journal-workspace").hidden).toBe(false);
    expect(root.querySelector("#voice-journal-file-name").textContent).toBe("notatka.m4a");
    expect(root.querySelector("#voice-journal-file-size").textContent).toContain("2");
    expect(root.querySelector("#voice-journal-file-format").textContent).toBe("M4A");
    expect(root.querySelector("#voice-journal-file-duration").textContent).toBe("1:23");
    expect(root.querySelector("#voice-journal-date").value).toBe("2026-07-20");
    expect(root.querySelector("#voice-journal-time").value).toBe("07:45");
    expect(detectedFileDateTime(file).date).toBe("2026-07-20");
    expect(root.querySelector("#voice-journal-transcribe").disabled).toBe(false);
  });

  it("accepts AAC files in the picker and drag-and-drop validation", async () => {
    const root = mountWidget();
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([]),
      metadataReader: vi.fn().mockResolvedValue({ durationSeconds: 12 }),
    });
    controllers.push(controller);
    const file = new File([new Uint8Array(128)], "notatka.aac", { type: "audio/aac" });

    await controller.selectFile(file);

    expect(VOICE_JOURNAL_ACCEPT).toContain(".aac");
    expect(VOICE_JOURNAL_ACCEPT).toContain("audio/aac");
    expect(VOICE_JOURNAL_ACCEPT).toContain("audio/vnd.dlna.adts");
    expect(root.querySelector("#voice-journal-workspace").hidden).toBe(false);
    expect(root.querySelector("#voice-journal-file-format").textContent).toBe("AAC");
  });

  it("requires confirmation before queuing a model missing from cache", async () => {
    const root = mountWidget();
    const createJob = vi.fn();
    const confirmAction = vi.fn().mockReturnValue(false);
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([]),
      metadataReader: vi.fn().mockResolvedValue({ durationSeconds: 10 }),
      createJob,
      confirmAction,
    });
    controllers.push(controller);
    await controller.selectFile(new File(["audio"], "memo.webm", { type: "audio/webm" }));
    root.querySelector("#voice-journal-model").value = "small";

    root.querySelector("#voice-journal-transcribe").click();

    expect(confirmAction).toHaveBeenCalledOnce();
    expect(confirmAction.mock.calls[0][0]).toContain("dużego pliku");
    expect(createJob).not.toHaveBeenCalled();
    expect(root.querySelector("#voice-journal-health-text").textContent).toContain("anulowane");
  });

  it("transcribes and persists the entry with its original audio file", async () => {
    const root = mountWidget();
    const result = {
      transcript: "Treść nagrania.",
      transcriptSegments: [
        { start: 2.2, end: 4.5, text: "Treść" },
        { start: 4.5, end: 6.8, text: "nagrania." },
      ],
      durationSeconds: 12.4,
      format: "matroska,webm",
      codec: "opus",
      sampleRate: 48000,
      channels: 1,
      sizeBytes: 5,
      model: "turbo",
      device: "cpu",
      transcriptionDurationSeconds: 3.2,
      realTimeFactor: 0.258,
    };
    const createJob = vi.fn().mockResolvedValue({
      id: "c".repeat(32), status: "queued", stage: "queued", elapsedSeconds: 0,
      queuePosition: 1, model: "turbo", device: "cpu", progressPercent: null,
      processedAudioSeconds: null,
    });
    const getJob = vi.fn().mockResolvedValue({
      id: "c".repeat(32), status: "completed", stage: "completed", elapsedSeconds: 4,
      queuePosition: null, model: "turbo", device: "cpu", progressPercent: 100,
      processedAudioSeconds: 12.4,
    });
    const getJobResult = vi.fn().mockResolvedValue(result);
    let storedEntries = [];
    const fetchEntries = vi.fn(async () => storedEntries);
    const createEntry = vi.fn(async ({ file, entry }) => {
      storedEntries = [{
        id: "a".repeat(32),
        ...entry,
        originalFilename: file.name,
        durationSeconds: 12.4,
        audioUrl: `/api/voice-journal/entries/${"a".repeat(32)}/audio`,
      }];
      return storedEntries[0];
    });
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries,
      metadataReader: vi.fn().mockResolvedValue({ durationSeconds: 12.4 }),
      createJob,
      getJob,
      getJobResult,
      waitForPoll: vi.fn().mockResolvedValue(),
      createEntry,
    });
    controllers.push(controller);
    const file = new File(["audio"], "memo.webm", {
      type: "audio/webm",
      lastModified: new Date(2026, 6, 21, 18, 30).getTime(),
    });
    await controller.selectFile(file);
    expect(root.querySelector("#voice-journal-title-input").value).toBe("memo.webm");
    root.querySelector("#voice-journal-title-input").value = "Wieczorne podsumowanie";
    root.querySelector("#voice-journal-type").value = "evening";
    root.querySelector("#voice-journal-tags").value = "dzień, refleksje, dzień";

    root.querySelector("#voice-journal-transcribe").click();
    await vi.waitFor(() => expect(root.querySelector("#voice-journal-result").hidden).toBe(false));

    expect(createJob).toHaveBeenCalledWith(expect.objectContaining({
      file,
      model: "turbo",
      language: "pl",
      task: "transcribe",
      device: "auto",
      transcriptionOptions: { temperature: [0, 0.2], fp16: true, word_timestamps: true },
    }), expect.objectContaining({ onUploadProgress: expect.any(Function) }));
    expect(root.querySelector("#voice-journal-transcript").value).toBe("Treść nagrania.");
    expect(root.querySelector("#voice-journal-result-raw-transcript").textContent).toContain("[00:02]");
    expect(root.querySelector("#voice-journal-result-meta").textContent).toContain("Model: turbo");
    expect(root.querySelector("#voice-journal-result-meta").textContent).toContain("RTF: 0,258");
    expect(root.querySelectorAll("#voice-journal-progress .is-done")).toHaveLength(6);

    root.querySelector("#voice-journal-transcript").value = "Treść po korekcie.";
    root.querySelector("#voice-journal-save").click();
    await vi.waitFor(() => expect(createEntry).toHaveBeenCalledOnce());

    expect(createEntry).toHaveBeenCalledWith({
      file,
      entry: expect.objectContaining({
        title: "Wieczorne podsumowanie",
        entryCategory: "evening",
        dateSource: "file_modified",
        tags: ["dzień", "refleksje"],
        transcript: "Treść po korekcie.",
        rawTranscript: "Treść nagrania.",
        transcriptSegments: result.transcriptSegments,
        model: "turbo",
      }),
    });
    await vi.waitFor(() => expect(root.querySelectorAll(".voice-journal-entry")).toHaveLength(1));
    expect(root.querySelector(".voice-journal-entry-title").textContent).toBe("Wieczorne podsumowanie");
    expect(root.querySelector(".voice-journal-entry-content").hidden).toBe(true);
    expect(localStorage.length).toBe(0);
  });

  it("keeps transcription progress indeterminate and allows cancellation", async () => {
    const root = mountWidget();
    const id = "d".repeat(32);
    let releasePoll;
    const waitForPoll = vi.fn(() => new Promise((resolve) => { releasePoll = resolve; }));
    const getJob = vi.fn().mockResolvedValue({
      id, status: "cancelled", stage: "cancelled", elapsedSeconds: 2,
      queuePosition: null, model: "turbo", device: "cpu",
      processedAudioSeconds: null, progressPercent: null,
    });
    const cancelJob = vi.fn().mockResolvedValue({
      id, status: "cancelling", stage: "cancelling", elapsedSeconds: 1,
      queuePosition: 0, model: "turbo", device: "cpu",
      processedAudioSeconds: null, progressPercent: null,
    });
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([]),
      metadataReader: vi.fn().mockResolvedValue({ durationSeconds: 30 }),
      createJob: vi.fn().mockResolvedValue({
        id, status: "running", stage: "transcribing", elapsedSeconds: 1,
        queuePosition: 0, model: "turbo", device: "cpu",
        processedAudioSeconds: null, progressPercent: null,
      }),
      getJob,
      cancelJob,
      waitForPoll,
    });
    controllers.push(controller);
    await controller.selectFile(new File(["audio"], "memo.webm", { type: "audio/webm" }));

    root.querySelector("#voice-journal-transcribe").click();
    await vi.waitFor(() => expect(root.querySelector("#voice-journal-job-meta").textContent).toContain("turbo"));
    const bar = root.querySelector(".voice-journal-indeterminate");
    expect(root.querySelector("#voice-journal-progress").classList.contains("is-determinate")).toBe(false);
    expect(bar.hasAttribute("aria-valuenow")).toBe(false);

    root.querySelector("#voice-journal-cancel-job").click();
    await vi.waitFor(() => expect(cancelJob).toHaveBeenCalledWith(id));
    releasePoll();
    await vi.waitFor(() => expect(root.querySelector("#voice-journal-health-text").textContent).toContain("anulowana"));
    expect(getJob).toHaveBeenCalledWith(id);
  });

  it("renders stored entries and supports edit plus two-step deletion", async () => {
    const root = mountWidget();
    const id = "b".repeat(32);
    let storedEntries = [{
      id,
      title: "Wpis z bazy",
      entryCategory: "morning",
      recordedAt: "2026-07-21T06:30:00.000Z",
      originalFilename: "rano.wav",
      durationSeconds: 62,
      transcript: "Długi tekst ".repeat(30),
      rawTranscript: "Surowy tekst ".repeat(30),
      transcriptSegments: [
        { start: 2, end: 4, text: "Surowy tekst" },
        { start: 65, end: 68, text: "Dalsza kwestia" },
      ],
      tags: ["rano"],
      model: "turbo",
      device: "cpu",
      realTimeFactor: 1.2,
      audioUrl: `/api/voice-journal/entries/${id}/audio`,
    }];
    const fetchEntries = vi.fn(async () => storedEntries);
    const updateEntry = vi.fn(async (entryId, patch) => {
      storedEntries = storedEntries.map((entry) => entry.id === entryId ? { ...entry, ...patch } : entry);
      return storedEntries[0];
    });
    const publishEntry = vi.fn().mockResolvedValue({ id: "journal-entry", sourceType: "voice-journal" });
    const deleteEntry = vi.fn(async () => {
      storedEntries = [];
      return { deleted: true, audioDeleted: true };
    });
    const confirmAction = vi.fn()
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(true);
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries,
      updateEntry,
      publishEntry,
      deleteEntry,
      confirmAction,
    });
    controllers.push(controller);

    const card = root.querySelector(`.voice-journal-entry[data-entry-id="${id}"]`);
    expect(card.querySelector("audio").getAttribute("src")).toBe(`/api/voice-journal/entries/${id}/audio`);
    expect(card.querySelectorAll(".voice-journal-transcript-pane")).toHaveLength(2);
    expect(card.querySelector(".voice-journal-timestamp").textContent).toBe("[00:02]");
    const audio = card.querySelector("audio");
    vi.spyOn(audio, "play").mockResolvedValue();
    card.querySelector(".voice-journal-timestamp").click();
    audio.dispatchEvent(new Event("loadedmetadata"));
    expect(audio.currentTime).toBe(2);
    const organizedInput = card.querySelector(`#voice-journal-entry-transcript-${id}`);
    organizedInput.value = "Nowa transkrypcja";
    organizedInput.dispatchEvent(new Event("input", { bubbles: true }));
    const saveOrganized = Array.from(card.querySelectorAll("button"))
      .find((button) => button.textContent === "Zapisz wersję uporządkowaną");
    expect(saveOrganized.disabled).toBe(false);
    saveOrganized.click();
    await vi.waitFor(() => expect(updateEntry).toHaveBeenCalledWith(id, { transcript: "Nowa transkrypcja" }));
    expect(card.querySelector(".voice-journal-organized-status").textContent).toBe("Zapisano.");
    card.querySelector(".voice-journal-publish-action").click();
    await vi.waitFor(() => expect(publishEntry).toHaveBeenCalledWith(id));
    expect(card.querySelector(".voice-journal-organized-status").textContent).toContain("Opublikowano");
    expect(card.classList.contains("is-published")).toBe(true);
    expect(card.querySelector(".voice-journal-entry-published").hidden).toBe(false);
    expect(card.querySelector(".voice-journal-entry-content").hidden).toBe(true);
    card.querySelector(".voice-journal-entry-toggle").click();
    expect(card.querySelector(".voice-journal-entry-content").hidden).toBe(false);
    const expandButton = Array.from(card.querySelectorAll(".voice-journal-entry-actions .voice-journal-entry-action"))
      .find((button) => button.textContent === "Rozwiń tekst");
    expandButton.click();
    expect(card.querySelector(".voice-journal-entry-workbench").classList.contains("is-expanded")).toBe(true);
    expect(expandButton.getAttribute("aria-expanded")).toBe("true");

    Array.from(card.querySelectorAll(".voice-journal-entry-action"))
      .find((button) => button.textContent === "Edytuj").click();
    const editForm = card.querySelector(".voice-journal-entry-edit");
    editForm.querySelector('[name="title"]').value = "Tytuł po edycji";
    expect(editForm.querySelector('[name="transcript"]')).toBeNull();
    editForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(updateEntry).toHaveBeenCalledTimes(2));
    expect(updateEntry.mock.calls[1][1]).toEqual(expect.objectContaining({ title: "Tytuł po edycji" }));
    expect(updateEntry.mock.calls[1][1]).not.toHaveProperty("transcript");

    const refreshedCard = root.querySelector(`.voice-journal-entry[data-entry-id="${id}"]`);
    refreshedCard.querySelector(".is-danger").click();
    await vi.waitFor(() => expect(deleteEntry).toHaveBeenCalledWith(id, { deleteAudio: true }));
    expect(confirmAction).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(root.querySelectorAll(".voice-journal-entry")).toHaveLength(0));
  });

  it("marks published entries and keeps them collapsed until expanded", async () => {
    const root = mountWidget();
    const id = "d".repeat(32);
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([{
        id,
        title: "",
        entryCategory: "evening",
        recordedAt: "2026-07-20T20:00:00.000Z",
        originalFilename: "wieczor.wav",
        durationSeconds: 30,
        transcript: "Gotowy tekst",
        rawTranscript: "Gotowy tekst",
        tags: [],
        model: "turbo",
        device: "cpu",
        realTimeFactor: 1,
        audioUrl: `/api/voice-journal/entries/${id}/audio`,
        journalPublication: {
          id: "journal-entry",
          publishedAt: "2026-07-21T08:00:00.000Z",
        },
      }]),
    });
    controllers.push(controller);

    const card = root.querySelector(`.voice-journal-entry[data-entry-id="${id}"]`);
    const toggle = card.querySelector(".voice-journal-entry-toggle");
    expect(card.classList.contains("is-published")).toBe(true);
    expect(card.querySelector(".voice-journal-entry-title").textContent).toBe("wieczor.wav");
    expect(card.querySelector(".voice-journal-entry-published").textContent).toBe("W Dzienniku");
    expect(card.querySelector(".voice-journal-entry-content").hidden).toBe(true);
    expect(toggle.textContent).toBe("Rozwiń wpis");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    toggle.click();
    expect(card.querySelector(".voice-journal-entry-content").hidden).toBe(false);
    expect(toggle.textContent).toBe("Zwiń wpis");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("syncs saved corrections into dirty timestamps while keeping organized text clean", async () => {
    const root = mountWidget();
    const id = "e".repeat(32);
    const entry = {
      id,
      title: "Korekta",
      entryCategory: "spontaneous",
      recordedAt: "2026-07-21T08:00:00.000Z",
      originalFilename: "korekta.wav",
      durationSeconds: 12,
      transcript: "Stary tekst",
      rawTranscript: "Stary tekst",
      transcriptSegments: [{ id: "segment-1", start: 2, end: 4, text: "Stary tekst" }],
      tags: [],
      model: "turbo",
      device: "cpu",
      realTimeFactor: 1,
      audioUrl: `/api/voice-journal/entries/${id}/audio`,
    };
    const updateEntry = vi.fn(async (_entryId, patch) => ({ ...entry, ...patch }));
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([entry]),
      updateEntry,
    });
    controllers.push(controller);

    const card = root.querySelector(`.voice-journal-entry[data-entry-id="${id}"]`);
    expect(card.querySelector(".voice-journal-organized-timestamp-ghosts")).toBeNull();
    const correctionEditor = card.querySelector(".voice-journal-correction-editor");
    correctionEditor.open = true;
    correctionEditor.dispatchEvent(new Event("toggle"));
    correctionEditor.querySelector(".voice-journal-segment-edit-trigger").click();
    correctionEditor.querySelector(".voice-journal-inline-editor input").value = "Poprawiony tekst";
    correctionEditor.querySelector(".voice-journal-inline-editor-save").click();

    await vi.waitFor(() => expect(updateEntry).toHaveBeenCalledOnce());
    expect(card.querySelector(".voice-journal-transcript-segments").textContent).toContain("Poprawiony tekst");
    expect(card.querySelector(`#voice-journal-entry-transcript-${id}`).value).toBe("Poprawiony tekst");
    expect(card.querySelector(".voice-journal-organized-status").textContent).toContain("Zaktualizowano po korekcie");
  });

  it("filters, searches and sorts existing entries without another backend request", async () => {
    const root = mountWidget();
    const storedEntries = [
      {
        id: "1".repeat(32), title: "Poranny plan", transcript: "Zakupy", entryCategory: "morning",
        recordedAt: "2026-07-20T08:00:00", tags: ["dom"], model: "small", durationSeconds: 60,
        device: "cpu", realTimeFactor: 1, originalFilename: "rano.wav", audioUrl: "/audio/1",
      },
      {
        id: "2".repeat(32), title: "Spotkanie", transcript: "Projekt Kraków", entryCategory: "after-event",
        recordedAt: "2026-07-22T18:00:00", tags: ["praca"], model: "turbo", durationSeconds: 180,
        device: "cpu", realTimeFactor: 1, originalFilename: "praca.webm", audioUrl: "/audio/2",
      },
      {
        id: "3".repeat(32), title: "Wieczór", transcript: "Podsumowanie", entryCategory: "evening",
        recordedAt: "2026-07-21T21:00:00", tags: ["dom"], model: "turbo", durationSeconds: 30,
        device: "cpu", realTimeFactor: 1, originalFilename: "wieczor.m4a", audioUrl: "/audio/3",
      },
    ];
    const fetchEntries = vi.fn().mockResolvedValue(storedEntries);
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries,
    });
    controllers.push(controller);

    expect(Array.from(root.querySelectorAll(".voice-journal-entry-title"), (node) => node.textContent))
      .toEqual(["Spotkanie", "Wieczór", "Poranny plan"]);
    const search = root.querySelector("#voice-journal-filter-query");
    search.value = "Kraków";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    expect(root.querySelectorAll(".voice-journal-entry")).toHaveLength(1);
    expect(root.querySelector(".voice-journal-entry-title").textContent).toBe("Spotkanie");
    expect(root.querySelector("#voice-journal-entry-count").textContent).toBe("1/3");
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(search.value).toBe("");
    expect(root.querySelectorAll(".voice-journal-entry")).toHaveLength(3);

    search.value = "brak wyniku";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    expect(root.querySelector("#voice-journal-empty-title").textContent).toBe("Brak pasujących wpisów");
    root.querySelector("#voice-journal-empty-reset").click();

    const sort = root.querySelector("#voice-journal-filter-sort");
    sort.value = "shortest";
    sort.dispatchEvent(new Event("change", { bubbles: true }));
    expect(Array.from(root.querySelectorAll(".voice-journal-entry-title"), (node) => node.textContent))
      .toEqual(["Wieczór", "Poranny plan", "Spotkanie"]);
    expect(fetchEntries).toHaveBeenCalledOnce();
  });

  it("shows a retryable list error and recovers", async () => {
    const root = mountWidget();
    const fetchEntries = vi.fn()
      .mockRejectedValueOnce(new Error("Backend listy jest offline"))
      .mockResolvedValueOnce([]);
    const controller = await initVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries,
    });
    controllers.push(controller);

    expect(root.querySelector("#voice-journal-list-status").dataset.kind).toBe("error");
    expect(root.querySelector("#voice-journal-list-status-text").textContent).toContain("offline");
    expect(root.querySelector("#voice-journal-list-retry").hidden).toBe(false);
    root.querySelector("#voice-journal-list-retry").click();
    await vi.waitFor(() => expect(fetchEntries).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(root.querySelector("#voice-journal-empty").hidden).toBe(false));
    expect(root.querySelector("#voice-journal-empty-title").textContent).toBe("Brak zapisanych wpisów");
  });
});
