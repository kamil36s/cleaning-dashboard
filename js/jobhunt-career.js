import { escapeHtml } from "./utils.js";

const COLLECTIONS = {
  experience: {
    title: "Experience",
    summary: (item) => [item.jobTitle, item.employer].filter(Boolean).join(" — ") || "Experience",
    fields: [
      ["jobTitle", "Job title", "text", true], ["employer", "Employer", "text"],
      ["startDate", "Start date", "date"], ["endDate", "End date", "date"],
      ["isCurrent", "Current role", "unknown-bool"], ["location", "Location", "text"],
      ["employmentType", "Employment type", "text"], ["description", "Description / evidence", "textarea"],
      ["domains", "Domains (comma-separated)", "csv"], ["notes", "Notes", "textarea"],
    ],
  },
  education: {
    title: "Education",
    summary: (item) => [item.qualification, item.fieldProgram, item.institution].filter(Boolean).join(" — ") || "Education",
    fields: [
      ["institution", "Institution", "text", true], ["fieldProgram", "Field / program", "text"],
      ["qualification", "Qualification / degree", "text"], ["startDate", "Start date", "date"],
      ["endDate", "End date", "date"], ["completionStatus", "Completion status", "text"],
      ["notes", "Notes / evidence", "textarea"],
    ],
  },
  certifications: {
    title: "Certifications",
    summary: (item) => [item.name, item.issuer].filter(Boolean).join(" — ") || "Certification",
    fields: [
      ["name", "Certification", "text", true], ["issuer", "Issuer", "text"],
      ["issuedDate", "Issued date", "date"], ["expirationDate", "Expiration date", "date"],
      ["credentialReference", "Credential / reference", "text"], ["notes", "Notes / evidence", "textarea"],
    ],
  },
  languages: {
    title: "Languages",
    summary: (item) => [item.languageName, item.proficiency].filter(Boolean).join(" — ") || "Language",
    fields: [
      ["languageName", "Language", "text", true], ["proficiency", "Proficiency", "text"],
      ["proficiencyScheme", "Scheme (for example CEFR)", "text"], ["confidence", "Confidence (1–5)", "number-1-5"],
      ["notes", "Notes / evidence", "textarea"],
    ],
  },
  preferences: {
    title: "Work preferences",
    summary: (item) => `${item.dimensionKey || "Preference"}: ${displayValue(item.value)}`,
    fields: [
      ["dimensionKey", "Dimension key", "text", true], ["value", "Typed value (JSON or text)", "json", true],
      ["importance", "Importance (1–5)", "number-1-5"], ["confidence", "Confidence (1–5)", "number-1-5"],
      ["notes", "Notes", "textarea"],
    ],
  },
  constraints: {
    title: "Constraints / dealbreakers",
    summary: (item) => `${item.constraintKey || "Constraint"}: ${displayValue(item.value)}`,
    fields: [
      ["constraintKey", "Constraint key", "text", true], ["value", "Typed value (JSON or text)", "json", true],
      ["isHard", "Hard blocker", "bool"], ["notes", "Notes", "textarea"],
    ],
  },
  skills: {
    title: "Skills",
    summary: (item) => `${item.displayName || "Skill"} — level ${item.level ?? "unknown"}`,
    fields: [
      ["displayName", "Skill name", "text", true], ["normalizedKey", "Optional normalized key", "text"],
      ["level", "Skill level (0–5)", "number-0-5"], ["confidence", "Confidence (1–5)", "number-1-5"],
      ["developmentInterest", "Interest in developing (1–5)", "number-1-5"],
      ["evidenceNotes", "Evidence / notes", "textarea"],
    ],
  },
};

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "unknown";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function valueFor(item, name, type) {
  const value = item?.[name];
  if (type === "csv" && Array.isArray(value)) return value.join(", ");
  if (type === "json" && value !== null && typeof value === "object") return JSON.stringify(value);
  if (value === null || value === undefined) return "";
  return String(value);
}

