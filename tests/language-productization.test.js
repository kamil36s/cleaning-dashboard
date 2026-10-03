import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToday } from '../js/language/views/overview.js';
import { renderExactReaderText } from '../js/language/views/reader.js';
import { appendInspectableWords, createLexicalInspector } from '../js/language/components/lexical-inspector.js';
import { renderLanguageHelp } from '../js/language/components/help.js';
import { renderCloze } from '../js/language/views/cloze.js';
import { renderListeningText } from '../js/language/views/listening.js';

afterEach(() => { vi.useRealTimers(); document.body.replaceChildren(); });

function readingFixture(updateStatus = vi.fn(async () => ({}))) {
  const rawText = 'Noen ser noen.';
  const sentences = [{ id: 's', sourceStart: 0, sourceEnd: 14, exactText: rawText, sentenceOrder: 0 }];
  const tokens = [
    { id: 'a', sentenceId: 's', tokenKind: 'WORD', sourceStart: 0, sourceEnd: 4, tokenOrder: 0, selectedLemmaId: 'lemma', selectedLemmaDisplay: 'noen', knowledgeStatus: 'NEW', disposition: 'TRACKED', resolutionState: 'MODEL_SELECTED' },
    { id: 'b', sentenceId: 's', tokenKind: 'WORD', sourceStart: 5, sourceEnd: 8, tokenOrder: 1, selectedLemmaId: 'other', selectedLemmaDisplay: 'se', knowledgeStatus: 'KNOWN', disposition: 'TRACKED', resolutionState: 'MODEL_SELECTED' },
    { id: 'c', sentenceId: 's', tokenKind: 'WORD', sourceStart: 9, sourceEnd: 13, tokenOrder: 2, selectedLemmaId: 'lemma', selectedLemmaDisplay: 'noen', knowledgeStatus: 'NEW', disposition: 'TRACKED', resolutionState: 'MODEL_SELECTED' },
  ];
  const mount = document.createElement('div'); document.body.append(mount);
  const root = renderExactReaderText({ mount, rawText, sentences, tokens });
  const preview = vi.fn(async () => ({ lemmaDisplay: 'noen', partOfSpeech: 'PRON', knowledgeStatus: 'NEW', translations: {
    user: [{ targetLocale: 'pl-PL', translationText: 'ktoś' }], learnerGlosses: [{ value: 'someone' }],
  } }));
  const full = vi.fn();
  const inspector = createLexicalInspector({ root, tokens, sentences, preview, updateStatus, openFull: full, savePhrase: vi.fn(async () => ({})), documentRef: document, windowRef: window });
  return { root, preview, updateStatus, full, inspector };
}

