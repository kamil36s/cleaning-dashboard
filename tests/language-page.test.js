import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createLanguageApp } from '../js/language/app.js';
import { LanguageApiError } from '../js/language/api.js';

const profile = {
  id: 'p'.repeat(32), languageCode: 'nb', locale: 'nb-NO', displayName: 'Norwegian Bokmål',
  translationLocales: ['pl-PL', 'en-GB'], analyzerId: 'stanza-nb-bokmaal', analyzerVersion: '1.0.0',
  analyzerSettings: { runtimeNetworkPolicy: 'OFFLINE_ONLY' }, status: 'ACTIVE',
};

const health = {
  status: 'READY', schemaVersion: 5, offsetUnit: 'UNICODE_CODE_POINT',
  canonicalAnalyzer: {
    id: 'stanza-nb-bokmaal', adapterVersion: '1.0.0', modelVersion: 'stanza-resources-1.14.0',
    processors: ['tokenize', 'pos', 'lemma'], runtimeState: 'LAZY_NOT_CREATED',
  },
  referenceProviders: {
    zipfFrequency: { id: 'wordfreq', version: '3.1.1', metric: 'ZIPF_FREQUENCY' },
    exactFrequencyRank: 'UNSELECTED', dictionary: 'UNSELECTED', translations: 'UNSELECTED', cefr: 'UNSELECTED',
  },
  analysisWorker: { state: 'RUNNING' },
};

function overviewData() {
  return {
    statistics: {
      streak: { currentDays: 2, definition: 'Real Reader activity only' },
      vocabulary: {
        totalTracked: 4,
        newlyAdvanced: 1,
        knowledgeCounts: { new: 1, learning: 1, known: 1, mastered: 1 },
        classifierCounts: { passive: 1, active: 1, mastered: 1, recent: 1, weak: 1, underexposed: 1 },
        series: [
          { date: '2026-09-15', totalTracked: 3 },
          { date: '2026-09-16', totalTracked: 4 },
        ],
      },
      exposures: { totalReaderOccurrences: 7, uniqueLemmas: 2, distribution: { '1-2': 1, '3-5': 1 } },
      reading: {
        activeSeconds: 900,
        textsStarted: 1,
        textsCompleted: 0,
        byDay: [{ date: '2026-09-16', activeSeconds: 900 }],
        recent: [],
      },
      coverage: { history: [], historicalSnapshotsRescored: false },
      topics: [],
      frequencyCoverage: { configured: false },
    },
    goals: [],
    todayPlan: {
      ruleVersion: 'language.learning-plan/v2',
      items: [{ kind: 'ADD_TEXT', title: 'Add a Reader text', detail: 'Build canonical evidence.', href: '#reader' }],
      wordsToRecycle: { items: [] },
      anki: { status: 'NOT_CONFIGURED', recommendations: 0 },
    },
    topics: [],
    frequencyCoverage: {
      configured: false,
      status: 'NOT_CONFIGURED',
      message: 'Exact ranked frequency coverage is not configured.',
    },
    anki: { status: 'NOT_CONFIGURED', dueCount: null, linkedVocabulary: 0, conflicts: 0 },
  };
}

function statisticsData() {
  return overviewData().statistics;
}

const row = (id = 'a'.repeat(32), lemmaDisplay = 'jobb') => ({
  id, lemmaDisplay, lemmaNormalized: lemmaDisplay.toLowerCase(), partOfSpeech: 'NOUN',
  knowledgeStatus: 'NEW', disposition: 'TRACKED', recognition: null, recall: null, production: null,
  totalExposures: 0, formsCount: 2, frequencyScore: 5.56, frequencyProviderId: 'wordfreq', lastSeenAt: null,
});

function detail(lemmaDisplay = 'jobb') {
  const lemmaId = 'a'.repeat(32);
  const targetId = 'b'.repeat(32);
  return {
    lemma: {
      id: lemmaId, languageProfileId: profile.id, lemmaDisplay, lemmaNormalized: 'jobb',
      partOfSpeech: 'NOUN', userNotes: '', mergedIntoId: null,
    },
    knowledge: {
      lemmaId, knowledgeStatus: 'NEW', disposition: 'TRACKED', recognition: null, recall: null,
      production: null, totalExposures: 0, firstSeenAt: null, lastSeenAt: null, lastReviewAt: null,
      manualStatusOverride: false, manualScoresOverride: false,
    },
    forms: [{
      id: 'f'.repeat(32), lemmaId, formDisplay: 'jobbene', formNormalized: 'jobbene',
      providerId: 'stanza-nb-bokmaal', providerVersion: '1.0.0', mappingProvenance: 'ANALYZER',
      ambiguityState: 'AMBIGUOUS', lexicalStatus: 'NOT_ASSESSED', confidence: null, manualLocked: false,
      candidateMappings: [
        { formId: 'f'.repeat(32), lemmaId, lemmaDisplay: 'jobb', partOfSpeech: 'NOUN', mappingProvenance: 'ANALYZER', ambiguityState: 'AMBIGUOUS', manualLocked: false, morphology: { Number: 'Plur' } },
        { formId: 'f'.repeat(32), lemmaId: targetId, lemmaDisplay: 'jobbe', partOfSpeech: 'VERB', mappingProvenance: 'ANALYZER', ambiguityState: 'AMBIGUOUS', manualLocked: false, morphology: {} },
      ],
    }],
    frequencies: [{
      metric: 'ZIPF_FREQUENCY', score: 5.56, lookupValue: 'jobb', matchKind: 'LEMMA',
      providerId: 'wordfreq', providerVersion: '3.1.1',
    }],
    events: [],
  };
}

