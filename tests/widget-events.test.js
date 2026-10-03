import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const rawEvents = [
  {
    id: "past",
    date: "2026-05-01",
    title: "Święto Pracy",
    type: "public_holiday",
    isDayOff: true,
    isShortDay: false,
    source: "local",
  },
  {
    id: "corpus-2026",
    date: "2026-06-04",
    title: "Boże Ciało",
    type: "public_holiday",
    isDayOff: true,
    isShortDay: false,
    source: "local",
  },
  {
    id: "google-trip",
    date: "2026-06-05",
    title: "Google trip",
    type: "personal_event",
    isDayOff: false,
    isShortDay: false,
    source: "google_calendar",
    external: {
      provider: "google_calendar",
      calendarId: "primary",
      eventId: "google-trip-id",
      htmlLink: "https://calendar.google.com/example",
    },
  },
  {
    id: "google-trip-copy",
    date: "2026-06-05",
    title: "Google trip",
    type: "personal_event",
    isDayOff: false,
    isShortDay: false,
    source: "google_calendar",
    external: {
      provider: "google_calendar",
      calendarId: "calendar-copy",
      calendarSummary: "Calendar",
      calendarColor: "#9aa0a6",
      eventId: "google-trip-copy-id",
      htmlLink: "https://calendar.google.com/example-copy",
    },
  },
  {
    id: "google-task-gray",
    date: "2026-06-06",
    title: "Cancel train ticket?",
    type: "personal_event",
    isDayOff: false,
    isShortDay: false,
    source: "google_calendar",
    startTime: "17:00",
    endTime: "17:30",
    notes: "Changes made to the title, description, or attachments will not be saved. To make edits, please go to: https://tasks.google.com/task/task-gray",
    external: {
      provider: "google_calendar",
      calendarId: "calendar-copy",
      calendarSummary: "Calendar",
      calendarColor: "#9aa0a6",
      eventId: "google-task-gray-id",
    },
  },
  {
    id: "google-task",
    date: "2026-06-06",
    title: "Cancel train ticket?",
    type: "task",
    isDayOff: false,
    isShortDay: false,
    source: "google_calendar",
    startTime: "17:00",
    endTime: "17:30",
    notes: "Changes made to the title, description, or attachments will not be saved. To make edits, please go to: https://tasks.google.com/task/task-yellow",
    external: {
      provider: "google_calendar",
      calendarId: "tasks",
      displayCalendarId: "tasks",
      calendarSummary: "Tasks",
      calendarColor: "#f6bf26",
      isTask: true,
      eventId: "google-task-id",
    },
  },
  {
    id: "liverpool-match",
    date: "2026-05-09",
    title: "Liverpool - Chelsea",
    type: "personal_event",
    isDayOff: false,
    isShortDay: false,
    source: "google_calendar",
    startTime: "16:00",
    endTime: "17:45",
    external: {
      provider: "google_calendar",
      calendarId: "liverpool-calendar",
      calendarSummary: "Liverpool",
      calendarColor: "#c8102e",
      eventId: "liverpool-match-id",
    },
  },
  {
    id: "past-same-day",
    date: "2026-05-08",
    title: "Already happened today",
    type: "personal_event",
    isDayOff: false,
    isShortDay: false,
    source: "google_calendar",
    startTime: "10:00",
    endTime: "10:30",
    external: {
      provider: "google_calendar",
      calendarId: "primary",
      calendarSummary: "Calendar",
      eventId: "past-same-day-id",
    },
  },
  {
    id: "trip",
    date: "2026-07-18",
    title: "Wyjazd wakacyjny",
    type: "trip",
    isDayOff: false,
    isShortDay: false,
    source: "local",
  },
];

function mockEventsPayload() {
  return {
    ok: true,
    events: rawEvents,
    google: {
      configured: true,
      connected: true,
      lastSyncAt: "2026-05-08T10:00:00",
    },
  };
}

