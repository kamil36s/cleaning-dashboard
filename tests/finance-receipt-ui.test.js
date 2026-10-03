import { describe, expect, it, vi } from "vitest";
import { receiptMatchLabel, receiptProcessingExplanation, receiptProcessingLabel, receiptTotalLabel } from "../js/finance-receipt-ui.js";

describe("Finance receipt runtime UI helpers", () => {
  it("never renders an unknown total as zero", () => {
    const formatter = vi.fn(() => "0,00 zł");
    expect(receiptTotalLabel({ total: null, currency: "PLN" }, formatter)).toBe("Kwota nierozpoznana");
    expect(formatter).not.toHaveBeenCalled();
  });

  it("uses human processing labels for actionable OCR states", () => {
    expect(receiptProcessingLabel({ processingState: "ocr_unavailable" })).toBe("OCR niedostępny");
    expect(receiptProcessingLabel({ processingState: "ocr_failed" })).toBe("OCR nie powiódł się");
    expect(receiptProcessingLabel({ processingState: "parsed" })).toBe("Odczytany");
    expect(receiptProcessingExplanation({ processingState: "ocr_unavailable" })).toContain("zapisany");
  });

  it("distinguishes manual, ambiguous, and missing matches", () => {
    expect(receiptMatchLabel({ transactionId: "tx", matchState: "manual" })).toBe("Dopasowano ręcznie");
    expect(receiptMatchLabel({ matchState: "ambiguous" })).toBe("Wybierz transakcję");
    expect(receiptMatchLabel({ matchState: "none" })).toBe("Bez dopasowania");
  });
});
