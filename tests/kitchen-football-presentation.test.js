import { describe, expect, it } from "vitest";
import { selectKitchenFootballSlides } from "../js/kitchen-football-presentation.js";

describe("Kitchen football presentation", () => {
  it("puts followed-team matches first and caps the glance carousel", () => {
    const slides = [
      { type: "results", id: 1 }, { type: "standings", id: 2 },
      { type: "match", id: 3 }, { type: "next", id: 4 }, { type: "results", id: 5 },
    ];
    expect(selectKitchenFootballSlides(slides, { kitchenMaxSlides: 3 }).map(item => item.id)).toEqual([3, 4, 1]);
    expect(selectKitchenFootballSlides(slides, { kitchenShowUpcoming: false, kitchenShowStandings: false }).map(item => item.id)).toEqual([3, 1, 5]);
  });
});
