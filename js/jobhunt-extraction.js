import { escapeHtml } from "./utils.js";

function displayValue(value) {
  if (value === null || value === undefined) return "unknown";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function renderFactInspector(extraction) {
  if (!extraction) return "";
  const runs = extraction.runs || [];
  const facts = extraction.facts || [];
  const projection = extraction.projection;
  const deterministicRuns = runs.filter((run) => run.extractorKind !== "ai");
  const aiRuns = runs.filter((run) => run.extractorKind === "ai");
  const showAi = extraction.showAi === true || aiRuns.length > 0;
  const runCards = (items, empty) => items.map((run) => `<article data-run-kind="${escapeHtml(run.extractorKind || "deterministic")}">
    <div><span class="jobhunt-badge is-extractor-${run.extractorKind === "ai" ? "ai" : "deterministic"}">${run.extractorKind === "ai" ? "AI" : "DETERMINISTIC"}</span><strong>${escapeHtml(run.extractorVersion)}</strong></div>
    <span>${escapeHtml(run.status)} &middot; ${run.factCount} facts &middot; ${run.warningCount} warnings${run.reused ? " &middot; reused" : ""}</span>
    ${run.ai ? `<small>${escapeHtml(run.ai.provider || "unknown provider")} &middot; ${escapeHtml(run.ai.model || "unknown model")} &middot; prompt ${escapeHtml(run.ai.promptVersion || "unknown")} &middot; ${Number(run.ai.latencyMs || 0).toFixed(0)} ms</small>
    <small>Usage: ${run.ai.usage?.inputTokens ?? "?"} input / ${run.ai.usage?.outputTokens ?? "?"} output / ${run.ai.usage?.totalTokens ?? "?"} total tokens &middot; ${run.ai.attemptCount || 0} attempt(s)</small>` : ""}
    ${(run.warnings || []).map((warning) => `<small>${escapeHtml(warning)}</small>`).join("")}
  </article>`).join("") || `<div class="jobhunt-empty-inline">${escapeHtml(empty)}</div>`;
  return `<section class="jobhunt-fact-inspector" aria-label="Extracted facts">
    <div class="jobhunt-career-block-head"><div><h4>Extraction history</h4><span>${runs.length} run(s) &middot; ${facts.length} fact(s)</span></div></div>
    ${projection ? `<div class="jobhunt-validation" data-tone="${projection.outcome === "review_required" ? "warning" : "success"}">
      Projection: ${escapeHtml(projection.outcome || "unknown")}${projection.canonicalJobId ? ` &middot; Job ${escapeHtml(projection.canonicalJobId)}` : ""}${projection.projectionVersion ? ` &middot; v${projection.projectionVersion}` : ""}
    </div>` : ""}
    <h5>Deterministic extraction</h5><div class="jobhunt-extraction-runs">${runCards(deterministicRuns, "No deterministic extraction run yet.")}</div>
    ${showAi ? `<h5>AI extraction</h5><div class="jobhunt-extraction-runs">${runCards(aiRuns, "Not run.")}</div>` : ""}
    ${facts.length ? `<div class="jobhunt-fact-list">${facts.map((fact) => `<article data-fact-id="${escapeHtml(fact.id)}">
      <div><span class="jobhunt-badge is-extractor-${fact.extractor?.kind === "ai" ? "ai" : "deterministic"}">${fact.extractor?.kind === "ai" ? "AI" : "DETERMINISTIC"}</span><strong>${escapeHtml(fact.type)}</strong><span class="jobhunt-badge">${escapeHtml(fact.state)}</span><span>${Math.round(Number(fact.confidence) * 100)}%</span></div>
      <p>${escapeHtml(displayValue(fact.value))}${fact.currency ? ` ${escapeHtml(fact.currency)}` : ""}${fact.period ? ` / ${escapeHtml(fact.period)}` : ""}</p>
      <small>Source wording: ${escapeHtml(fact.sourceWording)}</small>
      <small>Evidence: ${escapeHtml(displayValue(fact.evidence))}</small>
      <small>Validation: ${escapeHtml(fact.validationState)}${fact.validationMessage ? ` &middot; ${escapeHtml(fact.validationMessage)}` : ""}</small>
      <small>Extractor: ${escapeHtml(fact.extractor?.version || extraction.runVersions?.[fact.extractionRunId] || fact.extractionRunId)}</small>
      ${fact.extractor?.kind === "ai" ? `<small>Provider: ${escapeHtml(fact.extractor.provider || "unknown")} &middot; ${escapeHtml(fact.extractor.model || "unknown")} &middot; prompt ${escapeHtml(fact.extractor.promptVersion || "unknown")}</small>` : ""}
      ${fact.normalization ? `<small>Normalized: ${escapeHtml(fact.normalization.conceptType)}:${escapeHtml(fact.normalization.conceptKey)} &middot; ${escapeHtml(fact.normalization.ruleVersion)}</small>` : ""}
    </article>`).join("")}</div>` : ""}
  </section>`;
}

export function renderReviewItems(items = [], detail = null) {
  if (!items.length) return `<div class="jobhunt-empty-inline">No open extraction reviews.</div>`;
  return `<div class="jobhunt-review-layout"><div class="jobhunt-review-list">${items.map((item) => `<button type="button" data-review-action="open" data-review-id="${escapeHtml(item.id)}">
    <span class="jobhunt-badge is-review-${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</span>
    <strong>${escapeHtml(item.reason.replaceAll("_", " "))}</strong>
    <small>${escapeHtml(item.entityType)} · ${escapeHtml(item.entityId)} · ${escapeHtml(item.createdAt)}</small>
  </button>`).join("")}</div>${detail ? renderReviewDetail(detail) : ""}</div>`;
}

function renderReviewDetail(detail) {
  const item = detail.item;
  const candidates = item.candidateResolutions || [];
  return `<section class="jobhunt-review-detail">
    <h3>${escapeHtml(item.reason.replaceAll("_", " "))}</h3>
    <p>${escapeHtml(item.evidenceSummary)}</p>
    ${candidates.length ? `<pre>${escapeHtml(JSON.stringify(candidates, null, 2))}</pre>` : ""}
    ${(detail.facts || []).length ? renderFactInspector({ runs: [], facts: detail.facts }) : ""}
    ${item.entityType === "job" ? `<form data-review-override-form data-review-id="${escapeHtml(item.id)}">
      <label><span>Canonical field</span><select name="field"><option value="title">title</option><option value="company">company</option><option value="location_city">location city</option><option value="location_country">location country</option><option value="work_model">work model</option><option value="contract_type">contract type</option><option value="salary_min">salary minimum</option><option value="salary_max">salary maximum</option><option value="salary_currency">salary currency</option><option value="salary_period">salary period</option><option value="salary_tax_type">salary gross/net state</option></select></label>
      <label><span>Replacement value</span><input name="value" required maxlength="500"></label>
      <label><span>Reason</span><input name="reason" required maxlength="1000"></label>
      <button class="jobhunt-primary-action" type="submit">Resolve with Human Override</button>
    </form>` : ""}
    <div class="jobhunt-form-actions"><button type="button" class="jobhunt-ghost-action" data-review-action="resolve" data-review-id="${escapeHtml(item.id)}">Resolve</button><button type="button" class="jobhunt-ghost-action" data-review-action="dismiss" data-review-id="${escapeHtml(item.id)}">Dismiss</button></div>
  </section>`;
}

export function createJobhuntReviewController({ root, api, onStatus = () => {} }) {
  const state = { items: [], detail: null, error: null, loading: false };
  function render() {
    if (!root) return;
    root.innerHTML = `${state.error ? `<div class="jobhunt-validation" data-tone="error">${escapeHtml(state.error)}</div>` : ""}${state.loading && !state.items.length ? `<div class="jobhunt-empty-inline">Loading reviews…</div>` : renderReviewItems(state.items, state.detail)}`;
  }
  async function refresh() {
    state.loading = true; state.error = null; render();
    try {
      const result = await api.reviews({ state: "open" });
      state.items = result.items || [];
      if (state.detail && !state.items.some((item) => item.id === state.detail.item.id)) state.detail = null;
    } catch (error) {
      state.error = error?.message || "Review Queue could not be loaded.";
    } finally {
      state.loading = false; render();
    }
  }
  root?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-review-action]");
    if (!button) return;
    try {
      if (button.dataset.reviewAction === "open") state.detail = await api.review(button.dataset.reviewId);
      else if (button.dataset.reviewAction === "resolve") {
        await api.resolveReview(button.dataset.reviewId, { resolution: "Reviewed locally" });
        onStatus("Review resolved.", "success"); await refresh(); return;
      } else if (button.dataset.reviewAction === "dismiss") {
        await api.dismissReview(button.dataset.reviewId, { resolution: "Dismissed locally" });
        onStatus("Review dismissed.", "success"); await refresh(); return;
      }
      render();
    } catch (error) { state.error = error?.message || "Review action failed."; render(); }
  });
  root?.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-review-override-form]");
    if (!form) return;
    event.preventDefault();
    const data = new FormData(form);
    let value = String(data.get("value") || "").trim();
    if (["salary_min", "salary_max"].includes(String(data.get("field")))) value = Number(value);
    try {
      await api.resolveReview(form.dataset.reviewId, {
        resolution: "Resolved with Human Override",
        override: { field: String(data.get("field")), value, reason: String(data.get("reason") || "").trim() },
      });
      onStatus("Human Override saved; source facts remain unchanged.", "success");
      await refresh();
    } catch (error) { state.error = error?.message || "Human Override failed."; render(); }
  });
  return { state, render, refresh };
}
