import { escapeHtml } from "./utils.js";
import { renderFactInspector } from "./jobhunt-extraction.js";

export const MANUAL_CAPTURE_MAX_BYTES = 1024 * 1024;

function shortHash(value) {
  const text = String(value || "");
  return text ? `${text.slice(0, 12)}…${text.slice(-8)}` : "unknown";
}

function sourceOptions(sources, selected = "manual") {
  return sources
    .filter((source) => source.policy?.accessMethod === "manual")
    .map((source) => `<option value="${escapeHtml(source.id)}"${source.key === selected ? " selected" : ""}>${escapeHtml(source.displayName)}</option>`)
    .join("");
}

function trackOptions(tracks) {
  return `<option value="">No Track</option>${tracks.map((track) => `<option value="${escapeHtml(track.id)}">${escapeHtml(track.name)}</option>`).join("")}`;
}

function profileOptions(profiles = []) {
  return `<option value="">No Search Profile</option>${profiles.map((profile) => `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.name)}</option>`).join("")}`;
}

export function renderSourceStatus(sources = []) {
  if (!sources.length) return `<div class="jobhunt-empty-inline">No source definitions are available.</div>`;
  return `<div class="jobhunt-source-grid">${sources.map((source) => `
    <article class="jobhunt-source-card" data-source-id="${escapeHtml(source.id)}">
      <div><span class="jobhunt-badge is-track-${escapeHtml(source.definitionState)}">${escapeHtml(source.policy.operationalState)}</span><strong>${escapeHtml(source.displayName)}</strong></div>
      <p>${escapeHtml(source.collectionStatus)}</p>
      <small>Access: ${escapeHtml(source.policy.accessMethod)} · Adapter: ${source.adapter.implemented ? escapeHtml(`${source.adapter.key} ${source.adapter.version}`) : "not implemented"}</small>
      <div><span>${source.listingCount} listings</span><span>${source.captureCount} captures</span></div>
    </article>`).join("")}</div>`;
}

function operationalValue(value) {
  return value === null || value === undefined || value === "" ? "not observed" : String(value);
}

export function renderNavOperations(status = null) {
  if (!status) return "";
  const source = status.source || {};
  const policy = source.policy || {};
  const feed = status.feedState || {};
  const worker = status.worker || {};
  const enabled = Boolean(policy.enabled);
  return `<section class="jobhunt-nav-operations" data-nav-status>
    <div class="jobhunt-career-block-head"><div><span class="jobhunt-section-label">Live source</span><h3>NAV / Arbeidsplassen</h3><p>Official pam-stilling-feed adapter · token configured: ${status.tokenConfigured ? "yes" : "no"}</p></div>
      <div class="jobhunt-form-actions">
        ${enabled ? `<button type="button" class="jobhunt-ghost-action" data-ingestion-action="nav-pause">Pause</button><button type="button" class="jobhunt-primary-action" data-ingestion-action="nav-sync"${status.tokenConfigured ? "" : " disabled"}>Sync NAV now</button>` : `<button type="button" class="jobhunt-primary-action" data-ingestion-action="nav-enable"${status.tokenConfigured ? "" : " disabled"}>Enable NAV</button>`}
      </div>
    </div>
    ${status.tokenConfigured ? "" : `<div class="jobhunt-validation" data-tone="warning">Set JOBHUNT_NAV_TOKEN on the backend to enable collection. The token is never returned to the browser.</div>`}
    <dl class="jobhunt-nav-metrics">
      <div><dt>Source</dt><dd>${escapeHtml(policy.operationalState || "paused")}</dd></div>
      <div><dt>Worker</dt><dd>${escapeHtml(worker.state || "stopped")}</dd></div>
      <div><dt>Last successful poll</dt><dd>${escapeHtml(operationalValue(feed.last_success_at || policy.lastSuccessAt))}</dd></div>
      <div><dt>Feed position</dt><dd>${escapeHtml(operationalValue(feed.current_feed_page_id || feed.feed_path))}</dd></div>
      <div><dt>Backoff until</dt><dd>${escapeHtml(operationalValue(policy.backoffUntil))}</dd></div>
      <div><dt>Listings observed</dt><dd>${escapeHtml(operationalValue(feed.listings_observed))}</dd></div>
      <div><dt>Active listings</dt><dd>${escapeHtml(operationalValue(feed.active_listings))}</dd></div>
      <div><dt>Matched listings</dt><dd>${escapeHtml(operationalValue(feed.matched_listings))}</dd></div>
      <div><dt>Captures created</dt><dd>${escapeHtml(operationalValue(feed.captures_created))}</dd></div>
    </dl>
    ${(feed.last_error_message || policy.lastErrorMessage) ? `<div class="jobhunt-validation" data-tone="error">${escapeHtml(feed.last_error_message || policy.lastErrorMessage)}</div>` : ""}
  </section>`;
}

