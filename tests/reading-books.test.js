import { describe, expect, it, vi } from 'vitest';

vi.mock('../js/reading-api.js', () => ({
  fetchReadingSettings: vi.fn(() => Promise.resolve(null)),
  saveReadingSettings: vi.fn(() => Promise.resolve()),
}));
import {
  calculateReadingLogDelta,
  getReadingBookColor,
  getReadingBookColorForLabel,
  getReadingMapValue,
  getReadingRemoteId,
  isReadingPageEditable,
  mergeReadingBooksWithRemoteState,
  normalizeReadingBook,
  resolveReadingProgressBaseline,
  getReadingKnownRemotePage,
} from '../js/reading-books.js';

describe('Reading book sync helpers', () => {
  it('merges remote widget state into matching panel books', () => {
    const primaryBooks = [
      {
        row: 24,
        title: 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym',
        author: 'Christophe Andre',
        pagesAll: 328,
        pagesRead: 65,
        completedPct: 0.2,
        returnDate: '2026-03-22',
        daysToReturn: 6,
      },
    ];
    const remoteBooks = [
      {
        book_id: 'lek_przed_innymi',
        title: 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym',
        author: 'Christophe Andre',
        pagesTotal: 328,
        pagesRead: 69,
        percent: 21,
        dueDate: '2026-03-22',
        dueInDays: 6,
      },
    ];

    const [merged] = mergeReadingBooksWithRemoteState(primaryBooks, remoteBooks);

    expect(merged.book_id).toBe('lek_przed_innymi');
    expect(merged.pagesRead).toBe(69);
    expect(merged.pagesAll).toBe(328);
    expect(merged.percent).toBe(21);
    expect(merged.completedPct).toBe(0.21);
    expect(merged.returnDate).toBe('2026-03-22');
    expect(merged.daysToReturn).toBe(6);
  });

  it('keeps unmatched completed books but marks them as not editable', () => {
    const primaryBooks = [
      {
        row: 2,
        title: 'Silva Rerum',
        author: 'Kristina Sabaliauskaite',
        pagesAll: 511,
        pagesRead: 511,
        completedPct: 1,
      },
    ];

    const [merged] = mergeReadingBooksWithRemoteState(primaryBooks, []);

    expect(merged.title).toBe('Silva Rerum');
    expect(merged.pagesRead).toBe(511);
    expect(isReadingPageEditable(merged)).toBe(false);
  });

  it('appends active remote-only books that are missing from the primary feed', () => {
    const merged = mergeReadingBooksWithRemoteState([], [
      {
        book_id: 'solaris',
        title: 'Solaris',
        author: 'Stanislaw Lem',
        pagesTotal: 204,
        pagesRead: 50,
        percent: 25,
      },
    ]);

    expect(merged).toHaveLength(1);
    expect(merged[0].book_id).toBe('solaris');
    expect(merged[0].pagesRead).toBe(50);
  });

  it('still merges the same book when total pages changed between feeds', () => {
    const [merged] = mergeReadingBooksWithRemoteState([
      {
        row: 24,
        title: 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym',
        author: 'Christophe Andre',
        pagesAll: 328,
        pagesRead: 65,
        completedPct: 0.2,
      },
    ], [
      {
        book_id: 'lek_przed_innymi',
        title: 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym',
        author: 'Christophe Andre',
        pagesTotal: 330,
        pagesRead: 69,
        percent: 21,
      },
    ]);

    expect(merged.book_id).toBe('lek_przed_innymi');
    expect(merged.pagesRead).toBe(69);
    expect(merged.pagesAll).toBe(330);
  });

  it('does not treat row ids as valid remote ids for page updates', () => {
    expect(getReadingRemoteId({ row: 17, row_id: 17 })).toBeNull();
    expect(getReadingRemoteId({ book_id: 'solaris' })).toBe('solaris');
    expect(getReadingRemoteId({ bookId: 'diuna' })).toBe('diuna');
    expect(getReadingRemoteId({ id: 'lord-jim' })).toBe('lord-jim');
  });

  it('uses remote baseline first when calculating daily reading delta', () => {
    expect(calculateReadingLogDelta({
      nextPages: 69,
      remotePages: 69,
      localPages: 65,
    })).toBe(0);

    expect(calculateReadingLogDelta({
      nextPages: 69,
      remotePages: 65,
      localPages: 65,
    })).toBe(4);
  });

  it('never returns negative delta when page number goes backwards', () => {
    expect(calculateReadingLogDelta({
      nextPages: 65,
      remotePages: 69,
      localPages: 69,
    })).toBe(0);
  });

  it('normalizes primary records into consistent reading shape', () => {
    const book = normalizeReadingBook({
      title: 'Solaris',
      author: 'Stanislaw Lem',
      pagesAll: 204,
      pagesRead: 102,
      completedPct: 0.5,
      returnDate: '2026-03-30',
      daysToReturn: 14,
    });

    expect(book.pagesTotal).toBe(204);
    expect(book.pagesLeft).toBe(102);
    expect(book.percent).toBe(50);
    expect(book.dueDate).toBe('2026-03-30');
    expect(book.dueInDays).toBe(14);
  });

  it('prefers the older visible page when backend already equals the target page', () => {
    expect(resolveReadingProgressBaseline({
      nextPages: 266,
      remotePages: 266,
      localPages: 265,
    })).toBe(265);

    expect(resolveReadingProgressBaseline({
      nextPages: 300,
      remotePages: 290,
      localPages: 280,
    })).toBe(290);

    expect(resolveReadingProgressBaseline({
      nextPages: 256,
      remotePages: 255,
      localPages: 265,
    })).toBe(255);
  });

  it('uses the last known remote page when the live remote snapshot is unavailable', () => {
    expect(resolveReadingProgressBaseline({
      nextPages: 138,
      remotePages: null,
      knownPages: 130,
      localPages: 120,
    })).toBe(130);

    expect(resolveReadingProgressBaseline({
      nextPages: 266,
      remotePages: null,
      knownPages: 266,
      localPages: 255,
    })).toBe(255);
  });

  it('returns the same stable color for the same book across views', () => {
    const panelBook = {
      title: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
      author: 'Christophe André',
      pagesAll: 328,
    };
    const widgetBook = {
      title: 'Lęk przed innymi. Jak radzić sobie z lękiem społecznym',
      author: 'Christophe André',
      pagesTotal: 328,
      percent: 21,
    };

    expect(getReadingBookColor(panelBook)).toBe(getReadingBookColor(widgetBook));
  });

  it('uses the same muted palette color for label-based history bars', () => {
    const book = {
      title: 'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia',
      author: 'Michael Moyniham, Didrik Søderlind',
      pagesTotal: 410,
    };
    const label = 'Władcy Chaosu: Krwawe powstanie satanistycznego metalowego podziemia - Michael Moyniham, Didrik Søderlind';

    expect(getReadingBookColorForLabel(label)).toBe(getReadingBookColor(book));
    expect(getReadingBookColor(book)).not.toContain('hsl(');
  });

  it('resolves legacy ownership keys after switching to canonical reading keys', () => {
    const book = {
      book_id: 'lek_spoleczny',
      title: 'Lek przed innymi. Jak radzic sobie z lekiem spolecznym',
      author: 'Christophe Andre, Patrick Legeron, Antoine Pelissolo',
      pagesTotal: 328,
    };
    const legacyMap = {
      'lek przed innymi. jak radzic sobie z lekiem spolecznym|christophe andre, patrick legeron, antoine pelissolo|328': 'library',
    };

    expect(getReadingMapValue(legacyMap, book)).toBe('library');
  });

  it('reads last known remote page snapshots by remote id', () => {
    expect(getReadingKnownRemotePage({ lek_spoleczny: 130 }, { book_id: 'lek_spoleczny' })).toBe(130);
    expect(getReadingKnownRemotePage({ lek_spoleczny: 130 }, 'lek_spoleczny')).toBe(130);
  });
});
