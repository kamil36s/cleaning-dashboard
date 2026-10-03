function previousLocalDayStart(dayStartMs) {
  const date = new Date(dayStartMs);
  date.setDate(date.getDate() - 1);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function isConfirmedDay(values) {
  return Array.isArray(values) && values.some((value) => Number(value) === 2);
}

export function countSobrietyDays(dayValuesByStart, todayStartMs) {
  if (!(dayValuesByStart instanceof Map) || !Number.isFinite(todayStartMs)) return 0;

  let dayPointer = isConfirmedDay(dayValuesByStart.get(todayStartMs))
    ? todayStartMs
    : previousLocalDayStart(todayStartMs);
  let streak = 0;

  while (isConfirmedDay(dayValuesByStart.get(dayPointer))) {
    streak += 1;
    dayPointer = previousLocalDayStart(dayPointer);
  }

  return streak;
}

function previousDateKey(key) {
  const timestamp = Date.parse(`${key}T00:00:00Z`);
  if (!Number.isFinite(timestamp)) return "";
  return new Date(timestamp - 86_400_000).toISOString().slice(0, 10);
}

function isConfirmedValue(value) {
  return Number(value) > 0;
}

export function resolveSobrietyDateState(valuesByDate, todayKey) {
  if (!(valuesByDate instanceof Map) || !/^\d{4}-\d{2}-\d{2}$/.test(String(todayKey || ""))) {
    return { days: 0, confirmedToday: false };
  }

  const confirmedToday = isConfirmedValue(valuesByDate.get(todayKey));
  let dayPointer = confirmedToday ? todayKey : previousDateKey(todayKey);
  let days = 0;

  while (dayPointer && isConfirmedValue(valuesByDate.get(dayPointer))) {
    days += 1;
    dayPointer = previousDateKey(dayPointer);
  }

  return { days, confirmedToday };
}

function entryDateKey(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 10);
}

export function resolveDontDrinkHabitState(habits, todayKey, pendingMutations = []) {
  const source = Array.isArray(habits) ? habits : [];
  const habit = source.find((item) => String(item?.name || "").trim().toLowerCase() === "don't drink");
  if (!habit) return null;

  const valuesByDate = new Map();
  if (habit.entries instanceof Map) {
    habit.entries.forEach((value, key) => {
      const normalizedKey = entryDateKey(key);
      if (normalizedKey) valuesByDate.set(normalizedKey, value);
    });
  } else {
    (Array.isArray(habit.points) ? habit.points : []).forEach((point) => {
      if (!Array.isArray(point) || point.length < 2) return;
      const key = entryDateKey(point[0]);
      const value = Number(point[1]);
      if (key && Number.isFinite(value)) valuesByDate.set(key, value);
    });
  }

  const habitName = String(habit.name || "").trim().toLowerCase();
  (Array.isArray(pendingMutations) ? pendingMutations : [])
    .filter((mutation) => String(mutation?.habitId) === String(habit.id)
      || String(mutation?.habitName || "").trim().toLowerCase() === habitName)
    .forEach((mutation) => {
      const key = entryDateKey(mutation.date);
      if (key) valuesByDate.set(key, mutation.value);
    });

  return resolveSobrietyDateState(valuesByDate, todayKey);
}

export function isDontDrinkConfirmedToday(habit) {
  if (!habit || habit.doneToday !== true) return false;
  return Number(habit.todayValue) === 2 || String(habit.todayDisplay || "").toUpperCase() === "DONE";
}