export function renderJobbnorgeOperations(status = null) {
  if (!status) return "";
  const source = status.source || {};
  const policy = source.policy || {};
  const query = status.queryState || {};
  const worker = status.worker || {};
  const api = status.api || {};
  const enabled = Boolean(policy.enabled);
  return `<section class="jobhunt-nav-operations" data-jobbnorge-status>
    <div class="jobhunt-career-block-head"><div><span class="jobhunt-section-label">Live source</span><h3>Jobbnorge</h3><p>Method: Official Public API - ${escapeHtml(api.version || "v1")} - authentication: not required</p></div>
      <div class="jobhunt-form-actions">
        ${enabled ? `<button type="button" class="jobhunt-ghost-action" data-ingestion-action="jobbnorge-pause">Pause</button><button type="button" class="jobhunt-primary-action" data-ingestion-action="jobbnorge-sync">Sync now</button>` : `<button type="button" class="jobhunt-primary-action" data-ingestion-action="jobbnorge-enable">Enable</button>`}
      </div>
    </div>
    <dl class="jobhunt-nav-metrics">
      <div><dt>Source</dt><dd>${escapeHtml(policy.operationalState || "paused")}</dd></div>
      <div><dt>Worker</dt><dd>${escapeHtml(worker.state || "stopped")}</dd></div>
      <div><dt>Last poll</dt><dd>${escapeHtml(operationalValue(query.lastPollAt || policy.lastAttemptAt))}</dd></div>
      <div><dt>Last success</dt><dd>${escapeHtml(operationalValue(query.lastSuccessAt || policy.lastSuccessAt))}</dd></div>
      <div><dt>Cursor</dt><dd>${escapeHtml(`query ${Number(query.currentQueryIndex || 0) + 1}, page ${Number(query.currentPage || 1)}`)}</dd></div>
      <div><dt>Backoff until</dt><dd>${escapeHtml(operationalValue(policy.backoffUntil))}</dd></div>
      <div><dt>Listings observed</dt><dd>${Number(query.listingsObserved || 0)}</dd></div>
      <div><dt>Matched listings</dt><dd>${Number(query.matchedListings || 0)}</dd></div>
      <div><dt>Listing captures</dt><dd>${Number(query.capturesCreated || 0)}</dd></div>
      <div><dt>Collection evidence</dt><dd>${Number(source.collectionCaptureCount || 0)}</dd></div>
      <div><dt>Adapter</dt><dd>${escapeHtml(`${source.adapter?.key || "unavailable"} ${source.adapter?.version || ""}`.trim())}</dd></div>
      <div><dt>Policy review</dt><dd>${escapeHtml(policy.termsVersion || "not reviewed")}</dd></div>
    </dl>
    <p class="jobhunt-ai-privacy">Official Public API only. Exact collection response bytes are private evidence; per-listing JSON is explicitly derived and links back to its item index.</p>
    ${(query.lastErrorMessage || policy.lastErrorMessage) ? `<div class="jobhunt-validation" data-tone="error">${escapeHtml(query.lastErrorMessage || policy.lastErrorMessage)}</div>` : ""}
  </section>`;
}

