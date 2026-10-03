import { bootDebug, fetchData, markDone } from './api.js';
import {
  addTask,
  deleteTask,
  getCleaningSettings,
  getCleaningState,
  getTasks,
  saveCleaningSettings,
  undoCleaningAction,
  updateTask,
} from './cleaning-api.js';
import { generateCleaningContext } from './cleaning-context.js';
import { formatCleaningDate, parseCleaningDateInput } from './cleaning-format.js';
import { deriveStatus } from './cleaning-logic.js';
import { TODO_STORE_CHANGED_EVENT, listTodos } from './todo-store.js';
import { isMopPurchasePending } from './cleaning-dependencies.js';
import {
  LAST_LIST,
  preserveCleaningTaskPositions,
  render,
  setCleaningTaskViewMode,
} from './render.js';
import { DATA } from './state.js';
import { OPENAI_PROXY } from './config.js';
import { scheduleUndo } from './undo-toast.js';
import {
  CLEANING_APARTMENTS,
  getActiveCleaningApartment,
  getActiveCleaningApartmentId,
  setActiveCleaningApartment,
} from './cleaning-apartments.js';

// Initial debug ping
bootDebug();

// UI events

/*
const grid = document.getElementById('grid');
const refreshBtn = document.getElementById('refresh');
const dueOnly = document.getElementById('dueOnly');
const roomSel = document.getElementById('room');
const sortSel = document.getElementById('sort');
const catSel = document.getElementById('category');

refreshBtn.addEventListener('click', fetchData);
dueOnly.addEventListener('change', render);
roomSel.addEventListener('change', render);
sortSel.addEventListener('change', render);
catSel.addEventListener('change', render);

grid.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button.pill');
  if (!btn) return;
  const row = Number(btn.dataset.row || 0);
  if (!row) return;
  const prev = btn.textContent;
  btn.disabled = true; btn.textContent = '...';
  try { await markDone(row); } finally { btn.disabled = false; btn.textContent = prev; }
});
*/

// UI events  — null-safe
const $ = (id) => document.getElementById(id);
const on = (el, ev, fn) => el && el.addEventListener(ev, fn);

const grid     = $('grid');
const refreshBtn = $('refresh');   // upewnij się, że ID istnieje na tej stronie
const dueOnly  = $('dueOnly');
const roomSel  = $('room');
const sortSel  = $('sort');
const catSel   = $('category');
const apartmentSel = $('cleaning-apartment');
const taskDialog = $('cleaning-task-dialog');
const taskForm = $('cleaning-task-form');
const taskApartment = $('cleaning-task-apartment');
const taskFormError = $('cleaning-task-form-error');
const taskArticles = $('cleaning-task-articles');
const taskArticleSuggestions = $('cleaning-task-article-suggestions');
const contextDialog = $('cleaning-context-dialog');
const contextOutput = $('cleaning-context-output');
const contextNotes = $('cleaning-session-notes');
const contextMode = $('cleaning-context-mode');
const contextStatus = $('cleaning-context-status');
const viewSwitcher = $('cleaning-view-switcher');
const pendingDoneTaskIds = new Set();
let contextState = { tasks: [], sessionNotes: '' };
let sessionNotesByApartment = {};
let sessionNotesSaveTimer = null;

function syncPendingDoneButtons() {
  if (!grid) return;
  grid.querySelectorAll('button.pill[data-row]').forEach((button) => {
    const pending = pendingDoneTaskIds.has(String(button.dataset.row || ''));
    if (pending) {
      if (!button.dataset.pendingLabel) button.dataset.pendingLabel = button.textContent;
      button.textContent = 'DONE';
    } else if (button.dataset.pendingLabel) {
      button.textContent = button.dataset.pendingLabel;
      delete button.dataset.pendingLabel;
    }
    button.disabled = pending;
    button.classList.toggle('is-pending', pending);
    button.classList.remove('is-click-locked');
    button.setAttribute('aria-busy', pending ? 'true' : 'false');
  });
}

