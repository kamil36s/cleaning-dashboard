import { formatLanguageDate } from '../model.js';
import { definitionList, messageState, node, replace, statusPill } from '../components/dom.js';
import { renderAnkiInsights } from './anki-insights.js';

function tone(status) {
  if (status === 'CONNECTED') return 'success';
  if (status === 'PARTIALLY_CONFIGURED' || status === 'VERSION_UNSUPPORTED') return 'warning';
  return 'muted';
}

function categoryLabel(value) {
  return String(value || '').replaceAll('_', ' ').toLowerCase();
}

function mistakeCard(item, onMistakeDetail) {
  const detail = node('div', { className: 'language-mistake-detail', attrs: { role: 'status' }, hidden: true });
  const button = node('button', {
    className: 'language-button is-quiet', type: 'button', text: 'Details',
    attrs: { 'aria-expanded': 'false', 'aria-controls': `mistake-${item.id}` },
  });
  detail.id = `mistake-${item.id}`;
  button.addEventListener('click', async () => {
    if (!detail.hidden) {
      detail.hidden = true; button.setAttribute('aria-expanded', 'false'); return;
    }
    detail.hidden = false; button.disabled = true; detail.textContent = 'Loading attributable evidence...';
    try {
      const result = await onMistakeDetail(item.id);
      const cluster = result.cluster;
      detail.replaceChildren(...[
        node('p', { className: 'language-definition', text: cluster.explanation }),
        node('ol', { className: 'language-mistake-evidence' }, (cluster.evidence || []).map((evidence) => node('li', {}, [
          node('strong', { text: `${evidence.outcome} / ${formatLanguageDate(evidence.attemptedAt)}` }),
          node('span', { text: `${evidence.questionType} / expected ${evidence.expectedSurface}${evidence.userAnswer ? ` / supplied ${evidence.userAnswer}` : ''}` }),
          node('small', { text: `${evidence.sourceContextType} / ${evidence.sentenceId || 'source retained'}` }),
        ]))),
        cluster.evidenceTruncated ? node('p', { className: 'language-definition', text: 'Only the 50 most recent evidence rows are shown.' }) : null,
      ].filter(Boolean));
      button.setAttribute('aria-expanded', 'true');
    } catch (error) {
      detail.textContent = error?.message || 'Mistake evidence could not be loaded.';
    } finally {
      button.disabled = false;
    }
  });
  return node('article', { className: 'language-form-card language-mistake-card' }, [
    node('header', {}, [
      node('strong', { text: item.target?.lemma || item.title }),
      statusPill(`${item.severity} / ${item.state}`, item.severity === 'HIGH' ? 'warning' : 'muted'),
    ]),
    node('p', { text: item.title }),
    node('p', { className: 'language-definition', text: `${categoryLabel(item.category)} / ${item.historicalFailureCount} qualifying failures / ${item.laterSuccessCount} later successes` }),
    node('div', { className: 'language-form-actions' }, [
      node('a', { className: 'language-button is-primary', text: 'Practice', attrs: { href: '#cloze' } }), button,
    ]),
    detail,
  ]);
}

