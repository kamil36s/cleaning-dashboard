import { codePointOffsetToUtf16Index, codePointRangeToUtf16Range } from '../model.js';
import { definitionList, field, messageState, node, replace, statusPill } from '../components/dom.js';
import { createLexicalInspector } from '../components/lexical-inspector.js';
import { createGuidedReader } from '../components/guided-reader.js';
import { buildReaderStudyPrompt, parseReaderStudyResponse } from '../reader-study-pack.js';

const TERMINAL_JOB_STATES = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);

function dateLabel(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function percent(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function duration(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function wordBreakdown(coverage) {
  const known = Math.max(0, Number(coverage.coveredTokens || 0) - Number(coverage.ignoredTokens || 0));
  const learning = Math.max(0, Number(coverage.learningTokens || 0));
  const newWords = Math.max(0, Number(coverage.unknownTokens || 0));
  const total = known + learning + newWords;
  return { known, learning, newWords, total };
}

function sourceLabel(sourceType) {
  if (String(sourceType || '').startsWith('GENERATED_')) return 'Generated text';
  if (sourceType === 'PASTED') return 'Added by you';
  return 'Saved text';
}

function readingLabel(status) {
  return { IN_PROGRESS: 'Reading in progress', COMPLETED: 'Finished', NOT_STARTED: 'Not started' }[status] || 'Not started';
}

function analysisLabel(job) {
  if (job.state === 'FAILED') return 'Analysis failed';
  if (job.state === 'CANCELLED') return 'Analysis cancelled';
  if (job.state === 'COMPLETED') return 'Analysis complete';
  if (job.state === 'QUEUED') return 'Waiting for analysis';
  if (job.state === 'RUNNING') return 'Analyzing text';
  return 'Analysis pending';
}

function wordBreakdownView(coverage) {
  const { known, learning, newWords, total } = wordBreakdown(coverage);
  if (!total) return node('p', { className: 'language-reader-breakdown-empty', text: 'No words with a clear status to show yet.' });
  const parts = [
    ['known', 'Known', known],
    ['learning', 'Learning', learning],
    ['new', 'New', newWords],
  ];
  const omitted = Number(coverage.ignoredTokens || 0) + Number(coverage.ambiguousTokens || 0) + Number(coverage.excludedTokens || 0);
  return node('div', { className: 'language-reader-breakdown' }, [
    node('div', { className: 'language-reader-breakdown-stats' }, parts.map(([tone, label, count]) =>
      node('div', { className: `language-reader-breakdown-stat is-${tone}` }, [
        node('strong', { text: percent((count / total) * 100) }),
        node('span', { text: `${label} · ${count}` }),
      ]))),
    node('div', { className: 'language-reader-breakdown-bar', attrs: { 'aria-hidden': 'true' } }, parts.map(([tone, , count]) => {
      const segment = node('span', { className: `is-${tone}` });
      segment.style.width = `${(count / total) * 100}%`;
      return segment;
    })),
    node('p', { className: 'language-reader-breakdown-note', text: `Out of ${total} words with a clear status. Repeated words count each time.${omitted ? ` ${omitted} ignored, unresolved or excluded words left out.` : ''}` }),
  ]);
}

function jobTone(state) {
  if (state === 'COMPLETED') return 'ready';
  if (state === 'FAILED' || state === 'CANCELLED') return 'error';
  return 'lazy';
}

function tokenState(token) {
  if (token.tokenKind !== 'WORD') return 'nonlexical';
  if (!token.selectedLemmaId || ['AMBIGUOUS', 'UNRESOLVED'].includes(token.resolutionState)) return 'unresolved';
  if (token.disposition === 'EXCLUDED') return 'excluded';
  if (token.disposition === 'IGNORED') return 'ignored';
  return String(token.knowledgeStatus || 'NEW').toLowerCase();
}

function learningShade(token) {
  const recognition = Number(token.recognition);
  if (!Number.isFinite(recognition) || token.recognition == null || recognition <= 1) return 1;
  return recognition <= 3 ? 2 : 3;
}

export function sentenceOccurrences(tokens, sentenceId) {
  const counts = new Map();
  (tokens || []).forEach((token) => {
    if (token.sentenceId !== sentenceId || token.tokenKind !== 'WORD' || !token.selectedLemmaId) return;
    counts.set(token.selectedLemmaId, (counts.get(token.selectedLemmaId) || 0) + 1);
  });
  return [...counts.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([lemmaId, occurrenceCount]) => ({ lemmaId, occurrenceCount }));
}

export function renderExactReaderText({
  mount,
  rawText,
  sentences = [],
  tokens = [],
  expressions = [],
  documentRef = document,
  onOpenLemma = null,
}) {
  const root = documentRef.createElement('div');
  root.className = 'language-reader-prose';
  root.setAttribute('data-reader-source', '');
  const orderedSentences = [...sentences].sort((a, b) => a.sourceStart - b.sourceStart || a.sentenceOrder - b.sentenceOrder);
  const orderedTokens = [...tokens].sort((a, b) => a.sourceStart - b.sourceStart || a.tokenOrder - b.tokenOrder);
  const tokensBySentence = new Map();
  const expressionsByToken = new Map();
  (expressions || []).forEach((expression) => {
    const start = Number(expression.startTokenOrder);
    const end = Number(expression.endTokenOrder);
    orderedTokens.forEach((token) => {
      if (token.sentenceId === expression.sentenceId && token.tokenOrder >= start && token.tokenOrder <= end) {
        if (!expressionsByToken.has(token.id)) expressionsByToken.set(token.id, []);
        expressionsByToken.get(token.id).push(expression);
      }
    });
  });
  orderedTokens.forEach((token) => {
    if (!tokensBySentence.has(token.sentenceId)) tokensBySentence.set(token.sentenceId, []);
    tokensBySentence.get(token.sentenceId).push(token);
  });
  let sourceCursor = 0;
  let firstLexicalToken = true;

  function appendCodePointSlice(parent, start, end) {
    const range = codePointRangeToUtf16Range(rawText, start, end);
    parent.append(documentRef.createTextNode(rawText.slice(range.start, range.end)));
  }

  function appendSentence(sentence, sentenceTokens) {
    const wrapper = documentRef.createElement('span');
    wrapper.className = 'language-reader-sentence';
    wrapper.dataset.sentenceId = sentence.id;
    wrapper.dataset.sentenceOrder = String(sentence.sentenceOrder ?? 0);
    wrapper.dataset.sourceEnd = String(sentence.sourceEnd);
    let cursor = sentence.sourceStart;
    sentenceTokens.forEach((token) => {
      if (token.sourceStart < cursor || token.sourceEnd > sentence.sourceEnd) return;
      appendCodePointSlice(wrapper, cursor, token.sourceStart);
      const range = codePointRangeToUtf16Range(rawText, token.sourceStart, token.sourceEnd);
      const exactSurface = rawText.slice(range.start, range.end);
      if (token.tokenKind === 'WORD') {
        const tokenNode = documentRef.createElement('button');
        tokenNode.type = 'button';
        tokenNode.tabIndex = firstLexicalToken ? 0 : -1;
        firstLexicalToken = false;
        tokenNode.className = `language-reader-token is-${tokenState(token)}`;
        if (tokenState(token) === 'learning') tokenNode.classList.add(`is-learning-level-${learningShade(token)}`);
        const tokenExpressions = expressionsByToken.get(token.id) || [];
        if (tokenExpressions.length) {
          tokenNode.classList.add('has-reference-expression');
          tokenNode.dataset.referenceExpressionCount = String(tokenExpressions.length);
        }
        tokenNode.textContent = exactSurface;
        tokenNode.dataset.tokenId = token.id;
        tokenNode.dataset.sentenceId = sentence.id;
        tokenNode.dataset.tokenState = tokenState(token);
        if (token.selectedLemmaId) tokenNode.dataset.lemmaId = token.selectedLemmaId;
        if (token.selectedLemmaDisplay) tokenNode.dataset.lemmaDisplay = token.selectedLemmaDisplay;
        tokenNode.setAttribute('aria-label', `${exactSurface}, ${tokenState(token)}`);
        wrapper.append(tokenNode);
      } else {
        wrapper.append(documentRef.createTextNode(exactSurface));
      }
      cursor = token.sourceEnd;
    });
    appendCodePointSlice(wrapper, cursor, sentence.sourceEnd);
    root.append(wrapper);
  }

  orderedSentences.forEach((sentence) => {
    if (sentence.sourceStart < sourceCursor || sentence.sourceEnd < sentence.sourceStart) return;
    appendCodePointSlice(root, sourceCursor, sentence.sourceStart);
    appendSentence(sentence, tokensBySentence.get(sentence.id) || []);
    sourceCursor = sentence.sourceEnd;
  });
  appendCodePointSlice(root, sourceCursor, [...rawText].length);
  if (onOpenLemma) root.addEventListener('click', (event) => {
    const target = event.target.closest?.('[data-lemma-id]');
    if (target && root.contains(target)) onOpenLemma(target.dataset.lemmaId, {
      tokenId: target.dataset.tokenId,
      sentenceId: target.dataset.sentenceId,
    });
  });
  replace(mount, root);
  return root;
}

export function createActiveReadingTracker({
  documentRef = document,
  windowRef = window,
  heartbeatMs = 10_000,
  onHeartbeat = () => {},
  onAutoPause = () => {},
  onAutoResume = () => {},
} = {}) {
  let active = false;
  let autoPaused = false;
  let timer = null;

  function clearHeartbeat() {
    if (timer !== null) windowRef.clearInterval(timer);
    timer = null;
  }

  function setActive(value) {
    active = Boolean(value) && documentRef.visibilityState !== 'hidden';
    clearHeartbeat();
    if (active) timer = windowRef.setInterval(() => onHeartbeat(), heartbeatMs);
  }

  function visibilityChanged() {
    if (documentRef.visibilityState === 'hidden' && active) {
      autoPaused = true;
      setActive(false);
      onAutoPause();
    } else if (documentRef.visibilityState !== 'hidden' && autoPaused) {
      autoPaused = false;
      onAutoResume();
    }
  }

  documentRef.addEventListener('visibilitychange', visibilityChanged);
  return {
    setActive,
    isActive: () => active,
    destroy() {
      clearHeartbeat();
      documentRef.removeEventListener('visibilitychange', visibilityChanged);
    },
  };
}

export function createSentenceExposureObserver({
  root,
  windowRef = window,
  IntersectionObserverClass = globalThis.IntersectionObserver,
  dwellMs = 2_000,
  onExpose = () => {},
} = {}) {
  const exposed = new Set();
  const pending = new Map();
  let active = false;
  const clearPending = () => {
    pending.forEach((timer) => windowRef.clearTimeout(timer));
    pending.clear();
  };
  const observer = typeof IntersectionObserverClass === 'function'
    ? new IntersectionObserverClass((entries) => {
      entries.forEach((entry) => {
        const sentenceId = entry.target?.dataset?.sentenceId;
        if (!sentenceId || exposed.has(sentenceId)) return;
        if (!active || !entry.isIntersecting || entry.intersectionRatio < 0.6) {
          if (pending.has(sentenceId)) windowRef.clearTimeout(pending.get(sentenceId));
          pending.delete(sentenceId);
          return;
        }
        if (pending.has(sentenceId)) return;
        pending.set(sentenceId, windowRef.setTimeout(() => {
          pending.delete(sentenceId);
          if (!active || exposed.has(sentenceId)) return;
          exposed.add(sentenceId);
          onExpose(entry.target);
        }, dwellMs));
      });
    }, { threshold: [0.6] })
    : null;
  root?.querySelectorAll('[data-sentence-id]').forEach((sentence) => observer?.observe(sentence));
  return {
    setActive(value) {
      const wasActive = active;
      active = Boolean(value);
      if (!active) clearPending();
      // Starting/resuming study must assess sentences already visible while
      // inactive; IntersectionObserver otherwise only reports threshold changes.
      if (active && !wasActive) root?.querySelectorAll('[data-sentence-id]').forEach((sentence) => {
        if (exposed.has(sentence.dataset.sentenceId)) return;
        observer?.unobserve?.(sentence);
        observer?.observe(sentence);
      });
    },
    destroy() {
      clearPending();
      observer?.disconnect();
    },
  };
}

function coveragePanel(coverage) {
  const counts = [
    ['Covered', coverage.coveredTokens],
    ['Learning', coverage.learningTokens],
    ['Unknown', coverage.unknownTokens],
    ['Ignored', coverage.ignoredTokens],
    ['Excluded', coverage.excludedTokens],
    ['Ambiguous / unresolved', coverage.ambiguousTokens],
    ['Non-lexical', coverage.nonLexicalTokens],
  ];
  return node('section', { className: 'language-reader-coverage language-card' }, [
    node('p', { className: 'language-kicker', text: 'USER VOCABULARY COVERAGE' }),
    node('h3', { text: 'Words in this text' }),
    wordBreakdownView(coverage),
    node('details', {}, [
      node('summary', { text: 'More about these numbers' }),
      node('div', { className: 'language-reader-coverage-head' }, [
        node('div', {}, [node('span', { text: 'Token coverage' }), node('strong', { text: percent(coverage.tokenCoveragePercent) })]),
        node('div', {}, [node('span', { text: 'Unique lemma coverage' }), node('strong', { text: percent(coverage.uniqueLemmaCoveragePercent) })]),
      ]),
      node('dl', { className: 'language-reader-counts' }, counts.flatMap(([label, value]) => [
        node('dt', { text: label }), node('dd', { text: String(value ?? 0) }),
      ])),
      node('p', { text: 'Known/mastered and intentionally ignored tokens are covered. Learning and unresolved tokens remain uncovered; excluded and non-lexical tokens leave the denominator.' }),
    ]),
  ]);
}

function referenceProfilePanel(profile) {
  if (!profile?.available) {
    return node('section', { className: 'language-card language-reader-reference is-unavailable' }, [
      node('p', { className: 'language-kicker', text: 'REFERENCE PROFILE · READ ONLY' }),
      node('h3', { text: 'Reference data unavailable' }),
      node('p', { text: 'User vocabulary coverage and Reader behavior are unchanged.' }),
    ]);
  }
  const summary = profile.resolutionSummary || {};
  const distribution = profile.frequencyProfile?.learnerRankDistribution || {};
  const expressions = profile.expressions || [];
  return node('section', { className: 'language-card language-reader-reference' }, [
    node('p', { className: 'language-kicker', text: 'REFERENCE PROFILE · NOT USER COVERAGE' }),
    node('h3', { text: 'Source-backed text intelligence' }),
    definitionList([
      ['Resolved user lemmas', `${summary.matched || 0} matched · ${summary.ambiguous || 0} ambiguous · ${summary.unmatched || 0} unmatched`],
      ['KELLY learner ranks', profile.frequencyProfile?.learnerRankAvailable
        ? Object.entries(distribution).map(([band, count]) => `${band}: ${count}`).join(' · ')
        : 'Not available for resolved lemmas'],
      ['Official idioms', profile.idiomOccurrences || 0],
      ['MWE / idiom occurrences', profile.mweOccurrences || 0],
      ['CEFR', profile.cefr?.available ? 'Source evidence available' : 'Not available'],
    ], 'language-evidence'),
    expressions.length ? node('details', {}, [
      node('summary', { text: `Inspect expression annotations (${expressions.length})` }),
      node('div', { className: 'language-reference-expression-list' }, expressions.map((item) => node('article', { className: 'language-form-card' }, [
        node('strong', { text: item.surfaceText }),
        statusPill(item.unitType, item.unitType === 'IDIOM' ? 'info' : 'muted'),
        definitionList([
          ['Canonical expression', item.canonicalForm],
          ['Exact span', `${item.exactSourceSpan?.start}–${item.exactSourceSpan?.end} Unicode code points`],
          ['Match basis', (item.matchBasis || []).join(' · ')],
          ['Resolution', item.ambiguous ? 'Ambiguous' : item.selectionState],
          ['Detector', item.detectorVersion],
          ['Source', (item.sourceProvenance || []).map((source) => `${source.name || source.sourceId} ${source.version || ''}`.trim()).join(' · ') || 'Not reported'],
        ]),
      ]))),
    ]) : node('p', { text: 'No source-supported idiom or MWE occurrence was detected.' }),
  ]);
}

function readerLegend() {
  return node('div', { className: 'language-reader-legend', attrs: { 'aria-label': 'Vocabulary state legend' } }, [
    ['known', 'Known / mastered'], ['learning', 'Learning'], ['new', 'New'],
    ['ignored', 'Ignored'], ['excluded', 'Excluded'], ['unresolved', 'Unresolved'],
  ].map(([tone, label]) => node('span', { className: `is-${tone}`, text: label })));
}

export function renderReaderLibrary(mount, state, handlers) {
  if (state.loading && !state.items.length) {
    replace(mount, messageState('loading', 'Loading Reader library…'));
    return;
  }
  const title = node('input', { type: 'text', attrs: { maxlength: '500', required: '', placeholder: 'Text title' } });
  const rawText = node('textarea', { attrs: { required: '', placeholder: 'Paste exact Norwegian Bokmål text…' } });
  const feedback = node('p', { className: 'language-form-error', attrs: { role: 'status' }, hidden: true });
  const save = node('button', { className: 'language-button', type: 'button', text: 'Save draft' });
  const analyze = node('button', { className: 'language-button is-primary', type: 'button', text: 'Save & analyze' });
  async function submit(shouldAnalyze) {
    feedback.hidden = false;
    feedback.textContent = shouldAnalyze ? 'Saving and queueing analysis…' : 'Saving draft…';
    save.disabled = true;
    analyze.disabled = true;
    try {
      await handlers.onCreate({ title: title.value, rawText: rawText.value, analyze: shouldAnalyze });
      title.value = '';
      rawText.value = '';
      feedback.textContent = shouldAnalyze ? 'Saved. Analysis is queued.' : 'Draft saved.';
    } catch (error) {
      feedback.textContent = error?.message || 'Text could not be saved.';
    } finally {
      save.disabled = false;
      analyze.disabled = false;
    }
  }
  save.addEventListener('click', () => submit(false));
  analyze.addEventListener('click', () => submit(true));
  const form = node('section', { className: 'language-card language-reader-import' }, [
    node('p', { className: 'language-kicker', text: 'NEW TEXT' }),
    node('h3', { text: 'Paste Norwegian text' }),
    node('p', { text: 'The exact source—including spaces, line breaks, punctuation, Norwegian letters and emoji—remains canonical.' }),
    node('div', { className: 'language-form' }, [field('Title', title), field('Raw text', rawText)]),
    node('div', { className: 'language-form-actions' }, [save, analyze, feedback]),
  ]);

  const list = node('div', { className: 'language-reader-library' });
  const seriesGroups = new Map();
  (state.series || []).forEach((series) => {
    const episodes = node('div', { className: 'language-reader-series-episodes' });
    const editTitle = node('input', { type: 'text', value: series.title, attrs: { maxlength: '200', required: '' } });
    const editPremise = node('textarea', { attrs: { maxlength: '2000', rows: '3' } });
    editPremise.value = series.premise || '';
    const editNotes = node('textarea', { attrs: { maxlength: '4000', rows: '3' } });
    editNotes.value = series.continuityNotes || '';
    const editFeedback = node('span', { attrs: { role: 'status' } });
    const editForm = node('form', { className: 'language-reader-series-form' }, [
      field('Series name', editTitle), field('Premise and longer arc', editPremise),
      field('Continuity notes', editNotes),
      node('small', { text: 'Update these after each episode so older character and plot details stay in future prompts.' }),
      node('button', { className: 'language-button', type: 'submit', text: 'Save series notes' }), editFeedback,
    ]);
    editForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        await handlers.onUpdateSeries(series.id, { title: editTitle.value.trim(), premise: editPremise.value.trim(), continuityNotes: editNotes.value.trim() });
      } catch (error) { editFeedback.textContent = error?.message || 'Series could not be updated.'; }
    });
    const group = node('section', { className: 'language-reader-series' }, [
      node('div', { className: 'language-reader-series-head' }, [
        node('div', {}, [node('p', { className: 'language-kicker', text: 'SERIES' }), node('h4', { text: series.title }),
          node('p', { text: `${series.episodeCount || 0} episode${series.episodeCount === 1 ? '' : 's'}${series.premise ? ` · ${series.premise}` : ''}` })]),
      ]),
      node('details', { className: 'language-reader-series-details' }, [node('summary', { text: 'Edit story notes' }), editForm]),
      episodes,
    ]);
    seriesGroups.set(series.id, episodes);
    list.append(group);
  });
  const standalone = node('div', { className: 'language-reader-standalone' });
  list.append(standalone);
  if (!state.items.length) {
    standalone.append(messageState('empty', 'No saved texts yet.', 'Add a short Norwegian text to begin assisted reading.'));
  } else {
    const orderedItems = [...state.items].sort((left, right) =>
      String(left.seriesId || '').localeCompare(String(right.seriesId || ''))
      || (left.seriesId ? (left.episodeNumber || 0) - (right.episodeNumber || 0) : 0));
    orderedItems.forEach((item) => {
      const job = state.jobs.get(item.id) || (item.latestJobId ? {
        id: item.latestJobId, state: item.latestJobState, stage: item.latestJobStage,
        progress: item.latestJobProgress, errorMessage: item.latestJobError,
      } : null);
      const coverage = item.coverage;
      const action = node('button', {
        className: 'language-button is-primary', type: 'button',
        text: item.processingState === 'ANALYZED' ? (item.readingStatus === 'IN_PROGRESS' ? 'Continue' : 'Open') : 'Open draft',
      });
      action.addEventListener('click', () => handlers.onOpen(item.id));
      const controls = [action];
      if (item.processingState !== 'ANALYZED' && !['QUEUED', 'RUNNING'].includes(job?.state)) {
        const retry = node('button', { className: 'language-button', type: 'button', text: job?.state === 'FAILED' ? 'Retry analysis' : 'Analyze' });
        retry.addEventListener('click', () => handlers.onAnalyze(item.id));
        controls.push(retry);
      }
      if (['QUEUED', 'RUNNING'].includes(job?.state)) {
        const cancel = node('button', { className: 'language-button', type: 'button', text: 'Cancel' });
        cancel.addEventListener('click', () => handlers.onCancel(job.id, item.id));
        controls.push(cancel);
      }
      if (item.seriesId) {
        const next = node('button', { className: 'language-button', type: 'button', text: 'Continue story' });
        next.addEventListener('click', () => handlers.onContinueSeries(item));
        controls.push(next);
      }
      const seriesSelect = node('select', { attrs: { 'aria-label': `Series for ${item.title || 'Untitled text'}` } }, [
        node('option', { text: 'Standalone', attrs: { value: '' } }),
        ...(state.series || []).map((series) => node('option', { text: series.title, attrs: { value: series.id } })),
      ]);
      seriesSelect.value = item.seriesId || '';
      const seriesFeedback = node('span', { className: 'language-inline-error', attrs: { role: 'status' } });
      seriesSelect.addEventListener('change', async () => {
        try { await handlers.onAssignSeries(item.id, seriesSelect.value || null); }
        catch (error) { seriesSelect.value = item.seriesId || ''; seriesFeedback.textContent = error?.message || 'Series could not be changed.'; }
      });
      const readingDetails = [readingLabel(item.readingStatus)];
      if (Number(item.activeSeconds) > 0) readingDetails.push(`${duration(item.activeSeconds)} spent reading`);
      if (item.lastReadAt) readingDetails.push(`Last read ${dateLabel(item.lastReadAt)}`);
      const jobBlock = job && (item.processingState !== 'ANALYZED' || job.state === 'FAILED') ? node('div', { className: 'language-reader-job' }, [
        statusPill(analysisLabel(job), jobTone(job.state)),
        ['QUEUED', 'RUNNING'].includes(job.state) && job.progress != null
          ? node('span', { text: `${Math.round(Number(job.progress) * 100)}%` }) : null,
        job.errorMessage ? node('span', { className: 'language-inline-error', text: job.errorMessage }) : null,
      ]) : null;
      (seriesGroups.get(item.seriesId) || standalone).append(node('article', { className: 'language-card language-reader-row' }, [
        node('div', { className: 'language-reader-row-content' }, [
          item.seriesId ? node('p', { className: 'language-reader-episode-label', text: `EPISODE ${item.episodeNumber}` }) : null,
          node('h3', { text: item.title || 'Untitled text' }),
          node('p', { className: 'language-reader-row-origin', text: `${sourceLabel(item.sourceType)} · Added ${dateLabel(item.createdAt)}` }),
          coverage ? wordBreakdownView(coverage) : node('p', { className: 'language-reader-breakdown-empty', text: 'Analyze this text to see known, learning and new words.' }),
          node('p', { className: 'language-reader-row-progress', text: readingDetails.join(' · ') }),
        ]),
        node('div', { className: 'language-reader-row-actions' }, [jobBlock, ...controls,
          node('label', { className: 'language-reader-series-select' }, [node('span', { text: 'Series' }), seriesSelect]), seriesFeedback]),
      ]));
    });
  }
  (state.series || []).forEach((series) => {
    const group = seriesGroups.get(series.id);
    if (group && !group.children.length) group.append(node('p', { className: 'language-reader-series-empty', text: series.episodeCount ? 'No episodes in the loaded texts yet.' : 'No episodes yet. Assign a saved text to start this series.' }));
  });
  if (!standalone.children.length) standalone.remove();
  else if ((state.series || []).length) standalone.prepend(node('h4', { text: 'Standalone texts' }));
  const newSeriesTitle = node('input', { type: 'text', attrs: { maxlength: '200', required: '' }, placeholder: 'Name your series' });
  const newSeriesPremise = node('textarea', { attrs: { maxlength: '2000', rows: '3' }, placeholder: 'Characters, setting and long story arc' });
  const newSeriesNotes = node('textarea', { attrs: { maxlength: '4000', rows: '3' }, placeholder: 'Continuity notes and open threads' });
  const newSeriesFeedback = node('span', { attrs: { role: 'status' } });
  const newSeriesForm = node('form', { className: 'language-reader-series-form' }, [
    field('Series name', newSeriesTitle), field('Premise and longer arc', newSeriesPremise),
    field('Continuity notes', newSeriesNotes),
    node('small', { text: 'Keep names, relationships, places and open plot threads here for future episodes.' }),
    node('button', { className: 'language-button is-primary', type: 'submit', text: 'Create series' }), newSeriesFeedback,
  ]);
  newSeriesForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await handlers.onCreateSeries({ title: newSeriesTitle.value.trim(), premise: newSeriesPremise.value.trim(), continuityNotes: newSeriesNotes.value.trim() }); }
    catch (error) { newSeriesFeedback.textContent = error?.message || 'Series could not be created.'; }
  });
  const createSeries = node('details', { className: 'language-reader-create-series' }, [
    node('summary', { text: 'Create a story series' }), newSeriesForm,
  ]);
  const continuation = [...state.items]
    .filter((item) => item.readingStatus === 'IN_PROGRESS')
    .sort((left, right) => String(right.lastReadAt || '').localeCompare(String(left.lastReadAt || '')))[0];
  const continueCard = continuation ? node('section', { className: 'language-card language-reader-continue' }, [
    node('p', { className: 'language-kicker', text: 'CONTINUE READING' }),
    node('h3', { text: continuation.title || 'Your text' }),
    node('p', { text: `Last read ${dateLabel(continuation.lastReadAt)} · ${duration(continuation.activeSeconds)} active` }),
    node('button', { className: 'language-button is-primary', type: 'button', text: 'Continue reading' }),
  ]) : null;
  continueCard?.querySelector('button')?.addEventListener('click', () => handlers.onOpen(continuation.id));
  const addText = node('details', { className: 'language-reader-add-text' }, [
    node('summary', { text: state.items.length ? 'Add a new text' : 'Add your first text' }), form,
  ]);
  if (!state.items.length) addText.open = true;
  const body = [continueCard];
  if (state.error) body.push(node('p', { className: 'language-inline-error', text: state.error }));
  const loadMore = state.nextCursor ? node('button', { className: 'language-button', type: 'button',
    text: state.loadingMore ? 'Loading more texts…' : `Load more texts (${state.items.length} of ${state.total} shown)`, disabled: state.loadingMore }) : null;
  loadMore?.addEventListener('click', () => handlers.onLoadMore());
  body.push(node('section', { className: 'language-section' }, [
    node('div', { className: 'language-section-head' }, [node('div', {}, [node('h3', { text: 'Saved texts' }), node('p', { text: `${state.total} total` })])]),
    createSeries, list, loadMore,
  ]));
  body.push(addText);
  replace(mount, node('div', { className: 'language-reader-view' }, body));
}

