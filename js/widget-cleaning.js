import { onDomReady } from './dom-ready.js';
import { getTasks, markDone } from './cleaning-api.js';
import { getActiveCleaningApartmentId } from './cleaning-apartments.js';
import {
  buildCleaningForecastSeries,
  buildCleaningHistorySeries,
  CLEANING_HISTORY_CHANGED_EVENT,
  getCleaningActionHistory,
  getCleaningActionsForDay,
  getCleaningDayKey,
  getCleaningDayReference,
  getCleaningForecastDailyCapacity,
  getCleaningForecastRampStart,
  getCleaningRecoveryDayKeys,
  refreshCleaningActionHistory,
} from './cleaning-history.js';
import {
  computeCounts,
  deriveStatus,
  statusOrder,
} from './cleaning-logic.js';
import { fmtTimeShort, isSameDay, parseDateMaybe } from './utils.js';
import { formatCleaningDateWithWeekday } from './cleaning-format.js';
import { colorForCleaningProgress } from './cleaning-progress-color.js';
import { formatLoadedAt, loadTimeSuffix, startLoadTimer } from './load-timing.js';
import { scheduleUndo } from './undo-toast.js';
import { setDailyAchievement } from './daily-achievements.js';
import { publishCleaningGoal } from './phone-cleaning-gate.js';
import { DASHBOARD_WIDGETS_CHANGED_EVENT, loadDashboardWidgetConfig } from './dashboard-settings.js';
import { TODO_STORE_CHANGED_EVENT, listTodos } from './todo-store.js';
import { isMopPurchasePending } from './cleaning-dependencies.js';

const $ = (selector) => document.querySelector(selector);

const hasTimeInfo = (value) => {
  if (value == null || value === '') return false;
  if (value instanceof Date) return true;
  if (typeof value === 'number') return true;
  if (typeof value === 'string') return /\d:\d/.test(value);
  return false;
};

const escapeHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const MAX_WIDGET_TASKS = 6;
const CLEANING_DAY_ROLLOVER_HOUR = 6;
const DAILY_GOAL_TARGET_STORAGE_KEY = 'cleaningDashboard.dailyGoalTarget.v2';
const DAILY_GOAL_PLAN_VERSION = 2;
const LEGACY_DAILY_GOAL_TARGET_STORAGE_KEY = 'cleaningDashboard.dailyGoalTarget.v1';
const DAILY_DASHBOARD_UNLOCK_STORAGE_KEY = 'cleaningDashboard.dailyUnlock.v1';
let pendingWidgetTaskId = null;
const sessionDoneTasks = new Map();
const sessionTaskOrder = new Map();
let nextSessionTaskOrder = 0;
let dashboardCleaningLocked = false;
let cleaningLockEnabled = false;
let dailyGoalTargetSnapshot = null;
let dailyDashboardUnlockSnapshot = null;
let todayRecoveryDay = false;

const setLockTargetInert = (element, locked) => {
  if (!(element instanceof HTMLElement)) return;
  if (locked) {
    if (!element.hasAttribute('inert')) {
      element.dataset.cleaningLockOwnedInert = 'true';
      element.setAttribute('inert', '');
    }
    if (!element.hasAttribute('aria-disabled')) {
      element.dataset.cleaningLockOwnedAriaDisabled = 'true';
      element.setAttribute('aria-disabled', 'true');
    }
    return;
  }
  if (element.dataset.cleaningLockOwnedInert === 'true') {
    element.removeAttribute('inert');
    delete element.dataset.cleaningLockOwnedInert;
  }
  if (element.dataset.cleaningLockOwnedAriaDisabled === 'true') {
    element.removeAttribute('aria-disabled');
    delete element.dataset.cleaningLockOwnedAriaDisabled;
  }
};

