import { OSCARS_SEED } from './oscars-seed.js';

const STORAGE_KEY = 'oscars_watchlist_v1';
let cache = null;

const toNumber = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(String(value).replace(',', '.'));
  return Number.isFinite(n) ? n : null;
};

const toInt = (value) => {
  const n = toNumber(value);
  return Number.isFinite(n) ? Math.round(n) : null;
};

const toBool = (value) => {
  if (typeof value === 'boolean') return value;
  if (value === null || value === undefined) return false;
  const s = String(value).trim().toUpperCase();
  if (['TRUE', '1', 'YES', 'TAK'].includes(s)) return true;
  if (['FALSE', '0', 'NO', 'NIE'].includes(s)) return false;
  return false;
};

export function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function normalize(row, idx) {
  const out = { ...row };
  out.id = Number(out.id) || (idx + 1);
  out.watched = toBool(out.watched);
  out.watched_date = out.watched_date ? String(out.watched_date) : null;
  out.rating_1_10 = toNumber(out.rating_1_10);
  out.nominations_number = toInt(out.nominations_number);
  return out;
}

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch (e) {
    // ignore storage failures
  }
}

export function loadOscars(options = {}) {
  const force = options.force === true;
  if (cache && !force) return cache;

  let stored = null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    stored = raw ? JSON.parse(raw) : null;
  } catch (e) {
    stored = null;
  }

  if (Array.isArray(stored) && stored.length) {
    cache = stored.map(normalize);
    return cache;
  }

  cache = OSCARS_SEED.map(normalize);
  persist();
  return cache;
}

export function saveAll(list) {
  cache = Array.isArray(list) ? list.map(normalize) : OSCARS_SEED.map(normalize);
  persist();
  return cache;
}

export function updateItem(id, patch = {}) {
  const data = loadOscars();
  const idx = data.findIndex((item) => String(item.id) === String(id));
  if (idx === -1) return null;

  const current = data[idx];
  const next = { ...current, ...patch };

  if ('watched' in patch) {
    next.watched = toBool(patch.watched);
    if (next.watched && !next.watched_date) next.watched_date = todayISO();
    if (!next.watched) next.watched_date = null;
  }

  if ('watched_date' in patch) {
    next.watched_date = patch.watched_date ? String(patch.watched_date) : null;
  }

  if ('rating_1_10' in patch) {
    const n = toNumber(patch.rating_1_10);
    next.rating_1_10 = Number.isFinite(n) ? Math.max(0, Math.min(10, n)) : null;
  }

  if ('nominations_number' in patch) {
    next.nominations_number = toInt(patch.nominations_number);
  }

  data[idx] = next;
  cache = data;
  persist();
  return next;
}

export function resetOscars() {
  cache = OSCARS_SEED.map(normalize);
  persist();
  return cache;
}
