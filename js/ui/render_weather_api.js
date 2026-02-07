// render_weather_api.js
import { setTempAccent, tempColor } from '../temp-scale.js';

const el = (id) => document.getElementById(id);
const DASH = '\u2014';
const fmt1 = (v) => (Number.isFinite(v) ? v.toFixed(1) : DASH);

const fmtHour = new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' });
const fmtTime = new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' });

// opisy warunkow (Open-Meteo / MET Norway style)
const WX_DESC = {
  0: 'Bezchmurnie',
  1: 'G\u0142\u00f3wnie s\u0142onecznie',
  2: 'Cz\u0119\u015bciowe zachmurzenie',
  3: 'Pochmurno',
  45: 'Mg\u0142a',
  48: 'Szron/mg\u0142a',
  51: 'M\u017cawka lekka',
  53: 'M\u017cawka',
  55: 'M\u017cawka intensywna',
  61: 'Deszcz lekki',
  63: 'Deszcz',
  65: 'Ulewa',
  66: 'Marzn\u0105cy deszcz',
  67: 'Ulewa marzn\u0105ca',
  71: '\u015anieg lekki',
  73: '\u015anieg',
  75: '\u015anieg intensywny',
  77: 'Ziarna lodowe',
  80: 'Przelotny deszcz lekki',
  81: 'Przelotny deszcz',
  82: 'Ulewy przelotne',
  85: 'Przelotny \u015bnieg lekki',
  86: 'Przelotny \u015bnieg',
  95: 'Burza',
  96: 'Burza z gradem',
  99: 'Silna burza z gradem'
};

// status
export function setStatus(text) {
  const s = el('status') || el('wx-updated');
  if (s) s.textContent = text;
}

// skala Beauforta
const BFT = [
  { max: 1, label: 'cisza' },
  { max: 5, label: 'powiew' },
  { max: 11, label: 'bardzo s\u0142aby' },
  { max: 19, label: 's\u0142aby' },
  { max: 28, label: 'umiarkowany' },
  { max: 38, label: 'do\u015b\u0107 silny' },
  { max: 49, label: 'silny' },
  { max: 61, label: 'bardzo silny' },
  { max: 74, label: 'wichura' },
  { max: 88, label: 'silna wichura' },
  { max: 102, label: 'gwa\u0142towna wichura' },
  { max: 117, label: 'burza huraganowa' },
  { max: Infinity, label: 'huragan' }
];
const windLabel = (v) => BFT.find((b) => (Number(v) || 0) <= b.max).label;

let lastNowTemp = null;

