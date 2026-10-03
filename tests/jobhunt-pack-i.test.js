import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJobhuntApi } from "../js/jobhunt-api.js";
import {
  createJobhuntIngestionController,
  renderPracujOperations,
} from "../js/jobhunt-ingestion.js";


function response(data, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ ok: status >= 200 && status < 300, data }),
  });
}

function pracujStatus(overrides = {}) {
  return {
    mailConfig: {
      configured: true, host: "imap.example.test", mailbox: "Job Hunt/Pracuj",
      port: 993, tls: true, usernameConfigured: true,
    },
    source: {
      id: "source_pracuj", key: "pracuj", displayName: "Pracuj.pl",
      adapter: { implemented: true, key: "pracuj_jobalert", version: "1" },
      policy: { enabled: true, operationalState: "enabled", accessMethod: "official_email_alert" },
      collectionStatus: "Official JobAlert email available",
    },
    mailState: {
      lastPollAt: "2026-09-23T10:00:00Z", lastSuccessfulMessageAt: "2026-09-23T09:58:00Z",
      lastProcessedUid: 123, messagesInspected: 5, alertsRecognized: 2,
      listingsDiscovered: 3, capturesCreated: 3,
    },
    worker: { state: "running", counts: { queued: 0 } },
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("Job Hunt Pack I Pracuj JobAlert operations", () => {
  beforeEach(() => { document.body.innerHTML = `<div id="root"></div>`; });

  it("exposes only the narrow Pack I routes", async () => {
    const fetchImpl = vi.fn((url) => response({ url }));
    const api = createJobhuntApi({ fetchImpl, baseUrl: "/api/jobhunt" });
    await api.pracujStatus();
    await api.pracujMailState();
    await api.pracujEnable();
    await api.pracujPause();
    await api.pracujSync();
    await api.pracujBindings();
    await api.createPracujBinding({ subjectMatcher: "QA", searchProfileId: "search-1", enabled: true });
    await api.updatePracujBinding("binding / 1", { enabled: false });
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "/api/jobhunt/sources/pracuj/status",
      "/api/jobhunt/sources/pracuj/mail-state",
      "/api/jobhunt/sources/pracuj/enable",
      "/api/jobhunt/sources/pracuj/pause",
      "/api/jobhunt/sources/pracuj/sync",
      "/api/jobhunt/sources/pracuj/bindings",
      "/api/jobhunt/sources/pracuj/bindings",
      "/api/jobhunt/sources/pracuj/bindings/binding%20%2F%201",
    ]);
    expect(fetchImpl.mock.calls[2][1]).toMatchObject({ method: "POST", body: "{}" });
    expect(fetchImpl.mock.calls[7][1]).toMatchObject({ method: "PATCH", body: "{\"enabled\":false}" });
  });

  it("renders honest email-source state and escapes errors and bindings", () => {
    const html = renderPracujOperations(pracujStatus({
      mailState: { lastErrorMessage: `<img src=x onerror="bad()">` },
    }), [{
      id: "binding-1", enabled: true, trackName: "QA <script>",
      searchProfileName: "Poland", subjectMatcher: `<b>QA</b>`,
    }], [{ id: "search-1", name: "QA", trackName: "Track" }]);
    expect(html).toContain("Method: Official JobAlert email");
    expect(html).toContain("verified TLS / yes");
    expect(html).toContain("&lt;img");
    expect(html).toContain("QA &lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("password");
  });

  it("wires sync and binding controls through the ingestion controller", async () => {
    const status = pracujStatus();
    const source = status.source;
    const client = {
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      sourceListings: vi.fn().mockResolvedValue({ listings: [] }),
      tracks: vi.fn().mockResolvedValue({ tracks: [{ id: "track-1", name: "QA" }] }),
      track: vi.fn().mockResolvedValue({
        track: { id: "track-1", name: "QA" },
        searchProfiles: [{ id: "search-1", name: "Poland QA" }],
      }),
      pracujStatus: vi.fn().mockResolvedValue(status),
      pracujBindings: vi.fn().mockResolvedValue({ bindings: [] }),
      workerJobs: vi.fn().mockResolvedValue({ counts: {}, jobs: [] }),
      pracujSync: vi.fn().mockResolvedValue({ message: "queued" }),
      createPracujBinding: vi.fn().mockResolvedValue({ id: "binding-1" }),
    };
    const onStatus = vi.fn();
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client, onStatus });
    await controller.refresh();
    expect(root.textContent).toContain("Official JobAlert email");
    root.querySelector('[data-ingestion-action="pracuj-sync"]').click();
    await flush();
    expect(client.pracujSync).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenCalledWith("Pracuj mailbox sync queued.", "success");

    const form = root.querySelector("[data-pracuj-binding-form]");
    form.elements.subjectMatcher.value = "QA Krakow";
    form.elements.searchProfileId.value = "search-1";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(client.createPracujBinding).toHaveBeenCalledWith({
      subjectMatcher: "QA Krakow", searchProfileId: "search-1", enabled: true,
    });
    expect(JSON.stringify(controller.state)).not.toContain("must-never-leak");
  });
});
