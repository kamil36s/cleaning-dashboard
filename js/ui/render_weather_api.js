// render_weather_api.js
import { setTempAccent, tempColor } from '../temp-scale.js';
import { WX_COLORS } from '../config.js';

const el = (id) => document.getElementById(id);
const DASH = '\u2014';
const fmt1 = (v) => (Number.isFinite(v) ? v.toFixed(1) : DASH);
const fmtTemp = (v) => (Number.isFinite(v) ? String(Math.round(v)) : DASH);
const fmtSpeed = (v) => (Number.isFinite(v) ? `${v.toFixed(1)} km/h` : DASH);
const fmtPrcp = (v) => (Number.isFinite(v) ? `${v.toFixed(1)} mm/h` : DASH);
const formatTempLabel = (v) => {
  const t = fmtTemp(v);
  return t === DASH ? DASH : `${t}\u00b0C`;
};

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

function rainCategory(v) {
  if (!Number.isFinite(v) || v < 0.05) return null;
  if (v < 0.3) return 'mżawka';
  if (v < 2.5) return 'lekki';
  if (v < 7.6) return 'umiark.';
  if (v < 50)  return 'intensywny';
  return 'ulewa';
}

let lastNowTemp = null;

// ---- Icon style system ----
const WX_ICON_STYLE_KEY = 'wx-icon-style';
const WX_ICON_STYLES = ['outline', 'filled', 'neon', 'retro', 'glass'];

function getIconStyle() {
  try { return localStorage.getItem(WX_ICON_STYLE_KEY) || 'outline'; } catch (_) { return 'outline'; }
}
function saveIconStyle(s) {
  try { localStorage.setItem(WX_ICON_STYLE_KEY, s); } catch (_) {}
}

const svgWrap = (inner) =>
  `<svg class="wx-icon-svg" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
const svgFilled = (inner) =>
  `<svg class="wx-icon-svg" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor" stroke="none">${inner}</svg>`;

const ICONS_OUTLINE = {
  clear: svgWrap(
    `<circle cx="12" cy="12" r="4.5"></circle>
     <path d="M12 1.5v2M12 20.5v2M3.5 3.5l1.4 1.4M19.1 19.1l1.4 1.4M1.5 12h2M20.5 12h2M3.5 20.5l1.4-1.4M19.1 4.9l1.4-1.4"></path>`
  ),
  partly: svgWrap(
    `<circle cx="9.5" cy="7.5" r="3"></circle>
     <path d="M9.5 4.5V3M9.5 10.5V12M6.5 7.5H5M12.5 7.5H14M7.6 5.6l-1-1M11.4 9.4l1 1"></path>
     <path d="M7 18h10a4.5 4.5 0 0 0 .5-9 5.5 5.5 0 0 0-10-1.5A4 4 0 0 0 7 18z"></path>`
  ),
  cloudy: svgWrap(
    `<path d="M6.5 18.5h10a4.5 4.5 0 0 0 .4-9 5.5 5.5 0 0 0-10.8-.5A4 4 0 0 0 6.5 18.5z"></path>`
  ),
  fog: svgWrap(
    `<path d="M6.5 13h10a3.5 3.5 0 0 0 .4-7 4.5 4.5 0 0 0-8.8-.5A3.5 3.5 0 0 0 6.5 13z"></path>
     <path d="M3 16h18M5 19.5h14"></path>`
  ),
  drizzle: svgWrap(
    `<path d="M6.5 13h10a4 4 0 0 0 .4-8 5 5 0 0 0-9.8-1A4 4 0 0 0 6.5 13z"></path>
     <path d="M8.5 17l-.5 1.5M12.5 17l-.5 1.5M16.5 17l-.5 1.5"></path>`
  ),
  rain: svgWrap(
    `<path d="M6.5 13h10a4 4 0 0 0 .4-8 5 5 0 0 0-9.8-1A4 4 0 0 0 6.5 13z"></path>
     <path d="M8 17l-1.5 3M12 16.5l-1.5 3M16 17l-1.5 3"></path>`
  ),
  snow: svgWrap(
    `<path d="M6.5 13h10a4 4 0 0 0 .4-8 5 5 0 0 0-9.8-1A4 4 0 0 0 6.5 13z"></path>
     <path d="M8 17v3.5M7 18.5h2M12 17v3.5M11 18.5h2M16 17v3.5M15 18.5h2"></path>`
  ),
  storm: svgWrap(
    `<path d="M6.5 13h10a4 4 0 0 0 .4-8 5 5 0 0 0-9.8-1A4 4 0 0 0 6.5 13z"></path>
     <path d="M10.5 14l-2.5 5h3.5l-2.5 5 6.5-7h-4l2-3z"></path>`
  ),
  unknown: svgWrap(`<circle cx="12" cy="12" r="4"></circle><path d="M12 7v2"></path>`)
};

