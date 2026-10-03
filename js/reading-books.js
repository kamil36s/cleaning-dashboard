import {
    readReadingRemotePages,
    saveReadingRemotePages,
} from './reading-settings-store.js';

const RECENT_PAGE_SAVE_STORAGE_KEY = 'readingRecentPageSaves.v1';
const RECENT_BOOK_ADD_STORAGE_KEY = 'readingRecentBookAdds.v1';
const RECENT_PAGE_SAVE_GUARD_MS = 2 * 60 * 1000;
const RECENT_BOOK_ADD_GUARD_MS = 5 * 60 * 1000;

function toFiniteNumber(value) {
    if (value == null || value === '') return null;
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
}

function normalizeKeyPart(value) {
    return String(value || '')
        .normalize('NFC')
        .trim()
        .replace(/\s+/g, ' ')
        .toLowerCase();
}

function normalizeLabelPart(value) {
    return String(value || '')
        .normalize('NFC')
        .trim()
        .replace(/\s*[—–]\s*/g, ' - ')
        .replace(/\s+-\s+/g, ' - ')
        .replace(/\s+/g, ' ');
}

function normalizeRemoteId(value) {
    return normalizeKeyPart(value);
}

function canUseStorage() {
    return typeof window !== 'undefined' && !!window.localStorage;
}

function readRecentPageSaves(nowMs = Date.now()) {
    if (!canUseStorage()) return {};
    try {
        const raw = JSON.parse(window.localStorage.getItem(RECENT_PAGE_SAVE_STORAGE_KEY) || '{}');
        const out = {};
        Object.entries(raw || {}).forEach(([remoteIdRaw, entry]) => {
            const remoteId = normalizeRemoteId(remoteIdRaw);
            const pages = toFiniteNumber(entry?.pages ?? entry);
            const ts = toFiniteNumber(entry?.ts);
            if (!remoteId || pages == null || ts == null) return;
            if ((nowMs - ts) > RECENT_PAGE_SAVE_GUARD_MS) return;
            out[remoteId] = {
                pages: Math.max(0, Math.round(pages)),
                ts,
            };
        });
        return out;
    } catch (error) {
        return {};
    }
}

function writeRecentPageSaves(map) {
    if (!canUseStorage()) return;
    try {
        const normalized = {};
        Object.entries(map || {}).forEach(([remoteIdRaw, entry]) => {
            const remoteId = normalizeRemoteId(remoteIdRaw);
            const pages = toFiniteNumber(entry?.pages ?? entry);
            const ts = toFiniteNumber(entry?.ts);
            if (!remoteId || pages == null || ts == null) return;
            normalized[remoteId] = {
                pages: Math.max(0, Math.round(pages)),
                ts,
            };
        });
        if (Object.keys(normalized).length) {
            window.localStorage.setItem(RECENT_PAGE_SAVE_STORAGE_KEY, JSON.stringify(normalized));
        } else {
            window.localStorage.removeItem(RECENT_PAGE_SAVE_STORAGE_KEY);
        }
    } catch (error) {
        // ignore storage errors
    }
}

function readRecentBookAdds(nowMs = Date.now()) {
    if (!canUseStorage()) return {};
    try {
        const raw = JSON.parse(window.localStorage.getItem(RECENT_BOOK_ADD_STORAGE_KEY) || '{}');
        const out = {};
        Object.entries(raw || {}).forEach(([remoteIdRaw, entry]) => {
            const remoteId = normalizeRemoteId(remoteIdRaw);
            const ts = toFiniteNumber(entry?.ts);
            const book = normalizeReadingBook(entry?.book);
            if (!remoteId || ts == null || !book) return;
            if ((nowMs - ts) > RECENT_BOOK_ADD_GUARD_MS) return;
            out[remoteId] = { book, ts };
        });
        return out;
    } catch (error) {
        return {};
    }
}

function writeRecentBookAdds(map) {
    if (!canUseStorage()) return;
    try {
        const normalized = {};
        Object.entries(map || {}).forEach(([remoteIdRaw, entry]) => {
            const remoteId = normalizeRemoteId(remoteIdRaw);
            const ts = toFiniteNumber(entry?.ts);
            const book = normalizeReadingBook(entry?.book);
            if (!remoteId || ts == null || !book) return;
            normalized[remoteId] = { book, ts };
        });
        if (Object.keys(normalized).length) {
            window.localStorage.setItem(RECENT_BOOK_ADD_STORAGE_KEY, JSON.stringify(normalized));
        } else {
            window.localStorage.removeItem(RECENT_BOOK_ADD_STORAGE_KEY);
        }
    } catch (error) {
        // ignore storage errors
    }
}

