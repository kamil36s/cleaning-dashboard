import { describe, expect, it, vi } from "vitest";

import { renderJobhuntHome } from "../js/jobhunt-home.js";
import { filterJobhuntJobs, renderJobDetail } from "../js/jobhunt-jobs-view.js";
import { createJobhuntRouter, parseJobhuntHash } from "../js/jobhunt-router.js";
import { loadSourcesWorkspace, renderApplicationsWorkspace, renderSourcesWorkspace } from "../js/jobhunt-workspaces.js";

describe("Job Hunt product UX", () => {
  it("parses workspace, job, Track, and invalid deep links", () => {
    expect(parseJobhuntHash("#home")).toEqual({ workspace: "home", canonical: "home" });
    expect(parseJobhuntHash("#jobs/job%201")).toMatchObject({ workspace: "jobs", jobId: "job 1" });
    expect(parseJobhuntHash("#track/track-1/skills")).toMatchObject({ workspace: "tracks", trackId: "track-1", trackTab: "skills" });
    expect(parseJobhuntHash("#review/duplicates")).toMatchObject({ workspace: "review", reviewFilter: "duplicates" });
    expect(parseJobhuntHash("#does-not-exist")).toMatchObject({ workspace: "home", invalid: true });
  });

  it("preserves hash routes across navigation and back-compatible aliases", () => {
    const listeners = new Map();
    const fakeWindow = {
      location: { hash: "#job/job-9", pathname: "/jobhunt.html", search: "" },
      history: { replaceState: vi.fn() },
      addEventListener: vi.fn((name, callback) => listeners.set(name, callback)),
      removeEventListener: vi.fn(),
    };
    const onChange = vi.fn();
    const router = createJobhuntRouter({ windowObject: fakeWindow, onChange });
    router.start();
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ workspace: "jobs", jobId: "job-9" }));
    router.navigate("sources");
    expect(fakeWindow.location.hash).toBe("sources");
  });

  it("renders first-run Home and current Home without a global score", () => {
    const firstRun = renderJobhuntHome({
      firstRun: true,
      onboarding: [{ order: 1, title: "Complete your Career Profile", description: "Add evidence", href: "profile", complete: false }],
    });
    expect(firstRun).toContain("Complete your Career Profile");

    const current = renderJobhuntHome({
      firstRun: false,
      attention: { newJobs: 2, reviewItems: 1, followUpsDue: 1, jobsWithUnknowns: 3 },
      recentOpportunities: [{ id: "job-1", company: "ACME", role: "QA", evaluations: [{ trackName: "QA Poland", counts: { blockers: 0, gaps: 0, unknowns: 1, supportedRequired: 2 } }] }],
      tracks: [], sources: [],
    });
    expect(current).toContain("No blockers");
    expect(current).toContain("1 unknown");
    expect(current).not.toMatch(/\/100|Best match/i);
  });

  it("filters jobs by current history, Track blockers, unknowns, source, and search", () => {
    const jobs = [
      { id: "a", company: "ACME", role: "QA", status: "to_review", applicationStatus: "to_review", source: { name: "nav" }, location: { city: "Oslo", country: "NO", workMode: "hybrid" } },
      { id: "b", company: "Old", role: "Tester", status: "archived", applicationStatus: "archived", source: { name: "manual" }, location: { city: "Krakow", country: "PL", workMode: "onsite" } },
    ];
    const evaluations = new Map([["a", { counts: { blockers: 0, unknowns: 2 } }]]);
    expect(filterJobhuntJobs(jobs, { history: "current", trackId: "track", blockers: "none", unknowns: "present", source: "nav", search: "acme", workMode: "hybrid", stage: "all" }, evaluations).map((job) => job.id)).toEqual(["a"]);
    expect(filterJobhuntJobs(jobs, { history: "historical", stage: "all", source: "all", workMode: "all", blockers: "all", unknowns: "all" }, evaluations).map((job) => job.id)).toEqual(["b"]);
  });

  it("keeps evidence collapsed and distinguishes unknown from blocker in Job Detail", () => {
    const html = renderJobDetail({
      job: { id: "job-1", company: "ACME", role: "QA", location: {}, contract: {}, source: {}, requirements: {}, application: {} },
      application: { application: {}, events: [] },
      evaluations: { targets: [{ track: { id: "track", name: "QA Track" }, evaluation: { state: "current", counts: { blockers: 0, gaps: 0, unknowns: 2, supportedRequired: 1 } } }] },
    });
    expect(html).toContain("No blockers");
    expect(html).toContain("2 unknown");
    expect(html).toContain("Inspect source evidence");
    expect(html).not.toContain('class="jobhunt-evidence" open');
  });

  it("does not request a status route for an absent source and degrades one failing source independently", async () => {
    const apiWithoutJobbnorge = {
      sources: vi.fn().mockResolvedValue({ sources: [{ key: "nav", definitionState: "active", adapter: { implemented: true } }] }),
      navStatus: vi.fn().mockResolvedValue({ source: { policy: { enabled: true } }, tokenConfigured: true }),
      jobbnorgeStatus: vi.fn().mockRejectedValue(new Error("Not found")),
    };
    const first = await loadSourcesWorkspace(apiWithoutJobbnorge);
    expect(apiWithoutJobbnorge.jobbnorgeStatus).not.toHaveBeenCalled();
    expect(first.nav).toBeTruthy();

    const apiDegraded = {
      sources: vi.fn().mockResolvedValue({ sources: [
        { key: "nav", definitionState: "active", adapter: { implemented: true } },
        { key: "jobbnorge", definitionState: "active", adapter: { implemented: true } },
      ] }),
      navStatus: vi.fn().mockResolvedValue({ source: { policy: { enabled: true } }, tokenConfigured: true }),
      jobbnorgeStatus: vi.fn().mockRejectedValue(new Error("Jobbnorge status unavailable")),
    };
    const second = await loadSourcesWorkspace(apiDegraded);
    expect(second.nav).toBeTruthy();
    expect(second.errors.jobbnorge).toContain("unavailable");
    expect(renderSourcesWorkspace(second)).toContain("Source needs attention");
    const absentHtml = renderSourcesWorkspace(first);
    expect(absentHtml).toContain("Source unavailable");
    expect(absentHtml).not.toContain("Not found");

    const plannedApi = {
      sources: vi.fn().mockResolvedValue({ sources: [{ key: "jobbnorge", definitionState: "planned", adapter: { implemented: false } }] }),
      jobbnorgeStatus: vi.fn().mockRejectedValue(new Error("Not found")),
    };
    const planned = await loadSourcesWorkspace(plannedApi);
    expect(plannedApi.jobbnorgeStatus).not.toHaveBeenCalled();
    expect(renderSourcesWorkspace(planned)).toContain("Restart the dashboard service");
  });

  it("does not render unsafe original-source protocols", () => {
    const html = renderJobDetail({
      job: { id: "unsafe", company: "ACME", role: "QA", source: { url: "javascript:alert(1)" }, location: {}, contract: {}, requirements: {} },
      application: { application: {}, events: [] }, evaluations: { targets: [] },
    });
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("Open original source");
  });

  it("renders application stages as a pipeline without changing job facts", () => {
    const html = renderApplicationsWorkspace([{ id: "job", company: "ACME", role: "QA", applicationStatus: "applied", application: { followUpDate: "2026-09-30" }, nextAction: "follow_up" }]);
    expect(html).toContain("Applications and next actions");
    expect(html).toContain("Follow-up 2026-09-30");
    expect(html).toContain("data-application-job=\"job\"");
  });
});
