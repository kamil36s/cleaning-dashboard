const STORAGE_KEY = "moving-checklist-widget.v1";
const SCHEMA_VERSION = 1;

export const MOVING_CHECKLIST_PRIORITIES = ["low", "medium", "high"];
export const MOVING_CHECKLIST_STATUS_FILTERS = ["all", "incomplete", "completed"];
export const MOVING_CHECKLIST_SORT_OPTIONS = ["manual", "dueDate", "priority"];

const PRIORITY_SET = new Set(MOVING_CHECKLIST_PRIORITIES);
const STATUS_FILTER_SET = new Set(MOVING_CHECKLIST_STATUS_FILTERS);
const SORT_OPTION_SET = new Set(MOVING_CHECKLIST_SORT_OPTIONS);
const DAY_MS = 24 * 60 * 60 * 1000;

const PRIORITY_RANK = {
  high: 0,
  medium: 1,
  low: 2,
};

function createId(prefix = "moving") {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}

function cloneValue(value) {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value));
}

function normalizeText(value) {
  return String(value || "").trim();
}

function normalizeOptionalText(value) {
  return String(value || "").trim();
}

function isValidDateValue(value) {
  if (!value || typeof value !== "string") return false;
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);
  return (
    !Number.isNaN(date.getTime()) &&
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
  );
}

function normalizeDueDate(value) {
  const raw = String(value || "").trim();
  return isValidDateValue(raw) ? raw : "";
}

function normalizePriority(value) {
  const raw = String(value || "").trim().toLowerCase();
  return PRIORITY_SET.has(raw) ? raw : "medium";
}

function normalizeStatusFilter(value) {
  const raw = String(value || "").trim().toLowerCase();
  return STATUS_FILTER_SET.has(raw) ? raw : "all";
}

function normalizeSortOption(value) {
  const raw = String(value || "").trim();
  return SORT_OPTION_SET.has(raw) ? raw : "manual";
}

function normalizeTask(raw) {
  if (!raw || typeof raw !== "object") return null;
  const title = normalizeText(raw.title);
  if (!title) return null;

  const createdAt = Number.isFinite(raw.createdAt) ? raw.createdAt : Date.now();
  const updatedAt = Number.isFinite(raw.updatedAt) ? raw.updatedAt : createdAt;
  const subtasks = Array.isArray(raw.subtasks)
    ? raw.subtasks.map(normalizeTask).filter(Boolean)
    : [];

  return {
    id: typeof raw.id === "string" ? raw.id : createId("moving-task"),
    title,
    notes: normalizeOptionalText(raw.notes),
    completed: Boolean(raw.completed),
    priority: normalizePriority(raw.priority),
    dueDate: normalizeDueDate(raw.dueDate),
    collapsed: Boolean(raw.collapsed),
    subtasks,
    createdAt,
    updatedAt,
  };
}

function normalizeSection(raw) {
  if (!raw || typeof raw !== "object") return null;
  const title = normalizeText(raw.title) || "Untitled section";
  const tasks = Array.isArray(raw.tasks)
    ? raw.tasks.map(normalizeTask).filter(Boolean)
    : [];

  return {
    id: typeof raw.id === "string" ? raw.id : createId("moving-section"),
    title,
    collapsed: Boolean(raw.collapsed),
    tasks,
  };
}

