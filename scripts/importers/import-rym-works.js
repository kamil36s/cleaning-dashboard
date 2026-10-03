import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import {
  cleanText,
  normalizeTitle,
  parseRymWorksFile,
  slugPart,
} from './parse-rym-works.js';

const USER_PROGRESS_FIELDS = new Set([
  'status',
  'reaction',
  'notes',
  'hidden',
  'listenedAt',
  'rating',
  'userMetadataOverrides',
]);

const TITLE_WORD_MAP = new Map(Object.entries({
  variations: 'variation',
  variaciones: 'variation',
  variacions: 'variation',
  variation: 'variation',
  theme: 'theme',
  tema: 'theme',
  musica: 'music',
  musicae: 'music',
  music: 'music',
  callada: 'callada',
  silenciosa: 'callada',
  canciones: 'song',
  cancons: 'song',
  cancoes: 'song',
  songs: 'song',
  danses: 'dance',
  danzas: 'dance',
  dances: 'dance',
  combat: 'combat',
  combattimento: 'combat',
}));

const TITLE_STOPWORDS = new Set([
  'a',
  'an',
  'and',
  'de',
  'del',
  'dels',
  'des',
  'du',
  'el',
  'en',
  'for',
  'i',
  'la',
  'las',
  'le',
  'les',
  'l',
  'los',
  'no',
  'of',
  'on',
  'op',
  'sobre',
  'sur',
  'the',
  'un',
  'una',
  'y',
]);

function parseCliArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
    } else {
      args[key] = next;
      index += 1;
    }
  }
  return args;
}

function requireArg(args, name) {
  const value = args[name];
  if (!value || value === true) {
    throw new Error(`Missing --${name}.`);
  }
  return String(value);
}

function composerTitleKey(composerId, title) {
  return `${slugPart(composerId)}::${normalizeTitle(title)}`;
}

function titleTokens(title) {
  return normalizeTitle(title)
    .split(' ')
    .filter(Boolean)
    .map((token) => TITLE_WORD_MAP.get(token) || token)
    .filter((token) => token && !TITLE_STOPWORDS.has(token));
}

function titleSignature(title) {
  return Array.from(new Set(titleTokens(title))).sort().join(' ');
}

function tokenSimilarity(leftTitle, rightTitle) {
  const left = new Set(titleTokens(leftTitle));
  const right = new Set(titleTokens(rightTitle));
  if (!left.size || !right.size) return 0;
  const intersection = Array.from(left).filter((token) => right.has(token)).length;
  const union = new Set([...left, ...right]).size;
  return intersection / union;
}

function levenshtein(left, right) {
  const a = normalizeTitle(left);
  const b = normalizeTitle(right);
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  const previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  const current = Array.from({ length: b.length + 1 }, () => 0);

  for (let i = 1; i <= a.length; i += 1) {
    current[0] = i;
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      current[j] = Math.min(
        current[j - 1] + 1,
        previous[j] + 1,
        previous[j - 1] + cost,
      );
    }
    for (let j = 0; j <= b.length; j += 1) previous[j] = current[j];
  }

  return previous[b.length];
}

function normalizedSimilarity(left, right) {
  const maxLength = Math.max(normalizeTitle(left).length, normalizeTitle(right).length, 1);
  return 1 - (levenshtein(left, right) / maxLength);
}

function fuzzyReason(importedTitle, existingTitle) {
  const importedSignature = titleSignature(importedTitle);
  const existingSignature = titleSignature(existingTitle);
  if (importedSignature && importedSignature === existingSignature) {
    return `shared title signature "${importedSignature}"`;
  }
  const tokenScore = tokenSimilarity(importedTitle, existingTitle);
  if (tokenScore >= 0.67) return `token similarity ${tokenScore.toFixed(2)}`;
  const textScore = normalizedSimilarity(importedTitle, existingTitle);
  if (textScore >= 0.86) return `text similarity ${textScore.toFixed(2)}`;
  return '';
}

function findFuzzyMatches(importedWork, existingWorks) {
  return existingWorks
    .map((existingWork) => ({
      imported: importedWork,
      existing: existingWork,
      reason: fuzzyReason(importedWork.title, existingWork.title),
    }))
    .filter((match) => match.reason)
    .sort((a, b) => {
      const byToken = tokenSimilarity(b.imported.title, b.existing.title) - tokenSimilarity(a.imported.title, a.existing.title);
      if (byToken) return byToken;
      return normalizedSimilarity(b.imported.title, b.existing.title) - normalizedSimilarity(a.imported.title, a.existing.title);
    });
}

function flattenWorks(works, out = []) {
  (Array.isArray(works) ? works : []).forEach((work) => {
    if (!work || typeof work !== 'object') return;
    out.push(work);
    flattenWorks(work.parts || [], out);
  });
  return out;
}

function ensureUniqueWorkId(work, reservedIds) {
  const base = work.workId || work.id;
  let candidate = base;
  let suffix = 2;
  while (reservedIds.has(candidate)) {
    candidate = `${base}-${suffix}`;
    suffix += 1;
  }
  reservedIds.add(candidate);
  return { ...work, id: candidate, workId: candidate };
}

