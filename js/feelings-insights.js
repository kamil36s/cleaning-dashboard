import { QUADRANT_META, escapeHtml } from "./feelings-model.js";

export function trendSvg(points = []) {
  const recent = points.slice(-45);
  if (!recent.length) return '<p class="feelings-empty">No trend data for this range.</p>';
  const width = 760;
  const height = 220;
  const inset = 22;
  const x = (index) => inset + (index / Math.max(1, recent.length - 1)) * (width - inset * 2);
  const y = (value) => inset + ((1 - Number(value)) / 2) * (height - inset * 2);
  const path = (key) => recent.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point[key]).toFixed(1)}`).join(" ");
  return `
    <svg class="feelings-trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Daily energy and pleasantness trend">
      <line x1="${inset}" y1="${height / 2}" x2="${width - inset}" y2="${height / 2}" />
      <path class="is-energy" d="${path("energy")}" />
      <path class="is-pleasantness" d="${path("pleasantness")}" />
    </svg>
    <div class="feelings-chart-legend"><span class="is-energy">Energy</span><span class="is-pleasantness">Pleasantness</span></div>`;
}

export function heatmap(items = []) {
  const values = new Map(items.map((item) => [item.date, item.count]));
  const max = Math.max(1, ...values.values());
  const today = new Date();
  const cells = [];
  for (let offset = 83; offset >= 0; offset -= 1) {
    const date = new Date(today);
    date.setDate(date.getDate() - offset);
    const key = date.toISOString().slice(0, 10);
    const count = values.get(key) || 0;
    const level = count ? Math.max(1, Math.ceil((count / max) * 4)) : 0;
    cells.push(`<i data-level="${level}" title="${key}: ${count} check-in${count === 1 ? "" : "s"}"></i>`);
  }
  return `<div class="feelings-heatmap" aria-label="12 week check-in heatmap">${cells.join("")}</div>`;
}

export function quadrantBars(quadrants = []) {
  return `<div class="feelings-quadrant-bars">${quadrants.map((item) => {
    const meta = QUADRANT_META[item.quadrant];
    return `<div><span><b>${escapeHtml(meta?.short)}</b><em>${item.count} · ${item.percentage}%</em></span><i style="--value:${item.percentage};--bar:${meta?.color}"></i></div>`;
  }).join("")}</div>`;
}

export function frequencyBars(items = []) {
  const shown = items.slice(0, 12);
  const max = Math.max(1, ...shown.map((item) => item.count));
  return `<div class="feelings-frequency-bars">${shown.map((item) => `
    <div><span>${escapeHtml(item.emotion)}</span><i style="--value:${(item.count / max) * 100}"></i><b>${item.count}</b></div>`).join("")}</div>`;
}

export function distributionRows(values = {}, order = []) {
  const max = Math.max(1, ...order.map((key) => Number(values[key] || 0)));
  return `<div class="feelings-distribution">${order.map((key) => `
    <div><span>${escapeHtml(key)}</span><i style="--value:${(Number(values[key] || 0) / max) * 100}"></i><b>${Number(values[key] || 0)}</b></div>`).join("")}</div>`;
}

export function associationDetail(item, type) {
  if (!item) return '<p class="feelings-empty">Choose an item to inspect its local associations.</p>';
  if (type === "tag") {
    const top = (item.emotions || []).slice(0, 5).map(([name, count]) => `${escapeHtml(name)} (${count})`).join(", ");
    return `<p><b>${item.count}</b> check-ins carry this tag.</p><p>Most frequent emotions: ${top || "—"}.</p>${quadrantBars(Object.entries(item.quadrants || {}).map(([quadrant, count]) => ({ quadrant, count, percentage: item.count ? Math.round(count * 1000 / item.count) / 10 : 0 })))}`;
  }
  const tags = (item.tags || []).slice(0, 6).map(([name, count]) => `${escapeHtml(name)} (${count})`).join(", ");
  return `<p><b>${item.count}</b> check-ins use this emotion.</p><p>Common tags: ${tags || "—"}.</p>${distributionRows(item.timeOfDay || {}, ["morning", "afternoon", "evening", "night"])}`;
}