const READING_BOOK_COLOR_PALETTE = [
    '#4563d1',
    '#295fa8',
    '#3a4f9f',
    '#2f7a78',
    '#1f8a70',
    '#3d7f4f',
    '#6c5a9a',
    '#7a4f7d',
    '#8c4a5d',
    '#93543a',
    '#4f6b88',
    '#5d6f42',
];

function hashReadingColorSeed(value) {
    const normalized = normalizeLabelPart(value).toLocaleLowerCase('pl');
    let hash = 0;
    for (const ch of normalized) {
        hash = ((hash << 5) - hash) + ch.charCodeAt(0);
        hash |= 0;
    }
    return Math.abs(hash);
}

function getReadingMergeKey(book) {
    const title = normalizeKeyPart(book?.title ?? book?.bookTitle);
    const author = normalizeKeyPart(book?.author ?? book?.bookAuthor);
    if (title && author) return `${title}|${author}`;
    if (title) return title;
    return '';
}

export function getReadingTotalPages(book) {
    const total = toFiniteNumber(book?.pagesTotal ?? book?.pagesAll);
    return total != null ? total : '';
}

export function getReadingBookKey(book) {
    const title = normalizeKeyPart(book?.title);
    const author = normalizeKeyPart(book?.author);
    const total = getReadingTotalPages(book);
    const composite = [title, author, total].filter((value) => value !== '').join('|');
    return composite || '';
}

export function getReadingSourceKey(book) {
    const remoteId = getReadingRemoteId(book);
    if (remoteId) {
        return `remote:${normalizeKeyPart(remoteId)}`;
    }

    const title = normalizeKeyPart(book?.title ?? book?.bookTitle);
    const author = normalizeKeyPart(book?.author ?? book?.bookAuthor);
    if (title && author) {
        return `book:${title}|${author}`;
    }
    if (title) {
        return `title:${title}`;
    }

    return getReadingBookKey(book);
}

export function getReadingDisplayLabel(book) {
    const title = normalizeLabelPart(book?.title ?? book?.bookTitle);
    const author = normalizeLabelPart(book?.author ?? book?.bookAuthor);
    return title && author ? `${title} - ${author}` : (title || author);
}

export function getReadingBookColor(book) {
    const title = normalizeLabelPart(book?.title);
    const author = normalizeLabelPart(book?.author);
    const fallback = getReadingBookKey(book);
    const normalized = [title, author].filter(Boolean).join(' - ').toLocaleLowerCase('pl') || fallback;
    const hash = hashReadingColorSeed(normalized);
    return READING_BOOK_COLOR_PALETTE[hash % READING_BOOK_COLOR_PALETTE.length];
}

export function getReadingBookColorForLabel(label) {
    const normalized = normalizeLabelPart(label);
    if (!normalized) return READING_BOOK_COLOR_PALETTE[0];
    const hash = hashReadingColorSeed(normalized);
    return READING_BOOK_COLOR_PALETTE[hash % READING_BOOK_COLOR_PALETTE.length];
}

export function getReadingRemoteId(book) {
    const candidates = [book?.book_id, book?.bookId, book?.id];
    for (const value of candidates) {
        if (value == null) continue;
        const normalized = String(value).trim();
        if (normalized) return normalized;
    }
    return null;
}

export function getReadingLegacyKeys(book) {
    const keys = [];
    const seen = new Set();
    const push = (value) => {
        if (value == null) return;
        const normalized = String(value).trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        keys.push(normalized);
    };

    push(getReadingSourceKey(book));
    push(getReadingBookKey(book));
    push(getReadingRemoteId(book));
    push(book?.book_id);
    push(book?.bookId);
    push(book?.id);
    push(book?.row_id);
    push(book?.row);

    const title = normalizeKeyPart(book?.title ?? book?.bookTitle);
    const author = normalizeKeyPart(book?.author ?? book?.bookAuthor);
    const total = getReadingTotalPages(book);
    if (title && author && total !== '') {
        push([title, author, total].join('|'));
    }
    if (title && author) {
        push(`book:${title}|${author}`);
    }
    if (title) {
        push(`title:${title}`);
    }

    return keys;
}

export function getReadingMapValue(map, book) {
    if (!map || typeof map !== 'object') return undefined;
    const keys = getReadingLegacyKeys(book);
    for (const key of keys) {
        if (key in map) return map[key];
    }
    return undefined;
}

