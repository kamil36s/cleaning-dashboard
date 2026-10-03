import { getReadingDisplayLabel, getReadingSourceKey } from './reading-books.js';
import {
  fetchReadingHistory,
  saveReadingHistory,
} from './reading-api.js';
import { parseDateMaybe } from './utils.js';

const READING_LOG_KEY = 'readingDailyLog.v2';
const READING_LOG_START_KEY = 'readingDailyLogStart.v2';
const READING_FORECAST_PLAN_KEY = 'readingForecastPlan.v1';
const READING_CANONICAL_KEYS_FIX_KEY = 'readingDailyLogFix.canonicalKeys.v1';
const READING_WLADCY_CHAOSU_FIX_KEY = 'readingDailyLogFix.wladcyChaosu.v1';
const READING_NIEGRZECZNE_FIX_KEY = 'readingDailyLogFix.niegrzeczne.v1';
const DAY_MS = 24 * 60 * 60 * 1000;
const READING_PROGRESS_TRACKING_VERSION = 2;
const LEGACY_UNKNOWN_BOOK_LABEL = 'Nieznana książka';
const WLADCY_CHAOSU_LABEL = 'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik Søderlind';
const NIEGRZECZNE_LABEL = 'Niegrzeczne: Historie dzieci z ADHD, autyzmem i zespołem Aspergera - Jacek Hołub';
const NIEGRZECZNE_START_KEY = '2026-01-13';
const NIEGRZECZNE_END_KEY = '2026-02-05';
const NIEGRZECZNE_TOTAL_PAGES = 226;
const LEK_RESET_TARGET_DATE_KEY = '2026-03-20';
const LEK_RESET_TITLE = 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym';
const LEK_RESET_REMOTE_KEY = 'remote:lek_spoleczny';

export const READING_HISTORY_RANGE_DAYS = Object.freeze({
  week: 7,
  month: 30,
  quarter: 90,
  year: 365,
});

const canUseStorage = () => typeof window !== 'undefined' && !!window.localStorage;
export const READING_HISTORY_CHANGED_EVENT = 'reading-history:file-changed';
let readingHistoryStoreCache = null;
let readingHistoryLocalSnapshot = '';
let readingHistoryReadyForFileWrites = false;

const toDate = (value) => {
  const dt = parseDateMaybe(value);
  if (!dt || Number.isNaN(dt.getTime())) return null;
  return dt;
};

const startOfDay = (value) => {
  const dt = toDate(value) || new Date();
  return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
};

export const addDays = (value, days) => new Date(startOfDay(value).getTime() + (days * DAY_MS));

const diffInDays = (from, to) => Math.round((startOfDay(to) - startOfDay(from)) / DAY_MS);

const startOfWeek = (value) => {
  const dt = startOfDay(value);
  const weekday = dt.getDay() || 7;
  return addDays(dt, 1 - weekday);
};

const endOfWeek = (value) => addDays(startOfWeek(value), 6);
const startOfMonth = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), dt.getMonth(), 1);
};
const endOfMonth = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), dt.getMonth() + 1, 0);
};
const startOfQuarter = (value) => {
  const dt = startOfDay(value);
  const quarterMonth = Math.floor(dt.getMonth() / 3) * 3;
  return new Date(dt.getFullYear(), quarterMonth, 1);
};
const endOfQuarter = (value) => {
  const start = startOfQuarter(value);
  return new Date(start.getFullYear(), start.getMonth() + 3, 0);
};
const startOfYear = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), 0, 1);
};
const endOfYear = (value) => {
  const dt = startOfDay(value);
  return new Date(dt.getFullYear(), 11, 31);
};

