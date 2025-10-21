import { DATA } from './state.js';
import { fmtDate } from './utils.js';
import { iconFor } from './icons.js';
export let LAST_LIST = [];

function metrics(arr){
  const today = arr.filter(t => !t.overdue && t.nextDueIn === 0).length;
  const ov = arr.filter(t => t.overdue).length;
  const total = arr.length;
  const delays = arr
    .filter(t => t.overdue && t.daysSince != null)
    .map(t => (t.daysSince || 0) - (t.freq || 0));
  const avg = delays.length ? (delays.reduce((a,b)=>a+b,0) / delays.length) : 0;
  return { today, ov, total, avg: Math.max(0, Math.round(avg * 10) / 10) };
}

const daysOver = t => t.overdue ? Math.max(0, (t.daysSince || 0) - (t.freq || 0)) : 0;
const isDue = t => !t.overdue && t.nextDueIn === 0;
const isDead = t => t.overdue && daysOver(t) > 7;
const usedFrac = t => (t.daysSince != null && t.freq > 0) ? (t.daysSince / t.freq) : (t.overdue ? 1.01 : 0);
const pctOf = t => Math.min(100, Math.max(0, Math.round(usedFrac(t) * 100)));
const colorOf = t => {
  if (isDead(t)) return 'dead';
  if (t.overdue) return 'red';
  if (isDue(t)) return 'yellow';
  if (usedFrac(t) >= 0.8) return 'lime';
  return 'green';
};
const keyOf = t => [t.room||'', t.category||'', t.task||''].join('|');

// DEAD(0) -> OVERDUE(1) -> DUE(2) -> COMING(3) -> FRESH(4)
function statusRank(t) {
  const over   = t.overdue;
  const dead   = isDead(t);
  const due    = isDue(t);
  const coming = !over && !due && usedFrac(t) >= 0.8;

  if (dead)   return 0;
  if (over)   return 1;
  if (due)    return 2;
  if (coming) return 3;
  return 4; // fresh
}

function cardHTML(t){
  const id = (t.row ?? t.row_id ?? null);
  const pct = pctOf(t);
  const color = colorOf(t);
  const over = t.overdue;
  const dead = isDead(t);
  const due = isDue(t);
  const coming = !over && !due && usedFrac(t) >= 0.8;
  const frameClass = dead ? 'dead' : (over ? 'overdue' : (due ? 'due' : (coming ? 'coming' : '')));
  const dueLabel = over ? `OVERDUE by ${(t.daysSince||0)-(t.freq||0)}d` : (due ? 'DUE today' : `Next in ${t.nextDueIn}d`);

  return `
  <div class="card ${frameClass}" data-key="${keyOf(t)}">
    <div class="header">
      <div style="flex:1">
        <div class="title">
          <span class="ico">${iconFor(t.category)}</span>
          <span>${t.task}</span>
        </div>
        <div class="meta">
          ${t.room || ''} • every ${t.freq || '?'}d
          ${t.lastDone ? `• last: ${fmtDate(t.lastDone)}` : ''}
          • row ${id ?? '—'}
        </div>
      </div>
      <div class="badges">
        ${dead ? `<button class="pill pill-dead"  data-row="${id}" data-action="done">DEAD</button>` : ''}
        ${(!dead && over) ? `<button class="pill pill-over" data-row="${id}" data-action="done">OVERDUE</button>` : ''}
        ${(!dead && !over && due) ? `<button class="pill pill-due"  data-row="${id}" data-action="done">DUE</button>` : ''}
        ${(!dead && !over && !due && coming) ? `<button class="pill pill-coming" data-row="${id}" data-action="done">COMING</button>` : ''}
        ${(!dead && !over && !due && !coming) ? `<button class="pill pill-fresh"  data-row="${id}" data-action="done">FRESH</button>` : ''}
      </div>
    </div>
    <div class="progress"><div class="${color}" style="width:${pct}%"></div></div>
    <div class="footer">
      <span>${dueLabel}</span>
      <span>${t.daysSince != null ? `Since: ${t.daysSince}d` : 'Never'}</span>
    </div>
  </div>`;
}

