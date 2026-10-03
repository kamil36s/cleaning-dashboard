// reading.js
import { escapeHtml } from './utils.js';
import {
    createReadingBook,
    fetchReadingBooks,
    fetchReadingState,
    updateReadingBook,
    updateReadingBookProgress,
} from './reading-api.js';
import { formatReadingDate, parseReadingDateInput } from './reading-date.js';
import {
    buildReadingForecastSeries,
    buildReadingHistorySeries,
    buildReadingTargetSeries,
    buildReadingWindow,
    captureReadingLogBookSnapshot,
    ensureReadingLogStart,
    getLocalReadingStats,
    getReadingTodayTarget,
    loadReadingLog,
    READING_HISTORY_CHANGED_EVENT,
    reconcileTodayReadingLogWithBooks,
    recordReadingProgress,
    restoreReadingLogBookSnapshot,
    resetReadingTodayForecastPlan,
    stabilizeLegacyTodayRemoteProgress,
    summarizeReadingForecastSeries,
    summarizeReadingHistory,
} from './reading-history.js';
import {
    applyRecentReadingBookAddGuards,
    applyRecentReadingPageSaveGuards,
    clearRecentReadingPageSave,
    getReadingKnownRemotePage,
    getReadingBookColor,
    getReadingBookColorForLabel,
    getReadingDefaultOwnership,
    getReadingLegacyKeys,
    getReadingMapValue,
    getReadingOwnership,
    getReadingRemoteId,
    getReadingSourceKey,
    isReadingBookPossessed,
    isReadingBookWanted,
    isReadingPageEditable,
    markRecentReadingBookAdd,
    markRecentReadingPageSave,
    mergeReadingBooksWithRemoteState,
    normalizeReadingBook,
    resolveReadingProgressBaseline,
    syncReadingRemotePagesMap,
} from './reading-books.js';
import {
    NOBEL_READING_BOOKS,
    getNobelAuthorYear,
    isNobelAuthor,
} from './reading-nobel-books.js';
import {
    readReadingActiveMap,
    readReadingOwnershipMap,
    saveReadingActiveMap,
    saveReadingOwnershipMap,
    refreshReadingSettings,
    whenReadingSettingsReady,
} from './reading-settings-store.js';
import { scheduleUndo } from './undo-toast.js';
import {
    getCachedReadingCoverInfo,
    getCachedReadingCoverColor,
    isReadingCoversEnabled,
    READING_COVERS_ENABLED_KEY,
    readingCoverLetter,
    resolveLocalReadingCover,
    resolveReadingCoverColor,
    resolveReadingCover,
    saveReadingCoverUpload,
    setReadingCoversEnabled,
} from './reading-covers.js';

const ACTIVE_STORAGE_KEY = 'readingActiveMap.v1';
const OWNERSHIP_STORAGE_KEY = 'readingOwnershipMap.v1';
const READING_SYNC_KEY = 'readingDashboardSync.v1';
const READING_COLUMNS_KEY = 'readingViewColumns.v1';
const READING_COVER_SIZE_KEY = 'readingCoverSize.v1';
const READING_PAGE_SIZE_KEY = 'readingPageSize.v1';
const READING_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const READING_AUTO_REFRESH_MS = 15_000;
const NOBEL_LOGO_URL = `${import.meta.env.BASE_URL || './'}nobel_logo_transparent.png`;

let BOOKS = [];
let STATS = {};
let ACTIVE_MAP = {};
let OWNERSHIP_MAP = {};
let READING_CURRENT_PAGE = 1;
let HISTORY_RANGE = 'week';
let HISTORY_OFFSET = 0;
let HISTORY_WIRED = false;
let HISTORY_HOVERCARD = null;
let FETCH_DATA_REQUEST_ID = 0;
let READING_RENDER_TOKEN = 0;
let PENDING_COVER_UPLOAD_KEY = '';
let PENDING_COVER_UPLOAD_BOOK = null;
let EDITING_BOOK_KEY = '';
let READING_AUTO_REFRESH_PROMISE = null;
const READING_HISTORY_COLOR_ATTEMPTS = new Set();
let READING_HISTORY_COLOR_WARMUP = null;
const PAGE_SAVE_FEEDBACK_MS = 1800;
const ADD_BOOK_FEEDBACK_MS = 3200;
const PAGE_SAVE_STATES = {};
const PAGE_SAVE_TIMERS = {};
const REMOTE_BASELINE_TIMEOUT_MS = 1200;
let ADD_BOOK_STATUS_TIMER = null;

const READING_RANGE_LABELS = {
    week: 'tydzień',
    month: 'miesiąc',
    year: 'rok',
};

const HISTORY_CALENDAR_WEEKDAYS = ['pn', 'wt', 'śr', 'cz', 'pt', 'sb', 'nd'];

function fmtDate(d) {
    return formatReadingDate(d);
}

function formatHistoryDate(value) {
    return formatReadingDate(value);
}

function historyDayTitle(value) {
    const dt = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(dt.getTime())) return '';
    const weekday = dt.toLocaleDateString('pl-PL', { weekday: 'short' }).replace('.', '');
    return `${weekday}, ${formatReadingDate(dt)}`;
}

function formatHistoryStat(value, suffix = '') {
    if (value == null || value === '') return '—';
    return suffix ? `${value} ${suffix}` : String(value);
}

function getWindowLabel(windowMeta) {
    if (!windowMeta) return '—';
    const start = formatHistoryDate(windowMeta.startDate);
    const end = formatHistoryDate(windowMeta.endDate);
    return windowMeta.isFuture ? `Prognoza: ${start} - ${end}` : `${start} - ${end}`;
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
}

function pagesLabel(value) {
    return `${Number(value) || 0} str.`;
}

function broadcastReadingSync(reason = 'update') {
    try {
        localStorage.setItem(READING_SYNC_KEY, JSON.stringify({
            reason,
            ts: Date.now(),
        }));
    } catch (err) {
        // ignore storage errors
    }
}

function clearPageSaveFeedbackTimer(key) {
    const timer = PAGE_SAVE_TIMERS[key];
    if (!timer) return;
    clearTimeout(timer);
    delete PAGE_SAVE_TIMERS[key];
}

function setPageSaveFeedbackState(key, state) {
    if (!key) return;
    clearPageSaveFeedbackTimer(key);

    if (!state || state === 'idle') {
        delete PAGE_SAVE_STATES[key];
        return;
    }

    PAGE_SAVE_STATES[key] = state;

    if (state === 'success' || state === 'error') {
        PAGE_SAVE_TIMERS[key] = setTimeout(() => {
            delete PAGE_SAVE_STATES[key];
            delete PAGE_SAVE_TIMERS[key];
            renderAll();
        }, PAGE_SAVE_FEEDBACK_MS);
    }
}

function getPageSaveFeedbackState(key) {
    return PAGE_SAVE_STATES[key] || 'idle';
}

function buildPageSaveFeedbackInner(state) {
    if (state === 'saving') {
        return `
            <span class="reading-save-feedback-icon is-spinner" aria-hidden="true"></span>
            <span class="reading-save-feedback-label">Zapisywanie</span>
        `;
    }

    if (state === 'success') {
        return `
            <span class="reading-save-feedback-icon is-success" aria-hidden="true">✓</span>
            <span class="reading-save-feedback-label">Zapisano</span>
        `;
    }

    if (state === 'config') {
        return `
            <span class="reading-save-feedback-icon is-error" aria-hidden="true">!</span>
            <span class="reading-save-feedback-label">Brak tokena</span>
        `;
    }

    if (state === 'error') {
        return `
            <span class="reading-save-feedback-icon is-error" aria-hidden="true">!</span>
            <span class="reading-save-feedback-label">Błąd</span>
        `;
    }

    return '';
}

function renderPageSaveFeedback(key) {
    const state = getPageSaveFeedbackState(key);
    const hidden = state === 'idle';
    return `
        <span
            class="reading-save-feedback${hidden ? '' : ` is-${state}`}"
            data-book-page-feedback="${encodeURIComponent(key || '')}"
            aria-live="polite"
            aria-hidden="${hidden ? 'true' : 'false'}"
            ${hidden ? 'hidden' : ''}
        >${buildPageSaveFeedbackInner(state)}</span>
    `;
}

function updatePageSaveFeedback(container, key) {
    const feedback = container.querySelector(`.reading-save-feedback[data-book-page-feedback="${encodeURIComponent(key)}"]`);
    if (!(feedback instanceof HTMLElement)) return;

    const state = getPageSaveFeedbackState(key);
    feedback.className = `reading-save-feedback${state === 'idle' ? '' : ` is-${state}`}`;
    feedback.innerHTML = buildPageSaveFeedbackInner(state);
    feedback.hidden = state === 'idle';
    feedback.setAttribute('aria-hidden', state === 'idle' ? 'true' : 'false');
}

function hasReadingWriteToken() {
    return true;
}

function updateReadingPageInputWidth(input) {
    if (!(input instanceof HTMLInputElement)) return;
    const value = String(input.value || '0').replace(/[^\d]/g, '') || '0';
    const digits = Math.max(1, Math.min(4, value.length));
    input.style.setProperty('--reading-page-digits', String(digits));
}

function nudgePageInput(input, direction) {
    if (!(input instanceof HTMLInputElement) || input.disabled) return;

    const parsedMin = Number(input.min);
    const parsedMax = Number(input.max);
    const parsedStep = Number(input.step);

    const min = Number.isFinite(parsedMin) ? parsedMin : 0;
    const max = Number.isFinite(parsedMax) ? parsedMax : Number.POSITIVE_INFINITY;
    const step = Number.isFinite(parsedStep) && parsedStep > 0 ? parsedStep : 1;
    const current = Number.isFinite(Number(input.value)) ? Number(input.value) : min;
    const next = Math.min(max, Math.max(min, current + (step * direction)));

    input.value = String(next);
    updateReadingPageInputWidth(input);
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

function historyDayParts(value) {
    const dt = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(dt.getTime())) {
        return { weekday: '—', date: '—' };
    }
    return {
        weekday: dt.toLocaleDateString('pl-PL', { weekday: 'short' }).replace('.', ''),
        date: formatReadingDate(dt),
    };
}

function monthSummaryTitle(value, includeYear = true) {
    const dt = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(dt.getTime())) return '—';
    return dt.toLocaleDateString('pl-PL', includeYear
        ? { month: 'long', year: 'numeric' }
        : { month: 'long' });
}

function monthSummaryLabelParts(value) {
    const dt = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(dt.getTime())) {
        return { weekday: '—', date: '' };
    }
    return {
        weekday: dt.toLocaleDateString('pl-PL', { month: 'short' }).replace('.', ''),
        date: '',
    };
}

function historyCalendarWeekdayIndex(value) {
    const dt = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(dt.getTime())) return 0;
    return (dt.getDay() + 6) % 7;
}

function normalizeHistoryBookLabel(value) {
    if (value == null) return '';
    return String(value)
        .normalize('NFC')
        .replace(/\s*[—–]\s*/g, ' - ')
        .replace(/\s+-\s+/g, ' - ')
        .replace(/\s+/g, ' ')
        .trim();
}

function bookTitleFromLabel(label) {
    const normalized = normalizeHistoryBookLabel(label);
    const splitIndex = normalized.lastIndexOf(' - ');
    if (splitIndex <= 0) return normalized;
    return normalized.slice(0, splitIndex);
}

function formatBookLabel(title, author) {
    const normalizedTitle = normalizeHistoryBookLabel(title);
    const normalizedAuthor = normalizeHistoryBookLabel(author);
    if (normalizedTitle && normalizedAuthor) return `${normalizedTitle} - ${normalizedAuthor}`;
    return normalizedTitle || normalizedAuthor || '';
}

function findBookByHistoryLabel(label) {
    const normalized = normalizeHistoryBookLabel(label).toLocaleLowerCase('pl');
    if (!normalized) return null;
    return BOOKS.find((book) => {
        const bookLabel = formatBookLabel(book?.title || '', book?.author || '').toLocaleLowerCase('pl');
        if (bookLabel === normalized) return true;
        const title = normalizeHistoryBookLabel(book?.title || '').toLocaleLowerCase('pl');
        return title && title === normalized;
    }) || null;
}

function buildHistoryCalendarMonthMarkup(startDate, items) {
    const offset = historyCalendarWeekdayIndex(startDate);
    const trailing = (7 - ((offset + items.length) % 7)) % 7;
    const headers = HISTORY_CALENDAR_WEEKDAYS
        .map((label, index) => `<div class="history-calendar-head${index >= 5 ? ' is-weekend' : ''}">${label}</div>`)
        .join('');
    const lead = Array.from({ length: offset }, () => '<div class="history-calendar-spacer" aria-hidden="true"></div>').join('');
    const tail = Array.from({ length: trailing }, () => '<div class="history-calendar-spacer" aria-hidden="true"></div>').join('');
    return `${headers}${lead}${items.join('')}${tail}`;
}

function colorForBookLabel(label) {
    const book = findBookByHistoryLabel(label);
    if (book && isReadingCoversEnabled()) {
        const key = getBookKey(book);
        const assignedColor = getCachedReadingCoverColor(key);
        if (assignedColor) return assignedColor;
        const cachedCover = getCachedReadingCoverInfo(book, key);
        const coverColor = cachedCover.url ? getCachedReadingCoverColor(key, cachedCover.url) : '';
        if (coverColor) return coverColor;
    }
    return getReadingBookColorForLabel(normalizeHistoryBookLabel(label));
}

