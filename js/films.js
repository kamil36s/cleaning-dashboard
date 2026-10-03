import {
  addFilmToLibrary,
  createFilmList,
  fetchFilmLibrary,
  fetchFilmLists,
  fetchFilmSummary,
  getFilmsDataSource,
  searchFilms,
  updateFilmLibrary,
} from './films-library-api.js';

const $ = (id) => document.getElementById(id);

const CATEGORY_LABELS = Object.freeze({
  awards: 'Nagrody',
  festival: 'Festiwal',
  personal: 'Osobista',
  custom: 'Lista',
});
const FILMS_PAGE_SIZE = 60;

const state = {
  summary: null,
  lists: [],
  selectedList: readInitialList(),
  selectedListData: null,
  libraryItems: [],
  searchResults: [],
  libraryQuery: '',
  libraryPagination: { total: 0, hasMore: false },
  libraryLoadingMore: false,
};

function readInitialList() {
  try {
    const params = new URLSearchParams(window.location.search);
    return params.get('list') || 'all';
  } catch {
    return 'all';
  }
}

function syncLocation() {
  try {
    const url = new URL(window.location.href);
    if (state.selectedList === 'all') {
      url.searchParams.delete('list');
    } else {
      url.searchParams.set('list', state.selectedList);
    }
    window.history.replaceState({}, '', url);
  } catch {}
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setHtml(id, value) {
  const el = $(id);
  if (el) el.innerHTML = value;
}

function setStatus(id, value) {
  setText(id, value || '');
}

function categoryLabel(value) {
  return CATEGORY_LABELS[String(value || '').toLowerCase()] || 'Lista';
}

function isReadonlyMode() {
  return getFilmsDataSource() === 'static';
}

function buildListHref(slug) {
  if (!slug) return './films.html';
  return `./films.html?list=${encodeURIComponent(slug)}`;
}

function getSelectedList() {
  if (state.selectedList === 'all') return null;
  return state.lists.find((item) => item.slug === state.selectedList) || null;
}

function currentTargetLabel() {
  const selected = getSelectedList();
  if (!selected) return 'Dodawanie do całej biblioteki';
  return `Dodawanie do listy: ${selected.name}`;
}

function listMetaLine(item) {
  const parts = [];
  if (item.category) parts.push(categoryLabel(item.category));
  if (item.source_year) parts.push(String(item.source_year));
  if (Number(item.item_count || 0) > 0) parts.push(`${item.item_count} filmów`);
  if (Number(item.watched_count || 0) > 0) parts.push(`${item.watched_count} obejrzane`);
  return parts.join(' / ') || 'Lista filmowa';
}

function listInfoLine(item) {
  if (item.description) return item.description;
  if (Number(item.winners_count || 0) > 0) {
    return `${item.winners_count} zwycieskich tytułow zapisanych w tej liscie`;
  }
  if (Number(item.rated_count || 0) > 0) {
    return `${item.rated_count} filmów ma już ocenę w bibliotece`;
  }
  return 'Lista korzysta z tych samych filmów co reszta biblioteki.';
}

function filmMetaLine(item) {
  const parts = [];
  if (item.release_year) parts.push(String(item.release_year));
  if (item.director) parts.push(item.director);
  if (item.runtime) parts.push(item.runtime);
  if (item.country) parts.push(item.country);
  return parts.join(' / ') || 'Brak dodatkowych danych';
}

function renderSourceBadge() {
  const el = $('films-source');
  if (!el) return;
  el.classList.remove('is-api', 'is-static');
  if (!isReadonlyMode()) {
    el.classList.add('is-api');
    el.textContent = 'Data: lokalne API biblioteki + Wikipedia search';
    return;
  }
  el.classList.add('is-static');
  el.textContent = 'Data: snapshot biblioteki (read only)';
}

function applyReadonlyState() {
  const disabled = isReadonlyMode();
  const formSelectors = [
    '#films-list-form input',
    '#films-list-form select',
    '#films-list-form button',
    '#films-search-form input',
    '#films-search-form button',
    '#films-manual-form input',
    '#films-manual-form button',
  ];

  formSelectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((element) => {
      element.disabled = disabled;
    });
  });

  if (disabled) {
    setStatus('films-search-status', 'Tryb tylko do odczytu. Uruchom lokalny serwer, aby szukać i dodawać filmy.');
    setStatus('films-list-status', 'Tryb tylko do odczytu. Tworzenie list wymaga lokalnego API.');
    setStatus('films-manual-status', 'Tryb tylko do odczytu. Dodawanie filmów wymaga lokalnego API.');
    return;
  }

  setStatus('films-search-status', '');
  setStatus('films-list-status', '');
  setStatus('films-manual-status', '');
}

