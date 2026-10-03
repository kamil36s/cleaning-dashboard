export const BROWSER_SPEECH_STATES = Object.freeze({
  AVAILABLE: 'AVAILABLE',
  NO_BOKMAL_VOICE: 'NO_BOKMAL_VOICE',
  SPEECH_SYNTHESIS_UNSUPPORTED: 'SPEECH_SYNTHESIS_UNSUPPORTED',
  VOICE_LOADING: 'VOICE_LOADING',
  ERROR: 'ERROR',
});

export const MIN_SPEECH_RATE = 0.6;
export const MAX_SPEECH_RATE = 1.4;

export function clampSpeechRate(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.round(Math.min(MAX_SPEECH_RATE, Math.max(MIN_SPEECH_RATE, parsed)) * 10) / 10;
}

function normalizedLanguage(value) {
  return String(value || '').trim().replaceAll('_', '-').toLowerCase();
}

export function voiceStableId(voice) {
  return String(voice?.voiceURI || `${voice?.name || ''}|${voice?.lang || ''}`);
}

export function bokmalVoices(voices = []) {
  return [...voices]
    .filter((voice) => {
      const language = normalizedLanguage(voice?.lang);
      return language === 'nb-no' || language === 'nb';
    })
    .sort((left, right) => {
      const leftExact = normalizedLanguage(left.lang) === 'nb-no' ? 0 : 1;
      const rightExact = normalizedLanguage(right.lang) === 'nb-no' ? 0 : 1;
      return leftExact - rightExact
        || Number(Boolean(right.default)) - Number(Boolean(left.default))
        || String(left.name || '').localeCompare(String(right.name || ''));
    });
}

export function selectBokmalVoice(voices, preferredVoiceId = '') {
  const compatible = bokmalVoices(voices);
  return compatible.find((voice) => voiceStableId(voice) === preferredVoiceId) || compatible[0] || null;
}

export class BrowserSpeechAdapter {
  constructor({
    speechSynthesis = globalThis.speechSynthesis,
    UtteranceClass = globalThis.SpeechSynthesisUtterance,
    coordinator = null,
    owner = 'browser-tts',
    onStateChange = () => {},
  } = {}) {
    this.synthesis = speechSynthesis;
    this.UtteranceClass = UtteranceClass;
    this.coordinator = coordinator;
    this.owner = owner;
    this.onStateChange = onStateChange;
    this.state = BROWSER_SPEECH_STATES.VOICE_LOADING;
    this.voices = [];
    this.current = null;
    this.boundVoicesChanged = () => this.refreshVoices();
    this.initialized = false;
  }

  initialize() {
    if (!this.synthesis || typeof this.synthesis.speak !== 'function' || typeof this.UtteranceClass !== 'function') {
      this.setState(BROWSER_SPEECH_STATES.SPEECH_SYNTHESIS_UNSUPPORTED);
      return this.snapshot();
    }
    if (!this.initialized) {
      this.synthesis.addEventListener?.('voiceschanged', this.boundVoicesChanged);
      this.initialized = true;
    }
    return this.refreshVoices();
  }

  setState(state) {
    this.state = state;
    this.onStateChange(this.snapshot());
  }

  refreshVoices() {
    try {
      const listed = this.synthesis?.getVoices?.() || [];
      this.voices = bokmalVoices(listed);
      this.setState(
        !listed.length
          ? BROWSER_SPEECH_STATES.VOICE_LOADING
          : this.voices.length
            ? BROWSER_SPEECH_STATES.AVAILABLE
            : BROWSER_SPEECH_STATES.NO_BOKMAL_VOICE,
      );
    } catch {
      this.voices = [];
      this.setState(BROWSER_SPEECH_STATES.ERROR);
    }
    return this.snapshot();
  }

  snapshot(preferredVoiceId = '') {
    const selected = selectBokmalVoice(this.voices, preferredVoiceId);
    return {
      state: this.state,
      voices: this.voices.map((voice) => ({
        id: voiceStableId(voice), name: voice.name, lang: voice.lang, default: Boolean(voice.default),
      })),
      selectedVoiceId: selected ? voiceStableId(selected) : null,
      capabilityScope: 'DEVICE_LOCAL_NOT_SERVER_GLOBAL',
    };
  }

  speak(text, {
    preferredVoiceId = '', rate = 1, onStart, onPause, onResume, onEnd, onError, onCancel,
  } = {}) {
    this.initialize();
    const voice = selectBokmalVoice(this.voices, preferredVoiceId);
    if (!voice) throw new Error(
      this.state === BROWSER_SPEECH_STATES.SPEECH_SYNTHESIS_UNSUPPORTED
        ? 'Browser speech synthesis is unsupported.'
        : 'No compatible Bokm\u00e5l voice is installed in this browser.',
    );
    this.cancel();
    const utterance = new this.UtteranceClass(String(text || ''));
    utterance.lang = 'nb-NO';
    utterance.voice = voice;
    utterance.rate = clampSpeechRate(rate);
    const current = { utterance, cancelled: false, onCancel };
    this.current = current;
    utterance.onstart = (event) => onStart?.(event);
    utterance.onpause = (event) => onPause?.(event);
    utterance.onresume = (event) => onResume?.(event);
    utterance.onend = (event) => {
      if (this.current !== current || current.cancelled) return;
      this.current = null;
      this.coordinator?.release(this.owner);
      onEnd?.(event);
    };
    utterance.onerror = (event) => {
      if (this.current !== current || current.cancelled) return;
      this.current = null;
      this.coordinator?.release(this.owner);
      onError?.(event);
    };
    this.coordinator?.activate(this.owner, () => this.cancel({ release: false }));
    this.synthesis.speak(utterance);
    return utterance;
  }

  pause() {
    if (!this.current) return false;
    this.synthesis.pause?.();
    return true;
  }

  resume() {
    if (!this.current) return false;
    this.synthesis.resume?.();
    return true;
  }

  cancel({ release = true } = {}) {
    const current = this.current;
    if (!current) return false;
    current.cancelled = true;
    this.current = null;
    this.synthesis.cancel?.();
    if (release) this.coordinator?.release(this.owner);
    current.onCancel?.();
    return true;
  }

  destroy() {
    this.cancel();
    this.synthesis?.removeEventListener?.('voiceschanged', this.boundVoicesChanged);
    this.initialized = false;
  }
}
