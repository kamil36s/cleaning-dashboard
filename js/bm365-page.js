import { fmtDateTimeShort } from './utils.js';
import { getBm365Albums } from './bm365-api.js';

const CONFIG = {
  FIELDS: {
    date: 'date',
    artist: 'artist',
    album: 'album',
    listened: 'listened',
    rating: 'rating',
    minutes: 'minutes',
    rowId: 'rowId'
  }
};

const DASH = '\u2014';
const MONTHS_PL = [
  'stycznia',
  'lutego',
  'marca',
  'kwietnia',
  'maja',
  'czerwca',
  'lipca',
  'sierpnia',
  'września',
  'października',
  'listopada',
  'grudnia'
];

const COVER_CACHE_KEY = 'bm365_cover_cache_v1';
const COVER_CACHE_TTL_DAYS = 30;
const COVER_MISS_TTL_DAYS = 7;

const UPLOAD_STORAGE_KEY = 'bm365_uploads_v1';
const LOCAL_API_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  ? 'http://127.0.0.1:8000'
  : '';
const UPLOAD_API = LOCAL_API_BASE ? `${LOCAL_API_BASE}/api/bm365/cover` : '';
const COVER_BATCH_API = LOCAL_API_BASE ? `${LOCAL_API_BASE}/api/bm365/covers` : '';

const MB_RELEASE_API = 'https://musicbrainz.org/ws/2/release/';
const CAA_RELEASE_API = 'https://coverartarchive.org/release/';
const MB_MIN_DELAY_MS = 1100;
let mbLastCall = 0;
let mbQueue = Promise.resolve();

const $ = (id) => document.getElementById(id);

const STATE = {
  rows: [],
  filtered: [],
  renderToken: 0,
  uploads: loadUploadMap(),
  coverCache: loadCoverCache(),
  byKey: new Map()
};

let currentUploadKey = '';

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setFooter(msg) {
  setText('bm365-foot', msg || '');
}

