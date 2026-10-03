import { describe, expect, it } from "vitest";
import {
  applyBudgetRuleSuggestions,
  buildBudgetRuleSuggestions,
  DEFAULT_BUDGET_DATA,
  extractBudgetMerchantCandidate,
  formatBudgetDate,
  normalizeBudgetData,
  normalizeBudgetText,
  parseBudgetMoney,
  summarizeBudgetData,
  updateBudgetTransaction,
} from "../js/budget.js";

function sampleData() {
  return normalizeBudgetData({
    source: { name: "fixture.csv", importedAt: "2026-05-09T08:00:00.000Z" },
    settings: DEFAULT_BUDGET_DATA.settings,
    transactions: [
      { id: "saving", date: "2026-05-09", description: "CEL", account: "Konto 1234", category: "Regularne oszczedzanie", amount: -5.31, balanceAfter: 1920.43 },
      { id: "food", date: "2026-05-08", description: "BIEDRONKA 1234", account: "Konto 1234", category: "Zakupy spozywcze", amount: -42.1, balanceAfter: 1925.74 },
      { id: "salary", date: "2026-05-07", description: "Wynagrodzenie", account: "Konto 1234", category: "Przelew przychodzacy", amount: 3500, balanceAfter: 1967.84 },
    ],
  });
}

describe("Budget UI analytics", () => {
  it("ships broad editable dictionaries for categories and merchant types", () => {
    expect(DEFAULT_BUDGET_DATA.settings.userCategories).toContain("Kawa i slodycze");
    expect(DEFAULT_BUDGET_DATA.settings.userCategories.length).toBeGreaterThan(20);
    expect(DEFAULT_BUDGET_DATA.settings.merchantTypes).toContain("Sklep internetowy");
    expect(DEFAULT_BUDGET_DATA.settings.merchantTypes.length).toBeGreaterThan(20);
  });

  it("summarizes backend-normalized transactions without counting savings as expenses", () => {
    const summary = summarizeBudgetData(sampleData());
    expect(summary.latestBalance).toBeCloseTo(1920.43, 2);
    expect(summary.totalSpending).toBeCloseTo(42.1, 2);
    expect(summary.totalSavings).toBeCloseTo(5.31, 2);
    expect(summary.totalIncome).toBeCloseTo(3500, 2);
  });

  it("normalizes helper values used by the widget", () => {
    expect(parseBudgetMoney("1 920,43 PLN")).toBeCloseTo(1920.43, 2);
    expect(formatBudgetDate("09.05.2026")).toBe("09.05.2026");
    expect(normalizeBudgetText("  Oszczędzanie  ")).toBe("oszczedzanie");
  });

  it("uses user categories when transactions are enriched in the budget app", () => {
    const data = sampleData();
    const updated = updateBudgetTransaction(data, "food", {
      userCategory: "Jedzenie",
      merchant: "Biedronka",
      merchantType: "Sklep",
      note: "testowy opis",
    });
    const summary = summarizeBudgetData(updated);
    expect(updated.transactions.find((transaction) => transaction.id === "food")).toMatchObject({
      userCategory: "Jedzenie", merchant: "Biedronka", merchantType: "Sklep", note: "testowy opis",
    });
    expect(summary.categories[0]).toEqual({ name: "Jedzenie", amount: 42.1 });
  });

  it("preserves legitimate identical transactions returned by the backend", () => {
    const data = normalizeBudgetData({
      transactions: [
        { id: "tx_1", date: "2026-05-09", description: "Ticket", account: "A", category: "Transport", amount: -4 },
        { id: "tx_2", date: "2026-05-09", description: "Ticket", account: "A", category: "Transport", amount: -4 },
      ],
    });
    expect(data.transactions.map((transaction) => transaction.id)).toEqual(["tx_1", "tx_2"]);
  });

  it("can summarize only current-month spending by user categories", () => {
    const summary = summarizeBudgetData({
      transactions: [
        { id: "may-food", date: "2026-05-10", category: "Bankowe zakupy", userCategory: "Drobne zakupy", amount: -100 },
        { id: "may-rent", date: "2026-05-02", category: "Przelew", userCategory: "Czynsz i wynajem", amount: -300 },
        { id: "may-bank-only", date: "2026-05-08", category: "Bankowa kategoria", amount: -500 },
        { id: "april-food", date: "2026-04-30", category: "Bankowe zakupy", userCategory: "Drobne zakupy", amount: -900 },
      ],
    }, { categoryPeriod: "current-month", categorySource: "user", referenceDate: "2026-05-10" });
    expect(summary.totalSpending).toBeCloseTo(1800, 2);
    expect(summary.categoryTotalSpending).toBeCloseTo(400, 2);
  });

  it("builds current-month payroll metrics for the dashboard tiles", () => {
    const summary = summarizeBudgetData({
      settings: { savingsCategories: ["oszczedzanie"], ignoredCategories: [] },
      transactions: [
        { id: "salary", date: "2026-04-26", category: "Przelew przychodzacy", amount: 5000, transactionKind: "salary" },
        { id: "refund", date: "2026-04-27", category: "Zwrot", amount: 7000, transactionKind: "refund" },
        { id: "bonus", date: "2026-04-10", category: "Przelew przychodzacy", amount: 300 },
        { id: "food", date: "2026-05-05", category: "Zakupy", amount: -750 },
        { id: "savings", date: "2026-05-07", category: "Regularne oszczedzanie", amount: -1000 },
      ],
    }, { referenceDate: "2026-05-11" });
    expect(summary.currentMonth.totalSpending).toBeCloseTo(750, 2);
    expect(summary.currentMonth.totalSavings).toBeCloseTo(1000, 2);
    expect(summary.currentMonth.salaryAmount).toBeCloseTo(5000, 2);
    expect(summary.currentMonth.salarySpentPercent).toBeCloseTo(15, 2);
  });

  it("builds reviewable bulk suggestions and fills only selected empty fields", () => {
    const data = normalizeBudgetData({
      transactions: [12, 18, 8].map((amount, index) => ({
        id: `zabka-${index}`,
        date: `2026-05-0${index + 7}`,
        description: "Żabka ZAKUP PRZY UŻYCIU KARTY W KRAJU",
        account: "Konto",
        category: "Zakupy",
        amount: -amount,
      })),
    });
    const suggestions = buildBudgetRuleSuggestions(data);
    const zabka = suggestions.find((suggestion) => normalizeBudgetText(suggestion.merchant) === "zabka");
    expect(extractBudgetMerchantCandidate("Żabka ZAKUP PRZY UŻYCIU KARTY W KRAJU")).toBe("Żabka");
    expect(zabka?.applyCount).toBe(3);

    const applied = applyBudgetRuleSuggestions(data, [{
      ...zabka,
      selected: true,
      userCategory: "Jedzenie",
      transactionIds: zabka.transactionIds.slice(0, 2),
    }]);
    expect(applied.transactions.filter((transaction) => transaction.userCategory === "Jedzenie")).toHaveLength(2);
  });
});
