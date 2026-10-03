import { onDomReady } from "./dom-ready.js";
import {
  DASHBOARD_WIDGETS_CHANGED_EVENT,
  DASHBOARD_WIDGET_STORAGE_KEY,
  loadDashboardWidgetConfig,
} from "./dashboard-settings.js";

function applyOrder(orderMap) {
  const dash = document.querySelector(".dash");
  if (!dash) return;
  const items = Array.from(dash.children).filter((el) =>
    el.classList.contains("card")
  );
  const originalIndex = new Map(items.map((el, i) => [el, i]));
  const weight = (el) => {
    const key = el.dataset.widget || "";
    const val = orderMap[key];
    return Number.isFinite(val) ? val : 1000;
  };

  items
    .slice()
    .sort((a, b) => {
      const diff = weight(a) - weight(b);
      if (diff !== 0) return diff;
      return originalIndex.get(a) - originalIndex.get(b);
    })
    .forEach((el) => dash.appendChild(el));
}

function applyVisibility(visibleMap) {
  const dash = document.querySelector(".dash");
  if (!dash) return;
  const items = Array.from(dash.children).filter((el) =>
    el.classList.contains("card")
  );
  items.forEach((el) => {
    const key = el.dataset.widget || "";
    const show = visibleMap[key] !== false;
    if (key === "quote") {
      el.dataset.enabled = show ? "true" : "false";
      el.style.gridRowStart = "";
      el.style.gridRowEnd = "";
      el.style.alignSelf = "";
      el.style.minHeight = "";
      el.style.height = "";
      if (show) {
        el.removeAttribute("hidden");
      } else {
        el.setAttribute("hidden", "");
      }
      return;
    }
    if (show) {
      el.removeAttribute("hidden");
      el.style.gridRowEnd = "";
    } else {
      el.setAttribute("hidden", "");
      el.style.gridRowEnd = "";
    }
  });
}

function getColumnCount(config) {
  const columns = Number.parseInt(config?.layout?.columns, 10);
  if (!Number.isFinite(columns)) return 2;
  return Math.min(4, Math.max(2, columns));
}

function normalizeSpan(value) {
  const span = String(value || "auto").trim().toLowerCase();
  if (span === "full" || span === "1" || span === "2" || span === "3") {
    return span;
  }
  return "auto";
}

function resolveGridColumn(span, columns) {
  if (span === "full") return "1 / -1";
  const numeric = Number.parseInt(span, 10);
  if (Number.isFinite(numeric)) {
    const safeSpan = Math.min(columns, Math.max(1, numeric));
    return safeSpan > 1 ? `span ${safeSpan}` : "";
  }
  return "";
}

function effectivePlacementSpan(item) {
  if (
    item?.dataset?.widget === "cleaning"
    && item.closest(".dash")?.dataset?.cleaningLocked === "true"
  ) {
    return "full";
  }
  return normalizeSpan(item?.dataset?.placementSpan);
}

function isAutoFitEnabled(config = activeDashboardConfig) {
  return config?.layout?.autoFit === true;
}

function getRenderedColumnCount(grid) {
  const styles = getComputedStyle(grid);
  const columns = styles.gridTemplateColumns
    .split(/\s+/)
    .filter((value) => value && value !== "none").length;
  return Math.max(1, columns || getColumnCount(activeDashboardConfig));
}

function restorePlacementColumn(item, columns) {
  const span = effectivePlacementSpan(item);
  item.style.gridColumn = resolveGridColumn(span, columns);
}

function resetMeasuredPlacement(item, columns) {
  item.style.gridRowStart = "";
  item.style.gridRowEnd = "";
  if (item.dataset.widget !== "quote") {
    item.style.alignSelf = "";
    item.style.minHeight = "";
    item.style.height = "";
  }
  restorePlacementColumn(item, columns);
}

