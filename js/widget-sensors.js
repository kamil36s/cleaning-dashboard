// ./js/widget-sensors.js
import { fmtDateTimeShort } from './utils.js';
function comfortLabel(t, h) {
  // proste, rzeczowe klasy
  if (t >= 20 && t <= 24 && h >= 40 && h <= 60)
    return { cls: 'state-ok',   txt: 'Optymalny',    desc: 'temperatura i wilgotność w zalecanym przedziale' };
  if (t >= 18 && t <= 26 && h >= 35 && h <= 65)
    return { cls: 'state-warn', txt: 'Akceptowalny', desc: 'niewielkie odchylenia od optimum' };
  return { cls: 'state-bad',    txt: 'Poza zakresem', desc: 'warunki poza komfortem użytkowym' };
}
function trendText(now, prev, tol=0.05) {
  if (prev == null) return '—';
  const d = now - prev;
  if (Math.abs(d) < tol) return 'stabilnie';
  return d > 0 ? 'rośnie' : 'spada';
}

function humRange(h) {
  if (h >= 40 && h <= 60) return 'wilgotność w normie (40–60%)';
  if (h >= 30 && h < 40)  return 'sucho (30–40%)';
  if (h > 60 && h <= 70)  return 'wilgotno (60–70%)';
  return h < 30 ? 'za sucho (<30%)' : 'za wilgotno (>70%)';
}

function fmtTime(ts) {
  try {
    const d = new Date(ts * 1000);
    return fmtDateTimeShort(d);
  } catch { return '—:—'; }
}

async function fetchJSON(url) {
  const r = await fetch(url + '?t=' + Date.now(), { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

export function initSensorWidget({ url, pollMs = 60000 } = {}) {
  // elementy w Twoim HTML
  const elT   = document.getElementById('room-temp');
  const elH   = document.getElementById('room-hum');
  const elTT  = document.getElementById('temp-trend');
  const elHR  = document.getElementById('hum-range');
  const pill  = document.getElementById('comfort-pill');
  const desc  = document.getElementById('comfort-desc');
  const batt  = document.getElementById('room-batt');
  const upd   = document.getElementById('room-updated');

  let lastT = null;

  async function tick() {
    try {
      const j = await fetchJSON(url);
      const r = j.reading || {};
      const t = Number(r.temp_c);
      const h = Number(r.hum_pct);
      const b = Number(r.battery_pct);
      const ts = Number(j.timestamp || Date.now() / 1000);

      if (!Number.isFinite(t) || !Number.isFinite(h)) return;

      // liczby
      elT.textContent = Math.round(t).toString();
      elH.textContent = Math.round(h);

      // trend i zakres
      elTT.textContent = trendText(t, lastT);
      const f = (t * 9/5) + 32;
      document.getElementById('room-temp-f').textContent = `${Math.round(f)} \u00b0F`;
      elHR.textContent = humRange(h);
      lastT = t;

      // komfort
      const k = comfortLabel(t, h);
      pill.classList.remove('state-ok', 'state-warn', 'state-bad');
      pill.classList.add(k.cls);
      pill.textContent = k.txt;
      desc.textContent = k.desc;

      // meta
      if (Number.isFinite(b)) batt.textContent = b.toString();
      upd.textContent = fmtTime(ts);
    } catch (e) {
      // cicho w UI, log do konsoli
      console.warn('sensor widget fetch error', e);
    }
  }

  tick();
  setInterval(tick, pollMs);
}
