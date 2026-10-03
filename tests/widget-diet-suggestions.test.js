import { describe, expect, it } from "vitest";

import {
  buildCalorieTopUpSuggestions,
  buildMealSuggestions,
  normalizeMealDraft,
} from "../js/widget-diet.js";

describe("diet meal suggestions", () => {
  const days = [
    {
      day: "2026-05-11",
      meals: [
        { id: "1", name: "2 kostki czekolady", kcal: 98 },
        { id: "2", name: "Jajecznica: 3 jajka", kcal: 500 },
      ],
    },
    {
      day: "2026-05-10",
      meals: [
        { id: "3", name: "4 kostki czekolady", kcal: 196 },
        { id: "4", name: "Banan", kcal: 100 },
      ],
    },
    {
      day: "2026-05-08",
      meals: [
        { id: "5", name: "2 kostki czekolady", kcal: 98 },
        { id: "6", name: "Jajka sadzone 2 szt.", kcal: 260 },
      ],
    },
  ];

  it("returns matching old meals with their latest calories", () => {
    const suggestions = buildMealSuggestions("czek", days);

    expect(suggestions[0]).toMatchObject({
      name: "2 kostki czekolady",
      kcal: 98,
      count: 2,
      latestDay: "2026-05-11",
    });
    expect(suggestions.map((suggestion) => suggestion.name)).toContain("4 kostki czekolady");
  });

  it("matches without Polish diacritics", () => {
    expect(buildMealSuggestions("jajec", days)[0]).toMatchObject({
      name: "jajecznica: 3 jajka",
      kcal: 500,
    });
  });

  it("normalizes suggestion names to lowercase", () => {
    expect(buildMealSuggestions("ban", days)[0]).toMatchObject({
      name: "banan",
      kcal: 100,
    });
  });

  it("keeps spaces while lowercasing the live draft", () => {
    expect(normalizeMealDraft("Spaghetti ")).toBe("spaghetti ");
    expect(normalizeMealDraft("Banan + Skyr")).toBe("banan + skyr");
  });

  it("builds several top-up ideas from historical meals without exceeding remaining calories", () => {
    const suggestions = buildCalorieTopUpSuggestions(days, 600, { hour: 16, limit: 8 });

    expect(suggestions.length).toBeGreaterThan(3);
    expect(suggestions.every((suggestion) => suggestion.totalKcal <= 600)).toBe(true);
    expect(suggestions.filter((suggestion) => suggestion.mealCount === 1).length).toBeGreaterThanOrEqual(2);
    expect(suggestions.filter((suggestion) => suggestion.mealCount === 2).length).toBeGreaterThanOrEqual(2);
    expect(suggestions.some((suggestion) => suggestion.mealCount === 2)).toBe(true);
    expect(suggestions[0].meals[0]).toHaveProperty("name");
  });

  it("keeps late top-up ideas light and single-meal", () => {
    const suggestions = buildCalorieTopUpSuggestions(days, 1200, { hour: 22, limit: 6 });

    expect(suggestions.length).toBeGreaterThan(0);
    expect(suggestions.every((suggestion) => suggestion.mealCount === 1)).toBe(true);
    expect(suggestions.every((suggestion) => suggestion.totalKcal <= 650)).toBe(true);
  });
});
