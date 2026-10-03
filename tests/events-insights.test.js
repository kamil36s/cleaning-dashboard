import { describe, expect, it } from "vitest";
import { enrichEvents, normalizeEvents } from "../js/events-sources.js";
import {
  generateEventInsights,
  getCurrentWeekWorkingDays,
  getLongWeekendSuggestion,
} from "../js/events-insights.js";

function buildEvents(raw, today = new Date(2026, 4, 8)) {
  return enrichEvents(normalizeEvents(raw), { today });
}

describe("events insights", () => {
  it("detects Thursday holiday bridge suggestions", () => {
    const [event] = buildEvents([
      {
        id: "corpus-2026",
        date: "2026-06-04",
        title: "Boże Ciało",
        type: "public_holiday",
        isDayOff: true,
        source: "local",
      },
    ]);

    expect(getLongWeekendSuggestion(event)).toMatchObject({
      kind: "long_weekend",
      tone: "warn",
    });
    expect(getLongWeekendSuggestion(event).text).toContain("piątek");
  });

  it("detects ready long weekends on Friday", () => {
    const [event] = buildEvents([
      {
        id: "christmas-2026",
        date: "2026-12-25",
        title: "Boże Narodzenie",
        type: "public_holiday",
        isDayOff: true,
        source: "local",
      },
    ]);

    expect(getLongWeekendSuggestion(event).text).toContain("gotowy długi weekend");
  });

  it("generates dashboard counts and next event insights", () => {
    const events = buildEvents([
      {
        id: "payday",
        date: "2026-05-29",
        title: "Wypłata",
        type: "payday",
        isDayOff: false,
        source: "local",
      },
      {
        id: "corpus-2026",
        date: "2026-06-04",
        title: "Boże Ciało",
        type: "public_holiday",
        isDayOff: true,
        source: "local",
      },
      {
        id: "birthday",
        date: "2026-12-03",
        title: "Urodziny testowe",
        type: "birthday",
        isDayOff: false,
        source: "local",
      },
    ]);

    const { stats, insights } = generateEventInsights(events, {
      today: new Date(2026, 4, 8),
    });

    expect(stats.next30Days).toBe(2);
    expect(stats.publicHolidaysNext60Days).toBe(1);
    expect(insights.some((item) => item.kind === "next_day_off")).toBe(true);
    expect(insights.some((item) => item.kind === "next_birthday")).toBe(true);
  });

  it("counts fewer working days in the current week", () => {
    const today = new Date(2026, 5, 3);
    const events = buildEvents(
      [
        {
          id: "corpus-2026",
          date: "2026-06-04",
          title: "Boże Ciało",
          type: "public_holiday",
          isDayOff: true,
          source: "local",
        },
      ],
      today,
    );

    expect(getCurrentWeekWorkingDays(events, today)).toMatchObject({
      workingDays: 4,
    });
  });
});
