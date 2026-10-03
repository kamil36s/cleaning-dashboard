const API = '/api/music';

function url(path, params = {}) {
  const result = new URL(`${API}${path}`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) result.searchParams.set(key, String(value));
  });
  return result.toString();
}

async function errorMessage(response) {
  const text = await response.text().catch(() => '');
  try { return JSON.parse(text).error || `Błąd API ${response.status}`; } catch {
    if (response.status === 404 && /<!doctype|<html/i.test(text)) {
      return 'Music API nie jest dostępne. Uruchom ponownie server.py, aby załadować nowe trasy i katalog.';
    }
    return text || `Błąd API ${response.status}`;
  }
}

async function get(path, params) {
  const response = await fetch(url(path, params), { cache: 'no-store' });
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

async function post(path, payload = {}) {
  const response = await fetch(url(path), {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

export const musicApi = {
  overview: () => get('/overview'),
  library: (filters) => get('/library', filters),
  missingMetadata: (filters) => get('/missing-metadata', filters),
  enrichmentStatus: () => get('/enrichment/status'),
  queueEnrichment: (limit = 50) => post('/enrichment/queue', { limit }),
  release: (id) => get(`/releases/${id}`),
  rate: (id, rating) => post(`/releases/${id}/rating`, { rating }),
  uploadCover: (id, dataUrl) => post(`/releases/${id}/cover`, { dataUrl }),
  uploadArtwork: (kind, key, dataUrl) => post('/artwork', { kind, key, dataUrl }),
  fetchCover: (id) => post(`/releases/${id}/cover/fetch`),
  fetchMissingCovers: (limit = 25) => post('/covers/fetch', { limit }),
  genres: (filters) => get('/genres', filters),
  genreTree: () => get('/genres/tree'),
  genre: (id) => get(`/genres/${id}`),
  rankings: () => get('/rankings'),
  artistRanking: (filters) => get('/rankings/artists', filters),
  ranking: (id) => get(`/rankings/${id}`),
  createRanking: (payload) => post('/rankings', payload),
  rankingEntry: (id, payload) => post(`/rankings/${id}/entries`, payload),
  lists: () => get('/lists'),
  createList: (payload) => post('/lists', payload),
  listEntry: (id, payload) => post(`/lists/${id}/entries`, payload),
  search: (q, limit = 8) => get('/search', { q, limit }),
  lastfm: (params) => get('/lastfm', params),
  previewImport: (payload) => post('/imports/preview', payload),
  commitImport: (id, resolutions) => post(`/imports/${id}/commit`, { resolutions }),
  importBatch: (id) => get(`/imports/${id}`),
  syncLegacy: () => post('/legacy/sync'),
};
