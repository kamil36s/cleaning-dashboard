export const COUNTRY_ALIASES = {
  'united states': 'USA',
  'united states of america': 'USA',
  'u.s.': 'USA',
  'u.s.a.': 'USA',
  'us': 'USA',
  'usa': 'USA',
  'u s': 'USA',
  'u s a': 'USA'
};

function normalizeCountryKey(value) {
  return String(value)
    .toLowerCase()
    .replace(/[.]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function normalizeCountry(value) {
  if (!value) return '';
  const trimmed = String(value).trim();
  if (!trimmed) return '';
  const key = normalizeCountryKey(trimmed);
  return COUNTRY_ALIASES[key] || trimmed;
}

export function splitCountries(value) {
  if (!value) return [];
  const out = [];
  const seen = new Set();
  String(value)
    .split(/[;,/]/)
    .map((v) => v.trim())
    .filter(Boolean)
    .forEach((raw) => {
      const mapped = normalizeCountry(raw);
      if (!mapped || seen.has(mapped)) return;
      seen.add(mapped);
      out.push(mapped);
    });
  return out;
}

export function normalizeCountryList(value) {
  const list = splitCountries(value);
  return list.length ? list.join(', ') : '';
}
