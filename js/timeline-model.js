export const SCHEMA_VERSION = 1;
export const ITEM_TYPES = ["point", "period", "phase"];
export const DATE_PRECISIONS = [
  "exact_day",
  "month",
  "year",
  "approximate_day",
  "approximate_month",
  "approximate_year",
  "date_range",
  "unknown",
];

export const PRECISION_LABELS = {
  exact_day: "Exact day",
  month: "Month",
  year: "Year",
  approximate_day: "Approximate day",
  approximate_month: "Approximate month",
  approximate_year: "Approximate year",
  date_range: "Date range",
  unknown: "Unknown",
};

export function createId(prefix = "item") {
  const random = globalThis.crypto?.randomUUID?.().replaceAll("-", "")
    || `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${random}`;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function validDate(raw) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(raw || ""))) return false;
  const value = new Date(`${raw}T12:00:00`);
  return !Number.isNaN(value.getTime()) && value.toISOString().slice(0, 10) === raw;
}

function validMonth(raw) {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(String(raw || ""));
}

function validYear(raw) {
  return /^\d{4}$/.test(String(raw || ""));
}

export function formatIsoDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : String(value || "");
}

export function parseDisplayDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const match = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!match) return raw;
  const iso = `${match[3]}-${match[2]}-${match[1]}`;
  return validDate(iso) ? iso : raw;
}

export function formatStoredDate(value, precision = "exact_day") {
  const raw = String(value || "");
  if (["year", "approximate_year"].includes(precision)) return raw;
  if (["month", "approximate_month"].includes(precision)) {
    const match = raw.match(/^(\d{4})-(\d{2})$/);
    return match ? `${match[2]}/${match[1]}` : raw;
  }
  return formatIsoDate(raw);
}

export function parseDateInput(value, precision = "exact_day") {
  const raw = String(value || "").trim();
  if (["year", "approximate_year"].includes(precision)) return raw;
  if (["month", "approximate_month"].includes(precision)) {
    const match = raw.match(/^(\d{2})\/(\d{4})$/);
    return match ? `${match[2]}-${match[1]}` : raw;
  }
  return parseDisplayDate(raw);
}

export function formatIsoTimestamp(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value || "");
  const date = `${String(parsed.getDate()).padStart(2, "0")}/${String(parsed.getMonth() + 1).padStart(2, "0")}/${parsed.getFullYear()}`;
  const time = `${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}`;
  return `${date} ${time}`;
}

export function validateDatePart(part, field = "start", required = false) {
  const errors = [];
  const precision = part?.precision || "exact_day";
  if (!DATE_PRECISIONS.includes(precision)) return [`Invalid ${field} precision`];
  if (precision === "unknown") return errors;
  if (precision === "date_range") {
    if (!validDate(part?.earliest) || !validDate(part?.latest)) {
      errors.push(`${field} range needs valid earliest and latest dates`);
    } else if (part.latest < part.earliest) {
      errors.push(`${field} latest date cannot be before earliest date`);
    }
    return errors;
  }
  const value = String(part?.date || "");
  const valid = precision.includes("year")
    ? validYear(value)
    : precision.includes("month")
      ? validMonth(value)
      : validDate(value);
  if ((required || value) && !valid) errors.push(`${field} is invalid`);
  return errors;
}

