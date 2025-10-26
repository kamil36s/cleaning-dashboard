import { DATA } from './state.js';
import { fmtDate } from './utils.js';
import { iconFor } from './icons.js';

export let LAST_LIST = [];

// aktywny filtr po "Supplies"
const SUPPLY_FILTER = new Set();
// czy już podpięliśmy handler kliknięć do #supplies-list
let SUPPLIES_WIRED = false;

// --- CONFIG + HELPERS ---
const COMING_FRAC = 0.92;
const N = v => (v==null || v==='') ? null : Number(v);

const daysOver = t =>
  t.overdue ? Math.max(0, (N(t.daysSince)||0) - (N(t.freq)||0)) : 0;

const usedFrac = t => (
  t.overdue
    ? 1.01
    : (
        Number.isFinite(N(t.freq)) &&
        N(t.freq) > 0 &&
        Number.isFinite(N(t.daysSince))
      )
      ? (N(t.daysSince)/N(t.freq))
      : 0
);

const isDue     = t => !t.overdue && N(t.nextDueIn) === 0;
const isDead    = t => t.overdue && daysOver(t) > 7;
const isComing  = t => !t.overdue && !isDue(t) && usedFrac(t) >= COMING_FRAC;

const pctOf     = t => Math.min(100, Math.max(0, Math.round(usedFrac(t) * 100)));
const keyOf     = t => [t.room||'', t.category||'', t.task||''].join('|');

const colorOf = t => {
  if (isDead(t))   return 'dead';
  if (t.overdue)   return 'red';
  if (isDue(t))    return 'yellow';
  if (isComing(t)) return 'lime';
  return 'green';
};

// --- KPI METRYKI ---
export function metrics(arr){
  const today = arr.filter(t => !t.overdue && N(t.nextDueIn) === 0).length;
  const ov    = arr.filter(t => t.overdue).length;
  const total = arr.length;

  const delays = arr
    .filter(t => t.overdue && N(t.daysSince) != null)
    .map(t => (N(t.daysSince) || 0) - (N(t.freq) || 0));

  const avg = delays.length
    ? (delays.reduce((a,b)=>a+b,0) / delays.length)
    : 0;

  return {
    today,
    ov,
    total,
    avg: Math.max(0, Math.round(avg * 10) / 10)
  };
}

// DEAD(0) -> OVERDUE(1) -> DUE(2) -> COMING(3) -> FRESH(4)
function statusRank(t) {
  if (isDead(t))   return 0;
  if (t.overdue)   return 1;
  if (isDue(t))    return 2;
  if (isComing(t)) return 3;
  return 4;
}

// parse artykuły jednego taska -> ["Ręcznik papierowy", "Mop", ...]
function parseArticles(t){
  return (t.articles || '')
    .split(/[\n,]+/)
    .map(s => s.trim())
    .filter(Boolean);
}

// buduje chipy artykułów dla pojedynczego taska
function articlesHTMLFor(t){
  const list = parseArticles(t);
  if (!list.length) return '';

  return `<div class="needs">${
    list.map(a => `<span class="need-chip">${a}</span>`).join('')
  }</div>`;
}

// sprawdza czy task spełnia aktywny filtr SUPPLY_FILTER
// Logika: jeśli nic nie jest wybrane -> true dla wszystkich
// Jeśli wybrane ["Mop","Ręcznik"] -> task musi mieć i Mop i Ręcznik
function taskHasAllSupplies(t, filterSet){
  if (!filterSet || filterSet.size === 0) return true;

  const artsLower = new Set(parseArticles(t).map(a => a.toLowerCase()));
  for (const wanted of filterSet){
    if (!artsLower.has(wanted)) return false;
  }
  return true;
}

// zbiera unikalne artykuły z listy tasków (po filtrach room/category/dueOnly,
// ale jeszcze PRZED filtrem SUPPLY_FILTER)
function collectSupplies(tasks){
  const uniq = new Map(); // key: lowercase, val: oryginalny tekst

  for (const t of tasks){
    for (const item of parseArticles(t)){
      const key = item.toLowerCase();
      if (!uniq.has(key)){
        uniq.set(key, item);
      }
    }
  }

  return [...uniq.values()];
}