function setDashboardCleaningLock(locked) {
  const nextLocked = locked === true;
  const changed = dashboardCleaningLocked !== nextLocked;
  dashboardCleaningLocked = nextLocked;

  const dash = document.querySelector('.dash');
  document.body?.classList.toggle('is-cleaning-locked', nextLocked);
  if (dash instanceof HTMLElement) {
    dash.dataset.cleaningLocked = nextLocked ? 'true' : 'false';
    [...dash.children]
      .filter((card) => card.matches('.card:not(#cleaning-card)'))
      .forEach((card) => setLockTargetInert(card, nextLocked));
  }

  [
    document.querySelector('.dashboard-side-shortcuts'),
    document.getElementById('dashboard-event-notifications-trigger'),
    document.querySelector('.dashboard-screensaver-link'),
    document.querySelector('.daily-achievements'),
  ].forEach((element) => setLockTargetInert(element, nextLocked));

  const message = document.getElementById('cl-dashboard-lock-message');
  if (message) message.hidden = !nextLocked;

  if (changed) {
    window.dispatchEvent(new CustomEvent('dashboard:cleaning-lock-changed', {
      detail: { locked: nextLocked },
    }));
  }
  return changed;
}

const syncWidgetPendingButtons = (widget) => {
  widget?.querySelectorAll('.cl-btn[data-row]').forEach((button) => {
    const pending = Number(button.dataset.row || 0) === pendingWidgetTaskId;
    button.disabled = button.classList.contains('done') || pendingWidgetTaskId !== null;
    button.classList.toggle('is-pending', pending);
    button.classList.toggle('is-click-locked', pendingWidgetTaskId !== null && !pending);
    button.setAttribute('aria-busy', pending ? 'true' : 'false');
  });
};
const CATEGORY_PRIORITY = [
  'łóżko',
  'śmieci',
  'przetarcie kurzu',
  'organizacja',
  'odkurzanie',
  'inne',
];

const normalizeCategory = (value) => {
  if (!value) return '';
  return String(value)
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\u0142/g, 'l');
};

const CATEGORY_PRIORITY_NORM = CATEGORY_PRIORITY.map(normalizeCategory);
const ROOM_FALLBACK_LABEL = 'Bez pokoju';
const roomCollator = new Intl.Collator('pl', { sensitivity: 'base', numeric: true });

const roomLabel = (task) => String(task?.room || '').trim() || ROOM_FALLBACK_LABEL;

const compareLockedTasks = (a, b) => {
  const aHasRoom = a._roomLabel !== ROOM_FALLBACK_LABEL;
  const bHasRoom = b._roomLabel !== ROOM_FALLBACK_LABEL;
  if (aHasRoom !== bHasRoom) return aHasRoom ? -1 : 1;

  const roomDiff = roomCollator.compare(a._roomLabel, b._roomLabel);
  if (roomDiff !== 0) return roomDiff;

  const statusDiff = statusOrder[a._status] - statusOrder[b._status];
  if (statusDiff !== 0) return statusDiff;
  return roomCollator.compare(a.task || '', b.task || '');
};

const categoryRank = (task) => {
  const cat = normalizeCategory(task.category);
  if (!cat) return Number.POSITIVE_INFINITY;
  const idx = CATEGORY_PRIORITY_NORM.findIndex((key) => cat.includes(key));
  return idx === -1 ? Number.POSITIVE_INFINITY : idx;
};

let widgetTasks = [];
let lastLoadMs = null;
let lastLoadedAt = null;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

function getTodayForecast(tasks, historyEvents, today = new Date()) {
  const day = cleaningDayReference(today);
  return buildCleaningForecastSeries(tasks, {
    range: 'week', now: day, historyEvents,
    planStart: getCleaningForecastRampStart(tasks, day),
  })
    .find((day) => day.isToday) || { count: 0, tasks: [] };
}

function getTodayGoalTarget(tasks, completedItems = [], historyEvents = [], today = new Date()) {
  const forecast = getTodayForecast(tasks, historyEvents, today);
  const plannedRows = new Map();

  for (const task of forecast.tasks || []) {
    const row = Number(task.row);
    if (!Number.isFinite(row) || row <= 0) continue;
    plannedRows.set(row, (plannedRows.get(row) || 0) + Math.max(1, Number(task.count) || 1));
  }

  let completedOutsideCurrentPlan = 0;
  for (const item of completedItems) {
    const row = Number(item.row);
    const plannedCount = Number.isFinite(row) ? (plannedRows.get(row) || 0) : 0;
    if (plannedCount > 0) {
      plannedRows.set(row, plannedCount - 1);
    } else {
      completedOutsideCurrentPlan += 1;
    }
  }

  const day = cleaningDayReference(today);
  const capacity = getCleaningForecastDailyCapacity(tasks, day, {
    planStart: getCleaningForecastRampStart(tasks, day), historyEvents,
  });
  return Math.min(capacity, Math.max(0, Number(forecast.count) || 0) + completedOutsideCurrentPlan);
}

