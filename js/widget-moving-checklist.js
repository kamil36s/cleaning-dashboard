import { escapeHtml } from "./utils.js";

import {
  addMovingChecklistSection,
  addMovingChecklistTask,
  deleteMovingChecklistSection,
  deleteMovingChecklistTask,
  getMovingChecklistView,
  loadMovingChecklistState,
  moveMovingChecklistSection,
  moveMovingChecklistTask,
  renameMovingChecklistSection,
  resetMovingChecklistState,
  saveMovingChecklistState,
  toggleMovingChecklistSectionCollapsed,
  toggleMovingChecklistTask,
  toggleMovingChecklistTaskCollapsed,
  updateMovingChecklistTask,
  updateMovingChecklistUi,
} from "./moving-checklist-store.js";

const PRIORITY_LABELS = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

const ROOT_ID = "moving-checklist-card";
const TODAY = () => new Date();

function parseDueDate(value) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateShort(value) {
  const date = parseDueDate(value);
  if (!date) return "";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function formatRelativeDue(value) {
  const date = parseDueDate(value);
  if (!date) return null;
  const now = TODAY();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.round((date.getTime() - today.getTime()) / (24 * 60 * 60 * 1000));
  if (diffDays < 0) {
    return {
      label: `Overdue ${Math.abs(diffDays)}d`,
      tone: "is-overdue",
    };
  }
  if (diffDays === 0) {
    return {
      label: "Due today",
      tone: "is-due",
    };
  }
  if (diffDays === 1) {
    return {
      label: "Due tomorrow",
      tone: "is-soon",
    };
  }
  if (diffDays <= 7) {
    return {
      label: `Due in ${diffDays}d`,
      tone: "is-soon",
    };
  }
  return {
    label: formatDateShort(value),
    tone: "",
  };
}

function buildProgressText(completed, total) {
  return `${completed}/${total} done`;
}

function summarizeCountText(summary) {
  return buildProgressText(summary.completed || 0, summary.total || 0);
}

function findTaskById(tasks, taskId) {
  for (const task of tasks || []) {
    if (task.id === taskId) return task;
    const nested = findTaskById(task.subtasks, taskId);
    if (nested) return nested;
  }
  return null;
}

function getTaskFromState(state, taskId) {
  for (const section of state.sections || []) {
    const task = findTaskById(section.tasks, taskId);
    if (task) return task;
  }
  return null;
}

function getSectionFromState(state, sectionId) {
  return (state.sections || []).find((section) => section.id === sectionId) || null;
}

function renderStatusFilterButton(activeValue, value, label) {
  const active = activeValue === value;
  return `
    <button
      class="moving-filter-chip${active ? " is-active" : ""}"
      type="button"
      data-action="set-status-filter"
      data-value="${value}"
      aria-pressed="${active ? "true" : "false"}"
    >${label}</button>
  `;
}

function renderPriorityOptions(selected) {
  return ["all", "high", "medium", "low"]
    .map((value) => {
      const label = value === "all" ? "All priorities" : PRIORITY_LABELS[value];
      return `<option value="${value}"${selected === value ? " selected" : ""}>${label}</option>`;
    })
    .join("");
}

function renderSortOptions(selected) {
  const options = [
    ["manual", "Manual order"],
    ["dueDate", "Due date"],
    ["priority", "Priority"],
  ];
  return options
    .map(([value, label]) => `<option value="${value}"${selected === value ? " selected" : ""}>${label}</option>`)
    .join("");
}

function renderSectionOptions(sections, selected) {
  return sections
    .map((section) => `<option value="${section.id}"${section.id === selected ? " selected" : ""}>${escapeHtml(section.title)}</option>`)
    .join("");
}

function renderSummary(view) {
  const overall = view.stats.overall;
  const progressText = summarizeCountText(overall);

  return `
    <section class="moving-summary">
      <div class="moving-summary-top">
        <div>
          <div class="moving-summary-kicker">Local progress</div>
          <div class="moving-summary-value">${escapeHtml(progressText)}</div>
        </div>
        <div class="moving-summary-side">
          <span class="moving-summary-pill">${overall.open} open</span>
          <span class="moving-summary-pill">${overall.highPriorityOpen} high priority</span>
          <span class="moving-summary-pill">${overall.dueSoon} due soon</span>
        </div>
      </div>
      <div class="progress moving-progress" aria-hidden="true">
        <div class="green" style="width:${overall.progressPct}%"></div>
      </div>
      <div class="moving-summary-meta">
        <span>${overall.progressPct}% complete</span>
        <span>${overall.overdue} overdue</span>
      </div>
    </section>
  `;
}

function renderQuickAdd(view, allSections) {
  const hasSections = allSections.length > 0;
  return `
    <form class="moving-quick-add" data-role="quick-add">
      <input
        class="moving-input moving-input-title"
        type="text"
        name="title"
        maxlength="140"
        placeholder="Quick add a task..."
        ${hasSections ? "" : "disabled"}
      />
      <select class="moving-select" name="sectionId" data-role="quick-add-section"${hasSections ? "" : " disabled"}>
        ${hasSections ? renderSectionOptions(allSections, view.ui.quickAddSectionId) : '<option value="">Add a section first</option>'}
      </select>
      <button class="moving-primary-btn" type="submit"${hasSections ? "" : " disabled"}>Add task</button>
    </form>
  `;
}

function renderToolbar(view, transientState) {
  return `
    <div class="moving-toolbar">
      <div class="moving-toolbar-row">
        <div class="moving-toolbar-group moving-toolbar-group-filters">
          <span class="moving-toolbar-label">Show</span>
          <div class="moving-filter-row">
            ${renderStatusFilterButton(view.ui.statusFilter, "all", "All")}
            ${renderStatusFilterButton(view.ui.statusFilter, "incomplete", "Incomplete")}
            ${renderStatusFilterButton(view.ui.statusFilter, "completed", "Completed")}
          </div>
        </div>

        <label class="moving-toolbar-inline">
          <span class="moving-toolbar-inline-label">Priority</span>
          <select class="moving-select moving-select-compact" data-role="priority-filter">
            ${renderPriorityOptions(view.ui.priorityFilter)}
          </select>
        </label>

        <label class="moving-toolbar-inline">
          <span class="moving-toolbar-inline-label">Sort</span>
          <select class="moving-select moving-select-compact" data-role="sort-select">
            ${renderSortOptions(view.ui.sortBy)}
          </select>
        </label>

        <div class="moving-toolbar-actions">
          <button class="moving-secondary-btn" type="button" data-action="open-section-form">New section</button>
          <button class="moving-secondary-btn" type="button" data-action="reset-sample">Reset sample</button>
        </div>
      </div>
    </div>

    ${transientState.addSectionOpen ? `
      <form class="moving-inline-form" data-role="section-add">
        <input
          class="moving-input"
          type="text"
          name="title"
          maxlength="80"
          placeholder="Section name"
          data-focus-key="section-add"
          required
        />
        <div class="moving-inline-actions">
          <button class="moving-primary-btn" type="submit">Create section</button>
          <button class="moving-secondary-btn" type="button" data-action="cancel-section-form">Cancel</button>
        </div>
      </form>
    ` : ""}
  `;
}

function renderSectionHeader(section, index, totalSections, transientState) {
  const collapsed = section.collapsed && !section.forceExpanded;
  const editing = transientState.editingSectionId === section.id;
  const moveDisabledUp = index === 0;
  const moveDisabledDown = index === totalSections - 1;

  if (editing) {
    return `
      <form class="moving-inline-form moving-section-edit" data-role="section-rename" data-section-id="${section.id}">
        <input
          class="moving-input"
          type="text"
          name="title"
          value="${escapeHtml(section.title)}"
          maxlength="80"
          data-focus-key="section-edit-${section.id}"
          required
        />
        <div class="moving-inline-actions">
          <button class="moving-primary-btn" type="submit">Save</button>
          <button class="moving-secondary-btn" type="button" data-action="cancel-section-edit">Cancel</button>
        </div>
      </form>
    `;
  }

  return `
    <div class="moving-section-head">
      <div class="moving-section-main">
        <button
          class="moving-toggle-btn"
          type="button"
          data-action="toggle-section"
          data-section-id="${section.id}"
          aria-expanded="${collapsed ? "false" : "true"}"
          aria-label="${collapsed ? "Expand section" : "Collapse section"}"
        >${collapsed ? "+" : "-"}</button>

        <div class="moving-section-copy">
          <div class="moving-section-title-row">
            <div class="moving-section-title">${escapeHtml(section.title)}</div>
            <div class="moving-section-count">${summarizeCountText(section.summary)}</div>
          </div>
          <div class="progress moving-section-progress" aria-hidden="true">
            <div class="green" style="width:${section.summary.progressPct}%"></div>
          </div>
        </div>
      </div>

      <div class="moving-section-actions">
        <button class="moving-icon-btn" type="button" data-action="move-section-up" data-section-id="${section.id}"${moveDisabledUp ? " disabled" : ""}>↑</button>
        <button class="moving-icon-btn" type="button" data-action="move-section-down" data-section-id="${section.id}"${moveDisabledDown ? " disabled" : ""}>↓</button>
        <button class="moving-icon-btn" type="button" data-action="open-add-task" data-section-id="${section.id}">+Task</button>
        <button class="moving-icon-btn" type="button" data-action="edit-section" data-section-id="${section.id}">Rename</button>
        <button class="moving-icon-btn is-danger" type="button" data-action="delete-section" data-section-id="${section.id}">Delete</button>
      </div>
    </div>
  `;
}

function renderAddTaskForm(view, transientState, options = {}) {
  const sectionId = options.sectionId || "";
  const parentTaskId = options.parentTaskId || "";
  const targetKey = parentTaskId || sectionId;
  const shouldShow = transientState.addTaskTarget
    && transientState.addTaskTarget.sectionId === sectionId
    && transientState.addTaskTarget.parentTaskId === parentTaskId;

  if (!shouldShow) return "";

  return `
    <form
      class="moving-inline-form moving-task-inline-form"
      data-role="task-add"
      data-section-id="${sectionId}"
      data-parent-task-id="${parentTaskId}"
    >
      <input
        class="moving-input moving-input-title"
        type="text"
        name="title"
        maxlength="140"
        placeholder="${parentTaskId ? "New subtask title" : "New task title"}"
        data-focus-key="task-add-${targetKey}"
        required
      />
      <select class="moving-select" name="priority">
        <option value="medium">Medium priority</option>
        <option value="high">High priority</option>
        <option value="low">Low priority</option>
      </select>
      <input class="moving-input moving-date-input" type="date" name="dueDate" />
      <div class="moving-inline-actions">
        <button class="moving-primary-btn" type="submit">Add</button>
        <button class="moving-secondary-btn" type="button" data-action="cancel-task-add">Cancel</button>
      </div>
    </form>
  `;
}

function renderTaskEditForm(view, allSections, task, isTopLevel) {
  const selectedSectionId = isTopLevel
    ? allSections.find((section) => findTaskById(section.tasks, task.id))?.id
    : "";
  return `
    <form class="moving-task-edit" data-role="task-edit" data-task-id="${task.id}">
      <input
        class="moving-input moving-input-title"
        type="text"
        name="title"
        value="${escapeHtml(task.title)}"
        maxlength="140"
        data-focus-key="task-edit-${task.id}"
        required
      />

      <textarea class="moving-textarea" name="notes" rows="3" placeholder="Notes">${escapeHtml(task.notes || "")}</textarea>

      <div class="moving-task-edit-grid">
        <label class="moving-toolbar-field">
          <span class="moving-toolbar-label">Priority</span>
          <select class="moving-select" name="priority">
            <option value="high"${task.priority === "high" ? " selected" : ""}>High</option>
            <option value="medium"${task.priority === "medium" ? " selected" : ""}>Medium</option>
            <option value="low"${task.priority === "low" ? " selected" : ""}>Low</option>
          </select>
        </label>

        <label class="moving-toolbar-field">
          <span class="moving-toolbar-label">Due date</span>
          <input class="moving-input moving-date-input" type="date" name="dueDate" value="${escapeHtml(task.dueDate || "")}" />
        </label>

        ${isTopLevel ? `
          <label class="moving-toolbar-field">
            <span class="moving-toolbar-label">Section</span>
            <select class="moving-select" name="sectionId">
              ${renderSectionOptions(allSections, selectedSectionId)}
            </select>
          </label>
        ` : ""}
      </div>

      <div class="moving-inline-actions">
        <button class="moving-primary-btn" type="submit">Save</button>
        <button class="moving-secondary-btn" type="button" data-action="cancel-task-edit">Cancel</button>
      </div>
    </form>
  `;
}

function renderTask(view, allSections, task, options = {}) {
  const depth = options.depth || 0;
  const isTopLevel = Boolean(options.isTopLevel);
  const canReorder = view.ui.sortBy === "manual";
  const collapsed = task.collapsed && !task.forceExpanded;
  const due = formatRelativeDue(task.dueDate);
  const badges = [
    `<span class="moving-priority-pill priority-${task.priority}">${PRIORITY_LABELS[task.priority]}</span>`,
  ];

  if (due) {
    badges.push(`<span class="moving-due-pill ${due.tone}">${escapeHtml(due.label)}</span>`);
  }
  if (task.subtaskSummary.total > 0) {
    badges.push(`<span class="moving-subtask-pill">${task.subtaskSummary.completed}/${task.subtaskSummary.total} subtasks</span>`);
  }
  if (!task.selfMatches && view.filtersActive) {
    badges.push('<span class="moving-context-pill">Context</span>');
  }

  const editing = options.transientState.editingTaskId === task.id;
  const nestedVisible = task.subtasks.length > 0 && !collapsed;
  const addTaskForm = renderAddTaskForm(view, options.transientState, {
    sectionId: options.sectionId,
    parentTaskId: task.id,
  });

  return `
    <article class="moving-task${task.completed ? " is-complete" : ""}${!task.selfMatches && view.filtersActive ? " is-context" : ""}" style="--moving-depth:${depth}">
      <div class="moving-task-shell">
        <div class="moving-task-line">
          <div class="moving-task-main">
            ${task.subtasks.length > 0 ? `
              <button
                class="moving-toggle-btn"
                type="button"
                data-action="toggle-task-collapsed"
                data-task-id="${task.id}"
                aria-expanded="${collapsed ? "false" : "true"}"
                aria-label="${collapsed ? "Expand subtasks" : "Collapse subtasks"}"
              >${collapsed ? "+" : "-"}</button>
            ` : '<span class="moving-toggle-spacer" aria-hidden="true"></span>'}

            <label class="moving-checkbox">
              <input type="checkbox" data-action="toggle-task" data-task-id="${task.id}"${task.completed ? " checked" : ""} />
              <span class="moving-task-title">${escapeHtml(task.title)}</span>
            </label>
          </div>

          <div class="moving-task-trail">
            ${badges.join("")}
          </div>
        </div>

        <div class="moving-task-actions">
          ${canReorder ? `<button class="moving-icon-btn" type="button" data-action="move-task-up" data-task-id="${task.id}">↑</button>` : ""}
          ${canReorder ? `<button class="moving-icon-btn" type="button" data-action="move-task-down" data-task-id="${task.id}">↓</button>` : ""}
          <button class="moving-icon-btn" type="button" data-action="open-add-subtask" data-task-id="${task.id}" data-section-id="${options.sectionId}">+Sub</button>
          <button class="moving-icon-btn" type="button" data-action="edit-task" data-task-id="${task.id}">Edit</button>
          <button class="moving-icon-btn is-danger" type="button" data-action="delete-task" data-task-id="${task.id}">Delete</button>
        </div>
      </div>

      ${task.notes ? `<p class="moving-task-notes" title="${escapeHtml(task.notes)}">${escapeHtml(task.notes)}</p>` : ""}

      ${editing ? renderTaskEditForm(view, allSections, task, isTopLevel) : ""}
      ${addTaskForm}

      ${nestedVisible ? `
        <div class="moving-subtasks">
          ${task.subtasks.map((subtask) => renderTask(view, allSections, subtask, {
            sectionId: options.sectionId,
            depth: depth + 1,
            isTopLevel: false,
            transientState: options.transientState,
          })).join("")}
        </div>
      ` : ""}
    </article>
  `;
}

function renderSection(view, allSections, section, index, transientState) {
  const collapsed = section.collapsed && !section.forceExpanded;
  const addTopLevelForm = renderAddTaskForm(view, transientState, {
    sectionId: section.id,
    parentTaskId: "",
  });

  return `
    <section class="moving-section${collapsed ? " is-collapsed" : ""}">
      ${renderSectionHeader(section, index, view.sections.length, transientState)}

      ${collapsed ? "" : `
        <div class="moving-section-body">
          ${addTopLevelForm}
          ${section.tasks.length > 0 ? `
            <div class="moving-task-list">
              ${section.tasks.map((task) => renderTask(view, allSections, task, {
                sectionId: section.id,
                depth: 0,
                isTopLevel: true,
                transientState,
              })).join("")}
            </div>
          ` : `
            <div class="moving-empty-state">No tasks in this section yet.</div>
          `}
        </div>
      `}
    </section>
  `;
}

function renderEmptyWidget(hasSections) {
  return `
    <div class="moving-empty-widget">
      <p>${hasSections ? "Nothing matches the current filters." : "No sections yet. Create one to start planning the move."}</p>
    </div>
  `;
}

function renderWidget(view, transientState, allSections) {
  return `
    ${renderSummary(view)}
    ${renderQuickAdd(view, allSections)}
    ${renderToolbar(view, transientState)}
    <div class="moving-sections">
      ${view.sections.length > 0 ? view.sections.map((section, index) => renderSection(view, allSections, section, index, transientState)).join("") : renderEmptyWidget(allSections.length > 0)}
    </div>
  `;
}

export function initMovingChecklistWidget(root = document.getElementById(ROOT_ID)) {
  if (!(root instanceof HTMLElement)) return null;
  const body = root.querySelector(".moving-checklist-body");
  if (!(body instanceof HTMLElement)) return null;

  let state = loadMovingChecklistState();

  // Keep transient editor state outside localStorage so refresh only persists checklist data.
  const transientState = {
    editingTaskId: "",
    editingSectionId: "",
    addSectionOpen: false,
    addTaskTarget: null,
  };

  let pendingFocusSelector = "";

  function queueFocus(selector) {
    pendingFocusSelector = selector;
  }

  function closeTransientUi() {
    transientState.editingTaskId = "";
    transientState.editingSectionId = "";
    transientState.addSectionOpen = false;
    transientState.addTaskTarget = null;
  }

  function applyState(nextState) {
    state = saveMovingChecklistState(nextState);
    render();
  }

  function render() {
    const view = getMovingChecklistView(state);
    body.innerHTML = renderWidget(view, transientState, state.sections || []);

    if (pendingFocusSelector) {
      const target = body.querySelector(pendingFocusSelector);
      if (target instanceof HTMLElement) {
        target.focus();
        if (typeof target.select === "function") target.select();
      }
      pendingFocusSelector = "";
    }
  }

  function handleAction(action, element) {
    if (!action) return;

    if (action === "reset-sample") {
      const confirmed = window.confirm("Reset the moving checklist back to the sample moving plan?");
      if (!confirmed) return;
      closeTransientUi();
      queueFocus('[data-role="quick-add"] input[name="title"]');
      state = resetMovingChecklistState();
      render();
      return;
    }

    if (action === "set-status-filter") {
      applyState(updateMovingChecklistUi(state, { statusFilter: element.dataset.value || "all" }));
      return;
    }

    if (action === "open-section-form") {
      closeTransientUi();
      transientState.addSectionOpen = true;
      queueFocus('[data-focus-key="section-add"]');
      render();
      return;
    }

    if (action === "cancel-section-form") {
      transientState.addSectionOpen = false;
      render();
      return;
    }

    if (action === "toggle-section") {
      applyState(toggleMovingChecklistSectionCollapsed(state, element.dataset.sectionId));
      return;
    }

    if (action === "move-section-up") {
      applyState(moveMovingChecklistSection(state, element.dataset.sectionId, -1));
      return;
    }

    if (action === "move-section-down") {
      applyState(moveMovingChecklistSection(state, element.dataset.sectionId, 1));
      return;
    }

    if (action === "edit-section") {
      closeTransientUi();
      transientState.editingSectionId = element.dataset.sectionId || "";
      queueFocus(`[data-focus-key="section-edit-${transientState.editingSectionId}"]`);
      render();
      return;
    }

    if (action === "cancel-section-edit") {
      transientState.editingSectionId = "";
      render();
      return;
    }

    if (action === "delete-section") {
      const section = getSectionFromState(state, element.dataset.sectionId);
      if (!section) return;
      const hasTasks = (section.tasks || []).length > 0;
      const confirmed = window.confirm(
        hasTasks
          ? `Delete "${section.title}" and all tasks inside it?`
          : `Delete "${section.title}"?`,
      );
      if (!confirmed) return;
      closeTransientUi();
      applyState(deleteMovingChecklistSection(state, section.id));
      return;
    }

    if (action === "open-add-task") {
      closeTransientUi();
      transientState.addTaskTarget = {
        sectionId: element.dataset.sectionId || "",
        parentTaskId: "",
      };
      queueFocus(`[data-focus-key="task-add-${transientState.addTaskTarget.sectionId}"]`);
      render();
      return;
    }

    if (action === "open-add-subtask") {
      const taskId = element.dataset.taskId || "";
      closeTransientUi();
      transientState.addTaskTarget = {
        sectionId: element.dataset.sectionId || "",
        parentTaskId: taskId,
      };
      state = saveMovingChecklistState(toggleMovingChecklistTaskCollapsed(state, taskId, false));
      queueFocus(`[data-focus-key="task-add-${taskId}"]`);
      render();
      return;
    }

    if (action === "cancel-task-add") {
      transientState.addTaskTarget = null;
      render();
      return;
    }

    if (action === "toggle-task") {
      applyState(toggleMovingChecklistTask(state, element.dataset.taskId));
      return;
    }

    if (action === "toggle-task-collapsed") {
      applyState(toggleMovingChecklistTaskCollapsed(state, element.dataset.taskId));
      return;
    }

    if (action === "move-task-up") {
      applyState(moveMovingChecklistTask(state, element.dataset.taskId, -1));
      return;
    }

    if (action === "move-task-down") {
      applyState(moveMovingChecklistTask(state, element.dataset.taskId, 1));
      return;
    }

    if (action === "edit-task") {
      closeTransientUi();
      transientState.editingTaskId = element.dataset.taskId || "";
      queueFocus(`[data-focus-key="task-edit-${transientState.editingTaskId}"]`);
      render();
      return;
    }

    if (action === "cancel-task-edit") {
      transientState.editingTaskId = "";
      render();
      return;
    }

    if (action === "delete-task") {
      const task = getTaskFromState(state, element.dataset.taskId);
      if (!task) return;
      const hasSubtasks = (task.subtasks || []).length > 0;
      const confirmed = window.confirm(
        hasSubtasks
          ? `Delete "${task.title}" and all of its subtasks?`
          : `Delete "${task.title}"?`,
      );
      if (!confirmed) return;
      closeTransientUi();
      applyState(deleteMovingChecklistTask(state, task.id));
    }
  }

  body.addEventListener("click", (event) => {
    const actionEl = event.target.closest("[data-action]");
    if (!actionEl) return;
    if (actionEl.matches('input[type="checkbox"][data-action="toggle-task"]')) return;
    handleAction(actionEl.dataset.action, actionEl);
  });

  body.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    if (target.matches('[data-role="priority-filter"]')) {
      applyState(updateMovingChecklistUi(state, { priorityFilter: target.value }));
      return;
    }

    if (target.matches('[data-role="sort-select"]')) {
      applyState(updateMovingChecklistUi(state, { sortBy: target.value }));
      return;
    }

    if (target.matches('[data-role="quick-add-section"]')) {
      applyState(updateMovingChecklistUi(state, { quickAddSectionId: target.value }));
      return;
    }

    if (target.matches('input[type="checkbox"][data-action="toggle-task"]')) {
      applyState(toggleMovingChecklistTask(state, target.dataset.taskId, target.checked));
    }
  });

  body.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    event.preventDefault();

    if (form.dataset.role === "quick-add") {
      const title = form.elements.namedItem("title")?.value || "";
      const sectionId = form.elements.namedItem("sectionId")?.value || "";
      if (!String(title).trim()) return;
      closeTransientUi();
      queueFocus('[data-role="quick-add"] input[name="title"]');
      applyState(addMovingChecklistTask(state, { title, sectionId }));
      return;
    }

    if (form.dataset.role === "section-add") {
      const title = form.elements.namedItem("title")?.value || "";
      if (!String(title).trim()) return;
      closeTransientUi();
      queueFocus('[data-role="quick-add"] input[name="title"]');
      applyState(addMovingChecklistSection(state, title));
      return;
    }

    if (form.dataset.role === "section-rename") {
      const title = form.elements.namedItem("title")?.value || "";
      if (!String(title).trim()) return;
      transientState.editingSectionId = "";
      applyState(renameMovingChecklistSection(state, form.dataset.sectionId, title));
      return;
    }

    if (form.dataset.role === "task-add") {
      const title = form.elements.namedItem("title")?.value || "";
      const priority = form.elements.namedItem("priority")?.value || "medium";
      const dueDate = form.elements.namedItem("dueDate")?.value || "";
      if (!String(title).trim()) return;
      transientState.addTaskTarget = null;
      applyState(addMovingChecklistTask(state, {
        title,
        priority,
        dueDate,
        sectionId: form.dataset.sectionId || "",
        parentTaskId: form.dataset.parentTaskId || "",
      }));
      return;
    }

    if (form.dataset.role === "task-edit") {
      const title = form.elements.namedItem("title")?.value || "";
      const notes = form.elements.namedItem("notes")?.value || "";
      const priority = form.elements.namedItem("priority")?.value || "medium";
      const dueDate = form.elements.namedItem("dueDate")?.value || "";
      const sectionId = form.elements.namedItem("sectionId")?.value || "";
      if (!String(title).trim()) return;
      transientState.editingTaskId = "";
      applyState(updateMovingChecklistTask(state, form.dataset.taskId, {
        title,
        notes,
        priority,
        dueDate,
        sectionId,
      }));
    }
  });

  render();
  return {
    render,
  };
}

document.addEventListener("DOMContentLoaded", () => {
  initMovingChecklistWidget();
});