function isSameSource(left, right) {
  return cleanText(left?.url) && cleanText(left?.url) === cleanText(right?.url);
}

function mergeSourceMetadata(existingWork, importedWork) {
  let changed = false;
  const next = { ...existingWork };
  for (const field of ['sourceOrder', 'sourceRole', 'sourceUrl', 'source', 'sourceCategory']) {
    if ((next[field] === undefined || next[field] === null || next[field] === '') && importedWork[field]) {
      next[field] = importedWork[field];
      changed = true;
    }
  }

  const importedSource = Array.isArray(importedWork.sources) ? importedWork.sources[0] : null;
  if (importedSource) {
    const currentSources = Array.isArray(next.sources) ? next.sources : [];
    if (!currentSources.some((source) => isSameSource(source, importedSource))) {
      next.sources = [...currentSources, importedSource];
      changed = true;
    }
  }

  for (const field of USER_PROGRESS_FIELDS) {
    if (Object.hasOwn(existingWork, field)) {
      next[field] = existingWork[field];
    }
  }

  return { work: next, changed };
}

function replaceWorkById(works, workId, replacement) {
  return (Array.isArray(works) ? works : []).map((work) => {
    if (!work || typeof work !== 'object') return work;
    if (work.workId === workId || work.id === workId) return replacement;
    if (Array.isArray(work.parts) && work.parts.length) {
      return { ...work, parts: replaceWorkById(work.parts, workId, replacement) };
    }
    return work;
  });
}

function readComposerFromData(data, composerId) {
  if (Array.isArray(data)) {
    return data.find((composer) => composer?.composerId === composerId) || null;
  }
  if (Array.isArray(data?.composers)) {
    return data.composers.find((composer) => composer?.composerId === composerId) || null;
  }
  if (data?.composerId === composerId) return data;
  return null;
}

function replaceComposerInData(data, composer) {
  if (Array.isArray(data)) {
    return data.map((item) => (item?.composerId === composer.composerId ? composer : item));
  }
  if (Array.isArray(data?.composers)) {
    return {
      ...data,
      composers: data.composers.map((item) => (item?.composerId === composer.composerId ? composer : item)),
    };
  }
  return composer;
}

async function readJsonData(dataPath) {
  let raw;
  try {
    raw = await readFile(dataPath, 'utf8');
  } catch (error) {
    throw new Error(`Could not read data file: ${dataPath}. ${error.message}`);
  }

  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new Error(`Data file cannot be parsed as JSON: ${dataPath}. ${error.message}`);
  }
}

function classifyImport({ composer, importedWorks }) {
  const existingWorks = flattenWorks(composer.works || []);
  const exactByKey = new Map();
  existingWorks.forEach((work) => {
    exactByKey.set(composerTitleKey(composer.composerId, work.title), work);
  });

  const reservedIds = new Set(existingWorks.flatMap((work) => [work.id, work.workId].filter(Boolean)));
  const seenSourceKeys = new Set();
  const exactMatches = [];
  const fuzzyMatches = [];
  const sourceDuplicates = [];
  const newWorks = [];

  importedWorks.forEach((work) => {
    const key = composerTitleKey(work.composerId, work.title);
    const exact = exactByKey.get(key);
    if (exact) {
      exactMatches.push({ imported: work, existing: exact });
      return;
    }

    if (seenSourceKeys.has(key)) {
      sourceDuplicates.push(work);
      return;
    }
    seenSourceKeys.add(key);

    const fuzzy = findFuzzyMatches(work, existingWorks);
    if (fuzzy.length) {
      fuzzyMatches.push(fuzzy[0]);
      return;
    }

    newWorks.push(ensureUniqueWorkId(work, reservedIds));
  });

  return {
    extracted: importedWorks,
    exactMatches,
    fuzzyMatches,
    sourceDuplicates,
    newWorks,
    manualReviewWorks: [
      ...fuzzyMatches.map((match) => match.imported),
      ...sourceDuplicates,
      ...newWorks.filter((work) => work.needsReview),
    ],
  };
}

function groupCatalogue(importedWorks) {
  const byCategory = new Map();
  importedWorks.forEach((work) => {
    const name = work.category || 'Other';
    byCategory.set(name, (byCategory.get(name) || 0) + 1);
  });
  return Array.from(byCategory.entries()).map(([name, count], index) => ({
    name,
    order: index + 1,
    count,
  }));
}

