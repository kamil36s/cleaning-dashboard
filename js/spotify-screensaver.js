const STATUS_URL = '/api/screensaver-status';
const SPOTIFY_STATUS_URL = '/api/spotify/status';
const SCREENSAVER_CONFIG_URL = '/api/screensaver-config';
const SPOTIFY_AUTH_START_URL = '/api/spotify/auth/start';
const SPOTIFY_PLAYER_URL = '/api/spotify/player';
const ARTIST_FACTS_URL = '/api/artist-facts';
const REFRESH_MS = 3000;
const IS_MANUAL = new URLSearchParams(window.location.search).get('manual') === '1';

const body = document.body;
const cover = document.getElementById('album-cover');
const backgroundCover = document.getElementById('background-cover');
const title = document.getElementById('track-title');
const artist = document.getElementById('track-artist');
const album = document.getElementById('track-album');
const progressFill = document.getElementById('progress-fill');
const progressTimeLabel = document.getElementById('progress-time-label');
const previousButton = document.getElementById('previous-button');
const playPauseButton = document.getElementById('play-pause-button');
const playPauseIcon = document.getElementById('play-pause-icon');
const nextButton = document.getElementById('next-button');
const nextTrack = document.getElementById('next-track');
const nextTrackCover = document.getElementById('next-track-cover');
const nextTrackTitle = document.getElementById('next-track-title');
const nextTrackArtist = document.getElementById('next-track-artist');
const artistFacts = document.getElementById('artist-facts');
const artistFactsImage = document.getElementById('artist-facts-image');
const artistFactsKicker = document.getElementById('artist-facts-kicker');
const artistFactsTitle = document.getElementById('artist-facts-title');
const artistFactsText = document.getElementById('artist-facts-text');
const artistFactsCredit = document.getElementById('artist-facts-credit');
const message = document.getElementById('screensaver-message');
const messageTitle = document.getElementById('screensaver-message-title');
const messageCopy = document.getElementById('screensaver-message-copy');
const authLink = document.getElementById('spotify-auth-link');
const fullscreenButton = document.getElementById('fullscreen-button');
const fullscreenFloat = document.getElementById('fullscreen-float');
const backLink = document.getElementById('back-link');

let currentStatus = null;
let screensaverConfig = {
  backgroundMode: 'black',
  coverScale: 1.08,
  controlScale: 1,
  showNextTrack: false,
  nextTrackShowAtStart: false,
  nextTrackShowAtEnd: true,
  nextTrackTimingUnit: 'seconds',
  nextTrackStartWindow: 12,
  nextTrackEndWindow: 20,
  progressStyle: 'minimal',
  screensaverLayout: 'center',
  showArtistFacts: false,
  artistFactSlideSeconds: 14,
  artistFactLayout: 'side-card',
  artistFactMediaMode: 'media',
};
let initialized = false;
let progressFrame = 0;
let currentArtistKey = '';
let artistFactsPayload = null;
let artistFactsFetchedAt = 0;

fullscreenButton?.addEventListener('click', async () => {
  await enterFullscreen();
});

fullscreenFloat?.addEventListener('click', async () => {
  await enterFullscreen();
});

document.addEventListener('fullscreenchange', updateFullscreenPrompt);

previousButton?.addEventListener('click', () => sendPlayerCommand('previous'));
nextButton?.addEventListener('click', () => sendPlayerCommand('next'));
playPauseButton?.addEventListener('click', () => {
  sendPlayerCommand(currentStatus?.isPlaying ? 'pause' : 'play');
});

async function enterFullscreen() {
  try {
    if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
      await document.documentElement.requestFullscreen();
    }
  } catch (error) {
    console.warn('Could not enter fullscreen:', error);
  } finally {
    updateFullscreenPrompt();
  }
}

function updateFullscreenPrompt() {
  const hideControls = !IS_MANUAL || Boolean(document.fullscreenElement);
  body.classList.toggle('is-fullscreen', Boolean(document.fullscreenElement));
  if (fullscreenFloat) fullscreenFloat.hidden = hideControls;
  if (backLink) backLink.hidden = hideControls;
}

