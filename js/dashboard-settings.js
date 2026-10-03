import {
  fetchFileSetting,
  saveFileBackedSetting,
  saveFileSetting,
} from "./file-settings.js";

export const DASHBOARD_WIDGET_STORAGE_KEY = "dashboard.widget-settings.v1";
export const DASHBOARD_WIDGETS_CHANGED_EVENT = "dashboard:widgets-changed";
const CONFIG_URL = new URL("../data/widget-order.json", import.meta.url);
const SERVER_SETTINGS_NAME = "dashboard";
const REMOVED_WIDGET_KEYS = new Set([
  "moving-checklist",
  "flat-hunt",
  "journal",
  "great-timeline",
  "blood-pressure",
  "voice-journal",
]);
const DEFAULT_COLUMN_COUNT = 2;
const MIN_COLUMN_COUNT = 2;
const MAX_COLUMN_COUNT = 4;
const DEFAULT_HEADER_FONT_SIZE = 16;
const MIN_HEADER_FONT_SIZE = 13;
const MAX_HEADER_FONT_SIZE = 22;
const WIDGET_SPAN_VALUES = new Set(["auto", "1", "2", "3", "full"]);

const FALLBACK_DEFAULT_ORDER = {
  weather: 10,
  aqi: 20,
  cleaning: 30,
  "self-care": 35,
  feelings: 40.5,
  reading: 40,
  "language-learning": 41,
  "phone-activity": 41.5,
  todo: 42,
  bills: 42.5,
  budget: 43,
  "weight-cut": 44,
  "live-workout": 44.5,
  diet: 45,
  "blood-pressure": 46,
  "voice-journal": 47,
  journal: 47.5,
  "journal-htr": 47.7,
  quote: 47,
  jobhunt: 48,
  "ai-usage": 48.5,
  "mental-health": 48.6,
  "weekly-insights": 48.7,
  "great-timeline": 49,
  bm365: 50,
  "brutal-assault-2027": 51,
  "rym-polish-black-metal-top-100": 52,
  films: 60,
  "cinema-city": 63,
  "classical-library": 62,
  oscars: 61,
  "network-monitor": 65,
  habits: 70,
  events: 80,
  "event-countdowns": 85,
  sensors: 90,
  "habits-app": 95,
  "habits-timeline": 100,
  "phone-telemetry": 110,
};

const FALLBACK_DEFAULT_VISIBLE = {
  weather: true,
  aqi: true,
  cleaning: true,
  "self-care": true,
  feelings: true,
  reading: true,
  "language-learning": true,
  "phone-activity": true,
  "phone-telemetry": false,
  todo: false,
  bills: true,
  budget: false,
  "weight-cut": false,
  "live-workout": true,
  diet: false,
  "blood-pressure": true,
  "voice-journal": true,
  journal: true,
  "journal-htr": true,
  quote: true,
  jobhunt: true,
  "ai-usage": true,
  "mental-health": true,
  "weekly-insights": true,
  "great-timeline": true,
  bm365: true,
  "brutal-assault-2027": true,
  "rym-polish-black-metal-top-100": true,
  films: false,
  "cinema-city": false,
  "classical-library": false,
  oscars: true,
  "network-monitor": false,
  habits: false,
  events: false,
  "event-countdowns": false,
  sensors: false,
  "habits-app": true,
  "habits-timeline": false,
};

const FALLBACK_DEFAULT_LAYOUT = {
  columns: DEFAULT_COLUMN_COUNT,
  autoFit: false,
  showHeartRateHistoryShortcut: true,
  cleaningLockEnabled: false,
};

const FALLBACK_DEFAULT_PLACEMENT = {
  bills: { span: "full" },
  "weight-cut": { span: "full" },
  "live-workout": { span: "full" },
  diet: { span: "full" },
  "blood-pressure": { span: "full" },
  "voice-journal": { span: "full" },
  journal: { span: "auto" },
  "journal-htr": { span: "auto" },
  "mental-health": { span: "full" },
  "weekly-insights": { span: "full" },
  "habits-app": { span: "full" },
  "habits-timeline": { span: "full" },
};

const FALLBACK_DEFAULT_HEADERS = {
  titleFontSize: DEFAULT_HEADER_FONT_SIZE,
  widgets: {},
};

