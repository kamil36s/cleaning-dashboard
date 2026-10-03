import { createLanguageApi } from './language/api.js';
import { ankiDailyProgress } from './language/anki-daily.js';
import { getCleaningSettings, getCleaningState, getTasks } from './cleaning-api.js';
import { deriveStatus, statusOrder } from './cleaning-logic.js';
import {
  buildCleaningForecastSeries, getCleaningActionHistory, getCleaningDayKey,
  getCleaningActionsForDay, getCleaningDayReference, getCleaningForecastDailyCapacity,
  getCleaningForecastRampStart, getCleaningRecoveryDayKeys, refreshCleaningActionHistory,
} from './cleaning-history.js';
import { fetchReadingState } from './reading-api.js';
import { fetchFileSetting } from './file-settings.js';
import { liveWorkoutRuntimeUrl } from './live-workout-runtime-api.js';
import { HR_ZONE_CONFIG } from './live-workout-engine.js';
import { snapshotToHabits } from './habits-app-api.js';
import { isHabitComplete } from './habits-app-model.js';
import { localDateKey } from './habits-reminder-schedule.js';

const number = (value) => Math.max(0, Math.round(Number(value) || 0));
const format = (value) => number(value).toLocaleString('pl-PL');
const WORKOUT_TYPES = {
  recovery: 'Regeneracja', base: 'Baza tlenowa', tempo: 'Tempo',
  intervals: 'Interwały', long: 'Długi trening',
  'free-ride': 'Swobodny trening', virtual_walk: 'Spacer', strength: 'Trening siłowy',
};
const CLEANING_CATEGORY_PRIORITY = ['łóżko', 'śmieci', 'przetarcie kurzu', 'organizacja', 'odkurzanie', 'inne'];
const normalizeCleaningCategory = (value) => String(value || '').toLowerCase()
  .normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\u0142/g, 'l');
const cleaningCategoryRank = (task) => {
  const category = normalizeCleaningCategory(task.category);
  const index = CLEANING_CATEGORY_PRIORITY.findIndex((name) => category.includes(normalizeCleaningCategory(name)));
  return index < 0 ? Number.POSITIVE_INFINITY : index;
};

export function remaining(done, target) { return Math.max(0, number(target) - number(done)); }
export function completionPercent(done, target) {
  return Number(target) > 0 ? Math.min(100, Math.max(0, Math.floor(Number(done || 0) / Number(target) * 100))) : 0;
}

export function readingGoal(stats = {}) {
  const target = number(stats.todayTarget);
  const done = number(stats.todayRead);
  return { target, done, left: remaining(done, target) };
}

export function ankiGoal(decks = []) {
  const { done, planned } = ankiDailyProgress(decks);
  return { target: planned, done, left: remaining(done, planned) };
}

export function pendingSupplements(items = []) {
  return items.filter((item) => item.due === true && item.status !== 'TAKEN')
    .map((item) => item.displayName);
}

export function availableCleaningTasks(tasks = [], doneItems = []) {
  const doneRows = new Set(doneItems.map((item) => Number(item.row ?? item.row_id)));
  return tasks.map((task) => ({ ...task, status: deriveStatus(task) }))
    .filter((task) => !doneRows.has(Number(task.row ?? task.row_id))
      && ['DEAD', 'OVERDUE', 'DUE', 'COMING'].includes(task.status))
    .sort((a, b) => cleaningCategoryRank(a) - cleaningCategoryRank(b)
      || statusOrder[a.status] - statusOrder[b.status]
      || String(a.task || '').localeCompare(String(b.task || ''), 'pl'))
    .map((task) => ({ name: String(task.task || '').trim(), room: String(task.room || '').trim(), status: task.status }))
    .filter((task) => task.name);
}

