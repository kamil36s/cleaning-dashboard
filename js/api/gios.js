// js/api/gios.js

// zabezpiecz env nawet jeśli import.meta.env nie istnieje (np. na GitHub Pages)
const env = (
  typeof import !== 'undefined' &&
  import.meta &&
  import.meta.env
) ? import.meta.env : {};

// wykryj dev po hoście a nie po Vite
const DEV =
  location.hostname === 'localhost' ||
  location.hostname === '127.0.0.1';

// wybierz bazowy URL API
// kolejność:
// 1) jeśli Vite wstrzyknął VITE_GIOS_BASE to użyj tego
// 2) jeśli DEV to użyj local proxy /gios
// 3) inaczej produkcyjne API GIOŚ
const BASE =
  env.VITE_GIOS_BASE ||
  (DEV
    ? '/gios'
    : 'https://powietrze.gios.gov.pl');

// proste GET z obsługą błędów
async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    throw new Error(`HTTP ${r.status} for ${url}\n${t.slice(0,200)}`);
  }
  return r.json();
}

// ---------- AQ INDEX ----------

function normalizeIndex(json) {
  const a = json?.AqIndex || {};
  const g = k => (k in a ? a[k] : null);

  return {
    stationId: g('Identyfikator stacji pomiarowej'),
    value: g('Wartość indeksu'),
    category: g('Nazwa kategorii indeksu'),
    parts: {
      so2:  g('Nazwa kategorii indeksu dla wskażnika SO2'),
      no2:  g('Nazwa kategorii indeksu dla wskażnika NO2'),
      pm10: g('Nazwa kategorii indeksu dla wskażnika PM10'),
      pm25: g('Nazwa kategorii indeksu dla wskażnika PM2.5'),
      o3:   g('Nazwa kategorii indeksu dla wskażnika O3'),
    },
    dominantCode: g('Kod zanieczyszczenia krytycznego'),
    computedAt: g('Data wykonania obliczeń indeksu'),
  };
}

// ---------- SENSORS / STANOWISKA ----------

// zbiera wszystkie stringi z obiektu rekurencyjnie
function gatherStringsDeep(obj, bucket = []) {
  if (obj == null) return bucket;
  if (typeof obj === 'string') {
    bucket.push(obj);
    return bucket;
  }
  if (Array.isArray(obj)) {
    for (const v of obj) gatherStringsDeep(v, bucket);
    return bucket;
  }
  if (typeof obj === 'object') {
    for (const v of Object.values(obj)) gatherStringsDeep(v, bucket);
    return bucket;
  }
  return bucket;
}

// zgadnij kod zanieczyszczenia (PM2.5 / PM10 / NO2 / O3 / SO2 / CO / C6H6)
function guessParamCodeDeep(rawSensor) {
  if (rawSensor['Wskaźnik - wzór']) return String(rawSensor['Wskaźnik - wzór']).trim();
  if (rawSensor['Wskaźnik - kod'])  return String(rawSensor['Wskaźnik - kod']).trim();

  const strs = gatherStringsDeep(rawSensor, []);
  const pollutantRegex = /^(PM ?2\.?5|PM ?10|NO2|SO2|O3|CO|C6H6)$/i;
  for (const s of strs) {
    const trimmed = s.trim();
    if (pollutantRegex.test(trimmed)) return trimmed;
  }

  return undefined;
}

// normalizacja pojedynczego stanowiska
function normalizeSensor(rawSensor) {
  const id =
    rawSensor['Identyfikator stanowiska'] ??
    rawSensor['Identyfikator stanowiska pomiarowego'] ??
    rawSensor['Identyfikator czujnika'] ??
    rawSensor['Identyfikator stacji'] ??
    rawSensor['id'] ??
    rawSensor['sensorId'];

  const paramCode = guessParamCodeDeep(rawSensor);

  return {
    id,
    paramCode,
    _raw: rawSensor
  };
}

// ---------- PUBLIC API ----------

const GIOS = {
  async getIndex(stationId) {
    const url = `${BASE}/pjp-api/v1/rest/aqindex/getIndex/${stationId}`;
    const raw = await getJson(url);
    console.log('DEBUG getIndex raw response', raw);
    return normalizeIndex(raw);
  },

  async getSensors(stationId) {
    const url = `${BASE}/pjp-api/v1/rest/station/sensors/${stationId}`;
    const data = await getJson(url);

    console.log('DEBUG getSensors raw response', data);

    // szukamy tablicy stanowisk po znanych kluczach
    let arr =
      data['Lista stanowisk pomiarowych dla podanej stacji'] ??
      data['lista stanowisk pomiarowych dla podanej stacji'] ??
      data['sensors'] ??
      data['items'] ??
      data['@graph'] ??
      data['data'];

    if (!Array.isArray(arr)) {
      arr = [];
    }

    const normArr = arr.map(normalizeSensor);

    console.log('DEBUG getSensors normalized', normArr);
    if (normArr.length) {
      console.log('DEBUG sample raw sensor keys', Object.keys(normArr[0]._raw));
      console.log('DEBUG sample raw sensor obj', normArr[0]._raw);
    }

    return normArr;
  },

  async getSensorData(sensorId) {
    const url = `${BASE}/pjp-api/v1/rest/data/getData/${sensorId}`;
    const raw = await getJson(url);
    console.log('DEBUG getSensorData raw response', sensorId, raw);
    return raw;
  }
};

export default GIOS;
