import { fmtDateTimeShort } from './utils.js';
import { addDashboardNotification } from './dashboard-notifications-store.js';
import { createAlbumStarRating } from './album-star-rating.js';
import { appendLastFmAlbumBadge, fetchLastFmAlbumStats } from './lastfm-stats.js';
import {
  createRateYourMusicSearchLink,
  createSpotifySearchLink,
  createYoutubeSearchLink,
} from './spotify-link.js';
import {
  buildBrutalAssaultRecommendationQueue,
  albumDescriptionTeaser,
  copyBrutalAssaultAlbumPrompt,
  communityRatingLabel,
  computeBrutalAssaultDeadlineStats,
  isUnheardArtist,
  renderBrutalAssaultAlbumDescription,
  renderBrutalAssaultDeadlineSummary,
} from './brutal-assault-recommendations.js';

const API_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  && window.location.port !== '8000'
  ? 'http://127.0.0.1:8000'
  : '';
const ALBUMS_API = `${API_BASE}/api/brutal-assault-2027/albums`;
const UPDATE_API = `${ALBUMS_API}/update`;
const COVERS_API = `${API_BASE}/api/brutal-assault-2027/covers`;
const OFFICIAL_API = `${API_BASE}/api/brutal-assault-2027/official`;
const DELIVERED_KEY = 'brutal_assault_2027_monitor_delivered_v1';
const COVER_CACHE_KEY = 'brutal_assault_2027_widget_covers_v1';
let refreshTimer = null;

const $ = (id) => document.getElementById(id);

export function deliverOfficialNotifications(events) {
  let delivered;
  try {
    delivered = new Set(JSON.parse(localStorage.getItem(DELIVERED_KEY) || '[]'));
  } catch {
    delivered = new Set();
  }
  let changed = false;
  [...events].reverse().forEach((event) => {
    if (!event?.id || delivered.has(event.id)) return;
    if (event.type === 'lineup_change' && event.addedBands?.length) {
      const names = event.addedBands.map((band) => band.name);
      addDashboardNotification({
        id: event.id,
        category: 'Brutal Assault 2027',
        title: names.length === 1
          ? `Brutal Assault 2027: new band announced — ${names[0]}`
          : `Brutal Assault 2027: ${names.length} new bands announced`,
        message: names.join(', '),
        targetId: 'ba2027-card',
        createdAt: event.detectedAt,
      });
    } else if (event.type === 'news') {
      addDashboardNotification({
        id: event.id,
        category: 'Brutal Assault',
        title: `Brutal Assault: New news — ${event.title}`,
        message: event.url,
        targetId: 'ba2027-card',
        createdAt: event.detectedAt,
      });
    }
    delivered.add(event.id);
    changed = true;
  });
  if (changed) {
    try { localStorage.setItem(DELIVERED_KEY, JSON.stringify([...delivered].slice(-300))); } catch {}
  }
}

function renderOfficial(payload) {
  const count = payload?.announcedCount;
  const percent = payload?.confirmedPercent;
  if (Number.isFinite(count) && Number.isFinite(percent)) {
    setText('ba2027-official-summary', `${count} potwierdzonych zespołów · ${percent}% line-upu`);
    $('ba2027-official-bar').style.width = `${percent}%`;
    $('ba2027-official-bar').parentElement.setAttribute('aria-valuenow', String(percent));
  }
  const added = payload?.newBands || [];
  const update = $('ba2027-official-update');
  update.hidden = !added.length;
  if (added.length) update.textContent = `NEW · ${added.map((band) => band.name).join(', ')}`;
  const checked = payload?.lastSuccessfulCheckAt
    ? `Ostatnio sprawdzono: ${fmtDateTimeShort(new Date(payload.lastSuccessfulCheckAt))}`
    : 'Oczekiwanie na pierwsze sprawdzenie';
  setText('ba2027-foot', payload?.lastError ? `Nie udało się sprawdzić strony · ${checked}` : checked);
  const list = $('ba2027-official-news');
  list.replaceChildren();
  (payload?.latestNews || []).slice(0, 3).forEach((article) => {
    const link = document.createElement('a');
    link.href = article.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    const date = document.createElement('time');
    date.textContent = article.date;
    const title = document.createElement('span');
    title.textContent = article.title;
    link.append(date, title);
    list.appendChild(link);
  });
  deliverOfficialNotifications(payload?.events || []);
}

