import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../js/cleaning-history.js', async (importOriginal) => ({
  ...(await importOriginal()),
  getCleaningActionHistory: () => [],
  refreshCleaningActionHistory: vi.fn(async () => []),
}));

vi.mock('../js/cleaning-api.js', () => ({
  deleteCleaningAction: vi.fn(),
}));

vi.mock('../js/cleaning-apartments.js', () => ({
  getActiveCleaningApartmentId: () => 'aleja-pokoju6',
}));

import { render, setCleaningTaskViewMode } from '../js/render.js';
import { setData } from '../js/state.js';

const task = (overrides) => ({
  id: overrides.id,
  row: overrides.id,
  room: overrides.room,
  category: overrides.category || 'Inne',
  task: overrides.task,
  freq: 7,
  lastDone: '',
  daysSince: overrides.daysSince,
  nextDueIn: overrides.nextDueIn,
  overdue: overrides.overdue,
  articles: '',
});

describe('cleaning page room groups', () => {
  afterEach(() => {
    setCleaningTaskViewMode('room');
    localStorage.removeItem('cleaningDashboard.taskView.v1');
    setData([]);
    document.body.innerHTML = '';
  });

  it('keeps blocked mop cards and their progress bars grey until purchase', () => {
    document.body.innerHTML = `
      <span id="kpi-today"></span><span id="kpi-overdue"></span>
      <span id="kpi-total"></span><span id="kpi-delay"></span><span id="kpi-coming"></span>
      <select id="room"><option value="ALL">All rooms</option></select>
      <select id="category"><option value="ALL">All categories</option></select>
      <select id="sort"><option value="priority">Priority</option></select>
      <input id="dueOnly" type="checkbox">
      <div id="grid" class="grid"></div>
    `;
    const mop = task({ id: 5, room: 'Pokój', task: 'Umyj podłogę mopem', daysSince: 30, nextDueIn: 0, overdue: true });
    setData([{ ...mop, blocked: true }]);
    render();

    const card = document.querySelector('#grid .card');
    expect(card?.classList.contains('blocked')).toBe(true);
    expect(card?.querySelector('.progress > div')?.classList.contains('blocked')).toBe(true);
    expect(card?.querySelector('.pill-blocked')?.disabled).toBe(true);

    setData([mop]);
    render();
    expect(card?.classList.contains('blocked')).toBe(false);
    expect(card?.querySelector('.progress > div')?.classList.contains('dead')).toBe(true);
  });

  it('renders alphabetical room sections with priority-sorted cards', () => {
    document.body.innerHTML = `
      <span id="kpi-today"></span>
      <span id="kpi-overdue"></span>
      <span id="kpi-total"></span>
      <span id="kpi-delay"></span>
      <span id="kpi-coming"></span>
      <select id="room"><option value="ALL">All rooms</option></select>
      <select id="category"><option value="ALL">All categories</option></select>
      <select id="sort"><option value="priority">Priority</option></select>
      <input id="dueOnly" type="checkbox">
      <div id="cleaning-view-switcher">
        <button data-cleaning-view="all"></button>
        <button data-cleaning-view="room"></button>
        <button data-cleaning-view="category"></button>
      </div>
      <div id="grid" class="grid"></div>
    `;
    setData([
      task({ id: 1, room: 'Sypialnia', task: 'Due sypialnia', daysSince: 7, nextDueIn: 0, overdue: false }),
      task({ id: 2, room: 'Kuchnia', task: 'Overdue kuchnia', daysSince: 10, nextDueIn: 0, overdue: true }),
      task({ id: 3, room: 'Kuchnia', task: 'Dead kuchnia', daysSince: 16, nextDueIn: 0, overdue: true }),
      task({ id: 5, room: 'Kuchnia', task: 'Fresh kuchnia', daysSince: 2, nextDueIn: 5, overdue: false }),
      task({ id: 4, room: 'Łazienka', task: 'Due łazienka', daysSince: 7, nextDueIn: 0, overdue: false }),
    ]);

    render();

    const groups = [...document.querySelectorAll('.cleaning-room-group')].map((group) => ({
      room: group.querySelector('.cleaning-room-name')?.textContent,
      count: group.querySelector('.cleaning-room-count')?.textContent,
      tasks: [...group.querySelectorAll('.card .title > span:last-child')]
        .map((title) => title.textContent),
      progress: group.querySelector('.cleaning-room-progress-label')?.textContent,
      progressValue: group.querySelector('.cleaning-room-progress-track')?.getAttribute('aria-valuenow'),
      progressWidth: group.querySelector('.cleaning-room-progress-fill')?.style.width,
      progressColor: group.querySelector('.cleaning-room-progress-fill')?.style.getPropertyValue('--cleaning-group-progress-color'),
    }));
    expect(groups).toEqual([
      {
        room: 'Kuchnia',
        count: '3 zadania',
        tasks: ['Dead kuchnia', 'Overdue kuchnia', 'Fresh kuchnia'],
        progress: '1/3 aktualne · 33%',
        progressValue: '1',
        progressWidth: '33%',
        progressColor: '#e13f47',
      },
      {
        room: 'Łazienka',
        count: '1 zadanie',
        tasks: ['Due łazienka'],
        progress: '0/1 aktualne · 0%',
        progressValue: '0',
        progressWidth: '0%',
        progressColor: '#430069',
      },
      {
        room: 'Sypialnia',
        count: '1 zadanie',
        tasks: ['Due sypialnia'],
        progress: '0/1 aktualne · 0%',
        progressValue: '0',
        progressWidth: '0%',
        progressColor: '#430069',
      },
    ]);
  });

  it('switches between cached category and flat task views', () => {
    document.body.innerHTML = `
      <span id="kpi-today"></span>
      <span id="kpi-overdue"></span>
      <span id="kpi-total"></span>
      <span id="kpi-delay"></span>
      <select id="room"><option value="ALL">All rooms</option></select>
      <select id="category"><option value="ALL">All categories</option></select>
      <select id="sort"><option value="priority">Priority</option></select>
      <input id="dueOnly" type="checkbox">
      <div id="cleaning-view-switcher">
        <button data-cleaning-view="all"></button>
        <button data-cleaning-view="room"></button>
        <button data-cleaning-view="category"></button>
      </div>
      <div id="grid" class="grid"></div>
    `;
    setData([
      task({ id: 1, room: 'Kuchnia', category: 'Podłogi', task: 'Mop', daysSince: 10, nextDueIn: 0, overdue: true }),
      task({ id: 2, room: 'Salon', category: 'Kurz', task: 'Biurko', daysSince: 2, nextDueIn: 5, overdue: false }),
      task({ id: 3, room: 'Salon', category: 'Podłogi', task: 'Odkurzanie', daysSince: 7, nextDueIn: 0, overdue: false }),
    ]);

    setCleaningTaskViewMode('category');
    render();

    expect(localStorage.getItem('cleaningDashboard.taskView.v1')).toBe('category');
    expect([...document.querySelectorAll('.cleaning-room-name')].map((node) => node.textContent))
      .toEqual(['Kurz', 'Podłogi']);
    expect([...document.querySelectorAll('.cleaning-room-kicker')].map((node) => node.textContent))
      .toEqual(['Kategoria', 'Kategoria']);
    expect(document.querySelector('[data-cleaning-view="category"]')?.classList.contains('is-active')).toBe(true);

    setCleaningTaskViewMode('all');
    render();

    expect(document.querySelectorAll('.cleaning-room-group')).toHaveLength(0);
    expect(document.querySelectorAll('#grid > .card')).toHaveLength(3);
    expect(document.getElementById('grid')?.classList.contains('cleaning-flat-view')).toBe(true);
    expect(localStorage.getItem('cleaningDashboard.taskView.v1')).toBe('all');
  });
});
