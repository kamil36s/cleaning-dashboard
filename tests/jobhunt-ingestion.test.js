import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createJobhuntIngestionController,
  renderCaptureHistory,
  renderListingDetail,
  renderSourceStatus,
} from "../js/jobhunt-ingestion.js";

const source = {
  id: "source-manual", key: "manual", displayName: "Manual import", category: "manual",
  definitionState: "active", adapter: { key: "manual", version: "1.0.0", implemented: true },
  policy: { operationalState: "manual_only", accessMethod: "manual", enabled: true },
  listingCount: 1, captureCount: 2, collectionStatus: "Manual import available",
};
const externalSource = {
  id: "source-nav", key: "nav", displayName: "NAV", category: "job_board",
  definitionState: "planned", adapter: { key: null, version: null, implemented: false },
  policy: { operationalState: "planned", accessMethod: "unknown", enabled: false },
  listingCount: 0, captureCount: 0, collectionStatus: "Collection not implemented",
};
const listing = {
  id: "listing-1", source: { id: source.id, key: "manual", displayName: "Manual import" },
  externalId: "J1", observedUrl: "https://example.test/job/1", hints: { title: "QA <Lead>", company: "ACME", location: "Remote" },
  lifecycleState: "unknown", firstSeenAt: "2026-09-18T10:00:00Z", lastSeenAt: "2026-09-18T11:00:00Z",
  tracks: [{ id: "track-1", name: "QA Poland" }], searchProfiles: [{ id: "profile-1", name: "Manual QA" }], captureCount: 2,
};
const captures = [
  { id: "capture-2", listingId: "listing-1", sha256: "b".repeat(64), byteSize: 25, contentType: "text/html", capturedAt: "2026-09-18T11:00:00Z", changeState: "changed" },
  { id: "capture-1", listingId: "listing-1", sha256: "a".repeat(64), byteSize: 20, contentType: "text/html", capturedAt: "2026-09-18T10:00:00Z", changeState: "first" },
];

