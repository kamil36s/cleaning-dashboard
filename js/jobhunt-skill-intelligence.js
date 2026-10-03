import { escapeHtml } from "./utils.js";

const PRIORITY_ORDER = { high: 0, medium: 1, low: 2, monitor: 3, insufficient_evidence: 4 };

function percent(value) {
  return value == null ? "—" : `${Number(value).toFixed(1)}%`;
}

function populationParams(windowValue = "current") {
  return windowValue === "current"
    ? { population: "current", window: "90d" }
    : { population: "historical", window: windowValue };
}

export function skillWindowParams(windowValue) {
  return populationParams(windowValue);
}

function profileLabel(profile = {}) {
  if (!profile.exists) return "UNKNOWN";
  const values = [profile.displayName];
  if (profile.level != null) values.push(`level ${profile.level}`);
  if (profile.confidence != null) values.push(`confidence ${profile.confidence}/5`);
  return values.filter(Boolean).join(" · ");
}

function priorityBadge(priority = {}) {
  const value = priority.classification || "insufficient_evidence";
  return `<span class="jobhunt-skill-priority is-${escapeHtml(value)}">${escapeHtml(value.replaceAll("_", " "))}</span>`;
}

export function filterSkillRows(rows = [], filter = "all") {
  if (filter === "required-gaps") return rows.filter((item) => item.user.requiredGaps > 0);
  if (filter === "preferred-gaps") return rows.filter((item) => item.user.preferredGaps > 0);
  if (filter === "unknowns") return rows.filter((item) => item.user.unknown > 0);
  if (filter === "supported") return rows.filter((item) => item.user.supported > 0);
  if (filter === "high") return rows.filter((item) => item.priority.classification === "high");
  if (filter === "unlocked") return rows.filter((item) => item.opportunity.strictJobsUnlocked > 0);
  return rows;
}

function sourceTermJobs(term, jobs = []) {
  const wanted = new Set(term.jobIds || []);
  const values = jobs.filter((job) => wanted.has(job.id));
  return values.length
    ? `<ul>${values.map((job) => `<li>${escapeHtml(job.company)} — ${escapeHtml(job.role)}</li>`).join("")}</ul>`
    : "";
}

