import { onDomReady } from './dom-ready.js';
import { fetchFilmSummary, getFilmsDataSource } from './films-library-api.js';

const $ = (id) => document.getElementById(id);

const CATEGORY_LABELS = Object.freeze({
  awards: 'Nagrody',
  festival: 'Festiwal',
  personal: 'Osobista',
  custom: 'Lista',
});

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function listHref(slug) {
  if (!slug) return './films.html';
  return `./films.html?list=${encodeURIComponent(slug)}`;
}

function categoryLabel(value) {
  return CATEGORY_LABELS[String(value || '').toLowerCase()] || 'Lista';
}

function formatNow() {
  try {
    return new Date().toLocaleString('pl-PL', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return new Date().toISOString().slice(0, 16).replace('T', ' ');
  }
}

function renderCollections(summary) {
  const wrap = $('films-collections');
  if (!wrap) return;
  wrap.innerHTML = '';
  const dataSource = getFilmsDataSource();

  const chips = [
    { title: 'Wspólna biblioteka', kind: 'live' },
    { title: `${summary.total_lists || 0} list`, kind: summary.total_lists ? 'live' : 'planned' },
    {
      title: dataSource === 'api' ? 'Live API' : 'Snapshot offline',
      kind: dataSource === 'api' ? 'live' : 'planned',
    },
  ];

  chips.forEach((item) => {
    const chip = document.createElement('span');
    chip.className = `films-chip films-chip--${item.kind}`;
    chip.textContent = item.title;
    wrap.appendChild(chip);
  });
}

function linkMeta(item) {
  const parts = [];
  if (item.category) parts.push(categoryLabel(item.category));
  if (item.source_year) parts.push(String(item.source_year));
  if (Number(item.winners_count || 0) > 0) parts.push(`${item.winners_count} wins`);
  return parts.join(' / ') || 'Lista filmowa';
}

function linkDetail(item) {
  const count = Number(item.item_count || 0);
  const watched = Number(item.watched_count || 0);
  return `${count} filmów / ${watched} obejrzane`;
}

function renderLinks(summary) {
  const wrap = $('films-links');
  if (!wrap) return;
  wrap.innerHTML = '';

  const quickLinks = [
    {
      title: 'Cala biblioteka',
      href: './films.html',
      meta: `${summary.total_films || 0} filmów`,
      detail: `${summary.watched || 0} obejrzane / ${summary.rated || 0} ocenione`,
    },
    ...((summary.lists || []).slice(0, 3).map((item) => ({
      title: item.name || '-',
      href: listHref(item.slug),
      meta: linkMeta(item),
      detail: linkDetail(item),
    }))),
  ];

  quickLinks.forEach((item) => {
    const link = document.createElement('a');
    link.className = 'films-link';
    link.href = item.href;

    const head = document.createElement('div');
    head.className = 'films-link-head';

    const title = document.createElement('strong');
    title.textContent = item.title;

    const meta = document.createElement('span');
    meta.className = 'films-link-meta';
    meta.textContent = item.meta;

    const detail = document.createElement('span');
    detail.className = 'films-link-detail';
    detail.textContent = item.detail;

    head.append(title, meta);
    link.append(head, detail);
    wrap.appendChild(link);
  });

  setText(
    'films-links-meta',
    quickLinks.length > 1 ? 'Cały katalog i najważniejsze listy' : 'Główny katalog filmów'
  );
}

function render(summary) {
  const featured = summary.featured || {};
  const spotlightHref = featured.slug ? listHref(featured.slug) : featured.href || './films.html';
  const spotlightLink = $('films-spotlight-link');
  const dataSource = getFilmsDataSource();

  setText('films-title', 'Biblioteka filmów');
  setText('films-subtitle', 'Jedna biblioteka, wiele list');
  setText('films-total', String(summary.total_films || 0));
  setText('films-watched', String(summary.watched || 0));
  setText('films-lists', String(summary.total_lists || 0));
  setText('films-avg', summary.avg_rating === null || summary.avg_rating === undefined ? '-' : Number(summary.avg_rating).toFixed(1));
  setText('films-spotlight-label', featured.slug ? 'Na pierwszym planie' : 'Wspólna biblioteka');
  setText(
    'films-spotlight-title',
    featured.title || 'Jedna biblioteka filmów dla Oscarów, Cannes i Twoich prywatnych list'
  );
  setText(
    'films-spotlight-copy',
    featured.copy || 'Dodawaj tytuły raz i przypinaj je do kolejnych list bez duplikowania danych.'
  );
  setText(
    'films-spotlight-meta',
    featured.meta || `${summary.total_films || 0} filmów / ${summary.total_lists || 0} list`
  );

  if (spotlightLink) {
    spotlightLink.href = spotlightHref;
    spotlightLink.textContent = featured.slug ? 'Otwórz listę' : 'Otwórz bibliotekę';
  }

  renderCollections(summary);
  renderLinks(summary);
  setText(
    'films-foot',
    `Biblioteka filmów / ${dataSource === 'api' ? 'lokalne API' : 'snapshot'} / ${formatNow()}`
  );
}

async function refresh() {
  const summary = await fetchFilmSummary();
  render(summary || {});
}

onDomReady(() => {
  if (!$('films-card')) return;

  refresh().catch((error) => {
    console.error(error);
    setText('films-foot', 'Filmy: nie udało się załadować biblioteki.');
    setText('films-spotlight-title', 'Biblioteka filmów');
    setText(
      'films-spotlight-copy',
      'Widok biblioteki jest gotowy, ale lokalne API nie odpowiedziało.'
    );
    setText('films-spotlight-meta', 'Uruchom lokalny serwer aplikacji.');
  });
});
