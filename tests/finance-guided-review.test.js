import { describe, expect, it } from "vitest";
import {
  answerGuidedQuestion,
  backGuidedReview,
  createGuidedReviewSession,
  getGuidedReviewState,
  getNextGuidedQuestion,
  guidedReviewResult,
  restartGuidedReview,
} from "../js/finance-guided-review.js";

const taxonomy = [
  [1, "Zakupy codzienne"], [2, "Zakupy mieszane", 1, "Zakupy codzienne"], [3, "Spożywcze", 1, "Zakupy codzienne"], [4, "Używki", 1, "Zakupy codzienne"],
  [5, "Jedzenie poza domem"], [6, "Restauracje", 5, "Jedzenie poza domem"], [7, "Delivery", 5, "Jedzenie poza domem"], [8, "Kawa i przekąski", 5, "Jedzenie poza domem"],
  [9, "Transport"], [10, "Komunikacja", 9, "Transport"], [11, "Taxi / rideshare", 9, "Transport"], [12, "Kolej", 9, "Transport"], [13, "Paliwo", 9, "Transport"], [14, "Inny transport", 9, "Transport"],
  [15, "Zdrowie"], [16, "Apteka", 15, "Zdrowie"], [17, "Lekarze", 15, "Zdrowie"], [18, "Badania", 15, "Zdrowie"], [19, "Higiena i uroda"],
  [20, "Rozrywka"], [21, "Wydarzenia", 20, "Rozrywka"], [22, "Gry", 20, "Rozrywka"], [23, "Kino", 20, "Rozrywka"], [24, "Hobby", 20, "Rozrywka"],
  [25, "Usługi i subskrypcje"], [26, "Subskrypcje", 25, "Usługi i subskrypcje"], [27, "Aplikacje", 25, "Usługi i subskrypcje"], [28, "Rachunki i usługi", 25, "Usługi i subskrypcje"], [29, "Inne usługi", 25, "Usługi i subskrypcje"],
  [30, "Zakupy"], [31, "Elektronika", 30, "Zakupy"], [32, "Odzież", 30, "Zakupy"], [33, "Dom", 30, "Zakupy"], [34, "Inne zakupy", 30, "Zakupy"],
  [35, "Podróże"], [36, "Noclegi", 35, "Podróże"], [37, "Transport w podróży", 35, "Podróże"], [38, "Inne podróże", 35, "Podróże"],
  [39, "Edukacja"], [40, "Opłaty i prowizje"], [41, "Inne"], [42, "Do ustalenia", 41, "Inne"],
].map(([id, name, parentId = null, parentName = null]) => ({ id, name, parentId, parentName }));

const merchantTypes = ["Supermarket", "Drogeria", "Taxi / rideshare", "Delivery", "Subskrypcja", "Kino", "Apteka", "Nocleg"]
  .map((name, index) => ({ id: 100 + index, name }));

function session(group = {}) {
  return createGuidedReviewSession({
    group: {
      id: "rvg_fixture", displayName: "PHU XYZ", transactionKinds: ["unknown"],
      unresolvedFields: ["unknown_merchant", "missing_category", "missing_transaction_kind"],
      suggestion: { confidence: "unknown", evidence: [], resolvesAllFields: false },
      ...group,
    },
    categories: taxonomy,
    merchantTypes,
  });
}

function answer(current, choiceId) {
  const question = getNextGuidedQuestion(current);
  return answerGuidedQuestion(current, question.id, choiceId);
}

