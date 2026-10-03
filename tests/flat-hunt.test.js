import { describe, expect, it } from "vitest";
import {
  buildCallScript,
  buildSearchPresets,
  createDefaultFlatHuntPreferences,
  scoreFlatListing,
} from "../js/flat-hunt.js";

describe("Flat hunt preference scoring", () => {
  it("gives a high score when an offer satisfies active must-have and important rules", () => {
    const preferences = createDefaultFlatHuntPreferences();
    const result = scoreFlatListing({
      totalPrice: 2320,
      totalArea: 38,
      mainRoomArea: 25,
      windowsCount: 3,
      location: "near-center",
      buildingType: "kamienica",
      floor: "first-plus",
      light: "bright",
      condition: "good",
      deskAndBed: "yes",
      kitchen: "yes",
      bathroom: "yes",
      internetReady: "yes",
      washingMachine: "yes",
    }, preferences);

    expect(result.score).toBeGreaterThanOrEqual(80);
    expect(["Bierz ogledziny", "Dzwon teraz"]).toContain(result.verdict);
    expect(result.blockers).toHaveLength(0);
  });

  it("turns failed must-have criteria into blockers", () => {
    const preferences = createDefaultFlatHuntPreferences();
    const result = scoreFlatListing({
      totalPrice: 2700,
      totalArea: 34,
      mainRoomArea: 20,
      deskAndBed: "no",
      kitchen: "yes",
      bathroom: "yes",
    }, preferences);

    expect(result.verdict).toBe("Raczej nie");
    expect(result.blockers.join(" ")).toContain("Max all-in");
    expect(result.blockers.join(" ")).toContain("Min główny pokój");
    expect(result.blockers.join(" ")).toContain("Biurko i łóżko");
  });

  it("lets ignored criteria disappear from the score", () => {
    const preferences = createDefaultFlatHuntPreferences();
    preferences.balcony.importance = "ignore";
    preferences.elevator.importance = "ignore";
    preferences.quiet.importance = "ignore";

    const result = scoreFlatListing({
      totalPrice: 2400,
      totalArea: 36,
      mainRoomArea: 24,
      windowsCount: 2,
      location: "near-center",
      buildingType: "kamienica",
      floor: "first-plus",
      light: "bright",
      deskAndBed: "yes",
      kitchen: "yes",
      bathroom: "yes",
    }, preferences);

    expect(result.details.some((detail) => detail.label === "Balkon")).toBe(false);
    expect(result.details.some((detail) => detail.label === "Winda")).toBe(false);
  });
});

describe("Flat hunt helpers", () => {
  it("builds search presets from active criteria", () => {
    const preferences = createDefaultFlatHuntPreferences();
    const presets = buildSearchPresets(preferences);

    expect(presets[0].query).toContain("Kraków");
    expect(presets[0].query).toContain("2500");
    expect(presets[0].query).toContain("kamienica");
  });

  it("injects active preference questions into the call script", () => {
    const preferences = createDefaultFlatHuntPreferences();
    preferences.quiet.importance = "important";
    const sections = buildCallScript(preferences);
    const joined = sections.flatMap((section) => section.items).join(" ");

    expect(joined).toContain("2500");
    expect(joined).toContain("co najmniej 35");
    expect(joined).toContain("ciche");
  });
});
