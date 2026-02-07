import {
  fetchOscars,
  updateOscars,
  fetchPosters,
  fetchOscarsDetails,
  fetchOscarsWinners,
  fetchOscarsYears,
  fetchOscarsAll,
  getOscarsFootnote,
  getOscarsMode,
  resolveOscarsMode
} from './oscars-data.js';
import { splitCategories, sortCategories } from './oscars-categories.js';
import { splitCountries } from './oscars-countries.js';

const $ = (id) => document.getElementById(id);

const state = {
  query: '',
  type: 'ALL',
  filter: 'all',
  sort: 'title',
  providers: [],
  categories: [],
  countries: [],
  nominationsMin: null,
  nominationsMax: null,
  winnersOnly: false
};

let DATA_MODE = getOscarsMode();

let OSCARS_YEAR = null;
let AVAILABLE_YEARS = [];

let data = [];
const UI_STATE_KEY = 'oscars_ui_v1';
const ALL_YEARS_VALUE = 'all';
const UI_DEFAULTS = {
  query: '',
  type: 'ALL',
  filter: 'all',
  sort: 'title',
  providers: [],
  categories: [],
  countries: [],
  nominationsMin: null,
  nominationsMax: null,
  winnersOnly: false
};
const YEAR_MIN = 2010;
const YEAR_MAX = 2030;
const YEAR_MIN_ISO = `${YEAR_MIN}-01-01`;
const YEAR_MAX_ISO = `${YEAR_MAX}-12-31`;

function getYearFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get('year');
    if (!raw) return null;
    if (String(raw).toLowerCase() === ALL_YEARS_VALUE) return ALL_YEARS_VALUE;
    const num = Number(raw);
    return Number.isFinite(num) && num > 0 ? num : null;
  } catch {
    return null;
  }
}

function setUrlYear(year, replace = false) {
  if (!Number.isFinite(year) && year !== ALL_YEARS_VALUE) return;
  const url = new URL(window.location.href);
  url.searchParams.set('year', year === ALL_YEARS_VALUE ? ALL_YEARS_VALUE : String(year));
  if (replace) {
    history.replaceState(null, '', url.toString());
  } else {
    history.pushState(null, '', url.toString());
  }
}

function normalizeFilter(value) {
  if (value === 'unwatched') return 'unwatched';
  return 'all';
}

function yearKey(year) {
  if (year === ALL_YEARS_VALUE) return ALL_YEARS_VALUE;
  if (Number.isFinite(year)) return String(year);
  return '';
}

function loadUiState(year) {
  const key = yearKey(year);
  if (!key) return { ...UI_DEFAULTS };
  try {
    const raw = localStorage.getItem(UI_STATE_KEY);
    if (!raw) return { ...UI_DEFAULTS };
    const parsed = JSON.parse(raw);
    const entry = parsed && typeof parsed === 'object' ? parsed[key] : null;
    if (!entry || typeof entry !== 'object') return { ...UI_DEFAULTS };
    const rawMin = entry.nominationsMin;
    const rawMax = entry.nominationsMax;
    const minNum = rawMin === null || rawMin === undefined || rawMin === '' ? null : Number(rawMin);
    const maxNum = rawMax === null || rawMax === undefined || rawMax === '' ? null : Number(rawMax);
    return {
      query: String(entry.query || ''),
      type: String(entry.type || UI_DEFAULTS.type),
      filter: normalizeFilter(entry.filter),
      sort: String(entry.sort || UI_DEFAULTS.sort),
      providers: Array.isArray(entry.providers) ? entry.providers.map((v) => String(v)) : [],
      categories: Array.isArray(entry.categories) ? entry.categories.map((v) => String(v)) : [],
      countries: Array.isArray(entry.countries) ? entry.countries.map((v) => String(v)) : [],
      nominationsMin: Number.isFinite(minNum) ? minNum : null,
      nominationsMax: Number.isFinite(maxNum) ? maxNum : null,
      winnersOnly: Boolean(entry.winnersOnly)
    };
  } catch {
    return { ...UI_DEFAULTS };
  }
}

function saveUiState(year) {
  const key = yearKey(year);
  if (!key) return;
  let base = {};
  try {
    const raw = localStorage.getItem(UI_STATE_KEY);
    base = raw ? JSON.parse(raw) || {} : {};
  } catch {
    base = {};
  }
  base[key] = {
    query: state.query || '',
    type: state.type || 'ALL',
    filter: normalizeFilter(state.filter),
    sort: state.sort || 'title',
    providers: Array.isArray(state.providers) ? state.providers : [],
    categories: Array.isArray(state.categories) ? state.categories : [],
    countries: Array.isArray(state.countries) ? state.countries : [],
    nominationsMin: Number.isFinite(state.nominationsMin) ? state.nominationsMin : null,
    nominationsMax: Number.isFinite(state.nominationsMax) ? state.nominationsMax : null,
    winnersOnly: Boolean(state.winnersOnly)
  };
  try {
    localStorage.setItem(UI_STATE_KEY, JSON.stringify(base));
  } catch {
    // ignore
  }
}

function applyUiState(year) {
  const saved = loadUiState(year);
  state.query = saved.query;
  state.type = saved.type;
  state.filter = saved.filter;
  state.sort = saved.sort;
  state.providers = Array.isArray(saved.providers) ? saved.providers : [];
  state.categories = Array.isArray(saved.categories) ? saved.categories : [];
  state.countries = Array.isArray(saved.countries) ? saved.countries : [];
  state.nominationsMin = Number.isFinite(saved.nominationsMin) ? saved.nominationsMin : null;
  state.nominationsMax = Number.isFinite(saved.nominationsMax) ? saved.nominationsMax : null;
  state.winnersOnly = Boolean(saved.winnersOnly);
}

function setHideWatched(isOn) {
  const btn = $('oscars-hide-watched');
  if (!btn) return;
  btn.setAttribute('aria-pressed', isOn ? 'true' : 'false');
  btn.classList.toggle('is-on', isOn);
}

function setOnlyWinners(isOn) {
  const btn = $('oscars-only-winners');
  if (!btn) return;
  btn.setAttribute('aria-pressed', isOn ? 'true' : 'false');
  btn.classList.toggle('is-on', isOn);
}

