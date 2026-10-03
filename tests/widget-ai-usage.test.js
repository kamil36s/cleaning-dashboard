import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const payload = {
  providers: [
    {
      provider: "codex", group: "main", label: "Codex", status: "connected",
      fiveHour: { remaining: 71, resetAt: "2026-09-12T18:00:00Z" },
      weekly: { remaining: 63, resetAt: "2026-09-16T18:00:00Z" },
      updatedAt: "2026-09-12T12:00:00Z",
      burn: { lastHour: { weekly: 4 }, currentWindow: { fiveHour: 23, weekly: 31 } },
      stats: { today: { activeSeconds: 2520, sessions: 1, fiveHour: 8, weekly: 4 }, thisWeek: { activeSeconds: 2520, sessions: 1, weekly: 4 } },
      quotaValue: { usedUsd: 2.09, remainingUsd: 3.57, today: { usd: .23, pln: .86 } },
    },
    {
      provider: "antigravity", group: "gemini", label: "Gemini", status: "unavailable",
      fiveHour: null, weekly: null, updatedAt: null,
      burn: { lastHour: {}, currentWindow: {} },
      stats: { today: {}, thisWeek: {} },
    },
    {
      provider: "antigravity", group: "claude_gpt", label: "Claude / GPT", status: "connected",
      fiveHour: { remaining: 11 }, weekly: { remaining: 70 }, updatedAt: "2026-09-12T12:00:00Z",
      burn: { lastHour: {}, currentWindow: {} },
      stats: { today: { weekly: 9 }, thisWeek: {} },
    },
  ],
  sessions: [{
    provider: "codex", group: "main", session_start: "2026-09-12T11:18:00Z",
    session_end: "2026-09-12T12:00:00Z", status: "closed", duration_seconds: 2520,
    five_hour_burn: 12, weekly_burn: 4, quotaValue: { usd: .23, pln: .86 },
  }],
  history: [],
};

describe("AI Usage widget", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    localStorage.clear();
    document.body.innerHTML = `
      <section id="ai-usage-card">
        <a id="ai-usage-details" href="./ai-usage.html">Open details</a>
        <div id="ai-usage-root"></div>
      </section>`;
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("renders real quota and marks a missing bucket unavailable", async () => {
    await import("../js/widget-ai-usage.js?test=render");
    await Promise.resolve();
    await Promise.resolve();

    const text = document.querySelector("#ai-usage-root").textContent;
    expect(text).toContain("71%");
    expect(text).toContain("63%");
    expect(text).toContain("unavailable");
    expect(text).toContain("42m");
    expect(document.querySelector('[data-state="critical"]')).not.toBeNull();
  });

  it("links to the dedicated details page instead of creating a dialog", async () => {
    await import("../js/widget-ai-usage.js?test=detail");
    await Promise.resolve();
    await Promise.resolve();
    expect(document.querySelector("#ai-usage-details").getAttribute("href")).toBe("./ai-usage.html");
    expect(document.querySelector("#ai-usage-dialog")).toBeNull();
  });

  it("counts down every available provider window locally", async () => {
    vi.setSystemTime(new Date("2026-09-12T12:00:00Z"));
    const connectedPayload = structuredClone(payload);
    Object.assign(connectedPayload.providers[0], {
      fiveHour: { remaining: 71, resetAt: "2026-09-12T15:17:00Z" },
      weekly: { remaining: 63, resetAt: "2026-09-17T09:00:00Z" },
    });
    Object.assign(connectedPayload.providers[1], {
      status: "connected",
      fiveHour: { remaining: 100, resetAt: "2026-09-12T12:42:00Z" },
      weekly: { remaining: 99.1, resetAt: "2026-09-14T15:00:00Z" },
    });
    Object.assign(connectedPayload.providers[2], {
      fiveHour: { remaining: 11, resetAt: "2026-09-12T12:09:32Z" },
      weekly: { remaining: 70, resetAt: "2026-09-12T13:05:00Z" },
    });
    global.fetch.mockResolvedValue({ ok: true, json: async () => connectedPayload });

    await import("../js/widget-ai-usage.js?test=countdown");
    await Promise.resolve();
    await Promise.resolve();

    const cards = [...document.querySelectorAll(".ai-usage-provider-compact")];
    expect(cards[0].textContent).toContain("Resets in");
    expect([...cards[0].querySelectorAll("time")].map((node) => node.textContent)).toEqual(["3h 17m", "4d 21h"]);
    expect([...cards[1].querySelectorAll("time")].map((node) => node.textContent)).toEqual(["42m", "2d 3h"]);
    expect([...cards[2].querySelectorAll("time")].map((node) => node.textContent)).toEqual(["9m 32s", "1h 5m"]);

    await vi.advanceTimersByTimeAsync(1000);
    expect(cards[2].querySelector("time").textContent).toBe("9m 31s");
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("shows no invented countdown for unavailable or missing reset data", async () => {
    await import("../js/widget-ai-usage.js?test=countdown-unavailable");
    await Promise.resolve();
    await Promise.resolve();

    const cards = [...document.querySelectorAll(".ai-usage-provider-compact")];
    expect([...cards[1].querySelectorAll("time")].map((node) => node.textContent)).toEqual(["—", "—"]);
    expect([...cards[2].querySelectorAll("time")].map((node) => node.textContent)).toEqual(["—", "—"]);
  });

  it("adds one dashboard notification for every 0 to 100 quota reset", async () => {
    const beforeReset = structuredClone(payload);
    const afterReset = structuredClone(payload);
    [beforeReset, afterReset].forEach((value) => {
      value.providers.forEach((provider) => {
        provider.status = "connected";
        provider.fiveHour = { remaining: 0, resetAt: "2026-09-12T18:00:00Z" };
        provider.weekly = { remaining: 0, resetAt: "2026-09-19T09:00:00Z" };
      });
    });
    afterReset.providers.forEach((provider) => {
      provider.fiveHour = { remaining: 100, resetAt: "2026-09-12T23:00:00Z" };
      provider.weekly = { remaining: 100, resetAt: "2026-09-26T09:00:00Z" };
      provider.updatedAt = "2026-09-12T18:01:00Z";
    });
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => beforeReset })
      .mockResolvedValue({ ok: true, json: async () => afterReset });

    await import("../js/widget-ai-usage.js?test=reset-notifications");
    await Promise.resolve();
    await Promise.resolve();
    expect(JSON.parse(localStorage.getItem("dashboard.notifications.v1") || "[]")).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(60_000);
    const notifications = JSON.parse(localStorage.getItem("dashboard.notifications.v1") || "[]");
    expect(notifications).toHaveLength(6);
    expect(notifications.map((item) => item.title)).toEqual(expect.arrayContaining([
      "Codex 5h limit reset — 100% available",
      "Codex weekly limit reset — 100% available",
      "Gemini 5h limit reset — 100% available",
      "Gemini weekly limit reset — 100% available",
      "Claude / GPT 5h limit reset — 100% available",
      "Claude / GPT weekly limit reset — 100% available",
    ]));

    await vi.advanceTimersByTimeAsync(60_000);
    expect(JSON.parse(localStorage.getItem("dashboard.notifications.v1") || "[]")).toHaveLength(6);
  });
});
