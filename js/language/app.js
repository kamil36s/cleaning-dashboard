import { languageApi } from './api.js';
import { formatLanguageRoute, parseLanguageRoute, routeHeading, routeSection } from './router.js';
import { createLanguageState, selectBokmalProfile } from './state.js';
import { messageState, replace } from './components/dom.js';
import { renderLemmaDetail, renderLemmaError, renderReferenceOnlyDetail } from './components/lemma-detail.js';
import { renderLanguageHelp } from './components/help.js';
import { renderOverview } from './views/overview.js';
import { renderProgress } from './views/progress.js';
import { renderBenchmarkLanding, renderBenchmarkRun } from './views/benchmarks.js';
import { renderStudySession } from './views/study-session.js';
import { renderCurriculumLanding, renderCurriculumPack } from './views/curriculum.js';
import { renderGenerate } from './views/generate.js';
import { renderGrammar, mountReaderGrammar } from './views/grammar.js';
import { renderSettings } from './views/settings.js';
import { renderStatistics } from './views/statistics.js';
import { createKnownWordsControl } from './known-words.js';
import { renderGoals } from './views/goals.js';
import { renderReviews } from './views/reviews.js';
import { renderCloze } from './views/cloze.js';
import { createClozeAudioPlayer } from './cloze-audio.js';
import { BrowserSpeechAdapter, clampSpeechRate } from './audio/browser-speech.js';
import { createLanguagePlaybackCoordinator } from './audio/playback-coordinator.js';
import { createAuthenticMediaPlayer } from './audio/authentic-media.js';
import { renderListeningLanding, renderListeningText } from './views/listening.js';
import { renderInboxDetail, renderInboxLanding } from './views/inbox.js';
import { renderTopics } from './views/topics.js';
import { renderPhrasebook } from './views/phrasebook.js';
import { createVocabularyView } from './views/vocabulary.js';
import {
  TERMINAL_JOB_STATES,
  createActiveReadingTracker,
  createSentenceExposureObserver,
  renderReaderDocument,
  renderReaderLibrary,
  sentenceOccurrences,
} from './views/reader.js';

function openDialog(dialog) {
  if (!dialog || dialog.open) return;
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
}

function closeDialog(dialog) {
  if (!dialog?.open) return;
  if (typeof dialog.close === 'function') dialog.close();
  else {
    dialog.removeAttribute('open');
    dialog.dispatchEvent(new Event('close'));
  }
}

