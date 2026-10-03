import { fmtDateTimeShort } from './utils.js';
import { createAlbumStarRating } from './album-star-rating.js';
import { isBm365FinaleReady, renderBm365FinalePage } from './bm365-summary.js';
import { getBm365Albums, rateBm365Album, updateBm365Metadata } from './bm365-api.js';
import {
  appendLastFmAlbumBadge,
  artistScrobblesFromAlbums,
  fetchLastFmAlbumStats,
} from './lastfm-stats.js';
import {
  createRateYourMusicSearchLink,
  createSpotifySearchLink,
  createYoutubeSearchLink,
  rateYourMusicSearchUrl,
} from './spotify-link.js';
import {
  albumDescriptionTeaser,
  buildBrutalAssaultArtistRatingRankings,
  buildBrutalAssaultBulkDescriptionPrompt,
  buildBrutalAssaultRecommendationQueue,
  brutalAssaultMixedRating,
  buildRymPolishBlackMetalBulkDescriptionPrompt,
  communityRatingLabel,
  computeBrutalAssaultDeadlineStats,
  copyBrutalAssaultAlbumPrompt,
  copyRymPolishBlackMetalAlbumPrompt,
  countAlbumDescriptionSentences,
  parseBrutalAssaultBulkDescriptionJson,
  renderBrutalAssaultAlbumDescription,
  renderBrutalAssaultDeadlineSummary,
  sortBrutalAssaultAlbumsByRating,
  validateRymDescriptionBatch,
} from './brutal-assault-recommendations.js';

const PROJECT = document.body?.dataset.albumProject || 'bm365';
const IS_BRUTAL_ASSAULT_2027 = PROJECT === 'brutal-assault-2027';
const IS_RYM_POLISH_BM = PROJECT === 'rym-polish-black-metal-top-100';
const IS_LOCAL_PROJECT = IS_BRUTAL_ASSAULT_2027 || IS_RYM_POLISH_BM;
const PROJECT_LABEL = IS_BRUTAL_ASSAULT_2027
  ? 'Brutal Assault 2027'
  : (IS_RYM_POLISH_BM ? 'Top 100 RYM Polish BM' : 'BM365');

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
const COVER_CACHE_KEY = IS_BRUTAL_ASSAULT_2027
  ? 'brutal_assault_2027_cover_cache_v1'
  : (IS_RYM_POLISH_BM ? 'rym_polish_black_metal_cover_cache_v1' : 'bm365_cover_cache_v1');
const COVER_CACHE_TTL_DAYS = 30;
const COVER_MISS_TTL_DAYS = 7;
const UPLOAD_STORAGE_KEY = IS_BRUTAL_ASSAULT_2027
  ? 'brutal_assault_2027_uploads_v1'
  : (IS_RYM_POLISH_BM ? 'rym_polish_black_metal_uploads_v1' : 'bm365_uploads_v1');
const LOCAL_API_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  && window.location.port !== '8000'
  ? 'http://127.0.0.1:8000'
  : '';
const HAS_LOCAL_API = Boolean(LOCAL_API_BASE) || window.location.port === '8000';
const LOCAL_PROJECT_API = `${LOCAL_API_BASE}/api/${IS_RYM_POLISH_BM ? 'rym-polish-black-metal' : 'brutal-assault-2027'}`;
const LOCAL_BM365_API = `${LOCAL_API_BASE}/api/bm365`;
const UPLOAD_API = IS_LOCAL_PROJECT
  ? `${LOCAL_PROJECT_API}/cover`
  : (HAS_LOCAL_API ? `${LOCAL_API_BASE}/api/bm365/cover` : '');
const COVER_BATCH_API = IS_BRUTAL_ASSAULT_2027
  ? `${LOCAL_PROJECT_API}/covers`
  : (HAS_LOCAL_API ? `${LOCAL_API_BASE}/api/bm365/covers` : '');
const MB_RELEASE_API = 'https://musicbrainz.org/ws/2/release/';
const CAA_RELEASE_API = 'https://coverartarchive.org/release/';
const MB_MIN_DELAY_MS = 1100;
const ARTIST_WEIGHT_PRIOR = 3;

const $ = (id) => document.getElementById(id);

const STATE = {
  rows: [],
  filtered: [],
  renderToken: 0,
  coverAuditToken: 0,
  uploads: loadUploadMap(),
  coverCache: loadCoverCache(),
  coverPresence: new Map(),
  byKey: new Map(),
  mainView: 'albums',
  artistRankingMode: 'rym',
  lastfmStats: new Map()
};

let currentUploadKey = '';
let mbLastCall = 0;
let mbQueue = Promise.resolve();
let rymRatingArtistKey = '';
const rymRatingDrafts = new Map();

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setFooter(msg) {
  setText('bm365-foot', msg || '');
}

function setSource(message, tone = 'api') {
  const el = $('bm365-source');
  if (!el) return;
  el.textContent = message;
  el.classList.remove('is-api', 'is-static');
  el.classList.add(tone === 'static' ? 'is-static' : 'is-api');
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

function safeText(value, fallback = DASH) {
  const str = String(value ?? '').trim();
  return str ? str : fallback;
}

function pct(done, total) {
  if (!total) return 0;
  return Math.round((done / total) * 100);
}

function formatMinutes(totalMin) {
  if (!Number.isFinite(totalMin)) return DASH;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h <= 0) return `${m}m`;
  return `${h}h ${m}m`;
}

function formatRatingValue(value) {
  if (!Number.isFinite(value)) return '';
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatBmDate(value) {
  if (!value) return DASH;
  const isoMatch = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!isoMatch) return String(value);
  const dt = new Date(Number(isoMatch[1]), Number(isoMatch[2]) - 1, Number(isoMatch[3]));
  return dt.toLocaleDateString('pl-PL', { day: 'numeric', month: 'long' });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function coverKey(artist, album) {
  return `${String(artist || '').trim()} ${DASH} ${String(album || '').trim()}`.toLowerCase();
}

function albumIdentityPart(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/ł/g, 'l')
    .replace(/[đð]/g, 'd')
    .replace(/þ/g, 'th')
    .replace(/æ/g, 'ae')
    .replace(/œ/g, 'oe')
    .replace(/ø/g, 'o')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function albumIdentityKey(artist, album) {
  return `${albumIdentityPart(artist)}|${albumIdentityPart(album)}`;
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
    const tryAt = (index) => {
      if (index >= candidates.length) return resolve('');
      const url = candidates[index];
      const img = new Image();
      img.onload = () => resolve(url);
      img.onerror = () => tryAt(index + 1);
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
    // ignore storage failures
  }
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

function isFresh(ts, ttlDays) {
  if (!ts) return false;
  const ageMs = Date.now() - ts;
  return ageMs < ttlDays * 24 * 60 * 60 * 1000;
}

function upgradeArtworkUrl(url, sizePx = 600) {
  if (!url) return '';
  return String(url).replace(/\/(\d+)x(\d+)bb\.(jpg|png)/i, `/${sizePx}x${sizePx}bb.$3`);
}

function enqueueMb(task) {
  const next = mbQueue.then(task).catch(() => '');
  mbQueue = next.then(
    () => undefined,
    () => undefined
  );
  return next;
}

async function fetchCoverItunes(artist, album) {
  const term = `${artist} ${album}`.trim();
  if (!term) return '';

  const url = new URL('https://itunes.apple.com/search');
  url.searchParams.set('term', term);
  url.searchParams.set('entity', 'album');
  url.searchParams.set('limit', '1');

  const res = await fetch(url.toString());
  if (!res.ok) return '';
  const data = await res.json();
  const item = data?.results?.[0];
  return upgradeArtworkUrl(item?.artworkUrl100 || item?.artworkUrl60 || '', 600);
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
    return (
      img?.thumbnails?.['500'] ||
      img?.thumbnails?.large ||
      img?.thumbnails?.small ||
      img?.image ||
      ''
    );
  });
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

function getCoverPresence(row) {
  if (!row?.key) return 'missing';

  const cached = getCachedCoverInfo(row.key);
  if (cached.known) return cached.url ? 'present' : 'missing';

  return STATE.coverPresence.get(row.key) || 'unknown';
}

function hasCover(row) {
  return getCoverPresence(row) === 'present';
}

function isMissingCoverFilterActive() {
  return $('bm365-missing-covers')?.getAttribute('aria-pressed') === 'true';
}

async function auditLocalCoverPresence(rows, token) {
  const uniqueRows = [];
  const seen = new Set();

  rows.forEach((row) => {
    if (!row?.key || seen.has(row.key) || getCoverPresence(row) !== 'unknown') return;
    seen.add(row.key);
    uniqueRows.push(row);
  });

  if (!uniqueRows.length) return;

  const concurrency = 6;
  let cursor = 0;
  let changed = false;

  async function worker() {
    while (true) {
      const row = uniqueRows[cursor++];
      if (!row || token !== STATE.coverAuditToken) break;

      const local = await tryLocalCover(row.artist, row.album);
      if (token !== STATE.coverAuditToken) break;

      if (local) {
        STATE.coverCache[row.key] = { url: local, ts: Date.now(), local: true };
        STATE.coverPresence.set(row.key, 'present');
        changed = true;
      } else {
        STATE.coverPresence.set(row.key, 'missing');
        changed = true;
      }
    }
  }

  await Promise.all(Array.from({ length: concurrency }, worker));
  if (!changed || token !== STATE.coverAuditToken) return;

  saveCoverCache(STATE.coverCache);
  if (STATE.mainView === 'albums') renderAlbumList();
}

async function resolveCover(row) {
  const key = row.key;
  if (!key) return '';

  const uploadUrl = STATE.uploads?.[key];
  if (uploadUrl) {
    STATE.coverPresence.set(key, 'present');
    return uploadUrl;
  }

  const hit = STATE.coverCache?.[key];
  if (hit && hit.url && isFresh(hit.ts, COVER_CACHE_TTL_DAYS)) {
    STATE.coverPresence.set(key, 'present');
    return hit.url;
  }

  const local = await tryLocalCover(row.artist, row.album);
  if (local) {
    STATE.coverCache[key] = { url: local, ts: Date.now(), local: true };
    STATE.coverPresence.set(key, 'present');
    saveCoverCache(STATE.coverCache);
    return local;
  }

  if (hit && hit.miss && isFresh(hit.ts, COVER_MISS_TTL_DAYS)) {
    STATE.coverPresence.set(key, 'missing');
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
    STATE.coverPresence.set(key, url ? 'present' : 'missing');
    saveCoverCache(STATE.coverCache);
    return url || '';
  } catch {
    STATE.coverCache[key] = { url: '', ts: Date.now(), miss: true };
    STATE.coverPresence.set(key, 'missing');
    saveCoverCache(STATE.coverCache);
    return '';
  }
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
  const source = row.artist || row.album || '';
  return source ? source.trim().charAt(0).toUpperCase() : 'BM';
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
      el.insertBefore(buildPosterFallback(letter), el.firstChild);
    };
    el.classList.remove('is-empty');
    el.appendChild(img);
  } else {
    el.classList.add('is-empty');
    el.appendChild(buildPosterFallback(letter));
  }

  const overlay = document.createElement('div');
  overlay.className = 'bm365-upload-overlay';
  overlay.textContent = label;
  el.appendChild(overlay);
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === 'function') {
    return window.CSS.escape(value);
  }
  return String(value).replace(/["\\]/g, '\\$&');
}

function updatePostersForKey(key, url) {
  const selector = `[data-upload-key="${cssEscape(key)}"]`;
  const row = STATE.byKey.get(key);
  const letter = row ? posterLetter(row) : 'BM';
  document.querySelectorAll(selector).forEach((el) => {
    buildPoster(el, url, letter, url ? 'Change cover' : 'Upload cover');
  });
}

async function fileToDataUrl(file, maxSize = 900) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });

  const image = await new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Invalid image'));
    img.src = dataUrl;
  });

  const maxDim = Math.max(image.width, image.height);
  if (!Number.isFinite(maxDim) || maxDim <= maxSize) {
    return dataUrl;
  }

  const scale = maxSize / maxDim;
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(image.width * scale);
  canvas.height = Math.round(image.height * scale);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
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
    if (!payload?.ok || !payload?.url) return '';
    return String(payload.url);
  } catch {
    return '';
  }
}