describe("Finance C.7 guided decision engine", () => {
  it("uses one evidence confirmation for an exact known merchant", () => {
    let current = session({
      displayName: "Uber", transactionKinds: ["expense"],
      suggestion: { confidence: "exact", resolvesAllFields: true, merchantId: 7, merchant: "Uber", categoryId: 11, parentCategory: "Transport", category: "Taxi / rideshare", transactionKind: "expense", evidence: ["Dokładny alias."] },
    });
    expect(getNextGuidedQuestion(current).id).toBe("evidence_confirmation");
    expect(getNextGuidedQuestion(current).prompt).toContain("przejazd");
    current = answer(current, "yes");
    expect(getNextGuidedQuestion(current)).toBeNull();
    expect(guidedReviewResult(current).classification).toMatchObject({ merchantId: 7, categoryId: 11, transactionKind: "expense" });
  });

  it("uses strong history shortcuts but conflicting evidence falls back to questions", () => {
    const strong = session({ transactionKinds: ["expense"], suggestion: { confidence: "strong", resolvesAllFields: true, categoryId: 7, parentCategory: "Jedzenie poza domem", category: "Delivery", transactionKind: "expense", evidence: ["4 z 5 zgodnych."] } });
    expect(getNextGuidedQuestion(strong).id).toBe("evidence_confirmation");
    const mixed = session({ transactionKinds: ["expense"], suggestion: { confidence: "mixed", resolvesAllFields: false, evidence: ["Historia jest mieszana."] } });
    expect(getNextGuidedQuestion(mixed).id).toBe("expense_domain");
  });

  it("does not shortcut mixed semantics or an ambiguous Do ustalenia category", () => {
    const mixedKinds = session({
      transactionKinds: ["expense", "refund"],
      suggestion: { confidence: "strong", resolvesAllFields: true, categoryId: 8, category: "Kawa i przekąski", transactionKind: "expense", evidence: ["Historia."] },
    });
    expect(getNextGuidedQuestion(mixedKinds).id).toBe("root_kind");
    const unresolvedOther = session({
      transactionKinds: ["other"], unresolvedFields: ["ambiguous_category_mapping"],
      suggestion: { confidence: "exact", resolvesAllFields: true, categoryId: 42, parentCategory: "Inne", category: "Do ustalenia", transactionKind: "other", evidence: ["Stare mapowanie."] },
    });
    expect(getNextGuidedQuestion(unresolvedOther).id).toBe("root_kind");
  });

  it("asks an unknown transaction broadly and never asks a resolved kind twice", () => {
    let current = session();
    expect(getNextGuidedQuestion(current).id).toBe("root_kind");
    current = answer(current, "purchase");
    expect(getNextGuidedQuestion(current).id).toBe("expense_domain");
    expect(getGuidedReviewState(current).classification.transactionKind).toBe("expense");
  });

  it("asks zero questions when there are no unresolved semantic fields", () => {
    const current = session({ transactionKinds: ["expense"], unresolvedFields: [] });
    expect(getNextGuidedQuestion(current)).toBeNull();
  });

  it("applies the mixed-retailer policy without guessing basket contents", () => {
    let current = session({ transactionKinds: ["expense"] });
    current = answer(current, "shop");
    current = answer(current, "mixed");
    const result = guidedReviewResult(current);
    expect(result.labels.category).toBe("Zakupy codzienne → Zakupy mieszane");
    expect(result.notes.join(" ")).toContain("paragonu");
  });

  it.each([
    ["shop", "electronics", "Zakupy → Elektronika"],
    ["food", "restaurant", "Jedzenie poza domem → Restauracje"],
    ["food", "delivery", "Jedzenie poza domem → Delivery"],
    ["transport", "taxi", "Transport → Taxi / rideshare"],
    ["service", "streaming", "Usługi i subskrypcje → Subskrypcje"],
    ["entertainment", "cinema", "Rozrywka → Kino"],
    ["health", "tests", "Zdrowie → Badania"],
    ["travel", "lodging", "Podróże → Noclegi"],
  ])("maps %s/%s to the canonical taxonomy", (domain, subtype, expected) => {
    let current = session({ transactionKinds: ["expense"], unresolvedFields: ["missing_category"] });
    current = answer(current, domain);
    current = answer(current, subtype);
    expect(guidedReviewResult(current).labels.category).toBe(expected);
    expect(getNextGuidedQuestion(current)).toBeNull();
  });

  it("asks for an unresolved place and accepts a new canonical merchant name", () => {
    let current = session({
      displayName: "cm4m warszawska sp. z",
      transactionKinds: ["expense"],
      unresolvedFields: ["unknown_merchant"],
      suggestion: { confidence: "mixed", resolvesAllFields: false, categoryId: 17, category: "Lekarze" },
    });
    const question = getNextGuidedQuestion(current);
    expect(question.id).toBe("merchant_resolution");
    current = answerGuidedQuestion(current, question.id, "select_merchant", {
      merchantName: "CM4M Warszawska", merchantLabel: "CM4M Warszawska", manualValue: "CM4M Warszawska",
    });
    expect(getNextGuidedQuestion(current)).toBeNull();
    expect(guidedReviewResult(current).classification.merchantName).toBe("CM4M Warszawska");
    expect(guidedReviewResult(current).unresolvedFields).not.toContain("unknown_merchant");
  });

  it("continues from category to place until every missing field is handled", () => {
    let current = session({ transactionKinds: ["expense"] });
    current = answer(current, "health");
    current = answer(current, "doctor");
    expect(getNextGuidedQuestion(current).id).toBe("merchant_resolution");
    current = answerGuidedQuestion(current, "merchant_resolution", "skip");
    expect(getNextGuidedQuestion(current)).toBeNull();
    expect(guidedReviewResult(current).unresolvedFields).toContain("unknown_merchant");
    expect(guidedReviewResult(current).classification.categoryId).toBe(17);
  });

  it.each([
    ["own", "transfer"], ["refund", "refund"], ["private", "transfer"], ["income", "income"],
  ])("handles transfer answer %s conservatively", (choiceId, kind) => {
    let current = session({ transactionKinds: ["transfer"], unresolvedFields: ["missing_transaction_kind"] });
    current = answer(current, choiceId);
    const result = guidedReviewResult(current);
    expect(result.classification.transactionKind).toBe(kind);
    expect(result.classification.categoryId).toBeUndefined();
  });

  it("branches an actual transfer purchase into expense classification", () => {
    let current = session({ transactionKinds: ["transfer"] });
    current = answer(current, "purchase");
    expect(getNextGuidedQuestion(current).id).toBe("expense_domain");
    current = answer(current, "transport");
    current = answer(current, "rail");
    expect(guidedReviewResult(current).labels.category).toBe("Transport → Kolej");
  });

  it.each([
    ["salary", "salary"], ["income", "income"], ["expense_refund", "refund"],
    ["purchase_refund", "refund"], ["own_transfer", "transfer"], ["private", "transfer"],
  ])("distinguishes positive-flow answer %s from income", (choiceId, expectedKind) => {
    let current = session();
    current = answer(current, "income");
    expect(getNextGuidedQuestion(current).id).toBe("income_type");
    current = answer(current, choiceId);
    expect(guidedReviewResult(current).classification.transactionKind).toBe(expectedKind);
  });

  it("keeps cash movement uncategorized unless the user knows its use", () => {
    let current = session({ transactionKinds: ["cash"] });
    current = answer(current, "withdrawal");
    const result = guidedReviewResult(current);
    expect(result.semanticKind).toBe("cash");
    expect(result.classification.categoryId).toBeUndefined();
  });

  it("treats don't-know as first-class and fabricates no classification", () => {
    let current = session();
    current = answer(current, "unknown");
    const result = guidedReviewResult(current);
    expect(result.stopped).toBe(true);
    expect(result.classification).toEqual({});
    expect(result.unresolvedFields).toContain("missing_category");
  });

  it("supports safe back and restart recomputation", () => {
    let current = session({ transactionKinds: ["expense"] });
    current = answer(current, "shop");
    expect(getNextGuidedQuestion(current).id).toBe("shop_type");
    current = backGuidedReview(current);
    expect(getNextGuidedQuestion(current).id).toBe("expense_domain");
    current = answer(current, "health");
    current = restartGuidedReview(current);
    expect(getNextGuidedQuestion(current).id).toBe("expense_domain");
  });

  it("does not carry or alter transaction amounts", () => {
    const current = createGuidedReviewSession({ group: { transactionKinds: ["expense"], unresolvedFields: ["missing_category"], amount: -53.20, suggestion: { confidence: "unknown", resolvesAllFields: false } }, categories: taxonomy });
    expect(guidedReviewResult(current)).not.toHaveProperty("amount");
  });
});
