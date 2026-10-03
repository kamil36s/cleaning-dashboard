import { onDomReady } from "./dom-ready.js";
import {
  clearDashboardWidgetConfig,
  getDefaultDashboardWidgetConfig,
  getOrderedDashboardWidgets,
  loadDashboardWidgetConfig,
  moveDashboardWidget,
  saveDashboardWidgetConfig,
  setDashboardAutoFitEnabled,
  setAllDashboardWidgetsVisibility,
  setDashboardColumnCount,
  setDashboardCleaningLockEnabled,
  setDashboardHeartRateHistoryShortcutEnabled,
  setDashboardHeaderFontSize,
  setDashboardWidgetHeaderText,
  setDashboardWidgetVisibility,
  setDashboardWidgetSpan,
} from "./dashboard-settings.js";
import {
  fetchNetworkDevices,
  getNetworkApiBase,
  saveNetworkDeviceProfile,
} from "./network-monitor-api.js";
import {
  getNetworkStatusNotificationsEnabled,
  setNetworkStatusNotificationsEnabled,
} from "./network-notification-settings.js";

const DEFAULT_STATUS =
  "Ustawienia zapisują się automatycznie i od razu będą użyte na dashboardzie.";
const MODAL_DEFAULT_STATUS =
  "Nazwy nagłówków zapisują się automatycznie. Pozostałe zmiany zatwierdzisz przyciskiem „Zapisz i zamknij”.";
const MODAL_PENDING_STATUS =
  "Masz niezapisane zmiany. Kliknij „Zapisz i zamknij”, żeby użyć ich na dashboardzie.";
const DASHBOARD_COLUMN_OPTIONS = [2, 3, 4];
const DASHBOARD_SPAN_OPTIONS = [
  { value: "auto", label: "Auto" },
  { value: "1", label: "1 kolumna" },
  { value: "2", label: "2 kolumny" },
  { value: "3", label: "3 kolumny" },
  { value: "full", label: "Pełna szerokość" },
];
const NETWORK_DEFAULT_STATUS =
  "Profile urządzeń zapisują się lokalnie w backendzie monitora sieci.";
const KITCHEN_DEFAULT_STATUS =
  "Ustawienia zapisują się w backendzie, a tablet zauważy zmianę w ciągu kilku sekund.";
const SCREENSAVER_DEFAULT_STATUS =
  "Ustawienia screensavera zapiszą się lokalnie i będą użyte przez watcher przy kolejnym sprawdzeniu.";
const DEFAULT_SECTION = "dashboard-layout";
const PAGE_DEFAULT_SECTION = "status";
const SETTINGS_SECTIONS = ["status", "dashboard-layout", "network-devices", "kitchen-dashboard", "spotify-screensaver"];
const SETTINGS_SECTION_ALIASES = {
  "network-device-settings": "network-devices",
  kitchen: "kitchen-dashboard",
  spotify: "spotify-screensaver",
  screensaver: "spotify-screensaver",
};

let state = null;
let networkDevices = [];
let activeSection = DEFAULT_SECTION;
let statusTimer = 0;
let networkStatusTimer = 0;
let kitchenStatusTimer = 0;
let screensaverStatusTimer = 0;
let kitchenSportsSaveTimer = 0;
let headerTextSaveTimer = 0;
let headerTextPendingRow = null;
let kitchenSettings = null;
let screensaverSettings = null;
let lastFocusedEl = null;
let settingsModalLoading = false;
let modalDashboardDirty = false;

const $ = (id) => document.getElementById(id);
const isSettingsPage = () => document.body.classList.contains("page-settings");
const isDashboardModalContext = () => {
  const overlay = $("settings-overlay");
  return !isSettingsPage() && !!overlay && !overlay.hidden;
};
const DEVICE_CATEGORY_OPTIONS = [
  { value: "", label: "Nieokreślone" },
  { value: "personal", label: "Osobiste" },
  { value: "household", label: "Domowe" },
  { value: "iot", label: "IoT" },
  { value: "infrastructure", label: "Infrastruktura" },
];
const DEVICE_CATEGORY_LABELS = {
  personal: "Osobiste",
  household: "Domowe",
  iot: "IoT",
  infrastructure: "Infrastruktura",
};

const escapeHtml = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

function kitchenImageSrc(value) {
  const raw = String(value || "").trim();
  if (/^https:\/\//i.test(raw)) {
    return `/api/kitchen/image?u=${encodeURIComponent(raw)}`;
  }
  return raw;
}

