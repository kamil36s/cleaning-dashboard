import { parseDateMaybe } from './utils.js';
import {
  getActiveCleaningApartmentId,
  getCleaningApartmentHistoryKey,
} from './cleaning-apartments.js';
import { getCleaningHistory } from './cleaning-api.js';

const STORAGE_KEY = 'cleaning.action-history.v1';
export const CLEANING_HISTORY_CHANGED_EVENT = 'cleaning-history:file-changed';
const MAX_EVENTS = 5000;
const DAY_MS = 24 * 60 * 60 * 1000;
const MAX_FORECAST_TASKS_PER_DAY = 10;
const GENTLE_BACKLOG_FIRST_DAY_TARGET = 3;
const RECOVERY_DAY_AFTER_ACTIONS = 10;
const FORECAST_SEARCH_BUFFER_DAYS = 365;
const FORECAST_RAMP_START_STORAGE_KEY = 'cleaning.forecastRampStart.v1';

export const CLEANING_HISTORY_RANGE_DAYS = Object.freeze({
  week: 7,
  month: 30,
  quarter: 90,
  year: 365,
});

const isObject = (value) => typeof value === 'object' && value !== null;

const normalizeText = (value) => {
  if (value == null) return '';
  return String(value).trim();
};

const normalizeStatus = (value) => {
  const normalized = normalizeText(value).toUpperCase();
  return ['DEAD', 'OVERDUE', 'DUE', 'COMING', 'FRESH'].includes(normalized)
    ? normalized
    : '';
};

const normalizeRow = (value) => {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return null;
  return Math.trunc(num);
};

const toDate = (value) => {
  const dt = parseDateMaybe(value);
  if (!dt || Number.isNaN(dt.getTime())) return null;
  return dt;
};

const startOfDay = (dt) => new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
const addDays = (dt, amount) => new Date(dt.getTime() + (amount * DAY_MS));
const diffInDays = (from, to) => Math.round((startOfDay(to) - startOfDay(from)) / DAY_MS);

const startOfWeek = (value) => {
  const dt = startOfDay(value);
  const weekday = dt.getDay() || 7;
  return addDays(dt, 1 - weekday);
};

const startOfMonth = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), dt.getMonth(), 1);
};

const startOfQuarter = (value) => {
  const dt = startOfDay(value);
  const quarterMonth = Math.floor(dt.getMonth() / 3) * 3;
  return new Date(dt.getFullYear(), quarterMonth, 1);
};

const startOfYear = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), 0, 1);
};

const endOfWeek = (value) => addDays(startOfWeek(value), 6);
const endOfMonth = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), dt.getMonth() + 1, 0);
};
const endOfQuarter = (value) => {
  const start = startOfQuarter(value);
  return new Date(start.getFullYear(), start.getMonth() + 3, 0);
};
const endOfYear = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), 11, 31);
};

