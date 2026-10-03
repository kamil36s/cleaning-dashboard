import { describe, expect, it } from 'vitest';
import {
  analyzerRuntimeStatus,
  codePointOffsetToUtf16Index,
  codePointRangeToUtf16Range,
  dispositionLabel,
  knowledgeLabel,
  mappingState,
  providerStatus,
  scoreLabel,
  vocabularyRow,
} from '../js/language/model.js';

describe('Language client model', () => {
  it('labels canonical knowledge and disposition enums', () => {
    expect(knowledgeLabel('LEARNING')).toBe('Learning');
    expect(dispositionLabel('IGNORED')).toBe('Ignored');
    expect(knowledgeLabel(null)).toBe('Not set');
  });

  it('handles scores and missing vocabulary values safely', () => {
    expect(scoreLabel(0)).toBe('0/5');
    expect(scoreLabel(null)).toBe('—');
    expect(vocabularyRow({ lemmaDisplay: null, totalExposures: null, frequencyScore: null })).toMatchObject({
      lemma: '—', totalExposures: 0, recognition: null, frequencyScore: null,
    });
  });

  it('preserves truthful provider and analyzer health distinctions', () => {
    expect(analyzerRuntimeStatus('LAZY_NOT_CREATED')).toEqual({ label: 'Lazy · not loaded', tone: 'lazy' });
    expect(analyzerRuntimeStatus('UNAVAILABLE').tone).toBe('error');
    expect(providerStatus('UNSELECTED')).toEqual({ label: 'Not configured', tone: 'muted' });
    expect(providerStatus({ id: 'wordfreq', version: '3.1.1' }).label).toBe('wordfreq 3.1.1');
  });

  it('distinguishes manual, analyzer, ambiguous, and unresolved mappings', () => {
    expect(mappingState({ manualLocked: true }).label).toBe('Manual lock');
    expect(mappingState({ ambiguityState: 'AMBIGUOUS' }).label).toBe('Ambiguous');
    expect(mappingState({ ambiguityState: 'UNRESOLVED' }).label).toBe('Unresolved');
    expect(mappingState({ mappingProvenance: 'ANALYZER' }).label).toBe('Analyzer-selected');
  });
});

describe('Unicode code-point to UTF-16 conversion', () => {
  it('keeps ASCII offsets unchanged including end-of-string', () => {
    expect(codePointOffsetToUtf16Index('jobb', 0)).toBe(0);
    expect(codePointOffsetToUtf16Index('jobb', 4)).toBe(4);
  });

  it('keeps Norwegian BMP letters aligned', () => {
    const text = 'æøå jobb';
    expect(codePointOffsetToUtf16Index(text, 4)).toBe(4);
    expect(codePointRangeToUtf16Range(text, 4, 8)).toEqual({ start: 4, end: 8 });
  });

  it('accounts for one emoji before a token', () => {
    expect(codePointRangeToUtf16Range('😊jobb', 1, 5)).toEqual({ start: 2, end: 6 });
  });

  it('accounts for multiple emoji and non-BMP characters', () => {
    const text = '😊𐐷åx';
    expect(codePointOffsetToUtf16Index(text, 2)).toBe(4);
    expect(codePointRangeToUtf16Range(text, 2, 4)).toEqual({ start: 4, end: 6 });
  });

  it('supports empty and end boundary ranges', () => {
    expect(codePointRangeToUtf16Range('😊x', 0, 0)).toEqual({ start: 0, end: 0 });
    expect(codePointRangeToUtf16Range('😊x', 2, 2)).toEqual({ start: 3, end: 3 });
  });

  it('rejects invalid offsets and reversed ranges', () => {
    expect(() => codePointOffsetToUtf16Index('x', 2)).toThrow(RangeError);
    expect(() => codePointOffsetToUtf16Index('x', 0.5)).toThrow(RangeError);
    expect(() => codePointRangeToUtf16Range('x', 1, 0)).toThrow(RangeError);
  });
});
