import { getPhoneAccess, getPhoneAccessHistory, savePhoneAccessPolicy, changePhoneAccessPlan } from './phone-tracker-api.js';
import { escapeHtml } from './utils.js';
import { friendlyAppName } from './phone-activity-display.js';

const $ = (id) => document.getElementById(id);
let policies = [];
let deviceId = '';
let requestId = 0;
let version = 0;
let selectedDevice = null;
const fmt = (value) => {
  const number = Number(value || 0);
  return String(Math.round(number));
};
const number = (id) => Number($(id).value);
const checked = (id) => $(id).checked;
const set = (id, value) => { $(id).value = value ?? ''; };
const setMinutes = (id, value) => set(id,value == null ? '' : Math.max(Number($(id).min) || 0,Math.round(value)));
const check = (id, value) => { $(id).checked = Boolean(value); };
const target = () => $('pa-access-target').value === '__custom__'
  ? $('pa-access-custom-target').value.trim() : $('pa-access-target').value;

function showPolicy(policy) {
  if (!policy) return;
  check('pa-access-enabled',policy.enabled);
  set('pa-access-baseline-mode',policy.baseline.mode);
  set('pa-access-window',policy.baseline.window_days);
  set('pa-access-calculation',policy.baseline.calculation);
  setMinutes('pa-access-manual',policy.baseline.manual_minutes);
  setMinutes('pa-access-hard-max',policy.baseline.hard_max_minutes);
  const reduction = policy.reduction || {};
  check('pa-access-reduction-enabled',reduction.enabled);
  set('pa-access-reduction-source',reduction.start_source || 'automatic');
  setMinutes('pa-access-reduction-start',reduction.manual_start_minutes ?? 50);
  set('pa-access-reduction-type',reduction.type || 'compound_percentage');
  set('pa-access-reduction-rate',reduction.percentage_per_day ?? 10);
  setMinutes('pa-access-reduction-fixed',reduction.fixed_minutes_per_day ?? 5);
  setMinutes('pa-access-reduction-floor',reduction.floor_minutes ?? 15);
  const bonus = policy.extra_reading || {};
  check('pa-access-bonus-enabled',bonus.enabled);
  set('pa-access-bonus-pages',bonus.pages_per_reward ?? 10);
  setMinutes('pa-access-bonus-minutes',bonus.minutes_per_reward ?? 2);
  setMinutes('pa-access-bonus-cap',bonus.daily_bonus_cap ?? 10);
  check('pa-access-bonus-partial',bonus.partial_rewards);
  check('pa-access-bonus-above',bonus.allow_above_base ?? true);
  set('pa-access-bonus-standalone',bonus.standalone_target_pages);
  for (const key of ['reading','cleaning']) {
    check(`pa-access-${key}`,policy.sources[key].enabled);
    set(`pa-access-${key}-weight`,policy.sources[key].weight);
    set(`pa-access-${key}-empty`,policy.sources[key].no_plan);
  }
  set('pa-access-formula',policy.formula);
  check('pa-access-notify',policy.notifications.enabled);
  check('pa-access-notify-bonus',policy.notifications.extra_reading_enabled ?? true);
  check('pa-access-notify-full',policy.notifications.full_plan_enabled ?? true);
  check('pa-access-notify-reduction',policy.notifications.reduction_enabled ?? false);
  set('pa-access-notify-min',policy.notifications.minimum_increase);
  check('pa-access-milestones',policy.notifications.milestones_enabled);
  set('pa-access-debounce',policy.notifications.debounce_seconds);
  for (const key of ['baseline','reading','cleaning','used','remaining'])
    check(`pa-access-show-${key}`,policy.notifications[`show_${key}`]);
  setMinutes('pa-access-session-max',policy.session.max_minutes);
  setMinutes('pa-access-session-cooldown',policy.session.cooldown_minutes);
  check('pa-access-night',policy.night.enabled);
  set('pa-access-night-from',policy.night.from);
  set('pa-access-night-until',policy.night.until);
  check('pa-access-override',policy.override.enabled);
  setMinutes('pa-access-override-duration',policy.override.duration_minutes);
  setMinutes('pa-access-override-cooldown',policy.override.cooldown_minutes);
  set('pa-access-override-max',policy.override.max_per_day);
}

