import { formatDateLong, toISODate } from "./events-date.js";
import { isEventWithinCinemaCityMembership } from "./cinema-city.js";
import {
  deleteEventCountdownCover,
  fetchDashboardEvents,
  saveEventDashboardOverride,
  saveEventCountdownCategory,
  saveLocalDashboardEvent,
  syncGoogleCalendarNow,
  upsertGoogleCalendarEvent,
  uploadEventCountdownCover,
} from "./events-api.js";
import {
  EVENT_COUNTDOWN_CATEGORIES,
  EVENT_COUNTDOWN_CATEGORY_LABELS,
  compareEventsChronologically,
  enrichEvents,
  getVisibleEvents,
  normalizeEvents,
} from "./events-sources.js";
import {
  DASHBOARD_NOTIFICATIONS_CHANGED_EVENT,
  DASHBOARD_NOTIFICATIONS_STORAGE_KEY,
  listDashboardNotifications,
  markDashboardNotificationRead,
} from "./dashboard-notifications-store.js";

const SELECTED_KEY = "eventsCountdown.selectedIds.v1";
const HIDDEN_KEY = "eventsCountdown.hiddenIds.v1";
const CATEGORY_FILTER_KEY = "eventsCountdown.categoryFilter.v1";
const RANGE_FILTER_KEY = "eventsCountdown.rangeDays.v1";
const TODAY_NOTICE_KEY = "eventsCountdown.todayNoticeSeen.v1";
const TODAY_READ_KEY = "eventsCountdown.todayReadIds.v1";
const REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const EVENTS_WINDOW_DAYS = 400;
const DASHBOARD_BASE_PATH = "/cleaning-dashboard/";

const card = document.getElementById("event-countdowns-widget");
const list = document.getElementById("event-countdowns-list");
const select = document.getElementById("event-countdowns-select");
const categorySelect = document.getElementById("event-countdowns-category");
const categoryFilter = document.getElementById("event-countdowns-filter");
const categoryFilterMenu = document.getElementById("event-countdowns-filter-menu");
const addButton = document.getElementById("event-countdowns-add");
const createButton = document.getElementById("event-countdowns-create");
const createCategoryButton = document.getElementById("event-countdowns-create-category");
const refreshButton = document.getElementById("event-countdowns-refresh");
const foot = document.getElementById("event-countdowns-foot");

const DEFAULT_CATEGORY_DEFINITIONS = EVENT_COUNTDOWN_CATEGORIES.map((id) => ({
  id,
  label: EVENT_COUNTDOWN_CATEGORY_LABELS[id] || id,
  custom: false,
}));

let state = {
  events: [],
  allEvents: [],
  selectedIds: loadIdSet(SELECTED_KEY),
  hiddenIds: loadIdSet(HIDDEN_KEY),
  hiddenCategoryIds: loadHiddenCategoryIds(),
  rangeDays: loadRangeDays(),
  categoryCovers: {},
  categories: DEFAULT_CATEGORY_DEFINITIONS,
  loading: false,
  error: "",
  uploadingId: "",
  deletingCoverId: "",
  promptCopiedId: "",
  statusMessage: "",
  saving: false,
  categorySavingId: "",
};

let tickTimer = 0;
let refreshTimer = 0;
let loadInFlight = false;
let uploadInput = null;
let pendingUploadEventId = "";

if (card && list && select) {
  initCountdownsWidget();
}

async function initCountdownsWidget() {
  addButton?.addEventListener("click", () => addSelectedCountdown());
  select.addEventListener("change", () => syncAddControls({ syncCategory: true }));
  categorySelect?.addEventListener("change", syncAddControls);
  categoryFilter?.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = Boolean(categoryFilterMenu?.hidden);
    if (categoryFilterMenu) categoryFilterMenu.hidden = !open;
    categoryFilter.setAttribute("aria-expanded", String(open));
  });
  categoryFilterMenu?.addEventListener("click", (event) => event.stopPropagation());
  categoryFilterMenu?.addEventListener("change", handleFilterChange);
  document.addEventListener("click", closeCategoryFilterMenu);
  createButton?.addEventListener("click", openCreateEventDialog);
  createCategoryButton?.addEventListener("click", (event) => {
    if (event.shiftKey) openEditCategoryDialog();
    else openCreateCategoryDialog();
  });
  refreshButton?.addEventListener("click", () => loadEvents({ silent: true, forceRefresh: true }));
  populateCategoryControls();
  setupNotificationShell();
  window.addEventListener(DASHBOARD_NOTIFICATIONS_CHANGED_EVENT, renderEventNotifications);
  window.addEventListener("storage", (event) => {
    if (event.key === DASHBOARD_NOTIFICATIONS_STORAGE_KEY) renderEventNotifications();
  });
  uploadInput = createUploadInput();
  list.addEventListener("click", (event) => {
    const categoryTrigger = event.target.closest("[data-countdown-category-edit]");
    if (categoryTrigger) {
      openEventCategoryDialog(categoryTrigger.dataset.countdownCategoryEdit);
      return;
    }

    const removeButton = event.target.closest("[data-countdown-remove]");
    if (removeButton) {
      removeCountdown(removeButton.dataset.countdownRemove);
      return;
    }

    const uploadButton = event.target.closest("[data-countdown-upload]");
    if (uploadButton) {
      pendingUploadEventId = uploadButton.dataset.countdownUpload || "";
      uploadInput?.click();
      return;
    }

    const deleteCoverButton = event.target.closest("[data-countdown-delete-cover]");
    if (deleteCoverButton) {
      removeCover(deleteCoverButton.dataset.countdownDeleteCover);
      return;
    }

    const promptButton = event.target.closest("[data-countdown-copy-prompt]");
    if (promptButton) {
      copyPrompt(promptButton.dataset.countdownCopyPrompt);
    }
  });

  await loadEvents();
  tickTimer = window.setInterval(updateCountdownValues, SECOND_MS);
  refreshTimer = window.setInterval(() => loadEvents({ silent: true }), REFRESH_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      renderCountdowns();
      loadEvents({ silent: true });
    }
  });
}

