import {
  addComposer,
  fetchClassicalLibrary,
  flattenWorks,
  getClassicalDataSource,
  importComposerWorks,
  refreshComposerProfile,
  refreshComposerWorks,
  searchComposerCandidates,
  updateComposerMetadata,
  uploadComposerImage,
  updateWorkMetadata,
  updateWorkProgress,
} from './classical-library-api.js';
import {
  spotifyMarkMarkup,
  spotifySearchUrl,
  youtubeMarkMarkup,
  youtubeSearchUrl,
} from './spotify-link.js';
import { lucideIconMarkup } from './lucide-classical-icons.js';

const $ = (id) => document.getElementById(id);
const BASE_URL = String(
  import.meta.env?.BASE_URL ||
  (window.location.pathname.startsWith('/cleaning-dashboard/') ? '/cleaning-dashboard/' : '/')
);

const STATUSES = ['Not listened', 'In progress', 'Listened', 'Revisit', 'Skipped'];
const REACTIONS = [
  ['', ''],
  ['❤️', '❤️ Loved'],
  ['👍', '👍 Liked'],
  ['😐', '😐 Neutral'],
  ['👎', '👎 Not for me'],
  ['🧠', '🧠 Interesting'],
  ['🌙', '🌙 Mood piece'],
  ['🧊', '🧊 Cold / elegant'],
  ['🌀', '🌀 Strange / experimental'],
  ['🔁', '🔁 Return to this'],
  ['⭐', '⭐ Standout'],
];
const BASE_CATEGORIES = [
  'Solo Piano',
  'Solo Instrument',
  'Solo Instrument(s) and Orchestra',
  'Chamber',
  'Soloist(s) + Orchestra',
  'Orchestral',
  'Stage',
  'Stage / Ballet / Opera',
  'Vocal',
  'Choral',
  'Arrangement / Orchestration',
  'Other',
];
const VERSIONS = [
  'original',
  'piano version',
  'orchestral version',
  'two pianos version',
  'piano four hands version',
  'arrangement by another person',
  'suite',
  'other',
];

const DEFAULT_CATEGORY_ORDER = [
  'Solo Piano',
  'Solo Instrument',
  'Solo Instrument(s) and Orchestra',
  'Chamber',
  'Soloist(s) + Orchestra',
  'Orchestral',
  'Stage',
  'Stage / Ballet / Opera',
  'Vocal',
  'Choral',
  'Arrangement / Orchestration',
  'Other',
];

const state = {
  composers: [],
  progress: {},
  knownComposers: [],
  summary: {},
  query: '',
  selectedComposerId: readComposerFromLocation(),
  category: 'all',
  status: 'all',
  reaction: 'all',
  listened: 'all',
  review: 'all',
  hidden: 'visible',
  sort: 'source',
  expanded: new Set(),
  currentWork: null,
  currentComposer: null,
};

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function assetUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^(https?:|data:|blob:)/i.test(raw)) return raw;
  if (raw.startsWith('/assets/')) {
    return `${BASE_URL.replace(/\/?$/, '/')}${raw.slice(1)}`;
  }
  return raw;
}

function readComposerFromLocation() {
  try {
    const pretty = window.location.pathname.match(/\/classical-library\/composer\/([^/]+)/);
    if (pretty) return decodeURIComponent(pretty[1]);
    return new URLSearchParams(window.location.search).get('composer') || null;
  } catch {
    return null;
  }
}

function setStatus(text) {
  const el = $('classical-status');
  if (el) el.textContent = text || '';
}

function formatYearRange(composer) {
  const birth = String(composer?.birthDate || '').slice(0, 4);
  const death = String(composer?.deathDate || '').slice(0, 4);
  return [birth, death].filter(Boolean).join('-') || 'Dates unknown';
}

function composerImage(composer) {
  return assetUrl(composer?.image?.localFile || '');
}

function progressFor(workId) {
  return state.progress?.[workId] || {};
}

function listenedCount(composer) {
  return flattenWorks(composer).filter((work) => ['Listened', 'Revisit'].includes(progressFor(work.workId).status)).length;
}

function workCount(composer, includeHidden = false) {
  return flattenWorks(composer).filter((work) => includeHidden || !work.hidden).length;
}

function findComposer(id = state.selectedComposerId) {
  return state.composers.find((item) => item.composerId === id) || null;
}

function findWork(composer, workId) {
  return flattenWorks(composer).find((work) => work.workId === workId) || null;
}

function selectOptions(options, value) {
  return options.map((item) => `<option value="${esc(item)}"${item === value ? ' selected' : ''}>${esc(item)}</option>`).join('');
}

function uniqueValues(values) {
  const out = [];
  values.forEach((value) => {
    const text = String(value || '').trim();
    if (text && !out.includes(text)) out.push(text);
  });
  return out;
}

function sourceCategoryOrder(composer) {
  const groups = composer?.sourceCatalogue?.groups;
  if (Array.isArray(groups) && groups.length) {
    return groups.map((group) => group?.name).filter(Boolean);
  }
  return uniqueValues((composer?.works || []).map((work) => work.sourceCategory || work.displayCategory || work.category));
}

