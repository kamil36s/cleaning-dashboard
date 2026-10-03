import { getReminderOccurrences, localDateKey } from "./habits-reminder-schedule.js";

export class ReminderExecutionService {
  constructor({
    getHabits,
    getGroups,
    getStates,
    isComplete,
    claimOccurrence,
    updateOccurrence,
    notify,
    graceMinutes = 5,
  }) {
    this.getHabits = getHabits;
    this.getGroups = getGroups;
    this.getStates = getStates;
    this.isComplete = isComplete;
    this.claimOccurrence = claimOccurrence;
    this.updateOccurrence = updateOccurrence;
    this.notify = notify;
    this.graceMs = graceMinutes * 60_000;
    this.processing = new Set();
  }

  async tick(now = new Date()) {
    const localDate = localDateKey(now);
    const states = this.getStates();
    const stateByKey = new Map(states.map((state) => [state.occurrenceKey, state]));
    const due = [];
    const handledSnoozes = new Set();
    for (const state of states.filter((item) => item.status === "snoozed" && item.snoozedUntil)) {
      const habit = this.getHabits().find((item) => String(item.id) === String(state.habitId));
      if (!habit?.reminderConfig?.enabled || habit.archived) continue;
      const sourceGroupId = state.sourceKey?.startsWith("group:") ? state.sourceKey.slice(6) : null;
      const group = sourceGroupId ? this.getGroups().find((item) => String(item.id) === sourceGroupId) : null;
      const occurrence = {
        occurrenceKey: state.occurrenceKey,
        habitId: state.habitId,
        habitName: habit.name,
        localDate: state.localDate,
        sourceKey: state.sourceKey,
        localTime: state.scheduledLocalTime,
        label: group?.name || (sourceGroupId ? "Time group" : "Custom"),
        scheduledAt: new Date(state.snoozedUntil),
      };
      handledSnoozes.add(state.occurrenceKey);
      if (this.isComplete(habit, state.localDate)
        && habit.reminderConfig.skipIfCompleted
        && habit.reminderConfig.completionPolicy !== "occurrence") {
        await this.updateOccurrence("satisfied", occurrence);
        continue;
      }
      if (new Date(state.snoozedUntil).getTime() <= now.getTime() && !this.processing.has(state.occurrenceKey)) {
        due.push({ occurrence, dueAt: new Date(state.snoozedUntil) });
      }
    }
    for (const habit of this.getHabits()) {
      const config = habit.reminderConfig || {};
      if (!config.enabled || habit.archived) continue;
      const complete = this.isComplete(habit, localDate);
      const occurrences = getReminderOccurrences(habit, localDate, this.getGroups());
      for (const occurrence of occurrences) {
        const state = stateByKey.get(occurrence.occurrenceKey);
        if (handledSnoozes.has(occurrence.occurrenceKey)) continue;
        if (complete && config.skipIfCompleted && config.completionPolicy !== "occurrence") {
          if (state?.status === "snoozed") {
            await this.updateOccurrence("satisfied", occurrence);
          }
          continue;
        }
        let dueAt = occurrence.scheduledAt;
        if (state?.status === "snoozed" && state.snoozedUntil) dueAt = new Date(state.snoozedUntil);
        if (state && state.status !== "snoozed") continue;
        const lateness = now.getTime() - dueAt.getTime();
        if (lateness < 0 || (state?.status !== "snoozed" && lateness > this.graceMs)) continue;
        if (this.processing.has(occurrence.occurrenceKey)) continue;
        due.push({ occurrence, dueAt });
      }
    }
    for (const candidate of due) await this.#fire(candidate.occurrence);
    return due.map((candidate) => candidate.occurrence);
  }

  async #fire(occurrence) {
    this.processing.add(occurrence.occurrenceKey);
    try {
      const result = await this.claimOccurrence(occurrence);
      if (!result?.claimed) return;
      this.notify(occurrence);
    } finally {
      this.processing.delete(occurrence.occurrenceKey);
    }
  }
}