async function loadEvents(options = {}) {
  if (loadInFlight) return;
  loadInFlight = true;
  if (refreshButton) refreshButton.disabled = true;
  state.loading = !options.silent;
  if (state.loading) renderLoading();

  try {
    if (options.forceRefresh) {
      state.statusMessage = "Odświeżam Google Calendar...";
      renderCountdowns();
      const syncResult = await syncGoogleCalendarNow({ force: true });
      if (syncResult?.ok === false) {
        const detail = syncResult.errors?.[0]?.error || "synchronizacja Google Calendar nie powiodła się";
        throw new Error(detail);
      }
    }
    const payload = await fetchDashboardEvents({
      includeLocal: true,
      requireGoogle: false,
      showPastEvents: false,
      sync: !options.forceRefresh,
      windowDays: EVENTS_WINDOW_DAYS,
    });
    const todayResult = await fetchDashboardEvents({
      includeLocal: true,
      requireGoogle: false,
      showPastEvents: true,
      sync: false,
      windowDays: 1,
    }).catch(() => null);
    const referenceDate = new Date();
    const categories = normalizeCategoryDefinitions(payload.countdownCategories);
    const categoryCovers = normalizeCategoryCovers(payload.countdownCategoryCovers);
    const normalized = applyCategoryCovers(
      normalizeEvents(payload.events, { source: "local" }),
      categoryCovers,
    );
    const enrichedEvents = enrichEvents(normalized, { today: referenceDate });
    const events = getVisibleEvents(enrichedEvents, {
      referenceDate,
      showPastEvents: false,
    }).filter((event) => isEventWithinCinemaCityMembership(event));
    const notificationPayload = todayResult || payload;
    const allEvents = enrichEvents(applyCategoryCovers(
      normalizeEvents(notificationPayload.events, { source: "local" }),
      categoryCovers,
    ), {
      today: referenceDate,
    }).filter((event) => isEventWithinCinemaCityMembership(event));
    state = {
      ...state,
      events,
      allEvents,
      categories,
      hiddenCategoryIds: new Set([...state.hiddenCategoryIds].filter((id) => categories.some((row) => row.id === id))),
      categoryCovers,
      loading: false,
      error: "",
      lastSyncAt: payload.google?.lastSyncAt || state.lastSyncAt,
      statusMessage: options.forceRefresh ? "Google Calendar odświeżony" : state.statusMessage,
    };
    populateCategoryControls();
    syncCreateEventCategoryOptions();
    render();
    renderEventNotifications();
  } catch (error) {
    state = {
      ...state,
      loading: false,
      error: options.silent && state.events.length ? "" : error?.message || String(error || "load failed"),
      statusMessage: options.forceRefresh
        ? `Nie udało się odświeżyć kalendarza: ${error?.message || error}`
        : state.statusMessage,
    };
    render();
  } finally {
    loadInFlight = false;
    if (refreshButton) refreshButton.disabled = false;
  }
}

function render() {
  renderOptions();
  renderCountdowns();
}

function renderLoading() {
  list.innerHTML = "";
  list.appendChild(createEmpty("Ładuję countdowny..."));
  if (foot) foot.textContent = "Synchronizuję daty...";
}

function renderOptions() {
  const displayedIds = new Set(getCountdownEvents({ ignoreFilter: true }).map((event) => event.id));
  const options = state.events
    .filter((event) => !displayedIds.has(event.id))
    .sort(compareEventsChronologically);

  select.innerHTML = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = options.length ? "Wybierz event..." : "Brak kolejnych eventów";
  select.appendChild(empty);

  options.forEach((event) => {
    const option = document.createElement("option");
    option.value = event.id;
    option.textContent = `${event.title} · ${formatEventDate(event)}`;
    select.appendChild(option);
  });

  select.disabled = options.length === 0;
  syncAddControls({ syncCategory: true });
}

function populateCategoryControls() {
  const selectedCategory = categorySelect?.value || "";
  populateCategoryFilterMenu();

  if (categorySelect) {
    categorySelect.innerHTML = "";
    categorySelect.appendChild(createOption("", "Wybierz kategorię..."));
    state.categories.forEach((category) => {
      categorySelect.appendChild(createOption(category.id, category.label));
    });
    if (categoryIds().has(selectedCategory)) categorySelect.value = selectedCategory;
  }
}

function normalizeCategoryCovers(value) {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(Object.entries(value).filter(([id, url]) => (
    /^[a-z0-9][a-z0-9_-]{0,63}$/.test(id) && typeof url === "string" && url.trim()
  )));
}

function applyCategoryCovers(events, covers) {
  return events.map((event) => ({
    ...event,
    coverImage: covers[event.category] || event.coverImage,
  }));
}

function populateCategoryFilterMenu() {
  if (!categoryFilter || !categoryFilterMenu) return;
  categoryFilterMenu.innerHTML = "";
  const categorySection = document.createElement("fieldset");
  categorySection.innerHTML = "<legend>Kategorie</legend>";
  categorySection.appendChild(createFilterCheckbox("all", "Wszystkie", state.hiddenCategoryIds.size === 0));
  state.categories.forEach((category) => {
    categorySection.appendChild(createFilterCheckbox(
      category.id,
      category.label,
      !state.hiddenCategoryIds.has(category.id),
    ));
  });

  const rangeSection = document.createElement("fieldset");
  rangeSection.innerHTML = "<legend>Zakres czasu</legend>";
  [[30, "30 dni"], [90, "90 dni"], [180, "180 dni"], [400, "Cały rok"]].forEach(([days, label]) => {
    const row = document.createElement("label");
    row.className = "event-countdowns-filter-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "event-countdowns-range";
    input.value = String(days);
    input.checked = state.rangeDays === days;
    row.append(input, document.createTextNode(label));
    rangeSection.appendChild(row);
  });
  categoryFilterMenu.append(categorySection, rangeSection);
  updateCategoryFilterButton();
}

function createFilterCheckbox(value, label, checked) {
  const row = document.createElement("label");
  row.className = "event-countdowns-filter-option";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.value = value;
  input.checked = checked;
  row.append(input, document.createTextNode(label));
  return row;
}

function handleFilterChange(event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;
  if (input.name === "event-countdowns-range") {
    state.rangeDays = loadRangeDays(input.value);
    globalThis.localStorage?.setItem(RANGE_FILTER_KEY, String(state.rangeDays));
  } else if (input.type === "checkbox") {
    if (input.value === "all") {
      state.hiddenCategoryIds = input.checked ? new Set() : categoryIds();
    } else if (input.checked) {
      state.hiddenCategoryIds.delete(input.value);
    } else {
      state.hiddenCategoryIds.add(input.value);
    }
    saveIdSet(CATEGORY_FILTER_KEY, state.hiddenCategoryIds);
  }
  populateCategoryFilterMenu();
  renderCountdowns();
}

function updateCategoryFilterButton() {
  if (!categoryFilter) return;
  const visible = state.categories.filter((category) => !state.hiddenCategoryIds.has(category.id));
  const categoryLabelText = visible.length === state.categories.length
    ? "wszystkie"
    : visible.length === 1
      ? visible[0].label
      : `${visible.length}/${state.categories.length} kat.`;
  categoryFilter.textContent = `Filtry: ${categoryLabelText} · ${state.rangeDays} dni`;
}

function closeCategoryFilterMenu() {
  if (categoryFilterMenu) categoryFilterMenu.hidden = true;
  categoryFilter?.setAttribute("aria-expanded", "false");
}

function normalizeCategoryDefinitions(rows) {
  const definitions = new Map(DEFAULT_CATEGORY_DEFINITIONS.map((category) => [category.id, category]));
  (Array.isArray(rows) ? rows : []).forEach((row) => {
    const id = String(row?.id || "").trim().toLowerCase();
    const label = String(row?.label || "").trim();
    if (/^[a-z0-9][a-z0-9_-]{0,63}$/.test(id) && label) {
      definitions.set(id, { id, label, custom: Boolean(row.custom) });
    }
  });
  return [...definitions.values()];
}

