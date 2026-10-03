import { describe, expect, it } from "vitest";

import {
  normalizeDailyAchievement,
  setDailyAchievement,
} from "../js/daily-achievements.js";

describe("daily achievements", () => {
  it("normalizes unknown states to a non-actionable loading state", () => {
    expect(normalizeDailyAchievement({ state: "mystery", value: 3 })).toEqual({
      state: "loading",
      value: "3",
      detail: "Sprawdzam dane",
      coverUrl: "",
      eligible: false,
      progress: null,
    });
  });

  it("clamps and floors measurable progress", () => {
    expect(normalizeDailyAchievement({ state: "pending", progress: 34.9 }).progress).toBe(34);
    expect(normalizeDailyAchievement({ state: "pending", progress: 99.9 }).progress).toBe(99);
    expect(normalizeDailyAchievement({ state: "complete", progress: 140 }).progress).toBe(100);
  });

  it("renders percentage progress until the achievement is complete", () => {
    document.body.innerHTML = `
      <div id="daily-achievements-rail">
        <article data-daily-achievement="reading" data-label="Czytanie">
          <strong data-daily-achievement-value></strong>
          <span class="daily-achievement-mark">•</span>
        </article>
      </div>`;

    setDailyAchievement("reading", {
      state: "pending",
      value: "13/38 str.",
      detail: "25 str. zostało",
      progress: 34,
    });

    const item = document.querySelector('[data-daily-achievement="reading"]');
    expect(item.dataset.progress).toBe("34");
    expect(item.style.getPropertyValue("--achievement-progress")).toBe("122.4deg");
    expect(item.querySelector(".daily-achievement-mark").textContent).toBe("34%");

    setDailyAchievement("reading", {
      state: "complete",
      value: "Gotowe",
      detail: "Dzisiejsze strony przeczytane",
      progress: 100,
    });

    expect(item.dataset.state).toBe("complete");
    expect(item.querySelector(".daily-achievement-mark").textContent).toBe("");
  });

  it("renders album title and artist with the saved star rating", () => {
    document.body.innerHTML = `
      <div id="daily-achievements-rail">
        <article data-daily-achievement="album" data-label="Album dnia">
          <img class="daily-achievement-album-art" alt="" hidden>
          <strong data-daily-achievement-value></strong>
          <span data-daily-achievement-detail></span>
        </article>
      </div>`;

    setDailyAchievement("album", {
      state: "complete",
      value: "Album title",
      detail: "Artist · ★ 4.5",
      coverUrl: "./covers/album.jpg",
    });

    expect(document.querySelector("[data-daily-achievement-value]").textContent).toBe("Album title");
    expect(document.querySelector("[data-daily-achievement-detail]").textContent).toBe("Artist · ★ 4.5");
    expect(document.querySelector('[data-daily-achievement="album"]').dataset.state).toBe("complete");
    const artwork = document.querySelector('.daily-achievement-album-art');
    expect(artwork.getAttribute('src')).toBe('./covers/album.jpg');
    artwork.dispatchEvent(new Event('load'));
    expect(artwork.hidden).toBe(false);
    setDailyAchievement('album', { state: 'neutral', value: 'Brak albumu' });
    expect(artwork.hidden).toBe(true);
    expect(artwork.hasAttribute('src')).toBe(false);
  });
});