function showState(policy, device) {
  device ||= selectedDevice;
  const state = policy?.state;
  const last = device?.last_sync ? new Date(device.last_sync).toLocaleTimeString() : 'never';
  const health = device?.last_blocker_enabled === 1 ? `Protection active at last report (${last})` :
    device?.last_blocker_enabled === 0 ? `Accessibility protection was OFF at last report (${last}). Re-enable Phone Tracker limits in Android settings.` :
      'Waiting for phone protection report';
  const sync = Number(device?.last_config_version || 0) < version ? ' · New rule awaits phone sync' : '';
  $('pa-access-live').classList.toggle('is-warning',device?.last_blocker_enabled !== 1);
  if (!state) {
    $('pa-access-live').textContent = `${health}${sync}. Choose an app and save its rule.`;
    $('pa-access-baseline-info').textContent = '';
    $('pa-access-reduction-status').textContent = '';
    $('pa-access-forecast').textContent = '';
    $('pa-access-pause').disabled = true;
    $('pa-access-resume').disabled = true;
    $('pa-access-restart').disabled = true;
    return;
  }
  const source = (key) => {
    const item = state.sources?.[key];
    return item?.target_value == null ? `${key}: waiting for today's plan` :
      `${key}: ${item.current_value}/${item.target_value} (${Math.round(item.progress * 100)}%)`;
  };
  const plan = state.reduction_plan || {};
  const metrics = [
    ['Today’s base cap',fmt(state.effective_base_cap_minutes ?? state.baseline_minutes)],
    ['Plan unlocked',fmt(state.normal_unlocked_minutes ?? state.unlocked_minutes)],
    ['Reading bonus',`+${fmt(state.extra_reading_bonus_minutes)}`],
    ['Total unlocked',fmt(state.total_unlocked_minutes ?? state.unlocked_minutes)],
    ['Used',fmt(state.used_minutes)],
  ];
  $('pa-access-live').innerHTML = `<strong>${escapeHtml(friendlyAppName(policy.target))} · Available now ${fmt(state.remaining_minutes)} min</strong>
    <span>${escapeHtml(health + sync)}</span><div class="pa-access-metrics">${metrics.map(([label,value]) =>
      `<div><small>${escapeHtml(label)}</small><b>${escapeHtml(value)} min</b></div>`).join('')}</div>
    <span>${escapeHtml(source('reading'))} · ${escapeHtml(source('cleaning'))}</span>
    <span>${plan.enabled ? `Reduction day ${plan.day} · ${escapeHtml(policy.reduction.type.replaceAll('_',' '))} · floor ${fmt(policy.reduction.floor_minutes)} min` : 'Baseline reduction off'}</span>`;
  $('pa-access-baseline-info').textContent = `Historical ${policy.baseline.window_days}-day average now: ${fmt(state.historical_baseline_minutes ?? state.baseline_minutes)} min. Reduction reference snapshot: ${fmt(state.reference_baseline_minutes ?? state.baseline_minutes)} min.`;
  $('pa-access-reduction-status').textContent = plan.enabled ?
    `Started ${plan.start_date} · Day ${plan.day} · ${plan.paused ? 'Paused' : plan.floor_reached ? 'Floor reached' : 'Active'} · Floor date ${plan.estimated_floor_date || 'pending'}` :
    'Reduction disabled. Enable and save to snapshot a starting baseline.';
  const forecast = plan.forecast || {};
  $('pa-access-forecast').innerHTML = plan.enabled ?
    [['Today',forecast.today],['Tomorrow',forecast.tomorrow],['+3 days',forecast.plus_3_days],
      ['+7 days',forecast.plus_7_days],['Floor',forecast.floor]].map(([label,value]) =>
      `<span>${escapeHtml(label)}<b>${fmt(value)} min</b></span>`).join('') : '';
  $('pa-access-pause').disabled = !plan.enabled || plan.paused;
  $('pa-access-resume').disabled = !plan.enabled || !plan.paused;
  $('pa-access-restart').disabled = !plan.enabled;
}

