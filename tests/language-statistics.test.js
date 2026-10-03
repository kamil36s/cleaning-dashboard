import { afterEach, describe, expect, it } from 'vitest';
import {
  buildLinePoints,
  distributionBars,
  formatStudyDuration,
  lineChart,
} from '../js/language/charts.js';

describe('Language statistics chart helpers', () => {
  afterEach(() => document.body.replaceChildren());

  it('builds deterministic bounded points and formats active duration', () => {
    expect(buildLinePoints([0, 5, 10], { width: 100, height: 50, padding: 5 })).toEqual([
      { x: 5, y: 45, value: 0 },
      { x: 50, y: 25, value: 5 },
      { x: 95, y: 5, value: 10 },
    ]);
    expect(formatStudyDuration(0)).toBe('0m');
    expect(formatStudyDuration(3661)).toBe('1h 1m');
    expect(formatStudyDuration(-50)).toBe('0m');
  });

  it('renders an accessible SVG only when there is real activity', () => {
    const chart = lineChart([
      { date: '2026-09-15', total: 1 },
      { date: '2026-09-16', total: 3 },
    ], { label: 'Vocabulary history', valueKey: 'total' });
    document.body.append(chart);
    expect(document.querySelector('svg[role="img"]')?.getAttribute('aria-label')).toBe('Vocabulary history');
    expect(document.querySelector('polyline')?.getAttribute('points')).toContain(',');

    const empty = lineChart([{ total: 0 }], { valueKey: 'total', emptyText: 'No evidence.' });
    expect(empty.textContent).toBe('No evidence.');
    expect(empty.querySelector('svg')).toBeNull();
  });

  it('renders truthful distributions and an explicit no-evidence state', () => {
    const bars = distributionBars({ '1-2': 2, '3-5': 4 }, { label: 'Exposure distribution' });
    expect(bars.getAttribute('role')).toBe('img');
    expect(bars.getAttribute('aria-label')).toBe('Exposure distribution');
    expect(bars.querySelectorAll('.language-bar-row')).toHaveLength(2);
    expect(distributionBars({ '1-2': 0 }).textContent).toContain('No evidence');
  });
});
