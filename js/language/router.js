const SIMPLE_ROUTES = new Set([
  'overview', 'progress', 'benchmarks', 'study-session', 'curriculum', 'inbox', 'reader', 'listening', 'vocabulary', 'phrasebook', 'topics', 'reviews', 'cloze', 'generate', 'statistics', 'goals', 'settings', 'grammar',
]);

function cleanHash(value) {
  return String(value ?? '')
    .trim()
    .replace(/^#/, '')
    .replace(/^\/+|\/+$/g, '');
}

export function parseLanguageRoute(hash) {
  const raw = cleanHash(hash);
  if (!raw) return { name: 'overview', valid: true };
  if (SIMPLE_ROUTES.has(raw)) return { name: raw, valid: true };

  const parts = raw.split('/');
  if (parts.length === 3 && parts[0] === 'benchmarks' && parts[1] === 'run' && /^[a-f0-9]{32}$/.test(parts[2])) {
    return { name: 'benchmarkRun', runId: parts[2], valid: true };
  }
  if (parts.length === 3 && parts[0] === 'grammar' && parts[1] === 'pattern' && /^[A-Z0-9_]+$/.test(parts[2])) {
    return { name: 'grammarPattern', patternId: parts[2], valid: true };
  }
  if (parts.length === 5 && parts[0] === 'reader' && parts[1] === 'text' && parts[3] === 'sentence' && /^[a-f0-9]{32}$/.test(parts[2]) && /^[a-f0-9]{32}$/.test(parts[4])) {
    return { name: 'readerText', textId: parts[2], sentenceId: parts[4], valid: true };
  }
  if (parts.length === 4 && parts[0] === 'curriculum' && parts[2] === 'v' && /^\d+$/.test(parts[3])) {
    try {
      const packId = decodeURIComponent(parts[1]);
      if (packId && !/[/?#]/.test(packId)) {
        return { name: 'curriculumPack', packId, version: Number(parts[3]), valid: true };
      }
    } catch {
      // Invalid percent encoding is an invalid route.
    }
  }
  if (parts.length === 3 && parts[0] === 'vocabulary' && parts[1] === 'lemma') {
    try {
      const lemmaId = decodeURIComponent(parts[2]);
      if (lemmaId && !/[/?#]/.test(lemmaId)) {
        return { name: 'lemma', lemmaId, valid: true };
      }
    } catch {
      // Invalid percent encoding is an invalid route, not an application error.
    }
  }

  if (parts.length === 3 && parts[0] === 'reader' && parts[1] === 'text') {
    try {
      const textId = decodeURIComponent(parts[2]);
      if (textId && !/[/?#]/.test(textId)) {
        return { name: 'readerText', textId, valid: true };
      }
    } catch {
      // Invalid percent encoding is an invalid route.
    }
  }

  if (parts.length === 3 && parts[0] === 'listening' && parts[1] === 'text') {
    try {
      const textId = decodeURIComponent(parts[2]);
      if (textId && !/[/?#]/.test(textId)) {
        return { name: 'listeningText', textId, valid: true };
      }
    } catch {
      // Invalid percent encoding is an invalid route.
    }
  }
  if (parts.length === 3 && parts[0] === 'inbox' && parts[1] === 'content') {
    try {
      const contentId = decodeURIComponent(parts[2]);
      if (contentId && !/[/?#]/.test(contentId)) return { name: 'inboxContent', contentId, valid: true };
    } catch { /* invalid route */ }
  }
  if (parts.length === 3 && parts[0] === 'listening' && parts[1] === 'content') {
    try {
      const contentId = decodeURIComponent(parts[2]);
      if (contentId && !/[/?#]/.test(contentId)) return { name: 'listeningContent', contentId, valid: true };
    } catch { /* invalid route */ }
  }

  return { name: 'overview', valid: false, invalidHash: raw };
}

export function formatLanguageRoute(route) {
  const name = typeof route === 'string' ? route : route?.name;
  if (SIMPLE_ROUTES.has(name)) return `#${name}`;
  if (name === 'benchmarkRun' && /^[a-f0-9]{32}$/.test(route?.runId || '')) return `#benchmarks/run/${route.runId}`;
  if (name === 'grammarPattern' && route?.patternId) return `#grammar/pattern/${encodeURIComponent(route.patternId)}`;
  if (name === 'lemma' && route?.lemmaId) {
    return `#vocabulary/lemma/${encodeURIComponent(String(route.lemmaId))}`;
  }
  if (name === 'readerText' && route?.textId) {
    return `#reader/text/${encodeURIComponent(String(route.textId))}${route.sentenceId ? `/sentence/${encodeURIComponent(route.sentenceId)}` : ''}`;
  }
  if (name === 'listeningText' && route?.textId) {
    return `#listening/text/${encodeURIComponent(String(route.textId))}`;
  }
  if (name === 'inboxContent' && route?.contentId) return `#inbox/content/${encodeURIComponent(String(route.contentId))}`;
  if (name === 'listeningContent' && route?.contentId) return `#listening/content/${encodeURIComponent(String(route.contentId))}`;
  if (name === 'curriculumPack' && route?.packId && Number.isInteger(Number(route?.version))) {
    return `#curriculum/${encodeURIComponent(String(route.packId))}/v/${Number(route.version)}`;
  }
  return '#overview';
}

export function routeSection(route) {
  if (route?.name === 'grammarPattern') return 'grammar';
  if (route?.name === 'benchmarkRun') return 'benchmarks';
  if (route?.name === 'lemma') return 'vocabulary';
  if (route?.name === 'readerText') return 'reader';
  if (route?.name === 'listeningText') return 'listening';
  if (route?.name === 'inboxContent') return 'inbox';
  if (route?.name === 'listeningContent') return 'listening';
  if (route?.name === 'curriculumPack') return 'curriculum';
  return route?.name || 'overview';
}

export function routeHeading(route) {
  return {
    grammar: 'Grammar',
    grammarPattern: 'Grammar',
    overview: 'Today',
    progress: 'Progress',
    benchmarks: 'Benchmarks',
    'study-session': 'Study Session',
    benchmarkRun: 'Benchmarks',
    curriculum: 'Curriculum',
    curriculumPack: 'Curriculum',
    reader: 'Reader',
    readerText: 'Reader',
    listening: 'Listening',
    listeningText: 'Listening',
    inbox: 'Content Inbox',
    inboxContent: 'Content Inbox',
    listeningContent: 'Authentic Listening',
    vocabulary: 'Vocabulary',
    phrasebook: 'Phrasebook',
    lemma: 'Vocabulary',
    settings: 'Settings',
    topics: 'Topics',
    statistics: 'Statistics',
    goals: 'Goals',
    reviews: 'Reviews',
    cloze: 'Cloze',
    generate: 'Generate',
  }[route?.name] || 'Overview';
}
