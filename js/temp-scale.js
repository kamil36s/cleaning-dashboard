// js/temp-scale.js
const TEMP_STOPS = [
  { t: -15, c: '#2F2C7E' },
  { t: -5,  c: '#2B6CB0' },
  { t: 5,   c: '#2C9FA3' },
  { t: 12,  c: '#6CC2A5' },
  { t: 20,  c: '#F0E68C' },
  { t: 27,  c: '#F6B04C' },
  { t: 35,  c: '#E35B3F' },
  { t: 35.1, c: '#B11226' }
];

function hexToRgb(hex) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return null;
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(r, g, b) {
  const toHex = v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function mixHex(a, b, t) {
  const ra = hexToRgb(a);
  const rb = hexToRgb(b);
  if (!ra || !rb) return a || b || null;
  const m = (x, y) => x + (y - x) * t;
  return rgbToHex(m(ra[0], rb[0]), m(ra[1], rb[1]), m(ra[2], rb[2]));
}

export function tempColor(t) {
  if (!Number.isFinite(t)) return null;
  const v = Math.round(t * 10) / 10;
  if (v <= TEMP_STOPS[0].t) return TEMP_STOPS[0].c;
  if (v >= TEMP_STOPS[TEMP_STOPS.length - 1].t) return TEMP_STOPS[TEMP_STOPS.length - 1].c;
  for (let i = 0; i < TEMP_STOPS.length - 1; i++) {
    const a = TEMP_STOPS[i];
    const b = TEMP_STOPS[i + 1];
    if (v >= a.t && v <= b.t) {
      const span = b.t - a.t || 1;
      const r = (v - a.t) / span;
      return mixHex(a.c, b.c, r);
    }
  }
  return null;
}

export function setTempAccent(el, t) {
  if (!el) return;
  const c = tempColor(t) || 'transparent';
  el.style.setProperty('--temp-accent', c);
}
