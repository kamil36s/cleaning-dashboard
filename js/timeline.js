import { DataSet, Timeline } from "vis-timeline/standalone";
import "vis-timeline/styles/vis-timeline-graph2d.css";
import moment from "moment";
import "moment/locale/pl.js";
import {
  DATE_PRECISIONS,
  PRECISION_LABELS,
  createId,
  escapeHtml,
  filterTimelineItems,
  formatDatePart,
  formatItemDuration,
  formatIsoDate,
  formatIsoTimestamp,
  formatStoredDate,
  itemsToCsv,
  makeExportDocument,
  makeImportTemplate,
  normalizeImportDocument,
  parseDateInput,
  parseDisplayDate,
  toVisItem,
  toTravelGapVisItems,
  travelFlagRegionCode,
  travelFlagsFromTitle,
  travelItemLabelVariants,
  validateTimelineItem,
} from "./timeline-model.js";
import {
  createTimelineCategory,
  createTimelineItem,
  deleteTimelineCategory,
  deleteTimelineItem,
  fetchTimeline,
  importTimeline,
  updateTimelineCategory,
  updateTimelineItem,
} from "./timeline-api.js";
import { fetchTimelineActivity, importHowWeFeel, importLoopHabits } from "./timeline-activity-api.js";
import {
  ACTIVITY_SOURCES,
  DEFAULT_ACTIVITY_SETTINGS,
  activityEventTextBlocks,
  activityGranularityForRange,
  activityPeriodSummary,
  activityToCsv,
  aggregateActivityDays,
  buildTextReport,
  enabledSources,
  filterActivityForReport,
  formatActivityDate,
  normalizeActivitySettings,
  sourceFor,
  timelineItemsInRange,
} from "./timeline-activity-model.js?v=poems-context-2";

moment.locale("pl");

const VIEW_STORAGE_KEY = "dashboard.great-timeline.view.v1";
const ACTIVITY_STORAGE_KEY = "dashboard.great-timeline.activity.v1";
const PAGE_SIZE = 50;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const FLAG_COLOR_PALETTES = {
  AT: [["#ed2939", 2], ["#ffffff", 1]], BA: [["#002395", 7], ["#fecb00", 2], ["#ffffff", 1]],
  BE: [["#111111", 1], ["#fdda24", 1], ["#ef3340", 1]], BG: [["#ffffff", 1], ["#00966e", 1], ["#d62612", 1]],
  CA: [["#d80621", 1], ["#ffffff", 1]], CH: [["#d52b1e", 4], ["#ffffff", 1]],
  CN: [["#de2910", 6], ["#ffde00", 1]], CY: [["#ffffff", 7], ["#d57800", 2], ["#4e5b31", 1]],
  CZ: [["#ffffff", 3], ["#d7141a", 3], ["#11457e", 2]], DE: [["#111111", 1], ["#dd0000", 1], ["#ffce00", 1]],
  DK: [["#c60c30", 4], ["#ffffff", 1]], EE: [["#4891d9", 1], ["#111111", 1], ["#ffffff", 1]],
  EG: [["#ce1126", 1], ["#ffffff", 1], ["#111111", 1]], ES: [["#aa151b", 1], ["#f1bf00", 1]],
  FI: [["#ffffff", 3], ["#003580", 1]], FR: [["#0055a4", 1], ["#ffffff", 1], ["#ef4135", 1]],
  GE: [["#ffffff", 3], ["#ff0000", 1]], GR: [["#0d5eaf", 3], ["#ffffff", 2]],
  HR: [["#ff0000", 1], ["#ffffff", 1], ["#171796", 1]], HU: [["#ce2939", 1], ["#ffffff", 1], ["#477050", 1]],
  IE: [["#169b62", 1], ["#ffffff", 1], ["#ff883e", 1]], IL: [["#ffffff", 3], ["#0038b8", 1]],
  IN: [["#ff9933", 1], ["#ffffff", 1], ["#138808", 1], ["#000080", .15]], IT: [["#009246", 1], ["#ffffff", 1], ["#ce2b37", 1]],
  JO: [["#111111", 1], ["#ffffff", 1], ["#007a3d", 1], ["#ce1126", 1]], JP: [["#ffffff", 4], ["#bc002d", 1]],
  LT: [["#fdb913", 1], ["#006a44", 1], ["#c1272d", 1]], LV: [["#9e3039", 4], ["#ffffff", 1]],
  MA: [["#c1272d", 6], ["#006233", 1]], MD: [["#0046ae", 1], ["#ffd200", 1], ["#cc092f", 1]],
  ME: [["#c40308", 7], ["#d4af37", 2], ["#1d5eaa", 1]], MK: [["#d20000", 7], ["#ffe600", 3]],
  NL: [["#ae1c28", 1], ["#ffffff", 1], ["#21468b", 1]], NO: [["#ba0c2f", 3], ["#ffffff", 1], ["#00205b", 1]],
  PL: [["#ffffff", 1], ["#dc143c", 1]], PT: [["#046a38", 2], ["#da291c", 3], ["#ffcc29", .3]],
  RO: [["#002b7f", 1], ["#fcd116", 1], ["#ce1126", 1]], RS: [["#c6363c", 1], ["#0c4076", 1], ["#ffffff", 1]],
  SE: [["#006aa7", 3], ["#fecc00", 1]], SI: [["#ffffff", 1], ["#005da4", 1], ["#ed1c24", 1]],
  SK: [["#ffffff", 1], ["#0b4ea2", 1], ["#ee1c25", 1]], TR: [["#e30a17", 6], ["#ffffff", 1]],
  UA: [["#0057b7", 1], ["#ffd700", 1]], XK: [["#244aa5", 7], ["#d0a650", 2], ["#ffffff", 1]],
  "GB-ENG": [["#ffffff", 4], ["#ce1124", 1]], "GB-SCT": [["#0065bd", 4], ["#ffffff", 1]],
  "GB-WLS": [["#ffffff", 3], ["#00ab39", 3], ["#d30731", 2]],
};

const travelGradientCache = new Map();
let responsiveTravelFrame = 0;
let timelineRowFitFrame = 0;
let timelineLabelFitFrame = 0;

const TIMELINE_LABEL_MIN_FONT_SIZE = 7;
const TIMELINE_LABEL_MIN_SCALE_X = .7;

function flagColorGradient(title) {
  const flags = travelFlagsFromTitle(title);
  const flagText = flags.join("");
  if (!flagText) return "";
  if (travelGradientCache.has(flagText)) return travelGradientCache.get(flagText);
  const weightedColors = flags.flatMap((flag) => {
    const code = travelFlagRegionCode(flag);
    const fallbackHue = [...code].reduce((sum, character) => sum + character.charCodeAt(0) * 17, 0) % 360;
    const palette = FLAG_COLOR_PALETTES[code] || [[`hsl(${fallbackHue} 68% 44%)`, 3], ["#f1f1f1", 1]];
    const paletteTotal = palette.reduce((sum, row) => sum + row[1], 0);
    return palette.map(([color, weight]) => [color, weight / paletteTotal / flags.length]);
  });
  const blendedColors = weightedColors.reduce((rows, [color, weight]) => {
    const previous = rows.at(-1);
    if (previous?.[0] === color) previous[1] += weight;
    else rows.push([color, weight]);
    return rows;
  }, []);
  let position = 0;
  const centeredStops = blendedColors.map(([color, weight]) => {
    const center = position + weight * 50;
    position += weight * 100;
    return [color, center];
  });
  const stops = [
    `${centeredStops[0][0]} 0%`,
    ...centeredStops.map(([color, center]) => `${color} ${center.toFixed(1)}%`),
    `${centeredStops.at(-1)[0]} 100%`,
  ];
  const gradient = `linear-gradient(115deg, ${stops.join(", ")})`;
  travelGradientCache.set(flagText, gradient);
  return gradient;
}

function updateResponsiveTravelLabels() {
  responsiveTravelFrame = 0;
  for (const [labelClass, variants] of state.travelLabelVariants) {
    const item = elements.canvas.getElementsByClassName(labelClass)[0];
    const label = item?.querySelector(".vis-item-content");
    if (!item || !label) continue;
    item.classList.remove("is-responsive-label-hidden");
    const candidates = [variants.full, variants.medium, variants.compact]
      .filter((value, index, rows) => value && rows.indexOf(value) === index);
    const chosen = candidates.find((variant) => {
      label.textContent = variant;
      // Check the final rendered capsule, including its padding and max-width.
      // If the content is clipped even by a pixel, hide it instead of showing a fragment.
      return label.clientWidth > 0 && label.scrollWidth <= label.clientWidth;
    });
    if (!chosen) item.classList.add("is-responsive-label-hidden");
    else label.textContent = chosen;
  }
}

function scheduleResponsiveTravelLabels() {
  if (responsiveTravelFrame) return;
  responsiveTravelFrame = requestAnimationFrame(updateResponsiveTravelLabels);
}

