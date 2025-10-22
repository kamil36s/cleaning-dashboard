// src/js/heroClock.js

const pad = n => (n < 10 ? '0' + n : '' + n);

const DAYS_PL = ['Niedziela','Poniedziałek','Wtorek','Środa','Czwartek','Piątek','Sobota'];
const MONTHS_PL = ['stycznia','lutego','marca','kwietnia','maja','czerwca','lipca','sierpnia','września','października','listopada','grudnia'];

function formatDatePL(d) {
  return `${DAYS_PL[d.getDay()]} • ${d.getDate()} ${MONTHS_PL[d.getMonth()]} ${d.getFullYear()}`;
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
  if (c) c.textContent = formatDatePL(now);
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
