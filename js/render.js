import { DATA } from './state.js';
import { fmtTimeShort, isSameDay, parseDateMaybe } from './utils.js';
import { formatCleaningDate, formatCleaningDateWithWeekday } from './cleaning-format.js';
import { groupTasksByCategory, groupTasksByRoom, preserveTaskOrder } from './cleaning-logic.js';
import { colorForCleaningProgress } from './cleaning-progress-color.js';
import { deleteCleaningAction } from './cleaning-api.js';
import { getActiveCleaningApartmentId } from './cleaning-apartments.js';
import { iconFor } from './icons.js';
import {
  buildCleaningForecastSeries,
  buildCleaningHistoryWindow,
  buildCleaningHistorySeries,
  getCleaningActionHistory,
  getCleaningActionsForDay,
  getCleaningForecastRampStart,
  refreshCleaningActionHistory,
  summarizeCleaningForecastSeries,
  summarizeCleaningHistory,
} from './cleaning-history.js';

export let LAST_LIST = [];
let LAST_LIST_SIGNATURE = '';
let KEEP_CURRENT_TASK_ORDER = false;
const CLEANING_TASK_VIEW_STORAGE_KEY = 'cleaningDashboard.taskView.v1';
const CLEANING_TASK_VIEW_MODES = new Set(['all', 'room', 'category']);

const readCleaningTaskViewMode = () => {
  try {
    const stored = typeof window !== 'undefined'
      ? window.localStorage.getItem(CLEANING_TASK_VIEW_STORAGE_KEY)
      : null;
    if (CLEANING_TASK_VIEW_MODES.has(stored)) return stored;
  } catch {
    // A blocked localStorage must not block the Cleaning page.
  }
  return 'room';
};

let CLEANING_TASK_VIEW_MODE = readCleaningTaskViewMode();

export function getCleaningTaskViewMode() {
  return CLEANING_TASK_VIEW_MODE;
}

export function setCleaningTaskViewMode(mode) {
  if (!CLEANING_TASK_VIEW_MODES.has(mode)) return CLEANING_TASK_VIEW_MODE;
  CLEANING_TASK_VIEW_MODE = mode;
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(CLEANING_TASK_VIEW_STORAGE_KEY, mode);
    }
  } catch {
    // Keep the selected mode for this page session when storage is unavailable.
  }
  return CLEANING_TASK_VIEW_MODE;
}

export function preserveCleaningTaskPositions() {
  KEEP_CURRENT_TASK_ORDER = true;
}

const roomTaskCountLabel = (count) => {
  if (count === 1) return '1 zadanie';
  if (count >= 2 && count <= 4) return `${count} zadania`;
  return `${count} zadań`;
};

const roomProgress = (tasks) => {
  const active = Array.isArray(tasks) ? tasks.filter((task) => !task?.blocked) : [];
  const total = active.length;
  const current = Array.isArray(tasks)
    ? active.filter((task) => !task?.overdue && !isDue(task)).length
    : 0;
  return {
    current,
    total,
    percent: total ? Math.round((current / total) * 100) : 0,
  };
};

// aktywny filtr po "Supplies"
const SUPPLY_FILTER = new Set();
// whether click handler for #supplies-list has been attached
let SUPPLIES_WIRED = false;
let HISTORY_WIRED = false;
let HISTORY_DIALOG_WIRED = false;
let OPEN_HISTORY_PERIOD = null;
let HISTORY_RANGE = 'week';
let HISTORY_OFFSET = 0;

const HISTORY_RANGE_OPTIONS = [
  { key: 'week', label: 'Tydzień' },
  { key: 'month', label: 'Miesiąc' },
  { key: 'year', label: 'Rok' },
];

const HISTORY_CALENDAR_WEEKDAYS = ['pn', 'wt', 'sr', 'cz', 'pt', 'sb', 'nd'];

// --- CONFIG + HELPERS ---
const COMING_FRAC = 0.92;
const N = v => (v==null || v==='') ? null : Number(v);
const hasTimeInfo = (value) => {
  if (value == null || value === '') return false;
  if (value instanceof Date) return true;
  if (typeof value === 'number') return true;
  if (typeof value === 'string') return /\d:\d/.test(value);
  return false;
};

const daysOver = t =>
  t.overdue ? Math.max(0, (N(t.daysSince)||0) - (N(t.freq)||0)) : 0;

const usedFrac = t => (
  t.overdue
    ? 1.01
    : (
        Number.isFinite(N(t.freq)) &&
        N(t.freq) > 0 &&
        Number.isFinite(N(t.daysSince))
      )
      ? (N(t.daysSince)/N(t.freq))
      : 0
);

const isDue     = t => !t.overdue && N(t.nextDueIn) === 0;
const isDead    = t => t.overdue && daysOver(t) > 7;
const isComing  = t => !t.overdue && !isDue(t) && usedFrac(t) >= COMING_FRAC;

const pctOf     = t => Math.min(100, Math.max(0, Math.round(usedFrac(t) * 100)));
const keyOf     = t => String(t.id ?? t.row ?? [t.room || '', t.category || '', t.task || ''].join('|'));

const colorOf = t => {
  if (t.blocked)  return 'blocked';
  if (isDead(t))   return 'dead';
  if (t.overdue)   return 'red';
  if (isDue(t))    return 'yellow';
  if (isComing(t)) return 'lime';
  return 'green';
};

// --- KPI METRYKI ---
export function metrics(arr){
  const active = arr.filter((task) => !task.blocked);
  const today = active.filter(t => !t.overdue && N(t.nextDueIn) === 0).length;
  const ov    = active.filter(t => t.overdue).length;
  const total = active.length;

  const delays = active
    .filter(t => t.overdue && N(t.daysSince) != null)
    .map(t => (N(t.daysSince) || 0) - (N(t.freq) || 0));

  const avg = delays.length
    ? (delays.reduce((a,b)=>a+b,0) / delays.length)
    : 0;

  return {
    today,
    ov,
    total,
    avg: Math.max(0, Math.round(avg * 10) / 10)
  };
}

// DEAD(0) -> OVERDUE(1) -> DUE(2) -> COMING(3) -> FRESH(4)
function statusRank(t) {
  if (t.blocked) return 5;
  if (isDead(t))   return 0;
  if (t.overdue)   return 1;
  if (isDue(t))    return 2;
  if (isComing(t)) return 3;
  return 4;
}

// parse one task's supplies into ["Paper towel", "Mop", ...]
function parseArticles(t){
  return (t.articles || '')
    .split(/[\n,]+/)
    .map(s => s.trim())
    .filter(Boolean);
}

// build supply chips for a single task
function articlesHTMLFor(t){
  const list = parseArticles(t);
  if (!list.length) return '';

  return `<div class="needs">${
    list.map(a => `<span class="need-chip">${escapeHtml(a)}</span>`).join('')
  }</div>`;
}

