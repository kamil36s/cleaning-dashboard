import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJobhuntApi } from "../js/jobhunt-api.js";
import {
  createJobhuntInsightsController,
  renderApplicationAnalytics,
  renderCareerIntelligence,
  renderExperiments,
  renderMarketAnalytics,
  renderSourceAnalytics,
  renderTrackAnalytics,
  renderTradeoffMatrix,
} from "../js/jobhunt-insights.js";
import { parseJobhuntHash } from "../js/jobhunt-router.js";

const tracks = [
  { id: "track-pl", name: "QA Poland" },
  { id: "track-no", name: "Norway QA" },
];

describe("Job Hunt Pack M UI", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="root"></div>`;
  });

  it("routes Insights sections and the Track Analytics tab", () => {
    expect(parseJobhuntHash("#insights/market")).toMatchObject({ workspace: "insights", insightsTab: "market" });
    expect(parseJobhuntHash("#insights/experiments")).toMatchObject({ workspace: "insights", insightsTab: "experiments" });
    expect(parseJobhuntHash("#insights/not-real")).toMatchObject({ workspace: "insights", insightsTab: "market" });
    expect(parseJobhuntHash("#track/track-1/analytics")).toMatchObject({ workspace: "tracks", trackTab: "analytics" });
  });

  it("renders market populations, coverage, salary insufficiency, and Pack K link", () => {
    const html = renderMarketAnalytics({
      filters: { window: "90d" },
      populations: { observed: { denominator: 4 }, current: { denominator: 3 } },
      flow: { newLast7Days: 2, trend: [{ period: "2026-09-21", count: 2, granularity: "week" }] },
      coverage: {
        salary: { label: "Salary", known: 2, unknown: 2, denominator: 4 },
        workModel: { label: "Work model", known: 3, unknown: 1, denominator: 4 },
      },
      salary: {
        knownJobs: 2, unknownJobs: 2, denominator: 4,
        groups: [{ currency: "PLN", period: "month", taxType: "gross", count: 2, denominator: 4, status: "insufficient_salary_evidence", minimumSample: 3, minimumObserved: 10000, maximumObserved: 12000 }],
      },
      companies: { items: [{ company: "<Unsafe>", jobs: 2, denominator: 4 }] },
      geography: { countries: [{ value: "Poland", count: 3, denominator: 4 }] },
      workModels: [{ value: "hybrid", count: 2, denominator: 4 }],
      contractTypes: [{ value: "UoP", count: 1, denominator: 4 }],
      requirements: [{ type: "language", jobsWithEvidence: 2, denominator: 4 }],
      skillIntelligence: { href: "/api/jobhunt/tracks/track-pl/skills/intelligence" },
    });
    expect(html).toContain("Observed canonical jobs");
    expect(html).toContain("2 known");
    expect(html).toContain("2 unknown / 4 total");
    expect(html).toContain("Not shown");
    expect(html).toContain("No outliers are removed");
    expect(html).toContain("Open detailed Pack K skill demand");
    expect(html).not.toContain("<Unsafe>");
    expect(html).toContain("&lt;Unsafe&gt;");
  });

  it("renders source and application denominators rather than unlabeled percentages", () => {
    const sources = renderSourceAnalytics({ sources: [{
      displayName: "NAV", sourceKey: "nav", listingsDiscovered: 10,
      population: { denominator: 10 }, canonicalJobsContributed: 7,
      uniqueContribution: 4, unlinkedListings: 1,
      duplicateRate: { numerator: 2, denominator: 9, percent: 22.2 },
      duplicateOverlap: { numerator: 3, denominator: 7, percent: 42.9 },
      reviewBurden: { reviewItems: 2, per100Listings: 20 },
      requests: { succeeded: 9, failed: 1 }, health: { operationalState: "healthy" },
    }] });
    expect(sources).toMatch(/22[,.]2% \(2\/9\)/);
    expect(sources).toMatch(/42[,.]9% \(3\/7\)/);
    expect(sources).toContain("Review burden");

    const applications = renderApplicationAnalytics({
      filters: { window: "180d" }, population: { denominator: 5 },
      rates: {
        response: { numerator: 3, denominator: 5, percent: 60, lowSample: false },
        interview: { numerator: 2, denominator: 5, percent: 40 },
        offer: { numerator: 1, denominator: 5, percent: 20 },
      },
      funnel: { applied: 5, interview: 2, offer: 1, rejected: 1 },
      timing: { timeToFirstResponseDays: { median: 4, sample: 3, censored: 2 } },
      byTrack: [{ trackId: "track-pl", applications: 5, responses: 3, interviews: 2, offers: 1 }],
      byDiscoverySource: [{ source: "manual", applications: 5, responses: 3, interviews: 2, offers: 1 }],
      outcomeReasons: [], definitions: { trackAttribution: "Captured at application time." },
    });
    expect(applications).toContain("60% (3/5)");
    expect(applications).toContain("3 measured; 2 censored");
    expect(applications).toContain("By discovery source");
  });

  it("renders a 2-5 Track matrix with explicit scenario uncertainty and no winner", () => {
    const html = renderTradeoffMatrix({ tracks: [{
      track: { id: "track-pl", name: "QA Poland", currency: "PLN" },
      currentJobs: 8, observedJobs: 20,
      salaryEvidence: { currency: "PLN", count: 2, status: "insufficient_salary_evidence" },
      estimatedNetMonthly: null, monthlyLivingCosts: null,
      estimatedMonthlyRemainder: null, estimatedRemainderInBaseCurrency: null,
      requiredSkillGaps: 3, evaluationUnknowns: 4,
      evaluationUnknownRate: { numerator: 2, denominator: 5, percent: 40 },
      languageRequirements: [], languageRequirementCoverage: { unknown: 6, denominator: 8 },
      relocationRequired: false,
      uncertainty: ["net estimate unavailable", "living-cost assumptions incomplete"],
      economicScenario: null,
    }, {
      track: { id: "track-no", name: "Norway QA", currency: "NOK" },
      currentJobs: 4, observedJobs: 12, salaryEvidence: null,
      estimatedNetMonthly: null, monthlyLivingCosts: null,
      estimatedMonthlyRemainder: null, estimatedRemainderInBaseCurrency: null,
      requiredSkillGaps: 1, evaluationUnknowns: 2,
      evaluationUnknownRate: { numerator: 1, denominator: 3, percent: 33.3 },
      languageRequirements: [{ value: "Norwegian B2", jobCount: 2, denominator: 4 }],
      languageRequirementCoverage: { unknown: 2, denominator: 4 },
      relocationRequired: true, uncertainty: ["manual FX assumption unavailable"],
      economicScenario: null,
    }], winner: null }, tracks, ["track-pl", "track-no"]);
    expect(html).toContain("Compare 2-5 Tracks");
    expect(html).toContain("No winner or aggregate career score");
    expect(html).toContain("living-cost assumptions incomplete");
    expect(html).toContain("Norwegian B2 (2/4)");
    expect(html).toContain("Save new scenario version");
    expect(html).not.toContain("Winner =");
  });

  it("renders Track analytics, explainable adjacency, experiment states, and escapes evidence", () => {
    const trackHtml = renderTrackAnalytics({
      window: "90d", market: { populations: { current: { denominator: 6 } }, coverage: { salary: { label: "Salary", known: 2, denominator: 6 } } },
      evaluations: { population: { denominator: 6 }, evaluatedJobs: 4, blockerFreeJobs: 3, requiredGaps: 2, unknownFindings: 3, dimensions: [{ dimension: "skills", state: "gap", count: 2 }] },
      applications: { population: { denominator: 3 }, rates: { response: { numerator: 1, denominator: 3, percent: 33.3 }, interview: { numerator: 1, denominator: 3, percent: 33.3 }, offer: { numerator: 0, denominator: 3, percent: 0 } } },
      skillIntelligence: { href: "/skills" },
    });
    expect(trackHtml).toContain("current Pack J Evaluations");
    expect(trackHtml).toContain("Open detailed Pack K skill evidence");

    const career = renderCareerIntelligence({
      minimumSample: 3,
      suggestions: [{ roleFamily: "Data &lt;bad&gt;", confidenceCategory: "emerging pattern", observedJobCount: 4, population: { denominator: 20 }, sharedStrengths: [{ displayLabel: "SQL", observedJobs: 4, profileEvidence: { recordId: "skill-1" } }], explicitGaps: [], unknowns: [] }],
      trackProposals: [{ proposalKey: "proposal-1", proposedName: "Data QA", roleFamily: "Data QA", state: "suggested", evidence: { adjacency: { whySuggested: ["Observed jobs and Profile evidence."] } } }],
    }, [{ id: "sql-analysis@1", title: "SQL analysis" }]);
    expect(career).toContain("Hypotheses, not decisions");
    expect(career).toContain("Accept and create Track");
    expect(career).not.toContain("Data <bad>");

    const experiments = renderExperiments({ items: [{
      id: "exp-1", status: "completed", title: "SQL &lt;trial&gt;", hypothesis: "Test it",
      taskDefinitionVersion: "sql@1", plannedMinutes: 60, actualMinutes: 50,
      interestRating: 4, difficultyRating: 3, frustrationRating: 1,
      confidenceChangeRating: 1, desireToContinue: true,
      events: [{ type: "note_added", payload: { note: "Later <script>" } }],
    }] }, [{ id: "sql-analysis@1", title: "SQL analysis", plannedMinutes: 60 }], tracks);
    expect(experiments).toContain("Use experiment to update Profile");
    expect(experiments).toContain("Create planned follow-up");
    expect(experiments).toContain("Append reinterpretation note");
    expect(experiments).not.toContain("<script>");
  });

  it("wires scenario, proposal, and experiment actions through the controller", async () => {
    const api = {
      marketAnalytics: vi.fn(), sourceAnalytics: vi.fn(), applicationAnalytics: vi.fn(),
      tradeoffAnalytics: vi.fn().mockResolvedValue({ tracks: [] }),
      careerIntelligence: vi.fn(), experimentTemplates: vi.fn(), experiments: vi.fn(),
      saveEconomicScenario: vi.fn(), decideTrackProposal: vi.fn(), createExperiment: vi.fn(),
      experimentCommand: vi.fn(),
    };
    const root = document.getElementById("root");
    const controller = createJobhuntInsightsController({ root, api, tracks, tab: "tracks" });
    await controller.refresh();
    expect(api.tradeoffAnalytics).toHaveBeenCalledWith(["track-pl", "track-no"], { window: "90d" });

    controller.state.data = { tracks: [{
      track: { id: "track-pl", name: "QA Poland", currency: "PLN" }, currentJobs: 0,
      observedJobs: 0, salaryEvidence: null, requiredSkillGaps: 0, evaluationUnknowns: 0,
      evaluationUnknownRate: { numerator: 0, denominator: 0, percent: null },
      languageRequirements: [], languageRequirementCoverage: {}, uncertainty: [],
    }, {
      track: { id: "track-no", name: "Norway QA", currency: "NOK" }, currentJobs: 0,
      observedJobs: 0, salaryEvidence: null, requiredSkillGaps: 0, evaluationUnknowns: 0,
      evaluationUnknownRate: { numerator: 0, denominator: 0, percent: null },
      languageRequirements: [], languageRequirementCoverage: {}, uncertainty: [],
    }] };
    controller.render();
    const form = root.querySelector('[data-scenario-form][data-track-id="track-pl"]');
    form.elements.housing.value = "2000";
    form.elements.source.value = "manual";
    form.elements.updatedAt.value = "2026-09-24";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await Promise.resolve(); await Promise.resolve();
    expect(api.saveEconomicScenario).toHaveBeenCalledWith("track-pl", expect.objectContaining({
      assumptions: { monthlyCosts: { housing: expect.objectContaining({ value: 2000 }) } },
    }));
  });

  it("creates an explicit planned follow-up without mutating completed evidence", async () => {
    const api = {
      experimentTemplates: vi.fn().mockResolvedValue({ items: [{ id: "sql-analysis@1", title: "SQL analysis", plannedMinutes: 60 }] }),
      experiments: vi.fn().mockResolvedValue({ items: [] }),
      createExperiment: vi.fn().mockResolvedValue({ experiment: { id: "exp-2" } }),
      experimentCommand: vi.fn(),
    };
    const root = document.getElementById("root");
    const controller = createJobhuntInsightsController({ root, api, tracks, tab: "experiments" });
    controller.state.templates = [{ id: "sql-analysis@1", title: "SQL analysis", plannedMinutes: 60 }];
    controller.state.data = { items: [{
      id: "exp-1", trackId: "track-pl", status: "completed", title: "SQL trial",
      hypothesis: "Test it", taskDefinitionVersion: "sql@1", plannedMinutes: 60,
      actualMinutes: 50, interestRating: 4, difficultyRating: 3, frustrationRating: 1,
      confidenceChangeRating: 1, desireToContinue: true, events: [],
    }] };
    controller.render();
    root.querySelector("[data-experiment-followup]").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await Promise.resolve(); await Promise.resolve();
    expect(api.createExperiment).toHaveBeenCalledWith({
      templateId: "sql-analysis@1", trackId: "track-pl",
      evidence: { followupFromExperimentId: "exp-1" },
    });
    expect(api.experimentCommand).not.toHaveBeenCalled();
  });

  it("exposes Pack M API methods with bounded encoded routes", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, data: {} }),
    });
    const api = createJobhuntApi({ fetchImpl, baseUrl: "/api/jobhunt" });
    await api.marketAnalytics({ window: "30d", geography: "Oslo" });
    await api.trackAnalytics("track / one", { window: "90d" });
    await api.tradeoffAnalytics(["track-1", "track-2"], { window: "180d" });
    await api.experimentCommand("exp/1", "complete", { actualMinutes: 5 });
    expect(fetchImpl.mock.calls[0][0]).toContain("/analytics/market?window=30d&geography=Oslo");
    expect(fetchImpl.mock.calls[1][0]).toContain("/tracks/track%20%2F%20one/analytics");
    expect(fetchImpl.mock.calls[2][0]).toContain("trackIds=track-1%2Ctrack-2");
    expect(fetchImpl.mock.calls[3][0]).toContain("/experiments/exp%2F1/complete");
  });
});