describe("events widget", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 4, 8, 12));
    localStorage.clear();
    document.body.innerHTML = `
      <section class="card events" id="events-widget" data-display-mode="year" data-show-past-events="false">
        <div class="events-mode">
          <button data-events-mode="today"></button>
          <button data-events-mode="week"></button>
          <button data-events-mode="month"></button>
          <button data-events-mode="year"></button>
        </div>
        <div id="events-nearest"></div>
        <ul id="events-list"></ul>
        <footer id="events-foot"></footer>
      </section>
    `;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, options = {}) => {
        const target = String(url);
        if (target.startsWith("/api/events/google/upsert")) {
          return {
            ok: true,
            json: async () => ({ ok: true }),
          };
        }
        if (target.startsWith("/api/events/override")) {
          return {
            ok: true,
            json: async () => ({ ok: true }),
          };
        }
        if (target.startsWith("/api/events")) {
          const parsed = new URL(target, "http://localhost");
          const events = parsed.searchParams.get("local") === "0"
            ? rawEvents.filter((event) => event.source === "google_calendar")
            : rawEvents;
          return {
            ok: true,
            json: async () => ({ ...mockEventsPayload(), events }),
          };
        }
        return {
          ok: true,
          json: async () => rawEvents,
        };
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
    localStorage.clear();
  });

  it("renders Google Calendar events without local fixtures or predicted paydays", async () => {
    await import("../js/widget-events.js");
    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Liverpool - Chelsea");
    });

    expect(document.getElementById("events-nearest").textContent).toContain("mecz");
    expect(document.getElementById("events-nearest").textContent).toContain("16:00-17:45");
    expect(document.getElementById("events-list").textContent).toContain("Google trip");
    expect(document.getElementById("events-list").textContent.match(/Google trip/g)).toHaveLength(1);
    expect(document.getElementById("events-list").textContent).toContain("Cancel train ticket?");
    expect(document.getElementById("events-list").textContent).toContain("17:00-17:30");
    expect(document.getElementById("events-list").textContent.match(/Cancel train ticket\?/g)).toHaveLength(1);
    expect(document.getElementById("events-list").textContent).toContain("task");
    expect(document.getElementById("events-list").textContent).not.toContain("Liverpool - Chelsea");
    expect(document.getElementById("events-nearest").textContent).not.toContain("Already happened today");
    expect(document.getElementById("events-list").textContent).not.toContain("Already happened today");
    expect(document.getElementById("events-list").textContent).not.toContain("Boże Ciało");
    expect(document.getElementById("events-list").textContent).not.toContain("Wyjazd wakacyjny");
    expect(document.getElementById("events-list").textContent).not.toContain("Wypłata");
    let taskRow = Array.from(document.querySelectorAll(".evt"))
      .find((row) => row.textContent.includes("Cancel train ticket?"));
    expect(taskRow.querySelector(".evt-details").hidden).toBe(true);
    taskRow.click();
    taskRow = Array.from(document.querySelectorAll(".evt"))
      .find((row) => row.textContent.includes("Cancel train ticket?"));
    expect(taskRow.querySelector(".evt-details").hidden).toBe(false);
    expect(document.getElementById("events-list").textContent).not.toContain("Święto Pracy");
    expect(document.getElementById("events-foot").textContent).toContain("Google Calendar");
  });

  it("switches date views without the stats and insights section", async () => {
    await import("../js/widget-events.js");
    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Liverpool - Chelsea");
    });

    document.querySelector('[data-events-mode="month"]').click();
    expect(document.getElementById("events-list").textContent).not.toContain("Wyjazd wakacyjny");

    document.querySelector('[data-events-mode="year"]').click();

    expect(document.getElementById("events-stats")).toBeNull();
    expect(document.getElementById("events-insights")).toBeNull();
    expect(document.getElementById("events-list").textContent).not.toContain("Wyjazd wakacyjny");
    expect(localStorage.getItem("eventsWidget.dateView")).toBe("year");
  });

  it("auto-refreshes Google Calendar events while the dashboard stays open", async () => {
    let eventTitle = "Liverpool - Chelsea";
    fetch.mockImplementation(async (url) => {
      const target = String(url);
      if (target.startsWith("/api/events")) {
        return {
          ok: true,
          json: async () => ({
            ...mockEventsPayload(),
            events: rawEvents
              .filter((event) => event.source === "google_calendar")
              .map((event) => event.id === "liverpool-match" ? { ...event, title: eventTitle } : event),
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({ ok: true }),
      };
    });

    await import("../js/widget-events.js");
    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Liverpool - Chelsea");
    });

    eventTitle = "Liverpool - Arsenal";
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);

    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Liverpool - Arsenal");
    });
    expect(document.getElementById("events-nearest").textContent).not.toContain("Liverpool - Chelsea");
  });

  it("edits Google Calendar events from the widget", async () => {
    await import("../js/widget-events.js");
    await vi.waitFor(() => {
      expect(document.getElementById("events-list").textContent).toContain("Google trip");
    });

    document.querySelector('[data-events-mode="year"]').click();
    const googleRow = Array.from(document.querySelectorAll(".evt"))
      .find((row) => row.textContent.includes("Google trip"));
    googleRow.querySelector("[data-events-action='edit']").click();

    const overlay = document.getElementById("events-editor-overlay");
    expect(overlay.hidden).toBe(false);
    overlay.querySelector('input[name="title"]').value = "Google trip edited";
    overlay.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/events/google/upsert",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("saves dashboard-only Google event metadata without patching Google", async () => {
    await import("../js/widget-events.js");
    await vi.waitFor(() => {
      expect(document.getElementById("events-list").textContent).toContain("Google trip");
    });

    document.querySelector('[data-events-mode="year"]').click();
    const googleRow = Array.from(document.querySelectorAll(".evt"))
      .find((row) => row.textContent.includes("Google trip"));
    googleRow.querySelector("[data-events-action='edit']").click();

    const overlay = document.getElementById("events-editor-overlay");
    overlay.querySelector('select[name="type"]').value = "public_holiday";
    overlay.querySelector('select[name="type"]').dispatchEvent(new Event("change", { bubbles: true }));
    overlay.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/events/override",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/events/google/upsert",
      expect.objectContaining({ method: "POST" }),
    );
    expect(overlay.querySelector('input[name="isDayOff"]').checked).toBe(true);
  });

  it("shows Google Calendar diagnostics instead of local fallback events", async () => {
    fetch.mockImplementation(async (url) => {
      const target = String(url);
      if (target.startsWith("/api/events")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            events: [],
            google: {
              configured: true,
              connected: false,
              calendarIds: ["auto"],
              cachedEvents: 9169,
              lastSyncAt: "2026-05-10T15:46:10",
              cacheUpdatedAt: "2026-05-10T15:46:10",
              redirectUri: "http://127.0.0.1:8000/api/google-calendar/oauth/callback",
            },
          }),
        };
      }
      return {
        ok: true,
        json: async () => rawEvents,
      };
    });

    await import("../js/widget-events.js");

    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Nie udało się załadować danych z Google Calendar");
    });
    expect(document.getElementById("events-nearest").textContent).toContain("connected");
    expect(document.getElementById("events-nearest").textContent).toContain("false");
    expect(document.getElementById("events-nearest").textContent).toContain("9169");
    expect(document.getElementById("events-list").textContent).not.toContain("Wypłata");
    expect(document.getElementById("events-list").textContent).not.toContain("Boże Ciało");
    expect(document.getElementById("events-foot").textContent).toContain("lokalne dane testowe są wyłączone");
  });

  it("shows a Google re-login action when the saved token is expired or revoked", async () => {
    fetch.mockImplementation(async (url) => {
      const target = String(url);
      if (target.startsWith("/api/events")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            events: [],
            google: {
              configured: true,
              connected: true,
              calendarIds: ["auto"],
              cachedEvents: 9183,
              syncError: "Google Calendar API error 400: {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'}",
              redirectUri: "http://127.0.0.1:8000/api/google-calendar/oauth/callback",
            },
          }),
        };
      }
      return {
        ok: true,
        json: async () => rawEvents,
      };
    });

    await import("../js/widget-events.js");

    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Sesja Google wygasła");
    });
    const link = document.querySelector("a.events-error-action");
    expect(link?.textContent).toBe("Zaloguj ponownie do Google");
    expect(link?.getAttribute("href")).toBe("/api/google-calendar/auth/start");
    expect(document.getElementById("events-nearest").textContent).toContain("invalid_grant");
    expect(document.getElementById("events-list").textContent).not.toContain("Boże Ciało");
  });

  it("lets the user retry a failed Google Calendar sync from the error panel", async () => {
    let calls = 0;
    fetch.mockImplementation(async (url) => {
      const target = String(url);
      if (target.startsWith("/api/events")) {
        calls += 1;
        if (calls === 1) {
          return {
            ok: true,
            json: async () => ({
              ok: true,
              events: [],
              google: {
                configured: true,
                connected: true,
                calendarIds: ["auto"],
                cachedEvents: 9274,
                syncError: "Google Calendar API error 404: Not Found",
                redirectUri: "http://127.0.0.1:8000/api/google-calendar/oauth/callback",
              },
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            ...mockEventsPayload(),
            events: rawEvents.filter((event) => event.source === "google_calendar"),
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({ ok: true }),
      };
    });

    await import("../js/widget-events.js");

    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Ponów próbę");
    });
    document.querySelector("[data-events-action='retry-google']").click();

    await vi.waitFor(() => {
      expect(document.getElementById("events-nearest").textContent).toContain("Liverpool - Chelsea");
    });
    expect(calls).toBe(2);
  });
});