function colorForBook(book) {
    return getReadingBookColor(book);
}

function dayBooks(day) {
    if (Array.isArray(day?.books) && day.books.length) {
        const grouped = new Map();
        day.books.forEach((book) => {
            const label = normalizeHistoryBookLabel(book?.label);
            const count = Number(book?.count) || 0;
            if (!label || count <= 0) return;
            const key = label.toLocaleLowerCase('pl');
            const current = grouped.get(key);
            if (current) {
                current.count += count;
                if (label.length > current.label.length) {
                    current.label = label;
                }
                return;
            }
            grouped.set(key, { label, count });
        });
        return [...grouped.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pl'));
    }
    if ((Number(day?.count) || 0) > 0) {
        return [{ label: 'Nieznana książka', count: Number(day.count) || 0 }];
    }
    return [];
}

function historyBucketTitle(value, scope = 'day') {
    if (scope === 'month') return monthSummaryTitle(value, true);
    return historyDayTitle(value);
}

function historyDayAriaLabel(day, options = {}) {
    const targetCount = Math.max(0, Number(options.targetCount ?? day?.count) || 0);
    if (options.isForecast) {
        const targetLabel = options.scope === 'month' ? 'Target miesiąca' : 'Target dnia';
        return `${historyBucketTitle(day.date, options.scope)}: ${targetLabel.toLowerCase()} ${pagesLabel(targetCount)}. Prognoza czytania.`;
    }

    const lines = [`${historyBucketTitle(day.date, options.scope)}: ${pagesLabel(day.count)}`];
    const books = dayBooks(day);
    if (books.length) {
        lines.push('Książki:');
        books.forEach((book) => {
            lines.push(`- ${book.label}: ${pagesLabel(book.count)}`);
        });
    }
    return lines.join(' ');
}

function historyDayTooltipMarkup(day, options = {}) {
    const targetCount = Math.max(0, Number(options.targetCount ?? day?.count) || 0);
    if (options.isForecast) {
        const targetLabel = options.scope === 'month' ? 'Target miesiąca' : 'Target dnia';
        return targetCount > 0
            ? `
                <div class="history-bar-tooltip-kicker">${targetLabel}</div>
                <div class="history-bar-tooltip-total">${pagesLabel(targetCount)}</div>
                <div class="history-bar-tooltip-empty">To jest prognoza, nie zapis przeczytanych stron.</div>
            `
            : `<div class="history-bar-tooltip-empty">Brak targetu na ${options.scope === 'month' ? 'ten miesiąc' : 'ten dzień'}.</div>`;
    }

    const books = dayBooks(day);

    if (!books.length) {
        return '<div class="history-bar-tooltip-empty">Brak stron.</div>';
    }

    return `
        <div class="history-bar-tooltip-list">
            ${books.map((book) => `
                <div class="history-bar-tooltip-item">
                    <span class="history-bar-tooltip-name">
                        <span class="history-bar-tooltip-dot" style="background:${colorForBookLabel(book.label)};"></span>
                        <span>${escapeHtml(bookTitleFromLabel(book.label))}</span>
                    </span>
                    <span class="history-bar-tooltip-pages">${pagesLabel(book.count)}</span>
                </div>
            `).join('')}
        </div>
    `;
}

function historyDaySegments(day, totalCount = Number(day?.count) || 0) {
    const total = Math.max(1, Number(totalCount) || 0);
    return dayBooks(day).map((book) => `
        <span
            class="history-bar-segment"
            style="height:${Math.max(8, Math.round((book.count / total) * 100))}%; background:${colorForBookLabel(book.label)};"
            aria-hidden="true"
        ></span>
    `).join('');
}

async function warmReadingHistoryCoverColors(series = []) {
    if (!isReadingCoversEnabled() || READING_HISTORY_COLOR_WARMUP) return READING_HISTORY_COLOR_WARMUP;

    const targets = new Map();
    series.forEach((day) => {
        dayBooks(day).forEach((entry) => {
            const book = findBookByHistoryLabel(entry.label);
            const key = book ? getBookKey(book) : '';
            if (!book || !key || READING_HISTORY_COLOR_ATTEMPTS.has(key)) return;
            READING_HISTORY_COLOR_ATTEMPTS.add(key);
            targets.set(key, { book, key });
        });
    });
    if (!targets.size) return null;

    const queue = [...targets.values()];
    READING_HISTORY_COLOR_WARMUP = (async () => {
        let cursor = 0;
        let changed = false;

        async function worker() {
            while (cursor < queue.length) {
                const target = queue[cursor++];
                try {
                    const localUrl = await resolveLocalReadingCover(target.book, target.key);
                    const cachedCover = localUrl ? null : getCachedReadingCoverInfo(target.book, target.key);
                    const url = localUrl || cachedCover?.url || '';
                    if (!url) continue;
                    if (getCachedReadingCoverColor(target.key, url)) continue;
                    const color = await resolveReadingCoverColor(target.key, url);
                    if (color) changed = true;
                } catch {
                    // Brak lokalnej okładki nie powinien blokować wykresu historii.
                }
            }
        }

        await Promise.all([worker(), worker()]);
        return changed;
    })().finally(() => {
        READING_HISTORY_COLOR_WARMUP = null;
    });

    const changed = await READING_HISTORY_COLOR_WARMUP;
    if (changed) renderReadingHistoryPanel();
    return changed;
}

function aggregateHistorySeriesByMonth(series) {
    const grouped = new Map();

    (Array.isArray(series) ? series : []).forEach((day) => {
        const dt = day?.date ? new Date(day.date) : null;
        if (!dt || !Number.isFinite(dt.getTime())) return;

        const monthStart = new Date(dt.getFullYear(), dt.getMonth(), 1);
        const key = `${monthStart.getFullYear()}-${String(monthStart.getMonth() + 1).padStart(2, '0')}`;
        let bucket = grouped.get(key);
        if (!bucket) {
            bucket = {
                dayKey: key,
                date: monthStart.toISOString(),
                count: 0,
                booksMap: {},
                isToday: false,
            };
            grouped.set(key, bucket);
        }

        bucket.count += Number(day?.count) || 0;
        bucket.isToday = bucket.isToday || !!day?.isToday;

        dayBooks(day).forEach((book) => {
            bucket.booksMap[book.label] = (bucket.booksMap[book.label] || 0) + (Number(book.count) || 0);
        });
    });

    return [...grouped.values()].map((bucket) => ({
        dayKey: bucket.dayKey,
        date: bucket.date,
        count: bucket.count,
        books: Object.entries(bucket.booksMap)
            .map(([label, count]) => ({ label, count }))
            .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pl')),
        isToday: bucket.isToday,
    }));
}

function historyDayStart(value) {
    const dt = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(dt.getTime())) return null;
    return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
}

function historyBarPercent(value, maxValue) {
    const safeMax = Math.max(1, Number(maxValue) || 0);
    const safeValue = Math.max(0, Number(value) || 0);
    return Math.min(100, Math.max(0, Number(((safeValue / safeMax) * 100).toFixed(3))));
}

function renderReadingHistoryBar(day, options = {}) {
    const isForecast = !!options.isForecast;
    const value = Math.max(0, Number(day?.count) || 0);
    const fillCount = Math.max(0, Number(options.fillCount ?? value) || 0);
    const maxCount = Math.max(1, Number(options.maxCount) || 0);
    const pct = fillCount > 0 ? historyBarPercent(fillCount, maxCount) : 0;
    const targetCount = Math.max(0, Number(options.targetCount) || 0);
    const targetPct = targetCount > 0 ? historyBarPercent(targetCount, maxCount) : 0;
    const showTargetLine = options.showTargetLine !== false && targetCount > 0;
    const targetLineClasses = ['history-bar-target-line'];
    if (targetPct >= 72) targetLineClasses.push('is-badge-below');
    const label = options.labelParts || historyDayParts(day?.date);
    const showValue = options.showValue !== false;
    const fillClasses = ['history-bar-fill'];
    if (isForecast) fillClasses.push('is-forecast');
    if (fillCount <= 0) fillClasses.push('is-empty');
    const classes = ['history-bar'];
    if (isForecast) classes.push('is-forecast');
    if (day?.isToday) classes.push('is-today');
    if (!isForecast && targetCount > 0 && value >= targetCount && options.scope !== 'month') {
        classes.push('is-goal-hit');
    }

    return `
        <div class="${classes.join(' ')}" tabindex="0" aria-label="${escapeHtml(historyDayAriaLabel(day, {
            isForecast,
            targetCount: isForecast ? targetCount : value,
            scope: options.scope,
        }))}">
            <div class="history-bar-track">
                ${showTargetLine && targetPct > 0 ? `
                    <span
                        class="${targetLineClasses.join(' ')}"
                        style="bottom:calc(${targetPct}% - 1px)"
                        aria-hidden="true"
                    >
                        <span class="history-bar-target-badge">${pagesLabel(targetCount)}</span>
                    </span>
                ` : ''}
                <div class="${fillClasses.join(' ')}"${fillCount > 0 ? ` style="height:${pct}%"` : ''}>
                    ${fillCount > 0 ? historyDaySegments(day, value) : ''}
                </div>
            </div>
            <div class="history-bar-value${showValue ? '' : ' is-hidden'}">${showValue ? pagesLabel(value) : '&nbsp;'}</div>
            <div class="history-bar-label${options.scope === 'month' ? ' is-month-summary' : ''}">
                <span class="history-bar-label-day">${label.weekday}</span>
                <span class="history-bar-label-date">${label.date}</span>
            </div>
            <div class="history-bar-tooltip-data" hidden>${historyDayTooltipMarkup(day, {
                isForecast,
                targetCount: isForecast ? targetCount : value,
                scope: options.scope,
            })}</div>
        </div>
    `;
}

const DUE_MAX_DAYS = 31;
const DUE_STOPS = [
    { t: 0, c: [126, 34, 206] },  // purple
    { t: 0.33, c: [239, 68, 68] }, // red
    { t: 0.66, c: [251, 191, 36] }, // yellow
    { t: 1, c: [34, 197, 94] },   // green
];

function clamp(num, min, max) {
    return Math.min(max, Math.max(min, num));
}

function lerp(a, b, t) {
    return Math.round(a + (b - a) * t);
}

function mix(c1, c2, t) {
    return [
        lerp(c1[0], c2[0], t),
        lerp(c1[1], c2[1], t),
        lerp(c1[2], c2[2], t),
    ];
}

function dueColor(days) {
    if (!Number.isFinite(days)) return null;
    if (days <= 0) return "#ef4444";
    const d = clamp(days, 1, DUE_MAX_DAYS);
    const t = (d - 1) / (DUE_MAX_DAYS - 1);

    for (let i = 1; i < DUE_STOPS.length; i++) {
        if (t <= DUE_STOPS[i].t) {
            const a = DUE_STOPS[i - 1];
            const b = DUE_STOPS[i];
            const localT = (t - a.t) / (b.t - a.t);
            const c = mix(a.c, b.c, localT);
            return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
        }
    }
    return "rgb(34, 197, 94)";
}

function setReadingCoverStatus(message) {
    const el = document.getElementById('reading-cover-status');
    if (el) el.textContent = message || '';
}

function setAddBookStatus(message, state = 'idle') {
    const el = document.getElementById('reading-add-book-status');
    if (!(el instanceof HTMLElement)) return;
    if (ADD_BOOK_STATUS_TIMER) {
        clearTimeout(ADD_BOOK_STATUS_TIMER);
        ADD_BOOK_STATUS_TIMER = null;
    }
    el.textContent = message || '';
    el.className = `meta reading-add-book-status${state && state !== 'idle' ? ` is-${state}` : ''}`;
    if (state === 'success') {
        ADD_BOOK_STATUS_TIMER = setTimeout(() => {
            el.textContent = '';
            el.className = 'meta reading-add-book-status';
            ADD_BOOK_STATUS_TIMER = null;
        }, ADD_BOOK_FEEDBACK_MS);
    }
}

function setAddBookCoverName(file) {
    const el = document.getElementById('reading-add-cover-name');
    if (!(el instanceof HTMLElement)) return;
    el.textContent = file?.name ? file.name : 'Bez okładki';
}

function wireReadingDateControls(root = document) {
    root.querySelectorAll('.reading-date-control').forEach((control) => {
        if (control.dataset.readingDateWired === 'true') return;
        const textInput = control.querySelector('[data-reading-date-text]');
        const picker = control.querySelector('[data-reading-date-picker]');
        if (!(textInput instanceof HTMLInputElement) || !(picker instanceof HTMLInputElement)) return;

        control.dataset.readingDateWired = 'true';
        const syncPickerFromText = ({ normalize = false } = {}) => {
            try {
                const isoDate = parseReadingDateInput(textInput.value);
                picker.value = isoDate;
                if (normalize && isoDate) textInput.value = formatReadingDate(isoDate);
            } catch {
                picker.value = '';
            }
        };

        picker.addEventListener('change', () => {
            textInput.value = picker.value ? formatReadingDate(picker.value) : '';
            textInput.dispatchEvent(new Event('input', { bubbles: true }));
        });
        textInput.addEventListener('input', () => syncPickerFromText());
        textInput.addEventListener('blur', () => syncPickerFromText({ normalize: true }));
        syncPickerFromText();
    });
}