function normalizeRows(raw) {
  const rows = Array.isArray(raw) ? raw : raw?.rows || [];
  const f = CONFIG.FIELDS;

  return rows
    .map((r) => {
      const date = String(r?.[f.date] || '').trim();
      if (!date) return null;

      const rating = toNumber(r?.[f.rating]);
      const listenedValue = r?.[f.listened];
      const listenedFlag = listenedValue === true || listenedValue === 1
        || ['TAK', 'TRUE', 'YES', '1'].includes(String(listenedValue || '').trim().toUpperCase());

      return {
        date,
        artist: String(r?.[f.artist] || '').trim(),
        album: String(r?.[f.album] || '').trim(),
        listened: listenedFlag || Number.isFinite(rating),
        rating,
        minutes: toNumber(r?.[f.minutes]),
        rymRating: toNumber(r?.rymRating),
        rymRatingIgnored: r?.rymRatingIgnored === true || r?.rymRatingIgnored === 1,
        communityRating: toNumber(r?.communityRating),
        communityVotes: toNumber(r?.communityVotes) || 0,
        communitySource: safeText(r?.communitySource, ''),
        communityUrl: safeText(r?.communityUrl, ''),
        description: safeText(r?.description, '').trim(),
        rowId: r?.[f.rowId] ?? null,
        year: String(r?.year || '').trim(),
        sourceRank: toNumber(r?.sourceRank),
        crossList: r?.crossList && typeof r.crossList === 'object' ? { ...r.crossList } : null,
        crossLists: Array.isArray(r?.crossLists)
          ? r.crossLists.filter(Boolean).map((item) => ({ ...item }))
          : (r?.crossList && typeof r.crossList === 'object' ? [{ ...r.crossList }] : []),
        key: coverKey(r?.[f.artist], r?.[f.album]),
        search: `${String(r?.[f.artist] || '')} ${String(r?.[f.album] || '')}`.toLowerCase()
      };
    })
    .filter(Boolean);
}

function assignDayIndex(rows) {
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  sorted.forEach((row, index) => {
    row.dayIndex = index + 1;
  });
}

function computeStats(rows) {
  const total = rows.length;
  const done = rows.filter((row) => row.listened).length;
  const left = Math.max(0, total - done);
  const ratedRows = rows.filter((row) => Number.isFinite(row.rating));
  const avgRating = ratedRows.length
    ? ratedRows.reduce((sum, row) => sum + row.rating, 0) / ratedRows.length
    : null;
  const timeRows = rows.filter((row) => (
    Number.isFinite(row.minutes) && (IS_LOCAL_PROJECT || row.listened)
  ));
  const totalMinutes = timeRows.reduce((sum, row) => sum + row.minutes, 0);

  return {
    total,
    done,
    left,
    pct: pct(done, total),
    avgRating,
    ratedCount: ratedRows.length,
    totalMinutes
  };
}

function dayOfYear() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  return Math.floor((now - start) / (1000 * 60 * 60 * 24));
}

function updateProgress(done, total) {
  const bar = $('bm365-progress-bar');
  const delta = $('bm365-progress-delta');
  if (!bar) return;

  const safeTotal = Number.isFinite(total) && total > 0 ? total : 0;
  const safeDone = Number.isFinite(done) ? Math.max(0, done) : 0;
  const clampedDone = safeTotal ? Math.min(safeDone, safeTotal) : 0;
  const basePct = safeTotal ? (clampedDone / safeTotal) * 100 : 0;
  bar.style.width = `${basePct}%`;

  if (!delta) return;

  delta.classList.remove('is-ahead', 'is-behind');
  if (IS_LOCAL_PROJECT) {
    delta.style.width = '0%';
    delta.style.left = `${basePct}%`;
    return;
  }
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
    leftPct = basePct;
    delta.classList.add('is-behind');
  } else {
    leftPct = basePct;
  }

  delta.style.width = `${Math.min(100, Math.max(0, deltaPct))}%`;
  delta.style.left = `${Math.min(100, Math.max(0, leftPct))}%`;
}

function renderStats(rows) {
  const stats = computeStats(rows);
  const deadline = IS_BRUTAL_ASSAULT_2027
    ? computeBrutalAssaultDeadlineStats(rows)
    : null;
  setText('bm365-total', String(stats.total));
  setText('bm365-done', String(stats.done));
  setText('bm365-left', String(stats.left));
  setText('bm365-avg', stats.avgRating === null ? DASH : stats.avgRating.toFixed(2));
  setText('bm365-rated-count', String(stats.ratedCount));
  setText(
    'bm365-time',
    deadline
      ? (deadline.remainingMinutes ? formatMinutes(deadline.remainingMinutes) : DASH)
      : (stats.totalMinutes ? formatMinutes(stats.totalMinutes) : DASH)
  );
  updateProgress(stats.done, stats.total);
  setText('bm365-progress-text', `${stats.done} / ${stats.total} - ${stats.pct}%`);

  const deadlineElement = $('ba2027-deadline');
  if (deadlineElement && deadline) {
    renderBrutalAssaultDeadlineSummary(deadlineElement, deadline);
  }
}

function renderYearOptions(rows) {
  const select = $('bm365-year');
  if (!select) return;

  const current = select.value || 'ALL';
  const years = Array.from(new Set(rows.map((row) => row.year).filter(Boolean))).sort();

  select.innerHTML = '<option value="ALL">All years</option>';
  years.forEach((year) => {
    const option = document.createElement('option');
    option.value = year;
    option.textContent = year;
    select.appendChild(option);
  });

  select.value = years.includes(current) ? current : 'ALL';
}

function createRatingSelect(selectedValue, placeholder = 'Set rating') {
  const control = createAlbumStarRating(selectedValue, {
    ariaLabel: placeholder,
  });
  control.classList.add('bm365-rating-input');
  return control;
}

function buildRowActions(row) {
  const actions = document.createElement('div');
  actions.className = 'bm365-row-actions';

  const editor = document.createElement('div');
  editor.className = 'bm365-rating-editor';

  const select = createRatingSelect(
    row.rating,
    row.listened ? 'Set rating' : 'Rate + mark listened'
  );

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'oscars-toggle bm365-save-rating';
  button.textContent = Number.isFinite(row.rating) ? 'Save change' : 'Save rating';
  button.disabled = !select.value;

  const feedback = document.createElement('div');
  feedback.className = 'bm365-row-feedback';
  feedback.hidden = true;

  const syncButtonState = () => {
    button.disabled = !select.value;
  };

  select.addEventListener('change', () => {
    feedback.hidden = true;
    feedback.textContent = '';
    syncButtonState();
  });

  button.addEventListener('click', async () => {
    const rating = toNumber(select.value);
    if (!Number.isFinite(rating)) return;

    button.disabled = true;
    select.disabled = true;
    feedback.hidden = false;
    feedback.textContent = 'Saving...';
    setFooter(`Saving ${PROJECT_LABEL} rating...`);

    try {
      const payload = await apiRateAlbum({
        date: row.date,
        rowId: row.rowId,
        artist: row.artist,
        album: row.album,
        rating
      });
      if (IS_LOCAL_PROJECT) {
        applyPayload(payload);
      } else {
        applyPayload(STATE.rows.map((item) => (
          String(item.rowId) === String(payload?.album?.rowId)
            ? { ...item, ...payload.album }
            : item
        )));
      }
      setFooter(`Rating saved for ${safeText(row.artist)} - ${safeText(row.album)}`);
    } catch (error) {
      console.error(error);
      feedback.textContent = 'Save failed.';
      select.disabled = false;
      syncButtonState();
      setFooter(
        IS_LOCAL_PROJECT
          ? 'Could not save the rating. Check the local server.'
          : 'Could not save BM365 rating. Check the local server.'
      );
    }
  });

  editor.appendChild(select);
  editor.appendChild(button);
  actions.appendChild(editor);
  actions.appendChild(feedback);

  return actions;
}

