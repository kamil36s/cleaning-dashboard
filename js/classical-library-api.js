const API_BASE = '';
const STATIC_COMPOSER_INDEX = new URL('../data/classical-library/composers/index.json', import.meta.url);
const STATIC_PROGRESS_URL = new URL('../data/classical-library/progress/progress.json', import.meta.url);
const STATIC_KNOWN_URL = new URL('../data/classical-library/known-composers.json', import.meta.url);

let lastDataSource = 'api';
let staticCache = null;

function apiUrl(path, params = {}) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return;
    url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function parseError(res) {
  const text = await res.text().catch(() => '');
  if (!text) return `API error: ${res.status}`;
  try {
    return JSON.parse(text).error || `API error: ${res.status}`;
  } catch {
    return text;
  }
}

async function getJson(path, params = {}) {
  const res = await fetch(apiUrl(path, params), { cache: 'no-store' });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

async function postJson(path, body = {}) {
  const res = await fetch(apiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

async function fetchStaticJson(url, fallback) {
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) return fallback;
    return res.json();
  } catch {
    return fallback;
  }
}

function flattenWorks(composer) {
  const rows = [];
  const visit = (works, level = 0, parentWorkId = null) => {
    (Array.isArray(works) ? works : []).forEach((work) => {
      rows.push({ ...work, composerId: work.composerId || composer.composerId, level, parentWorkId: work.parentWorkId || parentWorkId });
      visit(work.parts || [], level + 1, work.workId);
    });
  };
  visit(composer?.works || []);
  return rows;
}

function buildSummary(composers, progress) {
  const rows = composers.flatMap((composer) => flattenWorks(composer).map((work) => ({ work, composer })));
  const visible = rows.filter(({ work }) => !work.hidden);
  const listened = visible.filter(({ work }) => ['Listened', 'Revisit'].includes(progress?.[work.workId]?.status)).length;
  const latest = visible
    .map(({ work, composer }) => ({ work, composer, progress: progress?.[work.workId] || null }))
    .filter((item) => item.progress && (item.progress.rating !== null || item.progress.status))
    .sort((a, b) => String(b.progress._updatedAt || '').localeCompare(String(a.progress._updatedAt || '')))[0];
  const fallback = composers.find((item) => item.composerId === 'maurice-ravel') || composers[0] || null;

  return {
    totalWorks: visible.length,
    listenedWorks: listened,
    composerCount: composers.length,
    featuredComposer: latest?.composer || fallback,
    latestRatedWork: latest?.progress?.rating != null ? latest.work : null,
    latestProgress: latest?.progress || null,
  };
}

async function loadStaticLibrary() {
  if (staticCache) return staticCache;
  const ids = await fetchStaticJson(STATIC_COMPOSER_INDEX, []);
  const composers = [];
  for (const id of ids) {
    const url = new URL(`../data/classical-library/composers/${id}.json`, import.meta.url);
    const composer = await fetchStaticJson(url, null);
    if (composer) composers.push(composer);
  }
  const progress = await fetchStaticJson(STATIC_PROGRESS_URL, {});
  const knownComposers = await fetchStaticJson(STATIC_KNOWN_URL, []);
  staticCache = {
    ok: true,
    composers,
    progress,
    knownComposers,
    summary: buildSummary(composers, progress),
  };
  return staticCache;
}

async function withStaticFallback(loader) {
  try {
    const data = await loader();
    lastDataSource = 'api';
    return data;
  } catch (error) {
    const data = await loadStaticLibrary();
    lastDataSource = 'static';
    return data;
  }
}

function readonlyError() {
  return new Error('Saving requires the local dashboard API. Start the Python server or use the configured dev proxy.');
}

export function getClassicalDataSource() {
  return lastDataSource;
}

export async function fetchClassicalLibrary() {
  return withStaticFallback(() => getJson('/api/classical-library'));
}

export async function fetchClassicalSummary() {
  return withStaticFallback(() => getJson('/api/classical-library/summary'));
}

export async function searchComposerCandidates(query, limit = 10) {
  try {
    const data = await getJson('/api/classical-library/search-composers', { q: query, limit });
    lastDataSource = 'api';
    return Array.isArray(data?.results) ? data.results : [];
  } catch (error) {
    const data = await loadStaticLibrary();
    lastDataSource = 'static';
    const q = String(query || '').trim().toLowerCase();
    return (data.knownComposers || [])
      .filter((item) => !q || `${item.name || ''} ${item.birthPlace || ''}`.toLowerCase().includes(q))
      .slice(0, limit);
  }
}

export async function updateWorkProgress(workId, patch) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/progress/update', { workId, patch });
}

export async function updateComposerMetadata(composerId, patch) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/composer/update', { composerId, patch });
}

export async function uploadComposerImage({ composerId, filename, mimeType, contentBase64 }) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/composer/image', {
    composerId,
    filename,
    mimeType,
    contentBase64,
  });
}

export async function updateWorkMetadata(composerId, workId, patch) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/work/update', { composerId, workId, patch });
}

export async function addComposer(payload) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/composer/add', payload);
}

export async function refreshComposerProfile(composerId) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/composer/refresh', { composerId });
}

export async function importComposerWorks(composerId, payload = {}) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/works/import', { composerId, ...payload });
}

export async function refreshComposerWorks(composerId) {
  if (lastDataSource === 'static') throw readonlyError();
  return postJson('/api/classical-library/works/refresh', { composerId });
}

export { flattenWorks, buildSummary };
