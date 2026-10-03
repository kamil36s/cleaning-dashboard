const DAY_MS = 86_400_000;

export const HABITS_APP_STORAGE_KEY = "habits.app.preview-mutations.v1";

export const LOOP_HABIT_PROFILES = [
  { name: "Don't drink", color: "#1976d2", category: "lifestyle", question: "Did you have an alcohol-free day?", frequency: [1, 1] },
  { name: "Don't smoke cigarettes", color: "#aaaaaa", category: "lifestyle", question: "Did you have a smoke-free day?", frequency: [1, 1] },
  { name: "Don't eat chips", color: "#8d6e63", category: "lifestyle", question: "Did you eat chips today?", frequency: [1, 1] },
  { name: "Don't smoke weed", color: "#c0ca33", category: "lifestyle", question: "Did you have a weed-free day today?", frequency: [1, 1] },
  { name: "Meditation", color: "#29b6f6", category: "lifestyle", question: "Did you meditate today?", frequency: [5, 7] },
  { name: "Push-ups", color: "#5c6bc0", category: "lifestyle", target: 10, frequency: [1, 1] },
  { name: "Squats", color: "#5c6bc0", category: "lifestyle", target: 15, frequency: [1, 1] },
  { name: "Pregabalin", color: "#eeeeee", category: "meds", target: 1, frequency: [1, 1] },
  { name: "Concerta/Atenza", color: "#26a69a", category: "meds", target: 1, frequency: [1, 1] },
  { name: "Creatine", color: "#90a4ae", category: "supplements", target: 0, frequency: [1, 1] },
  { name: "Bupropion", color: "#29b6f6", category: "meds", target: 0, frequency: [1, 1] },
  { name: "Duloxetine", color: "#ab47bc", category: "meds", target: 0, frequency: [1, 1] },
  { name: "Biotyna/B complex", color: "#ef5350", category: "supplements", frequency: [1, 1] },
  { name: "B12", color: "#29b6f6", category: "supplements", target: 0, frequency: [1, 1] },
  { name: "Vitamin C", color: "#ffa726", category: "supplements", target: 0, frequency: [1, 1] },
  { name: "Vitamin D", color: "#ffee58", category: "supplements", question: "Did you take vitamin D today?", frequency: [1, 1] },
  { name: "Zinc", color: "#bcaaa4", category: "supplements", frequency: [1, 2] },
  { name: "Magnesium", color: "#eeeeee", category: "supplements", frequency: [1, 1] },
  { name: "Omega 3", color: "#ec407a", category: "supplements", frequency: [1, 1] },
  { name: "Melatonin", color: "#29b6f6", category: "meds", target: 1, frequency: [1, 1] },
  { name: "Medikinet IR", color: "#ab47bc", category: "meds", target: 1, frequency: [1, 1] },
  { name: "Medikinet CR", color: "#c0ca33", category: "meds", target: 1, frequency: [1, 1] },
  { name: "L-Theanine", color: "#42a5f5", category: "supplements", frequency: [1, 1] },
  { name: "Heviran morning", color: "#ab47bc", category: "meds", frequency: [1, 1] },
  { name: "Heviran evening", color: "#ab47bc", category: "meds", frequency: [1, 1] },
  { name: "Collagen", color: "#26c6da", category: "supplements", frequency: [1, 1] },
  { name: "Lion's Mane", color: "#bcaaa4", category: "supplements", frequency: [1, 1] },
  { name: "Ashwaganda", color: "#bcaaa4", category: "supplements", frequency: [1, 1] },
];

const profileByName = new Map(LOOP_HABIT_PROFILES.map((profile, position) => [
  profile.name.toLocaleLowerCase("en"),
  { ...profile, position },
]));