function renderApartmentSelect() {
  if (!apartmentSel) return;
  const activeId = getActiveCleaningApartmentId();
  apartmentSel.innerHTML = CLEANING_APARTMENTS
    .map((apartment) => `<option value="${apartment.id}">${apartment.label}</option>`)
    .join('');
  apartmentSel.value = activeId;
  if (taskApartment) {
    taskApartment.innerHTML = apartmentSel.innerHTML;
    taskApartment.value = activeId;
  }
}

function closeTaskDialog() {
  if (!taskDialog) return;
  if (typeof taskDialog.close === 'function') taskDialog.close();
  else taskDialog.removeAttribute('open');
}

function sortedUnique(values) {
  const seen = new Map();
  for (const raw of values) {
    const value = String(raw || '').trim();
    const key = value.toLocaleLowerCase('pl-PL');
    if (value && !seen.has(key)) seen.set(key, value);
  }
  return [...seen.values()].sort((a, b) => a.localeCompare(b, 'pl'));
}

function splitArticles(value) {
  return String(value || '').split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
}

function fillDatalist(id, values) {
  const list = $(id);
  if (!list) return;
  list.replaceChildren(...values.map((value) => {
    const option = document.createElement('option');
    option.value = value;
    return option;
  }));
}

function renderTaskSuggestions(tasks) {
  const rooms = sortedUnique(tasks.map((task) => task.room));
  const categories = sortedUnique(tasks.map((task) => task.category));
  const articles = sortedUnique(tasks.flatMap((task) => splitArticles(task.articles || task.items)));
  fillDatalist('cleaning-task-room-options', rooms);
  fillDatalist('cleaning-task-category-options', categories);
  fillDatalist('cleaning-task-article-options', articles);
  if (!taskArticleSuggestions) return;
  taskArticleSuggestions.replaceChildren(...articles.map((article) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cleaning-task-suggestion';
    button.dataset.article = article;
    button.textContent = article;
    return button;
  }));
}

async function loadTaskSuggestions(apartmentId) {
  const tasks = apartmentId === getActiveCleaningApartmentId() && DATA.length
    ? DATA
    : await getTasks(apartmentId);
  renderTaskSuggestions(tasks);
}

function openTaskDialog(task = null) {
  if (!taskDialog || !taskForm) return;
  taskForm.reset();
  $('cleaning-task-id').value = task?.id ?? '';
  taskApartment.value = task?.apartmentId || getActiveCleaningApartmentId();
  taskApartment.disabled = !!task;
  $('cleaning-task-room').value = task?.room || '';
  $('cleaning-task-category').value = task?.category || '';
  $('cleaning-task-name').value = task?.task || '';
  $('cleaning-task-freq').value = task?.freq ?? '';
  $('cleaning-task-last-done').value = formatCleaningDate(task?.lastDone);
  $('cleaning-task-articles').value = task?.articles || task?.items || '';
  $('cleaning-task-notes').value = task?.notes || '';
  $('cleaning-task-dialog-title').textContent = task ? 'Edytuj zadanie' : 'Dodaj zadanie';
  $('cleaning-task-submit').textContent = task ? 'Zapisz zmiany' : 'Dodaj zadanie';
  taskFormError.hidden = true;
  taskFormError.textContent = '';
  loadTaskSuggestions(taskApartment.value).catch(() => renderTaskSuggestions(DATA));
  if (typeof taskDialog.showModal === 'function') taskDialog.showModal();
  else taskDialog.setAttribute('open', '');
}

