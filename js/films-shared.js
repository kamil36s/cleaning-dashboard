import { splitCategories } from './oscars-categories.js';

export const OSCARS_SPOTLIGHT_YEAR = 2026;
export const OSCARS_RESULTS_WINDOW_START = '2026-03-15';
export const OSCARS_RESULTS_WINDOW_END = '2026-03-17';
export const OSCARS_RESULTS_TARGET_DATE = '2026-03-15';

export const FILMS_COLLECTIONS = Object.freeze([
  {
    key: 'oscars-2026',
    title: 'Oscars 2026',
    kind: 'live',
    href: './oscars.html?year=2026',
    teaser: 'Aktywna lista nominowanych, oceny i wyniki po gali.',
  },
  {
    key: 'cannes',
    title: 'Cannes',
    kind: 'planned',
    href: './films.html',
    teaser: 'Slot pod następną festiwalową listę.',
  },
  {
    key: 'library',
    title: 'Biblioteka',
    kind: 'planned',
    href: './films.html',
    teaser: 'Miejsce na własne filmy, rewatch i oceny.',
  },
]);

const RESULTS_SYNC_STORAGE_PREFIX = 'oscars_results_autosync_v1';
const DEFAULT_RESULTS_SYNC_THROTTLE_MS = 30 * 60 * 1000;
const MS_DAY = 24 * 60 * 60 * 1000;

function parseLocalIsoDate(iso) {
  if (!iso) return null;
  const parts = String(iso).split('-').map(Number);
  if (parts.length !== 3 || parts.some((value) => !Number.isFinite(value))) {
    return null;
  }
  return new Date(parts[0], parts[1] - 1, parts[2], 12, 0, 0, 0);
}

function startOfLocalDay(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return new Date();
  return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 12, 0, 0, 0);
}

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const num = Number(String(value).replace(',', '.'));
  return Number.isFinite(num) ? num : null;
}

function formatMaybeRating(value) {
  const num = toNumber(value);
  return Number.isFinite(num) ? num.toFixed(1) : null;
}

function getStorage() {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage;
    }
  } catch {}
  return null;
}

function distinct(items) {
  return Array.from(new Set(items.filter(Boolean)));
}

function firstItalicTitle(value) {
  if (!value) return null;
  const text = String(value);
  const match =
    text.match(/'''''?\[\[([^|\]]+)\|([^\]]+)\]\]'''''?/) ||
    text.match(/'''''?\[\[([^\]]+)\]\]'''''?/) ||
    text.match(/'''''?([^'\n]+)'''''?/);

  if (!match) return null;
  const raw = match[2] || match[1] || '';
  return String(raw).trim() || null;
}

