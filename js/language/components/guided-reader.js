import { wordAudioControl } from './word-audio-control.js';

const STATUS_KEYS = { '1': 'NEW', '2': 'LEARNING', '3': 'KNOWN', '4': 'MASTERED', x: 'IGNORED', X: 'IGNORED' };
const ACTIONS = [['NEW', '1 New'], ['LEARNING', '2 Learning'], ['KNOWN', '3 Known'], ['MASTERED', '4 Mastered'], ['IGNORED', 'X Ignore']];

function el(documentRef, tag, className = '', text = '') {
  const item = documentRef.createElement(tag);
  item.className = className;
  item.textContent = text;
  return item;
}

function englishMeaning(data) {
  const user = (data?.translations?.user || []).find((item) => String(item.targetLocale || '').toLowerCase().startsWith('en') && item.translationText);
  if (user) return user.translationText;
  const gloss = (data?.translations?.learnerGlosses || []).find((item) => item.value);
  if (gloss) return gloss.value;
  const machine = (data?.translations?.machine || []).find((item) => String(item.targetLocale || '').toLowerCase().startsWith('en') && item.value);
  return machine ? `${machine.value} (automatic)` : 'English meaning unavailable';
}

export function createGuidedReader({
  source, sentences = [], tokens = [], initialSentenceId = null,
  preview, lookupSurface, lookupMeanings, updateStatus, translateSentence, openFull, playWordAudio,
  documentRef = document, windowRef = window,
}) {
  const sentenceNodes = sentences.map((sentence) => source.querySelector(`[data-sentence-id="${sentence.id}"]`)).filter(Boolean);
  const byId = new Map(sentences.map((sentence) => [sentence.id, sentence]));
  const tokenById = new Map(tokens.map((token) => [token.id, token]));
  const notes = new Map();
  const meaningCache = new Map();
  const toolbar = el(documentRef, 'div', 'language-guided-toolbar');
  const toggle = el(documentRef, 'button', 'language-button language-guided-toggle', 'Sentence focus: on');
  const previous = el(documentRef, 'button', 'language-button', '← Sentence');
  const next = el(documentRef, 'button', 'language-button', 'Sentence →');
  const position = el(documentRef, 'span', 'language-guided-position');
  const jump = el(documentRef, 'select', 'language-guided-jump');
  jump.setAttribute('aria-label', 'Jump to sentence');
  sentences.forEach((sentence, index) => {
    const option = documentRef.createElement('option');
    option.value = String(index);
    option.textContent = `${index + 1}. ${String(sentence.exactText || '').trim().slice(0, 55)}`;
    jump.append(option);
  });
  const help = el(documentRef, 'aside', 'language-reader-sentence-help');
  const helperTitle = el(documentRef, 'p', 'language-kicker', 'CURRENT SENTENCE');
  const englishTitle = el(documentRef, 'h4', '', 'English translation');
  const english = el(documentRef, 'p', 'language-reader-help-text');
  const glossesSection = el(documentRef, 'section', 'language-reader-context-words');
  const glossesTitle = el(documentRef, 'h4', '', 'Words in this sentence');
  const glossesList = el(documentRef, 'ul');
  glossesSection.append(glossesTitle, glossesList);
  const grammarTitle = el(documentRef, 'h4', '', 'Grammar hint');
  const grammar = el(documentRef, 'p', 'language-reader-help-text');
  const translate = el(documentRef, 'button', 'language-button', 'Translate this sentence');
  const helpStatus = el(documentRef, 'p', 'language-reader-help-status');
  translate.type = 'button';
  helpStatus.setAttribute('role', 'status');
  help.append(helperTitle, englishTitle, english, glossesSection, grammarTitle, grammar, translate, helpStatus);
  for (const button of [toggle, previous, next]) button.type = 'button';
  toolbar.append(toggle, previous, position, jump, next);
  let active = true;
  let sentenceIndex = Math.max(0, sentenceNodes.findIndex((item) => item.dataset.sentenceId === initialSentenceId));
  let activeWord = null;
  let popup = null;
  let lookupSerial = 0;
  let lookupController = null;
  let busy = false;
  let destroyed = false;

  const wordsInSentence = () => [...sentenceNodes[sentenceIndex]?.querySelectorAll('.language-reader-token[data-token-id]') || []];
  const hasNewWords = () => wordsInSentence().some((word) => word.dataset.tokenState === 'new');
  const actionable = (word) => ['new', 'learning'].includes(word.dataset.tokenState);

  function contextGlosses(word) {
    const entries = notes.get(word?.dataset.sentenceId)?.glosses;
    return Array.isArray(entries) ? entries.filter((entry) => entry.tokenIds?.includes(word.dataset.tokenId)) : [];
  }

  function removePopup() {
    lookupSerial += 1;
    lookupController?.abort();
    lookupController = null;
    popup?.remove();
    popup = null;
  }

  function placePopup() {
    if (!popup || !activeWord) return;
    const rect = activeWord.getBoundingClientRect();
    const width = Math.min(310, windowRef.innerWidth - 20);
    const height = popup.getBoundingClientRect().height || 145;
    popup.style.width = `${width}px`;
    popup.style.left = `${Math.max(10, Math.min(rect.left, windowRef.innerWidth - width - 10))}px`;
    popup.style.top = `${Math.max(10, rect.bottom + height + 10 < windowRef.innerHeight ? rect.bottom + 7 : rect.top - height - 7)}px`;
  }

  async function showMeaning(word, output, serial) {
    const contextual = contextGlosses(word);
    if (contextual.length) {
      output.textContent = contextual.map((entry) => entry.tokenIds.length > 1
        ? `${entry.source} — ${entry.english}` : entry.english).join('\n');
      return;
    }
    const key = word.dataset.lemmaId || `surface:${word.textContent}`;
    let data = meaningCache.get(key);
    if (!data) {
      const controller = new AbortController();
      lookupController = controller;
      try {
        data = word.dataset.lemmaId && preview
          ? await preview(word.dataset.lemmaId, { signal: controller.signal })
          : lookupSurface ? await lookupSurface(word.textContent, { signal: controller.signal }) : null;
        const hasEnglish = englishMeaning(data) !== 'English meaning unavailable';
        if (!hasEnglish && lookupMeanings && !controller.signal.aborted) {
          const fallback = await lookupMeanings(word.textContent, { signal: controller.signal });
          data = { ...data, translations: { ...data?.translations, machine: fallback?.translations?.machine || [] } };
        }
        if (!controller.signal.aborted) meaningCache.set(key, data);
      } catch {
        if (controller.signal.aborted) return;
        data = null;
      }
    }
    if (!destroyed && serial === lookupSerial && activeWord === word) {
      output.textContent = englishMeaning(data);
      placePopup();
    }
  }

  function showPopup() {
    removePopup();
    if (!active || !activeWord) return;
    const word = activeWord;
    const serial = lookupSerial;
    popup = el(documentRef, 'div', 'language-guided-word-card');
    popup.setAttribute('role', 'group');
    popup.setAttribute('aria-label', `Word ${word.textContent}`);
    const heading = el(documentRef, 'strong', '', word.textContent);
    const meaning = el(documentRef, 'p', 'language-guided-meaning', 'Looking up English meaning…');
    const state = el(documentRef, 'small', '', `Status: ${word.dataset.tokenState || 'unresolved'}`);
    const actions = el(documentRef, 'div', 'language-guided-word-actions');
    for (const [value, label] of ACTIONS) {
      const button = el(documentRef, 'button', 'language-button', label);
      button.type = 'button';
      button.disabled = !word.dataset.lemmaId || !updateStatus;
      button.addEventListener('click', () => setWordStatus(value));
      actions.append(button);
    }
    popup.append(heading);
    const audio = wordAudioControl(documentRef, playWordAudio
      ? (callbacks) => playWordAudio(word.dataset.tokenId, callbacks) : null);
    if (audio) popup.append(audio);
    popup.append(meaning, state, actions);
    if (word.dataset.lemmaId && openFull) {
      const details = el(documentRef, 'button', 'language-button language-guided-details', 'More details');
      details.type = 'button';
      details.addEventListener('click', () => openFull(word.dataset.lemmaId, {
        tokenId: word.dataset.tokenId, sentenceId: word.dataset.sentenceId,
      }));
      popup.append(details);
    }
    documentRef.body.append(popup);
    placePopup();
    showMeaning(word, meaning, serial);
  }

  function selectWord(word, { focus = true, scroll = true, openPopup = true } = {}) {
    activeWord?.classList.remove('is-guided-word');
    activeWord = word || null;
    if (!word) { removePopup(); return; }
    word.classList.add('is-guided-word');
    word.tabIndex = 0;
    if (scroll) scrollIntoViewIfNeeded(word);
    if (focus) word.focus?.({ preventScroll: true });
    if (openPopup) showPopup();
    else removePopup();
  }

  function scrollIntoViewIfNeeded(element) {
    const rect = element.getBoundingClientRect();
    if (rect.top >= 0 && rect.bottom <= windowRef.innerHeight) return;
    element.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }

  function updateHelp() {
    const sentence = byId.get(sentenceNodes[sentenceIndex]?.dataset.sentenceId);
    const note = notes.get(sentence?.id);
    helperTitle.textContent = sentence ? `SENTENCE ${sentenceIndex + 1} OF ${sentenceNodes.length}` : 'CURRENT SENTENCE';
    english.textContent = note?.english || 'Translation not added yet. Use the button below or import a study pack.';
    const words = wordsInSentence();
    const wordOrder = new Map(words.map((word, index) => [word.dataset.tokenId, index]));
    const required = words.filter((word) => ['new', 'learning'].includes(word.dataset.tokenState));
    const entries = Array.isArray(note?.glosses) ? note.glosses : [];
    const visible = entries.filter((entry) => entry.tokenIds?.length > 1
      || entry.tokenIds?.some((id) => required.some((word) => word.dataset.tokenId === id)));
    const covered = new Set(visible.flatMap((entry) => entry.tokenIds));
    const rows = [
      ...visible.map((entry) => ({ source: entry.source, english: entry.english,
        order: Math.min(...entry.tokenIds.map((id) => wordOrder.get(id) ?? Infinity)) })),
      ...required.filter((word) => !covered.has(word.dataset.tokenId))
        .map((word) => ({ source: word.textContent, english: 'Context meaning not in this Study Pack',
          order: wordOrder.get(word.dataset.tokenId) })),
    ].sort((left, right) => left.order - right.order);
    glossesSection.hidden = !rows.length;
    glossesList.replaceChildren(...rows.map((row) => {
      const item = el(documentRef, 'li');
      item.append(el(documentRef, 'strong', '', row.source), documentRef.createTextNode(` — ${row.english}`));
      return item;
    }));
    grammar.textContent = note?.grammarHint || 'Import a study pack to add a clear explanation of this sentence.';
    translate.disabled = !sentence || !translateSentence;
    position.textContent = sentence ? `${sentenceIndex + 1} / ${sentenceNodes.length}${hasNewWords() ? ' · new words remain' : sentenceIndex === sentenceNodes.length - 1 ? ' · last sentence ready' : ' · ready for next sentence'}` : 'No analyzed sentences';
    jump.value = String(sentenceIndex);
    previous.disabled = sentenceIndex <= 0;
    next.disabled = sentenceIndex >= sentenceNodes.length - 1;
  }

  function selectSentence(index, { scroll = true, openPopup = true } = {}) {
    if (index < 0 || index >= sentenceNodes.length) return;
    sentenceNodes[sentenceIndex]?.classList.remove('is-guided-active');
    sentenceNodes[sentenceIndex]?.removeAttribute('aria-current');
    sentenceIndex = index;
    const sentence = sentenceNodes[sentenceIndex];
    sentence.classList.add('is-guided-active');
    sentence.setAttribute('aria-current', 'true');
    const words = wordsInSentence();
    selectWord(words.find((word) => word.dataset.tokenState === 'new') || words.find(actionable) || words[0], { focus: scroll, scroll, openPopup });
    if (scroll && !words.length) scrollIntoViewIfNeeded(sentence);
    helpStatus.textContent = '';
    updateHelp();
  }

  function nextNewWord(afterWord = activeWord) {
    const words = sentenceNodes.flatMap((sentence) => [...sentence.querySelectorAll('.language-reader-token[data-token-id]')]);
    const index = words.indexOf(afterWord);
    return words.slice(index + 1).find((word) => word.dataset.tokenState === 'new') || null;
  }

  function focusWord(word) {
    if (!word || !active) return;
    const index = sentenceNodes.indexOf(word.closest('.language-reader-sentence'));
    if (index !== sentenceIndex) selectSentence(index, { scroll: false, openPopup: false });
    selectWord(word);
    updateHelp();
  }

  function moveWord(delta) {
    const words = wordsInSentence();
    const index = words.indexOf(activeWord);
    const nextIndex = index + delta;
    if (nextIndex >= 0 && nextIndex < words.length) selectWord(words[nextIndex]);
    else if (delta > 0 && !hasNewWords()) selectSentence(sentenceIndex + 1);
    else if (delta > 0) selectWord(words.find((word) => word.dataset.tokenState === 'new') || words[0]);
    else if (delta < 0 && sentenceIndex > 0) {
      selectSentence(sentenceIndex - 1);
      selectWord(wordsInSentence().at(-1));
    }
  }

  async function setWordStatus(status) {
    if (!activeWord?.dataset.lemmaId || busy) return;
    const lemmaId = activeWord.dataset.lemmaId;
    const currentWord = activeWord;
    const popupAtStart = popup;
    busy = true;
    popup?.querySelectorAll('button').forEach((button) => { button.disabled = true; });
    try {
      await updateStatus(lemmaId, status);
      const nextState = status === 'IGNORED' ? 'ignored' : status.toLowerCase();
      source.querySelectorAll('[data-lemma-id]').forEach((word) => {
        if (word.dataset.lemmaId !== lemmaId) return;
        word.classList.remove('is-new', 'is-learning', 'is-known', 'is-mastered', 'is-ignored',
          'is-learning-level-1', 'is-learning-level-2', 'is-learning-level-3');
        word.classList.add(`is-${nextState}`);
        word.dataset.tokenState = nextState;
        word.setAttribute('aria-label', `${word.textContent}, ${nextState}`);
      });
      tokens.filter((item) => item.selectedLemmaId === lemmaId).forEach((item) => {
        if (status === 'IGNORED') item.disposition = 'IGNORED';
        else { item.disposition = 'TRACKED'; item.knowledgeStatus = status; }
      });
      meaningCache.delete(lemmaId);
      if (popup !== popupAtStart || activeWord !== currentWord) {
        updateHelp();
        helpStatus.textContent = 'Word status saved.';
        return;
      }
      const nextNew = nextNewWord(currentWord);
      if (nextNew) focusWord(nextNew);
      else if (sentenceIndex < sentenceNodes.length - 1) selectSentence(sentenceIndex + 1);
      else { selectWord(null); updateHelp(); }
      helpStatus.textContent = 'Word status saved.';
    } catch (error) {
      helpStatus.textContent = error?.message || 'Word status could not be saved.';
      if (popup === popupAtStart && activeWord === currentWord) showPopup();
    } finally { busy = false; }
  }

  function onSourceClick(event) {
    if (!active) return;
    const word = event.target.closest?.('.language-reader-token[data-token-id]');
    const sentence = event.target.closest?.('.language-reader-sentence[data-sentence-id]');
    if (!sentence || !source.contains(sentence)) return;
    const index = sentenceNodes.indexOf(sentence);
    if (index !== sentenceIndex) selectSentence(index, { scroll: false, openPopup: false });
    if (word) { event.stopPropagation(); selectWord(word, { scroll: false }); }
  }

  function onOutsidePointer(event) {
    if (!popup || popup.contains(event.target)) return;
    if (event.target.closest?.('.language-reader-token[data-token-id]') && source.contains(event.target)) return;
    removePopup();
    activeWord?.classList.remove('is-guided-word');
  }

  let scrollFrame = null;
  function onScroll() {
    if (!active || scrollFrame !== null) return;
    scrollFrame = windowRef.requestAnimationFrame(() => {
      scrollFrame = null;
      const viewportHeight = windowRef.innerHeight;
      const visible = sentenceNodes.map((sentence, index) => ({ index, rect: sentence.getBoundingClientRect() }))
        .filter(({ rect }) => rect.bottom > 0 && rect.top < viewportHeight);
      if (!visible.length) return;
      const target = viewportHeight * 0.35;
      visible.sort((left, right) => Math.abs(left.rect.top - target) - Math.abs(right.rect.top - target));
      if (visible[0].index !== sentenceIndex) selectSentence(visible[0].index, { scroll: false, openPopup: false });
    });
  }

  function onKey(event) {
    if (!active || event.altKey || event.ctrlKey || event.metaKey || !activeWord) return;
    if (event.key === 'Escape' && popup) {
      removePopup();
      activeWord.classList.remove('is-guided-word');
      return;
    }
    const target = event.target;
    if (target.closest?.('input,textarea,select,[contenteditable="true"],dialog,button:not(.language-reader-token),a')) return;
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault(); event.stopPropagation(); moveWord(event.key === 'ArrowRight' ? 1 : -1);
    } else if (STATUS_KEYS[event.key] && popup) {
      event.preventDefault(); event.stopPropagation(); setWordStatus(STATUS_KEYS[event.key]);
    } else if (event.key === 'Enter' && activeWord.dataset.lemmaId && openFull) {
      event.preventDefault(); event.stopPropagation(); openFull(activeWord.dataset.lemmaId, {
        tokenId: activeWord.dataset.tokenId, sentenceId: activeWord.dataset.sentenceId,
      });
    }
  }

  toggle.addEventListener('click', () => {
    active = !active;
    source.classList.toggle('is-guided-mode', active);
    toggle.textContent = `Sentence focus: ${active ? 'on' : 'off'}`;
    toggle.setAttribute('aria-pressed', String(active));
    help.hidden = !active;
    previous.disabled = !active || sentenceIndex <= 0;
    next.disabled = !active || sentenceIndex >= sentenceNodes.length - 1;
    if (active) selectSentence(sentenceIndex, { scroll: false });
    else {
      sentenceNodes[sentenceIndex]?.classList.remove('is-guided-active');
      sentenceNodes[sentenceIndex]?.removeAttribute('aria-current');
      activeWord?.classList.remove('is-guided-word');
      removePopup();
    }
  });
  previous.addEventListener('click', () => selectSentence(sentenceIndex - 1));
  next.addEventListener('click', () => selectSentence(sentenceIndex + 1));
  jump.addEventListener('change', () => selectSentence(Number(jump.value)));
  translate.addEventListener('click', async () => {
    const sentence = byId.get(sentenceNodes[sentenceIndex]?.dataset.sentenceId);
    if (!sentence || !translateSentence) return;
    translate.disabled = true;
    helpStatus.textContent = 'Translating…';
    try {
      const result = await translateSentence(sentence, 'en');
      notes.set(sentence.id, { ...notes.get(sentence.id), english: result.translation });
      updateHelp();
      helpStatus.textContent = result.cached ? 'Saved translation loaded.' : 'English translation saved.';
    } catch (error) { helpStatus.textContent = error?.message || 'Translation unavailable.'; }
    finally { translate.disabled = false; }
  });
  source.addEventListener('click', onSourceClick, true);
  documentRef.addEventListener('pointerdown', onOutsidePointer, true);
  documentRef.addEventListener('keydown', onKey, true);
  windowRef.addEventListener('resize', placePopup);
  windowRef.addEventListener('scroll', placePopup, true);
  windowRef.addEventListener('scroll', onScroll, true);
  source.classList.add('is-guided-mode');
  toggle.setAttribute('aria-pressed', 'true');
  if (sentenceNodes.length) selectSentence(sentenceIndex, { scroll: false });
  else updateHelp();
  return {
    toolbar, help, isActive: () => active,
    currentSentenceId: () => sentenceNodes[sentenceIndex]?.dataset.sentenceId || null,
    focusCurrentNewWord() {
      const word = activeWord?.dataset.tokenState === 'new' ? activeWord : nextNewWord();
      if (word || activeWord) focusWord(word || activeWord);
      else {
        const sentence = sentenceNodes[sentenceIndex];
        if (sentence) {
          sentence.tabIndex = -1;
          scrollIntoViewIfNeeded(sentence);
          sentence.focus?.({ preventScroll: true });
        }
      }
    },
    setNotes(items) {
      (items || []).forEach((item) => notes.set(item.sentenceId, { ...notes.get(item.sentenceId), ...item }));
      updateHelp();
      if (popup && activeWord) showPopup();
    },
    selectSentenceById(sentenceId) {
      const index = sentenceNodes.findIndex((item) => item.dataset.sentenceId === sentenceId);
      if (index >= 0 && active) selectSentence(index);
    },
    destroy() {
      destroyed = true;
      removePopup();
      source.removeEventListener('click', onSourceClick, true);
      documentRef.removeEventListener('pointerdown', onOutsidePointer, true);
      documentRef.removeEventListener('keydown', onKey, true);
      windowRef.removeEventListener('resize', placePopup);
      windowRef.removeEventListener('scroll', placePopup, true);
      windowRef.removeEventListener('scroll', onScroll, true);
      if (scrollFrame !== null) windowRef.cancelAnimationFrame(scrollFrame);
    },
  };
}
