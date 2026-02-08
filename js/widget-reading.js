// Ustaw to na URL twojego Apps Script Web App (ten /exec)
const API_URL = "https://script.google.com/macros/s/AKfycbyHo8WLZ0NR22ePdnlM4PTs6LriziEVniDMF3TXJxw3w9TgYilFCSzisOpxt5iDutDI/exec";

// Ten sam token co w Apps Script READING_TOKEN
const READING_TOKEN = "WSTAW_TUTAJ_SWÓJ_SEKRETNY_TOKEN";

const ACTIVE_STORAGE_KEY = "readingActiveMap.v1";
const OWNERSHIP_STORAGE_KEY = "readingOwnershipMap.v1";
const READING_LOG_KEY = "readingDailyLog.v2";
const READING_LOG_START_KEY = "readingDailyLogStart.v2";

let allBooks = [];
let readingBooks = [];
let dailyStats = {};
let currentIndex = 0;
let activeMap = {};
let ownershipMap = {};

// referencje DOM
const elTitle          = document.getElementById("rdg-book-title");
const elAuthor         = document.getElementById("rdg-book-author");
const elDuePill        = document.getElementById("rdg-due-pill");
const elDueDateTop     = document.getElementById("rdg-due-date");

const elProgressBar    = document.getElementById("rdg-progress-bar");
const elProgressText   = document.getElementById("rdg-progress-text");

const elPageInput      = document.getElementById("rdg-page-input");
const elSaveBtn        = document.getElementById("rdg-save-btn");

const elTodayTarget    = document.getElementById("rdg-today-target");
const elTodayLeft      = document.getElementById("rdg-today-left");

const elDueInKpi       = document.getElementById("rdg-due-in");
const elDueDateKpi     = document.getElementById("rdg-due-date-2");

const elAvg            = document.getElementById("rdg-avg");
const elStreak         = document.getElementById("rdg-streak");

const elActiveCount    = document.getElementById("rdg-active-count");
const elActiveGrid     = document.getElementById("rdg-active-grid");

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

function formatDate(value) {
    if (!value) return "—";
    const s = String(value).trim();
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) {
        const dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
        if (Number.isFinite(dt.getTime())) {
            return dt.toLocaleDateString("pl-PL", { day: "numeric", month: "short", year: "numeric" });
        }
    }
    const dt = new Date(s);
    if (Number.isFinite(dt.getTime())) {
        return dt.toLocaleDateString("pl-PL", { day: "numeric", month: "short", year: "numeric" });
    }
    return s;
}

function getBookTotalPages(book) {
    const total = Number(book.pagesTotal ?? book.pagesAll);
    return Number.isFinite(total) ? total : "";
}

function getLegacyKeys(book) {
    const keys = [];
    if (book.book_id != null) keys.push(String(book.book_id));
    if (book.bookId != null) keys.push(String(book.bookId));
    if (book.id != null) keys.push(String(book.id));
    return keys;
}

