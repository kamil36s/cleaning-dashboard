// js/api/gios.js

// Detect whether we are running on localhost (Vite dev or local static server).
const IS_LOCAL =
  location.hostname === 'localhost' ||
  location.hostname === '127.0.0.1';

const WORKER_BASE = 'https://gios.kamil36s.workers.dev';
const LOCAL_PROXY_BASE = '/gios';
const REMOTE_FALLBACK_BASE = `${WORKER_BASE}/gios`;

function normalizeBase(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  return raw.replace(/\/+$/, '');
}

function resolveConfiguredBase() {
  return normalizeBase(import.meta?.env?.VITE_GIOS_BASE);
}

function buildBaseCandidates() {
  const configuredBase = resolveConfiguredBase();
  const primaryBase = configuredBase || (IS_LOCAL ? LOCAL_PROXY_BASE : REMOTE_FALLBACK_BASE);
  const bases = [];
  const seen = new Set();

  const push = (base) => {
    const normalized = normalizeBase(base);
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    bases.push(normalized);
  };

  push(primaryBase);

  // Vite serves /gios locally, but server.py does not.
  // If the local proxy is missing, fall back to the Worker.
  if (IS_LOCAL) push(LOCAL_PROXY_BASE);

  push(REMOTE_FALLBACK_BASE);
  return bases;
}

const BASE_CANDIDATES = buildBaseCandidates();

function buildUrl(base, path) {
  return `${base}/${String(path || '').replace(/^\/+/, '')}`;
}

async function fetchJsonFromBase(base, path) {
  const url = buildUrl(base, path);
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    const error = new Error(`HTTP ${response.status} for ${url}\n${body.slice(0, 200)}`);
    error.status = response.status;
    error.url = url;
    throw error;
  }
  return response.json();
}

async function getJson(path) {
  let lastError = null;

  for (const base of BASE_CANDIDATES) {
    try {
      return await fetchJsonFromBase(base, path);
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError || new Error(`Failed to fetch GIOS resource: ${path}`);
}

// ---------- AQ INDEX ----------

function normalizeIndex(json) {
  const a = json?.AqIndex || {};
  const g = k => (k in a ? a[k] : null);
  const computedAt = g('Data wykonania obliczeń indeksu');
  const partCategory = (code) => (
    g(`Nazwa kategorii indeksu dla wskaźnika ${code}`) ??
    g(`Nazwa kategorii indeksu dla wskażnika ${code}`)
  );

  return {
    stationId: g('Identyfikator stacji pomiarowej'),
    value: g('Wartość indeksu'),
    category: g('Nazwa kategorii indeksu'),
    parts: {
      so2: partCategory('SO2'),
      no2: partCategory('NO2'),
      pm10: partCategory('PM10'),
      pm25: partCategory('PM2.5'),
      o3: partCategory('O3'),
    },
    dominantCode: g('Kod zanieczyszczenia krytycznego'),
    computedAt: typeof computedAt === 'string'
      ? computedAt.trim().replace(' ', 'T')
      : computedAt,
  };
}

// ---------- SENSORS / STANOWISKA ----------

function gatherStringsDeep(obj, bucket = []) {
  if (obj == null) return bucket;
  if (typeof obj === 'string') {
    bucket.push(obj);
    return bucket;
  }
  if (Array.isArray(obj)) {
    for (const value of obj) gatherStringsDeep(value, bucket);
    return bucket;
  }
  if (typeof obj === 'object') {
    for (const value of Object.values(obj)) gatherStringsDeep(value, bucket);
    return bucket;
  }
  return bucket;
}

function guessParamCodeDeep(rawSensor) {
  if (rawSensor['Wskaźnik - wzór']) return String(rawSensor['Wskaźnik - wzór']).trim();
  if (rawSensor['Wskaźnik - kod']) return String(rawSensor['Wskaźnik - kod']).trim();

  const strings = gatherStringsDeep(rawSensor, []);
  const pollutantRegex = /^(PM ?2\.?5|PM ?10|NO2|SO2|O3|CO|C6H6)$/i;
  for (const value of strings) {
    const trimmed = value.trim();
    if (pollutantRegex.test(trimmed)) return trimmed;
  }

  return undefined;
}

function normalizeSensor(rawSensor) {
  const id =
    rawSensor['Identyfikator stanowiska'] ??
    rawSensor['Identyfikator stanowiska pomiarowego'] ??
    rawSensor['Identyfikator czujnika'] ??
    rawSensor['Identyfikator stacji'] ??
    rawSensor.id ??
    rawSensor.sensorId;

  const paramCode = guessParamCodeDeep(rawSensor);

  return {
    id,
    paramCode,
    _raw: rawSensor,
  };
}

// ---------- PUBLIC API WRAPPER ----------

const GIOS = {
  async getIndex(stationId) {
    const raw = await getJson(`pjp-api/v1/rest/aqindex/getIndex/${stationId}`);
    console.log('DEBUG getIndex raw response', raw);
    return normalizeIndex(raw);
  },

  async getSensors(stationId) {
    const data = await getJson(`pjp-api/v1/rest/station/sensors/${stationId}`);

    console.log('DEBUG getSensors raw response', data);

    let arr =
      data['Lista stanowisk pomiarowych dla podanej stacji'] ??
      data['lista stanowisk pomiarowych dla podanej stacji'] ??
      data.sensors ??
      data.items ??
      data['@graph'] ??
      data.data;

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
    const raw = await getJson(`pjp-api/v1/rest/data/getData/${sensorId}`);
    console.log('DEBUG getSensorData raw response', sensorId, raw);
    return raw;
  }
};

export default GIOS;
