export const NETWORK_STATUS_NOTIFICATIONS_STORAGE_KEY =
  "networkWidgetStatusNotificationsEnabled";
export const NETWORK_STATUS_NOTIFICATIONS_CHANGED_EVENT =
  "network:status-notifications-changed";

const canUseStorage = () => typeof window !== "undefined" && !!window.localStorage;

export function getNetworkStatusNotificationsEnabled() {
  if (!canUseStorage()) return true;

  try {
    return window.localStorage.getItem(NETWORK_STATUS_NOTIFICATIONS_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

export function setNetworkStatusNotificationsEnabled(enabled) {
  const nextEnabled = enabled !== false;

  if (canUseStorage()) {
    try {
      window.localStorage.setItem(
        NETWORK_STATUS_NOTIFICATIONS_STORAGE_KEY,
        nextEnabled ? "true" : "false",
      );
    } catch {
      // Ignore storage failures; same-window listeners still get the new value.
    }
  }

  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent(NETWORK_STATUS_NOTIFICATIONS_CHANGED_EVENT, {
      detail: { enabled: nextEnabled },
    }));
  }

  return nextEnabled;
}