export function createLanguageApp({
  api = languageApi,
  documentRef = document,
  windowRef = window,
  debounceMs = 250,
  jobPollMs = 750,
  readerHeartbeatMs = 10_000,
  exposureDwellMs = 2_000,
  IntersectionObserverClass = windowRef.IntersectionObserver,
  AudioClass = windowRef.Audio,
  SpeechSynthesisUtteranceClass = windowRef.SpeechSynthesisUtterance,
} = {}) {
  const generationRequestKey = 'language.generation.active-request.v1';
  const clozePreferencesKey = 'language.cloze.preferences.v1';
  const listeningPreferencesKey = 'language.listening.preferences.v1';
  const elements = {
    root: documentRef.querySelector('#language-app'),
    view: documentRef.querySelector('#language-view'),
    heading: documentRef.querySelector('#language-heading'),
    eyebrow: documentRef.querySelector('#language-eyebrow'),
    profileSummary: documentRef.querySelector('#language-profile-summary'),
    notice: documentRef.querySelector('#language-notice'),
    connection: documentRef.querySelector('#language-connection'),
    mobileNav: documentRef.querySelector('#language-mobile-nav'),
    nav: [...documentRef.querySelectorAll('[data-language-route]')],
    lemmaDialog: documentRef.querySelector('#language-lemma-dialog'),
    lemmaMount: documentRef.querySelector('#language-lemma-detail'),
    mergeDialog: documentRef.querySelector('#language-merge-dialog'),
    mergeSummary: documentRef.querySelector('#language-merge-summary'),
    mergeCheck: documentRef.querySelector('#language-merge-confirm-check'),
    mergeConfirm: documentRef.querySelector('#language-merge-confirm'),
    mergeError: documentRef.querySelector('#language-merge-error'),
    helpDialog: documentRef.querySelector('#language-help-dialog'),
    helpMount: documentRef.querySelector('#language-help-content'),
    helpOpen: documentRef.querySelector('#language-help-open'),
    helpClose: documentRef.querySelector('#language-help-close'),
  };
  if (!elements.root || !elements.view) throw new Error('Language page shell is missing');

  const state = createLanguageState();
  try {
    const saved = JSON.parse(windowRef.localStorage?.getItem(clozePreferencesKey) || 'null');
    if (saved && ['BEFORE', 'AFTER', 'OFF'].includes(saved.translationTiming)) {
      state.cloze.preferences = { translationTiming: saved.translationTiming };
    }
  } catch (_error) {
    // Ignore invalid or unavailable browser storage and keep safe defaults.
  }
  let listeningPreferences = {
    preferredVoiceId: '', rate: 1, defaultMode: 'READ_LISTEN', revealCurrent: false,
  };
  try {
    const saved = JSON.parse(windowRef.localStorage?.getItem(listeningPreferencesKey) || 'null');
    if (saved && typeof saved === 'object') {
      listeningPreferences = {
        preferredVoiceId: String(saved.preferredVoiceId || ''),
        rate: clampSpeechRate(saved.rate),
        defaultMode: saved.defaultMode === 'LISTENING_ONLY' ? 'LISTENING_ONLY' : 'READ_LISTEN',
        revealCurrent: Boolean(saved.revealCurrent),
      };
    }
  } catch (_error) {
    // Device-local listening preferences are disposable UI state.
  }
  const playbackCoordinator = createLanguagePlaybackCoordinator();
  let settingsRenderer = null;
  const clozeAudioPlayer = createClozeAudioPlayer({ AudioClass, coordinator: playbackCoordinator, owner: 'cloze-cloud' });
  const generatedAudioPlayer = createClozeAudioPlayer({ AudioClass, coordinator: playbackCoordinator, owner: 'reader-cloud' });
  const wordAudioPlayer = createClozeAudioPlayer({ AudioClass, coordinator: playbackCoordinator, owner: 'word-cloud' });
  const listeningCloudPlayer = createClozeAudioPlayer({ AudioClass, coordinator: playbackCoordinator, owner: 'listening-cloud' });
  const authenticMediaPlayer = createAuthenticMediaPlayer({ AudioClass, coordinator: playbackCoordinator });
  const browserSpeech = new BrowserSpeechAdapter({
    speechSynthesis: windowRef.speechSynthesis,
    UtteranceClass: SpeechSynthesisUtteranceClass,
    coordinator: playbackCoordinator,
    owner: 'listening-browser',
    onStateChange(snapshot) {
      const previousSpeechState = state.listening.speech?.state;
      state.listening.speech = snapshot;
      if (state.route.name === 'benchmarkRun' && snapshot.state !== previousSpeechState
          && previousSpeechState === 'VOICE_LOADING') {
        Promise.resolve().then(() => showBenchmarkRun(state.route.runId));
      }
      if (state.route.name === 'listeningText' && state.listening.payload && !listeningPlayback) {
        renderOpenListeningText();
      }
      if (state.route.name === 'settings') settingsRenderer?.();
    },
  });
  let vocabularyView = null;
  let knownWordsControl = null;
  let vocabularyController = null;
  let overviewController = null;
  let overviewPlanController = null;
  let overviewPlanSequence = 0;
  let progressController = null;
  let benchmarkSequence = 0;
  let sessionSequence = 0;
  const sessionState = { minutes: 20, plan: null, loading: false, error: null };
  let curriculumController = null;
  let analyticsController = null;
  let lemmaController = null;
  let readerController = null;
  let readerView = null;
  let readerTracker = null;
  let sentenceObserver = null;
  let currentReaderSession = null;
  let currentReaderPayload = null;
  let readerCoverageSequence = 0;
  const jobPollTimers = new Map();
  let readerCommandSequence = 0;
  let searchTimer = null;
  let generationPollTimer = null;
  let clozeCleanup = null;
  let listeningView = null;
  let listeningSession = null;
  let listeningSessionPromise = null;
  let listeningPlayback = null;
  let listeningSequence = 0;
  let routeSequence = 0;
  let lemmaSequence = 0;
  let suppressLemmaCloseNavigation = false;
  let pendingMerge = null;
  let started = false;
  let preserveNoticeOnce = false;

  async function playWordAudio(kind, wordId, callbacks = {}) {
    if (typeof api.wordAudio !== 'function') throw new Error('Word pronunciation is unavailable.');
    let result = await api.wordAudio(kind, wordId, { retry: true });
    for (let attempt = 0; ['QUEUED', 'RUNNING'].includes(result.state) && attempt < 150; attempt += 1) {
      callbacks.onQueued?.(result.state);
      await new Promise((resolve) => windowRef.setTimeout(resolve, 1000));
      result = await api.wordAudio(kind, wordId);
    }
    if (result.state !== 'READY' || !result.audioUrl) {
      const message = result.state === 'UNAVAILABLE'
        ? 'Pronunciation is available for single words only.'
        : result.errorCode === 'cloze_audio_credentials_missing' || result.errorCode === 'cloze_audio_credentials_invalid'
          ? 'Google Cloud TTS is not configured.'
          : result.errorCode === 'cloze_audio_quota_limit'
            ? 'Google Cloud TTS quota was reached.'
            : result.state === 'FAILED' ? 'Pronunciation generation failed. Try again.'
              : 'Pronunciation is not ready yet. Try again shortly.';
      throw new Error(message);
    }
    callbacks.onReady?.(result.audioUrl);
    return wordAudioPlayer.play(result.audioUrl, callbacks);
  }

  function setConnection(status, text) {
    if (!elements.connection) return;
    elements.connection.dataset.state = status;
    const label = elements.connection.querySelector('strong');
    if (label) label.textContent = text;
  }

  function updateProfileSummary() {
    if (!elements.profileSummary) return;
    elements.profileSummary.replaceChildren();
    if (!state.profile) return;
    const identity = documentRef.createElement('span');
    identity.className = 'language-profile-identity';
    const flag = documentRef.createElementNS('http://www.w3.org/2000/svg', 'svg');
    flag.classList.add('language-profile-flag');
    flag.setAttribute('viewBox', '0 0 22 16');
    flag.setAttribute('aria-hidden', 'true');
    const red = documentRef.createElementNS('http://www.w3.org/2000/svg', 'rect');
    red.setAttribute('width', '22');
    red.setAttribute('height', '16');
    red.setAttribute('fill', '#BA0C2F');
    const white = documentRef.createElementNS('http://www.w3.org/2000/svg', 'path');
    white.setAttribute('d', 'M0 6h6V0h4v6h12v4H10v6H6v-6H0z');
    white.setAttribute('fill', '#fff');
    const blue = documentRef.createElementNS('http://www.w3.org/2000/svg', 'path');
    blue.setAttribute('d', 'M0 7h7V0h2v7h13v2H9v7H7V9H0z');
    blue.setAttribute('fill', '#00205B');
    flag.append(red, white, blue);
    const copy = documentRef.createElement('span');
    copy.className = 'language-profile-copy';
    const strong = documentRef.createElement('strong');
    strong.textContent = state.profile.displayName || 'Language profile';
    const span = documentRef.createElement('span');
    span.textContent = `${state.profile.languageCode || '—'} · ${state.profile.locale || '—'}`;
    copy.append(strong, span);
    identity.append(flag, copy);
    elements.profileSummary.append(identity);
    if (typeof api.vocabulary === 'function') {
      knownWordsControl = createKnownWordsControl({ api, profileId: state.profile.id });
      elements.profileSummary.append(knownWordsControl);
    }
    if (elements.eyebrow) elements.eyebrow.textContent = String(state.profile.displayName || 'LANGUAGE').toUpperCase();
  }

  async function refreshKnownWords() {
    if (!state.profile || typeof api.widgetSummary !== 'function') return;
    try {
      const summary = await api.widgetSummary(state.profile.id);
      knownWordsControl?.setCount(summary.knownWords);
      knownWordsControl?.refresh();
    } catch (_error) { /* The list can still load directly from Vocabulary. */ }
  }

  function showNotice(message) {
    if (!elements.notice) return;
    elements.notice.textContent = message;
    elements.notice.hidden = !message;
  }

  function updateNavigation(route) {
    const section = routeSection(route);
    elements.nav.forEach((link) => {
      if (link.dataset.languageRoute === section) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (elements.heading) elements.heading.textContent = routeHeading(route);
  }

  function setViewBusy(value) {
    elements.view.setAttribute('aria-busy', value ? 'true' : 'false');
  }

  function ensureVocabularyView() {
    if (vocabularyView) return vocabularyView;
    vocabularyView = createVocabularyView(elements.view, state.vocabulary, {
      onQuery(value, { immediate = false } = {}) {
        state.vocabulary.query = value;
        windowRef.clearTimeout(searchTimer);
        if (immediate) loadVocabulary({ reset: true });
        else searchTimer = windowRef.setTimeout(() => loadVocabulary({ reset: true }), debounceMs);
      },
      onKnowledgeStatus(value) {
        state.vocabulary.knowledgeStatus = value;
        loadVocabulary({ reset: true });
      },
      onDisposition(value) {
        state.vocabulary.disposition = value;
        loadVocabulary({ reset: true });
      },
      onOpenLemma(lemmaId) {
        windowRef.location.hash = formatLanguageRoute({ name: 'lemma', lemmaId });
      },
      onPlayAudio: (lemmaId, callbacks) => playWordAudio('lemma', lemmaId, callbacks),
      onPreviewLemma: typeof api.lemmaPreview === 'function'
        ? (lemmaId, options) => api.lemmaPreview(lemmaId, options) : null,
      onLexicalDetail: typeof api.lemmaLexical === 'function'
        ? (lemmaId, options) => api.lemmaLexical(lemmaId, options) : null,
      async onUpdateKnowledge(lemmaId, status) {
        const result = await api.updateLemma(lemmaId, status === 'IGNORED'
          ? { disposition: 'IGNORED' }
          : { knowledgeStatus: status, disposition: 'TRACKED' });
        const item = state.vocabulary.items.find((entry) => entry.id === lemmaId);
        if (item) {
          item.knowledgeStatus = result.knowledge?.knowledgeStatus || item.knowledgeStatus;
          item.disposition = result.knowledge?.disposition || item.disposition;
        }
        refreshKnownWords();
        return result;
      },
      onLoadMore() {
        loadVocabulary({ reset: false });
      },
    });
    return vocabularyView;
  }

  async function loadVocabulary({ reset = true } = {}) {
    if (!state.profile) return;
    if (!reset && !state.vocabulary.nextCursor) return;
    vocabularyController?.abort();
    vocabularyController = new AbortController();
    const sequence = ++state.vocabulary.requestSequence;
    if (reset) {
      state.vocabulary.items = [];
      state.vocabulary.nextCursor = null;
      state.vocabulary.loading = true;
    } else {
      state.vocabulary.loadingMore = true;
    }
    state.vocabulary.error = null;
    state.vocabulary.ankiStatus = { status: 'LOADING', lemmas: {} };
    vocabularyView?.update(state.vocabulary);
    try {
      const result = await api.vocabulary(state.profile.id, {
        q: state.vocabulary.query,
        status: state.vocabulary.knowledgeStatus,
        disposition: state.vocabulary.disposition,
        limit: 30,
        cursor: reset ? undefined : state.vocabulary.nextCursor,
      }, { signal: vocabularyController.signal });
      if (sequence !== state.vocabulary.requestSequence) return;
      state.vocabulary.items = reset ? result.items : [...state.vocabulary.items, ...result.items];
      state.vocabulary.total = result.pagination?.total ?? state.vocabulary.items.length;
      state.vocabulary.nextCursor = result.pagination?.nextCursor ?? null;
      if (state.vocabulary.items.length) {
        const ids = state.vocabulary.items.map((item) => item.id);
        (typeof api.vocabularyAnkiStatus === 'function'
          ? api.vocabularyAnkiStatus(state.profile.id, ids, { signal: vocabularyController.signal })
          : Promise.resolve({ status: 'UNAVAILABLE', lemmas: {} }))
          .then((ankiStatus) => {
            if (sequence !== state.vocabulary.requestSequence) return;
            state.vocabulary.ankiStatus = ankiStatus;
            vocabularyView?.update(state.vocabulary);
          })
          .catch((error) => {
            if (error?.name === 'AbortError' || sequence !== state.vocabulary.requestSequence) return;
            state.vocabulary.ankiStatus = { status: 'UNAVAILABLE', lemmas: {} };
            vocabularyView?.update(state.vocabulary);
          });
      }
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== state.vocabulary.requestSequence) return;
      state.vocabulary.error = error?.message || 'Vocabulary could not be loaded.';
    } finally {
      if (sequence === state.vocabulary.requestSequence) {
        state.vocabulary.loading = false;
        state.vocabulary.loadingMore = false;
        vocabularyView?.update(state.vocabulary);
      }
    }
  }

  function phrasebookActions() {
    return {
      onSearch(query, sourceType) {
        state.phrasebook.query = query;
        state.phrasebook.sourceType = sourceType;
        showPhrasebook();
      },
      async onUpdate(entryId, payload) {
        await api.updatePhrasebookEntry(entryId, payload);
        await showPhrasebook();
      },
      async onDelete(entryId) {
        await api.deletePhrasebookEntry(entryId);
        await showPhrasebook();
      },
    };
  }

  async function showPhrasebook() {
    state.phrasebook.loading = true;
    state.phrasebook.error = null;
    renderPhrasebook(elements.view, state.phrasebook, phrasebookActions());
    try {
      const result = await api.phrasebook(state.profile.id, {
        q: state.phrasebook.query, sourceType: state.phrasebook.sourceType, limit: 100,
      });
      state.phrasebook.items = result.items || [];
      state.phrasebook.total = result.pagination?.total ?? state.phrasebook.items.length;
    } catch (error) {
      state.phrasebook.error = error?.message || 'Phrasebook could not be loaded.';
    } finally {
      state.phrasebook.loading = false;
      if (state.route.name === 'phrasebook') renderPhrasebook(elements.view, state.phrasebook, phrasebookActions());
    }
  }

  async function savePhrasebook(payload) {
    return api.createPhrasebookEntry(state.profile.id, payload);
  }

  function translationHandlers(lemmaId, rerender) {
    return {
      async onSaveTranslation(targetLocale, translation) {
        const result = await api.upsertLemmaTranslation(lemmaId, { targetLocale, translation });
        const rows = state.selectedLemma.lexical.translations.user || [];
        state.selectedLemma.lexical.translations.user = [
          ...rows.filter((item) => item.targetLocale !== targetLocale), result.translation,
        ].sort((left, right) => left.targetLocale.localeCompare(right.targetLocale));
        rerender();
      },
      async onDeleteTranslation(targetLocale) {
        await api.deleteLemmaTranslation(lemmaId, targetLocale);
        state.selectedLemma.lexical.translations.user = (state.selectedLemma.lexical.translations.user || [])
          .filter((item) => item.targetLocale !== targetLocale);
        rerender();
      },
    };
  }

  function enrichLemmaMeanings(detail, rerender, isCurrent) {
    const surface = detail?.lemma?.lemmaDisplay;
    if (!surface || typeof api.lexicalMeanings !== 'function') return;
    api.lexicalMeanings(state.profile.id, surface).then((fallback) => {
      if (!isCurrent() || state.selectedLemma !== detail) return;
      detail.lexical.translations ||= {};
      detail.lexical.translations.machine = fallback.translations?.machine || [];
      rerender();
    }).catch(() => { /* External meanings are optional; dictionary links remain available. */ });
  }

  async function showOverview() {
    vocabularyView = null;
    vocabularyController?.abort();
    overviewController?.abort();
    overviewPlanController?.abort();
    overviewController = new AbortController();
    state.overview.loading = true;
    state.overview.error = null;
    const overviewActions = { onStartSession(minutes) {
      sessionState.minutes = minutes;
      sessionState.plan = state.overview.data?.sessionPreview?.requestedMinutes === minutes
        ? state.overview.data.sessionPreview : null;
      windowRef.location.hash = formatLanguageRoute('study-session');
    }, onSelectDuration(minutes) {
      state.overview.minutes = minutes;
      if (state.overview.data) state.overview.data.sessionPreview = null;
      loadTodayPlan(minutes);
    }, onQuickGenerate(values) {
      const coverage = { VERY_EASY: 99, EASY: 97, BALANCED: 95, CHALLENGING: 90 }[values.difficultyPreset];
      Object.assign(state.generation.form, values, { targetCoverage: coverage });
      windowRef.location.hash = formatLanguageRoute('generate');
    } };
    async function loadTodayPlan(minutes) {
      if (typeof api.studySession !== 'function' || state.overview.data?.policyVersion !== 'language.today-summary/v1') return;
      overviewPlanController?.abort();
      overviewPlanController = new AbortController();
      const sequence = ++overviewPlanSequence;
      state.overview.planLoading = true;
      state.overview.planError = null;
      renderOverview(elements.view, state, overviewActions);
      try {
        const plan = await api.studySession(state.profile.id, minutes, { signal: overviewPlanController.signal });
        if (sequence !== overviewPlanSequence || state.route.name !== 'overview') return;
        state.overview.data.sessionPreview = plan;
      } catch (error) {
        if (error?.name === 'AbortError' || sequence !== overviewPlanSequence) return;
        state.overview.planError = error?.message || 'Session preview is unavailable.';
      } finally {
        if (sequence === overviewPlanSequence && state.route.name === 'overview') {
          state.overview.planLoading = false;
          renderOverview(elements.view, state, overviewActions);
        }
      }
    }
    renderOverview(elements.view, state, overviewActions);
    try {
      const [summary, ankiStatus] = await Promise.all([
        typeof api.todaySummary === 'function'
          ? api.todaySummary(state.profile.id, { signal: overviewController.signal })
          : api.overview(state.profile.id, {}, { signal: overviewController.signal }),
        typeof api.ankiStatus === 'function'
          ? api.ankiStatus(state.profile.id, { signal: overviewController.signal }).catch(() => null)
          : Promise.resolve(null),
      ]);
      state.overview.data = summary;
      if (ankiStatus?.deck && summary.policyVersion === 'language.today-summary/v1') {
        summary.anki = { ...summary.anki, configured: true, status: ankiStatus.status,
          deckName: ankiStatus.deck.name, newToday: ankiStatus.deck.new,
          learningToday: ankiStatus.deck.learn, dueCount: ankiStatus.deck.due,
          answeredCardsToday: ankiStatus.deck.answeredCardsToday, stale: false };
      }
      if (state.route.name === 'overview') void loadTodayPlan(state.overview.minutes);
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.overview.error = error?.message || 'Overview could not be loaded.';
    } finally {
      state.overview.loading = false;
      if (state.route.name === 'overview') renderOverview(elements.view, state, overviewActions);
    }
  }

  function progressActions() {
    return {
      async onCreateCampaign(payload) {
        try {
          await api.createCampaign(state.profile.id, payload);
          await showProgress();
        } catch (error) {
          state.progress.error = error?.message || 'Campaign could not be created.';
          renderProgress(elements.view, state.progress, progressActions());
        }
      },
      async onUpdateCampaign(campaignId, payload) {
        try {
          await api.updateCampaign(campaignId, payload);
          await showProgress();
        } catch (error) {
          state.progress.error = error?.message || 'Campaign could not be updated.';
          renderProgress(elements.view, state.progress, progressActions());
        }
      },
    };
  }

  async function showProgress() {
    progressController?.abort();
    progressController = new AbortController();
    state.progress.loading = true;
    state.progress.error = null;
    renderProgress(elements.view, state.progress, progressActions());
    try {
      state.progress.data = await api.gamification(
        state.profile.id, {}, { signal: progressController.signal },
      );
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.progress.error = error?.message || 'Progress could not be loaded.';
    } finally {
      state.progress.loading = false;
      if (state.route.name === 'progress') renderProgress(elements.view, state.progress, progressActions());
    }
  }

  function curriculumPackActions() {
    return {
      onBack() {
        windowRef.location.hash = formatLanguageRoute('curriculum');
      },
      onQuery(value) {
        state.curriculum.query = value;
        renderCurriculumPack(elements.view, state.curriculum, curriculumPackActions());
      },
      onStateFilter(value) {
        state.curriculum.stateFilter = value;
        renderCurriculumPack(elements.view, state.curriculum, curriculumPackActions());
      },
      async onOpenItem(item) {
        if (item.user?.userLemmaId) {
          windowRef.location.hash = formatLanguageRoute({ name: 'lemma', lemmaId: item.user.userLemmaId });
          return;
        }
        renderReferenceOnlyDetail(elements.lemmaMount, null);
        openDialog(elements.lemmaDialog);
        try {
          const payload = await api.curriculumItem(
            state.profile.id, state.curriculum.pack.id, state.curriculum.pack.version, item.membershipId,
          );
          renderReferenceOnlyDetail(elements.lemmaMount, payload);
        } catch (error) {
          renderLemmaError(elements.lemmaMount, error?.message || 'Curriculum item detail could not be loaded.');
        }
      },
    };
  }

  async function showCurriculumLanding() {
    curriculumController?.abort();
    curriculumController = new AbortController();
    state.curriculum.loading = true;
    state.curriculum.error = null;
    state.curriculum.pack = null;
    renderCurriculumLanding(elements.view, state.curriculum, {});
    try {
      state.curriculum.landing = await api.curriculum(
        state.profile.id, { signal: curriculumController.signal },
      );
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.curriculum.error = error?.message || 'Curriculum could not be loaded.';
    } finally {
      state.curriculum.loading = false;
      if (state.route.name === 'curriculum') renderCurriculumLanding(elements.view, state.curriculum, {
        onOpenPack(packId, version) {
          windowRef.location.hash = formatLanguageRoute({ name: 'curriculumPack', packId, version });
        },
      });
    }
  }

  async function showCurriculumPack(packId, version) {
    curriculumController?.abort();
    curriculumController = new AbortController();
    state.curriculum.loading = true;
    state.curriculum.error = null;
    state.curriculum.pack = null;
    renderCurriculumPack(elements.view, state.curriculum, curriculumPackActions());
    try {
      state.curriculum.pack = await api.curriculumPack(
        state.profile.id, packId, version, { signal: curriculumController.signal },
      );
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.curriculum.error = error?.message || 'Curriculum pack could not be loaded.';
    } finally {
      state.curriculum.loading = false;
      if (state.route.name === 'curriculumPack'
        && state.route.packId === packId && state.route.version === version) {
        renderCurriculumPack(elements.view, state.curriculum, curriculumPackActions());
      }
    }
  }

  async function showStatistics(range = state.statistics.range) {
    analyticsController?.abort();
    analyticsController = new AbortController();
    state.statistics.range = range;
    state.statistics.loading = true;
    state.statistics.error = null;
    renderStatistics(elements.view, state.statistics, { onRange: showStatistics });
    try {
      state.statistics.data = await api.statistics(
        state.profile.id, { range }, { signal: analyticsController.signal },
      );
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.statistics.error = error?.message || 'Statistics could not be loaded.';
    } finally {
      state.statistics.loading = false;
      if (state.route.name === 'statistics') {
        renderStatistics(elements.view, state.statistics, { onRange: showStatistics });
      }
    }
  }

  function goalActions() {
    return {
      async onCreate(payload) {
        await api.createGoal(state.profile.id, payload);
        await loadGoals();
      },
      async onUpdate(goalId, payload) {
        await api.updateGoal(goalId, payload);
        await loadGoals();
      },
    };
  }

  async function loadGoals() {
    analyticsController?.abort();
    analyticsController = new AbortController();
    state.goals.loading = true;
    state.goals.error = null;
    renderGoals(elements.view, state.goals, goalActions());
    try {
      const result = await api.goals(state.profile.id, {}, { signal: analyticsController.signal });
      state.goals.items = result.items || [];
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.goals.error = error?.message || 'Goals could not be loaded.';
    } finally {
      state.goals.loading = false;
      if (state.route.name === 'goals') renderGoals(elements.view, state.goals, goalActions());
    }
  }

  function topicActions() {
    return {
      async onCreate(payload) {
        const result = await api.createTopic(state.profile.id, payload);
        await loadTopics({ selectedId: result.topic.id });
      },
      async onOpen(topicId) {
        state.topics.selected = await api.topic(topicId);
        renderTopics(elements.view, state.topics, topicActions());
      },
      async onUpdate(topicId, payload) {
        await api.updateTopic(topicId, payload);
        await loadTopics({ selectedId: topicId });
      },
      async onSearchLemma(query) {
        const result = await api.vocabulary(state.profile.id, { q: query, limit: 10 });
        return result.items || [];
      },
      async onAssign(topicId, lemmaId) {
        await api.assignTopicLemma(topicId, {
          lemmaId, weight: 1, provenance: 'MANUAL', membershipState: 'MANUAL',
        });
        await loadTopics({ selectedId: topicId });
      },
      async onRemove(topicId, lemmaId) {
        await api.removeTopicLemma(topicId, lemmaId);
        await loadTopics({ selectedId: topicId });
      },
    };
  }

  async function loadTopics({ selectedId = state.topics.selected?.topic?.id } = {}) {
    analyticsController?.abort();
    analyticsController = new AbortController();
    state.topics.loading = true;
    state.topics.error = null;
    renderTopics(elements.view, state.topics, topicActions());
    try {
      const result = await api.topics(
        state.profile.id, { includeArchived: true }, { signal: analyticsController.signal },
      );
      state.topics.items = result.items || [];
      if (selectedId) {
        state.topics.selected = await api.topic(selectedId, { signal: analyticsController.signal });
      } else if (state.topics.selected && !state.topics.items.some((item) => item.topic.id === state.topics.selected.topic.id)) {
        state.topics.selected = null;
      }
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.topics.error = error?.message || 'Topics could not be loaded.';
    } finally {
      state.topics.loading = false;
      if (state.route.name === 'topics') renderTopics(elements.view, state.topics, topicActions());
    }
  }

  async function refreshSelectedLemma(lemmaId) {
    const sequence = ++lemmaSequence;
    lemmaController?.abort();
    lemmaController = new AbortController();
    state.selectedLemma = null;
    state.selectedLemmaLoading = true;
    state.selectedLemmaError = null;
    renderLemmaDetail(elements.lemmaMount, null, {});
    try {
      const [detail, anki, reference, lexical] = await Promise.all([
        api.lemma(lemmaId, { signal: lemmaController.signal }),
        typeof api.lemmaAnki === 'function'
          ? api.lemmaAnki(lemmaId, { signal: lemmaController.signal })
          : Promise.resolve({ status: { status: 'NOT_CONFIGURED' }, linked: false, cards: [] }),
        typeof api.lemmaReference === 'function'
          ? api.lemmaReference(lemmaId, { signal: lemmaController.signal }).catch((error) => ({
            reference: { available: false, error: error?.message || 'Reference lookup unavailable.' },
            resolution: { status: 'UNAVAILABLE', ruleVersion: 'reference-resolver/v1', candidates: [] },
          }))
          : Promise.resolve({ reference: { available: false }, resolution: { status: 'UNAVAILABLE', candidates: [] } }),
        typeof api.lemmaLexical === 'function'
          ? api.lemmaLexical(lemmaId, { signal: lemmaController.signal }).catch((error) => ({
            dictionary: { available: false, lookupStatus: 'PROVIDER_UNAVAILABLE', reason: error?.message || 'Dictionary lookup unavailable.', articles: [] },
            translations: { user: [], learnerGlosses: [], polish: { available: false, status: 'NOT_CONFIGURED' } },
          }))
          : Promise.resolve({ dictionary: { available: false, articles: [] }, translations: { user: [], learnerGlosses: [] } }),
      ]);
      detail.anki = anki;
      detail.reference = reference.reference;
      detail.referenceResolution = reference.resolution;
      detail.lexical = lexical;
      if (sequence !== lemmaSequence || state.route.name !== 'lemma' || state.route.lemmaId !== lemmaId) return;
      state.selectedLemma = detail;
      renderLemmaDetail(elements.lemmaMount, detail, {
        ...ankiLemmaHandlers(lemmaId, null, renderCurrentLemma),
        ...translationHandlers(lemmaId, renderCurrentLemma),
        onPlayAudio: (callbacks) => playWordAudio('lemma', lemmaId, callbacks),
        async onSave(payload) {
          const currentAnki = state.selectedLemma?.anki;
          const currentReference = state.selectedLemma?.reference;
          const currentResolution = state.selectedLemma?.referenceResolution;
          const currentLexical = state.selectedLemma?.lexical;
          const updated = await api.updateLemma(lemmaId, payload);
          updated.anki = currentAnki;
          updated.reference = currentReference;
          updated.referenceResolution = currentResolution;
          updated.lexical = currentLexical;
          state.selectedLemma = updated;
          renderCurrentLemma();
          await loadVocabulary({ reset: true });
        },
        async onLockMapping(formId, targetLemmaId) {
          await api.lockFormMapping(formId, targetLemmaId);
          const currentAnki = state.selectedLemma?.anki;
          const currentReference = state.selectedLemma?.reference;
          const currentResolution = state.selectedLemma?.referenceResolution;
          const currentLexical = state.selectedLemma?.lexical;
          const updated = await api.lemma(lemmaId);
          updated.anki = currentAnki;
          updated.reference = currentReference;
          updated.referenceResolution = currentResolution;
          updated.lexical = currentLexical;
          state.selectedLemma = updated;
          renderCurrentLemma();
        },
        async onSearchMerge(query) {
          const result = await api.vocabulary(state.profile.id, { q: query, limit: 10 });
          return result.items || [];
        },
        onPrepareMerge(target) {
          pendingMerge = { source: state.selectedLemma.lemma, target, returnRoute: { ...state.route } };
          elements.mergeSummary.textContent = `Merge “${pendingMerge.source.lemmaDisplay}” into “${pendingMerge.target.lemmaDisplay}” (${pendingMerge.target.partOfSpeech || 'POS not reported'}). The source ID will become a redirect.`;
          elements.mergeCheck.checked = false;
          elements.mergeConfirm.disabled = true;
          elements.mergeError.hidden = true;
          openDialog(elements.mergeDialog);
          elements.mergeCheck.focus();
        },
      });
      openDialog(elements.lemmaDialog);
      enrichLemmaMeanings(detail, renderCurrentLemma,
        () => sequence === lemmaSequence && state.route.name === 'lemma' && state.route.lemmaId === lemmaId);
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== lemmaSequence) return;
      state.selectedLemmaError = error;
      renderLemmaError(elements.lemmaMount, error?.message || 'The lemma could not be loaded.', {
        notFound: error?.status === 404 || error?.code === 'language_lemma_not_found',
      });
    } finally {
      if (sequence === lemmaSequence) state.selectedLemmaLoading = false;
    }
  }

  function renderCurrentLemma() {
    if (!state.selectedLemma || state.route.name !== 'lemma') return;
    const lemmaId = state.route.lemmaId;
    renderLemmaDetail(elements.lemmaMount, state.selectedLemma, {
      ...ankiLemmaHandlers(lemmaId, null, renderCurrentLemma),
      ...translationHandlers(lemmaId, renderCurrentLemma),
      onPlayAudio: (callbacks) => playWordAudio('lemma', lemmaId, callbacks),
      async onSave(payload) {
        const currentAnki = state.selectedLemma?.anki;
        const currentReference = state.selectedLemma?.reference;
        const currentResolution = state.selectedLemma?.referenceResolution;
        const currentLexical = state.selectedLemma?.lexical;
        state.selectedLemma = await api.updateLemma(lemmaId, payload);
        state.selectedLemma.anki = currentAnki;
        state.selectedLemma.reference = currentReference;
        state.selectedLemma.referenceResolution = currentResolution;
        state.selectedLemma.lexical = currentLexical;
        renderCurrentLemma();
        await loadVocabulary({ reset: true });
      },
      async onLockMapping(formId, targetLemmaId) {
        await api.lockFormMapping(formId, targetLemmaId);
        const currentAnki = state.selectedLemma?.anki;
        const currentReference = state.selectedLemma?.reference;
        const currentResolution = state.selectedLemma?.referenceResolution;
        const currentLexical = state.selectedLemma?.lexical;
        state.selectedLemma = await api.lemma(lemmaId);
        state.selectedLemma.anki = currentAnki;
        state.selectedLemma.reference = currentReference;
        state.selectedLemma.referenceResolution = currentResolution;
        state.selectedLemma.lexical = currentLexical;
        renderCurrentLemma();
      },
      async onSearchMerge(query) {
        const result = await api.vocabulary(state.profile.id, { q: query, limit: 10 });
        return result.items || [];
      },
      onPrepareMerge(target) {
        pendingMerge = { source: state.selectedLemma.lemma, target };
        elements.mergeSummary.textContent = `Merge “${pendingMerge.source.lemmaDisplay}” into “${pendingMerge.target.lemmaDisplay}” (${pendingMerge.target.partOfSpeech || 'POS not reported'}). The source ID will become a redirect.`;
        elements.mergeCheck.checked = false;
        elements.mergeConfirm.disabled = true;
        elements.mergeError.hidden = true;
        openDialog(elements.mergeDialog);
        elements.mergeCheck.focus();
      },
    });
  }

  function showVocabulary({ lemmaId = null } = {}) {
    ensureVocabularyView();
    if (!state.vocabulary.items.length && !state.vocabulary.loading) loadVocabulary({ reset: true });
    if (lemmaId) refreshSelectedLemma(lemmaId);
  }

  function readerCommandId(prefix) {
    readerCommandSequence += 1;
    return `${prefix}-${Date.now()}-${readerCommandSequence}`;
  }

  function clearJobPolls() {
    jobPollTimers.forEach((timer) => windowRef.clearTimeout(timer));
    jobPollTimers.clear();
  }

  function setReaderActivity(active) {
    readerTracker?.setActive(active);
    sentenceObserver?.setActive(active);
    readerView?.setSessionState?.(active ? 'ACTIVE' : (currentReaderSession ? 'PAUSED' : 'IDLE'));
  }

  async function sendReaderCommand(action, { quiet = false } = {}) {
    if (!currentReaderSession) return null;
    const sessionId = currentReaderSession.id;
    try {
      const result = await api.updateReaderSession(sessionId, {
        action,
        commandId: readerCommandId(action.toLowerCase()),
      });
      if (currentReaderSession?.id === sessionId) {
        currentReaderSession = result.session;
        setReaderActivity(result.session.activityState === 'ACTIVE' && result.session.status === 'ACTIVE');
      }
      return result.session;
    } catch (error) {
      setReaderActivity(false);
      if (!quiet) showNotice(error?.message || 'Reader session could not be updated.');
      return null;
    }
  }

  function disposeReaderActivity({ pause = false } = {}) {
    if (pause && currentReaderSession?.status === 'ACTIVE' && currentReaderSession?.activityState === 'ACTIVE') {
      sendReaderCommand('PAUSE', { quiet: true });
    }
    readerTracker?.destroy();
    sentenceObserver?.destroy();
    readerView?.destroy?.();
    generatedAudioPlayer.stop();
    readerTracker = null;
    sentenceObserver = null;
    readerView = null;
    currentReaderPayload = null;
    currentReaderSession = null;
  }

  function renderReaderLibraryState() {
    renderReaderLibrary(elements.view, state.reader, {
      async onCreate({ title, rawText, analyze }) {
        const result = await api.createText({
          languageProfileId: state.profile.id,
          title,
          rawText,
          sourceType: 'PASTED',
        });
        if (analyze) {
          const queued = await api.analyzeText(result.text.id);
          state.reader.jobs.set(result.text.id, queued.job);
          pollReaderJob(queued.job.id, result.text.id);
        }
        await loadReaderLibrary();
      },
      onOpen(textId) {
        windowRef.location.hash = formatLanguageRoute({ name: 'readerText', textId });
      },
      async onCreateSeries(payload) {
        await api.createReadingSeries(state.profile.id, payload);
        await loadReaderLibrary();
      },
      async onUpdateSeries(seriesId, payload) {
        await api.updateReadingSeries(seriesId, payload);
        await loadReaderLibrary();
      },
      async onAssignSeries(textId, seriesId) {
        await api.assignTextSeries(textId, seriesId);
        await loadReaderLibrary();
      },
      async onLoadMore() {
        if (!state.reader.nextCursor || state.reader.loadingMore) return;
        state.reader.loadingMore = true;
        if (state.route.name === 'reader') renderReaderLibraryState();
        try {
          state.reader.error = null;
          const result = await api.texts(state.profile.id, { limit: 100, cursor: state.reader.nextCursor });
          state.reader.items.push(...(result.items || []));
          state.reader.nextCursor = result.pagination?.nextCursor || null;
        } catch (error) { state.reader.error = error?.message || 'More texts could not be loaded.'; }
        finally { state.reader.loadingMore = false; if (state.route.name === 'reader') renderReaderLibraryState(); }
      },
      onContinueSeries(item) {
        Object.assign(state.generation.form, { storyMode: 'CONTINUE', seriesId: item.seriesId, previousTextId: item.id });
        windowRef.location.hash = formatLanguageRoute({ name: 'generate' });
      },
      async onAnalyze(textId) {
        const result = await api.analyzeText(textId);
        state.reader.jobs.set(textId, result.job);
        renderReaderLibraryState();
        pollReaderJob(result.job.id, textId);
      },
      async onCancel(jobId, textId) {
        const result = await api.cancelJob(jobId);
        state.reader.jobs.set(textId, result.job);
        renderReaderLibraryState();
      },
    });
  }

  function pollReaderJob(jobId, textId) {
    if (!jobId || jobPollTimers.has(jobId)) return;
    const poll = async () => {
      jobPollTimers.delete(jobId);
      try {
        const result = await api.job(jobId);
        state.reader.jobs.set(textId, result.job);
        if (state.route.name === 'reader') renderReaderLibraryState();
        if (TERMINAL_JOB_STATES.has(result.job.state)) {
          if (state.route.name === 'reader') await loadReaderLibrary();
          else if (state.route.name === 'readerText' && state.route.textId === textId) await showReaderDocument(textId);
          return;
        }
      } catch (error) {
        showNotice(error?.message || 'Analysis status could not be refreshed.');
        return;
      }
      jobPollTimers.set(jobId, windowRef.setTimeout(poll, jobPollMs));
    };
    jobPollTimers.set(jobId, windowRef.setTimeout(poll, jobPollMs));
  }

  async function loadReaderLibrary() {
    readerController?.abort();
    readerController = new AbortController();
    state.reader.loading = true;
    state.reader.error = null;
    renderReaderLibraryState();
    try {
      const result = await api.texts(state.profile.id, { limit: 100 }, { signal: readerController.signal });
      state.reader.items = result.items || [];
      state.reader.total = result.pagination?.total ?? state.reader.items.length;
      state.reader.nextCursor = result.pagination?.nextCursor || null;
      try {
        const seriesResult = await api.readingSeries(state.profile.id, { signal: readerController.signal });
        state.reader.series = seriesResult.items || [];
      } catch (error) {
        if (error?.name === 'AbortError') throw error;
        state.reader.series = [];
        state.reader.error = `Story series could not be loaded: ${error?.message || 'Unknown error'}`;
      }
      state.reader.items.forEach((item) => {
        if (item.latestJobId && ['QUEUED', 'RUNNING'].includes(item.latestJobState)) {
          pollReaderJob(item.latestJobId, item.id);
        }
      });
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.reader.error = error?.message || 'Reader library could not be loaded.';
    } finally {
      state.reader.loading = false;
      if (state.route.name === 'reader') renderReaderLibraryState();
    }
  }

  async function refreshReaderLemma(lemmaId, context = null) {
    const sequence = ++lemmaSequence;
    lemmaController?.abort();
    lemmaController = new AbortController();
    renderLemmaDetail(elements.lemmaMount, null, {});
    try {
      const [detail, anki, reference, lexical] = await Promise.all([
        api.lemma(lemmaId, { signal: lemmaController.signal }),
        typeof api.lemmaAnki === 'function'
          ? api.lemmaAnki(lemmaId, { signal: lemmaController.signal })
          : Promise.resolve({ status: { status: 'NOT_CONFIGURED' }, linked: false, cards: [] }),
        typeof api.lemmaReference === 'function'
          ? api.lemmaReference(lemmaId, { signal: lemmaController.signal }).catch((error) => ({
            reference: { available: false, error: error?.message || 'Reference lookup unavailable.' },
            resolution: { status: 'UNAVAILABLE', ruleVersion: 'reference-resolver/v1', candidates: [] },
          }))
          : Promise.resolve({ reference: { available: false }, resolution: { status: 'UNAVAILABLE', candidates: [] } }),
        context?.lexicalDetail
          ? Promise.resolve(context.lexicalDetail)
          : typeof api.lemmaLexical === 'function'
          ? api.lemmaLexical(lemmaId, { signal: lemmaController.signal }).catch((error) => ({
            dictionary: { available: false, lookupStatus: 'PROVIDER_UNAVAILABLE', reason: error?.message || 'Dictionary lookup unavailable.', articles: [] },
            translations: { user: [], learnerGlosses: [], polish: { available: false, status: 'NOT_CONFIGURED' } },
          }))
          : Promise.resolve({ dictionary: { available: false, articles: [] }, translations: { user: [], learnerGlosses: [] } }),
      ]);
      detail.anki = anki;
      detail.reference = reference.reference;
      detail.referenceResolution = reference.resolution;
      detail.lexical = lexical;
      if (sequence !== lemmaSequence || state.route.name !== 'readerText') return;
      state.selectedLemma = detail;
      const rerender = () => {
        renderLemmaDetail(elements.lemmaMount, state.selectedLemma, {
        ...ankiLemmaHandlers(lemmaId, context, rerender),
        ...translationHandlers(lemmaId, rerender),
        onPlayAudio: (callbacks) => playWordAudio('lemma', lemmaId, callbacks),
        async onSave(payload) {
          const currentAnki = state.selectedLemma?.anki;
          const currentReference = state.selectedLemma?.reference;
          const currentResolution = state.selectedLemma?.referenceResolution;
          const currentLexical = state.selectedLemma?.lexical;
          state.selectedLemma = await api.updateLemma(lemmaId, payload);
          state.selectedLemma.anki = currentAnki;
          state.selectedLemma.reference = currentReference;
          state.selectedLemma.referenceResolution = currentResolution;
          state.selectedLemma.lexical = currentLexical;
          rerender();
          await refreshOpenReaderDocument();
        },
        async onLockMapping(formId, targetLemmaId) {
          await api.lockFormMapping(formId, targetLemmaId);
          const currentAnki = state.selectedLemma?.anki;
          const currentReference = state.selectedLemma?.reference;
          const currentResolution = state.selectedLemma?.referenceResolution;
          const currentLexical = state.selectedLemma?.lexical;
          state.selectedLemma = await api.lemma(lemmaId);
          state.selectedLemma.anki = currentAnki;
          state.selectedLemma.reference = currentReference;
          state.selectedLemma.referenceResolution = currentResolution;
          state.selectedLemma.lexical = currentLexical;
          rerender();
          await refreshOpenReaderDocument();
        },
        async onSearchMerge(query) {
          const result = await api.vocabulary(state.profile.id, { q: query, limit: 10 });
          return result.items || [];
        },
        onPrepareMerge(target) {
          pendingMerge = { source: state.selectedLemma.lemma, target, returnRoute: { ...state.route } };
          elements.mergeSummary.textContent = `Merge “${pendingMerge.source.lemmaDisplay}” into “${pendingMerge.target.lemmaDisplay}”. The source ID will become a redirect.`;
          elements.mergeCheck.checked = false;
          elements.mergeConfirm.disabled = true;
          elements.mergeError.hidden = true;
          openDialog(elements.mergeDialog);
        },
        });
        const sentence = currentReaderPayload?.sentences?.find((item) => item.id === context?.sentenceId);
        if (sentence) {
          const contextSection = documentRef.createElement('section');
          contextSection.className = 'language-detail-section language-reader-context';
          const heading = documentRef.createElement('h3');
          heading.textContent = 'Current source sentence';
          const quote = documentRef.createElement('p');
          quote.textContent = sentence.exactText || '';
          contextSection.append(heading, quote);
          elements.lemmaMount.querySelector('.language-detail-layout > div')?.prepend(contextSection);
        }
      };
      rerender();
      openDialog(elements.lemmaDialog);
      enrichLemmaMeanings(detail, rerender,
        () => sequence === lemmaSequence && state.route.name === 'readerText');
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== lemmaSequence) return;
      renderLemmaError(elements.lemmaMount, error?.message || 'The lemma could not be loaded.', { notFound: error?.status === 404 });
    }
  }

  function bindReaderDocument(payload) {
    grammarCleanup?.();
    readerView?.destroy();
    currentReaderPayload = payload;
    sentenceObserver?.destroy();
    readerView = renderReaderDocument(elements.view, payload, {
      onContinueSeries() {
        Object.assign(state.generation.form, { storyMode: 'CONTINUE', seriesId: payload.document.seriesId, previousTextId: payload.document.id });
        windowRef.location.hash = formatLanguageRoute({ name: 'generate' });
      },
      onOpenLemma: refreshReaderLemma,
      onPlayWordAudio: (tokenId, callbacks) => playWordAudio('token', tokenId, callbacks),
      onPreviewLemma: typeof api.lemmaPreview === 'function'
        ? (lemmaId, options) => api.lemmaPreview(lemmaId, options) : null,
      onLookupSurface: typeof api.lexicalPreview === 'function'
        ? (surface, options) => api.lexicalPreview(state.profile.id, surface, options) : null,
      onLookupMeanings: typeof api.lexicalMeanings === 'function'
        ? (surface, options) => api.lexicalMeanings(state.profile.id, surface, options) : null,
      onLexicalDetail: typeof api.lemmaLexical === 'function'
        ? (lemmaId, options) => api.lemmaLexical(lemmaId, options) : null,
      async onUpdateKnowledge(lemmaId, status) {
        const changes = status === 'IGNORED'
          ? { disposition: 'IGNORED' }
          : { knowledgeStatus: status, disposition: 'TRACKED' };
        const result = await api.updateLemma(lemmaId, changes);
        const sequence = ++readerCoverageSequence;
        api.text(payload.document.id).then((fresh) => {
          if (sequence !== readerCoverageSequence || currentReaderPayload?.document.id !== payload.document.id) return;
          currentReaderPayload.coverage = fresh.coverage;
          readerView?.updateCoverage?.(fresh.coverage);
        }).catch(() => {});
        return result;
      },
      onSaveExpression({ expression, sentence }) {
        return savePhrasebook({
          expression,
          sourceType: 'READER',
          sourceEntityId: payload.document.id,
          sourceContext: sentence?.exactText || expression,
          sourceProvenance: {
            textDocumentId: payload.document.id,
            sentenceId: sentence?.id || null,
            sentenceOrder: sentence?.sentenceOrder ?? null,
            contentFingerprint: payload.document.contentFingerprint,
          },
          links: sentence?.id ? [{
            type: 'TOKEN_SPAN', value: `${payload.document.id}:${sentence.id}`,
            metadata: { sentenceOrder: sentence.sentenceOrder },
          }] : [],
        });
      },
      async onAnalyze() {
        const result = await api.analyzeText(payload.document.id);
        state.reader.jobs.set(payload.document.id, result.job);
        pollReaderJob(result.job.id, payload.document.id);
        await showReaderDocument(payload.document.id);
      },
      async onStart() {
        if (currentReaderSession) {
          await sendReaderCommand('RESUME');
          return;
        }
        const result = await api.startReaderSession({
          languageProfileId: state.profile.id,
          textDocumentId: payload.document.id,
          clientSessionId: readerCommandId('reader-session'),
        });
        currentReaderSession = result.session;
        readerTracker = createActiveReadingTracker({
          documentRef,
          windowRef,
          heartbeatMs: readerHeartbeatMs,
          onHeartbeat: () => sendReaderCommand('HEARTBEAT', { quiet: true }),
          onAutoPause: () => sendReaderCommand('PAUSE', { quiet: true }),
          onAutoResume: () => sendReaderCommand('RESUME', { quiet: true }),
        });
        setReaderActivity(true);
      },
      onPause: () => sendReaderCommand('PAUSE'),
      async onComplete() {
        const lastSentence = payload.sentences?.at(-1) || null;
        const sourceLength = [...payload.document.rawText].length;
        const result = await api.updateReadingProgress(payload.document.id, {
          languageProfileId: state.profile.id,
          progressSourceOffset: sourceLength,
          progressSentenceId: lastSentence?.id || null,
          status: 'COMPLETED',
        });
        payload.readingProgress = result.readingProgress;
        if (currentReaderSession) await sendReaderCommand('COMPLETE');
        readerView?.markComplete();
        setReaderActivity(false);
      },
      async onPlayAudio(sentence, callbacks = {}) {
        let result;
        try {
          result = await api.generatedSentenceAudio(payload.document.id, sentence.id);
        } catch (error) {
          callbacks.onError?.(error);
          throw error;
        }
        callbacks.onReady?.(result.audioUrl);
        await generatedAudioPlayer.play(result.audioUrl, callbacks);
        return result;
      },
      onTranslateSentence: (sentence, targetLanguage) => api.translateReaderSentence(
        payload.document.id, sentence.id, targetLanguage,
      ),
      onLoadStudyNotes: typeof api.readerStudyNotes === 'function'
        ? () => api.readerStudyNotes(payload.document.id) : null,
      onImportStudyNotes: typeof api.importReaderStudyNotes === 'function'
        ? (studyNotes) => api.importReaderStudyNotes(payload.document.id, studyNotes) : null,
      onPreviewStoryAnki: () => api.previewReaderStoryAnki(payload.document.id),
      onCreateStoryAnki: (previewToken, translationOverrides, sourceOverrides) => api.createReaderStoryAnki(payload.document.id, previewToken, translationOverrides, sourceOverrides),
      onPauseAudio() { generatedAudioPlayer.pause(); },
      onResumeAudio() { return generatedAudioPlayer.resume(); },
      onStopAudio() { generatedAudioPlayer.stop(); },
    });
    const grammarMount = elements.view.querySelector('[data-reader-grammar]');
    if (grammarMount && api.textGrammar) grammarCleanup = mountReaderGrammar(grammarMount, {
      api, textId: payload.document.id, profileId: state.profile.id, windowRef, pollMs: jobPollMs,
    });
    if (state.route.sentenceId) {
      const sentence = [...elements.view.querySelectorAll('[data-sentence-id]')].find((item) => item.dataset.sentenceId === state.route.sentenceId);
      if (sentence) {
        sentence.classList.add('is-grammar-focus');
        sentence.tabIndex = -1;
        sentence.scrollIntoView?.({ block: 'center' });
        sentence.focus({ preventScroll: true });
      }
    }
    sentenceObserver = createSentenceExposureObserver({
      root: readerView.source,
      windowRef,
      IntersectionObserverClass,
      dwellMs: exposureDwellMs,
      async onExpose(sentenceNode) {
        if (!currentReaderSession || currentReaderSession.activityState !== 'ACTIVE') return;
        const sentenceId = sentenceNode.dataset.sentenceId;
        const occurrences = sentenceOccurrences(payload.tokens, sentenceId);
        const batchKey = `${currentReaderSession.clientSessionId}:${sentenceId}`;
        try {
          await api.recordReaderExposures(currentReaderSession.id, {
            textDocumentId: payload.document.id,
            sentenceId,
            idempotencyKey: batchKey,
            occurrences,
          });
          const progress = await api.updateReadingProgress(payload.document.id, {
            languageProfileId: state.profile.id,
            progressSourceOffset: Number(sentenceNode.dataset.sourceEnd),
            progressSentenceId: sentenceId,
            status: 'IN_PROGRESS',
          });
          payload.readingProgress = progress.readingProgress;
        } catch (error) {
          showNotice(error?.message || 'Reader progress could not be recorded.');
        }
      },
    });
    setReaderActivity(currentReaderSession?.activityState === 'ACTIVE');
  }

  async function refreshOpenReaderDocument() {
    if (state.route.name !== 'readerText') return;
    const payload = await api.text(state.route.textId);
    bindReaderDocument(payload);
  }

  async function showReaderDocument(textId) {
    readerController?.abort();
    readerController = new AbortController();
    state.reader.documentLoading = true;
    state.reader.documentError = null;
    replace(elements.view, messageState('loading', 'Loading Reader text…'));
    try {
      const payload = await api.text(textId, { signal: readerController.signal });
      state.reader.document = payload;
      bindReaderDocument(payload);
      if (payload.latestJob && ['QUEUED', 'RUNNING'].includes(payload.latestJob.state)) {
        pollReaderJob(payload.latestJob.id, textId);
      }
    } catch (error) {
      if (error?.name === 'AbortError') return;
      state.reader.documentError = error;
      replace(elements.view, messageState(
        'error',
        error?.status === 404 || error?.code === 'language_text_not_found' ? 'Reader text was not found.' : 'Reader text could not be loaded.',
        error?.message || 'Check the text ID and backend connection.',
      ));
    } finally {
      state.reader.documentLoading = false;
    }
  }

  async function showReader() {
    disposeReaderActivity({ pause: true });
    await loadReaderLibrary();
  }

  function ankiLemmaHandlers(lemmaId, context, rerender) {
    const sentenceId = context?.sentenceId || null;
    const refresh = async () => {
      if (typeof api.lemmaAnki === 'function') state.selectedLemma.anki = await api.lemmaAnki(lemmaId);
      rerender?.();
    };
    return {
      onAnkiPreview: () => api.previewAnki(lemmaId, sentenceId ? { sentenceId } : {}),
      async onAnkiCommit(preview) {
        const result = await api.commitAnki(lemmaId, {
          confirm: true, previewFingerprint: preview.previewFingerprint, ...(sentenceId ? { sentenceId } : {}),
        });
        await refresh();
        return result;
      },
      async onAnkiLink(externalNoteId, confirm) {
        const result = await api.linkAnki(lemmaId, {
          externalNoteId, confirm, ...(sentenceId ? { sentenceId } : {}),
        });
        if (confirm) await refresh();
        return result;
      },
      async onAnkiResolve(resolution) {
        const result = await api.resolveAnki(lemmaId, {
          resolution, ...(sentenceId ? { sentenceId } : {}),
        });
        await refresh();
        return result;
      },
    };
  }

  async function showSettings() {
    vocabularyView = null;
    vocabularyController?.abort();
    state.anki.loading = true;
    state.anki.error = null;
    state.listening.speech = browserSpeech.initialize();
    const render = () => renderSettings(elements.view, {
      profile: state.profile,
      health: state.health,
      anki: state.anki,
      listening: { speech: state.listening.speech, preferences: listeningPreferences },
      onSaveListening: saveListeningPreferences,
      async onSaveProfile(payload) {
        const result = await api.updateProfile(state.profile.id, payload);
        state.profile = result.profile;
        state.profiles = state.profiles.map((profile) => profile.id === result.profile.id ? result.profile : profile);
        updateProfileSummary();
      },
      async onSaveAnki(payload) {
        const result = await api.updateAnkiConfig(state.profile.id, payload);
        state.anki.config = result.config;
        state.anki.status = await api.ankiStatus(state.profile.id);
        render();
      },
      async onTestAnki() {
        const result = await api.testAnki(state.profile.id);
        state.anki.status = result.status;
        render();
        return result;
      },
      async onDiscoverAnki(modelName) {
        const [decks, models, fields] = await Promise.all([
          api.ankiDecks(state.profile.id), api.ankiModels(state.profile.id),
          modelName ? api.ankiModelFields(state.profile.id, modelName) : Promise.resolve({ items: [] }),
        ]);
        return { decks: decks.items, models: models.items, fields: fields.items };
      },
    });
    settingsRenderer = render;
    render();
    try {
      if (typeof api.ankiConfig === 'function') {
        const [config, status] = await Promise.all([
          api.ankiConfig(state.profile.id), api.ankiStatus(state.profile.id),
        ]);
        state.anki.config = config.config;
        state.anki.status = status;
      }
    } catch (error) {
      state.anki.error = error?.message || 'Anki settings are unavailable.';
    } finally {
      state.anki.loading = false;
      if (state.route.name === 'settings') render();
    }
  }

  async function showReviews() {
    state.anki.loading = true;
    state.anki.error = null;
    state.mistakes.loading = true;
    state.mistakes.error = null;
    const actions = {
      async onPull() {
        const result = await api.pullAnki(state.profile.id);
        await showReviews();
        return result;
      },
      async onSyncWeb() {
        const result = await api.syncAnkiWeb(state.profile.id, { force: true });
        await showReviews();
        return result;
      },
      async onBrowseCards(query, offset) {
        if (typeof api.ankiInsights !== 'function') return;
        try {
          state.anki.insights = await api.ankiInsights(state.profile.id, {
            deck: state.anki.insights?.deckName, q: query, offset, limit: 50,
          });
          state.anki.insightsError = null;
        } catch (error) {
          state.anki.insightsError = error?.message || 'Anki cards could not be loaded.';
        }
        if (state.route.name === 'reviews') renderReviews(elements.view, { ...state.anki, cloze: state.cloze.tracks, mistakes: state.mistakes }, actions);
      },
      async onSelectDeck(deckName) {
        try {
          state.anki.insights = await api.ankiInsights(state.profile.id, { deck: deckName, limit: 50, refresh: true });
          state.anki.insightsError = null;
        } catch (error) {
          state.anki.insightsError = error?.message || 'Deck statistics could not be loaded.';
        }
        if (state.route.name === 'reviews') renderReviews(elements.view, { ...state.anki, cloze: state.cloze.tracks, mistakes: state.mistakes }, actions);
      },
      onRefresh: showReviews,
      onMistakeDetail: (clusterId) => api.mistakeDetail(state.profile.id, clusterId),
    };
    renderReviews(elements.view, { ...state.anki, cloze: state.cloze.tracks, mistakes: state.mistakes }, actions);
    try {
      const [status, runs, cloze, mistakes, insights] = await Promise.all([
        api.ankiStatus(state.profile.id), api.ankiSyncRuns(state.profile.id, { limit: 20 }),
        api.clozeTracks(state.profile.id), api.mistakes(state.profile.id, { limit: 10 }),
        typeof api.ankiInsights === 'function'
          ? api.ankiInsights(state.profile.id, { deck: state.anki.insights?.deckName, limit: 50, refresh: true }).then((data) => ({ data }), (error) => ({ error }))
          : Promise.resolve(null),
      ]);
      state.anki.status = status;
      state.anki.runs = runs.items || [];
      state.cloze.tracks = cloze;
      state.mistakes.summary = mistakes;
      state.anki.insights = insights?.data || null;
      state.anki.insightsError = insights?.error?.message || null;
    } catch (error) {
      state.anki.error = error?.message || 'Review status is unavailable.';
      state.mistakes.error = state.anki.error;
    } finally {
      state.anki.loading = false;
      state.mistakes.loading = false;
      if (state.route.name === 'reviews') renderReviews(elements.view, { ...state.anki, cloze: state.cloze.tracks, mistakes: state.mistakes }, actions);
    }
  }

  const listeningClock = () => windowRef.performance?.now?.() ?? Date.now();

  function saveListeningPreferences(changes = {}) {
    listeningPreferences = {
      ...listeningPreferences,
      ...changes,
      rate: clampSpeechRate(changes.rate ?? listeningPreferences.rate),
      defaultMode: (changes.defaultMode ?? listeningPreferences.defaultMode) === 'LISTENING_ONLY'
        ? 'LISTENING_ONLY' : 'READ_LISTEN',
    };
    try {
      windowRef.localStorage?.setItem(listeningPreferencesKey, JSON.stringify(listeningPreferences));
    } catch (_error) {
      // Device-local settings may be unavailable; playback still works for this page lifetime.
    }
  }

  function listeningCommandId(prefix) {
    const random = windowRef.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `listening:${prefix}:${random}`;
  }

  async function ensureListeningSession(mode) {
    if (listeningSession) return listeningSession;
    if (listeningSessionPromise) return listeningSessionPromise;
    const textId = state.listening.payload?.document?.id;
    listeningSessionPromise = api.startListeningSession(textId, {
      languageProfileId: state.profile.id,
      clientSessionId: listeningCommandId('session'),
      mode,
    }).then((result) => {
      listeningSession = result.session;
      return listeningSession;
    }).finally(() => { listeningSessionPromise = null; });
    return listeningSessionPromise;
  }

  function listeningAccumulate(playback) {
    if (!playback?.activeStartedAt) return;
    playback.activeMs += Math.max(0, Math.round(listeningClock() - playback.activeStartedAt));
    playback.activeStartedAt = null;
    state.listening.activeMs += playback.activeMs - playback.reportedActiveMs;
    playback.reportedActiveMs = playback.activeMs;
    listeningView?.setActiveMs(state.listening.activeMs);
  }

  async function finalizeListeningPlayback(outcome, { audio = null, error = null, evidence = null } = {}) {
    const playback = listeningPlayback;
    if (!playback || playback.finalized) return null;
    playback.finalized = true;
    if (playback.source === 'AUTHENTIC_MEDIA' && evidence) {
      playback.activeMs = Math.max(0, Math.round(evidence.activeMs || 0));
      playback.coverageMs = Math.max(0, Math.round(evidence.coverageMs || 0));
      state.listening.activeMs += playback.activeMs;
      listeningView?.setActiveMs(state.listening.activeMs);
    } else listeningAccumulate(playback);
    listeningPlayback = null;
    state.listening.playbackState = outcome === 'ERROR' ? 'ERROR' : 'IDLE';
    listeningView?.setPlaybackState(
      state.listening.playbackState,
      outcome === 'ENDED' ? 'Sentence finished' : outcome === 'ERROR' ? (error?.message || 'Playback failed') : 'Stopped',
    );
    // A rejected/unsupported playback can fail before the media lifecycle starts.
    // In that case no canonical session or activity event is created.
    if (!playback.sessionPromise) return null;
    let session;
    try {
      session = await playback.sessionPromise;
    } catch (sessionError) {
      showNotice(sessionError?.message || 'Listening session could not be started.');
      return null;
    }
    const mediaDuration = Number(audio?.duration);
    const durationMs = playback.source === 'AUTHENTIC_MEDIA'
      ? Math.max(1, Number(evidence?.durationMs || (playback.sentence.endMs - playback.sentence.startMs)))
      : outcome === 'ENDED'
      ? (Number.isFinite(mediaDuration) && mediaDuration > 0
        ? Math.max(playback.activeMs, Math.round(mediaDuration * 1000))
        : Math.max(1, playback.activeMs))
      : null;
    try {
      const result = await api.recordListeningEvent(session.id, {
        textDocumentId: state.listening.payload.document.id,
        sentenceId: playback.sentence.id,
        idempotencyKey: playback.eventKey,
        outcome,
        playbackSource: playback.source,
        activeMs: Math.min(600000, playback.activeMs),
        coverageMs: Math.min(600000, playback.source === 'AUTHENTIC_MEDIA' ? (playback.coverageMs || 0) : playback.activeMs),
        durationMs: durationMs == null ? null : Math.min(600000, durationMs),
        alignmentId: playback.source === 'AUTHENTIC_MEDIA' ? playback.sentence.alignmentId : undefined,
        metadata: { mode: playback.mode, replay: playback.replay, sentenceOrder: playback.index },
      });
      state.listening.progress = result.progress;
      if (result.progress?.status === 'COMPLETED' && listeningSession?.id === session.id) {
        listeningSession = null;
      }
      listeningView?.setProgress(result.progress);
      if (outcome === 'ENDED' && playback.continuous && playback.index + 1 < state.listening.payload.sentences.length) {
        listeningView?.setCurrent(playback.index + 1);
        state.listening.currentIndex = playback.index + 1;
        await playListeningSentence(playback.index + 1, {
          continuous: true, mode: playback.mode, replay: false,
        });
      }
      return result;
    } catch (eventError) {
      showNotice(eventError?.message || 'Listening evidence could not be recorded.');
      return null;
    }
  }

  async function stopListeningPlayback(outcome = 'CANCELLED') {
    const playback = listeningPlayback;
    if (!playback) return;
    const evidence = playback.source === 'AUTHENTIC_MEDIA' ? authenticMediaPlayer.summary() : null;
    await finalizeListeningPlayback(outcome, { evidence });
    if (playback.source === 'CLOUD_TTS') listeningCloudPlayer.stop();
    else if (playback.source === 'AUTHENTIC_MEDIA') authenticMediaPlayer.stop();
    else browserSpeech.cancel();
  }

  async function playListeningSentence(index, {
    continuous = false, mode = listeningPreferences.defaultMode, replay = false,
  } = {}) {
    await stopListeningPlayback('CANCELLED');
    const sentence = state.listening.payload?.sentences?.[index];
    if (!sentence) return;
    const authentic = Boolean(state.listening.authenticMedia);
    const generated = String(state.listening.payload.document.sourceType || '').startsWith('GENERATED_');
    if (authentic && (sentence.startMs == null || sentence.endMs == null || !sentence.alignmentId)) {
      listeningView?.setPlaybackState('ERROR', 'This sentence has no defensible current alignment.');
      return;
    }
    if (!authentic && !generated && state.listening.speech.state !== 'AVAILABLE') {
      listeningView?.setPlaybackState('ERROR', 'No compatible Bokm\u00e5l browser voice is available.');
      return;
    }
    const token = ++listeningSequence;
    const source = authentic ? 'AUTHENTIC_MEDIA' : generated ? 'CLOUD_TTS' : 'BROWSER_TTS';
    const playback = {
      token, source, sentence, index, continuous, mode, replay,
      eventKey: listeningCommandId(`sentence-${sentence.id}`),
      activeMs: 0, reportedActiveMs: 0, activeStartedAt: null,
      sessionPromise: null, finalized: false,
    };
    listeningPlayback = playback;
    state.listening.currentIndex = index;
    state.listening.playbackState = 'LOADING';
    listeningView?.setCurrent(index);
    listeningView?.setPlaybackState('LOADING', `Preparing sentence ${index + 1}\u2026`);
    const started = () => {
      if (listeningPlayback !== playback || playback.finalized) return;
      if (playback.source !== 'AUTHENTIC_MEDIA') playback.activeStartedAt = listeningClock();
      playback.sessionPromise = ensureListeningSession(mode);
      state.listening.playbackState = 'PLAYING';
      listeningView?.setPlaybackState('PLAYING', `Playing sentence ${index + 1} of ${state.listening.payload.sentences.length}`);
    };
    try {
      if (authentic) {
        await authenticMediaPlayer.playSegment({
          url: state.listening.authenticMedia.url,
          startMs: sentence.startMs,
          endMs: sentence.endMs,
          rate: listeningPreferences.rate,
          onStart: started,
          onProgress: (evidence) => listeningView?.setTimeline(evidence.currentMs),
          onEnded: (evidence) => finalizeListeningPlayback('ENDED', { evidence }),
          onError: (evidence) => finalizeListeningPlayback('ERROR', { evidence, error: new Error('Authentic media playback failed') }),
        });
      } else if (generated) {
        const result = await api.generatedSentenceAudio(state.listening.payload.document.id, sentence.id);
        if (token !== listeningSequence || playback.finalized) return;
        await listeningCloudPlayer.play(result.audioUrl, {
          onPlaying: started,
          onEnded: (audio) => finalizeListeningPlayback('ENDED', { audio }),
          onError: (error, audio) => finalizeListeningPlayback('ERROR', { audio, error }),
          onCancel: (audio) => finalizeListeningPlayback('CANCELLED', { audio }),
        });
      } else {
        browserSpeech.speak(sentence.exactText, {
          preferredVoiceId: listeningPreferences.preferredVoiceId,
          rate: listeningPreferences.rate,
          onStart: started,
          onEnd: () => finalizeListeningPlayback('ENDED'),
          onError: (error) => finalizeListeningPlayback('ERROR', { error }),
          onCancel: () => finalizeListeningPlayback('CANCELLED'),
        });
      }
    } catch (error) {
      await finalizeListeningPlayback('ERROR', { error });
    }
  }

  function pauseListening() {
    const playback = listeningPlayback;
    if (!playback || state.listening.playbackState !== 'PLAYING') return;
    listeningAccumulate(playback);
    if (playback.source === 'CLOUD_TTS') listeningCloudPlayer.pause();
    else if (playback.source === 'AUTHENTIC_MEDIA') authenticMediaPlayer.pause();
    else browserSpeech.pause();
    state.listening.playbackState = 'PAUSED';
    listeningView?.setPlaybackState('PAUSED', 'Paused');
  }

  async function resumeListening() {
    const playback = listeningPlayback;
    if (!playback || state.listening.playbackState !== 'PAUSED') return;
    if (playback.source === 'CLOUD_TTS') await listeningCloudPlayer.resume();
    else if (playback.source === 'AUTHENTIC_MEDIA') await authenticMediaPlayer.resume();
    else browserSpeech.resume();
    if (playback.source !== 'AUTHENTIC_MEDIA') playback.activeStartedAt = listeningClock();
    state.listening.playbackState = 'PLAYING';
    listeningView?.setPlaybackState('PLAYING', `Playing sentence ${playback.index + 1}`);
  }

  function renderOpenListeningText() {
    if (!state.listening.payload) return;
    listeningView?.destroy?.();
    listeningView = renderListeningText(elements.view, {
      ...state.listening, preferences: listeningPreferences,
      cloudAudio: state.health?.generatedReaderAudio || { state: 'UNAVAILABLE' },
    }, {
      onPlay: playListeningSentence,
      onPause: pauseListening,
      onResume: resumeListening,
      onStop: () => stopListeningPlayback('CANCELLED'),
      async onSelect(index) {
        await stopListeningPlayback('CANCELLED');
        state.listening.currentIndex = index;
        listeningView?.setCurrent(index);
      },
      onSeek: (ms) => authenticMediaPlayer.seek(ms),
      async onSaveExpression(sentence) {
        if (!state.listening.authenticMedia || !sentence) return;
        try {
          await api.createPhrasebookEntry(state.profile.id, {
            expression: sentence.exactText,
            sourceType: 'AUTHENTIC_MEDIA',
            sourceEntityId: state.listening.contentDetail?.item?.id,
            sourceContext: sentence.exactText,
            sourceProvenance: {
              contentId: state.listening.contentDetail?.item?.id,
              sourceUri: state.listening.contentDetail?.item?.sourceUri || null,
              sourceName: state.listening.contentDetail?.item?.sourceName || null,
              transcriptId: state.listening.contentDetail?.currentTranscript?.id,
              transcriptVersion: state.listening.contentDetail?.currentTranscript?.version,
              alignmentId: sentence.alignmentId,
              startMs: sentence.startMs,
              endMs: sentence.endMs,
            },
            links: [],
          });
          showNotice('Sentence saved to Phrasebook without mastery or extra exposure.');
        } catch (error) { showNotice(error?.message || 'Expression could not be saved.'); }
      },
      onPreference: saveListeningPreferences,
      onLookupSurface: typeof api.lexicalPreview === 'function'
        ? (surface, options) => api.lexicalPreview(state.profile.id, surface, options) : null,
      onLookupMeanings: typeof api.lexicalMeanings === 'function'
        ? (surface, options) => api.lexicalMeanings(state.profile.id, surface, options) : null,
    });
  }

  async function addInboxContent(input) {
    state.inbox.busy = true;
    state.inbox.error = null;
    try {
      const title = input.title || input.audioFile?.name || input.transcriptFile?.name || 'Untitled content';
      let result;
      if (input.sourceType === 'PASTED_TEXT') {
        result = await api.createContent(state.profile.id, { sourceType: 'PASTED_TEXT', title, text: input.text });
      } else if (input.sourceType.endsWith('_REFERENCE')) {
        result = await api.createContent(state.profile.id, { sourceType: input.sourceType, title, sourceUri: input.sourceUri });
      } else if (input.sourceType === 'LOCAL_TRANSCRIPT') {
        const transcriptText = input.transcriptFile ? await input.transcriptFile.text() : input.text;
        result = await api.createContent(state.profile.id, {
          sourceType: input.format === 'SRT' || input.format === 'VTT' ? input.format : 'LOCAL_TRANSCRIPT',
          title, transcriptText, format: input.format,
        });
      } else {
        if (!input.audioFile) throw new Error('Choose a supported local audio file.');
        result = await api.uploadContentAudio(state.profile.id, input.audioFile, { title });
        if (input.sourceType === 'LOCAL_AUDIO_PLUS_TRANSCRIPT') {
          const transcriptText = input.transcriptFile ? await input.transcriptFile.text() : input.text;
          if (!transcriptText?.trim()) throw new Error('Audio + transcript requires transcript text or a file.');
          result = await api.addContentTranscript(result.item.id, { format: input.format, transcriptText });
        }
      }
      windowRef.location.hash = formatLanguageRoute({ name: 'inboxContent', contentId: result.item.id });
      return result;
    } catch (error) {
      state.inbox.error = error?.message || 'Content could not be added.';
      if (state.route.name === 'inbox') renderInboxLanding(elements.view, state.inbox, { onAdd: addInboxContent, onOpen: openInboxContent });
      return null;
    } finally { state.inbox.busy = false; }
  }

  function openInboxContent(contentId) {
    windowRef.location.hash = formatLanguageRoute({ name: 'inboxContent', contentId });
  }

  async function showInbox() {
    state.inbox.loading = true;
    state.inbox.error = null;
    renderInboxLanding(elements.view, state.inbox, { onAdd: addInboxContent, onOpen: openInboxContent });
    try {
      const result = await api.contentItems(state.profile.id);
      state.inbox.items = result.items || [];
      state.inbox.total = result.total || 0;
    } catch (error) { state.inbox.error = error?.message || 'Content Inbox could not be loaded.'; }
    finally {
      state.inbox.loading = false;
      if (state.route.name === 'inbox') renderInboxLanding(elements.view, state.inbox, { onAdd: addInboxContent, onOpen: openInboxContent });
    }
  }

  async function showInboxContent(contentId) {
    replace(elements.view, messageState('loading', 'Loading content detail…'));
    try {
      state.inbox.detail = await api.contentItem(contentId);
      const render = () => renderInboxDetail(elements.view, state.inbox, {
        onRefresh: () => showInboxContent(contentId),
        async onTranscript(payload) {
          state.inbox.detail = await api.addContentTranscript(contentId, payload);
          render();
        },
        async onAlignment(alignmentId, payload) {
          state.inbox.detail = await api.correctContentAlignment(alignmentId, payload);
          render();
        },
      });
      render();
    } catch (error) {
      replace(elements.view, messageState('error', 'Content detail could not be loaded.', error?.message));
    }
  }

  async function showListening() {
    state.listening.loading = true;
    state.listening.error = null;
    renderListeningLanding(elements.view, state.listening, {
      onOpen: (textId) => { windowRef.location.hash = formatLanguageRoute({ name: 'listeningText', textId }); },
    });
    try {
      const result = await api.listening(state.profile.id);
      state.listening.items = result.items || [];
      state.listening.total = result.total || 0;
    } catch (error) {
      state.listening.error = error?.message || 'Listening material could not be loaded.';
    } finally {
      state.listening.loading = false;
      if (state.route.name === 'listening') renderListeningLanding(elements.view, state.listening, {
        onOpen: (textId) => { windowRef.location.hash = formatLanguageRoute({ name: 'listeningText', textId }); },
      });
    }
  }

  async function showListeningText(textId) {
    replace(elements.view, messageState('loading', 'Loading Listening text\u2026'));
    try {
      const [payload, progressResult] = await Promise.all([
        api.text(textId), api.listeningProgress(textId, state.profile.id),
      ]);
      state.listening.payload = payload;
      state.listening.authenticMedia = null;
      state.listening.contentDetail = null;
      state.listening.progress = progressResult.progress;
      state.listening.currentIndex = Math.max(0, Number(progressResult.progress?.currentSentenceOrder ?? 0));
      state.listening.activeMs = 0;
      state.listening.playbackState = 'IDLE';
      state.listening.statusText = 'Ready';
      state.listening.speech = browserSpeech.initialize();
      renderOpenListeningText();
    } catch (error) {
      replace(elements.view, messageState('error', 'Listening text could not be loaded.', error?.message));
    }
  }

  async function showAuthenticListening(contentId) {
    replace(elements.view, messageState('loading', 'Loading authentic Listening…'));
    try {
      const content = await api.contentItem(contentId);
      if (!content.media?.url || !content.document?.id || content.item?.status !== 'READY_LISTENING') {
        throw new Error('This content is not ready for authentic Listening.');
      }
      const [payload, progressResult] = await Promise.all([
        api.text(content.document.id), api.listeningProgress(content.document.id, state.profile.id),
      ]);
      const bySentence = new Map((content.alignments || []).map((item) => [item.sentenceId, item]));
      payload.sentences = (payload.sentences || []).map((sentence) => {
        const alignment = bySentence.get(sentence.id);
        return alignment ? {
          ...sentence, alignmentId: alignment.id, startMs: alignment.startMs, endMs: alignment.endMs,
          alignmentMethod: alignment.method, exposureEligible: alignment.exposureEligible,
        } : sentence;
      });
      state.listening.payload = payload;
      state.listening.progress = progressResult.progress;
      state.listening.authenticMedia = { ...content.media, sourceName: content.item?.sourceName };
      state.listening.contentDetail = content;
      state.listening.alignmentStatus = content.currentTranscript?.method || 'SOURCE TIMESTAMPS';
      state.listening.currentIndex = Math.max(0, Number(progressResult.progress?.currentSentenceOrder ?? 0));
      state.listening.activeMs = 0;
      state.listening.playbackState = 'IDLE';
      state.listening.statusText = 'Ready';
      renderOpenListeningText();
    } catch (error) {
      replace(elements.view, messageState('error', 'Authentic Listening could not be loaded.', error?.message));
    }
  }

  async function disposeListening() {
    await stopListeningPlayback('CANCELLED');
    playbackCoordinator.stop();
    if (listeningSession) {
      const closing = listeningSession;
      listeningSession = null;
      try {
        await api.closeListeningSession(closing.id, { commandId: listeningCommandId('close') });
      } catch (_error) {
        // Sentence events are already durable; a failed close can be retried by later cleanup.
      }
    }
    listeningView?.destroy?.();
    listeningView = null;
    state.listening.payload = null;
    state.listening.authenticMedia = null;
    state.listening.contentDetail = null;
  }

  function clozeCommandId(itemIndex) {
    const random = windowRef.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `cloze:${state.cloze.session?.id || 'session'}:${itemIndex}:${random}`;
  }

  function renderCurrentCloze() {
    clozeCleanup?.();
    clozeCleanup = renderCloze(elements.view, state.cloze, clozeActions());
  }

  function resetClozeAudio() {
    clozeAudioPlayer.stop();
    state.cloze.audio = { status: 'IDLE', itemKey: '', error: null };
  }

  async function playClozeAudio(item) {
    const sessionId = state.cloze.session?.id;
    if (!sessionId || !item || !clozeAudioPlayer.available()) {
      state.cloze.audio = {
        status: 'ERROR', itemKey: '', error: 'Audio playback is unavailable in this browser.',
      };
      renderCurrentCloze();
      return;
    }
    const itemKey = `${sessionId}:${item.index}:${item.fingerprint}`;
    if (state.cloze.audio.status === 'LOADING' && state.cloze.audio.itemKey === itemKey) return;
    clozeAudioPlayer.stop();
    state.cloze.audio = { status: 'LOADING', itemKey, error: null };
    renderCurrentCloze();
    const update = (status, error = null) => {
      if (state.cloze.audio.itemKey !== itemKey) return;
      state.cloze.audio = { status, itemKey, error };
      if (state.route.name === 'cloze') renderCurrentCloze();
    };
    try {
      const result = await api.clozeAudio(sessionId, item.index, {
        itemFingerprint: item.fingerprint,
      });
      if (state.cloze.audio.itemKey !== itemKey) return;
      await clozeAudioPlayer.play(result.audioUrl, {
        onPlaying: () => update('PLAYING'),
        onEnded: () => update('IDLE'),
        onError: (error) => update('ERROR', error?.message || 'Sentence audio could not be played.'),
      });
    } catch (error) {
      update('ERROR', error?.message || 'Sentence audio could not be generated.');
    }
  }

  async function submitCloze(action, optionIndex = undefined, answer = undefined) {
    if (state.cloze.busy || !state.cloze.session?.currentItem) return;
    const item = state.cloze.session.currentItem;
    state.cloze.busy = true;
    state.cloze.error = null;
    state.cloze.lastItem = item;
    renderCurrentCloze();
    try {
      const payload = {
        itemIndex: item.index,
        itemFingerprint: item.fingerprint,
        action,
        responseMs: Math.max(0, Math.min(600000, Date.now() - (state.cloze.questionStartedAt || Date.now()))),
        idempotencyKey: clozeCommandId(item.index),
      };
      if (optionIndex !== undefined) payload.optionIndex = optionIndex;
      if (answer !== undefined) payload.answer = answer;
      const result = await api.submitClozeAttempt(state.cloze.session.id, payload);
      state.cloze.session = result.session;
      state.cloze.attempts = result.attempts || [];
      state.cloze.feedback = result.feedback;
      if (action === 'ANSWER' && result.feedback && state.route.name === 'cloze') {
        void playClozeAudio(item);
      }
    } catch (error) {
      state.cloze.error = error?.message || 'The Cloze answer could not be recorded.';
    } finally {
      state.cloze.busy = false;
      if (state.route.name === 'cloze') renderCurrentCloze();
    }
  }

  function clozeActions() {
    return {
      async onStart(payload) {
        resetClozeAudio();
        state.cloze.busy = true; state.cloze.error = null; state.cloze.notice = '';
        renderCurrentCloze();
        try {
          const result = await api.startClozeSession(state.profile.id, payload);
          state.cloze.session = result.session; state.cloze.attempts = result.attempts || [];
          state.cloze.feedback = null; state.cloze.lastItem = null; state.cloze.questionStartedAt = Date.now();
          if (result.session.actualItemCount < result.session.requestedItemCount) {
            state.cloze.notice = `${result.session.actualItemCount} playable items were available for this selection.`;
          }
        } catch (error) { state.cloze.error = error?.message || 'The Cloze session could not start.'; }
        finally { state.cloze.busy = false; if (state.route.name === 'cloze') renderCurrentCloze(); }
      },
      async onResume(sessionId) {
        resetClozeAudio();
        state.cloze.busy = true; state.cloze.error = null; renderCurrentCloze();
        try {
          const result = await api.clozeSession(sessionId);
          state.cloze.session = result.session; state.cloze.attempts = result.attempts || [];
          state.cloze.feedback = null; state.cloze.lastItem = null; state.cloze.questionStartedAt = Date.now();
        } catch (error) { state.cloze.error = error?.message || 'The Cloze session could not be restored.'; }
        finally { state.cloze.busy = false; if (state.route.name === 'cloze') renderCurrentCloze(); }
      },
      onAnswer: (index) => submitCloze('ANSWER', index),
      onTypedAnswer: (answer) => submitCloze('ANSWER', undefined, answer),
      onReveal: () => submitCloze('REVEAL'),
      onSkip: () => submitCloze('SKIP'),
      onNext() {
        resetClozeAudio();
        state.cloze.feedback = null; state.cloze.lastItem = null; state.cloze.questionStartedAt = Date.now();
        renderCurrentCloze();
      },
      onPlayAudio: playClozeAudio,
      onLookupSurface: typeof api.lexicalPreview === 'function'
        ? (surface, options) => api.lexicalPreview(state.profile.id, surface, options) : null,
      onLookupMeanings: typeof api.lexicalMeanings === 'function'
        ? (surface, options) => api.lexicalMeanings(state.profile.id, surface, options) : null,
      onLexicalDetail: typeof api.lemmaLexical === 'function'
        ? (lemmaId, options) => api.lemmaLexical(lemmaId, options) : null,
      onSaveExpression(item) {
        const source = item.source || {};
        return savePhrasebook({
          expression: item.sentenceText,
          sourceType: 'CLOZE',
          sourceEntityId: `${source.sourceId || 'TATOEBA'}:${source.sentenceId || item.index}`,
          sourceContext: item.sentenceText,
          sourceProvenance: {
            clozeSessionId: state.cloze.session?.id,
            itemIndex: item.index,
            itemFingerprint: item.fingerprint,
            source,
          },
          links: item.targetLemmaId ? [{ type: 'LEMMA', value: item.targetLemmaId, metadata: {} }] : [],
        });
      },
      onPreferences(next) {
        state.cloze.preferences = { ...state.cloze.preferences, ...next };
        try { windowRef.localStorage?.setItem(clozePreferencesKey, JSON.stringify(state.cloze.preferences)); } catch (_error) { /* noop */ }
        renderCurrentCloze();
      },
      async onReport(reason) {
        const item = state.cloze.lastItem || state.cloze.session?.currentItem;
        if (!item || state.cloze.busy) return;
        const unanswered = !state.cloze.feedback;
        state.cloze.busy = true; renderCurrentCloze();
        try {
          await api.reportClozeItem(state.cloze.session.id, { itemIndex: item.index, reason });
          state.cloze.notice = 'Question suppressed from future sessions.';
        } catch (error) {
          state.cloze.error = error?.message || 'The question could not be reported.';
        } finally {
          state.cloze.busy = false;
        }
        if (unanswered && !state.cloze.error) await submitCloze('SKIP');
        else if (state.route.name === 'cloze') renderCurrentCloze();
      },
      async onBack() {
        resetClozeAudio();
        state.cloze.session = null; state.cloze.feedback = null; state.cloze.lastItem = null;
        await showCloze({ resumeActive: false });
      },
    };
  }

  async function showCloze({ resumeActive = true } = {}) {
    state.cloze.loading = true; state.cloze.error = null;
    renderCurrentCloze();
    try {
      state.cloze.tracks = await api.clozeTracks(state.profile.id);
      if (resumeActive && !state.cloze.session && state.cloze.tracks.activeSessionId) {
        const result = await api.clozeSession(state.cloze.tracks.activeSessionId);
        state.cloze.session = result.session; state.cloze.attempts = result.attempts || [];
        state.cloze.questionStartedAt = Date.now();
      }
    } catch (error) { state.cloze.error = error?.message || 'Cloze could not be loaded.'; }
    finally { state.cloze.loading = false; if (state.route.name === 'cloze') renderCurrentCloze(); }
  }

  async function copyGenerationText(value) {
    try {
      if (!windowRef.navigator?.clipboard?.writeText) throw new Error('Clipboard permission is unavailable.');
      await windowRef.navigator.clipboard.writeText(String(value));
      state.generation.notice = 'Copied to clipboard.';
    } catch (error) {
      state.generation.error = error?.message || 'Could not copy to the clipboard.';
    }
    renderGenerate(elements.view, state.generation, generationActions());
  }

  function exportGenerationPack(pack) {
    const blob = new windowRef.Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' });
    const url = windowRef.URL.createObjectURL(blob);
    const link = documentRef.createElement('a');
    link.href = url; link.download = `language-context-${state.generation.request.id}.json`; link.click();
    windowRef.URL.revokeObjectURL(url);
  }

  async function refreshGenerationCandidates({ poll = false } = {}) {
    if (!state.generation.request) return;
    const [requestResult, candidateResult] = await Promise.all([
      api.generationRequest(state.generation.request.id),
      api.generationCandidates(state.generation.request.id),
    ]);
    state.generation.request = requestResult.request;
    state.generation.candidates = candidateResult.items || [];
    if (state.route.name === 'generate') renderGenerate(elements.view, state.generation, generationActions());
    windowRef.clearTimeout(generationPollTimer);
    if (poll && (
      ['QUEUED', 'RUNNING'].includes(state.generation.request.automaticStatus)
      || state.generation.candidates.some((item) => ['QUEUED', 'ANALYZING'].includes(item.status))
    )) {
      generationPollTimer = windowRef.setTimeout(() => refreshGenerationCandidates({ poll: true }).catch(() => {}), jobPollMs);
    }
  }

  function generationActions() {
    return {
      async onCreate(payload) {
        state.generation.busy = true; state.generation.error = null; state.generation.notice = '';
        Object.assign(state.generation.form, payload);
        renderGenerate(elements.view, state.generation, generationActions());
        try {
          const requestPayload = { ...payload };
          if (requestPayload.newSeries) {
            const created = await api.createReadingSeries(state.profile.id, requestPayload.newSeries);
            requestPayload.seriesId = created.series.id;
            delete requestPayload.newSeries;
            state.generation.series = [...state.generation.series, created.series];
            if (requestPayload.storyMode === 'CONTINUE' && requestPayload.previousTextId) {
              await api.assignTextSeries(requestPayload.previousTextId, created.series.id);
              const previous = state.generation.texts.find((item) => item.id === requestPayload.previousTextId);
              if (previous) Object.assign(previous, { seriesId: created.series.id, episodeNumber: 1 });
              created.series.episodeCount = 1;
              created.series.episodes = [{ textDocumentId: requestPayload.previousTextId, episodeNumber: 1, title: previous?.title || 'Previous episode' }];
            }
            Object.assign(state.generation.form, { storyMode: requestPayload.storyMode, seriesId: created.series.id });
            delete state.generation.form.newSeries;
          }
          const result = await api.createGenerationRequest(state.profile.id, requestPayload);
          Object.assign(state.generation.form, requestPayload);
          state.generation.request = result.request; state.generation.contextPack = result.contextPack; state.generation.candidates = [];
          windowRef.localStorage?.setItem(generationRequestKey, result.request.id);
          if (payload.generationMode === 'AUTOMATIC') {
            await api.startAutomaticGeneration(result.request.id);
            state.generation.notice = 'Automatic Gemini generation started. Local analysis and up to three bounded attempts will run before review.';
            await refreshGenerationCandidates({ poll: true });
          } else {
            state.generation.notice = result.contextPack?.formatVersion === 'language-generation-context/v2'
              ? 'Reference-aware v2 context pack created from frozen user and reference snapshots.'
              : 'Context pack created from a frozen vocabulary snapshot.';
          }
        } catch (error) { state.generation.error = error?.message || 'Context pack could not be created.'; }
        finally { state.generation.busy = false; renderGenerate(elements.view, state.generation, generationActions()); }
      },
      onCopy: copyGenerationText,
      onExport: exportGenerationPack,
      async onStartAutomatic() {
        state.generation.error = null;
        try {
          await api.startAutomaticGeneration(state.generation.request.id);
          state.generation.notice = 'Automatic generation queued.';
          await refreshGenerationCandidates({ poll: true });
        } catch (error) {
          state.generation.error = error?.message || 'Automatic generation could not start.';
          renderGenerate(elements.view, state.generation, generationActions());
        }
      },
      async onCancelAutomatic() {
        try {
          await api.cancelAutomaticGeneration(state.generation.request.id);
          state.generation.notice = 'Cancellation requested.';
          await refreshGenerationCandidates({ poll: true });
        } catch (error) {
          state.generation.error = error?.message || 'Automatic generation could not be cancelled.';
          renderGenerate(elements.view, state.generation, generationActions());
        }
      },
      async onImport(payload) {
        state.generation.error = null;
        try { await api.importGenerationCandidate(state.generation.request.id, payload); await refreshGenerationCandidates(); state.generation.notice = 'Candidate imported. No study evidence was recorded.'; }
        catch (error) { state.generation.error = error?.message || 'Candidate could not be imported.'; }
        renderGenerate(elements.view, state.generation, generationActions());
      },
      async onAnalyze(candidateId) {
        try { await api.analyzeGenerationCandidate(candidateId); await refreshGenerationCandidates({ poll: true }); }
        catch (error) { state.generation.error = error?.message || 'Candidate analysis could not start.'; renderGenerate(elements.view, state.generation, generationActions()); }
      },
      async onRevision(candidateId) {
        try { const result = await api.generationRevisionPrompt(candidateId); await copyGenerationText(result.prompt); }
        catch (error) { state.generation.error = error?.message || 'Revision prompt is unavailable.'; renderGenerate(elements.view, state.generation, generationActions()); }
      },
      async onAccept(candidateId) {
        try { const result = await api.acceptGenerationCandidate(candidateId); await refreshGenerationCandidates({ poll: true }); state.generation.notice = result.warning || 'Accepted and saved to Reader.'; }
        catch (error) { state.generation.error = error?.message || 'Candidate could not be accepted.'; }
        renderGenerate(elements.view, state.generation, generationActions());
      },
      async onReject(candidateId) {
        try { await api.rejectGenerationCandidate(candidateId, {}); await refreshGenerationCandidates(); state.generation.notice = 'Candidate rejected; its history is retained.'; }
        catch (error) { state.generation.error = error?.message || 'Candidate could not be rejected.'; }
        renderGenerate(elements.view, state.generation, generationActions());
      },
      onSaveExpression(candidate, expression) {
        const text = String(candidate.extractedText || '');
        const index = text.indexOf(expression);
        if (index < 0) throw new Error('The expression must be copied exactly from this generated text.');
        const start = Math.max(0, index - 2000);
        const context = text.slice(start, Math.min(text.length, index + expression.length + 2000));
        return savePhrasebook({
          expression,
          sourceType: 'GENERATED',
          sourceEntityId: candidate.acceptedTextDocumentId || null,
          sourceContext: context,
          sourceProvenance: {
            generationCandidateId: candidate.id,
            generationRequestId: candidate.generationRequestId,
            attemptNumber: candidate.attemptNumber,
            contentFingerprint: candidate.contentFingerprint,
          },
          links: candidate.acceptedTextDocumentId
            ? [{ type: 'TOKEN_SPAN', value: candidate.acceptedTextDocumentId, metadata: { generationCandidateId: candidate.id } }]
            : [],
        });
      },
    };
  }

  async function showGenerate() {
    state.generation.error = null;
    renderGenerate(elements.view, state.generation, generationActions());
    try {
      const [topicsResult, providerHealth, seriesResult, textsResult] = await Promise.all([
        api.topics(state.profile.id, { includeArchived: false }),
        api.generationProviderHealth(),
        api.readingSeries(state.profile.id),
        api.texts(state.profile.id, { limit: 100 }),
      ]);
      state.generation.providerHealth = providerHealth;
      state.generation.series = seriesResult.items || [];
      state.generation.texts = textsResult.items || [];
      const savedRequestId = !state.generation.request ? windowRef.localStorage?.getItem(generationRequestKey) : null;
      if (savedRequestId) {
        try {
          const [saved, context, candidates] = await Promise.all([
            api.generationRequest(savedRequestId), api.generationContext(savedRequestId), api.generationCandidates(savedRequestId),
          ]);
          if (saved.request.languageProfileId === state.profile.id) {
            state.generation.request = saved.request; state.generation.contextPack = context.contextPack; state.generation.candidates = candidates.items || [];
          }
        } catch {
          windowRef.localStorage?.removeItem(generationRequestKey);
        }
      }
      state.generation.topics = topicsResult.items || [];
      if (['QUEUED', 'RUNNING'].includes(state.generation.request?.automaticStatus)) {
        refreshGenerationCandidates({ poll: true }).catch(() => {});
      }
    } catch (error) { state.generation.error = error?.message || 'Topics could not be loaded.'; }
    if (state.route.name === 'generate') renderGenerate(elements.view, state.generation, generationActions());
  }

  let grammarCleanup = null;
  async function showGrammar(route) {
    const sequence = routeSequence;
    replace(elements.view, messageState('loading', 'Loading Grammar…'));
    try {
      const data = route.patternId ? await api.grammarPattern(state.profile.id, route.patternId) : await api.grammar(state.profile.id);
      if (sequence !== routeSequence) return;
      renderGrammar(elements.view, data, { async onReview(id, decision) {
        await api.reviewGrammar(id, state.profile.id, decision);
        if (sequence === routeSequence) await showGrammar(route);
      } });
    } catch (error) {
      if (sequence === routeSequence) replace(elements.view, messageState('error', 'Grammar could not be loaded.', error.message));
    }
  }

  async function showBenchmarks() {
    const sequence = benchmarkSequence;
    replace(elements.view, messageState('loading', 'Loading benchmarks…'));
    try {
      const [history, preparation] = await Promise.all([
        api.benchmarks(state.profile.id), api.norwayPreparation(state.profile.id),
      ]);
      if (sequence !== benchmarkSequence) return;
      renderBenchmarkLanding(elements.view, history, preparation, {
        start: async () => {
          try {
            const run = await api.startBenchmark(state.profile.id);
            windowRef.location.hash = formatLanguageRoute({ name: 'benchmarkRun', runId: run.id });
          } catch (error) { showNotice(error.message, 'error'); }
        },
        open: (runId) => { windowRef.location.hash = formatLanguageRoute({ name: 'benchmarkRun', runId }); },
      });
    } catch (error) {
      if (sequence === benchmarkSequence) replace(elements.view, messageState('error', 'Benchmarks could not be loaded.', error.message));
    }
  }

  function showStudySession() {
    const build = async (minutes) => {
      const sequence = ++sessionSequence;
      sessionState.minutes = minutes;
      sessionState.plan = null;
      sessionState.error = null;
      sessionState.loading = true;
      render();
      try {
        const plan = await api.studySession(state.profile.id, minutes);
        if (sequence !== sessionSequence || state.route.name !== 'study-session') return;
        sessionState.plan = plan;
      } catch (error) {
        if (sequence !== sessionSequence || state.route.name !== 'study-session') return;
        sessionState.error = error?.message || 'The plan is unavailable.';
      } finally {
        if (sequence === sessionSequence && state.route.name === 'study-session') {
          sessionState.loading = false;
          render();
        }
      }
    };
    const render = () => {
      if (state.route.name !== 'study-session') return;
      renderStudySession(elements.view, sessionState, { onBuild: build });
    };
    render();
    if (!sessionState.plan && !sessionState.loading) build(sessionState.minutes);
  }

  async function showBenchmarkRun(runId) {
    const sequence = benchmarkSequence;
    replace(elements.view, messageState('loading', 'Loading benchmark run…'));
    try {
      const run = await api.benchmarkRun(state.profile.id, runId);
      if (sequence !== benchmarkSequence) return;
      const speech = {
        snapshot: () => browserSpeech.initialize(),
        retry: () => browserSpeech.refreshVoices(),
        play: (value) => browserSpeech.speak(value, { rate: 1 }),
      };
      const refresh = async () => {
        if (sequence === benchmarkSequence) await showBenchmarkRun(runId);
      };
      renderBenchmarkRun(elements.view, run, {
        speech,
        back: () => { windowRef.location.hash = '#benchmarks'; },
        answer: async (itemId, payload) => {
          const item = run.items.find((candidate) => candidate.id === itemId);
          if (item?.dimension === 'LISTENING') {
            const snapshot = browserSpeech.snapshot();
            payload.environment = {
              browserCapability: snapshot.state, voiceId: snapshot.selectedVoiceId,
              locale: 'nb-NO', speechRate: 1,
            };
            browserSpeech.cancel();
          }
          try {
            await api.respondBenchmark(state.profile.id, runId, { itemId, ...payload });
            await refresh();
          } catch (error) { showNotice(error.message, 'error'); }
        },
        complete: async () => {
          try { await api.completeBenchmark(state.profile.id, runId); await refresh(); }
          catch (error) { showNotice(error.message, 'error'); }
        },
      });
    } catch (error) {
      if (sequence === benchmarkSequence) replace(elements.view, messageState('error', 'Benchmark run could not be loaded.', error.message));
    }
  }

  async function renderRoute(route) {
    const sequence = ++routeSequence;
    benchmarkSequence += 1;
    sessionSequence += 1;
    const previousRoute = state.route;
    if (previousRoute.name === 'overview' && route.name !== 'overview') overviewPlanController?.abort();
    if (routeSection(previousRoute) === 'vocabulary' && routeSection(route) !== 'vocabulary') {
      vocabularyView?.destroy?.(); vocabularyView = null;
    }
    if (previousRoute.name === 'study-session' && route.name !== 'study-session') sessionState.loading = false;
    if (previousRoute.name === 'benchmarkRun' && route.name !== 'benchmarkRun') browserSpeech.cancel();
    grammarCleanup?.(); grammarCleanup = null;
    if (route.name !== 'settings') settingsRenderer = null;
    if (previousRoute.name === 'readerText' && route.name !== 'readerText') {
      disposeReaderActivity({ pause: true });
    }
    if (previousRoute.name === 'cloze' && route.name !== 'cloze') {
      clozeCleanup?.(); clozeCleanup = null;
      resetClozeAudio();
    }
    if (
      ['listeningText', 'listeningContent'].includes(previousRoute.name)
      && (route.name !== previousRoute.name || route.textId !== previousRoute.textId || route.contentId !== previousRoute.contentId)
    ) {
      await disposeListening();
    }
    state.route = route;
    updateNavigation(route);
    setViewBusy(false);
    if (route.name !== 'lemma') {
      lemmaController?.abort();
      suppressLemmaCloseNavigation = true;
      closeDialog(elements.lemmaDialog);
      suppressLemmaCloseNavigation = false;
    }
    if (route.name === 'overview') await showOverview();
    else if (route.name === 'progress') await showProgress();
    else if (route.name === 'benchmarks') await showBenchmarks();
    else if (route.name === 'study-session') showStudySession();
    else if (route.name === 'benchmarkRun') await showBenchmarkRun(route.runId);
    else if (route.name === 'curriculum') await showCurriculumLanding();
    else if (route.name === 'curriculumPack') await showCurriculumPack(route.packId, route.version);
    else if (route.name === 'inbox') await showInbox();
    else if (route.name === 'inboxContent') await showInboxContent(route.contentId);
    else if (route.name === 'reader') await showReader();
    else if (route.name === 'grammar' || route.name === 'grammarPattern') await showGrammar(route);
    else if (route.name === 'readerText') await showReaderDocument(route.textId);
    else if (route.name === 'listening') await showListening();
    else if (route.name === 'listeningText') await showListeningText(route.textId);
    else if (route.name === 'listeningContent') await showAuthenticListening(route.contentId);
    else if (route.name === 'vocabulary') showVocabulary();
    else if (route.name === 'lemma') showVocabulary({ lemmaId: route.lemmaId });
    else if (route.name === 'phrasebook') await showPhrasebook();
    else if (route.name === 'topics') await loadTopics();
    else if (route.name === 'statistics') await showStatistics();
    else if (route.name === 'goals') await loadGoals();
    else if (route.name === 'reviews') await showReviews();
    else if (route.name === 'cloze') await showCloze();
    else if (route.name === 'generate') await showGenerate();
    else if (route.name === 'settings') await showSettings();
    if (sequence !== routeSequence) return;
  }

  function readRoute() {
    const parsed = parseLanguageRoute(windowRef.location.hash);
    if (!parsed.valid) {
      showNotice(`“${parsed.invalidHash}” is not an available Language route. Showing Overview instead.`);
      preserveNoticeOnce = true;
      windowRef.location.replace(
        `${windowRef.location.pathname}${windowRef.location.search}${formatLanguageRoute('overview')}`,
      );
      renderRoute({ name: 'overview', valid: true });
      return;
    }
    if (preserveNoticeOnce) preserveNoticeOnce = false;
    else showNotice('');
    renderRoute(parsed);
  }

  async function bootstrap() {
    setViewBusy(true);
    replace(elements.view, messageState('loading', 'Loading Language Learning…'));
    try {
      const [profilesResult, health] = await Promise.all([api.profiles(), api.health()]);
      state.profiles = profilesResult.items || [];
      state.profile = selectBokmalProfile(state.profiles);
      state.health = health;
      if (!state.profile) throw new Error('No Language profile is available. Seed the Bokmål profile first.');
      state.bootstrapLoading = false;
      updateProfileSummary();
      refreshKnownWords();
      setConnection('ready', 'Ready');
      readRoute();
      refreshAnkiWebWhileOpen();
    } catch (error) {
      state.bootstrapLoading = false;
      state.bootstrapError = error?.message || 'Language Learning could not start.';
      setConnection('error', 'Backend unavailable');
      setViewBusy(false);
      replace(elements.view, messageState('error', 'Language Learning is unavailable.', state.bootstrapError));
    }
  }

  let ankiAutoTimer = null;
  let ankiAutoBusy = false;
  async function refreshAnkiWebWhileOpen() {
    if (!state.profile || documentRef.hidden || ankiAutoBusy || typeof api.syncAnkiWeb !== 'function') return;
    ankiAutoBusy = true;
    try {
      const status = await api.ankiStatus(state.profile.id);
      if (!status.config?.autoSync) return;
      const result = await api.syncAnkiWeb(state.profile.id);
      if (!result.skipped && state.route.name === 'reviews') await showReviews();
      else if (!result.skipped && state.route.name === 'overview') await showOverview();
    } catch (_error) {
      // Anki may be closed; the visible Reviews status reports connectivity.
    } finally { ankiAutoBusy = false; }
  }

  function bind() {
    windowRef.addEventListener('hashchange', readRoute);
    elements.mobileNav?.addEventListener('click', () => {
      const expanded = elements.mobileNav.getAttribute('aria-expanded') === 'true';
      elements.mobileNav.setAttribute('aria-expanded', String(!expanded));
    });
    documentRef.querySelector('#language-section-nav')?.addEventListener('click', (event) => {
      if (event.target.closest?.('a[data-language-route]')) elements.mobileNav?.setAttribute('aria-expanded', 'false');
    });
    documentRef.addEventListener('visibilitychange', interruptListeningForInactivity);
    windowRef.addEventListener('blur', interruptListeningForInactivity);
    elements.helpOpen?.addEventListener('click', () => {
      renderLanguageHelp(elements.helpMount, routeSection(state.route));
      openDialog(elements.helpDialog);
      elements.helpClose?.focus();
    });
    elements.helpClose?.addEventListener('click', () => closeDialog(elements.helpDialog));
    elements.helpDialog?.addEventListener('close', () => elements.helpOpen?.focus());
    documentRef.querySelector('[data-language-dialog-close]')?.addEventListener('click', () => closeDialog(elements.lemmaDialog));
    elements.lemmaDialog?.addEventListener('close', () => {
      if (!suppressLemmaCloseNavigation && state.route.name === 'lemma') {
        windowRef.location.hash = formatLanguageRoute('vocabulary');
      }
    });
    elements.mergeCheck?.addEventListener('change', () => {
      elements.mergeConfirm.disabled = !elements.mergeCheck.checked;
    });
    elements.mergeConfirm?.addEventListener('click', async () => {
      if (!pendingMerge || !elements.mergeCheck.checked) return;
      elements.mergeConfirm.disabled = true;
      elements.mergeError.hidden = false;
      elements.mergeError.textContent = 'Merging…';
      try {
        await api.mergeLemmas({
          sourceLemmaId: pendingMerge.source.id,
          targetLemmaId: pendingMerge.target.id,
          note: 'Confirmed in Language Phase 3 vocabulary UI',
        });
        const targetId = pendingMerge.target.id;
        const returnRoute = pendingMerge.returnRoute;
        pendingMerge = null;
        closeDialog(elements.mergeDialog);
        if (returnRoute?.name === 'readerText' && state.route.name === 'readerText') {
          await refreshOpenReaderDocument();
          await refreshReaderLemma(targetId);
        } else {
          windowRef.location.hash = formatLanguageRoute({ name: 'lemma', lemmaId: targetId });
        }
      } catch (error) {
        elements.mergeError.textContent = error?.message || 'The lemmas could not be merged.';
        elements.mergeConfirm.disabled = false;
      }
    });
  }

  function interruptListeningForInactivity(event) {
    if (event?.type === 'visibilitychange' && documentRef.visibilityState !== 'hidden') return;
    if (
      ['listeningText', 'listeningContent'].includes(state.route.name)
      && listeningPlayback
    ) {
      stopListeningPlayback('CANCELLED');
    }
  }

  function start() {
    if (started) return;
    started = true;
    bind();
    bootstrap();
    if (windowRef.setInterval) ankiAutoTimer = windowRef.setInterval(refreshAnkiWebWhileOpen, 5 * 60 * 1000);
  }

  function destroy() {
    sessionSequence += 1;
    grammarCleanup?.();
    windowRef.removeEventListener('hashchange', readRoute);
    documentRef.removeEventListener('visibilitychange', interruptListeningForInactivity);
    windowRef.removeEventListener('blur', interruptListeningForInactivity);
    vocabularyController?.abort();
    overviewController?.abort();
    overviewPlanController?.abort();
    progressController?.abort();
    curriculumController?.abort();
    analyticsController?.abort();
    lemmaController?.abort();
    readerController?.abort();
    clearJobPolls();
    disposeReaderActivity({ pause: true });
    windowRef.clearTimeout(searchTimer);
    windowRef.clearTimeout(generationPollTimer);
    if (ankiAutoTimer != null) windowRef.clearInterval(ankiAutoTimer);
    clozeCleanup?.();
    resetClozeAudio();
    disposeListening();
    browserSpeech.destroy();
  }

  return { start, destroy, state, readRoute, loadVocabulary };
}

const pageRoot = typeof document !== 'undefined' ? document.querySelector('#language-app') : null;
if (pageRoot && !globalThis.__LANGUAGE_TEST_DISABLE_AUTO__) createLanguageApp().start();