const cleaningDayOptions = { rolloverHour: CLEANING_DAY_ROLLOVER_HOUR };
const cleaningDayReference = (value = new Date()) => getCleaningDayReference(value, cleaningDayOptions);
const localDayKey = (value) => getCleaningDayKey(value, cleaningDayOptions);

const dailySnapshotKey = (date) => `${getActiveCleaningApartmentId()}:${localDayKey(date)}`;

function isDashboardUnlockedForDay(today = new Date()) {
  const key = dailySnapshotKey(today);
  if (dailyDashboardUnlockSnapshot?.key === key) {
    return dailyDashboardUnlockSnapshot.unlocked === true;
  }

  try {
    const stored = JSON.parse(window.localStorage.getItem(DAILY_DASHBOARD_UNLOCK_STORAGE_KEY) || 'null');
    if (stored?.key === key && stored?.unlocked === true) {
      dailyDashboardUnlockSnapshot = { key, unlocked: true };
      return true;
    }
  } catch {
    // A blocked localStorage keeps the explicit unlock scoped to this page view.
  }

  dailyDashboardUnlockSnapshot = { key, unlocked: false };
  return false;
}

function setDashboardUnlockedForDay(unlocked, today = new Date()) {
  const key = dailySnapshotKey(today);
  dailyDashboardUnlockSnapshot = { key, unlocked: unlocked === true };
  try {
    if (unlocked) {
      window.localStorage.setItem(
        DAILY_DASHBOARD_UNLOCK_STORAGE_KEY,
        JSON.stringify(dailyDashboardUnlockSnapshot),
      );
    } else {
      window.localStorage.removeItem(DAILY_DASHBOARD_UNLOCK_STORAGE_KEY);
    }
  } catch {
    // The in-memory state is sufficient until the page is closed.
  }
}

const restoredTaskBeforeAction = (task, action) => {
  const status = String(action?.status || '').trim().toUpperCase();
  if (!['DEAD', 'OVERDUE', 'DUE'].includes(status)) return null;

  const freq = Math.max(1, Number(task?.freq) || 1);
  const overdue = status === 'DEAD' || status === 'OVERDUE';
  const daysSince = status === 'DEAD'
    ? freq + 8
    : status === 'OVERDUE'
      ? freq + 1
      : freq;
  return {
    ...task,
    overdue,
    daysSince,
    nextDueIn: overdue ? -1 : 0,
  };
};

function targetAfterFirstCompletedAction(tasks, historyEvents, today) {
  const actions = getCleaningActionsForDay(historyEvents, today, {
    rolloverHour: CLEANING_DAY_ROLLOVER_HOUR,
  });
  const firstAction = actions.at(-1);
  const firstRow = Number(firstAction?.row);
  if (!Number.isFinite(firstRow)) return null;

  let tasksAfterFirst = [...tasks];
  let restoredCount = 0;
  for (const action of actions.slice(0, -1)) {
    const actionRow = Number(action.row);
    tasksAfterFirst = tasksAfterFirst.map((task) => {
      const row = Number(task.row ?? task.row_id);
      if (row !== actionRow) return task;
      const previousTask = restoredTaskBeforeAction(task, action);
      if (!previousTask) return task;
      restoredCount += 1;
      return previousTask;
    });
  }
  if (actions.length > 1 && restoredCount === 0) return null;

  return getTodayGoalTarget(tasksAfterFirst, [{ row: firstRow }], historyEvents, today);
}