const svgWrap = (inner) =>
  `<svg class="wx-icon-svg" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;

const ICONS = {
  clear: svgWrap(
    `<circle cx="12" cy="12" r="4"></circle>
     <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>`
  ),
  partly: svgWrap(
    `<path d="M6 13a4.5 4.5 0 0 1 8.7-1.5"></path>
     <circle cx="9" cy="8" r="3"></circle>
     <path d="M7 18h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 18z"></path>`
  ),
  cloudy: svgWrap(
    `<path d="M7 18h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 18z"></path>`
  ),
  fog: svgWrap(
    `<path d="M7 14h9a3.5 3.5 0 0 0 0-7 4.5 4.5 0 0 0-8.5-1.1A3.5 3.5 0 0 0 7 14z"></path>
     <path d="M4 17h16M6 20h12"></path>`
  ),
  rain: svgWrap(
    `<path d="M7 13h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 13z"></path>
     <path d="M8 17l-1 2M12 17l-1 2M16 17l-1 2"></path>`
  ),
  snow: svgWrap(
    `<path d="M7 13h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 13z"></path>
     <path d="M8 16v4M7 18h2M12 16v4M11 18h2M16 16v4M15 18h2"></path>`
  ),
  storm: svgWrap(
    `<path d="M7 13h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 13z"></path>
     <path d="M11 14l-2 4h3l-2 4 5-6h-3l2-4z"></path>`
  ),
  unknown: svgWrap(`<circle cx="12" cy="12" r="4"></circle><path d="M12 7v2"></path>`)
};

function iconForCode(code) {
  if (code === 0) return ICONS.clear;
  if (code === 1 || code === 2) return ICONS.partly;
  if (code === 3) return ICONS.cloudy;
  if (code === 45 || code === 48) return ICONS.fog;
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return ICONS.rain;
  if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) return ICONS.snow;
  if (code === 95 || code === 96 || code === 99) return ICONS.storm;
  return ICONS.unknown;
}

function buildTempGradient(temps, fallbackTemp) {
  const count = temps.length;
  const fallback = Number.isFinite(fallbackTemp) ? fallbackTemp : temps.find(Number.isFinite);
  if (!Number.isFinite(fallback) && !count) return null;

  if (count === 0 && Number.isFinite(fallback)) {
    const single = tempColor(fallback);
    return single ? `linear-gradient(90deg, ${single}, ${single})` : null;
  }

  if (!Number.isFinite(fallback)) return null;

  const stops = temps.map((t, i) => {
    const temp = Number.isFinite(t) ? t : fallback;
    const color = tempColor(temp) || tempColor(fallback);
    const pct = count === 1 ? 0 : (i / (count - 1)) * 100;
    return `${color} ${pct.toFixed(1)}%`;
  });

  return `linear-gradient(90deg, ${stops.join(', ')})`;
}

function applyTempGradient(card, temps, fallbackTemp) {
  if (!card) return;
  const gradient = buildTempGradient(temps, fallbackTemp);
  if (gradient) {
    card.style.setProperty('--temp-gradient', gradient);
  }
}

// TERAZ
export function renderNow(now) {
  const tempNum = Number(now.temp);
  if (Number.isFinite(tempNum)) lastNowTemp = tempNum;

  if (el('wx-temp')) {
    el('wx-temp').textContent = Number.isFinite(tempNum) ? `${tempNum.toFixed(1)}\u00b0C` : DASH;
  }
  setTempAccent(document.querySelector('.card.hero-card'), tempNum);
  if (el('wx-cond')) el('wx-cond').textContent = WX_DESC[now.code] ?? DASH;
  if (el('wx-icon')) el('wx-icon').innerHTML = iconForCode(Number(now.code));

  const prcp = Number(now.prcp);
  const wind = Number(now.wind);

  if (el('wx-wind')) {
    el('wx-wind').textContent = Number.isFinite(wind)
      ? `${wind.toFixed(1)} km/h (${windLabel(wind)})`
      : DASH;
  }

  if (el('wx-prcp')) {
    el('wx-prcp').textContent = Number.isFinite(prcp)
      ? `${prcp.toFixed(1)} mm/h`
      : DASH;
  }

  const feels = Number(now.feels ?? now.temp);
  const hum = Number(now.hum);
  const cloud = Number(now.cloud);
  const gust = Number(now.gust);

  const pills = [
    {
      key: 'feels',
      icon: '&#x1F321;',
      label: 'Odczuwalna',
      value: Number.isFinite(feels) ? feels.toFixed(1) : DASH,
      unit: '\u00b0C',
      tip: 'Temperatura odczuwalna (uwzgl\u0119dnia wiatr i wilgotno\u015b\u0107)'
    },
    {
      key: 'hum',
      icon: '&#x1F4A7;',
      label: 'Wilgotno\u015b\u0107',
      value: Number.isFinite(hum) ? Math.round(hum) : DASH,
      unit: '%',
      tip: 'Wilgotno\u015b\u0107 wzgl\u0119dna powietrza'
    },
    {
      key: 'cloud',
      icon: '&#x2601;',
      label: 'Zachmurzenie',
      value: Number.isFinite(cloud) ? Math.round(cloud) : DASH,
      unit: '%',
      tip: 'Procent pokrycia nieba chmurami'
    },
    {
      key: 'gust',
      icon: '&#x1F4A8;',
      label: 'Porywy',
      value: Number.isFinite(gust) ? gust.toFixed(1) : DASH,
      unit: 'km/h',
      extra: Number.isFinite(gust) ? ` (${windLabel(gust)})` : '',
      tip: 'Maksymalne kr\u00f3tkie skoki pr\u0119dko\u015bci wiatru'
    }
  ];

  const c = el('now');
  if (!c) return;

  c.innerHTML = pills.map((p) => {
    const val = p.value === DASH ? DASH : `${p.value}${p.unit}${p.extra ?? ''}`;
    return `
      <span class="pill" data-kind="${p.key}"
            title="${p.tip}"
            aria-label="${p.label}: ${val}"
            tabindex="0">
        <span class="pill-icon" aria-hidden="true">${p.icon}</span>
        <span class="pill-main">
          <span class="pill-value">${val}</span>
          <span class="pill-label">${p.label}</span>
        </span>
      </span>
    `;
  }).join('');
}

function buildMetricChart(hours, values, colWidth, gapWidth, options) {
  if (!hours.length) {
    return { svg: `<div class="wx-chart-empty">${DASH}</div>`, min: null, max: null };
  }

  const finite = values.filter(Number.isFinite);
  if (!finite.length) {
    return { svg: `<div class="wx-chart-empty">${DASH}</div>`, min: null, max: null };
  }

  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const range = Math.max(1, max - min);

  const col = Number.isFinite(colWidth) && colWidth > 0 ? colWidth : 120;
  const gap = Number.isFinite(gapWidth) && gapWidth >= 0 ? gapWidth : 10;
  const step = col + gap;
  const width = Math.max(260, (hours.length * col) + (Math.max(0, hours.length - 1) * gap));
  const height = 88;
  const plotTop = 8;
  const plotBottom = 48;
  const hourY = 66;
  const valueY = 80;

  const points = values.map((v, idx) => {
    const val = Number.isFinite(v) ? v : min;
    const x = idx * step + col / 2;
    const y = plotBottom - ((val - min) / range) * (plotBottom - plotTop);
    return { x, y, val };
  });

  const cols = points.map((_, idx) => {
    const x = idx * step;
    const cls = idx % 2 ? 'wx-chart-col odd' : 'wx-chart-col';
    return `<rect class="${cls}" x="${x}" y="${plotTop}" width="${col}" height="${plotBottom - plotTop}"></rect>`;
  }).join('');

  const gridLines = Array.from({ length: hours.length + 1 }, (_, idx) => {
    const x = idx === hours.length ? width : idx * step;
    return `<line class="wx-chart-grid" x1="${x}" y1="${plotTop}" x2="${x}" y2="${plotBottom}"></line>`;
  }).join('');

  const firstY = points[0].y.toFixed(2);
  const lastPoint = points[points.length - 1];
  const lastY = lastPoint.y.toFixed(2);
  const lastX = width.toFixed(2);

  const path = `M 0 ${firstY} ` +
    points.map((p) => `L ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ') +
    ` L ${lastX} ${lastY}`;

  const area = `M 0 ${plotBottom} L 0 ${firstY} ` +
    points.map((p) => `L ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ') +
    ` L ${lastX} ${lastY} L ${lastX} ${plotBottom} Z`;

  const dots = points
    .map((p) => `<circle cx="${p.x.toFixed(2)}" cy="${p.y.toFixed(2)}" r="1.6"></circle>`)
    .join('');

  const labels = points.map((p, idx) => {
    const hour = fmtHour.format(new Date(hours[idx].timeIso));
    const valueLabel = Number.isFinite(values[idx]) ? options.formatLabel(values[idx]) : DASH;
    return `
      <text class="wx-chart-hour" x="${p.x.toFixed(2)}" y="${hourY}" text-anchor="middle">${hour}</text>
      <text class="wx-chart-temp" x="${p.x.toFixed(2)}" y="${valueY}" text-anchor="middle">${valueLabel}</text>
    `;
  }).join('');

  const fallback = options.fallbackColor
    || (options.colorForValue ? options.colorForValue(finite[0]) : null)
    || '#ffffff';

  const stops = values.map((v, idx) => {
    const pct = values.length === 1 ? 0 : (idx / (values.length - 1)) * 100;
    const color = Number.isFinite(v) && options.colorForValue
      ? options.colorForValue(v)
      : null;
    return `<stop offset="${pct.toFixed(1)}%" stop-color="${color || fallback}"></stop>`;
  }).join('');

  const areaStops = values.map((v, idx) => {
    const pct = values.length === 1 ? 0 : (idx / (values.length - 1)) * 100;
    const color = Number.isFinite(v) && options.colorForValue
      ? options.colorForValue(v)
      : null;
    return `<stop offset="${pct.toFixed(1)}%" stop-color="${color || fallback}" stop-opacity="0.28"></stop>`;
  }).join('');

  const svg = `
    <svg class="wx-chart-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="${options.gradientId}-area" x1="0" y1="0" x2="1" y2="0">
          ${areaStops}
        </linearGradient>
        <linearGradient id="${options.gradientId}" x1="0" y1="0" x2="1" y2="0">
          ${stops}
        </linearGradient>
      </defs>
      ${cols}
      ${gridLines}
      <path class="wx-chart-area" d="${area}" fill="url(#${options.gradientId}-area)"></path>
      <path class="wx-chart-line" d="${path}" stroke="url(#${options.gradientId})"></path>
      ${dots}
      ${labels}
    </svg>
  `;

  return { svg, min, max };
}

function setupNextScroller(root) {
  const chartScrolls = Array.from(root.querySelectorAll('.wx-chart-scroll'));
  const left = root.querySelector('.wx-scroll-btn.left');
  const right = root.querySelector('.wx-scroll-btn.right');
  const primaryScroll = root.querySelector('.wx-scroll') || chartScrolls[0];
  if (!primaryScroll || !left || !right) return;

  const controller = new AbortController();
  const { signal } = controller;

  let autoTimer = null;
  let syncing = false;

  const on = (target, type, handler, options = {}) =>
    target.addEventListener(type, handler, { ...options, signal });

  const allScrolls = Array.from(new Set([primaryScroll, ...chartScrolls]));

  const syncAll = (source) => {
    if (syncing) return;
    syncing = true;
    const leftPos = source.scrollLeft;
    for (const el of allScrolls) {
      if (el !== source) el.scrollLeft = leftPos;
    }
    requestAnimationFrame(() => { syncing = false; });
  };

  const updateEdges = () => {
    const max = Math.max(0, primaryScroll.scrollWidth - primaryScroll.clientWidth);
    const atStart = primaryScroll.scrollLeft <= 2;
    const atEnd = primaryScroll.scrollLeft >= max - 2;
    left.classList.toggle('is-disabled', atStart);
    right.classList.toggle('is-disabled', atEnd);
    left.setAttribute('aria-disabled', String(atStart));
    right.setAttribute('aria-disabled', String(atEnd));
  };

  const stopAuto = () => {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
  };

  const scrollByAmount = (amount, behavior) => {
    for (const el of allScrolls) {
      el.scrollBy({ left: amount, behavior });
    }
  };

  const startAuto = (dir) => {
    stopAuto();
    autoTimer = setInterval(() => {
      scrollByAmount(dir * 4, 'auto');
      updateEdges();
    }, 16);
  };

  const stepClick = (dir) => {
    const step = Math.max(100, primaryScroll.clientWidth * 0.45);
    scrollByAmount(dir * step, 'smooth');
  };

  const guard = (fn, dir) => (ev) => {
    if (dir < 0 && left.classList.contains('is-disabled')) return;
    if (dir > 0 && right.classList.contains('is-disabled')) return;
    fn(ev);
  };

  on(left, 'mouseenter', guard(() => startAuto(-1), -1));
  on(right, 'mouseenter', guard(() => startAuto(1), 1));
  on(left, 'mouseleave', stopAuto);
  on(right, 'mouseleave', stopAuto);
  on(left, 'focus', guard(() => startAuto(-1), -1));
  on(right, 'focus', guard(() => startAuto(1), 1));
  on(left, 'blur', stopAuto);
  on(right, 'blur', stopAuto);
  on(left, 'click', guard(() => stepClick(-1), -1));
  on(right, 'click', guard(() => stepClick(1), 1));

  const attachDrag = (target) => {
    let dragging = false;
    let dragStartX = 0;
    let dragStartScroll = 0;

    on(target, 'pointerdown', (e) => {
      if (e.button !== 0) return;
      dragging = true;
      dragStartX = e.clientX;
      dragStartScroll = target.scrollLeft;
      target.classList.add('is-dragging');
      target.setPointerCapture(e.pointerId);
    });

    on(target, 'pointermove', (e) => {
      if (!dragging) return;
      const dx = e.clientX - dragStartX;
      target.scrollLeft = dragStartScroll - dx;
    });

    const endDrag = () => {
      if (!dragging) return;
      dragging = false;
      target.classList.remove('is-dragging');
    };

    on(target, 'pointerup', endDrag);
    on(target, 'pointercancel', endDrag);
    on(target, 'pointerleave', endDrag);
  };

  for (const el of allScrolls) attachDrag(el);

  for (const el of allScrolls) {
    on(el, 'scroll', () => {
      syncAll(el);
      updateEdges();
    });
  }

  requestAnimationFrame(updateEdges);

  return () => {
    stopAuto();
    controller.abort();
  };
}

export function renderNext(nextHours) {
  const n = el('next');
  if (!n) return;

  if (n.__wxCleanup) {
    n.__wxCleanup();
    n.__wxCleanup = null;
  }

  const hours = Array.isArray(nextHours) ? nextHours : [];
  if (!hours.length) {
    n.innerHTML = `<div class="wx-next-empty">${DASH}</div>`;
    const card = document.querySelector('.card.hero-card');
    applyTempGradient(card, [], lastNowTemp);
    return;
  }

  const col = Number.parseFloat(getComputedStyle(n).getPropertyValue('--wx-col')) || 120;
  const gap = Number.parseFloat(getComputedStyle(n).getPropertyValue('--wx-gap')) || 10;

  const temps = hours.map((h) => Number(h.temp));
  const prcps = hours.map((h) => Number(h.prcp));
  const winds = hours.map((h) => Number(h.wind));

  const tempChart = buildMetricChart(hours, temps, col, gap, {
    gradientId: 'wx-line-temp',
    colorForValue: (v) => tempColor(v),
    fallbackColor: tempColor(lastNowTemp) || '#ffffff',
    formatLabel: (v) => `${fmt1(v)}\u00b0C`
  });

  const prcpChart = buildMetricChart(hours, prcps, col, gap, {
    gradientId: 'wx-line-prcp',
    colorForValue: () => '#93c5fd',
    fallbackColor: '#93c5fd',
    formatLabel: (v) => `${fmt1(v)} mm/h`
  });

  const windChart = buildMetricChart(hours, winds, col, gap, {
    gradientId: 'wx-line-wind',
    colorForValue: () => '#fbbf24',
    fallbackColor: '#fbbf24',
    formatLabel: (v) => `${fmt1(v)} km/h`
  });

  const formatRangeVal = (val, unit, joiner = ' ') =>
    Number.isFinite(val) ? `${fmt1(val)}${joiner}${unit}` : DASH;

  const tempRange = `min ${formatRangeVal(tempChart.min, '\u00b0C', '')} \u2022 max ${formatRangeVal(tempChart.max, '\u00b0C', '')}`;
  const prcpRange = `min ${formatRangeVal(prcpChart.min, 'mm/h')} \u2022 max ${formatRangeVal(prcpChart.max, 'mm/h')}`;
  const windRange = `min ${formatRangeVal(windChart.min, 'km/h')} \u2022 max ${formatRangeVal(windChart.max, 'km/h')}`;

  const lastLabel = fmtTime.format(new Date(hours[hours.length - 1].timeIso));

  n.innerHTML = `
    <div class="wx-next">
      <div class="wx-next-head">
        <div class="wx-next-title">Najbli\u017csze godziny</div>
        <div class="wx-next-range">do ${lastLabel}</div>
      </div>
      <div class="wx-trends">
        <div class="wx-chart-shell">
          <button class="wx-scroll-btn left" type="button" aria-label="Przewi\u0144 w lewo">
            <span aria-hidden="true">&#x25C0;</span>
          </button>
          <div class="wx-chart" role="img" aria-label="Wykres zmian temperatury">
            <div class="wx-chart-head">
              <div class="wx-chart-label">Trend temperatury</div>
              <div class="wx-chart-range">${tempRange}</div>
            </div>
            <div class="wx-chart-scroll">
              ${tempChart.svg}
            </div>
          </div>
          <button class="wx-scroll-btn right" type="button" aria-label="Przewi\u0144 w prawo">
            <span aria-hidden="true">&#x25B6;</span>
          </button>
        </div>
        <div class="wx-chart" role="img" aria-label="Wykres zmian opadow">
          <div class="wx-chart-head">
            <div class="wx-chart-label">Trend opad\u00f3w</div>
            <div class="wx-chart-range">${prcpRange}</div>
          </div>
          <div class="wx-chart-scroll">
            ${prcpChart.svg}
          </div>
        </div>
        <div class="wx-chart" role="img" aria-label="Wykres zmian wiatru">
          <div class="wx-chart-head">
            <div class="wx-chart-label">Trend wiatru</div>
            <div class="wx-chart-range">${windRange}</div>
          </div>
          <div class="wx-chart-scroll">
            ${windChart.svg}
          </div>
        </div>
      </div>
    </div>
  `;

  const card = document.querySelector('.card.hero-card');
  applyTempGradient(card, temps, lastNowTemp);

  n.__wxCleanup = setupNextScroller(n);
}
