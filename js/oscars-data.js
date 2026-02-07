import { getOscarsConfig } from './oscars-config.js';
import * as api from './oscars-api.js';
import { normalizeCountryList } from './oscars-countries.js';
import { splitCategories } from './oscars-categories.js';

const STORAGE_PREFIX = 'oscars_watchlist_v2';
const LEGACY_KEYS = ['oscars_watchlist_v1', 'oscars_watchlist_v2'];
const MIGRATION_FLAG = 'oscars_watchlist_migrated_v1';
const staticCache = new Map();
let lastYear = null;
let resolvedMode = null;
let resolvingMode = null;

function storageKey(year) {
  return `${STORAGE_PREFIX}_${year}`;
}

function toBool(value) {
  if (typeof value === 'boolean') return value;
  if (value === null || value === undefined) return false;
  const s = String(value).trim().toUpperCase();
  return ['1', 'TRUE', 'YES', 'TAK'].includes(s);
}

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(String(value).replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

function toInt(value) {
  const n = toNumber(value);
  return Number.isFinite(n) ? Math.round(n) : null;
}

function normalizeCategoryList(value) {
  const list = splitCategories(value);
  return list.length ? list.join('; ') : null;
}

function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function resolvePoster(url, apiBase) {
  if (!url) return url;
  if (typeof url !== 'string') return url;
  if (url.startsWith('/posters/')) {
    return apiBase ? `${apiBase}${url}` : `.${url}`;
  }
  return url;
}

function normalizeRow(row, idx, apiBase, year) {
  const out = { ...row };
  out.id = Number(out.id) || idx + 1;
  out.watched = toBool(out.watched);
  out.watched_date = out.watched_date ? String(out.watched_date) : null;
  out.rating_1_10 = toNumber(out.rating_1_10);
  out.nominations_number = toInt(out.nominations_number);
  out.won_categories = normalizeCategoryList(out.won_categories);
  out.country = normalizeCountryList(out.country) || null;
  out.poster_url = resolvePoster(out.poster_url, apiBase);
  if (Number.isFinite(year)) out.oscars_year = year;
  return out;
}

function normalizeRows(rows, apiBase, year) {
  return Array.isArray(rows) ? rows.map((row, idx) => normalizeRow(row, idx, apiBase, year)) : [];
}

function readStored(year, apiBase) {
  try {
    const raw = localStorage.getItem(storageKey(year));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return normalizeRows(parsed, apiBase, year);
    if (parsed && Array.isArray(parsed.rows)) return normalizeRows(parsed.rows, apiBase, year);
    return null;
  } catch {
    return null;
  }
}

function writeStored(year, rows) {
  try {
    localStorage.setItem(storageKey(year), JSON.stringify({ year, rows }));
  } catch {
    // ignore storage failures
  }
}

function groupByYear(rows, fallbackYear) {
  const groups = new Map();
  rows.forEach((row, idx) => {
    const fromRow = Number(row.oscars_year);
    const year = Number.isFinite(fromRow) ? fromRow : fallbackYear;
    if (!Number.isFinite(year)) return;
    if (!groups.has(year)) groups.set(year, []);
    groups.get(year).push({ ...row, id: row.id || idx + 1, oscars_year: year });
  });
  return groups;
}

function migrateLegacyStorage(year, apiBase) {
  try {
    if (localStorage.getItem(MIGRATION_FLAG)) return false;
  } catch {
    return false;
  }

  let migrated = false;
  LEGACY_KEYS.forEach((key) => {
    let raw = null;
    try {
      raw = localStorage.getItem(key);
    } catch {
      raw = null;
    }
    if (!raw) return;

    let parsed = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
    if (!parsed) return;

    const rows = Array.isArray(parsed) ? parsed : parsed.rows || [];
    if (!Array.isArray(rows) || !rows.length) return;

    const groups = groupByYear(rows, Number.isFinite(year) ? year : null);
    groups.forEach((list, groupYear) => {
      try {
        if (localStorage.getItem(storageKey(groupYear))) return;
      } catch {
        // ignore
      }
      const normalized = normalizeRows(list, apiBase, groupYear);
      writeStored(groupYear, normalized);
      staticCache.set(groupYear, normalized);
      migrated = true;
    });
  });

  if (migrated) {
    try {
      localStorage.setItem(MIGRATION_FLAG, new Date().toISOString());
    } catch {
      // ignore
    }
  }

  return migrated;
}

async function loadSeed(year, staticBase, apiBase) {
  const res = await fetch(`${staticBase}/${year}.json`, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Missing data file for ${year}`);
  }
  const json = await res.json();
  const rows = Array.isArray(json) ? json : json.rows || [];
  return normalizeRows(rows, apiBase, year);
}

async function ensureStaticList(year) {
  if (!Number.isFinite(year)) {
    throw new Error('Year is required');
  }
  lastYear = year;
  const cached = staticCache.get(year);
  if (cached) return cached;

  const cfg = getOscarsConfig();
  migrateLegacyStorage(year, cfg.apiBase);
  const stored = readStored(year, cfg.apiBase);
  if (stored && stored.length) {
    staticCache.set(year, stored);
    return stored;
  }

  const seed = await loadSeed(year, cfg.staticBase, cfg.apiBase);
  staticCache.set(year, seed);
  writeStored(year, seed);
  return seed;
}

async function probeApi(apiBase) {
  if (!apiBase) return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1200);
  try {
    const res = await fetch(`${apiBase}/api/oscars/years`, {
      cache: 'no-store',
      signal: controller.signal
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function resolveMode() {
  if (resolvedMode) return resolvedMode;
  if (resolvingMode) return resolvingMode;

  const cfg = getOscarsConfig();
  if (cfg.mode !== 'auto') {
    resolvedMode = cfg.mode;
    return resolvedMode;
  }

  resolvingMode = (async () => {
    const ok = await probeApi(cfg.apiBase);
    return ok ? 'api' : 'static';
  })();

  resolvedMode = await resolvingMode;
  resolvingMode = null;
  return resolvedMode;
}

function getResolvedModeSync() {
  if (resolvedMode) return resolvedMode;
  const cfg = getOscarsConfig();
  return cfg.mode === 'auto' ? 'static' : cfg.mode;
}

function applyPatch(item, patch) {
  const next = { ...item, ...patch };

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

  if ('won_categories' in patch) {
    next.won_categories = normalizeCategoryList(patch.won_categories);
  }

  if ('poster_url' in patch) {
    const cfg = getOscarsConfig();
    next.poster_url = resolvePoster(patch.poster_url, cfg.apiBase);
  }

  return next;
}

export function getOscarsFootnote() {
  const cfg = getOscarsConfig();
  const mode = getResolvedModeSync();
  if (mode === 'api') {
    const base = cfg.apiBase ? `API: ${cfg.apiBase}` : 'API';
    return `${base}. Changes sync across devices.`;
  }
  if (mode === 'static') {
    return 'Local browser storage. Changes are saved only on this device.';
  }
  return 'Loading data source...';
}

export async function fetchOscars(year) {
  const mode = await resolveMode();
  if (mode === 'api') return api.fetchOscars(year);
  return ensureStaticList(year);
}

export async function updateOscars(id, patch, year = null) {
  const mode = await resolveMode();
  if (mode === 'api') return api.updateOscars(id, patch, year);

  const targetYear = Number.isFinite(year) ? year : lastYear;
  const list = await ensureStaticList(targetYear);
  const idx = list.findIndex((item) => String(item.id) === String(id));
  if (idx === -1) throw new Error('Item not found');

  const next = applyPatch(list[idx], patch);
  list[idx] = next;
  staticCache.set(targetYear, list);
  writeStored(targetYear, list);
  return next;
}

export async function fetchPosters(limit = 50, force = false, year) {
  const mode = await resolveMode();
  if (mode === 'api') return api.fetchPosters(limit, force, year);
  return {
    ok: true,
    attempted: 0,
    updated: 0,
    missing: 0,
    providers: { omdb: false, tmdb: false },
    message: 'Poster fetch requires API mode.'
  };
}

export async function fetchOscarsDetails(limit = 50, force = false, year) {
  const mode = await resolveMode();
  if (mode === 'api') return api.fetchOscarsDetails(limit, force, year);
  return {
    ok: true,
    attempted: 0,
    updated: 0,
    missing: 0,
    providers: { tmdb: false, omdb: false, wikidata: false },
    message: 'Details fetch requires API mode.'
  };
}

export async function fetchOscarsWinners(force = false, year) {
  const mode = await resolveMode();
  if (mode === 'api') return api.fetchOscarsWinners(force, year);
  return {
    ok: true,
    updated_rows: 0,
    updated_files: 0,
    matched_rows: 0,
    source: null,
    message: 'Winners import requires API mode.'
  };
}

export async function resetOscars(year) {
  const mode = await resolveMode();
  if (mode === 'api') return api.resetOscars(year);
  if (!Number.isFinite(year)) throw new Error('Year is required');
  const cfg = getOscarsConfig();
  const seed = await loadSeed(year, cfg.staticBase, cfg.apiBase);
  staticCache.set(year, seed);
  writeStored(year, seed);
  return { ok: true, rows: seed };
}

export async function fetchOscarsYears() {
  const mode = await resolveMode();
  if (mode === 'api') return api.fetchOscarsYears();

  const cfg = getOscarsConfig();
  const res = await fetch(`${cfg.staticBase}/years.json`, { cache: 'no-store' });
  if (!res.ok) {
    return [];
  }
  const data = await res.json();
  const years = Array.isArray(data) ? data : data.years || [];
  return years.map((y) => Number(y)).filter((y) => Number.isFinite(y));
}

export async function fetchOscarsAll(years = null) {
  const list = Array.isArray(years) && years.length ? years : await fetchOscarsYears();
  const uniq = Array.from(new Set(list.filter((y) => Number.isFinite(y))));
  const results = await Promise.all(
    uniq.map(async (y) => {
      try {
        return await fetchOscars(y);
      } catch {
        return [];
      }
    })
  );
  return results.flat();
}

export async function resolveOscarsMode() {
  return resolveMode();
}

export function getOscarsMode() {
  return getResolvedModeSync();
}
