import { afterEach, describe, expect, it, vi } from "vitest";

describe("events API client", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it("tries the backend API origin when same-origin returns a non-JSON fallback page", async () => {
    const fetchMock = vi.fn(async (url) => {
      const target = String(url);
      if (target.startsWith("/api/events")) {
        return {
          ok: true,
          headers: { get: () => "text/html" },
          json: async () => {
            throw new Error("not_json");
          },
        };
      }

      if (target.startsWith("http://127.0.0.1:8000/api/events")) {
        return {
          ok: true,
          headers: { get: () => "application/json; charset=utf-8" },
          json: async () => ({
            events: [{ id: "google", date: "2026-05-08", title: "Google event" }],
            google: { configured: true, connected: true },
          }),
        };
      }

      return {
        ok: true,
        headers: { get: () => "application/json" },
        json: async () => [{ id: "local", date: "2026-05-28", title: "Local payday" }],
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    const { fetchDashboardEvents } = await import("../js/events-api.js");
    const payload = await fetchDashboardEvents();

    expect(payload.source).toBe("dashboard_api");
    expect(payload.google.connected).toBe(true);
    expect(payload.events).toHaveLength(1);
    expect(payload.events[0].title).toBe("Google event");
    expect(fetchMock).not.toHaveBeenCalledWith("./data/events.json", expect.anything());
  });

  it("reports Google diagnostics instead of falling back to local JSON when Google is required", async () => {
    const fetchMock = vi.fn(async (url) => {
      const target = String(url);
      if (target.startsWith("/api/events")) {
        return {
          ok: true,
          headers: { get: () => "application/json" },
          json: async () => ({
            events: [],
            google: {
              configured: true,
              connected: false,
              cachedEvents: 42,
              redirectUri: "http://127.0.0.1:8000/api/google-calendar/oauth/callback",
            },
          }),
        };
      }

      return {
        ok: true,
        headers: { get: () => "application/json" },
        json: async () => [{ id: "local", date: "2026-05-28", title: "Local payday" }],
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    const { fetchDashboardEvents } = await import("../js/events-api.js");

    await expect(fetchDashboardEvents({ requireGoogle: true, includeLocal: false }))
      .rejects
      .toMatchObject({
        message: "Google Calendar is not connected",
        google: expect.objectContaining({ configured: true, connected: false, cachedEvents: 42 }),
      });
    expect(fetchMock).not.toHaveBeenCalledWith("./data/events.json", expect.anything());
  });
});
