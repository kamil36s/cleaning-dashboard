import { describe, expect, it } from 'vitest';

import {
  buildBm365Description_,
  mergeBm365Metadata_,
} from '../js/bm365.js';
import { mergeBm365CrossLists } from '../js/album-cross-lists.js';


describe('BM365 dashboard description', () => {
  it('marks matches from Brutal Assault and RYM at the same time', () => {
    const rows = [{ rowId: 2, artist: 'Evilfeast', album: 'Mysteries of the Nocturnal Forest' }];
    const merged = mergeBm365CrossLists(rows, {
      brutalAssault: {
        matches: [{
          bmRowId: 2,
          baRowId: 8,
          artist: 'Evilfeast',
          album: 'Mysteries of the Nocturnal Forest',
        }],
      },
      rymPolish: {
        rows: [{
          rowId: 42,
          sourceRank: 31,
          artist: 'Evilfeast',
          album: 'Mysteries of the Nocturnal Forest',
        }],
      },
    });

    expect(merged[0].crossLists.map((item) => item.label)).toEqual([
      'Brutal Assault 2027',
      'Top 100 RYM Polish BM',
    ]);
  });

  it('merges local descriptions into Apps Script rows by row id', () => {
    const rows = [{
      rowId: 2,
      date: '2026-01-01',
      artist: 'Darkthrone',
      album: 'A Blaze in the Northern Sky',
    }];

    expect(mergeBm365Metadata_(rows, {
      metadata: [{
        rowId: 2,
        artist: 'Darkthrone',
        album: 'A Blaze in the Northern Sky',
        year: '1992',
        description: '[W SKRÓCIE]\nPierwsze zdanie. Drugie zdanie.\n[CIEKAWOSTKI]\n• Fakt: Treść.',
      }],
    })[0]).toMatchObject({
      year: '1992',
      description: expect.stringContaining('Pierwsze zdanie'),
    });
  });

  it('keeps descriptions with album identities when row ids change', () => {
    const rows = [
      { rowId: 205, artist: 'Cradle of Filth', album: 'Cruelty and the Beast' },
      { rowId: 237, artist: 'Lunar Aurora', album: 'Andacht' },
    ];
    const metadata = [
      { rowId: 205, artist: 'Lunar Aurora', album: 'Andacht', description: 'Lunar description' },
      { rowId: 237, artist: 'Cradle of Filth', album: 'Cruelty and the Beast', description: 'Cradle description' },
    ];

    expect(mergeBm365Metadata_(rows, { metadata }).map((row) => row.description)).toEqual([
      'Cradle description',
      'Lunar description',
    ]);
  });

  it('keeps separate descriptions for duplicate album entries', () => {
    const rows = [{ rowId: 27, artist: 'Bekëth Nexëhmü', album: 'De fördolda klangorna' }];
    const metadata = [
      { ...rows[0], description: 'First entry' },
      { ...rows[0], rowId: 93, description: 'Second entry' },
    ];

    expect(mergeBm365Metadata_(rows, { metadata })[0].description).toBe('First entry');
  });

  it('renders the whole intro in the collapsed summary and the full expandable body', () => {
    const panel = buildBm365Description_({
      artist: 'Darkthrone',
      album: 'A Blaze in the Northern Sky',
      description: '[W SKRÓCIE]\nPierwsze zdanie. Drugie zdanie.\n[CIEKAWOSTKI]\n• Fakt: Treść.',
    });

    expect(panel.tagName).toBe('DETAILS');
    expect(panel.querySelector('summary small')?.textContent).toBe(
      'Pierwsze zdanie. Drugie zdanie.'
    );
    expect(panel.querySelector('.ba2027-description-content')?.textContent).toContain('Fakt: Treść.');
  });
});