export function renderSkillDetail(detail) {
  const skill = detail?.skill;
  if (!skill) return "";
  const demandJobs = skill.demandJobs || [];
  const gapJobs = (skill.findingJobs || []).filter((job) =>
    (job.findings || []).some((finding) => finding.status === "gap" || finding.status === "blocker"));
  const evidence = skill.profileEvidence || {};
  return `<section class="jobhunt-skill-detail" data-skill-detail="${escapeHtml(skill.reference)}">
    <div class="jobhunt-career-block-head">
      <div><span class="jobhunt-section-label">${escapeHtml(skill.conceptType)}</span><h3>${escapeHtml(skill.displayLabel)}</h3><small>${escapeHtml(skill.reference)}</small></div>
      <div class="jobhunt-row-actions"><button type="button" class="jobhunt-secondary-action" data-skill-action="create-experiment" data-skill-reference="${escapeHtml(skill.reference)}" data-skill-label="${escapeHtml(skill.displayLabel)}">Create experiment</button><button type="button" class="jobhunt-ghost-action" data-skill-action="close-detail">Close</button></div>
    </div>
    <div class="jobhunt-skill-detail-grid">
      <article><h4>Market demand</h4><p><strong>${skill.demand.jobsMentioning}</strong> / ${skill.demand.totalTrackJobs} jobs mention it (${percent(skill.demand.percentAllTrackJobs)}).</p><p>Required ${skill.demand.requiredJobs} · preferred ${skill.demand.preferredJobs} · optional ${skill.demand.optionalJobs} · unknown class ${skill.demand.unknownRequirementJobs} · ambiguous ${skill.demand.ambiguousRequirementJobs}.</p></article>
      <article><h4>My evidence</h4><p>${escapeHtml(profileLabel(evidence))}</p><p>Development interest: ${escapeHtml(evidence.developmentInterest ?? "not recorded")}</p>${evidence.evidenceReferences?.length ? `<ul>${evidence.evidenceReferences.map((item) => `<li>${escapeHtml(item.origin || "evidence")} · ${escapeHtml(item.notes || item.sourceReference || item.id)}</li>`).join("")}</ul>` : ""}</article>
      <article><h4>Current Pack J findings</h4><p>Supported ${skill.user.supported} · partial ${skill.user.partial} · gaps ${skill.user.gap} · blockers ${skill.user.blockers} · unknown ${skill.user.unknown}.</p><p>Required gaps ${skill.user.requiredGaps} · preferred gaps ${skill.user.preferredGaps}.</p></article>
      <article><h4>Learning priority</h4>${priorityBadge(skill.priority)}<ul>${skill.priority.reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul><small>Policy: ${escapeHtml(detail.priorityPolicy?.version || "skill-intelligence@1")}</small></article>
    </div>
    <div class="jobhunt-skill-detail-grid">
      <article><h4>Jobs contributing gaps/blockers (${gapJobs.length})</h4>${gapJobs.length ? `<ul>${gapJobs.map((job) => `<li><button type="button" data-job-open="${escapeHtml(job.id)}">${escapeHtml(job.company)} — ${escapeHtml(job.role)}</button><small>${job.findings.filter((finding) => finding.status === "gap" || finding.status === "blocker").map((finding) => `${escapeHtml(finding.requirementClass)} ${escapeHtml(finding.status)}${finding.label ? `: ${escapeHtml(finding.label)}` : ""}`).join(" · ")}</small></li>`).join("")}</ul>` : `<p>No current Pack J GAP or BLOCKER finding contributes to this concept.</p>`}</article>
      <article><h4>Strictly unlockable (${skill.opportunity.strictJobsUnlocked})</h4>${skill.strictUnlockJobs?.length ? `<ul>${skill.strictUnlockJobs.map((job) => `<li><button type="button" data-job-open="${escapeHtml(job.id)}">${escapeHtml(job.company)} — ${escapeHtml(job.role)}</button><small>${escapeHtml(job.reason)}</small></li>`).join("")}</ul>` : `<p>No job is strictly unlockable by this one skill under current evidence.</p>`}</article>
      <article><h4>Potential with remaining UNKNOWN (${skill.opportunity.potentialJobsUnlocked})</h4>${skill.potentialUnlockJobs?.length ? `<ul>${skill.potentialUnlockJobs.map((job) => `<li><button type="button" data-job-open="${escapeHtml(job.id)}">${escapeHtml(job.company)} — ${escapeHtml(job.role)}</button><small>${escapeHtml(job.reason)} ${escapeHtml((job.remainingUnknownLabels || []).filter(Boolean).join(", "))}</small></li>`).join("")}</ul>` : `<p>No potential single-skill unlock retains required UNKNOWN evidence.</p>`}</article>
      <article><h4>Multi-gap opportunities (${skill.opportunity.multiGapOpportunities})</h4>${skill.multiGapJobs?.length ? `<ul>${skill.multiGapJobs.map((job) => `<li><button type="button" data-job-open="${escapeHtml(job.id)}">${escapeHtml(job.company)} — ${escapeHtml(job.role)}</button><small>${escapeHtml((job.remainingGapLabels || []).filter(Boolean).join(", "))}</small></li>`).join("")}</ul>` : `<p>No multi-gap jobs for this concept.</p>`}</article>
    </div>
    <div class="jobhunt-skill-source-terms"><h4>Observed source terms</h4>${skill.sourceTerms.length ? skill.sourceTerms.map((term) => `<details><summary>“${escapeHtml(term.term)}” — ${term.jobCount} jobs (${term.observationCount} observations)</summary>${sourceTermJobs(term, demandJobs)}</details>`).join("") : `<p>No source terms.</p>`}</div>
    <details class="jobhunt-skill-provenance"><summary>Normalization and population provenance</summary><dl><div><dt>Concept</dt><dd>${escapeHtml(skill.reference)}</dd></div><div><dt>Mapping rules</dt><dd>${escapeHtml((skill.normalization.ruleVersions || []).join(", ") || "none")}</dd></div><div><dt>Manual mapping used</dt><dd>${skill.normalization.manualMappingUsed ? "yes" : "no"}</dd></div><div><dt>Mapping fingerprint</dt><dd><code>${escapeHtml(detail.versions?.mappingFingerprint)}</code></dd></div><div><dt>Population fingerprint</dt><dd><code>${escapeHtml(detail.population?.fingerprint)}</code></dd></div></dl></details>
  </section>`;
}

