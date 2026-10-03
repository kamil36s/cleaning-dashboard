import { escapeHtml } from "./utils.js";

const HISTORICAL_STATUSES = new Set(["archived", "expired", "rejected"]);

function lower(value) {
  return String(value || "").toLocaleLowerCase();
}

export function jobEvaluationSummary(evaluation) {
  const counts = evaluation?.counts || {};
  return {
    blockers: Number(counts.blockers || 0),
    gaps: Number(counts.gaps || 0),
    unknowns: Number(counts.unknowns || 0),
    supported: Number(counts.supportedRequired || 0),
  };
}

export function filterJobhuntJobs(jobs = [], filters = {}, evaluations = new Map()) {
  const query = lower(filters.search).trim();
  return jobs.filter((job) => {
    const evaluation = evaluations.get(job.id);
    const summary = jobEvaluationSummary(evaluation);
    const historical = Boolean(job.sourceExpired) || HISTORICAL_STATUSES.has(job.applicationStatus || job.status);
    if (filters.history === "current" && historical) return false;
    if (filters.history === "historical" && !historical) return false;
    if (filters.trackId && !evaluation) return false;
    if (filters.stage && filters.stage !== "all" && (job.applicationStatus || job.status) !== filters.stage) return false;
    if (filters.source && filters.source !== "all" && lower(job.source?.name) !== lower(filters.source)) return false;
    if (filters.location && !lower(`${job.location?.city || ""} ${job.location?.country || ""}`).includes(lower(filters.location))) return false;
    if (filters.workMode && filters.workMode !== "all" && job.location?.workMode !== filters.workMode) return false;
    if (filters.blockers === "none" && (!evaluation || summary.blockers > 0)) return false;
    if (filters.blockers === "present" && summary.blockers === 0) return false;
    if (filters.unknowns === "present" && summary.unknowns === 0) return false;
    if (filters.unknowns === "none" && (!evaluation || summary.unknowns > 0)) return false;
    if (query && !lower(`${job.company} ${job.role} ${job.location?.city} ${job.location?.country}`).includes(query)) return false;
    return true;
  });
}

function signal(tone, label) {
  return `<span class="jobhunt-signal is-${tone}">${escapeHtml(label)}</span>`;
}

