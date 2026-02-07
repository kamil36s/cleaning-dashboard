import { getTasks, markDone } from './api.js';
import {
  computeCounts,
  deriveStatus,
  isComing,
  isDead,
  isDue,
  statusOrder,
} from './cleaning-logic.js';
import { fmtTimeShort, isSameDay, parseDateMaybe } from './utils.js';
import { scheduleUndo } from './undo-toast.js';

const $ = s => document.querySelector(s);
const hasTimeInfo = (value) => {
  if (value == null || value === '') return false;
  if (value instanceof Date) return true;
  if (typeof value === 'number') return true;
  if (typeof value === 'string') return /\d:\d/.test(value);
  return false;
};

function renderList(tasks){
  const box = $('#cl-list');
  if (!box) return;
  const wanted = tasks
    .map(t => ({...t, _status: deriveStatus(t)}))
    .filter(t => ['DEAD','OVERDUE','DUE','COMING'].includes(t._status))
    .sort((a,b) => statusOrder[a._status]-statusOrder[b._status])
    .slice(0, 24);
  box.innerHTML = wanted.map(t => `
    <div class="cl-item">
      <div class="title">${t.task || '—'}</div>
      <button class="cl-btn ${t._status.toLowerCase()}" data-row="${t.row ?? t.row_id}">
        ${t._status}
      </button>
    </div>
  `).join('');
}
function updateCounters(tasks){
  const stats = computeCounts(tasks);
  $('#cl-overdue').textContent = stats.overdue;
  $('#cl-due').textContent     = stats.due;
  $('#cl-coming').textContent  = stats.coming;
  const bar = $('#cl-progress-bar');
  if (bar) {
    bar.style.width = `${stats.pct}%`;
    let cls = 'green';
    if (stats.dead > 0) cls = 'dead';
    else if (stats.overdue > 0) cls = 'red';
    else if (stats.due > 0) cls = 'yellow';
    else if (stats.coming > 0) cls = 'lime';
    bar.className = cls;
  }
  const text = $('#cl-progress-text');
  if (text) text.textContent = `${stats.ok} / ${stats.total} - ${stats.pct}%`;
  const zero = $('#cl-zerostate');
  if (zero) zero.hidden = (stats.overdue + stats.due + stats.coming) !== 0;
}

function renderTodayLog(tasks){
  const list = $('#cl-today-list');
  if (!list) return;
  const empty = $('#cl-today-empty');
  const count = $('#cl-today-count');
  const today = new Date();

  const doneToday = tasks
    .map(t => ({ t, dt: parseDateMaybe(t.lastDone) }))
    .filter(({ dt }) => dt && isSameDay(dt, today))
    .sort((a, b) => (b.dt?.getTime?.() || 0) - (a.dt?.getTime?.() || 0));

  const shown = doneToday.slice(0, 4);
  list.innerHTML = shown.map(({ t, dt }) => {
    const title = t.task || '—';
    const timeLabel = hasTimeInfo(t.lastDone) && dt ? fmtTimeShort(dt) : 'dziś';
    const metaParts = [];
    if (t.room) metaParts.push(t.room);
    if (timeLabel) metaParts.push(timeLabel);
    const meta = metaParts.join(' • ');
    return `
      <div class="today-log-item">
        <span class="today-log-dot" aria-hidden="true"></span>
        <span class="today-log-task">${title}</span>
        <span class="today-log-meta">${meta}</span>
      </div>
    `;
  }).join('');

  const hasAny = doneToday.length > 0;
  list.hidden = !hasAny;
  if (empty) empty.hidden = hasAny;
  if (count) count.textContent = String(doneToday.length);
}
async function refreshWidget(){
  const tasks = await getTasks();
  updateCounters(tasks);
  renderList(tasks);
  renderTodayLog(tasks);
}
document.addEventListener('DOMContentLoaded', async () => {
  const w = document.querySelector('.card.cleaning');
  if (!w) return;
  try {
    const tasks = await getTasks();
    updateCounters(tasks);
    renderList(tasks);
    renderTodayLog(tasks);
    // klik w pilla: zapisz i odśwież
    w.addEventListener('click', async (ev) => {
      const btn = ev.target.closest('.cl-btn');
      if (!btn) return;
      const row = Number(btn.dataset.row || 0);
      if (!row) return;
      const prev = btn.textContent;
      const title = btn.closest('.cl-item')?.querySelector('.title')?.textContent?.trim() || 'zadanie';
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
            await markDone(row, { refresh: false }); // zapis dzisiejszej daty w Sheets
            await refreshWidget(); // pobierz i przerysuj widget
          } catch (e) {
            console.error(e);
            btn.disabled = false;
            btn.classList.remove('is-pending');
            btn.textContent = prev;
          }
        }
      });
    });
  } catch (e) {
    console.error(e);
    const st = $('#cl-status'); if (st) st.textContent = 'error';
  }
});
