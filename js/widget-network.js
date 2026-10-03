import { onDomReady } from './dom-ready.js';
import {
  fetchNetworkDevices,
  fetchNetworkDeviceHistory,
  fetchNetworkSummary,
  getNetworkApiBase,
} from "./network-monitor-api.js";
import {
  getNetworkStatusNotificationsEnabled,
  NETWORK_STATUS_NOTIFICATIONS_CHANGED_EVENT,
  NETWORK_STATUS_NOTIFICATIONS_STORAGE_KEY,
} from "./network-notification-settings.js";
import { escapeHtml } from "./utils.js";

const MIN_REFRESH_MS = 15_000;
const DEFAULT_REFRESH_MS = 30_000;
const SCAN_TICK_MS = 1_000;
const ALL_HISTORY_DEVICE_KEY = "__all__";
const HIDDEN_ONLINE_STORAGE_KEY = "networkWidgetHiddenOnlineDeviceKeys";
const HIDDEN_RECENT_STORAGE_KEY = "networkWidgetHiddenRecentDeviceKeys";
const SHOWN_IP_ONLY_ONLINE_STORAGE_KEY = "networkWidgetShownIpOnlyOnlineDeviceKeys";
const SHOWN_IP_ONLY_RECENT_STORAGE_KEY = "networkWidgetShownIpOnlyRecentDeviceKeys";
const NETWORK_TOAST_STACK_ID = "network-status-toast-stack";
const NETWORK_TOAST_DURATION_MS = 60_000;
const NETWORK_TOAST_MAX = 6;
const PLAY_SESSION_DEVICE_MACS = new Set(["5C:84:3C:29:74:5F"]);
const PRESENCE_OWNER_GROUPS = [
  { key: "ja", label: "Ja" },
];
const HISTORY_WINDOWS = [
  { key: "day", label: "Dzień" },
  { key: "week", label: "Tydzień" },
  { key: "month", label: "Miesiąc" },
];
const DEVICE_CATEGORY_LABELS = {
  personal: "osobiste",
  household: "domowe",
  iot: "iot",
  infrastructure: "infrastruktura",
};

const $ = (id) => document.getElementById(id);
const API_BASE = getNetworkApiBase();

let lastScanAt = null;
let currentDevices = [];
let selectedHistoryDeviceKey = null;
let selectedHistoryDay = null;
let selectedHistorySnapshot = null;
let historyRequestToken = 0;
let selectedPresenceSnapshot = null;
let presenceRequestToken = 0;
let currentSummary = {};
let showHiddenOnline = false;
let showHiddenRecent = false;
let hiddenOnlineDeviceKeys = loadDeviceKeySet(HIDDEN_ONLINE_STORAGE_KEY);
let hiddenRecentDeviceKeys = loadHiddenRecentDeviceKeys();
let shownIpOnlyOnlineDeviceKeys = loadDeviceKeySet(SHOWN_IP_ONLY_ONLINE_STORAGE_KEY);
let shownIpOnlyRecentDeviceKeys = loadDeviceKeySet(SHOWN_IP_ONLY_RECENT_STORAGE_KEY);
let previousDeviceStatusMap = new Map();
let statusNotificationBaselineReady = false;
let statusNotificationsEnabled = getNetworkStatusNotificationsEnabled();
let networkToastLifecycleBound = false;
let refreshTimerId = 0;
let refreshInFlight = false;
const networkToastStates = new Map();
const historyFetchCache = new Map();

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function getRefreshIntervalMs(summary = currentSummary) {
  const scanIntervalSeconds = Number(summary?.scan_interval_seconds || 0);
  if (Number.isFinite(scanIntervalSeconds) && scanIntervalSeconds > 0) {
    return Math.max(MIN_REFRESH_MS, scanIntervalSeconds * 1000);
  }
  return DEFAULT_REFRESH_MS;
}

function scheduleWidgetRefresh(delayMs = getRefreshIntervalMs()) {
  if (refreshTimerId) {
    window.clearTimeout(refreshTimerId);
  }
  refreshTimerId = window.setTimeout(() => {
    refreshTimerId = 0;
    refreshWidget();
  }, Math.max(MIN_REFRESH_MS, Number(delayMs) || DEFAULT_REFRESH_MS));
}

function clearHistoryFetchCache() {
  historyFetchCache.clear();
}

function historyCacheKey(deviceKey, day) {
  return `${String(deviceKey || "").trim()}::${String(day || "").trim()}`;
}

function fetchHistorySnapshotCached(deviceKey, day) {
  const key = historyCacheKey(deviceKey, day);
  if (!key.trim()) return Promise.resolve(null);

  const cached = historyFetchCache.get(key);
  if (cached) return cached;

  const request = fetchNetworkDeviceHistory(deviceKey, day).finally(() => {
    historyFetchCache.delete(key);
  });
  historyFetchCache.set(key, request);
  return request;
}

function canUseStorage() {
  return typeof window !== "undefined" && !!window.localStorage;
}

function loadDeviceKeySet(storageKey) {
  if (!canUseStorage()) return new Set();
  try {
    const raw = JSON.parse(window.localStorage.getItem(storageKey) || "[]");
    if (!Array.isArray(raw)) return new Set();
    return new Set(raw.map((item) => String(item || "").trim()).filter(Boolean));
  } catch {
    return new Set();
  }
}

function loadHiddenRecentDeviceKeys() {
  return loadDeviceKeySet(HIDDEN_RECENT_STORAGE_KEY);
}

function saveDeviceKeySet(storageKey, values) {
  if (!canUseStorage()) return;
  try {
    const payload = Array.from(values).sort();
    window.localStorage.setItem(storageKey, JSON.stringify(payload));
  } catch {
    // ignore storage failures
  }
}

function saveHiddenRecentDeviceKeys() {
  saveDeviceKeySet(HIDDEN_RECENT_STORAGE_KEY, hiddenRecentDeviceKeys);
}

function saveHiddenOnlineDeviceKeys() {
  saveDeviceKeySet(HIDDEN_ONLINE_STORAGE_KEY, hiddenOnlineDeviceKeys);
}

function saveShownIpOnlyRecentDeviceKeys() {
  saveDeviceKeySet(SHOWN_IP_ONLY_RECENT_STORAGE_KEY, shownIpOnlyRecentDeviceKeys);
}

function saveShownIpOnlyOnlineDeviceKeys() {
  saveDeviceKeySet(SHOWN_IP_ONLY_ONLINE_STORAGE_KEY, shownIpOnlyOnlineDeviceKeys);
}

function deviceKeyOf(device) {
  return String(device?.device_key || "").trim();
}

function isIpOnlyDevice(device) {
  const ip = String(device?.ip || "").trim();
  const mac = String(device?.mac || "").trim();
  return Boolean(ip) && !mac;
}

function isHiddenRecentDevice(device) {
  const deviceKey = deviceKeyOf(device);
  if (!deviceKey) return false;
  if (hiddenRecentDeviceKeys.has(deviceKey)) return true;
  return isIpOnlyDevice(device) && !shownIpOnlyRecentDeviceKeys.has(deviceKey);
}

function isHiddenOnlineDevice(device) {
  const deviceKey = deviceKeyOf(device);
  if (!deviceKey) return false;
  if (hiddenOnlineDeviceKeys.has(deviceKey)) return true;
  return isIpOnlyDevice(device) && !shownIpOnlyOnlineDeviceKeys.has(deviceKey);
}

function findCurrentDeviceByKey(deviceKey) {
  const key = String(deviceKey || "").trim();
  if (!key) return null;
  return currentDevices.find((device) => deviceKeyOf(device) === key) || null;
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatShortAge(value) {
  const date = parseDate(value);
  if (!date) return "--";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  return `${days}d`;
}

function formatRelative(value) {
  const date = parseDate(value);
  if (!date) return "brak danych";
  const diffSeconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(diffSeconds);
  if (abs < 15) return "przed chwilą";

  const rtf = new Intl.RelativeTimeFormat("pl", { numeric: "auto" });
  if (abs < 3600) {
    return rtf.format(Math.round(diffSeconds / 60), "minute");
  }
  if (abs < 86_400) {
    return rtf.format(Math.round(diffSeconds / 3600), "hour");
  }
  return rtf.format(Math.round(diffSeconds / 86_400), "day");
}

function formatAbsolute(value) {
  const date = parseDate(value);
  if (!date) return "-";
  try {
    return new Intl.DateTimeFormat("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  } catch {
    return date.toISOString().slice(0, 16).replace("T", " ");
  }
}

function formatTimeOnly(value) {
  const date = parseDate(value);
  if (!date) return "--:--";
  try {
    return new Intl.DateTimeFormat("pl-PL", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  } catch {
    return date.toISOString().slice(11, 16);
  }
}

function formatDayOnly(value) {
  const date = parseDate(value);
  if (!date) return "--.--";
  try {
    return new Intl.DateTimeFormat("pl-PL", {
      day: "2-digit",
      month: "2-digit",
    }).format(date);
  } catch {
    return date.toISOString().slice(8, 10) + "." + date.toISOString().slice(5, 7);
  }
}

function toLocalDayValue(value = new Date()) {
  const date = value instanceof Date ? value : (parseDate(value) || new Date());
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDayInputValue(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "--/--/----";
  return `${match[3]}/${match[2]}/${match[1]}`;
}

function shiftDayValue(value, offsetDays) {
  const match = String(value || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return toLocalDayValue(new Date());
  const shifted = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]) + Number(offsetDays || 0),
  );
  return toLocalDayValue(shifted);
}

function openHistoryDayPicker() {
  const input = $("network-history-day");
  if (!input || input.disabled) return;
  if (typeof input.showPicker === "function") {
    try {
      input.showPicker();
      return;
    } catch {
      // fallback below
    }
  }
  input.focus({ preventScroll: true });
  input.click();
}

function formatEventRange(startValue, endValue) {
  const start = parseDate(startValue);
  const end = parseDate(endValue);
  if (!start || !end) return null;

  const sameDay =
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth() &&
    start.getDate() === end.getDate();

  if (sameDay) {
    return `${formatTimeOnly(start)} - ${formatTimeOnly(end)}`;
  }

  return `${formatDayOnly(start)} ${formatTimeOnly(start)} - ${formatDayOnly(end)} ${formatTimeOnly(end)}`;
}

function formatDurationFromSeconds(value) {
  const seconds = Math.max(0, Number(value || 0));
  if (!Number.isFinite(seconds)) return "0m";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86_400)} d`;
}

function formatWindowLabel(seconds) {
  const safe = Math.max(0, Number(seconds || 0));
  if (!Number.isFinite(safe) || safe <= 0) return "0 min";
  if (safe < 3600) return `${Math.max(1, Math.round(safe / 60))} min danych`;
  if (safe < 86_400) {
    const hours = Math.floor(safe / 3600);
    const minutes = Math.round((safe % 3600) / 60);
    return minutes ? `${hours}h ${minutes}m danych` : `${hours}h danych`;
  }
  return `${Math.round(safe / 86_400)} d danych`;
}

function formatAverageOnlineCount(value) {
  const safe = Number(value || 0);
  if (!Number.isFinite(safe)) return "0";
  return safe.toLocaleString("pl-PL", {
    minimumFractionDigits: safe % 1 === 0 ? 0 : 1,
    maximumFractionDigits: 1,
  });
}

function classToken(value) {
  return String(value || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";
}

function normalizeDisplayMac(value) {
  return String(value || "")
    .trim()
    .toUpperCase()
    .replace(/[^A-F0-9]/g, "")
    .match(/.{1,2}/g)?.join(":") || "";
}

function isPlaySessionDeviceForDisplay(device) {
  const normalizedMac = normalizeDisplayMac(device?.mac || device?.device_mac);
  return normalizedMac ? PLAY_SESSION_DEVICE_MACS.has(normalizedMac) : false;
}

function normalizePlaySessionEvent(event, device = null) {
  if (!isPlaySessionDeviceForDisplay(device || event)) return event;
  const reasonCode = String(event?.reason_code || "");
  if (reasonCode === "returned_home") {
    return {
      ...event,
      reason_code: "started_playing",
      reason_label: "Zaczęli grać",
      reason_detail: "Konsola znowu pojawiła się w lokalnej sieci.",
    };
  }
  if (reasonCode === "left_home") {
    return {
      ...event,
      reason_code: "stopped_playing",
      reason_label: "Skończyli grać",
      reason_detail: "Konsola przestała odpowiadać w lokalnej sieci.",
    };
  }
  return event;
}

function normalizePlaySessionInsight(insight, device = null) {
  if (!isPlaySessionDeviceForDisplay(device)) return insight;
  if (String(insight?.kind || "") === "returned_home") {
    return {
      ...insight,
      kind: "started_playing",
      label: "Zaczęli grać",
    };
  }
  if (String(insight?.kind || "") === "left_home") {
    return {
      ...insight,
      kind: "stopped_playing",
      label: "Skończyli grać",
    };
  }
  return insight;
}

function getOwnerPresenceLabel(owner, reasonCode) {
  const ownerLabel = String(owner || "").trim();
  if (!ownerLabel) return "";

  const normalizedOwner = ownerLabel.toLowerCase();
  if (reasonCode === "returned_home") {
    return normalizedOwner === "ja"
      ? "Wróciłem do domu"
      : `${ownerLabel} wrócił do domu`;
  }
  if (reasonCode === "left_home") {
    return normalizedOwner === "ja"
      ? "Wyszedłem z domu"
      : `${ownerLabel} wyszedł z domu`;
  }
  return "";
}

function normalizeOwnerPresenceEvent(event, device = null) {
  const owner = String(event?.device_owner || device?.owner || "").trim();
  if (!owner) return event;
  const reasonLabel = getOwnerPresenceLabel(owner, String(event?.reason_code || ""));
  if (!reasonLabel) return event;
  return {
    ...event,
    reason_label: reasonLabel,
  };
}

function normalizeOwnerPresenceInsight(insight, device = null) {
  const owner = String(device?.owner || "").trim();
  if (!owner) return insight;
  const label = getOwnerPresenceLabel(owner, String(insight?.kind || ""));
  if (!label) return insight;
  return {
    ...insight,
    label,
  };
}

function normalizeDisplayEvent(event, device = null) {
  return normalizeOwnerPresenceEvent(
    normalizePlaySessionEvent(event, device),
    device,
  );
}

function normalizeDisplayInsight(insight, device = null) {
  return normalizeOwnerPresenceInsight(
    normalizePlaySessionInsight(insight, device),
    device,
  );
}

function bundleNetworkIssueTimelineEvents(events) {
  const grouped = new Map();
  const ordered = [];

  (events || []).forEach((event) => {
    const isNetworkIssue = String(event?.reason_code || "") === "network_issue";
    if (!isNetworkIssue) {
      ordered.push(event);
      return;
    }
    const key = `${String(event?.type || "")}:${String(event?.at || "")}:${String(event?.reason_code || "")}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        ...event,
        grouped_events: [event],
      });
      ordered.push(grouped.get(key));
      return;
    }
    grouped.get(key)?.grouped_events?.push(event);
  });

  return ordered.map((event) => {
    const groupedEvents = Array.isArray(event?.grouped_events) ? event.grouped_events : null;
    if (!groupedEvents || groupedEvents.length <= 1) return event;
    const names = Array.from(new Set(
      groupedEvents
        .map((item) => String(item?.device_name || "").trim())
        .filter(Boolean),
    ));
    const preview = names.slice(0, 3).join(", ");
    const moreCount = Math.max(0, names.length - 3);
    return {
      ...event,
      device_name: "",
      device_ip: "",
      device_key: "",
      grouped_device_count: groupedEvents.length,
      grouped_device_label: `${groupedEvents.length} urządzeń`,
      grouped_device_preview: preview ? `${preview}${moreCount ? ` +${moreCount}` : ""}` : "",
      grouped_events: groupedEvents,
    };
  });
}