function fieldHtml(field, item = {}) {
  const [name, label, type, required] = field;
  const value = valueFor(item, name, type);
  const requiredAttr = required ? " required" : "";
  if (type === "textarea") {
    return `<label class="jobhunt-field-wide"><span>${escapeHtml(label)}</span><textarea name="${escapeHtml(name)}" rows="3"${requiredAttr}>${escapeHtml(value)}</textarea></label>`;
  }
  if (type === "unknown-bool") {
    return `<label><span>${escapeHtml(label)}</span><select name="${escapeHtml(name)}">
      <option value=""${value === "" ? " selected" : ""}>Unknown</option>
      <option value="true"${value === "true" ? " selected" : ""}>Yes</option>
      <option value="false"${value === "false" ? " selected" : ""}>No</option>
    </select></label>`;
  }
  if (type === "bool") {
    const selected = value === "" ? "true" : value;
    return `<label><span>${escapeHtml(label)}</span><select name="${escapeHtml(name)}">
      <option value="true"${selected === "true" ? " selected" : ""}>Yes</option>
      <option value="false"${selected === "false" ? " selected" : ""}>No</option>
    </select></label>`;
  }
  const number = type.startsWith("number");
  const min = type === "number-0-5" ? 0 : 1;
  const inputType = number ? "number" : (type === "json" ? "text" : type);
  return `<label><span>${escapeHtml(label)}</span><input name="${escapeHtml(name)}" type="${inputType}" value="${escapeHtml(value)}"${number ? ` min="${min}" max="5" step="1"` : ""}${requiredAttr}></label>`;
}

function recordListHtml(kind, items = []) {
  const config = COLLECTIONS[kind];
  if (!items.length) return `<div class="jobhunt-career-empty"><strong>No ${escapeHtml(config.title.toLowerCase())} added yet.</strong><span>Missing means unknown.</span></div>`;
  return `<div class="jobhunt-career-records">${items.map((item) => `
    <article class="jobhunt-career-record">
      <div><strong>${escapeHtml(config.summary(item))}</strong><span>${escapeHtml(item.notes || item.evidenceNotes || "No notes")}</span></div>
      <div class="jobhunt-row-actions">
        <button type="button" class="jobhunt-row-action" data-profile-edit="${kind}" data-record-id="${escapeHtml(item.id)}">Edit</button>
        <button type="button" class="jobhunt-row-action is-danger" data-profile-delete="${kind}" data-record-id="${escapeHtml(item.id)}">Delete</button>
      </div>
    </article>
  `).join("")}</div>`;
}

const GUIDED_PREFERENCES = [
  ["work_model", "Preferred work model", "select", ["remote", "hybrid", "onsite", "flexible"]],
  ["contract_type", "Preferred contract", "text"],
  ["schedule", "Preferred schedule", "select", ["weekdays", "weekends", "shifts", "flexible"]],
  ["location", "Preferred location", "text"],
  ["relocation", "Open to relocation", "select", ["yes", "no", "maybe"]],
];

const GUIDED_CONSTRAINTS = [
  ["minimum_salary", "Minimum compensation", "text"],
  ["geography", "Required geography", "text"],
  ["work_model", "Required work model", "select", ["remote", "hybrid", "onsite"]],
  ["schedule", "Schedule restriction", "text"],
  ["contract_type", "Required contract", "text"],
  ["language", "Language requirement", "text"],
];

const PROFILE_SECTIONS = [
  ["basics", "Basics"],
  ["experience", "Experience"],
  ["education", "Education"],
  ["certifications", "Certifications"],
  ["languages", "Languages"],
  ["preferences", "Preferences"],
  ["constraints", "Dealbreakers"],
  ["history", "History"],
];

function guidedValueControl(definition, value = "") {
  const options = definition?.[3] || [];
  if (definition?.[2] === "select") {
    return `<select name="guidedValue" required><option value="">Choose…</option>${options.map((option) => `<option value="${escapeHtml(option)}"${option === value ? " selected" : ""}>${escapeHtml(option.replaceAll("_", " "))}</option>`).join("")}</select>`;
  }
  return `<input name="guidedValue" value="${escapeHtml(value)}" required placeholder="Enter a value">`;
}

