import { dayKey, dateOf, shiftDay, weekStart, minuteOf, timeOf, expandEvent } from './calendar-model.js';
import { fetchDashboardEvents } from './events-api.js';
import { fetchTimelineActivity } from './timeline-activity-api.js';
import { getCleaningSettings, getTasks, getCleaningHistory } from './cleaning-api.js';
import { buildCleaningForecastSeries, getCleaningForecastRampStart } from './cleaning-history.js';
import { fetchReadingState, fetchReadingHistory } from './reading-api.js';
import { buildReadingForecastSeries } from './reading-history.js';
import { snapshotToHabits } from './habits-app-api.js';
import { getReminderOccurrences } from './habits-reminder-schedule.js';
import { isHabitComplete } from './habits-app-model.js';
import { createLanguageApi } from './language/api.js';
import { ankiDailyProgress, mainAnkiDecks } from './language/anki-daily.js';
import { fetchFinanceBills } from './budget-api.js';
import { liveWorkoutRuntimeUrl } from './live-workout-runtime-api.js';
import { fetchWeather } from './api/openMeteo.js';

async function json(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.ok === false) throw new Error(data.error || 'Błąd źródła');
    return data;
  } finally { clearTimeout(timeout); }
}
const summary = (source, day, title, detail = '', extra = {}) => ({ id: `${source}:${day}:${title}`, source, day, title, detail, start: null, ...extra });
const at = (value) => { const d = new Date(value); return { day: dayKey(d), start: minuteOf(timeOf(d)), point: true }; };