export function renderPracujOperations(status = null, bindings = [], profiles = []) {
  if (!status) return "";
  const source = status.source || {};
  const policy = source.policy || {};
  const mail = status.mailState || {};
  const config = status.mailConfig || {};
  const worker = status.worker || {};
  const enabled = Boolean(policy.enabled);
  return `<section class="jobhunt-nav-operations" data-pracuj-status>
    <div class="jobhunt-career-block-head"><div><span class="jobhunt-section-label">Live source</span><h3>Pracuj.pl</h3><p>Method: Official JobAlert email</p></div>
      <div class="jobhunt-form-actions">
        ${enabled ? `<button type="button" class="jobhunt-ghost-action" data-ingestion-action="pracuj-pause">Pause</button><button type="button" class="jobhunt-primary-action" data-ingestion-action="pracuj-sync"${config.configured ? "" : " disabled"}>Sync now</button>` : `<button type="button" class="jobhunt-primary-action" data-ingestion-action="pracuj-enable"${config.configured ? "" : " disabled"}>Enable</button>`}
      </div>
    </div>
    ${config.configured ? "" : `<div class="jobhunt-validation" data-tone="warning">Configure the backend-only JOBHUNT_PRACUJ_IMAP_* settings. Credentials are never returned to the browser.</div>`}
    <dl class="jobhunt-nav-metrics">
      <div><dt>Source</dt><dd>${escapeHtml(policy.operationalState || "paused")}</dd></div>
      <div><dt>Mailbox configured</dt><dd>${config.configured ? "yes" : "no"}</dd></div>
      <div><dt>Host / folder</dt><dd>${escapeHtml(`${config.host || "not configured"} / ${config.mailbox || "INBOX"}`)}</dd></div>
      <div><dt>TLS / read-only</dt><dd>${config.tls ? "verified TLS / yes" : "unavailable"}</dd></div>
      <div><dt>Worker</dt><dd>${escapeHtml(worker.state || "stopped")}</dd></div>
      <div><dt>Last poll</dt><dd>${escapeHtml(operationalValue(mail.lastPollAt))}</dd></div>
      <div><dt>Last successful message</dt><dd>${escapeHtml(operationalValue(mail.lastSuccessfulMessageAt))}</dd></div>
      <div><dt>UID cursor</dt><dd>${escapeHtml(operationalValue(mail.lastProcessedUid))}</dd></div>
      <div><dt>Messages inspected</dt><dd>${Number(mail.messagesInspected || 0)}</dd></div>
      <div><dt>JobAlerts recognized</dt><dd>${Number(mail.alertsRecognized || 0)}</dd></div>
      <div><dt>Listings discovered</dt><dd>${Number(mail.listingsDiscovered || 0)}</dd></div>
      <div><dt>Captures created</dt><dd>${Number(mail.capturesCreated || 0)}</dd></div>
    </dl>
    ${(mail.lastErrorMessage || policy.lastErrorMessage) ? `<div class="jobhunt-validation" data-tone="error">${escapeHtml(mail.lastErrorMessage || policy.lastErrorMessage)}</div>` : ""}
    <div class="jobhunt-career-block-head"><div><h4>Alert / Search Profile bindings</h4><span>Optional subject text maps a JobAlert to local discovery context.</span></div></div>
    <form class="jobhunt-career-form" data-pracuj-binding-form>
      <label><span>Subject contains (optional)</span><input name="subjectMatcher" maxlength="200"></label>
      <label><span>Search Profile</span><select name="searchProfileId" required><option value="">Choose a Search Profile</option>${profiles.map((profile) => `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.trackName)} / ${escapeHtml(profile.name)}</option>`).join("")}</select></label>
      <div class="jobhunt-form-actions"><button type="submit" class="jobhunt-primary-action">Add binding</button></div>
    </form>
    ${bindings.length ? `<div class="jobhunt-worker-jobs">${bindings.map((binding) => `<article><div><span class="jobhunt-badge">${binding.enabled ? "enabled" : "paused"}</span><strong>${escapeHtml(binding.trackName || "Track")} / ${escapeHtml(binding.searchProfileName || binding.searchProfileId)}</strong><small>Subject: ${escapeHtml(binding.subjectMatcher || "any recognized JobAlert")}</small></div><button type="button" class="jobhunt-ghost-action" data-ingestion-action="pracuj-binding-toggle" data-binding-id="${escapeHtml(binding.id)}" data-enabled="${binding.enabled ? "false" : "true"}">${binding.enabled ? "Pause" : "Enable"}</button></article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No alert bindings. Listings remain source-observed without invented Track context.</div>`}
  </section>`;
}

export function renderWorkerQueue(result = null) {
  if (!result) return "";
  const counts = result.counts || {};
  const jobs = result.jobs || [];
  return `<section class="jobhunt-worker-queue"><div class="jobhunt-career-block-head"><div><h3>Collection queue</h3><span>${Number(counts.queued || 0)} queued · ${Number(counts.running || 0)} running · ${Number(counts.retry_wait || 0)} retrying · ${Number(counts.failed || 0)} failed</span></div></div>
    ${jobs.length ? `<div class="jobhunt-worker-jobs">${jobs.map((job) => `<article data-worker-job-id="${escapeHtml(job.id)}"><div><span class="jobhunt-badge">${escapeHtml(job.state)}</span><strong>${escapeHtml(job.type)}</strong><small>${escapeHtml(job.stage || job.state)} · attempt ${Number(job.attemptCount || 0)}/${Number(job.maxAttempts || 0)}</small></div>${job.cancellable ? `<button type="button" class="jobhunt-ghost-action" data-ingestion-action="worker-cancel" data-worker-job-id="${escapeHtml(job.id)}">Cancel</button>` : ""}${job.error?.message ? `<p>${escapeHtml(job.error.message)}</p>` : ""}</article>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No collection jobs yet.</div>`}
  </section>`;
}

export function renderCaptureHistory(captures = []) {
  if (!captures.length) return `<div class="jobhunt-empty-inline">No captures for this listing.</div>`;
  return `<div class="jobhunt-capture-history">${captures.map((capture) => `
    <button type="button" data-ingestion-action="capture" data-capture-id="${escapeHtml(capture.id)}">
      <span class="jobhunt-badge is-capture-${escapeHtml(capture.changeState || "first")}">${escapeHtml(capture.changeState || "first")}</span>
      <strong>${escapeHtml(capture.contentType)} · ${capture.byteSize} bytes</strong>
      <code>${escapeHtml(shortHash(capture.sha256))}</code>
      <time>${escapeHtml(capture.capturedAt)}</time>
    </button>`).join("")}</div>`;
}

function renderAIControls(preview, extraction, aiStatus, loading) {
  if (aiStatus === null) return "";
  const aiRuns = (extraction?.runs || []).filter((run) => run.extractorKind === "ai");
  const latest = aiRuns[0];
  if (!aiStatus?.configured) {
    return `<section class="jobhunt-ai-extraction"><h4>AI extraction</h4><div class="jobhunt-validation" data-tone="warning">AI extraction unavailable — provider not configured</div></section>`;
  }
  return `<section class="jobhunt-ai-extraction">
    <div class="jobhunt-career-block-head"><div><h4>AI extraction</h4><p>${latest ? `${escapeHtml(latest.status)} &middot; ${escapeHtml(latest.ai?.provider || "provider")} / ${escapeHtml(latest.ai?.model || "model")}` : "Not run"}</p></div>
      <button type="button" class="jobhunt-primary-action" data-ingestion-action="ai-extract" data-capture-id="${escapeHtml(preview.capture.id)}" data-force="${aiRuns.length ? "true" : "false"}"${loading ? " disabled" : ""}>${loading ? "Running AI extraction…" : aiRuns.length ? "Rerun AI extraction" : "Run AI extraction"}</button>
    </div>
    <p class="jobhunt-ai-privacy">Advertisement content may be sent to the configured AI provider. Career Profile, assessments, applications, Track preferences, recruiter details, and unrelated dashboard data are not sent.</p>
  </section>`;
}

export function renderListingDetail(detail, preview = null, extraction = null, aiStatus = null, aiLoading = false) {
  const listing = detail?.listing;
  if (!listing) return "";
  return `<section class="jobhunt-ingestion-detail">
    <div class="jobhunt-details-head"><div><span class="jobhunt-section-label">Source Listing</span><h3>${escapeHtml(listing.hints.title || listing.externalId || listing.id)}</h3><p>${escapeHtml(listing.source.displayName)} · ${escapeHtml(listing.lifecycleState)}</p></div><button type="button" class="jobhunt-ghost-action" data-ingestion-action="close-listing">Close</button></div>
    <dl><div><dt>Company hint</dt><dd>${escapeHtml(listing.hints.company || "unknown")}</dd></div><div><dt>Location hint</dt><dd>${escapeHtml(listing.hints.location || "unknown")}</dd></div><div><dt>External ID</dt><dd>${escapeHtml(listing.externalId || "unknown")}</dd></div><div><dt>First / last seen</dt><dd>${escapeHtml(listing.firstSeenAt)} / ${escapeHtml(listing.lastSeenAt)}</dd></div></dl>
    ${listing.observedUrl ? `<a href="${escapeHtml(listing.observedUrl)}" target="_blank" rel="noopener">${escapeHtml(listing.observedUrl)}</a>` : ""}
    <p>Discovery context: ${escapeHtml([...(listing.tracks || []).map((item) => item.name), ...(listing.searchProfiles || []).map((item) => item.name)].join(", ") || "none")}</p>
    <h4>Capture history</h4>${renderCaptureHistory(detail.captures)}
    ${preview ? `<section class="jobhunt-capture-preview"><div class="jobhunt-career-block-head"><div><h4>Inert capture preview</h4><p>${escapeHtml(preview.capture.contentType)} · ${preview.capture.byteSize} bytes · ${escapeHtml(shortHash(preview.capture.sha256))}</p></div><button type="button" class="jobhunt-primary-action" data-ingestion-action="extract" data-capture-id="${escapeHtml(preview.capture.id)}">Run deterministic extraction</button></div><pre>${escapeHtml(preview.content)}</pre>${renderFactInspector(extraction)}</section>` : ""}
    ${preview ? renderAIControls(preview, extraction, aiStatus, aiLoading) : ""}
  </section>`;
}

function renderListings(listings = []) {
  if (!listings.length) return `<div class="jobhunt-empty-inline">No source listings imported yet.</div>`;
  return `<div class="jobhunt-ingestion-listings">${listings.map((listing) => `
    <button type="button" data-ingestion-action="listing" data-listing-id="${escapeHtml(listing.id)}">
      <span>${escapeHtml(listing.source.displayName)}</span>
      <strong>${escapeHtml(listing.hints.title || listing.externalId || "Untitled source listing")}</strong>
      <small>${listing.captureCount} capture(s) · last seen ${escapeHtml(listing.lastSeenAt)}</small>
    </button>`).join("")}</div>`;
}

function importForm(state) {
  const selectedTrack = state.tracks.find((item) => item.id === state.selectedTrackId);
  const profiles = selectedTrack ? (state.trackDetails.get(selectedTrack.id)?.searchProfiles || []) : [];
  return `<form class="jobhunt-career-form jobhunt-manual-import-form" data-manual-import-form>
    <label><span>Source</span><select name="sourceId">${sourceOptions(state.sources)}</select></label>
    <label><span>Original URL (optional)</span><input name="originalUrl" type="url" maxlength="2048"></label>
    <label><span>External listing ID</span><input name="externalListingId" maxlength="300"></label>
    <label><span>Listing state</span><select name="lifecycleState"><option value="unknown">unknown</option><option value="active">active (explicit evidence only)</option><option value="expired">expired</option><option value="removed">removed</option></select></label>
    <label><span>Title hint</span><input name="titleHint" maxlength="500"></label>
    <label><span>Company hint</span><input name="companyHint" maxlength="500"></label>
    <label><span>Location hint</span><input name="locationHint" maxlength="500"></label>
    <label><span>Track context</span><select name="trackId">${trackOptions(state.tracks)}</select></label>
    <label><span>Search Profile context</span><select name="searchProfileId">${profileOptions(profiles)}</select></label>
    <label><span>Input type</span><select name="inputMode"><option value="text">Paste text</option><option value="html">Paste HTML</option><option value="json">Paste JSON</option><option value="file">Upload UTF-8 file</option></select></label>
    <label class="jobhunt-field-wide" data-paste-field><span>Exact advertisement content</span><textarea name="content" rows="12" spellcheck="false"></textarea></label>
    <label class="jobhunt-field-wide" data-file-field hidden><span>TXT, HTML, or JSON (max 1 MB)</span><input name="file" type="file" accept=".txt,.html,.htm,.json,text/plain,text/html,application/json"></label>
    <label class="jobhunt-field-wide"><span>Discovery notes</span><textarea name="notes" rows="3" maxlength="8000"></textarea></label>
    <label class="jobhunt-field-wide"><input name="forceNewListing" type="checkbox"> Treat this as an explicitly new listing even if its identity matches</label>
    <div class="jobhunt-form-actions jobhunt-field-wide"><button class="jobhunt-primary-action" type="submit">Save raw advertisement</button><span>Paste text is encoded as UTF-8 exactly as entered; it is not trimmed or reformatted.</span></div>
  </form>`;
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

export function createJobhuntIngestionController({ root, api, onStatus = () => {}, onExtracted = () => {} }) {
  const state = {
    sources: [], listings: [], tracks: [], trackDetails: new Map(), selectedTrackId: "",
    detail: null, preview: null, extraction: null, result: null, health: null,
    aiStatus: null, navStatus: null, pracujStatus: null, jobbnorgeStatus: null, pracujBindings: [], workerJobs: null,
    aiLoading: false, loading: false, error: null,
  };

  function render() {
    if (!root) return;
    if (state.loading && !state.sources.length) {
      root.innerHTML = `<div class="jobhunt-empty-inline">Loading ingestion sources…</div>`;
      return;
    }
    if (state.error && !state.sources.length) {
      root.innerHTML = `<div class="jobhunt-validation" data-tone="error">${escapeHtml(state.error)}</div>`;
      return;
    }
    const boundProfiles = [...state.trackDetails.values()].flatMap((detail) =>
      (detail.searchProfiles || []).map((profile) => ({
        ...profile, trackName: detail.track?.name || "Track",
      })),
    );
    root.innerHTML = `${state.error ? `<div class="jobhunt-validation" data-tone="error">${escapeHtml(state.error)}</div>` : ""}
      <div class="jobhunt-ingestion-layout"><div>${importForm(state)}${state.result ? `<div class="jobhunt-validation" data-tone="success"><strong>Raw capture saved.</strong><p>Listing ${escapeHtml(state.result.listing.id)} · Capture ${escapeHtml(state.result.capture.id)}</p><p>${escapeHtml(shortHash(state.result.capture.sha256))} · ${state.result.capture.byteSize} bytes · blob ${state.result.blobReused ? "reused" : "created"}</p><p>No parsing was performed.</p></div>` : ""}</div>
      <div>${renderNavOperations(state.navStatus)}${renderPracujOperations(state.pracujStatus, state.pracujBindings, boundProfiles)}${renderJobbnorgeOperations(state.jobbnorgeStatus)}${renderWorkerQueue(state.workerJobs)}<div class="jobhunt-career-block-head"><div><h3>Sources</h3><span>Definitions and operational policy are separate.</span></div><button type="button" class="jobhunt-ghost-action" data-ingestion-action="health">Check archive</button></div>${renderSourceStatus(state.sources)}
      ${state.health ? `<div class="jobhunt-validation" data-tone="${state.health.healthy ? "success" : "error"}">Archive: ${state.health.uniqueBlobs} blobs / ${state.health.totalRawBytes} bytes · ${state.health.missingCount} missing · ${state.health.corruptCount} corrupt · ${state.health.orphanCount} orphan</div>` : ""}
      <div class="jobhunt-career-block-head"><div><h3>Source Listings</h3><span>Source observations, not normalized jobs.</span></div></div>${renderListings(state.listings)}</div></div>
      ${renderListingDetail(state.detail, state.preview, state.extraction, state.aiStatus, state.aiLoading)}`;
  }

  async function loadExtraction(captureId, projection = null) {
    if (typeof api.captureExtractionRuns !== "function") return;
    const result = await api.captureExtractionRuns(captureId);
    const runs = result.runs || [];
    const details = await Promise.all(runs.map((run) => api.extractionFacts(run.id)));
    state.extraction = {
      runs,
      facts: details.flatMap((item) => item.facts || []),
      runVersions: Object.fromEntries(runs.map((run) => [run.id, run.extractorVersion])),
      showAi: state.aiStatus !== null,
      projection,
    };
  }

  async function refresh() {
    state.loading = true; state.error = null; render();
    try {
      const sourceResult = await api.sources();
      const sourceKeys = new Set((sourceResult.sources || [])
        .filter((source) => source.definitionState !== "planned" && source.adapter?.implemented === true)
        .map((source) => source.key));
      const optional = (key, method, fallback = null) => (
        sourceKeys.has(key) && typeof api[method] === "function"
          ? Promise.resolve().then(() => api[method]()).catch((error) => ({
            __error: error?.message === "Not found"
              ? "The running dashboard service does not expose this source status yet; restart it after updating."
              : error?.message || `${key} status unavailable`,
          }))
          : Promise.resolve(fallback)
      );
      const [listingResult, trackResult, aiStatus, navStatus, pracujStatus, jobbnorgeStatus, bindingResult, workerJobs] = await Promise.all([
        api.sourceListings(), api.tracks(),
        typeof api.aiStatus === "function" ? api.aiStatus().catch(() => null) : Promise.resolve(null),
        optional("nav", "navStatus"),
        optional("pracuj", "pracujStatus"),
        optional("jobbnorge", "jobbnorgeStatus"),
        optional("pracuj", "pracujBindings", { bindings: [] }),
        typeof api.workerJobs === "function" ? api.workerJobs({ limit: 20 }).catch(() => null) : Promise.resolve(null),
      ]);
      state.sources = sourceResult.sources || [];
      state.listings = listingResult.listings || [];
      state.tracks = trackResult.tracks || [];
      state.aiStatus = aiStatus;
      state.navStatus = navStatus?.__error ? null : navStatus;
      state.pracujStatus = pracujStatus?.__error ? null : pracujStatus;
      state.jobbnorgeStatus = jobbnorgeStatus?.__error ? null : jobbnorgeStatus;
      state.pracujBindings = bindingResult?.bindings || [];
      state.workerJobs = workerJobs;
      const sourceErrors = [navStatus, pracujStatus, jobbnorgeStatus]
        .filter((result) => result?.__error)
        .map((result) => result.__error);
      if (sourceErrors.length) state.error = `Some source diagnostics could not be loaded: ${sourceErrors.join("; ")}. Import and saved listings still work.`;
      const details = await Promise.all(state.tracks.map((track) => api.track(track.id)));
      state.trackDetails = new Map(details.map((detail) => [detail.track.id, detail]));
    } catch (error) {
      state.error = error?.message || "Ingestion data could not be loaded.";
    } finally {
      state.loading = false; render();
    }
  }

  root?.addEventListener("change", (event) => {
    const form = event.target.closest("[data-manual-import-form]");
    if (!form) return;
    if (event.target.name === "trackId") {
      state.selectedTrackId = event.target.value;
      const profiles = state.trackDetails.get(state.selectedTrackId)?.searchProfiles || [];
      form.elements.searchProfileId.innerHTML = profileOptions(profiles);
    } else if (event.target.name === "inputMode") {
      form.querySelector("[data-paste-field]").hidden = event.target.value === "file";
      form.querySelector("[data-file-field]").hidden = event.target.value !== "file";
    }
  });

  root?.addEventListener("submit", async (event) => {
    const bindingForm = event.target.closest("[data-pracuj-binding-form]");
    if (bindingForm) {
      event.preventDefault();
      const data = new FormData(bindingForm);
      try {
        await api.createPracujBinding({
          subjectMatcher: String(data.get("subjectMatcher") || "").trim() || null,
          searchProfileId: String(data.get("searchProfileId") || ""),
          enabled: true,
        });
        onStatus("Pracuj alert binding saved.", "success");
        await refresh();
      } catch (error) {
        state.error = error?.message || "Pracuj binding could not be saved.";
        render();
      }
      return;
    }
    const form = event.target.closest("[data-manual-import-form]");
    if (!form) return;
    event.preventDefault();
    const data = new FormData(form);
    const inputMode = String(data.get("inputMode") || "text");
    const payload = {
      sourceId: String(data.get("sourceId") || ""), originalUrl: String(data.get("originalUrl") || "").trim() || null,
      externalListingId: String(data.get("externalListingId") || "").trim() || null,
      titleHint: String(data.get("titleHint") || "").trim() || null,
      companyHint: String(data.get("companyHint") || "").trim() || null,
      locationHint: String(data.get("locationHint") || "").trim() || null,
      lifecycleState: String(data.get("lifecycleState") || "unknown"),
      trackId: String(data.get("trackId") || "") || null,
      searchProfileId: String(data.get("searchProfileId") || "") || null,
      notes: String(data.get("notes") || "").trim() || null,
      forceNewListing: data.get("forceNewListing") === "on", inputMode,
    };
    try {
      if (inputMode === "file") {
        const file = form.elements.file.files?.[0];
        if (!file) throw new Error("Choose a TXT, HTML, or JSON file.");
        if (file.size > MANUAL_CAPTURE_MAX_BYTES) throw new Error("Raw advertisement exceeds the 1 MB limit.");
        const bytes = new Uint8Array(await file.arrayBuffer());
        Object.assign(payload, { filename: file.name, declaredContentType: file.type || null, contentBase64: bytesToBase64(bytes) });
      } else {
        payload.content = String(data.get("content") ?? "");
        payload.contentType = { text: "text/plain", html: "text/html", json: "application/json" }[inputMode];
      }
      state.result = await api.manualImport(payload);
      state.detail = { listing: state.result.listing, captures: [state.result.capture] };
      state.preview = null; state.extraction = null;
      onStatus("Raw advertisement preserved. Deterministic extraction is ready to run.", "success");
      await refresh();
      state.detail = await api.sourceListing(state.result.listing.id);
      render();
    } catch (error) {
      state.error = error?.message || "Manual import failed.";
      onStatus(state.error, "error"); render();
    }
  });

  root?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-ingestion-action]");
    if (!button) return;
    try {
      if (button.dataset.ingestionAction === "health") state.health = await api.ingestionStorageHealth();
      else if (button.dataset.ingestionAction === "nav-enable") {
        await api.navEnable(); onStatus("NAV collection enabled and queued.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "nav-pause") {
        await api.navPause(); onStatus("NAV collection paused.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "nav-sync") {
        await api.navSync(); onStatus("NAV sync queued.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "pracuj-enable") {
        await api.pracujEnable(); onStatus("Pracuj JobAlert collection enabled and queued.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "pracuj-pause") {
        await api.pracujPause(); onStatus("Pracuj JobAlert collection paused.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "pracuj-sync") {
        await api.pracujSync(); onStatus("Pracuj mailbox sync queued.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "jobbnorge-enable") {
        await api.jobbnorgeEnable(); onStatus("Jobbnorge collection enabled and queued.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "jobbnorge-pause") {
        await api.jobbnorgePause(); onStatus("Jobbnorge collection paused.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "jobbnorge-sync") {
        await api.jobbnorgeSync(); onStatus("Jobbnorge sync queued.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "pracuj-binding-toggle") {
        await api.updatePracujBinding(button.dataset.bindingId, {
          enabled: button.dataset.enabled === "true",
        });
        onStatus("Pracuj alert binding updated.", "success"); await refresh(); return;
      } else if (button.dataset.ingestionAction === "worker-cancel") {
        await api.cancelWorkerJob(button.dataset.workerJobId); onStatus("Collection job cancellation requested.", "success"); await refresh(); return;
      }
      else if (button.dataset.ingestionAction === "listing") {
        state.detail = await api.sourceListing(button.dataset.listingId); state.preview = null; state.extraction = null;
      } else if (button.dataset.ingestionAction === "capture") {
        state.preview = await api.rawCapture(button.dataset.captureId);
        await loadExtraction(button.dataset.captureId);
      } else if (button.dataset.ingestionAction === "extract") {
        const result = await api.extractCapture(button.dataset.captureId);
        await loadExtraction(button.dataset.captureId, result.projection);
        await onExtracted(result);
        onStatus(`Deterministic extraction completed: ${result.runs.reduce((sum, run) => sum + run.factCount, 0)} fact(s).`, "success");
      } else if (button.dataset.ingestionAction === "ai-extract") {
        state.aiLoading = true; state.error = null; render();
        const result = await api.aiExtractCapture(button.dataset.captureId, {
          force: button.dataset.force === "true",
        });
        await loadExtraction(button.dataset.captureId, result.projection);
        await onExtracted(result);
        const tone = result.run.status === "failed" ? "error" : "success";
        onStatus(result.run.status === "failed"
          ? `AI extraction failed: ${result.run.errorMessage || "provider output was not accepted"}.`
          : `AI extraction completed: ${result.run.factCount} validated fact(s).`, tone);
      } else if (button.dataset.ingestionAction === "close-listing") {
        state.detail = null; state.preview = null; state.extraction = null;
      }
      render();
    } catch (error) {
      state.error = error?.message || "Ingestion request failed."; render();
    } finally {
      state.aiLoading = false;
      render();
    }
  });

  return { state, render, refresh };
}
