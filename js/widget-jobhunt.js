import {
  JOBHUNT_CHANGED_EVENT,
  getFollowUpsDue,
  loadJobOffers,
} from "./jobhunt-store.js";
import { initializeJobhuntAuthority, jobhuntApi } from "./jobhunt-api.js";
import { escapeHtml } from "./utils.js";

const card = document.getElementById("jobhunt-card");
const root = document.getElementById("jobhunt-root");

function metric(label, value, tone = "neutral") {
  return `<div class="jobhunt-widget-metric is-${escapeHtml(tone)}"><strong>${Number(value || 0)}</strong><span>${escapeHtml(label)}</span></div>`;
}

function renderFirstRun() {
  root.innerHTML = `<div class="jobhunt-widget-current-empty">
    <span class="jobhunt-section-label">Job Hunt</span>
    <strong>Set up your profile and choose a Track</strong>
    <p>Start discovering relevant jobs with explainable, Track-specific signals.</p>
    <a class="jobhunt-widget-button" href="./jobhunt.html#profile">Set up Job Hunt</a>
  </div>`;
}

function renderUnavailable() {
  root.innerHTML = `<div class="jobhunt-widget-current-empty is-error">
    <strong>Job Hunt is temporarily unavailable</strong>
    <p>SQLite is authoritative. Start the dashboard API to refresh this card.</p>
    <a class="jobhunt-widget-button" href="./jobhunt.html">Open Job Hunt</a>
  </div>`;
}

function evaluationLine(opportunity) {
  const evaluation = opportunity?.evaluations?.[0];
  if (!evaluation) return `<span>No Track Evaluation yet</span>`;
  const counts = evaluation.counts || {};
  const parts = [
    Number(counts.blockers || 0) ? `${Number(counts.blockers)} blocker${Number(counts.blockers) === 1 ? "" : "s"}` : "blocker-free",
    Number(counts.unknowns || 0) ? `${Number(counts.unknowns)} unknown` : null,
  ].filter(Boolean);
  return `<span>${escapeHtml(evaluation.trackName || "Track")} · ${escapeHtml(parts.join(" · "))}</span>`;
}

function renderCurrent(home = {}) {
  if (home.firstRun) {
    renderFirstRun();
    return;
  }
  const attention = home.attention || {};
  const insights = home.insights || {};
  const opportunity = home.recentOpportunities?.[0] || null;
  const sourceIssue = (home.sources || []).find((source) => source.actionRequired);
  root.innerHTML = `<div class="jobhunt-widget-current">
    <div class="jobhunt-widget-grid">
      ${metric("jobs / 30d", insights.newJobs30d ?? attention.newJobs, "info")}
      ${metric("need review", Number(attention.reviewItems || 0) + Number(attention.duplicateCandidates || 0), attention.reviewItems || attention.duplicateCandidates ? "warning" : "positive")}
      ${metric("follow-ups due", attention.followUpsDue, attention.followUpsDue ? "critical" : "positive")}
    </div>
    ${opportunity ? `<section class="jobhunt-widget-opportunity">
      <span>Top current opportunity</span>
      <strong>${escapeHtml(opportunity.role || "Untitled role")} · ${escapeHtml(opportunity.company || "Unknown company")}</strong>
      ${evaluationLine(opportunity)}
      <a href="./jobhunt.html#jobs/${encodeURIComponent(opportunity.id)}">Open job →</a>
    </section>` : `<section class="jobhunt-widget-opportunity"><span>Opportunities</span><strong>No active jobs yet</strong><a href="./jobhunt.html#sources">Set up a source →</a></section>`}
    ${sourceIssue ? `<a class="jobhunt-widget-warning" href="./jobhunt.html#sources"><span aria-hidden="true">!</span><span><strong>${escapeHtml(sourceIssue.name)} needs attention</strong><small>Existing jobs are still available.</small></span></a>` : ""}
    ${(Number(insights.activeExperiments || 0) || Number(insights.plannedExperiments || 0)) ? `<a class="jobhunt-widget-warning is-neutral" href="./jobhunt.html#insights/experiments"><span aria-hidden="true">◇</span><span><strong>${Number(insights.activeExperiments || 0)} active Career Experiments</strong><small>${Number(insights.plannedExperiments || 0)} planned · open durable evidence</small></span></a>` : ""}
  </div>`;
}

function legacyHome() {
  const offers = loadJobOffers();
  const active = offers.filter((offer) => !["archived", "expired", "rejected"].includes(offer.status));
  return {
    firstRun: offers.length === 0,
    attention: {
      newJobs: active.filter((offer) => ["new", "to_review"].includes(offer.status)).length,
      reviewItems: 0,
      duplicateCandidates: 0,
      followUpsDue: getFollowUpsDue(offers).length,
    },
    recentOpportunities: active.slice(0, 1),
    sources: [],
  };
}

async function refreshWidget() {
  const authority = await initializeJobhuntAuthority();
  if (authority.mode === "unavailable") {
    renderUnavailable();
    return;
  }
  if (authority.mode === "legacy") {
    renderCurrent(legacyHome());
    return;
  }
  try {
    const result = await jobhuntApi.overview();
    renderCurrent(result.home || { firstRun: !result.summary?.total, attention: result.summary || {} });
  } catch {
    renderUnavailable();
  }
}

if (card && root) {
  root.innerHTML = `<div class="jobhunt-widget-current-empty"><span>Loading Job Hunt…</span></div>`;
  refreshWidget();
  window.addEventListener("storage", (event) => {
    if (event.key?.startsWith("dashboard.jobhunt.")) refreshWidget();
  });
  window.addEventListener(JOBHUNT_CHANGED_EVENT, refreshWidget);
}
