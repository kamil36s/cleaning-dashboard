import { escapeHtml } from "./utils.js";
import { policyFromForm, renderPolicyEditor, renderTrackEvaluations } from "./jobhunt-evaluations.js";
import { renderSkillIntelligence, skillWindowParams } from "./jobhunt-skill-intelligence.js";
import { renderTrackAnalytics } from "./jobhunt-insights.js";

export const TRACK_STATUSES = ["exploring", "active", "paused", "archived"];
export const SEARCH_PROFILE_STATUSES = ["enabled", "paused", "archived"];
export const PLANNED_SOURCES = [
  ["pracuj", "Pracuj", "available"], ["nofluffjobs", "No Fluff Jobs", "not implemented"],
  ["olx", "OLX", "not implemented"], ["nav", "NAV", "available"],
  ["finn", "FINN", "not implemented / unavailable"],
  ["alfred", "Alfred", "not implemented"],
  ["jobbnorge", "Jobbnorge", "available"],
  ["company_sites", "Company sites", "not implemented"],
  ["email_alerts", "Email alerts", "not implemented"],
];

function csv(values = []) {
  return Array.isArray(values) ? values.join(", ") : "";
}

export function parseTrackList(value) {
  const seen = new Set();
  return String(value || "").split(",").map((item) => item.trim()).filter((item) => {
    const key = item.toLowerCase();
    if (!item || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function statusOptions(status, values) {
  return values.map((value) => `<option value="${value}"${value === status ? " selected" : ""}>${value}</option>`).join("");
}

function unknownBoolOptions(value) {
  return `<option value=""${value == null ? " selected" : ""}>Unknown</option>
    <option value="true"${value === true ? " selected" : ""}>Yes</option>
    <option value="false"${value === false ? " selected" : ""}>No</option>`;
}

function geographyLabel(track) {
  const geography = track.geography || {};
  const places = [...(geography.countries || []), ...(geography.regionsCities || [])];
  const flags = [];
  if (geography.remoteAllowed === true) flags.push("remote relevant");
  if (geography.relocationRelevant === true) flags.push("relocation");
  if (geography.primaryCurrency) flags.push(geography.primaryCurrency);
  return [...places, ...flags].join(" · ") || "Geography not set";
}

export function renderTrackList(tracks = []) {
  if (!tracks.length) {
    return `<div class="jobhunt-empty-inline">No Career Tracks yet. Create one to record a search strategy.</div>`;
  }
  return `<div class="jobhunt-track-grid">${tracks.map((track) => `
    <article class="jobhunt-track-card" data-track-card="${escapeHtml(track.id)}">
      <div class="jobhunt-track-card-head">
        <span class="jobhunt-badge is-track-${escapeHtml(track.status)}">${escapeHtml(track.status)}</span>
        <time>${escapeHtml(String(track.updatedAt || "").slice(0, 10))}</time>
      </div>
      <h3>${escapeHtml(track.name)}</h3>
      <p>${escapeHtml(track.purpose || "No purpose recorded.")}</p>
      <small>${escapeHtml(geographyLabel(track))}</small>
      <div class="jobhunt-track-counts"><span><strong>${track.searchProfileCount}</strong> search profiles</span><span><strong>${track.assignedJobCount}</strong> assigned jobs</span></div>
      <div class="jobhunt-row-actions">
        <button type="button" class="jobhunt-primary-action" data-track-action="open" data-track-id="${escapeHtml(track.id)}">Open</button>
        <button type="button" class="jobhunt-row-action" data-track-action="edit" data-track-id="${escapeHtml(track.id)}">Edit</button>
        ${track.status === "archived"
          ? `<button type="button" class="jobhunt-row-action" data-track-action="status" data-track-status="exploring" data-track-id="${escapeHtml(track.id)}">Restore</button>`
          : `<button type="button" class="jobhunt-row-action" data-track-action="status" data-track-status="${track.status === "paused" ? "active" : "paused"}" data-track-id="${escapeHtml(track.id)}">${track.status === "paused" ? "Activate" : "Pause"}</button>
             <button type="button" class="jobhunt-row-action is-danger" data-track-action="status" data-track-status="archived" data-track-id="${escapeHtml(track.id)}">Archive</button>`}
      </div>
    </article>
  `).join("")}</div>`;
}

function trackEditor(track = null) {
  const geography = track?.geography || {};
  return `<form class="jobhunt-career-form jobhunt-track-form" data-track-form data-track-id="${escapeHtml(track?.id || "")}">
    <label><span>Name</span><input name="name" required maxlength="160" value="${escapeHtml(track?.name || "")}"></label>
    <label><span>Stable slug</span><input name="slug" maxlength="80" value="${escapeHtml(track?.slug || "")}" placeholder="generated from name"></label>
    <label><span>Status</span><select name="status">${statusOptions(track?.status || "exploring", TRACK_STATUSES)}</select></label>
    <label><span>Primary currency</span><input name="primaryCurrency" maxlength="12" value="${escapeHtml(geography.primaryCurrency || "")}" placeholder="Unknown"></label>
    <label class="jobhunt-field-wide"><span>Purpose</span><textarea name="purpose" rows="3" maxlength="4000">${escapeHtml(track?.purpose || "")}</textarea></label>
    <label><span>Countries (comma-separated codes)</span><input name="countries" value="${escapeHtml(csv(geography.countries))}" placeholder="PL, NO"></label>
    <label><span>Cities / regions (comma-separated)</span><input name="regionsCities" value="${escapeHtml(csv(geography.regionsCities))}" placeholder="Kraków"></label>
    <label><span>Remote relevant</span><select name="remoteAllowed">${unknownBoolOptions(geography.remoteAllowed)}</select></label>
    <label><span>Relocation relevant</span><select name="relocationRelevant">${unknownBoolOptions(geography.relocationRelevant)}</select></label>
    <label class="jobhunt-field-wide"><span>Why am I exploring this Track?</span><textarea name="rationale" rows="3" maxlength="8000">${escapeHtml(track?.rationale || "")}</textarea></label>
    <label class="jobhunt-field-wide"><span>Notes</span><textarea name="notes" rows="3" maxlength="8000">${escapeHtml(track?.notes || "")}</textarea></label>
    <div class="jobhunt-form-actions jobhunt-field-wide">
      <button class="jobhunt-primary-action" type="submit">${track ? "Save Track" : "Create Track"}</button>
      <button class="jobhunt-ghost-action" type="button" data-track-action="cancel-edit">Cancel</button>
    </div>
  </form>`;
}

function sourceHintFields(selected = []) {
  return `<fieldset class="jobhunt-source-hints jobhunt-field-wide"><legend>Discovery sources</legend>
    <p>Durable source bindings. Availability is independent per adapter.</p>
    <div>${PLANNED_SOURCES.map(([key, label, availability]) => `<label><input type="checkbox" name="plannedSourceKeys" value="${key}"${selected.includes(key) ? " checked" : ""}> <span>${escapeHtml(label)} - ${escapeHtml(availability)}</span></label>`).join("")}</div>
  </fieldset>`;
}

function profileEditor(profile = null) {
  return `<form class="jobhunt-career-form jobhunt-search-profile-form" data-search-profile-form data-profile-id="${escapeHtml(profile?.id || "")}">
    <label><span>Name</span><input name="name" required maxlength="160" value="${escapeHtml(profile?.name || "")}"></label>
    <label><span>Status</span><select name="status">${statusOptions(profile?.status || "enabled", SEARCH_PROFILE_STATUSES)}</select></label>
    <label class="jobhunt-field-wide"><span>Role family / free-text intent</span><textarea name="roleIntent" rows="2" maxlength="2000">${escapeHtml(profile?.roleIntent || "")}</textarea></label>
    <label><span>Include terms</span><input name="includeKeywords" value="${escapeHtml(csv(profile?.includeKeywords))}" placeholder="manual QA, test analyst"></label>
    <label><span>Exclude terms</span><input name="excludeKeywords" value="${escapeHtml(csv(profile?.excludeKeywords))}" placeholder="senior manager"></label>
    <label><span>Countries</span><input name="countries" value="${escapeHtml(csv(profile?.countries))}" placeholder="NO"></label>
    <label><span>Cities / regions</span><input name="regionsCities" value="${escapeHtml(csv(profile?.regionsCities))}"></label>
    <label><span>Work models</span><input name="workModels" value="${escapeHtml(csv(profile?.workModels))}" placeholder="remote, hybrid"></label>
    <label><span>Schedule hints</span><input name="scheduleHints" value="${escapeHtml(csv(profile?.scheduleHints))}" placeholder="weekend, shifts"></label>
    <label><span>Contract hints</span><input name="contractHints" value="${escapeHtml(csv(profile?.contractHints))}"></label>
    <label><span>Language hints</span><input name="languageHints" value="${escapeHtml(csv(profile?.languageHints))}"></label>
    <label><span>Seniority hints</span><input name="seniorityHints" value="${escapeHtml(csv(profile?.seniorityHints))}"></label>
    <label class="jobhunt-field-wide"><span>Notes</span><textarea name="notes" rows="3" maxlength="8000">${escapeHtml(profile?.notes || "")}</textarea></label>
    ${sourceHintFields(profile?.plannedSourceKeys || [])}
    <div class="jobhunt-form-actions jobhunt-field-wide">
      <button class="jobhunt-primary-action" type="submit">${profile ? "Save Search Profile" : "Add Search Profile"}</button>
      ${profile ? `<button class="jobhunt-ghost-action" type="button" data-track-action="cancel-profile">Cancel</button>` : ""}
    </div>
  </form>`;
}

export function renderTrackDetail(
  detail,
  editingProfileId = null,
  evaluationData = null,
  evaluationPolicy = null,
  evaluationPolicyHistory = [],
  evaluationFilter = "all",
  skillIntelligence = null,
  skillWindow = "current",
  skillFilter = "all",
  skillSort = "priority",
  skillDetail = null,
  loadingSkillDetail = false,
  activeTab = "all",
  trackAnalytics = null,
) {
  if (!detail?.track) return `<div class="jobhunt-empty-inline">Track is loading…</div>`;
  const { track, searchProfiles = [], assignedJobs = [] } = detail;
  const editingProfile = searchProfiles.find((item) => item.id === editingProfileId) || null;
  const show = (tab) => activeTab === "all" || activeTab === tab;
  return `<div class="jobhunt-track-detail">
    <div class="jobhunt-details-head">
      <div><button type="button" class="jobhunt-ghost-action" data-track-action="back">← All Tracks</button><span class="jobhunt-section-label">${escapeHtml(track.status)}</span><h3>${escapeHtml(track.name)}</h3><p>${escapeHtml(track.purpose || "No purpose recorded.")}</p></div>
      <div class="jobhunt-row-actions"><button type="button" class="jobhunt-row-action" data-track-action="edit" data-track-id="${escapeHtml(track.id)}">Edit Track</button></div>
    </div>
    <nav class="jobhunt-track-tabs" aria-label="Track sections">
      ${[["overview", "Overview"], ["analytics", "Analytics"], ["jobs", "Jobs"], ["skills", "Skills"], ["search", "Search"], ["policy", "Policy"]].map(([tab, label]) => `<button type="button" class="${activeTab === tab || activeTab === "all" ? "is-active" : ""}" data-track-tab="${tab}">${label}</button>`).join("")}
    </nav>
    ${show("overview") ? `<section class="jobhunt-track-overview">
      <div><span>Geography</span><strong>${escapeHtml(geographyLabel(track))}</strong></div>
      <div><span>Evaluation policy</span><strong>${evaluationPolicy ? `Version ${escapeHtml(evaluationPolicy.version)} (aggregate: none)` : escapeHtml(track.evaluationPolicyVersion || "Loading")}</strong></div>
      <div><span>Rationale</span><p>${escapeHtml(track.rationale || "Not recorded")}</p></div>
      <div><span>Notes</span><p>${escapeHtml(track.notes || "Not recorded")}</p></div>
    </section>` : ""}
    ${show("policy") ? (evaluationPolicy ? renderPolicyEditor(evaluationPolicy, evaluationPolicyHistory) : `<section class="jobhunt-career-block"><div class="jobhunt-empty-inline">Evaluation Policy is loading…</div></section>`) : ""}
    ${show("analytics") ? renderTrackAnalytics(trackAnalytics) : ""}
    ${show("jobs") || show("overview") ? renderTrackEvaluations(evaluationData || { items: [] }, evaluationFilter) : ""}
    ${show("skills") ? renderSkillIntelligence(skillIntelligence, {
      window: skillWindow, filter: skillFilter, sort: skillSort,
      detail: skillDetail, loadingDetail: loadingSkillDetail,
    }) : ""}
    ${show("search") ? `<section class="jobhunt-career-block">
      <div class="jobhunt-career-block-head"><div><h3>Search Profiles</h3><span>Discovery intent; only enabled, available adapters may collect.</span></div></div>
      ${searchProfiles.length ? `<div class="jobhunt-career-records">${searchProfiles.map((profile) => `
        <article class="jobhunt-career-record"><div><strong>${escapeHtml(profile.name)}</strong><span>${escapeHtml(profile.status)} · ${escapeHtml(profile.roleIntent || "No role intent")}</span><small>Include: ${escapeHtml(csv(profile.includeKeywords) || "none")} · Exclude: ${escapeHtml(csv(profile.excludeKeywords) || "none")}</small></div>
          <div class="jobhunt-row-actions"><button type="button" class="jobhunt-row-action" data-track-action="edit-profile" data-profile-id="${escapeHtml(profile.id)}">Edit</button>${profile.status !== "archived" ? `<button type="button" class="jobhunt-row-action" data-track-action="profile-status" data-profile-id="${escapeHtml(profile.id)}" data-profile-status="${profile.status === "paused" ? "enabled" : "paused"}">${profile.status === "paused" ? "Resume" : "Pause"}</button><button type="button" class="jobhunt-row-action is-danger" data-track-action="profile-status" data-profile-id="${escapeHtml(profile.id)}" data-profile-status="archived">Archive</button>` : `<button type="button" class="jobhunt-row-action" data-track-action="profile-status" data-profile-id="${escapeHtml(profile.id)}" data-profile-status="enabled">Restore</button>`}</div>
        </article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No Search Profiles for this Track.</div>`}
      ${profileEditor(editingProfile)}
    </section>` : ""}
    ${show("jobs") ? `<section class="jobhunt-career-block"><div class="jobhunt-career-block-head"><div><h3>Assigned jobs</h3><span>Assignment means relevant to this Track, not suitable or a good fit.</span></div></div>
      ${assignedJobs.length ? `<div class="jobhunt-career-records">${assignedJobs.map((job) => `<article class="jobhunt-career-record"><div><strong>${escapeHtml(job.company)} — ${escapeHtml(job.role)}</strong><span>${escapeHtml([job.location?.city, job.location?.country].filter(Boolean).join(", ") || "Unknown location")} · ${escapeHtml(job.applicationStatus)}</span></div><button type="button" class="jobhunt-row-action" data-job-open="${escapeHtml(job.jobId)}">Open job</button></article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No jobs are currently assigned.</div>`}
    </section>` : ""}
  </div>`;
}

export function renderJobTrackAssignment(result) {
  const tracks = result?.tracks || [];
  if (!tracks.length) return `<div class="jobhunt-empty-inline">No Career Tracks are available.</div>`;
  return `<form class="jobhunt-job-track-form" data-job-track-form>
    <p>${escapeHtml(result.assignmentMeaning || "Assignment records relevance, not fit.")}</p>
    <div>${tracks.map((track) => `<label class="${track.trackStatus === "archived" ? "is-archived" : ""}"><input type="checkbox" name="trackIds" value="${escapeHtml(track.trackId)}"${track.assigned ? " checked" : ""}><span>${escapeHtml(track.name)}</span><small>${escapeHtml(track.trackStatus)}</small></label>`).join("")}</div>
    <label class="jobhunt-field"><span>Optional assignment note</span><input name="note" maxlength="2000" placeholder="Why is this job relevant?"></label>
    <button class="jobhunt-primary-action" type="submit">Save Track assignments</button>
  </form>`;
}

function formBool(formData, name) {
  const value = String(formData.get(name) ?? "");
  return value === "" ? null : value === "true";
}

export function createJobhuntTracksController({
  root,
  api,
  onStatus = () => {},
  onJobOpen = () => {},
  onTrackNavigate = null,
} = {}) {
  const state = {
    tracks: [], detail: null, editingTrack: null, editingProfileId: null,
    evaluationData: null, evaluationPolicy: null, evaluationPolicyHistory: [], evaluationFilter: "all",
    skillIntelligence: null, skillWindow: "current", skillFilter: "all", skillSort: "priority",
    skillDetail: null, loadingSkillDetail: false,
    trackAnalytics: null,
    activeTab: "all",
    loading: false, error: null,
  };

  async function loadSkillIntelligence(trackId) {
    if (typeof api.trackSkillIntelligence !== "function") {
      state.skillIntelligence = null;
      return;
    }
    state.skillIntelligence = await api.trackSkillIntelligence(trackId, {
      ...skillWindowParams(state.skillWindow), sort: state.skillSort,
    });
    state.skillDetail = null;
  }

  async function loadTrackWorkspace(trackId) {
    const [detail, policyResult, historyResult, evaluationData, skillIntelligence, trackAnalytics] = await Promise.all([
      api.track(trackId),
      typeof api.trackEvaluationPolicy === "function" ? api.trackEvaluationPolicy(trackId) : Promise.resolve(null),
      typeof api.trackEvaluationPolicyHistory === "function" ? api.trackEvaluationPolicyHistory(trackId) : Promise.resolve({ items: [] }),
      typeof api.trackEvaluations === "function" ? api.trackEvaluations(trackId) : Promise.resolve({ items: [] }),
      typeof api.trackSkillIntelligence === "function"
        ? api.trackSkillIntelligence(trackId, { ...skillWindowParams(state.skillWindow), sort: state.skillSort })
        : Promise.resolve(null),
      typeof api.trackAnalytics === "function"
        ? api.trackAnalytics(trackId, { window: "90d" })
        : Promise.resolve(null),
    ]);
    state.detail = detail;
    state.evaluationPolicy = policyResult?.policy || null;
    state.evaluationPolicyHistory = historyResult?.items || [];
    state.evaluationData = evaluationData || { items: [] };
    state.skillIntelligence = skillIntelligence;
    state.trackAnalytics = trackAnalytics;
    state.skillDetail = null;
  }

  function render() {
    if (!root) return;
    if (state.loading && !state.tracks.length) root.innerHTML = `<div class="jobhunt-empty-inline">Loading Career Tracks…</div>`;
    else if (state.error) root.innerHTML = `<div class="jobhunt-validation" data-tone="error">${escapeHtml(state.error)}</div>`;
    else if (state.editingTrack !== null) root.innerHTML = trackEditor(state.editingTrack || null);
    else if (state.detail) root.innerHTML = renderTrackDetail(
      state.detail,
      state.editingProfileId,
      state.evaluationData,
      state.evaluationPolicy,
      state.evaluationPolicyHistory,
      state.evaluationFilter,
      state.skillIntelligence,
      state.skillWindow,
      state.skillFilter,
      state.skillSort,
      state.skillDetail,
      state.loadingSkillDetail,
      state.activeTab,
      state.trackAnalytics,
    );
    else root.innerHTML = `<div class="jobhunt-track-toolbar"><p>Tracks are user-managed search strategies. They do not calculate suitability.</p><button class="jobhunt-primary-action" type="button" data-track-action="new">+ New Track</button></div>${renderTrackList(state.tracks)}`;
  }

  async function refresh({ keepDetail = true } = {}) {
    state.loading = true;
    state.error = null;
    render();
    try {
      const result = await api.tracks();
      state.tracks = result.tracks || [];
      if (keepDetail && state.detail?.track?.id) await loadTrackWorkspace(state.detail.track.id);
    } catch (error) {
      state.error = error?.message || "Career Tracks could not be loaded.";
    } finally {
      state.loading = false;
      render();
    }
  }

  async function mutate(operation, message) {
    try {
      await operation();
      state.editingTrack = null;
      state.editingProfileId = null;
      await refresh();
      onStatus(message, "success");
    } catch (error) {
      onStatus(error?.message || "Track operation failed.", "error");
    }
  }

  root?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    if (form.matches("[data-track-form]")) {
      const data = new FormData(form);
      const payload = {
        name: String(data.get("name") || "").trim(), slug: String(data.get("slug") || "").trim() || undefined,
        status: String(data.get("status") || "exploring"), purpose: String(data.get("purpose") || "").trim(),
        geography: { countries: parseTrackList(data.get("countries")), regionsCities: parseTrackList(data.get("regionsCities")), remoteAllowed: formBool(data, "remoteAllowed"), relocationRelevant: formBool(data, "relocationRelevant"), primaryCurrency: String(data.get("primaryCurrency") || "").trim() || null },
        rationale: String(data.get("rationale") || "").trim() || null, notes: String(data.get("notes") || "").trim() || null,
      };
      const trackId = form.dataset.trackId;
      await mutate(() => trackId ? api.updateTrack(trackId, payload) : api.createTrack(payload), "Track saved.");
      return;
    }
    if (form.matches("[data-evaluation-policy-form]") && state.detail) {
      await mutate(
        () => api.createTrackEvaluationPolicy(state.detail.track.id, policyFromForm(form)),
        "New Evaluation Policy version saved; recomputation was queued.",
      );
      return;
    }
    if (form.matches("[data-search-profile-form]") && state.detail) {
      const data = new FormData(form);
      const listFields = ["includeKeywords", "excludeKeywords", "countries", "regionsCities", "workModels", "scheduleHints", "contractHints", "languageHints", "seniorityHints"];
      const payload = Object.fromEntries(listFields.map((name) => [name, parseTrackList(data.get(name))]));
      Object.assign(payload, { name: String(data.get("name") || "").trim(), status: String(data.get("status") || "enabled"), roleIntent: String(data.get("roleIntent") || "").trim() || null, notes: String(data.get("notes") || "").trim() || null, plannedSourceKeys: data.getAll("plannedSourceKeys").map(String) });
      const profileId = form.dataset.profileId;
      await mutate(() => profileId ? api.updateSearchProfile(profileId, payload) : api.createSearchProfile(state.detail.track.id, payload), "Search Profile saved.");
    }
  });

  root?.addEventListener("click", async (event) => {
    const job = event.target.closest("[data-job-open]");
    if (job) { onJobOpen(job.dataset.jobOpen); return; }
    const concept = event.target.closest("[data-skill-concept]");
    if (concept && state.detail && typeof api.trackSkillDetail === "function") {
      state.loadingSkillDetail = true;
      render();
      try {
        state.skillDetail = await api.trackSkillDetail(
          state.detail.track.id,
          concept.dataset.skillConcept,
          skillWindowParams(state.skillWindow),
        );
      } catch (error) {
        onStatus(error?.message || "Skill detail could not be loaded.", "error");
      } finally {
        state.loadingSkillDetail = false;
        render();
      }
      return;
    }
    const skillAction = event.target.closest("[data-skill-action]");
    if (skillAction?.dataset.skillAction === "create-experiment" && state.detail) {
      try {
        await api.createExperiment({
          trackId: state.detail.track.id,
          skillReference: skillAction.dataset.skillReference,
          title: `Explore ${skillAction.dataset.skillLabel}`,
          hypothesis: `A bounded practical task will clarify whether developing ${skillAction.dataset.skillLabel} is worthwhile.`,
          taskDefinition: `Complete one safe, realistic ${skillAction.dataset.skillLabel} task and record interest, difficulty, frustration, and desire to continue.`,
          taskDefinitionVersion: "skill-gap-trial@1",
          plannedMinutes: 60,
          evidence: { origin: "pack-k-skill-detail", conceptReference: skillAction.dataset.skillReference },
        });
        onStatus("Planned Career Experiment created from this Pack K skill.", "success");
      } catch (error) {
        onStatus(error?.message || "Career Experiment could not be created.", "error");
      }
      return;
    }
    if (skillAction?.dataset.skillAction === "close-detail") {
      state.skillDetail = null;
      render();
      return;
    }
    const button = event.target.closest("[data-track-action]");
    if (!button) return;
    const action = button.dataset.trackAction;
    const trackId = button.dataset.trackId;
    if (action === "new") { state.editingTrack = false; render(); }
    else if (action === "cancel-edit") { state.editingTrack = null; render(); }
    else if (action === "back") {
      if (onTrackNavigate) { onTrackNavigate(null, null); return; }
      state.detail = null; state.editingProfileId = null; state.evaluationData = null;
      state.evaluationPolicy = null; state.evaluationPolicyHistory = [];
      state.skillIntelligence = null; state.skillDetail = null; state.trackAnalytics = null; render();
    }
    else if (action === "open") {
      if (onTrackNavigate) { onTrackNavigate(trackId, "overview"); return; }
      await loadTrackWorkspace(trackId); state.editingProfileId = null; state.activeTab = "all"; render();
    }
    else if (action === "edit") {
      const track = state.detail?.track?.id === trackId ? state.detail.track : state.tracks.find((item) => item.id === trackId);
      state.editingTrack = track || null; render();
    } else if (action === "status") await mutate(() => api.updateTrack(trackId, { status: button.dataset.trackStatus }), "Track status saved.");
    else if (action === "edit-profile") { state.editingProfileId = button.dataset.profileId; render(); }
    else if (action === "cancel-profile") { state.editingProfileId = null; render(); }
    else if (action === "profile-status") await mutate(() => api.updateSearchProfile(button.dataset.profileId, { status: button.dataset.profileStatus }), "Search Profile status saved.");
  });

  root?.addEventListener("change", (event) => {
    const select = event.target.closest("[data-evaluation-filter]");
    if (select) {
      state.evaluationFilter = select.value;
      render();
      return;
    }
    const skillFilter = event.target.closest("[data-skill-filter]");
    if (skillFilter) {
      state.skillFilter = skillFilter.value;
      render();
      return;
    }
    const skillWindow = event.target.closest("[data-skill-window]");
    const skillSort = event.target.closest("[data-skill-sort]");
    if ((skillWindow || skillSort) && state.detail) {
      if (skillWindow) state.skillWindow = skillWindow.value;
      if (skillSort) state.skillSort = skillSort.value;
      state.loadingSkillDetail = true;
      render();
      loadSkillIntelligence(state.detail.track.id)
        .catch((error) => onStatus(error?.message || "Skill Intelligence could not be loaded.", "error"))
        .finally(() => {
          state.loadingSkillDetail = false;
          render();
        });
    }
  });

  root?.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-track-tab]");
    if (!tab || !state.detail) return;
    if (onTrackNavigate) { onTrackNavigate(state.detail.track.id, tab.dataset.trackTab); return; }
    state.activeTab = tab.dataset.trackTab;
    render();
  });

  async function openTrack(trackId, tab = "overview") {
    state.loading = true;
    state.error = null;
    state.activeTab = ["overview", "analytics", "jobs", "skills", "search", "policy"].includes(tab) ? tab : "overview";
    render();
    try {
      if (!state.tracks.length) {
        const result = await api.tracks();
        state.tracks = result.tracks || [];
      }
      await loadTrackWorkspace(trackId);
      state.editingProfileId = null;
    } catch (error) {
      state.error = error?.message || "Track could not be loaded.";
    } finally {
      state.loading = false;
      render();
    }
  }

  function setTab(tab) {
    state.activeTab = ["overview", "analytics", "jobs", "skills", "search", "policy"].includes(tab) ? tab : "overview";
    render();
  }

  async function mountJobAssignments(target, jobId) {
    if (!target || !jobId) return;
    target.innerHTML = `<div class="jobhunt-empty-inline">Loading Track assignments…</div>`;
    try {
      const result = await api.jobTracks(jobId);
      if (!target.isConnected || target.dataset.jobId !== jobId) return;
      target.innerHTML = renderJobTrackAssignment(result);
      target.querySelector("[data-job-track-form]")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData(event.target);
        try {
          const selectedTrackIds = [...event.target.querySelectorAll('input[name="trackIds"]:checked')]
            .map((input) => String(input.value));
          await api.setJobTracks(jobId, selectedTrackIds, { note: String(data.get("note") || "").trim() || null });
          await mountJobAssignments(target, jobId);
          await refresh();
          onStatus("Track assignments saved.", "success");
        } catch (error) {
          onStatus(error?.message || "Track assignments could not be saved.", "error");
        }
      });
    } catch (error) {
      target.innerHTML = `<div class="jobhunt-validation" data-tone="error">${escapeHtml(error?.message || "Track assignments could not be loaded.")}</div>`;
    }
  }

  return { state, render, refresh, openTrack, setTab, mountJobAssignments };
}
