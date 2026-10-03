export const ACTIVITY_SOURCES = [
  { id: "lastfm", label: "Last.fm", icon: "♫", color: "#d92323", private: true, report: false },
  { id: "journal", label: "Journal", icon: "📓", color: "#d9b36c", private: true },
  { id: "poems", label: "Poems", icon: "✒", color: "#bd8fb3", private: true, report: false },
  { id: "cleaning", label: "Cleaning", icon: "🧹", color: "#6fc7b3" },
  { id: "reading", label: "Reading", icon: "📚", color: "#8ba7dc" },
  { id: "habits", label: "Habits", icon: "✅", color: "#c790d8", private: true },
  { id: "todos", label: "Completed tasks", icon: "☑️", color: "#db8c70", private: true },
  { id: "selfCare", label: "Self-care", icon: "🧘", color: "#df8faf", private: true },
  { id: "emotions", label: "Emotions", icon: "💭", color: "#ef7d9b", private: true },
  { id: "health", label: "Health & activity", icon: "🏃", color: "#88c66e", private: true },
  { id: "culture", label: "Culture & events", icon: "🎭", color: "#9c94dd", optional: true },
];

export const DEFAULT_ACTIVITY_SETTINGS = Object.freeze({
  journalContent: "full",
  sources: Object.fromEntries(ACTIVITY_SOURCES.map((source) => [source.id, {
    timeline: source.optional !== true,
    report: source.report !== false && source.optional !== true,
  }])),
});

export function normalizeActivitySettings(value = {}) {
  const sources = {};
  for (const source of ACTIVITY_SOURCES) {
    const incoming = value.sources?.[source.id] || {};
    const defaults = DEFAULT_ACTIVITY_SETTINGS.sources[source.id];
    sources[source.id] = {
      timeline: typeof incoming.timeline === "boolean" ? incoming.timeline : defaults.timeline,
      report: typeof incoming.report === "boolean" ? incoming.report : defaults.report,
    };
  }
  return {
    journalContent: ["full", "summary", "metadata"].includes(value.journalContent) ? value.journalContent : "full",
    sources,
  };
}

export function enabledSources(settings, purpose = "timeline") {
  return ACTIVITY_SOURCES.filter((source) => settings.sources[source.id]?.[purpose]).map((source) => source.id);
}

export function formatActivityDate(iso) {
  const raw = String(iso || "");
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw);
  if (match) return `${match[3]}/${match[2]}/${match[1]}`;
  const month = /^(\d{4})-(\d{2})$/.exec(raw);
  if (month) return `${month[2]}/${month[1]}`;
  if (/^\d{4}$/.test(raw)) return raw;
  return "—";
}

export function dayTooltip(day) {
  const labels = new Map(ACTIVITY_SOURCES.map((source) => [source.id, source.label]));
  const lines = [`${formatActivityDate(day.date)} · ${day.total} records`];
  const grouped = new Map();
  for (const event of day.events || []) {
    if (!grouped.has(event.source)) grouped.set(event.source, []);
    grouped.get(event.source).push(event);
  }
  for (const [source, events] of grouped) {
    let value = `${events.length}`;
    if (source === "cleaning") value = `${events.length} action(s)`;
    if (source === "journal") value = `${events.length} entry/entries`;
    if (source === "poems") value = `${events.length} poem(s)`;
    if (source === "habits") value = `${events.length} completed`;
    if (source === "todos") value = `${events.length} completed`;
    if (source === "emotions") {
      const moods = [...new Set(events.map((event) => event.metrics?.mood || event.metrics?.moodKey).filter(Boolean))];
      const visibleMoods = moods.slice(0, 5);
      value = `${events.length} check-in(s)${visibleMoods.length ? ` · ${visibleMoods.join(", ")}${moods.length > visibleMoods.length ? ` +${moods.length - visibleMoods.length}` : ""}` : ""}`;
    }
    if (source === "reading") {
      const pages = events.reduce((sum, event) => sum + Number(event.metrics?.pages || 0), 0);
      value = pages ? `${pages} pages` : value;
    }
    if (source === "health") {
      const steps = events.reduce((sum, event) => sum + Number(event.metrics?.steps || 0), 0);
      value = steps ? `${steps.toLocaleString("en-US")} steps · ${events.length} record(s)` : value;
    }
    if (source === "lastfm") {
      const chart = events[0]?.metrics || {};
      value = `${Number(chart.scrobbles || 0).toLocaleString("pl-PL")} scrobbles${chart.topArtist?.name ? ` · ${chart.topArtist.name}` : ""}`;
    }
    const definition = sourceFor(source);
    lines.push(`${definition.icon || "•"} ${labels.get(source) || source}: ${value}`);
  }
  for (const [source, count] of Object.entries(day.sourceCounts || {})) {
    if (!grouped.has(source)) {
      const definition = sourceFor(source);
      lines.push(`${definition.icon || "•"} ${labels.get(source) || source}: ${count}`);
    }
  }
  return lines.join("\n");
}

