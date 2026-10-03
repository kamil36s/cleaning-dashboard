import { escapeHtml } from "./utils.js";

export const EVALUATION_DIMENSIONS = ["skills", "experience", "compensation", "geography", "preferences"];
export const POLICY_BLOCKERS = ["compensation", "trackGeography", "workModel", "contract", "schedule", "relocation", "language"];

function label(value) {
  return String(value || "").replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function badge(state) {
  return `<span class="jobhunt-evaluation-state is-${escapeHtml(state || "unknown")}">${escapeHtml(label(state || "unknown"))}</span>`;
}

function evidenceList(title, values) {
  const items = Array.isArray(values) ? values : values ? [values] : [];
  if (!items.length) return `<div><strong>${escapeHtml(title)}</strong><span>None recorded</span></div>`;
  return `<div><strong>${escapeHtml(title)}</strong>${items.map((item) => {
    const text = typeof item === "string" ? item : JSON.stringify(item);
    return `<span>${escapeHtml(text)}</span>`;
  }).join("")}</div>`;
}

export function renderEvaluationFinding(finding) {
  const display = finding?.display || {};
  return `<article class="jobhunt-evaluation-finding is-${escapeHtml(finding?.status || "unknown")}">
    <div class="jobhunt-evaluation-finding-head">
      ${badge(finding?.status)}
      <strong>${escapeHtml(display.label || label(finding?.dimension))}</strong>
      <small>${escapeHtml(finding?.requirementClass || "not_applicable")}</small>
    </div>
    <p>${escapeHtml(display.summary || finding?.explanationCode || "No explanation available.")}</p>
    <details><summary>Inspect evidence</summary><div class="jobhunt-evaluation-evidence">
      ${evidenceList("Job", finding?.jobEvidence)}
      ${evidenceList("Career Profile", finding?.profileEvidence)}
      ${evidenceList("Track policy", finding?.policyEvidence)}
    </div></details>
  </article>`;
}

export function renderEvaluation(evaluation, { compact = false } = {}) {
  if (!evaluation) return `<div class="jobhunt-empty-inline">No Evaluation snapshot exists yet.</div>`;
  const counts = evaluation.counts || {};
  const dimensions = evaluation.dimensions || [];
  const findings = evaluation.findings || [];
  return `<article class="jobhunt-evaluation-card ${compact ? "is-compact" : ""}">
    <div class="jobhunt-evaluation-head">
      <div>${badge(evaluation.state)} <strong>Policy v${escapeHtml(evaluation.policyVersion)}</strong></div>
      <div class="jobhunt-evaluation-counts">
        <span class="is-blocker">${Number(counts.blockers || 0)} blockers</span>
        <span class="is-gap">${Number(counts.gaps || 0)} gaps</span>
        <span class="is-unknown">${Number(counts.unknowns || 0)} unknowns</span>
      </div>
    </div>
    <div class="jobhunt-evaluation-dimensions">${dimensions.map((item) => `<div class="is-${escapeHtml(item.state)}"><span>${escapeHtml(label(item.dimension))}</span>${badge(item.state)}<small>${escapeHtml(item.importance)}</small></div>`).join("")}</div>
    ${compact ? "" : `<div class="jobhunt-evaluation-findings">${findings.length ? findings.map(renderEvaluationFinding).join("") : `<div class="jobhunt-empty-inline">No findings were produced for enabled dimensions.</div>`}</div>
    <details class="jobhunt-evaluation-snapshot"><summary>Snapshot identity and history inputs</summary>
      <dl><div><dt>Profile revision</dt><dd>${escapeHtml(evaluation.profileRevision)}</dd></div><div><dt>Projection version</dt><dd>${escapeHtml(evaluation.projectionVersion || "canonical row")}</dd></div><div><dt>Evaluator</dt><dd>${escapeHtml(evaluation.evaluatorVersion)}</dd></div><div><dt>Created</dt><dd>${escapeHtml(evaluation.createdAt)}</dd></div></dl>
      <code>${escapeHtml(evaluation.inputFingerprint || "")}</code>
    </details>`}
  </article>`;
}

export function renderJobEvaluationPanel(data) {
  const targets = data?.targets || [];
  const history = data?.history || [];
  return `<div class="jobhunt-evaluation-workspace">
    <div class="jobhunt-evaluation-intro"><div><h3>Track-specific Evaluation</h3><p>Deterministic Career Profile × Canonical Job × Track evidence. No global percentage is calculated.</p></div></div>
    ${targets.length ? targets.map(({ track, evaluation, basis }) => `<section class="jobhunt-job-evaluation-target">
      <div class="jobhunt-career-block-head"><div><h4>${escapeHtml(track?.name || "Track")}</h4><span>${escapeHtml((basis?.sources || []).map((item) => item.type).join(", ") || "explicit request")}</span></div>
        <button type="button" class="jobhunt-row-action" data-evaluate-track="${escapeHtml(track?.id || "")}">${evaluation ? "Re-evaluate current inputs" : "Evaluate"}</button></div>
      ${renderEvaluation(evaluation)}
    </section>`).join("") : `<div class="jobhunt-empty-inline">This job has no Track assignment or discovery context. Assign a Track, or use a Track-specific explicit request.</div>`}
    <details class="jobhunt-evaluation-history"><summary>Evaluation history (${history.length})</summary>
      ${history.length ? `<div>${history.map((item) => `<article><div>${badge(item.state)} <strong>${escapeHtml(item.trackName || item.trackId)}</strong></div><span>Profile r${escapeHtml(item.profileRevision)} · projection v${escapeHtml(item.projectionVersion)} · policy v${escapeHtml(item.policyVersion)} · ${escapeHtml(item.evaluatorVersion)}</span><time>${escapeHtml(item.createdAt)}</time></article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No historical Evaluations.</div>`}
    </details>
  </div>`;
}

export async function mountJobEvaluations(target, jobId, api, onStatus = () => {}) {
  if (!target || !jobId) return;
  target.innerHTML = `<div class="jobhunt-empty-inline">Loading deterministic Evaluations…</div>`;
  try {
    const data = await api.jobEvaluations(jobId);
    if (!target.isConnected || target.dataset.jobId !== jobId) return;
    target.innerHTML = renderJobEvaluationPanel(data);
    target.querySelectorAll("[data-evaluate-track]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const result = await api.evaluateJobTrack(jobId, button.dataset.evaluateTrack);
        onStatus(result.reused ? "Unchanged inputs reused the existing Evaluation." : "Evaluation completed.", "success");
        await mountJobEvaluations(target, jobId, api, onStatus);
      } catch (error) {
        button.disabled = false;
        onStatus(error?.message || "Evaluation failed.", "error");
      }
    }));
  } catch (error) {
    target.innerHTML = `<div class="jobhunt-validation" data-tone="error">${escapeHtml(error?.message || "Evaluations could not be loaded.")}</div>`;
  }
}

function importanceOptions(current) {
  return ["primary", "secondary", "informational"].map((value) => `<option value="${value}"${value === current ? " selected" : ""}>${value}</option>`).join("");
}

export function renderPolicyEditor(current, history = []) {
  const value = current?.policy || {};
  const dimensions = value.dimensions || {};
  const blockers = value.blockers || {};
  const thresholds = value.skillThresholds || {};
  return `<section class="jobhunt-career-block jobhunt-policy-editor">
    <div class="jobhunt-career-block-head"><div><h3>Evaluation Policy</h3><span>Version ${escapeHtml(current?.version)} · ${escapeHtml(String(current?.fingerprint || "").slice(0, 20))}… · aggregate: none</span></div></div>
    <form data-evaluation-policy-form>
      <fieldset><legend>Dimensions</legend>${EVALUATION_DIMENSIONS.map((dimension) => `<label><input type="checkbox" name="dimensionEnabled" value="${dimension}"${dimensions[dimension]?.enabled ? " checked" : ""}><span>${escapeHtml(label(dimension))}</span><select name="importance:${dimension}">${importanceOptions(dimensions[dimension]?.importance || "secondary")}</select></label>`).join("")}</fieldset>
      <fieldset><legend>Explicit blocker categories</legend>${POLICY_BLOCKERS.map((key) => `<label><input type="checkbox" name="blocker" value="${key}"${blockers[key] ? " checked" : ""}><span>${escapeHtml(label(key))}</span></label>`).join("")}</fieldset>
      <div class="jobhunt-policy-thresholds"><label><span>Partial skill level</span><input type="number" name="partialMin" min="0" max="4" value="${escapeHtml(thresholds.partialMin)}"></label><label><span>Supported skill level</span><input type="number" name="supportedMin" min="1" max="5" value="${escapeHtml(thresholds.supportedMin)}"></label></div>
      <button class="jobhunt-primary-action" type="submit">Save new policy version</button>
    </form>
    <details><summary>Policy history (${history.length})</summary><div class="jobhunt-policy-history">${history.map((item) => `<article><strong>Version ${escapeHtml(item.version)}</strong><span>${escapeHtml(item.origin)} · ${escapeHtml(item.createdAt)}</span><code>${escapeHtml(item.fingerprint)}</code></article>`).join("")}</div></details>
  </section>`;
}

export function policyFromForm(form) {
  const data = new FormData(form);
  const enabled = new Set(
    [...form.querySelectorAll('input[name="dimensionEnabled"]:checked')].map((input) => input.value),
  );
  const blockers = new Set(
    [...form.querySelectorAll('input[name="blocker"]:checked')].map((input) => input.value),
  );
  return {
    schemaVersion: "track-evaluation-policy@1",
    dimensions: Object.fromEntries(EVALUATION_DIMENSIONS.map((dimension) => [dimension, {
      enabled: enabled.has(dimension),
      importance: String(data.get(`importance:${dimension}`) || "secondary"),
    }])),
    blockers: Object.fromEntries(POLICY_BLOCKERS.map((key) => [key, blockers.has(key)])),
    skillThresholds: {
      partialMin: Number(data.get("partialMin")),
      supportedMin: Number(data.get("supportedMin")),
    },
    unknownHandling: "preserve",
    aggregate: "none",
  };
}

function evaluationMatches(item, filter) {
  if (filter === "no-blockers") return !item.counts?.blockers;
  if (filter === "blockers") return Boolean(item.counts?.blockers);
  if (filter === "unknowns") return Boolean(item.counts?.unknowns);
  if (filter === "skill-gaps") return (item.findings || []).some((finding) => finding.dimension === "skills" && finding.status === "gap");
  if (filter === "current") return item.state === "current";
  return true;
}

export function renderTrackEvaluations(data, filter = "all") {
  const items = (data?.items || []).filter((item) => evaluationMatches(item, filter));
  const options = [["all", "All"], ["no-blockers", "No blockers"], ["blockers", "Blockers"], ["unknowns", "Unknowns"], ["skill-gaps", "Skill gaps"], ["current", "Current only"]];
  return `<section class="jobhunt-career-block jobhunt-track-evaluations">
    <div class="jobhunt-career-block-head"><div><h3>Evaluated jobs</h3><span>Newest first. No hidden composite or percentage.</span></div><label><span class="sr-only">Filter Evaluations</span><select data-evaluation-filter>${options.map(([value, text]) => `<option value="${value}"${filter === value ? " selected" : ""}>${text}</option>`).join("")}</select></label></div>
    ${items.length ? `<div class="jobhunt-track-evaluation-list">${items.map((item) => `<article><div><strong>${escapeHtml(item.job?.company)} — ${escapeHtml(item.job?.role)}</strong>${badge(item.state)}</div>${renderEvaluation(item, { compact: true })}<button type="button" class="jobhunt-row-action" data-job-open="${escapeHtml(item.jobId)}">Open job</button></article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No evaluated jobs match this filter.</div>`}
  </section>`;
}
