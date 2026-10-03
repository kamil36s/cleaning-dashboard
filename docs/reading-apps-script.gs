/***** CONFIG *****/
const VERSION = 'reading_v5_add_book';
const SHEET_ID = '1Z7epQxDpfRDlxNlI_HbClG5tS3e9xNukCkNAaYVTy8Y';

/***** HEADER NAMES (PL/EN) *****/
const HN = {
  bookId: ['Book ID', 'book_id', 'Book Id', 'ID ksiazki', 'ID książki'],
  author: ['Author', 'Autor'],
  title: ['Title', 'Tytul', 'Tytuł'],
  completed: ['Completed', 'Completed %', 'Ukonczono', 'Ukończono'],
  pagesRead: ['Pages read', 'Przeczytane', 'Pages Read'],
  pagesAll: ['All pages', 'Wszystkie strony', 'Pages Total'],
  returnDate: ['Return date', 'Data zwrotu'],
  lastUpdate: ['Last update', 'Last Update', 'Ostatnia aktualizacja'],
};

/***** ENTRYPOINT *****/
function doGet(e) {
  const p = (e && e.parameter) || {};

  if (p.diag === 'version') return out({ version: VERSION });
  if (p.diag === 'sheets') return out(diagSheets());

  try {
    if (p.action === 'state') return out(readingState());

    if (p.action) {
      if (!p.token) return out({ error: 'forbidden' });
      return out(handleWrite(p));
    }

    const type = p.type || 'reading';
    if (type === 'reading') return out(readingFeed());
    return out({ error: 'unknown type' });
  } catch (err) {
    return out({ error: String(err && err.message ? err.message : err) });
  }
}

/***** READ API *****/
function readingFeed() {
  const rows = readBookRows({ ensureBookIds: false });
  const books = rows.books
    .filter(function (b) { return b.pagesAll > 0; })
    .filter(function (b) { return b.percent < 100; });

  const dated = books.filter(function (b) { return b.returnDate; });
  const earliest = dated.length ? Math.min.apply(null, dated.map(function (b) { return b.daysToReturn; })) : null;
  const pagesForEarliest = dated
    .filter(function (b) { return b.daysToReturn === earliest; })
    .reduce(function (sum, b) { return sum + b.pagesLeft; }, 0);
  const ppdToNext = earliest != null ? Math.ceil(pagesForEarliest / Math.max(1, earliest)) : 0;

  const stats = {
    updated: formatDate(new Date()),
    booksActive: books.length,
    avgPagesPerDay: 0,
    nextReturnDate: dated.length ? dated.sort(function (a, b) { return a.daysToReturn - b.daysToReturn; })[0].returnDate : null,
    nextReturnInDays: earliest,
    pagesPerDayUntilNextReturn: ppdToNext,
    pagesLeftAll: books.reduce(function (sum, b) { return sum + b.pagesLeft; }, 0),
  };

  return { updated: stats.updated, books: books, stats: stats };
}

function readingState() {
  const rows = readBookRows({ ensureBookIds: true });
  const activeBooks = rows.books
    .filter(function (b) { return b.pagesTotal > 0; })
    .filter(function (b) { return b.percent < 100; });

  return {
    version: VERSION,
    dailyStats: {
      todayRead: 0,
      avgPerDay7d: 0,
      streakDays: 0,
      todayTarget: 0,
      pagesLeftToday: 0,
      avgPagesPerDay: 0,
    },
    activeBooks: activeBooks,
    currentIndex: 0,
  };
}

/***** WRITE API *****/
function handleWrite(p) {
  if (p.action === 'addBook') return addBook(p);
  if (p.action === 'updatePage') return updatePage(p);
  if (p.action === 'addPages') return addPages(p);
  if (p.action === 'finish') return finishBook(p);
  return { error: 'unknown action' };
}

