import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const summary = {
  screen_time_seconds: 2100, unlocks: 3, notifications: 2, phone_sessions: 1,
  average_phone_session_seconds: 2400, longest_phone_session_seconds: 2400,
  first_unlock: '2026-09-26T08:00:00Z', last_activity: '2026-09-26T08:40:00Z',
  apps: [{ package_name: 'app.one', app_name: 'App One', seconds: 2100, launches: 1,
    average_seconds: 2100, longest_seconds: 2100, icon_base64: null }],
  hourly_usage_seconds: Array(24).fill(0), daily_usage_seconds: [{ day: '2026-09-26', seconds: 2100 }],
  heatmap_weekday_hour_seconds: Array.from({ length: 7 }, () => Array(24).fill(0)),
  sessions: [{ start: '2026-09-26T08:00:00Z', end: '2026-09-26T08:40:00Z', seconds: 2400 }],
  locations: [], battery_samples: [],
  patterns: { doomscroll_threshold_minutes: 20, doomscroll_sessions: 1, rapid_switch_windows: 0, late_night_seconds: 0 },
  session_facts: { empty_unlocks: 0, short_phone_sessions_under_2m: 0, average_first_app_latency_seconds: 60 },
  battery_exposure: { observed_drop_percent: 0, estimated_exposure_percent_by_package: {}, quality: 'estimate' },
  notification_attribution: { window_seconds: 120, matched: 1, response_rate: .5, average_latency_seconds: 37 },
  notifications_by_app: [{ app_name: 'App One', count: 2 }], notification_hourly: Array(24).fill(0),
};

