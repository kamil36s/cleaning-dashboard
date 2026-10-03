import { musicApi } from './music-api.js';
import { createAlbumStarRating } from './album-star-rating.js';

const content = document.querySelector('#music-content');
const actualHeading = document.querySelector('#music-heading');
const searchPanel = document.querySelector('#music-search-results');
const searchForm = document.querySelector('#music-global-search');
const searchInput = document.querySelector('#music-global-search input');
const releaseDialog = document.querySelector('#music-release-detail')?.closest('dialog');
const releaseMount = document.querySelector('#music-release-detail');
const toast = document.querySelector('#music-toast');
const topbar = document.querySelector('.music-topbar');
const topbarActions = document.querySelector('#music-topbar-actions');

const preferencesKey = 'music-view-preferences-v1';
let savedPreferences = {};
try { savedPreferences = JSON.parse(localStorage.getItem(preferencesKey) || '{}') || {}; } catch { /* Invalid or unavailable browser storage. */ }
const state = {
  view: location.hash.replace('#', '') || savedPreferences.view || 'overview',
  libraryOffset: savedPreferences.libraryOffset || 0,
  libraryFilters: { limit: 50, sort: 'my_desc', ...savedPreferences.libraryFilters },
  genreQuery: savedPreferences.genreQuery || '',
  genreSort: savedPreferences.genreSort || 'name',
  genreTree: null,
  historyPeriod: savedPreferences.historyPeriod || 'all',
  historyOffset: savedPreferences.historyOffset || 0,
  historyLimit: 50,
  missingOffset: 0,
  missingLimit: 50,
  missingField: '',
  artworkRevision: 0,
  currentImport: null,
  artistRankingMin: savedPreferences.artistRankingMin || 3,
  artistRankingOffset: savedPreferences.artistRankingOffset || 0,
  artistRankingSort: savedPreferences.artistRankingSort || 'weighted',
  artistYearFilters: savedPreferences.artistYearFilters || { yearMode: 'all' },
};

function savePreferences() {
  try {
    localStorage.setItem(preferencesKey, JSON.stringify({
      view: state.view, libraryFilters: state.libraryFilters, libraryOffset: state.libraryOffset,
      genreQuery: state.genreQuery, genreSort: state.genreSort,
      historyPeriod: state.historyPeriod, historyOffset: state.historyOffset,
      artistRankingMin: state.artistRankingMin, artistRankingOffset: state.artistRankingOffset,
      artistRankingSort: state.artistRankingSort, artistYearFilters: state.artistYearFilters,
    }));
  } catch { /* The page still works when storage is unavailable. */ }
}

const labels = {
  overview: 'Przegląd', library: 'Biblioteka', rankings: 'Rankingi', genres: 'Gatunki',
  lists: 'Listy', history: 'Historia słuchania', import: 'Import', imports: 'Import',
};
const legacyProjectLabels = {
  black_metal_365: 'BM365',
  brutal_assault_2027: 'Brutal Assault',
  rym_polish_bm: 'Polish BM Top 100',
};

if (topbar && searchForm && topbarActions) topbar.insertBefore(searchForm, topbarActions);

function renderTopbarActions(view) {
  if (!topbarActions) return;
  const actions = {
    overview: '<button class="music-button" data-open-view="history">Historia</button><button class="music-button is-primary" data-open-view="library">Otwórz bibliotekę</button>',
    library: '<button class="music-button is-primary" data-open-view="imports">+ Importuj</button>',
    rankings: '<button class="music-button" data-focus-create-ranking>+ Nowy ranking</button>',
    genres: '',
    lists: '<button class="music-button is-primary" data-focus-create-list>+ Nowa lista</button>',
    history: '<button class="music-button" data-open-view="library">Biblioteka</button>',
    imports: '<button class="music-button" data-open-view="library">Biblioteka</button>',
  };
  topbarActions.innerHTML = actions[view] || '';
}

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
}

function number(value) {
  return new Intl.NumberFormat('pl-PL').format(Number(value || 0));
}

function decimal(value) {
  return value == null ? '—' : Number(value).toLocaleString('pl-PL', { maximumFractionDigits: 2 });
}

function date(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? esc(value) : new Intl.DateTimeFormat('pl-PL', { dateStyle: 'medium', timeStyle: value.includes('T') ? 'short' : undefined }).format(parsed);
}

function mediaUrl(value) {
  const source = String(value || '');
  return source.startsWith('/covers/') && location.pathname.includes('/cleaning-dashboard/')
    ? `/cleaning-dashboard${source}`
    : source;
}

function cover(row, className = 'music-table-cover') {
  const source = row?.cover_local || row?.coverLocal || row?.cover_remote || row?.coverRemote || row?.cover || row?.image || row?.artistImage;
  if (!source) return `<span class="${className} music-cover-placeholder" aria-hidden="true">♪</span>`;
  return `<img class="${className}" src="${esc(mediaUrl(source))}" alt="" loading="lazy" referrerpolicy="no-referrer">`;
}

function historyMedia(row, kind = 'album') {
  const source = kind === 'artist' ? (row?.image || row?.artistImage) : row?.cover;
  return source
    ? `<img class="music-history-thumb" src="${esc(mediaUrl(source))}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<span class="music-history-thumb music-cover-placeholder" aria-hidden="true">${kind === 'artist' ? '♪' : '♫'}</span>`;
}

function manualArtwork(path, className, alt, upload) {
  const edit = upload ? `<button type="button" class="music-art-edit" data-art-kind="${esc(upload.kind)}" data-art-key="${esc(upload.key)}" title="Zmień grafikę" aria-label="Zmień grafikę ${esc(alt)}">✎</button>` : '';
  const source = state.artworkRevision ? `${path}?v=${state.artworkRevision}` : path;
  return `<span class="music-manual-art ${className}"><span class="music-art-placeholder" aria-hidden="true">▧</span><img src="${esc(source)}" alt="${esc(alt)}" loading="lazy" data-manual-art>${edit}</span>`;
}

function legacySources(row) {
  const sources = String(row?.legacy_sources || '').split(',').filter(Boolean);
  if (!sources.length) return 'Import RYM';
  return sources.map((source) => legacyProjectLabels[source] || source).join(' · ');
}

function notify(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { toast.hidden = true; }, 3500);
}

function showError(error) {
  content.innerHTML = `<div class="music-error"><strong>Nie udało się wczytać widoku.</strong><br>${esc(error?.message || error)}</div>`;
}

async function busy(button, task) {
  const label = button?.textContent;
  if (button) { button.disabled = true; button.textContent = 'Pracuję…'; }
  try { return await task(); } finally { if (button) { button.disabled = false; button.textContent = label; } }
}

function section(title, subtitle, body, action = '') {
  return `<section class="music-section"><header class="music-section-head"><div><h3>${esc(title)}</h3>${subtitle ? `<p>${esc(subtitle)}</p>` : ''}</div>${action}</header>${body}</section>`;
}

function feedRows(rows, renderer) {
  if (!rows?.length) return '<div class="music-empty">Brak danych.</div>';
  return `<div class="music-feed">${rows.map(renderer).join('')}</div>`;
}

function releaseTable(rows, { ranking = false, personal = false } = {}) {
  if (!rows?.length) return '<div class="music-empty">Brak albumów spełniających kryteria.</div>';
  return `<div class="music-table-wrap"><table class="music-table"><thead><tr>${ranking ? '<th>#</th>' : ''}<th></th><th>Album</th><th>Rok</th><th>Źródła</th><th>Gatunki</th><th>Średnia RYM</th><th>Moja ocena</th>${personal ? '<th></th>' : ''}<th aria-label="Szczegóły"></th></tr></thead><tbody>${rows.map((row) => `
    <tr data-release-id="${row.id}">
      ${ranking ? `<td>${row.position}${row.movement ? `<br><small>${row.movement > 0 ? '+' : ''}${row.movement}</small>` : ''}</td>` : ''}
      <td>${cover(row)}</td>
      <td class="music-title-cell"><strong>${esc(row.title)}</strong><span>${esc(row.artist_credit)}</span></td>
      <td>${row.release_year || '—'}</td>
      <td><span class="music-status ${row.legacy_listened ? 'is-new' : 'is-match'}">${row.legacy_listened ? '✓ ' : ''}${esc(legacySources(row))}</span></td>
      <td>${esc(row.primary_genres || '—')}</td>
      <td>${decimal(row.rym_rating)}</td><td>${row.user_rating ?? row.legacy_rating ? `★ ${decimal(row.user_rating ?? row.legacy_rating)}` : '—'}</td>
      ${personal ? `<td><div class="music-ranking-controls"><button data-rank-move="up" data-id="${row.id}" title="Wyżej">↑</button><button data-rank-move="down" data-id="${row.id}" title="Niżej">↓</button><button data-rank-remove data-id="${row.id}" title="Usuń">×</button></div></td>` : ''}
      <td class="music-row-chevron" aria-hidden="true">›</td>
    </tr>`).join('')}</tbody></table></div>`;
}

