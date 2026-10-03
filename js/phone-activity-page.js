import { getPhoneEvents, getPhoneStatus, getPhoneSummary, getPhoneInsights, pairPhone, deletePhoneEvents, deleteAllPhoneData, generatePhoneSample, clearPhoneSample, getPhoneRules, savePhoneRule, deletePhoneRule, getPhoneOverridePolicy, savePhoneOverridePolicy, setPhoneCategory, namePhonePlace, getPhoneRetention, savePhoneRetention } from './phone-tracker-api.js';
import { duration } from './widget-phone-activity.js';
import { escapeHtml } from './utils.js';
import { friendlyAppName, hiddenApps, setAppHidden } from './phone-activity-display.js';
import { loadAccessPage } from './phone-access-page.js';

const $ = (id) => document.getElementById(id);
const time = (value) => value ? new Date(value).toLocaleString() : '—';
const settings = () => ({ source: $('pa-source').value, device_id: $('pa-device').value,
  range: $('pa-range').value, start: $('pa-start').value, end: $('pa-end').value,
  attribution_seconds: $('pa-attribution').value });

const views = {
  overview: ['pa-kpis','pa-daily','pa-heatmap','pa-hourly','pa-notifications','pa-places','pa-patterns'],
  apps: ['pa-apps'], sessions: ['pa-sessions','pa-timeline'], insights: ['pa-insights'],
  limits: ['pa-rule-device'], settings: ['pa-pair-result','pa-sample-day','pa-delete-range'],
};
for (const [view, ids] of Object.entries(views)) {
  for (const id of ids) $(id)?.closest('section')?.setAttribute('data-pa-view',view);
}
function selectView() {
  const view = location.hash.slice(1);
  const active = Object.hasOwn(views,view) ? view : 'overview';
  document.querySelector('.pa-page').dataset.activeView = active;
  document.querySelectorAll('.pa-nav a').forEach((link) => {
    const selected = link.hash === `#${active}`;
    link.classList.toggle('is-active',selected);
    if (selected) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');
  });
}
window.addEventListener('hashchange',selectView);
selectView();

const icon = (app) => app?.icon_base64
  ? `<img src="data:image/png;base64,${app.icon_base64}" alt="" loading="lazy">`
  : '<span class="app-icon-fallback" aria-hidden="true">●</span>';