function categorySortIndex(composer, category) {
  const sourceIndex = sourceCategoryOrder(composer).indexOf(category);
  if (sourceIndex >= 0) return sourceIndex;
  const defaultIndex = DEFAULT_CATEGORY_ORDER.indexOf(category);
  return defaultIndex >= 0 ? defaultIndex + 1000 : 9999;
}

function categoryOptionsForComposer(composer) {
  const fromWorks = flattenWorks(composer).map((work) => work.displayCategory || work.category || work.sourceCategory);
  const merged = uniqueValues([...sourceCategoryOrder(composer), ...fromWorks, ...BASE_CATEGORIES, state.category]);
  return merged.sort((a, b) => {
    const ai = categorySortIndex(composer, a);
    const bi = categorySortIndex(composer, b);
    if (ai !== bi) return ai - bi;
    return a.localeCompare(b);
  });
}

function reactionOptions(value) {
  return REACTIONS.map(([emoji, label]) => `<option value="${esc(emoji)}"${emoji === (value || '') ? ' selected' : ''}>${esc(label || '-')}</option>`).join('');
}

function rowMatches(work) {
  const p = progressFor(work.workId);
  if (state.category !== 'all' && work.displayCategory !== state.category) return false;
  if (state.status !== 'all' && (p.status || 'Not listened') !== state.status) return false;
  if (state.reaction !== 'all' && (p.reaction || '') !== state.reaction) return false;
  if (state.listened === 'listened' && !['Listened', 'Revisit'].includes(p.status)) return false;
  if (state.listened === 'unlistened' && ['Listened', 'Revisit'].includes(p.status)) return false;
  if (state.review === 'needs' && !work.needsReview) return false;
  if (state.review === 'clean' && work.needsReview) return false;
  if (state.hidden === 'visible' && work.hidden) return false;
  if (state.hidden === 'hidden' && !work.hidden) return false;
  return true;
}

function sortRows(rows) {
  const val = (row) => {
    const p = progressFor(row.workId);
    if (state.sort === 'source') return Number(row.sourceOrder || 9999);
    if (state.sort === 'title') return row.title || '';
    if (state.sort === 'category') return row.displayCategory || '';
    const y = String(row.year || '').match(/\d{4}/);
    return y ? Number(y[0]) : 9999;
  };
  return rows.slice().sort((a, b) => {
    const av = val(a);
    const bv = val(b);
    if (typeof av === 'number' || typeof bv === 'number') return av - bv;
    return String(av).localeCompare(String(bv), undefined, { numeric: true });
  });
}

function syncLocation() {
  try {
    const url = new URL(window.location.href);
    if (!state.selectedComposerId) {
      url.searchParams.delete('composer');
      if (url.pathname.includes('/classical-library/composer/')) {
        url.pathname = `${url.pathname.split('/classical-library/')[0]}/classical-library`;
      }
      window.history.replaceState({}, '', url);
      return;
    }
    url.searchParams.set('composer', state.selectedComposerId);
    if (!url.pathname.includes('/classical-library/composer/')) {
      window.history.replaceState({}, '', url);
    }
  } catch {}
}

function renderSourceBadge() {
  const el = $('classical-source');
  if (!el) return;
  el.className = `classical-source is-${getClassicalDataSource()}`;
  el.textContent = getClassicalDataSource() === 'api'
    ? 'Data: local JSON API'
    : 'Data: static seed snapshot (read only)';
}

function renderSummary() {
  const summary = state.summary || {};
  $('classical-kpi-composers').textContent = String(state.composers.length);
  $('classical-kpi-total').textContent = String(summary.totalWorks || 0);
  $('classical-kpi-listened').textContent = String(summary.listenedWorks || 0);
  $('classical-kpi-review').textContent = String(state.composers.flatMap(flattenWorks).filter((work) => work.needsReview).length);
}

function renderComposerList() {
  const view = $('classical-list-view');
  if (!view) return;
  const query = state.query.trim().toLowerCase();
  const composers = state.composers.filter((composer) => {
    const text = `${composer.name || ''} ${composer.bioShort || ''} ${composer.birthPlace || ''}`.toLowerCase();
    return !query || text.includes(query);
  });
  view.innerHTML = `
    <section class="classical-toolbar">
      <div>
        <h2>Composers</h2>
        <div class="meta">${composers.length} shown / ${state.composers.length} in library</div>
      </div>
      <input id="classical-composer-search" class="oscars-input" type="search" placeholder="Search composers" value="${esc(state.query)}">
    </section>
    <section class="classical-composer-grid">
      ${composers.map(renderComposerCard).join('') || '<div class="classical-empty">No composers match this filter.</div>'}
    </section>
  `;
}