export function dateKey(input) {
  if (typeof input === "string" && /^\d{4}-\d{2}-\d{2}$/.test(input)) return input;
  const date = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

export function shiftDateKey(key, deltaDays) {
  const timestamp = Date.parse(`${key}T00:00:00Z`);
  return dateKey(timestamp + deltaDays * DAY_MS);
}

export function recentDateKeys(endDate, count = 7) {
  const end = dateKey(endDate);
  const safeCount = Math.max(1, Math.floor(Number(count) || 1));
  return Array.from({ length: safeCount }, (_, index) => shiftDateKey(end, index - safeCount + 1));
}

export function normalizeHabitDataset(raw = {}) {
  const sourceHabits = Array.isArray(raw?.habits) ? raw.habits : [];
  return sourceHabits
    .map((habit, sourcePosition) => {
      const name = String(habit?.name || "").trim();
      if (!name) return null;
      const profile = profileByName.get(name.toLocaleLowerCase("en")) || {};
      const type = Number(habit?.type) === 1 ? "numeric" : "binary";
      const entries = new Map();
      (Array.isArray(habit?.points) ? habit.points : []).forEach((point) => {
        if (!Array.isArray(point) || point.length < 2) return;
        const key = dateKey(point[0]);
        const value = Number(point[1]);
        if (!key || !Number.isFinite(value)) return;
        entries.set(key, type === "numeric" ? value / 1000 : value);
      });
      return {
        id: String(habit?.id ?? name),
        name,
        type,
        unit: String(habit?.unit || "").replace(/ÎĽ/g, "μ"),
        color: profile.color || "#60a5fa",
        category: profile.category || "other",
        question: profile.question || "",
        frequency: profile.frequency || [1, 1],
        target: Number.isFinite(profile.target) ? profile.target : null,
        position: Number.isFinite(profile.position) ? profile.position : 1000 + sourcePosition,
        entries,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
}

export function mutationKey(habitId, key) {
  return `${habitId}::${dateKey(key)}`;
}

export function reorderHabits(source, draggedId, targetId, placeAfter = false) {
  const habits = Array.isArray(source) ? [...source] : [];
  const draggedIndex = habits.findIndex((habit) => String(habit.id) === String(draggedId));
  if (draggedIndex < 0 || String(draggedId) === String(targetId)) return habits;
  const [dragged] = habits.splice(draggedIndex, 1);
  const targetIndex = habits.findIndex((habit) => String(habit.id) === String(targetId));
  if (targetIndex < 0) return [...source];
  habits.splice(targetIndex + (placeAfter ? 1 : 0), 0, dragged);
  return habits.map((habit, position) => ({ ...habit, position }));
}

export function readPreviewMutations(storage = globalThis.localStorage) {
  if (!storage) return [];
  try {
    const parsed = JSON.parse(storage.getItem(HABITS_APP_STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item?.habitId && dateKey(item?.date)) : [];
  } catch {
    return [];
  }
}

export function writePreviewMutations(mutations, storage = globalThis.localStorage) {
  if (!storage) return;
  storage.setItem(HABITS_APP_STORAGE_KEY, JSON.stringify(Array.isArray(mutations) ? mutations : []));
}

export function upsertPreviewMutation(mutations, next) {
  const list = Array.isArray(mutations) ? [...mutations] : [];
  const key = mutationKey(next.habitId, next.date);
  const index = list.findIndex((item) => mutationKey(item.habitId, item.date) === key);
  const mutation = {
    mutationId: String(next.mutationId || globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`),
    habitId: String(next.habitId),
    habitName: String(next.habitName || ""),
    date: dateKey(next.date),
    value: next.value === null ? null : Number(next.value),
    takenAt: next.takenAt ?? (Number(next.value) > 0 ? new Date().toISOString() : null),
    updatedAt: next.updatedAt || new Date().toISOString(),
    baseRevision: next.baseRevision ?? null,
  };
  if (index >= 0) list[index] = mutation;
  else list.push(mutation);
  return list;
}

export function resolvedValue(habit, key, mutations = []) {
  const match = [...mutations].reverse().find(
    (item) => mutationKey(item.habitId, item.date) === mutationKey(habit.id, key),
  );
  if (match) return match.value;
  return habit.entries.get(dateKey(key)) ?? null;
}

export function isHabitComplete(habit, value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return false;
  if (habit.type === "binary") return Number(value) > 0;
  const target = Number.isFinite(habit.target) ? habit.target : 0;
  return Number(value) > 0 && Number(value) >= target;
}

export function summarizeHabitsForDashboard(habits, day, mutations = []) {
  const today = dateKey(day);
  const active = (Array.isArray(habits) ? habits : []).filter((habit) => !habit.archived);
  const items = active.map((habit) => {
    const value = resolvedValue(habit, today, mutations);
    const recorded = value !== null && value !== undefined;
    const doneToday = isHabitComplete(habit, value);
    const todayDisplay = habit.type === 'numeric' && recorded
      ? `${Number(value).toLocaleString('pl-PL')} ${habit.unit || ''}`.trim()
      : doneToday ? 'DONE' : 'MISSED';
    return { name: habit.name, doneToday, todayDisplay, recorded,
      recordedZero: habit.type === 'numeric' && recorded && Number(value) === 0 };
  });
  const doneToday = items.filter((item) => item.doneToday).length;
  return { today, habits: items,
    stats: { doneToday, missedToday: items.length - doneToday, totalActive: items.length } };
}

export function habitMetrics(habit, endDate, mutations = [], rangeDays = 30) {
  const keys = recentDateKeys(endDate, Math.max(1, rangeDays));
  const completed = keys.filter((key) => isHabitComplete(habit, resolvedValue(habit, key, mutations))).length;
  let currentStreak = 0;
  for (let index = keys.length - 1; index >= 0; index -= 1) {
    if (!isHabitComplete(habit, resolvedValue(habit, keys[index], mutations))) break;
    currentStreak += 1;
  }
  let bestStreak = 0;
  let running = 0;
  keys.forEach((key) => {
    if (isHabitComplete(habit, resolvedValue(habit, key, mutations))) {
      running += 1;
      bestStreak = Math.max(bestStreak, running);
    } else {
      running = 0;
    }
  });
  return {
    completed,
    total: keys.length,
    score: keys.length ? Math.round((completed / keys.length) * 100) : 0,
    currentStreak,
    bestStreak,
  };
}

export function habitPeriodSummary(habit, endDate, mutations = [], rangeDays = 30) {
  const keys = recentDateKeys(endDate, Math.max(1, rangeDays));
  const values = keys
    .map((key) => resolvedValue(habit, key, mutations))
    .filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value)))
    .map(Number);
  const completed = values.filter((value) => isHabitComplete(habit, value)).length;

  return {
    days: keys.length,
    recorded: values.length,
    completed,
    percent: keys.length ? Math.round((completed / keys.length) * 100) : 0,
    average: values.length
      ? values.reduce((sum, value) => sum + value, 0) / values.length
      : null,
  };
}

export function habitLifetimeSummary(habit, endDate, mutations = []) {
  const end = dateKey(endDate);
  const candidateKeys = new Set([
    ...habit.entries.keys(),
    ...mutations
      .filter((item) => String(item?.habitId) === String(habit.id))
      .map((item) => dateKey(item?.date))
      .filter(Boolean),
  ]);
  const firstDate = [...candidateKeys]
    .filter((key) => key <= end && resolvedValue(habit, key, mutations) !== null)
    .sort()[0] || "";

  if (!firstDate || !end) {
    return { startDate: "", elapsedDays: 0, days: 0, recorded: 0, completed: 0, percent: 0, average: null };
  }

  const days = Math.max(1, Math.floor((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${firstDate}T00:00:00Z`)) / DAY_MS) + 1);
  return {
    startDate: firstDate,
    elapsedDays: days - 1,
    ...habitPeriodSummary(habit, end, mutations, days),
  };
}

export function latestDatasetDate(habits, fallback = new Date()) {
  let latest = "";
  (Array.isArray(habits) ? habits : []).forEach((habit) => {
    habit.entries.forEach((_, key) => {
      if (key > latest) latest = key;
    });
  });
  return latest || dateKey(fallback);
}