function getStableTodayGoalTarget(tasks, completedItems, historyEvents, today = new Date()) {
  const snapshotKey = dailySnapshotKey(today);
  if (getCleaningRecoveryDayKeys(historyEvents).has(localDayKey(today))) {
    dailyGoalTargetSnapshot = { key: snapshotKey, target: 1, planVersion: DAILY_GOAL_PLAN_VERSION };
    try {
      window.localStorage.setItem(DAILY_GOAL_TARGET_STORAGE_KEY, JSON.stringify(dailyGoalTargetSnapshot));
    } catch {}
    return 1;
  }
  if (dailyGoalTargetSnapshot?.key === snapshotKey) return dailyGoalTargetSnapshot.target;

  try {
    const stored = JSON.parse(window.localStorage.getItem(DAILY_GOAL_TARGET_STORAGE_KEY) || 'null');
    const storedTarget = Number(stored?.target);
    if (
      stored?.key === snapshotKey
      && stored?.planVersion === DAILY_GOAL_PLAN_VERSION
      && Number.isFinite(storedTarget)
      && storedTarget >= 0
    ) {
      dailyGoalTargetSnapshot = { key: snapshotKey, target: Math.min(10, Math.trunc(storedTarget)), planVersion: DAILY_GOAL_PLAN_VERSION };
      return dailyGoalTargetSnapshot.target;
    }
  } catch {
    // A blocked localStorage must not block the Cleaning widget.
  }

  const previousTarget = targetAfterFirstCompletedAction(tasks, historyEvents, today);
  const computedTarget = previousTarget ?? getTodayGoalTarget(tasks, completedItems, historyEvents, today);
  const target = Math.min(10, Math.max(0, Math.trunc(Number(computedTarget) || 0)));
  dailyGoalTargetSnapshot = { key: snapshotKey, target, planVersion: DAILY_GOAL_PLAN_VERSION };
  try {
    window.localStorage.setItem(
      DAILY_GOAL_TARGET_STORAGE_KEY,
      JSON.stringify(dailyGoalTargetSnapshot),
    );
    window.localStorage.removeItem(LEGACY_DAILY_GOAL_TARGET_STORAGE_KEY);
  } catch {
    // The in-memory snapshot still keeps the target stable for this page view.
  }
  return target;
}

function buildTodayLogItems(tasks, historyEvents = getCleaningActionHistory(), today = new Date()) {
  const taskByRow = new Map();
  for (const task of tasks) {
    const row = Number(task.row ?? task.row_id);
    if (!Number.isFinite(row) || row <= 0) continue;
    taskByRow.set(row, task);
  }

  const fromHistory = getCleaningActionsForDay(historyEvents, today, {
    rolloverHour: CLEANING_DAY_ROLLOVER_HOUR,
  })
    .map((entry) => {
      const row = Number(entry.row);
      const fallbackTask = Number.isFinite(row) ? taskByRow.get(row) : null;
      const dt = parseDateMaybe(entry.at);
      return {
        row: Number.isFinite(row) ? row : null,
        title: entry.task || fallbackTask?.task || '-',
        room: entry.room || fallbackTask?.room || '',
        timeLabel: dt ? fmtTimeShort(dt) : 'dziś',
        ts: dt?.getTime?.() || 0,
      };
    })
    .sort((a, b) => b.ts - a.ts);

  const items = fromHistory.length
    ? fromHistory
    : tasks
      .map((task) => ({ task, dt: parseDateMaybe(task.lastDone) }))
      .filter(({ dt }) => dt && isSameDay(cleaningDayReference(dt), cleaningDayReference(today)))
      .sort((a, b) => (b.dt?.getTime?.() || 0) - (a.dt?.getTime?.() || 0))
      .map(({ task, dt }) => ({
        row: Number(task.row ?? task.row_id) || null,
        title: task.task || '-',
        room: task.room || '',
        timeLabel: hasTimeInfo(task.lastDone) && dt ? fmtTimeShort(dt) : 'dziś',
        ts: dt?.getTime?.() || 0,
      }));

  const existingRows = new Set(items.map((item) => Number(item.row)).filter(Number.isFinite));
  for (const [row, item] of sessionDoneTasks) {
    if (!existingRows.has(row)) items.push(item);
  }

  return items.sort((a, b) => b.ts - a.ts);
}

function polishCleaningDayCount(days) {
  const value = Math.max(0, Math.round(Number(days) || 0));
  return value === 1 ? '1 dzień serii' : `${value} dni serii`;
}

function polishCleaningTaskUnit(tasks) {
  const value = Math.max(0, Math.round(Number(tasks) || 0));
  if (value === 1) return 'zadanie';
  const lastTwo = value % 100;
  const last = value % 10;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return 'zadania';
  return 'zadań';
}

function cleaningWeekdayLabel(dateValue) {
  const date = new Date(dateValue);
  if (!Number.isFinite(date.getTime())) return '—';
  return date.toLocaleDateString('pl-PL', { weekday: 'narrow' }).replace('.', '');
}

function currentCleaningStreak(days) {
  let streak = 0;
  for (let index = days.length - 1; index >= 0; index -= 1) {
    if ((Number(days[index]?.count) || 0) <= 0) break;
    streak += 1;
  }
  return streak;
}

