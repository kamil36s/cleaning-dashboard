import { escapeHtml } from "./utils.js";
import { createJobhuntRouter } from "./jobhunt-router.js";
import { renderJobhuntHome } from "./jobhunt-home.js";
import { renderJobsBrowser, renderJobDetail } from "./jobhunt-jobs-view.js";
import {
  loadSourcesWorkspace,
  renderAdvancedShell,
  renderApplicationsWorkspace,
  renderSourcesWorkspace,
} from "./jobhunt-workspaces.js";
import { createJobhuntCareerController } from "./jobhunt-career.js";
import { createJobhuntTracksController } from "./jobhunt-tracks.js";
import { createJobhuntIngestionController } from "./jobhunt-ingestion.js";
import { createJobhuntReviewController, renderFactInspector } from "./jobhunt-extraction.js";
import { createJobhuntDedupeController } from "./jobhunt-dedupe.js";
import { renderSkillIntelligence } from "./jobhunt-skill-intelligence.js";
import { createJobhuntInsightsController } from "./jobhunt-insights.js";
import {
  initializeJobhuntAuthority,
  jobhuntApi,
  notifyJobhuntChanged,
} from "./jobhunt-api.js";
import {
  JOBHUNT_PRIORITIES,
  JOBHUNT_STATUSES,
  findPossibleDuplicate,
  getJobhuntSummary,
  importJobOffers,
  loadJobOffers,
  loadJobhuntMatchSettings,
  normalizeJobOffer,
  saveJobhuntMatchSettings,
  updateJobOffer,
  upsertJobOffer,
  validateJobOfferPayload,
} from "./jobhunt-store.js";

const THEME_STORAGE_KEY = "dashboard.jobhunt.theme";

const WORKSPACE_META = {
  home: ["Home", "What deserves your attention right now."],
  jobs: ["Jobs", "Browse opportunities and inspect one job without unrelated clutter."],
  tracks: ["Tracks", "Separate search strategies with their own Evaluation and market evidence."],
  applications: ["Applications", "Follow every application, next action, and outcome."],
  profile: ["Career Profile", "Maintain the evidence used by Track Evaluations."],
  skills: ["Skills", "Compare your skills with demand inside one Track."],
  insights: ["Insights", "Market evidence, Track trade-offs, career hypotheses, and experiments."],
  sources: ["Sources", "Simple setup and health for NAV, Pracuj, and Jobbnorge."],
  review: ["Review", "Resolve data questions and duplicate candidates in one inbox."],
  advanced: ["Advanced", "Evidence, operations, histories, and legacy compatibility."],
};

const elements = {
  root: document.getElementById("jobhunt-workspace-root"),
  title: document.getElementById("jobhunt-workspace-title"),
  description: document.getElementById("jobhunt-workspace-description"),
  status: document.getElementById("jobhunt-status"),
  theme: document.getElementById("jobhunt-theme-toggle"),
  add: document.getElementById("jobhunt-add-manually"),
  import: document.getElementById("jobhunt-open-import"),
  manualDialog: document.getElementById("jobhunt-manual-dialog"),
  manualForm: document.getElementById("jobhunt-manual-form"),
  manualTitle: document.getElementById("jobhunt-manual-title"),
  manualSubmit: document.getElementById("jobhunt-manual-submit"),
  manualError: document.getElementById("jobhunt-manual-error"),
  importDialog: document.getElementById("jobhunt-import-dialog"),
  reviewCount: document.getElementById("jobhunt-review-count"),
};

const state = {
  authority: "loading",
  route: { workspace: "home", canonical: "home" },
  overview: null,
  jobs: null,
  tracks: null,
  sources: null,
  renderToken: 0,
  editingId: null,
  filters: {
    history: "current", trackId: "", stage: "all", source: "all", location: "",
    workMode: "all", blockers: "all", unknowns: "all", search: "",
  },
  evaluationsByTrack: new Map(),
  selectedJob: null,
  selectedJobBundle: null,
  selectedEvidence: null,
  skillTrackId: "",
  matchSettings: null,
};

function setStatus(message = "", tone = "neutral") {
  elements.status.textContent = message;
  elements.status.dataset.tone = tone;
  elements.status.hidden = !message;
}

function setLoading(label = "Loading workspace") {
  elements.root.setAttribute("aria-busy", "true");
  elements.root.innerHTML = `<div class="jobhunt-workspace-loading" role="status" aria-label="${escapeHtml(label)}"><span class="jobhunt-skeleton jobhunt-skeleton-title"></span><span class="jobhunt-skeleton"></span><span class="jobhunt-skeleton"></span></div>`;
}

