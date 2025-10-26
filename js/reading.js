// reading.js

// Stały endpoint Apps Script
const API_BASE = 'https://script.google.com/macros/s/AKfycbxHsr6z0XaqmWoJf6B2MuVtcnHVa9OFzha9mVAEH4p7yAoTPqi2hSp2SrwxZpO_Hq35/exec';
const API = `${API_BASE}?type=reading`;

let BOOKS = [];
let STATS = {};

// Format daty "2025-10-26T00:00:00Z" -> "26.10.2025"
function fmtDate(d) {
    return d ? new Date(d).toLocaleDateString('pl-PL') : '—';
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

// Oblicz KPI: ile stron dziennie i najbliższy deadline
function computePPD(list) {
    // bierzemy tylko książki z datą zwrotu i nieukończone
    const dated = list.filter(b => {
        const pct = b.completedPct ?? (b.pagesRead / b.pagesAll);
        return b.returnDate && pct < 1;
    });

    if (!dated.length) {
        return { ppd: 0, nextDate: null, nextDays: null };
    }

    // najmniej dni do zwrotu
    const earliest = Math.min(...dated.map(b => b.daysToReturn ?? 9999));

    // ile stron zostało łącznie
    const totalLeft = dated.reduce((sum, b) => {
        return sum + Math.max(0, b.pagesAll - b.pagesRead);
    }, 0);

    // zaokrąglamy w górę ile dziennie żeby wszystko oddać na czas
    const ppd = Math.ceil(totalLeft / Math.max(1, earliest));

    // znajdź książkę z najbliższym terminem
    const next = dated
        .slice()
        .sort((a, b) => (a.daysToReturn ?? 9999) - (b.daysToReturn ?? 9999))[0];

    return { ppd, nextDate: next.returnDate, nextDays: earliest };
}

// Render całego panelu i listy książek
function renderAll() {
    const unfinishedOnly = document.getElementById('unfinished').checked;
    const sortVal = document.getElementById('sort').value;

    // filtr: tylko nieukończone jeśli checkbox zaznaczony
    let list = BOOKS.slice();
    if (unfinishedOnly) {
        list = list.filter(b => {
            const pct = b.completedPct ?? (b.pagesRead / b.pagesAll);
            return pct < 1;
        });
    }

    // KPI z lewej
    const { ppd, nextDate, nextDays } = computePPD(list);

    document.getElementById('ppd').textContent = ppd;
    document.getElementById('next').textContent = nextDate
        ? `${fmtDate(nextDate)} (${nextDays}d)`
        : '—';

    document.getElementById('active').textContent = list.length;
    document.getElementById('avg').textContent = STATS.avgPagesPerDay ?? 0;

    // sortowanie listy książek
    list.sort((a, b) => {
        if (sortVal === 'title') {
            return (a.title || '').localeCompare(b.title || '');
        }
        if (sortVal === 'remain') {
            // sortuj po ile stron zostało malejąco
            return (b.pagesAll - b.pagesRead) - (a.pagesAll - a.pagesRead);
        }
        if (sortVal === 'completion') {
            // od najmniej ukończonych do najbardziej
            const pa = (a.pagesRead / Math.max(1, a.pagesAll));
            const pb = (b.pagesRead / Math.max(1, b.pagesAll));
            return pa - pb;
        }

        // default: due soon
        const da = a.daysToReturn ?? 9999;
        const db = b.daysToReturn ?? 9999;
        return da - db;
    });

    // render kart do #grid
    const grid = document.getElementById('grid');
    grid.innerHTML = list.map(b => {
        const pctNum = Math.round(
            (b.pagesRead / Math.max(1, b.pagesAll)) * 100
        );

        const color = colorForBook(b);
        const pagesLeft = Math.max(0, b.pagesAll - b.pagesRead);

        // tekst badga (termin zwrotu)
        const badgeText = b.returnDate
            ? (
                b.daysToReturn > 0
                    ? `Due in ${b.daysToReturn}d`
                    : (pagesLeft > 0 ? 'OVERDUE' : 'Due today')
            )
            : 'No due date';

        // klasa badga (kolor czerwony jeśli spóźnione)
        let badgeClass = 'due-badge';
        if (!b.returnDate) {
            badgeClass += ' nodate';
        } else if (b.daysToReturn <= 0 && pagesLeft > 0) {
            badgeClass += ' critical';
        }

        return `
            <div class="card">
                <div class="header">
                    <div>
                        <div class="title">${b.title || ''}</div>
                        <div class="meta">${b.author || ''}</div>
                    </div>

                    <span class="${badgeClass}">${badgeText}</span>
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
}

// Pobranie JSON z Apps Script
async function fetchData() {
    const r = await fetch(API, { cache: 'no-store' });
    const j = await r.json();

    BOOKS = j.books || [];
    STATS = j.stats || {};

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
