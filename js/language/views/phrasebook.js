import { messageState, node, replace, statusPill } from '../components/dom.js';

function sourceLink(entry) {
  if (['READER', 'GENERATED'].includes(entry.sourceType) && entry.sourceEntityId) {
    return node('a', {
      className: 'language-button is-quiet', text: 'Open source',
      attrs: { href: `#reader/text/${encodeURIComponent(entry.sourceEntityId)}` },
    });
  }
  return null;
}

function entryCard(entry, actions) {
  const note = node('textarea', {
    text: entry.note || '',
    attrs: { maxlength: '5000', placeholder: 'Your note (optional)' },
  });
  const translation = node('textarea', {
    text: entry.userTranslation || '',
    attrs: { maxlength: '5000', placeholder: 'Your translation (optional)' },
  });
  const status = node('span', { className: 'language-definition', attrs: { role: 'status' } });
  const save = node('button', { className: 'language-button is-primary', type: 'button', text: 'Save edits' });
  save.addEventListener('click', async () => {
    save.disabled = true; status.textContent = 'Saving…';
    try {
      await actions.onUpdate(entry.id, {
        note: note.value.trim() || null,
        userTranslation: translation.value.trim() || null,
      });
      status.textContent = 'Saved.';
    } catch (error) {
      status.textContent = error?.message || 'Could not save edits.';
      save.disabled = false;
    }
  });
  const remove = node('button', { className: 'language-button is-danger', type: 'button', text: 'Delete' });
  remove.addEventListener('click', async () => {
    if (!globalThis.confirm?.(`Delete “${entry.expressionText}” from Phrasebook?`)) return;
    remove.disabled = true;
    try { await actions.onDelete(entry.id); }
    catch (error) { remove.disabled = false; status.textContent = error?.message || 'Could not delete entry.'; }
  });
  const links = entry.links || [];
  return node('article', { className: 'language-card language-phrasebook-entry' }, [
    node('div', { className: 'language-phrasebook-head' }, [
      node('div', {}, [
        node('p', { className: 'language-kicker', text: entry.sourceType || 'MANUAL' }),
        node('h3', { text: entry.expressionText }),
      ]),
      statusPill(entry.sourceType || 'MANUAL', 'muted'),
    ]),
    entry.sourceContext ? node('blockquote', { text: entry.sourceContext }) : node('p', { text: 'No source context was stored.' }),
    node('label', { className: 'language-field' }, [node('span', { text: 'Your translation' }), translation]),
    node('label', { className: 'language-field' }, [node('span', { text: 'Your note' }), note]),
    links.length ? node('details', {}, [
      node('summary', { text: `Related links (${links.length})` }),
      node('ul', {}, links.map((item) => node('li', { text: `${item.linkType}: ${item.linkValue}` }))),
    ]) : null,
    node('div', { className: 'language-form-actions' }, [save, sourceLink(entry), remove, status]),
  ]);
}

export function renderPhrasebook(mount, state, actions) {
  const search = node('input', {
    type: 'search', value: state.query || '', placeholder: 'Search expressions, notes or translations…',
    attrs: { maxlength: '300', autocomplete: 'off' },
  });
  const source = node('select', {}, [
    node('option', { text: 'All sources', attrs: { value: '' } }),
    ...['READER', 'CLOZE', 'GENERATED', 'MANUAL'].map((value) => node('option', { text: value, attrs: { value } })),
  ]);
  source.value = state.sourceType || '';
  const form = node('form', { className: 'language-card language-phrasebook-search' }, [
    node('div', { className: 'language-form-grid' }, [
      node('label', { className: 'language-field' }, [node('span', { text: 'Search' }), search]),
      node('label', { className: 'language-field' }, [node('span', { text: 'Source' }), source]),
    ]),
    node('button', { className: 'language-button is-primary', type: 'submit', text: 'Filter' }),
  ]);
  form.addEventListener('submit', (event) => {
    event.preventDefault(); actions.onSearch(search.value.trim(), source.value);
  });
  const heading = node('div', { className: 'language-section-heading' }, [
    node('div', {}, [
      node('p', { className: 'language-kicker', text: 'PERSONAL · NO MASTERY CREDIT' }),
      node('h3', { text: 'Phrasebook' }),
      node('p', { text: `${state.total || 0} saved expressions with exact source snapshots.` }),
    ]),
  ]);
  let body;
  if (state.loading) body = messageState('loading', 'Loading Phrasebook…');
  else if (state.error) body = messageState('error', 'Phrasebook is unavailable.', state.error);
  else if (!state.items.length) body = node('div', { className: 'language-empty' }, [
    node('div', {}, [node('strong', { text: 'No saved expressions yet.' }),
      node('p', { text: 'Save a useful phrase while reading or practicing Cloze.' }),
      node('a', { className: 'language-button is-primary', text: 'Open Reader', attrs: { href: '#reader' } }),
    ]),
  ]);
  else body = node('div', { className: 'language-phrasebook-list' }, state.items.map((entry) => entryCard(entry, actions)));
  replace(mount, node('div', { className: 'language-phrasebook-page' }, [heading, form, body]));
}
