import { formatDateLong, formatDateShort, formatDaysUntil } from "./events-date.js";
import { fetchDashboardEvents, fetchGoogleCalendars, saveEventDashboardOverride, upsertGoogleCalendarEvent } from "./events-api.js";
import { getLongWeekendSuggestion } from "./events-insights.js";
import {
  EVENT_COUNTDOWN_CATEGORIES,
  EVENT_COUNTDOWN_CATEGORY_LABELS,
  EVENT_TYPES,
  TYPE_LABELS,
  compareEventsChronologically,
  enrichEvents,
  getVisibleEvents,
  normalizeEvents,
} from "./events-sources.js";
import { formatLoadedAt, formatLoadTime, startLoadTimer } from "./load-timing.js";

const STORAGE_KEY = "eventsWidget.dateView";
const LEGACY_STORAGE_KEY = "eventsWidget.displayMode";
const EVENTS_CACHE_KEY = "eventsWidget.lastPayload.v1";
const VALID_MODES = new Set(["today", "week", "month", "year"]);
const SYNTHETIC_TASKS_CALENDAR_ID = "__google_tasks__";
const AUTO_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const FOCUS_REFRESH_MIN_AGE_MS = 60 * 1000;
const EVENTS_WINDOW_DAYS = 400;

const TYPE_CLASS = {
  public_holiday: "is-public-holiday",
  birthday: "is-birthday",
  short_day: "is-short-day",
  trip: "is-purple",
  concert: "is-purple",
  match: "is-match",
  deadline: "is-deadline",
  payday: "is-payday",
  task: "is-task",
  personal_event: "is-neutral",
  custom: "is-neutral",
};

const card = document.getElementById("events-widget");
const nearestBox = document.getElementById("events-nearest");
const list = document.getElementById("events-list");
const calendarsBox = document.getElementById("events-calendars");
const foot = document.getElementById("events-foot");
const modeButtons = Array.from(document.querySelectorAll("[data-events-mode]"));
const typeOptions = EVENT_TYPES
  .filter((type) => type !== "birthday")
  .map((type) => ({ value: type, label: TYPE_LABELS[type] || type }));
const HIDDEN_CALENDARS_KEY = "eventsWidget.hiddenCalendars";

let displayMode = getInitialMode();
let state = {
  events: [],
  visibleEvents: [],
  google: {},
  calendars: [],
  hiddenCalendars: loadHiddenCalendars(),
  expandedEvents: new Set(),
  source: "local_json",
  loading: false,
  saving: false,
  editingEvent: null,
  isCachedSnapshot: false,
  cacheSavedAt: null,
  loadMs: null,
  loadedAt: null,
  refreshError: null,
};
let refreshTimer = 0;
let refreshInFlight = null;
let lastRefreshAt = 0;

if (card && nearestBox && list) {
  initEventsWidget();
}

async function initEventsWidget() {
  setMode(displayMode, { render: false });

  const cached = readEventsCache();
  if (cached) {
    applyEventsPayload(cached.payload, {
      isCachedSnapshot: true,
      cacheSavedAt: cached.savedAt,
      loadedAt: cached.savedAt,
    });
    render();
  }

  await loadEvents({ silent: Boolean(cached), preserveOnError: Boolean(cached) });
  await loadCalendars({ refresh: false });
  startAutoRefresh();

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setMode(button.dataset.eventsMode);
    });
  });

  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-events-action]");
    if (!button) return;
    const item = getDisplayEvents().find((entry) => entry.id === button.dataset.eventId);
    if (!item) return;
    if (button.dataset.eventsAction === "edit") {
      openEditor(item);
      return;
    }
  });
  list.addEventListener("click", (event) => {
    if (event.target.closest("[data-events-action]")) return;
    const row = event.target.closest(".evt[data-event-id][data-has-details='true']");
    if (row) toggleEventDetails(row.dataset.eventId);
  });
  list.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    const row = event.target.closest(".evt[data-event-id][data-has-details='true']");
    if (row) {
      event.preventDefault();
      toggleEventDetails(row.dataset.eventId);
    }
  });
  calendarsBox?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-calendar-id]");
    if (!button) return;
    toggleCalendar(button.dataset.calendarId);
  });
  nearestBox.addEventListener("click", (event) => {
    const button = event.target.closest("[data-events-action='retry-google']");
    if (!button) return;
    retryGoogleCalendarSync();
  });
}