function syncUiControls() {
  const search = $('oscars-search');
  if (search) search.value = state.query || '';

  const typeSelect = $('oscars-type');
  if (typeSelect && state.type) {
    typeSelect.value = state.type;
  }

  const sortSelect = $('oscars-sort');
  if (sortSelect && state.sort) {
    sortSelect.value = state.sort;
  }

  const nomMin = $('oscars-nom-min');
  if (nomMin) {
    nomMin.value = Number.isFinite(state.nominationsMin) ? String(state.nominationsMin) : '';
  }
  const nomMax = $('oscars-nom-max');
  if (nomMax) {
    nomMax.value = Number.isFinite(state.nominationsMax) ? String(state.nominationsMax) : '';
  }

  setHideWatched(state.filter === 'unwatched');
  setOnlyWinners(Boolean(state.winnersOnly));
}

function splitProviders(value) {
  if (!value) return [];
  const normalized = String(value).replace(/\s+\/\s+/g, ',');
  return normalized
    .split(/[,;|]/)
    .map((v) => v.trim())
    .filter(Boolean);
}

function formatCategoryList(value) {
  const list = splitCategories(value);
  return list.length ? list.join('; ') : '';
}

function collectCategories(item) {
  const set = new Set();
  splitCategories(item?.nominated_categories).forEach((c) => set.add(c));
  splitCategories(item?.won_categories).forEach((c) => set.add(c));
  return Array.from(set);
}

function hasWins(item) {
  return splitCategories(item?.won_categories).length > 0;
}

function extractProviders(items) {
  const set = new Set();
  items.forEach((item) => {
    splitProviders(item.where_to_watch).forEach((p) => set.add(p));
  });
  return Array.from(set).sort((a, b) => a.localeCompare(b));
}

function extractCategories(items) {
  const set = new Set();
  items.forEach((item) => {
    collectCategories(item).forEach((c) => set.add(c));
  });
  return sortCategories(Array.from(set));
}

function extractCountries(items) {
  const set = new Set();
  items.forEach((item) => {
    splitCountries(item.country).forEach((c) => set.add(c));
  });
  return Array.from(set).sort((a, b) => a.localeCompare(b));
}

function extractNominationValues(items) {
  const set = new Set();
  items.forEach((item) => {
    const raw = item.nominations_number;
    const num = raw === '' || raw === null || raw === undefined ? null : Number(raw);
    if (Number.isFinite(num)) set.add(num);
  });
  return Array.from(set).sort((a, b) => a - b);
}

function renderNominationFilters(items) {
  const minSelect = $('oscars-nom-min');
  const maxSelect = $('oscars-nom-max');
  if (!minSelect || !maxSelect) return;
  const values = extractNominationValues(items);
  const available = new Set(values);
  if (Number.isFinite(state.nominationsMin) && !available.has(state.nominationsMin)) {
    state.nominationsMin = null;
  }
  if (Number.isFinite(state.nominationsMax) && !available.has(state.nominationsMax)) {
    state.nominationsMax = null;
  }

  minSelect.innerHTML =
    '<option value="">Min nominations</option>' +
    values.map((n) => `<option value="${n}">Min ${n}</option>`).join('');
  maxSelect.innerHTML =
    '<option value="">Max nominations</option>' +
    values.map((n) => `<option value="${n}">Max ${n}</option>`).join('');

  minSelect.value = Number.isFinite(state.nominationsMin) ? String(state.nominationsMin) : '';
  maxSelect.value = Number.isFinite(state.nominationsMax) ? String(state.nominationsMax) : '';
}

function normalizeNomValue(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function normalizeNomRange(min, max) {
  if (Number.isFinite(min) && Number.isFinite(max) && min > max) {
    return [max, min];
  }
  return [min, max];
}

function renderWherePills(items) {
  const wrap = $('oscars-where-filters');
  if (!wrap) return;
  const providers = extractProviders(items);
  if (!providers.length) {
    wrap.innerHTML = '<span class="meta">No providers</span>';
    state.providers = [];
    return;
  }

  const available = new Set(providers);
  state.providers = (state.providers || []).filter((p) => available.has(p));

  wrap.innerHTML = '';
  providers.forEach((provider) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'oscars-pill';
    btn.textContent = provider;
    const isOn = state.providers.includes(provider);
    btn.classList.toggle('is-on', isOn);
    btn.setAttribute('aria-pressed', isOn ? 'true' : 'false');
    btn.addEventListener('click', () => {
      const idx = state.providers.indexOf(provider);
      if (idx === -1) {
        state.providers.push(provider);
      } else {
        state.providers.splice(idx, 1);
      }
      saveUiState(OSCARS_YEAR);
      renderWherePills(items);
      render();
    });
    wrap.appendChild(btn);
  });
}

function renderCategoryPills(items) {
  const wrap = $('oscars-category-filters');
  if (!wrap) return;
  const categories = extractCategories(items);
  if (!categories.length) {
    wrap.innerHTML = '<span class="meta">No categories</span>';
    state.categories = [];
    return;
  }
  const available = new Set(categories);
  state.categories = (state.categories || []).filter((c) => available.has(c));

  wrap.innerHTML = '';
  categories.forEach((category) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'oscars-pill';
    btn.textContent = category;
    const isOn = state.categories.includes(category);
    btn.classList.toggle('is-on', isOn);
    btn.setAttribute('aria-pressed', isOn ? 'true' : 'false');
    btn.addEventListener('click', () => {
      const idx = state.categories.indexOf(category);
      if (idx === -1) {
        state.categories.push(category);
      } else {
        state.categories.splice(idx, 1);
      }
      saveUiState(OSCARS_YEAR);
      renderCategoryPills(items);
      render();
    });
    wrap.appendChild(btn);
  });
}

