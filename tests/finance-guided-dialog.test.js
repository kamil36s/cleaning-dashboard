import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { createFinanceGuidedDialog } from "../js/finance-guided-dialog.js";

const categories = [
  { id: 1, name: "Zakupy codzienne", parentId: null },
  { id: 2, name: "Zakupy mieszane", parentId: 1, parentName: "Zakupy codzienne" },
];

const unknownGroup = {
  id: "rvg_ui", displayName: "PHU XYZ", transactionKinds: ["unknown"], transactionCount: 3,
  reviewTransactionCount: 3, unresolvedFields: ["missing_transaction_kind", "missing_category"],
  guidedTransaction: { id: "tx_3", date: "2026-09-14", amount: -53.2, currency: "PLN", description: "PHU XYZ" },
  samples: [{ id: "tx_3", date: "2026-09-14", amount: -53.2, currency: "PLN", description: "PHU XYZ" }],
  suggestion: { confidence: "unknown", evidence: [], resolvesAllFields: false },
};

function mount() {
  document.body.innerHTML = `
    <dialog id="finance-guided-review">
      <div id="finance-guided-progress"></div><div id="finance-guided-title"></div>
      <button id="finance-guided-close"></button>
      <div id="finance-guided-transaction"></div><div id="finance-guided-path"></div><div id="finance-guided-body"></div>
      <button id="finance-guided-back"></button><button id="finance-guided-restart"></button><button id="finance-guided-skip"></button>
      <img id="finance-guided-mascot-image" hidden><span id="finance-guided-mascot-fallback"></span>
    </dialog>`;
}

