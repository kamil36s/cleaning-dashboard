// Ten plik nie deklaruje globalnych const, zeby nie kolidowal z innymi plikami Apps Script.

function readingToken_() {
  return "SECRET_READING_TOKEN_666";
}

function readingSheetId_() {
  return "1Z7epQxDpfRDlxNlI_HbClG5tS3e9xNukCkNAaYVTy8Y";
}

function readingVersion_() {
  return "reading_update_v5_add_book_source_due";
}

// ================== ENTRYPOINTS ==================

function doGet(e) {
  var action = e.parameter.action;

  if (e.parameter.diag === 'version') {
    return jsonOut_({ version: readingVersion_() });
  }

  // Odczyt danych do widzetu
  if (action === 'state') {
    return getState_();
  }

  // Zapis nowych stron przez GET + token
  if (action === 'updatePage') {
    if (e.parameter.token !== readingToken_()) {
      return jsonOut_({ error: 'bad token' });
    }
    return updatePage_(e.parameter);
  }

  // Dodanie ksiazki z reading.html
  if (action === 'addBook') {
    if (e.parameter.token !== readingToken_()) {
      return jsonOut_({ error: 'bad token' });
    }
    return addBook_(e.parameter);
  }

  return jsonOut_({ error: 'unknown action' });
}

// doPost zostawiamy na przyszlosc (backend wlasny)
function doPost(e) {
  var data = {};
  if (e && e.parameter) {
    data = e.parameter;
  } else if (e && e.postData && e.postData.contents) {
    try {
      data = JSON.parse(e.postData.contents);
    } catch (err) {
      data = {};
    }
  }

  var action = data.action;

  if (action === 'updatePage') {
    if (data.token !== readingToken_()) {
      return jsonOut_({ error: 'bad token' });
    }
    return updatePage_(data);
  }

  if (action === 'addBook') {
    if (data.token !== readingToken_()) {
      return jsonOut_({ error: 'bad token' });
    }
    return addBook_(data);
  }

  return jsonOut_({ error: 'unknown action' });
}

// ================== CORE ==================

function getState_() {
  var ss = openReadingSpreadsheet_();
  var booksSh = ss.getSheetByName('2025');
  var logSh   = ss.getSheetByName('log');

  var values = booksSh.getDataRange().getValues();
  var header = values[0];
  var rows   = values.slice(1);

  function col(name){ return header.indexOf(name); }

  // 1. Wczytaj ksiazki
  var books = rows
    .filter(function(r){
      return r[col("Title")] && r[col("Completed")] !== "";
    })
    .map(function(r){
      var percentNum = normalizePercent_( r[col("Completed")] );
      return {
        book_id:      r[col("book_id")],
        title:        r[col("Title")],
        author:       r[col("Author")],
        pagesRead:    r[col("Pages read")],
        pagesTotal:   r[col("All pages")],
        percent:      percentNum,   // 0..100 dla UI
        dueDate:      r[col("Return date")] || null,
        last_update:  r[col("last_update")] || null
      };
    });

  // 2. Policz dueInDays dla kazdej ksiazki
  var today = new Date();
  books.forEach(function(b){
    if (!b.dueDate) {
      b.dueInDays = null;
    } else {
      var due = new Date(b.dueDate);
      var diffMs = due - today;
      var diffDays = Math.ceil(diffMs / (1000*60*60*24));
      b.dueInDays = diffDays;
    }
  });

  // 3. Filtr aktywnych (<100%)
  var activeBooks = books.filter(function(b){
    return b.percent < 100;
  });

  // 4. Wylicz bazowe statsy z loga
  var logStats = calcDailyStats_(logSh);

  // 5. Wylicz dzienny target czytania z terminem zwrotu
  var dailyGoal = computeDailyGoal_(activeBooks);

  // 6. Uzupelnij dzisiejsze KPI
  logStats.todayTarget    = dailyGoal;
  logStats.pagesLeftToday = Math.max(0, dailyGoal - logStats.todayRead);

  // 7. Wybierz ktora ksiazka idzie na top
  var currentIndex = pickCurrentIndex_(activeBooks);

  return jsonOut_({
    dailyStats: logStats,
    activeBooks: activeBooks,
    currentIndex: currentIndex
  });
}

