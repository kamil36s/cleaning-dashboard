import {
  addTodo,
  formatDateInputValue,
  deleteTodo,
  getStats,
  isTodoActiveListVisible,
  listTodos,
  normalizeDueDate,
  parseISODate,
  refreshTodosFromServer,
  sortTodos,
  startOfDay,
  toggleTodo,
  updateTodo,
  BUCKETS,
  TODO_STORE_CHANGED_EVENT,
} from "./todo-store.js";
import { createTodoAnimator } from "./todo-animations.js";

const WIDGET_BUCKET = "now";
const SHOPPING_BUCKET = "shopping";
const DAY_MS = 24 * 60 * 60 * 1000;

const form = document.getElementById("todo-quick-form");
if (!form) {
  // Not on the dashboard page.
  console.warn("todo widget: missing form");
}

const input = document.getElementById("todo-quick-input");
const dateInput = document.getElementById("todo-quick-date");
const list = document.getElementById("todo-quick-list");
const empty = document.getElementById("todo-quick-empty");
const count = document.getElementById("todo-quick-count");
const widget = form?.closest(".todo") ?? null;
const shoppingForm = document.getElementById("todo-shopping-form");
const shoppingInput = document.getElementById("todo-shopping-input");
const shoppingDateInput = document.getElementById("todo-shopping-date");
const shoppingList = document.getElementById("todo-shopping-list");
const shoppingEmpty = document.getElementById("todo-shopping-empty");
const shoppingCount = document.getElementById("todo-shopping-count");
const summary = document.getElementById("todo-summary");
const more = document.getElementById("todo-more");
const toggleDoneBtn = document.getElementById("todo-toggle-done");

let editingId = null;
let showDone = false;
const animator = createTodoAnimator(widget || list);
const bucketLabels = new Map(BUCKETS.map((bucket) => [bucket.id, bucket.label]));

function formatDateShort(iso) {
  return formatDateInputValue(iso);
}

function formatDateLong(iso) {
  const display = formatDateInputValue(iso);
  return display ? `Deadline: ${display}` : "";
}

function setupDateInput(inputEl, ariaLabel = "Deadline") {
  if (!inputEl) return null;
  inputEl.type = "text";
  inputEl.inputMode = "numeric";
  inputEl.autocomplete = "off";
  inputEl.maxLength = 10;
  inputEl.placeholder = "dd/mm/yyyy";
  inputEl.pattern = "[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}";
  inputEl.spellcheck = false;
  inputEl.setAttribute("aria-label", ariaLabel);
  return inputEl;
}

function readDueInput(inputEl, { report = false } = {}) {
  if (!inputEl) return "";
  const raw = inputEl.value.trim();
  if (!raw) {
    inputEl.setCustomValidity("");
    return "";
  }
  const due = normalizeDueDate(raw);
  if (!due) {
    inputEl.setCustomValidity("Wpisz date w formacie dd/mm/yyyy");
    if (report) inputEl.reportValidity();
    return null;
  }
  inputEl.value = formatDateInputValue(due);
  inputEl.setCustomValidity("");
  return due;
}

function handleDateInputEvent(event) {
  const target = event.target;
  if (!target || !target.matches(".todo-date-input")) return;
  if (!target.value.trim() || normalizeDueDate(target.value)) {
    target.setCustomValidity("");
  }
}

function handleDateBlurEvent(event) {
  const target = event.target;
  if (!target || !target.matches(".todo-date-input")) return;
  readDueInput(target);
}

function getDueMeta(item) {
  if (!item.due) return null;
  const dueDate = parseISODate(item.due);
  if (!dueDate) return null;
  if (item.done) {
    return {
      short: formatDateShort(item.due),
      long: formatDateLong(item.due),
      label: "",
      status: "",
    };
  }
  const today = startOfDay(new Date());
  const diffDays = Math.round((dueDate - today) / DAY_MS);
  let label = "";
  let status = "";
  if (diffDays < 0) {
    label = `po terminie ${Math.abs(diffDays)}d`;
    status = "is-overdue";
  } else if (diffDays === 0) {
    label = "dzisiaj";
    status = "is-due";
  } else if (diffDays === 1) {
    label = "jutro";
    status = "is-soon";
  } else if (diffDays <= 7) {
    label = `za ${diffDays} dni`;
    status = "is-soon";
  }
  return {
    short: formatDateShort(item.due),
    long: formatDateLong(item.due),
    label,
    status,
  };
}

function createActionButton(text, action) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "todo-action";
  btn.dataset.action = action;
  btn.textContent = text;
  return btn;
}

