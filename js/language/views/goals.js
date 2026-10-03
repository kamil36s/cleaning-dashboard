import { messageState, node, replace, selectControl } from '../components/dom.js';

const METRICS = [
  { value: 'NEW_WORDS', label: 'New words per week', unit: 'WORDS' },
  { value: 'ACTIVE_READING_MINUTES', label: 'Active reading minutes per week', unit: 'MINUTES' },
  { value: 'TEXTS_COMPLETED', label: 'Texts completed per week', unit: 'TEXTS' },
  { value: 'READER_EXPOSURES', label: 'Reader exposures per week', unit: 'EXPOSURES' },
  { value: 'LISTENING_ACTIVE_MINUTES', label: 'Active listening minutes per week', unit: 'MINUTES' },
  { value: 'LISTENING_SESSIONS', label: 'Listening sessions per week', unit: 'SESSIONS' },
  { value: 'LISTENING_TEXTS_COMPLETED', label: 'Listening texts completed per week', unit: 'TEXTS' },
];

function formatWarsawDate(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium', timeZone: 'Europe/Warsaw',
  }).format(parsed);
}

function goalForm({ goal = null, onSave }) {
  const form = node('form', { className: 'language-goal-form' });
  const metric = selectControl('metric', METRICS, goal?.goal?.metric || 'ACTIVE_READING_MINUTES');
  const target = node('input', { name: 'targetValue', value: goal?.target ?? 30, attrs: { type: 'number', min: '0.1', step: '0.1', required: '' } });
  const activeFrom = node('input', { name: 'activeFrom', value: goal?.goal?.activeFrom || '', attrs: { type: 'date' } });
  const activeUntil = node('input', { name: 'activeUntil', value: goal?.goal?.activeUntil || '', attrs: { type: 'date' } });
  const enabled = node('input', { name: 'enabled', attrs: { type: 'checkbox' } });
  enabled.checked = goal?.goal?.enabled ?? true;
  const error = node('p', { className: 'language-form-error', hidden: true, attrs: { role: 'alert' } });
  form.append(
    node('label', { className: 'language-field' }, [node('span', { text: 'Metric' }), metric]),
    node('label', { className: 'language-field' }, [node('span', { text: 'Weekly target' }), target]),
    node('label', { className: 'language-field' }, [node('span', { text: 'Active from (optional)' }), activeFrom]),
    node('label', { className: 'language-field' }, [node('span', { text: 'Active until (optional)' }), activeUntil]),
    node('label', { className: 'language-check' }, [enabled, node('span', { text: 'Enabled' })]),
    node('button', { className: 'language-button is-primary', text: goal ? 'Save goal' : 'Create goal', attrs: { type: 'submit' } }),
    error,
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const selected = METRICS.find((item) => item.value === metric.value);
    try {
      await onSave({
        metric: metric.value, targetValue: Number(target.value), unit: selected.unit,
        period: 'WEEK', weekStart: 1, timezone: 'Europe/Warsaw', enabled: enabled.checked,
        activeFrom: activeFrom.value || null, activeUntil: activeUntil.value || null,
      });
      error.hidden = true;
      if (!goal) form.reset();
    } catch (caught) {
      error.textContent = caught?.message || 'Goal could not be saved.';
      error.hidden = false;
    }
  });
  return form;
}

export function renderGoals(mount, state, { onCreate, onUpdate }) {
  if (state.loading && !state.items.length) return replace(mount, messageState('loading', 'Loading goals…'));
  if (state.error) return replace(mount, messageState('error', 'Goals are unavailable.', state.error));
  const intro = node('details', { className: 'language-card language-goals-create' }, [
    node('summary', { text: 'Create a weekly goal' }),
    node('p', { className: 'language-definition', text: 'Choose a supported Reader or Listening target. Progress uses recorded activity in Europe/Warsaw.' }),
    goalForm({ onSave: onCreate }),
  ]);
  if (!state.items.length) intro.open = true;
  const list = state.items.length ? node('div', { className: 'language-goal-list' }, state.items.map((item) => node('article', { className: 'language-card language-goal-card' }, [
    node('div', { className: 'language-goal-card-head' }, [
      node('div', {}, [
        node('h3', { text: METRICS.find((metric) => metric.value === item.goal.metric)?.label || item.goal.metric }),
        node('p', { text: `${formatWarsawDate(item.periodStart)} → ${formatWarsawDate(item.periodEnd)} · Europe/Warsaw` }),
      ]),
      node('strong', { text: `${item.percentage}%` }),
    ]),
    node('progress', { value: item.current, attrs: { max: item.target, 'aria-label': `${item.percentage}% complete` } }),
    node('p', { text: `${item.current} / ${item.target} ${item.goal.unit.toLowerCase()} · ${item.remaining} remaining` }),
    goalForm({ goal: item, onSave: (payload) => onUpdate(item.goal.id, payload) }),
  ]))) : messageState('empty', 'No goals yet.', 'Create a weekly goal below.');
  replace(mount, node('div', { className: 'language-goals-view' }, [
    node('h3', { text: 'Weekly goals' }), list, intro,
  ]));
}