const WIDGET_META = {
  weather: {
    label: "Pogoda",
    description: "Hero z temperaturą, warunkami i szybką prognozą.",
  },
  aqi: {
    label: "Jakość powietrza",
    description: "AQI, PM2.5, PM10 i pozostałe wskaźniki powietrza.",
  },
  cleaning: {
    label: "Cleaning Dashboard",
    description: "Dzisiejszy status sprzątania, progres i szybkie akcje.",
  },
  "self-care": {
    label: "Self-care",
    description: "Zdrowie, higiena, regularne zadania i szybkie oznaczanie.",
  },
  feelings: {
    label: "How I Feel",
    description: "Private local emotion check-ins, history, and descriptive insights.",
  },
  reading: {
    label: "Postęp czytania",
    description: "Aktywna książka, tempo i stan wszystkich pozycji.",
  },
  "language-learning": {
    label: "Language Learning",
    description: "Norwegian streak, weekly goal, vocabulary, and next Reader action.",
  },
  "phone-activity": {
    label: "Phone Activity",
    description: "Local phone usage, notifications and sync status.",
  },
  "phone-telemetry": {
    label: "Phone Telemetry",
    description: "Sesje telefonu, przełączanie aplikacji i presja notyfikacji.",
  },
  todo: {
    label: "Todo",
    description: "Bieżące taski i szybkie dopisywanie rzeczy do zrobienia.",
  },
  bills: {
    label: "Rachunki, raty i subskrypcje",
    description: "Terminy, przypomnienia i miesięczny plan cyklicznych płatności.",
  },
  budget: {
    label: "Budżet",
    description: "Saldo, koszty stałe i limit dzienny do końca miesiąca.",
  },
  "weight-cut": {
    label: "Redukcja",
    description: "Dwa kafle: aktualna waga i kroki dzisiaj.",
  },
  "live-workout": {
    label: "Live Workout",
    description: "Trening indoor cycling z tętnem na żywo, interwałami i strefami HR.",
  },
  diet: {
    label: "Dieta",
    description: "Dziennik posiłków, suma kalorii i wykres celu dziennego.",
  },
  "blood-pressure": {
    label: "Dziennik ciśnienia",
    description: "Lokalny dziennik pomiarów ciśnienia, pulsu, tagów i średnich.",
  },
  "voice-journal": {
    label: "Dziennik głosowy",
    description: "Lokalne nagrania i transkrypcja przez Whispera.",
  },
  journal: {
    label: "Dziennik",
    description: "Prywatne wpisy i dopracowane publikacje z Dziennika głosowego.",
  },
  "journal-htr": {
    label: "OCR dziennika",
    description: "Lokalna digitalizacja rękopisów przez eScriptorium i Krakena.",
  },
  quote: {
    label: "Losowy cytat",
    description: "Lekki widget z cytatem wpinanym w wolną przestrzeń siatki.",
  },
  jobhunt: {
    label: "Jobhunt",
    description: "Oferty pracy, aplikacje, follow-upy i najlepszy następny krok.",
  },
  "ai-usage": {
    label: "AI Usage",
    description: "Quota, burn i szacowane sesje Codexa oraz Antigravity.",
  },
  "mental-health": {
    label: "Mental Health",
    description: "Oddzielne skale, terminy, check-iny i trendy bez wyniku zbiorczego.",
  },
  "weekly-insights": {
    label: "Weekly insights",
    description: "Najważniejsze zmiany z ostatnich siedmiu dni na tle poprzedniego tygodnia.",
  },
  "great-timeline": {
    label: "The Great Timeline",
    description: "Osobista oś życia: wydarzenia, okresy, fazy i powiązania.",
  },
  bm365: {
    label: "Black Metal 365",
    description: "Postęp odsłuchu, statystyki i kolejny album.",
  },
  "brutal-assault-2027": {
    label: "Brutal Assault 2027",
    description: "Lokalna lista albumów festiwalowych, oceny i postęp odsłuchu.",
  },
  "rym-polish-black-metal-top-100": {
    label: "Top 100 RYM Polish BM",
    description: "Sto polskich albumów blackmetalowych z RYM, własne oceny i postęp odsłuchu.",
  },
  films: {
    label: "Filmy",
    description: "Biblioteka filmów, listy i spotlight z szybkimi wejściami.",
  },
  "cinema-city": {
    label: "Cinema City Galeria Kazimierz",
    description: "Dostępne seanse z filtrowanego Google Calendar.",
  },
  "classical-library": {
    label: "Classical Composer Library",
    description: "Kompozytorzy, katalog utworów, odsłuchy, oceny i poprawki metadanych.",
  },
  oscars: {
    label: "Oscary",
    description: "Dashboard oscarowy z rocznikami, shortlistą i danymi.",
  },
  "network-monitor": {
    label: "Sieć lokalna",
    description: "Urządzenia w LAN, status online i ostatni skan monitora sieci.",
  },
  habits: {
    label: "Habits",
    description: "Status nawyków i najważniejsze liczby z eksportu.",
  },
  events: {
    label: "Events",
    description: "Wydarzenia, daty i podsumowania w dashboardzie.",
  },
  "event-countdowns": {
    label: "Event Countdowns",
    description: "Odliczania do wybranych wydarzen z Events.",
  },
  sensors: {
    label: "Sensory",
    description: "Komfort pokoju i odczyty z czujników środowiskowych.",
  },
  "habits-app": {
    label: "Habits App",
    description: "Interaktywny frontend nawyków: siedem dni, wpisy, filtry i statystyki.",
  },
  "habits-timeline": {
    label: "Habits Timeline",
    description: "Pełna szerokość: porównanie wielu nawyków na osi czasu.",
  },
};