function monthLastDay(year, month) {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

export function datePartBounds(part) {
  if (!part || part.precision === "unknown") return { start: null, end: null };
  if (part.precision === "date_range") {
    return { start: part.earliest || null, end: part.latest || null };
  }
  const raw = part.date;
  if (!raw) return { start: null, end: null };
  if (["year", "approximate_year"].includes(part.precision)) {
    return { start: `${raw}-01-01`, end: `${raw}-12-31` };
  }
  if (["month", "approximate_month"].includes(part.precision)) {
    const [year, month] = raw.split("-").map(Number);
    return { start: `${raw}-01`, end: `${raw}-${String(monthLastDay(year, month)).padStart(2, "0")}` };
  }
  return { start: raw, end: raw };
}

export function validateTimelineItem(item) {
  const errors = [];
  if (!String(item?.title || "").trim()) errors.push("Title is required");
  if (!ITEM_TYPES.includes(item?.type)) errors.push("Type is required");
  if (!String(item?.categoryId || "").trim()) errors.push("Category is required");
  errors.push(...validateDatePart(item?.start, "Start", true));
  if (item?.type === "point" && item?.end) errors.push("Point cannot have an end date");
  if (item?.ongoing && item?.end) errors.push("Ongoing entry cannot have an end date");
  if (item?.type !== "point" && !item?.ongoing) {
    if (!item?.end) errors.push("End is required unless the entry is ongoing");
    else {
      errors.push(...validateDatePart(item.end, "End", true));
      const start = datePartBounds(item.start).start;
      const end = datePartBounds(item.end).end;
      if (start && end && end < start) errors.push("End cannot be before start");
    }
  }
  if (item?.parentId && item.parentId === item.id) errors.push("An item cannot be its own parent");
  const importance = Number(item?.importance);
  if (!Number.isInteger(importance) || importance < 1 || importance > 5) {
    errors.push("Importance must be between 1 and 5");
  }
  return errors;
}

export function formatDatePart(part, { ongoing = false } = {}) {
  if (ongoing) return "Ongoing";
  if (!part || part.precision === "unknown") return "Unknown";
  if (part.precision === "date_range") return `${formatIsoDate(part.earliest)} – ${formatIsoDate(part.latest)} (possible range)`;
  const raw = formatStoredDate(part.date, part.precision) || "Unknown";
  if (part.precision.startsWith("approximate_")) return `c. ${raw}`;
  return raw;
}

export function isUncertain(item) {
  return [item?.start?.precision, item?.end?.precision].some((value) =>
    value === "unknown" || value === "date_range" || String(value || "").startsWith("approximate_")
  );
}

export function itemTimelineDates(item, now = new Date()) {
  const startBounds = datePartBounds(item.start);
  const endBounds = datePartBounds(item.end);
  const fallback = item.start?.precision === "unknown" ? null : startBounds.start;
  const start = startBounds.start || fallback;
  if (!start) return null;
  if (item.type === "point") return { start };
  const today = now.toISOString().slice(0, 10);
  const end = item.ongoing ? today : (endBounds.end || startBounds.end || start);
  return { start, end };
}

function utcDateFromIso(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : null;
}

function daysInUtcMonth(year, monthIndex) {
  return new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
}

function addUtcYearsClamped(value, years) {
  const year = value.getUTCFullYear() + years;
  const month = value.getUTCMonth();
  const day = Math.min(value.getUTCDate(), daysInUtcMonth(year, month));
  return new Date(Date.UTC(year, month, day));
}

function addUtcMonthsClamped(value, months) {
  const total = value.getUTCFullYear() * 12 + value.getUTCMonth() + months;
  const year = Math.floor(total / 12);
  const month = ((total % 12) + 12) % 12;
  const day = Math.min(value.getUTCDate(), daysInUtcMonth(year, month));
  return new Date(Date.UTC(year, month, day));
}

function durationPartsExact(startIso, endIso) {
  const start = utcDateFromIso(startIso);
  const end = utcDateFromIso(endIso);
  if (!start || !end || end < start) return null;
  let years = end.getUTCFullYear() - start.getUTCFullYear();
  let cursor = addUtcYearsClamped(start, years);
  if (cursor > end) {
    years -= 1;
    cursor = addUtcYearsClamped(start, years);
  }
  let months = (end.getUTCFullYear() - cursor.getUTCFullYear()) * 12 + end.getUTCMonth() - cursor.getUTCMonth();
  let monthCursor = addUtcMonthsClamped(cursor, months);
  if (monthCursor > end) {
    months -= 1;
    monthCursor = addUtcMonthsClamped(cursor, months);
  }
  const days = Math.floor((end.getTime() - monthCursor.getTime()) / 86400000);
  return { years, months, days };
}

function durationUnit(value, singular, plural) {
  return value ? `${value} ${value === 1 ? singular : plural}` : "";
}

export function formatTravelGapDuration(startIso, endIso) {
  const parts = durationPartsExact(startIso, endIso);
  if (!parts) return "";
  return [
    durationUnit(parts.years, "year", "years"),
    durationUnit(parts.months, "month", "months"),
    durationUnit(parts.days, "day", "days"),
  ].filter(Boolean).join(", ");
}

export function travelGapLabelVariants(duration) {
  const full = String(duration || "");
  const withoutDays = full.split(", ").filter((part) => !/^\d+ days?$/.test(part)).join(", ");
  return {
    full,
    medium: withoutDays,
    compact: withoutDays,
  };
}

const FLAG_SEQUENCE_PATTERN = /\p{Regional_Indicator}{2}|\u{1F3F4}[\u{E0020}-\u{E007E}]+\u{E007F}/gu;
const SUBDIVISION_FLAG_NAMES = { "GB-ENG": "England", "GB-SCT": "Scotland", "GB-WLS": "Wales" };

export function travelFlagsFromTitle(title) {
  return [...String(title || "").matchAll(FLAG_SEQUENCE_PATTERN)].map((match) => match[0]);
}

export function travelFlagRegionCode(flag) {
  const codePoints = [...flag].map((character) => character.codePointAt(0));
  if (codePoints[0] === 0x1f3f4) {
    const subdivision = codePoints.slice(1, -1).map((codePoint) => String.fromCharCode(codePoint - 0xe0000)).join("");
    return subdivision.startsWith("gb") ? `GB-${subdivision.slice(2).toUpperCase()}` : subdivision.toUpperCase();
  }
  return codePoints.map((codePoint) => String.fromCharCode(65 + codePoint - 0x1f1e6)).join("");
}

function countryNameForFlag(flag) {
  const regionCode = travelFlagRegionCode(flag);
  if (SUBDIVISION_FLAG_NAMES[regionCode]) return SUBDIVISION_FLAG_NAMES[regionCode];
  if (regionCode === "XK") return "Kosovo";
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(regionCode) || regionCode;
  } catch {
    return regionCode;
  }
}