function addBook_(data) {
  var ss = openReadingSpreadsheet_();
  var booksSh = ss.getSheetByName('2025');
  var now = new Date();

  var values = booksSh.getDataRange().getValues();
  var header = values[0];

  function col(name){ return header.indexOf(name); }

  var cBookId = col("book_id");
  var cTitle = col("Title");
  var cAuthor = col("Author");
  var cPagesRead = col("Pages read");
  var cPagesTotal = col("All pages");
  var cReturnDate = col("Return date");
  var cCompleted = col("Completed");
  var cLastUpdate = col("last_update");

  if ([cBookId, cTitle, cAuthor, cPagesRead, cPagesTotal, cCompleted].some(function(i){ return i < 0; })) {
    return jsonOut_({ error: 'columns missing' });
  }

  var title = cleanText_(data.title);
  var author = cleanText_(data.author);
  var source = cleanText_(data.source) === "library" ? "library" : "owned";
  var returnDate = source === "library" ? parseReturnDate_(data.return_date || data.returnDate || data.dueDate) : null;
  var pagesTotal = Math.max(1, Math.round(Number(data.page_total || data.pagesTotal || 0)));
  var pagesRead = Math.max(0, Math.min(pagesTotal, Math.round(Number(data.page_current || data.pagesRead || 0))));

  if (!title) return jsonOut_({ error: 'missing title' });
  if (!author) return jsonOut_({ error: 'missing author' });
  if (!pagesTotal) return jsonOut_({ error: 'missing page_total' });
  if (source === "library" && !returnDate) return jsonOut_({ error: 'missing return_date' });

  var used = collectBookIds_(values, cBookId);
  var bookId = makeUniqueBookId_(title, author, used);
  var percentInt = pagesTotal > 0 ? Math.floor((pagesRead / pagesTotal) * 100) : 0;
  var percentFraction = percentInt / 100;
  var rowIndex = findFirstEmptyBookRow_(values, {
    bookId: cBookId,
    title: cTitle,
    author: cAuthor,
    pagesRead: cPagesRead,
    pagesTotal: cPagesTotal
  });

  var row = new Array(header.length).fill("");
  row[cBookId] = bookId;
  row[cTitle] = title;
  row[cAuthor] = author;
  row[cPagesRead] = pagesRead;
  row[cPagesTotal] = pagesTotal;
  if (cReturnDate >= 0 && returnDate) row[cReturnDate] = returnDate;
  row[cCompleted] = percentFraction;
  if (cLastUpdate >= 0) row[cLastUpdate] = now;

  booksSh.getRange(rowIndex, 1, 1, row.length).setValues([row]);

  return jsonOut_({
    ok: true,
    row: rowIndex,
    book_id: bookId,
    page_current: pagesRead,
    page_total: pagesTotal,
    percent: percentInt,
    book: {
      book_id: bookId,
      title: title,
      author: author,
      pagesRead: pagesRead,
      pagesTotal: pagesTotal,
      percent: percentInt,
      dueDate: returnDate ? returnDate.toISOString() : null,
      last_update: now.toISOString(),
      dueInDays: returnDate ? Math.ceil((returnDate - now) / (1000*60*60*24)) : null
    }
  });
}