const appLabel = (app) => friendlyAppName(app?.package_name,app?.app_name);
function render(summary, events, status) {
  const stale = !status.last_sync || Date.now() - new Date(status.last_sync).getTime() > 30 * 60_000;
  $('pa-sync-health').textContent = `${stale ? '○ Offline / stale' : '● Recently synced'} · ${time(status.last_sync)}`;
  const stats = [
    ['Screen time', duration(summary.screen_time_seconds)], ['Unlocks', summary.unlocks],
    ['Notifications', summary.notifications], ['Phone sessions', summary.phone_sessions],
    ['Average session', duration(summary.average_phone_session_seconds)],
    ['Longest session', duration(summary.longest_phone_session_seconds)],
    ['No-app unlocks', summary.session_facts.empty_unlocks],
    ['Unlock → first app', summary.session_facts.average_first_app_latency_seconds == null ? '—' : `${Math.round(summary.session_facts.average_first_app_latency_seconds)}s`],
    ['First unlock', time(summary.first_unlock)], ['Last activity', time(summary.last_activity)],
  ];
  $('pa-kpis').innerHTML = stats.map(([name, value]) => `<article><span>${escapeHtml(name)}</span><strong>${escapeHtml(String(value))}</strong></article>`).join('');
  const dailyMax = Math.max(1,...summary.daily_usage_seconds.map((day) => day.seconds));
  $('pa-daily').innerHTML = summary.daily_usage_seconds.length ? `<div class="daily-bars">${summary.daily_usage_seconds.map((day) => `<div title="${escapeHtml(day.day)} · ${escapeHtml(duration(day.seconds))}"><i style="height:${Math.max(3,day.seconds / dailyMax * 100)}%"></i><small>${escapeHtml(day.day.slice(5))}</small></div>`).join('')}</div>` : '<p class="empty">No completed app sessions.</p>';
  const heatMax = Math.max(1,...summary.heatmap_weekday_hour_seconds.flat());
  $('pa-heatmap').innerHTML = `<div class="heatmap-grid">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day,index) => `<span>${day}</span>${summary.heatmap_weekday_hour_seconds[index].map((seconds,hour) => `<i title="${day} ${hour}:00 · ${escapeHtml(duration(seconds))}" style="opacity:${Math.max(.12,seconds/heatMax)}"></i>`).join('')}`).join('')}</div>`;
  const total = Math.max(1, summary.screen_time_seconds);
  const sortKey = $('pa-app-sort').value;
  const hidden = new Set(hiddenApps());
  const sortedApps = [...summary.apps].filter((app) => !hidden.has(app.package_name)).sort((a,b) => (b[sortKey] || 0) - (a[sortKey] || 0));
  const appRows = sortedApps.slice(0,30).map((app) => {
    const gap = summary.session_facts.average_reopen_gap_seconds_by_package?.[app.package_name];
    return `<div class="app-line"><span class="app-name">${icon(app)}<strong>${escapeHtml(appLabel(app))}</strong></span><b>${escapeHtml(duration(app.seconds))}</b><span class="app-share">${Math.round(app.seconds / total * 100)}%</span><div class="bar"><i style="width:${Math.min(100,app.seconds / total * 100)}%"></i></div><div class="app-line-foot"><span>${app.launches} opens</span><details><summary>Details</summary><small>Average ${escapeHtml(duration(app.average_seconds))} · longest ${escapeHtml(duration(app.longest_seconds))}<br>First ${escapeHtml(time(app.first_use))} · last ${escapeHtml(time(app.last_use))}${gap == null ? '' : ` · return after ${escapeHtml(duration(gap))}`}</small></details><button type="button" data-hide-app="${escapeHtml(app.package_name)}">Hide</button></div></div>`;
  });
  $('pa-apps').innerHTML = appRows.length
    ? appRows.slice(0,10).join('') + (appRows.length > 10
      ? `<details class="pa-more-apps"><summary>Show ${appRows.length-10} more apps</summary>${appRows.slice(10).join('')}</details>` : '')
    : '<p class="empty">No app sessions in this period.</p>';
  $('pa-hidden-apps').innerHTML = [...hidden].map((pkg) => `<span>${escapeHtml(friendlyAppName(pkg))}<button type="button" data-show-app="${escapeHtml(pkg)}">Show</button></span>`).join('') || '<span>None</span>';
  const max = Math.max(1, ...summary.hourly_usage_seconds);
  $('pa-hourly').innerHTML = `<div class="hour-bars">${summary.hourly_usage_seconds.map((seconds, hour) => `<div title="${hour}:00 · ${escapeHtml(duration(seconds))}"><i style="height:${Math.max(3,seconds / max * 100)}%"></i><small>${hour % 3 === 0 ? hour : ''}</small></div>`).join('')}</div>`;
  const attribution = summary.notification_attribution;
  const maxNotifications = Math.max(1,...summary.notification_hourly);
  $('pa-notifications').innerHTML = `<div class="big-number">${summary.notifications}</div><p>Matched app opens: ${attribution.matched}</p><p>Response rate: ${attribution.response_rate == null ? '—' : `${Math.round(attribution.response_rate * 100)}%`}</p><p>Average response: ${attribution.average_latency_seconds == null ? '—' : `${Math.round(attribution.average_latency_seconds)}s`}</p><div class="hour-bars notification-bars">${summary.notification_hourly.map((count,hour) => `<div title="${hour}:00 · ${count} notifications"><i style="height:${Math.max(3,count/maxNotifications*100)}%"></i><small>${hour%3===0 ? hour : ''}</small></div>`).join('')}</div><div class="notification-apps">${summary.notifications_by_app.slice(0,8).map((app) => `<div><span>${escapeHtml(app.app_name)}</span><b>${app.count}</b></div>`).join('')}</div><p class="note">Temporal association within ${attribution.window_seconds}s; it does not prove the notification caused an open.</p>`;
  const sequences = summary.session_facts.sequences || [];
  const registry = new Map(summary.apps.map((app) => [app.package_name,app]));
  const sessionRows = summary.sessions.slice(-20).reverse().map((session) => {
    const sequence = sequences.find((item) => item.start === session.start);
    const packages = (sequence?.packages || []).filter((pkg,index,all) => pkg !== all[index-1]);
    const meaningful = packages.filter((pkg) => !hidden.has(pkg));
    const unique = [...new Set(meaningful)];
    const chips = unique.slice(0,4).map((pkg) => `<span class="session-app">${icon(registry.get(pkg))}${escapeHtml(friendlyAppName(pkg,registry.get(pkg)?.app_name))}</span>`).join('');
    return `<div class="session-line session-card"><div><strong>${escapeHtml(time(session.start))}</strong><div class="session-apps">${chips || '<span class="note">System activity</span>'}${unique.length > 4 ? `<span class="note">+${unique.length-4}</span>` : ''}</div>${unique.length > 4 ? `<details><summary>All ${unique.length} apps</summary><small>${escapeHtml(unique.map((pkg) => friendlyAppName(pkg,registry.get(pkg)?.app_name)).join(' → '))}</small></details>` : ''}</div><b>${escapeHtml(duration(session.seconds))}</b></div>`;
  });
  $('pa-sessions').innerHTML = sessionRows.length
    ? sessionRows.slice(0,8).join('') + (sessionRows.length > 8
      ? `<details class="pa-more-sessions"><summary>Show ${sessionRows.length-8} older sessions</summary>${sessionRows.slice(8).join('')}</details>` : '')
    : '<p class="empty">No completed phone sessions.</p>';
  $('pa-places').innerHTML = summary.locations.length ? summary.locations.map((place) => `<div class="session-line"><span><b>${escapeHtml(place.label)}</b><br><small>${place.points} fixes · last accuracy ±${Math.round(place.last_accuracy_m)}m</small></span><span>${escapeHtml(duration(place.dwell_seconds_lower_bound))} · ${escapeHtml(duration(place.screen_time_seconds_estimate))} screen</span><button type="button" data-place="${escapeHtml(place.cluster_key)}">Name</button></div>`).join('') : '<p class="empty">No usable location samples.</p>';
  const pattern = summary.patterns;
  const battery = summary.battery_exposure;
  const topBattery = Object.entries(battery.estimated_exposure_percent_by_package).sort((a,b) => b[1]-a[1]).slice(0,3);
  $('pa-patterns').innerHTML = `<p>Doomscroll sessions (≥${pattern.doomscroll_threshold_minutes} min): <b>${pattern.doomscroll_sessions}</b></p><p>Rapid switching windows: <b>${pattern.rapid_switch_windows}</b></p><p>Late-night usage (00:00–05:00): <b>${escapeHtml(duration(pattern.late_night_seconds))}</b></p><p>Short phone sessions: <b>${summary.session_facts.short_phone_sessions_under_2m}</b></p><p>Battery samples: <b>${summary.battery_samples.length}</b></p><p>Observed noncharging drop: <b>${battery.observed_drop_percent.toFixed(1)}%</b></p>${topBattery.map(([app,value]) => `<p>${escapeHtml(app)} · ${value.toFixed(2)}% exposure estimate</p>`).join('')}<p class="note">${escapeHtml(battery.quality)}</p>`;
  const selectedType = $('pa-type').value;
  const visible = selectedType ? events.filter((event) => event.event_type === selectedType) : events;
  $('pa-timeline').innerHTML = visible.length ? visible.slice(-300).reverse().map((event) => {
    const title = event.metadata?.title || '';
    const detail = event.event_type === 'notification_posted' ? title : event.app_name || event.package_name || '';
    return `<div class="timeline-row"><time>${escapeHtml(time(event.timestamp))}</time><span>${escapeHtml(event.event_type.replaceAll('_', ' '))}</span><b>${escapeHtml(detail)}</b></div>`;
  }).join('') : '<p class="empty">No events in this period.</p>';
  $('pa-devices').innerHTML = status.devices.map((device) => {
    const recent = device.last_sync && Date.now() - new Date(device.last_sync).getTime() < 30 * 60_000;
    return `<div class="device-line"><b>${escapeHtml(device.label)}</b><span>${escapeHtml(device.device_id)}</span><span>${recent ? 'Recently synced' : 'Offline / stale'} · IP ${escapeHtml(device.last_ip || 'unknown')} · last sync ${escapeHtml(time(device.last_sync))} · pending at last report ${device.last_reported_pending ?? '—'}</span></div>`;
  }).join('');
  const deviceFilter = $('pa-device');
  const oldDevice = deviceFilter.value;
  deviceFilter.innerHTML = '<option value="">All phones</option>' + status.devices.filter((device) => Boolean(device.is_sample) === (settings().source === 'sample')).map((device) => `<option value="${escapeHtml(device.device_id)}">${escapeHtml(device.label)}</option>`).join('');
  if (oldDevice && [...deviceFilter.options].some((option) => option.value === oldDevice)) deviceFilter.value = oldDevice;
  const selector = $('pa-rule-device');
  const selected = selector.value;
  selector.innerHTML = status.devices.filter((device) => !device.is_sample).map((device) => `<option value="${escapeHtml(device.device_id)}">${escapeHtml(device.label)}</option>`).join('');
  if (selected && status.devices.some((device) => device.device_id === selected)) selector.value = selected;
  window.phoneAccessDevices = status.devices;
  window.phoneAccessApps = summary.apps;
  loadAccessPage(status.devices,summary.apps);
  loadRules();
  loadOverridePolicy();
}

