import { describe, expect, it, vi } from 'vitest';
import { LanguageApiError, createLanguageApi } from '../js/language/api.js';

function response(payload, { ok = true, status = 200 } = {}) {
  return { ok, status, json: vi.fn(async () => payload) };
}

describe('Language API client', () => {
  it('unwraps success envelopes and sends bounded vocabulary query parameters', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: { items: [], pagination: { total: 0 } } }));
    const api = createLanguageApi({ fetchImpl });
    const controller = new AbortController();
    await api.vocabulary('profile id', { q: 'jobb', status: 'KNOWN', limit: 30 }, { signal: controller.signal });
    const [url, options] = fetchImpl.mock.calls[0];
    expect(url).toContain('/profiles/profile%20id/vocabulary?');
    expect(url).toContain('q=jobb');
    expect(url).toContain('status=KNOWN');
    expect(options.signal).toBe(controller.signal);
  });

  it('uses JSON PATCH writes compatible with the existing origin policy', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: { knowledge: {} } }));
    const api = createLanguageApi({ fetchImpl });
    await api.updateLemma('lemma', { knowledgeStatus: 'KNOWN' });
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      method: 'PATCH',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ knowledgeStatus: 'KNOWN' }),
    });
  });

  it('uses thin Content Inbox JSON routes and a raw audio upload', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: {} }));
    const api = createLanguageApi({ fetchImpl });
    const audio = new Blob(['audio'], { type: 'audio/wav' });
    Object.defineProperty(audio, 'name', { value: 'owned audio.wav' });
    await api.contentItems('profile', { limit: 20 });
    await api.contentItem('content');
    await api.createContent('profile', { sourceType: 'PASTED_TEXT', text: 'Hei.' });
    await api.uploadContentAudio('profile', audio, { title: 'Owned' });
    await api.addContentTranscript('content', { format: 'SRT', transcriptText: 'x' });
    await api.correctContentAlignment('alignment', { startMs: 0, endMs: 1000 });
    const calls = fetchImpl.mock.calls;
    expect(calls.map(([url]) => url)).toEqual([
      '/api/language/profiles/profile/content?limit=20',
      '/api/language/content/content',
      '/api/language/profiles/profile/content',
      '/api/language/profiles/profile/content/audio?title=Owned&fileName=owned+audio.wav',
      '/api/language/content/content/transcripts',
      '/api/language/content/alignments/alignment',
    ]);
    expect(calls[3][1]).toMatchObject({ method: 'POST', body: audio });
    expect(calls[3][1].headers['Content-Type']).toBe('audio/wav');
  });

  it('preserves Language error envelope details', async () => {
    const fetchImpl = vi.fn(async () => response({
      ok: false, error: 'Invalid score', code: 'invalid_language_request', details: ['recognition'],
    }, { ok: false, status: 400 }));
    const api = createLanguageApi({ fetchImpl });
    await expect(api.updateLemma('lemma', { recognition: 9 })).rejects.toMatchObject({
      name: 'LanguageApiError', message: 'Invalid score', code: 'invalid_language_request',
      details: ['recognition'], status: 400,
    });
  });

  it('distinguishes network and unreadable-response failures', async () => {
    const offline = createLanguageApi({ fetchImpl: vi.fn(async () => { throw new TypeError('offline'); }) });
    await expect(offline.health()).rejects.toMatchObject({
      name: 'LanguageApiError', code: 'language_api_unavailable',
    });

    const unreadable = createLanguageApi({ fetchImpl: vi.fn(async () => ({
      ok: false, status: 502, json: async () => { throw new Error('not json'); },
    })) });
    await expect(unreadable.health()).rejects.toBeInstanceOf(LanguageApiError);
    await expect(unreadable.health()).rejects.toMatchObject({ code: 'invalid_language_response', status: 502 });
  });

  it('uses the thin Reader job, session, exposure, and progress routes', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: {} }));
    const api = createLanguageApi({ fetchImpl });
    await api.analyzeText('text');
    await api.startReaderSession({ textDocumentId: 'text' });
    await api.updateReaderSession('session', { action: 'PAUSE', commandId: 'pause-1' });
    await api.recordReaderExposures('session', { sentenceId: 'sentence', occurrences: [] });
    await api.updateReadingProgress('text', { progressSourceOffset: 5, status: 'IN_PROGRESS' });
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/texts/text/analyze',
      '/api/language/study-sessions',
      '/api/language/study-sessions/session',
      '/api/language/study-sessions/session/exposures',
      '/api/language/texts/text/reading-progress',
    ]);
    expect(fetchImpl.mock.calls.map(([, options]) => options.method)).toEqual([
      'POST', 'POST', 'PATCH', 'POST', 'PATCH',
    ]);
  });

  it('uses authoritative lemma and token audio routes with an explicit retry request', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: { state: 'QUEUED' } }));
    const api = createLanguageApi({ fetchImpl });
    await api.wordAudio('lemma', 'lemma-1', { retry: true });
    await api.wordAudio('token', 'token-1');
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/lemmas/lemma-1/audio',
      '/api/language/tokens/token-1/audio',
    ]);
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({ method: 'POST', body: '{}' });
    expect(fetchImpl.mock.calls[1][1].method).toBe('GET');
  });

  it('uses thin Phase 5 analytics, topic, goal, and widget routes', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: {} }));
    const api = createLanguageApi({ fetchImpl });
    await api.overview('profile', { asOf: '2026-09-16T10:00:00Z' });
    await api.statistics('profile', { range: '30d' });
    await api.learningPlan('profile');
    await api.widgetSummary('profile');
    await api.topics('profile', { includeArchived: true });
    await api.topic('topic');
    await api.createTopic('profile', { displayName: 'Work' });
    await api.updateTopic('topic', { archived: true });
    await api.assignTopicLemma('topic', { lemmaId: 'lemma', weight: 2 });
    await api.removeTopicLemma('topic', 'lemma');
    await api.goals('profile');
    await api.createGoal('profile', { metric: 'NEW_WORDS', targetValue: 5, unit: 'WORDS' });
    await api.updateGoal('goal', { enabled: false });

    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/profiles/profile/overview?asOf=2026-09-16T10%3A00%3A00Z',
      '/api/language/profiles/profile/statistics?range=30d',
      '/api/language/profiles/profile/learning-plan',
      '/api/language/profiles/profile/widget-summary',
      '/api/language/profiles/profile/topics?includeArchived=true',
      '/api/language/topics/topic',
      '/api/language/profiles/profile/topics',
      '/api/language/topics/topic',
      '/api/language/topics/topic/lemmas',
      '/api/language/topics/topic/lemmas/lemma',
      '/api/language/profiles/profile/goals',
      '/api/language/profiles/profile/goals',
      '/api/language/goals/goal',
    ]);
    expect(fetchImpl.mock.calls.map(([, options]) => options.method)).toEqual([
      'GET', 'GET', 'GET', 'GET', 'GET', 'GET', 'POST', 'PATCH', 'POST', 'DELETE', 'GET', 'POST', 'PATCH',
    ]);
  });

  it('uses read-only Phase 9.5 mistake and remediation routes', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: {} }));
    const api = createLanguageApi({ fetchImpl });
    await api.mistakes('profile id', { limit: 10 });
    await api.mistakeDetail('profile id', 'mi:cluster');
    await api.remediation('profile id', { limit: 5 });
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/profiles/profile%20id/mistakes?limit=10',
      '/api/language/profiles/profile%20id/mistakes/mi%3Acluster',
      '/api/language/profiles/profile%20id/remediation?limit=5',
    ]);
    expect(fetchImpl.mock.calls.every(([, options]) => options.method === 'GET')).toBe(true);
  });

  it('uses thin Phase 6 Anki config, discovery, preview, commit, link, pull, and history routes', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: {} }));
    const api = createLanguageApi({ fetchImpl });
    await api.ankiStatus('profile');
    await api.ankiConfig('profile');
    await api.updateAnkiConfig('profile', { enabled: true });
    await api.testAnki('profile');
    await api.ankiDecks('profile');
    await api.ankiModels('profile');
    await api.ankiModelFields('profile', 'Basic & reversed');
    await api.lemmaAnki('lemma');
    await api.previewAnki('lemma', { sentenceId: 'sentence' });
    await api.commitAnki('lemma', { confirm: true, previewFingerprint: 'hash' });
    await api.linkAnki('lemma', { externalNoteId: 12, confirm: false });
    await api.resolveAnki('lemma', { resolution: 'ANKI_WINS' });
    await api.pullAnki('profile');
    await api.ankiSyncRuns('profile', { limit: 10 });
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/profiles/profile/anki/status',
      '/api/language/profiles/profile/anki/config',
      '/api/language/profiles/profile/anki/config',
      '/api/language/profiles/profile/anki/test',
      '/api/language/profiles/profile/anki/decks',
      '/api/language/profiles/profile/anki/models',
      '/api/language/profiles/profile/anki/models/Basic%20%26%20reversed/fields',
      '/api/language/lemmas/lemma/anki',
      '/api/language/lemmas/lemma/anki/preview',
      '/api/language/lemmas/lemma/anki/commit',
      '/api/language/lemmas/lemma/anki/link',
      '/api/language/lemmas/lemma/anki/resolve',
      '/api/language/profiles/profile/anki/pull',
      '/api/language/profiles/profile/anki/sync-runs?limit=10',
    ]);
  });

  it('uses thin Phase 7.7 lexical and Phrasebook routes', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, data: {} }));
    const api = createLanguageApi({ fetchImpl });
    await api.lemmaLexical('lemma');
    await api.upsertLemmaTranslation('lemma', { targetLocale: 'pl-PL', translation: 'praca' });
    await api.deleteLemmaTranslation('lemma', 'pl-PL');
    await api.phrasebook('profile', { q: 'på jobb', sourceType: 'READER', limit: 50 });
    await api.createPhrasebookEntry('profile', { expression: 'på jobb', sourceType: 'READER' });
    await api.phrasebookEntry('entry');
    await api.updatePhrasebookEntry('entry', { note: 'Useful' });
    await api.deletePhrasebookEntry('entry');
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/lemmas/lemma/lexical-detail',
      '/api/language/lemmas/lemma/translations',
      '/api/language/lemmas/lemma/translations?targetLocale=pl-PL',
      '/api/language/profiles/profile/phrasebook?q=p%C3%A5+jobb&sourceType=READER&limit=50',
      '/api/language/profiles/profile/phrasebook',
      '/api/language/phrasebook/entry',
      '/api/language/phrasebook/entry',
      '/api/language/phrasebook/entry',
    ]);
    expect(fetchImpl.mock.calls.map(([, options]) => options.method)).toEqual([
      'GET', 'POST', 'DELETE', 'GET', 'POST', 'GET', 'PATCH', 'DELETE',
    ]);
  });
});
