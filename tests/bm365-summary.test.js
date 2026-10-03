import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import {
  computeBm365FinaleStats,
  isBm365FinaleReady,
  renderBm365FinaleWidget,
} from "../js/bm365-summary.js";

function makeRows(count, overrides = {}) {
  return Array.from({ length: count }, (_, index) => {
    const day = index + 1;
    const date = new Date(2026, 0, day);
    const iso = [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");

    return {
      date: iso,
      artist: `Artist ${index % 24}`,
      album: `Album ${day}`,
      listened: true,
      rating: ((index % 10) + 1) / 2,
      minutes: 30 + (index % 45),
      rowId: day,
      ...overrides[index],
    };
  });
}

describe("BM365 finale summary", () => {
  it("stays locked before the exact 365 album completion point", () => {
    expect(isBm365FinaleReady(makeRows(364))).toBe(false);
    expect(isBm365FinaleReady(makeRows(366))).toBe(false);
    expect(
      isBm365FinaleReady(makeRows(365, { 364: { listened: false } })),
    ).toBe(false);
    expect(
      isBm365FinaleReady(makeRows(365, { 364: { rating: null } })),
    ).toBe(false);
  });

  it("unlocks only when every BM365 album is listened and rated", () => {
    const rows = makeRows(365);
    const stats = computeBm365FinaleStats(rows);

    expect(stats.total).toBe(365);
    expect(stats.done).toBe(365);
    expect(stats.left).toBe(0);
    expect(stats.ratedCount).toBe(365);
    expect(stats.pct).toBe(100);
    expect(stats.totalArtists).toBe(24);
    expect(stats.ratingDistribution.reduce((sum, item) => sum + item.count, 0)).toBe(365);
    expect(stats.topAlbums).toHaveLength(8);
    expect(isBm365FinaleReady(stats)).toBe(true);
    expect(isBm365FinaleReady({ total: 365, done: 365, left: 0, ratedCount: 365, pct: 100 })).toBe(true);
  });

  it("does not render the widget surprise until the finale is ready", async () => {
    const window = new Window();
    const container = window.document.createElement("div");

    const locked = await renderBm365FinaleWidget(container, makeRows(365, { 300: { rating: null } }), {
      document: window.document,
    });

    expect(locked).toBeNull();
    expect(container.children).toHaveLength(0);

    const ready = await renderBm365FinaleWidget(container, makeRows(365), {
      document: window.document,
      resolveCover: async () => "",
    });

    expect(ready).not.toBeNull();
    expect(container.querySelector(".bm365-finale-widget")).not.toBeNull();
    expect(container.textContent).toContain("365 / 365");
  });
});
