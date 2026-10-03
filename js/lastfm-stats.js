const API_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  && window.location.port !== '8000'
  ? 'http://127.0.0.1:8000'
  : '';
const MATCH_API = `${API_BASE}/api/lastfm/match`;

function normalizeName(value, { album = false } = {}) {
  let text = String(value || '')
    .toLowerCase()
    .replace(/[łøđðþæœ]/g, (char) => ({ ł: 'l', ø: 'o', đ: 'd', ð: 'd', þ: 'th', æ: 'ae', œ: 'oe' }[char]))
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/&/g, ' and ')
    .replace(/’/g, "'");
  if (album) {
    const suffix = /\s*(?:[-–—:]\s*)?(?:\([^)]*(?:remaster(?:ed)?|deluxe|expanded|anniversary|bonus|reissue|special\s+edition)[^)]*\)|\[[^\]]*(?:remaster(?:ed)?|deluxe|expanded|anniversary|bonus|reissue|special\s+edition)[^\]]*\]|(?:remaster(?:ed)?|deluxe|expanded|anniversary|bonus|reissue|special\s+edition).*)\s*$/i;
    let previous = '';
    while (previous !== text) {
      previous = text;
      text = text.replace(suffix, '').trim();
    }
  }
  const normalized = text.replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  if (normalized || !text.trim()) return normalized;
  return `symbol:${[...text].filter((char) => !/\s/u.test(char)).map((char) => char.codePointAt(0).toString(16)).join(',')}`;
}

export function lastFmAlbumKey(artist, album) {
  return `${normalizeName(artist)}\0${normalizeName(album, { album: true })}`;
}

export async function fetchLastFmAlbumStats(rows) {
  const unique = new Map();
  for (const row of rows || []) {
    const artist = String(row?.artist || '').trim();
    const album = String(row?.album || '').trim();
    if (!artist || !album) continue;
    unique.set(lastFmAlbumKey(artist, album), { artist, album });
  }
  if (!unique.size) return new Map();
  try {
    const response = await fetch(MATCH_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ albums: [...unique.values()] }),
    });
    if (!response.ok) return new Map();
    const payload = await response.json();
    return new Map((payload.albums || []).map((item) => [item.key, item]));
  } catch {
    return new Map();
  }
}

function compact(value) {
  return new Intl.NumberFormat('pl-PL', {
    notation: Number(value || 0) >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(Number(value || 0));
}

function formattedDate(value) {
  if (!value) return 'never';
  return new Intl.DateTimeFormat('pl-PL', { dateStyle: 'medium' }).format(new Date(value));
}

export function createLastFmAlbumBadge(row, statsMap) {
  const stat = statsMap?.get(lastFmAlbumKey(row?.artist, row?.album));
  if (!stat) return null;
  const badge = document.createElement('a');
  badge.className = `lastfm-album-badge${stat.matched ? ' is-matched' : ' is-zero'}`;
  badge.href = stat.lastfmUrl || `https://www.last.fm/music/${encodeURIComponent(row.artist)}/${encodeURIComponent(row.album)}`;
  badge.target = '_blank';
  badge.rel = 'noopener noreferrer';
  badge.textContent = `Last.fm ${compact(stat.albumScrobbles)} scrobbles`;
  badge.title = stat.matched
    ? `${compact(stat.artistScrobbles)} artist scrobbles · ${compact(stat.uniqueTracks)} unique tracks · last: ${formattedDate(stat.lastScrobbleAt)}`
    : `No scrobbles matched for ${row.artist} — ${row.album}`;
  return badge;
}

export function appendLastFmAlbumBadge(container, row, statsMap) {
  const badge = createLastFmAlbumBadge(row, statsMap);
  if (badge) container?.appendChild(badge);
  return badge;
}

export function artistScrobblesFromAlbums(artist, rows, statsMap) {
  for (const row of rows || []) {
    if (normalizeName(row?.artist) !== normalizeName(artist)) continue;
    const stat = statsMap?.get(lastFmAlbumKey(row.artist, row.album));
    if (stat) return Number(stat.artistScrobbles || 0);
  }
  return null;
}
