import { fetchOscars, updateOscars, getOscarsMode, resolveOscarsMode } from './oscars-data.js';
import { splitCategories } from './oscars-categories.js';

const $ = (id) => document.getElementById(id);
const TARGET_DATE = '2026-03-14';
const MS_DAY = 24 * 60 * 60 * 1000;
const OSCARS_YEAR = 2026;
let DATA_MODE = getOscarsMode();

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

function isWatched(value) {
  if (value === true) return true;
  if (value === false || value === null || value === undefined) return false;
  if (typeof value === 'number') return value === 1;
  const s = String(value).trim().toUpperCase();
  return ['1', 'TRUE', 'YES', 'TAK'].includes(s);
}

function parseRuntimeMinutes(value) {
  if (!value) return null;
  const s = String(value).toLowerCase();

  let hours = 0;
  let mins = 0;

  const h = s.match(/(\d+(?:[.,]\d+)?)\s*h/);
  if (h) hours = Number(h[1].replace(',', '.'));

  const m = s.match(/(\d+(?:[.,]\d+)?)\s*min/);
  if (m) mins = Number(m[1].replace(',', '.'));

  if (!h && !m) {
    const n = s.match(/(\d+(?:[.,]\d+)?)/);
    if (n) mins = Number(n[1].replace(',', '.'));
  }

  if (!Number.isFinite(hours) && !Number.isFinite(mins)) return null;
  return Math.round((Number(hours) || 0) * 60 + (Number(mins) || 0));
}

function getRuntimeMinutes(item) {
  return (
    parseRuntimeMinutes(item.runtime) ??
    parseRuntimeMinutes(item.runtime_helper) ??
    parseRuntimeMinutes(item.runtime_helper_2)
  );
}


function daysLeftInclusive(targetIso) {
  const [y, m, d] = targetIso.split('-').map(Number);
  const target = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.round((target - today) / MS_DAY);
  return Math.max(1, diff + 1);
}

function formatMinutes(mins) {
  if (!Number.isFinite(mins)) return '-';
  const total = Math.max(0, Math.round(mins));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h <= 0) return `${m}min`;
  return `${h}h ${String(m).padStart(2, '0')}min`;
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

function findNext(list) {
  return list
    .filter((i) => !isWatched(i.watched))
    .sort((a, b) => String(a.title || '').localeCompare(String(b.title || '')))[0] || null;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

let currentNextId = null;

function computeTimeStats(list) {
  const remaining = list.filter((i) => !isWatched(i.watched));
  const remainingMinutes = remaining.reduce((sum, item) => {
    const m = getRuntimeMinutes(item);
    return Number.isFinite(m) ? sum + m : sum;
  }, 0);

  const daysLeft = daysLeftInclusive(TARGET_DATE);
  const requiredPerDay = remainingMinutes / daysLeft;

  let suggested = null;
  let bestDiff = Infinity;

  remaining.forEach((item) => {
    const m = getRuntimeMinutes(item);
    if (!Number.isFinite(m)) return;
    const diff = Math.abs(m - requiredPerDay);
    if (diff < bestDiff) {
      bestDiff = diff;
      suggested = { item, minutes: m };
    }
  });

  return { remainingMinutes, requiredPerDay, suggested, remainingCount: remaining.length };
}

function renderFrom(list) {
  const stats = computeStats(list);
  const timeStats = computeTimeStats(list);

  setText('oscars-watched', String(stats.watched));
  setText('oscars-left', String(stats.left));
  setText('oscars-avg', stats.avg === null ? '-' : stats.avg.toFixed(2));

  const bar = $('oscars-progress-bar');
  if (bar) bar.style.width = `${stats.pct}%`;
  setText('oscars-progress-text', `${stats.watched} / ${stats.total} - ${stats.pct}%`);

  const next = findNext(list);
  const suggestedItem = timeStats.suggested ? timeStats.suggested.item : null;
  const displayItem = suggestedItem || next;
  const markBtn = $('oscars-mark-btn');
  const rateInput = $('oscars-rate-input');

  const poster = $('oscars-next-poster');
  if (poster) {
    if (!displayItem) {
      poster.classList.add('is-empty');
      poster.innerHTML = '<span>-</span>';
    } else if (displayItem.poster_url) {
      poster.classList.remove('is-empty');
      poster.innerHTML = '';
      const img = document.createElement('img');
      img.src = displayItem.poster_url;
      img.alt = displayItem.title ? `${displayItem.title} poster` : 'Poster';
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      poster.appendChild(img);
    } else {
      poster.classList.add('is-empty');
      const letter = String(displayItem.title || '?').trim().charAt(0).toUpperCase() || '?';
      poster.innerHTML = `<span>${letter}</span>`;
    }
  }

  if (!displayItem) {
    currentNextId = null;
    setText('oscars-next-title', 'All watched');
    setText('oscars-next-meta', '-');
    if (markBtn) markBtn.disabled = true;
    if (rateInput) rateInput.disabled = true;
  } else {
    currentNextId = displayItem.id;
    setText('oscars-next-title', displayItem.title || '-');
    const metaParts = [];
    if (displayItem.type) metaParts.push(displayItem.type);
    if (displayItem.runtime) metaParts.push(displayItem.runtime);
    const categories = splitCategories(displayItem.nominated_categories);
    if (categories.length) metaParts.push(...categories);
    setText('oscars-next-meta', metaParts.length ? metaParts.join('\n') : '-');
    if (markBtn) markBtn.disabled = false;
    if (rateInput) rateInput.disabled = false;
  }

  if (stats.left <= 0) {
    setText('oscars-required', '0min');
    setText('oscars-suggested', 'Brak nieobejrzanych tytu??w.');
  } else {
    setText('oscars-required', formatMinutes(timeStats.requiredPerDay));
    if (displayItem) {
      const mins = getRuntimeMinutes(displayItem);
      const title = displayItem.title || '-';
      setText('oscars-suggested', mins ? `${title} (${formatMinutes(mins)})` : title);
    } else {
      setText('oscars-suggested', 'Brak nieobejrzanych tytu??w.');
    }
  }


  const foot = $('oscars-updated');
  if (foot && !foot.hasAttribute('data-fixed')) {
    foot.textContent = `Updated: ${formatDatePl()}`;
  }
}

async function refresh() {
  try {
    const list = await fetchOscars(OSCARS_YEAR);
    renderFrom(list);
  } catch (e) {
    console.error(e);
    const foot = $('oscars-updated');
    if (foot && !foot.hasAttribute('data-fixed')) {
      foot.textContent = DATA_MODE === 'api' ? 'API offline. Start the local server.' : 'Data offline.';
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  if (!$('oscars-card')) return;

  (async () => {
    DATA_MODE = await resolveOscarsMode();
    await refresh();

    const markBtn = $('oscars-mark-btn');
    const rateInput = $('oscars-rate-input');

    if (markBtn) {
      markBtn.addEventListener('click', async () => {
        if (!currentNextId) return;
        try {
          const rating = rateInput && rateInput.value ? Number(rateInput.value) : null;
          await updateOscars(
            currentNextId,
            {
              watched: true,
              rating_1_10: rating
            },
            OSCARS_YEAR
          );
          if (rateInput) rateInput.value = '';
          await refresh();
        } catch (e) {
          console.error(e);
          const foot = $('oscars-updated');
          if (foot && !foot.hasAttribute('data-fixed')) {
            foot.textContent = 'Save failed.';
          }
        }
      });
    }
  })();
});
