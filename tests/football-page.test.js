import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

const snapshot = {
  ok: true, updatedAt: "2026-09-29T12:00:00",
  cache: [{ status: "fresh", ageSeconds: 30 }], stale: false,
  sourceErrors: [], fallback: { scores: false, fixtures: false },
  matches: [], clubs: [{ key: "liverpool", name: "Liverpool", followed: true, providerIds: {}, names: ["Liverpool"], crest: "", matchCount: 0 }],
  competitions: [{ key: "premier-league", name: "Premier League", followed: true, providers: [], matchCount: 0 }],
  following: { teams: ["liverpool"], competitions: ["premier-league"], standings: [], windowHours: 24 },
  providers: [], requests: [], runs: [], stored: { matches: 0, fixtures: 0 }, storedData: { matches: 0 },
  newsStatus: "No feed configured", storageNote: "Local cache", mappings: [], mappingConflicts: [],
};

beforeEach(() => {
  vi.resetModules();
  document.body.innerHTML = `<p id="football-freshness"></p><p id="football-notice" hidden></p>
    <nav><a data-tab="following"></a><a data-tab="overview"></a></nav><main id="football-content"></main>`;
  window.location.hash = "#following";
});
afterEach(() => vi.unstubAllGlobals());

describe("Football Dashboard", () => {
  it("preserves Kitchen hockey selection when football following is saved", async () => {
    let posted;
    vi.stubGlobal("fetch", vi.fn(async (url, options = {}) => {
      if (url === "/api/football") return { ok: true, json: async () => snapshot };
      if (url === "/api/football/settings") return { ok: true, json: async () => ({ ok: true, kitchenMaxSlides: 6, kitchenShowStandings: true, kitchenShowUpcoming: true }) };
      if (url === "/api/kitchen/settings" && options.method === "POST") {
        posted = JSON.parse(options.body);
        return { ok: true, json: async () => ({ ok: true }) };
      }
      if (url === "/api/kitchen/settings") return { ok: true, json: async () => ({
        ok: true, sports: { enabledTeamKeys: ["liverpool", "montreal-canadiens"],
          enabledLeagueKeys: ["premier-league", "nhl"], standingsLeagueKeys: [], windowHours: 24 },
      }) };
      throw new Error(`Unexpected request: ${url}`);
    }));

    await import("../js/football.js");
    await vi.waitFor(() => expect(document.getElementById("football-save-following")).toBeTruthy());
    document.querySelector('input[name="team"][value="liverpool"]').checked = false;
    document.querySelector('input[name="competition"][value="premier-league"]').checked = false;
    document.getElementById("football-save-following").click();
    await vi.waitFor(() => expect(posted).toBeTruthy());
    expect(posted.sports.enabledTeamKeys).toEqual(["montreal-canadiens"]);
    expect(posted.sports.enabledLeagueKeys).toEqual(["nhl"]);
  });
});
