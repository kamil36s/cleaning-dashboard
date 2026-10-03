import { describe, expect, it } from "vitest";
import {
  activityToCsv,
  activityEventTextBlocks,
  activityGranularityForRange,
  activityPeriodAverageWeight,
  activityPeriodSummary,
  aggregateActivityDays,
  buildTextReport,
  dayTooltip,
  filterActivityForReport,
  formatActivityDate,
  normalizeActivitySettings,
  timelineItemsInRange,
} from "../js/timeline-activity-model.js";

const activity = {
  from: "2026-07-20",
  to: "2026-07-22",
  days: [{
    date: "2026-07-22",
    events: [
      { source: "journal", kind: "journal_entry", title: "Today", summary: "Preview", details: "Full journal body", occurredAt: "2026-07-22T12:00:00", private: true, metrics: {} },
      { source: "cleaning", kind: "cleaning_action", title: "Kitchen", summary: "Home", details: "", occurredAt: "2026-07-22T13:00:00", private: false, metrics: {} },
    ],
  }],
};

describe("timeline activity model", () => {
  it("uses full journal content and keeps culture optional by default", () => {
    const settings = normalizeActivitySettings();
    expect(settings.journalContent).toBe("full");
    expect(settings.sources.journal.report).toBe(true);
    expect(settings.sources.emotions.report).toBe(true);
    expect(settings.sources.lastfm.timeline).toBe(true);
    expect(settings.sources.lastfm.report).toBe(false);
    expect(settings.sources.culture.timeline).toBe(false);
    expect(settings.sources.poems.timeline).toBe(true);
    expect(settings.sources.poems.report).toBe(false);
  });

  it("formats dates as DD/MM/YYYY", () => {
    expect(formatActivityDate("2026-07-22")).toBe("22/07/2026");
  });

  it("does not repeat the journal preview before its full content", () => {
    expect(activityEventTextBlocks(activity.days[0].events[0])).toEqual(["Full journal body"]);
    expect(activityEventTextBlocks({ source: "journal", summary: "Preview", details: "" })).toEqual(["Preview"]);
    expect(activityEventTextBlocks({ source: "poems", summary: "Preview", details: "Full poem" })).toEqual(["Full poem"]);
    expect(activityEventTextBlocks({ source: "reading", summary: "1 book", details: "Book: 12 pages" }))
      .toEqual(["1 book", "Book: 12 pages"]);
  });

  it("switches daily signals through week, month and year buckets when zooming out", () => {
    expect(activityGranularityForRange(30)).toBe("day");
    expect(activityGranularityForRange(90)).toBe("week");
    expect(activityGranularityForRange(365)).toBe("month");
    expect(activityGranularityForRange(730)).toBe("month");
    expect(activityGranularityForRange(731)).toBe("year");
    expect(activityGranularityForRange(14, 1200)).toBe("day");
    expect(activityGranularityForRange(90, 1200)).toBe("week");
    expect(activityGranularityForRange(180, 1200)).toBe("month");
    expect(activityGranularityForRange(366, 900)).toBe("month");
    expect(activityGranularityForRange(550, 1200)).toBe("year");
    const buckets = aggregateActivityDays([
      { date: "2026-07-20", total: 1, sourceCounts: { emotions: 1 }, events: [{ source: "emotions" }] },
      { date: "2026-07-22", total: 2, sourceCounts: { reading: 1, cleaning: 1 }, events: [{ source: "reading" }, { source: "cleaning" }] },
    ], "week");
    expect(buckets).toHaveLength(1);
    expect(buckets[0].total).toBe(3);
    expect(buckets[0].start).toBe("2026-07-20");
    expect(buckets[0].end).toBe("2026-07-26");
    const month = aggregateActivityDays([
      { date: "2026-07-22", total: 1, sourceCounts: { emotions: 1 }, events: [{ source: "emotions" }] },
    ], "month")[0];
    expect(month.label).toBe("lipiec 2026");
    const year = aggregateActivityDays([
      { date: "2026-07-22", total: 1, sourceCounts: { lastfm: 1 }, events: [{ source: "lastfm" }] },
    ], "year")[0];
    expect(year.label).toBe("2026");
  });

  it("summarizes useful daily metrics in the hover tooltip", () => {
    const tooltip = dayTooltip({
      date: "2026-07-22",
      total: 4,
      sourceCounts: { cleaning: 2, reading: 1, emotions: 1 },
      events: [
        { source: "cleaning", metrics: {} },
        { source: "cleaning", metrics: {} },
        { source: "reading", metrics: { pages: 42 } },
        { source: "emotions", metrics: { mood: "calm" } },
      ],
    });
    expect(tooltip).toContain("Cleaning: 2 action(s)");
    expect(tooltip).toContain("Reading: 42 pages");
    expect(tooltip).toContain("Emotions: 1 check-in(s) · calm");
  });

  it("builds date-free pill labels with source emoji and requested metrics", () => {
    const period = {
      label: "lipiec 2026",
      events: [
        { source: "journal", metrics: {} },
        { source: "poems", metrics: {} },
        { source: "cleaning", metrics: {} },
        { source: "cleaning", metrics: {} },
        { source: "reading", metrics: { pages: 42 } },
        { source: "habits", metrics: {} },
        { source: "todos", metrics: {} },
        { source: "selfCare", metrics: {} },
        { source: "emotions", metrics: { mood: "calm" } },
        { source: "culture", metrics: {} },
      ],
    };
    expect(activityPeriodSummary(period, "journal").primary).toBe("📓 1 entry");
    expect(activityPeriodSummary(period, "poems").primary).toBe("✒ 1 poem");
    expect(activityPeriodSummary(period, "cleaning").primary).toBe("🧹 2 actions");
    expect(activityPeriodSummary(period, "reading").primary).toBe("📚 42 pages");
    expect(activityPeriodSummary(period, "habits").primary).toBe("✅ 1 entry");
    expect(activityPeriodSummary(period, "todos").primary).toBe("☑️ 1 completed");
    expect(activityPeriodSummary(period, "selfCare").primary).toBe("🧘 1 record");
    expect(activityPeriodSummary(period, "emotions").primary).toBe("💭 1 check-in");
    expect(activityPeriodSummary(period, "culture").primary).toBe("🎭 1 event");
    expect(activityPeriodSummary(period, "cleaning").primary).not.toContain("lipiec 2026");
  });

  it("shows weighted average weight and its direction versus the previous period", () => {
    const current = { events: [
      { source: "health", metrics: { steps: 12_000 } },
      { source: "health", metrics: { averageKg: 79, measurements: 1 } },
      { source: "health", metrics: { averageKg: 78, measurements: 3 } },
    ] };
    const previous = { events: [{ source: "health", metrics: { averageKg: 80, measurements: 2 } }] };
    expect(activityPeriodAverageWeight(current)).toBe(78.25);
    expect(activityPeriodSummary(current, "health", previous)).toMatchObject({
      primary: "👟 12 tys. steps",
      secondary: "⚖️ 78,3 kg",
      trend: "↓",
      trendTone: "drop",
    });
  });

  it("filters report sources and includes full event details", () => {
    const settings = normalizeActivitySettings({ sources: { cleaning: { report: false } } });
    const filtered = filterActivityForReport(activity, settings);
    const report = buildTextReport(filtered, []);
    expect(filtered.days[0].events).toHaveLength(1);
    expect(report).toContain("Full journal body");
    expect(report).not.toContain("Kitchen");
  });

  it("includes timeline periods that overlap the report range", () => {
    const items = [
      { id: "inside", start: { date: "2026-07-01" }, end: { date: "2026-08-01" } },
      { id: "year", start: { date: "2026", precision: "year" } },
      { id: "outside", start: { date: "2025-01-01" }, end: { date: "2025-02-01" } },
    ];
    expect(timelineItemsInRange(items, "2026-07-20", "2026-07-22").map((item) => item.id)).toEqual(["inside", "year"]);
  });

  it("exports private flags and multiline details safely to CSV", () => {
    const csv = activityToCsv(activity);
    expect(csv).toContain("journal_entry");
    expect(csv).toContain("true");
    expect(csv).toContain("Full journal body");
  });
});