export const getDateKey = (value) => {
  const dt = startOfDay(value);
  const year = dt.getFullYear();
  const month = String(dt.getMonth() + 1).padStart(2, '0');
  const day = String(dt.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

export const parseDateKey = (value) => {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
};

const normalizeRange = (range) => {
  if (range === 'month' || range === 'quarter' || range === 'year') return range;
  return 'week';
};

const buildCalendarWindow = (range, now, offset = 0) => {
  const normalized = normalizeRange(range);
  const shift = Math.trunc(Number(offset) || 0);

  if (normalized === 'week') {
    const startDate = addDays(startOfWeek(now), shift * 7);
    const endDate = addDays(startDate, 6);
    return { range: normalized, startDate, endDate, days: 7 };
  }

  if (normalized === 'month') {
    const startDate = new Date(now.getFullYear(), now.getMonth() + shift, 1);
    const endDate = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0);
    return { range: normalized, startDate, endDate, days: diffInDays(startDate, endDate) + 1 };
  }

  if (normalized === 'quarter') {
    const start = startOfQuarter(now);
    const startDate = new Date(start.getFullYear(), start.getMonth() + (shift * 3), 1);
    const endDate = new Date(startDate.getFullYear(), startDate.getMonth() + 3, 0);
    return { range: normalized, startDate, endDate, days: diffInDays(startDate, endDate) + 1 };
  }

  const startDate = new Date(now.getFullYear() + shift, 0, 1);
  const endDate = new Date(startDate.getFullYear(), 11, 31);
  return { range: normalized, startDate, endDate, days: diffInDays(startDate, endDate) + 1 };
};

export const getReadingRangeDays = (range, opts = {}) => {
  const now = startOfDay(opts.now);
  const offset = Math.trunc(Number(opts.offset) || 0);
  return buildCalendarWindow(range, now, offset).days;
};

const normalizeCount = (value) => {
  const count = Number(value);
  if (!Number.isFinite(count) || count <= 0) return 0;
  return Math.round(count);
};

const normalizeSignedCount = (value) => {
  const count = Number(value);
  if (!Number.isFinite(count)) return 0;
  return Math.round(count);
};

const normalizeTrackingVersion = (value) => {
  const version = Number(value);
  if (!Number.isFinite(version) || version <= 0) return null;
  return Math.round(version);
};

const normalizeSaveCount = (value) => {
  if (value == null || value === '') return null;
  const count = Number(value);
  if (!Number.isFinite(count) || count < 0) return null;
  return Math.round(count);
};

const normalizePage = (value) => {
  const count = Number(value);
  if (!Number.isFinite(count)) return null;
  return Math.max(0, Math.round(count));
};

const normalizeBookLabel = (value) => {
  if (value == null) return '';
  return String(value)
    .normalize('NFC')
    .replace(/\s*[—–]\s*/g, ' - ')
    .replace(/\s+-\s+/g, ' - ')
    .replace(/\s+/g, ' ')
    .trim();
};

const bookLabelKey = (value) => normalizeBookLabel(value).toLocaleLowerCase('pl');
const normalizeHistoryKey = (value) => String(value || '')
  .normalize('NFC')
  .trim()
  .toLocaleLowerCase('pl');
const historyKeyRank = (value) => {
  const key = normalizeHistoryKey(value);
  if (key.startsWith('remote:')) return 4;
  if (key.startsWith('book:')) return 3;
  if (key.startsWith('title:')) return 2;
  if (key) return 1;
  return 0;
};
const extractBookTitle = (value) => {
  const normalized = normalizeBookLabel(value);
  const splitIndex = normalized.lastIndexOf(' - ');
  if (splitIndex <= 0) return normalized;
  return normalized.slice(0, splitIndex);
};
const foldForMatch = (value) => normalizeBookLabel(value)
  .normalize('NFKD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLocaleLowerCase('pl')
  .replace(/[^a-z0-9]+/g, ' ')
  .trim();
const titleTokens = (value) => foldForMatch(extractBookTitle(value))
  .split(/\s+/)
  .filter((token) => token.length >= 3);
const titlesProbablyMatch = (left, right) => {
  const leftFolded = foldForMatch(extractBookTitle(left));
  const rightFolded = foldForMatch(extractBookTitle(right));
  if (!leftFolded || !rightFolded) return false;
  if (leftFolded === rightFolded) {
    return true;
  }

  const leftSet = new Set(titleTokens(left));
  const rightSet = new Set(titleTokens(right));
  if (!leftSet.size || !rightSet.size) return false;

  const shorter = leftFolded.length <= rightFolded.length
    ? { text: leftFolded, tokens: leftSet }
    : { text: rightFolded, tokens: rightSet };
  const longer = leftFolded.length > rightFolded.length ? leftFolded : rightFolded;
  if (shorter.tokens.size >= 2 && shorter.text.length >= 10 && longer.includes(shorter.text)) {
    return true;
  }

  let overlap = 0;
  rightSet.forEach((token) => {
    if (leftSet.has(token)) overlap += 1;
  });

  const required = Math.max(2, Math.ceil(Math.min(leftSet.size, rightSet.size) * 0.6));
  return overlap >= required;
};
const labelContainsBookTitle = (label, title) => {
  const labelKey = bookLabelKey(extractBookTitle(label));
  const titleKey = bookLabelKey(title);
  if (!labelKey || !titleKey) return false;
  return labelKey === titleKey || titlesProbablyMatch(labelKey, titleKey);
};
const extractBookAuthor = (value) => {
  const normalized = normalizeBookLabel(value);
  const splitIndex = normalized.lastIndexOf(' - ');
  if (splitIndex <= 0) return '';
  return normalized.slice(splitIndex + 3);
};
const buildReadingLogIdentity = (meta = {}) => {
  const title = normalizeBookLabel(meta.bookTitle || meta.title || extractBookTitle(meta.label || ''));
  const author = normalizeBookLabel(meta.bookAuthor || meta.author || extractBookAuthor(meta.label || ''));
  const label = normalizeBookLabel(meta.label || getReadingDisplayLabel({ title, author }) || title || author);
  const explicitCandidate = normalizeHistoryKey(meta.bookKey || meta.key);
  const explicitKey = /^(remote|book|title|label):/.test(explicitCandidate) ? explicitCandidate : '';
  const key = explicitKey || getReadingSourceKey({
    book_id: meta.bookId || meta.book_id || meta.remoteId || meta.id,
    title,
    author,
  }) || `label:${bookLabelKey(label)}`;
  return {
    key,
    label: label || key,
    title,
    author,
  };
};
const choosePreferredLabel = (left, right) => {
  const leftLabel = normalizeBookLabel(left);
  const rightLabel = normalizeBookLabel(right);
  if (!leftLabel) return rightLabel;
  if (!rightLabel) return leftLabel;
  if (extractBookAuthor(rightLabel) && !extractBookAuthor(leftLabel)) return rightLabel;
  if (extractBookAuthor(leftLabel) && !extractBookAuthor(rightLabel)) return leftLabel;
  return rightLabel.length > leftLabel.length ? rightLabel : leftLabel;
};
const findCanonicalGroupKey = (groups, identity) => {
  const direct = groups.has(identity.key) ? identity.key : null;
  if (direct) return direct;
  for (const [key, entry] of groups.entries()) {
    if (labelsRepresentSameBook(entry.label, identity.label, identity.title) || labelContainsBookTitle(entry.label, identity.title)) {
      return key;
    }
  }
  return null;
};
const labelsRepresentSameBook = (left, right, titleHint = '') => {
  const leftKey = bookLabelKey(left);
  const rightKey = bookLabelKey(right);
  if (!leftKey || !rightKey) return false;
  if (leftKey === rightKey) return true;

  const leftTitle = extractBookTitle(left);
  const rightTitle = extractBookTitle(right || titleHint);
  if (!titlesProbablyMatch(leftTitle, rightTitle)) return false;

  const leftAuthor = foldForMatch(extractBookAuthor(left));
  const rightAuthor = foldForMatch(extractBookAuthor(right));
  if (!leftAuthor || !rightAuthor) return true;
  return leftAuthor === rightAuthor || leftAuthor.includes(rightAuthor) || rightAuthor.includes(leftAuthor);
};

const normalizeBookMap = (raw) => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const groups = new Map();
  for (const [labelRaw, countRaw] of Object.entries(raw)) {
    const identity = buildReadingLogIdentity({ label: labelRaw });
    const label = identity.label;
    const count = normalizeCount(countRaw);
    if (!label || count <= 0) continue;

    const key = findCanonicalGroupKey(groups, identity) || identity.key;
    const current = groups.get(key);
    if (current) {
      const nextKey = historyKeyRank(identity.key) > historyKeyRank(current.key) ? identity.key : current.key;
      const merged = {
        key: nextKey,
        label: choosePreferredLabel(current.label, label),
        count: current.count + count,
      };
      groups.delete(key);
      groups.set(nextKey, merged);
      continue;
    }

    groups.set(identity.key, { key: identity.key, label, count });
  }
  return Object.fromEntries(
    [...groups.values()].map((entry) => [entry.label, entry.count]),
  );
};

const normalizeProgressMap = (raw) => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const groups = new Map();

  for (const [keyRaw, valueRaw] of Object.entries(raw)) {
    const identity = buildReadingLogIdentity({
      key: keyRaw,
      bookKey: valueRaw?.bookKey,
      label: valueRaw?.label ?? keyRaw,
      title: valueRaw?.title,
      author: valueRaw?.author,
      bookId: valueRaw?.bookId ?? valueRaw?.book_id ?? valueRaw?.remoteId ?? valueRaw?.id,
    });
    const label = identity.label;
    const start = normalizePage(valueRaw?.start ?? valueRaw?.baseline ?? valueRaw?.from);
    const current = normalizePage(valueRaw?.current ?? valueRaw?.page ?? valueRaw?.to);
    if (!label || start == null || current == null) continue;

    const key = findCanonicalGroupKey(groups, identity) || identity.key;
    const existing = groups.get(key);
    if (existing) {
      const nextCurrent = Math.max(existing.current, current);
      const merged = {
        key: historyKeyRank(identity.key) > historyKeyRank(existing.key) ? identity.key : existing.key,
        label: choosePreferredLabel(existing.label, label),
        start: nextCurrent === existing.current && nextCurrent === current
          ? Math.max(existing.start, start)
          : (nextCurrent === current ? start : existing.start),
        current: nextCurrent,
        title: identity.title || existing.title || extractBookTitle(label),
        author: identity.author || existing.author || extractBookAuthor(label),
        trackingVersion: Math.max(
          normalizeTrackingVersion(existing.trackingVersion) ?? 0,
          normalizeTrackingVersion(valueRaw?.trackingVersion ?? valueRaw?.version) ?? 0,
        ) || null,
        saveCount: Math.max(
          normalizeSaveCount(existing.saveCount) ?? 0,
          normalizeSaveCount(valueRaw?.saveCount ?? valueRaw?.writes ?? valueRaw?.save_count) ?? 0,
        ) || null,
      };
      groups.delete(key);
      groups.set(merged.key, merged);
      continue;
    }

    groups.set(identity.key, {
      key: identity.key,
      label,
      start,
      current,
      title: identity.title || extractBookTitle(label),
      author: identity.author || extractBookAuthor(label),
      trackingVersion: normalizeTrackingVersion(valueRaw?.trackingVersion ?? valueRaw?.version),
      saveCount: normalizeSaveCount(valueRaw?.saveCount ?? valueRaw?.writes ?? valueRaw?.save_count),
    });
  }

  return Object.fromEntries(
    [...groups.values()].map((entry) => [entry.key, {
      key: entry.key,
      label: entry.label,
      title: entry.title,
      author: entry.author,
      start: entry.start,
      current: entry.current,
      trackingVersion: entry.trackingVersion,
      saveCount: entry.saveCount,
    }]),
  );
};

const countFromProgress = (entry) => {
  const start = normalizePage(entry?.start);
  const current = normalizePage(entry?.current);
  if (start == null || current == null) return 0;
  return Math.max(0, current - start);
};

const mergeBooksWithProgress = (rawBooks, rawProgress) => {
  const merged = new Map();

  for (const [label, count] of Object.entries(normalizeBookMap(rawBooks))) {
    const identity = buildReadingLogIdentity({ label });
    merged.set(identity.key, { key: identity.key, label: identity.label, count });
  }

  for (const [key, progress] of Object.entries(normalizeProgressMap(rawProgress))) {
    const count = countFromProgress(progress);
    if (count <= 0) {
      merged.delete(key);
      continue;
    }

    const existing = merged.get(key);
    merged.set(key, {
      key,
      label: choosePreferredLabel(existing?.label, progress.label),
      count,
    });
  }

  return Object.fromEntries(
    [...merged.values()].map((entry) => [entry.label, entry.count]),
  );
};

const buildReadingLogLabel = (meta = {}) => {
  return buildReadingLogIdentity(meta).label;
};

const findMatchingLogLabel = (collection, identity) => {
  const entries = Object.keys(collection || {});
  const exact = entries.find((candidate) => {
    const candidateIdentity = buildReadingLogIdentity({ label: candidate });
    return candidateIdentity.key === identity.key || bookLabelKey(candidateIdentity.label) === bookLabelKey(identity.label);
  });
  if (exact) return exact;
  if (!identity.title) return null;
  return entries.find((candidate) => labelsRepresentSameBook(candidate, identity.label, identity.title) || labelContainsBookTitle(candidate, identity.title)) || null;
};
const findMatchingLogEntries = (collection, identity) => Object.entries(collection || {})
  .filter(([candidate, value]) => {
    const candidateIdentity = buildReadingLogIdentity({
      key: candidate,
      bookKey: value?.bookKey || value?.key,
      label: value?.label ?? candidate,
      title: value?.title,
      author: value?.author,
    });
    return candidateIdentity.key === identity.key
      || bookLabelKey(candidateIdentity.label) === bookLabelKey(identity.label)
      || labelsRepresentSameBook(candidateIdentity.label, identity.label, identity.title)
      || (!!identity.title && labelContainsBookTitle(candidateIdentity.label, identity.title));
  });

