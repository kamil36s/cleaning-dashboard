import { describe, expect, it } from "vitest";
import {
  chapterEndTime, chapterIdAtTime, estimateQueueRemainingSeconds, formatQueueEstimate,
  formatRemaining, playbackRemainingTimes, realTimeRemaining,
} from "../js/synchrobook/utils.js";

describe("Synchrobook chapter time remaining", () => {
  const alignment = { chapters: [
    { id: "one", sentences: [{ start: 10, end: 40 }] },
    { id: "two", sentences: [{ start: null, end: null }, { start: 50, end: 100 }] },
  ] };

  it("uses the next chapter boundary and adjusts wall time for playback speed", () => {
    expect(chapterEndTime(alignment, "one")).toBe(50);
    expect(realTimeRemaining(20, 50, 1.5)).toBe(20);
    expect(formatRemaining(20)).toBe("0:20");
  });

  it("uses the final aligned sentence for the last chapter", () => {
    expect(chapterEndTime(alignment, "two")).toBe(100);
    expect(formatRemaining(realTimeRemaining(40, 100, 2))).toBe("0:30");
  });

  it("derives the chapter from the audio clock after jumping across a boundary", () => {
    expect(chapterIdAtTime(alignment, 49, "one")).toBe("one");
    expect(chapterIdAtTime(alignment, 50, "one")).toBe("two");
    expect(playbackRemainingTimes({
      alignment, currentTime: 60, duration: 180, playbackRate: 1.5, fallbackChapterId: "one",
    })).toEqual({ chapterId: "two", chapter: 80, book: 80 });
  });

  it("recalculates both clocks from the live playback rate", () => {
    const fast = playbackRemainingTimes({
      alignment, currentTime: 20, duration: 200, playbackRate: 2, fallbackChapterId: "one",
    });
    const normal = playbackRemainingTimes({
      alignment, currentTime: 20, duration: 200, playbackRate: 1, fallbackChapterId: "one",
    });
    expect(fast.chapter).toBe(15);
    expect(fast.book).toBe(90);
    expect(normal.chapter).toBe(30);
    expect(normal.book).toBe(180);
  });
});

describe("Synchrobook processing queue estimate", () => {
  const now = Date.parse("2026-09-05T12:10:00Z");

  it("combines live progress with queued jobs", () => {
    const jobs = [
      { kind: "import", status: "TRANSCRIBING", progress: 50, createdAt: "2026-09-05T12:00:00Z" },
      { kind: "import", status: "QUEUED", progress: 0, createdAt: "2026-09-05T12:05:00Z" },
    ];
    expect(estimateQueueRemainingSeconds(jobs, now)).toBe(1800);
    expect(formatQueueEstimate(1800)).toBe("Pozostało: około 30 min");
  });

  it("uses completed jobs when queued work has no live progress", () => {
    const jobs = [
      { kind: "import", status: "READY", createdAt: "2026-09-05T10:00:00Z", updatedAt: "2026-09-05T10:20:00Z" },
      { kind: "import", status: "QUEUED", progress: 0, createdAt: "2026-09-05T12:09:00Z" },
    ];
    expect(estimateQueueRemainingSeconds(jobs, now)).toBe(1200);
  });

  it("does not count time spent waiting behind an earlier completed job", () => {
    const jobs = [
      { kind: "import", status: "READY", createdAt: "2026-09-05T10:00:00Z", updatedAt: "2026-09-05T10:20:00Z" },
      { kind: "import", status: "READY", createdAt: "2026-09-05T10:00:00Z", updatedAt: "2026-09-05T10:40:00Z" },
      { kind: "import", status: "TRANSCRIBING", progress: 50, createdAt: "2026-09-05T10:00:00Z" },
      { kind: "import", status: "QUEUED", progress: 0, createdAt: "2026-09-05T10:00:00Z" },
    ];
    expect(estimateQueueRemainingSeconds(jobs, Date.parse("2026-09-05T10:50:00Z"))).toBe(1800);
  });

  it("waits for usable progress or history before showing a duration", () => {
    expect(estimateQueueRemainingSeconds([
      { kind: "import", status: "QUEUED", progress: 0, createdAt: "2026-09-05T12:09:00Z" },
    ], now)).toBeNull();
    expect(formatQueueEstimate(null)).toBe("Pozostało: obliczanie…");
  });
});
