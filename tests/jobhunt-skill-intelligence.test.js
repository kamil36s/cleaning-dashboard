import { describe, expect, it } from "vitest";

import {
  filterSkillRows,
  renderSkillDetail,
  renderSkillIntelligence,
  skillWindowParams,
  sortSkillRows,
} from "../js/jobhunt-skill-intelligence.js";

const skill = {
  reference: "skill:SQL",
  conceptId: "concept_skill_sql",
  conceptType: "skill",
  conceptKey: "SQL",
  displayLabel: "SQL",
  normalization: { ruleVersions: ["normalization@1"], manualMappingUsed: false },
  sourceTerms: [{ term: "SQL <script>", jobCount: 4, observationCount: 6, jobIds: ["job-a"] }],
  demand: {
    jobsMentioning: 4, requiredJobs: 3, preferredJobs: 1, optionalJobs: 0,
    unknownRequirementJobs: 0, ambiguousRequirementJobs: 0, notMentionedJobs: 6,
    totalTrackJobs: 10, jobsWithSkillEvidence: 8,
    percentAllTrackJobs: 40, percentSkillBearingJobs: 50,
  },
  profileEvidence: {
    exists: true, displayName: "SQL", level: 2, confidence: 4,
    developmentInterest: 5, evidenceReferences: [{ id: "e-1", origin: "manual_user", notes: "Practice" }],
  },
  user: {
    supported: 1, partial: 0, gap: 2, blocker: 0, blockers: 0, unknown: 1,
    state: "mixed", requiredGaps: 2, preferredGaps: 0, optionalGaps: 0,
    unknownRequirementGaps: 0, evaluatedJobsMentioning: 4,
    evaluatedJobsMissingConceptFinding: 0, unknownRate: 0.25,
  },
  opportunity: { strictJobsUnlocked: 1, potentialJobsUnlocked: 1, multiGapOpportunities: 1 },
  priority: {
    classification: "high",
    reasons: ["3 Track jobs explicitly require this concept.", "Pack J reports a required gap in 2 current jobs."],
    components: { requiredDemand: 3, requiredGaps: 2 },
  },
};

const data = {
  track: { id: "track-1", name: "QA Poland", status: "active" },
  population: {
    mode: "current", window: "current", startAt: null, endAt: "2026-09-24T00:00:00Z",
    canonicalJobDenominator: 10, semantics: "Active deduplicated jobs.",
    timeAnchorHierarchy: ["publication", "first observation", "created"],
    fingerprint: `sha256:${"a".repeat(64)}`,
  },
  coverage: {
    totalJobs: 10, jobsWithSkillEvidence: 8, jobsWithoutSkillEvidence: 2,
    jobsWithCurrentEvaluations: 6, jobsMissingCurrentEvaluations: 4,
    staleEvaluationPointers: 1,
  },
  versions: {
    skillIntelligence: "skill-intelligence@1",
    mappingFingerprint: `sha256:${"b".repeat(64)}`,
    mappingRuleVersions: ["normalization@1"], evaluatorVersion: "evaluator@1",
  },
  priorityPolicy: {
    version: "skill-intelligence@1", minimumPopulation: 5,
    minimumSkillEvidenceCoverage: 0.4, minimumEvaluationCoverage: 0.4,
  },
  skills: [skill, {
    ...skill, reference: "tool:JIRA", conceptType: "tool", conceptKey: "JIRA", displayLabel: "Jira",
    demand: { ...skill.demand, jobsMentioning: 2, requiredJobs: 2 },
    profileEvidence: { exists: false, evidenceReferences: [] },
    user: { ...skill.user, supported: 0, gap: 0, requiredGaps: 0, unknown: 2, state: "unknown" },
    opportunity: { strictJobsUnlocked: 0, potentialJobsUnlocked: 0, multiGapOpportunities: 0 },
    priority: { classification: "monitor", reasons: ["Observed demand is limited."], components: {} },
  }],
  strengths: [{ reference: "skill:SQL", displayLabel: "SQL", jobsMentioning: 4, requiredJobs: 3, supportedJobs: 1 }],
  unknownProfileAreas: [{ reference: "tool:JIRA", displayLabel: "Jira", jobsMentioning: 2, requiredJobs: 2, unknownJobs: 2 }],
  unmapped: {
    termCount: 1,
    terms: [{
      term: "Unsafe <img src=x onerror=1>", factType: "tool", jobCount: 2,
      observationCount: 2, normalizationStatus: "unmapped",
      sampleEvidence: [{ source: "manual", sourceWording: "<svg onload=1>" }],
    }],
  },
  generatedAt: "2026-09-24T00:00:00Z",
};