function applyImport({ composer, importedWorks, classification }) {
  let nextComposer = {
    ...composer,
    works: Array.isArray(composer.works) ? composer.works.slice() : [],
  };
  let sourceMetadataUpdated = 0;

  classification.exactMatches.forEach(({ imported, existing }) => {
    const { work, changed } = mergeSourceMetadata(existing, imported);
    if (!changed) return;
    nextComposer.works = replaceWorkById(nextComposer.works, existing.workId || existing.id, work);
    sourceMetadataUpdated += 1;
  });

  nextComposer.works = [...nextComposer.works, ...classification.newWorks];
  nextComposer.sourceCatalogue = {
    ...(nextComposer.sourceCatalogue || {}),
    provider: 'Rate Your Music',
    source: 'rym-saved-html',
    grouping: 'work type',
    groups: groupCatalogue(importedWorks),
  };
  const composerSources = Array.isArray(nextComposer.sources) ? nextComposer.sources.slice() : [];
  const rymSource = {
    name: 'Rate Your Music saved HTML Works table',
    url: '',
    notes: `Imported from saved RYM HTML. Added ${classification.newWorks.length} works; skipped ${classification.fuzzyMatches.length} fuzzy matches for manual review.`,
  };
  const existingRymSourceIndex = composerSources.findIndex((source) => source?.name === rymSource.name);
  if (existingRymSourceIndex >= 0) {
    composerSources[existingRymSourceIndex] = {
      ...composerSources[existingRymSourceIndex],
      ...rymSource,
    };
  } else {
    composerSources.push(rymSource);
  }
  nextComposer.sources = composerSources;
  nextComposer.updatedAt = new Date().toISOString();
  nextComposer.lastImportStatus = {
    kind: 'rym-saved-html',
    updatedAt: nextComposer.updatedAt,
    message: `Extracted ${classification.extracted.length} RYM works; added ${classification.newWorks.length}; exact matches ${classification.exactMatches.length}; fuzzy matches ${classification.fuzzyMatches.length}; source duplicates ${classification.sourceDuplicates.length}.`,
  };

  return { composer: nextComposer, sourceMetadataUpdated };
}

function formatList(items, formatter, limit = 20) {
  if (!items.length) return '  (none)';
  const lines = items.slice(0, limit).map((item) => `  - ${formatter(item)}`);
  if (items.length > limit) lines.push(`  ... ${items.length - limit} more`);
  return lines.join('\n');
}

function printPreview(classification) {
  console.log(`Works extracted: ${classification.extracted.length}`);
  console.log(`Exact matches: ${classification.exactMatches.length}`);
  console.log(formatList(
    classification.exactMatches,
    ({ imported, existing }) => `${imported.title} -> ${existing.title} (${existing.workId || existing.id})`,
  ));
  console.log(`Possible fuzzy matches: ${classification.fuzzyMatches.length}`);
  console.log(formatList(
    classification.fuzzyMatches,
    ({ imported, existing, reason }) => `${imported.title} -> ${existing.title} (${reason})`,
  ));
  console.log(`New works to add: ${classification.newWorks.length}`);
  console.log(formatList(
    classification.newWorks,
    (work) => `${work.year ? `${work.year} ` : ''}${work.title} [${work.category || 'Other'}]`,
  ));
  console.log(`Works that need manual review: ${classification.manualReviewWorks.length}`);
  console.log(formatList(
    classification.manualReviewWorks,
    (work) => `${work.title}${work.category ? ` [${work.category}]` : ''}`,
  ));
  if (classification.sourceDuplicates.length) {
    console.log(`Duplicate titles inside RYM source skipped: ${classification.sourceDuplicates.length}`);
    console.log(formatList(classification.sourceDuplicates, (work) => work.title));
  }
}

async function main() {
  const args = parseCliArgs(process.argv.slice(2));
  const composerId = requireArg(args, 'composer-id');
  const htmlPath = path.resolve(process.cwd(), requireArg(args, 'file'));
  const shouldPreview = Boolean(args.preview);
  const shouldImport = Boolean(args.import);
  if (shouldPreview === shouldImport) {
    throw new Error('Choose exactly one mode: --preview or --import.');
  }

  const defaultDataPath = path.join('data', 'classical-library', 'composers', `${composerId}.json`);
  const dataPath = path.resolve(process.cwd(), args.data && args.data !== true ? String(args.data) : defaultDataPath);
  const data = await readJsonData(dataPath);
  const composer = readComposerFromData(data, composerId);
  if (!composer) {
    throw new Error(`Composer id "${composerId}" does not exist in data file: ${dataPath}.`);
  }

  const importedWorks = await parseRymWorksFile(htmlPath, { composerId });
  const classification = classifyImport({ composer, importedWorks });
  printPreview(classification);

  if (!shouldImport) return;

  const { composer: nextComposer, sourceMetadataUpdated } = applyImport({ composer, importedWorks, classification });
  const nextData = replaceComposerInData(data, nextComposer);
  await writeFile(dataPath, `${JSON.stringify(nextData, null, 2)}\n`, 'utf8');
  console.log(`Import complete: added ${classification.newWorks.length} works and updated ${sourceMetadataUpdated} exact-match source metadata entries.`);
  console.log(`Updated data file: ${dataPath}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error.message || error);
    process.exitCode = 1;
  });
}

export {
  classifyImport,
  composerTitleKey,
  findFuzzyMatches,
  titleSignature,
};
