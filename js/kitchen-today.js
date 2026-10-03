import { localDateKey } from './habits-reminder-schedule.js';
import {
  completionPercent, getAlbumGoal, getAnkiGoal, getCleaningGoal, getReadingGoal,
  getSobrietyGoal, getStepsGoal, getSupplements, getWeightGoal, getWorkoutGoal,
  pendingSupplements,
} from './today-display.js';

const format = (value) => Math.max(0, Math.round(Number(value) || 0)).toLocaleString('pl-PL');

const SOURCES = [
  ['steps', 'Kroki', (day) => getStepsGoal(day)],
  ['anki', 'Anki', () => getAnkiGoal()],
  ['reading', 'Czytanie', () => getReadingGoal()],
  ['workout', 'Trening', (day) => getWorkoutGoal(day)],
  ['cleaning', 'Sprzątanie', () => getCleaningGoal()],
  ['weight', 'Ważenie', (day) => getWeightGoal(day)],
  ['supplements', 'Suplementy', (day) => getSupplements(day)],
  ['sobriety', 'Trzeźwość', (day) => getSobrietyGoal(day)],
  ['album', 'Album dnia', (day) => getAlbumGoal(day)],
];

function compactGoal(id, label, payload) {
  if (id === 'supplements') {
    const names = pendingSupplements(payload);
    if (!names.length) return null;
    const due = payload.filter((item) => item.due === true);
    return { label, value: `${format(names.length)} do wzięcia`, detail: names.join(' · '),
      percent: completionPercent(due.length - names.length, due.length) };
  }
  const { goal, tasks } = id === 'cleaning' ? payload : { goal: payload, tasks: [] };
  if (goal.state === 'done' || goal.state === 'neutral' || (goal.left !== undefined && goal.left <= 0)) return null;
  const percent = completionPercent(goal.done, goal.target);
  if (id === 'weight') return { label, value: 'Zważyć się', percent };
  if (id === 'sobriety') return { label, value: 'Potwierdź', percent };
  if (id === 'album') return { label, value: 'Odsłuchać', detail: goal.detail, percent };
  if (id === 'cleaning') return { label, value: `${format(goal.left)} zad.`,
    detail: tasks.map((task) => task.name).join(' · '), percent };
  if (id === 'workout') return { label, value: `${format(goal.left)} min`, detail: goal.detail,
    zones: goal.zones || [], percent };
  const unit = id === 'steps' ? 'kroków' : id === 'anki' ? 'kart' : 'stron';
  return { label, value: `${format(goal.left)} ${unit}`, percent };
}

function renderItem(item) {
  const tile = document.createElement('div');
  tile.className = 'kitchen-today-item';
  tile.style.setProperty('--progress', `${item.percent}%`);
  tile.title = [item.label, item.value, item.detail].filter(Boolean).join(' · ');
  const head = document.createElement('div');
  head.className = 'kitchen-today-item-head';
  const label = document.createElement('span');
  label.className = 'kitchen-today-item-label';
  label.textContent = item.label;
  const percent = document.createElement('span');
  percent.className = 'kitchen-today-item-percent';
  percent.textContent = `${item.percent}%`;
  head.append(label, percent);
  const value = document.createElement('strong');
  value.className = 'kitchen-today-item-value';
  value.textContent = item.value;
  tile.append(head, value);
  if (item.detail) {
    const detail = document.createElement('span');
    detail.className = 'kitchen-today-item-detail';
    detail.textContent = item.detail;
    tile.append(detail);
  }
  if (item.zones?.length) {
    const strip = document.createElement('div');
    strip.className = 'kitchen-today-zones';
    const total = item.zones.reduce((sum, zone) => sum + zone.minutes, 0);
    for (const zone of item.zones) {
      const segment = document.createElement('span');
      segment.style.setProperty('--zone-color', zone.color);
      segment.style.width = `${zone.minutes / total * 100}%`;
      strip.append(segment);
    }
    tile.append(strip);
  }
  return tile;
}

export function initKitchenToday() {
  const grid = document.getElementById('kitchen-today-grid');
  if (!grid) return;
  let loading = false;
  const refresh = async () => {
    if (loading) return;
    loading = true;
    try {
      const day = localDateKey();
      const results = await Promise.allSettled(SOURCES.map(([, , load]) => load(day)));
      const items = results.map((result, index) => result.status === 'fulfilled'
        ? compactGoal(SOURCES[index][0], SOURCES[index][1], result.value) : null).filter(Boolean);
      if (items.length) grid.replaceChildren(...items.map(renderItem));
      else {
        const empty = document.createElement('span');
        empty.className = 'kitchen-today-empty';
        empty.textContent = results.some((result) => result.status === 'rejected')
          ? 'Część danych niedostępna' : 'Wszystko zrobione na dziś';
        grid.replaceChildren(empty);
      }
    } finally {
      loading = false;
    }
  };
  refresh();
  window.setInterval(refresh, 2 * 60 * 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
}
