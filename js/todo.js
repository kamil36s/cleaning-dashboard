import {
  addTodo,
  addSubtask,
  clearDone,
  deleteSubtask,
  deleteTodo,
  ensureBacklogSeeded,
  formatDateInputValue,
  getStats,
  isTodoActiveListVisible,
  listTodos,
  normalizeDueDate,
  parseISODate,
  sortProjects,
  sortTodos,
  startOfDay,
  toggleSubtask,
  toggleTodo,
  todoStoreReady,
  updateSubtask,
  updateTodo,
  BUCKETS,
  PRIORITIES,
  TODO_STORE_CHANGED_EVENT,
} from "./todo-store.js";
import { createTodoAnimator } from "./todo-animations.js";

const DAY_MS = 24 * 60 * 60 * 1000;
const EXPANDED_KEY = "todo-expanded-projects-v1";

const layout = document.querySelector(".todo-layout") || document.querySelector(".todo-board");
if (!layout) {
  console.warn("todo page: missing layout");
}

const backBtn = document.getElementById("todo-back");
const clearBtn = document.getElementById("todo-clear-done");
const filterDone = document.getElementById("todo-filter-done");
const filterDeadline = document.getElementById("todo-filter-deadline");

const kpiOpen = document.getElementById("todo-kpi-open");
const kpiOverdue = document.getElementById("todo-kpi-overdue");
const kpiDone = document.getElementById("todo-kpi-done");
const kpiTotal = document.getElementById("todo-kpi-total");

let showDone = Boolean(filterDone?.checked);
let onlyDeadline = Boolean(filterDeadline?.checked);
let editingId = null;
let editingProjectId = null;
let editingSubtaskId = null; // { projectId, subtaskId }
let addingSubtaskProjectId = null; // projectId

const animator = createTodoAnimator(layout);

