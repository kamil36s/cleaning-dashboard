const COVER_CACHE_KEY = 'readingBookCoverCache.v1';
const UPLOAD_STORAGE_KEY = 'readingBookCoverUploads.v1';
const COLOR_CACHE_KEY = 'readingBookCoverColors.v1';
export const READING_COVERS_ENABLED_KEY = 'readingBookCoversEnabled.v1';

const COVER_CACHE_TTL_DAYS = 45;
const COVER_MISS_TTL_DAYS = 7;
const COVER_UPLOAD_TIMEOUT_MS = 4500;
const COVER_UPLOAD_API = '/api/reading/cover';
const OPEN_LIBRARY_SEARCH_API = 'https://openlibrary.org/search.json';
const OPEN_LIBRARY_COVER_API = 'https://covers.openlibrary.org/b';
const GOOGLE_BOOKS_API = 'https://www.googleapis.com/books/v1/volumes';

const STATE = {
  uploads: loadUploadMap(),
  coverCache: loadCoverCache(),
  colorCache: loadColorCache(),
};
const COVER_RESOLVE_PROMISES = new Map();
const COVER_PRELOAD_PROMISES = new Map();
const COVER_PRELOADED_URLS = new Set();
const COVER_LOCAL_CHECKED_KEYS = new Set();

function canUseStorage() {
  return typeof window !== 'undefined' && !!window.localStorage;
}

function readStorage(key) {
  if (!canUseStorage()) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key, value) {
  if (!canUseStorage()) return false;
  try {
    if (value === null || value === undefined) {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, value);
    }
    return true;
  } catch {
    return false;
  }
}

