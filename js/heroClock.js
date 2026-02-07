// src/js/heroClock.js
import { get, t } from './i18n.js';

const pad = n => (n < 10 ? '0' + n : '' + n);

const FALLBACK_DAYS = ['Niedziela','Poniedziałek','Wtorek','Środa','Czwartek','Piątek','Sobota'];
const FALLBACK_MONTHS = ['stycznia','lutego','marca','kwietnia','maja','czerwca','lipca','sierpnia','września','października','listopada','grudnia'];

function pick(list, idx, fallback) {
  if (Array.isArray(list) && list[idx] != null) return list[idx];
  return fallback[idx] ?? '';
}

function formatDate(d) {
  const days = get('date.days', FALLBACK_DAYS);
  const months = get('date.months_genitive', FALLBACK_MONTHS);
  const day = pick(days, d.getDay(), FALLBACK_DAYS);
  const month = pick(months, d.getMonth(), FALLBACK_MONTHS);
  const vars = { day, date: d.getDate(), month, year: d.getFullYear() };
  return t('date.format', vars, `${day} • ${vars.date} ${month} ${vars.year}`);
}

function tick() {
  const now = new Date();
  const hhmm = pad(now.getHours()) + ':' + pad(now.getMinutes());
  const ss = pad(now.getSeconds());

  const a = document.getElementById('hero-hhmm');
  const b = document.getElementById('hero-ss');
  const c = document.getElementById('hero-date');

  if (a) a.textContent = hhmm;
  if (b) b.textContent = ss;
  if (c) c.textContent = formatDate(now);
}

function startHeroClock() {
  tick();
  setInterval(tick, 250);
}

// auto-start po załadowaniu modułu
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startHeroClock, { once: true });
} else {
  startHeroClock();
}

export { startHeroClock };
