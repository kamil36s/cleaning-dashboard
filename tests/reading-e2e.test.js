import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { Window } from 'happy-dom';

const INDEX_HTML_PATH = path.join(process.cwd(), 'index.html');
const READING_HTML_PATH = path.join(process.cwd(), 'reading.html');
const PRIMARY_READING_API_URL = 'http://localhost/api/reading/books';
const REMOTE_READING_API_URL = 'http://localhost/api/reading/state';
const READING_TOKEN = 'SECRET_READING_TOKEN_666';

const sanitizeHtml = (html) => html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');

const ymd = (value = new Date()) => {
  const dt = new Date(value);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, '0');
  const d = String(dt.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
};

const dmy = (value = new Date()) => {
  const dt = new Date(value);
  const d = String(dt.getDate()).padStart(2, '0');
  const m = String(dt.getMonth() + 1).padStart(2, '0');
  const y = dt.getFullYear();
  return `${d}/${m}/${y}`;
};

const clone = (value) => JSON.parse(JSON.stringify(value));

class MockReadingBackend {
  constructor() {
    this.todayKey = ymd();
    this.updateCalls = [];
    this.bookEditCalls = [];
    this.addCalls = [];
    this.coverUploads = [];
    this.remoteBooks = [
      {
        book_id: 'lords_of_chaos',
        title: 'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia',
        author: 'Michael Moyniham, Didrik Søderlind',
        pagesRead: 80,
        pagesTotal: 410,
        percent: 20,
        dueDate: '2099-04-03T22:00:00.000Z',
        last_update: '2099-03-16T10:00:00.000Z',
        dueInDays: 19,
      },
      {
        book_id: 'lek_spoleczny',
        title: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
        author: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
        pagesRead: 57,
        pagesTotal: 328,
        percent: 17,
        dueDate: '2099-04-06T22:00:00.000Z',
        last_update: '2099-03-16T09:00:00.000Z',
        dueInDays: 22,
      },
    ];
    this.primaryBooks = [
      {
        row: 11,
        title: 'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia',
        author: 'Michael Moyniham, Didrik Søderlind',
        pagesRead: 76,
        pagesAll: 410,
        completedPct: 0.19,
        returnDate: '2099-04-03',
        daysToReturn: 19,
      },
      {
        row: 12,
        title: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
        author: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
        pagesRead: 54,
        pagesAll: 328,
        completedPct: 0.16,
        returnDate: '2099-04-06',
        daysToReturn: 22,
      },
    ];
  }

  buildState() {
    return {
      dailyStats: {
        todayRead: 11,
        avgPerDay7d: 6,
        streakDays: 2,
        todayTarget: 20,
        pagesLeftToday: 9,
      },
      activeBooks: clone(this.remoteBooks),
      currentIndex: 0,
    };
  }

  buildPrimaryFeed() {
    const books = this.primaryBooks.map((book) => {
      const remote = this.remoteBooks.find((entry) => entry.title === book.title);
      const total = Number(remote?.pagesTotal ?? book.pagesAll) || 0;
      const pagesRead = Number(book.pagesRead) || 0;
      const completedPct = total > 0 ? Math.round((pagesRead / total) * 100) / 100 : 0;
      return {
        ...book,
        completedPct,
      };
    });

    return {
      updated: this.todayKey,
      books,
      stats: {
        updated: this.todayKey,
        booksActive: books.length,
        avgPagesPerDay: 6,
        nextReturnDate: '2099-04-03',
        nextReturnInDays: 19,
        pagesPerDayUntilNextReturn: 20,
        pagesLeftAll: this.remoteBooks.reduce((sum, book) => sum + Math.max(0, book.pagesTotal - book.pagesRead), 0),
      },
    };
  }

  handleUpdate(url) {
    const token = url.searchParams.get('token');
    if (token !== READING_TOKEN) {
      return { error: 'bad token' };
    }

    const bookId = url.searchParams.get('book_id');
    const nextPage = Number(url.searchParams.get('page_current'));
    const book = this.remoteBooks.find((entry) => entry.book_id === bookId);
    if (!book) return { error: 'book_id not found' };

    const safePage = Math.max(0, Math.min(Number(book.pagesTotal) || 0, Math.round(nextPage)));
    book.pagesRead = safePage;
    book.percent = book.pagesTotal > 0 ? Math.round((safePage / book.pagesTotal) * 100) : 0;
    book.last_update = '2099-03-16T12:00:00.000Z';

    const primaryBook = this.primaryBooks.find((entry) => entry.title === book.title);
    if (primaryBook) {
      primaryBook.pagesRead = safePage;
      primaryBook.completedPct = book.pagesTotal > 0 ? Math.round((safePage / book.pagesTotal) * 100) / 100 : 0;
    }

    this.updateCalls.push({ bookId, nextPage: safePage });
    return {
      ok: true,
      book_id: bookId,
      page_current: safePage,
      percent: book.percent,
    };
  }

  handleAdd(url) {
    const token = url.searchParams.get('token');
    if (token !== READING_TOKEN) {
      return { error: 'bad token' };
    }

    const title = String(url.searchParams.get('title') || '').trim();
    const author = String(url.searchParams.get('author') || '').trim();
    const pagesTotal = Math.max(1, Math.round(Number(url.searchParams.get('page_total')) || 0));
    const pagesRead = Math.max(0, Math.min(pagesTotal, Math.round(Number(url.searchParams.get('page_current')) || 0)));
    const source = url.searchParams.get('source') === 'library' ? 'library' : 'owned';
    const returnDate = source === 'library' ? String(url.searchParams.get('return_date') || '').trim() : '';
    if (!title || !author || !pagesTotal) {
      return { error: 'bad book payload' };
    }
    if (source === 'library' && !returnDate) {
      return { error: 'missing return_date' };
    }

    const bookId = title
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
    const book = {
      book_id: bookId,
      title,
      author,
      pagesRead,
      pagesTotal,
      percent: Math.round((pagesRead / pagesTotal) * 100),
      dueDate: returnDate || null,
      last_update: '2099-03-16T13:00:00.000Z',
      dueInDays: returnDate ? 30 : null,
    };
    this.remoteBooks.push(book);
    this.primaryBooks.push({
      row: 20 + this.primaryBooks.length,
      title,
      author,
      pagesRead,
      pagesAll: pagesTotal,
      completedPct: pagesRead / pagesTotal,
      returnDate: returnDate || null,
      daysToReturn: returnDate ? 30 : null,
    });
    this.addCalls.push({ title, author, pagesRead, pagesTotal, source, returnDate, bookId });
    return {
      ok: true,
      book_id: bookId,
      book,
    };
  }

