import { beforeEach, describe, expect, it } from 'vitest';
import { deliverOfficialNotifications } from '../js/widget-brutal-assault-2027.js';
import { listDashboardNotifications } from '../js/dashboard-notifications-store.js';

describe('Brutal Assault official notifications', () => {
  beforeEach(() => localStorage.clear());

  it('delivers each new lineup and news event once with a widget target', () => {
    const events = [
      {
        id: 'ba-lineup:1', type: 'lineup_change', detectedAt: '2026-09-28T00:00:00Z',
        addedBands: [{ name: 'Band C', slug: 'c' }],
      },
      {
        id: 'ba-news:806', type: 'news', detectedAt: '2026-09-28T00:00:00Z',
        title: 'New announcement', url: 'https://brutalassault.cz/en/a/806/new-announcement',
      },
    ];
    deliverOfficialNotifications(events);
    deliverOfficialNotifications(events);
    const notifications = listDashboardNotifications();
    expect(notifications).toHaveLength(2);
    expect(notifications.every((item) => item.targetId === 'ba2027-card')).toBe(true);
    expect(notifications.find((item) => item.id === 'ba-lineup:1').message).toBe('Band C');
  });
});
