import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

const api = vi.hoisted(() => ({
  getTasks: vi.fn(),
  markDone: vi.fn(),
}));

const history = vi.hoisted(() => ({
  buildCleaningForecastSeries: vi.fn(),
  buildCleaningHistorySeries: vi.fn(),
  getCleaningActionHistory: vi.fn(),
  getCleaningActionsForDay: vi.fn(),
  getCleaningRecoveryDayKeys: vi.fn(() => new Set()),
  getCleaningForecastRampStart: vi.fn((_, date) => date),
  getCleaningForecastDailyCapacity: vi.fn(() => 3),
  getCleaningDayReference: vi.fn((value, options = {}) => {
    const date = new Date(value);
    date.setHours(date.getHours() - (Number(options.rolloverHour) || 0));
    return date;
  }),
  getCleaningDayKey: vi.fn((value, options = {}) => {
    const date = new Date(value);
    date.setHours(date.getHours() - (Number(options.rolloverHour) || 0));
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }),
  refreshCleaningActionHistory: vi.fn(),
  CLEANING_HISTORY_CHANGED_EVENT: 'cleaning-history:file-changed',
}));

const undo = vi.hoisted(() => ({
  options: null,
  scheduleUndo: vi.fn((options) => {
    undo.options = options;
  }),
}));

const dashboardSettings = vi.hoisted(() => ({
  cleaningLockEnabled: true,
}));

vi.mock('../js/cleaning-api.js', () => api);
vi.mock('../js/cleaning-apartments.js', () => ({
  getActiveCleaningApartmentId: () => 'aleja-pokoju6',
}));
vi.mock('../js/cleaning-history.js', () => history);
vi.mock('../js/load-timing.js', () => ({
  startLoadTimer: () => () => 4,
  formatLoadedAt: () => '12:00',
  loadTimeSuffix: () => 'load 4ms',
}));
vi.mock('../js/undo-toast.js', () => ({ scheduleUndo: undo.scheduleUndo }));
vi.mock('../js/dashboard-settings.js', () => ({
  DASHBOARD_WIDGETS_CHANGED_EVENT: 'dashboard:widgets-changed',
  loadDashboardWidgetConfig: vi.fn(async () => ({
    layout: { cleaningLockEnabled: dashboardSettings.cleaningLockEnabled },
  })),
}));

function installDom() {
  const window = new Window({ url: 'http://localhost:5173/index.html' });
  window.document.body.innerHTML = `
    <nav class="dashboard-side-shortcuts"><a href="/other">Other</a></nav>
    <a class="dashboard-screensaver-link" href="/screen">Screen</a>
    <a class="dashboard-settings-link" href="/settings">Settings</a>
    <section class="hero"><div id="hero-hhmm">12:00</div><div id="hero-date">Today</div><section class="daily-achievements"></section></section>
    <section class="dash" data-columns="3">
      <div class="card cleaning" id="cleaning-card" data-widget="cleaning">
        <div id="cl-dead"></div><div id="cl-overdue"></div><div id="cl-due"></div><div id="cl-coming"></div>
        <div id="cl-progress-bar"></div><div id="cl-progress-text"></div>
        <div id="cl-dashboard-lock-message" hidden>
          <span id="cl-dashboard-lock-text"></span>
          <button id="cl-dashboard-unlock" type="button" hidden>Odblokuj dashboard</button>
        </div>
        <div id="cl-goal-progress"></div>
        <div id="cl-goal-ring"><span id="cl-goal-ring-value"></span></div>
        <div id="cl-streak"></div><div id="cl-average"></div><div id="cl-week"></div>
        <div id="cl-today-list"></div><div id="cl-today-empty"></div><div id="cl-today-count"></div>
        <div id="cl-list"></div><div id="cl-zerostate"></div><div id="cl-updated"></div>
      </div>
      <div class="card" id="other-card" data-widget="other"><button type="button">Other action</button></div>
    </section>
  `;

  const previous = new Map();
  const assign = (key, value) => {
    previous.set(key, globalThis[key]);
    globalThis[key] = value;
  };

  assign('window', window);
  assign('document', window.document);
  assign('Event', window.Event);
  assign('CustomEvent', window.CustomEvent);
  assign('HTMLElement', window.HTMLElement);
  assign('Node', window.Node);
  assign('getComputedStyle', window.getComputedStyle.bind(window));

  return () => {
    for (const [key, value] of previous.entries()) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
    window.close();
  };
}

