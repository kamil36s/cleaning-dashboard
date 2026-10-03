import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createJobhuntTracksController,
  parseTrackList,
  renderJobTrackAssignment,
  renderTrackDetail,
  renderTrackList,
} from "../js/jobhunt-tracks.js";

const tracks = [
  {
    id: "track-qa", slug: "qa-poland", name: "QA Poland", status: "exploring",
    purpose: "QA roles in Poland", geography: { countries: ["PL"], regionsCities: ["Kraków"], remoteAllowed: true, relocationRelevant: null, primaryCurrency: "PLN" },
    searchProfileCount: 4, assignedJobCount: 1, updatedAt: "2026-09-18T10:00:00Z",
  },
  {
    id: "track-no", slug: "norway-qa", name: "Norway QA", status: "active",
    purpose: "QA roles in Norway", geography: { countries: ["NO"], regionsCities: [], remoteAllowed: true, relocationRelevant: true, primaryCurrency: "NOK" },
    searchProfileCount: 5, assignedJobCount: 0, updatedAt: "2026-09-18T10:00:00Z",
  },
];

const detail = {
  track: tracks[0],
  searchProfiles: [{
    id: "profile-1", trackId: "track-qa", name: "Manual QA", status: "enabled",
    includeKeywords: ["manual QA"], excludeKeywords: ["manager"], roleIntent: "Manual testing",
    countries: ["PL"], regionsCities: ["Kraków"], workModels: ["hybrid"],
    scheduleHints: [], contractHints: ["UoP"], languageHints: ["English"],
    seniorityHints: ["mid"], plannedSourceKeys: ["pracuj"], notes: null,
  }],
  assignedJobs: [{ jobId: "job-1", company: "ACME", role: "Tester", location: { city: "Kraków", country: "PL" }, applicationStatus: "to_review" }],
  assignmentMeaning: "Relevant, not fit.",
};

const evaluationPolicy = {
  id: "policy-1", trackId: "track-qa", version: 1,
  fingerprint: `sha256:${"a".repeat(64)}`, origin: "seed", createdAt: "2026-09-18T10:00:00Z",
  policy: {
    schemaVersion: "track-evaluation-policy@1",
    dimensions: Object.fromEntries(["skills", "experience", "compensation", "geography", "preferences"].map((key) => [key, { enabled: true, importance: key === "skills" ? "primary" : "secondary" }])),
    blockers: { compensation: true, trackGeography: true, workModel: true, contract: true, schedule: true, relocation: true, language: false },
    skillThresholds: { partialMin: 1, supportedMin: 3 }, unknownHandling: "preserve", aggregate: "none",
  },
};

