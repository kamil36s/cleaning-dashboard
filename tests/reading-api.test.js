import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createReadingBook,
  fetchReadingBooks,
  fetchReadingHistory,
  fetchReadingSettings,
  fetchReadingState,
  saveReadingHistory,
  saveReadingSettings,
  updateReadingBook,
  updateReadingBookProgress,
} from '../js/reading-api.js';


function response(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Bad Request',
    json: vi.fn().mockResolvedValue(payload),
  };
}


describe('reading API adapter', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(response({ ok: true }));
  });

  it('uses the local reading endpoints', async () => {
    await fetchReadingState();
    await fetchReadingBooks();
    await fetchReadingHistory();
    await fetchReadingSettings();

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/reading/state',
      '/api/reading/books',
      '/api/reading/history',
      '/api/reading/settings',
    ]);
  });

  it('creates books and updates progress with JSON requests', async () => {
    await createReadingBook({ title: 'Tytuł', author: 'Autor', pagesTotal: 100 });
    await updateReadingBook('book/id', { title: 'Nowy tytuł', author: 'Autor', pagesTotal: 120 });
    await updateReadingBookProgress('book/id', 42, { recordHistory: false });

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/reading/books', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ title: 'Tytuł', author: 'Autor', pagesTotal: 100 }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/reading/books/book%2Fid', expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ title: 'Nowy tytuł', author: 'Autor', pagesTotal: 120 }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(3, '/api/reading/books/book%2Fid/progress', expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ pageCurrent: 42, recordHistory: false }),
    }));
  });

  it('saves history and settings through their canonical endpoints', async () => {
    await saveReadingHistory({ log: {}, startKey: '', forecastPlan: null });
    await saveReadingSettings({ activeMap: {} });

    expect(fetch.mock.calls.map(([url, options]) => [url, options.method])).toEqual([
      ['/api/reading/history', 'POST'],
      ['/api/reading/settings', 'POST'],
    ]);
  });

  it('surfaces backend validation errors', async () => {
    fetch.mockResolvedValueOnce(response({ error: 'Book not found', code: 'book_not_found' }, { ok: false, status: 404 }));
    await expect(updateReadingBookProgress('missing', 2)).rejects.toMatchObject({
      message: 'Book not found',
      code: 'book_not_found',
      status: 404,
    });
  });
});
