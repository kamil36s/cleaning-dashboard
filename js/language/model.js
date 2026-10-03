export const KNOWLEDGE_STATUSES = ['NEW', 'LEARNING', 'KNOWN', 'MASTERED'];
export const DISPOSITIONS = ['TRACKED', 'IGNORED', 'EXCLUDED'];

const KNOWLEDGE_LABELS = {
  NEW: 'New',
  LEARNING: 'Learning',
  KNOWN: 'Known',
  MASTERED: 'Mastered',
};

const DISPOSITION_LABELS = {
  TRACKED: 'Tracked',
  IGNORED: 'Ignored',
  EXCLUDED: 'Excluded',
};

export function knowledgeLabel(value) {
  return KNOWLEDGE_LABELS[value] || value || 'Not set';
}

export function dispositionLabel(value) {
  return DISPOSITION_LABELS[value] || value || 'Not set';
}

export function nullableScore(value) {
  return Number.isInteger(value) && value >= 0 && value <= 5 ? value : null;
}

export function scoreLabel(value) {
  const score = nullableScore(value);
  return score == null ? '—' : `${score}/5`;
}

export function formatLanguageDate(value, locale = 'en-GB') {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function analyzerRuntimeStatus(runtimeState) {
  if (runtimeState === 'PIPELINE_READY') return { label: 'Ready', tone: 'ready' };
  if (runtimeState === 'INSTANCE_CREATED_PIPELINE_LAZY') {
    return { label: 'Lazy · adapter created', tone: 'lazy' };
  }
  if (runtimeState === 'LAZY_NOT_CREATED') return { label: 'Lazy · not loaded', tone: 'lazy' };
  if (runtimeState === 'UNAVAILABLE') return { label: 'Unavailable', tone: 'error' };
  return { label: runtimeState || 'Unknown', tone: 'muted' };
}

export function providerStatus(value) {
  if (value && typeof value === 'object' && value.id) {
    return { label: `${value.id}${value.version ? ` ${value.version}` : ''}`, tone: 'ready' };
  }
  if (value === 'UNSELECTED' || value == null) return { label: 'Not configured', tone: 'muted' };
  if (value === 'UNAVAILABLE') return { label: 'Unavailable', tone: 'error' };
  return { label: String(value), tone: 'info' };
}

export function vocabularyRow(item = {}) {
  return {
    id: item.id || '',
    lemma: item.lemmaDisplay || '—',
    normalized: item.lemmaNormalized || '',
    partOfSpeech: item.partOfSpeech || '—',
    knowledgeStatus: item.knowledgeStatus || 'NEW',
    disposition: item.disposition || 'TRACKED',
    recognition: nullableScore(item.recognition),
    recall: nullableScore(item.recall),
    production: nullableScore(item.production),
    totalExposures: Number.isFinite(Number(item.totalExposures)) ? Number(item.totalExposures) : 0,
    formsCount: Number.isFinite(Number(item.formsCount)) ? Number(item.formsCount) : 0,
    lastSeenAt: item.lastSeenAt || null,
    frequencyScore: item.frequencyScore !== null
      && item.frequencyScore !== undefined
      && Number.isFinite(Number(item.frequencyScore))
      ? Number(item.frequencyScore)
      : null,
    frequencyProviderId: item.frequencyProviderId || null,
  };
}

export function mappingState(mapping = {}) {
  if (mapping.manualLocked) return { label: 'Manual lock', tone: 'ready' };
  if (mapping.ambiguityState === 'AMBIGUOUS') return { label: 'Ambiguous', tone: 'lazy' };
  if (mapping.ambiguityState === 'UNRESOLVED') return { label: 'Unresolved', tone: 'error' };
  if (mapping.mappingProvenance === 'ANALYZER') return { label: 'Analyzer-selected', tone: 'info' };
  return { label: mapping.mappingProvenance || 'Not reported', tone: 'muted' };
}

export function codePointOffsetToUtf16Index(text, offset) {
  const source = String(text ?? '');
  if (!Number.isInteger(offset) || offset < 0) {
    throw new RangeError('Code-point offset must be a non-negative integer');
  }
  let codePointOffset = 0;
  let utf16Index = 0;
  while (utf16Index < source.length && codePointOffset < offset) {
    const codePoint = source.codePointAt(utf16Index);
    utf16Index += codePoint > 0xFFFF ? 2 : 1;
    codePointOffset += 1;
  }
  if (codePointOffset !== offset) throw new RangeError('Code-point offset is outside the string');
  return utf16Index;
}

export function codePointRangeToUtf16Range(text, start, end) {
  if (!Number.isInteger(start) || !Number.isInteger(end) || end < start) {
    throw new RangeError('Code-point range is invalid');
  }
  return {
    start: codePointOffsetToUtf16Index(text, start),
    end: codePointOffsetToUtf16Index(text, end),
  };
}
