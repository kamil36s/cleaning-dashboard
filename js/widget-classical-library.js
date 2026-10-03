import { onDomReady } from './dom-ready.js';
import { fetchClassicalSummary, getClassicalDataSource } from './classical-library-api.js';

const $ = (id) => document.getElementById(id);
const BASE_URL = String(
  import.meta.env?.BASE_URL ||
  (window.location.pathname.startsWith('/cleaning-dashboard/') ? '/cleaning-dashboard/' : '/')
);

function assetUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^(https?:|data:|blob:)/i.test(raw)) return raw;
  if (raw.startsWith('/assets/')) {
    return `${BASE_URL.replace(/\/?$/, '/')}${raw.slice(1)}`;
  }
  return raw;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function imageFor(composer) {
  return assetUrl(composer?.image?.localFile || '');
}

function render(summary = {}) {
  const composer = summary.featuredComposer || {};
  const image = imageFor(composer);

  setText('classical-widget-composer', composer.name || 'Maurice Ravel');
  setText('classical-widget-bio', composer.bioShort || 'French composer associated with luminous orchestration, piano color, and exacting craft.');
  setText(
    'classical-widget-latest',
    `${summary.composerCount || 0} composers in library`
  );
  setText(
    'classical-widget-progress',
    `${summary.listenedWorks || 0} works listened / ${summary.totalWorks || 0} total`
  );
  setText('classical-widget-foot', `Classical library / ${getClassicalDataSource() === 'api' ? 'local JSON API' : 'seed snapshot'}`);

  const img = $('classical-widget-image');
  const fallback = $('classical-widget-image-fallback');
  if (img && fallback) {
    if (image) {
      img.src = image;
      img.hidden = false;
      fallback.hidden = true;
    } else {
      img.hidden = true;
      fallback.hidden = false;
      fallback.textContent = (composer.name || 'M').slice(0, 1);
    }
  }
}

onDomReady(() => {
  if (!$('classical-library-card')) return;
  fetchClassicalSummary()
    .then(render)
    .catch((error) => {
      console.error(error);
      render({});
      setText('classical-widget-foot', 'Classical library unavailable.');
    });
});
