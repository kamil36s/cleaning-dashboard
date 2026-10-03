import { describe, expect, it } from "vitest";
import {
  daysBetween,
  formatDaysUntil,
  getDateMeta,
  isSameWeek,
  parseISODate,
} from "../js/events-date.js";

describe("events date utilities", () => {
  it("parses local ISO dates without timezone drift", () => {
    const date = parseISODate("2026-06-04");

    expect(date.getFullYear()).toBe(2026);
    expect(date.getMonth()).toBe(5);
    expect(date.getDate()).toBe(4);
  });

  it("rejects invalid calendar dates", () => {
    expect(parseISODate("2026-02-31")).toBeNull();
    expect(parseISODate("04.06.2026")).toBeNull();
  });

  it("calculates upcoming date metadata", () => {
    const today = new Date(2026, 4, 8);
    const eventDate = new Date(2026, 4, 9);
    const meta = getDateMeta(eventDate, today, "pl-PL");

    expect(daysBetween(today, eventDate)).toBe(1);
    expect(meta.isTomorrow).toBe(true);
    expect(meta.isThisWeek).toBe(true);
    expect(meta.isWithin30Days).toBe(true);
    expect(meta.isWeekend).toBe(true);
  });

  it("uses Monday as the start of the week", () => {
    expect(isSameWeek(new Date(2026, 4, 10), new Date(2026, 4, 8))).toBe(true);
    expect(isSameWeek(new Date(2026, 4, 11), new Date(2026, 4, 8))).toBe(false);
  });

  it("formats relative day labels", () => {
    expect(formatDaysUntil(0)).toBe("dzisiaj");
    expect(formatDaysUntil(1)).toBe("jutro");
    expect(formatDaysUntil(20)).toBe("za 20 dni");
    expect(formatDaysUntil(-2)).toBe("2 dni temu");
  });
});
