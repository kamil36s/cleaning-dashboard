import { describe, expect, it } from 'vitest';
import calendar from '../data/polish-namedays.json';
import { namedayLabel, namedaysForDate } from '../js/kitchen-namedays.js';

describe('offline Kitchen namedays', () => {
  it('covers every date, including 29 February', () => {
    expect(Object.keys(calendar.days)).toHaveLength(366);
    expect(Object.values(calendar.days).every((names) => names.length > 0)).toBe(true);
    expect(namedaysForDate(new Date(2024, 1, 29))).toContain('Roman');
  });

  it('shows the same local names without a weather response', () => {
    expect(namedayLabel(new Date(2026, 9, 1))).toBe('Imieniny: Danuta, Remigiusz, Cieszysław');
  });
});
