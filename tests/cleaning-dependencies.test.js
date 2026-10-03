import { describe, expect, it } from 'vitest';
import { applyCleaningDependencies } from '../js/cleaning-dependencies.js';
import { computeCounts, deriveStatus } from '../js/cleaning-logic.js';
import { buildCleaningForecastSeries } from '../js/cleaning-history.js';

const mopTodo = { id: 'ad7ac326-5485-4157-98c8-401f702cbbb9', title: 'Mop do podłogi', bucket: 'shopping' };
const tasks = [
  { row: 5, task: 'Umyj podłogę mopem w dużym pokoju', room: 'Salon', freq: 7, overdue: true, daysSince: 30, nextDueIn: 0 },
  { row: 6, task: 'Umyj podłogę mopem w kuchni', room: 'Kuchnia', freq: 7, overdue: true, daysSince: 30, nextDueIn: 0 },
  { row: 7, task: 'Odkurz podłogę w kuchni', room: 'Kuchnia', freq: 7, overdue: false, daysSince: 7, nextDueIn: 0 },
];

describe('mop purchase dependency', () => {
  it('blocks only mop washing tasks and removes them from counters and forecasts', () => {
    const blocked = applyCleaningDependencies(tasks, [{ ...mopTodo, done: false }]);
    expect(blocked.map(deriveStatus)).toEqual(['BLOCKED', 'BLOCKED', 'DUE']);
    expect(computeCounts(blocked)).toMatchObject({ total: 1, overdue: 0, dead: 0, due: 1 });

    const forecast = buildCleaningForecastSeries(blocked, { range: 'week', now: new Date(2026, 8, 29, 12) });
    expect(forecast.flatMap((day) => day.tasks).map((task) => task.label)).not.toContain('Umyj podłogę mopem w kuchni');
    expect(forecast.flatMap((day) => day.tasks).some((task) => task.label === 'Odkurz podłogę w kuchni')).toBe(true);
  });

  it('restores normal status and planning once the todo is completed', () => {
    const unblocked = applyCleaningDependencies(tasks, [{ ...mopTodo, done: true }]);
    expect(unblocked.map(deriveStatus)).toEqual(['DEAD', 'DEAD', 'DUE']);
    expect(computeCounts(unblocked)).toMatchObject({ total: 3, overdue: 2, dead: 2, due: 1 });
    const forecast = buildCleaningForecastSeries(unblocked, { range: 'week', now: new Date(2026, 8, 29, 12) });
    expect(forecast.flatMap((day) => day.tasks).some((task) => task.label === 'Umyj podłogę mopem w kuchni')).toBe(true);
  });
});