function categoryIds() {
  return new Set(state.categories.map((category) => category.id));
}

function categoryLabel(categoryId) {
  return state.categories.find((category) => category.id === categoryId)?.label
    || EVENT_COUNTDOWN_CATEGORY_LABELS[categoryId]
    || String(categoryId || "Inne").replaceAll("_", " ");
}

function populateCategorySelect(target, selected = "") {
  if (!target) return;
  target.innerHTML = "";
  state.categories.forEach((category) => {
    target.appendChild(createOption(category.id, category.label));
  });
  if (categoryIds().has(selected)) target.value = selected;
}

function syncCreateEventCategoryOptions() {
  const target = document.querySelector('#event-countdown-create-form select[name="category"]');
  if (target) populateCategorySelect(target, target.value);
}

function createOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function syncAddControls(options = {}) {
  const selectedEvent = state.events.find((event) => event.id === select.value);
  if (categorySelect && options.syncCategory) {
    categorySelect.value = selectedEvent?.category || "";
  }
  if (addButton) {
    addButton.disabled = state.saving || !selectedEvent || !categorySelect?.value;
  }
}

function renderCountdowns() {
  if (state.error) {
    list.innerHTML = "";
    list.appendChild(createEmpty(`Nie udało się załadować countdownów: ${state.error}`));
    if (foot) foot.textContent = "Błąd ładowania dat";
    return;
  }

  const countdowns = getCountdownEvents();
  const allCountdowns = getCountdownEvents({ ignoreFilter: true });
  list.innerHTML = "";
  card.classList.toggle("is-empty", countdowns.length === 0);

  if (countdowns.length === 0) {
    const message = allCountdowns.length
      ? "Brak countdownów w wybranej kategorii."
      : "Dodaj event z listy albo utwórz nowy event dashboardowy.";
    list.appendChild(createEmpty(message));
    if (foot) foot.textContent = `${state.events.length} nadchodzących eventów do wyboru`;
    return;
  }

  countdowns.forEach((event) => {
    list.appendChild(createCountdownCard(event));
  });

  if (foot && state.statusMessage) {
    foot.textContent = state.statusMessage;
    return;
  }

  if (foot) {
    const count = countdowns.length;
    const totalCount = allCountdowns.length;
    const suffix = count === totalCount ? "" : ` · pokazuję ${count} z ${totalCount}`;
    const syncLabel = formatLastSync(state.lastSyncAt);
    foot.textContent = `${count} aktywne ${count === 1 ? "odliczanie" : "odliczania"} · źródło: dashboard + Google Calendar${syncLabel ? ` · sync: ${syncLabel}` : ""}${suffix}`;
  }
}

function createCountdownCard(event) {
  const remaining = getRemainingParts(event);
  const item = document.createElement("article");
  item.className = "event-countdown-item";
  item.dataset.countdownId = event.id;
  item.dataset.countdownCategory = event.category;
  if (remaining.totalMs <= 0) item.classList.add("is-due");
  else if (remaining.totalMs <= DAY_MS) item.classList.add("is-soon");

  const cover = document.createElement("div");
  cover.className = "event-countdown-cover";
  let deleteCover = null;
  if (event.coverImage) {
    const img = document.createElement("img");
    img.src = resolveCoverImageUrl(event.coverImage);
    img.alt = "";
    img.loading = "lazy";
    cover.classList.add("has-image");
    cover.appendChild(img);

    deleteCover = document.createElement("button");
    deleteCover.type = "button";
    deleteCover.className = "event-countdown-cover-delete";
    deleteCover.dataset.countdownDeleteCover = event.id;
    deleteCover.disabled = state.deletingCoverId === event.id;
    deleteCover.textContent = "";
    deleteCover.title = state.deletingCoverId === event.id ? "Usuwanie coveru..." : "Usuń cover";
    deleteCover.setAttribute("aria-label", `Usuń cover: ${event.title}`);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "event-countdown-cover-placeholder";
    placeholder.textContent = categoryLabel(event.category);
    cover.appendChild(placeholder);
  }

  const upload = document.createElement("button");
  upload.type = "button";
  upload.className = "event-countdown-upload";
  upload.dataset.countdownUpload = event.id;
  upload.disabled = state.uploadingId === event.id;
  upload.title = "PNG/JPG/WebP, najlepiej 16:9";
  upload.setAttribute("aria-label", event.coverImage ? `Zmien cover: ${event.title}` : `Dodaj cover: ${event.title}`);
  upload.textContent = "";

  if (!event.coverImage) {
    const promptButton = document.createElement("button");
    promptButton.type = "button";
    promptButton.className = "event-countdown-prompt-copy";
    promptButton.dataset.countdownCopyPrompt = event.id;
    promptButton.textContent = state.promptCopiedId === event.id ? "Skopiowane" : "Kopiuj prompt";
    cover.appendChild(promptButton);
  }

  const head = document.createElement("div");
  head.className = "event-countdown-item-head";

  const copy = document.createElement("div");
  copy.className = "event-countdown-copy";

  const title = document.createElement("div");
  title.className = "event-countdown-title";
  title.textContent = event.title;

  const meta = document.createElement("div");
  meta.className = "event-countdown-meta";
  const categoryTrigger = document.createElement("button");
  categoryTrigger.type = "button";
  categoryTrigger.className = "event-countdown-category-trigger";
  categoryTrigger.dataset.countdownCategoryEdit = event.id;
  categoryTrigger.disabled = state.categorySavingId === event.id;
  categoryTrigger.setAttribute("aria-label", `Zmień kategorię: ${event.title}`);
  categoryTrigger.textContent = categoryLabel(event.category);
  meta.append(categoryTrigger, document.createTextNode(` · ${formatEventDate(event)}`));

  copy.append(title, meta);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "event-countdown-remove";
  remove.dataset.countdownRemove = event.id;
  remove.setAttribute("aria-label", `Usuń countdown: ${event.title}`);
  remove.title = "Usuń countdown";
  remove.textContent = "×";

  head.append(copy, remove);

  const grid = document.createElement("div");
  grid.className = "event-countdown-grid";
  [
    ["days", remaining.days, "dni"],
    ["hours", remaining.hours, "godz"],
    ["minutes", remaining.minutes, "min"],
    ["seconds", remaining.seconds, "sek"],
  ].forEach(([key, value, label]) => {
    const part = document.createElement("div");
    part.className = `event-countdown-part is-${key}`;
    const number = document.createElement("span");
    number.className = "event-countdown-number";
    number.textContent = key === "days" ? String(value) : pad(value);
    const text = document.createElement("span");
    text.className = "event-countdown-label";
    text.textContent = label;
    part.append(number, text);
    grid.appendChild(part);
  });

  item.append(upload);
  if (deleteCover) item.append(deleteCover);
  item.append(cover, head, grid);
  return item;
}

