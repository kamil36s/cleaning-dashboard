import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createJobhuntReviewController,
  renderFactInspector,
  renderReviewItems,
} from "../js/jobhunt-extraction.js";


const fact = {
  id: "fact-1", extractionRunId: "run-1", captureId: "capture-1",
  namespace: "job", type: "salary_min", sourceField: "minValue",
  sourceWording: "60000", valueType: "number", value: 60000,
  currency: "NOK", period: "month", requirementPreference: "unknown",
  state: "explicit_positive", confidence: 0.995,
  evidence: { kind: "json_ld_pointer", scriptIndex: 1, pointer: "/baseSalary/value/minValue" },
  validationState: "valid", normalizationState: "not_applicable", normalization: null,
};

const review = {
  id: "review-1", reason: "conflicting_salary", severity: "warning",
  entityType: "job", entityId: "job-1", relatedFactIds: ["fact-1"],
  evidenceSummary: "Two salary facts remain preserved.",
  candidateResolutions: [50000, 60000], state: "open", createdAt: "2026-09-18T12:00:00Z",
};

async function flush() {
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
}

describe("Job Hunt Pack E extraction and review UI", () => {
  beforeEach(() => { document.body.innerHTML = `<div id="root"></div>`; });

  it("renders fact values, evidence, extractor provenance, validation, and normalization safely", () => {
    const html = renderFactInspector({
      runs: [{ id: "run-1", extractorVersion: "json_ld_jobposting@1", status: "completed", factCount: 1, warningCount: 0 }],
      facts: [{ ...fact, sourceWording: "<img src=x onerror=alert(1)>", normalization: {
        conceptType: "skill", conceptKey: "SQL", ruleVersion: "normalization@1",
      }}],
      runVersions: { "run-1": "json_ld_jobposting@1" },
      projection: { outcome: "updated", canonicalJobId: "job-1", projectionVersion: 2 },
    });
    expect(html).toContain("json_ld_jobposting@1");
    expect(html).toContain("/baseSalary/value/minValue");
    expect(html).toContain("normalization@1");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).not.toContain("<img src=x");
  });

  it("renders review evidence and candidate values", () => {
    const html = renderReviewItems([review], { item: review, facts: [fact] });
    expect(html).toContain("conflicting salary");
    expect(html).toContain("Two salary facts remain preserved");
    expect(html).toContain("60000");
    expect(html).toContain("Human Override");
  });

  it("loads review detail and resolves with a bounded Human Override", async () => {
    const api = {
      reviews: vi.fn().mockResolvedValue({ items: [review] }),
      review: vi.fn().mockResolvedValue({ item: review, facts: [fact] }),
      resolveReview: vi.fn().mockResolvedValue({ item: { ...review, state: "resolved" } }),
      dismissReview: vi.fn(),
    };
    const root = document.getElementById("root");
    const controller = createJobhuntReviewController({ root, api });
    await controller.refresh();
    root.querySelector('[data-review-action="open"]').click();
    await flush();
    const form = root.querySelector("[data-review-override-form]");
    form.elements.field.value = "salary_min";
    form.elements.value.value = "55000";
    form.elements.reason.value = "Confirmed with recruiter";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(api.resolveReview).toHaveBeenCalledWith("review-1", {
      resolution: "Resolved with Human Override",
      override: { field: "salary_min", value: 55000, reason: "Confirmed with recruiter" },
    });
  });

  it("dismisses a review without creating an override", async () => {
    const api = {
      reviews: vi.fn().mockResolvedValue({ items: [review] }),
      review: vi.fn(), resolveReview: vi.fn(),
      dismissReview: vi.fn().mockResolvedValue({ item: { ...review, state: "dismissed" } }),
    };
    const root = document.getElementById("root");
    const controller = createJobhuntReviewController({ root, api });
    await controller.refresh();
    controller.state.detail = { item: review, facts: [fact] };
    controller.render();
    root.querySelector('[data-review-action="dismiss"]').click();
    await flush();
    expect(api.dismissReview).toHaveBeenCalledWith("review-1", { resolution: "Dismissed locally" });
    expect(api.resolveReview).not.toHaveBeenCalled();
  });
});
