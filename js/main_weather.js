// js/main_weather.js
import { REFRESH_MS } from './config.js';
import { fetchWeather } from './api/openMeteo.js';
import { setStatus as uiSetStatus, renderNow, renderNext } from './ui/render_weather_api.js';
import { t, onLocaleChange } from './i18n.js';
import { fmtDateTimeShort } from './utils.js';

const Q = {
  now: () => document.getElementById('now'),
  next: () => document.getElementById('next'),
  statusEl: () => document.getElementById('status') || document.getElementById('wx-updated'),
};

function setStatusSafe(msg) {
  try {
    if (Q.statusEl()) uiSetStatus(msg);
  } catch (_) { /* brak mounta albo inne UI */ }
}

function mountsReady() {
  return Q.now() && Q.next();
}

function ready(fn) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fn, { once: true });
  } else {
    fn();
  }
}

let busy = false;
let lastStatus = { type: 'idle', updatedIso: null, error: null };

function formatUpdated(iso) {
  if (!iso) return '';
  const datetime = fmtDateTimeShort(iso);
  return t('weather.updated', { datetime }, `Ostatnia aktualizacja: ${datetime}`);
}

function setStatusLoading() {
  lastStatus = { type: 'loading', updatedIso: null, error: null };
  setStatusSafe(t('weather.loading', null, 'Ładowanie...'));
}

function setStatusUpdated(iso) {
  lastStatus = { type: 'updated', updatedIso: iso, error: null };
  setStatusSafe(formatUpdated(iso));
}

function setStatusError(message) {
  lastStatus = { type: 'error', updatedIso: null, error: message };
  setStatusSafe(t('weather.error', { message }, `Błąd: ${message}`));
}

onLocaleChange(() => {
  if (lastStatus.type === 'updated') {
    setStatusUpdated(lastStatus.updatedIso);
  } else if (lastStatus.type === 'error') {
    setStatusError(lastStatus.error);
  } else if (lastStatus.type === 'loading') {
    setStatusLoading();
  }
});

async function loadWeather() {
  if (!mountsReady() || busy) return;
  busy = true;
  try {
    setStatusLoading();
    const data = await fetchWeather();
    if (Q.now()) renderNow(data.now);
    if (Q.next()) renderNext(data.nextHours);
    setStatusUpdated(data.updatedIso);
  } catch (e) {
    const fallback = t('weather.unknown_error', null, 'nieznany');
    const msg = e?.message || fallback;
    setStatusError(msg);
  } finally {
    busy = false;
  }
}

ready(() => {
  loadWeather();
  if (mountsReady()) setInterval(loadWeather, REFRESH_MS || 300000);
});
