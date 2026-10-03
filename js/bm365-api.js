const LOCAL_API_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  && window.location.port !== '8000'
  ? 'http://127.0.0.1:8000'
  : '';

export const BM365_API_BASE = `${LOCAL_API_BASE}/api/bm365`;

async function request(path, options = {}) {
  const response = await fetch(`${BM365_API_BASE}${path}`, {
    cache: 'no-store',
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw new Error(payload?.error || `BM365 API failed: ${response.status}`);
  }
  return payload;
}

function queryString(filters = {}) {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
  });
  const value = query.toString();
  return value ? `?${value}` : '';
}

export function getBm365State(today) {
  return request(`/state${queryString({ today })}`);
}

export function getBm365Albums(filters) {
  return request(`/albums${queryString(filters)}`);
}

export function markBm365Listened({ rowId, date, listened = true }) {
  return request('/mark', {
    method: 'POST',
    body: JSON.stringify({ rowId, date, listened }),
  });
}

export function rateBm365Album({ rowId, date, artist, album, rating }) {
  return request('/rate', {
    method: 'POST',
    body: JSON.stringify({ rowId, date, artist, album, rating }),
  });
}

export function updateBm365Metadata(rowId, patch) {
  return request(`/albums/${encodeURIComponent(String(rowId))}/metadata`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export function getBm365Summary() {
  return request('/summary');
}

export function syncBm365Sheets() {
  return request('/sync-sheets', { method: 'POST', body: '{}' });
}
