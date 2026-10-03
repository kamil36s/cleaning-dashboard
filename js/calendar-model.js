export const SOURCES = [
  ['events', 'Wydarzenia', '#8ab4f8', './index.html#events'],
  ['cleaning', 'Sprzątanie', '#64c7ae', './cleaning.html'],
  ['reading', 'Czytanie', '#c6a3ed', './reading.html'],
  ['emotions', 'How I Feel', '#ed91b4', './index.html#feelings'],
  ['anki', 'Anki', '#f4c66d', './language.html'],
  ['phone', 'Phone Activity', '#79b9ca', './phone-activity.html'],
  ['bm365', 'BM365', '#b0a0ed', './bm365.html'],
  ['todos', 'Todo · terminy', '#e5b65e', './todo.html'],
  ['bills', 'Rachunki', '#e6917b', './budget.html'],
  ['workout', 'Treningi', '#91bd72', './live-workout.html'],
  ['habits', 'Habitsy', '#7ebca1', './index.html#habits-app'],
];
export const dayKey = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
export const dateOf = (key) => new Date(`${key}T00:00:00`);
export function shiftDay(key, amount) { const d = dateOf(key); d.setDate(d.getDate() + amount); return dayKey(d); }
export function weekStart(key) { return shiftDay(key, -((dateOf(key).getDay() + 6) % 7)); }
export const weekDays = (key) => Array.from({ length: 7 }, (_, i) => shiftDay(weekStart(key), i));
export const minuteOf = (value) => { const m = /^(\d{2}):(\d{2})/.exec(value || ''); return m ? Number(m[1]) * 60 + Number(m[2]) : null; };
export const timeOf = (date) => `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
export const safeLink = (url) => { try { const u = new URL(url, 'http://localhost'); return ['http:', 'https:'].includes(u.protocol) ? url : ''; } catch { return ''; } };

// Split at local midnight; Google all-day end dates are exclusive.
export function expandEvent(event, days) {
  const start = event.external?.start;
  const end = event.external?.end;
  const timed = Boolean(start?.dateTime || event.startTime);
  const a = start?.dateTime ? new Date(start.dateTime) : dateOf(start?.date || event.date);
  if (Number.isNaN(a.getTime())) return [];
  if (!start?.dateTime && timed) a.setMinutes(minuteOf(event.startTime) || 0);
  let b = end?.dateTime ? new Date(end.dateTime) : end?.date ? dateOf(end.date) : null;
  if (!b && timed) { b = dateOf(event.date); b.setMinutes(minuteOf(event.endTime) ?? ((minuteOf(event.startTime) || 0) + 60)); if (b <= a) b.setDate(b.getDate() + 1); }
  if (!b) b = dateOf(shiftDay(dayKey(a), 1));
  return days.flatMap((day) => {
    const lo = dateOf(day), hi = dateOf(shiftDay(day, 1));
    if (a >= hi || b <= lo) return [];
    return [{ id: `${event.id}:${day}`, source: 'events', day, title: event.title || 'Wydarzenie',
      start: timed ? (a < lo ? 0 : a.getHours() * 60 + a.getMinutes()) : null,
      end: timed ? (b >= hi ? 1440 : b.getHours() * 60 + b.getMinutes()) : null,
      detail: [event.external?.calendarSummary, event.notes].filter(Boolean).join('\n'),
      calendar: event.external?.displayCalendarId || event.external?.calendarId || 'local',
      calendarLabel: event.external?.calendarSummary || 'Dashboard',
      color: event.external?.calendarColor, href: safeLink(event.external?.htmlLink) || './index.html#events' }];
  });
}

// Each connected overlap group gets stable, non-overlapping columns.
export function layoutEvents(events) {
  const sorted = events.map(e => ({ ...e, visualEnd: Math.max(e.end ?? e.start + 30, e.start + 24) }))
    .sort((a, b) => a.start - b.start || b.visualEnd - a.visualEnd);
  let group = [], groupEnd = -1;
  const result = [];
  const flush = () => { const ends = []; for (const e of group) { let col = ends.findIndex(end => end <= e.start); if (col < 0) col = ends.length; ends[col] = e.visualEnd; e.column = col; } result.push(...group.map(e => ({ ...e, columns: ends.length }))); };
  for (const e of sorted) { if (e.start >= groupEnd && group.length) { flush(); group = []; groupEnd = -1; } group.push(e); groupEnd = Math.max(groupEnd, e.visualEnd); }
  if (group.length) flush();
  return result;
}
