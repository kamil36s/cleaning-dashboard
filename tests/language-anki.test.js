import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderLemmaDetail } from '../js/language/components/lemma-detail.js';
import { renderReviews } from '../js/language/views/reviews.js';
import { renderSettings } from '../js/language/views/settings.js';
import { renderAnkiInsights } from '../js/language/views/anki-insights.js';

const profile = {
  id: 'p'.repeat(32), displayName: 'Norwegian Bokmal', languageCode: 'nb', locale: 'nb-NO',
  translationLocales: ['en-GB'], status: 'ACTIVE', analyzerSettings: {},
};

const health = {
  canonicalAnalyzer: { runtimeState: 'LAZY_NOT_CREATED' },
  referenceProviders: { zipfFrequency: { id: 'wordfreq', version: '3.1.1', metric: 'ZIPF_FREQUENCY' } },
};

function lemmaDetail() {
  return {
    lemma: { id: 'a'.repeat(32), lemmaDisplay: 'jobb', lemmaNormalized: 'jobb', partOfSpeech: 'NOUN' },
    knowledge: { knowledgeStatus: 'NEW', disposition: 'TRACKED', totalExposures: 0 },
    forms: [], frequencies: [], events: [],
    anki: {
      status: { status: 'NOT_CHECKED' }, linked: false, link: null, cards: [],
    },
  };
}

const noopLemmaHandlers = {
  onSave: vi.fn(), onLockMapping: vi.fn(), onSearchMerge: vi.fn(async () => []), onPrepareMerge: vi.fn(),
  onAnkiLink: vi.fn(), onAnkiResolve: vi.fn(),
};

