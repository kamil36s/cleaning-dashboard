import { describe, expect, it } from 'vitest';
import {
  buildCleaningForecastSeries,
  buildCleaningHistoryWindow,
  buildCleaningHistorySeries,
  getCleaningActionsForDay,
  getCleaningDayKey,
  getCleaningForecastRampStart,
  getCleaningRecoveryDayKeys,
  summarizeCleaningForecastSeries,
  summarizeCleaningHistory,
} from '../js/cleaning-history.js';

const ts = (y, m, d, h = 12, min = 0) => new Date(y, m - 1, d, h, min, 0, 0).toISOString();

describe('Cleaning history analytics', () => {
  it('builds daily series for selected range', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const events = [
      { at: ts(2026, 2, 20, 9, 15), task: 'Mop', status: 'DEAD' },
      { at: ts(2026, 2, 20, 18, 30), task: 'Dust' },
      { at: ts(2026, 2, 19, 8, 0), task: 'Dust' },
      { at: ts(2026, 2, 18, 7, 0), task: 'Trash' },
      { at: ts(2026, 2, 10, 7, 0), task: 'Old' },
    ];

    const series = buildCleaningHistorySeries(events, { days: 7, now });
    const map = new Map(series.map((item) => [item.dayKey, item.count]));

    expect(series).toHaveLength(7);
    expect(map.get('2026-02-20')).toBe(2);
    expect(map.get('2026-02-19')).toBe(1);
    expect(map.get('2026-02-18')).toBe(1);
    expect(map.get('2026-02-14')).toBe(0);
    expect(series.find((item) => item.dayKey === '2026-02-20')?.tasks.some((task) => task.status === 'DEAD')).toBe(true);
  });

  it('aligns month windows to full calendar month', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const events = [
      { at: ts(2026, 2, 1, 9, 15), task: 'Mop' },
      { at: ts(2026, 2, 20, 18, 30), task: 'Dust' },
      { at: ts(2026, 2, 28, 7, 0), task: 'Trash' },
      { at: ts(2026, 3, 1, 7, 0), task: 'Future' },
    ];

    const window = buildCleaningHistoryWindow({ range: 'month', now });
    const series = buildCleaningHistorySeries(events, { range: 'month', now });

    expect(window.startDate.getFullYear()).toBe(2026);
    expect(window.startDate.getMonth()).toBe(1);
    expect(window.startDate.getDate()).toBe(1);
    expect(window.endDate.getFullYear()).toBe(2026);
    expect(window.endDate.getMonth()).toBe(1);
    expect(window.endDate.getDate()).toBe(28);
    expect(series).toHaveLength(28);
    expect(series[0]?.dayKey).toBe('2026-02-01');
    expect(series[series.length - 1]?.dayKey).toBe('2026-02-28');
    expect(series.find((item) => item.dayKey === '2026-02-20')?.count).toBe(1);
    expect(series.find((item) => item.dayKey === '2026-02-28')?.count).toBe(1);
  });

  it('supports offset windows for future navigation', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const window = buildCleaningHistoryWindow({ range: 'week', now, offset: 1 });

    expect(window.startDate.getFullYear()).toBe(2026);
    expect(window.startDate.getMonth()).toBe(1);
    expect(window.startDate.getDate()).toBe(23);
    expect(window.endDate.getDate()).toBe(1);
    expect(window.isFuture).toBe(true);
    expect(window.includesToday).toBe(false);
  });

  it('summarizes streak and top stats', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const events = [
      { at: ts(2026, 2, 20, 7, 10), task: 'Mop', room: 'Kuchnia' },
      { at: ts(2026, 2, 20, 18, 5), task: 'Mop', room: 'Kuchnia' },
      { at: ts(2026, 2, 19, 9, 45), task: 'Kurz', room: 'Salon' },
      { at: ts(2026, 2, 18, 8, 30), task: 'Mop', room: 'Kuchnia' },
      { at: ts(2026, 1, 25, 11, 15), task: 'Okno', room: 'Salon' },
    ];

    const summary = summarizeCleaningHistory(events, { now });

    expect(summary.today).toBe(2);
    expect(summary.weekTotal).toBe(4);
    expect(summary.monthTotal).toBe(4);
    expect(summary.quarterTotal).toBe(5);
    expect(summary.yearTotal).toBe(5);
    expect(summary.streak).toBe(3);
    expect(summary.topTask).toEqual({ label: 'Mop', count: 3 });
    expect(summary.topRoom).toEqual({ label: 'Kuchnia', count: 3 });
    expect(summary.bestDay?.dayKey).toBe('2026-02-20');
    expect(summary.bestDay?.count).toBe(2);
  });

  it('returns day actions sorted from newest to oldest', () => {
    const target = new Date(2026, 1, 20, 12, 0, 0, 0);
    const events = [
      { at: ts(2026, 2, 20, 7, 0), task: 'A' },
      { at: ts(2026, 2, 20, 19, 0), task: 'B' },
      { at: ts(2026, 2, 19, 12, 0), task: 'C' },
    ];

    const actions = getCleaningActionsForDay(events, target);
    expect(actions).toHaveLength(2);
    expect(actions[0].task).toBe('B');
    expect(actions[1].task).toBe('A');
  });

  it('keeps the cleaning day open until 06:00 when a rollover hour is provided', () => {
    const target = new Date(2026, 1, 21, 2, 0, 0, 0);
    const events = [
      { at: ts(2026, 2, 20, 5, 59), task: 'Previous cleaning day' },
      { at: ts(2026, 2, 20, 23, 30), task: 'Before midnight' },
      { at: ts(2026, 2, 21, 2, 0), task: 'After midnight' },
      { at: ts(2026, 2, 21, 6, 0), task: 'Next cleaning day' },
    ];

    const actions = getCleaningActionsForDay(events, target, { rolloverHour: 6 });
    expect(actions.map((action) => action.task)).toEqual(['After midnight', 'Before midnight']);
    expect(getCleaningDayKey(target, { rolloverHour: 6 })).toBe('2026-02-20');
    expect(getCleaningDayKey(new Date(2026, 1, 21, 5, 59), { rolloverHour: 6 })).toBe('2026-02-20');
    expect(getCleaningDayKey(new Date(2026, 1, 21, 6, 0), { rolloverHour: 6 })).toBe('2026-02-21');
  });

  it('builds cleaning forecast with balanced recurring plan', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const tasks = [
      { task: 'Mop', room: 'Kitchen', category: 'Floor', freq: 3, overdue: true, nextDueIn: 0, daysSince: 5 },
      { task: 'Dust', room: 'Living', category: 'Dust', freq: 2, overdue: false, nextDueIn: 2, daysSince: 0 },
    ];

    const series = buildCleaningForecastSeries(tasks, { range: 'week', now });
    const summary = summarizeCleaningForecastSeries(series);
    const map = new Map(series.map((item) => [item.dayKey, item]));

    expect(series).toHaveLength(7);
    expect(summary.total).toBeGreaterThanOrEqual(2);
    expect(summary.topRoom?.label).toBeTruthy();
    expect(summary.topTask?.label).toBeTruthy();
    expect(map.get('2026-02-20')?.tasks.some((task) => task.label === 'Mop')).toBe(true);
    expect(series.some((item) => item.tasks.some((task) => task.label === 'Dust'))).toBe(true);
  });

  it('starts any backlog at 3 tasks and increases the limit gradually', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const tasks = Array.from({ length: 40 }, (_, index) => ({
      task: `Task ${index + 1}`,
      room: 'Kitchen',
      category: 'General',
      freq: 7,
      overdue: true,
      nextDueIn: 0,
      daysSince: 14,
    }));

    const series = buildCleaningForecastSeries(tasks, { range: 'week', now });
    const byDay = new Map(series.map((item) => [item.dayKey, item.count]));
    const counts = series.map((item) => item.count);

    expect(byDay.get('2026-02-20')).toBe(3);
    expect(byDay.get('2026-02-21')).toBe(4);
    expect(byDay.get('2026-02-22')).toBe(4);
    expect(Math.max(...counts)).toBeLessThanOrEqual(10);
    expect(counts.reduce((sum, value) => sum + value, 0)).toBe(11);
  });

  it('keeps the ramp start across days and resets it after the backlog is cleared', () => {
    const tasks = Array.from({ length: 9 }, (_, index) => ({
      task: `Task ${index + 1}`, room: 'Kitchen', freq: 7,
      overdue: index < 8, nextDueIn: 0, daysSince: 14,
    }));
    const firstDay = new Date(2026, 8, 29, 12);
    const nextDay = new Date(2026, 8, 30, 12);
    const firstStart = getCleaningForecastRampStart(tasks, firstDay);
    const firstPlan = buildCleaningForecastSeries(tasks, { range: 'week', now: firstDay, planStart: firstStart });
    const nextStart = getCleaningForecastRampStart(tasks, nextDay);
    const nextPlan = buildCleaningForecastSeries(tasks, { range: 'week', now: nextDay, planStart: nextStart });

    expect(firstPlan.find((day) => day.isToday)?.count).toBe(3);
    expect(firstPlan.find((day) => day.dayKey === '2026-09-30')?.count).toBe(4);
    expect(nextStart).toEqual(firstStart);
    expect(nextPlan.find((day) => day.isToday)?.count).toBe(4);

    getCleaningForecastRampStart(tasks.map((task) => ({ ...task, overdue: false })), nextDay);
    expect(getCleaningForecastRampStart(tasks, new Date(2026, 9, 1, 12)).getDate()).toBe(1);
  });

  it('keeps future tasks close to their deadlines instead of front-loading them', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const tasks = [
      { task: 'Due today', room: 'Kitchen', category: 'General', freq: 7, overdue: false, nextDueIn: 0, daysSince: 7 },
      { task: 'Due in 3 days', room: 'Salon', category: 'Dust', freq: 7, overdue: false, nextDueIn: 3, daysSince: 4 },
      { task: 'Due in 5 days', room: 'Lazienka', category: 'General', freq: 7, overdue: false, nextDueIn: 5, daysSince: 2 },
    ];

    const series = buildCleaningForecastSeries(tasks, { range: 'month', now });
    const byDay = new Map(series.map((item) => [item.dayKey, item]));

    expect(byDay.get('2026-02-20')?.tasks.some((task) => task.label === 'Due today')).toBe(true);
    expect(byDay.get('2026-02-23')?.tasks.some((task) => task.label === 'Due in 3 days')).toBe(true);
    expect(byDay.get('2026-02-25')?.tasks.some((task) => task.label === 'Due in 5 days')).toBe(true);
    expect(byDay.get('2026-02-21')?.count).toBe(0);
    expect(byDay.get('2026-02-22')?.count).toBe(0);
    expect(byDay.get('2026-02-24')?.count).toBe(0);
  });

  it('starts a heavy DEAD backlog gently, ramps up, then returns tasks to cadence', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const tasks = Array.from({ length: 12 }, (_, index) => ({
      task: `Overdue ${index + 1}`,
      room: 'Kitchen',
      category: 'General',
      freq: 7,
      overdue: true,
      nextDueIn: 0,
      daysSince: 21,
    }));

    const series = buildCleaningForecastSeries(tasks, { range: 'month', now });
    const byDay = new Map(series.map((item) => [item.dayKey, item.count]));

    expect(byDay.get('2026-02-20')).toBe(3);
    expect(byDay.get('2026-02-21')).toBe(4);
    expect(byDay.get('2026-02-22')).toBe(4);
    expect(byDay.get('2026-02-23')).toBe(1);
    expect(byDay.get('2026-02-27')).toBe(3);
    expect(byDay.get('2026-02-28')).toBe(4);
  });

  it('plans one task after 10 actions and resumes gently afterward', () => {
    const now = new Date(2026, 8, 28, 12);
    const yesterday = Array.from({ length: 15 }, (_, index) => ({
      at: ts(2026, 9, 27, 7, index), task: `Done ${index}`,
    }));
    const tasks = Array.from({ length: 12 }, (_, index) => ({
      task: `Overdue ${index}`, room: 'Kitchen', category: 'General',
      freq: 7, overdue: true, nextDueIn: 0, daysSince: 20,
    }));
    const series = buildCleaningForecastSeries(tasks, { range: 'week', now, historyEvents: yesterday });

    expect(getCleaningRecoveryDayKeys(yesterday).has('2026-09-28')).toBe(true);
    expect(series.find((day) => day.dayKey === '2026-09-28')?.count).toBe(1);
    expect(series.find((day) => day.dayKey === '2026-09-29')?.count).toBe(4);
    expect(Math.max(...series.map((day) => day.count))).toBeLessThanOrEqual(10);
  });

  it('counts routine work inside the gentle daily goal before adding DEAD backlog', () => {
    const now = new Date(2026, 1, 20, 12, 0, 0, 0);
    const routine = Array.from({ length: 2 }, (_, index) => ({
      task: `Routine ${index + 1}`,
      room: 'Kitchen',
      category: 'General',
      freq: 7,
      overdue: false,
      nextDueIn: 0,
      daysSince: 7,
    }));
    const dead = Array.from({ length: 8 }, (_, index) => ({
      task: `Dead ${index + 1}`,
      room: 'Kitchen',
      category: 'General',
      freq: 14,
      overdue: true,
      nextDueIn: 0,
      daysSince: 30,
    }));

    const series = buildCleaningForecastSeries([...routine, ...dead], { range: 'week', now });
    const today = series.find((day) => day.dayKey === '2026-02-20');

    expect(today?.count).toBe(3);
    expect(today?.tasks.filter((task) => task.label.startsWith('Routine'))).toHaveLength(2);
    expect(today?.tasks.filter((task) => task.label.startsWith('Dead'))).toHaveLength(1);
  });
});