const matchesReadingIdentity = (candidate, identity) => {
  const candidateIdentity = buildReadingLogIdentity({
    key: candidate?.key,
    bookKey: candidate?.bookKey,
    label: candidate?.label ?? candidate,
    title: candidate?.title,
    author: candidate?.author,
  });
  return candidateIdentity.key === identity.key
    || bookLabelKey(candidateIdentity.label) === bookLabelKey(identity.label)
    || labelsRepresentSameBook(candidateIdentity.label, identity.label, identity.title)
    || (!!identity.title && labelContainsBookTitle(candidateIdentity.label, identity.title));
};

const sumMatchingBookCounts = (collection, identity) => Object.entries(normalizeBookMap(collection))
  .reduce((sum, [label, count]) => (
    matchesReadingIdentity({ label }, identity)
      ? sum + normalizeCount(count)
      : sum
  ), 0);
const pickPreferredProgressMatch = (matches, identity) => {
  if (!Array.isArray(matches) || matches.length === 0) return null;
  const exact = matches.find(([candidate, value]) => {
    const candidateKey = normalizeHistoryKey(value?.bookKey || value?.key || candidate);
    return candidateKey === normalizeHistoryKey(identity.key);
  });
  if (exact) return exact;
  return [...matches].sort((left, right) => {
    const leftCurrent = normalizePage(left[1]?.current);
    const rightCurrent = normalizePage(right[1]?.current);
    if ((rightCurrent ?? -1) !== (leftCurrent ?? -1)) {
      return (rightCurrent ?? -1) - (leftCurrent ?? -1);
    }
    const leftCount = countFromProgress(left[1]);
    const rightCount = countFromProgress(right[1]);
    if (rightCount !== leftCount) return rightCount - leftCount;
    const rightRank = historyKeyRank(right[1]?.bookKey || right[1]?.key || right[0]);
    const leftRank = historyKeyRank(left[1]?.bookKey || left[1]?.key || left[0]);
    if (rightRank !== leftRank) return rightRank - leftRank;
    return String(right[1]?.label || right[0] || '').length - String(left[1]?.label || left[0] || '').length;
  })[0];
};
const removeMatchingBookEntries = (collection, identity) => {
  const next = { ...(collection || {}) };
  Object.keys(next).forEach((candidate) => {
    const candidateIdentity = buildReadingLogIdentity({ label: candidate });
    if (
      candidateIdentity.key === identity.key
      || bookLabelKey(candidateIdentity.label) === bookLabelKey(identity.label)
      || labelsRepresentSameBook(candidateIdentity.label, identity.label, identity.title)
      || labelContainsBookTitle(candidateIdentity.label, identity.title)
    ) {
      delete next[candidate];
    }
  });
  return next;
};
const removeMatchingProgressEntries = (collection, identity) => {
  const next = { ...(collection || {}) };
  Object.entries(next).forEach(([candidate, value]) => {
    const candidateIdentity = buildReadingLogIdentity({
      key: candidate,
      bookKey: value?.bookKey || value?.key,
      label: value?.label ?? candidate,
      title: value?.title,
      author: value?.author,
    });
    if (
      candidateIdentity.key === identity.key
      || bookLabelKey(candidateIdentity.label) === bookLabelKey(identity.label)
      || labelsRepresentSameBook(candidateIdentity.label, identity.label, identity.title)
      || labelContainsBookTitle(candidateIdentity.label, identity.title)
    ) {
      delete next[candidate];
    }
  });
  return next;
};

const mapsEqual = (left, right) => {
  const leftKeys = Object.keys(left || {});
  const rightKeys = Object.keys(right || {});
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => {
    const leftEntry = left[key];
    const rightEntry = right[key];
    return !!rightEntry
      && normalizeBookLabel(leftEntry.label) === normalizeBookLabel(rightEntry.label)
      && normalizeCount(leftEntry.count) === normalizeCount(rightEntry.count);
  });
};

const sumBookMap = (books) => Object.values(books || {}).reduce((sum, count) => sum + (Number(count) || 0), 0);

const toSortedBookList = (books) => Object.entries(normalizeBookMap(books))
  .map(([label, count]) => ({ label, count }))
  .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pl'));

const buildEvenDistribution = (totalPages, startKey, endKey) => {
  const startDate = parseDateKey(startKey);
  const endDate = parseDateKey(endKey);
  if (!startDate || !endDate) return [];
  const days = Math.max(1, diffInDays(startDate, endDate) + 1);
  const total = normalizeCount(totalPages);
  const result = [];

  for (let i = 0; i < days; i += 1) {
    const count = Math.floor((total * (i + 1)) / days) - Math.floor((total * i) / days);
    result.push({
      key: getDateKey(addDays(startDate, i)),
      count,
    });
  }

  return result.filter((item) => item.count > 0);
};

const mergeProgressEntry = (left, right, label) => {
  const leftStart = normalizePage(left?.start);
  const rightStart = normalizePage(right?.start);
  const leftCurrent = normalizePage(left?.current);
  const rightCurrent = normalizePage(right?.current);
  const fallbackCurrent = rightCurrent ?? leftCurrent ?? 0;

  return {
    label,
    start: Math.min(
      leftStart ?? fallbackCurrent,
      rightStart ?? fallbackCurrent,
    ),
    current: Math.max(leftCurrent ?? 0, rightCurrent ?? 0),
  };
};

const normalizeLogEntry = (raw) => {
  if (raw == null) return null;

  if (typeof raw !== 'object' || Array.isArray(raw)) {
    const total = normalizeCount(raw);
    return total > 0 ? { total, books: {}, progress: {} } : null;
  }

  const progress = normalizeProgressMap(raw.progress || raw.bookProgress || raw.pageProgress);
  const books = mergeBooksWithProgress(raw.books || raw.byBook || raw.bookCounts, progress);
  const booksTotal = sumBookMap(books);
  let total = normalizeCount(raw.total ?? raw.count ?? raw.pages ?? raw.value);
  if (Object.keys(progress).length > 0) {
    total = booksTotal;
  } else {
    if (total <= 0) total = booksTotal;
    if (booksTotal > total) total = booksTotal;
  }
  if (total <= 0) return null;

  return { total, books, progress };
};

const normalizeLog = (raw) => {
  if (!raw || typeof raw !== 'object') return {};
  const out = {};
  for (const [key, value] of Object.entries(raw)) {
    if (!parseDateKey(key)) continue;
    const entry = normalizeLogEntry(value);
    if (!entry) continue;
    out[key] = entry;
  }
  return out;
};

export function applyWladcyChaosuLogFix(rawLog) {
  const log = normalizeLog(rawLog);
  const out = {};
  let changed = false;

  for (const [key, entryRaw] of Object.entries(log)) {
    const entry = normalizeLogEntry(entryRaw);
    if (!entry) continue;

    let books = { ...(entry.books || {}) };
    let progress = { ...(entry.progress || {}) };

    const unknownBookKey = Object.keys(books).find((label) => bookLabelKey(label) === bookLabelKey(LEGACY_UNKNOWN_BOOK_LABEL));
    if (unknownBookKey) {
      const count = normalizeCount(books[unknownBookKey]);
      delete books[unknownBookKey];
      if (count > 0) {
        books[WLADCY_CHAOSU_LABEL] = (Number(books[WLADCY_CHAOSU_LABEL]) || 0) + count;
      }
      changed = true;
    }

    const unknownProgressKey = Object.keys(progress).find((label) => bookLabelKey(label) === bookLabelKey(LEGACY_UNKNOWN_BOOK_LABEL));
    if (unknownProgressKey) {
      const existing = progress[WLADCY_CHAOSU_LABEL];
      progress[WLADCY_CHAOSU_LABEL] = mergeProgressEntry(existing, progress[unknownProgressKey], WLADCY_CHAOSU_LABEL);
      delete progress[unknownProgressKey];
      changed = true;
    }

    if (entry.total > 0 && Object.keys(books).length === 0 && Object.keys(progress).length === 0) {
      books = { [WLADCY_CHAOSU_LABEL]: entry.total };
      changed = true;
    }

    const mergedBooks = Object.keys(progress).length > 0
      ? mergeBooksWithProgress(books, progress)
      : normalizeBookMap(books);
    const total = Object.keys(progress).length > 0
      ? sumBookMap(mergedBooks)
      : Math.max(entry.total, sumBookMap(mergedBooks));

    if (total > 0) {
      out[key] = {
        total,
        books: mergedBooks,
        progress: normalizeProgressMap(progress),
      };
    }
  }

  return { changed, log: out };
}

