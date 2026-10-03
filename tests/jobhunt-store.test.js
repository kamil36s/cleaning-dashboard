import { beforeEach, describe, expect, it } from "vitest";
import {
  JOBHUNT_OFFERS_STORAGE_KEY,
  formatExpirationLabel,
  getDaysUntilExpiration,
  getExpirationTone,
  getJobhuntSummary,
  getNextBestAction,
  getSkillGapSummary,
  loadJobOffers,
  markJobOfferAsApplied,
  saveJobOffers,
  validateJobOfferPayload,
} from "../js/jobhunt-store.js";

const baseOffer = {
  id: "job_20260705_hsbc_qa_analyst",
  company: "HSBC",
  role: "QA Analyst",
  seniority: "mid",
  location: {
    city: "Krakow",
    country: "Poland",
    workMode: "hybrid",
  },
  contract: {
    type: "UoP",
  },
  salary: {
    min: 12000,
    max: 16000,
    currency: "PLN",
    period: "month",
    taxType: "gross",
    isKnown: true,
  },
  source: {
    name: "Pracuj.pl",
    url: "https://example.com/job",
    capturedAt: "2026-07-05T11:45:00+02:00",
  },
  status: "to_review",
  priority: "P1",
  nextAction: "tailor_cv",
  match: {
    score: 82,
    summary: "Strong match for QA Analyst / UAT profile.",
    isExperimental: true,
  },
  requirements: {
    mustHave: ["manual testing"],
    niceToHave: ["API testing"],
    tools: ["Jira"],
  },
  analysis: {
    greenFlags: ["UAT"],
    redFlags: ["API testing gap"],
    skillGaps: ["Postman", "REST API"],
    fitReasons: ["Strong overlap with UAT coordination"],
  },
  cv: {
    recommendedVersion: "QA Analyst / UAT",
    bulletsToEmphasize: ["Coordinated IAT/UAT testing."],
  },
  application: {
    dateApplied: null,
    followUpDate: null,
    recruiterName: null,
    recruiterContact: null,
  },
  notes: "",
  originalText: "Full copied job offer text here.",
  createdAt: "2026-07-05T11:45:00+02:00",
  updatedAt: "2026-07-05T11:45:00+02:00",
};

