const SESSION_STATUS_ALIASES = Object.freeze({
  TODO: 'TODO',
  IN_PROGRESS: 'IN_PROGRESS',
  'IN PROGRESS': 'IN_PROGRESS',
  W_TRAKCIE: 'IN_PROGRESS',
  'W TRAKCIE': 'IN_PROGRESS',
  DONE: 'DONE',
  ZROBIONE: 'DONE',
  DEFERRED: 'DEFERRED',
  POSTPONED: 'DEFERRED',
  ODLOZONE: 'DEFERRED',
  'ODŁOŻONE': 'DEFERRED',
});

const STATUS_SECTIONS = Object.freeze([
  ['IN_PROGRESS', 'W TRAKCIE'],
  ['TODO', 'TODO'],
  ['DONE', 'ZROBIONE'],
  ['DEFERRED', 'ODŁOŻONE'],
]);

const URGENCY_ORDER = Object.freeze({ DEAD: 0, OVERDUE: 1, DUE: 2, COMING: 3, FRESH: 4 });

const oneLine = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();

export function mapCleaningSessionStatus(task = {}) {
  const raw = oneLine(task.sessionStatus ?? task.session_status ?? task.workflowStatus).toUpperCase();
  return SESSION_STATUS_ALIASES[raw] || 'TODO';
}

function formatDateTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return oneLine(value);
  const parts = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Europe/Warsaw',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const part = (type) => parts.find((item) => item.type === type)?.value || '';
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`;
}

function urgencyRank(task) {
  return URGENCY_ORDER[oneLine(task.status).toUpperCase()] ?? 9;
}

function sortTasks(tasks) {
  return [...tasks].sort((a, b) => (
    urgencyRank(a) - urgencyRank(b)
    || (Number(a.nextDueIn ?? 9999) - Number(b.nextDueIn ?? 9999))
    || oneLine(a.task ?? a.name).localeCompare(oneLine(b.task ?? b.name), 'pl')
  ));
}

function taskTitle(task) {
  const room = oneLine(task.room ?? task.area);
  const name = oneLine(task.task ?? task.name) || 'Zadanie bez nazwy';
  return room && !name.toLocaleLowerCase('pl').includes(room.toLocaleLowerCase('pl'))
    ? `${room} — ${name}`
    : name;
}

function fullTaskLines(task) {
  const lines = [`- ${taskTitle(task)}`];
  const category = oneLine(task.category);
  const urgency = oneLine(task.status);
  const notes = oneLine(task.notes);
  const articles = oneLine(task.articles ?? task.items);
  const reason = oneLine(task.deferReason ?? task.defer_reason ?? task.reason);
  const completedAt = task.completedAt ?? task.doneAt ?? task.lastDone;

  if (category) lines.push(`  Kategoria: ${category}`);
  if (urgency) lines.push(`  Pilność: ${urgency}`);
  if (notes) lines.push(`  Notes: ${notes}`);
  if (articles) lines.push(`  Potrzebne środki: ${articles}`);
  if (mapCleaningSessionStatus(task) === 'DEFERRED' && reason) lines.push(`  Reason: ${reason}`);
  if (mapCleaningSessionStatus(task) === 'DONE' && completedAt) {
    lines.push(`  Ukończono: ${formatDateTime(completedAt)}`);
  }
  return lines;
}

function groupedTasks(tasks, doneToday = []) {
  const groups = new Map(STATUS_SECTIONS.map(([key]) => [key, []]));
  const actions = Array.isArray(doneToday) ? doneToday : [];
  const completedByTaskId = new Map();
  for (const action of actions) {
    const taskId = action.taskId ?? action.row;
    if (taskId != null && !completedByTaskId.has(String(taskId))) {
      completedByTaskId.set(String(taskId), action);
    }
  }

  const matchedActionIds = new Set();
  for (const task of Array.isArray(tasks) ? tasks : []) {
    const taskId = task.id ?? task.row ?? task.row_id;
    const action = taskId == null ? null : completedByTaskId.get(String(taskId));
    const exportTask = action
      ? { ...task, sessionStatus: 'DONE', completedAt: action.doneAt ?? action.at ?? task.lastDone }
      : task;
    if (action) matchedActionIds.add(String(action.actionId ?? action.id ?? taskId));
    groups.get(mapCleaningSessionStatus(exportTask)).push(exportTask);
  }

  for (const action of actions) {
    const actionId = String(action.actionId ?? action.id ?? action.taskId ?? action.row ?? '');
    if (matchedActionIds.has(actionId)) continue;
    groups.get('DONE').push({
      task: action.task ?? action.taskName,
      room: action.room,
      category: action.category,
      status: action.status,
      sessionStatus: 'DONE',
      completedAt: action.doneAt ?? action.at,
    });
  }
  for (const [key, items] of groups) groups.set(key, sortTasks(items));
  return groups;
}

function fullContext(state, generatedAt) {
  const groups = groupedTasks(state.tasks, state.doneToday);
  const lines = [
    '# CLEANING SESSION CONTEXT',
    '',
    `Generated: ${formatDateTime(generatedAt)}`,
  ];
  const apartment = oneLine(state.apartmentLabel ?? state.apartment);
  if (apartment) lines.push(`Apartment: ${apartment}`);
  lines.push(
    '',
    '## SESSION MODE',
    '',
    'Pomagaj mi prowadzić sprzątanie live.',
    '',
    'Prowadź zadania w czterech stanach:',
    '- TODO',
    '- W TRAKCIE',
    '- ZROBIONE',
    '- ODŁOŻONE',
    '',
    'Dawaj mi na raz jedno małe, konkretne zadanie.',
    'Po wykonaniu przechodzimy do następnego.',
    'Nie twórz od razu dużego planu całego mieszkania, jeśli nie jest potrzebny.',
    '',
    '## CURRENT STATE',
  );

  for (const [key, label] of STATUS_SECTIONS) {
    lines.push('', `### ${label}`);
    const tasks = groups.get(key);
    if (!tasks.length) {
      lines.push('Brak.');
      continue;
    }
    for (const task of tasks) lines.push(...fullTaskLines(task));
  }

  lines.push('', '## ADDITIONAL NOTES', '');
  const notes = String(state.sessionNotes ?? '').trim();
  lines.push(notes || 'Brak.');
  lines.push(
    '',
    '## INSTRUCTION FOR CHATGPT',
    '',
    'Na podstawie powyższego stanu kontynuuj ze mną sprzątanie live.',
    '',
    'Najpierw krótko pokaż aktualny stan:',
    'TODO / W TRAKCIE / ZROBIONE / ODŁOŻONE.',
    '',
    'Następnie wskaż dokładnie JEDNĄ następną czynność do wykonania.',
    '',
    'Po mojej odpowiedzi aktualizuj stan i prowadź mnie dalej.',
  );
  return lines.join('\n');
}

function compactContext(state) {
  const groups = groupedTasks(state.tasks, state.doneToday);
  const lines = ['CLEANING LIVE'];
  for (const [key, label] of STATUS_SECTIONS) {
    lines.push('', `${label}:`);
    const tasks = groups.get(key);
    if (!tasks.length) lines.push('Brak.');
    else lines.push(...tasks.map((task) => `- ${taskTitle(task)}`));
  }
  const notes = String(state.sessionNotes ?? '').trim();
  if (notes) lines.push('', 'NOTATKI:', notes);
  lines.push('', 'Prowadź mnie dalej po jednym małym zadaniu naraz.');
  return lines.join('\n');
}

export function generateCleaningContext(state = {}, options = {}) {
  const mode = options.mode === 'compact' ? 'compact' : 'full';
  const generatedAt = options.generatedAt ?? state.generatedAt ?? new Date();
  return mode === 'compact'
    ? compactContext(state)
    : fullContext(state, generatedAt);
}
