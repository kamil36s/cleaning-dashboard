import { describe, expect, it, vi } from "vitest";

import {
  cancelVoiceJournalJob,
  createVoiceJournalJob,
  createVoiceJournalEntry,
  deleteVoiceJournalEntry,
  fetchVoiceJournalEntries,
  fetchVoiceJournalJob,
  fetchVoiceJournalJobResult,
  transcribeVoiceJournal,
  updateVoiceJournalEntry,
  availableVoiceJournalOptions,
  voiceJournalEngines,
} from "../js/voice-journal-api.js";

describe("voice journal API", () => {
  it("uploads a queued job with real XMLHttpRequest progress", async () => {
    const listeners = new Map();
    const uploadListeners = new Map();
    const xhr = {
      status: 202,
      statusText: "Accepted",
      responseText: JSON.stringify({ id: "a".repeat(32), status: "queued" }),
      upload: {
        addEventListener: (name, listener) => uploadListeners.set(name, listener),
      },
      open: vi.fn(),
      addEventListener: (name, listener) => listeners.set(name, listener),
      send: vi.fn((form) => {
        uploadListeners.get("progress")?.({ lengthComputable: true, loaded: 25, total: 100 });
        listeners.get("load")?.();
        xhr.form = form;
      }),
      abort: vi.fn(),
    };
    const onUploadProgress = vi.fn();
    const file = new File(["audio"], "memo.webm", { type: "audio/webm" });

    const job = await createVoiceJournalJob({
      file,
      model: "turbo",
      language: "pl",
      task: "transcribe",
      device: "cpu",
      transcriptionOptions: { temperature: 0, fp16: false },
      allowModelDownload: true,
    }, { xhrFactory: () => xhr, onUploadProgress });

    expect(job.status).toBe("queued");
    expect(xhr.open).toHaveBeenCalledWith("POST", "/api/voice-journal/jobs");
    expect(xhr.form.get("file").name).toBe("memo.webm");
    expect(JSON.parse(xhr.form.get("options"))).toEqual({ temperature: 0, fp16: false });
    expect(xhr.form.get("allowModelDownload")).toBe("true");
    expect(xhr.form.get("engine")).toBe("openai-whisper");
    expect(onUploadProgress).toHaveBeenCalledWith({ loaded: 25, total: 100, percent: 25 });
  });

  it("keeps OpenAI models and exposes Faster-Whisper as an independent optional engine", () => {
    const health = {
      defaultEngine: "openai-whisper",
      supportedDevices: ["auto", "cpu"],
      engines: [
        { id: "openai-whisper", available: true, supportedModels: ["small", "medium", "turbo"], cachedModels: ["turbo"] },
        { id: "faster-whisper", available: true, supportedModels: ["tiny", "base", "small", "large-v3"], cachedModels: [] },
      ],
    };
    expect(voiceJournalEngines(health).map((engine) => engine.id)).toEqual(["openai-whisper", "faster-whisper"]);
    expect(availableVoiceJournalOptions(health, "openai-whisper").supportedModels).toEqual(["small", "medium", "turbo"]);
    expect(availableVoiceJournalOptions(health, "faster-whisper").supportedModels).toEqual(["tiny", "base", "small", "large-v3"]);
  });

  it("uses job polling, cancellation and result routes", async () => {
    const id = "b".repeat(32);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id, status: "running" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id, status: "cancelling" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ transcript: "Gotowe" }) });

    await fetchVoiceJournalJob(id, fetchMock);
    await cancelVoiceJournalJob(id, fetchMock);
    await fetchVoiceJournalJobResult(id, fetchMock);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `/api/voice-journal/jobs/${id}`,
      `/api/voice-journal/jobs/${id}/cancel`,
      `/api/voice-journal/jobs/${id}/result`,
    ]);
    expect(fetchMock.mock.calls[1][1]).toEqual({ method: "POST" });
  });

  it("sends one audio file and selected options as multipart form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ transcript: "Test" }),
    });
    const file = new File(["audio"], "memo.webm", { type: "audio/webm" });

    await transcribeVoiceJournal({
      file,
      model: "turbo",
      language: "pl",
      task: "transcribe",
      device: "cpu",
    }, fetchMock);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/voice-journal/transcribe");
    expect(options.method).toBe("POST");
    expect(options.headers).toBeUndefined();
    expect(options.body.get("file").name).toBe("memo.webm");
    expect(options.body.get("model")).toBe("turbo");
    expect(options.body.get("language")).toBe("pl");
    expect(options.body.get("task")).toBe("transcribe");
    expect(options.body.get("device")).toBe("cpu");
  });

  it("uses the CRUD entry routes without encoding audio as JSON", async () => {
    const id = "a".repeat(32);
    const file = new File(["audio"], "memo.webm", { type: "audio/webm" });
    const entry = { title: "Test", transcript: "Treść" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ entries: [{ id }] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id, title: "Nowy" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ deleted: true }) });

    await createVoiceJournalEntry({ file, entry }, fetchMock);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/voice-journal/entries");
    expect(fetchMock.mock.calls[0][1].body.get("file")).toBeInstanceOf(File);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body.get("entry"))).toEqual(entry);

    expect(await fetchVoiceJournalEntries(fetchMock)).toEqual([{ id }]);
    await updateVoiceJournalEntry(id, { title: "Nowy" }, fetchMock);
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "PATCH" }));
    await deleteVoiceJournalEntry(id, { deleteAudio: true }, fetchMock);
    expect(fetchMock.mock.calls[3][0]).toBe(`/api/voice-journal/entries/${id}?deleteAudio=true`);
    expect(fetchMock.mock.calls[3][1].method).toBe("DELETE");
  });
});
