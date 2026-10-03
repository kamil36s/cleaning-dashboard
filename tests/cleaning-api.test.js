import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  addTask,
  deleteCleaningAction,
  deleteTask,
  getCleaningHistory,
  getTasks,
  markDone,
  updateTask,
} from '../js/cleaning-api.js';

describe('local cleaning API client', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, tasks: [{ id: 7, task: 'Biurko' }] }),
    });
  });

  it('reads tasks for the selected apartment', async () => {
    await expect(getTasks('aleja-pokoju6')).resolves.toEqual([{ id: 7, task: 'Biurko' }]);
    expect(fetch).toHaveBeenCalledWith(
      '/api/cleaning/tasks?apartment=aleja-pokoju6',
      expect.objectContaining({ cache: 'no-store' }),
    );
  });

  it('uses stable REST routes for CRUD and completion', async () => {
    await addTask('classic', { task: 'Test', room: 'Pokój', category: 'Inne', freq: 7 });
    await updateTask(12, { freq: 14 });
    await markDone(12, { apartmentId: 'classic', source: 'cleaning-widget' });
    await deleteTask(12);
    await getCleaningHistory('classic', { range: 'year', offset: -1 });
    await deleteCleaningAction(44, 'classic');

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/cleaning/tasks',
      '/api/cleaning/tasks/12',
      '/api/cleaning/tasks/12/done',
      '/api/cleaning/tasks/12',
      '/api/cleaning/history?apartment=classic&range=year&offset=-1',
      '/api/cleaning/history/actions/44?apartment=classic',
    ]);
    expect(fetch.mock.calls[3][1].method).toBe('DELETE');
    expect(fetch.mock.calls[5][1].method).toBe('DELETE');
  });
});
