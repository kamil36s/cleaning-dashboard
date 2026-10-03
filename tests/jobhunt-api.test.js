import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JOBHUNT_AUTHORITY_STORAGE_KEY,
  buildJobhuntMigrationPayload,
  createJobhuntApi,
  decideJobhuntAuthority,
  initializeJobhuntAuthority,
  readLegacyJobhuntSnapshot,
} from "../js/jobhunt-api.js";
import {
  JOBHUNT_MATCH_SETTINGS_STORAGE_KEY,
  JOBHUNT_OFFERS_STORAGE_KEY,
} from "../js/jobhunt-store.js";

function response(data, { ok = true, status = 200, error, code } = {}) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(ok
      ? { ok: true, data }
      : { ok: false, error: error || "Request failed", code }),
  };
}

describe("Job Hunt API adapter and cutover", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("builds a deterministic versioned migration without changing legacy keys", () => {
    const offers = [{ id: "legacy-1", company: "ACME", extra: { preserved: true } }];
    const settings = [{ id: "manual_qa", weight: 31 }];
    localStorage.setItem(JOBHUNT_OFFERS_STORAGE_KEY, JSON.stringify(offers));
    localStorage.setItem(JOBHUNT_MATCH_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    const offersBefore = localStorage.getItem(JOBHUNT_OFFERS_STORAGE_KEY);
    const settingsBefore = localStorage.getItem(JOBHUNT_MATCH_SETTINGS_STORAGE_KEY);

    const first = buildJobhuntMigrationPayload();
    const second = buildJobhuntMigrationPayload();

    expect(first).toEqual(second);
    expect(first.schemaVersion).toBe(1);
    expect(first.idempotencyKey).toMatch(/^jobhunt-local-storage-v1-/);
    expect(first.offers[0].extra).toEqual({ preserved: true });
    expect(localStorage.getItem(JOBHUNT_OFFERS_STORAGE_KEY)).toBe(offersBefore);
    expect(localStorage.getItem(JOBHUNT_MATCH_SETTINGS_STORAGE_KEY)).toBe(settingsBefore);
  });

  it("rejects malformed legacy storage instead of overwriting it", () => {
    localStorage.setItem(JOBHUNT_OFFERS_STORAGE_KEY, "{broken");
    expect(() => readLegacyJobhuntSnapshot()).toThrow(/not valid JSON/);
    expect(localStorage.getItem(JOBHUNT_OFFERS_STORAGE_KEY)).toBe("{broken");
  });

  it("uses encoded API routes, no-store reads, and normalized errors", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ jobs: [] }))
      .mockResolvedValueOnce(response({ job: { id: "job/1" } }))
      .mockResolvedValueOnce(response(null, {
        ok: false, status: 404, error: "Job not found", code: "jobhunt_job_not_found",
      }));
    const api = createJobhuntApi({ fetchImpl });

    await api.jobs();
    await api.updateJob("job/1", { notes: "hello" });
    await expect(api.job("missing")).rejects.toMatchObject({
      message: "Job not found", code: "jobhunt_job_not_found", status: 404,
    });

    expect(fetchImpl).toHaveBeenNthCalledWith(1, "/api/jobhunt/jobs", expect.objectContaining({
      method: "GET", cache: "no-store",
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/jobhunt/jobs/job%2F1", expect.objectContaining({
      method: "PATCH", body: JSON.stringify({ notes: "hello" }),
    }));
  });

  it("supports profile and versioned assessment route families", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ profile: { revision: 1 } }))
      .mockResolvedValueOnce(response({ record: { id: "skill/1" } }))
      .mockResolvedValueOnce(response({ instruments: [] }))
      .mockResolvedValueOnce(response({ run: { id: "run/1" } }))
      .mockResolvedValueOnce(response({ run: { id: "run/1", responses: { q1: 4 } } }))
      .mockResolvedValueOnce(response({ run: { id: "run/1", status: "completed" } }));
    const api = createJobhuntApi({ fetchImpl });

    await api.profile();
    await api.updateProfileRecord("skills", "skill/1", { level: 4 });
    await api.assessments();
    await api.startAssessment("ipip-50-big-five-markers", "1.0.0");
    await api.saveAssessmentResponses("run/1", { q1: 4 });
    await api.completeAssessment("run/1");

    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/jobhunt/profile/skills/skill%2F1", expect.objectContaining({
      method: "PATCH", body: JSON.stringify({ level: 4 }),
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(4, "/api/jobhunt/assessment-runs", expect.objectContaining({
      method: "POST", body: JSON.stringify({
        instrumentId: "ipip-50-big-five-markers", instrumentVersion: "1.0.0",
      }),
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(5, "/api/jobhunt/assessment-runs/run%2F1/responses", expect.objectContaining({
      body: JSON.stringify({ responses: { q1: 4 } }),
    }));
  });

  it("supports Track, Search Profile, and many-to-many assignment routes", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ tracks: [] }))
      .mockResolvedValueOnce(response({ track: { id: "track/1" } }))
      .mockResolvedValueOnce(response({ searchProfile: { id: "profile/1" } }))
      .mockResolvedValueOnce(response({ searchProfile: { id: "profile/1", status: "paused" } }))
      .mockResolvedValueOnce(response({ tracks: [] }))
      .mockResolvedValueOnce(response({ tracks: [{ trackId: "track/1", assigned: true }] }));
    const api = createJobhuntApi({ fetchImpl });

    await api.tracks();
    await api.updateTrack("track/1", { status: "active" });
    await api.createSearchProfile("track/1", { name: "Manual QA" });
    await api.updateSearchProfile("profile/1", { status: "paused" });
    await api.jobTracks("job/1");
    await api.setJobTracks("job/1", ["track/1", "track/2"], { note: "Relevant" });

    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/jobhunt/tracks/track%2F1", expect.objectContaining({
      method: "PATCH", body: JSON.stringify({ status: "active" }),
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(3, "/api/jobhunt/tracks/track%2F1/search-profiles", expect.objectContaining({
      method: "POST",
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(6, "/api/jobhunt/jobs/job%2F1/tracks", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ trackIds: ["track/1", "track/2"], origin: "manual", note: "Relevant" }),
    }));
  });

  it("supports Pack J policy, Evaluation, and history routes", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ policy: { version: 1 } }))
      .mockResolvedValueOnce(response({ items: [{ version: 1 }] }))
      .mockResolvedValueOnce(response({ policy: { version: 2 } }))
      .mockResolvedValueOnce(response({ evaluation: { id: "evaluation/1" } }))
      .mockResolvedValueOnce(response({ evaluation: { id: "evaluation/1" } }))
      .mockResolvedValueOnce(response({ targets: [] }))
      .mockResolvedValueOnce(response({ items: [] }));
    const api = createJobhuntApi({ fetchImpl });
    const policy = { schemaVersion: "track-evaluation-policy@1", aggregate: "none" };

    await api.trackEvaluationPolicy("track/1");
    await api.trackEvaluationPolicyHistory("track/1");
    await api.createTrackEvaluationPolicy("track/1", policy);
    await api.evaluateJobTrack("job/1", "track/1");
    await api.evaluation("evaluation/1");
    await api.jobEvaluations("job/1");
    await api.trackEvaluations("track/1");

    expect(fetchImpl).toHaveBeenNthCalledWith(1, "/api/jobhunt/tracks/track%2F1/evaluation-policy", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/jobhunt/tracks/track%2F1/evaluation-policy/history", expect.objectContaining({ cache: "no-store" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(3, "/api/jobhunt/tracks/track%2F1/evaluation-policy", expect.objectContaining({
      method: "POST", body: JSON.stringify({ policy }),
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(4, "/api/jobhunt/jobs/job%2F1/tracks/track%2F1/evaluate", expect.objectContaining({
      method: "POST", body: "{}",
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(5, "/api/jobhunt/evaluations/evaluation%2F1", expect.objectContaining({ method: "GET" }));
  });

  it("supports Pack D source, listing, capture, manual import, and health routes", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ sources: [] }))
      .mockResolvedValueOnce(response({ listings: [] }))
      .mockResolvedValueOnce(response({ listing: { id: "listing/1" }, captures: [] }))
      .mockResolvedValueOnce(response({ capture: { id: "capture/1" }, content: "safe" }))
      .mockResolvedValueOnce(response({ listing: { id: "listing/1" }, capture: { id: "capture/1" } }))
      .mockResolvedValueOnce(response({ healthy: true }));
    const api = createJobhuntApi({ fetchImpl });

    await api.sources();
    await api.sourceListings({ sourceId: "source/1" });
    await api.sourceListing("listing/1");
    await api.rawCapture("capture/1");
    await api.manualImport({ inputMode: "text", contentType: "text/plain", content: "raw" });
    await api.ingestionStorageHealth();

    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/jobhunt/listings?sourceId=source%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(3, "/api/jobhunt/listings/listing%2F1", expect.objectContaining({ cache: "no-store" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(4, "/api/jobhunt/captures/capture%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(5, "/api/jobhunt/manual-import", expect.objectContaining({
      method: "POST", body: JSON.stringify({ inputMode: "text", contentType: "text/plain", content: "raw" }),
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(6, "/api/jobhunt/ingestion/storage-health", expect.objectContaining({ method: "GET" }));
  });

  it("supports Pack K Track Skill Intelligence, detail, unmapped, and meta routes", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ skills: [] }))
      .mockResolvedValueOnce(response({ skill: { reference: "skill:SQL" } }))
      .mockResolvedValueOnce(response({ unmapped: { terms: [] } }))
      .mockResolvedValueOnce(response({ population: {} }));
    const api = createJobhuntApi({ fetchImpl });

    await api.trackSkillIntelligence("track/1", {
      population: "historical", window: "90d", requirementClass: "required", sort: "demand",
    });
    await api.trackSkillDetail("track/1", "skill:SQL", { population: "current" });
    await api.trackUnmappedSkills("track/1", { window: "30d" });
    await api.trackSkillMeta("track/1", { population: "current" });

    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      "/api/jobhunt/tracks/track%2F1/skills/intelligence?population=historical&window=90d&requirementClass=required&sort=demand",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
    expect(fetchImpl).toHaveBeenNthCalledWith(
      2,
      "/api/jobhunt/tracks/track%2F1/skills/skill%3ASQL?population=current",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchImpl).toHaveBeenNthCalledWith(
      3,
      "/api/jobhunt/tracks/track%2F1/skills/unmapped?window=30d",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("supports Pack E extraction, facts, review, and Human Override routes", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ runs: [] }))
      .mockResolvedValueOnce(response({ runs: [{ id: "run/1" }], projection: {} }))
      .mockResolvedValueOnce(response({ run: { id: "run/1" }, facts: [] }))
      .mockResolvedValueOnce(response({ facts: [], projection: {} }))
      .mockResolvedValueOnce(response({ items: [] }))
      .mockResolvedValueOnce(response({ item: { id: "review/1" } }))
      .mockResolvedValueOnce(response({ item: { id: "review/1", state: "resolved" } }))
      .mockResolvedValueOnce(response({ item: { id: "review/2", state: "dismissed" } }))
      .mockResolvedValueOnce(response({ override: { id: "override/1" } }));
    const api = createJobhuntApi({ fetchImpl });

    await api.captureExtractionRuns("capture/1");
    await api.extractCapture("capture/1");
    await api.extractionFacts("run/1");
    await api.jobFacts("job/1");
    await api.reviews({ state: "open" });
    await api.review("review/1");
    await api.resolveReview("review/1", { resolution: "confirmed" });
    await api.dismissReview("review/2", { resolution: "irrelevant" });
    await api.createJobOverride("job/1", { field: "salary_min", value: 55000, reason: "confirmed" });

    expect(fetchImpl).toHaveBeenNthCalledWith(1, "/api/jobhunt/captures/capture%2F1/extraction-runs", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/jobhunt/captures/capture%2F1/extract", expect.objectContaining({ method: "POST", body: "{}" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(3, "/api/jobhunt/extraction-runs/run%2F1/facts", expect.objectContaining({ cache: "no-store" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(5, "/api/jobhunt/review?state=open", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(7, "/api/jobhunt/review/review%2F1/resolve", expect.objectContaining({ method: "POST" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(9, "/api/jobhunt/jobs/job%2F1/overrides", expect.objectContaining({ method: "POST" }));
  });

  it("supports Pack F safe status and backend-selected AI extraction routes", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ configured: true, provider: "fake", model: "fake-job-facts" }))
      .mockResolvedValueOnce(response({ configured: true }))
      .mockResolvedValueOnce(response({ run: { id: "run/ai" } }));
    const api = createJobhuntApi({ fetchImpl });

    await api.aiStatus();
    await api.aiConfigSummary();
    await api.aiExtractCapture("capture/1", { force: true });

    expect(fetchImpl).toHaveBeenNthCalledWith(1, "/api/jobhunt/ai/status", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/api/jobhunt/ai/config-summary", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenNthCalledWith(3, "/api/jobhunt/captures/capture%2F1/ai-extract", expect.objectContaining({
      method: "POST", body: JSON.stringify({ force: true }),
    }));
  });

  it("cuts over only after a verified successful migration", async () => {
    localStorage.setItem(JOBHUNT_OFFERS_STORAGE_KEY, JSON.stringify([{ id: "legacy-1" }]));
    const api = {
      migrateLocalStorage: vi.fn().mockResolvedValue({
        migrationId: "mig_1", fingerprint: "abc", status: "succeeded", verified: true,
        imported: 1, alreadyExisting: 0,
      }),
      health: vi.fn(),
    };

    const result = await initializeJobhuntAuthority({ api, storage: localStorage });

    expect(result.mode).toBe("api");
    expect(api.migrateLocalStorage).toHaveBeenCalledTimes(1);
    expect(JSON.parse(localStorage.getItem(JOBHUNT_AUTHORITY_STORAGE_KEY))).toMatchObject({
      authority: "sqlite", verified: true, migrationId: "mig_1",
    });
    expect(localStorage.getItem(JOBHUNT_OFFERS_STORAGE_KEY)).toBe(JSON.stringify([{ id: "legacy-1" }]));
  });

  it("reuses the cutover marker and reports an outage without writable fallback", async () => {
    localStorage.setItem(JOBHUNT_AUTHORITY_STORAGE_KEY, JSON.stringify({
      authority: "sqlite", verified: true, migrationId: "mig_1", fingerprint: "abc",
    }));
    const api = {
      health: vi.fn().mockRejectedValue(new Error("offline")),
      migrateLocalStorage: vi.fn(),
    };

    const result = await initializeJobhuntAuthority({ api, storage: localStorage });

    expect(result.mode).toBe("unavailable");
    expect(api.migrateLocalStorage).not.toHaveBeenCalled();
    expect(decideJobhuntAuthority({ marker: result.marker, apiAvailable: false })).toBe("unavailable");
  });

  it("keeps legacy mode before cutover when migration cannot reach the API", async () => {
    const api = {
      migrateLocalStorage: vi.fn().mockRejectedValue(new Error("offline")),
      health: vi.fn(),
    };
    const result = await initializeJobhuntAuthority({ api, storage: localStorage });
    expect(result.mode).toBe("legacy");
    expect(localStorage.getItem(JOBHUNT_AUTHORITY_STORAGE_KEY)).toBeNull();
  });
});
