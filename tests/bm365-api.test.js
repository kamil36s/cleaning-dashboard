import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  BM365_API_BASE,
  getBm365Albums,
  getBm365State,
  markBm365Listened,
  rateBm365Album,
  updateBm365Metadata,
} from '../js/bm365-api.js';

describe('local BM365 API client', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, rows: [] }),
    });
  });

  it('reads state and albums only from local REST routes', async () => {
    await getBm365State('2026-08-27');
    await getBm365Albums({ sort: 'rating_desc', rated: true });

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      `${BM365_API_BASE}/state?today=2026-08-27`,
      `${BM365_API_BASE}/albums?sort=rating_desc&rated=true`,
    ]);
  });

  it('uses local writes for listening, rating, and metadata', async () => {
    await markBm365Listened({ rowId: 12, date: '2026-01-11', listened: true });
    await rateBm365Album({ rowId: 12, artist: 'Mgła', album: 'Exercises in Futility', rating: 4.5 });
    await updateBm365Metadata(12, { year: 2015, description: 'Opis.' });

    expect(fetch.mock.calls.map(([url, options]) => [url, options.method])).toEqual([
      [`${BM365_API_BASE}/mark`, 'POST'],
      [`${BM365_API_BASE}/rate`, 'POST'],
      [`${BM365_API_BASE}/albums/12/metadata`, 'PATCH'],
    ]);
    expect(JSON.parse(fetch.mock.calls[1][1].body).rating).toBe(4.5);
  });
});
