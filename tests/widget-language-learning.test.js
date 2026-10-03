import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  initLanguageLearningWidget,
  renderLanguageWidget,
  selectLanguageWidgetProfile,
} from '../js/widget-language-learning.js';
import { ankiAchievement } from '../js/language/anki-daily.js';
import { getDefaultDashboardWidgetConfig, getOrderedDashboardWidgets } from '../js/dashboard-settings.js';
import { filterVisibleWidgetKeys } from '../js/dashboard-widget-visibility.js';

describe('Language dashboard widget', () => {
  afterEach(() => document.body.replaceChildren());

  it('selects canonical Bokmal before other active profiles', () => {
    const other = { id: 'other', languageCode: 'nn', locale: 'nn-NO', status: 'ACTIVE' };
    const bokmal = { id: 'bokmal', languageCode: 'nb', locale: 'nb-NO', status: 'ACTIVE' };
    expect(selectLanguageWidgetProfile([other, bokmal])).toBe(bokmal);
    expect(selectLanguageWidgetProfile([])).toBeNull();
  });

  it('renders compact real metrics safely without interpreting server text as markup', () => {
    const root = document.createElement('div');
    renderLanguageWidget(root, {
      streakDays: 3,
      known: 12,
      mastered: 4,
      activeMinutes7d: 25,
      level: { level: 3, lifetimeXp: 175, currentLevelXpFloor: 150, nextLevelXp: 300, xpIntoLevel: 25, xpNeeded: 125 },
      dailyQuest: { title: 'Answer Cloze', current: 4, target: 10, href: '#cloze' },
      campaignMilestone: { type: 'READER_TEXTS_COMPLETED', current: 2, target: 5 },
      weeklyGoal: { current: 2, target: 5, percentage: 40 },
      nextAction: { title: '<img src=x onerror=alert(1)>', href: '#reader' },
    });
    expect(root.textContent).toContain('3d');
    expect(root.textContent).toContain('12');
    expect(root.textContent).toContain('40%');
    expect(root.textContent).toContain('125 to next');
    expect(root.textContent).toContain('Answer Cloze · 4/10');
    expect(root.textContent).toContain('Campaign · 2/5 reader texts completed');
    expect(root.querySelector('img')).toBeNull();
    const nextAction = [...root.querySelectorAll('a')].find((item) => item.textContent.includes('<img'));
    expect(nextAction?.getAttribute('href')).toBe('./language.html#reader');
  });

  it('loads only the selected profile summary when initialized', async () => {
    const root = document.createElement('div');
    const api = {
      profiles: vi.fn(async () => ({ items: [{ id: 'p', languageCode: 'nb', locale: 'nb-NO' }] })),
      widgetSummary: vi.fn(async () => ({ streakDays: 1, known: 2, mastered: 0, activeMinutes7d: 3 })),
    };
    await initLanguageLearningWidget({ api, root });
    expect(api.widgetSummary).toHaveBeenCalledWith('p');
    expect(root.getAttribute('aria-busy')).toBe('false');
    expect(root.textContent).toContain('Open Language Progress');
  });

  it('shows the selected Anki deck with both Cloze daily goals', () => {
    const root = document.createElement('div');
    renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1', anki: {
        configured: true,
        deck: { name: 'Norwegian A1 Words & Sentences [3.1k]', new: 0, due: 2, answeredCardsToday: 12 },
      },
      cloze: {}, reader: {},
    });
    expect(root.querySelector('.language-learning-widget-deck-name').textContent).toBe('Norwegian A1 Words & Sentences [3.1k]');
    expect(root.querySelector('.language-learning-widget-deck-details').textContent).toContain('Reviews 2');
    expect(root.querySelectorAll('.language-learning-widget-core-row')).toHaveLength(2);
    expect(root.textContent).toContain('Cloze · todayReviews 0/5 · New 0/3');
  });

  it('shows every deck returned by Anki, including a newly added deck', () => {
    const root = document.createElement('div');
    renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1',
      anki: { configured: true, decks: [
        { name: 'Default', new: 0, due: 0, reviewsCompletedToday: 0,
          reviewsPlannedToday: 0, newCompletedToday: 0, newPlannedToday: 0 },
        { name: 'Norwegian A1', new: 1, due: 2, answeredCardsToday: 3,
          reviewsCompletedToday: 2, reviewsPlannedToday: 4, newCompletedToday: 1, newPlannedToday: 2 },
        { name: 'Reader Stories::01 Words', new: 4, due: 5, answeredCardsToday: 6,
          reviewsCompletedToday: 4, reviewsPlannedToday: 9, newCompletedToday: 2, newPlannedToday: 6 },
      ] },
      cloze: { reviewedToday: 2, newSentencesToday: 1 }, reader: {},
    });
    expect([...root.querySelectorAll('.language-learning-widget-deck-name')].map((item) => item.textContent))
      .toEqual(['Norwegian A1', '01 Words']);
    expect(root.querySelectorAll('.language-learning-widget-deck-name')[1].title).toBe('Reader Stories::01 Words');
    expect([...root.querySelectorAll('progress')].map((bar) => [bar.value, bar.max])).toEqual([[9, 21]]);
    expect(root.querySelectorAll('.language-learning-widget-deck progress')).toHaveLength(0);
    expect(root.textContent).toContain('Anki today9/21 cards');
    expect(root.textContent).toContain('43%');
    expect(root.textContent).not.toContain('Default');
    expect(root.querySelector('.language-learning-widget-anki').classList.contains('is-goal-complete')).toBe(false);
    expect(root.textContent).toContain('Cloze · todayReviews 2/5 · New 1/3');
    expect(root.textContent).not.toContain('Unknown');
  });

  it('counts parent decks once in the single Anki daily bar', () => {
    const root = document.createElement('div');
    renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1', anki: { decks: [
        { name: 'Reader Stories', due: 1, new: 2, reviewsCompletedToday: 3,
          reviewsPlannedToday: 4, newCompletedToday: 2, newPlannedToday: 4 },
        { name: 'Reader Stories::Story', due: 1, new: 20, reviewsCompletedToday: 3,
          reviewsPlannedToday: 4, newCompletedToday: 2, newPlannedToday: 22 },
      ] }, cloze: {}, reader: {},
    });
    const bar = root.querySelector('.language-learning-widget-anki-today progress');
    expect([bar.value, bar.max]).toEqual([5, 8]);
    expect(root.querySelectorAll('.language-learning-widget-deck')).toHaveLength(1);
    expect(root.textContent).not.toContain('Reader Stories::Story');
  });

  it('shows seven Anki activity days and keeps yesterday’s streak before today has answers', () => {
    const root = document.createElement('div');
    const week = [0, 0, 1, 2, 4, 3, 0].map((answers, index) => ({
      date: `2026-10-${String(2 + index).padStart(2, '0')}`, answers,
      complete: index === 2 ? null : index >= 3 && index <= 5,
      planned: index === 2 ? null : 2,
    }));
    renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1',
      anki: { decks: [{ name: 'Norwegian', due: 1, new: 0 }], week },
      cloze: {}, reader: {},
    });
    expect(root.querySelectorAll('.language-learning-widget-anki-week-day')).toHaveLength(7);
    expect(root.querySelectorAll('.language-learning-widget-anki-week-day.has-answers')).toHaveLength(4);
    expect(root.querySelectorAll('.language-learning-widget-anki-week-day.is-complete')).toHaveLength(3);
    expect(root.querySelectorAll('.language-learning-widget-anki-week-day.is-unknown')).toHaveLength(1);
    expect(root.querySelector('.language-learning-widget-anki-rhythm-head strong').textContent).toBe('4 day streak');
    expect(root.querySelector('.language-learning-widget-anki-week-day.is-today').getAttribute('aria-label'))
      .toContain('0 Anki answers');
  });

  it('shows user-confirmed September days in gold and later days by actual completion', () => {
    const root = document.createElement('div');
    const dates = ['2026-09-25', '2026-09-26', '2026-09-27', '2026-09-28',
      '2026-09-29', '2026-09-30', '2026-10-01'];
    renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1',
      anki: { decks: [{ name: 'Norwegian', due: 1, new: 0 }],
        week: dates.map((date, index) => ({ date, answers: 10, planned: 10,
          complete: index === 6 })) },
      cloze: {}, reader: {},
    });
    const days = [...root.querySelectorAll('.language-learning-widget-anki-week-day')];
    expect(days.slice(0, 5).every((item) => item.classList.contains('is-complete'))).toBe(true);
    expect(days[5].classList.contains('is-complete')).toBe(false);
    expect(days[5].classList.contains('has-answers')).toBe(true);
    expect(days[6].classList.contains('is-complete')).toBe(true);
  });

  it('turns Cloze gold after both daily goals are met', () => {
    const root = document.createElement('div');
    const render = (cloze) => renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1', anki: {}, cloze, reader: {},
    });
    render({ reviewedToday: 5, newSentencesToday: 2, dailyReviewGoal: 5, dailyNewSentenceGoal: 3 });
    expect(root.querySelector('.language-learning-widget-cloze-row').classList.contains('is-goal-complete')).toBe(false);
    render({ reviewedToday: 5, newSentencesToday: 3, dailyReviewGoal: 5, dailyNewSentenceGoal: 3 });
    expect(root.querySelector('.language-learning-widget-cloze-row').classList.contains('is-goal-complete')).toBe(true);
    render({ reviewedToday: 10, newSentencesToday: 35, dailyReviewGoal: 5, dailyNewSentenceGoal: 3 });
    expect(root.querySelector('.language-learning-widget-cloze-row').classList.contains('is-goal-complete')).toBe(true);
  });

  it('keeps the original plan when reporting extra Anki cards in the achievement', () => {
    const achievement = ankiAchievement([
      { name: 'Reader Stories', reviewsCompletedToday: 8, reviewsPlannedToday: 5,
        newCompletedToday: 1, newPlannedToday: 1 },
      { name: 'Reader Stories::Story', reviewsCompletedToday: 8, reviewsPlannedToday: 5,
        newCompletedToday: 1, newPlannedToday: 1 },
    ]);
    expect(achievement).toMatchObject({ state: 'complete', value: '150%', progress: 150 });
    expect(achievement.detail).toContain('9/6 cards');
    expect(achievement.detail).toContain('3 extra');
  });

  it('turns the entire Anki block gold only when a nonempty daily plan is complete', () => {
    const root = document.createElement('div');
    const deck = { name: 'Norwegian', due: 0, new: 0, reviewsCompletedToday: 5,
      reviewsPlannedToday: 5, newCompletedToday: 2, newPlannedToday: 2 };
    const render = (item) => renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1', anki: { decks: [item] }, cloze: {}, reader: {},
    });
    render(deck);
    expect(root.querySelector('.language-learning-widget-anki').classList.contains('is-goal-complete')).toBe(true);
    expect(root.querySelector('.language-learning-widget-anki-today').textContent).toContain('7/7 cards · 100%');
    render({ ...deck, reviewsCompletedToday: 8 });
    expect(root.querySelector('.language-learning-widget-anki-today').textContent).toContain('10/7 cards · 143% · +3 extra');
    expect(root.querySelector('.language-learning-widget-anki').classList.contains('is-goal-complete')).toBe(true);
    render({ ...deck, reviewsCompletedToday: 0, reviewsPlannedToday: 0,
      newCompletedToday: 0, newPlannedToday: 0 });
    expect(root.querySelector('.language-learning-widget-anki').classList.contains('is-goal-complete')).toBe(false);
    expect(root.querySelector('.language-learning-widget-anki-today').textContent).toContain('0/0 cards · 0%');
  });

  it('shows progress for the current Reader text and explains disconnected Anki', () => {
    const root = document.createElement('div');
    renderLanguageWidget(root, {
      policyVersion: 'language.today-summary/v1',
      anki: { configured: true, status: 'UNAVAILABLE', config: { endpoint: 'http://127.0.0.1:8767' } },
      cloze: {}, reader: { continue: { id: 'text', title: 'Kort tekst', textLength: 100, progressSourceOffset: 43, sentenceCount: 10, sentencesRead: 4 } },
    });
    expect(root.textContent).toContain('AnkiConnect is not listening at http://127.0.0.1:8767');
    expect(root.textContent).toContain('Open Anki Desktop');
    expect(root.textContent).toContain('4/10 sentences · 43% read');
  });

  it('syncs AnkiWeb and refreshes the selected deck when the dashboard opens', async () => {
    const root = document.createElement('div');
    document.body.append(root);
    const interval = vi.spyOn(window, 'setInterval').mockReturnValue(1);
    const visibility = vi.spyOn(document, 'addEventListener');
    const deck = { name: 'Norwegian A1 Words & Sentences [3.1k]', new: 0, due: 2, answeredCardsToday: 12 };
    const api = {
      profiles: vi.fn(async () => ({ items: [{ id: 'p', languageCode: 'nb', locale: 'nb-NO' }] })),
      widgetSummary: vi.fn(async () => ({ policyVersion: 'language.today-summary/v1', anki: {}, cloze: {}, reader: {} })),
      ankiStatus: vi.fn(async () => ({ config: { autoSync: true }, deck })),
      syncAnkiWeb: vi.fn(async () => ({ status: { config: { autoSync: true }, deck: { ...deck, due: 0, answeredCardsToday: 13 } } })),
    };
    try {
      await initLanguageLearningWidget({ api, root });
      await vi.waitFor(() => expect(root.querySelector('.language-learning-widget-deck-details').textContent).toContain('Reviews 0'));
      expect(api.syncAnkiWeb).toHaveBeenCalledWith('p');
      expect(interval).toHaveBeenCalled();
    } finally {
      const listener = visibility.mock.calls.find(([name]) => name === 'visibilitychange')?.[1];
      if (listener) document.removeEventListener('visibilitychange', listener);
      vi.restoreAllMocks();
    }
  });

  it('lets the user request an AnkiWeb sync when automatic sync is off', async () => {
    const root = document.createElement('div');
    document.body.append(root);
    const deck = { name: 'Old deck', new: 0, due: 1, answeredCardsToday: 0 };
    const api = {
      profiles: vi.fn(async () => ({ items: [{ id: 'p', languageCode: 'nb', locale: 'nb-NO' }] })),
      widgetSummary: vi.fn(async () => ({ policyVersion: 'language.today-summary/v1', anki: {}, cloze: {}, reader: {} })),
      ankiStatus: vi.fn(async () => ({ config: { enabled: true, autoSync: false }, decks: [deck] })),
      syncAnkiWeb: vi.fn(async () => ({ status: { config: { enabled: true, autoSync: false }, decks: [deck, { ...deck, name: 'New deck' }] } })),
    };
    await initLanguageLearningWidget({ api, root });
    root.querySelector('button').click();
    await vi.waitFor(() => expect(root.textContent).toContain('New deck'));
    expect(api.syncAnkiWeb).toHaveBeenCalledWith('p', { force: true });
  });

  it('is visible in the default dashboard configuration', () => {
    const config = getDefaultDashboardWidgetConfig();
    expect(config.visible['language-learning']).toBe(true);
    expect(config.order['language-learning']).toBe(41);
    expect(getOrderedDashboardWidgets(config).find((item) => item.key === 'language-learning')).toMatchObject({
      visible: true,
      label: 'Language Learning',
    });
  });

  it('is excluded from lazy module loading while hidden', () => {
    const config = getDefaultDashboardWidgetConfig();
    config.visible['language-learning'] = false;
    const visible = filterVisibleWidgetKeys(['reading', 'language-learning', 'ai-usage'], config);
    expect(visible).toContain('reading');
    expect(visible).not.toContain('language-learning');
  });
});
