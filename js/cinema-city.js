import { toISODate } from "./events-date.js";

export const CINEMA_CITY_CONFIG = Object.freeze({
  calendarName: "Cinema City Galeria Kazimierz",
  autoTag: "AUTO_CINEMA_CITY",
  membershipExpiresOn: "2026-09-19",
  statusThresholds: {
    frequent: 8,
    ok: 4,
  },
  eventHints: [
    "event",
    "pokaz specjalny",
    "maraton",
    "premiera",
    "przedpremiera",
    "spotkanie",
    "q&a",
    "q & a",
    "opera",
    "koncert",
  ],
});

export function getCinemaCityMembershipState(now = new Date(), config = CINEMA_CITY_CONFIG) {
  const current = now instanceof Date ? now : new Date(now);
  const [year, month, day] = String(config.membershipExpiresOn || "")
    .split("-")
    .map(Number);
  const inactiveAt = new Date(year, month - 1, day + 1);

  if (!Number.isFinite(current.getTime()) || !Number.isFinite(inactiveAt.getTime())) {
    return { active: false, remainingMs: 0, days: 0, hours: 0, minutes: 0, seconds: 0 };
  }

  const remainingMs = Math.max(0, inactiveAt.getTime() - current.getTime());
  const totalSeconds = Math.floor(remainingMs / 1000);
  return {
    active: remainingMs > 0,
    inactiveAt,
    remainingMs,
    days: Math.floor(totalSeconds / 86400),
    hours: Math.floor((totalSeconds % 86400) / 3600),
    minutes: Math.floor((totalSeconds % 3600) / 60),
    seconds: totalSeconds % 60,
  };
}

export function isEventWithinCinemaCityMembership(event, config = CINEMA_CITY_CONFIG) {
  if (!isConfiguredCalendarEvent(event, config)) return true;
  const eventDate = String(event?.date || "").slice(0, 10);
  const expiresOn = String(config.membershipExpiresOn || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(eventDate) || !/^\d{4}-\d{2}-\d{2}$/.test(expiresOn)) return true;
  return eventDate <= expiresOn;
}

export function buildCinemaCitySummary(rawEvents = [], stats = null, options = {}) {
  const config = { ...CINEMA_CITY_CONFIG, ...(options.config || {}) };
  const now = options.now instanceof Date ? options.now : new Date();
  const events = (Array.isArray(rawEvents) ? rawEvents : [])
    .map((event) => normalizeCinemaEvent(event, { now, config }))
    .filter(Boolean)
    .sort((a, b) => a.start - b.start || a.title.localeCompare(b.title, "pl"));

  const todayKey = toISODate(now);
  const todayScreenings = events
    .filter((event) => event.date === todayKey);

  const groups = groupFutureEventsByMovie(events, config);
  const movies = groups
    .map((movie) => ({
      ...movie,
      status: getMovieStatus(movie, config),
    }))
    .sort(compareMovieGroups);

  return {
    todayScreenings,
    movies,
    stats: normalizeCinemaMonthlyStats(stats),
    monthLabel: formatMonthName(now),
  };
}

export function normalizeCinemaEvent(raw, options = {}) {
  if (!raw || typeof raw !== "object") return null;
  const config = options.config || CINEMA_CITY_CONFIG;
  const notes = String(raw.notes || raw.description || "");
  if (!notes.includes(config.autoTag)) return null;
  if (!isConfiguredCalendarEvent(raw, config)) return null;

  const title = parseDescriptionField(notes, "Film") || cleanTitle(raw.title);
  if (!title) return null;

  const start = getEventStartDateTime(raw);
  const now = options.now instanceof Date ? options.now : new Date();
  if (!start || start.getTime() <= now.getTime()) return null;

  const end = getEventEndDateTime(raw, start);
  const version = parseDescriptionField(notes, "Wersja seansu");
  const filmAttributes = parseDescriptionField(notes, "Film attributes");
  const eventAttributes = parseDescriptionField(notes, "Event attributes");

  return {
    id: String(raw.id || `${raw.date}-${raw.startTime || ""}-${title}`),
    title,
    normalizedTitle: normalizeMovieTitle(title),
    date: toISODate(start),
    start,
    end,
    startTime: formatTime(start),
    endTime: end ? formatTime(end) : "",
    version,
    filmAttributes,
    eventAttributes,
    eventLike: isEventLike({ title, version, filmAttributes, eventAttributes }, config),
  };
}

export function parseDescriptionField(description, fieldName) {
  const escaped = String(fieldName || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = String(description || "").match(new RegExp(`^[ \\t]*${escaped}:[ \\t]*(.*?)[ \\t]*$`, "im"));
  return match ? match[1].trim() : "";
}

export function normalizeMovieTitle(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("pl-PL");
}

export function getMovieStatus(movie, config = CINEMA_CITY_CONFIG) {
  if (movie.eventLike || movie.count === 1) return "event";
  if (movie.count >= config.statusThresholds.frequent) return "często grany";
  if (movie.count >= config.statusThresholds.ok) return "OK";
  return "końcówka";
}

export function formatAvailableScreeningCount(count) {
  const value = Number(count) || 0;
  if (value === 1) return "1 dostępny seans";
  const mod10 = value % 10;
  const mod100 = value % 100;
  const noun = mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)
    ? "dostępne seanse"
    : "dostępnych seansów";
  return `${value} ${noun}`;
}