function buildSampleState() {
  return {
    version: SCHEMA_VERSION,
    sections: [
      {
        id: "moving-section-before",
        title: "Before moving",
        collapsed: false,
        tasks: [
          {
            id: "moving-task-rental",
            title: "Sign rental agreement",
            notes: "Confirm move-in date, repairs list, and how the deposit will be returned.",
            completed: false,
            priority: "high",
            dueDate: "2026-04-01",
            collapsed: false,
            subtasks: [
              {
                id: "moving-task-rental-review",
                title: "Review final clauses",
                completed: true,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
              {
                id: "moving-task-rental-proof",
                title: "Save signed PDF and payment receipt",
                completed: false,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
            ],
          },
          {
            id: "moving-task-keys",
            title: "Get keys",
            notes: "Test the front door, mailbox key, and building access before leaving the office.",
            completed: false,
            priority: "high",
            dueDate: "2026-04-10",
            collapsed: false,
            subtasks: [],
          },
          {
            id: "moving-task-photos",
            title: "Photograph apartment condition",
            notes: "Keep timestamped photos in one folder for handover evidence.",
            completed: false,
            priority: "high",
            dueDate: "2026-04-10",
            collapsed: false,
            subtasks: [
              {
                id: "moving-task-photos-rooms",
                title: "Capture every room",
                completed: false,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [
                  {
                    id: "moving-task-photos-kitchen",
                    title: "Kitchen appliances and countertops",
                    completed: false,
                    priority: "medium",
                    dueDate: "",
                    notes: "",
                    collapsed: false,
                    subtasks: [],
                  },
                  {
                    id: "moving-task-photos-bathroom",
                    title: "Bathroom fixtures and tiles",
                    completed: false,
                    priority: "medium",
                    dueDate: "",
                    notes: "",
                    collapsed: false,
                    subtasks: [],
                  },
                ],
              },
            ],
          },
        ],
      },
      {
        id: "moving-section-packing",
        title: "Packing",
        collapsed: false,
        tasks: [
          {
            id: "moving-task-pack-kitchen",
            title: "Pack kitchen",
            notes: "Use towels and paper to cushion glassware, and label one box as essentials.",
            completed: false,
            priority: "high",
            dueDate: "2026-04-08",
            collapsed: false,
            subtasks: [
              {
                id: "moving-task-pack-kitchen-fragile",
                title: "Wrap plates and glasses",
                completed: false,
                priority: "high",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
              {
                id: "moving-task-pack-kitchen-pantry",
                title: "Pack pantry separately",
                completed: false,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [
                  {
                    id: "moving-task-pack-kitchen-cleaners",
                    title: "Leave one cleaning kit accessible",
                    completed: false,
                    priority: "low",
                    dueDate: "",
                    notes: "",
                    collapsed: false,
                    subtasks: [],
                  },
                ],
              },
            ],
          },
          {
            id: "moving-task-first-night-box",
            title: "Prepare first-night bag",
            notes: "Treat it like a one-night trip so the first evening is easy.",
            completed: false,
            priority: "high",
            dueDate: "2026-04-10",
            collapsed: false,
            subtasks: [
              {
                id: "moving-task-first-night-toiletries",
                title: "Toiletries and medication",
                completed: false,
                priority: "high",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
              {
                id: "moving-task-first-night-tech",
                title: "Chargers and extension lead",
                completed: false,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
            ],
          },
        ],
      },
      {
        id: "moving-section-shopping",
        title: "Shopping / supplies",
        collapsed: false,
        tasks: [
          {
            id: "moving-task-buy-bags",
            title: "Buy trash bags",
            notes: "Heavy-duty bags are useful for last-minute clothes, recycling, and cleaning waste.",
            completed: true,
            priority: "medium",
            dueDate: "2026-03-30",
            collapsed: false,
            subtasks: [],
          },
          {
            id: "moving-task-buy-boxes",
            title: "Buy cardboard boxes and tape",
            notes: "Get a few more boxes than expected to avoid a last-day store run.",
            completed: false,
            priority: "medium",
            dueDate: "2026-04-03",
            collapsed: false,
            subtasks: [],
          },
        ],
      },
      {
        id: "moving-section-day",
        title: "Moving day",
        collapsed: false,
        tasks: [
          {
            id: "moving-task-meter-readings",
            title: "Take meter readings",
            notes: "Record electricity, water, and gas before the truck leaves.",
            completed: false,
            priority: "high",
            dueDate: "2026-04-11",
            collapsed: false,
            subtasks: [
              {
                id: "moving-task-meter-electricity",
                title: "Electricity",
                completed: false,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
              {
                id: "moving-task-meter-water",
                title: "Water",
                completed: false,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
              {
                id: "moving-task-meter-gas",
                title: "Gas",
                completed: false,
                priority: "medium",
                dueDate: "",
                notes: "",
                collapsed: false,
                subtasks: [],
              },
            ],
          },
          {
            id: "moving-task-essentials-last",
            title: "Load essentials last",
            notes: "Keep cleaning kit, documents, and first-night bag easy to reach.",
            completed: false,
            priority: "medium",
            dueDate: "2026-04-11",
            collapsed: false,
            subtasks: [],
          },
        ],
      },
      {
        id: "moving-section-admin",
        title: "Administrative / paperwork",
        collapsed: false,
        tasks: [
          {
            id: "moving-task-bank",
            title: "Change address in bank",
            notes: "Update both mailing and registered address if the bank stores them separately.",
            completed: false,
            priority: "high",
            dueDate: "2026-04-15",
            collapsed: false,
            subtasks: [],
          },
          {
            id: "moving-task-forwarding",
            title: "Set up mail forwarding",
            notes: "Useful buffer while all services catch up with the new address.",
            completed: false,
            priority: "medium",
            dueDate: "2026-04-14",
            collapsed: false,
            subtasks: [],
          },
        ],
      },
      {
        id: "moving-section-week-one",
        title: "First week after moving",
        collapsed: false,
        tasks: [
          {
            id: "moving-task-unpack-bedroom",
            title: "Unpack bedroom first",
            notes: "A ready bed and basic clothes make the first week much easier.",
            completed: false,
            priority: "medium",
            dueDate: "2026-04-13",
            collapsed: false,
            subtasks: [],
          },
          {
            id: "moving-task-safety",
            title: "Test smoke detectors",
            notes: "Replace batteries right away if anything feels unreliable.",
            completed: false,
            priority: "medium",
            dueDate: "2026-04-14",
            collapsed: false,
            subtasks: [],
          },
        ],
      },
    ],
    ui: {
      statusFilter: "all",
      priorityFilter: "all",
      sortBy: "manual",
      quickAddSectionId: "moving-section-before",
    },
  };
}

function getFirstSectionId(sections = []) {
  return sections[0]?.id || "";
}

export function normalizeMovingChecklistState(raw) {
  const fallback = buildSampleState();
  const sections = Array.isArray(raw?.sections)
    ? raw.sections.map(normalizeSection).filter(Boolean)
    : fallback.sections;

  const quickAddSectionId = typeof raw?.ui?.quickAddSectionId === "string"
    && sections.some((section) => section.id === raw.ui.quickAddSectionId)
    ? raw.ui.quickAddSectionId
    : getFirstSectionId(sections);

  return {
    version: SCHEMA_VERSION,
    sections,
    ui: {
      statusFilter: normalizeStatusFilter(raw?.ui?.statusFilter),
      priorityFilter: raw?.ui?.priorityFilter === "all"
        ? "all"
        : normalizePriority(raw?.ui?.priorityFilter),
      sortBy: normalizeSortOption(raw?.ui?.sortBy),
      quickAddSectionId,
    },
  };
}

export function getDefaultMovingChecklistState() {
  return normalizeMovingChecklistState(buildSampleState());
}

export function loadMovingChecklistState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaultMovingChecklistState();
    return normalizeMovingChecklistState(JSON.parse(raw));
  } catch {
    return getDefaultMovingChecklistState();
  }
}

export function saveMovingChecklistState(state) {
  const normalized = normalizeMovingChecklistState(state);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  } catch {}
  return normalized;
}

export function resetMovingChecklistState() {
  const fallback = getDefaultMovingChecklistState();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fallback));
  } catch {}
  return fallback;
}

function findSectionIndex(state, sectionId) {
  return state.sections.findIndex((section) => section.id === sectionId);
}

function findTaskLocation(tasks, taskId, parent = null, depth = 0) {
  for (let index = 0; index < tasks.length; index += 1) {
    const task = tasks[index];
    if (task.id === taskId) {
      return {
        task,
        index,
        tasks,
        parent,
        depth,
      };
    }
    const nested = findTaskLocation(task.subtasks, taskId, task, depth + 1);
    if (nested) return nested;
  }
  return null;
}

function findTaskRecord(state, taskId) {
  for (let sectionIndex = 0; sectionIndex < state.sections.length; sectionIndex += 1) {
    const section = state.sections[sectionIndex];
    const location = findTaskLocation(section.tasks, taskId);
    if (location) {
      return {
        section,
        sectionIndex,
        ...location,
      };
    }
  }
  return null;
}

function touchTask(task) {
  task.updatedAt = Date.now();
  return task;
}

function setTaskCompletion(task, completed) {
  task.completed = Boolean(completed);
  touchTask(task);
  task.subtasks.forEach((subtask) => setTaskCompletion(subtask, completed));
  return task;
}

function sumTaskTree(tasks = []) {
  return tasks.reduce((acc, task) => {
    acc.total += 1;
    if (task.completed) acc.completed += 1;
    if (!task.completed && task.priority === "high") acc.highPriorityOpen += 1;

    if (!task.completed && task.dueDate) {
      const dueTime = new Date(`${task.dueDate}T00:00:00`).getTime();
      const today = startOfDay(new Date()).getTime();
      const diffDays = Math.round((dueTime - today) / DAY_MS);
      if (diffDays < 0) acc.overdue += 1;
      if (diffDays >= 0 && diffDays <= 7) acc.dueSoon += 1;
    }

    const nested = sumTaskTree(task.subtasks);
    acc.total += nested.total;
    acc.completed += nested.completed;
    acc.highPriorityOpen += nested.highPriorityOpen;
    acc.overdue += nested.overdue;
    acc.dueSoon += nested.dueSoon;
    return acc;
  }, {
    total: 0,
    completed: 0,
    highPriorityOpen: 0,
    overdue: 0,
    dueSoon: 0,
  });
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function getMovingChecklistStats(state) {
  const normalized = normalizeMovingChecklistState(state);
  const overall = sumTaskTree(normalized.sections.flatMap((section) => section.tasks));

  return {
    overall: {
      ...overall,
      open: Math.max(0, overall.total - overall.completed),
      progressPct: overall.total ? Math.round((overall.completed / overall.total) * 100) : 0,
    },
    sections: normalized.sections.map((section) => {
      const summary = sumTaskTree(section.tasks);
      return {
        id: section.id,
        title: section.title,
        total: summary.total,
        completed: summary.completed,
        open: Math.max(0, summary.total - summary.completed),
        progressPct: summary.total ? Math.round((summary.completed / summary.total) * 100) : 0,
      };
    }),
  };
}

function buildStatsFromSections(sections = []) {
  const sectionSummaries = sections.map((section) => {
    const summary = sumTaskTree(section.tasks);
    return {
      id: section.id,
      title: section.title,
      total: summary.total,
      completed: summary.completed,
      open: Math.max(0, summary.total - summary.completed),
      highPriorityOpen: summary.highPriorityOpen,
      overdue: summary.overdue,
      dueSoon: summary.dueSoon,
      progressPct: summary.total ? Math.round((summary.completed / summary.total) * 100) : 0,
    };
  });
  const overall = sectionSummaries.reduce((acc, section) => {
    acc.total += section.total;
    acc.completed += section.completed;
    acc.highPriorityOpen += section.highPriorityOpen;
    acc.overdue += section.overdue;
    acc.dueSoon += section.dueSoon;
    return acc;
  }, {
    total: 0,
    completed: 0,
    highPriorityOpen: 0,
    overdue: 0,
    dueSoon: 0,
  });

  return {
    overall: {
      ...overall,
      open: Math.max(0, overall.total - overall.completed),
      progressPct: overall.total ? Math.round((overall.completed / overall.total) * 100) : 0,
    },
    sections: sectionSummaries,
  };
}

function compareDueDate(a, b) {
  const aValue = a.dueDate ? new Date(`${a.dueDate}T00:00:00`).getTime() : null;
  const bValue = b.dueDate ? new Date(`${b.dueDate}T00:00:00`).getTime() : null;
  if (aValue === bValue) return 0;
  if (aValue === null) return 1;
  if (bValue === null) return -1;
  return aValue - bValue;
}

function comparePriority(a, b) {
  return (PRIORITY_RANK[a.priority] ?? 99) - (PRIORITY_RANK[b.priority] ?? 99);
}

function compareForSort(a, b, sortBy) {
  const doneDiff = Number(a.completed) - Number(b.completed);
  if (doneDiff !== 0) return doneDiff;

  if (sortBy === "dueDate") {
    return compareDueDate(a, b)
      || comparePriority(a, b)
      || a.title.localeCompare(b.title, "en");
  }

  if (sortBy === "priority") {
    return comparePriority(a, b)
      || compareDueDate(a, b)
      || a.title.localeCompare(b.title, "en");
  }

  return 0;
}

function matchesFilters(task, ui) {
  const statusOk = ui.statusFilter === "all"
    || (ui.statusFilter === "completed" ? task.completed : !task.completed);
  const priorityOk = ui.priorityFilter === "all" || task.priority === ui.priorityFilter;
  return statusOk && priorityOk;
}

function buildTaskView(task, ui, forceExpanded) {
  const filteredSubtasks = task.subtasks
    .map((subtask) => buildTaskView(subtask, ui, forceExpanded))
    .filter(Boolean);

  const selfMatches = matchesFilters(task, ui);
  if (!selfMatches && filteredSubtasks.length === 0) {
    return null;
  }

  const orderedSubtasks = ui.sortBy === "manual"
    ? filteredSubtasks
    : filteredSubtasks.slice().sort((a, b) => compareForSort(a, b, ui.sortBy));
  const subtaskSummary = sumTaskTree(task.subtasks);

  return {
    ...task,
    subtasks: orderedSubtasks,
    selfMatches,
    forceExpanded,
    subtaskSummary: {
      total: subtaskSummary.total,
      completed: subtaskSummary.completed,
    },
  };
}

export function getMovingChecklistView(state) {
  const normalized = normalizeMovingChecklistState(state);
  const filtersActive = normalized.ui.statusFilter !== "all" || normalized.ui.priorityFilter !== "all";

  const sections = normalized.sections
    .map((section) => {
      const renderedTasks = section.tasks
        .map((task) => buildTaskView(task, normalized.ui, filtersActive))
        .filter(Boolean);

      const orderedTasks = normalized.ui.sortBy === "manual"
        ? renderedTasks
        : renderedTasks.slice().sort((a, b) => compareForSort(a, b, normalized.ui.sortBy));

      return {
        ...section,
        tasks: orderedTasks,
        forceExpanded: filtersActive && orderedTasks.length > 0,
      };
    })
    .filter((section) => !filtersActive || section.tasks.length > 0);
  const stats = buildStatsFromSections(sections);
  const sectionsWithSummaries = sections.map((section) => {
    const summary = stats.sections.find((item) => item.id === section.id) || {
      id: section.id,
      title: section.title,
      total: 0,
      completed: 0,
      open: 0,
      progressPct: 0,
    };

    return {
      ...section,
      summary,
    };
  });

  return {
    ...normalized,
    sections: sectionsWithSummaries,
    stats,
    filtersActive,
  };
}

export function updateMovingChecklistUi(state, updates = {}) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  next.ui.statusFilter = normalizeStatusFilter(updates.statusFilter ?? next.ui.statusFilter);
  next.ui.priorityFilter = updates.priorityFilter === "all"
    ? "all"
    : normalizePriority(updates.priorityFilter ?? next.ui.priorityFilter);
  next.ui.sortBy = normalizeSortOption(updates.sortBy ?? next.ui.sortBy);

  if (typeof updates.quickAddSectionId === "string" && next.sections.some((section) => section.id === updates.quickAddSectionId)) {
    next.ui.quickAddSectionId = updates.quickAddSectionId;
  } else if (!next.sections.some((section) => section.id === next.ui.quickAddSectionId)) {
    next.ui.quickAddSectionId = getFirstSectionId(next.sections);
  }

  return next;
}

export function addMovingChecklistSection(state, title) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const cleanTitle = normalizeText(title);
  if (!cleanTitle) return next;

  const section = {
    id: createId("moving-section"),
    title: cleanTitle,
    collapsed: false,
    tasks: [],
  };
  next.sections.push(section);
  next.ui.quickAddSectionId = section.id;
  return next;
}