function analyzedText(knowledgeStatus = 'LEARNING') {
  const rawText = '😊 jobb jobben\njobber jobbene <script>alert(1)</script>';
  const forms = ['jobb', 'jobben', 'jobber', 'jobbene'];
  let cursor = 0;
  const tokens = forms.map((surface, index) => {
    const position = rawText.indexOf(surface, cursor);
    cursor = position + surface.length;
    return {
      id: `${index}`.padStart(32, '0'), sentenceId: '1'.repeat(32), tokenOrder: index,
      surface, sourceStart: [...rawText.slice(0, position)].length,
      sourceEnd: [...rawText.slice(0, position + surface.length)].length,
      tokenKind: 'WORD', selectedLemmaId: 'a'.repeat(32), selectedLemmaDisplay: 'jobb',
      knowledgeStatus, disposition: 'TRACKED', resolutionState: 'MODEL_SELECTED',
    };
  });
  return {
    document: { id: 't'.repeat(32), languageProfileId: profile.id, title: 'Exact text', rawText, sourceType: 'PASTED', processingState: 'ANALYZED' },
    sentences: [{ id: '1'.repeat(32), sentenceOrder: 0, sourceStart: 0, sourceEnd: [...rawText].length, exactText: rawText }],
    tokens,
    analysisRuns: [{ id: 'r'.repeat(32), completedAt: '2026-09-16T10:00:00Z' }],
    coverage: {
      tokenCoveragePercent: knowledgeStatus === 'KNOWN' ? 100 : 0,
      uniqueLemmaCoveragePercent: knowledgeStatus === 'KNOWN' ? 100 : 0,
      coveredTokens: knowledgeStatus === 'KNOWN' ? 4 : 0,
      learningTokens: knowledgeStatus === 'LEARNING' ? 4 : 0,
      unknownTokens: 0, ignoredTokens: 0, excludedTokens: 0, ambiguousTokens: 0, nonLexicalTokens: 0,
    },
    readingProgress: null, latestJob: null, studySessions: [],
  };
}

function shell() {
  document.body.innerHTML = `
    <div id="language-app">
      <nav>
        <a href="#overview" data-language-route="overview">Overview</a>
        <a href="#reader" data-language-route="reader">Reader</a>
        <a href="#listening" data-language-route="listening">Listening</a>
        <a href="#vocabulary" data-language-route="vocabulary">Vocabulary</a>
        <a href="#topics" data-language-route="topics">Topics</a>
        <a href="#reviews" data-language-route="reviews">Reviews</a>
        <a href="#cloze" data-language-route="cloze">Cloze</a>
        <a href="#statistics" data-language-route="statistics">Statistics</a>
        <a href="#goals" data-language-route="goals">Goals</a>
        <a href="#settings" data-language-route="settings">Settings</a>
      </nav>
      <div id="language-connection"><strong></strong></div>
      <p id="language-eyebrow"></p><h2 id="language-heading"></h2>
      <div id="language-profile-summary"></div>
      <div id="language-notice" hidden></div>
      <main id="language-view"></main>
    </div>
    <dialog id="language-lemma-dialog"><button data-language-dialog-close>close</button><div id="language-lemma-detail"></div></dialog>
    <dialog id="language-merge-dialog">
      <form method="dialog"><p id="language-merge-summary"></p><input type="checkbox" id="language-merge-confirm-check">
      <p id="language-merge-error" hidden></p><button id="language-merge-confirm" type="button" disabled>Merge lemmas</button></form>
    </dialog>`;
}