function renderCountryPills(items) {
  const wrap = $('oscars-country-filters');
  if (!wrap) return;
  const countries = extractCountries(items);
  if (!countries.length) {
    wrap.innerHTML = '<span class="meta">No countries</span>';
    state.countries = [];
    return;
  }
  const available = new Set(countries);
  state.countries = (state.countries || []).filter((c) => available.has(c));

  wrap.innerHTML = '';
  countries.forEach((country) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'oscars-pill';
    btn.textContent = country;
    const isOn = state.countries.includes(country);
    btn.classList.toggle('is-on', isOn);
    btn.setAttribute('aria-pressed', isOn ? 'true' : 'false');
    btn.addEventListener('click', () => {
      const idx = state.countries.indexOf(country);
      if (idx === -1) {
        state.countries.push(country);
      } else {
        state.countries.splice(idx, 1);
      }
      saveUiState(OSCARS_YEAR);
      renderCountryPills(items);
      render();
    });
    wrap.appendChild(btn);
  });
}

function pickYear(urlYear, years) {
  if (urlYear === ALL_YEARS_VALUE) return ALL_YEARS_VALUE;
  if (Number.isFinite(urlYear) && urlYear > 0) return urlYear;
  if (Array.isArray(years) && years.length) return years[0];
  return 2026;
}

function setYearTitle(year) {
  const title =
    year === ALL_YEARS_VALUE
      ? 'Oscars Watchlist — All Years'
      : Number.isFinite(year)
        ? `Oscars ${year} Watchlist`
        : 'Oscars Watchlist';
  const h1 = $('oscars-year-title');
  if (h1) h1.textContent = title;
  document.title = title;
}

function renderYearSelect(years, currentYear) {
  const select = $('oscars-year-select');
  if (!select) return;
  const list = Array.isArray(years) ? [...years] : [];
  if (Number.isFinite(currentYear) && !list.includes(currentYear)) {
    list.unshift(currentYear);
  }
  const full = [ALL_YEARS_VALUE, ...list];
  const unique = [];
  const seen = new Set();
  full.forEach((y) => {
    const key = String(y);
    if (seen.has(key)) return;
    seen.add(key);
    unique.push(y);
  });
  select.innerHTML = unique
    .map((y) => {
      const label = y === ALL_YEARS_VALUE ? 'All' : y;
      return `<option value="${y}">${label}</option>`;
    })
    .join('');
  if (currentYear === ALL_YEARS_VALUE) {
    select.value = ALL_YEARS_VALUE;
  } else if (Number.isFinite(currentYear)) {
    select.value = String(currentYear);
  }
  select.addEventListener('change', () => {
    const raw = select.value;
    const next = raw === ALL_YEARS_VALUE ? ALL_YEARS_VALUE : Number(raw);
    if (next !== ALL_YEARS_VALUE && !Number.isFinite(next)) return;
    saveUiState(currentYear);
    setUrlYear(next);
    location.reload();
  });
}

function formatDatePl(value = new Date()) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  try {
    const date = d.toLocaleDateString('pl-PL', { day: 'numeric', month: 'short', year: 'numeric' });
    const time = d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
    return `${date}, ${time}`;
  } catch {
    return d.toISOString().slice(0, 16).replace('T', ' ');
  }
}

function pluralPl(n, one, few, many) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (n === 1) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function formatRelativePl(iso) {
  if (!iso) return '';
  const parts = String(iso).split('-').map((v) => Number(v));
  if (parts.length !== 3 || parts.some((v) => !Number.isFinite(v))) return '';
  const [y, m, d] = parts;
  const target = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.round((today - target) / (24 * 60 * 60 * 1000));
  if (diffDays <= 0) return 'Obejrzany: dziś';
  if (diffDays < 7) {
    const label = pluralPl(diffDays, 'dzień', 'dni', 'dni');
    return `Obejrzany: ${diffDays} ${label} temu`;
  }
  if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7);
    const label = pluralPl(weeks, 'tydzień', 'tygodnie', 'tygodni');
    return `Obejrzany: ${weeks} ${label} temu`;
  }
  if (diffDays < 365) {
    const months = Math.floor(diffDays / 30);
    const label = pluralPl(months, 'miesiąc', 'miesiące', 'miesięcy');
    return `Obejrzany: ${months} ${label} temu`;
  }
  const years = Math.floor(diffDays / 365);
  const label = pluralPl(years, 'rok', 'lata', 'lat');
  return `Obejrzany: ${years} ${label} temu`;
}

function isWatched(value) {
  if (value === true) return true;
  if (value === false || value === null || value === undefined) return false;
  if (typeof value === 'number') return value === 1;
  const s = String(value).trim().toUpperCase();
  return ['1', 'TRUE', 'YES', 'TAK'].includes(s);
}

function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function clampIsoToRange(iso) {
  if (!iso) return '';
  if (iso < YEAR_MIN_ISO) return YEAR_MIN_ISO;
  if (iso > YEAR_MAX_ISO) return YEAR_MAX_ISO;
  return iso;
}

function syncTypeSelect() {
  const typeSelect = $('oscars-type');
  if (!typeSelect) return;

  const current = typeSelect.value || state.type || 'ALL';
  const types = Array.from(new Set(data.map((i) => i.type).filter(Boolean))).sort();
  typeSelect.innerHTML = '<option value="ALL">All types</option>' + types.map((t) => `<option value="${t}">${t}</option>`).join('');

  if (current !== 'ALL' && types.includes(current)) {
    typeSelect.value = current;
    state.type = current;
  } else {
    typeSelect.value = 'ALL';
    state.type = 'ALL';
  }
}

async function refresh() {
  if (OSCARS_YEAR === ALL_YEARS_VALUE) {
    data = await fetchOscarsAll(AVAILABLE_YEARS);
  } else {
    data = await fetchOscars(OSCARS_YEAR);
  }
  syncTypeSelect();
  renderWherePills(data);
  renderCategoryPills(data);
  renderCountryPills(data);
  renderNominationFilters(data);
  setDataStats(data);
  updateStats();
  render();
}

function isoToDisplay(iso) {
  if (!iso) return '';
  const parts = String(iso).split('-');
  if (parts.length !== 3) return '';
  const [y, m, d] = parts;
  if (!y || !m || !d) return '';
  return `${d.padStart(2, '0')}/${m.padStart(2, '0')}/${y}`;
}

