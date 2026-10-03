// Ustaw to na URL twojego Apps Script Web App (ten /exec)
import { setDailyAchievement } from "./daily-achievements.js";
import { addDashboardNotification } from "./dashboard-notifications-store.js";
import {
    fetchReadingBooks,
    fetchReadingState,
    updateReadingBookProgress,
} from "./reading-api.js";
import { formatReadingDate } from "./reading-date.js";
import {
    buildReadingLogSeries,
    captureReadingLogBookSnapshot,
    ensureReadingLogStart,
    getLocalReadingStats,
    getReadingTodayTarget,
    loadReadingLog,
    READING_HISTORY_CHANGED_EVENT,
    reconcileTodayReadingLogWithBooks,
    recordReadingProgress,
    restoreReadingLogBookSnapshot,
    stabilizeLegacyTodayRemoteProgress,
} from "./reading-history.js";
import {
    applyRecentReadingBookAddGuards,
    applyRecentReadingPageSaveGuards,
    clearRecentReadingPageSave,
    getReadingKnownRemotePage,
    getReadingBookColor,
    getReadingDefaultOwnership,
    getReadingLegacyKeys,
    getReadingMapValue,
    getReadingOwnership,
    getReadingRemoteId,
    getReadingSourceKey,
    isReadingBookWanted,
    markRecentReadingPageSave,
    mergeReadingBooksWithRemoteState,
    normalizeReadingBook,
    resolveReadingProgressBaseline,
    syncReadingRemotePagesMap,
} from "./reading-books.js";
import {
    readReadingActiveMap,
    readReadingOwnershipMap,
    readReadingSelectedBook,
    saveReadingActiveMap,
    saveReadingOwnershipMap,
    saveReadingSelectedBook,
    refreshReadingSettings,
    whenReadingSettingsReady,
} from "./reading-settings-store.js";
import { loadTimeSuffix, startLoadTimer } from "./load-timing.js";
import { scheduleUndo } from "./undo-toast.js";
import {
    getCachedReadingCoverColor,
    getCachedReadingCoverInfo,
    isReadingCoversEnabled,
    preloadReadingCoverUrl,
    READING_COVERS_ENABLED_KEY,
    resolveReadingCover,
    resolveReadingCoverColor,
} from "./reading-covers.js";

const ACTIVE_STORAGE_KEY = "readingActiveMap.v1";
const OWNERSHIP_STORAGE_KEY = "readingOwnershipMap.v1";
const READING_SYNC_KEY = "readingDashboardSync.v1";
const SELECTED_BOOK_STORAGE_KEY = "readingWidgetSelectedBook.v1";
const REMOTE_BASELINE_TIMEOUT_MS = 1200;
const READING_AUTO_REFRESH_MS = 15_000;
const READING_RETURN_NOTIFICATION_DAYS = 7;

let allBooks = [];
let readingBooks = [];
let dailyStats = {};
let currentIndex = 0;
let activeMap = {};
let ownershipMap = {};
let lastSyncedAt = null;
let lastLoadMs = null;
let fetchStateRequestId = 0;
let currentCoverToken = 0;
let readingAutoRefreshPromise = null;

// referencje DOM
const elTitle          = document.getElementById("rdg-book-title");
const elAuthor         = document.getElementById("rdg-book-author");
const elDuePill        = document.getElementById("rdg-due-pill");
const elDueDateTop     = document.getElementById("rdg-due-date");

const elProgressBar    = document.getElementById("rdg-progress-bar");
const elProgressText   = document.getElementById("rdg-progress-text");
const elCoverWrap      = document.getElementById("rdg-cover-wrap");
const elCover          = document.getElementById("rdg-cover");

const elPageInput      = document.getElementById("rdg-page-input");
const elSaveBtn        = document.getElementById("rdg-save-btn");
const elSaveFeedback   = document.getElementById("rdg-save-feedback");

const elTodayTarget    = document.getElementById("rdg-today-target");
const elTodayLeft      = document.getElementById("rdg-today-left");
const elGoalRing       = document.getElementById("rdg-goal-ring");
const elGoalRingValue  = document.getElementById("rdg-goal-ring-value");

const elDueInKpi       = document.getElementById("rdg-due-in");
const elReturnFee      = document.getElementById("rdg-return-fee");
const elDueDateKpi     = document.getElementById("rdg-due-date-2");

const elAvg            = document.getElementById("rdg-avg");
const elStreak         = document.getElementById("rdg-streak");
const elWeek           = document.getElementById("rdg-week");

const elActiveCount    = document.getElementById("rdg-active-count");
const elActiveGrid     = document.getElementById("rdg-active-grid");
const elUpdated        = document.getElementById("rdg-updated");
const elReadingCard    = document.getElementById("reading-card");

const DUE_MAX_DAYS = 31;
const LIBRARY_OVERDUE_FEE_PER_ITEM_PER_DAY = 0.35;
const WIDGET_SAVE_FEEDBACK_MS = 1800;
const DUE_STOPS = [
    { t: 0, c: [126, 34, 206] },  // purple
    { t: 0.33, c: [239, 68, 68] }, // red
    { t: 0.66, c: [251, 191, 36] }, // yellow
    { t: 1, c: [34, 197, 94] },   // green
];

let widgetSaveFeedbackState = "idle";
let widgetSaveFeedbackTimer = null;

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

