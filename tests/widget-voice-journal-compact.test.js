import { afterEach, describe, expect, it, vi } from "vitest";

import { initCompactVoiceJournalWidget } from "../js/widget-voice-journal-compact.js";

const HEALTH = {
  status: "ok",
  supportedModels: ["small", "medium", "turbo"],
  cachedModels: ["turbo"],
  recommendedModel: "small",
  supportedLanguages: ["auto", "pl"],
  supportedTasks: ["transcribe"],
  supportedDevices: ["auto", "cpu"],
  maxUploadBytes: 250 * 1024 * 1024,
  maxDurationSeconds: 90 * 60,
};

function mountCompactWidget() {
  document.body.innerHTML = `
    <section class="card voice-journal">
      <div id="voice-journal-backend-pill"></div>
      <a class="card-cta" href="./voice-journal.html">Otwórz</a>
      <div id="voice-journal-root" data-voice-journal-mode="compact"></div>
    </section>
  `;
  return document.getElementById("voice-journal-root");
}

describe("compact voice journal widget", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("shows only quick upload, title and entry statistics", async () => {
    const root = mountCompactWidget();
    const controller = await initCompactVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries: vi.fn().mockResolvedValue([{
        recordedAt: "2026-07-21T12:00:00.000Z",
        durationSeconds: 62,
      }]),
    });

    expect(root.querySelector("#voice-journal-compact-count").textContent).toBe("1");
    expect(root.querySelector("#voice-journal-compact-duration").textContent).toBe("1:02");
    expect(root.querySelector("#voice-journal-compact-status").textContent).toContain("250 MB / 90 min");
    expect(root.querySelector("#voice-journal-compact-title")).not.toBeNull();
    expect(root.querySelector("#voice-journal-transcription-settings")).toBeNull();
    expect(root.querySelector("#voice-journal-entry-list")).toBeNull();
    expect(document.querySelector('a[href="./voice-journal.html"]')).not.toBeNull();
    controller.dispose();
  });

  it("transcribes and saves a recording with cached defaults", async () => {
    const root = mountCompactWidget();
    const createJob = vi.fn().mockResolvedValue({
      id: "a".repeat(32), status: "queued", stage: "queued",
    });
    const getJob = vi.fn().mockResolvedValue({
      id: "a".repeat(32), status: "completed", stage: "completed",
    });
    const result = {
      transcript: "Surowa treść.",
      transcriptSegments: [{ start: 0, end: 2, text: "Surowa treść." }],
      model: "turbo",
      device: "cpu",
      transcriptionDurationSeconds: 2,
      realTimeFactor: 0.2,
    };
    const createEntry = vi.fn().mockResolvedValue({ id: "b".repeat(32) });
    const fetchEntries = vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ recordedAt: "2026-07-21T12:00:00.000Z", durationSeconds: 10 }]);
    const controller = await initCompactVoiceJournalWidget(root, {
      fetchHealth: vi.fn().mockResolvedValue(HEALTH),
      fetchEntries,
      createJob,
      getJob,
      getJobResult: vi.fn().mockResolvedValue(result),
      createEntry,
      waitForPoll: vi.fn().mockResolvedValue(),
    });
    const file = new File(["audio"], "memo.webm", {
      type: "audio/webm",
      lastModified: new Date("2026-07-21T12:00:00.000Z").getTime(),
    });
    controller.selectFile(file);
    expect(root.querySelector("#voice-journal-compact-title").value).toBe("memo.webm");
    root.querySelector("#voice-journal-compact-title").value = "Szybki wpis";

    root.querySelector("#voice-journal-compact-start").click();
    await vi.waitFor(() => expect(createEntry).toHaveBeenCalledOnce());

    expect(createJob).toHaveBeenCalledWith(expect.objectContaining({
      file,
      model: "turbo",
      language: "pl",
      transcriptionOptions: {},
      allowModelDownload: false,
    }), expect.objectContaining({ onUploadProgress: expect.any(Function) }));
    expect(createEntry).toHaveBeenCalledWith({
      file,
      entry: expect.objectContaining({
        title: "Szybki wpis",
        entryCategory: "spontaneous",
        rawTranscript: "Surowa treść.",
        transcript: "Surowa treść.",
        transcriptSegments: result.transcriptSegments,
      }),
    });
    await vi.waitFor(() => expect(root.querySelector("#voice-journal-compact-count").textContent).toBe("1"));
    expect(root.querySelector("#voice-journal-compact-status").textContent).toContain("zapisana");
    controller.dispose();
  });
});