async function loadEvents(options = {}) {
  if (refreshInFlight) return refreshInFlight;
  const silent = Boolean(options.silent);
  const preserveOnError = Boolean(options.preserveOnError);
  state.loading = true;
  if (state.events.length || silent) {
    render();
  } else {
    renderLoading();
  }

  refreshInFlight = (async () => {
    const stopTimer = startLoadTimer();
    try {
      const payload = await fetchEvents();
      const loadMs = stopTimer();
      applyEventsPayload(payload, {
        isCachedSnapshot: false,
        loadMs,
        loadedAt: new Date().toISOString(),
      });
      state.loading = false;
      lastRefreshAt = Date.now();
      render();
    } catch (error) {
      if (preserveOnError && state.events.length) {
        state = {
          ...state,
          google: error?.google || state.google || {},
          refreshError: error?.message || String(error || "refresh failed"),
        };
        state.loading = false;
        render();
      } else {
        renderError(error);
      }
    } finally {
      state.loading = false;
      refreshInFlight = null;
      card.classList.toggle("is-syncing", false);
    }
  })();

  return refreshInFlight;
}

function renderLoading() {
  card.classList.add("is-syncing");
  nearestBox.innerHTML = "";
  nearestBox.append(createEmpty("Ładuję daty z Google Calendar..."));
  list.innerHTML = "";
  if (foot) foot.textContent = "Synchronizuję Google Calendar...";
}

async function loadCalendars(options = {}) {
  if (!calendarsBox || !state.google?.connected) {
    renderCalendarFilters();
    return;
  }
  try {
    const payload = await fetchGoogleCalendars({ refresh: Boolean(options.refresh) });
    state.calendars = payload.calendars || payload.google?.availableCalendars || state.calendars || [];
    state.google = payload.google || state.google || {};
  } catch (error) {
    // Calendar list needs an extra OAuth scope. Footer/status already explains connection state.
  }
  renderCalendarFilters();
}

async function fetchEvents() {
  return fetchDashboardEvents({
    includeLocal: false,
    requireGoogle: true,
    showPastEvents: card.dataset.showPastEvents === "true",
    sync: true,
    windowDays: EVENTS_WINDOW_DAYS,
  });
}

function applyEventsPayload(payload, options = {}) {
  const normalized = normalizeEvents(payload.events, { source: "local" });
  const today = new Date();
  const events = enrichEvents(normalized, { today });
  const visibleEvents = getVisibleEvents(events, {
    showPastEvents: card.dataset.showPastEvents === "true",
    referenceDate: today,
  });

  state = {
    ...state,
    events,
    visibleEvents,
    google: payload.google || {},
    calendars: payload.google?.availableCalendars || state.calendars || [],
    source: payload.source || "local_json",
    isCachedSnapshot: Boolean(options.isCachedSnapshot),
    cacheSavedAt: options.cacheSavedAt || null,
    loadMs: Number.isFinite(options.loadMs) ? options.loadMs : state.loadMs,
    loadedAt: options.loadedAt || state.loadedAt,
    refreshError: null,
  };

  if (!options.isCachedSnapshot) {
    saveEventsCache(payload, state.loadedAt);
  }
}

function readEventsCache() {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(EVENTS_CACHE_KEY) || "null");
    if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.payload?.events)) {
      return null;
    }
    return {
      payload: parsed.payload,
      savedAt: parsed.savedAt || parsed.payload?.google?.lastSyncAt || null,
    };
  } catch (error) {
    return null;
  }
}

function saveEventsCache(payload, savedAt) {
  try {
    if (!payload || !Array.isArray(payload.events)) return;
    globalThis.localStorage?.setItem(EVENTS_CACHE_KEY, JSON.stringify({
      savedAt: savedAt || new Date().toISOString(),
      payload,
    }));
  } catch (error) {
    // Cache is an enhancement only; quota/privacy errors should not break the widget.
  }
}

function render() {
  const events = getDisplayEvents();
  const nearest = events[0];

  card.dataset.displayMode = displayMode;
  card.classList.toggle("is-syncing", state.loading && state.events.length > 0);
  card.classList.toggle("is-cache-snapshot", state.isCachedSnapshot);
  renderNearest(nearest);
  renderList(events, nearest);
  renderCalendarFilters();
  renderFooter(events);

  document.dispatchEvent(new Event("dashboard:net"));
}

function getDisplayEvents() {
  const filtered = state.visibleEvents.filter((event) => {
    const calendarId = getEventCalendarFilterId(event);
    return !calendarId || !state.hiddenCalendars.has(calendarId);
  });
  const deduped = dedupeDuplicateCalendarEvents(filtered);
  return collapseBirthdaysByPerson(filterEventsByDateView(deduped));
}

