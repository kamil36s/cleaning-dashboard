import path from "node:path";
import { pathToFileURL } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";

async function importFreshModule() {
  const modulePath = pathToFileURL(path.resolve("js/network-notification-settings.js")).href;
  return import(`${modulePath}?t=${Date.now()}`);
}

describe("network status notification settings", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("enables network notifications by default", async () => {
    const { getNetworkStatusNotificationsEnabled } = await importFreshModule();

    expect(getNetworkStatusNotificationsEnabled()).toBe(true);
  });

  it("persists the notification toggle and emits a same-window event", async () => {
    const {
      NETWORK_STATUS_NOTIFICATIONS_CHANGED_EVENT,
      NETWORK_STATUS_NOTIFICATIONS_STORAGE_KEY,
      getNetworkStatusNotificationsEnabled,
      setNetworkStatusNotificationsEnabled,
    } = await importFreshModule();

    const calls = [];
    const handler = (event) => calls.push(event.detail);

    window.addEventListener(NETWORK_STATUS_NOTIFICATIONS_CHANGED_EVENT, handler);
    try {
      setNetworkStatusNotificationsEnabled(false);
    } finally {
      window.removeEventListener(NETWORK_STATUS_NOTIFICATIONS_CHANGED_EVENT, handler);
    }

    expect(localStorage.getItem(NETWORK_STATUS_NOTIFICATIONS_STORAGE_KEY)).toBe("false");
    expect(getNetworkStatusNotificationsEnabled()).toBe(false);
    expect(calls).toEqual([{ enabled: false }]);
  });
});