export function getReadingDefaultOwnership(book) {
    const explicit = String(book?.ownership ?? book?.source ?? book?.status ?? '').toLowerCase();
    if (['wanted', 'wishlist', 'want', 'to-read', 'to_read'].includes(explicit)) return 'wanted';
    if (explicit === 'library') return 'library';
    if (explicit === 'owned') return 'owned';
    return book?.returnDate || book?.dueDate ? 'library' : 'owned';
}

export function getReadingOwnership(map, book) {
    const value = getReadingMapValue(map, book);
    if (value === 'wanted' || value === 'library' || value === 'owned') return value;
    return getReadingDefaultOwnership(book);
}

export function isReadingBookWanted(map, book) {
    return getReadingOwnership(map, book) === 'wanted';
}

export function isReadingBookPossessed(map, book) {
    const ownership = getReadingOwnership(map, book);
    return ownership === 'owned' || ownership === 'library';
}

export function isReadingPageEditable(book) {
    return !!getReadingRemoteId(book);
}

export function normalizeReadingBook(book) {
    if (!book || typeof book !== 'object') return null;

    const totalPages = toFiniteNumber(book.pagesAll ?? book.pagesTotal) ?? 0;
    const pagesRead = toFiniteNumber(book.pagesRead) ?? 0;
    const explicitPercent = toFiniteNumber(book.percent);
    const explicitCompletedPct = toFiniteNumber(book.completedPct);
    const percent = explicitPercent != null
        ? explicitPercent
        : (explicitCompletedPct != null
            ? Math.round(explicitCompletedPct * 100)
            : (totalPages > 0 ? Math.round((pagesRead / totalPages) * 100) : 0));
    const completedPct = explicitCompletedPct != null
        ? explicitCompletedPct
        : (explicitPercent != null
            ? explicitPercent / 100
            : (totalPages > 0 ? pagesRead / totalPages : 0));
    const daysToReturn = toFiniteNumber(book.daysToReturn ?? book.dueInDays);
    const returnDate = book.returnDate ?? book.dueDate ?? null;

    return {
        ...book,
        pagesAll: totalPages,
        pagesTotal: totalPages,
        pagesRead,
        pagesLeft: Math.max(0, totalPages - pagesRead),
        percent,
        completedPct,
        returnDate,
        dueDate: returnDate,
        daysToReturn,
        dueInDays: daysToReturn,
    };
}

export function mergeReadingBooksWithRemoteState(primaryBooks = [], remoteBooks = []) {
    const remoteMap = new Map();
    const merged = [];
    const seen = new Set();

    remoteBooks
        .map((book) => normalizeReadingBook(book))
        .filter(Boolean)
        .forEach((book) => {
            const key = getReadingMergeKey(book);
            if (!key) return;
            remoteMap.set(key, book);
        });

    primaryBooks
        .map((rawBook) => normalizeReadingBook(rawBook))
        .filter(Boolean)
        .map((book) => {
            const key = getReadingMergeKey(book);
            if (key) seen.add(key);
            const remote = remoteMap.get(key);
            if (!remote) return book;

            const remotePagesRead = toFiniteNumber(remote.pagesRead);
            const remoteTotal = toFiniteNumber(remote.pagesAll ?? remote.pagesTotal);
            const remotePercent = toFiniteNumber(remote.percent);
            const remoteCompletedPct = remotePercent != null ? remotePercent / 100 : toFiniteNumber(remote.completedPct);
            const remoteDays = toFiniteNumber(remote.daysToReturn ?? remote.dueInDays);
            const remoteDueDate = remote.returnDate ?? remote.dueDate ?? null;

            return normalizeReadingBook({
                ...book,
                book_id: getReadingRemoteId(book) ?? getReadingRemoteId(remote) ?? null,
                bookId: book.bookId ?? remote.bookId ?? remote.book_id ?? null,
                id: book.id ?? remote.id ?? null,
                title: book.title || remote.title || '',
                author: book.author || remote.author || '',
                pagesRead: remotePagesRead != null ? remotePagesRead : book.pagesRead,
                pagesAll: remoteTotal != null ? remoteTotal : book.pagesAll,
                pagesTotal: remoteTotal != null ? remoteTotal : book.pagesTotal,
                percent: remotePercent != null ? remotePercent : book.percent,
                completedPct: remoteCompletedPct != null ? remoteCompletedPct : book.completedPct,
                returnDate: remoteDueDate ?? book.returnDate ?? null,
                dueDate: remoteDueDate ?? book.dueDate ?? null,
                daysToReturn: remoteDays != null ? remoteDays : book.daysToReturn,
                dueInDays: remoteDays != null ? remoteDays : book.dueInDays,
            });
        })
        .forEach((book) => {
            merged.push(book);
        });

    remoteMap.forEach((book, key) => {
        if (seen.has(key)) return;
        merged.push(book);
    });

    return merged;
}