const WIDGET_DEFAULT_SUBTITLES = {
  "language-learning": "A little Norwegian every day",
  cleaning: "Dzisiejszy status sprzątania",
  "self-care": "Zdrowie, higiena i regularne ogarnianie siebie",
  feelings: "Private emotion journal",
  "phone-telemetry": "Usage sessions, app switching, and notification pressure",
  todo: "Wszystkie aktywne rzeczy",
  bills: "Poręczna przypominajka o cyklicznych płatnościach",
  budget: "CSV czeka na pierwsze dane",
  "weight-cut": "Podstawowe kafle dzienne",
  "live-workout": "Indoor cycling · tętno na żywo",
  diet: "Posiłki, kcal i cel dzienny",
  "blood-pressure": "Pomiary domowe, puls i średnia 7 dni",
  "voice-journal": "Lokalna transkrypcja nagrań",
  journal: "Prywatne zapiski i opublikowane transkrypcje",
  "journal-htr": "Lokalny HTR · eScriptorium + Kraken",
  jobhunt: "Status szukania pracy",
  "mental-health": "Profil · trendy · check-in",
  "weekly-insights": "Last 7 days compared with the previous 7",
  "great-timeline": "Personal life timeline",
  bm365: "Postęp odsłuchu albumów",
  "brutal-assault-2027": "Postęp odsłuchu albumów",
  "rym-polish-black-metal-top-100": "Postęp odsłuchu albumów",
  films: "Jedna biblioteka, wiele list",
  "cinema-city": "Dostępne seanse z Google Calendar",
  "classical-library": "Works, ratings, metadata corrections",
  "network-monitor": "Wi-Fi / LAN z lokalnego skanera",
  habits: "Dzisiejszy status nawyków",
  events: "Święta, wyjazdy, koncerty i ważne terminy",
  "event-countdowns": "Odliczania spięte z Holidays & Important Dates",
  sensors: "Live z termometru",
  "habits-app": "Interaktywny frontend inspirowany Loop Habit Tracker",
  "habits-timeline": "Pick multiple habits and compare",
};

const WIDGET_DEFAULT_TITLES = {
  weather: "Pogoda",
  aqi: "Jakość powietrza",
  cleaning: "Cleaning Dashboard",
  "self-care": "Self-care",
  feelings: "How I Feel",
  reading: "Postęp czytania",
  "language-learning": "Norwegian Bokmål",
  "phone-telemetry": "Phone Telemetry",
  todo: "To-do",
  bills: "Rachunki, raty i subskrypcje",
  budget: "Budżet",
  "weight-cut": "Redukcja",
  "live-workout": "Live Workout",
  diet: "Dieta",
  "blood-pressure": "Dziennik ciśnienia",
  "voice-journal": "Dziennik głosowy",
  journal: "Dziennik",
  "journal-htr": "OCR dziennika",
  quote: "Losowy cytat",
  jobhunt: "Jobhunt",
  "mental-health": "Mental Health",
  "weekly-insights": "Weekly insights",
  "great-timeline": "THE GREAT TIMELINE",
  bm365: "Black Metal 365",
  "brutal-assault-2027": "Brutal Assault 2027",
  "rym-polish-black-metal-top-100": "Top 100 RYM Polish BM",
  films: "Biblioteka filmów",
  "cinema-city": "Cinema City Galeria Kazimierz",
  "classical-library": "Classical Composer Library",
  oscars: "Oscary",
  "network-monitor": "Sieć lokalna",
  habits: "Habits",
  events: "Holidays & Important Dates",
  "event-countdowns": "Event Countdowns",
  sensors: "Temperatura i wilgotność",
  "habits-app": "Habits App",
  "habits-timeline": "Habits Timeline",
};