function evaluationSignals(evaluation) {
  if (!evaluation) return signal("neutral", "No Evaluation for selected Track");
  const summary = jobEvaluationSummary(evaluation);
  return [
    summary.blockers ? signal("critical", `${summary.blockers} blocker${summary.blockers === 1 ? "" : "s"}`) : signal("positive", "No blockers"),
    summary.gaps ? signal("negative", `${summary.gaps} gaps`) : "",
    summary.unknowns ? signal("warning", `${summary.unknowns} unknown`) : "",
    summary.supported ? signal("positive", `${summary.supported} supported`) : "",
  ].join("");
}

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export function renderJobsBrowser({ jobs = [], tracks = [], filters = {}, evaluations = new Map(), selectedId = null } = {}) {
  const visible = filterJobhuntJobs(jobs, filters, evaluations);
  const sources = [...new Set(jobs.map((job) => job.source?.name).filter(Boolean))].sort();
  const stages = [...new Set(jobs.map((job) => job.applicationStatus || job.status).filter(Boolean))].sort();
  const option = (value, label, current) => `<option value="${escapeHtml(value)}"${value === current ? " selected" : ""}>${escapeHtml(label)}</option>`;
  return `<div class="jobhunt-jobs-layout">
    <aside class="jobhunt-job-filters" aria-label="Job filters">
      <div class="jobhunt-filter-heading"><strong>Filters</strong><button type="button" data-jobs-action="clear-filters">Clear</button></div>
      <label><span>Search</span><input type="search" data-job-filter="search" value="${escapeHtml(filters.search || "")}" placeholder="Role or company"></label>
      <label><span>Availability</span><select data-job-filter="history">${option("current", "Current jobs", filters.history)}${option("historical", "Historical jobs", filters.history)}${option("all", "All jobs", filters.history)}</select></label>
      <label><span>Track</span><select data-job-filter="trackId"><option value="">Choose a Track</option>${tracks.map((track) => option(track.id, track.name, filters.trackId)).join("")}</select></label>
      <label><span>Application stage</span><select data-job-filter="stage"><option value="all">All stages</option>${stages.map((stage) => option(stage, stage.replaceAll("_", " "), filters.stage)).join("")}</select></label>
      <label><span>Source</span><select data-job-filter="source"><option value="all">All sources</option>${sources.map((source) => option(source, source, filters.source)).join("")}</select></label>
      <label><span>Location</span><input data-job-filter="location" value="${escapeHtml(filters.location || "")}" placeholder="City or country"></label>
      <label><span>Work model</span><select data-job-filter="workMode">${option("all", "Any work model", filters.workMode)}${option("remote", "Remote", filters.workMode)}${option("hybrid", "Hybrid", filters.workMode)}${option("onsite", "On-site", filters.workMode)}${option("unknown", "Unknown", filters.workMode)}</select></label>
      <label><span>Blockers</span><select data-job-filter="blockers">${option("all", "Any blocker state", filters.blockers)}${option("none", "No blockers", filters.blockers)}${option("present", "Has blockers", filters.blockers)}</select></label>
      <label><span>Unknowns</span><select data-job-filter="unknowns">${option("all", "Any unknown state", filters.unknowns)}${option("present", "Has unknowns", filters.unknowns)}${option("none", "No unknowns", filters.unknowns)}</select></label>
    </aside>
    <section class="jobhunt-job-list-pane" id="jobhunt-offers-panel" aria-label="Jobs">
      <div class="jobhunt-pane-head"><div><strong>${visible.length} job${visible.length === 1 ? "" : "s"}</strong><span>${filters.trackId ? "Evaluation signals use the selected Track." : "Choose a Track to compare blockers, gaps, and unknowns."}</span></div><button type="button" class="jobhunt-primary-action" data-jobs-action="add">+ Add job</button></div>
      <div class="jobhunt-offers-list" id="jobhunt-offers-list">${visible.length ? visible.map((job) => {
        const evaluation = evaluations.get(job.id);
        return `<button type="button" class="jobhunt-job-row${selectedId === job.id ? " is-selected" : ""}" data-job-id="${escapeHtml(job.id)}">
          <div class="jobhunt-job-row-top"><div><span>${escapeHtml(job.company || "Unknown company")}</span><strong>${escapeHtml(job.role || "Untitled role")}</strong></div><span class="jobhunt-badge is-status-${escapeHtml(job.applicationStatus || job.status)}">${escapeHtml((job.applicationStatus || job.status || "unknown").replaceAll("_", " "))}</span></div>
          <p>${escapeHtml([job.location?.city, job.location?.country, job.location?.workMode].filter(Boolean).join(" · ") || "Location unknown")}</p>
          <div class="jobhunt-signal-row">${evaluationSignals(evaluation)}</div>
          <footer><span>${escapeHtml(job.source?.name || "manual")}</span><time>${escapeHtml(job.expiresAt ? `Deadline ${job.expiresAt}` : "No deadline")}</time></footer>
        </button>`;
      }).join("") : `<div class="jobhunt-empty-state"><strong>No jobs match these filters</strong><p>Clear a filter or choose another Track.</p><button type="button" class="jobhunt-secondary-action" data-jobs-action="clear-filters">Clear filters</button></div>`}</div>
      <div id="jobhunt-offers-empty" hidden></div>
    </section>
    <section class="jobhunt-job-detail-pane" id="jobhunt-details" aria-label="Job detail">
      <div class="jobhunt-empty-state"><strong>Select a job</strong><p>Job facts, Track Evaluations, application actions, and source evidence will appear here.</p></div>
    </section>
  </div>`;
}

