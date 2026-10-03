import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const markup = `
  <div id="settings-runtime-summary"></div>
  <time id="settings-runtime-dashboard-time"></time>
  <span id="settings-runtime-dashboard-elapsed"></span>
  <time id="settings-runtime-boot-time"></time>
  <span id="settings-runtime-boot-elapsed"></span>
  <button id="settings-runtime-refresh"></button>`;

describe("Settings status tab", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = markup;
    vi.spyOn(globalThis, "setInterval").mockImplementation(() => 1);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("shows the dashboard and Windows start times and refreshes on demand", async () => {
    const started = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const booted = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ dashboard_started_at: started, system_booted_at: booted }),
    });
    vi.stubGlobal("fetch", fetch);

    await import("../js/settings-runtime-status.js");
    await vi.waitFor(() => expect(document.getElementById("settings-runtime-dashboard-time").dateTime).toBe(started));
    expect(document.getElementById("settings-runtime-boot-time").dateTime).toBe(booted);
    expect(document.getElementById("settings-runtime-summary").dataset.tone).toBe("saved");

    document.getElementById("settings-runtime-refresh").click();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("shows a useful fallback when the API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await import("../js/settings-runtime-status.js");
    await vi.waitFor(() => expect(document.getElementById("settings-runtime-summary").dataset.tone).toBe("error"));
    expect(document.getElementById("settings-runtime-summary").textContent).toContain("Nie udało się pobrać statusu");
  });

  it("explains that an older running API needs a restart", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    await import("../js/settings-runtime-status.js");
    await vi.waitFor(() => expect(document.getElementById("settings-runtime-summary").textContent).toContain("start-dev.cmd"));
    expect(document.getElementById("settings-runtime-summary").dataset.tone).toBe("idle");
  });
});
