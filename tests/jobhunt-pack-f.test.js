import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderFactInspector } from "../js/jobhunt-extraction.js";
import { createJobhuntIngestionController, renderListingDetail } from "../js/jobhunt-ingestion.js";


const listing = {
  id: "listing-1", source: { id: "source-manual", key: "manual", displayName: "Manual import" },
  externalId: "F1", observedUrl: null, hints: { title: "QA Engineer", company: "ACME", location: "Remote" },
  lifecycleState: "unknown", firstSeenAt: "2026-09-23T10:00:00Z", lastSeenAt: "2026-09-23T10:00:00Z",
  tracks: [], searchProfiles: [], captureCount: 1,
};
const capture = {
  id: "capture-1", listingId: "listing-1", sha256: "a".repeat(64), byteSize: 40,
  contentType: "text/plain", capturedAt: "2026-09-23T10:00:00Z", changeState: "first",
};
const deterministicRun = {
  id: "run-det", extractorKind: "manual_hints", extractorVersion: "manual_hints@1",
  status: "completed", factCount: 1, warningCount: 0,
};
const aiRun = {
  id: "run-ai", extractorKind: "ai", extractorVersion: "ai_factual@1",
  status: "completed", factCount: 1, warningCount: 0,
  ai: {
    provider: "fake", model: "fake-job-facts", promptVersion: "1.0.0", latencyMs: 12,
    attemptCount: 1, usage: { inputTokens: 20, outputTokens: 10, totalTokens: 30 },
  },
};
const aiFact = {
  id: "fact-ai", extractionRunId: "run-ai", captureId: "capture-1", namespace: "job",
  type: "skill", sourceField: "ai:skill", sourceWording: "SQL <required>", valueType: "text",
  value: "SQL", requirementPreference: "required", state: "explicit_positive", confidence: 0.9,
  evidence: { kind: "ai_text_span", start: 10, end: 22, quote: "SQL <required>" },
  validationState: "valid", normalizationState: "mapped",
  extractor: { kind: "ai", version: "ai_factual@1", provider: "fake", model: "fake-job-facts", promptVersion: "1.0.0" },
};

function api(overrides = {}) {
  return {
    sources: vi.fn().mockResolvedValue({ sources: [] }),
    sourceListings: vi.fn().mockResolvedValue({ listings: [listing] }),
    tracks: vi.fn().mockResolvedValue({ tracks: [] }),
    track: vi.fn(),
    aiStatus: vi.fn().mockResolvedValue({ configured: true, provider: "fake", model: "fake-job-facts" }),
    sourceListing: vi.fn().mockResolvedValue({ listing, captures: [capture] }),
    rawCapture: vi.fn().mockResolvedValue({ capture, content: "QA Engineer. SQL is required." }),
    captureExtractionRuns: vi.fn().mockResolvedValue({ runs: [deterministicRun] }),
    extractionFacts: vi.fn().mockImplementation((id) => Promise.resolve({
      facts: id === "run-ai" ? [aiFact] : [{
        id: "fact-det", extractionRunId: "run-det", type: "title", value: "QA Engineer",
        sourceWording: "QA Engineer", state: "explicit_positive", confidence: 0.96,
        evidence: { kind: "submitted_field" }, validationState: "valid",
        extractor: { kind: "manual_hints", version: "manual_hints@1" },
      }],
    })),
    extractCapture: vi.fn().mockResolvedValue({ runs: [deterministicRun], projection: { outcome: "created" } }),
    aiExtractCapture: vi.fn().mockResolvedValue({ run: aiRun, projection: { outcome: "updated" } }),
    ingestionStorageHealth: vi.fn(), manualImport: vi.fn(),
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("Job Hunt Pack F AI extraction UI", () => {
  beforeEach(() => { document.body.innerHTML = `<div id="root"></div>`; });

  it("labels AI facts and displays provider, model, prompt, usage, evidence, and escaped wording", () => {
    const html = renderFactInspector({ runs: [deterministicRun, aiRun], facts: [aiFact], showAi: true });
    expect(html).toContain("DETERMINISTIC");
    expect(html).toContain("AI");
    expect(html).toContain("fake-job-facts");
    expect(html).toContain("30 total tokens");
    expect(html).toContain("ai_text_span");
    expect(html).toContain("SQL &lt;required&gt;");
    expect(html).not.toContain("SQL <required>");
  });

  it("shows the explicit unavailable state without hiding deterministic extraction", () => {
    const html = renderListingDetail(
      { listing, captures: [capture] }, { capture, content: "QA Engineer" },
      { runs: [deterministicRun], facts: [], showAi: true },
      { configured: false },
    );
    expect(html).toContain("AI extraction unavailable — provider not configured");
    expect(html).toContain("Run deterministic extraction");
    expect(html).not.toContain("data-ingestion-action=\"ai-extract\"");
  });

  it("shows loading then success, sends only force, and retains extraction history", async () => {
    let resolveAI;
    const pending = new Promise((resolve) => { resolveAI = resolve; });
    const client = api({
      aiExtractCapture: vi.fn().mockReturnValue(pending),
      captureExtractionRuns: vi.fn()
        .mockResolvedValueOnce({ runs: [deterministicRun] })
        .mockResolvedValueOnce({ runs: [aiRun, deterministicRun] }),
    });
    const statuses = [];
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({
      root, api: client, onStatus: (...args) => statuses.push(args),
    });
    await controller.refresh();
    root.querySelector('[data-ingestion-action="listing"]').click();
    await flush();
    root.querySelector('[data-ingestion-action="capture"]').click();
    await flush();
    root.querySelector('[data-ingestion-action="ai-extract"]').click();
    expect(root.textContent).toContain("Running AI extraction");
    resolveAI({ run: aiRun, projection: { outcome: "updated" } });
    await flush();
    expect(client.aiExtractCapture).toHaveBeenCalledWith("capture-1", { force: false });
    expect(root.textContent).toContain("fake-job-facts");
    expect(root.textContent).toContain("QA Engineer");
    expect(statuses.at(-1)).toEqual(["AI extraction completed: 1 validated fact(s).", "success"]);
  });

  it("renders a failed AI run while deterministic history remains available", async () => {
    const failedRun = {
      ...aiRun, status: "failed", factCount: 0, errorMessage: "Provider timed out",
      ai: { ...aiRun.ai, attemptCount: 2 },
    };
    const client = api({
      aiExtractCapture: vi.fn().mockResolvedValue({ run: failedRun, projection: null }),
      captureExtractionRuns: vi.fn()
        .mockResolvedValueOnce({ runs: [deterministicRun] })
        .mockResolvedValueOnce({ runs: [failedRun, deterministicRun] }),
    });
    const statuses = [];
    const root = document.getElementById("root");
    const controller = createJobhuntIngestionController({ root, api: client, onStatus: (...args) => statuses.push(args) });
    await controller.refresh();
    root.querySelector('[data-ingestion-action="listing"]').click(); await flush();
    root.querySelector('[data-ingestion-action="capture"]').click(); await flush();
    root.querySelector('[data-ingestion-action="ai-extract"]').click(); await flush();
    expect(root.textContent).toContain("manual_hints@1");
    expect(root.textContent).toContain("failed");
    expect(statuses.at(-1)).toEqual(["AI extraction failed: Provider timed out.", "error"]);
  });
});
