import { describe, expect, it } from "vitest";

import {
  getNextReminder,
  getReminderOccurrences,
  isScheduledOnDate,
  localDateKey,
  occurrenceDateTime,
  shiftLocalDateKey,
  validateReminderConfig,
} from "../js/habits-reminder-schedule.js";

const groups = [
  { id: "morning", name: "Morning", localTime: "09:00" },
  { id: "evening", name: "Evening", localTime: "21:00" },
];

function item(reminderConfig) {
  return { id: "item-1", name: "Tracker item", reminderConfig: { enabled: true, snoozeMinutes: 10, skipIfCompleted: true, ...reminderConfig } };
}

describe("habits reminder schedule", () => {
  it("schedules daily reminders and multiple time groups", () => {
    const habit = item({ scheduleType: "daily", timeGroupIds: ["morning", "evening"] });
    expect(isScheduledOnDate(habit, "2026-09-23")).toBe(true);
    expect(getReminderOccurrences(habit, "2026-09-23", groups).map((value) => [value.label, value.localTime])).toEqual([
      ["Morning", "09:00"],
      ["Evening", "21:00"],
    ]);
  });

  it("includes selected weekdays and suppresses unselected weekdays", () => {
    const habit = item({ scheduleType: "weekdays", selectedWeekdays: [0, 2], timeGroupIds: ["morning"] });
    expect(isScheduledOnDate(habit, "2026-09-23")).toBe(true); // Wednesday
    expect(isScheduledOnDate(habit, "2026-09-24")).toBe(false);
  });

  it("resolves group times dynamically after a global edit", () => {
    const habit = item({ scheduleType: "daily", timeGroupIds: ["morning"] });
    expect(getReminderOccurrences(habit, "2026-09-23", groups)[0].localTime).toBe("09:00");
    expect(getReminderOccurrences(habit, "2026-09-23", [{ ...groups[0], localTime: "10:00" }])[0].localTime).toBe("10:00");
  });

  it("calculates every two days from its anchor across month and year boundaries", () => {
    const september = item({ scheduleType: "interval_days", intervalDays: 2, intervalAnchorDate: "2026-09-29", timeGroupIds: ["evening"] });
    expect(isScheduledOnDate(september, "2026-09-29")).toBe(true);
    expect(isScheduledOnDate(september, "2026-09-30")).toBe(false);
    expect(isScheduledOnDate(september, "2026-10-01")).toBe(true);
    expect(isScheduledOnDate(september, "2026-09-27")).toBe(false);

    const december = item({ scheduleType: "interval_days", intervalDays: 2, intervalAnchorDate: "2026-12-30", timeGroupIds: ["evening"] });
    expect(isScheduledOnDate(december, "2027-01-01")).toBe(true);
    expect(isScheduledOnDate(december, "2027-01-02")).toBe(false);
  });

  it("finds the next recurring interval occurrence", () => {
    const habit = item({ scheduleType: "interval_days", intervalDays: 2, intervalAnchorDate: "2026-09-23", timeGroupIds: ["evening"] });
    const next = getNextReminder(habit, new Date(2026, 8, 24, 12, 0), groups);
    expect(next.localDate).toBe("2026-09-25");
    expect(next.localTime).toBe("21:00");
  });

  it("uses local calendar dates at midnight and constructs DST-day local times", () => {
    const beforeMidnight = new Date(2026, 9, 25, 23, 59, 59);
    const afterMidnight = new Date(2026, 9, 26, 0, 0, 1);
    expect(localDateKey(beforeMidnight)).toBe("2026-10-25");
    expect(localDateKey(afterMidnight)).toBe("2026-10-26");
    expect(shiftLocalDateKey("2026-03-28", 1)).toBe("2026-03-29");
    const dstDay = occurrenceDateTime("2026-03-29", "03:30");
    expect([dstDay.getFullYear(), dstDay.getMonth() + 1, dstDay.getDate(), dstDay.getHours(), dstDay.getMinutes()]).toEqual([2026, 3, 29, 3, 30]);
  });

  it("never schedules disabled or invalid configurations", () => {
    const disabled = item({ enabled: false, scheduleType: "daily", timeGroupIds: ["morning"] });
    expect(getReminderOccurrences(disabled, "2026-09-23", groups)).toEqual([]);
    expect(validateReminderConfig({ enabled: true, scheduleType: "interval_days", intervalDays: 0, intervalAnchorDate: "", timeGroupIds: [] }, groups).length).toBeGreaterThan(0);
    expect(validateReminderConfig({ enabled: true, scheduleType: "daily", timeGroupIds: ["deleted"] }, groups)).toContain("A selected time group no longer exists.");
  });
});
