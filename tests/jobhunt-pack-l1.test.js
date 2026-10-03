import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJobhuntApi } from "../js/jobhunt-api.js";
import {
  createJobhuntIngestionController,
  renderJobbnorgeOperations,
} from "../js/jobhunt-ingestion.js";
import { PLANNED_SOURCES, renderTrackDetail } from "../js/jobhunt-tracks.js";


function response(data, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ ok: status >= 200 && status < 300, data }),
  });
}

function jobbnorgeStatus(overrides = {}) {
  return {
    auth: { required: false, configured: true, scheme: null },
    api: { host: "https://publicapi.jobbnorge.no", version: "v1", route: "/v1/Jobs", singleJobEndpoint: false },
    source: {
      id: "source_jobbnorge", key: "jobbnorge", displayName: "Jobbnorge",
      adapter: { implemented: true, key: "jobbnorge-public-api", version: "jobbnorge-public-api-v1@1" },
      policy: {
        enabled: true, operationalState: "enabled", accessMethod: "official_api",
        termsVersion: "public-api-v1-reviewed-2026-09-24", backoffUntil: null,
      },
      listingCount: 3, captureCount: 1, collectionCaptureCount: 3,
      collectionStatus: "Official Public API available",
    },
    worker: { state: "running", counts: { queued: 0, running: 0 } },
    queryState: {
      currentQueryIndex: 1, currentPage: 2, lastPollAt: "2026-09-24T10:00:00Z",
      lastSuccessAt: "2026-09-24T10:00:00Z", listingsObserved: 3,
      matchedListings: 1, capturesCreated: 1,
    },
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("Job Hunt Pack L1 Jobbnorge", () => {
  beforeEach(() => { document.body.innerHTML = `<div id="root"></div>`; });

  it("exposes narrow Jobbnorge API methods with empty command bodies", async () => {
    const fetchImpl = vi.fn((url) => response({ url }));
    const api = createJobhuntApi({ fetchImpl, baseUrl: "/api/jobhunt" });
    await api.jobbnorgeStatus();
    await api.jobbnorgeSyncState();
    await api.jobbnorgeEnable();
    await api.jobbnorgePause();
    await api.jobbnorgeSync();
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "/api/jobhunt/sources/jobbnorge/status",
      "/api/jobhunt/sources/jobbnorge/sync-state",
      "/api/jobhunt/sources/jobbnorge/enable",
      "/api/jobhunt/sources/jobbnorge/pause",
      "/api/jobhunt/sources/jobbnorge/sync",
    ]);
    expect(fetchImpl.mock.calls.slice(2).every(([, options]) => options.method === "POST" && options.body === "{}")).toBe(true);
  });

  it("renders honest public-API provenance and escapes operational errors", () => {
    const html = renderJobbnorgeOperations(jobbnorgeStatus({
      queryState: { lastErrorMessage: `<img src=x onerror="alert(1)">` },
    }));
    expect(html).toContain("Official Public API");
    expect(html).toContain("authentication: not required");
    expect(html).toContain("Exact collection response bytes");
    expect(html).toContain("explicitly derived");
    expect(html).not.toMatch(/crawler|scrap/i);
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
  });

  it("renders independent adapter availability in Search Profiles", () => {
    expect(PLANNED_SOURCES.find(([key]) => key === "jobbnorge")[2]).toBe("available");
    expect(PLANNED_SOURCES.find(([key]) => key === "finn")[2]).toContain("unavailable");
    const html = renderTrackDetail({
      track: {
        id: "track-1", name: "Norway QA", status: "active", geography: {},
        purpose: "QA", updatedAt: "2026-09-24T00:00:00Z",
      },
      searchProfiles: [], assignedJobs: [],
    });
    expect(html).toContain("Jobbnorge - available");
    expect(html).toContain("FINN - not implemented / unavailable");
    expect(html).toContain("only enabled, available adapters may collect");
  });

  it("loads Jobbnorge state and queues sync without browser credentials", async () => {
    const status = jobbnorgeStatus();
    const client = {
      sources: vi.fn().mockResolvedValue({ sources: [status.source] }),
      sourceListings: vi.fn().mockResolvedValue({ listings: [] }),
      tracks: vi.fn().mockResolvedValue({ tracks: [] }),
      jobbnorgeStatus: vi.fn().mockResolvedValue(status),
      workerJobs: vi.fn().mockResolvedValue({ counts: {}, jobs: [] }),
      jobbnorgeSync: vi.fn().mockResolvedValue({ message: "queued" }),
      ingestionStorageHealth: vi.fn(),
    };
    const onStatus = vi.fn();
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client, onStatus });
    await controller.refresh();
    expect(root.textContent).toContain("jobbnorge-public-api-v1@1");
    expect(root.textContent).toContain("query 2, page 2");
    root.querySelector('[data-ingestion-action="jobbnorge-sync"]').click();
    await flush();
    expect(client.jobbnorgeSync).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenCalledWith("Jobbnorge sync queued.", "success");
    expect(JSON.stringify(controller.state)).not.toContain("password");
  });
});