function updateCountdownValues() {
  const countdowns = getCountdownEvents();
  const items = Array.from(list.querySelectorAll("[data-countdown-id]"));
  const itemsById = new Map(items.map((item) => [item.dataset.countdownId, item]));
  if (items.length !== countdowns.length || countdowns.some((event) => !itemsById.has(event.id))) {
    renderCountdowns();
    return;
  }

  countdowns.forEach((event) => {
    const item = itemsById.get(event.id);
    const remaining = getRemainingParts(event);
    item.classList.toggle("is-due", remaining.totalMs <= 0);
    item.classList.toggle("is-soon", remaining.totalMs > 0 && remaining.totalMs <= DAY_MS);
    [
      ["days", remaining.days],
      ["hours", remaining.hours],
      ["minutes", remaining.minutes],
      ["seconds", remaining.seconds],
    ].forEach(([key, value]) => {
      const number = item.querySelector(`.event-countdown-part.is-${key} .event-countdown-number`);
      if (number) number.textContent = key === "days" ? String(value) : pad(value);
    });
  });
}

function getCountdownEvents(options = {}) {
  const sourceEvents = options.includePast ? state.allEvents : state.events;
  const byId = new Map(sourceEvents.map((event) => [event.id, event]));
  const ids = new Set();
  sourceEvents.forEach((event) => {
    if (event.countdown && event.category && !state.hiddenIds.has(event.id)) ids.add(event.id);
  });
  state.selectedIds.forEach((id) => {
    if (byId.has(id) && !state.hiddenIds.has(id)) ids.add(id);
  });
  return Array.from(ids)
    .map((id) => byId.get(id))
    .filter((event) => event?.category)
    .filter((event) => options.ignoreFilter || !state.hiddenCategoryIds.has(event.category))
    .filter((event) => options.ignoreFilter || getTargetDate(event).getTime() <= Date.now() + state.rangeDays * DAY_MS)
    .sort((a, b) => getTargetDate(a) - getTargetDate(b) || compareEventsChronologically(a, b));
}

async function addSelectedCountdown() {
  const id = select.value;
  const category = categorySelect?.value || "";
  const selectedEvent = state.events.find((event) => event.id === id);
  if (!selectedEvent || !categoryIds().has(category) || state.saving) return;

  state.saving = true;
  state.statusMessage = "Zapisuję kategorię eventu...";
  syncAddControls();
  try {
    const updatedEvent = { ...selectedEvent, category, countdown: true };
    const result = isGoogleEvent(updatedEvent)
      ? await saveEventDashboardOverride(updatedEvent)
      : await saveLocalDashboardEvent(updatedEvent);
    const savedEvent = result?.event || updatedEvent;
    state.events = state.events.map((event) => event.id === id ? mergeSavedEvent(event, savedEvent) : event);
    state.allEvents = state.allEvents.map((event) => event.id === id ? mergeSavedEvent(event, savedEvent) : event);
    state.selectedIds.add(id);
    state.hiddenIds.delete(id);
    saveIdSet(SELECTED_KEY, state.selectedIds);
    saveIdSet(HIDDEN_KEY, state.hiddenIds);
    state.statusMessage = "Event dodany do countdownów";
    renderEventNotifications();
  } catch (error) {
    state.statusMessage = `Nie udało się dodać eventu: ${error.message || error}`;
  } finally {
    state.saving = false;
    render();
  }
}

function removeCountdown(id) {
  if (!id) return;
  state.selectedIds.delete(id);
  state.hiddenIds.add(id);
  saveIdSet(SELECTED_KEY, state.selectedIds);
  saveIdSet(HIDDEN_KEY, state.hiddenIds);
  render();
  renderEventNotifications();
}

function isGoogleEvent(event) {
  return event?.external?.provider === "google_calendar" && Boolean(event.external?.eventId);
}

function mergeSavedEvent(current, saved) {
  return {
    ...current,
    ...saved,
    dateObj: current.dateObj,
    startDateTime: current.startDateTime,
  };
}

async function updateCountdownCategory(eventId, category) {
  const current = state.events.find((event) => event.id === eventId);
  if (!current || !categoryIds().has(category) || category === current.category || state.categorySavingId) return false;
  state.categorySavingId = eventId;
  state.statusMessage = "Zapisuję nową kategorię eventu...";
  renderCountdowns();
  try {
    const updatedEvent = { ...current, category, countdown: true };
    const result = isGoogleEvent(updatedEvent)
      ? await saveEventDashboardOverride(updatedEvent)
      : await saveLocalDashboardEvent(updatedEvent);
    const savedEvent = { ...(result?.event || updatedEvent), category, countdown: true };
    const applySaved = (event) => {
      if (event.id !== eventId) return event;
      const merged = mergeSavedEvent(event, savedEvent);
      return { ...merged, coverImage: state.categoryCovers[category] || merged.coverImage };
    };
    state.events = state.events.map(applySaved);
    state.allEvents = state.allEvents.map(applySaved);
    state.statusMessage = `Kategoria zmieniona na: ${categoryLabel(category)}`;
    renderEventNotifications();
    return true;
  } catch (error) {
    state.statusMessage = `Nie udało się zmienić kategorii: ${error.message || error}`;
    return false;
  } finally {
    state.categorySavingId = "";
    render();
  }
}

function openEventCategoryDialog(eventId) {
  const countdownEvent = state.events.find((event) => event.id === eventId);
  if (!countdownEvent) return;
  const overlay = ensureEventCategoryDialog();
  const form = overlay.querySelector("form");
  form.dataset.eventId = eventId;
  populateCategorySelect(form.elements.category, countdownEvent.category);
  overlay.querySelector("[data-event-category-change-note]").textContent = "";
  overlay.hidden = false;
  document.body.classList.add("event-countdown-dialog-open");
  requestAnimationFrame(() => form.elements.category.focus());
}

function ensureEventCategoryDialog() {
  let overlay = document.getElementById("event-countdown-category-change-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.className = "event-countdown-dialog-overlay";
  overlay.id = "event-countdown-category-change-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <form class="event-countdown-dialog" id="event-countdown-category-change-form">
      <header class="event-countdown-dialog-head">
        <div>
          <div class="event-countdown-dialog-kicker">Event Countdowns</div>
          <h3>Zmień kategorię eventu</h3>
        </div>
        <button class="event-countdown-dialog-close" type="button" data-event-category-change-close aria-label="Zamknij">×</button>
      </header>
      <div class="event-countdown-dialog-grid">
        <label class="event-countdown-dialog-wide">
          <span>Kategoria</span>
          <select name="category" required></select>
        </label>
      </div>
      <div class="event-countdown-dialog-note" data-event-category-change-note aria-live="polite"></div>
      <footer class="event-countdown-dialog-actions">
        <button class="event-countdown-dialog-cancel" type="button" data-event-category-change-close>Anuluj</button>
        <button class="event-countdown-dialog-save" type="submit">Zapisz</button>
      </footer>
    </form>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-event-category-change-close]")) {
      closeEventCategoryDialog();
    }
  });
  overlay.querySelector("form").addEventListener("submit", handleEventCategorySubmit);
  document.body.appendChild(overlay);
  return overlay;
}

