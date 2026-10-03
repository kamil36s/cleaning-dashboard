import { beforeEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  initializeJobhuntAuthority: vi.fn(),
  overview: vi.fn(),
}));

vi.mock("../js/jobhunt-api.js", () => ({
  initializeJobhuntAuthority: backend.initializeJobhuntAuthority,
  jobhuntApi: { overview: backend.overview },
}));

async function flushWidget() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("Job Hunt dashboard widget", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    document.body.innerHTML = `
      <section id="jobhunt-card">
        <div id="jobhunt-root"></div>
      </section>
    `;
  });

  it("renders current opportunities, review, and follow-up signals after cutover", async () => {
    backend.initializeJobhuntAuthority.mockResolvedValue({ mode: "api" });
    backend.overview.mockResolvedValue({
      summary: {
        total: 3,
        worthApplying: 2,
        appliedThisWeek: 1,
        followUpsDue: 1,
        expired: 1,
        bestMatchScore: 88,
        bestMatch: {
          id: "job_1",
          company: "ACME",
          role: "QA Analyst",
          status: "worth_applying",
          expiresAt: null,
          branding: { logoDataUrl: "" },
          match: { score: 88 },
        },
        nextAction: { title: "Send follow-up to ACME - QA Analyst" },
      },
      home: {
        firstRun: false,
        attention: { newJobs: 3, reviewItems: 2, duplicateCandidates: 0, followUpsDue: 1 },
        recentOpportunities: [{
          id: "job_1", company: "ACME", role: "QA Analyst",
          evaluations: [{ trackName: "Norway QA", counts: { blockers: 0, unknowns: 1 } }],
        }],
        sources: [],
      },
    });

    await import("../js/widget-jobhunt.js?test=api-overview");
    await flushWidget();

    const text = document.getElementById("jobhunt-root").textContent;
    expect(text).toContain("QA Analyst · ACME");
    expect(text).toContain("Norway QA · blocker-free · 1 unknown");
    expect(text).toContain("2need review");
    expect(text).not.toContain("88/100");
    expect(text).not.toContain("Best match");
    expect(backend.overview).toHaveBeenCalledTimes(1);
  });

  it("shows first-run guidance instead of a zero dashboard", async () => {
    backend.initializeJobhuntAuthority.mockResolvedValue({ mode: "api" });
    backend.overview.mockResolvedValue({ home: { firstRun: true } });

    await import("../js/widget-jobhunt.js?test=first-run");
    await flushWidget();

    const text = document.getElementById("jobhunt-root").textContent;
    expect(text).toContain("Set up your profile and choose a Track");
    expect(text).not.toContain("0/100");
  });

  it("keeps saved opportunities visible when one source is degraded", async () => {
    backend.initializeJobhuntAuthority.mockResolvedValue({ mode: "api" });
    backend.overview.mockResolvedValue({
      home: {
        firstRun: false,
        attention: { newJobs: 1, reviewItems: 0, duplicateCandidates: 0, followUpsDue: 0 },
        recentOpportunities: [{ id: "job_2", company: "Safe Co", role: "Tester", evaluations: [] }],
        sources: [{ name: "NAV / Arbeidsplassen", actionRequired: true }],
      },
    });

    await import("../js/widget-jobhunt.js?test=degraded");
    await flushWidget();

    const text = document.getElementById("jobhunt-root").textContent;
    expect(text).toContain("Tester · Safe Co");
    expect(text).toContain("NAV / Arbeidsplassen needs attention");
    expect(text).toContain("Existing jobs are still available");
  });

  it("shows an explicit unavailable state after SQLite cutover", async () => {
    backend.initializeJobhuntAuthority.mockResolvedValue({ mode: "unavailable" });

    await import("../js/widget-jobhunt.js?test=unavailable");
    await flushWidget();

    expect(document.getElementById("jobhunt-root").textContent).toContain("SQLite is authoritative");
    expect(backend.overview).not.toHaveBeenCalled();
  });
});