function renderCleaningWeek(days, dailyGoal) {
  const week = $('#cl-week');
  if (!(week instanceof HTMLElement)) return;
  const fragment = document.createDocumentFragment();

  days.forEach((day) => {
    const actions = Math.max(0, Math.round(Number(day?.count) || 0));
    const isToday = day?.isToday === true;
    const hasActions = actions > 0;
    const isGoalComplete = dailyGoal > 0 && actions >= dailyGoal;
    const date = new Date(day?.date);
    const dayName = Number.isFinite(date.getTime())
      ? formatCleaningDateWithWeekday(date, 'long')
      : 'Dzień';

    const item = document.createElement('div');
    item.className = 'cleaning-week-day';
    item.classList.toggle('is-today', isToday);
    item.classList.toggle('has-actions', hasActions);
    item.classList.toggle('is-goal-complete', isGoalComplete);
    item.setAttribute('aria-label', `${dayName}: ${actions} ${polishCleaningTaskUnit(actions)}`);

    const label = document.createElement('span');
    label.className = 'cleaning-week-label';
    label.textContent = cleaningWeekdayLabel(day?.date);

    const dot = document.createElement('span');
    dot.className = 'cleaning-week-dot';
    dot.setAttribute('aria-hidden', 'true');
    dot.textContent = hasActions ? '✓' : '';

    const count = document.createElement('span');
    count.className = 'cleaning-week-actions';
    count.textContent = String(actions);

    item.append(label, dot, count);
    fragment.append(item);
  });

  week.replaceChildren(fragment);
}

function updateGoalState(tasks) {
  const card = document.getElementById('cleaning-card') || document.querySelector('.card.cleaning');
  if (!(card instanceof HTMLElement)) return;

  const now = new Date();
  const historyEvents = getCleaningActionHistory();
  const todayItems = buildTodayLogItems(tasks, historyEvents, now);
  const todayTarget = getStableTodayGoalTarget(tasks, todayItems, historyEvents, now);
  const todayDone = todayItems.length;
  const isDailyGoalReached = todayTarget > 0 && todayDone >= todayTarget;
  if (document.getElementById('phone-activity-card')) {
    publishCleaningGoal(getActiveCleaningApartmentId(),todayTarget,todayDone).catch(() => {});
  }
  let manuallyUnlocked = isDashboardUnlockedForDay(now);
  if (!isDailyGoalReached && manuallyUnlocked) {
    setDashboardUnlockedForDay(false, now);
    manuallyUnlocked = false;
  }
  const shouldLockDashboard = cleaningLockEnabled && todayTarget > 0 && (!isDailyGoalReached || (!manuallyUnlocked && !todayRecoveryDay));
  const lockChanged = setDashboardCleaningLock(shouldLockDashboard);
  const lockMessage = document.getElementById('cl-dashboard-lock-message');
  const lockText = document.getElementById('cl-dashboard-lock-text');
  const unlockButton = document.getElementById('cl-dashboard-unlock');
  if (lockMessage) {
    lockMessage.hidden = !shouldLockDashboard;
    lockMessage.classList.toggle('is-ready-to-unlock', shouldLockDashboard && isDailyGoalReached);
  }
  if (lockText) {
    lockText.textContent = isDailyGoalReached
      ? 'Dzisiejszy cel osiągnięty. Możesz sprzątać dalej albo świadomie zakończyć tryb.'
      : 'Dashboard jest zablokowany do ukończenia dzisiejszego celu sprzątania.';
  }
  if (unlockButton) unlockButton.hidden = !(shouldLockDashboard && isDailyGoalReached);
  const goalProgress = todayTarget > 0
    ? clamp(Math.round((todayDone / todayTarget) * 100), 0, 100)
    : 0;
  const recentDays = buildCleaningHistorySeries(historyEvents, { days: 7, now: cleaningDayReference(now) })
    .map((day) => (day.isToday && todayDone > day.count
      ? { ...day, count: todayDone }
      : day));
  const weekTotal = recentDays.reduce((sum, day) => sum + (Number(day?.count) || 0), 0);
  const weekAverage = Math.round((weekTotal / 7) * 10) / 10;

  card.classList.toggle('is-goal-complete', isDailyGoalReached);
  setDailyAchievement('cleaning', todayTarget > 0 ? {
    state: isDailyGoalReached ? 'complete' : 'pending',
    value: isDailyGoalReached
      ? `${todayDone} ${polishCleaningTaskUnit(todayDone)}`
      : `${todayDone}/${todayTarget}`,
    detail: isDailyGoalReached ? 'Wszystkie zadania na dziś' : `${Math.max(0, todayTarget - todayDone)} zostało`,
    progress: (todayDone / todayTarget) * 100,
  } : {
    state: 'neutral',
    value: 'Brak planu',
    detail: 'Bez zadań na dzisiaj',
    eligible: false,
  });

  const goalValue = $('#cl-goal-progress');
  if (goalValue) {
    goalValue.textContent = `${todayDone}/${todayTarget} zadań`;
  }

  const ring = $('#cl-goal-ring');
  if (ring instanceof HTMLElement) {
    ring.style.setProperty('--cleaning-goal-progress', `${goalProgress * 3.6}deg`);
    ring.classList.toggle('is-complete', isDailyGoalReached);
    ring.setAttribute('aria-valuemax', String(todayTarget));
    ring.setAttribute('aria-valuenow', String(Math.min(todayDone, todayTarget)));
  }

  const ringValue = $('#cl-goal-ring-value');
  if (ringValue) ringValue.textContent = isDailyGoalReached ? '✓' : `${goalProgress}%`;

  const streak = $('#cl-streak');
  if (streak) streak.textContent = polishCleaningDayCount(currentCleaningStreak(recentDays));

  const average = $('#cl-average');
  if (average) {
    average.textContent = `${weekAverage.toLocaleString('pl-PL', { maximumFractionDigits: 1 })} zadań/dzień`;
  }

  renderCleaningWeek(recentDays, todayTarget);
  if (lockChanged) renderList(tasks);
}

