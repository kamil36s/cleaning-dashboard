import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const providers = [
  {
    provider: "codex", group: "main", label: "Codex", status: "connected",
    fiveHour: { remaining: 25, resetAt: "2026-09-12T15:00:00Z" },
    weekly: { remaining: 76, resetAt: "2026-09-19T09:00:00Z" },
    updatedAt: "2026-09-12T12:00:00Z",
    burn: { lastHour: { fiveHour: 9, weekly: 2 }, today: { fiveHour: 120, weekly: 20 }, currentWindow: { fiveHour: 68, weekly: 20 } },
    stats: { today: { activeSeconds: 5280, sessions: 4, fiveHour: 120, weekly: 20 }, thisWeek: { activeSeconds: 5280, sessions: 4, weekly: 20 } },
    quotaValue: { today: { usd: 1.13, pln: 4.22 } },
  },
  {
    provider: "antigravity", group: "gemini", label: "Gemini", status: "connected",
    fiveHour: { remaining: 100, resetAt: "2026-09-12T17:00:00Z" },
    weekly: { remaining: 99.1, resetAt: "2026-09-18T10:00:00Z" },
    updatedAt: "2026-09-12T12:00:00Z",
    burn: { lastHour: {}, today: {}, currentWindow: {} },
    stats: { today: {}, thisWeek: {} },
  },
  {
    provider: "antigravity", group: "claude_gpt", label: "Claude / GPT", status: "connected",
    fiveHour: { remaining: 0, resetAt: "2026-09-12T16:00:00Z" },
    weekly: { remaining: 3.3, resetAt: "2026-09-18T12:00:00Z" },
    updatedAt: "2026-09-12T12:00:00Z",
    burn: { lastHour: { fiveHour: 20, weekly: 7 }, today: { fiveHour: 167.8, weekly: 56.3 }, currentWindow: { fiveHour: 100, weekly: 56.3 } },
    stats: { today: { activeSeconds: 1980, sessions: 3, fiveHour: 167.8, weekly: 56.3 }, thisWeek: { activeSeconds: 1980, sessions: 3, weekly: 56.3 } },
  },
];

const history = [
  { provider: "codex", group: "main", status: "connected", checkedAt: "2026-09-12T10:00:00Z", fiveHour: { remaining: 40 }, weekly: { remaining: 80 }, fiveHourBurn: 5, weeklyBurn: 1 },
  { provider: "codex", group: "main", status: "connected", checkedAt: "2026-09-12T11:00:00Z", fiveHour: { remaining: 20 }, weekly: { remaining: 78 }, fiveHourBurn: 20, weeklyBurn: 2 },
  { provider: "codex", group: "main", status: "connected", checkedAt: "2026-09-12T11:30:00Z", fiveHour: { remaining: 100 }, weekly: { remaining: 77 }, fiveHourBurn: 0, weeklyBurn: 1 },
  { provider: "codex", group: "main", status: "connected", checkedAt: "2026-09-12T12:00:00Z", fiveHour: { remaining: 90 }, weekly: { remaining: 76 }, fiveHourBurn: 10, weeklyBurn: 1 },
  { provider: "antigravity", group: "gemini", status: "connected", checkedAt: "2026-09-12T12:00:00Z", fiveHour: { remaining: 100 }, weekly: { remaining: 99.1 }, fiveHourBurn: 0, weeklyBurn: 0 },
];

const payload = {
  providers,
  history,
  sessions: [
    { provider: "codex", group: "main", session_start: "2026-09-12T10:00:00Z", session_end: "2026-09-12T11:00:00Z", duration_seconds: 3600, status: "closed", five_hour_burn: 25, weekly_burn: 10, quotaValue: { usd: .57, pln: 2.13 } },
    { provider: "codex", group: "main", session_start: "2026-09-12T11:00:00Z", session_end: null, duration_seconds: 1800, status: "active", five_hour_burn: 20, weekly_burn: 8, quotaValue: { usd: .45, pln: 1.68 } },
    { provider: "antigravity", group: "claude_gpt", session_start: "2026-09-12T11:30:00Z", session_end: null, duration_seconds: 1200, status: "active", five_hour_burn: 50, weekly_burn: 17 },
  ],
  config: { planName: "ChatGPT Plus", vatRate: .23, usdPlnRate: 3.73, weeklyQuotaUsd: 5.66 },
};