// Zapisuje progres strony i dopisuje do log
function updatePage_(data) {
  var ss = openReadingSpreadsheet_();
  var booksSh = ss.getSheetByName('2025');
  var logSh   = ss.getSheetByName('log');

  var bookId  = data.book_id;
  var newPage = Number(data.page_current);
  var now     = new Date();

  var values = booksSh.getDataRange().getValues();
  var header = values[0];
  var rows   = values.slice(1);

  function col(name){ return header.indexOf(name); }

  var rowIndex = -1;
  var rowVals  = null;

  for (var i=0; i<rows.length; i++) {
    if (rows[i][ col("book_id") ] === bookId) {
      rowIndex = i + 2; // header = row 1
      rowVals  = rows[i];
      break;
    }
  }

  if (rowIndex === -1) {
    return jsonOut_({ error:'book_id not found' });
  }

  var pagesTotal = rowVals[col("All pages")];
  var title      = rowVals[col("Title")];
  var author     = rowVals[col("Author")];
  var dueDate    = rowVals[col("Return date")];

  // dopisz wpis do log
  logSh.appendRow([
    now,
    bookId,
    title,
    author,
    newPage,
    pagesTotal,
    dueDate
  ]);

  // przelicz procent ukonczenia
  var newPercentInt = pagesTotal > 0
    ? Math.floor((newPage / pagesTotal) * 100)
    : 0;

  var newPercentFraction = newPercentInt / 100;

  // update w arkuszu "2025"
  booksSh.getRange(rowIndex, col("Pages read")+1).setValue(newPage);
  booksSh.getRange(rowIndex, col("Completed")+1).setValue(newPercentFraction);
  booksSh.getRange(rowIndex, col("last_update")+1).setValue(now);

  return jsonOut_({
    ok: true,
    book_id: bookId,
    page_current: newPage,
    percent: newPercentInt
  });
}

// ================== KPI HELPERS ==================

// Ujednolicamy zapis %. Arkusz trzyma np. 0.32 a chcemy 32.
function normalizePercent_(raw) {
  if (raw === "" || raw === null || raw === undefined) return 0;

  if (typeof raw === "number") {
    if (raw <= 1 && raw >= 0) {
      return Math.round(raw * 100);
    }
    return Math.round(raw);
  }

  if (typeof raw === "string") {
    var num = parseFloat(raw.replace("%",""));
    if (!isNaN(num)) return Math.round(num);
  }
  return 0;
}

function computeDailyGoal_(booksArr) {
  var dated = booksArr.filter(function(b){
    return b.dueInDays != null && b.percent < 100;
  });

  if (dated.length === 0) {
    return 0;
  }

  var earliestDays = dated.reduce(function(minSoFar, b){
    var d = b.dueInDays;
    if (d < 1) d = 1;
    return (d < minSoFar) ? d : minSoFar;
  }, 999999);

  var totalLeft = dated.reduce(function(sum, b){
    var left = Math.max(0, Number(b.pagesTotal) - Number(b.pagesRead));
    return sum + left;
  }, 0);

  return Math.ceil(totalLeft / Math.max(1, earliestDays));
}

function calcDailyStats_(logSh) {
  var raw = logSh.getDataRange().getValues();
  if (!raw || raw.length === 0) {
    return {
      todayRead: 0,
      avgPerDay7d: 0,
      streakDays: 0
    };
  }

  var tz = Session.getScriptTimeZone();

  function dayKey_(d) {
    return Utilities.formatDate(d, tz, 'yyyy-MM-dd');
  }

  var perDayBook = {};

  for (var i = 0; i < raw.length; i++) {
    var row = raw[i];
    var ts = row[0];
    var bid = row[1];
    var pageNow = Number(row[4]);

    if (!(ts instanceof Date)) continue;
    if (!bid) continue;
    if (isNaN(pageNow)) continue;

    var dk = dayKey_(ts);
    if (!perDayBook[dk]) perDayBook[dk] = {};
    if (!perDayBook[dk][bid]) {
      perDayBook[dk][bid] = {min: pageNow, max: pageNow};
    } else {
      if (pageNow < perDayBook[dk][bid].min) perDayBook[dk][bid].min = pageNow;
      if (pageNow > perDayBook[dk][bid].max) perDayBook[dk][bid].max = pageNow;
    }
  }

  var pagesByDay = {};
  for (var dk2 in perDayBook) {
    if (!perDayBook.hasOwnProperty(dk2)) continue;
    var sumDay = 0;
    var byBook = perDayBook[dk2];
    for (var bid2 in byBook) {
      if (!byBook.hasOwnProperty(bid2)) continue;
      var rec = byBook[bid2];
      var delta = rec.max - rec.min;
      if (delta > 0) sumDay += delta;
    }
    pagesByDay[dk2] = sumDay;
  }

  var today = new Date();
  var todayKey = dayKey_(today);
  var todayRead = pagesByDay[todayKey] || 0;

  var total7 = 0;
  for (var off = 0; off < 7; off++) {
    var d = new Date(today.getTime() - off*24*60*60*1000);
    var k = dayKey_(d);
    total7 += (pagesByDay[k] || 0);
  }
  var avg7 = Math.round(total7 / 7);

  var streak = 0;
  for (var step = 0; step < 30; step++) {
    var d2 = new Date(today.getTime() - step*24*60*60*1000);
    var k2 = dayKey_(d2);
    var val = pagesByDay[k2] || 0;
    if (val > 0) {
      streak++;
    } else {
      break;
    }
  }

  return {
    todayRead: todayRead,
    avgPerDay7d: avg7,
    streakDays: streak
  };
}