function renderNearest(event) {
  nearestBox.innerHTML = "";
  if (!event) {
    nearestBox.append(createEmpty("Brak nadchodzących dat."));
    return;
  }

  const typeClass = TYPE_CLASS[event.type] || "is-neutral";
  const shell = document.createElement("div");
  shell.className = `events-next ${typeClass}`;
  applyEventAccent(shell, event);

  const label = document.createElement("div");
  label.className = "events-next-label";
  label.textContent = "Najbliższa data";

  const title = document.createElement("div");
  title.className = "events-next-title";
  title.textContent = event.title;

  const meta = document.createElement("div");
  meta.className = "events-next-meta";
  meta.append(
    createMetaChip(formatDateLong(event.dateObj)),
    ...(formatEventTime(event) ? [createMetaChip(formatEventTime(event))] : []),
    createMetaChip(formatDaysUntil(event.meta.daysUntil)),
    createMetaChip(capitalize(event.meta.weekday)),
  );

  const badge = createTypeBadge(event);
  const top = document.createElement("div");
  top.className = "events-next-top";
  top.append(label, badge);

  shell.append(top, title, meta);

  const suggestion = getLongWeekendSuggestion(event);
  if (suggestion || event.meta.isWeekend || event.actionNeeded) {
    const note = document.createElement("div");
    note.className = "events-next-note";
    note.textContent =
      suggestion?.text ||
      (event.meta.isWeekend ? "Ta data wypada w weekend." : event.actionNeeded);
    shell.appendChild(note);
  }

  if (isEditableEvent(event)) {
    const actions = document.createElement("div");
    actions.className = "events-next-actions";
    actions.appendChild(createEventActionButton(event, "Edytuj"));
    shell.appendChild(actions);
  }

  nearestBox.appendChild(shell);
}

function renderList(events, nearest) {
  list.innerHTML = "";

  list.hidden = false;
  const visible = nearest ? events.filter((event) => event.id !== nearest.id) : events;

  if (visible.length === 0) {
    list.appendChild(createEmpty("Brak kolejnych wydarzeń w tym widoku."));
    return;
  }

  visible.forEach((event) => {
    list.appendChild(createEventRow(event));
  });
}

function createEventRow(event) {
  const li = document.createElement("li");
  li.className = `evt ${TYPE_CLASS[event.type] || "is-neutral"}`;
  li.dataset.eventId = event.id;
  applyEventAccent(li, event);
  if (event.meta.isToday) li.classList.add("is-today");
  if (event.meta.isTomorrow) li.classList.add("is-tomorrow");

  const date = document.createElement("span");
  date.className = "date-badge";
  date.textContent = formatDateShort(event.dateObj);
  date.title = formatDateLong(event.dateObj);

  const body = document.createElement("span");
  body.className = "evt-body";

  const title = document.createElement("span");
  title.className = "evt-title";
  title.textContent = event.title;

  const meta = document.createElement("span");
  meta.className = "evt-meta";
  const calendarName = event.external?.calendarSummary;
  meta.textContent = [
    `${capitalize(event.meta.weekday)} · ${formatDaysUntil(event.meta.daysUntil)}`,
    formatEventTime(event),
    calendarName && calendarName !== event.external?.calendarId ? calendarName : "",
  ].filter(Boolean).join(" · ");

  body.append(title, meta);

  const badge = createTypeBadge(event);
  const side = document.createElement("span");
  side.className = "evt-side";
  if (isEditableEvent(event)) {
    side.appendChild(createEventActionButton(event));
  }
  side.appendChild(badge);

  const canExpand = Boolean(event.notes || event.actionNeeded);
  if (canExpand) {
    li.dataset.hasDetails = "true";
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    li.setAttribute("aria-expanded", state.expandedEvents.has(event.id) ? "true" : "false");
    li.title = state.expandedEvents.has(event.id) ? "Kliknij, żeby ukryć opis" : "Kliknij, żeby pokazać opis";
  }

  li.append(date, body, side);

  if (canExpand) {
    const details = document.createElement("div");
    details.className = "evt-details";
    details.hidden = !state.expandedEvents.has(event.id);
    details.textContent = event.actionNeeded
      ? `${event.actionNeeded}${event.actionStatus ? ` · ${event.actionStatus}` : ""}`
      : event.notes;
    li.appendChild(details);
  }

  return li;
}

function renderFooter(events) {
  if (!foot) return;
  const count = events.length;
  const google = state.google || {};
  const loadText = formatLoadTime(state.loadMs);
  const timingLabel = google.connected ? "Google Calendar" : "API";
  const timing = loadText ? ` · ${timingLabel} ${loadText}` : "";
  const loadedAt = state.loadedAt ? ` · ${formatLoadedAt(state.loadedAt)}` : "";
  const syncing = state.loading ? " · sync w toku" : "";
  const cached = state.isCachedSnapshot ? " · pokazuję cache" : "";
  const refreshError = state.refreshError ? " · ostatni auto-sync: błąd" : "";
  const tasksScope = google.connected && google.tasksScopeGranted === false ? " · Tasks: reconnect OAuth" : "";
  const partialSync = Array.isArray(google.partialSyncErrors) && google.partialSyncErrors.length ? " · część kalendarzy: błąd" : "";
  if (google.connected) {
    const synced = google.lastSyncAt ? ` · sync ${formatFooterDate(google.lastSyncAt)}` : "";
    const syncError = google.syncError ? " · błąd sync" : "";
    foot.textContent = `Źródło: Google Calendar · ${count} nadchodzących dat${synced}${timing}${loadedAt}${cached}${syncing}${syncError}${partialSync}${refreshError}${tasksScope}`;
    return;
  }
  if (google.configured && !google.connected) {
    foot.textContent = `Źródło: Google Calendar · wymaga połączenia · ${count} nadchodzących dat${timing}${cached}${syncing}${refreshError}`;
    return;
  }
  foot.textContent = `Źródło: Google Calendar · ${count} nadchodzących dat${timing}${cached}${syncing}${refreshError}`;
}

