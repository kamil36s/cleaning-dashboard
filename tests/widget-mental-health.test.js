import { beforeEach, describe, expect, it, vi } from "vitest";

describe("Mental Health widget", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = '<section id="mental-health-card"><div id="mental-health-root"></div></section>';
  });

  it("shows separate dimensions and never creates an aggregate score", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      dueCount: 3,
      lastCheckin: { recordedAt: "2026-09-22T10:00:00Z" },
      nextScheduled: { instrumentId: "phq9", nextDueAt: "2026-09-24T10:00:00Z" },
      registry: [{ id: "phq9", shortName: "PHQ-9" }],
      latest: [
        { instrument: { id: "phq9", shortName: "PHQ-9", scoreMax: 27 }, current: { rawScore: 9 }, changeFromPrevious: 1 },
        { instrument: { id: "who5", shortName: "WHO-5", scoreMax: 25 }, current: { rawScore: 12, normalizedScore: 48 }, changeFromPrevious: -4 },
      ],
    }) });

    await import("../js/widget-mental-health.js?test=widget");
    await Promise.resolve(); await Promise.resolve();

    const text = document.getElementById("mental-health-root").textContent;
    expect(text).toContain("Do zrobienia3");
    expect(text).toContain("PHQ-99/27");
    expect(text).toContain("WHO-548/100");
    expect(text).not.toMatch(/mental health score/i);
    expect(fetch).toHaveBeenCalledWith("/api/mental-health/overview", { cache: "no-store" });
  });

  it("renders a private backend failure without leaking details", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("sensitive-path"));
    await import("../js/widget-mental-health.js?test=error");
    await Promise.resolve(); await Promise.resolve();
    expect(document.getElementById("mental-health-root").textContent).toContain("backend jest niedostępny");
    expect(document.body.textContent).not.toContain("sensitive-path");
  });
});