function renderComposerCard(composer) {
  const image = composerImage(composer);
  const works = workCount(composer);
  const heard = listenedCount(composer);
  return `
    <article class="classical-composer-card" data-composer-id="${esc(composer.composerId)}">
      <div class="classical-composer-image">${image ? `<img src="${esc(image)}" alt="">` : `<span>${esc((composer.name || '?').slice(0, 1))}</span>`}</div>
      <div class="classical-composer-copy">
        <h3>${esc(composer.name)}</h3>
        <div class="classical-card-meta">${esc(formatYearRange(composer))}</div>
        <p>${esc(composer.bioShort || 'No short bio yet.')}</p>
        <div class="classical-mini-stats">
          <span>${works} works</span>
          <span>${heard} listened</span>
        </div>
        <div class="classical-card-actions">
          <a class="card-cta" href="./classical-library.html?composer=${encodeURIComponent(composer.composerId)}">Open Works</a>
          <button type="button" class="oscars-ghost" data-action="import-works" data-composer-id="${esc(composer.composerId)}">Import RYM HTML</button>
          <button type="button" class="oscars-ghost" data-action="edit-composer" data-composer-id="${esc(composer.composerId)}">Edit composer metadata</button>
        </div>
      </div>
    </article>
  `;
}

function renderDetail() {
  const view = $('classical-detail-view');
  const composer = findComposer();
  if (!view) return;
  if (!composer) {
    view.innerHTML = '';
    return;
  }
  const image = composerImage(composer);
  const works = flattenWorks(composer);
  const sourceText = (composer.sources || []).map((item) => item.name || item.notes).filter(Boolean).join(' / ') || 'Seed/manual metadata';

  view.innerHTML = `
    <section class="classical-detail-hero">
      <div class="classical-detail-image">${image ? `<img src="${esc(image)}" alt="">` : `<span>${esc((composer.name || '?').slice(0, 1))}</span>`}</div>
      <div class="classical-detail-copy">
        <div class="classical-overline">Classical Composer Library</div>
        <h1>${esc(composer.name)}</h1>
        <div class="classical-detail-meta">${esc(formatYearRange(composer))} / ${esc([composer.birthPlace, composer.deathPlace].filter(Boolean).join(' -> '))}</div>
        <p>${esc(composer.bioShort || '')}</p>
        <div class="classical-source-note">${esc(sourceText)}</div>
      </div>
      <div class="classical-detail-actions">
        <button type="button" class="card-cta" data-action="edit-composer" data-composer-id="${esc(composer.composerId)}">Edit composer metadata</button>
        <button type="button" class="oscars-ghost" data-action="refresh-profile" data-composer-id="${esc(composer.composerId)}">Refresh profile</button>
        <button type="button" class="oscars-ghost" data-action="import-works" data-composer-id="${esc(composer.composerId)}">Import RYM HTML</button>
        <button type="button" class="oscars-ghost" data-action="refresh-works" data-composer-id="${esc(composer.composerId)}">Refresh work catalogue</button>
      </div>
    </section>
    <section class="classical-filters">
      <select id="classical-filter-composer" class="oscars-input">${state.composers.map((item) => `<option value="${esc(item.composerId)}"${item.composerId === composer.composerId ? ' selected' : ''}>${esc(item.name)}</option>`).join('')}</select>
      <select id="classical-filter-category" class="oscars-input"><option value="all">All categories</option>${selectOptions(categoryOptionsForComposer(composer), state.category)}</select>
      <select id="classical-filter-status" class="oscars-input"><option value="all">All statuses</option>${selectOptions(STATUSES, state.status)}</select>
      <select id="classical-filter-reaction" class="oscars-input"><option value="all">All reactions</option>${reactionOptions(state.reaction).replace('<option value=""', '<option value="all"')}</select>
      <select id="classical-filter-listened" class="oscars-input">
        <option value="all"${state.listened === 'all' ? ' selected' : ''}>Listened + unlistened</option>
        <option value="listened"${state.listened === 'listened' ? ' selected' : ''}>Listened</option>
        <option value="unlistened"${state.listened === 'unlistened' ? ' selected' : ''}>Not listened</option>
      </select>
      <select id="classical-filter-review" class="oscars-input">
        <option value="all"${state.review === 'all' ? ' selected' : ''}>All review states</option>
        <option value="needs"${state.review === 'needs' ? ' selected' : ''}>Needs review</option>
        <option value="clean"${state.review === 'clean' ? ' selected' : ''}>No review flag</option>
      </select>
      <select id="classical-filter-hidden" class="oscars-input">
        <option value="visible"${state.hidden === 'visible' ? ' selected' : ''}>Visible works</option>
        <option value="hidden"${state.hidden === 'hidden' ? ' selected' : ''}>Hidden works</option>
        <option value="all"${state.hidden === 'all' ? ' selected' : ''}>Visible + hidden</option>
      </select>
      <select id="classical-sort" class="oscars-input">
        <option value="source"${state.sort === 'source' ? ' selected' : ''}>Sort: RYM source order</option>
        <option value="year"${state.sort === 'year' ? ' selected' : ''}>Sort: year</option>
        <option value="title"${state.sort === 'title' ? ' selected' : ''}>Sort: title</option>
        <option value="category"${state.sort === 'category' ? ' selected' : ''}>Sort: category</option>
      </select>
    </section>
    <section class="classical-table-wrap">${renderWorksTable(composer, works)}</section>
  `;
  view.querySelectorAll('.classical-notes-input').forEach(resizeNotesInput);
}