describe("Finance C.7 guided dialog", () => {
  beforeEach(mount);

  it("opens and closes while treating the mascot as decorative", () => {
    const controller = createFinanceGuidedDialog({ document, onSubmit: vi.fn() });
    controller.open({ group: unknownGroup, categories, merchantTypes: [], scope: "all_history", month: "2026-09" });
    expect(controller.isOpen()).toBe(true);
    expect(document.querySelector("[data-guided-choice]")).not.toBeNull();
    const image = document.getElementById("finance-guided-mascot-image");
    expect(image.src).toContain("assets/finance/financial-akinator.png");
    image.dispatchEvent(new Event("load"));
    expect(image.hidden).toBe(false);
    document.getElementById("finance-guided-close").click();
    expect(controller.isOpen()).toBe(false);
  });

  it("supports numeric choices, back, restart and skip", () => {
    const controller = createFinanceGuidedDialog({ document, onSubmit: vi.fn() });
    controller.open({ group: unknownGroup, categories, merchantTypes: [], scope: "all_history", month: "2026-09" });
    const dialog = document.getElementById("finance-guided-review");
    dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "1", bubbles: true }));
    expect(document.getElementById("finance-guided-body").textContent).toContain("Czego dotyczył ten wydatek?");
    document.getElementById("finance-guided-back").click();
    expect(document.getElementById("finance-guided-body").textContent).toContain("Co to było?");
    document.querySelector('[data-guided-choice="purchase"]').click();
    document.getElementById("finance-guided-restart").click();
    expect(document.getElementById("finance-guided-body").textContent).toContain("Co to było?");
    document.getElementById("finance-guided-skip").click();
    expect(document.getElementById("finance-guided-body").textContent).toContain("Nic nie zostanie zapisane");
  });

  it("passes a canonical result and selected scope to the C.6 submit callback", async () => {
    const onSubmit = vi.fn(async () => false);
    const controller = createFinanceGuidedDialog({ document, onSubmit });
    controller.open({
      group: { ...unknownGroup, transactionKinds: ["expense"], unresolvedFields: ["missing_category"] },
      categories, merchantTypes: [], scope: "selected_month", month: "2026-09",
    });
    document.querySelector('[data-guided-choice="shop"]').click();
    document.querySelector('[data-guided-choice="mixed"]').click();
    document.querySelector('[data-guided-scope="similar"]').click();
    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ mode: "similar", scope: "selected_month", month: "2026-09" });
    expect(onSubmit.mock.calls[0][0].result.classification.categoryId).toBe(2);
  });

  it("explains the three transaction save scopes in compact cards", () => {
    const controller = createFinanceGuidedDialog({ document, onSubmit: vi.fn() });
    controller.open({
      group: {
        ...unknownGroup,
        transactionKinds: ["expense"],
        unresolvedFields: ["missing_category"],
        rememberOptions: { merchantDefault: true },
      },
      categories, merchantTypes: [], scope: "selected_month", month: "2026-09",
    });
    document.querySelector('[data-guided-choice="shop"]').click();
    document.querySelector('[data-guided-choice="mixed"]').click();
    const cards = [...document.querySelectorAll(".finance-guided-scope-card")];
    expect(cards).toHaveLength(3);
    expect(cards[0].textContent).toContain("tylko przy transakcji widocznej powyżej");
    expect(cards[1].textContent).toContain("Ręcznych danych nie nadpisze");
    expect(cards[2].textContent).toContain("domyślną dla tego miejsca");
    expect(document.getElementById("finance-guided-body").textContent).toContain("bez kolejnego potwierdzenia");

    controller.close();
    controller.open({
      group: {
        ...unknownGroup,
        transactionKinds: ["expense"], reviewTransactionCount: 1,
        unresolvedFields: ["missing_category"], rememberOptions: { merchantDefault: true },
      },
      categories, merchantTypes: [], scope: "selected_month", month: "2026-09",
    });
    document.querySelector('[data-guided-choice="shop"]').click();
    document.querySelector('[data-guided-choice="mixed"]').click();
    expect(document.querySelectorAll(".finance-guided-scope-card")).toHaveLength(2);
    expect(document.querySelector('[data-guided-scope="similar"]')).toBeNull();
  });

  it("shows save feedback, refresh result, and then closes automatically", async () => {
    vi.useFakeTimers();
    try {
      const onSubmit = vi.fn(async () => ({ message: "Paragon i checklista są aktualne." }));
      const controller = createFinanceGuidedDialog({ document, onSubmit });
      controller.open({
        domain: "receipt_item",
        group: { id: "group_1", rawName: "Produkt", itemCount: 1, nameConfidence: "strong", suggestion: {} },
        productCategories: [{ id: 7, name: "Dom", parentId: null }],
      });
      document.querySelector('[data-guided-choice="category_7"]').click();
      document.querySelector('[data-guided-scope="similar"]').click();
      await Promise.resolve();
      await Promise.resolve();
      expect(document.getElementById("finance-guided-body").textContent).toContain("✓ Zapisano");
      expect(document.getElementById("finance-guided-body").textContent).toContain("Paragon i checklista są aktualne.");
      expect(controller.isOpen()).toBe(true);
      vi.advanceTimersByTime(2599);
      expect(controller.isOpen()).toBe(true);
      vi.advanceTimersByTime(1);
      expect(controller.isOpen()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows an inline place picker and a full saving state", async () => {
    let finish;
    const onSubmit = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
    const controller = createFinanceGuidedDialog({ document, onSubmit });
    controller.open({
      group: { ...unknownGroup, transactionKinds: ["expense"], unresolvedFields: ["unknown_merchant"], displayName: "CM4M Warszawska" },
      categories, merchants: [{ id: 9, canonicalName: "Centrum Medyczne" }], merchantTypes: [], scope: "selected_month", month: "2026-09",
    });
    expect(document.getElementById("finance-guided-body").textContent).toContain("Jak nazywa się to miejsce?");
    const input = document.querySelector('.finance-guided-merchant-editor input');
    input.value = "Centrum Medyczne";
    input.dispatchEvent(new Event("input"));
    document.querySelector('.finance-guided-merchant-editor button').click();
    expect(document.getElementById("finance-guided-body").textContent).toContain("Miejsce: Centrum Medyczne");
    document.querySelector('[data-guided-scope="similar"]').click();
    expect(document.querySelector(".finance-guided-saving-screen")).not.toBeNull();
    expect(document.getElementById("finance-guided-body").textContent).toContain("Zapisuję zmiany");
    finish({ message: "Gotowe." });
    await vi.waitFor(() => expect(document.getElementById("finance-guided-body").textContent).toContain("✓ Zapisano"));
    expect(onSubmit.mock.calls[0][0].result.classification.merchantId).toBe(9);
    controller.close();
  });

  it("replaces the old technical no-change error with a useful Polish message", async () => {
    const controller = createFinanceGuidedDialog({
      document,
      onSubmit: vi.fn(async () => { throw new Error("This Review group has no unresolved fields matching the selected action."); }),
    });
    controller.open({
      group: {
        ...unknownGroup,
        transactionKinds: ["expense"], reviewTransactionCount: 1,
        unresolvedFields: ["missing_category"], rememberOptions: { exactDescriptionRule: true },
      },
      categories, merchantTypes: [], scope: "selected_month", month: "2026-09",
    });
    document.querySelector('[data-guided-choice="shop"]').click();
    document.querySelector('[data-guided-choice="mixed"]').click();
    document.querySelector('[data-guided-scope="remember"]').click();
    await vi.waitFor(() => expect(document.getElementById("finance-guided-body").textContent).toContain("nie uzupełnia żadnego z brakujących pól"));
    expect(document.getElementById("finance-guided-body").textContent).not.toContain("This Review group");
  });

  it("keeps mobile and accessibility hooks in the production markup", () => {
    const html = readFileSync("budget.html", "utf8");
    const css = readFileSync("styles.css", "utf8");
    expect(html).toContain('id="finance-guided-review"');
    expect(html).toContain('id="finance-guided-mascot-image" alt=""');
    expect(html).toContain('aria-labelledby="finance-guided-title"');
    expect(css).toContain(".finance-guided-shell { grid-template-columns: 1fr;");
    expect(css).toContain(".finance-guided-choices { grid-template-columns: 1fr;");
  });
});
