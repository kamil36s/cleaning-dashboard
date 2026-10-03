import { node } from '../components/dom.js';

const ratingNames = { 1: 'Again', 2: 'Hard', 3: 'Good', 4: 'Easy' };

function metric(label, value, note = '') {
  return node('div', { className: 'language-anki-insight-metric' }, [
    node('span', { text: label }), node('strong', { text: value ?? '—' }),
    note ? node('small', { text: note }) : null,
  ].filter(Boolean));
}

function materialProgress(counts) {
  const categories = [
    ['mature', 'Mature', 'Cards with interval ≥ 21 days'],
    ['learningYoung', 'Learning / Young', 'Cards currently being learned or with shorter intervals'],
    ['unseen', 'Unseen', 'Cards not studied yet'],
    ['suspended', 'Suspended', 'Cards excluded from study'],
  ].map(([key, label, description]) => ({
    key, label, description, count: Math.max(0, Number(counts[key]) || 0),
  }));
  const total = categories.reduce((sum, item) => sum + item.count, 0);
  const exact = categories.map((item) => total ? item.count * 100 / total : 0);
  const rounded = exact.map(Math.floor);
  const remainderOrder = exact.map((value, index) => ({ index, fraction: value - rounded[index] }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
  const missing = total ? 100 - rounded.reduce((sum, value) => sum + value, 0) : 0;
  for (let i = 0; i < missing; i++) {
    rounded[remainderOrder[i].index] += 1;
  }
  const visible = categories.filter((item) => item.key !== 'suspended' || item.count);
  const bar = node('div', { className: 'language-anki-material-bar', attrs: {
    role: 'img', 'aria-label': visible.map((item) => `${item.label}: ${item.count} cards`).join(', '),
  } });
  visible.forEach((item) => {
    if (!item.count) return;
    const segment = node('div', { className: `language-anki-material-segment is-${item.key}` }, [
      node('span', { className: 'language-anki-material-segment-label', text: `${rounded[categories.indexOf(item)]}%` }),
    ]);
    segment.style.flexGrow = String(item.count);
    bar.append(segment);
  });
  const legend = node('div', { className: 'language-anki-material-legend' }, visible.map((item) =>
    node('div', { className: 'language-anki-material-row' }, [
      node('span', { className: `language-anki-material-name is-${item.key}` }, [
        node('i', { attrs: { 'aria-hidden': 'true' } }), node('span', { text: item.label }),
      ]),
      node('strong', { className: 'language-anki-material-count', text: item.count }),
      node('strong', { className: 'language-anki-material-percent', text: `${rounded[categories.indexOf(item)]}%` }),
      node('span', { className: 'language-anki-material-description', text: item.description }),
    ])));
  return node('section', { className: 'language-anki-material' }, [
    node('h4', { text: 'Progress through material' }), bar, legend,
  ]);
}

function bars(items, key, { className = '' } = {}) {
  const max = Math.max(1, ...items.map((item) => Number(item[key] || 0)));
  const labelStep = items.length > 20 ? 5 : 2;
  return node('div', { className: `language-anki-bars ${className}` }, items.map((item, index) => {
    const value = Number(item[key] || 0);
    const bar = node('span', { className: 'language-anki-bar-fill' });
    bar.style.height = `${Math.max(value ? 5 : 1, value / max * 100)}%`;
    const label = item.date?.slice(5) || '';
    return node('div', { className: 'language-anki-bar', attrs: {
      title: `${item.date}: ${value}`, 'aria-label': `${item.date}: ${value}`,
    } }, [bar, index % labelStep === 0 || index === items.length - 1 ? node('small', { text: label }) : null].filter(Boolean));
  }));
}

function cardRow(item) {
  const due = item.state === 'NEW' ? 'New queue'
    : item.dueOffset == null ? '—'
      : item.dueOffset < 0 ? `${Math.abs(item.dueOffset)}d overdue`
        : item.dueOffset === 0 ? 'Today' : `In ${item.dueOffset}d`;
  return node('tr', {}, [
    node('td', { text: item.front || '—' }),
    node('td', { text: item.back || '—' }),
    node('td', { text: item.state }),
    node('td', {}, [node('strong', { text: `${item.knowledge.status} · ${item.knowledge.score}/100` }),
      node('small', { text: ` ${item.knowledge.reviewCount} answers · last ${ratingNames[item.knowledge.lastRating] || '—'}` })]),
    node('td', { text: item.lemma ? `${item.lemma.display}: ${item.lemma.knowledgeStatus}${item.lemma.manualOverride ? ' (manual)' : ''}` : 'No safe word match' }),
    node('td', { text: due }),
  ]);
}

export function renderAnkiInsights(insights, { onBrowseCards = async () => {}, onSelectDeck = async () => {} } = {}) {
  if (!insights) return null;
  const today = insights.today;
  const inventory = insights.inventory;
  const history = insights.history || [];
  const forecast = insights.forecast || [];
  const page = insights.cards || { items: [], total: 0, offset: 0, limit: 50, query: '' };
  const root = node('section', { className: 'language-card language-anki-insights' }, [
    node('p', { className: 'language-kicker', text: 'ANKI · SELECTED DECK' }),
    node('h3', { text: insights.deckName }),
    node('p', { className: 'language-definition', text: `${inventory.totalCards} cards · ${inventory.matchedVocabularyCards} safely matched to Reader Vocabulary · ${inventory.newRemaining} new cards remain` }),
    node('div', { className: 'language-anki-insight-metrics' }, [
      metric('New today', today.new), metric('Learning', today.learning),
      metric('Reviews due today', today.reviewsDue), metric('New studied today', today.newIntroduced),
      metric('Review answers today', today.reviewAnswers), metric('All answers today', today.answered),
    ]),
  ]);
  if ((insights.availableDecks || []).length > 1) {
    const deckSelect = node('select', { attrs: { 'aria-label': 'Anki deck statistics' } },
      insights.availableDecks.map((name) => node('option', { text: name, value: name })));
    deckSelect.value = insights.deckName;
    deckSelect.addEventListener('change', () => onSelectDeck(deckSelect.value));
    root.append(node('label', { className: 'language-anki-deck-selector' }, [
      node('span', { text: 'Deck statistics' }), deckSelect,
    ]));
  }
  if (inventory.materialProgress) root.append(materialProgress(inventory.materialProgress));
  const grids = node('div', { className: 'language-anki-insight-grids' }, [
    node('section', {}, [
      node('h4', { text: 'New cards introduced · last 30 days' }),
      bars(history, 'newIntroduced', { className: 'is-new' }),
      node('h4', { text: 'Review answers · last 30 days' }),
      bars(history, 'reviewAnswers'),
      node('p', { className: 'language-definition', text: `Today: ${today.again} Again · ${today.hard} Hard · ${today.good} Good · ${today.easy} Easy. Bars count answers, so one card may count more than once.` }),
    ]),
    node('section', {}, [
      node('h4', { text: 'Scheduled reviews · next 14 days' }),
      bars(forecast, 'scheduledReviews', { className: 'is-forecast' }),
      node('h4', { text: 'Possible new cards · next 14 days' }),
      bars(forecast, 'possibleNew', { className: 'is-new' }),
      node('p', { className: 'language-definition', text: `New-card limit: ${insights.limits.newPerDay}/day. Possible new cards are not fixed appointments; review limit: ${insights.limits.reviewsPerDay}/day.` }),
    ]),
  ]);
  root.append(grids);
  const table = node('table', { className: 'language-anki-card-table' }, [
    node('thead', {}, [node('tr', {}, ['Front', 'Back', 'Anki queue', 'Estimated knowledge', 'Reader Vocabulary', 'Due'].map((label) => node('th', { text: label })))]),
    node('tbody', {}, page.items.length ? page.items.map(cardRow) : [node('tr', {}, [node('td', { text: 'No cards match this search.', attrs: { colspan: '6' } })])]),
  ]);
  const search = node('input', { type: 'search', attrs: { 'aria-label': 'Search selected Anki deck', placeholder: 'Search front or back', value: page.query || '' } });
  search.value = page.query || '';
  const form = node('form', { className: 'language-anki-card-search' }, [
    search, node('button', { className: 'language-button', type: 'submit', text: 'Search cards' }),
  ]);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    await onBrowseCards(search.value.trim(), 0);
  });
  const previous = node('button', { className: 'language-button', type: 'button', text: 'Previous', disabled: page.offset <= 0 });
  const next = node('button', { className: 'language-button', type: 'button', text: 'Next', disabled: page.offset + page.limit >= page.total });
  previous.addEventListener('click', () => onBrowseCards(page.query || '', Math.max(0, page.offset - page.limit)));
  next.addEventListener('click', () => onBrowseCards(page.query || '', page.offset + page.limit));
  root.append(node('section', { className: 'language-anki-catalog' }, [
    node('h4', { text: 'All cards in this deck' }),
    node('p', { className: 'language-definition', text: 'Knowledge is a versioned estimate from Anki answers and intervals. Reader manual knowledge remains explicit.' }),
    form, node('div', { className: 'language-anki-card-table-wrap' }, [table]),
    node('div', { className: 'language-anki-catalog-pages' }, [
      previous, node('span', { text: `${page.total ? page.offset + 1 : 0}–${Math.min(page.total, page.offset + page.limit)} of ${page.total}` }), next,
    ]),
  ]));
  return root;
}