function resizeNotesInput(control) {
  control.style.height = 'auto';
  control.style.height = `${Math.max(control.scrollHeight, 52)}px`;
}

function renderWorksTable(composer, works) {
  const rows = [];
  const topRows = sortRows(works.filter((work) => !work.level && rowMatches(work)));
  topRows.forEach((work) => {
    rows.push(work);
    if (!state.expanded.has(work.workId)) return;
    sortRows(works.filter((part) => part.parentWorkId === work.workId && rowMatches(part)))
      .forEach((part) => rows.push(part));
  });
  const byCategory = new Map();
  rows.forEach((work) => {
    const key = work.displayCategory || work.sourceCategory || work.category || 'Other';
    if (!byCategory.has(key)) byCategory.set(key, []);
    byCategory.get(key).push(work);
  });
  const categories = Array.from(byCategory.keys()).sort((a, b) => {
    if (state.sort === 'source') {
      return categorySortIndex(composer, a) - categorySortIndex(composer, b);
    }
    const ai = DEFAULT_CATEGORY_ORDER.indexOf(a);
    const bi = DEFAULT_CATEGORY_ORDER.indexOf(b);
    if (ai !== -1 || bi !== -1) return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    return a.localeCompare(b);
  });
  if (!rows.length) return '<div class="classical-empty">No works match these filters.</div>';

  return `
    <table class="classical-works-table">
      <colgroup>
        <col class="classical-col-year"><col class="classical-col-role"><col class="classical-col-title">
        <col class="classical-col-catalogue"><col class="classical-col-category"><col class="classical-col-version">
        <col class="classical-col-status"><col class="classical-col-reaction"><col class="classical-col-notes">
        <col class="classical-col-actions">
      </colgroup>
      <thead>
        <tr>
          <th>Year</th><th>Role</th><th>Title</th><th>Catalogue</th><th>Category</th><th>Version</th>
          <th>Status</th><th>Reaction</th><th>Notes</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${categories.map((category) => `
          <tr class="classical-group-row"><td colspan="10">${esc(category)} <span>${byCategory.get(category).length}</span></td></tr>
          ${byCategory.get(category).map((work) => renderWorkRow(composer, work)).join('')}
        `).join('')}
      </tbody>
    </table>
  `;
}

function renderWorkRow(composer, work) {
  const p = progressFor(work.workId);
  const hasParts = Array.isArray(work.parts) && work.parts.length > 0;
  const expanded = state.expanded.has(work.workId);
  const indent = Number(work.level || 0);
  const role = String(work.sourceRole || work.role || '').replace(/\s*,\s*/g, ', ');
  const category = work.displayCategory || work.category || '';
  return `
    <tr class="${work.hidden ? 'is-hidden' : ''} ${work.needsReview || Number(work.normalizationConfidence || 1) < 0.8 ? 'needs-review' : ''}" data-work-id="${esc(work.workId)}" data-composer-id="${esc(composer.composerId)}">
      <td data-label="Year" title="${esc(work.year || '')}">${esc(work.year || '')}</td>
      <td data-label="Role" class="classical-role-cell" title="${esc(role)}">${esc(role)}</td>
      <td data-label="Title" class="classical-title-cell">
        <div class="classical-title-inner" style="--indent:${indent}">
        ${hasParts ? `<button type="button" class="classical-expand" data-action="toggle-parts" data-work-id="${esc(work.workId)}">${expanded ? '−' : '+'}</button>` : '<span class="classical-expand-spacer"></span>'}
        ${Number(work.normalizationConfidence || 1) < 0.8 || work.needsReview ? '<span class="classical-warning" title="Needs metadata review">!</span>' : ''}
          <span class="classical-title-text" title="${esc(work.title || '')}">${esc(work.title || '')}</span>
        </div>
      </td>
      <td data-label="Catalogue" title="${esc(work.catalogue || '')}">${esc(work.catalogue || '')}</td>
      <td data-label="Category" title="${esc(category)}">${esc(category)}</td>
      <td data-label="Version" title="${esc(work.version || '')}">${esc(work.version || '')}</td>
      <td data-label="Status" class="classical-status-cell"><select class="classical-progress-control classical-status-select" data-progress-field="status">${selectOptions(STATUSES, p.status || 'Not listened')}</select></td>
      <td data-label="Reaction" class="classical-reaction-cell"><select class="classical-progress-control classical-reaction-select" data-progress-field="reaction">${reactionOptions(p.reaction)}</select></td>
      <td data-label="Notes" class="classical-notes-cell"><textarea class="classical-progress-control classical-notes-input" data-progress-field="notes" rows="2" placeholder="Notes">${esc(p.notes || '')}</textarea></td>
      <td data-label="Actions" class="classical-row-actions">
        <div class="classical-row-actions-inner">
          <div class="classical-media-actions">
            <a class="media-icon-action spotify-icon-action classical-spotify-action" href="${esc(spotifySearchUrl(composer.name, work.title))}" target="_blank" rel="noopener" title="Search on Spotify" aria-label="${esc(`Search on Spotify: ${composer.name} - ${work.title}`)}">${spotifyMarkMarkup()}</a>
            <a class="media-icon-action youtube-icon-action classical-youtube-action" href="${esc(youtubeSearchUrl(composer.name, work.title))}" target="_blank" rel="noopener" title="Search on YouTube" aria-label="${esc(`Search on YouTube: ${composer.name} - ${work.title}`)}">${youtubeMarkMarkup()}</a>
          </div>
          <div class="classical-metadata-actions">
            <button type="button" class="oscars-ghost classical-icon-action" data-action="edit-work" title="Edit work" aria-label="Edit work">${lucideIconMarkup('pencil')}</button>
            <button type="button" class="oscars-ghost classical-icon-action" data-action="${work.hidden ? 'restore-work' : 'hide-work'}" title="${work.hidden ? 'Restore work' : 'Hide work'}" aria-label="${work.hidden ? 'Restore work' : 'Hide work'}">${lucideIconMarkup(work.hidden ? 'eye' : 'eye-off')}</button>
          </div>
        </div>
      </td>
    </tr>
  `;
}