on(refreshBtn, 'click', fetchData);
let mopPurchasePending = isMopPurchasePending(listTodos());
const refreshAfterTodoChange = () => {
  const nextPending = isMopPurchasePending(listTodos());
  if (nextPending === mopPurchasePending) return;
  mopPurchasePending = nextPending;
  fetchData();
};
window.addEventListener(TODO_STORE_CHANGED_EVENT, refreshAfterTodoChange);
window.addEventListener('storage', (event) => {
  if (event.key === 'todo-items-v1') refreshAfterTodoChange();
});
on(dueOnly,   'change', render);
on(roomSel,   'change', render);
on(sortSel,   'change', render);
on(catSel,    'change', render);
on(viewSwitcher, 'click', (event) => {
  const button = event.target.closest('button[data-cleaning-view]');
  if (!button) return;
  setCleaningTaskViewMode(button.dataset.cleaningView);
  render();
});
on(apartmentSel, 'change', async () => {
  setActiveCleaningApartment(apartmentSel.value);
  if (roomSel) roomSel.innerHTML = '<option value="ALL">All rooms</option>';
  if (catSel) catSel.innerHTML = '<option value="ALL">All categories</option>';
  await fetchData();
});
on($('cleaning-add-task'), 'click', () => openTaskDialog());
on($('cleaning-task-dialog-close'), 'click', closeTaskDialog);
on($('cleaning-task-cancel'), 'click', closeTaskDialog);
on(taskApartment, 'change', () => {
  loadTaskSuggestions(taskApartment.value).catch(() => renderTaskSuggestions([]));
});
on(taskArticleSuggestions, 'click', (event) => {
  const button = event.target.closest('button[data-article]');
  if (!button || !taskArticles) return;
  const existing = splitArticles(taskArticles.value);
  if (!existing.some((item) => item.toLocaleLowerCase('pl-PL') === button.dataset.article.toLocaleLowerCase('pl-PL'))) {
    existing.push(button.dataset.article);
  }
  taskArticles.value = existing.join(', ');
  taskArticles.focus();
});
on($('cleaning-task-last-done'), 'input', (event) => {
  const digits = event.target.value.replace(/\D/g, '').slice(0, 8);
  event.target.value = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)]
    .filter(Boolean)
    .join('/');
});
on(taskDialog, 'click', (event) => {
  if (event.target === taskDialog) closeTaskDialog();
});
on(taskForm, 'submit', async (event) => {
  event.preventDefault();
  const submit = $('cleaning-task-submit');
  const taskId = $('cleaning-task-id').value;
  let lastDone = null;
  try {
    lastDone = parseCleaningDateInput($('cleaning-task-last-done').value);
  } catch (error) {
    taskFormError.textContent = error.message;
    taskFormError.hidden = false;
    $('cleaning-task-last-done').focus();
    return;
  }
  const payload = {
    room: $('cleaning-task-room').value.trim(),
    category: $('cleaning-task-category').value.trim(),
    task: $('cleaning-task-name').value.trim(),
    freq: Number($('cleaning-task-freq').value),
    lastDone,
    articles: $('cleaning-task-articles').value.trim(),
    notes: $('cleaning-task-notes').value.trim(),
  };
  submit.disabled = true;
  taskFormError.hidden = true;
  try {
    if (taskId) await updateTask(taskId, payload);
    else await addTask(taskApartment.value, payload);
    closeTaskDialog();
    await fetchData();
  } catch (error) {
    taskFormError.textContent = error?.message || 'Nie udało się zapisać zadania.';
    taskFormError.hidden = false;
  } finally {
    submit.disabled = false;
  }
});

on(window, 'cleaning:rendered', syncPendingDoneButtons);
on(window, 'cleaning-action:removed', () => fetchData());

