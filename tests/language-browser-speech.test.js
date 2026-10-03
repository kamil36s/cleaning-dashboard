import { describe, expect, it, vi } from 'vitest';
import {
  BROWSER_SPEECH_STATES,
  BrowserSpeechAdapter,
  bokmalVoices,
  clampSpeechRate,
  selectBokmalVoice,
} from '../js/language/audio/browser-speech.js';
import { createLanguagePlaybackCoordinator } from '../js/language/audio/playback-coordinator.js';

class FakeUtterance {
  constructor(text) { this.text = text; }
}

function fakeSynthesis(initial = []) {
  let voices = initial;
  const listeners = new Map();
  return {
    speak: vi.fn(), pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
    getVoices: vi.fn(() => voices),
    addEventListener: vi.fn((type, callback) => listeners.set(type, callback)),
    removeEventListener: vi.fn((type) => listeners.delete(type)),
    setVoices(next) { voices = next; listeners.get('voiceschanged')?.(); },
  };
}

describe('Language browser speech adapter', () => {
  it('reports unsupported and voice-loading states truthfully', () => {
    const unsupported = new BrowserSpeechAdapter({ speechSynthesis: null, UtteranceClass: null });
    expect(unsupported.initialize().state).toBe(BROWSER_SPEECH_STATES.SPEECH_SYNTHESIS_UNSUPPORTED);
    const synthesis = fakeSynthesis([]);
    const adapter = new BrowserSpeechAdapter({ speechSynthesis: synthesis, UtteranceClass: FakeUtterance });
    expect(adapter.initialize().state).toBe(BROWSER_SPEECH_STATES.VOICE_LOADING);
    synthesis.setVoices([{ name: 'Danish', lang: 'da-DK' }, { name: 'Nynorsk', lang: 'nn-NO' }]);
    expect(adapter.snapshot().state).toBe(BROWSER_SPEECH_STATES.NO_BOKMAL_VOICE);
  });

  it('accepts only nb voices, prioritizes exact nb-NO and honors a compatible preference', () => {
    const voices = [
      { name: 'English', lang: 'en-GB', voiceURI: 'en' },
      { name: 'Generic Norwegian', lang: 'nb', voiceURI: 'nb' },
      { name: 'Exact Bokmal', lang: 'nb-NO', voiceURI: 'nb-no' },
      { name: 'Swedish', lang: 'sv-SE', voiceURI: 'sv' },
    ];
    expect(bokmalVoices(voices).map((voice) => voice.voiceURI)).toEqual(['nb-no', 'nb']);
    expect(selectBokmalVoice(voices).voiceURI).toBe('nb-no');
    expect(selectBokmalVoice(voices, 'nb').voiceURI).toBe('nb');
  });

  it('applies bounded rates and emits real lifecycle callbacks', () => {
    const voice = { name: 'Bokmal', lang: 'nb-NO', voiceURI: 'nb-no' };
    const synthesis = fakeSynthesis([voice]);
    const adapter = new BrowserSpeechAdapter({ speechSynthesis: synthesis, UtteranceClass: FakeUtterance });
    const onStart = vi.fn();
    const onEnd = vi.fn();
    const utterance = adapter.speak('Jeg jobber.', { rate: 9, onStart, onEnd });
    expect(utterance.lang).toBe('nb-NO');
    expect(utterance.voice).toBe(voice);
    expect(utterance.rate).toBe(1.4);
    expect(clampSpeechRate(0.01)).toBe(0.6);
    utterance.onstart();
    utterance.onend();
    expect(onStart).toHaveBeenCalledOnce();
    expect(onEnd).toHaveBeenCalledOnce();
  });

  it('cancels the previous owner so cloud audio and browser speech cannot overlap', () => {
    const coordinator = createLanguagePlaybackCoordinator();
    const cloudCancel = vi.fn();
    coordinator.activate('reader-cloud', cloudCancel);
    const synthesis = fakeSynthesis([{ name: 'Bokmal', lang: 'nb-NO', voiceURI: 'nb-no' }]);
    const onCancel = vi.fn();
    const adapter = new BrowserSpeechAdapter({
      speechSynthesis: synthesis, UtteranceClass: FakeUtterance,
      coordinator, owner: 'listening-browser',
    });
    adapter.speak('Hei.', { onCancel });
    expect(cloudCancel).toHaveBeenCalledOnce();
    expect(coordinator.currentOwner()).toBe('listening-browser');
    adapter.cancel();
    expect(synthesis.cancel).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledOnce();
    expect(coordinator.currentOwner()).toBeNull();
  });
});
