import { describe, expect, it } from "vitest";
import { generatePredictedPaydays, getPredictedPayday, inferPaydayRule } from "../js/payday-events.js";
import { toISODate } from "../js/events-date.js";

describe("payday prediction", () => {
  it("uses the second-to-last business day for normal months", () => {
    expect(toISODate(getPredictedPayday(2026, 0))).toBe("2026-01-29");
    expect(toISODate(getPredictedPayday(2026, 2))).toBe("2026-03-30");
    expect(toISODate(getPredictedPayday(2026, 3))).toBe("2026-04-29");
    expect(toISODate(getPredictedPayday(2025, 6))).toBe("2025-07-30");
    expect(toISODate(getPredictedPayday(2025, 9))).toBe("2025-10-30");
  });

  it("treats December as a before-Christmas payout", () => {
    expect(toISODate(getPredictedPayday(2025, 11))).toBe("2025-12-22");
  });

  it("generates upcoming payday events from the current month", () => {
    const events = generatePredictedPaydays({
      today: new Date(2026, 4, 8),
      monthsAhead: 3,
    });

    expect(events.map((event) => event.date)).toEqual([
      "2026-05-28",
      "2026-06-29",
      "2026-07-30",
    ]);
  });

  it("infers the rule from the supplied samples", () => {
    const rule = inferPaydayRule([
      "2026-04-29",
      "2026-03-30",
      "2026-01-29",
      "2025-12-22",
      "2025-10-30",
      "2025-09-29",
      "2025-07-30",
    ]);

    expect(rule).toMatchObject({
      rule: "second_last_business_day",
      decemberRule: "business_day_on_or_before_december_22",
      confidence: 1,
    });
  });
});
