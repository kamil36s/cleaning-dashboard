import { afterEach, describe, expect, it, vi } from 'vitest';
import { wordAudioControl } from '../js/language/components/word-audio-control.js';
import { renderExactReaderText } from '../js/language/views/reader.js';
import { createGuidedReader } from '../js/language/components/guided-reader.js';
import { createVocabularyView } from '../js/language/views/vocabulary.js';

describe('single-word pronunciation controls', () => {
  afterEach(() => document.body.replaceChildren());

  it('offers native audio controls if automatic playback is blocked', async () => {
    const play = vi.fn(async (callbacks) => {
      callbacks.onQueued('RUNNING');
      callbacks.onReady('/api/language/audio/example.mp3');
      throw new Error('Playback blocked');
    });
    const control = wordAudioControl(document, play);
    document.body.append(control);
    control.querySelector('button').click();
    await vi.waitFor(() => expect(control.querySelector('audio')).not.toBeNull());
    expect(control.querySelector('audio').src).toContain('/api/language/audio/example.mp3');
    expect(control.textContent).toContain('Playback blocked');
  });

  it('plays the authoritative token surface from the Reader word card', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const sentence = { id: 'sentence-1', sentenceOrder: 0, sourceStart: 0, sourceEnd: 4, exactText: 'plan' };
    const token = { id: 'token-1', sentenceId: sentence.id, tokenOrder: 0, sourceStart: 0, sourceEnd: 4,
      tokenKind: 'WORD', selectedLemmaId: 'lemma-1', knowledgeStatus: 'NEW', disposition: 'TRACKED' };
    const source = renderExactReaderText({ mount, rawText: 'plan', sentences: [sentence], tokens: [token] });
    const playWordAudio = vi.fn(async () => {});
    const guided = createGuidedReader({ source, sentences: [sentence], tokens: [token], playWordAudio,
      documentRef: document, windowRef: window });
    document.querySelector('.language-guided-word-card .language-word-audio button').click();
    await vi.waitFor(() => expect(playWordAudio).toHaveBeenCalledWith('token-1', expect.any(Object)));
    guided.destroy();
  });

  it('offers pronunciation for vocabulary lemmas independently of opening details', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const onPlayAudio = vi.fn(async () => {});
    const view = createVocabularyView(mount, {
      query: '', knowledgeStatus: '', disposition: '', items: [{ id: 'lemma-1', lemmaDisplay: 'plan',
        knowledgeStatus: 'NEW', disposition: 'TRACKED', formsCount: 1, totalExposures: 0 }],
      total: 1, loading: false, loadingMore: false, nextCursor: null,
    }, { onPlayAudio, onOpenLemma: vi.fn(), onQuery: vi.fn(), onKnowledgeStatus: vi.fn(),
      onDisposition: vi.fn(), onLoadMore: vi.fn() });
    mount.querySelector('.language-word-audio button').click();
    await vi.waitFor(() => expect(onPlayAudio).toHaveBeenCalledWith('lemma-1', expect.any(Object)));
    view.destroy();
  });
});
