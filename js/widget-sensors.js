// ./js/widget-sensors.js
import { fmtDateTimeShort } from './utils.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function comfortLabel(t, h) {
  if (t >= 20 && t <= 24 && h >= 40 && h <= 60)
    return { cls: 'state-ok',   txt: 'Optymalne',    desc: 'temperatura i wilgotność w zalecanym przedziale' };
  if (t >= 18 && t <= 26 && h >= 35 && h <= 65)
    return { cls: 'state-warn', txt: 'Akceptowalne', desc: 'niewielkie odchylenia od optimum' };
  return { cls: 'state-bad',    txt: 'Poza zakresem', desc: 'warunki poza komfortem użytkowym' };
}
function trendText(now, prev, tol = 0.05) {
  if (prev == null) return 'Stabilna';
  const d = now - prev;
  if (Math.abs(d) < tol) return 'Stabilna';
  return d > 0 ? 'Rośnie' : 'Spada';
}
function humRange(h) {
  if (h >= 40 && h <= 60) return { label: 'W normie', target: '40\u201360%', icon: '\u2713' };
  if (h < 40) return { label: 'Za sucho', target: 'poniżej 40%', icon: '\u2193' };
  return { label: 'Za wilgotno', target: 'powyżej 60%', icon: '\u2191' };
}
function fmtTimeISO(iso) {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return '\u2014';
  return date.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
}
async function fetchJSON(url) {
  const r = await fetch(url + (url.includes('?') ? '&' : '?') + 't=' + Date.now(), { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

// ---------------------------------------------------------------------------
// SVG sparkline chart
// ---------------------------------------------------------------------------
const CHART_W = 400, CHART_H = 80;
const PAD = { top: 8, right: 8, bottom: 20, left: 32 };

function sparkline(rows) {
  if (!rows || rows.length < 2) return null;
  const pts = rows.map(r => ({
    t:    new Date(r.timestamp).getTime(),
    temp: r.temperature_c,
    hum:  r.humidity_percent,
  })).filter(p => isFinite(p.t) && isFinite(p.temp) && isFinite(p.hum));
  if (pts.length < 2) return null;

  const tMin = pts[0].t, tMax = pts[pts.length - 1].t, tRange = tMax - tMin || 1;
  const temps = pts.map(p => p.temp), hums = pts.map(p => p.hum);
  const tempMin = Math.min(...temps), tempMax = Math.max(...temps);
  const humMin  = Math.min(...hums),  humMax  = Math.max(...hums);
  const gW = CHART_W - PAD.left - PAD.right, gH = CHART_H - PAD.top - PAD.bottom;

  const sx = t  => PAD.left + (t - tMin) / tRange * gW;
  const st = v  => PAD.top + gH - (v - tempMin) / (tempMax - tempMin || 1) * gH;
  const sh = v  => PAD.top + gH - (v - humMin)  / (humMax  - humMin  || 1) * gH;

  const tempPts = pts.map(p => `${sx(p.t).toFixed(1)},${st(p.temp).toFixed(1)}`).join(' ');
  const humPts  = pts.map(p => `${sx(p.t).toFixed(1)},${sh(p.hum).toFixed(1)}`).join(' ');

  const labelIdxs = [0, Math.floor(pts.length / 2), pts.length - 1];
  const lbls = labelIdxs.map(i => {
    const p = pts[i];
    const hhmm = new Date(p.t).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
    return `<text x="${sx(p.t).toFixed(1)}" y="${CHART_H - 4}" text-anchor="middle" class="sc-lbl">${hhmm}</text>`;
  });
  const yLbls = [
    `<text x="${PAD.left - 4}" y="${(PAD.top + gH).toFixed(1)}" text-anchor="end" class="sc-lbl">${tempMin.toFixed(1)}\u00b0</text>`,
    `<text x="${PAD.left - 4}" y="${(PAD.top + 6).toFixed(1)}" text-anchor="end" class="sc-lbl">${tempMax.toFixed(1)}\u00b0</text>`,
  ];

  return `<svg class="sensor-chart" viewBox="0 0 ${CHART_W} ${CHART_H}" aria-hidden="true">
  <style>
    .sc-temp{fill:none;stroke:#f87171;stroke-width:2;stroke-linejoin:round}
    .sc-hum{fill:none;stroke:#60a5fa;stroke-width:2;stroke-linejoin:round}
    .sc-lbl{font-size:9px;fill:var(--color-text-muted,#888);font-family:inherit}
    .sc-grid{stroke:var(--color-border,#333);stroke-width:.5;stroke-dasharray:3,3}
  </style>
  <line class="sc-grid" x1="${PAD.left}" y1="${(PAD.top + gH / 2).toFixed(1)}" x2="${CHART_W - PAD.right}" y2="${(PAD.top + gH / 2).toFixed(1)}"/>
  <polyline class="sc-hum"  points="${humPts}"/>
  <polyline class="sc-temp" points="${tempPts}"/>
  ${lbls.join(' ')}
  ${yLbls.join(' ')}
</svg>`;
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------
export function initSensorWidget({ url, historyUrl, pollMs = 30000 } = {}) {
  const elT  = document.getElementById('room-temp');
  const elH  = document.getElementById('room-hum');
  const elTT = document.getElementById('temp-trend');
  const elHR = document.getElementById('hum-range');
  const elHRIcon = document.getElementById('hum-range-icon');
  const elHRTarget = document.getElementById('hum-target-range');
  const pill = document.getElementById('comfort-pill');
  const desc = document.getElementById('comfort-desc');
  const batt = document.getElementById('room-batt');
  const upd  = document.getElementById('room-updated');
  const elF  = document.getElementById('room-temp-f');
  const batteryEl = document.getElementById('sensor-battery');
  const locationEl = document.getElementById('sensor-location-name');
  const chartSlot = document.getElementById('sensor-chart-slot');

  let freshEl = document.getElementById('sensor-freshness');
  if (!freshEl && upd && upd.parentNode) {
    freshEl = document.createElement('span');
    freshEl.id = 'sensor-freshness';
    freshEl.className = 'sensor-live-status';
    const dot = document.createElement('i');
    dot.setAttribute('aria-hidden', 'true');
    const label = document.createElement('strong');
    freshEl.append(dot, label);
    upd.parentNode.insertBefore(freshEl, upd.nextSibling);
  }

  const STALE_SEC = 150;
  let lastT = null, histPollCount = 0;

  function setFreshness(ageSec) {
    if (!freshEl) return;
    const label = freshEl.querySelector('strong') || freshEl;
    if (ageSec == null) {
      freshEl.dataset.state = 'offline';
      label.textContent = 'BRAK SYGNAŁU';
    } else if (ageSec > STALE_SEC) {
      freshEl.dataset.state = 'stale';
      label.textContent = 'NIEAKTUALNY';
    } else {
      freshEl.dataset.state = 'live';
      label.textContent = 'LIVE';
    }
  }

  function setBattery(value) {
    if (!batteryEl || !batt || !Number.isFinite(value)) return;
    const level = Math.max(0, Math.min(100, Math.round(value)));
    batt.textContent = String(level);
    batteryEl.style.setProperty('--sensor-battery-level', `${level}%`);
    batteryEl.classList.remove('battery-unknown', 'battery-high', 'battery-medium', 'battery-low');
    batteryEl.classList.add(level >= 60 ? 'battery-high' : level >= 30 ? 'battery-medium' : 'battery-low');
    batteryEl.setAttribute('aria-label', `Poziom baterii ${level}%`);
  }

  async function tick() {
    try {
      const j = await fetchJSON(url);
      if (j?.ok === false) throw new Error(j.error || 'Brak odczytu czujnika');
      let t, h, b, ts, ageSec;
      if (j.reading) {
        // Legacy Gist format {reading:{temp_c,hum_pct,battery_pct}, timestamp(unix)}
        const r = j.reading;
        t = Number(r.temp_c); h = Number(r.hum_pct); b = Number(r.battery_pct);
        const unixSec = Number(j.timestamp);
        ts = isFinite(unixSec) ? new Date(unixSec * 1000).toISOString() : null;
        ageSec = isFinite(unixSec) ? (Date.now() / 1000 - unixSec) : null;
      } else {
        // New local API format
        t = Number(j.temp_c); h = Number(j.hum_pct); b = Number(j.battery_pct);
        ts = j.timestamp || null;
        ageSec = j.age_seconds != null ? Number(j.age_seconds) : null;
      }

      if (!Number.isFinite(t) || !Number.isFinite(h)) return;

      elT.textContent = t.toFixed(1);
      elH.textContent = Math.round(h);
      elTT.textContent = trendText(t, lastT);
      if (elF) elF.textContent = `${((t * 9 / 5) + 32).toFixed(1)} \u00b0F`;
      const humidityRange = humRange(h);
      elHR.textContent = humidityRange.label;
      if (elHRIcon) elHRIcon.textContent = humidityRange.icon;
      if (elHRTarget) elHRTarget.textContent = humidityRange.target;
      lastT = t;

      const k = comfortLabel(t, h);
      pill.classList.remove('state-ok', 'state-warn', 'state-bad');
      pill.classList.add(k.cls);
      pill.textContent = k.txt;
      desc.textContent = k.desc;

      if (locationEl && j.sensor_id) {
        locationEl.textContent = j.sensor_id === 'desk' ? 'Biurko' : String(j.sensor_id);
      }
      if (Number.isFinite(b)) setBattery(b);
      upd.textContent = ts ? fmtTimeISO(ts) : '\u2014';
      upd.title = ts ? fmtDateTimeShort(new Date(ts)) : '';
      setFreshness(ageSec);
    } catch (e) {
      console.warn('sensor widget fetch error', e);
      setFreshness(null);
    }
    histPollCount++;
    if (historyUrl && (histPollCount === 1 || histPollCount % 5 === 0)) tickChart();
  }

  async function tickChart() {
    if (!chartSlot || !historyUrl) return;
    try {
      const rows = await fetchJSON(historyUrl + '?hours=24');
      if (!Array.isArray(rows)) return;
      const svg = sparkline(rows);
      if (svg) chartSlot.innerHTML = svg;
    } catch (e) { console.warn('sensor chart error', e); }
  }

  tick();
  setInterval(tick, pollMs);
}
