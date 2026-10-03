import {
  BILLS_STORE_CHANGED_EVENT,
  BILLS_FORECAST_END_MONTH,
  addCustomBill,
  cancelSubscription,
  formatBillDate,
  formatMoney,
  getAverageMonthlyPlannedCents,
  getAverageMonthlyRemainingCents,
  getBillsRequiringAttention,
  getBillsState,
  getBillStatus,
  getMonthlyBillSummaries,
  getNextUnpaidManualBill,
  getTotalOutstandingCents,
  listBills,
  removeCustomBill,
  setBillPaid,
  setBillsNotificationsEnabled,
} from "./bills-store.js";

const NOTIFICATION_LOG_KEY = "todo-bills-notified-v1";
const panels = [...document.querySelectorAll("[data-bills-panel]")];
const floatingTooltips = new WeakMap();

function currentMonthKey(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function nextMonthKey(date = new Date()) {
  return currentMonthKey(new Date(date.getFullYear(), date.getMonth() + 1, 1));
}

function formatMonth(month) {
  const [year, monthNumber] = month.split("-").map(Number);
  const label = new Intl.DateTimeFormat("pl-PL", { month: "long", year: "numeric" })
    .format(new Date(year, monthNumber - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function positionBillsTooltip(tooltip, clientX, clientY) {
  const edgeGap = 8;
  const pointerGap = 16;
  const rect = tooltip.getBoundingClientRect();
  let left = clientX + pointerGap;
  let top = clientY + pointerGap;

  if (left + rect.width > window.innerWidth - edgeGap) {
    left = clientX - rect.width - pointerGap;
  }
  if (top + rect.height > window.innerHeight - edgeGap) {
    top = clientY - rect.height - pointerGap;
  }

  tooltip.style.left = `${Math.max(edgeGap, left)}px`;
  tooltip.style.top = `${Math.max(edgeGap, top)}px`;
}

function initBillsTooltip(panel) {
  const trigger = panel.querySelector(".bills-overview-total");
  const tooltip = panel.querySelector(".bills-total-tooltip");
  if (!trigger || !tooltip) return;

  document.body.appendChild(tooltip);
  floatingTooltips.set(panel, tooltip);

  const showAtPointer = (event) => {
    tooltip.classList.add("is-visible");
    positionBillsTooltip(tooltip, event.clientX, event.clientY);
  };
  const hide = () => tooltip.classList.remove("is-visible");

  trigger.addEventListener("pointerenter", showAtPointer);
  trigger.addEventListener("pointermove", showAtPointer);
  trigger.addEventListener("pointerleave", hide);
  trigger.addEventListener("focus", () => {
    const rect = trigger.getBoundingClientRect();
    tooltip.classList.add("is-visible");
    positionBillsTooltip(tooltip, rect.right, rect.top + rect.height / 2);
  });
  trigger.addEventListener("blur", hide);
  window.addEventListener("scroll", hide, { passive: true });
}

function pickInitialMonth(summaries) {
  const todayMonth = currentMonthKey();
  return summaries.find((summary) => summary.month === todayMonth)?.month
    || summaries.find((summary) => summary.month > todayMonth)?.month
    || summaries.at(-1)?.month
    || "";
}

function createBillItem(bill) {
  const status = getBillStatus(bill);
  const item = document.createElement("li");
  item.className = `bills-item is-${status.key}`;
  item.dataset.billId = bill.id;

  const check = document.createElement("label");
  check.className = "bills-check";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.className = "todo-toggle bills-paid-toggle";
  input.checked = bill.paid;
  input.disabled = Boolean(bill.automatic);
  input.setAttribute(
    "aria-label",
    bill.automatic
      ? `Płatność automatyczna: ${bill.name}`
      : `${bill.paid ? "Cofnij opłacenie" : "Oznacz jako opłacone"}: ${bill.name}`,
  );
  const copy = document.createElement("span");
  copy.className = "bills-copy";
  const title = document.createElement("strong");
  title.className = "bills-title";
  title.textContent = bill.name;
  title.title = bill.name;
  const provider = document.createElement("span");
  provider.className = "bills-provider";
  const providerDetails = [bill.provider, bill.category, bill.note].filter(Boolean).join(" · ");
  provider.textContent = providerDetails;
  provider.title = providerDetails;
  copy.append(title, provider);
  check.append(input, copy);

  const amount = document.createElement("strong");
  amount.className = "bills-amount";
  amount.textContent = formatMoney(bill.amountCents);

  const side = document.createElement("div");
  side.className = "bills-side";
  side.classList.toggle("has-cancel", Boolean(bill.subscriptionId || bill.customId));
  side.appendChild(amount);
  if (bill.subscriptionId || bill.customId) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "bills-cancel-subscription";
    if (bill.subscriptionId) cancel.dataset.billsCancelSubscription = bill.subscriptionId;
    if (bill.customId) cancel.dataset.billsRemoveCustom = bill.customId;
    cancel.textContent = "×";
    const removeLabel = bill.subscriptionId ? "Usuń subskrypcję" : "Usuń płatność";
    cancel.title = `${removeLabel} ${bill.name}`;
    cancel.setAttribute("aria-label", `${removeLabel} ${bill.name}`);
    side.appendChild(cancel);
  }

  const meta = document.createElement("div");
  meta.className = "bills-meta";
  const due = document.createElement("span");
  due.textContent = `Termin ${formatBillDate(bill.due)}`;
  const countdown = document.createElement("span");
  countdown.className = "bills-countdown";
  countdown.textContent = status.daysLabel;
  const pill = document.createElement("span");
  pill.className = "bills-status";
  pill.textContent = status.label;
  meta.append(due, countdown, pill);

  item.append(check, side, meta);
  return item;
}

function renderMonthStrip(panel, summaries, selectedMonth) {
  const strip = panel.querySelector("[data-bills-months]");
  if (!strip) return;
  const fragment = document.createDocumentFragment();
  const selectedIndex = Math.max(0, summaries.findIndex((summary) => summary.month === selectedMonth));
  const windowSize = Math.min(5, summaries.length);
  const windowStart = Math.max(0, Math.min(
    selectedIndex - Math.floor(windowSize / 2),
    summaries.length - windowSize,
  ));
  const visibleSummaries = summaries.slice(windowStart, windowStart + windowSize);

  const createArrow = ({ label, targetMonth, disabled }) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "bills-month-arrow";
    button.disabled = disabled;
    button.textContent = label === "Poprzedni miesiąc" ? "‹" : "›";
    button.setAttribute("aria-label", label);
    if (targetMonth) button.dataset.month = targetMonth;
    return button;
  };

  fragment.appendChild(createArrow({
    label: "Poprzedni miesiąc",
    targetMonth: summaries[selectedIndex - 1]?.month,
    disabled: selectedIndex <= 0,
  }));

  visibleSummaries.forEach((summary) => {
    const summaryIndex = summaries.indexOf(summary);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "bills-month";
    button.classList.toggle("is-far", Math.abs(summaryIndex - selectedIndex) > 1);
    button.classList.toggle("has-payments", summary.remainingCents < summary.plannedCents);
    button.dataset.month = summary.month;
    button.classList.toggle("is-selected", summary.month === selectedMonth);
    button.setAttribute("aria-pressed", String(summary.month === selectedMonth));
    button.title = `${formatMonth(summary.month)} · plan ${formatMoney(summary.plannedCents)} · pozostało ${formatMoney(summary.remainingCents)}`;

    const label = document.createElement("span");
    label.textContent = formatMonth(summary.month);
    const values = document.createElement("div");
    values.className = "bills-month-values";
    const total = document.createElement("strong");
    total.textContent = formatMoney(summary.plannedCents);
    const remaining = document.createElement("small");
    remaining.textContent = summary.remainingCents > 0
      ? `Pozostało ${formatMoney(summary.remainingCents)}`
      : "Rozliczone";
    values.append(total, remaining);
    button.append(label, values);
    fragment.appendChild(button);
  });

  fragment.appendChild(createArrow({
    label: "Następny miesiąc",
    targetMonth: summaries[selectedIndex + 1]?.month,
    disabled: selectedIndex >= summaries.length - 1,
  }));
  strip.replaceChildren(fragment);
}

function renderNotificationButton(panel) {
  const button = panel.querySelector("[data-bills-notifications]");
  if (!button) return;
  const supported = typeof Notification !== "undefined";
  const enabled = supported
    && getBillsState().notificationsEnabled
    && Notification.permission === "granted";
  button.disabled = !supported || (supported && Notification.permission === "denied");
  button.classList.toggle("is-enabled", enabled);
  if (!supported) button.textContent = "Powiadomienia niedostępne";
  else if (Notification.permission === "denied") button.textContent = "Powiadomienia zablokowane";
  else button.textContent = enabled ? "Powiadomienia włączone" : "Włącz powiadomienia";
}

function renderPanel(panel) {
  const bills = listBills();
  const summaries = getMonthlyBillSummaries(bills);
  if (!summaries.some((summary) => summary.month === panel.dataset.selectedMonth)) {
    panel.dataset.selectedMonth = pickInitialMonth(summaries);
  }
  const selectedMonth = panel.dataset.selectedMonth;
  const monthSummary = summaries.find((summary) => summary.month === selectedMonth);
  const monthBills = bills.filter((bill) => bill.month === selectedMonth);
  const showDone = panel.dataset.showDone === "true";
  const showAutomatic = panel.dataset.showAutomatic !== "false";
  const showRegular = panel.dataset.showRegular !== "false";
  const typeFilteredMonthBills = monthBills.filter((bill) => (
    bill.automatic ? showAutomatic : showRegular
  ));
  const visibleMonthBills = showDone
    ? typeFilteredMonthBills
    : typeFilteredMonthBills.filter((bill) => !bill.paid);
  const attention = getBillsRequiringAttention(bills);
  const nextManualPayment = getNextUnpaidManualBill(bills);

  const openCount = panel.querySelector("[data-bills-open]");
  if (openCount) {
    openCount.textContent = attention.length
      ? `${attention.length} do zapłaty`
      : `${bills.length} w planie`;
  }

  const reminder = panel.querySelector("[data-bills-reminder]");
  if (reminder) {
    reminder.className = "bills-reminder";
    if (attention.length) {
      const first = attention[0];
      reminder.classList.add(`is-${first.status.key}`);
      reminder.textContent = `${attention.length} ${attention.length === 1 ? "płatność wymaga" : "płatności wymagają"} uwagi. Najbliżej: ${first.bill.name} — ${first.status.daysLabel}.`;
    } else {
      if (nextManualPayment) {
        const { bill, status } = nextManualPayment;
        const timeLabel = status.days === 0
          ? "dzisiaj"
          : `za ${status.days} ${status.days === 1 ? "dzień" : "dni"}`;
        reminder.textContent = `Następna płatność nieautomatyczna ${timeLabel}: ${bill.name} · ${formatMoney(bill.amountCents)}.`;
      } else {
        reminder.textContent = "Brak kolejnych nieautomatycznych płatności w harmonogramie.";
      }
    }
  }

  const planned = panel.querySelector("[data-bills-planned]");
  if (planned) planned.textContent = formatMoney(monthSummary?.plannedCents || 0);
  const remaining = panel.querySelector("[data-bills-remaining]");
  if (remaining) remaining.textContent = formatMoney(monthSummary?.remainingCents || 0);
  const totalOutstanding = getTotalOutstandingCents(bills);
  const totalOutstandingElement = panel.querySelector("[data-bills-total-outstanding]");
  if (totalOutstandingElement) {
    totalOutstandingElement.textContent = formatMoney(totalOutstanding);
  }
  const monthlyAverageElement = panel.querySelector("[data-bills-monthly-average]");
  const monthlyRemainingAverageElement = floatingTooltips.get(panel)
    ?.querySelector("[data-bills-monthly-remaining-average]");
  const forecastStartMonth = currentMonthKey();
  const remainingForecastStartMonth = nextMonthKey();
  if (monthlyAverageElement) {
    const monthlyAverage = getAverageMonthlyPlannedCents(
      bills,
      forecastStartMonth,
      BILLS_FORECAST_END_MONTH,
    );
    monthlyAverageElement.textContent = formatMoney(monthlyAverage);
  }
  if (monthlyRemainingAverageElement) {
    const monthlyRemainingAverage = getAverageMonthlyRemainingCents(
      bills,
      remainingForecastStartMonth,
      BILLS_FORECAST_END_MONTH,
    );
    monthlyRemainingAverageElement.textContent = formatMoney(monthlyRemainingAverage);
  }
  panel.querySelectorAll("[data-bills-category]").forEach((element) => {
    const category = element.dataset.billsCategory;
    element.textContent = formatMoney(monthSummary?.categoryTotals?.[category] || 0);
  });

  const toggleDone = panel.querySelector("[data-bills-toggle-done]");
  if (toggleDone) {
    toggleDone.textContent = showDone ? "Ukryj zrobione" : "Pokaż zrobione";
    toggleDone.setAttribute("aria-pressed", String(showDone));
  }

  panel.querySelectorAll("[data-bills-view-filter]").forEach((button) => {
    const automatic = button.dataset.billsViewFilter === "automatic";
    const visible = automatic ? showAutomatic : showRegular;
    const label = automatic ? "automatyczne" : "zwykłe";
    button.textContent = `${visible ? "Ukryj" : "Pokaż"} ${label}`;
    button.classList.toggle("is-visible", visible);
    button.setAttribute("aria-pressed", String(visible));
  });

  renderMonthStrip(panel, summaries, selectedMonth);

  const list = panel.querySelector("[data-bills-list]");
  if (list) {
    const fragment = document.createDocumentFragment();
    visibleMonthBills.forEach((bill) => fragment.appendChild(createBillItem(bill)));
    list.replaceChildren(fragment);
  }
  const empty = panel.querySelector("[data-bills-empty]");
  if (empty) {
    empty.hidden = visibleMonthBills.length > 0;
    if (!monthBills.length) empty.textContent = "Brak płatności w tym miesiącu.";
    else if (!typeFilteredMonthBills.length) empty.textContent = "Wybrane typy płatności są teraz ukryte.";
    else empty.textContent = "Wszystkie widoczne płatności w tym miesiącu są rozliczone.";
  }
  renderNotificationButton(panel);
}

function ensureCancelDialog(panel) {
  let dialog = panel.querySelector("[data-bills-cancel-dialog]");
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.className = "bills-cancel-dialog";
  dialog.dataset.billsCancelDialog = "";

  const title = document.createElement("h3");
  title.dataset.billsCancelTitle = "";
  title.textContent = "Usunąć subskrypcję?";
  const message = document.createElement("p");
  message.dataset.billsCancelMessage = "";
  const warning = document.createElement("p");
  warning.className = "bills-cancel-warning";
  warning.textContent = "To usuwa subskrypcję tylko z tego widgetu — nie anuluje jej u usługodawcy.";
  const actions = document.createElement("div");
  actions.className = "bills-cancel-actions";
  const no = document.createElement("button");
  no.type = "button";
  no.className = "todo-ghost-btn";
  no.dataset.billsCancelNo = "";
  no.textContent = "Nie";
  const yes = document.createElement("button");
  yes.type = "button";
  yes.className = "todo-ghost-btn bills-cancel-confirm";
  yes.dataset.billsCancelYes = "";
  yes.textContent = "Tak";
  actions.append(no, yes);
  dialog.append(title, message, warning, actions);
  panel.appendChild(dialog);
  return dialog;
}

function openCancelDialog(panel, bill) {
  const dialog = ensureCancelDialog(panel);
  delete dialog.dataset.customId;
  dialog.dataset.subscriptionId = bill.subscriptionId;
  const title = dialog.querySelector("[data-bills-cancel-title]");
  if (title) title.textContent = "Usunąć subskrypcję?";
  const message = dialog.querySelector("[data-bills-cancel-message]");
  if (message) {
    message.textContent = `Czy na pewno subskrypcja „${bill.name}” została anulowana i chcesz usunąć ją z miesięcznych kosztów?`;
  }
  const warning = dialog.querySelector(".bills-cancel-warning");
  if (warning) warning.textContent = "To usuwa subskrypcję tylko z tego widgetu — nie anuluje jej u usługodawcy.";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function openCustomBillRemoveDialog(panel, bill) {
  const dialog = ensureCancelDialog(panel);
  delete dialog.dataset.subscriptionId;
  dialog.dataset.customId = bill.customId;
  const title = dialog.querySelector("[data-bills-cancel-title]");
  if (title) title.textContent = "Usunąć płatność?";
  const message = dialog.querySelector("[data-bills-cancel-message]");
  if (message) {
    message.textContent = bill.id === bill.customId
      ? `Czy na pewno chcesz usunąć płatność „${bill.name}”?`
      : `Czy na pewno chcesz usunąć płatność „${bill.name}” wraz z całą miesięczną serią?`;
  }
  const warning = dialog.querySelector(".bills-cancel-warning");
  if (warning) warning.textContent = "Tej operacji nie można cofnąć.";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function defaultDueDate(panel) {
  const selectedMonth = panel.dataset.selectedMonth;
  const today = new Date();
  if (!/^\d{4}-\d{2}$/.test(selectedMonth || "")) {
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  }
  const [year, month] = selectedMonth.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  return `${selectedMonth}-${String(Math.min(today.getDate(), lastDay)).padStart(2, "0")}`;
}

function ensureAddDialog(panel) {
  let dialog = panel.querySelector("[data-bills-add-dialog]");
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.className = "bills-add-dialog";
  dialog.dataset.billsAddDialog = "";
  dialog.innerHTML = `
    <form method="dialog" data-bills-add-form>
      <div class="bills-add-heading">
        <div>
          <h3>Nowa płatność</h3>
          <p>Dodana pozycja pojawi się w harmonogramie i podsumowaniach.</p>
        </div>
        <button type="button" class="bills-add-close" data-bills-add-close aria-label="Zamknij">×</button>
      </div>
      <div class="bills-add-grid">
        <label class="bills-add-field bills-add-field-wide">
          <span>Nazwa</span>
          <input name="name" type="text" maxlength="120" autocomplete="off" required placeholder="np. Ubezpieczenie mieszkania">
        </label>
        <label class="bills-add-field">
          <span>Kwota</span>
          <div class="bills-amount-input"><input name="amount" type="text" inputmode="decimal" autocomplete="off" required placeholder="0,00"><span>zł</span></div>
        </label>
        <label class="bills-add-field">
          <span>Termin</span>
          <input name="due" type="date" required>
        </label>
        <label class="bills-add-field">
          <span>Kategoria</span>
          <select name="category">
            <option value="Mieszkanie">Rachunki</option>
            <option value="Raty">Raty</option>
            <option value="Subskrypcje">Subskrypcje</option>
          </select>
        </label>
        <label class="bills-add-field">
          <span>Powtarzanie</span>
          <select name="recurrence" data-bills-recurrence>
            <option value="once">Jednorazowo</option>
            <option value="monthly">Co miesiąc</option>
          </select>
        </label>
        <label class="bills-add-field bills-add-end" data-bills-end-field hidden>
          <span>Ostatni miesiąc <small>(opcjonalnie)</small></span>
          <input name="endMonth" type="month">
        </label>
        <label class="bills-add-field bills-add-field-wide">
          <span>Usługodawca <small>(opcjonalnie)</small></span>
          <input name="provider" type="text" maxlength="120" autocomplete="off" placeholder="np. PZU">
        </label>
        <label class="bills-add-check bills-add-field-wide">
          <input name="automatic" type="checkbox">
          <span>Płatność pobierana automatycznie</span>
        </label>
      </div>
      <p class="bills-add-error" data-bills-add-error aria-live="polite"></p>
      <div class="bills-add-actions">
        <button class="todo-ghost-btn" type="button" data-bills-add-close>Anuluj</button>
        <button class="todo-ghost-btn bills-add-submit" type="submit">Dodaj płatność</button>
      </div>
    </form>`;
  panel.appendChild(dialog);
  return dialog;
}

function openAddDialog(panel) {
  const dialog = ensureAddDialog(panel);
  const form = dialog.querySelector("[data-bills-add-form]");
  form.reset();
  form.elements.due.value = defaultDueDate(panel);
  dialog.querySelector("[data-bills-end-field]").hidden = true;
  dialog.querySelector("[data-bills-add-error]").textContent = "";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  requestAnimationFrame(() => form.elements.name.focus());
}

function parseAmountCents(value) {
  const normalized = String(value || "").trim().replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return null;
  const amountCents = Math.round(Number(normalized) * 100);
  return amountCents > 0 ? amountCents : null;
}

function submitAddForm(panel, form) {
  const amountCents = parseAmountCents(form.elements.amount.value);
  const error = form.querySelector("[data-bills-add-error]");
  if (!amountCents) {
    error.textContent = "Wpisz poprawną kwotę większą od zera.";
    form.elements.amount.focus();
    return;
  }
  const startMonth = form.elements.due.value.slice(0, 7);
  if (form.elements.endMonth.value && form.elements.endMonth.value < startMonth) {
    error.textContent = "Ostatni miesiąc nie może być wcześniejszy niż pierwszy termin.";
    form.elements.endMonth.focus();
    return;
  }
  panel.dataset.selectedMonth = startMonth;
  const bill = addCustomBill({
    name: form.elements.name.value,
    provider: form.elements.provider.value,
    category: form.elements.category.value,
    amountCents,
    due: form.elements.due.value,
    recurrence: form.elements.recurrence.value,
    endMonth: form.elements.endMonth.value,
    automatic: form.elements.automatic.checked,
  });
  if (!bill) {
    error.textContent = "Nie udało się dodać płatności. Sprawdź formularz.";
    return;
  }
  closeCancelDialog(form.closest("dialog"));
}

function closeCancelDialog(dialog) {
  if (!dialog) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

function notificationDateKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function maybeNotify() {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  if (!getBillsState().notificationsEnabled) return;
  const attention = getBillsRequiringAttention();
  if (!attention.length) return;
  const notificationKey = `${notificationDateKey()}:${attention.map(({ bill, status }) => `${bill.id}-${status.key}`).join("|")}`;
  try {
    if (localStorage.getItem(NOTIFICATION_LOG_KEY) === notificationKey) return;
    const body = attention
      .slice(0, 3)
      .map(({ bill, status }) => `${bill.name}: ${status.daysLabel}`)
      .join("\n");
    new Notification(`Rachunki: ${attention.length} ${attention.length === 1 ? "płatność" : "płatności"} do sprawdzenia`, {
      body,
      tag: "cleaning-dashboard-bills",
    });
    localStorage.setItem(NOTIFICATION_LOG_KEY, notificationKey);
  } catch {}
}

async function toggleNotifications(panel) {
  if (typeof Notification === "undefined" || Notification.permission === "denied") return;
  const enabled = getBillsState().notificationsEnabled && Notification.permission === "granted";
  if (enabled) {
    setBillsNotificationsEnabled(false);
    return;
  }
  const permission = Notification.permission === "granted"
    ? "granted"
    : await Notification.requestPermission();
  setBillsNotificationsEnabled(permission === "granted");
  renderPanel(panel);
  maybeNotify();
}

panels.forEach((panel) => {
  initBillsTooltip(panel);
  panel.addEventListener("click", (event) => {
    const addButton = event.target.closest?.("[data-bills-add]");
    if (addButton && panel.contains(addButton)) {
      openAddDialog(panel);
      return;
    }
    if (event.target.closest?.("[data-bills-add-close]")) {
      closeCancelDialog(event.target.closest("dialog"));
      return;
    }
    const removeCustomButton = event.target.closest?.("[data-bills-remove-custom]");
    if (removeCustomButton && panel.contains(removeCustomButton)) {
      const bill = listBills().find((entry) => entry.customId === removeCustomButton.dataset.billsRemoveCustom);
      if (bill) openCustomBillRemoveDialog(panel, bill);
      return;
    }
    const cancelButton = event.target.closest?.("[data-bills-cancel-subscription]");
    if (cancelButton && panel.contains(cancelButton)) {
      const bill = listBills().find((entry) => entry.subscriptionId === cancelButton.dataset.billsCancelSubscription);
      if (bill) openCancelDialog(panel, bill);
      return;
    }
    const dialog = event.target.closest?.("[data-bills-cancel-dialog]");
    if (event.target.closest?.("[data-bills-cancel-no]")) {
      closeCancelDialog(dialog);
      return;
    }
    if (event.target.closest?.("[data-bills-cancel-yes]")) {
      const subscriptionId = dialog?.dataset.subscriptionId;
      const customId = dialog?.dataset.customId;
      if (subscriptionId) cancelSubscription(subscriptionId);
      if (customId) removeCustomBill(customId);
      closeCancelDialog(dialog);
      return;
    }
    const toggleDoneButton = event.target.closest?.("[data-bills-toggle-done]");
    if (toggleDoneButton && panel.contains(toggleDoneButton)) {
      panel.dataset.showDone = String(panel.dataset.showDone !== "true");
      renderPanel(panel);
      return;
    }
    const viewFilterButton = event.target.closest?.("[data-bills-view-filter]");
    if (viewFilterButton && panel.contains(viewFilterButton)) {
      const automatic = viewFilterButton.dataset.billsViewFilter === "automatic";
      const datasetKey = automatic ? "showAutomatic" : "showRegular";
      const visible = panel.dataset[datasetKey] !== "false";
      panel.dataset[datasetKey] = String(!visible);
      renderPanel(panel);
      return;
    }
    const monthButton = event.target.closest("[data-month]");
    if (monthButton && panel.contains(monthButton)) {
      panel.dataset.selectedMonth = monthButton.dataset.month;
      renderPanel(panel);
      return;
    }
    const notificationsButton = event.target.closest("[data-bills-notifications]");
    if (notificationsButton && panel.contains(notificationsButton)) {
      toggleNotifications(panel).catch(() => {});
    }
  });

  panel.addEventListener("change", (event) => {
    const target = event.target;
    if (target?.matches("[data-bills-recurrence]")) {
      const dialog = target.closest("[data-bills-add-dialog]");
      const endField = dialog?.querySelector("[data-bills-end-field]");
      if (endField) endField.hidden = target.value !== "monthly";
      return;
    }
    if (!target?.matches(".bills-paid-toggle")) return;
    const item = target.closest("[data-bill-id]");
    if (!item) return;
    setBillPaid(item.dataset.billId, target.checked);
  });

  panel.addEventListener("submit", (event) => {
    const form = event.target.closest?.("[data-bills-add-form]");
    if (!form) return;
    event.preventDefault();
    submitAddForm(panel, form);
  });

  renderPanel(panel);
});

window.addEventListener(BILLS_STORE_CHANGED_EVENT, () => {
  panels.forEach(renderPanel);
  maybeNotify();
});

maybeNotify();