function resolveSectionKey(value) {
  const normalized = String(value || "")
    .trim()
    .replace(/^#/, "")
    .toLowerCase();

  if (SETTINGS_SECTION_ALIASES[normalized]) {
    return SETTINGS_SECTION_ALIASES[normalized];
  }

  return SETTINGS_SECTIONS.includes(normalized) ? normalized : DEFAULT_SECTION;
}

function syncSectionHash(sectionKey) {
  if (!isSettingsPage() || typeof window === "undefined") return;

  const url = new URL(window.location.href);
  url.hash = sectionKey;
  window.history.replaceState(window.history.state, "", url);
}

function setStatus(message, tone = "idle") {
  const note = $("settings-save-note");
  if (!note) return;
  note.textContent = message;
  note.dataset.tone = tone;
}

function getDashboardStatusDefault() {
  if (isDashboardModalContext()) {
    return modalDashboardDirty ? MODAL_PENDING_STATUS : MODAL_DEFAULT_STATUS;
  }
  return DEFAULT_STATUS;
}

function setNetworkStatus(message, tone = "idle") {
  const note = $("network-settings-note");
  if (!note) return;
  note.textContent = message;
  note.dataset.tone = tone;
}

function setKitchenStatus(message, tone = "idle") {
  const note = $("kitchen-settings-note");
  if (!note) return;
  note.textContent = message;
  note.dataset.tone = tone;
}

function setScreensaverStatus(message, tone = "idle") {
  const note = $("screensaver-settings-note");
  if (!note) return;
  note.textContent = message;
  note.dataset.tone = tone;
}

function flashSaved(message) {
  if (statusTimer) {
    window.clearTimeout(statusTimer);
  }

  setStatus(message, "saved");
  statusTimer = window.setTimeout(() => {
    setStatus(getDashboardStatusDefault(), "idle");
    statusTimer = 0;
  }, 2400);
}

function flashNetworkSaved(message) {
  if (networkStatusTimer) {
    window.clearTimeout(networkStatusTimer);
  }

  setNetworkStatus(message, "saved");
  networkStatusTimer = window.setTimeout(() => {
    setNetworkStatus(NETWORK_DEFAULT_STATUS, "idle");
    networkStatusTimer = 0;
  }, 2400);
}

function flashKitchenSaved(message) {
  if (kitchenStatusTimer) {
    window.clearTimeout(kitchenStatusTimer);
  }

  setKitchenStatus(message, "saved");
  kitchenStatusTimer = window.setTimeout(() => {
    setKitchenStatus(KITCHEN_DEFAULT_STATUS, "idle");
    kitchenStatusTimer = 0;
  }, 2400);
}

function flashScreensaverSaved(message) {
  if (screensaverStatusTimer) {
    window.clearTimeout(screensaverStatusTimer);
  }

  setScreensaverStatus(message, "saved");
  screensaverStatusTimer = window.setTimeout(() => {
    setScreensaverStatus(SCREENSAVER_DEFAULT_STATUS, "idle");
    screensaverStatusTimer = 0;
  }, 2400);
}

function renderSectionNavigation() {
  const links = document.querySelectorAll("[data-settings-section-link]");
  const panels = document.querySelectorAll("[data-settings-panel]");

  links.forEach((link) => {
    const key = resolveSectionKey(link.dataset.settingsSectionLink);
    const isActive = key === activeSection;

    link.classList.toggle("is-active", isActive);
    link.setAttribute("aria-selected", isActive ? "true" : "false");
    link.tabIndex = isActive ? 0 : -1;
  });

  panels.forEach((panel) => {
    const key = resolveSectionKey(panel.dataset.settingsPanel);
    panel.hidden = key !== activeSection;
    panel.classList.toggle("is-active", key === activeSection);
  });

  document.body.dataset.settingsSection = activeSection;
}

function setActiveSection(nextSection, { syncHash = isSettingsPage() } = {}) {
  activeSection = resolveSectionKey(nextSection);
  renderSectionNavigation();

  if (syncHash) {
    syncSectionHash(activeSection);
  }
}

async function refreshState() {
  state = await loadDashboardWidgetConfig();
  renderLayoutControls();
  renderWidgetList();
  setStatus(DEFAULT_STATUS, "idle");
}

function renderLayoutControls() {
  const picker = $("settings-column-picker");
  const autoFitToggle = $("settings-auto-fit");
  const heartRateHistoryToggle = $("settings-heart-rate-history-shortcut");
  const cleaningLockToggle = $("settings-cleaning-lock");
  const fontSizeInput = $("settings-header-font-size");
  const fontSizeValue = $("settings-header-font-size-value");
  if (!state) return;

  const currentColumns = Number(state.layout?.columns) || 2;
  if (picker) {
    picker.innerHTML = DASHBOARD_COLUMN_OPTIONS
      .map((columns) => {
        const isActive = columns === currentColumns;
        return `
          <button
            class="settings-column-option${isActive ? " is-active" : ""}"
            type="button"
            role="radio"
            aria-checked="${isActive ? "true" : "false"}"
            data-columns="${columns}"
          >
            <span class="settings-column-value">${columns}</span>
            <span class="settings-column-label">kolumny</span>
          </button>
        `;
      })
      .join("");
  }

  if (autoFitToggle) {
    autoFitToggle.checked = state.layout?.autoFit === true;
  }

  if (heartRateHistoryToggle) {
    heartRateHistoryToggle.checked = state.layout?.showHeartRateHistoryShortcut !== false;
  }

  if (cleaningLockToggle) {
    cleaningLockToggle.checked = state.layout?.cleaningLockEnabled === true;
  }

  const headerFontSize = Number(state.headers?.titleFontSize) || 16;
  if (fontSizeInput) {
    fontSizeInput.value = String(headerFontSize);
  }
  if (fontSizeValue) {
    fontSizeValue.textContent = `${headerFontSize}px`;
  }
}

function renderWidgetList() {
  const list = $("settings-widget-list");
  if (!list || !state) return;

  const widgets = getOrderedDashboardWidgets(state);

  list.innerHTML = widgets
    .map((widget, index) => {
      const isFirst = index === 0;
      const isLast = index === widgets.length - 1;
      const rank = String(index + 1).padStart(2, "0");
      const span = widget.span || "auto";
      const title = widget.title || widget.label;
      const spanOptions = DASHBOARD_SPAN_OPTIONS
        .map((option) => `
          <option value="${escapeHtml(option.value)}"${option.value === span ? " selected" : ""}>
            ${escapeHtml(option.label)}
          </option>
        `)
        .join("");
      return `
        <article class="settings-widget-row${widget.visible ? "" : " is-hidden"}" data-key="${escapeHtml(widget.key)}">
          <div class="settings-widget-rank">${rank}</div>
          <div class="settings-widget-copy">
            <div class="settings-widget-topline">
              <div class="settings-widget-name">${escapeHtml(widget.label)}</div>
              <span class="settings-widget-state ${widget.visible ? "is-active" : "is-hidden"}">
                ${widget.visible ? "Aktywny" : "Ukryty"}
              </span>
            </div>
            <div class="settings-widget-desc">${escapeHtml(widget.description)}</div>
            <div class="settings-widget-header-editor">
              <label>
                <span>Nagłówek</span>
                <input data-action="header-title" type="text" value="${escapeHtml(title)}" maxlength="80" />
              </label>
            </div>
          </div>
          <label class="settings-widget-placement">
            <span>Szerokość</span>
            <select data-action="span" aria-label="Szerokość widgetu ${escapeHtml(widget.label)}">
              ${spanOptions}
            </select>
          </label>
          <label class="settings-widget-toggle">
            <input type="checkbox" data-action="toggle"${widget.visible ? " checked" : ""} />
            <span>Aktywny</span>
          </label>
          <div class="settings-widget-moves" aria-label="Zmiana kolejności">
            <button class="settings-move-btn" data-action="up" type="button" aria-label="Przesuń widget wyżej"${isFirst ? " disabled" : ""}>^</button>
            <button class="settings-move-btn" data-action="down" type="button" aria-label="Przesuń widget niżej"${isLast ? " disabled" : ""}>v</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatRelative(value) {
  const date = parseDate(value);
  if (!date) return "brak danych";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat("pl", { numeric: "auto" });
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  return rtf.format(Math.round(seconds / 86400), "day");
}

function formatDeviceStatus(device) {
  if (device?.is_online) {
    return `Online od ${formatRelative(device?.online_since || device?.last_seen)}`;
  }
  return `Offline, ostatnio ${formatRelative(device?.last_seen)}`;
}

function categoryLabel(value) {
  return DEVICE_CATEGORY_LABELS[String(value || "").trim()] || "Nieokreślone";
}

function categoryOptionsMarkup(selectedValue) {
  const current = String(selectedValue || "").trim();
  return DEVICE_CATEGORY_OPTIONS
    .map((option) => {
      const selected = option.value === current ? " selected" : "";
      return `<option value="${escapeHtml(option.value)}"${selected}>${escapeHtml(option.label)}</option>`;
    })
    .join("");
}

function renderNetworkDeviceList() {
  const list = $("network-device-list");
  if (!list) return;

  if (!getNetworkApiBase()) {
    list.innerHTML = '<div class="settings-device-empty">Backend monitora sieci jest dostępny tylko lokalnie.</div>';
    setNetworkStatus("Brak lokalnego adresu API monitora sieci.", "idle");
    return;
  }

  if (!networkDevices.length) {
    list.innerHTML = '<div class="settings-device-empty">Brak urządzeń w historii. Poczekaj na pierwszy skan monitora sieci.</div>';
    return;
  }

  list.innerHTML = networkDevices
    .map((device) => {
      const canEdit = !!device?.mac;
      const title = escapeHtml(
        device?.custom_name
        || device?.detected_name
        || device?.ip
        || device?.mac
        || "Nieznane urządzenie",
      );
      const meta = [
        device?.ip || "",
        device?.mac || "brak MAC",
        device?.last_method || "",
      ].filter(Boolean).join(" / ");
      const status = formatDeviceStatus(device);
      const customValue = escapeHtml(device?.custom_name || "");
      const placeholder = escapeHtml(
        device?.detected_name || device?.ip || device?.mac || "Własna nazwa",
      );
      const ownerValue = escapeHtml(device?.owner || "");
      const categoryValue = String(device?.category || "").trim();
      const tags = [
        `<span class="settings-device-tag">${escapeHtml(categoryLabel(categoryValue))}</span>`,
        device?.owner ? `<span class="settings-device-tag is-owner">${escapeHtml(device.owner)}</span>` : "",
      ].filter(Boolean).join("");
      return `
        <article class="settings-device-row${device?.is_online ? " is-online" : ""}" data-mac="${escapeHtml(device?.mac || "")}">
          <div class="settings-device-copy">
            <div class="settings-device-topline">
              <div class="settings-device-name">${title}</div>
              <span class="settings-device-state ${device?.is_online ? "is-online" : "is-offline"}">
                ${device?.is_online ? "Online" : "Offline"}
              </span>
            </div>
            <div class="settings-device-meta">${escapeHtml(meta)}</div>
            <div class="settings-device-hint">${escapeHtml(status)}</div>
            <div class="settings-device-tags">${tags}</div>
          </div>
          <div class="settings-device-controls">
            <div class="settings-device-form-grid">
              <label class="settings-device-field">
                <span class="settings-device-field-label">Nazwa</span>
                <input
                  class="settings-device-input"
                  data-field="name"
                  type="text"
                  value="${customValue}"
                  placeholder="${placeholder}"
                  ${canEdit ? "" : "disabled"}
                />
              </label>
              <div class="settings-device-meta-grid">
                <label class="settings-device-field">
                  <span class="settings-device-field-label">Kategoria</span>
                  <select class="settings-device-select" data-field="category" ${canEdit ? "" : "disabled"}>
                    ${categoryOptionsMarkup(categoryValue)}
                  </select>
                </label>
                <label class="settings-device-field">
                  <span class="settings-device-field-label">Owner</span>
                  <input
                    class="settings-device-input"
                    data-field="owner"
                    type="text"
                    value="${ownerValue}"
                    placeholder="np. Ja"
                    ${canEdit ? "" : "disabled"}
                  />
                </label>
              </div>
            </div>
            <div class="settings-device-actions">
              <button class="budget-action" data-action="save-device-profile" type="button" ${canEdit ? "" : "disabled"}>Zapisz</button>
              <button class="budget-action budget-action--ghost" data-action="clear-device-profile" type="button" ${canEdit ? "" : "disabled"}>Wyczyść</button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderNetworkNotificationSettings() {
  const toggle = $("network-notifications-toggle");
  if (!(toggle instanceof HTMLInputElement)) return;

  toggle.checked = getNetworkStatusNotificationsEnabled();
}

function isValidClozemasterUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return true;
  try {
    const url = new URL(raw);
    return url.origin === "https://www.clozemaster.com";
  } catch {
    return false;
  }
}

async function fetchKitchenSettings() {
  const response = await fetch("/api/kitchen/settings", { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `API error ${response.status}`);
  }
  return response.json();
}

async function saveKitchenSettings(payload = {}) {
  const response = await fetch("/api/kitchen/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error || `API error ${response.status}`);
  }
  return response.json();
}

async function fetchScreensaverSettings() {
  const response = await fetch("/api/screensaver-config", { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `API error ${response.status}`);
  }
  return response.json();
}

async function saveScreensaverSettings(payload = {}) {
  const response = await fetch("/api/screensaver-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error || `API error ${response.status}`);
  }
  return response.json();
}

async function requestDashboardTabletRefresh() {
  const current = state || await loadDashboardWidgetConfig();
  const response = await fetch("/api/settings/dashboard", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({
      data: {
        ...current,
        _refreshRequest: {
          nonce: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          requestedAt: new Date().toISOString(),
          source: "settings",
        },
      },
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error || `API error ${response.status}`);
  }
  return response.json();
}

async function uploadArtistFacts(payload = {}) {
  const response = await fetch("/api/artist-facts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error || `API error ${response.status}`);
  }
  return response.json();
}

async function fetchKitchenDebug() {
  const response = await fetch("/api/kitchen/debug", { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `API error ${response.status}`);
  }
  return response.json();
}

function renderKitchenDebug(payload) {
  const output = $("kitchen-debug-output");
  if (!output) return;
  const sources = Array.isArray(payload?.sources) ? payload.sources : [];
  const lines = [
    `Cache: ${payload?.cacheUpdatedAt || "brak"} | provider: ${payload?.provider || "brak"} | zakres: ${payload?.windowHours || 24}h`,
    "",
    ...sources.map((source) => [
      `${source.name || source.key} (${source.key})`,
      `  źródła: ${(source.providers || []).join(", ")}`,
      `  cache: wyniki ${source.cachedMatches || 0}, live ${source.cachedLiveMatches || 0}`,
    ].join("\n")),
  ];
  if (Array.isArray(payload?.errors) && payload.errors.length) {
    lines.push("", "Błędy:", ...payload.errors.map((error) => `- ${error}`));
  }
  output.textContent = lines.join("\n");
}

async function refreshKitchenDebug() {
  const output = $("kitchen-debug-output");
  if (output) output.textContent = "Sprawdzam źródła...";
  try {
    renderKitchenDebug(await fetchKitchenDebug());
  } catch (error) {
    if (output) output.textContent = `Nie udało się pobrać debug info: ${String(error?.message || error)}`;
  }
}

function kitchenCheckListMarkup(items, enabledKeys, kind) {
  const enabled = new Set(enabledKeys || []);
  return (items || []).map((item) => `
    <label class="settings-check-row">
      <input
        type="checkbox"
        data-kitchen-kind="${escapeHtml(kind)}"
        value="${escapeHtml(item.key)}"
        ${enabled.has(item.key) ? " checked" : ""}
      />
      ${item.crest ? `<img class="settings-sport-logo" src="${escapeHtml(kitchenImageSrc(item.crest))}" alt="" loading="lazy">` : `<span class="settings-sport-logo is-placeholder">${escapeHtml((item.name || "?").slice(0, 1))}</span>`}
      <span>
        <strong>${escapeHtml(item.name)}</strong>
        <small>${item.hasStandings ? "wyniki + tabela" : item.hasNextMatches && !item.hasRecentResults ? "najblizszy mecz" : "wyniki"}</small>
      </span>
    </label>
  `).join("");
}

function kitchenLeagueListMarkup(items, sports) {
  const enabled = new Set(sports.enabledLeagueKeys || []);
  const standings = new Set(sports.standingsLeagueKeys || []);
  const groups = new Map();
  (items || []).forEach((item) => {
    const group = item.group || "Inne";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(item);
  });
  return Array.from(groups.entries()).map(([group, groupItems]) => `
    <section class="settings-sport-group ${groupItems.length === 1 ? "is-single" : "is-wide"}">
      <h3>${escapeHtml(group)}</h3>
      <div class="settings-sport-grid">
        ${groupItems.map((item) => {
          const mode = standings.has(item.key) ? "table" : enabled.has(item.key) ? "results" : "off";
          const tournament = item.nextTournament || null;
          const tournamentStatus = tournament?.status === "confirmed" ? "is-confirmed" : "is-unconfirmed";
          const tournamentText = tournament
            ? `${tournament.dateLabel || "brak potwierdzonych dat"} | ${tournament.host || "brak potwierdzonego gospodarza"}`
            : "";
          return `
            <label class="settings-league-row">
              ${item.badge ? `<img class="settings-sport-logo" src="${escapeHtml(kitchenImageSrc(item.badge))}" alt="" loading="lazy">` : `<span class="settings-sport-logo is-placeholder">${escapeHtml((item.name || "?").slice(0, 1))}</span>`}
              <span class="settings-sport-copy">
                <strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong>
                <small>${escapeHtml([item.sport, item.source === "configured" ? "dodane ręcznie" : "TheSportsDB"].filter(Boolean).join(" / "))}</small>
                ${tournament ? `
                  <small class="settings-tournament-meta ${tournamentStatus}">
                    <span>Najbliższy turniej</span>
                    <b>${escapeHtml(tournamentText)}</b>
                    ${tournament.note ? `<em>${escapeHtml(tournament.note)}</em>` : ""}
                  </small>
                ` : ""}
              </span>
              <select class="settings-device-select" data-kitchen-league-mode="${escapeHtml(item.key)}">
                <option value="off"${mode === "off" ? " selected" : ""}>wyłączone</option>
                <option value="results"${mode === "results" ? " selected" : ""}>wyniki</option>
                ${item.tableAvailable ? `<option value="table"${mode === "table" ? " selected" : ""}>wyniki + tabela</option>` : ""}
              </select>
            </label>
          `;
        }).join("")}
      </div>
    </section>
  `).join("");
}

function kitchenWindowLabel(hours) {
  const value = Number(hours);
  if (value === 24) return "24h";
  if (value % 24 === 0) {
    const days = value / 24;
    return days === 1 ? "1 dzień" : `${days} dni`;
  }
  return `${value}h`;
}

function kitchenTournamentListMarkup(items) {
  const tournaments = Array.isArray(items) ? items : [];
  if (!tournaments.length) {
    return `<div class="settings-tournament-empty">Brak nadchodzacych turniejow z potwierdzona albo przyblizona data.</div>`;
  }
  return tournaments.map((item) => {
    const status = item.status === "confirmed" ? "is-confirmed" : "is-unconfirmed";
    const meta = [item.dateLabel, item.host].filter(Boolean).join(" | ");
    return `
      <article class="settings-tournament-row ${status}">
        <div>
          <strong>${escapeHtml(item.name || "Turniej")}</strong>
          <small>${escapeHtml(meta || item.note || "brak szczegolow")}</small>
        </div>
        <span>${escapeHtml(item.daysLabel || "")}</span>
      </article>
    `;
  }).join("");
}

function renderKitchenSettings() {
  const input = $("kitchen-clozemaster-url");
  const current = $("kitchen-clozemaster-current");
  const recipeToggle = $("kitchen-recipe-enabled");
  const recipeInput = $("kitchen-recipe-content");
  const recipeCurrent = $("kitchen-recipe-current");
  const windowSelect = $("kitchen-sports-window");
  const tournamentList = $("kitchen-tournament-list");
  const leagueList = $("kitchen-league-list");
  const teamList = $("kitchen-team-list");
  if (!(input instanceof HTMLInputElement)) return;

  const url = kitchenSettings?.clozemasterUrl || kitchenSettings?.defaultClozemasterUrl || "";
  const sports = kitchenSettings?.sports || {};
  const options = kitchenSettings?.sportsOptions || {};
  const recipe = kitchenSettings?.recipe || {};
  input.value = url;
  if (current) {
    current.textContent = url ? `Aktualny link: ${url}` : "Brak zapisanego linku.";
  }
  if (recipeToggle instanceof HTMLInputElement) {
    recipeToggle.checked = recipe.enabled === true;
  }
  if (recipeInput instanceof HTMLTextAreaElement) {
    recipeInput.value = String(recipe.content || "");
  }
  if (recipeCurrent) {
    const length = String(recipe.content || "").trim().length;
    recipeCurrent.textContent = recipe.enabled
      ? `Tryb aktywny · ${length.toLocaleString("pl-PL")} znaków`
      : length
      ? `Przepis zapisany (${length.toLocaleString("pl-PL")} znaków), tryb wyłączony.`
      : "Tryb wyłączony. Nie zapisano jeszcze przepisu.";
  }
  if (windowSelect instanceof HTMLSelectElement) {
    windowSelect.innerHTML = (options.windowHours || [24, 48, 72, 96, 168])
      .map((hours) => `<option value="${escapeHtml(hours)}">${escapeHtml(kitchenWindowLabel(hours))}</option>`)
      .join("");
    windowSelect.value = String(sports.windowHours || 24);
  }
  if (tournamentList) {
    tournamentList.innerHTML = kitchenTournamentListMarkup(options.nextTournaments || []);
  }
  if (leagueList) {
    leagueList.innerHTML = kitchenLeagueListMarkup(
      options.leagues || [],
      sports,
    );
  }
  if (teamList) {
    teamList.innerHTML = kitchenCheckListMarkup(
      options.teams || [],
      sports.enabledTeamKeys || [],
      "team",
    );
  }
}

async function refreshKitchenSettings() {
  const input = $("kitchen-clozemaster-url");
  if (!input) return;

  setKitchenStatus("Ładuję ustawienia kitchen dashboardu...", "idle");
  try {
    kitchenSettings = await fetchKitchenSettings();
    renderKitchenSettings();
    setKitchenStatus(KITCHEN_DEFAULT_STATUS, "idle");
  } catch (error) {
    console.error("Failed to load kitchen settings:", error);
    setKitchenStatus("Nie udało się połączyć z backendem dashboardu.", "idle");
  }
}

async function persistKitchenSettings(nextUrl, message = "Link Clozemastera zapisany.") {
  const input = $("kitchen-clozemaster-url");
  if (!(input instanceof HTMLInputElement)) return;
  const url = String(nextUrl ?? input.value ?? "").trim();

  if (!isValidClozemasterUrl(url)) {
    setKitchenStatus("Wklej link z https://www.clozemaster.com/ albo zostaw puste pole.", "idle");
    return;
  }

  input.disabled = true;
  setKitchenStatus("Zapisuję link Clozemastera...", "idle");
  try {
    kitchenSettings = await saveKitchenSettings({
      clozemasterUrl: url,
      sports: collectKitchenSportsSettings(),
      recipe: collectKitchenRecipeSettings(),
    });
    renderKitchenSettings();
    flashKitchenSaved(message);
  } catch (error) {
    console.error("Failed to save kitchen settings:", error);
    setKitchenStatus(`Nie udało się zapisać linku: ${String(error?.message || error)}`, "idle");
  } finally {
    input.disabled = false;
  }
}

function renderScreensaverSettings() {
  const idleInput = $("screensaver-idle-minutes");
  const intervalSelect = $("screensaver-check-interval");
  const backgroundSelect = $("screensaver-background-mode");
  const progressStyleSelect = $("screensaver-progress-style");
  const layoutSelect = $("screensaver-layout");
  const showNextTrackToggle = $("screensaver-show-next-track");
  const nextTrackAtStartToggle = $("screensaver-next-at-start");
  const nextTrackAtEndToggle = $("screensaver-next-at-end");
  const nextTrackTimingUnitSelect = $("screensaver-next-timing-unit");
  const nextTrackStartWindowInput = $("screensaver-next-start-window");
  const nextTrackEndWindowInput = $("screensaver-next-end-window");
  const coverScaleInput = $("screensaver-cover-scale");
  const coverScaleLabel = $("screensaver-cover-scale-label");
  const controlScaleInput = $("screensaver-control-scale");
  const controlScaleLabel = $("screensaver-control-scale-label");
  const showArtistFactsToggle = $("screensaver-show-artist-facts");
  const artistFactSlideSecondsInput = $("screensaver-artist-fact-slide-seconds");
  const artistFactLayoutSelect = $("screensaver-artist-fact-layout");
  const artistFactMediaModeSelect = $("screensaver-artist-fact-media-mode");
  const current = $("spotify-screensaver-current");
  const connectLink = $("spotify-connect-link");
  const previewLink = $("spotify-screensaver-preview");
  const artistFactsPreviewLink = $("artist-facts-preview");
  if (!(idleInput instanceof HTMLInputElement)) return;

  const idleMinutes = Number(screensaverSettings?.idleMinutes || 3);
  const checkIntervalMs = Number(screensaverSettings?.checkIntervalMs || 5000);
  const backgroundMode = String(screensaverSettings?.backgroundMode || "black");
  const progressStyle = String(screensaverSettings?.progressStyle || "minimal");
  const screensaverLayout = String(screensaverSettings?.screensaverLayout || "center");
  const showNextTrack = Boolean(screensaverSettings?.showNextTrack);
  const nextTrackShowAtStart = Boolean(screensaverSettings?.nextTrackShowAtStart);
  const nextTrackShowAtEnd = screensaverSettings?.nextTrackShowAtEnd !== false;
  const nextTrackTimingUnit = String(screensaverSettings?.nextTrackTimingUnit || "seconds");
  const nextTrackStartWindow = Number(screensaverSettings?.nextTrackStartWindow ?? 12);
  const nextTrackEndWindow = Number(screensaverSettings?.nextTrackEndWindow ?? 20);
  const coverScale = Number(screensaverSettings?.coverScale || 1.08);
  const controlScale = Number(screensaverSettings?.controlScale || 1);
  const showArtistFacts = Boolean(screensaverSettings?.showArtistFacts);
  const artistFactSlideSeconds = Number(screensaverSettings?.artistFactSlideSeconds || 14);
  const artistFactLayout = String(screensaverSettings?.artistFactLayout || "side-card");
  const artistFactMediaMode = String(screensaverSettings?.artistFactMediaMode || "media");
  const spotify = screensaverSettings?.spotify || {};

  idleInput.value = String(idleMinutes);
  if (intervalSelect instanceof HTMLSelectElement) {
    intervalSelect.value = String(checkIntervalMs);
  }
  if (backgroundSelect instanceof HTMLSelectElement) {
    backgroundSelect.value = backgroundMode;
  }
  if (progressStyleSelect instanceof HTMLSelectElement) {
    progressStyleSelect.value = progressStyle;
  }
  if (layoutSelect instanceof HTMLSelectElement) {
    layoutSelect.value = screensaverLayout;
  }
  if (showNextTrackToggle instanceof HTMLInputElement) {
    showNextTrackToggle.checked = showNextTrack;
  }
  if (nextTrackAtStartToggle instanceof HTMLInputElement) {
    nextTrackAtStartToggle.checked = nextTrackShowAtStart;
  }
  if (nextTrackAtEndToggle instanceof HTMLInputElement) {
    nextTrackAtEndToggle.checked = nextTrackShowAtEnd;
  }
  if (nextTrackTimingUnitSelect instanceof HTMLSelectElement) {
    nextTrackTimingUnitSelect.value = nextTrackTimingUnit === "percent" ? "percent" : "seconds";
  }
  if (nextTrackStartWindowInput instanceof HTMLInputElement) {
    nextTrackStartWindowInput.value = String(nextTrackStartWindow);
    nextTrackStartWindowInput.step = nextTrackTimingUnit === "percent" ? "1" : "0.5";
    nextTrackStartWindowInput.max = nextTrackTimingUnit === "percent" ? "100" : "600";
  }
  if (nextTrackEndWindowInput instanceof HTMLInputElement) {
    nextTrackEndWindowInput.value = String(nextTrackEndWindow);
    nextTrackEndWindowInput.step = nextTrackTimingUnit === "percent" ? "1" : "0.5";
    nextTrackEndWindowInput.max = nextTrackTimingUnit === "percent" ? "100" : "600";
  }
  if (coverScaleInput instanceof HTMLInputElement) {
    coverScaleInput.value = String(coverScale);
  }
  if (coverScaleLabel) {
    coverScaleLabel.textContent = `Aktualny rozmiar: ${Math.round(coverScale * 100)}%`;
  }
  if (controlScaleInput instanceof HTMLInputElement) {
    controlScaleInput.value = String(controlScale);
  }
  if (controlScaleLabel) {
    controlScaleLabel.textContent = `Przyciski: ${Math.round(controlScale * 100)}%, okladka powieksza sie relatywnie.`;
  }
  if (showArtistFactsToggle instanceof HTMLInputElement) {
    showArtistFactsToggle.checked = showArtistFacts;
  }
  if (artistFactSlideSecondsInput instanceof HTMLInputElement) {
    artistFactSlideSecondsInput.value = String(artistFactSlideSeconds);
  }
  if (artistFactLayoutSelect instanceof HTMLSelectElement) {
    artistFactLayoutSelect.value = artistFactLayout;
  }
  if (artistFactMediaModeSelect instanceof HTMLSelectElement) {
    artistFactMediaModeSelect.value = artistFactMediaMode === "text" ? "text" : "media";
  }

  if (connectLink instanceof HTMLAnchorElement) {
    const next = new URL("./spotify-screensaver.html?manual=1", window.location.href).toString();
    connectLink.href = `/api/spotify/auth/start?next=${encodeURIComponent(next)}`;
    connectLink.textContent = spotify.connected ? "Reconnect Spotify" : "Connect Spotify";
  }

  if (previewLink instanceof HTMLAnchorElement) {
    previewLink.href = "./spotify-screensaver.html?manual=1";
  }
  if (artistFactsPreviewLink instanceof HTMLAnchorElement) {
    artistFactsPreviewLink.href = "./artist-facts-screensaver.html?artist=Maurice%20Ravel";
  }

  if (current) {
    const auth = spotify.connected ? "Spotify połączone" : "Spotify niepołączone";
    const configured = spotify.configured ? "konfiguracja OK" : "brak konfiguracji";
    const modeLabel = backgroundSelect instanceof HTMLSelectElement
      ? backgroundSelect.selectedOptions[0]?.textContent || backgroundMode
      : backgroundMode;
    const layoutLabel = layoutSelect instanceof HTMLSelectElement
      ? layoutSelect.selectedOptions[0]?.textContent || screensaverLayout
      : screensaverLayout;
    current.textContent = `${auth} (${configured}). Watcher wystartuje po ${idleMinutes} min bezczynności. Tło: ${modeLabel}. Layout: ${layoutLabel}.`;
  }
}

async function refreshScreensaverSettings() {
  const idleInput = $("screensaver-idle-minutes");
  if (!idleInput) return;

  setScreensaverStatus("Ładuję ustawienia Spotify screensavera...", "idle");
  try {
    screensaverSettings = await fetchScreensaverSettings();
    renderScreensaverSettings();
    setScreensaverStatus(SCREENSAVER_DEFAULT_STATUS, "idle");
  } catch (error) {
    console.error("Failed to load screensaver settings:", error);
    setScreensaverStatus("Nie udało się połączyć z backendem dashboardu.", "idle");
  }
}

async function persistScreensaverSettings(message = "Ustawienia screensavera zapisane.") {
  const idleInput = $("screensaver-idle-minutes");
  const intervalSelect = $("screensaver-check-interval");
  const backgroundSelect = $("screensaver-background-mode");
  const progressStyleSelect = $("screensaver-progress-style");
  const layoutSelect = $("screensaver-layout");
  const showNextTrackToggle = $("screensaver-show-next-track");
  const nextTrackAtStartToggle = $("screensaver-next-at-start");
  const nextTrackAtEndToggle = $("screensaver-next-at-end");
  const nextTrackTimingUnitSelect = $("screensaver-next-timing-unit");
  const nextTrackStartWindowInput = $("screensaver-next-start-window");
  const nextTrackEndWindowInput = $("screensaver-next-end-window");
  const coverScaleInput = $("screensaver-cover-scale");
  const controlScaleInput = $("screensaver-control-scale");
  const showArtistFactsToggle = $("screensaver-show-artist-facts");
  const artistFactSlideSecondsInput = $("screensaver-artist-fact-slide-seconds");
  const artistFactLayoutSelect = $("screensaver-artist-fact-layout");
  const artistFactMediaModeSelect = $("screensaver-artist-fact-media-mode");
  if (!(idleInput instanceof HTMLInputElement)) return;

  const idleMinutes = Number(idleInput.value);
  const checkIntervalMs = intervalSelect instanceof HTMLSelectElement
    ? Number(intervalSelect.value)
    : Number(screensaverSettings?.checkIntervalMs || 5000);
  const backgroundMode = backgroundSelect instanceof HTMLSelectElement
    ? backgroundSelect.value
    : String(screensaverSettings?.backgroundMode || "black");
  const progressStyle = progressStyleSelect instanceof HTMLSelectElement
    ? progressStyleSelect.value
    : String(screensaverSettings?.progressStyle || "minimal");
  const screensaverLayout = layoutSelect instanceof HTMLSelectElement
    ? layoutSelect.value
    : String(screensaverSettings?.screensaverLayout || "center");
  const showNextTrack = showNextTrackToggle instanceof HTMLInputElement
    ? showNextTrackToggle.checked
    : Boolean(screensaverSettings?.showNextTrack);
  const nextTrackShowAtStart = nextTrackAtStartToggle instanceof HTMLInputElement
    ? nextTrackAtStartToggle.checked
    : Boolean(screensaverSettings?.nextTrackShowAtStart);
  const nextTrackShowAtEnd = nextTrackAtEndToggle instanceof HTMLInputElement
    ? nextTrackAtEndToggle.checked
    : screensaverSettings?.nextTrackShowAtEnd !== false;
  const nextTrackTimingUnit = nextTrackTimingUnitSelect instanceof HTMLSelectElement
    ? nextTrackTimingUnitSelect.value
    : String(screensaverSettings?.nextTrackTimingUnit || "seconds");
  const nextTrackStartWindow = nextTrackStartWindowInput instanceof HTMLInputElement
    ? Number(nextTrackStartWindowInput.value)
    : Number(screensaverSettings?.nextTrackStartWindow ?? 12);
  const nextTrackEndWindow = nextTrackEndWindowInput instanceof HTMLInputElement
    ? Number(nextTrackEndWindowInput.value)
    : Number(screensaverSettings?.nextTrackEndWindow ?? 20);
  const coverScale = coverScaleInput instanceof HTMLInputElement
    ? Number(coverScaleInput.value)
    : Number(screensaverSettings?.coverScale || 1.08);
  const controlScale = controlScaleInput instanceof HTMLInputElement
    ? Number(controlScaleInput.value)
    : Number(screensaverSettings?.controlScale || 1);
  const showArtistFacts = showArtistFactsToggle instanceof HTMLInputElement
    ? showArtistFactsToggle.checked
    : Boolean(screensaverSettings?.showArtistFacts);
  const artistFactSlideSeconds = artistFactSlideSecondsInput instanceof HTMLInputElement
    ? Number(artistFactSlideSecondsInput.value)
    : Number(screensaverSettings?.artistFactSlideSeconds || 14);
  const artistFactLayout = artistFactLayoutSelect instanceof HTMLSelectElement
    ? artistFactLayoutSelect.value
    : String(screensaverSettings?.artistFactLayout || "side-card");
  const artistFactMediaMode = artistFactMediaModeSelect instanceof HTMLSelectElement
    ? artistFactMediaModeSelect.value
    : String(screensaverSettings?.artistFactMediaMode || "media");

  if (!Number.isFinite(idleMinutes) || idleMinutes < 0.25 || idleMinutes > 120) {
    setScreensaverStatus("Podaj czas od 0.25 do 120 minut.", "idle");
    return;
  }
  if (!Number.isFinite(nextTrackStartWindow) || !Number.isFinite(nextTrackEndWindow)) {
    setScreensaverStatus("Podaj poprawne wartosci dla next track.", "idle");
    return;
  }
  if (!Number.isFinite(artistFactSlideSeconds) || artistFactSlideSeconds < 4 || artistFactSlideSeconds > 120) {
    setScreensaverStatus("Podaj czas slajdu ciekawostki od 4 do 120 sekund.", "idle");
    return;
  }
  if (!Number.isFinite(controlScale) || controlScale < 0.1 || controlScale > 1) {
    setScreensaverStatus("Podaj rozmiar przycisków od 10% do 100%.", "idle");
    return;
  }
  const nextTrackWindowMax = nextTrackTimingUnit === "percent" ? 100 : 600;
  if (
    nextTrackStartWindow < 0
    || nextTrackEndWindow < 0
    || nextTrackStartWindow > nextTrackWindowMax
    || nextTrackEndWindow > nextTrackWindowMax
  ) {
    setScreensaverStatus(
      nextTrackTimingUnit === "percent"
        ? "Dla procentow podaj wartosci od 0 do 100."
        : "Dla sekund podaj wartosci od 0 do 600.",
      "idle",
    );
    return;
  }

  idleInput.disabled = true;
  if (intervalSelect instanceof HTMLSelectElement) intervalSelect.disabled = true;
  if (backgroundSelect instanceof HTMLSelectElement) backgroundSelect.disabled = true;
  if (progressStyleSelect instanceof HTMLSelectElement) progressStyleSelect.disabled = true;
  if (layoutSelect instanceof HTMLSelectElement) layoutSelect.disabled = true;
  if (showNextTrackToggle instanceof HTMLInputElement) showNextTrackToggle.disabled = true;
  if (nextTrackAtStartToggle instanceof HTMLInputElement) nextTrackAtStartToggle.disabled = true;
  if (nextTrackAtEndToggle instanceof HTMLInputElement) nextTrackAtEndToggle.disabled = true;
  if (nextTrackTimingUnitSelect instanceof HTMLSelectElement) nextTrackTimingUnitSelect.disabled = true;
  if (nextTrackStartWindowInput instanceof HTMLInputElement) nextTrackStartWindowInput.disabled = true;
  if (nextTrackEndWindowInput instanceof HTMLInputElement) nextTrackEndWindowInput.disabled = true;
  if (coverScaleInput instanceof HTMLInputElement) coverScaleInput.disabled = true;
  if (controlScaleInput instanceof HTMLInputElement) controlScaleInput.disabled = true;
  if (showArtistFactsToggle instanceof HTMLInputElement) showArtistFactsToggle.disabled = true;
  if (artistFactSlideSecondsInput instanceof HTMLInputElement) artistFactSlideSecondsInput.disabled = true;
  if (artistFactLayoutSelect instanceof HTMLSelectElement) artistFactLayoutSelect.disabled = true;
  if (artistFactMediaModeSelect instanceof HTMLSelectElement) artistFactMediaModeSelect.disabled = true;
  setScreensaverStatus("Zapisuję ustawienia screensavera...", "idle");
  try {
    screensaverSettings = await saveScreensaverSettings({
      idleMinutes,
      checkIntervalMs,
      backgroundMode,
      progressStyle,
      screensaverLayout,
      showNextTrack,
      nextTrackShowAtStart,
      nextTrackShowAtEnd,
      nextTrackTimingUnit,
      nextTrackStartWindow,
      nextTrackEndWindow,
      coverScale,
      controlScale,
      showArtistFacts,
      artistFactSlideSeconds,
      artistFactLayout,
      artistFactMediaMode,
    });
    renderScreensaverSettings();
    flashScreensaverSaved(message);
  } catch (error) {
    console.error("Failed to save screensaver settings:", error);
    setScreensaverStatus(`Nie udało się zapisać ustawień: ${String(error?.message || error)}`, "idle");
  } finally {
    idleInput.disabled = false;
    if (intervalSelect instanceof HTMLSelectElement) intervalSelect.disabled = false;
    if (backgroundSelect instanceof HTMLSelectElement) backgroundSelect.disabled = false;
    if (progressStyleSelect instanceof HTMLSelectElement) progressStyleSelect.disabled = false;
    if (layoutSelect instanceof HTMLSelectElement) layoutSelect.disabled = false;
    if (showNextTrackToggle instanceof HTMLInputElement) showNextTrackToggle.disabled = false;
    if (nextTrackAtStartToggle instanceof HTMLInputElement) nextTrackAtStartToggle.disabled = false;
    if (nextTrackAtEndToggle instanceof HTMLInputElement) nextTrackAtEndToggle.disabled = false;
    if (nextTrackTimingUnitSelect instanceof HTMLSelectElement) nextTrackTimingUnitSelect.disabled = false;
    if (nextTrackStartWindowInput instanceof HTMLInputElement) nextTrackStartWindowInput.disabled = false;
    if (nextTrackEndWindowInput instanceof HTMLInputElement) nextTrackEndWindowInput.disabled = false;
    if (coverScaleInput instanceof HTMLInputElement) coverScaleInput.disabled = false;
    if (controlScaleInput instanceof HTMLInputElement) controlScaleInput.disabled = false;
    if (showArtistFactsToggle instanceof HTMLInputElement) showArtistFactsToggle.disabled = false;
    if (artistFactSlideSecondsInput instanceof HTMLInputElement) artistFactSlideSecondsInput.disabled = false;
    if (artistFactLayoutSelect instanceof HTMLSelectElement) artistFactLayoutSelect.disabled = false;
    if (artistFactMediaModeSelect instanceof HTMLSelectElement) artistFactMediaModeSelect.disabled = false;
  }
}

async function handleArtistFactsUpload(event) {
  const input = event?.target;
  if (!(input instanceof HTMLInputElement) || !input.files?.length) return;
  const file = input.files[0];
  setScreensaverStatus("Czytam JSON ciekawostek...", "idle");
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    const result = await uploadArtistFacts(payload);
    flashScreensaverSaved(`Zapisano ciekawostki: ${result.artist || result.slug}.`);
  } catch (error) {
    console.error("Failed to upload artist facts:", error);
    setScreensaverStatus(`Nie udało się wgrać JSON-a: ${String(error?.message || error)}`, "idle");
  } finally {
    input.value = "";
  }
}

function collectKitchenSportsSettings() {
  const windowSelect = $("kitchen-sports-window");
  const windowHours = windowSelect instanceof HTMLSelectElement
    ? Number(windowSelect.value)
    : Number(kitchenSettings?.sports?.windowHours || 24);
  const checkedValues = (kind) => Array.from(
    document.querySelectorAll(`input[data-kitchen-kind="${kind}"]:checked`),
  ).map((input) => input.value);
  const leagueModes = Array.from(
    document.querySelectorAll("select[data-kitchen-league-mode]"),
  );
  const enabledLeagueKeys = leagueModes
    .filter((select) => select.value === "results" || select.value === "table")
    .map((select) => select.dataset.kitchenLeagueMode);
  const standingsLeagueKeys = leagueModes
    .filter((select) => select.value === "table")
    .map((select) => select.dataset.kitchenLeagueMode);
  return {
    windowHours,
    enabledLeagueKeys,
    standingsLeagueKeys,
    enabledTeamKeys: checkedValues("team"),
  };
}

function collectKitchenRecipeSettings() {
  const toggle = $("kitchen-recipe-enabled");
  const input = $("kitchen-recipe-content");
  return {
    enabled: toggle instanceof HTMLInputElement
      ? toggle.checked
      : kitchenSettings?.recipe?.enabled === true,
    content: input instanceof HTMLTextAreaElement
      ? input.value
      : String(kitchenSettings?.recipe?.content || ""),
  };
}

async function persistKitchenRecipeSettings(message = "Przepis zapisany.") {
  const toggle = $("kitchen-recipe-enabled");
  const input = $("kitchen-recipe-content");
  const button = $("kitchen-recipe-save");
  if (!(toggle instanceof HTMLInputElement) || !(input instanceof HTMLTextAreaElement)) return;

  const recipe = collectKitchenRecipeSettings();
  if (recipe.enabled && !recipe.content.trim()) {
    toggle.checked = false;
    input.focus();
    setKitchenStatus("Najpierw wklej treść przepisu, a potem włącz tryb.", "idle");
    return;
  }

  toggle.disabled = true;
  input.disabled = true;
  if (button instanceof HTMLButtonElement) button.disabled = true;
  setKitchenStatus(recipe.enabled ? "Zapisuję i włączam tryb przepisu..." : "Zapisuję przepis...", "idle");
  try {
    const clozemasterInput = $("kitchen-clozemaster-url");
    kitchenSettings = await saveKitchenSettings({
      clozemasterUrl: clozemasterInput instanceof HTMLInputElement
        ? clozemasterInput.value
        : kitchenSettings?.clozemasterUrl,
      sports: collectKitchenSportsSettings(),
      recipe,
    });
    renderKitchenSettings();
    flashKitchenSaved(recipe.enabled ? "Przepis zapisany. Tryb włączony na tablecie." : message);
  } catch (error) {
    console.error("Failed to save kitchen recipe:", error);
    setKitchenStatus(`Nie udało się zapisać przepisu: ${String(error?.message || error)}`, "idle");
  } finally {
    toggle.disabled = false;
    input.disabled = false;
    if (button instanceof HTMLButtonElement) button.disabled = false;
  }
}

async function persistKitchenSportsSettings({ rerender = true } = {}) {
  const input = $("kitchen-clozemaster-url");
  const clozemasterUrl = input instanceof HTMLInputElement ? input.value : kitchenSettings?.clozemasterUrl;
  setKitchenStatus("Zapisuję ustawienia wyników...", "idle");
  try {
    kitchenSettings = await saveKitchenSettings({
      clozemasterUrl,
      sports: collectKitchenSportsSettings(),
      recipe: collectKitchenRecipeSettings(),
    });
    if (rerender) {
      renderKitchenSettings();
    }
    flashKitchenSaved("Ustawienia wyników zapisane.");
  } catch (error) {
    console.error("Failed to save sports settings:", error);
    setKitchenStatus(`Nie udało się zapisać ustawień: ${String(error?.message || error)}`, "idle");
  }
}

function scheduleKitchenSportsSave() {
  if (kitchenSportsSaveTimer) {
    window.clearTimeout(kitchenSportsSaveTimer);
  }
  setKitchenStatus("Zaraz zapiszę ustawienia wyników...", "idle");
  kitchenSportsSaveTimer = window.setTimeout(async () => {
    kitchenSportsSaveTimer = 0;
    await persistKitchenSportsSettings({ rerender: false });
  }, 350);
}

function persist(message) {
  commitDashboardWidgetState(message);
}

function commitDashboardWidgetState(message, { rerender = true } = {}) {
  if (!state) return null;

  if (isDashboardModalContext()) {
    modalDashboardDirty = true;
    if (rerender) {
      renderLayoutControls();
      renderWidgetList();
    }
    setStatus(`${message} Zapis nastąpi po kliknięciu „Zapisz i zamknij”.`, "idle");
    return state;
  }

  state = saveDashboardWidgetConfig(state);
  if (rerender) {
    renderLayoutControls();
    renderWidgetList();
  }
  flashSaved(message);
  return state;
}

function flushPendingHeaderTextSave() {
  if (!headerTextPendingRow) return;
  const row = headerTextPendingRow;
  headerTextPendingRow = null;
  if (headerTextSaveTimer) {
    window.clearTimeout(headerTextSaveTimer);
    headerTextSaveTimer = 0;
  }
  persistHeaderTextFromRow(row, "Tekst nagłówka zapisany.");
}

function savePendingModalDashboardChanges() {
  if (!isDashboardModalContext()) return;
  flushPendingHeaderTextSave();
  if (!modalDashboardDirty || !state) return;
  state = saveDashboardWidgetConfig(state);
  modalDashboardDirty = false;
  flashSaved("Ustawienia dashboardu zapisane.");
}

function persistHeaderTextFromRow(row, message = "Tekst nagłówka zapisany.") {
  if (!row || !state) return;
  const key = row.dataset.key || "";
  if (!key) return;

  const titleInput = row.querySelector('input[data-action="header-title"]');
  state = setDashboardWidgetHeaderText(state, key, {
    title: titleInput?.value || "",
    subtitle: "",
  });

  if (isDashboardModalContext()) {
    state = saveDashboardWidgetConfig(state);
    flashSaved(message);
    return;
  }
  commitDashboardWidgetState(message, { rerender: false });
}

function scheduleHeaderTextSave(row) {
  if (headerTextSaveTimer) {
    window.clearTimeout(headerTextSaveTimer);
  }
  headerTextPendingRow = row;
  headerTextSaveTimer = window.setTimeout(() => {
    headerTextSaveTimer = 0;
    headerTextPendingRow = null;
    persistHeaderTextFromRow(row);
  }, 300);
}

async function refreshNetworkDevices() {
  const list = $("network-device-list");
  if (!list) {
    return;
  }

  if (!getNetworkApiBase()) {
    networkDevices = [];
    renderNetworkDeviceList();
    return;
  }

  setNetworkStatus("Ładuję urządzenia z lokalnego backendu...", "idle");
  try {
    const devices = await fetchNetworkDevices();
    networkDevices = devices
      .slice()
      .sort((a, b) => {
        const onlineDiff = Number(Boolean(b?.is_online)) - Number(Boolean(a?.is_online));
        if (onlineDiff !== 0) return onlineDiff;
        const aTime = parseDate(a?.last_seen)?.getTime() || 0;
        const bTime = parseDate(b?.last_seen)?.getTime() || 0;
        return bTime - aTime;
      });
    renderNetworkDeviceList();
    setNetworkStatus(NETWORK_DEFAULT_STATUS, "idle");
  } catch (error) {
    console.error("Failed to load network devices:", error);
    networkDevices = [];
    renderNetworkDeviceList();
    setNetworkStatus(
      "Nie ma połączenia z monitorem sieci. Uruchom start-dev.cmd albo python run_network_monitor.py.",
      "idle",
    );
  }
}

function bindSectionNavigation() {
  const nav = document.querySelector(".settings-section-nav");
  if (!nav) return;

  nav.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-settings-section-link]");
    if (!(button instanceof HTMLButtonElement)) return;

    setActiveSection(button.dataset.settingsSectionLink, {
      syncHash: isSettingsPage(),
    });
  });

  nav.addEventListener("keydown", (event) => {
    const button = event.target.closest("button[data-settings-section-link]");
    if (!(button instanceof HTMLButtonElement)) return;

    const buttons = Array.from(
      nav.querySelectorAll("button[data-settings-section-link]"),
    );
    const currentIndex = buttons.indexOf(button);
    if (currentIndex < 0) return;

    let nextIndex = currentIndex;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % buttons.length;
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = buttons.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    buttons[nextIndex]?.focus();
    setActiveSection(buttons[nextIndex]?.dataset.settingsSectionLink, {
      syncHash: isSettingsPage(),
    });
  });

  if (isSettingsPage()) {
    window.addEventListener("hashchange", () => {
      setActiveSection(window.location.hash, { syncHash: false });
    });
  }
}