function client(overrides = {}) {
  return {
    tracks: vi.fn().mockResolvedValue({ tracks: structuredClone(tracks) }),
    track: vi.fn().mockResolvedValue(structuredClone(detail)),
    createTrack: vi.fn().mockResolvedValue({ track: tracks[0] }),
    updateTrack: vi.fn().mockResolvedValue({ track: tracks[0] }),
    createSearchProfile: vi.fn().mockResolvedValue({ searchProfile: detail.searchProfiles[0] }),
    updateSearchProfile: vi.fn().mockResolvedValue({ searchProfile: detail.searchProfiles[0] }),
    jobTracks: vi.fn().mockResolvedValue({
      jobId: "job-1", assignmentMeaning: "Relevant to a Track; not a fit score.",
      tracks: tracks.map((track, index) => ({ trackId: track.id, name: track.name, trackStatus: track.status, assigned: index === 0 })),
    }),
    setJobTracks: vi.fn().mockResolvedValue({ tracks: [] }),
    trackEvaluationPolicy: vi.fn().mockResolvedValue({ policy: structuredClone(evaluationPolicy) }),
    trackEvaluationPolicyHistory: vi.fn().mockResolvedValue({ items: [structuredClone(evaluationPolicy)] }),
    trackEvaluations: vi.fn().mockResolvedValue({ items: [] }),
    createTrackEvaluationPolicy: vi.fn().mockResolvedValue({ policy: { ...evaluationPolicy, version: 2 } }),
    trackSkillIntelligence: vi.fn().mockResolvedValue({
      track: { id: "track-qa", name: "QA Poland", status: "active" },
      population: { mode: "current", window: "current", canonicalJobDenominator: 0, semantics: "Active deduplicated jobs.", timeAnchorHierarchy: [], fingerprint: "sha256:population" },
      coverage: { totalJobs: 0, jobsWithSkillEvidence: 0, jobsWithoutSkillEvidence: 0, jobsWithCurrentEvaluations: 0, jobsMissingCurrentEvaluations: 0, staleEvaluationPointers: 0 },
      versions: { skillIntelligence: "skill-intelligence@1", mappingRuleVersions: [], mappingFingerprint: "sha256:mapping" },
      priorityPolicy: { minimumPopulation: 5, minimumSkillEvidenceCoverage: 0.4, minimumEvaluationCoverage: 0.4 },
      skills: [], strengths: [], unknownProfileAreas: [], unmapped: { terms: [] }, generatedAt: "2026-09-24T00:00:00Z",
    }),
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("Job Hunt Career Tracks UI", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="tracks"></div><div id="assignment" data-job-id="job-1"></div>`;
  });

  it("renders Track cards, seeded counts, statuses, and empty state", () => {
    const html = renderTrackList(tracks);
    expect(html).toContain("QA Poland");
    expect(html).toContain("4</strong> search profiles");
    expect(html).toContain("Norway QA");
    expect(renderTrackList([])).toContain("No Career Tracks yet");
  });

  it("deduplicates practical comma-separated editor values", () => {
    expect(parseTrackList("QA, testing, qa, , UAT")).toEqual(["QA", "testing", "UAT"]);
  });

  it("renders Search Profile criteria, source hints, and assigned jobs", () => {
    const html = renderTrackDetail(detail, "profile-1");
    expect(html).toContain("Manual QA");
    expect(html).toContain("Include: manual QA");
    expect(html).toContain("Discovery sources");
    expect(html).toContain("Pracuj - available");
    expect(html).toContain('value="pracuj" checked');
    expect(html).toContain("ACME — Tester");
    expect(html).toContain("not suitable or a good fit");
  });

  it("loads Tracks, edits a Track, and changes lifecycle status", async () => {
    const api = client();
    const root = document.getElementById("tracks");
    const controller = createJobhuntTracksController({ root, api });
    await controller.refresh();
    root.querySelector('[data-track-action="edit"]').click();
    const form = root.querySelector("[data-track-form]");
    form.elements.name.value = "QA Poland Updated";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(api.updateTrack).toHaveBeenCalledWith("track-qa", expect.objectContaining({ name: "QA Poland Updated" }));

    root.querySelector('[data-track-action="status"][data-track-status="paused"]').click();
    await flush();
    expect(api.updateTrack).toHaveBeenCalledWith("track-qa", { status: "paused" });
  });

  it("opens a Track and creates a structured Search Profile", async () => {
    const api = client();
    const root = document.getElementById("tracks");
    const controller = createJobhuntTracksController({ root, api });
    await controller.refresh();
    root.querySelector('[data-track-action="open"]').click();
    await flush();
    const form = root.querySelector("[data-search-profile-form]");
    form.elements.name.value = "Technical QA";
    form.elements.includeKeywords.value = "API, Postman";
    form.querySelector('input[name="plannedSourceKeys"][value="nofluffjobs"]').checked = true;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(api.createSearchProfile).toHaveBeenCalledWith("track-qa", expect.objectContaining({
      name: "Technical QA", includeKeywords: ["API", "Postman"],
      plannedSourceKeys: expect.arrayContaining(["nofluffjobs"]),
    }));
  });

  it("assigns one job to several Tracks and labels the meaning", async () => {
    const api = client();
    const root = document.getElementById("tracks");
    const target = document.getElementById("assignment");
    const controller = createJobhuntTracksController({ root, api });
    await controller.mountJobAssignments(target, "job-1");
    expect(renderJobTrackAssignment(await api.jobTracks())).toContain("not a fit score");
    target.querySelector('input[value="track-no"]').checked = true;
    target.querySelector("[data-job-track-form]").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(api.setJobTracks).toHaveBeenCalledWith("job-1", ["track-qa", "track-no"], { note: null });
  });

  it("loads Evaluation policy/history and saves a new immutable policy version", async () => {
    const api = client();
    const root = document.getElementById("tracks");
    const controller = createJobhuntTracksController({ root, api });
    await controller.refresh();
    root.querySelector('[data-track-action="open"]').click();
    await flush();
    expect(root.textContent).toContain("Evaluation Policy");
    expect(root.textContent).toContain("Policy history (1)");
    expect(root.textContent).toContain("No hidden composite or percentage");

    const form = root.querySelector("[data-evaluation-policy-form]");
    form.elements.supportedMin.value = "4";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(api.createTrackEvaluationPolicy).toHaveBeenCalledWith(
      "track-qa",
      expect.objectContaining({
        schemaVersion: "track-evaluation-policy@1",
        skillThresholds: { partialMin: 1, supportedMin: 4 },
        aggregate: "none",
      }),
    );
  });

  it("loads Track Skill Intelligence and reloads a bounded historical window", async () => {
    const api = client();
    const root = document.getElementById("tracks");
    const controller = createJobhuntTracksController({ root, api });
    await controller.refresh();
    root.querySelector('[data-track-action="open"]').click();
    await flush();
    expect(root.textContent).toContain("Skill Intelligence");
    expect(root.textContent).toContain("Current active jobs");
    expect(api.trackSkillIntelligence).toHaveBeenCalledWith("track-qa", {
      population: "current", window: "90d", sort: "priority",
    });
    const selector = root.querySelector("[data-skill-window]");
    selector.value = "30d";
    selector.dispatchEvent(new Event("change", { bubbles: true }));
    await flush();
    expect(api.trackSkillIntelligence).toHaveBeenLastCalledWith("track-qa", {
      population: "historical", window: "30d", sort: "priority",
    });
  });

  it("shows an explicit Track API error", async () => {
    const root = document.getElementById("tracks");
    const controller = createJobhuntTracksController({ root, api: client({ tracks: vi.fn().mockRejectedValue(new Error("Tracks unavailable")) }) });
    await controller.refresh();
    expect(root.textContent).toContain("Tracks unavailable");
  });
});
