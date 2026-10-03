import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { financeImportAgeLabel, remindAboutFinanceImports, scheduleFinanceImportReminders } from "../js/finance-import-reminder.js";
import { addDashboardNotification, listDashboardNotifications } from "../js/dashboard-notifications-store.js";

describe("finance import reminders", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { scheduleFinanceImportReminders([]); vi.useRealTimers(); });

  it("resets only that account's reminder after an import and waits a full seven days", () => {
    const now = new Date("2026-10-16T10:00:00Z");
    const accounts = [
      { id: 1, name: "Konto główne", lastImportedAt: "2026-10-02T10:00:00Z" },
      { id: 2, name: "Cele", lastImportedAt: "2026-10-10T10:00:00Z" },
    ];
    remindAboutFinanceImports(accounts, now);
    remindAboutFinanceImports(accounts, now);
    expect(listDashboardNotifications()).toHaveLength(1);
    expect(listDashboardNotifications()[0].title).toContain("Konto główne");

    remindAboutFinanceImports(accounts, new Date("2026-10-17T10:00:00Z"));
    expect(listDashboardNotifications()).toHaveLength(2);
    expect(listDashboardNotifications()[0].title).toContain("Cele");

    addDashboardNotification({ id: "other:1", title: "Other notification" });
    const refreshed = { ...accounts[0], lastImportedAt: "2026-10-17T11:00:00Z" };
    remindAboutFinanceImports([refreshed], new Date("2026-10-17T11:00:00Z"));
    expect(listDashboardNotifications().map((item) => item.id)).toEqual(["other:1", expect.stringContaining("finance-import:2:")]);
    remindAboutFinanceImports([refreshed], new Date("2026-10-24T10:59:59.999Z"));
    expect(listDashboardNotifications()).toHaveLength(2);
    remindAboutFinanceImports([refreshed], new Date("2026-10-24T11:00:00Z"));
    expect(listDashboardNotifications()).toHaveLength(3);
    expect(listDashboardNotifications()[0].id).toContain("2026-10-17T11:00:00Z:1");
  });

  it("triggers while the page stays open when seven days have elapsed", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-02T10:00:00Z"));
    scheduleFinanceImportReminders([{ id: 1, name: "Konto główne", lastImportedAt: "2026-10-02T10:00:00Z" }]);
    vi.advanceTimersByTime(7 * 24 * 60 * 60 * 1000 - 1);
    expect(listDashboardNotifications()).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(listDashboardNotifications()).toHaveLength(1);
  });

  it("moves the pending deadline when a newer import arrives", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-02T10:00:00Z"));
    const account = { id: 1, name: "Konto główne", lastImportedAt: "2026-10-02T10:00:00Z" };
    scheduleFinanceImportReminders([account]);
    vi.advanceTimersByTime(6 * 24 * 60 * 60 * 1000);
    scheduleFinanceImportReminders([{ ...account, lastImportedAt: "2026-10-08T10:00:00Z" }]);
    vi.advanceTimersByTime(24 * 60 * 60 * 1000);
    expect(listDashboardNotifications()).toHaveLength(0);
    vi.advanceTimersByTime(6 * 24 * 60 * 60 * 1000);
    expect(listDashboardNotifications()).toHaveLength(1);
  });

  it("formats the age of each account import", () => {
    const now = new Date("2026-10-05T12:00:00Z");
    expect(financeImportAgeLabel("2026-10-05T12:00:00Z", now)).toBe("teraz");
    expect(financeImportAgeLabel("2026-10-05T11:00:00Z", now)).toBe("1 godz. temu");
    expect(financeImportAgeLabel("2026-10-04T12:00:00Z", now)).toBe("wczoraj");
    expect(financeImportAgeLabel("2026-10-03T12:00:00Z", now)).toBe("2 dni temu");
  });
});