function guidedEditor(kind, item = null) {
  const preference = kind === "preferences";
  const definitions = preference ? GUIDED_PREFERENCES : GUIDED_CONSTRAINTS;
  const keyName = preference ? "dimensionKey" : "constraintKey";
  const currentKey = item?.[keyName] || definitions[0][0];
  const currentDefinition = definitions.find(([key]) => key === currentKey);
  const custom = !currentDefinition;
  const displayValueText = item?.value == null ? "" : (typeof item.value === "object" ? JSON.stringify(item.value) : String(item.value));
  return `<form class="jobhunt-career-form jobhunt-profile-drawer" role="dialog" aria-label="${item ? "Edit" : "Add"} ${preference ? "preference" : "dealbreaker"}" data-profile-form="${kind}" data-record-id="${escapeHtml(item?.id || "")}">
    <div class="jobhunt-dialog-head jobhunt-field-wide"><div><span class="jobhunt-section-label">${preference ? "Preference" : "Dealbreaker"}</span><h3>${item ? "Edit" : "Add"} ${preference ? "work preference" : "constraint"}</h3></div><button type="button" class="jobhunt-icon-button" data-profile-cancel="${kind}" aria-label="Close">×</button></div>
    <label><span>${preference ? "What matters?" : "What is required?"}</span><select name="guidedKey">${definitions.map(([key, label]) => `<option value="${key}"${key === currentKey ? " selected" : ""}>${escapeHtml(label)}</option>`).join("")}<option value="custom"${custom ? " selected" : ""}>Custom…</option></select></label>
    <label data-guided-value><span>Value</span>${guidedValueControl(currentDefinition, displayValueText)}</label>
    ${preference ? `<label><span>Importance</span><select name="importance"><option value="">Not set</option>${[1,2,3,4,5].map((value) => `<option value="${value}"${Number(item?.importance) === value ? " selected" : ""}>${value}${value === 5 ? " — essential" : value === 1 ? " — slight" : ""}</option>`).join("")}</select></label>` : `<label><span>Dealbreaker?</span><select name="isHard"><option value="true"${item?.isHard !== false ? " selected" : ""}>Yes, block jobs that conflict</option><option value="false"${item?.isHard === false ? " selected" : ""}>No, show as a concern</option></select></label>`}
    <label class="jobhunt-field-wide"><span>Notes (optional)</span><textarea name="notes" rows="3">${escapeHtml(item?.notes || "")}</textarea></label>
    <details class="jobhunt-field-wide jobhunt-advanced-field"><summary>Advanced custom field</summary><p>Use this only when the guided choices do not describe the preference.</p><label><span>Custom key</span><input name="customKey" value="${escapeHtml(custom ? currentKey : "")}" placeholder="for example travel_frequency"></label><label><span>JSON value (optional)</span><input name="customValue" value="${escapeHtml(custom && typeof item?.value === "object" ? JSON.stringify(item.value) : "")}"></label></details>
    <div class="jobhunt-form-actions jobhunt-field-wide"><button class="jobhunt-primary-action" type="submit">Save</button><button class="jobhunt-secondary-action" type="button" data-profile-cancel="${kind}">Cancel</button></div>
  </form>`;
}

function recordEditor(kind, item = null) {
  if (["preferences", "constraints"].includes(kind)) return guidedEditor(kind, item);
  const config = COLLECTIONS[kind];
  return `<form class="jobhunt-career-form jobhunt-profile-drawer" role="dialog" aria-label="${item ? "Edit" : "Add"} ${escapeHtml(config.title)}" data-profile-form="${kind}" data-record-id="${escapeHtml(item?.id || "")}">
    <div class="jobhunt-dialog-head jobhunt-field-wide"><div><span class="jobhunt-section-label">Career Profile</span><h3>${item ? "Edit" : "Add"} ${escapeHtml(config.title.toLowerCase())}</h3></div><button type="button" class="jobhunt-icon-button" data-profile-cancel="${kind}" aria-label="Close">×</button></div>
    ${config.fields.map((field) => fieldHtml(field, item || {})).join("")}
    <div class="jobhunt-form-actions jobhunt-field-wide"><button class="jobhunt-primary-action" type="submit">${item ? "Save changes" : "Add"}</button><button class="jobhunt-secondary-action" type="button" data-profile-cancel="${kind}">Cancel</button></div>
  </form>`;
}

function collectionHtml(kind, profile, editing) {
  const config = COLLECTIONS[kind];
  const items = profile[kind] || [];
  const editItem = editing?.kind === kind
    ? items.find((item) => item.id === editing.id) || null
    : null;
  return `<section class="jobhunt-career-block">
    <div class="jobhunt-career-block-head"><div><h3>${escapeHtml(config.title)}</h3><span>Optional; unset values remain unknown.</span></div><button class="jobhunt-secondary-action" type="button" data-profile-add="${kind}">+ Add</button></div>
    ${recordListHtml(kind, items)}
    ${editing?.kind === kind ? recordEditor(kind, editItem) : ""}
  </section>`;
}