export function applyNiegrzeczneLogFix(rawLog, startKeyRaw) {
  const log = normalizeLog(rawLog);
  const distribution = buildEvenDistribution(
    NIEGRZECZNE_TOTAL_PAGES,
    NIEGRZECZNE_START_KEY,
    NIEGRZECZNE_END_KEY,
  );
  let changed = false;

  distribution.forEach(({ key, count }) => {
    const entry = normalizeLogEntry(log[key]) || { total: 0, books: {}, progress: {} };
    const hasBookEntry = Object.keys(entry.books || {}).some((label) => bookLabelKey(label) === bookLabelKey(NIEGRZECZNE_LABEL));
    const hasProgressEntry = Object.keys(entry.progress || {}).some((label) => bookLabelKey(label) === bookLabelKey(NIEGRZECZNE_LABEL));
    if (hasBookEntry || hasProgressEntry) return;

    const books = normalizeBookMap({
      ...(entry.books || {}),
      [NIEGRZECZNE_LABEL]: (Number(entry.books?.[NIEGRZECZNE_LABEL]) || 0) + count,
    });
    const progress = normalizeProgressMap(entry.progress || {});
    const total = Object.keys(progress).length > 0
      ? sumBookMap(mergeBooksWithProgress(books, progress))
      : Math.max((Number(entry.total) || 0) + count, sumBookMap(books));

    log[key] = {
      total,
      books,
      progress,
    };
    changed = true;
  });

  const storedStart = parseDateKey(startKeyRaw) ? startKeyRaw : null;
  const nextStartKey = (!storedStart || storedStart > NIEGRZECZNE_START_KEY)
    ? NIEGRZECZNE_START_KEY
    : storedStart;

  return { changed, log, nextStartKey };
}

export function applyLekMarch20ResetFix(rawLog, targetDateKey = LEK_RESET_TARGET_DATE_KEY) {
  const log = normalizeLog(rawLog);
  const entry = normalizeLogEntry(log[targetDateKey]);
  if (!entry) {
    return { changed: false, log };
  }

  const targetIdentity = buildReadingLogIdentity({
    key: LEK_RESET_REMOTE_KEY,
    bookKey: LEK_RESET_REMOTE_KEY,
    title: LEK_RESET_TITLE,
    bookTitle: LEK_RESET_TITLE,
    label: LEK_RESET_TITLE,
  });
  const matchesLekReset = (value, meta = {}) => {
    const identity = buildReadingLogIdentity({
      key: meta.key,
      bookKey: meta.bookKey,
      label: meta.label,
      title: meta.title,
      author: meta.author,
      bookTitle: meta.bookTitle,
      bookAuthor: meta.bookAuthor,
    });
    return identity.key === targetIdentity.key
      || bookLabelKey(identity.label) === bookLabelKey(targetIdentity.label)
      || labelsRepresentSameBook(identity.label, targetIdentity.label, targetIdentity.title)
      || labelContainsBookTitle(identity.label, targetIdentity.title)
      || labelContainsBookTitle(value, targetIdentity.title);
  };

  const books = Object.fromEntries(
    Object.entries(entry.books || {}).filter(([label]) => !matchesLekReset(label, { label })),
  );
  const progress = Object.fromEntries(
    Object.entries(entry.progress || {}).filter(([key, value]) => !matchesLekReset(key, {
      key,
      bookKey: value?.bookKey || value?.key,
      label: value?.label ?? key,
      title: value?.title,
      author: value?.author,
    })),
  );

  const changed = Object.keys(books).length !== Object.keys(entry.books || {}).length
    || Object.keys(progress).length !== Object.keys(entry.progress || {}).length;

  if (!changed) {
    return { changed: false, log };
  }

  const mergedBooks = Object.keys(progress).length > 0
    ? mergeBooksWithProgress(books, progress)
    : normalizeBookMap(books);
  const total = sumBookMap(mergedBooks);

  if (total > 0) {
    log[targetDateKey] = {
      total,
      books: mergedBooks,
      progress: normalizeProgressMap(progress),
    };
  } else {
    delete log[targetDateKey];
  }

  return { changed: true, log };
}

const runWladcyChaosuLogFix = () => {
  if (!canUseStorage()) return;
  try {
    if (window.localStorage.getItem(READING_WLADCY_CHAOSU_FIX_KEY) === 'done') return;

    const raw = JSON.parse(window.localStorage.getItem(READING_LOG_KEY) || '{}');
    const result = applyWladcyChaosuLogFix(raw);

    if (result.changed) {
      saveReadingLog(result.log);
    }

    window.localStorage.setItem(READING_WLADCY_CHAOSU_FIX_KEY, 'done');
  } catch (error) {
    // ignore storage errors
  }
};

const runReadingCanonicalKeyFix = () => {
  if (!canUseStorage()) return;
  try {
    if (window.localStorage.getItem(READING_CANONICAL_KEYS_FIX_KEY) === 'done') return;

    const rawText = window.localStorage.getItem(READING_LOG_KEY) || '{}';
    const raw = JSON.parse(rawText);
    const normalized = normalizeLog(raw);
    const normalizedText = JSON.stringify(normalized);
    if (normalizedText !== rawText) {
      window.localStorage.setItem(READING_LOG_KEY, normalizedText);
    }

    window.localStorage.setItem(READING_CANONICAL_KEYS_FIX_KEY, 'done');
  } catch (error) {
    // ignore storage errors
  }
};

const runNiegrzeczneLogFix = () => {
  if (!canUseStorage()) return;
  try {
    if (window.localStorage.getItem(READING_NIEGRZECZNE_FIX_KEY) === 'done') return;

    const raw = JSON.parse(window.localStorage.getItem(READING_LOG_KEY) || '{}');
    const storedStart = window.localStorage.getItem(READING_LOG_START_KEY);
    const result = applyNiegrzeczneLogFix(raw, storedStart);

    if (result.changed) {
      saveReadingLog(result.log);
    }

    if (result.nextStartKey && (!parseDateKey(storedStart) || storedStart > result.nextStartKey)) {
      window.localStorage.setItem(READING_LOG_START_KEY, result.nextStartKey);
    }

    window.localStorage.setItem(READING_NIEGRZECZNE_FIX_KEY, 'done');
  } catch (error) {
    // ignore storage errors
  }
};

export function stabilizeLegacyTodayRemoteProgress(rawBooks, opts = {}) {
  const now = startOfDay(opts.now);
  const todayKey = getDateKey(now);
  const log = normalizeLog(opts.log || loadReadingLog());
  const entry = normalizeLogEntry(log[todayKey]);
  if (!entry) {
    return { changed: false, log };
  }

  let progress = normalizeProgressMap(entry.progress || {});
  let books = { ...(entry.books || {}) };
  let changed = false;

  (Array.isArray(rawBooks) ? rawBooks : []).forEach((book) => {
    const identity = buildReadingLogIdentity({
      bookId: book?.book_id || book?.bookId || book?.id,
      bookTitle: book?.title || book?.bookTitle,
      bookAuthor: book?.author || book?.bookAuthor,
    });
    const remoteCurrent = normalizePage(book?.pagesRead ?? book?.pageCurrent ?? book?.currentPages);
    if (remoteCurrent == null) return;

    const matches = findMatchingLogEntries(progress, identity);
    const preferred = pickPreferredProgressMatch(matches, identity);
    const existing = preferred?.[1];
    if (!existing) return;

    const saveCount = normalizeSaveCount(existing?.saveCount);
    if (saveCount != null) return;

    const localStart = normalizePage(existing?.start);
    const localCurrent = normalizePage(existing?.current);
    const trackingVersion = normalizeTrackingVersion(existing?.trackingVersion);
    const shouldReset = localStart == null
      || localCurrent == null
      || localStart !== remoteCurrent
      || localCurrent !== remoteCurrent
      || trackingVersion !== READING_PROGRESS_TRACKING_VERSION;

    if (!shouldReset) return;

    progress = removeMatchingProgressEntries(progress, identity);
    progress[identity.key] = {
      key: identity.key,
      bookKey: identity.key,
      label: normalizeBookLabel(identity.label || existing?.label) || identity.label || existing?.label,
      title: identity.title || existing?.title,
      author: identity.author || existing?.author,
      start: remoteCurrent,
      current: remoteCurrent,
      trackingVersion: READING_PROGRESS_TRACKING_VERSION,
      saveCount: 0,
    };
    books = removeMatchingBookEntries(books, identity);
    changed = true;
  });

  if (!changed) {
    return { changed: false, log };
  }

  const mergedBooks = Object.keys(progress).length > 0
    ? mergeBooksWithProgress(books, progress)
    : normalizeBookMap(books);
  const total = sumBookMap(mergedBooks);

  if (total > 0) {
    log[todayKey] = {
      total,
      books: mergedBooks,
      progress: normalizeProgressMap(progress),
    };
  } else {
    delete log[todayKey];
  }

  if (!opts.log) {
    saveReadingLog(log);
  }

  return { changed: true, log };
}