export function workoutGoal(plan, sessions = [], statuses = {}, day = localDateKey()) {
  const workout = plan?.schedule?.find((item) => item.date === day)
    || (plan?.current_workout?.date === day ? plan.current_workout : null);
  if (!workout) return { state: 'neutral', label: 'Brak planu', detail: 'Nie zaplanowano treningu' };
  if (workout.type === 'rest') return { state: 'done', label: 'Odpoczynek', detail: 'Dzień regeneracji' };
  const target = number(workout.duration || plan.total_duration_minutes);
  const todaySessions = sessions.filter((session) => session.status === 'finished'
    && !['virtual_walk', 'strength'].includes(session.workout_type)
    && session.plan_id !== 'free-ride'
    && (session.plan_date || localDateKey(new Date(Number(session.started_at)))) === day);
  const done = Math.max(0, ...todaySessions.map((session) => Number(session.duration_seconds || 0) / 60));
  const complete = statuses?.[day] === 'completed' || todaySessions.some((session) =>
    session.plan_completed === true || (session.plan_completed !== false && session.duration_seconds >= target * 60 * .9));
  return { state: complete ? 'done' : 'pending', target, done, left: complete ? 0 : Math.max(0, Math.ceil(target - done)),
    detail: WORKOUT_TYPES[workout.type] || workout.type || 'Trening',
    zones: HR_ZONE_CONFIG.map((zone) => ({ key: zone.key, color: zone.color, minutes: number(workout.zones?.[zone.key]) }))
      .filter((zone) => zone.minutes > 0) };
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store', headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function updateProgressFrame(card) {
  const svg = card.querySelector('.goal-progress-frame');
  if (!svg || card.hidden) return;
  const width = card.clientWidth;
  const height = card.clientHeight;
  if (!width || !height) return;
  const inset = 1.5;
  const radius = Math.max(0, parseFloat(getComputedStyle(card).borderTopLeftRadius) - inset);
  const outline = svg.querySelector('rect');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  outline.setAttribute('x', inset);
  outline.setAttribute('y', inset);
  outline.setAttribute('width', width - inset * 2);
  outline.setAttribute('height', height - inset * 2);
  outline.setAttribute('rx', radius);
}

const progressObserver = typeof ResizeObserver === 'undefined' ? null
  : new ResizeObserver((entries) => entries.forEach(({ target }) => updateProgressFrame(target)));

function showProgress(card, done, target) {
  const percent = completionPercent(done, target);
  let badge = card.querySelector('.goal-percent');
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'goal-percent';
    card.append(badge);
  }
  badge.textContent = `${percent}%`;
  badge.setAttribute('aria-label', `${percent}% wykonane`);
  let frame = card.querySelector('.goal-progress-frame');
  if (!frame) {
    frame = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    frame.classList.add('goal-progress-frame');
    frame.setAttribute('aria-hidden', 'true');
    const outline = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    outline.setAttribute('pathLength', '100');
    frame.append(outline);
    card.prepend(frame);
    progressObserver?.observe(card);
  }
  frame.hidden = percent === 0;
  frame.querySelector('rect').setAttribute('stroke-dasharray', `${percent} ${100 - percent}`);
  updateProgressFrame(card);
}

function showGoal(id, { left, state, label, detail, done, target }) {
  const card = document.querySelector(`[data-goal="${id}"]`);
  if (!card) return;
  const finalState = state || (left <= 0 ? 'done' : 'pending');
  card.dataset.state = finalState;
  card.hidden = finalState !== 'pending';
  if (card.hidden) return;
  showProgress(card, done, target);
  card.querySelector('.goal-number').textContent = label ?? format(left);
  const detailNode = card.querySelector('.goal-detail');
  if (detailNode) detailNode.textContent = detail || '';
}

function showWorkoutZones(zones) {
  const section = document.querySelector('[data-goal="workout"] .workout-plan');
  section.hidden = zones.length === 0;
  if (section.hidden) return;
  const strip = section.querySelector('.workout-zone-strip');
  const list = section.querySelector('.workout-zone-list');
  strip.replaceChildren();
  list.replaceChildren();
  const total = zones.reduce((sum, zone) => sum + zone.minutes, 0);
  for (const zone of zones) {
    const segment = document.createElement('span');
    segment.style.setProperty('--zone-color', zone.color);
    segment.style.width = `${zone.minutes / total * 100}%`;
    strip.append(segment);
    const row = document.createElement('li');
    row.style.setProperty('--zone-color', zone.color);
    const name = document.createElement('span');
    name.textContent = zone.key.toUpperCase();
    const minutes = document.createElement('strong');
    minutes.textContent = `${zone.minutes}m`;
    row.append(name, minutes);
    list.append(row);
  }
  strip.setAttribute('aria-label', `Plan: ${zones.map((zone) => `${zone.key} ${zone.minutes} minut`).join(', ')}`);
}

function showError(id) {
  showGoal(id, { state: 'error' });
}

function showSupplements(items) {
  const due = items.filter((item) => item.due === true);
  const names = pendingSupplements(items);
  const card = document.querySelector('[data-intake="supplements"]');
  card.hidden = names.length === 0;
  if (card.hidden) return;
  showProgress(card, due.length - names.length, due.length);
  const list = card.querySelector('.intake-list');
  card.querySelector('.intake-count').textContent = format(names.length);
  list.replaceChildren();
  for (const name of names) {
    const item = document.createElement('li');
    item.textContent = name;
    list.append(item);
  }
}

function showCleaningTasks(items) {
  const card = document.querySelector('[data-goal="cleaning"]');
  const list = card.querySelector('.goal-task-list');
  list.replaceChildren();
  for (const item of items) {
    const row = document.createElement('li');
    row.className = 'cleaning-task-pill';
    row.title = item.room ? `${item.name} · ${item.room}` : item.name;
    const name = document.createElement('span');
    name.className = 'cleaning-task-name';
    name.textContent = item.name;
    const badge = document.createElement('span');
    badge.className = `cleaning-task-status is-${item.status.toLowerCase()}`;
    badge.textContent = item.status;
    row.append(name, badge);
    list.append(row);
  }
}