async function renderOverview() {
  const data = await musicApi.overview();
  const lf = data.lastfm || {};
  const now = lf.nowPlaying;
  const recent = lf.rows?.[0];
  const nowImage = now?.image || now?.cover;
  const recentImage = recent?.cover || recent?.image;
  const nowMarkup = now
    ? `<article class="music-card music-now-playing">${nowImage ? `<img class="music-now-cover" src="${esc(mediaUrl(nowImage))}" alt="Okładka ${esc(now.album || now.track)}">` : '<span class="music-now-cover music-cover-placeholder">♫</span>'}<div class="music-now-copy"><span class="label">TERAZ GRA · LAST.FM</span><h3>${esc(now.track)}</h3><p>${esc(now.artist)}</p><p>${esc(now.album)}</p></div></article>`
    : `<article class="music-card music-now-playing">${recentImage ? `<img class="music-now-cover" src="${esc(mediaUrl(recentImage))}" alt="Okładka ${esc(recent?.album || recent?.track)}">` : '<span class="music-now-cover music-cover-placeholder">♫</span>'}<div class="music-now-copy"><span class="label">OSTATNIO · LAST.FM</span><h3>${esc(recent?.track || 'Brak bieżącego odtwarzania')}</h3><p>${esc(recent?.artist || (lf.status?.configured ? 'Połączono z Last.fm' : 'Dane z lokalnego cache Last.fm'))}</p><p>${esc(recent?.album || '')}</p></div></article>`;
  const stats = { ...data.stats, scrobbles: lf.status?.totalScrobbles || 0 };
  const projectMarkup = (data.projects || []).map((project) => {
    const pct = project.total ? Math.round(project.done / project.total * 100) : 0;
    const artwork = manualArtwork(`./assets/music/projects/${project.key}.webp`, 'music-project-cover', `projektu ${project.title}`, { kind: 'project', key: project.key });
    return `<article class="music-card music-project">${artwork}<a class="music-project-copy" href="${esc(project.href)}"><h4>${esc(project.title)}</h4><div class="progress"><i style="width:${pct}%"></i></div><div class="music-project-meta"><span>${project.done} / ${project.total} · ${pct}%</span><span>średnia ${decimal(project.averageRating)}</span></div>${project.next ? `<p class="music-project-next">Następny: <strong>${esc(project.next.artist)} — ${esc(project.next.title)}</strong></p>` : '<p class="music-project-next">Projekt ukończony</p>'}</a></article>`;
  }).join('');
  content.innerHTML = `
    <div class="music-grid music-overview-hero">${nowMarkup}<section class="music-card music-stats">
      <h3 class="music-card-heading">Twoja muzyka</h3>
      <div class="music-stat"><span>Albumy</span><strong>${number(stats.releases)}</strong></div>
      <div class="music-stat"><span>Artyści</span><strong>${number(stats.artists)}</strong></div>
      <div class="music-stat"><span>Gatunki</span><strong>${number(stats.genres)}</strong></div>
      <div class="music-stat"><span>Moje oceny</span><strong>${number(stats.ratings)}</strong></div>
      <div class="music-stat" style="grid-column:1/-1"><span>Scrobble Last.fm</span><strong>${number(stats.scrobbles)}</strong></div>
    </section></div>
    ${section('Projekty muzyczne', '', `<div class="music-grid music-projects">${projectMarkup}</div>`, '<button class="music-button" data-sync-legacy>Odśwież katalog projektów</button>')}
    <div class="music-two-columns">
      ${section('Ostatnie rankingi', '', feedRows(data.recentRankings, (row) => `<button class="music-feed-row music-search-result" data-ranking-id="${row.id}"><span><strong>${esc(row.name)}</strong><span>${esc(row.kind === 'PERSONAL' ? 'Mój ranking' : row.source)}</span></span><span>${number(row.entry_count)} pozycji</span></button>`))}
      ${section('Ostatnie importy', '', feedRows(data.recentImports, (row) => `<div class="music-feed-row"><span><strong>${esc(row.title || row.page_type)}</strong><span>${esc(row.status)} · ${date(row.imported_at)}</span></span><span>${number(row.parsed_count)}</span></div>`))}
    </div>
    ${section('Ostatnie słuchanie', '', feedRows(lf.rows, (row) => `<div class="music-feed-row music-history-row">${historyMedia(row)}<span><strong>${esc(row.track)}</strong><span>${esc(row.artist)} · ${esc(row.album)}</span></span><span>${date(row.playedAt)}</span></div>`), '<button class="music-button" data-view-jump="history">Pełna historia</button>')}`;
}

function yearFilterMarkup(filters = {}) {
  const mode = filters.yearMode || (filters.year ? 'year' : filters.decade ? 'decade' : 'all');
  const option = (value, label) => `<option value="${value}" ${mode === value ? 'selected' : ''}>${label}</option>`;
  const field = (name, label, active, step = 1) => `<label data-music-year-field="${active}" ${mode === active ? '' : 'hidden'}>${label}<input name="${name}" type="number" min="1000" max="2100" step="${step}" value="${esc(filters[name] || '')}" ${mode === active ? 'required' : ''}></label>`;
  return `<div class="music-year-filter" data-music-year-filter><label>Rok wydania<select name="yearMode" aria-label="Okres wydania">${option('all', 'Cały okres')}${option('year', 'Konkretny rok')}${option('decade', 'Dekada')}${option('range', 'Zakres lat')}</select></label>${field('year', 'Rok', 'year')}${field('decade', 'Dekada od', 'decade', 10)}${field('yearFrom', 'Od roku', 'range')}${field('yearTo', 'Do roku', 'range')}</div>`;
}

function updateYearFilterVisibility(container) {
  const mode = container?.querySelector('[name="yearMode"]')?.value;
  container?.querySelectorAll('[data-music-year-field]').forEach((label) => {
    const active = label.dataset.musicYearField === mode;
    label.hidden = !active;
    label.querySelector('input').required = active;
  });
}

async function renderLibrary() {
  const data = await musicApi.library({ ...state.libraryFilters, offset: state.libraryOffset });
  content.innerHTML = `${section('Katalog kanoniczny', `${number(data.total)} wydań · jedna encja niezależnie od źródła`, `
    <form class="music-filters" id="music-library-filters">
      <div class="music-filter-heading"><strong>Filtry biblioteki</strong><span>Wybierz kryteria i zapisz je przyciskiem poniżej.</span></div>
      <label class="music-filter-field music-filter-search"><span>Szukaj</span><input name="q" aria-label="Artysta lub album" value="${esc(state.libraryFilters.q || '')}" placeholder="Artysta lub album"></label>
      ${yearFilterMarkup(state.libraryFilters)}
      <label class="music-filter-field"><span>Typ wydania</span><select name="type" aria-label="Typ wydania"><option value="">Wszystkie typy</option>${['Album','EP','Single','Mixtape'].map((type) => `<option ${state.libraryFilters.type === type ? 'selected' : ''}>${type}</option>`).join('')}</select></label>
      <label class="music-filter-field"><span>Źródło</span><select name="source" aria-label="Źródło"><option value="">Wszystkie źródła</option>${Object.entries(legacyProjectLabels).map(([value, label]) => `<option value="${value}" ${state.libraryFilters.source === value ? 'selected' : ''}>${label}</option>`).join('')}<option value="rym_import" ${state.libraryFilters.source === 'rym_import' ? 'selected' : ''}>Import RYM</option></select></label>
      <label class="music-filter-field"><span>Odsłuchanie</span><select name="listened" aria-label="Status odsłuchania w projektach"><option value="">Wszystkie</option><option value="yes" ${state.libraryFilters.listened === 'yes' ? 'selected' : ''}>Odsłuchane w projektach</option><option value="no" ${state.libraryFilters.listened === 'no' ? 'selected' : ''}>Nieodsłuchane w projektach</option></select></label>
      <label class="music-filter-field"><span>Moja ocena</span><select name="rating" aria-label="Minimalna ocena" ${state.libraryFilters.showRated === '0' ? 'disabled' : ''}><option value="">Każda ocena</option>${[4.5,4,3.5,3].map((rating) => `<option value="${rating}" ${String(state.libraryFilters.rating) === String(rating) ? 'selected' : ''}>od ${rating}</option>`).join('')}</select></label>
      <fieldset class="music-rating-visibility"><legend>Pokazuj</legend><label><input type="checkbox" name="showRated" value="1" ${state.libraryFilters.showRated === '0' ? '' : 'checked'}> Ocenione</label><label><input type="checkbox" name="showUnrated" value="1" ${state.libraryFilters.showUnrated === '0' ? '' : 'checked'}> Nieocenione</label></fieldset>
      <label class="music-filter-field music-filter-sort"><span>Sortowanie</span><select name="sort" aria-label="Sortuj bibliotekę"><option value="my_desc" ${(!state.libraryFilters.sort || state.libraryFilters.sort === 'my_desc') ? 'selected' : ''}>Moja ocena: najwyższa</option><option value="my_asc" ${state.libraryFilters.sort === 'my_asc' ? 'selected' : ''}>Moja ocena: najniższa</option><option value="rym_desc" ${state.libraryFilters.sort === 'rym_desc' ? 'selected' : ''}>Średnia RYM: najwyższa</option><option value="rym_asc" ${state.libraryFilters.sort === 'rym_asc' ? 'selected' : ''}>Średnia RYM: najniższa</option><option value="year_desc" ${state.libraryFilters.sort === 'year_desc' ? 'selected' : ''}>Rok: najnowsze</option><option value="year_asc" ${state.libraryFilters.sort === 'year_asc' ? 'selected' : ''}>Rok: najstarsze</option><option value="artist_asc" ${state.libraryFilters.sort === 'artist_asc' ? 'selected' : ''}>Artysta: A–Z</option><option value="title_asc" ${state.libraryFilters.sort === 'title_asc' ? 'selected' : ''}>Album: A–Z</option></select></label>
      <div class="music-filter-actions"><button class="music-button is-primary">Zastosuj filtry</button>
      <button class="music-button" type="button" data-reset-library-filters>Wyczyść</button>
      <button class="music-button" type="button" data-fetch-missing-covers>Popraw okładki w tle</button></div>
    </form><p class="music-filter-explanation">Odsłuchane: status z projektów muzycznych; sam import ocen RYM go nie ustawia. Ocenione: wydania z Twoimi gwiazdkami w kolumnie „Moja ocena”.</p>${releaseTable(data.rows)}<div class="music-pagination"><button class="music-button" data-page="prev" ${data.offset === 0 ? 'disabled' : ''}>← Poprzednie</button><span>${data.total ? data.offset + 1 : 0}–${Math.min(data.offset + data.limit, data.total)} z ${data.total}</span><button class="music-button" data-page="next" ${data.offset + data.limit >= data.total ? 'disabled' : ''}>Następne →</button></div>`)} `;
}

