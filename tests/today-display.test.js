import { describe, expect, it, vi } from 'vitest';

vi.mock('../js/cleaning-apartments.js', () => ({
  getActiveCleaningApartmentId: () => 'aleja-pokoju6',
  getCleaningApartmentHistoryKey: (key) => `${key}.aleja-pokoju6`,
}));
import { ankiGoal, availableCleaningTasks, completionPercent, pendingSupplements, readingGoal, remaining, workoutGoal } from '../js/today-display.js';

describe('today display remaining counts', () => {
  it('clamps finished goals at zero', () => {
    expect(remaining(11000, 10000)).toBe(0);
    expect(readingGoal({ todayTarget: 20, todayRead: 8 })).toEqual({ target: 20, done: 8, left: 12 });
    expect(completionPercent(6000, 10000)).toBe(60);
    expect(completionPercent(11000, 10000)).toBe(100);
    expect(completionPercent(0, 0)).toBe(0);
  });

  it('counts outstanding Anki cards from the shared daily plan', () => {
    expect(ankiGoal([{ name: 'Norwegian', reviewsCompletedToday: 4, newCompletedToday: 1,
      reviewsPlannedToday: 10, newPlannedToday: 5 }])).toEqual({ target: 15, done: 5, left: 10 });
  });

  it('shows only supplements scheduled for today and still untaken', () => {
    expect(pendingSupplements([
      { displayName: 'Kreatyna', due: true, status: 'NO_ENTRY' },
      { displayName: 'Już przyjęty', due: true, status: 'TAKEN' },
      { displayName: 'Inny dzień', due: false, status: 'NO_ENTRY' },
    ])).toEqual(['Kreatyna']);
  });

  it('reduces workout minutes from finished sessions and honors completion', () => {
    const plan = { schedule: [{ date: '2026-10-01', type: 'base', duration: 30,
      zones: { light: 10, intensive: 20, aerobic: 0 } }] };
    const session = { status: 'finished', plan_date: '2026-10-01', duration_seconds: 600 };
    expect(workoutGoal(plan, [session], {}, '2026-10-01')).toMatchObject({ left: 20, state: 'pending', detail: 'Baza tlenowa' });
    expect(workoutGoal(plan, [session], {}, '2026-10-01').zones).toEqual([
      { key: 'light', color: '#3b82f6', minutes: 10 },
      { key: 'intensive', color: '#10b981', minutes: 20 },
    ]);
    expect(workoutGoal(plan, [session], { '2026-10-01': 'completed' }, '2026-10-01')).toMatchObject({ left: 0, state: 'done' });
  });

  it('lists available cleaning tasks and excludes blocked or already finished tasks', () => {
    expect(availableCleaningTasks([
      { row: 1, task: 'Zrobione', nextDueIn: 0 },
      { row: 2, task: 'Odkurzyć', room: 'Salon', category: 'Przetarcie kurzu', nextDueIn: 0 },
      { row: 3, task: 'Umyć zlew', room: 'Kuchnia', category: 'Inne', overdue: true, daysSince: 3, freq: 2 },
      { row: 4, task: 'Zablokowane', blocked: true, nextDueIn: 0 },
    ], [{ row: 1 }])).toEqual([
      { name: 'Odkurzyć', room: 'Salon', status: 'DUE' },
      { name: 'Umyć zlew', room: 'Kuchnia', status: 'OVERDUE' },
    ]);
  });
});
