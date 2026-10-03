import { describe, expect, it } from "vitest";
import {
  datePartBounds,
  filterTimelineItems,
  formatDatePart,
  formatItemDuration,
  formatTravelGapDuration,
  formatTravelItemLabel,
  formatIsoTimestamp,
  makeExportDocument,
  makeImportTemplate,
  normalizeImportDocument,
  parseDateInput,
  parseDisplayDate,
  toVisItem,
  toTravelGapVisItems,
  travelFlagRegionCode,
  travelGapLabelVariants,
  travelItemLabelVariants,
  validateTimelineItem,
} from "../js/timeline-model.js";

const category = { id: "work", name: "Work", color: "#7f98b8", visible: true };
const point = {
  id: "item-point", title: "Example trip", type: "point", categoryId: "work", subcategory: "",
  start: { date: "2024-05-10", precision: "exact_day", earliest: null, latest: null }, end: null,
  ongoing: false, importance: 3, description: "", location: "", peopleIds: [], parentId: null, tagIds: [], sourceIds: [], notes: "",
};
const period = {
  ...point, id: "item-period", title: "Example job", type: "period",
  end: { date: "2025-04", precision: "month", earliest: null, latest: null },
};

function documentWith(items = [point]) {
  return { schemaVersion: 1, timelineItems: items, people: [], categories: [category], sources: [], itemLinks: [], reflections: [] };
}

describe("timeline item validation", () => {
  it("accepts a point without an end date", () => {
    expect(validateTimelineItem(point)).toEqual([]);
  });

  it("accepts a bounded period", () => {
    expect(validateTimelineItem(period)).toEqual([]);
  });

  it("accepts an ongoing period without an end date", () => {
    expect(validateTimelineItem({ ...period, ongoing: true, end: null })).toEqual([]);
  });

  it("rejects an end before the start", () => {
    const invalid = { ...period, end: { date: "2023-01-01", precision: "exact_day", earliest: null, latest: null } };
    expect(validateTimelineItem(invalid)).toContain("End cannot be before start");
  });

  it("keeps month and year semantics while deriving display bounds", () => {
    expect(datePartBounds({ date: "2024-02", precision: "month" })).toEqual({ start: "2024-02-01", end: "2024-02-29" });
    expect(datePartBounds({ date: "2022", precision: "year" })).toEqual({ start: "2022-01-01", end: "2022-12-31" });
  });

  it("uses DD/MM/YYYY in the UI without changing stored ISO dates", () => {
    expect(formatDatePart(point.start)).toBe("10/05/2024");
    expect(formatDatePart(period.end)).toBe("04/2025");
    expect(parseDisplayDate("31/12/2024")).toBe("2024-12-31");
    expect(parseDateInput("04/2025", "month")).toBe("2025-04");
    expect(formatIsoTimestamp("2026-07-22T12:00:00Z")).toMatch(/^22\/07\/2026 \d{2}:\d{2}$/);
  });

  it("shows calendar duration on periods without inventing days for month or year precision", () => {
    const monthly = {
      ...period,
      start: { date: "2022-10", precision: "month", earliest: null, latest: null },
      end: { date: "2024-02", precision: "month", earliest: null, latest: null },
    };
    expect(formatItemDuration(monthly)).toBe("Duration: 1 year, 4 months");
    const exact = {
      ...period,
      start: { date: "2020-01-15", precision: "exact_day", earliest: null, latest: null },
      end: { date: "2022-03-20", precision: "exact_day", earliest: null, latest: null },
    };
    expect(formatItemDuration(exact)).toBe("Duration: 2 years, 2 months, 5 days");
    expect(formatItemDuration({ ...monthly, ongoing: true, end: null }, new Date("2024-07-22T12:00:00Z"))).toBe("Duration: 1 year, 9 months");
  });
});

