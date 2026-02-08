// reading.js
import { fmtDateShort } from './utils.js';

// Stały endpoint Apps Script
const API_BASE = 'https://script.google.com/macros/s/AKfycbxHsr6z0XaqmWoJf6B2MuVtcnHVa9OFzha9mVAEH4p7yAoTPqi2hSp2SrwxZpO_Hq35/exec';
const API = `${API_BASE}?type=reading`;

const ACTIVE_STORAGE_KEY = 'readingActiveMap.v1';
const OWNERSHIP_STORAGE_KEY = 'readingOwnershipMap.v1';

let BOOKS = [];
let STATS = {};
let ACTIVE_MAP = {};
let OWNERSHIP_MAP = {};

// Format daty "2025-10-26T00:00:00Z" -> "26.10.2025"
function fmtDate(d) {
    return fmtDateShort(d);
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

// Określ kolor progress bara dla książki
function colorForBook(b) {
    const pagesLeft = Math.max(0, b.pagesAll - b.pagesRead);
    const daysLeft = b.daysToReturn; // może być null
    const avg = Number(STATS.avgPagesPerDay) || 0;

    // krytyczne: termin dziś lub po terminie i jeszcze nie skończone
    if (b.returnDate && daysLeft === 0 && pagesLeft > 0) return 'red';

    // jeżeli brak terminu zwrotu albo nie mamy średniej prędkości czytania
    if (!b.returnDate || avg <= 0) return 'green';

    // ile musisz czytać dziennie żeby zdążyć
    const req = pagesLeft / Math.max(1, daysLeft);

    if (req > 1.2 * avg) return 'red';
    if (req > 0.8 * avg) return 'yellow';
    return 'green';
}

function getBookTotalPages(book) {
    const total = Number(book.pagesTotal ?? book.pagesAll);
    return Number.isFinite(total) ? total : '';
}

function getLegacyKeys(book) {
    const keys = [];
    if (book.book_id != null) keys.push(String(book.book_id));
    if (book.bookId != null) keys.push(String(book.bookId));
    if (book.id != null) keys.push(String(book.id));
    return keys;
}

function getBookKey(book) {
    const title = (book.title || '').trim().toLowerCase();
    const author = (book.author || '').trim().toLowerCase();
    const total = getBookTotalPages(book);
    const composite = [title, author, total].filter((v) => v !== '').join('|');
    return composite || '';
}

function isBookCompleted(book) {
    const pct = book.completedPct ?? (book.pagesRead / Math.max(1, book.pagesAll));
    return pct >= 1;
}

function loadActiveMap() {
    try {
        const raw = localStorage.getItem(ACTIVE_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : null;
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

function hasBookDueDate(book) {
    return !!book.returnDate;
}

function loadOwnershipMap() {
    try {
        const raw = localStorage.getItem(OWNERSHIP_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : null;
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
            map[key] = value !== undefined ? value : 'owned';
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
    return map[key] === 'library';
}

function isBookActive(map, book) {
    const key = getBookKey(book);
    if (!key) return !isBookCompleted(book);
    return map[key] !== false;
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

// Oblicz KPI: ile stron dziennie i najbliższy deadline
function computePPD(list) {
    const items = list
        .filter((b) => isBookActive(ACTIVE_MAP, b) && isBookLibrary(OWNERSHIP_MAP, b))
        .map((b) => {
            const total = Number(b.pagesAll ?? b.pagesTotal);
            const read = Number(b.pagesRead);
            const daysLeft = Number(b.daysToReturn);
            if (!Number.isFinite(total) || !Number.isFinite(read)) return null;
            if (!Number.isFinite(daysLeft) || daysLeft <= 0) return null;
            const remaining = Math.max(0, total - read);
            if (remaining <= 0) return null;
            return { daysLeft, remaining, returnDate: b.returnDate };
        })
        .filter(Boolean)
        .sort((a, b) => a.daysLeft - b.daysLeft);

    if (!items.length) {
        return { ppd: 0, nextDate: null, nextDays: null };
    }

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

    const next = items[0];
    return { ppd: Math.ceil(maxRate), nextDate: next.returnDate, nextDays: next.daysLeft };
}

// Render całego panelu i listy książek
function renderAll() {
    const unfinishedOnly = document.getElementById('unfinished').checked;
    const sortVal = document.getElementById('sort').value;

    // filtr: tylko nieukończone jeśli checkbox zaznaczony
    let list = BOOKS.slice();
    if (unfinishedOnly) {
        list = list.filter(b => !isBookCompleted(b));
    }

    // KPI z lewej
    const { ppd, nextDate, nextDays } = computePPD(list);

    document.getElementById('ppd').textContent = ppd;
    document.getElementById('next').textContent = nextDate
        ? `${fmtDate(nextDate)} (${nextDays} dni)`
        : '—';

    const activeCount = BOOKS.filter(b => isBookActive(ACTIVE_MAP, b)).length;
    document.getElementById('active').textContent = activeCount;
    document.getElementById('avg').textContent = STATS.avgPagesPerDay ?? 0;

    const compareSelected = (a, b) => compareBySortVal(a, b, sortVal);

    // sortowanie listy książek
    if (unfinishedOnly) {
        list.sort(compareSelected);
    } else {
        list.sort((a, b) => {
            const aDone = isBookCompleted(a);
            const bDone = isBookCompleted(b);
            if (aDone !== bDone) return aDone ? 1 : -1;
            if (aDone && bDone) return compareByDue(a, b);
            return compareSelected(a, b);
        });
    }

    // render kart do #grid
    const grid = document.getElementById('grid');
    grid.innerHTML = list.map(b => {
        const pctNum = Math.round(
            (b.pagesRead / Math.max(1, b.pagesAll)) * 100
        );

        const color = colorForBook(b);
        const pagesLeft = Math.max(0, b.pagesAll - b.pagesRead);

        const key = getBookKey(b);
        const keyAttr = encodeURIComponent(key || '');
        const canToggle = !!key;
        const isActive = isBookActive(ACTIVE_MAP, b);
        const isLibrary = isBookLibrary(OWNERSHIP_MAP, b);
        const ownershipLabel = isLibrary ? 'Biblioteka' : 'Moja';
        const ownershipIcon = isLibrary
            ? '<svg class="pill-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 9l9-5 9 5v2H3V9zm2 4h2v7H5v-7zm4 0h2v7H9v-7zm4 0h2v7h-2v-7zm4 0h2v7h-2v-7z"/></svg>'
            : '<svg class="pill-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l9 7h-3v9h-5v-5H11v5H6v-9H3z"/></svg>';
        const showDue = b.returnDate || isLibrary;

        // tekst badga (termin zwrotu)
        const badgeText = showDue
            ? (
                b.returnDate
                    ? (
                        b.daysToReturn > 0
                            ? `${b.daysToReturn} dni`
                            : (pagesLeft > 0 ? 'Po term.' : 'Dziś')
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
            <div class="card">
                <div class="header">
                    <div>
                        <div class="title">${b.title || ''}</div>
                        <div class="meta">${b.author || ''}</div>
                    </div>

                    <div class="header-actions">
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
                        <button
                            class="ownership-toggle ${isLibrary ? 'is-library' : 'is-owned'}"
                            type="button"
                            data-ownership-key="${keyAttr}"
                            aria-pressed="${isLibrary ? 'true' : 'false'}"
                            title="${ownershipLabel}"
                            aria-label="${ownershipLabel}"
                        >
                            ${ownershipIcon}
                        </button>
                        ` : ''}
                    </div>
                </div>

                <div class="progress">
                    <div class="${color}" style="width:${pctNum}%"></div>
                </div>

                <div class="footer">
                    <span>${b.pagesRead} / ${b.pagesAll} • ${pctNum}%</span>
                    <span></span>
                </div>
            </div>
        `;
    }).join('');

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

    grid.querySelectorAll('.ownership-toggle[data-ownership-key]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const key = decodeURIComponent(btn.dataset.ownershipKey || '');
            if (!key) return;

            const isLibrary = OWNERSHIP_MAP[key] === 'library';
            OWNERSHIP_MAP[key] = isLibrary ? 'owned' : 'library';
            saveOwnershipMap(OWNERSHIP_MAP);
            renderAll();
        });
    });
}

// Pobranie JSON z Apps Script
async function fetchData() {
    const r = await fetch(API, { cache: 'no-store' });
    const j = await r.json();

    BOOKS = j.books || [];
    STATS = j.stats || {};
    ACTIVE_MAP = syncActiveMap(BOOKS);
    OWNERSHIP_MAP = syncOwnershipMap(BOOKS);

    renderAll();
}

// Inicjalizacja handlerów
function initReadingDashboard() {
    const refreshBtn   = document.getElementById('refresh');
    const unfinishedCb = document.getElementById('unfinished');
    const sortSel      = document.getElementById('sort');
    const backBtn      = document.getElementById('back-btn');

    if (refreshBtn) {
        refreshBtn.addEventListener('click', fetchData);
    }
    if (unfinishedCb) {
        unfinishedCb.addEventListener('change', renderAll);
    }
    if (sortSel) {
        sortSel.addEventListener('change', renderAll);
    }
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            // przekierowanie na stronę główną
            window.location.href = 'index.html';
        });
    }

    fetchData();
}

// boot po załadowaniu DOM
document.addEventListener('DOMContentLoaded', initReadingDashboard);
