import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJobhuntApi } from "../js/jobhunt-api.js";
import {
  createJobhuntDedupeController,
  renderDuplicateCandidate,
  renderDuplicateDetail,
  renderMergeHistoryItem,
} from "../js/jobhunt-dedupe.js";

function response(data, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ ok: status >= 200 && status < 300, data }),
  });
}

function candidate(overrides = {}) {
  return {
    id: "duplicate-1", state: "open", confidenceClass: "strong",
    ruleVersion: "dedupe@1", reasonCodes: ["company_title_location_time"],
    leftJob: { id: "job-a", company: "<img src=x>", title: "QA Engineer", city: "Oslo", country: "Norway" },
    rightJob: { id: "job-b", company: "Example", title: "QA Engineer", city: "Oslo", country: "Norway" },
    evidence: {
      sameCompany: true, titleSimilarity: 1, sameCity: true, sameCountry: true,
      publicationDeltaDays: 1, salaryCompatible: null, descriptionSimilarity: 0.91,
      exactSharedUrl: false,
    },
    hardContradictions: [],
    ...overrides,
  };
}

describe("Job Hunt Pack H duplicate review", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="root"></div>`;
    globalThis.confirm = vi.fn(() => true);
  });

  it("uses encoded narrow duplicate, merge, unmerge, scan, and summary routes", async () => {
    const fetchImpl = vi.fn((url) => response({ url }));
    const api = createJobhuntApi({ fetchImpl, baseUrl: "/api/jobhunt" });
    await api.duplicates({ state: "open", limit: 20 });
    await api.duplicate("duplicate / 1");
    await api.mergeDuplicate("duplicate-1", { confirm: true, survivorJobId: "job-a" });
    await api.markNotDuplicate("duplicate-1", { note: "separate" });
    await api.dismissDuplicate("duplicate-1", {});
    await api.dedupeMerges({ state: "active" });
    await api.dedupeMerge("merge / 1");
    await api.unmerge("merge-1", { note: "wrong" });
    await api.dedupeSummary();
    await api.dedupeScan("job / 1");
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "/api/jobhunt/duplicates?state=open&limit=20",
      "/api/jobhunt/duplicates/duplicate%20%2F%201",
      "/api/jobhunt/duplicates/duplicate-1/merge",
      "/api/jobhunt/duplicates/duplicate-1/not-duplicate",
      "/api/jobhunt/duplicates/duplicate-1/dismiss",
      "/api/jobhunt/dedupe/merges?state=active",
      "/api/jobhunt/dedupe/merges/merge%20%2F%201",
      "/api/jobhunt/dedupe/merges/merge-1/unmerge",
      "/api/jobhunt/dedupe/summary",
      "/api/jobhunt/jobs/job%20%2F%201/dedupe-scan",
    ]);
    expect(fetchImpl.mock.calls[2][1]).toMatchObject({ method: "POST" });
    expect(fetchImpl.mock.calls[7][1].body).toBe(JSON.stringify({ note: "wrong" }));
  });

  it("renders evidence, conflicts, applications, overrides, history, and escaped source content", () => {
    const html = renderDuplicateCandidate(candidate({
      hardContradictions: ["different_authoritative_source_ids"],
    }));
    expect(html).toContain("Title similarity");
    expect(html).toContain("Description similarity");
    expect(html).toContain("different_authoritative_source_ids");
    expect(html).toContain("&lt;img src=x&gt;");
    expect(html).not.toContain("<img src=x>");

    const detail = renderDuplicateDetail({
      evidenceCurrent: true,
      safety: { safe: false, survivorJobId: "job-a", blockers: ["both_applications_have_meaningful_history", "conflicting_active_human_overrides"] },
      comparison: {
        left: {
          job: { company: "Example", title: "QA", location: {}, salary: {} },
          application: { meaningful: true, status: "applied", eventCount: 3 },
          tracks: [{ trackId: "track-a", origin: "manual" }],
          overrides: [{ field: "company", replacement: "<script>bad</script>" }],
          sources: [{ source: "nav", externalId: "uuid-a", lifecycleState: "active", canonicalUrl: "https://example.test/a" }],
        },
        right: null,
      },
    });
    expect(detail).toContain("Meaningful history");
    expect(detail).toContain("both_applications_have_meaningful_history");
    expect(detail).toContain("&lt;script&gt;bad&lt;/script&gt;");
    expect(detail).not.toContain("<script>bad</script>");
    expect(renderMergeHistoryItem({
      id: "merge-1", state: "active", origin: "manual_user", ruleVersion: "dedupe@1",
      survivor: { company: "Example", title: "QA" }, absorbed: { company: "Copy", title: "QA" },
      reason: "Confirmed", mergedAt: "2026-09-23",
    })).toContain("Unmerge");
  });

  it("loads summary/list/history and blocks unsafe merge before mutation", async () => {
    const item = candidate();
    const client = {
      duplicates: vi.fn().mockResolvedValue({
        items: [item], summary: { openCandidates: 1, activeMerges: 0, sourceListings: 2, canonicalJobs: 2, rawCaptures: 2 },
      }),
      dedupeMerges: vi.fn().mockResolvedValue({ items: [], summary: {} }),
      duplicate: vi.fn().mockResolvedValue({
        candidate: item, evidenceCurrent: true,
        comparison: { left: null, right: null },
        safety: { safe: false, blockers: ["application conflict"], survivorJobId: "job-a" },
      }),
      mergeDuplicate: vi.fn(), markNotDuplicate: vi.fn(), dismissDuplicate: vi.fn(), unmerge: vi.fn(),
    };
    const onStatus = vi.fn();
    const controller = createJobhuntDedupeController({
      root: document.getElementById("root"), api: client, onStatus,
    });
    await controller.refresh();
    expect(document.body.textContent).toContain("1 open candidates");
    expect(document.body.textContent).toContain("Source Listings");
    await controller.act("merge", "duplicate-1");
    expect(client.mergeDuplicate).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith("Merge blocked: application conflict", "error");
  });
});