function createAlbumEditField({ label, name, type = 'text', value = '', wide = false }) {
  const field = document.createElement('label');
  field.className = `ba2027-edit-field${wide ? ' is-wide' : ''}`;

  const caption = document.createElement('span');
  caption.textContent = label;

  const input = document.createElement('input');
  input.className = 'oscars-input';
  input.name = name;
  input.type = type;
  input.value = value ?? '';
  if (name === 'artist' || name === 'album') {
    input.required = true;
    input.maxLength = 240;
  }
  if (name === 'year') {
    input.min = '1900';
    input.max = '2100';
  }
  if (name === 'minutes') {
    input.min = '1';
    input.max = '1440';
  }
  if (name === 'rymRating') {
    input.min = '0.5';
    input.max = '5';
    input.step = '0.01';
    input.inputMode = 'decimal';
  }
  if (name === 'date') input.required = true;

  field.appendChild(caption);
  field.appendChild(input);
  return field;
}

function createAlbumDescriptionField(row) {
  const field = document.createElement('label');
  field.className = 'ba2027-edit-field is-full ba2027-description-editor';
  const head = document.createElement('span');
  head.className = 'ba2027-description-editor-head';
  const caption = document.createElement('span');
  caption.textContent = 'Opis i ciekawostki';
  const counter = document.createElement('span');
  const textarea = document.createElement('textarea');
  textarea.className = 'oscars-input';
  textarea.name = 'description';
  textarea.rows = 7;
  textarea.maxLength = 4000;
  textarea.value = row.description || '';
  textarea.placeholder = 'Wklej gotowy opis albumu — maksymalnie 10 zdań.';
  const formatHint = document.createElement('small');
  formatHint.className = 'ba2027-description-format-hint';
  formatHint.textContent = 'Formatowanie: ## Nagłówek, - punkt listy, **pogrubienie**.';
  const updateCounter = () => {
    const count = countAlbumDescriptionSentences(textarea.value);
    counter.textContent = `${count} / 10 zdań`;
    counter.classList.toggle('is-over', count > 10);
    textarea.setCustomValidity(count > 10 ? 'Opis może mieć maksymalnie 10 zdań.' : '');
  };
  textarea.addEventListener('input', updateCounter);
  updateCounter();
  head.append(caption, counter);
  field.append(head, textarea, formatHint);
  return field;
}

function buildAlbumDescription(row) {
  const description = document.createElement('details');
  description.className = `ba2027-album-description${row.description ? '' : ' is-empty'}`;
  if (!row.description) description.open = true;
  const summary = document.createElement('summary');
  const summaryLabel = document.createElement('span');
  summaryLabel.textContent = row.description
    ? 'Opis i ciekawostki'
    : 'Brak opisu — przygotuj ciekawostki';
  summary.appendChild(summaryLabel);
  if (row.description) {
    const teaser = document.createElement('small');
    teaser.textContent = albumDescriptionTeaser(row.description);
    summary.appendChild(teaser);
  }
  description.appendChild(summary);

  if (row.description) {
    const body = document.createElement('div');
    renderBrutalAssaultAlbumDescription(body, row.description);
    description.appendChild(body);
    return description;
  }

  const hint = document.createElement('p');
  hint.textContent = 'Skopiuj prompt, wygeneruj tekst i wklej go przez ikonę edycji albumu.';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'ba2027-copy-prompt';
  button.textContent = 'Kopiuj prompt do AI';
  button.addEventListener('click', async () => {
    try {
      if (IS_RYM_POLISH_BM) await copyRymPolishBlackMetalAlbumPrompt(row);
      else await copyBrutalAssaultAlbumPrompt(row);
      button.textContent = 'Skopiowano prompt';
    } catch {
      button.textContent = 'Nie udało się skopiować';
    }
  });
  description.append(hint, button);
  return description;
}

function buildAlbumEditor(row, wrap) {
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'ba2027-edit-toggle';
  toggle.textContent = '✎';
  toggle.title = 'Edytuj album';
  toggle.setAttribute('aria-label', `Edytuj ${safeText(row.artist)} — ${safeText(row.album)}`);
  toggle.setAttribute('aria-expanded', 'false');

  const form = document.createElement('form');
  form.className = 'ba2027-edit-form';
  form.hidden = true;
  if (IS_BRUTAL_ASSAULT_2027) {
    form.appendChild(createAlbumEditField({ label: 'Artist', name: 'artist', value: row.artist, wide: true }));
    form.appendChild(createAlbumEditField({ label: 'Album', name: 'album', value: row.album, wide: true }));
    form.appendChild(createAlbumEditField({ label: 'Release year', name: 'year', type: 'number', value: row.year }));
    form.appendChild(createAlbumEditField({ label: 'Minutes', name: 'minutes', type: 'number', value: row.minutes }));
    form.appendChild(createAlbumEditField({ label: 'Ocena RYM', name: 'rymRating', type: 'number', value: row.rymRating }));
  }
  form.appendChild(createAlbumDescriptionField(row));

  const actions = document.createElement('div');
  actions.className = 'ba2027-edit-actions';

  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'oscars-btn';
  save.textContent = 'Save changes';

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'oscars-toggle';
  cancel.textContent = 'Cancel';

  const feedback = document.createElement('span');
  feedback.className = 'bm365-row-feedback';
  feedback.setAttribute('aria-live', 'polite');

  actions.appendChild(save);
  actions.appendChild(cancel);
  actions.appendChild(feedback);
  form.appendChild(actions);

  const setOpen = (open) => {
    form.hidden = !open;
    wrap.classList.toggle('is-editing', open);
    toggle.setAttribute('aria-expanded', String(open));
    if (open) (form.elements.artist || form.elements.description)?.focus();
  };

  toggle.addEventListener('click', () => setOpen(form.hidden));
  cancel.addEventListener('click', () => setOpen(false));
  form.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setOpen(false);
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    save.disabled = true;
    cancel.disabled = true;
    feedback.textContent = 'Saving...';

    const data = new FormData(form);
    try {
      if (IS_LOCAL_PROJECT) {
        const patch = IS_RYM_POLISH_BM
          ? { id: row.rowId, description: data.get('description') }
          : {
              id: row.rowId,
              artist: data.get('artist'),
              album: data.get('album'),
              year: data.get('year'),
              minutes: data.get('minutes'),
              rymRating: data.get('rymRating'),
              description: data.get('description')
            };
        if (IS_RYM_POLISH_BM) {
          validateRymDescriptionBatch({ [String(row.rowId)]: patch.description });
        }
        const payload = await apiUpdateLocalAlbum(patch);
        applyPayload(payload);
      } else {
        const payload = await apiUpdateBm365Metadata({
          id: row.rowId,
          description: data.get('description')
        });
        applyBm365Metadata(payload);
      }
      setFooter(`Album updated - ${fmtDateTimeShort(new Date())}`);
    } catch (error) {
      console.error(error);
      feedback.textContent = error?.message || 'Could not update the album.';
      save.disabled = false;
      cancel.disabled = false;
    }
  });

  return { toggle, form };
}

