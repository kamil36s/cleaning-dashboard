import { getOscarsConfig } from './oscars-config.js';

const API_BASE = getOscarsConfig().apiBase || '';

function withYear(path, year) {
  if (!year) return `${API_BASE}${path}`;
  return `${API_BASE}${path}?year=${encodeURIComponent(year)}`;
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

function normalizeRow(row) {
  const posterUrl = row.poster_url;
  const resolvedPoster =
    typeof posterUrl === 'string' && posterUrl.startsWith('/posters/')
      ? (API_BASE ? `${API_BASE}${posterUrl}` : posterUrl)
      : posterUrl;
  return {
    ...row,
    watched: toBool(row.watched),
    rating_1_10: toNumber(row.rating_1_10),
    nominations_number: toInt(row.nominations_number),
    poster_url: resolvedPoster
  };
}

function normalizeRows(rows) {
  return Array.isArray(rows) ? rows.map(normalizeRow) : [];
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

export async function fetchOscars(year) {
  const res = await fetch(withYear('/api/oscars', year), { cache: 'no-store' });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  const data = await res.json();
  const rows = Array.isArray(data) ? data : data.rows || [];
  return normalizeRows(rows);
}

export async function updateOscars(id, patch, year = null) {
  const res = await fetch(`${API_BASE}/api/oscars/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ id, patch, year })
  });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return res.json();
}

export async function fetchPosters(limit = 50, force = false, year) {
  const res = await fetch(`${API_BASE}/api/oscars/posters`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ limit, force, year })
  });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return res.json();
}

export async function fetchOscarsDetails(limit = 50, force = false, year) {
  const res = await fetch(`${API_BASE}/api/oscars/details`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ limit, force, year })
  });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return res.json();
}

export async function fetchOscarsWinners(force = false, year) {
  const res = await fetch(`${API_BASE}/api/oscars/winners`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ force, year })
  });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return res.json();
}

export async function resetOscars(year) {
  const res = await fetch(`${API_BASE}/api/oscars/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ year })
  });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return res.json();
}

export async function fetchOscarsYears() {
  const res = await fetch(`${API_BASE}/api/oscars/years`, { cache: 'no-store' });
  if (!res.ok) {
    const err = await parseJson(res);
    throw new Error(err.error || `API error: ${res.status}`);
  }
  const data = await res.json();
  const years = Array.isArray(data) ? data : data.years || [];
  return years.map((y) => Number(y)).filter((y) => Number.isFinite(y));
}
