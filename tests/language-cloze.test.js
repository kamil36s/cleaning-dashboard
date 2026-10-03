import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createLanguageApi } from '../js/language/api.js';
import { parseLanguageRoute, routeHeading } from '../js/language/router.js';
import { renderCloze } from '../js/language/views/cloze.js';

function tracks(overrides = {}) {
  return {
    status: 'READY', activeSessionId: null,
    items: [
      { key: 'FAST_TRACK_1', label: 'Fast Track 1', rankLabel: 'KELLY', rankMin: 1, rankMax: 500, targets: 420, encountered: 12, playableTargets: 311 },
      { key: 'FAST_TRACK_2', label: 'Fast Track 2', rankLabel: 'KELLY', rankMin: 501, rankMax: 1000, targets: 428, encountered: 7, playableTargets: 321 },
    ],
    summary: { attempts: 4, correct: 3, incorrect: 1, accuracy: 75, mistakeTargets: 1 },
    ...overrides,
  };
}

function item(overrides = {}) {
  return {
    index: 0, fingerprint: 'sha256:item', sentenceText: 'Jeg jobber på lageret.',
    blankStart: 4, blankEnd: 10, options: ['går', 'jobber', 'sover', 'leser'],
    translation: { languageCode: 'en', text: 'I work at the warehouse.', sentenceId: '456', license: 'CC0-1.0' },
    source: { sentenceId: '123', license: 'CC BY 2.0 FR' },
    ...overrides,
  };
}

function session(overrides = {}) {
  return {
    id: 's'.repeat(32), trackKey: 'FAST_TRACK_1', actualItemCount: 10,
    answeredCount: 0, status: 'ACTIVE', currentItem: item(), ...overrides,
  };
}

function actions() {
  return {
    onStart: vi.fn(), onResume: vi.fn(), onAnswer: vi.fn(), onReveal: vi.fn(),
    onTypedAnswer: vi.fn(), onSkip: vi.fn(), onNext: vi.fn(), onReport: vi.fn(), onBack: vi.fn(),
    onPlayAudio: vi.fn(), onPreferences: vi.fn(),
  };
}