// check if task matches active SUPPLY_FILTER
// if nothing is selected -> true for all tasks
// if selected ["Mop","Towel"] -> task must contain both entries
function taskHasAllSupplies(t, filterSet){
  if (!filterSet || filterSet.size === 0) return true;

  const artsLower = new Set(parseArticles(t).map(a => a.toLowerCase()));
  for (const wanted of filterSet){
    if (!artsLower.has(wanted)) return false;
  }
  return true;
}

// collect unique supply names from task list (after room/category/dueOnly,
// ale jeszcze PRZED filtrem SUPPLY_FILTER)
function collectSupplies(tasks){
  const uniq = new Map(); // key: lowercase, val: oryginalny tekst

  for (const t of tasks){
    for (const item of parseArticles(t)){
      const key = item.toLowerCase();
      if (!uniq.has(key)){
        uniq.set(key, item);
      }
    }
  }

  return [...uniq.values()];
}

// render "Supplies" panel with chips
// chip visual state reflects SUPPLY_FILTER
function renderSuppliesBox(baseTasks){
  const box = document.getElementById('supplies-list');
  if (!box) return;

  const supplies = collectSupplies(baseTasks);

  if (!supplies.length){
    box.textContent = '-';
    return;
  }

  box.innerHTML = supplies
    .map(txt => {
      const key = txt.toLowerCase();
      const active = SUPPLY_FILTER.has(key);
      return `<span class="need-chip ${active ? 'active' : ''}" data-supply="${escapeHtml(txt)}">${escapeHtml(txt)}</span>`;
    })
    .join('');

  // attach delegated click handler only once
  if (!SUPPLIES_WIRED){
    SUPPLIES_WIRED = true;
    box.addEventListener('click', e => {
      const chip = e.target.closest('.need-chip');
      if (!chip) return;
      const raw = chip.getAttribute('data-supply');
      if (!raw) return;

      const key = raw.toLowerCase();
      if (SUPPLY_FILTER.has(key)){
        SUPPLY_FILTER.delete(key);
      } else {
        SUPPLY_FILTER.add(key);
      }

      // rerender after filter change
      render();
    });
  }
}

function cardHTML(t){
  const id   = (t.id ?? t.row ?? t.row_id ?? null);
  const pct  = pctOf(t);
  const over = t.overdue;
  const dead = isDead(t);
  const due  = isDue(t);
  const coming = isComing(t);

  const frameClass = t.blocked ? 'blocked' : dead
    ? 'dead'
    : (over
        ? 'overdue'
        : (due
            ? 'due'
            : (coming ? 'coming' : '')));

  const overdueBy = daysOver(t);
  const nextDue = N(t.nextDueIn);
  const nextDueLabel = Number.isFinite(nextDue) ? `${nextDue}d` : null;

  let badgeLabel = '';
  if (t.blocked) {
    badgeLabel = 'BLOCKED';
  } else if (dead) {
    badgeLabel = `DEAD \u2022 ${overdueBy}d`;
  } else if (over) {
    badgeLabel = `OVERDUE \u2022 ${overdueBy}d`;
  } else if (due) {
    badgeLabel = 'DUE \u2022 today';
  } else if (coming) {
    badgeLabel = nextDueLabel ? `COMING \u2022 ${nextDueLabel}` : 'COMING';
  } else {
    badgeLabel = nextDueLabel ? `FRESH \u2022 ${nextDueLabel}` : 'FRESH';
  }

  const metaParts = [];
  if (t.room) {
    metaParts.push(t.room);
  }
  metaParts.push(`co ${t.freq || '?'} dni`);
  if (t.lastDone) {
    metaParts.push(`ostatnio: ${formatCleaningDate(t.lastDone)}`);
  }
  const metaText = metaParts.join(' | ');

  return `
  <div class="card ${frameClass}" data-key="${escapeHtml(keyOf(t))}">
    <div class="header">
      <div style="flex:1">
        <div class="title">
          <span class="ico">${iconFor(t.category)}</span>
          <span>${escapeHtml(t.task)}</span>
        </div>

        <div class="meta meta-inline">${escapeHtml(metaText)}</div>

        ${articlesHTMLFor(t)}
      </div>

      <div class="badges">
        <span class="cleaning-task-actions" aria-label="Opcje zadania">
          <button class="cleaning-task-action" type="button" data-action="edit" data-task-id="${id}" title="Edytuj zadanie" aria-label="Edytuj zadanie">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11-4-4L4 16v4Zm10-13 4 4M13.5 6.5l4 4"/></svg>
          </button>
          <button class="cleaning-task-action is-delete" type="button" data-action="delete" data-task-id="${id}" title="Usuń zadanie" aria-label="Usuń zadanie">&times;</button>
        </span>
        ${t.blocked
          ? `<button class="pill pill-blocked" type="button" disabled title="Kup Mop do podłogi w TODO">${badgeLabel}</button>`
          : ''}
        ${(!t.blocked && dead)
          ? `<button class="pill pill-dead"  data-row="${id}" data-action="done">${badgeLabel}</button>`
          : ''}
        ${(!t.blocked && !dead && over)
          ? `<button class="pill pill-over" data-row="${id}" data-action="done">${badgeLabel}</button>`
          : ''}
        ${(!t.blocked && !dead && !over && due)
          ? `<button class="pill pill-due"  data-row="${id}" data-action="done">${badgeLabel}</button>`
          : ''}
        ${(!t.blocked && !dead && !over && !due && coming)
          ? `<button class="pill pill-coming" data-row="${id}" data-action="done">${badgeLabel}</button>`
          : ''}
        ${(!t.blocked && !dead && !over && !due && !coming)
          ? `<button class="pill pill-fresh"  data-row="${id}" data-action="done">${badgeLabel}</button>`
          : ''}
      </div>
    </div>

    <div class="progress">
      <div class="${colorOf(t)}" style="width:${pct}%"></div>
    </div>

    <div class="footer">
      <span>${t.blocked ? 'Czeka na zakup mopa' : (N(t.daysSince) != null ? `Since: ${N(t.daysSince)}d` : 'Never')}</span>
    </div>
  </div>`;
}

const taskRowId = (task) => {
  const raw = task?.row ?? task?.row_id;
  const num = Number(raw);
  if (!Number.isFinite(num) || num <= 0) return null;
  return Math.trunc(num);
};

const dayLabel = (date, days, index, isToday = false) => {
  if (!date) return '';
  if (days <= 7) {
    return date
      .toLocaleDateString('pl-PL', { weekday: 'short' })
      .replace('.', '');
  }
  if (days <= 30) {
    if (isToday) return 'dziś';
    if (index % 5 !== 0) return '';
    return formatCleaningDate(date);
  }
  if (days <= 90) {
    if (isToday) return 'dziś';
    if (index % 14 !== 0) return '';
    return formatCleaningDate(date);
  }
  if (isToday) return 'dziś';
  if (date.getDate() !== 1 && index !== 0) return '';
  return date.toLocaleDateString('pl-PL', { month: 'short' }).replace('.', '');
};

const dayLabelFull = (date) => {
  if (!date) return '';
  return formatCleaningDateWithWeekday(date);
};