export function activityEventTextBlocks(event) {
  const summary = String(event?.summary || "").trim();
  const details = String(event?.details || "").trim();
  if (["journal", "poems"].includes(event?.source) && details) return [details];
  return [summary, details].filter(Boolean);
}

export function sourceFor(id) {
  return ACTIVITY_SOURCES.find((source) => source.id === id) || { id, label: id, icon: "•", color: "#999" };
}

function compactMetricNumber(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1000) {
    return new Intl.NumberFormat("pl-PL", { notation: "compact", maximumFractionDigits: 1 }).format(number).replace(/\s/g, " ");
  }
  return String(Math.round(number));
}

export function activityPeriodAverageWeight(period) {
  let weightedTotal = 0;
  let measurementCount = 0;
  for (const event of period?.events || []) {
    if (event.source !== "health") continue;
    const averageKg = Number(event.metrics?.averageKg);
    if (!Number.isFinite(averageKg) || averageKg <= 0) continue;
    const measurements = Math.max(1, Number(event.metrics?.measurements) || 1);
    weightedTotal += averageKg * measurements;
    measurementCount += measurements;
  }
  return measurementCount ? weightedTotal / measurementCount : null;
}

export function activityPeriodSummary(period, sourceId, previousPeriod = null) {
  const events = (period?.events || []).filter((event) => event.source === sourceId);
  const count = events.length;
  const icon = sourceFor(sourceId).icon || "•";
  const result = { primary: `${icon} ${count} ${count === 1 ? "record" : "records"}`, secondary: "", trend: "", trendTone: "", trendLabel: "" };

  if (sourceId === "journal") result.primary = `${icon} ${count} ${count === 1 ? "entry" : "entries"}`;
  if (sourceId === "poems") result.primary = `${icon} ${count} ${count === 1 ? "poem" : "poems"}`;
  if (sourceId === "cleaning") result.primary = `${icon} ${count} ${count === 1 ? "action" : "actions"}`;
  if (sourceId === "reading") {
    const pages = events.reduce((sum, event) => sum + Number(event.metrics?.pages || 0), 0);
    result.primary = `${icon} ${compactMetricNumber(pages)} ${pages === 1 ? "page" : "pages"}`;
  }
  if (sourceId === "habits") result.primary = `${icon} ${count} ${count === 1 ? "entry" : "entries"}`;
  if (sourceId === "todos") result.primary = `${icon} ${count} completed`;
  if (sourceId === "selfCare") result.primary = `${icon} ${count} ${count === 1 ? "record" : "records"}`;
  if (sourceId === "emotions") result.primary = `${icon} ${count} ${count === 1 ? "check-in" : "check-ins"}`;
  if (sourceId === "culture") result.primary = `${icon} ${count} ${count === 1 ? "event" : "events"}`;
  if (sourceId === "health") {
    const steps = events.reduce((sum, event) => sum + Number(event.metrics?.steps || 0), 0);
    const averageKg = activityPeriodAverageWeight(period);
    const previousAverageKg = activityPeriodAverageWeight(previousPeriod);
    result.primary = `👟 ${compactMetricNumber(steps)} steps`;
    if (averageKg !== null) {
      result.secondary = `⚖️ ${new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(averageKg)} kg`;
    }
    if (averageKg !== null && previousAverageKg !== null) {
      const difference = averageKg - previousAverageKg;
      result.trend = difference < -0.005 ? "↓" : difference > 0.005 ? "↑" : "";
      result.trendTone = difference < -0.005 ? "drop" : difference > 0.005 ? "gain" : "";
      result.trendLabel = `${difference > 0 ? "+" : ""}${new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(difference)} kg vs previous period`;
    }
  }
  return result;
}

