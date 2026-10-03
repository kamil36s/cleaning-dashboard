import { describe, expect, it, vi } from "vitest";

import { financePrivacyPlugin } from "../vite.config.js";

describe("finance runtime privacy middleware", () => {
  it.each([
    "/data/budget.json",
    "/data/%62udget.json",
    "/data/finance.sqlite",
    "/data/finance.sqlite-wal",
    "/data/mental-health.sqlite",
    "/data/mental-health.sqlite-shm",
    "/data/jobhunt.sqlite",
    "/data/jobhunt.sqlite-shm",
    "/data/jobhunt/backups/local-storage-private.json",
    "/data/job%68unt/assets/branding/private.png",
    "/data/jobhunt/raw/sha256/aa/bb/private.txt",
    "/data/.finance-account-key",
    "/data/budget-backups/snapshot.json",
    "/data/finance-receipts/private.pdf",
    "/data/settings/bills.json",
  ])("blocks %s", (url) => {
    let middleware;
    financePrivacyPlugin().configureServer({
      middlewares: { use: (handler) => { middleware = handler; } },
    });
    const response = { end: vi.fn(), statusCode: 200 };
    const next = vi.fn();

    middleware({ url }, response, next);

    expect(response.statusCode).toBe(404);
    expect(response.end).toHaveBeenCalled();
    expect(next).not.toHaveBeenCalled();
  });
});
