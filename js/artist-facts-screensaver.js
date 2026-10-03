const STATUS_URL = '/api/screensaver-status';
const ARTIST_FACTS_URL = '/api/artist-facts';
const CONFIG_URL = '/api/screensaver-config';
const REFRESH_MS = 5000;

const body = document.body;
const backLink = document.getElementById('back-link');
const fullscreenButton = document.getElementById('fullscreen-button');
const message = document.getElementById('message');
const messageTitle = document.getElementById('message-title');
const messageCopy = document.getElementById('message-copy');
const slide = document.getElementById('slide');
const slideImage = document.getElementById('slide-image');
const slideArtist = document.getElementById('slide-artist');
const slideTitle = document.getElementById('slide-title');
const slideCaption = document.getElementById('slide-caption');
const slideCredit = document.getElementById('slide-credit');

let currentArtist = '';
let payload = null;
let fetchedAt = Date.now();
let slideSeconds = 14;

fullscreenButton?.addEventListener('click', enterFullscreen);
document.addEventListener('fullscreenchange', () => {
  body.classList.toggle('is-fullscreen', Boolean(document.fullscreenElement));
});

async function enterFullscreen() {
  try {
    if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
      await document.documentElement.requestFullscreen();
    }
  } catch (error) {
    console.warn('Could not enter fullscreen:', error);
  }
}

async function init() {
  const config = await fetchConfig();
  slideSeconds = numberOrDefault(config.artistFactSlideSeconds, 14);
  await refresh();
  setInterval(refresh, REFRESH_MS);
  requestAnimationFrame(tick);
}

async function fetchConfig() {
  try {
    const response = await fetch(CONFIG_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    return await response.json();
  } catch {
    return {};
  }
}

async function refresh() {
  const artist = await readCurrentArtist();
  if (!artist) {
    showMessage('No artist', 'Start Spotify playback or pass ?artist=Maurice%20Ravel in the URL.');
    return;
  }
  if (artist === currentArtist && payload) return;

  currentArtist = artist;
  payload = null;
  fetchedAt = Date.now();

  try {
    const response = await fetch(`${ARTIST_FACTS_URL}?artist=${encodeURIComponent(artist)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    payload = await response.json();
    renderSlide();
  } catch (error) {
    showMessage('Artist facts unavailable', String(error?.message || error));
  }
}

async function readCurrentArtist() {
  const queryArtist = new URLSearchParams(window.location.search).get('artist');
  if (queryArtist) return queryArtist.trim();
  try {
    const response = await fetch(STATUS_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    const status = await response.json();
    return String(status?.artist || '').split(',')[0].trim();
  } catch {
    return '';
  }
}

function tick() {
  renderSlide();
  requestAnimationFrame(tick);
}

function renderSlide() {
  const media = Array.isArray(payload?.media) ? payload.media.filter((item) => item?.url || item?.localUrl) : [];
  const facts = Array.isArray(payload?.facts) ? payload.facts.filter((item) => item?.text) : [];
  if (!facts.length) {
    showMessage(payload?.artist || currentArtist || 'No facts', 'No local JSON facts found for this artist.');
    return;
  }

  const slideMs = Math.max(4000, slideSeconds * 1000);
  const index = Math.floor((Date.now() - fetchedAt) / slideMs) % facts.length;
  const fact = facts[index] || facts[0];
  const item = media.length ? media[index % media.length] : null;
  const imageUrl = item?.localUrl || item?.url || '';

  message.hidden = true;
  slide.hidden = false;

  if (imageUrl) {
    slideImage.hidden = false;
    if (slideImage.src !== imageUrl) slideImage.src = imageUrl;
    slideImage.alt = item.caption || payload?.artist || '';
  } else {
    slideImage.hidden = true;
    slideImage.removeAttribute('src');
  }

  slideArtist.textContent = payload?.artist || currentArtist || 'Artist';
  slideTitle.textContent = fact.title || 'Ciekawostka';
  slideCaption.textContent = fact.text || '';
  slideCredit.textContent = [
    item?.caption,
    item?.license,
    item?.credit,
  ].filter(Boolean).join(' / ');
}

function showMessage(title, copy) {
  slide.hidden = true;
  message.hidden = false;
  messageTitle.textContent = title;
  messageCopy.textContent = copy;
}

function numberOrDefault(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

init();