on(grid, 'click', async (ev) => {
  const taskAction = ev.target.closest('button.cleaning-task-action');
  if (taskAction) {
    const taskId = taskAction.dataset.taskId;
    const task = LAST_LIST.find((item) => String(item.id ?? item.row ?? item.row_id) === String(taskId));
    if (!task) return;
    if (taskAction.dataset.action === 'edit') {
      openTaskDialog(task);
      return;
    }
    if (taskAction.dataset.action === 'delete') {
      const confirmed = window.confirm(`Usunąć zadanie „${task.task}”? Historia wykonań zostanie zachowana.`);
      if (!confirmed) return;
      taskAction.disabled = true;
      try {
        await deleteTask(taskId);
        await fetchData();
      } catch (error) {
        window.alert(error?.message || 'Nie udało się usunąć zadania.');
        taskAction.disabled = false;
      }
      return;
    }
  }
  const btn = ev.target.closest('button.pill');
  if (!btn) return;
  const row = btn.dataset.row || '';
  if (!row) return;
  if (pendingDoneTaskIds.size > 0 || pendingDoneTaskIds.has(String(row))) return;
  const taskMeta = LAST_LIST.find((item) => String(item.id ?? item.row ?? item.row_id) === String(row));
  const title =
    taskMeta?.task ||
    btn.closest('.card')?.querySelector('.title span:last-child')?.textContent?.trim() ||
    'zadanie';
  preserveCleaningTaskPositions();
  pendingDoneTaskIds.add(String(row));
  syncPendingDoneButtons();

  const savedAction = markDone(row, {
    refresh: false,
    history: {
      task: title,
      room: taskMeta?.room,
      category: taskMeta?.category,
      status: taskMeta ? deriveStatus(taskMeta) : '',
      source: 'cleaning-page',
    },
  }).then(async (result) => {
    if (result) await fetchData();
    return result;
  });

  scheduleUndo({
    message: `Zaznaczone: ${title}`,
    duration: 4000,
    onUndo: async () => {
      try {
        const result = await savedAction;
        const actionId = result?.action?.actionId ?? result?.action?.id;
        if (actionId) await undoCleaningAction(actionId);
        await fetchData();
      } finally {
        pendingDoneTaskIds.delete(String(row));
        syncPendingDoneButtons();
      }
    },
    onCommit: async () => {
      try {
        const ok = await savedAction;
        if (!ok) {
          throw new Error('markDone_failed');
        }
      } finally {
        pendingDoneTaskIds.delete(String(row));
        syncPendingDoneButtons();
      }
    }
  });
});


function summarizeVisible(){
  const box = document.getElementById('ai-box');
  const out = document.getElementById('ai-output');
  if (!box || !out) return;

  // Minimalny, ucięty payload
  const payload = LAST_LIST.slice(0, 40).map(t => ({
    task: t.task,
    room: t.room,
    category: t.category,
    status: (t.overdue
      ? (((t.daysSince||0)-(t.freq||0)) > 7 ? 'dead' : 'overdue')
      : (t.nextDueIn===0 ? 'due' : (((t.daysSince||0)/(t.freq||1)) >= .8 ? 'coming':'fresh')))
  }));

  box.hidden = false;
  box.classList.add('loading');
  out.textContent = 'Thinking…';

  fetch(OPENAI_PROXY, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ tasks: payload })
})
.then(async r => {
  const txt = await r.text().catch(()=> r.statusText);
  if (!r.ok) throw new Error(`${r.status} ${txt}`);
  return JSON.parse(txt);
})
.then(j => { out.textContent = j.text || '(no content)'; })
.catch(err => { out.textContent = `AI error: ${String(err.message||err)}`; })
.finally(()=> box.classList.remove('loading'));
}

document.getElementById('gen-tips')?.addEventListener('click', summarizeVisible);

function closeContextDialog() {
  if (!contextDialog) return;
  if (typeof contextDialog.close === 'function') contextDialog.close();
  else contextDialog.removeAttribute('open');
}

function renderContextOutput() {
  if (!contextOutput) return;
  contextState.sessionNotes = contextNotes?.value || '';
  contextOutput.value = generateCleaningContext(contextState, { mode: contextMode?.value });
}

async function persistSessionNotes() {
  const apartmentId = getActiveCleaningApartmentId();
  sessionNotesByApartment = {
    ...sessionNotesByApartment,
    [apartmentId]: contextNotes?.value || '',
  };
  await saveCleaningSettings({ sessionNotesByApartment });
}