function fakeApi(overrides = {}) {
  const api = {
    profiles: vi.fn(async () => ({ items: [profile] })),
    health: vi.fn(async () => health),
    overview: vi.fn(async () => overviewData()),
    statistics: vi.fn(async () => statisticsData()),
    topics: vi.fn(async () => ({ items: [] })),
    topic: vi.fn(async () => null),
    createTopic: vi.fn(async () => ({ topic: { id: 'q'.repeat(32), displayName: 'Work' } })),
    updateTopic: vi.fn(async () => ({})),
    assignTopicLemma: vi.fn(async () => ({})),
    removeTopicLemma: vi.fn(async () => ({})),
    goals: vi.fn(async () => ({ items: [] })),
    createGoal: vi.fn(async () => ({})),
    updateGoal: vi.fn(async () => ({})),
    vocabulary: vi.fn(async (_profileId, params = {}) => ({
      items: params.cursor ? [row('c'.repeat(32), 'bok')] : [row()],
      pagination: { total: params.q ? 1 : 2, nextCursor: params.cursor ? null : '30' },
    })),
    vocabularyAnkiStatus: vi.fn(async () => ({ status: 'NOT_CONFIGURED', lemmas: {} })),
    texts: vi.fn(async () => ({ items: [], pagination: { total: 3, nextCursor: null } })),
    readingSeries: vi.fn(async () => ({ items: [] })),
    lemma: vi.fn(async () => detail()),
    updateLemma: vi.fn(async (_id, payload) => ({
      ...detail(), lemma: { ...detail().lemma, userNotes: payload.userNotes },
      knowledge: { ...detail().knowledge, ...payload },
    })),
    lockFormMapping: vi.fn(async () => ({})),
    mergeLemmas: vi.fn(async () => ({ targetLemmaId: 'b'.repeat(32) })),
    updateProfile: vi.fn(async (_id, payload) => ({ profile: { ...profile, ...payload } })),
    createText: vi.fn(async (payload) => ({ text: { id: 't'.repeat(32), ...payload, processingState: 'DRAFT' } })),
    text: vi.fn(async () => { throw new LanguageApiError('Text was not found', { status: 404, code: 'language_text_not_found' }); }),
    analyzeText: vi.fn(async () => ({ job: { id: 'j'.repeat(32), state: 'QUEUED', stage: 'QUEUED', progress: 0 } })),
    job: vi.fn(async () => ({ job: { id: 'j'.repeat(32), state: 'COMPLETED', stage: 'COMPLETED', progress: 1 } })),
    cancelJob: vi.fn(async () => ({ job: { id: 'j'.repeat(32), state: 'CANCELLED', stage: 'CANCELLED' } })),
    startReaderSession: vi.fn(async () => ({ session: { id: 's'.repeat(32), clientSessionId: 'client', status: 'ACTIVE', activityState: 'ACTIVE' } })),
    updateReaderSession: vi.fn(async (_id, payload) => ({ session: { id: 's'.repeat(32), clientSessionId: 'client', status: payload.action === 'COMPLETE' ? 'COMPLETED' : 'ACTIVE', activityState: ['PAUSE', 'COMPLETE'].includes(payload.action) ? 'PAUSED' : 'ACTIVE' } })),
    recordReaderExposures: vi.fn(async () => ({ created: true, events: [] })),
    updateReadingProgress: vi.fn(async (_id, payload) => ({ readingProgress: { ...payload } })),
    ankiStatus: vi.fn(async () => ({ status: 'NOT_CONFIGURED', dueCount: null, linkedVocabulary: 0, conflicts: 0 })),
    ankiConfig: vi.fn(async () => ({ config: { enabled: false, endpoint: 'http://127.0.0.1:8765', deckName: '', modelName: '', fieldMap: {}, apiKeyConfigured: false } })),
    ankiSyncRuns: vi.fn(async () => ({ items: [] })),
    pullAnki: vi.fn(async () => ({ run: { status: 'COMPLETED', counts: {} } })),
    updateAnkiConfig: vi.fn(async (_id, payload) => ({ config: payload })),
    testAnki: vi.fn(async () => ({ status: { status: 'UNAVAILABLE' } })),
    ankiDecks: vi.fn(async () => ({ items: [] })),
    ankiModels: vi.fn(async () => ({ items: [] })),
    ankiModelFields: vi.fn(async () => ({ items: [] })),
    clozeTracks: vi.fn(async () => ({
      status: 'READY', activeSessionId: null, items: [],
      summary: { attempts: 0, correct: 0, incorrect: 0, accuracy: null, mistakeTargets: 0 },
    })),
    clozeStatistics: vi.fn(async () => ({ attempts: 0, correct: 0, incorrect: 0, accuracy: null })),
    startClozeSession: vi.fn(async () => ({ session: null, attempts: [] })),
    clozeSession: vi.fn(async () => ({ session: null, attempts: [] })),
    submitClozeAttempt: vi.fn(async () => ({})),
    reportClozeItem: vi.fn(async () => ({ created: true })),
    listening: vi.fn(async () => ({ items: [], total: 0 })),
    listeningProgress: vi.fn(async () => ({ progress: { status: 'NOT_STARTED', currentSentenceOrder: 0, completedSentenceCount: 0, eligibleSentenceCount: 1, completionPercent: 0 } })),
    startListeningSession: vi.fn(async () => ({ session: { id: 'l'.repeat(32), status: 'ACTIVE' }, created: true })),
    recordListeningEvent: vi.fn(async (_id, payload) => ({ event: payload, progress: { status: 'IN_PROGRESS', completedSentenceCount: 0, eligibleSentenceCount: 1, completionPercent: 0 } })),
    closeListeningSession: vi.fn(async () => ({ applied: true })),
  };
  return Object.assign(api, overrides);
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function start(url = 'http://localhost/language.html#overview', overrides = {}, options = {}) {
  window.happyDOM.setURL(url);
  const api = fakeApi(overrides);
  const app = createLanguageApp({
    api,
    debounceMs: options.debounceMs ?? 0,
    exposureDwellMs: options.exposureDwellMs ?? 0,
    readerHeartbeatMs: options.readerHeartbeatMs ?? 60_000,
    IntersectionObserverClass: options.IntersectionObserverClass,
    SpeechSynthesisUtteranceClass: options.SpeechSynthesisUtteranceClass,
    AudioClass: options.AudioClass,
  });
  app.start();
  await vi.waitFor(() => expect(document.querySelector('#language-connection').dataset.state).toBe('ready'));
  await tick();
  return { app, api };
}

function navigate(hash) {
  window.location.hash = hash;
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

describe('Language page', () => {
  beforeEach(() => {
    shell();
    if (!HTMLDialogElement.prototype.showModal) {
      HTMLDialogElement.prototype.showModal = function showModal() { this.setAttribute('open', ''); };
    }
    if (!HTMLDialogElement.prototype.close) {
      HTMLDialogElement.prototype.close = function close() {
        this.removeAttribute('open');
        this.dispatchEvent(new Event('close'));
      };
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it('plays the full Cloze sentence automatically after an answer', async () => {
    const played = [];
    class FakeAudio {
      constructor(url) { this.url = url; }
      play() { played.push(this.url); return Promise.resolve(); }
      pause() {}
    }
    const currentItem = { index: 0, fingerprint: 'fingerprint', sentenceText: 'Du har vært gjennom mye.',
      blankStart: 13, blankEnd: 21, options: ['uten', 'gjennom'], questionType: 'MULTIPLE_CHOICE' };
    const session = { id: 's'.repeat(32), trackKey: 'FAST_TRACK_1', status: 'ACTIVE',
      actualItemCount: 1, requestedItemCount: 10, currentItem };
    const overrides = {
      clozeTracks: vi.fn(async () => ({ status: 'READY', items: [{ key: 'FAST_TRACK_1', label: 'Fast Track 1',
        rankLabel: 'KELLY', rankMin: 1, rankMax: 500, targets: 1, encountered: 0, playableTargets: 1 }],
      summary: { mistakeTargets: 0 } })),
      startClozeSession: vi.fn(async () => ({ session, attempts: [] })),
      submitClozeAttempt: vi.fn(async () => ({ session: { ...session, currentItem: null }, attempts: [],
        feedback: { outcome: 'CORRECT', expectedSurfaceForm: 'gjennom', chosenOption: 'gjennom' } })),
      clozeAudio: vi.fn(async () => ({ audioUrl: '/api/language/cloze/audio/sentence.mp3' })),
    };
    const { app, api } = await start('http://localhost/language.html#cloze', overrides, { AudioClass: FakeAudio });
    await vi.waitFor(() => expect(document.querySelector('.language-cloze-track')).not.toBeNull());
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Start Fast Track').click();
    await vi.waitFor(() => expect(document.querySelectorAll('.language-cloze-option')).toHaveLength(2));
    document.querySelectorAll('.language-cloze-option')[1].click();
    await vi.waitFor(() => expect(played).toContain('/api/language/cloze/audio/sentence.mp3'));
    expect(api.clozeAudio).toHaveBeenCalledWith(session.id, 0, { itemFingerprint: 'fingerprint' });
    app.destroy();
  });

  it('ignores a stale Study Session response after route teardown', async () => {
    let resolvePlan;
    const studySession = vi.fn(() => new Promise((resolve) => { resolvePlan = resolve; }));
    const { app } = await start('http://localhost/language.html#study-session', { studySession });
    await vi.waitFor(() => expect(document.querySelector('#language-session-minutes')).not.toBeNull());
    document.querySelector('#language-session-minutes').value = '30';
    document.querySelector('.language-session-controls').requestSubmit();
    expect(studySession).toHaveBeenCalledWith(profile.id, 30);
    navigate('#overview');
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('Study streak'));
    resolvePlan({ requestedMinutes: 30, plannedMinutes: 5, segmentCount: 1,
      segments: [{ title: 'Stale plan', reason: 'Old', sourceOwner: 'Reader', estimatedMinutes: 5,
        destinationRoute: '#reader' }] });
    await tick();
    expect(document.querySelector('#language-view').textContent).not.toContain('Stale plan');
    navigate('#study-session');
    await vi.waitFor(() => expect(document.querySelector('#language-session-minutes')).not.toBeNull());
    expect(document.querySelector('#language-view').textContent).toContain('Building a study session');
    app.destroy();
  });

  it('bootstraps the Bokmål profile and renders only truthful Overview facts', async () => {
    const { app, api } = await start();
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('Study streak'));
    const content = document.querySelector('#language-view').textContent;
    expect(content).toContain('Tracked vocabulary');
    expect(content).toContain('Ranked frequency coverage');
    expect(content).toContain('Not configured');
    expect(content).toContain('2 days');
    expect(content).not.toContain('Lazy');
    const flag = document.querySelector('.language-profile-flag');
    expect(flag).not.toBeNull();
    expect(flag.getAttribute('viewBox')).toBe('0 0 22 16');
    expect(document.querySelector('#language-profile-summary').textContent).not.toContain('🇳🇴');
    expect(api.health).toHaveBeenCalledTimes(1);
    expect(api.overview).toHaveBeenCalledTimes(1);
    app.destroy();
  });

  it('keeps the inline Norwegian flag in the persistent header across routes', async () => {
    const { app } = await start();
    const flag = document.querySelector('.language-profile-flag');
    for (const route of ['#vocabulary', '#topics', '#statistics', '#goals', '#settings', '#reader']) {
      navigate(route);
      await tick();
      expect(document.querySelector('.language-profile-flag')).toBe(flag);
    }
    app.destroy();
  });

  it('renders event-derived Statistics and reloads a selected time range', async () => {
    const statistics = vi.fn(async () => statisticsData());
    const { app } = await start('http://localhost/language.html#statistics', { statistics });
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('Known Words'));
    expect(document.querySelector('#language-view').textContent).toContain('immutable');
    expect(document.querySelector('#language-view').textContent).toContain('Not configured');
    const range = document.querySelector('[aria-label="Statistics time range"]');
    range.value = '90d';
    range.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(statistics).toHaveBeenLastCalledWith(
      profile.id,
      { range: '90d' },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ));
    app.destroy();
  });

  it('loads the Reviews route with truthful unavailable Anki state', async () => {
    const { app, api } = await start('http://localhost/language.html#reviews');
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('Anki remains the scheduler'));
    expect(document.querySelector('#language-view').textContent).toContain('NOT_CONFIGURED');
    expect(document.querySelector('#language-view').textContent).not.toContain('Start review');
    expect(api.ankiStatus).toHaveBeenCalledTimes(1);
    app.destroy();
  });

  it('renders supported weekly goals and persists a new goal', async () => {
    const createGoal = vi.fn(async () => ({}));
    const goals = vi.fn(async () => ({ items: [] }));
    const { app } = await start('http://localhost/language.html#goals', { goals, createGoal });
    await vi.waitFor(() => expect(document.querySelector('.language-goal-form')).not.toBeNull());
    const form = document.querySelector('.language-goal-form');
    form.querySelector('[name="metric"]').value = 'TEXTS_COMPLETED';
    form.querySelector('[name="targetValue"]').value = '2';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(createGoal).toHaveBeenCalledWith(profile.id, expect.objectContaining({
      metric: 'TEXTS_COMPLETED', targetValue: 2, unit: 'TEXTS', period: 'WEEK', timezone: 'Europe/Warsaw',
    })));
    app.destroy();
  });

  it('renders manual topic membership and safely displays canonical lemma text', async () => {
    const topicId = 'q'.repeat(32);
    const topics = vi.fn(async () => ({ items: [{
      topic: { id: topicId, displayName: 'Work <script>', description: '', archived: false },
      weightedMasteryPercent: 35,
      mappedLemmaCount: 1,
    }] }));
    const topic = vi.fn(async () => ({
      topic: { id: topicId, displayName: 'Work <script>', description: '', archived: false },
      mastery: {
        weightedMasteryPercent: 35,
        denominatorQuality: { message: 'Partial: user-mapped lemmas only.' },
      },
      lemmas: [{
        lemmaId: 'a'.repeat(32), lemmaDisplay: '<img onerror=alert(1)>', knowledgeStatus: 'LEARNING',
        weight: 1, provenance: 'MANUAL',
      }],
    }));
    const { app } = await start('http://localhost/language.html#topics', { topics, topic });
    await vi.waitFor(() => expect(document.querySelector('.language-topic-button')).not.toBeNull());
    document.querySelector('.language-topic-button').click();
    await vi.waitFor(() => expect(document.querySelector('.language-topic-detail')).not.toBeNull());
    expect(document.querySelector('.language-topic-detail').textContent).toContain('<img onerror=alert(1)>');
    expect(document.querySelector('.language-topic-detail img')).toBeNull();
    expect(document.querySelector('.language-topic-detail').textContent).toContain('Partial: user-mapped lemmas only.');
    app.destroy();
  });

  it('creates an exact pasted draft and can queue analysis from Reader', async () => {
    const { app, api } = await start('http://localhost/language.html#reader', {
      texts: vi.fn(async () => ({ items: [], pagination: { total: 0, nextCursor: null } })),
    });
    await vi.waitFor(() => expect(document.querySelector('.language-reader-import textarea')).not.toBeNull());
    document.querySelector('.language-reader-import input').value = 'Min tekst';
    document.querySelector('.language-reader-import textarea').value = 'Ærlig 😊 jobb\n  jobbene';
    [...document.querySelectorAll('.language-reader-import button')].find((button) => button.textContent === 'Save & analyze').click();
    await vi.waitFor(() => expect(api.createText).toHaveBeenCalledTimes(1));
    expect(api.createText.mock.calls[0][0].rawText).toBe('Ærlig 😊 jobb\n  jobbene');
    await vi.waitFor(() => expect(api.analyzeText).toHaveBeenCalledWith('t'.repeat(32)));
    app.destroy();
  });

  it('keeps saved Reader texts visible when the series endpoint fails', async () => {
    const { app } = await start('http://localhost/language.html#reader', {
      texts: vi.fn(async () => ({
        items: [{ id: 't'.repeat(32), title: 'Jonas on Saturday', processingState: 'ANALYZED' }],
        pagination: { total: 1, nextCursor: null },
      })),
      readingSeries: vi.fn(async () => { throw new LanguageApiError('Not found', { status: 404 }); }),
    });
    await vi.waitFor(() => expect(document.querySelector('.language-reader-row h3')?.textContent).toBe('Jonas on Saturday'));
    expect(document.querySelector('#language-view').textContent).toContain('1 total');
    expect(document.querySelector('#language-view').textContent).toContain('Story series could not be loaded');
    app.destroy();
  });

  it('opens an analyzed Reader text, preserves exact text safely, and reuses canonical lemma detail', async () => {
    let status = 'LEARNING';
    const text = vi.fn(async () => analyzedText(status));
    const updateLemma = vi.fn(async (_id, payload) => {
      status = payload.knowledgeStatus;
      return { ...detail(), knowledge: { ...detail().knowledge, ...payload } };
    });
    const { app, api } = await start(`http://localhost/language.html#reader/text/${'t'.repeat(32)}`, { text, updateLemma });
    await vi.waitFor(() => expect(document.querySelector('[data-reader-source]')).not.toBeNull());
    expect(document.querySelector('[data-reader-source]').textContent).toBe(analyzedText().document.rawText);
    expect(document.querySelector('[data-reader-source] script')).toBeNull();
    expect(api.startReaderSession).not.toHaveBeenCalled();
    expect(api.recordReaderExposures).not.toHaveBeenCalled();
    document.querySelector('[data-lemma-id]').click();
    document.querySelector('.language-guided-details').click();
    await vi.waitFor(() => expect(document.querySelector('#language-lemma-dialog').open).toBe(true));
    expect(document.querySelector('.language-reader-context').textContent).toContain('😊 jobb jobben');
    document.querySelector('#language-lemma-detail [name="knowledgeStatus"]').value = 'KNOWN';
    document.querySelector('#language-lemma-detail .language-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(updateLemma).toHaveBeenCalled());
    await vi.waitFor(() => expect([...document.querySelectorAll('[data-reader-source] [data-lemma-id]')].every((item) => item.classList.contains('is-known'))).toBe(true));
    expect(document.querySelector('.language-reader-coverage').textContent).toContain('100.0%');
    app.destroy();
  });

  it('records one validated sentence batch only after explicit Reader start', async () => {
    class FakeObserver {
      static instance;
      constructor(callback) { this.callback = callback; FakeObserver.instance = this; }
      observe() {}
      disconnect() {}
      emit(target) { this.callback([{ target, isIntersecting: true, intersectionRatio: 0.8 }]); }
    }
    const { app, api } = await start(
      `http://localhost/language.html#reader/text/${'t'.repeat(32)}`,
      { text: vi.fn(async () => analyzedText()) },
      { IntersectionObserverClass: FakeObserver, exposureDwellMs: 0 },
    );
    await vi.waitFor(() => expect(document.querySelector('[data-reader-source]')).not.toBeNull());
    expect(api.recordReaderExposures).not.toHaveBeenCalled();
    [...document.querySelectorAll('.language-reader-actions button')].find((button) => button.textContent === 'Start reading').click();
    await vi.waitFor(() => expect(api.startReaderSession).toHaveBeenCalledTimes(1));
    FakeObserver.instance.emit(document.querySelector('[data-sentence-id]'));
    await vi.waitFor(() => expect(api.recordReaderExposures).toHaveBeenCalledTimes(1));
    expect(api.recordReaderExposures.mock.calls[0][1].occurrences).toEqual([
      { lemmaId: 'a'.repeat(32), occurrenceCount: 4 },
    ]);
    expect(api.updateReadingProgress).toHaveBeenCalledWith('t'.repeat(32), expect.objectContaining({ status: 'IN_PROGRESS' }));
    app.destroy();
  });

  it('navigates without remounting the shell and loads server-paginated vocabulary', async () => {
    const { app, api } = await start();
    const shellNode = document.querySelector('#language-app');
    navigate('#vocabulary');
    await vi.waitFor(() => expect(document.querySelectorAll('[data-lemma-id]')).toHaveLength(1));
    document.querySelector('[data-language-load-more]').click();
    await vi.waitFor(() => expect(document.querySelectorAll('[data-lemma-id]')).toHaveLength(2));
    expect(document.querySelector('#language-app')).toBe(shellNode);
    expect(api.vocabulary.mock.calls.some(([, params]) => params.cursor === '30')).toBe(true);
    app.destroy();
  });

  it('explains vocabulary columns and shows independent Anki deck statuses', async () => {
    const vocabularyAnkiStatus = vi.fn(async () => ({
      status: 'CURRENT', observedAt: '2026-10-01T12:00:00Z',
      lemmas: { ['a'.repeat(32)]: [
        { deckName: 'Norwegian words', statuses: ['LEARNING'] },
        { deckName: 'Daily review', statuses: ['SUSPENDED', 'NEW'] },
      ] },
    }));
    const { app } = await start('http://localhost/language.html#vocabulary', { vocabularyAnkiStatus });
    await vi.waitFor(() => expect(document.querySelector('.language-anki-deck-list')).not.toBeNull());
    const view = document.querySelector('#language-view');
    expect(view.textContent).toContain('Norwegian words');
    expect(view.textContent).toContain('Daily review');
    expect(view.textContent).toContain('Suspended');
    expect(view.querySelector('.language-vocabulary-guide').textContent).toContain('recorded study encounter');
    expect(view.querySelector('th[title*="Recognition / Recall / Production"]')).not.toBeNull();
    expect(view.querySelector('th[title*="higher means more common"]')).not.toBeNull();
    app.destroy();
  });

  it('sends search and filter values to the paginated API', async () => {
    const { app, api } = await start('http://localhost/language.html#vocabulary');
    await vi.waitFor(() => expect(document.querySelector('[data-language-search]')).not.toBeNull());
    const search = document.querySelector('[data-language-search]');
    search.value = 'jobbene';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    document.querySelector('[data-language-knowledge-filter]').value = 'KNOWN';
    document.querySelector('[data-language-knowledge-filter]').dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(api.vocabulary.mock.calls.some(([, params]) => params.q === 'jobbene' && params.status === 'KNOWN')).toBe(true));
    app.destroy();
  });

  it('renders empty and request-error vocabulary states without a blank screen', async () => {
    const empty = vi.fn(async () => ({ items: [], pagination: { total: 0, nextCursor: null } }));
    const first = await start('http://localhost/language.html#vocabulary', { vocabulary: empty });
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('No vocabulary matches'));
    first.app.destroy();

    shell();
    const failure = vi.fn(async () => { throw new Error('server unavailable'); });
    const second = await start('http://localhost/language.html#vocabulary', { vocabulary: failure });
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('server unavailable'));
    second.app.destroy();
  });

  it('prevents a stale rapid-search response from replacing the newer query', async () => {
    let resolveFirst;
    const first = new Promise((resolve) => { resolveFirst = resolve; });
    const vocabulary = vi.fn(async (_id, params = {}) => {
      if (params.q === 'first') return first;
      if (params.q === 'second') return { items: [row('2'.repeat(32), 'second')], pagination: { total: 1, nextCursor: null } };
      return { items: [row()], pagination: { total: 1, nextCursor: null } };
    });
    const { app } = await start('http://localhost/language.html#vocabulary', { vocabulary });
    const input = document.querySelector('[data-language-search]');
    input.value = 'first';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    input.value = 'second';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('second'));
    resolveFirst({ items: [row('1'.repeat(32), 'first')], pagination: { total: 1, nextCursor: null } });
    await tick();
    expect(document.querySelector('#language-view').textContent).toContain('second');
    expect(document.querySelector('#language-view').textContent).not.toContain('first');
    app.destroy();
  });

  it('loads a direct lemma route and renders hostile-looking values as text', async () => {
    const unsafe = '<script>alert(1)</script><img src=x onerror=alert(2)>';
    const { app } = await start(`http://localhost/language.html#vocabulary/lemma/${'a'.repeat(32)}`, {
      lemma: vi.fn(async () => {
        const value = detail(unsafe);
        value.forms[0].formDisplay = '<img src=x onerror=alert(3)>';
        return value;
      }),
    });
    await vi.waitFor(() => expect(document.querySelector('#language-lemma-dialog').open).toBe(true));
    const mount = document.querySelector('#language-lemma-detail');
    expect(mount.textContent).toContain('<script>alert(1)</script>');
    expect(mount.querySelector('script')).toBeNull();
    expect(mount.querySelector('img')).toBeNull();
    app.destroy();
  });

  it('persists knowledge edits only after the API accepts them', async () => {
    const { app, api } = await start(`http://localhost/language.html#vocabulary/lemma/${'a'.repeat(32)}`);
    await vi.waitFor(() => expect(document.querySelector('[name="knowledgeStatus"]')).not.toBeNull());
    document.querySelector('#language-lemma-detail [name="knowledgeStatus"]').value = 'KNOWN';
    document.querySelector('#language-lemma-detail [name="recognition"]').value = '4';
    document.querySelector('#language-lemma-detail .language-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(api.updateLemma).toHaveBeenCalled());
    expect(api.updateLemma.mock.calls[0][1]).toMatchObject({ knowledgeStatus: 'KNOWN', recognition: 4 });
    await vi.waitFor(() => expect(document.querySelector('#language-lemma-detail [name="knowledgeStatus"]').value).toBe('KNOWN'));
    app.destroy();
  });

  it('shows validation errors from rejected knowledge writes', async () => {
    const failure = new LanguageApiError('recognition must be 0–5', { code: 'invalid_language_request', status: 400 });
    const { app } = await start(`http://localhost/language.html#vocabulary/lemma/${'a'.repeat(32)}`, {
      updateLemma: vi.fn(async () => { throw failure; }),
    });
    await vi.waitFor(() => expect(document.querySelector('[name="knowledgeStatus"]')).not.toBeNull());
    document.querySelector('#language-lemma-detail .language-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(document.querySelector('#language-lemma-detail').textContent).toContain('recognition must be 0–5'));
    app.destroy();
  });

  it('locks an explicit candidate mapping through the thin API', async () => {
    const { app, api } = await start(`http://localhost/language.html#vocabulary/lemma/${'a'.repeat(32)}`);
    await vi.waitFor(() => expect(document.querySelector('[name^="mapping-"]')).not.toBeNull());
    const select = document.querySelector('[name^="mapping-"]');
    select.value = 'b'.repeat(32);
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Lock mapping').click();
    await vi.waitFor(() => expect(api.lockFormMapping).toHaveBeenCalledWith('f'.repeat(32), 'b'.repeat(32)));
    app.destroy();
  });

  it('requires explicit confirmation before a merge and redirects to the target', async () => {
    const target = row('b'.repeat(32), 'jobbe');
    const vocabulary = vi.fn(async (_id, params = {}) => ({
      items: params.q ? [target] : [row()], pagination: { total: 1, nextCursor: null },
    }));
    const { app, api } = await start(`http://localhost/language.html#vocabulary/lemma/${'a'.repeat(32)}`, { vocabulary });
    await vi.waitFor(() => expect(document.querySelector('input[placeholder="Search target lemma…"]')).not.toBeNull());
    const input = document.querySelector('input[placeholder="Search target lemma…"]');
    input.value = 'jobbe';
    input.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect([...document.querySelectorAll('button')].some((button) => button.textContent === 'Review merge')).toBe(true));
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Review merge').click();
    expect(document.querySelector('#language-merge-confirm').disabled).toBe(true);
    expect(document.querySelector('#language-merge-summary').textContent).toContain('jobb');
    expect(document.querySelector('#language-merge-summary').textContent).toContain('jobbe');
    const check = document.querySelector('#language-merge-confirm-check');
    check.checked = true;
    check.dispatchEvent(new Event('change', { bubbles: true }));
    document.querySelector('#language-merge-confirm').click();
    await vi.waitFor(() => expect(api.mergeLemmas).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(window.location.hash).toBe(`#vocabulary/lemma/${'b'.repeat(32)}`));
    app.destroy();
  });

  it('renders truthful Settings states and saves supported profile fields', async () => {
    const { app, api } = await start('http://localhost/language.html#settings');
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('Zipf score only'));
    const text = document.querySelector('#language-view').textContent;
    expect(text).toContain('Not configured');
    expect(text).toContain('FREE_ONLY');
    expect(text).toContain('manual copy/paste remains available');
    expect(text).toContain('Lazy · not loaded');
    const displayName = document.querySelector('.language-settings-card input[type="text"]');
    displayName.value = 'Norsk';
    displayName.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(api.updateProfile).toHaveBeenCalled());
    expect(api.updateProfile.mock.calls[0][1].displayName).toBe('Norsk');
    app.destroy();
  });

  it('starts Listening evidence only on audible start and cancels conservatively when hidden', async () => {
    let utterance;
    class FakeUtterance { constructor(text) { this.text = text; } }
    const synthesis = {
      getVoices: () => [{ name: 'Bokmal', lang: 'nb-NO', voiceURI: 'nb-no' }],
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      speak: vi.fn((value) => { utterance = value; }),
      pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
    };
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: synthesis });
    const listeningPayload = analyzedText();
    listeningPayload.sentences[0].exactText = listeningPayload.document.rawText;
    const { app, api } = await start(
      `http://localhost/language.html#listening/text/${'t'.repeat(32)}`,
      { text: vi.fn(async () => listeningPayload) },
      { SpeechSynthesisUtteranceClass: FakeUtterance },
    );
    await vi.waitFor(() => expect(document.querySelector('.language-listening-player')).not.toBeNull());
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Play').click();
    expect(api.startListeningSession).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(synthesis.speak).toHaveBeenCalledOnce());
    utterance.onstart();
    await vi.waitFor(() => expect(api.startListeningSession).toHaveBeenCalledOnce());
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.waitFor(() => expect(api.recordListeningEvent).toHaveBeenCalledOnce());
    expect(api.recordListeningEvent.mock.calls[0][1]).toMatchObject({
      outcome: 'CANCELLED', playbackSource: 'BROWSER_TTS', durationMs: null,
    });
    expect(synthesis.cancel).toHaveBeenCalledOnce();
    app.destroy();
  });

  it('shows a useful bootstrap error instead of a blank screen', async () => {
    window.happyDOM.setURL('http://localhost/language.html#overview');
    const api = fakeApi({ health: vi.fn(async () => { throw new Error('offline'); }) });
    const app = createLanguageApp({ api });
    app.start();
    await vi.waitFor(() => expect(document.querySelector('#language-view').textContent).toContain('offline'));
    expect(document.querySelector('#language-connection').dataset.state).toBe('error');
    app.destroy();
  });

  it('shows a not-found lemma state and keeps the Vocabulary shell usable', async () => {
    const error = new LanguageApiError('Lemma was not found', { code: 'language_lemma_not_found', status: 404 });
    const { app } = await start(`http://localhost/language.html#vocabulary/lemma/${'d'.repeat(32)}`, {
      lemma: vi.fn(async () => { throw error; }),
    });
    await vi.waitFor(() => expect(document.querySelector('#language-lemma-detail').textContent).toContain('Lemma was not found'));
    expect(document.querySelector('[data-language-route="vocabulary"]').getAttribute('aria-current')).toBe('page');
    app.destroy();
  });

  it('falls back from invalid routes with a visible non-destructive notice', async () => {
    const { app } = await start('http://localhost/language.html#future');
    await vi.waitFor(() => expect(document.querySelector('#language-heading').textContent).toBe('Today'));
    expect(document.querySelector('#language-notice').hidden).toBe(false);
    expect(document.querySelector('#language-notice').textContent).toContain('not an available Language route');
    expect(window.location.hash).toBe('#overview');
    app.destroy();
  });
});
