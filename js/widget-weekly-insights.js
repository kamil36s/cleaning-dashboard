import { fetchAiUsage } from "./ai-usage-api.js";
import { getCleaningHistory, getCleaningSettings } from "./cleaning-api.js";
import { fetchReadingHistory } from "./reading-api.js";
import { jobhuntApi } from "./jobhunt-api.js";
import { escapeHtml } from "./utils.js";

const REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const DEFAULT_APARTMENT_ID = "aleja-pokoju6";

function localDay(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(date, days) {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  copy.setDate(copy.getDate() + days);
  return copy;
}

export function buildWeeklyWindows(now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const currentStart = addDays(today, -6);
  const currentEnd = addDays(today, 1);
  const previousStart = addDays(currentStart, -7);
  return {
    current: { start: localDay(currentStart), end: localDay(currentEnd) },
    previous: { start: localDay(previousStart), end: localDay(currentStart) },
  };
}

function dayFromValue(value) {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return String(value);
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? localDay(parsed) : "";
}

function inWindow(day, window) {
  return Boolean(day && day >= window.start && day < window.end);
}

function sum(values) {
  return values.reduce((total, value) => total + (Number(value) || 0), 0);
}

function plural(value, singular, pluralForm) {
  return `${value} ${value === 1 ? singular : pluralForm}`;
}

function comparison(current, previous, { higherIsBetter = true } = {}) {
  const delta = current - previous;
  const direction = delta > 0 ? "up" : delta < 0 ? "down" : "stable";
  const tone = delta === 0
    ? "stable"
    : (delta > 0) === higherIsBetter
      ? "positive"
      : "negative";
  let label = "Same as last week";
  let percent = 0;
  if (previous > 0) {
    percent = Math.round((delta / previous) * 100);
    if (delta !== 0) label = `${percent > 0 ? "+" : ""}${percent}%`;
  } else if (current > 0) {
    label = "New this week";
    percent = 100;
  }
  return { delta, direction, tone, comparison: label, percent };
}

function candidateImportance(candidate) {
  const change = Math.min(100, Math.abs(candidate.percent || 0));
  const riskBonus = candidate.tone === "negative" ? 18 : 0;
  const activityBonus = candidate.current > 0 || candidate.previous > 0 ? 10 : 0;
  return change + riskBonus + activityBonus + (candidate.priority || 0);
}

function makeCandidate(data) {
  return { ...data, ...comparison(data.current, data.previous, data) };
}

function cleaningCandidate(payload, windows) {
  const actions = Array.isArray(payload?.actions) ? payload.actions : [];
  const currentActions = actions.filter((item) => inWindow(dayFromValue(item?.doneAt || item?.at), windows.current));
  const previousActions = actions.filter((item) => inWindow(dayFromValue(item?.doneAt || item?.at), windows.previous));
  if (!currentActions.length && !previousActions.length) return null;
  const activeDays = new Set(currentActions.map((item) => dayFromValue(item?.doneAt || item?.at))).size;
  const result = makeCandidate({
    key: "cleaning",
    label: "Cleaning",
    current: currentActions.length,
    previous: previousActions.length,
    higherIsBetter: true,
    priority: 8,
    value: plural(currentActions.length, "task completed", "tasks completed"),
    detail: `${plural(activeDays, "active day", "active days")} · previous week: ${previousActions.length}`,
  });
  result.watch = result.tone === "negative"
    ? `Cleaning activity fell from ${previousActions.length} to ${currentActions.length} completions.`
    : null;
  return result;
}

function readingCandidate(payload, windows) {
  const log = payload?.log && typeof payload.log === "object" ? payload.log : {};
  const currentRows = Object.entries(log).filter(([day]) => inWindow(day, windows.current));
  const previousRows = Object.entries(log).filter(([day]) => inWindow(day, windows.previous));
  const current = sum(currentRows.map(([, row]) => row?.total));
  const previous = sum(previousRows.map(([, row]) => row?.total));
  if (!current && !previous) return null;
  const activeDays = currentRows.filter(([, row]) => Number(row?.total) > 0).length;
  const result = makeCandidate({
    key: "reading",
    label: "Reading",
    current,
    previous,
    higherIsBetter: true,
    priority: 9,
    value: plural(current, "page read", "pages read"),
    detail: `${plural(activeDays, "reading day", "reading days")} · previous week: ${previous} pages`,
  });
  result.watch = result.tone === "negative"
    ? `Reading dropped by ${Math.abs(result.delta)} pages versus the previous seven days.`
    : null;
  return result;
}

function jobhuntCandidate(payload, windows) {
  const jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
  const applied = (window) => jobs.filter((job) => inWindow(dayFromValue(job?.application?.dateApplied), window)).length;
  const added = (window) => jobs.filter((job) => inWindow(dayFromValue(job?.createdAt), window)).length;
  const currentApplications = applied(windows.current);
  const previousApplications = applied(windows.previous);
  const useApplications = currentApplications > 0 || previousApplications > 0;
  const current = useApplications ? currentApplications : added(windows.current);
  const previous = useApplications ? previousApplications : added(windows.previous);
  if (!current && !previous) return null;
  const today = windows.current.end;
  const due = jobs.filter((job) => {
    const dueDay = dayFromValue(job?.application?.followUpDate);
    const closed = new Set(["offer", "rejected", "archived", "expired"]);
    return dueDay && dueDay < today && ![job?.applicationStatus, job?.status].some((status) => closed.has(status));
  }).length;
  const noun = useApplications ? "application" : "new offer";
  const result = makeCandidate({
    key: "jobhunt",
    label: "Job hunt",
    current,
    previous,
    higherIsBetter: true,
    priority: 7,
    value: plural(current, noun, `${noun}s`),
    detail: `${previous} in the previous week${due ? ` · ${plural(due, "follow-up", "follow-ups")} due` : ""}`,
  });
  result.watch = due
    ? `${plural(due, "Job application needs", "Job applications need")} a follow-up.`
    : result.tone === "negative"
      ? `Job hunt activity fell from ${previous} to ${current}.`
      : null;
  return result;
}

function aiCandidate(payload, windows) {
  const history = Array.isArray(payload?.history) ? payload.history : [];
  const burn = (window) => sum(history
    .filter((row) => inWindow(dayFromValue(row?.checkedAt || row?.updatedAt), window))
    .map((row) => row?.weeklyBurn));
  const current = Math.round(burn(windows.current) * 10) / 10;
  const previous = Math.round(burn(windows.previous) * 10) / 10;
  const providers = Array.isArray(payload?.providers) ? payload.providers : [];
  const remainingValues = providers
    .filter((provider) => ["connected", "stale"].includes(String(provider?.status || "").toLowerCase()))
    .map((provider) => provider?.weekly?.remaining)
    .filter((remaining) => remaining !== null && remaining !== undefined && remaining !== "")
    .map(Number)
    .filter(Number.isFinite);
  const remaining = remainingValues.length ? Math.min(...remainingValues) : null;
  if (!current && !previous && remaining === null) return null;
  if (!current && !previous) {
    return {
      key: "ai-usage",
      label: "AI quota",
      current: remaining,
      previous: null,
      delta: 0,
      direction: "unclear",
      tone: remaining < 20 ? "negative" : "unclear",
      comparison: "No comparable usage signal",
      percent: 0,
      priority: 5,
      importance: remaining < 20 ? 45 : 5,
      value: `${Math.round(remaining)}% available`,
      detail: "Current weekly quota · history is not long enough to compare",
      watch: remaining < 20 ? `AI weekly quota is down to ${Math.round(remaining)}% available.` : null,
    };
  }
  const result = makeCandidate({
    key: "ai-usage",
    label: "AI quota",
    current,
    previous,
    higherIsBetter: false,
    priority: 4,
    value: `${current.toFixed(current % 1 ? 1 : 0)}% used`,
    detail: `${remaining === null ? "Current quota unavailable" : `${Math.round(remaining)}% available now`} · previous week: ${previous}% used`,
  });
  result.watch = remaining !== null && remaining < 20
    ? `AI weekly quota is down to ${Math.round(remaining)}% available.`
    : result.tone === "negative"
      ? `AI quota use rose from ${previous}% to ${current}%.`
      : null;
  return result;
}

function stepsCandidate(payload, windows) {
  const rows = Array.isArray(payload?.daily) ? payload.daily.filter((row) => !row?.filled) : [];
  const values = (window) => rows
    .filter((row) => inWindow(dayFromValue(row?.day), window))
    .map((row) => Number(row?.steps))
    .filter(Number.isFinite);
  const currentRows = values(windows.current);
  const previousRows = values(windows.previous);
  if (currentRows.length < 2 || previousRows.length < 2) return null;
  const current = Math.round(sum(currentRows) / currentRows.length);
  const previous = Math.round(sum(previousRows) / previousRows.length);
  const result = makeCandidate({
    key: "steps",
    label: "Steps",
    current,
    previous,
    higherIsBetter: true,
    priority: 3,
    value: `${current.toLocaleString("en-US")} daily average`,
    detail: `${currentRows.length} recorded days · previous week: ${previous.toLocaleString("en-US")}`,
  });
  result.watch = result.tone === "negative"
    ? `Daily steps averaged ${Math.abs(result.delta).toLocaleString("en-US")} fewer than last week.`
    : null;
  return result;
}

function sleepCandidate(payload, windows) {
  const snapshots = Array.isArray(payload?.snapshots) ? payload.snapshots : [];
  const minutesByDay = new Map();
  snapshots.forEach((snapshot) => {
    const day = dayFromValue(snapshot?.day || snapshot?.payload?.day);
    const sessions = Array.isArray(snapshot?.payload?.sleep?.sessions) ? snapshot.payload.sleep.sessions : [];
    const minutes = sum(sessions.map((session) => {
      const start = new Date(session?.start).getTime();
      const end = new Date(session?.end).getTime();
      return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) / 60000 : 0;
    }));
    if (day && minutes > 0) minutesByDay.set(day, Math.round(minutes));
  });
  const values = (window) => Array.from(minutesByDay.entries())
    .filter(([day]) => inWindow(day, window))
    .map(([, minutes]) => minutes);
  const currentRows = values(windows.current);
  const previousRows = values(windows.previous);
  if (currentRows.length < 2 || previousRows.length < 2) return null;
  const current = Math.round(sum(currentRows) / currentRows.length);
  const previous = Math.round(sum(previousRows) / previousRows.length);
  const formatDuration = (minutes) => `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
  const result = makeCandidate({
    key: "sleep",
    label: "Sleep",
    current,
    previous,
    higherIsBetter: true,
    priority: 6,
    value: `${formatDuration(current)} average`,
    detail: `${currentRows.length} recorded nights · previous week: ${formatDuration(previous)}`,
  });
  result.watch = result.tone === "negative"
    ? `Average sleep fell by ${Math.abs(result.delta)} minutes versus last week.`
    : null;
  return result;
}

function trendText(candidate) {
  if (!candidate) return "No comparable weekly trend yet.";
  if (candidate.tone === "positive") return `${candidate.label} improved most (${candidate.comparison}).`;
  if (candidate.tone === "negative") return `${candidate.label} changed most and needs attention.`;
  return `${candidate.label} was steady week over week.`;
}

export function buildWeeklyInsights(sources = {}, { now = new Date(), maxInsights = 5 } = {}) {
  const windows = buildWeeklyWindows(now);
  const candidates = [
    cleaningCandidate(sources.cleaning, windows),
    readingCandidate(sources.reading, windows),
    jobhuntCandidate(sources.jobhunt, windows),
    aiCandidate(sources.aiUsage, windows),
    stepsCandidate(sources.steps, windows),
    sleepCandidate(sources.sleep, windows),
  ].filter(Boolean).map((candidate) => ({
    ...candidate,
    importance: candidate.importance || candidateImportance(candidate),
  }));

  const insights = [...candidates]
    .sort((left, right) => right.importance - left.importance)
    .slice(0, Math.max(3, Math.min(5, maxInsights)));
  const positive = [...candidates].filter((item) => item.tone === "positive")
    .sort((left, right) => right.importance - left.importance)[0] || null;
  const negative = [...candidates].filter((item) => item.tone === "negative")
    .sort((left, right) => right.importance - left.importance)[0] || null;
  const strongest = positive || negative || [...candidates].sort((left, right) => right.importance - left.importance)[0] || null;

  let summary = "There is not enough comparable history for a weekly readout yet.";
  if (positive && negative) {
    summary = `${positive.label} led the week, while ${negative.label.toLowerCase()} is the clearest area to watch.`;
  } else if (positive) {
    summary = `${positive.label} was the clearest improvement in the available data.`;
  } else if (negative) {
    summary = `${negative.label} slipped most compared with the previous seven days.`;
  } else if (strongest) {
    summary = "The available weekly signals were mostly steady.";
  }

  const watch = candidates
    .filter((candidate) => candidate.watch)
    .sort((left, right) => right.importance - left.importance)
    .map((candidate) => ({ key: candidate.key, text: candidate.watch }))
    .filter((item, index, items) => items.findIndex((other) => other.text === item.text) === index)
    .slice(0, 3);
  if (!watch.length && candidates.length) {
    watch.push({ key: "clear", text: "No major negative trend in the available weekly data." });
  }

  return {
    windows,
    insights,
    summary,
    strongest: strongest ? {
      label: positive ? "Biggest win" : negative ? "Biggest risk" : "Strongest trend",
      text: trendText(strongest),
      tone: strongest.tone,
    } : null,
    watch,
  };
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store", headers: { Accept: "application/json" } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) throw new Error(payload?.error || `${url} returned HTTP ${response.status}`);
  return payload;
}

async function loadCleaningSource() {
  const settings = await getCleaningSettings().catch(() => ({}));
  const apartmentId = settings?.activeApartmentId || settings?.settings?.activeApartmentId || DEFAULT_APARTMENT_ID;
  const [currentMonth, previousMonth] = await Promise.all([
    getCleaningHistory(apartmentId, { range: "month", offset: 0 }),
    getCleaningHistory(apartmentId, { range: "month", offset: -1 }),
  ]);
  return {
    actions: [...(currentMonth?.actions || []), ...(previousMonth?.actions || [])],
  };
}

async function loadJobhuntSource() {
  const [jobsResult, overviewResult] = await Promise.allSettled([
    jobhuntApi.jobs({ limit: 500 }),
    jobhuntApi.overview(),
  ]);
  if (jobsResult.status === "rejected" && overviewResult.status === "rejected") throw jobsResult.reason;
  return {
    jobs: jobsResult.status === "fulfilled" ? jobsResult.value?.jobs || [] : [],
    summary: overviewResult.status === "fulfilled" ? overviewResult.value?.summary || {} : {},
  };
}

export async function loadWeeklyInsightSources() {
  const entries = await Promise.allSettled([
    loadCleaningSource(),
    fetchReadingHistory(),
    loadJobhuntSource(),
    fetchAiUsage(globalThis.fetch, { historyHours: 24 * 15, sessionLimit: 30 }),
    fetchJson("/api/steps/history?days=14"),
    fetchJson("/api/health-connect/history"),
  ]);
  const keys = ["cleaning", "reading", "jobhunt", "aiUsage", "steps", "sleep"];
  const sources = {};
  let availableSources = 0;
  entries.forEach((entry, index) => {
    if (entry.status === "fulfilled") {
      sources[keys[index]] = entry.value;
      availableSources += 1;
    }
  });
  if (!availableSources) throw new Error("Weekly insights unavailable");
  return { sources, availableSources };
}

function changeGlyph(insight) {
  if (insight.direction === "up") return "↗";
  if (insight.direction === "down") return "↘";
  if (insight.direction === "stable") return "→";
  return "·";
}

function renderModel(root, model, availableSources) {
  if (!model.insights.length) {
    root.innerHTML = `
      <div class="weekly-insights-empty">
        <strong>Not enough weekly history yet</strong>
        <span>Keep using the trackers; comparisons appear once two seven-day windows contain activity.</span>
      </div>
    `;
    return;
  }
  const finalDay = addDays(new Date(`${model.windows.current.end}T12:00:00`), -1);
  const firstDay = new Date(`${model.windows.current.start}T12:00:00`);
  const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
  const dateLabel = `${dateFormat.format(firstDay)} – ${dateFormat.format(finalDay)}`;
  root.innerHTML = `
    <section class="weekly-insights-summary">
      <span class="weekly-insights-eyebrow">Weekly readout</span>
      <h4>${escapeHtml(model.summary)}</h4>
      <p>${escapeHtml(dateLabel)} · ${availableSources} connected ${availableSources === 1 ? "area" : "areas"}</p>
    </section>
    <div class="weekly-insights-grid">
      ${model.insights.map((insight) => `
        <article class="weekly-insights-item is-${escapeHtml(insight.tone)}">
          <div class="weekly-insights-item-head">
            <span>${escapeHtml(insight.label)}</span>
            <span class="weekly-insights-change">${changeGlyph(insight)} ${escapeHtml(insight.comparison)}</span>
          </div>
          <strong>${escapeHtml(insight.value)}</strong>
          <p>${escapeHtml(insight.detail)}</p>
        </article>
      `).join("")}
    </div>
    <div class="weekly-insights-footer">
      ${model.strongest ? `
        <section class="weekly-insights-trend is-${escapeHtml(model.strongest.tone)}">
          <span>${escapeHtml(model.strongest.label)}</span>
          <strong>${escapeHtml(model.strongest.text)}</strong>
        </section>
      ` : ""}
      <section class="weekly-insights-watch">
        <span>What to watch</span>
        <ul>${model.watch.map((item) => `<li>${escapeHtml(item.text)}</li>`).join("")}</ul>
      </section>
    </div>
  `;
}

function renderUnavailable(root) {
  root.innerHTML = `
    <div class="weekly-insights-empty is-error">
      <strong>Weekly insights unavailable</strong>
      <span>The tracker APIs did not respond. The widget will try again automatically.</span>
    </div>
  `;
}

export function initWeeklyInsights({
  root = document.getElementById("weekly-insights-root"),
  loader = loadWeeklyInsightSources,
  schedule = true,
  now = () => new Date(),
} = {}) {
  if (!root) return null;
  let destroyed = false;
  root.innerHTML = '<div class="weekly-insights-empty"><span>Reading the last two weeks…</span></div>';

  const refresh = async () => {
    root.setAttribute("aria-busy", "true");
    try {
      const { sources, availableSources } = await loader();
      if (!destroyed) renderModel(root, buildWeeklyInsights(sources, { now: now() }), availableSources);
    } catch {
      if (!destroyed) renderUnavailable(root);
    } finally {
      if (!destroyed) root.setAttribute("aria-busy", "false");
    }
  };
  const onVisibility = () => {
    if (document.visibilityState === "visible") refresh();
  };
  const interval = schedule ? window.setInterval(refresh, REFRESH_INTERVAL_MS) : null;
  if (schedule) document.addEventListener("visibilitychange", onVisibility);
  const refreshPromise = refresh();
  return {
    refresh,
    refreshPromise,
    destroy() {
      destroyed = true;
      if (interval !== null) window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
    },
  };
}

const weeklyInsightsRoot = document.getElementById("weekly-insights-root");
if (weeklyInsightsRoot) initWeeklyInsights({ root: weeklyInsightsRoot });
