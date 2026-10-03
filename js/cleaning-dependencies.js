import { listTodos, todoStoreReady } from './todo-store.js';

const MOP_TODO_ID = 'ad7ac326-5485-4157-98c8-401f702cbbb9';
const normalize = (value) => String(value || '').toLocaleLowerCase('pl-PL')
  .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  .replace(/ł/g, 'l').replace(/\s+/g, ' ').trim();

export function isMopPurchasePending(todos) {
  const items = Array.isArray(todos) ? todos : [];
  const mop = items.find((item) => item?.id === MOP_TODO_ID)
    || items.find((item) => item?.bucket === 'shopping' && normalize(item?.title) === 'mop do podlogi');
  return Boolean(mop && !mop.done);
}

export function applyCleaningDependencies(tasks, todos) {
  if (!Array.isArray(tasks)) return [];
  const pending = isMopPurchasePending(todos);
  return tasks.map((task) => {
    const blocked = pending && /^umyj podloge mopem\b/.test(normalize(task?.task));
    return blocked ? { ...task, blocked: true } : task;
  });
}

export async function resolveCleaningDependencies(tasks) {
  await todoStoreReady;
  return applyCleaningDependencies(tasks, listTodos());
}
