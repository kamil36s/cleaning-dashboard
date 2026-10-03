import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderGrammar, mountReaderGrammar } from '../js/language/views/grammar.js';
import { createLanguageApi } from '../js/language/api.js';
import { parseLanguageRoute, formatLanguageRoute, routeSection } from '../js/language/router.js';

const pattern = { patternId: 'A1_PRESENT_TENSE', name: 'Present tense', bucket: 'A1', status: 'SUPPORTED', state: 'DISCOVERED', explanation: 'Finite present verbs.', detectorId: 'nb.present', detectorVersion: '1.0.0', patternVersion: '1.0.0', rule: 'Finite morphology', limitations: 'Parser hypotheses', occurrenceCount: 1, authoritativeCount: 1 };
const example = { id: 'a'.repeat(32), textDocumentId: 'b'.repeat(32), sentenceId: 'c'.repeat(32), title: '<script>source</script>', exactText: '😊 Jeg jobber.', sentenceStart: 0, sourceStart: 6, sourceEnd: 12, state: 'DISCOVERED', sourceProvenance: { kind: 'TRANSCRIPT' }, reviewState: 'UNREVIEWED', evidence: { FINITE_VERB: { tokenId: 'token', start: 6, end: 12, morphology: { Tense: 'Pres' }, relation: 'root' } } };
function mount() { const el = document.createElement('section'); document.body.append(el); return el; }
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };
afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); });

describe('Grammar', () => {
  it('supports catalogue, pattern and exact Reader sentence routes', () => {
    expect(parseLanguageRoute('#grammar').name).toBe('grammar');
    const route = { name: 'grammarPattern', patternId: pattern.patternId };
    expect(parseLanguageRoute(formatLanguageRoute(route))).toEqual({ ...route, valid: true });
    expect(routeSection(route)).toBe('grammar');
    const reader = { name: 'readerText', textId: example.textDocumentId, sentenceId: example.sentenceId };
    expect(parseLanguageRoute(formatLanguageRoute(reader))).toEqual({ ...reader, valid: true });
  });
  it('groups all practical buckets and shows truthful deferred and unavailable states', () => {
    const el = mount();
    renderGrammar(el, { parser: { state: 'UNAVAILABLE', reason: 'MODEL_NOT_PROVISIONED' }, items: [pattern, { ...pattern, bucket: 'A2', status: 'EXPERIMENTAL' }, { ...pattern, bucket: 'B1', status: 'DEFERRED' }] });
    for (const text of ['A1 practical', 'A2 practical', 'B1 practical', 'SUPPORTED', 'EXPERIMENTAL', 'DEFERRED', 'MODEL_NOT_PROVISIONED', 'not certified CEFR']) expect(el.textContent).toContain(text);
  });
  it('renders exact Unicode evidence safely and provides source navigation', () => {
    const el = mount(); renderGrammar(el, { pattern, examples: [example] });
    expect(el.querySelector('mark').textContent).toBe('jobber');
    expect(el.querySelector('script')).toBeNull();
    expect(el.textContent).toContain('TRANSCRIPT');
    expect([...el.querySelectorAll('details')].some((item) => item.textContent.includes('FINITE_VERB'))).toBe(true);
    expect(el.querySelector(`a[href="#reader/text/${example.textDocumentId}/sentence/${example.sentenceId}"]`)).not.toBeNull();
  });
  it('confirms and rejects detector quality with semantic buttons and live status', async () => {
    const el = mount(); const onReview = vi.fn().mockResolvedValue({}); renderGrammar(el, { pattern, examples: [example] }, { onReview });
    const buttons = el.querySelectorAll('button'); buttons[0].focus(); expect(document.activeElement).toBe(buttons[0]); buttons[0].click(); await tick();
    expect(onReview).toHaveBeenCalledWith(example.id, 'CONFIRMED');
    buttons[1].click(); await tick(); expect(onReview).toHaveBeenCalledWith(example.id, 'REJECTED');
    expect(el.querySelector('[role="status"]').textContent).toContain('REJECTED');
  });
  it.each(['READER', 'AUTHENTIC', 'TRANSCRIPT', 'GENERATED'])('retains %s source label', (kind) => {
    const el = mount(); renderGrammar(el, { pattern, examples: [{ ...example, sourceProvenance: { kind } }] }); expect(el.textContent).toContain(kind);
  });
  it('Reader grammar is explicit, polls pending jobs and displays failure', async () => {
    vi.useFakeTimers(); const el = mount();
    const api = { textGrammar: vi.fn().mockResolvedValueOnce({ status: 'NOT_ANALYZED', parser: { state: 'AVAILABLE' } }).mockResolvedValueOnce({ status: 'RUNNING', parser: { state: 'AVAILABLE' } }).mockResolvedValue({ status: 'FAILED', parser: { state: 'AVAILABLE' }, job: { errorMessage: 'TOKEN_MAPPING_DIVERGED' } }), analyzeGrammar: vi.fn().mockResolvedValue({}) };
    const cleanup = mountReaderGrammar(el, { api, textId: 'text', profileId: 'profile' }); await tick();
    expect(api.analyzeGrammar).not.toHaveBeenCalled(); el.querySelector('button').click(); await tick(); expect(el.textContent).toContain('RUNNING');
    await vi.advanceTimersByTimeAsync(1000); expect(el.textContent).toContain('TOKEN_MAPPING_DIVERGED'); cleanup();
  });
  it('disables unavailable parser and ignores late work after route teardown', async () => {
    const el = mount(); const api = { textGrammar: vi.fn().mockResolvedValue({ status: 'NOT_ANALYZED', parser: { state: 'UNAVAILABLE', reason: 'MODEL_NOT_PROVISIONED' } }) };
    const cleanup = mountReaderGrammar(el, { api, textId: 'text', profileId: 'profile' }); await tick(); expect(el.querySelector('button').disabled).toBe(true); expect(el.textContent).toContain('MODEL_NOT_PROVISIONED'); cleanup();
  });
  it('uses profile scoped HTTP routes and only backend detector commands', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: {} }) }); const api = createLanguageApi({ fetchImpl });
    await api.grammar('p'); await api.grammarPattern('p','A1_PRESENT_TENSE'); await api.textGrammar('t','p'); await api.analyzeGrammar('t','p'); await api.reviewGrammar('o','p','CONFIRMED');
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual(['/api/language/profiles/p/grammar','/api/language/profiles/p/grammar/patterns/A1_PRESENT_TENSE','/api/language/texts/t/grammar?profileId=p','/api/language/texts/t/grammar-analysis','/api/language/grammar/occurrences/o/review']);
    expect(JSON.parse(fetchImpl.mock.calls[4][1].body)).toEqual({ languageProfileId: 'p', decision: 'CONFIRMED' });
  });
});