function closeEventCategoryDialog() {
  const overlay = document.getElementById("event-countdown-category-change-overlay");
  if (overlay) overlay.hidden = true;
  document.body.classList.remove("event-countdown-dialog-open");
}

async function handleEventCategorySubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const note = form.querySelector("[data-event-category-change-note]");
  const save = form.querySelector(".event-countdown-dialog-save");
  save.disabled = true;
  save.textContent = "Zapisuję...";
  const changed = await updateCountdownCategory(form.dataset.eventId, form.elements.category.value);
  if (changed) closeEventCategoryDialog();
  else note.textContent = "Nie udało się zmienić kategorii albo wybrano tę samą.";
  save.disabled = false;
  save.textContent = "Zapisz";
}

function openCreateEventDialog() {
  const overlay = ensureCreateEventDialog();
  const form = overlay.querySelector("form");
  form.reset();
  form.elements.date.value = toISODate(new Date());
  const visibleCategories = state.categories.filter((category) => !state.hiddenCategoryIds.has(category.id));
  form.elements.category.value = visibleCategories.length === 1 ? visibleCategories[0].id : "new_episode";
  form.elements.addToGoogle.checked = false;
  overlay.querySelector("[data-event-create-note]").textContent = "";
  overlay.hidden = false;
  document.body.classList.add("event-countdown-dialog-open");
  requestAnimationFrame(() => form.elements.title.focus());
}

function ensureCreateEventDialog() {
  let overlay = document.getElementById("event-countdown-create-overlay");
  if (overlay) return overlay;

  overlay = document.createElement("div");
  overlay.className = "event-countdown-dialog-overlay";
  overlay.id = "event-countdown-create-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <form class="event-countdown-dialog" id="event-countdown-create-form">
      <header class="event-countdown-dialog-head">
        <div>
          <div class="event-countdown-dialog-kicker">Event Countdowns</div>
          <h3>Nowy event</h3>
        </div>
        <button class="event-countdown-dialog-close" type="button" data-event-create-close aria-label="Zamknij">×</button>
      </header>
      <div class="event-countdown-dialog-grid">
        <label class="event-countdown-dialog-wide">
          <span>Tytuł</span>
          <input name="title" required maxlength="160" />
        </label>
        <label>
          <span>Data</span>
          <input name="date" type="date" required />
        </label>
        <label>
          <span>Kategoria</span>
          <select name="category" required></select>
        </label>
        <label class="event-countdown-dialog-wide">
          <span>Notatki</span>
          <textarea name="notes" rows="3"></textarea>
        </label>
        <label class="event-countdown-dialog-check event-countdown-dialog-wide">
          <input name="addToGoogle" type="checkbox" />
          <span>Dodaj również do Google Calendar</span>
        </label>
      </div>
      <p class="event-countdown-dialog-help">Domyślnie event zostanie zapisany wyłącznie w dashboardzie.</p>
      <div class="event-countdown-dialog-note" data-event-create-note aria-live="polite"></div>
      <footer class="event-countdown-dialog-actions">
        <button class="event-countdown-dialog-cancel" type="button" data-event-create-close>Anuluj</button>
        <button class="event-countdown-dialog-save" type="submit">Zapisz event</button>
      </footer>
    </form>
  `;
  const category = overlay.querySelector('select[name="category"]');
  populateCategorySelect(category);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-event-create-close]")) {
      closeCreateEventDialog();
    }
  });
  overlay.querySelector("form").addEventListener("submit", handleCreateEventSubmit);
  document.body.appendChild(overlay);
  return overlay;
}

function closeCreateEventDialog() {
  const overlay = document.getElementById("event-countdown-create-overlay");
  if (overlay) overlay.hidden = true;
  document.body.classList.remove("event-countdown-dialog-open");
}

function openCreateCategoryDialog() {
  const overlay = ensureCreateCategoryDialog();
  const form = overlay.querySelector("form");
  form.reset();
  overlay.querySelector("[data-event-category-note]").textContent = "";
  overlay.hidden = false;
  document.body.classList.add("event-countdown-dialog-open");
  requestAnimationFrame(() => form.elements.label.focus());
}

function ensureCreateCategoryDialog() {
  let overlay = document.getElementById("event-countdown-category-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.className = "event-countdown-dialog-overlay";
  overlay.id = "event-countdown-category-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <form class="event-countdown-dialog" id="event-countdown-category-form">
      <header class="event-countdown-dialog-head">
        <div>
          <div class="event-countdown-dialog-kicker">Event Countdowns</div>
          <h3>Nowa kategoria</h3>
        </div>
        <button class="event-countdown-dialog-close" type="button" data-event-category-close aria-label="Zamknij">×</button>
      </header>
      <div class="event-countdown-dialog-grid">
        <label class="event-countdown-dialog-wide">
          <span>Nazwa kategorii</span>
          <input name="label" required maxlength="80" placeholder="np. Premiera filmu" />
        </label>
      </div>
      <div class="event-countdown-dialog-note" data-event-category-note aria-live="polite"></div>
      <footer class="event-countdown-dialog-actions">
        <button class="event-countdown-dialog-cancel" type="button" data-event-category-close>Anuluj</button>
        <button class="event-countdown-dialog-save" type="submit">Dodaj kategorię</button>
      </footer>
    </form>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-event-category-close]")) {
      closeCreateCategoryDialog();
    }
  });
  overlay.querySelector("form").addEventListener("submit", handleCreateCategorySubmit);
  document.body.appendChild(overlay);
  return overlay;
}

function closeCreateCategoryDialog() {
  const overlay = document.getElementById("event-countdown-category-overlay");
  if (overlay) overlay.hidden = true;
  document.body.classList.remove("event-countdown-dialog-open");
}

function openEditCategoryDialog() {
  const overlay = ensureEditCategoryDialog();
  const form = overlay.querySelector("form");
  populateCategorySelect(form.elements.category);
  syncEditCategoryLabel(form);
  overlay.querySelector("[data-event-category-edit-note]").textContent = "";
  overlay.hidden = false;
  document.body.classList.add("event-countdown-dialog-open");
  requestAnimationFrame(() => form.elements.label.focus());
}

function ensureEditCategoryDialog() {
  let overlay = document.getElementById("event-countdown-category-edit-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.className = "event-countdown-dialog-overlay";
  overlay.id = "event-countdown-category-edit-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <form class="event-countdown-dialog" id="event-countdown-category-edit-form">
      <header class="event-countdown-dialog-head">
        <div>
          <div class="event-countdown-dialog-kicker">Event Countdowns</div>
          <h3>Edytuj kategorię</h3>
        </div>
        <button class="event-countdown-dialog-close" type="button" data-event-category-edit-close aria-label="Zamknij">×</button>
      </header>
      <div class="event-countdown-dialog-grid">
        <label class="event-countdown-dialog-wide">
          <span>Kategoria</span>
          <select name="category" required></select>
        </label>
        <label class="event-countdown-dialog-wide">
          <span>Nowa nazwa</span>
          <input name="label" required maxlength="80" />
        </label>
      </div>
      <div class="event-countdown-dialog-note" data-event-category-edit-note aria-live="polite"></div>
      <footer class="event-countdown-dialog-actions">
        <button class="event-countdown-dialog-cancel" type="button" data-event-category-edit-close>Anuluj</button>
        <button class="event-countdown-dialog-save" type="submit">Zapisz nazwę</button>
      </footer>
    </form>
  `;
  const form = overlay.querySelector("form");
  form.elements.category.addEventListener("change", () => syncEditCategoryLabel(form));
  form.addEventListener("submit", handleEditCategorySubmit);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-event-category-edit-close]")) {
      closeEditCategoryDialog();
    }
  });
  document.body.appendChild(overlay);
  return overlay;
}

