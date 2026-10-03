import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function response(payload) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload), text: () => Promise.resolve(JSON.stringify(payload)) });
}

describe('Music page', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.removeItem('music-view-preferences-v1');
    window.happyDOM.setURL('http://localhost:3000/music.html#overview');
    document.body.innerHTML = `
      <nav class="music-nav"><button data-music-view="overview">Przegląd</button><button data-music-view="library">Biblioteka</button><button data-music-view="genres">Gatunki</button><button data-music-view="history">Historia</button><button data-music-view="imports">Import</button></nav>
      <h2 id="music-heading"></h2><form id="music-global-search"><input></form>
      <section id="music-search-results" hidden></section><main id="music-content"></main>
      <div id="music-connection"><strong></strong></div><div id="music-toast" hidden></div>
      <dialog id="music-release-dialog"><button data-close-dialog></button><div id="music-release-detail"></div></dialog>`;
    global.fetch = vi.fn((input) => {
      const url = new URL(input, window.location.origin);
      if (url.pathname.endsWith('/overview')) return response({
        ok: true,
        stats: { releases: 1, artists: 1, genres: 2, ratings: 0 },
        projects: [], recentImports: [], recentRankings: [],
        lastfm: { status: { totalScrobbles: 10 }, stats: {}, rows: [] },
      });
      if (url.pathname.endsWith('/library')) return response({ ok: true, rows: [], total: 0, offset: 0, limit: 50 });
      if (url.pathname.endsWith('/rankings/artists')) return response({
        ok: true, rows: [{ id: 7, name: 'Artist', average_rating: 4.25, weighted_rating: 4.1, rated_count: 4, five_star_count: 1, release_ids: [11, 12] }],
        total: 1, offset: 0, limit: 100, globalAverage: 3.9,
      });
      if (url.pathname.endsWith('/genres/tree')) return response({
        ok: true,
        total: 5,
        genres: [
          { id: 1, name: 'Ambient', release_count: 2, child_count: 2, parent_count: 0 },
          { id: 2, name: 'Ambient Americana', release_count: 1, child_count: 0, parent_count: 1 },
          { id: 3, name: 'Drone', release_count: 1, child_count: 0, parent_count: 1 },
          { id: 4, name: 'Rock', release_count: 9, child_count: 0, parent_count: 0 },
          { id: 5, name: "Children's Music", slug: 'childrens-music', release_count: 0, child_count: 0, parent_count: 0 },
        ],
        relations: [{ parentId: 1, childId: 2 }, { parentId: 1, childId: 3 }],
      });
      if (url.pathname.endsWith('/lastfm')) return response({
        ok: true,
        stats: { scrobbles: 120, artists: 5, albums: 10, tracks: 20 },
        topArtists: [{ artist: 'Artist', scrobbles: 50 }],
        topAlbums: [{ artist: 'Artist', album: 'Album', scrobbles: 40 }],
        rows: Array.from({ length: url.searchParams.get('offset') === '50' ? 20 : 50 }, (_, index) => ({
          track: `Track ${index}`, artist: 'Artist', album: 'Album', playedAt: '2026-09-11T10:00:00Z',
        })),
      });
      if (url.pathname.endsWith('/missing-metadata')) return response({
        ok: true, total: 1, limit: 50, offset: 0,
        rows: [{ id: 9, title: 'Incomplete Album', artist_credit: 'Artist', release_year: 2020, missing_labels: ['okładka', 'tracklista'] }],
      });
      return response({ ok: true, rows: [] });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it('renders overview and navigates to the paginated library', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.querySelector('#music-content').textContent).toContain('Albumy');
    expect(document.querySelector('#music-content').textContent).toContain('1');

    document.querySelector('[data-music-view="library"]').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.querySelector('#music-heading').textContent).toBe('Biblioteka');
    expect(document.querySelector('#music-content').textContent).toContain('Katalog kanoniczny');
  });

  it('renders genre roots first and expands children lazily', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-music-view="genres"]').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const branches = document.querySelectorAll('.music-genre-branch');
    expect(branches).toHaveLength(1);
    expect(branches[0].hasAttribute('open')).toBe(false);
    branches[0].querySelector('summary').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.querySelectorAll('.music-genre-branch, .music-genre-leaf')).toHaveLength(5);
    expect(document.querySelector('#music-content').textContent).toContain('5 gatunków');
    expect(document.querySelector('[data-art-kind="genre"]')).not.toBeNull();
  });

  it('moves utility genre roots into a separate section at the bottom', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-music-view="genres"]').click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const primaryTree = document.querySelector('#music-content > .music-section > .music-genre-tree');
    const primaryNames = [...primaryTree.children]
      .map((node) => node.querySelector('.music-genre-name')?.textContent);
    const secondary = document.querySelector('.music-genre-secondary');
    expect(primaryNames).not.toContain("Children's Music");
    expect(secondary?.textContent).toContain('Kategorie użytkowe i pozamuzyczne');
    expect(secondary?.textContent).toContain("Children's Music");
    expect(secondary?.nextElementSibling).toBeNull();
  });

  it('sorts root genres by the number of albums', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-music-view="genres"]').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const form = document.querySelector('#music-genre-search');
    form.querySelector('[name="sort"]').value = 'albums';
    expect(new FormData(form).get('sort')).toBe('albums');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => {
      expect(document.querySelector('.music-genre-tree > :first-child .music-genre-name').textContent).toBe('Rock');
    });
  });

  it('uses server-side offsets for history pagination', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-music-view="history"]').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.querySelector('.music-pagination').textContent).toContain('1–50 z 120');
    document.querySelector('[data-history-page="next"]').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const historyCall = global.fetch.mock.calls.findLast(([input]) => new URL(input, window.location.origin).pathname.endsWith('/lastfm'));
    expect(new URL(historyCall[0], window.location.origin).searchParams.get('offset')).toBe('50');
    expect(document.querySelector('.music-pagination').textContent).toContain('51–70 z 120');
  });

  it('renders the live missing-metadata queue in Import', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-music-view="imports"]').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.querySelector('#music-content').textContent).toContain('Braki w katalogu');
    expect(document.querySelector('#music-content').textContent).toContain('Incomplete Album');
    expect(document.querySelector('.music-missing-tags').textContent).toContain('tracklista');
    expect(document.querySelector('#music-missing-filter [value="rym_rating"]')).toBeNull();
    expect(document.querySelector('[data-queue-enrichment]')).not.toBeNull();
  });

  it('shows the artist ranking and filters the library by artist', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    const rankingButton = document.createElement('button');
    rankingButton.dataset.openView = 'rankings';
    document.body.append(rankingButton);
    rankingButton.click();
    await vi.waitFor(() => expect(document.querySelector('[data-artist-filter="Artist"]')).not.toBeNull());
    expect(document.querySelector('[data-artist-filter="Artist"]').textContent).toContain('4,25');
    expect(document.querySelector('[data-artist-filter="Artist"]').textContent).toContain('4,1');
    expect(document.querySelector('#music-content').textContent).toContain('Single i EP');
    const sort = document.querySelector('#music-artist-ranking-sort');
    sort.value = 'average';
    const artistForm = document.querySelector('#music-artist-filters');
    artistForm.querySelector('[name="yearMode"]').value = 'decade';
    artistForm.querySelector('[name="yearMode"]').dispatchEvent(new Event('change', { bubbles: true }));
    artistForm.querySelector('[name="decade"]').value = '1980';
    artistForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => {
      const rankingCall = global.fetch.mock.calls.findLast(([input]) => new URL(input, window.location.origin).pathname.endsWith('/rankings/artists'));
      expect(new URL(rankingCall[0], window.location.origin).searchParams.get('sort')).toBe('average');
      expect(new URL(rankingCall[0], window.location.origin).searchParams.get('decade')).toBe('1980');
    });
    document.querySelector('[data-artist-filter="Artist"]').click();
    await vi.waitFor(() => expect(document.querySelector('#music-heading').textContent).toBe('Biblioteka'));
    const call = global.fetch.mock.calls.findLast(([input]) => new URL(input, window.location.origin).pathname.endsWith('/library'));
    expect(new URL(call[0], window.location.origin).searchParams.get('q')).toBe('Artist');
    expect(new URL(call[0], window.location.origin).searchParams.get('ids')).toBe('11,12');
  });

  it('filters the library by a year range and rated status', async () => {
    await import('../js/music.js');
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-music-view="library"]').click();
    await vi.waitFor(() => expect(document.querySelector('#music-library-filters')).not.toBeNull());
    const form = document.querySelector('#music-library-filters');
    expect(form.querySelector('[name="sort"]').value).toBe('my_desc');
    expect(document.querySelector('.music-filter-explanation').textContent).toContain('Odsłuchane: status z projektów muzycznych');
    const mode = form.querySelector('[name="yearMode"]');
    mode.value = 'range';
    mode.dispatchEvent(new Event('change', { bubbles: true }));
    expect(form.querySelector('[name="yearFrom"]').closest('label').hidden).toBe(false);
    expect(form.querySelector('[name="year"]').closest('label').hidden).toBe(true);
    form.querySelector('[name="yearFrom"]').value = '1984';
    form.querySelector('[name="yearTo"]').value = '1991';
    const rated = form.querySelector('[name="showRated"]');
    rated.checked = false;
    rated.dispatchEvent(new Event('change', { bubbles: true }));
    form.querySelector('[name="sort"]').value = 'rym_desc';
    expect(form.querySelector('[name="rating"]').disabled).toBe(true);
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => {
      const call = global.fetch.mock.calls.findLast(([input]) => new URL(input, window.location.origin).pathname.endsWith('/library'));
      const params = new URL(call[0], window.location.origin).searchParams;
      expect(params.get('yearMode')).toBe('range');
      expect(params.get('yearFrom')).toBe('1984');
      expect(params.get('yearTo')).toBe('1991');
      expect(params.get('showRated')).toBe('0');
      expect(params.get('showUnrated')).toBe('1');
      expect(params.get('sort')).toBe('rym_desc');
    });
  });

  it('restores the saved view and library choices after opening the page again', async () => {
    localStorage.setItem('music-view-preferences-v1', JSON.stringify({
      view: 'library', libraryFilters: { limit: 50, q: 'Pink Floyd', sort: 'year_desc', yearMode: 'decade', decade: '1970' },
    }));
    window.happyDOM.setURL('http://localhost:3000/music.html');
    await import('../js/music.js');
    await vi.waitFor(() => expect(document.querySelector('#music-library-filters')).not.toBeNull());
    expect(document.querySelector('#music-heading').textContent).toBe('Biblioteka');
    const form = document.querySelector('#music-library-filters');
    expect(form.querySelector('[name="q"]').value).toBe('Pink Floyd');
    expect(form.querySelector('[name="sort"]').value).toBe('year_desc');
    expect(form.querySelector('[name="decade"]').value).toBe('1970');
    const call = global.fetch.mock.calls.findLast(([input]) => new URL(input, window.location.origin).pathname.endsWith('/library'));
    expect(new URL(call[0], window.location.origin).searchParams.get('decade')).toBe('1970');
  });
});