function startAutoRefresh() {
  if (refreshTimer) return;
  refreshTimer = window.setInterval(() => {
    refreshEventsFromGoogle("interval");
  }, AUTO_REFRESH_INTERVAL_MS);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshEventsFromGoogle("visible");
    }
  });
  window.addEventListener("focus", () => {
    refreshEventsFromGoogle("focus");
  });
}

function refreshEventsFromGoogle(reason) {
  if (document.visibilityState === "hidden") return;
  if (state.saving || state.editingEvent) return;
  if (refreshInFlight) return;

  const now = Date.now();
  const minAge = reason === "interval" ? AUTO_REFRESH_INTERVAL_MS - 1000 : FOCUS_REFRESH_MIN_AGE_MS;
  if (lastRefreshAt && now - lastRefreshAt < minAge) return;

  loadEvents({ silent: true, preserveOnError: true });
}

async function retryGoogleCalendarSync() {
  if (refreshInFlight) return;
  state.refreshError = null;
  card.classList.toggle("is-syncing", true);
  await loadCalendars({ refresh: true });
  await loadEvents();
  await loadCalendars();
}

function renderCalendarFilters() {
  if (!calendarsBox) return;
  const calendars = state.calendars || [];
  const googleCalendars = getCalendarFilterOptions(calendars);
  calendarsBox.innerHTML = "";
  calendarsBox.hidden = !state.google?.connected || googleCalendars.length === 0;
  if (calendarsBox.hidden) return;

  googleCalendars.forEach((calendar) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "events-calendar-chip";
    button.dataset.calendarId = calendar.id;
    const color = String(calendar.backgroundColor || "").trim();
    if (/^#[0-9a-f]{6}$/i.test(color)) {
      button.style.setProperty("--calendar-color", color);
    }
    const isHidden = state.hiddenCalendars.has(calendar.id);
    button.classList.toggle("is-hidden", isHidden);
    button.setAttribute("aria-pressed", isHidden ? "false" : "true");
    button.title = isHidden ? "Kliknij, żeby pokazać kalendarz" : "Kliknij, żeby ukryć kalendarz";

    const dot = document.createElement("span");
    dot.className = "events-calendar-dot";
    if (calendar.backgroundColor) dot.style.backgroundColor = calendar.backgroundColor;

    const label = document.createElement("span");
    label.textContent = calendar.summary || calendar.id;

    button.append(dot, label);
    calendarsBox.appendChild(button);
  });
}

function toggleCalendar(calendarId) {
  if (!calendarId) return;
  if (state.hiddenCalendars.has(calendarId)) {
    state.hiddenCalendars.delete(calendarId);
  } else {
    state.hiddenCalendars.add(calendarId);
  }
  saveHiddenCalendars(state.hiddenCalendars);
  renderCalendarFilters();
  render();
}

function createEventActionButton(event) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "events-edit-btn";
  button.dataset.eventsAction = "edit";
  button.dataset.eventId = event.id;
  button.setAttribute("aria-label", `Edytuj: ${event.title}`);
  button.title = "Edytuj";
  button.innerHTML = "&#9881;";
  return button;
}

function toggleEventDetails(eventId) {
  if (!eventId) return;
  if (state.expandedEvents.has(eventId)) {
    state.expandedEvents.delete(eventId);
  } else {
    state.expandedEvents.add(eventId);
  }
  render();
}

function isEditableEvent(event) {
  return (event?.external?.provider === "google_calendar" && event?.external?.canWrite !== false) || event?.type === "payday";
}

