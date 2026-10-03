import { escapeHtml } from "./utils.js";

function text(value, fallback = "unknown") {
  return escapeHtml(value === null || value === undefined || value === "" ? fallback : value);
}

function percent(value) {
  return value === null || value === undefined ? "unknown" : `${Math.round(Number(value) * 100)}%`;
}

function evidenceRows(evidence = {}) {
  const rows = [
    ["Same company", evidence.sameCompany],
    ["Title similarity", evidence.titleSimilarity === null ? null : percent(evidence.titleSimilarity)],
    ["Same city", evidence.sameCity],
    ["Same country", evidence.sameCountry],
    ["Publication delta", evidence.publicationDeltaDays === null ? null : `${evidence.publicationDeltaDays} days`],
    ["Salary compatible", evidence.salaryCompatible],
    ["Description similarity", evidence.descriptionSimilarity === null ? null : percent(evidence.descriptionSimilarity)],
    ["Exact shared URL", evidence.exactSharedUrl],
  ];
  return rows.map(([label, value]) => `
    <div class="jobhunt-dedupe-evidence-row">
      <span>${escapeHtml(label)}</span><strong>${text(value)}</strong>
    </div>
  `).join("");
}

function jobSummary(job = {}) {
  return `
    <article class="jobhunt-dedupe-side">
      <h4>${text(job.company)} — ${text(job.title)}</h4>
      <p>${text(job.city)}, ${text(job.country)} · ${text(job.publishedAt, "date unknown")}</p>
      <code>${text(job.id)}</code>
    </article>
  `;
}

export function renderDuplicateCandidate(candidate) {
  const contradictions = candidate.hardContradictions || [];
  return `
    <article class="jobhunt-dedupe-candidate" data-candidate-id="${text(candidate.id)}">
      <div class="jobhunt-dedupe-pair">
        ${jobSummary(candidate.leftJob)}
        ${jobSummary(candidate.rightJob)}
      </div>
      <div class="jobhunt-badge-row">
        <span class="jobhunt-badge">${text(candidate.confidenceClass)}</span>
        <span class="jobhunt-badge">${text(candidate.ruleVersion)}</span>
        <span class="jobhunt-badge">${text(candidate.state)}</span>
      </div>
      <p>${(candidate.reasonCodes || []).map(text).join(" · ") || "No reason codes"}</p>
      ${contradictions.length ? `<div class="jobhunt-validation" data-tone="error"><strong>Safety conflicts:</strong> ${contradictions.map(text).join(", ")}</div>` : ""}
      <div class="jobhunt-dedupe-evidence">${evidenceRows(candidate.evidence)}</div>
      ${candidate.state === "open" ? `
        <div class="jobhunt-form-actions">
          <button class="jobhunt-ghost-action" type="button" data-dedupe-action="compare" data-id="${text(candidate.id)}">Compare</button>
          <button class="jobhunt-primary-action" type="button" data-dedupe-action="merge" data-id="${text(candidate.id)}">Merge</button>
          <button class="jobhunt-ghost-action" type="button" data-dedupe-action="not-duplicate" data-id="${text(candidate.id)}">Not duplicate</button>
          <button class="jobhunt-ghost-action" type="button" data-dedupe-action="dismiss" data-id="${text(candidate.id)}">Later</button>
        </div>
      ` : ""}
    </article>
  `;
}

function comparisonSide(side) {
  if (!side) return `<div class="jobhunt-empty-inline">Canonical identity is no longer active.</div>`;
  const job = side.job || {};
  return `
    <article class="jobhunt-dedupe-side">
      <h4>${text(job.company)} — ${text(job.title)}</h4>
      <dl>
        <dt>Location</dt><dd>${text(job.location?.city)}, ${text(job.location?.country)} · ${text(job.location?.workMode)}</dd>
        <dt>Dates</dt><dd>${text(job.publishedAt, "unknown")} → ${text(job.expiresAt, "unknown")}</dd>
        <dt>Salary</dt><dd>${text(job.salary?.min)}–${text(job.salary?.max)} ${text(job.salary?.currency)} / ${text(job.salary?.period)}</dd>
        <dt>Application</dt><dd>${side.application?.meaningful ? "Meaningful history" : "Default/discovered only"} · ${text(side.application?.status)} · ${Number(side.application?.eventCount || 0)} events</dd>
        <dt>Tracks</dt><dd>${(side.tracks || []).map((item) => `${text(item.trackId)} (${text(item.origin)})`).join(", ") || "none"}</dd>
        <dt>Overrides</dt><dd>${(side.overrides || []).map((item) => `${text(item.field)} = ${text(JSON.stringify(item.replacement))}`).join(", ") || "none"}</dd>
      </dl>
      <h5>Source provenance</h5>
      <ul>${(side.sources || []).map((item) => `<li>${text(item.source)} · ${text(item.externalId)} · ${text(item.lifecycleState)}<br><small>${text(item.canonicalUrl || item.observedUrl, "URL unavailable")}</small></li>`).join("") || "<li>None</li>"}</ul>
    </article>
  `;
}

export function renderDuplicateDetail(detail) {
  if (!detail) return "";
  const safety = detail.safety || { safe: false, blockers: ["stale_candidate"] };
  return `
    <section class="jobhunt-dedupe-detail">
      <div class="jobhunt-card-head"><h3>Side-by-side review</h3><span class="jobhunt-badge">${detail.evidenceCurrent ? "evidence current" : "stale evidence"}</span></div>
      <div class="jobhunt-dedupe-pair">
        ${comparisonSide(detail.comparison?.left)}
        ${comparisonSide(detail.comparison?.right)}
      </div>
      <div class="jobhunt-validation" data-tone="${safety.safe ? "success" : "error"}">
        <strong>${safety.safe ? "Merge is currently safe." : "Merge is blocked."}</strong>
        ${safety.blockers?.length ? ` ${safety.blockers.map(text).join(", ")}` : ""}
        <br>Proposed survivor: ${text(safety.survivorJobId)}
      </div>
    </section>
  `;
}

