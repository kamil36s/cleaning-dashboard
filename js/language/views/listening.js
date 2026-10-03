import { field, node, replace, statusPill } from '../components/dom.js';
import { appendInspectableWords, createLexicalInspector } from '../components/lexical-inspector.js';

function duration(ms) {
  const seconds = Math.max(0, Math.round(Number(ms || 0) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function renderListeningLanding(mount, state, { onOpen } = {}) {
  if (state.loading && !state.items?.length) {
    replace(mount, node('p', { className: 'language-empty-copy', text: 'Loading listening material\u2026' }));
    return;
  }
  const items = state.items || [];
  const cards = items.map((item) => {
    const source = String(item.sourceType || '').startsWith('GENERATED_') ? 'Generated \u00b7 Cloud audio' : 'Reader \u00b7 browser TTS';
    const action = node('button', {
      className: 'language-button is-primary', type: 'button',
      text: item.listeningStatus === 'IN_PROGRESS' ? 'Continue listening' : 'Open listening',
    });
    action.addEventListener('click', () => onOpen?.(item.id));
    return node('article', { className: 'language-card language-listening-row' }, [
      node('div', {}, [
        node('p', { className: 'language-kicker', text: source }),
        node('h3', { text: item.title || 'Untitled text' }),
        node('p', { text: `${item.completedSentenceCount || 0} / ${item.eligibleSentenceCount || item.sentenceCount || 0} sentences \u00b7 ${item.completionPercent || 0}%` }),
        node('p', { text: `${duration(item.activeMs)} active listening \u00b7 ${item.sessionCount || 0} sessions` }),
      ]),
      action,
    ]);
  });
  replace(mount, node('div', { className: 'language-listening-view' }, [
    node('section', { className: 'language-card language-listening-intro' }, [
      node('p', { className: 'language-kicker', text: 'PHASE 10 \u00b7 LISTENING STUDY' }),
      node('h3', { text: 'Listen to analyzed texts sentence by sentence' }),
      node('p', { text: 'Ordinary Reader texts use an installed browser Bokm\u00e5l voice. Accepted generated texts keep their existing cached Google Cloud sentence audio. Playback alone is not comprehension.' }),
    ]),
    state.error ? node('p', { className: 'language-form-error', text: state.error }) : null,
    items.length ? node('div', { className: 'language-listening-library' }, cards)
      : node('p', { className: 'language-empty-copy', text: 'No analyzed Reader text is eligible yet.' }),
  ]));
}

export function renderListeningText(mount, state, handlers = {}) {
  const { payload, progress = {}, speech = {}, preferences = {}, cloudAudio = {} } = state;
  const text = payload?.document || {};
  const sentences = payload?.sentences || [];
  const generated = String(text.sourceType || '').startsWith('GENERATED_');
  const authentic = Boolean(state.authenticMedia);
  let currentIndex = Math.max(0, Math.min(sentences.length - 1, Number(state.currentIndex || 0)));
  let mode = preferences.defaultMode === 'LISTENING_ONLY' ? 'LISTENING_ONLY' : 'READ_LISTEN';
  let revealCurrent = Boolean(preferences.revealCurrent);

  const source = node('div', { className: 'language-listening-transcript' });
  const status = node('p', {
    className: 'language-reader-audio-status',
    attrs: { role: 'status', 'aria-live': 'polite' },
    text: state.statusText || 'Ready',
  });
  const position = node('span', { className: 'language-definition' });
  const activeTime = node('span', { className: 'language-definition', text: `${duration(state.activeMs)} active` });
  const progressText = node('span', { className: 'language-definition' });
  const play = node('button', { className: 'language-button is-primary', type: 'button', text: 'Play' });
  const pause = node('button', { className: 'language-button', type: 'button', text: 'Pause', disabled: true });
  const resume = node('button', { className: 'language-button', type: 'button', text: 'Resume', disabled: true });
  const stop = node('button', { className: 'language-button', type: 'button', text: 'Stop', disabled: true });
  const replay = node('button', { className: 'language-button', type: 'button', text: 'Replay sentence' });
  const previous = node('button', { className: 'language-button', type: 'button', text: 'Previous' });
  const next = node('button', { className: 'language-button', type: 'button', text: 'Next' });
  const reveal = node('button', { className: 'language-button', type: 'button', text: 'Reveal current sentence' });
  const modeSelect = node('select', {}, [
    node('option', { text: 'Read + Listen', attrs: { value: 'READ_LISTEN' } }),
    node('option', { text: 'Listening Only', attrs: { value: 'LISTENING_ONLY' } }),
  ]);
  modeSelect.value = mode;
  const rate = node('input', {
    type: 'range', value: String(preferences.rate || 1),
    attrs: { min: authentic ? '0.75' : '0.6', max: authentic ? '1.5' : '1.4', step: '0.1', 'aria-label': authentic ? 'Media playback rate' : 'Speech rate' },
  });
  const rateValue = node('span', { className: 'language-definition', text: `${Number(rate.value).toFixed(1)}\u00d7` });
  const voice = node('select', { attrs: { 'aria-label': 'Bokm\u00e5l browser voice' } },
    [
      node('option', { text: 'Automatic compatible voice', attrs: { value: '' } }),
      ...(speech.voices || []).map((item) => node('option', {
        text: `${item.name} (${item.lang})`, attrs: { value: item.id },
      })),
    ],
  );
  if (preferences.preferredVoiceId) voice.value = preferences.preferredVoiceId;
  const timeline = node('input', { type: 'range', value: '0', attrs: { min: '0', max: '1', step: '1', 'aria-label': 'Aligned sentence timeline' } });
  const saveExpression = node('button', { className: 'language-button', type: 'button', text: 'Save sentence to Phrasebook' });
  let inspector = null;

  function updateTranscript() {
    inspector?.destroy();
    const lookupTokens = [];
    const lookupSentences = [];
    source.classList.toggle('is-listening-only', mode === 'LISTENING_ONLY');
    const windowStart = Math.max(0, currentIndex - 100);
    const windowEnd = Math.min(sentences.length, currentIndex + 101);
    source.replaceChildren(...sentences.slice(windowStart, windowEnd).map((sentence, windowIndex) => {
      const index = windowStart + windowIndex;
      const current = index === currentIndex;
      const revealed = mode !== 'LISTENING_ONLY' || (current && revealCurrent);
      const row = node('p', {
        className: `language-listening-sentence${current ? ' is-current' : ''}${revealed ? ' is-revealed' : ''}`,
        text: sentence.exactText || '',
        attrs: {
          'data-sentence-id': sentence.id,
          'data-sentence-order': String(sentence.sentenceOrder ?? index),
          ...(current ? { 'aria-current': 'true' } : {}),
          ...(revealed ? {} : { 'aria-hidden': 'true' }),
        },
      });
      if (revealed && handlers.onLookupSurface) {
        row.replaceChildren();
        lookupTokens.push(...appendInspectableWords(row, sentence.exactText || '', {
          sourceStart: 0, sentenceId: sentence.id, prefix: `listening-${index}`,
        }));
        lookupSentences.push({ id: sentence.id, exactText: sentence.exactText || '', sourceStart: 0 });
      }
      row.addEventListener('click', (event) => {
        if (!event.target.closest?.('.language-reader-token')) handlers.onSelect?.(index);
      });
      if (authentic && sentence.startMs != null) row.append(node('small', {
        className: 'language-listening-timing',
        text: ` ${duration(sentence.startMs)}–${duration(sentence.endMs)} · ${sentence.alignmentMethod || 'aligned'}`,
      }));
      return row;
    }));
    inspector = lookupTokens.length ? createLexicalInspector({
      root: source, tokens: lookupTokens, sentences: lookupSentences,
      surfaceLookup: handlers.onLookupSurface, fallbackLookup: handlers.onLookupMeanings, documentRef: mount.ownerDocument,
      windowRef: mount.ownerDocument.defaultView,
    }) : null;
    position.textContent = sentences.length ? `Sentence ${currentIndex + 1} / ${sentences.length}` : 'No sentences';
    progressText.textContent = `${progress.completedSentenceCount || 0} / ${progress.eligibleSentenceCount || sentences.length} qualified \u00b7 ${progress.completionPercent || 0}%`;
    reveal.hidden = mode !== 'LISTENING_ONLY';
    reveal.textContent = revealCurrent ? 'Hide current sentence' : 'Reveal current sentence';
    previous.disabled = currentIndex <= 0;
    next.disabled = currentIndex >= sentences.length - 1;
    const currentSentence = sentences[currentIndex];
    timeline.hidden = !authentic || currentSentence?.startMs == null;
    if (!timeline.hidden) {
      timeline.min = String(currentSentence.startMs);
      timeline.max = String(currentSentence.endMs);
      timeline.value = String(currentSentence.startMs);
    }
    if (authentic && currentSentence?.startMs == null) play.disabled = true;
  }

  function setPlaybackState(playbackState, message) {
    const playing = playbackState === 'PLAYING';
    const paused = playbackState === 'PAUSED';
    play.disabled = playing || paused || Boolean(authentic && sentences[currentIndex]?.startMs == null);
    pause.disabled = !playing;
    resume.disabled = !paused;
    stop.disabled = !(playing || paused || playbackState === 'LOADING');
    if (message) status.textContent = message;
  }

  play.addEventListener('click', () => handlers.onPlay?.(currentIndex, { continuous: true, mode }));
  replay.addEventListener('click', () => handlers.onPlay?.(currentIndex, { continuous: false, mode, replay: true }));
  pause.addEventListener('click', () => handlers.onPause?.());
  resume.addEventListener('click', () => handlers.onResume?.());
  stop.addEventListener('click', () => handlers.onStop?.());
  previous.addEventListener('click', () => handlers.onSelect?.(Math.max(0, currentIndex - 1)));
  next.addEventListener('click', () => handlers.onSelect?.(Math.min(sentences.length - 1, currentIndex + 1)));
  reveal.addEventListener('click', () => {
    revealCurrent = !revealCurrent;
    handlers.onPreference?.({ revealCurrent });
    updateTranscript();
  });
  modeSelect.addEventListener('change', () => {
    mode = modeSelect.value;
    revealCurrent = false;
    handlers.onPreference?.({ defaultMode: mode, revealCurrent });
    updateTranscript();
  });
  rate.addEventListener('input', () => {
    rateValue.textContent = `${Number(rate.value).toFixed(1)}\u00d7`;
    handlers.onPreference?.({ rate: Number(rate.value) });
  });
  timeline.addEventListener('input', () => handlers.onSeek?.(Number(timeline.value)));
  saveExpression.addEventListener('click', () => handlers.onSaveExpression?.(sentences[currentIndex]));
  voice.addEventListener('change', () => handlers.onPreference?.({ preferredVoiceId: voice.value }));

  const capability = authentic
    ? statusPill(`Managed authentic audio · ${state.alignmentStatus || 'SOURCE TIMESTAMPS'}`, 'ready')
    : generated
    ? statusPill(
      `Google Cloud cached MP3 · ${cloudAudio.state || 'UNAVAILABLE'}`,
      cloudAudio.state === 'CONFIGURED' ? 'ready' : 'warning',
    )
    : statusPill(speech.state || 'VOICE_LOADING', speech.state === 'AVAILABLE' ? 'ready' : 'warning');
  const browserControls = generated ? null : node('div', { className: 'language-form-grid' }, [
    authentic ? null : field('Browser Bokm\u00e5l voice', voice),
    field(authentic ? 'Media speed' : 'Speech rate', node('div', { className: 'language-listening-rate' }, [rate, rateValue])),
  ]);
  replace(mount, node('div', { className: 'language-listening-view' }, [
    node('div', { className: 'language-reader-actions' }, [
      node('a', { className: 'language-button', text: '\u2190 Listening library', attrs: { href: '#listening' } }),
      node('a', { className: 'language-button', text: 'Open in Reader', attrs: { href: `#reader/text/${text.id}` } }),
    ]),
    node('section', { className: 'language-card language-listening-player' }, [
      node('p', { className: 'language-kicker', text: `${authentic ? 'AUTHENTIC MEDIA' : generated ? 'GENERATED' : 'READER'} \u00b7 LISTENING` }),
      node('h3', { text: text.title || 'Listening' }),
      node('p', { text: authentic
        ? `Managed user-owned audio from ${state.authenticMedia?.sourceName || 'Content Inbox'}. Active time and non-seeked interval coverage are recorded separately.`
        : generated
        ? 'Uses the existing Phase 8 Google Cloud nb-NO sentence cache. Canonical Listening evidence is recorded only from the actual playback lifecycle.'
        : 'Uses the selected device-local Bokm\u00e5l browser voice. No browser-generated audio file is stored.' }),
      capability,
      field('Study mode', modeSelect),
      browserControls,
      authentic ? field('Sentence timeline', timeline) : null,
      node('div', { className: 'language-listening-progress' }, [position, progressText, activeTime]),
      node('div', { className: 'language-form-actions language-listening-controls' }, [
        previous, play, pause, resume, stop, replay, next, reveal, authentic ? saveExpression : null, status,
      ]),
    ]),
    source,
  ]));
  updateTranscript();
  setPlaybackState(state.playbackState || 'IDLE', state.statusText);

  return {
    setCurrent(index) {
      currentIndex = Math.max(0, Math.min(sentences.length - 1, Number(index || 0)));
      revealCurrent = mode !== 'LISTENING_ONLY';
      updateTranscript();
      source.querySelector('[aria-current="true"]')?.scrollIntoView?.({ block: 'center' });
    },
    setPlaybackState,
    setProgress(nextProgress) {
      Object.assign(progress, nextProgress || {});
      updateTranscript();
    },
    setActiveMs(value) { activeTime.textContent = `${duration(value)} active`; },
    setTimeline(value) { if (!timeline.hidden) timeline.value = String(value); },
    currentIndex: () => currentIndex,
    mode: () => mode,
    destroy() { inspector?.destroy(); },
  };
}
