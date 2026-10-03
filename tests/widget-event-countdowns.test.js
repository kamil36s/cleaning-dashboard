import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const events = [
  {
    id: "flight-perugia-fr2380-2026",
    date: "2026-07-13",
    title: "Flight to Perugia (FR 2380)",
    type: "trip",
    countdown: true,
    category: "album_release",
    coverImage: "/assets/events/event--flight.jpg",
    source: "local",
  },
  {
    id: "concert",
    date: "2026-07-20",
    title: "Concert",
    type: "concert",
    category: "concert",
    source: "google_calendar",
    startTime: "19:00",
    external: {
      provider: "google_calendar",
      calendarId: "primary",
      eventId: "concert-google-id",
    },
  },
  {
    id: "deadline",
    date: "2026-08-12",
    title: "Deadline",
    type: "deadline",
    countdown: true,
    category: "new_episode",
    source: "local",
  },
  {
    id: "today-episode",
    date: "2026-05-29",
    title: "New episode today",
    startTime: "20:00",
    type: "custom",
    countdown: true,
    category: "new_episode",
    coverImage: "/assets/events/event--today-episode.jpg",
    source: "local",
  },
  {
    id: "today-album",
    date: "2026-05-29",
    title: "Album release today",
    startTime: "21:00",
    type: "personal_event",
    countdown: true,
    category: "album_release",
    coverImage: "/assets/events/event--today-album.jpg",
    source: "local",
  },
  {
    id: "legacy-album",
    date: "2026-09-04",
    title: "Behemoth - I, Scvlptor album release",
    type: "personal_event",
    coverImage: "/assets/events/event--legacy-album.png",
    source: "google_calendar",
  },
  {
    id: "cinema-last-day",
    date: "2026-09-19",
    title: "Cinema film on final Unlimited day",
    type: "personal_event",
    source: "google_calendar",
    external: { calendarSummary: "Cinema City Galeria Kazimierz" },
  },
  {
    id: "cinema-after-unlimited",
    date: "2026-09-20",
    title: "Cinema film after Unlimited",
    type: "personal_event",
    source: "google_calendar",
    external: { calendarSummary: "Cinema City Galeria Kazimierz" },
  },
  {
    id: "auto-liverpool",
    date: "2026-09-18",
    title: "Liverpool - Everton",
    type: "personal_event",
    source: "google_calendar",
  },
  {
    id: "auto-canadiens",
    date: "2026-09-19",
    title: "Montreal Canadiens vs Toronto Maple Leafs",
    type: "personal_event",
    source: "google_calendar",
    startTime: "01:00",
  },
  {
    id: "auto-canadiens-reversed",
    date: "2026-09-19",
    title: "Toronto Maple Leafs vs Montreal Canadiens",
    type: "personal_event",
    source: "google_calendar",
    startTime: "01:00",
  },
  {
    id: "auto-full-moon",
    date: "2026-09-20",
    title: "Full moon 18:49",
    type: "personal_event",
    source: "google_calendar",
  },
  {
    id: "auto-full-moon-next",
    date: "2026-10-20",
    title: "Full moon 05:12",
    type: "personal_event",
    source: "google_calendar",
  },
];