  handleBookEdit(bookId, payload) {
    const book = this.remoteBooks.find((entry) => entry.book_id === bookId);
    if (!book) return { error: 'book_id not found' };
    const previousTitle = book.title;
    const primaryBook = this.primaryBooks.find((entry) => entry.title === previousTitle);
    Object.assign(book, {
      title: payload.title,
      author: payload.author,
      pagesRead: payload.pagesRead,
      pagesTotal: payload.pagesTotal,
      dueDate: payload.returnDate || null,
      source: payload.source,
    });
    if (primaryBook) {
      Object.assign(primaryBook, {
        title: payload.title,
        author: payload.author,
        pagesRead: payload.pagesRead,
        pagesAll: payload.pagesTotal,
        returnDate: payload.returnDate || null,
        source: payload.source,
      });
    }
    this.bookEditCalls.push({ bookId, ...payload });
    return { ok: true, book_id: bookId, book: clone(book) };
  }

  async fetch(input, options = {}) {
    const rawUrl = typeof input === 'string' ? input : input?.url;
    const url = new URL(rawUrl, 'http://localhost');

    if (url.pathname === '/api/reading/cover') {
      this.coverUploads.push({ url: url.toString() });
      return createJsonResponse({ ok: true, url: './covers/reading--test-cover.png' });
    }

    if (url.pathname === '/api/reading/books') {
      if (options.method === 'POST') {
        const body = JSON.parse(options.body || '{}');
        const legacyUrl = new URL('http://localhost/legacy');
        legacyUrl.searchParams.set('token', READING_TOKEN);
        legacyUrl.searchParams.set('title', body.title || '');
        legacyUrl.searchParams.set('author', body.author || '');
        legacyUrl.searchParams.set('page_total', body.pagesTotal ?? '');
        legacyUrl.searchParams.set('page_current', body.pagesRead ?? 0);
        legacyUrl.searchParams.set('source', body.source || 'owned');
        legacyUrl.searchParams.set('return_date', body.returnDate || '');
        return createJsonResponse(this.handleAdd(legacyUrl));
      }
      if (!options.method || options.method === 'GET') {
        return createJsonResponse(this.buildPrimaryFeed());
      }
    }

    if (url.pathname === '/api/reading/state') {
      return createJsonResponse(this.buildState());
    }

    const progressMatch = url.pathname.match(/^\/api\/reading\/books\/([^/]+)\/progress$/);
    if (progressMatch && options.method === 'PATCH') {
      const body = JSON.parse(options.body || '{}');
      const legacyUrl = new URL('http://localhost/legacy');
      legacyUrl.searchParams.set('token', READING_TOKEN);
      legacyUrl.searchParams.set('book_id', decodeURIComponent(progressMatch[1]));
      legacyUrl.searchParams.set('page_current', body.pageCurrent);
      return createJsonResponse(this.handleUpdate(legacyUrl));
    }

    const bookMatch = url.pathname.match(/^\/api\/reading\/books\/([^/]+)$/);
    if (bookMatch && options.method === 'PATCH') {
      return createJsonResponse(this.handleBookEdit(
        decodeURIComponent(bookMatch[1]),
        JSON.parse(options.body || '{}'),
      ));
    }

    if (url.pathname === '/api/reading/history') {
      if (options.method === 'POST') return createJsonResponse(JSON.parse(options.body || '{}'));
      return createJsonResponse({ log: {}, startKey: '', forecastPlan: null });
    }

    if (url.pathname === '/api/reading/settings') {
      if (options.method === 'POST') return createJsonResponse(JSON.parse(options.body || '{}'));
      return createJsonResponse({});
    }

    throw new Error(`Unexpected fetch request: ${url.toString()}`);
  }
}

function createJsonResponse(data, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    async json() {
      return clone(data);
    },
  };
}

function handleLocalProgressRequest(backend, url, options = {}) {
  const match = url.pathname.match(/^\/api\/reading\/books\/([^/]+)\/progress$/);
  if (!match || options.method !== 'PATCH') return null;
  const body = JSON.parse(options.body || '{}');
  const legacyUrl = new URL('http://localhost/legacy');
  legacyUrl.searchParams.set('token', READING_TOKEN);
  legacyUrl.searchParams.set('book_id', decodeURIComponent(match[1]));
  legacyUrl.searchParams.set('page_current', body.pageCurrent);
  return createJsonResponse(backend.handleUpdate(legacyUrl));
}

function createDelayedJsonResponse(data, delayMs, ok = true) {
  return new Promise((resolve) => {
    setTimeout(() => resolve(createJsonResponse(data, ok)), delayMs);
  });
}

function dispatchStorageEvent(window, key) {
  const event = typeof window.StorageEvent === 'function'
    ? new window.StorageEvent('storage', { key })
    : new window.Event('storage');
  if (!('key' in event)) {
    Object.defineProperty(event, 'key', { value: key });
  }
  window.dispatchEvent(event);
}

async function installDom(htmlPath, pageUrl) {
  const html = sanitizeHtml(await readFile(htmlPath, 'utf8'));
  const window = new Window({ url: pageUrl });
  window.document.write(html);
  window.document.close();

  const previous = new Map();
  const assign = (key, value) => {
    previous.set(key, globalThis[key]);
    globalThis[key] = value;
  };

  assign('window', window);
  assign('document', window.document);
  assign('navigator', window.navigator);
  assign('localStorage', window.localStorage);
  assign('location', window.location);
  assign('history', window.history);
  assign('Event', window.Event);
  assign('CustomEvent', window.CustomEvent);
  assign('MouseEvent', window.MouseEvent);
  assign('KeyboardEvent', window.KeyboardEvent);
  assign('FocusEvent', window.FocusEvent);
  assign('HTMLElement', window.HTMLElement);
  assign('HTMLFormElement', window.HTMLFormElement);
  assign('HTMLInputElement', window.HTMLInputElement);
  assign('HTMLButtonElement', window.HTMLButtonElement);
  assign('File', window.File);
  assign('FileReader', window.FileReader);
  assign('Image', window.Image);
  assign('Node', window.Node);
  assign('getComputedStyle', window.getComputedStyle.bind(window));
  assign('requestAnimationFrame', (cb) => setTimeout(() => cb(Date.now()), 0));
  assign('cancelAnimationFrame', (id) => clearTimeout(id));

  return () => {
    for (const [key, value] of previous.entries()) {
      if (value === undefined) {
        delete globalThis[key];
      } else {
        globalThis[key] = value;
      }
    }
    window.close();
  };
}

