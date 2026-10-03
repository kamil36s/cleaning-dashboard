import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderListeningLanding, renderListeningText } from '../js/language/views/listening.js';

function payload(sourceType = 'PASTED') {
  return {
    document: { id: 't'.repeat(32), title: 'Arbeid', sourceType },
    sentences: [
      { id: '1'.repeat(32), sentenceOrder: 0, exactText: 'Jeg jobber.' },
      { id: '2'.repeat(32), sentenceOrder: 1, exactText: 'Jeg leser.' },
    ],
  };
}

describe('Language Listening UI', () => {
  afterEach(() => document.body.replaceChildren());

  it('renders canonical material progress and distinguishes Reader from generated Cloud audio', () => {
    const mount = document.createElement('main');
    const onOpen = vi.fn();
    renderListeningLanding(mount, { items: [
      { id: 'a', title: 'Reader', sourceType: 'PASTED', listeningStatus: 'IN_PROGRESS', completedSentenceCount: 1, eligibleSentenceCount: 2, completionPercent: 50, activeMs: 10_000, sessionCount: 1 },
      { id: 'b', title: 'Generated', sourceType: 'GENERATED_GEMINI', listeningStatus: 'NOT_STARTED', completedSentenceCount: 0, eligibleSentenceCount: 2 },
    ] }, { onOpen });
    expect(mount.textContent).toContain('Reader');
    expect(mount.textContent).toContain('browser TTS');
    expect(mount.textContent).toContain('Cloud audio');
    expect(mount.textContent).toContain('50%');
    mount.querySelector('button').click();
    expect(onOpen).toHaveBeenCalledWith('a');
  });

  it('supports accessible current sentence, listening-only suppression, reveal and controls', () => {
    const mount = document.createElement('main');
    document.body.append(mount);
    const handlers = {
      onPlay: vi.fn(), onPause: vi.fn(), onResume: vi.fn(), onStop: vi.fn(),
      onSelect: vi.fn(), onPreference: vi.fn(),
    };
    const view = renderListeningText(mount, {
      payload: payload(), currentIndex: 0, playbackState: 'IDLE', activeMs: 0,
      progress: { completedSentenceCount: 0, eligibleSentenceCount: 2, completionPercent: 0 },
      preferences: { defaultMode: 'LISTENING_ONLY', rate: 1, revealCurrent: false },
      speech: { state: 'AVAILABLE', voices: [{ id: 'nb', name: 'Bokmal', lang: 'nb-NO' }] },
    }, handlers);
    expect(mount.querySelectorAll('[aria-current="true"]')).toHaveLength(1);
    expect(mount.querySelectorAll('[aria-hidden="true"]')).toHaveLength(2);
    const buttons = [...mount.querySelectorAll('button')];
    buttons.find((item) => item.textContent === 'Reveal current sentence').click();
    expect(mount.querySelectorAll('[aria-hidden="true"]')).toHaveLength(1);
    buttons.find((item) => item.textContent === 'Play').click();
    expect(handlers.onPlay).toHaveBeenCalledWith(0, { continuous: true, mode: 'LISTENING_ONLY' });
    view.setCurrent(1);
    expect(mount.querySelector('[aria-current="true"]').dataset.sentenceOrder).toBe('1');
    view.setPlaybackState('PLAYING', 'Playing sentence 2');
    expect(mount.querySelector('[role="status"]').textContent).toBe('Playing sentence 2');
  });

  it('keeps accepted generated text on the existing Google Cloud path', () => {
    const mount = document.createElement('main');
    renderListeningText(mount, {
      payload: payload('GENERATED_GEMINI'), progress: {}, preferences: {}, speech: {},
    });
    expect(mount.textContent).toContain('Google Cloud');
    expect(mount.textContent).toContain('Phase 8');
    expect(mount.querySelector('[aria-label="BokmÃ¥l browser voice"]')).toBeNull();
  });
});
