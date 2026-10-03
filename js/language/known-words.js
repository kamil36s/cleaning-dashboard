/** The Reader's explicit KNOWN and MASTERED vocabulary, shared by both headers. */
export function createKnownWordsControl({ api, profileId, count = null, baseHref = '' }) {
  const details = document.createElement('details');
  details.className = 'language-known-words';
  const summary = document.createElement('summary');
  const label = document.createElement('span');
  label.textContent = 'Known Words';
  const value = document.createElement('strong');
  value.textContent = count == null ? '—' : String(count);
  summary.append(label, value);
  const panel = document.createElement('div');
  panel.className = 'language-known-words-panel';
  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Find a known word';
  search.setAttribute('aria-label', 'Find a known word');
  const list = document.createElement('ul');
  const note = document.createElement('p');
  const more = document.createElement('button');
  more.type = 'button';
  more.textContent = 'Load more';
  more.hidden = true;
  panel.append(search, list, note, more);
  details.append(summary, panel);

  let cursors = { KNOWN: null, MASTERED: null };
  let finished = { KNOWN: false, MASTERED: false };
  let items = [];
  let loaded = false;
  let sequence = 0;
  let timer;

  function render() {
    list.replaceChildren();
    items.sort((a, b) => String(a.lemmaDisplay).localeCompare(String(b.lemmaDisplay), 'nb'));
    items.forEach((item) => {
      const row = document.createElement('li');
      const link = document.createElement('a');
      link.href = `${baseHref}#vocabulary/lemma/${encodeURIComponent(item.id)}`;
      link.textContent = item.lemmaDisplay;
      row.append(link);
      list.append(row);
    });
    note.textContent = items.length ? `${items.length} shown` : 'No known words found.';
    more.hidden = finished.KNOWN && finished.MASTERED;
  }

  async function load(reset = false) {
    const current = ++sequence;
    if (reset) {
      cursors = { KNOWN: null, MASTERED: null };
      finished = { KNOWN: false, MASTERED: false };
      items = [];
    }
    note.textContent = 'Loading words…';
    more.disabled = true;
    try {
      const statuses = ['KNOWN', 'MASTERED'].filter((status) => !finished[status]);
      const pages = await Promise.all(statuses.map((status) => api.vocabulary(profileId, {
        status, disposition: 'TRACKED', q: search.value.trim(), limit: 100,
        cursor: cursors[status] || undefined,
      })));
      if (current !== sequence) return;
      pages.forEach((page, index) => {
        const status = statuses[index];
        items.push(...(page.items || []));
        cursors[status] = page.pagination?.nextCursor || null;
        finished[status] = !cursors[status];
      });
      loaded = true;
      render();
    } catch (error) {
      if (current === sequence) note.textContent = error?.message || 'Known words could not be loaded.';
    } finally {
      if (current === sequence) more.disabled = false;
    }
  }

  details.addEventListener('toggle', () => { if (details.open && !loaded) load(true); });
  search.addEventListener('input', () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => load(true), 220);
  });
  more.addEventListener('click', () => load());
  details.setCount = (nextCount) => { value.textContent = nextCount == null ? '—' : String(nextCount); };
  details.refresh = () => { if (details.open) load(true); else loaded = false; };
  return details;
}
