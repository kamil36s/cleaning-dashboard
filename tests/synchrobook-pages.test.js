import { beforeEach, describe, expect, it } from "vitest";
import {
  PAGE_TOTALS_STORAGE_KEY, currentPageAtTime, loadPageTotals, normalizeTotalPages, savePageTotals,
} from "../js/synchrobook/page-progress.js";

describe("Synchrobook page counter", () => {
  beforeEach(() => localStorage.clear());

  it("maps audiobook progress onto the printed page range", () => {
    expect(currentPageAtTime(0, 1000, 320)).toBe(1);
    expect(currentPageAtTime(500, 1000, 320)).toBe(160);
    expect(currentPageAtTime(1000, 1000, 320)).toBe(320);
    expect(currentPageAtTime(1200, 1000, 320)).toBe(320);
  });

  it("requires a valid duration and whole positive page count", () => {
    expect(currentPageAtTime(100, 0, 320)).toBeNull();
    expect(currentPageAtTime(100, 1000, "")).toBeNull();
    expect(normalizeTotalPages(12.5)).toBeNull();
    expect(normalizeTotalPages(0)).toBeNull();
  });

  it("stores a separate total for each book and ignores corrupt values", () => {
    savePageTotals({ alpha: 250, beta: 480 });
    expect(loadPageTotals()).toEqual({ alpha: 250, beta: 480 });

    localStorage.setItem(PAGE_TOTALS_STORAGE_KEY, JSON.stringify({ alpha: 250, broken: -4, decimal: 12.5 }));
    expect(loadPageTotals()).toEqual({ alpha: 250 });
  });
});