function compareByLastSeenDesc(a, b) {
  const aTime = parseDate(a?.last_seen)?.getTime() || 0;
  const bTime = parseDate(b?.last_seen)?.getTime() || 0;
  return bTime - aTime;
}

function compareByOnlineSinceAsc(a, b) {
  const aTime = parseDate(a?.online_since)?.getTime() || Number.MAX_SAFE_INTEGER;
  const bTime = parseDate(b?.online_since)?.getTime() || Number.MAX_SAFE_INTEGER;
  return aTime - bTime;
}

function isAllHistorySelectionKey(value) {
  return String(value || "").trim() === ALL_HISTORY_DEVICE_KEY;
}

function isGlobalHistorySnapshot(snapshot) {
  return snapshot?.scope === "all";
}

function getHiddenHistoryDeviceKeys() {
  const hiddenKeys = new Set();
  hiddenOnlineDeviceKeys.forEach((key) => {
    const value = String(key || "").trim();
    if (value) hiddenKeys.add(value);
  });
  hiddenRecentDeviceKeys.forEach((key) => {
    const value = String(key || "").trim();
    if (value) hiddenKeys.add(value);
  });
  currentDevices.forEach((device) => {
    const deviceKey = deviceKeyOf(device);
    if (!deviceKey) return;
    const hidden = device?.is_online ? isHiddenOnlineDevice(device) : isHiddenRecentDevice(device);
    if (hidden) hiddenKeys.add(deviceKey);
  });
  return hiddenKeys;
}

function isHiddenFromNetworkNotifications(snapshotItem) {
  const key = String(snapshotItem?.deviceKey || "").trim();
  if (!key) return false;
  return Boolean(snapshotItem?.isAutoHidden) || hiddenOnlineDeviceKeys.has(key) || hiddenRecentDeviceKeys.has(key);
}

function buildDeviceStatusSnapshot(devices) {
  const snapshot = new Map();
  (devices || []).forEach((device) => {
    const deviceKey = String(device?.device_key || "").trim();
    if (!deviceKey) return;
    const timelineEvents = Array.isArray(device?.timeline_24h?.events) ? device.timeline_24h.events : [];
    const latestEvent = timelineEvents.length ? timelineEvents[timelineEvents.length - 1] : null;
    const normalizedLatestEvent = latestEvent ? normalizeDisplayEvent(latestEvent, device) : null;

    snapshot.set(deviceKey, {
      deviceKey,
      isOnline: Boolean(device?.is_online),
      title: deviceTitle(device),
      ip: String(device?.ip || "").trim(),
      method: String(device?.last_method || "").trim(),
      at: device?.is_online
        ? (device?.online_since || device?.last_seen || null)
        : (device?.last_seen || null),
      reasonCode: String(normalizedLatestEvent?.reason_code || "").trim(),
      reasonLabel: String(normalizedLatestEvent?.reason_label || "").trim(),
      reasonDetail: String(normalizedLatestEvent?.reason_detail || "").trim(),
      confidence: String(normalizedLatestEvent?.confidence || "").trim(),
      simultaneousChangeCount: Number(normalizedLatestEvent?.simultaneous_change_count || 0),
      isAutoHidden: device?.is_online ? isHiddenOnlineDevice(device) : isHiddenRecentDevice(device),
    });
  });
  return snapshot;
}

function resetStatusNotificationBaseline() {
  previousDeviceStatusMap = new Map();
  statusNotificationBaselineReady = false;
}

function bundleStatusNotifications(changes) {
  const bundled = [];
  const passthrough = [];
  const networkIssueGroups = new Map();

  changes.forEach((change) => {
    if (change?.reasonCode !== "network_issue") {
      passthrough.push(change);
      return;
    }
    const groupKey = `${change.kind}:${String(change.at || "")}`;
    if (!networkIssueGroups.has(groupKey)) {
      networkIssueGroups.set(groupKey, []);
    }
    networkIssueGroups.get(groupKey)?.push(change);
  });

  networkIssueGroups.forEach((group) => {
    const anchor = group[0];
    const names = Array.from(new Set(group.map((item) => String(item?.title || "").trim()).filter(Boolean)));
    const namePreview = names.slice(0, 3).join(", ");
    const moreCount = Math.max(0, names.length - 3);
    const detailSuffix = namePreview
      ? ` / ${namePreview}${moreCount ? ` +${moreCount}` : ""}`
      : "";

    bundled.push({
      ...anchor,
      title: anchor?.reasonLabel || "Problem z siecią",
      toastKicker: anchor?.kind === "disconnected" ? "Rozłączono" : "Połączono",
      summary: `${anchor?.reasonDetail || "Wiele urządzeń zmieniło stan naraz."}${detailSuffix}`,
      ip: "",
      method: "",
    });
  });

  return [...passthrough, ...bundled].sort((left, right) => {
    const leftTime = parseDate(left?.at)?.getTime() || 0;
    const rightTime = parseDate(right?.at)?.getTime() || 0;
    return rightTime - leftTime;
  });
}

function detectStatusNotifications(devices) {
  const nextSnapshot = buildDeviceStatusSnapshot(devices);
  if (!statusNotificationBaselineReady) {
    previousDeviceStatusMap = nextSnapshot;
    statusNotificationBaselineReady = true;
    return [];
  }

  const changes = [];
  nextSnapshot.forEach((nextState, deviceKey) => {
    const prevState = previousDeviceStatusMap.get(deviceKey);

    if (!prevState) {
      if (nextState.isOnline && !isHiddenFromNetworkNotifications(nextState)) {
        changes.push({
          ...nextState,
          kind: "connected",
        });
      }
      return;
    }

    if (prevState.isOnline === nextState.isOnline) return;
    if (isHiddenFromNetworkNotifications(nextState)) return;

    changes.push({
      ...nextState,
      kind: nextState.isOnline ? "connected" : "disconnected",
    });
  });

  previousDeviceStatusMap = nextSnapshot;
  return bundleStatusNotifications(changes);
}

function ensureNetworkToastStack() {
  let stack = document.getElementById(NETWORK_TOAST_STACK_ID);
  if (stack) return stack;

  stack = document.createElement("div");
  stack.id = NETWORK_TOAST_STACK_ID;
  stack.className = "network-toast-stack";
  stack.setAttribute("role", "status");
  stack.setAttribute("aria-live", "polite");
  stack.setAttribute("aria-relevant", "additions");
  document.body.appendChild(stack);
  return stack;
}

function isNetworkToastViewportActive() {
  if (typeof document === "undefined") return true;
  const isVisible = document.visibilityState === "visible";
  const hasFocus = typeof document.hasFocus === "function" ? document.hasFocus() : true;
  return isVisible && hasFocus;
}

function clearNetworkToastState(toast) {
  const state = networkToastStates.get(toast);
  if (!state) return;
  if (state.timeoutId) {
    window.clearTimeout(state.timeoutId);
  }
  networkToastStates.delete(toast);
}

function pauseNetworkToastTimer(toast) {
  const state = networkToastStates.get(toast);
  if (!state) return;
  if (state.timeoutId) {
    window.clearTimeout(state.timeoutId);
    state.timeoutId = null;
  }
  if (state.startedAt) {
    state.remainingMs = Math.max(0, state.remainingMs - (Date.now() - state.startedAt));
    state.startedAt = 0;
  }
}

function resumeNetworkToastTimer(toast) {
  const state = networkToastStates.get(toast);
  if (!state) return;
  if (!document.body.contains(toast)) {
    clearNetworkToastState(toast);
    return;
  }
  if (state.timeoutId) return;
  if (state.remainingMs <= 0) {
    dismissNetworkToast(toast);
    return;
  }
  state.startedAt = Date.now();
  state.timeoutId = window.setTimeout(() => {
    const currentState = networkToastStates.get(toast);
    if (currentState) {
      currentState.timeoutId = null;
      currentState.startedAt = 0;
      currentState.remainingMs = 0;
    }
    dismissNetworkToast(toast);
  }, state.remainingMs);
}