function genreSort(rows) {
  return [...rows].sort((left, right) => state.genreSort === 'albums'
    ? Number(right.release_count) - Number(left.release_count) || left.name.localeCompare(right.name, 'pl')
    : left.name.localeCompare(right.name, 'pl'));
}

const SUPPLEMENTARY_GENRE_ROOT_SLUGS = new Set([
  'childrens-music',
  'comedy',
  'field-recording',
  'hymn',
  'jingles',
  'mantra',
  'march',
  'marching-band',
  'musical-theatre-and-entertainment',
  'regional-music',
  'scenes-and-movements',
  'sound-effects',
  'spoken-word',
]);

function isSupplementaryGenreRoot(genre) {
  return SUPPLEMENTARY_GENRE_ROOT_SLUGS.has(String(genre?.slug || '').toLocaleLowerCase('en'));
}

function genreBranchMarkup(id, path = []) {
  const tree = state.genreTree;
  const genre = tree?.byId.get(Number(id));
  if (!genre || path.includes(Number(id))) return '';
  const childIds = tree.children.get(Number(id)) || [];
  const nextPath = [...path, Number(id)];
  const genreKey = genre.slug || `genre-${genre.id}`;
  const artwork = manualArtwork(`./assets/music/genres/${encodeURIComponent(genreKey)}.webp`, `music-genre-cover ${path.length ? 'is-nested' : ''}`, `gatunku ${genre.name}`, { kind: 'genre', key: genreKey });
  const description = !path.length && genre.description ? `<span class="music-genre-description">${esc(genre.description)}</span>` : '';
  const copy = `<span class="music-genre-copy"><span class="music-genre-name">${esc(genre.name)}</span>${description}<span class="music-genre-metrics"><span class="music-genre-count">${number(genre.release_count)} albumów</span>${childIds.length ? `<span class="music-genre-count">${number(childIds.length)} podgatunków</span>` : ''}</span></span>`;
  if (!childIds.length) return `<article class="music-genre-leaf" data-genre-path="${nextPath.join(',')}">${artwork}${copy}<button type="button" class="music-genre-open" data-genre-id="${genre.id}" aria-label="Otwórz stronę gatunku ${esc(genre.name)}">›</button></article>`;
  return `<details class="music-genre-branch" data-genre-branch="${genre.id}" data-genre-path="${nextPath.join(',')}"><summary>${artwork}${copy}<span class="music-genre-toggle" aria-hidden="true">⌄</span></summary><div class="music-genre-branch-action"><button type="button" class="music-button" data-genre-id="${genre.id}">Albumy i szczegóły →</button></div><div class="music-genre-children" data-genre-children="${genre.id}"></div></details>`;
}

async function renderGenres() {
  const data = await musicApi.genreTree();
  const genres = data.genres || [];
  const byId = new Map(genres.map((genre) => [Number(genre.id), genre]));
  const children = new Map();
  (data.relations || []).forEach(({ parentId, childId }) => {
    const list = children.get(Number(parentId)) || [];
    list.push(Number(childId));
    children.set(Number(parentId), list);
  });
  state.genreTree = { byId, children };
  const query = state.genreQuery.trim().toLocaleLowerCase('pl');
  let body;
  if (query) {
    const matches = genreSort(genres.filter((genre) => genre.name.toLocaleLowerCase('pl').includes(query)));
    body = `<div class="music-genre-grid">${matches.map((genre) => `<article class="music-card music-genre-card" data-genre-id="${genre.id}">${manualArtwork(`./assets/music/genres/${encodeURIComponent(genre.slug || `genre-${genre.id}`)}.webp`, 'music-genre-cover', `Grafika gatunku ${genre.name}`, { kind: 'genre', key: genre.slug || `genre-${genre.id}` })}<div><h4>${esc(genre.name)}</h4><p>${esc(genre.description || 'Brak opisu w źródle.')}</p><div class="music-card-kpis"><span><strong>${genre.release_count}</strong> albumów</span><span><strong>${genre.child_count}</strong> podgatunków</span><span><strong>${genre.parent_count}</strong> rodziców</span></div></div></article>`).join('') || '<div class="music-empty">Brak pasujących gatunków.</div>'}</div>`;
  } else {
    const roots = genreSort(genres.filter((genre) => Number(genre.parent_count) === 0));
    const primaryRoots = roots.filter((genre) => !isSupplementaryGenreRoot(genre));
    const supplementaryRoots = roots.filter(isSupplementaryGenreRoot);
    const supplementary = supplementaryRoots.length ? `
      <section class="music-genre-secondary" aria-labelledby="music-genre-secondary-title">
        <header class="music-genre-secondary-head">
          <div><span>Na końcu katalogu</span><h3 id="music-genre-secondary-title">Kategorie użytkowe i pozamuzyczne</h3></div>
          <small>${number(supplementaryRoots.length)} kategorii</small>
        </header>
        <div class="music-genre-tree">${supplementaryRoots.map((genre) => genreBranchMarkup(genre.id)).join('')}</div>
      </section>` : '';
    body = `<div class="music-genre-tree">${primaryRoots.map((genre) => genreBranchMarkup(genre.id)).join('')}</div>${supplementary}`;
  }
  content.innerHTML = `${section('Główne gatunki', `${number(data.total)} gatunków · ${number(data.relations?.length)} relacji`, `<form class="music-filters music-genre-toolbar" id="music-genre-search"><label class="music-field"><span>Szukaj</span><input name="q" value="${esc(state.genreQuery)}" placeholder="Szukaj gatunku"></label><label class="music-field"><span>Sortowanie</span><select name="sort"><option value="name" ${state.genreSort === 'name' ? 'selected' : ''}>A–Z</option><option value="albums" ${state.genreSort === 'albums' ? 'selected' : ''}>Najwięcej albumów</option></select></label><button class="music-button is-primary">Zastosuj</button>${state.genreQuery ? '<button class="music-button" type="button" data-clear-genre-search>Wyczyść</button>' : ''}</form>${body}`)}`;
}

async function openGenre(id) {
  const { genre } = await musicApi.genre(id);
  content.innerHTML = `<div class="music-actions" style="margin-bottom:12px"><button class="music-button" data-back-genres>← Gatunki</button><button class="music-button is-primary" data-create-for-genre="${genre.id}" data-name="${esc(genre.name)}">Utwórz mój ranking</button></div>
    ${section(genre.name, genre.description || 'Bez opisu', `<div class="music-two-columns"><article class="music-card"><h4>Rodzice</h4><div class="music-tag-list">${genre.parents.length ? genre.parents.map((item) => `<button class="music-tag" data-genre-id="${item.id}">${esc(item.name)}</button>`).join('') : '<span class="music-tag">Gatunek główny</span>'}</div></article><article class="music-card"><h4>Podgatunki</h4><div class="music-tag-list">${genre.children.length ? genre.children.map((item) => `<button class="music-tag" data-genre-id="${item.id}">${esc(item.name)}</button>`).join('') : '<span class="music-tag">Brak</span>'}</div></article></div>`)}
    ${section('Albumy', `${genre.releaseCount} w katalogu`, releaseTable(genre.releases))}
    ${section('Rankingi', '', feedRows(genre.rankings, (row) => `<button class="music-feed-row music-search-result" data-ranking-id="${row.id}"><strong>${esc(row.name)}</strong><span>${esc(row.kind)}</span></button>`))}`;
}