export function formatCinemaStats(stats, monthLabel) {
  const normalized = normalizeCinemaMonthlyStats(stats);
  if (!Number.isFinite(normalized.watchedCount) && !Number.isFinite(normalized.pricePerFilm) && normalized.error) {
    const note = isCinemaStatsAuthError(normalized.error)
      ? "połącz Google ponownie"
      : "błąd statystyk";
    return `statystyki kina: ${note}`;
  }
  const watched = Number.isFinite(normalized.watchedCount)
    ? `${normalized.watchedCount} ${formatWatchedFilmPlural(normalized.watchedCount)}`
    : "— filmów obejrzanych";
  const price = Number.isFinite(normalized.pricePerFilm)
    ? `średnia ${normalized.pricePerFilm.toLocaleString("pl-PL", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })} zł / film`
    : "średnia — zł / film";
  return `${watched} | ${price}`;
}

export function normalizeCinemaMonthlyStats(stats) {
  if (!stats || typeof stats !== "object") {
    return { configured: false, watchedCount: null, pricePerFilm: null };
  }
  const watchedCount = parseNumber(stats.watchedCount ?? stats.watched ?? stats.count);
  const pricePerFilm = parseNumber(stats.pricePerFilm ?? stats.price ?? stats.ticketPrice);
  return {
    configured: stats.configured !== false,
    watchedCount,
    pricePerFilm,
    error: typeof stats.error === "string" ? stats.error.trim() : "",
    periodLabel: typeof stats.periodLabel === "string" ? stats.periodLabel.trim() : "",
    updatedAt: stats.updatedAt || null,
  };
}

export function isCinemaStatsAuthError(error) {
  return /invalid_grant|expired|revoked|unauthori[sz]ed|401/i.test(String(error || ""));
}

function groupFutureEventsByMovie(events, config) {
  const byTitle = new Map();
  events.forEach((event) => {
    const key = event.normalizedTitle;
    const current = byTitle.get(key) || {
      title: event.title,
      normalizedTitle: key,
      count: 0,
      screenings: [],
      lastScreening: event,
      eventLike: false,
    };
    current.count += 1;
    current.screenings.push(event);
    current.eventLike = current.eventLike || event.eventLike;
    if (!current.lastScreening || event.start > current.lastScreening.start) {
      current.lastScreening = event;
    }
    byTitle.set(key, current);
  });

  return Array.from(byTitle.values()).map((movie) => ({
    ...movie,
    eventLike: movie.eventLike || (movie.count === 1 && movie.screenings.some((event) => event.eventLike)),
    status: getMovieStatus(movie, config),
  }));
}

function compareMovieGroups(a, b) {
  const countDiff = b.count - a.count;
  if (countDiff) return countDiff;
  const lastDiff = a.lastScreening.start - b.lastScreening.start;
  if (lastDiff) return lastDiff;
  return a.title.localeCompare(b.title, "pl");
}

function isConfiguredCalendarEvent(raw, config) {
  const external = raw.external || {};
  const labels = [
    external.calendarSummary,
    external.displayCalendarSummary,
    external.calendarName,
    external.calendarId,
    external.displayCalendarId,
  ]
    .filter(Boolean)
    .map((value) => normalizeCalendarLabel(value));
  return labels.includes(normalizeCalendarLabel(config.calendarName));
}

function normalizeCalendarLabel(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("pl-PL");
}

function cleanTitle(value) {
  return String(value || "")
    .replace(/^[^\p{L}\p{N}]+/u, "")
    .replace(/\s+\[[^\]]+\]$/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function getEventStartDateTime(event) {
  if (event.start instanceof Date && Number.isFinite(event.start.getTime())) return event.start;
  const date = String(event.date || "").slice(0, 10);
  const time = normalizeTime(event.startTime);
  if (!date || !time) return null;
  const parsed = new Date(`${date}T${time}:00`);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

function getEventEndDateTime(event, start) {
  const date = String(event.date || "").slice(0, 10);
  const time = normalizeTime(event.endTime);
  if (!date || !time) return null;
  const parsed = new Date(`${date}T${time}:00`);
  if (!Number.isFinite(parsed.getTime())) return null;
  if (parsed < start) parsed.setDate(parsed.getDate() + 1);
  return parsed;
}

function normalizeTime(value) {
  const match = String(value || "").trim().match(/^(\d{1,2}):(\d{2})/);
  if (!match) return "";
  return `${match[1].padStart(2, "0")}:${match[2]}`;
}

function formatTime(date) {
  return date.toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isEventLike(parts, config) {
  const text = [
    parts.title,
    parts.version,
    parts.filmAttributes,
    parts.eventAttributes,
  ]
    .filter(Boolean)
    .join(" ")
    .normalize("NFKC")
    .toLocaleLowerCase("pl-PL");
  return config.eventHints.some((hint) => text.includes(hint));
}

function formatMonthName(date) {
  const months = [
    "styczniu",
    "lutym",
    "marcu",
    "kwietniu",
    "maju",
    "czerwcu",
    "lipcu",
    "sierpniu",
    "wrześniu",
    "październiku",
    "listopadzie",
    "grudniu",
  ];
  return months[date.getMonth()] || date.toLocaleDateString("pl-PL", { month: "long" });
}

function formatWatchedFilmPlural(count) {
  return count === 1 ? "film obejrzany" : "filmów obejrzanych";
}

function parseNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(String(value).replace(/\s+/g, "").replace(",", "."));
  return Number.isFinite(number) ? number : null;
}