export function renderMergeHistoryItem(merge) {
  return `
    <article class="jobhunt-dedupe-merge">
      <div><strong>${text(merge.survivor?.company)} — ${text(merge.survivor?.title)}</strong></div>
      <p>Absorbed ${text(merge.absorbed?.company)} — ${text(merge.absorbed?.title)}</p>
      <p>${text(merge.origin)} · ${text(merge.ruleVersion)} · ${text(merge.mergedAt)} · ${text(merge.state)}</p>
      <p>${text(merge.reason)}</p>
      ${merge.state === "active" ? `<button class="jobhunt-ghost-action" type="button" data-dedupe-action="unmerge" data-id="${text(merge.id)}">Unmerge</button>` : ""}
    </article>
  `;
}

export function createJobhuntDedupeController({ root, api, onStatus = () => {}, onChanged = () => {} } = {}) {
  const state = { items: [], merges: [], summary: {}, selected: null, loading: false, error: "" };

  function render() {
    if (!root) return;
    if (state.loading && !state.items.length) {
      root.innerHTML = `<div class="jobhunt-empty-inline">Loading duplicate candidates…</div>`;
      return;
    }
    if (state.error) {
      root.innerHTML = `<div class="jobhunt-validation" data-tone="error">${text(state.error)}</div>`;
      return;
    }
    const summary = state.summary || {};
    root.innerHTML = `
      <div class="jobhunt-dedupe-summary">
        <span><strong>${Number(summary.openCandidates || 0)}</strong> open candidates</span>
        <span><strong>${Number(summary.activeMerges || 0)}</strong> active merges</span>
        <span><strong>${Number(summary.notDuplicatePairs || 0)}</strong> not duplicate</span>
        <span><strong>${Number(summary.mergedCanonicalJobs || 0)}</strong> merged identities</span>
      </div>
      <p class="jobhunt-muted">Counts: ${Number(summary.sourceListings || 0)} Source Listings · ${Number(summary.canonicalJobs || 0)} active Canonical Jobs · ${Number(summary.rawCaptures || 0)} Raw Captures. These denominators are intentionally distinct.</p>
      <div class="jobhunt-dedupe-list">${state.items.length ? state.items.map(renderDuplicateCandidate).join("") : `<div class="jobhunt-empty-inline">No open duplicate candidates.</div>`}</div>
      ${renderDuplicateDetail(state.selected)}
      <section class="jobhunt-dedupe-history"><h3>Merge history</h3>${state.merges.length ? state.merges.map(renderMergeHistoryItem).join("") : `<div class="jobhunt-empty-inline">No merges recorded.</div>`}</section>
    `;
  }

  async function refresh() {
    if (!root) return;
    state.loading = true;
    state.error = "";
    render();
    try {
      const [duplicates, merges] = await Promise.all([
        api.duplicates({ state: "open", limit: 200 }),
        api.dedupeMerges({ limit: 200 }),
      ]);
      state.items = duplicates.items || [];
      state.merges = merges.items || [];
      state.summary = duplicates.summary || merges.summary || {};
    } catch (error) {
      state.error = error?.message || "Duplicate review is unavailable.";
    } finally {
      state.loading = false;
      render();
    }
  }

  async function showDetail(id) {
    state.selected = await api.duplicate(id);
    render();
    return state.selected;
  }

  async function act(action, id) {
    try {
      if (action === "compare") {
        await showDetail(id);
        return;
      }
      if (action === "merge") {
        const detail = await showDetail(id);
        if (!detail.evidenceCurrent || !detail.safety?.safe) {
          onStatus(`Merge blocked: ${(detail.safety?.blockers || ["stale evidence"]).join(", ")}`, "error");
          return;
        }
        const listingCount = (detail.comparison?.left?.sources?.length || 0) + (detail.comparison?.right?.sources?.length || 0);
        if (!globalThis.confirm?.(`Merge these identities into ${detail.safety.survivorJobId}? ${listingCount} Source Listings and all evidence will be preserved.`)) return;
        await api.mergeDuplicate(id, {
          confirm: true, survivorJobId: detail.safety.survivorJobId,
          note: "Confirmed in duplicate review UI",
        });
        onStatus("Canonical Jobs merged; source evidence and history were preserved.", "success");
      } else if (action === "not-duplicate") {
        await api.markNotDuplicate(id, { note: "Confirmed in duplicate review UI" });
        onStatus("Pair marked not duplicate.", "success");
      } else if (action === "dismiss") {
        await api.dismissDuplicate(id, { note: "Deferred in duplicate review UI" });
        onStatus("Duplicate candidate deferred.", "success");
      } else if (action === "unmerge") {
        if (!globalThis.confirm?.("Unmerge these Canonical Jobs? Current source evidence will be reprojected after ownership is restored.")) return;
        await api.unmerge(id, { note: "Reverted in merge history UI" });
        onStatus("Merge reverted and current evidence reprojected.", "success");
      }
      state.selected = null;
      await refresh();
      onChanged();
    } catch (error) {
      onStatus(error?.message || "Duplicate operation failed.", "error");
    }
  }

  root?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-dedupe-action]");
    if (button) act(button.dataset.dedupeAction, button.dataset.id);
  });

  return { state, render, refresh, showDetail, act };
}

