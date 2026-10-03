import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createActiveReadingTracker,
  createSentenceExposureObserver,
  renderExactReaderText,
  renderReaderDocument,
  renderReaderLibrary,
  sentenceOccurrences,
} from '../js/language/views/reader.js';

function cpOffset(text, needle, from = 0) {
  const utf16 = text.indexOf(needle, from);
  return { start: [...text.slice(0, utf16)].length, end: [...text.slice(0, utf16 + needle.length)].length, utf16 };
}

describe('Language Reader exact rendering', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    document.body.replaceChildren();
  });

  it('preserves exact source text safely across emoji, spacing, lines, Norwegian text and hostile markup', () => {
    const raw = '😊 jobb  jobben\n«jobber» jobbene æ ø å <script>alert(1)</script>';
    const words = ['jobb', 'jobben', 'jobber', 'jobbene'];
    let cursor = 0;
    const tokens = words.map((surface, index) => {
      const offset = cpOffset(raw, surface, cursor);
      cursor = offset.utf16 + surface.length;
      return {
        id: String(index), sentenceId: 'sentence', tokenOrder: index, surface,
        sourceStart: offset.start, sourceEnd: offset.end, tokenKind: 'WORD',
        selectedLemmaId: 'lemma', selectedLemmaDisplay: 'jobb', knowledgeStatus: 'LEARNING',
        disposition: 'TRACKED', resolutionState: 'MODEL_SELECTED',
      };
    });
    const opened = vi.fn();
    const mount = document.createElement('div');
    document.body.append(mount);
    const root = renderExactReaderText({
      mount, rawText: raw,
      sentences: [{ id: 'sentence', sentenceOrder: 0, sourceStart: 0, sourceEnd: [...raw].length }],
      tokens, documentRef: document, onOpenLemma: opened,
    });
    expect(root.textContent).toBe(raw);
    expect(root.querySelector('script')).toBeNull();
    expect(root.querySelectorAll('[data-lemma-id]')).toHaveLength(4);
    expect([...root.querySelectorAll('.language-reader-token')].every((item) => !item.hasAttribute('title'))).toBe(true);
    expect([...root.querySelectorAll('[data-lemma-id]')].every((item) => item.classList.contains('is-learning'))).toBe(true);
    root.querySelector('[data-lemma-id]').click();
    expect(opened).toHaveBeenCalledWith('lemma', { tokenId: '0', sentenceId: 'sentence' });
  });

  it('aggregates repeated linked forms once per sentence batch', () => {
    const tokens = [
      { sentenceId: 's', tokenKind: 'WORD', selectedLemmaId: 'jobb' },
      { sentenceId: 's', tokenKind: 'WORD', selectedLemmaId: 'jobb' },
      { sentenceId: 's', tokenKind: 'WORD', selectedLemmaId: 'bok' },
      { sentenceId: 's', tokenKind: 'PUNCTUATION', selectedLemmaId: null },
    ];
    expect(sentenceOccurrences(tokens, 's')).toEqual([
      { lemmaId: 'bok', occurrenceCount: 1 },
      { lemmaId: 'jobb', occurrenceCount: 2 },
    ]);
  });

  it('renders several thousand tokens by sentence with delegated interaction', () => {
    const count = 3500;
    const raw = Array.from({ length: count }, () => 'jobb').join(' ');
    const tokens = [];
    let codePoint = 0;
    for (let index = 0; index < count; index += 1) {
      tokens.push({
        id: String(index), sentenceId: 'long', tokenOrder: index, tokenKind: 'WORD',
        sourceStart: codePoint, sourceEnd: codePoint + 4, selectedLemmaId: 'lemma',
        knowledgeStatus: 'NEW', disposition: 'TRACKED', resolutionState: 'MODEL_SELECTED',
      });
      codePoint += index === count - 1 ? 4 : 5;
    }
    const mount = document.createElement('div');
    const started = performance.now();
    const root = renderExactReaderText({
      mount, rawText: raw, tokens, documentRef: document,
      sentences: [{ id: 'long', sentenceOrder: 0, sourceStart: 0, sourceEnd: [...raw].length }],
    });
    const elapsed = performance.now() - started;
    expect(root.textContent).toBe(raw);
    expect(root.querySelectorAll('[data-token-id]')).toHaveLength(count);
    expect(elapsed).toBeGreaterThanOrEqual(0);
  });

  it('offers sentence audio only for accepted generated texts and highlights playback', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const onPlayAudio = vi.fn(async (sentence, callbacks) => { callbacks.onPlaying(); });
    const handlers = {
      onOpenLemma: vi.fn(), onSaveExpression: vi.fn(), onAnalyze: vi.fn(), onStart: vi.fn(),
      onPause: vi.fn(), onComplete: vi.fn(), onPlayAudio,
      onPauseAudio: vi.fn(), onResumeAudio: vi.fn(async () => {}), onStopAudio: vi.fn(),
    };
    const payload = {
      document: { id: 'a'.repeat(32), title: 'Generated', rawText: 'Jeg jobber.', sourceType: 'GENERATED_GEMINI', processingState: 'ANALYZED' },
      sentences: [{ id: 'b'.repeat(32), sentenceOrder: 0, sourceStart: 0, sourceEnd: 11, exactText: 'Jeg jobber.' }],
      tokens: [],
      coverage: { tokenCoveragePercent: 100, uniqueLemmaCoveragePercent: 100 },
      readingProgress: null, latestJob: null, referenceProfile: { available: false }, analysisRuns: [],
    };
    const view = renderReaderDocument(mount, payload, handlers);
    expect(mount.querySelector('.language-reader-audio-strip')).not.toBeNull();
    expect(document.body.textContent).toContain('Play text');
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Play current sentence').click();
    await vi.waitFor(() => expect(onPlayAudio).toHaveBeenCalledWith(payload.sentences[0], expect.any(Object)));
    expect(view.source.querySelector('[data-sentence-id]').classList.contains('is-audio-playing')).toBe(true);
    expect(view.source.querySelector('[data-sentence-id]').getAttribute('aria-current')).toBe('true');
    view.destroy();
    expect(handlers.onStopAudio).toHaveBeenCalled();

    mount.replaceChildren();
    renderReaderDocument(mount, {
      ...payload, document: { ...payload.document, sourceType: 'PASTED' },
    }, handlers);
    expect(mount.querySelector('.language-reader-audio-strip')).toBeNull();
  });

  it('plays a generated text sequentially through authoritative sentence audio', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const callbacks = [];
    const onPlayAudio = vi.fn(async (_sentence, handlers) => {
      callbacks.push(handlers);
      handlers.onPlaying();
    });
    const sentences = [
      { id: 'a'.repeat(32), sentenceOrder: 0, sourceStart: 0, sourceEnd: 11, exactText: 'Jeg jobber.' },
      { id: 'b'.repeat(32), sentenceOrder: 1, sourceStart: 11, sourceEnd: 21, exactText: ' Du leser.' },
    ];
    const view = renderReaderDocument(mount, {
      document: { id: 'c'.repeat(32), title: 'Generated', rawText: 'Jeg jobber. Du leser.', sourceType: 'GENERATED_GEMINI', processingState: 'ANALYZED' },
      sentences, tokens: [], coverage: { tokenCoveragePercent: 100, uniqueLemmaCoveragePercent: 100 },
      readingProgress: null, latestJob: null, referenceProfile: { available: false }, analysisRuns: [],
    }, {
      onOpenLemma: vi.fn(), onSaveExpression: vi.fn(), onAnalyze: vi.fn(), onStart: vi.fn(),
      onPause: vi.fn(), onComplete: vi.fn(), onPlayAudio,
      onPauseAudio: vi.fn(), onResumeAudio: vi.fn(async () => {}), onStopAudio: vi.fn(),
    });
    [...mount.querySelectorAll('button')].find((button) => button.textContent === 'Play text').click();
    await vi.waitFor(() => expect(onPlayAudio).toHaveBeenCalledTimes(1));
    callbacks[0].onEnded();
    await vi.waitFor(() => expect(onPlayAudio).toHaveBeenCalledTimes(2));
    expect(onPlayAudio.mock.calls[1][0]).toBe(sentences[1]);
    expect(view.source.querySelector(`[data-sentence-id="${sentences[1].id}"]`).getAttribute('aria-current')).toBe('true');
    callbacks[1].onEnded();
    expect(mount.textContent).toContain('Text finished');
  });

  it('offers a native play control when browser playback is blocked after audio is prepared', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const sentence = { id: 'b'.repeat(32), sentenceOrder: 0, sourceStart: 0, sourceEnd: 11, exactText: 'Jeg jobber.' };
    const onPlayAudio = vi.fn(async (_sentence, callbacks) => {
      callbacks.onReady('/api/language/audio/test.mp3');
      callbacks.onError(new Error('Playback blocked'));
    });
    const view = renderReaderDocument(mount, {
      document: { id: 'a'.repeat(32), title: 'Generated', rawText: 'Jeg jobber.', sourceType: 'GENERATED_GEMINI', processingState: 'ANALYZED' },
      sentences: [sentence], tokens: [], coverage: {}, readingProgress: null, referenceProfile: {}, analysisRuns: [],
    }, { onPlayAudio, onStopAudio: vi.fn(), onSaveExpression: vi.fn() });
    mount.querySelector('.language-reader-audio-strip button').click();
    await vi.waitFor(() => expect(mount.querySelector('audio').hidden).toBe(false));
    expect(mount.querySelector('audio').getAttribute('src')).toBe('/api/language/audio/test.mp3');
    expect(mount.querySelector('.language-reader-audio-status').textContent).toContain('Use the audio player below');
    view.destroy();
  });
});

