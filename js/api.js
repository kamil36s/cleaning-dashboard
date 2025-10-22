import { API, WRITE_TOKEN } from './config.js';
import { bust } from './utils.js';
import { setData } from './state.js';
import { render } from './render.js';

export async function bootDebug(){
  try {
    const r = await fetch(bust(`${API}?debug=1`));
    const t = await r.text();
    console.log('[BOOT] API debug payload:', t);
  } catch(e){ console.error('[BOOT] API debug ERR:', e); }
}

export async function fetchData(){
  const btn = document.getElementById('refresh');
  if (btn) { btn.disabled = true; btn.textContent = 'Refreshing…'; }
  try {
    const r = await fetch(bust(API), { cache:'no-store' });
    const j = await r.json();
    const rows = (j.tasks || [])
      .filter(t => t && String(t.task || '').trim() !== '')
      .filter(t => Number(t.freq) > 0);
    setData(rows);
    render();
  } catch(e){
    console.error('Refresh failed:', e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Refresh'; }
  }
}

export async function markDone(row){
  try {
    if (!row || row < 1) { console.error('Bad row', row); return; }
    const url = `${API}?action=done&row=${encodeURIComponent(row)}&token=${encodeURIComponent(WRITE_TOKEN)}`;
    const resp = await fetch(bust(url), { method:'GET', cache:'no-store' });
    const text = await resp.text();
    let j; try { j = JSON.parse(text); } catch { console.error('Non-JSON from GAS'); return; }
    if (!j.ok) { console.error('GAS error:', j.error); return; }
    await fetchData();
  } catch(e){ console.error('markDone exception:', e); }
}

// zwraca tablicę tasków
export async function getTasks(){
  const url = 'https://script.google.com/macros/s/AKfycbwZXHkLhl9HlcTHHzJjcMzAzDMRYhboDs3_kR8oAq9SdeKgBOp9JbWFS6P2OaiczpmXkg/exec'; // Twój URL
  const r = await fetch(url, {cache:'no-store'});
  if(!r.ok) throw new Error(r.statusText);
  const json = await r.json();
  return json.tasks; // dopasuj do realnego pola
}
