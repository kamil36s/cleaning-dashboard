import { describe, expect, it, vi } from 'vitest';
import { createKnownWordsControl } from '../js/language/known-words.js';

describe('Known Words control', () => {
  it('lists tracked known and mastered lemmas with links to their details', async () => {
    const api = { vocabulary: vi.fn(async (_profile, params) => ({
      items: params.status === 'KNOWN'
        ? [{ id: 'known-id', lemmaDisplay: 'bok' }]
        : [{ id: 'mastered-id', lemmaDisplay: 'hus' }],
      pagination: { nextCursor: null },
    })) };
    const control = createKnownWordsControl({ api, profileId: 'profile', count: 2, baseHref: './language.html' });
    document.body.append(control);
    try {
      expect(control.querySelector('summary').textContent).toContain('Known Words2');
      expect(api.vocabulary).not.toHaveBeenCalled();
      control.open = true;
      control.dispatchEvent(new Event('toggle'));
      await vi.waitFor(() => expect(control.querySelectorAll('li a')).toHaveLength(2));
      expect(api.vocabulary).toHaveBeenCalledWith('profile', expect.objectContaining({ status: 'KNOWN', disposition: 'TRACKED' }));
      expect(api.vocabulary).toHaveBeenCalledWith('profile', expect.objectContaining({ status: 'MASTERED', disposition: 'TRACKED' }));
      expect([...control.querySelectorAll('li a')].map((link) => link.getAttribute('href')))
        .toEqual(['./language.html#vocabulary/lemma/known-id', './language.html#vocabulary/lemma/mastered-id']);
      control.setCount(3);
      expect(control.querySelector('summary strong').textContent).toBe('3');
    } finally {
      control.remove();
    }
  });
});
