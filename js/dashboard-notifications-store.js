export const DASHBOARD_NOTIFICATIONS_STORAGE_KEY = "dashboard.notifications.v1";
export const DASHBOARD_NOTIFICATIONS_CHANGED_EVENT = "dashboard:notifications-changed";

const MAX_NOTIFICATIONS = 50;

export function listDashboardNotifications() {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(DASHBOARD_NOTIFICATIONS_STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item && item.id && item.title)
      .slice(0, MAX_NOTIFICATIONS);
  } catch {
    return [];
  }
}

export function addDashboardNotification(notification) {
  const id = String(notification?.id || "").trim();
  const title = String(notification?.title || "").trim();
  if (!id || !title) return false;

  const current = listDashboardNotifications();
  if (current.some((item) => item.id === id)) return false;

  const next = [{
    id,
    title,
    category: String(notification?.category || "Dashboard"),
    message: String(notification?.message || ""),
    targetId: String(notification?.targetId || ""),
    createdAt: notification?.createdAt || new Date().toISOString(),
    read: false,
  }, ...current].slice(0, MAX_NOTIFICATIONS);

  try {
    globalThis.localStorage?.setItem(DASHBOARD_NOTIFICATIONS_STORAGE_KEY, JSON.stringify(next));
  } catch {
    return false;
  }
  globalThis.window?.dispatchEvent?.(new CustomEvent(DASHBOARD_NOTIFICATIONS_CHANGED_EVENT));
  return true;
}

export function removeDashboardNotifications(predicate) {
  const current = listDashboardNotifications();
  const next = current.filter((item) => !predicate(item));
  if (next.length === current.length) return false;
  try {
    globalThis.localStorage?.setItem(DASHBOARD_NOTIFICATIONS_STORAGE_KEY, JSON.stringify(next));
  } catch {
    return false;
  }
  globalThis.window?.dispatchEvent?.(new CustomEvent(DASHBOARD_NOTIFICATIONS_CHANGED_EVENT));
  return true;
}

export function markDashboardNotificationRead(id) {
  const current = listDashboardNotifications();
  let changed = false;
  const next = current.map((item) => {
    if (item.id !== id || item.read) return item;
    changed = true;
    return { ...item, read: true };
  });
  if (!changed) return false;

  try {
    globalThis.localStorage?.setItem(DASHBOARD_NOTIFICATIONS_STORAGE_KEY, JSON.stringify(next));
  } catch {
    return false;
  }
  globalThis.window?.dispatchEvent?.(new CustomEvent(DASHBOARD_NOTIFICATIONS_CHANGED_EVENT));
  return true;
}
