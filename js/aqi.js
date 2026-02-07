// js/aqi.js
// Kafelek AQI dla stacji GIOŚ: Kraków, al. Krasińskiego (ID 400)

import GIOS from './api/gios.js';
import { t, onLocaleChange } from './i18n.js';
import { fmtDateTimeShort } from './utils.js';

const CLASS_BY_KEY = {
  very_good: 'k-verygood',
  good: 'k-good',
  moderate: 'k-moderate',
  sufficient: 'k-sufficient',
  bad: 'k-bad',
  very_bad: 'k-verybad'
};

const KEY_BY_PL_LABEL = {
  'Bardzo dobry': 'very_good',
  'Dobry': 'good',
  'Umiarkowany': 'moderate',
  'Dostateczny': 'sufficient',
  'Zły': 'bad',
  'Bardzo zły': 'very_bad'
};

const LEVEL_FALLBACK = {
  very_good: 'Bardzo dobry',
  good: 'Dobry',
  moderate: 'Umiarkowany',
  sufficient: 'Dostateczny',
  bad: 'Zły',
  very_bad: 'Bardzo zły'
};

const DESC_FALLBACK = {
  very_good: 'Jakość bardzo dobra. Aktywność na zewnątrz bez ograniczeń.',
  good: 'Jakość zadowalająca. Ryzyko niskie.',
  moderate: 'Akceptowalna; wrażliwi mogą odczuć skutki.',
  sufficient: 'Ogranicz intensywny wysiłek na zewnątrz.',
  bad: 'Unikaj aktywności na zewnątrz; wrażliwi nie wychodzą.',
  very_bad: 'Pozostań w pomieszczeniach; aktywność odradzana.'
};

const ORDER = ['very_good','good','moderate','sufficient','bad','very_bad'];

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

function setClass(el, key){
  if (!el) return;
  el.classList.remove('k-verygood','k-good','k-moderate','k-sufficient','k-bad','k-verybad');
  if (CLASS_BY_KEY[key]) el.classList.add(CLASS_BY_KEY[key]);
}

function levelLabel(key){
  return t(`aqi.levels.${key}`, null, LEVEL_FALLBACK[key] || key);
}

function levelDesc(key){
  return t(`aqi.descriptions.${key}`, null, DESC_FALLBACK[key] || '');
}

function dominantText(value){
  if (!value) return t('aqi.dominant_empty', null, 'Dominujące: —');
  return t('aqi.dominant_label', { value }, `Dominujące: ${value}`);
}

function updatedText(iso){
  if (!iso) return '—';
  const datetime = fmtDateTimeShort(iso);
  return t('aqi.updated', { datetime }, `Ostatnia aktualizacja: ${datetime}`);
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
function normalizeSnapshot(raw){
  if (!raw || typeof raw !== 'object') return null;
  if (raw.levelKey || raw.levelKey === null) return raw;

  const levelKey = toLevelKey(raw.name) || null;
  let dominantValue = null;

  if (typeof raw.dominantValue === 'string') {
    dominantValue = raw.dominantValue;
  } else if (typeof raw.dominant === 'string') {
    const m = raw.dominant.split(':');
    if (m.length > 1) dominantValue = m.slice(1).join(':').trim();
  }

  return {
    ts: raw.ts || Date.now(),
    location: raw.location || null,
    levelKey,
    dominantValue,
    updatedIso: raw.updatedIso || new Date().toISOString(),
    vals: raw.vals || {}
  };
}

function readCache(){
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    return normalizeSnapshot(JSON.parse(raw));
  } catch(e){
    return null;
  }
}

function writeCache(snap){
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(snap)); }
  catch(e){}
}

let lastSnapshot = null;

// render snapshot
function applySnapshot(snap){
  const card = $('#aq-card');
  if (!card || !snap) return;

  lastSnapshot = snap;

  const locationText = snap.location || t('aqi.location_default', null, 'Kraków, al. Krasińskiego');
  const levelKey = snap.levelKey;

  setText('#aq-location', locationText);
  setText('#aq-index', levelKey ? levelLabel(levelKey) : t('aqi.no_index', null, 'Brak indeksu'));
  setText('#aq-desc', levelKey ? levelDesc(levelKey) : t('aqi.no_index_desc', null, 'Brak indeksu GIOŚ dla tej stacji teraz.'));
  setText('#aq-dominant', dominantText(snap.dominantValue));
  setText('#aq-updated', updatedText(snap.updatedIso));

  setClass(card, levelKey || null);

  // słupki
  setBar('pm25', snap.vals?.pm25);
  setBar('pm10', snap.vals?.pm10);
  setBar('no2',  snap.vals?.no2);
  setBar('o3',   snap.vals?.o3);
}

function buildSnapshot(raw){
  return {
    ts: Date.now(),
    location: raw.location || null,
    levelKey: raw.levelKey || null,
    dominantValue: raw.dominantValue || null,
    updatedIso: raw.updatedIso || new Date().toISOString(),
    vals: raw.vals || {}
  };
}

function isGoodSnapshot(snap){
  if (!snap) return false;
  if (!snap.levelKey) return false;
  return true;
}

// util do normalizacji kodu parametru sensora
const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g,'');

// convert index numeric to label key
const fromValue = v => (Number.isFinite(v) && ORDER[v]) ? ORDER[v] : null;

function toLevelKey(label){
  if (!label) return null;
  const raw = String(label).trim();
  if (ORDER.includes(raw)) return raw;
  return KEY_BY_PL_LABEL[raw] || null;
}

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
    const levelKey = toLevelKey(idx.category) || fromValue(idx.value) || null;

    // dominujący składnik
    const codeMap = { PYL:'PM', SO2:'SO₂', NO2:'NO₂', O3:'O₃', CO:'CO', C6H6:'C₆H₆' };
    let dominantValue = null;
    if (idx.dominantCode && codeMap[idx.dominantCode]) {
      dominantValue = codeMap[idx.dominantCode];
    } else if (idx.parts) {
      let worst = null;
      let worstVal = -1;
      for (const [k,v] of Object.entries(idx.parts)) {
        const key = toLevelKey(v) || null;
        const score = key ? ORDER.indexOf(key) : -1;
        if (score > worstVal) {
          worstVal = score;
          worst = k.toUpperCase();
        }
      }
      dominantValue = worst || null;
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
      levelKey,
      dominantValue,
      vals,
      updatedIso: new Date().toISOString()
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
    setText('#aq-location', t('aqi.location_default', null, 'Kraków, al. Krasińskiego'));
    setText('#aq-index', t('aqi.no_index', null, 'Brak indeksu'));
    setText('#aq-desc', t('aqi.error_desc', null, 'Błąd pobierania lub brak danych.'));
    setText('#aq-dominant', t('aqi.dominant_empty', null, 'Dominujące: —'));
    setText('#aq-updated', '—');
    setClass($('#aq-card'), null);

    setBar('pm25', NaN);
    setBar('pm10', NaN);
    setBar('no2',  NaN);
    setBar('o3',   NaN);
  }
}

onLocaleChange(() => {
  if (lastSnapshot) applySnapshot(lastSnapshot);
});

