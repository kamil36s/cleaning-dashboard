import { bootDebug, fetchData, markDone } from './api.js';
import { render } from './render.js';
import { LAST_LIST } from './render.js';
import { OPENAI_PROXY } from './config.js';

// Initial debug ping
bootDebug();

// UI events
const grid = document.getElementById('grid');
const refreshBtn = document.getElementById('refresh');
const dueOnly = document.getElementById('dueOnly');
const roomSel = document.getElementById('room');
const sortSel = document.getElementById('sort');
const catSel = document.getElementById('category');

refreshBtn.addEventListener('click', fetchData);
dueOnly.addEventListener('change', render);
roomSel.addEventListener('change', render);
sortSel.addEventListener('change', render);
catSel.addEventListener('change', render);

grid.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button.pill');
  if (!btn) return;
  const row = Number(btn.dataset.row || 0);
  if (!row) return;
  const prev = btn.textContent;
  btn.disabled = true; btn.textContent = '...';
  try { await markDone(row); } finally { btn.disabled = false; btn.textContent = prev; }
});

function summarizeVisible(){
  const box = document.getElementById('ai-box');
  const out = document.getElementById('ai-output');
  if (!box || !out) return;

  // Minimalny, ucięty payload
  const payload = LAST_LIST.slice(0, 40).map(t => ({
    task: t.task,
    room: t.room,
    category: t.category,
    status: (t.overdue
      ? (((t.daysSince||0)-(t.freq||0)) > 7 ? 'dead' : 'overdue')
      : (t.nextDueIn===0 ? 'due' : (((t.daysSince||0)/(t.freq||1)) >= .8 ? 'coming':'fresh')))
  }));

  box.hidden = false;
  box.classList.add('loading');
  out.textContent = 'Thinking…';

  fetch(OPENAI_PROXY, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ tasks: payload })
})
.then(async r => {
  const txt = await r.text().catch(()=> r.statusText);
  if (!r.ok) throw new Error(`${r.status} ${txt}`);
  return JSON.parse(txt);
})
.then(j => { out.textContent = j.text || '(no content)'; })
.catch(err => { out.textContent = `AI error: ${String(err.message||err)}`; })
.finally(()=> box.classList.remove('loading'));
}

document.getElementById('gen-tips')
  .addEventListener('click', summarizeVisible);

// Start
fetchData();