export function renderJobDetail({ job, application, evaluations, tracks, facts = null, factsLoading = false } = {}) {
  if (!job) return `<div class="jobhunt-empty-state"><strong>Job unavailable</strong><p>This job could not be loaded. Your job list still works.</p></div>`;
  const targets = evaluations?.targets || [];
  const events = application?.events || [];
  const current = application?.application || job.application || {};
  const requirements = job.requirements || {};
  const originalUrl = safeExternalUrl(job.source?.url);
  const list = (items, empty) => (items || []).length ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p class="jobhunt-muted">${escapeHtml(empty)}</p>`;
  return `<article class="jobhunt-job-detail">
    <header class="jobhunt-job-detail-header">
      <div><span class="jobhunt-section-label">${escapeHtml(job.company || "Unknown company")}</span><h2>${escapeHtml(job.role || "Untitled role")}</h2><p>${escapeHtml([job.location?.city, job.location?.country, job.location?.workMode, job.contract?.type].filter(Boolean).join(" · ") || "Details unknown")}</p></div>
      <div class="jobhunt-job-action-stack">
        <button class="jobhunt-primary-action" type="button" data-job-command="applied" data-job-id="${escapeHtml(job.id)}">Mark applied</button>
        <button class="jobhunt-secondary-action" type="button" data-job-command="follow_up_sent" data-job-id="${escapeHtml(job.id)}">Follow-up sent</button>
        <button class="jobhunt-quiet-button" type="button" data-job-action="edit" data-job-id="${escapeHtml(job.id)}">Edit</button>
        <button class="jobhunt-quiet-button is-destructive" type="button" data-job-command="archive" data-job-id="${escapeHtml(job.id)}">Archive</button>
      </div>
    </header>
    <div class="jobhunt-job-meta">
      <div><span>Stage</span><strong>${escapeHtml((current.status || job.applicationStatus || job.status || "unknown").replaceAll("_", " "))}</strong></div>
      <div><span>Deadline</span><strong>${escapeHtml(job.expiresAt || "Not stated")}</strong></div>
      <div><span>Where this job came from</span><strong>${escapeHtml(job.source?.name || "Manual")}</strong></div>
    </div>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Evaluation</span><h3>Track-specific fit</h3></div></div>
      ${targets.length ? `<div class="jobhunt-evaluation-summary-list">${targets.map((target) => `<article><div><strong>${escapeHtml(target.track?.name || "Track")}</strong><span>${escapeHtml(target.evaluation?.state || "not evaluated")}</span></div><div class="jobhunt-signal-row">${evaluationSignals(target.evaluation)}</div>${target.evaluation ? `<a href="#track/${encodeURIComponent(target.track.id)}/jobs">Open Track</a>` : `<button type="button" data-evaluate-track="${escapeHtml(target.track?.id || "")}" data-job-id="${escapeHtml(job.id)}">Evaluate now</button>`}</article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">Assign this job to a Track to evaluate it.</div>`}
    </section>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Requirements</span><h3>What the job asks for</h3></div></div><h4>Required</h4>${list(requirements.mustHave, "No required facts extracted.")}<h4>Preferred</h4>${list(requirements.niceToHave, "No preferred facts extracted.")}<h4>Tools</h4>${list(requirements.tools, "No tools extracted.")}</section>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Application</span><h3>Your workflow</h3></div></div>
      <dl class="jobhunt-application-facts"><div><dt>Next action</dt><dd>${escapeHtml(job.nextAction || "Review")}</dd></div><div><dt>Applied</dt><dd>${escapeHtml(current.dateApplied || "Not yet")}</dd></div><div><dt>Follow-up</dt><dd>${escapeHtml(current.followUpDate || "Not scheduled")}</dd></div><div><dt>Recruiter</dt><dd>${escapeHtml(current.recruiterName || "Not recorded")}</dd></div></dl>
      ${job.notes ? `<p class="jobhunt-note">${escapeHtml(job.notes)}</p>` : ""}
      <details><summary>Application history (${events.length})</summary><ol class="jobhunt-history-list">${events.map((event) => `<li><span>${escapeHtml(event.event_type || event.type || "event")}</span><time>${escapeHtml(event.occurred_at || event.timestamp || "")}</time></li>`).join("")}</ol></details>
    </section>
    <section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Tracks</span><h3>Relevant search strategies</h3></div></div><div id="jobhunt-job-tracks" data-job-id="${escapeHtml(job.id)}">${tracks || `<div class="jobhunt-empty-inline">Loading Track assignments…</div>`}</div></section>
    <details class="jobhunt-evidence"${facts ? " open" : ""}><summary>Inspect source evidence</summary><p>Raw provenance and extraction versions are diagnostic context, not application status.</p>${factsLoading ? `<div class="jobhunt-empty-inline">Loading source evidence…</div>` : facts || `<button class="jobhunt-secondary-action" type="button" data-job-action="load-evidence" data-job-id="${escapeHtml(job.id)}">Load evidence</button>`}</details>
    ${originalUrl ? `<a class="jobhunt-original-link" href="${escapeHtml(originalUrl)}" target="_blank" rel="noopener">Open original source ↗</a>` : ""}
  </article>`;
}