function renderAddComposerPanel() {
  const el = $('classical-add-panel');
  if (!el) return;
  el.innerHTML = `
    <div class="classical-add-head">
      <div>
        <h2>Add Composer</h2>
        <div class="meta">Add a profile, upload a portrait, then import a saved RYM Works HTML file.</div>
      </div>
    </div>
    <form id="classical-manual-add-form" class="classical-manual-add-form">
      <input class="oscars-input" name="name" required placeholder="Composer name">
      <input class="oscars-input" name="composerId" placeholder="Optional id, e.g. frederic-mompou">
      <input class="oscars-input" name="birthDate" placeholder="Birth date">
      <input class="oscars-input" name="deathDate" placeholder="Death date">
      <input class="oscars-input" name="birthPlace" placeholder="Birth place">
      <input class="oscars-input" name="deathPlace" placeholder="Death place">
      <textarea class="oscars-input" name="bioShort" placeholder="Short description"></textarea>
      <label class="classical-upload-field">Profile image<input class="oscars-input" name="profileImage" type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"></label>
      <button class="card-cta" type="submit">Add profile</button>
    </form>
    <form id="classical-add-form" class="classical-add-form">
      <input id="classical-add-query" class="oscars-input" type="search" placeholder="Search composer by name">
      <button class="card-cta" type="submit">Search</button>
    </form>
    <div id="classical-add-results" class="classical-add-results"></div>
  `;
}

function renderAll() {
  renderSourceBadge();
  renderSummary();
  renderComposerList();
  renderDetail();
  renderAddComposerPanel();
  const list = $('classical-list-view');
  const detail = $('classical-detail-view');
  if (list) list.hidden = !!state.selectedComposerId;
  if (detail) detail.hidden = !state.selectedComposerId;
  if (detail && !detail.hidden) {
    detail.querySelectorAll('.classical-notes-input').forEach(resizeNotesInput);
  }
  const back = $('classical-back-library');
  if (back) back.hidden = !state.selectedComposerId;
  syncLocation();
}

function openComposerModal(composer) {
  state.currentComposer = composer;
  const image = composer.image || {};
  $('classical-modal-root').innerHTML = `
    <div class="classical-modal-backdrop" data-action="close-modal"></div>
    <form class="classical-modal" id="classical-composer-form">
      <h2>Edit composer metadata</h2>
      <label>Name<input class="oscars-input" name="name" value="${esc(composer.name)}"></label>
      <div class="classical-form-grid">
        <label>Birth date<input class="oscars-input" name="birthDate" value="${esc(composer.birthDate)}"></label>
        <label>Death date<input class="oscars-input" name="deathDate" value="${esc(composer.deathDate)}"></label>
        <label>Birth place<input class="oscars-input" name="birthPlace" value="${esc(composer.birthPlace)}"></label>
        <label>Death place<input class="oscars-input" name="deathPlace" value="${esc(composer.deathPlace)}"></label>
      </div>
      <label>Image file<input class="oscars-input" name="image.localFile" value="${esc(image.localFile)}"></label>
      <label class="classical-upload-field">Upload profile image<input class="oscars-input" name="profileImage" type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"></label>
      <label>Image source<input class="oscars-input" name="image.source" value="${esc(image.source)}"></label>
      <label>Image source URL<input class="oscars-input" name="image.sourceUrl" value="${esc(image.sourceUrl)}"></label>
      <label>Image license<input class="oscars-input" name="image.license" value="${esc(image.license)}"></label>
      <label>Short bio<textarea class="oscars-input" name="bioShort">${esc(composer.bioShort)}</textarea></label>
      <div class="classical-modal-actions">
        <button class="card-cta" type="submit">Save</button>
        <button class="oscars-ghost" type="button" data-action="close-modal">Cancel</button>
      </div>
    </form>
  `;
}