function buildRow(row, token, options = {}) {
  const { rank = null, recommendationRank = null, rankingMode = null } = options;
  const wrap = document.createElement('div');
  wrap.className = `oscars-row bm365-row-shell${row.listened ? ' is-watched' : ''}`;

  const main = document.createElement('div');
  main.className = 'oscars-row-main';

  const poster = document.createElement('button');
  poster.type = 'button';
  poster.className = 'oscars-poster bm365-poster';
  poster.dataset.uploadKey = row.key;
  poster.dataset.renderToken = String(token);
  poster.setAttribute('aria-label', row.key ? 'Upload cover' : 'Cover not available');

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
  const metaParts = [];
  if (!IS_LOCAL_PROJECT) {
    metaParts.push(formatBmDate(row.date));
  }
  if (IS_LOCAL_PROJECT && row.year) metaParts.push(row.year);
  if (Number.isFinite(row.minutes)) metaParts.push(`${row.minutes}m`);
  if (!IS_LOCAL_PROJECT && row.year) metaParts.push(row.year);
  if (IS_BRUTAL_ASSAULT_2027 && Number.isFinite(row.rating)) {
    metaParts.push(`Rating ${formatRatingValue(row.rating)}`);
  }
  meta.textContent = metaParts.join(' | ');

  const tags = document.createElement('div');
  tags.className = 'bm365-tags';

  if (Number.isFinite(rank)) {
    const rankTag = document.createElement('span');
    rankTag.className = 'bm365-tag is-rank';
    rankTag.textContent = `#${rank}`;
    tags.appendChild(rankTag);
  }

  if (Number.isFinite(recommendationRank)) {
    const recommendationTag = document.createElement('span');
    recommendationTag.className = 'bm365-tag is-recommendation';
    recommendationTag.textContent = `Propozycja #${recommendationRank}`;
    tags.appendChild(recommendationTag);
  }

  const status = document.createElement('span');
  status.className = `bm365-tag ${row.listened ? 'is-on' : 'is-off'}`;
  status.textContent = IS_LOCAL_PROJECT
    ? (row.listened ? 'Przesłuchane' : 'Do odsłuchania')
    : (row.listened ? 'Listened' : 'Pending');
  tags.appendChild(status);

  appendLastFmAlbumBadge(tags, row, STATE.lastfmStats);

  row.crossLists.forEach((crossList) => {
    const crossListTag = document.createElement('span');
    crossListTag.className = 'bm365-tag is-cross-list';
    crossListTag.title = `Ten album jest również na liście ${safeText(crossList.label)}`;
    crossListTag.textContent = `◆ ${safeText(crossList.label)}`;
    tags.appendChild(crossListTag);
  });

  if (IS_BRUTAL_ASSAULT_2027 && Number.isFinite(row.rating)) {
    const ratingTag = document.createElement('span');
    ratingTag.className = 'bm365-tag is-score';
    ratingTag.textContent = `Score ${formatRatingValue(row.rating)}`;
    tags.appendChild(ratingTag);
  }

  if (rankingMode === 'mixed') {
    const mixed = brutalAssaultMixedRating(row);
    if (mixed !== null) {
      const mixedTag = document.createElement('span');
      mixedTag.className = 'bm365-tag is-mixed-score';
      mixedTag.textContent = `Mix ${mixed.toFixed(2)}/5`;
      mixedTag.title = '(ocena RYM + Twoja ocena) / 2';
      tags.appendChild(mixedTag);
    }
  }

  if (IS_BRUTAL_ASSAULT_2027 && row.rymRatingIgnored) {
    const ignoredRymTag = document.createElement('span');
    ignoredRymTag.className = 'bm365-tag is-rym-ignored';
    ignoredRymTag.textContent = 'RYM po premierze';
    ignoredRymTag.title = 'Album jest na razie pominięty w kolejce uzupełniania RYM';
    tags.appendChild(ignoredRymTag);
  }

  const externalRating = communityRatingLabel(row);
  if (externalRating) {
    const hasRymRating = Number.isFinite(row.rymRating);
    const ratingUrl = hasRymRating
      ? rateYourMusicSearchUrl(row.artist, row.album)
      : row.communityUrl;
    const communityTag = document.createElement(ratingUrl ? 'a' : 'span');
    communityTag.className = 'bm365-tag is-community-score';
    communityTag.textContent = externalRating;
    communityTag.title = hasRymRating
      ? 'Ręcznie wpisana ocena Rate Your Music; kliknij, aby otworzyć wyszukiwanie RYM'
      : `Ocena społeczności ${safeText(row.communitySource, 'MusicBrainz')}; nie jest to Twoja ocena`;
    if (ratingUrl) {
      communityTag.href = ratingUrl;
      communityTag.target = '_blank';
      communityTag.rel = 'noopener noreferrer';
    }
    tags.appendChild(communityTag);
  }

  const media = document.createElement('div');
  media.className = 'media-search-actions bm365-media-actions bm365-page-media-actions';
  media.append(
    createSpotifySearchLink(row.artist, row.album),
    createYoutubeSearchLink(row.artist, row.album),
    createRateYourMusicSearchLink(row.artist, row.album),
  );

  text.appendChild(title);
  text.appendChild(meta);
  text.appendChild(tags);
  text.appendChild(media);

  main.appendChild(poster);
  main.appendChild(text);

  wrap.appendChild(main);
  wrap.appendChild(buildAlbumDescription(row));
  if (row.rowId != null) {
    const editor = buildAlbumEditor(row, wrap);
    wrap.appendChild(editor.toggle);
    wrap.appendChild(editor.form);
  }
  wrap.appendChild(buildRowActions(row));

  return { wrap, poster, cached };
}

async function queueCoverLoads(targets, token) {
  const concurrency = 4;
  let cursor = 0;
  let foundCover = false;

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
      foundCover = true;
      await sleep(120);
    }
  }

  await Promise.all(Array.from({ length: concurrency }, worker));
  if (foundCover && isMissingCoverFilterActive() && token === STATE.renderToken) {
    renderAlbumList();
  }
}

function albumRankingMode() {
  const sort = $('bm365-sort')?.value;
  if (IS_BRUTAL_ASSAULT_2027 && sort === 'rym_desc') return 'rym';
  if (IS_BRUTAL_ASSAULT_2027 && sort === 'mixed_desc') return 'mixed';
  if (sort === 'rating_desc' && (
    IS_BRUTAL_ASSAULT_2027
    || $('bm365-only-rated')?.getAttribute('aria-pressed') === 'true'
  )) return 'own';
  return null;
}

function isAlbumRankingModeActive() {
  return albumRankingMode() !== null;
}

function isAlbumRecommendationModeActive() {
  return IS_BRUTAL_ASSAULT_2027 && $('bm365-sort')?.value === 'recommended';
}

function isSourceOrderModeActive() {
  return IS_RYM_POLISH_BM && $('bm365-sort')?.value === 'source_asc';
}

function setPressedState(button, active) {
  if (!button) return;
  button.setAttribute('aria-pressed', active ? 'true' : 'false');
  button.classList.toggle('is-on', active);
}

function setSelectedState(button, active) {
  if (!button) return;
  button.setAttribute('aria-selected', active ? 'true' : 'false');
  setPressedState(button, active);
}

function applyFilters(rows) {
  const search = String($('bm365-search')?.value || '').trim().toLowerCase();
  const year = $('bm365-year')?.value || 'ALL';
  const sort = $('bm365-sort')?.value || 'date_asc';
  const hideListened = $('bm365-hide-listened')?.getAttribute('aria-pressed') === 'true';
  const onlyRated = $('bm365-only-rated')?.getAttribute('aria-pressed') === 'true';
  const missingCovers = isMissingCoverFilterActive();

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

  if (missingCovers) {
    list = list.filter((row) => !hasCover(row));
  }

  if (sort === 'date_desc') {
    list.sort((a, b) => b.date.localeCompare(a.date));
  } else if (sort === 'rating_desc' && IS_BRUTAL_ASSAULT_2027) {
    list = sortBrutalAssaultAlbumsByRating(list, 'own');
  } else if (sort === 'rym_desc' && IS_BRUTAL_ASSAULT_2027) {
    list = sortBrutalAssaultAlbumsByRating(list, 'rym');
  } else if (sort === 'mixed_desc' && IS_BRUTAL_ASSAULT_2027) {
    list = sortBrutalAssaultAlbumsByRating(list, 'mixed');
  } else if (sort === 'rating_desc') {
    list.sort((a, b) => {
      const ar = Number.isFinite(a.rating) ? a.rating : -Infinity;
      const br = Number.isFinite(b.rating) ? b.rating : -Infinity;
      if (br !== ar) return br - ar;
      return a.date.localeCompare(b.date);
    });
  } else if (sort === 'artist') {
    list.sort((a, b) => safeText(a.artist).localeCompare(safeText(b.artist), 'pl'));
  } else if (sort === 'recommended' && IS_BRUTAL_ASSAULT_2027) {
    const recommendations = buildBrutalAssaultRecommendationQueue(rows);
    const order = new Map(recommendations.map((row, index) => [row.rowId, index]));
    list.sort((a, b) => {
      const aOrder = order.has(a.rowId) ? order.get(a.rowId) : Number.MAX_SAFE_INTEGER;
      const bOrder = order.has(b.rowId) ? order.get(b.rowId) : Number.MAX_SAFE_INTEGER;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return a.date.localeCompare(b.date);
    });
  } else if (sort === 'source_asc' && IS_RYM_POLISH_BM) {
    list.sort((a, b) => (
      (a.sourceRank || Number.MAX_SAFE_INTEGER) - (b.sourceRank || Number.MAX_SAFE_INTEGER)
    ));
  } else {
    list.sort((a, b) => a.date.localeCompare(b.date));
  }

  return list;
}

function syncAlbumUi(list = STATE.filtered) {
  const ranking = isAlbumRankingModeActive();
  const rankingMode = albumRankingMode();
  const recommended = isAlbumRecommendationModeActive();
  const sourceOrder = isSourceOrderModeActive();
  const missingCovers = isMissingCoverFilterActive();
  setText(
    'bm365-list-title',
    missingCovers
      ? 'Missing covers'
      : ranking
        ? rankingMode === 'rym'
          ? 'Ranking albumów — Rate Your Music'
          : rankingMode === 'mixed'
            ? 'Ranking albumów — wynik mieszany'
            : 'Ranking albumów — moje oceny'
        : recommended
          ? 'Proponowane do odsłuchu'
          : sourceOrder
            ? 'RYM Top 100 order'
            : 'Chronological list'
  );
  setText(
    'bm365-list-copy',
    missingCovers
      ? 'Albums without a known cover, ready for manual upload.'
      : ranking
      ? rankingMode === 'rym'
        ? 'Albumy według ręcznie wpisanych ocen RYM, od najwyższej do najniższej.'
        : rankingMode === 'mixed'
          ? 'Średnia z oceny RYM i Twojej oceny; wyłącznie albumy mające obie wartości.'
          : 'Albumy według Twoich ocen, od najwyższej do najniższej.'
      : recommended
      ? 'Albumy do odsłuchu według ocen Rate Your Music — od najwyższej do najniższej. Albumy bez oceny RYM są na końcu.'
      : sourceOrder
        ? 'The selected, previously unrated albums renumbered from #1 to #100.'
        : 'Browse the full run in calendar order or jump into rating ranking.'
  );
  setText(
    'bm365-count',
    missingCovers
      ? `${list.length} missing covers`
      : ranking
        ? (IS_BRUTAL_ASSAULT_2027 ? `${list.length} albumów w rankingu` : `${list.length} rated items`)
        : recommended
          ? `${list.length} propozycji`
        : `${list.length} items`
  );
  setPressedState($('bm365-view-chronological'), !ranking && !recommended);
  setPressedState($('bm365-view-ranking-rym'), rankingMode === 'rym');
  setPressedState($('bm365-view-ranking-mixed'), rankingMode === 'mixed');
  setPressedState($('bm365-view-ranking'), rankingMode === 'own');
  setPressedState($('bm365-view-recommended'), recommended);
}

