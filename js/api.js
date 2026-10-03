// Compatibility facade for older imports. The cleaning UI uses cleaning-api.js directly.
import { setData } from './state.js';
import { render } from './render.js';
import { refreshCleaningActionHistory } from './cleaning-history.js';
import { getActiveCleaningApartmentId } from './cleaning-apartments.js';
import {
  getTasks as getLocalTasks,
  markDone as markDoneLocal,
} from './cleaning-api.js';

export async function bootDebug() {
  return true;
}

export async function fetchData() {
  const btn = document.getElementById('refresh');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Refreshing...';
  }
  try {
    const apartmentId = getActiveCleaningApartmentId();
    const [tasks] = await Promise.all([
      getLocalTasks(apartmentId),
      refreshCleaningActionHistory(apartmentId),
    ]);
    setData(tasks);
    render();
    return tasks;
  } catch (error) {
    console.error('Refresh failed:', error);
    return [];
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Refresh';
    }
  }
}

export async function markDone(taskId, opts = {}) {
  try {
    if (!taskId) return false;
    const history = opts.history && typeof opts.history === 'object' ? opts.history : {};
    const result = await markDoneLocal(taskId, {
      apartmentId: getActiveCleaningApartmentId(),
      doneAt: history.at,
      source: history.source || 'cleaning-page',
    });
    if (opts.refresh !== false) await fetchData();
    return result;
  } catch (error) {
    console.error('markDone exception:', error);
    return false;
  }
}

export async function getTasks() {
  return getLocalTasks(getActiveCleaningApartmentId());
}
