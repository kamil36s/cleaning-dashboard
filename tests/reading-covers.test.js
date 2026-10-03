import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  buildReadingCoverSearchQuery,
  dominantColorFromImageData,
  isReadingCoversEnabled,
  normalizeGoogleBooksImageUrl,
  openLibraryCoverUrlFromDoc,
  readingCoverLocalCandidates,
  readingCoverSlug,
  saveReadingCoverUpload,
  setReadingCoversEnabled,
} from '../js/reading-covers.js';

describe('Reading covers', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('keeps the cover feature enabled by default and persists the toggle', () => {
    expect(isReadingCoversEnabled()).toBe(true);

    setReadingCoversEnabled(false);
    expect(isReadingCoversEnabled()).toBe(false);

    setReadingCoversEnabled(true);
    expect(isReadingCoversEnabled()).toBe(true);
  });

  it('builds stable local cover candidates with the reading prefix', () => {
    const book = {
      title: 'Święty Franciszek z Asyżu',
      author: 'G.K. Chesterton',
    };

    expect(readingCoverSlug(book, 'remote:123')).toBe('reading--swiety-franciszek-z-asyzu--g-k-chesterton');
    expect(readingCoverLocalCandidates(book, 'remote:123')).toEqual([
      './covers/reading--swiety-franciszek-z-asyzu--g-k-chesterton.jpg',
      './covers/reading--swiety-franciszek-z-asyzu--g-k-chesterton.jpeg',
      './covers/reading--swiety-franciszek-z-asyzu--g-k-chesterton.png',
      './covers/reading--swiety-franciszek-z-asyzu--g-k-chesterton.webp',
    ]);
  });

  it('extracts Open Library cover URLs from cover IDs or ISBNs', () => {
    expect(openLibraryCoverUrlFromDoc({ cover_i: 12345 })).toBe('https://covers.openlibrary.org/b/id/12345-L.jpg?default=false');
    expect(openLibraryCoverUrlFromDoc({ isbn: ['9780141182636'] })).toBe('https://covers.openlibrary.org/b/isbn/9780141182636-L.jpg?default=false');
  });

  it('builds a Google Books query and normalizes image URLs', () => {
    expect(buildReadingCoverSearchQuery({
      title: 'A Clockwork Orange',
      author: 'Anthony Burgess',
    })).toBe('intitle:A Clockwork Orange inauthor:Anthony Burgess');
    expect(normalizeGoogleBooksImageUrl('http://books.google.com/cover.jpg')).toBe('https://books.google.com/cover.jpg');
  });

  it('finds the dominant usable cover color from sampled pixels', () => {
    const pixels = [];
    for (let i = 0; i < 20; i += 1) pixels.push(220, 20, 20, 255);
    for (let i = 0; i < 5; i += 1) pixels.push(40, 80, 210, 255);
    for (let i = 0; i < 5; i += 1) pixels.push(250, 250, 250, 255);

    expect(dominantColorFromImageData({ data: new Uint8ClampedArray(pixels) }, 1)).toBe('#dc1414');
  });

  it('prefers the shared disk cover over a stale browser-specific remote cache', async () => {
    vi.resetModules();
    localStorage.setItem('readingBookCoverCache.v1', JSON.stringify({
      'remote:wool': {
        url: 'https://example.test/green-wool.jpg',
        ts: Date.now(),
        source: 'remote',
      },
    }));
    const fetchSpy = vi.fn(async (url, options = {}) => {
      if (options.method === 'HEAD' && String(url).endsWith('reading--wool--hugh-howey.jpg')) {
        return {
          ok: true,
          headers: {
            get(name) {
              if (name.toLowerCase() === 'content-type') return 'image/jpeg';
              if (name.toLowerCase() === 'last-modified') return 'Fri, 11 Sep 2026 19:31:30 GMT';
              return null;
            },
          },
        };
      }
      return { ok: false, headers: { get: () => null } };
    });
    vi.stubGlobal('fetch', fetchSpy);
    window.fetch = fetchSpy;

    const { resolveReadingCover } = await import('../js/reading-covers.js');
    const url = await resolveReadingCover(
      { title: 'Wool', author: 'Hugh Howey' },
      'remote:wool',
    );

    expect(url).toMatch(/^\.\/covers\/reading--wool--hugh-howey\.jpg\?v=\d+$/);
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining('openlibrary.org'),
      expect.anything(),
    );
  });

  it('does not store uploaded cover image bytes in localStorage when disk save fails', async () => {
    const previousImage = globalThis.Image;
    class MockImage {
      constructor() {
        this.width = 10;
        this.height = 15;
        this.naturalWidth = 10;
        this.naturalHeight = 15;
      }

      set src(value) {
        this._src = value;
        setTimeout(() => this.onload?.(this), 0);
      }

      get src() {
        return this._src;
      }
    }
    globalThis.Image = MockImage;
    window.Image = MockImage;
    const fetchSpy = vi.fn(async () => ({ ok: false, json: async () => ({ error: 'no disk' }) }));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await expect(saveReadingCoverUpload(
      { title: 'Disk Only', author: 'Cache Test' },
      'remote:disk-only',
      new File(['cover'], 'cover.png', { type: 'image/png' }),
    )).rejects.toThrow('Lokalny serwer');

    expect(localStorage.getItem('readingBookCoverUploads.v1')).toBeNull();
    expect(localStorage.getItem('readingBookCoverCache.v1') || '').not.toContain('data:image/');

    globalThis.Image = previousImage;
    window.Image = previousImage;
  });
});
