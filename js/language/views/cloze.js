import { definitionList, messageState, node, replace, statusPill } from '../components/dom.js';
import { appendInspectableWords, createLexicalInspector } from '../components/lexical-inspector.js';

function questionSentence(item, feedback, lookupEnabled = false) {
  const text = String(item?.sentenceText || '');
  const start = Number(item?.blankStart || 0);
  const end = Number(item?.blankEnd || start);
  const sentence = node('p', { className: 'language-cloze-sentence', attrs: { 'aria-label': 'Cloze sentence' } });
  const before = text.slice(0, start);
  const after = text.slice(end);
  const startCp = [...before].length;
  const endCp = [...text.slice(0, end)].length;
  const tokens = [];
  if (lookupEnabled) tokens.push(...appendInspectableWords(sentence, before, { sentenceId: 'cloze', prefix: 'before' }));
  else sentence.append(document.createTextNode(before));
  const blank = node('span', { className: `language-cloze-blank${feedback ? ' is-revealed' : ''}`, attrs: { 'aria-label': feedback ? 'revealed word' : 'missing word' } });
  if (feedback) {
    if (lookupEnabled) tokens.push(...appendInspectableWords(blank, feedback.expectedSurfaceForm || text.slice(start, end), {
      sourceStart: startCp, sentenceId: 'cloze', prefix: 'answer',
    }));
    else blank.textContent = feedback.expectedSurfaceForm || text.slice(start, end);
  }
  sentence.append(blank);
  if (lookupEnabled) tokens.push(...appendInspectableWords(sentence, after, { sourceStart: endCp, sentenceId: 'cloze', prefix: 'after' }));
  else sentence.append(document.createTextNode(after));
  const hiddenAnswers = new Set([text.slice(start, end), ...(item.options || [])]
    .map((value) => String(value || '').toLocaleLowerCase('nb-NO')));
  const safeTokens = feedback ? tokens : tokens.filter((token) => {
    const button = sentence.querySelector(`[data-token-id="${token.id}"]`);
    if (!button || !hiddenAnswers.has(button.textContent.toLocaleLowerCase('nb-NO'))) return true;
    button.replaceWith(document.createTextNode(button.textContent));
    return false;
  });
  sentence.lookupTokens = safeTokens;
  sentence.lookupContext = {
    id: 'cloze', sourceStart: 0,
    exactText: feedback ? text : `${before}${'□'.repeat(Math.max(1, endCp - startCp))}${after}`,
  };
  return sentence;
}

function preferenceControls(state, actions, compact = false) {
  const preferences = state.preferences || { translationTiming: 'AFTER' };
  const timing = node('select', { attrs: { 'aria-label': 'Show English translation' } }, [
    node('option', { value: 'BEFORE', text: 'Before answering' }),
    node('option', { value: 'AFTER', text: 'After answering' }),
    node('option', { value: 'OFF', text: 'Never' }),
  ]);
  timing.value = preferences.translationTiming;
  timing.addEventListener('change', () => actions.onPreferences({ translationTiming: timing.value }));
  return node('div', { className: `language-cloze-preferences${compact ? ' is-compact' : ''}` }, [
    node('label', {}, [node('span', { text: 'English translation' }), timing]),
  ]);
}

function translationNode(item, feedback, preferences) {
  const translation = feedback?.translation || item?.translation;
  const timing = preferences?.translationTiming || 'AFTER';
  const visible = translation && timing !== 'OFF' && (timing === 'BEFORE' || Boolean(feedback));
  return visible ? node('div', { className: 'language-cloze-translation', attrs: { lang: 'en' } }, [
    node('span', { text: 'English' }), node('p', { text: translation.text }),
  ]) : null;
}

function lengthSelect(label) {
  return node('select', { attrs: { 'aria-label': label } }, [
    node('option', { value: '10', text: '10 questions' }),
    node('option', { value: '20', text: '20 questions' }),
    node('option', { value: '50', text: '50 questions' }),
  ]);
}