function recentSeries(now) {
  const counts = [0, 1, 0, 2, 1, 1, 3];
  return counts.map((count, index) => {
    const date = new Date(now);
    date.setDate(date.getDate() - (6 - index));
    return {
      date: date.toISOString(),
      dayKey: date.toISOString().slice(0, 10),
      count,
      isToday: index === counts.length - 1,
    };
  });
}

describe('cleaning dashboard rhythm panel', () => {
  let restoreDom;

  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    dashboardSettings.cleaningLockEnabled = true;
    undo.options = null;
    restoreDom = installDom();

    api.getTasks.mockResolvedValue([]);
    history.refreshCleaningActionHistory.mockResolvedValue([]);
    history.getCleaningRecoveryDayKeys.mockReturnValue(new Set());
    history.getCleaningForecastDailyCapacity.mockReturnValue(3);
    history.getCleaningActionHistory.mockReturnValue([{ at: new Date().toISOString() }]);
    history.getCleaningActionsForDay.mockReturnValue([
      { at: new Date().toISOString(), row: 1, task: 'Biurko' },
      { at: new Date().toISOString(), row: 2, task: 'Śmieci' },
      { at: new Date().toISOString(), row: 3, task: 'Łóżko' },
    ]);
    history.buildCleaningForecastSeries.mockImplementation((_tasks, { now }) => [
      { date: now.toISOString(), count: 0, tasks: [], isToday: true },
    ]);
    history.buildCleaningHistorySeries.mockImplementation((_events, { now }) => recentSeries(now));
  });

  afterEach(() => {
    restoreDom?.();
    vi.restoreAllMocks();
  });

  it('renders the goal, seven-day activity and gold completion state without recording anything', async () => {
    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('3/3 zadań');
    expect(document.getElementById('cl-goal-ring-value')?.textContent).toBe('✓');
    expect(document.getElementById('cl-goal-ring')?.classList.contains('is-complete')).toBe(true);
    expect(document.getElementById('cleaning-card')?.classList.contains('is-goal-complete')).toBe(true);
    expect(document.getElementById('cl-streak')?.textContent).toBe('4 dni serii');
    expect(document.getElementById('cl-average')?.textContent).toBe('1,1 zadań/dzień');
    expect(document.querySelectorAll('.cleaning-week-day')).toHaveLength(7);
    expect(document.querySelectorAll('.cleaning-week-day.is-goal-complete')).toHaveLength(1);
    expect(document.querySelectorAll('.cleaning-week-day.has-actions:not(.is-goal-complete)')).toHaveLength(4);
    expect(document.querySelector('.cleaning-week-day.is-today.is-goal-complete .cleaning-week-dot')?.textContent).toBe('✓');
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('true');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(true);
    expect(document.getElementById('cl-dashboard-unlock')?.hidden).toBe(false);
    document.getElementById('cl-dashboard-unlock')?.click();
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('false');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(false);
    expect(api.markDone).not.toHaveBeenCalled();
  });

  it('leaves the dashboard usable by default when cleaning lock is disabled', async () => {
    dashboardSettings.cleaningLockEnabled = false;
    api.getTasks.mockResolvedValue([{
      row: 1, task: 'Biurko', room: 'Pokój', category: 'Inne',
      nextDueIn: 0, daysSince: 7, freq: 7, overdue: false,
    }]);
    history.getCleaningActionHistory.mockReturnValue([]);
    history.getCleaningActionsForDay.mockReturnValue([]);
    history.buildCleaningForecastSeries.mockImplementation((_tasks, { now }) => [{
      date: now.toISOString(), count: 1, tasks: [{ row: 1, count: 1 }], isToday: true,
    }]);

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('false');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(false);
    expect(document.getElementById('cl-dashboard-lock-message')?.hidden).toBe(true);
    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('0/1 zadań');

    window.dispatchEvent(new CustomEvent('dashboard:widgets-changed', {
      detail: { layout: { cleaningLockEnabled: true } },
    }));
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('true');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(true);
    expect(document.querySelector('.dashboard-settings-link')?.hasAttribute('inert')).toBe(false);

    window.dispatchEvent(new CustomEvent('dashboard:widgets-changed', {
      detail: { layout: { cleaningLockEnabled: false } },
    }));
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('false');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(false);
  });

  it('keeps blocked mop tasks out of the next-tasks queue and daily target', async () => {
    dashboardSettings.cleaningLockEnabled = false;
    const tasks = [
      { row: 5, task: 'Umyj podłogę mopem w pokoju', room: 'Pokój', category: 'Inne', freq: 7, daysSince: 30, nextDueIn: 0, overdue: true, blocked: true },
      { row: 6, task: 'Umyj zlew', room: 'Kuchnia', category: 'Inne', freq: 7, daysSince: 7, nextDueIn: 0, overdue: false },
    ];
    api.getTasks.mockResolvedValue(tasks);
    history.getCleaningActionHistory.mockReturnValue([]);
    history.getCleaningActionsForDay.mockReturnValue([]);
    history.buildCleaningForecastSeries.mockImplementation((input, { now }) => [{
      date: now.toISOString(),
      count: input.filter((task) => !task.blocked).length,
      tasks: input.filter((task) => !task.blocked).map((task) => ({ row: task.row, count: 1 })),
      isToday: true,
    }]);

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.querySelector('.cl-btn[data-row="5"]')).toBeNull();
    expect(document.querySelector('.cl-btn[data-row="6"]')).not.toBeNull();
    expect(Number(document.getElementById('cl-dead')?.textContent || 0)).toBe(0);
    expect(document.getElementById('cl-progress-text')?.textContent).toBe('0 / 1 - 0%');
    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('0/1 zadań');
  });

  it('keeps the daily target and a green DONE status until a full page reload', async () => {
    const initialTasks = [1, 2, 3, 4, 5].map((row) => ({
      row,
      task: row === 1 ? 'Zadanie środkowe' : `${String.fromCharCode(64 + row)} zadanie`,
      room: 'Kuchnia',
      category: 'Inne',
      nextDueIn: 0,
      daysSince: 7,
      freq: 7,
      overdue: false,
    }));
    const refreshedTasks = initialTasks.map((task) => (task.row === 1
      ? { ...task, nextDueIn: 7, daysSince: 0 }
      : task));
    let todayActions = [];

    api.getTasks
      .mockResolvedValueOnce(initialTasks)
      .mockResolvedValueOnce(refreshedTasks);
    api.markDone.mockResolvedValue({ ok: true });
    history.getCleaningActionHistory.mockImplementation(() => todayActions);
    history.getCleaningActionsForDay.mockImplementation(() => todayActions);
    history.buildCleaningForecastSeries.mockImplementation((tasks, { now }) => {
      const planned = tasks.filter((task) => task.nextDueIn === 0);
      return [{
        date: now.toISOString(),
        count: planned.length,
        tasks: planned.map((task) => ({ row: task.row, count: 1 })),
        isToday: true,
      }];
    });

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('0/3 zadań');
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('true');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(true);
    const initialOrder = [...document.querySelectorAll('.cl-btn[data-row]')]
      .map((button) => button.dataset.row);
    expect(initialOrder.indexOf('1')).toBeGreaterThan(0);
    document.querySelector('.cl-btn[data-row="1"]')?.click();

    const immediateDone = document.querySelector('.cl-btn[data-row="1"]');
    expect(immediateDone?.textContent.trim()).toBe('DONE');
    expect(immediateDone?.classList.contains('done')).toBe(true);
    expect(immediateDone?.disabled).toBe(true);
    expect([...document.querySelectorAll('.cl-btn[data-row]')].map((button) => button.dataset.row)).toEqual(initialOrder);
    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('1/3 zadań');
    expect(api.markDone).not.toHaveBeenCalled();

    todayActions = [{
      at: new Date().toISOString(),
      row: 1,
      task: 'Wynieś śmieci',
      room: 'Kuchnia',
    }];
    await undo.options.onCommit();

    const committedDone = document.querySelector('.cl-btn[data-row="1"]');
    expect(api.markDone).toHaveBeenCalledWith(1, expect.objectContaining({ source: 'cleaning-widget' }));
    expect(committedDone?.textContent.trim()).toBe('DONE');
    expect(committedDone?.classList.contains('done')).toBe(true);
    expect(committedDone?.disabled).toBe(true);
    expect([...document.querySelectorAll('.cl-btn[data-row]')].map((button) => button.dataset.row)).toEqual(initialOrder);
    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('1/3 zadań');
  });

  it('restores today target after the first action and then freezes it', async () => {
    const actions = [
      { at: new Date(Date.now() + 60_000).toISOString(), row: 33, task: 'Zmień pościel', status: 'OVERDUE' },
      { at: new Date().toISOString(), row: 3, task: 'Przetrzyj biurko', status: 'OVERDUE' },
      { at: new Date(Date.now() - 60_000).toISOString(), row: 136, task: 'Przetrzyj pianino', status: 'OVERDUE' },
    ];
    const tasks = [
      { row: 3, task: 'Przetrzyj biurko', room: 'Duży pokój', freq: 7, daysSince: 0, nextDueIn: 7, overdue: false },
      { row: 33, task: 'Zmień pościel', room: 'Sypialnia', freq: 7, daysSince: 0, nextDueIn: 7, overdue: false },
      { row: 136, task: 'Przetrzyj pianino', room: 'Duży pokój', freq: 7, daysSince: 0, nextDueIn: 7, overdue: false },
      { row: 4, task: 'Plan 1', room: 'Kuchnia', freq: 7, daysSince: 14, nextDueIn: 0, overdue: true },
      { row: 5, task: 'Plan 2', room: 'Łazienka', freq: 7, daysSince: 14, nextDueIn: 0, overdue: true },
      { row: 6, task: 'Plan 3', room: 'Sypialnia', freq: 7, daysSince: 14, nextDueIn: 0, overdue: true },
    ];
    api.getTasks.mockResolvedValue(tasks);
    history.getCleaningActionHistory.mockReturnValue(actions);
    history.getCleaningActionsForDay.mockImplementation((events) => events);
    history.buildCleaningForecastSeries.mockImplementation((_tasks, { now }) => [{
      date: now.toISOString(),
      count: 3,
      tasks: [4, 5, 6].map((row) => ({ row, count: 1 })),
      isToday: true,
    }]);

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('3/3 zadań');
    expect(document.getElementById('cl-today-count')?.textContent).toBe('3/3');
    expect(JSON.parse(window.localStorage.getItem('cleaningDashboard.dailyGoalTarget.v2'))?.target).toBe(3);
  });

  it('uses the ramped plan as the dashboard goal after the first day', async () => {
    const tasks = Array.from({ length: 4 }, (_, index) => ({
      row: index + 1, task: `Overdue ${index + 1}`, room: 'Kitchen',
      freq: 7, daysSince: 14, nextDueIn: 0, overdue: true,
    }));
    api.getTasks.mockResolvedValue(tasks);
    history.getCleaningActionHistory.mockReturnValue([]);
    history.getCleaningActionsForDay.mockReturnValue([]);
    history.getCleaningForecastDailyCapacity.mockReturnValue(4);
    history.buildCleaningForecastSeries.mockImplementation((_tasks, { now }) => [{
      date: now.toISOString(), count: 4,
      tasks: tasks.map((task) => ({ row: task.row, count: 1 })), isToday: true,
    }]);

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('cl-goal-progress')?.textContent).toContain('0/4');
    expect(document.getElementById('cl-today-count')?.textContent).toBe('0/4');
  });

  it('overrides a stored nine-task target with 1/1 after the washing-machine task', async () => {
    const key = `aleja-pokoju6:${history.getCleaningDayKey(new Date(), { rolloverHour: 6 })}`;
    window.localStorage.setItem('cleaningDashboard.dailyGoalTarget.v2', JSON.stringify({ key, target: 9 }));
    history.getCleaningRecoveryDayKeys.mockReturnValue(new Set([key.split(':')[1]]));
    const action = { at: new Date().toISOString(), row: 1, task: 'Obudowa pralki' };
    history.getCleaningActionHistory.mockReturnValue([action]);
    history.getCleaningActionsForDay.mockReturnValue([action]);
    api.getTasks.mockResolvedValue([{
      row: 1, task: 'Overdue', room: 'Kitchen', category: 'General',
      freq: 7, overdue: true, nextDueIn: 0, daysSince: 20,
    }]);
    history.buildCleaningForecastSeries.mockImplementation((_tasks, { now }) => [{
      date: now.toISOString(), count: 9, tasks: [], isToday: true,
    }]);

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('cl-goal-progress')?.textContent).toBe('1/1 zadań');
    expect(document.getElementById('cl-today-count')?.textContent).toBe('1/1');
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('false');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(false);
    expect(document.getElementById('cl-list')?.textContent).toBe('');
    expect(document.querySelectorAll('.cl-btn[data-row]')).toHaveLength(0);
    expect(JSON.parse(window.localStorage.getItem('cleaningDashboard.dailyGoalTarget.v2'))?.target).toBe(1);
  });

  it('shows every DEAD, OVERDUE and DUE task while the dashboard is locked', async () => {
    const urgentTasks = Array.from({ length: 8 }, (_, index) => ({
      row: index + 1,
      task: `Pilne ${index + 1}`,
      category: 'Inne',
      nextDueIn: 0,
      daysSince: 7,
      freq: 7,
      overdue: false,
    }));
    const comingTask = {
      row: 99,
      task: 'Jeszcze nie teraz',
      category: 'Inne',
      nextDueIn: 1,
      daysSince: 9.5,
      freq: 10,
      overdue: false,
    };
    api.getTasks.mockResolvedValue([...urgentTasks, comingTask]);
    history.getCleaningActionHistory.mockReturnValue([]);
    history.getCleaningActionsForDay.mockReturnValue([]);
    history.buildCleaningForecastSeries.mockImplementation((tasks, { now }) => {
      const planned = tasks.filter((task) => task.nextDueIn === 0);
      return [{
        date: now.toISOString(),
        count: planned.length,
        tasks: planned.map((task) => ({ row: task.row, count: 1 })),
        isToday: true,
      }];
    });

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('true');
    expect(document.querySelectorAll('.cl-btn[data-row]')).toHaveLength(8);
    expect(document.querySelector('.cl-btn[data-row="99"]')).toBeNull();
  });

  it('groups locked tasks by room and orders each room DEAD, OVERDUE, DUE', async () => {
    const tasks = [
      { row: 1, task: 'Due sypialnia', room: 'Sypialnia', nextDueIn: 0, daysSince: 7, freq: 7, overdue: false },
      { row: 2, task: 'Overdue kuchnia', room: 'Kuchnia', nextDueIn: -3, daysSince: 10, freq: 7, overdue: true },
      { row: 3, task: 'Dead kuchnia', room: 'Kuchnia', nextDueIn: -9, daysSince: 16, freq: 7, overdue: true },
      { row: 4, task: 'Dead sypialnia', room: 'Sypialnia', nextDueIn: -10, daysSince: 17, freq: 7, overdue: true },
      { row: 5, task: 'Due lazienka', room: 'Łazienka', nextDueIn: 0, daysSince: 7, freq: 7, overdue: false },
    ];
    api.getTasks.mockResolvedValue(tasks);
    history.getCleaningActionHistory.mockReturnValue([]);
    history.getCleaningActionsForDay.mockReturnValue([]);
    history.buildCleaningForecastSeries.mockImplementation((_tasks, { now }) => [{
      date: now.toISOString(),
      count: tasks.length,
      tasks: tasks.map((task) => ({ row: task.row, count: 1 })),
      isToday: true,
    }]);

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    const groups = [...document.querySelectorAll('.cl-room-group')].map((group) => ({
      room: group.querySelector('.cl-room-name')?.textContent,
      statuses: [...group.querySelectorAll('.cl-btn')].map((button) => button.textContent.trim()),
    }));
    expect(groups).toEqual([
      { room: 'Kuchnia', statuses: ['DEAD', 'OVERDUE'] },
      { room: 'Łazienka', statuses: ['DUE'] },
      { room: 'Sypialnia', statuses: ['DEAD', 'DUE'] },
    ]);
  });

  it('offers an explicit unlock after the final task and relocks when undo is used', async () => {
    const task = {
      row: 1,
      task: 'Ostatnie zadanie',
      category: 'Inne',
      nextDueIn: 0,
      daysSince: 7,
      freq: 7,
      overdue: false,
    };
    api.getTasks.mockResolvedValue([task]);
    history.getCleaningActionHistory.mockReturnValue([]);
    history.getCleaningActionsForDay.mockReturnValue([]);
    history.buildCleaningForecastSeries.mockImplementation((_tasks, { now }) => [{
      date: now.toISOString(),
      count: 1,
      tasks: [{ row: 1, count: 1 }],
      isToday: true,
    }]);

    await import('../js/widget-cleaning.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(true);
    document.querySelector('.cl-btn[data-row="1"]')?.click();
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('true');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(true);
    expect(document.getElementById('cl-dashboard-unlock')?.hidden).toBe(false);

    document.getElementById('cl-dashboard-unlock')?.click();
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('false');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(false);
    expect(JSON.parse(window.localStorage.getItem('cleaningDashboard.dailyUnlock.v1'))?.unlocked).toBe(true);

    undo.options.onUndo();
    expect(document.querySelector('.dash')?.dataset.cleaningLocked).toBe('true');
    expect(document.getElementById('other-card')?.hasAttribute('inert')).toBe(true);
    expect(document.getElementById('cl-dashboard-unlock')?.hidden).toBe(true);
    expect(window.localStorage.getItem('cleaningDashboard.dailyUnlock.v1')).toBeNull();
  });
});
