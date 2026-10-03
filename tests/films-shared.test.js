import { describe, expect, it } from 'vitest';
import {
  OSCARS_RESULTS_WINDOW_END,
  OSCARS_RESULTS_WINDOW_START,
  buildFilmsSpotlight,
  getOscarsSeasonState,
  summarizeFilms,
} from '../js/films-shared.js';

const sample = [
  {
    title: 'Sinners',
    watched: true,
    rating_1_10: 9,
    nominations_number: 16,
    nominated_categories: 'Best Picture; Directing',
    won_categories: 'Best Picture; Directing; Sound',
  },
  {
    title: 'Sentimental Value',
    watched: false,
    rating_1_10: null,
    nominations_number: 9,
    nominated_categories: 'Best Picture; Actress in a Leading Role',
    won_categories: null,
  },
  {
    title: 'Hamnet',
    watched: true,
    rating_1_10: 8,
    nominations_number: 10,
    nominated_categories: 'Best Picture',
    won_categories: 'Costume Design',
  },
];

describe('films season state', () => {
  it('switches to results window on 15-17 March 2026', () => {
    expect(getOscarsSeasonState(new Date(`${OSCARS_RESULTS_WINDOW_START}T12:00:00`))).toBe('results');
    expect(getOscarsSeasonState(new Date(`${OSCARS_RESULTS_WINDOW_END}T12:00:00`))).toBe('results');
    expect(getOscarsSeasonState(new Date('2026-03-14T12:00:00'))).toBe('watchlist');
    expect(getOscarsSeasonState(new Date('2026-03-18T12:00:00'))).toBe('archive');
  });
});

describe('films summary', () => {
  it('counts watched, rated and winners from oscars data', () => {
    const summary = summarizeFilms(sample);

    expect(summary.total).toBe(3);
    expect(summary.watched).toBe(2);
    expect(summary.rated).toBe(2);
    expect(summary.avgRating).toBe(8.5);
    expect(summary.winnersCount).toBe(2);
    expect(summary.topWinner?.title).toBe('Sinners');
    expect(summary.nextUnwatched?.title).toBe('Sentimental Value');
  });
});

describe('films spotlight', () => {
  it('shows winners during the results window when winners are present', () => {
    const spotlight = buildFilmsSpotlight(sample, new Date('2026-03-16T12:00:00'));

    expect(spotlight.state).toBe('results');
    expect(spotlight.label).toContain('wyniki');
    expect(spotlight.title).toBe('Sinners');
    expect(spotlight.highlights).toHaveLength(2);
  });

  it('shows the watchlist state before the gala', () => {
    const spotlight = buildFilmsSpotlight(sample, new Date('2026-03-14T12:00:00'));

    expect(spotlight.state).toBe('watchlist');
    expect(spotlight.label).toContain('watchlist');
    expect(spotlight.title).toBe('Sentimental Value');
  });
});