function renderSidebarSummary() {
  const summary = state.summary || {};
  setText('films-kpi-total', String(summary.total_films || 0));
  setText('films-kpi-watched', String(summary.watched || 0));
  setText('films-kpi-rated', String(summary.rated || 0));
  setText('films-kpi-lists', String(summary.total_lists || 0));
}

function renderSidebarLists() {
  const wrap = $('films-sidebar-lists');
  if (!wrap) return;
  wrap.innerHTML = '';

  $('films-show-all')?.classList.toggle('is-active', state.selectedList === 'all');

  if (!state.lists.length) {
    wrap.innerHTML = '<div class="films-empty-state films-empty-state--compact">Nie ma jeszcze żadnych list.</div>';
    return;
  }

  state.lists.forEach((item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `films-sidebar-link${state.selectedList === item.slug ? ' is-active' : ''}`;
    button.dataset.slug = item.slug;

    const title = document.createElement('strong');
    title.textContent = item.name || '-';

    const meta = document.createElement('span');
    meta.textContent = listMetaLine(item);

    const info = document.createElement('span');
    info.className = 'films-sidebar-link-info';
    info.textContent = listInfoLine(item);

    button.append(title, meta, info);
    wrap.appendChild(button);
  });
}

function bannerCopyForList(item) {
  if (!item) {
    return 'Każdy film dodajesz raz. Potem przypinasz go do Oscarów, Cannes albo do swoich prywatnych list.';
  }
  if (item.description) return item.description;
  if (item.category === 'awards') {
    return 'Lista nagrod korzysta z tej samej biblioteki, co Twoje prywatne rankingi i przyszłe festiwale.';
  }
  if (item.category === 'festival') {
    return 'To miejsce na festiwalowa selekcje, ale wszystkie notatki i oceny zostaja w jednej bibliotece.';
  }
  if (item.category === 'personal') {
    return 'To Twoja osobista lista, zasilana tym samym katalogiem filmów co reszta aplikacji.';
  }
  return 'Ta lista korzysta z tej samej biblioteki filmów co wszystkie pozostałe widoki.';
}

function renderBanner() {
  const selected = getSelectedList();
  const count = Number.isFinite(state.libraryPagination.total)
    ? state.libraryPagination.total
    : state.libraryItems.length;
  const title = selected ? selected.name : 'Wspólna biblioteka filmów';
  const metaParts = [];

  if (selected) {
    metaParts.push(categoryLabel(selected.category));
    if (selected.source_year) metaParts.push(String(selected.source_year));
    metaParts.push(`${count} filmów w widoku`);
  } else {
    metaParts.push(`${count} filmów w całej bibliotece`);
    metaParts.push(`${state.lists.length} list opartych na tej samej bazie`);
  }

  setText('films-banner-title', title);
  setText('films-banner-copy', bannerCopyForList(selected));
  setText('films-main-meta', metaParts.join(' / '));
}

function renderMemberships(item) {
  const wrap = document.createElement('div');
  wrap.className = 'films-card-tags';
  const lists = Array.isArray(item.lists) ? item.lists : [];

  lists.slice(0, 5).forEach((entry) => {
    const tag = document.createElement('span');
    tag.className = 'films-card-tag';
    tag.textContent = entry.name || entry.slug || '-';
    wrap.appendChild(tag);
  });

  return wrap;
}

