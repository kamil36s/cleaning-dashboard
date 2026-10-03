import path from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function setupDom() {
  document.body.innerHTML = `
    <section id="budget-card" class="is-private">
      <div class="budget-sensitive" id="budget-source-meta"></div><button id="budget-privacy-toggle"></button><button id="budget-reset"></button>
      <strong class="budget-sensitive" id="budget-safe-to-spend"></strong><small class="budget-sensitive" id="budget-safe-daily"></small>
      <strong class="budget-sensitive" id="budget-spending"></strong><strong class="budget-sensitive" id="budget-net"></strong>
      <strong class="budget-sensitive" id="budget-savings"></strong><small class="budget-sensitive" id="budget-savings-rate"></small>
      <strong class="budget-sensitive" id="budget-upcoming"></strong>
      <section id="budget-goal" hidden><span class="budget-sensitive" id="budget-goal-name"></span><strong class="budget-sensitive" id="budget-goal-percent"></strong><div class="finance-widget-progress"><i id="budget-goal-progress"></i></div><small class="budget-sensitive" id="budget-goal-context"></small></section>
    </section>`;
}

const payload = {
  safeToSpend: { safeToSpend: 2180, safePerDay: 156, horizonDate: "2026-09-30" },
  expenses: 3420, netCashFlow: 1200, savings: 900, savingsRate: 18,
  upcoming30Days: 483,
  freshness: { latestTransactionDate: "2026-09-16", status: "fresh" },
  goals: [{ name: "Fundusz", primary: true, progressPercent: 12, allocated: 6000, target: 50000 }],
};

async function importFresh() {
  const url = pathToFileURL(path.resolve("js/widget-budget.js")).href;
  return import(`${url}?t=${Date.now()}-${Math.random()}`);
}

describe("compact Finance widget", () => {
  beforeEach(() => {
    setupDom();
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, data: payload }) }));
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders safe-to-spend, current status, upcoming costs, and primary goal", async () => {
    await importFresh();
    await vi.waitFor(() => expect(document.getElementById("budget-safe-to-spend").textContent.replace(/\s/g, "")).toContain("2180,00"));
    expect(document.getElementById("budget-spending").textContent.replace(/\s/g, "")).toContain("3420,00");
    expect(document.getElementById("budget-upcoming").textContent).toContain("483,00");
    expect(document.getElementById("budget-goal").hidden).toBe(false);
    expect(document.getElementById("budget-goal-progress").style.width).toBe("12%");
    expect(document.querySelector(".budget-transaction")).toBeNull();
  });

  it("refreshes the overview without posting a replacement snapshot", async () => {
    await importFresh();
    await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    document.getElementById("budget-reset").click();
    await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    expect(globalThis.fetch).toHaveBeenLastCalledWith("/api/budget/overview", { cache: "no-store" });
  });

  it("hides every sensitive value by default and keeps the choice during refresh", async () => {
    await importFresh();
    await vi.waitFor(() => expect(document.getElementById("budget-safe-to-spend").textContent.replace(/\s/g, "")).toContain("2180,00"));
    const card = document.getElementById("budget-card");
    const toggle = document.getElementById("budget-privacy-toggle");
    expect(card.classList.contains("is-private")).toBe(true);
    expect(toggle.textContent).toBe("Pokaż dane");
    expect([...card.querySelectorAll(".budget-sensitive")].every((element) => element.getAttribute("aria-hidden") === "true")).toBe(true);

    toggle.click();
    expect(card.classList.contains("is-private")).toBe(false);
    expect(toggle.textContent).toBe("Ukryj dane");
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    document.getElementById("budget-reset").click();
    await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    expect(card.classList.contains("is-private")).toBe(false);

    toggle.click();
    expect(card.classList.contains("is-private")).toBe(true);
    expect([...card.querySelectorAll(".budget-sensitive")].every((element) => element.getAttribute("aria-hidden") === "true")).toBe(true);
  });

  it("shows a restrained error state when the API is unavailable", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: false, statusText: "offline", json: async () => ({}) }));
    await importFresh();
    await vi.waitFor(() => expect(document.getElementById("budget-source-meta").textContent).toContain("Nie udało"));
  });
});