function readJsonStorage(key, fallback) {
  try {
    const raw = readStorage(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJsonStorage(key, value) {
  return writeStorage(key, JSON.stringify(value || {}));
}

function loadCoverCache() {
  const raw = readJsonStorage(COVER_CACHE_KEY, {});
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  let changed = false;
  const clean = {};
  Object.entries(raw).forEach(([key, value]) => {
    if (!value || typeof value !== 'object') return;
    if (typeof value.url === 'string' && value.url.startsWith('data:image/')) {
      changed = true;
      return;
    }
    clean[key] = value;
  });
  if (changed) saveCoverCache(clean);
  return clean;
}

function saveCoverCache(cache) {
  return writeJsonStorage(COVER_CACHE_KEY, cache);
}

function loadUploadMap() {
  writeStorage(UPLOAD_STORAGE_KEY, null);
  return {};
}

function saveUploadMap(map) {
  writeStorage(UPLOAD_STORAGE_KEY, null);
  return true;
}

function loadColorCache() {
  const raw = readJsonStorage(COLOR_CACHE_KEY, {});
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
}

function saveColorCache(map) {
  return writeJsonStorage(COLOR_CACHE_KEY, map);
}

async function fetchWithTimeout(url, options = {}, timeoutMs = COVER_UPLOAD_TIMEOUT_MS) {
  if (typeof AbortController !== 'function') {
    return fetch(url, options);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function isFresh(ts, ttlDays) {
  if (!ts) return false;
  return Date.now() - Number(ts) < ttlDays * 24 * 60 * 60 * 1000;
}

function isManualCoverHit(hit) {
  return !!hit && typeof hit === 'object' && (hit.manual === true || hit.source === 'manual' || hit.local === true);
}

function hasManualCover(key = '') {
  return isManualCoverHit(STATE.coverCache?.[key]);
}

export function isReadingCoversEnabled() {
  return readStorage(READING_COVERS_ENABLED_KEY) !== 'false';
}

export function setReadingCoversEnabled(enabled) {
  writeStorage(READING_COVERS_ENABLED_KEY, enabled ? 'true' : 'false');
}

export function slugifyReadingCoverPart(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function readingCoverSlug(book = {}, key = '') {
  const title = slugifyReadingCoverPart(book.title || book.bookTitle);
  const author = slugifyReadingCoverPart(book.author || book.bookAuthor);
  const fallback = slugifyReadingCoverPart(key);
  const base = [title, author].filter(Boolean).join('--') || fallback || 'unknown';
  return `reading--${base}`;
}

export function readingCoverLocalCandidates(book = {}, key = '') {
  const slug = readingCoverSlug(book, key);
  return [
    `./covers/${slug}.jpg`,
    `./covers/${slug}.jpeg`,
    `./covers/${slug}.png`,
    `./covers/${slug}.webp`,
  ];
}

async function tryLocalCover(book, key) {
  const candidates = readingCoverLocalCandidates(book, key);
  for (const url of candidates) {
    try {
      const response = await fetch(url, { method: 'HEAD' });
      const contentType = String(response.headers?.get?.('content-type') || '');
      if (response.ok && contentType.toLowerCase().startsWith('image/')) {
        const modified = Date.parse(String(response.headers?.get?.('last-modified') || ''));
        return Number.isFinite(modified) ? `${url}?v=${modified}` : url;
      }
    } catch {
      // Try the next local extension.
    }
  }
  return '';
}

export async function resolveLocalReadingCover(book = {}, key = '') {
  if (!isReadingCoversEnabled() || !key) return '';

  COVER_LOCAL_CHECKED_KEYS.add(key);
  const local = await tryLocalCover(book, key);
  if (!local) return '';

  STATE.coverCache[key] = { url: local, ts: Date.now(), source: 'local' };
  saveCoverCache(STATE.coverCache);
  return local;
}

function normalizeCoverBook(book = {}) {
  return {
    title: String(book.title || book.bookTitle || '').trim(),
    author: String(book.author || book.bookAuthor || '').trim(),
  };
}

export function readingCoverLetter(book = {}) {
  const title = String(book.title || book.bookTitle || '').trim();
  return title ? title.charAt(0).toLocaleUpperCase('pl') : 'K';
}

export function getCachedReadingCoverInfo(book = {}, key = '') {
  if (!key) return { known: true, url: '' };

  const hit = STATE.coverCache?.[key];
  if (hit && hit.url && isManualCoverHit(hit)) {
    if (!COVER_LOCAL_CHECKED_KEYS.has(key)) return { known: false, url: '' };
    return { known: true, url: hit.url };
  }
  if (hit && hit.url && isFresh(hit.ts, COVER_CACHE_TTL_DAYS)) {
    if (!COVER_LOCAL_CHECKED_KEYS.has(key)) return { known: false, url: '' };
    return { known: true, url: hit.url };
  }
  if (hit && hit.miss && isFresh(hit.ts, COVER_MISS_TTL_DAYS)) {
    return { known: true, url: '' };
  }

  return { known: false, url: '' };
}

export function preloadReadingCoverUrl(url = '') {
  if (!url) return Promise.resolve('');
  if (COVER_PRELOADED_URLS.has(url)) return Promise.resolve(url);
  const pending = COVER_PRELOAD_PROMISES.get(url);
  if (pending) return pending;

  const promise = new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      COVER_PRELOADED_URLS.add(url);
      resolve(url);
    };
    img.onerror = () => resolve('');
    img.src = url;
  }).finally(() => {
    COVER_PRELOAD_PROMISES.delete(url);
  });
  COVER_PRELOAD_PROMISES.set(url, promise);
  return promise;
}

export function getCachedReadingCoverColor(key = '', url = '') {
  const value = STATE.colorCache?.[key];
  if (!url && typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)) return value;
  if (!value || typeof value !== 'object') return '';
  if (url && value.url && value.url !== url) return '';
  return typeof value.color === 'string' && /^#[0-9a-f]{6}$/i.test(value.color) ? value.color : '';
}

function rgbToHex(r, g, b) {
  return `#${[r, g, b]
    .map((value) => Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, '0'))
    .join('')}`;
}

function colorDistance(left, right) {
  return Math.abs(left[0] - right[0]) + Math.abs(left[1] - right[1]) + Math.abs(left[2] - right[2]);
}

function isUsableCoverColor(r, g, b, a) {
  if (a < 180) return false;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max < 28 || min > 238) return false;
  if (max - min < 12 && (max < 64 || max > 210)) return false;
  return true;
}

export function dominantColorFromImageData(imageData, step = 12) {
  const data = imageData?.data;
  if (!data?.length) return '';
  const buckets = new Map();
  const stride = Math.max(1, Math.round(step)) * 4;

  for (let i = 0; i < data.length; i += stride) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const a = data[i + 3] ?? 255;
    if (!isUsableCoverColor(r, g, b, a)) continue;

    const qr = Math.round(r / 24) * 24;
    const qg = Math.round(g / 24) * 24;
    const qb = Math.round(b / 24) * 24;
    const key = `${qr},${qg},${qb}`;
    const current = buckets.get(key) || { count: 0, r: 0, g: 0, b: 0 };
    current.count += 1;
    current.r += r;
    current.g += g;
    current.b += b;
    buckets.set(key, current);
  }

  let best = null;
  for (const bucket of buckets.values()) {
    const avg = [bucket.r / bucket.count, bucket.g / bucket.count, bucket.b / bucket.count];
    const saturation = Math.max(...avg) - Math.min(...avg);
    const nearWhitePenalty = colorDistance(avg, [245, 245, 245]) < 72 ? 0.3 : 1;
    const score = bucket.count * (1 + Math.min(80, saturation) / 120) * nearWhitePenalty;
    if (!best || score > best.score) {
      best = { score, avg };
    }
  }

  return best ? rgbToHex(best.avg[0], best.avg[1], best.avg[2]) : '';
}