export function calculateReadingLogDelta({ nextPages, remotePages, localPages }) {
    const next = toFiniteNumber(nextPages);
    if (next == null) return 0;

    const remote = toFiniteNumber(remotePages);
    const local = toFiniteNumber(localPages);
    const baseline = remote != null ? remote : (local != null ? local : 0);
    return Math.max(0, next - baseline);
}

export function resolveReadingProgressBaseline({ nextPages, remotePages, localPages, knownPages }) {
    const next = toFiniteNumber(nextPages);
    const remote = toFiniteNumber(remotePages);
    const local = toFiniteNumber(localPages);
    const known = toFiniteNumber(knownPages);

    if (next == null) {
        return remote != null ? remote : (known != null ? known : (local != null ? local : 0));
    }

    if (remote != null && local != null) {
        // When the backend already reflects `nextPages` but the UI is one save behind,
        // keep the older visible page as the baseline so a correction roundtrip
        // (e.g. 265 -> 255 -> 266) still counts as +1, not +0.
        if (remote >= next && local <= next) {
            return Math.min(remote, local);
        }
        return remote;
    }

    if (known != null && local != null) {
        if (known >= next && local <= next) {
            return Math.min(known, local);
        }
        return Math.max(known, local);
    }

    if (remote != null) return remote;
    if (known != null) return known;
    if (local != null) return local;
    return 0;
}

export function loadReadingRemotePagesMap() {
    try {
        const raw = readReadingRemotePages();
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
        const out = {};
        Object.entries(raw).forEach(([key, value]) => {
            const remoteId = normalizeKeyPart(key);
            const pages = toFiniteNumber(value);
            if (!remoteId || pages == null) return;
            out[remoteId] = Math.max(0, Math.round(pages));
        });
        return out;
    } catch (error) {
        return {};
    }
}

export function saveReadingRemotePagesMap(map) {
    try {
        const normalized = {};
        Object.entries(map || {}).forEach(([key, value]) => {
            const remoteId = normalizeKeyPart(key);
            const pages = toFiniteNumber(value);
            if (!remoteId || pages == null) return;
            normalized[remoteId] = Math.max(0, Math.round(pages));
        });
        const current = loadReadingRemotePagesMap();
        const currentKeys = Object.keys(current);
        const nextKeys = Object.keys(normalized);
        const unchanged = currentKeys.length === nextKeys.length
            && nextKeys.every((key) => current[key] === normalized[key]);
        if (unchanged) return normalized;
        saveReadingRemotePages(normalized);
        return normalized;
    } catch (error) {
        // ignore storage errors
        return {};
    }
}

export function syncReadingRemotePagesMap(books = []) {
    const current = loadReadingRemotePagesMap();
    const next = { ...current };

    books
        .map((book) => normalizeReadingBook(book))
        .filter(Boolean)
        .forEach((book) => {
            const remoteId = normalizeKeyPart(getReadingRemoteId(book));
            const pages = toFiniteNumber(book.pagesRead);
            if (!remoteId || pages == null) return;
            next[remoteId] = Math.max(0, Math.round(pages));
        });

    saveReadingRemotePagesMap(next);
    return next;
}

export function getReadingKnownRemotePage(mapOrBook, maybeBook) {
    const map = maybeBook === undefined ? loadReadingRemotePagesMap() : (mapOrBook || {});
    const book = maybeBook === undefined ? mapOrBook : maybeBook;
    const remoteId = normalizeKeyPart(typeof book === 'string' ? book : getReadingRemoteId(book));
    if (!remoteId) return null;
    const pages = toFiniteNumber(map[remoteId]);
    return pages != null ? Math.max(0, Math.round(pages)) : null;
}