function renderUnmapped(data) {
  const terms = data?.unmapped?.terms || [];
  return `<details class="jobhunt-skill-unmapped"><summary>Unmapped / review-needed terms (${terms.length})</summary>
    <p>These observed terms remain source evidence. Pack K does not create taxonomy mappings automatically.</p>
    ${terms.length ? `<div class="jobhunt-skill-unmapped-list">${terms.map((item) => `<article><strong>${escapeHtml(item.term)}</strong><span>${escapeHtml(item.factType)} · ${item.jobCount} jobs · ${escapeHtml(item.normalizationStatus)}</span>${item.sampleEvidence?.length ? `<small>${item.sampleEvidence.map((sample) => `${escapeHtml(sample.source || "source")}: “${escapeHtml(sample.sourceWording)}”`).join(" · ")}</small>` : ""}</article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No unmapped skill-like terms in this population.</div>`}
  </details>`;
}

function renderHighlights(title, items, emptyText) {
  return `<article><h4>${escapeHtml(title)}</h4>${items?.length ? `<ul>${items.map((item) => `<li><button type="button" data-skill-concept="${escapeHtml(item.reference)}">${escapeHtml(item.displayLabel)}</button><small>${item.requiredJobs} required · ${item.jobsMentioning} mentioned${item.supportedJobs != null ? ` · ${item.supportedJobs} supported` : ` · ${item.unknownJobs} unknown`}</small></li>`).join("")}</ul>` : `<p>${escapeHtml(emptyText)}</p>`}</article>`;
}

export function renderSkillIntelligence(data, {
  window = "current", filter = "all", sort = "priority", detail = null, loadingDetail = false,
} = {}) {
  if (!data) return `<section class="jobhunt-career-block jobhunt-skill-intelligence"><div class="jobhunt-empty-inline">Skill Intelligence is loading…</div></section>`;
  const coverage = data.coverage || {};
  const population = data.population || {};
  const rows = filterSkillRows(data.skills || [], filter);
  return `<section class="jobhunt-career-block jobhunt-skill-intelligence">
    <div class="jobhunt-career-block-head"><div><span class="jobhunt-section-label">Pack K · ${escapeHtml(data.versions?.skillIntelligence)}</span><h3>Skill Intelligence</h3><span>Track-specific observed demand and Pack J aggregation. No hidden score or external model.</span></div></div>
    <div class="jobhunt-skill-controls">
      <label><span>Population</span><select data-skill-window><option value="current"${window === "current" ? " selected" : ""}>Current active jobs</option><option value="30d"${window === "30d" ? " selected" : ""}>Historical · 30 days</option><option value="90d"${window === "90d" ? " selected" : ""}>Historical · 90 days</option><option value="180d"${window === "180d" ? " selected" : ""}>Historical · 180 days</option></select></label>
      <label><span>View</span><select data-skill-filter><option value="all">All skills</option><option value="required-gaps"${filter === "required-gaps" ? " selected" : ""}>Required gaps</option><option value="preferred-gaps"${filter === "preferred-gaps" ? " selected" : ""}>Preferred gaps</option><option value="unknowns"${filter === "unknowns" ? " selected" : ""}>UNKNOWN evidence</option><option value="supported"${filter === "supported" ? " selected" : ""}>Supported strengths</option><option value="high"${filter === "high" ? " selected" : ""}>High priority</option><option value="unlocked"${filter === "unlocked" ? " selected" : ""}>Strict jobs unlocked &gt; 0</option></select></label>
      <label><span>Sort</span><select data-skill-sort><option value="priority"${sort === "priority" ? " selected" : ""}>Priority policy</option><option value="required"${sort === "required" ? " selected" : ""}>Required demand</option><option value="demand"${sort === "demand" ? " selected" : ""}>Total demand</option><option value="gaps"${sort === "gaps" ? " selected" : ""}>Required gaps</option><option value="unlocked"${sort === "unlocked" ? " selected" : ""}>Strict jobs unlocked</option><option value="unknown"${sort === "unknown" ? " selected" : ""}>UNKNOWN rate</option><option value="alphabetical"${sort === "alphabetical" ? " selected" : ""}>Alphabetical</option></select></label>
    </div>
    <div class="jobhunt-skill-population">
      <div><span>Canonical Jobs</span><strong>${population.canonicalJobDenominator ?? 0}</strong><small>${escapeHtml(population.mode)} · ${escapeHtml(population.window)}</small></div>
      <div><span>Skill evidence</span><strong>${coverage.jobsWithSkillEvidence ?? 0} / ${coverage.totalJobs ?? 0}</strong><small>${coverage.jobsWithoutSkillEvidence ?? 0} without usable evidence</small></div>
      <div><span>Current Evaluations</span><strong>${coverage.jobsWithCurrentEvaluations ?? 0} / ${coverage.totalJobs ?? 0}</strong><small>${coverage.jobsMissingCurrentEvaluations ?? 0} missing · ${coverage.staleEvaluationPointers ?? 0} stale</small></div>
      <div><span>Generated</span><strong>${escapeHtml(String(data.generatedAt || "").slice(0, 10))}</strong><small>Mapping ${escapeHtml((data.versions?.mappingRuleVersions || []).join(", ") || "no active rules")}</small></div>
    </div>
    <p class="jobhunt-skill-limitation">${escapeHtml(population.semantics)} Percentages retain both the ${coverage.totalJobs ?? 0}-job Track denominator and the ${coverage.jobsWithSkillEvidence ?? 0}-job skill-evidence denominator.</p>
    ${rows.length ? `<div class="jobhunt-skill-table-wrap"><table class="jobhunt-skill-table"><thead><tr><th>Skill</th><th>Demand</th><th>Required</th><th>Preferred</th><th>My evidence</th><th>Required gaps</th><th>UNKNOWN</th><th>Jobs unlocked</th><th>Priority</th></tr></thead><tbody>${rows.map((item) => `<tr><td><button type="button" data-skill-concept="${escapeHtml(item.reference)}"><strong>${escapeHtml(item.displayLabel)}</strong><small>${escapeHtml(item.conceptType)}</small></button></td><td>${item.demand.jobsMentioning} / ${item.demand.totalTrackJobs}<small>${percent(item.demand.percentAllTrackJobs)} all · ${percent(item.demand.percentSkillBearingJobs)} evidenced</small></td><td>${item.demand.requiredJobs}</td><td>${item.demand.preferredJobs}</td><td>${escapeHtml(profileLabel(item.profileEvidence))}<small>Pack J: ${escapeHtml(item.user.state)}</small></td><td>${item.user.requiredGaps}<small>${item.user.blockers} blockers</small></td><td>${item.user.unknown}<small>${item.user.unknownRate == null ? "no comparable findings" : percent(item.user.unknownRate * 100)}</small></td><td>${item.opportunity.strictJobsUnlocked}<small>+${item.opportunity.potentialJobsUnlocked} potential</small></td><td>${priorityBadge(item.priority)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="jobhunt-empty-inline">No normalized concepts match this view. Check evidence coverage or unmapped terms.</div>`}
    <div class="jobhunt-skill-highlights">${renderHighlights("Established strengths", data.strengths, "No supported recurring strength is visible in current Pack J findings.")}${renderHighlights("High-demand UNKNOWN Profile areas", data.unknownProfileAreas, "No recurring UNKNOWN Profile area is visible.")}</div>
    ${loadingDetail ? `<div class="jobhunt-empty-inline">Loading skill evidence…</div>` : renderSkillDetail(detail)}
    ${renderUnmapped(data)}
    <details class="jobhunt-skill-meta"><summary>Population, policy, and fingerprints</summary><p>${escapeHtml((population.timeAnchorHierarchy || []).join(" → "))}</p><p>Priority minimum: ${data.priorityPolicy?.minimumPopulation} jobs; skill coverage ${Math.round((data.priorityPolicy?.minimumSkillEvidenceCoverage || 0) * 100)}%; current-Evaluation coverage ${Math.round((data.priorityPolicy?.minimumEvaluationCoverage || 0) * 100)}%.</p><code>${escapeHtml(population.fingerprint)}</code><code>${escapeHtml(data.versions?.mappingFingerprint)}</code></details>
  </section>`;
}

export function sortSkillRows(rows = [], sort = "priority") {
  const values = [...rows];
  const selectors = {
    priority: (item) => [PRIORITY_ORDER[item.priority.classification] ?? 9, -item.demand.requiredJobs, item.displayLabel],
    required: (item) => [-item.demand.requiredJobs, -item.demand.jobsMentioning, item.displayLabel],
    demand: (item) => [-item.demand.jobsMentioning, -item.demand.requiredJobs, item.displayLabel],
    gaps: (item) => [-item.user.requiredGaps, -item.user.blockers, item.displayLabel],
    unlocked: (item) => [-item.opportunity.strictJobsUnlocked, -item.opportunity.potentialJobsUnlocked, item.displayLabel],
    unknown: (item) => [-(item.user.unknownRate || 0), -item.user.unknown, item.displayLabel],
    alphabetical: (item) => [item.displayLabel],
  };
  const selector = selectors[sort] || selectors.priority;
  return values.sort((left, right) => {
    const a = selector(left); const b = selector(right);
    for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
      if (a[index] === b[index]) continue;
      return typeof a[index] === "number" ? a[index] - b[index] : String(a[index]).localeCompare(String(b[index]));
    }
    return 0;
  });
}
