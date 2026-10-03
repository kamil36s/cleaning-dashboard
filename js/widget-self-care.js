import { onDomReady } from './dom-ready.js';
import { API, WRITE_TOKEN } from './config.js';
import { bust, isSameDay, parseDateMaybe } from './utils.js';
import { formatLoadedAt, loadTimeSuffix, startLoadTimer } from './load-timing.js';
import { scheduleUndo } from './undo-toast.js';

const SELF_CARE_APARTMENT_ID = 'self-care';
const SELF_CARE_SHEET_NAME = 'emotional_tracker';
const SELF_CARE_RECENT_DAYS = 7;
const MAX_WIDGET_TASKS = 6;

const STATUS_TO_DO = 'TO DO';
const STATUS_DONE = 'DONE';
const STATUS_IDEA = 'IDEA';
const STATUS_RECENTLY_DONE = 'RECENTLY DONE';

const STATUS_ORDER = {
  [STATUS_TO_DO]: 0,
  [STATUS_IDEA]: 1,
  [STATUS_RECENTLY_DONE]: 2,
  [STATUS_DONE]: 3,
};

const STATUS_CLASS = {
  [STATUS_TO_DO]: 'to-do',
  [STATUS_DONE]: 'done',
  [STATUS_IDEA]: 'idea',
  [STATUS_RECENTLY_DONE]: 'recently-done',
};

const IDEA_CATEGORY_KINDS = new Set(['self-care', 'mind', 'body', 'recovery']);

const CATEGORY_CLASS = {
  health: 'health',
  'self-care': 'self-care',
  mind: 'mind',
  body: 'body',
  recovery: 'recovery',
  fallback: 'fallback',
};

const $ = (selector) => document.querySelector(selector);

let widgetTasks = [];
let lastLoadMs = null;
let lastLoadedAt = null;

const escapeHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const normalizeText = (value) => String(value || '')
  .toLowerCase()
  .normalize('NFKD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/ł/g, 'l')
  .replace(/[^a-z0-9]+/g, ' ')
  .trim();

const getCategoryKind = (task) => {
  const normalized = normalizeText(task?.category);
  if (normalized === 'zdrowie') return 'health';
  if (normalized === 'self care') return 'self-care';
  if (normalized === 'mind') return 'mind';
  if (normalized === 'body') return 'body';
  if (normalized === 'recovery') return 'recovery';
  return 'fallback';
};

const numberValue = (value) => {
  const parsed = Number(String(value ?? '').replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : 0;
};

const isActionNeeded = (task) => {
  if (task?.overdue) return true;
  return numberValue(task?.nextDueIn) === 0;
};

const daysSinceLastDone = (task, today = new Date()) => {
  const last = parseDateMaybe(task?.lastDone);
  if (!last) return Number.POSITIVE_INFINITY;
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startLast = new Date(last.getFullYear(), last.getMonth(), last.getDate());
  return Math.floor((startToday - startLast) / 86400000);
};

const getRecentWindowDays = (task) => {
  const freq = numberValue(task?.freq);
  if (freq > 0) return Math.min(freq, SELF_CARE_RECENT_DAYS);
  return SELF_CARE_RECENT_DAYS;
};

const getSelfCareStatus = (task) => {
  const kind = getCategoryKind(task);

  if (IDEA_CATEGORY_KINDS.has(kind)) {
    return daysSinceLastDone(task) <= getRecentWindowDays(task)
      ? STATUS_RECENTLY_DONE
      : STATUS_IDEA;
  }

  return isActionNeeded(task) ? STATUS_TO_DO : STATUS_DONE;
};

const statusClass = (status) => STATUS_CLASS[status] || STATUS_CLASS[STATUS_IDEA];
const categoryClass = (task) => CATEGORY_CLASS[getCategoryKind(task)] || CATEGORY_CLASS.fallback;

function selfCareApiUrl(params = {}) {
  const url = new URL(API);
  url.searchParams.set('apartment', SELF_CARE_APARTMENT_ID);
  url.searchParams.set('sheet', SELF_CARE_SHEET_NAME);
  Object.entries(params).forEach(([key, value]) => {
    if (value == null || value === '') return;
    url.searchParams.set(key, value);
  });
  return url.toString();
}

function normalizeTasks(payload) {
  const rowsRaw = Array.isArray(payload?.tasks) ? payload.tasks : [];
  return rowsRaw
    .filter((task) => task && String(task.task || '').trim() !== '')
    .filter((task) => numberValue(task.freq) > 0)
    .map((task) => ({
      ...task,
      room: task.room || task.category || '',
      category: task.category || task.room || '',
    }));
}

async function getSelfCareTasks() {
  const response = await fetch(bust(selfCareApiUrl()), { cache: 'no-store' });
  if (!response.ok) throw new Error(response.statusText);
  const payload = await response.json();
  if (payload && payload.ok === false) {
    throw new Error(payload.error || 'self_care_api_error');
  }
  return normalizeTasks(payload);
}

async function markSelfCareDone(row) {
  const response = await fetch(bust(selfCareApiUrl({
    action: 'done',
    row,
    token: WRITE_TOKEN,
  })), { method: 'GET', cache: 'no-store' });
  if (!response.ok) return false;
  const payload = await response.json().catch(() => null);
  return !!payload?.ok;
}

async function recordSelfCareTimelineEvent(task, fallbackTitle) {
  try {
    await fetch('/api/timeline/activity/self-care', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: task?.task || fallbackTitle || 'self-care',
        category: task?.category || '',
        occurredAt: new Date().toISOString(),
      }),
    });
  } catch {
    // The dashboard action already succeeded; timeline capture is best-effort.
  }
}