function renderInsights(insights) {
  const result = insights.comparison;
  const mean = (value) => value == null ? '—' : result.unit === 'minutes' ? `${Math.round(value)} min` : value.toFixed(1);
  $('pa-insights').innerHTML = `<p>${escapeHtml(result.metric)} ${escapeHtml(result.operator)} ${result.threshold}: <b>${result.selected_days}</b> covered days, average ${escapeHtml(result.outcome)} <b>${escapeHtml(mean(result.selected_mean))}</b></p><p>Other covered days: <b>${result.other_days}</b>, average <b>${escapeHtml(mean(result.other_mean))}</b></p><h3>Limit streaks</h3>${insights.streaks.length ? insights.streaks.map((item) => `<div class="session-line"><span>${escapeHtml(item.name)}</span><b>${item.days} complete days</b></div>`).join('') : '<p class="empty">Select one paired phone and add a limit to see streaks.</p>'}`;
}

async function loadRules() {
  const deviceId = $('pa-rule-device').value;
  if (!deviceId) { $('pa-rules').textContent = 'Pair a phone to add limits.'; return; }
  try {
    const data = await getPhoneRules(deviceId);
    if (deviceId !== $('pa-rule-device').value) return;
    const limits = data.rules;
    $('pa-rules').innerHTML = limits.length ? limits.map((rule) => `<div class="rule-line"><span><b>${escapeHtml(rule.name)}</b><br><small>${escapeHtml(friendlyAppName(rule.target))}</small></span><button type="button" data-delete-rule="${escapeHtml(rule.rule_id)}">Remove</button></div>`).join('') : '<p class="empty">No other limits configured.</p>';
  } catch (error) { $('pa-rules').textContent = error.message; }
}

