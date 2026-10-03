import {
  loadFileBackedSetting,
  saveFileBackedSetting,
} from "./file-settings.js";
import {
  BACKLOG_PROJECTS_SEED,
  PROJECT_SEED_VERSION,
} from "./todo-projects-backlog-seed.js";

const STORAGE_KEY = "todo-items-v1";
const SERVER_SETTINGS_NAME = "todo";
const DEFAULT_BUCKET = "now";
const DELETED_SEED_KEY = "todo-deleted-seed-ids-v1";

export const TODO_STORE_CHANGED_EVENT = "todo:store-changed";
export { PROJECT_SEED_VERSION, BACKLOG_PROJECTS_SEED };

export const BUCKETS = [
  { id: "now", label: "Taski" },
  { id: "projects", label: "Projekty" },
  { id: "ideas", label: "Pomysly" },
  { id: "shopping", label: "Shopping list" },
];

export const PRIORITIES = ["P0", "P1", "P2", "P3", "P4"];
const PRIORITY_SET = new Set(PRIORITIES);
const PRIORITY_ORDER = { P0: 0, P1: 1, P2: 2, P3: 3, P4: 4 };

const BUCKET_SET = new Set(BUCKETS.map((b) => b.id));
const DAY_MS = 24 * 60 * 60 * 1000;
export const COMPLETED_ACTIVE_DAYS = 3;
export const COMPLETED_ACTIVE_MS = COMPLETED_ACTIVE_DAYS * DAY_MS;
let todosCache = null;
let todosLocalSnapshot = "";

function padDatePart(value) {
  return String(value).padStart(2, "0");
}

function isValidDateParts(year, month, day) {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return false;
  }
  const date = new Date(year, month - 1, day);
  return (
    !Number.isNaN(date.getTime()) &&
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
  );
}

function toISODateString(year, month, day) {
  return `${year}-${padDatePart(month)}-${padDatePart(day)}`;
}

