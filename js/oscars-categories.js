export const CANONICAL_CATEGORIES = [
  'Best Picture',
  'Directing',
  'Actor in a Leading Role',
  'Actress in a Leading Role',
  'Actor in a Supporting Role',
  'Actress in a Supporting Role',
  'Writing (Original Screenplay)',
  'Writing (Adapted Screenplay)',
  'Cinematography',
  'Production Design',
  'Costume Design',
  'Film Editing',
  'Sound',
  'Visual Effects',
  'Music (Original Score)',
  'Music (Original Song)',
  'Makeup and Hairstyling',
  'Animated Feature Film',
  'Animated Short Film',
  'Documentary Feature Film',
  'Documentary Short Film',
  'International Feature Film',
  'Live Action Short Film',
  'Casting',
  'Special Award'
];

export const CATEGORY_ALIASES = {
  'actor': 'Actor in a Leading Role',
  'actress': 'Actress in a Leading Role',
  'directing (dramatic picture)': 'Directing',
  'directing (comedy picture)': 'Directing',
  'writing (adaptation)': 'Writing (Adapted Screenplay)',
  'writing (original story)': 'Writing (Original Screenplay)',
  'writing (title writing)': 'Writing (Original Screenplay)',
  'outstanding picture': 'Best Picture',
  'unique and artistic picture': 'Best Picture',
  'engineering effects': 'Visual Effects',
  'art direction': 'Production Design'
};

const CANONICAL_BY_KEY = CANONICAL_CATEGORIES.reduce((acc, label) => {
  acc[label.toLowerCase()] = label;
  return acc;
}, {});

export function normalizeCategory(value) {
  if (!value) return '';
  const trimmed = String(value).trim().replace(/\s+/g, ' ');
  if (!trimmed) return '';
  const key = trimmed.toLowerCase();
  if (CATEGORY_ALIASES[key]) return CATEGORY_ALIASES[key];
  if (CANONICAL_BY_KEY[key]) return CANONICAL_BY_KEY[key];
  return trimmed;
}

export function splitCategories(value) {
  if (!value) return [];
  const out = [];
  const seen = new Set();
  String(value)
    .split(';')
    .map((v) => v.trim())
    .filter(Boolean)
    .forEach((raw) => {
      const mapped = normalizeCategory(raw);
      if (!mapped || seen.has(mapped)) return;
      seen.add(mapped);
      out.push(mapped);
    });
  return out;
}

export function sortCategories(list) {
  const order = new Map(CANONICAL_CATEGORIES.map((c, i) => [c, i]));
  return [...list].sort((a, b) => {
    const ai = order.has(a) ? order.get(a) : 999;
    const bi = order.has(b) ? order.get(b) : 999;
    if (ai !== bi) return ai - bi;
    return a.localeCompare(b);
  });
}
