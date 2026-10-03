// js/bm365.js
import { fmtDateTimeShort } from './utils.js';
import { createAlbumStarRating } from './album-star-rating.js';
import { loadTimeSuffix, startLoadTimer } from './load-timing.js';
import { createRateYourMusicSearchLink, createSpotifySearchLink, createYoutubeSearchLink } from './spotify-link.js';
import { isBm365FinaleReady, renderBm365FinaleWidget } from './bm365-summary.js';
import { appendLastFmAlbumBadge, fetchLastFmAlbumStats } from './lastfm-stats.js';
import { setDailyAchievement } from './daily-achievements.js';
import { getBm365Albums, markBm365Listened, rateBm365Album } from './bm365-api.js';
import {
  albumDescriptionTeaser,
  copyBrutalAssaultAlbumPrompt,
  renderBrutalAssaultAlbumDescription,
} from './brutal-assault-recommendations.js';
// Black Metal 365 - widget backed by the local SQLite REST API.
// + auto-okładki z iTunes (cache w localStorage)

const CONFIG = {
  // Stabilne nazwy pól w publicznym kontrakcie BM365.
  FIELDS: {
    date: "date", // "YYYY-MM-DD"
    artist: "artist",
    album: "album",
    listened: "listened", // "" / "TAK"
    rating: "rating", // liczba lub ""
    minutes: "minutes", // liczba minut lub ""
    rowId: "rowId", // opcjonalne
  },

  RECENT_LIMIT: 5,
};

let LASTFM_STATS = new Map();

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);

function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function toNumber(x) {
  if (x === null || x === undefined) return null;
  const s = String(x).trim();
  if (!s) return null;

  // Extract first number from text like "42m", "42 min", "42,5"
  const m = s.match(/-?\d+(?:[.,]\d+)?/);
  if (!m) return null;

  const n = Number(m[0].replace(",", "."));
  return Number.isFinite(n) ? n : null;
}


function safeText(x) {
  return x === null || x === undefined ? "—" : String(x);
}

function pct(done, total) {
  if (!total) return 0;
  return Math.round((done / total) * 100);
}

