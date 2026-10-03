import { describe, expect, it } from "vitest";

import {
  filterVoiceJournalEntries,
  hasActiveVoiceJournalFilters,
  voiceJournalFilterOptions,
} from "../js/voice-journal-filters.js";

const ENTRIES = [
  {
    id: "a", title: "Poranny plan", transcript: "Zakupy i spacer", recordedAt: "2026-07-20T08:00:00",
    entryCategory: "morning", tags: ["plan", "Dom"], model: "small", durationSeconds: 60,
  },
  {
    id: "b", title: "Po spotkaniu", transcript: "Omówienie projektu Kraków", recordedAt: "2026-07-22T18:00:00",
    entryCategory: "after-event", tags: ["praca"], model: "turbo", durationSeconds: 180,
  },
  {
    id: "c", title: "Wieczór", transcript: "Podsumowanie dnia", recordedAt: "2026-07-21T21:00:00",
    entryCategory: "evening", tags: ["dom"], model: "turbo", durationSeconds: 30,
  },
];

describe("voice journal entry filters", () => {
  it("searches title and transcript and combines all filters", () => {
    expect(filterVoiceJournalEntries(ENTRIES, { query: "Kraków" }).map(({ id }) => id)).toEqual(["b"]);
    expect(filterVoiceJournalEntries(ENTRIES, {
      dateFrom: "2026-07-21",
      dateTo: "2026-07-22",
      entryCategory: "after-event",
      tag: "PRACA",
      model: "turbo",
    }).map(({ id }) => id)).toEqual(["b"]);
  });

  it("sorts entries by date and duration", () => {
    expect(filterVoiceJournalEntries(ENTRIES, { sort: "newest" }).map(({ id }) => id)).toEqual(["b", "c", "a"]);
    expect(filterVoiceJournalEntries(ENTRIES, { sort: "oldest" }).map(({ id }) => id)).toEqual(["a", "c", "b"]);
    expect(filterVoiceJournalEntries(ENTRIES, { sort: "longest" }).map(({ id }) => id)).toEqual(["b", "a", "c"]);
    expect(filterVoiceJournalEntries(ENTRIES, { sort: "shortest" }).map(({ id }) => id)).toEqual(["c", "a", "b"]);
  });

  it("keeps unpublished entries before published ones while sorting inside both groups", () => {
    const groupedEntries = [
      { ...ENTRIES[0], journalPublication: { id: "published-a" } },
      { ...ENTRIES[1], journalPublication: null },
      { ...ENTRIES[2], journalPublication: { id: "published-c" } },
    ];

    expect(filterVoiceJournalEntries(groupedEntries, { sort: "newest" }).map(({ id }) => id))
      .toEqual(["b", "c", "a"]);
  });

  it("builds unique tag/model options and detects active filters", () => {
    expect(voiceJournalFilterOptions(ENTRIES)).toEqual({
      tags: ["Dom", "plan", "praca"],
      models: ["small", "turbo"],
    });
    expect(hasActiveVoiceJournalFilters({ sort: "newest" })).toBe(false);
    expect(hasActiveVoiceJournalFilters({ query: "plan", sort: "newest" })).toBe(true);
  });
});
