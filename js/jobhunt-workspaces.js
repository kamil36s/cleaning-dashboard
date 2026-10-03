import { escapeHtml } from "./utils.js";

const PIPELINE = [
  { key: "inbox", title: "Inbox", statuses: ["new", "to_review"] },
  { key: "shortlist", title: "Shortlist", statuses: ["worth_applying"] },
  { key: "applied", title: "Applied", statuses: ["applied", "follow_up"] },
  { key: "interview", title: "Interviews", statuses: ["interview"] },
  { key: "outcome", title: "Outcomes", statuses: ["offer", "rejected", "archived", "expired"] },
];

function statusTone(source, setupReady, available = true) {
  if (!available) return ["warning", "Unavailable"];
  const policy = source?.policy || {};
  if (policy.lastErrorMessage || policy.operationalState === "degraded") return ["critical", "Error"];
  if (policy.enabled) return ["positive", "Connected"];
  if (!setupReady) return ["warning", "Setup needed"];
  return ["neutral", "Paused"];
}

function sourceCard(config) {
  const source = config.status?.source || config.source || {};
  const policy = source.policy || {};
  const [tone, label] = statusTone(source, config.setupReady, config.available);
  return `<article class="jobhunt-source-product-card" data-source-key="${escapeHtml(config.key)}">
    <header><div><span>${escapeHtml(config.method)}</span><h2>${escapeHtml(config.name)}</h2></div><span class="jobhunt-signal is-${tone}">${escapeHtml(label)}</span></header>
    <p>${escapeHtml(config.description)}</p>
    <dl><div><dt>Last sync</dt><dd>${escapeHtml(config.lastSync || policy.lastSuccessAt || "Never")}</dd></div><div><dt>Jobs discovered</dt><dd>${Number(source.listingCount || config.discovered || 0)}</dd></div></dl>
    ${config.error ? `<div class="jobhunt-inline-error"><strong>${config.available ? "Source needs attention" : "Source unavailable"}</strong><span>${escapeHtml(config.error)}</span></div>` : ""}
    <footer>
      <button type="button" class="jobhunt-primary-action" data-source-action="${source.policy?.enabled ? "sync" : "enable"}" data-source-key="${escapeHtml(config.key)}"${config.canEnable && config.available ? "" : " disabled"}>${config.available ? (source.policy?.enabled ? "Sync now" : "Enable") : "Unavailable"}</button>
      ${source.policy?.enabled ? `<button type="button" class="jobhunt-secondary-action" data-source-action="pause" data-source-key="${escapeHtml(config.key)}">Pause</button>` : ""}
      <button type="button" class="jobhunt-quiet-button" data-source-action="details" data-source-key="${escapeHtml(config.key)}">Settings</button>
    </footer>
  </article>`;
}

export function renderApplicationsWorkspace(jobs = []) {
  return `<div class="jobhunt-applications-workspace">
    <div class="jobhunt-workspace-intro"><div><span class="jobhunt-section-label">Pipeline</span><h2>Applications and next actions</h2><p>Move from review to follow-up without mixing application state with job facts.</p></div></div>
    <div class="jobhunt-pipeline-board" id="jobhunt-pipeline-panel">${PIPELINE.map((column) => {
      const cards = jobs.filter((job) => column.statuses.includes(job.applicationStatus || job.status));
      return `<section class="jobhunt-pipeline-column"><header><h3>${column.title}</h3><span>${cards.length}</span></header><div>${cards.length ? cards.map((job) => `<button type="button" class="jobhunt-application-card" data-application-job="${escapeHtml(job.id)}"><strong>${escapeHtml(job.role)}</strong><span>${escapeHtml(job.company)}</span><small>${escapeHtml(job.application?.followUpDate ? `Follow-up ${job.application.followUpDate}` : job.nextAction?.replaceAll("_", " ") || "Review")}</small></button>`).join("") : `<p>No jobs</p>`}</div></section>`;
    }).join("")}</div>
    <section class="jobhunt-application-agenda" id="jobhunt-followups-panel"><div><span class="jobhunt-section-label">Due now</span><h2>Follow-ups</h2></div>${jobs.filter((job) => job.application?.followUpDate).length ? `<div>${jobs.filter((job) => job.application?.followUpDate).sort((a, b) => a.application.followUpDate.localeCompare(b.application.followUpDate)).map((job) => `<button type="button" data-application-job="${escapeHtml(job.id)}"><time>${escapeHtml(job.application.followUpDate)}</time><span><strong>${escapeHtml(job.company)}</strong><small>${escapeHtml(job.role)}</small></span><em>${escapeHtml(job.applicationStatus || job.status)}</em></button>`).join("")}</div>` : `<div class="jobhunt-empty-inline">No follow-ups are scheduled.</div>`}</section>
  </div>`;
}