function loadImageForColor(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Image color load failed'));
    img.src = url;
  });
}

async function sampleCoverColorFromUrl(url, displayedImage = null) {
  const image = displayedImage || await loadImageForColor(url);
  const maxSize = 96;
  const scale = Math.min(1, maxSize / Math.max(image.naturalWidth || image.width, image.naturalHeight || image.height));
  const width = Math.max(1, Math.round((image.naturalWidth || image.width) * scale));
  const height = Math.max(1, Math.round((image.naturalHeight || image.height) * scale));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return '';
  ctx.drawImage(image, 0, 0, width, height);
  return dominantColorFromImageData(ctx.getImageData(0, 0, width, height));
}

function isExternalCoverUrl(url = '') {
  try {
    const parsed = new URL(url, window.location.href);
    return parsed.origin !== window.location.origin;
  } catch {
    return false;
  }
}

export async function resolveReadingCoverColor(key = '', url = '', displayedImage = null) {
  if (!key || !url) return '';
  const cached = getCachedReadingCoverColor(key, url);
  if (cached) return cached;

  let color = '';
  try {
    color = await sampleCoverColorFromUrl(url, displayedImage);
  } catch (error) {
    if (!isExternalCoverUrl(url)) throw error;
    const localUrl = await saveRemoteCoverToServer({}, key, url);
    if (localUrl) {
      color = await sampleCoverColorFromUrl(localUrl.split('?')[0]);
    }
  }
  if (color) {
    STATE.colorCache[key] = { url, color, ts: Date.now() };
    saveColorCache(STATE.colorCache);
  }
  return color;
}

export function openLibraryCoverUrlFromDoc(doc) {
  const coverId = doc?.cover_i;
  if (coverId) return `${OPEN_LIBRARY_COVER_API}/id/${encodeURIComponent(String(coverId))}-L.jpg?default=false`;

  const isbn = Array.isArray(doc?.isbn)
    ? doc.isbn.find((value) => String(value || '').trim())
    : '';
  return isbn ? `${OPEN_LIBRARY_COVER_API}/isbn/${encodeURIComponent(String(isbn).trim())}-L.jpg?default=false` : '';
}

export function buildReadingCoverSearchQuery(book = {}) {
  const normalized = normalizeCoverBook(book);
  const parts = [];
  if (normalized.title) parts.push(`intitle:${normalized.title}`);
  if (normalized.author) parts.push(`inauthor:${normalized.author}`);
  return parts.join(' ');
}

async function fetchCoverOpenLibrary(book) {
  const normalized = normalizeCoverBook(book);
  if (!normalized.title) return '';

  const url = new URL(OPEN_LIBRARY_SEARCH_API);
  url.searchParams.set('title', normalized.title);
  if (normalized.author) url.searchParams.set('author', normalized.author);
  url.searchParams.set('fields', 'title,author_name,cover_i,isbn');
  url.searchParams.set('limit', '5');

  const res = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
  if (!res.ok) return '';
  const payload = await res.json();
  const docs = Array.isArray(payload?.docs) ? payload.docs : [];
  for (const doc of docs) {
    const coverUrl = openLibraryCoverUrlFromDoc(doc);
    if (coverUrl) return coverUrl;
  }
  return '';
}

export function normalizeGoogleBooksImageUrl(value) {
  if (!value) return '';
  return String(value).replace(/^http:/i, 'https:');
}

async function fetchCoverGoogleBooks(book) {
  const query = buildReadingCoverSearchQuery(book);
  if (!query) return '';

  const url = new URL(GOOGLE_BOOKS_API);
  url.searchParams.set('q', query);
  url.searchParams.set('printType', 'books');
  url.searchParams.set('maxResults', '5');

  const res = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
  if (!res.ok) return '';
  const payload = await res.json();
  const items = Array.isArray(payload?.items) ? payload.items : [];
  for (const item of items) {
    const links = item?.volumeInfo?.imageLinks || {};
    const coverUrl = normalizeGoogleBooksImageUrl(
      links.extraLarge || links.large || links.medium || links.small || links.thumbnail || links.smallThumbnail,
    );
    if (coverUrl) return coverUrl;
  }
  return '';
}