describe("event countdowns widget", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 4, 29, 15, 0));
    window.history.pushState({}, "", "/cleaning-dashboard/");
    localStorage.clear();
    document.body.innerHTML = `
      <section class="card event-countdowns" id="event-countdowns-widget">
        <div class="event-countdowns-filter-wrap">
          <button id="event-countdowns-filter" type="button"></button>
          <div id="event-countdowns-filter-menu" hidden></div>
        </div>
        <select id="event-countdowns-select"></select>
        <select id="event-countdowns-category"></select>
        <button id="event-countdowns-add" type="button"></button>
        <button id="event-countdowns-create" type="button"></button>
        <button id="event-countdowns-create-category" type="button"></button>
        <button id="event-countdowns-refresh" type="button"></button>
        <div id="event-countdowns-list"></div>
        <footer id="event-countdowns-foot"></footer>
      </section>
    `;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, options = {}) => {
        const target = String(url);
        if (target.startsWith("/api/events/categories")) {
          const request = JSON.parse(options.body);
          const label = request.label;
          const categoryId = request.id || "film_premiere";
          const categories = [
            { id: "album_release", label: "Album release", custom: false },
            { id: "match", label: "Match", custom: false },
            { id: "hockey_match", label: "Mecz hokejowy", custom: false },
            { id: "stadium_match", label: "Match (going to the stadium)", custom: false },
            { id: "concert", label: "Concert", custom: false },
            { id: "new_episode", label: "New episode", custom: false },
            { id: "phases_of_the_moon", label: "Phases of the Moon", custom: false },
            { id: "film_premiere", label: "Film premiere", custom: true },
          ].map((category) => category.id === categoryId ? { ...category, label } : category);
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({
              ok: true,
              category: categories.find((category) => category.id === categoryId),
              categories,
            }),
          };
        }
        if (target.startsWith("/api/events/countdown-cover")) {
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({
              ok: true,
              url: "/assets/events/event--deadline.png?v=123",
              event: { id: "deadline", coverImage: "/assets/events/event--deadline.png?v=123" },
            }),
          };
        }
        if (target.startsWith("/api/events/local/upsert")) {
          const saved = JSON.parse(options.body).event;
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({ ok: true, event: { id: "saved-local-event", ...saved, source: "local" } }),
          };
        }
        if (target.startsWith("/api/events")) {
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({
              ok: true,
              events,
              countdownCategoryCovers: {
                phases_of_the_moon: "/assets/events/shared-full-moon.png",
              },
              google: { configured: true, connected: true },
            }),
          };
        }
        return {
          ok: true,
          headers: { get: () => "application/json" },
          json: async () => ({ ok: true }),
        };
      }),
    );
    Object.defineProperty(globalThis.navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(async () => undefined) },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
    localStorage.clear();
  });

  it("renders countdown-enabled events from the shared events feed", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.getElementById("event-countdowns-list").textContent)
        .toContain("Flight to Perugia (FR 2380)");
    });
    expect(document.getElementById("event-countdowns-foot").textContent)
      .toContain("dashboard + Google Calendar");
    expect(document.getElementById("event-countdowns-select").textContent)
      .toContain("Concert");
  });

  it("requests a current Google Calendar sync instead of repeatedly reading stale cache", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(fetch.mock.calls.some(([url]) => String(url).includes("/api/events?sync=1"))).toBe(true);
    });
  });

  it("does not offer Cinema City screenings after Unlimited expires", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.getElementById("event-countdowns-select").textContent)
        .toContain("Cinema film on final Unlimited day");
    });
    expect(document.getElementById("event-countdowns-select").textContent)
      .not.toContain("Cinema film after Unlimited");
  });

  it("adds a persistent custom countdown category", async () => {
    await import("../js/widget-event-countdowns.js");
    document.getElementById("event-countdowns-create-category").click();
    const form = document.getElementById("event-countdown-category-form");
    form.elements.label.value = "Film premiere";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.getElementById("event-countdowns-category").textContent).toContain("Film premiere");
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/events/categories",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"label":"Film premiere"'),
      }),
    );
  });

  it("automatically adds matching sports and moon events once, without cover art", async () => {
    localStorage.setItem("eventsCountdown.selectedIds.v1", JSON.stringify(["auto-liverpool"]));
    localStorage.setItem("eventsCountdown.rangeDays.v1", "400");
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.querySelector('[data-countdown-id="auto-liverpool"]')).toBeTruthy();
    });
    expect(document.querySelectorAll('[data-countdown-id="auto-liverpool"]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-countdown-category="hockey_match"]')).toHaveLength(1);
    expect(document.querySelector('[data-countdown-id="auto-liverpool"]')?.textContent).toContain("Match");
    expect(document.querySelector('[data-countdown-id="auto-canadiens"]')?.textContent).toContain("Mecz hokejowy");
    expect(document.querySelector('[data-countdown-id="auto-full-moon"]')?.textContent).toContain("Phases of the Moon");
    expect(document.querySelector('[data-countdown-id="auto-full-moon"]')?.textContent).toContain("18:49");
    expect(document.querySelector('[data-countdown-id="auto-full-moon"]')?.textContent).not.toContain("Full moon 18:49");
    expect(document.querySelector('[data-countdown-id="auto-liverpool"] img')).toBeNull();
    expect(document.querySelector('[data-countdown-id="auto-canadiens"] img')).toBeNull();
    expect(document.querySelector('[data-countdown-id="auto-full-moon"] img')?.getAttribute("src"))
      .toBe("/cleaning-dashboard/assets/events/shared-full-moon.png");
    expect(document.querySelector('[data-countdown-id="auto-full-moon-next"] img')?.getAttribute("src"))
      .toBe("/cleaning-dashboard/assets/events/shared-full-moon.png");
  });

  it("edits a category name through the hidden Shift-click action", async () => {
    await import("../js/widget-event-countdowns.js");
    document.getElementById("event-countdowns-create-category").dispatchEvent(new MouseEvent("click", {
      bubbles: true,
      shiftKey: true,
    }));
    const form = document.getElementById("event-countdown-category-edit-form");
    form.elements.category.value = "match";
    form.elements.category.dispatchEvent(new Event("change", { bubbles: true }));
    form.elements.label.value = "Mecz piłkarski";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.getElementById("event-countdowns-filter-menu").textContent).toContain("Mecz piłkarski");
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/events/categories",
      expect.objectContaining({ body: expect.stringContaining('"id":"match"') }),
    );
  });

  it("renders cover art and keeps the image prompt hidden behind copy", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.querySelector('[data-countdown-id="flight-perugia-fr2380-2026"] .event-countdown-cover img')?.getAttribute("src"))
        .toBe("/cleaning-dashboard/assets/events/event--flight.jpg");
    });

    expect(document.querySelector(".event-countdown-prompt-text")).toBeNull();
    const coveredCard = document.querySelector('[data-countdown-id="flight-perugia-fr2380-2026"]');
    expect(coveredCard.querySelector("[data-countdown-copy-prompt]")).toBeNull();
    expect(coveredCard.querySelector("[data-countdown-upload]").textContent).toBe("");
    expect(coveredCard.textContent).not.toContain("Zmien cover");
    expect(coveredCard.textContent).not.toContain("Upload cover");

    const emptyCoverCard = document.querySelector('[data-countdown-id="deadline"]');
    emptyCoverCard.querySelector("[data-countdown-copy-prompt]").click();

    await vi.waitFor(() => {
      expect(globalThis.navigator.clipboard.writeText).toHaveBeenCalledWith(
        expect.stringContaining("Deadline"),
      );
    });
    const copiedPrompt = globalThis.navigator.clipboard.writeText.mock.calls[0][0];
    expect(copiedPrompt).toContain("Design a clean 16:9 event cover");
    expect(copiedPrompt).toContain("Text, logo, venue name");
    expect(copiedPrompt).not.toContain("No text");
    expect(copiedPrompt).not.toContain("no logo");
    expect(copiedPrompt).not.toContain("cinematic");
  });

  it("uploads cover art to the project asset endpoint and hides prompt copy afterwards", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.querySelector('[data-countdown-id="deadline"] [data-countdown-upload]')).toBeTruthy();
    });

    document.querySelector('[data-countdown-id="deadline"] [data-countdown-upload]').click();
    const input = document.querySelector('#event-countdowns-widget input[type="file"]');
    const file = new File(["cover-bytes"], "deadline.png", { type: "image/png" });
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [file],
    });
    input.dispatchEvent(new Event("change", { bubbles: true }));

    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/events/countdown-cover",
        expect.objectContaining({ method: "POST" }),
      );
    });
    await vi.waitFor(() => {
      const card = document.querySelector('[data-countdown-id="deadline"]');
      expect(card.querySelector(".event-countdown-cover img")?.getAttribute("src"))
        .toBe("/cleaning-dashboard/assets/events/event--deadline.png?v=123");
      expect(card.querySelector("[data-countdown-copy-prompt]")).toBeNull();
    });
    expect(document.getElementById("event-countdowns-foot").textContent)
      .toContain("Cover zapisany w assets/events");
  });

  it("removes an assigned cover and restores prompt copy and upload", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.querySelector(
        '[data-countdown-id="flight-perugia-fr2380-2026"] [data-countdown-delete-cover]',
      )).toBeTruthy();
    });

    document.querySelector(
      '[data-countdown-id="flight-perugia-fr2380-2026"] [data-countdown-delete-cover]',
    ).click();

    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/events/countdown-cover",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"remove":true'),
        }),
      );
    });
    await vi.waitFor(() => {
      const card = document.querySelector('[data-countdown-id="flight-perugia-fr2380-2026"]');
      expect(card.querySelector(".event-countdown-cover img")).toBeNull();
      expect(card.querySelector("[data-countdown-copy-prompt]")).toBeTruthy();
      expect(card.querySelector("[data-countdown-upload]")).toBeTruthy();
    });
    expect(document.getElementById("event-countdowns-foot").textContent)
      .toContain("możesz skopiować prompt");
  });

  it("updates countdown numbers without rebuilding hovered controls", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.querySelector(
        '[data-countdown-id="flight-perugia-fr2380-2026"] [data-countdown-upload]',
      )).toBeTruthy();
    });

    const uploadButton = document.querySelector(
      '[data-countdown-id="flight-perugia-fr2380-2026"] [data-countdown-upload]',
    );
    await vi.advanceTimersByTimeAsync(1000);

    expect(document.querySelector(
      '[data-countdown-id="flight-perugia-fr2380-2026"] [data-countdown-upload]',
    )).toBe(uploadButton);
  });

  it("lets the user add another event countdown locally", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.getElementById("event-countdowns-select").textContent)
        .toContain("Concert");
    });

    const select = document.getElementById("event-countdowns-select");
    select.value = "concert";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    document.getElementById("event-countdowns-add").click();

    await vi.waitFor(() => {
      expect(document.getElementById("event-countdowns-list").textContent).toContain("Concert");
      expect(JSON.parse(localStorage.getItem("eventsCountdown.selectedIds.v1"))).toContain("concert");
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/events/override",
      expect.objectContaining({ body: expect.stringContaining('"category":"concert"') }),
    );
  });

  it("filters countdown cards by their required category", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.querySelector('[data-countdown-id="flight-perugia-fr2380-2026"]')).toBeTruthy();
    });
    const filter = document.getElementById("event-countdowns-filter");
    filter.click();
    const all = document.querySelector('#event-countdowns-filter-menu input[value="all"]');
    all.checked = false;
    all.dispatchEvent(new Event("change", { bubbles: true }));
    const newEpisode = document.querySelector('#event-countdowns-filter-menu input[value="new_episode"]');
    newEpisode.checked = true;
    newEpisode.dispatchEvent(new Event("change", { bubbles: true }));

    expect(document.getElementById("event-countdowns-list").textContent).toContain("New episode today");
    expect(document.getElementById("event-countdowns-list").textContent).toContain("Deadline");
    expect(document.getElementById("event-countdowns-list").textContent).not.toContain("Flight to Perugia");
    expect(JSON.parse(localStorage.getItem("eventsCountdown.categoryFilter.v1")))
      .not.toContain("new_episode");
  });

  it("changes and persists the category of an existing countdown", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.querySelector('[data-countdown-id="deadline"] [data-countdown-category-edit]')).toBeTruthy();
    });
    const trigger = document.querySelector('[data-countdown-id="deadline"] [data-countdown-category-edit]');
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger.textContent).toBe("New episode");
    trigger.click();
    const form = document.getElementById("event-countdown-category-change-form");
    form.elements.category.value = "album_release";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/events/local/upsert",
        expect.objectContaining({ body: expect.stringContaining('"category":"album_release"') }),
      );
    });
    await vi.waitFor(() => {
      expect(document.querySelector('[data-countdown-id="deadline"] [data-countdown-category-edit]').textContent)
        .toBe("Album release");
    });
  });

  it("restores a legacy selected countdown by inferring its category", async () => {
    localStorage.setItem("eventsCountdown.selectedIds.v1", JSON.stringify(["legacy-album"]));
    localStorage.setItem("eventsCountdown.rangeDays.v1", "400");
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      const card = document.querySelector('[data-countdown-id="legacy-album"]');
      expect(card?.textContent).toContain("Behemoth - I, Scvlptor album release");
      expect(card?.textContent).toContain("Album release");
    });
  });

  it("creates a dashboard-only event without writing to Google Calendar", async () => {
    await import("../js/widget-event-countdowns.js");
    document.getElementById("event-countdowns-create").click();

    const form = document.getElementById("event-countdown-create-form");
    form.elements.title.value = "Severance S03E01";
    form.elements.date.value = "2026-09-01";
    form.elements.category.value = "new_episode";
    form.elements.addToGoogle.checked = false;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/events/local/upsert",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"category":"new_episode"'),
        }),
      );
    });
    expect(fetch.mock.calls.some(([url]) => String(url) === "/api/events/google/upsert")).toBe(false);
  });

  it("lets the notification-center list mark one event as read", async () => {
    localStorage.setItem("eventsCountdown.todayNoticeSeen.v1", "2026-05-29");
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.getElementById("dashboard-event-notifications-count")?.textContent).toBe("2");
    });
    const trigger = document.getElementById("dashboard-event-notifications-trigger");
    trigger.click();
    document.querySelector('[data-event-notification-id="today-episode"]').click();

    expect(document.getElementById("dashboard-event-notifications-count").textContent).toBe("1");
    expect(document.querySelector('[data-event-notification-id="today-episode"]')?.classList)
      .toContain("is-read");
    expect(document.querySelector('[data-event-notification-id="today-album"]')?.classList)
      .not.toContain("is-read");
    const panel = document.getElementById("dashboard-event-notifications-panel");
    expect(panel.hidden).toBe(false);

    document.body.click();
    expect(panel.hidden).toBe(true);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("shows AI Usage resets in the existing notification center", async () => {
    localStorage.setItem("eventsCountdown.todayNoticeSeen.v1", "2026-05-29");
    await import("../js/widget-event-countdowns.js");
    const { addDashboardNotification } = await import("../js/dashboard-notifications-store.js");

    await vi.waitFor(() => {
      expect(document.getElementById("dashboard-event-notifications-count")?.textContent).toBe("2");
    });
    addDashboardNotification({
      id: "ai-usage:codex:main:fiveHour:test-reset",
      category: "AI Usage",
      title: "Codex 5h limit reset — 100% available",
      targetId: "ai-usage-card",
    });

    expect(document.getElementById("dashboard-event-notifications-count").textContent).toBe("3");
    const notification = document.querySelector('[data-dashboard-notification-id="ai-usage:codex:main:fiveHour:test-reset"]');
    expect(notification.textContent).toContain("AI Usage");
    expect(notification.textContent).toContain("Codex 5h limit reset");
    notification.click();
    expect(document.querySelector('[data-dashboard-notification-id="ai-usage:codex:main:fiveHour:test-reset"]')?.classList)
      .toContain("is-read");
    expect(document.getElementById("dashboard-event-notifications-count").textContent).toBe("2");
  });

  it("shows today's events one by one and tracks which notifications were read", async () => {
    await import("../js/widget-event-countdowns.js");

    await vi.waitFor(() => {
      expect(document.getElementById("event-today-notification-overlay")?.textContent)
        .toContain("New episode today");
    });
    expect(document.querySelector(".event-today-notification-cover img")?.getAttribute("src"))
      .toBe("/cleaning-dashboard/assets/events/event--today-episode.jpg");
    const trigger = document.getElementById("dashboard-event-notifications-trigger");
    expect(trigger.hidden).toBe(false);
    const count = document.getElementById("dashboard-event-notifications-count");
    expect(count.textContent).toBe("2");

    document.querySelector("[data-event-today-close]").click();
    expect(document.getElementById("event-today-notification-overlay")?.textContent)
      .toContain("Album release today");
    expect(count.textContent).toBe("1");
    expect(JSON.parse(localStorage.getItem("eventsCountdown.todayReadIds.v1"))).toEqual({
      date: "2026-05-29",
      ids: ["today-episode"],
    });

    document.querySelector("[data-event-today-close]").click();
    expect(document.getElementById("event-today-notification-overlay")).toBeNull();
    expect(count.textContent).toBe("0");
    expect(count.hidden).toBe(true);
    expect(localStorage.getItem("eventsCountdown.todayNoticeSeen.v1")).toBe("2026-05-29");

    trigger.click();
    expect(document.getElementById("dashboard-event-notifications-panel").textContent)
      .toContain("New episode today");
    expect(document.getElementById("dashboard-event-notifications-panel").textContent)
      .toContain("Album release today");
    expect(document.querySelectorAll(".dashboard-event-notification-item.is-read")).toHaveLength(2);
  });
});