describe('Phone Activity page', () => {
  beforeEach(() => {
    vi.resetModules();
    const html = readFileSync('phone-activity.html', 'utf8');
    document.body.innerHTML = html.match(/<body>([\s\S]*)<\/body>/)[1]
      .replace(/<script[^>]*><\/script>/g, '');
    global.fetch = vi.fn(async (url) => {
      const path = String(url);
      let data = {};
      if (path.includes('/summary?')) data = summary;
      else if (path.includes('/events?')) data = { events: [] };
      else if (path.includes('/insights?')) data = { comparison: { metric: 'notifications', operator: '>=', threshold: 100,
        outcome: 'screen_time', selected_days: 0, other_days: 1, selected_mean: null, other_mean: 35,
        unit: 'minutes' }, streaks: [] };
      else if (path.endsWith('/status')) data = { last_sync: null, devices: [] };
      else if (path.endsWith('/retention')) data = { raw_notification_text_days: 30, usage_events_days: null };
      return { ok: true, json: async () => data };
    });
  });

  it('renders live metrics and an honest empty place state', async () => {
    await import('../js/phone-activity-page.js?test=render');
    await vi.waitFor(() => expect(document.querySelector('#pa-kpis').textContent).toContain('35m'));
    expect(document.querySelector('#pa-apps').textContent).toContain('App One');
    expect(document.querySelector('#pa-places').textContent).toContain('No usable location samples');
    expect(document.querySelector('#pa-notifications').textContent).toContain('50%');
    expect(document.querySelector('#pa-timeline-details').hasAttribute('open')).toBe(false);
    expect(document.querySelector('.pa-page').dataset.activeView).toBe('overview');
    expect(document.querySelector('#pa-apps .app-name').textContent).toContain('App One');
  });

  it('loads and saves the temporary unlock policy for a paired phone', async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn(async (url, options) => {
      const path = String(url);
      if (path.endsWith('/status')) return { ok: true, json: async () => ({ last_sync: null,
        devices: [{ device_id: 'phone-1', label: 'Redmi', is_sample: false, last_sync: null }] }) };
      if (path.includes('/override-policy')) return { ok: true, json: async () =>
        options?.method === 'POST' ? { mode: 'cooldown' } : { mode: 'always', duration_minutes: 5, cooldown_minutes: 0 } };
      return originalFetch(url, options);
    });
    await import('../js/phone-activity-page.js?test=override');
    await vi.waitFor(() => expect(document.querySelector('#pa-rule-device').value).toBe('phone-1'));
    document.querySelector('#pa-override-mode').value = 'cooldown';
    document.querySelector('#pa-override-duration').value = '7';
    document.querySelector('#pa-override-cooldown').value = '60';
    document.querySelector('#pa-override-save').click();
    await vi.waitFor(() => expect(global.fetch.mock.calls.some(([url, options]) =>
      String(url).endsWith('/override-policy') && options?.method === 'POST')).toBe(true));
    const [, options] = global.fetch.mock.calls.find(([url, request]) =>
      String(url).endsWith('/override-policy') && request?.method === 'POST');
    expect(JSON.parse(options.body)).toEqual({ device_id: 'phone-1', mode: 'cooldown',
      duration_minutes: 7, cooldown_minutes: 60 });
  });

  it('saves a dynamic access rule for a selected app', async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn(async (url, options) => {
      const path = String(url);
      if (path.endsWith('/status')) return { ok: true, json: async () => ({ last_sync: null,
        devices: [{ device_id: 'phone-1', label: 'Redmi', is_sample: false, last_sync: null,
          last_blocker_enabled: 1 }] }) };
      if (path.includes('/access?')) return { ok: true, json: async () => ({ policies: [] }) };
      if (path.endsWith('/access') && options?.method === 'POST') return { ok: true, json: async () => ({ ok:true }) };
      return originalFetch(url,options);
    });
    await import('../js/phone-activity-page.js?test=access');
    await vi.waitFor(() => expect(document.querySelector('#pa-rule-device').value).toBe('phone-1'));
    await vi.waitFor(() => expect(document.querySelector('#pa-access-target option[value="__custom__"]')).toBeTruthy());
    document.querySelector('#pa-access-target').value = '__custom__';
    document.querySelector('#pa-access-target').dispatchEvent(new Event('change'));
    document.querySelector('#pa-access-custom-target').value = 'com.reddit.frontpage';
    document.querySelector('#pa-access-manual').value = '45';
    document.querySelector('#pa-access-baseline-mode').value = 'manual';
    document.querySelector('#pa-access-reduction-rate').value = '12';
    document.querySelector('#pa-access-bonus-pages').value = '8';
    document.querySelector('#pa-access-bonus-minutes').value = '3';
    document.querySelector('#pa-access-save').click();
    await vi.waitFor(() => expect(global.fetch.mock.calls.some(([url, options]) =>
      String(url).endsWith('/access') && options?.method === 'POST')).toBe(true));
    const [, options] = global.fetch.mock.calls.find(([url, request]) =>
      String(url).endsWith('/access') && request?.method === 'POST');
    const saved = JSON.parse(options.body);
    expect(saved.device_id).toBe('phone-1');
    expect(saved.policy.target).toBe('com.reddit.frontpage');
    expect(saved.policy.baseline.manual_minutes).toBe(45);
    expect(saved.policy.formula).toBe('minimum');
    expect(saved.policy.reduction).toMatchObject({enabled:true,type:'compound_percentage',percentage_per_day:12,floor_minutes:15});
    expect(saved.policy.extra_reading).toMatchObject({enabled:true,pages_per_reward:8,minutes_per_reward:3,daily_bonus_cap:10});
    expect(saved.policy.notifications).toMatchObject({extra_reading_enabled:true,full_plan_enabled:true,reduction_enabled:false});
  });

  it('shows reduced base, separate reading bonus, total and compact forecast', async () => {
    const originalFetch = global.fetch;
    const policy = {
      target:'com.instagram.android',enabled:true,
      baseline:{mode:'automatic',window_days:7,calculation:'average',manual_minutes:50,hard_max_minutes:null},
      reduction:{enabled:true,start_source:'automatic',manual_start_minutes:50,type:'compound_percentage',
        percentage_per_day:10,fixed_minutes_per_day:5,floor_minutes:15},
      extra_reading:{enabled:true,pages_per_reward:10,minutes_per_reward:2,daily_bonus_cap:10,
        partial_rewards:false,allow_above_base:true,standalone_target_pages:null},
      sources:{reading:{enabled:true,weight:50,no_plan:'fulfilled'},cleaning:{enabled:true,weight:50,no_plan:'fulfilled'}},
      formula:'minimum',notifications:{enabled:true,minimum_increase:1,milestones_enabled:true,
        debounce_seconds:30,show_baseline:true,show_reading:true,show_cleaning:true,show_used:true,show_remaining:true},
      session:{max_minutes:15,cooldown_minutes:20},night:{enabled:false,from:'23:30',until:'09:00'},
      override:{enabled:true,duration_minutes:5,cooldown_minutes:60,max_per_day:1},
      state:{day:'2026-09-28',baseline_minutes:56,reference_baseline_minutes:118,historical_baseline_minutes:112,
        effective_base_cap_minutes:56,effective_base_cap_exact_minutes:56.44,
        normal_unlocked_minutes:42,extra_reading_pages:20,
        extra_reading_bonus_minutes:4,total_unlocked_minutes:46,unlocked_minutes:46,used_minutes:31,
        remaining_minutes:15,sources:{reading:{current_value:50,target_value:30,progress:1},
          cleaning:{current_value:3,target_value:4,progress:.75}},
        reduction_plan:{enabled:true,day:7,start_date:'2026-09-21',paused:false,estimated_floor_date:'2026-10-11',
          forecast:{today:56,tomorrow:51,plus_3_days:41,plus_7_days:27,floor:15}}},
    };
    global.fetch = vi.fn(async (url, options) => {
      const path = String(url);
      if (path.endsWith('/status')) return {ok:true,json:async () => ({devices:[{
        device_id:'phone-1',label:'Redmi',is_sample:false,last_blocker_enabled:1,last_config_version:2}]})};
      if (path.includes('/access?')) return {ok:true,json:async () => ({version:2,policies:[policy]})};
      if (path.includes('/access/history?')) return {ok:true,json:async () => ({days:[]})};
      return originalFetch(url,options);
    });
    await import('../js/phone-activity-page.js?test=reduction');
    await vi.waitFor(() => expect(document.querySelector('#pa-access-live').textContent).toContain('Available now 15 min'));
    expect(document.querySelector('#pa-access-live').textContent).toContain('Reading bonus');
    expect(document.querySelector('#pa-access-live').textContent).toContain('46 min');
    expect(document.querySelector('#pa-access-baseline-info').textContent).toContain('118 min');
    expect(document.querySelector('#pa-access-forecast').textContent).toContain('Tomorrow');
    expect(document.querySelector('#pa-access-live').textContent).not.toMatch(/\d+\.\d+ min/);
  });
});