export function renderCareerProfile(profile, editing = null, section = "basics") {
  if (!profile) return `<div class="jobhunt-empty-inline">Career Profile is loading.</div>`;
  const activeSection = PROFILE_SECTIONS.some(([key]) => key === section) ? section : "basics";
  const sectionContent = activeSection === "basics" ? `<form class="jobhunt-career-form" data-profile-identity>
      <div class="jobhunt-guidance jobhunt-field-wide"><strong>Describe where you are now.</strong><span>For example: Testing Coordinator, manual QA and UAT, moving toward API testing.</span></div>
      <label><span>Current role / title</span><input name="currentRoleTitle" value="${escapeHtml(profile.currentRoleTitle || "")}" placeholder="For example, Testing Coordinator"></label>
      <label><span>Career headline</span><input name="headline" value="${escapeHtml(profile.headline || "")}" placeholder="For example, Manual QA · UAT · test coordination"></label>
      <label class="jobhunt-field-wide"><span>Professional summary</span><textarea name="professionalSummary" rows="4" placeholder="Summarize the work and evidence you want Evaluations to use.">${escapeHtml(profile.professionalSummary || "")}</textarea></label>
      <div class="jobhunt-form-actions jobhunt-field-wide"><button class="jobhunt-primary-action" type="submit">Save profile</button></div>
    </form>` : activeSection === "history" ? `<section class="jobhunt-career-block"><div class="jobhunt-career-version"><strong>Revision ${profile.revision}</strong><span>Changes create a reproducible Profile snapshot for Track Evaluations.</span><details><summary>Technical fingerprint</summary><code>${escapeHtml(profile.fingerprint || "")}</code></details></div></section>` : collectionHtml(activeSection, profile, editing);
  return `<div class="jobhunt-career-content">
    <nav class="jobhunt-profile-sections" aria-label="Career Profile sections">${PROFILE_SECTIONS.map(([key, label]) => `<button type="button" data-profile-section="${key}" class="${key === activeSection ? "is-active" : ""}" aria-pressed="${key === activeSection}">${label}</button>`).join("")}</nav>
    ${sectionContent}
  </div>`;
}

export function renderCareerSkills(profile, editing = null) {
  if (!profile) return `<div class="jobhunt-empty-inline">Skills are loading.</div>`;
  const scale = Object.entries(profile.skillLevelScale || {}).map(([value, label]) => `<li><strong>${value}</strong> — ${escapeHtml(label)}</li>`).join("");
  return `<div class="jobhunt-career-content">
    <section class="jobhunt-career-block"><h3>Skill level semantics</h3><ul class="jobhunt-skill-scale">${scale}</ul><p>Level, confidence, and interest in developing are separate values. An unset level is unknown, not zero.</p></section>
    ${collectionHtml("skills", profile, editing)}
  </div>`;
}

function statusLabel(instrument) {
  if (!instrument.available) return "Unavailable — verification pending";
  if (instrument.status === "draft") return "Draft — resume available";
  if (instrument.status === "completed") return "Completed";
  return "Not started";
}

export function renderAssessmentList(instruments = []) {
  return `<div class="jobhunt-assessment-list">${instruments.map((instrument) => `
    <article class="jobhunt-assessment-card${instrument.available ? "" : " is-unavailable"}">
      <div>
        <span class="jobhunt-section-label">${escapeHtml(statusLabel(instrument))}</span>
        <h3>${escapeHtml(instrument.title)}</h3>
        <p>${escapeHtml(instrument.description || "")}</p>
        ${instrument.latestCompletedAt ? `<p><strong>Latest:</strong> ${escapeHtml(instrument.latestCompletedAt)}</p>` : ""}
        ${instrument.unavailableReason ? `<p class="jobhunt-warning">${escapeHtml(instrument.unavailableReason)}</p>` : ""}
      </div>
      <div class="jobhunt-row-actions">
        ${instrument.available ? `<button class="jobhunt-primary-action" type="button" data-assessment-action="${instrument.draftRunId ? "resume" : "start"}" data-instrument-id="${escapeHtml(instrument.instrumentId)}" data-run-id="${escapeHtml(instrument.draftRunId || "")}">${instrument.draftRunId ? "Resume" : (instrument.status === "completed" ? "Retake" : "Start")}</button>` : ""}
      </div>
      ${instrument.history.length ? `<details><summary>History (${instrument.history.length})</summary><div class="jobhunt-assessment-history">${instrument.history.map((run) => `
        <button type="button" data-assessment-action="view-run" data-run-id="${escapeHtml(run.id)}"><span>${escapeHtml(run.completedAt || run.startedAt)}</span><strong>${escapeHtml(run.status)}</strong></button>
      `).join("")}</div></details>` : ""}
      ${instrument.source?.attribution ? `<small>${escapeHtml(instrument.source.attribution)}</small>` : ""}
    </article>
  `).join("")}</div>`;
}

