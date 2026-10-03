import { describe, expect, it } from "vitest";
import { lastFmAlbumKey } from "../js/lastfm-stats.js";

describe("Last.fm album matching", () => {
  it("normalizes Polish letters, punctuation and edition suffixes", () => {
    expect(lastFmAlbumKey("Mgła", "Exercises in Futility (2024 Remastered)"))
      .toBe(lastFmAlbumKey("Mgla", "Exercises in Futility — Deluxe"));
  });

  it("keeps the artist in the identity", () => {
    expect(lastFmAlbumKey("Artist one", "Black Album"))
      .not.toBe(lastFmAlbumKey("Artist two", "Black Album"));
  });

  it("keeps Unicode and symbol-only artist identities distinct", () => {
    expect(lastFmAlbumKey("Океан Ельзи", "Альбом"))
      .not.toBe(lastFmAlbumKey("Путь", "Альбом"));
    expect(lastFmAlbumKey("!!!", "★"))
      .not.toBe(lastFmAlbumKey("†††", "•"));
  });
});