const LEGACY_WIDGET_DEFAULT_TITLES = {
  aqi: "Jakosc powietrza",
  reading: "Postep czytania",
  budget: "Budzet",
  films: "Biblioteka filmow",
  "network-monitor": "Siec lokalna",
  sensors: "Temperatura i wilgotnosc",
};

const LEGACY_WIDGET_DEFAULT_SUBTITLES = {
  cleaning: "Dzisiejszy status sprzatania",
  diet: "Posilki, kcal i cel dzienny",
  bm365: "Progress odsluchu albumow",
  "brutal-assault-2027": "Progress odsluchu albumow",
  "rym-polish-black-metal-top-100": "Progress odsluchu albumow",
  habits: "Dzisiejszy status nawykow",
  events: "Swieta, wyjazdy, koncerty i wazne terminy",
  "event-countdowns": "Odliczania spiete z Holidays & Important Dates",
};

const FALLBACK_DEFAULT_CONFIG = {
  order: FALLBACK_DEFAULT_ORDER,
  visible: FALLBACK_DEFAULT_VISIBLE,
  layout: FALLBACK_DEFAULT_LAYOUT,
  placement: FALLBACK_DEFAULT_PLACEMENT,
  headers: FALLBACK_DEFAULT_HEADERS,
};

const ACCIDENTAL_SHOW_ALL_KEYS = Object.entries(FALLBACK_DEFAULT_VISIBLE)
  .filter(([, visible]) => visible === false)
  .map(([key]) => key);

let remoteDefaultsPromise = null;

const canUseStorage = () => typeof window !== "undefined" && !!window.localStorage;

const cloneConfig = (config) => ({
  order: { ...(config?.order || {}) },
  visible: { ...(config?.visible || {}) },
  layout: { ...(config?.layout || {}) },
  placement: Object.fromEntries(
    Object.entries(config?.placement || {}).map(([key, value]) => [
      key,
      { ...(value || {}) },
    ]),
  ),
  headers: {
    titleFontSize: config?.headers?.titleFontSize,
    widgets: Object.fromEntries(
      Object.entries(config?.headers?.widgets || {}).map(([key, value]) => [
        key,
        { ...(value || {}) },
      ]),
    ),
  },
});

const clampColumnCount = (value) => {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return DEFAULT_COLUMN_COUNT;
  return Math.min(MAX_COLUMN_COUNT, Math.max(MIN_COLUMN_COUNT, parsed));
};

const normalizeWidgetSpan = (value) => {
  const normalized = String(value || "auto").trim().toLowerCase();
  return WIDGET_SPAN_VALUES.has(normalized) ? normalized : "auto";
};

const clampHeaderFontSize = (value) => {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return DEFAULT_HEADER_FONT_SIZE;
  return Math.min(MAX_HEADER_FONT_SIZE, Math.max(MIN_HEADER_FONT_SIZE, parsed));
};

const normalizeHeaderText = (value) =>
  typeof value === "string" ? value.trim().slice(0, 80) : "";

const normalizeLegacyWidgetHeaderText = (key, value, legacyMap, defaultMap) => {
  const normalized = normalizeHeaderText(value);
  if (normalized && normalized === legacyMap[key]) {
    return defaultMap[key] || normalized;
  }
  return normalized;
};

