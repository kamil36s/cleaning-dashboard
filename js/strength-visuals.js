const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

const paths = Object.freeze({
  bolt: '<path d="m13 2-8 11h6l-1 9 9-12h-6z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  sparkles: '<path d="m12 3 1.3 3.7L17 8l-3.7 1.3L12 13l-1.3-3.7L7 8l3.7-1.3zM5 14l.8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8zM19 13l.7 1.8 1.8.7-1.8.7L19 18l-.7-1.8-1.8-.7 1.8-.7z"/>',
  dumbbell: '<path d="M6 7v10M3.5 9v6M18 7v10M20.5 9v6M6 12h12"/>',
  trophy: '<path d="M8 4h8v4a4 4 0 0 1-8 0zM9 20h6M12 12v5M9 17h6M8 6H4v1a4 4 0 0 0 4 4M16 6h4v1a4 4 0 0 1-4 4"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  infinity: '<path d="M7.5 9C4.5 9 3 10.5 3 12s1.5 3 4.5 3c4 0 5-6 9-6 3 0 4.5 1.5 4.5 3s-1.5 3-4.5 3c-4 0-5-6-9-6z"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M15 9 21 3M17 3h4v4"/>',
  shield: '<path d="M12 3 5 6v5c0 4.6 2.8 8.1 7 10 4.2-1.9 7-5.4 7-10V6z"/><path d="m9 12 2 2 4-5"/>',
  medal: '<circle cx="12" cy="14" r="5"/><path d="m9 9-3-6h4l2 4 2-4h4l-3 6M12 11v6"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  chart: '<path d="M4 19V5M4 19h16M7 15l4-5 3 2 5-7"/>',
  activity: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  body: '<circle cx="12" cy="5" r="2.5"/><path d="M8 21l1.5-7L7 10l2-3h6l2 3-2.5 4L16 21M9.5 14h5"/>',
  abs: '<path d="M8 4h8l2 5-2 11H8L6 9zM12 5v14M8 10h8M8 15h8"/>',
  chest: '<path d="M5 8c2-3 4-4 7-1 3-3 5-2 7 1l-2 6c-2 1-3 0-5-1-2 1-3 2-5 1z"/>',
  back: '<path d="M8 4h8l4 6-4 3-1 7H9l-1-7-4-3zM12 5v14"/>',
  legs: '<path d="M8 3h8l-1 8 2 10h-4l-1-8-1 8H7l2-10z"/>',
  shoulders: '<path d="M5 10c1-4 3-6 7-6s6 2 7 6l-3 3-1-4H9l-1 4z"/>',
  biceps: '<path d="M8 7v5c0 3 2 5 4 5 3 0 5-2 5-5 0-2-1-4-3-5v4c-2-1-3-3-3-5z"/>',
  triceps: '<path d="M9 5c4 0 7 3 7 7v7h-4v-6c-3 0-5-2-5-5z"/>',
});

export function strengthIcon(name, className = "") {
  const body = paths[name] || paths.activity;
  return `<svg class="strength-v2-icon ${escapeHtml(className)}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${body}</svg>`;
}

export function estimateSetCount(duration) {
  const minutes = Number(duration);
  if (minutes <= 5) return 2;
  if (minutes <= 10) return 4;
  return 6;
}

function mondayAt(timestamp) {
  const date = new Date(timestamp);
  date.setHours(0, 0, 0, 0);
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  return date;
}

export function weeklySetBuckets(history, reference = Date.now()) {
  const currentMonday = mondayAt(reference);
  return Array.from({ length: 4 }, (_, index) => {
    const start = new Date(currentMonday);
    start.setDate(start.getDate() - (3 - index) * 7);
    const end = new Date(start);
    end.setDate(end.getDate() + 7);
    const sets = history.filter((item) => item.quality && Number(item.completed_at) >= start.getTime() && Number(item.completed_at) < end.getTime()).length;
    return {
      start: start.getTime(),
      label: new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short" }).format(start),
      sets,
    };
  });
}

export function exerciseSeries(history, exerciseId, metric = "total") {
  const rows = history.filter((item) => item.exercise_id === exerciseId && item.quality);
  const sessions = rows.reduce((map, item) => {
    if (!map.has(item.session_id)) map.set(item.session_id, []);
    map.get(item.session_id).push(item);
    return map;
  }, new Map());
  return [...sessions.values()].map((sets) => {
    const chronological = sets.slice().sort((left, right) => Number(left.completed_at) - Number(right.completed_at));
    let value = 0;
    if (metric === "max") value = Math.max(0, ...chronological.map((item) => Number(item.reps || item.duration_seconds || 0)));
    else if (metric === "weight") {
      const exact = chronological.map((item) => Number(item.load_kg)).filter(Number.isFinite);
      value = exact.length ? Math.max(...exact) : null;
    } else if (metric === "volume") {
      const exact = chronological.filter((item) => Number.isFinite(Number(item.load_kg)) && Number.isFinite(Number(item.reps)));
      value = exact.length ? exact.reduce((sum, item) => sum + Number(item.load_kg) * Number(item.reps), 0) : null;
    } else if (metric === "sets") value = chronological.length;
    else value = chronological.reduce((sum, item) => sum + Number(item.reps || item.duration_seconds || 0), 0);
    return {
      value,
      timestamp: Number(chronological.at(-1)?.completed_at || 0),
      label: new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short" }).format(new Date(Number(chronological.at(-1)?.completed_at || 0))),
    };
  }).filter((item) => Number.isFinite(item.value)).sort((left, right) => left.timestamp - right.timestamp).slice(-10);
}