function openRymImportModal(composer) {
  state.currentComposer = composer;
  $('classical-modal-root').innerHTML = `
    <div class="classical-modal-backdrop" data-action="close-modal"></div>
    <form class="classical-modal classical-modal--wide" id="classical-rym-import-form">
      <h2>Import RYM saved HTML</h2>
      <div class="classical-source-note">Composer: ${esc(composer.name)}. Use a saved RateYourMusic artist page; the importer reads only the local file you choose.</div>
      <label class="classical-upload-field">Saved RYM HTML<input class="oscars-input" name="rymHtml" type="file" accept=".html,.htm,text/html" required></label>
      <pre id="classical-rym-import-output" class="classical-import-output"></pre>
      <div class="classical-modal-actions">
        <button class="oscars-ghost" type="submit" data-import-mode="preview">Preview</button>
        <button class="card-cta" type="submit" data-import-mode="import">Import</button>
        <button class="oscars-ghost" type="button" data-action="close-modal">Cancel</button>
      </div>
    </form>
  `;
}

function openWorkModal(composer, work) {
  state.currentComposer = composer;
  state.currentWork = work;
  const otherWorks = flattenWorks(composer).filter((item) => item.workId !== work.workId);
  const instrumentation = Array.isArray(work.instrumentation)
    ? work.instrumentation.join(', ')
    : String(work.instrumentation || '');
  $('classical-modal-root').innerHTML = `
    <div class="classical-modal-backdrop" data-action="close-modal"></div>
    <form class="classical-modal classical-modal--wide" id="classical-work-form">
      <h2>Edit work metadata</h2>
      <label>Title<input class="oscars-input" name="title" value="${esc(work.title)}"></label>
      <div class="classical-form-grid">
        <label>Year<input class="oscars-input" name="year" value="${esc(work.year)}"></label>
        <label>Catalogue<input class="oscars-input" name="catalogue" value="${esc(work.catalogue)}"></label>
        <label>Category<select class="oscars-input" name="category">${selectOptions(categoryOptionsForComposer(composer).filter((item) => item !== 'Solo Piano'), work.category || 'Other')}</select></label>
        <label>Version<select class="oscars-input" name="version">${selectOptions(VERSIONS, work.version || 'original')}</select></label>
      </div>
      <label>Instrumentation<input class="oscars-input" name="instrumentation" value="${esc(instrumentation)}"></label>
      <div class="classical-check-row">
        <label><input type="checkbox" name="isArrangement" ${work.isArrangement ? 'checked' : ''}> Mark as arrangement</label>
        <label><input type="checkbox" name="needsReview" ${work.needsReview ? 'checked' : ''}> Needs review</label>
        <label><input type="checkbox" name="hidden" ${work.hidden ? 'checked' : ''}> Hidden from main table</label>
      </div>
      <div class="classical-form-grid">
        <label>Arranger<input class="oscars-input" name="arrangerName" value="${esc(work.arrangerName || '')}"></label>
        <label>Original work id<input class="oscars-input" name="originalWorkId" value="${esc(work.originalWorkId || '')}"></label>
        <label>Confidence<input class="oscars-input" type="number" min="0" max="1" step="0.01" name="normalizationConfidence" value="${esc(work.normalizationConfidence ?? 0)}"></label>
        <label>Merge duplicate into<select class="oscars-input" name="mergeInto"><option value="">Do not merge</option>${otherWorks.map((item) => `<option value="${esc(item.workId)}">${esc(item.title)} (${esc(item.workId)})</option>`).join('')}</select></label>
      </div>
      <label>Normalization reason<textarea class="oscars-input" name="normalizationReason">${esc(work.normalizationReason || '')}</textarea></label>
      <label>Source notes / metadata quality notes<textarea class="oscars-input" name="sourceNotes">${esc(work.sourceNotes || '')}</textarea></label>
      <div class="classical-modal-actions">
        <button class="card-cta" type="submit">Save</button>
        <button class="oscars-ghost" type="button" data-action="close-modal">Cancel</button>
      </div>
    </form>
  `;
}

function closeModal() {
  $('classical-modal-root').innerHTML = '';
  state.currentComposer = null;
  state.currentWork = null;
}

async function reload() {
  const data = await fetchClassicalLibrary();
  state.composers = Array.isArray(data.composers) ? data.composers : [];
  state.progress = data.progress || {};
  state.knownComposers = data.knownComposers || [];
  state.summary = data.summary || {};
  if (state.selectedComposerId && !findComposer()) state.selectedComposerId = null;
  renderAll();
}

