import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('../js/events-api.js', () => ({ fetchDashboardEvents: vi.fn(async () => ({ events: [], google: { connected: true } })) }));
vi.mock('../js/timeline-activity-api.js', () => ({ fetchTimelineActivity: vi.fn(async () => ({ days: [], sources: [] })) }));
vi.mock('../js/cleaning-api.js', () => ({ getCleaningSettings: vi.fn(async () => ({ activeApartmentId: 'home' })), getTasks: vi.fn(async () => []), getCleaningHistory: vi.fn(async () => ({ actions: [] })) }));
vi.mock('../js/cleaning-history.js', () => ({ buildCleaningForecastSeries: vi.fn(() => []), getCleaningForecastRampStart: vi.fn() }));
vi.mock('../js/reading-api.js', () => ({ fetchReadingState: vi.fn(async () => ({ activeBooks: [] })), fetchReadingHistory: vi.fn(async () => ({ log: {} })) }));
vi.mock('../js/reading-history.js', () => ({ buildReadingForecastSeries: vi.fn(() => []) }));
vi.mock('../js/language/api.js', () => ({ createLanguageApi: () => ({ profiles: async () => ({ items: [] }) }) }));
vi.mock('../js/budget-api.js', () => ({ fetchFinanceBills: vi.fn(async () => ({ bills: [{ id: 'rent', name: 'Rent', due: '2026-10-01', amountCents: 12345, paid: false }] })) }));
vi.mock('../js/api/openMeteo.js', () => ({ fetchWeather: vi.fn(async () => ({ now: { temp: 15 } })) }));
import { loadCalendar } from '../js/calendar-data.js';
import { weekDays } from '../js/calendar-model.js';

let unavailablePhone;
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-01T12:00:00'));
  unavailablePhone = false;
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url.includes('/phone-tracker/') && unavailablePhone) throw new Error('Phone offline');
    let payload = {};
    if (url.includes('/settings/todo')) payload = { data: [{ id: 'todo', title: 'Deadline', due: '2026-10-01', dueTime: '14:30' }, { id: 'no-date', title: 'Backlog' }] };
    if (url.includes('/feelings/')) payload = { checkins: [{ id: 'mood', occurredAt: '2026-10-01T09:15:00', emotions: [{ name: 'Calm', color: '#51c891' }], note: '<b>note</b>' }] };
    if (url.includes('/bm365/')) payload = { rows: [{ date: '2026-10-01', artist: 'A', album: 'B', listened: 'NIE' }, { date: '2026-10-02', artist: 'C', album: 'D', listened: 'TAK' }] };
    if (url.includes('/phone-tracker/')) payload = { daily_usage_seconds: [{ day: '2026-10-01', seconds: 3600 }] };
    if (url.includes('/habits/')) payload = { habits: [{ id: 'water', name: 'Water', type: 'BOOLEAN', frequencyNumerator: 1, frequencyDenominator: 1 }], entries: [{ habitId: 'water', date: '2026-09-30', status: 'DONE' }] };
    if (url.includes('/live-workout/history')) payload = { sessions: [] };
    return { ok: true, json: async () => payload };
  }));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
async function load() { const sources = {}; await loadCalendar(weekDays('2026-10-01'), (id, data) => { sources[id] = data; }); return sources; }
describe('calendar source adapters', () => {
  it('uses real deadlines, canonical feelings and BM365 completion semantics', async () => {
    const sources = await load();
    expect(Object.keys(sources)).toHaveLength(13);
    expect(sources.todos.items).toHaveLength(1);
    expect(sources.todos.items[0].start).toBe(870);
    expect(sources.emotions.items[0]).toMatchObject({ title: 'Calm', start: 555, point: true, detail: '<b>note</b>', color: '#51c891' });
    expect(sources.bm365.items.map(i => i.done)).toEqual([false, true]);
    expect(sources.phone.items[0].title).toBe('Telefon: 60 min');
    expect(sources.habits.items.find(i => i.day === '2026-09-30').done).toBe(true);
    expect(sources.habits.items.find(i => i.day === '2026-10-01').forecast).toBe(true);
  });
  it('keeps successful sources when a service is unavailable', async () => {
    unavailablePhone = true;
    const sources = await load();
    expect(sources.phone).toMatchObject({ status: 'error', items: [], note: 'Phone offline' });
    expect(sources.bills.status).toBe('ready');
    expect(sources.bills.items).toHaveLength(1);
  });
});
