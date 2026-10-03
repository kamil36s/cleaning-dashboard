import { escapeHtml } from "./utils.js";

export const INSIGHT_TABS = [
  ["market", "Market"], ["sources", "Sources"], ["applications", "Applications"],
  ["tracks", "Track trade-offs"], ["career", "Career Intelligence"],
  ["experiments", "Experiments"],
];

function number(value, fallback = "0") {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : fallback;
}

function value(value, fallback = "Unknown") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function percent(metric) {
  if (metric?.percent === null || metric?.percent === undefined) return "Unknown";
  return `${number(metric.percent)}% (${number(metric.numerator)}/${number(metric.denominator)})`;
}

function metric(label, main, detail = "") {
  return `<article class="jobhunt-insight-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value(main))}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</article>`;
}

function empty(title, body) {
  return `<div class="jobhunt-empty-state"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p></div>`;
}

function windowControl(window) {
  return `<label class="jobhunt-inline-select"><span>Window</span><select data-insights-window>${["30d", "90d", "180d", "365d", "all"].map((item) => `<option value="${item}"${item === window ? " selected" : ""}>${item}</option>`).join("")}</select></label>`;
}

export function renderMarketAnalytics(data) {
  if (!data) return empty("Market analytics unavailable", "Try loading this view again.");
  const observed = data.populations?.observed || {};
  const current = data.populations?.current || {};
  const coverage = Object.values(data.coverage || {});
  const salary = data.salary || {};
  return `<div class="jobhunt-analytics-stack">
    <div class="jobhunt-insight-metrics">
      ${metric("Observed canonical jobs", number(observed.denominator), `${data.filters?.window || "window"}; deduplicated`)}
      ${metric("Current jobs", number(current.denominator), "active, non-expired snapshot")}
      ${metric("New in 7 days", number(data.flow?.newLast7Days), `of ${number(observed.denominator)} observed`)}
      ${metric("Known salary", number(salary.knownJobs), `of ${number(salary.denominator)} jobs`)}
    </div>
    <section class="jobhunt-analytics-card"><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Coverage</span><h2>Known and unknown evidence</h2></div></div>
      <div class="jobhunt-coverage-grid">${coverage.map((item) => `<div><span>${escapeHtml(item.label)}</span><strong>${number(item.known)} known</strong><small>${number(item.unknown)} unknown / ${number(item.denominator)} total</small></div>`).join("")}</div>
    </section>
    <section class="jobhunt-analytics-card"><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Salary evidence</span><h2>Comparable groups only</h2></div></div>
      ${salary.groups?.length ? `<div class="jobhunt-table-wrap"><table class="jobhunt-data-table"><thead><tr><th>Group</th><th>Sample</th><th>Median range</th><th>Observed range</th><th>Evidence</th></tr></thead><tbody>${salary.groups.map((group) => `<tr><td>${escapeHtml(`${group.currency} / ${group.period} / ${group.taxType}`)}</td><td>${number(group.count)} / ${number(group.denominator)}</td><td>${group.status === "sufficient" ? escapeHtml(`${number(group.medianLower, "?")} - ${number(group.medianUpper, "?")}`) : "Not shown"}</td><td>${escapeHtml(`${number(group.minimumObserved, "?")} - ${number(group.maximumObserved, "?")}`)}</td><td>${escapeHtml(group.status)}; minimum ${number(group.minimumSample)}</td></tr>`).join("")}</tbody></table></div>` : empty("Insufficient salary evidence", `No comparable currency/period/tax group meets the evidence rules. ${number(salary.unknownJobs)} jobs have unknown or incomparable salary.`)}
      <p class="jobhunt-method-note">No outliers are removed. No currency conversion is performed.</p>
    </section>
    <section class="jobhunt-analytics-card"><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Market mix</span><h2>Top companies and geography</h2></div></div>
      <div class="jobhunt-two-column"><div><h3>Companies</h3>${(data.companies?.items || []).slice(0, 8).map((item) => `<p><strong>${escapeHtml(item.company)}</strong><span>${number(item.jobs)} / ${number(item.denominator)} jobs</span></p>`).join("") || "<p>No company evidence.</p>"}</div><div><h3>Countries</h3>${(data.geography?.countries || []).slice(0, 8).map((item) => `<p><strong>${escapeHtml(item.value)}</strong><span>${number(item.count)} / ${number(item.denominator)} jobs</span></p>`).join("") || "<p>No geography evidence.</p>"}</div></div>
    </section>
    <section class="jobhunt-analytics-card"><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Conditions</span><h2>Work model, contracts, and requirements</h2></div></div><div class="jobhunt-two-column"><div><h3>Work models</h3>${(data.workModels || []).map((item) => `<p><strong>${escapeHtml(item.value)}</strong><span>${number(item.count)} / ${number(item.denominator)}</span></p>`).join("") || "<p>No evidence.</p>"}<h3>Contract types</h3>${(data.contractTypes || []).map((item) => `<p><strong>${escapeHtml(item.value)}</strong><span>${number(item.count)} / ${number(item.denominator)}</span></p>`).join("") || "<p>No evidence.</p>"}</div><div><h3>Typed requirements</h3>${(data.requirements || []).map((item) => `<p><strong>${escapeHtml(item.type)}</strong><span>${number(item.jobsWithEvidence)} / ${number(item.denominator)} jobs</span></p>`).join("") || "<p>No typed requirement evidence.</p>"}<a href="${escapeHtml(data.skillIntelligence?.href || "#skills")}">Open detailed Pack K skill demand</a></div></div></section>
    <section class="jobhunt-analytics-card"><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Flow</span><h2>Observed jobs over time</h2></div></div>${data.flow?.trend?.length ? `<div class="jobhunt-table-wrap"><table class="jobhunt-data-table"><thead><tr><th>Period</th><th>Unique jobs</th><th>Window denominator</th></tr></thead><tbody>${data.flow.trend.map((item) => `<tr><td>${escapeHtml(item.period)} (${escapeHtml(item.granularity)})</td><td>${number(item.count)}</td><td>${number(observed.denominator)}</td></tr>`).join("")}</tbody></table></div>` : `<p>No dated observations in this window.</p>`}</section>
  </div>`;
}