export async function loadCalendar(days, onSource) {
  const from = days[0], to = days.at(-1), today = dayKey();
  const offset = Math.round((dateOf(weekStart(from)) - dateOf(weekStart(today))) / 604800000);
  const options = { range: 'week', offset, now: new Date() };
  const jobs = {
    events: async () => {
      const data = await fetchDashboardEvents({ showPastEvents: true });
      return { items: data.events.flatMap(e => expandEvent(e, days)), google: data.google,
        note: data.google?.syncError || (data.google?.partialSyncErrors?.length ? 'Część kalendarzy Google nie została zsynchronizowana.' : '') };
    },
    history: async () => {
      const data = await fetchTimelineActivity({ from, to, sources: ['cleaning', 'reading', 'emotions'], journalContent: 'metadata' });
      const items = [];
      for (const day of data.days || []) {
        for (const source of ['cleaning', 'reading']) {
          const rows = day.events.filter(e => e.source === source);
          if (!rows.length) continue;
          const count = source === 'reading' ? rows.reduce((n, e) => n + Number(e.metrics?.pages || 0), 0) : rows.length;
          items.push(summary(source, day.date, `${source === 'reading' ? 'Przeczytane strony' : source === 'cleaning' ? 'Sprzątanie wykonane' : 'Nawyki wykonane'}: ${count}`, rows.map(e => [e.title, e.summary].filter(Boolean).join(' · ')).join('\n'), { done: true }));
        }
        for (const e of day.events.filter(e => e.source === 'emotions')) {
          items.push({ ...summary('emotions', day.date, e.title, [e.summary, e.details].filter(Boolean).join('\n')), id: e.id, ...at(e.occurredAt) });
        }
      }
      return { items, note: data.sources.filter(s => !s.available).map(s => `${s.label}: niedostępne`).join(', ') };
    },
    cleaning: async () => {
      if (to < today) return { items: [] };
      const settings = await getCleaningSettings();
      const apartment = settings.activeApartmentId || settings.settings?.activeApartmentId || 'aleja-pokoju6';
      const [tasks, history] = await Promise.all([getTasks(apartment), getCleaningHistory(apartment)]);
      const historyEvents = (history.events || history.actions || []).map(e => ({ ...e, at: e.at || e.doneAt }));
      return { items: buildCleaningForecastSeries(tasks, { ...options, historyEvents, planStart: getCleaningForecastRampStart(tasks) })
        .filter(d => d.dayKey >= today && d.count).map(d => summary('cleaning', d.dayKey, `Sprzątanie: ${d.count} zadań`, d.tasks.map(t => `${t.label || t.task || t.name} ×${t.count}`).join('\n'), { forecast: true })) };
    },
    reading: async () => {
      if (to < today) return { items: [] };
      const [state, history] = await Promise.all([fetchReadingState(), fetchReadingHistory()]);
      const books = state.activeBooks || state.books || [];
      return { items: buildReadingForecastSeries(books, { ...options, log: history.log || {}, todayPlan: history.forecastPlan?.dayKey === today ? history.forecastPlan.books : {} })
        .filter(d => d.dayKey >= today && d.count).map(d => summary('reading', d.dayKey, `Czytanie: ${d.count} stron`, (d.books || []).map(b => `${b.label}: ${b.count}`).join('\n'), { forecast: true })) };
    },
    todos: async () => {
      const data = await json('/api/settings/todo');
      return { items: (data.data || []).filter(t => t.due || t.dueDate).map(t => {
        const due = t.due || t.dueDate;
        return summary('todos', due.slice(0, 10), t.title, t.description || '', { id: `todo:${t.id}`, done: t.done, start: minuteOf(t.dueTime || due.split('T')[1]), point: true });
      }) };
    },
    emotions: async () => {
      const data = await json(`/api/feelings/checkins?from=${shiftDay(from, -1)}&to=${shiftDay(to, 1)}&limit=5000`);
      return { items: (data.checkins || []).map(e => ({ ...summary('emotions', '', (e.emotions || []).map(m => m.name).join(', ') || 'How I Feel', [e.note, (e.tags || []).map(t => t.name).join(' · ')].filter(Boolean).join('\n')), ...at(e.occurredAt), id: `feelings:${e.id}`, color: e.emotions?.[0]?.color || e.emotion?.color })) };
    },
    bills: async () => {
      const data = await fetchFinanceBills();
      return { items: (data.bills || []).map(b => summary('bills', b.due, `${b.name} · ${(b.amountCents / 100).toLocaleString('pl-PL')} zł`, b.note || b.provider, { id: `bill:${b.id}`, done: b.paid })) };
    },
    bm365: async () => {
      const data = await json(`/api/bm365/state?today=${today}`);
      return { items: (data.rows || []).filter(a => days.includes(a.date)).map(a => summary('bm365', a.date, `${a.artist} · ${a.album}`, 'Album dnia · BM365', { done: a.listened === true || a.listened === 'TAK' })) };
    },
    phone: async () => {
      const data = await json(`/api/phone-tracker/summary?range=custom&start=${from}&end=${to}&tz=${encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone)}`);
      return { items: (data.daily_usage_seconds || []).map(d => summary('phone', d.day, `Telefon: ${Math.round(d.seconds / 60)} min`, 'Zarejestrowany czas korzystania z aplikacji', { done: true })) };
    },
    habits: async () => {
      const data = await json(`/api/habits/snapshot?from=${from}&to=${to}`);
      const items = [];
      const untimed = new Map();
      const habits = snapshotToHabits(data);
      for (const day of days.filter(d => d <= today)) {
        const recorded = habits.filter(h => h.entries.has(day));
        const complete = recorded.filter(h => isHabitComplete(h, h.entries.get(day)));
        if (recorded.length) items.push(summary('habits', day, `Habitsy: ${complete.length}/${recorded.length} wykonane`, recorded.map(h => `${isHabitComplete(h, h.entries.get(day)) ? '✓' : '○'} ${h.name}`).join('\n'), { done: complete.length === recorded.length }));
      }
      for (const h of habits.filter(h => !h.archived)) for (const day of days.filter(d => d >= today)) {
        const done = isHabitComplete(h, h.entries.get(day) ?? null);
        const occurrences = getReminderOccurrences(h, day, data.reminderTimeGroups);
        for (const occurrence of occurrences) items.push(summary('habits', day, h.name, 'Zaplanowane przypomnienie', { id: occurrence.occurrenceKey, start: minuteOf(occurrence.localTime), done, point: true }));
        if (!h.reminderConfig.enabled && h.frequency[0] === h.frequency[1] && !done) {
          if (!untimed.has(day)) untimed.set(day, []);
          untimed.get(day).push(h.name);
        }
      }
      for (const [day, names] of untimed) items.push(summary('habits', day, `Habitsy: ${names.length} do wykonania`, names.join('\n'), { forecast: true }));
      return { items };
    },
    workout: async () => {
      const [planResult, historyResult] = await Promise.allSettled([json(liveWorkoutRuntimeUrl('plan')), json(`${liveWorkoutRuntimeUrl('history')}?limit=1000`)]);
      if (planResult.status === 'rejected' && historyResult.status === 'rejected') throw new Error('Runtime treningów niedostępny');
      const plan = planResult.value || {}, sessions = historyResult.value?.sessions || [];
      const items = sessions.filter(s => s.status === 'finished').map(s => ({ ...summary('workout', '', `Trening · ${Math.round(s.duration_seconds / 60)} min`, s.workout_type, { done: true }), ...at(Number(s.started_at)), point: false, id: `session:${s.id}`, duration: s.duration_seconds / 60 }));
      for (const w of plan.schedule || []) if (w.date >= today && !items.some(e => e.day === w.date)) items.push(summary('workout', w.date, w.type === 'rest' ? 'Regeneracja' : `Trening · ${w.duration || plan.total_duration_minutes || '—'} min`, w.title || w.type, { forecast: true }));
      return { items, note: [planResult.status === 'rejected' ? 'Plan niedostępny' : '', historyResult.status === 'rejected' ? 'Historia niedostępna' : ''].filter(Boolean).join(' · ') };
    },
    anki: async () => {
      const api = createLanguageApi(), profiles = await api.profiles(), items = [], seenDecks = new Set();
      let unavailable = false;
      for (const p of profiles.items || []) {
        const status = await api.ankiStatus(p.id);
        if (status.status === 'UNAVAILABLE') { unavailable = true; continue; }
        const decks = mainAnkiDecks(status.decks || []).filter(d => !seenDecks.has(d.name));
        const progress = ankiDailyProgress(decks);
        if (days.includes(today) && progress.planned) items.push(summary('anki', today, `Anki: ${progress.done}/${progress.planned} kart`, p.name || p.languageCode, { id: `anki:${p.id}:today` }));
        for (const deck of decks) {
          seenDecks.add(deck.name);
          try {
            const data = await api.ankiInsights(p.id, { deck: deck.name, limit: 1 });
            for (const d of data.history || []) if (d.date < today && d.reviews) items.push(summary('anki', d.date, `Anki: ${d.reviews} odpowiedzi`, deck.name, { id: `anki:${p.id}:${deck.name}:${d.date}`, done: true }));
            for (const d of data.forecast || []) if (d.scheduledReviews) items.push(summary('anki', d.date, `Anki: ${d.scheduledReviews} powtórek`, `${deck.name}\nPrognoza bez kolejnych odpowiedzi i zmian terminów.`, { id: `anki:${p.id}:${deck.name}:${d.date}`, forecast: true }));
          } catch { unavailable = true; }
        }
      }
      return { items, note: unavailable ? 'Część danych Anki niedostępna. Historia obejmuje ostatnie 30 dni.' : 'Historia Anki: ostatnie 30 dni; przyszłość: dostępna prognoza powtórek.' };
    },
    weather: async () => ({ items: [], weather: await fetchWeather() }),
  };
  await Promise.allSettled(Object.entries(jobs).map(async ([source, run]) => {
    try {
      const data = await run();
      data.items = data.items.filter(e => days.includes(e.day)).map(e => ({ ...e, end: e.start == null ? null : Math.min(1440, e.end ?? e.start + (e.duration || 30)) }));
      onSource(source, { ...data, status: 'ready' });
    } catch (error) { onSource(source, { status: 'error', items: [], note: error.message }); }
  }));
}