export function renameMovingChecklistSection(state, sectionId, title) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const index = findSectionIndex(next, sectionId);
  const cleanTitle = normalizeText(title);
  if (index < 0 || !cleanTitle) return next;
  next.sections[index].title = cleanTitle;
  return next;
}

export function deleteMovingChecklistSection(state, sectionId) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const index = findSectionIndex(next, sectionId);
  if (index < 0) return next;
  next.sections.splice(index, 1);
  if (!next.sections.some((section) => section.id === next.ui.quickAddSectionId)) {
    next.ui.quickAddSectionId = getFirstSectionId(next.sections);
  }
  return next;
}

export function moveMovingChecklistSection(state, sectionId, direction) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const index = findSectionIndex(next, sectionId);
  if (index < 0) return next;
  const target = index + (direction < 0 ? -1 : 1);
  if (target < 0 || target >= next.sections.length) return next;
  [next.sections[index], next.sections[target]] = [next.sections[target], next.sections[index]];
  return next;
}

export function toggleMovingChecklistSectionCollapsed(state, sectionId, forceValue) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const index = findSectionIndex(next, sectionId);
  if (index < 0) return next;
  next.sections[index].collapsed = typeof forceValue === "boolean"
    ? forceValue
    : !next.sections[index].collapsed;
  return next;
}