function dayOfYear_() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const diff = now - start;
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function albumIdentityPart_(value) {
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

function albumIdentityKey_(artist, album) {
  return `${albumIdentityPart_(artist)}|${albumIdentityPart_(album)}`;
}

function appendCrossListBadge_(container, row) {
  const crossLists = Array.isArray(row?.crossLists)
    ? row.crossLists.filter(Boolean)
    : (row?.crossList ? [row.crossList] : []);
  if (!container || !crossLists.length) return;
  const tags = document.createElement('div');
  tags.className = 'bm365-tags';
  crossLists.forEach((crossList) => {
    const badge = document.createElement('span');
    badge.className = 'bm365-tag is-cross-list';
    badge.title = `Ten album jest również na liście ${crossList.label || 'innej liście'}`;
    badge.textContent = `◆ ${crossList.label || 'Inna lista'}`;
    tags.appendChild(badge);
  });
  container.appendChild(tags);
}

function updateBm365Progress_(done, total) {
  const bar = $("bm365-progress-bar");
  const delta = $("bm365-progress-delta");
  if (!bar) return;

  const safeTotal = Number.isFinite(total) && total > 0 ? total : 0;
  const safeDone = Number.isFinite(done) ? Math.max(0, done) : 0;
  const clampedDone = safeTotal ? Math.min(safeDone, safeTotal) : 0;
  const pct = safeTotal ? (clampedDone / safeTotal) * 100 : 0;
  bar.style.width = `${pct}%`;

  if (!delta) return;

  delta.classList.remove("is-ahead", "is-behind");
  if (!safeTotal) {
    delta.style.width = "0%";
    delta.style.left = "0%";
    return;
  }

  const target = Math.min(dayOfYear_(), safeTotal);
  const targetPct = (target / safeTotal) * 100;
  let deltaPct = 0;
  let leftPct = 0;

  if (clampedDone > target) {
    deltaPct = ((clampedDone - target) / safeTotal) * 100;
    leftPct = targetPct;
    delta.classList.add("is-ahead");
  } else if (clampedDone < target) {
    deltaPct = ((target - clampedDone) / safeTotal) * 100;
    leftPct = pct;
    delta.classList.add("is-behind");
  } else {
    deltaPct = 0;
    leftPct = pct;
  }

  delta.style.width = `${Math.min(100, Math.max(0, deltaPct))}%`;
  delta.style.left = `${Math.min(100, Math.max(0, leftPct))}%`;
}

function formatMinutes(totalMin) {
  if (!Number.isFinite(totalMin)) return "—";
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h <= 0) return `${m}m`;
  return `${h}h ${m}m`;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setFooter(msg) {
  const el = $("bm365-foot");
  if (!el) return;
  el.textContent = msg || "";
}

function setFooterWithLoad(msg, loadMs) {
  const load = loadTimeSuffix(loadMs);
  setFooter(`${msg || ""}${load ? ` · ${load}` : ""}`);
}

function clearRecent() {
  const grid = $("bm365-recent-grid");
  if (grid) grid.innerHTML = "";
}

// ---------- covers (iTunes) ----------
const BM_COVER_CACHE_KEY = "bm365_cover_cache_v1";
const BM_COVER_CACHE_TTL_DAYS = 30;
const BM_COVER_MISS_TTL_DAYS = 7;
const BM_UPLOADS_KEY = "bm365_uploads_v1";
const BM_PREFETCH_TTL_DAYS = 14;
const BM_PREFETCH_TS_KEY = "bm365_prefetch_ts_v1";
const BM_PREFETCH_RUNNING_KEY = "bm365_prefetch_running_v1";
const BM_MISSING_KEY = "bm365_missing_covers_v1";
const BM_RANDOM_PICK_KEY = "bm365_random_pick_v1";

function bm_slugify_(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
function bm_coverSlug_(artist, album) {
  const a = bm_slugify_(artist);
  const b = bm_slugify_(album);
  const base = [a, b].filter(Boolean).join("--");
  return base || "unknown";
}
function bm_localCoverCandidates_(artist, album) {
  const slug = bm_coverSlug_(artist, album);
  return [
    `./covers/${slug}.jpg`,
    `./covers/${slug}.jpeg`,
    `./covers/${slug}.png`,
    `./covers/${slug}.webp`,
  ];
}
function bm_tryLocalCover_(artist, album) {
  const candidates = bm_localCoverCandidates_(artist, album);
  return new Promise((resolve) => {
    const tryAt = (i) => {
      if (i >= candidates.length) return resolve("");
      const url = candidates[i];
      const img = new Image();
      img.onload = () => resolve(url);
      img.onerror = () => tryAt(i + 1);
      img.src = url;
    };
    tryAt(0);
  });
}
function bm_coverHint_(artist, album) {
  const slug = bm_coverSlug_(artist, album);
  return `covers/${slug}.jpg|.png|.webp`;
}

function bm_loadCoverCache_() {
  try {
    return JSON.parse(localStorage.getItem(BM_COVER_CACHE_KEY) || "{}");
  } catch {
    return {};
  }
}
function bm_loadUploads_() {
  try {
    const raw = JSON.parse(localStorage.getItem(BM_UPLOADS_KEY) || "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}
function bm_normKey_(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}
function bm_findUpload_(artist, album) {
  const uploads = bm_loadUploads_();
  const target = bm_normKey_(`${artist} ${album}`);
  if (!target) return "";
  const keys = Object.keys(uploads);
  for (let i = 0; i < keys.length; i += 1) {
    const key = keys[i];
    if (bm_normKey_(key) === target) return uploads[key] || "";
  }
  return "";
}
function bm_saveCoverCache_(obj) {
  try {
    localStorage.setItem(BM_COVER_CACHE_KEY, JSON.stringify(obj));
  } catch {}
}
function bm_cacheKey_(artist, album) {
  return (
    (String(artist || "").trim() + " — " + String(album || "").trim()).toLowerCase()
  );
}
function bm_isFresh_(ts, ttlDays = BM_COVER_CACHE_TTL_DAYS) {
  if (!ts) return false;
  const ageMs = Date.now() - ts;
  return ageMs < ttlDays * 24 * 60 * 60 * 1000;
}
function bm_upgradeArtworkUrl_(url, sizePx = 600) {
  if (!url) return "";
  return String(url).replace(
    /\/(\d+)x(\d+)bb\.(jpg|png)/i,
    `/${sizePx}x${sizePx}bb.$3`
  );
}
async function bm_fetchCoverItunes_(artist, album) {
  const term = `${artist} ${album}`.trim();
  if (!term) return "";

  const u = new URL("https://itunes.apple.com/search");
  u.searchParams.set("term", term);
  u.searchParams.set("entity", "album");
  u.searchParams.set("limit", "1");

  const res = await fetch(u.toString());
  if (!res.ok) return "";
  const data = await res.json();
  const item = data?.results?.[0];
  const art = item?.artworkUrl100 || item?.artworkUrl60 || "";
  return bm_upgradeArtworkUrl_(art, 600);
}
async function bm_getCoverUrl_(artist, album, opts = {}) {
  const { force = false } = opts;
  const key = bm_cacheKey_(artist, album);
  if (!key || key === " ??? ") return "";

  const cache = bm_loadCoverCache_();

  const uploaded = bm_findUpload_(artist, album);
  if (uploaded) return uploaded;

  // Prefer locally saved covers over cached remote URLs.
  const local = await bm_tryLocalCover_(artist, album);
  if (local) {
    cache[key] = { url: local, ts: Date.now(), local: true };
    bm_saveCoverCache_(cache);
    return local;
  }

  const hit = cache[key];
  if (hit && hit.url && bm_isFresh_(hit.ts, BM_COVER_CACHE_TTL_DAYS)) return hit.url;

  if (hit && !force && hit.miss && bm_isFresh_(hit.ts, BM_COVER_MISS_TTL_DAYS)) return "";

  try {
    const url = await bm_fetchCoverItunes_(artist, album);
    cache[key] = url
      ? { url, ts: Date.now() }
      : { url: "", ts: Date.now(), miss: true };
    bm_saveCoverCache_(cache);
    return url || "";
  } catch {
    cache[key] = { url: "", ts: Date.now(), miss: true };
    bm_saveCoverCache_(cache);
    return "";
  }
}

function bm_prefetchDue_() {
  const ts = Number(localStorage.getItem(BM_PREFETCH_TS_KEY) || 0);
  return Date.now() - ts > BM_PREFETCH_TTL_DAYS * 24 * 60 * 60 * 1000;
}

function bm_saveMissingList_(items) {
  try {
    localStorage.setItem(
      BM_MISSING_KEY,
      JSON.stringify({ ts: Date.now(), items: items || [] })
    );
  } catch {}
}

function bm_loadMissingList_() {
  try {
    const raw = JSON.parse(localStorage.getItem(BM_MISSING_KEY) || "{}");
    return Array.isArray(raw.items) ? raw.items : [];
  } catch {
    return [];
  }
}

function bm_renderMissingList_(items) {
  const wrap = $("bm365-missing");
  const countEl = $("bm365-missing-count");
  const listEl = $("bm365-missing-list");
  if (!wrap || !countEl || !listEl) return;

  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    wrap.hidden = true;
    return;
  }

  wrap.hidden = false;
  countEl.textContent = String(list.length);
  listEl.textContent = list
    .map((r) => `${r.artist} - ${r.album} (${bm_coverHint_(r.artist, r.album)})`)
    .join("\n");
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function prefetchAllCovers(rows) {
  if (!rows || !rows.length) return;
  if (!bm_prefetchDue_()) return;
  if (localStorage.getItem(BM_PREFETCH_RUNNING_KEY) === "1") return;

  localStorage.setItem(BM_PREFETCH_RUNNING_KEY, "1");

  const map = new Map();
  for (const r of rows) {
    const key = bm_cacheKey_(r.artist, r.album);
    if (key && !map.has(key)) map.set(key, r);
  }

  const items = Array.from(map.values());
  const missing = [];
  let cursor = 0;
  const concurrency = 4;
  const delayMs = 120;

  async function worker() {
    while (true) {
      const r = items[cursor++];
      if (!r) break;
      try {
        const url = await bm_getCoverUrl_(r.artist, r.album, { force: true });
        if (!url) missing.push(r);
      } catch {
        missing.push(r);
      }
      if (delayMs) await sleep(delayMs);
    }
  }

  await Promise.all(Array.from({ length: concurrency }, worker));

  localStorage.setItem(BM_PREFETCH_TS_KEY, String(Date.now()));
  localStorage.removeItem(BM_PREFETCH_RUNNING_KEY);

  bm_saveMissingList_(missing);
  bm_renderMissingList_(missing);
}

function schedulePrefetch(rows) {
  if (!bm_prefetchDue_()) return;
  const run = () => prefetchAllCovers(rows).catch((e) => console.error(e));
  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(run, { timeout: 2000 });
  } else {
    setTimeout(run, 1500);
  }
}

// ---------- API ----------
async function apiGetAll() {
  return getBm365Albums();
}

export function mergeBm365Metadata_(payload, metadataPayload) {
  const metadata = Array.isArray(metadataPayload?.metadata) ? metadataPayload.metadata : [];
  if (!metadata.length) return payload;
  const byRowId = new Map(metadata.map((item) => [String(item?.rowId), item]));
  const byKey = new Map(metadata.map((item) => [
    albumIdentityKey_(item?.artist, item?.album),
    item
  ]));
  const sourceRows = Array.isArray(payload) ? payload : payload?.rows || [];
  const rows = sourceRows.map((row) => {
    const key = albumIdentityKey_(row?.artist, row?.album);
    const idMatch = byRowId.get(String(row?.rowId));
    const item = idMatch && albumIdentityKey_(idMatch.artist, idMatch.album) === key
      ? idMatch
      : byKey.get(key);
    if (!item) return row;
    return {
      ...row,
      year: item.year || row?.year || '',
      description: item.description || ''
    };
  });
  return Array.isArray(payload) ? rows : { ...payload, rows };
}

async function apiMarkListened({ date, rowId }) {
  return markBm365Listened({ date, rowId, listened: true });
}

async function apiRateAlbum({ date, rowId, artist, album, rating }) {
  const value = toNumber(rating);
  if (!Number.isFinite(value)) {
    throw new Error("Missing rating");
  }

  return rateBm365Album({ date, rowId, artist, album, rating: value });
}

// ---------- main render ----------
function normalizeRows(raw) {
  const rows = Array.isArray(raw) ? raw : raw.rows || [];
  const f = CONFIG.FIELDS;

  return rows
    .map((r) => {
      const date = r[f.date];
      return {
        date: date ? String(date) : "",
        artist: safeText(r[f.artist]),
        album: safeText(r[f.album]),
        listened: String(r[f.listened] || "").toUpperCase() === "TAK",
        rating: toNumber(r[f.rating]),
        minutes: toNumber(r[f.minutes]),
        year: String(r.year || '').trim(),
        description: String(r.description || '').trim(),
        rowId: r[f.rowId] ?? null,
        crossList: r.crossList && typeof r.crossList === 'object' ? { ...r.crossList } : null,
        crossLists: Array.isArray(r.crossLists)
          ? r.crossLists.filter(Boolean).map((item) => ({ ...item }))
          : (r.crossList && typeof r.crossList === 'object' ? [{ ...r.crossList }] : []),
      };
    })
    .filter((r) => r.date);
}

function computeStats(rows) {
  const total = rows.length;
  const done = rows.filter((r) => r.listened).length;
  const left = Math.max(0, total - done);

  const rated = rows.filter((r) => Number.isFinite(r.rating));
  const avgRating = rated.length
    ? rated.reduce((a, b) => a + b.rating, 0) / rated.length
    : null;

  const timeRows = rows.filter((r) => r.listened && Number.isFinite(r.minutes));
  const totalMinutes = timeRows.reduce((a, b) => a + b.minutes, 0);

  return {
    total,
    done,
    left,
    pct: pct(done, total),
    avgRating,
    ratedCount: rated.length,
    totalMinutes,
    timeCount: timeRows.length,
  };
}

function formatCountPl(value, one, few, many) {
  const abs = Math.abs(Number(value) || 0);
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (abs === 1) return `${abs} ${one}`;
  if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) {
    return `${abs} ${few}`;
  }
  return `${abs} ${many}`;
}

function computeCatchUpTime(rows, today) {
  const catchUpRows = rows.filter((r) => !r.listened && r.date <= today);
  const rowsWithMinutes = catchUpRows.filter((r) => Number.isFinite(r.minutes));

  return {
    hasOverdue: catchUpRows.some((r) => r.date < today),
    count: catchUpRows.length,
    totalMinutes: rowsWithMinutes.reduce((sum, row) => sum + row.minutes, 0),
    missingMinutes: catchUpRows.length - rowsWithMinutes.length,
  };
}

function parseISODateMs(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const ms = Date.UTC(year, month - 1, day);
  return Number.isFinite(ms) ? ms : null;
}

function daysBetweenInclusive(startDate, endDate) {
  const startMs = parseISODateMs(startDate);
  const endMs = parseISODateMs(endDate);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return 0;
  return Math.floor((endMs - startMs) / 86400000) + 1;
}

function formatDecimalPl(value, digits = 1) {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(digits).replace(".", ",");
}

function computeRemainingProjection(rows, today) {
  const remainingRows = rows.filter((r) => !r.listened);
  const rowsWithMinutes = remainingRows.filter((r) => Number.isFinite(r.minutes));
  const dates = rows.map((r) => r.date).filter(Boolean).sort((a, b) => a.localeCompare(b));
  const elapsedDays = dates.length ? daysBetweenInclusive(dates[0], today) : 0;
  const done = rows.filter((r) => r.listened).length;
  const pace = elapsedDays > 0 && done > 0 ? done / elapsedDays : null;

  return {
    count: remainingRows.length,
    totalMinutes: rowsWithMinutes.reduce((sum, row) => sum + row.minutes, 0),
    missingMinutes: remainingRows.length - rowsWithMinutes.length,
    pace,
    estimatedDays: pace > 0 && remainingRows.length ? Math.ceil(remainingRows.length / pace) : null,
  };
}

function renderRemainingProjection(rows, today) {
  const el = $("bm365-projection");
  if (!el) return;

  const projection = computeRemainingProjection(rows, today);
  if (!projection.count) {
    el.hidden = true;
    el.textContent = "";
    return;
  }

  const countText = formatCountPl(projection.count, "album", "albumy", "albumów");
  const timeText = projection.totalMinutes > 0 ? formatMinutes(projection.totalMinutes) : "brak czasu";
  const missingText = projection.missingMinutes ? ` (${projection.missingMinutes} bez czasu)` : "";
  const paceText = projection.pace ? `${formatDecimalPl(projection.pace, projection.pace >= 1 ? 1 : 2)}/dzień` : "brak tempa";
  const etaText = projection.estimatedDays
    ? `ok. ${formatCountPl(projection.estimatedDays, "dzień", "dni", "dni")}`
    : "brak estymacji";

  el.textContent = `Zostało: ${countText} • ${timeText}${missingText} • tempo ${paceText}: ${etaText}`;
  el.hidden = false;
}

function formatRatingValue(value) {
  if (!Number.isFinite(value)) return "";
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function createRatingSelect(selectedValue, placeholder = "Ocena") {
  return createAlbumStarRating(selectedValue, {
    ariaLabel: placeholder,
  });
}

function renderCatchUpInfo(rows, today) {
  const el = $("bm365-catchup");
  if (!el) return;

  const catchUp = computeCatchUpTime(rows, today);
  if (!catchUp.hasOverdue) {
    el.hidden = true;
    el.textContent = "";
    return;
  }

  const parts = [];
  if (catchUp.totalMinutes > 0) {
    parts.push(`Do nadrobienia: ${formatMinutes(catchUp.totalMinutes)}`);
  } else {
    parts.push("Do nadrobienia: brak danych o czasie");
  }

  parts.push(formatCountPl(catchUp.count, "album", "albumy", "albumów"));
  if (catchUp.missingMinutes) {
    parts.push(`${catchUp.missingMinutes} bez czasu`);
  }

  el.textContent = parts.join(" • ");
  el.hidden = false;
}

function findAlbumOfDay(rows, today) {
  return rows.find((r) => r.date === today) || null;
}

function findNextUp(rows, today) {
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  const future = sorted.find((r) => !r.listened && r.date >= today);
  if (future) return future;
  return sorted.find((r) => !r.listened) || null;
}

function findFirstOverdue(rows, today) {
  return (
    [...rows]
      .filter((r) => !r.listened && r.date < today)
      .sort((a, b) => a.date.localeCompare(b.date))[0] || null
  );
}

function bm_albumPickKey_(row) {
  if (!row) return "";
  return [row.date, row.artist, row.album, row.rowId || ""].map((part) => String(part || "")).join("|");
}

function bm_isSuggestionCandidate_(row) {
  return row && !row.listened && !Number.isFinite(row.rating);
}

function bm_randomIndex_(length) {
  if (!Number.isFinite(length) || length <= 0) return -1;
  if (globalThis.crypto?.getRandomValues) {
    const value = new Uint32Array(1);
    globalThis.crypto.getRandomValues(value);
    return value[0] % length;
  }
  return Math.floor(Math.random() * length);
}

function findStableRandomSuggestion(rows) {
  const candidates = rows.filter(bm_isSuggestionCandidate_);
  if (!candidates.length) {
    localStorage.removeItem(BM_RANDOM_PICK_KEY);
    return null;
  }

  const storedKey = localStorage.getItem(BM_RANDOM_PICK_KEY);
  const storedPick = storedKey
    ? candidates.find((row) => bm_albumPickKey_(row) === storedKey)
    : null;
  if (storedPick) return storedPick;

  const nextPick = candidates[bm_randomIndex_(candidates.length)] || null;
  if (nextPick) {
    localStorage.setItem(BM_RANDOM_PICK_KEY, bm_albumPickKey_(nextPick));
  }
  return nextPick;
}

function hasAlternativeRandomSuggestion(rows, currentRow) {
  const currentKey = bm_albumPickKey_(currentRow);
  return rows.filter((row) => bm_isSuggestionCandidate_(row) && bm_albumPickKey_(row) !== currentKey).length > 0;
}

function refreshRandomSuggestion(rows, currentRow) {
  const candidates = rows.filter(bm_isSuggestionCandidate_);
  if (!candidates.length) {
    localStorage.removeItem(BM_RANDOM_PICK_KEY);
    return null;
  }

  const currentKey = bm_albumPickKey_(currentRow);
  const pool =
    candidates.length > 1
      ? candidates.filter((row) => bm_albumPickKey_(row) !== currentKey)
      : candidates;

  const nextPick = pool[bm_randomIndex_(pool.length)] || null;
  if (nextPick) {
    localStorage.setItem(BM_RANDOM_PICK_KEY, bm_albumPickKey_(nextPick));
  }
  return nextPick;
}

function updateBm365GoalState(rows, today) {
  const card = $("bm365-card");
  if (!card) return;

  const hasOverdue = rows.some((r) => !r.listened && r.date < today);
  card.classList.toggle("is-goal-complete", !hasOverdue);
  card.classList.toggle("is-bloody-overdue", hasOverdue);
}

function clearBm365GoalState() {
  const card = $("bm365-card");
  if (!card) return;
  card.classList.remove("is-goal-complete", "is-bloody-overdue", "is-finale-complete");
}

function clearBm365FinaleWidgetState() {
  const card = $("bm365-card");
  const grid = $("bm365-recent-grid");
  card?.classList.remove("is-finale-complete");
  grid?.classList.remove("bm365-finale-mount");
}

function recentListened(rows) {
  return rows
    .filter((r) => r.listened)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, CONFIG.RECENT_LIMIT);
}

async function renderTopRated(rows) {
  const grid = $("bm365-top-grid");
  if (!grid) return;

  grid.innerHTML = "";

  let rank = 1;
  for (const r of rows) {
    const cover = await bm_getCoverUrl_(r.artist, r.album);

    const wrap = document.createElement("div");
    wrap.className = "bm365-row bm365-top-row";

    const rankEl = document.createElement("div");
    rankEl.className = "bm365-rank";
    rankEl.textContent = `${rank}.`;

    const left = document.createElement("div");
    left.className = "bm365-left";

    if (cover) {
      const img = document.createElement("img");
      img.className = "bm365-cover";
      img.alt = "";
      img.src = cover;
      img.loading = "lazy";
      img.decoding = "async";
      img.onerror = () => {
        img.style.display = "none";
      };
      left.appendChild(img);
    } else {
      const ph = document.createElement("div");
      ph.className = "bm365-cover bm365-cover--placeholder";
      ph.textContent = "NO";
      left.appendChild(ph);
    }

    const text = document.createElement("div");
    text.className = "bm365-text";

    const title = document.createElement("div");
    title.className = "bm365-title";
    title.textContent = `${r.artist} — ${r.album}`;

    const sub = document.createElement("div");
    sub.className = "bm365-sub";
    sub.textContent = `${r.date} • ★ ${r.rating}`;

    text.appendChild(title);
    appendCrossListBadge_(text, r);
    appendLastFmAlbumBadge(text, r, LASTFM_STATS);
    text.appendChild(sub);

    left.appendChild(text);

    wrap.appendChild(rankEl);
    wrap.appendChild(left);

    grid.appendChild(wrap);

    rank++;
  }

}


export function buildBm365Description_(row) {
  const description = document.createElement(row.description ? 'details' : 'section');
  description.className = `ba2027-album-description${row.description ? '' : ' is-empty'}`;
  const title = document.createElement(row.description ? 'summary' : 'h4');
  const label = document.createElement('span');
  label.textContent = 'Opis i ciekawostki';
  title.appendChild(label);

  if (row.description) {
    const teaser = document.createElement('small');
    teaser.textContent = albumDescriptionTeaser(row.description);
    title.appendChild(teaser);
  }
  description.appendChild(title);

  if (row.description) {
    const body = document.createElement('div');
    renderBrutalAssaultAlbumDescription(body, row.description);
    description.appendChild(body);
    return description;
  }

  const emptyText = document.createElement('p');
  emptyText.textContent = 'Brak opisu. Wygeneruj go i wklej przez edycję albumu na pełnej stronie BM365.';
  const copyPrompt = document.createElement('button');
  copyPrompt.type = 'button';
  copyPrompt.className = 'ba2027-copy-prompt';
  copyPrompt.textContent = 'Kopiuj prompt do AI';
  copyPrompt.addEventListener('click', async () => {
    try {
      await copyBrutalAssaultAlbumPrompt(row);
      copyPrompt.textContent = 'Skopiowano prompt';
    } catch {
      copyPrompt.textContent = 'Nie udało się skopiować';
    }
  });
  description.append(emptyText, copyPrompt);
  return description;
}



async function renderAlreadyDoneState(row, options = {}) {
  const {
    titleText = `Dzisiaj odsłuchane: ${row.artist} — ${row.album}`,
    subText = row.date,
  } = options;
  clearRecent();
  const grid = $("bm365-recent-grid");
  if (!grid) return;

  const cover = await bm_getCoverUrl_(row.artist, row.album);

const wrap = document.createElement("div");
wrap.className = "bm365-row bm365-hero";


  const left = document.createElement("div");
  left.className = "bm365-left";

  const img = document.createElement("img");
  img.className = "bm365-cover";
  img.alt = "";
  img.src = cover || "";
  img.loading = "lazy";
  img.decoding = "async";
  img.onerror = () => {
    img.style.display = "none";
  };

  const text = document.createElement("div");
  text.className = "bm365-text";

  const title = document.createElement("div");
  title.className = "bm365-title";
  title.textContent = titleText;

  const sub = document.createElement("div");
  sub.className = "bm365-sub";
  sub.textContent = subText;

  const spotifyLink = createSpotifySearchLink(row.artist, row.album);
  spotifyLink.classList.add("bm365-spotify-action");
  const youtubeLink = createYoutubeSearchLink(row.artist, row.album);
  youtubeLink.classList.add("bm365-youtube-action");
  const rateYourMusicLink = createRateYourMusicSearchLink(row.artist, row.album);
  rateYourMusicLink.classList.add("bm365-rateyourmusic-action");
  const mediaActions = document.createElement("div");
  mediaActions.className = "media-search-actions bm365-media-actions";
  mediaActions.appendChild(spotifyLink);
  mediaActions.appendChild(youtubeLink);
  mediaActions.appendChild(rateYourMusicLink);

  text.appendChild(title);
  appendCrossListBadge_(text, row);
  appendLastFmAlbumBadge(text, row, LASTFM_STATS);
  text.appendChild(mediaActions);
  text.appendChild(sub);

  left.appendChild(img);
  left.appendChild(text);

  wrap.appendChild(left);
  wrap.appendChild(buildBm365Description_(row));
  grid.appendChild(wrap);

  setText("bm365-recent-count", "(1)");
}

async function renderAlbumOfDayStateLegacy(todayRow, onMark) {
  clearRecent();
  const grid = $("bm365-recent-grid");
  if (!grid) return;

  const cover = await bm_getCoverUrl_(todayRow.artist, todayRow.album);

  const btn = document.createElement("button");
  btn.textContent = "Przesłuchane";
  btn.className = "bm365-btn";
  btn.addEventListener("click", onMark);

  const wrap = document.createElement("div");
  wrap.className = "bm365-row bm365-hero";

  const left = document.createElement("div");
  left.className = "bm365-left";

  const img = document.createElement("img");
  img.className = "bm365-cover";
  img.alt = "";
  img.src = cover || "";
  img.loading = "lazy";
  img.decoding = "async";
  img.onerror = () => {
    img.style.display = "none";
  };

  const text = document.createElement("div");
  text.className = "bm365-text";

  const title = document.createElement("div");
  title.className = "bm365-title";
  title.textContent = `${todayRow.artist} — ${todayRow.album}`;

  const sub = document.createElement("div");
  sub.className = "bm365-sub";
  sub.textContent = `Album dnia • ${todayRow.date}${
    Number.isFinite(todayRow.minutes) ? ` • ${todayRow.minutes}m` : ""
  }`;

  text.appendChild(title);
  appendCrossListBadge_(text, todayRow);
  appendLastFmAlbumBadge(text, todayRow, LASTFM_STATS);
  text.appendChild(sub);

  left.appendChild(img);
  left.appendChild(text);

  wrap.appendChild(left);
  wrap.appendChild(btn);

  grid.appendChild(wrap);
  setText("bm365-recent-count", "(1)");
}

async function renderRateAlbumState(row, options = {}) {
  const {
    titleText = `${row.artist} — ${row.album}`,
    subText = row.date,
    buttonText = Number.isFinite(row.rating) ? "Zmień ocenę" : "Zapisz ocenę",
    refreshSuggestionText = "",
    onRefreshSuggestion = null,
  } = options;

  clearRecent();
  const grid = $("bm365-recent-grid");
  if (!grid) return;

  const cover = await bm_getCoverUrl_(row.artist, row.album);

  const wrap = document.createElement("div");
  wrap.className = "bm365-row bm365-hero";

  const left = document.createElement("div");
  left.className = "bm365-left";

  const img = document.createElement("img");
  img.className = "bm365-cover";
  img.alt = "";
  img.src = cover || "";
  img.loading = "lazy";
  img.decoding = "async";
  img.onerror = () => {
    img.style.display = "none";
  };

  const text = document.createElement("div");
  text.className = "bm365-text";

  const title = document.createElement("div");
  title.className = "bm365-title";
  title.textContent = titleText;

  const sub = document.createElement("div");
  sub.className = "bm365-sub";
  sub.textContent = subText;

  const spotifyLink = createSpotifySearchLink(row.artist, row.album);
  spotifyLink.classList.add("bm365-spotify-action");
  const youtubeLink = createYoutubeSearchLink(row.artist, row.album);
  youtubeLink.classList.add("bm365-youtube-action");
  const rateYourMusicLink = createRateYourMusicSearchLink(row.artist, row.album);
  rateYourMusicLink.classList.add("bm365-rateyourmusic-action");
  const mediaActions = document.createElement("div");
  mediaActions.className = "media-search-actions bm365-media-actions";
  mediaActions.appendChild(spotifyLink);
  mediaActions.appendChild(youtubeLink);
  mediaActions.appendChild(rateYourMusicLink);

  const controls = document.createElement("div");
  controls.className = "bm365-rate-control";

  const select = createRatingSelect(
    row.rating,
    Number.isFinite(row.rating) ? "Ocena" : "Wybierz ocenę"
  );

  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = buttonText;
  btn.className = "bm365-btn";
  btn.disabled = !select.value;

  const refreshBtn = document.createElement("button");
  refreshBtn.type = "button";
  refreshBtn.textContent = refreshSuggestionText || "Odśwież propozycję";
  refreshBtn.className = "bm365-btn bm365-refresh-suggestion";
  refreshBtn.hidden = typeof onRefreshSuggestion !== "function";

  const feedback = document.createElement("div");
  feedback.className = "bm365-rate-feedback";
  feedback.hidden = true;

  const syncButtonState = () => {
    btn.disabled = !select.value;
  };

  select.addEventListener("change", () => {
    feedback.hidden = true;
    feedback.textContent = "";
    syncButtonState();
  });

  btn.addEventListener("click", async () => {
    const rating = toNumber(select.value);
    if (!Number.isFinite(rating)) return;

    btn.disabled = true;
    select.disabled = true;
    feedback.hidden = false;
    feedback.textContent = "Zapisywanie...";
    setFooter("Zapis oceny do arkusza...");

    try {
      await apiRateAlbum({
        date: row.date,
        rowId: row.rowId,
        artist: row.artist,
        album: row.album,
        rating
      });
      feedback.textContent = "Ocena zapisana.";
      await init();
    } catch (error) {
      console.error(error);
      feedback.textContent = "Nie udało się zapisać oceny.";
      select.disabled = false;
      syncButtonState();
      setFooter("Błąd zapisu oceny. Sprawdź lokalny serwer.");
    }
  });

  refreshBtn.addEventListener("click", async () => {
    if (typeof onRefreshSuggestion !== "function") return;

    refreshBtn.disabled = true;
    btn.disabled = true;
    select.disabled = true;
    feedback.hidden = false;
    feedback.textContent = "Losowanie propozycji...";
    setFooter("Losuję inną propozycję...");

    try {
      await onRefreshSuggestion();
    } catch (error) {
      console.error(error);
      feedback.textContent = "Nie udało się odświeżyć propozycji.";
      refreshBtn.disabled = false;
      select.disabled = false;
      syncButtonState();
      setFooter("Błąd odświeżania propozycji.");
    }
  });

  text.appendChild(title);
  appendCrossListBadge_(text, row);
  appendLastFmAlbumBadge(text, row, LASTFM_STATS);
  text.appendChild(mediaActions);
  text.appendChild(sub);

  left.appendChild(img);
  left.appendChild(text);

  controls.appendChild(select);
  controls.appendChild(btn);
  controls.appendChild(refreshBtn);
  controls.appendChild(feedback);

  wrap.appendChild(left);
  wrap.appendChild(buildBm365Description_(row));
  wrap.appendChild(controls);

  grid.appendChild(wrap);
  setText("bm365-recent-count", "(1)");
}

async function renderAlbumOfDayState(todayRow) {
  const parts = ["Album dnia", todayRow.date];
  if (Number.isFinite(todayRow.minutes)) parts.push(`${todayRow.minutes}m`);

  await renderRateAlbumState(todayRow, {
    titleText: `${todayRow.artist} - ${todayRow.album}`,
    subText: parts.join(" | "),
    buttonText: Number.isFinite(todayRow.rating) ? "Zmień ocenę" : "Zapisz ocenę",
  });
}

async function renderRecent(rows) {
  clearRecent();
  const grid = $("bm365-recent-grid");
  if (!grid) return;

  for (const r of rows) {
    const cover = await bm_getCoverUrl_(r.artist, r.album);

    const wrap = document.createElement("div");
    wrap.className = "bm365-row";

    const left = document.createElement("div");
    left.className = "bm365-left";

    const img = document.createElement("img");
    img.className = "bm365-cover";
    img.alt = "";
    img.src = cover || "";
    img.loading = "lazy";
    img.decoding = "async";
    img.onerror = () => {
      img.style.display = "none";
    };

    const text = document.createElement("div");
    text.className = "bm365-text";

    const title = document.createElement("div");
    title.className = "bm365-title";
    title.textContent = `${r.artist} — ${r.album}`;

    const rightParts = [];
    if (Number.isFinite(r.rating)) rightParts.push(`★ ${r.rating}`);
    if (Number.isFinite(r.minutes)) rightParts.push(`${r.minutes}m`);

    const sub = document.createElement("div");
    sub.className = "bm365-sub";
    sub.textContent = `${r.date}${rightParts.length ? ` • ${rightParts.join(" • ")}` : ""}`;

    text.appendChild(title);
    appendCrossListBadge_(text, r);
    appendLastFmAlbumBadge(text, r, LASTFM_STATS);
    text.appendChild(sub);

    left.appendChild(img);
    left.appendChild(text);
    wrap.appendChild(left);

    grid.appendChild(wrap);
  }

  setText("bm365-recent-count", `(${rows.length})`);
}

async function renderNextUp(nextRow) {
  if (!nextRow) {
    setText("bm365-next", "—");
    setText("bm365-next-date", "—");
    return;
  }

  const cover = await bm_getCoverUrl_(nextRow.artist, nextRow.album);

  const nextBox = $("bm365-next-box"); // opcjonalny wrapper; jeśli nie ma, zostaje tekst
  setText("bm365-next", `${nextRow.artist} — ${nextRow.album}`);
  setText("bm365-next-date", nextRow.date);

  // Jeśli masz wrapper w HTML i chcesz mini-okładkę w "Next up", dodaj go w index.html:
  // <div id="bm365-next-box"></div>
  // Jeśli nie masz, nic się nie stanie.
  if (nextBox) {
    nextBox.innerHTML = "";
    const row = document.createElement("div");
    row.className = "bm365-nextRow";

    const img = document.createElement("img");
    img.className = "bm365-cover sm";
    img.alt = "";
    img.src = cover || "";
    img.loading = "lazy";
    img.decoding = "async";
    img.onerror = () => {
      img.style.display = "none";
    };

    const text = document.createElement("div");
    text.className = "bm365-text";

    const t = document.createElement("div");
    t.className = "bm365-title";
    t.textContent = `${nextRow.artist} — ${nextRow.album}`;

    const s = document.createElement("div");
    s.className = "bm365-sub";
    s.textContent = nextRow.date;

    text.appendChild(t);
    appendLastFmAlbumBadge(text, nextRow, LASTFM_STATS);
    text.appendChild(s);

    row.appendChild(img);
    row.appendChild(text);

    nextBox.appendChild(row);
  }
}

async function init() {
  if (!$("bm365-card")) return;

  const today = todayISO();
  const stopTimer = startLoadTimer();
  setFooter("Ładowanie…");

  try {
    const raw = await apiGetAll();
    const rows = normalizeRows(raw);
    LASTFM_STATS = await fetchLastFmAlbumStats(rows);
    bm_renderMissingList_(bm_loadMissingList_());
    schedulePrefetch(rows);
    updateBm365GoalState(rows, today);

    const stats = computeStats(rows);

    // KPI
    setText("bm365-done", String(stats.done));
    setText("bm365-left", String(stats.left));
    setText("bm365-pct", `${stats.pct}%`);
    updateBm365Progress_(stats.done, stats.total);
    setText("bm365-progress-text", `${stats.done} / ${stats.total} - ${stats.pct}%`);
    renderCatchUpInfo(rows, today);
    renderRemainingProjection(rows, today);

    // Avg rating / total time
    setText("bm365-avg", stats.avgRating === null ? "—" : stats.avgRating.toFixed(2));
    setText("bm365-avg-note", stats.ratedCount ? `${stats.ratedCount} ocen` : "brak ocen");

    setText("bm365-time", stats.timeCount ? formatMinutes(stats.totalMinutes) : "—");
    setText("bm365-time-note", stats.timeCount ? `${stats.timeCount} wpisów` : "brak czasu");

    const albumToday = findAlbumOfDay(rows, today);
    const albumCover = albumToday ? await bm_getCoverUrl_(albumToday.artist, albumToday.album) : "";
    if (isBm365FinaleReady(stats)) {
      setDailyAchievement("album", {
        state: "complete",
        value: albumToday?.album || "BM365",
        coverUrl: albumCover,
        detail: albumToday
          ? [
            albumToday.artist,
            Number.isFinite(albumToday.rating) ? `★ ${formatRatingValue(albumToday.rating)}` : "",
          ].filter(Boolean).join(" · ")
          : "365 / 365",
      });
      const card = $("bm365-card");
      const catchUpEl = $("bm365-catchup");
      const projectionEl = $("bm365-projection");
      card?.classList.add("is-finale-complete");
      if (catchUpEl) {
        catchUpEl.hidden = true;
        catchUpEl.textContent = "";
      }
      if (projectionEl) {
        projectionEl.hidden = true;
        projectionEl.textContent = "";
      }
      setText("bm365-next", "Podsumowanie");
      setText("bm365-next-date", "365 / 365");
      await renderBm365FinaleWidget($("bm365-recent-grid"), rows, {
        resolveCover: (row) => bm_getCoverUrl_(row.artist, row.album),
      });
      setText("bm365-recent-count", "");
      setFooterWithLoad("BM365 complete.", stopTimer());
      return;
    }

    clearBm365FinaleWidgetState();

    // Next up
    const next = findNextUp(rows, today);
    await renderNextUp(next);

    // Album dnia
    if (!albumToday) {
      setDailyAchievement("album", {
        state: "neutral",
        value: "Brak albumu",
        detail: "Brak pozycji BM365 na dziś",
        eligible: false,
      });
      await renderRecent(recentListened(rows));
      setFooterWithLoad(`Brak wiersza na dzisiaj (${today}).`, stopTimer());
      return;
    }

    setDailyAchievement("album", {
      state: albumToday.listened ? "complete" : "pending",
      value: albumToday.album || "—",
      coverUrl: albumCover,
      detail: [
        albumToday.artist,
        Number.isFinite(albumToday.rating) ? `★ ${formatRatingValue(albumToday.rating)}` : "",
      ].filter(Boolean).join(" · "),
    });

    if (albumToday.listened) {
      const overdue = findFirstOverdue(rows, today);
      if (overdue) {
        const overdueParts = ["Najstarsza zaległość", overdue.date];
        if (Number.isFinite(overdue.minutes)) overdueParts.push(`${overdue.minutes}m`);
        await renderRateAlbumState(overdue, {
          titleText: `Zaległy album: ${overdue.artist} — ${overdue.album}`,
          subText: overdueParts.join(" • "),
        });
        setFooterWithLoad(`Pokazuję zaległość (${overdue.date}).`, stopTimer());
        return;
      }

      const randomPick = findStableRandomSuggestion(rows);
      if (randomPick) {
        const randomParts = ["Losowa propozycja", randomPick.date];
        if (Number.isFinite(randomPick.minutes)) randomParts.push(`${randomPick.minutes}m`);
        await renderRateAlbumState(randomPick, {
          titleText: `Propozycja: ${randomPick.artist} — ${randomPick.album}`,
          subText: randomParts.join(" • "),
          refreshSuggestionText: "Odśwież propozycję",
          onRefreshSuggestion: hasAlternativeRandomSuggestion(rows, randomPick)
            ? async () => {
                refreshRandomSuggestion(rows, randomPick);
                await init();
              }
            : null,
        });
        setFooterWithLoad("Pokazuję losową propozycję.", stopTimer());
        return;
      }

      if (!Number.isFinite(albumToday.rating)) {
        const albumTodayParts = ["Uzupełnij ocenę", albumToday.date];
        if (Number.isFinite(albumToday.minutes)) albumTodayParts.push(`${albumToday.minutes}m`);
        await renderRateAlbumState(albumToday, {
          titleText: `Uzupełnij ocenę: ${albumToday.artist} - ${albumToday.album}`,
          subText: albumTodayParts.join(" | "),
          buttonText: "Zapisz ocenę",
        });
        setFooterWithLoad("Album dnia jest przesłuchany, ale czeka na ocenę.", stopTimer());
        return;
      }

      await renderAlreadyDoneState(albumToday);
      window.setTimeout(() => setFooterWithLoad(`Dzisiaj już odklikane (${today}).`, stopTimer()), 0);
      setFooter(`Dzisiaj już odklikane (${today}).`);
      return;
    }

    await renderAlbumOfDayState(albumToday, async () => {
      try {
        setFooter("Zapis lokalny…");
        await apiMarkListened({ date: albumToday.date, rowId: albumToday.rowId });
        await init(); // refresh
      } catch (e) {
        console.error(e);
        setFooter("Błąd zapisu. Sprawdź lokalny serwer.");
      }
    });

    setFooterWithLoad(`Aktualizacja: ${fmtDateTimeShort(new Date())}`, stopTimer());
  } catch (e) {
    console.error(e);
    setDailyAchievement("album", {
      state: "error",
      value: "Brak danych",
      detail: "Nie udało się pobrać BM365",
      eligible: false,
    });
    clearBm365GoalState();
    const catchUpEl = $("bm365-catchup");
    if (catchUpEl) {
      catchUpEl.hidden = true;
      catchUpEl.textContent = "";
    }
    const projectionEl = $("bm365-projection");
    if (projectionEl) {
      projectionEl.hidden = true;
      projectionEl.textContent = "";
    }
    setFooter("Nie udało się pobrać danych. Uruchom lokalny serwer Python.");
  }
}

init();