function updateTimelineItemLabels() {
  timelineLabelFitFrame = 0;
  if (!state.timeline || elements.visualPanel.hidden) return;
  const items = elements.canvas.querySelectorAll(".vis-item.timeline-vis-period, .vis-item.timeline-vis-phase");
  for (const item of items) {
    const content = item.querySelector(".vis-item-content");
    const label = content?.querySelector(".timeline-item-label");
    if (!content || !label) continue;

    label.style.fontSize = "";
    label.style.transform = "";
    item.classList.remove("is-label-too-tight");

    const contentStyle = getComputedStyle(content);
    const baseFontSize = Number.parseFloat(contentStyle.fontSize) || 11;
    const horizontalPadding = (Number.parseFloat(contentStyle.paddingLeft) || 0)
      + (Number.parseFloat(contentStyle.paddingRight) || 0);
    let availableWidth = Math.max(0, item.clientWidth - horizontalPadding - 2);
    const showOngoing = item.classList.contains("is-ongoing") && item.clientWidth >= 110;
    item.classList.toggle("is-compact-ongoing-label", item.classList.contains("is-ongoing") && !showOngoing);
    if (showOngoing) availableWidth = Math.max(0, availableWidth - 43);

    const naturalWidth = label.getBoundingClientRect().width;
    if (!availableWidth || !naturalWidth || naturalWidth <= availableWidth) continue;

    const fittedFontSize = Math.max(
      TIMELINE_LABEL_MIN_FONT_SIZE,
      Math.min(baseFontSize, baseFontSize * availableWidth / naturalWidth),
    );
    label.style.fontSize = `${Math.floor(fittedFontSize * 10) / 10}px`;

    const reducedWidth = label.getBoundingClientRect().width;
    if (reducedWidth <= availableWidth) continue;
    const scaleX = Math.max(TIMELINE_LABEL_MIN_SCALE_X, availableWidth / reducedWidth);
    label.style.transform = `scaleX(${scaleX})`;
    if (reducedWidth * scaleX > availableWidth + .5) item.classList.add("is-label-too-tight");
  }
}

function scheduleTimelineItemLabels() {
  if (timelineLabelFitFrame) cancelAnimationFrame(timelineLabelFitFrame);
  timelineLabelFitFrame = requestAnimationFrame(updateTimelineItemLabels);
}

function updateTimelineRowFit() {
  timelineRowFitFrame = 0;
  if (!state.timeline || elements.visualPanel.hidden) return;
  const viewport = elements.canvas.querySelector(".vis-panel.vis-center");
  const itemset = elements.canvas.querySelector(".vis-itemset");
  const groupCount = elements.canvas.querySelectorAll(".vis-labelset .vis-label").length;
  if (!viewport || !itemset || !groupCount) return;
  const targetHeight = Math.max(0, viewport.clientHeight - 18);
  const adjustment = Math.round((targetHeight - itemset.offsetHeight) / groupCount);
  const nextMargin = Math.max(3, Math.min(14, state.timelineRowMargin + adjustment));
  if (nextMargin === state.timelineRowMargin) return;
  state.timelineRowMargin = nextMargin;
  state.timeline.setOptions({ margin: { item: { horizontal: 5, vertical: nextMargin }, axis: 8 } });
  scheduleTimelineItemLabels();
  timelineRowFitFrame = requestAnimationFrame(updateTimelineRowFit);
}

function scheduleTimelineRowFit() {
  if (timelineRowFitFrame) cancelAnimationFrame(timelineRowFitFrame);
  timelineRowFitFrame = requestAnimationFrame(updateTimelineRowFit);
}

const elements = {
  status: $("#timeline-status"), count: $("#timeline-count"), content: $(".timeline-content"),
  canvas: $("#timeline-canvas"), loading: $("#timeline-loading"), empty: $("#timeline-empty"),
  visualTab: $("#timeline-tab-visual"), listTab: $("#timeline-tab-list"), visualPanel: $("#timeline-visual-panel"), listPanel: $("#timeline-list-panel"),
  entryDialog: $("#timeline-entry-dialog"), entryForm: $("#timeline-entry-form"), entryHeading: $("#timeline-entry-heading"), formErrors: $("#timeline-form-errors"),
  detailDialog: $("#timeline-detail-dialog"), detailContent: $("#timeline-detail-content"),
  categoryDialog: $("#timeline-category-dialog"), categoryList: $("#timeline-category-list"), categoryForm: $("#timeline-category-form"),
  importDialog: $("#timeline-import-dialog"), importFile: $("#timeline-import-file"), importMode: $("#timeline-import-mode"), importConflict: $("#timeline-import-conflict"), importConfirm: $("#timeline-import-confirm"), importConfirmWrap: $("#timeline-import-confirm-wrap"), importReport: $("#timeline-import-report"), importApply: $("#timeline-import-apply"),
  tableBody: $("#timeline-table-body"), pageLabel: $("#timeline-page-label"), pagePrev: $("#timeline-page-prev"), pageNext: $("#timeline-page-next"),
  toast: $("#timeline-toast"), categoryToggles: $("#timeline-category-toggles"),
  activityDialog: $("#timeline-activity-dialog"), activitySources: $("#timeline-activity-sources"), journalContent: $("#timeline-journal-content"),
  dayDialog: $("#timeline-day-dialog"), dayHeading: $("#timeline-day-heading"), dayContent: $("#timeline-day-content"),
  reportDialog: $("#timeline-report-dialog"), reportFrom: $("#timeline-report-from"), reportTo: $("#timeline-report-to"), reportPreview: $("#timeline-report-preview"), reportStatus: $("#timeline-report-status"),
};

const filterElements = {
  search: $("#timeline-filter-search"), categoryId: $("#timeline-filter-category"), subcategory: $("#timeline-filter-subcategory"),
  type: $("#timeline-filter-type"), personId: $("#timeline-filter-person"), location: $("#timeline-filter-location"), tag: $("#timeline-filter-tag"),
  importance: $("#timeline-filter-importance"), status: $("#timeline-filter-status"), precision: $("#timeline-filter-precision"),
  from: $("#timeline-filter-from"), to: $("#timeline-filter-to"), includeHiddenCategories: $("#timeline-filter-hidden"),
  showTravelGaps: $("#timeline-filter-travel-gaps"), colorTravelPills: $("#timeline-filter-travel-colors"), density: $("#timeline-density"),
};

const emptyData = () => ({ schemaVersion: 1, timelineItems: [], people: [], categories: [], sources: [], itemLinks: [], reflections: [] });
const state = {
  data: emptyData(), filtered: [], selectedId: null, editingId: null, timeline: null,
  firstRender: true, page: 1, sortKey: "start", sortDirection: "asc", importData: null,
  filters: {}, hiddenCategoryIds: new Set(), shownCategoryIds: new Set(),
  activity: { days: [], sources: [], totals: { days: 0, events: 0, bySource: {} } },
  activitySettings: normalizeActivitySettings(DEFAULT_ACTIVITY_SETTINGS), reportData: null,
  activityGranularity: null, activityPeriods: new Map(), activityRangeTimer: 0, selectedActivityRange: null,
  visItems: null, ongoingTimer: 0, travelLabelVariants: new Map(), timelineRowMargin: 5,
};

function setStatus(message, tone = "neutral") {
  elements.status.textContent = message;
  elements.status.dataset.tone = tone;
}

let toastTimer = 0;
function showToast(message, tone = "neutral") {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.dataset.tone = tone;
  elements.toast.hidden = false;
  toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 4200);
}

function readViewSettings() {
  try {
    const parsed = JSON.parse(localStorage.getItem(VIEW_STORAGE_KEY) || "{}");
    state.filters = parsed.filters || {};
    state.hiddenCategoryIds = new Set(parsed.hiddenCategoryIds || []);
    state.shownCategoryIds = new Set(parsed.shownCategoryIds || []);
    state.sortKey = parsed.sortKey || "start";
    state.sortDirection = parsed.sortDirection === "desc" ? "desc" : "asc";
  } catch {}
  try {
    state.activitySettings = normalizeActivitySettings(JSON.parse(localStorage.getItem(ACTIVITY_STORAGE_KEY) || "{}"));
  } catch {
    state.activitySettings = normalizeActivitySettings(DEFAULT_ACTIVITY_SETTINGS);
  }
}

function saveViewSettings() {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify({
      filters: state.filters,
      hiddenCategoryIds: [...state.hiddenCategoryIds],
      shownCategoryIds: [...state.shownCategoryIds],
      sortKey: state.sortKey,
      sortDirection: state.sortDirection,
    }));
  } catch {}
}

function saveActivitySettings() {
  try { localStorage.setItem(ACTIVITY_STORAGE_KEY, JSON.stringify(state.activitySettings)); } catch {}
}

