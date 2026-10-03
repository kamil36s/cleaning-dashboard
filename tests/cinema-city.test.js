import { describe, expect, it } from "vitest";
import {
  buildCinemaCitySummary,
  formatAvailableScreeningCount,
  formatCinemaStats,
  getCinemaCityMembershipState,
  isEventWithinCinemaCityMembership,
  parseDescriptionField,
} from "../js/cinema-city.js";

const calendarExternal = {
  provider: "google_calendar",
  calendarSummary: "Cinema City Galeria Kazimierz",
  calendarId: "cinema",
};

function cinemaEvent(id, date, startTime, title, extra = "") {
  return {
    id,
    date,
    title: `🎬 ${title} [2D napisy]`,
    startTime,
    endTime: "23:00",
    notes: [
      "AUTO_CINEMA_CITY",
      `Film: ${title}`,
      "Wersja seansu: 2D napisy",
      "Film attributes:",
      `Event attributes: ${extra}`,
      "Link: https://example.test",
    ].join("\n"),
    source: "google_calendar",
    external: calendarExternal,
  };
}

describe("cinema city summary", () => {
  it("keeps Unlimited active through 19 September and disables it on the next day", () => {
    const lastDay = getCinemaCityMembershipState(new Date(2026, 8, 19, 23, 59, 0));
    const inactive = getCinemaCityMembershipState(new Date(2026, 8, 20, 0, 0, 0));

    expect(lastDay).toMatchObject({ active: true, days: 0, hours: 0, minutes: 1 });
    expect(inactive).toMatchObject({ active: false, remainingMs: 0 });
  });

  it("allows Cinema City events only through the final Unlimited day", () => {
    expect(isEventWithinCinemaCityMembership(cinemaEvent("last", "2026-09-19", "22:00", "Last film"))).toBe(true);
    expect(isEventWithinCinemaCityMembership(cinemaEvent("late", "2026-09-20", "10:00", "Too late"))).toBe(false);
    expect(isEventWithinCinemaCityMembership({
      id: "concert",
      date: "2026-10-01",
      external: { calendarSummary: "Entertainment/Social" },
    })).toBe(true);
  });

  it("parses Film field and filters to future auto events from the configured calendar", () => {
    const now = new Date(2026, 5, 7, 15, 0);
    const events = [
      cinemaEvent("today", "2026-06-07", "16:50", "Dzień objawienia"),
      cinemaEvent("later", "2026-06-08", "18:00", "Dzień objawienia"),
      cinemaEvent("past", "2026-06-07", "10:00", "Pasażer"),
      {
        ...cinemaEvent("other-calendar", "2026-06-07", "19:00", "Zawodowcy"),
        external: { ...calendarExternal, calendarSummary: "Other" },
      },
      {
        ...cinemaEvent("no-tag", "2026-06-07", "20:00", "Raw repertory"),
        notes: "Film: Raw repertory",
      },
    ];

    const summary = buildCinemaCitySummary(events, { watchedCount: 6, pricePerFilm: 8.5 }, { now });

    expect(summary.todayScreenings.map((event) => event.title)).toEqual(["Dzień objawienia"]);
    expect(summary.movies).toHaveLength(1);
    expect(summary.movies[0]).toMatchObject({
      title: "Dzień objawienia",
      count: 2,
      status: "końcówka",
    });
    expect(formatCinemaStats(summary.stats, summary.monthLabel)).toBe("6 filmów obejrzanych | średnia 8,50 zł / film");
  });

  it("counts grouped future screenings and marks ending/event statuses", () => {
    const now = new Date(2026, 5, 7, 9, 0);
    const events = [
      cinemaEvent("a1", "2026-06-07", "16:00", "Zawodowcy"),
      cinemaEvent("a2", "2026-06-08", "16:00", "Zawodowcy"),
      cinemaEvent("a3", "2026-06-09", "16:00", "Zawodowcy"),
      cinemaEvent("a4", "2026-06-10", "16:00", "Zawodowcy"),
      cinemaEvent("b1", "2026-06-08", "22:10", "Pasażer"),
      cinemaEvent("b2", "2026-06-09", "22:10", "Pasażer"),
      cinemaEvent("event", "2026-06-11", "19:00", "Specjalny pokaz", "Q&A"),
    ];

    const summary = buildCinemaCitySummary(events, null, { now });

    expect(summary.movies.find((movie) => movie.title === "Zawodowcy").status).toBe("OK");
    expect(summary.movies.find((movie) => movie.title === "Pasażer").status).toBe("końcówka");
    expect(summary.movies.find((movie) => movie.title === "Specjalny pokaz").status).toBe("event");
    expect(summary).not.toHaveProperty("lastChance");
  });

  it("keeps the full future movie list", () => {
    const now = new Date(2026, 5, 7, 9, 0);
    const events = Array.from({ length: 10 }, (_, index) =>
      cinemaEvent(`movie-${index}`, "2026-06-08", "16:00", `Film ${index + 1}`)
    );

    const summary = buildCinemaCitySummary(events, null, { now });

    expect(summary.movies).toHaveLength(10);
  });

  it("keeps the full today screenings list", () => {
    const now = new Date(2026, 5, 7, 9, 0);
    const events = Array.from({ length: 8 }, (_, index) =>
      cinemaEvent(`today-${index}`, "2026-06-07", `${10 + index}:00`, `Film ${index + 1}`)
    );

    const summary = buildCinemaCitySummary(events, null, { now });

    expect(summary.todayScreenings).toHaveLength(8);
    expect(summary.todayScreenings.map((event) => event.startTime)).toEqual([
      "10:00",
      "11:00",
      "12:00",
      "13:00",
      "14:00",
      "15:00",
      "16:00",
      "17:00",
    ]);
  });

  it("formats Polish available-screening counts", () => {
    expect(formatAvailableScreeningCount(1)).toBe("1 dostępny seans");
    expect(formatAvailableScreeningCount(2)).toBe("2 dostępne seanse");
    expect(formatAvailableScreeningCount(6)).toBe("6 dostępnych seansów");
    expect(formatAvailableScreeningCount(12)).toBe("12 dostępnych seansów");
  });

  it("shows a useful auth hint when monthly stats fail on expired Google token", () => {
    expect(formatCinemaStats({
      configured: false,
      error: "Google API error: invalid_grant Token has been expired or revoked.",
    })).toBe("statystyki kina: połącz Google ponownie");
  });

  it("extracts structured fields from multiline descriptions", () => {
    expect(parseDescriptionField("Film: Pasażer\nGodzina: 22:10", "Film")).toBe("Pasażer");
  });
});