const dayKey = (dt) => {
  const year = dt.getFullYear();
  const month = String(dt.getMonth() + 1).padStart(2, '0');
  const day = String(dt.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const dayFromKey = (value) => {
  if (!value) return null;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  return new Date(year, month, day);
};

export function getCleaningForecastRampStart(tasks, now = new Date()) {
  const today = startOfDay(toDate(now) || new Date());
  const key = `${FORECAST_RAMP_START_STORAGE_KEY}:${getActiveCleaningApartmentId()}`;
  const hasBacklog = Array.isArray(tasks) && tasks.some((task) => !task?.blocked && !!task?.overdue);
  if (!canUseStorage()) return today;

  try {
    if (!hasBacklog) {
      if (Array.isArray(tasks) && tasks.length > 0) window.localStorage.removeItem(key);
      return today;
    }
    const storedKey = window.localStorage.getItem(key);
    const storedDate = dayFromKey(storedKey);
    if (storedDate && dayKey(storedDate) === storedKey && storedDate <= today) return storedDate;
    window.localStorage.setItem(key, dayKey(today));
  } catch {
    // The plan still works for this page view if storage is unavailable.
  }
  return today;
}

const forecastDailyCapacity = (date, planStart, hasBacklog, recoveryDays) => {
  if (recoveryDays.has(dayKey(date))) return 1;
  if (!hasBacklog) return GENTLE_BACKLOG_FIRST_DAY_TARGET;
  const dayOffset = Math.max(0, diffInDays(planStart, date));
  const ramp = GENTLE_BACKLOG_FIRST_DAY_TARGET + Math.floor((dayOffset + 1) / 2);
  return Math.min(MAX_FORECAST_TASKS_PER_DAY, ramp);
};

export function getCleaningForecastDailyCapacity(tasks, date = new Date(), opts = {}) {
  const day = startOfDay(toDate(date) || new Date());
  const planStart = startOfDay(toDate(opts.planStart) || day);
  const hasBacklog = Array.isArray(tasks) && tasks.some((task) => !task?.blocked && !!task?.overdue);
  return forecastDailyCapacity(day, planStart, hasBacklog, getCleaningRecoveryDayKeys(opts.historyEvents));
}

const normalizeRange = (range) => {
  if (range === 'month' || range === 'quarter' || range === 'year') return range;
  return 'week';
};

const buildCalendarWindow = (range, now, offset = 0) => {
  const normalized = normalizeRange(range);
  const shift = Math.trunc(Number(offset) || 0);

  if (normalized === 'week') {
    const startDate = addDays(startOfWeek(now), shift * 7);
    const endDate = addDays(startDate, 6);
    return { range: normalized, startDate, endDate, days: 7 };
  }

  if (normalized === 'month') {
    const startDate = new Date(now.getFullYear(), now.getMonth() + shift, 1);
    const endDate = endOfMonth(startDate);
    return { range: normalized, startDate, endDate, days: diffInDays(startDate, endDate) + 1 };
  }

  if (normalized === 'quarter') {
    const base = startOfQuarter(now);
    const startDate = new Date(base.getFullYear(), base.getMonth() + (shift * 3), 1);
    const endDate = endOfQuarter(startDate);
    return { range: normalized, startDate, endDate, days: diffInDays(startDate, endDate) + 1 };
  }

  const startDate = new Date(now.getFullYear() + shift, 0, 1);
  const endDate = endOfYear(startDate);
  return { range: normalized, startDate, endDate, days: diffInDays(startDate, endDate) + 1 };
};

export function buildCleaningHistoryWindow(opts = {}) {
  const now = startOfDay(toDate(opts.now) || new Date());
  const offset = Math.trunc(Number(opts.offset) || 0);
  const window = buildCalendarWindow(opts.range, now, offset);
  return {
    range: window.range,
    now,
    offset,
    startDate: window.startDate,
    endDate: window.endDate,
    days: window.days,
    isFuture: window.startDate > now,
    isPast: window.endDate < now,
    includesToday: window.startDate <= now && window.endDate >= now,
  };
}

export const getCleaningHistoryRangeDays = (range, opts = {}) => buildCleaningHistoryWindow({
  range,
  now: opts.now,
}).days;

const byNewest = (a, b) => {
  const left = toDate(a?.at)?.getTime() || 0;
  const right = toDate(b?.at)?.getTime() || 0;
  return right - left;
};

const sortLabelCounts = (map) => [...map.entries()]
  .map(([label, count]) => ({ label, count }))
  .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pl'));

const sortTaskCounts = (map) => [...map.values()]
  .sort((a, b) => b.count - a.count
    || a.label.localeCompare(b.label, 'pl')
    || a.room.localeCompare(b.room, 'pl'));

const createSeriesBucket = () => ({
  count: 0,
  roomsMap: new Map(),
  tasksMap: new Map(),
});

const normalizePositiveInt = (value) => {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return 0;
  return Math.max(0, Math.round(num));
};

const canUseStorage = () => typeof window !== 'undefined' && !!window.localStorage;
const storageKey = () => getCleaningApartmentHistoryKey(STORAGE_KEY);
const cleaningHistoryCache = new Map();

const normalizeEntry = (raw) => {
  if (!isObject(raw)) return null;
  const atDate = toDate(raw.at ?? raw.timestamp ?? raw.ts);
  if (!atDate) return null;

  return {
    id: normalizePositiveInt(raw.id ?? raw.actionId) || undefined,
    actionId: normalizePositiveInt(raw.actionId ?? raw.id) || undefined,
    taskId: normalizePositiveInt(raw.taskId ?? raw.task_id) || undefined,
    at: atDate.toISOString(),
    row: normalizeRow(raw.row ?? raw.taskId ?? raw.task_id),
    task: normalizeText(raw.task ?? raw.taskName ?? raw.task_name),
    room: normalizeText(raw.room),
    category: normalizeText(raw.category),
    status: normalizeStatus(raw.status),
    source: normalizeText(raw.source) || 'cleaning-dashboard',
  };
};

const normalizeList = (rawList) => {
  if (!Array.isArray(rawList)) return [];
  return rawList.map(normalizeEntry).filter(Boolean).sort(byNewest);
};

function emitCleaningHistoryChanged() {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return;
  window.dispatchEvent(new CustomEvent(CLEANING_HISTORY_CHANGED_EVENT));
}

function readLocalHistory(key) {
  if (!canUseStorage()) return [];
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    return normalizeList(JSON.parse(raw));
  } catch (error) {
    console.warn('Failed to read cleaning history:', error);
    return [];
  }
}

async function hydrateCleaningHistory(key = storageKey(), apartmentId = getActiveCleaningApartmentId()) {
  let server = null;
  try {
    const payload = await getCleaningHistory(apartmentId, { range: 'all', offset: 0 });
    server = payload?.actions;
  } catch {}
  const local = readLocalHistory(key);
  const next = server === null || server === undefined ? local : normalizeList(server);
  const previous = JSON.stringify(cleaningHistoryCache.get(key) || local);
  cleaningHistoryCache.set(key, next);
  if (canUseStorage()) {
    try {
      window.localStorage.setItem(key, JSON.stringify(next));
    } catch {}
  }
  if (JSON.stringify(next) !== previous) {
    emitCleaningHistoryChanged();
  }
}

const saveHistory = (entries) => {
  const key = storageKey();
  const normalized = normalizeList(entries);
  cleaningHistoryCache.set(key, normalized);
  if (canUseStorage()) {
    try {
      window.localStorage.setItem(key, JSON.stringify(normalized));
    } catch (error) {
      console.warn('Failed to persist cleaning history:', error);
    }
  }
};

export async function refreshCleaningActionHistory(apartmentId = getActiveCleaningApartmentId()) {
  const key = getCleaningApartmentHistoryKey(STORAGE_KEY);
  await hydrateCleaningHistory(key, apartmentId);
  return cleaningHistoryCache.get(key) || [];
}

export function getCleaningActionHistory() {
  const key = storageKey();
  if (cleaningHistoryCache.has(key)) {
    return cleaningHistoryCache.get(key);
  }
  const normalized = readLocalHistory(key);
  cleaningHistoryCache.set(key, normalized);
  hydrateCleaningHistory(key, getActiveCleaningApartmentId()).catch(() => {});
  return normalized;
}

export function recordCleaningAction(action = {}) {
  const entry = normalizeEntry({
    ...action,
    at: action.at || new Date().toISOString(),
  });
  if (!entry) return null;

  const existing = getCleaningActionHistory();
  const previous = existing[0];

  if (previous) {
    const prevTime = toDate(previous.at)?.getTime() || 0;
    const nextTime = toDate(entry.at)?.getTime() || 0;
    const sameRow = previous.row != null && entry.row != null && previous.row === entry.row;
    const sameTask = !!previous.task && !!entry.task && previous.task === entry.task;
    if ((sameRow || sameTask) && Math.abs(nextTime - prevTime) <= 1500) {
      return previous;
    }
  }

  const next = [entry, ...existing];
  if (next.length > MAX_EVENTS) {
    next.length = MAX_EVENTS;
  }
  saveHistory(next);
  return entry;
}

export function getCleaningDayReference(value = new Date(), options = {}) {
  const target = toDate(value);
  if (!target) return null;
  const rolloverHour = Math.max(0, Math.min(23, Number(options.rolloverHour) || 0));
  const shiftedTarget = addDays(target, 0);
  shiftedTarget.setHours(shiftedTarget.getHours() - rolloverHour);
  return shiftedTarget;
}

export function getCleaningDayKey(value = new Date(), options = {}) {
  const reference = getCleaningDayReference(value, options);
  return reference ? dayKey(startOfDay(reference)) : '';
}

export function getCleaningActionsForDay(events, targetDate = new Date(), options = {}) {
  const key = getCleaningDayKey(targetDate, options);
  if (!key) return [];
  const normalized = normalizeList(events);
  return normalized.filter((entry) => {
    return getCleaningDayKey(entry.at, options) === key;
  });
}

export function getCleaningRecoveryDayKeys(events) {
  const counts = new Map();
  for (const entry of normalizeList(events)) {
    const key = getCleaningDayKey(entry.at, { rolloverHour: 6 });
    if (key) counts.set(key, (counts.get(key) || 0) + 1);
  }
  return new Set([...counts]
    .filter(([, count]) => count >= RECOVERY_DAY_AFTER_ACTIONS)
    .map(([key]) => dayKey(addDays(dayFromKey(key), 1))));
}

export function buildCleaningHistorySeries(events, opts = {}) {
  const now = startOfDay(toDate(opts.now) || new Date());
  const window = opts.range
    ? buildCleaningHistoryWindow({ range: opts.range, now, offset: opts.offset })
    : null;
  const days = window?.days ?? Math.max(1, Math.trunc(Number(opts.days || 7)));
  const startDay = window?.startDate ?? addDays(now, -(days - 1));
  const endDay = window?.endDate ?? now;
  const endExclusive = addDays(endDay, 1);
  const counts = new Map();

  for (const entry of normalizeList(events)) {
    const dt = toDate(entry.at);
    if (!dt || dt < startDay || dt >= endExclusive) continue;
    const key = dayKey(startOfDay(dt));
    let bucket = counts.get(key);
    if (!bucket) {
      bucket = createSeriesBucket();
      counts.set(key, bucket);
    }

    bucket.count += 1;

    const room = normalizeText(entry.room) || 'Bez pokoju';
    bucket.roomsMap.set(room, (bucket.roomsMap.get(room) || 0) + 1);

    const label = normalizeText(entry.task) || 'Zadanie';
    const category = normalizeText(entry.category);
    const status = normalizeStatus(entry.status);
    const taskKey = [label, room, category, status].join('||');
    const taskEntry = bucket.tasksMap.get(taskKey) || {
      label,
      room,
      category,
      status,
      count: 0,
    };
    taskEntry.count += 1;
    bucket.tasksMap.set(taskKey, taskEntry);
  }

  const result = [];
  for (let i = 0; i < days; i += 1) {
    const day = addDays(startDay, i);
    const key = dayKey(day);
    const bucket = counts.get(key) || createSeriesBucket();
    result.push({
      dayKey: key,
      date: day.toISOString(),
      count: bucket.count,
      rooms: sortLabelCounts(bucket.roomsMap),
      tasks: sortTaskCounts(bucket.tasksMap),
      isToday: key === dayKey(now),
    });
  }
  return result;
}

const normalizeForecastTask = (raw) => {
  if (!isObject(raw) || raw.blocked) return null;

  const label = normalizeText(raw.task);
  const room = normalizeText(raw.room) || 'Bez pokoju';
  const category = normalizeText(raw.category);
  const row = normalizeRow(raw.row ?? raw.row_id);
  const freq = normalizePositiveInt(raw.freq);
  if (!label || freq <= 0) return null;

  const nextDueInRaw = Number(raw.nextDueIn);
  const daysSinceRaw = Number(raw.daysSince);
  const overdue = !!raw.overdue;
  const daysSince = Number.isFinite(daysSinceRaw) ? Math.max(0, Math.round(daysSinceRaw)) : 0;

  let dueOffset = 0;
  if (overdue) {
    dueOffset = 0;
  } else if (Number.isFinite(nextDueInRaw)) {
    dueOffset = Math.max(0, Math.round(nextDueInRaw));
  } else if (Number.isFinite(daysSinceRaw)) {
    dueOffset = Math.max(0, freq - Math.round(daysSinceRaw));
  } else {
    dueOffset = freq;
  }

  return {
    row,
    label,
    room,
    category,
    freq,
    dueOffset,
    daysSince,
    lateness: overdue ? Math.max(0, daysSince - freq) : 0,
    overdue,
  };
};

const pickPlannedDate = (
  startDate,
  dueDate,
  loadByDay,
  roomLoadByDay,
  room,
  horizon,
  aggressive = false,
  dailyCapacity = () => MAX_FORECAST_TASKS_PER_DAY,
) => {
  const searchEnd = addDays(
    horizon && horizon > dueDate ? horizon : dueDate,
    FORECAST_SEARCH_BUFFER_DAYS,
  );

  if (aggressive) {
    for (let cursor = startDate; cursor <= dueDate; cursor = addDays(cursor, 1)) {
      const key = dayKey(cursor);
      const totalLoad = loadByDay.get(key) || 0;
      if (totalLoad < dailyCapacity(cursor)) {
        return cursor;
      }
    }

    for (let cursor = addDays(dueDate, 1); cursor <= searchEnd; cursor = addDays(cursor, 1)) {
      const key = dayKey(cursor);
      const totalLoad = loadByDay.get(key) || 0;
      if (totalLoad < dailyCapacity(cursor)) {
        return cursor;
      }
    }

    return null;
  }

  for (let cursor = dueDate; cursor >= startDate; cursor = addDays(cursor, -1)) {
    const key = dayKey(cursor);
    const totalLoad = loadByDay.get(key) || 0;
    if (totalLoad < dailyCapacity(cursor)) {
      return cursor;
    }
  }

  for (let cursor = addDays(dueDate, 1); cursor <= searchEnd; cursor = addDays(cursor, 1)) {
    const key = dayKey(cursor);
    const totalLoad = loadByDay.get(key) || 0;
    if (totalLoad < dailyCapacity(cursor)) {
      return cursor;
    }
  }

  return null;
};

const appendForecastBucket = (map, plannedDate, task, dueDate) => {
  const key = dayKey(plannedDate);
  let bucket = map.get(key);
  if (!bucket) {
    bucket = createSeriesBucket();
    map.set(key, bucket);
  }

  bucket.count += 1;
  bucket.roomsMap.set(task.room, (bucket.roomsMap.get(task.room) || 0) + 1);

  const taskKey = [task.label, task.room, task.category, ''].join('||');
  const taskEntry = bucket.tasksMap.get(taskKey) || {
    label: task.label,
    room: task.room,
    category: task.category,
    status: '',
    count: 0,
    dueDate: dueDate.toISOString(),
    overdue: task.overdue,
    row: task.row,
  };

  taskEntry.count += 1;
  taskEntry.dueDate = taskEntry.dueDate && taskEntry.dueDate < dueDate.toISOString()
    ? taskEntry.dueDate
    : dueDate.toISOString();
  taskEntry.overdue = taskEntry.overdue || task.overdue;
  bucket.tasksMap.set(taskKey, taskEntry);
};

const buildEmptySeries = (window) => {
  const result = [];
  for (let i = 0; i < window.days; i += 1) {
    const date = addDays(window.startDate, i);
    result.push({
      dayKey: dayKey(date),
      date: date.toISOString(),
      count: 0,
      rooms: [],
      tasks: [],
      isToday: dayKey(date) === dayKey(window.now),
    });
  }
  return result;
};

export function buildCleaningForecastSeries(tasks, opts = {}) {
  const window = buildCleaningHistoryWindow(opts);
  const now = window.now;
  if (window.endDate < now) return buildEmptySeries(window);

  const normalized = Array.isArray(tasks)
    ? tasks.map(normalizeForecastTask).filter(Boolean)
    : [];
  const backlogTasks = normalized
    .filter((task) => task.overdue)
    .sort((a, b) => b.lateness - a.lateness
      || a.freq - b.freq
      || a.label.localeCompare(b.label, 'pl'));
  const routineTasks = normalized
    .filter((task) => !task.overdue)
    .sort((a, b) => a.dueOffset - b.dueOffset
      || a.freq - b.freq
      || a.label.localeCompare(b.label, 'pl'));
  const buckets = new Map();
  const loadByDay = new Map();
  const roomLoadByDay = new Map();
  const horizon = window.endDate;
  const recoveryDays = getCleaningRecoveryDayKeys(opts.historyEvents);
  const planStart = startOfDay(toDate(opts.planStart) || now);
  const dailyCapacity = (date) => forecastDailyCapacity(date, planStart, backlogTasks.length > 0, recoveryDays);
  const scheduleTask = (
    task,
    aggressiveFirstInstance = false,
  ) => {
    let plannedBase = now;
    let dueDate = addDays(now, task.dueOffset);
    let useAggressive = aggressiveFirstInstance;

    while (dueDate <= horizon) {
      const scheduledDate = pickPlannedDate(
        plannedBase,
        dueDate,
        loadByDay,
        roomLoadByDay,
        task.room,
        horizon,
        useAggressive,
        dailyCapacity,
      );
      if (!scheduledDate) break;

      const key = dayKey(scheduledDate);
      loadByDay.set(key, (loadByDay.get(key) || 0) + 1);
      roomLoadByDay.set(`${key}::${task.room}`, (roomLoadByDay.get(`${key}::${task.room}`) || 0) + 1);
      appendForecastBucket(buckets, scheduledDate, task, dueDate);

      plannedBase = addDays(scheduledDate, 1);
      dueDate = addDays(scheduledDate, task.freq);
      useAggressive = false;
    }
  };

  for (const task of routineTasks) {
    scheduleTask(task, false);
  }

  for (const task of backlogTasks) {
    scheduleTask(task, true);
  }

  const result = [];
  for (let i = 0; i < window.days; i += 1) {
    const date = addDays(window.startDate, i);
    const key = dayKey(date);
    const bucket = buckets.get(key) || createSeriesBucket();
    result.push({
      dayKey: key,
      date: date.toISOString(),
      count: bucket.count,
      rooms: sortLabelCounts(bucket.roomsMap),
      tasks: sortTaskCounts(bucket.tasksMap),
      isToday: key === dayKey(now),
    });
  }

  return result;
}

const topByField = (events, field) => {
  const counts = new Map();
  for (const entry of events) {
    const key = normalizeText(entry[field]);
    if (!key) continue;
    counts.set(key, (counts.get(key) || 0) + 1);
  }

  let best = null;
  for (const [label, count] of counts.entries()) {
    if (!best || count > best.count) {
      best = { label, count };
      continue;
    }
    if (best && count === best.count && label.localeCompare(best.label, 'pl') < 0) {
      best = { label, count };
    }
  }
  return best;
};

export function summarizeCleaningHistory(events, opts = {}) {
  const now = startOfDay(toDate(opts.now) || new Date());
  const normalized = normalizeList(events);
  const byDay = new Map();

  for (const entry of normalized) {
    const dt = toDate(entry.at);
    if (!dt) continue;
    const key = dayKey(startOfDay(dt));
    byDay.set(key, (byDay.get(key) || 0) + 1);
  }

  const weekSeries = buildCleaningHistorySeries(normalized, { range: 'week', now });
  const monthSeries = buildCleaningHistorySeries(normalized, { range: 'month', now });
  const quarterSeries = buildCleaningHistorySeries(normalized, { range: 'quarter', now });
  const yearSeries = buildCleaningHistorySeries(normalized, { range: 'year', now });
  const weekTotal = weekSeries.reduce((sum, day) => sum + day.count, 0);
  const monthTotal = monthSeries.reduce((sum, day) => sum + day.count, 0);
  const quarterTotal = quarterSeries.reduce((sum, day) => sum + day.count, 0);
  const yearTotal = yearSeries.reduce((sum, day) => sum + day.count, 0);
  const today = byDay.get(dayKey(now)) || 0;

  let streak = 0;
  let cursor = startOfDay(now);
  while ((byDay.get(dayKey(cursor)) || 0) > 0) {
    streak += 1;
    cursor = addDays(cursor, -1);
  }

  let bestDay = null;
  for (const [key, count] of byDay.entries()) {
    if (!bestDay || count > bestDay.count) {
      bestDay = { dayKey: key, count };
      continue;
    }
    if (count === bestDay.count && key > bestDay.dayKey) {
      bestDay = { dayKey: key, count };
    }
  }

  const monthWindow = buildCleaningHistoryWindow({ range: 'month', now });
  const monthStart = monthWindow.startDate;
  const endExclusive = addDays(monthWindow.endDate, 1);
  const monthEvents = normalized.filter((entry) => {
    const dt = toDate(entry.at);
    return !!dt && dt >= monthStart && dt < endExclusive;
  });

  return {
    today,
    weekTotal,
    monthTotal,
    quarterTotal,
    yearTotal,
    weekAvg: Math.round((weekTotal / Math.max(1, weekSeries.length)) * 10) / 10,
    monthAvg: Math.round((monthTotal / Math.max(1, monthSeries.length)) * 10) / 10,
    quarterAvg: Math.round((quarterTotal / Math.max(1, quarterSeries.length)) * 10) / 10,
    yearAvg: Math.round((yearTotal / Math.max(1, yearSeries.length)) * 10) / 10,
    streak,
    topTask: topByField(monthEvents, 'task'),
    topRoom: topByField(monthEvents, 'room'),
    bestDay: bestDay
      ? {
          ...bestDay,
          date: dayFromKey(bestDay.dayKey)?.toISOString() || '',
        }
      : null,
  };
}

export function summarizeCleaningForecastSeries(series) {
  const normalized = Array.isArray(series) ? series : [];
  const roomCounts = new Map();
  const taskCounts = new Map();
  let maxDay = null;

  const total = normalized.reduce((sum, day) => {
    const count = Number(day?.count) || 0;
    if (count > 0 && (!maxDay || count > maxDay.count || (count === maxDay.count && String(day.dayKey) > String(maxDay.dayKey)))) {
      maxDay = {
        dayKey: day.dayKey,
        date: day.date,
        count,
      };
    }

    for (const room of Array.isArray(day?.rooms) ? day.rooms : []) {
      roomCounts.set(room.label, (roomCounts.get(room.label) || 0) + (Number(room.count) || 0));
    }

    for (const task of Array.isArray(day?.tasks) ? day.tasks : []) {
      const key = [task.label, task.room, task.category || ''].join('||');
      const current = taskCounts.get(key) || {
        label: task.label,
        room: task.room,
        category: task.category || '',
        count: 0,
      };
      current.count += Number(task.count) || 0;
      taskCounts.set(key, current);
    }

    return sum + count;
  }, 0);

  const activeDays = normalized.filter((day) => (Number(day?.count) || 0) > 0).length;
  const topRoom = sortLabelCounts(roomCounts)[0] || null;
  const topTask = sortTaskCounts(taskCounts)[0] || null;

  return {
    total,
    activeDays,
    avgPerDay: normalized.length
      ? Math.round((total / normalized.length) * 10) / 10
      : 0,
    maxDay,
    topRoom,
    topTask,
  };
}

export function clearCleaningHistory() {
  const key = storageKey();
  cleaningHistoryCache.set(key, []);
  try {
    if (canUseStorage()) window.localStorage.removeItem(key);
  } catch (error) {
    console.warn('Failed to clear cleaning history:', error);
  }
  saveFileSetting(historySettingsName(), []).catch(() => {});
}