describe('Language Reader library', () => {
  afterEach(() => document.body.replaceChildren());

  it('shows known, learning and new shares among classified words with a clear denominator', () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    renderReaderLibrary(mount, {
      loading: false, total: 1, jobs: new Map(), items: [{
        id: 'text-1', title: 'En rolig lørdag', sourceType: 'GENERATED_MANUAL_LLM',
        processingState: 'ANALYZED', readingStatus: 'NOT_STARTED',
        latestJobId: 'job-1', latestJobState: 'COMPLETED', latestJobStage: 'COMPLETED', latestJobProgress: 1,
        coverage: {
          coveredTokens: 5, ignoredTokens: 1, learningTokens: 3,
          unknownTokens: 1, ambiguousTokens: 2, excludedTokens: 1,
        },
      }],
    }, { onOpen: vi.fn(), onCreate: vi.fn(), onAnalyze: vi.fn(), onCancel: vi.fn() });
    const card = mount.querySelector('.language-reader-row');
    expect([...card.querySelectorAll('.language-reader-breakdown-stat')].map((item) => item.textContent))
      .toEqual(['50.0%Known · 4', '37.5%Learning · 3', '12.5%New · 1']);
    expect(card.textContent).toContain('Out of 8 words with a clear status');
    expect(card.textContent).toContain('4 ignored, unresolved or excluded words left out');
    expect(card.textContent).toContain('Generated text');
    expect(card.textContent).toContain('Not started');
    expect(card.textContent).not.toContain('COMPLETED');
    expect(card.textContent).not.toContain('Coverage:');
  });

  it('explains why a draft has no word percentages yet', () => {
    const mount = document.createElement('div');
    renderReaderLibrary(mount, {
      loading: false, total: 1, jobs: new Map(), items: [{
        id: 'text-2', title: 'Draft', sourceType: 'PASTED', processingState: 'DRAFT', readingStatus: 'NOT_STARTED',
      }],
    }, { onOpen: vi.fn(), onCreate: vi.fn(), onAnalyze: vi.fn(), onCancel: vi.fn() });
    expect(mount.textContent).toContain('Analyze this text to see known, learning and new words.');
    expect(mount.textContent).toContain('Added by you');
  });

  it('groups episodes and lets a saved text start the next episode', async () => {
    const mount = document.createElement('div');
    const onContinueSeries = vi.fn();
    const onAssignSeries = vi.fn(async () => {});
    const seriesId = 's'.repeat(32);
    const item = { id: 't'.repeat(32), title: 'The boat', seriesId, seriesTitle: 'Harbor', episodeNumber: 2,
      processingState: 'ANALYZED', readingStatus: 'IN_PROGRESS' };
    const first = { id: 'u'.repeat(32), title: 'The letter', seriesId, seriesTitle: 'Harbor', episodeNumber: 1,
      processingState: 'ANALYZED', readingStatus: 'COMPLETED' };
    renderReaderLibrary(mount, {
      loading: false, total: 2, jobs: new Map(), series: [{ id: seriesId, title: 'Harbor', episodeCount: 2 }], items: [item, first],
    }, { onOpen: vi.fn(), onCreate: vi.fn(), onAnalyze: vi.fn(), onCancel: vi.fn(),
      onCreateSeries: vi.fn(), onUpdateSeries: vi.fn(), onAssignSeries, onContinueSeries });
    expect(mount.querySelector('.language-reader-series h4').textContent).toBe('Harbor');
    expect([...mount.querySelectorAll('.language-reader-series .language-reader-row h3')].map((heading) => heading.textContent)).toEqual(['The letter', 'The boat']);
    expect([...mount.querySelectorAll('.language-reader-episode-label')].map((label) => label.textContent)).toEqual(['EPISODE 1', 'EPISODE 2']);
    [...mount.querySelectorAll('button')].filter((button) => button.textContent === 'Continue story').at(-1).click();
    expect(onContinueSeries).toHaveBeenCalledWith(item);
    const select = mount.querySelectorAll('.language-reader-series-select select')[1];
    select.value = ''; select.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(onAssignSeries).toHaveBeenCalledWith(item.id, null));
  });

  it('lets older texts be loaded for series assignment', () => {
    const mount = document.createElement('div');
    const onLoadMore = vi.fn();
    renderReaderLibrary(mount, {
      loading: false, total: 101, nextCursor: '100', jobs: new Map(), series: [], items: [{ id: 't', title: 'Recent', processingState: 'DRAFT' }],
    }, { onOpen: vi.fn(), onCreate: vi.fn(), onAnalyze: vi.fn(), onCancel: vi.fn(), onLoadMore });
    const button = [...mount.querySelectorAll('button')].find((item) => item.textContent.startsWith('Load more texts'));
    expect(button.textContent).toContain('1 of 101 shown');
    button.click();
    expect(onLoadMore).toHaveBeenCalledOnce();
  });
});