function getPlacementColumnSpan(item, columns) {
  const placementSpan = effectivePlacementSpan(item);
  if (placementSpan === "full") return columns;

  const manualSpan = Number.parseInt(placementSpan, 10);
  if (Number.isFinite(manualSpan)) {
    return Math.min(columns, Math.max(1, manualSpan));
  }

  const styles = getComputedStyle(item);
  const start = String(styles.gridColumnStart || "").trim();
  const end = String(styles.gridColumnEnd || "").trim();
  if (start === "1" && end === "-1") return columns;

  const spanMatch = end.match(/span\s+(\d+)/);
  if (spanMatch) {
    const cssSpan = Number.parseInt(spanMatch[1], 10);
    if (Number.isFinite(cssSpan)) {
      return Math.min(columns, Math.max(1, cssSpan));
    }
  }

  return 1;
}

function measureRowSpan(item, rowHeight, rowGap) {
  const height = item.getBoundingClientRect().height;
  const rowUnit = rowHeight + rowGap;
  return Math.max(1, Math.ceil((height + rowGap) / rowUnit));
}

function resetWidgetLayoutState(card) {
  if (!card) return;
  card.style.gridRowStart = "";
  card.style.gridRowEnd = "";
  if (card.dataset.widget !== "quote") {
    card.style.alignSelf = "";
    card.style.minHeight = "";
    card.style.height = "";
  }
  card.querySelectorAll(".wx-scroll, .wx-chart-scroll").forEach((scroller) => {
    scroller.scrollLeft = 0;
  });
}

function applyLayout(config) {
  const dash = document.querySelector(".dash");
  if (!dash) return;
  dash.classList.remove("layout-ready");
  const columns = getColumnCount(config);
  const previousAutoFit = dash.dataset.autoFit;
  const nextAutoFit = isAutoFitEnabled(config) ? "true" : "false";
  document.documentElement.dataset.dashboardColumns = String(columns);
  dash.dataset.columns = String(columns);
  dash.dataset.autoFit = nextAutoFit;
  dash.style.setProperty("--dashboard-columns", String(columns));

  const placement = config?.placement || {};
  Array.from(dash.children)
    .filter((el) => el.classList.contains("card"))
    .forEach((el) => {
      const key = el.dataset.widget || "";
      const span = normalizeSpan(placement[key]?.span);
      const nextGridColumn = resolveGridColumn(span, columns);
      const layoutChanged = el.dataset.placementSpan !== span
        || el.style.gridColumn !== nextGridColumn
        || previousAutoFit !== nextAutoFit;
      el.dataset.placementSpan = span;
      el.style.gridColumn = nextGridColumn;
      if (layoutChanged) {
        resetWidgetLayoutState(el);
      }
    });

  // Let width-dependent widgets settle before masonry measures heights.
  void dash.offsetHeight;
  window.dispatchEvent(new Event("resize"));
}

let resizeRaf = 0;
let stableTimer = 0;
let windowLoaded = false;
let gridWatching = false;
let pendingScrollAnchor = null;
let activeDashboardConfig = null;

const HEADER_BLOCK_SELECTORS = {
  weather: ".header .title > div",
  aqi: ".aqi-head.with-sep > div",
  cleaning: "#cl-title > div",
  "self-care": "#sc-title > div",
  feelings: "#feelings-title > div",
  reading: ".reading-header-text",
  "phone-telemetry": "#pt-title > div",
  todo: "#todo-title > div",
  bills: "#bills-widget-title > div",
  budget: "#budget-title > div",
  "weight-cut": "#weight-cut-title > div",
  "live-workout": "#live-workout-title > div",
  diet: "#diet-title > div",
  quote: "#quote-title > div",
  jobhunt: "#jobhunt-title > div",
  "ai-usage": "#ai-usage-title > div",
  "mental-health": "#mental-health-title > div",
  "journal-htr": "#journal-htr-widget-title > div",
  "great-timeline": "#great-timeline-title > div",
  films: ".films-head-left > div",
  "cinema-city": ".cinema-city-head-main > div",
  "classical-library": ".classical-widget-title-wrap > div",
  "network-monitor": ".network-head-main > div",
  bm365: ".habits-head > div",
  "brutal-assault-2027": ".habits-head > div",
  "rym-polish-black-metal-top-100": ".habits-head > div",
  habits: ".habits-head > div",
  events: ".events-head-text",
  "event-countdowns": ".event-countdowns-head > div:first-child",
  sensors: ".sensor-head-main",
  "habits-app": "#habits-app-title > div",
  "habits-timeline": ".hm-head > div",
};