async function syncSelfCareTimelineHistory(tasks) {
  const events = (tasks || []).map((task) => {
    const parsed = parseDateMaybe(task?.lastDone);
    if (!parsed) return null;
    return { title: task.task, category: task.category || '', occurredAt: parsed.toISOString() };
  }).filter(Boolean);
  if (!events.length) return;
  try {
    await fetch('/api/timeline/activity/self-care', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events }),
    });
  } catch {
    // History sync is best-effort and must not block the widget.
  }
}

function renderFooter(status = 'ok') {
  const footer = $('#sc-updated');
  if (!footer) return;
  const loaded = lastLoadedAt ? formatLoadedAt(lastLoadedAt) : '-';
  const load = loadTimeSuffix(lastLoadMs);
  const prefix = status === 'error' ? 'Blad synchronizacji' : 'Ostatnia synchronizacja';
  footer.textContent = `${prefix}: ${loaded}${load ? ` - ${load}` : ''}`;
}

function getStatusCounts(tasks) {
  const counts = {
    [STATUS_TO_DO]: 0,
    [STATUS_DONE]: 0,
    [STATUS_IDEA]: 0,
    [STATUS_RECENTLY_DONE]: 0,
  };

  tasks.forEach((task) => {
    counts[getSelfCareStatus(task)] += 1;
  });

  return counts;
}

function updateCounters(tasks) {
  const counts = getStatusCounts(tasks);
  const actionTotal = counts[STATUS_TO_DO] + counts[STATUS_DONE];
  const actionDone = counts[STATUS_DONE];
  const pct = actionTotal ? Math.round((actionDone / actionTotal) * 100) : 0;

  $('#sc-to-do').textContent = counts[STATUS_TO_DO];
  $('#sc-done').textContent = counts[STATUS_DONE];
  $('#sc-idea').textContent = counts[STATUS_IDEA];
  $('#sc-recently-done').textContent = counts[STATUS_RECENTLY_DONE];

  const bar = $('#sc-progress-bar');
  if (bar) {
    bar.style.width = `${pct}%`;
    bar.style.background = 'linear-gradient(90deg, #9bcfba, #8bd7c5)';
    bar.className = 'progress-fill';
  }

  const text = $('#sc-progress-text');
  if (text) text.textContent = `${actionDone} / ${actionTotal} - ${pct}%`;

  const zero = $('#sc-zerostate');
  if (zero) zero.hidden = (counts[STATUS_TO_DO] + counts[STATUS_IDEA]) !== 0;
}

