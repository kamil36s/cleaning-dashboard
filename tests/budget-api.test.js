import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyBudgetRule,
  classifyBudgetTransaction,
  createBudgetRule,
  fetchBudgetAnalytics,
  fetchBudgetReview,
  fetchBudgetTransactions,
  previewBudgetRule,
  saveBudgetServerData,
  updateBudgetAnnotations,
  updateBudgetSettings,
  fetchFinanceReceiptSources,
  fetchReceiptProcessingHealth,
  reprocessFinanceReceipt,
  deleteFinanceReceipt,
  reprocessFinanceReceiptsNeedingOcr,
  updateFinanceReceiptMetadata,
  matchFinanceReceipt,
} from "../js/budget-api.js";

describe("Budget API write boundaries", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not issue legacy full-snapshot writes", async () => {
    globalThis.fetch = vi.fn();
    await expect(saveBudgetServerData({ transactions: [] })).rejects.toThrow("Pełny zapis");
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("uses narrow annotation and settings operations", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true }),
    }));

    await updateBudgetAnnotations([{ id: "tx_1", merchant: "Fixture" }]);
    await updateBudgetSettings({ userCategories: ["Fixture"] });

    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      "/api/budget/annotations",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      "/api/budget/settings",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("uses paginated reads and narrow Pack B operations", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true, transactions: [], items: [], data: {} }),
    }));

    await fetchBudgetTransactions({ page: 2, limit: 25, transactionKind: "expense" });
    await fetchBudgetReview("open");
    await fetchBudgetAnalytics("summary", { period: "latest_data_month" });
    await createBudgetRule({ name: "Fixture", conditions: [], actions: [] });
    await previewBudgetRule(12);
    await applyBudgetRule(12, { includeManual: false });
    await classifyBudgetTransaction("tx_1", { transactionKind: "expense" });

    expect(globalThis.fetch.mock.calls[0][0]).toContain("/api/budget/transactions?");
    expect(globalThis.fetch.mock.calls[0][0]).toContain("limit=25");
    expect(globalThis.fetch.mock.calls[1][0]).toBe("/api/budget/review?status=open");
    expect(globalThis.fetch.mock.calls[2][0]).toContain("/api/budget/analytics/summary?");
    expect(globalThis.fetch.mock.calls[3][0]).toBe("/api/budget/rules");
    expect(globalThis.fetch.mock.calls[4][0]).toBe("/api/budget/rules/12/preview");
    expect(globalThis.fetch.mock.calls[5][0]).toBe("/api/budget/rules/12/apply");
    expect(globalThis.fetch.mock.calls[6][0]).toBe("/api/budget/transactions/tx_1/classification");
    expect(globalThis.fetch.mock.calls.slice(3).every(([, options]) => options.method === "POST")).toBe(true);
  });

  it("uses receipt-scoped preview, retry, deletion, metadata, matching, and health routes", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true, sources: [], health: {}, receipt: {}, reprocess: {}, match: {} }),
    }));

    await fetchFinanceReceiptSources("receipt/unsafe");
    await fetchReceiptProcessingHealth();
    await reprocessFinanceReceipt("receipt/unsafe");
    await deleteFinanceReceipt("receipt/unsafe");
    await reprocessFinanceReceiptsNeedingOcr();
    await updateFinanceReceiptMetadata("receipt/unsafe", { total: "12.34" });
    await matchFinanceReceipt("receipt/unsafe", "transaction-1");

    expect(globalThis.fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/budget/receipts/receipt%2Funsafe/sources",
      "/api/budget/receipts/processing-health",
      "/api/budget/receipts/receipt%2Funsafe/reprocess",
      "/api/budget/receipts/receipt%2Funsafe/delete",
      "/api/budget/receipts/reprocess-needing-ocr",
      "/api/budget/receipts/receipt%2Funsafe/metadata",
      "/api/budget/receipts/receipt%2Funsafe/match",
    ]);
    expect(globalThis.fetch.mock.calls.slice(2).every(([, options]) => options.method === "POST")).toBe(true);
  });
});