export async function getStepsGoal(day) {
  const data = await fetchJson('/api/steps/history?days=1');
  const done = number(data.daily?.find((row) => row.day === day)?.steps);
  return { done, target: 10000, left: remaining(done, 10000) };
}
async function loadSteps(day) { showGoal('steps', await getStepsGoal(day)); }

export async function getAnkiGoal() {
  const api = createLanguageApi();
  const profiles = await api.profiles();
  const profile = profiles.items?.find((item) => item.languageCode === 'nb' && item.locale === 'nb-NO');
  if (!profile) return { state: 'neutral' };
  const status = await api.ankiStatus(profile.id);
  if (status.status === 'UNAVAILABLE') throw new Error('Anki unavailable');
  const goal = ankiGoal(status.decks || []);
  return goal.target ? goal : { state: 'neutral' };
}
async function loadAnki() { showGoal('anki', await getAnkiGoal()); }

export async function getReadingGoal() {
  const data = await fetchReadingState();
  const goal = readingGoal(data.dailyStats);
  return goal.target ? goal : { state: 'neutral' };
}
async function loadReading() { showGoal('reading', await getReadingGoal()); }

export async function getWeightGoal(day) {
  const data = await fetchJson('/api/weight/events');
  const event = data.events?.find((item) => {
    const date = new Date(item.timestamp);
    return !Number.isNaN(date.getTime()) && localDateKey(date) === day;
  });
  return event ? { state: 'done' } : { state: 'pending', label: 'Zważyć się', done: 0, target: 1 };
}
async function loadWeight(day) { showGoal('weight', await getWeightGoal(day)); }

export async function getWorkoutGoal(day) {
  const [plan, history, tracking] = await Promise.all([
    fetchJson(liveWorkoutRuntimeUrl('plan')),
    fetchJson(`${liveWorkoutRuntimeUrl('history')}?limit=200`),
    fetchFileSetting('live-workout-plan', { statuses: {} }).catch(() => ({ statuses: {} })),
  ]);
  return workoutGoal(plan, history.sessions || [], tracking?.statuses || {}, day);
}
async function loadWorkout(day) {
  const goal = await getWorkoutGoal(day);
  showGoal('workout', goal);
  if (goal.state === 'pending') showWorkoutZones(goal.zones);
}

function forecastCleaningTarget(tasks, doneItems, history, now) {
  const reference = getCleaningDayReference(now, { rolloverHour: 6 });
  const planStart = getCleaningForecastRampStart(tasks, reference);
  const forecast = buildCleaningForecastSeries(tasks, { range: 'week', now: reference, historyEvents: history, planStart })
    .find((item) => item.isToday);
  const planned = new Map((forecast?.tasks || []).map((item) => [Number(item.row), Math.max(1, Number(item.count) || 1)]));
  let extraDone = 0;
  for (const item of doneItems) {
    const row = Number(item.row ?? item.row_id);
    if (planned.get(row) > 0) planned.set(row, planned.get(row) - 1);
    else extraDone += 1;
  }
  const capacity = getCleaningForecastDailyCapacity(tasks, reference, { planStart, historyEvents: history });
  return Math.min(10, capacity, Math.max(0, Number(forecast?.count) || 0) + extraDone);
}

function targetAfterFirstCleaningAction(tasks, history, now) {
  const actions = getCleaningActionsForDay(history, now, { rolloverHour: 6 });
  const firstRow = Number(actions.at(-1)?.row);
  if (!Number.isFinite(firstRow)) return null;
  let restoredCount = 0;
  let restoredTasks = [...tasks];
  for (const action of actions.slice(0, -1)) {
    const status = String(action.status || '').toUpperCase();
    if (!['DEAD', 'OVERDUE', 'DUE'].includes(status)) continue;
    restoredTasks = restoredTasks.map((task) => {
      if (Number(task.row ?? task.row_id) !== Number(action.row)) return task;
      restoredCount += 1;
      const freq = Math.max(1, Number(task.freq) || 1);
      const overdue = status !== 'DUE';
      return { ...task, overdue, daysSince: status === 'DEAD' ? freq + 8 : status === 'OVERDUE' ? freq + 1 : freq,
        nextDueIn: overdue ? -1 : 0 };
    });
  }
  if (actions.length > 1 && restoredCount === 0) return null;
  return forecastCleaningTarget(restoredTasks, [{ row: firstRow }], history, now);
}