export function travelItemLabelVariants(item, now = new Date()) {
  const title = String(item?.title || "").trim();
  const flags = travelFlagsFromTitle(title);
  const countries = flags.map(countryNameForFlag);
  const remainingTitle = title.replace(FLAG_SEQUENCE_PATTERN, "").trim();
  const descriptors = remainingTitle && !countries.some((country) => country.toLowerCase() === remainingTitle.toLowerCase())
    ? [remainingTitle, ...countries]
    : countries;
  const dates = itemTimelineDates(item, now);
  let duration = "";
  if (dates?.start && dates?.end) {
    const start = utcDateFromIso(dates.start);
    const end = utcDateFromIso(dates.end);
    if (start && end && end >= start) {
      const days = Math.max(1, Math.round((end.getTime() - start.getTime()) / 86400000));
      duration = `${days} ${days === 1 ? "day" : "days"}`;
    }
  }
  const flagText = flags.join("") || (!descriptors.length ? title : "");
  const details = [...descriptors, duration].filter(Boolean).join(", ");
  return {
    full: `${flagText}${flagText && details ? " " : ""}${details}`,
    medium: `${flagText}${flagText && duration ? " " : ""}${duration}`,
    compact: flagText,
  };
}

export function formatTravelItemLabel(item, now = new Date()) {
  return travelItemLabelVariants(item, now).full;
}