async function renderRankings() {
  const [data, artists] = await Promise.all([
    musicApi.rankings(),
    musicApi.artistRanking({ minRatings: state.artistRankingMin, offset: state.artistRankingOffset, limit: 100, sort: state.artistRankingSort, ...state.artistYearFilters }),
  ]);
  const sources = data.rows.filter((row) => row.kind === 'SOURCE');
  const personal = data.rows.filter((row) => row.kind === 'PERSONAL');
  const cards = (rows) => rows.length ? `<div class="music-ranking-grid">${rows.map((row) => `<article class="music-card music-ranking-card" data-ranking-id="${row.id}"><span class="music-status ${row.kind === 'PERSONAL' ? 'is-new' : 'is-match'}">${row.kind === 'PERSONAL' ? 'MÓJ' : esc(row.source)}</span><h4 style="margin-top:9px">${esc(row.name)}</h4><p>${row.latest_snapshot_at ? `Aktualizacja ${date(row.latest_snapshot_at)}` : 'Nowy ranking'}</p><div class="music-card-kpis"><span><strong>${row.entry_count}</strong> pozycji</span><span><strong>${row.snapshot_count}</strong> snapshotów</span></div></article>`).join('')}</div>` : '<div class="music-empty">Brak rankingów.</div>';
  const artistRows = artists.rows.map((row, index) => `<tr data-artist-filter="${esc(row.name)}" data-artist-releases="${(row.release_ids || []).join(',')}"><td>${artists.offset + index + 1}</td><td><span class="music-artist-identity">${cover({ image: row.image }, 'music-artist-avatar')}<strong>${esc(row.name)}</strong></span></td><td>★ ${decimal(row.weighted_rating)}</td><td>★ ${decimal(row.average_rating)}</td><td>${number(row.rated_count)}</td><td>${number(row.five_star_count)}</td></tr>`).join('');
  const artistTable = `<form class="music-filters" id="music-artist-filters"><label>Ocenione albumy <select id="music-artist-min-ratings">${[1, 3, 5, 10].map((value) => `<option value="${value}" ${state.artistRankingMin === value ? 'selected' : ''}>co najmniej ${value}</option>`).join('')}</select></label><label>Kolejność <select id="music-artist-ranking-sort"><option value="weighted" ${state.artistRankingSort === 'weighted' ? 'selected' : ''}>średnia ważona</option><option value="average" ${state.artistRankingSort === 'average' ? 'selected' : ''}>średnia zwykła</option></select></label>${yearFilterMarkup(state.artistYearFilters)}<button class="music-button is-primary">Filtruj</button></form><div class="music-table-wrap"><table class="music-table"><thead><tr><th>#</th><th>Artysta</th><th>Średnia ważona / 5</th><th>Średnia / 5</th><th>Albumy</th><th>5★</th></tr></thead><tbody>${artistRows || '<tr><td colspan="6">Brak artystów z ocenami.</td></tr>'}</tbody></table></div><div class="music-pagination"><button class="music-button" data-artist-page="prev" ${artists.offset === 0 ? 'disabled' : ''}>← Poprzednie</button><span>${number(artists.total)} artystów</span><button class="music-button" data-artist-page="next" ${artists.offset + artists.rows.length >= artists.total ? 'disabled' : ''}>Następne →</button></div>`;
  content.innerHTML = `${section('Artyści według moich ocen', `Jak w BM365: (suma ocen albumów + 3 × średnia globalna albumów ${decimal(artists.globalAverage)}) / (liczba ocenionych albumów + 3). Single i EP nie liczą się; współprace liczą się dla każdego artysty.`, artistTable)}<form class="music-form music-compact-form" id="music-create-ranking"><h3>Nowy ranking osobisty</h3><div class="music-filters"><input name="name" aria-label="Nazwa rankingu" required placeholder="np. Mój ranking Ambient Americana"><button class="music-button is-primary">Utwórz</button></div></form>${section('Rankingi źródłowe', 'Każdy import chartu tworzy historyczny snapshot', cards(sources))}${section('Moje rankingi', 'Kolejność jest niezależna od ocen', cards(personal))}`;
}

async function openRanking(id) {
  const data = await musicApi.ranking(id);
  const personal = data.ranking.kind === 'PERSONAL';
  content.innerHTML = `<div class="music-actions" style="margin-bottom:12px"><button class="music-button" data-back-rankings>← Rankingi</button></div>
    ${section(data.ranking.name, `${personal ? 'Mój ranking' : data.ranking.source} · ${data.snapshots.length ? date(data.snapshots[0].captured_at) : 'bez snapshotu'}`, `${personal ? '<form class="music-form" id="music-ranking-add"><label>Dodaj album<input name="q" required placeholder="Wpisz artystę lub tytuł"></label><div id="music-ranking-candidates"></div><button class="music-button">Szukaj w katalogu</button></form><br>' : ''}${releaseTable(data.entries, { ranking: true, personal })}`)}`;
  content.dataset.rankingId = id;
}

async function renderLists() {
  const data = await musicApi.lists();
  content.innerHTML = `<form class="music-form music-compact-form" id="music-create-list"><h3>Nowa lista</h3><div class="music-filters"><input name="name" aria-label="Nazwa listy" required placeholder="np. Albumy na wyjazd"><input name="description" aria-label="Opis listy" placeholder="Krótki opis"><button class="music-button is-primary">Utwórz</button></div></form>${section('Listy', 'Luźne kolekcje, niezależne od rankingów', data.rows.length ? `<div class="music-list-grid">${data.rows.map((row) => `<article class="music-card music-list-card"><h4>${esc(row.name)}</h4><p>${esc(row.description || 'Bez opisu')}</p><div class="music-card-kpis"><span><strong>${row.entry_count}</strong> albumów</span></div></article>`).join('')}</div>` : '<div class="music-empty music-empty-compact"><span aria-hidden="true">≡</span><strong>Nie masz jeszcze list</strong><p>Utwórz pierwszą kolekcję albumów powyżej.</p></div>')}`;
}

async function renderHistory(period = state.historyPeriod) {
  state.historyPeriod = period;
  savePreferences();
  const data = await musicApi.lastfm({ period, limit: state.historyLimit, offset: state.historyOffset, live: 1 });
  const total = Number(data.stats?.scrobbles || 0);
  const first = data.rows?.length ? state.historyOffset + 1 : 0;
  const last = state.historyOffset + Number(data.rows?.length || 0);
  const rankedRows = (rows, kind) => {
    const max = Math.max(...(rows || []).map((row) => Number(row.scrobbles || 0)), 1);
    return feedRows(rows, (row, index) => `<div class="music-ranked-row${kind === 'artist' ? ' is-artist' : ''}"><span class="music-rank-number">${index + 1}</span>${historyMedia(row, kind)}<span class="music-ranked-copy"><strong>${esc(kind === 'artist' ? row.artist : row.album)}</strong>${kind === 'album' ? `<span>${esc(row.artist)}</span>` : ''}</span><span class="music-ranked-count"><strong>${number(row.scrobbles)}×</strong><i style="--rank-width:${Math.max(4, Math.round(Number(row.scrobbles || 0) / max * 100))}%"></i></span></div>`);
  };
  const pagination = `<div class="music-pagination"><button class="music-button" data-history-page="prev" ${state.historyOffset === 0 ? 'disabled' : ''}>← Poprzednie</button><span>${number(first)}–${number(last)} z ${number(total)}</span><button class="music-button" data-history-page="next" ${last >= total || !data.rows?.length ? 'disabled' : ''}>Następne →</button></div>`;
  content.innerHTML = `<div class="music-subnav">${[['today','Dziś'],['week','Tydzień'],['month','Miesiąc'],['year','Rok'],['all','Całość']].map(([key,label]) => `<button data-history-period="${key}" class="${period === key ? 'is-active' : ''}">${label}</button>`).join('')}</div>
    <div class="music-grid" style="margin-bottom:20px"><section class="music-card music-stats" style="grid-column:1/-1;grid-template-columns:repeat(4,1fr)">${Object.entries(data.stats).map(([key,value]) => `<div class="music-stat"><span>${({scrobbles:'Scrobble',artists:'Artyści',albums:'Albumy',tracks:'Utwory'})[key]}</span><strong>${number(value)}</strong></div>`).join('')}</section></div>
    <div class="music-two-columns music-history-leaders">${section('Top artyści', '', rankedRows(data.topArtists, 'artist'))}${section('Top albumy', '', rankedRows(data.topAlbums, 'album'))}</div>
    ${section('Ostatnie scrobble', 'Widok stronicowany z istniejącej bazy Last.fm', `${feedRows(data.rows, (row) => `<div class="music-feed-row music-history-row">${historyMedia(row)}<span><strong>${esc(row.track)}</strong><span>${esc(row.artist)} · ${esc(row.album)}</span></span><span>${date(row.playedAt)}</span></div>`)}${pagination}`)}`;
}