function updateOverrideFields() {
  const mode = $('pa-override-mode').value;
  $('pa-override-pin-label').hidden = mode !== 'pin';
  $('pa-override-cooldown-label').hidden = mode !== 'cooldown';
}

async function loadOverridePolicy() {
  const deviceId = $('pa-rule-device').value;
  if (!deviceId) { $('pa-override-status').textContent = 'Pair a phone to configure temporary unlock.'; return; }
  try {
    const policy = await getPhoneOverridePolicy(deviceId);
    if (deviceId !== $('pa-rule-device').value) return;
    $('pa-override-mode').value = policy.mode;
    $('pa-override-duration').value = policy.duration_minutes;
    $('pa-override-cooldown').value = policy.cooldown_minutes;
    $('pa-override-pin').value = '';
    $('pa-override-status').textContent = policy.mode === 'pin' ? 'A new PIN is required when saving PIN mode.' : 'Changes reach the phone on its next sync.';
    updateOverrideFields();
  } catch (error) { $('pa-override-status').textContent = error.message; }
}

let cachedEvents = [];
let cachedSummary;
let cachedStatus;
async function refresh() {
  $('pa-error').hidden = true;
  try {
    const selection = settings();
    const [summary, data, status, insights] = await Promise.all([
      getPhoneSummary(selection), getPhoneEvents({ ...selection, limit: 5000 }), getPhoneStatus(),
      getPhoneInsights({ source:selection.source, device_id:selection.device_id,
        days:$('pa-insight-days').value,metric:$('pa-compare-metric').value.trim(),
        operator:'>=',threshold:$('pa-compare-threshold').value,
        outcome:$('pa-compare-outcome').value.trim() }),
    ]);
    cachedSummary = summary; cachedEvents = data.events; cachedStatus = status;
    render(summary, cachedEvents, status);
    renderInsights(insights);
  } catch (error) { $('pa-error').textContent = error.message; $('pa-error').hidden = false; }
}

