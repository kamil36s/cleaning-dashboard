import { describe, expect, it, vi } from 'vitest';
import { financePrivacyPlugin } from '../vite.config.js';

describe('Language private static paths', () => {
  it.each([
    '/data/language-learning.sqlite',
    '/data/language-learning.sqlite-wal',
    '/data/language-learning/media/owned.wav',
    '/data/audio/language-learning/nb/cloze/cached.mp3',
    '/data/reference/language-reference-nb.sqlite',
    '/data/reference/sources/private.tsv',
    '/data/backups/language-2026/manifest.json',
    '/language_learning/benchmark_content/v1.json',
    '/language_learning/service.py',
    '/.env.production',
    '/cleaning-dashboard/data/language-learning/media/owned.wav',
  ])('denies %s in dev and preview middleware', (url) => {
    for (const phase of ['configureServer', 'configurePreviewServer']) {
      let middleware;
      financePrivacyPlugin()[phase]({ middlewares: { use: (handler) => { middleware = handler; } } });
      const response = { end: vi.fn(), statusCode: 200 };
      const next = vi.fn();
      middleware({ url }, response, next);
      expect(response.statusCode).toBe(404);
      expect(next).not.toHaveBeenCalled();
    }
  });
});
