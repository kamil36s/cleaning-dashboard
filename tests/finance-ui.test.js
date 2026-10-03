import { describe, expect, it } from "vitest";
import {
  chooseDefaultFinanceMonth,
  financePeriodOptions,
  onboardingVisibility,
  polishMonthLabel,
  hierarchicalCategoryOptions,
  reviewScopeLabel,
  reviewPreviewLines,
} from "../js/finance-ui.js";

describe("Finance C.5 UI helpers", () => {
  it("defaults to the current month when current data exists", () => {
    expect(chooseDefaultFinanceMonth("2026-09", "2026-09-12")).toBe("2026-09");
  });

  it("defaults stale data to its latest populated month", () => {
    expect(chooseDefaultFinanceMonth("2026-09", "2026-05-28")).toBe("2026-05");
  });

  it("formats periods in Polish and keeps explicit current-month selection", () => {
    expect(polishMonthLabel("2026-05")).toBe("maj 2026");
    const values = financePeriodOptions("2026-05", "2026-09").map((item) => item.value);
    expect(values).toContain("2026-05");
    expect(values).toContain("2026-09");
  });

  it("supports dismissing and resuming onboarding", () => {
    expect(onboardingVisibility(true, 2, 8)).toEqual({ hidden: true, complete: false });
    expect(onboardingVisibility(false, 8, 8)).toEqual({ hidden: false, complete: true });
  });

  it("builds searchable hierarchical category labels", () => {
    const result = hierarchicalCategoryOptions([
      { id: 1, name: "Transport", parentId: null },
      { id: 2, name: "Taxi", parentId: 1, parentName: "Transport" },
    ]);
    expect(result[1].label).toBe("Transport → Taxi");
  });

  it("keeps scope and bulk consequences explicit", () => {
    expect(reviewScopeLabel("selected_month", "wrzesień 2026")).toContain("wrzesień 2026");
    expect(reviewScopeLabel("all_history", "wrzesień 2026")).toBe("Cała historia");
    const lines = reviewPreviewLines({ transactionCount: 38, changes: { category: 38 }, manualClassificationsOverwritten: 0 }, { category: "Transport → Taxi" });
    expect(lines.join(" ")).toContain("38 transakcji");
    expect(lines.join(" ")).toContain("Ręczne klasyfikacje nadpisane: 0");
  });
});
