import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  mountJobEvaluations,
  policyFromForm,
  renderEvaluation,
  renderJobEvaluationPanel,
  renderPolicyEditor,
  renderTrackEvaluations,
} from "../js/jobhunt-evaluations.js";

const finding = (status, label, dimension = "skills") => ({
  id: `finding-${status}-${label}`,
  dimension,
  type: status === "unknown" ? "unknown_requirement" : status,
  status,
  importance: "primary",
  requirementClass: "required",
  conceptKey: label.toLowerCase(),
  jobFactIds: ["fact-1"],
  jobEvidence: [{ type: "extracted_fact", id: "fact-1", sourceWording: `${label} required` }],
  profileEvidence: status === "unknown" ? [] : [{ type: "skills", id: "skill-1" }],
  policyEvidence: { policyId: "policy-1", policyVersion: 2, path: "skillThresholds" },
  explanationCode: `${dimension}_${status}`,
  display: { label, summary: `${label} has state ${status}.` },
});

const evaluation = {
  id: "evaluation-1",
  jobId: "job-1",
  trackId: "track-1",
  trackName: "QA Poland",
  job: { company: "ACME", role: "QA Engineer" },
  state: "current",
  profileRevision: 4,
  projectionVersion: 3,
  policyVersion: 2,
  evaluatorVersion: "evaluator@1",
  inputFingerprint: `sha256:${"a".repeat(64)}`,
  counts: { blockers: 1, gaps: 0, unknowns: 1 },
  dimensions: [
    { dimension: "skills", state: "unknown", importance: "primary" },
    { dimension: "geography", state: "blocker", importance: "primary" },
  ],
  findings: [
    finding("unknown", "SQL"),
    finding("blocker", "Geography", "geography"),
  ],
  createdAt: "2026-09-23T10:00:00Z",
};

const policy = {
  id: "policy-2",
  trackId: "track-1",
  version: 2,
  fingerprint: `sha256:${"b".repeat(64)}`,
  origin: "user",
  createdAt: "2026-09-23T10:00:00Z",
  policy: {
    schemaVersion: "track-evaluation-policy@1",
    dimensions: {
      skills: { enabled: true, importance: "primary" },
      experience: { enabled: true, importance: "primary" },
      compensation: { enabled: true, importance: "secondary" },
      geography: { enabled: true, importance: "primary" },
      preferences: { enabled: true, importance: "secondary" },
    },
    blockers: {
      compensation: true, trackGeography: true, workModel: true,
      contract: true, schedule: true, relocation: true, language: false,
    },
    skillThresholds: { partialMin: 1, supportedMin: 3 },
    unknownHandling: "preserve",
    aggregate: "none",
  },
};

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("Job Hunt Pack J Evaluation UI", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="target" data-job-id="job-1"></div>`;
  });

  it("renders categorical dimensions, prominent blockers, unknowns, and inspectable evidence", () => {
    const html = renderEvaluation(evaluation);
    expect(html).toContain("is-blocker");
    expect(html).toContain("is-unknown");
    expect(html).toContain("Inspect evidence");
    expect(html).toContain("fact-1");
    expect(html).toContain("policyVersion");
    expect(html).toContain("Profile revision");
    expect(html).not.toMatch(/\d+%/);
    expect(html).not.toContain("/100");
  });

  it("renders Track-specific current and historical Evaluations without a magic score", () => {
    const html = renderJobEvaluationPanel({
      targets: [{
        track: { id: "track-1", name: "QA Poland" },
        evaluation,
        basis: { sources: [{ type: "track_assignment" }] },
      }],
      history: [{ ...evaluation, state: "historical" }],
    });
    expect(html).toContain("Career Profile × Canonical Job × Track");
    expect(html).toContain("No global percentage");
    expect(html).toContain("Historical");
    expect(html).toContain("Re-evaluate current inputs");
    expect(html).not.toContain("Match score");
  });

  it("mounts a Job Evaluation and supports explicit deterministic re-evaluation", async () => {
    const api = {
      jobEvaluations: vi.fn().mockResolvedValue({
        targets: [{ track: { id: "track-1", name: "QA Poland" }, evaluation, basis: { sources: [] } }],
        history: [],
      }),
      evaluateJobTrack: vi.fn().mockResolvedValue({ evaluation, reused: false }),
    };
    const status = vi.fn();
    const target = document.getElementById("target");
    await mountJobEvaluations(target, "job-1", api, status);
    target.querySelector("[data-evaluate-track]").click();
    await flush();
    expect(api.evaluateJobTrack).toHaveBeenCalledWith("job-1", "track-1");
    expect(status).toHaveBeenCalledWith("Evaluation completed.", "success");
    expect(api.jobEvaluations).toHaveBeenCalledTimes(2);
  });

  it("renders and serializes a bounded versioned policy editor and history", () => {
    const html = renderPolicyEditor(policy, [policy, { ...policy, id: "policy-1", version: 1, origin: "seed" }]);
    document.getElementById("target").innerHTML = html;
    const form = document.querySelector("[data-evaluation-policy-form]");
    form.querySelector('[name="importance:skills"]').value = "informational";
    form.querySelector('[name="blocker"][value="language"]').checked = true;
    form.elements.partialMin.value = "2";
    form.elements.supportedMin.value = "4";
    const parsed = policyFromForm(form);
    expect(parsed.schemaVersion).toBe("track-evaluation-policy@1");
    expect(parsed.dimensions.skills).toEqual({ enabled: true, importance: "informational" });
    expect(parsed.blockers.language).toBe(true);
    expect(parsed.skillThresholds).toEqual({ partialMin: 2, supportedMin: 4 });
    expect(parsed.aggregate).toBe("none");
    expect(html).toContain("Policy history (2)");
    expect(html).toContain("Version 2");
  });

  it("filters Track Evaluations by blocker, unknown, skill gap, and current state", () => {
    const clean = {
      ...evaluation,
      id: "evaluation-clean",
      jobId: "job-clean",
      job: { company: "Clean", role: "Tester" },
      counts: { blockers: 0, gaps: 0, unknowns: 0 },
      findings: [],
    };
    const data = { items: [evaluation, clean] };
    expect(renderTrackEvaluations(data, "blockers")).toContain("ACME");
    expect(renderTrackEvaluations(data, "blockers")).not.toContain("Clean");
    expect(renderTrackEvaluations(data, "no-blockers")).toContain("Clean");
    expect(renderTrackEvaluations(data, "unknowns")).toContain("ACME");
    expect(renderTrackEvaluations(data, "current")).toContain("ACME");
  });
});
