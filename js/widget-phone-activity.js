import { onDomReady } from './dom-ready.js';
import { getPhoneStatus, getPhoneSummary, getPhoneAccess } from './phone-tracker-api.js';
import { escapeHtml } from './utils.js';
import { friendlyAppName, hiddenApps } from './phone-activity-display.js';

export const duration = (seconds) => {
  const minutes = Math.round((Number(seconds) || 0) / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m` : `${minutes}m`;
};

export function renderPhoneActivity(root, summary, status, previousWeek = null, access = null) {
  if (!root) return;
  const hidden = new Set(hiddenApps());
  const rows = summary.apps.filter((app) => !hidden.has(app.package_name)).slice(0, 4);
  const total = Math.max(summary.screen_time_seconds, 1);
  const lastSync = status.last_sync ? new Date(status.last_sync).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Never';
  const stale = !status.last_sync || Date.now() - new Date(status.last_sync).getTime() > 30 * 60_000;
  const maxHour = Math.max(1, ...summary.hourly_usage_seconds);
  const comparison = previousWeek?.event_count ? `vs previous 7-day avg · ${escapeHtml(duration(previousWeek.screen_time_seconds / 7))} / day` : 'No 7-day baseline yet';
  const instagram = access?.policies?.find((item) => item.target === "com.instagram.android");
  const budget = instagram?.state;
  const phone = status.devices?.find((item) => !item.is_sample);
  const protection = phone?.last_blocker_enabled === 0 ? '<span class="pa-budget-warning">Protection off on phone</span>' : '';
  root.innerHTML = `
    <div class="pa-hero"><div><span class="pa-eyebrow">TODAY</span><strong>${escapeHtml(duration(summary.screen_time_seconds))}</strong><small>${comparison}</small></div>
      <span class="pa-health ${stale ? 'is-stale' : ''}">${stale ? '○ Offline' : '● Recent sync'}</span></div>
    ${budget ? `<div class="pa-budget"><span>Instagram access</span><strong>${Math.round(budget.remaining_minutes)} min left ${budget.remaining_minutes > 0 ? '· available' : '· locked'}</strong>
      <small>${Math.round(budget.unlocked_minutes)} / ${Math.round(budget.baseline_minutes)} min unlocked · ${Math.round(budget.used_minutes)} used</small>
      <div class="pa-budget-track"><i style="width:${Math.min(100,100*budget.unlocked_minutes/Math.max(1,budget.baseline_minutes))}%"></i></div>
      ${['reading','cleaning'].map((key) => { const item = budget.sources?.[key]; return item ? `<div class="pa-budget-source"><span>${escapeHtml(key)} ${item.current_value}/${item.target_value ?? '?'} · ${Math.round(item.progress*100)}%</span><div class="pa-budget-track"><i style="width:${Math.round(item.progress*100)}%"></i></div></div>` : ''; }).join('')}
      ${protection}</div>` : protection}
    <div class="pa-apps">${rows.length ? rows.map((app) => `<div class="pa-app-row">
      <span class="pa-app-name">${app.icon_base64 ? `<img src="data:image/png;base64,${app.icon_base64}" alt="" loading="lazy">` : ''}${escapeHtml(friendlyAppName(app.package_name, app.app_name))}</span><span>${escapeHtml(duration(app.seconds))}</span>
      <span class="pa-share">${Math.round(app.seconds / total * 100)}%</span>
      <div class="pa-track"><i style="width:${Math.min(100, app.seconds / total * 100)}%"></i></div></div>`).join('') : '<p class="pa-muted">Waiting for phone events.</p>'}</div>
    <div class="pa-metrics"><span><b>${summary.unlocks}</b> unlocks</span><span><b>${summary.notifications}</b> notifications</span><span><b>${summary.phone_sessions}</b> sessions</span></div>
    <div class="pa-hours" aria-label="Hourly screen time">${summary.hourly_usage_seconds.map((value, hour) => `<i title="${hour}:00 · ${escapeHtml(duration(value))}" style="height:${Math.max(4, Math.round(value / maxHour * 100))}%"></i>`).join('')}</div>
    <div class="pa-footer"><span>Last sync ${escapeHtml(lastSync)} · pending at last report ${(status.devices || []).reduce((sum,device) => sum + (device.last_reported_pending || 0),0)}</span><a href="./phone-activity.html">Explore activity →</a></div>`;
}

onDomReady(async () => {
  const root = document.getElementById('phone-activity-body');
  if (!root) return;
  const refresh = async () => {
    if (document.visibilityState === 'hidden') return;
    try {
      const [summary, status, previousWeek] = await Promise.all([getPhoneSummary(), getPhoneStatus(),getPhoneSummary({ range:'previous_7d' })]);
      const device = status.devices?.find((item) => !item.is_sample);
      const access = device ? await getPhoneAccess(device.device_id).catch(() => null) : null;
      renderPhoneActivity(root, summary, status, previousWeek, access);
    } catch (error) {
      root.textContent = `Phone activity unavailable: ${error.message}`;
    }
  };
  await refresh();
  window.setInterval(refresh, 60_000);
  window.addEventListener('phone-activity-visibility-changed', refresh);
});