function importStatusClass(status) {
  if (status === 'NEW') return 'is-new';
  if (status === 'AMBIGUOUS' || status === 'ERROR') return 'is-ambiguous';
  return 'is-match';
}

function renderImportPreview(payload) {
  const batch = payload.batch;
  state.currentImport = batch;
  const isGenre = batch.page_type === 'RYM_GENRE_INDEX';
  const rows = batch.rows.slice(0, isGenre ? 250 : 500);
  const body = rows.map((row) => {
    const item = row.parsed;
    if (isGenre) return `<tr><td>${row.row_index}</td><td class="music-title-cell"><strong>${esc(item.name)}</strong><span>${esc(item.slug || '')}</span></td><td>${item.depth}</td><td>${esc(item.parentUrls?.length || 0)}</td><td colspan="4">${esc(item.description || '—')}</td></tr>`;
    const defaultAction = row.match_status === 'AMBIGUOUS' || row.match_status === 'ERROR' ? 'skip' : (row.matched_release_id ? `match:${row.matched_release_id}` : 'create');
    const candidates = (row.candidates || []).map((candidate) => `<option value="match:${candidate.id}" ${defaultAction === `match:${candidate.id}` ? 'selected' : ''}>Połącz: ${esc(candidate.artist_credit)} — ${esc(candidate.title)} (${candidate.release_year || '—'})</option>`).join('');
    return `<tr><td>${item.position || row.row_index}</td><td>${cover(item)}</td><td class="music-title-cell"><strong>${esc(item.title)}</strong><span>${esc(item.artistCredit)}</span></td><td>${item.releaseYear || '—'}</td><td>${decimal(item.userRating ?? item.rymRating)}</td><td>${esc((item.primaryGenres || []).map((genre) => genre.name).join(', '))}</td><td><span class="music-status ${importStatusClass(row.match_status)}">${esc(row.match_status)}</span></td><td><select data-import-resolution="${row.id}"><option value="create" ${defaultAction === 'create' ? 'selected' : ''}>Utwórz nowy</option>${candidates}<option value="skip" ${defaultAction === 'skip' ? 'selected' : ''}>Pomiń</option></select><button class="music-button" type="button" data-import-find="${row.id}">Znajdź</button></td></tr>`;
  }).join('');
  content.innerHTML = `${section('Podgląd importu', batch.title || batch.original_filename, `
    <div class="music-file-meta">${esc(batch.original_filename)} · ${esc(batch.page_type)} · parser ${esc(batch.parser_version)}${payload.alreadyImported ? ' · ten sam plik był już analizowany' : ''}</div>
    <div class="music-import-summary"><div class="music-stat"><span>Wiersze</span><strong>${batch.parsed_count}</strong></div><div class="music-stat"><span>Nowe</span><strong>${batch.new_count}</strong></div><div class="music-stat"><span>Dopasowane</span><strong>${batch.matched_count}</strong></div><div class="music-stat"><span>Niejednoznaczne</span><strong>${batch.ambiguous_count}</strong></div><div class="music-stat"><span>Błędy</span><strong>${batch.error_count}</strong></div></div>
    <div class="music-table-wrap"><table class="music-table"><thead><tr><th>#</th>${isGenre ? '<th>Gatunek</th><th>Poziom</th><th>Rodzice</th><th colspan="4">Opis</th>' : '<th></th><th>Album</th><th>Rok</th><th>' + (batch.page_type === 'RYM_COLLECTION' ? 'Moja ocena' : 'RYM') + '</th><th>Gatunki</th><th>Status</th><th>Akcja</th>'}</tr></thead><tbody>${body}</tbody></table></div>${rows.length < batch.rows.length ? `<p class="music-file-meta">Podgląd pokazuje pierwsze ${rows.length} z ${batch.rows.length} wierszy. Commit obejmie cały import.</p>` : ''}
    <div class="music-import-actions"><button class="music-button" data-import-reset>Wybierz inny plik</button><button class="music-button is-primary" data-import-commit ${batch.status === 'COMMITTED' ? 'disabled' : ''}>${batch.status === 'COMMITTED' ? 'Już zatwierdzono' : 'Zatwierdź import'}</button></div>`)}`;
}

