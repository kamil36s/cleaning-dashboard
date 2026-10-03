import { describe, expect, it } from 'vitest';
import { duration, renderPhoneActivity } from '../js/widget-phone-activity.js';

describe('Phone Activity widget', () => {
  it('renders computed time and escapes phone app names', () => {
    const root = document.createElement('div');
    renderPhoneActivity(root, {
      screen_time_seconds: 3900, unlocks: 4, notifications: 2, phone_sessions: 3,
      hourly_usage_seconds: Array(24).fill(0),
      apps: [{ app_name: '<img src=x onerror=alert(1)>', seconds: 1800 }],
    }, { last_sync: null });
    expect(duration(3900)).toBe('1h 05m');
    expect(root.textContent).toContain('1h 05m');
    expect(root.querySelector('img')).toBeNull();
    expect(root.textContent).toContain('<img');
    expect(root.textContent).toContain('Offline');
  });

  it('hides launcher from the list while keeping the total screen time', () => {
    const root = document.createElement('div');
    renderPhoneActivity(root, {
      screen_time_seconds: 4200, unlocks: 4, notifications: 2, phone_sessions: 3,
      hourly_usage_seconds: Array(24).fill(0),
      apps: [
        { package_name:'com.miui.home', app_name:'System launcher', seconds:1800 },
        { package_name:'com.instagram.android', app_name:'com.instagram.android', seconds:2400 },
      ],
    }, { last_sync:null });
    expect(root.textContent).toContain('1h 10m');
    expect(root.textContent).toContain('Instagram');
    expect(root.textContent).not.toContain('System launcher');
  });

  it('shows remaining Instagram access and warns when protection is off', () => {
    const root = document.createElement('div');
    renderPhoneActivity(root, {
      screen_time_seconds: 600, unlocks: 1, notifications: 0, phone_sessions: 1,
      hourly_usage_seconds: Array(24).fill(0), apps: [],
    }, { last_sync:null, devices:[{ is_sample:false, last_blocker_enabled:0 }] }, null, {
      policies:[{ target:'com.instagram.android', state:{ baseline_minutes:50, unlocked_minutes:25,
        used_minutes:17, remaining_minutes:8, sources:{
          reading:{ current_value:30, target_value:40, progress:.75 },
          cleaning:{ current_value:3, target_value:6, progress:.5 },
        } } }],
    });
    expect(root.querySelector('.pa-budget strong').textContent).toContain('8 min left');
    expect(root.textContent).toContain('25 / 50 min unlocked');
    expect(root.textContent).toContain('Protection off on phone');
  });
});