function setSelectOptions(select, rows, { placeholder = "", valueKey = "id", labelKey = "name" } = {}) {
  const current = select.value;
  select.innerHTML = `${placeholder ? `<option value="">${escapeHtml(placeholder)}</option>` : ""}${rows.map((row) =>
    `<option value="${escapeHtml(row[valueKey])}">${escapeHtml(row[labelKey] || row[valueKey])}</option>`
  ).join("")}`;
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function sortedCategories() {
  return [...state.data.categories].sort((a, b) => Number(a.order) - Number(b.order) || a.name.localeCompare(b.name));
}

function populateReferenceControls() {
  const categories = sortedCategories();
  setSelectOptions(filterElements.categoryId, categories, { placeholder: "All categories" });
  setSelectOptions(filterElements.personId, state.data.people, { placeholder: "All people", labelKey: "displayName" });
  const categorySelect = elements.entryForm.elements.categoryId;
  setSelectOptions(categorySelect, categories.filter((category) => !category.archived));
  setSelectOptions(elements.entryForm.elements.parentId, state.data.timelineItems, { placeholder: "None", labelKey: "title" });
  setSelectOptions(elements.entryForm.elements.peopleIds, state.data.people, { labelKey: "displayName" });
  setSelectOptions(elements.entryForm.elements.sourceIds, state.data.sources, { labelKey: "title" });
  const subcategories = [...new Set(categories.flatMap((row) => row.subcategories || []).concat(state.data.timelineItems.map((row) => row.subcategory)).filter(Boolean))].sort();
  setSelectOptions(filterElements.subcategory, subcategories.map((value) => ({ id: value, name: value })), { placeholder: "All subcategories" });
  $("#timeline-subcategories").innerHTML = subcategories.map((value) => `<option value="${escapeHtml(value)}"></option>`).join("");
}

function effectiveCategories() {
  return state.data.categories.map((category) => ({
    ...category,
    visible: state.shownCategoryIds.has(category.id)
      || (category.visible !== false && !state.hiddenCategoryIds.has(category.id)),
  }));
}

function renderCategoryToggles() {
  const activityToggles = ACTIVITY_SOURCES.map((source) => {
    const hidden = !state.activitySettings.sources[source.id].timeline;
    return `<button class="timeline-category-toggle${hidden ? " is-hidden" : ""}" style="--category-color:${escapeHtml(source.color)}" data-activity-toggle="${escapeHtml(source.id)}" type="button" aria-pressed="${!hidden}">${escapeHtml(source.label)}</button>`;
  });
  const visibility = new Map(effectiveCategories().map((category) => [category.id, category.visible]));
  const categoryToggles = sortedCategories().map((category) => {
    const hidden = visibility.get(category.id) === false;
    return `<button class="timeline-category-toggle${hidden ? " is-hidden" : ""}" style="--category-color:${escapeHtml(category.color)}" data-category-toggle="${escapeHtml(category.id)}" type="button" aria-pressed="${!hidden}">${escapeHtml(category.name)}</button>`;
  });
  elements.categoryToggles.innerHTML = [...activityToggles, ...categoryToggles].join("");
}

function readFilters() {
  state.filters = Object.fromEntries(Object.entries(filterElements).map(([key, input]) => {
    const raw = input.type === "checkbox" ? input.checked : input.value;
    return [key, ["from", "to"].includes(key) ? parseDisplayDate(raw) : raw];
  }));
  return state.filters;
}

function applyStoredFilters() {
  for (const [key, input] of Object.entries(filterElements)) {
    const value = state.filters[key];
    if (value === undefined) continue;
    if (input.type === "checkbox") input.checked = Boolean(value);
    else input.value = ["from", "to"].includes(key) ? formatIsoDate(value) : String(value);
  }
  elements.content.classList.toggle("is-compact", filterElements.density.value === "compact");
}

function itemSortValue(item, key) {
  if (key === "start") return item.start?.date || item.start?.earliest || "9999";
  return item[key] ?? "";
}

function sortedFilteredItems() {
  const direction = state.sortDirection === "desc" ? -1 : 1;
  return [...state.filtered].sort((a, b) => String(itemSortValue(a, state.sortKey)).localeCompare(String(itemSortValue(b, state.sortKey)), undefined, { numeric: true }) * direction);
}

function categoryName(id) { return state.data.categories.find((row) => row.id === id)?.name || id; }
function personNames(ids = []) { return ids.map((id) => state.data.people.find((row) => row.id === id)?.displayName || id); }

function renderTable() {
  const items = sortedFilteredItems();
  const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  state.page = Math.min(Math.max(1, state.page), pages);
  const start = (state.page - 1) * PAGE_SIZE;
  const pageItems = items.slice(start, start + PAGE_SIZE);
  elements.tableBody.innerHTML = pageItems.length ? pageItems.map((item) => `
    <tr data-id="${escapeHtml(item.id)}">
      <td><strong>${escapeHtml(item.title)}</strong></td><td><span class="timeline-badge">${escapeHtml(item.type)}</span></td><td>${escapeHtml(categoryName(item.categoryId))}</td>
      <td>${escapeHtml(formatDatePart(item.start))}</td><td>${escapeHtml(formatDatePart(item.end, { ongoing: item.ongoing }))}${formatItemDuration(item) ? `<small class="timeline-duration">${escapeHtml(formatItemDuration(item))}</small>` : ""}</td><td>${escapeHtml(PRECISION_LABELS[item.start?.precision] || item.start?.precision)}</td>
      <td>${escapeHtml(item.importance)}</td><td>${escapeHtml(personNames(item.peopleIds).join(", ") || "—")}</td><td>${escapeHtml((item.tagIds || []).join(", ") || "—")}</td>
      <td>${escapeHtml(formatTimestamp(item.updatedAt))}</td><td><div class="timeline-table-actions"><button data-row-action="view" type="button">View</button><button data-row-action="locate" type="button">Locate</button><button data-row-action="edit" type="button">Edit</button><button data-row-action="duplicate" type="button">Duplicate</button><button data-row-action="delete" type="button">Delete</button></div></td>
    </tr>`).join("") : `<tr><td colspan="11">No records match the current filters.</td></tr>`;
  elements.pageLabel.textContent = `Page ${state.page} of ${pages}`;
  elements.pagePrev.disabled = state.page <= 1;
  elements.pageNext.disabled = state.page >= pages;
}

function visibleActivityDays(granularity = null) {
  const allowed = new Set(enabledSources(state.activitySettings, "timeline"));
  const from = state.filters.from || "";
  const to = state.filters.to || "";
  return (state.activity.days || []).map((day) => {
    const events = (day.events || []).filter((event) => (
      allowed.has(event.source)
      && (event.source !== "lastfm" || !granularity || event.metrics?.granularity === granularity)
    ));
    const sourceCounts = {};
    for (const event of events) sourceCounts[event.source] = (sourceCounts[event.source] || 0) + 1;
    return { ...day, events, total: events.length, sourceCounts };
  }).filter((day) => day.events.length && (!from || day.date >= from) && (!to || day.date <= to));
}

function activitySpanDays(days) {
  if (!days.length) return 1;
  const first = new Date(`${days[0].date}T12:00:00`);
  const last = new Date(`${days[days.length - 1].date}T12:00:00`);
  return Math.max(1, Math.round((last - first) / 86_400_000) + 1);
}

function compactNumber(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1000) return new Intl.NumberFormat("pl-PL", { notation: "compact", maximumFractionDigits: 1 }).format(number);
  return String(Math.round(number));
}

function periodSourceValue(period, sourceId) {
  if (sourceId === "lastfm") {
    const events = period.events.filter((event) => event.source === sourceId);
    const chart = events[0]?.metrics || {};
    const artist = chart.topArtist?.name ? ` · ${chart.topArtist.name}` : "";
    return `${compactNumber(chart.scrobbles)} scrobbles${artist}`;
  }
  return activityPeriodSummary(period, sourceId).primary;
}

function activityGroupId(sourceId) {
  return `__daily-signal-${sourceId}`;
}

function activitySourcesForDays(days) {
  const present = new Set(days.flatMap((day) => Object.keys(day.sourceCounts || {})));
  return [
    ...ACTIVITY_SOURCES.filter((source) => present.has(source.id)),
    ...[...present].filter((id) => !ACTIVITY_SOURCES.some((source) => source.id === id)).map(sourceFor),
  ];
}

function activityPeriodForSource(period, sourceId) {
  const events = period.events.filter((event) => event.source === sourceId);
  return {
    ...period,
    id: `${period.id}-${sourceId}`,
    sourceId,
    total: events.length,
    sourceCounts: { [sourceId]: events.length },
    events,
  };
}

function lastFmChartLines(chart) {
  const artist = String(chart.topArtist?.name || "").trim();
  const album = String(chart.topAlbum?.name || "").trim();
  const albumArtist = String(chart.topAlbum?.artist || artist).trim();
  const track = String(chart.topTrack?.name || "").trim();
  const trackArtist = String(chart.topTrack?.artist || artist).trim();
  return [
    artist ? { label: "Artist", icon: "👨🏻‍🎤", name: artist, byArtist: "", value: artist, scrobbles: chart.topArtist?.scrobbles } : null,
    album ? { label: "Album", icon: "💿", name: album, byArtist: albumArtist, value: albumArtist ? `${album} by ${albumArtist}` : album, scrobbles: chart.topAlbum?.scrobbles } : null,
    track ? { label: "Song", icon: "🎵", name: track, byArtist: trackArtist, value: trackArtist ? `${track} by ${trackArtist}` : track, scrobbles: chart.topTrack?.scrobbles } : null,
  ].filter(Boolean);
}

