import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJobhuntApi } from "../js/jobhunt-api.js";
import {
  createJobhuntIngestionController,
  renderNavOperations,
  renderWorkerQueue,
} from "../js/jobhunt-ingestion.js";


function response(data, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ ok: status >= 200 && status < 300, data }),
  });
}

function navStatus(overrides = {}) {
  return {
    tokenConfigured: true,
    source: {
      id: "source_nav", key: "nav", displayName: "NAV / Arbeidsplassen",
      definitionState: "active", adapter: { implemented: true, key: "nav", version: "v1" },
      policy: { enabled: true, operationalState: "enabled", accessMethod: "official_feed" },
      listingCount: 2, captureCount: 1, collectionStatus: "Official feed available",
    },
    worker: { state: "running", counts: { queued: 1, running: 0 } },
    feedState: { current_feed_page_id: "page-7", listings_observed: 4, active_listings: 2, matched_listings: 1, captures_created: 1 },
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("Job Hunt Pack G NAV operations", () => {
  beforeEach(() => { document.body.innerHTML = `<div id="root"></div>`; });

  it("exposes narrow worker and NAV API methods with empty command bodies", async () => {
    const fetchImpl = vi.fn((url) => response({ url }));
    const api = createJobhuntApi({ fetchImpl, baseUrl: "/api/jobhunt" });
    await api.workerStatus();
    await api.workerJobs({ states: "queued,running", limit: 20 });
    await api.workerJob("job / 1");
    await api.cancelWorkerJob("job-1");
    await api.navStatus();
    await api.navFeedState();
    await api.navEnable();
    await api.navPause();
    await api.navSync();
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "/api/jobhunt/worker/status",
      "/api/jobhunt/worker/jobs?states=queued%2Crunning&limit=20",
      "/api/jobhunt/worker/jobs/job%20%2F%201",
      "/api/jobhunt/worker/jobs/job-1/cancel",
      "/api/jobhunt/sources/nav/status",
      "/api/jobhunt/sources/nav/feed-state",
      "/api/jobhunt/sources/nav/enable",
      "/api/jobhunt/sources/nav/pause",
      "/api/jobhunt/sources/nav/sync",
    ]);
    expect(fetchImpl.mock.calls[6][1]).toMatchObject({ method: "POST", body: "{}" });
  });

  it("shows unknown metrics honestly and escapes source errors and worker data", () => {
    const navHtml = renderNavOperations(navStatus({
      tokenConfigured: false,
      feedState: { last_error_message: `<img src=x onerror="alert(1)">` },
    }));
    expect(navHtml).toContain("not observed");
    expect(navHtml).toContain("&lt;img");
    expect(navHtml).not.toContain("<img");
    expect(navHtml).toContain("JOBHUNT_NAV_TOKEN");

    const queueHtml = renderWorkerQueue({
      counts: { queued: 1, running: 0, retry_wait: 1, failed: 1 },
      jobs: [{
        id: "job-1", type: "nav_feed_poll", state: "retry_wait", stage: "retry_wait",
        attemptCount: 1, maxAttempts: 5, cancellable: true,
        error: { message: "<script>bad</script>" },
      }],
    });
    expect(queueHtml).toContain("1 retrying");
    expect(queueHtml).toContain("&lt;script&gt;bad&lt;/script&gt;");
    expect(queueHtml).not.toContain("<script>");
  });

  it("renders operational controls and queues sync without a browser token", async () => {
    const status = navStatus();
    const client = {
      sources: vi.fn().mockResolvedValue({ sources: [status.source] }),
      sourceListings: vi.fn().mockResolvedValue({ listings: [] }),
      tracks: vi.fn().mockResolvedValue({ tracks: [] }),
      navStatus: vi.fn().mockResolvedValue(status),
      workerJobs: vi.fn().mockResolvedValue({ counts: { queued: 1 }, jobs: [] }),
      navSync: vi.fn().mockResolvedValue({ message: "queued" }),
      navPause: vi.fn().mockResolvedValue(status),
      ingestionStorageHealth: vi.fn(),
    };
    const onStatus = vi.fn();
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client, onStatus });
    await controller.refresh();
    expect(root.textContent).toContain("Official pam-stilling-feed adapter");
    expect(root.textContent).toContain("page-7");
    root.querySelector('[data-ingestion-action="nav-sync"]').click();
    await flush();
    expect(client.navSync).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenCalledWith("NAV sync queued.", "success");
    expect(JSON.stringify(controller.state)).not.toContain("Bearer ");
  });
});