async function saveRemoteCoverToServer(book, key, sourceUrl) {
  if (!sourceUrl) return '';
  try {
    const res = await fetchWithTimeout(COVER_UPLOAD_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key,
        title: book?.title || book?.bookTitle || '',
        author: book?.author || book?.bookAuthor || '',
        sourceUrl,
      }),
    });
    if (!res.ok) return '';
    const payload = await res.json();
    return payload?.ok && payload?.url ? String(payload.url) : '';
  } catch {
    return '';
  }
}

async function uploadCoverToServer(book, key, dataUrl) {
  try {
    const res = await fetchWithTimeout(COVER_UPLOAD_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key,
        title: book?.title || book?.bookTitle || '',
        author: book?.author || book?.bookAuthor || '',
        dataUrl,
      }),
    });
    if (!res.ok) return '';
    const payload = await res.json();
    return payload?.ok && payload?.url ? String(payload.url) : '';
  } catch {
    return '';
  }
}

async function fileToDataUrl(file, maxSize = 1100) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });

  const image = await new Promise((resolve, reject) => {
    const img = new Image();
    const timer = setTimeout(() => reject(new Error('Image decode timed out')), 5000);
    const finish = (callback, value) => () => {
      clearTimeout(timer);
      callback(value);
    };
    img.onload = finish(resolve, img);
    img.onerror = finish(() => reject(new Error('Invalid image')));
    img.src = dataUrl;
  });

  const maxDim = Math.max(image.width, image.height);
  if (!Number.isFinite(maxDim) || maxDim <= maxSize) return dataUrl;

  const scale = maxSize / maxDim;
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(image.width * scale);
  canvas.height = Math.round(image.height * scale);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.9);
}

export async function resolveReadingCover(book = {}, key = '') {
  if (!isReadingCoversEnabled() || !key) return '';

  const cached = getCachedReadingCoverInfo(book, key);
  if (cached.known) {
    return cached.url;
  }

  const pending = COVER_RESOLVE_PROMISES.get(key);
  if (pending) return pending;

  const promise = (async () => {
    const cachedFallback = STATE.coverCache?.[key];
    const local = await resolveLocalReadingCover(book, key);
    if (local) {
      return local;
    }

    if (cachedFallback?.url && isFresh(cachedFallback.ts, COVER_CACHE_TTL_DAYS)) {
      return cachedFallback.url;
    }

    try {
      const remoteUrl = await fetchCoverOpenLibrary(book) || await fetchCoverGoogleBooks(book);
      const serverUrl = remoteUrl ? await saveRemoteCoverToServer(book, key, remoteUrl) : '';
      const url = serverUrl || remoteUrl;
      const manual = getCachedReadingCoverInfo(book, key);
      if (manual.url && hasManualCover(key)) return manual.url;
      STATE.coverCache[key] = url
        ? { url: serverUrl ? serverUrl.split('?')[0] : url, ts: Date.now(), source: 'remote' }
        : { url: '', ts: Date.now(), miss: true };
      saveCoverCache(STATE.coverCache);
      return url || '';
    } catch {
      const manual = getCachedReadingCoverInfo(book, key);
      if (manual.url && hasManualCover(key)) return manual.url;
      STATE.coverCache[key] = { url: '', ts: Date.now(), miss: true };
      saveCoverCache(STATE.coverCache);
      return '';
    }
  })().finally(() => {
    COVER_RESOLVE_PROMISES.delete(key);
  });
  COVER_RESOLVE_PROMISES.set(key, promise);
  return promise;
}

export async function saveReadingCoverUpload(book = {}, key = '', file) {
  if (!key || !file || !String(file.type || '').startsWith('image/')) {
    throw new Error('Unsupported image file');
  }

  const dataUrl = await fileToDataUrl(file);
  const serverUrl = await uploadCoverToServer(book, key, dataUrl);
  if (serverUrl) {
    const cleanUrl = serverUrl.split('?')[0];
    COVER_LOCAL_CHECKED_KEYS.add(key);
    const manualUrl = await tryLocalCover(book, key) || `${cleanUrl}?t=${Date.now()}`;
    STATE.coverCache[key] = { url: manualUrl, ts: Date.now(), manual: true, source: 'manual' };
    delete STATE.colorCache[key];
    saveUploadMap({});
    saveCoverCache(STATE.coverCache);
    saveColorCache(STATE.colorCache);
    COVER_RESOLVE_PROMISES.delete(key);
    return manualUrl;
  }

  throw new Error('Lokalny serwer nie zapisal pliku do folderu covers.');
}
