import {
  answerGuidedQuestion,
  backGuidedReview,
  createGuidedReviewSession,
  getGuidedReviewState,
  getNextGuidedQuestion,
  guidedReviewResult,
  restartGuidedReview,
} from "./finance-guided-review.js";

const KIND_LABELS = {
  expense: "Wydatek", transfer: "Przelew", salary: "Wynagrodzenie", income: "Dochód",
  refund: "Zwrot", saving: "Oszczędzanie", cash: "Gotówka", other: "Inne",
};

const ISSUE_LABELS = {
  unknown_merchant: "miejsce", missing_category: "kategoria", missing_transaction_kind: "rodzaj operacji",
  ambiguous_category_mapping: "potwierdzenie kategorii", rule_conflict: "konflikt reguł",
};

function element(document, tag, className = "", text = undefined) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

function defaultMoney(value, currency = "PLN") {
  return new Intl.NumberFormat("pl-PL", { style: "currency", currency }).format(Number(value || 0));
}

function defaultDate(value) {
  return value ? new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(`${value}T12:00:00`)) : "—";
}

function saveErrorMessage(error) {
  const message = String(error?.message || "").trim();
  if (/no unresolved fields matching the selected action/i.test(message)) {
    return "Ta decyzja nie uzupełnia żadnego z brakujących pól. Wróć i wybierz odpowiedź dotyczącą pola wskazanego jako brakujące.";
  }
  return message || "Nie udało się zastosować klasyfikacji.";
}