function syncEditCategoryLabel(form) {
  const category = state.categories.find((row) => row.id === form.elements.category.value);
  form.elements.label.value = category?.label || "";
}

function closeEditCategoryDialog() {
  const overlay = document.getElementById("event-countdown-category-edit-overlay");
  if (overlay) overlay.hidden = true;
  document.body.classList.remove("event-countdown-dialog-open");
}

async function handleEditCategorySubmit(event) {
  event.preventDefault();
  if (state.saving) return;
  const form = event.currentTarget;
  const note = form.querySelector("[data-event-category-edit-note]");
  const save = form.querySelector(".event-countdown-dialog-save");
  const id = form.elements.category.value;
  const label = form.elements.label.value.trim();
  if (!categoryIds().has(id) || !label) return;

  state.saving = true;
  save.disabled = true;
  save.textContent = "Zapisuję...";
  note.textContent = "Zapisuję nową nazwę kategorii...";
  try {
    const result = await saveEventCountdownCategory(label, id);
    state.categories = normalizeCategoryDefinitions(result?.categories);
    populateCategoryControls();
    syncCreateEventCategoryOptions();
    state.statusMessage = `Zmieniono nazwę kategorii na: ${result?.category?.label || label}`;
    closeEditCategoryDialog();
    render();
  } catch (error) {
    note.textContent = `Nie udało się zmienić nazwy: ${error.message || error}`;
  } finally {
    state.saving = false;
    save.disabled = false;
    save.textContent = "Zapisz nazwę";
  }
}

async function handleCreateCategorySubmit(event) {
  event.preventDefault();
  if (state.saving) return;
  const form = event.currentTarget;
  const note = form.querySelector("[data-event-category-note]");
  const save = form.querySelector(".event-countdown-dialog-save");
  const label = form.elements.label.value.trim();
  if (!label) return;

  state.saving = true;
  save.disabled = true;
  save.textContent = "Dodaję...";
  note.textContent = "Zapisuję kategorię w dashboardzie...";
  try {
    const result = await saveEventCountdownCategory(label);
    state.categories = normalizeCategoryDefinitions(result?.categories);
    populateCategoryControls();
    syncCreateEventCategoryOptions();
    if (result?.category?.id && categorySelect) categorySelect.value = result.category.id;
    state.statusMessage = `Dodano kategorię: ${result?.category?.label || label}`;
    closeCreateCategoryDialog();
    render();
  } catch (error) {
    note.textContent = `Nie udało się dodać kategorii: ${error.message || error}`;
  } finally {
    state.saving = false;
    save.disabled = false;
    save.textContent = "Dodaj kategorię";
  }
}

async function handleCreateEventSubmit(event) {
  event.preventDefault();
  if (state.saving) return;
  const form = event.currentTarget;
  const note = form.querySelector("[data-event-create-note]");
  const save = form.querySelector(".event-countdown-dialog-save");
  const category = form.elements.category.value;
  if (!categoryIds().has(category)) {
    note.textContent = "Wybierz kategorię eventu.";
    return;
  }

  const eventData = {
    title: form.elements.title.value.trim(),
    date: form.elements.date.value,
    category,
    type: category === "concert" ? "concert" : ["match", "stadium_match"].includes(category) ? "match" : "custom",
    countdown: true,
    notes: nullableText(form.elements.notes.value),
  };

  state.saving = true;
  save.disabled = true;
  save.textContent = "Zapisuję...";
  note.textContent = form.elements.addToGoogle.checked
    ? "Dodaję event do dashboardu i Google Calendar..."
    : "Dodaję event tylko do dashboardu...";
  try {
    const result = form.elements.addToGoogle.checked
      ? await upsertGoogleCalendarEvent(eventData)
      : await saveLocalDashboardEvent(eventData);
    const savedId = result?.event?.id;
    if (savedId) {
      state.selectedIds.add(savedId);
      state.hiddenIds.delete(savedId);
      saveIdSet(SELECTED_KEY, state.selectedIds);
      saveIdSet(HIDDEN_KEY, state.hiddenIds);
    }
    state.statusMessage = form.elements.addToGoogle.checked
      ? "Event zapisany w dashboardzie i Google Calendar"
      : "Event zapisany tylko w dashboardzie";
    closeCreateEventDialog();
    await loadEvents({ silent: true });
  } catch (error) {
    note.textContent = `Nie udało się zapisać eventu: ${error.message || error}`;
  } finally {
    state.saving = false;
    save.disabled = false;
    save.textContent = "Zapisz event";
  }
}

function nullableText(value) {
  const text = String(value || "").trim();
  return text || null;
}

function setupNotificationShell() {
  let trigger = document.getElementById("dashboard-event-notifications-trigger");
  if (!trigger) {
    trigger = document.createElement("button");
    trigger.id = "dashboard-event-notifications-trigger";
    trigger.type = "button";
    trigger.className = "dashboard-action-link dashboard-notifications-link";
    trigger.setAttribute("aria-label", "Powiadomienia dashboardu");
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML = '<span aria-hidden="true">●</span><span class="dashboard-notifications-badge" id="dashboard-event-notifications-count">0</span>';
    trigger.hidden = true;
    document.body.appendChild(trigger);
  }

  let panel = document.getElementById("dashboard-event-notifications-panel");
  if (!panel) {
    panel = document.createElement("aside");
    panel.id = "dashboard-event-notifications-panel";
    panel.className = "dashboard-event-notifications-panel";
    panel.hidden = true;
    panel.setAttribute("aria-label", "Powiadomienia dashboardu");
    panel.innerHTML = `
      <div class="dashboard-event-notifications-head">
        <strong>Powiadomienia</strong>
        <button type="button" data-event-notifications-close aria-label="Zamknij">×</button>
      </div>
      <div class="dashboard-event-notifications-list" data-event-notifications-list></div>
    `;
    document.body.appendChild(panel);
  }

  trigger.addEventListener("click", () => {
    const willOpen = panel.hidden;
    panel.hidden = !willOpen;
    trigger.setAttribute("aria-expanded", String(willOpen));
  });
  panel.querySelector("[data-event-notifications-close]")?.addEventListener("click", () => {
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  });
  document.addEventListener("click", (event) => {
    if (panel.hidden) return;
    const path = event.composedPath?.() || [];
    const clickedPanel = path.includes(panel) || panel.contains(event.target);
    const clickedTrigger = path.includes(trigger) || trigger.contains(event.target);
    if (clickedPanel || clickedTrigger) return;
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }, { capture: true });
}