function setWorkspaceMeta(workspace) {
  const [title, description] = WORKSPACE_META[workspace] || WORKSPACE_META.home;
  elements.title.textContent = title;
  elements.description.textContent = description;
  document.title = `${title} · Job Hunt`;
  document.querySelectorAll("[data-jobhunt-route]").forEach((link) => {
    const active = link.dataset.jobhuntRoute === workspace;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function workspaceError(title, error, retry = true) {
  elements.root.removeAttribute("aria-busy");
  elements.root.innerHTML = `<div class="jobhunt-workspace-error"><span aria-hidden="true">!</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(error?.message || String(error || "Unknown error"))}</p><small>Your other Job Hunt data is still available.</small>${retry ? `<button type="button" class="jobhunt-primary-action" data-workspace-retry>Retry</button>` : ""}</div>`;
}

function readTheme() {
  try { return localStorage.getItem(THEME_STORAGE_KEY) === "dark" ? "dark" : "light"; }
  catch { return "light"; }
}

function applyTheme(theme) {
  document.body.dataset.jobhuntTheme = theme;
  elements.theme.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  try { localStorage.setItem(THEME_STORAGE_KEY, theme); } catch {}
}

function openDialog(dialog) {
  if (!dialog) return;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function closeDialog(dialog) {
  if (!dialog) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

function options(values, selected) {
  return values.map((value) => `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(value.replaceAll("_", " "))}</option>`).join("");
}

function initManualForm() {
  const form = elements.manualForm;
  form.elements.workMode.innerHTML = options(["unknown", "remote", "hybrid", "onsite"], "unknown");
  form.elements.contractType.innerHTML = options(["unknown", "UoP", "B2B", "contract_of_mandate"], "unknown");
}

function resetManualForm() {
  state.editingId = null;
  elements.manualForm.reset();
  elements.manualForm.elements.status.value = "to_review";
  elements.manualForm.elements.priority.value = "unknown";
  elements.manualTitle.textContent = "Add job manually";
  elements.manualSubmit.textContent = "Save job";
  elements.manualError.textContent = "";
}

function populateManualForm(job) {
  resetManualForm();
  state.editingId = job.id;
  elements.manualTitle.textContent = `Edit ${job.company || "job"}`;
  elements.manualSubmit.textContent = "Save changes";
  const form = elements.manualForm;
  form.elements.company.value = job.company || "";
  form.elements.role.value = job.role || "";
  form.elements.city.value = job.location?.city || "";
  form.elements.workMode.value = job.location?.workMode || "unknown";
  form.elements.contractType.value = job.contract?.type || "unknown";
  form.elements.expiresAt.value = job.expiresAt || "";
  form.elements.sourceUrl.value = job.source?.url || "";
  form.elements.notes.value = job.notes || "";
  form.elements.status.value = job.applicationStatus || job.status || "to_review";
  form.elements.priority.value = job.priority || "unknown";
}

function manualPayload() {
  const form = elements.manualForm;
  const value = (name) => String(form.elements[name]?.value || "").trim();
  const existing = state.editingId ? (state.jobs || []).find((job) => job.id === state.editingId) : null;
  const now = new Date().toISOString();
  return normalizeJobOffer({
    ...(existing || {}),
    id: existing?.id,
    company: value("company"), role: value("role"),
    location: { ...(existing?.location || {}), city: value("city") || "unknown", country: existing?.location?.country || "unknown", workMode: value("workMode") || "unknown" },
    contract: { ...(existing?.contract || {}), type: value("contractType") || "unknown" },
    source: { ...(existing?.source || {}), name: existing?.source?.name || "manual", url: value("sourceUrl"), capturedAt: existing?.source?.capturedAt || now },
    expiresAt: value("expiresAt") || null,
    status: value("status") || "to_review", applicationStatus: value("status") || "to_review",
    priority: value("priority") || "unknown", notes: value("notes"),
    createdAt: existing?.createdAt || now, updatedAt: now,
  });
}

function invalidate({ jobs = true, overview = true, sources = false } = {}) {
  if (jobs) state.jobs = null;
  if (overview) state.overview = null;
  if (sources) state.sources = null;
  state.evaluationsByTrack.clear();
}

async function ensureOverview() {
  if (state.overview) return state.overview;
  if (state.authority === "api") state.overview = await jobhuntApi.overview();
  else {
    const jobs = await ensureJobs();
    const summary = getJobhuntSummary(jobs);
    state.overview = {
      summary,
      home: {
        firstRun: jobs.length === 0,
        attention: {
          newJobs: jobs.filter((job) => ["new", "to_review"].includes(job.status)).length,
          reviewItems: 0, duplicateCandidates: 0, followUpsDue: summary.followUpsDue,
          jobsWithUnknowns: 0, interviewsUpcoming: summary.interviewsActive,
          applicationsNeedingAction: jobs.filter((job) => job.nextAction && job.nextAction !== "none").length,
        },
        recentOpportunities: jobs.filter((job) => !["archived", "expired", "rejected"].includes(job.status)).slice(0, 6),
        tracks: [], sources: [],
      },
    };
  }
  const reviewCount = Number(state.overview.home?.attention?.reviewItems || 0) + Number(state.overview.home?.attention?.duplicateCandidates || 0);
  elements.reviewCount.hidden = reviewCount === 0;
  elements.reviewCount.textContent = reviewCount > 99 ? "99+" : String(reviewCount);
  return state.overview;
}

async function ensureJobs() {
  if (state.jobs) return state.jobs;
  state.jobs = state.authority === "api" ? (await jobhuntApi.jobs()).jobs || [] : loadJobOffers();
  return state.jobs;
}

async function ensureTracks() {
  if (state.tracks) return state.tracks;
  state.tracks = state.authority === "api" ? (await jobhuntApi.tracks()).tracks || [] : [];
  return state.tracks;
}

async function evaluationsForTrack(trackId) {
  if (!trackId || state.authority !== "api") return new Map();
  if (!state.evaluationsByTrack.has(trackId)) {
    const result = await jobhuntApi.trackEvaluations(trackId);
    state.evaluationsByTrack.set(trackId, new Map((result.items || []).map((item) => [item.jobId, item])));
  }
  return state.evaluationsByTrack.get(trackId);
}

async function renderHome(token) {
  const overview = await ensureOverview();
  if (token !== state.renderToken) return;
  elements.root.removeAttribute("aria-busy");
  elements.root.innerHTML = renderJobhuntHome(overview.home || {});
}

async function renderJobs(token) {
  const [jobs, tracks, evaluations] = await Promise.all([
    ensureJobs(), ensureTracks(), evaluationsForTrack(state.filters.trackId),
  ]);
  if (token !== state.renderToken) return;
  const selectedId = state.route.jobId || null;
  elements.root.removeAttribute("aria-busy");
  elements.root.innerHTML = renderJobsBrowser({ jobs, tracks, filters: state.filters, evaluations, selectedId });
  if (selectedId) await loadJobDetail(selectedId, token);
}

async function loadJobDetail(jobId, token = state.renderToken) {
  const target = elements.root.querySelector("#jobhunt-details");
  if (!target) return;
  target.innerHTML = `<div class="jobhunt-workspace-loading"><span class="jobhunt-skeleton jobhunt-skeleton-title"></span><span class="jobhunt-skeleton"></span></div>`;
  try {
    let job;
    let application = { application: null, events: [] };
    let evaluations = { targets: [] };
    if (state.authority === "api") {
      const [jobResult, applicationResult, evaluationResult] = await Promise.all([
        jobhuntApi.job(jobId), jobhuntApi.application(jobId), jobhuntApi.jobEvaluations(jobId),
      ]);
      job = jobResult.job;
      application = applicationResult;
      evaluations = evaluationResult;
    } else {
      job = (await ensureJobs()).find((item) => item.id === jobId);
    }
    if (token !== state.renderToken || !elements.root.querySelector("#jobhunt-details")) return;
    state.selectedJob = job;
    state.selectedJobBundle = { job, application, evaluations };
    target.innerHTML = renderJobDetail({ job, application, evaluations });
    if (state.authority === "api") {
      const assignmentTarget = target.querySelector("#jobhunt-job-tracks");
      const assignmentController = createJobhuntTracksController({
        root: null, api: jobhuntApi, onStatus: setStatus,
      });
      await assignmentController.mountJobAssignments(assignmentTarget, job.id);
    }
  } catch (error) {
    target.innerHTML = `<div class="jobhunt-workspace-error"><h2>Could not load this job</h2><p>${escapeHtml(error?.message || "Job detail unavailable")}</p><small>The job list still works.</small><button type="button" class="jobhunt-secondary-action" data-job-action="retry-detail" data-job-id="${escapeHtml(jobId)}">Retry</button></div>`;
  }
}

async function renderTracks(token) {
  elements.root.innerHTML = `<section id="jobhunt-tracks-panel"><div id="jobhunt-tracks-root"><div class="jobhunt-workspace-loading"><span class="jobhunt-skeleton"></span></div></div></section>`;
  const controller = createJobhuntTracksController({
    root: elements.root.querySelector("#jobhunt-tracks-root"), api: jobhuntApi, onStatus: setStatus,
    onJobOpen: (jobId) => router.navigate({ workspace: "jobs", jobId }),
    onTrackNavigate: (trackId, tab) => router.navigate(trackId ? `track/${encodeURIComponent(trackId)}/${tab || "overview"}` : "tracks"),
  });
  if (state.authority !== "api") {
    controller.state.error = "Tracks become available after the durable Job Hunt store is connected.";
    controller.render();
  } else if (state.route.trackId) await controller.openTrack(state.route.trackId, state.route.trackTab);
  else await controller.refresh({ keepDetail: false });
  if (token !== state.renderToken) return;
  elements.root.removeAttribute("aria-busy");
}

async function renderApplications(token) {
  const jobs = await ensureJobs();
  if (token !== state.renderToken) return;
  elements.root.removeAttribute("aria-busy");
  elements.root.innerHTML = renderApplicationsWorkspace(jobs);
}

async function renderProfile(token) {
  elements.root.innerHTML = `<section id="jobhunt-career-panel"><nav class="jobhunt-subnav" aria-label="Profile sections"><button type="button" data-career-tab="profile">Profile</button><button type="button" data-career-tab="assessments">Assessments</button></nav><div id="jobhunt-career-root"></div></section>`;
  const controller = createJobhuntCareerController({ root: elements.root.querySelector("#jobhunt-career-root"), api: jobhuntApi, onStatus: setStatus });
  const tab = state.route.profileTab || "profile";
  controller.state.tab = tab;
  if (state.authority === "api") await controller.refresh({ includeAssessments: true });
  else {
    controller.state.error = "Career Profile requires the durable Job Hunt store.";
    controller.render();
  }
  if (token !== state.renderToken) return;
  elements.root.removeAttribute("aria-busy");
}

async function renderSkills(token) {
  const tracks = await ensureTracks();
  if (!state.skillTrackId) state.skillTrackId = tracks.find((track) => track.status === "active")?.id || tracks[0]?.id || "";
  elements.root.innerHTML = `<div class="jobhunt-skills-workspace"><section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">My skills</span><h2>Profile evidence</h2></div></div><div id="jobhunt-career-root"></div></section><section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Market signals</span><h2>Demand inside a Track</h2></div><label class="jobhunt-inline-select"><span>Track</span><select data-skill-workspace-track>${tracks.map((track) => `<option value="${escapeHtml(track.id)}"${track.id === state.skillTrackId ? " selected" : ""}>${escapeHtml(track.name)}</option>`).join("")}</select></label></div><div id="jobhunt-market-skills-root"><div class="jobhunt-empty-inline">Loading Track demand…</div></div></section></div>`;
  if (state.authority !== "api") {
    elements.root.querySelector("#jobhunt-career-root").innerHTML = `<div class="jobhunt-validation" data-tone="warning">Skills require the durable Job Hunt store.</div>`;
    elements.root.querySelector("#jobhunt-market-skills-root").innerHTML = "";
    return;
  }
  const career = createJobhuntCareerController({ root: elements.root.querySelector("#jobhunt-career-root"), api: jobhuntApi, onStatus: setStatus });
  career.state.tab = "skills";
  const intelligencePromise = state.skillTrackId ? jobhuntApi.trackSkillIntelligence(state.skillTrackId, { population: "current", window: "90d", sort: "priority" }) : Promise.resolve(null);
  const [, intelligence] = await Promise.all([career.refresh({ includeAssessments: false }), intelligencePromise]);
  if (token !== state.renderToken) return;
  elements.root.querySelector("#jobhunt-market-skills-root").innerHTML = state.skillTrackId
    ? renderSkillIntelligence(intelligence, { window: "current", filter: "all", sort: "priority" })
    : `<div class="jobhunt-empty-state"><strong>Choose a Track first</strong><p>Market demand is always Track-specific.</p><a class="jobhunt-primary-action" href="#tracks">Open Tracks</a></div>`;
  elements.root.removeAttribute("aria-busy");
}

async function renderInsights(token) {
  if (state.authority !== "api") {
    if (token !== state.renderToken) return;
    elements.root.removeAttribute("aria-busy");
    elements.root.innerHTML = `<div class="jobhunt-empty-state"><strong>Insights require the durable Job Hunt store</strong><p>Reconnect the API to calculate bounded, reproducible analytics.</p></div>`;
    return;
  }
  const tracks = await ensureTracks();
  if (token !== state.renderToken) return;
  elements.root.innerHTML = `<div id="jobhunt-insights-root"></div>`;
  const controller = createJobhuntInsightsController({
    root: elements.root.firstElementChild,
    api: jobhuntApi,
    tracks,
    tab: state.route.insightsTab || "market",
    onStatus: setStatus,
  });
  await controller.refresh();
  if (token === state.renderToken) elements.root.removeAttribute("aria-busy");
}

async function renderSources(token, selectedKey = null) {
  if (state.authority !== "api") {
    if (token !== state.renderToken) return;
    elements.root.removeAttribute("aria-busy");
    elements.root.innerHTML = `<div class="jobhunt-empty-state"><strong>Source management is unavailable</strong><p>Reconnect the durable Job Hunt API. Saved browser jobs remain readable in legacy mode.</p><a class="jobhunt-secondary-action" href="#advanced/legacy">Open legacy compatibility</a></div>`;
    return;
  }
  if (!state.sources) state.sources = await loadSourcesWorkspace(jobhuntApi);
  if (token !== state.renderToken) return;
  elements.root.removeAttribute("aria-busy");
  elements.root.innerHTML = renderSourcesWorkspace(state.sources, selectedKey);
}

async function renderReview(token) {
  const filter = state.route.reviewFilter || "all";
  elements.root.innerHTML = `<section id="jobhunt-review-panel"><nav class="jobhunt-review-tabs" aria-label="Review filters">${[["all", "All"], ["job-data", "Job data"], ["duplicates", "Duplicates"], ["sources", "Sources"]].map(([key, label]) => `<a href="#review/${key}" class="${filter === key ? "is-active" : ""}">${label}</a>`).join("")}</nav><div class="jobhunt-review-workspace">${filter !== "duplicates" ? `<section><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Needs review</span><h2>${filter === "sources" ? "Source issues" : "Job data"}</h2></div></div><div id="jobhunt-review-root"></div></section>` : ""}${["all", "duplicates"].includes(filter) ? `<section id="jobhunt-duplicates-panel"><div class="jobhunt-section-heading"><div><span class="jobhunt-section-label">Identity</span><h2>Duplicate candidates</h2></div></div><div id="jobhunt-duplicates-root"></div></section>` : ""}</div></section>`;
  if (state.authority !== "api") {
    elements.root.querySelectorAll("#jobhunt-review-root,#jobhunt-duplicates-root").forEach((root) => { root.innerHTML = `<div class="jobhunt-validation" data-tone="warning">Review requires the durable Job Hunt store.</div>`; });
    return;
  }
  const tasks = [];
  const reviewRoot = elements.root.querySelector("#jobhunt-review-root");
  if (reviewRoot) {
    const review = createJobhuntReviewController({ root: reviewRoot, api: jobhuntApi, onStatus: setStatus });
    tasks.push(review.refresh().then(() => {
      if (filter === "sources") {
        review.state.items = review.state.items.filter((item) => /source|storage|policy|capture/i.test(`${item.reason} ${item.entityType}`));
        review.render();
      }
    }));
  }
  const duplicateRoot = elements.root.querySelector("#jobhunt-duplicates-root");
  if (duplicateRoot) {
    const dedupe = createJobhuntDedupeController({ root: duplicateRoot, api: jobhuntApi, onStatus: setStatus, onChanged: () => invalidate() });
    tasks.push(dedupe.refresh());
  }
  await Promise.all(tasks);
  if (token === state.renderToken) elements.root.removeAttribute("aria-busy");
}

function legacyScore(job) {
  if (job.evaluationSource === "none") return "Not imported";
  return `${Number(job.match?.score || 0)}/100 historical`;
}

async function renderLegacyAdvanced() {
  const jobs = await ensureJobs();
  if (!state.matchSettings) state.matchSettings = state.authority === "api" ? (await jobhuntApi.matchSettings()).settings || [] : loadJobhuntMatchSettings();
  return `<div class="jobhunt-legacy-workspace">
    <div class="jobhunt-validation" data-tone="warning"><strong>Historical compatibility only.</strong> Imported scores are not current Evaluations and are never compared across Tracks.</div>
    <section><div class="jobhunt-section-heading"><div><h3>Imported legacy match data</h3><span>Preserved for recovery and context.</span></div><button id="jobhunt-export" type="button" class="jobhunt-secondary-action" data-legacy-action="export">Export JSON</button></div><div class="jobhunt-legacy-list">${jobs.length ? jobs.map((job) => `<article><div><strong>${escapeHtml(job.company)} · ${escapeHtml(job.role)}</strong><span>${escapeHtml(legacyScore(job))}</span></div><small>${escapeHtml((job.analysis?.skillGaps || []).join(", ") || "No imported gap data")}</small></article>`).join("") : `<div class="jobhunt-empty-inline">No historical jobs.</div>`}</div></section>
    <section id="jobhunt-settings-panel"><h3>Legacy match settings</h3><div class="jobhunt-settings" id="jobhunt-match-settings">${state.matchSettings.map((setting) => `<label><span>${escapeHtml(setting.label)}</span><input type="number" min="0" max="100" data-setting-id="${escapeHtml(setting.id)}" value="${Number(setting.weight || 0)}"></label>`).join("")}</div><button class="jobhunt-secondary-action" id="jobhunt-save-settings" type="button" data-legacy-action="save-settings">Save legacy settings</button></section>
    <section id="jobhunt-import-panel"><h3>Old standardized JSON importer</h3><p>Use only for historical compatibility data. New advertisements belong in Evidence & import.</p><textarea id="jobhunt-import-text" rows="8" spellcheck="false"></textarea><div class="jobhunt-form-actions"><button id="jobhunt-validate-import" class="jobhunt-secondary-action" type="button" data-legacy-action="validate">Validate</button><button id="jobhunt-import-offers" class="jobhunt-primary-action" type="button" data-legacy-action="import" disabled>Import</button><button id="jobhunt-clear-import" class="jobhunt-quiet-button" type="button" data-legacy-action="clear">Clear</button></div><div id="jobhunt-import-result" class="jobhunt-validation"></div></section>
    <div id="jobhunt-best-match" hidden></div><div id="jobhunt-stats" hidden></div><div id="jobhunt-skill-gaps" hidden></div><div id="jobhunt-best-action" hidden></div><div id="jobhunt-week-plan" hidden></div>
  </div>`;
}

async function renderAdvanced(token) {
  const section = state.route.advancedSection || "diagnostics";
  elements.root.innerHTML = renderAdvancedShell(section);
  const target = elements.root.querySelector("#jobhunt-advanced-root");
  if (state.authority !== "api" && section !== "legacy") {
    target.innerHTML = `<div class="jobhunt-validation" data-tone="warning">Advanced operational tools require the durable Job Hunt store.</div>`;
    return;
  }
  if (section === "ingestion") {
    target.innerHTML = `<section id="jobhunt-ingestion-panel"><div id="jobhunt-ingestion-root"></div></section>`;
    const controller = createJobhuntIngestionController({ root: target.querySelector("#jobhunt-ingestion-root"), api: jobhuntApi, onStatus: setStatus, onExtracted: () => invalidate({ sources: true }) });
    await controller.refresh();
  } else if (section === "legacy") {
    target.innerHTML = await renderLegacyAdvanced();
  } else if (section === "merges") {
    target.innerHTML = `<div id="jobhunt-duplicates-root"></div>`;
    const controller = createJobhuntDedupeController({ root: target.firstElementChild, api: jobhuntApi, onStatus: setStatus, onChanged: () => invalidate() });
    await controller.refresh();
  } else if (["evaluations", "policies"].includes(section)) {
    const tracks = await ensureTracks();
    target.innerHTML = `<div class="jobhunt-advanced-link-list">${tracks.map((track) => `<a href="#track/${encodeURIComponent(track.id)}/${section === "policies" ? "policy" : "jobs"}"><strong>${escapeHtml(track.name)}</strong><span>${section === "policies" ? "Open current policy and immutable history" : "Open current Track Evaluations"}</span></a>`).join("")}</div>`;
  } else {
    const [worker, jobs, health] = await Promise.all([
      jobhuntApi.workerStatus().catch((error) => ({ error: error.message })),
      jobhuntApi.workerJobs({ limit: 20 }).catch((error) => ({ error: error.message, jobs: [] })),
      jobhuntApi.ingestionStorageHealth().catch((error) => ({ error: error.message })),
    ]);
    target.innerHTML = `<div class="jobhunt-diagnostics-grid"><article><span>Worker</span><strong>${escapeHtml(worker.worker?.state || "Unavailable")}</strong><p>${escapeHtml(worker.error || `${Number(worker.worker?.counts?.queued || 0)} queued · ${Number(worker.worker?.counts?.running || 0)} running`)}</p></article><article><span>Raw evidence archive</span><strong>${health.healthy === true ? "Healthy" : health.healthy === false ? "Needs attention" : "Unavailable"}</strong><p>${escapeHtml(health.error || `${Number(health.uniqueBlobs || 0)} blobs · ${Number(health.totalRawBytes || 0)} bytes`)}</p></article><article><span>Recent worker jobs</span><strong>${Number(jobs.jobs?.length || 0)}</strong><p>${escapeHtml(jobs.error || "Open Evidence & import for job-level operations.")}</p></article></div>`;
  }
  if (token === state.renderToken) elements.root.removeAttribute("aria-busy");
}

async function renderRoute(route = state.route) {
  state.route = route;
  const token = ++state.renderToken;
  setWorkspaceMeta(route.workspace);
  setLoading(`Loading ${route.workspace}`);
  try {
    if (route.workspace === "home") await renderHome(token);
    else if (route.workspace === "jobs") await renderJobs(token);
    else if (route.workspace === "tracks") await renderTracks(token);
    else if (route.workspace === "applications") await renderApplications(token);
    else if (route.workspace === "profile") await renderProfile(token);
    else if (route.workspace === "skills") await renderSkills(token);
    else if (route.workspace === "insights") await renderInsights(token);
    else if (route.workspace === "sources") await renderSources(token, route.sourceKey || null);
    else if (route.workspace === "review") await renderReview(token);
    else await renderAdvanced(token);
  } catch (error) {
    if (token === state.renderToken) workspaceError(`Could not load ${WORKSPACE_META[route.workspace]?.[0] || "workspace"}`, error);
  }
}

async function persistManual(event) {
  event.preventDefault();
  const job = manualPayload();
  if (!job.company || job.company === "unknown" || !job.role || job.role === "unknown") {
    elements.manualError.textContent = "Company and role are required.";
    return;
  }
  if (!state.editingId && findPossibleDuplicate(job, state.jobs || [])) {
    elements.manualError.textContent = "A similar job already exists. Save only if this is a separate opportunity.";
    return;
  }
  try {
    let savedId = state.editingId || job.id;
    if (state.authority === "api") {
      const result = state.editingId ? await jobhuntApi.updateJob(state.editingId, job) : await jobhuntApi.createJob(job);
      savedId = result.job?.id || savedId;
    } else if (state.authority === "legacy") {
      state.jobs = upsertJobOffer(job, state.jobs || loadJobOffers());
    } else throw new Error("Job Hunt is unavailable; SQLite remains authoritative.");
    closeDialog(elements.manualDialog);
    resetManualForm();
    invalidate();
    notifyJobhuntChanged();
    setStatus("Job saved.", "success");
    router.navigate({ workspace: "jobs", jobId: savedId });
  } catch (error) {
    elements.manualError.textContent = error?.message || "Job could not be saved.";
  }
}

async function commandJob(command, jobId) {
  try {
    if (state.authority === "api") await jobhuntApi.applicationCommand(jobId, { type: command });
    else if (state.authority === "legacy" && command === "archive") state.jobs = updateJobOffer(jobId, { status: "archived", nextAction: "none" }, state.jobs);
    else throw new Error("This application action requires the durable Job Hunt store.");
    invalidate();
    notifyJobhuntChanged();
    setStatus(command === "follow_up_sent" ? "Follow-up marked as sent." : command === "applied" ? "Marked as applied; follow-up scheduled." : "Job archived.", "success");
    await renderRoute(state.route);
  } catch (error) { setStatus(error?.message || "Application action failed.", "error"); }
}

async function loadEvidence(jobId) {
  if (state.authority !== "api" || !state.selectedJobBundle) return;
  const target = elements.root.querySelector("#jobhunt-details");
  target.innerHTML = renderJobDetail({ ...state.selectedJobBundle, factsLoading: true });
  try {
    const data = await jobhuntApi.jobFacts(jobId);
    const facts = renderFactInspector({ runs: [], facts: data.facts || [], projection: data.projection ? { outcome: "canonical", canonicalJobId: jobId, projectionVersion: data.projection.version } : null });
    target.innerHTML = renderJobDetail({ ...state.selectedJobBundle, facts });
    const assignmentController = createJobhuntTracksController({ root: null, api: jobhuntApi, onStatus: setStatus });
    await assignmentController.mountJobAssignments(target.querySelector("#jobhunt-job-tracks"), jobId);
  } catch (error) { setStatus(error?.message || "Source evidence could not be loaded.", "error"); }
}

async function sourceAction(action, key) {
  const method = `${key}${action[0].toUpperCase()}${action.slice(1)}`;
  try {
    if (typeof jobhuntApi[method] !== "function") throw new Error("This source action is unavailable.");
    await jobhuntApi[method]();
    state.sources = null;
    state.overview = null;
    notifyJobhuntChanged();
    setStatus(`${key === "jobbnorge" ? "Jobbnorge" : key === "pracuj" ? "Pracuj JobAlert" : "NAV"} ${action === "sync" ? "sync queued" : action === "pause" ? "paused" : "enabled"}.`, "success");
    await renderSources(++state.renderToken, key);
  } catch (error) { setStatus(error?.message || "Source action failed.", "error"); }
}

function exportJobs() {
  const blob = new Blob([JSON.stringify(state.jobs || [], null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = `jobhunt-offers-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}

async function legacyAction(action) {
  const input = elements.root.querySelector("#jobhunt-import-text");
  const resultRoot = elements.root.querySelector("#jobhunt-import-result");
  const importButton = elements.root.querySelector("#jobhunt-import-offers");
  if (action === "export") { exportJobs(); return; }
  if (action === "clear") { input.value = ""; resultRoot.innerHTML = ""; importButton.disabled = true; return; }
  if (action === "save-settings") {
    const settings = [...elements.root.querySelectorAll("[data-setting-id]")].map((node) => ({ id: node.dataset.settingId, weight: node.value }));
    state.matchSettings = state.authority === "api" ? (await jobhuntApi.updateMatchSettings(settings)).settings : saveJobhuntMatchSettings(settings);
    setStatus("Legacy compatibility settings saved.", "success");
    return;
  }
  const validation = validateJobOfferPayload(input.value, state.jobs || []);
  resultRoot.dataset.tone = validation.ok ? (validation.warnings.length ? "warning" : "success") : "error";
  resultRoot.innerHTML = `<strong>${validation.ok ? `${validation.offers.length} historical offer(s) ready.` : "Import needs fixes."}</strong>${[...validation.errors, ...validation.warnings].length ? `<ul>${[...validation.errors, ...validation.warnings].map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}`;
  importButton.disabled = !validation.ok;
  if (action !== "import" || !validation.ok) return;
  if (state.authority === "api") for (const job of validation.offers) await jobhuntApi.createJob(job);
  else state.jobs = importJobOffers(validation.offers, state.jobs || []);
  input.value = ""; invalidate(); notifyJobhuntChanged();
  setStatus("Historical compatibility data imported.", "success");
  await renderRoute(state.route);
}

function wireEvents() {
  elements.theme.addEventListener("click", () => applyTheme(document.body.dataset.jobhuntTheme === "dark" ? "light" : "dark"));
  elements.add.addEventListener("click", () => { resetManualForm(); openDialog(elements.manualDialog); });
  elements.import.addEventListener("click", () => openDialog(elements.importDialog));
  elements.manualForm.addEventListener("submit", persistManual);
  document.getElementById("jobhunt-manual-close").addEventListener("click", () => closeDialog(elements.manualDialog));
  document.getElementById("jobhunt-manual-cancel").addEventListener("click", () => closeDialog(elements.manualDialog));
  document.getElementById("jobhunt-import-close").addEventListener("click", () => closeDialog(elements.importDialog));
  elements.importDialog.addEventListener("click", (event) => { if (event.target.closest("[data-dialog-close],[data-dialog-route]")) closeDialog(elements.importDialog); });

  let jobFilterTimer = null;
  elements.root.addEventListener("input", (event) => {
    const filter = event.target.closest("[data-job-filter]");
    if (!filter || filter.tagName === "SELECT") return;
    state.filters[filter.dataset.jobFilter] = filter.value;
    const filterName = filter.dataset.jobFilter;
    const selectionStart = filter.selectionStart;
    const selectionEnd = filter.selectionEnd;
    clearTimeout(jobFilterTimer);
    jobFilterTimer = setTimeout(async () => {
      await renderJobs(state.renderToken);
      const replacement = elements.root.querySelector(`[data-job-filter="${filterName}"]`);
      replacement?.focus();
      if (typeof replacement?.setSelectionRange === "function" && selectionStart !== null) {
        replacement.setSelectionRange(selectionStart, selectionEnd);
      }
    }, 120);
  });
  elements.root.addEventListener("change", async (event) => {
    const filter = event.target.closest("[data-job-filter]");
    if (filter) {
      state.filters[filter.dataset.jobFilter] = filter.value;
      await renderJobs(state.renderToken);
      return;
    }
    const skillTrack = event.target.closest("[data-skill-workspace-track]");
    if (skillTrack) { state.skillTrackId = skillTrack.value; await renderSkills(++state.renderToken); }
  });
  elements.root.addEventListener("click", async (event) => {
    if (event.target.closest("[data-workspace-retry]")) { await renderRoute(state.route); return; }
    if (event.target.closest("[data-home-action='add-job'],[data-jobs-action='add']")) { resetManualForm(); openDialog(elements.manualDialog); return; }
    const jobRow = event.target.closest("[data-job-id]:not([data-job-command]):not([data-job-action])");
    if (jobRow) { router.navigate({ workspace: "jobs", jobId: jobRow.dataset.jobId }); return; }
    const applicationJob = event.target.closest("[data-application-job]");
    if (applicationJob) { router.navigate({ workspace: "jobs", jobId: applicationJob.dataset.applicationJob }); return; }
    const clear = event.target.closest("[data-jobs-action='clear-filters']");
    if (clear) {
      state.filters = { history: "current", trackId: "", stage: "all", source: "all", location: "", workMode: "all", blockers: "all", unknowns: "all", search: "" };
      await renderJobs(state.renderToken); return;
    }
    const command = event.target.closest("[data-job-command]");
    if (command) { await commandJob(command.dataset.jobCommand, command.dataset.jobId); return; }
    const jobAction = event.target.closest("[data-job-action]");
    if (jobAction) {
      if (jobAction.dataset.jobAction === "edit") { populateManualForm(state.selectedJob); openDialog(elements.manualDialog); }
      else if (jobAction.dataset.jobAction === "load-evidence") await loadEvidence(jobAction.dataset.jobId);
      else if (jobAction.dataset.jobAction === "retry-detail") await loadJobDetail(jobAction.dataset.jobId);
      return;
    }
    const evaluate = event.target.closest("[data-evaluate-track]");
    if (evaluate) {
      try { await jobhuntApi.evaluateJobTrack(evaluate.dataset.jobId, evaluate.dataset.evaluateTrack); state.evaluationsByTrack.clear(); await loadJobDetail(evaluate.dataset.jobId); }
      catch (error) { setStatus(error?.message || "Evaluation failed.", "error"); }
      return;
    }
    const source = event.target.closest("[data-source-action]");
    if (source) {
      const action = source.dataset.sourceAction;
      if (action === "details") { await renderSources(++state.renderToken, source.dataset.sourceKey); }
      else if (action === "close-details") { await renderSources(++state.renderToken, null); }
      else await sourceAction(action, source.dataset.sourceKey);
      return;
    }
    const careerTab = event.target.closest("[data-career-tab]");
    if (careerTab && state.route.workspace === "profile") {
      router.navigate(careerTab.dataset.careerTab === "assessments" ? "profile/assessments" : "profile");
      return;
    }
    const legacy = event.target.closest("[data-legacy-action]");
    if (legacy) { await legacyAction(legacy.dataset.legacyAction); }
  });
}

const router = createJobhuntRouter({
  onChange: (route) => {
    state.route = route;
    if (state.authority === "loading") {
      setWorkspaceMeta(route.workspace);
      setLoading(`Loading ${route.workspace}`);
      return;
    }
    renderRoute(route);
  },
});

async function bootstrap() {
  applyTheme(readTheme());
  initManualForm();
  wireEvents();
  router.start();
  setStatus("Connecting to the durable Job Hunt store…", "neutral");
  const authority = await initializeJobhuntAuthority();
  state.authority = authority.mode;
  if (authority.mode === "api") {
    const migratedRecords = Number(authority.migration?.imported || 0) + Number(authority.migration?.alreadyExisting || 0);
    setStatus(migratedRecords ? "Your existing Job Hunt data was verified and imported." : "", "success");
  } else if (authority.mode === "legacy") {
    state.jobs = loadJobOffers();
    setStatus("Legacy browser mode is active. Current Evaluations, Tracks, and sources require the dashboard API.", "warning");
  } else {
    setStatus("Job Hunt API is offline. SQLite remains authoritative; local browser writes are disabled.", "error");
  }
  await renderRoute(state.route);
}

bootstrap();
