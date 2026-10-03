import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLanguageApi } from '../js/language/api.js';
import { renderProgress } from '../js/language/views/progress.js';
import { formatLanguageRoute, parseLanguageRoute, routeHeading } from '../js/language/router.js';

function progressData() {
  return {
    level: {
      label: 'Norwegian Level 2', level: 2, lifetimeXp: 75,
      currentLevelXpFloor: 50, nextLevelXp: 150, xpIntoLevel: 25, xpNeeded: 75, progressPercent: 25,
    },
    today: {
      localStudyDate: '2026-09-17', timezone: 'Europe/Warsaw', completedCount: 1,
      items: [
        { key: 'CLOZE_ATTEMPTS', title: 'Answer 10 Cloze questions', reason: 'Real evidence.', href: '#cloze', current: 4, target: 10, unit: 'answers', completed: false, progressPercent: 40 },
        { key: 'READER_ACTIVE_MINUTES', title: 'Read actively', reason: 'Canonical Reader.', href: '#reader', current: 10, target: 10, unit: 'minutes', completed: true, progressPercent: 100 },
      ],
    },
    streak: { currentDays: 2, bestDays: 7, studyDaysLast7: 3, studyDaysLast30: 9 },
    noPenaltyPolicy: 'Missing a day removes no earned progress.',
    achievements: {
      policyVersion: 'language.gamification-achievements/v1', completionLabel: '1 / 2 achievements',
      items: [
        { key: 'FIRST_STUDY', category: 'SPECIAL', name: '<img src=x onerror=alert(1)>', description: 'First real study.', current: 1, target: 1, progressPercent: 100, state: 'UNLOCKED', unlockedAt: '2026-09-17T10:00:00Z' },
        { key: 'CLOZE_100', category: 'CLOZE', name: '100 Cloze answers', description: 'Real answers.', current: 4, target: 100, progressPercent: 4, state: 'LOCKED', unlockedAt: null },
      ],
    },
    collections: {
      policyVersion: 'language.gamification-collections/v1',
      items: [{ collectionKey: 'FAST_TRACK_1', name: 'Fast Track 1', tier: 'BRONZE', status: 'AVAILABLE', completed: 25, totalEligible: 100, mapped: 100, unresolved: 20, excluded: 0, progressPercent: 25, denominatorSource: 'Playable KELLY targets', completionStateRule: '3 correct across 2 dates.' }],
    },
    campaigns: { ruleVersion: 'language.gamification-campaigns/v1', items: [] },
  };
}

describe('Language Phase 7.6 progress UI', () => {
  afterEach(() => document.body.replaceChildren());

  it('renders level, accessible progress, quests, collections, and truthful locked states safely', () => {
    const mount = document.createElement('main');
    renderProgress(mount, { loading: false, error: null, data: progressData() }, {});
    expect(mount.textContent).toContain('Norwegian Level 2');
    expect(mount.textContent).toContain('75 lifetime XP');
    expect(mount.textContent).toContain('Locked');
    expect(mount.textContent).toContain('mapped 100, unresolved 20, excluded 0');
    expect(mount.querySelectorAll('progress').length).toBeGreaterThan(2);
    expect([...mount.querySelectorAll('progress')].every((item) => item.getAttribute('aria-label'))).toBe(true);
    expect(mount.querySelector('img')).toBeNull();
  });

  it('renders an explicit error state', () => {
    const mount = document.createElement('main');
    renderProgress(mount, { loading: false, error: 'Offline', data: null }, {});
    expect(mount.textContent).toContain('Progress is unavailable');
    expect(mount.textContent).toContain('Offline');
  });

  it('creates a configurable Norway campaign from available milestone controls', async () => {
    const mount = document.createElement('main');
    const onCreateCampaign = vi.fn(async () => {});
    renderProgress(mount, { loading: false, error: null, data: progressData() }, { onCreateCampaign });
    const form = mount.querySelector('.language-campaign-form');
    form.querySelector('[name="name"]').value = 'Norway Autumn 2027';
    form.querySelector('[name="targetDate"]').value = '2027-10-01';
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve();
    expect(onCreateCampaign).toHaveBeenCalledTimes(1);
    expect(onCreateCampaign.mock.calls[0][0]).toMatchObject({
      name: 'Norway Autumn 2027', targetDate: '2027-10-01', enabled: true,
    });
    expect(onCreateCampaign.mock.calls[0][0].milestones.length).toBe(3);
  });

  it('supports the reload-safe Progress route', () => {
    expect(parseLanguageRoute('#progress')).toEqual({ name: 'progress', valid: true });
    expect(formatLanguageRoute('progress')).toBe('#progress');
    expect(routeHeading({ name: 'progress' })).toBe('Progress');
  });

  it('uses only thin server-owned gamification and campaign API routes', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, data: {} }) }));
    const api = createLanguageApi({ fetchImpl });
    await api.gamification('profile', { asOf: '2026-09-17T10:00:00Z' });
    await api.achievements('profile');
    await api.collections('profile');
    await api.quests('profile');
    await api.campaigns('profile');
    await api.createCampaign('profile', { name: 'Norway' });
    await api.updateCampaign('campaign', { enabled: false });
    expect(fetchImpl.mock.calls.map(([url, options]) => [url, options.method])).toEqual([
      ['/api/language/profiles/profile/gamification?asOf=2026-09-17T10%3A00%3A00Z', 'GET'],
      ['/api/language/profiles/profile/achievements', 'GET'],
      ['/api/language/profiles/profile/collections', 'GET'],
      ['/api/language/profiles/profile/quests', 'GET'],
      ['/api/language/profiles/profile/campaigns', 'GET'],
      ['/api/language/profiles/profile/campaigns', 'POST'],
      ['/api/language/campaigns/campaign', 'PATCH'],
    ]);
  });
});