async function loadOfficial(checkNow = false) {
  const button = $('ba2027-check-now');
  if (!button) return;
  if (checkNow) {
    button.disabled = true;
    setText('ba2027-foot', 'Sprawdzanie…');
  }
  try {
    const response = await fetch(checkNow ? `${OFFICIAL_API}/check` : OFFICIAL_API,
      checkNow ? { method: 'POST' } : { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    renderOfficial(payload);
  } catch (error) {
    console.error(error);
    setText('ba2027-foot', 'Nie udało się pobrać stanu monitora');
  } finally {
    button.disabled = false;
  }
}

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(String(value).replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeRows(payload) {
  const rows = Array.isArray(payload) ? payload : payload?.rows || [];
  return rows.map((row) => {
    const rating = toNumber(row?.rating);
    const listenedValue = row?.listened;
    const listened = listenedValue === true || listenedValue === 1
      || ['TAK', 'TRUE', 'YES', '1'].includes(String(listenedValue || '').trim().toUpperCase());
    return {
      rowId: row?.rowId ?? row?.id ?? null,
      date: String(row?.date || ''),
      artist: String(row?.artist || '').trim(),
      album: String(row?.album || '').trim(),
      year: String(row?.year || '').trim(),
      listened: listened || Number.isFinite(rating),
      rating,
      minutes: toNumber(row?.minutes),
      rymRating: toNumber(row?.rymRating),
      communityRating: toNumber(row?.communityRating),
      communityVotes: toNumber(row?.communityVotes) || 0,
      communitySource: String(row?.communitySource || ''),
      communityUrl: String(row?.communityUrl || ''),
      description: String(row?.description || '').trim(),
      crossList: row?.crossList && typeof row.crossList === 'object' ? { ...row.crossList } : null,
    };
  }).filter((row) => row.artist || row.album);
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function formatMinutes(totalMinutes) {
  if (!Number.isFinite(totalMinutes) || totalMinutes <= 0) return '—';
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function formatRating(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
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

function localCoverCandidates(row) {
  const slug = [slugify(row.artist), slugify(row.album)].filter(Boolean).join('--') || 'unknown';
  return ['jpg', 'jpeg', 'png', 'webp'].map((extension) => `./covers/${slug}.${extension}`);
}

function firstAvailableImage(urls) {
  return new Promise((resolve) => {
    const tryNext = (index) => {
      if (index >= urls.length) {
        resolve('');
        return;
      }
      const image = new Image();
      image.onload = () => resolve(urls[index]);
      image.onerror = () => tryNext(index + 1);
      image.src = urls[index];
    };
    tryNext(0);
  });
}

function loadCoverCache() {
  try {
    const value = JSON.parse(localStorage.getItem(COVER_CACHE_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

function saveCoverCache(cache) {
  try {
    localStorage.setItem(COVER_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Cover cache is optional.
  }
}

async function resolveCover(row) {
  const local = await firstAvailableImage(localCoverCandidates(row));
  if (local) return local;

  const key = `${row.artist} — ${row.album}`.toLowerCase();
  const cache = loadCoverCache();
  if (cache[key]?.url) return cache[key].url;

  try {
    const query = new URLSearchParams({
      term: `${row.artist} ${row.album}`,
      entity: 'album',
      limit: '1',
    });
    const response = await fetch(`https://itunes.apple.com/search?${query}`);
    const payload = await response.json();
    const rawUrl = payload?.results?.[0]?.artworkUrl100 || '';
    const url = rawUrl.replace(/\/(\d+)x(\d+)bb\.(jpg|png)/, '/600x600bb.$3');
    if (url) {
      cache[key] = { url, ts: Date.now() };
      saveCoverCache(cache);
    }
    if (url) return url;
  } catch {
    // Try MusicBrainz through the local API below.
  }

  try {
    const response = await fetch(COVERS_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artist: row.artist, album: row.album }),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.url) return '';
    const url = `${payload.url}${payload.url.includes('?') ? '&' : '?'}t=${Date.now()}`;
    cache[key] = { url, ts: Date.now() };
    saveCoverCache(cache);
    return url;
  } catch {
    return '';
  }
}

function computeStats(rows) {
  const doneRows = rows.filter((row) => row.listened);
  const ratedRows = rows.filter((row) => Number.isFinite(row.rating));
  const timeRows = rows.filter((row) => Number.isFinite(row.minutes));
  return {
    total: rows.length,
    done: doneRows.length,
    left: Math.max(0, rows.length - doneRows.length),
    pct: rows.length ? Math.round((doneRows.length / rows.length) * 100) : 0,
    avg: ratedRows.length
      ? ratedRows.reduce((sum, row) => sum + row.rating, 0) / ratedRows.length
      : null,
    ratedCount: ratedRows.length,
    totalMinutes: timeRows.reduce((sum, row) => sum + row.minutes, 0),
    timeCount: timeRows.length,
  };
}

function chooseNext(rows) {
  return buildBrutalAssaultRecommendationQueue(rows)[0] || null;
}

function createRatingSelect(row) {
  return createAlbumStarRating(row.rating, {
    ariaLabel: `Ocena albumu ${row.artist} — ${row.album}`,
  });
}

async function updateRating(row, rating) {
  const response = await fetch(UPDATE_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: row.rowId, rating }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload;
}

async function renderFeatured(row, rows = [], lastFmStats = new Map()) {
  const grid = $('ba2027-recent-grid');
  if (!grid) return;
  grid.innerHTML = '';
  grid.classList.remove('skeleton-block', 'skeleton-lg');

  if (!row) {
    const empty = document.createElement('div');
    empty.className = 'bm365-row bm365-hero';
    const copy = document.createElement('div');
    copy.className = 'bm365-text';
    const title = document.createElement('div');
    title.className = 'bm365-title';
    title.textContent = rows.length ? 'Wszystko przesłuchane' : 'Lista jest pusta';
    const sub = document.createElement('div');
    sub.className = 'bm365-sub';
    sub.textContent = rows.length
      ? 'Nie ma już albumów oczekujących na odsłuch.'
      : 'Dodaj pierwszy album ręcznie na stronie Brutal Assault 2027.';
    copy.append(title, sub);
    empty.appendChild(copy);
    grid.appendChild(empty);
    return;
  }

  const wrap = document.createElement('div');
  wrap.className = 'bm365-row bm365-hero';
  const left = document.createElement('div');
  left.className = 'bm365-left';
  const image = document.createElement('img');
  image.className = 'bm365-cover';
  image.alt = '';
  image.loading = 'lazy';
  image.decoding = 'async';
  image.hidden = true;
  const cover = await resolveCover(row);
  if (cover) {
    image.src = cover;
    image.hidden = false;
    image.onerror = () => { image.hidden = true; };
  }

  const copy = document.createElement('div');
  copy.className = 'bm365-text';
  const title = document.createElement('div');
  title.className = 'bm365-title';
  title.textContent = `${row.artist} — ${row.album}`;
  const sub = document.createElement('div');
  sub.className = 'bm365-sub';
  const externalRating = communityRatingLabel(row);
  sub.textContent = [
    isUnheardArtist(row, rows) ? 'Nowy artysta' : 'Kolejny album artysty',
    externalRating || 'Ocena RYM / MusicBrainz jeszcze niedostępna',
    row.year,
    Number.isFinite(row.minutes) ? `${row.minutes}m` : ''
  ].filter(Boolean).join(' • ');
  const media = document.createElement('div');
  media.className = 'media-search-actions bm365-media-actions';
  media.append(
    createSpotifySearchLink(row.artist, row.album),
    createYoutubeSearchLink(row.artist, row.album),
    createRateYourMusicSearchLink(row.artist, row.album),
  );
  copy.appendChild(title);
  appendLastFmAlbumBadge(copy, row, lastFmStats);
  if (row.crossList) {
    const tags = document.createElement('div');
    tags.className = 'bm365-tags';
    const badge = document.createElement('span');
    badge.className = 'bm365-tag is-cross-list';
    badge.title = `Ten album jest również na liście ${row.crossList.label || 'Black Metal 365'}`;
    badge.textContent = `◆ ${row.crossList.label || 'Black Metal 365'}`;
    tags.appendChild(badge);
    copy.appendChild(tags);
  }
  copy.append(media, sub);
  left.append(image, copy);

  const controls = document.createElement('div');
  controls.className = 'bm365-rate-control';
  const select = createRatingSelect(row);
  const save = document.createElement('button');
  save.className = 'bm365-btn';
  save.type = 'button';
  save.textContent = 'Zapisz ocenę';
  save.disabled = !select.value;
  const feedback = document.createElement('div');
  feedback.className = 'bm365-rate-feedback';
  feedback.hidden = true;
  select.addEventListener('change', () => { save.disabled = !select.value; });
  save.addEventListener('click', async () => {
    const rating = toNumber(select.value);
    if (!Number.isFinite(rating)) return;
    save.disabled = true;
    select.disabled = true;
    feedback.hidden = false;
    feedback.textContent = 'Zapisywanie...';
    try {
      await updateRating(row, rating);
      await init();
    } catch (error) {
      console.error(error);
      feedback.textContent = 'Nie udało się zapisać oceny.';
      select.disabled = false;
      save.disabled = false;
    }
  });
  controls.append(select, save, feedback);

  const description = document.createElement(row.description ? 'details' : 'section');
  description.className = `ba2027-album-description${row.description ? '' : ' is-empty'}`;
  const descriptionTitle = document.createElement(row.description ? 'summary' : 'h4');
  const descriptionLabel = document.createElement('span');
  descriptionLabel.textContent = 'Opis i ciekawostki';
  descriptionTitle.appendChild(descriptionLabel);
  if (row.description) {
    const teaser = document.createElement('small');
    teaser.textContent = albumDescriptionTeaser(row.description);
    descriptionTitle.appendChild(teaser);
  }
  description.appendChild(descriptionTitle);
  if (row.description) {
    const body = document.createElement('div');
    renderBrutalAssaultAlbumDescription(body, row.description);
    description.appendChild(body);
  } else {
    const emptyText = document.createElement('p');
    emptyText.textContent = 'Brak opisu. Skopiuj gotowy prompt, wygeneruj tekst i wklej go przez edycję albumu na pełnej stronie.';
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
  }

  wrap.append(left, description, controls);
  grid.appendChild(wrap);
}

async function render(payload) {
  const rows = normalizeRows(payload);
  const stats = computeStats(rows);
  const deadline = computeBrutalAssaultDeadlineStats(rows);
  const next = chooseNext(rows);
  const lastFmStats = await fetchLastFmAlbumStats(next ? [next] : []);
  setText('ba2027-done', String(stats.done));
  setText('ba2027-left', String(stats.left));
  setText('ba2027-pct', `${stats.pct}%`);
  setText('ba2027-progress-text', `${stats.done} / ${stats.total} — ${stats.pct}%`);
  setText('ba2027-avg', stats.avg === null ? '—' : stats.avg.toFixed(2));
  setText('ba2027-avg-note', stats.ratedCount ? `${stats.ratedCount} ocen` : 'brak ocen');
  setText('ba2027-time', formatMinutes(deadline.remainingMinutes));
  const progress = $('ba2027-progress-bar');
  if (progress) progress.style.width = `${stats.pct}%`;
  const projection = $('ba2027-projection');
  if (projection) {
    projection.hidden = stats.total === 0;
    if (stats.total) renderBrutalAssaultDeadlineSummary(projection, deadline);
  }
  await renderFeatured(next, rows, lastFmStats);
  const pending = Number(payload?.communityRatingsPending || 0);
  setText('ba2027-sub', 'Progress odsłuchu albumów');

  if (refreshTimer) clearTimeout(refreshTimer);
  if (pending > 0) refreshTimer = setTimeout(init, 15000);
}

async function init() {
  if (!$('ba2027-card')) return;
  try {
    const response = await fetch(ALBUMS_API, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    await render(payload);
  } catch (error) {
    console.error(error);
    setText('ba2027-sub', 'Nie udało się połączyć z lokalną bazą albumów');
    await renderFeatured(null, []);
  }
}

init();
$('ba2027-check-now')?.addEventListener('click', () => loadOfficial(true));
loadOfficial();
setInterval(() => { if ($('ba2027-card')) loadOfficial(); }, 5 * 60 * 1000);
