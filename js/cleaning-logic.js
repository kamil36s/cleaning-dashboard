export const N = (v) => (v == null || v === '') ? null : Number(v);

export const daysOver = (t) => t.overdue ? Math.max(0, (N(t.daysSince) || 0) - (N(t.freq) || 0)) : 0;
export const isDead = (t) => t.overdue && daysOver(t) > 7; // DEAD = spoznienie > 7 dni

const COMING_FRAC = 0.92;

export const usedFrac = (t) =>
  t.overdue ? 1.01 :
  (Number.isFinite(N(t.freq)) && N(t.freq) > 0 && Number.isFinite(N(t.daysSince)))
    ? N(t.daysSince) / N(t.freq)
    : 0;

export const isDue = (t) => !t.overdue && N(t.nextDueIn) === 0;
export const isComing = (t) => !t.overdue && !isDue(t) && usedFrac(t) >= COMING_FRAC;

export const deriveStatus = (t) => {
  if (isDead(t)) return 'DEAD';
  if (t.overdue) return 'OVERDUE';
  if (isDue(t)) return 'DUE';
  if (isComing(t)) return 'COMING';
  return 'FRESH';
};

export const statusOrder = { DEAD: 0, OVERDUE: 1, DUE: 2, COMING: 3, FRESH: 9 };

export function computeCounts(arr) {
  const total = arr.length;
  const overdue = arr.filter(t => !!t.overdue).length;
  const due = arr.filter(isDue).length;
  const coming = arr.filter(isComing).length;
  const dead = arr.filter(isDead).length;
  const pending = overdue + due + coming;
  const ok = Math.max(0, total - pending);
  const pct = total ? Math.round((ok / total) * 100) : 0;
  return { total, overdue, due, coming, dead, ok, pct };
}
