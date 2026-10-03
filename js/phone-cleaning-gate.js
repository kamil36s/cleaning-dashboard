const TARGET_KEY = 'cleaningDashboard.dailyGoalTarget.v2';
let lastPublished = '';
let lastPublishedAt = 0;
const dayKey = () => {
  const date = new Date();
  date.setHours(date.getHours() - 6);
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
};

export async function publishCleaningGoal(apartmentId, target, done) {
  const complete = target > 0 && done >= target;
  const stamp = `${dayKey()}:${apartmentId}:${target}:${done}:${complete}`;
  if (stamp === lastPublished && Date.now() - lastPublishedAt < 60_000) return;
  const response = await fetch('/api/cleaning/phone-goal', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({apartmentId,day:dayKey(),target,done}),
  });
  if (!response.ok) throw new Error(`Cleaning phone gate HTTP ${response.status}`);
  lastPublished = stamp;
  lastPublishedAt = Date.now();
}

export async function refreshCleaningGoalAfterAction(apartmentId, loadState) {
  let snapshot;
  try { snapshot = JSON.parse(localStorage.getItem(TARGET_KEY) || 'null'); } catch { return; }
  const target = Number(snapshot?.target);
  if (!Number.isFinite(target) || snapshot?.key !== `${apartmentId}:${dayKey()}`) return;
  const state = await loadState(apartmentId);
  await publishCleaningGoal(apartmentId,target,state.doneToday?.length || 0);
}