function bindListInteractions() {
  const list = $("settings-widget-list");
  if (!list) return;

  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    const row = event.target.closest(".settings-widget-row[data-key]");
    if (!button || !row || !state) return;

    const key = row.dataset.key || "";
    if (!key) return;

    if (button.dataset.action === "up") {
      state = moveDashboardWidget(state, key, -1);
      persist("Kolejność widgetów zapisana.");
      return;
    }

    if (button.dataset.action === "down") {
      state = moveDashboardWidget(state, key, 1);
      persist("Kolejność widgetów zapisana.");
    }
  });

  list.addEventListener("input", (event) => {
    const headerInput = event.target.closest('input[data-action^="header-"]');
    if (!headerInput) return;
    const row = event.target.closest(".settings-widget-row[data-key]");
    if (!row || !state) return;

    scheduleHeaderTextSave(row);
  });

  list.addEventListener("change", (event) => {
    const headerInput = event.target.closest('input[data-action^="header-"]');
    if (headerInput) {
      const row = event.target.closest(".settings-widget-row[data-key]");
      if (!row || !state) return;
      if (headerTextSaveTimer) {
        window.clearTimeout(headerTextSaveTimer);
        headerTextSaveTimer = 0;
      }
      headerTextPendingRow = null;
      persistHeaderTextFromRow(row);
      return;
    }

    const spanSelect = event.target.closest('select[data-action="span"]');
    if (spanSelect) {
      const row = event.target.closest(".settings-widget-row[data-key]");
      if (!row || !state) return;

      const key = row.dataset.key || "";
      if (!key) return;

      state = setDashboardWidgetSpan(state, key, spanSelect.value);
      persist("Szerokość widgetu zapisana.");
      return;
    }

    const toggle = event.target.closest('input[data-action="toggle"]');
    const row = event.target.closest(".settings-widget-row[data-key]");
    if (!toggle || !row || !state) return;

    const key = row.dataset.key || "";
    if (!key) return;

    state = setDashboardWidgetVisibility(state, key, toggle.checked);
    persist(toggle.checked ? "Widget włączony." : "Widget ukryty.");
  });
}