function renderEventNotifications() {
  const todayEvents = getTodayCountdownEvents();
  const dashboardNotifications = listDashboardNotifications();
  const today = toISODate(new Date());
  const readIds = loadTodayReadIds(today);
  const unreadEvents = todayEvents.filter((event) => !readIds.has(event.id));
  const unreadDashboardNotifications = dashboardNotifications.filter((item) => !item.read);
  const trigger = document.getElementById("dashboard-event-notifications-trigger");
  const panel = document.getElementById("dashboard-event-notifications-panel");
  if (!trigger || !panel) return;

  trigger.hidden = todayEvents.length === 0 && dashboardNotifications.length === 0;
  const count = document.getElementById("dashboard-event-notifications-count");
  if (count) {
    const unreadCount = unreadEvents.length + unreadDashboardNotifications.length;
    count.textContent = String(unreadCount);
    count.hidden = unreadCount === 0;
  }
  const notificationList = panel.querySelector("[data-event-notifications-list]");
  notificationList.innerHTML = "";
  dashboardNotifications.forEach((notification) => {
    notificationList.appendChild(createDashboardNotificationItem(notification));
  });
  todayEvents.forEach((event) => {
    notificationList.appendChild(createNotificationItem(event, { isRead: readIds.has(event.id) }));
  });
  if (!todayEvents.length && !dashboardNotifications.length) {
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    return;
  }

  if (unreadEvents.length && globalThis.localStorage?.getItem(TODAY_NOTICE_KEY) !== today) {
    globalThis.localStorage?.setItem(TODAY_NOTICE_KEY, today);
    showTodayEventDialog(unreadEvents);
  }
}

function createDashboardNotificationItem(notification) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "dashboard-event-notification-item";
  item.classList.toggle("is-read", notification.read === true);
  item.dataset.dashboardNotificationId = notification.id;
  item.setAttribute("aria-label", `${notification.read ? "Przeczytane" : "Oznacz jako przeczytane"}: ${notification.title}`);
  item.innerHTML = `<span class="dashboard-event-notification-category"></span><strong></strong>`;
  item.querySelector("span").textContent = notification.category || "Dashboard";
  item.querySelector("strong").textContent = notification.title;
  item.title = notification.message || notification.title;
  item.addEventListener("click", () => {
    markDashboardNotificationRead(notification.id);
    if (notification.targetId) {
      document.getElementById(notification.targetId)?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    }
  });
  return item;
}

function getTodayCountdownEvents() {
  const today = toISODate(new Date());
  return getCountdownEvents({ includePast: true, ignoreFilter: true })
    .filter((event) => event.date === today);
}

function createNotificationItem(event, { isRead = false } = {}) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "dashboard-event-notification-item";
  item.classList.toggle("is-read", isRead);
  item.dataset.eventNotificationId = event.id;
  item.setAttribute("aria-label", `${isRead ? "Przeczytane" : "Oznacz jako przeczytane"}: ${event.title}`);
  item.innerHTML = `<span class="dashboard-event-notification-category"></span><strong></strong>`;
  item.querySelector("span").textContent = categoryLabel(event.category);
  item.querySelector("strong").textContent = event.title;
  item.addEventListener("click", () => {
    markTodayEventRead(event);
    card.scrollIntoView?.({ behavior: "smooth", block: "center" });
  });
  return item;
}

function showTodayEventDialog(events) {
  const queue = events.filter(Boolean);
  if (!queue.length) return;

  document.getElementById("event-today-notification-overlay")?.remove();
  const overlay = document.createElement("div");
  overlay.id = "event-today-notification-overlay";
  overlay.className = "event-today-notification-overlay";
  overlay.innerHTML = `
    <section class="event-today-notification" role="alertdialog" aria-modal="true" aria-labelledby="event-today-notification-title">
      <button type="button" class="event-today-notification-close" data-event-today-close aria-label="Oznacz jako przeczytane i pokaż następne">×</button>
      <div class="event-today-notification-cover" data-event-today-cover></div>
      <div class="event-today-notification-copy">
        <div class="event-today-notification-kicker">Powiadomienie <span data-event-today-progress></span></div>
        <h2 id="event-today-notification-title"></h2>
        <strong class="event-today-notification-category" data-event-today-category></strong>
      </div>
    </section>
  `;

  let index = 0;
  const renderCurrent = () => {
    const current = queue[index];
    const cover = overlay.querySelector("[data-event-today-cover]");
    cover.innerHTML = "";
    if (current.coverImage) {
      const image = document.createElement("img");
      image.src = resolveCoverImageUrl(current.coverImage);
      image.alt = "";
      cover.appendChild(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "event-today-notification-cover-placeholder";
      placeholder.textContent = categoryLabel(current.category);
      cover.appendChild(placeholder);
    }
    overlay.querySelector("[data-event-today-progress]").textContent = queue.length > 1
      ? `${index + 1} / ${queue.length}`
      : "";
    overlay.querySelector("[data-event-today-category]").textContent = categoryLabel(current.category);
    overlay.querySelector("h2").textContent = current.title;
    overlay.querySelector("[data-event-today-close]")?.focus();
  };

  overlay.querySelector("[data-event-today-close]").addEventListener("click", () => {
    markTodayEventRead(queue[index]);
    index += 1;
    if (index >= queue.length) {
      overlay.remove();
      return;
    }
    renderCurrent();
  });
  document.body.appendChild(overlay);
  renderCurrent();
}

function markTodayEventRead(event) {
  if (!event?.id) return;
  const today = toISODate(new Date());
  const readIds = loadTodayReadIds(today);
  readIds.add(String(event.id));
  saveTodayReadIds(today, readIds);
  renderEventNotifications();
}

function loadTodayReadIds(today) {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(TODAY_READ_KEY) || "null");
    if (parsed?.date !== today || !Array.isArray(parsed.ids)) return new Set();
    return new Set(parsed.ids.filter(Boolean).map(String));
  } catch (error) {
    return new Set();
  }
}

function saveTodayReadIds(today, readIds) {
  globalThis.localStorage?.setItem(TODAY_READ_KEY, JSON.stringify({
    date: today,
    ids: Array.from(readIds),
  }));
}