function setReadingDateControlEnabled(container, enabled) {
    const textInput = container?.querySelector?.('[data-reading-date-text]');
    const picker = container?.querySelector?.('[data-reading-date-picker]');
    if (textInput instanceof HTMLInputElement) {
        textInput.required = enabled;
        textInput.disabled = !enabled;
        if (!enabled) textInput.value = '';
    }
    if (picker instanceof HTMLInputElement) {
        picker.disabled = !enabled;
        if (!enabled) picker.value = '';
    }
}

function syncAddBookReturnDateVisibility(form = document.getElementById('reading-add-book-form')) {
    if (!(form instanceof HTMLFormElement)) return;
    const wrap = document.getElementById('reading-add-return-date-wrap');
    const isLibrary = form.elements.source?.value === 'library';
    if (wrap instanceof HTMLElement) {
        wrap.classList.toggle('is-hidden', !isLibrary);
        setReadingDateControlEnabled(wrap, isLibrary);
    }
}

function normalizeAddBookText(value) {
    return String(value || '').normalize('NFC').replace(/\s+/g, ' ').trim();
}

function normalizeBookIdentityPart(value) {
    return normalizeAddBookText(value).toLocaleLowerCase('pl');
}

function booksReferToSameBook(left, right) {
    const leftId = getReadingRemoteId(left);
    const rightId = getReadingRemoteId(right);
    if (leftId && rightId && leftId === rightId) return true;

    const leftTitle = normalizeBookIdentityPart(left?.title ?? left?.bookTitle);
    const rightTitle = normalizeBookIdentityPart(right?.title ?? right?.bookTitle);
    const leftAuthor = normalizeBookIdentityPart(left?.author ?? left?.bookAuthor);
    const rightAuthor = normalizeBookIdentityPart(right?.author ?? right?.bookAuthor);
    return !!leftTitle && leftTitle === rightTitle && leftAuthor === rightAuthor;
}

function upsertReadingBook(book) {
    const normalized = normalizeReadingBook(book);
    if (!normalized) return null;
    const existingIndex = BOOKS.findIndex((entry) => booksReferToSameBook(entry, normalized));
    if (existingIndex >= 0) {
        BOOKS[existingIndex] = normalizeReadingBook({
            ...BOOKS[existingIndex],
            ...normalized,
        });
        return BOOKS[existingIndex];
    }
    BOOKS.push(normalized);
    return normalized;
}

function buildAddBookFromResponse(payload, formValues) {
    const raw = payload?.book || payload?.item || payload?.entry || {};
    const bookId = getReadingRemoteId(raw)
        || payload?.book_id
        || payload?.bookId
        || payload?.id
        || '';

    return normalizeReadingBook({
        ...raw,
        book_id: bookId,
        title: raw.title ?? raw.bookTitle ?? formValues.title,
        author: raw.author ?? raw.bookAuthor ?? formValues.author,
        pagesRead: raw.pagesRead ?? raw.page_current ?? raw.pageCurrent ?? payload?.page_current ?? formValues.pagesRead,
        pagesAll: raw.pagesAll ?? raw.pagesTotal ?? raw.page_total ?? raw.pageTotal ?? payload?.page_total ?? formValues.pagesTotal,
        pagesTotal: raw.pagesTotal ?? raw.pagesAll ?? raw.page_total ?? raw.pageTotal ?? payload?.page_total ?? formValues.pagesTotal,
        percent: raw.percent ?? payload?.percent,
        completedPct: raw.completedPct,
        returnDate: raw.returnDate ?? raw.dueDate ?? payload?.return_date ?? payload?.dueDate ?? formValues.returnDate ?? null,
        daysToReturn: raw.daysToReturn ?? raw.dueInDays ?? null,
    });
}

function readAddBookFormValues(form) {
    const author = normalizeAddBookText(form.elements.author?.value);
    const title = normalizeAddBookText(form.elements.title?.value);
    const pagesRead = Math.round(Number(form.elements.pagesRead?.value));
    const pagesTotal = Math.round(Number(form.elements.pagesTotal?.value));
    const sourceRaw = String(form.elements.source?.value || 'owned');
    const source = sourceRaw === 'library' || sourceRaw === 'wanted' ? sourceRaw : 'owned';
    const returnDate = parseReadingDateInput(form.elements.returnDate?.value, { required: source === 'library' });
    const cover = form.elements.cover?.files?.[0] || null;

    if (!author) throw new Error('Wpisz autora.');
    if (!title) throw new Error('Wpisz tytuł.');
    if (!Number.isFinite(pagesTotal) || pagesTotal < 1) throw new Error('Podaj liczbę stron.');
    if (!Number.isFinite(pagesRead) || pagesRead < 0) throw new Error('Podaj liczbę przeczytanych stron.');
    if (pagesRead > pagesTotal) throw new Error('Przeczytane strony nie mogą przekraczać liczby stron.');
    if (cover && !String(cover.type || '').startsWith('image/')) throw new Error('Okładka musi być plikiem obrazu.');

    return { author, title, pagesRead, pagesTotal, source, returnDate: source === 'library' ? returnDate : '', cover };
}

async function addReadingBook(formValues) {
    const payload = await createReadingBook({
        title: formValues.title,
        author: formValues.author,
        pagesRead: formValues.pagesRead,
        pagesTotal: formValues.pagesTotal,
        source: formValues.source,
        returnDate: formValues.returnDate || null,
    });

    const addedBook = buildAddBookFromResponse(payload, formValues);
    if (!getReadingRemoteId(addedBook)) {
        throw new Error('Endpoint addBook nie zwrócił book_id.');
    }
    return addedBook;
}

async function handleAddBookSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    const submit = document.getElementById('reading-add-submit');

    let values;
    try {
        values = readAddBookFormValues(form);
    } catch (error) {
        setAddBookStatus(error?.message || 'Nie udało się odczytać formularza.', 'error');
        return;
    }

    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    setAddBookStatus('Dodawanie książki...', 'saving');

    try {
        const addedBook = upsertReadingBook(await addReadingBook(values));
        if (!addedBook) throw new Error('Nie udało się znormalizować książki.');
        const addedKey = getBookKey(addedBook);
        markRecentReadingBookAdd(addedBook);

        ACTIVE_MAP = syncActiveMap(BOOKS);
        OWNERSHIP_MAP = syncOwnershipMap(BOOKS);
        if (addedKey) {
            ACTIVE_MAP[addedKey] = true;
            OWNERSHIP_MAP[addedKey] = values.source === 'library' ? 'library' : (values.source === 'wanted' ? 'wanted' : 'owned');
            saveActiveMap(ACTIVE_MAP);
            saveOwnershipMap(OWNERSHIP_MAP);
        }

        let coverWarning = '';
        if (values.cover) {
            try {
                const key = getBookKey(addedBook);
                await saveReadingCoverUpload(addedBook, key, values.cover);
            } catch (error) {
                console.warn('Reading add-book cover upload failed:', error);
                coverWarning = ' Okładka nie została zapisana.';
            }
        }

        form.reset();
        form.elements.pagesRead.value = '0';
        setAddBookCoverName(null);
        setAddBookStatus(`Książka dodana.${coverWarning}`, coverWarning ? 'warning' : 'success');
        broadcastReadingSync('add-book');
        renderAll();
        fetchData().catch((error) => {
            console.warn('Reading add-book refresh failed:', error);
        });
    } catch (error) {
        console.warn('Reading add-book failed:', error);
        setAddBookStatus(error?.message || 'Nie udało się dodać książki.', 'error');
    } finally {
        if (submit instanceof HTMLButtonElement) submit.disabled = false;
    }
}

function getReadingColumnMode() {
    try {
        return localStorage.getItem(READING_COLUMNS_KEY) === '3' ? '3' : '2';
    } catch {
        return '2';
    }
}

function saveReadingColumnMode(value) {
    const normalized = value === '3' ? '3' : '2';
    try {
        localStorage.setItem(READING_COLUMNS_KEY, normalized);
    } catch {
        // ignore storage errors
    }
    return normalized;
}