function getDueDaysValue(book) {
    const raw = Number(book.dueInDays);
    if (Number.isFinite(raw)) return raw;
    if (!book.dueDate) return null;
    const due = new Date(book.dueDate);
    if (!Number.isFinite(due.getTime())) return null;
    const today = new Date();
    const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const end = new Date(due.getFullYear(), due.getMonth(), due.getDate());
    const diffMs = end - start;
    return Math.ceil(diffMs / (24 * 60 * 60 * 1000));
}

function addReadingReturnNotifications() {
    readingBooks.forEach((book) => {
        if (!isBookLibrary(ownershipMap, book) || !book.dueDate) return;
        const dueDays = getDueDaysValue(book);
        if (!Number.isFinite(dueDays) || dueDays > READING_RETURN_NOTIFICATION_DAYS) return;
        const bookKey = getReadingRemoteId(book) || getBookKey(book) || book.title;
        const dueKey = String(book.dueDate).slice(0, 10);
        const timing = dueDays < 0
            ? Math.abs(dueDays) === 1 ? "1 dzień po terminie" : `${Math.abs(dueDays)} dni po terminie`
            : dueDays === 0
                ? "termin zwrotu jest dzisiaj"
                : dueDays === 1 ? "do zwrotu został 1 dzień" : `do zwrotu zostało ${dueDays} dni`;
        addDashboardNotification({
            id: `reading-return:${bookKey}:${dueKey}`,
            title: `Zwrot książki: ${book.title || "książka"}`,
            category: "Czytanie",
            message: `${timing} (${formatDate(book.dueDate)}).`,
            targetId: "reading-card",
        });
    });
}

function formatDate(value) {
    return formatReadingDate(value);
}