export function createFinanceGuidedDialog({
  document,
  onSubmit,
  onOpenRecurring,
  money = defaultMoney,
  dateLabel = defaultDate,
  mascotPath = "./assets/finance/financial-akinator.png",
} = {}) {
  const byId = (id) => document.getElementById(id);
  const dialog = byId("finance-guided-review");
  if (!dialog) return null;
  const body = byId("finance-guided-body");
  const progress = byId("finance-guided-progress");
  const path = byId("finance-guided-path");
  const back = byId("finance-guided-back");
  const restart = byId("finance-guided-restart");
  const skip = byId("finance-guided-skip");
  let active = null;
  let closeTimer = null;

  function setupMascot() {
    const image = byId("finance-guided-mascot-image");
    if (!image || image.dataset.initialized) return;
    image.dataset.initialized = "1";
    image.addEventListener("load", () => { image.hidden = false; });
    image.addEventListener("error", () => { image.hidden = true; });
    image.src = mascotPath;
  }

  function close() {
    if (closeTimer) {
      globalThis.clearTimeout(closeTimer);
      closeTimer = null;
    }
    delete dialog.dataset.saving;
    delete dialog.dataset.saved;
    dialog.removeAttribute("aria-busy");
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  function transactionNode() {
    if (active.session.domain === "receipt_parse") {
      const receipt = active.receipt || {};
      const copy = element(document, "div");
      copy.append(
        element(document, "strong", "", receipt.retailer || "Paragon do uzupełnienia"),
        element(document, "small", "", `${dateLabel(receipt.date)} · ${receipt.itemCount || 0} pozycji`),
      );
      return [copy, element(document, "b", "", receipt.total == null ? "suma nierozpoznana" : money(receipt.total, receipt.currency || "PLN"))];
    }
    if (active.session.domain === "receipt_item") {
      const copy = element(document, "div");
      copy.append(
        element(document, "strong", "", active.group.rawName || "Pozycja paragonu"),
        element(document, "small", "", `${active.group.retailerKey || "sprzedawca"} · ${active.group.itemCount || 1} wystąpień`),
      );
      if (active.group.sourceLine) copy.append(element(document, "small", "", `Źródło OCR: ${active.group.sourceLine}`));
      if (active.group.cropUrl) {
        const image = element(document, "img", "finance-guided-receipt-crop");
        image.src = active.group.cropUrl;
        image.alt = "Wycinek pozycji z paragonu";
        copy.prepend(image);
      }
      return [copy, element(document, "b", "", money(active.group.samplePrice ?? active.group.impact ?? 0, "PLN"))];
    }
    const transaction = active.group.guidedTransaction || active.group.samples?.at(-1) || {};
    const copy = element(document, "div");
    copy.append(
      element(document, "strong", "", active.group.displayName || transaction.description || "Transakcja"),
      element(document, "small", "", `${dateLabel(transaction.date)} · ${transaction.description || "brak opisu"}`),
    );
    const amount = element(document, "b", Number(transaction.amount) >= 0 ? "is-positive" : "", money(transaction.amount, transaction.currency || "PLN"));
    return [copy, amount];
  }

  function summaryNode(result) {
    const summary = element(document, "div", "finance-guided-summary");
    summary.append(element(document, "strong", "", "Ustalone"));
    if (result.semanticKind) summary.append(element(document, "span", "", `Rodzaj: ${KIND_LABELS[result.semanticKind] || result.semanticKind}`));
    if (result.labels.merchant) summary.append(element(document, "span", "", `Miejsce: ${result.labels.merchant}`));
    if (result.labels.category) summary.append(element(document, "span", "", `Kategoria: ${result.labels.category}`));
    if (result.labels.merchantType) summary.append(element(document, "span", "", `Kontekst: ${result.labels.merchantType}`));
    if (result.labels.product) summary.append(element(document, "span", "", `Produkt: ${result.labels.product}`));
    const missing = result.unresolvedFields.map((item) => ISSUE_LABELS[item] || item);
    summary.append(element(document, "small", "", `Nadal brakuje: ${missing.length ? missing.join(", ") : "niczego"}`));
    for (const note of result.notes) summary.append(element(document, "small", "", note));
    return summary;
  }

  function renderQuestion(question, result) {
    const wrapper = element(document, "section", "finance-guided-question");
    wrapper.append(element(document, "h3", "", question.prompt));
    if (question.explanation) wrapper.append(element(document, "p", "", question.explanation));
    const denseChoices = question.id === "receipt_item_type";
    const choices = element(document, "div", `finance-guided-choices${denseChoices ? " is-dense" : ""}`);
    question.choices.forEach((item, index) => {
      if (item.manualField === "merchant") {
        const editor = element(document, "div", "finance-guided-merchant-editor");
        const input = element(document, "input");
        const list = element(document, "datalist");
        const button = element(document, "button", "finance-guided-choice");
        const merchants = active.merchants || [];
        const normalized = (value) => String(value || "").trim().replace(/\s+/g, " ").toLocaleLowerCase("pl");
        input.type = "search";
        input.placeholder = "Np. CM4M Warszawska, Lidl, dentysta…";
        input.value = active.group.displayName || "";
        input.autocomplete = "off";
        input.setAttribute("aria-label", "Nazwa miejsca");
        list.id = "finance-guided-merchant-options";
        merchants.forEach((merchant) => {
          const option = element(document, "option");
          option.value = merchant.canonicalName;
          list.append(option);
        });
        input.setAttribute("list", list.id);
        button.type = "button";
        button.dataset.guidedChoice = item.id;
        const refreshLabel = () => {
          const name = input.value.trim().replace(/\s+/g, " ");
          const existing = merchants.find((merchant) => normalized(merchant.canonicalName) === normalized(name));
          button.textContent = existing ? `Wybierz „${existing.canonicalName}”` : name ? `Utwórz nowe miejsce „${name}”` : "Podaj nazwę miejsca";
          button.disabled = !name;
        };
        input.addEventListener("input", refreshLabel);
        input.addEventListener("keydown", (event) => {
          if (event.key === "Enter") { event.preventDefault(); button.click(); }
        });
        button.addEventListener("click", () => {
          const name = input.value.trim().replace(/\s+/g, " ");
          if (!name) return;
          const existing = merchants.find((merchant) => normalized(merchant.canonicalName) === normalized(name));
          const extra = existing
            ? { merchantId: Number(existing.id), merchantLabel: existing.canonicalName, manualValue: existing.canonicalName }
            : { merchantName: name, merchantLabel: name, manualValue: name };
          active.session = answerGuidedQuestion(active.session, question.id, item.id, extra);
          render();
        });
        refreshLabel();
        editor.append(input, list, button);
        choices.append(editor);
        return;
      }
      const button = element(document, "button", "finance-guided-choice", item.label);
      button.type = "button";
      button.dataset.guidedChoice = item.id;
      if (index < 9) button.append(element(document, "kbd", "", String(index + 1)));
      button.addEventListener("click", () => {
        let extra = {};
        if (item.manualField) {
          const promptLabel = item.manualField === "total" ? "Podaj sumę w PLN (np. 115,97)"
            : item.manualField === "purchase_date" ? "Podaj datę DD/MM/YYYY"
              : "Podaj poprawną nazwę produktu";
          const raw = globalThis.prompt?.(promptLabel, "")?.trim();
          if (!raw) return;
          let value = raw;
          if (item.manualField === "total") {
            const amount = Number(raw.replace(",", "."));
            if (!Number.isFinite(amount) || amount < 0) return;
          }
          if (item.manualField === "purchase_date") {
            const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(raw);
            if (!match) return;
            value = `${match[3]}-${match[2]}-${match[1]}`;
          }
          extra = { manualValue: value };
        }
        active.session = answerGuidedQuestion(active.session, question.id, item.id, extra);
        render();
      });
      choices.append(button);
    });
    wrapper.append(choices, summaryNode(result));
    body.replaceChildren(wrapper);
  }

  function samplesNode() {
    const details = element(document, "details");
    if (active.session.domain === "receipt_parse") {
      details.append(element(document, "summary", "", "Pola pochodzą z lokalnej analizy OCR i obrazu paragonu"));
      return details;
    }
    if (active.session.domain === "receipt_item") {
      details.append(element(document, "summary", "", `${active.group.itemCount || 1} takich pozycji u sprzedawcy ${active.group.retailerKey || "—"}`));
      return details;
    }
    details.append(element(document, "summary", "", `Zobacz przykłady z grupy (${active.group.transactionCount})`));
    (active.group.samples || []).forEach((item) => details.append(element(
      document, "p", "", `${dateLabel(item.date)} · ${money(item.amount, item.currency || "PLN")} · ${item.description}`,
    )));
    return details;
  }

  function scopeButton(label, mode, quiet = false, detail = null) {
    const button = element(
      document,
      "button",
      detail ? `finance-guided-scope-card${detail.recommended ? " is-recommended" : ""}` : `finance-button${quiet ? " is-quiet" : ""}`,
      detail ? undefined : label,
    );
    button.type = "button";
    button.dataset.guidedScope = mode;
    if (detail) {
      button.append(
        element(document, "strong", "", label),
        element(document, "span", "", detail.description),
        element(document, "small", "", detail.meta),
      );
    }
    button.addEventListener("click", async () => {
      const result = guidedReviewResult(active.session);
      dialog.dataset.saving = "true";
      dialog.setAttribute("aria-busy", "true");
      [back, restart, skip].forEach((item) => { if (item) item.disabled = true; });
      const saving = element(document, "section", "finance-guided-saving-screen");
      saving.setAttribute("role", "status");
      const spinner = element(document, "span", "finance-guided-spinner");
      spinner.setAttribute("aria-hidden", "true");
      saving.append(
        spinner,
        element(document, "strong", "", "Zapisuję zmiany"),
        element(document, "p", "", "Aktualizuję klasyfikację i kolejkę przeglądu."),
        element(document, "small", "", "To może potrwać kilka sekund — możesz zostawić kursor w spokoju."),
      );
      body.replaceChildren(saving);
      progress.textContent = "Zapisywanie…";
      path.textContent = "Aktualizuję dane i odświeżam widok";
      try {
        const applied = await onSubmit?.({ ...active, result, mode });
        if (applied === false) {
          delete dialog.dataset.saving;
          dialog.removeAttribute("aria-busy");
          render();
          return;
        }
        const message = typeof applied === "object" && applied?.message
          ? applied.message
          : "Zmiany zostały zapisane, a widok odświeżony.";
        const success = element(document, "section", "finance-guided-save-success");
        success.setAttribute("role", "status");
        success.append(
          element(document, "strong", "", "✓ Zapisano"),
          element(document, "p", "", message),
          element(document, "small", "", "Okno zamknie się za chwilę."),
        );
        const closeNow = element(document, "button", "finance-button is-quiet", "Zamknij teraz");
        closeNow.type = "button";
        closeNow.addEventListener("click", close);
        success.append(closeNow);
        body.replaceChildren(success);
        delete dialog.dataset.saving;
        dialog.dataset.saved = "true";
        dialog.removeAttribute("aria-busy");
        progress.textContent = "Zapisano";
        path.textContent = "Zapis zakończony";
        closeTimer = globalThis.setTimeout(close, 2600);
      } catch (error) {
        delete dialog.dataset.saving;
        dialog.removeAttribute("aria-busy");
        [back, restart, skip].forEach((item) => { if (item) item.disabled = false; });
        progress.textContent = "Nie zapisano";
        path.textContent = "Popraw błąd i spróbuj ponownie";
        render();
        const message = element(document, "p", "finance-status is-error", saveErrorMessage(error));
        body.querySelector(".finance-guided-final")?.append(message);
      }
    });
    return button;
  }

  function renderFinal(result) {
    const wrapper = element(document, "section", "finance-guided-final");
    wrapper.append(element(document, "h3", "", result.stopped ? "Zostawiamy to na później" : "Ustaliliśmy:"), summaryNode(result));
    if (result.stopped || !Object.keys(result.classification).length) {
      wrapper.append(element(document, "p", "", "Nic nie zostanie zapisane. Transakcja pozostanie w Przeglądzie bez zgadywania."));
      const closeButton = element(document, "button", "finance-button", "Zamknij bez zmian");
      closeButton.type = "button";
      closeButton.addEventListener("click", close);
      wrapper.append(closeButton);
      body.replaceChildren(wrapper);
      return;
    }
    const receiptItem = active.session.domain === "receipt_item";
    const receiptParse = active.session.domain === "receipt_parse";
    const reviewCount = active.group.reviewTransactionCount || 1;
    wrapper.append(
      element(document, "p", "", receiptItem
        ? `Ta odpowiedź może uzupełnić ${active.group.itemCount || 1} powtarzających się pozycji. Transakcje i ich kwoty nie zostaną zmienione.`
        : receiptParse ? "Potwierdzone pola zostaną zapisane przy paragonie, a dopasowanie transakcji uruchomi się ponownie."
        : reviewCount === 1
          ? "Ta odpowiedź uzupełni tę jedną transakcję. Istniejące ręczne klasyfikacje nie zostaną zmienione."
          : `Ta odpowiedź może uzupełnić ${reviewCount} podobnych transakcji. Istniejące ręczne klasyfikacje nie zostaną zmienione.`),
      samplesNode(),
      element(document, "div", "finance-guided-impact", receiptItem || receiptParse
        ? "Kliknięcie przycisku zapisze zmiany, odświeży paragon i zamknie to okno."
        : "Wybierz zakres zapisu. Kliknięcie od razu zapisze zmianę, odświeży kolejkę i zamknie to okno — bez kolejnego potwierdzenia."),
    );
    if (!receiptItem && !receiptParse && active.group.transactionCount >= 3 && /subskrypc|rachunki i usługi/i.test(result.labels.category || "")) {
      const recurring = element(document, "div", "finance-guided-impact");
      recurring.append(element(document, "span", "", "Wygląda na płatność cykliczną. Powiązać ją z Cyklicznymi? "));
      const openRecurring = element(document, "button", "finance-button is-quiet", "Sprawdź w Cyklicznych");
      openRecurring.type = "button";
      openRecurring.addEventListener("click", () => { close(); onOpenRecurring?.(); });
      recurring.append(openRecurring);
      wrapper.append(recurring);
    }
    const scopes = element(document, "div", "finance-guided-scopes");
    if (receiptParse) {
      scopes.append(scopeButton("Zapisz i zamknij", "receipt"));
      wrapper.append(scopes);
      body.replaceChildren(wrapper);
      return;
    }
    if (receiptItem) {
      scopes.append(
        scopeButton(`Zapisz i zamknij (${active.group.itemCount || 1})`, "similar"),
        scopeButton("Zapisz, zamknij i zapamiętaj", "remember", true),
      );
      wrapper.append(scopes);
      body.replaceChildren(wrapper);
      return;
    }
    scopes.classList.add("is-choice-grid");
    scopes.append(scopeButton("Tylko ta płatność", "transaction", false, {
      description: "Zapisze ustaloną kategorię tylko przy transakcji widocznej powyżej.",
      meta: "1 transakcja · bez reguły na przyszłość",
    }));
    if (reviewCount > 1) {
      scopes.append(scopeButton("Wszystkie podobne", "similar", false, {
        description: "Uzupełni tylko brakujące pola w obecnych podobnych transakcjach. Ręcznych danych nie nadpisze.",
        meta: `${reviewCount} transakcji · bez reguły na przyszłość`,
        recommended: true,
      }));
    }
    if (active.group.rememberOptions?.merchantDefault || active.group.rememberOptions?.exactDescriptionRule) {
      const memoryDescription = active.group.rememberOptions?.merchantDefault
        ? "Uzupełni podobne transakcje i ustawi tę kategorię jako domyślną dla tego miejsca."
        : "Uzupełni podobne transakcje i utworzy ścisłą regułę dla dokładnie tego opisu.";
      scopes.append(scopeButton("Podobne + zapamiętaj", "remember", false, {
        description: memoryDescription,
        meta: `${reviewCount} teraz · automatycznie w przyszłości`,
      }));
    } else {
      scopes.append(element(document, "small", "", "Ta grupa nie ma jednego bezpiecznego wzorca do zapamiętania na przyszłość."));
    }
    wrapper.append(scopes);
    body.replaceChildren(wrapper);
  }

  function render() {
    if (!active) return;
    const state = getGuidedReviewState(active.session);
    const result = guidedReviewResult(active.session);
    const question = getNextGuidedQuestion(active.session);
    progress.textContent = state.answerCount ? `${state.answerCount} ${state.answerCount === 1 ? "odpowiedź" : "odpowiedzi"}` : "Ustalamy kategorię";
    path.textContent = result.path.length ? result.path.join(" → ") : "Zaczynamy od tego, co już wiadomo";
    back.disabled = !active.session.answers.length;
    restart.disabled = !active.session.answers.length;
    skip.disabled = false;
    skip.hidden = !question;
    if (question) renderQuestion(question, result);
    else renderFinal(result);
  }

  function open(options) {
    if (closeTimer) {
      globalThis.clearTimeout(closeTimer);
      closeTimer = null;
    }
    active = {
      ...options,
      session: createGuidedReviewSession({
        domain: options.domain || "transaction", group: options.group,
        categories: options.categories, merchants: options.merchants, merchantTypes: options.merchantTypes,
        productCategories: options.productCategories,
        receipt: options.receipt,
      }),
    };
    setupMascot();
    byId("finance-guided-transaction").replaceChildren(...transactionNode());
    render();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  byId("finance-guided-close")?.addEventListener("click", close);
  back?.addEventListener("click", () => { if (active) { active.session = backGuidedReview(active.session); render(); } });
  restart?.addEventListener("click", () => { if (active) { active.session = restartGuidedReview(active.session); render(); } });
  skip?.addEventListener("click", () => {
    if (!active) return;
    const current = getNextGuidedQuestion(active.session);
    const safe = current?.choices.find((item) => item.id === "skip");
    if (safe) active.session = answerGuidedQuestion(active.session, current.id, safe.id);
    render();
  });
  dialog.addEventListener("keydown", (event) => {
    if (!active || event.target.matches?.("input, textarea, select")) return;
    if ((event.key === "Backspace" || (event.altKey && event.key === "ArrowLeft")) && active.session.answers.length) {
      event.preventDefault(); active.session = backGuidedReview(active.session); render(); return;
    }
    if (/^[1-9]$/.test(event.key)) {
      const button = body.querySelectorAll("[data-guided-choice]")[Number(event.key) - 1];
      if (button) { event.preventDefault(); button.click(); }
    }
  });
  dialog.addEventListener("close", () => {
    if (closeTimer) globalThis.clearTimeout(closeTimer);
    closeTimer = null;
    delete dialog.dataset.saving;
    delete dialog.dataset.saved;
    dialog.removeAttribute("aria-busy");
    active = null;
  });

  return { open, close, render, isOpen: () => Boolean(dialog.open || dialog.hasAttribute("open")), getSession: () => active?.session || null };
}