function applyReadingColumnMode(value = getReadingColumnMode()) {
    const mode = value === '3' ? '3' : '2';
    const grid = document.getElementById('grid');
    if (grid instanceof HTMLElement) {
        grid.classList.toggle('is-two-columns', mode === '2');
        grid.classList.toggle('is-three-columns', mode === '3');
    }
    document.querySelectorAll('.reading-view-mode-btn[data-reading-columns]').forEach((btn) => {
        const active = btn.dataset.readingColumns === mode;
        btn.classList.toggle('is-active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function getReadingCoverSize() {
    try {
        const value = Number(localStorage.getItem(READING_COVER_SIZE_KEY));
        return Number.isFinite(value) ? Math.max(82, Math.min(152, Math.round(value))) : 112;
    } catch {
        return 112;
    }
}

function applyReadingCoverSize(value = getReadingCoverSize()) {
    const size = Math.max(82, Math.min(152, Math.round(Number(value) || 112)));
    document.documentElement.style.setProperty('--reading-cover-size', `${size}px`);
    const input = document.getElementById('reading-cover-size');
    if (input instanceof HTMLInputElement) input.value = String(size);
    return size;
}

function saveReadingCoverSize(value) {
    const size = applyReadingCoverSize(value);
    try {
        localStorage.setItem(READING_COVER_SIZE_KEY, String(size));
    } catch {
        // ignore storage errors
    }
}

function getReadingPageSize() {
    try {
        const parsed = Number(localStorage.getItem(READING_PAGE_SIZE_KEY));
        return READING_PAGE_SIZE_OPTIONS.includes(parsed) ? parsed : 20;
    } catch {
        return 20;
    }
}

function saveReadingPageSize(value) {
    const parsed = Number(value);
    const size = READING_PAGE_SIZE_OPTIONS.includes(parsed) ? parsed : 20;
    try {
        localStorage.setItem(READING_PAGE_SIZE_KEY, String(size));
    } catch {
        // ignore storage errors
    }
    READING_CURRENT_PAGE = 1;
    return size;
}

function syncReadingPageSizeControl() {
    const el = document.getElementById('reading-page-size');
    if (el instanceof HTMLSelectElement) {
        el.value = String(getReadingPageSize());
    }
}

function resetReadingPagination() {
    READING_CURRENT_PAGE = 1;
    renderAll();
}

function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
        return window.CSS.escape(value);
    }
    return String(value).replace(/["\\]/g, '\\$&');
}

function renderReadingCoverInner(book, url) {
    const letter = escapeHtml(readingCoverLetter(book));
    if (url) {
        return `
            <img src="${escapeAttr(url)}" alt="" loading="lazy" decoding="async" />
            <span class="reading-cover-overlay">Zmień okładkę</span>
        `;
    }
    return `
        <span class="reading-cover-placeholder" aria-hidden="true">${letter}</span>
        <span class="reading-cover-overlay">Wgraj okładkę</span>
    `;
}

function renderReadingCoverButton(book, key, cached) {
    const keyAttr = encodeURIComponent(key || '');
    const hasCover = !!cached?.url;
    const title = book?.title || 'książki';
    return `
        <button
            class="reading-cover${hasCover ? '' : ' is-empty'}"
            type="button"
            data-reading-cover-key="${keyAttr}"
            aria-label="${hasCover ? 'Zmień okładkę' : 'Wgraj okładkę'} dla ${escapeAttr(title)}"
        >
            ${renderReadingCoverInner(book, cached?.url || '')}
        </button>
    `;
}

function updateReadingCoverElement(button, book, url) {
    if (!(button instanceof HTMLElement)) return;
    button.classList.toggle('is-empty', !url);
    button.innerHTML = renderReadingCoverInner(book, url);
    button.setAttribute('aria-label', `${url ? 'Zmień okładkę' : 'Wgraj okładkę'} dla ${book?.title || 'książki'}`);
}

function setReadingBookProgressColor(key, color) {
    if (!key || !color) return;
    const selector = `.reading-progress-fill[data-reading-progress-key="${cssEscape(encodeURIComponent(key))}"]`;
    document.querySelectorAll(selector).forEach((el) => {
        if (el instanceof HTMLElement) el.style.background = color;
    });
}

function getDisplayedReadingCoverImage(key) {
    if (!key) return null;
    const selector = `.reading-cover[data-reading-cover-key="${cssEscape(encodeURIComponent(key))}"] img`;
    const image = document.querySelector(selector);
    return image instanceof window.HTMLImageElement ? image : null;
}

function waitForDisplayedReadingCover(image) {
    if (!(image instanceof window.HTMLImageElement)) return Promise.resolve(null);
    if (image.complete) return Promise.resolve(image.naturalWidth ? image : null);
    if (typeof image.decode === 'function') {
        return image.decode().then(() => image.naturalWidth ? image : null).catch(() => null);
    }
    return new Promise((resolve) => {
        image.addEventListener('load', () => resolve(image), { once: true });
        image.addEventListener('error', () => resolve(null), { once: true });
    });
}

async function applyReadingCoverColor(key, url, displayedImage = null) {
    if (!key || !url) return;
    try {
        const cachedColor = getCachedReadingCoverColor(key, url);
        if (cachedColor) {
            setReadingBookProgressColor(key, cachedColor);
            return true;
        }
        const image = await waitForDisplayedReadingCover(displayedImage || getDisplayedReadingCoverImage(key));
        const color = await resolveReadingCoverColor(key, url, image);
        setReadingBookProgressColor(key, color);
        return !!color;
    } catch {
        // Some remote images cannot be sampled because of CORS; keep the fallback book color.
        return false;
    }
}

async function queueReadingCoverLoads(targets, token) {
    if (!targets.length) return;
    const concurrency = 4;
    let cursor = 0;
    const colorTasks = [];

    async function worker() {
        while (cursor < targets.length) {
            const target = targets[cursor++];
            if (!target || token !== READING_RENDER_TOKEN || !isReadingCoversEnabled()) break;
            const selector = `.reading-cover[data-reading-cover-key="${cssEscape(encodeURIComponent(target.key))}"]`;
            const button = document.querySelector(selector);
            if (!(button instanceof HTMLElement)) continue;

            const url = await resolveReadingCover(target.book, target.key);
            if (!url || token !== READING_RENDER_TOKEN || !document.body.contains(button)) continue;
            updateReadingCoverElement(button, target.book, url);
            colorTasks.push(applyReadingCoverColor(target.key, url, button.querySelector('img')));
        }
    }

    await Promise.all(Array.from({ length: concurrency }, worker));
    await Promise.all(colorTasks);
    return true;
}

async function refreshReadingCoverColors(loadTargets, colorTargets, token) {
    const tasks = [];
    if (loadTargets.length) tasks.push(queueReadingCoverLoads(loadTargets, token));
    if (colorTargets.length) {
        tasks.push(Promise.all(colorTargets.map((target) => (
            applyReadingCoverColor(target.key, target.url, getDisplayedReadingCoverImage(target.key))
        ))));
    }
    if (!tasks.length) return;
    await Promise.all(tasks);
    if (token === READING_RENDER_TOKEN) renderReadingHistoryPanel();
}

function getBookTotalPages(book) {
    const total = Number(book.pagesTotal ?? book.pagesAll);
    return Number.isFinite(total) ? total : '';
}

function normalizeReadingStats(stats = {}) {
    const localStats = getLocalReadingStats();
    const avgPagesPerDay = Math.round(Number(stats.avgPagesPerDay) || Number(localStats.avgPerDay7d) || 0);
    return {
        ...stats,
        avgPagesPerDay,
    };
}

async function fetchPrimaryReadingData() {
    const payload = await fetchReadingBooks();
    return {
        books: Array.isArray(payload?.books) ? payload.books.map(normalizeReadingBook).filter(Boolean) : [],
        stats: normalizeReadingStats(payload?.stats || {}),
    };
}

async function fetchRemoteReadingState() {
    const payload = await fetchReadingState();
    return {
        books: Array.isArray(payload?.activeBooks) ? payload.activeBooks.map(normalizeReadingBook).filter(Boolean) : [],
        stats: normalizeReadingStats({
            avgPagesPerDay: payload?.dailyStats?.avgPagesPerDay,
        }),
    };
}

async function fetchRemoteBookSnapshot(remoteId) {
    if (!remoteId) return null;
    const timeout = new Promise((resolve) => {
        window.setTimeout(() => resolve(null), REMOTE_BASELINE_TIMEOUT_MS);
    });
    const state = await Promise.race([fetchRemoteReadingState(), timeout]);
    if (!state?.books) return null;
    return state.books.find((book) => getReadingRemoteId(book) === remoteId) || null;
}

async function rollbackReadingPageUpdate(remoteId, page) {
    return updateReadingBookProgress(remoteId, page, { recordHistory: false });
}

function getLegacyKeys(book) {
    return getReadingLegacyKeys(book);
}

function getBookKey(book) {
    return getReadingSourceKey(book);
}

function getBookMergeKey(book) {
    const title = String(book?.title || '').normalize('NFC').trim().toLocaleLowerCase('pl');
    const author = String(book?.author || '').normalize('NFC').trim().toLocaleLowerCase('pl');
    return title && author ? `${title}|${author}` : '';
}

function mergeNobelWishlistBooks(books) {
    const seen = new Set((Array.isArray(books) ? books : [])
        .map((book) => getBookMergeKey(book))
        .filter(Boolean));
    const merged = [...(Array.isArray(books) ? books : [])];

    NOBEL_READING_BOOKS.forEach((book) => {
        const key = getBookMergeKey(book);
        if (!key || seen.has(key)) return;
        seen.add(key);
        merged.push(normalizeReadingBook(book));
    });

    return merged;
}

function isBookCompleted(book) {
    const pct = book.completedPct ?? (book.pagesRead / Math.max(1, book.pagesAll));
    return pct >= 1;
}

function loadActiveMap() {
    const parsed = readReadingActiveMap();
    return parsed && typeof parsed === 'object' ? parsed : null;
}

function saveActiveMap(map) {
    saveReadingActiveMap(map);
}

function hasBookDueDate(book) {
    return !!book.returnDate;
}

function loadOwnershipMap() {
    const parsed = readReadingOwnershipMap();
    return parsed && typeof parsed === 'object' ? parsed : null;
}

function saveOwnershipMap(map) {
    saveReadingOwnershipMap(map);
}

function syncActiveMap(books) {
    let map = loadActiveMap();
    let changed = false;
    let hadExistingMap = false;

    if (!map) {
        map = {};
        changed = true;
    } else {
        hadExistingMap = Object.keys(map).length > 0;
    }

    const seen = new Set();

    books.forEach((book) => {
        const key = getBookKey(book);
        if (!key) return;
        seen.add(key);
        if (!(key in map)) {
            let value;
            const legacy = getLegacyKeys(book);
            for (let i = 0; i < legacy.length; i += 1) {
                if (legacy[i] in map) {
                    value = map[legacy[i]];
                    break;
                }
            }
            map[key] = value !== undefined ? value : (book.defaultActive === false || isReadingBookWanted(null, book)
                ? false
                : (hadExistingMap ? false : !isBookCompleted(book)));
            changed = true;
        }
    });

    Object.keys(map).forEach((key) => {
        if (!seen.has(key)) {
            delete map[key];
            changed = true;
        }
    });

    if (changed) saveActiveMap(map);
    return map;
}

function syncOwnershipMap(books) {
    let map = loadOwnershipMap();
    let changed = false;

    if (!map) {
        map = {};
        changed = true;
    }

    const seen = new Set();

    books.forEach((book) => {
        const key = getBookKey(book);
        if (!key) return;
        seen.add(key);
        const legacy = getLegacyKeys(book).filter((candidate) => candidate !== key);
        let legacyValue;
        for (let i = 0; i < legacy.length; i += 1) {
            if (legacy[i] in map) {
                legacyValue = map[legacy[i]];
                break;
            }
        }
        if (!(key in map)) {
            const value = legacyValue;
            map[key] = value !== undefined ? value : getReadingDefaultOwnership(book);
            changed = true;
        } else if (legacyValue !== undefined && map[key] !== legacyValue) {
            map[key] = legacyValue;
            changed = true;
        } else if (map[key] === 'owned' && hasBookDueDate(book) && legacyValue === undefined) {
            map[key] = 'library';
            changed = true;
        }
    });

    Object.keys(map).forEach((key) => {
        if (!seen.has(key)) {
            delete map[key];
            changed = true;
        }
    });

    if (changed) saveOwnershipMap(map);
    return map;
}

function isBookLibrary(map, book) {
    return getReadingOwnership(map, book) === 'library';
}

function isBookActive(map, book) {
    const value = getReadingMapValue(map, book);
    if (value === false) return false;
    return !isBookCompleted(book) || value !== false;
}

function dueSortValue(book) {
    if (!hasBookDueDate(book)) return Number.POSITIVE_INFINITY;
    const days = Number(book.daysToReturn);
    return Number.isFinite(days) ? days : Number.POSITIVE_INFINITY;
}

function compareByDue(a, b) {
    const da = dueSortValue(a);
    const db = dueSortValue(b);
    if (da !== db) return da - db;
    return (a.title || '').localeCompare(b.title || '', 'pl');
}

function compareBySortVal(a, b, sortVal) {
    const aHasDue = hasBookDueDate(a);
    const bHasDue = hasBookDueDate(b);
    if (aHasDue !== bHasDue) return aHasDue ? -1 : 1;

    if (sortVal === 'title') {
        return (a.title || '').localeCompare(b.title || '', 'pl');
    }
    if (sortVal === 'remain') {
        return (b.pagesAll - b.pagesRead) - (a.pagesAll - a.pagesRead);
    }
    if (sortVal === 'completion') {
        const pa = (a.pagesRead / Math.max(1, a.pagesAll));
        const pb = (b.pagesRead / Math.max(1, b.pagesAll));
        return pa - pb;
    }

    return compareByDue(a, b);
}

function compareActiveFirst(a, b) {
    const aActive = isBookActive(ACTIVE_MAP, a);
    const bActive = isBookActive(ACTIVE_MAP, b);
    if (aActive !== bActive) return aActive ? -1 : 1;
    return 0;
}

function comparePossessedFirst(a, b) {
    const aPossessed = isReadingBookPossessed(OWNERSHIP_MAP, a);
    const bPossessed = isReadingBookPossessed(OWNERSHIP_MAP, b);
    if (aPossessed !== bPossessed) return aPossessed ? -1 : 1;
    return 0;
}

function renderNobelAwardBadge(author) {
    if (!isNobelAuthor(author)) return '';
    const year = getNobelAuthorYear(author);
    const label = year
        ? `Laureat literackiej Nagrody Nobla, ${year}`
        : 'Laureat literackiej Nagrody Nobla';
    return `
        <span class="nobel-author-award" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">
            <span class="nobel-author-medal" aria-hidden="true">
                <img src="${escapeAttr(NOBEL_LOGO_URL)}" alt="" loading="lazy" decoding="async" />
            </span>
            <span>Nobel</span>
            ${year ? `<span class="nobel-author-year">· ${year}</span>` : ''}
        </span>
    `;
}

function renderReadingAwardsStrip(book) {
    const award = renderNobelAwardBadge(book?.author || '');
    if (!award) return '';
    return `
        <div class="reading-awards-strip" aria-label="Nagrody autora">
            ${award}
        </div>
    `;
}

function renderAuthorMeta(book) {
    const author = book?.author || '';
    return `
        <div class="meta reading-author-meta">
            <span class="reading-author-name">${escapeHtml(author)}</span>
        </div>
    `;
}

function ownershipConfig(ownership) {
    if (ownership === 'library') {
        return {
            label: 'Biblioteka',
            className: 'is-library',
            icon: '<svg class="pill-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 9l9-5 9 5v2H3V9zm2 4h2v7H5v-7zm4 0h2v7H9v-7zm4 0h2v7h-2v-7zm4 0h2v7h-2v-7z"/></svg>',
        };
    }
    if (ownership === 'wanted') {
        return {
            label: 'Chcę przeczytać',
            className: 'is-wanted',
            icon: '<svg class="pill-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4zm3 12a1 1 0 0 0 1 1h8V7a1 1 0 0 0-1-1H7v10h1zm2-7h5v2h-5V9zm0 4h4v2h-4v-2z"/></svg>',
        };
    }
    return {
        label: 'Dom',
        className: 'is-owned',
        icon: '<svg class="pill-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l9 7h-3v9h-5v-5H11v5H6v-9H3z"/></svg>',
    };
}

function renderBookEditForm(book, keyAttr, ownership) {
    const isLibrary = ownership === 'library';
    return `
        <form class="reading-book-edit-form" data-book-edit-form="${keyAttr}">
            <div class="reading-book-edit-grid">
                <label>
                    <span>Autor</span>
                    <input name="author" type="text" autocomplete="off" value="${escapeAttr(book.author || '')}" required />
                </label>
                <label>
                    <span>Tytuł</span>
                    <input name="title" type="text" autocomplete="off" value="${escapeAttr(book.title || '')}" required />
                </label>
                <label>
                    <span>Przeczytane</span>
                    <input name="pagesRead" type="number" min="0" step="1" value="${Number(book.pagesRead) || 0}" required />
                </label>
                <label>
                    <span>Stron</span>
                    <input name="pagesTotal" type="number" min="1" step="1" value="${Number(book.pagesAll ?? book.pagesTotal) || 0}" required />
                </label>
                <label>
                    <span>Źródło</span>
                    <select name="source">
                        <option value="owned"${ownership === 'owned' ? ' selected' : ''}>Dom</option>
                        <option value="library"${isLibrary ? ' selected' : ''}>Biblioteka</option>
                        <option value="wanted"${ownership === 'wanted' ? ' selected' : ''}>Chcę przeczytać</option>
                    </select>
                </label>
                <label class="reading-book-edit-date${isLibrary ? '' : ' is-hidden'}">
                    <span>Data zwrotu (dd/mm/yyyy)</span>
                    <span class="reading-date-control">
                        <input name="returnDate" type="text" inputmode="numeric" autocomplete="off" placeholder="dd/mm/yyyy" maxlength="10" value="${book.returnDate ? escapeAttr(formatReadingDate(book.returnDate)) : ''}" data-reading-date-text${isLibrary ? ' required' : ' disabled'} />
                        <span class="reading-date-calendar-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" fill="none"><path d="M7 3v3m10-3v3M4.5 9h15M6 5h12a2 2 0 0 1 2 2v12H4V7a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 13h2m4 0h2m-8 3h2m4 0h2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
                        </span>
                        <input class="reading-native-date-picker" type="date" tabindex="-1" aria-label="Wybierz datę zwrotu z kalendarza" value="${book.returnDate ? escapeAttr(String(book.returnDate).slice(0, 10)) : ''}" data-reading-date-picker${isLibrary ? '' : ' disabled'} />
                    </span>
                </label>
            </div>
            <div class="reading-book-edit-actions">
                <button class="reading-book-edit-save" type="submit">Zapisz zmiany</button>
                <button class="reading-book-edit-cancel" type="button" data-book-edit-cancel>Anuluj</button>
                <span class="reading-book-edit-status" aria-live="polite"></span>
            </div>
        </form>
    `;
}

function syncBookEditReturnDateVisibility(form) {
    const wrap = form.querySelector('.reading-book-edit-date');
    const isLibrary = form.elements.source?.value === 'library';
    wrap?.classList.toggle('is-hidden', !isLibrary);
    setReadingDateControlEnabled(wrap, isLibrary);
}

function readBookEditFormValues(form) {
    const author = normalizeAddBookText(form.elements.author?.value);
    const title = normalizeAddBookText(form.elements.title?.value);
    const pagesRead = Math.round(Number(form.elements.pagesRead?.value));
    const pagesTotal = Math.round(Number(form.elements.pagesTotal?.value));
    const sourceRaw = String(form.elements.source?.value || 'owned');
    const source = ['owned', 'library', 'wanted'].includes(sourceRaw) ? sourceRaw : 'owned';
    const returnDate = parseReadingDateInput(form.elements.returnDate?.value, { required: source === 'library' });

    if (!author) throw new Error('Wpisz autora.');
    if (!title) throw new Error('Wpisz tytuł.');
    if (!Number.isFinite(pagesTotal) || pagesTotal < 1) throw new Error('Podaj liczbę stron.');
    if (!Number.isFinite(pagesRead) || pagesRead < 0) throw new Error('Podaj liczbę przeczytanych stron.');
    if (pagesRead > pagesTotal) throw new Error('Przeczytane strony nie mogą przekraczać liczby stron.');

    return { author, title, pagesRead, pagesTotal, source, returnDate: source === 'library' ? returnDate : null };
}

async function handleBookEditSubmit(form, book, key) {
    const status = form.querySelector('.reading-book-edit-status');
    const submit = form.querySelector('.reading-book-edit-save');
    let values;
    try {
        values = readBookEditFormValues(form);
    } catch (error) {
        if (status) status.textContent = error?.message || 'Sprawdź dane książki.';
        return;
    }

    const remoteId = getReadingRemoteId(book);
    if (!remoteId) {
        if (status) status.textContent = 'Ta książka nie ma identyfikatora i nie może zostać zapisana.';
        return;
    }

    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    if (status) status.textContent = 'Zapisywanie...';
    try {
        const payload = await updateReadingBook(remoteId, values);
        const updatedBook = upsertReadingBook(payload?.book || { ...book, ...values });
        if (!updatedBook) throw new Error('Nie udało się odczytać zapisanej książki.');
        const updatedKey = getBookKey(updatedBook) || key;
        if (updatedKey) {
            OWNERSHIP_MAP[updatedKey] = values.source;
            saveOwnershipMap(OWNERSHIP_MAP);
        }
        EDITING_BOOK_KEY = '';
        broadcastReadingSync('edit-book');
        renderAll();
        fetchData().catch((error) => console.warn('Reading book refresh failed:', error));
    } catch (error) {
        console.warn('Reading book update failed:', error);
        const isMissingUpdateRoute = error?.status === 404
            && String(error?.message || '').trim().toLocaleLowerCase('pl') === 'not found';
        if (status) {
            status.textContent = isMissingUpdateRoute
                ? 'Uruchom ponownie server.py, aby włączyć zapis edycji.'
                : (error?.message || 'Nie udało się zapisać zmian.');
        }
        if (submit instanceof HTMLButtonElement) submit.disabled = false;
    }
}

function setBookEditToggleState(button, expanded) {
    if (!(button instanceof HTMLButtonElement)) return;
    button.classList.toggle('is-active', expanded);
    button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    button.setAttribute('aria-label', expanded ? 'Zamknij edycję książki' : 'Edytuj książkę');
    button.title = expanded ? 'Zamknij edycję' : 'Edytuj książkę';
}

function closeInlineBookEditor(card) {
    if (!(card instanceof HTMLElement)) return;
    card.querySelector('.reading-book-edit-form')?.remove();
    setBookEditToggleState(card.querySelector('.reading-book-edit-toggle'), false);
}

function wireBookEditForm(form, book, key) {
    if (!(form instanceof HTMLFormElement) || form.dataset.readingBookEditWired === 'true') return;
    form.dataset.readingBookEditWired = 'true';
    wireReadingDateControls(form);
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        handleBookEditSubmit(form, book, key);
    });
    form.elements.source?.addEventListener('change', () => syncBookEditReturnDateVisibility(form));
    form.querySelector('[data-book-edit-cancel]')?.addEventListener('click', () => {
        const card = form.closest('.reading-book-card');
        EDITING_BOOK_KEY = '';
        closeInlineBookEditor(card);
    });
}

function toggleInlineBookEditor(button, book, key) {
    const card = button.closest('.reading-book-card');
    if (!(card instanceof HTMLElement)) return;
    const currentForm = card.querySelector('.reading-book-edit-form');
    if (currentForm) {
        EDITING_BOOK_KEY = '';
        closeInlineBookEditor(card);
        return;
    }

    document.querySelectorAll('#grid .reading-book-card').forEach((entry) => closeInlineBookEditor(entry));
    const header = card.querySelector('.header');
    if (!(header instanceof HTMLElement)) return;
    EDITING_BOOK_KEY = key;
    setBookEditToggleState(button, true);
    header.insertAdjacentHTML('afterend', renderBookEditForm(book, encodeURIComponent(key), getReadingOwnership(OWNERSHIP_MAP, book)));
    wireBookEditForm(card.querySelector('.reading-book-edit-form'), book, key);
}

async function markLibraryBookReturned(button, book, key) {
    const remoteId = getReadingRemoteId(book);
    if (!remoteId || !book?.returnDate) return;
    const label = button.querySelector('span');
    const originalLabel = label?.textContent || 'Książka oddana';
    button.disabled = true;
    if (label) label.textContent = 'Zapisywanie...';
    try {
        const payload = await updateReadingBook(remoteId, {
            title: book.title || '',
            author: book.author || '',
            pagesRead: Number(book.pagesRead) || 0,
            pagesTotal: Number(book.pagesAll ?? book.pagesTotal) || 0,
            source: 'library',
            returnDate: null,
        });
        const updatedBook = upsertReadingBook(payload?.book || { ...book, returnDate: null, dueDate: null, daysToReturn: null });
        const updatedKey = getBookKey(updatedBook) || key;
        if (updatedKey) {
            OWNERSHIP_MAP[updatedKey] = 'library';
            saveOwnershipMap(OWNERSHIP_MAP);
        }
        broadcastReadingSync('return-library-book');
        renderAll();
        fetchData().catch((error) => console.warn('Reading book refresh failed:', error));
    } catch (error) {
        console.warn('Reading book return failed:', error);
        button.disabled = false;
        button.title = error?.message || 'Nie udało się oznaczyć książki jako oddanej.';
        if (label) label.textContent = 'Błąd — spróbuj ponownie';
        setTimeout(() => {
            if (label) label.textContent = originalLabel;
        }, 2200);
    }
}

// Oblicz KPI: ile stron dziennie i najbliższy deadline
function computePPD(list) {
    const items = list
        .filter((b) => isBookActive(ACTIVE_MAP, b) && isBookLibrary(OWNERSHIP_MAP, b))
        .map((b) => {
            const total = Number(b.pagesAll ?? b.pagesTotal);
            const read = Number(b.pagesRead);
            const daysLeftRaw = Number(b.daysToReturn);
            if (!Number.isFinite(total) || !Number.isFinite(read)) return null;
            if (!Number.isFinite(daysLeftRaw)) return null;
            const remaining = Math.max(0, total - read);
            if (remaining <= 0) return null;
            const daysLeft = Math.max(1, Math.ceil(daysLeftRaw));
            return { daysLeft, remaining, returnDate: b.returnDate };
        })
        .filter(Boolean)
        .sort((a, b) => a.daysLeft - b.daysLeft);

    if (!items.length) {
        return { ppd: 0, nextDate: null, nextDays: null };
    }

    const todayTarget = getReadingTodayTarget(
        list
            .filter((b) => isBookActive(ACTIVE_MAP, b) && isBookLibrary(OWNERSHIP_MAP, b))
            .map((book) => ({
                key: getBookKey(book) || formatBookLabel(book.title || '', book.author || ''),
                label: formatBookLabel(book.title || '', book.author || ''),
                title: book.title || '',
                author: book.author || '',
                pagesTotal: Number(book.pagesAll ?? book.pagesTotal),
                pagesRead: Number(book.pagesRead),
                dueDate: book.returnDate,
            })),
        { now: new Date() },
    );
    const ppd = todayTarget.total;

    const next = items[0];
    return { ppd, nextDate: next.returnDate, nextDays: next.daysLeft };
}

function getForecastBooks() {
    return BOOKS
        .filter((book) => isBookActive(ACTIVE_MAP, book) && isBookLibrary(OWNERSHIP_MAP, book))
        .map((book) => {
            const total = Number(book.pagesAll ?? book.pagesTotal);
            const read = Number(book.pagesRead);
            if (!Number.isFinite(total) || !Number.isFinite(read) || total <= read) return null;
            if (!book.returnDate) return null;
            return {
                key: getBookKey(book) || formatBookLabel(book.title || '', book.author || ''),
                label: formatBookLabel(book.title || '', book.author || ''),
                title: book.title || '',
                author: book.author || '',
                pagesTotal: total,
                pagesRead: read,
                dueDate: book.returnDate,
            };
        })
        .filter(Boolean);
}

async function saveBookPageProgress(book, nextPage) {
    const targetKey = getBookKey(book);
    if (!hasReadingWriteToken()) {
        setPageSaveFeedbackState(targetKey, 'config');
        console.warn('Reading write token is not configured.');
        return false;
    }
    const parsedPage = Math.round(Number(nextPage));
    if (!Number.isFinite(parsedPage)) {
        setPageSaveFeedbackState(targetKey, 'error');
        return false;
    }
    const remoteId = getReadingRemoteId(book);
    if (!remoteId) {
        setPageSaveFeedbackState(targetKey, 'error');
        console.warn('Missing reading book id for page update:', book);
        return false;
    }

    const totalPages = Number(book.pagesAll ?? book.pagesTotal);
    const safePage = Math.max(0, Number.isFinite(totalPages) && totalPages > 0
        ? Math.min(parsedPage, totalPages)
        : parsedPage);
    const prevPages = Number(book.pagesRead) || 0;
    const prevPercent = Number(book.percent) || 0;
    const bookSnapshot = captureReadingLogBookSnapshot({
        meta: {
            bookKey: getBookKey(book),
            bookId: remoteId,
            bookTitle: book.title,
            bookAuthor: book.author,
        },
    });
    let remoteBeforePages = null;
    const knownRemotePages = getReadingKnownRemotePage(book);

    try {
        remoteBeforePages = Number((await fetchRemoteBookSnapshot(remoteId))?.pagesRead);
    } catch (error) {
        console.warn('Reading page baseline fetch failed:', error);
    }

    let out;
    try {
        out = await updateReadingBookProgress(remoteId, safePage, { recordHistory: false });
    } catch (error) {
        setPageSaveFeedbackState(targetKey, 'error');
        console.warn('Reading page update failed:', error);
        return false;
    }

    if (out?.error) {
        setPageSaveFeedbackState(targetKey, 'error');
        console.warn('Sheet error:', out.error);
        return false;
    }

    const nextPages = Number(out.page_current);
    const nextPercent = Number(out.percent);
    const appliedPages = Number.isFinite(nextPages) ? nextPages : safePage;
    const appliedPercent = Number.isFinite(nextPercent)
        ? nextPercent
        : Math.round((appliedPages / Math.max(1, totalPages || 1)) * 100);
    markRecentReadingPageSave(remoteId, appliedPages);

    BOOKS.forEach((entry) => {
        if (getBookKey(entry) !== targetKey) return;
        entry.pagesRead = appliedPages;
        entry.percent = appliedPercent;
    });

    recordReadingProgress({
        baselinePages: resolveReadingProgressBaseline({
            nextPages: appliedPages,
            remotePages: remoteBeforePages,
            localPages: prevPages,
            knownPages: knownRemotePages,
        }),
        currentPages: appliedPages,
        visiblePages: prevPages,
        meta: {
            bookKey: getBookKey(book),
            bookId: remoteId,
            bookTitle: book.title,
            bookAuthor: book.author,
        },
    });

    syncReadingRemotePagesMap(BOOKS);
    ACTIVE_MAP = syncActiveMap(BOOKS);
    OWNERSHIP_MAP = syncOwnershipMap(BOOKS);
    setPageSaveFeedbackState(targetKey, 'success');
    broadcastReadingSync('pages');
    renderAll();
    if (appliedPages !== prevPages) {
        scheduleUndo({
            message: `Zapisano stronę: ${book.title || 'książka'}`,
            duration: 7000,
            onUndo: async () => {
                try {
                    await rollbackReadingPageUpdate(remoteId, prevPages);
                    clearRecentReadingPageSave(remoteId);
                    BOOKS.forEach((entry) => {
                        if (getBookKey(entry) !== targetKey) return;
                        entry.pagesRead = prevPages;
                        entry.percent = prevPercent;
                    });
                    restoreReadingLogBookSnapshot({
                        meta: {
                            bookKey: getBookKey(book),
                            bookId: remoteId,
                            bookTitle: book.title,
                            bookAuthor: book.author,
                        },
                        snapshot: bookSnapshot,
                    });
                    syncReadingRemotePagesMap(BOOKS);
                    ACTIVE_MAP = syncActiveMap(BOOKS);
                    OWNERSHIP_MAP = syncOwnershipMap(BOOKS);
                    broadcastReadingSync('pages-undo');
                    renderAll();
                    await fetchData();
                } catch (error) {
                    setPageSaveFeedbackState(targetKey, 'error');
                    renderAll();
                    console.warn('Reading page undo failed:', error);
                }
            },
        });
    }
    window.setTimeout(() => {
        fetchData().catch((error) => {
            console.warn('Reading post-save refresh failed:', error);
        });
    }, 150);
    return true;
}

function updateHistoryRangeButtons(panel, activeRange) {
    panel.querySelectorAll('.history-range-btn[data-range]').forEach((button) => {
        const active = button.dataset.range === activeRange;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function ensureReadingHistoryHovercard(panel) {
    if (HISTORY_HOVERCARD?.isConnected) return HISTORY_HOVERCARD;

    const hovercard = document.createElement('div');
    hovercard.className = 'history-hovercard';
    hovercard.hidden = true;
    panel.appendChild(hovercard);
    HISTORY_HOVERCARD = hovercard;
    return hovercard;
}

function hideReadingHistoryHovercard() {
    if (!HISTORY_HOVERCARD) return;
    HISTORY_HOVERCARD.classList.remove('is-active');
    HISTORY_HOVERCARD.hidden = true;
}

function positionReadingHistoryHovercard(panel, hovercard, clientX, clientY) {
    const panelRect = panel.getBoundingClientRect();
    const cardRect = hovercard.getBoundingClientRect();
    const margin = 12;
    let left = (clientX - panelRect.left) + 18;
    let top = (clientY - panelRect.top) - cardRect.height - 18;
    const maxLeft = Math.max(margin, panelRect.width - cardRect.width - margin);
    const maxTop = Math.max(margin, panelRect.height - cardRect.height - margin);

    left = Math.min(Math.max(margin, left), maxLeft);
    if (top < margin) {
        top = Math.min((clientY - panelRect.top) + 18, maxTop);
    } else {
        top = Math.min(top, maxTop);
    }

    hovercard.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
}

function showReadingHistoryHovercard(panel, bar, point) {
    const hovercard = ensureReadingHistoryHovercard(panel);
    const tooltipData = bar?.querySelector('.history-bar-tooltip-data');
    if (!tooltipData) {
        hideReadingHistoryHovercard();
        return;
    }

    hovercard.innerHTML = tooltipData.innerHTML;
    hovercard.hidden = false;
    hovercard.classList.add('is-active');
    positionReadingHistoryHovercard(panel, hovercard, point.x, point.y);
}

function renderReadingHistoryPanel() {
    const panel = document.getElementById('reading-history');
    const chart = document.getElementById('reading-history-chart');
    const stats = document.getElementById('reading-history-stats');
    const badge = document.getElementById('reading-history-total-badge');
    const empty = document.getElementById('reading-history-empty');
    const windowLabel = document.getElementById('reading-history-window-label');
    if (!panel || !chart || !stats || !badge || !empty || !windowLabel) return;

    const now = new Date();
    const log = loadReadingLog();
    const windowMeta = buildReadingWindow({ range: HISTORY_RANGE, offset: HISTORY_OFFSET, now });
    const forecastBooks = getForecastBooks();
    const isForecast = windowMeta.isFuture;
    let series = isForecast
        ? buildReadingForecastSeries(forecastBooks, { range: HISTORY_RANGE, offset: HISTORY_OFFSET, now, log })
        : buildReadingHistorySeries(log, { range: HISTORY_RANGE, offset: HISTORY_OFFSET, now });
    let targetSeries = isForecast
        ? []
        : (
            HISTORY_RANGE === 'week' || HISTORY_RANGE === 'month'
                ? buildReadingTargetSeries(forecastBooks, { range: HISTORY_RANGE, offset: HISTORY_OFFSET, now, log })
                : buildReadingForecastSeries(forecastBooks, { range: HISTORY_RANGE, offset: HISTORY_OFFSET, now, log })
        );
    const isYearSummary = HISTORY_RANGE === 'year';
    if (isYearSummary) {
        series = aggregateHistorySeriesByMonth(series);
        targetSeries = aggregateHistorySeriesByMonth(targetSeries);
    }
    const targetByDay = new Map(targetSeries.map((day) => [day.dayKey, Number(day.count) || 0]));
    const todayStart = historyDayStart(now);
    const dayRenderData = series.map((day) => {
        const targetCount = isForecast ? (Number(day.count) || 0) : (targetByDay.get(day.dayKey) || 0);
        const dayStart = historyDayStart(day?.date);
        const showTargetLine = isForecast
            || (targetCount > 0 && !!todayStart && !!dayStart && dayStart >= todayStart);
        return {
            day,
            targetCount,
            showTargetLine,
        };
    });
    const summary = summarizeReadingForecastSeries(series);
    const historySummary = summarizeReadingHistory(log, { now });
    const { ppd, nextDate } = computePPD(BOOKS);
    const maxCount = Math.max(
        1,
        ...dayRenderData.map(({ day }) => Number(day.count) || 0),
        ...dayRenderData.map(({ targetCount, showTargetLine }) => (showTargetLine ? targetCount : 0)),
    );
    const hasAnyHistory = Object.keys(log).length > 0;
    const hasAnyForecast = forecastBooks.length > 0;
    const isCalendarMonth = HISTORY_RANGE === 'month';
    const isStretched = !isCalendarMonth && series.length <= 14;
    const currentBucket = isYearSummary ? (series.find((day) => day.isToday)?.count || 0) : historySummary.today;
    const averageLabel = isYearSummary ? 'Średnio / miesiąc' : 'Średnio / dzień';
    const activeLabel = isYearSummary ? 'Aktywne miesiące' : 'Aktywne dni';
    const maxLabel = isYearSummary
        ? (isForecast ? 'Max miesiąc' : 'Najlepszy miesiąc')
        : (isForecast ? 'Max dzień' : 'Najlepszy dzień');
    const currentLabel = isYearSummary ? 'Ten miesiąc' : 'Dzisiaj';

    updateHistoryRangeButtons(panel, HISTORY_RANGE);
    windowLabel.textContent = getWindowLabel(windowMeta);
    badge.textContent = isForecast
        ? `${pagesLabel(summary.total)} · prognoza / ${READING_RANGE_LABELS[HISTORY_RANGE]}`
        : `${pagesLabel(summary.total)} / ${READING_RANGE_LABELS[HISTORY_RANGE]}`;
    chart.classList.toggle('is-calendar-month', isCalendarMonth);
    chart.classList.toggle('is-stretched', isStretched);
    if (isStretched) {
        chart.style.setProperty('--history-columns', String(series.length));
    } else {
        chart.style.removeProperty('--history-columns');
    }

    const barItems = dayRenderData.map(({ day, targetCount, showTargetLine }) => renderReadingHistoryBar(day, {
        isForecast,
        maxCount,
        fillCount: isForecast ? 0 : (Number(day.count) || 0),
        targetCount,
        showTargetLine,
        showValue: !isForecast,
        labelParts: isYearSummary ? monthSummaryLabelParts(day.date) : undefined,
        scope: isYearSummary ? 'month' : 'day',
    }));

    chart.innerHTML = isCalendarMonth
        ? buildHistoryCalendarMonthMarkup(windowMeta.startDate, barItems)
        : barItems.join('');
    hideReadingHistoryHovercard();
    warmReadingHistoryCoverColors(series).catch((error) => console.warn('Reading history cover colors failed:', error));

    if (isForecast) {
        const maxDayLabel = summary.maxDay
            ? `${pagesLabel(summary.maxDay.count)} (${isYearSummary ? monthSummaryTitle(summary.maxDay.date, false) : historyDayTitle(summary.maxDay.date)})`
            : '—';
        stats.innerHTML = `
            <article class="history-stat">
                <div class="history-stat-label">Łącznie</div>
                <div class="history-stat-value">${formatHistoryStat(summary.total, 'str.')}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">${averageLabel}</div>
                <div class="history-stat-value">${formatHistoryStat(summary.avgPerDay, 'str.')}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">${activeLabel}</div>
                <div class="history-stat-value">${formatHistoryStat(summary.activeDays)}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">${maxLabel}</div>
                <div class="history-stat-value">${maxDayLabel}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">Target teraz</div>
                <div class="history-stat-value">${formatHistoryStat(ppd, 'str.')}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">Najbliższy zwrot</div>
                <div class="history-stat-value">${nextDate ? fmtDate(nextDate) : '—'}</div>
            </article>
        `;
    } else {
        const bestDayLabel = summary.maxDay
            ? `${pagesLabel(summary.maxDay.count)} (${isYearSummary ? monthSummaryTitle(summary.maxDay.date, false) : historyDayTitle(summary.maxDay.date)})`
            : '—';
        stats.innerHTML = `
            <article class="history-stat">
                <div class="history-stat-label">${isYearSummary ? 'W roku' : 'W oknie'}</div>
                <div class="history-stat-value">${formatHistoryStat(summary.total, 'str.')}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">${averageLabel}</div>
                <div class="history-stat-value">${formatHistoryStat(summary.avgPerDay, 'str.')}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">${activeLabel}</div>
                <div class="history-stat-value">${formatHistoryStat(summary.activeDays)}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">${maxLabel}</div>
                <div class="history-stat-value">${bestDayLabel}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">${currentLabel}</div>
                <div class="history-stat-value">${formatHistoryStat(currentBucket, 'str.')}</div>
            </article>
            <article class="history-stat">
                <div class="history-stat-label">Seria</div>
                <div class="history-stat-value">${formatHistoryStat(historySummary.streak, 'dni')}</div>
            </article>
        `;
    }

    const hasInRange = summary.total > 0;
    empty.hidden = hasInRange;
    if (!hasInRange) {
        empty.textContent = isForecast
            ? (hasAnyForecast ? 'Brak targetów w tym okresie.' : 'Brak aktywnych terminów do prognozy.')
            : (hasAnyHistory ? 'Brak wpisów w wybranym okresie.' : 'Brak lokalnej historii czytania.');
    }
}

function wireHistoryControls() {
    const panel = document.getElementById('reading-history');
    const chart = document.getElementById('reading-history-chart');
    if (HISTORY_WIRED || !panel) return;
    ensureReadingHistoryHovercard(panel);

    panel.addEventListener('click', (event) => {
        const rangeBtn = event.target.closest('.history-range-btn[data-range]');
        if (rangeBtn) {
            if (rangeBtn.dataset.range !== HISTORY_RANGE) {
                HISTORY_RANGE = rangeBtn.dataset.range;
                HISTORY_OFFSET = 0;
                renderReadingHistoryPanel();
            }
            return;
        }

        const navBtn = event.target.closest('.history-nav-btn[data-direction]');
        if (!navBtn) return;
        HISTORY_OFFSET += navBtn.dataset.direction === 'next' ? 1 : -1;
        renderReadingHistoryPanel();
    });

    if (chart) {
        chart.addEventListener('pointermove', (event) => {
            const bar = event.target.closest('.history-bar');
            if (!bar || !chart.contains(bar)) {
                hideReadingHistoryHovercard();
                return;
            }

            showReadingHistoryHovercard(panel, bar, {
                x: event.clientX,
                y: event.clientY,
            });
        });

        chart.addEventListener('pointerleave', () => {
            hideReadingHistoryHovercard();
        });

        chart.addEventListener('focusin', (event) => {
            const bar = event.target.closest('.history-bar');
            if (!bar || !chart.contains(bar)) return;
            const rect = bar.getBoundingClientRect();
            showReadingHistoryHovercard(panel, bar, {
                x: rect.left + (rect.width / 2),
                y: rect.top + 8,
            });
        });

        chart.addEventListener('focusout', (event) => {
            if (chart.contains(event.relatedTarget)) return;
            hideReadingHistoryHovercard();
        });
    }

    HISTORY_WIRED = true;
}

// Render całego panelu i listy książek
function renderAll() {
    const unfinishedEl = document.getElementById('unfinished');
    const ownedOnlyEl = document.getElementById('owned-only');
    const wantedOnlyEl = document.getElementById('wanted-only');
    const sortEl = document.getElementById('sort');
    const grid = document.getElementById('grid');
    const ppdEl = document.getElementById('ppd');
    const nextEl = document.getElementById('next');
    const activeEl = document.getElementById('active');
    const avgEl = document.getElementById('avg');
    const pageInfoEl = document.getElementById('reading-page-info');
    const prevPageBtn = document.getElementById('reading-page-prev');
    const nextPageBtn = document.getElementById('reading-page-next');

    if (!(grid instanceof HTMLElement) || !(ppdEl instanceof HTMLElement) || !(nextEl instanceof HTMLElement)
        || !(activeEl instanceof HTMLElement) || !(avgEl instanceof HTMLElement)) {
        return;
    }

    const unfinishedOnly = unfinishedEl && 'checked' in unfinishedEl ? unfinishedEl.checked : true;
    const ownedOnly = ownedOnlyEl && 'checked' in ownedOnlyEl ? ownedOnlyEl.checked : false;
    const wantedOnly = wantedOnlyEl && 'checked' in wantedOnlyEl ? wantedOnlyEl.checked : false;
    const sortVal = sortEl && 'value' in sortEl ? sortEl.value : 'due';
    const pageSize = getReadingPageSize();
    const coversEnabled = isReadingCoversEnabled();
    const renderToken = ++READING_RENDER_TOKEN;
    applyReadingColumnMode();

    // filtr: tylko nieukończone jeśli checkbox zaznaczony
    let list = BOOKS.slice();
    if (unfinishedOnly) {
        list = list.filter(b => !isBookCompleted(b));
    }
    if (wantedOnly) {
        list = list.filter((book) => isReadingBookWanted(OWNERSHIP_MAP, book));
    } else if (ownedOnly) {
        list = list.filter((book) => isReadingBookPossessed(OWNERSHIP_MAP, book));
    }

    // KPI z lewej
    const { ppd, nextDate, nextDays } = computePPD(list);

    ppdEl.textContent = ppd;
    nextEl.textContent = nextDate
        ? `${fmtDate(nextDate)} (${nextDays} dni)`
        : '—';

    const activeCount = BOOKS.filter((b) => isBookActive(ACTIVE_MAP, b) && isReadingBookPossessed(OWNERSHIP_MAP, b)).length;
    const localStats = getLocalReadingStats();
    activeEl.textContent = activeCount;
    avgEl.textContent = localStats.avgPerDay7d;
    renderReadingHistoryPanel();

    const compareSelected = (a, b) => compareBySortVal(a, b, sortVal);
    const compareForList = (a, b) => comparePossessedFirst(a, b) || compareActiveFirst(a, b) || compareSelected(a, b);

    // sortowanie listy książek
    if (unfinishedOnly) {
        list.sort(compareForList);
    } else {
        list.sort((a, b) => {
            const ownershipOrder = comparePossessedFirst(a, b);
            if (ownershipOrder) return ownershipOrder;
            const activeOrder = compareActiveFirst(a, b);
            if (activeOrder) return activeOrder;
            const aDone = isBookCompleted(a);
            const bDone = isBookCompleted(b);
            if (aDone !== bDone) return aDone ? 1 : -1;
            if (aDone && bDone) return compareByDue(a, b);
            return compareSelected(a, b);
        });
    }

    const totalItems = list.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
    READING_CURRENT_PAGE = Math.min(Math.max(1, READING_CURRENT_PAGE), totalPages);
    const pageStart = (READING_CURRENT_PAGE - 1) * pageSize;
    const visibleList = list.slice(pageStart, pageStart + pageSize);
    if (pageInfoEl instanceof HTMLElement) {
        const startLabel = totalItems ? pageStart + 1 : 0;
        const endLabel = Math.min(totalItems, pageStart + pageSize);
        pageInfoEl.textContent = `${READING_CURRENT_PAGE} / ${totalPages} (${startLabel}-${endLabel} z ${totalItems})`;
    }
    if (prevPageBtn instanceof HTMLButtonElement) prevPageBtn.disabled = READING_CURRENT_PAGE <= 1;
    if (nextPageBtn instanceof HTMLButtonElement) nextPageBtn.disabled = READING_CURRENT_PAGE >= totalPages;

    // render kart do #grid
    const coverTargets = [];
    const coverColorTargets = [];
    grid.innerHTML = visibleList.map(b => {
        const pctNum = Math.round(
            (b.pagesRead / Math.max(1, b.pagesAll)) * 100
        );

        const pagesLeft = Math.max(0, b.pagesAll - b.pagesRead);

        const key = getBookKey(b);
        const keyAttr = encodeURIComponent(key || '');
        const canToggle = !!key;
        const canEditBook = !!getReadingRemoteId(b);
        const isEditing = key === EDITING_BOOK_KEY;
        const ownership = getReadingOwnership(OWNERSHIP_MAP, b);
        const isWanted = ownership === 'wanted';
        const canEditPages = isReadingPageEditable(b) && !isWanted;
        const cachedCover = coversEnabled ? getCachedReadingCoverInfo(b, key) : { known: true, url: '' };
        const progressColor = colorForBook(b);
        const cachedCoverColor = coversEnabled ? getCachedReadingCoverColor(key, cachedCover.url) : '';
        if (coversEnabled && key && cachedCover.url && !cachedCoverColor) {
            coverColorTargets.push({ key, url: cachedCover.url });
        }
        if (coversEnabled && key && !cachedCover.known) {
            coverTargets.push({ book: b, key });
        }
        const isActive = isBookActive(ACTIVE_MAP, b);
        const isLibrary = ownership === 'library';
        const ownershipUi = ownershipConfig(ownership);
        const showDue = b.returnDate || isLibrary;

        // tekst badga (termin zwrotu)
        const badgeText = showDue
            ? (
                b.returnDate
                    ? (
                        b.daysToReturn > 0
                            ? `${b.daysToReturn} dni`
                            : (pagesLeft > 0 ? 'Po terminie' : 'Dziś')
                    )
                    : 'Brak'
            )
            : '';

        // klasa badga (kolor czerwony jeśli spóźnione)
        let badgeClass = 'due-badge';
        if (showDue) {
            if (!b.returnDate) {
                badgeClass += ' nodate';
            } else if (b.daysToReturn <= 0 && pagesLeft > 0) {
                badgeClass += ' critical';
            }
        }
        const dueDays = Number(b.daysToReturn);
        const dueColorVal = (b.returnDate && Number.isFinite(dueDays) && dueDays > 0)
            ? dueColor(dueDays)
            : null;
        const badgeStyle = dueColorVal ? ` style="border-color:${dueColorVal};"` : '';

        return `
            <div class="card reading-book-card${coversEnabled ? ' has-cover' : ''}">
                ${coversEnabled ? renderReadingCoverButton(b, key, cachedCover) : ''}
                <div class="reading-card-body">
                    <div class="header">
                        <div>
                            <div class="title">${escapeHtml(b.title || '')}</div>
                            ${renderAuthorMeta(b)}
                        </div>

                        <div class="header-actions">
                            ${canEditBook ? `
                            <button
                                class="reading-book-edit-toggle${isEditing ? ' is-active' : ''}"
                                type="button"
                                data-book-edit="${keyAttr}"
                                aria-expanded="${isEditing ? 'true' : 'false'}"
                                aria-label="${isEditing ? 'Zamknij edycję książki' : 'Edytuj książkę'}"
                                title="${isEditing ? 'Zamknij edycję' : 'Edytuj książkę'}"
                            >
                                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                    <path d="M4 20h4.2L19 9.2a2 2 0 0 0 0-2.8L17.6 5a2 2 0 0 0-2.8 0L4 15.8V20Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                                    <path d="m13.5 6.3 4.2 4.2M4 20l4.8-1.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                                </svg>
                            </button>
                            ` : ''}
                            <div class="reading-book-statuses">
                            ${canToggle ? `
                            <button
                                class="active-toggle ${isActive ? 'is-active' : 'is-inactive'}"
                                type="button"
                                data-book-key="${keyAttr}"
                                aria-pressed="${isActive ? 'true' : 'false'}"
                                title="${isActive ? 'Aktywna' : 'Nieaktywna'}"
                                aria-label="${isActive ? 'Aktywna' : 'Nieaktywna'}"
                            >
                                ${isActive ? '▶' : '⏸'}
                            </button>
                            ` : ''}
                            ${showDue ? `<span class="${badgeClass}"${badgeStyle}>${badgeText}</span>` : ''}
                            ${canToggle ? `
                            <div class="ownership-menu" data-ownership-key="${keyAttr}">
                                <button
                                    class="ownership-toggle ${ownershipUi.className}"
                                    type="button"
                                    data-ownership-value="${escapeAttr(ownership)}"
                                    title="${escapeAttr(ownershipUi.label)}"
                                    aria-label="${escapeAttr(ownershipUi.label)}"
                                >
                                    ${ownershipUi.icon}
                                </button>
                                <div class="ownership-menu-list" role="menu" aria-label="Zmień status książki">
                                    ${['owned', 'library', 'wanted'].map((value) => {
                                        const option = ownershipConfig(value);
                                        return `
                                            <button
                                                class="ownership-menu-item ${ownership === value ? 'is-selected' : ''}"
                                                type="button"
                                                role="menuitemradio"
                                                aria-checked="${ownership === value ? 'true' : 'false'}"
                                                data-ownership-option="${value}"
                                            >
                                                ${option.icon}
                                                <span>${escapeHtml(option.label)}</span>
                                            </button>
                                        `;
                                    }).join('')}
                                    ${isLibrary ? `
                                        <button
                                            class="ownership-menu-item reading-book-returned"
                                            type="button"
                                            role="menuitem"
                                            data-book-returned="${keyAttr}"
                                            title="${b.returnDate ? 'Wyczyść termin zwrotu' : 'Termin zwrotu jest już wyczyszczony'}"
                                            ${b.returnDate ? '' : 'disabled'}
                                        >
                                            <svg class="pill-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M9.4 16.6 5.8 13l-1.4 1.4 5 5L20 8.8l-1.4-1.4-9.2 9.2Z"/></svg>
                                            <span>Książka oddana</span>
                                        </button>
                                    ` : ''}
                                </div>
                            </div>
                            ` : ''}
                            </div>
                        </div>
                    </div>

                    ${isEditing ? renderBookEditForm(b, keyAttr, ownership) : ''}

                    <div class="reading-card-footer">
                        ${renderReadingAwardsStrip(b)}
                        <div class="reading-progress-line">
                            <div class="progress">
                                <div
                                    class="reading-progress-fill"
                                    data-reading-progress-key="${keyAttr}"
                                    style="width:${pctNum}%; background:${cachedCoverColor || progressColor};"
                                ></div>
                            </div>
                        </div>

                        <div class="reading-card-progress-row">
                            ${canEditPages ? `
                                <div class="reading-card-edit">
                                    <label class="sr-only" for="reading-page-${keyAttr}">Ustaw stronę dla ${b.title || 'książki'}</label>
                                    <div class="reading-page-control">
                                        <input
                                            id="reading-page-${keyAttr}"
                                            class="reading-page-input"
                                            type="number"
                                            min="0"
                                            max="${Number.isFinite(Number(b.pagesAll)) ? Number(b.pagesAll) : ''}"
                                            step="1"
                                            value="${Number(b.pagesRead) || 0}"
                                            style="--reading-page-digits:${Math.max(1, Math.min(4, String(Number(b.pagesRead) || 0).length))}"
                                            data-book-page-input="${keyAttr}"
                                        />
                                        <div class="reading-page-stepper">
                                            <button
                                                class="reading-step-btn"
                                                type="button"
                                                data-book-page-step="${keyAttr}"
                                                data-step="1"
                                                aria-label="Następna strona"
                                            >
                                                <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
                                                    <path d="M2.25 7.5 6 3.75 9.75 7.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                                                </svg>
                                            </button>
                                            <button
                                                class="reading-step-btn"
                                                type="button"
                                                data-book-page-step="${keyAttr}"
                                                data-step="-1"
                                                aria-label="Poprzednia strona"
                                            >
                                                <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
                                                    <path d="M2.25 4.5 6 8.25 9.75 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                                                </svg>
                                            </button>
                                        </div>
                                    </div>
                                    <button
                                        class="reading-save-btn"
                                        type="button"
                                        data-book-page-save="${keyAttr}"
                                    >Strona</button>
                                    ${renderPageSaveFeedback(key)}
                                </div>
                            ` : ''}
                            <div class="reading-pages-summary">${b.pagesRead} / ${b.pagesAll} • ${pctNum}%</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    wireReadingDateControls(grid);

    if (coversEnabled) {
        refreshReadingCoverColors(coverTargets, coverColorTargets, renderToken)
            .catch((error) => console.error(error));
    }

    grid.querySelectorAll('.active-toggle[data-book-key]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const key = decodeURIComponent(btn.dataset.bookKey || '');
            if (!key) return;

            const current = ACTIVE_MAP[key] !== false;
            ACTIVE_MAP[key] = !current;
            saveActiveMap(ACTIVE_MAP);
            renderAll();
        });
    });

    grid.querySelectorAll('.reading-book-edit-toggle[data-book-edit]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const key = decodeURIComponent(btn.dataset.bookEdit || '');
            if (!key) return;
            const book = BOOKS.find((entry) => getBookKey(entry) === key);
            if (!book) return;
            toggleInlineBookEditor(btn, book, key);
        });
    });

    grid.querySelectorAll('.reading-book-edit-form[data-book-edit-form]').forEach((form) => {
        const key = decodeURIComponent(form.dataset.bookEditForm || '');
        const book = BOOKS.find((entry) => getBookKey(entry) === key);
        if (!book) return;
        wireBookEditForm(form, book, key);
    });

    grid.querySelectorAll('.reading-book-returned[data-book-returned]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const key = decodeURIComponent(btn.dataset.bookReturned || '');
            const book = BOOKS.find((entry) => getBookKey(entry) === key);
            if (!book) return;
            markLibraryBookReturned(btn, book, key);
        });
    });

    grid.querySelectorAll('.ownership-menu[data-ownership-key]').forEach((menu) => {
        menu.querySelectorAll('.ownership-menu-item[data-ownership-option]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const key = decodeURIComponent(menu.dataset.ownershipKey || '');
                const nextValue = btn.dataset.ownershipOption || '';
                if (!key || !['owned', 'library', 'wanted'].includes(nextValue)) return;

                OWNERSHIP_MAP[key] = nextValue;
                saveOwnershipMap(OWNERSHIP_MAP);
                renderAll();
            });
        });
    });

    grid.querySelectorAll('.ownership-toggle').forEach((btn) => {
        btn.addEventListener('click', () => {
            btn.focus();
        });
    });

    grid.querySelectorAll('.reading-save-btn[data-book-page-save]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const key = decodeURIComponent(btn.dataset.bookPageSave || '');
            if (!key) return;
            const book = BOOKS.find((entry) => getBookKey(entry) === key);
            const input = grid.querySelector(`.reading-page-input[data-book-page-input="${encodeURIComponent(key)}"]`);
            if (!book || !(input instanceof HTMLInputElement)) return;

            setPageSaveFeedbackState(key, 'saving');
            updatePageSaveFeedback(grid, key);
            btn.disabled = true;
            input.disabled = true;
            let saved = false;
            try {
                saved = await saveBookPageProgress(book, input.value);
            } finally {
                btn.disabled = false;
                input.disabled = false;
            }
            if (!saved) updatePageSaveFeedback(grid, key);
        });
    });

    grid.querySelectorAll('.reading-step-btn[data-book-page-step]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const keyAttr = btn.dataset.bookPageStep || '';
            if (!keyAttr) return;
            const input = grid.querySelector(`.reading-page-input[data-book-page-input="${keyAttr}"]`);
            nudgePageInput(input, Number(btn.dataset.step) || 0);
        });
    });

    grid.querySelectorAll('.reading-page-input[data-book-page-input]').forEach((input) => {
        updateReadingPageInputWidth(input);
        input.addEventListener('input', () => updateReadingPageInputWidth(input));
        input.addEventListener('keydown', async (event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            const key = decodeURIComponent(input.dataset.bookPageInput || '');
            if (!key) return;
            const book = BOOKS.find((entry) => getBookKey(entry) === key);
            const btn = grid.querySelector(`.reading-save-btn[data-book-page-save="${encodeURIComponent(key)}"]`);
            if (!book || !(btn instanceof HTMLButtonElement)) return;

            setPageSaveFeedbackState(key, 'saving');
            updatePageSaveFeedback(grid, key);
            btn.disabled = true;
            input.disabled = true;
            let saved = false;
            try {
                saved = await saveBookPageProgress(book, input.value);
            } finally {
                btn.disabled = false;
                input.disabled = false;
            }
            if (!saved) updatePageSaveFeedback(grid, key);
        });
    });
}

// Pobranie JSON z Apps Script
async function fetchData() {
    const requestId = ++FETCH_DATA_REQUEST_ID;
    try {
        ensureReadingLogStart();
        const [primaryResult, remoteResult] = await Promise.allSettled([
            fetchPrimaryReadingData(),
            fetchRemoteReadingState(),
        ]);
        let nextBooks = [];
        let nextStats = normalizeReadingStats();

        if (primaryResult.status === 'fulfilled') {
            const remoteBooks = remoteResult.status === 'fulfilled' ? remoteResult.value.books : [];
            nextBooks = mergeReadingBooksWithRemoteState(primaryResult.value.books, remoteBooks);
            nextStats = normalizeReadingStats({
                ...primaryResult.value.stats,
                avgPagesPerDay: primaryResult.value.stats?.avgPagesPerDay
                    ?? (remoteResult.status === 'fulfilled' ? remoteResult.value.stats?.avgPagesPerDay : undefined),
            });
            if (remoteResult.status === 'rejected') {
                console.warn('Remote reading state unavailable for ID merge:', remoteResult.reason);
            }
        } else if (remoteResult.status === 'fulfilled') {
            console.warn('Primary reading feed failed, using widget state fallback:', primaryResult.reason);
            nextBooks = remoteResult.value.books;
            nextStats = remoteResult.value.stats;
        } else {
            throw primaryResult.reason || remoteResult.reason || new Error('reading_data_unavailable');
        }

        if (requestId !== FETCH_DATA_REQUEST_ID) {
            return false;
        }

        BOOKS = applyRecentReadingBookAddGuards(applyRecentReadingPageSaveGuards(mergeNobelWishlistBooks(nextBooks)));
        STATS = nextStats;
        syncReadingRemotePagesMap(BOOKS);
        ACTIVE_MAP = syncActiveMap(BOOKS);
        OWNERSHIP_MAP = syncOwnershipMap(BOOKS);
        stabilizeLegacyTodayRemoteProgress(BOOKS);
        reconcileTodayReadingLogWithBooks(BOOKS);
        renderAll();
        return true;
    } catch (error) {
        if (requestId !== FETCH_DATA_REQUEST_ID) {
            return false;
        }
        console.error('Failed to load reading dashboard data:', error);
        BOOKS = [];
        STATS = normalizeReadingStats();
        ACTIVE_MAP = {};
        OWNERSHIP_MAP = {};
        renderAll();
        return false;
    }
}

function canAutoRefreshReadingPage() {
    if (document.visibilityState === 'hidden') return false;
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) return true;
    return !active.closest('#reading-add-book-form, .reading-book-edit-form, .reading-card-edit');
}

function autoRefreshReadingPage() {
    if (!canAutoRefreshReadingPage() || READING_AUTO_REFRESH_PROMISE) return READING_AUTO_REFRESH_PROMISE;
    READING_AUTO_REFRESH_PROMISE = refreshReadingSettings()
        .catch(() => {})
        .then(() => fetchData())
        .catch((error) => {
            console.warn('Reading page auto-refresh failed:', error);
        })
        .finally(() => {
            READING_AUTO_REFRESH_PROMISE = null;
        });
    return READING_AUTO_REFRESH_PROMISE;
}

// Inicjalizacja handlerów
async function initReadingDashboard() {
    const refreshBtn   = document.getElementById('refresh');
    const resetForecastBtn = document.getElementById('reset-reading-forecast');
    const coverToggle = document.getElementById('reading-covers-enabled');
    const coverUploadInput = document.getElementById('reading-cover-upload-input');
    const coverSizeInput = document.getElementById('reading-cover-size');
    const addBookForm = document.getElementById('reading-add-book-form');
    const addBookCoverInput = document.getElementById('reading-add-cover');
    const columnButtons = document.querySelectorAll('.reading-view-mode-btn[data-reading-columns]');
    const unfinishedCb = document.getElementById('unfinished');
    const ownedOnlyCb = document.getElementById('owned-only');
    const wantedOnlyCb = document.getElementById('wanted-only');
    const pageSizeSel = document.getElementById('reading-page-size');
    const prevPageBtn = document.getElementById('reading-page-prev');
    const nextPageBtn = document.getElementById('reading-page-next');
    const sortSel      = document.getElementById('sort');
    const backBtn      = document.getElementById('back-btn');

    ensureReadingLogStart();
    wireHistoryControls();
    await whenReadingSettingsReady().catch(() => {});
    applyReadingColumnMode();
    applyReadingCoverSize();
    syncReadingPageSizeControl();

    columnButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const mode = saveReadingColumnMode(btn.dataset.readingColumns);
            applyReadingColumnMode(mode);
        });
    });
    if (coverToggle instanceof HTMLInputElement) {
        coverToggle.checked = isReadingCoversEnabled();
        setReadingCoverStatus(coverToggle.checked ? '' : 'Okładki są wyłączone.');
        coverToggle.addEventListener('change', () => {
            setReadingCoversEnabled(coverToggle.checked);
            setReadingCoverStatus(coverToggle.checked ? 'Okładki włączone.' : 'Okładki są wyłączone.');
            renderAll();
        });
    }
    if (coverSizeInput instanceof HTMLInputElement) {
        coverSizeInput.addEventListener('input', () => {
            saveReadingCoverSize(coverSizeInput.value);
        });
    }
    if (addBookForm instanceof HTMLFormElement) {
        wireReadingDateControls(addBookForm);
        syncAddBookReturnDateVisibility(addBookForm);
        addBookForm.addEventListener('submit', handleAddBookSubmit);
        addBookForm.addEventListener('change', (event) => {
            if (event.target?.name === 'source') {
                syncAddBookReturnDateVisibility(addBookForm);
            }
        });
        addBookForm.addEventListener('reset', () => {
            setTimeout(() => {
                setAddBookCoverName(null);
                syncAddBookReturnDateVisibility(addBookForm);
            }, 0);
        });
    }
    if (addBookCoverInput instanceof HTMLInputElement) {
        addBookCoverInput.addEventListener('change', () => {
            setAddBookCoverName(addBookCoverInput.files?.[0] || null);
        });
    }
    if (coverUploadInput instanceof HTMLInputElement) {
        const grid = document.getElementById('grid');
        if (grid instanceof HTMLElement) {
            grid.addEventListener('click', (event) => {
                const btn = event.target?.closest?.('.reading-cover[data-reading-cover-key]');
                if (!(btn instanceof HTMLElement) || !grid.contains(btn)) return;
                const key = decodeURIComponent(btn.dataset.readingCoverKey || '');
                if (!key) return;
                PENDING_COVER_UPLOAD_KEY = key;
                PENDING_COVER_UPLOAD_BOOK = BOOKS.find((entry) => getBookKey(entry) === key) || null;
                coverUploadInput.value = '';
                coverUploadInput.click();
            });
        }
        coverUploadInput.addEventListener('change', async () => {
            const file = coverUploadInput.files?.[0];
            const key = PENDING_COVER_UPLOAD_KEY;
            const pendingBook = PENDING_COVER_UPLOAD_BOOK;
            PENDING_COVER_UPLOAD_KEY = '';
            PENDING_COVER_UPLOAD_BOOK = null;
            if (!file) {
                setReadingCoverStatus('Nie wybrano pliku okładki.');
                return;
            }
            if (!key) {
                setReadingCoverStatus('Nie udało się powiązać pliku z książką. Kliknij okładkę jeszcze raz.');
                coverUploadInput.value = '';
                return;
            }
            const book = pendingBook || BOOKS.find((entry) => getBookKey(entry) === key);
            if (!book) {
                setReadingCoverStatus('Nie znaleziono książki dla tej okładki.');
                coverUploadInput.value = '';
                return;
            }

            setReadingCoverStatus(`Zapisywanie okładki: ${file.name || 'plik'}...`);
            try {
                const url = await saveReadingCoverUpload(book, key, file);
                if (url) applyReadingCoverColor(key, url);
                setReadingCoverStatus('Okładka zapisana.');
                renderAll();
            } catch (error) {
                console.error(error);
                setReadingCoverStatus(`Nie udało się zapisać okładki${error?.message ? `: ${error.message}` : '.'}`);
            } finally {
                coverUploadInput.value = '';
            }
        });
    }
    if (refreshBtn) {
        refreshBtn.addEventListener('click', fetchData);
    }
    if (resetForecastBtn) {
        resetForecastBtn.addEventListener('click', () => {
            resetReadingTodayForecastPlan();
            renderAll();

            const originalText = resetForecastBtn.textContent;
            resetForecastBtn.textContent = 'Zresetowano prognozę';
            resetForecastBtn.disabled = true;
            setTimeout(() => {
                resetForecastBtn.textContent = originalText || 'Reset dziennej prognozy stron';
                resetForecastBtn.disabled = false;
            }, 1200);
        });
    }
    if (unfinishedCb) {
        unfinishedCb.addEventListener('change', resetReadingPagination);
    }
    if (ownedOnlyCb instanceof HTMLInputElement) {
        ownedOnlyCb.addEventListener('change', () => {
            if (ownedOnlyCb.checked && wantedOnlyCb instanceof HTMLInputElement) wantedOnlyCb.checked = false;
            resetReadingPagination();
        });
    }
    if (wantedOnlyCb instanceof HTMLInputElement) {
        wantedOnlyCb.addEventListener('change', () => {
            if (wantedOnlyCb.checked && ownedOnlyCb instanceof HTMLInputElement) ownedOnlyCb.checked = false;
            resetReadingPagination();
        });
    }
    if (pageSizeSel instanceof HTMLSelectElement) {
        pageSizeSel.addEventListener('change', () => {
            saveReadingPageSize(pageSizeSel.value);
            syncReadingPageSizeControl();
            renderAll();
        });
    }
    if (prevPageBtn instanceof HTMLButtonElement) {
        prevPageBtn.addEventListener('click', () => {
            READING_CURRENT_PAGE -= 1;
            renderAll();
        });
    }
    if (nextPageBtn instanceof HTMLButtonElement) {
        nextPageBtn.addEventListener('click', () => {
            READING_CURRENT_PAGE += 1;
            renderAll();
        });
    }
    if (sortSel) {
        sortSel.addEventListener('change', resetReadingPagination);
    }
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            // przekierowanie na stronę główną
            window.location.href = 'index.html';
        });
    }

    window.addEventListener('storage', (event) => {
        if (!event?.key) return;
        if (event.key === READING_SYNC_KEY) {
            fetchData();
            return;
        }
        if (event.key === READING_COVERS_ENABLED_KEY) {
            if (coverToggle instanceof HTMLInputElement) {
                coverToggle.checked = isReadingCoversEnabled();
            }
            renderAll();
            return;
        }
        if (event.key === 'readingDailyLog.v2' || event.key === 'readingDailyLogStart.v2' || event.key === 'readingForecastPlan.v1') {
            renderReadingHistoryPanel();
        }
    });
    window.addEventListener(READING_HISTORY_CHANGED_EVENT, renderAll);
    window.addEventListener('focus', autoRefreshReadingPage);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') autoRefreshReadingPage();
    });
    window.setInterval(autoRefreshReadingPage, READING_AUTO_REFRESH_MS);

    fetchData();
}

// boot po załadowaniu DOM
document.addEventListener('DOMContentLoaded', initReadingDashboard);
