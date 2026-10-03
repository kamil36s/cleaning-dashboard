import { getDateMeta, parseISODate } from "./events-date.js";

const MATCH_CALENDARS = new Set(["besiktas", "cracovia", "hearts", "liverpool", "poland"]);

export const EVENT_TYPES = [
  "public_holiday",
  "birthday",
  "short_day",
  "personal_event",
  "trip",
  "concert",
  "match",
  "deadline",
  "payday",
  "task",
  "custom",
];

export const EVENT_COUNTDOWN_CATEGORIES = [
  "album_release",
  "match",
  "hockey_match",
  "stadium_match",
  "concert",
  "new_episode",
  "phases_of_the_moon",
];

export const EVENT_COUNTDOWN_CATEGORY_LABELS = {
  album_release: "Album release",
  match: "Match",
  hockey_match: "Mecz hokejowy",
  stadium_match: "Match (going to the stadium)",
  concert: "Concert",
  new_episode: "New episode",
  phases_of_the_moon: "Phases of the Moon",
};

const AUTOMATIC_FOOTBALL_COUNTDOWN_TITLES = [
  "wieczysta krakow",
  "liverpool",
  "wisla krakow",
  "lech poznan",
  "jagiellonia",
];

export const TYPE_LABELS = {
  public_holiday: "dzień wolny",
  birthday: "urodziny",
  short_day: "krótki dzień",
  personal_event: "wydarzenie",
  trip: "wyjazd",
  concert: "koncert",
  match: "mecz",
  deadline: "deadline",
  payday: "wypłata",
  task: "task",
  custom: "inne",
};

export function normalizeLocalEvent(raw, options = {}) {
  if (!raw || typeof raw !== "object") return null;
  const date = parseISODate(raw.date);
  if (!date) return null;

  const rawType = EVENT_TYPES.includes(raw.type) ? raw.type : "custom";
  const type = isMatchCalendarEvent(raw) && rawType === "personal_event" ? "match" : rawType;
  const title = String(raw.title || "").trim();
  if (!title) return null;

  return applyAutomaticCountdownCategory({
    id: String(raw.id || `${raw.source || "local"}-${raw.date}-${title}`),
    date: raw.date,
    title,
    type,
    isDayOff: Boolean(raw.isDayOff),
    isShortDay: Boolean(raw.isShortDay),
    source: String(raw.source || options.source || "local"),
    startTime: normalizeTime(raw.startTime),
    endTime: normalizeTime(raw.endTime),
    notes: optionalString(raw.notes),
    actionNeeded: optionalString(raw.actionNeeded),
    actionStatus: optionalString(raw.actionStatus),
    countdown: Boolean(raw.countdown),
    category: normalizeCountdownCategory(raw.category) || inferCountdownCategory(raw, type, title),
    coverImage: optionalString(raw.coverImage),
    external: raw.external && typeof raw.external === "object" ? { ...raw.external } : undefined,
  });
}

export function applyAutomaticCountdownCategory(event) {
  if (!event || typeof event !== "object") return event;
  const title = normalizeCalendarName(event.title);
  let category = "";
  if (title.includes("full moon")) {
    const timeMatch = String(event.title || "").trim().match(/\s([01]?\d|2[0-3]):([0-5]\d)\s*$/);
    const normalizedMoon = {
      ...event,
      title: "Full Moon",
      startTime: event.startTime || (timeMatch ? `${timeMatch[1].padStart(2, "0")}:${timeMatch[2]}` : undefined),
    };
    return event.countdown && event.category
      ? normalizedMoon
      : { ...normalizedMoon, countdown: true, category: "phases_of_the_moon" };
  } else if (event.countdown && event.category) {
    return event;
  } else if (title.includes("montreal canadiens")) {
    const montrealIndex = title.indexOf("montreal canadiens");
    const separatorIndex = title.search(/\s(?:@|vs?\.?)\s/);
    if (separatorIndex < 0 || montrealIndex < separatorIndex) category = "hockey_match";
  } else if (AUTOMATIC_FOOTBALL_COUNTDOWN_TITLES.some((team) => title.includes(team))) {
    category = "match";
  }
  return category ? { ...event, countdown: true, category } : event;
}

export function normalizeGoogleCalendarEvent(raw, options = {}) {
  if (!raw || typeof raw !== "object") return null;
  const start = raw.start?.date || raw.start?.dateTime || raw.date;
  const isoDate = extractLocalDate(start);
  const rawType = options.type || raw.extendedProperties?.private?.dashboardType;
  const isTask = isGoogleTaskEvent(raw);

  return normalizeLocalEvent(
    {
      id: raw.id,
      date: isoDate,
      title: raw.summary || raw.title,
      type: isTask ? "task" : rawType || "personal_event",
      isDayOff: raw.extendedProperties?.private?.isDayOff === "true",
      isShortDay: raw.extendedProperties?.private?.isShortDay === "true",
      source: options.source || "google_calendar",
      startTime: raw.startTime || extractTime(raw.start?.dateTime),
      endTime: raw.endTime || extractTime(raw.end?.dateTime),
      notes: raw.description,
      actionNeeded: raw.extendedProperties?.private?.actionNeeded,
      actionStatus: raw.extendedProperties?.private?.actionStatus,
      countdown: Boolean(raw.countdown) || raw.extendedProperties?.private?.dashboardCountdown === "true",
      category: raw.category || raw.extendedProperties?.private?.dashboardCategory,
      coverImage: raw.coverImage,
    },
    { source: options.source || "google_calendar" },
  );
}