function renderFooter(status = 'ok') {
  const footer = $('#cl-updated');
  if (!footer) return;
  const loaded = lastLoadedAt ? formatLoadedAt(lastLoadedAt) : '—';
  const load = loadTimeSuffix(lastLoadMs);
  const prefix = status === 'error' ? 'Błąd synchronizacji' : 'Ostatnia synchronizacja';
  footer.textContent = `${prefix}: ${loaded}${load ? ` · ${load}` : ''}`;
}

function applyTasks(tasks) {
  widgetTasks = Array.isArray(tasks) ? tasks : [];
  todayRecoveryDay = getCleaningRecoveryDayKeys(getCleaningActionHistory()).has(localDayKey(new Date()));
  updateCounters(widgetTasks);
  renderList(widgetTasks);
  renderTodayLog(widgetTasks);
  updateGoalState(widgetTasks);
}

function renderList(tasks) {
  const box = $('#cl-list');
  if (!box) return;
  if (todayRecoveryDay && !dashboardCleaningLocked) {
    box.replaceChildren();
    return;
  }
  const plannedRows = dashboardCleaningLocked
    ? new Set(getTodayForecast(tasks, getCleaningActionHistory()).tasks
      .map((task) => Number(task.row)).filter(Number.isFinite))
    : null;

  const wanted = tasks
    .map((task) => {
      const row = Number(task.row ?? task.row_id);
      return {
        ...task,
        _status: deriveStatus(task),
        _sessionDone: sessionDoneTasks.has(row),
        _roomLabel: roomLabel(task),
      };
    })
    .filter((task) => {
      if (task._sessionDone) return true;
      if (dashboardCleaningLocked) {
        return plannedRows.has(Number(task.row ?? task.row_id))
          && ['DEAD', 'OVERDUE', 'DUE'].includes(task._status);
      }
      return ['DEAD', 'OVERDUE', 'DUE', 'COMING'].includes(task._status);
    })
    .sort((a, b) => {
      if (dashboardCleaningLocked) return compareLockedTasks(a, b);
      const catDiff = categoryRank(a) - categoryRank(b);
      if (catDiff !== 0) return catDiff;
      const statusDiff = statusOrder[a._status] - statusOrder[b._status];
      if (statusDiff !== 0) return statusDiff;
      return (a.task || '').localeCompare(b.task || '');
    });

  if (dashboardCleaningLocked && sessionDoneTasks.size === 0) {
    sessionTaskOrder.clear();
    nextSessionTaskOrder = 0;
  }
  for (const task of wanted) {
    const row = Number(task.row ?? task.row_id);
    if (!sessionTaskOrder.has(row)) sessionTaskOrder.set(row, nextSessionTaskOrder++);
  }
  if (sessionDoneTasks.size > 0) {
    wanted.sort((a, b) => (
      sessionTaskOrder.get(Number(a.row ?? a.row_id))
      - sessionTaskOrder.get(Number(b.row ?? b.row_id))
    ));
  }

  const visibleTasks = dashboardCleaningLocked
    ? wanted
    : wanted.slice(0, MAX_WIDGET_TASKS + sessionDoneTasks.size);

  const renderTask = (task) => `
    <div class="cl-item${task._sessionDone ? ' is-done' : ''}">
      <div class="title">${escapeHtml(task.task || '-')}</div>
      <button class="cl-btn ${task._sessionDone ? 'done' : task._status.toLowerCase()}" data-row="${task.row ?? task.row_id}"${task._sessionDone ? ' disabled' : ''}>
        ${task._sessionDone ? 'DONE' : task._status}
      </button>
    </div>
  `;

  box.classList.toggle('is-room-grouped', dashboardCleaningLocked);
  if (!dashboardCleaningLocked) {
    box.innerHTML = visibleTasks.map(renderTask).join('');
    return;
  }

  const roomGroups = new Map();
  for (const task of visibleTasks) {
    const group = roomGroups.get(task._roomLabel) || [];
    group.push(task);
    roomGroups.set(task._roomLabel, group);
  }
  box.innerHTML = [...roomGroups.entries()].map(([room, roomTasks]) => `
    <section class="cl-room-group" aria-label="${escapeHtml(room)}">
      <div class="cl-room-heading">
        <span class="cl-room-name">${escapeHtml(room)}</span>
        <span class="cl-room-count">${roomTasks.length}</span>
      </div>
      <div class="cl-room-tasks">${roomTasks.map(renderTask).join('')}</div>
    </section>
  `).join('');
}