function bindPageActions() {
  $("settings-header-font-size")?.addEventListener("input", (event) => {
    if (!state) return;
    state = setDashboardHeaderFontSize(state, event.target.value);
    commitDashboardWidgetState(`Rozmiar nagłówków: ${state.headers.titleFontSize}px.`);
  });

  $("settings-column-picker")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-columns]");
    if (!button || !state) return;

    state = setDashboardColumnCount(state, button.dataset.columns);
    persist(`Widok ${state.layout.columns}-kolumnowy zapisany.`);
  });

  $("settings-auto-fit")?.addEventListener("change", (event) => {
    if (!state) return;
    state = setDashboardAutoFitEnabled(state, event.target.checked);
    persist(event.target.checked
      ? "Kompaktowe dopasowanie widgetów włączone."
      : "Kompaktowe dopasowanie widgetów wyłączone.");
  });

  $("settings-heart-rate-history-shortcut")?.addEventListener("change", (event) => {
    if (!state) return;
    state = setDashboardHeartRateHistoryShortcutEnabled(state, event.target.checked);
    persist(event.target.checked
      ? "Skrót do historii HR włączony."
      : "Skrót do historii HR wyłączony.");
  });

  $("settings-cleaning-lock")?.addEventListener("change", (event) => {
    if (!state) return;
    state = setDashboardCleaningLockEnabled(state, event.target.checked);
    persist(event.target.checked
      ? "Blokada dashboardu za sprzątanie włączona."
      : "Blokada dashboardu za sprzątanie wyłączona.");
  });

  $("settings-show-all")?.addEventListener("click", () => {
    if (!state) return;
    state = setAllDashboardWidgetsVisibility(state, true);
    persist("Wszystkie widgety są aktywne.");
  });

  $("settings-reset")?.addEventListener("click", async () => {
    if (isDashboardModalContext()) {
      state = getDefaultDashboardWidgetConfig();
      modalDashboardDirty = true;
      renderLayoutControls();
      renderWidgetList();
      setStatus('Domyślny układ gotowy. Zapis nastąpi po kliknięciu „Zapisz i zamknij”.', "idle");
      return;
    }
    clearDashboardWidgetConfig();
    await refreshState();
    flashSaved("Przywrócono domyślny układ dashboardu.");
  });

  $("dashboard-tablet-refresh")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (button instanceof HTMLButtonElement) {
      button.disabled = true;
    }
    setKitchenStatus("Wysyłam sygnał odświeżenia dashboardu na tablecie...", "idle");
    try {
      await requestDashboardTabletRefresh();
      flashKitchenSaved("Wysłano sygnał. Tablet przeładuje dashboard przy najbliższym sprawdzeniu.");
    } catch (error) {
      console.error("Failed to request dashboard refresh:", error);
      setKitchenStatus(`Nie udało się wysłać odświeżenia: ${String(error?.message || error)}`, "idle");
    } finally {
      if (button instanceof HTMLButtonElement) {
        button.disabled = false;
      }
    }
  });

  $("network-settings-refresh")?.addEventListener("click", async () => {
    await refreshNetworkDevices();
  });

  $("kitchen-clozemaster-save")?.addEventListener("click", async () => {
    await persistKitchenSettings();
  });

  $("kitchen-clozemaster-reset")?.addEventListener("click", async () => {
    await persistKitchenSettings("", "Przywrócono domyślny link Clozemastera.");
  });

  $("kitchen-clozemaster-url")?.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    await persistKitchenSettings();
  });

  $("kitchen-recipe-save")?.addEventListener("click", async () => {
    await persistKitchenRecipeSettings();
  });

  $("kitchen-recipe-enabled")?.addEventListener("change", async (event) => {
    const enabled = event.currentTarget instanceof HTMLInputElement && event.currentTarget.checked;
    await persistKitchenRecipeSettings(enabled ? "Przepis zapisany." : "Tryb przepisu wyłączony.");
  });

  $("kitchen-sports-window")?.addEventListener("change", () => {
    scheduleKitchenSportsSave();
  });

  $("kitchen-league-list")?.addEventListener("change", (event) => {
    if (!event.target.closest("select[data-kitchen-league-mode]")) return;
    scheduleKitchenSportsSave();
  });

  $("kitchen-team-list")?.addEventListener("change", (event) => {
    if (!event.target.closest("input[data-kitchen-kind]")) return;
    scheduleKitchenSportsSave();
  });

  $("kitchen-debug-refresh")?.addEventListener("click", async () => {
    await refreshKitchenDebug();
  });

  $("screensaver-idle-minutes")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-idle-minutes")?.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    await persistScreensaverSettings();
  });

  $("screensaver-check-interval")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-background-mode")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-progress-style")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-layout")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-show-next-track")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-next-at-start")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-next-at-end")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-next-timing-unit")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  ["screensaver-next-start-window", "screensaver-next-end-window"].forEach((id) => {
    $(id)?.addEventListener("change", async () => {
      await persistScreensaverSettings();
    });
    $(id)?.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      await persistScreensaverSettings();
    });
  });

  $("screensaver-cover-scale")?.addEventListener("input", (event) => {
    const input = event.target;
    const label = $("screensaver-cover-scale-label");
    if (input instanceof HTMLInputElement && label) {
      label.textContent = `Aktualny rozmiar: ${Math.round(Number(input.value) * 100)}%`;
    }
  });

  $("screensaver-cover-scale")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-control-scale")?.addEventListener("input", (event) => {
    const input = event.target;
    const label = $("screensaver-control-scale-label");
    if (input instanceof HTMLInputElement && label) {
      label.textContent = `Przyciski: ${Math.round(Number(input.value) * 100)}%, okladka powieksza sie relatywnie.`;
    }
  });

  $("screensaver-control-scale")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-show-artist-facts")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-artist-fact-slide-seconds")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-artist-fact-slide-seconds")?.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    await persistScreensaverSettings();
  });

  $("screensaver-artist-fact-layout")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("screensaver-artist-fact-media-mode")?.addEventListener("change", async () => {
    await persistScreensaverSettings();
  });

  $("artist-facts-upload")?.addEventListener("change", async (event) => {
    await handleArtistFactsUpload(event);
  });

  $("network-notifications-toggle")?.addEventListener("change", (event) => {
    const toggle = event.target;
    if (!(toggle instanceof HTMLInputElement)) return;

    const enabled = setNetworkStatusNotificationsEnabled(toggle.checked);
    toggle.checked = enabled;
    flashNetworkSaved(
      enabled
        ? "Powiadomienia sieci lokalnej włączone."
        : "Powiadomienia sieci lokalnej wyłączone.",
    );
  });
}

