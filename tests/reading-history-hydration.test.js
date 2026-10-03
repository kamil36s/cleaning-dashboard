import { beforeEach, describe, expect, it, vi } from 'vitest';

const readingApi = vi.hoisted(() => ({
  fetchReadingHistory: vi.fn(),
  saveReadingHistory: vi.fn(() => Promise.resolve()),
  fetchReadingSettings: vi.fn(() => Promise.resolve(null)),
  saveReadingSettings: vi.fn(() => Promise.resolve()),
}));

vi.mock('../js/reading-api.js', () => readingApi);

describe('reading history hydration safety', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('does not let an empty browser profile overwrite file-backed history before hydration finishes', async () => {
    let resolveServer;
    readingApi.fetchReadingHistory.mockReturnValue(new Promise((resolve) => {
      resolveServer = resolve;
    }));

    const history = await import('../js/reading-history.js');
    history.getLocalReadingStats({ now: new Date(2026, 7, 20, 12) });

    expect(readingApi.saveReadingHistory).not.toHaveBeenCalled();

    const serverHistory = {
      log: {
        '2026-01-13': {
          total: 9,
          books: { 'Niegrzeczne - Jacek Hołub': 9 },
          progress: {},
        },
        '2026-08-18': {
          total: 43,
          books: { 'Głód - Knut Hamsun': 43 },
          progress: {},
        },
      },
      startKey: '2026-01-13',
      forecastPlan: null,
    };
    resolveServer(serverHistory);
    await vi.waitFor(() => {
      expect(history.loadReadingLog()['2026-08-18']?.total).toBe(43);
    });

    expect(window.localStorage.getItem('readingDailyLogStart.v2')).toBe('2026-01-13');
    expect(readingApi.saveReadingHistory).not.toHaveBeenCalled();
  });
});
