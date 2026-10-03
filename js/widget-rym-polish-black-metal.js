import { createAlbumStarRating } from './album-star-rating.js';
import { appendLastFmAlbumBadge, fetchLastFmAlbumStats } from './lastfm-stats.js';
import {
  albumDescriptionTeaser,
  communityRatingLabel,
  copyRymPolishBlackMetalAlbumPrompt,
  renderBrutalAssaultAlbumDescription,
} from './brutal-assault-recommendations.js';
import {
  createRateYourMusicSearchLink,
  createSpotifySearchLink,
  createYoutubeSearchLink,
} from './spotify-link.js';
import { fmtDateTimeShort } from './utils.js';

const API_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  && window.location.port !== '8000'
  ? 'http://127.0.0.1:8000'
  : '';
const ALBUMS_API = `${API_BASE}/api/rym-polish-black-metal/albums`;
const UPDATE_API = `${ALBUMS_API}/update`;
const $ = (id) => document.getElementById(id);

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(String(value).replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : null;
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

function normalizeRows(payload) {
  const rows = Array.isArray(payload) ? payload : payload?.rows || [];
  return rows.map((row) => {
    const rating = toNumber(row?.rating);
    const listened = row?.listened === true || row?.listened === 1
      || ['TAK', 'TRUE', 'YES', '1'].includes(String(row?.listened || '').trim().toUpperCase());
    return {
      rowId: row?.rowId ?? null,
      sourceRank: toNumber(row?.sourceRank),
      artist: String(row?.artist || '').trim(),
      album: String(row?.album || '').trim(),
      year: String(row?.year || '').trim(),
      listened: listened || Number.isFinite(rating),
      rating,
      communityRating: toNumber(row?.communityRating),
      communityVotes: toNumber(row?.communityVotes) || 0,
      communitySource: String(row?.communitySource || ''),
      communityUrl: String(row?.communityUrl || ''),
      description: String(row?.description || '').trim(),
      crossLists: Array.isArray(row?.crossLists)
        ? row.crossLists.filter(Boolean)
        : (row?.crossList ? [row.crossList] : []),
    };
  }).filter((row) => row.artist || row.album);
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function localCoverCandidates(row) {
  const slug = [slugify(row.artist), slugify(row.album)].filter(Boolean).join('--') || 'unknown';
  return ['jpg', 'jpeg', 'png', 'webp'].map((extension) => `./covers/${slug}.${extension}`);
}

function firstAvailableImage(urls) {
  return new Promise((resolve) => {
    const tryNext = (index) => {
      if (index >= urls.length) return resolve('');
      const image = new Image();
      image.onload = () => resolve(urls[index]);
      image.onerror = () => tryNext(index + 1);
      image.src = urls[index];
    };
    tryNext(0);
  });
}

async function resolveCover(row) {
  const local = await firstAvailableImage(localCoverCandidates(row));
  if (local) return local;
  try {
    const query = new URLSearchParams({
      term: `${row.artist} ${row.album}`,
      entity: 'album',
      limit: '1',
    });
    const response = await fetch(`https://itunes.apple.com/search?${query}`);
    const payload = await response.json();
    return String(payload?.results?.[0]?.artworkUrl100 || '')
      .replace(/\/(\d+)x(\d+)bb\.(jpg|png)/, '/600x600bb.$3');
  } catch {
    return '';
  }
}

function createCrossListTags(row) {
  const tags = document.createElement('div');
  tags.className = 'bm365-tags';
  row.crossLists.forEach((crossList) => {
    const badge = document.createElement('span');
    badge.className = 'bm365-tag is-cross-list';
    badge.title = `Ten album jest również na liście ${crossList.label}`;
    badge.textContent = `◆ ${crossList.label}`;
    tags.appendChild(badge);
  });
  return tags;
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

async function renderNext(row, rows, lastFmStats = new Map()) {
  const grid = $('rym-polish-bm-recent-grid');
  if (!grid) return;
  grid.innerHTML = '';
  grid.classList.remove('skeleton-block', 'skeleton-lg');

  if (!row) {
    const empty = document.createElement('div');
    empty.className = 'bm365-row bm365-hero';
    empty.textContent = rows.length ? 'Wszystkie 100 albumów przesłuchane.' : 'Lista jest pusta.';
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
  const meta = document.createElement('div');
  meta.className = 'bm365-sub';
  meta.textContent = [
    Number.isFinite(row.sourceRank) ? `#${row.sourceRank}` : '',
    row.year,
    communityRatingLabel(row),
  ].filter(Boolean).join(' • ');
  const media = document.createElement('div');
  media.className = 'media-search-actions bm365-media-actions';
  media.append(
    createSpotifySearchLink(row.artist, row.album),
    createYoutubeSearchLink(row.artist, row.album),
    createRateYourMusicSearchLink(row.artist, row.album),
  );
  copy.append(title);
  appendLastFmAlbumBadge(copy, row, lastFmStats);
  if (row.crossLists.length) copy.appendChild(createCrossListTags(row));
  copy.append(media, meta);
  left.append(image, copy);

  const controls = document.createElement('div');
  controls.className = 'bm365-rate-control';
  const rating = createAlbumStarRating(row.rating, {
    ariaLabel: `Ocena albumu ${row.artist} — ${row.album}`,
  });
  const save = document.createElement('button');
  save.className = 'bm365-btn';
  save.type = 'button';
  save.textContent = 'Zapisz ocenę';
  save.disabled = !rating.value;
  const feedback = document.createElement('div');
  feedback.className = 'bm365-rate-feedback';
  feedback.hidden = true;
  rating.addEventListener('change', () => { save.disabled = !rating.value; });
  save.addEventListener('click', async () => {
    const value = toNumber(rating.value);
    if (!Number.isFinite(value)) return;
    save.disabled = true;
    rating.disabled = true;
    feedback.hidden = false;
    feedback.textContent = 'Zapisywanie...';
    try {
      await updateRating(row, value);
      await init();
    } catch (error) {
      console.error(error);
      feedback.textContent = 'Nie udało się zapisać oceny.';
      rating.disabled = false;
      save.disabled = false;
    }
  });
  controls.append(rating, save, feedback);

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
    emptyText.textContent = 'Brak opisu. Skopiuj prompt, wygeneruj tekst i wklej go przez edycję albumu na pełnej stronie.';
    const copyPrompt = document.createElement('button');
    copyPrompt.type = 'button';
    copyPrompt.className = 'ba2027-copy-prompt';
    copyPrompt.textContent = 'Kopiuj prompt do AI';
    copyPrompt.addEventListener('click', async () => {
      try {
        await copyRymPolishBlackMetalAlbumPrompt(row);
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
  const rows = normalizeRows(payload).sort((a, b) => a.sourceRank - b.sourceRank);
  const doneRows = rows.filter((row) => row.listened);
  const ratedRows = rows.filter((row) => Number.isFinite(row.rating));
  const done = doneRows.length;
  const total = rows.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const average = ratedRows.length
    ? ratedRows.reduce((sum, row) => sum + row.rating, 0) / ratedRows.length
    : null;
  const next = rows.find((row) => !row.listened) || null;
  const lastFmStats = await fetchLastFmAlbumStats(next ? [next] : []);

  setText('rym-polish-bm-done', String(done));
  setText('rym-polish-bm-left', String(Math.max(0, total - done)));
  setText('rym-polish-bm-pct', `${pct}%`);
  setText('rym-polish-bm-progress-text', `${done} / ${total} — ${pct}%`);
  setText('rym-polish-bm-avg', average === null ? '—' : average.toFixed(2));
  setText('rym-polish-bm-avg-note', ratedRows.length ? `${ratedRows.length} ocen` : 'brak ocen');
  const progress = $('rym-polish-bm-progress-bar');
  if (progress) progress.style.width = `${pct}%`;
  await renderNext(next, rows, lastFmStats);
  setText('rym-polish-bm-foot', `Źródło: Rate Your Music • ${fmtDateTimeShort(new Date())}`);
}

async function init() {
  if (!$('rym-polish-bm-card')) return;
  try {
    const response = await fetch(ALBUMS_API, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    await render(payload);
  } catch (error) {
    console.error(error);
    setText('rym-polish-bm-foot', 'Nie udało się połączyć z lokalną bazą. Uruchom server.py.');
    await renderNext(null, []);
  }
}

init();