export function renderReviews(mount, state, { onPull, onRefresh, onSyncWeb = async () => {}, onBrowseCards = async () => {}, onSelectDeck = async () => {}, onMistakeDetail = async () => ({ cluster: { evidence: [] } }) }) {
  if (state.loading && !state.status && !state.cloze) {
    replace(mount, messageState('loading', 'Loading Anki and Cloze review status...'));
    return;
  }
  const status = state.status || { status: 'NOT_CONFIGURED' };
  const cloze = state.cloze || { summary: {} };
  const mistakes = state.mistakes?.summary || null;
  const canPull = status.status === 'CONNECTED';
  const canSyncWeb = Boolean(status.config?.enabled && status.config?.deckName && status.connection?.supported);
  const pull = node('button', { className: 'language-button is-primary', type: 'button', text: 'Pull card metadata', disabled: !canPull });
  const syncWeb = node('button', { className: 'language-button', type: 'button', text: 'Sync AnkiWeb now', disabled: !canSyncWeb });
  const refresh = node('button', { className: 'language-button', type: 'button', text: 'Refresh status' });
  const feedback = node('p', { className: 'language-form-error', attrs: { role: 'status' }, hidden: true });
  pull.addEventListener('click', async () => {
    pull.disabled = true;
    feedback.hidden = false;
    feedback.textContent = 'Pulling read-only card metadata...';
    try {
      const result = await onPull();
      feedback.textContent = `Pull ${String(result.run?.status || 'completed').toLowerCase()}: ${result.run?.counts?.succeeded || 0} linked notes observed.`;
    } catch (error) {
      feedback.textContent = error?.message || 'Metadata pull failed.';
    } finally {
      pull.disabled = !canPull;
    }
  });
  syncWeb.addEventListener('click', async () => {
    syncWeb.disabled = true;
    feedback.hidden = false;
    feedback.textContent = 'Syncing desktop Anki with AnkiWeb...';
    try {
      await onSyncWeb();
      feedback.textContent = 'AnkiWeb sync finished. Deck counts refreshed.';
    } catch (error) {
      feedback.textContent = error?.message || 'AnkiWeb sync failed.';
    } finally {
      syncWeb.disabled = !canSyncWeb;
    }
  });
  refresh.addEventListener('click', onRefresh);
  const summary = node('section', { className: 'language-card language-settings-card is-wide', attrs: { 'data-review-kind': 'ANKI_DUE' } }, [
    node('p', { className: 'language-kicker', text: 'ANKI SCHEDULED' }),
    node('h3', { text: 'Anki remains the scheduler' }),
    node('p', { text: 'Anki answers update safely matched Reader words. Reader status changes add dashboard_status_* tags to those Anki notes; Anki still owns due dates and intervals.' }),
    statusPill(status.status, tone(status.status)),
    status.deck ? node('p', { className: 'language-definition', text: `Selected deck: ${status.deck.name}` }) : null,
    definitionList([
      ['Due cards', status.dueCount == null ? 'Not observed' : status.dueCount],
      ...(status.deck ? [
        ['New available', status.deck.new],
        ['Learning', status.deck.learn],
        ['Distinct cards answered today', status.deck.answeredCardsToday],
        ['Observed', formatLanguageDate(status.deck.observedAt)],
      ] : []),
      ['Linked vocabulary', status.linkedVocabulary ?? 0],
      ['Conflicts', status.conflicts ?? 0],
      ['Last AnkiWeb sync from dashboard', formatLanguageDate(status.lastWebSyncAt)],
    ], 'language-evidence'),
    node('p', { className: 'language-definition', text: 'Phone reviews appear after the phone syncs to AnkiWeb and this computer syncs. Anki Desktop must remain open.' }),
    node('div', { className: 'language-form-actions' }, [syncWeb, pull, refresh, feedback]),
    state.error ? node('p', { className: 'language-form-error', text: state.error }) : null,
  ]);
  const clozeCard = node('section', { className: 'language-card language-settings-card is-wide', attrs: { 'data-review-kind': 'CLOZE_PRACTICE' } }, [
    node('p', { className: 'language-kicker', text: 'CLOZE PRACTICE · DASHBOARD QUEUE' }),
    node('h3', { text: 'Shared-context and Fast Track practice' }),
    node('p', { text: 'Reader, Phrasebook, accepted generated, curriculum, and Tatoeba contexts produce practice evidence only. They never create Anki due dates.' }),
    definitionList([
      ['Attempts', cloze.summary?.attempts || 0],
      ['Mistake targets', cloze.summary?.mistakeTargets || 0],
      ['Encountered targets', cloze.summary?.encounteredTargets || 0],
      ['Accuracy', cloze.summary?.accuracy == null ? 'Not yet available' : `${cloze.summary.accuracy}%`],
      ['Shared-context targets', cloze.practiceModes?.review?.targetCount || 0],
    ], 'language-evidence'),
    node('div', { className: 'language-form-actions' }, [
      node('a', { className: 'language-button is-primary', text: 'Open Cloze practice', attrs: { href: '#cloze' } }),
    ]),
  ]);
  const recycle = node('section', { className: 'language-card language-settings-card', attrs: { 'data-review-kind': 'CLOZE_RECYCLE' } }, [
    node('p', { className: 'language-kicker', text: 'CLOZE RECYCLE · DASHBOARD QUEUE' }),
    node('h3', { text: `${cloze.summary?.mistakeTargets || 0} mistake targets` }),
    node('p', { text: 'Replays dashboard Cloze mistakes deterministically. It is not spaced repetition and does not alter the Anki schedule.' }),
    node('a', { className: 'language-button', text: 'Recycle Cloze mistakes', attrs: { href: '#cloze' } }),
  ]);
  const reader = node('section', { className: 'language-card language-settings-card', attrs: { 'data-review-kind': 'READER_REVISIT' } }, [
    node('p', { className: 'language-kicker', text: 'READER REVISIT · DASHBOARD QUEUE' }),
    node('h3', { text: 'Revisit analyzed text' }),
    node('p', { text: 'Return to saved Reader documents and their exact analyzed token spans. Reader revisit has no independent scheduler.' }),
    node('a', { className: 'language-button', text: 'Open Reader', attrs: { href: '#reader' } }),
  ]);
  const listening = node('section', { className: 'language-card language-settings-card', attrs: { 'data-review-kind': 'LISTENING_PRACTICE' } }, [
    node('p', { className: 'language-kicker', text: 'LISTENING PRACTICE · DASHBOARD RECOMMENDATION' }),
    node('h3', { text: 'Continue listening' }),
    node('p', { text: 'Resume an analyzed text from canonical Listening progress. This is not SRS due work and does not change Anki scheduling.' }),
    node('a', { className: 'language-button', text: 'Open Listening', attrs: { href: '#listening' } }),
  ]);
  const curriculum = node('section', { className: 'language-card language-settings-card', attrs: { 'data-review-kind': 'CURRICULUM_PRACTICE' } }, [
    node('p', { className: 'language-kicker', text: 'CURRICULUM PRACTICE · DASHBOARD QUEUE' }),
    node('h3', { text: `${cloze.practiceModes?.curriculum?.packs?.length || 0} versioned packs` }),
    node('p', { text: 'Practice an approved pack version with its identity frozen into the session snapshot. This is evidence, not mastery.' }),
    node('a', { className: 'language-button', text: 'Choose a curriculum pack', attrs: { href: '#cloze' } }),
  ]);
  const needsAttention = node('section', { className: 'language-card language-settings-card is-wide', attrs: { 'data-review-kind': 'MISTAKE_REMEDIATION' } }, [
    node('p', { className: 'language-kicker', text: 'MISTAKE INTELLIGENCE / DIAGNOSTIC' }),
    node('h3', { text: 'Needs attention' }),
    node('p', { text: 'Only repeated canonical failures form a cluster. Severity and state are written labels, not color-only signals.' }),
    mistakes?.topProblems?.length
      ? node('div', { className: 'language-forms language-mistake-list' }, mistakes.topProblems.map((item) => mistakeCard(item, onMistakeDetail)))
      : node('p', { className: 'language-empty-copy', text: 'No established mistake cluster currently needs remediation.' }),
    mistakes ? definitionList([
      ['Current problem clusters', mistakes.activeClusterCount || 0],
      ['Historical incorrect attempts', mistakes.historicalIncorrectCount || 0],
      ['Anki mistake events', mistakes.sourceAvailability?.ankiReviewHistory || 'NOT_SUPPORTED'],
    ], 'language-evidence') : null,
  ]);
  const recoveries = node('section', { className: 'language-card language-settings-card is-wide', attrs: { 'data-review-kind': 'MISTAKE_RECOVERIES' } }, [
    node('p', { className: 'language-kicker', text: 'RECOVERY / HISTORY PRESERVED' }),
    node('h3', { text: 'Recent recoveries' }),
    mistakes?.recentRecoveries?.length
      ? node('div', { className: 'language-forms' }, mistakes.recentRecoveries.map((item) => node('article', { className: 'language-form-card' }, [
        node('strong', { text: item.target?.lemma || item.title }),
        node('span', { text: `${item.state} / ${item.laterSuccessCount} later successes across ${item.laterSuccessDates} dates` }),
      ])))
      : node('p', { className: 'language-empty-copy', text: 'No cluster has reached the versioned recovered state yet.' }),
  ]);
  const runs = node('section', { className: 'language-card language-settings-card is-wide' }, [
    node('p', { className: 'language-kicker', text: 'RECENT SYNC RUNS' }),
    state.runs?.length
      ? node('div', { className: 'language-forms' }, state.runs.map((run) => node('article', { className: 'language-form-card' }, [
        node('strong', { text: `${run.mode} / ${run.status}` }),
        node('span', { text: formatLanguageDate(run.completedAt || run.startedAt) }),
        node('small', { text: `${run.counts?.succeeded || 0} succeeded / ${run.counts?.failed || 0} failed` }),
      ])))
      : node('p', { className: 'language-empty-copy', text: 'No explicit Anki sync has run.' }),
  ]);
  replace(mount, node('div', { className: 'language-reviews-view' }, [
    node('section', {}, [node('h3', { text: 'Today' }), state.insights ? renderAnkiInsights(state.insights, { onBrowseCards, onSelectDeck }) : null,
      state.insightsError ? node('p', { className: 'language-form-error', text: state.insightsError }) : null,
      node('div', { className: 'language-settings-grid' }, [summary, clozeCard])]),
    node('section', {}, [node('h3', { text: 'Needs attention' }), node('div', { className: 'language-settings-grid' }, [needsAttention, recycle])]),
    node('details', { className: 'language-reviews-secondary' }, [
      node('summary', { text: 'More practice and history' }),
      node('div', { className: 'language-settings-grid' }, [reader, listening, curriculum, recoveries, runs]),
    ]),
  ]));
}