export function render(){
  // KPI
  const m = metrics(DATA);
  document.getElementById('kpi-today').textContent = m.today;
  document.getElementById('kpi-overdue').textContent = m.ov;
  document.getElementById('kpi-total').textContent = m.total;
  document.getElementById('kpi-delay').textContent = `${m.avg}d`;

  // Fill selects once
  const roomSel = document.getElementById('room');
  if (roomSel.options.length === 1){
    [...new Set(DATA.map(t=>t.room).filter(Boolean))].sort()
      .forEach(r => { const o = document.createElement('option'); o.value=r; o.textContent=r; roomSel.appendChild(o); });
  }
  const catSel = document.getElementById('category');
  if (catSel && catSel.options.length === 1){
    [...new Set(DATA.map(t=>t.category).filter(Boolean))].sort()
      .forEach(c => { const o = document.createElement('option'); o.value=c; o.textContent=c; catSel.appendChild(o); });
  }

  // Filters
  const dueOnly = document.getElementById('dueOnly')?.checked ?? false;
  const room = roomSel.value;
  const category = catSel ? catSel.value : 'ALL';
  const sort = document.getElementById('sort').value;

  let list = DATA.slice();
  if (room !== 'ALL') list = list.filter(t => t.room === room);
  if (category !== 'ALL') list = list.filter(t => t.category === category);
  if (dueOnly) list = list.filter(t => t.overdue || t.nextDueIn === 0);

  const safeNext = x => (Number.isFinite(x) ? x : 9999);
  list.sort((a, b) => {
  if (sort === 'room')    return (a.room || '').localeCompare(b.room || '');
  if (sort === 'soonest') return safeNext(a.nextDueIn) - safeNext(b.nextDueIn);
  // default: DEAD -> OVERDUE -> DUE -> COMING -> FRESH
  return statusRank(a) - statusRank(b)
      || safeNext(a.nextDueIn) - safeNext(b.nextDueIn)
      || (a.task || '').localeCompare(b.task || '');
});

  // ...po list.sort(...)
LAST_LIST = list;

  const grid = document.getElementById('grid');
  const existing = new Map([...grid.children].map(el => [el.getAttribute('data-key'), el]));
  const nextKeys = new Set();

  for (const t of list){
    const k = keyOf(t);
    nextKeys.add(k);
    const html = cardHTML(t);

    if (existing.has(k)){
      const el = existing.get(k);
      const tmp = document.createElement('div');
      tmp.innerHTML = html.trim();
      const newEl = tmp.firstElementChild;

      const oldBar = el.querySelector('.progress > div');
      const newBar = newEl.querySelector('.progress > div');
      if (oldBar && newBar){
        const newWidth = newBar.style.width;
        const newClass = newBar.className;
        oldBar.className = newClass;
        requestAnimationFrame(()=>{ oldBar.style.width = newWidth; });
      }

      el.querySelector('.badges').innerHTML = newEl.querySelector('.badges').innerHTML;
      el.querySelector('.title').innerHTML = newEl.querySelector('.title').innerHTML;
      el.querySelector('.meta').innerHTML = newEl.querySelector('.meta').innerHTML;

      el.className = `card ${isDead(t) ? 'dead' : (t.overdue ? 'overdue' : (isDue(t) ? 'due' : (usedFrac(t) >= 0.8 ? 'coming' : '')))}`;
      el.classList.add('update');
      setTimeout(()=>el.classList.remove('update'), 300);
    } else {
      const tmp = document.createElement('div');
      tmp.innerHTML = html.trim();
      const el = tmp.firstElementChild;
      el.classList.add('enter');
      grid.appendChild(el);
      requestAnimationFrame(()=> el.classList.remove('enter'));
    }
  }

  for (const [k, el] of existing.entries()){
    if (!nextKeys.has(k)){
      el.classList.add('leaving');
      el.addEventListener('transitionend', () => el.remove(), { once:true });
      setTimeout(()=> el.remove(), 400);
    }
  }
}