export function renderSourceAnalytics(data) {
  if (!data?.sources?.length) return empty("No source observations", "The selected window contains no implemented-source listings.");
  return `<div class="jobhunt-table-wrap"><table class="jobhunt-data-table"><thead><tr><th>Source</th><th>Listings</th><th>Canonical jobs</th><th>Unique</th><th>Duplicates / overlap</th><th>Review burden</th><th>Requests</th><th>Health</th></tr></thead><tbody>${data.sources.map((source) => `<tr>
    <td><strong>${escapeHtml(source.displayName)}</strong><small>${escapeHtml(source.sourceKey)}</small></td>
    <td>${number(source.listingsDiscovered)}<small>denominator ${number(source.population?.denominator)}</small></td>
    <td>${number(source.canonicalJobsContributed)}</td><td>${number(source.uniqueContribution)}</td>
    <td>${percent(source.duplicateRate)} duplicates<small>${percent(source.duplicateOverlap)} cross-source overlap; ${number(source.unlinkedListings)} unlinked</small></td>
    <td>${number(source.reviewBurden?.reviewItems)} reviews<small>${number(source.reviewBurden?.per100Listings, "n/a")} / 100 listings</small></td>
    <td>${number(source.requests?.succeeded)} ok / ${number(source.requests?.failed)} failed</td>
    <td>${escapeHtml(source.health?.operationalState || "unknown")}</td>
  </tr>`).join("")}</tbody></table><p class="jobhunt-method-note">Canonical jobs are counted once per source contribution. Cross-source overlap is shown separately and may corroborate evidence.</p></div>`;
}