function activityPeriodContent(period, source, previousPeriod = null) {
  if (source.id === "lastfm") {
    const chart = period.events[0]?.metrics || {};
    const lines = lastFmChartLines(chart).map((line) => `<div class="timeline-lastfm-line"><span class="timeline-lastfm-icon" aria-hidden="true">${escapeHtml(line.icon)}</span><strong class="timeline-lastfm-name">${escapeHtml(line.name)}</strong>${line.byArtist ? ` <span class="timeline-lastfm-by">by ${escapeHtml(line.byArtist)}</span>` : ""} <small>${escapeHtml(`${compactNumber(line.scrobbles)}×`)}</small></div>`).join("");
    return `<div class="timeline-signal-card is-${escapeHtml(period.granularity)} is-lastfm" style="--signal-color:${escapeHtml(source.color)}"><div class="timeline-signal-heading"><b class="timeline-lastfm-scrobbles">${escapeHtml(`${source.icon} ${compactNumber(chart.scrobbles)} scrobbles`)}</b></div><div class="timeline-lastfm-chart">${lines}</div></div>`;
  }
  const summary = activityPeriodSummary(period, source.id, previousPeriod);
  const secondary = summary.secondary
    ? `<div class="timeline-signal-secondary"><span>${escapeHtml(summary.secondary)}</span>${summary.trend ? `<span class="timeline-weight-trend is-${escapeHtml(summary.trendTone)}" title="${escapeHtml(summary.trendLabel)}" aria-label="${escapeHtml(summary.trendLabel)}">${escapeHtml(summary.trend)}</span>` : ""}</div>`
    : "";
  return `<div class="timeline-signal-card is-${escapeHtml(period.granularity)}${source.id === "health" ? " is-health" : ""}" style="--signal-color:${escapeHtml(source.color)}"><div class="timeline-signal-heading"><b>${escapeHtml(summary.primary)}</b></div>${secondary}</div>`;
}

function activityVisItem(period, source, previousPeriod = null) {
  const chart = period.events[0]?.metrics || {};
  const title = source.id === "lastfm"
    ? `${source.label} · ${period.label}\n${compactNumber(chart.scrobbles)} scrobbles\n${lastFmChartLines(chart).map((line) => `${line.label}: ${line.value} (${compactNumber(line.scrobbles)})`).join("\n")}`
    : `${source.label} · ${period.label}\n${periodSourceValue(period, source.id)}`;
  return {
    id: period.id,
    group: activityGroupId(source.id),
    start: `${period.start}T00:00:00`,
    end: `${period.endExclusive}T00:00:00`,
    type: "range",
    subgroup: source.id,
    content: activityPeriodContent(period, source, previousPeriod),
    title,
    className: `timeline-activity-signal timeline-activity-${period.granularity}${source.id === "lastfm" ? " timeline-lastfm-signal" : ""}${source.id === "health" ? " timeline-health-signal" : ""}`,
    style: `--signal-color:${source.color}`,
  };
}

function timeAxisForGranularity(granularity) {
  if (granularity === "day") return { scale: "day", step: 1 };
  if (granularity === "week") return { scale: "week", step: 1 };
  if (granularity === "month") return { scale: "month", step: 1 };
  return { scale: "year", step: 1 };
}

function timelineViewportWidth() {
  return elements.canvas.querySelector(".vis-panel.vis-center")?.clientWidth || elements.canvas.clientWidth;
}

function scheduleActivityGranularity(start, end) {
  const days = Math.max(1, (new Date(end) - new Date(start)) / 86_400_000);
  const next = activityGranularityForRange(days, timelineViewportWidth());
  if (next === state.activityGranularity) return;
  clearTimeout(state.activityRangeTimer);
  state.activityRangeTimer = setTimeout(() => {
    state.activityGranularity = next;
    renderTimeline({ keepWindow: true });
  }, 90);
}

function renderTimeline({ keepWindow = true } = {}) {
  const categories = effectiveCategories();
  const categoryMap = new Map(categories.map((row) => [row.id, row]));
  const visibleCategoryIds = new Set(state.filtered.map((item) => item.categoryId));
  const allActivityDays = visibleActivityDays();
  const previousWindow = keepWindow && state.timeline ? state.timeline.getWindow() : null;
  const visibleRangeDays = previousWindow ? Math.max(1, (previousWindow.end - previousWindow.start) / 86_400_000) : activitySpanDays(allActivityDays);
  const granularity = state.activityGranularity || activityGranularityForRange(visibleRangeDays, timelineViewportWidth());
  state.activityGranularity = granularity;
  const activityDays = visibleActivityDays(granularity);
  const activityPeriods = aggregateActivityDays(activityDays, granularity);
  const activityPeriodsByEnd = new Map(activityPeriods.map((period) => [period.endExclusive, period]));
  const activitySources = activitySourcesForDays(activityDays);
  const activitySourcePeriods = activityPeriods.flatMap((period) => activitySources
    .filter((source) => period.sourceCounts[source.id])
    .map((source) => {
      const previousPeriod = activityPeriodsByEnd.get(period.start);
      return [
        activityPeriodForSource(period, source.id),
        source,
        previousPeriod ? activityPeriodForSource(previousPeriod, source.id) : null,
      ];
    }));
  state.activityPeriods = new Map(activitySourcePeriods.map(([period]) => [period.id, period]));
  const travelCategory = categories.find((category) => category.id === "travel")
    || categories.find((category) => String(category.name || "").toLowerCase() === "travel");
  const homeCategory = categories.find((category) => category.id === "home")
    || categories.find((category) => String(category.name || "").toLowerCase() === "home");
  const healthCategory = categories.find((category) => category.id === "health")
    || categories.find((category) => String(category.name || "").toLowerCase() === "health");
  const groups = categories.filter((category) => visibleCategoryIds.has(category.id)).map((category) => ({
    id: category.id,
    content: `<span class="timeline-group-label is-category" style="--group-color:${escapeHtml(category.color)}"><span class="timeline-group-marker" aria-hidden="true"><i class="timeline-group-dot"></i></span><span class="timeline-group-name">${escapeHtml(category.name)}</span></span>`,
    className: category.id === travelCategory?.id ? "timeline-group-travel" : category.id === healthCategory?.id ? "timeline-group-health" : "",
    order: Number(category.order) || 0,
    ...(category.id === travelCategory?.id
      ? { subgroupStack: { travel: false, __enableSubgroupLayout: true } }
      : category.id === homeCategory?.id
        ? { subgroupStack: { home: false, __enableSubgroupLayout: true } }
        : category.id === healthCategory?.id
          ? { subgroupStack: { health: false, __enableSubgroupLayout: true } }
        : {}),
  }));
  groups.unshift(...activitySources.map((source, index) => ({
    id: activityGroupId(source.id),
    content: `<span class="timeline-group-label is-signal" style="--group-color:${escapeHtml(source.color)}"><span class="timeline-group-marker" aria-hidden="true">${escapeHtml(source.icon || "•")}</span><span class="timeline-group-name">${escapeHtml(source.label)}</span></span>`,
    order: -1000 + index,
    // Touching period ranges for a source stay on one timeline row.
    subgroupStack: { [source.id]: false, __enableSubgroupLayout: true },
  })));
  const renderNow = new Date();
  state.travelLabelVariants = new Map();
  const registerResponsiveTravelLabel = (visItem, labels) => {
    const labelClass = `timeline-responsive-label-${state.travelLabelVariants.size}`;
    state.travelLabelVariants.set(labelClass, labels);
    return { ...visItem, className: `${visItem.className || ""} ${labelClass}`.trim() };
  };
  const travelGapsRaw = state.filters.showTravelGaps && travelCategory
    ? toTravelGapVisItems(state.filtered, travelCategory.id, renderNow)
    : [];
  const travelGaps = travelGapsRaw.map(({ responsiveLabels, ...gap }) => registerResponsiveTravelLabel(gap, responsiveLabels));
  const visItems = state.filtered.map((item) => {
    const visItem = toVisItem(item, categoryMap.get(item.categoryId), renderNow);
    if (visItem) visItem.content = `<span class="timeline-item-label">${visItem.content}</span>`;
    if (visItem && item.categoryId === homeCategory?.id) return { ...visItem, subgroup: "home" };
    if (visItem && item.categoryId === healthCategory?.id) return { ...visItem, subgroup: "health", className: `${visItem.className} timeline-vis-health` };
    if (!visItem || item.categoryId !== travelCategory?.id) return visItem;
    const labels = travelItemLabelVariants(item, renderNow);
    const gradient = state.filters.colorTravelPills ? flagColorGradient(item.title) : "";
    return registerResponsiveTravelLabel({
      ...visItem,
      content: escapeHtml(labels.full),
      className: `${visItem.className} timeline-vis-travel${gradient ? " has-flag-gradient" : ""}`,
      style: `${visItem.style}${gradient ? `;--travel-flag-gradient:${gradient}` : ""}`,
      subgroup: "travel",
    }, labels);
  }).filter(Boolean)
    .concat(travelGaps, activitySourcePeriods.map(([period, source, previousPeriod]) => activityVisItem(period, source, previousPeriod)));
  const data = { groups: new DataSet(groups), items: new DataSet(visItems) };
  state.visItems = data.items;
  if (!state.timeline) {
    state.timeline = new Timeline(elements.canvas, data.items, data.groups, {
      stack: true,
      groupOrder: "order",
      horizontalScroll: true,
      verticalScroll: false,
      zoomable: true,
      moveable: true,
      zoomMin: 1000 * 60 * 60 * 24 * 3,
      zoomMax: 1000 * 60 * 60 * 24 * 365 * 180,
      height: "100%",
      margin: { item: { horizontal: 5, vertical: state.timelineRowMargin }, axis: 8 },
      orientation: { axis: "top", item: "top" },
      showCurrentTime: true,
      locale: "pl",
      timeAxis: timeAxisForGranularity(granularity),
      tooltip: { followMouse: true, overflowMethod: "cap" },
      xss: {
        filterOptions: {
          whiteList: {
            b: ["class"],
            div: ["class", "style"],
            i: ["class", "style"],
            small: ["class"],
            span: ["aria-hidden", "class", "style", "title"],
            strong: ["class"],
          },
        },
      },
      format: {
        minorLabels: { millisecond: "SSS", second: "s", minute: "HH:mm", hour: "HH:mm", weekday: "ddd D", day: "D ddd", week: "[tydz.] W", month: "MMMM", year: "YYYY" },
        majorLabels: { millisecond: "HH:mm:ss", second: "D MMMM YYYY HH:mm", minute: "D MMMM YYYY", hour: "D MMMM YYYY", weekday: "MMMM YYYY", day: "MMMM YYYY", week: "MMMM YYYY", month: "YYYY", year: "" },
      },
    });
    state.timeline.on("select", ({ items }) => {
      const id = String(items[0] || "");
      if (id.startsWith("activity-period-")) openActivityPeriodDetails(state.activityPeriods.get(id));
      else if (id) openDetails(id);
    });
    state.timeline.on("rangechanged", ({ start, end }) => {
      scheduleResponsiveTravelLabels();
      scheduleTimelineItemLabels();
      scheduleActivityGranularity(start, end);
    });
  } else {
    state.timeline.setOptions({ timeAxis: timeAxisForGranularity(granularity) });
    state.timeline.setData(data);
  }
  if (previousWindow && previousWindow.start < previousWindow.end) {
    state.timeline.setWindow(previousWindow.start, previousWindow.end, { animation: false });
  } else if (visItems.length) {
    state.timeline.fit({ animation: false });
  }
  elements.loading.hidden = true;
  elements.empty.hidden = state.data.timelineItems.length !== 0 || activityDays.length !== 0;
  scheduleResponsiveTravelLabels();
  scheduleTimelineItemLabels();
  scheduleTimelineRowFit();
}