export function markRecentReadingPageSave(bookOrRemoteId, pages, opts = {}) {
    const remoteId = normalizeRemoteId(typeof bookOrRemoteId === 'string'
        ? bookOrRemoteId
        : getReadingRemoteId(bookOrRemoteId));
    const savedPages = toFiniteNumber(pages);
    if (!remoteId || savedPages == null) return;
    const nowMs = toFiniteNumber(opts.nowMs) ?? Date.now();
    const recent = readRecentPageSaves(nowMs);
    recent[remoteId] = {
        pages: Math.max(0, Math.round(savedPages)),
        ts: nowMs,
    };
    writeRecentPageSaves(recent);
}

export function clearRecentReadingPageSave(bookOrRemoteId) {
    const remoteId = normalizeRemoteId(typeof bookOrRemoteId === 'string'
        ? bookOrRemoteId
        : getReadingRemoteId(bookOrRemoteId));
    if (!remoteId) return;
    const recent = readRecentPageSaves();
    if (!(remoteId in recent)) return;
    delete recent[remoteId];
    writeRecentPageSaves(recent);
}

export function markRecentReadingBookAdd(book, opts = {}) {
    const normalized = normalizeReadingBook(book);
    const remoteId = normalizeRemoteId(getReadingRemoteId(normalized));
    if (!remoteId || !normalized) return;
    const nowMs = toFiniteNumber(opts.nowMs) ?? Date.now();
    const recent = readRecentBookAdds(nowMs);
    recent[remoteId] = {
        book: normalized,
        ts: nowMs,
    };
    writeRecentBookAdds(recent);
}

export function clearRecentReadingBookAdd(bookOrRemoteId) {
    const remoteId = normalizeRemoteId(typeof bookOrRemoteId === 'string'
        ? bookOrRemoteId
        : getReadingRemoteId(bookOrRemoteId));
    if (!remoteId) return;
    const recent = readRecentBookAdds();
    if (!(remoteId in recent)) return;
    delete recent[remoteId];
    writeRecentBookAdds(recent);
}

export function applyRecentReadingBookAddGuards(books = [], opts = {}) {
    const nowMs = toFiniteNumber(opts.nowMs) ?? Date.now();
    const recent = readRecentBookAdds(nowMs);
    let changed = false;
    const guarded = (Array.isArray(books) ? books : [])
        .map((book) => normalizeReadingBook(book))
        .filter(Boolean);
    const seenRemoteIds = new Set();
    const seenMergeKeys = new Set();

    guarded.forEach((book) => {
        const remoteId = normalizeRemoteId(getReadingRemoteId(book));
        const mergeKey = getReadingMergeKey(book);
        if (remoteId) seenRemoteIds.add(remoteId);
        if (mergeKey) seenMergeKeys.add(mergeKey);
        if (remoteId && recent[remoteId]) {
            delete recent[remoteId];
            changed = true;
        }
    });

    Object.entries(recent).forEach(([remoteId, entry]) => {
        const book = normalizeReadingBook(entry?.book);
        if (!book) {
            delete recent[remoteId];
            changed = true;
            return;
        }
        const mergeKey = getReadingMergeKey(book);
        if (seenRemoteIds.has(remoteId) || (mergeKey && seenMergeKeys.has(mergeKey))) {
            delete recent[remoteId];
            changed = true;
            return;
        }
        guarded.push(book);
        seenRemoteIds.add(remoteId);
        if (mergeKey) seenMergeKeys.add(mergeKey);
    });

    if (changed) {
        writeRecentBookAdds(recent);
    }

    return guarded;
}

export function applyRecentReadingPageSaveGuards(books = [], opts = {}) {
    const nowMs = toFiniteNumber(opts.nowMs) ?? Date.now();
    const recent = readRecentPageSaves(nowMs);
    let changed = false;

    const guarded = (Array.isArray(books) ? books : []).map((rawBook) => {
        const book = normalizeReadingBook(rawBook);
        if (!book) return null;
        const remoteId = normalizeRemoteId(getReadingRemoteId(book));
        const guard = remoteId ? recent[remoteId] : null;
        if (!guard) return book;

        const current = toFiniteNumber(book.pagesRead);
        if (current != null && current >= guard.pages) {
            delete recent[remoteId];
            changed = true;
            return book;
        }

        changed = true;
        const total = toFiniteNumber(book.pagesTotal ?? book.pagesAll);
        const percent = total != null && total > 0
            ? Math.round((guard.pages / total) * 100)
            : book.percent;
        return normalizeReadingBook({
            ...book,
            pagesRead: guard.pages,
            percent,
            completedPct: total != null && total > 0 ? guard.pages / total : book.completedPct,
        });
    }).filter(Boolean);

    if (changed) {
        writeRecentPageSaves(recent);
    }

    return guarded;
}
