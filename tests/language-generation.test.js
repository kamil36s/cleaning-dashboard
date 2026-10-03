import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createLanguageApi } from '../js/language/api.js';
import { renderGenerate } from '../js/language/views/generate.js';

const request = { id: 'r'.repeat(32), promptFingerprint: 'sha256:test' };
const pack = { formatVersion: 'language-generation-context/v1', estimatedCharacterCount: 400, files: {
  'prompt.md': 'Write Norwegian Bokmål.',
  'known-vocabulary.txt': 'jobb\nbok',
  'focus-vocabulary.json': { items: [{ lemma: 'jobb' }] },
  'generation-spec.json': { requestedLengthWords: 400 },
  'metadata.json': { knownVocabularyIncluded: 2, focusVocabularyCount: 1 },
} };

function state(overrides = {}) {
  return { busy: false, error: null, notice: '', topics: [], request: null, contextPack: null, candidates: [],
    providerHealth: { state: 'CONFIGURED', configured: true, modelId: 'gemini-3.8-flash', policy: 'FREE_ONLY' },
    form: { generationMode: 'AUTOMATIC', length: 400, difficultyPreset: 'BALANCED', targetCoverage: 95, customTopic: '', grammarFocus: '', styleInstruction: '' }, ...overrides };
}

function actions() {
  return { onCreate: vi.fn(), onStartAutomatic: vi.fn(), onCancelAutomatic: vi.fn(), onCopy: vi.fn(), onExport: vi.fn(), onImport: vi.fn(), onAnalyze: vi.fn(), onRevision: vi.fn(), onAccept: vi.fn(), onReject: vi.fn() };
}