function renderSelectedListMeta(item) {
  const selected = getSelectedList();
  if (!selected) return null;

  const parts = [];
  if (item.selected_nominations_number) {
    parts.push(`${item.selected_nominations_number} nominacji`);
  }
  if (item.selected_nominated_categories) {
    parts.push(item.selected_nominated_categories);
  }
  if (item.selected_won_categories) {
    parts.push(`Wygrane: ${item.selected_won_categories}`);
  }
  if (item.selected_where_to_watch) {
    parts.push(`Gdzie obejrzec: ${item.selected_where_to_watch}`);
  }

  if (!parts.length) return null;

  const box = document.createElement('div');
  box.className = 'films-card-listmeta';
  box.textContent = parts.join(' / ');
  return box;
}

function createPoster(item) {
  const poster = document.createElement('div');
  poster.className = 'films-card-poster';

  if (item.poster_url) {
    const img = document.createElement('img');
    img.src = item.poster_url;
    img.alt = item.title ? `${item.title} poster` : 'Poster';
    img.loading = 'lazy';
    img.referrerPolicy = 'no-referrer';
    poster.appendChild(img);
    return poster;
  }

  poster.classList.add('is-empty');
  poster.textContent = String(item.title || '?').trim().charAt(0).toUpperCase() || '?';
  return poster;
}

function createFilmCard(item) {
  const readonly = isReadonlyMode();
  const article = document.createElement('article');
  article.className = 'films-library-card';
  article.dataset.id = String(item.id);

  const poster = createPoster(item);

  const body = document.createElement('div');
  body.className = 'films-library-card-body';

  const title = document.createElement('h3');
  title.textContent = item.title || '-';

  const meta = document.createElement('div');
  meta.className = 'films-library-card-meta';
  meta.textContent = filmMetaLine(item);

  const tags = renderMemberships(item);
  const selectedMeta = renderSelectedListMeta(item);

  const controls = document.createElement('div');
  controls.className = 'films-library-card-controls';

  const watchedLabel = document.createElement('label');
  watchedLabel.className = 'films-watch-toggle';
  const watchedInput = document.createElement('input');
  watchedInput.type = 'checkbox';
  watchedInput.checked = Number(item.watched || 0) === 1;
  watchedInput.dataset.role = 'watched';
  watchedInput.disabled = readonly;
  watchedLabel.append(watchedInput, document.createTextNode(' obejrzany'));

  const rating = document.createElement('input');
  rating.type = 'number';
  rating.min = '0';
  rating.max = '10';
  rating.step = '0.1';
  rating.className = 'oscars-input films-rating-input';
  rating.dataset.role = 'rating';
  rating.value = item.rating_1_10 ?? '';
  rating.placeholder = 'Ocena';
  rating.disabled = readonly;

  const save = document.createElement('button');
  save.type = 'button';
  save.className = 'card-cta films-card-save';
  save.dataset.role = 'save';
  save.textContent = 'Zapisz';
  save.disabled = readonly;

  controls.append(watchedLabel, rating, save);

  const notes = document.createElement('textarea');
  notes.className = 'oscars-input films-notes-input';
  notes.rows = 3;
  notes.dataset.role = 'notes';
  notes.placeholder = 'Notatki do filmu...';
  notes.value = item.notes || '';
  notes.disabled = readonly;

  const actions = document.createElement('div');
  actions.className = 'films-library-card-actions';
  const selected = getSelectedList();
  const inSelectedList =
    !selected ||
    (Array.isArray(item.lists) && item.lists.some((entry) => entry.slug === selected.slug));

  if (selected && !inSelectedList) {
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'oscars-ghost films-card-addlist';
    addBtn.dataset.role = 'add-to-list';
    addBtn.textContent = `Dodaj do ${selected.name}`;
    addBtn.disabled = readonly;
    actions.appendChild(addBtn);
  }

  body.append(title, meta, tags);
  if (selectedMeta) body.appendChild(selectedMeta);
  body.append(controls, notes, actions);
  article.append(poster, body);
  return article;
}