function ensureEditor() {
  let overlay = document.getElementById("events-editor-overlay");
  if (overlay) return overlay;

  overlay = document.createElement("div");
  overlay.className = "events-editor-overlay";
  overlay.id = "events-editor-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <form class="events-editor" id="events-editor-form">
      <header class="events-editor-head">
        <div>
          <div class="events-editor-kicker">Google Calendar</div>
          <h3>Edytuj datę</h3>
        </div>
        <button class="events-editor-close" type="button" data-events-editor-close aria-label="Zamknij">×</button>
      </header>
      <div class="events-editor-grid">
        <label>
          <span>Tytuł</span>
          <input class="events-editor-input" name="title" required maxlength="160" />
        </label>
        <label>
          <span>Data</span>
          <input class="events-editor-input" name="date" type="date" required />
        </label>
        <label>
          <span>Typ</span>
          <select class="events-editor-input" name="type"></select>
        </label>
        <label>
          <span>Status akcji</span>
          <input class="events-editor-input" name="actionStatus" maxlength="80" />
        </label>
        <label class="events-editor-check">
          <input name="isDayOff" type="checkbox" />
          <span>Dzień wolny</span>
        </label>
        <label class="events-editor-check">
          <input name="isShortDay" type="checkbox" />
          <span>Krótki dzień</span>
        </label>
        <label class="events-editor-check">
          <input name="countdown" type="checkbox" />
          <span>Odliczaj w countdownie</span>
        </label>
        <label>
          <span>Kategoria countdownu</span>
          <select class="events-editor-input" name="category"></select>
        </label>
        <label class="events-editor-wide">
          <span>Notatki</span>
          <textarea class="events-editor-input" name="notes" rows="4"></textarea>
        </label>
        <label class="events-editor-wide">
          <span>Action needed</span>
          <input class="events-editor-input" name="actionNeeded" maxlength="160" />
        </label>
      </div>
      <div class="events-editor-note" id="events-editor-note"></div>
      <footer class="events-editor-actions">
        <a class="events-editor-google" id="events-editor-google" href="#" target="_blank" rel="noopener" hidden>Otwórz w Google</a>
        <button class="events-editor-cancel" type="button" data-events-editor-close>Anuluj</button>
        <button class="events-editor-save" type="submit">Zapisz</button>
      </footer>
    </form>
  `;
  document.body.appendChild(overlay);

  const select = overlay.querySelector('select[name="type"]');
  typeOptions.forEach((option) => {
    const el = document.createElement("option");
    el.value = option.value;
    el.textContent = option.label;
    select.appendChild(el);
  });

  const categorySelect = overlay.querySelector('select[name="category"]');
  const emptyCategory = document.createElement("option");
  emptyCategory.value = "";
  emptyCategory.textContent = "Wybierz kategorię...";
  categorySelect.appendChild(emptyCategory);
  EVENT_COUNTDOWN_CATEGORIES.forEach((category) => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = EVENT_COUNTDOWN_CATEGORY_LABELS[category];
    categorySelect.appendChild(option);
  });

  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-events-editor-close]")) {
      closeEditor();
    }
  });
  overlay.querySelector("form").addEventListener("submit", handleEditorSubmit);
  select.addEventListener("change", () => syncTypeFlags(overlay.querySelector("form")));
  overlay.querySelector('input[name="countdown"]').addEventListener("change", () => syncCountdownCategory(overlay.querySelector("form")));
  return overlay;
}

function syncCountdownCategory(form) {
  const category = form?.elements.category;
  if (!category) return;
  category.required = Boolean(form.elements.countdown.checked);
}

function syncTypeFlags(form) {
  if (!form) return;
  if (form.elements.type.value === "public_holiday") {
    form.elements.isDayOff.checked = true;
  }
  if (form.elements.type.value === "short_day") {
    form.elements.isShortDay.checked = true;
  }
}

function openEditor(event) {
  if (!isEditableEvent(event)) return;
  const overlay = ensureEditor();
  const form = overlay.querySelector("form");
  state.editingEvent = event;
  form.elements.title.value = event.title || "";
  form.elements.date.value = event.date || "";
  form.elements.type.value = event.type || "custom";
  form.elements.isDayOff.checked = Boolean(event.isDayOff);
  form.elements.isShortDay.checked = Boolean(event.isShortDay);
  form.elements.countdown.checked = Boolean(event.countdown);
  form.elements.category.value = event.category || "";
  syncCountdownCategory(form);
  form.elements.notes.value = event.notes || "";
  form.elements.actionNeeded.value = event.actionNeeded || "";
  form.elements.actionStatus.value = event.actionStatus || "";

  const googleLink = overlay.querySelector("#events-editor-google");
  if (event.external?.htmlLink) {
    googleLink.href = event.external.htmlLink;
    googleLink.hidden = false;
  } else {
    googleLink.hidden = true;
  }

  const note = overlay.querySelector("#events-editor-note");
  note.textContent = event.external?.provider === "google_calendar"
    ? "Typ, wolne i status zapiszą się w dashboardzie. Tytuł, data albo notatki zmienią event w Google Calendar."
    : "To utworzy/zmieni tylko wypłatę w Google Calendar. Inne lokalne daty są zablokowane.";

  overlay.hidden = false;
  requestAnimationFrame(() => form.elements.title.focus());
}

function closeEditor() {
  const overlay = document.getElementById("events-editor-overlay");
  if (!overlay) return;
  overlay.hidden = true;
  state.editingEvent = null;
}

async function handleEditorSubmit(event) {
  event.preventDefault();
  if (state.saving || !state.editingEvent) return;

  const form = event.currentTarget;
  const save = form.querySelector(".events-editor-save");
  const note = document.getElementById("events-editor-note");
  if (form.elements.countdown.checked && !EVENT_COUNTDOWN_CATEGORIES.includes(form.elements.category.value)) {
    note.textContent = "Wybierz kategorię countdownu.";
    form.elements.category.focus();
    return;
  }
  const edited = {
    ...state.editingEvent,
    title: form.elements.title.value.trim(),
    date: form.elements.date.value,
    type: form.elements.type.value,
    isDayOff: form.elements.isDayOff.checked,
    isShortDay: form.elements.isShortDay.checked,
    notes: nullableText(form.elements.notes.value),
    actionNeeded: nullableText(form.elements.actionNeeded.value),
    actionStatus: nullableText(form.elements.actionStatus.value),
    countdown: form.elements.countdown.checked,
    category: form.elements.category.value || null,
  };

  state.saving = true;
  save.disabled = true;
  save.textContent = "Zapisuję...";
  note.textContent = "Zapisuję...";
  try {
    const original = state.editingEvent;
    const isGoogleEvent = original.external?.provider === "google_calendar" && original.external?.eventId;
    if (isGoogleEvent) {
      if (hasDashboardMetadataChanged(original, edited)) {
        note.textContent = "Zapisuję ustawienia dashboardu...";
        await saveEventDashboardOverride(edited);
      }
      if (hasGoogleCoreChanged(original, edited)) {
        note.textContent = "Zapisuję w Google Calendar...";
        await upsertGoogleCalendarEvent(edited);
      }
    } else {
      note.textContent = "Zapisuję w Google Calendar...";
      await upsertGoogleCalendarEvent(edited);
    }
    note.textContent = "Zapisane. Odświeżam listę...";
    await loadEvents();
    closeEditor();
  } catch (error) {
    note.textContent = `Błąd zapisu: ${error.message || error}`;
  } finally {
    state.saving = false;
    save.disabled = false;
    save.textContent = "Zapisz";
  }
}

function nullableText(value) {
  const clean = String(value || "").trim();
  return clean ? clean : null;
}

function comparableText(value) {
  return String(value || "").trim();
}

function hasDashboardMetadataChanged(before, after) {
  return before.type !== after.type
    || Boolean(before.isDayOff) !== Boolean(after.isDayOff)
    || Boolean(before.isShortDay) !== Boolean(after.isShortDay)
    || Boolean(before.countdown) !== Boolean(after.countdown)
    || comparableText(before.category) !== comparableText(after.category)
    || comparableText(before.actionNeeded) !== comparableText(after.actionNeeded)
    || comparableText(before.actionStatus) !== comparableText(after.actionStatus);
}

function hasGoogleCoreChanged(before, after) {
  return comparableText(before.title) !== comparableText(after.title)
    || comparableText(before.date) !== comparableText(after.date)
    || comparableText(before.notes) !== comparableText(after.notes);
}

function renderError(error) {
  state = {
    ...state,
    events: [],
    visibleEvents: [],
    google: error?.google || state.google || {},
    calendars: [],
    isCachedSnapshot: false,
    loadMs: null,
    loadedAt: null,
    refreshError: error?.message || String(error || "load failed"),
  };
  nearestBox.innerHTML = "";
  nearestBox.append(createGoogleErrorPanel(error));
  list.innerHTML = "";
  renderCalendarFilters();
  if (foot) foot.textContent = "Błąd Google Calendar · lokalne dane testowe są wyłączone";
}

function setMode(mode, options = {}) {
  if (options.render !== false) {
    document.dispatchEvent(new CustomEvent("dashboard:layout-transition", {
      detail: { anchor: card },
    }));
  }
  displayMode = VALID_MODES.has(mode) ? mode : "month";
  globalThis.localStorage?.setItem(STORAGE_KEY, displayMode);
  globalThis.localStorage?.removeItem(LEGACY_STORAGE_KEY);
  card.dataset.displayMode = displayMode;

  modeButtons.forEach((button) => {
    const isActive = button.dataset.eventsMode === displayMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });

  if (options.render !== false) render();
}

function getInitialMode() {
  const stored = globalThis.localStorage?.getItem(STORAGE_KEY);
  if (VALID_MODES.has(stored)) return stored;
  const fromDom = card?.dataset.displayMode;
  return VALID_MODES.has(fromDom) ? fromDom : "month";
}

function createTypeBadge(event) {
  const badge = document.createElement("span");
  badge.className = `evt-pill ${TYPE_CLASS[event.type] || "is-neutral"}`;
  applyEventAccent(badge, event);
  badge.textContent = TYPE_LABELS[event.type] || TYPE_LABELS.custom;
  return badge;
}

function createMetaChip(text) {
  const chip = document.createElement("span");
  chip.textContent = text;
  return chip;
}

function createEmpty(text) {
  const empty = document.createElement("div");
  empty.className = "events-empty";
  empty.textContent = text;
  return empty;
}

function createGoogleErrorPanel(error) {
  const google = error?.google || {};
  const needsReauth = isGoogleCalendarReauthRequired(error, google);
  const panel = document.createElement("div");
  panel.className = "events-empty events-error";

  const title = document.createElement("strong");
  title.textContent = "Nie udało się załadować danych z Google Calendar.";

  const message = document.createElement("div");
  message.textContent = explainGoogleCalendarError(error);

  const rows = document.createElement("dl");
  rows.className = "events-error-diagnostics";
  getGoogleDiagnosticRows(error, google).forEach(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    rows.append(term, detail);
  });

  const retryButton = document.createElement("button");
  retryButton.type = "button";
  retryButton.className = "events-error-action";
  retryButton.dataset.eventsAction = "retry-google";
  retryButton.textContent = "Ponów próbę";

  panel.append(title, message, retryButton);
  if (google.configured && (!google.connected || needsReauth)) {
    const link = document.createElement("a");
    link.className = "events-error-action";
    link.href = "/api/google-calendar/auth/start";
    link.textContent = needsReauth ? "Zaloguj ponownie do Google" : "Połącz Google Calendar";
    panel.appendChild(link);
  }
  panel.appendChild(rows);
  return panel;
}

function explainGoogleCalendarError(error) {
  const google = error?.google || {};
  if (isGoogleCalendarReauthRequired(error, google)) {
    return "Sesja Google wygasła albo token został cofnięty. Zaloguj się ponownie, żeby odświeżyć autoryzację.";
  }
  if (google.configured && !google.connected) {
    return "Konfiguracja OAuth istnieje, ale backend nie ma aktywnego połączenia z kontem Google.";
  }
  if (google.syncError) {
    return "Google Calendar zwrócił błąd podczas synchronizacji.";
  }
  if (google.configured === false) {
    return "Brakuje konfiguracji OAuth dla Google Calendar.";
  }
  return "Backend API wydarzeń nie zwrócił poprawnych danych z Google Calendar.";
}

function isGoogleCalendarReauthRequired(error, google = {}) {
  const text = [
    google.syncError,
    google.authError,
    error?.message,
    error?.details?.payload?.error,
    error?.details?.payload?.message,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return text.includes("invalid_grant")
    || text.includes("expired or revoked")
    || text.includes("token has been expired")
    || text.includes("invalid credentials")
    || text.includes("invalid_credentials")
    || text.includes("unauthorized")
    || text.includes("insufficient authentication scopes")
    || text.includes("insufficientpermissions")
    || text.includes("missing google refresh token")
    || text.includes("reconnect google calendar");
}

function getGoogleDiagnosticRows(error, google) {
  return [
    ["configured", formatBooleanDiagnostic(google.configured)],
    ["connected", formatBooleanDiagnostic(google.connected)],
    ["calendarIds", formatListDiagnostic(google.calendarIds)],
    ["cachedEvents", String(google.cachedEvents ?? "brak danych")],
    ["lastSyncAt", google.lastSyncAt || "brak"],
    ["calendarListSyncAt", google.calendarListSyncAt || "brak"],
    ["cacheUpdatedAt", google.cacheUpdatedAt || "brak"],
    ["redirectUri", google.redirectUri || "brak"],
    ["syncError", google.syncError || "brak"],
    ["partialSyncErrors", formatPartialSyncErrors(google.partialSyncErrors)],
    ["clientError", error?.message || String(error || "brak")],
  ];
}

function formatPartialSyncErrors(errors) {
  if (!Array.isArray(errors) || errors.length === 0) return "brak";
  return errors
    .map((item) => {
      if (!item || typeof item !== "object") return String(item || "");
      const label = item.calendarSummary || item.calendarId || "kalendarz";
      return `${label}: ${item.status || ""} ${item.error || ""}`.trim();
    })
    .join(" | ");
}

function formatBooleanDiagnostic(value) {
  if (value === true) return "true";
  if (value === false) return "false";
  return "brak danych";
}

function formatListDiagnostic(value) {
  if (!Array.isArray(value)) return "brak danych";
  return value.length ? value.join(", ") : "pusta lista";
}

function capitalize(text) {
  const value = String(text || "");
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

function formatFooterDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return date.toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatEventTime(event) {
  if (!event?.startTime) return "";
  return event.endTime ? `${event.startTime}-${event.endTime}` : event.startTime;
}

function loadHiddenCalendars() {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(HIDDEN_CALENDARS_KEY) || "[]");
    return new Set(Array.isArray(value) ? value.filter(Boolean) : []);
  } catch (error) {
    return new Set();
  }
}

function saveHiddenCalendars(value) {
  globalThis.localStorage?.setItem(HIDDEN_CALENDARS_KEY, JSON.stringify(Array.from(value)));
}

function filterEventsByDateView(events) {
  const today = startOfDay(new Date());
  const end = getDateViewEnd(today, displayMode);
  return events.filter((event) => {
    const eventDay = startOfDay(event.dateObj);
    return eventDay >= today && eventDay <= end;
  });
}

function getDateViewEnd(today, view) {
  const end = new Date(today);
  if (view === "today") return end;
  if (view === "week") {
    const daysUntilSunday = (7 - end.getDay()) % 7;
    end.setDate(end.getDate() + daysUntilSunday);
    return end;
  }
  if (view === "year") {
    return new Date(end.getFullYear(), 11, 31);
  }
  return new Date(end.getFullYear(), end.getMonth() + 1, 0);
}

function startOfDay(value) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function getEventCalendarFilterId(event) {
  if (event?.type === "task" || event?.external?.isTask) {
    return event?.external?.displayCalendarId || SYNTHETIC_TASKS_CALENDAR_ID;
  }
  return event?.external?.displayCalendarId || event?.external?.calendarId || "";
}

function getCalendarFilterOptions(calendars) {
  const options = (Array.isArray(calendars) ? calendars : []).filter((calendar) => calendar?.id);
  const byId = new Map(options.map((calendar) => [calendar.id, calendar]));
  const taskEvents = state.visibleEvents.filter((event) => event?.type === "task" || event?.external?.isTask);
  if (taskEvents.length) {
    const taskId = taskEvents.find((event) => event?.external?.displayCalendarId)?.external?.displayCalendarId
      || SYNTHETIC_TASKS_CALENDAR_ID;
    if (!byId.has(taskId)) {
      const taskColor = taskEvents.map((event) => event?.external?.calendarColor).find(isHexColor) || "#f6bf26";
      options.push({
        id: taskId,
        summary: "Tasks",
        backgroundColor: taskColor,
        foregroundColor: "#000000",
        accessRole: "reader",
        selected: true,
        synthetic: true,
      });
    }
  }
  return options;
}

function collapseBirthdaysByPerson(events) {
  const seen = new Set();
  return events.filter((event) => {
    const person = getBirthdayPerson(event);
    if (!person) return true;
    if (seen.has(person)) return false;
    seen.add(person);
    return true;
  });
}

function getBirthdayPerson(event) {
  const title = String(event?.title || "").trim();
  const calendar = String(event?.external?.calendarSummary || "").toLowerCase();
  const type = String(event?.type || "").toLowerCase();
  const titleLower = title.toLowerCase();
  const isBirthday =
    type === "birthday" ||
    calendar.includes("birthday") ||
    calendar.includes("urodzin") ||
    titleLower.includes("urodziny") ||
    titleLower.includes("birthday");
  if (!isBirthday) return "";
  return titleLower
    .replace(/\burodziny\b/g, "")
    .replace(/\bbirthday\b/g, "")
    .replace(/\burodziny:\b/g, "")
    .replace(/\s+/g, " ")
    .trim() || titleLower;
}

function dedupeDuplicateCalendarEvents(events) {
  const byKey = new Map();
  events.forEach((event) => {
    const key = getDuplicateEventKey(event);
    const current = byKey.get(key);
    if (!current || scoreDuplicateCandidate(event) > scoreDuplicateCandidate(current)) {
      byKey.set(key, event);
    }
  });
  return Array.from(byKey.values())
    .sort(compareEventsChronologically);
}

function getDuplicateEventKey(event) {
  const title = normalizeDuplicateTitle(event?.title);
  return `${event?.date || ""}:${title}`;
}

function normalizeDuplicateTitle(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function scoreDuplicateCandidate(event) {
  const calendarName = String(event?.external?.calendarSummary || "").toLowerCase();
  let score = 0;
  if (event?.external?.provider === "google_calendar") score += 10;
  if (event?.external?.calendarColor) score += 5;
  if (event?.external?.canWrite) score += 2;
  if (event?.type === "task" || event?.external?.isTask) score += 6;
  if (event?.notes && !String(event.notes).includes("Changes made to the title")) score += 2;
  if (calendarName.includes("task")) score += 4;
  if (calendarName === "calendar") score -= 4;
  if (calendarName.includes("holiday")) score -= 1;
  return score;
}

function applyEventAccent(element, event) {
  const color = getEventCalendarColor(event);
  if (!color) return;
  element.style.setProperty("--event-accent", color);
}

function getEventCalendarColor(event) {
  const color = String(event?.external?.calendarColor || "").trim();
  return isHexColor(color) ? color : "";
}

function isHexColor(color) {
  return /^#[0-9a-f]{6}$/i.test(String(color || "").trim());
}
