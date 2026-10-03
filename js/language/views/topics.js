import { messageState, node, replace } from '../components/dom.js';

function topicForm(topic, onSave) {
  const form = node('form', { className: 'language-topic-form' });
  const name = node('input', { name: 'displayName', value: topic?.displayName || '', attrs: { required: '', maxlength: '120' } });
  const description = node('textarea', { name: 'description', text: topic?.description || '', attrs: { rows: '2', maxlength: '2000' } });
  const archived = node('input', { name: 'archived', attrs: { type: 'checkbox' } });
  archived.checked = topic?.archived || false;
  const error = node('p', { className: 'language-form-error', hidden: true, attrs: { role: 'alert' } });
  const fields = [
    node('label', { className: 'language-field' }, [node('span', { text: 'Name' }), name]),
    node('label', { className: 'language-field' }, [node('span', { text: 'Description' }), description]),
    topic ? node('label', { className: 'language-check' }, [archived, node('span', { text: 'Archived' })]) : null,
    node('button', { className: 'language-button is-primary', text: topic ? 'Save topic' : 'Create topic', attrs: { type: 'submit' } }), error,
  ].filter(Boolean);
  form.append(...fields);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await onSave({ displayName: name.value, description: description.value, ...(topic ? { archived: archived.checked } : {}) });
      error.hidden = true;
      if (!topic) form.reset();
    } catch (caught) {
      error.textContent = caught?.message || 'Topic could not be saved.';
      error.hidden = false;
    }
  });
  return form;
}

export function renderTopics(mount, state, actions) {
  if (state.loading && !state.items.length) return replace(mount, messageState('loading', 'Loading topics…'));
  if (state.error) return replace(mount, messageState('error', 'Topics are unavailable.', state.error));
  const create = node('section', { className: 'language-card' }, [
    node('p', { className: 'language-kicker', text: 'MANUAL MEMBERSHIP ONLY' }), node('h3', { text: 'Create a topic' }),
    node('p', { className: 'language-definition', text: 'No Norwegian vocabulary is seeded or fabricated. Mastery covers only the lemmas you explicitly assign.' }),
    topicForm(null, actions.onCreate),
  ]);
  const list = node('section', { className: 'language-card language-topic-list' }, [
    node('h3', { text: 'Topics' }),
    state.items.length ? node('div', {}, state.items.map((item) => node('button', {
      className: `language-topic-button${state.selected?.topic?.id === item.topic.id ? ' is-selected' : ''}`,
      type: 'button',
    }, [
      node('span', { text: item.topic.displayName }),
      node('strong', { text: item.weightedMasteryPercent == null ? '—' : `${item.weightedMasteryPercent}%` }),
      node('small', { text: `${item.mappedLemmaCount} mapped · partial denominator` }),
    ]))) : node('div', { className: 'language-empty' }, [
      node('div', {}, [node('strong', { text: 'No topics yet.' }),
        node('p', { text: 'Create one above to organize words you already track.' })]),
    ]),
  ]);
  [...list.querySelectorAll('.language-topic-button')].forEach((button, index) => button.addEventListener('click', () => actions.onOpen(state.items[index].topic.id)));

  let detail = null;
  if (state.selected) {
    const topic = state.selected.topic;
    const search = node('input', { placeholder: 'Search canonical vocabulary', attrs: { type: 'search' } });
    const results = node('div', { className: 'language-topic-search-results' });
    let timer;
    search.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        results.replaceChildren();
        if (!search.value.trim()) return;
        const items = await actions.onSearchLemma(search.value);
        items.forEach((lemma) => {
          const add = node('button', { className: 'language-button', text: `Add ${lemma.lemmaDisplay}`, type: 'button' });
          add.addEventListener('click', () => actions.onAssign(topic.id, lemma.id));
          results.append(add);
        });
      }, 180);
    });
    detail = node('section', { className: 'language-card language-topic-detail' }, [
      node('p', { className: 'language-kicker', text: 'USER-MAPPED DENOMINATOR' }),
      node('h3', { text: topic.displayName }),
      node('p', { className: 'language-definition', text: state.selected.mastery.denominatorQuality.message }),
      node('strong', { className: 'language-topic-score', text: state.selected.mastery.weightedMasteryPercent == null ? 'No mapped lemmas' : `${state.selected.mastery.weightedMasteryPercent}% weighted mastery` }),
      topicForm(topic, (payload) => actions.onUpdate(topic.id, payload)),
      node('div', { className: 'language-topic-assignment' }, [node('h4', { text: 'Assign a lemma' }), search, results]),
      state.selected.lemmas.length ? node('ul', { className: 'language-action-list' }, state.selected.lemmas.map((lemma) => {
        const remove = node('button', { className: 'language-button', text: 'Remove', type: 'button' });
        remove.addEventListener('click', () => actions.onRemove(topic.id, lemma.lemmaId));
        return node('li', {}, [
          node('span', {}, [node('strong', { text: lemma.lemmaDisplay }), node('small', { text: `${lemma.knowledgeStatus} · weight ${lemma.weight} · ${lemma.provenance}` })]), remove,
        ]);
      })) : messageState('empty', 'No lemmas assigned.', 'Search the canonical Vocabulary above.'),
    ]);
  }
  replace(mount, node('div', { className: 'language-topics-view' }, [create, list, detail]));
}