function updateCounters(tasks) {
  const stats = computeCounts(tasks);
  const overdueOnly = Math.max(0, stats.overdue - stats.dead);
  $('#cl-dead').textContent = stats.dead;
  $('#cl-overdue').textContent = overdueOnly;
  $('#cl-due').textContent = stats.due;
  $('#cl-coming').textContent = stats.coming;

  const bar = $('#cl-progress-bar');
  if (bar) {
    bar.style.width = `${stats.pct}%`;
    bar.style.background = colorForCleaningProgress(stats.pct);
    bar.className = 'progress-fill';
  }

  const text = $('#cl-progress-text');
  if (text) text.textContent = `${stats.ok} / ${stats.total} - ${stats.pct}%`;

  const zero = $('#cl-zerostate');
  if (zero) zero.hidden = (stats.overdue + stats.due + stats.coming) !== 0;
}

function renderTodayLog(tasks) {
  const list = $('#cl-today-list');
  if (!list) return;

  const empty = $('#cl-today-empty');
  const count = $('#cl-today-count');
  const today = new Date();
  const historyEvents = getCleaningActionHistory();
  const items = buildTodayLogItems(tasks, historyEvents, today);
  const plannedCount = getStableTodayGoalTarget(tasks, items, historyEvents, today);

  list.innerHTML = items.map((item) => {
    const metaParts = [];
    if (item.room) metaParts.push(item.room);
    if (item.timeLabel) metaParts.push(item.timeLabel);
    return `
      <div class="today-log-item">
        <span class="today-log-dot" aria-hidden="true"></span>
        <span class="today-log-task">${escapeHtml(item.title || '-')}</span>
        <span class="today-log-meta">${escapeHtml(metaParts.join(' • '))}</span>
      </div>
    `;
  }).join('');

  const hasAny = items.length > 0;
  list.hidden = !hasAny;
  if (empty) empty.hidden = hasAny;
  if (count) {
    count.textContent = `${items.length}/${plannedCount}`;
    count.title = 'Zrobione / zaplanowane na dziś';
    count.setAttribute('aria-label', `Zrobione ${items.length} z ${plannedCount} zaplanowanych na dziś`);
  }
}

async function refreshWidget() {
  const stopTimer = startLoadTimer();
  const apartmentId = getActiveCleaningApartmentId();
  const [tasks] = await Promise.all([
    getTasks(apartmentId),
    refreshCleaningActionHistory(apartmentId),
  ]);
  lastLoadMs = stopTimer();
  lastLoadedAt = new Date();
  applyTasks(tasks);
  renderFooter();
}