describe('Language Phase 9A Cloze UI', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="mount"></main>'; });

  it('renders Fast Track coverage and starts the selected 10/20/50 session', () => {
    const handlers = actions();
    renderCloze(document.querySelector('#mount'), { tracks: tracks(), attempts: [] }, handlers);
    expect(document.body.textContent).toContain('311 playable');
    document.querySelectorAll('.language-cloze-track')[1].click();
    const length = document.querySelector('[aria-label="Session length"]');
    expect([...length.options].map((option) => option.value)).toEqual(['10', '20', '50']);
    length.value = '20';
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Start Fast Track').click();
    expect(handlers.onStart).toHaveBeenCalledWith({ mode: 'FAST_TRACK', trackKey: 'FAST_TRACK_2', itemCount: 20 });
    [...document.querySelectorAll('button')].find((button) => button.textContent.includes('Recycle')).click();
    expect(handlers.onStart).toHaveBeenCalledWith({ mode: 'RECYCLE_MISTAKES', trackKey: 'FAST_TRACK_2', itemCount: 20 });
  });

  it('renders sentence content as text, four choices, progress, and attribution', () => {
    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session({ currentItem: item({ sentenceText: '<img src=x onerror=alert(1)> jobber.' }) }), attempts: [],
    }, actions());
    expect(document.querySelector('.language-cloze-sentence').textContent).toContain('<img');
    expect(document.querySelector('.language-cloze-sentence img')).toBeNull();
    expect(document.querySelectorAll('.language-cloze-option')).toHaveLength(4);
    expect([...document.querySelectorAll('.language-cloze-option strong')]).toHaveLength(0);
    expect(document.querySelector('.language-cloze-blank').textContent).toBe('');
    expect(document.body.textContent).toContain('Question 1 of 10');
    expect(document.body.textContent).toContain('Tatoeba #123');
  });

  it('replaces the answer gap with a normally sized inspectable word', () => {
    const sentenceText = 'Du har vært gjennom mye.';
    const blankStart = sentenceText.indexOf('gjennom');
    const current = item({ sentenceText, blankStart, blankEnd: blankStart + 'gjennom'.length });
    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session({ currentItem: item({ index: 1 }) }), lastItem: current,
      feedback: { outcome: 'CORRECT', expectedSurfaceForm: 'gjennom' }, attempts: [],
    }, { ...actions(), onLookupSurface: vi.fn(async () => ({ translations: {} })) });
    expect(document.querySelector('.language-cloze-blank.is-revealed').textContent).toBe('gjennom');
    expect(document.querySelector('.language-cloze-blank .language-reader-token')).not.toBeNull();
  });

  it('supports number-only answer shortcuts and Enter for Next feedback', () => {
    const answerHandlers = actions();
    const cleanup = renderCloze(document.querySelector('#mount'), { tracks: tracks(), session: session(), attempts: [] }, answerHandlers);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '2', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'D', bubbles: true }));
    expect(answerHandlers.onAnswer.mock.calls).toEqual([[1]]);
    cleanup();

    const nextHandlers = actions();
    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session({ currentItem: item({ index: 1 }) }), lastItem: item(), attempts: [],
      feedback: { outcome: 'INCORRECT', chosenOption: 'går', expectedSurfaceForm: 'jobber', targetLemmaDisplay: 'jobbe', rankLabel: 'KELLY', kellyLearnerRank: 12 },
    }, nextHandlers);
    expect(document.querySelector('.language-cloze-option.is-correct').textContent).toContain('jobber');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(nextHandlers.onNext).toHaveBeenCalledOnce();
  });

  it('shows English translation before, after, or never according to the preference', () => {
    const handlers = actions();
    const base = { tracks: tracks(), session: session(), attempts: [] };
    renderCloze(document.querySelector('#mount'), {
      ...base, preferences: { translationTiming: 'BEFORE' },
    }, handlers);
    expect(document.querySelector('.language-cloze-translation').textContent).toContain('I work at the warehouse.');

    renderCloze(document.querySelector('#mount'), {
      ...base, preferences: { translationTiming: 'AFTER' },
    }, handlers);
    expect(document.querySelector('.language-cloze-translation')).toBeNull();

    const feedback = { outcome: 'CORRECT', expectedSurfaceForm: 'jobber', chosenOption: 'jobber', targetLemmaDisplay: 'jobbe', rankLabel: 'KELLY', kellyLearnerRank: 12, translation: item().translation };
    renderCloze(document.querySelector('#mount'), {
      ...base, session: session({ currentItem: item({ index: 1 }) }), lastItem: item(), feedback,
      preferences: { translationTiming: 'AFTER' },
    }, handlers);
    expect(document.querySelector('.language-cloze-translation').textContent).toContain('I work at the warehouse.');

    renderCloze(document.querySelector('#mount'), {
      ...base, session: session({ currentItem: item({ index: 1 }) }), lastItem: item(), feedback,
      preferences: { translationTiming: 'OFF' },
    }, handlers);
    expect(document.querySelector('.language-cloze-translation')).toBeNull();
  });

  it('offers cached full-sentence audio states and configurable translation preferences', () => {
    const handlers = actions();
    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session(), attempts: [],
      preferences: { translationTiming: 'AFTER' }, audio: { status: 'IDLE', itemKey: '', error: null },
    }, handlers);
    document.querySelector('.language-cloze-listen').click();
    expect(handlers.onPlayAudio).toHaveBeenCalledWith(expect.objectContaining({ sentenceText: expect.any(String) }));
    expect(document.querySelector('[aria-label="Norwegian voice"]')).toBeNull();
    const timing = document.querySelector('[aria-label="Show English translation"]');
    timing.value = 'BEFORE';
    timing.dispatchEvent(new Event('change'));
    expect(handlers.onPreferences).toHaveBeenCalledWith({ translationTiming: 'BEFORE' });

    const key = `${session().id}:${item().index}:${item().fingerprint}`;
    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session(), attempts: [], preferences: { translationTiming: 'AFTER' },
      audio: { status: 'LOADING', itemKey: key, error: null },
    }, handlers);
    expect(document.querySelector('.language-cloze-listen').textContent).toContain('Generating audio');
    expect(document.querySelector('.language-cloze-listen').disabled).toBe(true);

    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session(), attempts: [], preferences: { translationTiming: 'AFTER' },
      audio: { status: 'ERROR', itemKey: key, error: 'Google TTS unavailable' },
    }, handlers);
    expect(document.querySelector('.language-cloze-audio-error').textContent).toBe('Google TTS unavailable');
  });

  it('offers reveal, skip, reporting, resume, and completion navigation', () => {
    const handlers = actions();
    renderCloze(document.querySelector('#mount'), { tracks: tracks({ activeSessionId: 'active' }), attempts: [] }, handlers);
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Continue active session').click();
    expect(handlers.onResume).toHaveBeenCalledWith('active');

    renderCloze(document.querySelector('#mount'), { tracks: tracks(), session: session(), attempts: [] }, handlers);
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Reveal').click();
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Skip').click();
    document.querySelector('[aria-label="Bad question reason"]').value = 'BAD_DISTRACTORS';
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Report bad question').click();
    expect(handlers.onReveal).toHaveBeenCalledOnce();
    expect(handlers.onSkip).toHaveBeenCalledOnce();
    expect(handlers.onReport).toHaveBeenCalledWith('BAD_DISTRACTORS');

    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session({ status: 'COMPLETED', currentItem: null, answeredCount: 10 }),
      attempts: [{ outcome: 'CORRECT' }, { outcome: 'INCORRECT' }],
    }, handlers);
    expect(document.body.textContent).toContain('10 questions finished');
    expect(document.querySelector('a[href="#reviews"]')).not.toBeNull();
  });

  it('starts shared review and frozen curriculum practice with an explicit answer style', () => {
    const handlers = actions();
    renderCloze(document.querySelector('#mount'), { tracks: tracks({
      practiceModes: {
        review: { available: true, targetCount: 4, sourceTargetCounts: { READER: 2, PHRASEBOOK: 1, GENERATED: 1 } },
        curriculum: { available: true, packs: [{ id: 'starter', version: '3', name: 'Starter', eligibleTargets: 12 }] },
      },
    }), attempts: [] }, handlers);
    const length = document.querySelector('[aria-label="Shared practice session length"]');
    const style = document.querySelector('[aria-label="Shared practice answer style"]');
    length.value = '20'; style.value = 'TYPED';
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Start review practice').click();
    expect(handlers.onStart).toHaveBeenCalledWith({ mode: 'REVIEW', itemCount: 20, questionType: 'TYPED' });
    style.value = 'MULTIPLE_CHOICE';
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Practice curriculum pack').click();
    expect(handlers.onStart).toHaveBeenCalledWith({
      mode: 'CURRICULUM', curriculumPackId: 'starter', curriculumVersion: '3', itemCount: 20,
      questionType: 'MULTIPLE_CHOICE',
    });
    expect(document.body.textContent).toContain('Anki alone owns due scheduling');
  });

  it('submits a bounded typed answer on Enter and exposes source-aware feedback', async () => {
    const handlers = actions();
    const typedItem = item({
      questionType: 'TYPED', options: [], sentenceText: 'Jeg drikker øl.', blankStart: 12, blankEnd: 14,
      sourceContextType: 'READER', targetLemmaId: 'lemma-id', targetLemmaDisplay: 'øl',
      source: { sentenceId: 'reader-sentence', sourceEntityId: 'reader-document' },
    });
    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session({ mode: 'REVIEW', trackKey: 'SHARED_REVIEW', currentItem: typedItem }), attempts: [],
    }, handlers);
    const input = document.querySelector('[aria-label="Typed Cloze answer"]');
    expect(input.maxLength).toBe(200);
    input.value = ' ØL ';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    input.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(handlers.onTypedAnswer).toHaveBeenCalledWith(' ØL ');

    renderCloze(document.querySelector('#mount'), {
      tracks: tracks(), session: session({ mode: 'REVIEW', trackKey: 'SHARED_REVIEW', currentItem: item({ index: 1 }) }),
      lastItem: typedItem, attempts: [], feedback: {
        outcome: 'INCORRECT', questionType: 'TYPED', userAnswer: 'øllet', expectedSurfaceForm: 'øl',
        targetLemmaDisplay: 'øl', sourceContextType: 'READER', source: typedItem.source,
      },
    }, handlers);
    expect(document.querySelector('[role="status"]').textContent).toContain('Your answer: øllet');
    expect(document.body.textContent).toContain('Source: Reader #reader-sentence');
    expect(document.querySelector('a[href="#vocabulary/lemma/lemma-id"]')).not.toBeNull();
    await Promise.resolve();
    expect(document.activeElement.textContent).toBe('Next');
  });

  it('exposes the Cloze route and calls the bounded API endpoints', async () => {
    expect(parseLanguageRoute('#cloze')).toEqual({ name: 'cloze', valid: true });
    expect(routeHeading({ name: 'cloze' })).toBe('Cloze');
    const fetchImpl = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, data: {} }) }));
    const api = createLanguageApi({ fetchImpl });
    await api.clozeTracks('profile id');
    await api.startClozeSession('profile id', { itemCount: 10 });
    await api.submitClozeAttempt('session id', { action: 'SKIP' });
    await api.reportClozeItem('session id', { reason: 'OTHER' });
    await api.clozeAudio('session id', 2, { itemFingerprint: 'fingerprint' });
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/profiles/profile%20id/cloze/tracks',
      '/api/language/profiles/profile%20id/cloze/sessions',
      '/api/language/cloze/sessions/session%20id/attempts',
      '/api/language/cloze/sessions/session%20id/report',
      '/api/language/cloze/sessions/session%20id/items/2/audio',
    ]);
  });
});
