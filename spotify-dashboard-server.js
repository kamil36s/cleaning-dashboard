import express from 'express';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const ROOT = path.dirname(__filename);

loadEnvFiles([
  path.join(ROOT, '.env'),
  path.join(ROOT, '.env.local'),
  path.join(ROOT, '.env.development'),
]);

const PORT = normalizePort(process.env.PORT || process.env.DASHBOARD_PORT || '4173');
const HOST = String(process.env.HOST || process.env.DASHBOARD_HOST || '127.0.0.1').trim();
const DASHBOARD_URL = String(
  process.env.DASHBOARD_URL || `http://${HOST === '0.0.0.0' ? 'localhost' : HOST}:${PORT}`,
).replace(/\/+$/, '');

const SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token';
const SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize';
const SPOTIFY_CURRENTLY_PLAYING_URL =
  'https://api.spotify.com/v1/me/player/currently-playing?additional_types=track';
const SPOTIFY_QUEUE_URL = 'https://api.spotify.com/v1/me/player/queue';
const SPOTIFY_PLAYER_API_BASE = 'https://api.spotify.com/v1/me/player';
const SPOTIFY_SCOPE = 'user-read-currently-playing user-read-playback-state user-modify-playback-state';
const SPOTIFY_STATE_PATH = path.join(ROOT, 'data', 'spotify', 'state.json');
const SPOTIFY_SCREENSAVER_SETTINGS_PATH = path.join(ROOT, 'data', 'spotify', 'screensaver-settings.json');
const ARTIST_FACTS_DIR = path.join(ROOT, 'data', 'spotify', 'artist-facts');
const DEFAULT_IDLE_MINUTES = 3;
const DEFAULT_CHECK_INTERVAL_MS = 5000;

let spotifyAccessTokenCache = {
  accessToken: '',
  expiresAt: 0,
};

const app = express();

app.disable('x-powered-by');

app.get('/api/spotify/status', (_req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.json(getSpotifyStatus());
});