export function renderAssessmentRun(run, instrument, page = 0) {
  if (run.status === "completed") {
    return `<div class="jobhunt-assessment-results">
      <button class="jobhunt-ghost-action" type="button" data-assessment-action="back">← Assessment list</button>
      <span class="jobhunt-section-label">Completed ${escapeHtml(run.completedAt || "")}</span>
      <h3>${escapeHtml(instrument.title)}</h3>
      <div class="jobhunt-score-grid">${run.scores.map((score) => `<div><span>${escapeHtml(score.label)}</span><strong>${Math.round(score.normalizedScore)}</strong><em>raw ${escapeHtml(score.rawScore)}</em></div>`).join("")}</div>
      <p>${escapeHtml(instrument.interpretationLimits?.[0] || "Scores are descriptive evidence, not career prescriptions.")}</p>
    </div>`;
  }
  if (run.status === "abandoned") {
    return `<div class="jobhunt-assessment-results">
      <button class="jobhunt-ghost-action" type="button" data-assessment-action="back">← Assessment list</button>
      <span class="jobhunt-section-label">Abandoned draft</span>
      <h3>${escapeHtml(instrument.title)}</h3>
      <p>This historical draft is closed and cannot be edited. Start a new run to retake the assessment.</p>
    </div>`;
  }
  const pageSize = 5;
  const pageCount = Math.ceil(instrument.items.length / pageSize);
  const safePage = Math.max(0, Math.min(pageCount - 1, page));
  const items = instrument.items.slice(safePage * pageSize, (safePage + 1) * pageSize);
  const answered = Object.keys(run.responses || {}).length;
  return `<div class="jobhunt-assessment-run">
    <button class="jobhunt-ghost-action" type="button" data-assessment-action="back">← Save and leave</button>
    <div class="jobhunt-assessment-progress"><span>${answered} of ${instrument.items.length} answered</span><progress max="${instrument.items.length}" value="${answered}"></progress></div>
    <h3>${escapeHtml(instrument.title)}</h3>
    <p>${escapeHtml(instrument.description)}</p>
    <div class="jobhunt-question-list">${items.map((item) => `
      <fieldset data-question-id="${escapeHtml(item.id)}"><legend><span>${item.order}.</span> ${escapeHtml(item.text)}</legend>
        <div class="jobhunt-answer-scale">${instrument.answerScale.options.map((option) => `
          <label><input type="radio" name="answer-${escapeHtml(item.id)}" value="${option.value}" data-assessment-answer="${escapeHtml(item.id)}"${Number(run.responses?.[item.id]) === option.value ? " checked" : ""}><span>${escapeHtml(option.label)}</span></label>
        `).join("")}</div>
      </fieldset>
    `).join("")}</div>
    <div class="jobhunt-assessment-nav">
      <button class="jobhunt-ghost-action" type="button" data-assessment-action="previous"${safePage === 0 ? " disabled" : ""}>Previous</button>
      <span>Page ${safePage + 1} of ${pageCount}</span>
      ${safePage < pageCount - 1
        ? `<button class="jobhunt-primary-action" type="button" data-assessment-action="next">Next</button>`
        : `<button class="jobhunt-primary-action" type="button" data-assessment-action="complete"${answered === instrument.items.length ? "" : " disabled"}>Complete</button>`}
    </div>
    <div class="jobhunt-assessment-notices">${(instrument.source?.requiredNotices || []).map((notice) => `<small>${escapeHtml(notice)}</small>`).join("")}</div>
  </div>`;
}