function renderAlbumList() {
  const grid = $('bm365-grid');
  if (!grid) return;

  const token = ++STATE.renderToken;
  const list = applyFilters(STATE.rows);
  const ranking = isAlbumRankingModeActive();
  const rankingMode = albumRankingMode();
  const recommended = isAlbumRecommendationModeActive();
  const sourceOrder = isSourceOrderModeActive();
  const recommendationRanks = recommended
    ? new Map(buildBrutalAssaultRecommendationQueue(STATE.rows).map((row, index) => [row.rowId, index + 1]))
    : new Map();
  STATE.filtered = list;
  grid.innerHTML = '';

  const targets = [];
  list.forEach((row, index) => {
    const { wrap, poster, cached } = buildRow(row, token, {
      rank: sourceOrder ? row.sourceRank : (ranking ? index + 1 : null),
      recommendationRank: recommended ? recommendationRanks.get(row.rowId) ?? null : null,
      rankingMode
    });
    grid.appendChild(wrap);
    if (!cached.known) {
      targets.push({ row, poster });
    }
  });

  syncAlbumUi(list);
  const auditToken = ++STATE.coverAuditToken;
  auditLocalCoverPresence(STATE.rows, auditToken).catch((error) => console.error(error));
  if (targets.length) {
    queueCoverLoads(targets, token).catch((error) => console.error(error));
  }
}

function computeArtistRankings(rows) {
  const map = new Map();
  const ratedRows = rows.filter((row) => Number.isFinite(row.rating));
  const globalAverage = ratedRows.length
    ? ratedRows.reduce((sum, row) => sum + row.rating, 0) / ratedRows.length
    : 0;

  rows.forEach((row) => {
    if (!Number.isFinite(row.rating)) return;

    const key = row.artist || DASH;
    const entry = map.get(key) || {
      artist: key,
      ratedCount: 0,
      totalRating: 0,
      totalMinutes: 0,
      bestAlbum: null
    };

    entry.ratedCount += 1;
    entry.totalRating += row.rating;
    if (Number.isFinite(row.minutes)) entry.totalMinutes += row.minutes;
    if (!entry.bestAlbum || row.rating > entry.bestAlbum.rating) {
      entry.bestAlbum = {
        album: row.album,
        rating: row.rating
      };
    }

    map.set(key, entry);
  });

  return Array.from(map.values()).map((entry) => ({
    ...entry,
    averageRating: entry.totalRating / entry.ratedCount,
    weightedRating:
      (entry.totalRating + globalAverage * ARTIST_WEIGHT_PRIOR) /
      (entry.ratedCount + ARTIST_WEIGHT_PRIOR)
  }));
}

function buildArtistRow(item, rank, mode) {
  const row = document.createElement('div');
  row.className = 'bm365-artist-row';

  const rankEl = document.createElement('div');
  rankEl.className = 'bm365-artist-rank';
  rankEl.textContent = `#${rank}`;

  const copy = document.createElement('div');
  copy.className = 'bm365-artist-copy';

  const name = document.createElement('div');
  name.className = 'bm365-artist-name';
  name.textContent = item.artist;

  const meta = document.createElement('div');
  meta.className = 'bm365-artist-meta';
  const metaParts =
    mode === 'weighted'
      ? [
          `${item.ratedCount} rated`,
          `avg ${item.averageRating.toFixed(2)}`,
          `weighted ${item.weightedRating.toFixed(2)}`
        ]
      : [`${item.ratedCount} rated`, `avg ${item.averageRating.toFixed(2)}`];
  const lastFmArtistScrobbles = artistScrobblesFromAlbums(item.artist, STATE.rows, STATE.lastfmStats);
  if (lastFmArtistScrobbles !== null) metaParts.push(`Last.fm ${lastFmArtistScrobbles.toLocaleString('pl-PL')} scrobbles`);
  if (item.totalMinutes > 0) metaParts.push(formatMinutes(item.totalMinutes));
  meta.textContent = metaParts.join(' | ');

  const note = document.createElement('div');
  note.className = 'bm365-artist-note';
  note.textContent = item.bestAlbum
    ? `Best: ${safeText(item.bestAlbum.album)} (${formatRatingValue(item.bestAlbum.rating)})`
    : 'No rated album details yet.';

  const score = document.createElement('div');
  score.className = 'bm365-artist-score';

  const scoreValue = document.createElement('strong');
  scoreValue.textContent =
    mode === 'weighted'
      ? item.weightedRating.toFixed(2)
      : mode === 'average'
        ? item.averageRating.toFixed(2)
        : String(item.ratedCount);

  const scoreLabel = document.createElement('span');
  scoreLabel.textContent =
    mode === 'weighted' ? 'weighted' : mode === 'average' ? 'avg' : 'rated';

  copy.appendChild(name);
  copy.appendChild(meta);
  copy.appendChild(note);

  score.appendChild(scoreValue);
  score.appendChild(scoreLabel);

  row.appendChild(rankEl);
  row.appendChild(copy);
  row.appendChild(score);

  return row;
}

function renderArtistRanking(listId, items, mode) {
  const list = $(listId);
  if (!list) return;
  list.innerHTML = '';

  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'bm365-ranking-empty';
    empty.textContent = 'No rated artists yet.';
    list.appendChild(empty);
    return;
  }

  items.forEach((item, index) => {
    list.appendChild(buildArtistRow(item, index + 1, mode));
  });
}

function buildBrutalAssaultArtistRow(item, rank, mode) {
  const row = document.createElement('div');
  row.className = 'bm365-artist-row';

  const rankEl = document.createElement('div');
  rankEl.className = 'bm365-artist-rank';
  rankEl.textContent = `#${rank}`;

  const copy = document.createElement('div');
  copy.className = 'bm365-artist-copy';
  const name = document.createElement('div');
  name.className = 'bm365-artist-name';
  name.textContent = item.artist;

  const meta = document.createElement('div');
  meta.className = 'bm365-artist-meta';
  const note = document.createElement('div');
  note.className = 'bm365-artist-note';
  const score = document.createElement('div');
  score.className = 'bm365-artist-score';
  const scoreValue = document.createElement('strong');
  const scoreLabel = document.createElement('span');

  if (mode === 'rym') {
    scoreValue.textContent = item.rymAverage.toFixed(2);
    scoreLabel.textContent = 'RYM avg';
    meta.textContent = `${item.rymCount} ${item.rymCount === 1 ? 'album' : 'albumów'} z oceną RYM`;
    note.textContent = item.bestRymAlbum
      ? `Najwyżej: ${safeText(item.bestRymAlbum.album)} (${item.bestRymAlbum.score.toFixed(2)})`
      : '';
  } else if (mode === 'own') {
    scoreValue.textContent = item.ownAverage.toFixed(2);
    scoreLabel.textContent = 'moja avg';
    meta.textContent = `${item.ownCount} ${item.ownCount === 1 ? 'oceniony album' : 'ocenionych albumów'}`;
    note.textContent = item.bestOwnAlbum
      ? `Najwyżej: ${safeText(item.bestOwnAlbum.album)} (${formatRatingValue(item.bestOwnAlbum.score)})`
      : '';
  } else {
    scoreValue.textContent = item.mixedAverage.toFixed(2);
    scoreLabel.textContent = 'mix avg';
    meta.textContent = `RYM ${item.rymAverage.toFixed(2)} | moja ${item.ownAverage.toFixed(2)}`;
    note.textContent = item.bestMixedAlbum
      ? `Najwyższy wspólny album: ${safeText(item.bestMixedAlbum.album)} (${item.bestMixedAlbum.score.toFixed(2)})`
      : 'Wynik łączy osobne średnie zespołu.';
  }

  const lastFmArtistScrobbles = artistScrobblesFromAlbums(item.artist, STATE.rows, STATE.lastfmStats);
  if (lastFmArtistScrobbles !== null) {
    meta.textContent += ` | Last.fm ${lastFmArtistScrobbles.toLocaleString('pl-PL')} scrobbles`;
  }

  copy.append(name, meta, note);
  score.append(scoreValue, scoreLabel);
  row.append(rankEl, copy, score);
  return row;
}

function renderBrutalAssaultArtistRanking(listId, items, mode) {
  const list = $(listId);
  if (!list) return;
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'bm365-ranking-empty';
    empty.textContent = 'Brak wystarczających ocen.';
    list.appendChild(empty);
    return;
  }
  items.forEach((item, index) => {
    list.appendChild(buildBrutalAssaultArtistRow(item, index + 1, mode));
  });
}