describe('Language Phase 6 Anki UI', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="mount"></main>';
    vi.clearAllMocks();
  });

  it('renders material status in advanced-to-unseen order with percentages totaling 100', () => {
    const root = renderAnkiInsights({
      deckName: 'Norwegian',
      inventory: { totalCards: 10, matchedVocabularyCards: 0, newRemaining: 1,
        materialProgress: { mature: 6, learningYoung: 2, unseen: 1, suspended: 1 } },
      today: { new: 0, learning: 0, reviewsDue: 0, newIntroduced: 0, reviewAnswers: 0,
        answered: 0, again: 0, hard: 0, good: 0, easy: 0 },
      limits: { newPerDay: 0, reviewsPerDay: 0 }, cards: { items: [], total: 0, offset: 0, limit: 50 },
    });
    expect([...root.querySelectorAll('.language-anki-material-segment')].map((item) => item.className))
      .toEqual(['language-anki-material-segment is-mature', 'language-anki-material-segment is-learningYoung',
        'language-anki-material-segment is-unseen', 'language-anki-material-segment is-suspended']);
    expect([...root.querySelectorAll('.language-anki-material-name span')].map((item) => item.textContent))
      .toEqual(['Mature', 'Learning / Young', 'Unseen', 'Suspended']);
    expect([...root.querySelectorAll('.language-anki-material-percent')].map((item) => item.textContent))
      .toEqual(['60%', '20%', '10%', '10%']);
    expect([...root.querySelectorAll('.language-anki-material-segment')].map((item) => Number(item.style.flexGrow)))
      .toEqual([6, 2, 1, 1]);
  });

  it('omits suspended when zero and distributes rounding remainders exactly', () => {
    const root = renderAnkiInsights({
      deckName: 'Norwegian',
      inventory: { totalCards: 3, matchedVocabularyCards: 0, newRemaining: 1,
        materialProgress: { mature: 1, learningYoung: 1, unseen: 1, suspended: 0 } },
      today: { new: 0, learning: 0, reviewsDue: 0, newIntroduced: 0, reviewAnswers: 0,
        answered: 0, again: 0, hard: 0, good: 0, easy: 0 },
      limits: { newPerDay: 0, reviewsPerDay: 0 }, cards: { items: [], total: 0, offset: 0, limit: 50 },
    });
    expect(root.querySelector('.language-anki-material .is-suspended')).toBeNull();
    expect([...root.querySelectorAll('.language-anki-material-percent')].map((item) => item.textContent))
      .toEqual(['34%', '33%', '33%']);
  });

  it('saves server-side settings and exposes read-only discovery controls', async () => {
    const onSaveAnki = vi.fn(async () => ({}));
    const onTestAnki = vi.fn(async () => ({ status: { status: 'CONNECTED' } }));
    const onDiscoverAnki = vi.fn(async () => ({ decks: ['Language'], models: ['Dashboard'], fields: ['Front'] }));
    renderSettings(document.querySelector('#mount'), {
      profile, health, onSaveProfile: vi.fn(), onSaveAnki, onTestAnki, onDiscoverAnki,
      anki: {
        status: { status: 'CONNECTED', linkedVocabulary: 2, conflicts: 0 },
        config: { enabled: true, endpoint: 'http://127.0.0.1:8765', deckName: 'Language', modelName: 'Dashboard', fieldMap: { target: 'Front' }, apiKeyConfigured: true },
      },
    });
    expect(document.querySelector('.language-anki-settings').textContent).toContain('Configured on server');
    const form = document.querySelector('.language-anki-settings form');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(onSaveAnki).toHaveBeenCalledWith(expect.objectContaining({
      enabled: true, endpoint: 'http://127.0.0.1:8765', fieldMap: { target: 'Front' },
    })));
    [...document.querySelectorAll('.language-anki-settings button')].find((item) => item.textContent.startsWith('Refresh')).click();
    await vi.waitFor(() => expect(document.querySelector('.language-anki-settings').textContent).toContain('Decks: Language'));
  });

  it('shows exact preview, requires confirmation, and renders conflict choices', async () => {
    const onAnkiCommit = vi.fn(async () => ({}));
    const onAnkiResolve = vi.fn(async () => ({}));
    const preview = {
      action: 'CONFLICT', deckName: 'Language', modelName: 'Dashboard', existingNoteId: 123,
      logicalFields: { context: 'Jeg liker jobben.', translation: '', definition: '' },
      mappedFields: { Front: 'jobb' }, previewFingerprint: 'sha256:test',
      conflicts: [{ field: 'Front', lastSynced: 'jobb', dashboardProposed: 'jobb!', ankiCurrent: 'edited' }],
    };
    renderLemmaDetail(document.querySelector('#mount'), lemmaDetail(), {
      ...noopLemmaHandlers, onAnkiPreview: vi.fn(async () => preview), onAnkiCommit, onAnkiResolve,
    });
    [...document.querySelectorAll('.language-anki-section button')].find((item) => item.textContent.includes('Preview add')).click();
    await vi.waitFor(() => expect(document.querySelector('.language-anki-preview').textContent).toContain('Jeg liker jobben.'));
    expect(document.querySelector('.language-anki-preview').textContent).toContain('Dashboard proposed');
    expect([...document.querySelectorAll('.language-anki-preview button')].find((item) => item.textContent === 'Confirm Anki change').disabled).toBe(true);
    [...document.querySelectorAll('.language-anki-preview button')].find((item) => item.textContent === 'Keep Anki').click();
    await vi.waitFor(() => expect(onAnkiResolve).toHaveBeenCalledWith('ANKI_WINS'));
    expect(onAnkiCommit).not.toHaveBeenCalled();
  });

  it('renders linked metadata without exposing raw provider JSON', () => {
    const detail = lemmaDetail();
    detail.anki = {
      status: { status: 'NOT_CHECKED' }, linked: true,
      link: { externalNoteId: 42, deckName: 'Language', modelName: 'Dashboard', conflictState: 'NONE', lastSyncAt: '2026-09-16T10:00:00Z' },
      cards: [{ externalCardId: 99, due: 10, reviews: 2 }],
    };
    renderLemmaDetail(document.querySelector('#mount'), detail, { ...noopLemmaHandlers, onAnkiPreview: vi.fn() });
    expect(document.querySelector('.language-anki-section').textContent).toContain('Linked note 42');
    expect(document.querySelector('.language-anki-section').textContent).toContain('Observed cards1');
    expect(document.querySelector('.language-anki-section').textContent).not.toContain('raw_supported_json');
  });

  it('keeps Reviews as an Anki orchestrator rather than a scheduler', async () => {
    const onPull = vi.fn(async () => ({ run: { status: 'COMPLETED', counts: { succeeded: 2 } } }));
    const onSyncWeb = vi.fn(async () => ({ syncedAt: '2026-09-26T10:00:00Z' }));
    renderReviews(document.querySelector('#mount'), {
      loading: false,
      status: {
        status: 'CONNECTED', dueCount: 3, linkedVocabulary: 2, conflicts: 1,
        config: { enabled: true, deckName: 'Norwegian A1 Words & Sentences [3.1k]' },
        connection: { supported: true },
        deck: { name: 'Norwegian A1 Words & Sentences [3.1k]', new: 0, learn: 0, due: 3, answeredCardsToday: 12 },
      },
      runs: [{ mode: 'PULL', status: 'PARTIAL', startedAt: '2026-09-16T10:00:00Z', counts: { succeeded: 1, failed: 1 } }],
    }, { onPull, onSyncWeb, onRefresh: vi.fn() });
    expect(document.querySelector('#mount').textContent).toContain('Anki remains the scheduler');
    expect(document.querySelector('#mount').textContent).toContain('Due cards3');
    expect(document.querySelector('#mount').textContent).toContain('Distinct cards answered today12');
    [...document.querySelectorAll('button')].find((item) => item.textContent === 'Sync AnkiWeb now').click();
    await vi.waitFor(() => expect(onSyncWeb).toHaveBeenCalledTimes(1));
    document.querySelector('.language-button.is-primary').click();
    await vi.waitFor(() => expect(onPull).toHaveBeenCalledTimes(1));
  });

  it('separates Anki due ownership from dashboard practice queues', () => {
    renderReviews(document.querySelector('#mount'), {
      loading: false, status: { status: 'CONNECTED', dueCount: 3 }, runs: [],
      cloze: {
        summary: { mistakeTargets: 2, attempts: 5, correct: 3, incorrect: 2, accuracy: 60 },
        practiceModes: { review: { targetCount: 4 }, curriculum: { packs: [{ id: 'starter' }] } },
      },
    }, { onPull: vi.fn(), onRefresh: vi.fn() });
    expect([...document.querySelectorAll('[data-review-kind]')].map((item) => item.dataset.reviewKind)).toEqual([
      'ANKI_DUE', 'CLOZE_PRACTICE', 'MISTAKE_REMEDIATION', 'CLOZE_RECYCLE',
      'READER_REVISIT', 'LISTENING_PRACTICE', 'CURRICULUM_PRACTICE', 'MISTAKE_RECOVERIES',
    ]);
    expect(document.body.textContent).toContain('Anki remains the scheduler');
    expect(document.body.textContent).toContain('They never create Anki due dates');
    expect(document.body.textContent).toContain('LISTENING PRACTICE');
    expect(document.body.textContent).toContain('not SRS due work');
  });

  it('renders explainable mistake priority, recovery, and bounded evidence details', async () => {
    const onMistakeDetail = vi.fn(async () => ({ cluster: {
      explanation: 'Two direct canonical failures.', evidenceTruncated: false,
      evidence: [{ outcome: 'INCORRECT', attemptedAt: '2026-09-17T10:00:00Z', questionType: 'TYPED', expectedSurface: 'kjenne', userAnswer: 'vite', sourceContextType: 'READER', sentenceId: 'sentence-1' }],
    } }));
    renderReviews(document.querySelector('#mount'), {
      loading: false, status: { status: 'NOT_CONFIGURED' }, runs: [], cloze: { summary: {} },
      mistakes: { summary: {
        activeClusterCount: 1, historicalIncorrectCount: 2, sourceAvailability: { ankiReviewHistory: 'NOT_SUPPORTED' },
        topProblems: [{
          id: 'mi_test', category: 'DIRECTIONAL_CONFUSION', severity: 'HIGH', state: 'ACTIVE',
          title: 'kjenne is repeatedly answered as vite', historicalFailureCount: 2, laterSuccessCount: 0,
          target: { lemma: 'kjenne' },
        }],
        recentRecoveries: [{ target: { lemma: 'jobb' }, state: 'RECOVERED', laterSuccessCount: 2, laterSuccessDates: 2 }],
      } },
    }, { onPull: vi.fn(), onRefresh: vi.fn(), onMistakeDetail });
    expect(document.body.textContent).toContain('HIGH / ACTIVE');
    expect(document.body.textContent).toContain('Anki mistake eventsNOT_SUPPORTED');
    expect(document.body.textContent).toContain('jobbRECOVERED');
    [...document.querySelectorAll('button')].find((item) => item.textContent === 'Details').click();
    await vi.waitFor(() => expect(onMistakeDetail).toHaveBeenCalledWith('mi_test'));
    expect(document.querySelector('.language-mistake-detail').textContent).toContain('supplied vite');
    expect(document.querySelector('a[href="#cloze"]')).not.toBeNull();
  });
});
