import {
  DISPOSITIONS,
  KNOWLEDGE_STATUSES,
  dispositionLabel,
  formatLanguageDate,
  knowledgeLabel,
  scoreLabel,
  vocabularyRow,
} from '../model.js';
import { field, messageState, node, replace, selectControl, statusPill } from '../components/dom.js';
import { createLexicalInspector } from '../components/lexical-inspector.js';
import { wordAudioControl } from '../components/word-audio-control.js';

function stateTone(status) {
  if (status === 'KNOWN' || status === 'MASTERED') return 'ready';
  if (status === 'LEARNING') return 'lazy';
  return 'muted';
}

function cell(child) {
  return node('td', {}, child);
}

const COLUMN_HELP = {
  Lemma: 'The dictionary form of the word. The smaller line shows its part of speech and normalized spelling.',
  Audio: 'Play the Norwegian pronunciation of this vocabulary word.',
  State: 'Your vocabulary knowledge level (New, Learning, Known, or Mastered) and whether the word is tracked. It is not the same as the Anki card queue.',
  Anki: 'Cards found across all Anki decks at the shown check time. New = unseen; Learning = in learning steps; Review = scheduled review; Suspended = paused; Buried = temporarily hidden. Linked notes and unambiguous exact word matches are included.',
  'R / C / P': 'Recognition / Recall / Production, each scored 0–5. Recognition: understand it when seen; Recall: remember its meaning; Production: use it yourself. — means no score has been set.',
  Forms: 'Number of distinct written forms linked to this dictionary word, such as inflections. It is not the number of times you saw the word.',
  Exposures: 'Number of recorded encounters with this word during Reader or listening study. Saving or analyzing a text alone does not add an exposure.',
  Zipf: 'Estimated frequency in general Norwegian: higher means more common; one point is roughly 10× more frequent. It is not your personal usage or an exact rank. — means no estimate.',
  'Last seen': 'Time of the latest recorded study encounter that added an exposure. It is not the date the text was saved or the date of an Anki review. — means none yet.',
};

function columnHeader(label) {
  return node('th', { attrs: { scope: 'col', title: COLUMN_HELP[label], 'aria-label': `${label}. ${COLUMN_HELP[label]}`, tabindex: '0' } }, [
    node('span', { text: label }), node('span', { className: 'language-column-help', text: 'ⓘ', attrs: { 'aria-hidden': 'true' } }),
  ]);
}

function ankiCell(ankiStatus, lemmaId) {
  const status = ankiStatus?.status;
  if (!status || status === 'LOADING') return node('span', { className: 'language-anki-empty', text: 'Checking…' });
  if (status === 'NOT_CONFIGURED') return node('span', { className: 'language-anki-empty', text: 'Not connected' });
  if (status === 'TOO_LARGE') return node('span', { className: 'language-anki-empty', text: 'Too many cards to check' });
  if (status !== 'CURRENT') return node('span', { className: 'language-anki-empty', text: 'Anki unavailable' });
  const decks = ankiStatus.lemmas?.[lemmaId] || [];
  if (!decks.length) return node('span', { className: 'language-anki-empty', text: 'No exact match' });
  return node('div', { className: 'language-anki-deck-list', attrs: { title: `Checked ${formatLanguageDate(ankiStatus.observedAt)}` } }, decks.map((deck) => {
    const counts = new Map();
    (deck.statuses || []).forEach((value) => counts.set(value, (counts.get(value) || 0) + 1));
    return node('div', { className: 'language-anki-deck' }, [
      node('span', { className: 'language-anki-deck-name', text: deck.deckName }),
      node('span', { text: [...counts].map(([value, count]) => `${value === 'REVIEW' ? 'Review' : value.charAt(0) + value.slice(1).toLowerCase()}${count > 1 ? ` ×${count}` : ''}`).join(', ') }),
    ]);
  }));
}

function vocabularyTable(items, ankiStatus, onOpenLemma, onPlayAudio, compact = false) {
  const table = node('table', { className: 'language-table language-vocabulary-table' });
  const head = node('thead', {}, node('tr', {}, [
    ...Object.keys(COLUMN_HELP).map(columnHeader),
  ]));
  const body = node('tbody');
  items.map(vocabularyRow).forEach((item) => {
    const open = node('button', {
      className: `language-lemma-open${compact ? ' language-reader-token' : ''}`,
      type: 'button',
      dataset: { lemmaId: item.id, tokenId: item.id, lemmaDisplay: item.lemma,
        wordSurface: item.lemma, tokenState: String(item.knowledgeStatus || 'NEW').toLowerCase() },
      attrs: { 'aria-label': `Open ${item.lemma}` },
    }, [node('strong', { text: item.lemma }), node('span', { text: `${item.partOfSpeech} · ${item.normalized || 'no normalized value'}` })]);
    if (!compact) open.addEventListener('click', () => onOpenLemma(item.id));
    body.append(node('tr', {}, [
      cell(open),
      cell(wordAudioControl(table.ownerDocument, onPlayAudio
        ? (callbacks) => onPlayAudio(item.id, callbacks) : null, 'Hear word') || '—'),
      cell(node('div', {}, [
        statusPill(knowledgeLabel(item.knowledgeStatus), stateTone(item.knowledgeStatus)),
        node('div', { text: dispositionLabel(item.disposition), attrs: { title: 'Disposition' } }),
      ])),
      cell(ankiCell(ankiStatus, item.id)),
      cell(node('span', { className: 'language-scoreline', text: `${scoreLabel(item.recognition)} / ${scoreLabel(item.recall)} / ${scoreLabel(item.production)}` })),
      cell(String(item.formsCount)),
      cell(String(item.totalExposures)),
      cell(item.frequencyScore == null
        ? '—'
        : node('span', { text: item.frequencyScore.toFixed(2), attrs: { title: `${item.frequencyProviderId || 'Provider'} Zipf frequency score; not an exact rank` } })),
      cell(formatLanguageDate(item.lastSeenAt)),
    ]));
  });
  table.append(head, body);
  return node('div', { className: 'language-table-wrap' }, table);
}