export function buildSourceCards({ sources = [], nav = null, pracuj = null, jobbnorge = null, errors = {} } = {}) {
  const sourceByKey = new Map(sources.map((source) => [source.key, source]));
  const registered = (key) => {
    const source = sourceByKey.get(key);
    return Boolean(source && source.definitionState !== "planned" && source.adapter?.implemented === true);
  };
  const sourceError = (key, error) => error || (registered(key) ? null : "This source is unavailable in the running backend. Restart the dashboard service after updating it.");
  return [
    {
      key: "nav", name: "NAV / Arbeidsplassen", method: "Official feed",
      description: "Norway vacancies from the official pam-stilling-feed.", status: nav,
      source: sourceByKey.get("nav"), available: registered("nav"), setupReady: Boolean(nav?.tokenConfigured), canEnable: Boolean(nav?.tokenConfigured),
      lastSync: nav?.feedState?.last_success_at, discovered: nav?.feedState?.listings_observed,
      error: sourceError("nav", errors.nav || nav?.feedState?.last_error_message || nav?.source?.policy?.lastErrorMessage),
    },
    {
      key: "pracuj", name: "Pracuj JobAlert", method: "Official JobAlert email",
      description: "Read-only mailbox collection for alerts you requested from Pracuj.", status: pracuj,
      source: sourceByKey.get("pracuj"), available: registered("pracuj"), setupReady: Boolean(pracuj?.mailConfig?.configured), canEnable: Boolean(pracuj?.mailConfig?.configured),
      lastSync: pracuj?.mailState?.lastSuccessfulMessageAt || pracuj?.mailState?.lastPollAt,
      discovered: pracuj?.mailState?.listingsDiscovered,
      error: sourceError("pracuj", errors.pracuj || pracuj?.mailState?.lastErrorMessage || pracuj?.source?.policy?.lastErrorMessage),
    },
    {
      key: "jobbnorge", name: "Jobbnorge", method: "Official Public API",
      description: "Public-sector vacancies through the unauthenticated official API.", status: jobbnorge,
      source: sourceByKey.get("jobbnorge"), available: registered("jobbnorge"), setupReady: true, canEnable: true,
      lastSync: jobbnorge?.queryState?.lastSuccessAt || jobbnorge?.queryState?.lastPollAt,
      discovered: jobbnorge?.queryState?.listingsObserved,
      error: sourceError("jobbnorge", errors.jobbnorge || jobbnorge?.queryState?.lastErrorMessage || jobbnorge?.source?.policy?.lastErrorMessage),
    },
  ];
}

export function renderSourcesWorkspace(data = {}, selectedKey = null) {
  const cards = buildSourceCards(data);
  const selected = cards.find((card) => card.key === selectedKey);
  return `<div class="jobhunt-sources-workspace">
    <div class="jobhunt-workspace-intro"><div><span class="jobhunt-section-label">Discovery</span><h2>Job sources</h2><p>Enable, pause, or sync each source independently. Saved jobs keep working if a source is unavailable.</p></div></div>
    <div class="jobhunt-source-product-grid">${cards.map(sourceCard).join("")}</div>
    ${selected ? renderSourceDetail(selected) : ""}
  </div>`;
}

