import { describe, expect, it, vi } from "vitest";

import { ReminderExecutionService } from "../js/habits-reminder-execution.js";
import { localDateKey } from "../js/habits-reminder-schedule.js";

function fixture(now, overrides = {}) {
  const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  const habit = {
    id: "habit-1",
    name: "Tracker item",
    type: "binary",
    archived: false,
    reminderConfig: {
      enabled: true,
      scheduleType: "daily",
      timeGroupIds: ["morning"],
      customTimes: [],
      snoozeMinutes: 10,
      skipIfCompleted: true,
      completionPolicy: "day",
      ...overrides,
    },
  };
  const groups = [{ id: "morning", name: "Morning", localTime: time }];
  const states = [];
  const notify = vi.fn();
  const claim = vi.fn(async (occurrence) => {
    if (states.some((state) => state.occurrenceKey === occurrence.occurrenceKey && state.status !== "snoozed")) return { claimed: false };
    const state = { ...occurrence, status: "fired", scheduledLocalTime: occurrence.localTime };
    states.splice(0, states.length, state);
    return { claimed: true, state };
  });
  const update = vi.fn(async (action, occurrence) => {
    states.splice(0, states.length, { ...occurrence, status: action });
  });
  let complete = false;
  const service = new ReminderExecutionService({
    getHabits: () => [habit],
    getGroups: () => groups,
    getStates: () => states,
    isComplete: () => complete,
    claimOccurrence: claim,
    updateOccurrence: update,
    notify,
  });
  return { service, habit, states, notify, claim, update, setComplete: (value) => { complete = value; } };
}

describe("habits reminder execution", () => {
  it("fires once and a reload cannot duplicate a claimed occurrence", async () => {
    const now = new Date(2026, 8, 23, 9, 0, 30);
    const run = fixture(now);
    await run.service.tick(now);
    await run.service.tick(now);
    expect(run.notify).toHaveBeenCalledTimes(1);
    expect(run.claim).toHaveBeenCalledTimes(1);

    const reloadedNotify = vi.fn();
    const reloaded = new ReminderExecutionService({
      getHabits: () => [run.habit], getGroups: () => [{ id: "morning", name: "Morning", localTime: "09:00" }],
      getStates: () => run.states, isComplete: () => false,
      claimOccurrence: run.claim, updateOccurrence: run.update, notify: reloadedNotify,
    });
    await reloaded.tick(now);
    expect(reloadedNotify).not.toHaveBeenCalled();
  });

  it("does not fire disabled reminders", async () => {
    const now = new Date(2026, 8, 23, 9, 0, 30);
    const run = fixture(now, { enabled: false });
    await run.service.tick(now);
    expect(run.notify).not.toHaveBeenCalled();
  });

  it("suppresses a later reminder after completion", async () => {
    const now = new Date(2026, 8, 23, 21, 0, 30);
    const run = fixture(now);
    run.setComplete(true);
    await run.service.tick(now);
    expect(run.notify).not.toHaveBeenCalled();
  });

  it("fires a due snooze and completion cancels a snooze", async () => {
    const now = new Date(2026, 8, 23, 9, 10, 0);
    const run = fixture(now);
    const occurrenceKey = `habit-1|${localDateKey(now)}|group:morning`;
    run.states.push({ occurrenceKey, habitId: "habit-1", status: "snoozed", snoozedUntil: new Date(now.getTime() - 1000).toISOString() });
    await run.service.tick(now);
    expect(run.notify).toHaveBeenCalledOnce();

    run.notify.mockClear();
    run.states.splice(0, run.states.length, { occurrenceKey, habitId: "habit-1", status: "snoozed", snoozedUntil: new Date(now.getTime() + 60_000).toISOString() });
    run.setComplete(true);
    await run.service.tick(now);
    expect(run.update).toHaveBeenCalledWith("satisfied", expect.objectContaining({ occurrenceKey }));
    expect(run.notify).not.toHaveBeenCalled();
  });

  it("keeps a snooze valid across local midnight", async () => {
    const now = new Date(2026, 8, 24, 0, 5, 0);
    const run = fixture(now);
    const priorDate = "2026-09-23";
    const occurrenceKey = `habit-1|${priorDate}|group:morning`;
    run.states.push({
      occurrenceKey,
      habitId: "habit-1",
      localDate: priorDate,
      sourceKey: "group:morning",
      scheduledLocalTime: "23:55",
      status: "snoozed",
      snoozedUntil: new Date(now.getTime() - 1000).toISOString(),
    });
    await run.service.tick(now);
    expect(run.notify).toHaveBeenCalledWith(expect.objectContaining({ occurrenceKey, localDate: priorDate }));
  });
});