function bindNetworkDeviceInteractions() {
  const list = $("network-device-list");
  if (!list) return;

  async function saveFromRow(row, override = null) {
    const mac = row?.dataset?.mac || "";
    if (!mac) return;

    const nameInput = row.querySelector('[data-field="name"]');
    const ownerInput = row.querySelector('[data-field="owner"]');
    const categorySelect = row.querySelector('[data-field="category"]');
    if (!(nameInput instanceof HTMLInputElement)) return;
    if (!(ownerInput instanceof HTMLInputElement)) return;
    if (!(categorySelect instanceof HTMLSelectElement)) return;

    const fields = [nameInput, ownerInput, categorySelect];
    const payload = override || {
      mac,
      name: nameInput.value,
      category: categorySelect.value,
      owner: ownerInput.value,
    };

    fields.forEach((field) => {
      field.disabled = true;
    });
    row.classList.add("is-saving");

    try {
      await saveNetworkDeviceProfile({
        mac,
        name: payload.name,
        category: payload.category,
        owner: payload.owner,
      });
      await refreshNetworkDevices();
      if (payload.name || payload.category || payload.owner) {
        flashNetworkSaved("Profil urządzenia zapisany.");
      } else {
        flashNetworkSaved("Profil urządzenia wyczyszczony.");
      }
    } catch (error) {
      console.error("Failed to save device profile:", error);
      setNetworkStatus(
        `Nie udało się zapisać profilu: ${String(error?.message || error)}`,
        "idle",
      );
    } finally {
      fields.forEach((field) => {
        field.disabled = false;
      });
      row.classList.remove("is-saving");
    }
  }

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    const row = event.target.closest(".settings-device-row[data-mac]");
    if (!button || !row) return;

    if (button.dataset.action === "save-device-profile") {
      await saveFromRow(row);
      return;
    }

    if (button.dataset.action === "clear-device-profile") {
      const nameInput = row.querySelector('[data-field="name"]');
      const ownerInput = row.querySelector('[data-field="owner"]');
      const categorySelect = row.querySelector('[data-field="category"]');

      if (nameInput instanceof HTMLInputElement) nameInput.value = "";
      if (ownerInput instanceof HTMLInputElement) ownerInput.value = "";
      if (categorySelect instanceof HTMLSelectElement) categorySelect.value = "";

      await saveFromRow(row, {
        mac: row.dataset.mac || "",
        name: "",
        category: "",
        owner: "",
      });
    }
  });

  list.addEventListener("keydown", async (event) => {
    const input = event.target.closest(".settings-device-input, .settings-device-select");
    const row = event.target.closest(".settings-device-row[data-mac]");
    if (!(input instanceof HTMLInputElement) && !(input instanceof HTMLSelectElement)) return;
    if (!row) return;
    if (event.key !== "Enter") return;

    event.preventDefault();
    await saveFromRow(row);
  });
}

