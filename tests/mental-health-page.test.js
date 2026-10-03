import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";

const html = readFileSync("mental-health.html", "utf8");
const body = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i)[1].replace(/<script[\s\S]*?<\/script>/gi, "");

const instrument = {
  id: "phq9", name: "Patient Health Questionnaire-9", shortName: "PHQ-9",
  category: "depression", description: "Depressive symptom screening.", constructType: "state",
  questionnaireMode: "external-score", questionTextStatus: "missing", defaultCadenceDays: 14,
  minimumRetestDays: 7, recallPeriod: "past 2 weeks", estimatedMinutes: 3, itemCount: 9,
  language: "en", version: "1.0", scoringVersion: "1.0", source: "PHQ Screeners",
  licenseStatus: "unrestricted", licenseNotice: "", scoreMin: 0, scoreMax: 27,
  higherIsBetter: false, requiresTotalScore: true, subscales: [], responseOptions: [], questions: [],
  interpretationBands: [], custom: false, disclaimer: "Screening is not diagnosis.",
};

function payload() {
  return {
    schemaVersion: 1, registry: [instrument],
    schedules: [{ instrumentId: "phq9", enabled: true, paused: false, baselineOnly: false, defaultCadenceDays: 14, userCadenceDays: null, status: "not_started", nextDueAt: "2026-09-24T10:00:00Z", lastCompletedAt: null }],
    latest: [], assessments: [], checkins: [], events: [], drafts: {}, dueCount: 1, lastCheckin: null,
    nextScheduled: { instrumentId: "phq9", nextDueAt: "2026-09-24T10:00:00Z" },
    analytics90: { assessmentCount: 0, instruments: [], mostStableDimension: null, largestNumericChange: null, correlations: [], correlationNotice: "Need more observations." },
    settings: { checkin_fields: { mood: true, anxiety: true } },
  };
}

describe("Mental Health page", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = body;
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => payload() });
    global.confirm = vi.fn(() => true);
    global.prompt = vi.fn(() => "");
    history.replaceState(null, "", "/mental-health.html");
  });

  it("renders due battery, registry and clean empty states", async () => {
    await import("../js/mental-health-page.js?test=page");
    await Promise.resolve(); await Promise.resolve();

    expect(document.getElementById("mh-due-badge").textContent).toBe("1");
    expect(document.getElementById("mh-due-list").textContent).toContain("Patient Health Questionnaire-9");
    expect(document.getElementById("mh-library").textContent).toContain("Wynik zewnętrzny");
    expect(document.getElementById("mh-library-filter").textContent).toContain("Do wypełnienia");
    expect(document.getElementById("mh-library-filter").textContent).toContain("Wynik zewnętrzny");
    expect(document.getElementById("mh-score-grid").textContent).toContain("Pierwsze wyniki");
  });

  it("switches between the full-page sections", async () => {
    await import("../js/mental-health-page.js?test=tabs");
    await Promise.resolve(); await Promise.resolve();
    document.querySelector('[data-tab="settings"]').click();
    expect(document.querySelector('[data-panel="settings"]').classList.contains("is-active")).toBe(true);
  });

  it("resumes a native draft with exact registered options and progress", async () => {
    const native = {
      ...instrument, questionnaireMode: "native", questionTextStatus: "official_translation",
      questionCount: 2, scoredItemCount: 2, language: "pl-PL", instructions: "Instrukcja oficjalna",
      questions: [{ id: "1", text: "Pierwsza pozycja", required: true }, { id: "2", text: "Druga pozycja", required: true }],
      responseOptions: [{ value: 0, label: "Wcale nie" }, { value: 1, label: "Kilka dni" }],
      languagePacks: [{ language: "pl-PL", scoringVersion: "fixture-v1" }],
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      ...payload(), registry: [native], drafts: { phq9: { instrumentId: "phq9", updatedAt: "2026-09-24T10:00:00Z", payload: { responses: { "1": 1 }, notes: "wróć" } } },
    }) });
    await import("../js/mental-health-page.js?test=native-draft");
    await Promise.resolve(); await Promise.resolve();
    document.querySelector('[data-action="start"][data-id="phq9"]').click();
    expect(document.getElementById("mh-assessment-content").textContent).toContain("Pierwsza pozycja");
    expect(document.getElementById("mh-assessment-content").textContent).toContain("Wcale nie");
    expect(document.querySelector('[name="response-1"]').value).toBe("1");
    expect(document.querySelector("[data-assessment-progress]").textContent).toBe("1/2");
  });
});
