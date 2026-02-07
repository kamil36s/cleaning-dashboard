// js/bm365.js
import { fmtDateTimeShort } from './utils.js';
// Black Metal 365 - widget (album dnia + odklikanie do Google Sheets przez Apps Script Web App)
// + auto-okładki z iTunes (cache w localStorage)

const CONFIG = {
  // Przykład: https://script.google.com/macros/s/AKfycb.../exec
  API_BASE:
    "https://script.google.com/macros/s/AKfycbwinBwL3N0BPJ1H5wx4Q0MxP7JzXJ4y2M5lNoEsy81jL6I-p-GQJbplyFmQMEDW6Sgq/exec",

  // Nazwy pól w JSON (dopasowanie do Apps Script)
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
  if (el.hasAttribute("data-fixed")) return;
  el.textContent = msg || "";
}

function clearRecent() {
  const grid = $("bm365-recent-grid");
  if (grid) grid.innerHTML = "";
}

// ---------- covers (iTunes) ----------
const BM_COVER_CACHE_KEY = "bm365_cover_cache_v1";
const BM_COVER_CACHE_TTL_DAYS = 30;
const BM_COVER_MISS_TTL_DAYS = 7;
const BM_PREFETCH_TTL_DAYS = 14;
const BM_PREFETCH_TS_KEY = "bm365_prefetch_ts_v1";
const BM_PREFETCH_RUNNING_KEY = "bm365_prefetch_running_v1";
const BM_MISSING_KEY = "bm365_missing_covers_v1";

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
  if (!key || key === " — ") return "";

  const cache = bm_loadCoverCache_();
  const hit = cache[key];
  if (hit && hit.url && bm_isFresh_(hit.ts, BM_COVER_CACHE_TTL_DAYS)) return hit.url;

  if (!hit || hit.miss || !hit.url) {
    const local = await bm_tryLocalCover_(artist, album);
    if (local) {
      cache[key] = { url: local, ts: Date.now(), local: true };
      bm_saveCoverCache_(cache);
      return local;
    }
  }

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
  const url = `${CONFIG.API_BASE}?action=bm365_get`;
  const res = await fetch(url, { method: "GET" });
  if (!res.ok) throw new Error(`GET failed: ${res.status}`);
  return res.json();
}

async function apiMarkListened({ date, rowId }) {
  // Apps Script GET-only: ?action=bm365_mark&date=... albo &rowId=...
  const url = rowId
    ? `${CONFIG.API_BASE}?action=bm365_mark&rowId=${encodeURIComponent(String(rowId))}`
    : `${CONFIG.API_BASE}?action=bm365_mark&date=${encodeURIComponent(String(date))}`;

  const res = await fetch(url, { method: "GET" });
  if (!res.ok) throw new Error(`MARK failed: ${res.status}`);
  return res.json();
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
        rowId: r[f.rowId] ?? null,
      };
    })
    .filter((r) => r.date);
}

function computeStats(rows) {
  const total = rows.length;
  const done = rows.filter((r) => r.listened).length;
  const left = Math.max(0, total - done);

  const rated = rows.filter((r) => r.listened && Number.isFinite(r.rating));
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

function findAlbumOfDay(rows, today) {
  return rows.find((r) => r.date === today) || null;
}

function findNextUp(rows, today) {
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  const future = sorted.find((r) => !r.listened && r.date >= today);
  if (future) return future;
  return sorted.find((r) => !r.listened) || null;
}

function recentListened(rows) {
  return rows
    .filter((r) => r.listened)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, CONFIG.RECENT_LIMIT);
}

function topRated(rows, limit = 10) {
  return rows
    .filter((r) => r.listened && Number.isFinite(r.rating))
    .sort((a, b) => {
if (b.rating !== a.rating) return b.rating - a.rating;
return String(b.date).localeCompare(String(a.date));
    })
    .slice(0, limit);
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
    text.appendChild(sub);

    left.appendChild(text);

    wrap.appendChild(rankEl);
    wrap.appendChild(left);

    grid.appendChild(wrap);

    rank++;
    if (rank > 10) break;
  }

}



async function renderAlreadyDoneState(todayRow) {
  clearRecent();
  const grid = $("bm365-recent-grid");
  if (!grid) return;

  const cover = await bm_getCoverUrl_(todayRow.artist, todayRow.album);

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
  title.textContent = `Dzisiaj odsłuchane: ${todayRow.artist} — ${todayRow.album}`;

  const sub = document.createElement("div");
  sub.className = "bm365-sub";
  sub.textContent = todayRow.date;

  text.appendChild(title);
  text.appendChild(sub);

  left.appendChild(img);
  left.appendChild(text);

  wrap.appendChild(left);
  grid.appendChild(wrap);

  setText("bm365-recent-count", "(1)");
}

async function renderAlbumOfDayState(todayRow, onMark) {
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
  text.appendChild(sub);

  left.appendChild(img);
  left.appendChild(text);

  wrap.appendChild(left);
  wrap.appendChild(btn);

  grid.appendChild(wrap);
  setText("bm365-recent-count", "(1)");
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
    text.appendChild(s);

    row.appendChild(img);
    row.appendChild(text);

    nextBox.appendChild(row);
  }
}

async function init() {
  if (!$("bm365-card")) return;

  const today = todayISO();
  setFooter("Ładowanie…");

  try {
    const raw = await apiGetAll();
    const rows = normalizeRows(raw);
    bm_renderMissingList_(bm_loadMissingList_());
    schedulePrefetch(rows);
    const top = topRated(rows, 10);
    await renderTopRated(top);

    const stats = computeStats(rows);

    // KPI
    setText("bm365-done", String(stats.done));
    setText("bm365-left", String(stats.left));
    setText("bm365-pct", `${stats.pct}%`);
    const prog = $("bm365-progress-bar");
    if (prog) prog.style.width = `${stats.pct}%`;
    setText("bm365-progress-text", `${stats.done} / ${stats.total} - ${stats.pct}%`);

    // Avg rating / total time
    setText("bm365-avg", stats.avgRating === null ? "—" : stats.avgRating.toFixed(2));
    setText("bm365-avg-note", stats.ratedCount ? `${stats.ratedCount} ocen` : "brak ocen");

    setText("bm365-time", stats.timeCount ? formatMinutes(stats.totalMinutes) : "—");
    setText("bm365-time-note", stats.timeCount ? `${stats.timeCount} wpisów` : "brak czasu");

    // Next up
    const next = findNextUp(rows, today);
    await renderNextUp(next);

    // Album dnia
    const albumToday = findAlbumOfDay(rows, today);
    if (!albumToday) {
      await renderRecent(recentListened(rows));
      setFooter(`Brak wiersza na dzisiaj (${today}).`);
      return;
    }

    if (albumToday.listened) {
      await renderAlreadyDoneState(albumToday);
      setFooter(`Dzisiaj już odklikane (${today}).`);
      return;
    }

    await renderAlbumOfDayState(albumToday, async () => {
      try {
        setFooter("Zapis do arkusza…");
        await apiMarkListened({ date: albumToday.date, rowId: albumToday.rowId });
        await init(); // refresh
      } catch (e) {
        console.error(e);
        setFooter("Błąd zapisu. Sprawdź Apps Script / dostęp.");
      }
    });

    setFooter(`Aktualizacja: ${fmtDateTimeShort()}`);
  } catch (e) {
    console.error(e);
    setFooter("Nie udało się pobrać danych. Sprawdź URL Apps Script i dostęp.");
  }
}

init();

