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

    if (book.dueInDays == null) {
        elDuePill.textContent = "No due date";
        elDuePill.classList.remove("danger");
    } else {
        elDuePill.textContent = `Due in ${book.dueInDays}d`;
        if (book.dueInDays <= 2) {
            elDuePill.classList.add("danger");
        } else {
            elDuePill.classList.remove("danger");
        }
    }
    elDueDateTop.textContent = book.dueDate || "—";

    const pct = book.percent || 0;
    elProgressBar.style.width = pct + "%";
    elProgressText.textContent = `${book.pagesRead} / ${book.pagesTotal} • ${pct}%`;

    elPageInput.value = book.pagesRead;

    elTodayTarget.textContent = `${dailyStats.todayTarget} str`;
    elTodayLeft.textContent   = `${dailyStats.todayRead} przeczytane · ${dailyStats.pagesLeftToday} zostaje`;

    if (book.dueInDays == null) {
        elDueInKpi.textContent = "—";
        elDueInKpi.classList.remove("danger");
        elDueDateKpi.textContent = "Brak";
    } else {
        elDueInKpi.textContent = `${book.dueInDays} dni`;
        if (book.dueInDays <= 2) {
            elDueInKpi.classList.add("danger");
        } else {
            elDueInKpi.classList.remove("danger");
        }
        elDueDateKpi.textContent = book.dueDate || "—";
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
        if (book.dueInDays == null) {
            dueBadgeText = "No due date";
            dueBadgeClass = "nodate";
        } else {
            dueBadgeText = `Due in ${book.dueInDays}d`;
            dueBadgeClass = (book.dueInDays <= 2) ? "critical" : "";
        }

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
                <span class="due-badge ${dueBadgeClass}">${dueBadgeText}</span>
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