const dayFromSeries = (day) => parseDateMaybe(day?.date || day?.dayKey);

const calendarWeekdayIndex = (date) => {
  if (!date) return 0;
  return (date.getDay() + 6) % 7;
};

const calendarDateLabel = (date) => {
  if (!date) return '';
  return formatCleaningDate(date);
};

const buildHistoryCalendarMonthMarkup = (startDate, items) => {
  const offset = calendarWeekdayIndex(startDate);
  const trailing = (7 - ((offset + items.length) % 7)) % 7;
  const headers = HISTORY_CALENDAR_WEEKDAYS
    .map((label, index) => `<div class="history-calendar-head${index >= 5 ? ' is-weekend' : ''}">${label}</div>`)
    .join('');
  const lead = Array.from({ length: offset }, () => '<div class="history-calendar-spacer" aria-hidden="true"></div>').join('');
  const tail = Array.from({ length: trailing }, () => '<div class="history-calendar-spacer" aria-hidden="true"></div>').join('');
  return `${headers}${lead}${items.join('')}${tail}`;
};

const escapeHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const formatStatValue = (value, fallback = '-') => {
  if (value == null || value === '') return fallback;
  return String(value);
};

const actionLabel = (value) => `${Number(value) || 0} akcji`;

const formatHistoryDate = (value) => {
  const dt = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(dt.getTime())) return '-';
  return formatCleaningDate(dt);
};

const getHistoryWindowLabel = (windowMeta) => {
  if (!windowMeta) return '-';
  const start = formatHistoryDate(windowMeta.startDate);
  const end = formatHistoryDate(windowMeta.endDate);
  return windowMeta.isFuture ? `Plan: ${start} - ${end}` : `${start} - ${end}`;
};

const historyDayParts = (value) => {
  const dt = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(dt.getTime())) {
    return { weekday: '-', date: '-' };
  }
  return {
    weekday: dt.toLocaleDateString('pl-PL', { weekday: 'short' }).replace('.', ''),
    date: formatCleaningDate(dt),
  };
};

const monthSummaryTitle = (value, includeYear = true) => {
  const dt = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(dt.getTime())) return '-';
  return dt.toLocaleDateString('pl-PL', includeYear
    ? { month: 'long', year: 'numeric' }
    : { month: 'long' });
};

const monthSummaryLabelParts = (value) => {
  const dt = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(dt.getTime())) {
    return { weekday: '-', date: '' };
  }
  return {
    weekday: dt.toLocaleDateString('pl-PL', { month: 'short' }).replace('.', ''),
    date: '',
  };
};

const HISTORY_STATUS_COLORS = {
  DEAD: 'var(--dead)',
  OVERDUE: 'var(--over)',
  DUE: 'var(--due)',
  COMING: 'var(--coming)',
  FRESH: 'var(--fresh)',
  '': 'var(--fresh)',
};

const HISTORY_STATUS_ORDER = {
  DEAD: 0,
  OVERDUE: 1,
  DUE: 2,
  COMING: 3,
  FRESH: 4,
  '': 5,
};

const historyStatusColor = (status) => HISTORY_STATUS_COLORS[String(status || '').toUpperCase()] || 'var(--fresh)';

const historyStatusLabel = (status) => {
  const normalized = String(status || '').toUpperCase();
  return normalized || 'OK';
};

const sortTasksForHistoryDisplay = (items = []) => [...items].sort((a, b) =>
  (HISTORY_STATUS_ORDER[String(a?.status || '').toUpperCase()] ?? 99)
    - (HISTORY_STATUS_ORDER[String(b?.status || '').toUpperCase()] ?? 99)
  || (Number(b?.count) || 0) - (Number(a?.count) || 0)
  || String(a?.label || '').localeCompare(String(b?.label || ''), 'pl')
  || String(a?.room || '').localeCompare(String(b?.room || ''), 'pl'));

const mergeSeriesTasks = (target, items = []) => {
  for (const item of items) {
    const key = [item.label, item.room || '', item.category || '', item.status || ''].join('||');
    const current = target.get(key) || {
      label: item.label,
      room: item.room || '',
      category: item.category || '',
      status: item.status || '',
      count: 0,
      dueDate: item.dueDate || '',
      overdue: !!item.overdue,
    };
    current.count += Number(item.count) || 0;
    if (!current.dueDate || (item.dueDate && item.dueDate < current.dueDate)) {
      current.dueDate = item.dueDate || current.dueDate;
    }
    current.overdue = current.overdue || !!item.overdue;
    target.set(key, current);
  }
};

const aggregateCleaningSeriesByMonth = (series) => {
  const buckets = new Map();

  for (const day of Array.isArray(series) ? series : []) {
    const dt = dayFromSeries(day);
    if (!dt) continue;
    const monthStart = new Date(dt.getFullYear(), dt.getMonth(), 1);
    const key = `${monthStart.getFullYear()}-${String(monthStart.getMonth() + 1).padStart(2, '0')}`;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = {
        dayKey: key,
        date: monthStart.toISOString(),
        count: 0,
        roomsMap: new Map(),
        tasksMap: new Map(),
        isToday: false,
      };
      buckets.set(key, bucket);
    }

    bucket.count += Number(day?.count) || 0;
    for (const room of Array.isArray(day?.rooms) ? day.rooms : []) {
      bucket.roomsMap.set(room.label, (bucket.roomsMap.get(room.label) || 0) + (Number(room.count) || 0));
    }
    mergeSeriesTasks(bucket.tasksMap, day.tasks);
    bucket.isToday = bucket.isToday || !!day?.isToday;
  }

  return [...buckets.values()].map((bucket) => ({
    dayKey: bucket.dayKey,
    date: bucket.date,
    count: bucket.count,
    rooms: [...bucket.roomsMap.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pl')),
    tasks: [...bucket.tasksMap.values()]
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pl')),
    isToday: bucket.isToday,
  }));
};

const renderCleaningHistorySegments = (day, totalCount = Number(day?.count) || 0) => {
  const tasks = sortTasksForHistoryDisplay(Array.isArray(day?.tasks) ? day.tasks : []);
  return tasks
    .filter((task) => (Number(task.count) || 0) > 0)
    .map((task) => {
      const pct = Math.max(6, Math.round(((Number(task.count) || 0) / Math.max(1, totalCount)) * 100));
      return `<span class="history-bar-segment" style="height:${pct}%; background:${historyStatusColor(task.status)};"></span>`;
    })
    .join('');
};

const cleaningHistoryAriaLabel = (day, options = {}) => {
  const dt = dayFromSeries(day);
  const title = options.scope === 'month' ? monthSummaryTitle(dt, true) : dayLabelFull(dt);
  const count = Number(day?.count) || 0;
  return options.isForecast
    ? `${title}: plan ${actionLabel(count)}`
    : `${title}: ${actionLabel(count)}`;
};