function syncOngoingItemsToNow() {
  if (!state.visItems) return;
  const now = new Date();
  for (const item of state.filtered) {
    if (item.ongoing && item.type !== "point") state.visItems.update({ id: item.id, end: now });
  }
}

function renderAll(options = {}) {
  readFilters();
  elements.content.classList.toggle("is-compact", filterElements.density.value === "compact");
  state.filtered = filterTimelineItems(state.data.timelineItems, state.filters, effectiveCategories());
  const activityDays = visibleActivityDays(state.activityGranularity);
  elements.count.textContent = `${state.filtered.length} entries · ${activityDays.length} signal days`;
  renderCategoryToggles();
  renderTimeline(options);
  renderTable();
  saveViewSettings();
}

function precisionOptions() {
  return DATE_PRECISIONS.map((value) => `<option value="${value}">${escapeHtml(PRECISION_LABELS[value])}</option>`).join("");
}

function configureDateField(partName) {
  const fieldset = $(`[data-date-part="${partName}"]`, elements.entryForm);
  const precision = elements.entryForm.elements[`${partName}Precision`].value;
  const singleLabel = $("[data-date-single]", fieldset);
  const input = elements.entryForm.elements[`${partName}Date`];
  const range = $("[data-date-range]", fieldset);
  const isRange = precision === "date_range";
  const isUnknown = precision === "unknown";
  range.hidden = !isRange;
  singleLabel.hidden = isRange || isUnknown;
  input.type = "text";
  input.inputMode = "numeric";
  input.maxLength = precision.includes("year") && !precision.includes("month") ? 4 : precision.includes("month") ? 7 : 10;
  input.placeholder = precision.includes("year") && !precision.includes("month") ? "YYYY" : precision.includes("month") ? "MM/YYYY" : "DD/MM/YYYY";
}

function configureTypeFields() {
  const type = elements.entryForm.elements.type.value;
  const endField = $("[data-date-part='end']", elements.entryForm);
  endField.hidden = type === "point";
  const ongoing = elements.entryForm.elements.ongoing.checked;
  $$('input:not([name="ongoing"]), select', endField).forEach((control) => { control.disabled = ongoing; });
}

function resetEntryForm() {
  elements.entryForm.reset();
  elements.entryForm.elements.id.value = "";
  elements.entryForm.elements.importance.value = "3";
  elements.entryForm.elements.startPrecision.value = "exact_day";
  elements.entryForm.elements.endPrecision.value = "exact_day";
  elements.formErrors.hidden = true;
  state.editingId = null;
  configureDateField("start"); configureDateField("end"); configureTypeFields();
}

function setDatePart(partName, part) {
  const form = elements.entryForm.elements;
  form[`${partName}Precision`].value = part?.precision || "exact_day";
  configureDateField(partName);
  form[`${partName}Date`].value = formatStoredDate(part?.date, part?.precision);
  form[`${partName}Earliest`].value = formatIsoDate(part?.earliest);
  form[`${partName}Latest`].value = formatIsoDate(part?.latest);
}

function setMultiple(select, values = []) {
  const wanted = new Set(values);
  [...select.options].forEach((option) => { option.selected = wanted.has(option.value); });
}

function openEntry(item = null, { duplicate = false } = {}) {
  resetEntryForm();
  if (item) {
    const form = elements.entryForm.elements;
    state.editingId = duplicate ? null : item.id;
    form.id.value = duplicate ? "" : item.id;
    form.title.value = duplicate ? `${item.title} (copy)` : item.title;
    form.type.value = item.type; form.categoryId.value = item.categoryId; form.subcategory.value = item.subcategory || ""; form.importance.value = item.importance;
    setDatePart("start", item.start); setDatePart("end", item.end);
    form.ongoing.checked = item.ongoing; form.location.value = item.location || ""; form.parentId.value = duplicate ? "" : (item.parentId || "");
    setMultiple(form.peopleIds, item.peopleIds); form.tagIds.value = (item.tagIds || []).join(", "); form.description.value = item.description || ""; form.notes.value = item.notes || "";
    setMultiple(form.sourceIds, item.sourceIds); form.private.checked = Boolean(item.private);
  }
  elements.entryHeading.textContent = duplicate ? "Duplicate entry" : item ? "Edit entry" : "Add entry";
  configureTypeFields();
  elements.entryDialog.showModal();
  requestAnimationFrame(() => elements.entryForm.elements.title.focus());
}

function readDatePart(partName) {
  const form = elements.entryForm.elements;
  return {
    date: parseDateInput(form[`${partName}Date`].value, form[`${partName}Precision`].value) || null,
    precision: form[`${partName}Precision`].value,
    earliest: parseDisplayDate(form[`${partName}Earliest`].value) || null,
    latest: parseDisplayDate(form[`${partName}Latest`].value) || null,
  };
}

function selectedValues(select) { return [...select.selectedOptions].map((option) => option.value); }
function commaValues(value) { return [...new Set(String(value || "").split(",").map((part) => part.trim()).filter(Boolean))]; }

function readEntryForm() {
  const form = elements.entryForm.elements;
  const type = form.type.value;
  const ongoing = type !== "point" && form.ongoing.checked;
  return {
    id: state.editingId || createId("item"), title: form.title.value.trim(), type, categoryId: form.categoryId.value,
    subcategory: form.subcategory.value.trim(), start: readDatePart("start"), end: type === "point" || ongoing ? null : readDatePart("end"), ongoing,
    importance: Number(form.importance.value), description: form.description.value.trim(), location: form.location.value.trim(),
    peopleIds: selectedValues(form.peopleIds), parentId: form.parentId.value || null, tagIds: commaValues(form.tagIds.value), sourceIds: selectedValues(form.sourceIds),
    notes: form.notes.value.trim(), private: form.private.checked,
  };
}

async function saveEntry(event) {
  event.preventDefault();
  const item = readEntryForm();
  const errors = validateTimelineItem(item);
  if (errors.length) {
    elements.formErrors.textContent = errors.join("\n"); elements.formErrors.hidden = false; return;
  }
  elements.formErrors.hidden = true;
  try {
    if (state.editingId) await updateTimelineItem(state.editingId, item);
    else await createTimelineItem(item);
    elements.entryDialog.close();
    await reloadTimeline({ keepWindow: true });
    showToast(state.editingId ? "Entry updated." : "Entry created.");
  } catch (error) {
    elements.formErrors.textContent = [error.message, ...(error.details || [])].join("\n"); elements.formErrors.hidden = false;
  }
}