$('pa-range').addEventListener('change', () => {
  const custom = $('pa-range').value === 'custom';
  $('pa-start').hidden = !custom; $('pa-end').hidden = !custom;
  if (!custom) refresh();
});
for (const id of ['pa-start','pa-end']) $(id).addEventListener('change', refresh);
$('pa-source').addEventListener('change', refresh);
$('pa-device').addEventListener('change', refresh);
$('pa-refresh').addEventListener('click', refresh);
$('pa-type').addEventListener('change', () => { if (cachedSummary) render(cachedSummary,cachedEvents,cachedStatus); });
$('pa-app-sort').addEventListener('change', () => { if (cachedSummary) render(cachedSummary,cachedEvents,cachedStatus); });
$('pa-attribution').addEventListener('change', refresh);
$('pa-compare-refresh').addEventListener('click', refresh);
$('pa-insight-days').addEventListener('change', refresh);
$('pa-rule-device').addEventListener('change', () => { loadAccessPage(window.phoneAccessDevices || [],window.phoneAccessApps || []); loadRules(); loadOverridePolicy(); });
$('pa-apps').addEventListener('click', (event) => {
  const pkg = event.target.closest('[data-hide-app]')?.dataset.hideApp;
  if (pkg) { setAppHidden(pkg,true); if (cachedSummary) render(cachedSummary,cachedEvents,cachedStatus); }
});
$('pa-hidden-apps').addEventListener('click', (event) => {
  const pkg = event.target.closest('[data-show-app]')?.dataset.showApp;
  if (pkg) { setAppHidden(pkg,false); if (cachedSummary) render(cachedSummary,cachedEvents,cachedStatus); }
});
$('pa-override-mode').addEventListener('change', updateOverrideFields);
$('pa-override-save').addEventListener('click', async () => {
  const deviceId = $('pa-rule-device').value;
  if (!deviceId) return alert('Select a paired phone.');
  const policy = {
    mode: $('pa-override-mode').value,
    duration_minutes: Number($('pa-override-duration').value),
    cooldown_minutes: Number($('pa-override-cooldown').value),
  };
  if (policy.mode === 'pin') policy.pin = $('pa-override-pin').value;
  try {
    await savePhoneOverridePolicy(deviceId, policy);
    await loadOverridePolicy();
    $('pa-override-status').textContent = 'Saved. The phone will receive this policy on its next sync.';
  } catch (error) { $('pa-override-status').textContent = error.message; }
});
$('pa-rule-metric').addEventListener('change', () => { $('pa-rule-category').hidden = !$('pa-rule-metric').value.startsWith('category_'); });
$('pa-rule-save').addEventListener('click', async () => {
  const deviceId = $('pa-rule-device').value;
  const target = $('pa-rule-package').value.trim();
  const metric = $('pa-rule-metric').value;
  const category = $('pa-rule-category').value.trim();
  const value = Number($('pa-rule-value').value);
  if (!deviceId || !target || !Number.isFinite(value) || value < 1) return alert('Choose a phone, package and positive limit.');
  if (metric.startsWith('category_') && !category) return alert('Enter a category for the shared limit.');
  try {
    if (metric.startsWith('category_')) await setPhoneCategory(deviceId,target,category);
    await savePhoneRule(deviceId, { name: `${target} · ${value} ${metric.includes('usage') ? 'min' : 'opens'}`, target, action: 'block',
      when: { metric, operator: '>=', value, unit: metric.includes('usage') ? 'minutes' : 'count',
        ...(metric.startsWith('category_') ? { category } : {}) } });
    await loadRules();
  } catch (error) { alert(error.message); }
});
$('pa-rules').addEventListener('click', async (event) => {
  const ruleId = event.target.closest('[data-delete-rule]')?.dataset.deleteRule;
  if (!ruleId) return;
  try { await deletePhoneRule(ruleId); await loadRules(); } catch (error) { alert(error.message); }
});
$('pa-places').addEventListener('click', async (event) => {
  const key = event.target.closest('[data-place]')?.dataset.place;
  const deviceId = $('pa-device').value;
  if (!key) return;
  if (!deviceId) return alert('Select one phone before naming a place.');
  const label = prompt('Place name');
  if (!label) return;
  try { await namePhonePlace(deviceId,key,label); await refresh(); } catch (error) { alert(error.message); }
});
$('pa-pair').addEventListener('click', async () => {
  try {
    const credentials = await pairPhone($('pa-device-label').value);
    const host = location.hostname === 'localhost' || location.hostname === '127.0.0.1' ? '<PC LAN IP>' : location.hostname;
    $('pa-pair-result').textContent = `Server: http://${host}:8000\nDevice ID: ${credentials.device_id}\nToken: ${credentials.token}\n\nCopy now. This token cannot be retrieved later.`;
    $('pa-pair-result').hidden = false;
    await refresh();
  } catch (error) { $('pa-error').textContent = error.message; $('pa-error').hidden = false; }
});
$('pa-delete-range').addEventListener('click', async () => {
  if (settings().range === 'all') return alert('Choose a bounded period, or use Delete all.');
  if (!confirm('Delete all PC phone events in the selected period?')) return;
  try { await deletePhoneEvents(settings()); await refresh(); }
  catch (error) { alert(error.message); }
});
$('pa-delete-all').addEventListener('click', async () => {
  if (!confirm('Delete all PC phone events, devices, pairings, app icons and rules? You must pair again. This cannot be undone.')) return;
  try { await deleteAllPhoneData(); await refresh(); }
  catch (error) { alert(error.message); }
});
for (const [id,days] of [['pa-sample-day',1],['pa-sample-week',7]]) $(id).addEventListener('click', async () => {
  try { await generatePhoneSample(days); $('pa-source').value = 'sample'; $('pa-range').value = days === 7 ? '7d' : 'today'; await refresh(); }
  catch (error) { alert(error.message); }
});
$('pa-sample-clear').addEventListener('click', async () => {
  try { await clearPhoneSample(); await refresh(); } catch (error) { alert(error.message); }
});
getPhoneRetention().then((settings) => {
  $('pa-retention-notification').value = settings.raw_notification_text_days;
  $('pa-retention-usage').value = settings.usage_events_days ?? '';
}).catch(() => {});
$('pa-retention-save').addEventListener('click', async () => {
  const notification = Number($('pa-retention-notification').value);
  const usage = $('pa-retention-usage').value ? Number($('pa-retention-usage').value) : null;
  try { await savePhoneRetention({ raw_notification_text_days:notification, usage_events_days:usage }); await refresh(); }
  catch (error) { alert(error.message); }
});
refresh();