function renderArtistView() {
  if (IS_BRUTAL_ASSAULT_2027) {
    const rankings = buildBrutalAssaultArtistRatingRankings(STATE.rows);
    renderBrutalAssaultArtistRanking('ba2027-artist-rym-list', rankings.rym, 'rym');
    renderBrutalAssaultArtistRanking('ba2027-artist-own-list', rankings.own, 'own');
    renderBrutalAssaultArtistRanking('ba2027-artist-mixed-list', rankings.mixed, 'mixed');

    const mode = ['rym', 'own', 'mixed'].includes(STATE.artistRankingMode)
      ? STATE.artistRankingMode
      : 'rym';
    const labels = {
      rym: {
        copy: 'Zespoły według średniej z ręcznie uzupełnionych ocen Rate Your Music.',
        button: 'ba2027-artist-view-rym',
      },
      own: {
        copy: 'Zespoły według średniej z albumów ocenionych przez Ciebie.',
        button: 'ba2027-artist-view-own',
      },
      mixed: {
        copy: 'Połączenie średniej RYM zespołu i średniej Twoich ocen.',
        button: 'ba2027-artist-view-mixed',
      },
    };
    ['rym', 'own', 'mixed'].forEach((candidate) => {
      $(`ba2027-artist-${candidate}-panel`)?.toggleAttribute('hidden', candidate !== mode);
      setSelectedState($(labels[candidate].button), candidate === mode);
    });
    setText('bm365-artists-copy', labels[mode].copy);
    setText('bm365-artists-count', `${rankings[mode].length} zespołów`);
    return;
  }
  const artists = computeArtistRankings(STATE.rows);
  const byCount = [...artists].sort((a, b) => {
    if (b.ratedCount !== a.ratedCount) return b.ratedCount - a.ratedCount;
    if (b.weightedRating !== a.weightedRating) return b.weightedRating - a.weightedRating;
    if (b.averageRating !== a.averageRating) return b.averageRating - a.averageRating;
    return a.artist.localeCompare(b.artist, 'pl');
  });
  const byWeighted = [...artists].sort((a, b) => {
    if (b.weightedRating !== a.weightedRating) return b.weightedRating - a.weightedRating;
    if (b.ratedCount !== a.ratedCount) return b.ratedCount - a.ratedCount;
    if (b.averageRating !== a.averageRating) return b.averageRating - a.averageRating;
    return a.artist.localeCompare(b.artist, 'pl');
  });

  setText('bm365-artists-count', `${artists.length} artists`);
  renderArtistRanking('bm365-artist-volume-list', byCount, 'count');
  renderArtistRanking('bm365-artist-average-list', byWeighted, 'weighted');
}

function syncMainViewUi() {
  const isAlbums = STATE.mainView === 'albums';
  $('bm365-albums-view')?.toggleAttribute('hidden', !isAlbums);
  $('bm365-artists-view')?.toggleAttribute('hidden', isAlbums);
  $('bm365-albums-sidebar-tools')?.toggleAttribute('hidden', !isAlbums);

  setSelectedState($('bm365-view-albums-nav'), isAlbums);
  setSelectedState($('bm365-view-artists-nav'), !isAlbums);
}

function renderCurrentView() {
  syncMainViewUi();
  if (STATE.mainView === 'artists') {
    renderArtistView();
    return;
  }
  renderAlbumList();
}

function getFinaleMount() {
  const main = document.querySelector('.page-bm365 .main');
  if (!main) return null;

  let mount = $('bm365-finale-view');
  if (!mount) {
    mount = document.createElement('section');
    mount.id = 'bm365-finale-view';
    mount.className = 'bm365-main-view';
    main.insertBefore(mount, main.firstElementChild);
  }
  return mount;
}

function setFinalePageMode(active) {
  document.body.classList.toggle('is-bm365-finale-ready', active);
  $('bm365-albums-view')?.toggleAttribute('hidden', active);
  $('bm365-artists-view')?.toggleAttribute('hidden', true);
  $('bm365-albums-sidebar-tools')?.toggleAttribute('hidden', active);
  document.querySelector('.bm365-side-nav')?.toggleAttribute('hidden', active);
  $('bm365-to-top')?.toggleAttribute('hidden', active);
}

async function renderFinalePageIfReady(rows) {
  if (IS_LOCAL_PROJECT) {
    setFinalePageMode(false);
    $('bm365-finale-view')?.remove();
    return false;
  }
  const ready = isBm365FinaleReady(rows);
  const mount = $('bm365-finale-view');

  if (!ready) {
    setFinalePageMode(false);
    mount?.remove();
    return false;
  }

  setFinalePageMode(true);
  await renderBm365FinalePage(getFinaleMount(), rows, {
    resolveCover,
  });
  return true;
}

function applyPayload(raw) {
  const rows = normalizeRows(raw);
  assignDayIndex(rows);
  STATE.rows = rows;
  STATE.coverPresence = new Map();
  STATE.byKey = new Map(rows.map((row) => [row.key, row]));
  renderRymRatingQueue();
  syncBulkDescriptionUi();
  syncManualAlbumDate(rows);
  renderStats(rows);
  renderYearOptions(rows);
  renderFinalePageIfReady(rows)
    .then((ready) => {
      if (!ready) renderCurrentView();
    })
    .catch((error) => {
      console.error(error);
      renderCurrentView();
    });
}

function applyBm365Metadata(payload) {
  const metadata = Array.isArray(payload?.metadata)
    ? payload.metadata
    : (Array.isArray(payload?.updated) ? payload.updated : (payload?.updated ? [payload.updated] : []));
  if (!metadata.length) {
    syncBulkDescriptionUi();
    return;
  }
  const byRowId = new Map(metadata.map((item) => [String(item?.rowId), item]));
  applyPayload(STATE.rows.map((row) => {
    const item = byRowId.get(String(row.rowId));
    return item
      ? { ...row, description: item.description || '' }
      : row;
  }));
}

async function fetchAllRows() {
  if (IS_LOCAL_PROJECT) {
    const res = await fetch(`${LOCAL_PROJECT_API}/albums`, { method: 'GET', cache: 'no-store' });
    if (!res.ok) throw new Error(`GET failed: ${res.status}`);
    return res.json();
  }
  return getBm365Albums();
}

