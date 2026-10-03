import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../js/reading-api.js', () => ({
  fetchReadingHistory: vi.fn(() => Promise.resolve(null)),
  saveReadingHistory: vi.fn(() => Promise.resolve()),
  fetchReadingSettings: vi.fn(() => Promise.resolve(null)),
  saveReadingSettings: vi.fn(() => Promise.resolve()),
}));
import {
  buildReadingHistorySeries,
  loadReadingLog,
  recordReadingProgress,
} from '../js/reading-history.js';

const day = (y, m, d) => new Date(y, m - 1, d, 12, 0, 0, 0);

describe('Reading history dedup', () => {
  beforeEach(() => {
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.clear();
    }
  });

  it('replaces duplicate progress labels for the same book with one canonical entry', () => {
    const now = day(2026, 3, 21);
    const titleOnly = 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym';
    const fullLabel = 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym - Christophe Andre, Patrick Legeron, Antoine Pelissolo';

    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-21': {
        total: 120,
        progress: {
          [titleOnly]: {
            label: titleOnly,
            start: 0,
            current: 120,
          },
          [fullLabel]: {
            label: fullLabel,
            start: 120,
            current: 120,
          },
        },
      },
    }));

    recordReadingProgress({
      baselinePages: 120,
      currentPages: 138,
      visiblePages: 120,
      dateKey: '2026-03-21',
      meta: {
        bookTitle: 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym',
        bookAuthor: 'Christophe Andre, Patrick Legeron, Antoine Pelissolo',
      },
    });

    const todayEntry = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now })
      .find((item) => item.dayKey === '2026-03-21');
    const rawLog = loadReadingLog()['2026-03-21'];

    expect(todayEntry?.count).toBe(18);
    expect(todayEntry?.books).toEqual([
      {
        label: fullLabel,
        count: 18,
      },
    ]);
    expect(Object.keys(rawLog.progress || {})).toEqual([
      'book:lek przed innymi. jak radzic sobie z lekiem spolecznym|christophe andre, patrick legeron, antoine pelissolo',
    ]);
  });
});
