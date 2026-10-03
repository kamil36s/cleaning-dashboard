import { escapeHtml } from "./utils.js";

function count(value) {
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function statusPill(tone, text) {
  return `<span class="jobhunt-signal is-${escapeHtml(tone)}">${escapeHtml(text)}</span>`;
}

function evaluationSignals(evaluation) {
  const counts = evaluation?.counts || {};
  const signals = [];
  if (count(counts.blockers)) signals.push(statusPill("critical", `${count(counts.blockers)} blocker${count(counts.blockers) === 1 ? "" : "s"}`));
  else if (evaluation) signals.push(statusPill("positive", "No blockers"));
  if (count(counts.gaps)) signals.push(statusPill("negative", `${count(counts.gaps)} gap${count(counts.gaps) === 1 ? "" : "s"}`));
  if (count(counts.unknowns)) signals.push(statusPill("warning", `${count(counts.unknowns)} unknown`));
  if (count(counts.supportedRequired)) signals.push(statusPill("positive", `${count(counts.supportedRequired)} supported`));
  return signals.join("") || statusPill("neutral", "Not evaluated");
}

export function isCareerProfileEmpty(profile = {}) {
  return !profile.currentRoleTitle
    && !profile.headline
    && !profile.professionalSummary
    && ["experience", "education", "certifications", "languages", "skills", "preferences", "constraints"]
      .every((key) => !(profile[key] || []).length);
}

function attentionCard(item) {
  return `<a class="jobhunt-attention-card is-${escapeHtml(item.tone || "neutral")}" href="#${escapeHtml(item.href || "home")}">
    <span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><small>${escapeHtml(item.help || "")}</small>
  </a>`;
}

function opportunityCard(job) {
  const evaluations = job.evaluations || [];
  const lead = evaluations[0] || null;
  const sourceNames = (job.sources || [job.source?.name]).filter(Boolean);
  return `<article class="jobhunt-opportunity-card">
    <div class="jobhunt-opportunity-head">
      <div><span>${escapeHtml(job.company || "Unknown company")}</span><h3>${escapeHtml(job.role || "Untitled role")}</h3></div>
      ${job.isNew ? statusPill("informational", "New") : ""}
    </div>
    <p>${escapeHtml([job.location?.city, job.location?.country, job.location?.workMode].filter(Boolean).join(" · ") || "Location unknown")}</p>
    <div class="jobhunt-signal-row">${lead ? `<strong>${escapeHtml(lead.trackName || "Track")}</strong>${evaluationSignals(lead)}` : statusPill("neutral", "Choose a Track to evaluate")}</div>
    <footer><span>${escapeHtml(sourceNames.join(" + ") || "Manual")}</span><a href="#jobs/${encodeURIComponent(job.id)}">Open job <span aria-hidden="true">→</span></a></footer>
  </article>`;
}

function trackCard(track) {
  return `<a class="jobhunt-track-pulse-card" href="#track/${encodeURIComponent(track.id)}/overview">
    <div><span class="jobhunt-badge is-track-${escapeHtml(track.status || "exploring")}">${escapeHtml(track.status || "exploring")}</span><h3>${escapeHtml(track.name)}</h3></div>
    <dl>
      <div><dt>Current jobs</dt><dd>${count(track.currentJobs)}</dd></div>
      <div><dt>Blocker-free</dt><dd>${count(track.blockerFree)}</dd></div>
      <div><dt>With unknowns</dt><dd>${count(track.withUnknowns)}</dd></div>
    </dl>
    <span>${track.topGap ? `Top explicit gap: ${escapeHtml(track.topGap)}` : "Open Track details"}</span>
  </a>`;
}

function onboarding(home) {
  const steps = home.onboarding || [];
  return `<section class="jobhunt-onboarding">
    <span class="jobhunt-section-label">Get started</span>
    <h2>Build a useful job-search signal</h2>
    <p>Complete these foundations once, then Home can focus on opportunities and actions.</p>
    <ol>${steps.map((step) => `<li class="${step.complete ? "is-complete" : ""}"><span>${step.complete ? "✓" : step.order}</span><div><strong>${escapeHtml(step.title)}</strong><small>${escapeHtml(step.description)}</small></div>${step.complete ? `<em>Done</em>` : `<a href="#${escapeHtml(step.href)}">Continue</a>`}</li>`).join("")}</ol>
  </section>`;
}

export function renderJobhuntHome(home = {}) {
  if (home.firstRun) return onboarding(home);
  const attention = home.attention || {};
  const cards = [
    { label: "New jobs", value: count(attention.newJobs), help: "Ready to review", href: "jobs", tone: "informational" },
    { label: "Need review", value: count(attention.reviewItems) + count(attention.duplicateCandidates), help: "Data decisions", href: "review", tone: attention.reviewItems || attention.duplicateCandidates ? "warning" : "positive" },
    { label: "Follow-ups", value: count(attention.followUpsDue), help: "Due now", href: "applications", tone: attention.followUpsDue ? "critical" : "positive" },
    { label: "Unknowns", value: count(attention.jobsWithUnknowns), help: "Across current Evaluations", href: "jobs", tone: attention.jobsWithUnknowns ? "warning" : "neutral" },
  ];
  const sourceIssue = (home.sources || []).find((source) => source.actionRequired);
  const insights = home.insights || {};
  return `<div class="jobhunt-home">
    ${sourceIssue ? `<a class="jobhunt-degraded-banner" href="#sources"><span aria-hidden="true">!</span><div><strong>${escapeHtml(sourceIssue.name)} needs attention</strong><small>${escapeHtml(sourceIssue.message || "Saved jobs remain available.")}</small></div><span>Review source →</span></a>` : ""}
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Attention</span><h2>What needs you now</h2></div></div><div class="jobhunt-attention-grid">${cards.map(attentionCard).join("")}</div></section>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Recent opportunities</span><h2>New and current jobs</h2></div><a href="#jobs">Browse all jobs</a></div>
      ${(home.recentOpportunities || []).length ? `<div class="jobhunt-opportunity-grid">${home.recentOpportunities.map(opportunityCard).join("")}</div>` : `<div class="jobhunt-empty-state"><strong>No active jobs yet</strong><p>Add a job or enable a source to begin.</p><div><button type="button" class="jobhunt-primary-action" data-home-action="add-job">Add job</button><a class="jobhunt-secondary-action" href="#sources">Set up a source</a></div></div>`}
    </section>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Track pulse</span><h2>Your search strategies</h2></div><a href="#tracks">Manage Tracks</a></div>
      ${(home.tracks || []).length ? `<div class="jobhunt-track-pulse-grid">${home.tracks.map(trackCard).join("")}</div>` : `<div class="jobhunt-empty-state"><strong>No active Tracks</strong><p>Choose the career directions you actually want to explore.</p><a class="jobhunt-primary-action" href="#tracks">Choose Tracks</a></div>`}
    </section>
    <section class="jobhunt-home-insights"><div><span class="jobhunt-section-label">Evidence pulse</span><h2>Market and experiments</h2><p>${count(insights.newJobs30d)} jobs observed in 30 days · ${count(insights.activeExperiments)} active experiments · ${count(insights.savedTrackProposals)} saved proposals.</p><small>Salary coverage: ${insights.salaryCoveragePercent == null ? "unknown" : `${count(insights.salaryCoveragePercent)}%`} of the 30-day observed population.</small></div><a class="jobhunt-secondary-action" href="#insights/market">Open Insights</a></section>
    <section class="jobhunt-home-flow"><div><span class="jobhunt-section-label">Application workflow</span><h2>Keep momentum</h2><p>${count(attention.applicationsNeedingAction)} applications have a next action. ${count(attention.interviewsUpcoming)} interviews are active.</p></div><a class="jobhunt-secondary-action" href="#applications">Open pipeline</a></section>
  </div>`;
}