const buildKeyList = (raw = {}, defaults = FALLBACK_DEFAULT_CONFIG) => {
  const keys = [];
  const pushKey = (key) => {
    if (!key || REMOVED_WIDGET_KEYS.has(key) || keys.includes(key)) return;
    keys.push(key);
  };

  Object.keys(defaults?.order || {}).forEach(pushKey);
  Object.keys(defaults?.visible || {}).forEach(pushKey);
  Object.keys(raw?.order || {}).forEach(pushKey);
  Object.keys(raw?.visible || {}).forEach(pushKey);

  return keys;
};

const titleCaseKey = (key) =>
  String(key || "")
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

function emitDashboardWidgetConfigChange(config) {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") {
    return;
  }

  window.dispatchEvent(new CustomEvent(DASHBOARD_WIDGETS_CHANGED_EVENT, {
    detail: config ? cloneConfig(config) : null,
  }));
}

export function getDefaultDashboardWidgetConfig() {
  return cloneConfig(FALLBACK_DEFAULT_CONFIG);
}

export function normalizeDashboardWidgetConfig(
  raw = {},
  defaults = FALLBACK_DEFAULT_CONFIG,
) {
  const base = cloneConfig(defaults);
  const keys = buildKeyList(raw, base);
  const order = {};
  const visible = {};
  const placement = {};
  const headerWidgets = {};

  keys.forEach((key, index) => {
    const fallbackOrder = Number(base.order[key]);
    const rawOrder = Number(raw?.order?.[key]);
    order[key] = Number.isFinite(rawOrder)
      ? rawOrder
      : (Number.isFinite(fallbackOrder) ? fallbackOrder : (index + 1) * 10);

    const fallbackVisible = base.visible[key] !== false;
    visible[key] = typeof raw?.visible?.[key] === "boolean"
      ? raw.visible[key]
      : fallbackVisible;

    placement[key] = {
      span: normalizeWidgetSpan(
        raw?.placement?.[key]?.span ?? base.placement?.[key]?.span,
      ),
    };

    headerWidgets[key] = {
      title: normalizeLegacyWidgetHeaderText(
        key,
        raw?.headers?.widgets?.[key]?.title,
        LEGACY_WIDGET_DEFAULT_TITLES,
        WIDGET_DEFAULT_TITLES,
      ),
      subtitle: normalizeLegacyWidgetHeaderText(
        key,
        raw?.headers?.widgets?.[key]?.subtitle,
        LEGACY_WIDGET_DEFAULT_SUBTITLES,
        WIDGET_DEFAULT_SUBTITLES,
      ),
    };
  });

  return {
    order,
    visible,
    layout: {
      columns: clampColumnCount(raw?.layout?.columns ?? base.layout?.columns),
      autoFit: typeof raw?.layout?.autoFit === "boolean"
        ? raw.layout.autoFit
        : base.layout?.autoFit === true,
      showHeartRateHistoryShortcut:
        typeof raw?.layout?.showHeartRateHistoryShortcut === "boolean"
          ? raw.layout.showHeartRateHistoryShortcut
          : base.layout?.showHeartRateHistoryShortcut !== false,
      cleaningLockEnabled: typeof raw?.layout?.cleaningLockEnabled === "boolean"
        ? raw.layout.cleaningLockEnabled
        : base.layout?.cleaningLockEnabled === true,
    },
    placement,
    headers: {
      titleFontSize: clampHeaderFontSize(
        raw?.headers?.titleFontSize ?? base.headers?.titleFontSize,
      ),
      widgets: headerWidgets,
    },
  };
}