function addBook(p) {
  const title = cleanText(p.title);
  const author = cleanText(p.author);
  const pagesTotal = Math.max(1, Math.round(Number(p.page_total || p.pagesTotal || p.pages_all || 0)));
  const pagesRead = Math.max(0, Math.min(pagesTotal, Math.round(Number(p.page_current || p.pagesRead || p.pages_read || 0))));

  if (!title) return { error: 'missing title' };
  if (!author) return { error: 'missing author' };
  if (!pagesTotal) return { error: 'missing page_total' };

  const ctx = getContext({ ensureBookId: true, ensureLastUpdate: true });
  requireColumns(ctx, [ctx.c.author, ctx.c.title, ctx.c.pagesRead, ctx.c.pagesAll]);

  const used = collectUsedBookIds(ctx);
  const bookId = makeUniqueBookId(title, author, used);
  const percent = pagesTotal > 0 ? Math.round((pagesRead / pagesTotal) * 100) : 0;
  const nextRow = findFirstEmptyBookRow(ctx);
  const values = new Array(ctx.sh.getLastColumn()).fill('');

  values[ctx.c.bookId] = bookId;
  values[ctx.c.author] = author;
  values[ctx.c.title] = title;
  values[ctx.c.pagesRead] = pagesRead;
  values[ctx.c.pagesAll] = pagesTotal;
  if (ctx.c.completed >= 0) values[ctx.c.completed] = percent + '%';
  if (ctx.c.lastUpdate >= 0) values[ctx.c.lastUpdate] = new Date();

  ctx.sh.getRange(nextRow, 1, 1, values.length).setValues([values]);

  return {
    ok: true,
    row: nextRow,
    book_id: bookId,
    page_current: pagesRead,
    page_total: pagesTotal,
    percent: percent,
    book: {
      book_id: bookId,
      title: title,
      author: author,
      pagesRead: pagesRead,
      pagesTotal: pagesTotal,
      pagesAll: pagesTotal,
      percent: percent,
      completedPct: percent / 100,
      dueDate: null,
      returnDate: null,
      dueInDays: null,
      daysToReturn: null,
      last_update: new Date().toISOString(),
    },
  };
}

function updatePage(p) {
  const bookId = cleanText(p.book_id || p.bookId || p.id);
  const nextPageRaw = Number(p.page_current || p.pagesRead || p.pages_read);
  if (!bookId) return { error: 'missing book_id' };
  if (!isFinite(nextPageRaw)) return { error: 'bad page_current' };

  const ctx = getContext({ ensureBookId: true, ensureLastUpdate: true });
  requireColumns(ctx, [ctx.c.bookId, ctx.c.pagesRead, ctx.c.pagesAll]);
  ensureExistingBookIds(ctx);

  const data = readSheetValues(ctx.sh);
  const rowIndex = findDataRowByBookId(data, ctx, bookId);
  if (rowIndex < 0) return { error: 'book_id not found' };

  const rowNumber = rowIndex + 1;
  const all = numSafe(data[rowIndex][ctx.c.pagesAll]);
  const safePage = Math.max(0, all > 0 ? Math.min(all, Math.round(nextPageRaw)) : Math.round(nextPageRaw));
  const percent = all > 0 ? Math.round((safePage / all) * 100) : 0;

  ctx.sh.getRange(rowNumber, ctx.c.pagesRead + 1).setValue(safePage);
  if (ctx.c.completed >= 0) ctx.sh.getRange(rowNumber, ctx.c.completed + 1).setValue(percent + '%');
  if (ctx.c.lastUpdate >= 0) ctx.sh.getRange(rowNumber, ctx.c.lastUpdate + 1).setValue(new Date());

  return { ok: true, book_id: bookId, row: rowNumber, page_current: safePage, percent: percent };
}