function getBucketLabel(bucket) {
  return bucketLabels.get(bucket) || bucket || "";
}

function renderDisplayItem(item) {
  const li = document.createElement("li");
  li.className = "todo-item";
  li.dataset.id = item.id;
  if (item.done) li.classList.add("is-done");

  const dueMeta = getDueMeta(item);
  if (dueMeta?.status) li.classList.add(dueMeta.status);

  const main = document.createElement("div");
  main.className = "todo-main";

  const label = document.createElement("label");
  label.className = "todo-check";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "todo-toggle";
  checkbox.checked = Boolean(item.done);
  checkbox.dataset.action = "toggle";
  const title = document.createElement("span");
  title.className = "todo-title";
  title.textContent = item.title;
  label.append(checkbox, title);

  const meta = document.createElement("div");
  meta.className = "todo-meta";
  if (dueMeta) {
    const date = document.createElement("span");
    date.className = "todo-date";
    date.textContent = dueMeta.short;
    date.title = dueMeta.long;
    meta.appendChild(date);
    if (dueMeta.label) {
      const pill = document.createElement("span");
      pill.className = "todo-pill";
      pill.textContent = dueMeta.label;
      meta.appendChild(pill);
    }
  }

  main.append(label, meta);

  const actions = document.createElement("div");
  actions.className = "todo-actions";
  actions.append(
    createActionButton("Edytuj", "edit"),
    createActionButton("Usuń", "delete"),
  );

  li.append(main, actions);
  return li;
}

function renderEditItem(item) {
  const li = document.createElement("li");
  li.className = "todo-item is-editing";
  li.dataset.id = item.id;

  const formEl = document.createElement("form");
  formEl.className = "todo-edit-form";
  formEl.dataset.id = item.id;

  const inputEl = document.createElement("input");
  inputEl.type = "text";
  inputEl.className = "todo-input";
  inputEl.value = item.title;
  inputEl.maxLength = 120;
  inputEl.required = true;

  const dateEl = document.createElement("input");
  dateEl.className = "todo-date-input";
  setupDateInput(dateEl, "Deadline (dd/mm/yyyy)");
  dateEl.value = formatDateInputValue(item.due);

  const selectEl = document.createElement("select");
  selectEl.className = "todo-select";
  selectEl.name = "bucket";
  BUCKETS.forEach((bucket) => {
    const option = document.createElement("option");
    option.value = bucket.id;
    option.textContent = getBucketLabel(bucket.id);
    if (bucket.id === item.bucket) option.selected = true;
    selectEl.appendChild(option);
  });

  const actions = document.createElement("div");
  actions.className = "todo-edit-actions";

  const save = document.createElement("button");
  save.type = "submit";
  save.className = "todo-action primary";
  save.textContent = "Zapisz";

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "todo-action";
  cancel.dataset.action = "cancel";
  cancel.textContent = "Anuluj";

  actions.append(save, cancel);
  formEl.append(inputEl, dateEl, selectEl, actions);
  li.appendChild(formEl);
  return li;
}

function renderItems(targetList, targetEmpty, targetCount, items) {
  const fragment = document.createDocumentFragment();
  items.forEach((item) => {
    if (item.id === editingId) {
      fragment.appendChild(renderEditItem(item));
    } else {
      fragment.appendChild(renderDisplayItem(item));
    }
  });

  targetList?.replaceChildren(fragment);
  if (targetEmpty) targetEmpty.hidden = items.length > 0;
  if (targetCount) targetCount.textContent = String(items.length);
}

function render() {
  const items = listTodos();
  const visibleItems = showDone ? items : items.filter((item) => isTodoActiveListVisible(item));
  const taskItems = sortTodos(visibleItems.filter((item) => item.bucket === WIDGET_BUCKET));
  const shoppingItems = sortTodos(visibleItems.filter((item) => item.bucket === SHOPPING_BUCKET));

  renderItems(list, empty, count, taskItems);
  renderItems(shoppingList, shoppingEmpty, shoppingCount, shoppingItems);

  const stats = getStats(items);
  const shoppingStats = getStats(items.filter((item) => item.bucket === SHOPPING_BUCKET));
  const parts = [];
  parts.push(`${stats.open} otwarte`);
  if (shoppingStats.open > 0) parts.push(`${shoppingStats.open} zakupów`);
  if (stats.overdue > 0) parts.push(`${stats.overdue} po terminie`);
  summary.textContent = parts.join(" • ");

  const remaining = 0;
  if (remaining > 0) {
    more.hidden = false;
    more.textContent = `+${remaining} więcej`;
  } else {
    more.hidden = true;
  }

  if (toggleDoneBtn) {
    const showLabel = toggleDoneBtn.dataset.labelShow || "Pokaż zrobione";
    const hideLabel = toggleDoneBtn.dataset.labelHide || "Ukryj zrobione";
    toggleDoneBtn.textContent = showDone ? hideLabel : showLabel;
  }

  if (editingId) {
    const focusInput =
      widget?.querySelector(".todo-edit-form .todo-input") ||
      list?.querySelector(".todo-edit-form .todo-input");
    if (focusInput) focusInput.focus();
  }
}