export function formatDatePl(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  try {
    const day = date.toLocaleDateString('pl-PL', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
    const time = date.toLocaleTimeString('pl-PL', {
      hour: '2-digit',
      minute: '2-digit',
    });
    return `${day}, ${time}`;
  } catch {
    return date.toISOString().slice(0, 16).replace('T', ' ');
  }
}

export function isWatched(value) {
  if (value === true) return true;
  if (value === false || value === null || value === undefined) return false;
  if (typeof value === 'number') return value === 1;
  const normalized = String(value).trim().toUpperCase();
  return ['1', 'TRUE', 'YES', 'TAK'].includes(normalized);
}

export function getOscarsSeasonState(now = new Date()) {
  const today = startOfLocalDay(now);
  const start = parseLocalIsoDate(OSCARS_RESULTS_WINDOW_START);
  const end = parseLocalIsoDate(OSCARS_RESULTS_WINDOW_END);
  if (!start || !end) return 'archive';
  if (today < start) return 'watchlist';
  if (today <= end) return 'results';
  return 'archive';
}

export function isOscarsResultsWindow(now = new Date()) {
  return getOscarsSeasonState(now) === 'results';
}

export function daysUntilIso(targetIso, now = new Date()) {
  const target = parseLocalIsoDate(targetIso);
  if (!target) return null;
  const today = startOfLocalDay(now);
  const diff = Math.round((target - today) / MS_DAY);
  return Math.max(0, diff);
}

export function summarizeFilms(list = []) {
  const safeList = Array.isArray(list) ? list : [];
  const watchedItems = safeList.filter((item) => isWatched(item?.watched));
  const ratedItems = watchedItems.filter((item) => Number.isFinite(toNumber(item?.rating_1_10)));
  const winnerItems = safeList
    .map((item) => {
      const categories = splitCategories(item?.won_categories);
      return {
        item,
        title: String(item?.title || '').trim(),
        categories,
        winCount: categories.length,
        rating: toNumber(item?.rating_1_10),
        nominations: toNumber(item?.nominations_number) || 0,
      };
    })
    .filter((entry) => entry.title && entry.winCount > 0)
    .sort((a, b) => {
      if (b.winCount !== a.winCount) return b.winCount - a.winCount;
      if ((b.rating ?? -1) !== (a.rating ?? -1)) return (b.rating ?? -1) - (a.rating ?? -1);
      if (b.nominations !== a.nominations) return b.nominations - a.nominations;
      return a.title.localeCompare(b.title, 'pl');
    });

  const topRated = watchedItems
    .filter((item) => Number.isFinite(toNumber(item?.rating_1_10)))
    .map((item) => ({
      title: String(item?.title || '').trim(),
      rating: toNumber(item?.rating_1_10),
      runtime: String(item?.runtime || item?.runtime_helper || item?.runtime_helper_2 || '').trim(),
      categories: splitCategories(item?.won_categories),
    }))
    .filter((item) => item.title)
    .sort((a, b) => {
      if ((b.rating ?? -1) !== (a.rating ?? -1)) return (b.rating ?? -1) - (a.rating ?? -1);
      return a.title.localeCompare(b.title, 'pl');
    })[0] || null;

  const nextUnwatched = safeList
    .filter((item) => !isWatched(item?.watched))
    .map((item) => ({
      title: String(item?.title || '').trim(),
      nominations: toNumber(item?.nominations_number) || 0,
      runtime: String(item?.runtime || item?.runtime_helper || item?.runtime_helper_2 || '').trim(),
      categories: splitCategories(item?.nominated_categories),
      poster: item?.poster_url || null,
      raw: item,
    }))
    .filter((item) => item.title)
    .sort((a, b) => {
      if (b.nominations !== a.nominations) return b.nominations - a.nominations;
      return a.title.localeCompare(b.title, 'pl');
    })[0] || null;

  const avgRating = ratedItems.length
    ? ratedItems.reduce((sum, item) => sum + toNumber(item.rating_1_10), 0) / ratedItems.length
    : null;

  const winnerCategories = distinct(winnerItems.flatMap((entry) => entry.categories));

  return {
    total: safeList.length,
    watched: watchedItems.length,
    rated: ratedItems.length,
    avgRating,
    progressPct: safeList.length ? Math.round((watchedItems.length / safeList.length) * 100) : 0,
    winnersCount: winnerItems.length,
    winnerCategoriesCount: winnerCategories.length,
    winnerItems,
    topWinner: winnerItems[0] || null,
    topRated,
    nextUnwatched,
  };
}

export function buildFilmsSpotlight(list = [], now = new Date()) {
  const summary = summarizeFilms(list);
  const state = getOscarsSeasonState(now);
  const daysLeft = daysUntilIso(OSCARS_RESULTS_TARGET_DATE, now);

  if (state === 'results') {
    if (summary.winnersCount > 0) {
      const topWinner = summary.topWinner;
      return {
        state,
        label: `Oscars ${OSCARS_SPOTLIGHT_YEAR}: wyniki`,
        meta: `${summary.winnersCount} tytułów ze statuetkami`,
        title: topWinner?.title || 'Wyniki są już zapisane',
        copy: topWinner
          ? `Najwięcej wygranych kategorii: ${topWinner.winCount}.`
          : 'Widget trzyma zwycięzców na wierzchu przez trzy dni po gali.',
        highlights: summary.winnerItems.slice(0, 3).map((entry) => ({
          title: entry.title,
          detail: entry.categories.slice(0, 3).join(' • '),
        })),
      };
    }

    return {
      state,
      label: `Oscars ${OSCARS_SPOTLIGHT_YEAR}: wyniki`,
      meta: 'okno 15-17 marca',
      title: 'Czekam na zwycięzców',
      copy: 'Jeśli źródło już je opublikuje, widget spróbuje zaciągnąć je automatycznie.',
      highlights: [],
    };
  }

  if (state === 'watchlist') {
    const next = summary.nextUnwatched;
    return {
      state,
      label: `Oscars ${OSCARS_SPOTLIGHT_YEAR}: watchlist`,
      meta:
        daysLeft === null
          ? `${summary.progressPct}% ukończone`
          : `${daysLeft} dni do gali • ${summary.progressPct}% ukończone`,
      title: next?.title || 'Watchlist domknięty',
      copy: next
        ? [next.runtime, next.categories.slice(0, 2).join(' • ')].filter(Boolean).join(' • ') || 'Najmocniejszy nieobejrzany kandydat.'
        : 'Wszystkie tytuły z listy są już oznaczone jako obejrzane.',
      highlights: summary.topRated
        ? [
            {
              title: 'Top ocena',
              detail: `${summary.topRated.title} • ${formatMaybeRating(summary.topRated.rating) || '-/10'}`,
            },
          ]
        : [],
    };
  }

  if (summary.winnersCount > 0) {
    const topWinner = summary.topWinner;
    return {
      state,
      label: `Oscars ${OSCARS_SPOTLIGHT_YEAR}: archiwum`,
      meta: `${summary.winnersCount} zwycięskich tytułów zapisanych`,
      title: topWinner?.title || 'Wyniki zostały zapisane',
      copy: topWinner
        ? `${topWinner.categories.slice(0, 3).join(' • ')}`
        : 'Wyniki zostały już zachowane w liście Oscarów.',
      highlights: summary.winnerItems.slice(0, 3).map((entry) => ({
        title: entry.title,
        detail: entry.categories.slice(0, 3).join(' • '),
      })),
    };
  }

  return {
    state,
    label: 'Filmy',
    meta: `${summary.watched}/${summary.total} obejrzane`,
    title: summary.topRated?.title || 'Hub filmowy',
    copy: summary.topRated
      ? `Najwyżej ocenione teraz: ${formatMaybeRating(summary.topRated.rating) || '-/10'}.`
      : 'Tu będą kolejne listy, festiwale i Twoja własna biblioteka filmów.',
    highlights: [],
  };
}

export async function maybeSyncOscarResults({
  mode,
  year = OSCARS_SPOTLIGHT_YEAR,
  now = new Date(),
  syncFn,
  storage = getStorage(),
  throttleMs = DEFAULT_RESULTS_SYNC_THROTTLE_MS,
} = {}) {
  if (mode !== 'api' || !Number.isFinite(year) || !isOscarsResultsWindow(now) || typeof syncFn !== 'function') {
    return { attempted: false, skipped: true };
  }

  const key = `${RESULTS_SYNC_STORAGE_PREFIX}_${year}`;
  const currentTs = Date.now();
  const lastTs = storage ? Number(storage.getItem(key) || 0) : 0;
  if (Number.isFinite(lastTs) && currentTs - lastTs < throttleMs) {
    return { attempted: false, skipped: true, throttled: true };
  }

  if (storage) {
    try {
      storage.setItem(key, String(currentTs));
    } catch {}
  }

  try {
    const response = await syncFn(false, year);
    return { attempted: true, ok: true, response };
  } catch (error) {
    return { attempted: true, ok: false, error };
  }
}

export function getFilmsCollectionSummary() {
  return FILMS_COLLECTIONS.map((item) => ({ ...item }));
}

export function describeWinnerLine(item) {
  if (!item) return '';
  const detail = firstItalicTitle(item.detail || '');
  return detail || '';
}