function isGoogleTaskEvent(raw) {
  const text = `${raw?.description || ""} ${raw?.htmlLink || ""}`.toLowerCase();
  return text.includes("tasks.google.com/task/")
    || text.includes("changes made to the title, description, or attachments will not be saved");
}

function isMatchCalendarEvent(raw) {
  const calendarName = normalizeCalendarName(raw?.external?.calendarSummary);
  return MATCH_CALENDARS.has(calendarName);
}

function normalizeCalendarName(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[łŁ]/g, "l")
    .trim()
    .toLowerCase();
}

export function normalizeIcsEvent(raw, options = {}) {
  if (!raw || typeof raw !== "object") return null;
  const isoDate = String(raw.date || raw.startDate || raw.start || "").slice(0, 10);

  return normalizeLocalEvent(
    {
      id: raw.uid || raw.id,
      date: isoDate,
      title: raw.summary || raw.title,
      type: options.type || raw.type || "custom",
      isDayOff: Boolean(raw.isDayOff),
      isShortDay: Boolean(raw.isShortDay),
      source: options.source || "ics",
      notes: raw.description || raw.notes,
    },
    { source: options.source || "ics" },
  );
}

export function normalizeEvents(rawEvents, options = {}) {
  const source = options.source || "local";
  const normalizer =
    source === "google_calendar"
      ? normalizeGoogleCalendarEvent
      : source === "ics"
        ? normalizeIcsEvent
        : normalizeLocalEvent;

  return (Array.isArray(rawEvents) ? rawEvents : [])
    .map((event) => normalizer(event, options))
    .filter(Boolean);
}

export function enrichEvents(events, options = {}) {
  const today = options.today || new Date();
  const locale = options.locale || "pl-PL";

  return events
    .map((event) => {
      const dateObj = parseISODate(event.date);
      if (!dateObj) return null;
      return {
        ...event,
        dateObj,
        startDateTime: getEventStartDateTime(event, dateObj),
        meta: getDateMeta(dateObj, today, locale),
      };
    })
    .filter(Boolean)
    .sort(compareEventsChronologically);
}

export function getVisibleEvents(events, options = {}) {
  const showPastEvents = Boolean(options.showPastEvents);
  const referenceDate = options.referenceDate || options.today || new Date();
  return events.filter((event) => showPastEvents || isEventUpcoming(event, referenceDate));
}

function optionalString(value) {
  const text = String(value || "").trim();
  return text || undefined;
}

export function normalizeCountdownCategory(value) {
  const category = String(value || "").trim().toLowerCase();
  return /^[a-z0-9][a-z0-9_-]{0,63}$/.test(category) ? category : undefined;
}

function inferCountdownCategory(raw, type, title) {
  if (type === "concert") return "concert";
  if (type === "match") return "match";

  const normalizedTitle = String(title || "").trim().toLowerCase();
  if (/\balbum release\b|\bpremiera albumu\b/.test(normalizedTitle)) return "album_release";
  if (/\bnew episode\b|\bnowy odcinek\b|\bodcinek\b|\bs\d{1,2}e\d{1,2}\b/i.test(normalizedTitle)) {
    return "new_episode";
  }
  if (/^⚽/.test(String(title || "").trim())) return "match";

  const calendarName = normalizeCalendarName(raw?.external?.calendarSummary);
  if (calendarName === "entertainment/social") return "concert";
  return undefined;
}

function normalizeTime(value) {
  const match = String(value || "").trim().match(/^(\d{1,2}):(\d{2})/);
  if (!match) return undefined;
  return `${match[1].padStart(2, "0")}:${match[2]}`;
}

function extractTime(value) {
  const date = parseDateTime(value);
  if (date) {
    return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }
  return normalizeTime(value);
}

function extractLocalDate(value) {
  const date = parseDateTime(value);
  if (!date) return String(value || "").slice(0, 10);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseDateTime(value) {
  const text = String(value || "");
  if (!text.includes("T")) return null;
  const date = new Date(text);
  return Number.isFinite(date.getTime()) ? date : null;
}

export function compareEventsChronologically(a, b, locale = "pl") {
  const dateDiff = a.dateObj - b.dateObj;
  if (dateDiff) return dateDiff;

  const timeDiff = timeSortValue(a) - timeSortValue(b);
  if (timeDiff) return timeDiff;

  return String(a.title || "").localeCompare(String(b.title || ""), locale);
}

function timeSortValue(event) {
  const time = normalizeTime(event?.startTime);
  if (!time) return 24 * 60;
  const [hours, minutes] = time.split(":").map(Number);
  return hours * 60 + minutes;
}

export function getEventStartDateTime(event, dateObj = event?.dateObj) {
  if (!dateObj) return null;
  const time = normalizeTime(event?.startTime);
  if (!time) return new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
  const [hours, minutes] = time.split(":").map(Number);
  return new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate(), hours, minutes);
}

export function isEventUpcoming(event, referenceDate = new Date()) {
  if (!event?.dateObj) return false;
  if (event.startTime) {
    const start = event.startDateTime || getEventStartDateTime(event);
    return Boolean(start && start.getTime() > referenceDate.getTime());
  }
  return event.meta?.daysUntil >= 0;
}
