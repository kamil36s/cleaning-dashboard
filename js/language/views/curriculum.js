import { messageState, node, replace, statusPill } from '../components/dom.js';

function meter(progress, label) {
  return node('div', { className: 'language-curriculum-meter' }, [
    node('progress', { value: Number(progress) || 0, attrs: { max: 100, 'aria-label': label } }),
    node('span', { text: label }),
  ]);
}

function countLine(progress) {
  return `Source ${progress.sourceItemTotal} · approved ${progress.approvedTotal} · mapped ${progress.mappedTotal} · ambiguous ${progress.ambiguousTotal} · unresolved ${progress.unresolvedTotal} · excluded ${progress.excludedTotal} · eligible ${progress.eligibleDenominator}`;
}

function packCard(pack, onOpenPack) {
  const progress = pack.progress;
  const open = node('button', {
    className: 'language-button is-primary', type: 'button', text: 'Open pack',
    attrs: { 'aria-label': `Open ${pack.name}, version ${pack.version}` },
  });
  open.addEventListener('click', () => onOpenPack?.(pack.id, pack.version));
  return node('article', { className: 'language-card language-curriculum-card' }, [
    node('p', { className: 'language-kicker', text: `${pack.category} · VERSION ${pack.version}` }),
    node('h3', { text: pack.name }),
    node('p', { text: pack.description }),
    meter(progress.progressPercent, `${progress.completed} of ${progress.eligibleDenominator} acquired · ${progress.progressPercent}%`),
    node('details', { className: 'language-technical-details' }, [
      node('summary', { text: 'Sources and pack diagnostics' }),
      node('small', { text: countLine(progress) }),
      node('small', { text: `${pack.source.name} · ${pack.source.version} · ${pack.source.license}` }),
    ]),
    open,
  ]);
}

export function renderCurriculumLanding(mount, state, { onOpenPack } = {}) {
  if (state.loading && !state.landing) return replace(mount, messageState('loading', 'Loading curated curriculum packs…'));
  if (state.error) return replace(mount, messageState('error', 'Curriculum is unavailable.', state.error));
  const data = state.landing;
  if (!data) return replace(mount, messageState('empty', 'No curriculum catalog is available.'));
  const packs = data.packs || [];
  const unavailable = data.unavailablePacks || [];
  replace(mount, node('div', { className: 'language-curriculum-view' }, [
    node('section', { className: 'language-card language-curriculum-intro' }, [
      node('p', { className: 'language-kicker', text: 'PRACTICAL PACKS' }),
      node('h3', { text: 'Choose a topic to study' }),
      node('p', { text: 'These packs use reviewed, versioned source membership. Browsing does not add words to your vocabulary.' }),
      node('details', { className: 'language-technical-details' }, [
        node('summary', { text: 'Technical details' }),
        node('p', { text: `${data.policyVersion} · ${data.boundaries?.proficiency || ''}` }),
      ]),
    ]),
    packs.length
      ? node('section', { className: 'language-curriculum-grid' }, packs.map((pack) => packCard(pack, onOpenPack)))
      : messageState('empty', 'No active reviewed packs are available.'),
    node('details', { className: 'language-card language-curriculum-unavailable' }, [
      node('summary', { text: `Audited packs not yet available (${unavailable.length})` }),
      node('div', { className: 'language-curriculum-unavailable-list' }, unavailable.map((item) => node('article', {}, [
        node('strong', { text: item.name }),
        statusPill(item.status, 'muted'),
        node('p', { text: item.reason }),
      ]))),
    ]),
  ]));
}

function itemMatches(item, query, filter) {
  const text = `${item.displayTerm} ${item.normalizedLookup}`.toLocaleLowerCase('nb-NO');
  const queryMatch = !query || text.includes(query.toLocaleLowerCase('nb-NO'));
  return queryMatch && (!filter || item.user?.state === filter);
}

