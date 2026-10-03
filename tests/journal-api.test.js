import { describe, expect, it, vi } from "vitest";

import {
  createJournalEntry,
  deleteJournalEntry,
  fetchJournalContexts,
  fetchJournalEntries,
  publishVoiceJournalEntry,
  updateJournalEntry,
} from "../js/journal-api.js";

const response = (payload, ok = true) => ({
  ok,
  status: ok ? 200 : 400,
  statusText: ok ? "OK" : "Bad Request",
  json: vi.fn().mockResolvedValue(payload),
});

describe("journal API", () => {
  it("sends the delete version and decodes a structured conflict", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({
      error: { code: "VERSION_CONFLICT", message: "changed", details: { serverVersion: 3 } },
    }, false));
    await expect(deleteJournalEntry("a", fetchImpl, 2)).rejects.toMatchObject({
      code: "VERSION_CONFLICT", details: { serverVersion: 3 },
    });
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/journal/entries/a?expectedVersion=2");
  });
  it("uses isolated journal CRUD routes", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ entries: [{ id: "1" }] }))
      .mockResolvedValueOnce(response({ id: "2" }))
      .mockResolvedValueOnce(response({ id: "2", title: "Nowy" }))
      .mockResolvedValueOnce(response({ deleted: true }));

    expect(await fetchJournalEntries(fetchImpl)).toHaveLength(1);
    await createJournalEntry({ title: "Test", content: "Treść" }, fetchImpl);
    await updateJournalEntry("2", { title: "Nowy" }, fetchImpl);
    await deleteJournalEntry("2", fetchImpl);

    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "/api/journal/entries",
      "/api/journal/entries",
      "/api/journal/entries/2",
      "/api/journal/entries/2",
    ]);
    expect(fetchImpl.mock.calls[1][1].method).toBe("POST");
    expect(fetchImpl.mock.calls[2][1].method).toBe("PATCH");
    expect(fetchImpl.mock.calls[3][1].method).toBe("DELETE");
  });

  it("loads Great Timeline context for journal dates in one request", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({ contexts: { "2026-08-16": { timelineGroups: [] } } }));

    const contexts = await fetchJournalContexts(["2026-08-16"], fetchImpl);

    expect(contexts).toHaveProperty("2026-08-16");
    expect(fetchImpl).toHaveBeenCalledWith("/api/journal/context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dates: ["2026-08-16"] }),
    });
  });

  it("publishes through the explicit voice-journal bridge", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({ id: "journal-1", sourceType: "voice-journal" }));

    const result = await publishVoiceJournalEntry("a".repeat(32), fetchImpl);

    expect(result.sourceType).toBe("voice-journal");
    expect(fetchImpl).toHaveBeenCalledWith(
      `/api/journal/publish/voice-journal/${"a".repeat(32)}`,
      { method: "POST" },
    );
  });
});
