import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function slugPart(value) {
  const cleaned = String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return cleaned || 'work';
}

function sourceUrl(source, work) {
  const raw = String(work.path || '').trim();
  const base = String(source.sourceUrl || 'https://rateyourmusic.com/');
  if (!raw) return base;
  if (/^https?:\/\//i.test(raw)) return raw;
  return new URL(raw, base).toString();
}

function inferVersion(title) {
  const lower = String(title || '').toLowerCase();
  if (lower.includes('orchestral version')) return 'orchestral version';
  if (lower.includes('piano four hands')) return 'piano four hands version';
  if (lower.includes('two pianos')) return 'two pianos version';
  if (lower.includes('piano version')) return 'piano version';
  if (/\barr\.|arranged|orch\./i.test(lower)) return 'arrangement';
  return 'original';
}

function isArrangement(work) {
  const text = `${work.role || ''} ${work.title || ''}`.toLowerCase();
  return text.includes('arranger')
    || text.includes('arrangements')
    || /\barr\.|\borch\.|version\)/i.test(text);
}

function materializeWorks(source, composerId) {
  let order = 0;
  const groups = Array.isArray(source.groups) ? source.groups : [];
  return groups.flatMap((group, groupIndex) => {
    const groupName = String(group.name || 'Other').trim() || 'Other';
    return (Array.isArray(group.works) ? group.works : []).map((work, itemIndex) => {
      order += 1;
      const pathSlug = slugPart(String(work.path || '').split('/').filter(Boolean).pop() || work.title);
      const arranged = isArrangement(work);
      const role = String(work.role || '').trim();
      const url = sourceUrl(source, work);
      return {
        workId: `${composerId}-rym-${String(order).padStart(3, '0')}-${pathSlug}`,
        composerId,
        title: String(work.title || '').trim(),
        year: String(work.date || '').trim(),
        catalogue: String(work.numbers || '').trim(),
        sourceCategory: groupName,
        category: groupName,
        displayCategory: groupName,
        instrumentation: [],
        version: inferVersion(work.title),
        isArrangement: arranged,
        arrangerName: arranged && /ravel/i.test(role) ? 'Maurice Ravel' : null,
        originalWorkId: null,
        parentWorkId: null,
        parts: [],
        sources: [
          {
            name: `${source.provider || 'RYM'} artist Works table`,
            url,
            notes: `${source.grouping || 'source'}: ${groupName}; role: ${role || 'n/a'}.`
          }
        ],
        sourceNotes: role ? `RYM role: ${role}` : '',
        sourceOrder: order,
        sourceGroupOrder: groupIndex + 1,
        sourceItemOrder: itemIndex + 1,
        sourceUrl: url,
        sourceRole: role,
        normalizationConfidence: 1,
        normalizationReason: 'Preserved from RYM artist Works table without category remapping.',
        needsReview: false,
        hidden: false,
        userMetadataOverrides: {}
      };
    });
  });
}

async function main() {
  const rawArg = process.argv[2] || 'data/classical-library/raw/rym/maurice-ravel.json';
  const composerArg = process.argv[3] || 'data/classical-library/composers/maurice-ravel.json';
  const rawPath = path.resolve(root, rawArg);
  const composerPath = path.resolve(root, composerArg);
  const source = JSON.parse(await readFile(rawPath, 'utf8'));
  const composer = JSON.parse(await readFile(composerPath, 'utf8'));
  const composerId = composer.composerId || slugPart(source.artistName || source.artistSlug);

  composer.sources = [
    ...(Array.isArray(composer.sources) ? composer.sources.filter((item) => item?.name !== 'Rate Your Music Works table') : []),
    {
      name: 'Rate Your Music Works table',
      url: source.sourceUrl || '',
      notes: source.sourceNote || 'Imported from RYM source data.'
    }
  ];
  composer.sourceCatalogue = {
    provider: source.provider || 'Rate Your Music',
    artistSlug: source.artistSlug || composerId,
    sourceUrl: source.sourceUrl || '',
    grouping: source.grouping || 'work type',
    groups: (Array.isArray(source.groups) ? source.groups : []).map((group, index) => ({
      name: group.name,
      order: index + 1,
      count: Array.isArray(group.works) ? group.works.length : 0
    }))
  };
  composer.works = materializeWorks(source, composerId);
  composer.lastImportStatus = {
    kind: 'rym-source-works',
    updatedAt: new Date().toISOString(),
    message: `Imported ${composer.works.length} works from ${source.provider || 'RYM'} source groups.`
  };
  composer.updatedAt = new Date().toISOString();

  await writeFile(composerPath, `${JSON.stringify(composer, null, 2)}\n`, 'utf8');
  console.log(`Materialized ${composer.works.length} works into ${path.relative(root, composerPath)}.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