function getExpandedProjectIds() {
  if (typeof localStorage === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(EXPANDED_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function saveExpandedProjectIds(set) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(EXPANDED_KEY, JSON.stringify(Array.from(set)));
  } catch {}
}

let expandedProjectIds = getExpandedProjectIds();

const bucketMap = new Map();

if (layout) {
  ["now", "shopping"].forEach((bucketId) => {
    const column = layout.querySelector(`.todo-column[data-bucket="${bucketId}"]`);
    if (!column) return;
    bucketMap.set(bucketId, {
      column,
      label: column.dataset.label || bucketId,
      list: column.querySelector(".todo-list"),
      empty: column.querySelector(".todo-empty"),
      count: column.querySelector(".todo-column-count"),
    });
  });
}

const projectsSection = layout?.querySelector(".todo-projects-section");
const projectsCount = document.getElementById("todo-projects-count");
const projectsContainer = document.getElementById("todo-projects-container");
const projectsEmpty = document.getElementById("todo-projects-empty");

const PRIORITY_LABELS = {
  P0: "P0 — Fundament",
  P1: "P1 — Wysoki",
  P2: "P2 — Średni",
  P3: "P3 — Później",
  P4: "P4 — Backlog",
};

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

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

function escapeIcsText(text) {
  return String(text || "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\n/g, "\\n");
}

function formatIcsDate(iso) {
  return iso.replace(/-/g, "");
}

function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function toIcsTimestamp(date) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function buildIcs(item) {
  if (!item?.due) return null;
  const startDate = parseISODate(item.due);
  if (!startDate) return null;
  const start = formatIcsDate(item.due);
  const endDate = addDays(startDate, 1);
  const end = formatIcsDate(
    `${endDate.getFullYear()}-${String(endDate.getMonth() + 1).padStart(2, "0")}-${String(
      endDate.getDate(),
    ).padStart(2, "0")}`,
  );

  const summary = escapeIcsText(item.title);
  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Cleaning Dashboard//TODO//PL",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${item.id}@cleaning-dashboard`,
    `DTSTAMP:${toIcsTimestamp(new Date())}`,
    `SUMMARY:${summary}`,
    `DTSTART;VALUE=DATE:${start}`,
    `DTEND;VALUE=DATE:${end}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
}

function downloadIcs(item) {
  const ics = buildIcs(item);
  if (!ics) return;
  const blob = new Blob([ics], { type: "text/calendar" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeName = item.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
  link.href = url;
  link.download = `todo-${safeName || "task"}.ics`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function createActionButton(text, action, extraClass = "") {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `todo-action ${extraClass}`.trim();
  btn.dataset.action = action;
  btn.textContent = text;
  return btn;
}

// Render regular tasks / shopping item
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
  if (item.due) {
    actions.append(createActionButton("Kalendarz", "ics"));
  }

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
    const label = bucketMap.get(bucket.id)?.label || bucket.id;
    option.value = bucket.id;
    option.textContent = label;
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

// Render project card
function renderProjectCard(project) {
  const card = document.createElement("div");
  card.className = "todo-project-card";
  card.dataset.id = project.id;
  if (project.done) card.classList.add("is-done");

  const isExpanded = expandedProjectIds.has(project.id);
  card.classList.add(isExpanded ? "is-expanded" : "is-collapsed");

  const subtasks = Array.isArray(project.subtasks) ? project.subtasks : [];
  const totalCount = subtasks.length;
  const doneCount = subtasks.filter((st) => st.done).length;
  const percent = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : (project.done ? 100 : 0);

  let progressText = "";
  if (totalCount > 0) {
    if (doneCount === totalCount) {
      progressText = `${totalCount} / ${totalCount} • Done`;
    } else {
      progressText = `${doneCount} / ${totalCount}`;
    }
  } else {
    progressText = project.done ? "Done" : "0 subtasków";
  }

  const dueMeta = getDueMeta(project);

  // Header
  const header = document.createElement("div");
  header.className = "todo-project-header";
  header.dataset.action = "toggle-expand";

  const headerLeft = document.createElement("div");
  headerLeft.className = "todo-project-header-left";

  const toggleIcon = document.createElement("span");
  toggleIcon.className = "todo-project-toggle-icon";
  toggleIcon.textContent = isExpanded ? "▾" : "▸";

  const prioBadge = document.createElement("span");
  prioBadge.className = `todo-priority-badge ${(project.priority || "P3").toLowerCase()}`;
  prioBadge.textContent = project.priority || "P3";

  const titleEl = document.createElement("span");
  titleEl.className = "todo-project-title";
  titleEl.textContent = project.title;

  headerLeft.append(toggleIcon, prioBadge, titleEl);

  if (dueMeta) {
    const dueEl = document.createElement("span");
    dueEl.className = "todo-date";
    dueEl.textContent = dueMeta.short;
    dueEl.title = dueMeta.long;
    headerLeft.appendChild(dueEl);
    if (dueMeta.label) {
      const pill = document.createElement("span");
      pill.className = `todo-pill ${dueMeta.status || ""}`.trim();
      pill.textContent = dueMeta.label;
      headerLeft.appendChild(pill);
    }
  }

  const headerRight = document.createElement("div");
  headerRight.className = "todo-project-header-right";

  const progressPill = document.createElement("div");
  progressPill.className = "todo-project-progress-pill";

  const progressLabel = document.createElement("span");
  progressLabel.textContent = progressText;

  const progressBar = document.createElement("div");
  progressBar.className = "todo-project-progress-bar";
  const progressFill = document.createElement("div");
  progressFill.className = "todo-project-progress-fill";
  progressFill.style.width = `${percent}%`;
  progressBar.appendChild(progressFill);

  progressPill.append(progressLabel, progressBar);

  const expandBtn = createActionButton(isExpanded ? "Zwiń" : "Rozwiń", "toggle-expand");
  const editBtn = createActionButton("Edytuj", "edit-project");
  const deleteBtn = createActionButton("Usuń", "delete-project");

  headerRight.append(progressPill, expandBtn, editBtn, deleteBtn);
  if (project.due) {
    headerRight.append(createActionButton("Kalendarz", "ics"));
  }

  header.append(headerLeft, headerRight);
  card.appendChild(header);

  // Body (if expanded)
  if (isExpanded) {
    const body = document.createElement("div");
    body.className = "todo-project-body";

    if (project.description) {
      const descEl = document.createElement("div");
      descEl.className = "todo-project-desc";
      descEl.textContent = project.description;
      body.appendChild(descEl);
    }

    const subtasksHeader = document.createElement("div");
    subtasksHeader.className = "todo-subtasks-header";
    subtasksHeader.innerHTML = `<span>Subtaski (${doneCount} / ${totalCount}) • ${percent}%</span>`;
    body.appendChild(subtasksHeader);

    const subtasksList = document.createElement("ul");
    subtasksList.className = "todo-subtasks-list";

    subtasks.forEach((st) => {
      const isEditingSubtask =
        editingSubtaskId &&
        editingSubtaskId.projectId === project.id &&
        editingSubtaskId.subtaskId === st.id;

      if (isEditingSubtask) {
        const editLi = document.createElement("li");
        editLi.className = "todo-subtask-item is-editing";

        const editForm = document.createElement("form");
        editForm.className = "todo-subtask-form";
        editForm.dataset.projectId = project.id;
        editForm.dataset.subtaskId = st.id;

        const titleInput = document.createElement("input");
        titleInput.type = "text";
        titleInput.className = "todo-input";
        titleInput.value = st.title;
        titleInput.required = true;
        titleInput.placeholder = "Nazwa subtasku...";

        const descInput = document.createElement("input");
        descInput.type = "text";
        descInput.className = "todo-input";
        descInput.value = st.description || "";
        descInput.placeholder = "Opcjonalny opis...";

        const editActions = document.createElement("div");
        editActions.className = "todo-actions";
        const saveBtn = document.createElement("button");
        saveBtn.type = "submit";
        saveBtn.className = "todo-action primary";
        saveBtn.textContent = "Zapisz";

        const cancelBtn = createActionButton("Anuluj", "cancel-edit-subtask");
        editActions.append(saveBtn, cancelBtn);

        editForm.append(titleInput, descInput, editActions);
        editLi.appendChild(editForm);
        subtasksList.appendChild(editLi);
      } else {
        const li = document.createElement("li");
        li.className = "todo-subtask-item";
        li.dataset.subtaskId = st.id;
        if (st.done) li.classList.add("is-done");

        const label = document.createElement("label");
        label.className = "todo-subtask-label";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "todo-toggle subtask-toggle";
        checkbox.checked = Boolean(st.done);
        checkbox.dataset.projectId = project.id;
        checkbox.dataset.subtaskId = st.id;

        const content = document.createElement("div");
        content.className = "todo-subtask-content";

        const stTitle = document.createElement("span");
        stTitle.className = "todo-subtask-title";
        stTitle.textContent = st.title;
        content.appendChild(stTitle);

        if (st.description) {
          const stDesc = document.createElement("span");
          stDesc.className = "todo-subtask-desc";
          stDesc.textContent = st.description;
          content.appendChild(stDesc);
        }

        label.append(checkbox, content);

        const actions = document.createElement("div");
        actions.className = "todo-subtask-actions";

        const editStBtn = createActionButton("Edytuj", "edit-subtask");
        editStBtn.dataset.projectId = project.id;
        editStBtn.dataset.subtaskId = st.id;

        const delStBtn = createActionButton("Usuń", "delete-subtask");
        delStBtn.dataset.projectId = project.id;
        delStBtn.dataset.subtaskId = st.id;

        actions.append(editStBtn, delStBtn);
        li.append(label, actions);
        subtasksList.appendChild(li);
      }
    });

    body.appendChild(subtasksList);

    // Subtask add form or "+ Dodaj subtask" button
    if (addingSubtaskProjectId === project.id) {
      const addForm = document.createElement("form");
      addForm.className = "todo-subtask-form";
      addForm.dataset.projectId = project.id;

      const titleInput = document.createElement("input");
      titleInput.type = "text";
      titleInput.className = "todo-input";
      titleInput.placeholder = "Nazwa subtasku...";
      titleInput.required = true;
      titleInput.autofocus = true;

      const descInput = document.createElement("input");
      descInput.type = "text";
      descInput.className = "todo-input";
      descInput.placeholder = "Opcjonalny opis subtasku...";

      const addActions = document.createElement("div");
      addActions.className = "todo-actions";
      const addSubmit = document.createElement("button");
      addSubmit.type = "submit";
      addSubmit.className = "todo-action primary";
      addSubmit.textContent = "Dodaj subtask";

      const cancelAdd = createActionButton("Anuluj", "cancel-add-subtask");
      addActions.append(addSubmit, cancelAdd);

      addForm.append(titleInput, descInput, addActions);
      body.appendChild(addForm);
    } else {
      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "todo-subtask-add-btn";
      addBtn.dataset.action = "open-add-subtask";
      addBtn.dataset.projectId = project.id;
      addBtn.textContent = "+ Dodaj subtask";
      body.appendChild(addBtn);
    }

    card.appendChild(body);
  }

  return card;
}

function renderEditProjectCard(project) {
  const card = document.createElement("div");
  card.className = "todo-project-card is-editing";
  card.dataset.id = project.id;

  const formEl = document.createElement("form");
  formEl.className = "todo-project-edit-form";
  formEl.dataset.id = project.id;

  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.className = "todo-input";
  titleInput.value = project.title;
  titleInput.placeholder = "Tytuł projektu...";
  titleInput.required = true;

  const descTextarea = document.createElement("textarea");
  descTextarea.className = "todo-project-edit-textarea";
  descTextarea.placeholder = "Opis projektu...";
  descTextarea.value = project.description || "";

  const metaRow = document.createElement("div");
  metaRow.style.display = "flex";
  metaRow.style.gap = "8px";
  metaRow.style.alignItems = "center";
  metaRow.style.flexWrap = "wrap";

  const prioritySelect = document.createElement("select");
  prioritySelect.className = "todo-select";
  prioritySelect.name = "priority";
  PRIORITIES.forEach((prio) => {
    const opt = document.createElement("option");
    opt.value = prio;
    opt.textContent = `${prio} (${PRIORITY_LABELS[prio] || prio})`;
    if (prio === (project.priority || "P3")) opt.selected = true;
    prioritySelect.appendChild(opt);
  });

  const dateInput = document.createElement("input");
  dateInput.className = "todo-date-input";
  setupDateInput(dateInput, "Deadline (dd/mm/yyyy)");
  dateInput.value = formatDateInputValue(project.due);

  metaRow.append(prioritySelect, dateInput);

  const actions = document.createElement("div");
  actions.className = "todo-actions";
  actions.style.justifyContent = "flex-end";

  const saveBtn = document.createElement("button");
  saveBtn.type = "submit";
  saveBtn.className = "todo-action primary";
  saveBtn.textContent = "Zapisz projekt";

  const cancelBtn = createActionButton("Anuluj", "cancel-edit-project");

  actions.append(saveBtn, cancelBtn);
  formEl.append(titleInput, descTextarea, metaRow, actions);
  card.appendChild(formEl);
  return card;
}

function render() {
  if (!layout) return;
  const items = listTodos();
  const stats = getStats(items);
  if (kpiOpen) kpiOpen.textContent = String(stats.open);
  if (kpiOverdue) kpiOverdue.textContent = String(stats.overdue);
  if (kpiDone) kpiDone.textContent = String(stats.done);
  if (kpiTotal) kpiTotal.textContent = String(stats.total);

  // 1. Regular columns (Taski, Shopping list)
  ["now", "shopping"].forEach((bucketId) => {
    const bucketEls = bucketMap.get(bucketId);
    if (!bucketEls) return;
    const bucketItems = items.filter((item) => item.bucket === bucketId);
    const filtered = bucketItems.filter((item) => {
      if (!showDone && !isTodoActiveListVisible(item)) return false;
      if (onlyDeadline && !item.due) return false;
      return true;
    });
    const sorted = sortTodos(filtered);

    const fragment = document.createDocumentFragment();
    sorted.forEach((item) => {
      if (item.id === editingId) {
        fragment.appendChild(renderEditItem(item));
      } else {
        fragment.appendChild(renderDisplayItem(item));
      }
    });

    if (bucketEls.list) bucketEls.list.replaceChildren(fragment);
    if (bucketEls.empty) bucketEls.empty.hidden = sorted.length > 0;
    if (bucketEls.count) bucketEls.count.textContent = String(sorted.length);
  });

  // 2. Projects Section
  if (projectsContainer) {
    const projectItems = items.filter((item) => item.bucket === "projects");
    const filteredProjects = projectItems.filter((item) => {
      if (!showDone && !isTodoActiveListVisible(item)) return false;
      if (onlyDeadline && !item.due) return false;
      return true;
    });

    if (projectsCount) {
      projectsCount.textContent = String(filteredProjects.length);
    }

    if (filteredProjects.length === 0) {
      if (projectsEmpty) projectsEmpty.hidden = false;
      projectsContainer.replaceChildren();
    } else {
      if (projectsEmpty) projectsEmpty.hidden = true;

      const fragment = document.createDocumentFragment();

      // Render grouped by Priority P0 -> P4
      PRIORITIES.forEach((prio) => {
        const groupProjects = filteredProjects.filter(
          (p) => (p.priority || "P3") === prio,
        );
        if (groupProjects.length === 0) return;

        const sortedGroup = sortProjects(groupProjects);

        const groupEl = document.createElement("div");
        groupEl.className = "todo-priority-group";

        const groupHeader = document.createElement("div");
        groupHeader.className = "todo-priority-header";
        groupHeader.innerHTML = `<span>${PRIORITY_LABELS[prio] || prio}</span><span class="todo-priority-header-count">${sortedGroup.length}</span>`;

        groupEl.appendChild(groupHeader);

        sortedGroup.forEach((project) => {
          if (editingProjectId === project.id) {
            groupEl.appendChild(renderEditProjectCard(project));
          } else {
            groupEl.appendChild(renderProjectCard(project));
          }
        });

        fragment.appendChild(groupEl);
      });

      projectsContainer.replaceChildren(fragment);
    }
  }

  if (editingId) {
    const focusInput = layout.querySelector(".todo-edit-form .todo-input");
    if (focusInput) focusInput.focus();
  }
  if (editingProjectId) {
    const focusInput = layout.querySelector(".todo-project-edit-form .todo-input");
    if (focusInput) focusInput.focus();
  }
}

function handleAdd(formEl) {
  const title = formEl.querySelector(".todo-input")?.value ?? "";
  const dueInput = formEl.querySelector(".todo-date-input");
  const due = readDueInput(dueInput, { report: true });
  const bucket = formEl.dataset.bucket || "now";
  if (!title.trim() || due === null) return;
  const item = addTodo({ title, due, bucket });
  animator.run(() => {
    formEl.reset();
    editingId = null;
    render();
  }, { action: "add", highlightId: item?.id ?? null });
}

function handleEditSubmit(formEl) {
  const id = formEl.dataset.id;
  const title = formEl.querySelector(".todo-input")?.value ?? "";
  const dueInput = formEl.querySelector(".todo-date-input");
  const due = readDueInput(dueInput, { report: true });
  const bucket = formEl.querySelector(".todo-select")?.value ?? "now";
  if (due === null) return;
  animator.run(() => {
    updateTodo(id, { title, due, bucket });
    editingId = null;
    render();
  }, { action: "save", highlightId: id });
}

function handleProjectEditSubmit(formEl) {
  const id = formEl.dataset.id;
  const title = formEl.querySelector(".todo-input")?.value ?? "";
  const desc = formEl.querySelector(".todo-project-edit-textarea")?.value ?? "";
  const priority = formEl.querySelector(".todo-select")?.value ?? "P3";
  const dueInput = formEl.querySelector(".todo-date-input");
  const due = readDueInput(dueInput, { report: true });
  if (!title.trim() || due === null) return;

  animator.run(() => {
    updateTodo(id, {
      title,
      description: desc,
      priority,
      due,
    });
    editingProjectId = null;
    render();
  }, { action: "save", highlightId: id });
}

function handleSubtaskAddSubmit(formEl) {
  const projectId = formEl.dataset.projectId;
  const inputs = formEl.querySelectorAll(".todo-input");
  const title = inputs[0]?.value ?? "";
  const desc = inputs[1]?.value ?? "";
  if (!title.trim() || !projectId) return;

  animator.run(() => {
    addSubtask(projectId, { title, description: desc });
    addingSubtaskProjectId = null;
    render();
  }, { action: "add" });
}

function handleSubtaskEditSubmit(formEl) {
  const projectId = formEl.dataset.projectId;
  const subtaskId = formEl.dataset.subtaskId;
  const inputs = formEl.querySelectorAll(".todo-input");
  const title = inputs[0]?.value ?? "";
  const desc = inputs[1]?.value ?? "";
  if (!title.trim() || !projectId || !subtaskId) return;

  animator.run(() => {
    updateSubtask(projectId, subtaskId, { title, description: desc });
    editingSubtaskId = null;
    render();
  }, { action: "save" });
}

function handleClick(event) {
  const actionEl = event.target.closest("[data-action]");

  // 1. Project header click to toggle expand/collapse
  const projectHeader = event.target.closest(".todo-project-header");
  if (projectHeader && !actionEl) {
    const card = projectHeader.closest(".todo-project-card");
    const id = card?.dataset.id;
    if (id) {
      if (expandedProjectIds.has(id)) {
        expandedProjectIds.delete(id);
      } else {
        expandedProjectIds.add(id);
      }
      saveExpandedProjectIds(expandedProjectIds);
      render();
      return;
    }
  }

  if (!actionEl) return;

  // Handle specific actions
  const action = actionEl.dataset.action;

  // Subtask actions
  if (action === "open-add-subtask") {
    addingSubtaskProjectId = actionEl.dataset.projectId;
    render();
    return;
  }
  if (action === "cancel-add-subtask") {
    addingSubtaskProjectId = null;
    render();
    return;
  }
  if (action === "edit-subtask") {
    editingSubtaskId = {
      projectId: actionEl.dataset.projectId,
      subtaskId: actionEl.dataset.subtaskId,
    };
    render();
    return;
  }
  if (action === "cancel-edit-subtask") {
    editingSubtaskId = null;
    render();
    return;
  }
  if (action === "delete-subtask") {
    deleteSubtask(actionEl.dataset.projectId, actionEl.dataset.subtaskId);
    render();
    return;
  }

  // Project actions
  const projectCard = actionEl.closest(".todo-project-card");
  if (projectCard) {
    const projectId = projectCard.dataset.id;
    const project = listTodos().find((p) => p.id === projectId);

    switch (action) {
      case "toggle-expand":
        if (expandedProjectIds.has(projectId)) {
          expandedProjectIds.delete(projectId);
        } else {
          expandedProjectIds.add(projectId);
        }
        saveExpandedProjectIds(expandedProjectIds);
        render();
        return;
      case "edit-project":
        editingProjectId = projectId;
        render();
        return;
      case "cancel-edit-project":
        editingProjectId = null;
        render();
        return;
      case "delete-project":
        if (
          window.confirm(
            `Czy na pewno chcesz usunąć projekt "${project?.title || "Projekt"}" wraz ze wszystkimi subtaskami?`,
          )
        ) {
          deleteTodo(projectId);
          if (editingProjectId === projectId) editingProjectId = null;
          render();
        }
        return;
      case "ics":
        if (project) downloadIcs(project);
        return;
      default:
        break;
    }
  }

  // Regular item actions (Taski / Shopping list)
  const itemEl = actionEl.closest(".todo-item");
  if (!itemEl) return;
  const id = itemEl.dataset.id;
  const item = listTodos().find((entry) => entry.id === id);

  switch (action) {
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
    case "ics":
      if (item) downloadIcs(item);
      break;
    default:
      break;
  }
}

function handleChange(event) {
  const target = event.target;
  if (!target) return;

  // Subtask checkbox toggle
  if (target.matches(".subtask-toggle")) {
    const projectId = target.dataset.projectId;
    const subtaskId = target.dataset.subtaskId;
    if (projectId && subtaskId) {
      toggleSubtask(projectId, subtaskId, target.checked);
      render();
      return;
    }
  }

  // Regular todo item toggle
  if (target.matches(".todo-toggle")) {
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
}

if (backBtn) {
  backBtn.addEventListener("click", () => {
    window.location.href = "./index.html";
  });
}

if (clearBtn) {
  clearBtn.addEventListener("click", () => {
    animator.run(() => {
      clearDone();
      editingId = null;
      editingProjectId = null;
      render();
    }, { action: "clear" });
  });
}

if (filterDone) {
  filterDone.addEventListener("change", () => {
    animator.run(() => {
      showDone = filterDone.checked;
      render();
    }, { action: showDone ? "hide-done" : "show-done" });
  });
}

if (filterDeadline) {
  filterDeadline.addEventListener("change", () => {
    animator.run(() => {
      onlyDeadline = filterDeadline.checked;
      render();
    }, { action: "filter" });
  });
}

if (layout) {
  layout.querySelectorAll(".todo-date-input").forEach((inputEl) => {
    setupDateInput(inputEl, "Deadline (dd/mm/yyyy)");
  });
  layout.addEventListener("click", handleClick);
  layout.addEventListener("change", handleChange);
  layout.addEventListener("input", handleDateInputEvent);
  layout.addEventListener("focusout", handleDateBlurEvent);
  layout.addEventListener("submit", (event) => {
    const formEl = event.target;
    if (formEl.classList.contains("todo-add-form")) {
      event.preventDefault();
      handleAdd(formEl);
      return;
    }
    if (formEl.classList.contains("todo-edit-form")) {
      event.preventDefault();
      handleEditSubmit(formEl);
      return;
    }
    if (formEl.classList.contains("todo-project-edit-form")) {
      event.preventDefault();
      handleProjectEditSubmit(formEl);
      return;
    }
    if (formEl.classList.contains("todo-subtask-form")) {
      event.preventDefault();
      if (formEl.dataset.subtaskId) {
        handleSubtaskEditSubmit(formEl);
      } else {
        handleSubtaskAddSubmit(formEl);
      }
    }
  });
}

window.addEventListener(TODO_STORE_CHANGED_EVENT, render);
async function initializeTodoPage() {
  await todoStoreReady;
  ensureBacklogSeeded();
  render();
}

initializeTodoPage().catch((error) => {
  console.error("todo page: initialization failed", error);
});