function formatCurrency(value) {
    return value.toLocaleString("pl-PL", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function getOverdueFee(days) {
    if (!Number.isFinite(days) || days >= 0) return 0;
    return Math.abs(days) * LIBRARY_OVERDUE_FEE_PER_ITEM_PER_DAY;
}

function getTotalOverdueFee() {
    return readingBooks.reduce((sum, book) => {
        if (!isBookLibrary(ownershipMap, book) || !book.dueDate) return sum;
        return sum + getOverdueFee(getDueDaysValue(book));
    }, 0);
}

function renderReturnFee() {
    if (!(elReturnFee instanceof HTMLElement)) return;
    const fee = getTotalOverdueFee();
    if (!Number.isFinite(fee) || fee <= 0) {
        elReturnFee.textContent = "";
        elReturnFee.hidden = true;
        return;
    }
    elReturnFee.textContent = `Kara: ${formatCurrency(fee)} zł`;
    elReturnFee.hidden = false;
}

function formatSyncDateTime(value) {
    if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
        return "—";
    }
    const time = value.toLocaleTimeString("pl-PL", {
        hour: "2-digit",
        minute: "2-digit",
    });
    return `${formatReadingDate(value)}, ${time}`;
}

function renderUpdatedAt() {
    if (!(elUpdated instanceof HTMLElement)) return;
    const load = loadTimeSuffix(lastLoadMs);
    elUpdated.textContent = `Ostatnia synchronizacja: ${formatSyncDateTime(lastSyncedAt)}${load ? ` · ${load}` : ""}`;
}

function getBookTotalPages(book) {
    const total = Number(book.pagesTotal ?? book.pagesAll);
    return Number.isFinite(total) ? total : "";
}

function getLegacyKeys(book) {
    return getReadingLegacyKeys(book);
}

function getBookKey(book) {
    return getReadingSourceKey(book);
}

function escapeAttr(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/`/g, "&#96;");
}

function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(value);
    }
    return String(value).replace(/["\\]/g, "\\$&");
}

function setWidgetBookProgressColor(key, color) {
    if (!key || !color) return;
    const current = readingBooks[currentIndex];
    if (current && getBookKey(current) === key && elProgressBar instanceof HTMLElement) {
        elProgressBar.style.background = color;
    }
    const selector = `.mini-progress-bar[data-rdg-progress-key="${cssEscape(encodeURIComponent(key))}"]`;
    document.querySelectorAll(selector).forEach((el) => {
        if (el instanceof HTMLElement) el.style.background = color;
    });
}

async function applyWidgetCoverColor(key, url, token = null) {
    if (!key || !url) return;
    try {
        const color = await resolveReadingCoverColor(key, url);
        if (token !== null && token !== currentCoverToken) return;
        setWidgetBookProgressColor(key, color);
    } catch {
        // Remote covers can be blocked by image/CORS rules; keep the existing book color.
    }
}

function renderCurrentCover(book, key, cachedCover) {
    currentCoverToken += 1;
    const token = currentCoverToken;
    const url = cachedCover?.url || "";
    if (!(elCoverWrap instanceof HTMLElement) || !(elCover instanceof HTMLImageElement)) return;
    if (!isReadingCoversEnabled() || !book || !key) {
        elCoverWrap.hidden = true;
        elCover.removeAttribute("src");
        return;
    }
    if (!url) {
        elCoverWrap.hidden = true;
        elCover.removeAttribute("src");
        resolveReadingCover(book, key)
            .then((resolvedUrl) => {
                if (!resolvedUrl || token !== currentCoverToken) return;
                elCover.src = resolvedUrl;
                elCover.alt = "";
                elCoverWrap.hidden = false;
                applyWidgetCoverColor(key, resolvedUrl, token);
            })
            .catch(() => {});
        return;
    }
    elCover.src = url;
    elCover.alt = "";
    elCoverWrap.hidden = false;
    preloadReadingCoverUrl(url);
    applyWidgetCoverColor(key, url, token);
}

function warmWidgetCoverCache() {
    if (!isReadingCoversEnabled() || !readingBooks.length) return;
    const books = readingBooks.slice(0, 12);
    let cursor = 0;

    async function worker() {
        while (cursor < books.length) {
            const book = books[cursor++];
            const key = getBookKey(book);
            if (!key) continue;
            const cached = getCachedReadingCoverInfo(book, key);
            const url = cached.url || await resolveReadingCover(book, key).catch(() => "");
            if (url) preloadReadingCoverUrl(url);
        }
    }

    Promise.all([worker(), worker()]).catch(() => {});
}

function getWidgetReadingBooks() {
    return sortByDueDays(
        allBooks.filter((book) => isBookActive(activeMap, book)),
    );
}

function isBookCompleted(book) {
    const pct = Number(book.percent);
    if (Number.isFinite(pct)) return pct >= 100;
    const total = Number(book.pagesTotal);
    const read = Number(book.pagesRead);
    if (Number.isFinite(total) && Number.isFinite(read) && total > 0) {
        return read >= total;
    }
    return false;
}

function hasBookDueDate(book) {
    return !!book.dueDate;
}

function loadOwnershipMap() {
    const parsed = readReadingOwnershipMap();
    return parsed && typeof parsed === "object" ? parsed : null;
}

function saveOwnershipMap(map) {
    saveReadingOwnershipMap(map);
}

function loadActiveMap() {
    const parsed = readReadingActiveMap();
    return parsed && typeof parsed === "object" ? parsed : null;
}

function saveActiveMap(map) {
    saveReadingActiveMap(map);
}

function loadSelectedBookPreference() {
    return readReadingSelectedBook();
}

function saveSelectedBookPreference(book) {
    const previous = loadSelectedBookPreference();
    if (!book) {
        if (!previous) return;
        saveReadingSelectedBook(null);
        return;
    }

    const remoteId = getReadingRemoteId(book);
    const key = getBookKey(book);
    if (!remoteId && !key) {
        if (!previous) return;
        saveReadingSelectedBook(null);
        return;
    }

    const next = {
        remoteId: remoteId || null,
        key: key || null,
    };
    if (previous?.remoteId === next.remoteId && previous?.key === next.key) return;
    saveReadingSelectedBook(next);
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
        } else if (map[key] === "owned" && hasBookDueDate(book) && legacyValue === undefined) {
            map[key] = "library";
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
    return getReadingOwnership(map, book) === "library";
}

function isBookActive(map, book) {
    const value = getReadingMapValue(map, book);
    if (value === false) return false;
    return !isBookCompleted(book) || value !== false;
}

function dueSortValue(book) {
    if (!hasBookDueDate(book)) return Number.POSITIVE_INFINITY;
    const days = getDueDaysValue(book);
    return Number.isFinite(days) ? days : Number.POSITIVE_INFINITY;
}

function sortByDueDays(list) {
    return list.slice().sort((a, b) => {
        const da = dueSortValue(a);
        const db = dueSortValue(b);
        if (da !== db) return da - db;
        return (a.title || "").localeCompare(b.title || "", "pl");
    });
}

function computeTodayTarget(books) {
    return getReadingTodayTarget(
        books
            .filter((book) => isBookLibrary(ownershipMap, book))
            .map((book) => ({
                key: getBookKey(book) || `${book.title || ""}|${book.author || ""}|${getBookTotalPages(book)}`,
                label: [book.title || "", book.author || ""].filter(Boolean).join(" - "),
                title: book.title || "",
                author: book.author || "",
                pagesTotal: Number(book.pagesTotal ?? book.pagesAll),
                pagesRead: Number(book.pagesRead),
                dueDate: book.dueDate,
            })),
        { now: new Date() },
    ).total;
}

function computeTodayStats(books, todayReadOverride) {
    const todayTarget = computeTodayTarget(books);
    const todayRead = Number.isFinite(todayReadOverride)
        ? todayReadOverride
        : (Number(dailyStats.todayRead) || 0);
    const pagesLeftToday = Math.max(0, todayTarget - todayRead);

    return { todayTarget, todayRead, pagesLeftToday };
}

function broadcastReadingSync(reason = "update") {
    try {
        localStorage.setItem(READING_SYNC_KEY, JSON.stringify({
            reason,
            ts: Date.now(),
        }));
    } catch (err) {
        // ignore storage errors
    }
}

function hasReadingWriteToken() {
    return true;
}

function updateReadingPageInputWidth(input) {
    if (!(input instanceof HTMLInputElement)) return;
    const value = String(input.value || "0").replace(/[^\d]/g, "") || "0";
    const digits = Math.max(1, Math.min(4, value.length));
    input.style.setProperty("--reading-page-digits", String(digits));
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
    input.dispatchEvent(new Event("input", { bubbles: true }));
}

function clearWidgetSaveFeedbackTimer() {
    if (!widgetSaveFeedbackTimer) return;
    window.clearTimeout(widgetSaveFeedbackTimer);
    widgetSaveFeedbackTimer = null;
}

function buildWidgetSaveFeedbackInner(state) {
    if (state === "saving") {
        return `
            <span class="reading-save-feedback-icon is-spinner" aria-hidden="true"></span>
            <span class="reading-save-feedback-label">Zapisywanie</span>
        `;
    }

    if (state === "success") {
        return `
            <span class="reading-save-feedback-icon is-success" aria-hidden="true">✓</span>
            <span class="reading-save-feedback-label">Zapisano</span>
        `;
    }

    if (state === "config") {
        return `
            <span class="reading-save-feedback-icon is-error" aria-hidden="true">!</span>
            <span class="reading-save-feedback-label">Brak tokena</span>
        `;
    }

    if (state === "error") {
        return `
            <span class="reading-save-feedback-icon is-error" aria-hidden="true">!</span>
            <span class="reading-save-feedback-label">Błąd zapisu</span>
        `;
    }

    return "";
}

function renderWidgetSaveFeedback() {
    if (!(elSaveFeedback instanceof HTMLElement)) return;
    const hidden = widgetSaveFeedbackState === "idle";
    elSaveFeedback.className = `reading-save-feedback${hidden ? "" : ` is-${widgetSaveFeedbackState}`}`;
    elSaveFeedback.innerHTML = buildWidgetSaveFeedbackInner(widgetSaveFeedbackState);
    elSaveFeedback.hidden = hidden;
    elSaveFeedback.setAttribute("aria-hidden", hidden ? "true" : "false");
}

function setWidgetSaveFeedbackState(state) {
    clearWidgetSaveFeedbackTimer();
    widgetSaveFeedbackState = state || "idle";
    renderWidgetSaveFeedback();

    if (state === "success" || state === "error" || state === "config") {
        widgetSaveFeedbackTimer = window.setTimeout(() => {
            widgetSaveFeedbackState = "idle";
            widgetSaveFeedbackTimer = null;
            renderWidgetSaveFeedback();
        }, WIDGET_SAVE_FEEDBACK_MS);
    }
}

async function rollbackReadingPageUpdate(remoteId, page) {
    return updateReadingBookProgress(remoteId, page, { recordHistory: false });
}

async function fetchStatePayload() {
    return fetchReadingState();
}

async function fetchPrimaryReadingBooks() {
    const payload = await fetchReadingBooks();
    return Array.isArray(payload?.books) ? payload.books.map(normalizeReadingBook).filter(Boolean) : [];
}

async function fetchCurrentRemotePages(remoteId) {
    if (!remoteId) return null;
    const timeout = new Promise((resolve) => {
        window.setTimeout(() => resolve(null), REMOTE_BASELINE_TIMEOUT_MS);
    });
    const data = await Promise.race([fetchStatePayload(), timeout]);
    if (!data?.activeBooks) return null;
    const books = Array.isArray(data?.activeBooks) ? data.activeBooks.map(normalizeReadingBook).filter(Boolean) : [];
    return Number(books.find((book) => getReadingRemoteId(book) === remoteId)?.pagesRead);
}

// 1. pobierz stan
async function fetchState(preferredRemoteId = null) {
    const requestId = ++fetchStateRequestId;
    const stopTimer = startLoadTimer();
    ensureReadingLogStart();
    const data = await fetchStatePayload();
    const remoteBooks = Array.isArray(data.activeBooks) ? data.activeBooks.map(normalizeReadingBook).filter(Boolean) : [];
    // Lokalny /state zawiera już pełną bibliotekę. /books jest potrzebne tylko
    // jako fallback dla starszego backendu, który zwracał samo activeBooks.
    const stateBooks = Array.isArray(data.books)
        ? data.books.map(normalizeReadingBook).filter(Boolean)
        : null;
    const primaryBooks = stateBooks || await fetchPrimaryReadingBooks().catch(() => null);
    const nextBooks = primaryBooks
        ? mergeReadingBooksWithRemoteState(primaryBooks, remoteBooks)
        : remoteBooks;
    if (requestId !== fetchStateRequestId) {
        return false;
    }

    dailyStats = data.dailyStats || {};
    allBooks = applyRecentReadingBookAddGuards(applyRecentReadingPageSaveGuards(nextBooks));
    lastSyncedAt = new Date();
    lastLoadMs = stopTimer();
    syncReadingRemotePagesMap(allBooks);
    activeMap = syncActiveMap(allBooks);
    ownershipMap = syncOwnershipMap(allBooks);
    stabilizeLegacyTodayRemoteProgress(allBooks);
    reconcileTodayReadingLogWithBooks(allBooks);

    const savedSelection = loadSelectedBookPreference();
    const currentBook = (preferredRemoteId
        ? allBooks.find((book) => getReadingRemoteId(book) === preferredRemoteId) || null
        : null)
        || (savedSelection?.remoteId
            ? allBooks.find((book) => getReadingRemoteId(book) === savedSelection.remoteId) || null
            : null)
        || (savedSelection?.key
            ? allBooks.find((book) => getBookKey(book) === savedSelection.key) || null
            : null)
        || (allBooks[data.currentIndex] || null);
    const currentKey = currentBook ? getBookKey(currentBook) : null;

    readingBooks = getWidgetReadingBooks();

    currentIndex = currentKey
        ? readingBooks.findIndex((book) => getBookKey(book) === currentKey)
        : 0;

    if (currentIndex < 0) currentIndex = 0;
    saveSelectedBookPreference(readingBooks[currentIndex] || null);
    addReadingReturnNotifications();
    return true;
}

// 2. zapisz nowe strony (GET, token, bez POST)
async function handleSavePages() {
    if (!hasReadingWriteToken()) {
        setWidgetSaveFeedbackState("config");
        console.warn("Reading write token is not configured.");
        return;
    }
    const parsedPage = Math.round(Number(elPageInput.value));
    if (!Number.isFinite(parsedPage)) {
        setWidgetSaveFeedbackState("error");
        return;
    }

    const book = readingBooks[currentIndex];
    if (!book) {
        setWidgetSaveFeedbackState("error");
        return;
    }
    const remoteId = getReadingRemoteId(book);
    if (!remoteId) {
        setWidgetSaveFeedbackState("error");
        console.warn("Missing reading book id for page update:", book);
        return;
    }
    setWidgetSaveFeedbackState("saving");
    if (elSaveBtn) elSaveBtn.disabled = true;
    if (elPageInput) elPageInput.disabled = true;
    const totalPages = Number(book.pagesTotal ?? book.pagesAll);
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
        remoteBeforePages = await fetchCurrentRemotePages(remoteId);
    } catch (error) {
        console.warn("Reading widget baseline fetch failed:", error);
    }

    try {
        const out = await updateReadingBookProgress(remoteId, safePage, { recordHistory: false });

        if (out?.error) {
            setWidgetSaveFeedbackState("error");
            console.warn("Sheet error:", out.error);
            return;
        }

        const nextPages = Number(out.page_current);
        const nextPercent = Number(out.percent);
        const appliedPages = Number.isFinite(nextPages) ? nextPages : safePage;
        const appliedPercent = Number.isFinite(nextPercent)
            ? nextPercent
            : Math.round((appliedPages / Math.max(1, totalPages || 1)) * 100);
        markRecentReadingPageSave(remoteId, appliedPages);

        // aktualizuj UI lokalnie bez refetch całości
        book.pagesRead = appliedPages;
        book.percent = appliedPercent;
        activeMap = syncActiveMap(allBooks);
        ownershipMap = syncOwnershipMap(allBooks);

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
        syncReadingRemotePagesMap(allBooks);
        broadcastReadingSync("pages");
        lastSyncedAt = new Date();
        const currentKey = getBookKey(book);
        readingBooks = getWidgetReadingBooks();
        currentIndex = currentKey
            ? readingBooks.findIndex((entry) => getBookKey(entry) === currentKey)
            : currentIndex;
        if (currentIndex < 0 || currentIndex >= readingBooks.length) currentIndex = 0;
        saveSelectedBookPreference(readingBooks[currentIndex] || null);

        renderCurrent();
        renderActiveGrid();
        renderUpdatedAt();
        setWidgetSaveFeedbackState("success");
        if (appliedPages !== prevPages) {
            scheduleUndo({
                message: `Zapisano stronę: ${book.title || 'książka'}`,
                duration: 7000,
                onUndo: async () => {
                    try {
                        await rollbackReadingPageUpdate(remoteId, prevPages);
                        clearRecentReadingPageSave(remoteId);
                        book.pagesRead = prevPages;
                        book.percent = prevPercent;
                        restoreReadingLogBookSnapshot({
                            meta: {
                                bookKey: getBookKey(book),
                                bookId: remoteId,
                                bookTitle: book.title,
                                bookAuthor: book.author,
                            },
                            snapshot: bookSnapshot,
                        });
                        syncReadingRemotePagesMap(allBooks);
                        broadcastReadingSync("pages-undo");
                        lastSyncedAt = new Date();
                        await fetchState(remoteId);
                        renderCurrent();
                        renderActiveGrid();
                        renderUpdatedAt();
                    } catch (error) {
                        setWidgetSaveFeedbackState("error");
                        console.warn("Reading widget undo failed:", error);
                    }
                },
            });
        }
        window.setTimeout(() => {
            fetchState(remoteId)
                .then(() => {
                    renderCurrent();
                    renderActiveGrid();
                    renderUpdatedAt();
                })
                .catch((error) => {
                    console.warn("Reading widget post-save refresh failed:", error);
                });
        }, 150);
    } catch (error) {
        setWidgetSaveFeedbackState("error");
        console.warn("Reading widget page update failed:", error);
    } finally {
        if (elSaveBtn) elSaveBtn.disabled = false;
        if (elPageInput) elPageInput.disabled = false;
    }
}

// wybór książki
function handleSelectBook(idx) {
    currentIndex = idx;
    saveSelectedBookPreference(readingBooks[currentIndex] || null);
    renderCurrent();
}

function canAutoRefreshReadingWidget() {
    if (document.visibilityState === "hidden") return false;
    if (elSaveBtn?.disabled) return false;
    return document.activeElement !== elPageInput;
}

function autoRefreshReadingWidget() {
    if (!canAutoRefreshReadingWidget() || readingAutoRefreshPromise) return readingAutoRefreshPromise;
    const preferredRemoteId = getReadingRemoteId(readingBooks[currentIndex]);
    readingAutoRefreshPromise = refreshReadingSettings()
        .catch(() => {})
        .then(() => fetchState(preferredRemoteId))
        .then(() => {
            renderCurrent();
            renderActiveGrid();
            renderUpdatedAt();
        })
        .catch((error) => {
            console.warn("Reading widget auto-refresh failed:", error);
        })
        .finally(() => {
            readingAutoRefreshPromise = null;
        });
    return readingAutoRefreshPromise;
}

function polishDayCount(days) {
    const value = Math.max(0, Math.round(Number(days) || 0));
    if (value === 1) return "1 dzień serii";
    const lastTwo = value % 100;
    const last = value % 10;
    if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) {
        return `${value} dni serii`;
    }
    return `${value} dni serii`;
}

function readingWeekdayLabel(dateValue) {
    const date = new Date(dateValue);
    if (!Number.isFinite(date.getTime())) return "—";
    return date.toLocaleDateString("pl-PL", { weekday: "narrow" }).replace(".", "");
}

function previousReadingStreak(days, dailyGoal) {
    if (!(dailyGoal > 0)) return 0;
    let streak = 0;
    for (let index = days.length - 2; index >= 0; index -= 1) {
        if ((Number(days[index]?.count) || 0) < dailyGoal) break;
        streak += 1;
    }
    return streak;
}

function renderReadingWeek(days, dailyGoal) {
    if (!(elWeek instanceof HTMLElement)) return;
    const fragment = document.createDocumentFragment();

    days.forEach((day) => {
        const pages = Math.max(0, Math.round(Number(day?.count) || 0));
        const isToday = day?.isToday === true;
        const isComplete = dailyGoal > 0 && pages >= dailyGoal;
        const date = new Date(day?.date);
        const dayName = Number.isFinite(date.getTime())
            ? `${date.toLocaleDateString("pl-PL", { weekday: "long" })}, ${formatReadingDate(date)}`
            : "Dzień";

        const item = document.createElement("div");
        item.className = "reading-week-day";
        item.classList.toggle("is-today", isToday);
        item.classList.toggle("has-reading", pages > 0);
        item.classList.toggle("is-complete", isComplete);
        item.setAttribute("aria-label", `${dayName}: ${pages} str.${isToday && !isComplete ? ", cel w toku" : ""}`);

        const label = document.createElement("span");
        label.className = "reading-week-label";
        label.textContent = readingWeekdayLabel(day?.date);

        const dot = document.createElement("span");
        dot.className = "reading-week-dot";
        dot.setAttribute("aria-hidden", "true");
        dot.textContent = isComplete ? "✓" : "";

        const count = document.createElement("span");
        count.className = "reading-week-pages";
        count.textContent = String(pages);

        item.append(label, dot, count);
        fragment.append(item);
    });

    elWeek.replaceChildren(fragment);
}

// render sekcji wybranej książki
function renderCurrent() {
    const localStats = getLocalReadingStats();
    const stats = computeTodayStats(readingBooks, localStats.todayRead);
    const isDailyGoalReached = stats.todayTarget > 0 && stats.todayRead >= stats.todayTarget;
    const recentDays = buildReadingLogSeries(loadReadingLog(), { days: 7 });
    const streakDays = previousReadingStreak(recentDays, stats.todayTarget) + (isDailyGoalReached ? 1 : 0);
    const goalProgress = stats.todayTarget > 0
        ? clamp(Math.round((stats.todayRead / stats.todayTarget) * 100), 0, 100)
        : 0;

    if (elReadingCard instanceof HTMLElement) {
        elReadingCard.classList.toggle("is-goal-complete", isDailyGoalReached);
    }
    setDailyAchievement("reading", stats.todayTarget > 0 ? {
        state: isDailyGoalReached ? "complete" : "pending",
        value: `${stats.todayRead} str.`,
        detail: isDailyGoalReached ? "Dzisiejsze strony przeczytane" : `${stats.pagesLeftToday} str. zostało`,
        progress: goalProgress,
    } : {
        state: "neutral",
        value: "Brak planu",
        detail: "Bez celu czytania na dziś",
        eligible: false,
    });

    elTodayTarget.textContent = stats.todayTarget > 0
        ? `${stats.todayRead}/${stats.todayTarget} str.`
        : `${stats.todayRead} str.`;
    elTodayLeft.textContent = "";
    elTodayLeft.hidden = true;

    elAvg.textContent    = `${localStats.avgPerDay7d} str./dzień`;
    elStreak.textContent = polishDayCount(streakDays);
    renderReadingWeek(recentDays, stats.todayTarget);

    if (elGoalRing instanceof HTMLElement) {
        elGoalRing.style.setProperty("--reading-goal-progress", `${goalProgress * 3.6}deg`);
        elGoalRing.classList.toggle("is-complete", isDailyGoalReached);
        elGoalRing.setAttribute("aria-valuemax", String(stats.todayTarget));
        elGoalRing.setAttribute("aria-valuenow", String(Math.min(stats.todayRead, stats.todayTarget)));
    }
    if (elGoalRingValue) {
        elGoalRingValue.textContent = isDailyGoalReached ? "✓" : `${goalProgress}%`;
    }

    const book = readingBooks[currentIndex];
    if (!book) {
        currentCoverToken += 1;
        if (elCoverWrap instanceof HTMLElement) elCoverWrap.hidden = true;
        if (elCover instanceof HTMLImageElement) elCover.removeAttribute("src");
        elTitle.textContent  = "Brak aktywnych książek";
        elAuthor.textContent = "";

        elDuePill.hidden = true;
        elDueDateTop.hidden = true;
        elDuePill.textContent = "";
        elDuePill.classList.remove("danger");
        elDuePill.style.borderColor = "";
        elDueDateTop.textContent = "";

        elProgressBar.style.width = "0%";
        elProgressText.textContent = "0 / 0 • 0%";
        elPageInput.value = 0;

        elDueInKpi.textContent = "—";
        elDueInKpi.classList.remove("danger");
        renderReturnFee();
        elDueDateKpi.textContent = "—";
        return;
    }

    elTitle.textContent  = book.title;
    elAuthor.textContent = book.author || "—";

    const hasDue = !!book.dueDate;
    const isLibrary = isBookLibrary(ownershipMap, book);
    const showDue = hasDue || isLibrary;
    const dueDays = getDueDaysValue(book);
    if (!showDue) {
        elDuePill.hidden = false;
        elDueDateTop.hidden = false;
        elDuePill.textContent = "—";
        elDuePill.classList.remove("danger");
        elDuePill.style.borderColor = "";
        elDueDateTop.textContent = "—";
    } else {
        elDuePill.hidden = false;
        elDueDateTop.hidden = false;
        if (!hasDue) {
            elDuePill.textContent = "Brak";
            elDuePill.classList.remove("danger");
            elDuePill.style.borderColor = "";
        } else if (!Number.isFinite(dueDays)) {
            elDuePill.textContent = "Zwrot";
            elDuePill.classList.remove("danger");
            elDuePill.style.borderColor = "";
        } else {
            if (dueDays <= 0) {
                elDuePill.textContent = dueDays === 0 ? "Dziś" : "Po terminie";
            } else {
                elDuePill.textContent = `${dueDays} dni`;
            }
            if (dueDays <= 0) {
                elDuePill.classList.add("danger");
                elDuePill.style.borderColor = "";
            } else {
                elDuePill.classList.remove("danger");
                const c = dueColor(dueDays);
                if (c) elDuePill.style.borderColor = c;
            }
        }
        elDueDateTop.textContent = formatDate(book.dueDate);
    }

    const key = getBookKey(book);
    const cachedCover = isReadingCoversEnabled() ? getCachedReadingCoverInfo(book, key) : { known: true, url: "" };
    const coverColor = cachedCover.url ? getCachedReadingCoverColor(key, cachedCover.url) : "";
    renderCurrentCover(book, key, cachedCover);

    const pct = book.percent || 0;
    const pagesRead = Number(book.pagesRead) || 0;
    const pagesTotal = Number(book.pagesTotal) || 0;
    elProgressBar.style.width = pct + "%";
    elProgressBar.style.background = coverColor || getReadingBookColor(book);
    elProgressText.textContent = `${pagesRead} / ${pagesTotal} • ${pct}%`;

    elPageInput.value = pagesRead;
    updateReadingPageInputWidth(elPageInput);
    elPageInput.min = "0";
    elPageInput.max = pagesTotal > 0 ? String(pagesTotal) : "";

    if (!showDue) {
        elDueInKpi.textContent = "—";
        elDueInKpi.classList.remove("danger");
        renderReturnFee();
        elDueDateKpi.textContent = "—";
    } else if (!hasDue) {
        elDueInKpi.textContent = "—";
        elDueInKpi.classList.remove("danger");
        renderReturnFee();
        elDueDateKpi.textContent = "Brak terminu";
    } else {
        if (Number.isFinite(dueDays)) {
            elDueInKpi.textContent = `${dueDays} dni`;
        } else {
            elDueInKpi.textContent = "—";
        }
        renderReturnFee();
        if (Number.isFinite(dueDays) && dueDays <= 0) {
            elDueInKpi.classList.add("danger");
        } else {
            elDueInKpi.classList.remove("danger");
        }
        elDueDateKpi.textContent = formatDate(book.dueDate);
    }
}

// render listy aktywnych
function renderActiveGrid() {
    elActiveGrid.innerHTML = "";
    elActiveCount.textContent = `(${readingBooks.length})`;

    readingBooks.forEach((book, idx) => {
        const key = getBookKey(book);
        const cachedCover = isReadingCoversEnabled() ? getCachedReadingCoverInfo(book, key) : { known: true, url: "" };
        const coverColor = cachedCover.url ? getCachedReadingCoverColor(key, cachedCover.url) : "";
        if (cachedCover.url) preloadReadingCoverUrl(cachedCover.url);
        let dueBadgeText, dueBadgeClass;
        const hasDue = !!book.dueDate;
        const isLibrary = isBookLibrary(ownershipMap, book);
        const showDue = hasDue || isLibrary;
    const dueDays = getDueDaysValue(book);
        if (showDue) {
            if (!hasDue) {
                dueBadgeText = "Brak";
                dueBadgeClass = "nodate";
            } else if (!Number.isFinite(dueDays)) {
                dueBadgeText = "Zwrot";
                dueBadgeClass = "";
            } else {
                if (dueDays <= 0) {
                    dueBadgeText = dueDays === 0 ? "Dziś" : "Po terminie";
                } else {
                    dueBadgeText = `${dueDays} dni`;
                }
                dueBadgeClass = (dueDays <= 0) ? "critical" : "";
            }
        }
        const dueColorVal = (hasDue && Number.isFinite(dueDays) && dueDays > 0)
            ? dueColor(dueDays)
            : null;
        const dueBadgeStyle = dueColorVal ? ` style="border-color:${dueColorVal};"` : "";

        const pagesRead = Number(book.pagesRead) || 0;
        const pagesTotal = Number(book.pagesTotal) || 0;

        const btn = document.createElement("button");
        btn.className = "reading-bookbtn";
        btn.setAttribute("type", "button");
        btn.innerHTML = `
            <div class="rb-top">
                <div class="rb-head">
                    <div class="rb-title">${book.title}</div>
                    <div class="rb-author">${book.author || ""}</div>
                </div>
                ${showDue ? `<span class="due-badge rb-due ${dueBadgeClass}"${dueBadgeStyle}>${dueBadgeText}</span>` : ""}
            </div>
            <div class="rb-stats">
                <span class="rb-pages">${pagesRead}/${pagesTotal}</span>
                <span class="rb-percent">${book.percent}%</span>
            </div>
            <div class="mini-progress">
                <div
                    class="mini-progress-bar"
                    data-rdg-progress-key="${escapeAttr(encodeURIComponent(key || ""))}"
                    style="width:${book.percent}%; background:${coverColor || getReadingBookColor(book)};"
                ></div>
            </div>
            <div class="mini-progress-meta">${book.percent}%</div>
        `;

        if (key && cachedCover.url) {
            applyWidgetCoverColor(key, cachedCover.url);
        }

        btn.addEventListener("click", () => handleSelectBook(idx));
        elActiveGrid.appendChild(btn);
    });
    warmWidgetCoverCache();
}

// init
async function init() {
    ensureReadingLogStart();
    await whenReadingSettingsReady().catch(() => {});
    await fetchState();
    renderWidgetSaveFeedback();
    renderUpdatedAt();
    document.querySelectorAll(".reading-step-btn[data-page-step]").forEach((btn) => {
        btn.addEventListener("click", () => {
            nudgePageInput(elPageInput, Number(btn.dataset.pageStep) || 0);
        });
    });
    if (elSaveBtn) {
        elSaveBtn.addEventListener("click", handleSavePages);
    }
    if (elPageInput) {
        updateReadingPageInputWidth(elPageInput);
        elPageInput.addEventListener("input", () => updateReadingPageInputWidth(elPageInput));
    }
    window.addEventListener("storage", (evt) => {
        if (!evt || !evt.key) return;
        if (evt.key === READING_SYNC_KEY) {
            const preferredRemoteId = getReadingRemoteId(readingBooks[currentIndex]);
            fetchState(preferredRemoteId).then(() => {
                if (currentIndex >= readingBooks.length) currentIndex = 0;
                renderCurrent();
                renderActiveGrid();
                renderUpdatedAt();
            });
            return;
        }
        if (evt.key === ACTIVE_STORAGE_KEY || evt.key === OWNERSHIP_STORAGE_KEY) {
            const preferredKey = getBookKey(readingBooks[currentIndex]);
            activeMap = syncActiveMap(allBooks);
            ownershipMap = syncOwnershipMap(allBooks);
            readingBooks = getWidgetReadingBooks();
            currentIndex = preferredKey
                ? readingBooks.findIndex((book) => getBookKey(book) === preferredKey)
                : currentIndex;
            if (currentIndex < 0 || currentIndex >= readingBooks.length) currentIndex = 0;
            saveSelectedBookPreference(readingBooks[currentIndex] || null);
            renderCurrent();
            renderActiveGrid();
            renderUpdatedAt();
        }
        if (evt.key === READING_COVERS_ENABLED_KEY || evt.key === "readingBookCoverCache.v1" || evt.key === "readingBookCoverColors.v1" || evt.key === "readingBookCoverUploads.v1") {
            renderCurrent();
            renderActiveGrid();
        }
    });
    window.addEventListener(READING_HISTORY_CHANGED_EVENT, () => {
        renderCurrent();
        renderActiveGrid();
        renderUpdatedAt();
    });
    window.addEventListener("pageshow", () => {
        const preferredKey = getBookKey(readingBooks[currentIndex]);
        activeMap = syncActiveMap(allBooks);
        ownershipMap = syncOwnershipMap(allBooks);
        readingBooks = getWidgetReadingBooks();
        currentIndex = preferredKey
            ? readingBooks.findIndex((book) => getBookKey(book) === preferredKey)
            : currentIndex;
        if (currentIndex < 0 || currentIndex >= readingBooks.length) currentIndex = 0;
        saveSelectedBookPreference(readingBooks[currentIndex] || null);
        renderCurrent();
        renderActiveGrid();
        renderUpdatedAt();
        autoRefreshReadingWidget();
    });
    window.addEventListener("focus", autoRefreshReadingWidget);
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") autoRefreshReadingWidget();
    });
    window.setInterval(autoRefreshReadingWidget, READING_AUTO_REFRESH_MS);
    renderCurrent();
    renderActiveGrid();
    renderUpdatedAt();
}

init();