export function formatItemDuration(item, now = new Date()) {
  if (!item || item.type === "point") return "";
  const startPrecision = item.start?.precision;
  const endPrecision = item.ongoing ? "exact_day" : item.end?.precision;
  if ([startPrecision, endPrecision].includes("unknown")) return "Duration uncertain";
  if ([startPrecision, endPrecision].includes("date_range")) return "Duration varies with the possible date range";
  const dates = itemTimelineDates(item, now);
  if (!dates?.start || !dates?.end) return "";
  const approximate = [startPrecision, endPrecision].some((value) => String(value || "").startsWith("approximate_"));
  const hasYearPrecision = [startPrecision, endPrecision].some((value) => String(value || "").includes("year"));
  const hasMonthPrecision = [startPrecision, endPrecision].some((value) => String(value || "").includes("month"));
  let parts;
  if (hasYearPrecision) {
    const startYear = Number(String(dates.start).slice(0, 4));
    const endYear = Number(String(dates.end).slice(0, 4));
    parts = { years: Math.max(0, endYear - startYear), months: 0, days: 0 };
  } else if (hasMonthPrecision) {
    const [startYear, startMonth] = String(dates.start).slice(0, 7).split("-").map(Number);
    const [endYear, endMonth] = String(dates.end).slice(0, 7).split("-").map(Number);
    const totalMonths = Math.max(0, (endYear - startYear) * 12 + endMonth - startMonth);
    parts = { years: Math.floor(totalMonths / 12), months: totalMonths % 12, days: 0 };
  } else {
    parts = durationPartsExact(dates.start, dates.end);
  }
  if (!parts) return "";
  const value = [
    durationUnit(parts.years, "year", "years"),
    durationUnit(parts.months, "month", "months"),
    durationUnit(parts.days, "day", "days"),
  ].filter(Boolean).join(", ") || "0 days";
  return `Duration: ${approximate ? "about " : ""}${value}`;
}

export function toVisItem(item, category, now = new Date()) {
  const dates = itemTimelineDates(item, now);
  if (!dates) return null;
  const uncertain = isUncertain(item);
  const duration = formatItemDuration(item, now);
  const classes = [`timeline-vis-${item.type}`, uncertain ? "is-uncertain" : "", item.ongoing ? "is-ongoing" : ""]
    .filter(Boolean).join(" ");
  const visualEnd = item.type === "point" ? null : item.ongoing ? now : addOneIsoDay(dates.end);
  return {
    id: item.id,
    group: item.categoryId,
    content: escapeHtml(item.title),
    title: escapeHtml(`${item.title}\n${formatDatePart(item.start)}${item.type === "point" ? "" : ` — ${formatDatePart(item.end, { ongoing: item.ongoing })}`}${duration ? `\n${duration}` : ""}`),
    start: dates.start,
    ...(visualEnd ? { end: visualEnd } : {}),
    type: item.type === "point" ? "point" : "range",
    className: classes,
    style: `--item-color:${category?.color || "#858585"}`,
  };
}

export function toTravelGapVisItems(items, categoryId = "travel", now = new Date()) {
  const intervals = (items || []).filter((item) => item.categoryId === categoryId).map((item) => {
    const dates = itemTimelineDates(item, now);
    return dates?.start ? { item, start: dates.start, end: dates.end || dates.start } : null;
  }).filter(Boolean).sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end));
  if (intervals.length < 2) return [];

  const gaps = [];
  let previous = intervals[0];
  for (const current of intervals.slice(1)) {
    const gapStart = addOneIsoDay(previous.end);
    if (gapStart < current.start) {
      const duration = formatTravelGapDuration(gapStart, current.start);
      const labels = travelGapLabelVariants(duration);
      gaps.push({
        id: `travel-gap-${previous.item.id}-${current.item.id}`,
        group: categoryId,
        start: previous.end,
        end: current.start,
        type: "background",
        content: escapeHtml(labels.full),
        title: escapeHtml(`No travel: ${duration}`),
        className: "timeline-travel-gap",
        responsiveLabels: labels,
        selectable: false,
      });
    }
    if (current.end > previous.end) previous = current;
  }
  return gaps;
}

