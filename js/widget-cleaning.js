import { getTasks, markDone } from './api.js';

const $ = s => document.querySelector(s);
const N = v => (v==null || v==='') ? null : Number(v);

/* ⇩⇩ DODANE ZARAZ POD N ⇩⇩ */
const daysOver = t => t.overdue ? Math.max(0, (N(t.daysSince)||0) - (N(t.freq)||0)) : 0;
const isDead   = t => t.overdue && daysOver(t) > 7;   // DEAD = spóźnione > 7 dni
/* ⇧⇧ DODANE ⇧⇧ */

const COMING_FRAC = 0.92;

const usedFrac = t =>
  t.overdue ? 1.01 :
  (Number.isFinite(N(t.freq)) && N(t.freq) > 0 && Number.isFinite(N(t.daysSince)))
    ? N(t.daysSince) / N(t.freq)
    : 0;

const isDue    = t => !t.overdue && N(t.nextDueIn) === 0;
const isComing = t => !t.overdue && !isDue(t) && usedFrac(t) >= COMING_FRAC;

const deriveStatus = (t) => {
  if (isDead(t))   return 'DEAD';
  if (t.overdue)   return 'OVERDUE';
  if (isDue(t))    return 'DUE';
  if (isComing(t)) return 'COMING';
  return 'FRESH';
};

const order = { DEAD:0, OVERDUE:1, DUE:2, COMING:3, FRESH:9 };

const counters = arr => ({
  overdue: arr.filter(t => !!t.overdue).length,
  due:     arr.filter(isDue).length,
  coming:  arr.filter(isComing).length,
});

function renderList(tasks){
  const box = $('#cl-list');
  if (!box) return;

  const wanted = tasks
    .map(t => ({...t, _status: deriveStatus(t)}))
    .filter(t => ['DEAD','OVERDUE','DUE','COMING'].includes(t._status))
    .sort((a,b) => order[a._status]-order[b._status])
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
  const overdue = tasks.filter(t=>t.overdue).length;
  const due     = tasks.filter(t=>!t.overdue && t.nextDueIn===0).length;
  const coming  = tasks.filter(t=>{
    if (t.overdue || t.nextDueIn===0) return false;
    const ds = +t.daysSince||0, f = +t.freq||0;
    return f>0 && ds/f >= 0.95;
  }).length;

  $('#cl-overdue').textContent = overdue;
  $('#cl-due').textContent     = due;
  $('#cl-coming').textContent  = coming;
  const zero = $('#cl-zerostate');
  if (zero) zero.hidden = (overdue+due+coming)!==0;
}

async function refreshWidget(){
  const tasks = await getTasks();
  updateCounters(tasks);
  renderList(tasks);
}

document.addEventListener('DOMContentLoaded', async () => {
  const w = document.querySelector('.card.cleaning');
  if (!w) return;

  try {
    const tasks = await getTasks();
    const { overdue, due, coming } = counters(tasks);
    $('#cl-overdue').textContent = overdue;
    $('#cl-due').textContent     = due;
    $('#cl-coming').textContent  = coming;
    const zero = $('#cl-zerostate');
    if (zero) zero.hidden = (overdue + due + coming) !== 0;

    renderList(tasks);

    // klik w pilla: zapisz i odśwież
    w.addEventListener('click', async (ev) => {
      const btn = ev.target.closest('.cl-btn');
      if (!btn) return;
      const row = Number(btn.dataset.row || 0);
      if (!row) return;

      const prev = btn.textContent;
      btn.disabled = true; btn.textContent = '...';
      try {
        await markDone(row);      // zapis dzisiejszej daty w Sheets
        await refreshWidget();    // pobierz i przerysuj widget
      } catch (e) {
        console.error(e);
      } finally {
        btn.disabled = false; btn.textContent = prev;
      }
    });

  } catch (e) {
    console.error(e);
    const st = $('#cl-status'); if (st) st.textContent = 'error';
  }
});
