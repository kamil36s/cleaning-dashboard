import {
  fetchReadingSettings as fetchReadingSettingsApi,
  saveReadingSettings as saveReadingSettingsApi,
} from "./reading-api.js";

const ACTIVE_STORAGE_KEY = "readingActiveMap.v1";
const OWNERSHIP_STORAGE_KEY = "readingOwnershipMap.v1";
const SELECTED_BOOK_STORAGE_KEY = "readingWidgetSelectedBook.v1";
const REMOTE_PAGES_STORAGE_KEY = "readingRemotePages.v1";
const SETTINGS_UPDATED_AT_STORAGE_KEY = "readingSettingsUpdatedAt.v1";

let readingSettingsCache = null;
let readingSettingsSaveQueue = Promise.resolve();
let readingSettingsHydrationPromise = null;

const canUseStorage = () => typeof window !== "undefined" && !!window.localStorage;

function readJsonStorage(key, fallback) {
  if (!canUseStorage()) return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJsonStorage(key, value) {
  if (!canUseStorage()) return;
  try {
    if (value === null || value === undefined) {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, JSON.stringify(value));
    }
  } catch {}
}

function normalizeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
}

function normalizeUpdatedAt(value) {
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) return numeric;
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function normalizeSelectedBook(value) {
  if (!value || typeof value !== "object") return null;
  const remoteId = typeof value.remoteId === "string" && value.remoteId.trim()
    ? value.remoteId.trim()
    : null;
  const key = typeof value.key === "string" && value.key.trim()
    ? value.key.trim()
    : null;
  return remoteId || key ? { remoteId, key } : null;
}

function normalizeReadingSettings(raw = {}) {
  return {
    activeMap: normalizeObject(raw?.activeMap),
    ownershipMap: normalizeObject(raw?.ownershipMap),
    selectedBook: normalizeSelectedBook(raw?.selectedBook),
    remotePages: normalizeObject(raw?.remotePages),
    updatedAt: normalizeUpdatedAt(raw?.updatedAt),
  };
}

function readLocalSettings() {
  return normalizeReadingSettings({
    activeMap: readJsonStorage(ACTIVE_STORAGE_KEY, {}),
    ownershipMap: readJsonStorage(OWNERSHIP_STORAGE_KEY, {}),
    selectedBook: readJsonStorage(SELECTED_BOOK_STORAGE_KEY, null),
    remotePages: readJsonStorage(REMOTE_PAGES_STORAGE_KEY, {}),
    updatedAt: readJsonStorage(SETTINGS_UPDATED_AT_STORAGE_KEY, 0),
  });
}

function writeLocalSettings(settings) {
  writeJsonStorage(ACTIVE_STORAGE_KEY, settings.activeMap || {});
  writeJsonStorage(OWNERSHIP_STORAGE_KEY, settings.ownershipMap || {});
  writeJsonStorage(SELECTED_BOOK_STORAGE_KEY, settings.selectedBook || null);
  writeJsonStorage(REMOTE_PAGES_STORAGE_KEY, settings.remotePages || {});
  writeJsonStorage(SETTINGS_UPDATED_AT_STORAGE_KEY, settings.updatedAt || 0);
}

function getReadingSettings() {
  // localStorage can be changed by the reading page or the main dashboard in
  // another tab. Always refresh the module cache before composing a full
  // settings payload so a stale tab cannot write an older activeMap back.
  readingSettingsCache = readLocalSettings();
  return readingSettingsCache;
}

function persistReadingSettings(settings) {
  const snapshot = normalizeReadingSettings(settings);
  readingSettingsSaveQueue = readingSettingsSaveQueue
    .catch(() => {})
    .then(() => saveReadingSettingsApi(snapshot));
  return readingSettingsSaveQueue;
}

function hasLocalReadingSettings(settings) {
  return Object.keys(settings.activeMap || {}).length > 0
    || Object.keys(settings.ownershipMap || {}).length > 0
    || Object.keys(settings.remotePages || {}).length > 0
    || !!settings.selectedBook;
}

function saveReadingSettings(settings, { touch = true } = {}) {
  readingSettingsCache = normalizeReadingSettings({
    ...settings,
    updatedAt: touch ? Date.now() : settings?.updatedAt,
  });
  writeLocalSettings(readingSettingsCache);
  persistReadingSettings(readingSettingsCache).catch(() => {});
  return readingSettingsCache;
}

async function hydrateReadingSettings() {
  let server = null;
  try {
    server = await fetchReadingSettingsApi();
  } catch {}
  const local = readLocalSettings();
  const serverSettings = server === null || server === undefined
    ? null
    : normalizeReadingSettings(server);
  let next = local;

  if (serverSettings) {
    if (local.updatedAt && (!serverSettings.updatedAt || local.updatedAt > serverSettings.updatedAt)) {
      next = local;
      persistReadingSettings(next).catch(() => {});
    } else if (serverSettings.updatedAt && serverSettings.updatedAt >= local.updatedAt) {
      next = serverSettings;
    } else if (hasLocalReadingSettings(local)) {
      next = local;
      persistReadingSettings(next).catch(() => {});
    } else {
      next = serverSettings;
    }
  }

  readingSettingsCache = next;
  writeLocalSettings(next);
  if (server === null || server === undefined) {
    persistReadingSettings(next).catch(() => {});
  }
}

export function refreshReadingSettings() {
  if (readingSettingsHydrationPromise) return readingSettingsHydrationPromise;
  readingSettingsHydrationPromise = hydrateReadingSettings()
    .finally(() => {
      readingSettingsHydrationPromise = null;
    });
  return readingSettingsHydrationPromise;
}

export function whenReadingSettingsReady() {
  return readingSettingsHydrationPromise || refreshReadingSettings();
}

refreshReadingSettings().catch(() => {});

export function readReadingActiveMap() {
  return { ...getReadingSettings().activeMap };
}

export function saveReadingActiveMap(activeMap) {
  return saveReadingSettings({ ...getReadingSettings(), activeMap }).activeMap;
}

export function readReadingOwnershipMap() {
  return { ...getReadingSettings().ownershipMap };
}

export function saveReadingOwnershipMap(ownershipMap) {
  return saveReadingSettings({ ...getReadingSettings(), ownershipMap }).ownershipMap;
}

export function readReadingSelectedBook() {
  return normalizeSelectedBook(getReadingSettings().selectedBook);
}

export function saveReadingSelectedBook(selectedBook) {
  return saveReadingSettings({ ...getReadingSettings(), selectedBook }).selectedBook;
}

export function readReadingRemotePages() {
  return { ...getReadingSettings().remotePages };
}

export function saveReadingRemotePages(remotePages) {
  return saveReadingSettings({ ...getReadingSettings(), remotePages }).remotePages;
}