async function waitFor(assertion, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? 1500;
  const intervalMs = opts.intervalMs ?? 10;
  const started = Date.now();
  let lastError = null;

  while ((Date.now() - started) < timeoutMs) {
    try {
      const result = await assertion();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  if (lastError) throw lastError;
  throw new Error('waitFor timeout');
}

function getTodayLog() {
  const raw = window.localStorage.getItem('readingDailyLog.v2');
  return raw ? JSON.parse(raw) : {};
}

function findReadingCardByTitle(title) {
  return [...document.querySelectorAll('#grid .card')].find((card) => {
    const titleNode = card.querySelector('.title');
    return titleNode?.textContent?.trim() === title;
  }) || null;
}

function findReadingCardByTitleFragment(titleFragment) {
  return [...document.querySelectorAll('#grid .card')].find((card) => {
    const titleNode = card.querySelector('.title');
    return titleNode?.textContent?.includes(titleFragment);
  }) || null;
}

function findWidgetBookButtonByTitle(titleFragment) {
  return [...document.querySelectorAll('#rdg-active-grid .reading-bookbtn')].find((button) => (
    button.textContent?.includes(titleFragment)
  )) || null;
}

describe('Reading E2E', () => {
  let restoreDom;
  let backend;

  beforeEach(() => {
    vi.resetModules();
    vi.doMock('../js/config.js', () => ({
      API: '',
      WRITE_TOKEN: '',
      READING_WRITE_TOKEN: READING_TOKEN,
      READING_API_URL: REMOTE_READING_API_URL,
      OPENAI_PROXY: '',
      COORDS: { lat: 0, lon: 0 },
      TIMEZONE: 'Europe/Warsaw',
      REFRESH_MS: 300000,
      TEMP_STOPS: [],
      WX_COLORS: {},
    }));
    backend = new MockReadingBackend();
    restoreDom = null;
  });

  afterEach(() => {
    if (restoreDom) restoreDom();
    vi.restoreAllMocks();
  });

  it('covers widget flow on mocked backend without touching real data', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    backend.primaryBooks.push({
      row: 13,
      title: 'Primary-only unfinished book',
      author: 'Shelf Import',
      pagesRead: 10,
      pagesAll: 200,
      completedPct: 0.05,
    });
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      [ymd()]: {
        total: 11,
        books: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo': 11,
        },
      },
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Władcy Chaosu');
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('80 / 410');
      expect(document.getElementById('rdg-active-count')?.textContent).toContain('(3)');
      expect(findWidgetBookButtonByTitle('Primary-only unfinished book')).toBeTruthy();
      return true;
    });

    const input = document.getElementById('rdg-page-input');
    const button = document.getElementById('rdg-save-btn');
    expect(input).toBeTruthy();
    expect(button).toBeTruthy();

    input.value = '57';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(1);
      expect(backend.remoteBooks[0].pagesRead).toBe(57);
      return true;
    });

    input.value = '80';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(2);
      expect(backend.remoteBooks[0].pagesRead).toBe(80);
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('80 / 410');
      expect(document.getElementById('rdg-save-feedback')?.textContent).toContain('Zapisano');
      return true;
    });

    const todayLog = getTodayLog();
    const todayEntry = todayLog[ymd()];
    expect(todayEntry.total).toBe(34);
    expect(todayEntry.books['Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo']).toBe(11);
    expect(todayEntry.books['Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik Søderlind']).toBe(23);
  });

  it('keeps widget progress when the post-save refresh briefly returns stale pages', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');

    const staleRemoteBooks = clone(backend.remoteBooks);
    const stalePrimaryBooks = clone(backend.primaryBooks);
    let updateSeen = false;
    const fetchSpy = vi.fn((input, options = {}) => {
      const rawUrl = typeof input === 'string' ? input : input?.url;
      const url = new URL(rawUrl, 'http://localhost');

      if (url.pathname === '/api/reading/books' && (!options.method || options.method === 'GET')) {
        if (updateSeen) {
          return createJsonResponse({ ...backend.buildPrimaryFeed(), books: clone(stalePrimaryBooks) });
        }
        return createJsonResponse(backend.buildPrimaryFeed());
      }

      if (url.pathname === '/api/reading/state') {
        if (updateSeen) {
          return createJsonResponse({ ...backend.buildState(), activeBooks: clone(staleRemoteBooks) });
        }
        return createJsonResponse(backend.buildState());
      }

      const progressResponse = handleLocalProgressRequest(backend, url, options);
      if (progressResponse) {
        updateSeen = true;
        return progressResponse;
      }
      return backend.fetch(input, options);
    });
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Chaosu');
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('80 / 410');
      return true;
    });

    const input = document.getElementById('rdg-page-input');
    const button = document.getElementById('rdg-save-btn');
    input.value = '81';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(1);
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('81 / 410');
      expect(document.getElementById('rdg-today-target')?.textContent).toBe('1/2 str.');
      return true;
    });

    await new Promise((resolve) => setTimeout(resolve, 260));

    await waitFor(() => {
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('81 / 410');
      expect(document.getElementById('rdg-today-target')?.textContent).toBe('1/2 str.');
      expect(getTodayLog()[ymd()]?.total).toBe(1);
      return true;
    });

  });

  it('shows the summed library overdue fee in the return tile', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    backend.remoteBooks[0].dueInDays = -4;
    backend.remoteBooks[1].dueInDays = -2;
    backend.primaryBooks[0].daysToReturn = -4;
    backend.primaryBooks[1].daysToReturn = -2;

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Władcy Chaosu');
      expect(document.getElementById('rdg-due-in')?.textContent).toBe('-4 dni');
      const fee = document.getElementById('rdg-return-fee');
      expect(fee?.hidden).toBe(false);
      expect(fee?.textContent).toBe('Kara: 2,10 zł');
      return true;
    });
  });

  it('adds one dashboard notification when a library return is due within seven days', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    backend.remoteBooks[0].dueInDays = 7;
    backend.remoteBooks[1].dueInDays = 8;
    backend.primaryBooks[0].daysToReturn = 7;
    backend.primaryBooks[1].daysToReturn = 8;

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      const notifications = JSON.parse(localStorage.getItem('dashboard.notifications.v1') || '[]');
      expect(notifications).toHaveLength(1);
      expect(notifications[0]).toMatchObject({
        category: 'Czytanie',
        targetId: 'reading-card',
      });
      expect(notifications[0].title).toContain('Władcy Chaosu');
      expect(notifications[0].message).toContain('zostało 7 dni');
      return true;
    });
  });

  it('keeps widget reading delta correct for Lęk when local log contains legacy duplicate labels', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    backend.remoteBooks[1].pagesRead = 120;
    backend.remoteBooks[1].percent = 37;
    backend.primaryBooks[1].pagesRead = 120;
    backend.primaryBooks[1].completedPct = 0.37;
    window.localStorage.setItem('readingWidgetSelectedBook.v1', JSON.stringify({
      remoteId: 'lek_spoleczny',
      key: 'remote:lek_spoleczny',
    }));
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      [ymd()]: {
        total: 120,
        progress: {
          'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym': {
            label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym',
            start: 0,
            current: 120,
          },
          'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo': {
            label: 'L?k przed innymi. Jak radzi? sobie z l?kiem spo?ecznym - Christophe Andr?, Patrick L?geron, Antoine Pelissolo',
            start: 120,
            current: 120,
          },
        },
      },
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Lęk przed innymi');
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('120 / 328');
      return true;
    });

    const input = document.getElementById('rdg-page-input');
    const button = document.getElementById('rdg-save-btn');
    expect(input).toBeTruthy();
    expect(button).toBeTruthy();

    input.value = '138';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls.at(-1)).toMatchObject({ bookId: 'lek_spoleczny', nextPage: 138 });
      return true;
    });

    const todayLog = getTodayLog();
    const todayEntry = todayLog[ymd()];
    expect(todayEntry.total).toBe(18);
    expect(Object.values(todayEntry.books || {})).toEqual([18]);
  });

  it('keeps widget reading delta correct for Lęk after the delayed post-save refresh runs', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    backend.remoteBooks[1].pagesRead = 120;
    backend.remoteBooks[1].percent = 37;
    backend.primaryBooks[1].pagesRead = 120;
    backend.primaryBooks[1].completedPct = 0.37;
    window.localStorage.setItem('readingWidgetSelectedBook.v1', JSON.stringify({
      remoteId: 'lek_spoleczny',
      key: 'remote:lek_spoleczny',
    }));
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      [ymd()]: {
        total: 120,
        books: {
          'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo': 120,
        },
        progress: {
          'remote:lek_spoleczny': {
            key: 'remote:lek_spoleczny',
            bookKey: 'remote:lek_spoleczny',
            label: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym - Christophe André, Patrick Légeron, Antoine Pelissolo',
            title: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
            author: 'Christophe André, Patrick Légeron, Antoine Pelissolo',
            start: 0,
            current: 120,
          },
        },
      },
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Lęk przed innymi');
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('120 / 328');
      return true;
    });

    const input = document.getElementById('rdg-page-input');
    const button = document.getElementById('rdg-save-btn');
    input.value = '138';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls.at(-1)).toMatchObject({ bookId: 'lek_spoleczny', nextPage: 138 });
      return true;
    });

    await new Promise((resolve) => setTimeout(resolve, 350));

    const todayLog = getTodayLog();
    const todayEntry = todayLog[ymd()];
    expect(todayEntry.total).toBe(18);
    expect(Object.values(todayEntry.books || {})).toEqual([18]);
  });

  it('allows undoing the last page save from the reading widget', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Chaosu');
      return true;
    });

    const input = document.getElementById('rdg-page-input');
    const button = document.getElementById('rdg-save-btn');
    expect(input).toBeTruthy();
    expect(button).toBeTruthy();

    input.value = '81';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(1);
      expect(backend.remoteBooks[0].pagesRead).toBe(81);
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('81 / 410');
      expect(document.querySelector('#undo-toast .undo-toast-btn')).toBeTruthy();
      return true;
    });

    document.querySelector('#undo-toast .undo-toast-btn')?.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(2);
      expect(backend.remoteBooks[0].pagesRead).toBe(80);
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('80 / 410');
      return true;
    });

    expect(getTodayLog()[ymd()]).toBeUndefined();
  });

  it('adds a gold glow to the reading widget when the daily target is reached', async () => {
    const firstDue = new Date();
    firstDue.setDate(firstDue.getDate() + 19);
    backend.remoteBooks[0].dueDate = firstDue.toISOString();
    backend.remoteBooks[0].dueInDays = 19;
    backend.primaryBooks[0].returnDate = ymd(firstDue);
    backend.primaryBooks[0].daysToReturn = 19;

    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      [ymd()]: {
        total: 20,
        books: {
          'W?adcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik S?derlind': 20,
        },
      },
    }));
    window.localStorage.setItem('readingOwnershipMap.v1', JSON.stringify(Object.fromEntries([
      [`${String(backend.remoteBooks[0].title).trim().toLowerCase()}|${String(backend.remoteBooks[0].author).trim().toLowerCase()}|${backend.remoteBooks[0].pagesTotal}`, 'library'],
    ])));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('reading-card')?.classList.contains('is-goal-complete')).toBe(true);
      expect(document.getElementById('rdg-today-target')?.textContent).toBe('20/19 str.');
      expect(document.getElementById('rdg-goal-ring')?.classList.contains('is-complete')).toBe(true);
      expect(document.querySelector('.reading-week-day.is-today')?.classList.contains('is-complete')).toBe(true);
      expect(document.querySelector('.reading-week-day.is-today .reading-week-dot')?.textContent).toBe('✓');
      expect(document.getElementById('rdg-streak')?.textContent).toBe('1 dzień serii');
      return true;
    });
  });

  it('restores the last selected widget book after reopening the page', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Władcy Chaosu');
      return true;
    });

    const selectedButton = findWidgetBookButtonByTitle('Lęk przed innymi');
    expect(selectedButton).toBeTruthy();
    selectedButton.click();

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Lęk przed innymi');
      return true;
    });

    const persistedSelection = window.localStorage.getItem('readingWidgetSelectedBook.v1');
    expect(persistedSelection).toContain('lek_spoleczny');

    restoreDom();
    restoreDom = null;

    vi.resetModules();
    vi.doMock('../js/config.js', () => ({
      API: '',
      WRITE_TOKEN: '',
      READING_WRITE_TOKEN: READING_TOKEN,
      READING_API_URL: REMOTE_READING_API_URL,
      OPENAI_PROXY: '',
      COORDS: { lat: 0, lon: 0 },
      TIMEZONE: 'Europe/Warsaw',
      REFRESH_MS: 300000,
      TEMP_STOPS: [],
      WX_COLORS: {},
    }));

    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    window.localStorage.setItem('readingWidgetSelectedBook.v1', persistedSelection);

    const reopenedFetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = reopenedFetchSpy;
    window.fetch = reopenedFetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Lęk przed innymi');
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('57 / 328');
      return true;
    });
  });

  it('covers reading panel load, merge and save flow on mocked backend', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(document.getElementById('active')?.textContent).toBe('2');
      expect(findReadingCardByTitle('Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia')).toBeTruthy();
      return true;
    });

    const card = findReadingCardByTitle('Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia');
    const footer = card.querySelector('.reading-pages-summary');
    expect(footer?.textContent).toContain('80 / 410');

    const input = card.querySelector('.reading-page-input');
    const button = card.querySelector('.reading-save-btn');
    expect(input).toBeTruthy();
    expect(button).toBeTruthy();

    input.value = '81';
    button.click();

    await waitFor(() => {
      const refreshedCard = findReadingCardByTitle('Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia');
      expect(backend.updateCalls).toHaveLength(1);
      expect(backend.remoteBooks[0].pagesRead).toBe(81);
      expect(refreshedCard?.querySelector('.reading-pages-summary')?.textContent).toContain('81 / 410');
      expect(refreshedCard?.querySelector('.reading-save-feedback')?.textContent).toContain('Zapisano');
      return true;
    });

    await waitFor(() => {
      expect(document.getElementById('reading-history-total-badge')?.textContent).toContain('1 str.');
      expect(document.getElementById('reading-history-stats')?.textContent).toContain('Dzisiaj');
      expect(document.getElementById('reading-history-stats')?.textContent).toContain('1 str.');
      return true;
    });

    const todayBar = [...document.querySelectorAll('#reading-history-chart .history-bar')]
      .find((bar) => bar.textContent.includes('1 str.'));
    expect(todayBar).toBeTruthy();
  });

  it('keeps active books above inactive books on reading.html', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');
    window.localStorage.setItem('readingActiveMap.v1', JSON.stringify({
      'remote:lords_of_chaos': false,
      'remote:lek_spoleczny': true,
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      const cards = [...document.querySelectorAll('#grid .card')];
      expect(cards.length).toBeGreaterThan(2);
      expect(cards[0].querySelector('.active-toggle')?.getAttribute('aria-pressed')).toBe('true');
      expect(cards[0].querySelector('.title')?.textContent).toContain('Lęk przed innymi');
      expect(cards[1].querySelector('.active-toggle')?.getAttribute('aria-pressed')).toBe('false');
      return true;
    });

    document.getElementById('wanted-only').checked = true;
    document.getElementById('wanted-only').dispatchEvent(new Event('change', { bubbles: true }));

    await waitFor(() => {
      const cards = [...document.querySelectorAll('#grid .card')];
      expect(cards).toHaveLength(20);
      expect(document.getElementById('reading-page-info')?.textContent).toMatch(/^1 \/ \d+ \(1-20 z \d+\)$/);
      expect(cards[0].querySelector('.ownership-toggle')?.getAttribute('aria-label')).toBe('Chcę przeczytać');
      expect(document.getElementById('reading-page-info')?.textContent).toMatch(/z \d{3,}/);
      return true;
    });

    const pageSize = document.getElementById('reading-page-size');
    pageSize.value = '10';
    pageSize.dispatchEvent(new Event('change', { bubbles: true }));

    await waitFor(() => {
      expect([...document.querySelectorAll('#grid .card')]).toHaveLength(10);
      expect(document.getElementById('reading-page-info')?.textContent).toMatch(/^1 \/ \d+ \(1-10 z \d+\)$/);
      return true;
    });

    document.getElementById('reading-page-next').click();

    await waitFor(() => {
      expect([...document.querySelectorAll('#grid .card')]).toHaveLength(10);
      expect(document.getElementById('reading-page-info')?.textContent).toMatch(/^2 \/ \d+ \(11-20 z \d+\)$/);
      return true;
    });
  });

  it('allows adding a book from reading.html with an uploaded cover', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const previousImage = globalThis.Image;
    class MockImage {
      constructor() {
        this.width = 12;
        this.height = 18;
        this.naturalWidth = 12;
        this.naturalHeight = 18;
      }

      set src(value) {
        this._src = value;
        setTimeout(() => this.onload?.(this), 0);
      }

      get src() {
        return this._src;
      }
    }
    globalThis.Image = MockImage;
    window.Image = MockImage;

    try {
      const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
      globalThis.fetch = fetchSpy;
      window.fetch = fetchSpy;

      await import('../js/reading.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      await waitFor(() => {
        expect(document.getElementById('active')?.textContent).toBe('2');
        return true;
      });
      window.localStorage.setItem('readingActiveMap.v1', JSON.stringify({
        'remote:lords_of_chaos': true,
        'remote:lek_spoleczny': false,
      }));

      document.getElementById('reading-add-author').value = 'Ursula K. Le Guin';
      document.getElementById('reading-add-title').value = 'Lewa ręka ciemności';
      document.getElementById('reading-add-pages-read').value = '24';
      document.getElementById('reading-add-pages-total').value = '304';
      document.querySelector('input[name="source"][value="library"]').checked = true;
      document.querySelector('input[name="source"][value="library"]')
        .dispatchEvent(new Event('change', { bubbles: true }));
      expect(document.getElementById('reading-add-return-date-wrap')?.classList.contains('is-hidden')).toBe(false);
      const addDatePicker = document.querySelector('#reading-add-return-date-wrap [data-reading-date-picker]');
      addDatePicker.value = '2099-04-15';
      addDatePicker.dispatchEvent(new Event('change', { bubbles: true }));
      expect(document.getElementById('reading-add-return-date').value).toBe('15/04/2099');
      Object.defineProperty(document.getElementById('reading-add-cover'), 'files', {
        value: [new File(['cover'], 'cover.png', { type: 'image/png' })],
        configurable: true,
      });
      document.getElementById('reading-add-cover').dispatchEvent(new Event('change', { bubbles: true }));
      expect(document.getElementById('reading-add-cover-name')?.textContent).toBe('cover.png');

      document.getElementById('reading-add-book-form')
        .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await waitFor(() => {
        expect(backend.addCalls).toHaveLength(1);
        expect(backend.addCalls[0]).toMatchObject({
          title: 'Lewa ręka ciemności',
          author: 'Ursula K. Le Guin',
          pagesRead: 24,
          pagesTotal: 304,
          source: 'library',
          returnDate: '2099-04-15',
        });
        const activeMap = JSON.parse(window.localStorage.getItem('readingActiveMap.v1') || '{}');
        expect(activeMap[`remote:${backend.addCalls[0].bookId}`]).toBe(true);
        const ownershipMap = JSON.parse(window.localStorage.getItem('readingOwnershipMap.v1') || '{}');
        expect(ownershipMap[`remote:${backend.addCalls[0].bookId}`]).toBe('library');
        expect(findReadingCardByTitle('Lewa ręka ciemności')).toBeTruthy();
        const activeStates = [...document.querySelectorAll('#grid .active-toggle')]
          .map((button) => button.getAttribute('aria-pressed'));
        expect(activeStates[0]).toBe('true');
        return true;
      });

      await waitFor(() => {
        expect(backend.coverUploads).toHaveLength(1);
        expect(document.getElementById('reading-add-book-status')?.textContent).toContain('Książka dodana');
        return true;
      });
    } finally {
      globalThis.Image = previousImage;
      window.Image = previousImage;
    }
  });

  it('edits a book inline and uses dd/mm/yyyy for its return date', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(findReadingCardByTitleFragment('Chaosu')).toBeTruthy();
      return true;
    });

    let card = findReadingCardByTitleFragment('Chaosu');
    const cardsBeforeEdit = [...document.querySelectorAll('#grid .reading-book-card')];
    card.querySelector('.reading-book-edit-toggle').click();
    expect(findReadingCardByTitleFragment('Chaosu')).toBe(card);
    expect([...document.querySelectorAll('#grid .reading-book-card')]).toEqual(cardsBeforeEdit);
    const form = card.querySelector('.reading-book-edit-form');
    expect(form).toBeTruthy();
    expect(form.elements.returnDate.value).toBe('03/04/2099');
    form.elements.returnDate.value = '5/10/2099';
    form.elements.returnDate.dispatchEvent(new Event('input', { bubbles: true }));
    form.elements.returnDate.dispatchEvent(new Event('blur'));
    expect(form.elements.returnDate.value).toBe('05/10/2099');
    expect(form.querySelector('[data-reading-date-picker]').value).toBe('2099-10-05');

    form.elements.title.value = 'Władcy Chaosu — wydanie poprawione';
    form.elements.pagesTotal.value = '420';
    const editDatePicker = form.querySelector('[data-reading-date-picker]');
    editDatePicker.value = '2099-10-05';
    editDatePicker.dispatchEvent(new Event('change', { bubbles: true }));
    expect(form.elements.returnDate.value).toBe('05/10/2099');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

    await waitFor(() => {
      expect(backend.bookEditCalls).toHaveLength(1);
      expect(backend.bookEditCalls[0]).toMatchObject({
        bookId: 'lords_of_chaos',
        title: 'Władcy Chaosu — wydanie poprawione',
        pagesTotal: 420,
        returnDate: '2099-10-05',
      });
      card = findReadingCardByTitle('Władcy Chaosu — wydanie poprawione');
      expect(card).toBeTruthy();
      expect(card.querySelector('.reading-book-edit-form')).toBeNull();
      return true;
    });
  });

  it('marks a library book as returned from the ownership hover menu', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(findReadingCardByTitleFragment('Chaosu')).toBeTruthy();
      return true;
    });

    const card = findReadingCardByTitleFragment('Chaosu');
    const returnedButton = card.querySelector('.reading-book-returned');
    expect(card.querySelector('.ownership-toggle')?.getAttribute('aria-label')).toBe('Biblioteka');
    expect(returnedButton?.textContent).toContain('Książka oddana');
    expect(returnedButton?.disabled).toBe(false);
    returnedButton.click();

    await waitFor(() => {
      expect(backend.bookEditCalls.at(-1)).toMatchObject({
        bookId: 'lords_of_chaos',
        source: 'library',
        returnDate: null,
      });
      const refreshedCard = findReadingCardByTitleFragment('Chaosu');
      expect(refreshedCard?.querySelector('.due-badge')?.textContent).toBe('Brak');
      expect(refreshedCard?.querySelector('.reading-book-returned')?.disabled).toBe(true);
      return true;
    });
  });

  it('keeps panel progress when the post-save refresh briefly returns stale pages', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const staleRemoteBooks = clone(backend.remoteBooks);
    const stalePrimaryBooks = clone(backend.primaryBooks);
    let updateSeen = false;
    const fetchSpy = vi.fn((input, options = {}) => {
      const rawUrl = typeof input === 'string' ? input : input?.url;
      const url = new URL(rawUrl, 'http://localhost');

      if (url.pathname === '/api/reading/books' && (!options.method || options.method === 'GET')) {
        if (updateSeen) {
          return createJsonResponse({ ...backend.buildPrimaryFeed(), books: clone(stalePrimaryBooks) });
        }
        return createJsonResponse(backend.buildPrimaryFeed());
      }

      if (url.pathname === '/api/reading/state') {
        if (updateSeen) {
          return createJsonResponse({ ...backend.buildState(), activeBooks: clone(staleRemoteBooks) });
        }
        return createJsonResponse(backend.buildState());
      }

      const progressResponse = handleLocalProgressRequest(backend, url, options);
      if (progressResponse) {
        updateSeen = true;
        return progressResponse;
      }
      return backend.fetch(input, options);
    });
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(findReadingCardByTitleFragment('Chaosu')).toBeTruthy();
      return true;
    });

    const card = findReadingCardByTitleFragment('Chaosu');
    const input = card.querySelector('.reading-page-input');
    const button = card.querySelector('.reading-save-btn');
    input.value = '81';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(1);
      expect(findReadingCardByTitleFragment('Chaosu')?.querySelector('.reading-pages-summary')?.textContent).toContain('81 / 410');
      expect(document.getElementById('reading-history-total-badge')?.textContent).toContain('1 str.');
      return true;
    });

    await new Promise((resolve) => setTimeout(resolve, 260));

    await waitFor(() => {
      expect(findReadingCardByTitleFragment('Chaosu')?.querySelector('.reading-pages-summary')?.textContent).toContain('81 / 410');
      expect(document.getElementById('reading-history-total-badge')?.textContent).toContain('1 str.');
      expect(getTodayLog()[ymd()]?.total).toBe(1);
      return true;
    });
  });

  it('allows undoing the last page save from reading.html', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(findReadingCardByTitleFragment('Chaosu')).toBeTruthy();
      return true;
    });

    const card = findReadingCardByTitleFragment('Chaosu');
    const input = card.querySelector('.reading-page-input');
    const button = card.querySelector('.reading-save-btn');
    expect(input).toBeTruthy();
    expect(button).toBeTruthy();

    input.value = '81';
    button.click();

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(1);
      expect(backend.remoteBooks[0].pagesRead).toBe(81);
      expect(findReadingCardByTitleFragment('Chaosu')?.querySelector('.reading-pages-summary')?.textContent).toContain('81 / 410');
      expect(document.querySelector('#undo-toast .undo-toast-btn')).toBeTruthy();
      return true;
    });

    document.querySelector('#undo-toast .undo-toast-btn')?.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

    await waitFor(() => {
      expect(backend.updateCalls).toHaveLength(2);
      expect(backend.remoteBooks[0].pagesRead).toBe(80);
      expect(findReadingCardByTitleFragment('Chaosu')?.querySelector('.reading-pages-summary')?.textContent).toContain('80 / 410');
      return true;
    });

    expect(getTodayLog()[ymd()]).toBeUndefined();
  });

  it('adds a gold goal border in week and month history views when a day hits its target', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const today = new Date();
    const todayKey = ymd(today);
    const todayLabel = dmy(today);

    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      [todayKey]: {
        total: 2,
        books: {
          [`${backend.remoteBooks[0].title} - ${backend.remoteBooks[0].author}`]: 1,
          [`${backend.remoteBooks[1].title} - ${backend.remoteBooks[1].author}`]: 1,
        },
      },
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    const findBarForDate = () => [...document.querySelectorAll('#reading-history-chart .history-bar')]
      .find((bar) => bar.querySelector('.history-bar-label-date')?.textContent?.trim() === todayLabel);

    await waitFor(() => {
      const bar = findBarForDate();
      expect(bar).toBeTruthy();
      expect(bar?.classList.contains('is-goal-hit')).toBe(true);
      return true;
    });

    document.querySelector('#reading-history .history-range-btn[data-range="month"]')
      ?.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

    await waitFor(() => {
      const bar = findBarForDate();
      expect(bar).toBeTruthy();
      expect(bar?.classList.contains('is-goal-hit')).toBe(true);
      return true;
    });
  });

  it('keeps current-week target lines perfectly proportional and hides them in past weeks', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const today = new Date();
    const todayKey = ymd(today);
    const todayLabel = dmy(today);

    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      [todayKey]: {
        total: 8,
        books: {
          [`${backend.remoteBooks[1].title} - ${backend.remoteBooks[1].author}`]: 8,
        },
      },
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    const findBarForDate = () => [...document.querySelectorAll('#reading-history-chart .history-bar')]
      .find((bar) => bar.querySelector('.history-bar-label-date')?.textContent?.trim() === todayLabel);

    await waitFor(() => {
      const bar = findBarForDate();
      expect(bar).toBeTruthy();
      expect(bar?.querySelector('.history-bar-target-line')).toBeTruthy();
      return true;
    });

    const todayBar = findBarForDate();
    const fill = todayBar?.querySelector('.history-bar-fill');
    const targetLine = todayBar?.querySelector('.history-bar-target-line');
    const valueText = todayBar?.querySelector('.history-bar-value')?.textContent || '';
    const targetText = targetLine?.querySelector('.history-bar-target-badge')?.textContent || '';
    const fillStyle = fill?.getAttribute('style') || '';
    const targetStyle = targetLine?.getAttribute('style') || '';
    const value = Number.parseInt(valueText, 10);
    const target = Number.parseInt(targetText, 10);
    const fillPct = Number((fillStyle.match(/height:\s*([\d.]+)%/i) || [])[1]);
    const targetPct = Number((targetStyle.match(/bottom:\s*calc\(([\d.]+)%\s*-\s*1px\)/i) || [])[1]);

    expect(Number.isFinite(value)).toBe(true);
    expect(Number.isFinite(target)).toBe(true);
    expect(Number.isFinite(fillPct)).toBe(true);
    expect(Number.isFinite(targetPct)).toBe(true);
    expect(Math.abs((fillPct / targetPct) - (value / target))).toBeLessThan(0.001);
    expect(targetLine?.classList.contains('is-badge-below')).toBe(targetPct >= 72);

    document.querySelector('#reading-history .history-nav-btn[data-direction="prev"]')
      ?.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

    await waitFor(() => {
      expect(document.querySelectorAll('#reading-history-chart .history-bar').length).toBe(7);
      expect(document.querySelectorAll('#reading-history-chart .history-bar-target-line')).toHaveLength(0);
      return true;
    });
  });

  it('ignores stale widget fetch responses and keeps the latest synced state', async () => {
    restoreDom = await installDom(INDEX_HTML_PATH, 'http://localhost:5173/index.html');
    window.localStorage.setItem('readingWidgetSelectedBook.v1', JSON.stringify({
      remoteId: 'lek_spoleczny',
      key: 'remote:lek_spoleczny',
    }));

    let stateCalls = 0;
    let primaryCalls = 0;
    const fetchSpy = vi.fn((input, options = {}) => {
      const rawUrl = typeof input === 'string' ? input : input?.url;
      const url = new URL(rawUrl, 'http://localhost');

      if (url.pathname === '/api/reading/books' && (!options.method || options.method === 'GET')) {
        const snapshot = backend.buildPrimaryFeed();
        const call = primaryCalls++;
        const delay = call === 1 ? 120 : 10;
        return createDelayedJsonResponse(snapshot, delay);
      }

      if (url.pathname === '/api/reading/state') {
        const snapshot = backend.buildState();
        const call = stateCalls++;
        const delay = call === 1 ? 120 : 10;
        return createDelayedJsonResponse(snapshot, delay);
      }

      return handleLocalProgressRequest(backend, url, options) || backend.fetch(input, options);
    });
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/widget-reading.js');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Lęk przed innymi');
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('57 / 328');
      return true;
    });

    backend.remoteBooks[1].pagesRead = 120;
    backend.remoteBooks[1].percent = 37;
    backend.primaryBooks[1].pagesRead = 120;
    backend.primaryBooks[1].completedPct = 0.37;
    dispatchStorageEvent(window, 'readingDashboardSync.v1');

    backend.remoteBooks[1].pagesRead = 138;
    backend.remoteBooks[1].percent = 42;
    backend.primaryBooks[1].pagesRead = 138;
    backend.primaryBooks[1].completedPct = 0.42;
    dispatchStorageEvent(window, 'readingDashboardSync.v1');

    await waitFor(() => {
      expect(document.getElementById('rdg-book-title')?.textContent).toContain('Lęk przed innymi');
      expect(document.getElementById('rdg-progress-text')?.textContent).toContain('138 / 328');
      return true;
    }, { timeoutMs: 1200 });

    await new Promise((resolve) => setTimeout(resolve, 180));

    expect(document.getElementById('rdg-progress-text')?.textContent).toContain('138 / 328');
  });

  it('ignores stale panel fetch responses and keeps the newest reading data', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    let stateCalls = 0;
    let primaryCalls = 0;
    const fetchSpy = vi.fn((input, options = {}) => {
      const rawUrl = typeof input === 'string' ? input : input?.url;
      const url = new URL(rawUrl, 'http://localhost');

      if (url.pathname === '/api/reading/books' && (!options.method || options.method === 'GET')) {
        const snapshot = backend.buildPrimaryFeed();
        const call = primaryCalls++;
        const delay = call === 1 ? 120 : 10;
        return createDelayedJsonResponse(snapshot, delay);
      }

      if (url.pathname === '/api/reading/state') {
        const snapshot = backend.buildState();
        const call = stateCalls++;
        const delay = call === 1 ? 120 : 10;
        return createDelayedJsonResponse(snapshot, delay);
      }

      return handleLocalProgressRequest(backend, url, options) || backend.fetch(input, options);
    });
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      const card = findReadingCardByTitleFragment('Lęk przed innymi');
      expect(card).toBeTruthy();
      expect(card?.querySelector('.reading-pages-summary')?.textContent).toContain('57 / 328');
      return true;
    });

    backend.remoteBooks[1].pagesRead = 120;
    backend.remoteBooks[1].percent = 37;
    backend.primaryBooks[1].pagesRead = 120;
    backend.primaryBooks[1].completedPct = 0.37;
    document.getElementById('refresh')?.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

    backend.remoteBooks[1].pagesRead = 138;
    backend.remoteBooks[1].percent = 42;
    backend.primaryBooks[1].pagesRead = 138;
    backend.primaryBooks[1].completedPct = 0.42;
    document.getElementById('refresh')?.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

    await waitFor(() => {
      const card = findReadingCardByTitleFragment('Lęk przed innymi');
      expect(card).toBeTruthy();
      expect(card?.querySelector('.reading-pages-summary')?.textContent).toContain('138 / 328');
      return true;
    }, { timeoutMs: 1200 });
  });

  it('shows the best day from the current reading range, not from all-time history', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');
    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      '2026-01-02': {
        total: 99,
        books: {
          'Stary wpis - Autor': 99,
        },
      },
      [ymd()]: {
        total: 1,
        books: {
          'Dzisiejsza książka - Autor': 1,
        },
      },
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      const stats = document.getElementById('reading-history-stats')?.textContent || '';
      expect(stats).toContain('Najlepszy dzień');
      expect(stats).toContain('1 str.');
      return true;
    });

    expect(document.getElementById('reading-history-stats')?.textContent || '').not.toContain('99 str.');
  });

  it('uses yearly reading view as 12 monthly summaries and hides quarter range', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(document.querySelector('#reading-history .history-range-btn[data-range="year"]')).toBeTruthy();
      return true;
    });

    expect(document.querySelector('#reading-history .history-range-btn[data-range="quarter"]')).toBeNull();

    document.querySelector('#reading-history .history-range-btn[data-range="year"]')?.click();

    await waitFor(() => {
      expect(document.querySelectorAll('#reading-history-chart .history-bar').length).toBe(12);
      expect(document.getElementById('reading-history-stats')?.textContent).toContain('Średnio / miesiąc');
      expect(document.getElementById('reading-history-stats')?.textContent).toContain('Ten miesiąc');
      return true;
    });

    const monthLabels = [...document.querySelectorAll('#reading-history-chart .history-bar-label.is-month-summary .history-bar-label-day')]
      .map((node) => node.textContent?.trim() || '')
      .filter(Boolean);

    expect(monthLabels).toHaveLength(12);
    expect(document.querySelectorAll('#reading-history-chart .history-bar-label.is-month-summary .history-bar-label-date')).toHaveLength(12);
  });

  it('keeps the assigned cover color for a book in historical months', async () => {
    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');
    const historicalDay = new Date(new Date().getFullYear(), 0, 15);
    const label = `${backend.remoteBooks[0].title} - ${backend.remoteBooks[0].author}`;
    const assignedColor = '#a17bc4';

    window.localStorage.setItem('readingDailyLog.v2', JSON.stringify({
      [ymd(historicalDay)]: {
        total: 31,
        books: { [label]: 31 },
      },
    }));
    window.localStorage.setItem('readingBookCoverColors.v1', JSON.stringify({
      'remote:lords_of_chaos': {
        url: './covers/reading--lords.jpg?v=1',
        color: assignedColor,
        ts: Date.now(),
      },
    }));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(document.querySelector('#reading-history .history-range-btn[data-range="year"]')).toBeTruthy();
      return true;
    });
    document.querySelector('#reading-history .history-range-btn[data-range="year"]')?.click();

    await waitFor(() => {
      const segment = [...document.querySelectorAll('#reading-history-chart .history-bar-segment')]
        .find((node) => node.getAttribute('style')?.includes(assignedColor));
      expect(segment).toBeTruthy();
      return true;
    });
  });

  it('shows future reading week as empty bars with forecast lines only', async () => {
    const firstDue = new Date();
    firstDue.setDate(firstDue.getDate() + 19);
    const secondDue = new Date();
    secondDue.setDate(secondDue.getDate() + 22);

    backend.remoteBooks[0].dueDate = firstDue.toISOString();
    backend.remoteBooks[0].dueInDays = 19;
    backend.remoteBooks[1].dueDate = secondDue.toISOString();
    backend.remoteBooks[1].dueInDays = 22;
    backend.primaryBooks[0].returnDate = ymd(firstDue);
    backend.primaryBooks[0].daysToReturn = 19;
    backend.primaryBooks[1].returnDate = ymd(secondDue);
    backend.primaryBooks[1].daysToReturn = 22;

    restoreDom = await installDom(READING_HTML_PATH, 'http://localhost:5173/reading.html');
    window.localStorage.setItem('readingOwnershipMap.v1', JSON.stringify(
      Object.fromEntries(backend.remoteBooks.map((book) => [
        `${String(book.title || '').trim().toLowerCase()}|${String(book.author || '').trim().toLowerCase()}|${book.pagesTotal}`,
        'library',
      ])),
    ));

    const fetchSpy = vi.fn((input, options) => backend.fetch(input, options));
    globalThis.fetch = fetchSpy;
    window.fetch = fetchSpy;

    await import('../js/reading.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    await waitFor(() => {
      expect(document.querySelector('#reading-history .history-nav-btn[data-direction="next"]')).toBeTruthy();
      expect(document.querySelectorAll('#reading-history-chart .history-bar').length).toBeGreaterThan(0);
      return true;
    });

    document.querySelector('#reading-history .history-nav-btn[data-direction="next"]')?.click();

    await waitFor(() => {
      expect(document.getElementById('reading-history-window-label')?.textContent).toContain('Prognoza:');
      return true;
    });

    const bars = [...document.querySelectorAll('#reading-history-chart .history-bar')];
    const fills = [...document.querySelectorAll('#reading-history-chart .history-bar-fill')];
    const targetLines = [...document.querySelectorAll('#reading-history-chart .history-bar-target-line')];
    const tooltipPayloads = [...document.querySelectorAll('#reading-history-chart .history-bar-tooltip-data')];
    const visibleValues = [...document.querySelectorAll('#reading-history-chart .history-bar-value')]
      .map((node) => node.textContent?.trim() || '')
      .filter(Boolean);

    expect(bars).toHaveLength(7);
    expect(fills).toHaveLength(7);
    expect(tooltipPayloads).toHaveLength(7);
    expect(targetLines).toHaveLength(7);
    expect(fills.every((fill) => fill.classList.contains('is-empty'))).toBe(true);
    expect(document.querySelectorAll('#reading-history-chart .history-bar-segment')).toHaveLength(0);
    expect(tooltipPayloads.every((node) => node.textContent?.includes('Target dnia'))).toBe(true);
    expect(document.querySelectorAll('#reading-history-chart .history-bar-tooltip-item')).toHaveLength(0);
    expect(visibleValues).toHaveLength(0);
    expect(document.getElementById('reading-history-total-badge')?.textContent).toContain('prognoza / tydzień');
  });
});