function emitReadingHistoryChanged() {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return;
  window.dispatchEvent(new CustomEvent(READING_HISTORY_CHANGED_EVENT));
}

function readLocalReadingHistoryStore() {
  if (!canUseStorage()) {
    return { log: {}, startKey: '', forecastPlan: null };
  }
  try {
    return {
      log: normalizeLog(JSON.parse(window.localStorage.getItem(READING_LOG_KEY) || '{}')),
      startKey: window.localStorage.getItem(READING_LOG_START_KEY) || '',
      forecastPlan: JSON.parse(window.localStorage.getItem(READING_FORECAST_PLAN_KEY) || 'null'),
    };
  } catch {
    return { log: {}, startKey: '', forecastPlan: null };
  }
}

function readLocalReadingHistorySnapshot() {
  if (!canUseStorage()) return '';
  try {
    return JSON.stringify({
      log: window.localStorage.getItem(READING_LOG_KEY) || '',
      startKey: window.localStorage.getItem(READING_LOG_START_KEY) || '',
      forecastPlan: window.localStorage.getItem(READING_FORECAST_PLAN_KEY) || '',
    });
  } catch {
    return '';
  }
}

function normalizeReadingHistoryStore(raw = {}) {
  return {
    log: normalizeLog(raw?.log || {}),
    startKey: parseDateKey(raw?.startKey) ? raw.startKey : '',
    forecastPlan: raw?.forecastPlan && typeof raw.forecastPlan === 'object' ? raw.forecastPlan : null,
  };
}

function mergeHydratedReadingHistory(serverValue, localValue) {
  const server = normalizeReadingHistoryStore(serverValue);
  const local = normalizeReadingHistoryStore(localValue);
  const serverDates = Object.keys(server.log).sort();
  const lastServerDate = serverDates.at(-1) || '';
  const log = { ...server.log };

  // The file is canonical. Keep only genuinely newer, local-only days so a
  // stale/empty browser profile can never replace or backfill old server data.
  Object.entries(local.log).forEach(([dayKey, entry]) => {
    if (!(dayKey in log) && (!lastServerDate || dayKey > lastServerDate)) {
      log[dayKey] = entry;
    }
  });

  const logDates = Object.keys(log).sort();
  const startCandidates = [server.startKey, local.startKey, logDates[0]]
    .filter((value) => parseDateKey(value))
    .sort();
  const serverPlanDay = parseDateKey(server.forecastPlan?.dayKey) ? server.forecastPlan.dayKey : '';
  const localPlanDay = parseDateKey(local.forecastPlan?.dayKey) ? local.forecastPlan.dayKey : '';

  return normalizeReadingHistoryStore({
    log,
    startKey: startCandidates[0] || '',
    forecastPlan: localPlanDay > serverPlanDay ? local.forecastPlan : server.forecastPlan,
  });
}

function getReadingHistoryStore() {
  const localSnapshot = readLocalReadingHistorySnapshot();
  if (readingHistoryStoreCache && localSnapshot === readingHistoryLocalSnapshot) {
    return readingHistoryStoreCache;
  }
  readingHistoryStoreCache = normalizeReadingHistoryStore(readLocalReadingHistoryStore());
  readingHistoryLocalSnapshot = localSnapshot;
  return readingHistoryStoreCache;
}

function writeLocalReadingHistoryStore(store) {
  if (!canUseStorage()) return;
  try {
    window.localStorage.setItem(READING_LOG_KEY, JSON.stringify(normalizeLog(store?.log || {})));
    if (parseDateKey(store?.startKey)) {
      window.localStorage.setItem(READING_LOG_START_KEY, store.startKey);
    } else {
      window.localStorage.removeItem(READING_LOG_START_KEY);
    }
    if (store?.forecastPlan) {
      window.localStorage.setItem(READING_FORECAST_PLAN_KEY, JSON.stringify(store.forecastPlan));
    } else {
      window.localStorage.removeItem(READING_FORECAST_PLAN_KEY);
    }
    readingHistoryLocalSnapshot = readLocalReadingHistorySnapshot();
  } catch {}
}

function saveReadingHistoryStore(store, { notify = false } = {}) {
  const normalized = normalizeReadingHistoryStore(store);
  readingHistoryStoreCache = normalized;
  writeLocalReadingHistoryStore(normalized);
  if (readingHistoryReadyForFileWrites) {
    saveReadingHistory(normalized).catch(() => {});
  }
  if (notify) emitReadingHistoryChanged();
  return normalized;
}

async function hydrateReadingHistoryStore() {
  let serverValue = null;
  let serverFetchSucceeded = false;
  try {
    serverValue = await fetchReadingHistory();
    serverFetchSucceeded = true;
  } catch {}
  const local = normalizeReadingHistoryStore(readLocalReadingHistoryStore());
  const hasServerValue = serverValue !== null && serverValue !== undefined;
  const next = hasServerValue
    ? mergeHydratedReadingHistory(serverValue, local)
    : local;
  const previous = JSON.stringify(getReadingHistoryStore());
  readingHistoryStoreCache = next;
  writeLocalReadingHistoryStore(next);
  readingHistoryReadyForFileWrites = serverFetchSucceeded;
  if (serverFetchSucceeded && (!hasServerValue || JSON.stringify(next) !== JSON.stringify(normalizeReadingHistoryStore(serverValue)))) {
    saveReadingHistory(next).catch(() => {});
  }
  if (JSON.stringify(next) !== previous) {
    emitReadingHistoryChanged();
  }
}

hydrateReadingHistoryStore().catch(() => {});

export function loadReadingLog() {
  return normalizeLog(getReadingHistoryStore().log || {});
}

export function saveReadingLog(map) {
  const store = getReadingHistoryStore();
  saveReadingHistoryStore({ ...store, log: normalizeLog(map) }, { notify: true });
}

export function ensureReadingLogStart(now = new Date()) {
  const fallback = getDateKey(now);
  const store = getReadingHistoryStore();
  try {
    runReadingCanonicalKeyFix();
    runWladcyChaosuLogFix();
    runNiegrzeczneLogFix();
    const stored = store.startKey || (canUseStorage() ? window.localStorage.getItem(READING_LOG_START_KEY) : '');
    if (parseDateKey(stored)) return stored;
    saveReadingHistoryStore({ ...store, startKey: fallback });
    return fallback;
  } catch (error) {
    return fallback;
  }
}

export function updateReadingLog(delta, dateKey, meta = {}) {
  const count = normalizeSignedCount(delta);
  if (count === 0) return;
  ensureReadingLogStart();
  const key = parseDateKey(dateKey) ? dateKey : getDateKey();
  const log = loadReadingLog();
  const entry = normalizeLogEntry(log[key]) || { total: 0, books: {}, progress: {} };
  const label = buildReadingLogLabel(meta);
  if (label) {
    const nextBooks = { ...entry.books };
    const nextCount = Math.max(0, (Number(nextBooks[label]) || 0) + count);
    if (nextCount > 0) {
      nextBooks[label] = nextCount;
    } else {
      delete nextBooks[label];
    }
    entry.books = normalizeBookMap(nextBooks);
    entry.total = sumBookMap(entry.books);
  } else {
    entry.total = Math.max(0, entry.total + count);
  }

  if (entry.total > 0) {
    log[key] = entry;
  } else {
    delete log[key];
  }
  saveReadingLog(log);
}

