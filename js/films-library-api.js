import { getOscarsConfig } from './oscars-config.js';

const API_BASE = getOscarsConfig().apiBase || '';
const STATIC_SNAPSHOT_URL = './data/films/library.json';

let staticSnapshotPromise = null;
let lastFilmsDataSource = API_BASE ? 'api' : 'static';

function withQuery(path, params = {}) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return;
    url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function parseJson(res) {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

async function getJson(path, params = {}) {
  const res = await fetch(withQuery(path, params), { cache: 'no-store' });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return res.json();
}

async function postJson(path, body = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return res.json();
}

async function loadStaticSnapshot() {
  if (!staticSnapshotPromise) {
    staticSnapshotPromise = fetch(STATIC_SNAPSHOT_URL, { cache: 'no-store' }).then(async (res) => {
      if (!res.ok) {
        throw new Error(`Missing static snapshot: ${res.status}`);
      }
      return res.json();
    });
  }
  return staticSnapshotPromise;
}

function isLikelyNetworkError(error) {
  const message = String(error?.message || error || '');
  return /Failed to fetch|NetworkError|Load failed|fetch/i.test(message);
}

function projectStaticItem(item, listSlug = null) {
  const memberships = Array.isArray(item?.lists) ? item.lists : [];
  const selected = listSlug ? memberships.find((entry) => entry.slug === listSlug) || null : null;

  return {
    ...item,
    selected_nominated_categories: selected?.nominated_categories || null,
    selected_won_categories: selected?.won_categories || null,
    selected_nominations_number: selected?.nominations_number ?? null,
    selected_where_to_watch: selected?.where_to_watch || null,
  };
}

function filterStaticItems(snapshot, { list = null, q = '', limit = 60, offset = 0 } = {}) {
  const lists = Array.isArray(snapshot?.lists) ? snapshot.lists : [];
  const selectedList = list ? lists.find((entry) => entry.slug === list) || null : null;
  const normalizedQuery = String(q || '').trim().toLowerCase();

  let items = Array.isArray(snapshot?.items) ? snapshot.items.slice() : [];

  if (list) {
    items = items.filter((item) =>
      Array.isArray(item?.lists) && item.lists.some((entry) => entry.slug === list)
    );
  }

  if (normalizedQuery) {
    items = items.filter((item) => {
      const haystack = [item?.title, item?.director, item?.notes]
        .map((value) => String(value || '').toLowerCase())
        .join(' ');
      return haystack.includes(normalizedQuery);
    });
  }

  const total = items.length;
  const pageLimit = Math.max(1, Number(limit) || 60);
  const pageOffset = Math.max(0, Number(offset) || 0);
  items = items.slice(pageOffset, pageOffset + pageLimit);

  return {
    selected_list: selectedList,
    items: items.map((item) => projectStaticItem(item, list)),
    pagination: {
      limit: pageLimit,
      offset: pageOffset,
      total,
      has_more: pageOffset + items.length < total,
    },
  };
}

async function withStaticFallback(loadApi, fallback) {
  try {
    const data = await loadApi();
    lastFilmsDataSource = 'api';
    return data;
  } catch (error) {
    const snapshot = await loadStaticSnapshot();
    lastFilmsDataSource = 'static';
    return fallback(snapshot, error);
  }
}

function readonlyError(message) {
  return new Error(message || 'Biblioteka działa teraz w trybie tylko do odczytu.');
}

export function getFilmsApiBase() {
  return API_BASE;
}

export function getFilmsDataSource() {
  return lastFilmsDataSource;
}

export async function fetchFilmSummary() {
  return withStaticFallback(
    () => getJson('/api/films/summary'),
    (snapshot) => snapshot?.summary || {}
  );
}

export async function fetchFilmLists() {
  return withStaticFallback(
    async () => {
      const data = await getJson('/api/films/lists');
      return Array.isArray(data?.lists) ? data.lists : [];
    },
    (snapshot) => (Array.isArray(snapshot?.lists) ? snapshot.lists : [])
  );
}

export async function fetchFilmLibrary({ list = null, q = '', limit = 60, offset = 0 } = {}) {
  return withStaticFallback(
    () => getJson('/api/films/library', { list, q, limit, offset }),
    (snapshot) => filterStaticItems(snapshot, { list, q, limit, offset })
  );
}

export async function searchFilms(query, limit = 8) {
  try {
    const data = await getJson('/api/films/search', { q: query, limit });
    lastFilmsDataSource = 'api';
    return Array.isArray(data?.results) ? data.results : [];
  } catch (error) {
    if (isLikelyNetworkError(error)) {
      throw readonlyError('Wyszukiwanie wymaga lokalnego API biblioteki.');
    }
    throw error;
  }
}

export async function createFilmList(payload) {
  try {
    const data = await postJson('/api/films/lists/create', payload);
    lastFilmsDataSource = 'api';
    return data?.list || null;
  } catch (error) {
    if (isLikelyNetworkError(error)) {
      throw readonlyError('Tworzenie list wymaga lokalnego API biblioteki.');
    }
    throw error;
  }
}

export async function addFilmToLibrary(payload) {
  try {
    const data = await postJson('/api/films/library/add', payload);
    lastFilmsDataSource = 'api';
    return data?.film || null;
  } catch (error) {
    if (isLikelyNetworkError(error)) {
      throw readonlyError('Dodawanie filmów wymaga lokalnego API biblioteki.');
    }
    throw error;
  }
}

export async function updateFilmLibrary(id, patch) {
  try {
    const data = await postJson('/api/films/library/update', { id, patch });
    lastFilmsDataSource = 'api';
    return data?.film || null;
  } catch (error) {
    if (isLikelyNetworkError(error)) {
      throw readonlyError('Zapisywanie zmian wymaga lokalnego API biblioteki.');
    }
    throw error;
  }
}
