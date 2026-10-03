import { describe, expect, it, vi } from 'vitest';
import { financePrivacyPlugin } from '../vite.config.js';

describe('Phone Tracker static privacy', () => {
  it.each(['/data/phone-tracker.sqlite','/data/phone-tracker.sqlite-wal',
    '/data/phone-tracker.sqlite-shm','/cleaning-dashboard/data/phone-tracker.sqlite-wal'])
  ('denies %s through the Vite middleware', (path) => {
    let middleware;
    financePrivacyPlugin().configureServer({ middlewares: { use: (fn) => { middleware = fn; } } });
    const response = { statusCode: 200, end: vi.fn() };
    const next = vi.fn();
    middleware({ url: path }, response, next);
    expect(response.statusCode).toBe(404);
    expect(response.end).toHaveBeenCalled();
    expect(next).not.toHaveBeenCalled();
  });
});
