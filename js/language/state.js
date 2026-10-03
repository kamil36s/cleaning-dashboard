export function createLanguageState() {
  return {
    route: { name: 'overview', valid: true },
    profiles: [],
    profile: null,
    health: null,
    bootstrapLoading: true,
    bootstrapError: null,
    overview: { loading: false, error: null, data: null, minutes: 20, planLoading: false, planError: null },
    progress: { loading: false, error: null, data: null },
    curriculum: {
      loading: false, error: null, landing: null, pack: null, query: '', stateFilter: '',
    },
    statistics: { loading: false, error: null, range: '30d', data: null },
    topics: { loading: false, error: null, items: [], selected: null },
    goals: { loading: false, error: null, items: [] },
    phrasebook: { loading: false, error: null, items: [], total: 0, query: '', sourceType: '' },
    anki: { loading: false, error: null, status: null, config: null, runs: [] },
    mistakes: { loading: false, error: null, summary: null },
    cloze: {
      loading: false, busy: false, error: null, notice: '', tracks: null, session: null,
      feedback: null, lastItem: null, attempts: [], questionStartedAt: 0,
      preferences: { translationTiming: 'AFTER' },
      audio: { status: 'IDLE', itemKey: '', error: null },
    },
    generation: {
      busy: false, error: null, notice: '', topics: [], series: [], texts: [], request: null, contextPack: null, candidates: [],
      providerHealth: null,
      form: { generationMode: 'AUTOMATIC', length: 400, difficultyPreset: 'BALANCED', targetCoverage: 95, customTopic: '', grammarFocus: '', styleInstruction: '', referenceEnrichment: true, storyMode: 'NEW', seriesId: '', previousTextId: '', episodeDirection: '', avoidRepeating: '', pacing: 'STEADY', ending: 'OPEN' },
    },
    reader: {
      items: [],
      series: [],
      total: 0,
      nextCursor: null,
      loadingMore: false,
      loading: false,
      error: null,
      jobs: new Map(),
      document: null,
      documentLoading: false,
      documentError: null,
    },
    listening: {
      items: [], total: 0, loading: false, error: null, payload: null, progress: null,
      currentIndex: 0, playbackState: 'IDLE', statusText: 'Ready', activeMs: 0,
      speech: { state: 'VOICE_LOADING', voices: [], selectedVoiceId: null },
    },
    inbox: { items: [], total: 0, loading: false, busy: false, error: null, detail: null },
    vocabulary: {
      query: '',
      knowledgeStatus: '',
      disposition: '',
      items: [],
      ankiStatus: { status: 'LOADING', lemmas: {} },
      total: 0,
      nextCursor: null,
      loading: false,
      loadingMore: false,
      error: null,
      requestSequence: 0,
    },
    selectedLemma: null,
    selectedLemmaLoading: false,
    selectedLemmaError: null,
  };
}

export function selectBokmalProfile(profiles) {
  const items = Array.isArray(profiles) ? profiles : [];
  return items.find((profile) => profile.languageCode === 'nb' && profile.locale === 'nb-NO')
    || items.find((profile) => profile.languageCode === 'nb')
    || items.find((profile) => profile.status === 'ACTIVE')
    || items[0]
    || null;
}