const ICONS_FILLED = {
  clear: svgFilled(`<circle cx="12" cy="12" r="5.5"></circle><path d="M12 1v2.5M12 20.5V23M3.2 3.2l1.8 1.8M19 19l1.8 1.8M1 12h2.5M20.5 12H23M3.2 20.8l1.8-1.8M19 5l1.8-1.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>`),
  partly: svgFilled(`<circle cx="9.5" cy="7" r="4" opacity="0.9"></circle><path d="M14 10a5 5 0 0 1 2.5 9.5H7a4.5 4.5 0 0 1-.5-9A5.5 5.5 0 0 1 14 10z" opacity="0.78"></path>`),
  cloudy: svgFilled(`<path d="M6 18.5h11.5a5 5 0 0 0 .5-10 6 6 0 0 0-11.5-.5A4.5 4.5 0 0 0 6 18.5z"></path>`),
  fog: svgFilled(`<path d="M6 13h11.5a4 4 0 0 0 .5-8 5 5 0 0 0-9.5-.5A4 4 0 0 0 6 13z"></path><rect x="2" y="16" width="20" height="2" rx="1"></rect><rect x="4" y="20" width="16" height="2" rx="1"></rect>`),
  drizzle: svgFilled(`<path d="M6 13h11.5a4.5 4.5 0 0 0 .5-9 5.5 5.5 0 0 0-10.5-1A4.5 4.5 0 0 0 6 13z"></path><circle cx="8.5" cy="18.5" r="1.5"></circle><circle cx="13" cy="18.5" r="1.5"></circle><circle cx="17.5" cy="18.5" r="1.5"></circle>`),
  rain: svgFilled(`<path d="M6 13h11.5a4.5 4.5 0 0 0 .5-9 5.5 5.5 0 0 0-10.5-1A4.5 4.5 0 0 0 6 13z"></path><ellipse cx="8.5" cy="19.5" rx="1.5" ry="2.5" transform="rotate(-10 8.5 19.5)"></ellipse><ellipse cx="13" cy="19.5" rx="1.5" ry="2.5" transform="rotate(-10 13 19.5)"></ellipse><ellipse cx="17.5" cy="19.5" rx="1.5" ry="2.5" transform="rotate(-10 17.5 19.5)"></ellipse>`),
  snow: svgFilled(`<path d="M6 13h11.5a4.5 4.5 0 0 0 .5-9 5.5 5.5 0 0 0-10.5-1A4.5 4.5 0 0 0 6 13z"></path><path d="M8 17v4M7 19h2M12 17v4M11 19h2M16 17v4M15 19h2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>`),
  storm: svgFilled(`<path d="M6 13h11.5a4.5 4.5 0 0 0 .5-9 5.5 5.5 0 0 0-10.5-1A4.5 4.5 0 0 0 6 13z"></path><path d="M10 14l-3 5.5h4l-2.5 5.5 7.5-8h-5l2-3z"></path>`),
  unknown: svgFilled(`<circle cx="12" cy="12" r="5.5"></circle><path d="M12 8v3.5M12 16.5v1" fill="none" stroke="#000" stroke-width="2" stroke-linecap="round"></path>`)
};

function _iconKey(code) {
  if (code === 0) return 'clear';
  if (code === 1 || code === 2) return 'partly';
  if (code === 3) return 'cloudy';
  if (code === 45 || code === 48) return 'fog';
  if (code >= 51 && code <= 55) return 'drizzle';
  if ((code >= 56 && code <= 67) || (code >= 80 && code <= 82)) return 'rain';
  if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) return 'snow';
  if (code === 95 || code === 96 || code === 99) return 'storm';
  return 'unknown';
}