function addPages(p) {
  const ctx = getContext({ ensureBookId: false, ensureLastUpdate: true });
  requireColumns(ctx, [ctx.c.pagesRead, ctx.c.pagesAll]);
  const row = Number(p.row);
  if (!row) return { error: 'bad row' };

  const add = Number(p.count) || 0;
  const read = numSafe(ctx.sh.getRange(row, ctx.c.pagesRead + 1).getValue());
  const all = numSafe(ctx.sh.getRange(row, ctx.c.pagesAll + 1).getValue());
  const newRead = Math.min(all, Math.max(0, read + add));
  const percent = all > 0 ? Math.round((newRead / all) * 100) : 0;

  ctx.sh.getRange(row, ctx.c.pagesRead + 1).setValue(newRead);
  if (ctx.c.completed >= 0) ctx.sh.getRange(row, ctx.c.completed + 1).setValue(percent + '%');
  if (ctx.c.lastUpdate >= 0) ctx.sh.getRange(row, ctx.c.lastUpdate + 1).setValue(new Date());
  return { ok: true, row: row, newRead: newRead };
}

function finishBook(p) {
  const ctx = getContext({ ensureBookId: false, ensureLastUpdate: true });
  requireColumns(ctx, [ctx.c.pagesRead, ctx.c.pagesAll]);
  const row = Number(p.row);
  if (!row) return { error: 'bad row' };

  const all = numSafe(ctx.sh.getRange(row, ctx.c.pagesAll + 1).getValue());
  ctx.sh.getRange(row, ctx.c.pagesRead + 1).setValue(all);
  if (ctx.c.completed >= 0) ctx.sh.getRange(row, ctx.c.completed + 1).setValue('100%');
  if (ctx.c.lastUpdate >= 0) ctx.sh.getRange(row, ctx.c.lastUpdate + 1).setValue(new Date());
  return { ok: true, row: row };
}

/***** SHEET HELPERS *****/
function readBookRows(options) {
  const ctx = getContext({ ensureBookId: !!options.ensureBookIds });
  requireColumns(ctx, [ctx.c.author, ctx.c.title, ctx.c.pagesRead, ctx.c.pagesAll]);
  if (options.ensureBookIds) ensureExistingBookIds(ctx);

  const data = readSheetValues(ctx.sh);
  const today = new Date();
  const books = [];

  for (let i = ctx.headerRow + 1; i < data.length; i += 1) {
    const r = data[i];
    const title = String(r[ctx.c.title] || '').trim();
    const author = String(r[ctx.c.author] || '').trim();
    const pagesRead = numSafe(r[ctx.c.pagesRead]);
    const pagesAll = numSafe(r[ctx.c.pagesAll]);
    if (!title && !author && pagesAll <= 0) continue;

    const percent = ctx.c.completed >= 0
      ? pctNum(r[ctx.c.completed])
      : (pagesAll > 0 ? Math.round((pagesRead / pagesAll) * 100) : 0);
    const returnDate = ctx.c.returnDate >= 0 ? toYMD(r[ctx.c.returnDate]) : null;
    const daysToReturn = returnDate ? diffDays(new Date(returnDate), today) : null;
    const bookId = ctx.c.bookId >= 0 ? cleanText(r[ctx.c.bookId]) : '';

    books.push({
      row: i + 1,
      book_id: bookId,
      bookId: bookId,
      id: bookId,
      author: author,
      title: title,
      percent: percent,
      completedPct: percent / 100,
      pagesRead: pagesRead,
      pagesAll: pagesAll,
      pagesTotal: pagesAll,
      pagesLeft: Math.max(0, pagesAll - pagesRead),
      returnDate: returnDate,
      dueDate: returnDate,
      daysToReturn: daysToReturn,
      dueInDays: daysToReturn,
    });
  }

  return { books: books, ctx: ctx };
}

