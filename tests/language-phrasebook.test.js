import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderPhrasebook } from '../js/language/views/phrasebook.js';

describe('Language Phrasebook view', () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it('renders external and user text as text and exposes intentional edits', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    const onUpdate = vi.fn(async () => {});
    renderPhrasebook(mount, {
      loading: false, error: null, query: '', sourceType: '', total: 1,
      items: [{
        id: 'entry', sourceType: 'READER', sourceEntityId: 'doc',
        expressionText: '<img src=x onerror=alert(1)>',
        sourceContext: '<script>alert(1)</script>',
        userTranslation: '<b>translation</b>', note: '<i>note</i>', links: [],
      }],
    }, { onSearch: vi.fn(), onUpdate, onDelete: vi.fn() });
    expect(mount.querySelector('script')).toBeNull();
    expect(mount.querySelector('img')).toBeNull();
    expect(mount.textContent).toContain('<img src=x onerror=alert(1)>');
    const fields = mount.querySelectorAll('textarea');
    fields[0].value = 'user translation';
    fields[1].value = 'user note';
    mount.querySelector('.language-phrasebook-entry .is-primary').click();
    await Promise.resolve();
    expect(onUpdate).toHaveBeenCalledWith('entry', {
      note: 'user note', userTranslation: 'user translation',
    });
  });

  it('shows an explicit empty state', () => {
    const mount = document.createElement('div');
    renderPhrasebook(mount, {
      loading: false, error: null, query: '', sourceType: '', total: 0, items: [],
    }, { onSearch: vi.fn(), onUpdate: vi.fn(), onDelete: vi.fn() });
    expect(mount.textContent).toContain('No saved expressions');
  });
});
