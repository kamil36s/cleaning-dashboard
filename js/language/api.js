export class LanguageApiError extends Error {
  constructor(message, { code = 'language_request_failed', details = [], status = 0 } = {}) {
    super(message);
    this.name = 'LanguageApiError';
    this.code = code;
    this.details = Array.isArray(details) ? details : [];
    this.status = status;
  }
}

function queryString(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) query.set(key, String(value));
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}

export function createLanguageApi({ fetchImpl = globalThis.fetch, baseUrl = '/api/language' } = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('A fetch implementation is required');

  async function request(path, { method = 'GET', body, signal } = {}) {
    let response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method,
        cache: 'no-store',
        signal,
        headers: body === undefined
          ? { Accept: 'application/json' }
          : { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new LanguageApiError('Language API is unavailable. Start or reconnect the dashboard server.', {
        code: 'language_api_unavailable',
      });
    }

    let envelope;
    try {
      envelope = await response.json();
    } catch {
      throw new LanguageApiError(`Language API returned an unreadable response (${response.status}).`, {
        code: 'invalid_language_response',
        status: response.status,
      });
    }

    if (!response.ok || envelope?.ok !== true) {
      throw new LanguageApiError(
        envelope?.error || `Language request failed (${response.status}).`,
        {
          code: envelope?.code,
          details: envelope?.details,
          status: response.status,
        },
      );
    }
    return envelope.data;
  }

  async function rawRequest(path, { body, contentType, signal } = {}) {
    let response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method: 'POST', cache: 'no-store', signal,
        headers: { Accept: 'application/json', 'Content-Type': contentType || 'application/octet-stream' },
        body,
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new LanguageApiError('Language API is unavailable. Start or reconnect the dashboard server.', {
        code: 'language_api_unavailable',
      });
    }
    let envelope;
    try { envelope = await response.json(); } catch {
      throw new LanguageApiError(`Language API returned an unreadable response (${response.status}).`, {
        code: 'invalid_language_response', status: response.status,
      });
    }
    if (!response.ok || envelope?.ok !== true) {
      throw new LanguageApiError(envelope?.error || `Language request failed (${response.status}).`, {
        code: envelope?.code, details: envelope?.details, status: response.status,
      });
    }
    return envelope.data;
  }

  const id = (value) => encodeURIComponent(String(value));
  return {
    grammar: (profileId) => request(`/profiles/${encodeURIComponent(profileId)}/grammar`),
    grammarPattern: (profileId, patternId) => request(`/profiles/${encodeURIComponent(profileId)}/grammar/patterns/${encodeURIComponent(patternId)}`),
    textGrammar: (textId, profileId) => request(`/texts/${encodeURIComponent(textId)}/grammar${queryString({ profileId })}`),
    analyzeGrammar: (textId, profileId) => request(`/texts/${encodeURIComponent(textId)}/grammar-analysis`, { method: 'POST', body: { languageProfileId: profileId } }),
    reviewGrammar: (occurrenceId, profileId, decision) => request(`/grammar/occurrences/${encodeURIComponent(occurrenceId)}/review`, { method: 'PATCH', body: { languageProfileId: profileId, decision } }),
    health: ({ signal } = {}) => request('/health', { signal }),
    referenceHealth: ({ signal } = {}) => request('/reference/health', { signal }),
    profiles: ({ signal } = {}) => request('/profiles', { signal }),
    profile: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}`, { signal }),
    overview: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/overview${queryString(params)}`, { signal },
    ),
    todaySummary: (profileId, { signal } = {}) => request(
      `/profiles/${id(profileId)}/today-summary`, { signal },
    ),
    lexicalPreview: (profileId, surface, { signal } = {}) => request(
      `/profiles/${id(profileId)}/lexical-preview${queryString({ surface })}`, { signal },
    ),
    lexicalMeanings: (profileId, surface, { signal } = {}) => request(
      `/profiles/${id(profileId)}/lexical-meanings${queryString({ surface })}`, { signal },
    ),
    gamification: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/gamification${queryString(params)}`, { signal },
    ),
    achievements: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/achievements${queryString(params)}`, { signal },
    ),
    collections: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/collections`, { signal }),
    curriculum: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/curriculum`, { signal }),
    benchmarks: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/benchmarks`, { signal }),
    studySession: (profileId, minutes, { signal } = {}) => request(
      `/profiles/${id(profileId)}/study-session${queryString({ minutes })}`, { signal },
    ),
    benchmarkRun: (profileId, runId, { signal } = {}) => request(`/profiles/${id(profileId)}/benchmarks/${id(runId)}`, { signal }),
    startBenchmark: (profileId) => request(`/profiles/${id(profileId)}/benchmarks`, { method: 'POST', body: {} }),
    respondBenchmark: (profileId, runId, payload) => request(`/profiles/${id(profileId)}/benchmarks/${id(runId)}/responses`, { method: 'POST', body: payload }),
    completeBenchmark: (profileId, runId) => request(`/profiles/${id(profileId)}/benchmarks/${id(runId)}/complete`, { method: 'POST', body: {} }),
    norwayPreparation: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/norway-preparation`, { signal }),
    curriculumPack: (profileId, packId, version, { signal } = {}) => request(
      `/profiles/${id(profileId)}/curriculum/${id(packId)}/versions/${id(version)}`, { signal },
    ),
    curriculumItem: (profileId, packId, version, membershipId, { signal } = {}) => request(
      `/profiles/${id(profileId)}/curriculum/${id(packId)}/versions/${id(version)}/items/${id(membershipId)}`,
      { signal },
    ),
    quests: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/quests${queryString(params)}`, { signal },
    ),
    campaigns: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/campaigns`, { signal }),
    createCampaign: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/campaigns`, {
      method: 'POST', body: payload, signal,
    }),
    updateCampaign: (campaignId, payload, { signal } = {}) => request(`/campaigns/${id(campaignId)}`, {
      method: 'PATCH', body: payload, signal,
    }),
    statistics: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/statistics${queryString(params)}`, { signal },
    ),
    listening: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/listening${queryString(params)}`, { signal },
    ),
    contentItems: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/content${queryString(params)}`, { signal },
    ),
    contentItem: (contentId, { signal } = {}) => request(`/content/${id(contentId)}`, { signal }),
    createContent: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/content`, {
      method: 'POST', body: payload, signal,
    }),
    uploadContentAudio: (profileId, file, { title = '', signal } = {}) => rawRequest(
      `/profiles/${id(profileId)}/content/audio${queryString({ title, fileName: file?.name || 'audio' })}`,
      { body: file, contentType: file?.type || 'application/octet-stream', signal },
    ),
    addContentTranscript: (contentId, payload, { signal } = {}) => request(
      `/content/${id(contentId)}/transcripts`, { method: 'POST', body: payload, signal },
    ),
    correctContentAlignment: (alignmentId, payload, { signal } = {}) => request(
      `/content/alignments/${id(alignmentId)}`, { method: 'PATCH', body: payload, signal },
    ),
    listeningProgress: (textId, profileId, { signal } = {}) => request(
      `/texts/${id(textId)}/listening-progress${queryString({ profileId })}`, { signal },
    ),
    startListeningSession: (textId, payload, { signal } = {}) => request(
      `/texts/${id(textId)}/listening-sessions`, { method: 'POST', body: payload, signal },
    ),
    recordListeningEvent: (sessionId, payload, { signal } = {}) => request(
      `/listening-sessions/${id(sessionId)}/sentence-events`, { method: 'POST', body: payload, signal },
    ),
    closeListeningSession: (sessionId, payload, { signal } = {}) => request(
      `/listening-sessions/${id(sessionId)}`, { method: 'PATCH', body: payload, signal },
    ),
    mistakes: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/mistakes${queryString(params)}`, { signal },
    ),
    mistakeDetail: (profileId, clusterId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/mistakes/${id(clusterId)}${queryString(params)}`, { signal },
    ),
    remediation: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/remediation${queryString(params)}`, { signal },
    ),
    learningPlan: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/learning-plan${queryString(params)}`, { signal },
    ),
    clozeTracks: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/cloze/tracks`, { signal }),
    clozeStatistics: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/cloze/statistics`, { signal }),
    startClozeSession: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/cloze/sessions`, {
      method: 'POST', body: payload, signal,
    }),
    clozeSession: (sessionId, { signal } = {}) => request(`/cloze/sessions/${id(sessionId)}`, { signal }),
    submitClozeAttempt: (sessionId, payload, { signal } = {}) => request(`/cloze/sessions/${id(sessionId)}/attempts`, {
      method: 'POST', body: payload, signal,
    }),
    reportClozeItem: (sessionId, payload, { signal } = {}) => request(`/cloze/sessions/${id(sessionId)}/report`, {
      method: 'POST', body: payload, signal,
    }),
    clozeAudio: (sessionId, itemIndex, payload, { signal } = {}) => request(
      `/cloze/sessions/${id(sessionId)}/items/${id(itemIndex)}/audio`,
      { method: 'POST', body: payload, signal },
    ),
    createGenerationRequest: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/generation-requests`, { method: 'POST', body: payload, signal }),
    readingSeries: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/reading-series`, { signal }),
    createReadingSeries: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/reading-series`, { method: 'POST', body: payload, signal }),
    updateReadingSeries: (seriesId, payload, { signal } = {}) => request(`/reading-series/${id(seriesId)}`, { method: 'PATCH', body: payload, signal }),
    assignTextSeries: (textId, seriesId, { signal } = {}) => request(`/texts/${id(textId)}/series`, { method: 'PATCH', body: { seriesId }, signal }),
    generationProviderHealth: ({ signal } = {}) => request('/generation/provider-health', { signal }),
    startAutomaticGeneration: (requestId, { signal } = {}) => request(`/generation-requests/${id(requestId)}/automatic`, { method: 'POST', body: {}, signal }),
    cancelAutomaticGeneration: (requestId, { signal } = {}) => request(`/generation-requests/${id(requestId)}/cancel`, { method: 'POST', body: {}, signal }),
    generationRequest: (requestId, { signal } = {}) => request(`/generation-requests/${id(requestId)}`, { signal }),
    generationContext: (requestId, { signal } = {}) => request(`/generation-requests/${id(requestId)}/context-pack`, { signal }),
    generationCandidates: (requestId, { signal } = {}) => request(`/generation-requests/${id(requestId)}/candidates`, { signal }),
    importGenerationCandidate: (requestId, payload, { signal } = {}) => request(`/generation-requests/${id(requestId)}/candidates`, { method: 'POST', body: payload, signal }),
    generationCandidate: (candidateId, { signal } = {}) => request(`/generation-candidates/${id(candidateId)}`, { signal }),
    analyzeGenerationCandidate: (candidateId, { signal } = {}) => request(`/generation-candidates/${id(candidateId)}/analyze`, { method: 'POST', body: {}, signal }),
    generationRevisionPrompt: (candidateId, { signal } = {}) => request(`/generation-candidates/${id(candidateId)}/revision-prompt`, { signal }),
    acceptGenerationCandidate: (candidateId, { signal } = {}) => request(`/generation-candidates/${id(candidateId)}/accept`, { method: 'POST', body: {}, signal }),
    rejectGenerationCandidate: (candidateId, payload = {}, { signal } = {}) => request(`/generation-candidates/${id(candidateId)}/reject`, { method: 'POST', body: payload, signal }),
    widgetSummary: (profileId, { signal } = {}) => request(
      `/profiles/${id(profileId)}/widget-summary`, { signal },
    ),
    ankiStatus: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/anki/status`, { signal }),
    ankiInsights: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/anki/insights${queryString(params)}`, { signal },
    ),
    translateReaderSentence: (textId, sentenceId, targetLanguage = 'en', { signal } = {}) => request(
      `/texts/${id(textId)}/sentences/${id(sentenceId)}/translate`,
      { method: 'POST', body: { targetLanguage }, signal },
    ),
    readerStudyNotes: (textId, { signal } = {}) => request(`/texts/${id(textId)}/study-notes`, { signal }),
    importReaderStudyNotes: (textId, payload, { signal } = {}) => request(
      `/texts/${id(textId)}/study-notes/import`, { method: 'POST', body: payload, signal },
    ),
    previewReaderStoryAnki: (textId, { signal } = {}) => request(`/texts/${id(textId)}/anki-story/preview`, {
      method: 'POST', body: {}, signal,
    }),
    createReaderStoryAnki: (textId, previewToken, translationOverrides = {}, sourceOverrides = {}, { signal } = {}) => request(`/texts/${id(textId)}/anki-story/create`, {
      method: 'POST', body: { previewToken, translationOverrides, sourceOverrides }, signal,
    }),
    ankiConfig: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/anki/config`, { signal }),
    updateAnkiConfig: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/anki/config`, {
      method: 'PATCH', body: payload, signal,
    }),
    testAnki: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/anki/test`, {
      method: 'POST', body: {}, signal,
    }),
    ankiDecks: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/anki/decks`, { signal }),
    ankiModels: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/anki/models`, { signal }),
    ankiModelFields: (profileId, modelName, { signal } = {}) => request(
      `/profiles/${id(profileId)}/anki/models/${id(modelName)}/fields`, { signal },
    ),
    pullAnki: (profileId, { signal } = {}) => request(`/profiles/${id(profileId)}/anki/pull`, {
      method: 'POST', body: {}, signal,
    }),
    syncAnkiWeb: (profileId, { force = false, signal } = {}) => request(`/profiles/${id(profileId)}/anki/sync-web`, {
      method: 'POST', body: { force }, signal,
    }),
    ankiSyncRuns: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/anki/sync-runs${queryString(params)}`, { signal },
    ),
    updateProfile: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}`, {
      method: 'PATCH', body: payload, signal,
    }),
    vocabulary: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/vocabulary${queryString(params)}`,
      { signal },
    ),
    vocabularyAnkiStatus: (profileId, lemmaIds, { signal } = {}) => request(
      `/profiles/${id(profileId)}/vocabulary/anki-status${queryString({ ids: lemmaIds.join(',') })}`,
      { signal },
    ),
    phrasebook: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/phrasebook${queryString(params)}`, { signal },
    ),
    createPhrasebookEntry: (profileId, payload, { signal } = {}) => request(
      `/profiles/${id(profileId)}/phrasebook`, { method: 'POST', body: payload, signal },
    ),
    phrasebookEntry: (entryId, { signal } = {}) => request(`/phrasebook/${id(entryId)}`, { signal }),
    updatePhrasebookEntry: (entryId, payload, { signal } = {}) => request(`/phrasebook/${id(entryId)}`, {
      method: 'PATCH', body: payload, signal,
    }),
    deletePhrasebookEntry: (entryId, { signal } = {}) => request(`/phrasebook/${id(entryId)}`, {
      method: 'DELETE', signal,
    }),
    topics: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/topics${queryString(params)}`, { signal },
    ),
    topic: (topicId, { signal } = {}) => request(`/topics/${id(topicId)}`, { signal }),
    createTopic: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/topics`, {
      method: 'POST', body: payload, signal,
    }),
    updateTopic: (topicId, payload, { signal } = {}) => request(`/topics/${id(topicId)}`, {
      method: 'PATCH', body: payload, signal,
    }),
    assignTopicLemma: (topicId, payload, { signal } = {}) => request(`/topics/${id(topicId)}/lemmas`, {
      method: 'POST', body: payload, signal,
    }),
    removeTopicLemma: (topicId, lemmaId, { signal } = {}) => request(`/topics/${id(topicId)}/lemmas/${id(lemmaId)}`, {
      method: 'DELETE', signal,
    }),
    goals: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/goals${queryString(params)}`, { signal },
    ),
    createGoal: (profileId, payload, { signal } = {}) => request(`/profiles/${id(profileId)}/goals`, {
      method: 'POST', body: payload, signal,
    }),
    updateGoal: (goalId, payload, { signal } = {}) => request(`/goals/${id(goalId)}`, {
      method: 'PATCH', body: payload, signal,
    }),
    texts: (profileId, params = {}, { signal } = {}) => request(
      `/profiles/${id(profileId)}/texts${queryString(params)}`,
      { signal },
    ),
    createText: (payload, { signal } = {}) => request('/texts', {
      method: 'POST', body: payload, signal,
    }),
    text: (textId, { signal } = {}) => request(`/texts/${id(textId)}`, { signal }),
    generatedSentenceAudio: (textId, sentenceId, { signal } = {}) => request(
      `/texts/${id(textId)}/sentences/${id(sentenceId)}/audio`,
      { method: 'POST', body: {}, signal },
    ),
    wordAudio: (kind, wordId, { retry = false, signal } = {}) => request(
      `/${kind === 'token' ? 'tokens' : 'lemmas'}/${id(wordId)}/audio`,
      retry ? { method: 'POST', body: {}, signal } : { signal },
    ),
    textReferenceProfile: (textId, { signal } = {}) => request(`/texts/${id(textId)}/reference-profile`, { signal }),
    analyzeText: (textId, { signal } = {}) => request(`/texts/${id(textId)}/analyze`, {
      method: 'POST', body: {}, signal,
    }),
    job: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}`, { signal }),
    cancelJob: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}/cancel`, {
      method: 'POST', body: {}, signal,
    }),
    startReaderSession: (payload, { signal } = {}) => request('/study-sessions', {
      method: 'POST', body: payload, signal,
    }),
    updateReaderSession: (sessionId, payload, { signal } = {}) => request(`/study-sessions/${id(sessionId)}`, {
      method: 'PATCH', body: payload, signal,
    }),
    recordReaderExposures: (sessionId, payload, { signal } = {}) => request(`/study-sessions/${id(sessionId)}/exposures`, {
      method: 'POST', body: payload, signal,
    }),
    updateReadingProgress: (textId, payload, { signal } = {}) => request(`/texts/${id(textId)}/reading-progress`, {
      method: 'PATCH', body: payload, signal,
    }),
    lemma: (lemmaId, { signal } = {}) => request(`/lemmas/${id(lemmaId)}`, { signal }),
    lemmaReference: (lemmaId, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/reference`, { signal }),
    lemmaLexical: (lemmaId, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/lexical-detail`, { signal }),
    lemmaPreview: (lemmaId, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/preview`, { signal }),
    upsertLemmaTranslation: (lemmaId, payload, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/translations`, {
      method: 'POST', body: payload, signal,
    }),
    deleteLemmaTranslation: (lemmaId, targetLocale, { signal } = {}) => request(
      `/lemmas/${id(lemmaId)}/translations${queryString({ targetLocale })}`, { method: 'DELETE', signal },
    ),
    lemmaAnki: (lemmaId, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/anki`, { signal }),
    previewAnki: (lemmaId, payload = {}, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/anki/preview`, {
      method: 'POST', body: payload, signal,
    }),
    commitAnki: (lemmaId, payload, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/anki/commit`, {
      method: 'POST', body: payload, signal,
    }),
    linkAnki: (lemmaId, payload, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/anki/link`, {
      method: 'POST', body: payload, signal,
    }),
    resolveAnki: (lemmaId, payload, { signal } = {}) => request(`/lemmas/${id(lemmaId)}/anki/resolve`, {
      method: 'POST', body: payload, signal,
    }),
    updateLemma: (lemmaId, payload, { signal } = {}) => request(`/lemmas/${id(lemmaId)}`, {
      method: 'PATCH', body: payload, signal,
    }),
    formMapping: (formId, { signal } = {}) => request(`/forms/${id(formId)}/mapping`, { signal }),
    lockFormMapping: (formId, lemmaId, { signal } = {}) => request(`/forms/${id(formId)}/mapping`, {
      method: 'PATCH', body: { lemmaId }, signal,
    }),
    mergeLemmas: (payload, { signal } = {}) => request('/lemmas/merge', {
      method: 'POST', body: payload, signal,
    }),
  };
}

export const languageApi = createLanguageApi();
