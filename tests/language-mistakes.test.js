import { beforeEach, describe, expect, it } from 'vitest';
import { renderOverview } from '../js/language/views/overview.js';
import { renderStatistics } from '../js/language/views/statistics.js';

function mistakeSummary() {
  return {
    historicalIncorrectCount: 7, activeClusterCount: 2, recoveredClusterCount: 1,
    newInLast7Days: 1, recoveredInLast7Days: 1,
    topProblems: [{
      category: 'TARGET_LEMMA_DIFFICULTY', state: 'ACTIVE', historicalFailureCount: 3,
      title: 'jobb needs practice', target: { lemma: 'jobb' },
    }],
  };
}

function statistics() {
  return {
    vocabulary: {
      totalTracked: 4, newlyAdvanced: 1, series: [],
      knowledgeCounts: { learning: 1, known: 2, mastered: 1 },
      classifierCounts: { passive: 1, active: 2, mastered: 1, underexposed: 1 },
    },
    exposures: { totalReaderOccurrences: 0, uniqueLemmas: 0, byDay: [], distribution: {}, highExposure: [] },
    reading: { activeSeconds: 0, textsStarted: 0, textsCompleted: 0, byDay: [], recent: [] },
    streak: { currentDays: 0, definition: 'Canonical Reader days.' },
    coverage: { history: [] }, topics: [], cloze: {}, mistakes: mistakeSummary(),
  };
}

describe('Language Phase 9.5 mistake UI', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="mount"></main>'; });

  it('keeps historical errors separate from active and recovered statistics', () => {
    renderStatistics(document.querySelector('#mount'), {
      loading: false, error: null, range: '30d', data: statistics(),
    }, { onRange() {} });
    const text = document.body.textContent;
    expect(text).toContain('Historical errors7');
    expect(text).toContain('Active clusters2');
    expect(text).toContain('Recovered / 7 days1');
    expect(text).toContain('jobbTARGET LEMMA DIFFICULTY / ACTIVE / 3 qualifying failures');
  });

  it('keeps Overview compact and links the user to Reviews', () => {
    renderOverview(document.querySelector('#mount'), { overview: { loading: false, error: null, data: {
      statistics: statistics(), goals: [], topics: [],
      todayPlan: { items: [], wordsToRecycle: { items: [] } },
      frequencyCoverage: { message: 'Not configured.' }, anki: { status: 'NOT_CONFIGURED' },
      gamification: null, mistakes: mistakeSummary(),
    } } });
    const card = [...document.querySelectorAll('.language-card')].find((item) => item.textContent.includes('Mistakes needing attention'));
    expect(card.textContent).toContain('2 established clusters currently need attention.');
    expect(card.textContent).toContain('jobb');
    expect(card.querySelector('a').getAttribute('href')).toBe('#reviews');
  });
});
