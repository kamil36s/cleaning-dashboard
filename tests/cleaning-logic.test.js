import { describe, it, expect } from 'vitest';
import { computeCounts, deriveStatus } from '../js/cleaning-logic.js';

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
});