app.get('/api/spotify/auth/start', (req, res) => {
  try {
    res.redirect(makeSpotifyAuthUrl(String(req.query.next || '')));
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

app.get('/api/spotify/oauth/callback', async (req, res) => {
  try {
    const nextUrl = await handleSpotifyCallback(req.query);
    res.redirect(nextUrl);
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

app.get('/api/screensaver-status', async (_req, res) => {
  res.setHeader('Cache-Control', 'no-store');

  try {
    const status = await getSpotifyScreensaverStatus();
    res.json(status);
  } catch (error) {
    res.json(emptyScreensaverStatus(error.message || 'Spotify status unavailable'));
  }
});

app.get('/api/screensaver-config', (_req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.json(readScreensaverConfig());
});

app.post('/api/screensaver-config', express.json(), (req, res) => {
  try {
    res.json(writeScreensaverConfig(req.body));
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

app.post('/api/spotify/player', express.json(), async (req, res) => {
  try {
    res.json(await controlSpotifyPlayer(req.body?.action));
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

app.get('/api/artist-facts', (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.json(readArtistFacts(String(req.query.artist || '')));
});

app.post('/api/artist-facts', express.json({ limit: '1mb' }), (req, res) => {
  try {
    res.json(writeArtistFacts(req.body));
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

app.get('/spotify-screensaver', (_req, res) => {
  res.sendFile(path.join(ROOT, 'spotify-screensaver.html'));
});

app.get('/artist-facts-screensaver', (_req, res) => {
  res.sendFile(path.join(ROOT, 'artist-facts-screensaver.html'));
});

app.use(express.static(ROOT, {
  etag: true,
  index: ['index.html'],
  maxAge: 0,
}));

app.listen(PORT, HOST, () => {
  console.log(`Dashboard server running at ${DASHBOARD_URL}`);
  console.log(`Spotify screensaver: ${DASHBOARD_URL}/spotify-screensaver`);
});

function normalizePort(value) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`Invalid PORT/DASHBOARD_PORT value: ${value}`);
  }
  return parsed;
}

function loadEnvFiles(files) {
  for (const file of files) {
    if (!fs.existsSync(file)) continue;

    const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith('#')) continue;

      const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
      if (!match) continue;

      const [, key, rawValue] = match;
      if (process.env[key] !== undefined) continue;

      let value = rawValue.trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      process.env[key] = value;
    }
  }
}

async function getSpotifyScreensaverStatus() {
  const status = getSpotifyStatus();
  if (!status.configured && !String(process.env.SPOTIFY_ACCESS_TOKEN || '').trim()) {
    return emptyScreensaverStatus('Spotify is not configured', true);
  }

  const token = await getSpotifyAccessToken();
  if (!token) return emptyScreensaverStatus('Spotify is not authenticated', true);

  const response = await fetch(SPOTIFY_CURRENTLY_PLAYING_URL, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
  });

  if (response.status === 204 || response.status === 205) {
    return emptyScreensaverStatus('Nothing is currently playing');
  }

  if (response.status === 401 || response.status === 403) {
    return emptyScreensaverStatus('Spotify authentication failed', true);
  }

  if (!response.ok) {
    return emptyScreensaverStatus(`Spotify API returned ${response.status}`);
  }

  const payload = await response.json();
  const item = payload?.item;
  const track = normalizeSpotifyTrack(item);
  const isTrack = payload?.currently_playing_type === 'track' && Boolean(track);
  const isPlaying = Boolean(payload?.is_playing);
  const nothingPlaying = !isTrack;
  const shouldShow = Boolean(isTrack && isPlaying && !nothingPlaying);
  const settings = readScreensaverConfig();
  const nextTrack = settings.showNextTrack ? await readSpotifyNextTrack(token) : null;

  if (!shouldShow) {
    return {
      ...emptyScreensaverStatus(isTrack ? 'Spotify is paused' : 'Nothing is currently playing'),
      isPlaying,
      nothingPlaying,
      title: track?.title || '',
      artist: track?.artist || '',
      album: track?.album || '',
      albumCoverUrl: track?.albumCoverUrl || '',
      progressMs: numberOrZero(payload?.progress_ms),
      durationMs: track?.durationMs || 0,
      nextTrack,
    };
  }

  return {
    shouldShow: true,
    isPlaying: true,
    nothingPlaying: false,
    title: track.title,
    artist: track.artist,
    album: track.album,
    albumCoverUrl: track.albumCoverUrl,
    progressMs: numberOrZero(payload.progress_ms),
    durationMs: track.durationMs,
    nextTrack,
    fetchedAt: Date.now(),
  };
}

async function getSpotifyAccessToken() {
  const state = readSpotifyState();
  const refreshToken = String(state.refresh_token || process.env.SPOTIFY_REFRESH_TOKEN || '').trim();
  const clientId = String(process.env.SPOTIFY_CLIENT_ID || '').trim();
  const clientSecret = String(process.env.SPOTIFY_CLIENT_SECRET || '').trim();

  if (state.access_token && Number(state.expires_at || 0) * 1000 > Date.now() + 60000) {
    return state.access_token;
  }

  if (refreshToken && clientId && clientSecret) {
    if (spotifyAccessTokenCache.accessToken && Date.now() < spotifyAccessTokenCache.expiresAt) {
      return spotifyAccessTokenCache.accessToken;
    }

    const credentials = Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
    const response = await fetch(SPOTIFY_TOKEN_URL, {
      method: 'POST',
      headers: {
        Authorization: `Basic ${credentials}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
      }),
    });

    if (!response.ok) return '';

    const tokenPayload = await response.json();
    const accessToken = String(tokenPayload.access_token || '').trim();
    if (!accessToken) return '';

    const expiresInSeconds = Number(tokenPayload.expires_in || 3600);
    spotifyAccessTokenCache = {
      accessToken,
      expiresAt: Date.now() + Math.max(60, expiresInSeconds - 60) * 1000,
    };

    writeSpotifyState({
      ...state,
      access_token: accessToken,
      refresh_token: tokenPayload.refresh_token || refreshToken,
      expires_at: Math.floor(spotifyAccessTokenCache.expiresAt / 1000),
      token_type: tokenPayload.token_type || state.token_type,
    });
    return accessToken;
  }

  return String(process.env.SPOTIFY_ACCESS_TOKEN || '').trim();
}

function getSpotifyStatus() {
  const state = readSpotifyState();
  const configured = Boolean(
    String(process.env.SPOTIFY_CLIENT_ID || '').trim() &&
    String(process.env.SPOTIFY_CLIENT_SECRET || '').trim() &&
    spotifyRedirectUri(),
  );

  return {
    configured,
    connected: Boolean(
      state.refresh_token ||
      state.access_token ||
      String(process.env.SPOTIFY_REFRESH_TOKEN || '').trim() ||
      String(process.env.SPOTIFY_ACCESS_TOKEN || '').trim()
    ),
    redirectUri: spotifyRedirectUri(),
    scope: SPOTIFY_SCOPE,
    connectedAt: state.connected_at || '',
    reason: configured ? '' : 'Missing SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, or SPOTIFY_REDIRECT_URI',
  };
}

async function spotifyApiRequest(method, url, token = '') {
  const accessToken = token || await getSpotifyAccessToken();
  if (!accessToken) throw new Error('Spotify is not connected');

  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: 'application/json',
    },
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`Spotify API error ${response.status}: ${body}`);
  }
  if (response.status === 204 || response.status === 205) return {};
  return response.json();
}

async function readSpotifyNextTrack(token) {
  try {
    const payload = await spotifyApiRequest('GET', SPOTIFY_QUEUE_URL, token);
    const queue = Array.isArray(payload?.queue) ? payload.queue : [];
    for (const item of queue) {
      const track = normalizeSpotifyTrack(item);
      if (track) {
        return {
          title: track.title,
          artist: track.artist,
          album: track.album,
          albumCoverUrl: track.albumCoverUrl,
        };
      }
    }
  } catch {
    return null;
  }
  return null;
}

async function controlSpotifyPlayer(action) {
  const endpoints = {
    previous: ['POST', `${SPOTIFY_PLAYER_API_BASE}/previous`],
    next: ['POST', `${SPOTIFY_PLAYER_API_BASE}/next`],
    play: ['PUT', `${SPOTIFY_PLAYER_API_BASE}/play`],
    pause: ['PUT', `${SPOTIFY_PLAYER_API_BASE}/pause`],
  };
  const normalized = String(action || '').trim().toLowerCase();
  const endpoint = endpoints[normalized];
  if (!endpoint) throw new Error('Unsupported Spotify player action');
  await spotifyApiRequest(endpoint[0], endpoint[1]);
  return { ok: true, action: normalized };
}

function makeSpotifyAuthUrl(nextUrl = '') {
  if (!getSpotifyStatus().configured) {
    throw new Error('Missing SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, or SPOTIFY_REDIRECT_URI');
  }

  const stateToken = crypto.randomBytes(24).toString('base64url');
  const state = readSpotifyState();
  writeSpotifyState({
    ...state,
    pending_oauth_state: stateToken,
    pending_oauth_at: new Date().toISOString(),
    pending_next_url: sanitizeNextUrl(nextUrl),
  });

  const params = new URLSearchParams({
    client_id: process.env.SPOTIFY_CLIENT_ID.trim(),
    response_type: 'code',
    redirect_uri: spotifyRedirectUri(),
    scope: SPOTIFY_SCOPE,
    state: stateToken,
    show_dialog: 'true',
  });

  return `${SPOTIFY_AUTH_URL}?${params.toString()}`;
}

async function handleSpotifyCallback(query) {
  const code = String(query.code || '');
  const incomingState = String(query.state || '');
  if (!code) throw new Error('Missing OAuth code');

  const state = readSpotifyState();
  if (!state.pending_oauth_state || incomingState !== state.pending_oauth_state) {
    throw new Error('OAuth state mismatch');
  }

  const response = await fetch(SPOTIFY_TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: process.env.SPOTIFY_CLIENT_ID.trim(),
      client_secret: process.env.SPOTIFY_CLIENT_SECRET.trim(),
      code,
      grant_type: 'authorization_code',
      redirect_uri: spotifyRedirectUri(),
    }),
  });

  if (!response.ok) throw new Error(`Spotify token exchange failed with ${response.status}`);

  const token = await response.json();
  if (!token.access_token) throw new Error('Spotify did not return an access token');

  const nextUrl = sanitizeNextUrl(state.pending_next_url);
  writeSpotifyState({
    access_token: token.access_token,
    refresh_token: token.refresh_token || state.refresh_token || '',
    expires_at: Math.floor(Date.now() / 1000) + Math.max(60, Number(token.expires_in || 3600) - 60),
    scope: token.scope || '',
    token_type: token.token_type || '',
    connected_at: new Date().toISOString(),
  });

  return nextUrl;
}

function spotifyRedirectUri() {
  return String(process.env.SPOTIFY_REDIRECT_URI || `${DASHBOARD_URL}/api/spotify/oauth/callback`).trim();
}

function sanitizeNextUrl(nextUrl = '') {
  const fallback = '/spotify-screensaver';
  const value = String(nextUrl || '').trim();
  if (!value) return fallback;

  try {
    if (value.startsWith('/')) return value;

    const parsed = new URL(value);
    if (['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)) {
      return value;
    }
  } catch {
    return fallback;
  }

  return fallback;
}

function readSpotifyState() {
  try {
    return JSON.parse(fs.readFileSync(SPOTIFY_STATE_PATH, 'utf8'));
  } catch {
    return {};
  }
}

function writeSpotifyState(state) {
  fs.mkdirSync(path.dirname(SPOTIFY_STATE_PATH), { recursive: true });
  fs.writeFileSync(SPOTIFY_STATE_PATH, `${JSON.stringify(state, null, 2)}\n`);
}

function readScreensaverConfig() {
  const raw = readJsonFile(SPOTIFY_SCREENSAVER_SETTINGS_PATH, {});
  const settings = normalizeScreensaverConfig(raw);
  return {
    ok: true,
    ...settings,
    spotify: getSpotifyStatus(),
    screensaverUrl: '/spotify-screensaver',
    manualUrl: '/spotify-screensaver.html?manual=1',
    updatedAt: raw.updatedAt || '',
  };
}

function writeScreensaverConfig(payload) {
  const current = readScreensaverConfig();
  const settings = normalizeScreensaverConfig({
    idleMinutes: payload?.idleMinutes ?? current.idleMinutes,
    checkIntervalMs: payload?.checkIntervalMs ?? current.checkIntervalMs,
    backgroundMode: payload?.backgroundMode ?? current.backgroundMode,
    coverScale: payload?.coverScale ?? current.coverScale,
    showNextTrack: payload?.showNextTrack ?? current.showNextTrack,
    nextTrackShowAtStart: payload?.nextTrackShowAtStart ?? current.nextTrackShowAtStart,
    nextTrackShowAtEnd: payload?.nextTrackShowAtEnd ?? current.nextTrackShowAtEnd,
    nextTrackTimingUnit: payload?.nextTrackTimingUnit ?? current.nextTrackTimingUnit,
    nextTrackStartWindow: payload?.nextTrackStartWindow ?? current.nextTrackStartWindow,
    nextTrackEndWindow: payload?.nextTrackEndWindow ?? current.nextTrackEndWindow,
    progressStyle: payload?.progressStyle ?? current.progressStyle,
    screensaverLayout: payload?.screensaverLayout ?? current.screensaverLayout,
    showArtistFacts: payload?.showArtistFacts ?? current.showArtistFacts,
    artistFactSlideSeconds: payload?.artistFactSlideSeconds ?? current.artistFactSlideSeconds,
    artistFactLayout: payload?.artistFactLayout ?? current.artistFactLayout,
    artistFactMediaMode: payload?.artistFactMediaMode ?? current.artistFactMediaMode,
  });
  writeJsonFile(SPOTIFY_SCREENSAVER_SETTINGS_PATH, {
    ...settings,
    updatedAt: new Date().toISOString(),
  });
  return readScreensaverConfig();
}

function normalizeScreensaverConfig(raw = {}) {
  const idleMinutes = clampNumber(raw.idleMinutes, DEFAULT_IDLE_MINUTES, 0.25, 120);
  const checkIntervalMs = Math.round(clampNumber(raw.checkIntervalMs, DEFAULT_CHECK_INTERVAL_MS, 1000, 60000));
  const allowedModes = new Set(['black', 'blur', 'gradient', 'ambient']);
  const backgroundMode = allowedModes.has(String(raw.backgroundMode || '').trim())
    ? String(raw.backgroundMode).trim()
    : 'black';
  const coverScale = clampNumber(raw.coverScale, 1.08, 0.75, 1.35);
  const progressStyles = new Set(['minimal', 'slim', 'glow', 'rail']);
  const progressStyle = progressStyles.has(String(raw.progressStyle || '').trim())
    ? String(raw.progressStyle).trim()
    : 'minimal';
  const layouts = new Set(['center', 'safe-bottom', 'side-right', 'side-left', 'compact']);
  const screensaverLayout = layouts.has(String(raw.screensaverLayout || '').trim())
    ? String(raw.screensaverLayout).trim()
    : 'center';
  const factLayouts = new Set(['side-card', 'left-panel', 'bottom-wide', 'full-height', 'text-focus']);
  const artistFactLayout = factLayouts.has(String(raw.artistFactLayout || '').trim())
    ? String(raw.artistFactLayout).trim()
    : 'side-card';
  const mediaModes = new Set(['media', 'text']);
  const artistFactMediaMode = mediaModes.has(String(raw.artistFactMediaMode || '').trim())
    ? String(raw.artistFactMediaMode).trim()
    : 'media';
  const timingUnits = new Set(['seconds', 'percent']);
  const nextTrackTimingUnit = timingUnits.has(String(raw.nextTrackTimingUnit || '').trim())
    ? String(raw.nextTrackTimingUnit).trim()
    : 'seconds';
  const nextTrackWindowMax = nextTrackTimingUnit === 'percent' ? 100 : 600;
  return {
    idleMinutes,
    checkIntervalMs,
    backgroundMode,
    coverScale,
    showNextTrack: Boolean(raw.showNextTrack),
    nextTrackShowAtStart: Boolean(raw.nextTrackShowAtStart),
    nextTrackShowAtEnd: raw.nextTrackShowAtEnd === undefined ? true : Boolean(raw.nextTrackShowAtEnd),
    nextTrackTimingUnit,
    nextTrackStartWindow: clampNumber(raw.nextTrackStartWindow, 12, 0, nextTrackWindowMax),
    nextTrackEndWindow: clampNumber(raw.nextTrackEndWindow, 20, 0, nextTrackWindowMax),
    progressStyle,
    screensaverLayout,
    showArtistFacts: Boolean(raw.showArtistFacts),
    artistFactSlideSeconds: clampNumber(raw.artistFactSlideSeconds, 14, 4, 120),
    artistFactLayout,
    artistFactMediaMode,
  };
}

function clampNumber(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

function readJsonFile(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJsonFile(file, payload) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(payload, null, 2)}\n`);
}

function artistFactSlug(value) {
  return cleanText(value)
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'artist';
}

function normalizeArtistFacts(payload = {}) {
  const artist = cleanText(payload.artist);
  if (!artist) throw new Error('Artist facts JSON needs an artist field');
  const rawFacts = Array.isArray(payload.facts) ? payload.facts : [];
  const facts = rawFacts
    .map((item) => {
      if (typeof item === 'string') return { text: cleanText(item) };
      if (!item || typeof item !== 'object') return null;
      const text = cleanText(item.text);
      if (!text) return null;
      return {
        ...(item.title ? { title: cleanText(item.title) } : {}),
        text,
        ...(item.source ? { source: cleanText(item.source) } : {}),
        ...(item.sourceUrl ? { sourceUrl: cleanText(item.sourceUrl) } : {}),
      };
    })
    .filter(Boolean);
  if (!facts.length) throw new Error('Artist facts JSON needs at least one fact');
  const commons = payload.commons && typeof payload.commons === 'object' ? payload.commons : {};
  const media = Array.isArray(payload.media)
    ? payload.media
        .map((item) => {
          if (!item || typeof item !== 'object') return null;
          const url = cleanText(item.url || item.localUrl);
          if (!url) return null;
          return {
            title: cleanText(item.title),
            caption: cleanText(item.caption),
            credit: cleanText(item.credit),
            license: cleanText(item.license),
            sourceUrl: cleanText(item.sourceUrl),
            url,
            localUrl: cleanText(item.localUrl),
          };
        })
        .filter(Boolean)
    : [];
  return {
    artist,
    slug: artistFactSlug(artist),
    summary: cleanText(payload.summary),
    slideSeconds: clampNumber(payload.slideSeconds, 14, 4, 120),
    commons: {
      category: cleanText(commons.category || `Category:${artist}`),
      limit: Math.round(clampNumber(commons.limit, 6, 0, 12)),
    },
    facts,
    media,
    updatedAt: new Date().toISOString(),
  };
}

function readArtistFacts(artist) {
  const slug = artistFactSlug(artist);
  const file = path.join(ARTIST_FACTS_DIR, `${slug}.json`);
  const data = readJsonFile(file, null);
  if (!data) return { ok: true, artist: cleanText(artist), slug, facts: [], media: [] };
  return { ok: true, ...normalizeArtistFacts(data) };
}

function writeArtistFacts(payload) {
  const data = normalizeArtistFacts(payload);
  writeJsonFile(path.join(ARTIST_FACTS_DIR, `${data.slug}.json`), data);
  return { ok: true, artist: data.artist, slug: data.slug };
}

function emptyScreensaverStatus(reason = '', needsAuth = false) {
  return {
    shouldShow: false,
    isPlaying: false,
    nothingPlaying: true,
    title: '',
    artist: '',
    album: '',
    albumCoverUrl: '',
    progressMs: 0,
    durationMs: 0,
    fetchedAt: Date.now(),
    reason,
    needsAuth,
  };
}

function cleanText(value) {
  return String(value || '').trim();
}

function artistsText(item) {
  const artists = Array.isArray(item?.artists) ? item.artists : [];
  return artists.map((artist) => cleanText(artist?.name)).filter(Boolean).join(', ');
}

function albumCoverUrl(item) {
  const images = Array.isArray(item?.album?.images) ? item.album.images : [];
  const sorted = [...images].sort((a, b) => numberOrZero(b?.width) - numberOrZero(a?.width));
  return cleanText(sorted[0]?.url);
}

function normalizeSpotifyTrack(item) {
  if (!item || item.type !== 'track') return null;
  return {
    title: cleanText(item.name),
    artist: artistsText(item),
    album: cleanText(item.album?.name),
    albumCoverUrl: albumCoverUrl(item),
    durationMs: numberOrZero(item.duration_ms),
  };
}

function numberOrZero(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}
