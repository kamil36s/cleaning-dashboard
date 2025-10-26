// js/aqi.js
// Kafelek AQI dla stacji GIOŚ: Kraków, al. Krasińskiego (ID 400)

import GIOS from './api/gios.js';

const CLASS_BY_NAME = {
  "Bardzo dobry": "k-verygood",
  "Dobry": "k-good",
  "Umiarkowany": "k-moderate",
  "Dostateczny": "k-sufficient",
  "Zły": "k-bad",
  "Bardzo zły": "k-verybad"
};

const DESC_PL = {
  "Bardzo dobry": "Jakość bardzo dobra. Aktywność na zewnątrz bez ograniczeń.",
  "Dobry": "Jakość zadowalająca. Ryzyko niskie.",
  "Umiarkowany": "Akceptowalna; wrażliwi mogą odczuć skutki.",
  "Dostateczny": "Ogranicz intensywny wysiłek na zewnątrz.",
  "Zły": "Unikaj aktywności na zewnątrz; wrażliwi nie wychodzą.",
  "Bardzo zły": "Pozostań w pomieszczeniach; aktywność odradzana."
};

const ORDER = ["Bardzo dobry","Dobry","Umiarkowany","Dostateczny","Zły","Bardzo zły"];

// skala końcowa do wyświetlenia pod paskiem
const MAXS  = { pm25:150, pm10:200, no2:200, o3:240 };

// progi zdrowotne per parametr [prog1, prog2]
const THRESH = {
  pm25: [15, 35],
  pm10: [25, 50],
  no2:  [40,100],
  o3:   [60,120],
};

// progi jakości (granice między zielony/żółty/czerwony z tooltipa)
// każdy [goodTop, midTop, maxScale]
const THRESHOLDS = {
  pm25:[15, 35, MAXS.pm25],
  pm10:[25, 50, MAXS.pm10],
  no2: [40,100, MAXS.no2],
  o3:  [60,120, MAXS.o3]
};

const CACHE_KEY   = 'aqi:lastGood';
const THROTTLE_MS = 15 * 60 * 1000; // 15 min

function $(s){ return document.querySelector(s); }
function setText(sel, text){ const el = $(sel); if (el) el.textContent = text; }

function pct(v, max){
  return Math.max(0, Math.min(100, (v/max)*100));
}

function setClass(el, name){
  if (!el) return;
  el.classList.remove('k-verygood','k-good','k-moderate','k-sufficient','k-bad','k-verybad');
  if (CLASS_BY_NAME[name]) el.classList.add(CLASS_BY_NAME[name]);
}

// nowa wersja setBar:
// - ustawia podział segmentów wg progów
// - ustawia marker (pozycja + tekst)
// - ustawia tekst w tooltipie
function setBar(param, value){
  const track   = document.querySelector(`.aqi-track.track-${param}`);
  const fillEl  = document.getElementById(`bar-${param}`);
  const marker  = document.getElementById(`marker-${param}`);
  const markerVal = document.getElementById(`marker-val-${param}`);
  const tick1   = document.getElementById(`brk1-${param}`);
  const tick2   = document.getElementById(`brk2-${param}`);

  if (!track || !fillEl || !marker || !markerVal) return;

  const max = MAXS[param];
  const v   = Number(value);

  // procent aktualnej wartości
  const p = (Number.isFinite(v) && max)
    ? Math.min(100, (v / max) * 100)
    : 0;

  // wypełnienie paska do aktualnej wartości
  fillEl.style.width = `${p}%`;

  // marker nad/bieżący
  marker.style.left = `${p}%`;
  markerVal.textContent = Number.isFinite(v) ? v.toFixed(1) : '—';

  // ustaw labelki progów
  const limits = THRESH[param];
  if (limits && limits.length === 2 && max) {
    const p1 = (limits[0] / max) * 100;
    const p2 = (limits[1] / max) * 100;

    if (tick1) tick1.style.left = `${p1}%`;
    if (tick2) tick2.style.left = `${p2}%`;

    // ustaw tło segmentów (CSS zmienne --seg1 --seg2 --seg3)
    track.style.setProperty('--seg1', `${p1}%`);
    track.style.setProperty('--seg2', `${p2 - p1}%`);
    track.style.setProperty('--seg3', `${100 - p2}%`);
  }
}


// helpers cache
function readCache(){
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch(e){
    return null;
  }
}

function writeCache(snap){
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(snap)); }
  catch(e){}
}

// render snapshot
function applySnapshot(snap){
  const card = $('#aq-card');
  if (!card || !snap) return;

  setText('#aq-location', snap.location || 'Kraków, al. Krasińskiego');
  setText('#aq-index', snap.name || 'Brak indeksu');
  setText('#aq-desc', snap.desc || 'Brak indeksu GIOŚ dla tej stacji teraz.');
  setText('#aq-dominant', snap.dominant || 'Dominujące: —');
  setText('#aq-updated', snap.updatedText || '—');

  setClass(card, snap.name || null);

  // słupki
  setBar('pm25', snap.vals?.pm25);
  setBar('pm10', snap.vals?.pm10);
  setBar('no2',  snap.vals?.no2);
  setBar('o3',   snap.vals?.o3);
}