export function renderReaderDocument(mount, payload, handlers) {
  const { document: text, sentences = [], tokens = [], coverage = {}, readingProgress, latestJob, referenceProfile } = payload;
  const back = node('a', { className: 'language-button', text: '← Reader library', attrs: { href: '#reader' } });
  const actions = node('div', { className: 'language-reader-actions' }, [back]);
  if (text.seriesId) {
    const continueStory = node('button', { className: 'language-button', type: 'button', text: 'Create next episode' });
    continueStory.addEventListener('click', () => handlers.onContinueSeries?.());
    actions.append(continueStory);
  }
  if (text.processingState !== 'ANALYZED') {
    const analyze = node('button', { className: 'language-button is-primary', type: 'button', text: ['QUEUED', 'RUNNING'].includes(latestJob?.state) ? 'Analysis in progress…' : 'Analyze text', disabled: ['QUEUED', 'RUNNING'].includes(latestJob?.state) });
    analyze.addEventListener('click', handlers.onAnalyze);
    actions.append(analyze);
    replace(mount, node('div', { className: 'language-reader-view' }, [
      actions,
      node('section', { className: 'language-card' }, [
        node('p', { className: 'language-kicker', text: 'DRAFT' }),
        node('h3', { text: text.title }),
        latestJob ? statusPill(`${latestJob.state} · ${latestJob.stage}`, jobTone(latestJob.state)) : null,
        latestJob?.errorMessage ? node('p', { className: 'language-inline-error', text: latestJob.errorMessage }) : null,
        node('pre', { className: 'language-reader-draft', text: text.rawText }),
      ]),
    ]));
    return { destroy() {} };
  }

  const colors = node('input', { type: 'checkbox', checked: true });
  const grammarMount = node('span', { className: 'language-reader-grammar', attrs: { 'data-reader-grammar': '' } });
  actions.append(node('a', {
    className: 'language-button', text: 'Open in Listening',
    attrs: { href: `#listening/text/${text.id}` },
  }));
  const colorsLabel = node('label', { className: 'language-reader-toggle' }, [colors, node('span', { text: 'Show vocabulary colors' })]);
  const start = node('button', { className: 'language-button is-primary', type: 'button', text: readingProgress ? 'Continue reading' : 'Start reading' });
  const pause = node('button', { className: 'language-button', type: 'button', text: 'Pause', disabled: true });
  const complete = node('button', { className: 'language-button', type: 'button', text: readingProgress?.status === 'COMPLETED' ? 'Completed' : 'Mark complete', disabled: readingProgress?.status === 'COMPLETED' });
  const sessionStatus = node('span', { className: 'language-reader-session-status', text: 'Not tracking' });
  let sessionState = 'IDLE';
  let sessionPending = false;
  const sourceMount = node('section', { className: 'language-reader-source-card' });
  const source = renderExactReaderText({ mount: sourceMount, rawText: text.rawText, sentences, tokens, expressions: referenceProfile?.expressions || [], documentRef: mount.ownerDocument,
    onOpenLemma: handlers.onPreviewLemma ? null : handlers.onOpenLemma });
  let guided = null;
  const inspector = handlers.onPreviewLemma ? createLexicalInspector({
    root: source, tokens, sentences, documentRef: mount.ownerDocument,
    windowRef: mount.ownerDocument.defaultView,
    preview: handlers.onPreviewLemma,
    surfaceLookup: handlers.onLookupSurface,
    fallbackLookup: handlers.onLookupMeanings,
    detailLookup: handlers.onLexicalDetail,
    updateStatus: handlers.onUpdateKnowledge,
    playWordAudio: handlers.onPlayWordAudio,
    openFull: handlers.onOpenLemma,
    savePhrase: handlers.onSaveExpression,
    isEnabled: () => !guided?.isActive(),
  }) : null;
  let clearAudioHighlight = () => {};
  let audioPlaybackSequence = 0;
  let audioPanel = null;
  const translationPicker = node('select', { attrs: { 'aria-label': 'Sentence to translate' } }, sentences.map((sentence, index) => node('option', {
    text: `${index + 1}. ${String(sentence.exactText || '').slice(0, 110)}`,
    attrs: { value: sentence.id },
  })));
  const translationLanguage = node('select', { attrs: { 'aria-label': 'Translation language' } }, [
    node('option', { value: 'en', text: 'English' }), node('option', { value: 'pl', text: 'Polski' }),
  ]);
  const translationButton = node('button', { className: 'language-button', type: 'button', text: 'Translate sentence' });
  const translationResult = node('div', { className: 'language-reader-translation-result', attrs: { role: 'status', 'aria-live': 'polite' } });
  source.addEventListener('click', (event) => {
    const sentence = event.target.closest?.('[data-sentence-id]');
    if (sentence?.dataset.sentenceId) translationPicker.value = sentence.dataset.sentenceId;
  });
  translationButton.addEventListener('click', async () => {
    const sentence = sentences.find((item) => item.id === translationPicker.value);
    if (!sentence) return;
    translationButton.disabled = true;
    translationResult.textContent = 'Translating…';
    try {
      const result = await handlers.onTranslateSentence(sentence, translationLanguage.value);
      translationResult.replaceChildren(
        node('strong', { text: sentence.exactText }),
        node('p', { text: result.translation }),
        node('small', { text: `${result.provider}${result.cached ? ' · cached' : ''}` }),
      );
      if (translationLanguage.value === 'en') guided?.setNotes([{ sentenceId: sentence.id, english: result.translation }]);
    } catch (error) {
      translationResult.textContent = error?.message || 'Sentence translation is unavailable.';
    } finally {
      translationButton.disabled = false;
    }
  });
  const translationPanel = node('section', { className: 'language-card language-reader-translation' }, [
    node('div', {}, [node('p', { className: 'language-kicker', text: 'FULL SENTENCE TRANSLATION' }),
      node('h3', { text: 'Translate a sentence from this text' })]),
    node('p', { className: 'language-definition', text: 'Click a sentence in the text or choose it below. Translations are saved for this exact sentence.' }),
    field('Sentence', translationPicker),
    node('div', { className: 'language-form-actions' }, [field('Into', translationLanguage), translationButton]),
    translationResult,
  ]);
  let storyPanel = null;
  if (String(text.sourceType || '').startsWith('GENERATED_') && handlers.onPreviewStoryAnki) {
    const previewButton = node('button', { className: 'language-button', type: 'button', text: 'Preview Anki story deck' });
    const createButton = node('button', { className: 'language-button is-primary', type: 'button', text: 'Create staged deck in Anki', disabled: true });
    const storyStatus = node('p', { className: 'language-definition', attrs: { role: 'status', 'aria-live': 'polite' } });
    const storyPreview = node('div', { className: 'language-reader-story-preview' });
    let previewToken = null;
    let previewInputs = [];
    let previewSourceInputs = [];
    let previewCards = [];
    previewButton.addEventListener('click', async () => {
      previewButton.disabled = true;
      createButton.disabled = true;
      storyStatus.textContent = 'Preparing words, phrases and sentences with English translations…';
      try {
        const result = await handlers.onPreviewStoryAnki();
        previewToken = result.previewToken;
        previewCards = result.cards;
        const counts = result.cards.reduce((values, card) => ({ ...values, [card.stage]: (values[card.stage] || 0) + 1 }), {});
        storyStatus.textContent = `${counts.words || 0} words · ${counts.phrases || 0} phrases · ${counts.sentences || 0} sentences · ${result.audioSentences} sentence audio files. Study subdecks 01 → 02 → 03.`;
        previewInputs = result.cards.map((card, index) => node('input', {
          type: 'text', value: card.english,
          attrs: { 'aria-label': `English translation for card ${index + 1}: ${card.source}`, maxlength: 1000 },
        }));
        previewSourceInputs = result.cards.map((card, index) => node('input', {
          type: 'text', value: card.source,
          attrs: { 'aria-label': `Norwegian text for card ${index + 1}`, maxlength: 1000,
            ...(card.stage === 'sentences' ? { readonly: '', title: 'Exact Reader sentence; audio uses this text' } : {}) },
        }));
        const list = node('ol', {}, result.cards.map((card, index) => node('li', {}, [
          node('span', { text: `${card.stage}: ` }), previewSourceInputs[index],
          node('span', { text: ' → ' }), previewInputs[index],
        ])));
        storyPreview.replaceChildren(node('details', {}, [node('summary', { text: `Review and edit all ${result.cards.length} cards` }), list]));
        createButton.disabled = false;
      } catch (error) {
        previewToken = null;
        storyStatus.textContent = error?.message || 'Could not prepare the story deck.';
      } finally { previewButton.disabled = false; }
    });
    createButton.addEventListener('click', async () => {
      if (!previewToken) return;
      const translationOverrides = {};
      const sourceOverrides = {};
      for (let index = 0; index < previewInputs.length; index += 1) {
        const value = previewInputs[index].value.trim();
        const sourceValue = previewSourceInputs[index].value.trim();
        if (!value || !sourceValue) { storyStatus.textContent = `Card ${index + 1} has an empty side.`; return; }
        if (value !== previewCards[index].english) translationOverrides[String(index)] = value;
        if (sourceValue !== previewCards[index].source) sourceOverrides[String(index)] = sourceValue;
      }
      createButton.disabled = true;
      storyStatus.textContent = 'Creating Anki cards and sentence audio…';
      try {
        const result = await handlers.onCreateStoryAnki(previewToken, translationOverrides, sourceOverrides);
        storyStatus.textContent = `Created ${result.created} cards in ${result.deckName}. ${result.skippedDuplicates} duplicates skipped. ${result.audioFiles} audio files.${result.ankiWebSyncError ? ` AnkiWeb sync: ${result.ankiWebSyncError}` : ' Synced to AnkiWeb; sync AnkiDroid to download them.'}`;
      } catch (error) {
        storyStatus.textContent = error?.message || 'Could not create the story deck.';
        createButton.disabled = false;
      }
    });
    storyPanel = node('section', { className: 'language-card language-reader-story-deck' }, [
      node('p', { className: 'language-kicker', text: 'READER → ANKI' }),
      node('h3', { text: 'Learn this story in stages' }),
      node('p', { className: 'language-definition', text: 'Review and correct Norwegian card text and English machine translations, then create three subdecks: words, expressions and full sentences with audio.' }),
      node('div', { className: 'language-form-actions' }, [previewButton, createButton]), storyStatus, storyPreview,
    ]);
  }
  if (String(text.sourceType || '').startsWith('GENERATED_') && sentences.length) {
    const sentencePicker = node('select', { attrs: { 'aria-label': 'Sentence to play' } }, sentences.map((sentence, index) => node('option', {
      text: `Sentence ${index + 1}: ${String(sentence.exactText || '').slice(0, 80)}`,
      attrs: { value: sentence.id },
    })));
    const audioStatus = node('span', { className: 'language-reader-audio-status', attrs: { role: 'status', 'aria-live': 'polite' }, text: 'Ready' });
    const playText = node('button', { className: 'language-button is-primary', type: 'button', text: 'Play text' });
    const playAudio = node('button', { className: 'language-button', type: 'button', text: 'Play current sentence' });
    const pauseAudio = node('button', { className: 'language-button', type: 'button', text: 'Pause', disabled: true });
    const resumeAudio = node('button', { className: 'language-button', type: 'button', text: 'Resume', disabled: true });
    const stopAudio = node('button', { className: 'language-button', type: 'button', text: 'Stop', disabled: true });
    const fallbackAudio = node('audio', { attrs: { controls: '', preload: 'none', 'aria-label': 'Sentence audio player', hidden: '' } });
    clearAudioHighlight = () => {
      source.querySelectorAll('.is-audio-playing').forEach((item) => {
        item.classList.remove('is-audio-playing');
        item.removeAttribute('aria-current');
      });
    };
    const setPlaying = (sentenceId) => {
      clearAudioHighlight();
      const activeSentence = [...source.querySelectorAll('[data-sentence-id]')]
        .find((item) => item.dataset.sentenceId === sentenceId);
      activeSentence?.classList.add('is-audio-playing');
      activeSentence?.setAttribute('aria-current', 'true');
      activeSentence?.scrollIntoView?.({ block: 'center' });
      audioStatus.textContent = 'Playing selected sentence';
      playText.disabled = false; playAudio.disabled = false; pauseAudio.disabled = false; resumeAudio.disabled = true; stopAudio.disabled = false;
    };
    const finishAudio = (message = 'Ready') => {
      clearAudioHighlight();
      audioStatus.textContent = message;
      playText.disabled = false; playAudio.disabled = false; pauseAudio.disabled = true; resumeAudio.disabled = true; stopAudio.disabled = true;
    };
    async function beginPlayback(startIndex, continueThroughText) {
      const token = ++audioPlaybackSequence;
      fallbackAudio.hidden = true;
      fallbackAudio.removeAttribute('src');
      async function playAt(index) {
        const sentence = sentences[index];
        if (!sentence || token !== audioPlaybackSequence) return;
        sentencePicker.value = sentence.id;
        playText.disabled = true; playAudio.disabled = true;
        audioStatus.textContent = `Preparing sentence ${index + 1} of ${sentences.length}…`;
        try {
          await handlers.onPlayAudio(sentence, {
            onReady: (url) => { if (token === audioPlaybackSequence) fallbackAudio.src = url; },
            onPlaying: () => {
              if (token === audioPlaybackSequence) setPlaying(sentence.id);
            },
            onEnded: () => {
              if (token !== audioPlaybackSequence) return;
              if (continueThroughText && index + 1 < sentences.length) playAt(index + 1);
              else finishAudio(continueThroughText ? 'Text finished' : 'Sentence finished');
            },
            onError: (error) => {
              if (token !== audioPlaybackSequence) return;
              finishAudio(error?.message || 'Audio playback failed');
              if (fallbackAudio.hasAttribute('src')) {
                fallbackAudio.hidden = false;
                audioStatus.textContent += ' Use the audio player below to start it manually.';
              }
            },
          });
        } catch (error) {
          if (token === audioPlaybackSequence && audioStatus.textContent.startsWith('Preparing')) finishAudio(error?.message || 'Audio playback failed');
        }
      }
      await playAt(startIndex);
    }
    playText.addEventListener('click', () => beginPlayback(0, true));
    playAudio.addEventListener('click', () => {
      const index = sentences.findIndex((item) => item.id === (guided?.currentSentenceId() || sentencePicker.value));
      beginPlayback(Math.max(0, index), false);
    });
    pauseAudio.addEventListener('click', () => {
      handlers.onPauseAudio();
      audioStatus.textContent = 'Paused';
      pauseAudio.disabled = true; resumeAudio.disabled = false;
    });
    resumeAudio.addEventListener('click', async () => {
      try {
        await handlers.onResumeAudio();
        audioStatus.textContent = 'Playing selected sentence';
        pauseAudio.disabled = false; resumeAudio.disabled = true;
      } catch (error) { finishAudio(error?.message || 'Audio playback failed'); }
    });
    stopAudio.addEventListener('click', () => {
      audioPlaybackSequence += 1;
      handlers.onStopAudio();
      if (!fallbackAudio.hidden) fallbackAudio.pause();
      fallbackAudio.hidden = true;
      finishAudio('Stopped');
    });
    audioPanel = node('section', { className: 'language-reader-audio-strip' }, [
      node('strong', { text: 'Listen' }),
      node('div', { className: 'language-form-actions' }, [playAudio, playText, pauseAudio, resumeAudio, stopAudio, audioStatus]),
      fallbackAudio,
      node('details', {}, [node('summary', { text: 'Choose a different sentence' }), field('Sentence', sentencePicker)]),
    ]);
  }
  const saveStatus = node('span', { className: 'language-definition', attrs: { role: 'status' } });
  const saveExpression = node('button', { className: 'language-button', type: 'button', text: 'Save selected expression' });
  saveExpression.addEventListener('click', async () => {
    const selection = mount.ownerDocument.defaultView?.getSelection?.();
    const expression = String(selection?.toString() || '').trim();
    const anchor = selection?.anchorNode?.nodeType === 1 ? selection.anchorNode : selection?.anchorNode?.parentElement;
    const focus = selection?.focusNode?.nodeType === 1 ? selection.focusNode : selection?.focusNode?.parentElement;
    const sentenceNode = anchor?.closest?.('[data-sentence-id]');
    const focusSentence = focus?.closest?.('[data-sentence-id]');
    if (!expression || !sentenceNode || focusSentence !== sentenceNode || !source.contains(sentenceNode)) {
      saveStatus.textContent = 'Select an expression inside one Reader sentence first.';
      return;
    }
    const sentence = sentences.find((item) => item.id === sentenceNode.dataset.sentenceId);
    saveExpression.disabled = true; saveStatus.textContent = 'Saving…';
    try {
      const result = await handlers.onSaveExpression({ expression, sentence });
      saveStatus.textContent = result?.reused ? 'Already saved for this context.' : 'Saved to Phrasebook.';
    } catch (error) { saveStatus.textContent = error?.message || 'Expression could not be saved.'; }
    finally { saveExpression.disabled = false; }
  });
  actions.append(saveExpression, saveStatus);
  const readingControls = node('div', { className: 'language-reader-actions language-reader-reading-controls' }, [complete, colorsLabel]);
  colors.addEventListener('change', () => source.classList.toggle('is-colors-off', !colors.checked));
  async function changeSession(action) {
    if (sessionPending || (action === 'start' ? sessionState === 'ACTIVE' : sessionState !== 'ACTIVE')) return;
    sessionPending = true;
    start.disabled = true;
    pause.disabled = true;
    try {
      const result = await (action === 'start' ? handlers.onStart?.() : handlers.onPause?.());
      if (action === 'start' && result !== null) guided?.focusCurrentNewWord();
    } catch (error) {
      sessionStatus.textContent = error?.message || 'Reading session could not be updated.';
    } finally {
      sessionPending = false;
      start.disabled = sessionState === 'ACTIVE';
      pause.disabled = sessionState !== 'ACTIVE';
    }
  }
  start.addEventListener('click', () => changeSession('start'));
  pause.addEventListener('click', () => changeSession('pause'));
  complete.addEventListener('click', () => handlers.onComplete());

  function onReaderSpace(event) {
    if ((event.key !== ' ' && event.code !== 'Space') || event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target?.nodeType === 1 ? event.target : null;
    if (target?.closest?.('input,textarea,select,[contenteditable="true"],dialog,a')) return;
    const button = target?.closest?.('button');
    if (button && button !== start && button !== pause && !button.classList.contains('language-reader-token')) return;
    if (target && target !== mount.ownerDocument.body && !mount.contains(target)) return;
    event.preventDefault();
    event.stopPropagation();
    changeSession(sessionState === 'ACTIVE' ? 'pause' : 'start');
  }

  const promptOutput = node('textarea', { attrs: { 'aria-label': 'Study pack prompt', rows: 7, readonly: '' } });
  const responseInput = node('textarea', { attrs: { 'aria-label': 'Study pack JSON response', rows: 7, placeholder: '{"sentences":[{"sentenceId":"...","source":"...","english":"...","glosses":[{"source":"...","english":"...","tokenIds":["..."]}],"grammarHint":"..."}]}' } });
  const responseFile = node('input', { type: 'file', attrs: { accept: '.json,.txt,application/json,text/plain', 'aria-label': 'Upload study pack JSON file' } });
  const studyStatus = node('p', { className: 'language-definition', attrs: { role: 'status' } });
  responseFile.addEventListener('change', async () => {
    const file = responseFile.files?.[0];
    if (!file) return;
    if (file.size > 512 * 1024) { studyStatus.textContent = 'File is too large. Choose a JSON file under 512 KB.'; return; }
    try {
      responseInput.value = await file.text();
      studyStatus.textContent = `${file.name} loaded. Select Import to check and save the sentences.`;
    } catch { studyStatus.textContent = 'Could not read that file. Paste the JSON response instead.'; }
  });
  const promptDetails = node('details', {}, [node('summary', { text: 'View the full prompt' }), promptOutput]);
  promptDetails.addEventListener('toggle', () => {
    if (promptDetails.open && !promptOutput.value) promptOutput.value = buildReaderStudyPrompt(text, sentences, tokens);
  });
  const copyPrompt = node('button', { className: 'language-button', type: 'button', text: 'Copy study prompt' });
  copyPrompt.addEventListener('click', async () => {
    promptOutput.value = buildReaderStudyPrompt(text, sentences, tokens);
    try {
      if (!mount.ownerDocument.defaultView?.navigator?.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await mount.ownerDocument.defaultView.navigator.clipboard.writeText(promptOutput.value);
      studyStatus.textContent = 'Prompt copied. Paste it into your external chat.';
    } catch {
      promptDetails.open = true;
      promptOutput.select();
      studyStatus.textContent = 'Select and copy the prompt shown below.';
    }
  });
  const importNotes = node('button', { className: 'language-button is-primary', type: 'button', text: 'Import translations, words and grammar' });
  importNotes.disabled = !handlers.onImportStudyNotes;
  importNotes.addEventListener('click', async () => {
    importNotes.disabled = true;
    studyStatus.textContent = 'Checking sentences…';
    try {
      const response = parseReaderStudyResponse(responseInput.value);
      const result = await handlers.onImportStudyNotes(response);
      guided?.setNotes(result.items);
      studyStatus.textContent = `Saved translations, contextual word meanings and grammar hints for ${result.items.length} sentences.`;
      responseInput.value = '';
      studyPanel.open = false;
    } catch (error) {
      studyStatus.textContent = error?.message || 'Study pack could not be imported.';
    } finally { importNotes.disabled = !handlers.onImportStudyNotes; }
  });
  const studyPanel = node('details', { className: 'language-card language-reader-study-pack' }, [
    node('summary', { text: 'Sentence Study Pack' }),
    node('p', { className: 'language-kicker', text: 'SENTENCE STUDY PACK' }),
    node('h3', { text: 'Translations, words and grammar' }),
    node('p', { className: 'language-definition', text: `For all ${sentences.length} sentences: copy the prompt, ask your chat to answer, then upload its JSON file or paste the response.` }),
    copyPrompt, promptDetails,
    field('Upload JSON or text file', responseFile),
    field('Or paste the JSON response', responseInput),
    importNotes, studyStatus,
  ]);
  studyPanel.open = !handlers.onLoadStudyNotes;

  let coverageNode = coveragePanel(coverage);
  const header = node('section', { className: 'language-reader-document-head' }, [
    node('div', {}, [
      node('p', { className: 'language-kicker', text: text.seriesId ? `${text.seriesTitle} · EPISODE ${text.episodeNumber}` : (readingProgress?.status || 'NOT STARTED') }),
      node('h3', { text: text.title }),
    ]),
    coverageNode,
  ]);
  const workspace = node('div', { className: 'language-reader-workspace' }, [sourceMount]);
  const tools = node('details', { className: 'language-reader-tools' }, [
    node('summary', { text: 'Anki, translation and other tools' }),
    actions, storyPanel, translationPanel,
    node('details', { className: 'language-reader-insights' }, [
      node('summary', { text: 'Text insights and reference details' }),
      node('p', { text: `${text.sourceType || 'PASTED'} · analyzed ${dateLabel(payload.analysisRuns?.at(-1)?.completedAt)}` }),
      grammarMount, referenceProfilePanel(referenceProfile),
    ]),
  ]);
  replace(mount, node('div', { className: 'language-reader-view language-reader-document' }, [
    header, workspace, readerLegend(), readingControls, tools,
  ]));
  const savedOffset = Number(readingProgress?.progressSourceOffset || 0);
  const initialSentenceId = readingProgress?.progressSentenceId || sentences.find((sentence) => Number(sentence.sourceEnd) >= savedOffset)?.id;
  guided = createGuidedReader({
    source, sentences, tokens, initialSentenceId,
    preview: handlers.onPreviewLemma, lookupSurface: handlers.onLookupSurface,
    lookupMeanings: handlers.onLookupMeanings, updateStatus: handlers.onUpdateKnowledge,
    translateSentence: handlers.onTranslateSentence, openFull: handlers.onOpenLemma,
    playWordAudio: handlers.onPlayWordAudio,
    documentRef: mount.ownerDocument, windowRef: mount.ownerDocument.defaultView,
  });
  guided.toolbar.classList.add('language-reader-actions');
  guided.toolbar.append(start, pause, sessionStatus);
  sourceMount.prepend(guided.toolbar);
  if (audioPanel) guided.toolbar.after(audioPanel);
  workspace.append(node('aside', { className: 'language-reader-sidebar' }, [guided.help, studyPanel]));
  let destroyed = false;
  mount.ownerDocument.addEventListener('keydown', onReaderSpace, true);
  if (handlers.onLoadStudyNotes) handlers.onLoadStudyNotes().then((result) => {
    if (!destroyed) {
      guided?.setNotes(result.items);
      studyPanel.open = !result.items?.length;
    }
  }).catch((error) => {
    if (!destroyed) {
      studyPanel.open = true;
      studyStatus.textContent = error?.message || 'Saved study notes could not be loaded.';
    }
  });
  if (savedOffset > 0) {
    const target = [...source.querySelectorAll('[data-source-end]')].find((item) => Number(item.dataset.sourceEnd) >= savedOffset);
    target?.scrollIntoView?.({ block: 'center' });
  }
  return {
    source,
    updateCoverage(nextCoverage) {
      coverageNode.replaceWith(coveragePanel(nextCoverage));
      coverageNode = header.querySelector('.language-reader-coverage');
    },
    setSessionState(value) {
      sessionState = value;
      const active = value === 'ACTIVE';
      start.disabled = active || sessionPending;
      start.textContent = active ? 'Reading in progress' : value === 'PAUSED'
        ? 'Resume reading'
        : (readingProgress ? 'Continue reading' : 'Start reading');
      pause.disabled = !active || sessionPending;
      sessionStatus.textContent = active ? 'Active reading' : value === 'PAUSED' ? 'Paused' : 'Not tracking';
    },
    markComplete() {
      complete.disabled = true;
      complete.textContent = 'Completed';
    },
    destroy() {
      destroyed = true;
      mount.ownerDocument.removeEventListener('keydown', onReaderSpace, true);
      guided?.destroy();
      inspector?.destroy();
      audioPlaybackSequence += 1;
      handlers.onStopAudio?.();
      clearAudioHighlight();
    },
  };
}

export { TERMINAL_JOB_STATES };