function syncNetworkToastTimers() {
  const shouldRun = isNetworkToastViewportActive();
  networkToastStates.forEach((_state, toast) => {
    if (shouldRun) {
      resumeNetworkToastTimer(toast);
    } else {
      pauseNetworkToastTimer(toast);
    }
  });
}

function bindNetworkToastLifecycle() {
  if (networkToastLifecycleBound) return;
  networkToastLifecycleBound = true;
  document.addEventListener("visibilitychange", syncNetworkToastTimers);
  window.addEventListener("focus", syncNetworkToastTimers);
  window.addEventListener("blur", syncNetworkToastTimers);
  window.addEventListener("pageshow", syncNetworkToastTimers);
}

function dismissNetworkToast(toast) {
  if (!toast || toast.dataset.closing === "1") return;
  clearNetworkToastState(toast);
  toast.dataset.closing = "1";
  toast.classList.remove("is-visible");
  window.setTimeout(() => {
    toast.remove();
  }, 220);
}

function dismissAllNetworkToasts() {
  Array.from(networkToastStates.keys()).forEach((toast) => {
    dismissNetworkToast(toast);
  });
}

function trimNetworkToastStack(stack) {
  while (stack.childElementCount > NETWORK_TOAST_MAX) {
    const oldestToast = stack.lastElementChild;
    if (!oldestToast) break;
    clearNetworkToastState(oldestToast);
    oldestToast.remove();
  }
}

function showNetworkStatusNotification(change) {
  const stack = ensureNetworkToastStack();
  bindNetworkToastLifecycle();
  const toast = document.createElement("article");
  toast.className = `network-toast is-${change?.kind || "connected"}`;
  toast.tabIndex = 0;
  toast.setAttribute("role", "button");
  toast.setAttribute("aria-label", "Zamknij powiadomienie");
  toast.title = "Kliknij, aby zamknąć";

  const head = document.createElement("div");
  head.className = "network-toast-head";

  const status = document.createElement("div");
  status.className = "network-toast-status";

  const dot = document.createElement("span");
  dot.className = "network-toast-dot";
  dot.setAttribute("aria-hidden", "true");

  const kicker = document.createElement("span");
  kicker.className = "network-toast-kicker";
  kicker.textContent = change?.toastKicker || (change?.kind === "disconnected" ? "Rozłączono" : "Połączono");

  const time = document.createElement("span");
  time.className = "network-toast-time";
  time.textContent = formatTimeOnly(change?.at);

  status.append(dot, kicker);
  head.append(status, time);

  const title = document.createElement("strong");
  title.className = "network-toast-title";
  title.textContent = change?.title || "Nieznane urządzenie";

  const meta = document.createElement("div");
  meta.className = "network-toast-meta";
  const metaParts = [];
  if (change?.ip) metaParts.push(change.ip);
  if (change?.method) metaParts.push(change.method);
  meta.textContent = String(change?.summary || "").trim() || metaParts.join(" / ")
    || (change?.kind === "disconnected"
      ? "Urządzenie zniknęło z lokalnego skanu."
      : "Urządzenie pojawiło się w lokalnym skanie.");

  toast.addEventListener("click", () => {
    dismissNetworkToast(toast);
  });
  toast.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    dismissNetworkToast(toast);
  });

  toast.append(head, title, meta);
  stack.prepend(toast);
  networkToastStates.set(toast, {
    remainingMs: NETWORK_TOAST_DURATION_MS,
    startedAt: 0,
    timeoutId: null,
  });
  trimNetworkToastStack(stack);

  window.requestAnimationFrame(() => {
    toast.classList.add("is-visible");
  });
  syncNetworkToastTimers();
}

function showNetworkStatusNotifications(changes) {
  if (!statusNotificationsEnabled) return;
  changes.slice().reverse().forEach((change) => {
    showNetworkStatusNotification(change);
  });
}

function bindNetworkNotificationSettings() {
  window.addEventListener(NETWORK_STATUS_NOTIFICATIONS_CHANGED_EVENT, (event) => {
    statusNotificationsEnabled = event.detail?.enabled !== false;
    if (!statusNotificationsEnabled) {
      dismissAllNetworkToasts();
    }
  });

  window.addEventListener("storage", (event) => {
    if (event.key !== NETWORK_STATUS_NOTIFICATIONS_STORAGE_KEY) return;
    statusNotificationsEnabled = getNetworkStatusNotificationsEnabled();
    if (!statusNotificationsEnabled) {
      dismissAllNetworkToasts();
    }
  });
}

function deviceTitle(device) {
  return String(device?.name || device?.ip || device?.mac || "Nieznane urządzenie");
}

function categoryLabel(value) {
  return DEVICE_CATEGORY_LABELS[String(value || "").trim()] || null;
}

function normalizePresenceOwner(value) {
  const raw = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "");

  if (!raw) return null;
  if (raw === "ja") return "ja";
  return null;
}

function buildPresenceSnapshot(devices) {
  const groups = PRESENCE_OWNER_GROUPS.map((group) => ({
    ...group,
    devices: [],
  }));
  const groupMap = new Map(groups.map((group) => [group.key, group]));

  (devices || [])
    .filter((device) => Boolean(device?.is_online))
    .forEach((device) => {
      const ownerKey = normalizePresenceOwner(device?.owner);
      if (!ownerKey) return;
      const group = groupMap.get(ownerKey);
      if (!group) return;
      group.devices.push(device);
    });

  const presentGroups = groups.filter((group) => group.devices.length > 0);
  const summaryLabel = presentGroups.length
    ? presentGroups.map((group) => group.label).join(", ")
    : "Nikogo nie wykryto";

  return {
    groups,
    presentGroups,
    summaryLabel,
    activeOwnersCount: presentGroups.length,
    activeDevicesCount: presentGroups.reduce((sum, group) => sum + group.devices.length, 0),
  };
}

function getOwnerGroupDescriptor(device) {
  const rawOwner = String(device?.owner || "").trim();
  const normalizedOwner = normalizePresenceOwner(rawOwner);
  if (normalizedOwner) {
    const known = PRESENCE_OWNER_GROUPS.find((group) => group.key === normalizedOwner);
    if (known) {
      return {
        key: `owner:${known.key}`,
        label: known.label,
        sortOrder: PRESENCE_OWNER_GROUPS.findIndex((group) => group.key === known.key),
      };
    }
  }
  if (rawOwner) {
    return {
      key: `owner:custom:${rawOwner.toLowerCase()}`,
      label: rawOwner,
      sortOrder: 50,
    };
  }
  return {
    key: "owner:unassigned",
    label: "Bez ownera",
    sortOrder: 99,
  };
}

function groupDevicesByOwner(devices) {
  const groups = new Map();
  (devices || []).forEach((device) => {
    const descriptor = getOwnerGroupDescriptor(device);
    if (!groups.has(descriptor.key)) {
      groups.set(descriptor.key, {
        ...descriptor,
        devices: [],
      });
    }
    groups.get(descriptor.key)?.devices.push(device);
  });
  return Array.from(groups.values()).sort((left, right) => {
    if (left.sortOrder !== right.sortOrder) return left.sortOrder - right.sortOrder;
    return left.label.localeCompare(right.label, "pl");
  });
}

function appendGroupedOnlineDevices(target, devices, options = {}) {
  const groups = groupDevicesByOwner(devices);
  groups.forEach((group) => {
    const section = document.createElement("section");
    section.className = "network-owner-group";

    const head = document.createElement("div");
    head.className = "network-owner-group-head";

    const title = document.createElement("div");
    title.className = "network-owner-group-title";
    title.textContent = group.label;

    const meta = document.createElement("div");
    meta.className = "network-owner-group-meta";
    meta.textContent = `${group.devices.length} urz. online`;

    head.append(title, meta);
    section.appendChild(head);

    const list = document.createElement("div");
    list.className = "network-owner-group-list";
    group.devices.forEach((device) => {
      list.appendChild(createDeviceRow(device, options));
    });
    section.appendChild(list);
    target.appendChild(section);
  });
}

function buildPresenceTimelineModel(snapshot) {
  const presence = snapshot?.presence;
  if (!presence || !Array.isArray(presence?.owners)) return null;

  const owners = new Map(
    PRESENCE_OWNER_GROUPS.map((group, index) => [
      group.key,
      {
        key: group.key,
        label: group.label,
        sortOrder: index,
        onlineSeconds: 0,
        deviceCount: 0,
        deviceNames: [],
        segments: [],
      },
    ]),
  );

  presence.owners.forEach((ownerRow) => {
    const rawOwner = String(ownerRow?.owner || "").trim();
    if (!rawOwner) return;
    const normalizedOwner = normalizePresenceOwner(rawOwner);
    const known = normalizedOwner ? owners.get(normalizedOwner) : null;
    if (known) {
      known.onlineSeconds = Number(ownerRow?.online_seconds || 0);
      known.deviceCount = Number(ownerRow?.device_count || 0);
      known.deviceNames = Array.isArray(ownerRow?.device_names) ? ownerRow.device_names.slice() : [];
      known.segments = Array.isArray(ownerRow?.segments) ? ownerRow.segments.slice() : [];
      return;
    }
    owners.set(`custom:${rawOwner.toLowerCase()}`, {
      key: `custom:${rawOwner.toLowerCase()}`,
      label: rawOwner,
      sortOrder: 50,
      onlineSeconds: Number(ownerRow?.online_seconds || 0),
      deviceCount: Number(ownerRow?.device_count || 0),
      deviceNames: Array.isArray(ownerRow?.device_names) ? ownerRow.device_names.slice() : [],
      segments: Array.isArray(ownerRow?.segments) ? ownerRow.segments.slice() : [],
    });
  });

  return {
    selectedDayLabel: String(snapshot?.selected_day_label || ""),
    windowStartedAt: presence?.window_started_at || null,
    windowEndedAt: presence?.window_ended_at || null,
    owners: Array.from(owners.values()).sort((left, right) => {
      if (left.sortOrder !== right.sortOrder) return left.sortOrder - right.sortOrder;
      return left.label.localeCompare(right.label, "pl");
    }),
  };
}

function createPresenceScale(windowStart, windowEnd) {
  const wrap = document.createElement("div");
  wrap.className = "network-presence-scale-wrap";

  const spacer = document.createElement("div");
  spacer.className = "network-presence-scale-spacer";
  spacer.setAttribute("aria-hidden", "true");

  const scale = document.createElement("div");
  scale.className = "network-presence-scale";
  if (!windowStart || !windowEnd) {
    scale.innerHTML = "<span>--:--</span><span>--:--</span><span>--:--</span><span>--:--</span><span>--:--</span>";
    wrap.append(spacer, scale);
    return wrap;
  }

  const totalMs = Math.max(1, windowEnd.getTime() - windowStart.getTime());
  const marks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => new Date(windowStart.getTime() + totalMs * ratio));
  marks.forEach((mark) => {
    const node = document.createElement("span");
    node.textContent = formatTimeOnly(mark);
    scale.appendChild(node);
  });
  wrap.append(spacer, scale);
  return wrap;
}

function deviceSubtitle(device) {
  const parts = [];
  if (device?.ip) parts.push(device.ip);
  if (device?.mac) parts.push(device.mac);
  const category = categoryLabel(device?.category);
  if (category) parts.push(category);
  if (device?.owner) parts.push(`owner: ${device.owner}`);
  if (device?.last_method) parts.push(device.last_method);
  if (device?.custom_name && device?.detected_name && device.custom_name !== device.detected_name) {
    parts.push(`host: ${device.detected_name}`);
  }
  return parts.join(" / ") || "brak dodatkowych danych";
}

function setStateChip(mode, label) {
  const chip = $("network-state-chip");
  if (!chip) return;
  chip.className = `network-status-chip is-${mode}`;
  chip.textContent = label;
}

function createEmptyState(message) {
  const box = document.createElement("div");
  box.className = "network-empty";
  box.textContent = message;
  return box;
}

