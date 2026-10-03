import { normalizeHabitDataset } from "./habits-app-model.js";

const DEVICE_KEY = "habits.app.dashboard-device-id.v1";

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

export async function fetchHabitsSnapshot(fetchImpl = globalThis.fetch) {
  return readJson(await fetchImpl("/api/habits/snapshot", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  }));
}

export async function pollHabitChanges(cursor, fetchImpl = globalThis.fetch) {
  return readJson(await fetchImpl("/api/habits/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      schemaVersion: 1,
      deviceId: dashboardDeviceId(),
      lastPulledCursor: cursor || null,
      mutations: [],
      limit: 500,
    }),
  }));
}

export function snapshotToHabits(snapshot) {
  const entriesByHabit = new Map();
  (snapshot?.entries || []).forEach((entry) => {
    if (!entriesByHabit.has(entry.habitId)) entriesByHabit.set(entry.habitId, []);
    const value = entry.valueMilli ?? (entry.status === "DONE" ? 2 : entry.status === "MISSED" ? 0 : null);
    if (value !== null) entriesByHabit.get(entry.habitId).push([`${entry.date}T00:00:00Z`, value]);
  });
  const normalized = normalizeHabitDataset({
    habits: (snapshot?.habits || []).map((habit) => ({
      id: habit.id,
      name: habit.name,
      type: habit.type === "NUMERIC" ? 1 : 0,
      unit: habit.unit || "",
      points: entriesByHabit.get(habit.id) || [],
    })),
  });
  const sourceById = new Map((snapshot?.habits || []).map((habit) => [habit.id, habit]));
  const revisionsByHabit = new Map();
  (snapshot?.entries || []).forEach((entry) => {
    if (!revisionsByHabit.has(entry.habitId)) revisionsByHabit.set(entry.habitId, new Map());
    revisionsByHabit.get(entry.habitId).set(entry.date, entry.revision);
  });
  normalized.forEach((habit) => {
    const source = sourceById.get(habit.id);
    habit.color = source?.colorHex || habit.color;
    habit.sourceName = habit.name;
    habit.name = { "Biotyna/B complex": "Vitamin B Complex", "Vitamin D": "Vitamin D3 + K2", "Omega 3": "Omega-3" }[habit.name] || habit.name;
    habit.category = { HABIT: "lifestyle", MEDICATION: "meds", SUPPLEMENT: "supplements" }[source?.category] || "other";
    habit.question = source?.question || habit.question;
    habit.frequency = [source?.frequencyNumerator || 1, source?.frequencyDenominator || 1];
    habit.target = source?.targetValueMilli == null ? habit.target : source.targetValueMilli / 1000;
    habit.position = source?.position ?? habit.position;
    habit.archived = Boolean(source?.archived || source?.deletedAt);
    habit.revision = source?.revision ?? 0;
    habit.reminderConfig = source?.reminderConfig || { enabled: false };
    habit.entryRevisions = revisionsByHabit.get(habit.id) || new Map();
    habit.entryTakenAt = new Map((snapshot?.entries || [])
      .filter((entry) => entry.habitId === habit.id && entry.takenAt)
      .map((entry) => [entry.date, entry.takenAt]));
  });
  return normalized.sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
}

export async function createHabit(payload, cursor, fetchImpl = globalThis.fetch) {
  const mutationId = globalThis.crypto?.randomUUID?.() || `dashboard-new-habit-${Date.now()}-${Math.random()}`;
  const entityId = globalThis.crypto?.randomUUID?.() || `dashboard-habit-${Date.now()}-${Math.random()}`;
  const response = await readJson(await fetchImpl("/api/habits/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      schemaVersion: 1,
      deviceId: dashboardDeviceId(),
      lastPulledCursor: cursor || null,
      mutations: [{
        mutationId,
        entityType: "HABIT",
        entityId,
        operation: "UPSERT",
        baseRevision: null,
        clientUpdatedAt: new Date().toISOString(),
        payload,
      }],
      limit: 500,
    }),
  }));
  if (!(response.acknowledgedMutationIds || []).includes(mutationId)) {
    throw new Error((response.conflicts || []).length ? "Nawyk nie został zapisany z powodu konfliktu. Odśwież dane i spróbuj ponownie." : "Serwer nie potwierdził dodania.");
  }
  return entityId;
}


export async function setHabitArchived(habit, archived, cursor, fetchImpl = globalThis.fetch) {
  const mutationId = globalThis.crypto?.randomUUID?.() || `dashboard-habit-${Date.now()}-${Math.random()}`;
  return readJson(await fetchImpl("/api/habits/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      schemaVersion: 1,
      deviceId: dashboardDeviceId(),
      lastPulledCursor: cursor || null,
      mutations: [{
        mutationId,
        entityType: "HABIT",
        entityId: habit.id,
        operation: "UPSERT",
        baseRevision: habit.revision ?? null,
        clientUpdatedAt: new Date().toISOString(),
        payload: {
          name: habit.name,
          archived: Boolean(archived),
        },
      }],
      limit: 500,
    }),
  }));
}

