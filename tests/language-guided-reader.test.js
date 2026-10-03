import { afterEach, describe, expect, it, vi } from 'vitest';
import { createGuidedReader } from '../js/language/components/guided-reader.js';
import { renderExactReaderText, renderReaderDocument } from '../js/language/views/reader.js';
import { buildReaderStudyPrompt, parseReaderStudyResponse } from '../js/language/reader-study-pack.js';

describe('Reader sentence focus', () => {
  afterEach(() => document.body.replaceChildren());

  function setup(secondWordState = 'LEARNING', updateStatusHandler = async () => ({})) {
    const rawText = 'Jeg ser. Hun går.';
    const sentences = [
      { id: 'sentence-1', sentenceOrder: 0, sourceStart: 0, sourceEnd: 8, exactText: 'Jeg ser.' },
      { id: 'sentence-2', sentenceOrder: 1, sourceStart: 9, sourceEnd: 17, exactText: 'Hun går.' },
    ];
    const tokens = [
      { id: 'token-1', sentenceId: 'sentence-1', tokenOrder: 0, sourceStart: 0, sourceEnd: 3, tokenKind: 'WORD', selectedLemmaId: 'lemma-1', knowledgeStatus: 'NEW', disposition: 'TRACKED' },
      { id: 'token-2', sentenceId: 'sentence-1', tokenOrder: 1, sourceStart: 4, sourceEnd: 7, tokenKind: 'WORD', selectedLemmaId: 'lemma-2', knowledgeStatus: secondWordState, disposition: 'TRACKED' },
      { id: 'token-3', sentenceId: 'sentence-2', tokenOrder: 2, sourceStart: 9, sourceEnd: 12, tokenKind: 'WORD', selectedLemmaId: 'lemma-3', knowledgeStatus: 'NEW', disposition: 'TRACKED' },
      { id: 'token-4', sentenceId: 'sentence-2', tokenOrder: 3, sourceStart: 13, sourceEnd: 16, tokenKind: 'WORD', selectedLemmaId: 'lemma-4', knowledgeStatus: 'KNOWN', disposition: 'TRACKED' },
    ];
    const mount = document.createElement('div');
    document.body.append(mount);
    const source = renderExactReaderText({ mount, rawText, sentences, tokens });
    const updateStatus = vi.fn(updateStatusHandler);
    const guided = createGuidedReader({ source, sentences, tokens, updateStatus,
      preview: vi.fn(async () => ({ translations: { learnerGlosses: [{ value: 'see' }] } })),
      documentRef: document, windowRef: window });
    return { source, guided, updateStatus, sentences };
  }

  it('keeps the whole text visible, navigates words, and advances only after all New words in a sentence are cleared', async () => {
    const { source, guided, updateStatus, sentences } = setup('NEW');
    expect(source.textContent).toBe('Jeg ser. Hun går.');
    expect(source.querySelector('.is-guided-active').dataset.sentenceId).toBe(sentences[0].id);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '2', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma-1', 'LEARNING'));
    expect(source.querySelector('.is-guided-active').dataset.sentenceId).toBe(sentences[0].id);
    expect(source.querySelector('.is-guided-word').textContent).toBe('ser');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '3', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma-2', 'KNOWN'));
    expect(source.querySelector('.is-guided-active').dataset.sentenceId).toBe(sentences[1].id);
    expect(source.querySelector('.is-guided-word').textContent).toBe('Hun');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(source.querySelector('.is-guided-word').textContent).toBe('går');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    expect(source.querySelector('.is-guided-word').textContent).toBe('Hun');
    guided.destroy();
  });

  it('builds a prompt with exact sentence IDs and parses a fenced JSON response', () => {
    const { source, guided, sentences } = setup();
    const tokens = [...source.querySelectorAll('[data-token-id]')].map((word) => ({
      id: word.dataset.tokenId, sentenceId: word.dataset.sentenceId, surface: word.textContent,
      tokenKind: 'WORD', selectedLemmaId: word.dataset.lemmaId, knowledgeStatus: word.dataset.tokenState.toUpperCase(),
    }));
    const prompt = buildReaderStudyPrompt({ title: 'A story' }, sentences, tokens);
    expect(prompt).toContain('sentence-1');
    expect(prompt).toContain('Jeg ser.');
    expect(prompt).toContain('token-1');
    expect(prompt).toContain('NEW or LEARNING');
    expect(prompt).toContain('tokenIds');
    const parsed = parseReaderStudyResponse('```json\n{"sentences":[{"sentenceId":"sentence-1","source":"Jeg ser.","english":"I see.","grammarHint":"Present tense."}]}\n```');
    expect(parsed.sentences[0].english).toBe('I see.');
    guided.destroy();
  });

  it('shows imported meanings between translation and grammar and uses them in the word card', async () => {
    const { source, guided } = setup('NEW');
    guided.setNotes([{ sentenceId: 'sentence-1', english: 'I see.', grammarHint: 'Present tense.',
      glosses: [{ source: 'Jeg ser', english: 'I see', tokenIds: ['token-1', 'token-2'] }] }]);
    const help = guided.help;
    expect(help.textContent.indexOf('I see.')).toBeLessThan(help.textContent.indexOf('Jeg ser — I see'));
    expect(help.textContent.indexOf('Jeg ser — I see')).toBeLessThan(help.textContent.indexOf('Present tense.'));
    expect(help.querySelectorAll('.language-reader-context-words li')).toHaveLength(1);
    expect(document.querySelector('.language-guided-meaning').textContent).toBe('Jeg ser — I see');
    source.querySelector('[data-token-id="token-2"]').click();
    expect(document.querySelector('.language-guided-meaning').textContent).toBe('Jeg ser — I see');
    guided.destroy();
  });

  it('removes a Known word while keeping other New words in the sentence list', async () => {
    const { guided, updateStatus } = setup('NEW');
    guided.setNotes([{ sentenceId: 'sentence-1', english: 'I see.', grammarHint: 'Present tense.',
      glosses: [{ source: 'Jeg', english: 'I', tokenIds: ['token-1'] }] }]);
    expect(guided.help.querySelector('.language-reader-context-words').textContent).toContain('Jeg — I');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '3', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma-1', 'KNOWN'));
    await vi.waitFor(() => expect(guided.help.querySelector('.language-reader-context-words').textContent).not.toContain('Jeg — I'));
    expect(guided.help.querySelector('.language-reader-context-words').textContent).toContain('ser');
    guided.destroy();
  });

  it('supports X Ignore and 4 Mastered without treating either word as New', async () => {
    const { source, guided, updateStatus, sentences } = setup();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma-1', 'IGNORED'));
    expect(source.querySelector('[data-token-id="token-1"]').dataset.tokenState).toBe('ignored');
    expect(source.querySelector('.is-guided-active').dataset.sentenceId).toBe(sentences[1].id);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '4', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma-3', 'MASTERED'));
    expect(source.querySelector('[data-token-id="token-3"]').dataset.tokenState).toBe('mastered');
    guided.destroy();
  });

  it('skips Learning words to focus the next New word after a rating', async () => {
    const { source, guided, updateStatus, sentences } = setup('LEARNING');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '2', bubbles: true }));
    await vi.waitFor(() => expect(updateStatus).toHaveBeenCalledWith('lemma-1', 'LEARNING'));
    await vi.waitFor(() => expect(source.querySelector('.is-guided-active').dataset.sentenceId).toBe(sentences[1].id));
    expect(source.querySelector('.is-guided-word').textContent).toBe('Hun');
    guided.destroy();
  });

  it('closes the word actions outside the word and popup, then reopens them on selection', () => {
    const { source, guided } = setup();
    expect(document.querySelector('.language-guided-word-card')).not.toBeNull();
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect(document.querySelector('.language-guided-word-card')).toBeNull();
    source.querySelector('[data-token-id="token-1"]').click();
    expect(document.querySelector('.language-guided-word-card')).not.toBeNull();
    document.querySelector('.language-guided-word-card').dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect(document.querySelector('.language-guided-word-card')).not.toBeNull();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.querySelector('.language-guided-word-card')).toBeNull();
    guided.destroy();
  });

  it('does not reopen the word popup after a pending status save when the user dismissed it', async () => {
    let finishSave;
    const { guided } = setup('LEARNING', () => new Promise((resolve) => { finishSave = resolve; }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '3', bubbles: true }));
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    finishSave({});
    await vi.waitFor(() => expect(guided.help.querySelector('.language-reader-help-status').textContent).toBe('Word status saved.'));
    expect(document.querySelector('.language-guided-word-card')).toBeNull();
    guided.destroy();
  });

  it('tracks the visible sentence and shows its saved help in the side panel', async () => {
    const { source, guided, sentences } = setup();
    guided.setNotes([
      { sentenceId: sentences[0].id, english: 'I see.', grammarHint: 'First hint.' },
      { sentenceId: sentences[1].id, english: 'She walks.', grammarHint: 'Second hint.' },
    ]);
    const [first, second] = source.querySelectorAll('.language-reader-sentence');
    first.getBoundingClientRect = () => ({ top: -100, bottom: -50 });
    second.getBoundingClientRect = () => ({ top: 200, bottom: 240 });
    window.dispatchEvent(new Event('scroll'));
    await vi.waitFor(() => expect(guided.currentSentenceId()).toBe(sentences[1].id));
    expect(guided.help.textContent).toContain('SENTENCE 2 OF 2');
    expect(guided.help.textContent).toContain('She walks.');
    expect(guided.help.textContent).toContain('Second hint.');
    guided.destroy();
  });

  it('keeps visible words in place and scrolls only when the selected word is outside the viewport', () => {
    const { source, guided } = setup();
    const visibleWord = source.querySelector('[data-token-id="token-2"]');
    visibleWord.getBoundingClientRect = () => ({ top: 100, bottom: 125 });
    visibleWord.scrollIntoView = vi.fn();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(visibleWord.scrollIntoView).not.toHaveBeenCalled();

    const offscreenWord = source.querySelector('[data-token-id="token-3"]');
    offscreenWord.getBoundingClientRect = () => ({ top: window.innerHeight + 100, bottom: window.innerHeight + 125 });
    offscreenWord.scrollIntoView = vi.fn();
    guided.selectSentenceById('sentence-2');
    expect(offscreenWord.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest' });
    guided.destroy();
  });

  it('resumes at a New word and uses Space to pause and resume outside form controls', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const sentence = { id: 'sentence-1', sentenceOrder: 0, sourceStart: 0, sourceEnd: 8, exactText: 'Jeg ser.' };
    const token = { id: 'token-1', sentenceId: sentence.id, tokenOrder: 0, sourceStart: 0, sourceEnd: 3,
      tokenKind: 'WORD', selectedLemmaId: 'lemma-1', knowledgeStatus: 'NEW', disposition: 'TRACKED' };
    let view;
    const onStart = vi.fn(async () => view.setSessionState('ACTIVE'));
    const onPause = vi.fn(async () => view.setSessionState('PAUSED'));
    const onUpdateKnowledge = vi.fn(async () => ({}));
    view = renderReaderDocument(mount, {
      document: { id: 'text-1', title: 'A story', rawText: 'Jeg ser.', processingState: 'ANALYZED' },
      sentences: [sentence], tokens: [token], coverage: {}, readingProgress: null, referenceProfile: {}, analysisRuns: [],
    }, { onStart, onPause, onUpdateKnowledge, onStopAudio: vi.fn() });
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect(document.querySelector('.language-guided-word-card')).toBeNull();
    [...mount.querySelectorAll('button')].find((button) => button.textContent === 'Start reading').click();
    await vi.waitFor(() => expect(onStart).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(document.querySelector('.language-guided-word-card')).not.toBeNull());
    expect(document.activeElement.dataset.tokenId).toBe('token-1');
    await vi.waitFor(() => expect([...mount.querySelectorAll('button')].find((button) => button.textContent === 'Pause').disabled).toBe(false));
    document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
    await vi.waitFor(() => expect(onPause).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect([...mount.querySelectorAll('button')].find((button) => button.textContent === 'Resume reading').disabled).toBe(false));
    const input = mount.querySelector('.language-reader-study-pack textarea');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
    expect(onStart).toHaveBeenCalledOnce();
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
    await vi.waitFor(() => expect(onStart).toHaveBeenCalledTimes(2));
    document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: '3', bubbles: true }));
    await vi.waitFor(() => expect(onUpdateKnowledge).toHaveBeenCalledWith('lemma-1', 'KNOWN'));
    view.destroy();
  });

  it('collapses an existing study pack and keeps it expandable', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const sentence = { id: 'sentence-1', sentenceOrder: 0, sourceStart: 0, sourceEnd: 8, exactText: 'Jeg ser.' };
    const view = renderReaderDocument(mount, {
      document: { id: 'text-1', title: 'A story', rawText: 'Jeg ser.', processingState: 'ANALYZED' },
      sentences: [sentence], tokens: [], coverage: {}, readingProgress: null, referenceProfile: {}, analysisRuns: [],
    }, { onLoadStudyNotes: vi.fn(async () => ({ items: [{ sentenceId: sentence.id, english: 'I see.', grammarHint: 'Present tense.' }] })), onStopAudio: vi.fn() });
    const panel = mount.querySelector('.language-reader-study-pack');
    await vi.waitFor(() => expect(mount.querySelector('.language-reader-sentence-help').textContent).toContain('Present tense.'));
    expect(panel.open).toBe(false);
    expect(panel.querySelector('summary')).not.toBeNull();
    panel.open = true;
    expect(panel.open).toBe(true);
    view.destroy();
  });

  it('puts reading before tools and displays imported sentence help in the focus panel', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const sentence = { id: 'sentence-1', sentenceOrder: 0, sourceStart: 0, sourceEnd: 8, exactText: 'Jeg ser.' };
    const note = { sentenceId: sentence.id, source: sentence.exactText, english: 'I see.', grammarHint: 'Ser is present tense.' };
    const onImportStudyNotes = vi.fn(async () => ({ items: [note] }));
    const view = renderReaderDocument(mount, {
      document: { id: 'text-1', title: 'A story', rawText: 'Jeg ser.', processingState: 'ANALYZED' },
      sentences: [sentence], tokens: [], coverage: {}, readingProgress: null, referenceProfile: {}, analysisRuns: [],
    }, {
      onStart: vi.fn(), onPause: vi.fn(), onComplete: vi.fn(), onStopAudio: vi.fn(),
      onSaveExpression: vi.fn(), onLoadStudyNotes: vi.fn(async () => ({ items: [] })), onImportStudyNotes,
    });
    const page = mount.querySelector('.language-reader-document');
    expect(page.children[0].classList.contains('language-reader-document-head')).toBe(true);
    expect(page.children[1].classList.contains('language-reader-workspace')).toBe(true);
    expect(page.querySelector('.language-reader-tools')).toBe(page.lastElementChild);
    const studyPanel = page.querySelector('.language-reader-sidebar .language-reader-study-pack');
    await vi.waitFor(() => expect(studyPanel.open).toBe(true));
    expect(page.querySelector('[aria-label="Upload study pack JSON file"]')).not.toBeNull();
    page.querySelector('.language-reader-study-pack button').click();
    expect(page.querySelector('[aria-label="Study pack prompt"]').value).toContain('sentence-1');
    page.querySelector('[aria-label="Study pack JSON response"]').value = JSON.stringify({ sentences: [note] });
    page.querySelector('.language-reader-study-pack .is-primary').click();
    await vi.waitFor(() => expect(onImportStudyNotes).toHaveBeenCalledWith({ sentences: [note] }));
    expect(page.querySelector('.language-reader-sentence-help').textContent).toContain('Ser is present tense.');
    expect(studyPanel.open).toBe(false);
    studyPanel.open = true;
    const upload = page.querySelector('[aria-label="Upload study pack JSON file"]');
    Object.defineProperty(upload, 'files', { configurable: true, value: [{ name: 'notes.json', size: 128, text: async () => JSON.stringify({ sentences: [note] }) }] });
    upload.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(page.querySelector('[aria-label="Study pack JSON response"]').value).toContain('Ser is present tense.'));
    page.querySelector('.language-reader-study-pack .is-primary').click();
    await vi.waitFor(() => expect(onImportStudyNotes).toHaveBeenCalledTimes(2));
    view.destroy();
  });
});
