import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import {
  answerGuidedQuestion,
  createGuidedReviewSession,
  getNextGuidedQuestion,
  guidedReviewResult,
} from "../js/finance-guided-review.js";
import { financeDateLabel, financeDateToIso } from "../js/finance-date.js";

function answer(session, choiceId, extra = {}) {
  const question = getNextGuidedQuestion(session);
  return answerGuidedQuestion(session, question.id, choiceId, extra);
}

describe("Finance Pack D.2 receipt intelligence UI", () => {
  it("uses DD/MM/YYYY for display and validates date input", () => {
    expect(financeDateLabel("2026-03-03")).toBe("03/03/2026");
    expect(financeDateToIso("15/06/2026")).toBe("2026-06-15");
    expect(financeDateToIso("31/02/2026")).toBe("");
  });

  it("guides a receipt total candidate then a date candidate", () => {
    let session = createGuidedReviewSession({
      domain: "receipt_parse",
      receipt: { id: "rcpt_1", parseReview: {
        unresolved: ["total", "purchase_date"],
        totalCandidates: [{ valueMinor: 11597, label: "115,97" }, { valueMinor: 2169, label: "21,69" }],
        dateCandidates: [{ value: "2026-03-03", label: "03/03/2026" }], itemCandidates: [],
      } },
    });
    expect(getNextGuidedQuestion(session).id).toBe("receipt_parse_total");
    session = answer(session, "total_0");
    expect(getNextGuidedQuestion(session).id).toBe("receipt_parse_date");
    session = answer(session, "date_0");
    expect(getNextGuidedQuestion(session)).toBeNull();
    expect(guidedReviewResult(session).classification.receiptUpdates).toEqual([
      { field: "total", valueMinor: 11597 }, { field: "purchase_date", value: "2026-03-03" },
    ]);
  });

  it("supports receipt item-line confirmation", () => {
    let session = createGuidedReviewSession({
      domain: "receipt_parse",
      receipt: { parseReview: { unresolved: ["items"], totalCandidates: [], dateCandidates: [],
        itemCandidates: [{ itemId: "item_1", name: "Małe akcesoria", priceLabel: "49,99 PLN" }] } },
    });
    expect(getNextGuidedQuestion(session).id).toBe("receipt_parse_item");
    session = answer(session, "yes");
    expect(guidedReviewResult(session).classification.receiptUpdates[0]).toEqual({ field: "item", itemId: "item_1", accepted: true });
  });

  it("confirms or corrects a weak product name before category questions", () => {
    let session = createGuidedReviewSession({
      domain: "receipt_item", group: { rawName: "K0SZYK NA 0W0CE", nameConfidence: "weak", suggestion: {} },
      productCategories: [{ id: 1, name: "Dom", parentId: null }],
    });
    expect(getNextGuidedQuestion(session).id).toBe("receipt_product_name");
    session = answer(session, "edit", { manualValue: "Koszyk na owoce" });
    expect(getNextGuidedQuestion(session).id).toBe("receipt_item_type");
    session = answer(session, "category_1");
    expect(guidedReviewResult(session).classification).toMatchObject({ canonicalName: "Koszyk na owoce", productCategoryId: 1 });
  });

  it("keeps the receipt detail wide, crop-scoped, and free of native date controls", () => {
    const html = readFileSync("budget.html", "utf8");
    const css = readFileSync("styles.css", "utf8");
    expect(html).not.toContain('type="date"');
    expect(html).toContain("DD/MM/YYYY");
    expect(css).toContain("#finance-receipt-detail");
    expect(css).toContain("overflow-x: hidden");
    expect(css).toContain("finance-guided-receipt-crop");
  });

  it("offers explicit receipt deletion and explains the optional computer OCR", () => {
    const page = readFileSync("js/finance-page.js", "utf8");
    expect(page).toContain("Usuń paragon");
    expect(page).toContain("Transakcja bankowa pozostanie bez zmian");
    expect(page).toContain("OCR telefonu działa");
    expect(page).toContain("Tesseract na komputerze jest opcjonalny");
  });

  it("uses a denser responsive grid for the expanded receipt taxonomy", () => {
    const dialog = readFileSync("js/finance-guided-dialog.js", "utf8");
    const css = readFileSync("styles.css", "utf8");
    const backend = readFileSync("finance_receipts.py", "utf8");
    expect(dialog).toContain('question.id === "receipt_item_type"');
    expect(css).toContain(".finance-guided-choices.is-dense");
    expect(css).toContain("repeat(3, minmax(0, 1fr))");
    expect(backend).not.toContain('(\"Dzieci i niemowlęta\", ())');
  });

  it("shows a refreshable receipt checklist and per-product repair actions", () => {
    const page = readFileSync("js/finance-page.js", "utf8");
    expect(page).toContain("Co jeszcze trzeba potwierdzić?");
    expect(page).toContain("Sprzedawca");
    expect(page).toContain("Suma paragonu");
    expect(page).toContain("Produkty");
    expect(page).toContain("Płatność bankowa");
    expect(page).toContain("Ustal produkt");
    expect(page).toContain("Zapisano dane paragonu. Checklista została odświeżona.");
  });

  it("saves guided transaction scope immediately and refreshes visible finance data", () => {
    const page = readFileSync("js/finance-page.js", "utf8");
    const guidedSubmit = page.slice(page.indexOf('if (mode === "transaction")'), page.indexOf("async function loadReview"));
    expect(guidedSubmit).toContain("await applyBudgetReviewGroup");
    expect(guidedSubmit).toContain("await Promise.all([loadReview(), loadOverview()])");
    expect(guidedSubmit).not.toContain("confirmReviewPreview");
  });
});