describe('Language productization', () => {
  it('provides concise route help and Reader shortcuts', () => {
    const mount = document.createElement('div');
    for (const route of ['overview', 'reader', 'cloze', 'listening', 'vocabulary', 'progress',
      'benchmarks', 'curriculum', 'inbox', 'reviews', 'generate', 'grammar', 'statistics', 'goals', 'settings']) {
      renderLanguageHelp(mount, route);
      expect(mount.querySelectorAll('h3')).toHaveLength(4);
      expect(mount.textContent).toContain('First action');
      if (route === 'reader') expect(mount.textContent).toContain('Enter opens word details');
    }
  });
  it('shows learner actions first and keeps owner labels truthful', () => {
    const mount = document.createElement('div');
    const start = vi.fn();
    renderToday(mount, {
      anki: { configured: true, dueCount: 4, stale: true, lastSyncAt: '2026-09-24T12:00:00Z' },
      cloze: { recommendedQuestionCount: 10, answeredToday: 3 }, reader: { continue: { id: 'text', title: 'Kort tekst' }, todaySeconds: 420 },
      level: { level: 2, lifetimeXp: 60 }, startHere: false,
    }, { onStartSession: start });
    expect(mount.querySelector('.language-today-hero')).not.toBeNull();
    expect(mount.textContent).toContain('4 due at last sync · stale');
    expect(mount.textContent).toContain('Reviews 0/5 · new sentences 0/3');
    expect(mount.textContent).toContain('Continue “Kort tekst”');
    mount.querySelectorAll('.language-today-duration button')[2].click();
    mount.querySelector('.language-today-start').click();
    expect(start).toHaveBeenCalledWith(30);
  });

  it('gives an empty-history learner a short first step', () => {
    window.localStorage.removeItem('language-start-here-dismissed-v1');
    const mount = document.createElement('div');
    renderToday(mount, { anki: { configured: false }, cloze: { answeredToday: 0 },
      reader: { todaySeconds: 0 }, level: { level: 1, lifetimeXp: 0 }, startHere: true }, {});
    expect(mount.querySelector('.language-today-onboarding')?.textContent).toContain('Begin with one small step');
    expect(mount.querySelector('.language-today-onboarding a[href="#reader"]')).not.toBeNull();
    expect(mount.querySelector('.language-today-onboarding a[href="#cloze"]')).not.toBeNull();
    mount.querySelector('.language-today-onboarding button').click();
    expect(mount.querySelector('.language-today-onboarding')).toBeNull();
    window.localStorage.removeItem('language-start-here-dismissed-v1');
  });

  it('debounces hover, caches read-only meaning, and opens compact detail', async () => {
    vi.useFakeTimers();
    const { root, preview, full, inspector } = readingFixture();
    const word = root.querySelector('[data-token-id="a"]');
    word.dispatchEvent(new Event('pointerover', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(200);
    expect(preview).not.toHaveBeenCalled();
    word.dispatchEvent(new Event('pointerout', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(400);
    expect(preview).not.toHaveBeenCalled();
    word.dispatchEvent(new Event('pointerover', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(330);
    expect(document.querySelector('.language-word-quick')?.textContent).toContain('someone');
    expect(preview).toHaveBeenCalledTimes(1);
    word.click();
    await Promise.resolve();
    expect(document.querySelector('.language-word-panel')?.textContent).toContain('ktoś');
    expect(full).not.toHaveBeenCalled();
    document.querySelector('.language-word-panel > .language-button').click();
    word.dispatchEvent(new Event('pointerover', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(330);
    expect(preview).toHaveBeenCalledTimes(1);
    inspector.destroy();
  });

  it('fills missing word meanings on hover and links to dictionary sources', async () => {
    vi.useFakeTimers();
    const root = document.createElement('p'); document.body.append(root);
    const tokens = appendInspectableWords(root, 'gjennom', { sentenceId: 's' });
    const fallbackLookup = vi.fn(async () => ({ translations: { machine: [
      { targetLocale: 'en', value: 'through' }, { targetLocale: 'pl', value: 'przez' },
    ] } }));
    const inspector = createLexicalInspector({ root, tokens, sentences: [{ id: 's', exactText: 'gjennom' }],
      surfaceLookup: vi.fn(async () => ({ translations: { user: [], learnerGlosses: [] } })),
      fallbackLookup, hoverDelayMs: 0 });
    root.querySelector('button').dispatchEvent(new Event('pointerover', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(1);
    expect(document.querySelector('.language-word-quick')?.textContent).toContain('through (automatic)');
    expect(document.querySelector('.language-word-quick')?.textContent).toContain('przez (automatic)');
    root.querySelector('button').click();
    await Promise.resolve();
    expect(document.querySelector('.language-word-sources a[href="https://en.wiktionary.org/wiki/gjennom"]')).not.toBeNull();
    expect(document.querySelector('.language-word-sources a[href="https://ordbokene.no/bm/gjennom"]')).not.toBeNull();
    expect(fallbackLookup).toHaveBeenCalledOnce();
    inspector.destroy();
  });

  it('switches English, Polish, and both without inventing missing translations', async () => {
    const { root, inspector, full } = readingFixture();
    root.querySelector('[data-token-id="a"]').click();
    await vi.waitFor(() => expect(document.querySelector('.language-word-panel')?.textContent).toContain('someone'));
    const panel = document.querySelector('.language-word-panel');
    const language = panel.querySelector('select');
    expect(panel.textContent).toContain('ktoś');
    language.value = 'en'; language.dispatchEvent(new Event('change', { bubbles: true }));
    expect(panel.textContent).toContain('someone');
    expect(panel.textContent).not.toContain('ktoś');
    language.value = 'pl'; language.dispatchEvent(new Event('change', { bubbles: true }));
    expect(panel.textContent).toContain('ktoś');
    expect(panel.textContent).not.toContain('someone');
    language.value = 'both'; language.dispatchEvent(new Event('change', { bubbles: true }));
    expect(panel.textContent).toContain('someone');
    expect(panel.textContent).toContain('ktoś');
    [...panel.querySelectorAll('button')].find((button) => button.textContent === 'Open full details').click();
    expect(full).toHaveBeenCalledWith('lemma', expect.objectContaining({ tokenId: 'a', sentenceId: 's' }));
    inspector.destroy();
  });

  it('keeps untracked surface lookup read-only and states missing meanings explicitly', async () => {
    const mount = document.createElement('main'); document.body.append(mount);
    const tokens = [{ id: 'u', sentenceId: 's', tokenKind: 'WORD', sourceStart: 0, sourceEnd: 6 }];
    const sentences = [{ id: 's', sourceStart: 0, sourceEnd: 7, exactText: 'ukjent.' }];
    const root = renderExactReaderText({ mount, rawText: 'ukjent.', tokens, sentences });
    const lookup = vi.fn(async () => ({ lemmaDisplay: 'ukjent', translations: { user: [], learnerGlosses: [] } }));
    const updateStatus = vi.fn();
    const inspector = createLexicalInspector({ root, tokens, sentences, preview: vi.fn(),
      surfaceLookup: lookup, updateStatus, documentRef: document, windowRef: window });
    root.querySelector('.language-reader-token').click();
    await vi.waitFor(() => expect(document.querySelector('.language-word-panel')?.textContent).toContain('English meaning unavailable'));
    expect(document.querySelector('.language-word-panel').textContent).toContain('Polish translation unavailable');
    expect(document.querySelector('.language-word-panel').textContent).toContain('Read-only meaning lookup');
    expect(lookup).toHaveBeenCalledWith('ukjent', expect.anything());
    expect(updateStatus).not.toHaveBeenCalled();
    inspector.destroy();
  });

  it('moves a single lexical cursor and updates repeated lemma only after a successful save', async () => {
    const updateStatus = vi.fn(async () => ({}));
    const { root, inspector } = readingFixture(updateStatus);
    const words = [...root.querySelectorAll('.language-reader-token')];
    expect(words.map((word) => word.tabIndex)).toEqual([0, -1, -1]);
    words[0].focus();
    words[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(document.activeElement).toBe(words[1]);
    words[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    expect(document.activeElement).toBe(words[0]);
    words[0].dispatchEvent(new KeyboardEvent('keydown', { key: '3', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma', 'KNOWN'));
    await vi.waitFor(() => expect(words[2].classList.contains('is-known')).toBe(true));
    expect(document.activeElement).toBe(words[1]);
    inspector.destroy();
  });

  it.each([['1', 'NEW', 'new'], ['2', 'LEARNING', 'learning'],
    ['4', 'MASTERED', 'mastered'], ['x', 'IGNORED', 'ignored']])(
    'applies the %s shortcut to every occurrence after the API accepts %s', async (key, status, className) => {
      const updateStatus = vi.fn(async () => ({}));
      const { root, inspector } = readingFixture(updateStatus);
      const words = [...root.querySelectorAll('.language-reader-token')];
      words[0].focus();
      words[0].dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
      await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma', status));
      await vi.waitFor(() => expect(words[2].classList.contains(`is-${className}`)).toBe(true));
      expect(document.activeElement).toBe(words[1]);
      inspector.destroy();
    });

  it('keeps selection on a failed save and ignores form-field shortcuts', async () => {
    const updateStatus = vi.fn(async () => { throw new Error('offline'); });
    const { root, inspector } = readingFixture(updateStatus);
    const word = root.querySelector('[data-token-id="a"]');
    word.focus();
    word.dispatchEvent(new KeyboardEvent('keydown', { key: '2', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledTimes(1));
    expect(document.activeElement).toBe(word);
    expect(word.classList.contains('is-new')).toBe(true);
    const input = document.createElement('input'); root.append(input); input.focus();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: '4', bubbles: true }));
    expect(updateStatus).toHaveBeenCalledTimes(1);
    inspector.destroy();
  });

  it('allows Cloze context lookup without exposing the masked answer', async () => {
    const mount = document.createElement('main'); document.body.append(mount);
    const lookup = vi.fn(async () => ({ translations: { user: [], learnerGlosses: [{ value: 'I' }] } }));
    const item = { index: 0, fingerprint: 'x', sentenceText: 'Jeg jobber her.', blankStart: 4, blankEnd: 10,
      options: ['jobber', 'sover'], source: {}, questionType: 'MULTIPLE_CHOICE' };
    const state = { tracks: { status: 'READY' }, session: { id: 's', trackKey: 'FAST_TRACK_1', actualItemCount: 10, currentItem: item }, attempts: [] };
    const actions = { onLookupSurface: lookup, onAnswer: vi.fn(), onPlayAudio: vi.fn(), onPreferences: vi.fn(), onReveal: vi.fn(), onSkip: vi.fn(), onReport: vi.fn() };
    const cleanup = renderCloze(mount, state, actions);
    expect(mount.querySelector('.language-cloze-blank').textContent).toBe('');
    expect(mount.querySelector('.language-cloze-sentence').textContent).not.toContain('jobber');
    const words = [...mount.querySelectorAll('.language-cloze-sentence .language-reader-token')];
    expect(words.map((word) => word.textContent)).toEqual(['Jeg', 'her']);
    words[0].click();
    await vi.waitFor(() => expect(document.querySelector('.language-word-panel')?.textContent).toContain('□'));
    expect(document.querySelector('.language-word-panel').textContent).not.toContain('jobber');
    expect(lookup).toHaveBeenCalledWith('Jeg', expect.anything());
    cleanup();
  });

  it('offers lookup only on visible Listening transcript text', () => {
    const mount = document.createElement('main'); document.body.append(mount);
    const payload = { document: { id: 't', title: 'Lytt', sourceType: 'PASTED' },
      sentences: [{ id: 'one', exactText: 'Jeg leser.', sentenceOrder: 0 }] };
    const lookup = vi.fn(async () => ({ translations: { user: [], learnerGlosses: [] } }));
    const view = renderListeningText(mount, { payload, progress: {}, speech: {},
      preferences: { defaultMode: 'LISTENING_ONLY', revealCurrent: false } }, { onLookupSurface: lookup });
    expect(mount.querySelectorAll('.language-listening-transcript .language-reader-token')).toHaveLength(0);
    [...mount.querySelectorAll('button')].find((button) => button.textContent === 'Reveal current sentence').click();
    expect(mount.querySelectorAll('.language-listening-transcript .language-reader-token')).toHaveLength(2);
    view.destroy();
  });
});
