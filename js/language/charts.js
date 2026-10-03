import { node } from './components/dom.js';

export function buildLinePoints(values, { width = 320, height = 96, padding = 8 } = {}) {
  const numbers = (values || []).map((value) => Number(value) || 0);
  if (!numbers.length) return [];
  const maximum = Math.max(1, ...numbers);
  const span = Math.max(1, numbers.length - 1);
  return numbers.map((value, index) => ({
    x: padding + ((width - padding * 2) * index) / span,
    y: height - padding - ((height - padding * 2) * value) / maximum,
    value,
  }));
}

export function formatStudyDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function lineChart(series, {
  label = 'Time series',
  valueKey = 'value',
  emptyText = 'No activity in this range.',
} = {}) {
  if (!Array.isArray(series) || !series.length || !series.some((item) => Number(item[valueKey]) > 0)) {
    return node('div', { className: 'language-chart-empty', text: emptyText });
  }
  const width = 360;
  const height = 108;
  const points = buildLinePoints(series.map((item) => item[valueKey]), { width, height });
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('language-line-chart');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', label);
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  line.setAttribute('points', points.map((point) => `${point.x},${point.y}`).join(' '));
  line.setAttribute('fill', 'none');
  line.setAttribute('stroke', 'currentColor');
  line.setAttribute('stroke-width', '3');
  line.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.append(line);
  return node('div', { className: 'language-chart-wrap' }, [
    svg,
    node('p', {
      className: 'language-chart-summary',
      text: `${series.length} daily points · latest ${points.at(-1)?.value ?? 0}`,
    }),
  ]);
}

export function distributionBars(entries, { label = 'Distribution' } = {}) {
  const rows = Object.entries(entries || {});
  if (!rows.length || rows.every(([, value]) => Number(value) === 0)) {
    return node('div', { className: 'language-chart-empty', text: 'No evidence in this range.' });
  }
  const maximum = Math.max(1, ...rows.map(([, value]) => Number(value) || 0));
  return node('div', { className: 'language-bars', attrs: { role: 'img', 'aria-label': label } }, rows.map(([key, value]) => (
    node('div', { className: 'language-bar-row' }, [
      node('span', { text: key }),
      node('span', { className: 'language-bar-track' }, [
        node('span', { className: 'language-bar-fill', attrs: { style: `width:${((Number(value) || 0) / maximum) * 100}%` } }),
      ]),
      node('strong', { text: value }),
    ])
  )));
}
