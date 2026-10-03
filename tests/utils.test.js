import { describe, it, expect } from 'vitest';
import { bust, escapeHtml, fmtDateShort } from '../js/utils.js';

describe('HTML escaping (WHY: dynamic values are rendered inside HTML templates)', () => {
  it('escapes every character that can break out of text or an attribute', () => {
    expect(escapeHtml(`<script data-x="'">&`)).toBe(
      '&lt;script data-x=&quot;&#39;&quot;&gt;&amp;'
    );
  });

  it('normalizes nullish values without changing ordinary text', () => {
    expect(escapeHtml(null)).toBe('');
    expect(escapeHtml('Zażółć gęślą')).toBe('Zażółć gęślą');
  });
});

describe('Cache busting (WHY: avoid stale widget data)', () => {
  it('adds _= with the correct separator', () => {
    const noQuery = bust('https://example.com/api');
    expect(noQuery).toMatch(/\?_=\d+$/);

    const withQuery = bust('https://example.com/api?x=1');
    expect(withQuery).toMatch(/&_=\d+$/);
  });
});

describe('Date formatting (WHY: UI shows stable fallback)', () => {
  it('returns the same placeholder for empty and invalid dates', () => {
    const placeholder = fmtDateShort(null);
    expect(fmtDateShort('not-a-date')).toBe(placeholder);
  });

  it('returns a non-placeholder string for valid dates', () => {
    const placeholder = fmtDateShort(null);
    const out = fmtDateShort('2026-02-07');
    expect(out).not.toBe(placeholder);
    expect(out).toContain('2026');
  });
});