function iconForCode(code, style) {
  const s = style !== undefined ? style : getIconStyle();
  const key = _iconKey(Number(code));
  if (s === 'filled' || s === 'glass') return (ICONS_FILLED[key] || ICONS_FILLED.unknown);
  return (ICONS_OUTLINE[key] || ICONS_OUTLINE.unknown);
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
    el('wx-temp').textContent = formatTempLabel(tempNum);
  }
  setTempAccent(document.querySelector('.card.hero-card'), tempNum);
  if (el('wx-cond')) el('wx-cond').textContent = WX_DESC[now.code] ?? DASH;

  const wxIcon = el('wx-icon');
  if (wxIcon) {
    const nowCode = Number(now.code);
    wxIcon.title = 'Kliknij, aby zmienić styl ikony pogody';
    wxIcon.style.cursor = 'pointer';
    const applyIconStyle = (s) => {
      wxIcon.innerHTML = iconForCode(nowCode, s);
      wxIcon.dataset.iconStyle = s;
      wxIcon.dataset.wxKey = _iconKey(nowCode);
      WX_ICON_STYLES.forEach(st => wxIcon.classList.remove(`wx-icon--${st}`));
      wxIcon.classList.add(`wx-icon--${s}`);
    };
    wxIcon.onclick = () => {
      const cur = getIconStyle();
      const next = WX_ICON_STYLES[(WX_ICON_STYLES.indexOf(cur) + 1) % WX_ICON_STYLES.length];
      saveIconStyle(next);
      applyIconStyle(next);
    };
    applyIconStyle(getIconStyle());
  }

  const prcp = Number(now.prcp);
  const wind = Number(now.wind);
  const feels = Number(now.feels);

  const hum = Number(now.hum);
  const cloud = Number(now.cloud);
  const gust = Number(now.gust);

  const pills = [
    {
      key: 'wind',
      icon: '&#x1F32C;',
      label: 'Wiatr',
      valueText: fmtSpeed(wind),
      note: Number.isFinite(wind) ? windLabel(wind) : '',
      tip: 'Pr\u0119dko\u015b\u0107 wiatru na wysoko\u015bci 10 metr\u00f3w'
    },
    {
      key: 'gust',
      icon: '&#x1F4A8;',
      label: 'Porywy',
      valueText: fmtSpeed(gust),
      note: Number.isFinite(gust) ? windLabel(gust) : '',
      tip: 'Maksymalne kr\u00f3tkie skoki pr\u0119dko\u015bci wiatru'
    },
    {
      key: 'prcp',
      icon: '&#x1F4A6;',
      label: 'Opad',
      valueText: fmtPrcp(prcp),
      tip: 'Aktualna intensywno\u015b\u0107 opadu'
    },
    {
      key: 'feels',
      icon: '&#x1F321;',
      label: 'Odczuwalna',
      valueText: formatTempLabel(feels),
      tip: 'Temperatura odczuwalna z modelu Open-Meteo'
    },
    {
      key: 'hum',
      icon: '&#x1F4A7;',
      label: 'Wilgotno\u015b\u0107',
      valueText: Number.isFinite(hum) ? `${Math.round(hum)}%` : DASH,
      tip: 'Wilgotno\u015b\u0107 wzgl\u0119dna powietrza'
    },
    {
      key: 'cloud',
      icon: '&#x2601;',
      label: 'Zachmurzenie',
      valueText: Number.isFinite(cloud) ? `${Math.round(cloud)}%` : DASH,
      tip: 'Procent pokrycia nieba chmurami'
    }
  ];

  const c = el('now');
  if (!c) return;

  c.innerHTML = pills.map((p) => {
    const note = p.note ? `<span class="pill-note">${p.note}</span>` : '';
    const ariaText = p.note ? `${p.valueText}, ${p.note}` : p.valueText;
    return `
      <span class="pill" data-kind="${p.key}"
            title="${p.tip}"
            aria-label="${p.label}: ${ariaText}"
            tabindex="0">
        <span class="pill-icon" aria-hidden="true">${p.icon}</span>
        <span class="pill-main">
          <span class="pill-value">${p.valueText}</span>
          <span class="pill-label">${p.label}</span>
          ${note}
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
  const height = 104;
  const plotTop = 6;
  const plotBottom = 46;
  const hourY = 64;
  const valueY = 82;
  const extraY = 97;

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

  // 1. Godziny
  const hourLabels = points.map((p, idx) => {
    const hour = fmtHour.format(new Date(hours[idx].timeIso));
    return `<text class="wx-chart-hour" x="${p.x.toFixed(2)}" y="${hourY}" text-anchor="middle">${hour}</text>`;
  }).join('');

  // 2. Wartości i opisy słowne:
  // W temperaturze w każdej godzinie, w opadach/wietrze centrowane pośrodku serii.
  // Opis słowny (kategoria) ZAWSZE pod wartością liczbową (to samo x).
  let valueLabels = '';
  let extraLabels = '';

  if (!options.roundForDedup) {
    valueLabels = points.map((p, idx) => {
      const valueLabel = Number.isFinite(values[idx]) ? options.formatLabel(values[idx]) : DASH;
      return `<text class="wx-chart-temp" x="${p.x.toFixed(2)}" y="${valueY}" text-anchor="middle">${valueLabel}</text>`;
    }).join('');
  } else {
    let runs = [];
    let curRun = null;
    values.forEach((v, idx) => {
      if (!Number.isFinite(v)) return;
      const key = options.roundForDedup(v);
      if (curRun && curRun.key === key) {
        curRun.end = idx;
        curRun.count++;
      } else {
        if (curRun) runs.push(curRun);
        curRun = { key, start: idx, end: idx, count: 1, val: v };
      }
    });
    if (curRun) runs.push(curRun);

    let lastRenderedCat = null;
    runs.forEach((r) => {
      const midIdx = (r.start + r.end) / 2;
      const midX = (midIdx * step + col / 2).toFixed(2);
      const vl = options.formatLabel(r.val);
      valueLabels += `<text class="wx-chart-temp" x="${midX}" y="${valueY}" text-anchor="middle">${vl}</text>`;

      if (options.getCategory) {
        const cat = options.getCategory(r.val);
        if (cat && cat !== lastRenderedCat) {
          extraLabels += `<text class="wx-chart-extra" x="${midX}" y="${extraY}" text-anchor="middle">${cat}</text>`;
          lastRenderedCat = cat;
        }
      }
    });
  }

  const labels = hourLabels + valueLabels + extraLabels;

  const fallback = options.fallbackColor
    || (options.colorForValue ? options.colorForValue(finite[0]) : null)
    || WX_COLORS.tempFallback
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

  const col = Number.parseFloat(getComputedStyle(n).getPropertyValue('--wx-col')) || 72;
  const gap = Number.parseFloat(getComputedStyle(n).getPropertyValue('--wx-gap')) || 6;

  const temps = hours.map((h) => Number(h.temp));
  const prcps = hours.map((h) => Number(h.prcp));
  const winds = hours.map((h) => Number(h.wind));

  const tempChart = buildMetricChart(hours, temps, col, gap, {
    gradientId: 'wx-line-temp',
    colorForValue: (v) => tempColor(v),
    fallbackColor: tempColor(lastNowTemp) || WX_COLORS.tempFallback || '#ffffff',
    formatLabel: (v) => formatTempLabel(v)
  });

  const prcpChart = buildMetricChart(hours, prcps, col, gap, {
    gradientId: 'wx-line-prcp',
    colorForValue: () => WX_COLORS.prcp || '#93c5fd',
    fallbackColor: WX_COLORS.prcp || '#93c5fd',
    formatLabel: (v) => `${fmt1(v)} mm`,
    roundForDedup: (v) => fmt1(v),
    getCategory: rainCategory
  });

  const windChart = buildMetricChart(hours, winds, col, gap, {
    gradientId: 'wx-line-wind',
    colorForValue: () => WX_COLORS.wind || '#fbbf24',
    fallbackColor: WX_COLORS.wind || '#fbbf24',
    formatLabel: (v) => `${Math.round(v)} km/h`,
    roundForDedup: (v) => String(Math.round(v)),
    getCategory: (v) => windLabel(v)
  });

  const formatRangeVal = (val, unit, joiner = ' ') =>
    Number.isFinite(val) ? `${fmt1(val)}${joiner}${unit}` : DASH;

  const tempRange = `min ${formatTempLabel(tempChart.min)} \u2022 max ${formatTempLabel(tempChart.max)}`;
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