function createDeviceRow(device, { recent = false, hidden = false, online = false } = {}) {
  const item = document.createElement("article");
  item.className = "network-item";
  item.dataset.deviceKey = String(device?.device_key || "");
  if (hidden) item.classList.add("is-hidden-device");

  const head = document.createElement("div");
  head.className = "network-item-head";

  const titleWrap = document.createElement("div");
  titleWrap.className = "network-item-title";

  const title = document.createElement("strong");
  title.textContent = deviceTitle(device);

  const subtitle = document.createElement("span");
  subtitle.textContent = deviceSubtitle(device);

  titleWrap.append(title, subtitle);

  const state = document.createElement("span");
  state.className = `network-method ${recent ? "is-offline" : "is-online"}`;
  state.textContent = recent ? "offline" : "online";

  const rail = document.createElement("div");
  rail.className = "network-item-rail";
  rail.appendChild(state);

  if (recent || online) {
    const action = document.createElement("button");
    action.type = "button";
    action.className = `network-item-action ${hidden ? "is-show" : "is-hide"}`;
    action.dataset.networkAction = hidden
      ? (recent ? "show-recent-device" : "show-online-device")
      : (recent ? "hide-recent-device" : "hide-online-device");
    action.dataset.deviceKey = String(device?.device_key || "");
    action.textContent = hidden ? "Pokaż" : "Ukryj";
    rail.appendChild(action);
  }

  head.append(titleWrap, rail);

  const time = document.createElement("div");
  time.className = "network-item-time";
  time.textContent = recent
    ? `ostatnio: ${formatRelative(device?.last_seen)} / widziane ${formatAbsolute(device?.last_seen)}`
    : `online od: ${formatRelative(device?.online_since || device?.last_seen)} / ${formatDurationFromSeconds(device?.online_for_seconds)}`;

  item.append(head, time);
  return item;
}

function renderList(containerId, devices, emptyMessage, options = {}) {
  const wrap = $(containerId);
  if (!wrap) return;
  wrap.textContent = "";
  if (!devices.length) {
    wrap.appendChild(createEmptyState(emptyMessage));
    return;
  }
  const fragment = document.createDocumentFragment();
  devices.forEach((device) => fragment.appendChild(createDeviceRow(device, options)));
  wrap.appendChild(fragment);
}

function renderRecentList(devices) {
  const wrap = $("network-recent-list");
  if (!wrap) return;
  wrap.textContent = "";

  const visibleRecent = devices.filter((device) => !isHiddenRecentDevice(device));
  const hiddenRecent = devices.filter((device) => isHiddenRecentDevice(device));

  if (!visibleRecent.length && !hiddenRecent.length) {
    wrap.appendChild(createEmptyState("Brak starszych urządzeń w historii."));
    return;
  }

  if (visibleRecent.length) {
    const fragment = document.createDocumentFragment();
    visibleRecent.forEach((device) => fragment.appendChild(createDeviceRow(device, { recent: true })));
    wrap.appendChild(fragment);
  } else {
    const note = document.createElement("div");
    note.className = "network-hidden-note";
    note.textContent = "Wszystkie wpisy offline są obecnie ukryte.";
    wrap.appendChild(note);
  }

  if (!hiddenRecent.length) return;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "network-hidden-toggle";
  toggle.dataset.networkAction = "toggle-hidden-recent";
  toggle.textContent = showHiddenRecent
    ? `Ukryj sekcję ukrytych (${hiddenRecent.length})`
    : `Pokaż ukryte (${hiddenRecent.length})`;
  wrap.appendChild(toggle);

  if (!showHiddenRecent) return;

  const hiddenSection = document.createElement("div");
  hiddenSection.className = "network-hidden-section";

  const hiddenTitle = document.createElement("div");
  hiddenTitle.className = "network-hidden-section-title";
  hiddenTitle.textContent = "Ukryte wpisy";

  const hiddenList = document.createElement("div");
  hiddenList.className = "network-hidden-list";
  hiddenRecent.forEach((device) => hiddenList.appendChild(createDeviceRow(device, { recent: true, hidden: true })));

  hiddenSection.append(hiddenTitle, hiddenList);
  wrap.appendChild(hiddenSection);
}

function isLikelyPhoneDevice(device) {
  const haystack = [
    device?.name,
    device?.custom_name,
    device?.detected_name,
    device?.category,
  ].join(" ").toLowerCase();
  return /\b(redmi|iphone|android|pixel|samsung|phone|telefon|note)\b/.test(haystack);
}

function scoreCableProblemCandidate(device) {
  if (!device || isIpOnlyDevice(device) || isLikelyPhoneDevice(device)) return -100;
  const haystack = [
    device?.name,
    device?.custom_name,
    device?.detected_name,
    device?.category,
    device?.owner,
    device?.ip,
    device?.mac,
  ].join(" ").toLowerCase();

  let score = 0;
  if (/\b(pc|desktop|komputer|stacjonarny|lan|ethernet)\b/.test(haystack)) score += 12;
  if (/\b(laptop|notebook|aon)\b/.test(haystack)) score += 7;
  if (String(device?.owner || "").trim().toLowerCase() === "ja") score += 3;
  if (String(device?.category || "").trim() === "personal") score += 2;
  if (device?.is_online) score += 1;
  if (String(device?.category || "").trim() === "infrastructure") score -= 12;
  if (/\b(router|gateway|brama|ap|access point)\b/.test(haystack)) score -= 12;
  return score;
}

function findCableProblemDevice(devices) {
  const candidates = (devices || [])
    .map((device) => ({
      device,
      score: scoreCableProblemCandidate(device),
      lastSeen: parseDate(device?.last_seen)?.getTime() || 0,
    }))
    .filter((item) => item.score > 0)
    .sort((left, right) => {
      if (left.score !== right.score) return right.score - left.score;
      return right.lastSeen - left.lastSeen;
    });
  return candidates[0]?.device || null;
}

function buildCableIssueSessions(device) {
  const timeline = device?.timeline_24h || {};
  const windowStart = parseDate(timeline?.window_started_at);
  const windowEnd = parseDate(timeline?.window_ended_at) || new Date();
  const events = (Array.isArray(timeline?.events) ? timeline.events : [])
    .map((event) => normalizeDisplayEvent(event, device))
    .slice()
    .sort((a, b) => (parseDate(a?.at)?.getTime() || 0) - (parseDate(b?.at)?.getTime() || 0));
  const sessions = [];
  let openSession = null;

  events.forEach((event) => {
    const at = parseDate(event?.at);
    if (!at) return;
    if (event?.type === "disconnected") {
      if (openSession) {
        sessions.push({
          ...openSession,
          endedAt: at,
          durationSeconds: Math.max(0, Math.round((at.getTime() - openSession.startedAt.getTime()) / 1000)),
          recovered: false,
        });
      }
      openSession = {
        event,
        startedAt: at,
        endedAt: null,
        durationSeconds: 0,
        recovered: false,
      };
      return;
    }
    if (event?.type === "connected" && openSession) {
      openSession.endedAt = at;
      openSession.durationSeconds = Math.max(0, Math.round((at.getTime() - openSession.startedAt.getTime()) / 1000));
      openSession.recovered = true;
      sessions.push(openSession);
      openSession = null;
    }
  });

  if (openSession) {
    openSession.endedAt = windowEnd;
    openSession.durationSeconds = Math.max(0, Math.round((windowEnd.getTime() - openSession.startedAt.getTime()) / 1000));
    openSession.recovered = false;
    sessions.push(openSession);
  }

  return {
    timeline,
    windowStart,
    windowEnd,
    sessions,
  };
}