function toNumber(x) {
  if (x === null || x === undefined) return null;
  const s = String(x).trim();
  if (!s) return null;
  const m = s.match(/-?\d+(?:[.,]\d+)?/);
  if (!m) return null;
  const n = Number(m[0].replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

function safeText(value, fallback = '-') {
  const str = String(value ?? '').trim();
  return str ? str : fallback;
}

function pct(done, total) {
  if (!total) return 0;
  return Math.round((done / total) * 100);
}

function formatMinutes(totalMin) {
  if (!Number.isFinite(totalMin)) return '-';
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h <= 0) return `${m}m`;
  return `${h}h ${m}m`;
}

function formatBmDate(value) {
  if (!value) return '-';
  const str = String(value).trim();
  if (!str) return '-';

  const parts = str.split('-');
  if (parts.length === 3) {
    const year = Number(parts[0]);
    const month = Number(parts[1]);
    const day = Number(parts[2]);
    if (Number.isFinite(year) && Number.isFinite(month) && Number.isFinite(day)) {
      const label = MONTHS_PL[month - 1];
      if (label) return `${day} ${label}`;
    }
  }

  const dt = new Date(str);
  if (!Number.isNaN(dt.getTime())) {
    const label = MONTHS_PL[dt.getMonth()];
    if (label) return `${dt.getDate()} ${label}`;
  }

  return str;
}

function dayOfYear() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const diff = now - start;
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function updateBm365Progress(done, total) {
  const bar = $('bm365-progress-bar');
  const delta = $('bm365-progress-delta');
  if (!bar) return;

  const safeTotal = Number.isFinite(total) && total > 0 ? total : 0;
  const safeDone = Number.isFinite(done) ? Math.max(0, done) : 0;
  const clampedDone = safeTotal ? Math.min(safeDone, safeTotal) : 0;
  const pct = safeTotal ? (clampedDone / safeTotal) * 100 : 0;
  bar.style.width = `${pct}%`;

  if (!delta) return;
  delta.classList.remove('is-ahead', 'is-behind');
  if (!safeTotal) {
    delta.style.width = '0%';
    delta.style.left = '0%';
    return;
  }

  const target = Math.min(dayOfYear(), safeTotal);
  const targetPct = (target / safeTotal) * 100;
  let deltaPct = 0;
  let leftPct = 0;

  if (clampedDone > target) {
    deltaPct = ((clampedDone - target) / safeTotal) * 100;
    leftPct = targetPct;
    delta.classList.add('is-ahead');
  } else if (clampedDone < target) {
    deltaPct = ((target - clampedDone) / safeTotal) * 100;
    leftPct = pct;
    delta.classList.add('is-behind');
  } else {
    deltaPct = 0;
    leftPct = pct;
  }

  delta.style.width = `${Math.min(100, Math.max(0, deltaPct))}%`;
  delta.style.left = `${Math.min(100, Math.max(0, leftPct))}%`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function enqueueMb(task) {
  const next = mbQueue.then(task).catch(() => '');
  mbQueue = next.then(
    () => undefined,
    () => undefined
  );
  return next;
}

function normalizeRows(raw) {
  const rows = Array.isArray(raw) ? raw : raw?.rows || [];
  const f = CONFIG.FIELDS;

  return rows
    .map((r) => {
      const date = String(r?.[f.date] || '').trim();
      if (!date) return null;

      const artist = String(r?.[f.artist] || '').trim();
      const album = String(r?.[f.album] || '').trim();
      const listened = String(r?.[f.listened] || '').toUpperCase() === 'TAK';
      const rating = toNumber(r?.[f.rating]);
      const minutes = toNumber(r?.[f.minutes]);
      const rowId = r?.[f.rowId] ?? null;

      return {
        date,
        artist,
        album,
        listened,
        rating,
        minutes,
        rowId,
        year: date.slice(0, 4),
        key: coverKey(artist, album),
        search: `${artist} ${album}`.toLowerCase()
      };
    })
    .filter(Boolean);
}

function assignDayIndex(rows) {
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  sorted.forEach((row, idx) => {
    row.dayIndex = idx + 1;
  });
}

function computeStats(rows) {
  const total = rows.length;
  const done = rows.filter((r) => r.listened).length;
  const left = Math.max(0, total - done);

  const rated = rows.filter((r) => r.listened && Number.isFinite(r.rating));
  const avgRating = rated.length
    ? rated.reduce((sum, r) => sum + r.rating, 0) / rated.length
    : null;

  const timeRows = rows.filter((r) => r.listened && Number.isFinite(r.minutes));
  const totalMinutes = timeRows.reduce((sum, r) => sum + r.minutes, 0);

  return {
    total,
    done,
    left,
    pct: pct(done, total),
    avgRating,
    ratedCount: rated.length,
    totalMinutes
  };
}

function coverKey(artist, album) {
  return `${String(artist || '').trim()} ${DASH} ${String(album || '').trim()}`.toLowerCase();
}

function slugify(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function coverSlug(artist, album) {
  const a = slugify(artist);
  const b = slugify(album);
  const base = [a, b].filter(Boolean).join('--');
  return base || 'unknown';
}

function localCoverCandidates(artist, album) {
  const slug = coverSlug(artist, album);
  return [
    `./covers/${slug}.jpg`,
    `./covers/${slug}.jpeg`,
    `./covers/${slug}.png`,
    `./covers/${slug}.webp`
  ];
}

function tryLocalCover(artist, album) {
  const candidates = localCoverCandidates(artist, album);
  return new Promise((resolve) => {
    const tryAt = (i) => {
      if (i >= candidates.length) return resolve('');
      const url = candidates[i];
      const img = new Image();
      img.onload = () => resolve(url);
      img.onerror = () => tryAt(i + 1);
      img.src = url;
    };
    tryAt(0);
  });
}

function loadCoverCache() {
  try {
    return JSON.parse(localStorage.getItem(COVER_CACHE_KEY) || '{}');
  } catch {
    return {};
  }
}

function saveCoverCache(cache) {
  try {
    localStorage.setItem(COVER_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // ignore quota errors
  }
}

function isFresh(ts, ttlDays) {
  if (!ts) return false;
  const ageMs = Date.now() - ts;
  return ageMs < ttlDays * 24 * 60 * 60 * 1000;
}

function upgradeArtworkUrl(url, sizePx = 600) {
  if (!url) return '';
  return String(url).replace(/\/(\d+)x(\d+)bb\.(jpg|png)/i, `/${sizePx}x${sizePx}bb.$3`);
}

async function fetchCoverItunes(artist, album) {
  const term = `${artist} ${album}`.trim();
  if (!term) return '';

  const u = new URL('https://itunes.apple.com/search');
  u.searchParams.set('term', term);
  u.searchParams.set('entity', 'album');
  u.searchParams.set('limit', '1');

  const res = await fetch(u.toString());
  if (!res.ok) return '';
  const data = await res.json();
  const item = data?.results?.[0];
  const art = item?.artworkUrl100 || item?.artworkUrl60 || '';
  return upgradeArtworkUrl(art, 600);
}

async function fetchCoverMusicBrainz(artist, album) {
  const term = `${artist} ${album}`.trim();
  if (!term) return '';

  return enqueueMb(async () => {
    const now = Date.now();
    const wait = MB_MIN_DELAY_MS - (now - mbLastCall);
    if (wait > 0) await sleep(wait);
    mbLastCall = Date.now();

    const query = `artist:"${artist}" AND release:"${album}"`;
    const url = new URL(MB_RELEASE_API);
    url.searchParams.set('query', query);
    url.searchParams.set('fmt', 'json');
    url.searchParams.set('limit', '1');

    const res = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
    if (!res.ok) return '';
    const data = await res.json();
    const mbid = data?.releases?.[0]?.id;
    if (!mbid) return '';

    const caaRes = await fetch(`${CAA_RELEASE_API}${mbid}`);
    if (!caaRes.ok) return '';
    const caa = await caaRes.json();
    const img = caa?.images?.find((item) => item.front) || caa?.images?.[0];
    const urlBest =
      img?.thumbnails?.['500'] ||
      img?.thumbnails?.large ||
      img?.thumbnails?.small ||
      img?.image ||
      '';
    return urlBest || '';
  });
}

function loadUploadMap() {
  try {
    const raw = JSON.parse(localStorage.getItem(UPLOAD_STORAGE_KEY) || '{}');
    return raw && typeof raw === 'object' ? raw : {};
  } catch {
    return {};
  }
}

function saveUploadMap(map) {
  try {
    localStorage.setItem(UPLOAD_STORAGE_KEY, JSON.stringify(map));
    return true;
  } catch {
    return false;
  }
}

function getCachedCoverInfo(key) {
  if (!key) return { known: true, url: '' };
  const uploadUrl = STATE.uploads?.[key];
  if (uploadUrl) return { known: true, url: uploadUrl };

  const hit = STATE.coverCache?.[key];
  if (hit && hit.url && isFresh(hit.ts, COVER_CACHE_TTL_DAYS)) {
    return { known: true, url: hit.url };
  }
  if (hit && hit.miss && isFresh(hit.ts, COVER_MISS_TTL_DAYS)) {
    return { known: true, url: '' };
  }

  return { known: false, url: '' };
}

async function resolveCover(row) {
  const key = row.key;
  if (!key) return '';

  const uploadUrl = STATE.uploads?.[key];
  if (uploadUrl) return uploadUrl;

  const hit = STATE.coverCache?.[key];
  if (hit && hit.url && isFresh(hit.ts, COVER_CACHE_TTL_DAYS)) {
    return hit.url;
  }

  const local = await tryLocalCover(row.artist, row.album);
  if (local) {
    STATE.coverCache[key] = { url: local, ts: Date.now(), local: true };
    saveCoverCache(STATE.coverCache);
    return local;
  }

  if (hit && hit.miss && isFresh(hit.ts, COVER_MISS_TTL_DAYS)) {
    return '';
  }

  try {
    let url = await fetchCoverItunes(row.artist, row.album);
    if (!url) {
      url = await fetchCoverMusicBrainz(row.artist, row.album);
    }
    STATE.coverCache[key] = url
      ? { url, ts: Date.now() }
      : { url: '', ts: Date.now(), miss: true };
    saveCoverCache(STATE.coverCache);
    return url || '';
  } catch {
    STATE.coverCache[key] = { url: '', ts: Date.now(), miss: true };
    saveCoverCache(STATE.coverCache);
    return '';
  }
}

function buildPoster(el, url, letter, label) {
  el.innerHTML = '';

  if (url) {
    const img = document.createElement('img');
    img.alt = '';
    img.src = url;
    img.loading = 'lazy';
    img.decoding = 'async';
    img.onerror = () => {
      img.remove();
      el.classList.add('is-empty');
      const fallback = buildPosterFallback(letter);
      el.insertBefore(fallback, el.firstChild);
    };
    el.classList.remove('is-empty');
    el.appendChild(img);
  } else {
    el.classList.add('is-empty');
    const fallback = buildPosterFallback(letter);
    el.appendChild(fallback);
  }

  const overlay = document.createElement('div');
  overlay.className = 'bm365-upload-overlay';
  overlay.textContent = label;
  el.appendChild(overlay);
}

function buildPosterFallback(letter) {
  const wrap = document.createElement('div');
  wrap.className = 'oscars-poster-fallback';

  const letterEl = document.createElement('div');
  letterEl.className = 'oscars-poster-letter';
  letterEl.textContent = letter;

  wrap.appendChild(letterEl);
  return wrap;
}

function posterLetter(row) {
  const src = row.artist || row.album || '';
  return src ? src.trim().charAt(0).toUpperCase() : 'BM';
}

async function fileToDataUrl(file, maxSize = 900) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });

  const img = await new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('Invalid image'));
    image.src = dataUrl;
  });

  const maxDim = Math.max(img.width, img.height);
  if (!Number.isFinite(maxDim) || maxDim <= maxSize) {
    return dataUrl;
  }

  const scale = maxSize / maxDim;
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

  return canvas.toDataURL('image/jpeg', 0.9);
}