function startView(state, actions) {
  const tracks = state.tracks;
  if (!tracks || tracks.status !== 'READY') return messageState('error', 'Cloze practice is unavailable.', tracks?.status || 'Practice metadata unavailable');
  let selectedTrack = tracks.items?.[0]?.key || 'FAST_TRACK_1';
  const trackButtons = node('div', { className: 'language-cloze-tracks', attrs: { role: 'radiogroup', 'aria-label': 'Fast Track' } });
  const buttons = (tracks.items || []).map((track, index) => {
    const button = node('button', {
      className: `language-cloze-track${index === 0 ? ' is-selected' : ''}`, type: 'button',
      attrs: { role: 'radio', 'aria-checked': index === 0 ? 'true' : 'false' },
    }, [node('strong', { text: track.label }), node('span', { text: `${track.encountered} / ${track.targets} encountered` }), node('small', { text: `${track.rankLabel} ${track.rankMin}–${track.rankMax} · ${track.playableTargets} playable` })]);
    button.addEventListener('click', () => {
      selectedTrack = track.key;
      buttons.forEach((item) => { item.classList.remove('is-selected'); item.setAttribute('aria-checked', 'false'); });
      button.classList.add('is-selected'); button.setAttribute('aria-checked', 'true');
    });
    trackButtons.append(button); return button;
  });
  const fastLength = lengthSelect('Session length');
  const startFast = node('button', { className: 'language-button is-primary', type: 'button', text: 'Start Fast Track', disabled: state.busy || tracks.fastTrackStatus === 'UNAVAILABLE' || !(tracks.items || []).length });
  startFast.addEventListener('click', () => actions.onStart({ mode: 'FAST_TRACK', trackKey: selectedTrack, itemCount: Number(fastLength.value) }));
  const fastControls = [fastLength, startFast];
  if (tracks.summary?.mistakeTargets > 0) {
    const recycle = node('button', { className: 'language-button', type: 'button', text: `Recycle ${tracks.summary.mistakeTargets} mistakes`, disabled: state.busy });
    recycle.addEventListener('click', () => actions.onStart({ mode: 'RECYCLE_MISTAKES', trackKey: selectedTrack, itemCount: Number(fastLength.value) }));
    fastControls.push(recycle);
  }
  if (tracks.activeSessionId) {
    const resume = node('button', { className: 'language-button', type: 'button', text: 'Continue active session', disabled: state.busy });
    resume.addEventListener('click', () => actions.onResume(tracks.activeSessionId)); fastControls.push(resume);
  }
  const sharedLength = lengthSelect('Shared practice session length');
  const answerStyle = node('select', { attrs: { 'aria-label': 'Shared practice answer style' } }, [
    node('option', { value: 'TYPED', text: 'Type the exact answer' }),
    node('option', { value: 'MULTIPLE_CHOICE', text: 'Multiple choice when safe' }),
  ]);
  const review = tracks.practiceModes?.review || {};
  const reviewStart = node('button', { className: 'language-button is-primary', type: 'button', text: 'Start review practice', disabled: state.busy || !review.available });
  reviewStart.addEventListener('click', () => actions.onStart({ mode: 'REVIEW', itemCount: Number(sharedLength.value), questionType: answerStyle.value }));
  const counts = review.sourceTargetCounts || {};
  const curriculum = tracks.practiceModes?.curriculum || {};
  const packs = curriculum.packs || [];
  const packSelect = node('select', { attrs: { 'aria-label': 'Curriculum pack' } }, packs.map((pack) => node('option', { value: `${pack.id}\u001f${pack.version}`, text: `${pack.name} v${pack.version} · ${pack.eligibleTargets} eligible` })));
  const curriculumStart = node('button', { className: 'language-button', type: 'button', text: 'Practice curriculum pack', disabled: state.busy || !curriculum.available || !packs.length });
  curriculumStart.addEventListener('click', () => {
    const [curriculumPackId, curriculumVersion] = packSelect.value.split('\u001f');
    actions.onStart({ mode: 'CURRICULUM', curriculumPackId, curriculumVersion, itemCount: Number(sharedLength.value), questionType: answerStyle.value });
  });
  return node('div', { className: 'language-cloze-start' }, [
    node('section', { className: 'language-card language-cloze-intro' }, [
      node('p', { className: 'language-kicker', text: 'FAST TRACK · KELLY LEARNER RANK' }), node('h3', { text: 'Norwegian Cloze practice' }),
      node('p', { text: 'Choose the exact missing surface form. This is deterministic recycling practice, not a second SRS.' }),
      preferenceControls(state, actions), trackButtons, node('div', { className: 'language-form-actions' }, fastControls),
      state.notice ? node('p', { className: 'language-definition', text: state.notice, attrs: { role: 'status' } }) : null,
    ]),
    node('section', { className: 'language-card language-cloze-summary' }, [
      node('p', { className: 'language-kicker', text: 'REAL CLOZE EVIDENCE' }),
      definitionList([['Attempts', tracks.summary?.attempts || 0], ['Correct', tracks.summary?.correct || 0], ['Incorrect', tracks.summary?.incorrect || 0], ['Accuracy', tracks.summary?.accuracy == null ? 'Not yet available' : `${tracks.summary.accuracy}%`]], 'language-evidence'),
    ]),
    node('section', { className: 'language-card language-cloze-shared' }, [
      node('p', { className: 'language-kicker', text: 'SHARED-CONTEXT PRACTICE' }), node('h3', { text: 'Review real words in real contexts' }),
      node('p', { text: 'Uses exact analyzed Reader spans, accepted generated text, linked Phrasebook contexts, or a frozen curriculum pack. Dashboard practice records evidence; Anki alone owns due scheduling.' }),
      definitionList([['Eligible review targets', review.targetCount || 0], ['Reader contexts', counts.READER || 0], ['Phrasebook contexts', counts.PHRASEBOOK || 0], ['Generated contexts', counts.GENERATED || 0]], 'language-evidence'),
      node('div', { className: 'language-cloze-shared-controls' }, [sharedLength, answerStyle, reviewStart]),
      packs.length ? node('div', { className: 'language-cloze-shared-controls' }, [packSelect, curriculumStart]) : null,
      !review.available ? node('p', { className: 'language-empty-copy', text: 'Add analyzed Reader text or an exact linked Phrasebook context to unlock review practice.' }) : null,
    ]),
  ]);
}