export function renderApplicationAnalytics(data) {
  if (!data) return empty("Application analytics unavailable", "Try loading this view again.");
  const population = data.population || {};
  const rates = data.rates || {};
  const timing = data.timing || {};
  const funnel = data.funnel || {};
  return `<div class="jobhunt-analytics-stack">
    <div class="jobhunt-insight-metrics">
      ${metric("Applications", number(population.denominator), data.filters?.window || "window")}
      ${metric("Response rate", percent(rates.response), rates.response?.lowSample ? `Low sample; minimum ${number(rates.response.minimumSample)}` : "documented responses")}
      ${metric("Interview rate", percent(rates.interview), "documented events")}
      ${metric("Offer rate", percent(rates.offer), "documented events")}
    </div>
    <section class="jobhunt-analytics-card"><h2>Funnel</h2><div class="jobhunt-funnel">${Object.entries(funnel).map(([stage, count]) => `<div><span>${escapeHtml(stage)}</span><strong>${number(count)}</strong><small>of ${number(population.denominator)}</small></div>`).join("")}</div></section>
    <section class="jobhunt-analytics-card"><h2>Timing</h2><div class="jobhunt-insight-metrics">${Object.entries(timing).map(([key, item]) => metric(key.replaceAll(/([A-Z])/g, " $1"), item.median == null ? "Unknown" : `${number(item.median)} days`, `${number(item.sample)} measured; ${number(item.censored)} censored`)).join("")}</div></section>
    <section class="jobhunt-analytics-card"><h2>By Track</h2>${data.byTrack?.length ? `<div class="jobhunt-table-wrap"><table class="jobhunt-data-table"><thead><tr><th>Track</th><th>Applications</th><th>Responses</th><th>Interviews</th><th>Offers</th></tr></thead><tbody>${data.byTrack.map((item) => `<tr><td>${escapeHtml(item.trackId)}</td><td>${number(item.applications)}</td><td>${number(item.responses)}</td><td>${number(item.interviews)}</td><td>${number(item.offers)}</td></tr>`).join("")}</tbody></table></div>` : `<p>No attributed applications.</p>`}</section>
    <section class="jobhunt-analytics-card"><h2>By discovery source</h2>${data.byDiscoverySource?.length ? `<div class="jobhunt-table-wrap"><table class="jobhunt-data-table"><thead><tr><th>Source</th><th>Applications</th><th>Responses</th><th>Interviews</th><th>Offers</th></tr></thead><tbody>${data.byDiscoverySource.map((item) => `<tr><td>${escapeHtml(item.source)}</td><td>${number(item.applications)}</td><td>${number(item.responses)}</td><td>${number(item.interviews)}</td><td>${number(item.offers)}</td></tr>`).join("")}</tbody></table></div>` : `<p>No source-attributed applications.</p>`}<h3>Structured outcome reasons</h3><p>${(data.outcomeReasons || []).length ? data.outcomeReasons.map((item) => `${escapeHtml(item.reason)} (${number(item.count)})`).join("; ") : "No structured outcome reasons recorded."}</p></section>
    <p class="jobhunt-method-note">${escapeHtml(data.definitions?.trackAttribution || "")}</p>
  </div>`;
}

function salaryLabel(group) {
  if (!group) return "Insufficient evidence";
  if (group.status !== "sufficient") return `${number(group.count)} observations (insufficient)`;
  return `${number(group.medianLower, "?")} - ${number(group.medianUpper, "?")} ${group.currency} gross/month (${number(group.count)} jobs)`;
}

function scenarioForm(item) {
  const scenario = item.economicScenario;
  const costs = scenario?.assumptions?.monthlyCosts || {};
  const entry = (key) => costs[key] || {};
  const updated = entry("housing").updatedAt || new Date().toISOString().slice(0, 10);
  const source = entry("housing").source || "manual estimate";
  const assumptions = scenario?.assumptions || {};
  const provenanceRows = Object.entries(costs).map(([key, assumption]) => `<tr><td>${escapeHtml(key)}</td><td>${number(assumption.value)} ${escapeHtml(item.track.currency)}</td><td>${escapeHtml(assumption.source || "Unknown")}</td><td>${escapeHtml(String(assumption.updatedAt || "Unknown").slice(0, 10))}</td></tr>`).join("");
  return `<details class="jobhunt-scenario-editor"><summary>View or edit economic scenario</summary>${scenario ? `<p><strong>${escapeHtml(scenario.name)} · version ${number(scenario.version)}</strong></p><div class="jobhunt-table-wrap"><table class="jobhunt-data-table"><thead><tr><th>Assumption</th><th>Value</th><th>Source</th><th>Updated</th></tr></thead><tbody>${provenanceRows || `<tr><td colspan="4">No living-cost values recorded.</td></tr>`}</tbody></table></div>` : `<p>No scenario has been saved. Blank costs remain unknown.</p>`}<form data-scenario-form data-track-id="${escapeHtml(item.track.id)}">
    <label><span>Scenario name</span><input name="name" required value="${escapeHtml(scenario?.name || `${item.track.name} scenario`)}"></label>
    <label><span>Currency</span><input name="currency" required value="${escapeHtml(item.track.currency === "unknown" ? "" : item.track.currency)}"></label>
    ${["housing", "utilities", "food", "transport", "other"].map((key) => `<label><span>${escapeHtml(key)} (blank = unknown)</span><input name="${key}" type="number" min="0" step="0.01" value="${escapeHtml(value(entry(key).value, ""))}"></label>`).join("")}
    <label><span>Assumption source</span><input name="source" required value="${escapeHtml(source)}"></label>
    <label><span>Updated</span><input name="updatedAt" type="date" required value="${escapeHtml(String(updated).slice(0, 10))}"></label>
    <label><span>Estimated net / month</span><input name="netAmount" type="number" min="0" step="0.01" value="${escapeHtml(value(scenario?.assumptions?.netMonthlyEstimate?.amount, ""))}" placeholder="optional"></label>
    <label><span>Jurisdiction</span><input name="jurisdiction" value="${escapeHtml(scenario?.assumptions?.netMonthlyEstimate?.jurisdiction || "")}" placeholder="required with net"></label>
    <label><span>Tax model/version</span><input name="taxModelVersion" value="${escapeHtml(scenario?.assumptions?.netMonthlyEstimate?.taxModelVersion || "")}" placeholder="manual-estimate@1"></label>
    <label><span>Tax year</span><input name="year" type="number" value="${escapeHtml(value(scenario?.assumptions?.netMonthlyEstimate?.year, new Date().getFullYear()))}"></label>
    <label class="jobhunt-field-wide"><span>Deductions included/ignored</span><input name="deductions" value="${escapeHtml(scenario?.assumptions?.netMonthlyEstimate?.deductions || "")}"></label>
    <label><span>Relocation cost</span><input name="relocationCost" type="number" min="0" step="0.01" value="${escapeHtml(value(assumptions.relocationCost?.value, ""))}" placeholder="optional"></label>
    <label><span>FX rate to base</span><input name="fxRate" type="number" min="0" step="0.000001" value="${escapeHtml(value(assumptions.fx?.rateToBase, ""))}" placeholder="optional"></label>
    <label><span>FX base currency</span><input name="baseCurrency" value="${escapeHtml(assumptions.fx?.baseCurrency || "")}" placeholder="PLN"></label>
    <button class="jobhunt-primary-action" type="submit">Save new scenario version</button>
  </form></details>`;
}