const renderCleaningHistoryTooltip = (day, options = {}) => {
  const dt = dayFromSeries(day);
  const count = Number(day?.count) || 0;
  const title = options.scope === 'month' ? monthSummaryTitle(dt, true) : dayLabelFull(dt);
  const kicker = options.isForecast
    ? (options.scope === 'month' ? 'Plan miesiąca' : 'Plan dnia')
    : (options.scope === 'month' ? 'Historia miesiąca' : 'Historia dnia');
  const tasks = sortTasksForHistoryDisplay(Array.isArray(day?.tasks) ? day.tasks : []);
  const rooms = Array.isArray(day?.rooms) ? day.rooms : [];

  const listMarkup = tasks.length
    ? `
        <div class="history-bar-tooltip-list">
          ${tasks.slice(0, 6).map((task) => `
            <div class="history-bar-tooltip-item">
              <span class="history-bar-tooltip-name">
                <span class="history-bar-tooltip-dot" style="background:${historyStatusColor(task.status)};"></span>
                <span>${escapeHtml(task.label)}${task.room ? ` · ${escapeHtml(task.room)}` : ''}${task.status ? ` · ${historyStatusLabel(task.status)}` : ''}</span>
              </span>
              <span class="history-bar-tooltip-pages">${Number(task.count) || 0}</span>
            </div>
          `).join('')}
        </div>
      `
    : (rooms.length
      ? `
          <div class="history-bar-tooltip-list">
            ${rooms.slice(0, 4).map((room) => `
              <div class="history-bar-tooltip-item">
                <span class="history-bar-tooltip-name">
                  <span class="history-bar-tooltip-dot" style="background:${historyStatusColor('')}"></span>
                  <span>${escapeHtml(room.label)}</span>
                </span>
                <span class="history-bar-tooltip-pages">${Number(room.count) || 0}</span>
              </div>
            `).join('')}
          </div>
        `
      : '');

  const emptyText = options.isForecast
    ? (count > 0 ? 'Rekomendowane akcje do wykonania w tym okresie.' : 'Brak planu na ten okres.')
    : (count > 0 ? 'Zrobione zadania w tym okresie.' : 'Brak akcji w tym okresie.');

  return `
      <div class="history-bar-tooltip" aria-hidden="true">
        <div class="history-bar-tooltip-kicker">${kicker}</div>
        <div class="history-bar-tooltip-title">${escapeHtml(title)}</div>
        <div class="history-bar-tooltip-total">${actionLabel(count)}</div>
        ${listMarkup || `<div class="history-bar-tooltip-empty">${emptyText}</div>`}
      </div>
    `;
};

const HISTORY_BAR_MAX_PCT = 78;

const countToHistoryPct = (count, maxCount, minPct = 0, maxPct = HISTORY_BAR_MAX_PCT) => {
  const safeCount = Math.max(0, Number(count) || 0);
  const safeMax = Math.max(1, Number(maxCount) || 0);
  if (safeCount <= 0) return 0;
  return Math.max(minPct, Math.min(maxPct, Math.round((safeCount / safeMax) * maxPct)));
};

const renderCleaningHistoryBar = (day, options = {}) => {
  const value = Math.max(0, Number(day?.count) || 0);
  const fillCount = Math.max(0, Number(options.fillCount ?? value) || 0);
  const maxCount = Math.max(1, Number(options.maxCount) || 0);
  const targetCount = Math.max(0, Number(options.targetCount) || 0);
  const pct = countToHistoryPct(fillCount, maxCount, 10);
  const targetPct = countToHistoryPct(targetCount, maxCount, 10);
  const showValue = options.showValue !== false;
  const labelParts = options.labelParts || historyDayParts(day?.date);
  const classes = ['history-bar'];
  const fillClasses = ['history-bar-fill'];
  if (options.isForecast) classes.push('is-forecast');
  else classes.push('is-clickable');
  if (day?.isToday) classes.push('is-today');
  if (options.isForecast) fillClasses.push('is-forecast');
  if (fillCount <= 0) fillClasses.push('is-empty');

  return `
      <div class="${classes.join(' ')}" tabindex="0"
        ${options.isForecast ? '' : `role="button" data-history-key="${escapeHtml(day?.dayKey || '')}" data-history-scope="${escapeHtml(options.scope || 'day')}"`}
        aria-label="${escapeHtml(cleaningHistoryAriaLabel(day, {
        isForecast: options.isForecast,
        scope: options.scope,
      }))}">
        <div class="history-bar-track">
          ${targetPct > 0 ? `
            <span class="history-bar-target-line" style="bottom:calc(${targetPct}% - 1px)" aria-hidden="true">
              <span class="history-bar-target-badge">${actionLabel(targetCount)}</span>
            </span>
          ` : ''}
          <div class="${fillClasses.join(' ')}"${fillCount > 0 ? ` style="height:${pct}%"` : ''}>
            ${fillCount > 0 ? renderCleaningHistorySegments(day, value) : ''}
          </div>
        </div>
        <div class="history-bar-value${showValue ? '' : ' is-hidden'}">${showValue ? value : '&nbsp;'}</div>
        <div class="history-bar-label${options.scope === 'month' ? ' is-month-summary' : ''}">
          <span class="history-bar-label-day">${labelParts.weekday}</span>
          <span class="history-bar-label-date">${labelParts.date}</span>
        </div>
        ${renderCleaningHistoryTooltip(day, {
          isForecast: options.isForecast,
          scope: options.scope,
        })}
      </div>
    `;
};

