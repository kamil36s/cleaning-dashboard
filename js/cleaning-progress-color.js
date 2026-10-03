let resolvedStops = null;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const resolveColor = (name, fallback) => {
  if (typeof window === 'undefined' || typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
};

const getProgressStops = () => {
  if (resolvedStops) return resolvedStops;
  resolvedStops = [
    { pct: 0, color: resolveColor('--dead', '#430069') },
    { pct: 10, color: resolveColor('--dead', '#430069') },
    { pct: 35, color: resolveColor('--over', '#ef4444') },
    { pct: 60, color: resolveColor('--due', '#fbbf24') },
    { pct: 80, color: resolveColor('--coming', '#a3e635') },
    { pct: 90, color: resolveColor('--fresh', '#22c55e') },
    { pct: 100, color: resolveColor('--fresh', '#22c55e') },
  ];
  return resolvedStops;
};

const hexToRgb = (hex) => {
  const clean = hex.replace('#', '').trim();
  const full = clean.length === 3
    ? clean.split('').map((char) => char + char).join('')
    : clean;
  const value = Number.parseInt(full, 16);
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  };
};

const rgbToHex = ({ r, g, b }) => {
  const toHex = (value) => value.toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
};

const lerp = (a, b, amount) => Math.round(a + (b - a) * amount);

export function colorForCleaningProgress(percent) {
  const value = clamp(Number(percent) || 0, 0, 100);
  const stops = getProgressStops();
  let left = stops[0];
  let right = stops[stops.length - 1];

  for (let index = 0; index < stops.length - 1; index += 1) {
    const start = stops[index];
    const end = stops[index + 1];
    if (value >= start.pct && value <= end.pct) {
      left = start;
      right = end;
      break;
    }
  }

  if (left.pct === right.pct) return left.color;
  const amount = (value - left.pct) / (right.pct - left.pct);
  const startColor = hexToRgb(left.color);
  const endColor = hexToRgb(right.color);
  return rgbToHex({
    r: lerp(startColor.r, endColor.r, amount),
    g: lerp(startColor.g, endColor.g, amount),
    b: lerp(startColor.b, endColor.b, amount),
  });
}