function formatTimestamp(value) {
  return value ? formatIsoTimestamp(value) : "—";
}

function detailField(label, value, span = false) {
  return `<div class="timeline-detail-field${span ? " is-span-2" : ""}"><span>${escapeHtml(label)}</span><p>${escapeHtml(value || "—")}</p></div>`;
}

function openDetails(id) {
  const item = state.data.timelineItems.find((row) => row.id === id);
  if (!item) return;
  state.selectedId = item.id;
  elements.detailContent.innerHTML = `<div class="timeline-detail-grid"><h2>${escapeHtml(item.title)}</h2>
    ${detailField("Type", item.type)}${detailField("Category", categoryName(item.categoryId))}
    ${detailField("Start", formatDatePart(item.start))}${detailField("End", formatDatePart(item.end, { ongoing: item.ongoing }))}
    ${item.type !== "point" ? detailField("Duration", formatItemDuration(item).replace(/^Duration:\s*/, ""), true) : ""}
    ${detailField("Importance", `${item.importance}/5`)}${detailField("Location", item.location)}
    ${detailField("People", personNames(item.peopleIds).join(", "))}${detailField("Tags", (item.tagIds || []).join(", "))}
    ${detailField("Description", item.description, true)}${detailField("Notes", item.notes, true)}
    ${detailField("Updated", formatTimestamp(item.updatedAt), true)}</div>`;
  elements.detailDialog.showModal();
}

function renderActivitySettings() {
  const statuses = new Map((state.activity.sources || []).map((row) => [row.id, row]));
  elements.activitySources.innerHTML = ACTIVITY_SOURCES.map((source) => {
    const status = statuses.get(source.id);
    const stateLabel = status?.available === false ? ` · unavailable` : status ? ` · ${status.count} records` : "";
    return `<div class="timeline-source-row" data-activity-source="${escapeHtml(source.id)}">
      <span><i class="timeline-source-dot" style="--source-color:${escapeHtml(source.color)}"></i>${escapeHtml(source.label)}${source.private ? '<span class="timeline-private-badge">private</span>' : ""}<small>${escapeHtml(stateLabel)}</small></span>
      <label aria-label="Show ${escapeHtml(source.label)} on timeline"><input data-activity-purpose="timeline" type="checkbox"${state.activitySettings.sources[source.id].timeline ? " checked" : ""}></label>
      <label aria-label="Include ${escapeHtml(source.label)} in reports"><input data-activity-purpose="report" type="checkbox"${state.activitySettings.sources[source.id].report ? " checked" : ""}></label>
    </div>`;
  }).join("");
  elements.journalContent.value = state.activitySettings.journalContent;
}

function readActivitySettingsForm() {
  const next = normalizeActivitySettings(state.activitySettings);
  $$('[data-activity-source]', elements.activitySources).forEach((row) => {
    const source = row.dataset.activitySource;
    $$('[data-activity-purpose]', row).forEach((input) => { next.sources[source][input.dataset.activityPurpose] = input.checked; });
  });
  next.journalContent = elements.journalContent.value;
  return next;
}

function eventTime(value) {
  const match = /T(\d{2}):(\d{2})/.exec(String(value || ""));
  return match ? `${match[1]}:${match[2]}` : "";
}

function openActivityPeriodDetails(period) {
  if (!period) return;
  state.selectedActivityRange = { from: period.start, to: period.end };
  elements.dayHeading.textContent = period.granularity === "day" ? formatActivityDate(period.start) : period.label;
  const groups = new Map();
  for (const event of period.events || []) {
    if (!state.activitySettings.sources[event.source]?.timeline) continue;
    if (!groups.has(event.source)) groups.set(event.source, []);
    groups.get(event.source).push(event);
  }
  elements.dayContent.innerHTML = [...groups].map(([sourceId, events]) => {
    const source = sourceFor(sourceId);
    return `<section class="timeline-day-source"><h3><i class="timeline-source-dot" style="--source-color:${escapeHtml(source.color)}"></i>${escapeHtml(source.label)} <small>${events.length}</small></h3>${events.map((event) => `
      <article class="timeline-day-event"><header><strong>${escapeHtml(event.title)}</strong><span>${event.private ? '<span class="timeline-private-badge">private</span>' : ""} <small>${escapeHtml(eventTime(event.occurredAt))}</small></span></header>
      ${activityEventTextBlocks(event).map((text) => `<p>${escapeHtml(text)}</p>`).join("")}</article>`).join("")}</section>`;
  }).join("") || `<p class="timeline-dialog-intro">No enabled signals for this period.</p>`;
  elements.dayDialog.showModal();
}

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function setReportRange(preset) {
  const today = new Date();
  let from = new Date(today);
  if (preset === "month") from = new Date(today.getFullYear(), today.getMonth(), 1);
  else if (preset !== "today") from.setDate(from.getDate() - Math.max(0, Number(preset) - 1));
  elements.reportFrom.value = formatIsoDate(localIsoDate(from));
  elements.reportTo.value = formatIsoDate(localIsoDate(today));
}

function openReportDialog(from = "", to = from) {
  if (from) {
    elements.reportFrom.value = formatIsoDate(from);
    elements.reportTo.value = formatIsoDate(to || from);
  } else if (!elements.reportFrom.value || !elements.reportTo.value) {
    setReportRange("7");
  }
  state.reportData = null;
  elements.reportPreview.value = "";
  elements.reportStatus.textContent = "Ready to generate.";
  elements.reportDialog.showModal();
}

async function generateReport() {
  const from = parseDisplayDate(elements.reportFrom.value);
  const to = parseDisplayDate(elements.reportTo.value);
  if (!from || !to || from > to) {
    elements.reportStatus.textContent = "Enter a valid range in DD/MM/YYYY.";
    return;
  }
  elements.reportStatus.textContent = "Collecting dashboard data…";
  try {
    const sources = enabledSources(state.activitySettings, "report");
    const activity = await fetchTimelineActivity({ from, to, sources, journalContent: state.activitySettings.journalContent });
    const filtered = filterActivityForReport(activity, state.activitySettings);
    const timelineItems = timelineItemsInRange(state.data.timelineItems, from, to);
    state.reportData = { activity: filtered, timelineItems, from, to };
    elements.reportPreview.value = buildTextReport(filtered, timelineItems);
    const events = filtered.days.reduce((sum, day) => sum + day.events.length, 0);
    elements.reportStatus.textContent = `${filtered.days.length} days · ${events} records · ${timelineItems.length} timeline entries`;
  } catch (error) {
    elements.reportStatus.textContent = `Could not generate report: ${error.message}`;
  }
}

function reportFilename(extension) {
  return `great-timeline-report-${state.reportData.from}-to-${state.reportData.to}.${extension}`;
}

function downloadReport(format) {
  if (!state.reportData) { showToast("Generate the report first.", "error"); return; }
  const { activity, timelineItems } = state.reportData;
  if (format === "txt") download(reportFilename("txt"), buildTextReport(activity, timelineItems), "text/plain;charset=utf-8");
  if (format === "md") download(reportFilename("md"), buildTextReport(activity, timelineItems, { markdown: true }), "text/markdown;charset=utf-8");
  if (format === "csv") download(reportFilename("csv"), `\ufeff${activityToCsv(activity, timelineItems)}`, "text/csv;charset=utf-8");
  if (format === "json") download(reportFilename("json"), JSON.stringify({ schemaVersion: 1, range: { from: activity.from, to: activity.to }, activity, timelineItems }, null, 2), "application/json");
}

async function importHabitsFile() {
  const file = $("#timeline-habits-file").files?.[0];
  const report = $("#timeline-habits-report");
  if (!file) { report.textContent = "Choose a .db, .zip or .csv file."; return; }
  if (!/\.(db|zip|csv)$/i.test(file.name)) { report.textContent = "Unsupported file type."; return; }
  report.textContent = `Importing ${file.name}…`;
  try {
    const result = await importLoopHabits(file);
    report.textContent = `Import complete.\nFormat: ${result.format}\nHabits: ${result.summary?.habits ?? "—"}\nPoints: ${result.summary?.kept_points ?? "—"}\nConflicts: ${result.summary?.conflicts ?? 0}`;
    await reloadActivity();
    renderAll({ keepWindow: true });
  } catch (error) {
    report.textContent = `Import failed:\n${error.message}`;
  }
}