export async function getCleaningGoal() {
  const settings = await getCleaningSettings();
  const apartmentId = settings.activeApartmentId || settings.settings?.activeApartmentId || 'aleja-pokoju6';
  const [tasks, state] = await Promise.all([
    getTasks(apartmentId), getCleaningState(apartmentId), refreshCleaningActionHistory(apartmentId),
  ]);
  const now = new Date();
  const day = getCleaningDayKey(now, { rolloverHour: 6 });
  const history = getCleaningActionHistory();
  const doneItems = state.doneToday || [];
  const done = doneItems.length;
  let target = getCleaningRecoveryDayKeys(history).has(day) ? 1
    : targetAfterFirstCleaningAction(tasks, history, now) ?? forecastCleaningTarget(tasks, doneItems, history, now);
  try {
    const saved = JSON.parse(localStorage.getItem('cleaningDashboard.dailyGoalTarget.v2') || 'null');
    if (saved?.key === `${apartmentId}:${day}` && saved.planVersion === 2) target = number(saved.target);
  } catch { /* Tablet browsers may block storage. */ }
  return {
    goal: target ? { done, target, left: remaining(done, target) } : { state: 'neutral' },
    tasks: target > done ? availableCleaningTasks(tasks, doneItems) : [],
  };
}
async function loadCleaning() {
  const { goal, tasks } = await getCleaningGoal();
  showGoal('cleaning', goal);
  if (goal.state !== 'neutral' && goal.left > 0) showCleaningTasks(tasks);
}

export async function getSobrietyGoal(day) {
  const snapshot = await fetchJson(`/api/habits/snapshot?from=${day}&to=${day}`);
  const habits = snapshotToHabits(snapshot);
  const sobriety = habits.find((habit) => habit.sourceName?.toLowerCase() === "don't drink");
  return sobriety
    ? isHabitComplete(sobriety, sobriety.entries.get(day) ?? null)
      ? { state: 'done' }
      : { state: 'pending', label: 'Potwierdzić' }
    : { state: 'neutral' };
}
async function loadSobriety(day) { showGoal('sobriety', await getSobrietyGoal(day)); }

export async function getSupplements(day) {
  const snapshot = await fetchJson(`/api/habits/supplements?date=${day}`);
  return snapshot.items || [];
}
async function loadSupplements(day) { showSupplements(await getSupplements(day)); }

export async function getAlbumGoal(day) {
  const data = await fetchJson(`/api/bm365/state?today=${day}`);
  const album = data.albumToday;
  return album
    ? { state: album.listened ? 'done' : 'pending', label: 'Odsłuchać',
        detail: `${album.artist || ''} · ${album.album || ''}`.replace(/^ · | · $/g, '') }
    : { state: 'neutral' };
}
async function loadAlbum(day) { showGoal('album', await getAlbumGoal(day)); }

function updateClock() {
  const now = new Date();
  document.getElementById('display-clock').textContent = new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' }).format(now);
  document.getElementById('display-date').textContent = new Intl.DateTimeFormat('pl-PL', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
    .format(now).replace(/^./, (letter) => letter.toLocaleUpperCase('pl-PL'));
}

let loading = false;
async function refresh() {
  if (loading) return;
  loading = true;
  const day = localDateKey();
  const status = document.getElementById('display-updated');
  status.textContent = 'Odświeżam…';
  const jobs = [
    ['steps', () => loadSteps(day)], ['anki', loadAnki], ['reading', loadReading],
    ['workout', () => loadWorkout(day)], ['cleaning', loadCleaning], ['weight', () => loadWeight(day)],
    ['sobriety', () => loadSobriety(day)], ['supplements', () => loadSupplements(day)], ['album', () => loadAlbum(day)],
  ];
  const results = await Promise.allSettled(jobs.map(([, run]) => run()));
  results.forEach((result, index) => {
    if (result.status !== 'rejected') return;
    if (jobs[index][0] === 'supplements') document.querySelector('[data-intake="supplements"]').hidden = true;
    else showError(jobs[index][0]);
    console.warn('Today display:', jobs[index][0], result.reason);
  });
  document.getElementById('display-empty').hidden = results.some((result) => result.status === 'rejected')
    || !!document.querySelector('[data-goal]:not([hidden]), [data-intake]:not([hidden])');
  status.textContent = results.some((result) => result.status === 'rejected')
    ? 'Część danych niedostępna'
    : `Aktualizacja ${new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' }).format(new Date())}`;
  loading = false;
}

if (typeof document !== 'undefined' && document.querySelector('.display')) {
  updateClock();
  refresh();
  window.setInterval(updateClock, 1000);
  window.setInterval(refresh, 2 * 60 * 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  document.getElementById('display-refresh').addEventListener('click', refresh);
  document.getElementById('display-fullscreen').addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen?.();
  });
  if (!progressObserver) window.addEventListener('resize', () =>
    document.querySelectorAll('.goal-progress-frame').forEach((frame) => updateProgressFrame(frame.parentElement)));
}
