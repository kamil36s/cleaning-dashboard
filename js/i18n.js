// js/i18n.js

const SUPPORTED = ['pl', 'en'];
const DEFAULT_LOCALE = 'pl';
const STORAGE_KEY = 'ui:lang';
const LOCALE_BY_LANG = { pl: 'pl-PL', en: 'en-US' };

let locale = DEFAULT_LOCALE;
let dict = {};
const cache = {};
const listeners = new Set();

const normalizeLang = (lang) => {
  if (!lang) return null;
  const base = String(lang).trim().toLowerCase();
  const short = base.split('-')[0];
  return SUPPORTED.includes(short) ? short : null;
};

async function loadLocale(lang) {
  if (cache[lang]) return cache[lang];
  try {
    const res = await fetch(`/locales/${lang}.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    cache[lang] = data || {};
    return cache[lang];
  } catch (_) {
    cache[lang] = {};
    return cache[lang];
  }
}

const getPath = (obj, path) => {
  if (!path) return undefined;
  return path.split('.').reduce((acc, key) => {
    if (acc && Object.prototype.hasOwnProperty.call(acc, key)) return acc[key];
    return undefined;
  }, obj);
};

const interpolate = (str, vars) => {
  if (!vars) return str;
  return str.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, k) => (vars[k] ?? ''));
};

export function get(key, fallback) {
  const val = getPath(dict, key);
  return val === undefined ? fallback : val;
}

export function t(key, vars, fallback) {
  const val = get(key, fallback);
  if (typeof val !== 'string') {
    if (typeof fallback === 'string') return interpolate(fallback, vars);
    return typeof val === 'string' ? interpolate(val, vars) : String(val ?? '');
  }
  return interpolate(val, vars);
}

export function getLocale() { return locale; }
export function getIntlLocale() { return LOCALE_BY_LANG[locale] || 'pl-PL'; }

function applyTranslationsWhenReady() {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => applyTranslations(), { once: true });
  } else {
    applyTranslations();
  }
}

function notify() {
  listeners.forEach(fn => {
    try { fn(locale, dict); } catch (_) {}
  });
}

export function onLocaleChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export async function setLocale(next) {
  const target = normalizeLang(next) || DEFAULT_LOCALE;
  if (target === locale && Object.keys(dict).length) {
    applyTranslationsWhenReady();
    notify();
    return;
  }
  locale = target;
  try { localStorage.setItem(STORAGE_KEY, locale); } catch (_) {}
  dict = await loadLocale(locale);
  document.documentElement.lang = locale;
  applyTranslationsWhenReady();
  notify();
}

export async function initI18n() {
  let initial = null;
  try { initial = normalizeLang(localStorage.getItem(STORAGE_KEY)); } catch (_) {}
  if (!initial) initial = normalizeLang(document.documentElement.lang);
  if (!initial) initial = DEFAULT_LOCALE;
  await setLocale(initial);
}

export function applyTranslations(root = document) {
  if (!root) return;
  const nodes = root.querySelectorAll('[data-i18n]');
  nodes.forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (!key) return;
    const fallback = el.getAttribute('data-i18n-fallback') ?? el.textContent;
    const text = t(key, null, fallback);
    if (typeof text === 'string') el.textContent = text;
  });
}

export function initLangSwitch() {
  const setup = () => {
    const root = document.querySelector('.lang-switch');
    if (!root) return;

    const buttons = Array.from(root.querySelectorAll('[data-lang]'));

    const sync = () => {
      const current = getLocale();
      buttons.forEach(btn => {
        const active = btn.dataset.lang === current;
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        btn.classList.toggle('is-active', active);
      });
    };

    root.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-lang]');
      if (!btn) return;
      const next = btn.dataset.lang;
      await setLocale(next);
      sync();
    });

    onLocaleChange(sync);
    sync();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup, { once: true });
  } else {
    setup();
  }
}
