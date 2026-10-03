const API_BASE = '/api/reading';

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) {
    const error = new Error(payload?.error || response.statusText || `Reading API error (${response.status})`);
    error.status = response.status;
    error.code = payload?.code || 'reading_api_error';
    throw error;
  }
  return payload;
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body !== undefined && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    ...options,
    headers,
    body: options.body === undefined || typeof options.body === 'string'
      ? options.body
      : JSON.stringify(options.body),
  });
  return readJson(response);
}

export function fetchReadingState() {
  return request('/state');
}

export function fetchReadingBooks() {
  return request('/books');
}

export function createReadingBook(book) {
  return request('/books', { method: 'POST', body: book });
}

export function updateReadingBook(bookId, book) {
  return request(`/books/${encodeURIComponent(bookId)}`, {
    method: 'PATCH',
    body: book,
  });
}

export function updateReadingBookProgress(bookId, pageCurrent, options = {}) {
  return request(`/books/${encodeURIComponent(bookId)}/progress`, {
    method: 'PATCH',
    body: {
      pageCurrent,
      recordHistory: options.recordHistory !== false,
      ...(options.day ? { day: options.day } : {}),
    },
  });
}

export function fetchReadingHistory() {
  return request('/history');
}

export function saveReadingHistory(history) {
  return request('/history', { method: 'POST', body: history });
}

export function fetchReadingSettings() {
  return request('/settings');
}

export function saveReadingSettings(settings) {
  return request('/settings', { method: 'POST', body: settings });
}