function buildSnapshot(raw){
  return {
    ts: Date.now(),
    location: 'Kraków, al. Krasińskiego',
    name:     raw.name || null,
    desc:     raw.desc || null,
    dominant: raw.dominant || null,
    updatedText: `Ostatnia aktualizacja: ${new Date().toLocaleString('pl-PL')}`,
    vals: {
      pm25: raw.vals?.pm25,
      pm10: raw.vals?.pm10,
      no2:  raw.vals?.no2,
      o3:   raw.vals?.o3
    }
  };
}

function isGoodSnapshot(snap){
  if (!snap) return false;
  if (!snap.name) return false;
  if (snap.name === 'Brak indeksu') return false;
  return true;
}

// util do normalizacji kodu parametru sensora
const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g,'');

// convert index numeric to label
const fromValue = v => (Number.isFinite(v) && ORDER[v]) ? ORDER[v] : null;

// wyciąga ostatnią sensowną wartość z odpowiedzi sensora GIOŚ
function extractNumericValueFromSensorData(d){
  const list =
    d['Lista danych pomiarowych'] ??
    d['lista danych pomiarowych'] ??
    d['values'] ??
    d['data'] ??
    [];

  if (!Array.isArray(list)) return NaN;

  for (const rec of list) {
    if (!rec || typeof rec !== 'object') continue;

    for (const v of Object.values(rec)) {
      if (v == null) continue;

      // odrzuć stringi które wyglądają jak data "2025-10-26T10:57:20"
      if (typeof v === 'string') {
        const t = v.trim();
        if (/^\d{4}-\d{2}-\d{2}/.test(t)) continue; // yyyy-mm-dd...
        if (/^\d{1,2}:\d{2}/.test(t)) continue;     // hh:mm...
      }

      const num = parseFloat(v);

      // sensowny odczyt stężenia to kilkadziesiąt, kilkaset max
      // rok 2025 odrzucamy
      if (Number.isFinite(num) && num >= 0 && num < 1000) {
        return num;
      }
    }
  }

  return NaN;
}

// GŁÓWNA FUNKCJA
export async function renderAqiForKrasinskiego() {
  const stationId = 400;
  const card = $('#aq-card');
  if (!card) return;

  const cache = readCache();

  // throttle 15 min
  if (cache && (Date.now() - cache.ts) < THROTTLE_MS) {
    applySnapshot(cache);
    return;
  }

  try {
    // 1) indeks jakości
    const idx  = await GIOS.getIndex(stationId);
    const name = idx.category || fromValue(idx.value) || null;

    // dominujący składnik
    const codeMap = { PYL:'PM', SO2:'SO₂', NO2:'NO₂', O3:'O₃', CO:'CO', C6H6:'C₆H₆' };
    let dominantTxt = 'Dominujące: —';
    if (idx.dominantCode && codeMap[idx.dominantCode]) {
      dominantTxt = `Dominujące: ${codeMap[idx.dominantCode]}`;
    } else if (idx.parts) {
      let worst = null;
      let worstVal = -1;
      for (const [k,v] of Object.entries(idx.parts)) {
        const score = ORDER.indexOf(v);
        if (score > worstVal) {
          worstVal = score;
          worst = k.toUpperCase();
        }
      }
      dominantTxt = `Dominujące: ${worst ?? '—'}`;
    }

    // 2) lista sensorów -> mapowanie do pm25/pm10/no2/o3
    const wanted = { pm25:null, pm10:null, no2:null, o3:null };
    let sensors = [];
    try {
      const res = await GIOS.getSensors(stationId);
      sensors = Array.isArray(res) ? res : [];
    } catch(e){
      console.warn('[AQI] getSensors failed:', e);
    }

    for (const s of sensors) {
      const code = norm(s?.paramCode); // po naszej normalizacji
      if (code in wanted && !wanted[code]) {
        wanted[code] = s.id;
      }
    }

        // 3) wartości z sensorów
    const vals = {};
    for (const [code, sid] of Object.entries(wanted)) {
      if (!sid) { vals[code] = NaN; continue; }

      try {
        const d = await GIOS.getSensorData(sid);
        const num = extractNumericValueFromSensorData(d);
        vals[code] = Number.isFinite(num) ? num : NaN;
      } catch(e){
        console.warn('[AQI] getSensorData failed:', code, e);
        vals[code] = NaN;
      }
    }


    // 4) snapshot
    const freshSnap = buildSnapshot({
      name,
      desc: name ? DESC_PL[name] : 'Brak indeksu GIOŚ dla tej stacji teraz.',
      dominant: dominantTxt,
      vals
    });

    // 5) renderuj
    applySnapshot(freshSnap);

    // 6) cache
    if (isGoodSnapshot(freshSnap)) {
      writeCache(freshSnap);
    } else if (isGoodSnapshot(cache)) {
      applySnapshot(cache);
    }

  } catch (e) {
    console.error('[AQI] Error:', e);

    if (isGoodSnapshot(cache)) {
      applySnapshot(cache);
      return;
    }

    // fallback totalny
    setText('#aq-location', 'Kraków, al. Krasińskiego');
    setText('#aq-index', 'Brak indeksu');
    setText('#aq-desc', 'Błąd pobierania lub brak danych.');
    setText('#aq-dominant', 'Dominujące: —');
    setText('#aq-updated', '—');
    setClass($('#aq-card'), null);

    setBar('pm25', NaN);
    setBar('pm10', NaN);
    setBar('no2',  NaN);
    setBar('o3',   NaN);
  }
}
