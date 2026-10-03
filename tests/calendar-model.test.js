import { describe, it, expect } from 'vitest';
import { weekDays, shiftDay, expandEvent, layoutEvents, safeLink } from '../js/calendar-model.js';

describe('calendar dates and layout', () => {
  it('starts on Monday across year boundaries and daylight saving weekends', () => {
    expect(weekDays('2027-01-01')).toEqual(['2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31', '2027-01-01', '2027-01-02', '2027-01-03']);
    expect(shiftDay('2026-10-25', 1)).toBe('2026-10-26');
  });
  it('respects exclusive Google all-day end dates and clips to the week', () => {
    const items = expandEvent({ id: 'leave', date: '2026-09-25', title: 'L4', external: { start: { date: '2026-09-25' }, end: { date: '2026-10-03' } } }, weekDays('2026-10-01'));
    expect(items.map(e => e.day)).toEqual(['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02']);
    expect(items.every(e => e.start === null)).toBe(true);
  });
  it('splits overnight events without extending into another midnight', () => {
    const items = expandEvent({ id: 'night', date: '2026-10-01', startTime: '23:00', endTime: '01:30' }, weekDays('2026-10-01'));
    expect(items.map(e => [e.day, e.start, e.end])).toEqual([['2026-10-01', 1380, 1440], ['2026-10-02', 0, 90]]);
  });
  it('lays out chained overlaps and releases columns after the group', () => {
    const result = layoutEvents([{ id: 'a', start: 600, end: 660 }, { id: 'b', start: 630, end: 690 }, { id: 'c', start: 660, end: 720 }, { id: 'd', start: 720, end: 750 }]);
    expect(result.map(e => [e.column, e.columns])).toEqual([[0, 2], [1, 2], [0, 2], [0, 1]]);
  });
  it('rejects executable external URLs', () => {
    expect(safeLink('javascript:alert(1)')).toBe('');
    expect(safeLink('https://calendar.google.com/event')).toContain('https://');
  });
});
