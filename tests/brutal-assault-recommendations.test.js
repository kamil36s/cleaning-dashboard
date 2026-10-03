import { describe, expect, it } from 'vitest';

import {
  albumDescriptionTeaser,
  buildBrutalAssaultAlbumPrompt,
  buildBrutalAssaultBulkDescriptionPrompt,
  buildRymPolishBlackMetalAlbumPrompt,
  buildRymPolishBlackMetalBulkDescriptionPrompt,
  buildBrutalAssaultRecommendationQueue,
  buildBrutalAssaultArtistRatingRankings,
  brutalAssaultMixedRating,
  communityRatingLabel,
  computeBrutalAssaultDeadlineStats,
  countAlbumDescriptionSentences,
  isUnheardArtist,
  parseBrutalAssaultBulkDescriptionJson,
  renderBrutalAssaultAlbumDescription,
  renderBrutalAssaultDeadlineSummary,
  sortBrutalAssaultAlbumsByRating,
  validateRymDescriptionBatch,
} from '../js/brutal-assault-recommendations.js';

const album = (rowId, artist, title, extras = {}) => ({
  rowId,
  artist,
  album: title,
  date: `2026-08-${String(rowId).padStart(2, '0')}`,
  listened: false,
  communityRating: null,
  communityVotes: 0,
  rymRating: null,
  ...extras,
});