function renderList(tasks) {
  const box = $('#sc-list');
  if (!box) return;

  const decorated = tasks
    .map((task) => ({ ...task, _status: getSelfCareStatus(task) }))
    .sort((a, b) => {
      const statusDiff = STATUS_ORDER[a._status] - STATUS_ORDER[b._status];
      if (statusDiff !== 0) return statusDiff;
      return (a.task || '').localeCompare(b.task || '');
    });

  const actionItems = decorated
    .filter((task) => task._status === STATUS_TO_DO)
    .slice(0, MAX_WIDGET_TASKS);

  const ideaItems = decorated
    .filter((task) => task._status === STATUS_IDEA)
    .slice(0, MAX_WIDGET_TASKS);

  const renderItems = (items) => items.map((task) => {
    const row = task.row ?? task.row_id;
    const meta = task.category || '';
    const klass = statusClass(task._status);
    const catClass = categoryClass(task);
    return `
      <div class="sc-item sc-status-${klass} sc-category-${catClass}">
        <div class="sc-item-text">
          <div class="title">${escapeHtml(task.task || '-')}</div>
          ${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ''}
        </div>
        <button class="sc-btn sc-status-${klass} sc-category-${catClass}" data-row="${row}">
          ${task._status}
        </button>
      </div>
    `;
  }).join('');

  const renderSection = (title, items, emptyText) => `
    <section class="sc-section">
      <div class="sc-section-title">${escapeHtml(title)}</div>
      <div class="sc-section-list">
        ${items.length ? renderItems(items) : `<div class="sc-section-empty">${escapeHtml(emptyText)}</div>`}
      </div>
    </section>
  `;

  box.innerHTML = [
    renderSection('TO DO', actionItems, 'Brak rzeczy z deadline albo rotacji.'),
    renderSection('IDEA', ideaItems, 'Brak pomyslow self-care.'),
  ].join('');
}

function renderTodayLog(tasks) {
  const list = $('#sc-today-list');
  if (!list) return;

  const empty = $('#sc-today-empty');
  const count = $('#sc-today-count');
  const today = new Date();
  const items = tasks
    .map((task) => ({ task, dt: parseDateMaybe(task.lastDone) }))
    .filter(({ dt }) => dt && isSameDay(dt, today))
    .sort((a, b) => (b.dt?.getTime?.() || 0) - (a.dt?.getTime?.() || 0))
    .map(({ task, dt }) => ({
      title: task.task || '-',
      category: task.category || '',
      ts: dt?.getTime?.() || 0,
    }));

  list.innerHTML = items.map((item) => {
    const meta = item.category ? `<span class="today-log-meta">${escapeHtml(item.category)}</span>` : '';
    return `
      <div class="today-log-item">
        <span class="today-log-dot" aria-hidden="true"></span>
        <span class="today-log-task">${escapeHtml(item.title || '-')}</span>
        ${meta}
      </div>
    `;
  }).join('');

  const hasAny = items.length > 0;
  list.hidden = !hasAny;
  if (empty) empty.hidden = hasAny;
  if (count) {
    count.textContent = String(items.length);
    count.title = 'Zrobione dzisiaj';
    count.setAttribute('aria-label', `Self-care zrobione dzisiaj: ${items.length}`);
  }
}

function applyTasks(tasks) {
  widgetTasks = Array.isArray(tasks) ? tasks : [];
  updateCounters(widgetTasks);
  renderList(widgetTasks);
  renderTodayLog(widgetTasks);
}

async function refreshWidget() {
  const stopTimer = startLoadTimer();
  const tasks = await getSelfCareTasks();
  lastLoadMs = stopTimer();
  lastLoadedAt = new Date();
  applyTasks(tasks);
  void syncSelfCareTimelineHistory(tasks);
  renderFooter();
}

onDomReady(async () => {
  const widget = document.querySelector('.card.self-care');
  if (!widget) return;

  try {
    await refreshWidget();

    widget.addEventListener('click', async (event) => {
      const btn = event.target.closest('.sc-btn');
      if (!btn) return;

      const row = Number(btn.dataset.row || 0);
      if (!row) return;

      const prev = btn.textContent;
      const taskMeta = widgetTasks.find((item) => Number(item.row ?? item.row_id) === row);
      const title = taskMeta?.task
        || btn.closest('.sc-item')?.querySelector('.title')?.textContent?.trim()
        || 'self-care';

      btn.disabled = true;
      btn.classList.add('is-pending');
      btn.textContent = 'Zaznaczone';

      scheduleUndo({
        message: `Zaznaczone: ${title}`,
        duration: 4000,
        onUndo: () => {
          btn.disabled = false;
          btn.classList.remove('is-pending');
          btn.textContent = prev;
        },
        onCommit: async () => {
          btn.textContent = '...';
          try {
            const ok = await markSelfCareDone(row);
            if (!ok) {
              throw new Error('markSelfCareDone_failed');
            }
            await recordSelfCareTimelineEvent(taskMeta, title);
            await refreshWidget();
          } catch (error) {
            console.error(error);
            btn.disabled = false;
            btn.classList.remove('is-pending');
            btn.textContent = prev;
            renderFooter('error');
          }
        },
      });
    });
  } catch (error) {
    console.error(error);
    renderFooter('error');
  }
});