describe('Language Reader activity policy', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('heartbeats only while visible and explicitly active', () => {
    vi.useFakeTimers();
    let visibility = 'visible';
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
    const heartbeat = vi.fn();
    let tracker;
    tracker = createActiveReadingTracker({
      documentRef: document, windowRef: window, heartbeatMs: 10_000,
      onHeartbeat: heartbeat,
      onAutoPause: vi.fn(),
      onAutoResume: () => tracker.setActive(true),
    });
    tracker.setActive(true);
    vi.advanceTimersByTime(30_000);
    visibility = 'hidden';
    document.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(60_000);
    visibility = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(20_000);
    tracker.setActive(false);
    vi.advanceTimersByTime(20_000);
    expect(heartbeat).toHaveBeenCalledTimes(5);
    tracker.destroy();
  });

  it('records a segment only after the stable visible dwell and cancels pending dwell on pause', () => {
    vi.useFakeTimers();
    class FakeObserver {
      static instance;
      constructor(callback) { this.callback = callback; FakeObserver.instance = this; }
      observe() {}
      disconnect() {}
      emit(target, ratio) { this.callback([{ target, isIntersecting: ratio > 0, intersectionRatio: ratio }]); }
    }
    const root = document.createElement('div');
    const first = document.createElement('span');
    first.dataset.sentenceId = 'one';
    const second = document.createElement('span');
    second.dataset.sentenceId = 'two';
    root.append(first, second);
    const exposed = vi.fn();
    const observer = createSentenceExposureObserver({
      root, windowRef: window, IntersectionObserverClass: FakeObserver, dwellMs: 2_000,
      onExpose: exposed,
    });
    observer.setActive(true);
    FakeObserver.instance.emit(first, 0.7);
    vi.advanceTimersByTime(1_999);
    expect(exposed).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(exposed).toHaveBeenCalledWith(first);
    FakeObserver.instance.emit(second, 0.8);
    observer.setActive(false);
    vi.advanceTimersByTime(3_000);
    expect(exposed).toHaveBeenCalledTimes(1);
    observer.destroy();
  });

  it('rechecks an already visible sentence when study starts, retaining the full dwell requirement', () => {
    vi.useFakeTimers();
    const root = document.createElement('div');
    const sentence = document.createElement('span'); sentence.dataset.sentenceId = 'visible'; root.append(sentence);
    class VisibleObserver {
      constructor(callback) { this.callback = callback; }
      observe(target) { this.callback([{ target, isIntersecting: true, intersectionRatio: 1 }]); }
      unobserve() {}
      disconnect() {}
    }
    const onExpose = vi.fn();
    const tracker = createSentenceExposureObserver({ root, windowRef: window, IntersectionObserverClass: VisibleObserver, onExpose });
    vi.advanceTimersByTime(3000); expect(onExpose).not.toHaveBeenCalled();
    tracker.setActive(true); vi.advanceTimersByTime(1999); expect(onExpose).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1); expect(onExpose).toHaveBeenCalledOnce();
    tracker.setActive(false); tracker.setActive(true); vi.advanceTimersByTime(3000); expect(onExpose).toHaveBeenCalledOnce(); tracker.destroy();
  });
});