function completedView(state, actions) {
  const rows = state.attempts || [];
  const count = (outcome) => rows.filter((item) => item.outcome === outcome).length;
  const correct = count('CORRECT'); const incorrect = count('INCORRECT'); const answered = correct + incorrect;
  const sourceCount = new Set(rows.map((item) => item.sourceContextType).filter(Boolean)).size;
  const targetCount = new Set(rows.map((item) => item.targetLemmaId || item.referenceTargetStableKey).filter(Boolean)).size;
  const back = node('button', { className: 'language-button is-primary', type: 'button', text: 'Back to Cloze practice' });
  back.addEventListener('click', actions.onBack);
  return node('section', { className: 'language-card language-cloze-complete' }, [
    node('p', { className: 'language-kicker', text: 'SESSION COMPLETE' }), node('h3', { text: `${state.session?.answeredCount || 0} questions finished` }),
    node('p', { text: 'A correct answer is evidence, not mastery. No dashboard due date was created.' }),
    definitionList([['Correct', correct], ['Incorrect', incorrect], ['Revealed', count('REVEALED')], ['Skipped', count('SKIPPED')], ['Accuracy', answered ? `${Math.round((correct / answered) * 100)}%` : 'Not available'], ['Sources used', sourceCount], ['Targets practiced', targetCount]], 'language-evidence'),
    node('div', { className: 'language-form-actions' }, [back, node('a', { className: 'language-button', text: 'Open Reviews', attrs: { href: '#reviews' } })]),
  ]);
}

function sourceDescription(item, feedback) {
  const source = item.source || feedback?.source || {};
  const type = item.sourceContextType || feedback?.sourceContextType || source.type || 'TATOEBA';
  const labels = { TATOEBA: 'Tatoeba', READER: 'Reader', PHRASEBOOK: 'Phrasebook', GENERATED: 'Generated text' };
  const identifier = source.sentenceId || source.sourceEntityId || '';
  const curriculum = item.curriculum ? `Curriculum ${item.curriculum.name || item.curriculum.packId} v${item.curriculum.version} · ` : '';
  return `Source: ${curriculum}${labels[type] || type}${identifier ? ` #${identifier}` : ''}${source.license ? ` · ${source.license}` : ''}`;
}

