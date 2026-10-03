const ROOT = '/api/phone-tracker';

async function request(path, options = {}) {
  const response = await fetch(`${ROOT}${path}`, {
    cache: 'no-store', credentials: 'same-origin', ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Phone Tracker HTTP ${response.status}`);
  return body;
}

function query(params) {
  const url = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') url.set(key, String(value));
  }
  return `?${url}`;
}

export const trackerTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
export const getPhoneStatus = () => request('/status');
export const getPhoneDevices = () => request('/devices');
export const getPhoneSummary = (params = {}) => request(`/summary${query({ tz: trackerTimezone(), ...params })}`);
export const getPhoneEvents = (params = {}) => request(`/events${query({ tz: trackerTimezone(), ...params })}`);
export const getPhoneInsights = (params = {}) => request(`/insights${query({ tz: trackerTimezone(), ...params })}`);
export const pairPhone = (label) => request('/pair', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ label }),
});
export const deletePhoneEvents = (params) => request(`/events${query({ tz: trackerTimezone(), ...params })}`, { method: 'DELETE' });
export const deleteAllPhoneData = () => request('/all?confirm=delete', { method: 'DELETE' });
export const generatePhoneSample = (days) => request('/sample', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ days, tz: trackerTimezone() }),
});
export const clearPhoneSample = () => request('/sample', { method: 'DELETE' });
export const getPhoneRules = (deviceId) => request(`/rules${query({ device_id: deviceId })}`);
export const getPhoneAccess = (deviceId) => request(`/access${query({ device_id: deviceId })}`);
export const getPhoneAccessHistory = (deviceId, target = 'com.instagram.android', days = 30) =>
  request(`/access/history${query({ device_id:deviceId,target,days })}`);
export const savePhoneAccessPolicy = (deviceId, policy) => request('/access', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body:JSON.stringify({device_id:deviceId,policy}),
});
export const changePhoneAccessPlan = (deviceId, target, action) => request('/access/plan', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body:JSON.stringify({device_id:deviceId,target,action}),
});
export const getPhoneOverridePolicy = (deviceId) => request(`/override-policy${query({ device_id: deviceId })}`);
export const savePhoneOverridePolicy = (deviceId, policy) => request('/override-policy', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ device_id: deviceId, ...policy }),
});
export const savePhoneRule = (deviceId, rule) => request('/rules', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ device_id: deviceId, rule }),
});
export const deletePhoneRule = (ruleId) => request(`/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' });
export const setPhoneCategory = (deviceId, packageName, category) => request('/category', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ device_id: deviceId, package_name: packageName, category }),
});
export const setPhoneExternalCondition = (deviceId, name, value) => request('/external-condition', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ device_id: deviceId, name, value }),
});
export const namePhonePlace = (deviceId, clusterKey, label) => request('/place', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ device_id: deviceId, cluster_key: clusterKey, label }),
});
export const getPhoneRetention = () => request('/retention');
export const savePhoneRetention = (settings) => request('/retention', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings),
});