async function renderImport() {
  const [overview, missing, enrichment] = await Promise.all([
    musicApi.overview().catch(() => ({ recentImports: [] })),
    musicApi.missingMetadata({ limit: state.missingLimit, offset: state.missingOffset, field: state.missingField }).catch(() => ({ rows: [], total: 0, limit: state.missingLimit, offset: 0 })),
    musicApi.enrichmentStatus().catch(() => null),
  ]);
  const recent = feedRows(overview.recentImports, (row) => `<div class="music-feed-row"><span><strong>${esc(row.title || row.page_type)}</strong><span>${esc(row.status)} · ${date(row.imported_at)}</span></span><span>${number(row.parsed_count)} rekordów</span></div>`);
  const missingRows = feedRows(missing.rows, (row) => `<button class="music-missing-row" data-release-id="${row.id}">${cover(row, 'music-missing-cover')}<span class="music-missing-copy"><strong>${esc(row.title)}</strong><span>${esc(row.artist_credit)} · ${row.release_year || 'rok nieznany'}</span><span class="music-missing-tags">${(row.missing_labels || []).map((label) => `<i>${esc(label)}</i>`).join('')}</span></span><span class="music-row-chevron" aria-hidden="true">›</span></button>`);
  const missingLast = Number(missing.offset || 0) + Number(missing.rows?.length || 0);
  const queueStatus = enrichment ? `<p class="music-enrichment-status">Uzupełnianie: ${enrichment.enabled ? 'włączone' : 'wyłączone'} · okładki ${number(enrichment.covers)}/${number(enrichment.total)} · zidentyfikowane ${number(enrichment.identified)} · w kolejce ${number(enrichment.jobs?.pending)} · niejednoznaczne ${number(enrichment.jobs?.unresolved)} · błędy API ${number(enrichment.apiErrors)}</p>` : '';
  const missingControls = `<form class="music-missing-filter" id="music-missing-filter"><label>Rodzaj braku<select name="field"><option value="">Wszystkie braki</option>${Object.entries({ cover: 'Okładka', date: 'Pełna data wydania', year: 'Rok wydania', genres: 'Gatunki', tracklist: 'Tracklista', description: 'Opis' }).map(([value, label]) => `<option value="${value}" ${state.missingField === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label><button class="music-button">Filtruj</button><button class="music-button" type="button" data-queue-enrichment>Dodaj 50 do kolejki</button></form>${queueStatus}${missingRows}<div class="music-pagination"><button class="music-button" data-missing-page="prev" ${Number(missing.offset || 0) === 0 ? 'disabled' : ''}>← Poprzednie</button><span>${missing.rows?.length ? Number(missing.offset || 0) + 1 : 0}–${missingLast} z ${number(missing.total)}</span><button class="music-button" data-missing-page="next" ${missingLast >= Number(missing.total || 0) ? 'disabled' : ''}>Następne →</button></div>`;
  content.innerHTML = `<div class="music-import-layout">${section('Import zapisanej strony RYM', 'Plik jest analizowany lokalnie; zatwierdzasz wynik dopiero po podglądzie.', `<label class="music-import-drop" id="music-import-drop"><input id="music-import-file" type="file" accept=".html,.htm,text/html"><div><span class="music-import-icon" aria-hidden="true">⇧</span><strong>Upuść tutaj zapisany plik HTML</strong><span>Obsługiwane: indeks gatunków, chart albumów, strona wydania i kolekcja ocen.</span><span class="music-button is-primary">Wybierz plik</span></div></label><p class="music-file-meta" id="music-import-status">Oryginalny HTML zostanie zachowany lokalnie wraz z hashem SHA-256 i wersją parsera.</p>`)}<aside class="music-card music-import-guide"><h3>Jak to działa?</h3><ol><li><span>1</span><div><strong>Eksportuj stronę</strong><p>Zapisz stronę RYM jako plik HTML.</p></div></li><li><span>2</span><div><strong>Wgraj plik</strong><p>Wybierz go z dysku albo przeciągnij tutaj.</p></div></li><li><span>3</span><div><strong>Sprawdź podgląd</strong><p>Parser wykryje rekordy i możliwe duplikaty.</p></div></li><li><span>4</span><div><strong>Zatwierdź</strong><p>Dopiero wtedy dane trafią do biblioteki.</p></div></li></ol></aside></div>${section('Braki w katalogu', `${number(missing.total)} albumów wymaga uzupełnienia · po dodaniu danych pozycja znika z odpowiedniego filtra`, missingControls)}${section('Ostatnie importy', '', recent)}`;
}

async function openRelease(id) {
  const data = await musicApi.release(id);
  const row = data.release;
  const lists = await musicApi.lists();
  const duration = (seconds) => seconds == null ? '—' : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  const effectiveRating = row.user_rating ?? row.legacy_rating;
  const legacyMarkup = row.legacyLinks.map((link) => `<article class="music-card"><strong>${esc(legacyProjectLabels[link.legacy_module] || link.legacy_module)}</strong><p>${link.listened ? '✓ Odsłuchane' : 'Nieodsłuchane'} · moja ocena ${decimal(link.rating)}</p><p>${link.planned_date ? `Plan: ${date(link.planned_date)}` : ''}${link.minutes ? ` · ${link.minutes} min` : ''}${link.source_rank ? ` · #${link.source_rank}` : ''}</p></article>`).join('');
  const meta = row.metadata || {};
  const facts = [['Typ', [meta.primary_type, ...(meta.secondary_types || [])].filter(Boolean).join(' · ')], ['Kraj', meta.country], ['Format', (meta.formats || []).join(', ')], ['Język', meta.language], ['Wytwórnia', row.label], ['Nr katalogowy', row.catalog_number], ['Kod kreskowy', meta.barcode]].filter(([, value]) => value);
  const artistFacts = (row.artists || []).map((artist) => `<div class="music-artist-facts">${artist.metadata?.image_url ? `<img src="${esc(mediaUrl(artist.metadata.image_url))}" alt="">` : ''}<span><strong>${esc(artist.name)}</strong><small>${esc([artist.metadata?.country, artist.metadata?.begin_date, artist.metadata?.end_date].filter(Boolean).join(' · '))}</small>${artist.metadata?.factual_description ? `<small>${esc(artist.metadata.factual_description)}</small>` : ''}${/^https?:\/\//i.test(artist.metadata?.official_website || '') ? `<a href="${esc(artist.metadata.official_website)}" target="_blank" rel="noopener noreferrer">Strona artysty ↗</a>` : ''}</span></div>`).join('');
  releaseMount.innerHTML = `<header class="music-release-hero"><div class="music-release-cover-panel">${cover(row, 'music-cover')}<div class="music-cover-actions"><button class="music-button" type="button" data-fetch-cover="${row.id}">Uzupełnij w tle</button><label class="music-button">Wybierz plik<input type="file" accept="image/*" data-upload-cover="${row.id}" hidden></label></div></div><div><span class="music-status is-match">${esc([meta.primary_type, ...(meta.secondary_types || [])].filter(Boolean).join(' · ') || row.release_type)}</span><h2>${esc(row.title)}</h2><p>${esc(row.artist_credit)}</p><p>${esc(row.effective_release_date || row.release_year || 'Data nieznana')}${row.duration_seconds ? ` · ${Math.round(row.duration_seconds / 60)} min` : ''}</p><div class="music-tag-list">${row.genres.map((genre) => `<button class="music-tag" data-modal-genre="${genre.id}">${esc(genre.role)} · ${esc(genre.name)}</button>`).join('')}</div><div class="music-rating-form"><span>Moja ocena</span><div id="music-album-rating"></div>${row.user_rating == null && row.legacy_rating != null ? '<small>Wartość przeniesiona z projektu źródłowego.</small>' : ''}</div></div></header>
    <div class="music-release-body"><div>
      ${row.description ? section('Opis', '', `<div class="music-card"><p style="white-space:pre-line">${esc(row.description)}</p></div>`) : ''}
      ${facts.length || artistFacts ? section('Dane wydania i artyści', '', `<div class="music-card">${facts.map(([label, value]) => `<p><strong>${esc(label)}:</strong> ${esc(value)}</p>`).join('')}${artistFacts}</div>`) : ''}
      ${section('Utwory', '', row.tracks.length ? row.tracks.map((track) => `<div class="music-track-row"><span>${esc(track.position)}</span><strong>${esc(track.title)}</strong><span>${duration(track.duration_seconds)}</span></div>`).join('') : '<p>Brak tracklisty — zaimportuj stronę albumu.</p>')}
      ${section('Rankingi', '', feedRows(row.rankings, (ranking) => `<button class="music-feed-row music-search-result" data-modal-ranking="${ranking.id}"><span><strong>#${ranking.position} · ${esc(ranking.name)}</strong><span>${esc(ranking.kind)}</span></span><span>${date(ranking.captured_at)}</span></button>`))}
      ${section('Kredyty', '', row.credits.length ? row.credits.map((credit) => `<div class="music-credit-row"><span>•</span><strong>${esc(credit.person_name)}</strong><span>${esc(credit.role)}</span></div>`).join('') : '<p>Brak danych.</p>')}
    </div><aside>
      ${section('Projekty źródłowe', '', legacyMarkup || '<p>Album pochodzi z importu RYM.</p>')}
      ${section('Metadane RYM', '', row.metrics.length ? `<article class="music-card"><strong>${decimal(row.metrics[0].rating)} / 5</strong><p>${esc(row.metrics[0].rating_count_display || '—')} ocen · ${esc(row.metrics[0].review_count_display || '—')} recenzji</p><p>${esc(row.metrics[0].ranking_text || '')}</p><small>${date(row.metrics[0].captured_at)}</small></article>` : (row.rym_rating != null ? `<article class="music-card"><strong>${decimal(row.rym_rating)} / 5</strong><p>Ocena zachowana z projektu legacy.</p></article>` : '<p>Brak metryk.</p>'))}
      ${section('Deskryptory', '', `<div class="music-tag-list">${row.descriptors.map((item) => `<span class="music-tag">${esc(item)}</span>`).join('') || '<span class="music-tag">Brak</span>'}</div>`)}
      ${section('Last.fm', '', `<article class="music-card"><strong>${number(data.lastfm?.albumScrobbles)} scrobbli</strong><p>${data.lastfm?.lastScrobbleAt ? `Ostatnio ${date(data.lastfm.lastScrobbleAt)}` : 'Jeszcze niesłuchany lub brak dopasowania.'}</p></article>`)}
      ${section('Dodaj do listy', '', lists.rows.length ? `<form class="music-form" data-list-add="${row.id}"><select name="listId">${lists.rows.map((list) => `<option value="${list.id}">${esc(list.name)}</option>`).join('')}</select><button class="music-button">Dodaj</button></form>` : '<p>Najpierw utwórz listę.</p>')}
      <details><summary>Źródła i identyfikatory</summary><pre style="white-space:pre-wrap;font-size:9px">${esc(JSON.stringify({ externalIds: row.externalIds, legacyLinks: row.legacyLinks }, null, 2))}</pre></details>
    </aside></div>`;
  const ratingMount = releaseMount.querySelector('#music-album-rating');
  const ratingControl = createAlbumStarRating(effectiveRating, { ariaLabel: `Ocena albumu ${row.title}` });
  ratingControl.addEventListener('change', async () => {
    ratingControl.disabled = true;
    try {
      await musicApi.rate(row.id, Number(ratingControl.value));
      notify('Ocena zapisana.');
    } catch (error) {
      notify(error.message);
    } finally {
      ratingControl.disabled = false;
    }
  });
  ratingMount?.appendChild(ratingControl);
  if (!releaseDialog.open) releaseDialog.showModal();
}

async function navigate(view, { push = true } = {}) {
  view = view === 'import' ? 'imports' : view;
  if (!labels[view]) view = 'overview';
  state.view = view;
  savePreferences();
  if (push) history.replaceState(null, '', `#${view}`);
  document.querySelectorAll('.music-nav button').forEach((button) => button.classList.toggle('is-active', button.dataset.musicView === view));
  if (actualHeading) actualHeading.textContent = labels[view];
  renderTopbarActions(view);
  content.innerHTML = '<div class="music-loading">Ładowanie…</div>';
  delete content.dataset.rankingId;
  try {
    if (view === 'overview') await renderOverview();
    if (view === 'library') await renderLibrary();
    if (view === 'genres') await renderGenres();
    if (view === 'rankings') await renderRankings();
    if (view === 'lists') await renderLists();
    if (view === 'history') await renderHistory();
    if (view === 'imports') await renderImport();
    return true;
  } catch (error) {
    showError(error);
    return false;
  }
}

document.addEventListener('click', async (event) => {
  const nav = event.target.closest('.music-nav button, [data-view-jump], [data-open-view]');
  if (nav) { navigate(nav.dataset.musicView || nav.dataset.viewJump || nav.dataset.openView); return; }
  const artist = event.target.closest('[data-artist-filter]');
  if (artist) {
    state.libraryFilters = { limit: 50, q: artist.dataset.artistFilter, ids: artist.dataset.artistReleases };
    state.libraryOffset = 0;
    savePreferences();
    navigate('library');
    return;
  }
  const artistPage = event.target.closest('[data-artist-page]');
  if (artistPage) {
    state.artistRankingOffset = Math.max(0, state.artistRankingOffset + (artistPage.dataset.artistPage === 'next' ? 100 : -100));
    savePreferences();
    renderRankings().catch(showError);
    return;
  }
  const syncLegacy = event.target.closest('[data-sync-legacy]');
  if (syncLegacy) {
    try {
      const result = await busy(syncLegacy, () => musicApi.syncLegacy());
      notify(`Katalog odświeżony. Okładki: ${result.covers?.matched || 0}, poprawione rekordy: ${result.metadata?.updated || 0}.`);
      await renderOverview();
    } catch (error) { notify(error.message); }
    return;
  }
  const fetchMissing = event.target.closest('[data-fetch-missing-covers]');
  if (fetchMissing) {
    try {
      const result = await busy(fetchMissing, () => musicApi.fetchMissingCovers(25));
      notify(`Dodano ${result.queued || 0} albumów do kolejki.`);
      await renderLibrary();
    } catch (error) { notify(error.message); }
    return;
  }
  const fetchCover = event.target.closest('[data-fetch-cover]');
  if (fetchCover) {
    try {
      const result = await busy(fetchCover, () => musicApi.fetchCover(fetchCover.dataset.fetchCover));
      notify(result.status === 'pending' ? 'Album dodany do kolejki uzupełniania.' : 'Nie udało się dodać albumu do kolejki.');
    } catch (error) { notify(error.message); }
    return;
  }
  const artworkEdit = event.target.closest('[data-art-kind]');
  if (artworkEdit) {
    event.preventDefault();
    event.stopPropagation();
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/*';
    picker.addEventListener('change', async () => {
      const file = picker.files?.[0];
      if (!file) return;
      artworkEdit.disabled = true;
      artworkEdit.classList.add('is-busy');
      try {
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(reader.error || new Error('Nie udało się odczytać grafiki.'));
          reader.readAsDataURL(file);
        });
        await musicApi.uploadArtwork(artworkEdit.dataset.artKind, artworkEdit.dataset.artKey, dataUrl);
        state.artworkRevision = Date.now();
        notify('Grafika zapisana i dopasowana do formatu 16:9.');
        if (state.view === 'genres') await renderGenres();
        if (state.view === 'overview') await renderOverview();
      } catch (error) {
        notify(error.message);
      } finally {
        artworkEdit.disabled = false;
        artworkEdit.classList.remove('is-busy');
      }
    }, { once: true });
    picker.click();
    return;
  }
  if (event.target.closest('[data-clear-genre-search]')) {
    state.genreQuery = '';
    savePreferences();
    renderGenres().catch(showError);
    return;
  }
  if (event.target.closest('[data-reset-library-filters]')) {
    state.libraryFilters = { limit: 50, sort: 'my_desc' };
    state.libraryOffset = 0;
    savePreferences();
    renderLibrary().catch(showError);
    return;
  }
  const focusRanking = event.target.closest('[data-focus-create-ranking]');
  if (focusRanking) {
    document.querySelector('#music-create-ranking input')?.focus();
    return;
  }
  const focusList = event.target.closest('[data-focus-create-list]');
  if (focusList) {
    document.querySelector('#music-create-list input')?.focus();
    return;
  }
  const genreSummary = event.target.closest('summary');
  if (genreSummary?.parentElement?.matches('.music-genre-branch') && !event.target.closest('button')) {
    const branch = genreSummary.parentElement;
    const wasOpen = branch.open;
    setTimeout(() => {
      if (!wasOpen && !branch.open) branch.open = true;
      if (!wasOpen) hydrateGenreBranch(branch);
    }, 0);
  }
  const release = event.target.closest('[data-release-id]');
  if (release && !event.target.closest('.music-ranking-controls')) { openRelease(release.dataset.releaseId).catch(showError); return; }
  const genre = event.target.closest('[data-genre-id]');
  if (genre) { openGenre(genre.dataset.genreId).catch(showError); return; }
  const ranking = event.target.closest('[data-ranking-id]');
  if (ranking) { openRanking(ranking.dataset.rankingId).catch(showError); return; }
  if (event.target.closest('[data-back-genres]')) { renderGenres().catch(showError); return; }
  if (event.target.closest('[data-back-rankings]')) { renderRankings().catch(showError); return; }
  const createGenre = event.target.closest('[data-create-for-genre]');
  if (createGenre) {
    const result = await musicApi.createRanking({ name: `Mój ranking ${createGenre.dataset.name}`, genreId: Number(createGenre.dataset.createForGenre) });
    await openRanking(result.ranking.id); return;
  }
  const page = event.target.closest('[data-page]');
  if (page) { state.libraryOffset = Math.max(0, state.libraryOffset + (page.dataset.page === 'next' ? 50 : -50)); savePreferences(); renderLibrary().catch(showError); return; }
  const period = event.target.closest('[data-history-period]');
  if (period) { state.historyOffset = 0; savePreferences(); renderHistory(period.dataset.historyPeriod).catch(showError); return; }
  const historyPage = event.target.closest('[data-history-page]');
  if (historyPage) { state.historyOffset = Math.max(0, state.historyOffset + (historyPage.dataset.historyPage === 'next' ? state.historyLimit : -state.historyLimit)); savePreferences(); renderHistory(state.historyPeriod).catch(showError); return; }
  const missingPage = event.target.closest('[data-missing-page]');
  if (missingPage) { state.missingOffset = Math.max(0, state.missingOffset + (missingPage.dataset.missingPage === 'next' ? state.missingLimit : -state.missingLimit)); renderImport().catch(showError); return; }
  if (event.target.closest('[data-import-reset]')) { state.currentImport = null; renderImport().catch(showError); return; }
  const findImportMatch = event.target.closest('[data-import-find]');
  if (findImportMatch) {
    const query = window.prompt('Szukaj w katalogu kanonicznym (artysta lub tytuł):');
    if (!query) return;
    const result = await musicApi.search(query, 10);
    if (!result.releases?.length) { notify('Brak pasujących albumów w katalogu.'); return; }
    const choices = result.releases.map((row) => `${row.id}: ${row.artist_credit} — ${row.title} (${row.release_year || '—'})`).join('\n');
    const selected = window.prompt(`Podaj ID albumu:\n\n${choices}`);
    const candidate = result.releases.find((row) => String(row.id) === String(selected || '').trim());
    if (!candidate) { notify('Nie wybrano prawidłowego ID.'); return; }
    const select = document.querySelector(`[data-import-resolution="${findImportMatch.dataset.importFind}"]`);
    const option = new Option(`Połącz: ${candidate.artist_credit} — ${candidate.title}`, `match:${candidate.id}`, true, true);
    select?.add(option);
    return;
  }
  const commit = event.target.closest('[data-import-commit]');
  if (commit) {
    const resolutions = {};
    document.querySelectorAll('[data-import-resolution]').forEach((select) => {
      const [action, releaseId] = select.value.split(':');
      resolutions[select.dataset.importResolution] = { action, ...(releaseId ? { releaseId: Number(releaseId) } : {}) };
    });
    try {
      const result = await busy(commit, () => musicApi.commitImport(state.currentImport.id, resolutions));
      notify(`Import zakończony: ${result.created ?? result.genres ?? 0} nowych, ${result.matched ?? 0} dopasowanych.`);
      const refreshed = await musicApi.importBatch(state.currentImport.id);
      renderImportPreview(refreshed);
    } catch (error) { notify(error.message); }
    return;
  }
  const move = event.target.closest('[data-rank-move]');
  const remove = event.target.closest('[data-rank-remove]');
  if (move || remove) {
    const rankingId = content.dataset.rankingId;
    const row = event.target.closest('tr');
    const current = Number(row?.firstElementChild?.textContent?.trim() || 1);
    const payload = remove ? { action: 'remove', releaseId: Number(remove.dataset.id) } : { action: 'move', releaseId: Number(move.dataset.id), position: Math.max(1, current + (move.dataset.rankMove === 'up' ? -1 : 1)) };
    await musicApi.rankingEntry(rankingId, payload); await openRanking(rankingId); return;
  }
  const modalGenre = event.target.closest('[data-modal-genre]');
  if (modalGenre) { releaseDialog.close(); navigate('genres'); await openGenre(modalGenre.dataset.modalGenre); return; }
  const modalRanking = event.target.closest('[data-modal-ranking]');
  if (modalRanking) { releaseDialog.close(); navigate('rankings'); await openRanking(modalRanking.dataset.modalRanking); }
});

document.addEventListener('submit', async (event) => {
  if (event.target === searchForm) {
    event.preventDefault();
    const query = searchInput.value.trim();
    if (!query) { searchPanel.hidden = true; return; }
    try {
      const data = await musicApi.search(query);
      const groups = [
        ['Albumy', data.releases, (row) => `<button class="music-search-result" data-search-release="${row.id}">${esc(row.artist_credit)} — <strong>${esc(row.title)}</strong></button>`],
        ['Gatunki', data.genres, (row) => `<button class="music-search-result" data-search-genre="${row.id}">${esc(row.name)}</button>`],
        ['Rankingi', data.rankings, (row) => `<button class="music-search-result" data-search-ranking="${row.id}">${esc(row.name)}</button>`],
        ['Listy', data.lists, (row) => `<span class="music-search-result">${esc(row.name)}</span>`],
      ].filter(([, rows]) => rows?.length);
      searchPanel.innerHTML = groups.map(([label, rows, renderer]) => `<section class="music-search-group"><h3>${label}</h3>${rows.map(renderer).join('')}</section>`).join('') || '<p>Brak wyników.</p>';
      searchPanel.hidden = false;
    } catch (error) { notify(error.message); }
    return;
  }
  if (event.target.id === 'music-library-filters') {
    event.preventDefault();
    const form = new FormData(event.target);
    state.libraryFilters = Object.fromEntries(form);
    state.libraryFilters.showRated = form.has('showRated') ? '1' : '0';
    state.libraryFilters.showUnrated = form.has('showUnrated') ? '1' : '0';
    if (state.libraryFilters.showRated === '0') delete state.libraryFilters.rating;
    state.libraryFilters.limit = 50; state.libraryOffset = 0; savePreferences(); renderLibrary().catch(showError); return;
  }
  if (event.target.id === 'music-artist-filters') {
    event.preventDefault();
    state.artistRankingMin = Number(event.target.querySelector('#music-artist-min-ratings').value);
    state.artistRankingSort = event.target.querySelector('#music-artist-ranking-sort').value;
    state.artistYearFilters = Object.fromEntries(new FormData(event.target));
    state.artistRankingOffset = 0;
    savePreferences();
    renderRankings().catch(showError);
    return;
  }
  const queueEnrichment = event.target.closest('[data-queue-enrichment]');
  if (queueEnrichment) {
    try {
      const result = await busy(queueEnrichment, () => musicApi.queueEnrichment(50));
      notify(`Dodano ${result.queued || 0} albumów do kolejki.`);
      await renderImport();
    } catch (error) { notify(error.message); }
    return;
  }
  if (event.target.id === 'music-genre-search') {
    event.preventDefault();
    const form = new FormData(event.target);
    state.genreQuery = form.get('q') || '';
    state.genreSort = form.get('sort') || 'name';
    savePreferences();
    renderGenres().catch(showError);
    return;
  }
  if (event.target.id === 'music-missing-filter') {
    event.preventDefault();
    state.missingField = new FormData(event.target).get('field') || '';
    state.missingOffset = 0;
    renderImport().catch(showError);
    return;
  }
  if (event.target.id === 'music-create-ranking') {
    event.preventDefault(); const name = new FormData(event.target).get('name');
    try { await musicApi.createRanking({ name }); notify('Ranking utworzony.'); await renderRankings(); } catch (error) { notify(error.message); } return;
  }
  if (event.target.id === 'music-create-list') {
    event.preventDefault(); const data = Object.fromEntries(new FormData(event.target));
    try { await musicApi.createList(data); notify('Lista utworzona.'); await renderLists(); } catch (error) { notify(error.message); } return;
  }
  if (event.target.id === 'music-ranking-add') {
    event.preventDefault(); const query = new FormData(event.target).get('q'); const data = await musicApi.search(query, 10);
    const mount = document.querySelector('#music-ranking-candidates');
    mount.innerHTML = (data.releases || []).map((row) => `<button type="button" class="music-search-result" data-add-ranking-release="${row.id}">${esc(row.artist_credit)} — <strong>${esc(row.title)}</strong></button>`).join('') || '<p>Brak wyników.</p>'; return;
  }
  const rating = event.target.closest('[data-rating-form]');
  if (rating) {
    event.preventDefault(); const value = new FormData(rating).get('rating'); if (!value) return;
    try { await musicApi.rate(rating.dataset.ratingForm, Number(value)); notify('Ocena zapisana.'); } catch (error) { notify(error.message); } return;
  }
  const list = event.target.closest('[data-list-add]');
  if (list) {
    event.preventDefault(); const listId = new FormData(list).get('listId');
    try { await musicApi.listEntry(listId, { action: 'add', releaseId: Number(list.dataset.listAdd) }); notify('Dodano do listy.'); } catch (error) { notify(error.message); }
  }
});

function hydrateGenreBranch(branch) {
  if (!branch?.open) return;
  const mount = [...branch.children].find((child) => child.matches('[data-genre-children]'));
  if (!mount || mount.dataset.loaded === 'true') return;
  const path = String(branch.dataset.genrePath || '').split(',').filter(Boolean).map(Number);
  const childRows = (state.genreTree?.children.get(Number(branch.dataset.genreBranch)) || [])
    .map((id) => state.genreTree.byId.get(id)).filter(Boolean);
  mount.innerHTML = genreSort(childRows).map((row) => genreBranchMarkup(row.id, path)).join('');
  mount.dataset.loaded = 'true';
}

content?.addEventListener('toggle', (event) => {
  const branch = event.target.closest('[data-genre-branch]');
  hydrateGenreBranch(branch);
}, true);

document.addEventListener('click', async (event) => {
  const release = event.target.closest('[data-search-release]');
  if (release) { searchPanel.hidden = true; await openRelease(release.dataset.searchRelease); return; }
  const genre = event.target.closest('[data-search-genre]');
  if (genre) { searchPanel.hidden = true; await navigate('genres'); await openGenre(genre.dataset.searchGenre); return; }
  const ranking = event.target.closest('[data-search-ranking]');
  if (ranking) { searchPanel.hidden = true; await navigate('rankings'); await openRanking(ranking.dataset.searchRanking); return; }
  const add = event.target.closest('[data-add-ranking-release]');
  if (add) { const id = content.dataset.rankingId; await musicApi.rankingEntry(id, { action: 'add', releaseId: Number(add.dataset.addRankingRelease) }); await openRanking(id); }
});

async function handleFile(file) {
  if (!file) return;
  const status = document.querySelector('#music-import-status');
  try {
    if (status) status.textContent = `Czytam ${file.name}…`;
    const html = await file.text();
    const payload = await musicApi.previewImport({ filename: file.name, html, capturedAt: new Date(file.lastModified).toISOString() });
    renderImportPreview(payload);
  } catch (error) { if (status) status.textContent = error.message; else notify(error.message); }
}

document.addEventListener('change', async (event) => {
  if (event.target.matches('[data-music-year-filter] [name="yearMode"]')) {
    updateYearFilterVisibility(event.target.closest('[data-music-year-filter]'));
    return;
  }
  if (event.target.name === 'showRated' && event.target.closest('#music-library-filters')) {
    const rating = event.target.form.querySelector('[name="rating"]');
    rating.disabled = !event.target.checked;
    if (!event.target.checked) rating.value = '';
    return;
  }
  if (event.target.id === 'music-import-file') {
    handleFile(event.target.files?.[0]);
    return;
  }
  const upload = event.target.closest('[data-upload-cover]');
  const file = upload?.files?.[0];
  if (!upload || !file) return;
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error || new Error('Nie udało się odczytać pliku.'));
      reader.readAsDataURL(file);
    });
    await musicApi.uploadCover(upload.dataset.uploadCover, dataUrl);
    notify('Okładka zapisana.');
    await openRelease(upload.dataset.uploadCover);
  } catch (error) { notify(error.message); }
});
document.addEventListener('error', (event) => {
  if (event.target.matches?.('[data-manual-art]')) event.target.remove();
}, true);
document.addEventListener('dragover', (event) => { const drop = event.target.closest('#music-import-drop'); if (drop) { event.preventDefault(); drop.classList.add('is-dragging'); } });
document.addEventListener('dragleave', (event) => event.target.closest('#music-import-drop')?.classList.remove('is-dragging'));
document.addEventListener('drop', (event) => { const drop = event.target.closest('#music-import-drop'); if (drop) { event.preventDefault(); drop.classList.remove('is-dragging'); handleFile(event.dataTransfer.files?.[0]); } });
document.querySelector('[data-close-dialog]')?.addEventListener('click', () => releaseDialog.close());
releaseDialog?.addEventListener('click', (event) => { if (event.target === releaseDialog) releaseDialog.close(); });
releaseDialog?.addEventListener('close', () => { if (state.view === 'imports') renderImport().catch(showError); });
window.addEventListener('hashchange', () => navigate(location.hash.replace('#', ''), { push: false }));

navigate(state.view, { push: false }).then((ready) => {
  const connection = document.querySelector('#music-connection');
  connection?.classList.toggle('is-ok', ready);
  const status = connection?.querySelector('strong');
  if (status) status.textContent = ready ? 'Katalog lokalny gotowy' : 'API niedostępne — uruchom ponownie server.py';
});