function playView(state, actions) {
  const session = state.session; const feedback = state.feedback;
  const item = feedback ? state.lastItem : session?.currentItem;
  if (!item && session?.status === 'COMPLETED') return completedView(state, actions);
  if (!item) return messageState('empty', 'This Cloze session has no current question.');
  const progressIndex = feedback ? Number(state.lastItem.index) : Number(item.index);
  const typed = item.questionType === 'TYPED';
  const optionButtons = (item.options || []).map((option, index) => {
    let className = 'language-cloze-option';
    if (feedback && option === feedback.expectedSurfaceForm) className += ' is-correct';
    if (feedback && option === feedback.chosenOption && feedback.outcome === 'INCORRECT') className += ' is-incorrect';
    const button = node('button', { className, type: 'button', disabled: state.busy || Boolean(feedback) }, [node('kbd', { text: `${index + 1}` }), node('span', { text: option })]);
    button.addEventListener('click', () => actions.onAnswer(index)); return button;
  });
  const typedInput = node('input', { className: 'language-cloze-typed-input', type: 'text', placeholder: 'Type the exact missing form', disabled: state.busy || Boolean(feedback), attrs: { 'aria-label': 'Typed Cloze answer', maxlength: '200', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false' } });
  const typedForm = node('form', { className: 'language-cloze-typed' }, [typedInput, node('button', { className: 'language-button is-primary', type: 'submit', text: 'Check answer', disabled: state.busy || Boolean(feedback) })]);
  typedForm.addEventListener('submit', (event) => { event.preventDefault(); if (!typedInput.value.trim()) typedInput.focus(); else actions.onTypedAnswer(typedInput.value); });
  const reason = node('select', { attrs: { 'aria-label': 'Bad question reason' } }, [
    ['WRONG_ANSWER', 'Wrong expected answer'], ['AMBIGUOUS_ANSWER', 'Ambiguous answer'], ['MULTIPLE_VALID_ANSWERS', 'Multiple valid answers'],
    ['UNNATURAL_SENTENCE', 'Unnatural sentence'], ['BAD_DISTRACTORS', 'Bad distractors'], ['BAD_MAPPING', 'Wrong lemma mapping'],
    ['UNNATURAL_GENERATED_CONTEXT', 'Bad generated context'], ['OTHER', 'Other'],
  ].map(([value, text]) => node('option', { value, text })));
  const report = node('button', { className: 'language-button is-quiet', type: 'button', text: 'Report bad question', disabled: state.busy });
  report.addEventListener('click', () => actions.onReport(reason.value));
  const footerActions = [];
  if (feedback) {
    const next = node('button', { className: 'language-button is-primary language-cloze-next', type: 'button', text: 'Next', disabled: state.busy });
    next.addEventListener('click', actions.onNext); footerActions.push(next);
  } else {
    const reveal = node('button', { className: 'language-button', type: 'button', text: 'Reveal', disabled: state.busy });
    const skip = node('button', { className: 'language-button', type: 'button', text: 'Skip', disabled: state.busy });
    reveal.addEventListener('click', actions.onReveal); skip.addEventListener('click', actions.onSkip); footerActions.push(reveal, skip);
  }
  const answerDetail = feedback?.questionType === 'TYPED' && feedback.userAnswer != null ? `Your answer: ${feedback.userAnswer} · Expected: ${feedback.expectedSurfaceForm}` : feedback ? `Expected: ${feedback.expectedSurfaceForm}` : '';
  const rankDetail = feedback?.rankLabel && feedback?.kellyLearnerRank != null ? `${feedback.targetLemmaDisplay} · ${feedback.rankLabel} ${feedback.kellyLearnerRank}` : feedback?.targetLemmaDisplay || '';
  const feedbackNode = feedback ? node('div', { className: `language-cloze-feedback is-${feedback.outcome.toLowerCase()}`, attrs: { role: 'status', 'aria-live': 'assertive' } }, [
    statusPill(feedback.outcome === 'CORRECT' ? 'Correct' : feedback.outcome === 'INCORRECT' ? 'Incorrect' : feedback.outcome, feedback.outcome === 'CORRECT' ? 'success' : 'warning'), node('strong', { text: answerDetail }), node('span', { text: rankDetail }),
  ]) : null;
  const audioKey = `${session.id}:${item.index}:${item.fingerprint}`; const audio = state.audio || { status: 'IDLE', itemKey: '', error: null };
  const currentAudio = audio.itemKey === audioKey; const loadingAudio = currentAudio && audio.status === 'LOADING'; const playingAudio = currentAudio && audio.status === 'PLAYING';
  const listen = node('button', { className: 'language-button language-cloze-listen', type: 'button', text: loadingAudio ? 'Generating audio…' : playingAudio ? '🔊 Playing…' : '🔊 Play sentence', disabled: loadingAudio, attrs: { title: 'Play the complete Norwegian sentence' } });
  listen.addEventListener('click', () => actions.onPlayAudio(item));
  const audioError = currentAudio && audio.status === 'ERROR' ? node('span', { className: 'language-cloze-audio-error', text: audio.error, attrs: { role: 'status' } }) : null;
  const saveStatus = node('span', { className: 'language-definition', attrs: { role: 'status' } });
  const saveExpression = node('button', { className: 'language-button', type: 'button', text: 'Save sentence' });
  saveExpression.addEventListener('click', async () => {
    saveExpression.disabled = true; saveStatus.textContent = 'Saving…';
    try { const result = await actions.onSaveExpression(item); saveStatus.textContent = result?.reused ? 'Already in Phrasebook for this context.' : 'Saved to Phrasebook.'; }
    catch (error) { saveStatus.textContent = error?.message || 'Sentence could not be saved.'; }
    finally { saveExpression.disabled = false; }
  });
  const result = node('div', { className: 'language-cloze-play' }, [
    node('div', { className: 'language-view-head' }, [node('div', {}, [node('p', { className: 'language-kicker', text: session.trackKey.replaceAll('_', ' ') }), node('h3', { text: `Question ${progressIndex + 1} of ${session.actualItemCount}` })]), node('button', { className: 'language-button is-quiet', type: 'button', text: 'Back' })]),
    node('section', { className: 'language-card language-cloze-question' }, [
      questionSentence(item, feedback, Boolean(actions.onLookupSurface)), node('div', { className: 'language-cloze-audio-row' }, [listen, audioError]), translationNode(item, feedback, state.preferences),
      typed ? typedForm : node('div', { className: 'language-cloze-options' }, optionButtons), feedbackNode,
      node('div', { className: 'language-cloze-actions' }, [...footerActions, feedback ? saveExpression : null, reason, report, saveStatus]), preferenceControls(state, actions, true),
      feedback && item.targetLemmaId ? node('a', { className: 'language-definition', text: `Open full lexical detail: ${feedback.targetLemmaDisplay || item.targetLemmaDisplay || 'target lemma'}`, attrs: { href: `#vocabulary/lemma/${encodeURIComponent(item.targetLemmaId)}` } }) : null,
      node('p', { className: 'language-definition', text: sourceDescription(item, feedback) }),
    ]),
  ]);
  queueMicrotask(() => { if (feedback) result.querySelector('.language-cloze-next')?.focus(); else if (typed) typedInput.focus(); });
  return result;
}

export function renderCloze(mount, state, actions) {
  if (state.loading && !state.tracks) { replace(mount, messageState('loading', 'Loading Cloze practice…')); return () => {}; }
  if (state.error) { replace(mount, messageState('error', 'Cloze is unavailable.', state.error)); return () => {}; }
  const content = state.session ? playView(state, actions) : startView(state, actions); replace(mount, content);
  const sentence = content.querySelector?.('.language-cloze-sentence');
  const inspector = sentence?.lookupTokens?.length && actions.onLookupSurface
    ? createLexicalInspector({ root: sentence, tokens: sentence.lookupTokens, sentences: [sentence.lookupContext],
      surfaceLookup: actions.onLookupSurface, fallbackLookup: actions.onLookupMeanings,
      detailLookup: actions.onLexicalDetail, savePhrase: state.feedback ? () => actions.onSaveExpression(state.lastItem) : null,
      documentRef: mount.ownerDocument, windowRef: mount.ownerDocument.defaultView }) : null;
  const documentRef = mount.ownerDocument;
  const keyboard = (event) => {
    if (state.busy || !state.session) return;
    const tag = String(event.target?.tagName || '').toLowerCase(); if (['input', 'select', 'textarea', 'button'].includes(tag)) return;
    if (state.feedback && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); actions.onNext(); return; }
    if (state.feedback || state.session?.currentItem?.questionType === 'TYPED') return;
    const index = ({ '1': 0, '2': 1, '3': 2, '4': 3 })[event.key]; if (index !== undefined) { event.preventDefault(); actions.onAnswer(index); }
  };
  documentRef.addEventListener('keydown', keyboard);
  content.querySelector('.language-view-head > button')?.addEventListener('click', actions.onBack);
  return () => { documentRef.removeEventListener('keydown', keyboard); inspector?.destroy(); };
}