async function init() {
  screensaverConfig = await fetchScreensaverConfig();
  applyBackgroundMode(screensaverConfig.backgroundMode);
  applyProgressStyle(screensaverConfig.progressStyle);
  applyScreensaverLayout(screensaverConfig.screensaverLayout);
  applyArtistFactDisplay();

  const spotify = await fetchSpotifyStatus();
  initialized = true;
  updateFullscreenPrompt();

  if (!spotify.configured) {
    showMessage(
      'Spotify is not configured',
      'Set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, and SPOTIFY_REDIRECT_URI, then restart the dashboard server.',
      { showAuth: false },
    );
    return;
  }

  if (!spotify.connected) {
    const next = window.location.href;
    const authUrl = `${SPOTIFY_AUTH_START_URL}?next=${encodeURIComponent(next)}`;
    if (new URLSearchParams(window.location.search).get('manual') === '1') {
      window.location.assign(authUrl);
      return;
    }
    showMessage('Connect Spotify', 'Spotify authorization is required before this screensaver can show now playing data.', {
      authUrl,
    });
    return;
  }

  fetchStatus();
  setInterval(fetchStatus, REFRESH_MS);
  startProgressLoop();
}

async function fetchScreensaverConfig() {
  try {
    const response = await fetch(SCREENSAVER_CONFIG_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    const config = await response.json();
    return {
      backgroundMode: String(config?.backgroundMode || 'black'),
      coverScale: numberOrDefault(config?.coverScale, 1.08),
      controlScale: clampNumber(config?.controlScale, 0.1, 1, 1),
      showNextTrack: Boolean(config?.showNextTrack),
      nextTrackShowAtStart: Boolean(config?.nextTrackShowAtStart),
      nextTrackShowAtEnd: config?.nextTrackShowAtEnd !== false,
      nextTrackTimingUnit: String(config?.nextTrackTimingUnit || 'seconds') === 'percent' ? 'percent' : 'seconds',
      nextTrackStartWindow: numberOrDefault(config?.nextTrackStartWindow, 12),
      nextTrackEndWindow: numberOrDefault(config?.nextTrackEndWindow, 20),
      progressStyle: String(config?.progressStyle || 'minimal'),
      screensaverLayout: String(config?.screensaverLayout || 'center'),
      showArtistFacts: Boolean(config?.showArtistFacts),
      artistFactSlideSeconds: numberOrDefault(config?.artistFactSlideSeconds, 14),
      artistFactLayout: String(config?.artistFactLayout || 'side-card'),
      artistFactMediaMode: String(config?.artistFactMediaMode || 'media') === 'text' ? 'text' : 'media',
    };
  } catch (error) {
    return {
      backgroundMode: 'black',
      coverScale: 1.08,
      controlScale: 1,
      showNextTrack: false,
      nextTrackShowAtStart: false,
      nextTrackShowAtEnd: true,
      nextTrackTimingUnit: 'seconds',
      nextTrackStartWindow: 12,
      nextTrackEndWindow: 20,
      progressStyle: 'minimal',
      screensaverLayout: 'center',
      showArtistFacts: false,
      artistFactSlideSeconds: 14,
      artistFactLayout: 'side-card',
      artistFactMediaMode: 'media',
    };
  }
}

async function sendPlayerCommand(action) {
  try {
    setControlsDisabled(true);
    const response = await fetch(SPOTIFY_PLAYER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ action }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload?.error || `Status ${response.status}`);
    }
    window.setTimeout(fetchStatus, 450);
  } catch (error) {
    console.warn('Spotify playback command failed:', error);
  } finally {
    window.setTimeout(() => setControlsDisabled(false), 500);
  }
}

function setControlsDisabled(disabled) {
  [previousButton, playPauseButton, nextButton].forEach((button) => {
    if (button) button.disabled = disabled;
  });
}

