import {
  dateKey,
  habitLifetimeSummary,
  habitPeriodSummary,
  isHabitComplete,
  latestDatasetDate,
  normalizeHabitDataset,
  readPreviewMutations,
  recentDateKeys,
  reorderHabits,
  resolvedValue,
  shiftDateKey,
  upsertPreviewMutation,
  writePreviewMutations,
} from "./habits-app-model.js";
import {
  createHabit,
  fetchHabitsSnapshot,
  pollHabitChanges,
  pushHabitMutations,
  setHabitArchived,
  setHabitPositions,
  setHabitReminderConfig,
  saveReminderSettings,
  snapshotToHabits,
  updateReminderOccurrence,
} from "./habits-app-api.js";
import {
  getNextReminder,
  getReminderOccurrences,
  localDateKey,
  normalizeReminderConfig,
  scheduleLabel,
  validateReminderConfig,
} from "./habits-reminder-schedule.js";
import { ReminderExecutionService } from "./habits-reminder-execution.js";
import { createSupplementPanel } from "./supplement-panel.js";

const card = document.getElementById("habits-app-card");
const root = document.getElementById("habits-app-root");

if (card && root) {
  let habits = normalizeHabitDataset(window.HABIT_DB || {});
  let latestDate = latestDatasetDate(habits);
  const today = dateKey(new Date());
  let maxDate = latestDate > today ? latestDate : today;
  const state = {
    endDate: maxDate,
    filter: "all",
    query: "",
    selectedId: habits[0]?.id || "",
    mutations: readPreviewMutations(),
    cursor: null,
    apiReady: false,
    syncStatus: "connecting",
    syncMessage: "łączenie z API",
    heatmapPage: 0,
    reminderTimeGroups: [],
    reminderSettings: { browserNotificationsEnabled: false },
    reminderStates: [],
  };

  root.innerHTML = `
    <div class="habits-app-summary">
      <div class="habits-app-progress" id="habits-app-progress" aria-hidden="true"><span id="habits-app-progress-value">0%</span></div>
      <div class="habits-app-summary-copy">
        <strong id="habits-app-day-result">0 z 0</strong>
        <span id="habits-app-day-label">wykonanych</span>
      </div>
      <div class="habits-app-sync" role="status">
        <span class="habits-app-sync-dot" aria-hidden="true"></span>
        <span><strong id="habits-app-sync-title">Łączenie</strong><small id="habits-app-pending">łączenie z API</small></span>
      </div>
      <button class="habits-app-reset" id="habits-app-reset" type="button">Synchronizuj</button>
      <button class="habits-app-reminders-button" id="habits-app-reminders" type="button" aria-label="Open reminders">🔔 <span>Reminders</span></button>
      <button class="habits-app-manage-button" id="habits-app-manage" type="button">Zarządzaj</button>
    </div>
    <div class="habits-app-toolbar">
      <div class="habits-app-filters" role="group" aria-label="Filtr kategorii">
        <button type="button" class="is-active" data-habits-filter="all">Wszystkie</button>
        <button type="button" data-habits-filter="lifestyle">Nawyki</button>
        <button type="button" data-habits-filter="meds">Leki</button>
        <button type="button" data-habits-filter="supplements">Suplementy</button>
      </div>
      <button class="habits-app-add-button" id="habits-app-add" type="button">+ Dodaj nawyk / lek / suplement</button>
      <label class="habits-app-search">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.6"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
        <span class="sr-only">Szukaj nawyku</span>
        <input id="habits-app-search" type="search" placeholder="Szukaj nawyku" autocomplete="off" />
      </label>
      <div class="habits-app-date-nav">
        <button id="habits-app-prev" type="button" aria-label="Poprzedni tydzień">←</button>
        <button id="habits-app-today" type="button">Dzisiaj</button>
        <button id="habits-app-next" type="button" aria-label="Następny tydzień">→</button>
      </div>
    </div>
    <div class="habits-app-layout">
      <section class="habits-app-board" aria-label="Wpisy nawyków z siedmiu dni">
        <div class="habits-app-table-scroll">
          <div class="habits-app-table" id="habits-app-table"></div>
        </div>
        <div class="habits-app-board-foot"><span>Kliknij wpis binarny, aby przełączyć: brak → ✓ → ×</span><span>Wpis liczbowy otwiera edycję.</span></div>
      </section>
      <aside class="habits-app-detail" id="habits-app-detail" aria-live="polite"></aside>
    </div>
    <dialog class="habits-app-dialog" id="habits-app-dialog">
      <form method="dialog" id="habits-app-entry-form">
        <div class="habits-app-dialog-head">
          <div><strong id="habits-app-dialog-title">Wpis</strong><span id="habits-app-dialog-date"></span></div>
          <button value="cancel" aria-label="Zamknij" type="submit">×</button>
        </div>
        <label><span>Wartość</span><div class="habits-app-value-input"><input id="habits-app-value" type="text" inputmode="decimal" autocomplete="off" /><b id="habits-app-value-unit"></b></div></label>
        <div class="habits-app-dialog-actions">
          <button class="habits-app-dialog-clear" id="habits-app-entry-clear" type="button">Usuń wpis</button>
          <button class="habits-app-dialog-save" value="default" type="submit">Zapisz</button>
        </div>
      </form>
    </dialog>
    <dialog class="habits-app-dialog habits-app-add-dialog" id="habits-app-add-dialog">
      <form id="habits-app-add-form">
        <div class="habits-app-dialog-head">
          <div><strong>Dodaj nową pozycję</strong><span>Nawyk, lek lub suplement</span></div>
          <button id="habits-app-add-close" aria-label="Zamknij" type="button">×</button>
        </div>
        <label><span>Nazwa</span><input id="habits-app-add-name" type="text" maxlength="120" required autocomplete="off" /></label>
        <label><span>Kategoria</span><select id="habits-app-add-category"><option value="HABIT">Nawyk</option><option value="MEDICATION">Lek</option><option value="SUPPLEMENT">Suplement</option></select></label>
        <label><span>Jak śledzić?</span><select id="habits-app-add-type"><option value="BINARY">Wykonane / niewykonane</option><option value="NUMERIC">Wartość liczbowa</option></select></label>
        <div class="habits-app-add-numeric" id="habits-app-add-numeric" hidden>
          <label><span>Jednostka</span><input id="habits-app-add-unit" type="text" maxlength="24" placeholder="np. mg, g, szt." /></label>
          <label><span>Cel dzienny (opcjonalnie)</span><input id="habits-app-add-target" type="number" min="0" step="any" placeholder="np. 5" /></label>
        </div>
        <p class="habits-app-add-error" id="habits-app-add-error" role="alert" hidden></p>
        <div class="habits-app-dialog-actions"><span></span><button class="habits-app-dialog-save" id="habits-app-add-save" type="submit">Dodaj</button></div>
      </form>
    </dialog>
    <dialog class="habits-app-dialog habits-app-manage-dialog" id="habits-app-manage-dialog">
      <form method="dialog">
        <div class="habits-app-dialog-head">
          <div><strong>Zarządzaj nawykami</strong><span>Przeciągnij pozycję lub użyj strzałek. Ukrycie nie usuwa historii.</span></div>
          <button value="cancel" aria-label="Zamknij" type="submit">×</button>
        </div>
        <div class="habits-app-manage-list" id="habits-app-manage-list"></div>
      </form>
    </dialog>
    <dialog class="habits-app-dialog habits-reminder-dialog" id="habits-reminder-item-dialog">
      <form method="dialog" id="habits-reminder-item-form">
        <div class="habits-app-dialog-head"><div><strong id="habits-reminder-item-title">Reminders</strong><span>User-configured schedule</span></div><button value="cancel" aria-label="Close" type="submit">×</button></div>
        <label class="habits-reminder-toggle"><input id="habits-reminder-enabled" type="checkbox" /> <span>Enable reminders</span></label>
        <label><span>Schedule</span><select id="habits-reminder-schedule"><option value="daily">Every day</option><option value="weekdays">Selected weekdays</option><option value="interval_days">Every N days</option><option value="custom">Custom</option></select></label>
        <section class="habits-reminder-weekdays" id="habits-reminder-weekdays" hidden><span>Days</span><div id="habits-reminder-weekday-buttons"></div><div class="habits-reminder-presets"><button type="button" data-reminder-preset="all">Every day</button><button type="button" data-reminder-preset="weekdays">Weekdays</button><button type="button" data-reminder-preset="weekend">Weekend</button><button type="button" data-reminder-preset="clear">Clear</button></div></section>
        <section class="habits-reminder-interval" id="habits-reminder-interval" hidden><label><span>Repeat every</span><input id="habits-reminder-interval-days" type="number" min="1" max="365" value="2" /> days</label><label><span>Starting</span><input id="habits-reminder-anchor" type="date" /></label></section>
        <section class="habits-reminder-times"><strong>Times</strong><div id="habits-reminder-group-options"></div><div id="habits-reminder-custom-times"></div><div class="habits-reminder-add-time"><input id="habits-reminder-custom-time" type="time" /><button type="button" id="habits-reminder-add-custom">+ Custom time</button></div></section>
        <label><span>Snooze</span><select id="habits-reminder-snooze"><option value="10">10 minutes</option><option value="15">15 minutes</option><option value="30">30 minutes</option><option value="60">60 minutes</option></select></label>
        <label class="habits-reminder-toggle"><input id="habits-reminder-skip" type="checkbox" checked /> <span>Skip later reminders when today is completed</span></label>
        <p class="habits-reminder-error" id="habits-reminder-error" hidden></p>
        <div class="habits-app-dialog-actions"><span></span><button class="habits-app-dialog-save" value="save" type="submit">Save reminders</button></div>
      </form>
    </dialog>
    <dialog class="habits-app-dialog habits-reminder-panel-dialog" id="habits-reminder-panel-dialog">
      <form method="dialog"><div class="habits-app-dialog-head"><div><strong>Reminders</strong><span>Upcoming and recent schedule</span></div><button value="cancel" aria-label="Close" type="submit">×</button></div><div id="habits-reminder-panel"></div><div class="habits-app-dialog-actions"><button type="button" id="habits-reminder-open-settings">Time groups & settings</button><button class="habits-app-dialog-save" value="cancel" type="submit">Done</button></div></form>
    </dialog>
    <dialog class="habits-app-dialog habits-reminder-settings-dialog" id="habits-reminder-settings-dialog">
      <form method="dialog" id="habits-reminder-settings-form"><div class="habits-app-dialog-head"><div><strong>Reminder settings</strong><span>Global local-time groups</span></div><button value="cancel" aria-label="Close" type="submit">×</button></div><label class="habits-reminder-toggle"><input id="habits-reminder-browser-enabled" type="checkbox" /> <span>Browser notifications</span></label><p class="habits-reminder-permission" id="habits-reminder-permission"></p><section class="habits-reminder-time-settings"><strong>Time groups</strong><div id="habits-reminder-time-groups"></div><button type="button" id="habits-reminder-add-group">+ Add time group</button></section><p class="habits-reminder-error" id="habits-reminder-settings-error" hidden></p><div class="habits-app-dialog-actions"><span></span><button class="habits-app-dialog-save" value="save" type="submit">Save settings</button></div></form>
    </dialog>
    <dialog class="habits-app-dialog habits-reminder-delete-dialog" id="habits-reminder-delete-dialog"><form method="dialog"><div class="habits-app-dialog-head"><div><strong>Time group is in use</strong><span id="habits-reminder-delete-message"></span></div><button value="cancel" aria-label="Close" type="submit">×</button></div><label><span>Replace references with</span><select id="habits-reminder-delete-replacement"></select></label><div class="habits-app-dialog-actions"><button value="remove" type="submit">Remove references</button><button class="habits-app-dialog-save" value="replace" type="submit">Replace references</button></div></form></dialog>
    <div class="habits-reminder-toast-stack" id="habits-reminder-toast-stack" aria-live="assertive"></div>
  `;

  const table = document.getElementById("habits-app-table");
  const detail = document.getElementById("habits-app-detail");
  const progress = document.getElementById("habits-app-progress");
  const progressValue = document.getElementById("habits-app-progress-value");
  const dayResult = document.getElementById("habits-app-day-result");
  const dayLabel = document.getElementById("habits-app-day-label");
  const syncTitle = document.getElementById("habits-app-sync-title");
  const pending = document.getElementById("habits-app-pending");
  const resetButton = document.getElementById("habits-app-reset");
  const addButton = document.getElementById("habits-app-add");
  const addDialog = document.getElementById("habits-app-add-dialog");
  const addForm = document.getElementById("habits-app-add-form");
  const addName = document.getElementById("habits-app-add-name");
  const addCategory = document.getElementById("habits-app-add-category");
  const addType = document.getElementById("habits-app-add-type");
  const addNumeric = document.getElementById("habits-app-add-numeric");
  const addUnit = document.getElementById("habits-app-add-unit");
  const addTarget = document.getElementById("habits-app-add-target");
  const addError = document.getElementById("habits-app-add-error");
  const addSave = document.getElementById("habits-app-add-save");
  const manageButton = document.getElementById("habits-app-manage");
  const manageDialog = document.getElementById("habits-app-manage-dialog");
  const manageList = document.getElementById("habits-app-manage-list");
  const remindersButton = document.getElementById("habits-app-reminders");
  const reminderItemDialog = document.getElementById("habits-reminder-item-dialog");
  const reminderItemForm = document.getElementById("habits-reminder-item-form");
  const reminderItemTitle = document.getElementById("habits-reminder-item-title");
  const reminderEnabled = document.getElementById("habits-reminder-enabled");
  const reminderSchedule = document.getElementById("habits-reminder-schedule");
  const reminderWeekdays = document.getElementById("habits-reminder-weekdays");
  const reminderWeekdayButtons = document.getElementById("habits-reminder-weekday-buttons");
  const reminderInterval = document.getElementById("habits-reminder-interval");
  const reminderIntervalDays = document.getElementById("habits-reminder-interval-days");
  const reminderAnchor = document.getElementById("habits-reminder-anchor");
  const reminderGroupOptions = document.getElementById("habits-reminder-group-options");
  const reminderCustomTimes = document.getElementById("habits-reminder-custom-times");
  const reminderCustomTime = document.getElementById("habits-reminder-custom-time");
  const reminderAddCustom = document.getElementById("habits-reminder-add-custom");
  const reminderSnooze = document.getElementById("habits-reminder-snooze");
  const reminderSkip = document.getElementById("habits-reminder-skip");
  const reminderError = document.getElementById("habits-reminder-error");
  const reminderPanelDialog = document.getElementById("habits-reminder-panel-dialog");
  const reminderPanel = document.getElementById("habits-reminder-panel");
  const reminderOpenSettings = document.getElementById("habits-reminder-open-settings");
  const reminderSettingsDialog = document.getElementById("habits-reminder-settings-dialog");
  const reminderSettingsForm = document.getElementById("habits-reminder-settings-form");
  const reminderBrowserEnabled = document.getElementById("habits-reminder-browser-enabled");
  const reminderPermission = document.getElementById("habits-reminder-permission");
  const reminderTimeGroups = document.getElementById("habits-reminder-time-groups");
  const reminderAddGroup = document.getElementById("habits-reminder-add-group");
  const reminderSettingsError = document.getElementById("habits-reminder-settings-error");
  const reminderDeleteDialog = document.getElementById("habits-reminder-delete-dialog");
  const reminderDeleteMessage = document.getElementById("habits-reminder-delete-message");
  const reminderDeleteReplacement = document.getElementById("habits-reminder-delete-replacement");
  const reminderToastStack = document.getElementById("habits-reminder-toast-stack");
  const search = document.getElementById("habits-app-search");
  const previousButton = document.getElementById("habits-app-prev");
  const todayButton = document.getElementById("habits-app-today");
  const nextButton = document.getElementById("habits-app-next");
  const dialog = document.getElementById("habits-app-dialog");
  const entryForm = document.getElementById("habits-app-entry-form");
  const dialogTitle = document.getElementById("habits-app-dialog-title");
  const dialogDate = document.getElementById("habits-app-dialog-date");
  const valueInput = document.getElementById("habits-app-value");
  const valueUnit = document.getElementById("habits-app-value-unit");
  const entryClear = document.getElementById("habits-app-entry-clear");
  let editing = null;
  let syncPromise = null;
  let pollPromise = null;
  let orderPromise = null;
  let draggedHabitId = "";
  let reminderEditingHabit = null;
  let reminderDraftCustomTimes = [];
  let reminderSettingsDraft = [];
  let reminderDeletedGroupResolutions = {};
  let pendingDeletedGroup = null;

  const categoryLabels = {
    lifestyle: "Nawyk",
    meds: "Lek",
    supplements: "Suplement",
    other: "Inne",
  };

  const activeHabits = () => habits.filter((habit) => !habit.archived);

  function formatDay(key, options = {}) {
    return new Intl.DateTimeFormat("pl-PL", {
      timeZone: "UTC",
      weekday: options.weekday ? "short" : undefined,
      day: "numeric",
      month: options.month ? "short" : undefined,
    }).format(new Date(`${key}T12:00:00Z`));
  }

  function formatValue(habit, value) {
    if (value === null || value === undefined) return "";
    if (habit.type === "binary") return Number(value) > 0 ? "✓" : "×";
    const number = Number(value);
    const display = Number.isInteger(number)
      ? number.toLocaleString("pl-PL")
      : number.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
    return display;
  }

  function mutationFor(habit, key, value, takenAt = null) {
    state.mutations = upsertPreviewMutation(state.mutations, {
      habitId: habit.id,
      habitName: habit.name,
      date: key,
      value,
      takenAt,
    });
    writePreviewMutations(state.mutations);
    return queueSync();
  }

  function applySnapshot(snapshot) {
    const selectedName = habits.find((item) => item.id === state.selectedId)?.name;
    habits = snapshotToHabits(snapshot);
    state.cursor = snapshot.cursor;
    state.reminderTimeGroups = Array.isArray(snapshot.reminderTimeGroups) ? snapshot.reminderTimeGroups : [];
    state.reminderSettings = snapshot.reminderSettings || { browserNotificationsEnabled: false };
    state.reminderStates = Array.isArray(snapshot.reminderStates) ? snapshot.reminderStates : [];
    state.apiReady = true;
    latestDate = latestDatasetDate(habits);
    maxDate = latestDate > today ? latestDate : today;
    const active = activeHabits();
    state.selectedId = active.find((item) => item.name === selectedName)?.id || active[0]?.id || "";
    const liveData = { habits, cursor: state.cursor };
    window.HABITS_APP_LIVE_DATA = liveData;
    document.dispatchEvent(new CustomEvent("habits-app:data-updated", { detail: liveData }));
  }

  async function refreshFromApi() {
    const snapshot = await fetchHabitsSnapshot();
    applySnapshot(snapshot);
    state.syncStatus = "online";
    state.syncMessage = "dane aktualne";
    render();
  }

  async function pollForRemoteChanges() {
    if (!state.apiReady || syncPromise || orderPromise || pollPromise || document.hidden) return;
    pollPromise = (async () => {
      const previousCursor = state.cursor;
      const response = await pollHabitChanges(previousCursor);
      const changed = (response.changes || []).length > 0
        || (response.nextCursor && response.nextCursor !== previousCursor);
      if (changed) {
        await refreshFromApi();
        state.syncMessage = "zaktualizowano z telefonu";
        render();
      } else {
        state.syncStatus = "online";
      }
    })().catch((error) => {
      state.syncStatus = "offline";
      state.syncMessage = error?.message || "brak połączenia z API";
      renderHeader(recentDateKeys(state.endDate, 7));
    }).finally(() => {
      pollPromise = null;
    });
    return pollPromise;
  }

  function queueSync() {
    if (syncPromise) return syncPromise;
    syncPromise = (async () => {
      state.syncStatus = "syncing";
      state.syncMessage = "synchronizacja…";
      renderHeader(recentDateKeys(state.endDate, 7));
      if (!state.apiReady) await refreshFromApi();
      while (state.mutations.length) {
        const sending = [...state.mutations];
        const response = await pushHabitMutations(sending, habits, state.cursor);
        const completed = new Set([
          ...(response.acknowledgedMutationIds || []),
          ...(response.conflicts || []).map((item) => item.mutationId),
        ]);
        if (!completed.size) throw new Error("Serwer nie potwierdził zmian");
        state.mutations = state.mutations.filter((item) => !completed.has(item.mutationId));
        writePreviewMutations(state.mutations);
        if (response.conflicts?.length) state.syncMessage = `${response.conflicts.length} konflikt rozwiązany danymi serwera`;
        await refreshFromApi();
      }
      state.syncStatus = "online";
      state.syncMessage = "zsynchronizowano";
    })().catch((error) => {
      state.syncStatus = "offline";
      state.syncMessage = error?.message || "brak połączenia z API";
    }).finally(() => {
      syncPromise = null;
      render();
    });
    return syncPromise;
  }

  async function changeHabitVisibility(habit, active, control) {
    control.disabled = true;
    state.syncStatus = "syncing";
    state.syncMessage = active ? "aktywowanie nawyku…" : "ukrywanie nawyku…";
    renderHeader(recentDateKeys(state.endDate, 7));
    try {
      const response = await setHabitArchived(habit, !active, state.cursor);
      const accepted = (response.acknowledgedMutationIds || []).length > 0;
      if (!accepted && !(response.conflicts || []).length) throw new Error("Serwer nie potwierdził zmiany");
      await refreshFromApi();
      state.syncMessage = (response.conflicts || []).length
        ? "stan odświeżony po konflikcie"
        : active ? "nawyk aktywowany" : "nawyk ukryty, historia zachowana";
      render();
    } catch (error) {
      state.syncStatus = "offline";
      state.syncMessage = error?.message || "nie udało się zmienić widoczności";
      render();
    } finally {
      control.disabled = false;
      renderManageList();
    }
  }

  function clearDragMarkers() {
    root.querySelectorAll(".is-dragging, .is-drop-before, .is-drop-after").forEach((node) => {
      node.classList.remove("is-dragging", "is-drop-before", "is-drop-after");
    });
  }

  function dropAfter(node, event) {
    const bounds = node.getBoundingClientRect();
    return event.clientY > bounds.top + (bounds.height / 2);
  }

  function wireHabitDropTarget(node, habit) {
    node.dataset.habitId = String(habit.id);
    node.addEventListener("dragover", (event) => {
      if (!draggedHabitId || draggedHabitId === String(habit.id) || orderPromise) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      const placeAfter = dropAfter(node, event);
      node.classList.toggle("is-drop-before", !placeAfter);
      node.classList.toggle("is-drop-after", placeAfter);
    });
    node.addEventListener("dragleave", (event) => {
      if (!node.contains(event.relatedTarget)) node.classList.remove("is-drop-before", "is-drop-after");
    });
    node.addEventListener("drop", (event) => {
      event.preventDefault();
      const sourceId = draggedHabitId || event.dataTransfer?.getData("text/plain") || "";
      const placeAfter = dropAfter(node, event);
      clearDragMarkers();
      draggedHabitId = "";
      moveHabit(sourceId, habit.id, placeAfter);
    });
  }

  function wireHabitDragSource(node, habit) {
    node.draggable = state.apiReady && !orderPromise;
    node.addEventListener("dragstart", (event) => {
      if (!state.apiReady || orderPromise) {
        event.preventDefault();
        return;
      }
      draggedHabitId = String(habit.id);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", draggedHabitId);
      }
      node.classList.add("is-dragging");
    });
    node.addEventListener("dragend", () => {
      draggedHabitId = "";
      clearDragMarkers();
    });
  }

  function moveHabit(draggedId, targetId, placeAfter = false) {
    if (!state.apiReady || orderPromise || !draggedId || String(draggedId) === String(targetId)) return;
    const previousHabits = habits;
    const reordered = reorderHabits(habits, draggedId, targetId, placeAfter);
    const positions = new Map(previousHabits.map((habit) => [String(habit.id), habit.position]));
    const changed = reordered.filter((habit) => positions.get(String(habit.id)) !== habit.position);
    if (!changed.length) return;

    habits = reordered;
    state.syncStatus = "syncing";
    state.syncMessage = "zapisywanie kolejności…";
    orderPromise = Promise.resolve().then(async () => {
      const response = await setHabitPositions(changed, state.cursor);
      const completedCount = (response.acknowledgedMutationIds || []).length + (response.conflicts || []).length;
      if (completedCount < changed.length) throw new Error("Serwer nie potwierdził kolejności");
      await refreshFromApi();
      state.syncMessage = (response.conflicts || []).length
        ? "kolejność odświeżona po konflikcie"
        : "kolejność zapisana w aplikacji";
    }).catch((error) => {
      habits = previousHabits;
      state.syncStatus = "offline";
      state.syncMessage = error?.message || "nie udało się zapisać kolejności";
    }).finally(() => {
      orderPromise = null;
      render();
    });
    render();
    return orderPromise;
  }

  function renderManageList() {
    manageList.replaceChildren();
    habits.forEach((habit, index) => {
      const row = document.createElement("div");
      row.className = "habits-app-manage-row";
      row.style.setProperty("--habit-color", habit.color);
      wireHabitDropTarget(row, habit);
      const handle = document.createElement("button");
      handle.type = "button";
      handle.className = "habits-app-drag-handle";
      handle.textContent = "⋮⋮";
      handle.setAttribute("aria-label", `Przeciągnij ${habit.name}`);
      wireHabitDragSource(handle, habit);
      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = habit.name;
      const meta = document.createElement("small");
      meta.textContent = `${categoryLabels[habit.category]} · ${habit.archived ? "nieaktywny" : "aktywny"}`;
      copy.append(name, meta);
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = !habit.archived;
      toggle.setAttribute("aria-label", `${habit.archived ? "Aktywuj" : "Dezaktywuj"} ${habit.name}`);
      toggle.addEventListener("change", () => changeHabitVisibility(habit, toggle.checked, toggle));
      const actions = document.createElement("span");
      actions.className = "habits-app-manage-actions";
      const reminderButton = document.createElement("button");
      reminderButton.type = "button";
      reminderButton.className = "habits-app-manage-reminder";
      reminderButton.textContent = habit.reminderConfig?.enabled ? "🔔" : "Bell";
      reminderButton.setAttribute("aria-label", `Edit reminders: ${habit.name}`);
      reminderButton.addEventListener("click", () => openReminderEditor(habit));
      actions.appendChild(reminderButton);
      [-1, 1].forEach((direction) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = direction < 0 ? "↑" : "↓";
        button.disabled = Boolean(orderPromise) || index + direction < 0 || index + direction >= habits.length;
        button.setAttribute("aria-label", `${direction < 0 ? "Przesuń wyżej" : "Przesuń niżej"}: ${habit.name}`);
        button.addEventListener("click", () => {
          const target = habits[index + direction];
          if (target) moveHabit(habit.id, target.id, direction > 0);
        });
        actions.appendChild(button);
      });
      actions.appendChild(toggle);
      row.append(handle, copy, actions);
      manageList.appendChild(row);
    });
  }

  function selectHabit(habit) {
    state.selectedId = habit.id;
    render();
  }

  function toggleBinary(habit, key) {
    const current = resolvedValue(habit, key, state.mutations);
    const next = current === null ? 2 : Number(current) > 0 ? 0 : null;
    mutationFor(habit, key, next);
    state.selectedId = habit.id;
    render();
  }

  function openNumericEditor(habit, key, occurrence = null) {
    editing = { habit, key, occurrence };
    const current = resolvedValue(habit, key, state.mutations);
    dialogTitle.textContent = habit.name;
    dialogDate.textContent = formatDay(key, { weekday: true, month: true });
    valueInput.value = current === null
      ? (habit.name === "Creatine" && key >= "2026-09-29" ? "5" : "")
      : String(current).replace(".", ",");
    valueUnit.textContent = habit.unit;
    dialog.showModal();
    requestAnimationFrame(() => valueInput.select());
  }

  function reminderDescription(habit) {
    const config = normalizeReminderConfig(habit.reminderConfig);
    const lines = [habit.name, "", scheduleLabel(config)];
    if (config.scheduleType === "interval_days") {
      const next = getNextReminder(habit, new Date(), state.reminderTimeGroups);
      if (next) lines.push(`Next scheduled day: ${next.localDate}`);
    }
    getReminderOccurrences(habit, localDateKey(), state.reminderTimeGroups).forEach((occurrence) => {
      lines.push(`${occurrence.label} ${occurrence.localTime}`);
    });
    if (lines.length === 3) {
      config.timeGroupIds.forEach((id) => {
        const group = state.reminderTimeGroups.find((item) => item.id === id);
        if (group) lines.push(`${group.name} ${group.localTime}`);
      });
      config.customTimes.forEach((time) => lines.push(`Custom ${time}`));
    }
    return lines.join("\n");
  }

  function renderReminderScheduleFields() {
    const usesWeekdays = reminderSchedule.value === "weekdays" || reminderSchedule.value === "custom";
    reminderWeekdays.hidden = !usesWeekdays;
    reminderInterval.hidden = reminderSchedule.value !== "interval_days";
  }

  function selectedReminderWeekdays() {
    return [...reminderWeekdayButtons.querySelectorAll("button.is-selected")]
      .map((button) => Number(button.dataset.weekday));
  }

  function setReminderWeekdays(days) {
    const selected = new Set(days);
    reminderWeekdayButtons.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("is-selected", selected.has(Number(button.dataset.weekday)));
    });
  }

  function renderReminderCustomTimes() {
    reminderCustomTimes.replaceChildren();
    reminderDraftCustomTimes.forEach((time) => {
      const chip = document.createElement("span");
      chip.textContent = time;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove custom time ${time}`);
      remove.addEventListener("click", () => {
        reminderDraftCustomTimes = reminderDraftCustomTimes.filter((value) => value !== time);
        renderReminderCustomTimes();
      });
      chip.appendChild(remove);
      reminderCustomTimes.appendChild(chip);
    });
  }

  function renderReminderGroupOptions(selectedIds = []) {
    const selected = new Set(selectedIds);
    reminderGroupOptions.replaceChildren();
    state.reminderTimeGroups.forEach((group) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = group.id;
      input.checked = selected.has(group.id);
      const name = document.createElement("span");
      name.textContent = group.name;
      const time = document.createElement("time");
      time.textContent = group.localTime;
      label.append(input, name, time);
      reminderGroupOptions.appendChild(label);
    });
  }

  function openReminderEditor(habit) {
    reminderEditingHabit = habit;
    const config = normalizeReminderConfig(habit.reminderConfig);
    reminderItemTitle.textContent = habit.name;
    reminderEnabled.checked = config.enabled;
    reminderSchedule.value = config.scheduleType;
    reminderIntervalDays.value = String(config.intervalDays || 2);
    reminderAnchor.value = config.intervalAnchorDate || localDateKey();
    reminderSnooze.value = String(config.snoozeMinutes || 10);
    reminderSkip.checked = config.skipIfCompleted;
    reminderDraftCustomTimes = [...config.customTimes];
    reminderError.hidden = true;
    reminderWeekdayButtons.replaceChildren();
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((label, day) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.weekday = String(day);
      button.textContent = label;
      button.classList.toggle("is-selected", config.selectedWeekdays.includes(day));
      button.addEventListener("click", () => button.classList.toggle("is-selected"));
      reminderWeekdayButtons.appendChild(button);
    });
    renderReminderGroupOptions(config.timeGroupIds);
    renderReminderCustomTimes();
    renderReminderScheduleFields();
    reminderItemDialog.showModal();
  }

  async function saveItemReminder() {
    const config = normalizeReminderConfig({
      enabled: reminderEnabled.checked,
      scheduleType: reminderSchedule.value,
      selectedWeekdays: selectedReminderWeekdays(),
      intervalDays: Number(reminderIntervalDays.value),
      intervalAnchorDate: reminderAnchor.value || null,
      timeGroupIds: [...reminderGroupOptions.querySelectorAll("input:checked")].map((input) => input.value),
      customTimes: reminderDraftCustomTimes,
      snoozeMinutes: Number(reminderSnooze.value),
      skipIfCompleted: reminderSkip.checked,
      completionPolicy: "day",
    });
    const errors = validateReminderConfig(config, state.reminderTimeGroups);
    if (errors.length) {
      reminderError.textContent = errors.join(" ");
      reminderError.hidden = false;
      return false;
    }
    reminderError.hidden = true;
    const response = await setHabitReminderConfig(reminderEditingHabit, config, state.cursor);
    if (!(response.acknowledgedMutationIds || []).length && !(response.conflicts || []).length) {
      throw new Error("The server did not confirm the reminder configuration.");
    }
    await refreshFromApi();
    return true;
  }

  function notificationPermissionLabel() {
    if (typeof Notification === "undefined") return "Browser notifications are unsupported. Dashboard reminders remain active.";
    if (Notification.permission === "granted") return "Permission granted: browser and dashboard reminders are available.";
    if (Notification.permission === "denied") return "Permission denied: dashboard reminders will still appear.";
    return "Permission has not been requested. It is requested only when you enable this option.";
  }

  function groupReferenceCount(groupId) {
    return habits.filter((habit) => habit.reminderConfig?.timeGroupIds?.includes(groupId)).length;
  }

  function renderReminderSettingsDraft() {
    reminderTimeGroups.replaceChildren();
    reminderSettingsDraft.forEach((group) => {
      const row = document.createElement("div");
      row.className = "habits-reminder-time-group-row";
      const name = document.createElement("input");
      name.value = group.name;
      name.setAttribute("aria-label", `Name for ${group.id}`);
      name.addEventListener("input", () => { group.name = name.value; });
      const time = document.createElement("input");
      time.type = "time";
      time.value = group.localTime;
      time.addEventListener("input", () => { group.localTime = time.value; });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete";
      remove.addEventListener("click", () => requestTimeGroupDeletion(group));
      row.append(name, time, remove);
      reminderTimeGroups.appendChild(row);
    });
  }

  function openReminderSettings() {
    reminderSettingsDraft = state.reminderTimeGroups.map((group) => ({ ...group }));
    reminderDeletedGroupResolutions = {};
    reminderBrowserEnabled.checked = Boolean(state.reminderSettings.browserNotificationsEnabled)
      && typeof Notification !== "undefined" && Notification.permission === "granted";
    reminderPermission.textContent = notificationPermissionLabel();
    reminderSettingsError.hidden = true;
    renderReminderSettingsDraft();
    reminderSettingsDialog.showModal();
  }

  function requestTimeGroupDeletion(group) {
    const references = groupReferenceCount(group.id);
    if (!references) {
      reminderSettingsDraft = reminderSettingsDraft.filter((item) => item.id !== group.id);
      reminderDeletedGroupResolutions[group.id] = null;
      renderReminderSettingsDraft();
      return;
    }
    pendingDeletedGroup = group;
    reminderDeleteMessage.textContent = `${group.name} is used by ${references} tracker item${references === 1 ? "" : "s"}.`;
    reminderDeleteReplacement.replaceChildren();
    reminderSettingsDraft.filter((item) => item.id !== group.id).forEach((candidate) => {
      const option = document.createElement("option");
      option.value = candidate.id;
      option.textContent = `${candidate.name} · ${candidate.localTime}`;
      reminderDeleteReplacement.appendChild(option);
    });
    reminderDeleteDialog.returnValue = "";
    reminderDeleteDialog.showModal();
  }

  function finishTimeGroupDeletion(replacement) {
    if (!pendingDeletedGroup) return;
    reminderDeletedGroupResolutions[pendingDeletedGroup.id] = replacement;
    reminderSettingsDraft = reminderSettingsDraft.filter((item) => item.id !== pendingDeletedGroup.id);
    pendingDeletedGroup = null;
    renderReminderSettingsDraft();
  }

  function newTimeGroupId() {
    let suffix = 1;
    const used = new Set(reminderSettingsDraft.map((group) => group.id));
    while (used.has(`time-${suffix}`)) suffix += 1;
    return `time-${suffix}`;
  }

  async function saveGlobalReminderSettings() {
    const invalid = reminderSettingsDraft.find((group) => !group.name.trim() || !/^\d{2}:\d{2}$/.test(group.localTime));
    if (invalid) throw new Error("Every time group needs a name and valid local time.");
    await saveReminderSettings({
      timeGroups: reminderSettingsDraft,
      browserNotificationsEnabled: reminderBrowserEnabled.checked,
      deletedGroupResolutions: reminderDeletedGroupResolutions,
    });
    await refreshFromApi();
  }

  function updateReminderState(nextState) {
    state.reminderStates = [nextState, ...state.reminderStates.filter((item) => item.occurrenceKey !== nextState.occurrenceKey)];
  }

  async function claimReminderOccurrence(occurrence) {
    const result = await updateReminderOccurrence("claim", occurrence);
    if (result.state) updateReminderState(result.state);
    return result;
  }

  async function changeReminderOccurrence(action, occurrence, extra = {}) {
    const result = await updateReminderOccurrence(action, occurrence, extra);
    if (result.state) updateReminderState(result.state);
    renderReminderPanel();
    return result;
  }

  function reminderCompleteOnDate(habit, key) {
    return isHabitComplete(habit, resolvedValue(habit, key, state.mutations));
  }

  async function markReminderTaken(habit, occurrence) {
    if (habit.type === "binary") {
      mutationFor(habit, occurrence.localDate, 2);
    } else if (Number.isFinite(habit.target) && habit.target > 0) {
      mutationFor(habit, occurrence.localDate, habit.target);
    } else {
      openNumericEditor(habit, occurrence.localDate, occurrence);
      return;
    }
    await changeReminderOccurrence("satisfied", occurrence);
    render();
  }

  function showReminderNotification(occurrence) {
    const habit = habits.find((item) => String(item.id) === String(occurrence.habitId));
    if (!habit) return;
    if (state.reminderSettings.browserNotificationsEnabled
      && typeof Notification !== "undefined" && Notification.permission === "granted") {
      try {
        new Notification(habit.name, { body: `Scheduled reminder · ${occurrence.label} · ${occurrence.localTime}`, tag: occurrence.occurrenceKey });
      } catch {
        // Dashboard toast below remains the reliable in-page fallback.
      }
    }
    const toast = document.createElement("article");
    toast.className = "habits-reminder-toast";
    const title = document.createElement("strong");
    title.textContent = habit.name;
    const meta = document.createElement("span");
    meta.textContent = `Scheduled reminder · ${occurrence.label} · ${occurrence.localTime}`;
    const actions = document.createElement("div");
    const taken = document.createElement("button");
    taken.type = "button";
    taken.textContent = "Mark as taken";
    taken.addEventListener("click", () => markReminderTaken(habit, occurrence).then(() => toast.remove()));
    const snooze = document.createElement("button");
    snooze.type = "button";
    snooze.textContent = "Snooze";
    snooze.addEventListener("click", () => {
      const minutes = Number(habit.reminderConfig?.snoozeMinutes || 10);
      const snoozedUntil = new Date(Date.now() + minutes * 60_000).toISOString();
      changeReminderOccurrence("snooze", occurrence, { snoozedUntil }).then(() => toast.remove());
    });
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => changeReminderOccurrence("dismiss", occurrence).then(() => toast.remove()));
    actions.append(taken, snooze, dismiss);
    toast.append(title, meta, actions);
    reminderToastStack.appendChild(toast);
  }

  function reminderPanelItem(occurrence, detail = "") {
    const row = document.createElement("div");
    row.className = "habits-reminder-panel-item";
    const time = document.createElement("time");
    time.textContent = occurrence.localTime || new Date(occurrence.snoozedUntil).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const copy = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = occurrence.habitName || habits.find((habit) => habit.id === occurrence.habitId)?.name || "Tracker item";
    const meta = document.createElement("small");
    meta.textContent = detail || `${occurrence.localDate} · ${occurrence.label || occurrence.sourceKey}`;
    copy.append(name, meta);
    row.append(time, copy);
    return row;
  }

  function appendReminderPanelSection(title, items) {
    const section = document.createElement("section");
    const heading = document.createElement("strong");
    heading.textContent = title;
    section.appendChild(heading);
    if (!items.length) {
      const empty = document.createElement("p");
      empty.textContent = "None";
      section.appendChild(empty);
    } else items.forEach((item) => section.appendChild(reminderPanelItem(item.occurrence || item, item.detail)));
    reminderPanel.appendChild(section);
  }

  function renderReminderPanel() {
    reminderPanel.replaceChildren();
    const now = new Date();
    const todayKey = localDateKey(now);
    const enabled = activeHabits().filter((habit) => habit.reminderConfig?.enabled);
    const upcoming = enabled.map((habit) => getNextReminder(habit, now, state.reminderTimeGroups)).filter(Boolean)
      .sort((a, b) => a.scheduledAt - b.scheduledAt).slice(0, 6);
    const later = enabled.flatMap((habit) => getReminderOccurrences(habit, todayKey, state.reminderTimeGroups))
      .filter((occurrence) => occurrence.scheduledAt > now)
      .sort((a, b) => a.scheduledAt - b.scheduledAt);
    const snoozed = state.reminderStates.filter((item) => item.status === "snoozed").map((item) => ({
      ...item,
      habitName: habits.find((habit) => habit.id === item.habitId)?.name,
      localTime: item.snoozedUntil ? new Date(item.snoozedUntil).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : item.scheduledLocalTime,
    }));
    const satisfied = enabled.filter((habit) => reminderCompleteOnDate(habit, todayKey)).map((habit) => ({
      occurrence: { habitName: habit.name, localTime: "✓", localDate: todayKey, label: "Completed" },
      detail: "Today's entry satisfies later reminders",
    }));
    appendReminderPanelSection("Next", upcoming.map((occurrence) => ({ occurrence, detail: `${occurrence.localDate} · ${occurrence.label}` })));
    appendReminderPanelSection("Later today", later.map((occurrence) => ({ occurrence, detail: occurrence.label })));
    appendReminderPanelSection("Snoozed", snoozed);
    appendReminderPanelSection("Completed / satisfied", satisfied);
  }

  function renderHeader(days) {
    const key = days[days.length - 1];
    const active = activeHabits();
    const completed = active.filter((habit) => isHabitComplete(habit, resolvedValue(habit, key, state.mutations))).length;
    const percent = active.length ? Math.round((completed / active.length) * 100) : 0;
    progress.style.setProperty("--habits-app-progress", `${percent * 3.6}deg`);
    progressValue.textContent = `${percent}%`;
    dayResult.textContent = `${completed} z ${active.length}`;
    dayLabel.textContent = `${formatDay(key, { weekday: true, month: true })} · wykonanych`;
    const count = state.mutations.length;
    syncTitle.textContent = state.syncStatus === "online" ? "Połączono" : state.syncStatus === "syncing" ? "Synchronizacja" : state.syncStatus === "offline" ? "Offline" : "Łączenie";
    pending.textContent = count ? `${count} ${count === 1 ? "zmiana oczekuje" : "zmian oczekuje"}` : state.syncMessage;
    resetButton.disabled = state.syncStatus === "syncing";
    nextButton.disabled = state.endDate >= maxDate;
  }

  function createDateHeader(days) {
    const fragment = document.createDocumentFragment();
    const nameHeader = document.createElement("div");
    nameHeader.className = "habits-app-name-head";
    const range = document.createElement("strong");
    range.textContent = `${formatDay(days[0], { month: true })} – ${formatDay(days.at(-1), { month: true })}`;
    const hint = document.createElement("span");
    hint.textContent = "7 dni";
    nameHeader.append(range, hint);
    fragment.appendChild(nameHeader);
    days.forEach((key) => {
      const node = document.createElement("div");
      node.className = `habits-app-date-head${key === today ? " is-today" : ""}`;
      const weekday = document.createElement("span");
      weekday.textContent = new Intl.DateTimeFormat("pl-PL", { weekday: "short", timeZone: "UTC" })
        .format(new Date(`${key}T12:00:00Z`)).replace(".", "");
      const day = document.createElement("strong");
      day.textContent = key.slice(-2).replace(/^0/, "");
      node.append(weekday, day);
      fragment.appendChild(node);
    });
    return fragment;
  }

  function createHabitRow(habit, days) {
    const fragment = document.createDocumentFragment();
    const selected = habit.id === state.selectedId;
    const nameButton = document.createElement("button");
    nameButton.type = "button";
    nameButton.className = `habits-app-habit${selected ? " is-selected" : ""}`;
    nameButton.style.setProperty("--habit-color", habit.color);
    nameButton.title = state.apiReady ? "Przeciągnij, aby zmienić kolejność" : "";
    wireHabitDropTarget(nameButton, habit);
    wireHabitDragSource(nameButton, habit);
    nameButton.addEventListener("click", () => selectHabit(habit));
    const ring = document.createElement("span");
    ring.className = "habits-app-habit-ring";
    const copy = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = habit.name;
    if (habit.reminderConfig?.enabled) {
      const bell = document.createElement("span");
      bell.className = "habits-app-row-bell";
      bell.textContent = "🔔";
      bell.title = reminderDescription(habit);
      name.appendChild(bell);
    }
    const meta = document.createElement("small");
    meta.textContent = habit.type === "numeric"
      ? `${categoryLabels[habit.category]} · wartość${habit.unit ? ` w ${habit.unit}` : ""}`
      : `${categoryLabels[habit.category]} · ${habit.frequency[0]}/${habit.frequency[1]} dni`;
    copy.append(name, meta);
    nameButton.append(ring, copy);
    fragment.appendChild(nameButton);

    days.forEach((key) => {
      const value = resolvedValue(habit, key, state.mutations);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `habits-app-entry is-${habit.type}`;
      button.style.setProperty("--habit-color", habit.color);
      if (key === today) button.classList.add("is-today");
      if (value === null) button.classList.add("is-empty");
      else if (isHabitComplete(habit, value)) button.classList.add("is-complete");
      else button.classList.add("is-missed");
      button.setAttribute("aria-label", `${habit.name}, ${key}: ${value === null ? "brak wpisu" : formatValue(habit, value)}`);
      const main = document.createElement("span");
      main.textContent = value === null ? "·" : formatValue(habit, value);
      button.appendChild(main);
      if (habit.type === "numeric" && habit.unit && value !== null) {
        const unit = document.createElement("small");
        unit.textContent = habit.unit;
        button.appendChild(unit);
      }
      button.addEventListener("click", () => {
        if (habit.type === "binary") toggleBinary(habit, key);
        else openNumericEditor(habit, key);
      });
      fragment.appendChild(button);
    });
    return fragment;
  }

  function renderTable(days) {
    table.replaceChildren();
    table.appendChild(createDateHeader(days));
    const normalizedQuery = state.query.trim().toLocaleLowerCase("pl");
    const visible = activeHabits().filter((habit) => {
      const categoryMatch = state.filter === "all" || habit.category === state.filter;
      return categoryMatch && (!normalizedQuery || habit.name.toLocaleLowerCase("pl").includes(normalizedQuery));
    });
    visible.forEach((habit) => table.appendChild(createHabitRow(habit, days)));
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "habits-app-empty";
      empty.textContent = "Brak nawyków pasujących do filtra.";
      table.appendChild(empty);
    }
  }

  function metricNode(value, label, detailText = "") {
    const node = document.createElement("div");
    const strong = document.createElement("strong");
    const span = document.createElement("span");
    strong.textContent = String(value);
    span.textContent = label;
    node.append(strong, span);
    if (detailText) {
      const detailNode = document.createElement("small");
      detailNode.className = "habits-app-metric-detail";
      detailNode.textContent = detailText;
      node.appendChild(detailNode);
    }
    return node;
  }

  function formatTrackingDate(key) {
    if (!key) return "—";
    return new Intl.DateTimeFormat("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(`${key}T12:00:00Z`));
  }

  function formatTrackingDuration(value) {
    let days = Math.max(0, Math.floor(Number(value) || 0));
    if (!days) return "dzisiaj";
    const years = Math.floor(days / 365);
    days %= 365;
    const months = Math.floor(days / 30);
    days %= 30;
    const parts = [];
    if (years) parts.push(`${years} r.`);
    if (months) parts.push(`${months} mies.`);
    if (days && parts.length < 2) parts.push(days === 1 ? "1 dzień" : `${days} dni`);
    return parts.join(" ");
  }

  function renderDetail() {
    const active = activeHabits();
    const habit = active.find((item) => item.id === state.selectedId) || active[0];
    detail.replaceChildren();
    if (!habit) return;
    const heading = document.createElement("div");
    heading.className = "habits-app-detail-head";
    heading.style.setProperty("--habit-color", habit.color);
    const eyebrow = document.createElement("span");
    eyebrow.textContent = categoryLabels[habit.category];
    const title = document.createElement("strong");
    title.textContent = habit.name;
    const question = document.createElement("p");
    question.textContent = habit.question || (habit.type === "numeric" ? `Cel dzienny: ${habit.target ?? 0}${habit.unit ? ` ${habit.unit}` : ""}` : `Częstotliwość: ${habit.frequency[0]} na ${habit.frequency[1]} dni`);
    heading.append(eyebrow, title, question);

    const periodStats = document.createElement("section");
    periodStats.className = "habits-app-period-stats";
    const periodHeading = document.createElement("div");
    const periodTitle = document.createElement("strong");
    periodTitle.textContent = habit.type === "numeric" ? "Średnia" : "Skuteczność";
    const periodHint = document.createElement("span");
    periodHint.textContent = habit.type === "numeric" ? "z zapisanych wartości" : "dni zrealizowane";
    periodHeading.append(periodTitle, periodHint);
    const periodGrid = document.createElement("div");
    periodGrid.className = "habits-app-metrics";
    [
      { days: 7, label: "ostatni tydzień" },
      { days: 30, label: "ostatni miesiąc" },
      { days: 365, label: "ostatni rok" },
    ].forEach(({ days, label }) => {
      const summary = habitPeriodSummary(habit, state.endDate, state.mutations, days);
      const value = habit.type === "numeric"
        ? summary.average === null
          ? "—"
          : `${summary.average.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}${habit.unit ? ` ${habit.unit}` : ""}`
        : `${summary.percent}%`;
      const node = metricNode(value, label);
      node.title = habit.type === "numeric"
        ? `${summary.recorded} zapisanych wartości`
        : `${summary.completed} z ${summary.days} dni`;
      periodGrid.appendChild(node);
    });
    const lifetime = habitLifetimeSummary(habit, state.endDate, state.mutations);
    const lifetimeValue = habit.type === "numeric"
      ? lifetime.average === null
        ? "—"
        : `${lifetime.average.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}${habit.unit ? ` ${habit.unit}` : ""}`
      : `${lifetime.percent}%`;
    const lifetimeDetail = lifetime.startDate
      ? `od ${formatTrackingDate(lifetime.startDate)} · ${formatTrackingDuration(lifetime.elapsedDays)}${habit.type === "numeric" ? ` · skuteczność ${lifetime.percent}%` : ""}`
      : "brak wpisów";
    const lifetimeNode = metricNode(lifetimeValue, "od początku trackowania", lifetimeDetail);
    lifetimeNode.title = lifetime.startDate
      ? `${lifetime.completed} z ${lifetime.days} dni od ${formatTrackingDate(lifetime.startDate)}`
      : "Brak zapisanych wpisów";
    periodGrid.appendChild(lifetimeNode);
    periodStats.append(periodHeading, periodGrid);

    const heatmap = document.createElement("div");
    heatmap.className = "habits-app-heatmap-wrap";
    const heatmapHead = document.createElement("div");
    heatmapHead.className = "habits-app-heatmap-head";
    const endWeekday = (new Date(`${state.endDate}T12:00:00Z`).getUTCDay() + 6) % 7;
    const currentHeatmapEnd = shiftDateKey(state.endDate, 6 - endWeekday);
    const heatmapEnd = shiftDateKey(currentHeatmapEnd, state.heatmapPage * 84);
    const heatmapKeys = recentDateKeys(heatmapEnd, 84);
    const heatmapTitle = document.createElement("strong");
    heatmapTitle.textContent = "Historia";
    const heatmapControls = document.createElement("div");
    heatmapControls.className = "habits-app-heatmap-controls";
    const heatmapRange = document.createElement("span");
    const visibleHeatmapEnd = state.heatmapPage === 0 ? state.endDate : heatmapEnd;
    heatmapRange.textContent = `${formatDay(heatmapKeys[0], { month: true })} – ${formatDay(visibleHeatmapEnd, { month: true })}`;
    const olderButton = document.createElement("button");
    olderButton.type = "button";
    olderButton.textContent = "←";
    olderButton.setAttribute("aria-label", "Starsze 12 tygodni historii");
    olderButton.addEventListener("click", () => {
      state.heatmapPage -= 1;
      renderDetail();
    });
    const newerButton = document.createElement("button");
    newerButton.type = "button";
    newerButton.textContent = "→";
    newerButton.disabled = state.heatmapPage >= 0;
    newerButton.setAttribute("aria-label", "Nowsze 12 tygodni historii");
    newerButton.addEventListener("click", () => {
      state.heatmapPage = Math.min(0, state.heatmapPage + 1);
      renderDetail();
    });
    heatmapControls.append(heatmapRange, olderButton, newerButton);
    heatmapHead.append(heatmapTitle, heatmapControls);
    const heatmapScroll = document.createElement("div");
    heatmapScroll.className = "habits-app-heatmap-scroll";
    const heatmapGrid = document.createElement("div");
    heatmapGrid.className = "habits-app-heatmap";
    heatmapGrid.style.setProperty("--habit-color", habit.color);
    heatmapGrid.setAttribute("role", "grid");
    heatmapGrid.setAttribute("aria-label", `Historia ${habit.name}, 12 tygodni`);
    ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz"].forEach((label, index) => {
      const dayLabelNode = document.createElement("span");
      dayLabelNode.className = "habits-app-heatmap-day";
      dayLabelNode.textContent = label;
      dayLabelNode.style.gridColumn = "1";
      dayLabelNode.style.gridRow = String(index + 2);
      heatmapGrid.appendChild(dayLabelNode);
    });
    let previousMonth = "";
    for (let week = 0; week < 12; week += 1) {
      const representativeKey = heatmapKeys[(week * 7) + 3];
      const month = representativeKey.slice(0, 7);
      if (month === previousMonth) continue;
      previousMonth = month;
      const monthLabel = document.createElement("span");
      monthLabel.className = "habits-app-heatmap-month";
      monthLabel.textContent = new Intl.DateTimeFormat("pl-PL", { month: "short", timeZone: "UTC" })
        .format(new Date(`${representativeKey}T12:00:00Z`)).replace(".", "");
      monthLabel.style.gridColumn = String(week + 2);
      monthLabel.style.gridRow = "1";
      heatmapGrid.appendChild(monthLabel);
    }
    heatmapKeys.forEach((key, index) => {
      const value = resolvedValue(habit, key, state.mutations);
      const dot = document.createElement("span");
      dot.className = `habits-app-heatmap-day-cell ${value === null ? "is-empty" : isHabitComplete(habit, value) ? "is-on" : "is-off"}${key > state.endDate ? " is-future" : ""}`;
      dot.style.gridColumn = String(Math.floor(index / 7) + 2);
      dot.style.gridRow = String((index % 7) + 2);
      const fullDate = new Intl.DateTimeFormat("pl-PL", {
        weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
      }).format(new Date(`${key}T12:00:00Z`));
      const displayedValue = value === null ? "brak wpisu" : `${formatValue(habit, value)}${habit.unit ? ` ${habit.unit}` : ""}`;
      dot.title = `${fullDate}: ${displayedValue}`;
      dot.setAttribute("aria-label", dot.title);
      dot.setAttribute("role", "gridcell");
      heatmapGrid.appendChild(dot);
    });
    heatmapScroll.appendChild(heatmapGrid);
    heatmap.append(heatmapHead, heatmapScroll);

    const note = document.createElement("p");
    note.className = "habits-app-detail-note";
    note.textContent = state.apiReady
      ? "Dane są wspólne dla dashboardu i telefonu. Zmiany synchronizują się przez lokalny serwer w tej samej sieci."
      : "Brak połączenia z lokalnym serwerem. Zmiany pozostaną w kolejce i wyślą się po odzyskaniu połączenia.";
    detail.append(heading, periodStats, heatmap, note);
  }

  function render() {
    const days = recentDateKeys(state.endDate, 7);
    renderHeader(days);
    renderTable(days);
    renderDetail();
    renderManageList();
  }

  const reminderExecution = new ReminderExecutionService({
    getHabits: () => activeHabits().filter((habit) => !new Set([
      "Vitamin B Complex", "Vitamin D3 + K2", "Omega-3", "Creatine", "Magnesium", "Zinc",
    ]).has(habit.name)),
    getGroups: () => state.reminderTimeGroups,
    getStates: () => state.reminderStates,
    isComplete: reminderCompleteOnDate,
    claimOccurrence: claimReminderOccurrence,
    updateOccurrence: changeReminderOccurrence,
    notify: showReminderNotification,
  });
  const supplementPanel = createSupplementPanel({
    root,
    getHabits: () => habits,
    getValue: (habit, day) => resolvedValue(habit, day, state.mutations),
    markTaken: mutationFor,
    notificationsEnabled: () => state.reminderSettings.browserNotificationsEnabled,
    toastStack: reminderToastStack,
  });

  document.querySelectorAll("[data-habits-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.habitsFilter;
      document.querySelectorAll("[data-habits-filter]").forEach((item) => item.classList.toggle("is-active", item === button));
      renderTable(recentDateKeys(state.endDate, 7));
    });
  });

  search.addEventListener("input", () => {
    state.query = search.value;
    renderTable(recentDateKeys(state.endDate, 7));
  });
  previousButton.addEventListener("click", () => {
    state.endDate = shiftDateKey(state.endDate, -7);
    render();
  });
  nextButton.addEventListener("click", () => {
    state.endDate = shiftDateKey(state.endDate, 7);
    if (state.endDate > maxDate) state.endDate = maxDate;
    render();
  });
  todayButton.addEventListener("click", () => {
    state.endDate = maxDate;
    render();
  });
  resetButton.addEventListener("click", () => {
    if (state.mutations.length) queueSync();
    else refreshFromApi().catch((error) => {
      state.syncStatus = "offline";
      state.syncMessage = error?.message || "brak połączenia z API";
      render();
    });
  });
  addButton.addEventListener("click", () => {
    addForm.reset();
    addCategory.value = { lifestyle: "HABIT", meds: "MEDICATION", supplements: "SUPPLEMENT" }[state.filter] || "HABIT";
    addNumeric.hidden = true;
    addError.hidden = true;
    addDialog.showModal();
    addName.focus();
  });
  document.getElementById("habits-app-add-close").addEventListener("click", () => addDialog.close());
  addName.addEventListener("input", () => {
    addName.setCustomValidity("");
    addError.hidden = true;
  });
  addType.addEventListener("change", () => {
    addNumeric.hidden = addType.value !== "NUMERIC";
  });
  addForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = addName.value.trim();
    if (!name) {
      addName.setCustomValidity("Podaj nazwę.");
      addName.reportValidity();
      return;
    }
    addName.setCustomValidity("");
    if (habits.some((habit) => [habit.name, habit.sourceName].some((existing) => existing?.toLocaleLowerCase("pl") === name.toLocaleLowerCase("pl")))) {
      addError.textContent = "Pozycja o tej nazwie już istnieje. Sprawdź też ukryte pozycje w Zarządzaj.";
      addError.hidden = false;
      return;
    }
    if (!state.apiReady) {
      addError.textContent = "Połącz się z lokalnym serwerem, aby dodać pozycję.";
      addError.hidden = false;
      return;
    }
    addSave.disabled = true;
    addError.hidden = true;
    let savedId = null;
    try {
      if (syncPromise) await syncPromise;
      if (orderPromise) await orderPromise;
      const target = addType.value === "NUMERIC" && addTarget.value !== "" ? Number(addTarget.value) : null;
      const payload = {
        name,
        category: addCategory.value,
        type: addType.value,
        unit: addType.value === "NUMERIC" ? addUnit.value.trim() : "",
        targetValueMilli: target === null ? null : Math.round(target * 1000),
        position: Math.max(-1, ...habits.map((habit) => habit.position)) + 1,
      };
      savedId = await createHabit(payload, state.cursor);
      addDialog.close();
      await refreshFromApi();
      state.selectedId = savedId;
      state.endDate = maxDate;
      state.filter = "all";
      state.query = "";
      search.value = "";
      root.querySelectorAll("[data-habits-filter]").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.habitsFilter === "all");
      });
      state.syncMessage = "dodano nową pozycję";
      render();
    } catch (error) {
      if (savedId) {
        state.syncStatus = "offline";
        state.syncMessage = error?.message || "Dodano pozycję, ale nie udało się odświeżyć listy.";
        render();
      } else {
        addError.textContent = error?.message || "Nie udało się dodać pozycji.";
        addError.hidden = false;
      }
    } finally {
      addSave.disabled = false;
    }
  });
  manageButton.addEventListener("click", () => {
    renderManageList();
    manageDialog.showModal();
  });
  remindersButton.addEventListener("click", () => {
    renderReminderPanel();
    reminderPanelDialog.showModal();
  });
  reminderOpenSettings.addEventListener("click", () => {
    reminderPanelDialog.close();
    openReminderSettings();
  });
  reminderSchedule.addEventListener("change", renderReminderScheduleFields);
  reminderItemDialog.querySelectorAll("[data-reminder-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      const preset = button.dataset.reminderPreset;
      setReminderWeekdays(preset === "all" ? [0, 1, 2, 3, 4, 5, 6]
        : preset === "weekdays" ? [0, 1, 2, 3, 4]
          : preset === "weekend" ? [5, 6] : []);
    });
  });
  reminderAddCustom.addEventListener("click", () => {
    const value = reminderCustomTime.value;
    if (value && !reminderDraftCustomTimes.includes(value)) {
      reminderDraftCustomTimes.push(value);
      reminderDraftCustomTimes.sort();
      renderReminderCustomTimes();
      reminderCustomTime.value = "";
    }
  });
  reminderItemForm.addEventListener("submit", (event) => {
    if (event.submitter?.value !== "save") return;
    event.preventDefault();
    saveItemReminder().then((saved) => {
      if (saved) reminderItemDialog.close();
    }).catch((error) => {
      reminderError.textContent = error?.message || "Could not save reminders.";
      reminderError.hidden = false;
    });
  });
  reminderBrowserEnabled.addEventListener("change", async () => {
    if (!reminderBrowserEnabled.checked) return;
    if (typeof Notification === "undefined") {
      reminderBrowserEnabled.checked = false;
    } else if (Notification.permission !== "granted") {
      try {
        const permission = await Notification.requestPermission();
        reminderBrowserEnabled.checked = permission === "granted";
      } catch {
        reminderBrowserEnabled.checked = false;
      }
    }
    reminderPermission.textContent = notificationPermissionLabel();
  });
  reminderAddGroup.addEventListener("click", () => {
    reminderSettingsDraft.push({ id: newTimeGroupId(), name: "New time", localTime: "09:00", sortOrder: reminderSettingsDraft.length });
    renderReminderSettingsDraft();
  });
  reminderDeleteDialog.addEventListener("close", () => {
    const result = reminderDeleteDialog.returnValue;
    if (result === "remove") finishTimeGroupDeletion(null);
    else if (result === "replace" && reminderDeleteReplacement.value) finishTimeGroupDeletion(reminderDeleteReplacement.value);
    else pendingDeletedGroup = null;
  });
  reminderSettingsForm.addEventListener("submit", (event) => {
    if (event.submitter?.value !== "save") return;
    event.preventDefault();
    saveGlobalReminderSettings().then(() => reminderSettingsDialog.close()).catch((error) => {
      reminderSettingsError.textContent = error?.message || "Could not save reminder settings.";
      reminderSettingsError.hidden = false;
    });
  });
  entryClear.addEventListener("click", () => {
    if (!editing) return;
    mutationFor(editing.habit, editing.key, null);
    dialog.close();
    render();
  });
  entryForm.addEventListener("submit", (event) => {
    if (event.submitter?.value === "cancel" || !editing) return;
    event.preventDefault();
    const value = Number.parseFloat(valueInput.value.trim().replace(",", "."));
    if (!Number.isFinite(value) || value < 0) {
      valueInput.setCustomValidity("Wpisz liczbę równą lub większą od zera.");
      valueInput.reportValidity();
      return;
    }
    valueInput.setCustomValidity("");
    mutationFor(editing.habit, editing.key, value);
    if (editing.occurrence) changeReminderOccurrence("satisfied", editing.occurrence).catch(() => {});
    state.selectedId = editing.habit.id;
    dialog.close();
    render();
  });
  dialog.addEventListener("close", () => {
    editing = null;
    valueInput.setCustomValidity("");
  });

  render();
  refreshFromApi()
    .then(() => {
      if (state.mutations.length) queueSync();
      reminderExecution.tick().catch(() => {});
      supplementPanel.tick().catch(() => {});
    })
    .catch((error) => {
      state.syncStatus = "offline";
      state.syncMessage = error?.message || "brak połączenia z API";
      render();
    });
  const pollTimer = window.setInterval(pollForRemoteChanges, 3000);
  const reminderTimer = window.setInterval(() => reminderExecution.tick().catch(() => {}), 15000);
  const supplementTimer = window.setInterval(() => supplementPanel.tick().catch(() => {}), 15000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollForRemoteChanges();
    if (!document.hidden) supplementPanel.tick().catch(() => {});
  });
  window.addEventListener("beforeunload", () => {
    window.clearInterval(pollTimer);
    window.clearInterval(reminderTimer);
    window.clearInterval(supplementTimer);
  }, { once: true });
  card.dataset.ready = "true";
  document.dispatchEvent(new CustomEvent("dashboard:content-updated"));
}
