const DEFAULT_STATIC_BASE = './data/oscars';

const MODE_VALUES = new Set(['api', 'static', 'auto']);

let cachedConfig = null;

function normalizeMode(value) {
  if (!value) return null;
  const mode = String(value).trim().toLowerCase();
  return MODE_VALUES.has(mode) ? mode : null;
}

function normalizeBase(value) {
  if (!value) return '';
  const raw = String(value).trim();
  if (!raw) return '';
  return raw.endsWith('/') ? raw.slice(0, -1) : raw;
}

function readMeta(name) {
  if (typeof document === 'undefined') return null;
  const el = document.querySelector(`meta[name="${name}"]`);
  return el ? el.getAttribute('content') : null;
}

function readDataset() {
  if (typeof document === 'undefined') return {};
  const root = document.documentElement;
  const body = document.body;
  return {
    mode: root?.dataset?.oscarsMode || body?.dataset?.oscarsMode || null,
    apiBase: root?.dataset?.oscarsApiBase || body?.dataset?.oscarsApiBase || null,
    staticBase: root?.dataset?.oscarsStaticBase || body?.dataset?.oscarsStaticBase || null
  };
}

function readWindowConfig() {
  if (typeof window === 'undefined') return {};
  const cfg = window.__OSCARS_CONFIG__;
  if (!cfg || typeof cfg !== 'object') return {};
  return {
    mode: cfg.mode,
    apiBase: cfg.apiBase,
    staticBase: cfg.staticBase
  };
}

function readParams() {
  if (typeof window === 'undefined' || !window.location) return {};
  try {
    const params = new URLSearchParams(window.location.search);
    return {
      mode: params.get('oscars_mode') || params.get('mode'),
      apiBase: params.get('oscars_api') || params.get('apiBase'),
      staticBase: params.get('oscars_static') || params.get('staticBase')
    };
  } catch {
    return {};
  }
}

function isLocalhost() {
  if (typeof window === 'undefined' || !window.location) return false;
  const host = window.location.hostname;
  return host === 'localhost' || host === '127.0.0.1';
}

function readEnv(key) {
  try {
    return import.meta?.env?.[key];
  } catch {
    return null;
  }
}

export function getOscarsConfig() {
  if (cachedConfig) return cachedConfig;

  const envMode = readEnv('VITE_OSCARS_MODE');
  const envApiBase = readEnv('VITE_OSCARS_API_BASE');
  const envStaticBase = readEnv('VITE_OSCARS_STATIC_BASE');

  const params = readParams();
  const winCfg = readWindowConfig();
  const dataset = readDataset();

  const metaMode = readMeta('oscars:mode');
  const metaApiBase = readMeta('oscars:api-base');
  const metaStaticBase = readMeta('oscars:static-base');

  const local = isLocalhost();

  const mode =
    normalizeMode(params.mode) ||
    normalizeMode(winCfg.mode) ||
    normalizeMode(dataset.mode) ||
    normalizeMode(metaMode) ||
    normalizeMode(envMode) ||
    'auto';

  const apiBase =
    normalizeBase(params.apiBase) ||
    normalizeBase(winCfg.apiBase) ||
    normalizeBase(dataset.apiBase) ||
    normalizeBase(metaApiBase) ||
    normalizeBase(envApiBase) ||
    ((mode === 'api' || mode === 'auto') && local ? 'http://127.0.0.1:8000' : '');

  const staticBase =
    normalizeBase(params.staticBase) ||
    normalizeBase(winCfg.staticBase) ||
    normalizeBase(dataset.staticBase) ||
    normalizeBase(metaStaticBase) ||
    normalizeBase(envStaticBase) ||
    DEFAULT_STATIC_BASE;

  cachedConfig = {
    mode,
    apiBase,
    staticBase,
    isLocalhost: local
  };

  return cachedConfig;
}

export function getOscarsMode() {
  return getOscarsConfig().mode;
}
