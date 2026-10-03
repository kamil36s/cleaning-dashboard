// js/temp-scale.js
import { TEMP_STOPS } from './config.js';

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