function displayToIso(value) {
  if (!value) return '';
  const m = String(value).trim().match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/);
  if (!m) return '';
  const day = Number(m[1]);
  const month = Number(m[2]);
  const year = Number(m[3]);
  if (!Number.isFinite(day) || !Number.isFinite(month) || !Number.isFinite(year)) return '';
  if (year < YEAR_MIN || year > YEAR_MAX) return '';
  if (month < 1 || month > 12 || day < 1 || day > 31) return '';
  const dt = new Date(year, month - 1, day);
  if (dt.getFullYear() !== year || dt.getMonth() !== month - 1 || dt.getDate() !== day) return '';
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function runtimeToMin(value) {
  if (!value) return null;
  const m = String(value).match(/\d+(?:[.,]\d+)?/);
  if (!m) return null;
  const n = Number(m[0].replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

function computeStats(list) {
  const total = list.length;
  const watched = list.filter((i) => isWatched(i.watched)).length;
  const left = Math.max(0, total - watched);
  const rated = list.filter((i) => isWatched(i.watched) && Number.isFinite(i.rating_1_10));
  const avg = rated.length ? rated.reduce((s, i) => s + i.rating_1_10, 0) / rated.length : null;
  const pct = total ? Math.round((watched / total) * 100) : 0;
  return { total, watched, left, avg, pct };
}

function updateStats() {
  const stats = computeStats(data);
  if ($('oscars-kpi-total')) $('oscars-kpi-total').textContent = String(stats.total);
  if ($('oscars-kpi-watched')) $('oscars-kpi-watched').textContent = String(stats.watched);
  if ($('oscars-kpi-left')) $('oscars-kpi-left').textContent = String(stats.left);
  if ($('oscars-kpi-avg')) $('oscars-kpi-avg').textContent = stats.avg === null ? '-' : stats.avg.toFixed(2);
  const bar = $('oscars-progress-bar');
  if (bar) bar.style.width = `${stats.pct}%`;
  const label = $('oscars-progress-text');
  if (label) label.textContent = `${stats.watched} / ${stats.total} - ${stats.pct}%`;
}

function setFoot(msg) {
  const foot = $('oscars-foot');
  if (foot) foot.textContent = msg;
}

function setSourceBadge(mode) {
  const el = $('oscars-source');
  if (!el) return;
  el.classList.remove('is-api', 'is-static');
  if (mode === 'api') {
    el.classList.add('is-api');
    el.textContent = 'Data: API (synced across devices)';
  } else if (mode === 'static') {
    el.classList.add('is-static');
    el.textContent = 'Data: Local browser (this device)';
  } else {
    el.textContent = 'Data: loading...';
  }
}

function setPosterStatus(msg) {
  const el = $('oscars-posters-status');
  if (el) el.textContent = msg;
}

function setMetaStatus(msg) {
  const el = $('oscars-meta-status');
  if (el) el.textContent = msg;
}

function setWinnersStatus(msg) {
  const el = $('oscars-winners-status');
  if (el) el.textContent = msg;
}

function computeDataStats(list) {
  const total = list.length;
  const missingPoster = list.filter((i) => !i.poster_url).length;
  const missingRuntime = list.filter((i) => !i.runtime).length;
  const missingCountry = list.filter((i) => !i.country).length;
  const missingDetails = list.filter((i) => !i.runtime || !i.country).length;
  const winnersTagged = list.filter((i) => splitCategories(i.won_categories).length > 0).length;
  const winnerCats = new Set();
  list.forEach((i) => {
    splitCategories(i.won_categories).forEach((c) => winnerCats.add(c));
  });
  return {
    total,
    missingPoster,
    missingRuntime,
    missingCountry,
    missingDetails,
    winnersTagged,
    winnerCategories: winnerCats.size
  };
}

function setDataStats(list) {
  const el = $('oscars-data-stats');
  if (!el) return;
  if (!list || list.length === 0) {
    el.textContent = 'No items loaded.';
    return;
  }
  const stats = computeDataStats(list);
  const posterHave = stats.total - stats.missingPoster;
  const detailsHave = stats.total - stats.missingDetails;
  el.innerHTML = [
    `Posters: ${posterHave}/${stats.total} (missing ${stats.missingPoster})`,
    `Details: ${detailsHave}/${stats.total} (missing ${stats.missingDetails}; runtime ${stats.missingRuntime}, country ${stats.missingCountry})`,
    `Winners tagged: ${stats.winnersTagged}/${stats.total} (categories ${stats.winnerCategories})`
  ]
    .map((line) => `<div>${line}</div>`)
    .join('');
}

function buildMetaTags(item) {
  const tags = [];
  if (item.type) tags.push({ label: String(item.type), kind: 'type' });
  if (item.runtime) tags.push({ label: String(item.runtime), kind: 'runtime' });
  if (item.country) tags.push({ label: String(item.country), kind: 'country' });
  if (item.nominations_number !== null && item.nominations_number !== undefined) {
    const n = Number(item.nominations_number);
    const label = Number.isFinite(n) && n === 1 ? 'nomination' : 'nominations';
    tags.push({ label: `${item.nominations_number} ${label}`, kind: 'nominations' });
  }
  const nominated = splitCategories(item.nominated_categories);
  const wonSet = new Set(splitCategories(item.won_categories));
  if (nominated.length || wonSet.size) {
    const seen = new Set();
    nominated.forEach((c) => {
      seen.add(c);
      tags.push({ label: c, kind: 'category', isWinner: wonSet.has(c) });
    });
    wonSet.forEach((c) => {
      if (seen.has(c)) return;
      tags.push({ label: c, kind: 'category', isWinner: true });
    });
  }
  return tags;
}

function createPosterIcon() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.classList.add('oscars-poster-icon');

  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  circle.setAttribute('cx', '12');
  circle.setAttribute('cy', '12');
  circle.setAttribute('r', '9');
  circle.setAttribute('fill', 'none');
  circle.setAttribute('stroke', 'currentColor');
  circle.setAttribute('stroke-width', '1.5');

  const tri = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  tri.setAttribute('d', 'M10 8l6 4-6 4z');
  tri.setAttribute('fill', 'currentColor');

  svg.appendChild(circle);
  svg.appendChild(tri);
  return svg;
}

function createPosterFallback(letter) {
  const wrap = document.createElement('div');
  wrap.className = 'oscars-poster-fallback';
  wrap.appendChild(createPosterIcon());
  const letterEl = document.createElement('span');
  letterEl.className = 'oscars-poster-letter';
  letterEl.textContent = letter;
  wrap.appendChild(letterEl);
  return wrap;
}

function applyFilters(items) {
  let list = [...items];

  if (state.query) {
    const q = state.query.toLowerCase();
    list = list.filter((i) => {
      const hay = [i.title, i.director_s, i.nominated_categories, i.won_categories, i.country, i.notes, i.where_to_watch]
        .filter(Boolean)
        .map((v) => String(v).toLowerCase());
      return hay.some((v) => v.includes(q));
    });
  }

  if (state.type && state.type !== 'ALL') {
    list = list.filter((i) => String(i.type || '') === state.type);
  }

  if (state.filter === 'watched') list = list.filter((i) => isWatched(i.watched));
  if (state.filter === 'unwatched') list = list.filter((i) => !isWatched(i.watched));

  if (Array.isArray(state.providers) && state.providers.length) {
    const selected = new Set(state.providers);
    list = list.filter((i) => {
      const providers = splitProviders(i.where_to_watch);
      return providers.some((p) => selected.has(p));
    });
  }

  if (Array.isArray(state.categories) && state.categories.length) {
    const selected = new Set(state.categories);
    list = list.filter((i) => {
      const cats = collectCategories(i);
      return cats.some((c) => selected.has(c));
    });
  }

  if (Array.isArray(state.countries) && state.countries.length) {
    const selected = new Set(state.countries);
    list = list.filter((i) => {
      const countries = splitCountries(i.country);
      return countries.some((c) => selected.has(c));
    });
  }

  if (state.winnersOnly) {
    list = list.filter((i) => hasWins(i));
  }

  if (Number.isFinite(state.nominationsMin) || Number.isFinite(state.nominationsMax)) {
    const min = Number.isFinite(state.nominationsMin) ? state.nominationsMin : null;
    const max = Number.isFinite(state.nominationsMax) ? state.nominationsMax : null;
    list = list.filter((i) => {
      const n = Number(i.nominations_number);
      if (!Number.isFinite(n)) return false;
      if (min !== null && n < min) return false;
      if (max !== null && n > max) return false;
      return true;
    });
  }

  const byTitle = (a, b) => String(a.title || '').localeCompare(String(b.title || ''));

  if (state.sort === 'rating_desc') {
    list.sort((a, b) => (b.rating_1_10 ?? -1) - (a.rating_1_10 ?? -1) || byTitle(a, b));
  } else if (state.sort === 'rating_asc') {
    list.sort((a, b) => (a.rating_1_10 ?? 999) - (b.rating_1_10 ?? 999) || byTitle(a, b));
  } else if (state.sort === 'runtime') {
    list.sort((a, b) => {
      const ar = runtimeToMin(a.runtime);
      const br = runtimeToMin(b.runtime);
      if (ar === null && br === null) return byTitle(a, b);
      if (ar === null) return 1;
      if (br === null) return -1;
      return ar - br || byTitle(a, b);
    });
  } else if (state.sort === 'watched_date') {
    list.sort((a, b) => {
      const ad = a.watched_date || '';
      const bd = b.watched_date || '';
      if (ad === bd) return byTitle(a, b);
      return bd.localeCompare(ad);
    });
  } else {
    list.sort(byTitle);
  }

  return list;
}

function renderRow(item) {
  const row = document.createElement('div');
  row.className = `oscars-row${isWatched(item.watched) ? ' is-watched' : ''}`;

  const itemYear = OSCARS_YEAR === ALL_YEARS_VALUE ? item.oscars_year : OSCARS_YEAR;

  const main = document.createElement('div');
  main.className = 'oscars-row-main';

  const poster = document.createElement('div');
  poster.className = 'oscars-poster';
  if (item.poster_url) {
    const img = document.createElement('img');
    img.src = item.poster_url;
    img.alt = `${item.title || 'Poster'}`;
    img.loading = 'lazy';
    img.referrerPolicy = 'no-referrer';
    poster.appendChild(img);
  } else {
    poster.classList.add('is-empty');
    const letter = String(item.title || '?').trim().charAt(0).toUpperCase() || '?';
    poster.appendChild(createPosterFallback(letter));
  }

  const text = document.createElement('div');
  text.className = 'oscars-main-text';
  const title = document.createElement('div');
  title.className = 'oscars-title';
  title.textContent = item.title || '-';
  const watchBtn = document.createElement('button');
  watchBtn.type = 'button';
  watchBtn.className = 'oscars-watch-toggle';
  const watchedNow = isWatched(item.watched);
  if (watchedNow) {
    watchBtn.classList.add('is-reset');
    watchBtn.setAttribute('aria-label', 'Reset watched');
    watchBtn.title = 'Reset watched';
    watchBtn.textContent = '↺';
  } else {
    watchBtn.textContent = 'Mark watched';
  }
  watchBtn.setAttribute('aria-pressed', watchedNow ? 'true' : 'false');

  const titleRow = document.createElement('div');
  titleRow.className = 'oscars-title-row';
  const titleWrap = document.createElement('div');
  titleWrap.className = 'oscars-title-wrap';
  titleWrap.appendChild(title);
  if (isWatched(item.watched)) {
    const badge = document.createElement('span');
    badge.className = 'oscars-watched-badge';
    const badgeIcon = document.createElement('span');
    badgeIcon.className = 'oscars-watched-icon';
    const badgeLabel = document.createElement('span');
    badgeLabel.textContent = 'Watched';
    badge.appendChild(badgeIcon);
    badge.appendChild(badgeLabel);
    titleWrap.appendChild(badge);
  }
  if (OSCARS_YEAR === ALL_YEARS_VALUE && Number.isFinite(item.oscars_year)) {
    const yearBadge = document.createElement('span');
    yearBadge.className = 'oscars-year-badge';
    yearBadge.textContent = String(item.oscars_year);
    titleWrap.appendChild(yearBadge);
  }
  titleRow.appendChild(titleWrap);
  titleRow.appendChild(watchBtn);
  const meta = document.createElement('div');
  meta.className = 'oscars-meta';
  const metaTags = buildMetaTags(item);
  if (!metaTags.length) {
    meta.textContent = '-';
  } else {
    metaTags.forEach((tag) => {
      const span = document.createElement('span');
      span.className = `oscars-tag oscars-tag--${tag.kind}`;
      if (tag.isWinner) {
        span.classList.add('oscars-tag--win');
        const icon = document.createElement('span');
        icon.className = 'oscars-win-icon';
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = '🏆';
        span.appendChild(icon);
      }
      const label = document.createElement('span');
      label.textContent = tag.label;
      span.appendChild(label);
      meta.appendChild(span);
    });
  }
  text.appendChild(titleRow);
  text.appendChild(meta);

  const rating = document.createElement('input');
  rating.type = 'number';
  rating.min = '0';
  rating.max = '10';
  rating.step = '0.5';
  rating.className = 'oscars-input oscars-rating';
  rating.placeholder = 'Rating';
  if (Number.isFinite(item.rating_1_10)) rating.value = String(item.rating_1_10);

  const dateWrap = document.createElement('div');
  dateWrap.className = 'oscars-date-wrap';

  const dateRelative = document.createElement('button');
  dateRelative.type = 'button';
  dateRelative.className = 'oscars-date-relative';
  const relativeText = formatRelativePl(item.watched_date);
  dateRelative.textContent = relativeText || 'Dodaj datę';

  const dateDisplay = document.createElement('input');
  dateDisplay.type = 'text';
  dateDisplay.className = 'oscars-input oscars-date-text';
  dateDisplay.placeholder = 'dd/mm/yyyy';
  dateDisplay.inputMode = 'numeric';
  dateDisplay.value = isoToDisplay(item.watched_date);

  const datePicker = document.createElement('input');
  datePicker.type = 'date';
  datePicker.className = 'oscars-date-picker';
  datePicker.min = `${YEAR_MIN}-01-01`;
  datePicker.max = `${YEAR_MAX}-12-31`;
  if (item.watched_date) datePicker.value = item.watched_date;

  dateWrap.appendChild(dateDisplay);
  dateWrap.appendChild(datePicker);

  const miniRow = document.createElement('div');
  miniRow.className = 'oscars-mini-row';
  miniRow.appendChild(rating);
  miniRow.appendChild(dateRelative);
  miniRow.appendChild(dateWrap);
  text.appendChild(miniRow);

  const hasDate = Boolean(item.watched_date);
  if (hasDate) {
    dateWrap.classList.add('is-hidden');
  } else {
    dateRelative.classList.add('is-hidden');
  }

  const starsWrap = document.createElement('div');
  starsWrap.className = 'oscars-stars-wrap';

  const stars = document.createElement('div');
  stars.className = 'oscars-stars';
  stars.setAttribute('role', 'group');
  stars.setAttribute('aria-label', 'Rating');

  const ratingLabel = document.createElement('span');
  ratingLabel.className = 'oscars-rating-label';

  const currentRating = Number.isFinite(item.rating_1_10) ? item.rating_1_10 : null;
  const selectedStars = Number.isFinite(currentRating) ? Math.round(currentRating) : 0;
  if (Number.isFinite(currentRating)) {
    ratingLabel.textContent = '';
    ratingLabel.classList.add('is-hidden');
  } else {
    ratingLabel.textContent = 'No rating';
  }

  const starButtons = [];
  for (let value = 10; value >= 1; value -= 1) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'oscars-star';
    btn.dataset.value = String(value);
    btn.setAttribute('aria-pressed', value === selectedStars ? 'true' : 'false');
    btn.setAttribute('aria-label', `Rate ${value}`);
    btn.innerHTML = '&#9733;';
    if (value <= selectedStars) btn.classList.add('is-on');
    stars.appendChild(btn);
    starButtons.push(btn);
  }

  starsWrap.appendChild(stars);
  starsWrap.appendChild(ratingLabel);
  text.appendChild(starsWrap);

  main.appendChild(poster);
  main.appendChild(text);

  const edit = document.createElement('div');
  edit.className = 'oscars-row-edit';

  const where = document.createElement('input');
  where.type = 'text';
  where.className = 'oscars-input';
  where.placeholder = 'Where to watch';
  where.value = item.where_to_watch || '';

  const notes = document.createElement('input');
  notes.type = 'text';
  notes.className = 'oscars-input';
  notes.placeholder = 'Notes';
  notes.value = item.notes || '';

  const wins = document.createElement('input');
  wins.type = 'text';
  wins.className = 'oscars-input oscars-wins-input';
  wins.placeholder = 'Won categories (semicolon-separated)';
  wins.value = item.won_categories || '';

  const posterInput = document.createElement('input');
  posterInput.type = 'text';
  posterInput.className = 'oscars-input oscars-poster-input';
  posterInput.placeholder = 'Poster URL (or /posters/...)';
  posterInput.value = item.poster_url || '';

  const links = document.createElement('div');
  links.className = 'oscars-links';
  const posterToggle = document.createElement('button');
  posterToggle.type = 'button';
  posterToggle.className = 'oscars-link-btn oscars-poster-toggle';
  posterToggle.textContent = 'Upload';
  posterToggle.title = 'Upload poster (Shift: edit URL)';
  links.appendChild(posterToggle);
  const posterFile = document.createElement('input');
  posterFile.type = 'file';
  posterFile.accept = 'image/*';
  posterFile.className = 'oscars-file-input';
  posterFile.setAttribute('aria-label', 'Upload poster image');
  links.appendChild(posterFile);
  if (item.wikipedia_url) {
    const a = document.createElement('a');
    a.href = item.wikipedia_url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = 'Wiki';
    links.appendChild(a);
  }
  if (item.imdb_url) {
    const a = document.createElement('a');
    a.href = item.imdb_url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = 'IMDb';
    links.appendChild(a);
  }

  edit.appendChild(where);
  edit.appendChild(notes);
  edit.appendChild(wins);
  edit.appendChild(posterInput);
  edit.appendChild(links);

  row.appendChild(main);
  row.appendChild(edit);

  const handleChange = () => {
    updateStats();
    render();
  };

  const setStarsDisabled = (value) => {
    starButtons.forEach((btn) => {
      btn.disabled = value;
    });
  };

  const applyStarPatch = async (value) => {
    setStarsDisabled(true);
    try {
      await updateOscars(
        item.id,
        {
          watched: true,
          watched_date: todayISO(),
          rating_1_10: value
        },
        itemYear
      );
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    } finally {
      setStarsDisabled(false);
    }
  };

  starButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const value = Number(btn.dataset.value);
      if (!Number.isFinite(value)) return;
      applyStarPatch(value);
    });
  });

  watchBtn.addEventListener('click', async () => {
    const next = !isWatched(item.watched);
    watchBtn.disabled = true;
    try {
      const patch = { watched: next };
      if (next) {
        patch.watched_date = todayISO();
        patch.rating_1_10 = null;
      }
      await updateOscars(item.id, patch, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    } finally {
      watchBtn.disabled = false;
    }
  });

  rating.addEventListener('change', async () => {
    try {
      await updateOscars(item.id, { rating_1_10: rating.value }, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    }
  });

  dateDisplay.addEventListener('click', () => {
    if (!datePicker.value) {
      datePicker.value = clampIsoToRange(todayISO());
    }
    if (typeof datePicker.showPicker === 'function') {
      datePicker.showPicker();
      return;
    }
    datePicker.focus();
    datePicker.click();
  });

  dateRelative.addEventListener('click', () => {
    dateRelative.classList.add('is-hidden');
    dateWrap.classList.remove('is-hidden');
    if (!datePicker.value) {
      datePicker.value = clampIsoToRange(todayISO());
    }
    if (typeof datePicker.showPicker === 'function') {
      datePicker.showPicker();
      return;
    }
    datePicker.focus();
    datePicker.click();
  });

  datePicker.addEventListener('change', async () => {
    try {
      dateDisplay.value = isoToDisplay(datePicker.value);
      await updateOscars(item.id, { watched_date: datePicker.value }, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    }
  });

  dateDisplay.addEventListener('change', async () => {
    const iso = displayToIso(dateDisplay.value);
    if (!iso) {
      dateDisplay.value = isoToDisplay(datePicker.value);
      return;
    }
    try {
      datePicker.value = iso;
      await updateOscars(item.id, { watched_date: iso }, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    }
  });

  where.addEventListener('change', async () => {
    try {
      await updateOscars(item.id, { where_to_watch: where.value }, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    }
  });

  notes.addEventListener('change', async () => {
    try {
      await updateOscars(item.id, { notes: notes.value }, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    }
  });

  wins.addEventListener('change', async () => {
    const normalized = formatCategoryList(wins.value);
    wins.value = normalized;
    try {
      await updateOscars(item.id, { won_categories: normalized }, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    }
  });

  posterInput.addEventListener('change', async () => {
    try {
      await updateOscars(item.id, { poster_url: posterInput.value }, itemYear);
      await refresh();
      setFoot(`Saved: ${formatDatePl()}`);
    } catch (e) {
      console.error(e);
      setFoot('Save failed.');
    }
  });

  posterToggle.addEventListener('click', (e) => {
    if (e.shiftKey) {
      row.classList.toggle('show-poster-input');
      if (row.classList.contains('show-poster-input')) {
        posterInput.focus();
      }
      return;
    }
    posterFile.click();
  });

  posterFile.addEventListener('change', () => {
    const file = posterFile.files && posterFile.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      setFoot('Poster too large (max 2MB).');
      posterFile.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      const dataUrl = String(reader.result || '');
      if (!dataUrl.startsWith('data:image')) {
        setFoot('Invalid image file.');
        return;
      }
      try {
        await updateOscars(item.id, { poster_url: dataUrl }, itemYear);
        posterInput.value = '';
        posterInput.placeholder = `Uploaded: ${file.name}`;
        await refresh();
        setFoot(`Saved: ${formatDatePl()}`);
      } catch (e) {
        console.error(e);
        setFoot('Save failed.');
      } finally {
        posterFile.value = '';
      }
    };
    reader.readAsDataURL(file);
  });

  return row;
}

function render() {
  const grid = $('oscars-grid');
  if (!grid) return;
  const list = applyFilters(data);
  grid.innerHTML = '';
  list.forEach((item) => grid.appendChild(renderRow(item)));
  if ($('oscars-count')) $('oscars-count').textContent = `${list.length} items`;
}

async function init() {
  DATA_MODE = await resolveOscarsMode();
  try {
    AVAILABLE_YEARS = await fetchOscarsYears();
  } catch (e) {
    console.error(e);
    AVAILABLE_YEARS = [];
  }

  const urlYear = getYearFromUrl();
  OSCARS_YEAR = pickYear(urlYear, AVAILABLE_YEARS);
  renderYearSelect(AVAILABLE_YEARS, OSCARS_YEAR);
  setYearTitle(OSCARS_YEAR);
  if (!urlYear || urlYear !== OSCARS_YEAR) {
    setUrlYear(OSCARS_YEAR, true);
  }
  applyUiState(OSCARS_YEAR);
  syncUiControls();
  setSourceBadge(DATA_MODE);

  try {
    await refresh();
    setFoot(getOscarsFootnote());
  } catch (e) {
    console.error(e);
    setFoot(DATA_MODE === 'api' ? 'API offline. Start the local server.' : 'Data offline. Check static files.');
  }

  const search = $('oscars-search');
  if (search) {
    search.addEventListener('input', (e) => {
      state.query = String(e.target.value || '').trim();
      render();
      saveUiState(OSCARS_YEAR);
    });
  }

  const typeSelect = $('oscars-type');
  if (typeSelect) {
    typeSelect.addEventListener('change', (e) => {
      state.type = String(e.target.value || 'ALL');
      render();
      saveUiState(OSCARS_YEAR);
    });
  }

  const hideBtn = $('oscars-hide-watched');
  if (hideBtn) {
    hideBtn.addEventListener('click', () => {
      const next = state.filter === 'unwatched' ? 'all' : 'unwatched';
      state.filter = next;
      setHideWatched(next === 'unwatched');
      render();
      saveUiState(OSCARS_YEAR);
    });
  }

  const winnersToggleBtn = $('oscars-only-winners');
  if (winnersToggleBtn) {
    winnersToggleBtn.addEventListener('click', () => {
      const next = !state.winnersOnly;
      state.winnersOnly = next;
      setOnlyWinners(next);
      render();
      saveUiState(OSCARS_YEAR);
    });
  }

  const clearBtn = $('oscars-clear-filters');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      state.query = UI_DEFAULTS.query;
      state.type = UI_DEFAULTS.type;
      state.filter = UI_DEFAULTS.filter;
      state.sort = UI_DEFAULTS.sort;
      state.providers = [];
      state.categories = [];
      state.countries = [];
      state.nominationsMin = null;
      state.nominationsMax = null;
      state.winnersOnly = false;
      syncUiControls();
      renderWherePills(data);
      renderCategoryPills(data);
      renderCountryPills(data);
      renderNominationFilters(data);
      setDataStats(data);
      render();
      saveUiState(OSCARS_YEAR);
    });
  }

  const sortSelect = $('oscars-sort');
  if (sortSelect) {
    sortSelect.addEventListener('change', (e) => {
      state.sort = String(e.target.value || 'title');
      render();
      saveUiState(OSCARS_YEAR);
    });
  }

  const nomMin = $('oscars-nom-min');
  const nomMax = $('oscars-nom-max');
  const onNomChange = () => {
    let min = normalizeNomValue(nomMin ? nomMin.value : null);
    let max = normalizeNomValue(nomMax ? nomMax.value : null);
    [min, max] = normalizeNomRange(min, max);
    state.nominationsMin = min;
    state.nominationsMax = max;
    if (nomMin) nomMin.value = Number.isFinite(min) ? String(min) : '';
    if (nomMax) nomMax.value = Number.isFinite(max) ? String(max) : '';
    render();
    saveUiState(OSCARS_YEAR);
  };
  if (nomMin) nomMin.addEventListener('change', onNomChange);
  if (nomMax) nomMax.addEventListener('change', onNomChange);

  const toTop = $('oscars-to-top');
  if (toTop) {
    const onScroll = () => {
      const show = window.scrollY > 400;
      toTop.classList.toggle('is-visible', show);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    toTop.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }
  const postersBtn = $('oscars-posters-btn');
  if (postersBtn) {
    if (DATA_MODE !== 'api') {
      postersBtn.disabled = true;
      postersBtn.title = 'Poster fetch requires API mode.';
      setPosterStatus('Poster fetch requires API mode.');
    } else {
      postersBtn.addEventListener('click', async (e) => {
        postersBtn.disabled = true;
        setPosterStatus('Fetching posters...');
        try {
          const res = await fetchPosters(50, e.shiftKey, OSCARS_YEAR);
          await refresh();
          const providers = res.providers
            ? ` OMDb: ${res.providers.omdb ? 'on' : 'off'}, Wiki: on${res.providers.tmdb ? ', TMDb: on' : ''}`
            : '';
          const localInfo = typeof res.local_updated === 'number' ? ` Local applied: ${res.local_updated}.` : '';
          setPosterStatus(`Posters updated: ${res.updated}/${res.attempted}. Missing: ${res.missing}.${localInfo}${providers}`);
        } catch (err) {
          console.error(err);
          setPosterStatus('Poster fetch failed.');
        } finally {
          postersBtn.disabled = false;
        }
      });
    }
  }

  const metaBtn = $('oscars-meta-btn');
  if (metaBtn) {
    if (DATA_MODE !== 'api') {
      metaBtn.disabled = true;
      metaBtn.title = 'Details fetch requires API mode.';
      setMetaStatus('Details fetch requires API mode.');
    } else {
      metaBtn.addEventListener('click', async (e) => {
        metaBtn.disabled = true;
        setMetaStatus('Fetching details...');
        try {
          const res = await fetchOscarsDetails(50, e.shiftKey, OSCARS_YEAR);
          await refresh();
          const providers = res.providers
            ? ` TMDb: ${res.providers.tmdb ? 'on' : 'off'}, OMDb: ${res.providers.omdb ? 'on' : 'off'}, Wikidata: on`
            : '';
          const localInfo = typeof res.updated_runtime === 'number'
            ? ` Runtime: ${res.updated_runtime}, Country: ${res.updated_country}.`
            : '';
          setMetaStatus(`Details updated: ${res.updated}/${res.attempted}. Missing: ${res.missing}.${localInfo}${providers}`);
        } catch (err) {
          console.error(err);
          setMetaStatus('Details fetch failed.');
        } finally {
          metaBtn.disabled = false;
        }
      });
    }
  }

  const winnersImportBtn = $('oscars-winners-btn');
  if (winnersImportBtn) {
    if (DATA_MODE !== 'api') {
      winnersImportBtn.disabled = true;
      winnersImportBtn.title = 'Winners import requires API mode.';
      setWinnersStatus('Winners import requires API mode.');
    } else {
      winnersImportBtn.addEventListener('click', async (e) => {
        winnersImportBtn.disabled = true;
        setWinnersStatus('Importing winners...');
        try {
          const year = OSCARS_YEAR === ALL_YEARS_VALUE ? null : OSCARS_YEAR;
          const res = await fetchOscarsWinners(e.shiftKey, year);
          await refresh();
          const scope = year ? `Year ${year}. ` : '';
          const fileInfo = typeof res.updated_files === 'number' ? ` Files: ${res.updated_files}.` : '';
          setWinnersStatus(`${scope}Winners updated: ${res.updated_rows}. Matched: ${res.matched_rows}.${fileInfo}`);
        } catch (err) {
          console.error(err);
          setWinnersStatus('Winners import failed.');
        } finally {
          winnersImportBtn.disabled = false;
        }
      });
    }
  }
}

init();
