const API_BASE = '/api/cleaning';
import { refreshCleaningGoalAfterAction } from './phone-cleaning-gate.js';
import { resolveCleaningDependencies } from './cleaning-dependencies.js';

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) {
    const error = new Error(payload?.error || response.statusText || 'Cleaning API error');
    error.code = payload?.code || 'cleaning_api_error';
    error.status = response.status;
    throw error;
  }
  return payload;
}

const apartmentQuery = (apartmentId, params = {}) => {
  const query = new URLSearchParams({ apartment: String(apartmentId || '') });
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value));
  });
  return query.toString();
};

export async function getCleaningState(apartmentId) {
  return requestJson(`/state?${apartmentQuery(apartmentId)}`);
}

export async function getTasks(apartmentId, filters = {}) {
  const payload = await requestJson(`/tasks?${apartmentQuery(apartmentId, filters)}`);
  return resolveCleaningDependencies(payload?.tasks);
}

export async function addTask(apartmentId, data) {
  return requestJson('/tasks', {
    method: 'POST',
    body: JSON.stringify({ ...data, apartmentId }),
  });
}

export async function updateTask(taskId, data) {
  return requestJson(`/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteTask(taskId) {
  return requestJson(`/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
}

export async function markDone(taskId, options = {}) {
  const result = await requestJson(`/tasks/${encodeURIComponent(taskId)}/done`, {
    method: 'POST',
    body: JSON.stringify({
      apartmentId: options.apartmentId,
      doneAt: options.doneAt,
      source: options.source || 'cleaning-page',
    }),
  });
  if (options.apartmentId) refreshCleaningGoalAfterAction(options.apartmentId,getCleaningState).catch(() => {});
  return result;
}

export async function getCleaningHistory(apartmentId, options = {}) {
  return requestJson(`/history?${apartmentQuery(apartmentId, {
    range: options.range || 'all',
    offset: options.offset ?? 0,
  })}`);
}

export async function undoCleaningAction(actionId) {
  const result = await requestJson('/history/undo', {
    method: 'POST',
    body: JSON.stringify({ actionId }),
  });
  if (result?.action?.apartmentId) refreshCleaningGoalAfterAction(result.action.apartmentId,getCleaningState).catch(() => {});
  return result;
}

export async function deleteCleaningAction(actionId, apartmentId) {
  return requestJson(`/history/actions/${encodeURIComponent(actionId)}?${apartmentQuery(apartmentId)}`, {
    method: 'DELETE',
  });
}

export async function getCleaningSettings() {
  return requestJson('/settings');
}

export async function saveCleaningSettings(settings) {
  return requestJson('/settings', {
    method: 'POST',
    body: JSON.stringify({ settings }),
  });
}
