import {
  JOBHUNT_CHANGED_EVENT,
  JOBHUNT_MATCH_SETTINGS_DEFAULTS,
  JOBHUNT_MATCH_SETTINGS_STORAGE_KEY,
  JOBHUNT_OFFERS_STORAGE_KEY,
} from "./jobhunt-store.js";

export const JOBHUNT_AUTHORITY_STORAGE_KEY = "dashboard.jobhunt.authority";
export const JOBHUNT_MIGRATION_SCHEMA_VERSION = 1;

export class JobhuntApiError extends Error {
  constructor(message, { code = "jobhunt_request_failed", details = [], status = 0 } = {}) {
    super(message);
    this.name = "JobhuntApiError";
    this.code = code;
    this.details = Array.isArray(details) ? details : [];
    this.status = status;
  }
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stableValue(value[key])]),
    );
  }
  return value;
}

export function stableJobhuntJson(value) {
  return JSON.stringify(stableValue(value));
}

function fnv1a(text) {
  let value = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 0x01000193) >>> 0;
  }
  return value.toString(16).padStart(8, "0");
}

function queryString(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) query.set(key, String(value));
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

function parseStoredArray(raw, key, fallback) {
  if (raw === null || raw === "") return fallback;
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new JobhuntApiError(`Legacy ${key} data is not valid JSON.`, {
      code: "invalid_legacy_snapshot",
    });
  }
  if (!Array.isArray(parsed)) {
    throw new JobhuntApiError(`Legacy ${key} data must be an array.`, {
      code: "invalid_legacy_snapshot",
    });
  }
  return parsed;
}

export function readLegacyJobhuntSnapshot(storage = globalThis.localStorage) {
  if (!storage || typeof storage.getItem !== "function") {
    return {
      offers: [],
      matchSettings: JOBHUNT_MATCH_SETTINGS_DEFAULTS.map((item) => ({ ...item })),
    };
  }
  const offers = parseStoredArray(
    storage.getItem(JOBHUNT_OFFERS_STORAGE_KEY),
    "Job Hunt offers",
    [],
  );
  const matchSettings = parseStoredArray(
    storage.getItem(JOBHUNT_MATCH_SETTINGS_STORAGE_KEY),
    "Job Hunt match settings",
    JOBHUNT_MATCH_SETTINGS_DEFAULTS.map((item) => ({ ...item })),
  );
  return { offers, matchSettings };
}

export function buildJobhuntMigrationPayload(storage = globalThis.localStorage) {
  const snapshot = readLegacyJobhuntSnapshot(storage);
  const meaningful = {
    schemaVersion: JOBHUNT_MIGRATION_SCHEMA_VERSION,
    offers: snapshot.offers,
    matchSettings: snapshot.matchSettings,
  };
  return {
    ...meaningful,
    idempotencyKey: `jobhunt-local-storage-v1-${fnv1a(stableJobhuntJson(meaningful))}`,
  };
}

export function readJobhuntAuthorityMarker(storage = globalThis.localStorage) {
  if (!storage || typeof storage.getItem !== "function") return null;
  try {
    const marker = JSON.parse(storage.getItem(JOBHUNT_AUTHORITY_STORAGE_KEY) || "null");
    return marker?.authority === "sqlite" && marker?.verified === true ? marker : null;
  } catch {
    return null;
  }
}

export function decideJobhuntAuthority({ marker, migrationResult, apiAvailable = true } = {}) {
  if (marker?.authority === "sqlite" && marker?.verified === true) {
    return apiAvailable ? "api" : "unavailable";
  }
  if (migrationResult?.status === "succeeded" && migrationResult?.verified === true) return "api";
  return "legacy";
}

export function writeJobhuntAuthorityMarker(result, storage = globalThis.localStorage) {
  const marker = {
    authority: "sqlite",
    verified: true,
    migrationId: result.migrationId,
    fingerprint: result.fingerprint,
    cutoverAt: new Date().toISOString(),
  };
  if (storage && typeof storage.setItem === "function") {
    storage.setItem(JOBHUNT_AUTHORITY_STORAGE_KEY, JSON.stringify(marker));
  }
  return marker;
}

export function notifyJobhuntChanged() {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent(JOBHUNT_CHANGED_EVENT));
  }
}