function pageMarkup() {
  return `
    <span id="ai-page-last-sync"></span><span id="ai-page-provider-summary"></span>
    <button id="ai-page-refresh"></button><p id="ai-page-error" hidden></p>
    <div id="ai-page-summary"></div><div id="ai-page-exhaustion"></div>
    <select id="ai-page-quota-provider"></select>
    <select id="ai-page-quota-window"><option value="both">Both</option><option value="fiveHour">5h</option><option value="weekly">Weekly</option></select>
    <select id="ai-page-quota-range"><option value="5">5h</option><option value="24" selected>24h</option><option value="168">7d</option></select>
    <div id="ai-page-quota-chart"></div><div id="ai-page-quota-legend"></div>
    <select id="ai-page-burn-provider"></select>
    <select id="ai-page-burn-range"><option value="today">Today</option><option value="7d">7d</option></select>
    <div id="ai-page-burn-summary"></div><div id="ai-page-burn-chart"></div>
    <div id="ai-page-plans"></div><table><tbody id="ai-page-sessions"></tbody></table>
    <details id="ai-page-history-details"><summary><span id="ai-page-history-count"></span></summary><table><tbody id="ai-page-history"></tbody></table></details>`;
}

describe("AI Usage page", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-12T12:30:00Z"));
    document.body.innerHTML = pageMarkup();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => structuredClone(payload) });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders summary, exhaustion, charts, plans, sessions and history", async () => {
    await import("../js/ai-usage-page.js?test=page");
    await Promise.resolve();
    await Promise.resolve();

    expect(document.querySelectorAll(".ai-page-provider-card")).toHaveLength(3);
    expect(document.getElementById("ai-page-summary").textContent).toContain("Current 5h window68% used");
    expect(document.getElementById("ai-page-summary").textContent).toContain("5h consumed today120% used · 1.2× quota");
    expect(document.querySelectorAll(".ai-page-exhaustion-card")).toHaveLength(3);
    expect(document.querySelector("#ai-page-quota-chart svg")).not.toBeNull();
    expect(document.querySelectorAll("#ai-page-quota-chart .ai-chart-reset-label")).toHaveLength(1);
    expect(document.querySelectorAll("#ai-page-quota-chart .ai-chart-reset-pill")).toHaveLength(1);
    expect(document.querySelector("#ai-page-burn-chart svg")).not.toBeNull();
    expect(document.querySelectorAll(".ai-page-plan-card")).toHaveLength(3);
    expect(document.getElementById("ai-page-plans").textContent).toContain("$24.60");
    expect(document.getElementById("ai-page-plans").textContent).toContain("$123.00");
    expect(document.getElementById("ai-page-plans").textContent).toContain("$246.00");
    expect(document.querySelectorAll("#ai-page-sessions tr")).toHaveLength(3);
    expect(document.querySelectorAll("#ai-page-history tr")).toHaveLength(history.length);
    expect(document.getElementById("ai-page-history-details").hasAttribute("open")).toBe(false);
    expect(fetch).toHaveBeenCalledWith("/api/ai-usage?historyHours=168&sessionLimit=100", { cache: "no-store" });
  });

  it("hides consecutive unchanged readings for each provider", async () => {
    const repeatedPayload = structuredClone(payload);
    repeatedPayload.history = [
      { provider: "codex", group: "main", status: "connected", checkedAt: "2026-09-12T12:00:00Z", fiveHour: { remaining: 40 }, weekly: { remaining: 80 } },
      { provider: "antigravity", group: "gemini", status: "connected", checkedAt: "2026-09-12T11:59:00Z", fiveHour: { remaining: 100 }, weekly: { remaining: 99.1 } },
      { provider: "codex", group: "main", status: "connected", checkedAt: "2026-09-12T11:58:00Z", fiveHour: { remaining: 40 }, weekly: { remaining: 80 } },
      { provider: "codex", group: "main", status: "connected", checkedAt: "2026-09-12T11:57:00Z", fiveHour: { remaining: 41 }, weekly: { remaining: 80 } },
    ];
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => repeatedPayload });

    await import("../js/ai-usage-page.js?test=compact-history");
    await Promise.resolve();
    await Promise.resolve();

    expect(document.querySelectorAll("#ai-page-history tr")).toHaveLength(3);
    expect(document.getElementById("ai-page-history-count").textContent).toContain("1 unchanged reading hidden");
  });

  it("updates chart provider filters and exposes point tooltips", async () => {
    await import("../js/ai-usage-page.js?test=filters");
    await Promise.resolve();
    await Promise.resolve();

    const point = document.querySelector("#ai-page-quota-chart [data-chart-tooltip]");
    point.dispatchEvent(new Event("pointerover", { bubbles: true }));
    expect(document.querySelector("#ai-page-quota-chart .ai-page-chart-tooltip")?.textContent).toContain("Codex");

    const provider = document.getElementById("ai-page-quota-provider");
    provider.value = "antigravity:gemini";
    provider.dispatchEvent(new Event("change"));
    expect(document.querySelector("#ai-page-quota-chart svg")?.getAttribute("aria-label")).toContain("Gemini");
  });

  it("keeps dense quota history readable while preserving hover targets", async () => {
    const densePayload = structuredClone(payload);
    densePayload.history = Array.from({ length: 60 }, (_, index) => ({
      provider: "codex",
      group: "main",
      status: "connected",
      checkedAt: new Date(Date.parse("2026-09-12T11:30:00Z") + index * 60_000).toISOString(),
      fiveHour: { remaining: 100 - index },
      weekly: { remaining: 100 - index / 2 },
      fiveHourBurn: 1,
      weeklyBurn: .5,
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => densePayload });

    await import("../js/ai-usage-page.js?test=dense-history");
    await Promise.resolve();
    await Promise.resolve();

    expect(document.querySelectorAll("#ai-page-quota-chart .ai-chart-point").length).toBeLessThanOrEqual(18);
    expect(document.querySelectorAll("#ai-page-quota-chart .ai-chart-hit").length).toBe(120);
  });

  it("marks the Pro 5X upgrade and uses only post-upgrade sessions for pace", async () => {
    const upgradedPayload = structuredClone(payload);
    upgradedPayload.config = {
      ...upgradedPayload.config,
      planName: "ChatGPT Pro 5X",
      planActivatedAt: "2026-09-12T10:30:00Z",
      planChanges: [{
        provider: "codex",
        group: "main",
        activatedAt: "2026-09-12T10:30:00Z",
        fromPlanName: "ChatGPT Plus",
        toPlanName: "ChatGPT Pro 5X",
        quotaMultiplier: 5,
      }],
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => upgradedPayload });

    await import("../js/ai-usage-page.js?test=pro-upgrade");
    await Promise.resolve();
    await Promise.resolve();

    expect(document.querySelector("#ai-page-exhaustion .ai-page-pace-scope")?.textContent)
      .toContain("Pro 5X only");
    expect(document.querySelector("#ai-page-exhaustion .ai-page-pace-scope")?.textContent)
      .toContain("1 post-upgrade session");
    expect(document.querySelectorAll("#ai-page-quota-chart .ai-chart-plan-change-label")).toHaveLength(1);
    expect(document.querySelector("#ai-page-quota-chart .ai-chart-plan-change-label")?.textContent)
      .toBe("Pro 5X ×5");
    expect(document.querySelector("#ai-page-history .ai-page-history-plan-change")?.textContent)
      .toContain("Plus → Pro 5X · weekly quota ×5");
  });
});