function createId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `todo-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}

function normalizeTitle(value) {
  return String(value || "").trim();
}

function normalizeBucket(value) {
  return BUCKET_SET.has(value) ? value : DEFAULT_BUCKET;
}

export function normalizePriority(value) {
  const p = String(value || "").toUpperCase().trim();
  return PRIORITY_SET.has(p) ? p : "P3";
}

export function normalizeSubtask(raw, index = 0) {
  if (!raw || typeof raw !== "object") return null;
  const title = normalizeTitle(raw.title);
  if (!title) return null;
  const createdAt = Number.isFinite(raw.createdAt) ? raw.createdAt : Date.now();
  const updatedAt = Number.isFinite(raw.updatedAt) ? raw.updatedAt : createdAt;
  return {
    id: typeof raw.id === "string" ? raw.id : createId(),
    title,
    description: typeof raw.description === "string" ? raw.description : "",
    done: Boolean(raw.done),
    order: Number.isFinite(raw.order) ? raw.order : index + 1,
    createdAt,
    updatedAt,
  };
}

export function parseISODate(value) {
  if (!value || typeof value !== "string") return null;
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!isValidDateParts(year, month, day)) return null;
  const date = new Date(year, month - 1, day);
  return date;
}

export function normalizeDueDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;

  const isoMatch = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoMatch) {
    const year = Number(isoMatch[1]);
    const month = Number(isoMatch[2]);
    const day = Number(isoMatch[3]);
    return isValidDateParts(year, month, day) ? toISODateString(year, month, day) : null;
  }

  const displayMatch = raw.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);
  if (!displayMatch) return null;

  const day = Number(displayMatch[1]);
  const month = Number(displayMatch[2]);
  const year = Number(displayMatch[3]);
  if (!isValidDateParts(year, month, day)) return null;
  return toISODateString(year, month, day);
}

export function formatDateInputValue(value) {
  const iso = normalizeDueDate(value);
  if (!iso) return "";
  const date = parseISODate(iso);
  if (!date) return "";
  return `${padDatePart(date.getDate())}/${padDatePart(date.getMonth() + 1)}/${date.getFullYear()}`;
}

export function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function normalizeItem(raw) {
  if (!raw || typeof raw !== "object") return null;
  const title = normalizeTitle(raw.title);
  if (!title) return null;
  const createdAt = Number.isFinite(raw.createdAt) ? raw.createdAt : Date.now();
  const updatedAt = Number.isFinite(raw.updatedAt) ? raw.updatedAt : createdAt;
  const bucket = normalizeBucket(raw.bucket);

  const isProject = bucket === "projects";
  let done = Boolean(raw.done);
  let completedAt = Number.isFinite(raw.completedAt)
    ? raw.completedAt
    : (raw.done ? updatedAt : null);

  const item = {
    id: typeof raw.id === "string" ? raw.id : createId(),
    title,
    bucket,
    due: normalizeDueDate(raw.due ?? raw.dueDate),
    done,
    completedAt,
    createdAt,
    updatedAt,
  };

  // STRICT RULE: priority, description, order and subtasks ONLY for projects
  if (isProject) {
    item.description = typeof raw.description === "string" ? raw.description : "";
    item.priority = normalizePriority(raw.priority);
    item.order = Number.isFinite(raw.order) ? raw.order : 0;
    item.subtasks = Array.isArray(raw.subtasks)
      ? raw.subtasks.map((st, idx) => normalizeSubtask(st, idx)).filter(Boolean)
      : [];

    if (item.subtasks.length > 0) {
      const allDone = item.subtasks.every((st) => st.done);
      item.done = allDone;
      item.completedAt = allDone ? (item.completedAt || updatedAt) : null;
    }
  }

  return item;
}

function normalizeItems(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.map(normalizeItem).filter(Boolean);
}

function emitTodoStoreChanged() {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  window.dispatchEvent(new CustomEvent(TODO_STORE_CHANGED_EVENT));
}

export function getDeletedSeedProjectIds() {
  if (typeof localStorage === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(DELETED_SEED_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

export function markSeedProjectDeleted(id) {
  if (!id || typeof localStorage === "undefined") return;
  const isSeed = BACKLOG_PROJECTS_SEED.some((p) => p.id === id);
  if (!isSeed) return;
  try {
    const set = getDeletedSeedProjectIds();
    set.add(id);
    localStorage.setItem(DELETED_SEED_KEY, JSON.stringify(Array.from(set)));
  } catch {}
}

export function ensureBacklogSeeded() {
  const items = listTodos();
  const deletedIds = getDeletedSeedProjectIds();
  const existingIds = new Set(items.map((it) => it.id));
  let added = false;

  BACKLOG_PROJECTS_SEED.forEach((seedProject) => {
    if (deletedIds.has(seedProject.id) || existingIds.has(seedProject.id)) {
      return;
    }
    const normalized = normalizeItem({
      ...seedProject,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    });
    if (normalized) {
      items.push(normalized);
      existingIds.add(normalized.id);
      added = true;
    }
  });

  if (added) {
    saveTodos(items);
    emitTodoStoreChanged();
  }
  return added;
}

function readLocalTodos() {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw);
    return normalizeItems(data);
  } catch {
    return [];
  }
}

function readLocalTodosSnapshot() {
  if (typeof localStorage === "undefined") return "";
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeLocalTodos(items) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    todosLocalSnapshot = readLocalTodosSnapshot();
  } catch {}
}

export async function refreshTodosFromServer() {
  const next = await loadFileBackedSetting({
    name: SERVER_SETTINGS_NAME,
    storageKey: STORAGE_KEY,
    fallback: [],
    normalize: normalizeItems,
  });
  const previous = JSON.stringify(todosCache ?? readLocalTodos());
  todosCache = next;
  writeLocalTodos(next);
  if (JSON.stringify(next) !== previous) {
    emitTodoStoreChanged();
  }
}

export const todoStoreReady = refreshTodosFromServer().catch(() => {});

export function listTodos() {
  const localSnapshot = readLocalTodosSnapshot();
  if (todosCache && localSnapshot === todosLocalSnapshot) return [...todosCache];
  const local = readLocalTodos();
  todosCache = local;
  todosLocalSnapshot = localSnapshot;
  return [...local];
}

function saveTodos(items) {
  const normalized = normalizeItems(items);
  todosCache = normalized;
  saveFileBackedSetting({
    name: SERVER_SETTINGS_NAME,
    storageKey: STORAGE_KEY,
    value: normalized,
  });
  emitTodoStoreChanged();
}

export function addTodo({
  title,
  due,
  bucket,
  priority,
  description,
  order,
  subtasks,
} = {}) {
  const cleanTitle = normalizeTitle(title);
  if (!cleanTitle) return null;
  const items = listTodos();
  const now = Date.now();
  const normalizedBucket = normalizeBucket(bucket);
  const item = {
    id: createId(),
    title: cleanTitle,
    bucket: normalizedBucket,
    due: normalizeDueDate(due),
    done: false,
    completedAt: null,
    createdAt: now,
    updatedAt: now,
  };

  if (normalizedBucket === "projects") {
    item.description = typeof description === "string" ? description : "";
    item.priority = normalizePriority(priority);
    item.order = Number.isFinite(order) ? order : items.filter((i) => i.bucket === "projects").length + 1;
    item.subtasks = Array.isArray(subtasks)
      ? subtasks.map((st, idx) => normalizeSubtask(st, idx)).filter(Boolean)
      : [];
  }

  items.push(item);
  saveTodos(items);
  return item;
}

export function updateTodo(id, updates = {}) {
  if (!id) return null;
  const items = listTodos();
  const index = items.findIndex((item) => item.id === id);
  if (index === -1) return null;

  const current = items[index];
  const now = Date.now();
  const next = { ...current, updatedAt: now };

  if (updates.title !== undefined) {
    const cleanTitle = normalizeTitle(updates.title);
    if (cleanTitle) next.title = cleanTitle;
  }

  if (updates.bucket !== undefined) {
    next.bucket = normalizeBucket(updates.bucket);
  }

  if (updates.due !== undefined) {
    next.due = normalizeDueDate(updates.due);
  }

  if (next.bucket === "projects") {
    if (updates.description !== undefined) {
      next.description = typeof updates.description === "string" ? updates.description : "";
    }
    if (updates.priority !== undefined) {
      next.priority = normalizePriority(updates.priority);
    }
    if (updates.order !== undefined && Number.isFinite(updates.order)) {
      next.order = updates.order;
    }
    if (updates.subtasks !== undefined && Array.isArray(updates.subtasks)) {
      next.subtasks = updates.subtasks.map((st, idx) => normalizeSubtask(st, idx)).filter(Boolean);
    }
    if (!Array.isArray(next.subtasks)) {
      next.subtasks = [];
    }

    if (next.subtasks.length > 0) {
      const allDone = next.subtasks.every((st) => st.done);
      next.done = allDone;
      next.completedAt = allDone ? (next.completedAt || now) : null;
    } else if (updates.done !== undefined) {
      const done = Boolean(updates.done);
      next.done = done;
      next.completedAt = done ? now : null;
    }
  } else {
    delete next.description;
    delete next.priority;
    delete next.order;
    delete next.subtasks;

    if (updates.done !== undefined) {
      const done = Boolean(updates.done);
      next.done = done;
      next.completedAt = done ? now : null;
    }
  }

  items[index] = next;
  saveTodos(items);
  return next;
}

export function deleteTodo(id) {
  if (!id) return false;
  const items = listTodos();
  const item = items.find((entry) => entry.id === id);
  if (!item) return false;
  markSeedProjectDeleted(item.id);
  const next = items.filter((item) => item.id !== id);
  if (next.length === items.length) return false;
  saveTodos(next);
  return true;
}

export function toggleTodo(id, done) {
  const items = listTodos();
  const index = items.findIndex((item) => item.id === id);
  if (index === -1) return null;
  const current = items[index];
  const now = Date.now();
  const nextDone = done ?? !current.done;

  if (current.bucket === "projects" && Array.isArray(current.subtasks) && current.subtasks.length > 0) {
    const nextSubtasks = current.subtasks.map((st) => ({
      ...st,
      done: nextDone,
      updatedAt: now,
    }));
    return updateTodo(id, { done: nextDone, subtasks: nextSubtasks });
  }

  const next = {
    ...current,
    done: nextDone,
    completedAt: nextDone ? now : null,
    updatedAt: now,
  };
  items[index] = next;
  saveTodos(items);
  return next;
}

function syncProjectCompletion(project) {
  if (!project || project.bucket !== "projects") return;
  if (!Array.isArray(project.subtasks) || project.subtasks.length === 0) return;
  const allDone = project.subtasks.every((st) => st.done);
  project.done = allDone;
  project.completedAt = allDone ? (project.completedAt || Date.now()) : null;
}

export function addSubtask(projectId, { title, description } = {}) {
  const cleanTitle = normalizeTitle(title);
  if (!cleanTitle || !projectId) return null;
  const items = listTodos();
  const project = items.find((p) => p.id === projectId && p.bucket === "projects");
  if (!project) return null;

  if (!Array.isArray(project.subtasks)) {
    project.subtasks = [];
  }
  const now = Date.now();
  const subtask = {
    id: createId(),
    title: cleanTitle,
    description: typeof description === "string" ? description.trim() : "",
    done: false,
    order: project.subtasks.length + 1,
    createdAt: now,
    updatedAt: now,
  };

  project.subtasks.push(subtask);
  project.updatedAt = now;
  syncProjectCompletion(project);
  saveTodos(items);
  return subtask;
}

export function updateSubtask(projectId, subtaskId, updates = {}) {
  if (!projectId || !subtaskId) return null;
  const items = listTodos();
  const project = items.find((p) => p.id === projectId && p.bucket === "projects");
  if (!project || !Array.isArray(project.subtasks)) return null;

  const subtask = project.subtasks.find((st) => st.id === subtaskId);
  if (!subtask) return null;

  const now = Date.now();
  if (updates.title !== undefined) {
    const cleanTitle = normalizeTitle(updates.title);
    if (cleanTitle) subtask.title = cleanTitle;
  }
  if (updates.description !== undefined) {
    subtask.description = typeof updates.description === "string" ? updates.description.trim() : "";
  }
  if (updates.done !== undefined) {
    subtask.done = Boolean(updates.done);
  }
  if (updates.order !== undefined && Number.isFinite(updates.order)) {
    subtask.order = updates.order;
  }

  subtask.updatedAt = now;
  project.updatedAt = now;
  syncProjectCompletion(project);
  saveTodos(items);
  return subtask;
}

export function toggleSubtask(projectId, subtaskId, done) {
  if (!projectId || !subtaskId) return null;
  const items = listTodos();
  const project = items.find((p) => p.id === projectId && p.bucket === "projects");
  if (!project || !Array.isArray(project.subtasks)) return null;

  const subtask = project.subtasks.find((st) => st.id === subtaskId);
  if (!subtask) return null;

  const now = Date.now();
  subtask.done = done !== undefined ? Boolean(done) : !subtask.done;
  subtask.updatedAt = now;
  project.updatedAt = now;
  syncProjectCompletion(project);
  saveTodos(items);
  return subtask;
}

export function deleteSubtask(projectId, subtaskId) {
  if (!projectId || !subtaskId) return false;
  const items = listTodos();
  const project = items.find((p) => p.id === projectId && p.bucket === "projects");
  if (!project || !Array.isArray(project.subtasks)) return false;

  const prevLength = project.subtasks.length;
  project.subtasks = project.subtasks.filter((st) => st.id !== subtaskId);
  if (project.subtasks.length === prevLength) return false;

  project.updatedAt = Date.now();
  syncProjectCompletion(project);
  saveTodos(items);
  return true;
}

export function clearDone() {
  const items = listTodos();
  items
    .filter((item) => item.done && item.bucket === "projects")
    .forEach((item) => markSeedProjectDeleted(item.id));
  const next = items.filter((item) => !item.done);
  if (next.length !== items.length) {
    saveTodos(next);
  }
  return next;
}

export function sortTodos(items) {
  const sorted = [...items];
  sorted.sort((a, b) => {
    if (a.done !== b.done) return a.done ? 1 : -1;
    const dateA = a.due ? parseISODate(a.due)?.getTime() ?? null : null;
    const dateB = b.due ? parseISODate(b.due)?.getTime() ?? null : null;
    if (dateA !== dateB) {
      if (dateA === null) return 1;
      if (dateB === null) return -1;
      return dateA - dateB;
    }
    return (a.createdAt || 0) - (b.createdAt || 0);
  });
  return sorted;
}

export function sortProjects(projects) {
  return [...projects].sort((a, b) => {
    const prioA = PRIORITY_ORDER[a.priority] ?? 3;
    const prioB = PRIORITY_ORDER[b.priority] ?? 3;
    if (prioA !== prioB) return prioA - prioB;
    if ((a.order || 0) !== (b.order || 0)) return (a.order || 0) - (b.order || 0);
    return (a.createdAt || 0) - (b.createdAt || 0);
  });
}

export function isRecentlyCompletedTodo(item, now = Date.now()) {
  if (!item?.done) return false;
  const completedAt = Number.isFinite(item.completedAt)
    ? item.completedAt
    : (Number.isFinite(item.updatedAt) ? item.updatedAt : 0);
  return now - completedAt < COMPLETED_ACTIVE_MS;
}

export function isTodoArchived(item, now = Date.now()) {
  return Boolean(item?.done) && !isRecentlyCompletedTodo(item, now);
}

export function isTodoActiveListVisible(item, now = Date.now()) {
  return !item?.done || isRecentlyCompletedTodo(item, now);
}

export function getStats(items) {
  const today = startOfDay(new Date());
  let done = 0;
  let overdue = 0;
  let withDue = 0;

  items.forEach((item) => {
    if (item.done) done += 1;
    const dueDate = item.due ? parseISODate(item.due) : null;
    if (dueDate) {
      withDue += 1;
      if (!item.done && dueDate < today) overdue += 1;
    }
  });

  const total = items.length;
  const open = total - done;
  return {
    total,
    done,
    open,
    overdue,
    withDue,
    dueSoon: items.filter((item) => {
      if (!item.due || item.done) return false;
      const dueDate = parseISODate(item.due);
      if (!dueDate) return false;
      const diffDays = Math.round((dueDate - today) / DAY_MS);
      return diffDays >= 0 && diffDays <= 3;
    }).length,
  };
}