async function apiUpdateLocalAlbum(patch) {
  const res = await fetch(`${LOCAL_PROJECT_API}/albums/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch)
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload?.error || `UPDATE failed: ${res.status}`);
  return payload;
}

function missingRymRatingRows() {
  if (!IS_BRUTAL_ASSAULT_2027) return [];
  const missing = STATE.rows.filter((row) => (
    row.rowId != null && !row.rymRatingIgnored && !Number.isFinite(row.rymRating)
  ));
  const missingIds = new Set(missing.map((row) => String(row.rowId)));
  const recommended = buildBrutalAssaultRecommendationQueue(STATE.rows)
    .filter((row) => missingIds.has(String(row.rowId)));
  const included = new Set(recommended.map((row) => String(row.rowId)));
  const rest = missing
    .filter((row) => !included.has(String(row.rowId)))
    .sort((a, b) => (
      String(a.date || '').localeCompare(String(b.date || ''))
      || Number(a.rowId || 0) - Number(b.rowId || 0)
    ));
  return [...recommended, ...rest];
}

function renderRymRatingQueue() {
  const list = $('ba2027-rym-rating-list');
  const count = $('ba2027-rym-rating-count');
  const artistLabel = $('ba2027-rym-rating-artist');
  const saveAll = $('ba2027-rym-rating-save-all');
  if (!list || !count || !artistLabel || !saveAll || !IS_BRUTAL_ASSAULT_2027) return;

  const allMissing = missingRymRatingRows();
  count.textContent = allMissing.length ? `${allMissing.length} bez RYM` : 'Dane kompletne';
  list.replaceChildren();

  if (!allMissing.length) {
    rymRatingArtistKey = '';
    artistLabel.textContent = '';
    artistLabel.hidden = true;
    saveAll.hidden = true;
    const complete = document.createElement('p');
    complete.className = 'ba2027-rym-complete';
    complete.textContent = 'Wszystkie albumy mają ocenę RYM.';
    list.appendChild(complete);
    return;
  }

  const availableArtistKeys = new Set(allMissing.map((row) => albumIdentityPart(row.artist)));
  if (!rymRatingArtistKey || !availableArtistKeys.has(rymRatingArtistKey)) {
    rymRatingArtistKey = albumIdentityPart(allMissing[0].artist);
  }
  const missing = allMissing.filter((row) => (
    albumIdentityPart(row.artist) === rymRatingArtistKey
  ));
  artistLabel.hidden = false;
  artistLabel.textContent = `${safeText(missing[0].artist)} · ${missing.length} ${missing.length === 1 ? 'album' : 'albumów'}`;
  saveAll.hidden = false;
  saveAll.disabled = false;
  saveAll.textContent = `Zapisz wszystkie (${missing.length})`;

  missing.forEach((row) => {
    const form = document.createElement('form');
    form.className = 'ba2027-rym-rating-item';
    form.dataset.rowId = String(row.rowId);

    const copy = document.createElement('div');
    copy.className = 'ba2027-rym-rating-copy';
    const title = document.createElement('strong');
    title.textContent = `${safeText(row.artist)} ${DASH} ${safeText(row.album)}`;
    const meta = document.createElement('span');
    meta.textContent = [row.year, Number.isFinite(row.minutes) ? `${row.minutes}m` : '']
      .filter(Boolean)
      .join(' · ');
    const link = document.createElement('a');
    link.href = rateYourMusicSearchUrl(row.artist, row.album);
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.tabIndex = -1;
    link.textContent = 'Otwórz w RYM ↗';
    copy.append(title, meta, link);

    const controls = document.createElement('div');
    controls.className = 'ba2027-rym-rating-controls';
    const input = document.createElement('input');
    input.className = 'oscars-input';
    input.type = 'text';
    input.inputMode = 'decimal';
    input.autocomplete = 'off';
    input.placeholder = 'np. 3,72';
    input.value = rymRatingDrafts.get(String(row.rowId)) || '';
    input.dataset.rowId = String(row.rowId);
    input.setAttribute('aria-label', `Ocena RYM: ${safeText(row.artist)} — ${safeText(row.album)}`);
    input.addEventListener('input', () => {
      rymRatingDrafts.set(String(row.rowId), input.value);
    });
    const save = document.createElement('button');
    save.type = 'submit';
    save.className = 'oscars-btn';
    save.tabIndex = -1;
    save.textContent = 'Zapisz';
    controls.append(input, save);

    const feedback = document.createElement('div');
    feedback.className = 'ba2027-rym-rating-feedback';
    feedback.setAttribute('aria-live', 'polite');

    form.append(copy, controls, feedback);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const value = Number(String(input.value || '').trim().replace(',', '.'));
      if (!Number.isFinite(value) || value < 0.5 || value > 5) {
        feedback.textContent = 'Wpisz ocenę od 0,50 do 5,00.';
        feedback.classList.add('is-error');
        input.focus();
        return;
      }
      input.disabled = true;
      save.disabled = true;
      feedback.classList.remove('is-error');
      feedback.textContent = 'Zapisuję…';
      try {
        const payload = await apiUpdateLocalAlbum({
          id: row.rowId,
          rymRating: Math.round(value * 100) / 100,
        });
        rymRatingDrafts.delete(String(row.rowId));
        applyPayload(payload);
        setFooter(`Ocena RYM zapisana — ${fmtDateTimeShort(new Date())}`);
      } catch (error) {
        feedback.textContent = error?.message || 'Nie udało się zapisać oceny.';
        feedback.classList.add('is-error');
        input.disabled = false;
        save.disabled = false;
      }
    });
    list.appendChild(form);
  });
}

function bindRymRatingSaveAll() {
  const button = $('ba2027-rym-rating-save-all');
  const list = $('ba2027-rym-rating-list');
  const status = $('ba2027-rym-rating-save-all-status');
  if (!button || !list || !status || !IS_BRUTAL_ASSAULT_2027) return;

  button.addEventListener('click', async () => {
    const inputs = [...list.querySelectorAll('.ba2027-rym-rating-controls input[data-row-id]')];
    if (!inputs.length) return;

    const entries = [];
    for (const input of inputs) {
      const value = Number(String(input.value || '').trim().replace(',', '.'));
      if (!Number.isFinite(value) || value < 0.5 || value > 5) {
        status.textContent = 'Uzupełnij wszystkie pola ocenami od 0,50 do 5,00.';
        status.classList.add('is-error');
        input.focus();
        return;
      }
      entries.push({
        id: input.dataset.rowId,
        rating: Math.round(value * 100) / 100,
      });
    }

    button.disabled = true;
    inputs.forEach((input) => { input.disabled = true; });
    status.classList.remove('is-error');
    status.textContent = `Zapisuję 0 / ${entries.length}…`;

    let saved = 0;
    try {
      for (const entry of entries) {
        await apiUpdateLocalAlbum({ id: entry.id, rymRating: entry.rating });
        rymRatingDrafts.delete(String(entry.id));
        saved += 1;
        status.textContent = `Zapisuję ${saved} / ${entries.length}…`;
      }
      const payload = await fetchAllRows();
      applyPayload(payload);
      status.textContent = `Zapisano wszystkie: ${saved}.`;
      setFooter(`Oceny RYM zapisane — ${fmtDateTimeShort(new Date())}`);
    } catch (error) {
      try {
        applyPayload(await fetchAllRows());
      } catch {
        inputs.forEach((input) => { input.disabled = false; });
        button.disabled = false;
      }
      status.textContent = saved
        ? `Zapisano ${saved}, potem wystąpił błąd: ${error?.message || 'nie udało się zapisać kolejnej oceny.'}`
        : (error?.message || 'Nie udało się zapisać ocen.');
      status.classList.add('is-error');
    }
  });
}

async function apiUpdateBm365Metadata(patch) {
  const { id, rowId, ...metadata } = patch;
  return updateBm365Metadata(id ?? rowId, metadata);
}

function missingDescriptionRows() {
  return STATE.rows.filter((row) => row.rowId != null && !String(row.description || '').trim());
}

function setBulkDescriptionStatus(message, tone = '') {
  const status = $('ba2027-bulk-status');
  if (!status) return;
  status.textContent = message || '';
  status.classList.toggle('is-error', tone === 'error');
  status.classList.toggle('is-success', tone === 'success');
}

function syncBulkDescriptionUi() {
  const missing = missingDescriptionRows().length;
  setText('ba2027-bulk-missing', `${missing} bez opisu`);
  const copy = $('ba2027-bulk-copy');
  if (copy) copy.disabled = missing === 0;
}

async function copyPlainText(value) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall back when clipboard permission is blocked.
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('Schowek jest niedostępny.');
}

function validateBulkDescriptionInput({ quiet = false } = {}) {
  const input = $('ba2027-bulk-json');
  const button = $('ba2027-bulk-import');
  if (!input?.value.trim()) {
    if (button) button.disabled = true;
    if (!quiet) setBulkDescriptionStatus('Wklej tutaj JSON otrzymany od AI.');
    return null;
  }

  try {
    const descriptions = parseBrutalAssaultBulkDescriptionJson(input.value);
    if (IS_RYM_POLISH_BM) validateRymDescriptionBatch(descriptions);
    const knownRows = new Map(STATE.rows.map((row) => [String(row.rowId), row]));
    const unknownIds = Object.keys(descriptions).filter((id) => !knownRows.has(id));
    if (unknownIds.length) throw new Error(`Nie ma albumów o ID: ${unknownIds.join(', ')}.`);
    const alreadyFilled = Object.keys(descriptions)
      .filter((id) => String(knownRows.get(id)?.description || '').trim()).length;
    if (button) button.disabled = false;
    if (!quiet) {
      setBulkDescriptionStatus(
        `Gotowe: ${Object.keys(descriptions).length} opisów${alreadyFilled ? ` • ${alreadyFilled} istniejących zostanie pominiętych` : ''}.`,
        'success'
      );
    }
    return descriptions;
  } catch (error) {
    if (button) button.disabled = true;
    if (!quiet) setBulkDescriptionStatus(error?.message || 'Nieprawidłowa paczka.', 'error');
    return null;
  }
}

function bindBulkDescriptions() {
  const copy = $('ba2027-bulk-copy');
  const input = $('ba2027-bulk-json');
  const importButton = $('ba2027-bulk-import');
  if (!copy || !input || !importButton) return;

  copy.addEventListener('click', async () => {
    const requestedSize = Number($('ba2027-bulk-size')?.value || 20);
    const batch = missingDescriptionRows().slice(0, requestedSize);
    if (!batch.length) {
      setBulkDescriptionStatus('Wszystkie albumy mają już opis.', 'success');
      return;
    }
    copy.disabled = true;
    try {
      const prompt = IS_RYM_POLISH_BM
        ? buildRymPolishBlackMetalBulkDescriptionPrompt(batch)
        : buildBrutalAssaultBulkDescriptionPrompt(batch);
      await copyPlainText(prompt);
      copy.textContent = `Skopiowano ${batch.length} albumów`;
      setBulkDescriptionStatus('Prompt jest w schowku. Wklej go do AI, a odpowiedź JSON w pole poniżej.', 'success');
    } catch (error) {
      setBulkDescriptionStatus(error?.message || 'Nie udało się skopiować promptu.', 'error');
    } finally {
      setTimeout(() => {
        copy.textContent = 'Kopiuj prompt + paczkę';
        copy.disabled = missingDescriptionRows().length === 0;
      }, 1800);
    }
  });

  input.addEventListener('input', () => validateBulkDescriptionInput());
  importButton.addEventListener('click', async () => {
    const descriptions = validateBulkDescriptionInput({ quiet: true });
    if (!descriptions) return;
    importButton.disabled = true;
    copy.disabled = true;
    setBulkDescriptionStatus('Zapisywanie całej paczki do SQLite...');
    try {
      const importUrl = IS_LOCAL_PROJECT
        ? `${LOCAL_PROJECT_API}/albums/descriptions/import`
        : `${LOCAL_BM365_API}/metadata/descriptions/import`;
      const response = await fetch(importUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ descriptions })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
      const importedCount = Number(payload?.updatedCount || 0);
      const skippedCount = Array.isArray(payload?.skippedIds) ? payload.skippedIds.length : 0;
      input.value = '';
      if (IS_LOCAL_PROJECT) applyPayload(payload);
      else applyBm365Metadata(payload);
      setBulkDescriptionStatus(
        `Zaimportowano ${importedCount} opisów${skippedCount ? ` • pominięto ${skippedCount} istniejących` : ''}. Możesz kopiować kolejną paczkę.`,
        'success'
      );
      setFooter(`Bulk descriptions saved - ${fmtDateTimeShort(new Date())}`);
    } catch (error) {
      console.error(error);
      setBulkDescriptionStatus(error?.message || 'Import opisów nie powiódł się.', 'error');
      importButton.disabled = false;
    } finally {
      copy.disabled = missingDescriptionRows().length === 0;
    }
  });
}

async function apiRateAlbum({ date, rowId, artist, album, rating }) {
  const value = toNumber(rating);
  if (!Number.isFinite(value)) {
    throw new Error('Missing rating');
  }

  if (IS_LOCAL_PROJECT) {
    return apiUpdateLocalAlbum({ id: rowId, rating: value });
  }

  return rateBm365Album({ date, rowId, artist, album, rating: value });
}

function localDateIso() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function nextAlbumDate(rows = STATE.rows) {
  const latest = rows
    .map((row) => String(row?.date || ''))
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value))
    .sort((a, b) => b.localeCompare(a))[0];
  if (!latest) return localDateIso();

  const [year, month, day] = latest.split('-').map(Number);
  const next = new Date(year, month - 1, day + 1);
  const nextYear = next.getFullYear();
  const nextMonth = String(next.getMonth() + 1).padStart(2, '0');
  const nextDay = String(next.getDate()).padStart(2, '0');
  return `${nextYear}-${nextMonth}-${nextDay}`;
}

function syncManualAlbumDate(rows = STATE.rows) {
  if (!IS_BRUTAL_ASSAULT_2027) return;
  const dateInput = $('ba2027-add-date');
  if (dateInput) dateInput.value = nextAlbumDate(rows);
}

function bindManualAlbumForm() {
  if (!IS_BRUTAL_ASSAULT_2027) return;
  const form = $('ba2027-add-form');
  const submit = $('ba2027-add-submit');
  const status = $('ba2027-add-status');
  const dateInput = $('ba2027-add-date');
  if (!form || !submit) return;

  if (dateInput && !dateInput.value) dateInput.value = nextAlbumDate();

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submit.disabled = true;
    if (status) status.textContent = 'Saving to the local database...';

    const body = {
      artist: $('ba2027-add-artist')?.value || '',
      album: $('ba2027-add-album')?.value || '',
      year: $('ba2027-add-year')?.value || '',
      minutes: $('ba2027-add-minutes')?.value || ''
    };
    if (dateInput?.value) body.date = dateInput.value;

    try {
      const res = await fetch(`${LOCAL_PROJECT_API}/albums`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload?.error || `HTTP ${res.status}`);
      if (status) {
        status.textContent = `${body.artist} - ${body.album} zapisany. Okładki szukam osobno w tle.`;
      }
      form.reset();
      applyPayload(payload);
      setFooter(`Saved locally - ${fmtDateTimeShort(new Date())}`);
      if (Number(payload?.communityRatingsPending || 0) > 0) {
        setTimeout(async () => {
          try {
            applyPayload(await fetchAllRows());
          } catch {
            // The album is already saved; community rating enrichment is best-effort.
          }
        }, 6000);
      }
      $('ba2027-add-artist')?.focus();
    } catch (error) {
      console.error(error);
      if (status) {
        status.textContent = error instanceof TypeError
          ? 'Brak połączenia z lokalnym API. To nie jest błąd pobierania okładki — uruchom server.py i spróbuj ponownie.'
          : (error?.message || 'Could not add the album.');
      }
    } finally {
      submit.disabled = false;
    }
  });
}

function toggleButton(button) {
  if (!button) return;
  const pressed = button.getAttribute('aria-pressed') === 'true';
  setPressedState(button, !pressed);
}

function bindFilters() {
  $('bm365-search')?.addEventListener('input', () => {
    if (STATE.mainView === 'albums') renderAlbumList();
  });
  $('bm365-year')?.addEventListener('change', () => {
    if (STATE.mainView === 'albums') renderAlbumList();
  });
  $('bm365-sort')?.addEventListener('change', () => {
    if (IS_BRUTAL_ASSAULT_2027 && ['rym_desc', 'rating_desc', 'mixed_desc'].includes($('bm365-sort')?.value)) {
      setPressedState($('bm365-hide-listened'), false);
      setPressedState($('bm365-only-rated'), $('bm365-sort')?.value === 'rating_desc');
    }
    if (STATE.mainView === 'albums') renderAlbumList();
  });

  $('bm365-hide-listened')?.addEventListener('click', (event) => {
    toggleButton(event.currentTarget);
    if (STATE.mainView === 'albums') renderAlbumList();
  });

  $('bm365-only-rated')?.addEventListener('click', (event) => {
    toggleButton(event.currentTarget);
    if (STATE.mainView === 'albums') renderAlbumList();
  });

  $('bm365-missing-covers')?.addEventListener('click', (event) => {
    toggleButton(event.currentTarget);
    if (STATE.mainView === 'albums') renderAlbumList();
  });

  $('bm365-clear-filters')?.addEventListener('click', () => {
    if ($('bm365-search')) $('bm365-search').value = '';
    if ($('bm365-year')) $('bm365-year').value = 'ALL';
    if ($('bm365-sort')) {
      $('bm365-sort').value = IS_BRUTAL_ASSAULT_2027
        ? 'recommended'
        : (IS_RYM_POLISH_BM ? 'source_asc' : 'date_asc');
    }
    setPressedState($('bm365-hide-listened'), false);
    setPressedState($('bm365-only-rated'), false);
    setPressedState($('bm365-missing-covers'), false);
    if (STATE.mainView === 'albums') renderAlbumList();
  });
}

function bindAlbumModeToggle() {
  $('bm365-view-recommended')?.addEventListener('click', () => {
    STATE.mainView = 'albums';
    if ($('bm365-sort')) $('bm365-sort').value = 'recommended';
    setPressedState($('bm365-hide-listened'), true);
    setPressedState($('bm365-only-rated'), false);
    renderCurrentView();
  });

  $('bm365-view-chronological')?.addEventListener('click', () => {
    STATE.mainView = 'albums';
    if ($('bm365-sort')) $('bm365-sort').value = IS_RYM_POLISH_BM ? 'source_asc' : 'date_asc';
    setPressedState($('bm365-only-rated'), false);
    renderCurrentView();
  });

  $('bm365-view-ranking')?.addEventListener('click', () => {
    STATE.mainView = 'albums';
    if ($('bm365-sort')) $('bm365-sort').value = 'rating_desc';
    setPressedState($('bm365-hide-listened'), false);
    setPressedState($('bm365-only-rated'), true);
    renderCurrentView();
  });

  $('bm365-view-ranking-rym')?.addEventListener('click', () => {
    STATE.mainView = 'albums';
    if ($('bm365-sort')) $('bm365-sort').value = 'rym_desc';
    setPressedState($('bm365-hide-listened'), false);
    setPressedState($('bm365-only-rated'), false);
    renderCurrentView();
  });

  $('bm365-view-ranking-mixed')?.addEventListener('click', () => {
    STATE.mainView = 'albums';
    if ($('bm365-sort')) $('bm365-sort').value = 'mixed_desc';
    setPressedState($('bm365-hide-listened'), false);
    setPressedState($('bm365-only-rated'), false);
    renderCurrentView();
  });
}

function bindSideViews() {
  $('bm365-view-albums-nav')?.addEventListener('click', () => {
    STATE.mainView = 'albums';
    renderCurrentView();
  });

  $('bm365-view-artists-nav')?.addEventListener('click', () => {
    STATE.mainView = 'artists';
    renderCurrentView();
  });
}

function bindArtistRankingToggle() {
  ['rym', 'own', 'mixed'].forEach((mode) => {
    $(`ba2027-artist-view-${mode}`)?.addEventListener('click', () => {
      STATE.artistRankingMode = mode;
      STATE.mainView = 'artists';
      renderCurrentView();
    });
  });
}

function bindScrollToTop() {
  const btn = $('bm365-to-top');
  if (!btn) return;

  const onScroll = () => {
    btn.classList.toggle('is-visible', window.scrollY > 400);
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
  const clearButton = $('bm365-clear-uploads');

  grid?.addEventListener('click', (event) => {
    const button = event.target.closest('.bm365-poster');
    if (!button) return;
    const key = button.dataset.uploadKey || '';
    if (!key) return;
    currentUploadKey = key;
    if (input) {
      input.value = '';
      input.click();
    }
  });

  input?.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file || !currentUploadKey) return;
    if (!file.type.startsWith('image/')) {
      setFooter('Only image files are supported.');
      return;
    }

    setFooter('Processing cover...');

    try {
      const key = currentUploadKey;
      const row = STATE.byKey.get(key);
      const dataUrl = await fileToDataUrl(file, 900);
      const serverUrl = await uploadCoverToServer(row, dataUrl);

      if (serverUrl) {
        const cleanUrl = serverUrl.split('?')[0];
        delete STATE.uploads[key];
        STATE.coverCache[key] = { url: cleanUrl, ts: Date.now(), local: true };
        saveUploadMap(STATE.uploads);
        saveCoverCache(STATE.coverCache);
        updatePostersForKey(key, `${cleanUrl}?t=${Date.now()}`);
        if (isMissingCoverFilterActive()) renderCurrentView();
        setFooter(`Cover saved to covers - ${fmtDateTimeShort(new Date())}`);
        return;
      }

      STATE.uploads[key] = dataUrl;
      if (!saveUploadMap(STATE.uploads)) {
        setFooter('Upload failed: local storage is full.');
        return;
      }
      updatePostersForKey(key, dataUrl);
      if (isMissingCoverFilterActive()) renderCurrentView();
      setFooter(`Cover saved locally - ${fmtDateTimeShort(new Date())}`);
    } catch (error) {
      console.error(error);
      setFooter('Upload failed.');
    } finally {
      currentUploadKey = '';
    }
  });

  clearButton?.addEventListener('click', () => {
    if (!window.confirm('Clear browser uploads?')) return;
    STATE.uploads = {};
    try {
      localStorage.removeItem(UPLOAD_STORAGE_KEY);
    } catch {
      // ignore
    }
    renderCurrentView();
    setFooter('Browser uploads cleared.');
  });
}

function bindFetchCovers() {
  const button = $('bm365-fetch-covers');
  const status = $('bm365-fetch-status');
  if (!button) return;

  button.addEventListener('click', async () => {
    if (!COVER_BATCH_API) {
      if (status) status.textContent = 'Start server.py to download covers.';
      return;
    }

    button.disabled = true;
    if (status) status.textContent = 'Downloading covers...';

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
      renderCurrentView();
    } catch (error) {
      console.error(error);
      if (status) status.textContent = 'Download failed.';
    } finally {
      button.disabled = false;
    }
  });
}

async function init() {
  setSource(`Loading ${PROJECT_LABEL} data...`, 'static');
  setFooter('Loading...');

  try {
    const payload = await fetchAllRows();
    applyPayload(payload);
    STATE.lastfmStats = await fetchLastFmAlbumStats(STATE.rows);
    renderCurrentView();
    setSource(`Source: local SQLite (${STATE.rows.length} rows) | Covers: local / iTunes / MusicBrainz`, 'api');
    const pending = Number(payload?.communityRatingsPending || 0);
    setFooter(
      IS_BRUTAL_ASSAULT_2027 && pending
        ? `MusicBrainz ratings are updating in the background (${pending} left).`
        : `Updated ${fmtDateTimeShort(new Date())}`
    );
  } catch (error) {
    console.error(error);
    setSource('Source: local SQLite (error)', 'static');
    setFooter('Failed to load data. Start the local Python server.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  bindFilters();
  bindAlbumModeToggle();
  bindSideViews();
  bindArtistRankingToggle();
  bindScrollToTop();
  bindUploads();
  bindFetchCovers();
  bindManualAlbumForm();
  bindBulkDescriptions();
  bindRymRatingSaveAll();
  init();
});