async function uploadCoverToServer(row, dataUrl) {
  if (!UPLOAD_API || !row) return '';
  try {
    const res = await fetch(UPLOAD_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        artist: row.artist,
        album: row.album,
        dataUrl
      })
    });
    if (!res.ok) return '';
    const payload = await res.json();
    if (!payload || !payload.ok || !payload.url) return '';
    return String(payload.url);
  } catch {
    return '';
  }
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === 'function') {
    return window.CSS.escape(value);
  }
  return String(value).replace(/["\\]/g, '\\$&');
}

function updatePostersForKey(key, url) {
  const selector = `[data-upload-key="${cssEscape(key)}"]`;
  const row = STATE.byKey?.get(key);
  const letter = row ? posterLetter(row) : 'BM';
  document.querySelectorAll(selector).forEach((el) => {
    buildPoster(el, url, letter, url ? 'Change cover' : 'Upload cover');
  });
}

function isRankingViewActive() {
  return (
    $('bm365-sort')?.value === 'rating_desc' &&
    $('bm365-only-rated')?.getAttribute('aria-pressed') === 'true'
  );
}

function setPressedState(btn, active) {
  if (!btn) return;
  btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  btn.classList.toggle('is-on', active);
}

function syncListModeUi(list = STATE.filtered) {
  const ranking = isRankingViewActive();
  setText('bm365-list-title', ranking ? 'Rating ranking' : 'Chronological list');
  setText(
    'bm365-list-copy',
    ranking
      ? 'Only rated albums, sorted from highest score to lowest.'
      : 'Browse the full run in calendar order or jump into rating ranking.'
  );
  setText('bm365-count', ranking ? `${list.length} rated items` : `${list.length} items`);
  setPressedState($('bm365-view-chronological'), !ranking);
  setPressedState($('bm365-view-ranking'), ranking);
}

function buildRow(row, token, options = {}) {
  const { rank = null } = options;
  const wrap = document.createElement('div');
  wrap.className = `oscars-row bm365-row${row.listened ? ' is-watched' : ''}`;

  const main = document.createElement('div');
  main.className = 'oscars-row-main';

  const poster = document.createElement('button');
  poster.type = 'button';
  poster.className = 'oscars-poster bm365-poster';
  poster.dataset.uploadKey = row.key;
  poster.dataset.renderToken = String(token);
  poster.setAttribute(
    'aria-label',
    row.key ? 'Upload cover' : 'Cover not available'
  );

  const cached = getCachedCoverInfo(row.key);
  const letter = posterLetter(row);
  if (cached.known && cached.url) {
    buildPoster(poster, cached.url, letter, 'Change cover');
  } else {
    buildPoster(poster, '', letter, 'Upload cover');
  }

  const text = document.createElement('div');
  text.className = 'oscars-main-text';

  const title = document.createElement('div');
  title.className = 'bm365-title';
  title.textContent = `${safeText(row.artist)} ${DASH} ${safeText(row.album)}`;

  const meta = document.createElement('div');
  meta.className = 'bm365-meta';
  const metaParts = [`Day ${row.dayIndex}`, formatBmDate(row.date)];
  if (Number.isFinite(row.minutes)) metaParts.push(`${row.minutes}m`);
  if (Number.isFinite(row.rating)) metaParts.push(`Rating ${row.rating}`);
  meta.textContent = metaParts.join(' | ');

  const tags = document.createElement('div');
  tags.className = 'bm365-tags';
  if (Number.isFinite(rank)) {
    const rankTag = document.createElement('span');
    rankTag.className = 'bm365-tag is-rank';
    rankTag.textContent = `#${rank}`;
    tags.appendChild(rankTag);
  }
  const status = document.createElement('span');
  status.className = `bm365-tag ${row.listened ? 'is-on' : 'is-off'}`;
  status.textContent = row.listened ? 'Listened' : 'Pending';
  tags.appendChild(status);

  text.appendChild(title);
  text.appendChild(meta);
  text.appendChild(tags);

  main.appendChild(poster);
  main.appendChild(text);

  wrap.appendChild(main);

  return { wrap, poster, cached };
}

async function queueCoverLoads(targets, token) {
  const concurrency = 4;
  let cursor = 0;
  const delayMs = 120;

  async function worker() {
    while (true) {
      const target = targets[cursor++];
      if (!target) break;
      if (!document.body.contains(target.poster)) continue;
      if (String(token) !== target.poster.dataset.renderToken) continue;

      const url = await resolveCover(target.row);
      if (!url) continue;
      if (!document.body.contains(target.poster)) continue;
      if (String(token) !== target.poster.dataset.renderToken) continue;

      buildPoster(target.poster, url, posterLetter(target.row), 'Change cover');
      if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    }
  }

  await Promise.all(Array.from({ length: concurrency }, worker));
}

function applyFilters(rows) {
  const search = String($('bm365-search')?.value || '').trim().toLowerCase();
  const year = $('bm365-year')?.value || 'ALL';
  const sort = $('bm365-sort')?.value || 'date_asc';

  const hideListened = $('bm365-hide-listened')?.getAttribute('aria-pressed') === 'true';
  const onlyRated = $('bm365-only-rated')?.getAttribute('aria-pressed') === 'true';

  let list = rows.slice();

  if (search) {
    list = list.filter((row) => row.search.includes(search));
  }

  if (year !== 'ALL') {
    list = list.filter((row) => row.year === year);
  }

  if (hideListened) {
    list = list.filter((row) => !row.listened);
  }

  if (onlyRated) {
    list = list.filter((row) => Number.isFinite(row.rating));
  }

  if (sort === 'date_desc') {
    list.sort((a, b) => b.date.localeCompare(a.date));
  } else if (sort === 'rating_desc') {
    list.sort((a, b) => {
      const ar = Number.isFinite(a.rating) ? a.rating : -Infinity;
      const br = Number.isFinite(b.rating) ? b.rating : -Infinity;
      if (br !== ar) return br - ar;
      return a.date.localeCompare(b.date);
    });
  } else if (sort === 'artist') {
    list.sort((a, b) => safeText(a.artist).localeCompare(safeText(b.artist)));
  } else {
    list.sort((a, b) => a.date.localeCompare(b.date));
  }

  return list;
}

function renderStats(rows) {
  const stats = computeStats(rows);
  setText('bm365-total', String(stats.total));
  setText('bm365-done', String(stats.done));
  setText('bm365-left', String(stats.left));
  setText('bm365-avg', stats.avgRating === null ? '-' : stats.avgRating.toFixed(2));

  setText('bm365-rated-count', String(stats.ratedCount));
  setText('bm365-time', stats.totalMinutes ? formatMinutes(stats.totalMinutes) : '-');

  updateBm365Progress(stats.done, stats.total);
  setText('bm365-progress-text', `${stats.done} / ${stats.total} - ${stats.pct}%`);
}

function renderYearOptions(rows) {
  const select = $('bm365-year');
  if (!select) return;

  const years = Array.from(new Set(rows.map((r) => r.year))).filter(Boolean);
  years.sort();

  const current = select.value || 'ALL';
  select.innerHTML = '<option value="ALL">All years</option>';
  years.forEach((year) => {
    const opt = document.createElement('option');
    opt.value = year;
    opt.textContent = year;
    select.appendChild(opt);
  });
  select.value = years.includes(current) ? current : 'ALL';
}

function renderList() {
  const grid = $('bm365-grid');
  if (!grid) return;

  const token = ++STATE.renderToken;
  const list = applyFilters(STATE.rows);
  const ranking = isRankingViewActive();
  STATE.filtered = list;

  grid.innerHTML = '';

  const targets = [];
  list.forEach((row, idx) => {
    const { wrap, poster, cached } = buildRow(row, token, {
      rank: ranking ? idx + 1 : null
    });
    grid.appendChild(wrap);
    if (!cached.known) {
      targets.push({ row, poster });
    }
  });

  syncListModeUi(list);
  if (targets.length) {
    queueCoverLoads(targets, token).catch((err) => console.error(err));
  }
}

function toggleBtn(btn) {
  if (!btn) return;
  const pressed = btn.getAttribute('aria-pressed') === 'true';
  setPressedState(btn, !pressed);
}

function bindFilters() {
  const search = $('bm365-search');
  const year = $('bm365-year');
  const sort = $('bm365-sort');
  const hideBtn = $('bm365-hide-listened');
  const ratedBtn = $('bm365-only-rated');
  const clearBtn = $('bm365-clear-filters');

  if (search) search.addEventListener('input', renderList);
  if (year) year.addEventListener('change', renderList);
  if (sort) sort.addEventListener('change', renderList);

  if (hideBtn) {
    hideBtn.addEventListener('click', () => {
      toggleBtn(hideBtn);
      renderList();
    });
  }

  if (ratedBtn) {
    ratedBtn.addEventListener('click', () => {
      toggleBtn(ratedBtn);
      renderList();
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      if (search) search.value = '';
      if (year) year.value = 'ALL';
      if (sort) sort.value = 'date_asc';
      setPressedState(hideBtn, false);
      setPressedState(ratedBtn, false);
      renderList();
    });
  }
}

function bindViewToggle() {
  const chronologicalBtn = $('bm365-view-chronological');
  const rankingBtn = $('bm365-view-ranking');
  const sort = $('bm365-sort');
  const ratedBtn = $('bm365-only-rated');

  if (chronologicalBtn) {
    chronologicalBtn.addEventListener('click', () => {
      if (sort) sort.value = 'date_asc';
      setPressedState(ratedBtn, false);
      renderList();
    });
  }

  if (rankingBtn) {
    rankingBtn.addEventListener('click', () => {
      if (sort) sort.value = 'rating_desc';
      setPressedState(ratedBtn, true);
      renderList();
    });
  }
}

function bindScrollToTop() {
  const btn = $('bm365-to-top');
  if (!btn) return;

  const onScroll = () => {
    if (window.scrollY > 400) btn.classList.add('is-visible');
    else btn.classList.remove('is-visible');
  };

  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  btn.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
}

function bindUploads() {
  const grid = $('bm365-grid');
  const input = $('bm365-upload-input');
  const clearUploads = $('bm365-clear-uploads');

  if (grid) {
    grid.addEventListener('click', (event) => {
      const btn = event.target.closest('.bm365-poster');
      if (!btn) return;
      const key = btn.dataset.uploadKey || '';
      if (!key) return;
      currentUploadKey = key;
      if (input) {
        input.value = '';
        input.click();
      }
    });
  }

  if (input) {
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file || !currentUploadKey) return;
      if (!file.type.startsWith('image/')) {
        setFooter('Only image files are supported.');
        return;
      }

      setFooter('Processing cover...');

      try {
        const key = currentUploadKey;
        const row = STATE.byKey?.get(key);
        const dataUrl = await fileToDataUrl(file, 900);
        const serverUrl = await uploadCoverToServer(row, dataUrl);

        if (serverUrl) {
          const cleanUrl = serverUrl.split('?')[0];
          if (STATE.uploads?.[key]) {
            delete STATE.uploads[key];
            saveUploadMap(STATE.uploads);
          }
          STATE.coverCache[key] = { url: cleanUrl, ts: Date.now(), local: true };
          saveCoverCache(STATE.coverCache);
          updatePostersForKey(key, `${cleanUrl}?t=${Date.now()}`);
          setFooter(`Cover saved to covers/ - ${fmtDateTimeShort(new Date())}`);
          return;
        }

        STATE.uploads[key] = dataUrl;
        const saved = saveUploadMap(STATE.uploads);
        if (!saved) {
          setFooter('Upload failed (storage full).');
          return;
        }
        updatePostersForKey(key, dataUrl);
        setFooter(`Cover saved locally - ${fmtDateTimeShort(new Date())}`);
      } catch (err) {
        console.error(err);
        setFooter('Upload failed.');
      } finally {
        currentUploadKey = '';
      }
    });
  }

  if (clearUploads) {
    clearUploads.addEventListener('click', () => {
      if (!confirm('Clear browser uploads?')) return;
      STATE.uploads = {};
      try {
        localStorage.removeItem(UPLOAD_STORAGE_KEY);
      } catch {
        // ignore
      }
      renderList();
      setFooter('Browser uploads cleared.');
    });
  }
}