async function fetchSpotifyStatus() {
  try {
    const response = await fetch(SPOTIFY_STATUS_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    return await response.json();
  } catch (error) {
    return { configured: false, connected: false, error: error.message };
  }
}

async function fetchStatus() {
  try {
    const response = await fetch(STATUS_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    const status = await response.json();
    if (status?.needsAuth) {
      const authUrl = `${SPOTIFY_AUTH_START_URL}?next=${encodeURIComponent(window.location.href)}`;
      showMessage('Connect Spotify', 'Spotify authorization expired or is missing.', { authUrl });
      return;
    }
    currentStatus = normalizeStatus(status);
    if (IS_MANUAL && !currentStatus.shouldShow) {
      showMessage(
        currentStatus.reason || 'Nothing is playing',
        'Spotify is connected. Start playback and this screen will switch to the album cover view automatically.',
        { showAuth: false },
      );
      return;
    }
    render(currentStatus);
  } catch (error) {
    currentStatus = null;
    renderIdle();
  }
}

function normalizeStatus(status) {
  return {
    shouldShow: Boolean(status?.shouldShow),
    isPlaying: Boolean(status?.isPlaying),
    title: String(status?.title || ''),
    artist: String(status?.artist || ''),
    album: String(status?.album || ''),
    albumCoverUrl: String(status?.albumCoverUrl || ''),
    progressMs: numberOrZero(status?.progressMs),
    durationMs: numberOrZero(status?.durationMs),
    fetchedAt: numberOrZero(status?.fetchedAt) || Date.now(),
    reason: String(status?.reason || ''),
    nextTrack: status?.nextTrack && typeof status.nextTrack === 'object'
      ? {
          title: String(status.nextTrack.title || ''),
          artist: String(status.nextTrack.artist || ''),
          album: String(status.nextTrack.album || ''),
          albumCoverUrl: String(status.nextTrack.albumCoverUrl || ''),
        }
      : null,
  };
}

function render(status) {
  if (!status.shouldShow) {
    renderIdle();
    return;
  }

  hideMessage();
  body.classList.remove('is-idle');

  title.textContent = status.title;
  artist.textContent = status.artist;
  album.textContent = status.album;
  renderPlayPauseIcon(status.isPlaying);
  renderNextTrack(status.nextTrack);
  updateArtistFacts(status);

  if (cover.src !== status.albumCoverUrl) {
    cover.crossOrigin = 'anonymous';
    cover.src = status.albumCoverUrl;
  }
  if (backgroundCover && backgroundCover.src !== status.albumCoverUrl) {
    backgroundCover.crossOrigin = 'anonymous';
    backgroundCover.src = status.albumCoverUrl;
  }
  cover.alt = status.album ? `${status.album} album cover` : 'Album cover';
  applyAlbumColors(status.albumCoverUrl);

  updateProgress();
}

function renderIdle() {
  hideMessage();
  body.classList.add('is-idle');
  title.textContent = '';
  artist.textContent = '';
  album.textContent = '';
  renderNextTrack(null);
  hideArtistFacts();
  if (progressFill) progressFill.style.transform = 'scaleX(0)';
  setTimeLabels(0, 0);
  cover.removeAttribute('src');
  backgroundCover?.removeAttribute('src');
  cover.alt = '';
}

function renderPlayPauseIcon(isPlaying) {
  if (!playPauseIcon) return;
  playPauseIcon.innerHTML = isPlaying
    ? '<path d="M9 6v12" /><path d="M15 6v12" />'
    : '<path d="m8 5 11 7-11 7V5Z" />';
  if (playPauseButton) {
    playPauseButton.setAttribute('aria-label', isPlaying ? 'Pause' : 'Play');
    playPauseButton.title = isPlaying ? 'Pause' : 'Play';
  }
}

function renderNextTrack(track) {
  if (!nextTrack || !nextTrackTitle || !nextTrackArtist) return;
  if (!screensaverConfig.showNextTrack || !track?.title) {
    nextTrack.hidden = true;
    nextTrackTitle.textContent = '';
    nextTrackArtist.textContent = '';
    if (nextTrackCover) {
      nextTrackCover.hidden = true;
      nextTrackCover.removeAttribute('src');
    }
    return;
  }
  nextTrack.hidden = !shouldShowNextTrackTile(track);
  nextTrackTitle.textContent = track.title;
  nextTrackArtist.textContent = track.artist || '';
  if (nextTrackCover) {
    if (track.albumCoverUrl) {
      nextTrackCover.hidden = false;
      nextTrackCover.referrerPolicy = 'no-referrer';
      nextTrackCover.src = track.albumCoverUrl;
      nextTrackCover.alt = track.album ? `${track.album} album cover` : 'Next track album cover';
    } else {
      nextTrackCover.hidden = true;
      nextTrackCover.removeAttribute('src');
    }
  }
}

function updateNextTrackVisibility() {
  if (!nextTrack) return;
  if (!currentStatus?.nextTrack?.title) {
    nextTrack.hidden = true;
    return;
  }
  nextTrack.hidden = !shouldShowNextTrackTile(currentStatus.nextTrack);
}

function shouldShowNextTrackTile(track) {
  if (!screensaverConfig.showNextTrack || !track?.title || !currentStatus?.shouldShow) return false;
  const showAtStart = Boolean(screensaverConfig.nextTrackShowAtStart);
  const showAtEnd = Boolean(screensaverConfig.nextTrackShowAtEnd);
  if (!showAtStart && !showAtEnd) return false;
  if (!currentStatus.durationMs) return true;

  const progress = getLiveProgressMs();
  const remaining = Math.max(0, currentStatus.durationMs - progress);
  const startWindowMs = nextTrackWindowMs(screensaverConfig.nextTrackStartWindow);
  const endWindowMs = nextTrackWindowMs(screensaverConfig.nextTrackEndWindow);
  return (showAtStart && progress <= startWindowMs) || (showAtEnd && remaining <= endWindowMs);
}

function nextTrackWindowMs(value) {
  const normalized = Math.max(0, Number(value || 0));
  if (screensaverConfig.nextTrackTimingUnit === 'percent') {
    return currentStatus.durationMs * Math.min(100, normalized) / 100;
  }
  return normalized * 1000;
}

async function updateArtistFacts(status) {
  if (!screensaverConfig.showArtistFacts || !status?.artist) {
    hideArtistFacts();
    return;
  }
  const primaryArtist = primaryArtistName(status.artist);
  if (!primaryArtist) {
    hideArtistFacts();
    return;
  }
  const key = primaryArtist.toLowerCase();
  if (key !== currentArtistKey || !artistFactsPayload) {
    currentArtistKey = key;
    artistFactsPayload = null;
    artistFactsFetchedAt = Date.now();
    hideArtistFacts();
    try {
      const response = await fetch(`${ARTIST_FACTS_URL}?artist=${encodeURIComponent(primaryArtist)}`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Status ${response.status}`);
      const payload = await response.json();
      if (currentArtistKey === key) {
        artistFactsPayload = payload;
        artistFactsFetchedAt = Date.now();
      }
    } catch (error) {
      artistFactsPayload = null;
    }
  }
  renderArtistFacts();
}

function renderArtistFacts() {
  if (!artistFacts || !artistFactsPayload?.facts?.length) {
    hideArtistFacts();
    return;
  }
  const facts = artistFactsPayload.facts;
  const slideMs = Math.max(4000, Number(screensaverConfig.artistFactSlideSeconds || 14) * 1000);
  const index = Math.floor((Date.now() - artistFactsFetchedAt) / slideMs) % facts.length;
  const fact = facts[index] || facts[0];
  const media = Array.isArray(artistFactsPayload.media) ? artistFactsPayload.media : [];
  const wantsMedia = screensaverConfig.artistFactMediaMode !== 'text';
  const image = wantsMedia && media.length ? media[index % media.length] : null;

  artistFacts.hidden = false;
  body.classList.add('has-artist-facts');
  if (artistFactsKicker) artistFactsKicker.textContent = artistFactsPayload.artist || 'Artist notes';
  if (artistFactsTitle) artistFactsTitle.textContent = fact.title || 'Ciekawostka';
  if (artistFactsText) artistFactsText.textContent = fact.text || '';
  if (artistFactsCredit) {
    artistFactsCredit.textContent = image?.license
      ? `${image.license}${image.credit ? ` / ${image.credit}` : ''}`
      : (fact.source || '');
  }
  if (artistFactsImage) {
    const imageUrl = image?.localUrl || image?.url || '';
    if (wantsMedia && imageUrl) {
      artistFactsImage.hidden = false;
      artistFactsImage.src = imageUrl;
      artistFactsImage.alt = image.caption || image.title || artistFactsPayload.artist || '';
    } else {
      artistFactsImage.hidden = true;
      artistFactsImage.removeAttribute('src');
    }
  }
}

function hideArtistFacts() {
  body.classList.remove('has-artist-facts');
  if (!artistFacts) return;
  artistFacts.hidden = true;
  if (artistFactsImage) {
    artistFactsImage.hidden = true;
    artistFactsImage.removeAttribute('src');
  }
}

function primaryArtistName(value) {
  return String(value || '').split(',')[0].trim();
}

function showMessage(heading, copy, options = {}) {
  body.classList.remove('is-idle');
  body.classList.add('has-message');
  message.hidden = false;
  messageTitle.textContent = heading;
  messageCopy.textContent = copy;

  const showAuth = options.showAuth !== false && options.authUrl;
  authLink.hidden = !showAuth;
  if (showAuth) {
    authLink.href = options.authUrl;
  }
}

function hideMessage() {
  if (!initialized) return;
  body.classList.remove('has-message');
  message.hidden = true;
}

function updateProgress() {
  if (!currentStatus?.shouldShow || !currentStatus.durationMs) {
    if (progressFill) progressFill.style.transform = 'scaleX(0)';
    setTimeLabels(0, 0);
    updateNextTrackVisibility();
    return;
  }

  const progress = getLiveProgressMs();
  const ratio = Math.max(0, Math.min(1, progress / currentStatus.durationMs));
  if (progressFill) progressFill.style.transform = `scaleX(${ratio})`;
  setTimeLabels(progress, currentStatus.durationMs);
  updateNextTrackVisibility();
}

function getLiveProgressMs() {
  if (!currentStatus?.durationMs) return 0;
  const elapsedSinceFetch = currentStatus.isPlaying ? Date.now() - currentStatus.fetchedAt : 0;
  return Math.min(currentStatus.durationMs, currentStatus.progressMs + elapsedSinceFetch);
}

function setTimeLabels(progressMs, durationMs) {
  if (progressTimeLabel) {
    progressTimeLabel.textContent = `${formatDuration(progressMs)} / ${formatDuration(durationMs)}`;
  }
}

function startProgressLoop() {
  if (progressFrame) return;

  const tick = () => {
    updateProgress();
    progressFrame = window.requestAnimationFrame(tick);
  };
  progressFrame = window.requestAnimationFrame(tick);
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function applyBackgroundMode(mode) {
  const allowed = new Set(['black', 'blur', 'gradient', 'ambient']);
  body.dataset.backgroundMode = allowed.has(mode) ? mode : 'black';
  applyVisualScales();
}

function applyVisualScales() {
  const controlScale = clampNumber(screensaverConfig.controlScale, 0.1, 1, 1);
  const coverScale = clampNumber(screensaverConfig.coverScale, 0.75, 1.35, 1.08);
  const coverBoost = 1 + ((1 - controlScale) * 0.32);
  const effectiveCoverScale = Math.min(1.55, coverScale * coverBoost);

  document.documentElement.style.setProperty('--controls-scale', String(controlScale));
  document.documentElement.style.setProperty('--cover-scale', String(effectiveCoverScale));
}

function applyProgressStyle(style) {
  const allowed = new Set(['minimal', 'slim', 'glow', 'rail']);
  body.dataset.progressStyle = allowed.has(style) ? style : 'minimal';
}

function applyScreensaverLayout(layout) {
  const allowed = new Set(['center', 'safe-bottom', 'side-right', 'side-left', 'compact']);
  body.dataset.layout = allowed.has(layout) ? layout : 'center';
}

function applyArtistFactDisplay() {
  const layouts = new Set(['side-card', 'left-panel', 'bottom-wide', 'full-height', 'text-focus']);
  body.dataset.factLayout = layouts.has(screensaverConfig.artistFactLayout)
    ? screensaverConfig.artistFactLayout
    : 'side-card';
  body.dataset.factMediaMode = screensaverConfig.artistFactMediaMode === 'text' ? 'text' : 'media';
}

async function applyAlbumColors(imageUrl) {
  if (!imageUrl || !['gradient', 'ambient'].includes(body.dataset.backgroundMode)) return;

  try {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.decoding = 'async';
    image.src = imageUrl;
    await image.decode();

    const colors = sampleImageColors(image);
    document.documentElement.style.setProperty('--album-color-a', colors[0]);
    document.documentElement.style.setProperty('--album-color-b', colors[1]);
    document.documentElement.style.setProperty('--album-color-c', colors[2]);
  } catch (error) {
    document.documentElement.style.setProperty('--album-color-a', '#151515');
    document.documentElement.style.setProperty('--album-color-b', '#050505');
    document.documentElement.style.setProperty('--album-color-c', '#222222');
  }
}

function sampleImageColors(image) {
  const canvas = document.createElement('canvas');
  const size = 24;
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(image, 0, 0, size, size);
  const data = ctx.getImageData(0, 0, size, size).data;
  const buckets = new Map();

  for (let index = 0; index < data.length; index += 4) {
    const alpha = data[index + 3];
    if (alpha < 200) continue;
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const brightness = (r + g + b) / 3;
    if (brightness < 18 || brightness > 236) continue;
    const key = `${Math.round(r / 28) * 28},${Math.round(g / 28) * 28},${Math.round(b / 28) * 28}`;
    buckets.set(key, (buckets.get(key) || 0) + 1);
  }

  const colors = [...buckets.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([key]) => {
      const [r, g, b] = key.split(',').map(Number);
      return `rgb(${r} ${g} ${b})`;
    });

  return [
    colors[0] || '#1b1b1b',
    colors[1] || colors[0] || '#101010',
    colors[2] || colors[1] || '#272727',
  ];
}

function numberOrZero(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

function numberOrDefault(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

init();
