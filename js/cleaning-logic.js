export const N = (v) => (v == null || v === '') ? null : Number(v);

export const daysOver = (t) => t.overdue ? Math.max(0, (N(t.daysSince) || 0) - (N(t.freq) || 0)) : 0;
export const isDead = (t) => !t.blocked && t.overdue && daysOver(t) > 7; // DEAD = spoznienie > 7 dni

const COMING_FRAC = 0.92;

export const usedFrac = (t) =>
  t.overdue ? 1.01 :
  (Number.isFinite(N(t.freq)) && N(t.freq) > 0 && Number.isFinite(N(t.daysSince)))
    ? N(t.daysSince) / N(t.freq)
    : 0;

export const isDue = (t) => !t.blocked && !t.overdue && N(t.nextDueIn) === 0;
export const isComing = (t) => !t.blocked && !t.overdue && !isDue(t) && usedFrac(t) >= COMING_FRAC;

export const deriveStatus = (t) => {
  if (t.blocked) return 'BLOCKED';
  if (isDead(t)) return 'DEAD';
  if (t.overdue) return 'OVERDUE';
  if (isDue(t)) return 'DUE';
  if (isComing(t)) return 'COMING';
  return 'FRESH';
};

export const statusOrder = { DEAD: 0, OVERDUE: 1, DUE: 2, COMING: 3, FRESH: 9, BLOCKED: 10 };

const stableTaskKey = (task) => String(
  task?.id ?? task?.row ?? task?.row_id ?? [task?.room || '', task?.category || '', task?.task || ''].join('|')
);

export function preserveTaskOrder(previousTasks, currentTasks) {
  const currentByKey = new Map(currentTasks.map((task) => [stableTaskKey(task), task]));
  const stableKeys = new Set();
  const stableTasks = [];
  for (const previousTask of previousTasks) {
    const key = stableTaskKey(previousTask);
    const currentTask = currentByKey.get(key);
    if (!currentTask) continue;
    stableKeys.add(key);
    stableTasks.push(currentTask);
  }
  return [...stableTasks, ...currentTasks.filter((task) => !stableKeys.has(stableTaskKey(task)))];
}

function groupTasksByField(tasks, field, fallbackLabel) {
  const collator = new Intl.Collator('pl', { sensitivity: 'base', numeric: true });
  const fallbackKey = fallbackLabel.toLocaleLowerCase('pl-PL');
  const groups = new Map();

  for (const task of Array.isArray(tasks) ? tasks : []) {
    const label = String(task?.[field] || '').trim() || fallbackLabel;
    const key = label.toLocaleLowerCase('pl-PL');
    if (!groups.has(key)) groups.set(key, { key, [field]: label, tasks: [] });
    groups.get(key).tasks.push(task);
  }

  return [...groups.values()].sort((a, b) => {
    if (a.key === fallbackKey && b.key !== fallbackKey) return 1;
    if (b.key === fallbackKey && a.key !== fallbackKey) return -1;
    return collator.compare(a[field], b[field]);
  });
}

export function groupTasksByRoom(tasks, fallbackLabel = 'Bez pokoju') {
  return groupTasksByField(tasks, 'room', fallbackLabel);
}

export function groupTasksByCategory(tasks, fallbackLabel = 'Bez kategorii') {
  return groupTasksByField(tasks, 'category', fallbackLabel);
}

export function computeCounts(arr) {
  const active = arr.filter((task) => !task.blocked);
  const total = active.length;
  const overdue = active.filter(t => !!t.overdue).length;
  const due = active.filter(isDue).length;
  const coming = active.filter(isComing).length;
  const dead = active.filter(isDead).length;
  const pending = overdue + due + coming;
  const ok = Math.max(0, total - pending);
  const pct = total ? Math.round((ok / total) * 100) : 0;
  return { total, overdue, due, coming, dead, ok, pct };
}