const detail = {
  population: data.population, versions: data.versions, priorityPolicy: data.priorityPolicy,
  skill: {
    ...skill,
    demandJobs: [{ id: "job-a", company: "ACME <unsafe>", role: "QA", requirementClass: "required" }],
    findingJobs: [{
      id: "job-a", company: "ACME <unsafe>", role: "QA", state: "gap",
      findings: [{ status: "gap", requirementClass: "required", label: "SQL <gap>" }],
    }],
    strictUnlockJobs: [{ id: "job-a", company: "ACME", role: "QA", reason: "Only required GAP." }],
    potentialUnlockJobs: [{ id: "job-b", company: "Beta", role: "Tester", reason: "UNKNOWN remains.", remainingUnknownLabels: ["Norwegian"] }],
    multiGapJobs: [{ id: "job-c", company: "Gamma", role: "QA", remainingGapLabels: ["Playwright"] }],
  },
};

describe("Job Hunt Pack K Skill Intelligence UI", () => {
  it("renders explicit denominators, demand classes, Profile evidence, UNKNOWN, unlocks, and priority", () => {
    const html = renderSkillIntelligence(data);
    expect(html).toContain("10");
    expect(html).toContain("8 / 10");
    expect(html).toContain("Required gaps");
    expect(html).toContain("UNKNOWN");
    expect(html).toContain("+1 potential");
    expect(html).toContain("skill-intelligence@1");
    expect(html).toContain("Established strengths");
    expect(html).toContain("High-demand UNKNOWN Profile areas");
    expect(html).not.toContain("/100");
  });

  it("escapes imported source terms and unmapped evidence", () => {
    const html = renderSkillIntelligence(data);
    expect(html).toContain("Unsafe &lt;img src=x onerror=1&gt;");
    expect(html).toContain("&lt;svg onload=1&gt;");
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("<svg onload");
  });

  it("renders concept drill-down, source-term jobs, strict/potential unlocks, and provenance", () => {
    const html = renderSkillDetail(detail);
    expect(html).toContain("Strictly unlockable (1)");
    expect(html).toContain("Potential with remaining UNKNOWN (1)");
    expect(html).toContain("Multi-gap opportunities (1)");
    expect(html).toContain("Jobs contributing gaps/blockers (1)");
    expect(html).toContain("SQL &lt;gap&gt;");
    expect(html).toContain("SQL &lt;script&gt;");
    expect(html).toContain("normalization@1");
    expect(html).toContain("Population fingerprint");
    expect(html).toContain("ACME &lt;unsafe&gt;");
  });

  it("supports the required user filters and transparent sorts", () => {
    expect(filterSkillRows(data.skills, "required-gaps").map((item) => item.displayLabel)).toEqual(["SQL"]);
    expect(filterSkillRows(data.skills, "unknowns")).toHaveLength(2);
    expect(filterSkillRows(data.skills, "supported").map((item) => item.displayLabel)).toEqual(["SQL"]);
    expect(filterSkillRows(data.skills, "high").map((item) => item.displayLabel)).toEqual(["SQL"]);
    expect(filterSkillRows(data.skills, "unlocked").map((item) => item.displayLabel)).toEqual(["SQL"]);
    expect(sortSkillRows(data.skills, "demand")[0].displayLabel).toBe("SQL");
    expect(sortSkillRows(data.skills, "alphabetical")[0].displayLabel).toBe("Jira");
  });

  it("maps current and bounded historical selectors and renders empty/insufficient states", () => {
    expect(skillWindowParams("current")).toEqual({ population: "current", window: "90d" });
    expect(skillWindowParams("30d")).toEqual({ population: "historical", window: "30d" });
    const empty = renderSkillIntelligence({ ...data, skills: [], strengths: [], unknownProfileAreas: [] });
    expect(empty).toContain("No normalized concepts match this view");
    const insufficient = renderSkillIntelligence({
      ...data,
      skills: [{ ...skill, priority: { ...skill.priority, classification: "insufficient_evidence" } }],
    });
    expect(insufficient).toContain("insufficient evidence");
  });
});
