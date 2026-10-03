import { wordAudioControl } from './word-audio-control.js';

const STATUS_KEYS = { '1': 'NEW', '2': 'LEARNING', '3': 'KNOWN', '4': 'MASTERED', x: 'IGNORED', X: 'IGNORED' };
const STATES = ['new', 'learning', 'known', 'mastered', 'ignored', 'excluded', 'unresolved'];

export function appendInspectableWords(parent, text, { sourceStart = 0, sentenceId = '', prefix = 'word' } = {}) {
  const tokens = [];
  let cursor = 0;
  let index = 0;
  for (const match of String(text).matchAll(/\p{L}[\p{L}\p{M}'’-]*/gu)) {
    parent.append(parent.ownerDocument.createTextNode(text.slice(cursor, match.index)));
    const start = sourceStart + [...text.slice(0, match.index)].length;
    const end = start + [...match[0]].length;
    const id = `${prefix}:${index++}`;
    const button = element(parent.ownerDocument, 'button', 'language-reader-token is-unresolved', match[0]);
    button.type = 'button'; button.tabIndex = tokens.length ? -1 : 0;
    button.dataset.tokenId = id; button.dataset.sentenceId = sentenceId;
    button.dataset.tokenState = 'unresolved';
    button.setAttribute('aria-label', `${match[0]}, inspect meaning`);
    parent.append(button);
    tokens.push({ id, sentenceId, sourceStart: start, sourceEnd: end, tokenKind: 'WORD' });
    cursor = match.index + match[0].length;
  }
  parent.append(parent.ownerDocument.createTextNode(text.slice(cursor)));
  return tokens;
}

function element(documentRef, tag, className = '', text = '') {
  const item = documentRef.createElement(tag);
  item.className = className;
  item.textContent = text;
  return item;
}

const surfaceOf = (target) => target?.dataset.wordSurface || target?.textContent || '';

function localeMeaning(preview, prefix) {
  const own = (preview?.translations?.user || []).find((row) =>
    String(row.targetLocale || '').toLowerCase().startsWith(prefix));
  if (own?.translationText) return own.translationText;
  if (prefix === 'en') {
    const gloss = (preview?.translations?.learnerGlosses || []).find((row) => row.value);
    if (gloss) return gloss.value;
  }
  const machine = (preview?.translations?.machine || []).find((row) =>
    String(row.targetLocale || '').toLowerCase().startsWith(prefix) && row.value);
  if (machine) return `${machine.value} (automatic)`;
  return prefix === 'pl' ? 'Polish translation unavailable' : 'English meaning unavailable';
}

function sentenceFragment(documentRef, sentence, token) {
  const wrap = element(documentRef, 'p', 'language-word-context');
  const full = [...String(sentence?.exactText || '')];
  const start = Math.max(0, Number(token?.sourceStart || 0) - Number(sentence?.sourceStart || 0));
  const end = Math.max(start, Number(token?.sourceEnd || 0) - Number(sentence?.sourceStart || 0));
  wrap.append(documentRef.createTextNode(full.slice(0, start).join('')));
  wrap.append(element(documentRef, 'mark', '', full.slice(start, end).join('')));
  wrap.append(documentRef.createTextNode(full.slice(end).join('')));
  return wrap;
}

export function createLexicalInspector({
  root, tokens = [], sentences = [], preview, surfaceLookup, fallbackLookup, detailLookup, updateStatus, openFull, savePhrase, playWordAudio,
  documentRef = document, windowRef = window, hoverDelayMs = 320, isEnabled = () => true,
}) {
  const lexical = () => [...root.querySelectorAll('.language-reader-token[data-token-id]')];
  const tokenById = new Map(tokens.map((token) => [token.id, token]));
  const sentenceById = new Map(sentences.map((sentence) => [sentence.id, sentence]));
  const cache = new Map();
  const detailCache = new Map();
  let hoverTimer = null;
  let request = null;
  let detailRequest = null;
  let sequence = 0;
  let active = lexical()[0] || null;
  lexical().forEach((item, index) => { item.tabIndex = index === 0 ? 0 : -1; });
  let pinned = null;
  let quick = null;
  let panel = null;
  let locale = 'both';
  let destroyed = false;

  function cancelHover() {
    windowRef.clearTimeout(hoverTimer);
    hoverTimer = null;
    request?.abort();
    request = null;
    sequence += 1;
    quick?.remove();
    quick = null;
  }

  async function getPreview(target, serial) {
    const lemmaId = target?.dataset.lemmaId;
    const key = lemmaId || `surface:${String(surfaceOf(target)).toLocaleLowerCase('nb-NO')}`;
    if (cache.has(key)) return cache.get(key);
    if (!lemmaId && !surfaceLookup) return null;
    const controller = new AbortController();
    request?.abort();
    request = controller;
    let value = lemmaId
      ? await preview(lemmaId, { signal: controller.signal })
      : await surfaceLookup(surfaceOf(target), { signal: controller.signal });
    const own = value?.translations?.user || [];
    const hasEnglish = own.some((row) => String(row.targetLocale || '').startsWith('en') && row.translationText)
      || (value?.translations?.learnerGlosses || []).some((row) => row.value);
    const hasPolish = own.some((row) => String(row.targetLocale || '').startsWith('pl') && row.translationText);
    if (fallbackLookup && (!hasEnglish || !hasPolish) && !controller.signal.aborted) {
      try {
        const fallback = await fallbackLookup(surfaceOf(target), { signal: controller.signal });
        value = { ...value, translations: { ...value?.translations, machine: fallback?.translations?.machine || [] } };
      } catch (error) { if (error?.name === 'AbortError') return null; }
    }
    if (destroyed || serial !== sequence) return null;
    cache.set(key, value);
    if (cache.size > 48) cache.delete(cache.keys().next().value);
    return value;
  }

  function locate(card, target) {
    const rect = target.getBoundingClientRect();
    card.style.left = `${Math.max(8, Math.min(rect.left, windowRef.innerWidth - 328))}px`;
    card.style.top = `${Math.min(windowRef.innerHeight - 190, rect.bottom + 9)}px`;
  }

  function displayMeanings(host, data) {
    if (locale !== 'pl') host.append(element(documentRef, 'p', '', `EN · ${localeMeaning(data, 'en')}`));
    if (locale !== 'en') host.append(element(documentRef, 'p', '', `PL · ${localeMeaning(data, 'pl')}`));
  }

  async function showQuick(target) {
    if (destroyed || !target || pinned) return;
    const serial = ++sequence;
    let data = null;
    try { data = await getPreview(target, serial); }
    catch (error) { if (error?.name === 'AbortError') return; }
    if (destroyed || serial !== sequence || pinned) return;
    quick?.remove();
    quick = element(documentRef, 'div', 'language-word-quick');
    quick.setAttribute('role', 'tooltip');
    quick.append(element(documentRef, 'strong', '', surfaceOf(target)),
      element(documentRef, 'small', '', data?.partOfSpeech || target.dataset.tokenState || 'Word'));
    displayMeanings(quick, data);
    quick.append(element(documentRef, 'small', '', data?.knowledgeStatus || target.dataset.tokenState || 'Unresolved'));
    quick.append(element(documentRef, 'small', '', 'Click for dictionary sources'));
    documentRef.body.append(quick);
    locate(quick, target);
  }

  function scheduleQuick(target) {
    if (pinned) return;
    cancelHover();
    hoverTimer = windowRef.setTimeout(() => showQuick(target), hoverDelayMs);
  }

  function select(target, focus = true) {
    if (!target) return;
    active?.classList.remove('is-selected');
    if (active) active.tabIndex = -1;
    active = target;
    active.classList.add('is-selected');
    active.tabIndex = 0;
    if (focus) active.focus({ preventScroll: true });
    const rect = active.getBoundingClientRect?.();
    if (rect && (rect.top < 40 || rect.bottom > windowRef.innerHeight - 40)) active.scrollIntoView?.({ block: 'nearest' });
  }

  function closePanel() {
    if (!panel) return;
    detailRequest?.abort(); detailRequest = null;
    if (panel.open && typeof panel.close === 'function') panel.close();
    else panel.removeAttribute('open');
    panel.remove();
    panel = null;
    const restore = pinned;
    pinned = null;
    restore?.focus({ preventScroll: true });
  }

  async function setStatus(target, status, output = null) {
    if (!target?.dataset.lemmaId) return;
    try {
      if (output) output.textContent = 'Saving…';
      await updateStatus(target.dataset.lemmaId, status);
      const nextState = status === 'IGNORED' ? 'ignored' : status.toLowerCase();
      root.querySelectorAll('[data-lemma-id]').forEach((item) => {
        if (item.dataset.lemmaId !== target.dataset.lemmaId) return;
        STATES.forEach((state) => item.classList.remove(`is-${state}`));
        item.classList.add(`is-${nextState}`);
        item.dataset.tokenState = nextState;
        item.setAttribute('aria-label', `${surfaceOf(item)}, ${nextState}`);
        const model = tokenById.get(item.dataset.tokenId);
        if (model) {
          model.knowledgeStatus = status === 'IGNORED' ? model.knowledgeStatus : status;
          model.disposition = status === 'IGNORED' ? 'IGNORED' : 'TRACKED';
        }
      });
      cache.delete(target.dataset.lemmaId);
      closePanel();
      const items = lexical();
      const index = items.indexOf(target);
      select(items[Math.min(index + 1, items.length - 1)] || target);
    } catch (error) {
      if (output) output.textContent = error?.message || 'Could not save word state.';
      else {
        showQuick(target);
        if (quick) quick.append(element(documentRef, 'p', 'language-inline-error', error?.message || 'Could not save word state.'));
      }
    }
  }

  async function openPanel(target) {
    cancelHover();
    select(target, false);
    pinned = target;
    panel = element(documentRef, 'dialog', 'language-word-panel');
    const heading = element(documentRef, 'h2', '', surfaceOf(target));
    heading.id = 'language-word-panel-title';
    panel.setAttribute('aria-labelledby', heading.id);
    const close = element(documentRef, 'button', 'language-button', 'Close');
    close.type = 'button';
    close.addEventListener('click', closePanel);
    panel.addEventListener('cancel', (event) => { event.preventDefault(); closePanel(); });
    const token = tokenById.get(target.dataset.tokenId);
    const sentence = sentenceById.get(target.dataset.sentenceId);
    const status = element(documentRef, 'p', 'language-word-status');
    status.setAttribute('role', 'status');
    const meaning = element(documentRef, 'div', 'language-word-meanings', 'Loading meaning…');
    const forms = element(documentRef, 'p', 'language-word-forms');
    const localeSelect = element(documentRef, 'select');
    localeSelect.setAttribute('aria-label', 'Translation language');
    [['both', 'English and Polish'], ['en', 'English'], ['pl', 'Polish']].forEach(([value, label]) => {
      const option = element(documentRef, 'option', '', label); option.value = value; localeSelect.append(option);
    });
    localeSelect.value = locale;
    let data = null;
    let lexicalDetail = null;
    const renderMeaning = () => {
      meaning.replaceChildren(); displayMeanings(meaning, data);
      const sense = lexicalDetail?.dictionary?.articles?.flatMap((article) => article.senses || [])?.find((item) => item.definition)?.definition;
      if (sense) meaning.append(element(documentRef, 'p', 'language-word-dictionary-sense', `NO dictionary · ${sense}`));
    };
    localeSelect.addEventListener('change', () => { locale = localeSelect.value; renderMeaning(); });
    const buttons = element(documentRef, 'div', 'language-word-state-actions');
    if (target.dataset.lemmaId && updateStatus) Object.entries({ NEW: '1 New', LEARNING: '2 Learning', KNOWN: '3 Known', MASTERED: '4 Mastered', IGNORED: 'X Ignore' }).forEach(([value, label]) => {
      const button = element(documentRef, 'button', 'language-button', label); button.type = 'button';
      button.addEventListener('click', () => setStatus(target, value, status)); buttons.append(button);
    });
    else buttons.append(element(documentRef, 'p', '', 'Read-only meaning lookup. Inspecting does not change vocabulary.'));
    const actions = element(documentRef, 'div', 'language-form-actions');
    const surface = encodeURIComponent(surfaceOf(target).trim());
    const sources = element(documentRef, 'div', 'language-word-sources');
    for (const [label, url] of [
      ['Bokmålsordboka', `https://ordbokene.no/bm/${surface}`],
      ['NAOB', `https://naob.no/ordbok/${surface}`],
      ['Wiktionary EN', `https://en.wiktionary.org/wiki/${surface}`],
      ['Glosbe EN', `https://glosbe.com/nb/en/${surface}`],
      ['Wikisłownik PL', `https://pl.wiktionary.org/wiki/${surface}`],
      ['Translate EN', `https://translate.google.com/?sl=no&tl=en&text=${surface}&op=translate`],
      ['Translate PL', `https://translate.google.com/?sl=no&tl=pl&text=${surface}&op=translate`],
    ]) {
      const link = element(documentRef, 'a', 'language-button', label);
      link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      sources.append(link);
    }
    if (savePhrase) {
      const save = element(documentRef, 'button', 'language-button', 'Save phrase'); save.type = 'button';
      save.addEventListener('click', async () => {
        try { await savePhrase({ expression: surfaceOf(target), sentence }); status.textContent = 'Saved to Phrasebook.'; }
        catch (error) { status.textContent = error?.message || 'Phrase could not be saved.'; }
      });
      actions.append(save);
    }
    if (target.dataset.lemmaId && openFull) {
      const full = element(documentRef, 'button', 'language-button', 'Open full details'); full.type = 'button';
      full.addEventListener('click', () => { closePanel(); openFull(target.dataset.lemmaId, {
        tokenId: target.dataset.tokenId, sentenceId: target.dataset.sentenceId, lexicalDetail,
      }); });
      actions.append(full);
    }
    const audio = wordAudioControl(documentRef, playWordAudio
      ? (callbacks) => playWordAudio(target.dataset.tokenId, callbacks) : null);
    panel.append(...[heading, audio, element(documentRef, 'p', 'language-word-lemma', target.dataset.lemmaDisplay || 'Meaning not resolved'),
      localeSelect, meaning, sentence ? sentenceFragment(documentRef, sentence, token) : null,
      forms, buttons, sources, actions, status, close].filter(Boolean));
    documentRef.body.append(panel);
    if (typeof panel.showModal === 'function') panel.showModal(); else panel.setAttribute('open', '');
    close.focus();
    const serial = ++sequence;
    try { data = await getPreview(target, serial); }
    catch (error) { if (error?.name !== 'AbortError') status.textContent = 'Meaning lookup unavailable.'; }
    if (pinned === target && panel) {
      renderMeaning();
      forms.textContent = data?.forms?.length ? `Forms · ${data.forms.join(' · ')}` : '';
      if (data?.multipleMeanings || target.dataset.tokenState === 'unresolved') {
        status.textContent = 'Multiple possible meanings. Open full details to inspect the mapping.';
      }
    }
    if ((target.dataset.lemmaId || data?.lemmaId) && detailLookup && pinned === target) {
      try {
        const lemmaId = target.dataset.lemmaId || data.lemmaId;
        if (detailCache.has(lemmaId)) lexicalDetail = detailCache.get(lemmaId);
        else {
          detailRequest = new AbortController();
          lexicalDetail = await detailLookup(lemmaId, { signal: detailRequest.signal });
          detailCache.set(lemmaId, lexicalDetail);
          if (detailCache.size > 20) detailCache.delete(detailCache.keys().next().value);
        }
        if (pinned === target && panel) renderMeaning();
      } catch (error) {
        if (error?.name !== 'AbortError' && pinned === target) status.textContent = 'Dictionary source unavailable; saved meanings remain visible.';
      }
    }
  }

  function onKey(event) {
    if (!isEnabled()) return;
    if (event.target.closest?.('input,textarea,select,[contenteditable="true"]')) return;
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target.closest?.('.language-reader-token[data-token-id]');
    if (!target || !root.contains(target)) return;
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault(); cancelHover();
      const items = lexical();
      const index = items.indexOf(target);
      select(items[Math.max(0, Math.min(items.length - 1, index + (event.key === 'ArrowRight' ? 1 : -1)))], true);
    } else if (STATUS_KEYS[event.key] && updateStatus) {
      event.preventDefault(); setStatus(target, STATUS_KEYS[event.key]);
    } else if (event.key === 'Enter') {
      event.preventDefault(); openPanel(target);
    } else if (event.key === 'Escape') {
      event.preventDefault(); closePanel(); cancelHover();
    }
  }

  root.addEventListener('pointerover', (event) => {
    if (!isEnabled()) return;
    const target = event.target.closest?.('.language-reader-token[data-token-id]');
    if (target && root.contains(target)) scheduleQuick(target);
  });
  root.addEventListener('pointerout', (event) => {
    if (!isEnabled()) return;
    if (pinned) return;
    const target = event.target.closest?.('.language-reader-token[data-token-id]');
    if (target && !target.contains(event.relatedTarget)) cancelHover();
  });
  root.addEventListener('focusin', (event) => {
    if (!isEnabled()) return;
    const target = event.target.closest?.('.language-reader-token[data-token-id]');
    if (target) { select(target, false); scheduleQuick(target); }
  });
  root.addEventListener('focusout', () => { if (!pinned) cancelHover(); });
  root.addEventListener('click', (event) => {
    if (!isEnabled()) return;
    const target = event.target.closest?.('.language-reader-token[data-token-id]');
    if (target && root.contains(target)) openPanel(target);
  });
  root.addEventListener('keydown', onKey);
  return { select, close: closePanel, destroy() { destroyed = true; cancelHover(); closePanel(); } };
}