async function saveProgressFromControl(control) {
  const row = control.closest('tr[data-work-id]');
  if (!row) return;
  const workId = row.dataset.workId;
  const field = control.dataset.progressField;
  let value = control.value;
  try {
    const result = await updateWorkProgress(workId, { [field]: value });
    state.progress[workId] = result.progress;
    if (result.summary) state.summary = result.summary;
    setStatus('Saved.');
    renderSummary();
  } catch (error) {
    setStatus(error.message || 'Save failed.');
  }
}

async function handleSearchAdd(query) {
  const results = await searchComposerCandidates(query, 12);
  const root = $('classical-add-results');
  root.innerHTML = results.map((item) => `
    <article class="classical-search-result">
      <div>
        <strong>${esc(item.name)}</strong>
        <span>${esc(formatYearRange(item))}</span>
        <p>${esc(item.bioShort || '')}</p>
      </div>
      <button class="card-cta" type="button" data-action="add-composer" data-composer-payload="${esc(JSON.stringify(item))}" ${item.alreadyInLibrary ? 'disabled' : ''}>${item.alreadyInLibrary ? 'Added' : 'Add composer'}</button>
    </article>
  `).join('') || '<div class="classical-empty">No matches.</div>';
}

async function handleAction(target) {
  const action = target.dataset.action;
  const composerId = target.dataset.composerId || target.closest('[data-composer-id]')?.dataset.composerId;
  const composer = composerId ? findComposer(composerId) : findComposer();
  const row = target.closest('tr[data-work-id]');
  const work = row && composer ? findWork(composer, row.dataset.workId) : null;
  try {
    if (action === 'close-modal') return closeModal();
    if (action === 'edit-composer' && composer) return openComposerModal(composer);
    if (action === 'edit-work' && composer && work) return openWorkModal(composer, work);
    if (action === 'toggle-parts') {
      const workId = target.dataset.workId;
      if (state.expanded.has(workId)) state.expanded.delete(workId);
      else state.expanded.add(workId);
      return renderDetail();
    }
    if ((action === 'hide-work' || action === 'restore-work') && composer && work) {
      const result = await updateWorkMetadata(composer.composerId, work.workId, { hidden: action === 'hide-work' });
      const idx = state.composers.findIndex((item) => item.composerId === composer.composerId);
      if (idx >= 0) state.composers[idx] = result.composer;
      state.summary = result.summary || state.summary;
      setStatus(action === 'hide-work' ? 'Work hidden.' : 'Work restored.');
      return renderAll();
    }
    if (action === 'refresh-profile' && composer) {
      await refreshComposerProfile(composer.composerId);
      setStatus('Profile refresh placeholder ran; manual edits preserved.');
      return reload();
    }
    if (action === 'refresh-works' && composer) {
      await refreshComposerWorks(composer.composerId);
      setStatus('Catalogue refresh placeholder ran; manual edits preserved.');
      return reload();
    }
    if (action === 'import-works' && composer) {
      return openRymImportModal(composer);
    }
    if (action === 'add-composer') {
      const payload = JSON.parse(target.dataset.composerPayload || '{}');
      await addComposer(payload);
      setStatus('Composer added with basic profile only.');
      return reload();
    }
  } catch (error) {
    setStatus(error.message || 'Action failed.');
  }
}

function formDataObject(form) {
  const data = new FormData(form);
  return Object.fromEntries(data.entries());
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',').pop() : value);
    };
    reader.onerror = () => reject(reader.error || new Error('Image read failed'));
    reader.readAsDataURL(file);
  });
}

async function handleComposerForm(form) {
  const raw = formDataObject(form);
  const file = form.elements.profileImage?.files?.[0] || null;
  const patch = {
    name: raw.name,
    birthDate: raw.birthDate,
    deathDate: raw.deathDate,
    birthPlace: raw.birthPlace,
    deathPlace: raw.deathPlace,
    bioShort: raw.bioShort,
    image: {
      localFile: raw['image.localFile'],
      source: raw['image.source'],
      sourceUrl: raw['image.sourceUrl'],
      license: raw['image.license'],
    },
  };
  if (file) {
    setStatus('Uploading profile image...');
    const contentBase64 = await fileToBase64(file);
    const upload = await uploadComposerImage({
      composerId: state.currentComposer.composerId,
      filename: file.name,
      mimeType: file.type,
      contentBase64,
    });
    patch.image = {
      ...(upload.image || {}),
      localFile: upload.image?.localFile || patch.image.localFile,
    };
  }
  const result = await updateComposerMetadata(state.currentComposer.composerId, patch);
  const idx = state.composers.findIndex((item) => item.composerId === state.currentComposer.composerId);
  if (idx >= 0) state.composers[idx] = result.composer;
  state.summary = result.summary || state.summary;
  closeModal();
  renderAll();
  setStatus('Composer metadata saved.');
}

