import { describe, expect, it } from "vitest";

import {
  countSobrietyDays,
  isDontDrinkConfirmedToday,
  resolveDontDrinkHabitState,
  resolveSobrietyDateState,
} from "../js/sobriety-streak.js";

function dayStart(year, monthIndex, day) {
  return new Date(year, monthIndex, day, 0, 0, 0, 0).getTime();
}

describe("sobriety streak", () => {
  it("counts through yesterday while today's tick is still missing", () => {
    const today = dayStart(2026, 7, 25);
    const days = new Map([
      [dayStart(2026, 7, 24), [2]],
      [dayStart(2026, 7, 23), [2]],
    ]);

    expect(countSobrietyDays(days, today)).toBe(2);
  });

  it("adds today only after the sober tick is confirmed", () => {
    const today = dayStart(2026, 7, 25);
    const days = new Map([
      [today, [2]],
      [dayStart(2026, 7, 24), [2]],
      [dayStart(2026, 7, 23), [2]],
    ]);

    expect(countSobrietyDays(days, today)).toBe(3);
    expect(isDontDrinkConfirmedToday({ doneToday: true, todayValue: 2 })).toBe(true);
    expect(isDontDrinkConfirmedToday({ doneToday: false, todayValue: null })).toBe(false);
  });

  it("reads the current Habits App date map without zeroing an unconfirmed morning", () => {
    const values = new Map([
      ["2026-08-22", 0],
      ["2026-08-23", 2],
      ["2026-08-24", 2],
      ["2026-08-25", 2],
    ]);

    expect(resolveSobrietyDateState(values, "2026-08-26")).toEqual({
      days: 3,
      confirmedToday: false,
    });
    values.set("2026-08-26", 2);
    expect(resolveSobrietyDateState(values, "2026-08-26")).toEqual({
      days: 4,
      confirmedToday: true,
    });
  });

  it("uses the live API habit map and pending mutations instead of the static export", () => {
    const habits = [{
      id: "live-dont-drink",
      name: "Don't drink",
      entries: new Map([
        ["2026-08-23", 2],
        ["2026-08-24", 2],
        ["2026-08-25", 2],
        ["2026-08-26", 2],
      ]),
    }];

    expect(resolveDontDrinkHabitState(habits, "2026-08-26")).toEqual({
      days: 4,
      confirmedToday: true,
    });
    expect(resolveDontDrinkHabitState(habits, "2026-08-26", [{
      habitId: "live-dont-drink",
      date: "2026-08-26",
      value: null,
    }])).toEqual({
      days: 3,
      confirmedToday: false,
    });
  });
});
