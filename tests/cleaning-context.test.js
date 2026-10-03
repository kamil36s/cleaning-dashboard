import { describe, expect, it } from 'vitest';
import {
  generateCleaningContext,
  mapCleaningSessionStatus,
} from '../js/cleaning-context.js';

describe('cleaning context export', () => {
  const tasks = [
    {
      id: 91,
      room: 'Kuchnia',
      category: 'Blaty',
      task: 'Umyj blat',
      status: 'OVERDUE',
      nextDueIn: 0,
      notes: 'Najpierw zebrać rzeczy',
      articles: 'Ściereczka, spray',
    },
    {
      id: 92,
      room: 'Łazienka',
      category: 'Umywalka',
      task: 'Umyj umywalkę',
      status: 'DUE',
      nextDueIn: 0,
    },
    {
      id: 93,
      room: 'Pokój',
      category: 'Porządek',
      task: 'Odłóż ubrania',
      status: 'FRESH',
      lastDone: '2026-09-24T09:20:00Z',
    },
    {
      id: 94,
      room: 'Salon',
      category: 'Okna',
      task: 'Umyj okna',
      status: 'COMING',
    },
  ];

  it('builds a stable full snapshot from real task fields without technical ids', () => {
    const text = generateCleaningContext({
      apartmentLabel: 'Mieszkanie',
      tasks,
      doneToday: [{ actionId: 7, taskId: 93, doneAt: '2026-09-24T09:20:00Z' }],
      sessionNotes: 'Mam około godzinę.',
    }, {
      generatedAt: '2026-09-24T09:35:00Z',
    });

    expect(text).toContain('Generated: 2026-09-24 11:35');
    expect(text).toContain('### W TRAKCIE\nBrak.');
    expect(text).toContain('### TODO\n- Kuchnia — Umyj blat');
    expect(text).toContain('Notes: Najpierw zebrać rzeczy');
    expect(text).toContain('Potrzebne środki: Ściereczka, spray');
    expect(text).toContain('- Łazienka — Umyj umywalkę');
    expect(text).toContain('### ZROBIONE\n- Pokój — Odłóż ubrania');
    expect(text).toContain('Ukończono: 2026-09-24 11:20');
    expect(text).toContain('- Salon — Umyj okna');
    expect(text).toContain('### ODŁOŻONE\nBrak.');
    expect(text).toContain('Mam około godzinę.');
    expect(text).not.toContain('id: 91');

    const headings = ['### W TRAKCIE', '### TODO', '### ZROBIONE', '### ODŁOŻONE'];
    expect(headings.map((heading) => text.indexOf(heading))).toEqual(
      [...headings.map((heading) => text.indexOf(heading))].sort((a, b) => a - b),
    );
  });

  it('keeps every empty section and supports compact mode', () => {
    const full = generateCleaningContext({ tasks: [] }, { generatedAt: '2026-09-24T09:35:00Z' });
    expect(full.match(/Brak\./g)).toHaveLength(5);

    const compact = generateCleaningContext({ tasks: tasks.slice(0, 1) }, { mode: 'compact' });
    expect(compact).toContain('W TRAKCIE:\nBrak.');
    expect(compact).toContain('TODO:\n- Kuchnia — Umyj blat');
    expect(compact).not.toContain('## SESSION MODE');
  });

  it('maps compatible status aliases and leaves urgency statuses as TODO', () => {
    expect(mapCleaningSessionStatus({ sessionStatus: 'W TRAKCIE' })).toBe('IN_PROGRESS');
    expect(mapCleaningSessionStatus({ session_status: 'ODŁOŻONE' })).toBe('DEFERRED');
    expect(mapCleaningSessionStatus({ status: 'OVERDUE' })).toBe('TODO');
  });
});
