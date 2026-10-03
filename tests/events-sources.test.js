import { describe, expect, it } from "vitest";
import { enrichEvents, getVisibleEvents, normalizeEvents } from "../js/events-sources.js";

describe("events source normalization", () => {
  it("sorts same-day events by start time before title", () => {
    const events = enrichEvents(
      normalizeEvents([
        {
          id: "late",
          date: "2026-05-08",
          title: "Late task",
          type: "task",
          startTime: "17:00",
        },
        {
          id: "all-day",
          date: "2026-05-08",
          title: "All day note",
          type: "custom",
        },
        {
          id: "early",
          date: "2026-05-08",
          title: "Early meeting",
          type: "personal_event",
          startTime: "08:30",
        },
      ]),
      { today: new Date(2026, 4, 8) },
    );

    expect(events.map((event) => event.id)).toEqual(["early", "late", "all-day"]);
  });

  it("filters same-day timed events using the current time", () => {
    const referenceDate = new Date(2026, 4, 8, 12, 0);
    const events = enrichEvents(
      normalizeEvents([
        {
          id: "past-time",
          date: "2026-05-08",
          title: "Morning event",
          type: "personal_event",
          startTime: "10:00",
        },
        {
          id: "future-time",
          date: "2026-05-08",
          title: "Afternoon event",
          type: "personal_event",
          startTime: "15:00",
        },
        {
          id: "all-day",
          date: "2026-05-08",
          title: "All day event",
          type: "custom",
        },
      ]),
      { today: referenceDate },
    );

    expect(getVisibleEvents(events, { referenceDate }).map((event) => event.id))
      .toEqual(["future-time", "all-day"]);
  });

  it("keeps countdown metadata during normalization", () => {
    const [event] = normalizeEvents([
      {
        id: "flight",
        date: "2026-07-13",
        title: "Flight to Perugia (FR 2380)",
        type: "trip",
        countdown: true,
        category: "album_release",
        coverImage: "/assets/events/event--flight.jpg",
      },
    ]);

    expect(event.countdown).toBe(true);
    expect(event.category).toBe("album_release");
    expect(event.coverImage).toBe("/assets/events/event--flight.jpg");
  });

  it("preserves valid user-defined countdown categories", () => {
    const [event] = normalizeEvents([{
      id: "film",
      date: "2026-09-18",
      title: "Film premiere",
      type: "custom",
      countdown: true,
      category: "film_premiere",
    }]);

    expect(event.category).toBe("film_premiere");
  });

  it("automatically enables team, hockey, and full-moon countdowns without assigning covers", () => {
    const normalized = normalizeEvents([
      { id: "wieczysta", date: "2026-09-18", title: "Wieczysta Kraków - Cracovia" },
      { id: "liverpool", date: "2026-09-18", title: "Liverpool - Everton" },
      { id: "wisla", date: "2026-09-18", title: "Wisła Kraków - Ruch Chorzów" },
      { id: "lech", date: "2026-09-18", title: "Lech Poznań - Legia" },
      { id: "jagiellonia", date: "2026-09-18", title: "Jagiellonia - Raków" },
      { id: "hockey", date: "2026-09-19", title: "Montreal Canadiens vs Toronto" },
      { id: "hockey-reversed", date: "2026-09-19", title: "Toronto vs Montreal Canadiens" },
      { id: "moon", date: "2026-09-20", title: "Full moon 18:49" },
    ]);

    expect(normalized.map(({ countdown, category, coverImage }) => ({ countdown, category, coverImage })))
      .toEqual([
        { countdown: true, category: "match", coverImage: undefined },
        { countdown: true, category: "match", coverImage: undefined },
        { countdown: true, category: "match", coverImage: undefined },
        { countdown: true, category: "match", coverImage: undefined },
        { countdown: true, category: "match", coverImage: undefined },
        { countdown: true, category: "hockey_match", coverImage: undefined },
        { countdown: false, category: undefined, coverImage: undefined },
        { countdown: true, category: "phases_of_the_moon", coverImage: undefined },
      ]);
    expect(normalized.at(-1)).toMatchObject({ title: "Full Moon", startTime: "18:49" });
  });

  it("keeps a manually selected category on an automatically recognized event", () => {
    const [event] = normalizeEvents([{
      id: "manual-liverpool",
      date: "2026-09-20",
      title: "Liverpool - Everton",
      countdown: true,
      category: "new_episode",
    }]);

    expect(event).toMatchObject({ countdown: true, category: "new_episode" });
  });

  it("migrates legacy countdown categories from titles and calendars", () => {
    const normalized = normalizeEvents([
      {
        id: "album",
        date: "2026-08-21",
        title: "The Afghan Whigs - Soft Control album release",
        type: "personal_event",
      },
      {
        id: "match",
        date: "2026-08-23",
        title: "⚽️ Newcastle United - Liverpool",
        type: "personal_event",
      },
      {
        id: "concert",
        date: "2026-09-12",
        title: "Antimatter + Sleeping Pulse",
        type: "personal_event",
        external: { calendarSummary: "Entertainment/Social" },
      },
    ]);

    expect(normalized.map((event) => event.category))
      .toEqual(["album_release", "match", "concert"]);
  });

  it("normalizes Google dateTime values into local date and time", async () => {
    const { normalizeEvents: normalizeGoogleEvents } = await import("../js/events-sources.js");
    const [event] = normalizeGoogleEvents(
      [
        {
          id: "match",
          summary: "Mx Mexico - za South Africa",
          start: { dateTime: "2026-06-11T19:00:00Z" },
          end: { dateTime: "2026-06-11T20:45:00Z" },
        },
      ],
      { source: "google_calendar" },
    );

    const expectedStart = new Date("2026-06-11T19:00:00Z");
    const expectedEnd = new Date("2026-06-11T20:45:00Z");
    const expectedStartTime = `${String(expectedStart.getHours()).padStart(2, "0")}:${String(expectedStart.getMinutes()).padStart(2, "0")}`;
    const expectedEndTime = `${String(expectedEnd.getHours()).padStart(2, "0")}:${String(expectedEnd.getMinutes()).padStart(2, "0")}`;

    expect(event.date).toBe([
      expectedStart.getFullYear(),
      String(expectedStart.getMonth() + 1).padStart(2, "0"),
      String(expectedStart.getDate()).padStart(2, "0"),
    ].join("-"));
    expect(event.startTime).toBe(expectedStartTime);
    expect(event.endTime).toBe(expectedEndTime);
  });
});
