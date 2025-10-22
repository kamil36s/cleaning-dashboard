// js/aqi.js
// Render kafla AQI dla stacji GIOŚ: Kraków, al. Krasińskiego (ID 400)

import GIOS from './api/gios.js';

const CLASS_BY_NAME = {
  "Bardzo dobry":"k-verygood",
  "Dobry":"k-good",
  "Umiarkowany":"k-moderate",
  "Dostateczny":"k-sufficient",
  "Zły":"k-bad",
  "Bardzo zły":"k-verybad"
};

const DESC_PL = {
  "Bardzo dobry":"Jakość bardzo dobra. Aktywność na zewnątrz bez ograniczeń.",
  "Dobry":"Jakość zadowalająca. Ryzyko niskie.",
  "Umiarkowany":"Akceptowalna; wrażliwi mogą odczuć skutki.",
  "Dostateczny":"Ogranicz intensywny wysiłek na zewnątrz.",
  "Zły":"Unikaj aktywności na zewnątrz; wrażliwi nie wychodzą.",
  "Bardzo zły":"Pozostań w pomieszczeniach; aktywność odradzana."
};

const ORDER = ["Bardzo dobry","Dobry","Umiarkowany","Dostateczny","Zły","Bardzo zły"];
const MAXS  = { pm25:150, pm10:200, no2:200, o3:240 };

function $(s){ return document.querySelector(s); }
function setText(sel, text){ const el = $(sel); if (el) el.textContent = text; }
function pct(v, max){ return Math.max(0, Math.min(100, (v/max)*100)); }
function setClass(el, name){
  el.classList.remove('k-verygood','k-good','k-moderate','k-sufficient','k-bad','k-verybad');
  if (CLASS_BY_NAME[name]) el.classList.add(CLASS_BY_NAME[name]);
}
function setBar(param, value){
  const bar = document.getElementById(`bar-${param}`);
  const label = document.getElementById(`val-${param}`);
  if (!bar || !label) return;
  const key = param.toLowerCase();
  const max = MAXS[key] || 100;
  const v = Number(value);
  bar.style.width = Number.isFinite(v) ? `${pct(v, max)}%` : '0%';
  label.textContent = Number.isFinite(v) ? `${v.toFixed(1)} µg/m³` : '— µg/m³';
}
const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g,''); // "PM2.5" -> "pm25"
const fromValue = v => (Number.isFinite(v) && ORDER[v]) ? ORDER[v] : null;

export async function renderAqiForKrasinskiego() {
  const stationId = 400;
  const card = $('#aq-card');
  if (!card) return;

  try {
    // 1) Indeks (już znormalizowany przez gios.js)
    const idx = await GIOS.getIndex(stationId);
    const name = idx.category || fromValue(idx.value) || null;

    setText('#aq-location', 'Kraków, al. Krasińskiego');
    setText('#aq-badge', name || '—');
    setText('#aq-index', name || 'Brak indeksu');
    setText('#aq-desc', name ? DESC_PL[name] : 'Brak indeksu GIOŚ dla tej stacji teraz.');
    setClass(card, name);

    // 2) Dominujące (preferuj kod z API, inaczej najgorsza część)
    const codeMap = { PYL:'PM', SO2:'SO2', NO2:'NO2', O3:'O3', CO:'CO', C6H6:'C6H6' };
    if (idx.dominantCode && codeMap[idx.dominantCode]) {
      setText('#aq-dominant', `Dominujące: ${codeMap[idx.dominantCode]}`);
    } else if (idx.parts) {
      let worst = null, worstVal = -1;
      for (const [k,v] of Object.entries(idx.parts)) {
        const score = ORDER.indexOf(v);
        if (score > worstVal) { worstVal = score; worst = k.toUpperCase(); }
      }
      setText('#aq-dominant', `Dominujące: ${worst ?? '—'}`);
    } else {
      setText('#aq-dominant', 'Dominujące: —');
    }

    // 3) Słupki PM2.5/PM10/NO2/O3
    const wanted = { pm25:null, pm10:null, no2:null, o3:null };

    let sensors = [];
    try {
      const res = await GIOS.getSensors(stationId);
      sensors = Array.isArray(res) ? res : [];
    } catch (e) {
      console.warn('[AQI] getSensors failed:', e);
    }

    for (const s of sensors) {
      const code = norm(s?.param?.paramCode);
      if (code in wanted && !wanted[code]) wanted[code] = s.id;
    }

    const vals = {};
    for (const [code, sid] of Object.entries(wanted)) {
      if (!sid) { setBar(code, NaN); vals[code] = NaN; continue; }
      try {
        const d = await GIOS.getSensorData(sid);
        const v = d && Array.isArray(d.values) ? d.values.find(x => x && x.value != null)?.value : null;
        vals[code] = Number.isFinite(v) ? v : NaN;
        setBar(code, vals[code]);
      } catch (e) {
        console.warn('[AQI] getSensorData failed:', code, e);
        vals[code] = NaN;
        setBar(code, NaN);
      }
    }

    // 4) Znacznik czasu
    setText('#aq-updated', `Ostatnia aktualizacja: ${new Date().toLocaleString('pl-PL')}`);

  } catch (e) {
    console.error('[AQI] Error:', e);
    setText('#aq-badge', '—');
    setText('#aq-index', 'Brak indeksu');
    setText('#aq-desc', 'Błąd pobierania lub brak danych.');
    setClass($('#aq-card'), null);
  }
}