export function recordReadingProgress({ baselinePages, currentPages, dateKey, meta = {}, visiblePages }) {
  const current = normalizePage(currentPages);
  if (current == null) return;

  const identity = buildReadingLogIdentity(meta);
  const { label, title, author, key: bookKey } = identity;
  if (!label) {
    updateReadingLog(current - (normalizePage(baselinePages) ?? current), dateKey, meta);
    return;
  }

  ensureReadingLogStart();
  const key = parseDateKey(dateKey) ? dateKey : getDateKey();
  const log = loadReadingLog();
  const entry = normalizeLogEntry(log[key]) || { total: 0, books: {}, progress: {} };
  const books = { ...(entry.books || {}) };
  const progress = { ...(entry.progress || {}) };

  const matchingProgressEntries = findMatchingLogEntries(progress, identity);
  const preferredProgressMatch = pickPreferredProgressMatch(matchingProgressEntries, identity);
  const existingProgressLabel = preferredProgressMatch?.[0] || null;
  const existing = preferredProgressMatch?.[1];
  const start = normalizePage(existing?.start);
  const existingCurrent = normalizePage(existing?.current);
  const existingSaveCount = normalizeSaveCount(existing?.saveCount);
  const baseline = normalizePage(baselinePages);
  const visible = normalizePage(visiblePages);
  const sanitizedBooks = removeMatchingBookEntries(books, identity);
  const sanitizedProgress = removeMatchingProgressEntries(progress, identity);
  const existingIdentity = existingProgressLabel
    ? buildReadingLogIdentity({ key: existingProgressLabel, label: existing?.label ?? existingProgressLabel, title: existing?.title, author: existing?.author })
    : null;
  const fuzzyProgressMatch = !!existingIdentity && existingIdentity.key !== bookKey;

  let nextStart;
  const shouldResetLegacyCanonicalBaseline = existingSaveCount == null
    && start != null
    && existingCurrent != null
    && visible != null
    && baseline != null
    && existingCurrent === visible
    && baseline === visible
    && start < visible;

  if (shouldResetLegacyCanonicalBaseline) {
    nextStart = current < visible ? current : visible;
  } else if (visible != null && fuzzyProgressMatch) {
    nextStart = current < visible ? current : visible;
  } else if (visible != null && existingCurrent != null && existingCurrent > visible) {
    nextStart = current < visible ? current : visible;
  } else if (current < (baseline ?? current)) {
    nextStart = current;
  } else {
    nextStart = start ?? baseline ?? current;
  }

  sanitizedProgress[bookKey] = {
    key: bookKey,
    bookKey,
    label: normalizeBookLabel(label) || label,
    title,
    author,
    start: nextStart,
    current,
    trackingVersion: READING_PROGRESS_TRACKING_VERSION,
    saveCount: (existingSaveCount ?? 0) + 1,
  };

  const mergedBooks = mergeBooksWithProgress(sanitizedBooks, sanitizedProgress);
  const total = sumBookMap(mergedBooks);

  if (total > 0) {
    log[key] = { total, books: mergedBooks, progress: sanitizedProgress };
  } else {
    delete log[key];
  }

  saveReadingLog(log);
}

export function captureReadingLogBookSnapshot({ dateKey, meta = {}, log: rawLog } = {}) {
  const identity = buildReadingLogIdentity(meta);
  const key = parseDateKey(dateKey) ? dateKey : getDateKey();
  const log = normalizeLog(rawLog || loadReadingLog());
  const entry = normalizeLogEntry(log[key]);

  if (!entry || !identity.label) {
    return {
      dayKey: key,
      books: {},
      progress: {},
    };
  }

  const books = {};
  Object.entries(entry.books || {}).forEach(([label, count]) => {
    const candidateIdentity = buildReadingLogIdentity({ label });
    if (
      candidateIdentity.key === identity.key
      || bookLabelKey(candidateIdentity.label) === bookLabelKey(identity.label)
      || labelsRepresentSameBook(candidateIdentity.label, identity.label, identity.title)
      || labelContainsBookTitle(candidateIdentity.label, identity.title)
    ) {
      books[label] = normalizeCount(count);
    }
  });

  const progress = Object.fromEntries(findMatchingLogEntries(entry.progress || {}, identity));

  return {
    dayKey: key,
    books: normalizeBookMap(books),
    progress: normalizeProgressMap(progress),
  };
}

export function restoreReadingLogBookSnapshot({ dateKey, meta = {}, snapshot, log: rawLog } = {}) {
  const identity = buildReadingLogIdentity(meta);
  const key = parseDateKey(dateKey) ? dateKey : getDateKey();
  const log = normalizeLog(rawLog || loadReadingLog());
  const entry = normalizeLogEntry(log[key]) || { total: 0, books: {}, progress: {} };

  let books = removeMatchingBookEntries(entry.books || {}, identity);
  let progress = removeMatchingProgressEntries(entry.progress || {}, identity);

  const restoredBooks = normalizeBookMap(snapshot?.books || {});
  const restoredProgress = normalizeProgressMap(snapshot?.progress || {});

  books = normalizeBookMap({
    ...books,
    ...restoredBooks,
  });
  progress = normalizeProgressMap({
    ...progress,
    ...restoredProgress,
  });

  const mergedBooks = Object.keys(progress).length > 0
    ? mergeBooksWithProgress(books, progress)
    : normalizeBookMap(books);
  const total = sumBookMap(mergedBooks);

  if (total > 0) {
    log[key] = {
      total,
      books: mergedBooks,
      progress,
    };
  } else {
    delete log[key];
  }

  if (!rawLog) {
    saveReadingLog(log);
  }

  return { changed: true, log };
}

export function reconcileTodayReadingLogWithBooks(books, opts = {}) {
  const now = startOfDay(opts.now);
  const todayKey = getDateKey(now);
  const log = normalizeLog(opts.log || loadReadingLog());
  const entry = normalizeLogEntry(log[todayKey]);
  if (!entry) {
    return { changed: false, log };
  }

  const remoteMap = new Map();
  (Array.isArray(books) ? books : []).forEach((book) => {
    const identity = buildReadingLogIdentity({
      bookId: book?.book_id || book?.bookId || book?.id,
      bookTitle: book?.title || book?.bookTitle,
      bookAuthor: book?.author || book?.bookAuthor,
    });
    const current = normalizePage(book?.pagesRead ?? book?.pageCurrent ?? book?.currentPages);
    if (!identity.label || current == null) return;
    remoteMap.set(identity.key, { ...identity, current });
    if (identity.title) {
      remoteMap.set(`title:${bookLabelKey(identity.title)}`, { ...identity, current });
    }
  });

  let changed = false;
  const nextProgress = { ...(entry.progress || {}) };

  Object.entries(nextProgress).forEach(([storedKey, progress]) => {
    const progressIdentity = buildReadingLogIdentity({
      key: storedKey,
      bookKey: progress?.bookKey || progress?.key,
      label: progress?.label ?? storedKey,
      title: progress?.title,
      author: progress?.author,
    });
    const remote = remoteMap.get(progressIdentity.key)
      || remoteMap.get(`title:${bookLabelKey(progressIdentity.title)}`);
    if (!remote) return;

    const saveCount = normalizeSaveCount(progress?.saveCount);
    const localStart = normalizePage(progress?.start);
    const localCurrent = normalizePage(progress?.current);
    const nextKey = remote.key || progressIdentity.key;
    const nextLabel = normalizeBookLabel(remote.label || progress?.label || progressIdentity.label)
      || remote.label
      || progressIdentity.label;
    const nextTitle = remote.title || progressIdentity.title;
    const nextAuthor = remote.author || progressIdentity.author;

    if (saveCount == null) {
      const shouldReset = localStart !== remote.current
        || localCurrent !== remote.current
        || normalizeTrackingVersion(progress?.trackingVersion) !== READING_PROGRESS_TRACKING_VERSION;
      if (shouldReset) {
        delete nextProgress[storedKey];
        nextProgress[nextKey] = {
          key: nextKey,
          bookKey: nextKey,
          label: nextLabel,
          title: nextTitle,
          author: nextAuthor,
          start: remote.current,
          current: remote.current,
          trackingVersion: READING_PROGRESS_TRACKING_VERSION,
          saveCount: 0,
        };
        changed = true;
      }
      return;
    }

    if (localCurrent != null && localCurrent > remote.current) {
      delete nextProgress[storedKey];
      nextProgress[nextKey] = {
        key: nextKey,
        bookKey: nextKey,
        label: nextLabel,
        title: nextTitle,
        author: nextAuthor,
        start: remote.current,
        current: remote.current,
        trackingVersion: normalizeTrackingVersion(progress?.trackingVersion) ?? READING_PROGRESS_TRACKING_VERSION,
        saveCount,
      };
      changed = true;
    }
  });

  const normalizedProgress = normalizeProgressMap(nextProgress);
  const progressLabels = Object.keys(normalizedProgress);
  let nextBooks = { ...(entry.books || {}) };

  progressLabels.forEach((storedKey) => {
    nextBooks = removeMatchingBookEntries(nextBooks, buildReadingLogIdentity({
      key: storedKey,
      bookKey: normalizedProgress[storedKey]?.bookKey || normalizedProgress[storedKey]?.key,
      label: normalizedProgress[storedKey]?.label ?? storedKey,
      title: normalizedProgress[storedKey]?.title,
      author: normalizedProgress[storedKey]?.author,
    }));
  });

  Object.entries(nextBooks).forEach(([label, count]) => {
    const identity = buildReadingLogIdentity({ label });
    const remote = remoteMap.get(identity.key)
      || remoteMap.get(`title:${bookLabelKey(identity.title)}`);
    if (!remote) return;
    if ((Number(count) || 0) > remote.current) {
      delete nextBooks[label];
      changed = true;
    }
  });

  if (!changed) {
    return { changed: false, log };
  }

  const mergedBooks = Object.keys(normalizedProgress).length > 0
    ? mergeBooksWithProgress(nextBooks, normalizedProgress)
    : normalizeBookMap(nextBooks);
  const total = sumBookMap(mergedBooks);

  if (total > 0) {
    log[todayKey] = {
      total,
      books: mergedBooks,
      progress: normalizedProgress,
    };
  } else {
    delete log[todayKey];
  }

  if (!opts.log) {
    saveReadingLog(log);
  }

  return { changed: true, log };
}

