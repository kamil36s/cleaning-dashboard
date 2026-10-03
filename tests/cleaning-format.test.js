import { describe, expect, it } from 'vitest';
import {
  formatCleaningDate,
  formatCleaningDateWithWeekday,
  parseCleaningDateInput,
} from '../js/cleaning-format.js';

describe('cleaning date format', () => {
  it('always displays a full dd/mm/yyyy date', () => {
    const date = new Date(2026, 7, 5, 12, 0, 0);
    expect(formatCleaningDate(date)).toBe('05/08/2026');
    expect(formatCleaningDateWithWeekday(date)).toMatch(/05\/08\/2026$/);
  });

  it('converts valid form input to the ISO API value', () => {
    expect(parseCleaningDateInput('05/08/2026')).toBe('2026-08-05');
    expect(parseCleaningDateInput('')).toBeNull();
  });

  it('rejects ambiguous and impossible dates', () => {
    expect(() => parseCleaningDateInput('08/05/26')).toThrow(/dd\/mm\/yyyy/);
    expect(() => parseCleaningDateInput('31/02/2026')).toThrow(/nie istnieje/);
  });
});