describe("jobhunt store", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("validates and normalizes a standardized imported offer", () => {
    const result = validateJobOfferPayload(JSON.stringify(baseOffer), []);

    expect(result.ok).toBe(true);
    expect(result.offers).toHaveLength(1);
    expect(result.offers[0].company).toBe("HSBC");
    expect(result.offers[0].match.score).toBe(82);
    expect(result.offers[0].match.category).toBe("strong_fit");
  });

  it("rejects invalid required fields and out-of-range scores", () => {
    const result = validateJobOfferPayload({
      ...baseOffer,
      source: { url: "" },
      match: { score: 120 },
      status: "maybe",
    });

    expect(result.ok).toBe(false);
    expect(result.errors.join(" ")).toContain("source.url");
    expect(result.errors.join(" ")).toContain("between 0 and 100");
    expect(result.errors.join(" ")).toContain("not supported");
  });

  it("warns about possible duplicates while keeping import allowed", () => {
    const result = validateJobOfferPayload(baseOffer, [baseOffer]);

    expect(result.ok).toBe(true);
    expect(result.duplicates).toHaveLength(1);
    expect(result.warnings.join(" ")).toContain("Possible duplicate");
  });

  it("persists offers in localStorage", () => {
    saveJobOffers([baseOffer]);

    expect(localStorage.getItem(JOBHUNT_OFFERS_STORAGE_KEY)).toContain("HSBC");
    expect(loadJobOffers()).toHaveLength(1);
  });

  it("preserves manually uploaded company logos", () => {
    const logoDataUrl = "data:image/png;base64,aGVsbG8=";
    const result = validateJobOfferPayload({
      ...baseOffer,
      branding: { logoDataUrl },
    });

    expect(result.offers[0].branding.logoDataUrl).toBe(logoDataUrl);

    saveJobOffers(result.offers);
    expect(loadJobOffers()[0].branding.logoDataUrl).toBe(logoDataUrl);
  });

  it("tracks expiration dates and reports days left", () => {
    const result = validateJobOfferPayload({
      ...baseOffer,
      expiresAt: "2026-07-12",
    }, [], { now: new Date("2026-07-05T12:00:00") });

    expect(result.ok).toBe(true);
    expect(result.offers[0].expiresAt).toBe("2026-07-12");
    expect(getDaysUntilExpiration(result.offers[0], new Date("2026-07-05T12:00:00"))).toBe(7);
    expect(formatExpirationLabel(result.offers[0], new Date("2026-07-05T12:00:00"))).toBe("7d left");
    expect(getExpirationTone(result.offers[0], new Date("2026-07-05T12:00:00"))).toBe("soon");
  });

  it("automatically expires active offers after the expiration date", () => {
    const result = validateJobOfferPayload({
      ...baseOffer,
      expiresAt: "2026-07-04",
      status: "worth_applying",
    }, [], { now: new Date("2026-07-05T12:00:00") });

    expect(result.ok).toBe(true);
    expect(result.offers[0].status).toBe("expired");
    expect(formatExpirationLabel(result.offers[0], new Date("2026-07-05T12:00:00"))).toBe("Expired 1d ago");
  });

  it("does not overwrite terminal statuses when an offer is expired", () => {
    ["rejected", "archived", "offer"].forEach((status) => {
      const result = validateJobOfferPayload({
        ...baseOffer,
        id: `job_${status}`,
        status,
        expiresAt: "2026-07-04",
      }, [], { now: new Date("2026-07-05T12:00:00") });

      expect(result.offers[0].status).toBe(status);
    });
  });

  it("labels manually expired offers even without an expiration date", () => {
    const offer = validateJobOfferPayload({
      ...baseOffer,
      status: "expired",
    }).offers[0];

    expect(formatExpirationLabel(offer, new Date("2026-07-05T12:00:00"))).toBe("Expired");
    expect(getExpirationTone(offer, new Date("2026-07-05T12:00:00"))).toBe("expired");
  });

  it("computes stats, best match, next action, and skill gaps", () => {
    const offers = [
      baseOffer,
      {
        ...baseOffer,
        id: "job_motorola",
        company: "Motorola Solutions",
        role: "QA Tester",
        priority: "P2",
        status: "applied",
        match: { score: 74 },
        analysis: { skillGaps: ["Postman", "SQL"] },
        application: {
          dateApplied: "2026-07-03",
          followUpDate: "2026-07-04",
        },
      },
    ].map((offer) => validateJobOfferPayload(offer).offers[0]);

    const summary = getJobhuntSummary(offers, new Date("2026-07-05T12:00:00"));
    expect(summary.total).toBe(2);
    expect(summary.worthApplying).toBe(2);
    expect(summary.appliedThisWeek).toBe(1);
    expect(summary.followUpsDue).toBe(1);
    expect(summary.expired).toBe(0);
    expect(summary.bestMatch.company).toBe("HSBC");
    expect(getNextBestAction(offers, new Date("2026-07-05T12:00:00")).type).toBe("follow_up");
    expect(getSkillGapSummary(offers)[0]).toMatchObject({ skill: "Postman", count: 2 });
  });

  it("keeps expired offers out of active recommendations", () => {
    const offers = [
      {
        ...baseOffer,
        id: "job_expired",
        expiresAt: "2026-07-04",
        priority: "P1",
        match: { score: 98 },
      },
      {
        ...baseOffer,
        id: "job_active",
        company: "Sii",
        expiresAt: "2026-07-12",
        priority: "P1",
        match: { score: 74 },
      },
    ].map((offer) => validateJobOfferPayload(offer, [], { now: new Date("2026-07-05T12:00:00") }).offers[0]);

    const summary = getJobhuntSummary(offers, new Date("2026-07-05T12:00:00"));
    expect(summary.expired).toBe(1);
    expect(summary.expiringSoon).toBe(1);
    expect(summary.bestMatch.company).toBe("Sii");
    expect(getNextBestAction(offers, new Date("2026-07-05T12:00:00")).offerId).toBe("job_active");
  });

  it("marks an offer as applied and creates a seven-day follow-up", () => {
    const offers = saveJobOffers([baseOffer]);
    const updated = markJobOfferAsApplied(baseOffer.id, offers, {
      now: new Date("2026-07-05T12:00:00"),
    });

    expect(updated[0].status).toBe("applied");
    expect(updated[0].application.dateApplied).toBe("2026-07-05");
    expect(updated[0].application.followUpDate).toBe("2026-07-12");
    expect(updated[0].nextAction).toBe("follow_up");
  });
});