// renderuje panel "Supplies" z listą chipów
// chip pokazuje aktywność (w SUPPLY_FILTER)
function renderSuppliesBox(baseTasks){
  const box = document.getElementById('supplies-list');
  if (!box) return;

  const supplies = collectSupplies(baseTasks);

  if (!supplies.length){
    box.textContent = '—';
    return;
  }

  box.innerHTML = supplies
    .map(txt => {
      const key = txt.toLowerCase();
      const active = SUPPLY_FILTER.has(key);
      return `<span class="need-chip ${active ? 'active' : ''}" data-supply="${txt}">${txt}</span>`;
    })
    .join('');

  // podpinamy delegację kliknięć jeden raz globalnie
  if (!SUPPLIES_WIRED){
    SUPPLIES_WIRED = true;
    box.addEventListener('click', e => {
      const chip = e.target.closest('.need-chip');
      if (!chip) return;
      const raw = chip.getAttribute('data-supply');
      if (!raw) return;

      const key = raw.toLowerCase();
      if (SUPPLY_FILTER.has(key)){
        SUPPLY_FILTER.delete(key);
      } else {
        SUPPLY_FILTER.add(key);
      }

      // Po zmianie filtra robimy pełny rerender
      render();
    });
  }
}

function cardHTML(t){
  const id   = (t.row ?? t.row_id ?? null);
  const pct  = pctOf(t);
  const over = t.overdue;
  const dead = isDead(t);
  const due  = isDue(t);
  const coming = isComing(t);

  const frameClass = dead
    ? 'dead'
    : (over
        ? 'overdue'
        : (due
            ? 'due'
            : (coming ? 'coming' : '')));

  const dueLabel = over
    ? `OVERDUE by ${(N(t.daysSince)||0)-(N(t.freq)||0)}d`
    : (due
        ? 'DUE today'
        : `Next in ${N(t.nextDueIn) ?? '—'}d`);

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

        ${articlesHTMLFor(t)}
      </div>

      <div class="badges">
        ${dead
          ? `<button class="pill pill-dead"  data-row="${id}" data-action="done">DEAD</button>`
          : ''}
        ${(!dead && over)
          ? `<button class="pill pill-over" data-row="${id}" data-action="done">OVERDUE</button>`
          : ''}
        ${(!dead && !over && due)
          ? `<button class="pill pill-due"  data-row="${id}" data-action="done">DUE</button>`
          : ''}
        ${(!dead && !over && !due && coming)
          ? `<button class="pill pill-coming" data-row="${id}" data-action="done">COMING</button>`
          : ''}
        ${(!dead && !over && !due && !coming)
          ? `<button class="pill pill-fresh"  data-row="${id}" data-action="done">FRESH</button>`
          : ''}
      </div>
    </div>

    <div class="progress">
      <div class="${colorOf(t)}" style="width:${pct}%"></div>
    </div>

    <div class="footer">
      <span>${dueLabel}</span>
      <span>${N(t.daysSince) != null ? `Since: ${N(t.daysSince)}d` : 'Never'}</span>
    </div>
  </div>`;
}

export function render(){
  // KPI
  const m = metrics(DATA);
  document.getElementById('kpi-today').textContent   = m.today;
  document.getElementById('kpi-overdue').textContent = m.ov;
  document.getElementById('kpi-total').textContent   = m.total;
  document.getElementById('kpi-delay').textContent   = `${m.avg}d`;

  const kpiComing = document.getElementById('kpi-coming');
  if (kpiComing) {
    kpiComing.textContent = DATA.filter(isComing).length;
  }

  // Fill selects once
  const roomSel = document.getElementById('room');
  if (roomSel.options.length === 1){
    [...new Set(DATA.map(t=>t.room).filter(Boolean))].sort()
      .forEach(r => {
        const o = document.createElement('option');
        o.value = r;
        o.textContent = r;
        roomSel.appendChild(o);
      });
  }

  const catSel = document.getElementById('category');
  if (catSel && catSel.options.length === 1){
    [...new Set(DATA.map(t=>t.category).filter(Boolean))].sort()
      .forEach(c => {
        const o = document.createElement('option');
        o.value = c;
        o.textContent = c;
        catSel.appendChild(o);
      });
  }

  // 1. normalne filtry UI
  const dueOnly  = document.getElementById('dueOnly')?.checked ?? false;
  const room     = roomSel.value;
  const category = catSel ? catSel.value : 'ALL';
  const sort     = document.getElementById('sort').value;

  let baseList = DATA.slice();

  if (room !== 'ALL'){
    baseList = baseList.filter(t => t.room === room);
  }
  if (category !== 'ALL'){
    baseList = baseList.filter(t => t.category === category);
  }
  if (dueOnly){
    baseList = baseList.filter(t => t.overdue || N(t.nextDueIn) === 0);
  }

  // 2. panel Supplies bazuje na baseList (czyli po room/category/dueOnly)
  renderSuppliesBox(baseList);

  // 3. filtr właśnie po SUPPLY_FILTER (Mop itd)
  let list = baseList.filter(t => taskHasAllSupplies(t, SUPPLY_FILTER));

  // 4. sortowanie końcowe
  const safeNext = x => (Number.isFinite(N(x)) ? N(x) : 9999);

  list.sort((a, b) => {
    if (sort === 'room'){
      return (a.room || '').localeCompare(b.room || '');
    }
    if (sort === 'soonest'){
      return safeNext(a.nextDueIn) - safeNext(b.nextDueIn);
    }
    // default sort: DEAD -> OVERDUE -> DUE -> COMING -> FRESH
    return (
      statusRank(a) - statusRank(b) ||
      safeNext(a.nextDueIn) - safeNext(b.nextDueIn) ||
      (a.task || '').localeCompare(b.task || '')
    );
  });

  LAST_LIST = list;

  // 5. aktualizacja siatki kart
  const grid = document.getElementById('grid');

  // mapa obecnych elementów w DOM
  const existing = new Map(
    [...grid.children].map(el => [el.getAttribute('data-key'), el])
  );

  // będziemy też trzymać referencje do node'ów po update/create
  const nodeMap = new Map();
  const nextKeys = new Set();

  for (const t of list){
    const k = keyOf(t);
    nextKeys.add(k);
    const html = cardHTML(t);

    if (existing.has(k)){
      // update istniejącej karty
      const el = existing.get(k);
      const tmp = document.createElement('div');
      tmp.innerHTML = html.trim();
      const newEl = tmp.firstElementChild;

      // progress bar
      const oldBar = el.querySelector('.progress > div');
      const newBar = newEl.querySelector('.progress > div');
      if (oldBar && newBar){
        const newWidth = newBar.style.width;
        const newClass = newBar.className;
        oldBar.className = newClass;
        requestAnimationFrame(() => {
          oldBar.style.width = newWidth;
        });
      }

      // title + meta
      el.querySelector('.title').innerHTML =
        newEl.querySelector('.title').innerHTML;
      el.querySelector('.meta').innerHTML  =
        newEl.querySelector('.meta').innerHTML;

      // sekcja artykułów (.needs)
      const oldNeeds = el.querySelector('.needs');
      const newNeeds = newEl.querySelector('.needs');

      if (oldNeeds && newNeeds){
        oldNeeds.innerHTML = newNeeds.innerHTML;
      } else if (!oldNeeds && newNeeds){
        const metaEl = el.querySelector('.meta');
        if (metaEl){
          metaEl.insertAdjacentElement('afterend', newNeeds);
        }
      } else if (oldNeeds && !newNeeds){
        oldNeeds.remove();
      }

      // badges
      el.querySelector('.badges').innerHTML =
        newEl.querySelector('.badges').innerHTML;

      // klasa obramowania
      const cls = isDead(t)
        ? 'dead'
        : (t.overdue
            ? 'overdue'
            : (isDue(t)
                ? 'due'
                : (isComing(t)
                    ? 'coming'
                    : '')));

      el.className = `card ${cls}`;
      el.classList.add('update');
      setTimeout(() => el.classList.remove('update'), 300);

      nodeMap.set(k, el); // zapamiętaj referencję po update

    } else {
      // nowa karta
      const tmp = document.createElement('div');
      tmp.innerHTML = html.trim();
      const el = tmp.firstElementChild;
      el.classList.add('enter');
      grid.appendChild(el);
      requestAnimationFrame(() => el.classList.remove('enter'));

      nodeMap.set(k, el); // zapamiętaj referencję po create
    }
  }

  // 6. usuń karty które już nie pasują
  for (const [k, el] of existing.entries()){
    if (!nextKeys.has(k)){
      el.classList.add('leaving');
      el.addEventListener('transitionend', () => el.remove(), { once:true });
      setTimeout(() => el.remove(), 400);
    }
  }

  // 7. USTAW PORZĄDEK W DOM wg list (dead > overdue > due > coming > fresh)
  //    AppendChild na istniejącym elemencie przenosi go na koniec kontenera
  //    więc po tej pętli kolejność w grid = kolejność w list
  for (const t of list){
    const k = keyOf(t);
    const node = nodeMap.get(k);
    if (node){
      grid.appendChild(node);
    }
  }
}