export function createVocabularyView(mount, state, handlers) {
  let inspector = null;
  const search = node('input', {
    type: 'search',
    value: state.query,
    placeholder: 'Lemma or surface form…',
    attrs: { autocomplete: 'off', 'data-language-search': '' },
  });
  const knowledge = selectControl('knowledgeStatus', [
    { value: '', label: 'All knowledge states' },
    ...KNOWLEDGE_STATUSES.map((value) => ({ value, label: knowledgeLabel(value) })),
  ], state.knowledgeStatus);
  knowledge.setAttribute('data-language-knowledge-filter', '');
  const disposition = selectControl('disposition', [
    { value: '', label: 'All dispositions' },
    ...DISPOSITIONS.map((value) => ({ value, label: dispositionLabel(value) })),
  ], state.disposition);
  disposition.setAttribute('data-language-disposition-filter', '');

  search.addEventListener('input', () => handlers.onQuery(search.value));
  knowledge.addEventListener('change', () => handlers.onKnowledgeStatus(knowledge.value));
  disposition.addEventListener('change', () => handlers.onDisposition(disposition.value));

  const toolbar = node('form', { className: 'language-vocabulary-toolbar', attrs: { role: 'search' } }, [
    field('Search vocabulary', search),
    field('Knowledge', knowledge),
    field('Disposition', disposition),
  ]);
  toolbar.addEventListener('submit', (event) => {
    event.preventDefault();
    handlers.onQuery(search.value, { immediate: true });
  });
  const meta = node('div', { className: 'language-results-meta', attrs: { 'aria-live': 'polite' } });
  const results = node('div', { attrs: { 'data-language-results': '' } });
  const guide = node('details', { className: 'language-vocabulary-guide' }, [
    node('summary', { text: 'How to read this table' }),
    node('p', { text: 'Each row is one dictionary word. Hover over or focus a column heading for its explanation. Vocabulary knowledge and Anki card queue answer different questions.' }),
    node('dl', {}, Object.entries(COLUMN_HELP).flatMap(([label, explanation]) => [node('dt', { text: label }), node('dd', { text: explanation })])),
  ]);
  const root = node('section', { className: 'language-section' }, [toolbar, guide, meta, results]);
  replace(mount, root);

  function update(nextState) {
    inspector?.destroy(); inspector = null;
    const itemCount = nextState.items.length;
    meta.textContent = nextState.loading && itemCount === 0
      ? 'Loading vocabulary…'
      : `${itemCount} shown · ${nextState.total} total${nextState.ankiStatus?.status === 'CURRENT' ? ` · Anki checked ${formatLanguageDate(nextState.ankiStatus.observedAt)}` : ''}`;
    root.setAttribute('aria-busy', nextState.loading || nextState.loadingMore ? 'true' : 'false');
    if (nextState.error && itemCount === 0) {
      replace(results, messageState('error', 'Vocabulary could not be loaded.', nextState.error));
      return;
    }
    if (nextState.loading && itemCount === 0) {
      replace(results, messageState('loading', 'Loading vocabulary…'));
      return;
    }
    if (itemCount === 0) {
      replace(results, messageState('empty', 'No vocabulary matches these filters.', 'Try a different search or filter.'));
      return;
    }
    const table = vocabularyTable(nextState.items, nextState.ankiStatus, handlers.onOpenLemma,
      handlers.onPlayAudio, Boolean(handlers.onPreviewLemma));
    const more = node('button', {
      className: 'language-button',
      type: 'button',
      text: nextState.loadingMore ? 'Loading…' : 'Load more',
      disabled: nextState.loadingMore || !nextState.nextCursor,
      dataset: { languageLoadMore: '' },
    });
    more.addEventListener('click', handlers.onLoadMore);
    const pagination = node('div', { className: 'language-pagination' }, [
      node('span', { text: nextState.nextCursor ? `Showing ${itemCount} of ${nextState.total}` : `All ${nextState.total} matching lemmas shown` }),
      more,
    ]);
    const blocks = [table, pagination];
    if (nextState.error) blocks.unshift(node('p', { className: 'language-inline-error', text: nextState.error }));
    replace(results, ...blocks);
    if (handlers.onPreviewLemma) inspector = createLexicalInspector({
      root: results,
      tokens: nextState.items.map((item) => ({ id: item.id, sourceStart: 0, sourceEnd: [...String(item.lemmaDisplay || '')].length })),
      preview: handlers.onPreviewLemma, updateStatus: handlers.onUpdateKnowledge,
      playWordAudio: handlers.onPlayAudio,
      detailLookup: handlers.onLexicalDetail,
      openFull: (lemmaId) => handlers.onOpenLemma(lemmaId),
      documentRef: mount.ownerDocument, windowRef: mount.ownerDocument.defaultView,
    });
  }

  update(state);
  return { update, search, destroy() { inspector?.destroy(); } };
}