async function showHistory() {
  const current = target();
  if (!deviceId || !current || !policies.some((item) => item.target === current)) {
    $('pa-access-history').textContent = 'Save this app rule to start history.';
    return;
  }
  try {
    const response = await getPhoneAccessHistory(deviceId,current);
    if (current !== target()) return;
    const days = response.days || response.history || [];
    const mean = (values) => values.reduce((sum,value) => sum + value,0) / values.length;
    const xs = days.map((day) => Number(day.progress || 0));
    const ys = days.map((day) => Number(day.used_minutes || 0));
    const xMean = days.length ? mean(xs) : 0;
    const yMean = days.length ? mean(ys) : 0;
    const numerator = xs.reduce((sum,value,index) => sum + (value-xMean)*(ys[index]-yMean),0);
    const denominator = Math.sqrt(xs.reduce((sum,value) => sum + (value-xMean)**2,0) *
      ys.reduce((sum,value) => sum + (value-yMean)**2,0));
    const correlation = days.length >= 3 && denominator > 0 ?
      `<p class="note">Completion vs app use: r = ${(numerator/denominator).toFixed(2)} across ${days.length} days. Descriptive association only.</p>` : '';
    $('pa-access-history').innerHTML = days.length ? correlation + days.map((day) => {
      const baseline = Math.max(1,day.effective_base_cap_minutes ?? day.baseline_minutes);
      const completion = Math.round(100 * (day.progress || 0));
      const normal = day.normal_unlocked_minutes ?? day.unlocked_minutes;
      const bonus = day.extra_reading_bonus_minutes ?? 0;
      const total = day.total_unlocked_minutes ?? day.unlocked_minutes;
      return `<div class="pa-access-day"><b>${escapeHtml(day.day)}</b>
        <span>Reference ${fmt(day.reference_baseline_minutes ?? day.baseline_minutes)} · Base cap ${fmt(baseline)} min · Reduction day ${day.reduction_plan?.day ?? '—'}</span>
        <span>Reading ${day.sources?.reading?.current_value ?? 0}/${day.sources?.reading?.target_value ?? '—'} · Cleaning ${day.sources?.cleaning?.current_value ?? 0}/${day.sources?.cleaning?.target_value ?? '—'}</span>
        <span>Plan ${fmt(normal)} + Extra reading ${fmt(bonus)} (${day.extra_reading_pages ?? 0} pages) = <b>${fmt(total)} min</b></span>
        <span>Used ${fmt(day.used_minutes)} · Remaining ${fmt(day.remaining_minutes_at_day_end ?? day.unused_minutes)} · ${day.blocked_attempts} blocks · ${day.override_count} overrides (${fmt(day.override_minutes)} min)</span>
        <div class="pa-access-bars" aria-label="Unlocked and used versus base cap"><i style="width:${Math.min(100,100*total/baseline)}%"></i><em style="width:${Math.min(100,100*day.used_minutes/baseline)}%"></em></div>
        <small>Plan completion ${completion}% · ${day.corrections?.length || 0} corrections</small></div>`;
    }).join('') : '<p class="note">No completed days yet.</p>';
  } catch (error) { $('pa-access-history').textContent = error.message; }
}

function choosePolicy(device) {
  const policy = policies.find((item) => item.target === target());
  if (policy) showPolicy(policy);
  showState(policy,device);
  showHistory();
}

export async function loadAccessPage(devices = [], apps = []) {
  const currentDevice = $('pa-rule-device').value;
  if (!currentDevice) { $('pa-access-live').textContent = 'Pair a phone first.'; return; }
  const currentRequest = ++requestId;
  deviceId = currentDevice;
  try {
    const data = await getPhoneAccess(currentDevice);
    if (currentRequest !== requestId) return;
    policies = data.policies || [];
    version = Number(data.version || 0);
    selectedDevice = devices.find((item) => item.device_id === currentDevice);
    const existing = target();
    const choices = new Map([['com.instagram.android','Instagram']]);
    for (const app of apps) if (app.package_name) choices.set(app.package_name,friendlyAppName(app.package_name,app.app_name));
    for (const policy of policies) choices.set(policy.target,friendlyAppName(policy.target));
    $('pa-access-target').innerHTML = [...choices].sort((a,b) => a[1].localeCompare(b[1])).map(([pkg,name]) =>
      `<option value="${escapeHtml(pkg)}">${escapeHtml(name)}</option>`).join('') + '<option value="__custom__">Other app…</option>';
    $('pa-access-target').value = choices.has(existing) ? existing : 'com.instagram.android';
    $('pa-access-custom-target').hidden = $('pa-access-target').value !== '__custom__';
    choosePolicy(selectedDevice);
  } catch (error) { $('pa-access-live').textContent = error.message; }
}