function handleAdd(event, { sourceInput, sourceDateInput, bucket }) {
  event.preventDefault();
  const title = sourceInput?.value.trim() || "";
  if (!title) return;
  const due = readDueInput(sourceDateInput, { report: true });
  if (due === null) return;
  const item = addTodo({ title, due, bucket });
  animator.run(() => {
    event.currentTarget.reset();
    editingId = null;
    render();
  }, { action: "add", highlightId: item?.id ?? null });
}

function handleListClick(event) {
  const actionEl = event.target.closest("[data-action]");
  if (!actionEl) return;
  const itemEl = actionEl.closest(".todo-item");
  if (!itemEl) return;
  const id = itemEl.dataset.id;

  switch (actionEl.dataset.action) {
    case "edit":
      animator.run(() => {
        editingId = id;
        render();
      }, { action: "edit", highlightId: id });
      break;
    case "delete":
      animator.run(() => {
        deleteTodo(id);
        if (editingId === id) editingId = null;
        render();
      }, { action: "delete" });
      break;
    case "cancel":
      animator.run(() => {
        editingId = null;
        render();
      }, { action: "cancel", highlightId: id });
      break;
    default:
      break;
  }
}

function handleListChange(event) {
  const target = event.target;
  if (!target || !target.matches(".todo-toggle")) return;
  const itemEl = target.closest(".todo-item");
  if (!itemEl) return;
  const id = itemEl.dataset.id;
  animator.run(() => {
    toggleTodo(id, target.checked);
    render();
  }, {
    action: target.checked ? "done" : "undone",
    highlightId: id,
  });
}

function handleEditSubmit(event) {
  const formEl = event.target;
  if (!formEl.classList.contains("todo-edit-form")) return;
  event.preventDefault();
  const id = formEl.dataset.id;
  const title = formEl.querySelector(".todo-input")?.value ?? "";
  const dueInput = formEl.querySelector(".todo-date-input");
  const due = readDueInput(dueInput, { report: true });
  const bucket = formEl.querySelector(".todo-select")?.value;
  if (due === null) return;
  animator.run(() => {
    updateTodo(id, { title, due, bucket });
    editingId = null;
    render();
  }, { action: "save", highlightId: id });
}

if (form) {
  setupDateInput(dateInput, "Deadline (dd/mm/yyyy)");
  setupDateInput(shoppingDateInput, "Deadline (dd/mm/yyyy)");
  form.addEventListener("submit", (event) => {
    handleAdd(event, { sourceInput: input, sourceDateInput: dateInput, bucket: WIDGET_BUCKET });
  });
  shoppingForm?.addEventListener("submit", (event) => {
    handleAdd(event, {
      sourceInput: shoppingInput,
      sourceDateInput: shoppingDateInput,
      bucket: SHOPPING_BUCKET,
    });
  });
  form.addEventListener("input", handleDateInputEvent);
  form.addEventListener("focusout", handleDateBlurEvent);
  shoppingForm?.addEventListener("input", handleDateInputEvent);
  shoppingForm?.addEventListener("focusout", handleDateBlurEvent);
  widget?.addEventListener("click", handleListClick);
  widget?.addEventListener("change", handleListChange);
  widget?.addEventListener("submit", handleEditSubmit);
  widget?.addEventListener("input", handleDateInputEvent);
  widget?.addEventListener("focusout", handleDateBlurEvent);

  if (toggleDoneBtn) {
    toggleDoneBtn.addEventListener("click", () => {
      animator.run(() => {
        showDone = !showDone;
        render();
      }, { action: showDone ? "hide-done" : "show-done" });
    });
  }

  render();
  window.addEventListener(TODO_STORE_CHANGED_EVENT, render);
  setInterval(() => {
    if (!document.hidden) refreshTodosFromServer().catch(() => {});
  }, 15000);
}
