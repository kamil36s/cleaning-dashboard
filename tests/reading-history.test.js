import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../js/reading-api.js', () => ({
  fetchReadingHistory: vi.fn(() => Promise.resolve(null)),
  saveReadingHistory: vi.fn(() => Promise.resolve()),
  fetchReadingSettings: vi.fn(() => Promise.resolve(null)),
  saveReadingSettings: vi.fn(() => Promise.resolve()),
}));
import {
  applyLekMarch20ResetFix,
  applyNiegrzeczneLogFix,
  applyWladcyChaosuLogFix,
  buildReadingForecastSeries,
  buildReadingHistorySeries,
  buildReadingTargetSeries,
  captureReadingLogBookSnapshot,
  getLocalReadingStats,
  loadReadingLog,
  reconcileTodayReadingLogWithBooks,
  recordReadingProgress,
  restoreReadingLogBookSnapshot,
  resetReadingTodayForecastPlan,
  stabilizeLegacyTodayRemoteProgress,
  summarizeReadingHistory,
} from '../js/reading-history.js';

const day = (y, m, d) => new Date(y, m - 1, d, 12, 0, 0, 0);

describe('Reading history analytics', () => {
  beforeEach(() => {
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.clear();
    }
  });

  it('builds daily history series for the selected window', () => {
    const now = day(2026, 3, 13);
    const log = {
      '2026-03-13': {
        total: 22,
        books: {
          'Solaris - Stanisław Lem': 12,
          'Diuna - Frank Herbert': 10,
        },
      },
      '2026-03-12': 10,
      '2026-03-09': 7,
      '2026-02-28': 99,
    };

    const series = buildReadingHistorySeries(log, { range: 'week', now });
    const map = new Map(series.map((item) => [item.dayKey, item.count]));
    const todayEntry = series.find((item) => item.dayKey === '2026-03-13');

    expect(series).toHaveLength(7);
    expect(map.get('2026-03-13')).toBe(22);
    expect(map.get('2026-03-12')).toBe(10);
    expect(map.get('2026-03-09')).toBe(7);
    expect(map.get('2026-03-11')).toBe(0);
    expect(todayEntry?.books).toEqual([
      { label: 'Solaris - Stanisław Lem', count: 12 },
      { label: 'Diuna - Frank Herbert', count: 10 },
    ]);
  });

  it('merges duplicate entries for the same book into one segment', () => {
    const now = day(2026, 3, 13);
    const log = {
      '2026-03-13': {
        total: 22,
        books: {
          'Solaris - Stanisław Lem': 5,
          'Solaris — Stanisław Lem': 7,
          'Diuna - Frank Herbert': 10,
        },
      },
    };

    const series = buildReadingHistorySeries(log, { range: 'week', now });
    const todayEntry = series.find((item) => item.dayKey === '2026-03-13');

    expect(todayEntry?.books).toEqual([
      { label: 'Solaris - Stanisław Lem', count: 12 },
      { label: 'Diuna - Frank Herbert', count: 10 },
    ]);
  });

  it('builds forecast targets for future windows', () => {
    const now = day(2026, 3, 13);
    const books = [
      { title: 'Solaris', pagesTotal: 120, pagesRead: 70, dueDate: '2026-03-18' },
      { title: 'Diuna', pagesTotal: 200, pagesRead: 191, dueDate: '2026-03-16' },
    ];

    const series = buildReadingForecastSeries(books, {
      range: 'week',
      offset: 1,
      now,
    });
    const map = new Map(series.map((item) => [item.dayKey, item.count]));
    const march16 = series.find((item) => item.dayKey === '2026-03-16');

    expect(series).toHaveLength(7);
    expect(map.get('2026-03-16')).toBe(10);
    expect(map.get('2026-03-17')).toBe(10);
    expect(map.get('2026-03-18')).toBe(0);
    expect(map.get('2026-03-22')).toBe(0);
    expect(march16?.books).toEqual([
      { label: 'Solaris', count: 10 },
    ]);
  });

  it('keeps today frozen and updates only future forecast days', () => {
    const now = day(2026, 3, 13);
    const books = [
      { title: 'Solaris', pagesTotal: 120, pagesRead: 85, dueDate: '2026-03-18' },
    ];
    const log = {
      '2026-03-13': {
        total: 15,
        books: {
          Solaris: 15,
        },
      },
    };

    const series = buildReadingForecastSeries(books, {
      range: 'month',
      now,
      log,
      todayPlan: {
        Solaris: 10,
      },
    });
    const map = new Map(series.map((item) => [item.dayKey, item.count]));

    expect(map.get('2026-03-13')).toBe(10);
    expect(map.get('2026-03-14')).toBe(9);
    expect(map.get('2026-03-15')).toBe(9);
    expect(map.get('2026-03-16')).toBe(9);
    expect(map.get('2026-03-17')).toBe(8);
  });

  it('resets the frozen daily reading forecast plan', () => {
    window.localStorage.setItem('readingDailyLog.v2', '{}');
    window.localStorage.setItem('readingForecastPlan.v1', JSON.stringify({
      dayKey: '2026-03-13',
      books: {
        Solaris: { label: 'Solaris', count: 10 },
      },
    }));

    resetReadingTodayForecastPlan();

    expect(window.localStorage.getItem('readingForecastPlan.v1')).toBeNull();
    expect(window.localStorage.getItem('readingDailyLog.v2')).toBe('{}');
  });

  it('reconstructs past daily reading targets and keeps today on the frozen plan', () => {
    const now = day(2026, 3, 26);
    const books = [
      {
        key: 'solaris',
        title: 'Solaris',
        author: 'Stanisław Lem',
        pagesTotal: 120,
        pagesRead: 90,
        dueDate: '2026-03-28',
      },
    ];
    const log = {
      '2026-03-24': {
        total: 10,
        books: {
          'Solaris - Stanisław Lem': 10,
        },
      },
      '2026-03-25': {
        total: 10,
        books: {
          'Solaris - Stanisław Lem': 10,
        },
      },
      '2026-03-26': {
        total: 10,
        books: {
          'Solaris - Stanisław Lem': 10,
        },
      },
    };

    const series = buildReadingTargetSeries(books, {
      range: 'week',
      now,
      log,
      todayPlan: {
        solaris: 12,
      },
    });
    const map = new Map(series.map((item) => [item.dayKey, item.count]));

    expect(map.get('2026-03-24')).toBe(15);
    expect(map.get('2026-03-25')).toBe(17);
    expect(map.get('2026-03-26')).toBe(12);
  });

  it('aligns month windows to full calendar month', () => {
    const now = day(2026, 3, 13);
    const log = {
      '2026-03-01': 8,
      '2026-03-13': 22,
      '2026-03-31': 11,
      '2026-02-28': 99,
    };

    const series = buildReadingHistorySeries(log, { range: 'month', now });

    expect(series).toHaveLength(31);
    expect(series[0]?.dayKey).toBe('2026-03-01');
    expect(series[series.length - 1]?.dayKey).toBe('2026-03-31');
    expect(series.find((item) => item.dayKey === '2026-03-13')?.count).toBe(22);
    expect(series.find((item) => item.dayKey === '2026-03-31')?.count).toBe(11);
  });

  it('summarizes totals, averages and streak', () => {
    const now = day(2026, 3, 13);
    const log = {
      '2026-03-13': 20,
      '2026-03-12': 10,
      '2026-03-11': 5,
      '2026-03-01': 25,
      '2026-01-15': 40,
      '2025-04-01': 12,
    };

    const summary = summarizeReadingHistory(log, { now });

    expect(summary.today).toBe(20);
    expect(summary.weekTotal).toBe(35);
    expect(summary.monthTotal).toBe(60);
    expect(summary.quarterTotal).toBe(100);
    expect(summary.yearTotal).toBe(112);
    expect(summary.streak).toBe(3);
    expect(summary.bestDay?.dayKey).toBe('2026-01-15');
    expect(summary.bestDay?.count).toBe(40);
  });

  it('treats page corrections as corrections, not extra pages read', () => {
    const now = day(2026, 3, 16);
    const meta = {
      bookTitle: 'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia',
      bookAuthor: 'Michael Moyniham, Didrik Søderlind',
    };

    recordReadingProgress({
      baselinePages: 255,
      currentPages: 265,
      dateKey: '2026-03-16',
      meta,
    });
    recordReadingProgress({
      baselinePages: 265,
      currentPages: 255,
      dateKey: '2026-03-16',
      meta,
    });
    recordReadingProgress({
      baselinePages: 255,
      currentPages: 256,
      dateKey: '2026-03-16',
      meta,
    });

    const series = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now });
    const todayEntry = series.find((item) => item.dayKey === '2026-03-16');
    const stats = getLocalReadingStats({ now });

    expect(todayEntry?.count).toBe(1);
    expect(todayEntry?.books).toEqual([
      {
        label: 'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik Søderlind',
        count: 1,
      },
    ]);
    expect(stats.todayRead).toBe(1);
  });

  it('preserves earlier legacy bars and lets down-then-up edits rebuild the current book', () => {
    const now = day(2026, 3, 16);
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-16': {
        total: 11,
        books: {
          'Lęk przed innymi - Christophe André': 11,
        },
      },
    }));

    recordReadingProgress({
      baselinePages: 80,
      currentPages: 57,
      dateKey: '2026-03-16',
      meta: {
        bookTitle: 'Władcy Chaosu',
        bookAuthor: 'Michael Moyniham',
      },
    });
    recordReadingProgress({
      baselinePages: 57,
      currentPages: 80,
      dateKey: '2026-03-16',
      meta: {
        bookTitle: 'Władcy Chaosu',
        bookAuthor: 'Michael Moyniham',
      },
    });

    const todayEntry = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now })
      .find((item) => item.dayKey === '2026-03-16');

    expect(todayEntry?.count).toBe(34);
    expect(todayEntry?.books).toEqual([
      { label: 'Władcy Chaosu - Michael Moyniham', count: 23 },
      { label: 'Lęk przed innymi - Christophe André', count: 11 },
    ]);
  });
  it('resets a stale progress baseline when visible page is lower than stored current', () => {
    const now = day(2026, 3, 20);
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-20': {
        total: 124,
        books: {
          'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo': 124,
        },
        progress: {
          'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo': {
            label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
            start: 0,
            current: 124,
          },
        },
      },
    }));

    recordReadingProgress({
      baselinePages: 120,
      currentPages: 133,
      visiblePages: 120,
      dateKey: '2026-03-20',
      meta: {
        bookTitle: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
        bookAuthor: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
      },
    });

    const todayEntry = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now })
      .find((item) => item.dayKey === '2026-03-20');

    expect(todayEntry?.count).toBe(13);
    expect(todayEntry?.books).toEqual([
      {
        label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
        count: 13,
      },
    ]);
  });

  it.skip('reuses a title-only progress entry instead of double counting the same book', () => {
    const now = day(2026, 3, 21);
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-21': {
        total: 120,
        books: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym': 120,
        },
        progress: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym': {
            label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
            start: 0,
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
        bookTitle: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
        bookAuthor: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
      },
    });

    const todayEntry = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now })
      .find((item) => item.dayKey === '2026-03-21');

    expect(todayEntry?.count).toBe(18);
    expect(todayEntry?.books).toEqual([
      {
        label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
        count: 18,
      },
    ]);
  });

  it('replaces a legacy title-only book count when the same save now uses title plus author', () => {
    const now = day(2026, 3, 21);
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-21': {
        total: 120,
        books: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym': 120,
        },
      },
    }));

    recordReadingProgress({
      baselinePages: 120,
      currentPages: 138,
      visiblePages: 120,
      dateKey: '2026-03-21',
      meta: {
        bookTitle: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
        bookAuthor: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
      },
    });

    const todayEntry = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now })
      .find((item) => item.dayKey === '2026-03-21');

    expect(todayEntry?.count).toBe(18);
    expect(todayEntry?.books).toEqual([
      {
        label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo',
        count: 18,
      },
    ]);
  });

  it('matches a dirty legacy title-only entry without Polish characters to the same book', () => {
    const now = day(2026, 3, 21);
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-21': {
        total: 120,
        books: {
          'Lek przed innymi Jak radzic sobie z lekiem spolecznym': 120,
        },
      },
    }));

    recordReadingProgress({
      baselinePages: 120,
      currentPages: 138,
      visiblePages: 120,
      dateKey: '2026-03-21',
      meta: {
        bookTitle: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
        bookAuthor: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
      },
    });

    const todayEntry = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now })
      .find((item) => item.dayKey === '2026-03-21');

    expect(todayEntry?.count).toBe(18);
    expect(todayEntry?.books).toEqual([
      {
        label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo',
        count: 18,
      },
    ]);
  });

  it.skip('drops duplicate progress entries for the same book before saving a new page', () => {
    const now = day(2026, 3, 21);
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-21': {
        total: 120,
        progress: {
          'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym': {
        label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
            start: 0,
            current: 120,
          },
          'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo': {
            label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
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
        bookTitle: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
        bookAuthor: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
      },
    });

    const todayEntry = buildReadingHistorySeries(loadReadingLog(), { range: 'week', now })
      .find((item) => item.dayKey === '2026-03-21');
    const rawLog = loadReadingLog()['2026-03-21'];

    expect(todayEntry?.count).toBe(18);
    expect(todayEntry?.books).toEqual([
      {
        label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
        count: 18,
      },
    ]);
    expect(Object.keys(rawLog.progress || {})).toEqual([
      'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
    ]);
  });

  it('relabels legacy unknown reading entries to Wladcy Chaosu as a one-off fix', () => {
    const fixed = applyWladcyChaosuLogFix({
      '2026-03-15': {
        total: 14,
      },
      '2026-03-16': {
        total: 9,
        books: {
          'Nieznana książka': 4,
          'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik Søderlind': 5,
        },
      },
    });

    expect(fixed.changed).toBe(true);
    expect(fixed.log['2026-03-15']?.books).toEqual({
      'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik Søderlind': 14,
    });
    expect(fixed.log['2026-03-16']?.books).toEqual({
      'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik Søderlind': 9,
    });
  });

  it('backfills Niegrzeczne evenly from 13 Jan to 5 Feb 2026', () => {
    const fixed = applyNiegrzeczneLogFix({
      '2026-01-15': {
        total: 6,
        books: {
          'Inna książka - Autor': 6,
        },
      },
    }, '2026-03-01');

    const entries = Object.entries(fixed.log)
      .filter(([key]) => key >= '2026-01-13' && key <= '2026-02-05');
    const importedTotal = entries.reduce((sum, [, entry]) => (
      sum + (Number(entry.books?.['Niegrzeczne: Historie dzieci z ADHD, autyzmem i zespołem Aspergera - Jacek Hołub']) || 0)
    ), 0);

    expect(fixed.changed).toBe(true);
    expect(fixed.nextStartKey).toBe('2026-01-13');
    expect(entries).toHaveLength(24);
    expect(importedTotal).toBe(226);
    expect(fixed.log['2026-01-15']?.books).toEqual({
      'Inna książka - Autor': 6,
      'Niegrzeczne: Historie dzieci z ADHD, autyzmem i zespołem Aspergera - Jacek Hołub': 10,
    });
    expect(Number(fixed.log['2026-01-13']?.books?.['Niegrzeczne: Historie dzieci z ADHD, autyzmem i zespołem Aspergera - Jacek Hołub']) || 0).toBeGreaterThan(0);
    expect(Number(fixed.log['2026-02-05']?.books?.['Niegrzeczne: Historie dzieci z ADHD, autyzmem i zespołem Aspergera - Jacek Hołub']) || 0).toBeGreaterThan(0);
  });

  it('removes canonical Lęk progress entries during the 20 March reset fix', () => {
    const fixed = applyLekMarch20ResetFix({
      '2026-03-20': {
        total: 120,
        books: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo': 120,
        },
        progress: {
          'remote:lek_spoleczny': {
            key: 'remote:lek_spoleczny',
            bookKey: 'remote:lek_spoleczny',
            label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo',
            title: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
            author: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
            start: 0,
            current: 120,
          },
        },
      },
    });

    expect(fixed.changed).toBe(true);
    expect(fixed.log['2026-03-20']).toBeUndefined();
  });

  it('reconciles today progress with lower remote pages after an external rollback', () => {
    const repaired = stabilizeLegacyTodayRemoteProgress([
      {
        title: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
        author: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
        pagesRead: 120,
      },
    ], {
      now: day(2026, 3, 20),
      log: {
        '2026-03-20': {
          total: 124,
          books: {
            'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo': 124,
          },
          progress: {
            'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo': {
              label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo',
              start: 0,
              current: 124,
            },
          },
        },
      },
    });

    expect(repaired.changed).toBe(true);
    expect(repaired.log).toEqual({});
  });

  it('removes only Lęk from the local bar on 20 March 2026', () => {
    const fixed = applyLekMarch20ResetFix({
      '2026-03-20': {
        total: 135,
        books: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo': 124,
          'Władcy Chaosu - Michael Moyniham': 11,
        },
        progress: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo': {
            label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo',
            start: 0,
            current: 124,
          },
        },
      },
    });

    expect(fixed.changed).toBe(true);
    expect(fixed.log['2026-03-20']).toEqual({
      total: 11,
      books: {
        'Władcy Chaosu - Michael Moyniham': 11,
      },
      progress: {},
    });
  });
  it('resets stale canonical progress baseline when a legacy entry already equals the visible page', () => {
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-20': {
        total: 120,
        books: {
          'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo': 120,
        },
        progress: {
          'remote:lek_spoleczny': {
            key: 'remote:lek_spoleczny',
            bookKey: 'remote:lek_spoleczny',
            label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
            title: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
            author: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
            start: 0,
            current: 120,
          },
        },
      },
    }));

    recordReadingProgress({
      baselinePages: 120,
      currentPages: 138,
      visiblePages: 120,
      dateKey: '2026-03-20',
      meta: {
        bookKey: 'remote:lek_spoleczny',
        bookId: 'lek_spoleczny',
        bookTitle: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
        bookAuthor: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
      },
    });

    const todayEntry = loadReadingLog()['2026-03-20'];
    expect(todayEntry.total).toBe(18);
    expect(todayEntry.progress['remote:lek_spoleczny'].start).toBe(120);
    expect(todayEntry.progress['remote:lek_spoleczny'].trackingVersion).toBe(2);
  });

  it('keeps accumulating progress across multiple saves created by the new tracker', () => {
    recordReadingProgress({
      baselinePages: 0,
      currentPages: 120,
      visiblePages: 0,
      dateKey: '2026-03-20',
      meta: {
        bookKey: 'remote:lek_spoleczny',
        bookId: 'lek_spoleczny',
        bookTitle: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
        bookAuthor: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
      },
    });

    recordReadingProgress({
      baselinePages: 120,
      currentPages: 138,
      visiblePages: 120,
      dateKey: '2026-03-20',
      meta: {
        bookKey: 'remote:lek_spoleczny',
        bookId: 'lek_spoleczny',
        bookTitle: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
        bookAuthor: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
      },
    });

    const todayEntry = loadReadingLog()['2026-03-20'];
    expect(todayEntry.total).toBe(138);
    expect(todayEntry.progress['remote:lek_spoleczny'].start).toBe(0);
    expect(todayEntry.progress['remote:lek_spoleczny'].trackingVersion).toBe(2);
  });

  it('does not remove a different book when the saved title is a word inside another title', () => {
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-07-08': {
        total: 30,
        books: {
          'Florencja: Od Dantego do Galileusza - Paul Strathern': 30,
        },
        progress: {
          'remote:florencja': {
            key: 'remote:florencja',
            bookKey: 'remote:florencja',
            label: 'Florencja: Od Dantego do Galileusza - Paul Strathern',
            title: 'Florencja: Od Dantego do Galileusza',
            author: 'Paul Strathern',
            start: 112,
            current: 142,
            trackingVersion: 2,
            saveCount: 1,
          },
        },
      },
    }));

    recordReadingProgress({
      baselinePages: 22,
      currentPages: 34,
      visiblePages: 22,
      dateKey: '2026-07-08',
      meta: {
        bookKey: 'remote:dante',
        bookId: 'dante',
        bookTitle: 'Dante',
        bookAuthor: 'Alessandro Barbero',
      },
    });

    const todayEntry = loadReadingLog()['2026-07-08'];
    expect(todayEntry.total).toBe(42);
    expect(todayEntry.books).toEqual({
      'Dante - Alessandro Barbero': 12,
      'Florencja: Od Dantego do Galileusza - Paul Strathern': 30,
    });
    expect(Object.keys(todayEntry.progress || {}).sort()).toEqual([
      'remote:dante',
      'remote:florencja',
    ]);
  });

  it('restores only one book snapshot without deleting later pages from another book', () => {
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-03-20': {
        total: 20,
        books: {
          'Solaris - Stanislaw Lem': 20,
        },
        progress: {
          'book:solaris|stanislaw lem': {
            key: 'book:solaris|stanislaw lem',
            bookKey: 'book:solaris|stanislaw lem',
            label: 'Solaris - Stanislaw Lem',
            title: 'Solaris',
            author: 'Stanislaw Lem',
            start: 100,
            current: 120,
            trackingVersion: 2,
            saveCount: 1,
          },
        },
      },
    }));

    const snapshot = captureReadingLogBookSnapshot({
      dateKey: '2026-03-20',
      meta: {
        bookKey: 'book:solaris|stanislaw lem',
        bookTitle: 'Solaris',
        bookAuthor: 'Stanislaw Lem',
      },
    });

    recordReadingProgress({
      baselinePages: 120,
      currentPages: 140,
      visiblePages: 120,
      dateKey: '2026-03-20',
      meta: {
        bookKey: 'book:lek|autor',
        bookTitle: 'Lek',
        bookAuthor: 'Autor',
      },
    });
    recordReadingProgress({
      baselinePages: 120,
      currentPages: 121,
      visiblePages: 120,
      dateKey: '2026-03-20',
      meta: {
        bookKey: 'book:solaris|stanislaw lem',
        bookTitle: 'Solaris',
        bookAuthor: 'Stanislaw Lem',
      },
    });

    restoreReadingLogBookSnapshot({
      dateKey: '2026-03-20',
      meta: {
        bookKey: 'book:solaris|stanislaw lem',
        bookTitle: 'Solaris',
        bookAuthor: 'Stanislaw Lem',
      },
      snapshot,
    });

    const todayEntry = loadReadingLog()['2026-03-20'];
    expect(todayEntry.total).toBe(40);
    expect(todayEntry.books).toEqual({
      'Lek - Autor': 20,
      'Solaris - Stanislaw Lem': 20,
    });
  });

  it('stabilizes legacy remote progress without saveCount to the current remote page on startup', () => {
    const repaired = reconcileTodayReadingLogWithBooks([
      {
        book_id: 'lek_spoleczny',
        title: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
        author: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
        pagesRead: 120,
      },
    ], {
      now: day(2026, 3, 20),
      log: {
        '2026-03-20': {
          total: 120,
          books: {
            'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo': 120,
          },
          progress: {
            'remote:lek_spoleczny': {
              key: 'remote:lek_spoleczny',
              bookKey: 'remote:lek_spoleczny',
              label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
              title: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
              author: 'Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
              start: 0,
              current: 120,
            },
          },
        },
      },
    });

    expect(repaired.changed).toBe(true);
    expect(repaired.log['2026-03-20']).toBeUndefined();
  });
});