export function addMovingChecklistTask(state, input = {}) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const title = normalizeText(input.title);
  if (!title) return next;

  const task = {
    id: createId("moving-task"),
    title,
    notes: normalizeOptionalText(input.notes),
    completed: Boolean(input.completed),
    priority: normalizePriority(input.priority),
    dueDate: normalizeDueDate(input.dueDate),
    collapsed: false,
    subtasks: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };

  if (typeof input.parentTaskId === "string" && input.parentTaskId) {
    const record = findTaskRecord(next, input.parentTaskId);
    if (!record) return next;
    record.task.collapsed = false;
    record.task.subtasks.push(task);
    touchTask(record.task);
    return next;
  }

  const targetSectionId = typeof input.sectionId === "string" && input.sectionId
    ? input.sectionId
    : next.ui.quickAddSectionId || getFirstSectionId(next.sections);
  const sectionIndex = findSectionIndex(next, targetSectionId);
  if (sectionIndex < 0) return next;
  next.sections[sectionIndex].tasks.push(task);
  next.ui.quickAddSectionId = next.sections[sectionIndex].id;
  return next;
}

export function updateMovingChecklistTask(state, taskId, updates = {}) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const record = findTaskRecord(next, taskId);
  if (!record) return next;

  if (updates.title !== undefined) {
    const title = normalizeText(updates.title);
    if (title) record.task.title = title;
  }
  if (updates.notes !== undefined) {
    record.task.notes = normalizeOptionalText(updates.notes);
  }
  if (updates.priority !== undefined) {
    record.task.priority = normalizePriority(updates.priority);
  }
  if (updates.dueDate !== undefined) {
    record.task.dueDate = normalizeDueDate(updates.dueDate);
  }
  if (updates.completed !== undefined) {
    setTaskCompletion(record.task, updates.completed);
  } else {
    touchTask(record.task);
  }

  if (updates.sectionId && !record.parent) {
    const currentSectionId = record.section.id;
    const nextSectionId = updates.sectionId;
    if (nextSectionId !== currentSectionId && next.sections.some((section) => section.id === nextSectionId)) {
      const [moved] = record.tasks.splice(record.index, 1);
      const sectionIndex = findSectionIndex(next, nextSectionId);
      next.sections[sectionIndex].tasks.push(moved);
      next.ui.quickAddSectionId = nextSectionId;
    }
  }

  return next;
}