export function getLocalReadingStats(opts = {}) {
  const now = startOfDay(opts.now);
  const log = normalizeLog(opts.log || loadReadingLog());
  const startKey = parseDateKey(opts.startKey) ? opts.startKey : ensureReadingLogStart(now);
  const startDate = startOfDay(parseDateKey(startKey) || now);
  const daysSinceStart = Math.max(1, Math.floor((now - startDate) / DAY_MS) + 1);
  const windowDays = Math.min(7, daysSinceStart);

  let total = 0;
  for (let i = 0; i < windowDays; i += 1) {
    total += normalizeLogEntry(log[getDateKey(addDays(now, -i))])?.total || 0;
  }

  let streak = 0;
  for (let i = 0; i < daysSinceStart; i += 1) {
    const value = normalizeLogEntry(log[getDateKey(addDays(now, -i))])?.total || 0;
    if (value <= 0) break;
    streak += 1;
  }

  return {
    avgPerDay7d: Math.round(total / windowDays),
    streakDays: streak,
    todayRead: normalizeLogEntry(log[getDateKey(now)])?.total || 0,
  };
}

export function buildReadingWindow(opts = {}) {
  const now = startOfDay(opts.now);
  const offset = Math.trunc(Number(opts.offset) || 0);
  const window = buildCalendarWindow(opts.range, now, offset);
  return {
    range: window.range,
    days: window.days,
    offset,
    now,
    startDate: window.startDate,
    endDate: window.endDate,
    isFuture: window.startDate > now,
    isPast: window.endDate < now,
    includesToday: window.startDate <= now && window.endDate >= now,
  };
}

export function buildReadingLogSeries(rawLog, opts = {}) {
  const log = normalizeLog(rawLog);
  const now = startOfDay(opts.now);
  const days = Math.max(1, Math.trunc(Number(opts.days) || 7));
  const startDate = startOfDay(opts.startDate || addDays(now, -(days - 1)));
  const todayKey = getDateKey(now);
  const result = [];

  for (let i = 0; i < days; i += 1) {
    const date = addDays(startDate, i);
    const key = getDateKey(date);
    const entry = normalizeLogEntry(log[key]);
    result.push({
      dayKey: key,
      date: date.toISOString(),
      count: entry?.total || 0,
      books: toSortedBookList(entry?.books),
      isToday: key === todayKey,
    });
  }

  return result;
}

export function buildReadingHistorySeries(rawLog, opts = {}) {
  const window = buildReadingWindow(opts);
  return buildReadingLogSeries(rawLog, {
    now: window.now,
    startDate: window.startDate,
    days: window.days,
  });
}

const normalizeForecastBook = (book) => {
  const due = toDate(book?.dueDate);
  if (!due) return null;
  const dueDate = startOfDay(due);
  const explicitRemaining = Number(book?.remaining);
  const total = Number(book?.pagesTotal ?? book?.pagesAll);
  const read = Number(book?.pagesRead);
  let remaining = Number.isFinite(explicitRemaining)
    ? Math.max(0, Math.round(explicitRemaining))
    : Math.max(0, Math.round(total - read));
  if (!Number.isFinite(remaining)) return null;
  if (remaining <= 0) return null;
  return {
    key: normalizeBookLabel(book?.key || book?.id || book?.label || book?.title || book?.bookTitle) || 'Plan czytania',
    label: normalizeBookLabel(book?.label || book?.title || book?.bookTitle) || 'Plan czytania',
    remaining,
    dueDate,
  };
};

const plannedPagesForDay = (remaining, spanDays, index) => {
  const previous = Math.ceil((remaining * index) / spanDays);
  const next = Math.ceil((remaining * (index + 1)) / spanDays);
  return Math.max(0, next - previous);
};

const normalizeForecastPlanEntry = (raw, fallbackLabel = '') => {
  const count = normalizeCount(raw?.count ?? raw?.total ?? raw?.pages ?? raw?.value ?? raw);
  if (count <= 0) return null;
  const label = normalizeBookLabel(raw?.label ?? fallbackLabel) || normalizeBookLabel(fallbackLabel);
  return { label, count };
};

const normalizeForecastPlanMap = (raw) => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const out = {};
  for (const [keyRaw, value] of Object.entries(raw)) {
    const key = normalizeBookLabel(keyRaw);
    if (!key) continue;
    const entry = normalizeForecastPlanEntry(value);
    if (!entry) continue;
    out[key] = entry;
  }
  return out;
};

const loadReadingForecastPlan = (now = new Date()) => {
  const dayKey = getDateKey(now);
  try {
    const raw = getReadingHistoryStore().forecastPlan || {};
    if (raw?.dayKey !== dayKey) return { dayKey, books: {} };
    return {
      dayKey,
      books: normalizeForecastPlanMap(raw?.books),
    };
  } catch (error) {
    return { dayKey, books: {} };
  }
};

const saveReadingForecastPlan = (plan) => {
  const store = getReadingHistoryStore();
  saveReadingHistoryStore({
    ...store,
    forecastPlan: {
      dayKey: plan?.dayKey || getDateKey(),
      books: normalizeForecastPlanMap(plan?.books),
    },
  });
};

export function resetReadingTodayForecastPlan() {
  const store = getReadingHistoryStore();
  saveReadingHistoryStore({ ...store, forecastPlan: null }, { notify: true });
}

const resolveExplicitForecastPlan = (rawPlan, books) => {
  const normalized = normalizeForecastPlanMap(rawPlan);
  const resolved = {};
  for (const book of books) {
    const direct = normalized[book.key]
      || normalized[book.label]
      || normalized[bookLabelKey(book.label)];
    if (!direct) continue;
    resolved[book.key] = {
      label: normalizeBookLabel(direct.label || book.label) || book.label,
      count: normalizeCount(direct.count),
    };
  }
  return resolved;
};

const ensureReadingTodayPlan = (rawBooks, opts = {}) => {
  const now = startOfDay(opts.now);
  const dayKey = getDateKey(now);
  const books = Array.isArray(rawBooks) ? rawBooks.map(normalizeForecastBook).filter(Boolean) : [];
  const stored = opts.todayPlan
    ? { dayKey, books: resolveExplicitForecastPlan(opts.todayPlan, books) }
    : loadReadingForecastPlan(now);
  const nextBooks = {};

  for (const book of books) {
    const existing = stored.books[book.key];
    const spanDays = Math.max(1, diffInDays(now, book.dueDate));
    const count = normalizeCount(existing?.count ?? plannedPagesForDay(book.remaining, spanDays, 0));
    if (count <= 0) continue;
    nextBooks[book.key] = {
      label: normalizeBookLabel(existing?.label || book.label) || book.label,
      count,
    };
  }

  if (!opts.todayPlan && !mapsEqual(stored.books, nextBooks)) {
    saveReadingForecastPlan({ dayKey, books: nextBooks });
  }

  return { dayKey, books: nextBooks };
};

const buildTodayReadMap = (rawLog, now = new Date()) => {
  const log = normalizeLog(rawLog || loadReadingLog());
  const todayEntry = normalizeLogEntry(log[getDateKey(now)]);
  const map = new Map();
  for (const [label, count] of Object.entries(normalizeBookMap(todayEntry?.books))) {
    map.set(bookLabelKey(label), normalizeCount(count));
  }
  return map;
};

export function getReadingTodayTarget(rawBooks, opts = {}) {
  const now = startOfDay(opts.now);
  const books = Array.isArray(rawBooks) ? rawBooks.map(normalizeForecastBook).filter(Boolean) : [];
  const plan = ensureReadingTodayPlan(books, {
    now,
    todayPlan: opts.todayPlan,
  });
  const result = books
    .map((book) => {
      const entry = plan.books[book.key];
      const count = normalizeCount(entry?.count);
      if (count <= 0) return null;
      return {
        key: book.key,
        label: normalizeBookLabel(entry?.label || book.label) || book.label,
        count,
      };
    })
    .filter(Boolean);

  return {
    total: result.reduce((sum, book) => sum + book.count, 0),
    books: result,
  };
};