async function openModal() {
  const overlay = $("settings-overlay");
  if (!overlay) return;

  if (!overlay.hidden || settingsModalLoading) {
    overlay.hidden = false;
    document.body.classList.add("settings-modal-open");
    setStatus(getDashboardStatusDefault(), "idle");
    return;
  }

  lastFocusedEl = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;

  overlay.hidden = false;
  document.body.classList.add("settings-modal-open");
  $("settings-close-btn")?.focus();
  modalDashboardDirty = false;

  settingsModalLoading = true;
  try {
    renderNetworkNotificationSettings();
    await refreshState();
    setStatus(MODAL_DEFAULT_STATUS, "idle");
    await Promise.allSettled([
      refreshNetworkDevices(),
      refreshKitchenSettings(),
      refreshScreensaverSettings(),
    ]);
  } finally {
    settingsModalLoading = false;
  }
}

async function closeModal() {
  const overlay = $("settings-overlay");
  if (!overlay || overlay.hidden) return;

  savePendingModalDashboardChanges();
  overlay.hidden = true;
  document.body.classList.remove("settings-modal-open");
  lastFocusedEl?.focus?.();
}

function bindModalInteractions() {
  const overlay = $("settings-overlay");
  const trigger = $("dashboard-settings-trigger");
  const closeBtn = $("settings-close-btn");

  if (!overlay) return;

  trigger?.addEventListener("click", (event) => {
    event.preventDefault();
    openModal();
  });

  closeBtn?.addEventListener("click", () => {
    closeModal();
  });

  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) {
      closeModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !overlay.hidden) {
      closeModal();
    }
  });
}

onDomReady(async () => {
  bindSectionNavigation();
  bindListInteractions();
  bindNetworkDeviceInteractions();
  bindPageActions();
  bindModalInteractions();

  setActiveSection(
    isSettingsPage() ? window.location.hash || PAGE_DEFAULT_SECTION : DEFAULT_SECTION,
    { syncHash: isSettingsPage() },
  );

  renderNetworkNotificationSettings();

  // Na dashboardzie dane ustawień pobieramy dopiero po otwarciu modala.
  // Osobna strona ustawień nadal inicjalizuje wszystko od razu.
  if (!isSettingsPage()) return;

  setStatus("Ładuję ustawienia...", "idle");
  setNetworkStatus("Ładuję urządzenia z monitora sieci...", "idle");
  setKitchenStatus("Ładuję ustawienia kitchen dashboardu...", "idle");
  setScreensaverStatus("Ładuję ustawienia Spotify screensavera...", "idle");

  await refreshState();
  await refreshNetworkDevices();
  await refreshKitchenSettings();
  await refreshScreensaverSettings();
});