describe("timeline filtering and import", () => {
  it("filters by text, type, category, location, person and tag", () => {
    const enriched = { ...period, peopleIds: ["person-a"], tagIds: ["career"], location: "Kraków" };
    expect(filterTimelineItems([point, enriched], { search: "job", type: "period", categoryId: "work", personId: "person-a", tag: "care", location: "krak" }, [category])).toEqual([enriched]);
  });

  it("accepts valid JSON and rejects malformed JSON documents", () => {
    expect(normalizeImportDocument(documentWith()).timelineItems).toHaveLength(1);
    expect(() => normalizeImportDocument({ schemaVersion: 1, timelineItems: [] })).toThrow(/people must be an array/);
    expect(() => normalizeImportDocument(documentWith([{ ...point, title: "" }]))).toThrow(/Title is required/);
  });

  it("accepts existing category IDs during merge validation", () => {
    const mergeDocument = documentWith([point]);
    mergeDocument.categories = [];
    expect(normalizeImportDocument(mergeDocument, { existingCategoryIds: ["work"] }).timelineItems).toHaveLength(1);
    expect(() => normalizeImportDocument(mergeDocument)).toThrow(/unknown categoryId/);
  });

  it("provides a copyable complete template that validates with DD/MM/YYYY values", () => {
    const template = makeImportTemplate();
    const records = template._templateGuide.recordTemplates;
    template.timelineItems = [records.point, records.period, records.phase];
    template.people = [records.person];
    template.categories = [records.category];
    template.sources = [records.source];
    template.itemLinks = [records.itemLink];
    template.reflections = [records.reflection];
    const normalized = normalizeImportDocument(template);
    expect(normalized.timelineItems[0].start.date).toBe("2024-05-10");
    expect(normalized.timelineItems[1].start.date).toBe("2022-10");
    expect(template._templateGuide.allowedValues.datePrecision).toEqual(expect.arrayContaining(["exact_day", "month", "year", "date_range", "unknown"]));
  });

  it("exports and imports without losing data", () => {
    const exported = makeExportDocument(documentWith(), new Date("2026-07-22T12:00:00Z"));
    const imported = normalizeImportDocument(JSON.parse(JSON.stringify(exported)));
    expect(imported.timelineItems).toEqual([point]);
    expect(exported.exportedAt).toBe("2026-07-22T12:00:00.000Z");
  });

  it("maps point, period and uncertain phase records for the visual timeline", () => {
    expect(toVisItem(point, category).type).toBe("point");
    expect(toVisItem(period, category)).toMatchObject({ type: "range", group: "work" });
    expect(toVisItem(period, category).title).toContain("Duration:");
    const phase = { ...period, type: "phase", start: { date: "2021", precision: "approximate_year", earliest: null, latest: null } };
    expect(toVisItem(phase, category).className).toContain("is-uncertain");
  });

  it("draws completed end dates inclusively and ongoing items to the exact current time", () => {
    const completed = toVisItem(period, category);
    expect(completed.end).toBe("2025-05-01");
    const now = new Date("2026-07-23T14:37:00.000Z");
    const ongoing = toVisItem({ ...period, ongoing: true, end: null }, category, now);
    expect(ongoing.end).toBe(now);
  });

  it("builds labeled Travel gaps and omits zero duration units", () => {
    const travelCategory = { ...category, id: "travel", name: "Travel" };
    const firstTrip = {
      ...period, id: "trip-one", categoryId: "travel",
      start: { date: "2020-01-10", precision: "exact_day", earliest: null, latest: null },
      end: { date: "2020-01-15", precision: "exact_day", earliest: null, latest: null },
    };
    const nextTrip = {
      ...point, id: "trip-two", categoryId: "travel",
      start: { date: "2022-03-20", precision: "exact_day", earliest: null, latest: null },
    };
    const [gap] = toTravelGapVisItems([nextTrip, firstTrip], travelCategory.id);
    expect(gap).toMatchObject({ group: "travel", start: "2020-01-15", end: "2022-03-20", type: "background", selectable: false });
    expect(gap.content).toContain("2 years, 2 months, 4 days");
    expect(formatTravelGapDuration("2024-02-01", "2024-03-01")).toBe("1 month");
    expect(travelGapLabelVariants("8 months, 4 days")).toEqual({
      full: "8 months, 4 days", medium: "8 months", compact: "8 months",
    });
    expect(travelGapLabelVariants("20 days")).toEqual({ full: "20 days", medium: "", compact: "" });
  });

  it("expands Travel flags into a centered country and duration label", () => {
    const trip = {
      ...period, categoryId: "travel", title: "🇧🇬🇷🇴🇭🇺",
      start: { date: "2024-08-14", precision: "exact_day", earliest: null, latest: null },
      end: { date: "2024-08-24", precision: "exact_day", earliest: null, latest: null },
    };
    expect(formatTravelItemLabel(trip)).toBe("🇧🇬🇷🇴🇭🇺 Bulgaria, Romania, Hungary, 10 days");
    expect(travelItemLabelVariants(trip)).toEqual({
      full: "🇧🇬🇷🇴🇭🇺 Bulgaria, Romania, Hungary, 10 days",
      medium: "🇧🇬🇷🇴🇭🇺 10 days",
      compact: "🇧🇬🇷🇴🇭🇺",
    });
    expect(travelFlagRegionCode("🇧🇬")).toBe("BG");
    expect(travelFlagRegionCode("🏴󠁧󠁢󠁳󠁣󠁴󠁿")).toBe("GB-SCT");
  });

  it("does not draw a Travel gap between touching or overlapping trips", () => {
    const firstTrip = { ...period, id: "trip-one", categoryId: "travel", end: { date: "2024-05-10", precision: "exact_day", earliest: null, latest: null } };
    const touchingTrip = { ...point, id: "trip-two", categoryId: "travel", start: { date: "2024-05-11", precision: "exact_day", earliest: null, latest: null } };
    expect(toTravelGapVisItems([firstTrip, touchingTrip])).toEqual([]);
  });
});