const DAY_MS = 86_400_000;

function parseIsoDay(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

function localIsoDay(value) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function addDays(value, count) {
  const next = new Date(value);
  next.setDate(next.getDate() + count);
  return next;
}

function isoWeek(value) {
  const utc = new Date(Date.UTC(value.getFullYear(), value.getMonth(), value.getDate()));
  utc.setUTCDate(utc.getUTCDate() + 4 - (utc.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  return Math.ceil((((utc - yearStart) / DAY_MS) + 1) / 7);
}

function periodDefinition(day, granularity) {
  const value = parseIsoDay(day);
  if (!value) return null;
  if (granularity === "week") {
    const weekday = value.getDay() || 7;
    const start = addDays(value, 1 - weekday);
    const end = addDays(start, 7);
    const endInclusive = addDays(end, -1);
    return {
      key: localIsoDay(start), start, end,
      label: `Tydz. ${isoWeek(start)} · ${String(start.getDate()).padStart(2, "0")}/${String(start.getMonth() + 1).padStart(2, "0")}–${String(endInclusive.getDate()).padStart(2, "0")}/${String(endInclusive.getMonth() + 1).padStart(2, "0")}`,
    };
  }
  if (granularity === "month") {
    const start = new Date(value.getFullYear(), value.getMonth(), 1);
    const end = new Date(value.getFullYear(), value.getMonth() + 1, 1);
    const month = new Intl.DateTimeFormat("pl-PL", { month: "long" }).format(start);
    return { key: localIsoDay(start).slice(0, 7), start, end, label: `${month} ${start.getFullYear()}` };
  }
  if (granularity === "year") {
    const start = new Date(value.getFullYear(), 0, 1);
    const end = new Date(value.getFullYear() + 1, 0, 1);
    return { key: String(value.getFullYear()), start, end, label: String(value.getFullYear()) };
  }
  const end = addDays(value, 1);
  const label = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short" }).format(value);
  return { key: day, start: value, end, label };
}

export function activityGranularityForRange(rangeDays, viewportWidth = 0) {
  const days = Math.max(1, Number(rangeDays) || 1);
  const width = Number(viewportWidth) || 0;
  if (width > 0) {
    const pixelsPerDay = width / days;
    if (pixelsPerDay >= 72) return "day";
    if (pixelsPerDay * 7 >= 90) return "week";
    if (days <= 370) return "month";
    if (pixelsPerDay * 30.4375 >= 110) return "month";
    return "year";
  }
  if (days <= 45) return "day";
  if (days <= 180) return "week";
  if (days <= 730) return "month";
  return "year";
}

export function aggregateActivityDays(days, granularity = "day") {
  const buckets = new Map();
  for (const day of days || []) {
    const definition = periodDefinition(day.date, granularity);
    if (!definition) continue;
    if (!buckets.has(definition.key)) {
      buckets.set(definition.key, {
        id: `activity-period-${granularity}-${definition.key}`,
        granularity,
        label: definition.label,
        start: localIsoDay(definition.start),
        endExclusive: localIsoDay(definition.end),
        end: localIsoDay(addDays(definition.end, -1)),
        date: localIsoDay(definition.start),
        total: 0,
        sourceCounts: {},
        events: [],
        days: [],
      });
    }
    const bucket = buckets.get(definition.key);
    bucket.days.push(day.date);
    bucket.events.push(...(day.events || []));
    bucket.total += Number(day.total || day.events?.length || 0);
    for (const [source, count] of Object.entries(day.sourceCounts || {})) {
      bucket.sourceCounts[source] = (bucket.sourceCounts[source] || 0) + Number(count || 0);
    }
  }
  return [...buckets.values()].sort((a, b) => a.start.localeCompare(b.start));
}

function itemBoundary(item, side) {
  const part = item?.[side];
  return part?.date || part?.earliest || part?.latest || "";
}

function comparableBoundary(part, edge) {
  const raw = edge === "start"
    ? (part?.earliest || part?.date || part?.latest || "")
    : (part?.latest || part?.date || part?.earliest || "");
  if (/^\d{4}$/.test(raw)) return `${raw}-${edge === "start" ? "01-01" : "12-31"}`;
  if (/^\d{4}-\d{2}$/.test(raw)) return `${raw}-${edge === "start" ? "01" : "31"}`;
  return raw;
}

export function timelineItemsInRange(items, from, to) {
  return (items || []).filter((item) => {
    const start = comparableBoundary(item.start, "start");
    const end = item.ongoing ? to : (comparableBoundary(item.end, "end") || comparableBoundary(item.start, "end"));
    return Boolean(start && start <= to && end >= from);
  });
}

export function filterActivityForReport(activity, settings) {
  const allowed = new Set(enabledSources(settings, "report"));
  return {
    ...activity,
    days: (activity.days || []).map((day) => {
      const events = (day.events || []).filter((event) => allowed.has(event.source));
      const sourceCounts = {};
      for (const event of events) sourceCounts[event.source] = (sourceCounts[event.source] || 0) + 1;
      return { ...day, total: events.length, events, sourceCounts };
    }).filter((day) => day.events.length),
  };
}

function eventText(event, markdown) {
  const prefix = markdown ? "- **" : "- ";
  const suffix = markdown ? "**" : "";
  const summary = event.summary ? ` — ${event.summary}` : "";
  const lines = [`${prefix}${event.title}${suffix}${summary}`];
  if (event.details) {
    const details = String(event.details).trim().split("\n");
    lines.push(...details.map((line) => markdown ? `  ${line}` : `  ${line}`));
  }
  return lines.join("\n");
}

export function buildTextReport(activity, timelineItems = [], { markdown = false, title = "The Great Timeline report" } = {}) {
  const heading = markdown ? "# " : "";
  const h2 = markdown ? "## " : "";
  const h3 = markdown ? "### " : "";
  const lines = [
    `${heading}${title}`,
    `${formatActivityDate(activity.from)} – ${formatActivityDate(activity.to)}`,
    `Days with records: ${(activity.days || []).length}; activity records: ${(activity.days || []).reduce((sum, day) => sum + day.events.length, 0)}; timeline entries: ${timelineItems.length}`,
  ];

  if (timelineItems.length) {
    lines.push("", `${h2}Timeline entries`);
    for (const item of timelineItems) {
      const start = itemBoundary(item, "start");
      const end = item.ongoing ? "ongoing" : itemBoundary(item, "end");
      lines.push(`- ${item.title} (${formatActivityDate(start)}${end ? ` – ${end === "ongoing" ? end : formatActivityDate(end)}` : ""})`);
      if (item.description) lines.push(`  ${item.description}`);
      if (item.notes) lines.push(`  Notes: ${item.notes}`);
    }
  }

  const labels = new Map(ACTIVITY_SOURCES.map((source) => [source.id, source.label]));
  for (const day of activity.days || []) {
    lines.push("", `${h2}${formatActivityDate(day.date)}`);
    const groups = new Map();
    for (const event of day.events || []) {
      if (!groups.has(event.source)) groups.set(event.source, []);
      groups.get(event.source).push(event);
    }
    for (const [source, events] of groups) {
      lines.push("", `${h3}${labels.get(source) || source} (${events.length})`);
      lines.push(...events.map((event) => eventText(event, markdown)));
    }
  }
  return lines.join("\n").trim() + "\n";
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function activityToCsv(activity, timelineItems = []) {
  const rows = [["recordType", "date", "endDate", "source", "kind", "title", "summary", "details", "occurredAt", "private", "metrics"]];
  for (const item of timelineItems) {
    rows.push([
      "timeline", itemBoundary(item, "start"), item.ongoing ? "ongoing" : itemBoundary(item, "end"), "timeline", item.type,
      item.title, item.description, item.notes, item.updatedAt, item.private, JSON.stringify({ categoryId: item.categoryId, tags: item.tagIds || [], peopleIds: item.peopleIds || [] }),
    ]);
  }
  for (const day of activity.days || []) {
    for (const event of day.events || []) {
      rows.push(["activity", day.date, "", event.source, event.kind, event.title, event.summary, event.details, event.occurredAt, event.private, JSON.stringify(event.metrics || {})]);
    }
  }
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}
