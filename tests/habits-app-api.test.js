import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createHabit,
  pollHabitChanges,
  pushHabitMutations,
  saveReminderSettings,
  setHabitArchived,
  setHabitPositions,
  setHabitReminderConfig,
  snapshotToHabits,
  updateReminderOccurrence,
} from "../js/habits-app-api.js";

describe("habits app API adapter", () => {
  beforeEach(() => localStorage.clear());

  it("creates a canonical habit through sync and returns its new id", async () => {
    const fetchImpl = vi.fn(async (_url, options) => {
      const request = JSON.parse(options.body);
      return { ok: true, json: async () => ({ acknowledgedMutationIds: [request.mutations[0].mutationId] }) };
    });
    const id = await createHabit({
      name: "Witamina B12", category: "SUPPLEMENT", type: "NUMERIC",
      unit: "mg", targetValueMilli: 5000, position: 3,
    }, "12", fetchImpl);
    const [url, options] = fetchImpl.mock.calls[0];
    const request = JSON.parse(options.body);
    expect(url).toBe("/api/habits/sync");
    expect(request).toMatchObject({ schemaVersion: 1, lastPulledCursor: "12" });
    expect(request.mutations[0]).toMatchObject({
      entityId: id, entityType: "HABIT", operation: "UPSERT", baseRevision: null,
      payload: { name: "Witamina B12", category: "SUPPLEMENT", type: "NUMERIC", unit: "mg", targetValueMilli: 5000, position: 3 },
    });
  });

  it("maps canonical API entities to dashboard values", () => {
    const habits = snapshotToHabits({
      habits: [{
        id: "habit-1", name: "Pregabalin", type: "NUMERIC", category: "MEDICATION",
        unit: "mg", colorHex: "#ffffff", targetValueMilli: 150000,
        frequencyNumerator: 1, frequencyDenominator: 1, position: 0, archived: true, revision: 3,
      }],
      entries: [{ id: "entry-1", habitId: "habit-1", date: "2026-08-26", valueMilli: 150000, status: null, revision: 4 }],
    });
    expect(habits[0]).toMatchObject({ id: "habit-1", type: "numeric", category: "meds", target: 150, archived: true });
    expect(habits[0].entries.get("2026-08-26")).toBe(150);
    expect(habits[0].entryRevisions.get("2026-08-26")).toBe(4);
  });

  it("maps reminder configuration without changing tracker value semantics", () => {
    const [habit] = snapshotToHabits({
      habits: [{
        id: "habit-1", name: "Vitamin D", type: "BINARY", category: "SUPPLEMENT",
        reminderConfig: { enabled: true, scheduleType: "daily", timeGroupIds: ["morning"] },
      }],
      entries: [],
    });
    expect(habit).toMatchObject({ type: "binary", category: "supplements" });
    expect(habit.reminderConfig).toMatchObject({ enabled: true, timeGroupIds: ["morning"] });
  });

  it("sends an Android-compatible ENTRY mutation", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ acknowledgedMutationIds: ["m1"], changes: [], conflicts: [] }),
    }));
    const habit = { id: "habit-1", name: "Meditation", type: "binary", entryRevisions: new Map([["2026-08-26", 2]]) };
    await pushHabitMutations([{ mutationId: "m1", habitId: "habit-1", habitName: "Meditation", date: "2026-08-26", value: 2 }], [habit], "10", fetchImpl);
    const request = JSON.parse(fetchImpl.mock.calls[0][1].body);
    expect(request).toMatchObject({ schemaVersion: 1, lastPulledCursor: "10" });
    expect(request.mutations[0]).toMatchObject({
      entityType: "ENTRY", operation: "UPSERT", baseRevision: 2,
      payload: { habitId: "habit-1", date: "2026-08-26", status: "DONE" },
    });
  });

  it("polls the change stream without requesting a full snapshot", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ nextCursor: "12", changes: [] }),
    }));
    await pollHabitChanges("12", fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith("/api/habits/sync", expect.objectContaining({ method: "POST" }));
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toMatchObject({
      lastPulledCursor: "12",
      mutations: [],
    });
  });

  it("archives a habit with a partial HABIT upsert and keeps its identity", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ acknowledgedMutationIds: ["ok"], changes: [], conflicts: [] }),
    }));
    await setHabitArchived({ id: "habit-1", name: "Meditation", revision: 7 }, true, "12", fetchImpl);
    const request = JSON.parse(fetchImpl.mock.calls[0][1].body);
    expect(request.mutations[0]).toMatchObject({
      entityType: "HABIT",
      entityId: "habit-1",
      operation: "UPSERT",
      baseRevision: 7,
      payload: { name: "Meditation", archived: true },
    });
  });

  it("syncs reordered positions as Android-compatible HABIT mutations", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ acknowledgedMutationIds: ["ok"], changes: [], conflicts: [] }),
    }));
    await setHabitPositions([
      { id: "creatine", name: "Creatine", position: 9, revision: 3 },
    ], "12", fetchImpl);
    const request = JSON.parse(fetchImpl.mock.calls[0][1].body);
    expect(request.mutations[0]).toMatchObject({
      entityType: "HABIT",
      entityId: "creatine",
      operation: "UPSERT",
      baseRevision: 3,
      payload: { name: "Creatine", position: 9 },
    });
  });

  it("saves item reminders, global groups and durable occurrence actions", async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ acknowledgedMutationIds: ["ok"], claimed: true }) }));
    await setHabitReminderConfig({ id: "habit-1", name: "Meditation", revision: 2 }, {
      enabled: true, scheduleType: "daily", timeGroupIds: ["morning"], customTimes: [], snoozeMinutes: 10,
    }, "20", fetchImpl);
    let request = JSON.parse(fetchImpl.mock.calls[0][1].body);
    expect(request.mutations[0]).toMatchObject({ entityType: "HABIT", payload: { name: "Meditation" } });
    expect(request.mutations[0].payload.reminderConfig.timeGroupIds).toEqual(["morning"]);

    await saveReminderSettings({ timeGroups: [{ id: "morning", name: "Morning", localTime: "09:00" }] }, fetchImpl);
    expect(fetchImpl.mock.calls[1][0]).toBe("/api/habits/reminders/settings");

    await updateReminderOccurrence("claim", {
      occurrenceKey: "habit-1|2026-09-23|group:morning", habitId: "habit-1", localDate: "2026-09-23",
      sourceKey: "group:morning", localTime: "09:00",
    }, {}, fetchImpl);
    expect(fetchImpl.mock.calls[2][0]).toBe("/api/habits/reminders/action");
    request = JSON.parse(fetchImpl.mock.calls[2][1].body);
    expect(request).toMatchObject({ action: "claim", scheduledLocalTime: "09:00" });
  });
});
