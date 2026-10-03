import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createJobhuntCareerController,
  renderAssessmentList,
  renderAssessmentRun,
  renderCareerProfile,
} from "../js/jobhunt-career.js";

const emptyProfile = {
  revision: 0,
  fingerprint: "sha256:empty",
  currentRoleTitle: null,
  headline: null,
  professionalSummary: null,
  experience: [], education: [], certifications: [], languages: [],
  preferences: [], constraints: [], skills: [], evidence: [],
  skillLevelScale: { 0: "no experience", 3: "independent working ability", 5: "advanced" },
};

const instrument = {
  instrumentId: "test-instrument",
  instrumentVersion: "1.0.0",
  definitionHash: "sha256:test",
  title: "Test assessment",
  description: "A deterministic test instrument.",
  answerScale: {
    min: 1,
    max: 5,
    options: [1, 2, 3, 4, 5].map((value) => ({ value, label: String(value) })),
  },
  items: [{ id: "q1", order: 1, text: "Question one", dimension: "one", reverse: false }],
  dimensions: [{ id: "one", label: "Dimension one" }],
  source: { requiredNotices: ["Not a diagnosis."] },
  interpretationLimits: ["Descriptive only."],
};

function api(overrides = {}) {
  return {
    profile: vi.fn().mockResolvedValue({ profile: structuredClone(emptyProfile) }),
    assessments: vi.fn().mockResolvedValue({ instruments: [] }),
    updateProfile: vi.fn().mockResolvedValue({ profile: { ...emptyProfile, headline: "Updated", revision: 1 } }),
    createProfileRecord: vi.fn(),
    updateProfileRecord: vi.fn(),
    deleteProfileRecord: vi.fn(),
    startAssessment: vi.fn().mockResolvedValue({
      run: { id: "run-1", status: "draft", responses: {}, scores: [] }, instrument,
    }),
    assessmentRun: vi.fn(),
    saveAssessmentResponses: vi.fn().mockResolvedValue({
      run: { id: "run-1", status: "draft", responses: { q1: 4 }, scores: [] }, instrument,
    }),
    completeAssessment: vi.fn().mockResolvedValue({
      run: {
        id: "run-1", status: "completed", completedAt: "2026-09-18T12:00:00Z",
        responses: { q1: 4 }, scores: [{ label: "Dimension one", rawScore: 4, normalizedScore: 75 }],
      },
      instrument,
    }),
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("Job Hunt Career Profile and assessments UI", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="career"></div>`;
  });

  it("renders guided Profile sections and keeps version identity in History", () => {
    const html = renderCareerProfile(emptyProfile);
    expect(html).toContain("Career Profile sections");
    expect(html).toContain("Describe where you are now");
    expect(html).not.toContain("sha256:empty");
    const history = renderCareerProfile(emptyProfile, null, "history");
    expect(history).toContain("Revision 0");
    expect(history).toContain("sha256:empty");
  });

  it("opens focused collection editors, cancels, and validates guided fields", async () => {
    const client = api({
      createProfileRecord: vi.fn().mockResolvedValue({ profile: structuredClone(emptyProfile) }),
    });
    const onStatus = vi.fn();
    const root = document.getElementById("career");
    const controller = createJobhuntCareerController({ root, api: client, onStatus });
    await controller.refresh();
    root.querySelector('[data-profile-section="experience"]').click();
    expect(root.textContent).toContain("No experience added yet");
    root.querySelector('[data-profile-add="experience"]').click();
    expect(root.querySelector('[data-profile-form="experience"]')).toBeTruthy();
    root.querySelector('[data-profile-cancel="experience"]').click();
    expect(root.querySelector('[data-profile-form="experience"]')).toBeNull();

    root.querySelector('[data-profile-section="preferences"]').click();
    root.querySelector('[data-profile-add="preferences"]').click();
    const preference = root.querySelector('[data-profile-form="preferences"]');
    expect(preference.elements.guidedValue.tagName).toBe("SELECT");
    preference.elements.guidedKey.value = "location";
    preference.elements.guidedKey.dispatchEvent(new Event("change", { bubbles: true }));
    expect(root.querySelector('[data-profile-form="preferences"] [name="guidedValue"]').tagName).toBe("INPUT");
    preference.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(client.createProfileRecord).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith(expect.stringContaining("required fields"), "error");
  });

  it("renders unavailable instruments and assessment history explicitly", () => {
    const html = renderAssessmentList([
      {
        instrumentId: "pending", title: "Pending instrument", description: "Pending",
        available: false, status: "not_started", unavailableReason: "Verification pending",
        history: [], source: null,
      },
      {
        instrumentId: "ready", title: "Ready", description: "Ready", available: true,
        status: "completed", draftRunId: null, latestCompletedAt: "2026-09-18",
        history: [{ id: "run-old", status: "completed", completedAt: "2026-09-18", startedAt: "2026-09-18" }],
        source: { attribution: "Source" },
      },
    ]);
    expect(html).toContain("Unavailable — verification pending");
    expect(html).toContain("History (1)");
    expect(html).toContain("Retake");
  });

  it("loads and saves the Career Profile", async () => {
    const client = api();
    const root = document.getElementById("career");
    const controller = createJobhuntCareerController({ root, api: client });
    await controller.refresh();
    const form = root.querySelector("[data-profile-identity]");
    form.elements.headline.value = "Updated";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();
    expect(client.updateProfile).toHaveBeenCalledWith(expect.objectContaining({ headline: "Updated" }));
    root.querySelector('[data-profile-section="history"]').click();
    expect(root.textContent).toContain("Revision 1");
  });

  it("autosaves an answer and completes a run with results", async () => {
    const catalog = [{
      instrumentId: "test-instrument", title: "Test assessment", description: "Test",
      available: true, status: "not_started", draftRunId: null, latestCompletedAt: null,
      history: [], source: null,
    }];
    const client = api({ assessments: vi.fn().mockResolvedValue({ instruments: catalog }) });
    const root = document.getElementById("career");
    const controller = createJobhuntCareerController({ root, api: client });
    controller.state.tab = "assessments";
    await controller.refresh();
    root.querySelector('[data-assessment-action="start"]').click();
    await flush();
    const answer = root.querySelector('[data-assessment-answer="q1"][value="4"]');
    answer.checked = true;
    answer.dispatchEvent(new Event("change", { bubbles: true }));
    await flush();
    expect(client.saveAssessmentResponses).toHaveBeenCalledWith("run-1", { q1: 4 });
    root.querySelector('[data-assessment-action="complete"]').click();
    await flush();
    expect(client.completeAssessment).toHaveBeenCalledWith("run-1");
    expect(root.textContent).toContain("Dimension one");
    expect(root.textContent).toContain("75");
  });

  it("renders a durable draft with progress and previous/next navigation", () => {
    const expanded = {
      ...instrument,
      items: Array.from({ length: 6 }, (_, index) => ({
        id: `q${index + 1}`, order: index + 1, text: `Question ${index + 1}`,
        dimension: "one", reverse: false,
      })),
    };
    const html = renderAssessmentRun(
      { id: "run", status: "draft", responses: { q1: 3 }, scores: [] }, expanded, 0,
    );
    expect(html).toContain("1 of 6 answered");
    expect(html).toContain('data-assessment-action="next"');
    expect(html).toContain("Question 5");
    expect(html).not.toContain("Question 6");
  });

  it("shows an API error state", async () => {
    const root = document.getElementById("career");
    const controller = createJobhuntCareerController({
      root,
      api: api({ profile: vi.fn().mockRejectedValue(new Error("Profile unavailable")) }),
    });
    await controller.refresh();
    expect(root.textContent).toContain("Profile unavailable");
  });
});