async function importEmotionsFile() {
  const file = $("#timeline-emotions-file").files?.[0];
  const report = $("#timeline-emotions-report");
  if (!file) { report.textContent = "Choose Check-in_data.csv."; return; }
  if (!/\.csv$/i.test(file.name)) { report.textContent = "How We Feel import requires a CSV file."; return; }
  if (file.size > 16 * 1024 * 1024) { report.textContent = "The CSV file is too large (maximum 16 MB)."; return; }
  report.textContent = `Importing ${file.name}…`;
  try {
    const result = await importHowWeFeel(file);
    report.textContent = `Import complete.\nNew: ${result.imported}\nUpdated: ${result.updated}\nAlready present: ${result.duplicates}\nSkipped: ${result.skipped}\nTotal check-ins: ${result.total}\nRange: ${formatActivityDate(result.range?.from)} – ${formatActivityDate(result.range?.to)}`;
    await reloadActivity();
    renderAll({ keepWindow: true });
  } catch (error) {
    report.textContent = `Import failed:\n${error.message}`;
  }
}

async function removeItem(id) {
  const item = state.data.timelineItems.find((row) => row.id === id);
  if (!item) return;
  const links = state.data.itemLinks.filter((row) => row.fromItemId === id || row.toItemId === id).length;
  const reflections = state.data.reflections.filter((row) => row.itemId === id).length;
  const children = state.data.timelineItems.filter((row) => row.parentId === id).length;
  if (!confirm(`Delete “${item.title}”?\n\nLinked records: ${links} links, ${reflections} reflections, ${children} child items. Links/reflections will be removed and child items detached.`)) return;
  try {
    await deleteTimelineItem(id);
    if (elements.detailDialog.open) elements.detailDialog.close();
    await reloadTimeline({ keepWindow: true });
    showToast("Entry deleted.");
  } catch (error) { showToast(error.message, "error"); }
}

function locateItem(id) {
  switchView("visual");
  const item = state.data.timelineItems.find((row) => row.id === id);
  const vis = item ? toVisItem(item, state.data.categories.find((row) => row.id === item.categoryId)) : null;
  if (!vis || !state.timeline) { showToast("This entry has no displayable date.", "error"); return; }
  state.timeline.focus(id, { animation: { duration: 350, easingFunction: "easeInOutQuad" }, zoom: true });
  state.timeline.setSelection(id);
}

function switchView(view) {
  const visual = view === "visual";
  elements.visualPanel.hidden = !visual; elements.listPanel.hidden = visual;
  elements.visualTab.classList.toggle("is-active", visual); elements.listTab.classList.toggle("is-active", !visual);
  elements.visualTab.setAttribute("aria-selected", String(visual)); elements.listTab.setAttribute("aria-selected", String(!visual));
  if (visual) requestAnimationFrame(() => state.timeline?.redraw());
}

function renderCategoryManager() {
  elements.categoryList.innerHTML = sortedCategories().map((category) => `<div class="timeline-category-row" style="--category-color:${escapeHtml(category.color)}"><span class="timeline-category-swatch"></span><span>${escapeHtml(category.name)}${category.archived ? " · archived" : ""}</span><button data-category-action="edit" data-id="${escapeHtml(category.id)}" type="button">Edit</button><button data-category-action="delete" data-id="${escapeHtml(category.id)}" type="button">Delete</button></div>`).join("");
}

function resetCategoryForm() {
  elements.categoryForm.reset();
  elements.categoryForm.elements.id.value = "";
  elements.categoryForm.elements.color.value = "#858585";
  elements.categoryForm.elements.order.value = String((Math.max(0, ...state.data.categories.map((row) => Number(row.order) || 0)) + 1));
  elements.categoryForm.elements.visible.checked = true;
  $("#timeline-category-form-title").textContent = "New category";
}

function editCategory(id) {
  const category = state.data.categories.find((row) => row.id === id);
  if (!category) return;
  const form = elements.categoryForm.elements;
  for (const key of ["id", "name", "color", "icon", "order"]) form[key].value = category[key] ?? "";
  form.subcategories.value = (category.subcategories || []).join(", "); form.visible.checked = category.visible !== false; form.archived.checked = Boolean(category.archived);
  $("#timeline-category-form-title").textContent = `Edit ${category.name}`;
}

async function saveCategory(event) {
  event.preventDefault();
  const form = elements.categoryForm.elements;
  const payload = { id: form.id.value || undefined, name: form.name.value.trim(), color: form.color.value, icon: form.icon.value.trim(), order: Number(form.order.value), subcategories: commaValues(form.subcategories.value), visible: form.visible.checked, archived: form.archived.checked };
  try {
    if (form.id.value) await updateTimelineCategory(form.id.value, payload);
    else await createTimelineCategory(payload);
    await reloadTimeline({ keepWindow: true }); resetCategoryForm(); renderCategoryManager(); showToast("Category saved.");
  } catch (error) { showToast(error.message, "error"); }
}

async function removeCategory(id) {
  const category = state.data.categories.find((row) => row.id === id);
  if (!category || !confirm(`Delete category “${category.name}”? Empty categories are removed immediately; categories in use must be reassigned.`)) return;
  try {
    await deleteTimelineCategory(id);
  } catch (error) {
    if (error.code !== "category_in_use") { showToast(error.message, "error"); return; }
    const choices = state.data.categories.filter((row) => row.id !== id).map((row) => `${row.id} (${row.name})`).join("\n");
    const moveTo = prompt(`This category is used by ${error.details.length} entries. Enter the destination category ID:\n\n${choices}`);
    if (!moveTo) return;
    try { await deleteTimelineCategory(id, moveTo.trim()); } catch (moveError) { showToast(moveError.message, "error"); return; }
  }
  await reloadTimeline({ keepWindow: true }); renderCategoryManager(); resetCategoryForm(); showToast("Category deleted.");
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function exportJson() {
  const payload = makeExportDocument(state.data);
  download(`great-timeline-${formatIsoDate(new Date().toISOString().slice(0, 10)).replaceAll("/", "-")}.json`, JSON.stringify(payload, null, 2), "application/json");
  showToast("JSON backup exported.");
}

function exportCsv() {
  download(`great-timeline-items-${formatIsoDate(new Date().toISOString().slice(0, 10)).replaceAll("/", "-")}.csv`, `\ufeff${itemsToCsv(state.data.timelineItems, state.data.categories, state.data.people)}`, "text/csv;charset=utf-8");
  showToast("CSV exported.");
}

function templateJson() {
  return JSON.stringify(makeImportTemplate(), null, 2);
}

async function copyImportTemplate() {
  const value = templateJson();
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const preview = $("#timeline-template-preview");
    preview.value = value;
    preview.focus();
    preview.select();
    document.execCommand("copy");
  }
  showToast("JSON template copied.");
}

function downloadImportTemplate() {
  download("great-timeline-import-template.json", templateJson(), "application/json");
  showToast("JSON template downloaded.");
}

async function validateImportFile() {
  state.importData = null; elements.importApply.disabled = true;
  const file = elements.importFile.files?.[0];
  if (!file) { elements.importReport.textContent = "Choose a JSON backup to validate it."; return; }
  try {
    const parsed = normalizeImportDocument(JSON.parse(await file.text()), {
      existingCategoryIds: elements.importMode.value === "merge"
        ? state.data.categories.map((category) => category.id)
        : [],
    });
    const preview = await importTimeline(parsed, { mode: elements.importMode.value, conflict: elements.importConflict.value, dryRun: true });
    state.importData = parsed;
    const report = preview.report;
    elements.importReport.textContent = `Validation passed.\nNew: ${report.new}\nChanged: ${report.changed}\nID conflicts: ${report.conflicts}\nSkipped: ${report.skipped}\n\nNo data has been written yet.`;
    elements.importApply.disabled = elements.importMode.value === "replace" && !elements.importConfirm.checked;
  } catch (error) {
    elements.importReport.textContent = `Validation failed:\n${error.message}${error.details?.length ? `\n${error.details.join("\n")}` : ""}`;
  }
}

async function applyImport() {
  if (!state.importData) return;
  if (elements.importMode.value === "replace" && !elements.importConfirm.checked) return;
  try {
    const response = await importTimeline(state.importData, { mode: elements.importMode.value, conflict: elements.importConflict.value });
    elements.importDialog.close(); await reloadTimeline({ keepWindow: false });
    showToast(`Import complete: ${response.report.new} new, ${response.report.changed} changed.`);
  } catch (error) { elements.importReport.textContent = `Import failed without partial write:\n${error.message}`; }
}

async function reloadActivity() {
  state.activity = await fetchTimelineActivity({ journalContent: state.activitySettings.journalContent });
  renderActivitySettings();
}

async function reloadTimeline(options = {}) {
  setStatus("Loading timeline…");
  try {
    const [timelineResult, activityResult] = await Promise.allSettled([
      fetchTimeline(),
      fetchTimelineActivity({ journalContent: state.activitySettings.journalContent }),
    ]);
    if (timelineResult.status === "rejected") throw timelineResult.reason;
    state.data = timelineResult.value;
    if (activityResult.status === "fulfilled") state.activity = activityResult.value;
    else showToast(`Daily signals unavailable: ${activityResult.reason?.message || "unknown error"}`, "error");
    populateReferenceControls(); applyStoredFilters(); renderAll(options);
    renderActivitySettings();
    const sourceErrors = (state.activity.sources || []).filter((source) => source.available === false).length;
    setStatus(sourceErrors ? `Timeline loaded · ${sourceErrors} activity source(s) unavailable` : "Timeline is up to date");
  } catch (error) {
    setStatus(`Could not load timeline: ${error.message}`, "error"); elements.loading.textContent = "Timeline API is unavailable. Start the local Python server and try again.";
    throw error;
  }
}