const HEADER_TITLE_SELECTORS = [
  ".dashboard-widget-title-text",
  "h3",
  ".events-title",
  ".event-countdowns-title",
  ".cinema-city-title",
  ".sensor-title",
  "#films-title",
  "#classical-widget-title",
  "#network-title",
  "#rdg-title",
  "[id$='-title']",
];
const DASHBOARD_REFRESH_POLL_MS = 5000;
const DASHBOARD_REFRESH_STORAGE_KEY = "dashboard.reload-signal.v1";

let refreshSignalInitialized = false;
let refreshSignalTimer = 0;

function dashboardSettingsRefreshSignal(settings) {
  const request = settings?._refreshRequest || null;
  if (!request) return "";
  try {
    return JSON.stringify(request);
  } catch {
    return String(request?.nonce || request?.requestedAt || "");
  }
}

function readSeenDashboardRefreshSignal() {
  try {
    return window.localStorage?.getItem(DASHBOARD_REFRESH_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeSeenDashboardRefreshSignal(value) {
  try {
    window.localStorage?.setItem(DASHBOARD_REFRESH_STORAGE_KEY, value);
  } catch {}
}

async function fetchDashboardSettingsSnapshot() {
  const response = await fetch("/api/settings/dashboard", { cache: "no-store" });
  if (!response.ok) return null;
  const payload = await response.json().catch(() => ({}));
  return payload?.data || null;
}

async function checkDashboardRefreshSignal() {
  let settingsSnapshot = null;
  try {
    settingsSnapshot = await fetchDashboardSettingsSnapshot();
  } catch {
    settingsSnapshot = null;
  }

  const signalId = dashboardSettingsRefreshSignal(settingsSnapshot);
  const seenId = readSeenDashboardRefreshSignal();
  if (!signalId) {
    refreshSignalInitialized = true;
    if (seenId) {
      writeSeenDashboardRefreshSignal("");
    }
    return;
  }

  if (!refreshSignalInitialized) {
    refreshSignalInitialized = true;
    if (!seenId) {
      writeSeenDashboardRefreshSignal(signalId);
      return;
    }
  }

  if (signalId !== readSeenDashboardRefreshSignal()) {
    writeSeenDashboardRefreshSignal(signalId);
    window.location.reload();
  }
}

function startDashboardRefreshWatcher() {
  if (refreshSignalTimer || typeof fetch !== "function") return;
  checkDashboardRefreshSignal();
  refreshSignalTimer = window.setInterval(checkDashboardRefreshSignal, DASHBOARD_REFRESH_POLL_MS);
}

function ensureHeaderTitleElement(block) {
  if (!block) return null;
  const existing = HEADER_TITLE_SELECTORS
    .map((selector) => block.querySelector(selector))
    .find(Boolean);
  if (existing) return existing;

  const textNode = Array.from(block.childNodes).find(
    (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim(),
  );
  if (!textNode) return null;

  const title = document.createElement("span");
  title.className = "dashboard-widget-title-text";
  title.textContent = textNode.textContent.trim();
  block.replaceChild(title, textNode);
  return title;
}

function removeHeaderSubtitles(block) {
  if (!block) return;
  block.querySelectorAll(".dashboard-widget-subtitle, .meta, .muted").forEach((element) => element.remove());
}

function rememberDefaultText(element) {
  if (!element || element.dataset.defaultText !== undefined) return;
  element.dataset.defaultText = element.textContent.trim();
}

function setElementText(element, value) {
  if (!element) return;
  rememberDefaultText(element);
  if (!value && element.dataset.dashboardCustom !== "true") {
    return;
  }

  const nextText = value || element.dataset.defaultText || "";
  if (element.textContent !== nextText) {
    element.textContent = nextText;
  }
  if (value) {
    element.dataset.dashboardCustom = "true";
  } else {
    delete element.dataset.dashboardCustom;
  }
  if (element.classList.contains("dashboard-widget-subtitle")) {
    element.hidden = !element.textContent.trim();
  }
}

function applyHeaderCustomization(config = activeDashboardConfig) {
  const dash = document.querySelector(".dash");
  if (!dash || !config) return;
  const fontSize = Number.parseInt(config.headers?.titleFontSize, 10) || 16;
  dash.style.setProperty("--dashboard-header-font-size", `${fontSize}px`);

  const headerMap = config.headers?.widgets || {};
  Array.from(dash.querySelectorAll(".card[data-widget]")).forEach((card) => {
    const key = card.dataset.widget || "";
    const blockSelector = HEADER_BLOCK_SELECTORS[key];
    if (!blockSelector) return;
    const block = card.querySelector(blockSelector);
    if (!block) return;

    const title = ensureHeaderTitleElement(block);
    removeHeaderSubtitles(block);
    setElementText(title, headerMap[key]?.title);
  });
}

function getPendingRequests() {
  return Number.isFinite(window.__pendingRequests)
    ? window.__pendingRequests
    : 0;
}

function scheduleLayoutStable() {
  if (!windowLoaded) return;
  if (stableTimer) clearTimeout(stableTimer);
  stableTimer = setTimeout(() => {
    if (getPendingRequests() > 0) {
      scheduleLayoutStable();
      return;
    }
    window.__dashboardStable = true;
    document.dispatchEvent(new CustomEvent("dashboard:stable"));
  }, 2000);
}

function scheduleMasonryResize(options = {}) {
  pendingScrollAnchor = pendingScrollAnchor || captureScrollAnchor(options.anchor);
  if (resizeRaf) cancelAnimationFrame(resizeRaf);
  resizeRaf = requestAnimationFrame(resizeMasonry);
}

const COMPACT_LOOKAHEAD_LIMIT = 18;
const COMPACT_STRETCH_ROW_LIMIT = 5;
const COMPACT_GAP_FILL_MIN_ROWS = 2;
const COMPACT_FIXED_FIRST_WIDGETS = new Set(["weather", "aqi"]);

function clearCompactFillers(grid) {
  grid.querySelectorAll(".dashboard-gap-fill").forEach((filler) => filler.remove());
}

function resizeMasonry() {
  resizeRaf = 0;
  const grid = document.querySelector(".dash");
  if (!grid) return;
  const scrollAnchor = pendingScrollAnchor || captureScrollAnchor();
  pendingScrollAnchor = null;
  const styles = getComputedStyle(grid);
  const rowHeight = parseInt(styles.getPropertyValue("grid-auto-rows"), 10);
  const rowGap = parseInt(styles.getPropertyValue("gap"), 10) || 0;
  if (!rowHeight) return;
  clearCompactFillers(grid);

  const items = Array.from(grid.children).filter((el) =>
    el.classList.contains("card") && !el.hasAttribute("hidden")
  );
  if (grid.dataset.cleaningLocked === "true") {
    items.sort((a, b) => {
      if (a.dataset.widget === "cleaning") return -1;
      if (b.dataset.widget === "cleaning") return 1;
      return 0;
    });
  }
  const columns = getRenderedColumnCount(grid);
  items.forEach((item) => resetMeasuredPlacement(item, columns));
  void grid.offsetHeight;

  if (isAutoFitEnabled()) {
    applyCompactMasonry(grid, items, columns, rowHeight, rowGap);
  } else {
    items.forEach((item) => {
      const span = measureRowSpan(item, rowHeight, rowGap);
      item.style.gridRowEnd = `span ${span}`;
    });
    placeQuoteInGap(grid, rowHeight, rowGap);
  }

  grid.classList.add("layout-ready");
  restoreScrollAnchor(scrollAnchor);
  scheduleLayoutStable();
}

function applyCompactMasonry(grid, items, columns, rowHeight, rowGap) {
  const entries = items.map((item) => ({
    item,
    key: item.dataset.widget || "",
    colSpan: getPlacementColumnSpan(item, columns),
    rowSpan: measureRowSpan(item, rowHeight, rowGap),
  }));
  const columnHeights = Array.from({ length: columns }, () => 1);
  const lastByColumn = Array.from({ length: columns }, () => null);
  const used = new Set();

  entries.forEach((entry, index) => {
    if (used.has(index)) return;
    entry.colSpan = Math.min(columns, Math.max(1, entry.colSpan));

    if (entry.colSpan >= columns) {
      fillCompactGapsBeforeFull(grid, entries, index, used, columnHeights, lastByColumn, columns);
      stretchSmallCompactGaps(columnHeights, lastByColumn);
      placeCompactGapFillers(grid, columnHeights);
      placeCompactEntry(entry, 0, Math.max(...columnHeights), columns, columnHeights, lastByColumn);
      return;
    }

    const column = findBestCompactColumn(columnHeights, entry.colSpan);
    const rowStart = getSpanHeight(columnHeights, column, entry.colSpan);
    placeCompactEntry(entry, column, rowStart, columns, columnHeights, lastByColumn);
  });

  placeCompactGapFillers(grid, columnHeights);
}

function findBestCompactColumn(columnHeights, colSpan) {
  let bestColumn = 0;
  let bestHeight = Infinity;
  let bestBalance = Infinity;
  const maxStart = columnHeights.length - colSpan;

  for (let column = 0; column <= maxStart; column += 1) {
    const heights = columnHeights.slice(column, column + colSpan);
    const height = Math.max(...heights);
    const balance = heights.reduce((sum, value) => sum + value, 0);
    if (height < bestHeight || (height === bestHeight && balance < bestBalance)) {
      bestColumn = column;
      bestHeight = height;
      bestBalance = balance;
    }
  }

  return bestColumn;
}

function getSpanHeight(columnHeights, column, colSpan) {
  return Math.max(...columnHeights.slice(column, column + colSpan));
}

function placeCompactEntry(entry, column, rowStart, columns, columnHeights, lastByColumn) {
  const colSpan = Math.min(columns, Math.max(1, entry.colSpan));
  const rowSpan = Math.max(1, entry.rowSpan);
  const rowEnd = rowStart + rowSpan;

  entry.item.style.gridColumn = colSpan >= columns
    ? "1 / -1"
    : `${column + 1} / span ${colSpan}`;
  entry.item.style.gridRowStart = String(rowStart);
  entry.item.style.gridRowEnd = `span ${rowSpan}`;

  if (entry.item.dataset.widget !== "quote") {
    entry.item.style.alignSelf = "";
    entry.item.style.minHeight = "";
    entry.item.style.height = "";
  }

  for (let offset = 0; offset < colSpan; offset += 1) {
    columnHeights[column + offset] = rowEnd;
    lastByColumn[column + offset] = entry;
  }
}

function fillCompactGapsBeforeFull(grid, entries, fullIndex, used, columnHeights, lastByColumn, columns) {
  let changed = true;
  while (changed) {
    changed = false;
    const slot = findLargestCompactGap(columnHeights);
    if (!slot || slot.height < COMPACT_GAP_FILL_MIN_ROWS) return;

    const candidate = findCompactLookaheadCandidate(entries, fullIndex, used, slot, columns);
    if (!candidate) return;

    const rowStart = getSpanHeight(columnHeights, slot.column, candidate.entry.colSpan);
    placeCompactEntry(candidate.entry, slot.column, rowStart, columns, columnHeights, lastByColumn);
    used.add(candidate.index);
    changed = true;
  }
}

function findLargestCompactGap(columnHeights) {
  const target = Math.max(...columnHeights);
  let best = null;
  let column = 0;

  while (column < columnHeights.length) {
    if (columnHeights[column] >= target) {
      column += 1;
      continue;
    }

    const start = column;
    let minGap = target - columnHeights[column];
    while (column < columnHeights.length && columnHeights[column] < target) {
      minGap = Math.min(minGap, target - columnHeights[column]);
      column += 1;
    }

    const width = column - start;
    const area = width * minGap;
    if (!best || area > best.area) {
      best = { column: start, width, height: minGap, area };
    }
  }

  return best;
}

function findCompactLookaheadCandidate(entries, fullIndex, used, slot, columns) {
  const end = Math.min(entries.length, fullIndex + 1 + COMPACT_LOOKAHEAD_LIMIT);
  let best = null;

  for (let index = fullIndex + 1; index < end; index += 1) {
    if (used.has(index)) continue;
    const entry = entries[index];
    if (!entry) continue;
    entry.colSpan = Math.min(columns, Math.max(1, entry.colSpan));
    if (COMPACT_FIXED_FIRST_WIDGETS.has(entry.key)) continue;
    if (entry.colSpan >= columns) continue;
    if (entry.colSpan > slot.width || entry.rowSpan > slot.height) continue;

    const area = entry.colSpan * entry.rowSpan;
    if (!best || area > best.area) {
      best = { index, entry, area };
    }
  }

  return best;
}

function placeCompactGapFillers(grid, columnHeights) {
  const target = Math.max(...columnHeights);
  let column = 0;

  while (column < columnHeights.length) {
    const rowStart = columnHeights[column];
    if (target - rowStart < COMPACT_GAP_FILL_MIN_ROWS) {
      column += 1;
      continue;
    }

    const start = column;
    let span = 1;
    while (
      start + span < columnHeights.length
      && columnHeights[start + span] === rowStart
      && target - columnHeights[start + span] >= COMPACT_GAP_FILL_MIN_ROWS
    ) {
      span += 1;
    }

    const filler = document.createElement("div");
    filler.className = "dashboard-gap-fill";
    filler.setAttribute("aria-hidden", "true");
    filler.style.gridColumn = `${start + 1} / span ${span}`;
    filler.style.gridRowStart = String(rowStart);
    filler.style.gridRowEnd = String(target);
    grid.appendChild(filler);

    for (let offset = 0; offset < span; offset += 1) {
      columnHeights[start + offset] = target;
    }
    column = start + span;
  }
}

function stretchSmallCompactGaps(columnHeights, lastByColumn) {
  const target = Math.max(...columnHeights);
  const stretched = new Set();

  columnHeights.forEach((height, column) => {
    const delta = target - height;
    const entry = lastByColumn[column];
    if (!entry || stretched.has(entry.item) || entry.colSpan !== 1) return;
    if (delta <= 0 || delta > COMPACT_STRETCH_ROW_LIMIT) return;

    entry.rowSpan += delta;
    entry.item.style.gridRowEnd = `span ${entry.rowSpan}`;
    if (entry.item.dataset.widget !== "quote") {
      entry.item.style.alignSelf = "stretch";
      entry.item.style.minHeight = "0";
      entry.item.style.height = "100%";
    }
    columnHeights[column] = target;
    stretched.add(entry.item);
  });
}

function captureScrollAnchor(preferred) {
  if (typeof window === "undefined") return null;
  const currentScrollY = window.scrollY || window.pageYOffset || 0;
  if (currentScrollY < 4) return null;
  const grid = document.querySelector(".dash");
  if (!grid) return null;
  const candidate = resolveAnchorElement(preferred) || findViewportAnchor(grid);
  if (!candidate) return null;
  const rect = candidate.getBoundingClientRect();
  return {
    element: candidate,
    top: rect.top,
    scrollY: currentScrollY,
  };
}

function resolveAnchorElement(value) {
  if (value instanceof Element && document.contains(value)) {
    return value.closest(".card") || value;
  }
  if (typeof value !== "string" || !value.trim()) return null;
  return document.querySelector(value);
}

function findViewportAnchor(grid) {
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  const targetTop = Math.min(Math.max(96, viewportHeight * 0.22), viewportHeight * 0.45);
  const visibleCards = Array.from(grid.children).filter((el) => {
    if (!el.classList.contains("card") || el.hasAttribute("hidden")) return false;
    const rect = el.getBoundingClientRect();
    return rect.bottom > 0 && rect.top < viewportHeight;
  });
  if (!visibleCards.length) return null;

  return visibleCards
    .map((element) => {
      const rect = element.getBoundingClientRect();
      const visibleTop = Math.max(rect.top, 0);
      const visibleBottom = Math.min(rect.bottom, viewportHeight);
      const visibleHeight = Math.max(0, visibleBottom - visibleTop);
      const distance = Math.abs(rect.top - targetTop);
      return { element, visibleHeight, distance };
    })
    .sort((a, b) => {
      const heightDiff = b.visibleHeight - a.visibleHeight;
      if (heightDiff) return heightDiff;
      return a.distance - b.distance;
    })[0]?.element || null;
}

function restoreScrollAnchor(anchor) {
  if (!anchor?.element || !document.contains(anchor.element)) return;
  const beforeY = window.scrollY || window.pageYOffset || 0;
  const nextTop = anchor.element.getBoundingClientRect().top;
  const delta = nextTop - anchor.top;
  if (Math.abs(delta) < 1) return;
  window.scrollTo({ top: Math.max(0, beforeY + delta), left: window.scrollX || 0, behavior: "auto" });
}

function placeQuoteInGap(grid, rowHeight, rowGap) {
  const quote = document.getElementById("quote-card");
  if (!quote) return;
  const quoteSpan = normalizeSpan(quote.dataset.placementSpan);
  const hasManualQuoteSpan = quoteSpan !== "auto";

  const resetQuotePlacement = ({ keepColumn = hasManualQuoteSpan } = {}) => {
    if (!keepColumn) {
      quote.style.gridColumn = "";
    }
    quote.style.gridRowStart = "";
    quote.style.gridRowEnd = "";
    quote.style.alignSelf = "";
    quote.style.minHeight = "";
    quote.style.height = "";
  };

  if (quote.dataset.enabled === "false") {
    quote.setAttribute("hidden", "");
    return;
  }
  quote.removeAttribute("hidden");

  if (hasManualQuoteSpan) {
    resetQuotePlacement({ keepColumn: true });
    return;
  }

  if (quote.dataset.ready !== "true") {
    resetQuotePlacement({ keepColumn: false });
    return;
  }

  resetQuotePlacement({ keepColumn: false });

  const anchor = grid.querySelector('.card[data-widget="habits-timeline"]');
  if (!anchor || anchor.hasAttribute("hidden")) {
    quote.removeAttribute("hidden");
    return;
  }

  const gridRect = grid.getBoundingClientRect();
  const anchorRect = anchor.getBoundingClientRect();
  const anchorTop = anchorRect.top - gridRect.top;

  const candidates = Array.from(grid.children).filter(
    (el) =>
      el.classList.contains("card") &&
      !el.hasAttribute("hidden") &&
      el !== quote &&
      el !== anchor
  );
  if (candidates.length === 0) {
    quote.removeAttribute("hidden");
    return;
  }

  const columnsMap = new Map();
  candidates.forEach((card) => {
    const rect = card.getBoundingClientRect();
    const left = Math.round(rect.left - gridRect.left);
    if (!columnsMap.has(left)) columnsMap.set(left, []);
    columnsMap.get(left).push({ card, rect });
  });

  const colLefts = Array.from(columnsMap.keys()).sort((a, b) => a - b);
  if (colLefts.length < 2) {
    quote.removeAttribute("hidden");
    return;
  }

  const rowUnit = rowHeight + rowGap;
  const minGapRows = 2;
  const anchorRowStart = Math.round(anchorTop / rowUnit) + 1;

  let best = null;
  colLefts.forEach((left, index) => {
    const entries = columnsMap.get(left) || [];
    if (entries.length === 0) return;

    let maxRowEnd = 1;
    entries.forEach(({ card, rect }) => {
      const top = rect.top - gridRect.top;
      const rowStart = Math.round(top / rowUnit) + 1;
      if (rowStart >= anchorRowStart) return;

      let span = 1;
      const inlineEnd = card.style.gridRowEnd || "";
      const match = inlineEnd.match(/span\s+(\d+)/);
      if (match) {
        span = parseInt(match[1], 10) || 1;
      } else {
        span = Math.ceil((rect.height + rowGap) / rowUnit);
      }
      const rowEnd = rowStart + span;
      if (rowEnd > maxRowEnd) maxRowEnd = rowEnd;
    });

    const gapRows = anchorRowStart - maxRowEnd;
    if (gapRows < minGapRows) return;
    if (!best || gapRows > best.gapRows) {
      best = { index, gapRows, rowStart: maxRowEnd };
    }
  });

  if (!best) {
    quote.removeAttribute("hidden");
    return;
  }

  if (!best || best.gapRows < minGapRows) {
    quote.removeAttribute("hidden");
    return;
  }

  const gapRowStart = best.rowStart;
  const span = anchorRowStart - gapRowStart;
  if (span < 1) {
    quote.removeAttribute("hidden");
    return;
  }

  quote.style.gridColumn = `${best.index + 1}`;
  quote.style.gridRowStart = `${gapRowStart}`;
  quote.style.gridRowEnd = `${anchorRowStart}`;
  quote.style.alignSelf = "stretch";
  quote.style.minHeight = "0";
  quote.style.height = "100%";
  quote.removeAttribute("hidden");
}

function applyDashboardWidgetConfig(config) {
  if (!config) return;
  activeDashboardConfig = config;
  applyVisibility(config.visible || {});
  applyOrder(config.order || {});
  applyLayout(config);
  applyHeaderCustomization(config);
  scheduleMasonryResize();
}

async function syncDashboardLayoutFromConfig() {
  const config = await loadDashboardWidgetConfig();
  applyDashboardWidgetConfig(config);
}

function watchGrid() {
  if (gridWatching) return;
  const grid = document.querySelector(".dash");
  if (!grid) return;
  gridWatching = true;

  const mo = new MutationObserver((mutations) => {
    const onlyCompactFillers = mutations.every((mutation) => {
      const nodes = [...mutation.addedNodes, ...mutation.removedNodes];
      return nodes.length > 0
        && nodes.every((node) =>
          node.nodeType === Node.ELEMENT_NODE
          && node.classList.contains("dashboard-gap-fill"));
    });
    if (onlyCompactFillers) return;
    applyHeaderCustomization();
    scheduleMasonryResize();
  });
  mo.observe(grid, { childList: true, subtree: true, characterData: true });

  if ("ResizeObserver" in window) {
    const ro = new ResizeObserver(() => scheduleMasonryResize());
    Array.from(grid.children).forEach((el) => {
      if (el.classList.contains("card")) ro.observe(el);
    });
  }

  window.addEventListener("resize", scheduleMasonryResize);
  window.addEventListener("load", () => {
    windowLoaded = true;
    scheduleMasonryResize();
    scheduleLayoutStable();
  });

  document.addEventListener("quote:ready", scheduleMasonryResize);
  document.addEventListener("dashboard:net", scheduleLayoutStable);
  document.addEventListener("dashboard:layout-transition", (event) => {
    pendingScrollAnchor = captureScrollAnchor(event.detail?.anchor);
  });
  window.addEventListener("pageshow", () => {
    syncDashboardLayoutFromConfig();
  });
  window.addEventListener("storage", (event) => {
    if (event.key && event.key !== DASHBOARD_WIDGET_STORAGE_KEY) return;
    syncDashboardLayoutFromConfig();
  });
  window.addEventListener(DASHBOARD_WIDGETS_CHANGED_EVENT, (event) => {
    if (event.detail) {
      applyDashboardWidgetConfig(event.detail);
      return;
    }
    syncDashboardLayoutFromConfig();
  });
  window.addEventListener("dashboard:cleaning-lock-changed", () => {
    scheduleMasonryResize({ anchor: "#cleaning-card" });
  });
}

onDomReady(async () => {
  await syncDashboardLayoutFromConfig();
  watchGrid();
  startDashboardRefreshWatcher();
});