async function handleCoverUpload(event) {
  const file = event.target.files?.[0];
  const eventId = pendingUploadEventId;
  pendingUploadEventId = "";
  event.target.value = "";
  if (!file || !eventId) return;

  const countdownEvent = state.events.find((item) => item.id === eventId);
  if (!countdownEvent) return;
  if (!String(file.type || "").startsWith("image/")) {
    state.statusMessage = "Cover musi byc obrazem PNG, JPG albo WebP";
    renderCountdowns();
    return;
  }

  state.uploadingId = eventId;
  state.statusMessage = "Zapisuje cover w folderze projektu...";
  renderCountdowns();
  try {
    const dataUrl = await fileToDataUrl(file);
    const result = await uploadEventCountdownCover(countdownEvent, dataUrl);
    const coverImage = result?.url || result?.event?.coverImage;
    if (!coverImage) throw new Error("Brak URL grafiki po uploadzie");
    const sharedCategory = countdownEvent.category === "phases_of_the_moon" ? countdownEvent.category : "";
    if (sharedCategory) state.categoryCovers[sharedCategory] = coverImage;
    const assignCover = (item) => (
      item.id === eventId || (sharedCategory && item.category === sharedCategory)
        ? { ...item, coverImage }
        : item
    );
    state.events = state.events.map(assignCover);
    state.allEvents = state.allEvents.map(assignCover);
    state.statusMessage = sharedCategory
      ? "Wspólny cover Full Moon zapisany dla wszystkich pełni"
      : "Cover zapisany w assets/events";
  } catch (error) {
    state.statusMessage = `Nie udalo sie zapisac covera: ${error.message || error}`;
  } finally {
    state.uploadingId = "";
    render();
  }
}

async function removeCover(eventId) {
  const countdownEvent = state.events.find((item) => item.id === eventId);
  if (!countdownEvent || !countdownEvent.coverImage || state.deletingCoverId) return;

  state.deletingCoverId = eventId;
  state.statusMessage = "Usuwam cover...";
  renderCountdowns();
  try {
    await deleteEventCountdownCover(countdownEvent);
    const sharedCategory = countdownEvent.category === "phases_of_the_moon" ? countdownEvent.category : "";
    if (sharedCategory) delete state.categoryCovers[sharedCategory];
    const clearCover = (item) => (
      item.id === eventId || (sharedCategory && item.category === sharedCategory)
        ? { ...item, coverImage: "" }
        : item
    );
    state.events = state.events.map(clearCover);
    state.allEvents = state.allEvents.map(clearCover);
    state.promptCopiedId = "";
    state.statusMessage = "Cover usunięty — możesz skopiować prompt i wgrać nowe zdjęcie";
  } catch (error) {
    state.statusMessage = `Nie udało się usunąć covera: ${error.message || error}`;
  } finally {
    state.deletingCoverId = "";
    render();
  }
}

function createUploadInput() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/png,image/jpeg,image/webp";
  input.hidden = true;
  input.addEventListener("change", handleCoverUpload);
  card.appendChild(input);
  return input;
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Nie udalo sie odczytac pliku"));
    reader.readAsDataURL(file);
  });
}

async function copyPrompt(eventId) {
  const event = state.events.find((item) => item.id === eventId);
  if (!event) return;
  const prompt = buildCoverPrompt(event);
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(prompt);
    } else {
      copyTextFallback(prompt);
    }
    state.promptCopiedId = eventId;
    state.statusMessage = "Prompt skopiowany";
    renderCountdowns();
  } catch (error) {
    state.statusMessage = "Nie udalo sie skopiowac promptu";
    renderCountdowns();
  }
}

function copyTextFallback(text) {
  const node = document.createElement("textarea");
  node.value = text;
  node.setAttribute("readonly", "");
  node.style.position = "fixed";
  node.style.opacity = "0";
  document.body.appendChild(node);
  node.select();
  document.execCommand("copy");
  node.remove();
}

function buildCoverPrompt(event) {
  const pieces = [
    `Design a clean 16:9 event cover for "${event.title}".`,
    `Event date: ${formatEventDate(event)}.`,
    `Event category: ${categoryLabel(event.category) || event.type || "custom"}.`,
  ];
  if (event.notes) pieces.push(`Context notes: ${event.notes}.`);
  pieces.push(
    "Mood and key visual: [add your own details].",
    "Text, logo, venue name, sponsor marks, or other branding: [describe what should appear, or leave blank].",
    "Specific real-world visual details, natural composition, restrained color grading, dashboard-friendly contrast, no generic AI glow.",
  );
  return pieces.join(" ");
}

function resolveCoverImageUrl(value) {
  const url = String(value || "").trim();
  if (!url) return "";
  if (/^(?:https?:|data:|blob:)/i.test(url)) return url;
  if (url.startsWith("/cleaning-dashboard/")) return url;
  if (url.startsWith("/assets/")) {
    return `${DASHBOARD_BASE_PATH}${url.slice(1)}`;
  }
  return url;
}

function getRemainingParts(event) {
  const totalMs = Math.max(0, getTargetDate(event).getTime() - Date.now());
  return {
    totalMs,
    days: Math.floor(totalMs / DAY_MS),
    hours: Math.floor((totalMs % DAY_MS) / HOUR_MS),
    minutes: Math.floor((totalMs % HOUR_MS) / MINUTE_MS),
    seconds: Math.floor((totalMs % MINUTE_MS) / SECOND_MS),
  };
}

function getTargetDate(event) {
  return event.startDateTime || event.dateObj || new Date();
}

function formatEventDate(event) {
  const pieces = [formatDateLong(event.dateObj)];
  if (event.startTime) pieces.push(event.endTime ? `${event.startTime}-${event.endTime}` : event.startTime);
  return pieces.filter(Boolean).join(" · ");
}

function formatLastSync(value) {
  const date = new Date(value || "");
  if (!Number.isFinite(date.getTime())) return "";
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function createEmpty(text) {
  const empty = document.createElement("div");
  empty.className = "event-countdown-empty";
  empty.textContent = text;
  return empty;
}

function pad(value) {
  return String(Math.max(0, value)).padStart(2, "0");
}

function loadIdSet(key) {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(key) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : []);
  } catch (error) {
    return new Set();
  }
}

function saveIdSet(key, value) {
  globalThis.localStorage?.setItem(key, JSON.stringify(Array.from(value)));
}

function loadHiddenCategoryIds() {
  const stored = globalThis.localStorage?.getItem(CATEGORY_FILTER_KEY) || "";
  try {
    const parsed = JSON.parse(stored);
    return new Set(Array.isArray(parsed) ? parsed.filter((id) => /^[a-z0-9][a-z0-9_-]{0,63}$/.test(id)) : []);
  } catch {
    return new Set();
  }
}

function loadRangeDays(value = globalThis.localStorage?.getItem(RANGE_FILTER_KEY)) {
  const parsed = Number(value);
  return [30, 90, 180, 400].includes(parsed) ? parsed : 90;
}

window.addEventListener("beforeunload", () => {
  if (tickTimer) window.clearInterval(tickTimer);
  if (refreshTimer) window.clearInterval(refreshTimer);
});
