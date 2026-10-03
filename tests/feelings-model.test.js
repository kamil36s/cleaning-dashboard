import { describe, expect, it } from "vitest";
import { emotionMeterItems, filterCheckins, groupCheckins, searchEmotions } from "../js/feelings-model.js";

const emotions = [
  { id: "calm", name: "Calm", description: "free of worry", quadrant: "low_pleasant" },
  { id: "anxious", name: "Anxious", description: "uneasy about what may happen", quadrant: "high_unpleasant" },
];

describe("feelings model", () => {
  it("searches emotion names and definitions with a color filter", () => {
    expect(searchEmotions(emotions, "worry").map((item) => item.name)).toEqual(["Calm"]);
    expect(searchEmotions(emotions, "", ["high_unpleasant"]).map((item) => item.name)).toEqual(["Anxious"]);
  });

  it("filters history by date, emotion, tag, and text", () => {
    const checkins = [{
      id: "one", occurredAt: "2026-09-23T10:00", emotion: emotions[0],
      tags: [{ id: "home", name: "Home" }], note: "Quiet morning",
    }, {
      id: "two", occurredAt: "2026-08-01T10:00", emotion: emotions[1],
      tags: [{ id: "work", name: "Work" }], note: "Deadline",
    }];
    expect(filterCheckins(checkins, { from: "2026-09-01", q: "morning", tag: "Home", emotion: "Calm" }).map((item) => item.id)).toEqual(["one"]);
  });

  it("groups recent history into Today and Yesterday", () => {
    const checkins = [
      { occurredAt: "2026-09-23T10:00" },
      { occurredAt: "2026-09-22T11:00" },
    ];
    expect(groupCheckins(checkins, new Date("2026-09-23T12:00:00")).map((group) => group.label)).toEqual(["Today", "Yesterday"]);
  });

  it("uses canonical two-dimensional meter coordinates and excludes dictionary-only emotions", () => {
    const meter = emotionMeterItems([
      { name: "Serene", meter: true, x: 11, y: 11 },
      { name: "Concerned", x: 4, y: 4 },
      { name: "Dictionary only", meter: false, x: 0, y: 0 },
      { name: "Enraged", meter: true, x: 0, y: 0 },
    ]);
    expect(meter.map((item) => item.name)).toEqual(["Enraged", "Concerned", "Serene"]);
  });
});
