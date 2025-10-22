// js/main_weather.js
import { REFRESH_MS } from './config.js';
import { fetchWeather } from './api/openMeteo.js';
import { setStatus as uiSetStatus, renderNow, renderNext } from './ui/render_weather_api.js';

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

async function loadWeather() {
  if (!mountsReady() || busy) return;
  busy = true;
  try {
    setStatusSafe('Ładowanie…');
    const data = await fetchWeather();
    if (Q.now()) renderNow(data.now);
    if (Q.next()) renderNext(data.nextHours);
    setStatusSafe(`Ostatnia aktualizacja: ${new Date(data.updatedIso).toLocaleString('pl-PL')}`);
  } catch (e) {
    setStatusSafe(`Błąd: ${e?.message || 'nieznany'}`);
  } finally {
    busy = false;
  }
}

ready(() => {
  loadWeather();
  if (mountsReady()) setInterval(loadWeather, REFRESH_MS || 300000);
});