export function buildReadingForecastSeries(rawBooks, opts = {}) {
  const books = Array.isArray(rawBooks) ? rawBooks.map(normalizeForecastBook).filter(Boolean) : [];
  const window = buildReadingWindow(opts);
  const dayIndex = new Map();
  const series = [];
  const todayPlan = window.includesToday
    ? ensureReadingTodayPlan(books, { now: window.now, todayPlan: opts.todayPlan })
    : { dayKey: getDateKey(window.now), books: {} };
  const todayReadMap = window.includesToday ? buildTodayReadMap(opts.log, window.now) : new Map();
  const todayKey = getDateKey(window.now);

  for (let i = 0; i < window.days; i += 1) {
    const date = addDays(window.startDate, i);
    const key = getDateKey(date);
    dayIndex.set(key, i);
    series.push({
      dayKey: key,
      date: date.toISOString(),
      count: 0,
      booksMap: {},
      isToday: key === todayKey,
    });
  }

  for (const book of books) {
    if (window.includesToday) {
      const frozenToday = normalizeCount(todayPlan.books[book.key]?.count);
      const frozenLabel = normalizeBookLabel(todayPlan.books[book.key]?.label || book.label) || book.label;
      const todayIndex = dayIndex.get(todayKey);
      if (todayIndex != null && frozenToday > 0) {
        series[todayIndex].count += frozenToday;
        series[todayIndex].booksMap[frozenLabel] = (series[todayIndex].booksMap[frozenLabel] || 0) + frozenToday;
      }

      const todayRead = todayReadMap.get(bookLabelKey(frozenLabel)) || 0;
      const todayLeft = Math.max(0, frozenToday - todayRead);
      const futureRemaining = Math.max(0, book.remaining - todayLeft);
      const futureSpanDays = Math.max(0, diffInDays(addDays(window.now, 1), book.dueDate));

      for (let i = 0; i < futureSpanDays; i += 1) {
        const date = addDays(window.now, i + 1);
        const key = getDateKey(date);
        const index = dayIndex.get(key);
        if (index == null) continue;
        const pages = plannedPagesForDay(futureRemaining, futureSpanDays, i);
        if (pages <= 0) continue;
        series[index].count += pages;
        series[index].booksMap[book.label] = (series[index].booksMap[book.label] || 0) + pages;
      }
      continue;
    }

    const spanDays = Math.max(1, diffInDays(window.now, book.dueDate));
    for (let i = 0; i < spanDays; i += 1) {
      const date = addDays(window.now, i);
      const key = getDateKey(date);
      const index = dayIndex.get(key);
      if (index == null) continue;
      const pages = plannedPagesForDay(book.remaining, spanDays, i);
      if (pages <= 0) continue;
      series[index].count += pages;
      series[index].booksMap[book.label] = (series[index].booksMap[book.label] || 0) + pages;
    }
  }

  return series.map((day) => ({
    dayKey: day.dayKey,
    date: day.date,
    count: day.count,
    books: toSortedBookList(day.booksMap),
    isToday: day.isToday,
  }));
}

const normalizeHistoricalTargetBook = (book) => {
  const due = toDate(book?.dueDate || book?.returnDate);
  if (!due) return null;

  const dueDate = startOfDay(due);
  const explicitRemaining = Number(book?.remaining);
  const total = Number(book?.pagesTotal ?? book?.pagesAll);
  const read = Number(book?.pagesRead);
  const remaining = Number.isFinite(explicitRemaining)
    ? Math.max(0, Math.round(explicitRemaining))
    : (Number.isFinite(total) && Number.isFinite(read)
      ? Math.max(0, Math.round(total - read))
      : null);
  if (!Number.isFinite(remaining)) return null;

  const identity = buildReadingLogIdentity({
    bookId: book?.bookId || book?.book_id || book?.id,
    bookKey: book?.bookKey || book?.key,
    label: book?.label,
    bookTitle: book?.title || book?.bookTitle,
    bookAuthor: book?.author || book?.bookAuthor,
  });
  if (!identity.label) return null;

  return {
    key: identity.key,
    label: identity.label,
    identity,
    dueDate,
    remaining,
  };
};

function historicalTargetForBookOnDay(book, dayDate, now, log) {
  if (!book || !(dayDate instanceof Date) || book.dueDate < dayDate) return 0;

  let pagesReadSinceDayStart = 0;
  for (let cursor = startOfDay(dayDate); cursor <= now; cursor = addDays(cursor, 1)) {
    const entry = normalizeLogEntry(log[getDateKey(cursor)]);
    if (!entry) continue;
    pagesReadSinceDayStart += sumMatchingBookCounts(entry.books, book.identity);
  }

  const remainingAtDayStart = Math.max(0, book.remaining + pagesReadSinceDayStart);
  if (remainingAtDayStart <= 0) return 0;

  const spanDays = Math.max(1, diffInDays(dayDate, book.dueDate));
  return plannedPagesForDay(remainingAtDayStart, spanDays, 0);
}

export function buildReadingTargetSeries(rawBooks, opts = {}) {
  const window = buildReadingWindow(opts);
  const now = startOfDay(window.now);
  const todayKey = getDateKey(now);
  const log = normalizeLog(opts.log || loadReadingLog());
  const books = Array.isArray(rawBooks)
    ? rawBooks.map(normalizeHistoricalTargetBook).filter(Boolean)
    : [];
  const forecastByDay = new Map(
    buildReadingForecastSeries(rawBooks, opts)
      .map((day) => [day.dayKey, day]),
  );

  const result = [];
  for (let i = 0; i < window.days; i += 1) {
    const dayDate = addDays(window.startDate, i);
    const dayKey = getDateKey(dayDate);
    const forecast = forecastByDay.get(dayKey);

    if (forecast && dayDate >= now) {
      result.push({
        dayKey,
        date: dayDate.toISOString(),
        count: Number(forecast.count) || 0,
        books: Array.isArray(forecast.books) ? forecast.books : [],
        isToday: dayKey === todayKey,
      });
      continue;
    }

    const booksMap = {};
    let count = 0;

    books.forEach((book) => {
      const pages = historicalTargetForBookOnDay(book, dayDate, now, log);
      if (pages <= 0) return;
      count += pages;
      booksMap[book.label] = (booksMap[book.label] || 0) + pages;
    });

    result.push({
      dayKey,
      date: dayDate.toISOString(),
      count,
      books: toSortedBookList(booksMap),
      isToday: dayKey === todayKey,
    });
  }

  return result;
}

export function summarizeReadingHistory(rawLog, opts = {}) {
  const now = startOfDay(opts.now);
  const log = normalizeLog(rawLog);
  const todayKey = getDateKey(now);
  const weekSeries = buildReadingLogSeries(log, { now, days: 7 });
  const monthSeries = buildReadingLogSeries(log, { now, days: 30 });
  const quarterSeries = buildReadingLogSeries(log, { now, days: 90 });
  const yearSeries = buildReadingLogSeries(log, { now, days: 365 });

  const totalOf = (series) => series.reduce((sum, day) => sum + (Number(day.count) || 0), 0);

  let streak = 0;
  let cursor = now;
  while ((normalizeLogEntry(log[getDateKey(cursor)])?.total || 0) > 0) {
    streak += 1;
    cursor = addDays(cursor, -1);
  }

  let bestDay = null;
  for (const [key, entryRaw] of Object.entries(log)) {
    const count = normalizeLogEntry(entryRaw)?.total || 0;
    if (count <= 0) continue;
    if (!bestDay || count > bestDay.count || (count === bestDay.count && key > bestDay.dayKey)) {
      bestDay = {
        dayKey: key,
        date: parseDateKey(key)?.toISOString() || '',
        count,
      };
    }
  }

  const weekTotal = totalOf(weekSeries);
  const monthTotal = totalOf(monthSeries);
  const quarterTotal = totalOf(quarterSeries);
  const yearTotal = totalOf(yearSeries);

  return {
    today: normalizeLogEntry(log[todayKey])?.total || 0,
    weekTotal,
    monthTotal,
    quarterTotal,
    yearTotal,
    weekAvg: Math.round(weekTotal / 7),
    monthAvg: Math.round(monthTotal / 30),
    quarterAvg: Math.round(quarterTotal / 90),
    yearAvg: Math.round(yearTotal / 365),
    streak,
    bestDay,
  };
}

export function summarizeReadingForecastSeries(series) {
  const normalized = Array.isArray(series) ? series : [];
  const total = normalized.reduce((sum, day) => sum + (Number(day.count) || 0), 0);
  const activeDays = normalized.filter((day) => (Number(day.count) || 0) > 0).length;

  let maxDay = null;
  for (const day of normalized) {
    const count = Number(day?.count) || 0;
    if (count <= 0) continue;
    if (!maxDay || count > maxDay.count) {
      maxDay = {
        dayKey: day.dayKey,
        date: day.date,
        count,
      };
    }
  }

  return {
    total,
    activeDays,
    avgPerDay: normalized.length ? Math.round(total / normalized.length) : 0,
    maxDay,
  };
}
