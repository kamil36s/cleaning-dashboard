import { describe, expect, it, vi } from "vitest";
import { createAssessment, fetchMentalHealthOverview, saveAssessmentDraft, updateAssessmentSchedule } from "../js/mental-health-api.js";

describe("Mental Health API client", () => {
  it("loads the private overview without caching", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ dueCount: 2 }) });
    await expect(fetchMentalHealthOverview(fetchImpl)).resolves.toEqual({ dueCount: 2 });
    expect(fetchImpl).toHaveBeenCalledWith("/api/mental-health/overview", { cache: "no-store" });
  });

  it("posts versionable assessment payloads as JSON", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "a1" }) });
    const payload = { instrumentId: "phq9", totalScore: 8 };
    await createAssessment(payload, fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith("/api/mental-health/assessments", expect.objectContaining({ method: "POST", body: JSON.stringify(payload), headers: { "Content-Type": "application/json" } }));
  });

  it("keeps schedule updates instrument-scoped", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "due_soon" }) });
    await updateAssessmentSchedule("who5", { userCadenceDays: 21 }, fetchImpl);
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/mental-health/schedules/who5");
  });

  it("stores incomplete native drafts per instrument", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    const draft = { responses: { "1": 2 }, notes: "later" };
    await saveAssessmentDraft("phq9", draft, fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith("/api/mental-health/drafts/phq9", expect.objectContaining({ method: "POST", body: JSON.stringify(draft) }));
  });
});