function getContext(options) {
  const found = getSheetWithHeaders(SHEET_ID);
  if (!found) throw new Error('Sheet with required headers not found');

  const sh = found.sh;
  if (options && options.ensureBookId) ensureColumn(sh, found.headerRow, HN.bookId[0]);
  if (options && options.ensureLastUpdate) ensureColumn(sh, found.headerRow, HN.lastUpdate[0]);

  const values = readSheetValues(sh);
  const headerRow = found.headerRow;
  const headers = values[headerRow].map(norm);

  return {
    sh: sh,
    headerRow: headerRow,
    c: {
      bookId: colByNames(headers, HN.bookId),
      author: colByNames(headers, HN.author),
      title: colByNames(headers, HN.title),
      completed: colByNames(headers, HN.completed),
      pagesRead: colByNames(headers, HN.pagesRead),
      pagesAll: colByNames(headers, HN.pagesAll),
      returnDate: colByNames(headers, HN.returnDate),
      lastUpdate: colByNames(headers, HN.lastUpdate),
    },
  };
}

function ensureColumn(sh, headerRow, name) {
  const lastColumn = sh.getLastColumn();
  const headers = sh.getRange(headerRow + 1, 1, 1, lastColumn).getValues()[0].map(norm);
  if (headers.indexOf(norm(name)) >= 0) return;
  sh.getRange(headerRow + 1, lastColumn + 1).setValue(name);
}

function ensureExistingBookIds(ctx) {
  if (ctx.c.bookId < 0) return;
  const data = readSheetValues(ctx.sh);
  const used = collectUsedBookIds(ctx);
  let changed = false;

  for (let i = ctx.headerRow + 1; i < data.length; i += 1) {
    const r = data[i];
    const current = cleanText(r[ctx.c.bookId]);
    if (current) continue;
    const title = ctx.c.title >= 0 ? cleanText(r[ctx.c.title]) : '';
    const author = ctx.c.author >= 0 ? cleanText(r[ctx.c.author]) : '';
    const pagesAll = ctx.c.pagesAll >= 0 ? numSafe(r[ctx.c.pagesAll]) : 0;
    if (!title && !author && pagesAll <= 0) continue;

    const nextId = makeUniqueBookId(title, author, used);
    ctx.sh.getRange(i + 1, ctx.c.bookId + 1).setValue(nextId);
    used[nextId] = true;
    changed = true;
  }

  if (changed) SpreadsheetApp.flush();
}

function collectUsedBookIds(ctx) {
  const data = readSheetValues(ctx.sh);
  const used = {};
  if (ctx.c.bookId < 0) return used;
  for (let i = ctx.headerRow + 1; i < data.length; i += 1) {
    const value = cleanText(data[i][ctx.c.bookId]);
    if (value) used[value] = true;
  }
  return used;
}

function findDataRowByBookId(data, ctx, bookId) {
  const wanted = cleanText(bookId);
  for (let i = ctx.headerRow + 1; i < data.length; i += 1) {
    if (cleanText(data[i][ctx.c.bookId]) === wanted) return i;
  }
  return -1;
}

function findFirstEmptyBookRow(ctx) {
  const data = readSheetValues(ctx.sh);
  for (let i = ctx.headerRow + 1; i < data.length; i += 1) {
    const row = data[i] || [];
    const title = ctx.c.title >= 0 ? cleanText(row[ctx.c.title]) : '';
    const author = ctx.c.author >= 0 ? cleanText(row[ctx.c.author]) : '';
    const pagesRead = ctx.c.pagesRead >= 0 ? cleanText(row[ctx.c.pagesRead]) : '';
    const pagesAll = ctx.c.pagesAll >= 0 ? cleanText(row[ctx.c.pagesAll]) : '';
    const bookId = ctx.c.bookId >= 0 ? cleanText(row[ctx.c.bookId]) : '';
    if (!title && !author && !pagesRead && !pagesAll && !bookId) return i + 1;
  }
  return Math.max(ctx.headerRow + 2, ctx.sh.getLastRow() + 1);
}

