const DAY_MS = 24 * 60 * 60 * 1000;
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function parseISODate(value) {
  const match = String(value || "").match(ISO_DATE_RE);
  if (!match) return null;

  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  const day = Number(match[3]);
  const date = new Date(year, monthIndex, day);

  if (
    !Number.isFinite(date.getTime()) ||
    date.getFullYear() !== year ||
    date.getMonth() !== monthIndex ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
}

export function startOfDay(date = new Date()) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function toISODate(date = new Date()) {
  const normalized = startOfDay(date);
  const year = normalized.getFullYear();
  const month = String(normalized.getMonth() + 1).padStart(2, "0");
  const day = String(normalized.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function daysBetween(fromDate, toDate) {
  const from = startOfDay(fromDate);
  const to = startOfDay(toDate);
  return Math.round((to - from) / DAY_MS);
}

export function getWeekStart(date = new Date()) {
  const normalized = startOfDay(date);
  const day = normalized.getDay();
  const offset = day === 0 ? -6 : 1 - day;
  normalized.setDate(normalized.getDate() + offset);
  return normalized;
}

export function addDays(date, days) {
  const next = startOfDay(date);
  next.setDate(next.getDate() + Number(days || 0));
  return next;
}

export function isSameWeek(date, referenceDate = new Date()) {
  const weekStart = getWeekStart(referenceDate);
  const weekEnd = addDays(weekStart, 6);
  const current = startOfDay(date);
  return current >= weekStart && current <= weekEnd;
}

export function isWeekend(date) {
  const day = date.getDay();
  return day === 0 || day === 6;
}

export function formatWeekday(date, locale = "pl-PL") {
  return date.toLocaleDateString(locale, { weekday: "long" });
}

export function formatDateLong(date, locale = "pl-PL") {
  return date.toLocaleDateString(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function formatDateShort(date, locale = "pl-PL") {
  return date.toLocaleDateString(locale, {
    day: "2-digit",
    month: "2-digit",
  });
}

export function getDateMeta(date, referenceDate = new Date(), locale = "pl-PL") {
  const daysUntil = daysBetween(referenceDate, date);
  return {
    daysUntil,
    weekday: formatWeekday(date, locale),
    isToday: daysUntil === 0,
    isTomorrow: daysUntil === 1,
    isThisWeek: isSameWeek(date, referenceDate),
    isWithin30Days: daysUntil >= 0 && daysUntil <= 30,
    isWeekend: isWeekend(date),
  };
}

export function formatDaysUntil(daysUntil) {
  if (daysUntil === 0) return "dzisiaj";
  if (daysUntil === 1) return "jutro";
  if (daysUntil < 0) {
    const days = Math.abs(daysUntil);
    return `${days} ${pluralizeDays(days)} temu`;
  }
  return `za ${daysUntil} ${pluralizeDays(daysUntil)}`;
}

function pluralizeDays(value) {
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (value === 1) return "dzień";
  if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) {
    return "dni";
  }
  return "dni";
}