export function lineChartSvg(points, { label = "Wynik", suffix = "" } = {}) {
  if (!points.length) return `<div class="strength-v2-empty"><span>${strengthIcon("chart")}</span><strong>Za mało porównywalnych danych</strong><p>Wykres pojawi się po zapisaniu pierwszej serii dla tej metryki.</p></div>`;
  const width = 720;
  const height = 244;
  const left = 42;
  const right = 18;
  const top = 20;
  const bottom = 38;
  const values = points.map((point) => Number(point.value));
  const max = Math.max(1, ...values);
  const min = Math.min(0, ...values);
  const range = Math.max(1, max - min);
  const x = (index) => left + (points.length === 1 ? (width - left - right) / 2 : index / (points.length - 1) * (width - left - right));
  const y = (value) => top + (1 - (value - min) / range) * (height - top - bottom);
  const coordinates = points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const area = `${left},${height - bottom} ${coordinates} ${x(points.length - 1)},${height - bottom}`;
  const grid = [0, .25, .5, .75, 1].map((step) => {
    const gy = top + step * (height - top - bottom);
    const tick = Math.round((max - step * range) * 10) / 10;
    return `<line x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}"/><text x="${left - 8}" y="${gy + 4}">${tick}</text>`;
  }).join("");
  const dots = points.map((point, index) => `<g><circle cx="${x(index)}" cy="${y(point.value)}" r="4"><title>${escapeHtml(point.label)}: ${point.value}${escapeHtml(suffix)}</title></circle><text class="strength-v2-chart-date" x="${x(index)}" y="${height - 14}">${escapeHtml(point.label)}</text></g>`).join("");
  return `<figure class="strength-v2-line-figure"><figcaption class="sr-only">${escapeHtml(label)}</figcaption><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(label)}"><g class="strength-v2-chart-grid">${grid}</g><polygon class="strength-v2-chart-area" points="${area}"/><polyline class="strength-v2-chart-line" points="${coordinates}"/>${dots}</svg></figure>`;
}

export function recoveryScore(recovery = []) {
  if (!recovery.length) return 0;
  const weights = { green: 100, yellow: 62, red: 28 };
  return Math.round(recovery.reduce((sum, item) => sum + (weights[item.status] ?? 62), 0) / recovery.length);
}

export function recoveryGaugeSvg(score) {
  const safe = Math.max(0, Math.min(100, Number(score) || 0));
  return `<div class="strength-v2-gauge" style="--gauge-score:${safe}"><svg viewBox="0 0 180 106" role="img" aria-label="Heurystyczna gotowość ${safe} procent"><path class="strength-v2-gauge-track" d="M24 88a66 66 0 0 1 132 0"/><path class="strength-v2-gauge-value" pathLength="100" stroke-dasharray="${safe} 100" d="M24 88a66 66 0 0 1 132 0"/></svg><div><strong>${safe}</strong><span>READINESS</span></div></div>`;
}

export function muscleMapHtml(scoreboard = [], recovery = [], selectedMuscle = "abs") {
  const status = new Map(recovery.map((item) => [item.muscleGroup, item.status]));
  const score = new Map(scoreboard.map((item) => [item.muscle_group, item]));
  const buttons = [
    ["shoulders", 31, 22], ["chest", 31, 31], ["abs", 31, 44], ["biceps", 18, 35], ["triceps", 84, 35], ["legs", 31, 70], ["back", 73, 42],
  ].map(([group, x, y]) => {
    const item = score.get(group);
    return `<button type="button" data-strength-muscle="${group}" class="is-${status.get(group) || "green"} ${selectedMuscle === group ? "is-selected" : ""}" style="--map-x:${x}%;--map-y:${y}%" aria-label="${escapeHtml(item?.label || group)}: ${item?.sets || 0} serii"><span>${item?.sets || 0}</span></button>`;
  }).join("");
  return `<div class="strength-v2-muscle-map"><svg viewBox="0 0 300 330" role="img" aria-label="Uproszczona mapa grup mięśniowych, widok przód i tył"><g class="strength-v2-body-shape"><circle cx="92" cy="36" r="21"/><path d="M62 69Q92 51 122 69l16 80-25 37 12 119H96l-4-91-4 91H59l12-119-25-37z"/><circle cx="218" cy="36" r="21"/><path d="M188 69q30-18 60 0l16 80-25 37 12 119h-29l-4-91-4 91h-29l12-119-25-37z"/></g><g class="strength-v2-body-detail"><path d="M92 62v137M65 101h54M72 144h40M218 62v137M191 101h54M198 145h40"/></g><text x="92" y="325">FRONT</text><text x="218" y="325">BACK</text></svg>${buttons}</div>`;
}

export function weeklyBarsHtml(buckets) {
  const max = Math.max(1, ...buckets.map((item) => item.sets));
  return `<div class="strength-v2-week-bars" role="img" aria-label="Jakościowe serie w czterech ostatnich tygodniach">${buckets.map((item, index) => `<div class="${index === buckets.length - 1 ? "is-current" : ""}"><span>${item.sets}</span><i style="--bar:${Math.max(item.sets ? 10 : 2, item.sets / max * 100)}%"></i><small>${escapeHtml(item.label)}</small></div>`).join("")}</div>`;
}