function readSheetValues(sh) {
  const lr = sh.getLastRow();
  const lc = sh.getLastColumn();
  if (!lr || !lc) return [[]];
  return sh.getRange(1, 1, lr, lc).getValues();
}

function getSheetWithHeaders(id) {
  const ss = SpreadsheetApp.openById(id);
  for (const sh of ss.getSheets()) {
    const lr = sh.getLastRow();
    const lc = sh.getLastColumn();
    if (!lr || !lc) continue;
    const rng = sh.getRange(1, 1, Math.min(lr, 10), Math.min(lc, 30)).getValues();
    for (let r = 0; r < rng.length; r += 1) {
      const row = rng[r].map(norm);
      const need = [HN.author, HN.title, HN.pagesRead, HN.pagesAll];
      const ok = need.every(function (list) {
        return list.map(norm).some(function (n) { return row.indexOf(n) >= 0; });
      });
      if (ok) return { sh: sh, headerRow: r, headerValues: rng[r] };
    }
  }
  return null;
}

function requireColumns(ctx, cols) {
  if (cols.some(function (i) { return i < 0; })) throw new Error('columns missing');
}

/***** GENERIC HELPERS *****/
function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function diagSheets() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const result = { fileName: ss.getName(), sheets: [] };
  ss.getSheets().forEach(function (sh) {
    const lr = sh.getLastRow();
    const lc = sh.getLastColumn();
    const firstRow = lr ? sh.getRange(1, 1, 1, Math.min(lc, 30)).getValues()[0] : [];
    result.sheets.push({ name: sh.getName(), lastRow: lr, lastColumn: lc, firstRow: firstRow });
  });
  return result;
}

function norm(x) {
  return String(x || '').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').trim();
}

function colByNames(headersNorm, names) {
  for (let i = 0; i < names.length; i += 1) {
    const idx = headersNorm.indexOf(norm(names[i]));
    if (idx !== -1) return idx;
  }
  return -1;
}

function cleanText(value) {
  return String(value || '').normalize('NFC').replace(/\s+/g, ' ').trim();
}

function pctNum(value) {
  const n = Number(String(value || '').replace('%', '').replace(',', '.'));
  return isFinite(n) ? n : 0;
}

function numSafe(value) {
  if (Object.prototype.toString.call(value) === '[object Date]') return 0;
  const n = Number(String(value || '').replace(',', '.'));
  return isFinite(n) ? n : 0;
}

function toYMD(value) {
  if (!value) return null;
  if (typeof value === 'number') {
    const ms = Math.round((value - 25569) * 86400 * 1000);
    return formatDate(new Date(ms));
  }
  if (Object.prototype.toString.call(value) === '[object Date]') return formatDate(value);
  const d = new Date(String(value));
  return isNaN(d) ? null : formatDate(d);
}

function diffDays(d2, d1) {
  return Math.max(0, Math.ceil((d2 - d1) / 86400000));
}

function formatDate(date) {
  const tz = SpreadsheetApp.openById(SHEET_ID).getSpreadsheetTimeZone() || Session.getScriptTimeZone();
  return Utilities.formatDate(date, tz, 'yyyy-MM-dd');
}

function makeUniqueBookId(title, author, used) {
  const base = slugify([title, author].filter(Boolean).join('-')) || ('book-' + Date.now());
  let candidate = base;
  let n = 2;
  while (used[candidate]) {
    candidate = base + '-' + n;
    n += 1;
  }
  used[candidate] = true;
  return candidate;
}

function slugify(value) {
  const replacements = {
    'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n', 'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
    'Ą': 'a', 'Ć': 'c', 'Ę': 'e', 'Ł': 'l', 'Ń': 'n', 'Ó': 'o', 'Ś': 's', 'Ź': 'z', 'Ż': 'z',
  };
  return String(value || '')
    .replace(/[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]/g, function (ch) { return replacements[ch] || ch; })
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