describe('Language generation workflow', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="mount"></main>'; });
  afterEach(() => { vi.restoreAllMocks(); document.body.replaceChildren(); });

  it('renders presets and submits a deterministic generation specification', () => {
    const handlers = actions();
    renderGenerate(document.querySelector('#mount'), state(), handlers);
    expect(document.body.textContent).toContain('Automatic · Gemini free tier');
    expect(document.body.textContent).toContain('Gemini ready');
    expect(document.body.textContent).toContain('Very Easy · 99%');
    document.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(handlers.onCreate).toHaveBeenCalledWith(expect.objectContaining({ generationMode: 'AUTOMATIC', length: 400, difficultyPreset: 'BALANCED', targetCoverage: 95 }));
  });

  it('offers a new series and passes its story bible into creation', () => {
    const handlers = actions();
    renderGenerate(document.querySelector('#mount'), state(), handlers);
    const form = document.querySelector('.language-generation-form');
    const selects = [...form.querySelectorAll('select')];
    const series = selects.find((item) => [...item.options].some((option) => option.value === '__new__'));
    series.value = '__new__'; series.dispatchEvent(new Event('change'));
    const storyFields = form.querySelector('.language-generation-story-fields');
    expect(storyFields.hidden).toBe(false);
    storyFields.querySelector('input').value = 'Maja and Erik';
    storyFields.querySelectorAll('textarea')[0].value = 'A harbor mystery';
    storyFields.querySelectorAll('textarea')[1].value = 'Erik knows the boat owner';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(handlers.onCreate).toHaveBeenCalledWith(expect.objectContaining({
      storyMode: 'NEW', newSeries: { title: 'Maja and Erik', premise: 'A harbor mystery', continuityNotes: 'Erik knows the boat owner' },
    }));
  });

  it('selects a specific prior episode and directions for a continuation', () => {
    const handlers = actions();
    const series = [{ id: 's'.repeat(32), title: 'Harbor', episodeCount: 2, episodes: [
      { textDocumentId: 'a'.repeat(32), episodeNumber: 1, title: 'Letter' },
      { textDocumentId: 'b'.repeat(32), episodeNumber: 2, title: 'Boat' },
    ] }];
    renderGenerate(document.querySelector('#mount'), state({ series, form: {
      ...state().form, storyMode: 'CONTINUE', seriesId: series[0].id, previousTextId: 'a'.repeat(32),
    } }), handlers);
    const form = document.querySelector('.language-generation-form');
    const story = form.querySelector('.language-generation-story');
    expect(story.textContent).toContain('Episode 1: Letter');
    const textareas = story.querySelectorAll('textarea');
    textareas[textareas.length - 2].value = 'Follow the boat';
    textareas[textareas.length - 1].value = 'No second letter';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(handlers.onCreate).toHaveBeenCalledWith(expect.objectContaining({
      storyMode: 'CONTINUE', seriesId: series[0].id, previousTextId: 'a'.repeat(32),
      episodeDirection: 'Follow the boat', avoidRepeating: 'No second letter',
    }));
  });

  it('can turn a standalone Reader text into the first episode before continuing it', () => {
    const handlers = actions();
    renderGenerate(document.querySelector('#mount'), state({ texts: [{ id: 't'.repeat(32), title: 'A quiet Saturday' }] }), handlers);
    const form = document.querySelector('.language-generation-form');
    const storySelect = [...form.querySelectorAll('select')].find((item) => [...item.options].some((option) => option.value === 'CONTINUE'));
    storySelect.value = 'CONTINUE'; storySelect.dispatchEvent(new Event('change'));
    const seriesSelect = [...form.querySelectorAll('select')].find((item) => [...item.options].some((option) => option.value === '__new__'));
    seriesSelect.value = '__new__'; seriesSelect.dispatchEvent(new Event('change'));
    expect(form.textContent).toContain('A quiet Saturday');
    form.querySelector('.language-generation-story-fields input').value = 'Saturday stories';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(handlers.onCreate).toHaveBeenCalledWith(expect.objectContaining({
      storyMode: 'CONTINUE', previousTextId: 't'.repeat(32),
      newSeries: expect.objectContaining({ title: 'Saturday stories' }),
    }));
  });

  it('shows the context pack and safe copy/export controls', () => {
    const handlers = actions();
    renderGenerate(document.querySelector('#mount'), state({ request, contextPack: pack }), handlers);
    expect(document.body.textContent).toContain('Write Norwegian Bokmål.');
    const copy = [...document.querySelectorAll('button')].find((button) => button.textContent === 'Copy complete prompt');
    copy.click();
    expect(handlers.onCopy).toHaveBeenCalledWith(pack.files['prompt.md']);
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Export context pack').click();
    expect(handlers.onExport).toHaveBeenCalledWith(pack);
  });

  it('requires explicit plain-text fallback in the import UI', () => {
    const handlers = actions();
    renderGenerate(document.querySelector('#mount'), state({ request, contextPack: pack }), handlers);
    const forms = document.querySelectorAll('form');
    forms[1].querySelector('textarea').value = '<b>tekst</b>';
    forms[1].querySelector('input[type="checkbox"]').click();
    forms[1].dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(handlers.onImport).toHaveBeenCalledWith(expect.objectContaining({ response: '<b>tekst</b>', treatAsPlainText: true }));
  });

  it('labels measured gaps, unknowns, target use and acceptance clearly', () => {
    const candidate = { id: 'c'.repeat(32), attemptNumber: 1, title: 'Tekst', source: 'MANUAL_EXTERNAL_LLM', status: 'OUT_OF_TOLERANCE',
      analysis: { requestedTokenCoveragePercent: 95, tolerancePercentagePoints: 1, length: { actualWords: 390, requestedWords: 400 },
        coverage: { tokenCoveragePercent: 89, uniqueLemmaCoveragePercent: 84 },
        problematicWords: [{ lemma: 'sjeldent', count: 3, unresolved: false }], targetUsage: [{ lemma: 'jobb', count: 0 }] } };
    const handlers = actions();
    renderGenerate(document.querySelector('#mount'), state({ request, contextPack: pack, candidates: [candidate] }), handlers);
    expect(document.body.textContent).toContain('OUT OF TOLERANCE');
    expect(document.body.textContent).toContain('sjeldent ×3');
    expect(document.body.textContent).toContain('jobb: missed');
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Accept despite gap').click();
    expect(handlers.onAccept).toHaveBeenCalledWith(candidate.id);
  });

  it('exposes Read now only for explicitly accepted candidates', () => {
    renderGenerate(document.querySelector('#mount'), state({ request, contextPack: pack, candidates: [{ id: 'c'.repeat(32), attemptNumber: 2, title: 'Accepted', source: 'MANUAL_EXTERNAL_LLM', status: 'ACCEPTED', acceptedTextDocumentId: 't'.repeat(32) }] }), actions());
    expect(document.querySelector('a[href^="#reader/text/"]').textContent).toBe('Read now');
  });

  it('shows persisted automatic progress, cancellation and best-candidate labeling', () => {
    const handlers = actions();
    const automatic = { ...request, generationMode: 'AUTOMATIC', automaticStatus: 'RUNNING', automaticStage: 'GEMINI_ATTEMPT_2_OF_3', automaticProgress: 0.5, maxProviderAttempts: 3 };
    const candidate = { id: 'c'.repeat(32), attemptNumber: 1, title: 'Candidate', source: 'AUTOMATIC_GEMINI', status: 'OUT_OF_TOLERANCE', isBestCandidate: true };
    renderGenerate(document.querySelector('#mount'), state({ request: automatic, contextPack: pack, candidates: [candidate] }), handlers);
    expect(document.body.textContent).toContain('GEMINI ATTEMPT 2 OF 3');
    expect(document.body.textContent).toContain('BEST AVAILABLE');
    expect(document.querySelector('progress').getAttribute('value')).toBe('0.5');
    [...document.querySelectorAll('button')].find((button) => button.textContent.startsWith('Cancel')).click();
    expect(handlers.onCancelAutomatic).toHaveBeenCalledOnce();
  });

  it('maps manual and automatic generation API calls to bounded routes', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, data: {} }) }));
    const api = createLanguageApi({ fetchImpl });
    await api.createGenerationRequest('p', {}); await api.readingSeries('p'); await api.createReadingSeries('p', { title: 'Harbor' }); await api.updateReadingSeries('s', { title: 'Harbor' }); await api.assignTextSeries('t', 's');
    await api.generationProviderHealth(); await api.startAutomaticGeneration('r'); await api.cancelAutomaticGeneration('r'); await api.generationContext('r'); await api.importGenerationCandidate('r', { response: '{}' });
    await api.analyzeGenerationCandidate('c'); await api.generationRevisionPrompt('c'); await api.acceptGenerationCandidate('c'); await api.rejectGenerationCandidate('c');
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/language/profiles/p/generation-requests',
      '/api/language/profiles/p/reading-series', '/api/language/profiles/p/reading-series',
      '/api/language/reading-series/s', '/api/language/texts/t/series',
      '/api/language/generation/provider-health',
      '/api/language/generation-requests/r/automatic', '/api/language/generation-requests/r/cancel',
      '/api/language/generation-requests/r/context-pack',
      '/api/language/generation-requests/r/candidates', '/api/language/generation-candidates/c/analyze',
      '/api/language/generation-candidates/c/revision-prompt', '/api/language/generation-candidates/c/accept',
      '/api/language/generation-candidates/c/reject',
    ]);
  });
});