export async function loadSourcesWorkspace(api) {
  const sourceResult = await api.sources();
  const sources = sourceResult.sources || [];
  const keys = new Set(sources
    .filter((source) => source.definitionState !== "planned" && source.adapter?.implemented === true)
    .map((source) => source.key));
  const specs = [
    ["nav", "navStatus"], ["pracuj", "pracujStatus"], ["jobbnorge", "jobbnorgeStatus"],
  ];
  const results = await Promise.all(specs.map(async ([key, method]) => {
    if (!keys.has(key) || typeof api[method] !== "function") return [key, null, null];
    try {
      return [key, await api[method](), null];
    } catch (error) {
      const message = error?.message === "Not found"
        ? "The running dashboard service does not expose this source status yet. Restart it to load the updated backend."
        : error?.message || `${key} status unavailable`;
      return [key, null, message];
    }
  }));
  const data = { sources, errors: {} };
  results.forEach(([key, value, error]) => {
    data[key] = value;
    if (error) data.errors[key] = error;
  });
  return data;
}

function renderSourceDetail(config) {
  const status = config.status || {};
  const source = status.source || config.source || {};
  const policy = source.policy || {};
  const technical = config.key === "nav" ? status.feedState : config.key === "pracuj" ? status.mailState : status.queryState;
  return `<section class="jobhunt-source-detail">
    <header><div><span class="jobhunt-section-label">Source settings</span><h2>${escapeHtml(config.name)}</h2></div><button type="button" class="jobhunt-icon-button" data-source-action="close-details" aria-label="Close source settings">×</button></header>
    <dl class="jobhunt-source-detail-grid"><div><dt>Enabled</dt><dd>${policy.enabled ? "Yes" : "No"}</dd></div><div><dt>Status</dt><dd>${escapeHtml(policy.operationalState || "Paused")}</dd></div><div><dt>Last sync</dt><dd>${escapeHtml(config.lastSync || "Never")}</dd></div><div><dt>Listings</dt><dd>${Number(source.listingCount || config.discovered || 0)}</dd></div></dl>
    ${config.error ? `<div class="jobhunt-inline-error"><strong>What failed</strong><span>${escapeHtml(config.error)}</span><small>Your saved jobs and other sources still work.</small></div>` : ""}
    <p class="jobhunt-setup-note">${config.setupReady ? "This source is ready to use." : "Complete the backend setup shown in Advanced diagnostics before enabling this source."}</p>
    <details><summary>Advanced source diagnostics</summary><pre>${escapeHtml(JSON.stringify({ policy, adapter: source.adapter, operationalState: technical }, null, 2))}</pre></details>
  </section>`;
}

export function renderAdvancedShell(section = "diagnostics") {
  const items = [
    ["diagnostics", "Diagnostics"], ["ingestion", "Evidence & import"], ["worker", "Worker"],
    ["merges", "Merge history"], ["evaluations", "Evaluation history"], ["policies", "Policy versions"],
    ["legacy", "Legacy compatibility"],
  ];
  return `<div class="jobhunt-advanced-shell">
    <aside aria-label="Advanced sections">${items.map(([key, label]) => `<a href="#advanced/${key}" class="${section === key ? "is-active" : ""}">${label}</a>`).join("")}</aside>
    <section class="jobhunt-advanced-content">
      <div class="jobhunt-workspace-intro"><div><span class="jobhunt-section-label">Advanced</span><h2>${escapeHtml(items.find(([key]) => key === section)?.[1] || "Diagnostics")}</h2><p>Technical provenance, operations, and compatibility tools are kept out of everyday workflows.</p></div></div>
      <div id="jobhunt-advanced-root"></div>
    </section>
  </div>`;
}