function formPayload(form, fields) {
  const data = new FormData(form);
  const payload = {};
  fields.forEach(([name, , type]) => {
    const raw = String(data.get(name) ?? "").trim();
    if (type === "csv") payload[name] = raw ? raw.split(",").map((value) => value.trim()).filter(Boolean) : [];
    else if (type.startsWith("number")) payload[name] = raw === "" ? null : Number(raw);
    else if (type === "bool") payload[name] = raw === "true";
    else if (type === "unknown-bool") payload[name] = raw === "" ? null : raw === "true";
    else if (type === "json") {
      if (!raw) payload[name] = null;
      else {
        try { payload[name] = JSON.parse(raw); }
        catch { payload[name] = raw; }
      }
    }
    else payload[name] = raw || null;
  });
  payload.origin = "manual_user";
  return payload;
}

function guidedPayload(form, kind) {
  const data = new FormData(form);
  const preference = kind === "preferences";
  const keyName = preference ? "dimensionKey" : "constraintKey";
  const guidedKey = String(data.get("guidedKey") || "");
  const key = guidedKey === "custom" ? String(data.get("customKey") || "").trim() : guidedKey;
  const customRaw = String(data.get("customValue") || "").trim();
  let value = String(data.get("guidedValue") || "").trim();
  if (guidedKey === "custom" && customRaw) {
    try { value = JSON.parse(customRaw); } catch { value = customRaw; }
  }
  const payload = { [keyName]: key, value, origin: "manual_user", notes: String(data.get("notes") || "").trim() || null };
  if (preference) payload.importance = data.get("importance") ? Number(data.get("importance")) : null;
  else payload.isHard = data.get("isHard") === "true";
  return payload;
}