export async function setHabitPositions(habits, cursor, fetchImpl = globalThis.fetch) {
  const updatedAt = new Date().toISOString();
  const mutations = (Array.isArray(habits) ? habits : []).map((habit) => ({
    mutationId: globalThis.crypto?.randomUUID?.() || `dashboard-order-${Date.now()}-${Math.random()}`,
    entityType: "HABIT",
    entityId: habit.id,
    operation: "UPSERT",
    baseRevision: habit.revision ?? null,
    clientUpdatedAt: updatedAt,
    payload: {
      name: habit.name,
      position: habit.position,
    },
  }));
  return readJson(await fetchImpl("/api/habits/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      schemaVersion: 1,
      deviceId: dashboardDeviceId(),
      lastPulledCursor: cursor || null,
      mutations,
      limit: 500,
    }),
  }));
}

export async function fetchSupplementSnapshot(date, fetchImpl = globalThis.fetch) {
  const suffix = date ? `?date=${encodeURIComponent(date)}` : "";
  return readJson(await fetchImpl(`/api/habits/supplements${suffix}`, { cache: "no-store" }));
}

async function postSupplement(path, payload, fetchImpl = globalThis.fetch) {
  return readJson(await fetchImpl(`/api/habits/supplements/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  }));
}

export const saveSupplementSlots = (payload, fetchImpl) => postSupplement("slots", payload, fetchImpl);
export const saveSupplementRegimen = (payload, fetchImpl) => postSupplement("regimen", payload, fetchImpl);
export const changeSupplementProduct = (payload, fetchImpl) => postSupplement("product", payload, fetchImpl);
export const claimSupplementSlot = (payload, fetchImpl) => postSupplement("claim", payload, fetchImpl);

export async function setHabitReminderConfig(habit, reminderConfig, cursor, fetchImpl = globalThis.fetch) {
  const mutationId = globalThis.crypto?.randomUUID?.() || `dashboard-reminder-${Date.now()}-${Math.random()}`;
  return readJson(await fetchImpl("/api/habits/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      schemaVersion: 1,
      deviceId: dashboardDeviceId(),
      lastPulledCursor: cursor || null,
      mutations: [{
        mutationId,
        entityType: "HABIT",
        entityId: habit.id,
        operation: "UPSERT",
        baseRevision: habit.revision ?? null,
        clientUpdatedAt: new Date().toISOString(),
        payload: { name: habit.name, reminderConfig },
      }],
      limit: 500,
    }),
  }));
}

export async function saveReminderSettings(settings, fetchImpl = globalThis.fetch) {
  return readJson(await fetchImpl("/api/habits/reminders/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(settings),
  }));
}

export async function updateReminderOccurrence(action, occurrence, extra = {}, fetchImpl = globalThis.fetch) {
  return readJson(await fetchImpl("/api/habits/reminders/action", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      action,
      occurrenceKey: occurrence.occurrenceKey,
      habitId: occurrence.habitId,
      localDate: occurrence.localDate,
      sourceKey: occurrence.sourceKey,
      scheduledLocalTime: occurrence.localTime || occurrence.scheduledLocalTime,
      ...extra,
    }),
  }));
}

function dashboardDeviceId(storage = globalThis.localStorage) {
  let value = storage?.getItem(DEVICE_KEY);
  if (!value) {
    value = globalThis.crypto?.randomUUID?.() || `dashboard-${Date.now()}`;
    storage?.setItem(DEVICE_KEY, value);
  }
  return value;
}

export async function pushHabitMutations(mutations, habits, cursor, fetchImpl = globalThis.fetch) {
  const byId = new Map(habits.map((habit) => [habit.id, habit]));
  const byName = new Map(habits.flatMap((habit) => [habit.name, habit.sourceName].filter(Boolean)
    .map((name) => [name.toLocaleLowerCase("en"), habit])));
  const outgoing = mutations.map((mutation) => {
    const habit = byId.get(String(mutation.habitId)) || byName.get(String(mutation.habitName || "").toLocaleLowerCase("en"));
    if (!habit) throw new Error(`Nie znaleziono nawyku: ${mutation.habitName || mutation.habitId}`);
    const value = mutation.value;
    return {
      mutationId: mutation.mutationId,
      entityType: "ENTRY",
      entityId: `${habit.id}:${mutation.date}`,
      operation: value === null ? "DELETE" : "UPSERT",
      baseRevision: mutation.baseRevision ?? habit.entryRevisions?.get(mutation.date) ?? null,
      clientUpdatedAt: mutation.updatedAt || new Date().toISOString(),
      payload: {
        habitId: habit.id,
        date: mutation.date,
        status: habit.type === "binary" ? (value === null ? null : Number(value) > 0 ? "DONE" : "MISSED") : null,
        valueMilli: habit.type === "numeric" && value !== null ? Math.round(Number(value) * 1000) : null,
        note: null,
        takenAt: Number(value) > 0 ? mutation.takenAt || mutation.updatedAt || new Date().toISOString() : null,
      },
    };
  });
  return readJson(await fetchImpl("/api/habits/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      schemaVersion: 1,
      deviceId: dashboardDeviceId(),
      lastPulledCursor: cursor || null,
      mutations: outgoing,
      limit: 500,
    }),
  }));
}