describe('Brutal Assault recommendation queue', () => {
  it('builds a personalized prompt and counts the maximum description length', () => {
    const prompt = buildBrutalAssaultAlbumPrompt({ artist: 'Hypocrisy', album: 'Abducted' });
    expect(prompt).toContain('Hypocrisy');
    expect(prompt).toContain('Abducted');
    expect(prompt).toContain('Maksymalnie 10 zdań');
    expect(prompt).toContain('[CIEKAWOSTKI]');
    expect(prompt).toContain('• Krótkie hasło:');
    expect(countAlbumDescriptionSentences('Jedno. Dwa! Trzy?')).toBe(3);
  });

  it('builds and parses the token-efficient bulk description workflow', () => {
    const prompt = buildBrutalAssaultBulkDescriptionPrompt([
      album(195, 'Plebeian Grandstand', 'Rien ne suffit'),
      album(196, 'Hypocrisy', 'Abducted'),
    ]);
    expect(prompt).toContain('195|Plebeian Grandstand|Rien ne suffit');
    expect(prompt).toContain('196|Hypocrisy|Abducted');
    expect(prompt).toContain('Maksymalnie 7 zdań');

    expect(parseBrutalAssaultBulkDescriptionJson('```json\n{"195":"[W SKRÓCIE]\\nOpis."}\n```')).toEqual({
      195: '[W SKRÓCIE]\nOpis.',
    });
    expect(parseBrutalAssaultBulkDescriptionJson(JSON.stringify({
      195: 'Zdanie. '.repeat(11),
    }))['195']).toContain('Zdanie.');
    expect(() => parseBrutalAssaultBulkDescriptionJson('{broken')).toThrow('poprawny JSON');
  });

  it('builds varied RYM prompts and rejects template-like descriptions', () => {
    const row = album(1, 'Azarath', 'Diabolic Impious Evil', { sourceRank: 1, year: 2006 });
    const single = buildRymPolishBlackMetalAlbumPrompt(row);
    const bulk = buildRymPolishBlackMetalBulkDescriptionPrompt([row]);

    expect(single).toContain('pozycja #1');
    expect(single).toContain('NIE używaj nigdzie formuł');
    expect(bulk).toContain('Żadne dwa opisy nie mogą zaczynać się tymi samymi trzema słowami');
    expect(bulk).toContain('1|1|Azarath|Diabolic Impious Evil|2006');
    expect(() => validateRymDescriptionBatch({
      1: '[W SKRÓCIE]\nWarto posłuchać dla świetnych riffów.',
    })).toThrow('zakazaną szablonową formułę');
    expect(() => validateRymDescriptionBatch({
      1: '[W SKRÓCIE]\nSurowe gitarowe tremola prowadzą album.',
      2: '[W SKRÓCIE]\nSurowe gitarowe tremola otwierają materiał.',
    })).toThrow('zaczynają się tak samo');
  });

  it('formats legacy paragraphs and structured descriptions without unsafe HTML', () => {
    const legacy = document.createElement('div');
    renderBrutalAssaultAlbumDescription(
      legacy,
      'Pierwsze zdanie. Drugie zdanie. Trzecia ciekawostka. Czwarta ciekawostka.'
    );
    expect(legacy.querySelector('.ba2027-description-lead')?.textContent).toContain('Pierwsze zdanie');
    expect(legacy.querySelectorAll('li')).toHaveLength(2);

    const formatted = document.createElement('div');
    renderBrutalAssaultAlbumDescription(
      formatted,
      '## Ciekawostki\n- **Produkcja:** Brzmienie jest surowe.\n- <img src=x onerror=alert(1)>'
    );
    expect(formatted.querySelector('h5')?.textContent).toBe('Ciekawostki');
    expect(formatted.querySelector('strong')?.textContent).toBe('Produkcja:');
    expect(formatted.querySelector('img')).toBeNull();
    expect(albumDescriptionTeaser('## W skrócie\nPierwsze zdanie. Drugie.')).toBe('Pierwsze zdanie. Drugie.');
    expect(albumDescriptionTeaser('To jest pierwsze zdanie, które pozostaje widoczne w całości bez sztucznego skracania. Drugie zdanie.')).toBe(
      'To jest pierwsze zdanie, które pozostaje widoczne w całości bez sztucznego skracania. Drugie zdanie.'
    );
  });

  it('recognizes plain AI headings and bolds labels before colons', () => {
    const container = document.createElement('div');
    const value = [
      'W skrócie',
      '',
      'Pierwsze zdanie wprowadzenia.',
      'Drugie zdanie wprowadzenia.',
      '',
      'Ciekawostki',
      'Bez prób: zespół nie odbywał klasycznych prób.',
      'Nowy etap: album rozszerzył wcześniejsze brzmienie.',
      '',
      'Na co zwrócić uwagę',
      'Brzmienie: noise przejmuje konstrukcję utworów.',
    ].join('\n');

    renderBrutalAssaultAlbumDescription(container, value);

    expect([...container.querySelectorAll('h5')].map((node) => node.textContent)).toEqual([
      'W skrócie', 'Ciekawostki', 'Na co zwrócić uwagę',
    ]);
    expect(container.querySelector('.ba2027-description-lead')?.textContent).toBe(
      'Pierwsze zdanie wprowadzenia. Drugie zdanie wprowadzenia.'
    );
    expect([...container.querySelectorAll('li strong')].map((node) => node.textContent)).toEqual([
      'Bez prób:', 'Nowy etap:', 'Brzmienie:',
    ]);
    expect(albumDescriptionTeaser(value)).toBe('Pierwsze zdanie wprowadzenia. Drugie zdanie wprowadzenia.');
  });

  it('starts with the best RYM album from every completely unheard artist', () => {
    const rows = [
      album(1, 'Artist A', 'Lower', { rymRating: 3.5 }),
      album(2, 'Artist A', 'Best', { rymRating: 4.8 }),
      album(3, 'Artist B', 'Only', { rymRating: 4.2 }),
      album(4, 'Artist C', 'Heard', { listened: true, rating: 4 }),
      album(5, 'Artist C', 'Top rated', { rymRating: 5 }),
    ];

    const queue = buildBrutalAssaultRecommendationQueue(rows);

    expect(queue.map((row) => row.album)).toEqual(['Best', 'Only', 'Top rated', 'Lower']);
  });

  it('takes only one album per unheard artist before the remaining queue', () => {
    const rows = [
      album(1, 'Artist A', 'A1', { rymRating: 5 }),
      album(2, 'Artist A', 'A2', { rymRating: 4.9 }),
      album(3, 'Artist A', 'A3', { rymRating: 4.8 }),
      album(4, 'Artist B', 'B1', { rymRating: 4.5 }),
      album(5, 'Artist B', 'B2', { rymRating: 3.5 }),
    ];

    expect(buildBrutalAssaultRecommendationQueue(rows).map((row) => row.album)).toEqual([
      'A1', 'B1', 'A2', 'A3', 'B2',
    ]);
  });

  it('orders the remaining albums by the dynamic mixed artist ranking', () => {
    const rows = [
      album(1, 'Artist A', 'A best', { rymRating: 4.8 }),
      album(2, 'Artist A', 'A next', { rymRating: 4 }),
      album(3, 'Artist B', 'B best', { rymRating: 4.9 }),
      album(4, 'Artist B', 'B next', { rymRating: 3.5 }),
      album(5, 'Artist C', 'C heard', { listened: true, rymRating: 4, rating: 5 }),
      album(6, 'Artist C', 'C next', { rymRating: 4.7 }),
    ];

    const afterArtistB = rows.map((row) => (
      row.rowId === 3 ? { ...row, listened: true, rating: 2 } : row
    ));
    expect(buildBrutalAssaultRecommendationQueue(afterArtistB)[0].album).toBe('A best');

    const afterBothNewArtists = afterArtistB.map((row) => (
      row.rowId === 1 ? { ...row, listened: true, rating: 5 } : row
    ));
    expect(buildBrutalAssaultRecommendationQueue(afterBothNewArtists).map((row) => row.album)).toEqual([
      'A next', 'C next', 'B next',
    ]);
  });

  it('does not recommend Shapes of Midnight before its release date', () => {
    const rows = [
      album(1, 'Uncle Acid & The Deadbeats', 'Shapes of Midnight', { rymRating: 5 }),
      album(2, 'Available Artist', 'Available album', { rymRating: 4 }),
    ];

    expect(buildBrutalAssaultRecommendationQueue(rows, '2026-09-17').map((row) => row.album)).toEqual([
      'Available album',
    ]);
    expect(buildBrutalAssaultRecommendationQueue(rows, '2026-09-18').map((row) => row.album)).toEqual([
      'Shapes of Midnight', 'Available album',
    ]);
  });

  it('puts albums without a RYM rating last and does not substitute MusicBrainz ratings', () => {
    const rows = [
      album(1, 'Artist A', 'No RYM', { communityRating: 5 }),
      album(2, 'Artist B', 'Rated', { rymRating: 1, communityRating: 1 }),
    ];

    expect(buildBrutalAssaultRecommendationQueue(rows)[0].album).toBe('Rated');
  });

  it('uses the manual RYM rating instead of MusicBrainz in labels and ordering', () => {
    const rows = [
      album(1, 'Artist A', 'High MusicBrainz', {
        rymRating: 2.15,
        communityRating: 5,
        communityVotes: 100,
      }),
      album(2, 'Artist A', 'Higher RYM', {
        rymRating: 4.37,
        communityRating: 3,
        communityVotes: 1,
      }),
    ];

    expect(buildBrutalAssaultRecommendationQueue(rows)[0].album).toBe('Higher RYM');
    expect(communityRatingLabel(rows[0])).toBe('Rate Your Music 2.15/5');
    expect(communityRatingLabel(rows[0])).not.toContain('MusicBrainz');
  });

  it('builds RYM, personal and mixed album rankings', () => {
    const rows = [
      album(1, 'Artist A', 'One', { rymRating: 4.8, rating: 3 }),
      album(2, 'Artist B', 'Two', { rymRating: 3.5, rating: 5 }),
      album(3, 'Artist C', 'RYM only', { rymRating: 4.9 }),
    ];

    expect(brutalAssaultMixedRating(rows[0])).toBe(3.9);
    expect(sortBrutalAssaultAlbumsByRating(rows, 'rym').map((row) => row.album)).toEqual([
      'RYM only', 'One', 'Two',
    ]);
    expect(sortBrutalAssaultAlbumsByRating(rows, 'own').map((row) => row.album)).toEqual([
      'Two', 'One',
    ]);
    expect(sortBrutalAssaultAlbumsByRating(rows, 'mixed').map((row) => row.album)).toEqual([
      'Two', 'One',
    ]);
  });

  it('ranks artist averages for RYM, personal and mixed scores', () => {
    const rows = [
      album(1, 'Artist A', 'A1', { rymRating: 4, rating: 5 }),
      album(2, 'Artist A', 'A2', { rymRating: 5, rating: 3 }),
      album(3, 'Artist B', 'B1', { rymRating: 4.7, rating: 4.8 }),
    ];
    const rankings = buildBrutalAssaultArtistRatingRankings(rows);

    expect(rankings.rym.map((item) => item.artist)).toEqual(['Artist B', 'Artist A']);
    expect(rankings.own.map((item) => item.artist)).toEqual(['Artist B', 'Artist A']);
    expect(rankings.mixed.map((item) => item.artist)).toEqual(['Artist B', 'Artist A']);
    expect(rankings.mixed[1].mixedAverage).toBe(4.25);
  });

  it('detects whether an artist has already been heard', () => {
    const rows = [album(1, 'Mgła', 'One', { listened: true }), album(2, 'Mgla', 'Two')];
    expect(isUnheardArtist(rows[1], rows)).toBe(false);
  });

  it('calculates the daily pace and remaining listening time to 4 August 2027', () => {
    const rows = [
      album(1, 'Artist A', 'Pending one', { minutes: 60 }),
      album(2, 'Artist B', 'Pending two', { minutes: 30 }),
      album(3, 'Artist C', 'Already heard', { minutes: 45, listened: true }),
      album(4, 'Artist D', 'No duration'),
    ];

    const result = computeBrutalAssaultDeadlineStats(rows, '2027-08-01');

    expect(result.daysLeft).toBe(3);
    expect(result.albumCount).toBe(3);
    expect(result.remainingMinutes).toBe(90);
    expect(result.missingMinutes).toBe(1);
    expect(result.albumsPerDay).toBe(1);
    expect(result.minutesPerDay).toBe(30);
  });

  it('does not repeat the remaining album count inside the deadline panel', () => {
    const container = document.createElement('div');
    renderBrutalAssaultDeadlineSummary(container, {
      daysLeft: 357,
      albumCount: 205,
      albumsPerDay: 0.57,
      minutesPerDay: 26,
      missingMinutes: 0,
    });

    expect(container.textContent).not.toContain('205');
    expect(container.textContent).not.toContain('albumów zostało');
    expect(container.querySelectorAll('.ba2027-deadline-metric')).toHaveLength(2);
  });
});