async function refreshContext({ saveNotes = true } = {}) {
  if (contextStatus) contextStatus.textContent = 'Odświeżanie…';
  try {
    if (saveNotes) await persistSessionNotes();
    const apartmentId = getActiveCleaningApartmentId();
    const state = await getCleaningState(apartmentId);
    contextState = {
      ...state,
      apartmentLabel: getActiveCleaningApartment().label,
      sessionNotes: contextNotes?.value || '',
    };
    renderContextOutput();
    if (contextStatus) contextStatus.textContent = 'Kontekst jest aktualny.';
    return contextOutput?.value || '';
  } catch (error) {
    if (contextStatus) contextStatus.textContent = error?.message || 'Nie udało się wygenerować kontekstu.';
    throw error;
  }
}

async function openContextDialog() {
  if (!contextDialog) return;
  if (typeof contextDialog.showModal === 'function') contextDialog.showModal();
  else contextDialog.setAttribute('open', '');
  if (contextStatus) contextStatus.textContent = 'Wczytywanie…';
  try {
    const apartmentId = getActiveCleaningApartmentId();
    const [state, settingsPayload] = await Promise.all([
      getCleaningState(apartmentId),
      getCleaningSettings(),
    ]);
    const settings = settingsPayload?.settings || settingsPayload || {};
    sessionNotesByApartment = settings.sessionNotesByApartment || {};
    if (contextNotes) contextNotes.value = sessionNotesByApartment[apartmentId] || '';
    contextState = {
      ...state,
      apartmentLabel: getActiveCleaningApartment().label,
      sessionNotes: contextNotes?.value || '',
    };
    renderContextOutput();
    if (contextStatus) contextStatus.textContent = 'Kontekst jest aktualny.';
  } catch (error) {
    if (contextStatus) contextStatus.textContent = error?.message || 'Nie udało się wczytać danych.';
  }
}

async function copyContextToClipboard() {
  const text = await refreshContext();
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard_unavailable');
    await navigator.clipboard.writeText(text);
  } catch {
    contextOutput.focus();
    contextOutput.select();
    contextOutput.setSelectionRange(0, contextOutput.value.length);
    if (!document.execCommand?.('copy')) throw new Error('Nie udało się skopiować tekstu.');
  }
  if (contextStatus) contextStatus.textContent = 'Skopiowano do schowka.';
}

async function downloadContext() {
  const text = await refreshContext();
  const href = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = href;
  link.download = `cleaning-context-${new Date().toISOString().slice(0, 10)}.txt`;
  link.click();
  URL.revokeObjectURL(href);
  if (contextStatus) contextStatus.textContent = 'Pobrano plik tekstowy.';
}

on($('cleaning-generate-context'), 'click', openContextDialog);
on($('cleaning-context-close'), 'click', () => {
  persistSessionNotes().catch(() => {});
  closeContextDialog();
});
on(contextDialog, 'click', (event) => {
  if (event.target === contextDialog) {
    persistSessionNotes().catch(() => {});
    closeContextDialog();
  }
});
on(contextNotes, 'input', () => {
  renderContextOutput();
  clearTimeout(sessionNotesSaveTimer);
  sessionNotesSaveTimer = setTimeout(() => persistSessionNotes().catch(() => {}), 500);
});
on(contextNotes, 'blur', () => persistSessionNotes().catch(() => {}));
on(contextMode, 'change', renderContextOutput);
on($('cleaning-context-refresh'), 'click', () => refreshContext().catch(() => {}));
on($('cleaning-context-copy'), 'click', () => copyContextToClipboard().catch((error) => {
  if (contextStatus) contextStatus.textContent = error?.message || 'Nie udało się skopiować tekstu.';
}));
on($('cleaning-context-download'), 'click', () => downloadContext().catch((error) => {
  if (contextStatus) contextStatus.textContent = error?.message || 'Nie udało się pobrać pliku.';
}));

// Start
renderApartmentSelect();
fetchData();