export function renderTradeoffMatrix(data, tracks = [], selected = []) {
  const items = data?.tracks || [];
  const selector = `<fieldset class="jobhunt-track-compare-picker"><legend>Compare 2-5 Tracks</legend>${tracks.map((track) => `<label><input type="checkbox" data-tradeoff-track value="${escapeHtml(track.id)}"${selected.includes(track.id) ? " checked" : ""}><span>${escapeHtml(track.name)}</span></label>`).join("")}</fieldset>`;
  if (selected.length < 2) return `${selector}${empty("Choose at least two Tracks", "The matrix compares factual rows and explicit scenarios; it never declares a winner.")}`;
  if (!items.length) return `${selector}${empty("Trade-off evidence unavailable", "Try refreshing the selected Tracks.")}`;
  const rows = [
    ["Current jobs", (item) => number(item.currentJobs)],
    ["Observed jobs", (item) => number(item.observedJobs)],
    ["Salary evidence", (item) => salaryLabel(item.salaryEvidence)],
    ["Estimated net", (item) => item.estimatedNetMonthly == null ? "Unavailable" : `${number(item.estimatedNetMonthly)} ${item.track.currency} (estimate)`],
    ["Scenario living costs", (item) => item.monthlyLivingCosts == null ? "Incomplete" : `${number(item.monthlyLivingCosts)} ${item.track.currency}`],
    ["Estimated monthly remainder", (item) => item.estimatedMonthlyRemainder == null ? "Unavailable" : `${number(item.estimatedMonthlyRemainder)} ${item.track.currency} (scenario estimate)`],
    ["Common-currency remainder", (item) => item.estimatedRemainderInBaseCurrency == null ? "No manual FX" : `${number(item.estimatedRemainderInBaseCurrency)} ${item.commonCurrency} (scenario estimate)`],
    ["Required skill gaps", (item) => number(item.requiredSkillGaps)],
    ["Evaluation unknowns", (item) => number(item.evaluationUnknowns)],
    ["Jobs with Evaluation unknowns", (item) => percent(item.evaluationUnknownRate)],
    ["Language requirements", (item) => (item.languageRequirements || []).map((entry) => `${entry.value} (${entry.jobCount}/${entry.denominator})`).join("; ") || `Unknown in ${number(item.languageRequirementCoverage?.unknown)} / ${number(item.languageRequirementCoverage?.denominator)} jobs`],
    ["Relocation", (item) => item.relocationRequired == null ? "Unknown" : item.relocationRequired ? "Required/relevant" : "Not marked"],
    ["Uncertainty", (item) => (item.uncertainty || []).join("; ") || "No listed scenario gaps"],
  ];
  return `${selector}<div class="jobhunt-table-wrap"><table class="jobhunt-data-table jobhunt-tradeoff-table"><thead><tr><th>Dimension</th>${items.map((item) => `<th>${escapeHtml(item.track.name)}</th>`).join("")}</tr></thead><tbody>${rows.map(([label, pick]) => `<tr><th>${escapeHtml(label)}</th>${items.map((item) => `<td>${escapeHtml(pick(item))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="jobhunt-method-note">No winner or aggregate career score is calculated. FX, tax, and living-cost values only appear when explicitly saved with provenance.</p>
    <div class="jobhunt-scenario-grid">${items.map(scenarioForm).join("")}</div>`;
}

export function renderTrackAnalytics(data) {
  if (!data) return empty("Track analytics are loading", "Market, current Evaluations, and applications will appear here.");
  const evaluations = data.evaluations || {};
  return `<section class="jobhunt-track-analytics"><div class="jobhunt-insight-metrics">
    ${metric("Current jobs", number(data.market?.populations?.current?.denominator), `${data.window} window`)}
    ${metric("Evaluated", number(evaluations.evaluatedJobs), `of ${number(evaluations.population?.denominator)} current jobs`)}
    ${metric("Blocker-free", number(evaluations.blockerFreeJobs), "current Pack J Evaluations")}
    ${metric("Applications", number(data.applications?.population?.denominator), `${data.window} submitted`)}
  </div><div class="jobhunt-two-column"><div><h3>Evaluation distribution</h3>${(evaluations.dimensions || []).map((item) => `<p><strong>${escapeHtml(item.dimension)}: ${escapeHtml(item.state)}</strong><span>${number(item.count)}</span></p>`).join("") || "<p>No current Evaluation evidence.</p>"}<h3>Application outcomes</h3><p><strong>Responses</strong><span>${percent(data.applications?.rates?.response)}</span></p><p><strong>Interviews</strong><span>${percent(data.applications?.rates?.interview)}</span></p><p><strong>Offers</strong><span>${percent(data.applications?.rates?.offer)}</span></p></div><div><h3>Market evidence</h3><p><strong>Salary coverage</strong><span>${number(data.market?.coverage?.salary?.known)} / ${number(data.market?.coverage?.salary?.denominator)}</span></p><p><strong>Required gaps</strong><span>${number(evaluations.requiredGaps)}</span></p><p><strong>Unknown findings</strong><span>${number(evaluations.unknownFindings)}</span></p>${Object.values(data.market?.coverage || {}).slice(0, 8).map((item) => `<p><strong>${escapeHtml(item.label)}</strong><span>${number(item.known)} / ${number(item.denominator)}</span></p>`).join("")}<a href="${escapeHtml(data.skillIntelligence?.href || "#skills")}">Open detailed Pack K skill evidence</a></div></div></section>`;
}

export function renderCareerIntelligence(data, templates = []) {
  const suggestions = data?.suggestions || [];
  const proposals = data?.trackProposals || [];
  return `<div class="jobhunt-analytics-stack">
    <div class="jobhunt-validation" data-tone="neutral"><strong>Hypotheses, not decisions.</strong> Deterministic title families require at least ${number(data?.minimumSample)} recurring current jobs and explicit Profile overlap. Assessments are supporting context only.</div>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Adjacent directions</span><h2>Evidence-backed hypotheses</h2></div></div>${suggestions.length ? `<div class="jobhunt-intelligence-grid">${suggestions.map((item) => `<article><span class="jobhunt-badge">${escapeHtml(item.confidenceCategory)}</span><h3>${escapeHtml(item.roleFamily)}</h3><p>${number(item.observedJobCount)} recurring jobs / ${number(item.population?.denominator)} current jobs.</p><h4>Shared Profile evidence</h4><ul>${item.sharedStrengths.map((skill) => `<li>${escapeHtml(skill.displayLabel)}: ${number(skill.observedJobs)} jobs; Profile record ${escapeHtml(skill.profileEvidence?.recordId || "unknown")}</li>`).join("")}</ul><h4>Explicit gaps / unknowns</h4><p>${escapeHtml([...(item.explicitGaps || []).map((x) => `${x.label} (${x.jobs})`), ...(item.unknowns || []).map((x) => `${x.label} unknown (${x.jobs})`)].join("; ") || "None in current Pack J evidence.")}</p></article>`).join("")}</div>` : empty("Insufficient recurring evidence", "No current title family meets both the recurring-job threshold and Profile-overlap rule.")}</section>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Track proposals</span><h2>Explicit decisions only</h2></div></div>${proposals.length ? `<div class="jobhunt-intelligence-grid">${proposals.map((item) => `<article><span class="jobhunt-badge">${escapeHtml(item.state)}</span><h3>${escapeHtml(item.proposedName)}</h3><p>${escapeHtml(item.evidence?.adjacency?.whySuggested?.join(" ") || "Evidence is recorded in the proposal.")}</p><div class="jobhunt-row-actions"><button data-proposal-action="save" data-proposal-key="${escapeHtml(item.proposalKey)}">Save for review</button><button data-proposal-action="accept" data-proposal-key="${escapeHtml(item.proposalKey)}">Accept and create Track</button><button data-proposal-action="dismiss" data-proposal-key="${escapeHtml(item.proposalKey)}">Dismiss</button></div><form data-proposal-experiment data-proposal-key="${escapeHtml(item.proposalKey)}"><select name="templateId">${templates.map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.title)}</option>`).join("")}</select><button type="submit">Create experiment</button></form></article>`).join("")}</div>` : empty("No new Track proposals", "Directions already represented by existing Tracks are not proposed again.")}</section>
  </div>`;
}

function ratingSelect(name, minimum = 1, maximum = 5) {
  const values = [];
  for (let current = minimum; current <= maximum; current += 1) values.push(current);
  return `<select name="${name}" required><option value="">Choose</option>${values.map((item) => `<option value="${item}">${item}</option>`).join("")}</select>`;
}

export function renderExperiments(data, templates = [], tracks = []) {
  const items = data?.items || [];
  return `<div class="jobhunt-analytics-stack"><section class="jobhunt-analytics-card"><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">New experiment</span><h2>Test a hypothesis cheaply</h2></div></div><form class="jobhunt-experiment-create" data-experiment-create>
    <label><span>Template</span><select name="templateId" required>${templates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.title)} - ${number(item.plannedMinutes)} min</option>`).join("")}</select></label>
    <label><span>Track (optional)</span><select name="trackId"><option value="">No Track</option>${tracks.map((track) => `<option value="${escapeHtml(track.id)}">${escapeHtml(track.name)}</option>`).join("")}</select></label>
    <label><span>Skill reference (optional)</span><input name="skillReference" placeholder="skill:SQL"></label>
    <button class="jobhunt-primary-action" type="submit">Create planned experiment</button>
  </form><p class="jobhunt-method-note">Templates are starting points, not validated instruments. Creation never starts an experiment.</p></section>
  <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Experiment log</span><h2>Durable observations</h2></div></div>${items.length ? `<div class="jobhunt-experiment-list">${items.map((item) => `<article><div><span class="jobhunt-badge">${escapeHtml(item.status)}</span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.hypothesis)}</p><small>${number(item.plannedMinutes, "Unknown")} min planned${item.actualMinutes == null ? "" : ` / ${number(item.actualMinutes)} min actual`} | task ${escapeHtml(item.taskDefinitionVersion)}</small></div>
    ${item.status === "planned" ? `<div class="jobhunt-row-actions"><button data-experiment-action="start" data-experiment-id="${escapeHtml(item.id)}">Start</button><button data-experiment-action="abandon" data-experiment-id="${escapeHtml(item.id)}">Abandon</button></div>` : ""}
    ${item.status === "active" ? `<form class="jobhunt-experiment-complete" data-experiment-complete data-experiment-id="${escapeHtml(item.id)}"><label>Actual minutes<input name="actualMinutes" type="number" min="0" required></label><label>Interest${ratingSelect("interestRating")}</label><label>Difficulty${ratingSelect("difficultyRating")}</label><label>Frustration${ratingSelect("frustrationRating")}</label><label>Confidence change${ratingSelect("confidenceChangeRating", -2, 2)}</label><label>Continue<select name="desireToContinue" required><option value="">Choose</option><option value="true">Yes</option><option value="false">No</option></select></label><label class="jobhunt-field-wide">Notes<textarea name="notes"></textarea></label><button class="jobhunt-primary-action" type="submit">Complete and preserve evidence</button><button type="button" data-experiment-action="abandon" data-experiment-id="${escapeHtml(item.id)}">Abandon</button></form>` : ""}
    ${item.status === "completed" ? `<div class="jobhunt-experiment-outcome"><p>Interest ${number(item.interestRating)} | difficulty ${number(item.difficultyRating)} | frustration ${number(item.frustrationRating)} | confidence ${number(item.confidenceChangeRating)} | continue ${item.desireToContinue ? "yes" : "no"}</p>${(item.events || []).filter((event) => event.type === "note_added").length ? `<ul>${item.events.filter((event) => event.type === "note_added").map((event) => `<li>${escapeHtml(event.payload?.note || "")}</li>`).join("")}</ul>` : ""}<form data-experiment-insight data-experiment-id="${escapeHtml(item.id)}"><label><span>Reviewed skill name</span><input name="displayName" required></label><label><span>Level 0-5</span><input name="level" type="number" min="0" max="5" required></label><label><input name="confirm" type="checkbox" required> I reviewed this Profile update</label><button type="submit">Use experiment to update Profile</button></form><form data-experiment-followup data-experiment-id="${escapeHtml(item.id)}" data-track-id="${escapeHtml(item.trackId || "")}"><label><span>Follow-up experiment</span><select name="templateId">${templates.map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.title)}</option>`).join("")}</select></label><button type="submit">Create planned follow-up</button></form><form data-experiment-note data-experiment-id="${escapeHtml(item.id)}"><label><span>Append reinterpretation note</span><textarea name="note" required></textarea></label><button type="submit">Append note</button></form></div>` : ""}
  </article>`).join("")}</div>` : empty("No Career Experiments yet", "Create one from a bounded template, a Track, a proposal, or a skill hypothesis.")}</section></div>`;
}

export function renderInsightsWorkspace({ tab = "market", window = "90d", data = null, tracks = [], selectedTrackIds = [], templates = [] } = {}) {
  const content = {
    market: () => renderMarketAnalytics(data), sources: () => renderSourceAnalytics(data),
    applications: () => renderApplicationAnalytics(data),
    tracks: () => renderTradeoffMatrix(data, tracks, selectedTrackIds),
    career: () => renderCareerIntelligence(data, templates),
    experiments: () => renderExperiments(data, templates, tracks),
  }[tab] || (() => renderMarketAnalytics(data));
  return `<section class="jobhunt-insights"><nav class="jobhunt-insights-tabs" aria-label="Insights sections">${INSIGHT_TABS.map(([key, label]) => `<a href="#insights/${key}" class="${tab === key ? "is-active" : ""}"${tab === key ? ' aria-current="page"' : ""}>${escapeHtml(label)}</a>`).join("")}</nav><div class="jobhunt-insights-toolbar"><p>All counts show their population or denominator. Unknown stays visible.</p>${["market", "sources", "applications", "tracks"].includes(tab) ? windowControl(window) : ""}</div>${content()}</section>`;
}

export function createJobhuntInsightsController({ root, api, tracks = [], tab = "market", onStatus = () => {} } = {}) {
  const state = { tab, window: "90d", tracks, selectedTrackIds: tracks.slice(0, 2).map((item) => item.id), data: null, templates: [], loading: false };

  function render() {
    if (!root) return;
    if (state.loading && !state.data) root.innerHTML = `<div class="jobhunt-workspace-loading"><span class="jobhunt-skeleton jobhunt-skeleton-title"></span><span class="jobhunt-skeleton"></span></div>`;
    else root.innerHTML = renderInsightsWorkspace(state);
  }

  async function refresh() {
    state.loading = true; render();
    try {
      if (["career", "experiments"].includes(state.tab) && !state.templates.length) {
        state.templates = (await api.experimentTemplates()).items || [];
      }
      if (state.tab === "market") state.data = await api.marketAnalytics({ window: state.window });
      else if (state.tab === "sources") state.data = await api.sourceAnalytics({ window: state.window });
      else if (state.tab === "applications") state.data = await api.applicationAnalytics({ window: state.window });
      else if (state.tab === "tracks") state.data = state.selectedTrackIds.length >= 2 ? await api.tradeoffAnalytics(state.selectedTrackIds, { window: state.window }) : { tracks: [] };
      else if (state.tab === "career") state.data = await api.careerIntelligence();
      else state.data = await api.experiments();
    } catch (error) {
      onStatus(error?.message || "Insights could not be loaded.", "error");
      state.data = null;
    } finally { state.loading = false; render(); }
  }

  root?.addEventListener("change", async (event) => {
    if (event.target.matches("[data-insights-window]")) { state.window = event.target.value; state.data = null; await refresh(); }
    if (event.target.matches("[data-tradeoff-track]")) {
      const selected = [...root.querySelectorAll("[data-tradeoff-track]:checked")].map((item) => item.value);
      if (selected.length > 5) { event.target.checked = false; onStatus("Choose at most five Tracks.", "warning"); return; }
      state.selectedTrackIds = selected; state.data = null; await refresh();
    }
  });

  root?.addEventListener("click", async (event) => {
    const proposal = event.target.closest("[data-proposal-action]");
    const experiment = event.target.closest("[data-experiment-action]");
    try {
      if (proposal) {
        await api.decideTrackProposal(proposal.dataset.proposalKey, proposal.dataset.proposalAction);
        onStatus("Track proposal decision saved.", "success"); await refresh();
      } else if (experiment) {
        await api.experimentCommand(experiment.dataset.experimentId, experiment.dataset.experimentAction, {});
        onStatus("Career Experiment updated.", "success"); await refresh();
      }
    } catch (error) { onStatus(error?.message || "Action failed.", "error"); }
  });

  root?.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form.matches("[data-scenario-form],[data-experiment-create],[data-experiment-complete],[data-experiment-insight],[data-experiment-followup],[data-experiment-note],[data-proposal-experiment]")) return;
    event.preventDefault();
    const fields = new FormData(form);
    try {
      if (form.matches("[data-scenario-form]")) {
        const source = String(fields.get("source") || "").trim();
        const updatedAt = String(fields.get("updatedAt") || "");
        const monthlyCosts = Object.fromEntries(["housing", "utilities", "food", "transport", "other"]
          .filter((key) => String(fields.get(key) || "").trim() !== "")
          .map((key) => [key, { value: Number(fields.get(key)), source, updatedAt }]));
        const assumptions = { monthlyCosts };
        if (String(fields.get("netAmount") || "").trim()) assumptions.netMonthlyEstimate = { amount: Number(fields.get("netAmount")), taxModelVersion: fields.get("taxModelVersion"), year: Number(fields.get("year")), jurisdiction: fields.get("jurisdiction"), deductions: fields.get("deductions"), source, updatedAt };
        if (String(fields.get("relocationCost") || "").trim()) assumptions.relocationCost = { value: Number(fields.get("relocationCost")), source, updatedAt };
        if (String(fields.get("fxRate") || "").trim()) assumptions.fx = { rateToBase: Number(fields.get("fxRate")), baseCurrency: fields.get("baseCurrency"), source, updatedAt };
        await api.saveEconomicScenario(form.dataset.trackId, { name: fields.get("name"), currency: fields.get("currency"), assumptions });
        onStatus("A new economic scenario version was saved.", "success"); await refresh();
      } else if (form.matches("[data-experiment-create]")) {
        await api.createExperiment({ templateId: fields.get("templateId"), trackId: fields.get("trackId") || undefined, skillReference: fields.get("skillReference") || undefined });
        onStatus("Planned Career Experiment created.", "success"); await refresh();
      } else if (form.matches("[data-proposal-experiment]")) {
        const saved = await api.decideTrackProposal(form.dataset.proposalKey, "save");
        await api.createExperiment({ templateId: fields.get("templateId"), proposalId: saved.proposal.id, evidence: { proposalKey: form.dataset.proposalKey } });
        onStatus("Planned proposal experiment created.", "success"); await refresh();
      } else if (form.matches("[data-experiment-complete]")) {
        await api.experimentCommand(form.dataset.experimentId, "complete", { actualMinutes: Number(fields.get("actualMinutes")), interestRating: Number(fields.get("interestRating")), difficultyRating: Number(fields.get("difficultyRating")), frustrationRating: Number(fields.get("frustrationRating")), confidenceChangeRating: Number(fields.get("confidenceChangeRating")), desireToContinue: fields.get("desireToContinue") === "true", notes: fields.get("notes") });
        onStatus("Completed observations were preserved.", "success"); await refresh();
      } else if (form.matches("[data-experiment-followup]")) {
        await api.createExperiment({ templateId: fields.get("templateId"), trackId: form.dataset.trackId || undefined, evidence: { followupFromExperimentId: form.dataset.experimentId } });
        onStatus("Planned follow-up experiment created.", "success"); await refresh();
      } else if (form.matches("[data-experiment-note]")) {
        await api.experimentCommand(form.dataset.experimentId, "notes", { note: fields.get("note") });
        onStatus("A note was appended without changing completed observations.", "success"); await refresh();
      } else {
        const displayName = String(fields.get("displayName") || "").trim();
        await api.experimentCommand(form.dataset.experimentId, "apply-insight", { confirm: fields.get("confirm") === "on", collection: "skills", record: { displayName, normalizedKey: displayName.toLowerCase(), level: Number(fields.get("level")), confidence: 3 } });
        onStatus("Reviewed experiment insight added to the Career Profile.", "success"); await refresh();
      }
    } catch (error) { onStatus(error?.message || "Action failed.", "error"); }
  });

  return { state, render, refresh };
}