function renderLibrary() {
  const grid = $('films-library-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const selected = getSelectedList();
  setText('films-library-title', selected ? selected.name : 'Cały katalog');
  setText(
    'films-library-subtitle',
    selected ? listMetaLine(selected) : 'Wszystkie wpisy z jednej biblioteki'
  );

  renderBanner();
  renderLibraryPagination();

  if (!state.libraryItems.length) {
    grid.innerHTML = '<div class="films-empty-state">Brak filmów w tym widoku. Dodaj pierwszy tytuł z wyszukiwarki albo ręcznie.</div>';
    return;
  }

  state.libraryItems.forEach((item) => {
    grid.appendChild(createFilmCard(item));
  });
}

function renderLibraryPagination() {
  const button = $('films-library-more');
  if (!button) return;
  const total = Number(state.libraryPagination.total || state.libraryItems.length);
  button.hidden = !state.libraryPagination.hasMore;
  button.disabled = state.libraryLoadingMore;
  button.textContent = state.libraryLoadingMore
    ? 'Ładowanie...'
    : `Pokaż kolejne (${state.libraryItems.length} z ${total})`;
}

function renderSearchResults() {
  const wrap = $('films-search-results');
  if (!wrap) return;
  wrap.innerHTML = '';
  const readonly = isReadonlyMode();

  if (!state.searchResults.length) {
    wrap.innerHTML = '<div class="films-empty-state films-empty-state--compact">Tu pojawią się wyniki wyszukiwania z darmowego API Wikipedii.</div>';
    return;
  }

  state.searchResults.forEach((item, index) => {
    const card = document.createElement('article');
    card.className = 'films-search-card';

    const poster = document.createElement('div');
    poster.className = 'films-search-card-poster';
    if (item.poster_url) {
      const img = document.createElement('img');
      img.src = item.poster_url;
      img.alt = item.title ? `${item.title} poster` : 'Poster';
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      poster.appendChild(img);
    } else {
      poster.classList.add('is-empty');
      poster.textContent = String(item.title || '?').trim().charAt(0).toUpperCase() || '?';
    }

    const body = document.createElement('div');
    body.className = 'films-search-card-body';

    const title = document.createElement('strong');
    title.textContent = item.title || '-';

    const meta = document.createElement('span');
    meta.className = 'films-search-card-meta';
    meta.textContent = item.release_year ? String(item.release_year) : 'Wikipedia API';

    const copy = document.createElement('p');
    copy.textContent = item.description || 'Brak opisu.';

    const actions = document.createElement('div');
    actions.className = 'films-search-card-actions';

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'card-cta';
    addBtn.dataset.index = String(index);
    addBtn.dataset.role = 'add-search-result';
    addBtn.textContent = getSelectedList() ? 'Dodaj do biblioteki i listy' : 'Dodaj do biblioteki';
    addBtn.disabled = readonly;
    actions.appendChild(addBtn);

    if (item.wikipedia_url) {
      const link = document.createElement('a');
      link.className = 'oscars-ghost';
      link.href = item.wikipedia_url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = 'Wikipedia';
      actions.appendChild(link);
    }

    body.append(title, meta, copy, actions);
    card.append(poster, body);
    wrap.appendChild(card);
  });
}

async function loadLibrary({ append = false } = {}) {
  const offset = append ? state.libraryItems.length : 0;
  const data = await fetchFilmLibrary({
    list: state.selectedList === 'all' ? null : state.selectedList,
    q: state.libraryQuery,
    limit: FILMS_PAGE_SIZE,
    offset,
  });
  state.selectedListData = data?.selected_list || null;
  const nextItems = Array.isArray(data?.items) ? data.items : [];
  state.libraryItems = append ? [...state.libraryItems, ...nextItems] : nextItems;
  state.libraryPagination = {
    total: Number(data?.pagination?.total ?? state.libraryItems.length),
    hasMore: Boolean(data?.pagination?.has_more),
  };
  renderLibrary();
}

async function loadSidebar() {
  const [summary, lists] = await Promise.all([fetchFilmSummary(), fetchFilmLists()]);
  state.summary = summary;
  state.lists = lists;

  if (
    state.selectedList !== 'all' &&
    !state.lists.some((item) => item.slug === state.selectedList)
  ) {
    state.selectedList = 'all';
  }

  syncLocation();
  renderSourceBadge();
  renderSidebarSummary();
  renderSidebarLists();
  setText('films-search-target', currentTargetLabel());
}

async function refreshPage() {
  setText('films-foot', 'Ładowanie biblioteki...');
  await loadSidebar();
  await loadLibrary();
  applyReadonlyState();
  setText(
    'films-foot',
    isReadonlyMode()
      ? 'Tryb tylko do odczytu. Uruchom lokalny serwer, aby zapisywa? zmiany.'
      : `Ostatnia aktualizacja: ${new Date().toLocaleString('pl-PL')}`
  );
}

async function handleSearchSubmit(event) {
  event.preventDefault();
  const input = $('films-search-input');
  const query = String(input?.value || '').trim();
  if (!query) {
    setStatus('films-search-status', 'Podaj tytuł do wyszukania.');
    return;
  }

  setStatus('films-search-status', 'Szukam przez Wikipedia API...');
  try {
    state.searchResults = await searchFilms(query, 8);
    renderSearchResults();
    setStatus('films-search-status', `${state.searchResults.length} wyników.`);
  } catch (error) {
    console.error(error);
    setStatus('films-search-status', 'Wyszukiwanie nie powiodło się.');
  }
}

async function handleAddSearchResult(index) {
  const item = state.searchResults[index];
  if (!item) return;

  try {
    await addFilmToLibrary({
      ...item,
      list_slug: state.selectedList === 'all' ? null : state.selectedList,
    });
    setStatus('films-search-status', `Dodano: ${item.title}`);
    await refreshPage();
  } catch (error) {
    console.error(error);
    setStatus('films-search-status', 'Dodawanie filmu nie powiodło się.');
  }
}

async function handleManualAdd(event) {
  event.preventDefault();
  const title = String($('films-manual-title')?.value || '').trim();
  const year = String($('films-manual-year')?.value || '').trim();
  const director = String($('films-manual-director')?.value || '').trim();

  if (!title) {
    setStatus('films-manual-status', 'Tytuł jest wymagany.');
    return;
  }

  try {
    await addFilmToLibrary({
      title,
      release_year: year,
      director,
      list_slug: state.selectedList === 'all' ? null : state.selectedList,
      source: 'manual',
    });
    event.target.reset();
    setStatus('films-manual-status', `Dodano: ${title}`);
    await refreshPage();
  } catch (error) {
    console.error(error);
    setStatus('films-manual-status', 'Ręczne dodawanie nie powiodło się.');
  }
}

async function handleCreateList(event) {
  event.preventDefault();
  const name = String($('films-list-name')?.value || '').trim();
  const category = String($('films-list-category')?.value || 'custom');
  const description = String($('films-list-description')?.value || '').trim();

  if (!name) {
    setStatus('films-list-status', 'Nazwa listy jest wymagana.');
    return;
  }

  try {
    const created = await createFilmList({ name, category, description });
    event.target.reset();
    setStatus('films-list-status', `Utworzono listę: ${created?.name || name}`);
    if (created?.slug) state.selectedList = created.slug;
    await refreshPage();
  } catch (error) {
    console.error(error);
    setStatus('films-list-status', 'Nie udało się utworzyć listy.');
  }
}

async function handleLibraryAction(target) {
  const card = target.closest('.films-library-card');
  if (!card) return;
  const filmId = Number(card.dataset.id || 0);
  if (!filmId) return;

  if (target.dataset.role === 'save') {
    const watched = card.querySelector('[data-role="watched"]');
    const rating = card.querySelector('[data-role="rating"]');
    const notes = card.querySelector('[data-role="notes"]');

    try {
      await updateFilmLibrary(filmId, {
        watched: watched?.checked,
        rating_1_10: rating?.value,
        notes: notes?.value,
      });
      setText(
        'films-foot',
        `Zapisano zmiany / ${new Date().toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}`
      );
      await loadSidebar();
      await loadLibrary();
    } catch (error) {
      console.error(error);
      setText('films-foot', 'Nie udało się zapisać filmu.');
    }
    return;
  }

  if (target.dataset.role === 'add-to-list') {
    try {
      await addFilmToLibrary({
        film_id: filmId,
        list_slug: state.selectedList === 'all' ? null : state.selectedList,
      });
      setText('films-foot', 'Film dodany do aktywnej listy.');
      await loadSidebar();
      await loadLibrary();
    } catch (error) {
      console.error(error);
      setText('films-foot', 'Nie udało się dodać filmu do listy.');
    }
  }
}

function bindEvents() {
  $('films-refresh-btn')?.addEventListener('click', () => {
    refreshPage().catch((error) => {
      console.error(error);
      setText('films-foot', 'Odświeżanie nie powiodło się.');
    });
  });

  $('films-show-all')?.addEventListener('click', () => {
    state.selectedList = 'all';
    syncLocation();
    refreshPage().catch((error) => {
      console.error(error);
      setText('films-foot', 'Nie udało się załadować biblioteki.');
    });
  });

  $('films-list-form')?.addEventListener('submit', handleCreateList);
  $('films-search-form')?.addEventListener('submit', handleSearchSubmit);
  $('films-manual-form')?.addEventListener('submit', handleManualAdd);

  $('films-sidebar-lists')?.addEventListener('click', (event) => {
    const btn = event.target.closest('.films-sidebar-link');
    if (!btn) return;
    const slug = btn.dataset.slug;
    if (!slug) return;
    state.selectedList = slug;
    syncLocation();
    refreshPage().catch((error) => {
      console.error(error);
      setText('films-foot', 'Nie udało się przełączyć listy.');
    });
  });

  $('films-search-results')?.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-role="add-search-result"]');
    if (!btn) return;
    handleAddSearchResult(Number(btn.dataset.index || -1));
  });

  $('films-library-grid')?.addEventListener('click', (event) => {
    const action = event.target.closest('[data-role="save"], [data-role="add-to-list"]');
    if (!action) return;
    handleLibraryAction(action);
  });

  $('films-library-more')?.addEventListener('click', async () => {
    if (state.libraryLoadingMore || !state.libraryPagination.hasMore) return;
    state.libraryLoadingMore = true;
    renderLibraryPagination();
    try {
      await loadLibrary({ append: true });
    } catch (error) {
      console.error(error);
      setText('films-foot', 'Nie udało się załadować kolejnych filmów.');
    } finally {
      state.libraryLoadingMore = false;
      renderLibraryPagination();
    }
  });

  $('films-library-query')?.addEventListener('input', (event) => {
    state.libraryQuery = String(event.target.value || '').trim();
    window.clearTimeout(window.__filmsLibraryQueryTimer);
    window.__filmsLibraryQueryTimer = window.setTimeout(() => {
      loadLibrary().catch((error) => {
        console.error(error);
        setText('films-foot', 'Filtrowanie biblioteki nie powiodło się.');
      });
    }, 180);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  if (!$('films-page')) return;

  bindEvents();
  renderSearchResults();
  refreshPage().catch((error) => {
    console.error(error);
    setText('films-foot', 'Nie udało się załadować biblioteki filmów.');
  });
});