export function createJobhuntCareerController({ root, api, onStatus = () => {} }) {
  const state = {
    tab: "profile", profileSection: "basics", profile: null, instruments: [], editing: null,
    run: null, instrument: null, assessmentPage: 0, loading: false, error: null,
  };

  function render() {
    if (!root) return;
    document.querySelectorAll("[data-career-tab]").forEach((button) => {
      button.setAttribute("aria-selected", String(button.dataset.careerTab === state.tab));
      button.classList.toggle("is-active", button.dataset.careerTab === state.tab);
    });
    if (state.loading && !state.profile) root.innerHTML = `<div class="jobhunt-empty-inline">Loading Career Profile…</div>`;
    else if (state.error) root.innerHTML = `<div class="jobhunt-validation" data-tone="error">${escapeHtml(state.error)}</div>`;
    else if (state.tab === "skills") root.innerHTML = renderCareerSkills(state.profile, state.editing);
    else if (state.tab === "assessments") root.innerHTML = state.run
      ? renderAssessmentRun(state.run, state.instrument, state.assessmentPage)
      : renderAssessmentList(state.instruments);
    else root.innerHTML = renderCareerProfile(state.profile, state.editing, state.profileSection);
  }

  async function refresh({ includeAssessments = true } = {}) {
    state.loading = true;
    state.error = null;
    render();
    try {
      const [profileResult, assessmentResult] = await Promise.all([
        api.profile(),
        includeAssessments ? api.assessments() : Promise.resolve({ instruments: state.instruments }),
      ]);
      state.profile = profileResult.profile;
      state.instruments = assessmentResult.instruments || [];
    } catch (error) {
      state.error = error?.message || "Career data could not be loaded.";
    } finally {
      state.loading = false;
      render();
    }
  }

  async function mutate(operation, message) {
    try {
      const result = await operation();
      if (result?.profile) state.profile = result.profile;
      state.editing = null;
      onStatus(message, "success");
      render();
      return result;
    } catch (error) {
      onStatus(error?.message || "Career operation failed.", "error");
      throw error;
    }
  }

  async function openRun(runId) {
    const result = await api.assessmentRun(runId);
    state.run = result.run;
    state.instrument = result.instrument;
    const firstMissing = state.instrument.items.findIndex((item) => state.run.responses?.[item.id] === undefined);
    state.assessmentPage = Math.max(0, Math.floor((firstMissing < 0 ? 0 : firstMissing) / 5));
    render();
  }

  root?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    if (form.matches("[data-profile-identity]")) {
      const data = new FormData(form);
      await mutate(() => api.updateProfile({
        currentRoleTitle: String(data.get("currentRoleTitle") || "").trim() || null,
        headline: String(data.get("headline") || "").trim() || null,
        professionalSummary: String(data.get("professionalSummary") || "").trim() || null,
      }), "Career Profile saved.");
      return;
    }
    const kind = form.dataset.profileForm;
    if (!kind) return;
    if (typeof form.checkValidity === "function" && !form.checkValidity()) {
      form.reportValidity?.();
      onStatus("Complete the required fields before saving.", "error");
      return;
    }
    const payload = ["preferences", "constraints"].includes(kind)
      ? guidedPayload(form, kind)
      : formPayload(form, COLLECTIONS[kind].fields);
    const guidedKey = kind === "preferences" ? payload.dimensionKey : payload.constraintKey;
    if (["preferences", "constraints"].includes(kind) && (!guidedKey || payload.value === "" || payload.value === null)) {
      onStatus("Choose a field and enter its value before saving.", "error");
      return;
    }
    const recordId = form.dataset.recordId;
    await mutate(
      () => recordId ? api.updateProfileRecord(kind, recordId, payload) : api.createProfileRecord(kind, payload),
      `${COLLECTIONS[kind].title} saved.`,
    );
  });

  root?.addEventListener("change", async (event) => {
    if (event.target.matches('[name="guidedKey"]')) {
      const definitions = event.target.form?.dataset.profileForm === "constraints" ? GUIDED_CONSTRAINTS : GUIDED_PREFERENCES;
      const definition = definitions.find(([key]) => key === event.target.value);
      const target = event.target.form?.querySelector("[data-guided-value]");
      if (target) target.innerHTML = `<span>Value</span>${guidedValueControl(definition)}`;
      return;
    }
    const itemId = event.target.dataset.assessmentAnswer;
    if (!itemId || !state.run) return;
    try {
      const result = await api.saveAssessmentResponses(state.run.id, { [itemId]: Number(event.target.value) });
      state.run = result.run;
      state.instrument = result.instrument;
      render();
      root.querySelector(`[data-question-id="${itemId}"]`)?.focus();
    } catch (error) {
      onStatus(error?.message || "Answer could not be saved.", "error");
    }
  });

  root?.addEventListener("click", async (event) => {
    const section = event.target.closest("[data-profile-section]");
    if (section) {
      state.profileSection = section.dataset.profileSection;
      state.editing = null;
      render();
      return;
    }
    const add = event.target.closest("[data-profile-add]");
    if (add) {
      state.editing = { kind: add.dataset.profileAdd, id: null };
      render();
      root.querySelector(".jobhunt-profile-drawer input, .jobhunt-profile-drawer select")?.focus();
      return;
    }
    const edit = event.target.closest("[data-profile-edit]");
    if (edit) {
      state.editing = { kind: edit.dataset.profileEdit, id: edit.dataset.recordId };
      render();
      return;
    }
    const cancel = event.target.closest("[data-profile-cancel]");
    if (cancel) { state.editing = null; render(); return; }
    const remove = event.target.closest("[data-profile-delete]");
    if (remove) {
      if (!window.confirm("Delete this Career Profile record?")) return;
      await mutate(
        () => api.deleteProfileRecord(remove.dataset.profileDelete, remove.dataset.recordId),
        "Career Profile record deleted.",
      );
      return;
    }
    const action = event.target.closest("[data-assessment-action]");
    if (!action) return;
    try {
      if (action.dataset.assessmentAction === "start") {
        const result = await api.startAssessment(action.dataset.instrumentId);
        state.run = result.run; state.instrument = result.instrument; state.assessmentPage = 0; render();
      } else if (["resume", "view-run"].includes(action.dataset.assessmentAction)) {
        await openRun(action.dataset.runId);
      } else if (action.dataset.assessmentAction === "back") {
        state.run = null; state.instrument = null; await refresh();
      } else if (action.dataset.assessmentAction === "previous") {
        state.assessmentPage -= 1; render();
      } else if (action.dataset.assessmentAction === "next") {
        state.assessmentPage += 1; render();
      } else if (action.dataset.assessmentAction === "complete") {
        const result = await api.completeAssessment(state.run.id);
        state.run = result.run; state.instrument = result.instrument; render();
        onStatus("Assessment completed. The result was stored as immutable history.", "success");
      }
    } catch (error) {
      onStatus(error?.message || "Assessment operation failed.", "error");
    }
  });

  document.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-career-tab]");
    if (!tab) return;
    state.tab = tab.dataset.careerTab;
    state.editing = null;
    state.run = null;
    render();
  });

  function setTab(tab) {
    state.tab = ["profile", "skills", "assessments"].includes(tab) ? tab : "profile";
    state.editing = null;
    state.run = null;
    if (state.tab === "profile") state.profileSection = "basics";
    render();
  }

  return { state, refresh, render, openRun, setTab };
}
