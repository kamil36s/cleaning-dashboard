// Ustaw to na URL twojego Apps Script Web App (ten /exec)
const API_URL = "https://script.google.com/macros/s/AKfycbyHo8WLZ0NR22ePdnlM4PTs6LriziEVniDMF3TXJxw3w9TgYilFCSzisOpxt5iDutDI/exec";

// Ten sam token co w Apps Script READING_TOKEN
const READING_TOKEN = "WSTAW_TUTAJ_SWÓJ_SEKRETNY_TOKEN";

let readingBooks = [];
let dailyStats = {};
let currentIndex = 0;

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

// 1. pobierz stan
async function fetchState() {
    const url = API_URL + "?action=state";
    const res = await fetch(url, { cache: "no-store" });
    const data = await res.json();

    dailyStats    = data.dailyStats;
    readingBooks  = data.activeBooks;
    currentIndex  = data.currentIndex || 0;
}

// 2. zapisz nowe strony (GET, token, bez POST)
async function handleSavePages() {
    const newPage = Number(elPageInput.value);
    if (Number.isNaN(newPage)) return;

    const book = readingBooks[currentIndex];

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

    // aktualizuj UI lokalnie bez refetch całości
    book.pagesRead = out.page_current;
    book.percent   = out.percent;

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
    const book = readingBooks[currentIndex];
    if (!book) return;

    elTitle.textContent  = book.title;
    elAuthor.textContent = book.author || "—";

    const hasDue = !!book.dueDate;
    const dueDays = Number(book.dueInDays);
    if (!hasDue) {
        elDuePill.textContent = "No due date";
        elDuePill.classList.remove("danger");
        elDuePill.style.borderColor = "";
    } else if (!Number.isFinite(dueDays)) {
        elDuePill.textContent = "Due date";
        elDuePill.classList.remove("danger");
        elDuePill.style.borderColor = "";
    } else {
        elDuePill.textContent = `Due in ${dueDays}d`;
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

    const pct = book.percent || 0;
    elProgressBar.style.width = pct + "%";
    elProgressText.textContent = `${book.pagesRead} / ${book.pagesTotal} • ${pct}%`;

    elPageInput.value = book.pagesRead;

    elTodayTarget.textContent = `${dailyStats.todayTarget} str`;
    elTodayLeft.textContent   = `${dailyStats.todayRead} przeczytane · ${dailyStats.pagesLeftToday} zostaje`;

    if (!hasDue) {
        elDueInKpi.textContent = "—";
        elDueInKpi.classList.remove("danger");
        elDueDateKpi.textContent = "Brak";
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

    elAvg.textContent    = `${dailyStats.avgPerDay7d}/dzień`;
    elStreak.textContent = `Streak ${dailyStats.streakDays} dni`;
}

// render listy aktywnych
function renderActiveGrid() {
    elActiveGrid.innerHTML = "";
    elActiveCount.textContent = `(${readingBooks.length})`;

    readingBooks.forEach((book, idx) => {
        let dueBadgeText, dueBadgeClass;
        const hasDue = !!book.dueDate;
        const dueDays = Number(book.dueInDays);
        if (!hasDue) {
            dueBadgeText = "No due date";
            dueBadgeClass = "nodate";
        } else if (!Number.isFinite(dueDays)) {
            dueBadgeText = "Due date";
            dueBadgeClass = "";
        } else {
            dueBadgeText = `Due in ${dueDays}d`;
            dueBadgeClass = (dueDays <= 0) ? "critical" : "";
        }
        const dueColorVal = (hasDue && Number.isFinite(dueDays) && dueDays > 0)
            ? dueColor(dueDays)
            : null;
        const dueBadgeStyle = dueColorVal ? ` style="border-color:${dueColorVal};"` : "";

        const btn = document.createElement("button");
        btn.className = "reading-bookbtn";
        btn.setAttribute("type", "button");
        btn.innerHTML = `
            <div class="rb-head">
                <div class="rb-title">${book.title}</div>
                <div class="rb-author">${book.author || ""}</div>
            </div>
            <div class="rb-stats">
                <span class="rb-pages">${book.pagesRead}/${book.pagesTotal}</span>
                <span class="rb-percent">${book.percent}%</span>
                <span class="due-badge ${dueBadgeClass}"${dueBadgeStyle}>${dueBadgeText}</span>
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
    if (elSaveBtn) {
        elSaveBtn.addEventListener("click", handleSavePages);
    }
    renderCurrent();
    renderActiveGrid();
}

init();