function api(overrides = {}) {
  return {
    sources: vi.fn().mockResolvedValue({ sources: [source, externalSource] }),
    sourceListings: vi.fn().mockResolvedValue({ listings: [listing] }),
    tracks: vi.fn().mockResolvedValue({ tracks: [{ id: "track-1", name: "QA Poland" }] }),
    track: vi.fn().mockResolvedValue({ track: { id: "track-1" }, searchProfiles: [{ id: "profile-1", name: "Manual QA" }] }),
    manualImport: vi.fn().mockResolvedValue({ listing, capture: captures[0], blobReused: false, parsingPerformed: false }),
    sourceListing: vi.fn().mockResolvedValue({ listing, captures }),
    rawCapture: vi.fn().mockResolvedValue({ capture: captures[0], content: "<img src=x onerror=alert(1)><b>raw</b>", rendering: "inert_text_only" }),
    captureExtractionRuns: vi.fn().mockResolvedValue({ runs: [] }),
    extractionFacts: vi.fn().mockResolvedValue({ facts: [] }),
    extractCapture: vi.fn().mockResolvedValue({
      runs: [{ id: "run-1", extractorVersion: "html_metadata@1", factCount: 1, warningCount: 0, status: "completed" }],
      projection: { outcome: "created", canonicalJobId: "job-1", projectionVersion: 1 },
    }),
    ingestionStorageHealth: vi.fn().mockResolvedValue({ healthy: true, uniqueBlobs: 2, totalRawBytes: 45, missingCount: 0, corruptCount: 0, orphanCount: 0 }),
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("Job Hunt Pack D ingestion UI", () => {
  beforeEach(() => { document.body.innerHTML = `<div id="root"></div>`; });

  it("renders source identity separately from operational and adapter status", () => {
    const html = renderSourceStatus([source, externalSource]);
    expect(html).toContain("Manual import available");
    expect(html).toContain("manual_only");
    expect(html).toContain("Collection not implemented");
    expect(html).toContain("Adapter: not implemented");
  });

  it("renders capture history and escapes archived HTML in the inert preview", () => {
    expect(renderCaptureHistory(captures)).toContain("changed");
    const html = renderListingDetail({ listing, captures }, {
      capture: captures[0], content: "<script>alert(1)</script>",
    });
    expect(html).toContain("QA &lt;Lead&gt;");
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(html).not.toContain("<script>alert(1)</script>");
  });

  it("loads sources and submits exact HTML without asking for parsing", async () => {
    const client = api();
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client });
    await controller.refresh();
    const form = root.querySelector("[data-manual-import-form]");
    expect([...form.elements.inputMode.options].map((option) => option.value)).toEqual(["text", "html", "json", "file"]);
    form.elements.inputMode.value = "html";
    form.elements.inputMode.dispatchEvent(new Event("change", { bubbles: true }));
    form.elements.content.value = "  <h1>Exact</h1>\n";
    form.elements.titleHint.value = "QA role";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(client.manualImport).toHaveBeenCalledWith(expect.objectContaining({
      inputMode: "html", contentType: "text/html", content: "  <h1>Exact</h1>\n",
      titleHint: "QA role",
    }));
    expect(controller.state.result.parsingPerformed).toBe(false);
    expect(root.textContent).toContain("No parsing was performed");
  });

  it("skips diagnostics for a planned source instead of surfacing a Not found failure", async () => {
    const jobbnorgeStatus = vi.fn().mockRejectedValue(new Error("Not found"));
    const client = api({
      sources: vi.fn().mockResolvedValue({ sources: [source, {
        id: "source-jobbnorge", key: "jobbnorge", displayName: "Jobbnorge",
        definitionState: "planned", adapter: { implemented: false }, policy: {},
      }] }),
      jobbnorgeStatus,
    });
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client });
    await controller.refresh();
    expect(jobbnorgeStatus).not.toHaveBeenCalled();
    expect(root.textContent).not.toContain("Not found");
    expect(controller.state.error).toBeNull();
  });

  it("opens listing history, previews capture safely, and checks health", async () => {
    const client = api();
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client });
    await controller.refresh();
    root.querySelector('[data-ingestion-action="listing"]').click();
    await flush();
    root.querySelector('[data-ingestion-action="capture"]').click();
    await flush();
    expect(root.querySelector(".jobhunt-capture-preview pre").textContent).toContain("<img src=x");
    expect(root.querySelector(".jobhunt-capture-preview img")).toBeNull();
    root.querySelector('[data-ingestion-action="health"]').click();
    await flush();
    expect(root.textContent).toContain("0 missing");
  });

  it("runs deterministic extraction and renders inspectable results", async () => {
    const client = api({
      captureExtractionRuns: vi.fn()
        .mockResolvedValueOnce({ runs: [] })
        .mockResolvedValueOnce({ runs: [{ id: "run-1", extractorVersion: "html_metadata@1", factCount: 1, warningCount: 0, status: "completed" }] }),
      extractionFacts: vi.fn().mockResolvedValue({ facts: [{
        id: "fact-1", extractionRunId: "run-1", captureId: "capture-2", type: "title",
        value: "QA role", sourceWording: "QA role", state: "explicit_positive", confidence: 0.9,
        evidence: { kind: "html_selector", pointer: "head > title" }, validationState: "valid",
      }] }),
    });
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client });
    await controller.refresh();
    root.querySelector('[data-ingestion-action="listing"]').click();
    await flush();
    root.querySelector('[data-ingestion-action="capture"]').click();
    await flush();
    root.querySelector('[data-ingestion-action="extract"]').click();
    await flush();
    expect(client.extractCapture).toHaveBeenCalledWith("capture-2");
    expect(root.textContent).toContain("html_metadata@1");
    expect(root.textContent).toContain("QA role");
    expect(root.textContent).not.toContain("AI");
  });

  it("shows API validation errors", async () => {
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({
      root, api: api({ manualImport: vi.fn().mockRejectedValue(new Error("Invalid URL")) }),
    });
    await controller.refresh();
    const form = root.querySelector("[data-manual-import-form]");
    form.elements.content.value = "raw";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(root.textContent).toContain("Invalid URL");
  });
});