export function toggleMovingChecklistTask(state, taskId, forceValue) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const record = findTaskRecord(next, taskId);
  if (!record) return next;
  setTaskCompletion(record.task, typeof forceValue === "boolean" ? forceValue : !record.task.completed);
  return next;
}

export function toggleMovingChecklistTaskCollapsed(state, taskId, forceValue) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const record = findTaskRecord(next, taskId);
  if (!record) return next;
  record.task.collapsed = typeof forceValue === "boolean"
    ? forceValue
    : !record.task.collapsed;
  touchTask(record.task);
  return next;
}

export function deleteMovingChecklistTask(state, taskId) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const record = findTaskRecord(next, taskId);
  if (!record) return next;
  record.tasks.splice(record.index, 1);
  return next;
}

export function moveMovingChecklistTask(state, taskId, direction) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const record = findTaskRecord(next, taskId);
  if (!record) return next;

  const target = record.index + (direction < 0 ? -1 : 1);
  if (target < 0 || target >= record.tasks.length) return next;
  [record.tasks[record.index], record.tasks[target]] = [record.tasks[target], record.tasks[record.index]];
  return next;
}

export function moveMovingChecklistTaskToSection(state, taskId, sectionId) {
  const next = cloneValue(normalizeMovingChecklistState(state));
  const record = findTaskRecord(next, taskId);
  const sectionIndex = findSectionIndex(next, sectionId);
  if (!record || sectionIndex < 0) return next;

  const [moved] = record.tasks.splice(record.index, 1);
  next.sections[sectionIndex].tasks.push(moved);
  next.ui.quickAddSectionId = sectionId;
  return next;
}