// ================== OTHER HELPERS ==================

function pickCurrentIndex_(books) {
  if (books.length === 0) return 0;

  var withDue = books
    .map(function(b,i){ return {b:b,i:i}; })
    .filter(function(x){
      return x.b.dueInDays != null && x.b.dueInDays >= 0;
    });

  if (withDue.length > 0) {
    withDue.sort(function(a,b){
      if (a.b.dueInDays !== b.b.dueInDays) {
        return a.b.dueInDays - b.b.dueInDays;
      }
      return a.b.percent - b.b.percent;
    });
    return withDue[0].i;
  }

  var byUpdate = books
    .map(function(b,i){ return {b:b,i:i}; })
    .sort(function(a,b){
      return new Date(b.b.last_update || 0) - new Date(a.b.last_update || 0);
    });

  return byUpdate[0].i;
}

function collectBookIds_(values, cBookId) {
  var used = {};
  for (var i = 1; i < values.length; i++) {
    var id = cleanText_(values[i][cBookId]);
    if (id) used[id] = true;
  }
  return used;
}

function findFirstEmptyBookRow_(values, cols) {
  var startIndex = findFirstBookDataIndex_(values, cols);
  if (startIndex < 1) startIndex = 1;

  for (var i = startIndex; i < values.length; i++) {
    var row = values[i];
    var empty = !cleanText_(row[cols.bookId])
      && !cleanText_(row[cols.title])
      && !cleanText_(row[cols.author])
      && !cleanText_(row[cols.pagesRead])
      && !cleanText_(row[cols.pagesTotal]);
    if (empty) return i + 1;
  }
  return values.length + 1;
}

function findFirstBookDataIndex_(values, cols) {
  for (var i = 1; i < values.length; i++) {
    var row = values[i];
    var hasBookData = cleanText_(row[cols.bookId])
      || cleanText_(row[cols.title])
      || cleanText_(row[cols.author]);
    if (hasBookData) return i;
  }
  return 1;
}

function openReadingSpreadsheet_() {
  return SpreadsheetApp.openById(readingSheetId_());
}

function parseReturnDate_(value) {
  var text = cleanText_(value);
  if (!text) return null;

  var iso = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) {
    return new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
  }

  var parsed = new Date(text);
  if (isNaN(parsed.getTime())) return null;
  return parsed;
}

function makeUniqueBookId_(title, author, used) {
  var base = slugify_([title, author].join("-")) || ("book-" + new Date().getTime());
  var candidate = base;
  var n = 2;
  while (used[candidate]) {
    candidate = base + "-" + n;
    n++;
  }
  used[candidate] = true;
  return candidate;
}

function cleanText_(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function slugify_(value) {
  var replacements = {
    'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n', 'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
    'Ą': 'a', 'Ć': 'c', 'Ę': 'e', 'Ł': 'l', 'Ń': 'n', 'Ó': 'o', 'Ś': 's', 'Ź': 'z', 'Ż': 'z'
  };
  return String(value || '')
    .replace(/[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]/g, function(ch){ return replacements[ch] || ch; })
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

// standardowy output JSON
function jsonOut_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