function summarizeCableIssueHours(sessions) {
  const buckets = new Map();
  sessions.forEach((session) => {
    const date = session.startedAt;
    if (!(date instanceof Date)) return;
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:00`;
    const current = buckets.get(key) || { label: key, count: 0, offlineSeconds: 0 };
    current.count += 1;
    current.offlineSeconds += Number(session.durationSeconds || 0);
    buckets.set(key, current);
  });
  return Array.from(buckets.values())
    .sort((left, right) => {
      if (left.count !== right.count) return right.count - left.count;
      return right.offlineSeconds - left.offlineSeconds;
    })
    .slice(0, 3);
}

function renderCableIssues(devices) {
  const meta = $("network-cable-issues-meta");
  const status = $("network-cable-issues-status");
  const wrap = $("network-cable-issues-body");
  if (!wrap) return;
  wrap.textContent = "";

  const target = findCableProblemDevice(devices);
  if (!target) {
    if (meta) meta.textContent = "nazwij komputer jako PC/LAN w ustawieniach";
    if (status) {
      status.textContent = "--";
      status.className = "network-cable-status";
    }
    wrap.appendChild(createEmptyState("Nie znalazłem jeszcze urządzenia wyglądającego jak PC po kablu."));
    return;
  }

  const { timeline, windowStart, windowEnd, sessions } = buildCableIssueSessions(target);
  const coverageSeconds = Math.max(0, Math.round(((windowEnd || new Date()).getTime() - (windowStart || new Date()).getTime()) / 1000));
  const totalOfflineSeconds = sessions.reduce((sum, session) => sum + Number(session.durationSeconds || 0), 0);
  const networkWideCount = sessions.filter((session) => String(session?.event?.reason_code || "") === "network_issue").length;
  const averageGapSeconds = sessions.length ? Math.round(Math.max(1, coverageSeconds) / sessions.length) : 0;
  const averageOfflineSeconds = sessions.length ? Math.round(totalOfflineSeconds / sessions.length) : 0;
  const latestSession = sessions[sessions.length - 1] || null;
  const hourBuckets = summarizeCableIssueHours(sessions);

  if (meta) {
    meta.textContent = `${deviceTitle(target)} / ${String(target?.ip || target?.mac || "").trim()} / ostatnie 24h`;
  }
  if (status) {
    status.className = `network-cable-status ${target?.is_online ? "is-online" : "is-offline"}`;
    status.textContent = target?.is_online ? "online" : "offline";
  }

  const stats = document.createElement("div");
  stats.className = "network-cable-stats";
  [
    {
      label: "Zerwania",
      value: String(sessions.length),
      note: networkWideCount ? `w tym cała sieć: ${networkWideCount}` : "tylko ten PC",
    },
    {
      label: "Offline łącznie",
      value: formatDurationFromSeconds(totalOfflineSeconds),
      note: sessions.length ? `średnio ${formatDurationFromSeconds(averageOfflineSeconds)}` : "brak przerw",
    },
    {
      label: "Częstość",
      value: sessions.length ? `co ${formatDurationFromSeconds(averageGapSeconds)}` : "0",
      note: formatWindowLabel(coverageSeconds || Number(timeline?.window_hours || 24) * 3600),
    },
  ].forEach((item) => {
    const node = document.createElement("article");
    node.className = "network-cable-stat";
    node.innerHTML = `
      <div class="network-cable-stat-label">${escapeHtml(item.label)}</div>
      <div class="network-cable-stat-value">${escapeHtml(item.value)}</div>
      <div class="network-cable-stat-note">${escapeHtml(item.note)}</div>
    `;
    stats.appendChild(node);
  });
  wrap.appendChild(stats);

  if (!sessions.length) {
    const stable = document.createElement("div");
    stable.className = "network-cable-empty";
    stable.textContent = "Zero rozłączeń PC w ostatnich 24h.";
    wrap.appendChild(stable);
    return;
  }

  const details = document.createElement("div");
  details.className = "network-cable-details";

  const hours = document.createElement("section");
  hours.className = "network-cable-block";
  hours.innerHTML = `<div class="network-cable-block-title">Godziny z problemami</div>`;
  const hourList = document.createElement("div");
  hourList.className = "network-cable-hour-list";
  hourBuckets.forEach((bucket) => {
    const row = document.createElement("div");
    row.className = "network-cable-hour";
    row.innerHTML = `
      <span>${escapeHtml(bucket.label)}</span>
      <strong>${bucket.count}x</strong>
      <small>${escapeHtml(formatDurationFromSeconds(bucket.offlineSeconds))}</small>
    `;
    hourList.appendChild(row);
  });
  hours.appendChild(hourList);

  const latest = document.createElement("section");
  latest.className = "network-cable-block";
  latest.innerHTML = `<div class="network-cable-block-title">Ostatnie zerwania</div>`;
  const eventList = document.createElement("div");
  eventList.className = "network-cable-event-list";
  sessions
    .slice()
    .sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime())
    .slice(0, 5)
    .forEach((session) => {
      const row = document.createElement("article");
      row.className = `network-cable-event${session.recovered ? "" : " is-open"}`;
      const reason = String(session?.event?.reason_code || "") === "network_issue"
        ? "cała sieć"
        : "PC/LAN";
      row.innerHTML = `
        <div>
          <div class="network-cable-event-time">${escapeHtml(formatAbsolute(session.startedAt))}</div>
          <div class="network-cable-event-reason">${escapeHtml(reason)}</div>
        </div>
        <div class="network-cable-event-duration">${session.recovered ? escapeHtml(formatDurationFromSeconds(session.durationSeconds)) : "trwa"}</div>
      `;
      eventList.appendChild(row);
    });
  latest.appendChild(eventList);

  details.append(hours, latest);
  wrap.appendChild(details);

  if (latestSession && !latestSession.recovered) {
    const warning = document.createElement("div");
    warning.className = "network-cable-warning";
    warning.textContent = `Ostatnie zerwanie nadal trwa od ${formatTimeOnly(latestSession.startedAt)}.`;
    wrap.appendChild(warning);
  }
}

function renderOnlineList(devices) {
  const wrap = $("network-online-list");
  if (!wrap) return;
  wrap.textContent = "";

  const visibleOnline = devices.filter((device) => !isHiddenOnlineDevice(device));
  const hiddenOnline = devices.filter((device) => isHiddenOnlineDevice(device));

  if (!visibleOnline.length && !hiddenOnline.length) {
    wrap.appendChild(createEmptyState("Brak urządzeń online w ostatnim skanie."));
    return;
  }

  if (visibleOnline.length) {
    appendGroupedOnlineDevices(wrap, visibleOnline, { online: true });
  } else {
    const note = document.createElement("div");
    note.className = "network-hidden-note";
    note.textContent = "Wszystkie wpisy online są obecnie ukryte.";
    wrap.appendChild(note);
  }

  if (!hiddenOnline.length) return;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "network-hidden-toggle";
  toggle.dataset.networkAction = "toggle-hidden-online";
  toggle.textContent = showHiddenOnline
    ? `Ukryj sekcję ukrytych (${hiddenOnline.length})`
    : `Pokaż ukryte (${hiddenOnline.length})`;
  wrap.appendChild(toggle);

  if (!showHiddenOnline) return;

  const hiddenSection = document.createElement("div");
  hiddenSection.className = "network-hidden-section";

  const hiddenTitle = document.createElement("div");
  hiddenTitle.className = "network-hidden-section-title";
  hiddenTitle.textContent = "Ukryte wpisy";

  const hiddenList = document.createElement("div");
  hiddenList.className = "network-hidden-list";
  appendGroupedOnlineDevices(hiddenList, hiddenOnline, { online: true, hidden: true });

  hiddenSection.append(hiddenTitle, hiddenList);
  wrap.appendChild(hiddenSection);
}

function updateScanAgeDisplay() {
  setText("network-scan-age", formatShortAge(lastScanAt));
}

function elapsedWindowSeconds(bucket) {
  const start = parseDate(bucket?.window_started_at);
  const end = parseDate(bucket?.window_ended_at) || new Date();
  if (!start || !end) return 0;
  return Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000));
}

function percentAcrossWindow(value, windowStart, windowEnd) {
  const point = parseDate(value);
  if (!point || !windowStart || !windowEnd) return 0;
  const total = Math.max(1, windowEnd.getTime() - windowStart.getTime());
  const offset = point.getTime() - windowStart.getTime();
  return Math.max(0, Math.min(100, (offset / total) * 100));
}

function getGlobalHistoryMinDay(devices) {
  const timestamps = devices
    .map((device) => parseDate(device?.first_seen)?.getTime() || 0)
    .filter((value) => value > 0);
  if (!timestamps.length) return toLocalDayValue(new Date());
  return toLocalDayValue(new Date(Math.min(...timestamps)));
}

function getGlobalHistoryMaxDay(devices) {
  const timestamps = devices
    .map((device) => parseDate(device?.last_seen)?.getTime() || 0)
    .filter((value) => value > 0);
  const fallback = Date.now();
  return toLocalDayValue(new Date(Math.max(fallback, ...timestamps)));
}

function getSelectedHistoryTarget(devices) {
  if (!devices.length) {
    selectedHistoryDeviceKey = null;
    return { mode: "none", key: null, device: null };
  }

  if (isAllHistorySelectionKey(selectedHistoryDeviceKey) || !selectedHistoryDeviceKey) {
    selectedHistoryDeviceKey = ALL_HISTORY_DEVICE_KEY;
    return { mode: "all", key: ALL_HISTORY_DEVICE_KEY, device: null };
  }

  const selected = devices.find((device) => device?.device_key === selectedHistoryDeviceKey);
  if (selected) {
    return { mode: "device", key: String(selected.device_key || ""), device: selected };
  }

  selectedHistoryDeviceKey = ALL_HISTORY_DEVICE_KEY;
  return { mode: "all", key: ALL_HISTORY_DEVICE_KEY, device: null };
}

function historyTargetMatchesSnapshot(target, snapshot) {
  if (!target || !snapshot) return false;
  if (target.mode === "all") return isGlobalHistorySnapshot(snapshot);
  if (target.mode !== "device") return false;
  return snapshot?.device_key === target?.device?.device_key;
}

function syncHistoryDayControl(historyTarget, snapshot = null, devices = []) {
  const input = $("network-history-day");
  const display = $("network-history-day-display");
  const prevButton = $("network-history-day-prev");
  const nextButton = $("network-history-day-next");
  if (!input) return;
  const safeSnapshot = historyTargetMatchesSnapshot(historyTarget, snapshot) ? snapshot : null;

  if (!historyTarget || historyTarget.mode === "none") {
    input.value = "";
    input.min = "";
    input.max = "";
    input.disabled = true;
    if (display) {
      display.textContent = "--/--/----";
      display.disabled = true;
    }
    if (prevButton) prevButton.disabled = true;
    if (nextButton) nextButton.disabled = true;
    return;
  }

  const minDay = String(
    safeSnapshot?.available_day_min || (
      historyTarget.mode === "all"
        ? getGlobalHistoryMinDay(devices)
        : toLocalDayValue(historyTarget?.device?.first_seen || new Date())
    )
  );
  const maxDay = String(
    safeSnapshot?.available_day_max || (
      historyTarget.mode === "all"
        ? getGlobalHistoryMaxDay(devices)
        : toLocalDayValue(new Date())
    )
  );
  let nextValue = String(selectedHistoryDay || maxDay);

  if (nextValue < minDay) nextValue = minDay;
  if (nextValue > maxDay) nextValue = maxDay;

  selectedHistoryDay = nextValue;
  input.min = minDay;
  input.max = maxDay;
  input.value = nextValue;
  input.disabled = false;
  if (display) {
    display.textContent = formatDayInputValue(nextValue);
    display.disabled = false;
  }
  if (prevButton) prevButton.disabled = nextValue <= minDay;
  if (nextButton) nextButton.disabled = nextValue >= maxDay;
}

function renderHistoryPicker(devices, historyTarget) {
  const select = $("network-history-device");
  if (!select) return;

  if (!devices.length) {
    select.innerHTML = '<option value="">Brak urządzeń</option>';
    select.disabled = true;
    return;
  }

  const selectedValue = historyTarget?.mode === "all"
    ? ALL_HISTORY_DEVICE_KEY
    : String(historyTarget?.device?.device_key || "");

  select.innerHTML = [
    `<option value="${ALL_HISTORY_DEVICE_KEY}"${selectedValue === ALL_HISTORY_DEVICE_KEY ? " selected" : ""}>Wszystkie urządzenia</option>`,
    ...devices.map((device) => {
      const deviceKey = String(device?.device_key || "");
      const selectedAttr = deviceKey === selectedValue ? " selected" : "";
      return `<option value="${deviceKey}"${selectedAttr}>${escapeHtml(deviceTitle(device))}</option>`;
    }),
  ].join("");
  select.disabled = devices.length === 0;
}

function renderHistoryStats(device) {
  const wrap = $("network-history-stats");
  if (!wrap) return;

  if (!device) {
    wrap.textContent = "";
    wrap.appendChild(createEmptyState("Brak danych historycznych dla urządzeń."));
    return;
  }

  const history = device?.history || {};
  const isGlobal = isGlobalHistorySnapshot(device);
  wrap.innerHTML = HISTORY_WINDOWS.map(({ key, label }) => {
    const bucket = history?.[key] || {};
    if (isGlobal) {
      const eventCount = Number(bucket?.event_count || 0);
      const connected = Number(bucket?.connected_count || 0);
      const disconnected = Number(bucket?.disconnected_count || 0);
      const devices = Number(bucket?.device_count || 0);
      return `
        <article class="network-history-stat">
          <div class="network-history-stat-label">${label}</div>
          <div class="network-history-stat-value">${eventCount} zdarzeń</div>
          <div class="network-history-stat-sub">połączenia ${connected} / rozłączenia ${disconnected}</div>
          <div class="network-history-stat-foot">urządzenia ze zmianami ${devices}</div>
        </article>
      `;
    }

    const online = formatDurationFromSeconds(bucket?.online_seconds);
    const offline = formatDurationFromSeconds(bucket?.offline_seconds);
    const sessions = Number(bucket?.online_sessions || 0);
    return `
      <article class="network-history-stat">
        <div class="network-history-stat-label">${label}</div>
        <div class="network-history-stat-value">on ${online}</div>
        <div class="network-history-stat-sub">off ${offline}</div>
        <div class="network-history-stat-foot">sesje online ${sessions}</div>
      </article>
    `;
  }).join("");
}

function renderHistoryChart(device) {
  const wrap = $("network-history-chart");
  if (!wrap) return;

  wrap.textContent = "";
  if (!device) {
    wrap.appendChild(createEmptyState("Brak historii do narysowania."));
    return;
  }

  const timeline = device?.timeline_24h || {};
  const isGlobal = isGlobalHistorySnapshot(device);
  const selectedDayLabel = String(device?.selected_day_label || "Wybrany dzień");
  const windowStart = parseDate(timeline?.window_started_at);
  const windowEnd = parseDate(timeline?.window_ended_at);
  const onlineSeconds = Number(timeline?.online_seconds || 0);
  const offlineSeconds = Number(timeline?.offline_seconds || 0);
  const rawConnectedCount = Number(timeline?.connected_count || 0);
  const rawDisconnectedCount = Number(timeline?.disconnected_count || 0);
  const rawEventCount = Number(timeline?.event_count || 0);
  const rawDevicesWithEventsCount = Number(timeline?.devices_with_events_count || 0);
  const maxOnlineCount = Number(timeline?.max_online_count || 0);
  const averageOnlineCount = Number(timeline?.average_online_count || 0);
  const totalSeconds = Math.max(elapsedWindowSeconds(timeline), onlineSeconds + offlineSeconds, 1);
  const onlinePercent = Math.max(0, Math.min(100, (onlineSeconds / totalSeconds) * 100));
  const segments = Array.isArray(timeline?.segments) ? timeline.segments : [];
  const rawEvents = Array.isArray(timeline?.events) ? timeline.events.slice() : [];
  const hiddenHistoryDeviceKeys = isGlobal ? getHiddenHistoryDeviceKeys() : new Set();
  const visibleEvents = isGlobal
    ? rawEvents.filter((event) => !hiddenHistoryDeviceKeys.has(String(event?.device_key || "").trim()))
    : rawEvents;
  const normalizedEvents = visibleEvents.map((event) => normalizeDisplayEvent(event, isGlobal ? event : device));
  const displayEvents = isGlobal ? bundleNetworkIssueTimelineEvents(normalizedEvents) : normalizedEvents;
  const hiddenEventCount = Math.max(0, rawEvents.length - visibleEvents.length);
  const bundledEventCount = Math.max(0, visibleEvents.length - displayEvents.length);
  const connectedCount = isGlobal
    ? visibleEvents.filter((event) => event?.type === "connected").length
    : rawConnectedCount;
  const disconnectedCount = isGlobal
    ? visibleEvents.filter((event) => event?.type === "disconnected").length
    : rawDisconnectedCount;
  const eventCount = isGlobal ? visibleEvents.length : rawEventCount;
  const devicesWithEventsCount = isGlobal
    ? new Set(visibleEvents.map((event) => String(event?.device_key || "").trim()).filter(Boolean)).size
    : rawDevicesWithEventsCount;
  const insight = normalizeDisplayInsight(timeline?.insight || {}, device);

  if (!windowStart || !windowEnd || (!segments.length && !displayEvents.length)) {
    wrap.appendChild(createEmptyState("Za mało danych, żeby narysować ostatnie 24h."));
    return;
  }

  const firstKnownPoint =
    parseDate(segments[0]?.started_at) ||
    parseDate(displayEvents[0]?.at) ||
    windowStart;
  const effectiveStart = firstKnownPoint > windowStart ? firstKnownPoint : windowStart;
  const coverageSeconds = Math.max(1, Math.round((windowEnd.getTime() - effectiveStart.getTime()) / 1000));

  const track = document.createElement("div");
  track.className = "network-timeline-track";
  track.setAttribute(
    "aria-label",
    isGlobal
      ? `Wszystkie zdarzenia: ${eventCount} zmian, połączenia ${connectedCount}, rozłączenia ${disconnectedCount}`
      : `Ostatnie 24 godziny: online ${formatDurationFromSeconds(onlineSeconds)}, offline ${formatDurationFromSeconds(offlineSeconds)}`
  );
  track.setAttribute("role", "img");

  segments
    .filter((segment) => isGlobal ? Number(segment?.online_count || 0) > 0 : segment?.state === "online")
    .forEach((segment) => {
      const left = percentAcrossWindow(segment?.started_at, effectiveStart, windowEnd);
      const right = percentAcrossWindow(segment?.ended_at, effectiveStart, windowEnd);
      const width = Math.max(0.8, right - left);
      const block = document.createElement("span");
      block.className = "network-timeline-segment is-online";
      if (isGlobal) {
        const currentOnlineCount = Math.max(1, Number(segment?.online_count || 0));
        const normalized = Math.max(0.22, Math.min(1, currentOnlineCount / Math.max(1, maxOnlineCount || currentOnlineCount)));
        block.classList.add("is-network-load");
        block.style.opacity = `${normalized}`;
        block.title = `${currentOnlineCount} urządzeń online / ${formatTimeOnly(segment?.started_at)}-${formatTimeOnly(segment?.ended_at)}`;
      } else {
        block.title = `Online ${formatTimeOnly(segment?.started_at)}-${formatTimeOnly(segment?.ended_at)}`;
      }
      block.style.left = `${left}%`;
      block.style.width = `${width}%`;
      track.appendChild(block);
    });

  displayEvents.forEach((event) => {
    const left = percentAcrossWindow(event?.at, effectiveStart, windowEnd);
    const marker = document.createElement("span");
    marker.className = `network-timeline-marker is-${event?.type === "disconnected" ? "disconnected" : "connected"}`;
    marker.style.left = `${left}%`;
    marker.title = `${event?.type === "disconnected" ? "Rozłączono" : "Połączono"} ${formatAbsolute(event?.at)}`;
    track.appendChild(marker);
  });

  const scale = document.createElement("div");
  scale.className = "network-timeline-scale";
  [0, 0.25, 0.5, 0.75, 1].forEach((ratio) => {
    const tick = document.createElement("span");
    tick.textContent = formatTimeOnly(
      new Date(effectiveStart.getTime() + ((windowEnd.getTime() - effectiveStart.getTime()) * ratio))
    );
    scale.appendChild(tick);
  });

  const eventsWrap = document.createElement("div");
  eventsWrap.className = "network-timeline-events";

  const recentEvents = displayEvents
    .slice()
    .sort((a, b) => (parseDate(b?.at)?.getTime() || 0) - (parseDate(a?.at)?.getTime() || 0));

  if (recentEvents.length) {
    recentEvents.forEach((event) => {
      const rangeLabel = formatEventRange(event?.at, event?.ended_at);
      const deviceName = String(event?.device_name || "");
      const deviceIp = String(event?.device_ip || "").trim();
      const deviceKey = String(event?.device_key || "").trim();
      const groupedDeviceLabel = String(event?.grouped_device_label || "").trim();
      const groupedDevicePreview = String(event?.grouped_device_preview || "").trim();
      const item = document.createElement("article");
      item.className = `network-timeline-event is-${event?.type === "disconnected" ? "disconnected" : "connected"}`;
      item.innerHTML = `
        <div class="network-timeline-event-timeblock">
          <div class="network-timeline-event-time">${escapeHtml(formatTimeOnly(event?.at))}</div>
          <div class="network-timeline-event-date">${escapeHtml(formatDayOnly(event?.at))}</div>
        </div>
        <div class="network-timeline-event-body">
          <div class="network-timeline-event-top">
            <div class="network-timeline-event-type">${event?.type === "disconnected" ? "Rozłączono" : "Połączono"}</div>
            <div class="network-timeline-event-confidence is-${classToken(event?.confidence)}">${escapeHtml(event?.confidence || "niska")}</div>
          </div>
          <div class="network-timeline-event-reason">${escapeHtml(event?.reason_label || "Zmiana stanu")}</div>
          ${isGlobal && groupedDeviceLabel ? `
            <div class="network-timeline-event-device is-static">
              ${escapeHtml(groupedDeviceLabel)}${groupedDevicePreview ? ` · ${escapeHtml(groupedDevicePreview)}` : ""}
            </div>
          ` : ""}
          ${isGlobal && deviceName ? `
            <button
              class="network-timeline-event-device"
              type="button"
              data-network-action="select-history-device"
              data-device-key="${escapeHtml(deviceKey)}"
            >
              ${escapeHtml(deviceName)}${deviceIp ? ` · ${escapeHtml(deviceIp)}` : ""}
            </button>
          ` : ""}
          ${rangeLabel ? `<div class="network-timeline-event-range">${escapeHtml(rangeLabel)}</div>` : ""}
          <div class="network-timeline-event-detail">${escapeHtml(event?.reason_detail || "")}</div>
        </div>
      `;
      eventsWrap.appendChild(item);
    });
  } else {
    const stable = document.createElement("div");
    stable.className = "network-timeline-empty";
    stable.textContent = isGlobal && hiddenEventCount
      ? "Brak zmian dla widocznych urządzeń. Odkryj ukryte urządzenia, aby zobaczyć pełny log."
      : "Brak zmian stanu w ostatnich 24h.";
    eventsWrap.appendChild(stable);
  }

  const displayLegend = isGlobal
    ? `${formatWindowLabel(coverageSeconds)} / zdarzenia ${eventCount}${bundledEventCount ? ` / zgrupowane ${bundledEventCount}` : ""}${hiddenEventCount ? ` / ukryte ${hiddenEventCount}` : ""} / połączenia ${connectedCount} / rozłączenia ${disconnectedCount}`
    : `${formatWindowLabel(coverageSeconds)} / wejścia ${connectedCount} / wyjścia ${disconnectedCount}`;
  const summaryNotes = [];
  if (bundledEventCount) summaryNotes.push(`Zgrupowano ${bundledEventCount} zdarzeń sieciowych w jeden wpis na moment zmiany.`);
  if (hiddenEventCount) summaryNotes.push(`Ukryto ${hiddenEventCount} zdarzeń z ukrytych urządzeń.`);

  wrap.innerHTML = `
    <article class="network-timeline-card">
      <div class="network-timeline-head">
        <div>
          <div class="network-chart-title">${escapeHtml(selectedDayLabel)}</div>
          <div class="network-chart-meta">${
            isGlobal
              ? `maks ${maxOnlineCount} online / średnio ${formatAverageOnlineCount(averageOnlineCount)} online / urządzeń ze zmianami ${devicesWithEventsCount}`
              : `online ${formatDurationFromSeconds(onlineSeconds)} / offline ${formatDurationFromSeconds(offlineSeconds)} / obecny udział online ${Math.round(onlinePercent)}%`
          }</div>
        </div>
        <div class="network-chart-legend">${
          isGlobal
            ? `${formatWindowLabel(coverageSeconds)} / zdarzenia ${eventCount}${hiddenEventCount ? ` / ukryte ${hiddenEventCount}` : ""} / połączenia ${connectedCount} / rozłączenia ${disconnectedCount}`
            : `${formatWindowLabel(coverageSeconds)} / wejścia ${connectedCount} / wyjścia ${disconnectedCount}`
        }</div>
      </div>
    </article>
  `;

  const card = wrap.querySelector(".network-timeline-card");
  if (!card) return;
  const legendNode = card.querySelector(".network-chart-legend");
  if (legendNode) {
    legendNode.textContent = displayLegend;
  }
  const summary = document.createElement("article");
  summary.className = `network-timeline-summary is-${classToken(insight?.kind)}`;
  summary.innerHTML = `
    <div class="network-timeline-summary-head">
      <div class="network-timeline-summary-label">${escapeHtml(insight?.label || "Brak mocnej heurystyki")}</div>
      <div class="network-timeline-confidence is-${classToken(insight?.confidence)}">${escapeHtml(insight?.confidence || "niska")}</div>
    </div>
    <div class="network-timeline-summary-copy">${escapeHtml(insight?.detail || "Za mało danych, żeby sensownie określić powód zmian.")}${hiddenEventCount ? `<br><span class="network-timeline-summary-note">Ukryto ${hiddenEventCount} zdarzeń z ukrytych urządzeń.</span>` : ""}</div>
  `;
  card.append(summary, track, scale, eventsWrap);
  const summaryCopyNode = summary.querySelector(".network-timeline-summary-copy");
  if (summaryCopyNode) {
    summaryCopyNode.innerHTML = [
      escapeHtml(insight?.detail || "Za mało danych, żeby sensownie określić powód zmian."),
      ...summaryNotes.map((note) => `<span class="network-timeline-summary-note">${escapeHtml(note)}</span>`),
    ].join("<br>");
  }
}

function renderPresenceWidgetLegacy(devices) {
  const wrap = $("network-home-presence");
  if (!wrap) return;

  wrap.textContent = "";
  const snapshot = buildPresenceSnapshot(devices);

  const card = document.createElement("section");
  card.className = "network-presence-card";

  const head = document.createElement("div");
  head.className = "network-presence-head";

  const titleWrap = document.createElement("div");
  titleWrap.className = "network-presence-copy";

  const title = document.createElement("div");
  title.className = "network-panel-title";
  title.textContent = "Kto jest w domu";

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = snapshot.activeOwnersCount
    ? `Aktywne profile: ${snapshot.activeOwnersCount} / 4 · urządzenia z ownerem online: ${snapshot.activeDevicesCount}`
    : "Liczone tylko z aktywnych urządzeń z przypisanym ownerem.";

  titleWrap.append(title, meta);

  const summary = document.createElement("div");
  summary.className = `network-presence-summary${snapshot.activeOwnersCount ? " is-active" : ""}`;

  const summaryLabel = document.createElement("span");
  summaryLabel.className = "network-presence-summary-label";
  summaryLabel.textContent = snapshot.activeOwnersCount ? "W domu teraz" : "Brak obecności";

  const summaryValue = document.createElement("strong");
  summaryValue.className = "network-presence-summary-value";
  summaryValue.textContent = snapshot.summaryLabel;

  summary.append(summaryLabel, summaryValue);
  head.append(titleWrap, summary);

  const grid = document.createElement("div");
  grid.className = "network-presence-grid";

  snapshot.groups.forEach((group) => {
    const item = document.createElement("article");
    item.className = `network-presence-person${group.devices.length ? " is-present" : ""}`;

    const top = document.createElement("div");
    top.className = "network-presence-person-top";

    const name = document.createElement("strong");
    name.className = "network-presence-person-name";
    name.textContent = group.label;

    const state = document.createElement("span");
    state.className = `network-presence-person-state${group.devices.length ? " is-present" : ""}`;
    state.textContent = group.devices.length ? "W domu" : "Poza domem";

    top.append(name, state);

    const detail = document.createElement("div");
    detail.className = "network-presence-person-detail";
    if (group.devices.length) {
      const titles = group.devices
        .slice(0, 2)
        .map((device) => deviceTitle(device));
      const more = group.devices.length > 2 ? ` +${group.devices.length - 2}` : "";
      detail.textContent = `${group.devices.length} urz. online · ${titles.join(", ")}${more}`;
    } else {
      detail.textContent = "Brak aktywnego urządzenia w ostatnim skanie.";
    }

    item.append(top, detail);
    grid.appendChild(item);
  });

  card.append(head, grid);
  wrap.appendChild(card);
}

function renderPresenceWidget(devices) {
  const wrap = $("network-home-presence");
  if (!wrap) return;

  wrap.textContent = "";
  const snapshot = buildPresenceSnapshot(devices);
  const timeline = buildPresenceTimelineModel(selectedPresenceSnapshot);
  const timelineWindowStart = parseDate(timeline?.windowStartedAt);
  const timelineWindowEnd = parseDate(timeline?.windowEndedAt);

  const card = document.createElement("section");
  card.className = "network-presence-card";

  const head = document.createElement("div");
  head.className = "network-presence-head";

  const titleWrap = document.createElement("div");
  titleWrap.className = "network-presence-copy";

  const title = document.createElement("div");
  title.className = "network-panel-title";
  title.textContent = "Kto jest w domu";

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = snapshot.activeOwnersCount
    ? `Aktywne profile: ${snapshot.activeOwnersCount} / ${PRESENCE_OWNER_GROUPS.length} · urządzenia z ownerem online: ${snapshot.activeDevicesCount}`
    : "Liczone tylko z aktywnych urządzeń z przypisanym ownerem.";

  titleWrap.append(title, meta);

  const summary = document.createElement("div");
  summary.className = `network-presence-summary${snapshot.activeOwnersCount ? " is-active" : ""}`;

  const summaryLabel = document.createElement("span");
  summaryLabel.className = "network-presence-summary-label";
  summaryLabel.textContent = snapshot.activeOwnersCount ? "W domu teraz" : "Brak obecności";

  const summaryValue = document.createElement("strong");
  summaryValue.className = "network-presence-summary-value";
  summaryValue.textContent = snapshot.summaryLabel;

  summary.append(summaryLabel, summaryValue);
  head.append(titleWrap, summary);

  const grid = document.createElement("div");
  grid.className = "network-presence-grid";

  snapshot.groups.forEach((group) => {
    const item = document.createElement("article");
    item.className = `network-presence-person${group.devices.length ? " is-present" : ""}`;

    const top = document.createElement("div");
    top.className = "network-presence-person-top";

    const name = document.createElement("strong");
    name.className = "network-presence-person-name";
    name.textContent = group.label;

    const state = document.createElement("span");
    state.className = `network-presence-person-state${group.devices.length ? " is-present" : ""}`;
    state.textContent = group.devices.length ? "W domu" : "Poza domem";

    top.append(name, state);

    const detail = document.createElement("div");
    detail.className = "network-presence-person-detail";
    if (group.devices.length) {
      const titles = group.devices
        .slice(0, 2)
        .map((device) => deviceTitle(device));
      const more = group.devices.length > 2 ? ` +${group.devices.length - 2}` : "";
      detail.textContent = `${group.devices.length} urz. online · ${titles.join(", ")}${more}`;
    } else {
      detail.textContent = "Brak aktywnego urządzenia w ostatnim skanie.";
    }

    item.append(top, detail);
    grid.appendChild(item);
  });

  const timelineSection = document.createElement("section");
  timelineSection.className = "network-presence-timeline";

  const timelineHead = document.createElement("div");
  timelineHead.className = "network-presence-timeline-head";

  const timelineTitle = document.createElement("div");
  timelineTitle.className = "network-presence-timeline-title";
  timelineTitle.textContent = timeline?.selectedDayLabel
    ? `Obecność w domu · ${timeline.selectedDayLabel}`
    : "Obecność w domu";

  const timelineMeta = document.createElement("div");
  timelineMeta.className = "network-presence-timeline-meta";
  timelineMeta.textContent = timeline
    ? "Na podstawie aktywnych urządzeń ownera w wybranym dniu."
    : "Ładowanie historii obecności dla wybranego dnia...";

  timelineHead.append(timelineTitle, timelineMeta);
  timelineSection.appendChild(timelineHead);

  if (timeline && timelineWindowStart && timelineWindowEnd) {
    timeline.owners.forEach((owner) => {
      const row = document.createElement("article");
      row.className = `network-presence-row${owner.onlineSeconds > 0 ? " is-present" : ""}`;

      const rowCopy = document.createElement("div");
      rowCopy.className = "network-presence-row-copy";

      const rowTitle = document.createElement("div");
      rowTitle.className = "network-presence-row-title";
      rowTitle.textContent = owner.label;

      const rowMeta = document.createElement("div");
      rowMeta.className = "network-presence-row-meta";
      rowMeta.textContent = owner.onlineSeconds > 0
        ? `w domu ${formatDurationFromSeconds(owner.onlineSeconds)} / urządzeń ${owner.deviceCount || 0}`
        : "brak obecności w tym dniu";

      rowCopy.append(rowTitle, rowMeta);

      const track = document.createElement("div");
      track.className = "network-presence-track";
      track.setAttribute("role", "img");
      track.setAttribute("aria-label", `${owner.label}: obecność ${formatDurationFromSeconds(owner.onlineSeconds)}`);

      (owner.segments || []).forEach((segment) => {
        const left = percentAcrossWindow(segment?.started_at, timelineWindowStart, timelineWindowEnd);
        const right = percentAcrossWindow(segment?.ended_at, timelineWindowStart, timelineWindowEnd);
        const width = Math.max(0.8, right - left);
        const bar = document.createElement("span");
        bar.className = "network-presence-segment";
        bar.style.left = `${left}%`;
        bar.style.width = `${width}%`;
        bar.title = `${owner.label}: ${formatTimeOnly(segment?.started_at)}-${formatTimeOnly(segment?.ended_at)}`;
        track.appendChild(bar);
      });

      row.append(rowCopy, track);
      timelineSection.appendChild(row);
    });

    timelineSection.appendChild(createPresenceScale(timelineWindowStart, timelineWindowEnd));
  } else {
    timelineSection.appendChild(createEmptyState("Ładuję timeline obecności..."));
  }

  card.append(head, grid, timelineSection);
  wrap.appendChild(card);
}

function getHistoryViewModel(historyTarget) {
  if (!historyTarget || historyTarget.mode === "none") return null;
  if (
    selectedHistorySnapshot &&
    historyTargetMatchesSnapshot(historyTarget, selectedHistorySnapshot) &&
    String(selectedHistorySnapshot?.selected_day || "") === String(selectedHistoryDay || "")
  ) {
    return selectedHistorySnapshot;
  }

  const today = toLocalDayValue(new Date());
  if (historyTarget.mode === "device" && String(selectedHistoryDay || today) === today) {
    return {
      ...historyTarget.device,
      selected_day: today,
      selected_day_label: new Intl.DateTimeFormat("pl-PL", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      }).format(new Date()),
    };
  }

  return null;
}

function renderHistoryPanel(devices) {
  const historyTarget = getSelectedHistoryTarget(devices);
  setText(
    "network-analytics-title",
    historyTarget.mode === "all" ? "Historia całej sieci" : "Historia urządzenia"
  );
  renderHistoryPicker(devices, historyTarget);
  syncSelectedRows();
  syncHistoryDayControl(historyTarget, selectedHistorySnapshot, devices);

  if (historyTarget.mode === "none") {
    setText("network-history-meta", "Brak danych historycznych dla urządzeń.");
    renderHistoryStats(null);
    renderHistoryChart(null);
    return;
  }

  const historyDevice = getHistoryViewModel(historyTarget);
  if (!historyDevice) {
    renderHistoryStats(null);
    renderHistoryChart(null);
    setText(
      "network-history-meta",
      historyTarget.mode === "all"
        ? `Wszystkie urządzenia / ładowanie danych dla dnia ${selectedHistoryDay || toLocalDayValue(new Date())}...`
        : `${deviceTitle(historyTarget.device)} / ładowanie danych dla dnia ${selectedHistoryDay || toLocalDayValue(new Date())}...`
    );
    return;
  }

  renderHistoryStats(historyDevice);
  renderHistoryChart(historyDevice);

  if (isGlobalHistorySnapshot(historyDevice)) {
    const rawEvents = Array.isArray(historyDevice?.timeline_24h?.events)
      ? historyDevice.timeline_24h.events
      : [];
    const hiddenKeys = getHiddenHistoryDeviceKeys();
    const visibleEvents = rawEvents.filter((event) => !hiddenKeys.has(String(event?.device_key || "").trim()));
    const hiddenEventCount = Math.max(0, rawEvents.length - visibleEvents.length);
    const recentChanges = visibleEvents.length;
    const connectedCount = visibleEvents.filter((event) => event?.type === "connected").length;
    const disconnectedCount = visibleEvents.filter((event) => event?.type === "disconnected").length;
    const changedDevices = new Set(
      visibleEvents.map((event) => String(event?.device_key || "").trim()).filter(Boolean)
    ).size;
    const insightLabel = normalizeDisplayInsight(historyDevice?.timeline_24h?.insight || {}, historyDevice)?.label || "brak mocnej heurystyki";
    setText(
      "network-history-meta",
      `Wszystkie urządzenia / dzień ${historyDevice?.selected_day_label || selectedHistoryDay || "-"} / zdarzenia dnia: ${recentChanges}${hiddenEventCount ? ` / ukryte: ${hiddenEventCount}` : ""} / połączenia: ${connectedCount} / rozłączenia: ${disconnectedCount} / urządzenia ze zmianami: ${changedDevices} / heurystyka dnia: ${insightLabel}`
    );
    return;
  }

  const currentState = historyDevice?.is_online
    ? `online od ${formatRelative(historyDevice?.online_since || historyDevice?.last_seen)}`
    : `offline, ostatnio ${formatRelative(historyDevice?.last_seen)}`;
  const recentChanges = Array.isArray(historyDevice?.timeline_24h?.events)
    ? historyDevice.timeline_24h.events.length
    : 0;
  const insightLabel = normalizeDisplayInsight(
    historyDevice?.timeline_24h?.insight || {},
    historyDevice,
  )?.label || "brak mocnej heurystyki";
  const identityBits = [
    historyDevice?.ip || "-",
    categoryLabel(historyDevice?.category),
    historyDevice?.owner ? `owner: ${historyDevice.owner}` : "",
  ].filter(Boolean).join(" / ");
  setText(
    "network-history-meta",
    `${deviceTitle(historyDevice)} / ${identityBits} / ${currentState} / dzień ${historyDevice?.selected_day_label || selectedHistoryDay || "-"} / zmiany dnia: ${recentChanges} / heurystyka dnia: ${insightLabel}`
  );
}

function renderOfflineState(message) {
  lastScanAt = null;
  currentSummary = {};
  currentDevices = [];
  selectedHistoryDeviceKey = null;
  selectedHistorySnapshot = null;
  selectedPresenceSnapshot = null;
  clearHistoryFetchCache();
  resetStatusNotificationBaseline();
  setText("network-online-count", "0");
  setText("network-total-count", "0");
  setText("network-scan-age", "--");
  setText("network-online-meta", "backend lokalny offline");
  setText("network-recent-meta", "widżet czeka na API");
  setText("network-foot", message);
  setText("network-history-meta", "Brak historii, bo backend nie odpowiada.");
  setStateChip("offline", "offline");
  renderList("network-online-list", [], "Brak danych online.");
  renderList("network-recent-list", [], "Brak historii urządzeń.");
  renderCableIssues([]);
  renderHistoryPicker([], null);
  syncHistoryDayControl(null, null);
  renderHistoryStats(null);
  renderHistoryChart(null);
  renderPresenceWidget([]);
  document.dispatchEvent(new Event("dashboard:net"));
}

function renderWidget(devices, summary) {
  currentDevices = Array.isArray(devices) ? devices.slice() : [];
  currentSummary = summary && typeof summary === "object" ? { ...summary } : {};
  const allOnline = currentDevices
    .filter((device) => Boolean(device?.is_online))
    .sort(compareByOnlineSinceAsc);

  const allRecent = currentDevices
    .filter((device) => !device?.is_online)
    .sort(compareByLastSeenDesc);
  const visibleOnline = allOnline.filter((device) => !isHiddenOnlineDevice(device));
  const hiddenOnline = allOnline.length - visibleOnline.length;
  const visibleRecent = allRecent.filter((device) => !isHiddenRecentDevice(device));
  const hiddenRecent = allRecent.length - visibleRecent.length;

  const onlineTotal = Number(summary?.currently_online ?? allOnline.length);
  const totalSeen = Number(summary?.total_devices_seen ?? currentDevices.length);
  lastScanAt = summary?.last_scan_at || null;

  setText("network-online-count", String(onlineTotal));
  setText("network-total-count", String(totalSeen));
  updateScanAgeDisplay();
  setText(
    "network-online-meta",
    onlineTotal
      ? `${visibleOnline.length} urządzeń odpowiedziało w ostatnim skanie${hiddenOnline ? ` / ukryte ${hiddenOnline}` : ""}`
      : "brak aktywnych hostów"
  );
  setText(
    "network-recent-meta",
    allRecent.length
      ? `${visibleRecent.length} ostatnio widzianych poza bieżącym skanem${hiddenRecent ? ` / ukryte ${hiddenRecent}` : ""}`
      : "na razie brak historii offline"
  );
  setText(
    "network-foot",
    summary?.last_scan_at
      ? `Lokalny backend / ${API_BASE} / ostatni skan ${formatRelative(summary.last_scan_at)}`
      : "Lokalny backend uruchomiony, czekam na pierwszy skan."
  );
  setStateChip("live", summary?.last_scan_at ? "lokalnie" : "skan");
  renderOnlineList(allOnline);
  renderRecentList(allRecent);
  renderCableIssues(currentDevices);
  renderHistoryPanel(currentDevices);
  renderPresenceWidget(currentDevices);
  document.dispatchEvent(new Event("dashboard:net"));
}

async function refreshSelectedHistory() {
  if (!API_BASE) return;
  const historyTarget = getSelectedHistoryTarget(currentDevices);
  syncHistoryDayControl(historyTarget, selectedHistorySnapshot, currentDevices);
  if (historyTarget.mode === "none" || !selectedHistoryDay) {
    selectedHistorySnapshot = null;
    renderHistoryPanel(currentDevices);
    return;
  }

  const requestToken = ++historyRequestToken;
  try {
    const lookupKey = historyTarget.mode === "all"
      ? ALL_HISTORY_DEVICE_KEY
      : historyTarget?.device?.device_key;
    const snapshot = await fetchHistorySnapshotCached(lookupKey, selectedHistoryDay);
    if (requestToken !== historyRequestToken) return;
    selectedHistorySnapshot = snapshot;
  } catch (error) {
    if (requestToken !== historyRequestToken) return;
    console.error("Network history refresh failed:", error);
    selectedHistorySnapshot = null;
  }
  renderHistoryPanel(currentDevices);
}

async function refreshPresenceHistory() {
  if (!API_BASE) return;
  if (!selectedHistoryDay) {
    selectedPresenceSnapshot = null;
    renderPresenceWidget(currentDevices);
    return;
  }

  const requestToken = ++presenceRequestToken;
  try {
    const snapshot = await fetchHistorySnapshotCached(ALL_HISTORY_DEVICE_KEY, selectedHistoryDay);
    if (requestToken !== presenceRequestToken) return;
    selectedPresenceSnapshot = snapshot;
  } catch (error) {
    if (requestToken !== presenceRequestToken) return;
    console.error("Network presence history refresh failed:", error);
    selectedPresenceSnapshot = null;
  }
  renderPresenceWidget(currentDevices);
}

async function refreshWidget({ force = false } = {}) {
  if (!API_BASE) {
    renderOfflineState("Widżet sieci działa tylko lokalnie z backendem na 127.0.0.1.");
    return;
  }

  if (refreshInFlight) {
    scheduleWidgetRefresh();
    return;
  }

  refreshInFlight = true;

  try {
    const previousScanAt = lastScanAt;
    const summary = await fetchNetworkSummary();
    const nextSummary = summary && typeof summary === "object" ? { ...summary } : {};
    const nextScanAt = nextSummary?.last_scan_at || null;
    const scanChanged = force || !currentDevices.length || nextScanAt !== previousScanAt;

    let devices = currentDevices;
    let statusChanges = [];

    if (scanChanged) {
      clearHistoryFetchCache();
      devices = await fetchNetworkDevices();
      statusChanges = detectStatusNotifications(devices);
    }

    renderWidget(devices, nextSummary);

    if (statusChanges.length && statusNotificationsEnabled) {
      showNetworkStatusNotifications(statusChanges);
    }

    if (scanChanged) {
      await Promise.all([
        refreshSelectedHistory(),
        refreshPresenceHistory(),
      ]);
    }
  } catch (error) {
    console.error("Network widget refresh failed:", error);
    renderOfflineState("Nie ma połączenia z lokalnym backendem sieci. Uruchom `python run_network_monitor.py`.");
  } finally {
    refreshInFlight = false;
    if (API_BASE) {
      scheduleWidgetRefresh();
    }
  }
}

function bindInteractions() {
  const card = $("network-card");
  const select = $("network-history-device");
  const dayInput = $("network-history-day");
  const dayDisplay = $("network-history-day-display");
  const dayPrev = $("network-history-day-prev");
  const dayNext = $("network-history-day-next");

  select?.addEventListener("change", (event) => {
    selectedHistoryDeviceKey = event.target.value || null;
    selectedHistorySnapshot = null;
    renderHistoryPanel(currentDevices);
    refreshSelectedHistory();
  });

  dayInput?.addEventListener("change", (event) => {
    selectedHistoryDay = String(event.target.value || "").trim() || toLocalDayValue(new Date());
    selectedHistorySnapshot = null;
    selectedPresenceSnapshot = null;
    renderHistoryPanel(currentDevices);
    renderPresenceWidget(currentDevices);
    refreshSelectedHistory();
    refreshPresenceHistory();
  });

  dayDisplay?.addEventListener("click", () => {
    openHistoryDayPicker();
  });

  dayPrev?.addEventListener("click", () => {
    const input = $("network-history-day");
    if (!input || input.disabled) return;
    const nextValue = shiftDayValue(selectedHistoryDay || input.value || toLocalDayValue(new Date()), -1);
    const minValue = String(input.min || "");
    if (minValue && nextValue < minValue) return;
    selectedHistoryDay = nextValue;
    selectedHistorySnapshot = null;
    selectedPresenceSnapshot = null;
    renderHistoryPanel(currentDevices);
    renderPresenceWidget(currentDevices);
    refreshSelectedHistory();
    refreshPresenceHistory();
  });

  dayNext?.addEventListener("click", () => {
    const input = $("network-history-day");
    if (!input || input.disabled) return;
    const nextValue = shiftDayValue(selectedHistoryDay || input.value || toLocalDayValue(new Date()), 1);
    const maxValue = String(input.max || "");
    if (maxValue && nextValue > maxValue) return;
    selectedHistoryDay = nextValue;
    selectedHistorySnapshot = null;
    selectedPresenceSnapshot = null;
    renderHistoryPanel(currentDevices);
    renderPresenceWidget(currentDevices);
    refreshSelectedHistory();
    refreshPresenceHistory();
  });

  card?.addEventListener("click", (event) => {
    const actionButton = event.target.closest("[data-network-action]");
    if (actionButton) {
      const action = String(actionButton.dataset.networkAction || "");
      const deviceKey = String(actionButton.dataset.deviceKey || "");
      const device = findCurrentDeviceByKey(deviceKey);
      const ipOnly = isIpOnlyDevice(device);

      if (action === "hide-recent-device" && deviceKey) {
        shownIpOnlyRecentDeviceKeys.delete(deviceKey);
        if (ipOnly) {
          hiddenRecentDeviceKeys.delete(deviceKey);
        } else {
          hiddenRecentDeviceKeys.add(deviceKey);
        }
        saveHiddenRecentDeviceKeys();
        saveShownIpOnlyRecentDeviceKeys();
        renderWidget(currentDevices, currentSummary || {});
        return;
      }

      if (action === "show-recent-device" && deviceKey) {
        hiddenRecentDeviceKeys.delete(deviceKey);
        if (ipOnly) shownIpOnlyRecentDeviceKeys.add(deviceKey);
        saveHiddenRecentDeviceKeys();
        saveShownIpOnlyRecentDeviceKeys();
        renderWidget(currentDevices, currentSummary || {});
        return;
      }

      if (action === "toggle-hidden-recent") {
        showHiddenRecent = !showHiddenRecent;
        renderWidget(currentDevices, currentSummary || {});
        return;
      }

      if (action === "hide-online-device" && deviceKey) {
        shownIpOnlyOnlineDeviceKeys.delete(deviceKey);
        if (ipOnly) {
          hiddenOnlineDeviceKeys.delete(deviceKey);
        } else {
          hiddenOnlineDeviceKeys.add(deviceKey);
        }
        saveHiddenOnlineDeviceKeys();
        saveShownIpOnlyOnlineDeviceKeys();
        renderWidget(currentDevices, currentSummary || {});
        return;
      }

      if (action === "show-online-device" && deviceKey) {
        hiddenOnlineDeviceKeys.delete(deviceKey);
        if (ipOnly) shownIpOnlyOnlineDeviceKeys.add(deviceKey);
        saveHiddenOnlineDeviceKeys();
        saveShownIpOnlyOnlineDeviceKeys();
        renderWidget(currentDevices, currentSummary || {});
        return;
      }

      if (action === "toggle-hidden-online") {
        showHiddenOnline = !showHiddenOnline;
        renderWidget(currentDevices, currentSummary || {});
        return;
      }

      if (action === "select-history-device" && deviceKey) {
        selectedHistoryDeviceKey = deviceKey;
        selectedHistorySnapshot = null;
        renderHistoryPanel(currentDevices);
        refreshSelectedHistory();
        return;
      }
    }

    const row = event.target.closest(".network-item[data-device-key]");
    if (!row) return;
    const key = row.dataset.deviceKey || "";
    if (!key) return;
    selectedHistoryDeviceKey = key;
    selectedHistorySnapshot = null;
    renderHistoryPanel(currentDevices);
    refreshSelectedHistory();
  });
}

function syncSelectedRows() {
  const activeKey = isAllHistorySelectionKey(selectedHistoryDeviceKey) ? "" : selectedHistoryDeviceKey;
  document.querySelectorAll(".network-item[data-device-key]").forEach((node) => {
    const isSelected = node.dataset.deviceKey === activeKey;
    node.classList.toggle("is-selected", isSelected);
  });
}

onDomReady(() => {
  if (!$("network-card")) return;
  selectedHistoryDay = toLocalDayValue(new Date());
  bindNetworkNotificationSettings();
  bindInteractions();
  refreshWidget({ force: true });
  window.setInterval(updateScanAgeDisplay, SCAN_TICK_MS);
});
