import { SOURCES, dayKey, dateOf, shiftDay, weekStart, weekDays, layoutEvents, safeLink } from './calendar-model.js';
import { loadCalendar } from './calendar-data.js';
import { saveLocalDashboardEvent, upsertGoogleCalendarEvent, saveEventCountdownCategory } from './events-api.js';

const $ = (id) => document.getElementById(id);
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (day, options) => dateOf(day).toLocaleDateString('pl-PL', options);
const clock = (minute) => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(Math.round(minute % 60)).padStart(2, '0')}`;
const sourceOf = (id) => SOURCES.find(s => s[0] === id) || [id, id, '#8ab4f8', './index.html'];
const color = (value, fallback) => /^#[\da-f]{6}$/i.test(value || '') ? value : fallback;
const foreground = (hex) => {
  const values = hex.match(/[\da-f]{2}/gi)?.map(value => parseInt(value, 16) / 255) || [1, 1, 1];
  const light = values.map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  return light[0] * .2126 + light[1] * .7152 + light[2] * .0722 > .18 ? '#17191c' : '#fff';
};
const feelingMark = (source) => source === 'emotions'
  ? '<span class="calendar-feelings-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>'
  : '';
let selected = dayKey(), miniMonth = selected.slice(0, 7) + '-01', generation = 0, buckets = {}, visibleItems = [];
let hiddenSources = new Set(), hiddenCalendars = new Set();
let denseCalendarsInitialized = false;
try {
  const stored = localStorage.getItem('dashboard.calendar.filters.v1');
  denseCalendarsInitialized = Boolean(stored);
  const saved = JSON.parse(stored || '{}');
  hiddenSources = new Set(saved.sources || []);
  hiddenCalendars = new Set(saved.calendars || []);
} catch { /* Storage is optional. */ }
function saveFilters() { try { localStorage.setItem('dashboard.calendar.filters.v1', JSON.stringify({ sources: [...hiddenSources], calendars: [...hiddenCalendars] })); } catch { /* Storage is optional. */ } }

function renderMini() {
  $('mini-title').textContent = fmt(miniMonth, { month: 'long', year: 'numeric' });
  const start = weekStart(miniMonth), days = weekDays(selected);
  $('mini-calendar').innerHTML = ['P', 'W', 'Ś', 'C', 'P', 'S', 'N'].map(d => `<span class="weekday">${d}</span>`).join('') + Array.from({ length: 42 }, (_, i) => {
    const key = shiftDay(start, i);
    return `<button data-date="${key}" aria-label="${escape(fmt(key, { dateStyle: 'full' }))}" class="${key.slice(0, 7) !== miniMonth.slice(0, 7) ? 'outside' : ''} ${days.includes(key) ? 'selected-week' : ''} ${key === dayKey() ? 'is-today' : ''}">${dateOf(key).getDate()}</button>`;
  }).join('');
}
function renderFilters(items) {
  $('source-filters').innerHTML = SOURCES.map(([id, label, c]) => `<label class="filter" style="--source:${c}"><input type="checkbox" data-source="${id}" ${hiddenSources.has(id) ? '' : 'checked'}><span>${label}</span><small>${items.filter(e => e.source === id).length || ''}</small></label>`).join('');
  const calendars = new Map(items.filter(e => e.calendar).map(e => [e.calendar, e]));
  $('calendar-filters').innerHTML = [...calendars].map(([id, e]) => `<label class="filter" style="--source:${color(e.color, '#8ab4f8')}"><input type="checkbox" data-calendar="${escape(id)}" ${hiddenCalendars.has(id) ? '' : 'checked'}><span title="${escape(e.calendarLabel)}">${escape(e.calendarLabel)}</span></label>`).join('') || '<span class="muted">Brak wydarzeń w tym tygodniu</span>';
}
function eventButton(e, index, timed = false) {
  const c = color(e.color, sourceOf(e.source)[2]);
  let style = `--event-color:${c};--event-text:${foreground(c)};`;
  if (timed) style += `top:calc(${e.start / 60} * var(--hour));height:calc(${Math.min(1440 - e.start, e.visualEnd - e.start) / 60} * var(--hour) - 2px);left:calc(${e.column / e.columns * 100}% + 3px);width:calc(${100 / e.columns}% - 6px);`;
  const title = `${e.done ? '✓ ' : e.forecast ? '◌ ' : ''}${e.title}`;
  return `<button class="event-chip ${timed ? 'timed-event' : ''} ${e.done ? 'done' : ''} ${e.forecast ? 'forecast' : ''} ${e.source === 'emotions' ? 'emotion-event' : ''}" style="${style}" data-event="${index}" title="${escape(title)}"><span class="event-main">${feelingMark(e.source)}<span class="event-title">${escape(title)}</span></span>${timed ? `<small>${clock(e.start)}${e.point ? '' : `–${clock(e.end)}`}</small>` : ''}</button>`;
}
function daySummary(rows) {
  const done = rows.filter(e => e.done).length;
  const plan = rows.filter(e => e.forecast && !e.done).length;
  const other = rows.length - done - plan;
  return [done && `${done} wykonane`, plan && `${plan} w planie`, other && `${other} terminy`].filter(Boolean).join(' · ');
}
function showDayList(day, kind) {
  const entries = visibleItems.filter(e => e.day === day && e.start == null && (kind === 'events' ? e.source === 'events' : e.source !== 'events'));
  $('day-dialog-title').textContent = `${kind === 'events' ? 'Wydarzenia' : 'Aktywność'} · ${fmt(day, { weekday: 'long', day: 'numeric', month: 'long' })}`;
  const groups = new Map();
  for (const e of entries) {
    if (!groups.has(e.source)) groups.set(e.source, []);
    groups.get(e.source).push(e);
  }
  $('day-dialog-list').innerHTML = [...groups].map(([source, list]) => `<section><h3>${escape(sourceOf(source)[1])}</h3>${list.map(e => `<button type="button" class="day-list-item" data-event="${visibleItems.indexOf(e)}" style="--event-color:${color(e.color, sourceOf(e.source)[2])}"><span class="event-main">${feelingMark(e.source)}<span>${escape(e.title)}</span></span><small>${e.done ? 'Wykonane' : e.forecast ? 'Plan' : 'Termin'}</small></button>`).join('')}</section>`).join('');
  $('day-dialog').showModal();
}
function render() {
  const days = weekDays(selected), items = Object.values(buckets).flatMap(b => b.items || []);
  if (!denseCalendarsInitialized && buckets.events?.status === 'ready') {
    const counts = new Map();
    for (const e of buckets.events.items) if (e.calendar && e.start != null) counts.set(e.calendar, (counts.get(e.calendar) || 0) + 1);
    for (const [calendar, count] of counts) if (count >= 50) hiddenCalendars.add(calendar);
    denseCalendarsInitialized = true;
    if (hiddenCalendars.size) saveFilters();
  }
  const search = $('search').value.trim().toLocaleLowerCase('pl');
  visibleItems = items.filter(e => !hiddenSources.has(e.source) && !hiddenCalendars.has(e.calendar) && (!search || `${e.title} ${e.detail}`.toLocaleLowerCase('pl').includes(search)));
  renderFilters(items);
  $('period').textContent = `${fmt(days[0], { day: 'numeric', month: 'short' })} – ${fmt(days[6], { day: 'numeric', month: 'short', year: 'numeric' })}`;
  const thursday = dateOf(days[3]), jan4 = weekStart(`${thursday.getFullYear()}-01-04`);
  $('week-number').textContent = `Tydz. ${1 + Math.round((dateOf(days[0]) - dateOf(jan4)) / 604800000)}`;
  $('days-header').innerHTML = '<div class="rail-label">' + escape(new Intl.DateTimeFormat('pl', { timeZoneName: 'short' }).formatToParts(new Date()).find(p => p.type === 'timeZoneName')?.value || '') + '</div>' + days.map(day => `<div class="day-heading ${day === dayKey() ? 'today' : ''}"><div class="weekday-name">${fmt(day, { weekday: 'short' })}</div><button class="day-number" data-date="${day}" aria-label="Plan dnia ${day}">${dateOf(day).getDate()}</button></div>`).join('');
  $('all-day').innerHTML = days.map(day => {
    const rows = visibleItems.filter(e => e.day === day && e.start == null);
    const events = rows.filter(e => e.source === 'events');
    const activity = rows.filter(e => e.source !== 'events');
    return `<div class="summary-column">${events.slice(0, 2).map(e => eventButton(e, visibleItems.indexOf(e))).join('')}${events.length > 2 ? `<button class="day-more" data-day-list="events" data-day="${day}">+${events.length - 2} wydarzeń</button>` : ''}${activity.length ? `<button class="day-activity" data-day-list="activity" data-day="${day}" title="Pokaż ${activity.length} wpisów"><span class="activity-dot"></span><span class="day-activity-label">${daySummary(activity)}</span><span class="activity-arrow">›</span></button>` : ''}${rows.length ? '' : '<div class="empty-day">—</div>'}</div>`;
  }).join('');
  $('timed').innerHTML = days.map(day => `<div class="timed-day" data-day="${day}">${layoutEvents(visibleItems.filter(e => e.day === day && e.start != null)).map(e => eventButton(e, visibleItems.findIndex(item => item.id === e.id), true)).join('')}</div>`).join('');
  updateNow();
  $('agenda').innerHTML = days.map(day => {
    const entries = visibleItems.filter(e => e.day === day).sort((a, b) => (a.start ?? -1) - (b.start ?? -1));
    return `<section class="agenda-section"><h2>${fmt(day, { weekday: 'long', day: 'numeric', month: 'short' })}</h2><div>${entries.map(e => `<button class="event-chip" style="--event-color:${color(e.color, sourceOf(e.source)[2])}" data-event="${visibleItems.indexOf(e)}"><time>${e.start == null ? 'Cały dzień' : clock(e.start)}</time><span class="event-main">${feelingMark(e.source)}<span>${e.done ? '✓ ' : e.forecast ? '◌ ' : ''}${escape(e.title)}</span></span></button>`).join('') || '<p class="muted">Brak wpisów z wybranych źródeł.</p>'}</div></section>`;
  }).join('');
  const errors = Object.entries(buckets).filter(([, b]) => b.status === 'error');
  const googleProblem = Boolean(buckets.events?.google?.syncError || buckets.events?.google?.partialSyncErrors?.length);
  $('status').textContent = `${visibleItems.length} wpisów · ${Object.keys(buckets).length < 13 ? 'Wczytywanie źródeł…' : 'Dane odświeżone'}${errors.length ? ` · ${errors.length} źródła niedostępne (szczegóły w panelu)` : ''}${googleProblem ? ' · Google: dane z pamięci, synchronizacja nieudana' : ''}`;
  $('source-status').innerHTML = Object.entries(buckets).map(([id, b]) => `<p>${escape(id === 'history' ? 'Historia' : id === 'weather' ? 'Pogoda' : sourceOf(id)[1])}: ${b.status === 'error' ? 'niedostępne' : 'wczytane'}${b.note ? ` · ${escape(b.note)}` : ''}</p>`).join('');
  const google = buckets.events?.google;
  $('google-status').textContent = googleProblem ? 'Google Calendar · błąd synchronizacji. Ponów połączenie, jeśli autoryzacja wygasła.' : google ? google.connected ? 'Google Calendar · połączony' : google.configured ? 'Google Calendar · wymaga połączenia' : 'Google Calendar · wymaga konfiguracji w ustawieniach dashboardu' : buckets.events?.status === 'error' ? 'Google Calendar · API niedostępne' : 'Google Calendar · ładowanie…';
  document.querySelector('.google-connect').hidden = Boolean(google?.connected) && !googleProblem;
  const weather = buckets.weather;
  if (weather) $('weather').textContent = weather.weather ? `Pogoda teraz · ${Math.round(weather.weather.now.temp)}°C\nOdczuwalna ${Math.round(weather.weather.now.feels)}°C · wiatr ${Math.round(weather.weather.now.wind)} km/h` : 'Pogoda teraz · niedostępna';
  renderMini();
}
function updateNow() {
  document.querySelectorAll('.now-line').forEach(e => e.remove());
  const column = document.querySelector(`.timed-day[data-day="${dayKey()}"]`);
  if (column) {
    const now = new Date(), line = document.createElement('div');
    line.className = 'now-line';
    line.style.top = `calc(${now.getHours() + now.getMinutes() / 60} * var(--hour))`;
    line.style.width = `${column.clientWidth}px`;
    column.append(line);
  }
}
async function refresh() {
  const version = ++generation;
  buckets = {}; render();
  await loadCalendar(weekDays(selected), (source, data) => { if (version !== generation) return; buckets[source] = data; render(); });
}
function navigate(day) { selected = day; miniMonth = day.slice(0, 7) + '-01'; refresh(); }
function showDetails(index) {
  const e = visibleItems[index]; if (!e) return;
  $('detail-source').textContent = sourceOf(e.source)[1] + (e.forecast ? ' · Prognoza / plan' : e.done ? ' · Wykonane' : '');
  $('detail-title').textContent = e.title;
  $('detail-time').textContent = fmt(e.day, { dateStyle: 'full' }) + (e.start == null ? ' · Bez godziny' : ` · ${clock(e.start)}${e.point ? '' : `–${clock(e.end)}`}`);
  $('detail-body').textContent = e.detail || '';
  $('detail-link').href = safeLink(e.href) || sourceOf(e.source)[3];
  $('detail-dialog').showModal();
}
$('previous').onclick = () => navigate(shiftDay(selected, -7));
$('next').onclick = () => navigate(shiftDay(selected, 7));
$('today').onclick = () => navigate(dayKey());
$('refresh').onclick = refresh;
$('search').oninput = render;
$('view').onchange = () => { $('week-view').hidden = $('view').value !== 'week'; $('agenda').hidden = $('view').value !== 'agenda'; };
$('toggle-sidebar').onclick = () => document.body.classList.toggle(matchMedia('(max-width:850px)').matches ? 'sidebar-open' : 'sidebar-hidden');
for (const [id, amount] of [['mini-prev', -1], ['mini-next', 1]]) $(id).onclick = () => { const d = dateOf(miniMonth); d.setMonth(d.getMonth() + amount); miniMonth = dayKey(d); renderMini(); };
document.addEventListener('click', event => {
  const dayList = event.target.closest('[data-day-list]'); if (dayList) showDayList(dayList.dataset.day, dayList.dataset.dayList);
  const item = event.target.closest('[data-event]'); if (item) { if ($('day-dialog').open) $('day-dialog').close(); showDetails(Number(item.dataset.event)); }
  const date = event.target.closest('[data-date]'); if (date) navigate(date.dataset.date);
  if (event.target.closest('[data-close]')) event.target.closest('dialog').close();
});
document.addEventListener('change', event => {
  const input = event.target;
  const set = input.dataset.source ? hiddenSources : input.dataset.calendar ? hiddenCalendars : null;
  if (!set) return;
  const id = input.dataset.source || input.dataset.calendar;
  if (input.checked) set.delete(id); else set.add(id);
  saveFilters(); render();
});
$('create').onclick = () => { $('event-form').reset(); $('event-form').elements.date.value = selected; $('event-form').elements.destination.value = buckets.events?.google?.connected ? 'google' : 'local'; $('form-error').textContent = ''; $('create-dialog').showModal(); };
$('event-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget, values = Object.fromEntries(new FormData(form));
  if ((values.startTime && !values.endTime) || (!values.startTime && values.endTime) || (values.endTime && values.endTime <= values.startTime)) { $('form-error').textContent = 'Podaj obie godziny; koniec musi być późniejszy niż początek.'; return; }
  const submit = form.querySelector('[type="submit"]'); submit.disabled = true; $('form-error').textContent = '';
  try {
    const payload = { id: `calendar-${crypto.randomUUID()}`, title: values.title.trim(), date: values.date, startTime: values.startTime || null, endTime: values.endTime || null, notes: values.notes, type: 'personal_event', source: 'local' };
    if (!payload.title) throw new Error('Wpisz tytuł wydarzenia.');
    const category = await saveEventCountdownCategory('Kalendarz');
    payload.category = category.category.id;
    payload.countdown = true;
    if (values.destination === 'google') await upsertGoogleCalendarEvent(payload); else await saveLocalDashboardEvent(payload);
    $('create-dialog').close(); navigate(values.date);
  } catch (error) { $('form-error').textContent = `Nie zapisano wydarzenia: ${error.message}`; } finally { submit.disabled = false; }
};
$('hours').innerHTML = Array.from({ length: 24 }, (_, h) => `<div class="hour-label">${String(h).padStart(2, '0')}:00</div>`).join('');
$('brand-day').textContent = new Date().getDate();
$('timezone').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
refresh();
requestAnimationFrame(() => { $('time-scroll').scrollTop = Math.max(0, new Date().getHours() - 2) * parseInt(getComputedStyle(document.documentElement).getPropertyValue('--hour')); });
setInterval(updateNow, 60000);
window.addEventListener('resize', updateNow);
setInterval(() => { if (!document.hidden && !$('create-dialog').open && !$('detail-dialog').open && !$('day-dialog').open) refresh(); }, 300000);