function bindEvents() {
  window.addEventListener("resize", () => {
    scheduleResponsiveTravelLabels();
    scheduleTimelineItemLabels();
    scheduleTimelineRowFit();
    const range = state.timeline?.getWindow();
    if (range) scheduleActivityGranularity(range.start, range.end);
  });
  $("#timeline-add").addEventListener("click", () => openEntry());
  $("#timeline-activity-open").addEventListener("click", () => { renderActivitySettings(); elements.activityDialog.showModal(); });
  $("#timeline-report-open").addEventListener("click", () => openReportDialog());
  $$('[data-action="add"]').forEach((button) => button.addEventListener("click", () => openEntry()));
  elements.entryForm.addEventListener("submit", saveEntry);
  elements.entryForm.elements.type.addEventListener("change", configureTypeFields);
  elements.entryForm.elements.ongoing.addEventListener("change", configureTypeFields);
  elements.entryForm.elements.startPrecision.addEventListener("change", () => configureDateField("start"));
  elements.entryForm.elements.endPrecision.addEventListener("change", () => configureDateField("end"));
  Object.values(filterElements).forEach((input) => input.addEventListener(input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input", () => { state.page = 1; renderAll(); }));
  $("#timeline-filter-reset").addEventListener("click", () => {
    Object.values(filterElements).forEach((input) => { if (input.type === "checkbox") input.checked = input.defaultChecked; else input.value = input.id === "timeline-density" ? "comfortable" : ""; });
    state.hiddenCategoryIds.clear(); state.shownCategoryIds.clear(); state.page = 1; renderAll();
  });
  elements.categoryToggles.addEventListener("click", (event) => {
    const sourceId = event.target.closest("[data-activity-toggle]")?.dataset.activityToggle;
    if (sourceId) {
      state.activitySettings.sources[sourceId].timeline = !state.activitySettings.sources[sourceId].timeline;
      saveActivitySettings();
      renderAll({ keepWindow: true });
      return;
    }
    const id = event.target.closest("[data-category-toggle]")?.dataset.categoryToggle;
    if (!id) return;
    const visible = effectiveCategories().find((category) => category.id === id)?.visible !== false;
    if (visible) {
      state.shownCategoryIds.delete(id);
      state.hiddenCategoryIds.add(id);
    } else {
      state.hiddenCategoryIds.delete(id);
      state.shownCategoryIds.add(id);
    }
    renderAll();
  });
  elements.visualTab.addEventListener("click", () => switchView("visual")); elements.listTab.addEventListener("click", () => switchView("list"));
  $("#timeline-zoom-in").addEventListener("click", () => state.timeline?.zoomIn(.35)); $("#timeline-zoom-out").addEventListener("click", () => state.timeline?.zoomOut(.35));
  $("#timeline-fit").addEventListener("click", () => state.timeline?.fit({ animation: true }));
  $("#timeline-today").addEventListener("click", () => state.timeline?.moveTo(new Date(), { animation: true }));
  $("#timeline-jump").addEventListener("click", () => {
    const value = parseDisplayDate($("#timeline-jump-date").value); if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !state.timeline) { showToast("Enter the date as DD/MM/YYYY.", "error"); return; }
    const center = new Date(`${value}T12:00:00`); const start = new Date(center); const end = new Date(center); start.setMonth(start.getMonth() - 6); end.setMonth(end.getMonth() + 6);
    state.timeline.setWindow(start, end, { animation: true });
  });
  elements.detailDialog.addEventListener("click", (event) => {
    const action = event.target.dataset.detailAction; if (!action) return;
    const item = state.data.timelineItems.find((row) => row.id === state.selectedId);
    if (action === "close") elements.detailDialog.close();
    if (action === "edit" && item) { elements.detailDialog.close(); openEntry(item); }
    if (action === "duplicate" && item) { elements.detailDialog.close(); openEntry(item, { duplicate: true }); }
    if (action === "delete" && item) removeItem(item.id);
  });
  elements.tableBody.addEventListener("click", (event) => {
    const action = event.target.dataset.rowAction; const id = event.target.closest("tr")?.dataset.id; if (!action || !id) return;
    const item = state.data.timelineItems.find((row) => row.id === id);
    if (action === "view") openDetails(id); if (action === "locate") locateItem(id); if (action === "edit") openEntry(item); if (action === "duplicate") openEntry(item, { duplicate: true }); if (action === "delete") removeItem(id);
  });
  $$("[data-sort]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.sort; state.sortDirection = state.sortKey === key && state.sortDirection === "asc" ? "desc" : "asc"; state.sortKey = key; state.page = 1; renderTable(); saveViewSettings();
  }));
  elements.pagePrev.addEventListener("click", () => { state.page -= 1; renderTable(); }); elements.pageNext.addEventListener("click", () => { state.page += 1; renderTable(); });
  $("#timeline-categories-open").addEventListener("click", () => { renderCategoryManager(); resetCategoryForm(); elements.categoryDialog.showModal(); });
  elements.categoryForm.addEventListener("submit", saveCategory); $("#timeline-category-reset").addEventListener("click", resetCategoryForm);
  elements.categoryDialog.addEventListener("click", (event) => { const action = event.target.dataset.categoryAction; const id = event.target.dataset.id; if (action === "close") elements.categoryDialog.close(); if (action === "edit") editCategory(id); if (action === "delete") removeCategory(id); });
  $("#timeline-export-json").addEventListener("click", exportJson); $("#timeline-export-csv").addEventListener("click", exportCsv);
  $("#timeline-import-open").addEventListener("click", () => { state.importData = null; elements.importFile.value = ""; elements.importReport.textContent = "Choose a JSON backup to validate it."; elements.importApply.disabled = true; elements.importConfirm.checked = false; $("#timeline-template-preview").value = templateJson(); elements.importDialog.showModal(); });
  $("#timeline-template-copy").addEventListener("click", copyImportTemplate);
  $("#timeline-template-download").addEventListener("click", downloadImportTemplate);
  elements.importDialog.addEventListener("click", (event) => { if (event.target.dataset.importAction === "close") elements.importDialog.close(); });
  elements.importFile.addEventListener("change", validateImportFile); elements.importConflict.addEventListener("change", validateImportFile);
  elements.importMode.addEventListener("change", () => { elements.importConfirmWrap.hidden = elements.importMode.value !== "replace"; elements.importConfirm.checked = false; validateImportFile(); });
  elements.importConfirm.addEventListener("change", () => { elements.importApply.disabled = !state.importData || (elements.importMode.value === "replace" && !elements.importConfirm.checked); });
  elements.importApply.addEventListener("click", applyImport);
  elements.activityDialog.addEventListener("click", async (event) => {
    const action = event.target.dataset.activityAction;
    if (action === "close") elements.activityDialog.close();
    if (action === "save") {
      const previousJournalMode = state.activitySettings.journalContent;
      state.activitySettings = readActivitySettingsForm();
      saveActivitySettings();
      elements.activityDialog.close();
      if (previousJournalMode !== state.activitySettings.journalContent) {
        try { await reloadActivity(); } catch (error) { showToast(error.message, "error"); }
      }
      renderAll({ keepWindow: true });
      showToast("Daily signal settings saved.");
    }
  });
  $("#timeline-habits-import").addEventListener("click", importHabitsFile);
  $("#timeline-emotions-import").addEventListener("click", importEmotionsFile);
  elements.dayDialog.addEventListener("click", (event) => {
    const action = event.target.dataset.dayAction;
    if (action === "close") elements.dayDialog.close();
    if (action === "report" && state.selectedActivityRange) {
      elements.dayDialog.close();
      openReportDialog(state.selectedActivityRange.from, state.selectedActivityRange.to);
    }
  });
  $$('[data-report-preset]').forEach((button) => button.addEventListener("click", () => setReportRange(button.dataset.reportPreset)));
  $("#timeline-report-generate").addEventListener("click", generateReport);
  elements.reportDialog.addEventListener("click", (event) => {
    const action = event.target.dataset.reportAction;
    if (action === "close") elements.reportDialog.close();
    if (action?.startsWith("download-")) downloadReport(action.slice("download-".length));
  });
}

async function init() {
  readViewSettings();
  $$('select[name="startPrecision"], select[name="endPrecision"], #timeline-filter-precision').forEach((select) => {
    select.innerHTML = select.id === "timeline-filter-precision" ? `<option value="">Any precision</option>${precisionOptions()}` : precisionOptions();
  });
  bindEvents();
  await reloadTimeline({ keepWindow: false });
  state.ongoingTimer = window.setInterval(syncOngoingItemsToNow, 30_000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) syncOngoingItemsToNow(); });
}

window.addEventListener("error", (event) => setStatus(`Timeline error: ${event.message}`, "error"));
init().catch((error) => console.error("Timeline initialization failed", error));
