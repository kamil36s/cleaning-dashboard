import { describe, expect, it } from 'vitest';

import { formatReadingDate, parseReadingDateInput } from '../js/reading-date.js';

describe('reading date format', () => {
  it('always displays complete dates as dd/mm/yyyy', () => {
    expect(formatReadingDate('2026-09-03')).toBe('03/09/2026');
    expect(formatReadingDate('2026-09-03T22:00:00.000Z')).toBe('03/09/2026');
  });

  it('converts a valid dd/mm/yyyy form value to the API format', () => {
    expect(parseReadingDateInput('15/04/2099')).toBe('2099-04-15');
    expect(parseReadingDateInput('5/4/2099')).toBe('2099-04-05');
    expect(parseReadingDateInput('')).toBe('');
  });

  it('rejects other formats and impossible dates', () => {
    expect(() => parseReadingDateInput('2099-04-15')).toThrow('dd/mm/yyyy');
    expect(() => parseReadingDateInput('31/02/2026')).toThrow('nieprawidłowa');
  });
});
