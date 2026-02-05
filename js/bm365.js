// js/bm365.js
// Black Metal 365 - widget (album dnia + odklikanie do Google Sheets przez Apps Script Web App)
// + auto-okładki z iTunes (cache w localStorage)

const CONFIG = {
  // Przykład: https://script.google.com/macros/s/AKfycb.../exec
  API_BASE:
    "https://script.google.com/macros/s/AKfycbwr8vEWMrcNubg7qu6a5CFCnRINV5M992ZGCsWbZuJpB3kqlKIyErlfH77wgA4xZu1Y/exec",

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
  if (x === null || x === undefined || x === "") return null;
  const n = Number(String(x).replace(",", "."));
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
  if (el) el.textContent = msg || "";
}

function clearRecent() {
  const grid = $("bm365-recent-grid");
  if (grid) grid.innerHTML = "";
}

// ---------- covers (iTunes) ----------
const BM_COVER_CACHE_KEY = "bm365_cover_cache_v1";
const BM_COVER_CACHE_TTL_DAYS = 30;

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
function bm_isFresh_(ts) {
  if (!ts) return false;
  const ageMs = Date.now() - ts;
  return ageMs < BM_COVER_CACHE_TTL_DAYS * 24 * 60 * 60 * 1000;
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
async function bm_getCoverUrl_(artist, album) {
  const key = bm_cacheKey_(artist, album);
  if (!key || key === " — ") return "";

  const cache = bm_loadCoverCache_();
  const hit = cache[key];
  if (hit && bm_isFresh_(hit.ts) && hit.url) return hit.url;

  try {
    const url = await bm_fetchCoverItunes_(artist, album);
    cache[key] = { url: url || "", ts: Date.now() };
    bm_saveCoverCache_(cache);
    return url || "";
  } catch {
    cache[key] = { url: "", ts: Date.now() };
    bm_saveCoverCache_(cache);
    return "";
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
    const stats = computeStats(rows);

    // KPI
    setText("bm365-done", String(stats.done));
    setText("bm365-left", String(stats.left));
    setText("bm365-pct", `${stats.pct}%`);

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

    setFooter(`Aktualizacja: ${new Date().toLocaleString("pl-PL")}`);
  } catch (e) {
    console.error(e);
    setFooter("Nie udało się pobrać danych. Sprawdź URL Apps Script i dostęp.");
  }
}

init();
