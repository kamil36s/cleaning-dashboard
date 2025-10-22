// js/api/gios.js
const BASE =
  (import.meta.env && import.meta.env.VITE_GIOS_BASE)
    ?? (import.meta.env.DEV ? '/gios' : 'https://api.gios.gov.pl');


async function getJson(url) {
  const r = await fetch(url); // bez Accept, unikniesz 406
  if (!r.ok) {
    const t = await r.text().catch(()=> '');
    throw new Error(`HTTP ${r.status} for ${url}\n${t.slice(0,200)}`);
  }
  return r.json();
}

// JSON-LD -> prosty obiekt
function normalizeIndex(json) {
  const a = json?.AqIndex || {};
  const g = k => (k in a ? a[k] : null);
  return {
    stationId: g('Identyfikator stacji pomiarowej'),
    value: g('Wartość indeksu'),                         // 0..5
    category: g('Nazwa kategorii indeksu'),              // "Umiarkowany" itd.
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

const GIOS = {
  async getIndex(stationId) {
    const raw = await getJson(`${BASE}/pjp-api/v1/rest/aqindex/getIndex/${stationId}`);
    return normalizeIndex(raw);
  },
  async getSensors(stationId) {
    const data = await getJson(`${BASE}/pjp-api/v1/rest/station/sensors/${stationId}`);
    return Array.isArray(data) ? data : [];
  },
  getSensorData(sensorId) {
    return getJson(`${BASE}/pjp-api/v1/rest/data/getData/${sensorId}`);
  }
};

export default GIOS;