function formPolicy() {
  const current = policies.find((item) => item.target === target());
  return {
    ...(current?.policy_id ? {policy_id:current.policy_id} : {}), target:target(), enabled:checked('pa-access-enabled'),
    baseline:{mode:$('pa-access-baseline-mode').value,window_days:number('pa-access-window'),
      calculation:$('pa-access-calculation').value,manual_minutes:number('pa-access-manual'),
      hard_max_minutes:$('pa-access-hard-max').value ? number('pa-access-hard-max') : null},
    reduction:{enabled:checked('pa-access-reduction-enabled'),start_source:$('pa-access-reduction-source').value,
      manual_start_minutes:number('pa-access-reduction-start'),type:$('pa-access-reduction-type').value,
      percentage_per_day:number('pa-access-reduction-rate'),fixed_minutes_per_day:number('pa-access-reduction-fixed'),
      floor_minutes:number('pa-access-reduction-floor')},
    extra_reading:{enabled:checked('pa-access-bonus-enabled'),pages_per_reward:number('pa-access-bonus-pages'),
      minutes_per_reward:number('pa-access-bonus-minutes'),daily_bonus_cap:number('pa-access-bonus-cap'),
      partial_rewards:checked('pa-access-bonus-partial'),allow_above_base:checked('pa-access-bonus-above'),
      standalone_target_pages:$('pa-access-bonus-standalone').value ? number('pa-access-bonus-standalone') : null},
    sources:Object.fromEntries(['reading','cleaning'].map((key) => [key,{
      enabled:checked(`pa-access-${key}`),weight:number(`pa-access-${key}-weight`),
      no_plan:$(`pa-access-${key}-empty`).value}])),
    formula:$('pa-access-formula').value,
    notifications:{enabled:checked('pa-access-notify'),extra_reading_enabled:checked('pa-access-notify-bonus'),
      full_plan_enabled:checked('pa-access-notify-full'),reduction_enabled:checked('pa-access-notify-reduction'),
      minimum_increase:number('pa-access-notify-min'),
      milestones_enabled:checked('pa-access-milestones'),milestones:[25,50,75,100],debounce_seconds:number('pa-access-debounce'),
      ...Object.fromEntries(['baseline','reading','cleaning','used','remaining'].map((key) => [`show_${key}`,checked(`pa-access-show-${key}`)]))},
    session:{max_minutes:number('pa-access-session-max'),cooldown_minutes:number('pa-access-session-cooldown')},
    night:{enabled:checked('pa-access-night'),from:$('pa-access-night-from').value,until:$('pa-access-night-until').value},
    override:{enabled:checked('pa-access-override'),duration_minutes:number('pa-access-override-duration'),
      cooldown_minutes:number('pa-access-override-cooldown'),max_per_day:number('pa-access-override-max')},
  };
}

$('pa-access-target').addEventListener('change', () => {
  $('pa-access-custom-target').hidden = $('pa-access-target').value !== '__custom__';
  choosePolicy();
});
for (const action of ['pause','resume','restart']) {
  $(`pa-access-${action}`).addEventListener('click', async () => {
    const status = $('pa-access-save-status');
    if (!deviceId || !target()) { status.textContent = 'Choose a paired phone and an app.'; return; }
    if (action === 'restart' && !window.confirm('Restart reduction from today? This snapshots a new starting baseline and date.')) return;
    status.textContent = `${action}…`;
    try {
      if (action === 'restart') await savePhoneAccessPolicy(deviceId,formPolicy());
      await changePhoneAccessPlan(deviceId,target(),action);
      await loadAccessPage(window.phoneAccessDevices || [],window.phoneAccessApps || []);
      status.textContent = `Reduction plan ${action === 'pause' ? 'paused' : action === 'resume' ? 'resumed' : 'restarted'}. Phone updates on its next sync.`;
    } catch (error) { status.textContent = error.message; }
  });
}
$('pa-access-custom-target').addEventListener('change',() => choosePolicy());
$('pa-access-save').addEventListener('click', async () => {
  const status = $('pa-access-save-status');
  status.textContent = 'Saving…';
  try {
    if (!deviceId || !target()) throw new Error('Choose a paired phone and an app.');
    await savePhoneAccessPolicy(deviceId,formPolicy());
    await loadAccessPage(window.phoneAccessDevices || [],window.phoneAccessApps || []);
    status.textContent = 'Saved. The phone will receive this rule on its next sync.';
  } catch (error) { status.textContent = error.message; }
});
