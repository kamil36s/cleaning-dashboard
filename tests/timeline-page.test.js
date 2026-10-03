import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("The Great Timeline page wiring", () => {
  const index = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
  const page = readFileSync(resolve(process.cwd(), "timeline.html"), "utf8");
  const script = readFileSync(resolve(process.cwd(), "js/timeline.js"), "utf8");
  const styles = readFileSync(resolve(process.cwd(), "timeline.css"), "utf8");

  it("exposes the dedicated app only through the dashboard side shortcut", () => {
    expect(index).toContain('href="./timeline.html"');
    expect(index).toContain('class="dashboard-action-link dashboard-side-shortcut dashboard-timeline-link"');
    expect(index).not.toContain('data-widget="great-timeline"');
    expect(index).not.toContain('src="./js/widget-timeline.js"');
  });

  it("provides timeline, list, form, import and category controls", () => {
    for (const id of ["timeline-canvas", "timeline-list-panel", "timeline-entry-form", "timeline-import-dialog", "timeline-category-dialog"]) {
      expect(page).toContain(`id="${id}"`);
    }
    expect(page).toContain('id="timeline-filter-travel-gaps"');
    expect(page).toContain('id="timeline-filter-travel-colors"');
    expect(page).toContain('id="timeline-filter-menu"');
    expect(page).toContain('<details class="timeline-filter-menu"');
    expect(page.indexOf('id="timeline-filter-menu"')).toBeLessThan(page.indexOf('id="timeline-density"'));
    expect(script).not.toContain("setFiltersExpanded");
  });

  it("provides accessible zoom, pan-range and fit controls", () => {
    expect(page).toContain('id="timeline-zoom-in"');
    expect(page).toContain('id="timeline-zoom-out"');
    expect(page).toContain('id="timeline-fit"');
    expect(script).toContain("zoomIn(.35)");
    expect(script).toContain("zoomOut(.35)");
    expect(script).toContain("setWindow(start, end");
    expect(script).toContain("moveable: true");
  });

  it("fills the browser viewport without a vertical timeline scrollbar", () => {
    expect(styles).toContain("height: 100dvh");
    expect(styles).toContain("overflow: hidden");
    expect(script).toContain("verticalScroll: false");
    expect(script).toContain('height: "100%"');
    expect(script).not.toContain('maxHeight: "70vh"');
    expect(script).toContain('div: ["class", "style"]');
    expect(script).toContain("scheduleTimelineRowFit");
    expect(styles).toContain("padding: 4px 6px 8px");
  });

  it("uses explicit European date inputs instead of browser-dependent date fields", () => {
    expect(page).not.toContain('type="date"');
    expect(page.match(/placeholder="DD\/MM\/YYYY"/g)?.length).toBeGreaterThanOrEqual(7);
    expect(script).toContain('month: "MMMM"');
    expect(script).toContain('week: "[tydz.] W"');
    expect(script).toContain('day: "D ddd"');
    expect(script).toContain('scale: "day", step: 1');
    expect(script).not.toContain('month: "MM"');
  });

  it("shows every daily signal source on its own timeline row", () => {
    expect(script).toContain('type: "range"');
    expect(script).toContain("activitySourcesForDays");
    expect(script).toContain("activityPeriodForSource");
    expect(script).toContain("group: activityGroupId(source.id)");
    expect(script).toContain("subgroup: source.id");
    expect(script).toContain("activitySourcePeriods.map");
    expect(script).toContain("aggregateActivityDays");
    expect(styles).toContain(".timeline-signal-card");
    expect(styles).toContain("var(--signal-color)");
    expect(script).not.toContain("<b>${escapeHtml(period.label)}</b>");
    expect(script).toContain("activityPeriodSummary(period, source.id, previousPeriod)");
    expect(styles).toContain(".timeline-signal-secondary");
  });

  it("uses one visual label system for activity sources and timeline categories", () => {
    expect(script).toContain('class="timeline-group-label is-signal"');
    expect(script).toContain('class="timeline-group-label is-category"');
    expect(script).toContain('class="timeline-group-marker"');
    expect(styles).toContain(".timeline-group-label");
    expect(styles).toContain(".timeline-group-marker");
    expect(styles).toContain(".timeline-group-dot");
  });

  it("lets the left visibility list toggle daily signals as well as timeline categories", () => {
    expect(script).toContain('data-activity-toggle="${escapeHtml(source.id)}"');
    expect(script).toContain('closest("[data-activity-toggle]")');
    expect(script).toContain("saveActivitySettings()");
    expect(script).toContain("shownCategoryIds");
  });

  it("fits ordinary timeline labels without changing their bar lengths", () => {
    expect(script).toContain("updateTimelineItemLabels");
    expect(script).toContain("TIMELINE_LABEL_MIN_FONT_SIZE = 7");
    expect(script).toContain("TIMELINE_LABEL_MIN_SCALE_X = .7");
    expect(script).toContain('item.clientWidth >= 110');
    expect(script).toContain('label.style.fontSize');
    expect(script).toContain('label.style.transform = `scaleX(${scaleX})`');
    expect(script).toContain("scheduleTimelineItemLabels");
    expect(styles).toContain(".timeline-item-label");
    expect(styles).toContain(".is-compact-ongoing-label::after");
  });

  it("passes items and groups separately on the first timeline render", () => {
    expect(script).toContain("new Timeline(elements.canvas, data.items, data.groups, {");
    expect(script).not.toContain("new Timeline(elements.canvas, data, {");
  });

  it("shows complete Last.fm chart winners on separate lines", () => {
    expect(script).toContain('label: "Artist"');
    expect(script).toContain('label: "Album"');
    expect(script).toContain('label: "Song"');
    expect(script).toContain('icon: "👨🏻‍🎤"');
    expect(script).toContain('icon: "💿"');
    expect(script).toContain('icon: "🎵"');
    expect(script).toContain("`${album} by ${albumArtist}`");
    expect(script).toContain("`${track} by ${trackArtist}`");
    expect(script).toContain("timeline-lastfm-name");
    expect(script).toContain("timeline-lastfm-scrobbles");
    expect(styles).toContain(".timeline-lastfm-line");
    expect(styles).toContain("text-overflow: ellipsis");
    expect(styles).toContain("white-space: nowrap");
  });

  it("renders optional gold Travel gap connectors", () => {
    expect(script).toContain("toTravelGapVisItems");
    expect(script).toContain('subgroup: "travel"');
    expect(script).toContain('subgroup: "home"');
    expect(script).toContain("subgroupStack: { travel: false");
    expect(script).toContain("subgroupStack: { home: false");
    expect(script).toContain("subgroupStack: { health: false");
    expect(script).not.toContain('subgroup: "relationships"');
    expect(script).toContain("timeline-responsive-label-");
    expect(script).toContain("scheduleResponsiveTravelLabels");
    expect(script).not.toContain('on("rangechange", scheduleResponsiveTravelLabels)');
    expect(script).not.toContain('on("changed", scheduleResponsiveTravelLabels)');
    expect(script).toContain("activityGranularityForRange(days, timelineViewportWidth())");
    expect(script).toContain("label.scrollWidth <= label.clientWidth");
    expect(script).toContain("flagColorGradient");
    expect(styles).toContain(".timeline-vis-travel .vis-item-content");
    expect(styles).toContain(".timeline-vis-health .vis-item-content");
    expect(styles).toContain("-webkit-text-stroke: .65px #000");
    expect(styles).toContain("background: rgba(5, 6, 8, .84)");
    expect(styles).toContain("width: max-content");
    expect(styles).toContain(".has-flag-gradient");
    expect(styles).toContain("#ffd166");
    expect(styles).toContain("#d6ad52");
  });

  it("offers a copyable and downloadable complete JSON template", () => {
    expect(page).toContain('id="timeline-template-copy"');
    expect(page).toContain('id="timeline-template-download"');
    expect(page).toContain('id="timeline-template-preview"');
    expect(script).toContain("makeImportTemplate");
  });

  it("offers connected-data imports for Loop and How We Feel", () => {
    expect(page).toContain('id="timeline-habits-import"');
    expect(page).toContain('id="timeline-emotions-file"');
    expect(page).toContain('id="timeline-emotions-import"');
    expect(script).toContain("importHowWeFeel");
  });
});