function getBookKey(book) {
    const title = (book.title || "").trim().toLowerCase();
    const author = (book.author || "").trim().toLowerCase();
    const total = getBookTotalPages(book);
    const composite = [title, author, total].filter((v) => v !== "").join("|");
    return composite || "";
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

function getDateKey(date) {
    const dt = date ? new Date(date) : new Date();
    const yyyy = dt.getFullYear();
    const mm = String(dt.getMonth() + 1).padStart(2, "0");
    const dd = String(dt.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
}

function parseDateKey(key) {
    const match = String(key || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function addDays(date, days) {
    const dt = new Date(date);
    dt.setDate(dt.getDate() + days);
    return dt;
}

function loadReadingLog() {
    try {
        const raw = localStorage.getItem(READING_LOG_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : null;
    } catch (err) {
        return null;
    }
}

function saveReadingLog(map) {
    try {
        localStorage.setItem(READING_LOG_KEY, JSON.stringify(map));
    } catch (err) {
        // ignore storage errors
    }
}

function ensureReadingLogStart() {
    try {
        const stored = localStorage.getItem(READING_LOG_START_KEY);
        if (stored) return stored;
        const key = getDateKey();
        localStorage.setItem(READING_LOG_START_KEY, key);
        return key;
    } catch (err) {
        return getDateKey();
    }
}

function updateReadingLog(delta, dateKey) {
    if (!Number.isFinite(delta) || delta <= 0) return;
    ensureReadingLogStart();
    const key = dateKey || getDateKey();
    const log = loadReadingLog() || {};
    const current = Number(log[key]) || 0;
    log[key] = current + delta;
    saveReadingLog(log);
}

function getLocalReadingStats() {
    const log = loadReadingLog() || {};
    const startKey = ensureReadingLogStart();
    const startDate = parseDateKey(startKey) || new Date();
    const today = new Date();
    const startMidnight = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate());
    const todayMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const daysSinceStart = Math.max(
        1,
        Math.floor((todayMidnight - startMidnight) / (24 * 60 * 60 * 1000)) + 1
    );
    const windowDays = Math.min(7, daysSinceStart);

    let total = 0;
    for (let i = 0; i < windowDays; i += 1) {
        const key = getDateKey(addDays(todayMidnight, -i));
        total += Number(log[key]) || 0;
    }

    let streak = 0;
    for (let i = 0; i < daysSinceStart; i += 1) {
        const key = getDateKey(addDays(todayMidnight, -i));
        const val = Number(log[key]) || 0;
        if (val <= 0) break;
        streak += 1;
    }

    const todayKey = getDateKey(todayMidnight);

    return {
        avgPerDay7d: Math.round(total / windowDays),
        streakDays: streak,
        todayRead: Number(log[todayKey]) || 0,
    };
}

function loadOwnershipMap() {
    try {
        const raw = localStorage.getItem(OWNERSHIP_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : null;
    } catch (err) {
        return null;
    }
}

function saveOwnershipMap(map) {
    try {
        localStorage.setItem(OWNERSHIP_STORAGE_KEY, JSON.stringify(map));
    } catch (err) {
        // ignore storage errors
    }
}

function loadActiveMap() {
    try {
        const raw = localStorage.getItem(ACTIVE_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : null;
    } catch (err) {
        return null;
    }
}

function saveActiveMap(map) {
    try {
        localStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify(map));
    } catch (err) {
        // ignore storage errors
    }
}

function syncActiveMap(books) {
    let map = loadActiveMap();
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
        if (!(key in map)) {
            let value;
            const legacy = getLegacyKeys(book);
            for (let i = 0; i < legacy.length; i += 1) {
                if (legacy[i] in map) {
                    value = map[legacy[i]];
                    break;
                }
            }
            map[key] = value !== undefined ? value : !isBookCompleted(book);
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
        if (!(key in map)) {
            let value;
            const legacy = getLegacyKeys(book);
            for (let i = 0; i < legacy.length; i += 1) {
                if (legacy[i] in map) {
                    value = map[legacy[i]];
                    break;
                }
            }
            map[key] = value !== undefined ? value : "owned";
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
    const key = getBookKey(book);
    if (!key) return false;
    return map[key] === "library";
}

function isBookActive(map, book) {
    const key = getBookKey(book);
    if (!key) return !isBookCompleted(book);
    return map[key] !== false;
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
    const items = books
        .filter((book) => isBookLibrary(ownershipMap, book))
        .map((book) => {
            const total = Number(book.pagesTotal ?? book.pagesAll);
            const read = Number(book.pagesRead);
            const daysLeft = getDueDaysValue(book);
            if (!Number.isFinite(total) || !Number.isFinite(read)) return null;
            if (!Number.isFinite(daysLeft) || daysLeft <= 0) return null;
            const remaining = Math.max(0, total - read);
            if (remaining <= 0) return null;
            return { daysLeft, remaining };
        })
        .filter(Boolean)
        .sort((a, b) => a.daysLeft - b.daysLeft);

    if (!items.length) return 0;

    let maxRate = 0;
    let cumulative = 0;
    let i = 0;
    while (i < items.length) {
        const d = items[i].daysLeft;
        while (i < items.length && items[i].daysLeft === d) {
            cumulative += items[i].remaining;
            i += 1;
        }
        maxRate = Math.max(maxRate, cumulative / d);
    }

    return Math.ceil(maxRate);
}

function computeTodayStats(books, todayReadOverride) {
    const todayTarget = computeTodayTarget(books);
    const todayRead = Number.isFinite(todayReadOverride)
        ? todayReadOverride
        : (Number(dailyStats.todayRead) || 0);
    const pagesLeftToday = Math.max(0, todayTarget - todayRead);

    return { todayTarget, todayRead, pagesLeftToday };
}

// 1. pobierz stan
async function fetchState() {
    const url = API_URL + "?action=state";
    const res = await fetch(url, { cache: "no-store" });
    const data = await res.json();

    dailyStats = data.dailyStats || {};
    allBooks = data.activeBooks || [];
    activeMap = syncActiveMap(allBooks);
    ownershipMap = syncOwnershipMap(allBooks);

    const currentBook = allBooks[data.currentIndex] || null;
    const currentKey = currentBook ? getBookKey(currentBook) : null;

    const activeBooks = allBooks.filter((book) => isBookActive(activeMap, book));
    readingBooks = sortByDueDays(activeBooks);

    currentIndex = currentKey
        ? readingBooks.findIndex((book) => getBookKey(book) === currentKey)
        : 0;

    if (currentIndex < 0) currentIndex = 0;
}

// 2. zapisz nowe strony (GET, token, bez POST)
async function handleSavePages() {
    const newPage = Number(elPageInput.value);
    if (Number.isNaN(newPage)) return;

    const book = readingBooks[currentIndex];
    if (!book) return;

    const url = API_URL
      + "?action=updatePage"
      + "&book_id=" + encodeURIComponent(book.book_id)
      + "&page_current=" + encodeURIComponent(String(newPage))
      + "&token=" + encodeURIComponent(READING_TOKEN);

    const res = await fetch(url, { method: "GET", cache: "no-store" });
    const out = await res.json();

    if (out.error) {
        console.warn("Sheet error:", out.error);
        return;
    }

    const prevPages = Number(book.pagesRead) || 0;

    // aktualizuj UI lokalnie bez refetch całości
    book.pagesRead = out.page_current;
    book.percent   = out.percent;

    const delta = Math.max(0, Number(out.page_current) - prevPages);
    updateReadingLog(delta);

    renderCurrent();
    renderActiveGrid();
}

// wybór książki
function handleSelectBook(idx) {
    currentIndex = idx;
    renderCurrent();
}

// render sekcji wybranej książki
function renderCurrent() {
    const localStats = getLocalReadingStats();
    const stats = computeTodayStats(readingBooks, localStats.todayRead);

    elTodayTarget.textContent = `${stats.todayTarget} str.`;
    elTodayLeft.textContent   = `${stats.todayRead} przeczytane · ${stats.pagesLeftToday} zostaje`;

    elAvg.textContent    = `${localStats.avgPerDay7d} str./dzień`;
    elStreak.textContent = `Seria: ${localStats.streakDays} dni`;

    const book = readingBooks[currentIndex];
    if (!book) {
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
                elDuePill.textContent = dueDays === 0 ? "Dziś" : "Po term.";
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

    const pct = book.percent || 0;
    const pagesRead = Number(book.pagesRead) || 0;
    const pagesTotal = Number(book.pagesTotal) || 0;
    elProgressBar.style.width = pct + "%";
    elProgressText.textContent = `${pagesRead} / ${pagesTotal} • ${pct}%`;

    elPageInput.value = pagesRead;

    if (!showDue) {
        elDueInKpi.textContent = "—";
        elDueInKpi.classList.remove("danger");
        elDueDateKpi.textContent = "—";
    } else if (!hasDue) {
        elDueInKpi.textContent = "—";
        elDueInKpi.classList.remove("danger");
        elDueDateKpi.textContent = "Brak terminu";
    } else {
        if (Number.isFinite(dueDays)) {
            elDueInKpi.textContent = `${dueDays} dni`;
        } else {
            elDueInKpi.textContent = "—";
        }
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
                    dueBadgeText = dueDays === 0 ? "Dziś" : "Po term.";
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
                <div class="mini-progress-bar" style="width:${book.percent}%"></div>
            </div>
            <div class="mini-progress-meta">${book.percent}%</div>
        `;

        btn.addEventListener("click", () => handleSelectBook(idx));
        elActiveGrid.appendChild(btn);
    });
}

// init
async function init() {
    await fetchState();
    ensureReadingLogStart();
    if (elSaveBtn) {
        elSaveBtn.addEventListener("click", handleSavePages);
    }
    window.addEventListener("storage", (evt) => {
        if (!evt || !evt.key) return;
        if (evt.key === ACTIVE_STORAGE_KEY || evt.key === OWNERSHIP_STORAGE_KEY) {
            activeMap = syncActiveMap(allBooks);
            ownershipMap = syncOwnershipMap(allBooks);
            readingBooks = sortByDueDays(allBooks.filter((book) => isBookActive(activeMap, book)));
            if (currentIndex >= readingBooks.length) currentIndex = 0;
            renderCurrent();
            renderActiveGrid();
        }
    });
    window.addEventListener("pageshow", () => {
        activeMap = syncActiveMap(allBooks);
        ownershipMap = syncOwnershipMap(allBooks);
        readingBooks = sortByDueDays(allBooks.filter((book) => isBookActive(activeMap, book)));
        if (currentIndex >= readingBooks.length) currentIndex = 0;
        renderCurrent();
        renderActiveGrid();
    });
    renderCurrent();
    renderActiveGrid();
}

init();