async function handleManualComposerForm(form) {
  const raw = formDataObject(form);
  const file = form.elements.profileImage?.files?.[0] || null;
  const payload = {
    composerId: raw.composerId,
    name: raw.name,
    birthDate: raw.birthDate,
    deathDate: raw.deathDate,
    birthPlace: raw.birthPlace,
    deathPlace: raw.deathPlace,
    bioShort: raw.bioShort,
  };
  setStatus('Adding composer profile...');
  const added = await addComposer(payload);
  const composerId = added.composer?.composerId || payload.composerId;
  if (file && composerId) {
    setStatus('Uploading profile image...');
    const contentBase64 = await fileToBase64(file);
    await uploadComposerImage({
      composerId,
      filename: file.name,
      mimeType: file.type,
      contentBase64,
    });
  }
  state.selectedComposerId = composerId || null;
  await reload();
  setStatus('Composer added. Open Import RYM HTML to add works.');
}

async function handleRymImportForm(form, submitter) {
  const file = form.elements.rymHtml?.files?.[0] || null;
  const output = $('classical-rym-import-output');
  const mode = submitter?.dataset?.importMode || 'preview';
  if (!file) {
    setStatus('Choose a saved RYM HTML file first.');
    return;
  }
  if (!state.currentComposer?.composerId) {
    setStatus('No composer selected for import.');
    return;
  }
  setStatus(mode === 'import' ? 'Importing saved RYM HTML...' : 'Previewing saved RYM HTML...');
  if (output) output.textContent = 'Reading file...';
  const contentBase64 = await fileToBase64(file);
  const result = await importComposerWorks(state.currentComposer.composerId, {
    mode,
    filename: file.name,
    contentBase64,
  });
  if (output) output.textContent = result.output || 'No importer output.';
  if (mode === 'import') {
    closeModal();
    await reload();
    setStatus('RYM works imported. Fuzzy matches were left for manual review.');
  } else {
    setStatus('Preview ready. Nothing was written.');
  }
}

async function handleWorkForm(form) {
  const raw = formDataObject(form);
  const patch = {
    title: raw.title,
    year: raw.year,
    catalogue: raw.catalogue,
    category: raw.category,
    instrumentation: raw.instrumentation,
    version: raw.version,
    isArrangement: form.elements.isArrangement.checked,
    needsReview: form.elements.needsReview.checked,
    hidden: form.elements.hidden.checked,
    arrangerName: raw.arrangerName,
    originalWorkId: raw.originalWorkId,
    normalizationConfidence: raw.normalizationConfidence,
    normalizationReason: raw.normalizationReason,
    sourceNotes: raw.sourceNotes,
    mergeInto: raw.mergeInto,
  };
  const result = await updateWorkMetadata(state.currentComposer.composerId, state.currentWork.workId, patch);
  const idx = state.composers.findIndex((item) => item.composerId === state.currentComposer.composerId);
  if (idx >= 0) state.composers[idx] = result.composer;
  state.summary = result.summary || state.summary;
  closeModal();
  renderAll();
  setStatus('Work metadata saved.');
}

function bindEvents() {
  document.addEventListener('input', (event) => {
    if (event.target?.id === 'classical-composer-search') {
      state.query = event.target.value;
      renderComposerList();
    }
    if (event.target?.classList?.contains('classical-notes-input')) {
      resizeNotesInput(event.target);
    }
  });

  document.addEventListener('change', (event) => {
    const t = event.target;
    if (t.classList?.contains('classical-progress-control')) saveProgressFromControl(t);
    if (t.id === 'classical-filter-composer') {
      state.selectedComposerId = t.value;
      renderAll();
      return;
    }
    const map = {
      'classical-filter-category': 'category',
      'classical-filter-status': 'status',
      'classical-filter-reaction': 'reaction',
      'classical-filter-listened': 'listened',
      'classical-filter-review': 'review',
      'classical-filter-hidden': 'hidden',
      'classical-sort': 'sort',
    };
    if (map[t.id]) {
      state[map[t.id]] = t.value;
      renderDetail();
    }
  });

  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-action]');
    if (action) handleAction(action);
    if (event.target?.id === 'classical-back-library') {
      state.selectedComposerId = null;
      renderAll();
    }
  });

  document.addEventListener('submit', (event) => {
    if (event.target?.id === 'classical-add-form') {
      event.preventDefault();
      handleSearchAdd($('classical-add-query').value).catch((error) => setStatus(error.message));
    }
    if (event.target?.id === 'classical-manual-add-form') {
      event.preventDefault();
      handleManualComposerForm(event.target).catch((error) => setStatus(error.message));
    }
    if (event.target?.id === 'classical-composer-form') {
      event.preventDefault();
      handleComposerForm(event.target).catch((error) => setStatus(error.message));
    }
    if (event.target?.id === 'classical-rym-import-form') {
      event.preventDefault();
      handleRymImportForm(event.target, event.submitter).catch((error) => setStatus(error.message));
    }
    if (event.target?.id === 'classical-work-form') {
      event.preventDefault();
      handleWorkForm(event.target).catch((error) => setStatus(error.message));
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  if (!$('classical-page')) return;
  bindEvents();
  reload().catch((error) => {
    console.error(error);
    setStatus(error.message || 'Failed to load classical library.');
  });
});