function bindFetchCovers() {
  const btn = $('bm365-fetch-covers');
  const status = $('bm365-fetch-status');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    if (!COVER_BATCH_API) {
      if (status) status.textContent = 'Start server.py to download covers.';
      return;
    }

    btn.disabled = true;
    if (status) status.textContent = 'Downloading covers (this may take a while)...';

    try {
      const res = await fetch(COVER_BATCH_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 0, force: false })
      });
      const data = await res.json();
      if (!res.ok || data?.error) {
        throw new Error(data?.error || `HTTP ${res.status}`);
      }
      if (status) {
        status.textContent = `Saved ${data.saved} | Skipped ${data.skipped} | Missing ${data.missing} | Errors ${data.errors}`;
      }
      renderList();
    } catch (err) {
      console.error(err);
      if (status) status.textContent = 'Download failed.';
    } finally {
      btn.disabled = false;
    }
  });
}

async function fetchAllRows() {
  return getBm365Albums();
}

async function init() {
  setFooter('Loading...');
  try {
    const raw = await fetchAllRows();
    const rows = normalizeRows(raw);
    assignDayIndex(rows);
    STATE.rows = rows;
    STATE.byKey = new Map(rows.map((row) => [row.key, row]));

    renderStats(rows);
    renderYearOptions(rows);
    renderList();

    setText(
      'bm365-source',
      `Source: local SQLite (${rows.length} rows) • Covers: local / iTunes / MusicBrainz`
    );
    setFooter(`Updated ${fmtDateTimeShort(new Date())}`);
  } catch (err) {
    console.error(err);
    setText('bm365-source', 'Source: local SQLite (error)');
    setFooter('Failed to load data. Start the local Python server.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  bindFilters();
  bindViewToggle();
  bindScrollToTop();
  bindUploads();
  bindFetchCovers();
  init();
});