onDomReady(async () => {
  const widget = document.querySelector('.card.cleaning');
  if (!widget) return;

  let mopPurchasePending = isMopPurchasePending(listTodos());
  const refreshAfterTodoChange = () => {
    const nextPending = isMopPurchasePending(listTodos());
    if (nextPending === mopPurchasePending) return;
    mopPurchasePending = nextPending;
    dailyGoalTargetSnapshot = null;
    try { window.localStorage.removeItem(DAILY_GOAL_TARGET_STORAGE_KEY); } catch {}
    refreshWidget().catch(console.error);
  };
  window.addEventListener(TODO_STORE_CHANGED_EVENT, refreshAfterTodoChange);
  window.addEventListener('storage', (event) => {
    if (event.key === 'todo-items-v1') refreshAfterTodoChange();
  });

  window.addEventListener(DASHBOARD_WIDGETS_CHANGED_EVENT, (event) => {
    cleaningLockEnabled = event.detail?.layout?.cleaningLockEnabled === true;
    updateGoalState(widgetTasks);
    renderList(widgetTasks);
  });

  const unlockButton = document.getElementById('cl-dashboard-unlock');
  unlockButton?.addEventListener('click', () => {
    if (!widget.classList.contains('is-goal-complete')) return;
    setDashboardUnlockedForDay(true);
    updateGoalState(widgetTasks);
  });

  try {
    const stopTimer = startLoadTimer();
    const apartmentId = getActiveCleaningApartmentId();
    const [tasks, dashboardConfig] = await Promise.all([
      getTasks(apartmentId),
      loadDashboardWidgetConfig(),
      refreshCleaningActionHistory(apartmentId),
    ]);
    cleaningLockEnabled = dashboardConfig?.layout?.cleaningLockEnabled === true;
    lastLoadMs = stopTimer();
    lastLoadedAt = new Date();
    applyTasks(tasks);
    renderFooter();
    window.addEventListener(CLEANING_HISTORY_CHANGED_EVENT, () => {
      applyTasks(widgetTasks);
      renderFooter();
    });

    widget.addEventListener('click', async (event) => {
      const btn = event.target.closest('.cl-btn');
      if (!btn) return;

      const row = Number(btn.dataset.row || 0);
      if (!row) return;
      if (pendingWidgetTaskId !== null) return;

      const taskMeta = widgetTasks.find((item) => Number(item.row ?? item.row_id) === row);
      const title = taskMeta?.task
        || btn.closest('.cl-item')?.querySelector('.title')?.textContent?.trim()
        || 'zadanie';

      pendingWidgetTaskId = row;
      sessionDoneTasks.set(row, {
        row,
        title,
        room: taskMeta?.room || '',
        timeLabel: 'teraz',
        ts: Date.now(),
      });
      renderList(widgetTasks);
      renderTodayLog(widgetTasks);
      updateGoalState(widgetTasks);
      syncWidgetPendingButtons(widget);

      scheduleUndo({
        message: `Zaznaczone: ${title}`,
        duration: 4000,
        onUndo: () => {
          sessionDoneTasks.delete(row);
          pendingWidgetTaskId = null;
          renderList(widgetTasks);
          renderTodayLog(widgetTasks);
          updateGoalState(widgetTasks);
          syncWidgetPendingButtons(widget);
        },
        onCommit: async () => {
          try {
            const ok = await markDone(row, {
              apartmentId: getActiveCleaningApartmentId(),
              source: 'cleaning-widget',
            });
            if (!ok) {
              throw new Error('markDone_failed');
            }
            await refreshWidget();
          } catch (error) {
            console.error(error);
            sessionDoneTasks.delete(row);
            applyTasks(widgetTasks);
          } finally {
            pendingWidgetTaskId = null;
            syncWidgetPendingButtons(widget);
          }
        },
      });
    });
  } catch (error) {
    console.error(error);
    setDashboardCleaningLock(false);
    setDailyAchievement('cleaning', {
      state: 'error',
      value: 'Brak danych',
      detail: 'Błąd synchronizacji sprzątania',
      eligible: false,
    });
    const status = $('#cl-status');
    if (status) status.textContent = 'error';
    renderFooter('error');
  }
});