function addOneIsoDay(value) {
  const date = utcDateFromIso(value);
  if (!date) return value;
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

export function filterTimelineItems(items, filters = {}, categories = []) {
  const categoryMap = new Map(categories.map((category) => [category.id, category]));
  const search = String(filters.search || "").trim().toLowerCase();
  return (items || []).filter((item) => {
    const category = categoryMap.get(item.categoryId);
    if (category?.visible === false && !filters.includeHiddenCategories) return false;
    if (filters.categoryId && item.categoryId !== filters.categoryId) return false;
    if (filters.subcategory && item.subcategory !== filters.subcategory) return false;
    if (filters.type && item.type !== filters.type) return false;
    if (filters.personId && !(item.peopleIds || []).includes(filters.personId)) return false;
    if (filters.location && !String(item.location || "").toLowerCase().includes(filters.location.toLowerCase())) return false;
    if (filters.tag && !(item.tagIds || []).some((tag) => tag.toLowerCase().includes(filters.tag.toLowerCase()))) return false;
    if (filters.importance && Number(item.importance) !== Number(filters.importance)) return false;
    if (filters.status === "ongoing" && !item.ongoing) return false;
    if (filters.status === "completed" && item.ongoing) return false;
    if (filters.precision && ![item.start?.precision, item.end?.precision].includes(filters.precision)) return false;
    const bounds = itemTimelineDates(item);
    if (filters.from && bounds?.end && bounds.end < filters.from) return false;
    if (filters.to && bounds?.start && bounds.start > filters.to) return false;
    if (search) {
      const haystack = [item.title, item.description, item.notes, item.location, item.subcategory, ...(item.tagIds || [])]
        .join(" ").toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });
}

export function normalizeImportDocument(document, { existingCategoryIds = [] } = {}) {
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    throw new Error("Import must be a JSON object.");
  }
  if (Number(document.schemaVersion) !== SCHEMA_VERSION) {
    throw new Error(`Unsupported schemaVersion. Expected ${SCHEMA_VERSION}.`);
  }
  const entities = ["timelineItems", "people", "categories", "sources", "itemLinks", "reflections"];
  const copy = { schemaVersion: SCHEMA_VERSION };
  for (const entity of entities) {
    if (!Array.isArray(document[entity])) throw new Error(`${entity} must be an array.`);
    copy[entity] = structuredClone(document[entity]);
  }
  copy.timelineItems = copy.timelineItems.map((item) => {
    const normalized = structuredClone(item);
    for (const key of ["start", "end"]) {
      const part = normalized[key];
      if (!part) continue;
      part.date = parseDateInput(part.date, part.precision) || null;
      part.earliest = parseDisplayDate(part.earliest) || null;
      part.latest = parseDisplayDate(part.latest) || null;
    }
    return normalized;
  });
  const errors = copy.timelineItems.flatMap((item, index) =>
    validateTimelineItem(item).map((error) => `timelineItems[${index}]: ${error}`)
  );
  const categoryIds = new Set([
    ...existingCategoryIds,
    ...copy.categories.map((category) => category.id),
  ]);
  copy.timelineItems.forEach((item, index) => {
    if (!categoryIds.has(item.categoryId)) errors.push(`timelineItems[${index}]: unknown categoryId`);
  });
  if (errors.length) throw new Error(errors.slice(0, 20).join("\n"));
  return copy;
}

export function makeImportTemplate() {
  return {
    schemaVersion: SCHEMA_VERSION,
    exportedAt: new Date().toISOString(),
    _templateGuide: {
      instructions: [
        "Copy the required record templates into the corresponding top-level arrays.",
        "Replace every example-* ID consistently in references.",
        "Daily dates may use DD/MM/YYYY; month precision uses MM/YYYY; year precision uses YYYY.",
        "Remove _templateGuide before import if desired. It is ignored by the importer.",
      ],
      allowedValues: {
        itemType: ["point", "period", "phase"],
        datePrecision: [...DATE_PRECISIONS],
        importance: [1, 2, 3, 4, 5],
        linkType: ["part_of", "occurred_during", "overlaps", "followed_by", "related_to", "possibly_contributed_to", "contradicts"],
        boolean: [true, false],
        conflictModeInUi: ["merge", "replace"],
        conflictStrategyInUi: ["overwrite", "skip"],
      },
      dateExamples: {
        exact_day: { date: "10/05/2024", precision: "exact_day", earliest: null, latest: null },
        month: { date: "05/2024", precision: "month", earliest: null, latest: null },
        year: { date: "2024", precision: "year", earliest: null, latest: null },
        approximate_day: { date: "10/05/2024", precision: "approximate_day", earliest: null, latest: null },
        approximate_month: { date: "05/2024", precision: "approximate_month", earliest: null, latest: null },
        approximate_year: { date: "2024", precision: "approximate_year", earliest: null, latest: null },
        date_range: { date: null, precision: "date_range", earliest: "01/05/2024", latest: "31/05/2024" },
        unknown: { date: null, precision: "unknown", earliest: null, latest: null },
      },
      recordTemplates: {
        point: {
          id: "example-point-001", type: "point", categoryId: "example-category", subcategory: "milestone", title: "Example trip",
          start: { date: "10/05/2024", precision: "exact_day", earliest: null, latest: null }, end: null, ongoing: false, importance: 3,
          description: "", location: "", peopleIds: ["example-person"], parentId: null, tagIds: ["example-tag"], sourceIds: ["example-source"], notes: "", private: false,
          createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z",
        },
        period: {
          id: "example-period-001", type: "period", categoryId: "example-category", subcategory: "employment", title: "Example job",
          start: { date: "10/2022", precision: "month", earliest: null, latest: null }, end: { date: "02/2024", precision: "month", earliest: null, latest: null }, ongoing: false, importance: 4,
          description: "", location: "", peopleIds: [], parentId: null, tagIds: [], sourceIds: [], notes: "", private: false,
          createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z",
        },
        phase: {
          id: "example-phase-001", type: "phase", categoryId: "example-category", subcategory: "chapter", title: "Example life phase",
          start: { date: "2021", precision: "approximate_year", earliest: null, latest: null }, end: null, ongoing: true, importance: 3,
          description: "", location: "", peopleIds: [], parentId: null, tagIds: [], sourceIds: [], notes: "", private: false,
          createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z",
        },
        person: { id: "example-person", displayName: "Example person", relationshipType: "friend", notes: "", private: false, createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z" },
        category: { id: "example-category", name: "Example category", color: "#7f98b8", icon: "dot", order: 100, visible: true, archived: false, allowedTypes: ["point", "period", "phase"], subcategories: ["milestone", "employment", "chapter"], createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z" },
        source: { id: "example-source", sourceType: "document", title: "Example source", sourceDate: "10/05/2024", pathOrUrl: "https://example.com", notes: "", createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z" },
        itemLink: { id: "example-link", fromItemId: "example-point-001", toItemId: "example-period-001", linkType: "related_to", notes: "", createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z" },
        reflection: { id: "example-reflection", itemId: "example-point-001", reflectionDate: "22/07/2026", text: "Example reflection", tags: ["example-tag"], createdAt: "2026-07-22T12:00:00Z", updatedAt: "2026-07-22T12:00:00Z" },
      },
    },
    timelineItems: [],
    people: [],
    categories: [],
    sources: [],
    itemLinks: [],
    reflections: [],
  };
}

export function makeExportDocument(data, now = new Date()) {
  return {
    schemaVersion: SCHEMA_VERSION,
    exportedAt: now.toISOString(),
    timelineItems: structuredClone(data.timelineItems || []),
    people: structuredClone(data.people || []),
    categories: structuredClone(data.categories || []),
    sources: structuredClone(data.sources || []),
    itemLinks: structuredClone(data.itemLinks || []),
    reflections: structuredClone(data.reflections || []),
  };
}

function csvCell(value) {
  const text = Array.isArray(value) ? value.join("|") : String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

export function itemsToCsv(items, categories = [], people = []) {
  const categoryMap = new Map(categories.map((row) => [row.id, row.name]));
  const peopleMap = new Map(people.map((row) => [row.id, row.displayName]));
  const headers = ["id", "title", "type", "category", "subcategory", "start", "startPrecision", "end", "endPrecision", "ongoing", "importance", "location", "people", "tags", "description", "notes", "updatedAt"];
  const rows = (items || []).map((item) => [
    item.id, item.title, item.type, categoryMap.get(item.categoryId) || item.categoryId, item.subcategory,
    formatDatePart(item.start), item.start?.precision, formatDatePart(item.end, { ongoing: item.ongoing }), item.end?.precision,
    item.ongoing, item.importance, item.location, (item.peopleIds || []).map((id) => peopleMap.get(id) || id), item.tagIds,
    item.description, item.notes, formatIsoTimestamp(item.updatedAt),
  ]);
  return [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
}
