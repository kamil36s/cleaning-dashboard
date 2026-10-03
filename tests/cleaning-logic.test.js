import { describe, it, expect } from 'vitest';
import {
  computeCounts,
  deriveStatus,
  groupTasksByCategory,
  groupTasksByRoom,
  preserveTaskOrder,
} from '../js/cleaning-logic.js';

describe('Cleaning status (WHY: highlight urgent chores)', () => {
  it('classifies overdue > 7 days as DEAD', () => {
    const task = { overdue: true, daysSince: 20, freq: 10 };
    expect(deriveStatus(task)).toBe('DEAD');
  });

  it('computes counters and health percent', () => {
    const tasks = [
      { overdue: true, daysSince: 20, freq: 10 }, // DEAD
      { overdue: true, daysSince: 5, freq: 3 },   // OVERDUE
      { overdue: false, nextDueIn: 0, freq: 7, daysSince: 7 }, // DUE
      { overdue: false, nextDueIn: 1, freq: 10, daysSince: 10 }, // COMING
      { overdue: false, nextDueIn: 5, freq: 10, daysSince: 1 }, // FRESH
    ];

    const stats = computeCounts(tasks);
    expect(stats.total).toBe(5);
    expect(stats.overdue).toBe(2);
    expect(stats.due).toBe(1);
    expect(stats.coming).toBe(1);
    expect(stats.dead).toBe(1);
    expect(stats.ok).toBe(1);
    expect(stats.pct).toBe(20);
  });

  it('keeps existing cards in place after their status changes', () => {
    const previous = [{ id: 1, status: 'OVERDUE' }, { id: 2, status: 'DUE' }, { id: 3, status: 'COMING' }];
    const freshlySorted = [{ id: 2, status: 'DUE' }, { id: 3, status: 'COMING' }, { id: 1, status: 'FRESH' }, { id: 4 }];

    expect(preserveTaskOrder(previous, freshlySorted).map((task) => task.id)).toEqual([1, 2, 3, 4]);
  });

  it('groups rooms alphabetically and preserves status-sorted task order inside them', () => {
    const tasks = [
      { id: 1, room: 'Sypialnia', status: 'DEAD' },
      { id: 2, room: 'Kuchnia', status: 'DEAD' },
      { id: 3, room: 'Kuchnia', status: 'OVERDUE' },
      { id: 4, room: 'Łazienka', status: 'DUE' },
      { id: 5, room: '', status: 'FRESH' },
    ];

    expect(groupTasksByRoom(tasks).map((group) => ({
      room: group.room,
      ids: group.tasks.map((task) => task.id),
    }))).toEqual([
      { room: 'Kuchnia', ids: [2, 3] },
      { room: 'Łazienka', ids: [4] },
      { room: 'Sypialnia', ids: [1] },
      { room: 'Bez pokoju', ids: [5] },
    ]);
  });

  it('groups categories alphabetically and puts missing categories last', () => {
    const tasks = [
      { id: 1, category: 'Podłogi' },
      { id: 2, category: 'Kurz' },
      { id: 3, category: 'Podłogi' },
      { id: 4, category: '' },
    ];

    expect(groupTasksByCategory(tasks).map((group) => ({
      category: group.category,
      ids: group.tasks.map((task) => task.id),
    }))).toEqual([
      { category: 'Kurz', ids: [2] },
      { category: 'Podłogi', ids: [1, 3] },
      { category: 'Bez kategorii', ids: [4] },
    ]);
  });
});
