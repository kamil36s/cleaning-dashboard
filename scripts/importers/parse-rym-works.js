import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { load } from 'cheerio';

const DEFAULT_SOURCE = 'rym-saved-html';

function cleanText(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function stripDiacritics(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '');
}

function normalizeTitle(value) {
  return stripDiacritics(value)
    .toLowerCase()
    .replace(/['’]/g, '')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function slugPart(value) {
  return normalizeTitle(value).replace(/\s+/g, '-') || 'work';
}

function resolveSourceUrl(rawHref, baseUrl = 'https://rateyourmusic.com/') {
  const href = cleanText(rawHref);
  if (!href) return '';
  try {
    return new URL(href, baseUrl).toString();
  } catch {
    return href;
  }
}

function generateWorkId(composerId, title) {
  return `${slugPart(composerId)}-${slugPart(title)}`;
}

function createImportedWork({
  composerId,
  year,
  role,
  title,
  catalogue = '',
  category = '',
  sourceUrl = '',
  sourceOrder,
}) {
  const id = generateWorkId(composerId, title);
  return {
    id,
    workId: id,
    composerId,
    year: cleanText(year),
    role: cleanText(role),
    sourceRole: cleanText(role),
    title: cleanText(title),
    catalogue: cleanText(catalogue),
    category: cleanText(category),
    sourceCategory: cleanText(category),
    displayCategory: cleanText(category),
    instrumentation: '',
    version: 'original',
    status: 'Not listened',
    reaction: '',
    notes: '',
    source: DEFAULT_SOURCE,
    sourceUrl: cleanText(sourceUrl),
    sourceOrder,
    sources: [
      {
        name: 'Rate Your Music saved HTML Works table',
        url: cleanText(sourceUrl),
        notes: cleanText(role) ? `RYM role: ${cleanText(role)}` : 'Imported from saved RYM Works table.',
      },
    ],
    parts: [],
    sourceNotes: cleanText(role) ? `RYM role: ${cleanText(role)}` : '',
    normalizationConfidence: 0.6,
    normalizationReason: 'Imported from saved RYM HTML; local metadata needs review.',
    needsReview: true,
    hidden: false,
    userMetadataOverrides: {},
  };
}

function parseRymWorksHtml(html, { composerId, baseUrl = 'https://rateyourmusic.com/' } = {}) {
  const $ = load(html);
  const worksList = $('ul#works');
  if (!worksList.length) {
    throw new Error('RYM works list missing: expected ul#works in the saved HTML file.');
  }

  const works = [];
  let category = '';
  let sourceOrder = 0;

  worksList.children('li').each((_, element) => {
    const row = $(element);
    if (row.hasClass('work_header')) {
      category = cleanText(row.text());
      return;
    }
    if (!row.hasClass('work')) return;

    const titleLink = row.find('.work_title a.work').first();
    const title = cleanText(titleLink.text());
    if (!title) return;

    sourceOrder += 1;
    works.push(createImportedWork({
      composerId,
      year: row.find('.work_date').first().text(),
      role: row.find('.work_role').first().text(),
      title,
      catalogue: row.find('.work_numbers').first().text(),
      category,
      sourceUrl: resolveSourceUrl(titleLink.attr('href'), baseUrl),
      sourceOrder,
    }));
  });

  if (!works.length) {
    throw new Error('No RYM work rows found: expected li.work rows inside ul#works.');
  }

  return works;
}

async function parseRymWorksFile(filePath, options = {}) {
  const html = await readFile(filePath, 'utf8');
  return parseRymWorksHtml(html, options);
}

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

async function main() {
  const args = parseCliArgs(process.argv.slice(2));
  const file = args.file || args._;
  const composerId = args['composer-id'] || args.composerId || '';
  if (!file) throw new Error('Missing --file path to a saved RYM HTML file.');
  if (!composerId) throw new Error('Missing --composer-id.');

  const works = await parseRymWorksFile(path.resolve(file), { composerId });
  console.log(JSON.stringify(works, null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error.message || error);
    process.exitCode = 1;
  });
}

export {
  cleanText,
  normalizeTitle,
  slugPart,
  generateWorkId,
  parseRymWorksHtml,
  parseRymWorksFile,
};