const historyEntriesForPeriod = (events, key, scope) => {
  if (scope === 'month') {
    return (Array.isArray(events) ? events : []).filter((entry) => {
      const dt = parseDateMaybe(entry?.at);
      if (!dt) return false;
      const monthKey = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}`;
      return monthKey === key;
    });
  }
  const date = parseDateMaybe(`${key}T12:00:00`);
  return date ? getCleaningActionsForDay(events, date) : [];
};

const historyPeriodTitle = (key, scope) => {
  if (scope === 'month') {
    const match = String(key || '').match(/^(\d{4})-(\d{2})$/);
    if (!match) return 'Historia akcji';
    return `Historia: ${monthSummaryTitle(new Date(Number(match[1]), Number(match[2]) - 1, 1), true)}`;
  }
  const date = parseDateMaybe(`${key}T12:00:00`);
  return `Historia dnia: ${formatCleaningDate(date)}`;
};

function closeHistoryDialog() {
  const dialog = document.getElementById('cleaning-day-dialog');
  OPEN_HISTORY_PERIOD = null;
  if (!dialog) return;
  if (typeof dialog.close === 'function') dialog.close();
  else dialog.removeAttribute('open');
}

function renderOpenHistoryDialog() {
  if (!OPEN_HISTORY_PERIOD) return;
  const dialog = document.getElementById('cleaning-day-dialog');
  const title = document.getElementById('cleaning-day-dialog-title');
  const count = document.getElementById('cleaning-day-dialog-count');
  const list = document.getElementById('cleaning-day-dialog-list');
  const empty = document.getElementById('cleaning-day-dialog-empty');
  const error = document.getElementById('cleaning-day-dialog-error');
  if (!dialog || !title || !count || !list || !empty || !error) return;

  const { key, scope } = OPEN_HISTORY_PERIOD;
  const entries = historyEntriesForPeriod(getCleaningActionHistory(), key, scope);
  title.textContent = historyPeriodTitle(key, scope);
  count.textContent = actionLabel(entries.length);
  error.hidden = true;
  error.textContent = '';
  list.innerHTML = entries.map((entry) => {
    const dt = parseDateMaybe(entry.at);
    const time = dt ? fmtTimeShort(dt) : '-';
    const datePrefix = scope === 'month' && dt ? `${formatCleaningDate(dt)} \u00b7 ` : '';
    const meta = [entry.room, entry.category].filter(Boolean).join(' \u00b7 ');
    const actionId = entry.actionId || entry.id;
    return `
      <article class="cleaning-day-action">
        <span class="cleaning-day-action-dot" style="background:${historyStatusColor(entry.status)}" aria-hidden="true"></span>
        <span class="cleaning-day-action-copy">
          <strong>${escapeHtml(entry.task || 'Zadanie')}</strong>
          <small>${escapeHtml(meta || 'Bez dodatkowych danych')}</small>
        </span>
        <time datetime="${escapeHtml(entry.at)}">${escapeHtml(datePrefix + time)}</time>
        <button type="button" class="cleaning-day-action-delete" data-action-id="${actionId || ''}"
          ${actionId ? '' : 'disabled'} title="Usu\u0144 t\u0119 akcj\u0119" aria-label="Usu\u0144 akcj\u0119: ${escapeHtml(entry.task || 'zadanie')}">&times;</button>
      </article>
    `;
  }).join('');
  list.hidden = entries.length === 0;
  empty.hidden = entries.length > 0;

  if (!dialog.open) {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }
}

function openHistoryDialog(key, scope = 'day') {
  if (!key) return;
  OPEN_HISTORY_PERIOD = { key, scope };
  renderOpenHistoryDialog();
}

function wireHistoryDialog() {
  if (HISTORY_DIALOG_WIRED) return;
  const dialog = document.getElementById('cleaning-day-dialog');
  if (!dialog) return;
  document.getElementById('cleaning-day-dialog-close')?.addEventListener('click', closeHistoryDialog);
  dialog.addEventListener('close', () => { OPEN_HISTORY_PERIOD = null; });
  dialog.addEventListener('click', async (event) => {
    if (event.target === dialog) {
      closeHistoryDialog();
      return;
    }
    const button = event.target.closest('button.cleaning-day-action-delete[data-action-id]');
    if (!button || button.disabled) return;
    const entry = getCleaningActionHistory().find((item) => String(item.actionId || item.id) === button.dataset.actionId);
    const confirmed = window.confirm(`Usun\u0105\u0107 tylko t\u0119 akcj\u0119${entry?.task ? `: \u201e${entry.task}\u201d` : ''}? Pozosta\u0142a historia zostanie bez zmian.`);
    if (!confirmed) return;
    button.disabled = true;
    const error = document.getElementById('cleaning-day-dialog-error');
    try {
      await deleteCleaningAction(button.dataset.actionId, getActiveCleaningApartmentId());
      const history = await refreshCleaningActionHistory(getActiveCleaningApartmentId());
      renderTodayLog(history);
      renderHistoryPanel(history);
      renderOpenHistoryDialog();
      window.dispatchEvent(new CustomEvent('cleaning-action:removed'));
    } catch (deleteError) {
      if (error) {
        error.textContent = deleteError?.message || 'Nie uda\u0142o si\u0119 usun\u0105\u0107 akcji.';
        error.hidden = false;
      }
      button.disabled = false;
    }
  });
  HISTORY_DIALOG_WIRED = true;
}

function renderTodayLog(historyEvents = []) {
  const list = document.getElementById('today-log-list');
  if (!list) return;
  const empty = document.getElementById('today-log-empty');
  const count = document.getElementById('today-log-count');
  const today = new Date();

  const taskByRow = new Map();
  for (const task of DATA) {
    const row = taskRowId(task);
    if (row == null) continue;
    taskByRow.set(row, task);
  }

  const fromHistory = getCleaningActionsForDay(historyEvents, today)
    .map((entry) => {
      const row = Number.isFinite(Number(entry.row)) ? Number(entry.row) : null;
      const fallbackTask = row != null ? taskByRow.get(row) : null;
      const dt = parseDateMaybe(entry.at);
      return {
        title: entry.task || fallbackTask?.task || '-',
        room: entry.room || fallbackTask?.room || '',
        timeLabel: dt ? fmtTimeShort(dt) : 'dziś',
        ts: dt?.getTime?.() || 0,
      };
    })
    .sort((a, b) => b.ts - a.ts);

  let items = fromHistory;

  if (!items.length) {
    items = DATA
      .map((t) => ({ t, dt: parseDateMaybe(t.lastDone) }))
      .filter(({ dt }) => dt && isSameDay(dt, today))
      .sort((a, b) => (b.dt?.getTime?.() || 0) - (a.dt?.getTime?.() || 0))
      .map(({ t, dt }) => ({
        title: t.task || '-',
        room: t.room || '',
        timeLabel: hasTimeInfo(t.lastDone) && dt ? fmtTimeShort(dt) : 'dziś',
        ts: dt?.getTime?.() || 0,
      }));
  }

  list.innerHTML = items.map((item) => {
    const metaParts = [];
    if (item.room) metaParts.push(item.room);
    if (item.timeLabel) metaParts.push(item.timeLabel);
    const meta = metaParts.join(' | ');
    return `
      <div class="today-log-item">
        <span class="today-log-dot" aria-hidden="true"></span>
        <span class="today-log-task">${item.title}</span>
        <span class="today-log-meta">${meta}</span>
      </div>
    `;
  }).join('');

  const hasAny = items.length > 0;
  list.hidden = !hasAny;
  if (empty) empty.hidden = hasAny;
  if (count) {
    const plannedCount = Number(
      buildCleaningForecastSeries(DATA, {
        range: 'week', now: today, historyEvents,
        planStart: getCleaningForecastRampStart(DATA, today),
      })
        .find((day) => day.isToday)?.count || 0,
    );
    count.textContent = `${items.length}/${plannedCount}`;
    count.title = 'Zrobione / zaplanowane na dziś';
    count.setAttribute('aria-label', `Zrobione ${items.length} z ${plannedCount} zaplanowanych na dziś`);
  }
}

function ensureHistoryRangeButtons(panel) {
  const wrap = panel?.querySelector('.history-range');
  if (!wrap) return;
  const existing = new Set(
    [...wrap.querySelectorAll('.history-range-btn[data-range]')].map((button) => button.dataset.range)
  );

  for (const option of HISTORY_RANGE_OPTIONS) {
    if (existing.has(option.key)) continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-range-btn';
    button.dataset.range = option.key;
    button.setAttribute('aria-pressed', 'false');
    button.textContent = option.label;
    wrap.appendChild(button);
  }
}

const updateHistoryRangeButtons = (panel) => {
  panel.querySelectorAll('.history-range-btn[data-range]').forEach((button) => {
    const active = button.dataset.range === HISTORY_RANGE;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
};

function wireHistoryControls() {
  if (HISTORY_WIRED) return;
  const panel = document.getElementById('cleaning-history');
  if (!panel) return;
  ensureHistoryRangeButtons(panel);
  wireHistoryDialog();

  panel.addEventListener('click', (event) => {
    const rangeButton = event.target.closest('.history-range-btn[data-range]');
    if (rangeButton) {
      const next = rangeButton.dataset.range || 'week';
      if (next === HISTORY_RANGE) return;
      HISTORY_RANGE = next;
      HISTORY_OFFSET = 0;
      renderHistoryPanel(getCleaningActionHistory());
      return;
    }

    const historyBar = event.target.closest('.history-bar[data-history-key]');
    if (historyBar) {
      openHistoryDialog(historyBar.dataset.historyKey, historyBar.dataset.historyScope || 'day');
      return;
    }

    const navButton = event.target.closest('.history-nav-btn[data-direction]');
    if (!navButton) return;
    HISTORY_OFFSET += navButton.dataset.direction === 'next' ? 1 : -1;
    renderHistoryPanel(getCleaningActionHistory());
  });

  panel.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const historyBar = event.target.closest('.history-bar[data-history-key]');
    if (!historyBar) return;
    event.preventDefault();
    openHistoryDialog(historyBar.dataset.historyKey, historyBar.dataset.historyScope || 'day');
  });

  HISTORY_WIRED = true;
}

function renderHistoryPanel(historyEvents = []) {
  const panel = document.getElementById('cleaning-history');
  if (!panel) return;
  wireHistoryControls();

  const chart = document.getElementById('history-chart');
  const stats = document.getElementById('history-stats');
  const badge = document.getElementById('history-total-badge');
  const empty = document.getElementById('history-empty');
  const windowLabel = document.getElementById('history-window-label');
  if (!chart || !stats || !badge || !empty || !windowLabel) return;

  ensureHistoryRangeButtons(panel);

  const windowMeta = buildCleaningHistoryWindow({ range: HISTORY_RANGE, offset: HISTORY_OFFSET });
  let series = buildCleaningHistorySeries(historyEvents, { range: HISTORY_RANGE, offset: HISTORY_OFFSET });
  let targetSeries = windowMeta.isPast
    ? []
    : buildCleaningForecastSeries(DATA, {
      range: HISTORY_RANGE, offset: HISTORY_OFFSET, historyEvents,
      planStart: getCleaningForecastRampStart(DATA),
    });
  const isYearSummary = HISTORY_RANGE === 'year';
  if (isYearSummary) {
    series = aggregateCleaningSeriesByMonth(series);
    targetSeries = aggregateCleaningSeriesByMonth(targetSeries);
  }

  const displaySeries = windowMeta.isFuture ? targetSeries : series;
  const historySummary = summarizeCleaningHistory(historyEvents);
  const seriesSummary = summarizeCleaningForecastSeries(series);
  const targetSummary = summarizeCleaningForecastSeries(targetSeries);
  const maxCount = Math.max(
    1,
    ...series.map((day) => Number(day.count) || 0),
    ...targetSeries.map((day) => Number(day.count) || 0),
  );
  const hasAnyHistory = Array.isArray(historyEvents) && historyEvents.length > 0;
  const selectedRangeLabel = HISTORY_RANGE_OPTIONS.find((option) => option.key === HISTORY_RANGE)?.label || 'Tydzień';
  const selectedRangeLabelLower = selectedRangeLabel.toLocaleLowerCase('pl-PL');
  const isCalendarMonth = HISTORY_RANGE === 'month';
  const isStretched = !isCalendarMonth && displaySeries.length <= 14;
  const averageLabel = isYearSummary ? 'Średnio / miesiąc' : 'Średnio / dzień';
  const activeLabel = isYearSummary ? 'Aktywne miesiące' : 'Aktywne dni';
  const maxLabel = isYearSummary
    ? (windowMeta.isFuture ? 'Najcięższy miesiąc' : 'Najlepszy miesiąc')
    : (windowMeta.isFuture ? 'Najcięższy dzień' : 'Najlepszy dzien');
  const currentLabel = isYearSummary ? 'Ten miesiąc' : 'Dzisiaj';
  const targetByDay = new Map(targetSeries.map((day) => [day.dayKey, Number(day.count) || 0]));
  const overdueNow = DATA.filter((task) => !task?.blocked && !!task?.overdue).length;
  const dueNow = DATA.filter((task) => isDue(task)).length;

  updateHistoryRangeButtons(panel);
  windowLabel.textContent = getHistoryWindowLabel(windowMeta);
  badge.textContent = windowMeta.isFuture
    ? `${actionLabel(targetSummary.total)} · plan / ${selectedRangeLabelLower}`
    : `${actionLabel(seriesSummary.total)} / ${selectedRangeLabelLower}`;
  chart.classList.toggle('is-calendar-month', isCalendarMonth);
  chart.classList.toggle('is-stretched', isStretched);
  if (isStretched) {
    chart.style.setProperty('--history-columns', String(displaySeries.length));
  } else {
    chart.style.removeProperty('--history-columns');
  }

  const barItems = displaySeries.map((day) => renderCleaningHistoryBar(day, {
    isForecast: windowMeta.isFuture,
    maxCount,
    fillCount: windowMeta.isFuture ? 0 : (Number(day.count) || 0),
    targetCount: windowMeta.isFuture
      ? (Number(day.count) || 0)
      : (targetByDay.get(day.dayKey) || 0),
    showValue: !windowMeta.isFuture,
    labelParts: isYearSummary ? monthSummaryLabelParts(day.date) : undefined,
    scope: isYearSummary ? 'month' : 'day',
  }));

  chart.innerHTML = isCalendarMonth
    ? buildHistoryCalendarMonthMarkup(windowMeta.startDate, barItems)
    : barItems.join('');

  if (windowMeta.isFuture) {
    const maxDayLabel = targetSummary.maxDay
      ? `${actionLabel(targetSummary.maxDay.count)} (${isYearSummary ? monthSummaryTitle(targetSummary.maxDay.date, false) : dayLabelFull(parseDateMaybe(targetSummary.maxDay.date))})`
      : '-';
    const topRoomLabel = targetSummary.topRoom
      ? `${targetSummary.topRoom.label} (${targetSummary.topRoom.count})`
      : '-';
    const topTaskLabel = targetSummary.topTask
      ? `${targetSummary.topTask.label} (${targetSummary.topTask.count})`
      : '-';

    stats.innerHTML = `
      <article class="history-stat">
        <div class="history-stat-label">Do zrobienia</div>
        <div class="history-stat-value">${formatStatValue(targetSummary.total, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">${averageLabel}</div>
        <div class="history-stat-value">${formatStatValue(targetSummary.avgPerDay, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">${activeLabel}</div>
        <div class="history-stat-value">${formatStatValue(targetSummary.activeDays, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">${maxLabel}</div>
        <div class="history-stat-value">${maxDayLabel}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">Top pokój</div>
        <div class="history-stat-value">${topRoomLabel}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">Top zadanie</div>
        <div class="history-stat-value">${topTaskLabel}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">Zaległe teraz</div>
        <div class="history-stat-value">${formatStatValue(overdueNow, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">Due dziś</div>
        <div class="history-stat-value">${formatStatValue(dueNow, '0')}</div>
      </article>
    `;
  } else {
    const currentBucket = isYearSummary
      ? (series.find((day) => day.isToday)?.count || 0)
      : historySummary.today;
    const bestDayLabel = seriesSummary.maxDay
      ? `${actionLabel(seriesSummary.maxDay.count)} (${isYearSummary ? monthSummaryTitle(seriesSummary.maxDay.date, false) : dayLabelFull(parseDateMaybe(seriesSummary.maxDay.date))})`
      : '-';
    const topTaskLabel = historySummary.topTask
      ? `${historySummary.topTask.label} (${historySummary.topTask.count})`
      : '-';
    const topRoomLabel = historySummary.topRoom
      ? `${historySummary.topRoom.label} (${historySummary.topRoom.count})`
      : '-';

    stats.innerHTML = `
      <article class="history-stat">
        <div class="history-stat-label">${isYearSummary ? 'W roku' : 'W oknie'}</div>
        <div class="history-stat-value">${formatStatValue(seriesSummary.total, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">${averageLabel}</div>
        <div class="history-stat-value">${formatStatValue(seriesSummary.avgPerDay, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">${activeLabel}</div>
        <div class="history-stat-value">${formatStatValue(seriesSummary.activeDays, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">${maxLabel}</div>
        <div class="history-stat-value">${bestDayLabel}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">${currentLabel}</div>
        <div class="history-stat-value">${formatStatValue(currentBucket, '0')}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">Seria</div>
        <div class="history-stat-value">${formatStatValue(historySummary.streak, '0')} dni</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">Top zadanie (miesiąc)</div>
        <div class="history-stat-value">${topTaskLabel}</div>
      </article>
      <article class="history-stat">
        <div class="history-stat-label">Top pokój (miesiąc)</div>
        <div class="history-stat-value">${topRoomLabel}</div>
      </article>
    `;
  }

  const hasVisibleData = windowMeta.isFuture
    ? targetSummary.total > 0
    : (seriesSummary.total > 0 || targetSummary.total > 0);
  empty.hidden = hasVisibleData;
  if (!hasVisibleData) {
    empty.textContent = windowMeta.isFuture
      ? 'Brak zadań do zaplanowania w tym okresie.'
      : (hasAnyHistory
        ? 'Brak akcji w wybranym okresie.'
        : 'Brak historii akcji. Oznacz zadanie jako zrobione, aby zacząć zbierać timestampy.');
  }
}

export function render(){
  const taskViewMode = getCleaningTaskViewMode();
  document.querySelectorAll('[data-cleaning-view]').forEach((button) => {
    const active = button.dataset.cleaningView === taskViewMode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });

  // KPI
  const m = metrics(DATA);
  document.getElementById('kpi-today').textContent   = m.today;
  document.getElementById('kpi-overdue').textContent = m.ov;
  document.getElementById('kpi-total').textContent   = m.total;
  document.getElementById('kpi-delay').textContent   = `${m.avg}d`;

  const kpiComing = document.getElementById('kpi-coming');
  if (kpiComing) {
    kpiComing.textContent = DATA.filter(isComing).length;
  }

  // Fill selects once
  const roomSel = document.getElementById('room');
  if (roomSel.options.length === 1){
    [...new Set(DATA.map(t=>t.room).filter(Boolean))].sort()
      .forEach(r => {
        const o = document.createElement('option');
        o.value = r;
        o.textContent = r;
        roomSel.appendChild(o);
      });
  }

  const catSel = document.getElementById('category');
  if (catSel && catSel.options.length === 1){
    [...new Set(DATA.map(t=>t.category).filter(Boolean))].sort()
      .forEach(c => {
        const o = document.createElement('option');
        o.value = c;
        o.textContent = c;
        catSel.appendChild(o);
      });
  }

  // 1. normalne filtry UI
  const dueOnly  = document.getElementById('dueOnly')?.checked ?? false;
  const room     = roomSel.value;
  const category = catSel ? catSel.value : 'ALL';
  const sort     = document.getElementById('sort').value;

  let baseList = DATA.slice();

  if (room !== 'ALL'){
    baseList = baseList.filter(t => t.room === room);
  }
  if (category !== 'ALL'){
    baseList = baseList.filter(t => t.category === category);
  }
  if (dueOnly){
    baseList = baseList.filter(t => !t.blocked && (t.overdue || N(t.nextDueIn) === 0));
  }

  // 2. panel Supplies bazuje na baseList (czyli po room/category/dueOnly)
  renderSuppliesBox(baseList);

  // 3. apply SUPPLY_FILTER (Mop etc.)
  let list = baseList.filter(t => taskHasAllSupplies(t, SUPPLY_FILTER));

  // 4. final sorting
  const safeNext = x => (Number.isFinite(N(x)) ? N(x) : 9999);
  const safeSince = x => (Number.isFinite(N(x)) ? N(x) : -1);

  list.sort((a, b) => {
    if (sort === 'room'){
      return (
        (a.room || '').localeCompare(b.room || '', 'pl') ||
        statusRank(a) - statusRank(b) ||
        safeNext(a.nextDueIn) - safeNext(b.nextDueIn) ||
        (a.task || '').localeCompare(b.task || '', 'pl')
      );
    }
    if (sort === 'soonest'){
      return safeNext(a.nextDueIn) - safeNext(b.nextDueIn);
    }
    if (sort === 'since'){
      return (
        safeSince(b.daysSince) - safeSince(a.daysSince) ||
        (a.task || '').localeCompare(b.task || '')
      );
    }
    // default sort: DEAD -> OVERDUE -> DUE -> COMING -> FRESH
    return (
      statusRank(a) - statusRank(b) ||
      safeNext(a.nextDueIn) - safeNext(b.nextDueIn) ||
      (a.task || '').localeCompare(b.task || '')
    );
  });

  const listSignature = JSON.stringify([
    room,
    category,
    sort,
    dueOnly,
    taskViewMode,
    [...SUPPLY_FILTER].sort(),
  ]);
  if (listSignature !== LAST_LIST_SIGNATURE) KEEP_CURRENT_TASK_ORDER = false;
  if (KEEP_CURRENT_TASK_ORDER && listSignature === LAST_LIST_SIGNATURE && LAST_LIST.length) {
    list = preserveTaskOrder(LAST_LIST, list);
  }

  LAST_LIST_SIGNATURE = listSignature;
  LAST_LIST = list;

  // 5. aktualizacja siatki kart
  const grid = document.getElementById('grid');

  // map current DOM nodes
  const existing = new Map(
    [...grid.querySelectorAll('.card[data-key]')].map(el => [el.getAttribute('data-key'), el])
  );

  // keep node references after update/create
  const nodeMap = new Map();
  const nextKeys = new Set();

  for (const t of list){
    const k = keyOf(t);
    nextKeys.add(k);
    const html = cardHTML(t);

    if (existing.has(k)){
      // update existing card
      const el = existing.get(k);
      const tmp = document.createElement('div');
      tmp.innerHTML = html.trim();
      const newEl = tmp.firstElementChild;

      // progress bar
      const oldBar = el.querySelector('.progress > div');
      const newBar = newEl.querySelector('.progress > div');
      if (oldBar && newBar){
        const newWidth = newBar.style.width;
        const newClass = newBar.className;
        oldBar.className = newClass;
        requestAnimationFrame(() => {
          oldBar.style.width = newWidth;
        });
      }

      // title + meta
      el.querySelector('.title').innerHTML =
        newEl.querySelector('.title').innerHTML;
      el.querySelector('.meta').innerHTML  =
        newEl.querySelector('.meta').innerHTML;

      // supplies section (.needs)
      const oldNeeds = el.querySelector('.needs');
      const newNeeds = newEl.querySelector('.needs');

      if (oldNeeds && newNeeds){
        oldNeeds.innerHTML = newNeeds.innerHTML;
      } else if (!oldNeeds && newNeeds){
        const metaEl = el.querySelector('.meta');
        if (metaEl){
          metaEl.insertAdjacentElement('afterend', newNeeds);
        }
      } else if (oldNeeds && !newNeeds){
        oldNeeds.remove();
      }

      // badges
      el.querySelector('.badges').innerHTML =
        newEl.querySelector('.badges').innerHTML;

      const oldFooter = el.querySelector('.footer');
      const newFooter = newEl.querySelector('.footer');
      if (oldFooter && newFooter) oldFooter.innerHTML = newFooter.innerHTML;

      // klasa obramowania
      const cls = t.blocked ? 'blocked' : isDead(t)
        ? 'dead'
        : (t.overdue
            ? 'overdue'
            : (isDue(t)
                ? 'due'
                : (isComing(t)
                    ? 'coming'
                    : '')));

      el.className = `card ${cls}`;

      nodeMap.set(k, el); // store node ref after update

    } else {
      // nowa karta
      const tmp = document.createElement('div');
      tmp.innerHTML = html.trim();
      const el = tmp.firstElementChild;
      el.classList.add('enter');
      requestAnimationFrame(() => el.classList.remove('enter'));

      nodeMap.set(k, el); // store node ref after create
    }
  }

  // 6. remove cards that no longer match filters
  for (const [k, el] of existing.entries()){
    if (!nextKeys.has(k)){
      el.classList.add('leaving');
      el.addEventListener('transitionend', () => el.remove(), { once:true });
      setTimeout(() => {
        const roomGroup = el.closest('.cleaning-room-group');
        el.remove();
        if (roomGroup && !roomGroup.querySelector('.card')) roomGroup.remove();
      }, 400);
    }
  }

  // 7. render the selected flat/room/category view without rebuilding card nodes
  const existingGroups = new Map(
    [...grid.querySelectorAll('.cleaning-room-group')]
      .map((section) => [section.dataset.groupKey || section.dataset.roomKey || '', section])
  );

  if (taskViewMode === 'all') {
    grid.classList.remove('cleaning-room-sections');
    grid.classList.add('cleaning-flat-view');
    for (const task of list) {
      const node = nodeMap.get(keyOf(task));
      if (node) grid.appendChild(node);
    }
    existingGroups.forEach((section) => section.remove());
  } else {
    grid.classList.add('cleaning-room-sections');
    grid.classList.remove('cleaning-flat-view');
    const isCategoryView = taskViewMode === 'category';
    const groups = isCategoryView
      ? groupTasksByCategory(list).map((group) => ({ ...group, label: group.category }))
      : groupTasksByRoom(list).map((group) => ({ ...group, label: group.room }));
    const groupTypeLabel = isCategoryView ? 'Kategoria' : 'Pokój';
    const activeGroupKeys = new Set();

    for (const group of groups) {
      const groupKey = `${taskViewMode}:${encodeURIComponent(group.key)}`;
      activeGroupKeys.add(groupKey);
      let section = existingGroups.get(groupKey);
      if (!section) {
        section = document.createElement('section');
        section.className = 'cleaning-room-group';
        section.innerHTML = `
          <header class="cleaning-room-head">
            <div class="cleaning-room-heading-copy">
              <span class="cleaning-room-kicker"></span>
              <h2 class="cleaning-room-name"></h2>
            </div>
            <span class="cleaning-room-count"></span>
          </header>
          <div class="cleaning-room-progress-row">
            <div class="cleaning-room-progress-track" role="progressbar" aria-valuemin="0">
              <span class="cleaning-room-progress-fill"></span>
            </div>
            <span class="cleaning-room-progress-label"></span>
          </div>
          <div class="cleaning-room-task-grid"></div>
        `;
      }

      section.dataset.groupKey = groupKey;
      delete section.dataset.roomKey;
      section.classList.remove('is-leaving');
      section.setAttribute('aria-label', `${groupTypeLabel}: ${group.label}`);
      section.querySelector('.cleaning-room-kicker').textContent = groupTypeLabel;
      section.querySelector('.cleaning-room-name').textContent = group.label;
      section.querySelector('.cleaning-room-count').textContent = roomTaskCountLabel(group.tasks.length);
      const progress = roomProgress(group.tasks);
      const progressTrack = section.querySelector('.cleaning-room-progress-track');
      progressTrack.setAttribute('aria-label', `Aktualne zadania: ${group.label}`);
      progressTrack.setAttribute('aria-valuemax', String(progress.total));
      progressTrack.setAttribute('aria-valuenow', String(progress.current));
      const progressFill = progressTrack.querySelector('.cleaning-room-progress-fill');
      progressFill.style.width = `${progress.percent}%`;
      progressFill.style.setProperty('--cleaning-group-progress-color', colorForCleaningProgress(progress.percent));
      section.querySelector('.cleaning-room-progress-label').textContent = `${progress.current}/${progress.total} aktualne · ${progress.percent}%`;
      const taskGrid = section.querySelector('.cleaning-room-task-grid');
      for (const task of group.tasks) {
        const node = nodeMap.get(keyOf(task));
        if (node) taskGrid.appendChild(node);
      }
      grid.appendChild(section);
    }

    for (const [groupKey, section] of existingGroups) {
      if (activeGroupKeys.has(groupKey)) continue;
      section.remove();
    }
  }

  const historyEvents = getCleaningActionHistory();
  renderTodayLog(historyEvents);
  renderHistoryPanel(historyEvents);
  window.dispatchEvent(new CustomEvent('cleaning:rendered'));
}