async function loadRemoteDefaults() {
  if (!remoteDefaultsPromise) {
    remoteDefaultsPromise = (async () => {
      try {
        const response = await fetch(CONFIG_URL, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        return normalizeDashboardWidgetConfig(data, FALLBACK_DEFAULT_CONFIG);
      } catch {
        return getDefaultDashboardWidgetConfig();
      }
    })();
  }

  return remoteDefaultsPromise;
}

export function readStoredDashboardWidgetConfig(defaults = FALLBACK_DEFAULT_CONFIG) {
  if (!canUseStorage()) return null;

  try {
    const raw = window.localStorage.getItem(DASHBOARD_WIDGET_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const accidentallyEnabledCount = ACCIDENTAL_SHOW_ALL_KEYS.filter(
      (key) => parsed?.visible?.[key] === true,
    ).length;

    if (accidentallyEnabledCount >= 8) {
      window.localStorage.removeItem(DASHBOARD_WIDGET_STORAGE_KEY);
      return null;
    }

    return normalizeDashboardWidgetConfig(parsed, defaults);
  } catch {
    return null;
  }
}

export async function loadDashboardWidgetConfig() {
  const defaults = await loadRemoteDefaults();
  try {
    const serverConfig = await fetchFileSetting(SERVER_SETTINGS_NAME, null);
    if (serverConfig !== null && serverConfig !== undefined) {
      const normalized = normalizeDashboardWidgetConfig(serverConfig, defaults);
      if (canUseStorage()) {
        try {
          window.localStorage.setItem(DASHBOARD_WIDGET_STORAGE_KEY, JSON.stringify(normalized));
        } catch {}
      }
      return normalized;
    }
  } catch {}

  const stored = readStoredDashboardWidgetConfig(defaults);
  if (stored) {
    saveFileSetting(SERVER_SETTINGS_NAME, stored).catch(() => {});
    return stored;
  }

  return defaults;
}

export function saveDashboardWidgetConfig(config) {
  const normalized = normalizeDashboardWidgetConfig(config);
  if (!canUseStorage()) {
    emitDashboardWidgetConfigChange(normalized);
    return normalized;
  }

  try {
    window.localStorage.setItem(DASHBOARD_WIDGET_STORAGE_KEY, JSON.stringify(normalized));
  } catch {}
  saveFileBackedSetting({
    name: SERVER_SETTINGS_NAME,
    storageKey: DASHBOARD_WIDGET_STORAGE_KEY,
    value: normalized,
  });

  emitDashboardWidgetConfigChange(normalized);

  return normalized;
}

export function clearDashboardWidgetConfig() {
  if (canUseStorage()) {
    try {
      window.localStorage.removeItem(DASHBOARD_WIDGET_STORAGE_KEY);
    } catch {}
  }
  saveFileSetting(SERVER_SETTINGS_NAME, null).catch(() => {});

  emitDashboardWidgetConfigChange(null);
}

export function getOrderedDashboardWidgets(config) {
  const normalized = normalizeDashboardWidgetConfig(config);
  const keys = buildKeyList(normalized, normalized);

  return keys
    .map((key, index) => {
      const meta = WIDGET_META[key] || {};
      return {
        key,
        label: meta.label || titleCaseKey(key),
        description: meta.description || "Widget dashboardu.",
        order: normalized.order[key],
        visible: normalized.visible[key] !== false,
        span: normalized.placement[key]?.span || "auto",
        title: normalized.headers.widgets[key]?.title || WIDGET_DEFAULT_TITLES[key] || meta.label || titleCaseKey(key),
        subtitle: normalized.headers.widgets[key]?.subtitle || WIDGET_DEFAULT_SUBTITLES[key] || "",
        customTitle: normalized.headers.widgets[key]?.title || "",
        customSubtitle: normalized.headers.widgets[key]?.subtitle || "",
        originalIndex: index,
      };
    })
    .sort((a, b) =>
      (a.order - b.order)
      || (a.originalIndex - b.originalIndex)
      || a.label.localeCompare(b.label, "pl"));
}

function withWidgetOrder(config, orderedKeys) {
  const normalized = normalizeDashboardWidgetConfig(config);
  const order = { ...normalized.order };

  orderedKeys.forEach((key, index) => {
    order[key] = (index + 1) * 10;
  });

  return {
    order,
    visible: { ...normalized.visible },
    layout: { ...normalized.layout },
    placement: cloneConfig(normalized).placement,
    headers: cloneConfig(normalized).headers,
  };
}

export function moveDashboardWidget(config, key, direction) {
  const widgets = getOrderedDashboardWidgets(config);
  const keys = widgets.map((widget) => widget.key);
  const fromIndex = keys.indexOf(key);
  if (fromIndex < 0) return normalizeDashboardWidgetConfig(config);

  const toIndex = fromIndex + (direction < 0 ? -1 : 1);
  if (toIndex < 0 || toIndex >= keys.length) {
    return normalizeDashboardWidgetConfig(config);
  }

  [keys[fromIndex], keys[toIndex]] = [keys[toIndex], keys[fromIndex]];
  return withWidgetOrder(config, keys);
}

export function setDashboardWidgetVisibility(config, key, nextVisible) {
  const normalized = normalizeDashboardWidgetConfig(config);
  return {
    order: { ...normalized.order },
    visible: {
      ...normalized.visible,
      [key]: !!nextVisible,
    },
    layout: { ...normalized.layout },
    placement: cloneConfig(normalized).placement,
    headers: cloneConfig(normalized).headers,
  };
}

export function setAllDashboardWidgetsVisibility(config, nextVisible) {
  const normalized = normalizeDashboardWidgetConfig(config);
  const visible = {};

  Object.keys(normalized.visible).forEach((key) => {
    visible[key] = !!nextVisible;
  });

  return {
    order: { ...normalized.order },
    visible,
    layout: { ...normalized.layout },
    placement: cloneConfig(normalized).placement,
    headers: cloneConfig(normalized).headers,
  };
}

export function setDashboardColumnCount(config, nextColumns) {
  const normalized = normalizeDashboardWidgetConfig(config);
  return {
    order: { ...normalized.order },
    visible: { ...normalized.visible },
    layout: {
      ...normalized.layout,
      columns: clampColumnCount(nextColumns),
    },
    placement: cloneConfig(normalized).placement,
    headers: cloneConfig(normalized).headers,
  };
}

export function setDashboardAutoFitEnabled(config, nextEnabled) {
  const normalized = normalizeDashboardWidgetConfig(config);
  return {
    order: { ...normalized.order },
    visible: { ...normalized.visible },
    layout: {
      ...normalized.layout,
      autoFit: !!nextEnabled,
    },
    placement: cloneConfig(normalized).placement,
    headers: cloneConfig(normalized).headers,
  };
}

export function setDashboardHeartRateHistoryShortcutEnabled(config, nextEnabled) {
  const normalized = normalizeDashboardWidgetConfig(config);
  return {
    order: { ...normalized.order },
    visible: { ...normalized.visible },
    layout: {
      ...normalized.layout,
      showHeartRateHistoryShortcut: !!nextEnabled,
    },
    placement: cloneConfig(normalized).placement,
    headers: cloneConfig(normalized).headers,
  };
}

export function setDashboardCleaningLockEnabled(config, nextEnabled) {
  const normalized = normalizeDashboardWidgetConfig(config);
  return {
    order: { ...normalized.order },
    visible: { ...normalized.visible },
    layout: {
      ...normalized.layout,
      cleaningLockEnabled: !!nextEnabled,
    },
    placement: cloneConfig(normalized).placement,
    headers: cloneConfig(normalized).headers,
  };
}

export function setDashboardWidgetSpan(config, key, nextSpan) {
  const normalized = normalizeDashboardWidgetConfig(config);
  if (!key || !Object.prototype.hasOwnProperty.call(normalized.placement, key)) {
    return normalized;
  }

  return {
    order: { ...normalized.order },
    visible: { ...normalized.visible },
    layout: { ...normalized.layout },
    headers: cloneConfig(normalized).headers,
    placement: {
      ...cloneConfig(normalized).placement,
      [key]: {
        ...(normalized.placement[key] || {}),
        span: normalizeWidgetSpan(nextSpan),
      },
    },
  };
}

export function setDashboardHeaderFontSize(config, nextFontSize) {
  const normalized = normalizeDashboardWidgetConfig(config);
  return {
    order: { ...normalized.order },
    visible: { ...normalized.visible },
    layout: { ...normalized.layout },
    placement: cloneConfig(normalized).placement,
    headers: {
      ...cloneConfig(normalized).headers,
      titleFontSize: clampHeaderFontSize(nextFontSize),
    },
  };
}

export function setDashboardWidgetHeaderText(config, key, patch = {}) {
  const normalized = normalizeDashboardWidgetConfig(config);
  if (!key || !Object.prototype.hasOwnProperty.call(normalized.headers.widgets, key)) {
    return normalized;
  }

  const headers = cloneConfig(normalized).headers;
  headers.widgets[key] = {
    ...(headers.widgets[key] || {}),
    title: normalizeHeaderText(patch.title ?? headers.widgets[key]?.title),
    subtitle: normalizeHeaderText(patch.subtitle ?? headers.widgets[key]?.subtitle),
  };

  return {
    order: { ...normalized.order },
    visible: { ...normalized.visible },
    layout: { ...normalized.layout },
    placement: cloneConfig(normalized).placement,
    headers,
  };
}
