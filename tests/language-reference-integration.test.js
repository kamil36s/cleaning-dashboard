import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createLanguageApi } from '../js/language/api.js';
import { renderLemmaDetail } from '../js/language/components/lemma-detail.js';
import { renderReaderDocument } from '../js/language/views/reader.js';
import { renderGenerate } from '../js/language/views/generate.js';

function detail(reference, resolution) {
  return {
    lemma: { id: 'l'.repeat(32), lemmaDisplay: 'jobb', lemmaNormalized: 'jobb', partOfSpeech: 'NOUN', userNotes: null },
    knowledge: { knowledgeStatus: 'NEW', disposition: 'TRACKED', totalExposures: 0 },
    forms: [], frequencies: [], events: [], anki: { status: { status: 'NOT_CONFIGURED' }, cards: [] },
    reference, referenceResolution: resolution,
  };
}

const handlers = {
  onSave: vi.fn(), onSearchMerge: vi.fn(async () => []), onPrepareMerge: vi.fn(),
  onAnkiPreview: vi.fn(), onAnkiCommit: vi.fn(), onAnkiLink: vi.fn(), onAnkiResolve: vi.fn(),
};

describe('Language Phase 7.5C reference integration', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="mount"></main>'; });
  afterEach(() => { vi.restoreAllMocks(); document.body.replaceChildren(); });

  it('renders matched source-specific evidence separately from user knowledge', () => {
    renderLemmaDetail(document.querySelector('#mount'), detail({
      available: true,
      unit: { canonicalForm: 'jobb', partOfSpeech: 'NOUN', stableKey: 'reference-key/v1|jobb' },
      frequencyEvidence: [
        { label: 'Learner rank', metricType: 'SOURCE_LEARNER_RANK', rank: 220, sourceName: 'KELLY', sourceId: 'kelly', sourceVersion: '1', scope: 'REFERENCE_UNIT' },
        { label: 'Source form rank', metricType: 'SOURCE_FORM_RANK', rank: 90, sourceName: 'CLARINO', sourceId: 'clarino', sourceVersion: '2025', scope: 'SOURCE_SURFACE_FORM' },
        { label: 'Derived lemma rank', metricType: 'DERIVED_LEMMA_RANK', rank: 111, sourceName: 'CLARINO', sourceId: 'clarino', sourceVersion: '2025', scope: 'DERIVED_LEMMA', methodVersion: 'clarino-derived/v1' },
        { label: 'Zipf estimate', metricType: 'ZIPF_FREQUENCY', zipfScore: 5.2, sourceName: 'wordfreq', sourceId: 'wordfreq', sourceVersion: '3', scope: 'REFERENCE_UNIT' },
      ],
      forms: [{ displayForm: 'jobben', morphology: { Definite: 'Def' } }],
      expressions: [{ canonicalForm: 'gjøre en jobb', unitType: 'PHRASE' }],
      sources: [{ name: 'Norsk ordbank', provider: 'NB', version: '2022', license: 'CC BY 4.0' }],
      cefrAvailable: false,
    }, { status: 'MATCHED', ruleVersion: 'reference-resolver/v1', candidates: [] }), handlers);
    expect(document.body.textContent).toContain('USER KNOWLEDGE');
    expect(document.body.textContent).toContain('REFERENCE · READ ONLY');
    expect(document.body.textContent).toContain('Learner rank');
    expect(document.body.textContent).toContain('Source form rank');
    expect(document.body.textContent).toContain('Derived lemma rank');
    expect(document.body.textContent).toContain('Zipf estimate');
    expect(document.body.textContent).toContain('CEFRNot available');
  });

  it.each([
    ['AMBIGUOUS', [{ canonicalForm: 'så', partOfSpeech: 'ADV', stableKey: 'one', matchBasis: 'LANGUAGE_LEMMA_POS_REQUIRED' }], 'Reference candidate'],
    ['UNMATCHED', [], 'No exact reference candidate was found'],
    ['UNAVAILABLE', [], 'Reference data is unavailable'],
  ])('renders %s without silently selecting a homograph', (status, candidates, expected) => {
    renderLemmaDetail(document.querySelector('#mount'), detail(
      { available: status !== 'UNAVAILABLE' },
      { status, ruleVersion: 'reference-resolver/v1', candidates },
    ), handlers);
    expect(document.body.textContent).toContain(status);
    expect(document.body.textContent).toContain(expected);
  });

  it('annotates exact Reader tokens subtly and keeps the reference profile separate from coverage', () => {
    const rawText = 'ugler i mosen';
    const tokens = [
      ['u', 'ugler', 0, 5], ['i', 'i', 6, 7], ['m', 'mosen', 8, 13],
    ].map(([id, surface, sourceStart, sourceEnd], tokenOrder) => ({
      id, sentenceId: 's', tokenOrder, surface, sourceStart, sourceEnd, tokenKind: 'WORD',
      selectedLemmaId: id.repeat(32).slice(0, 32), selectedLemmaDisplay: surface,
      knowledgeStatus: 'NEW', disposition: 'TRACKED', resolutionState: 'MODEL_SELECTED',
    }));
    const expression = {
      referenceLexicalUnitKey: 'idiom', canonicalForm: 'ugler i mosen', unitType: 'IDIOM',
      sentenceId: 's', startToken: 'u', endToken: 'm', startTokenOrder: 0, endTokenOrder: 2,
      exactSourceSpan: { start: 0, end: 13 }, surfaceText: rawText,
      matchBasis: ['LEMMA_CONSTRAINT', 'SURFACE_CONSTRAINT', 'LEMMA_CONSTRAINT'],
      ambiguous: false, detectorVersion: 'language.reference-expression-detection/v1',
      selectionState: 'LONGEST_PREFERRED', sourceProvenance: [{ name: 'Norske idiomer', version: '1' }],
    };
    renderReaderDocument(document.querySelector('#mount'), {
      document: { title: '<unsafe>', rawText, sourceType: 'PASTED', processingState: 'ANALYZED' },
      sentences: [{ id: 's', sentenceOrder: 0, sourceStart: 0, sourceEnd: 13 }], tokens,
      coverage: { tokenCoveragePercent: 0, uniqueLemmaCoveragePercent: 0 }, analysisRuns: [],
      referenceProfile: {
        available: true, resolutionSummary: { matched: 1, ambiguous: 0, unmatched: 2 },
        frequencyProfile: { learnerRankAvailable: false }, expressions: [expression],
        idiomOccurrences: 1, mweOccurrences: 1, cefr: { available: false },
      },
    }, { onOpenLemma: vi.fn(), onAnalyze: vi.fn(), onStart: vi.fn(), onPause: vi.fn(), onComplete: vi.fn() });
    expect(document.querySelectorAll('.has-reference-expression')).toHaveLength(3);
    expect(document.body.textContent).toContain('REFERENCE PROFILE · NOT USER COVERAGE');
    expect(document.body.textContent).toContain('USER VOCABULARY COVERAGE');
    expect(document.body.textContent).toContain('ugler i mosen');
    expect(document.querySelector('script')).toBeNull();
  });

  it('shows a bounded generator v2 fingerprint and safe reference copy action', () => {
    const actions = { onCreate: vi.fn(), onCopy: vi.fn(), onExport: vi.fn(), onImport: vi.fn(), onAnalyze: vi.fn(), onRevision: vi.fn(), onAccept: vi.fn(), onReject: vi.fn() };
    const facts = { formatVersion: 'language-generation-reference-facts/v1', items: [{ userLemmaId: 'lemma' }] };
    renderGenerate(document.querySelector('#mount'), {
      busy: false, error: null, notice: '', topics: [], candidates: [],
      form: { length: 200, difficultyPreset: 'BALANCED', targetCoverage: 95, referenceEnrichment: true },
      request: { id: 'r' }, contextPack: { formatVersion: 'language-generation-context/v2', estimatedCharacterCount: 800, files: {
        'prompt.md': 'prompt', 'known-vocabulary.txt': 'jobb', 'focus-vocabulary.json': {},
        'reference-facts.json': facts,
        'metadata.json': { knownVocabularyIncluded: 1, focusVocabularyCount: 1, referenceEnrichment: { enabled: true, schemaVersion: 3, referenceFingerprint: 'sha256:test' } },
      } },
    }, actions);
    expect(document.querySelector('.language-reference-toggle input').checked).toBe(true);
    expect(document.body.textContent).toContain('Reference v2 · schema 3 · frozen fingerprint sha256:test');
    const copy = [...document.querySelectorAll('button')].find((button) => button.textContent === 'Copy reference facts');
    copy.click();
    expect(actions.onCopy).toHaveBeenCalledWith(JSON.stringify(facts, null, 2));
  });

  it('maps the three thin read-only reference API routes', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, data: {} }) }));
    const api = createLanguageApi({ fetchImpl });
    await api.referenceHealth();
    await api.lemmaReference('lemma');
    await api.textReferenceProfile('text');
    expect(fetchImpl.mock.calls.map(([url, options]) => [url, options.method])).toEqual([
      ['/api/language/reference/health', 'GET'],
      ['/api/language/lemmas/lemma/reference', 'GET'],
      ['/api/language/texts/text/reference-profile', 'GET'],
    ]);
  });

  it('keeps narrow reference panels wrap-safe at the 430px breakpoint', () => {
    const css = readFileSync(resolve(process.cwd(), 'language.css'), 'utf8');
    expect(css).toContain('.language-reference-section');
    expect(css).toContain('overflow-wrap: anywhere');
    expect(css).toMatch(/@media\s*\(max-width:\s*700px\)/);
    expect(css).toContain('.language-reference-row span { text-align: left; }');
  });
});
