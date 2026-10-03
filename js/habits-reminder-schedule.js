const DAY_MS = 86_400_000;

export const DEFAULT_REMINDER_CONFIG = Object.freeze({
  enabled: false,
  scheduleType: "daily",
  selectedWeekdays: [],
  intervalDays: 2,
  intervalAnchorDate: null,
  timeGroupIds: [],
  customTimes: [],
  snoozeMinutes: 10,
  skipIfCompleted: true,
  completionPolicy: "day",
});

export function localDateKey(input = new Date()) {
  const date = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function shiftLocalDateKey(key, days) {
  const [year, month, day] = String(key).split("-").map(Number);
  if (![year, month, day].every(Number.isFinite)) return "";
  const shifted = new Date(Date.UTC(year, month - 1, day + Number(days || 0)));
  return shifted.toISOString().slice(0, 10);
}

export function localDayDifference(fromKey, toKey) {
  const from = Date.parse(`${fromKey}T00:00:00Z`);
  const to = Date.parse(`${toKey}T00:00:00Z`);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return NaN;
  return Math.round((to - from) / DAY_MS);
}

export function weekdayIndex(key) {
  const timestamp = Date.parse(`${key}T12:00:00Z`);
  if (!Number.isFinite(timestamp)) return -1;
  return (new Date(timestamp).getUTCDay() + 6) % 7;
}

export function normalizeReminderConfig(raw = {}) {
  return {
    ...DEFAULT_REMINDER_CONFIG,
    ...(raw && typeof raw === "object" ? raw : {}),
    selectedWeekdays: [...new Set((raw?.selectedWeekdays || []).map(Number))]
      .filter((day) => Number.isInteger(day) && day >= 0 && day <= 6)
      .sort((a, b) => a - b),
    timeGroupIds: [...new Set((raw?.timeGroupIds || []).map(String).filter(Boolean))],
    customTimes: [...new Set((raw?.customTimes || []).map(String).filter(Boolean))].sort(),
  };
}

export function validateReminderConfig(raw, groups = []) {
  const config = normalizeReminderConfig(raw);
  const errors = [];
  if (!["daily", "weekdays", "interval_days", "custom"].includes(config.scheduleType)) {
    errors.push("Invalid schedule type.");
  }
  if (["weekdays", "custom"].includes(config.scheduleType) && !config.selectedWeekdays.length) {
    errors.push("Select at least one weekday.");
  }
  if (config.scheduleType === "interval_days") {
    if (!Number.isInteger(Number(config.intervalDays)) || Number(config.intervalDays) < 1 || Number(config.intervalDays) > 365) {
      errors.push("The repeat interval must be between 1 and 365 days.");
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(config.intervalAnchorDate || "")) errors.push("Choose a start date.");
  }
  const groupIds = new Set((groups || []).map((group) => String(group.id)));
  if (config.timeGroupIds.some((id) => !groupIds.has(id))) errors.push("A selected time group no longer exists.");
  if (config.customTimes.some((time) => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time))) errors.push("Custom times must use HH:MM.");
  if (config.enabled && !config.timeGroupIds.length && !config.customTimes.length) errors.push("Choose at least one reminder time.");
  if (![10, 15, 30, 60].includes(Number(config.snoozeMinutes))) errors.push("Choose a supported snooze duration.");
  return errors;
}

export function isScheduledOnDate(item, date) {
  const config = normalizeReminderConfig(item?.reminderConfig || item);
  if (!config.enabled) return false;
  const key = typeof date === "string" ? date : localDateKey(date);
  if (!key) return false;
  if (config.scheduleType === "daily") return true;
  if (config.scheduleType === "weekdays" || config.scheduleType === "custom") {
    return config.selectedWeekdays.includes(weekdayIndex(key));
  }
  if (config.scheduleType === "interval_days") {
    const difference = localDayDifference(config.intervalAnchorDate, key);
    return difference >= 0 && difference % Number(config.intervalDays) === 0;
  }
  return false;
}

export function occurrenceDateTime(localDate, localTime) {
  const [year, month, day] = String(localDate).split("-").map(Number);
  const [hour, minute] = String(localTime).split(":").map(Number);
  return new Date(year, month - 1, day, hour, minute, 0, 0);
}

export function getReminderOccurrences(item, date, groups = []) {
  const localDate = typeof date === "string" ? date : localDateKey(date);
  const config = normalizeReminderConfig(item?.reminderConfig || item);
  if (!isScheduledOnDate({ reminderConfig: config }, localDate)) return [];
  const groupById = new Map((groups || []).map((group) => [String(group.id), group]));
  const candidates = [];
  config.timeGroupIds.forEach((id) => {
    const group = groupById.get(id);
    if (!group || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(group.localTime || "")) return;
    candidates.push({
      sourceKey: `group:${id}`,
      groupId: id,
      label: group.name,
      localTime: group.localTime,
    });
  });
  config.customTimes.forEach((localTime) => {
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(localTime)) return;
    candidates.push({ sourceKey: `custom:${localTime}`, groupId: null, label: "Custom", localTime });
  });
  const seenTimes = new Set();
  return candidates
    .sort((a, b) => a.localTime.localeCompare(b.localTime) || a.sourceKey.localeCompare(b.sourceKey))
    .filter((candidate) => {
      if (seenTimes.has(candidate.localTime)) return false;
      seenTimes.add(candidate.localTime);
      return true;
    })
    .map((candidate) => ({
      ...candidate,
      habitId: String(item.id),
      habitName: item.name,
      localDate,
      scheduledAt: occurrenceDateTime(localDate, candidate.localTime),
      occurrenceKey: `${item.id}|${localDate}|${candidate.sourceKey}`,
    }));
}

export function getNextReminder(item, now = new Date(), groups = [], maxDays = 370) {
  const start = localDateKey(now);
  for (let offset = 0; offset <= maxDays; offset += 1) {
    const date = shiftLocalDateKey(start, offset);
    const occurrence = getReminderOccurrences(item, date, groups)
      .find((candidate) => candidate.scheduledAt.getTime() >= now.getTime());
    if (occurrence) return occurrence;
  }
  return null;
}

export function scheduleLabel(configInput) {
  const config = normalizeReminderConfig(configInput);
  if (config.scheduleType === "daily") return "Every day";
  if (config.scheduleType === "interval_days") return `Every ${config.intervalDays} days`;
  const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return config.selectedWeekdays.map((day) => labels[day]).join(", ") || "No days selected";
}