function curriculumItem(item, onOpenItem) {
  const userState = item.user?.state || 'NOT_ELIGIBLE';
  const button = node('button', {
    className: 'language-curriculum-item-button', type: 'button',
    attrs: { 'aria-label': `Open lexical detail for ${item.displayTerm}` },
  }, [
    node('span', {}, [
      node('strong', { text: item.displayTerm }),
      node('small', { text: item.referenceUnit?.partOfSpeech || item.mappingState }),
    ]),
    node('span', { className: 'language-curriculum-item-status' }, [
      statusPill(userState.replaceAll('_', ' '), item.user?.acquired ? 'success' : 'muted'),
      statusPill(item.mappingState, item.mappingState === 'MAPPED' ? 'ready' : item.mappingState === 'AMBIGUOUS' ? 'warning' : 'muted'),
    ]),
  ]);
  button.addEventListener('click', () => onOpenItem?.(item));
  return node('li', {}, [button]);
}

export function renderCurriculumPack(mount, state, {
  onBack, onQuery, onStateFilter, onOpenItem,
} = {}) {
  if (state.loading && !state.pack) return replace(mount, messageState('loading', 'Loading curriculum pack…'));
  if (state.error) return replace(mount, messageState('error', 'Curriculum pack is unavailable.', state.error));
  const pack = state.pack;
  if (!pack) return replace(mount, messageState('empty', 'No curriculum pack is selected.'));
  const progress = pack.progress;
  const search = node('input', {
    type: 'search', placeholder: 'Search this pack…', value: state.query,
    attrs: { 'aria-label': 'Search curriculum terms', autocomplete: 'off' },
  });
  search.addEventListener('input', () => onQuery?.(search.value));
  const filter = node('select', { attrs: { 'aria-label': 'Filter by learning state' } }, [
    ['ALL', 'All states'], ['UNSEEN', 'Unseen'], ['NEW', 'New'], ['LEARNING', 'Learning'],
    ['KNOWN', 'Known'], ['MASTERED', 'Mastered'],
  ].map(([value, label]) => node('option', { value, text: label })));
  filter.value = state.stateFilter || 'ALL';
  filter.addEventListener('change', () => onStateFilter?.(filter.value === 'ALL' ? '' : filter.value));
  const items = (progress.items || []).filter((item) => itemMatches(item, state.query, state.stateFilter));
  const back = node('button', { className: 'language-button', type: 'button', text: 'Back to curriculum' });
  back.addEventListener('click', () => onBack?.());
  replace(mount, node('div', { className: 'language-curriculum-view' }, [
    node('section', { className: 'language-card language-curriculum-pack-head' }, [
      back,
      node('p', { className: 'language-kicker', text: `${pack.category} · VERSION ${pack.version} · ${pack.status}` }),
      node('h3', { text: pack.name }),
      node('p', { text: pack.description }),
      meter(progress.progressPercent, `${progress.completed} of ${progress.eligibleDenominator} acquired · ${progress.progressPercent}%`),
      node('p', { className: 'language-definition', text: progress.completionSemantics }),
      node('small', { text: countLine(progress) }),
      node('details', { className: 'language-evidence' }, [
        node('summary', { text: 'Source, membership and mapping snapshot' }),
        node('p', { text: `${pack.source.name} · ${pack.source.provider} · ${pack.source.version} · ${pack.source.license}` }),
        node('p', { text: pack.source.membershipBasis }),
        node('p', { text: `Pack ${pack.fingerprint} · reference ${pack.mappingSnapshot.referenceFingerprint}` }),
      ]),
    ]),
    node('section', { className: 'language-card language-curriculum-list-card' }, [
      node('div', { className: 'language-curriculum-controls' }, [search, filter]),
      node('p', { attrs: { role: 'status', 'aria-live': 'polite' }, text: `${items.length} of ${progress.items?.length || 0} source items shown` }),
      items.length
        ? node('ul', { className: 'language-curriculum-items' }, items.map((item) => curriculumItem(item, onOpenItem)))
        : messageState('empty', 'No terms match these filters.'),
    ]),
  ]));
}