export function createJobhuntApi({ fetchImpl = globalThis.fetch, baseUrl = "/api/jobhunt" } = {}) {
  if (typeof fetchImpl !== "function") throw new TypeError("A fetch implementation is required");

  async function request(path, { method = "GET", body, maxBytes = 1024 * 1024, signal } = {}) {
    const encodedBody = body === undefined ? undefined : JSON.stringify(body);
    if (encodedBody !== undefined && new TextEncoder().encode(encodedBody).byteLength > maxBytes) {
      throw new JobhuntApiError("Job Hunt request is too large.", {
        code: "jobhunt_request_too_large",
        status: 413,
      });
    }
    let response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method,
        cache: "no-store",
        signal,
        headers: encodedBody === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
        body: encodedBody,
      });
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw new JobhuntApiError(
        "Job Hunt API is unavailable. SQLite remains authoritative after cutover.",
        { code: "jobhunt_api_unavailable" },
      );
    }
    let envelope;
    try {
      envelope = await response.json();
    } catch {
      throw new JobhuntApiError(`Job Hunt API returned an unreadable response (${response.status}).`, {
        code: "invalid_jobhunt_response",
        status: response.status,
      });
    }
    if (!response.ok || envelope?.ok !== true) {
      throw new JobhuntApiError(envelope?.error || `Job Hunt request failed (${response.status}).`, {
        code: envelope?.code,
        details: envelope?.details,
        status: response.status,
      });
    }
    return envelope.data;
  }

  const id = (value) => encodeURIComponent(String(value));
  return {
    health: ({ signal } = {}) => request("/health", { signal }),
    overview: ({ signal } = {}) => request("/overview", { signal }),
    jobs: (params = {}, { signal } = {}) => request(`/jobs${queryString(params)}`, { signal }),
    job: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}`, { signal }),
    createJob: (payload, { signal } = {}) => request("/jobs", {
      method: "POST", body: payload, maxBytes: 1024 * 1024, signal,
    }),
    updateJob: (jobId, payload, { signal } = {}) => request(`/jobs/${id(jobId)}`, {
      method: "PATCH", body: payload, maxBytes: 1024 * 1024, signal,
    }),
    deleteJob: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}`, {
      method: "DELETE", signal,
    }),
    application: (jobId, { signal } = {}) => request(`/applications/${id(jobId)}`, { signal }),
    applicationCommand: (jobId, payload, { signal } = {}) => request(`/applications/${id(jobId)}/events`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    matchSettings: ({ signal } = {}) => request("/settings/match", { signal }),
    updateMatchSettings: (settings, { signal } = {}) => request("/settings/match", {
      method: "PATCH", body: { settings }, maxBytes: 64 * 1024, signal,
    }),
    profile: ({ signal } = {}) => request("/profile", { signal }),
    updateProfile: (payload, { signal } = {}) => request("/profile", {
      method: "PATCH", body: payload, maxBytes: 64 * 1024, signal,
    }),
    createProfileRecord: (collection, payload, { signal } = {}) => request(`/profile/${id(collection)}`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    updateProfileRecord: (collection, recordId, payload, { signal } = {}) => request(`/profile/${id(collection)}/${id(recordId)}`, {
      method: "PATCH", body: payload, maxBytes: 64 * 1024, signal,
    }),
    deleteProfileRecord: (collection, recordId, { signal } = {}) => request(`/profile/${id(collection)}/${id(recordId)}`, {
      method: "DELETE", signal,
    }),
    assessments: ({ signal } = {}) => request("/assessments", { signal }),
    assessment: (instrumentId, version, { signal } = {}) => request(
      `/assessments/${id(instrumentId)}${queryString({ version })}`, { signal },
    ),
    startAssessment: (instrumentId, instrumentVersion, { signal } = {}) => request("/assessment-runs", {
      method: "POST", body: { instrumentId, instrumentVersion }, maxBytes: 64 * 1024, signal,
    }),
    assessmentRun: (runId, { signal } = {}) => request(`/assessment-runs/${id(runId)}`, { signal }),
    saveAssessmentResponses: (runId, responses, { signal } = {}) => request(`/assessment-runs/${id(runId)}/responses`, {
      method: "POST", body: { responses }, maxBytes: 256 * 1024, signal,
    }),
    completeAssessment: (runId, { signal } = {}) => request(`/assessment-runs/${id(runId)}/complete`, {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    abandonAssessment: (runId, { signal } = {}) => request(`/assessment-runs/${id(runId)}/abandon`, {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    tracks: ({ signal } = {}) => request("/tracks", { signal }),
    track: (trackId, { signal } = {}) => request(`/tracks/${id(trackId)}`, { signal }),
    createTrack: (payload, { signal } = {}) => request("/tracks", {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    updateTrack: (trackId, payload, { signal } = {}) => request(`/tracks/${id(trackId)}`, {
      method: "PATCH", body: payload, maxBytes: 64 * 1024, signal,
    }),
    searchProfiles: (trackId, { signal } = {}) => request(`/tracks/${id(trackId)}/search-profiles`, { signal }),
    createSearchProfile: (trackId, payload, { signal } = {}) => request(`/tracks/${id(trackId)}/search-profiles`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    updateSearchProfile: (profileId, payload, { signal } = {}) => request(`/search-profiles/${id(profileId)}`, {
      method: "PATCH", body: payload, maxBytes: 64 * 1024, signal,
    }),
    jobTracks: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}/tracks`, { signal }),
    setJobTracks: (jobId, trackIds, { note = null, signal } = {}) => request(`/jobs/${id(jobId)}/tracks`, {
      method: "POST", body: { trackIds, origin: "manual", note }, maxBytes: 64 * 1024, signal,
    }),
    evaluation: (evaluationId, { signal } = {}) => request(`/evaluations/${id(evaluationId)}`, { signal }),
    jobEvaluations: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}/evaluations`, { signal }),
    evaluateJobTrack: (jobId, trackId, { signal } = {}) => request(`/jobs/${id(jobId)}/tracks/${id(trackId)}/evaluate`, {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    trackEvaluations: (trackId, { signal } = {}) => request(`/tracks/${id(trackId)}/evaluations`, { signal }),
    trackEvaluationPolicy: (trackId, { signal } = {}) => request(`/tracks/${id(trackId)}/evaluation-policy`, { signal }),
    trackEvaluationPolicyHistory: (trackId, { signal } = {}) => request(`/tracks/${id(trackId)}/evaluation-policy/history`, { signal }),
    createTrackEvaluationPolicy: (trackId, policy, { signal } = {}) => request(`/tracks/${id(trackId)}/evaluation-policy`, {
      method: "POST", body: { policy }, maxBytes: 64 * 1024, signal,
    }),
    trackSkillIntelligence: (trackId, params = {}, { signal } = {}) => request(
      `/tracks/${id(trackId)}/skills/intelligence${queryString(params)}`, { signal },
    ),
    trackSkillDetail: (trackId, conceptReference, params = {}, { signal } = {}) => request(
      `/tracks/${id(trackId)}/skills/${id(conceptReference)}${queryString(params)}`, { signal },
    ),
    trackUnmappedSkills: (trackId, params = {}, { signal } = {}) => request(
      `/tracks/${id(trackId)}/skills/unmapped${queryString(params)}`, { signal },
    ),
    trackSkillMeta: (trackId, params = {}, { signal } = {}) => request(
      `/tracks/${id(trackId)}/skills/meta${queryString(params)}`, { signal },
    ),
    marketAnalytics: (params = {}, { signal } = {}) => request(
      `/analytics/market${queryString(params)}`, { signal },
    ),
    sourceAnalytics: (params = {}, { signal } = {}) => request(
      `/analytics/sources${queryString(params)}`, { signal },
    ),
    applicationAnalytics: (params = {}, { signal } = {}) => request(
      `/analytics/applications${queryString(params)}`, { signal },
    ),
    tradeoffAnalytics: (trackIds, params = {}, { signal } = {}) => request(
      `/analytics/tradeoffs${queryString({ ...params, trackIds: (trackIds || []).join(",") })}`, { signal },
    ),
    trackAnalytics: (trackId, params = {}, { signal } = {}) => request(
      `/tracks/${id(trackId)}/analytics${queryString(params)}`, { signal },
    ),
    economicScenarios: (trackId, { signal } = {}) => request(
      `/economic-scenarios${queryString({ trackId })}`, { signal },
    ),
    saveEconomicScenario: (trackId, payload, { signal } = {}) => request(
      `/tracks/${id(trackId)}/economic-scenarios`, {
        method: "POST", body: payload, maxBytes: 128 * 1024, signal,
      },
    ),
    careerIntelligence: ({ signal } = {}) => request("/career-intelligence", { signal }),
    adjacentCareers: ({ signal } = {}) => request("/career-intelligence/adjacent", { signal }),
    trackProposals: ({ signal } = {}) => request("/career-intelligence/track-proposals", { signal }),
    decideTrackProposal: (proposalKey, action, payload = {}, { signal } = {}) => request(
      `/career-intelligence/track-proposals/${id(proposalKey)}/${id(action)}`, {
        method: "POST", body: payload, maxBytes: 64 * 1024, signal,
      },
    ),
    experimentTemplates: ({ signal } = {}) => request("/experiments/templates", { signal }),
    experiments: (params = {}, { signal } = {}) => request(`/experiments${queryString(params)}`, { signal }),
    experiment: (experimentId, { signal } = {}) => request(`/experiments/${id(experimentId)}`, { signal }),
    createExperiment: (payload, { signal } = {}) => request("/experiments", {
      method: "POST", body: payload, maxBytes: 128 * 1024, signal,
    }),
    updateExperiment: (experimentId, payload, { signal } = {}) => request(`/experiments/${id(experimentId)}`, {
      method: "PATCH", body: payload, maxBytes: 128 * 1024, signal,
    }),
    experimentCommand: (experimentId, action, payload = {}, { signal } = {}) => request(
      `/experiments/${id(experimentId)}/${id(action)}`, {
        method: "POST", body: payload, maxBytes: 128 * 1024, signal,
      },
    ),
    sources: ({ signal } = {}) => request("/sources", { signal }),
    source: (sourceId, { signal } = {}) => request(`/sources/${id(sourceId)}`, { signal }),
    workerStatus: ({ signal } = {}) => request("/worker/status", { signal }),
    workerJobs: (params = {}, { signal } = {}) => request(`/worker/jobs${queryString(params)}`, { signal }),
    workerJob: (jobId, { signal } = {}) => request(`/worker/jobs/${id(jobId)}`, { signal }),
    cancelWorkerJob: (jobId, { signal } = {}) => request(`/worker/jobs/${id(jobId)}/cancel`, {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    navStatus: ({ signal } = {}) => request("/sources/nav/status", { signal }),
    navFeedState: ({ signal } = {}) => request("/sources/nav/feed-state", { signal }),
    navEnable: ({ signal } = {}) => request("/sources/nav/enable", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    navPause: ({ signal } = {}) => request("/sources/nav/pause", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    navSync: ({ signal } = {}) => request("/sources/nav/sync", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    pracujStatus: ({ signal } = {}) => request("/sources/pracuj/status", { signal }),
    pracujMailState: ({ signal } = {}) => request("/sources/pracuj/mail-state", { signal }),
    pracujEnable: ({ signal } = {}) => request("/sources/pracuj/enable", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    pracujPause: ({ signal } = {}) => request("/sources/pracuj/pause", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    pracujSync: ({ signal } = {}) => request("/sources/pracuj/sync", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    jobbnorgeStatus: ({ signal } = {}) => request("/sources/jobbnorge/status", { signal }),
    jobbnorgeSyncState: ({ signal } = {}) => request("/sources/jobbnorge/sync-state", { signal }),
    jobbnorgeEnable: ({ signal } = {}) => request("/sources/jobbnorge/enable", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    jobbnorgePause: ({ signal } = {}) => request("/sources/jobbnorge/pause", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    jobbnorgeSync: ({ signal } = {}) => request("/sources/jobbnorge/sync", {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    pracujBindings: ({ signal } = {}) => request("/sources/pracuj/bindings", { signal }),
    createPracujBinding: (payload, { signal } = {}) => request("/sources/pracuj/bindings", {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    updatePracujBinding: (bindingId, payload, { signal } = {}) => request(`/sources/pracuj/bindings/${id(bindingId)}`, {
      method: "PATCH", body: payload, maxBytes: 64 * 1024, signal,
    }),
    sourceListings: (params = {}, { signal } = {}) => request(`/listings${queryString(params)}`, { signal }),
    sourceListing: (listingId, { signal } = {}) => request(`/listings/${id(listingId)}`, { signal }),
    listingCaptures: (listingId, { signal } = {}) => request(`/listings/${id(listingId)}/captures`, { signal }),
    rawCapture: (captureId, { signal } = {}) => request(`/captures/${id(captureId)}`, { signal }),
    aiStatus: ({ signal } = {}) => request("/ai/status", { signal }),
    aiConfigSummary: ({ signal } = {}) => request("/ai/config-summary", { signal }),
    extractCapture: (captureId, { signal } = {}) => request(`/captures/${id(captureId)}/extract`, {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    aiExtractCapture: (captureId, { force = false, signal } = {}) => request(`/captures/${id(captureId)}/ai-extract`, {
      method: "POST", body: { force }, maxBytes: 1024, signal,
    }),
    captureExtractionRuns: (captureId, { signal } = {}) => request(`/captures/${id(captureId)}/extraction-runs`, { signal }),
    extractionRun: (runId, { signal } = {}) => request(`/extraction-runs/${id(runId)}`, { signal }),
    extractionFacts: (runId, { signal } = {}) => request(`/extraction-runs/${id(runId)}/facts`, { signal }),
    jobFacts: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}/facts`, { signal }),
    reviews: (params = {}, { signal } = {}) => request(`/review${queryString(params)}`, { signal }),
    review: (reviewId, { signal } = {}) => request(`/review/${id(reviewId)}`, { signal }),
    resolveReview: (reviewId, payload = {}, { signal } = {}) => request(`/review/${id(reviewId)}/resolve`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    dismissReview: (reviewId, payload = {}, { signal } = {}) => request(`/review/${id(reviewId)}/dismiss`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    duplicates: (params = {}, { signal } = {}) => request(`/duplicates${queryString(params)}`, { signal }),
    duplicate: (candidateId, { signal } = {}) => request(`/duplicates/${id(candidateId)}`, { signal }),
    mergeDuplicate: (candidateId, payload, { signal } = {}) => request(`/duplicates/${id(candidateId)}/merge`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    markNotDuplicate: (candidateId, payload = {}, { signal } = {}) => request(`/duplicates/${id(candidateId)}/not-duplicate`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    dismissDuplicate: (candidateId, payload = {}, { signal } = {}) => request(`/duplicates/${id(candidateId)}/dismiss`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    dedupeMerges: (params = {}, { signal } = {}) => request(`/dedupe/merges${queryString(params)}`, { signal }),
    dedupeMerge: (mergeId, { signal } = {}) => request(`/dedupe/merges/${id(mergeId)}`, { signal }),
    unmerge: (mergeId, payload = {}, { signal } = {}) => request(`/dedupe/merges/${id(mergeId)}/unmerge`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    dedupeSummary: ({ signal } = {}) => request("/dedupe/summary", { signal }),
    dedupeScan: (jobId, { signal } = {}) => request(`/jobs/${id(jobId)}/dedupe-scan`, {
      method: "POST", body: {}, maxBytes: 1024, signal,
    }),
    createJobOverride: (jobId, payload, { signal } = {}) => request(`/jobs/${id(jobId)}/overrides`, {
      method: "POST", body: payload, maxBytes: 64 * 1024, signal,
    }),
    manualImport: (payload, { signal } = {}) => request("/manual-import", {
      method: "POST", body: payload, maxBytes: 2 * 1024 * 1024, signal,
    }),
    ingestionStorageHealth: ({ signal } = {}) => request("/ingestion/storage-health", { signal }),
    migrateLocalStorage: (payload, { signal } = {}) => request("/migrations/local-storage", {
      method: "POST", body: payload, maxBytes: 5 * 1024 * 1024, signal,
    }),
    migration: (migrationId, { signal } = {}) => request(`/migrations/${id(migrationId)}`, { signal }),
  };
}

export async function initializeJobhuntAuthority({
  api = jobhuntApi,
  storage = globalThis.localStorage,
} = {}) {
  const marker = readJobhuntAuthorityMarker(storage);
  if (marker) {
    try {
      await api.health();
      return { mode: "api", marker, migration: null };
    } catch (error) {
      return { mode: "unavailable", marker, migration: null, error };
    }
  }
  try {
    const payload = buildJobhuntMigrationPayload(storage);
    const migration = await api.migrateLocalStorage(payload);
    const mode = decideJobhuntAuthority({ migrationResult: migration, apiAvailable: true });
    if (mode !== "api") {
      return { mode: "legacy", marker: null, migration, error: null };
    }
    const nextMarker = writeJobhuntAuthorityMarker(migration, storage);
    notifyJobhuntChanged();
    return { mode: "api", marker: nextMarker, migration };
  } catch (error) {
    return { mode: "legacy", marker: null, migration: null, error };
  }
}

export const jobhuntApi = createJobhuntApi();
