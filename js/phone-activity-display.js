const HIDDEN_KEY = 'phoneActivity.hiddenApps.v1';
const DEFAULT_HIDDEN = ['com.miui.home', 'com.android.systemui'];
const NAMES = {
  'com.miui.home': 'System launcher',
  'com.android.systemui': 'System UI',
  'com.miui.securitycenter': 'Security',
  'com.google.android.googlequicksearchbox': 'Google',
  'com.google.android.permissioncontroller': 'Permissions',
  'com.android.permissioncontroller': 'Permissions',
  'com.android.settings': 'Settings',
  'com.cleaningdashboard.phonetracker': 'Phone Tracker',
  'com.cleaningdashboard.howifeel': 'How I Feel',
  'com.instagram.android': 'Instagram',
  'com.tinder': 'Tinder',
};

export function friendlyAppName(packageName, appName = '') {
  if (appName && appName !== packageName && !appName.startsWith('com.')) return appName;
  return NAMES[packageName] || (packageName || 'Unknown app').split('.').at(-1)
    .replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[-_]/g, ' ')
    .replace(/^./, (letter) => letter.toUpperCase());
}

export function hiddenApps() {
  try {
    const saved = JSON.parse(localStorage.getItem(HIDDEN_KEY) || 'null');
    if (Array.isArray(saved)) return saved.filter((value) => typeof value === 'string');
  } catch { /* use defaults */ }
  return [...DEFAULT_HIDDEN];
}

export function setAppHidden(packageName, hidden) {
  const next = new Set(hiddenApps());
  if (hidden) next.add(packageName);
  else next.delete(packageName);
  localStorage.setItem(HIDDEN_KEY, JSON.stringify([...next]));
  window.dispatchEvent(new Event('phone-activity-visibility-changed'));
}
