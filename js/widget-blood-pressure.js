import { escapeHtml } from "./utils.js";

const STORAGE_KEY = "bloodPressure.entries.v1";
const MAX_VISIBLE_ENTRIES = 5;
const DAY_MS = 24 * 60 * 60 * 1000;
const CHART_WIDTH = 640;
const CHART_HEIGHT = 220;
const CHART_TIME_CLUSTER_GAP = 34;
const CHART_TIME_TICK_COLLISION_GAP = 42;

export const BLOOD_PRESSURE_THRESHOLDS = {
  systolic: [
    { key: "low", max: 89 },
    { key: "normal", min: 90, max: 134 },
    { key: "elevated", min: 135, max: 139 },
    { key: "high", min: 140, max: 159 },
    { key: "very-high", min: 160, max: 179 },
    { key: "urgent", min: 180 },
  ],
  diastolic: [
    { key: "low", max: 59 },
    { key: "normal", min: 60, max: 84 },
    { key: "elevated", min: 85, max: 89 },
    { key: "high", min: 90, max: 99 },
    { key: "very-high", min: 100, max: 119 },
    { key: "urgent", min: 120 },
  ],
  categories: {
    normal: {
      severity: 0,
      label: "w normie dla pomiaru domowego",
      className: "is-normal",
    },
    low: {
      severity: 1,
      label: "niskie",
      className: "is-low",
    },
    elevated: {
      severity: 2,
      label: "lekko podwyższone",
      className: "is-elevated",
    },
    high: {
      severity: 3,
      label: "wysokie",
      className: "is-high",
    },
    "very-high": {
      severity: 4,
      label: "bardzo wysokie",
      className: "is-very-high",
    },
    urgent: {
      severity: 5,
      label: "pilne / powtórz pomiar po kilku minutach; przy objawach alarmowych skontaktuj się z pomocą medyczną",
      className: "is-urgent",
    },
  },
};

export const PULSE_THRESHOLDS = {
  low: { max: 49, label: "niski puls" },
  normal: { min: 50, max: 100, label: "puls w typowym zakresie spoczynkowym" },
  elevated: { min: 101, label: "podwyższony puls w spoczynku" },
};

const STATUS_COLORS = {
  low: "#60a5fa",
  normal: "#22c55e",
  elevated: "#eab308",
  high: "#f97316",
  "very-high": "#ef4444",
  urgent: "#ef4444",
};

const OFFICIAL_THRESHOLD_SOURCE_URL = "https://www.nice.org.uk/guidance/ng136/chapter/recommendations";
const EMERGENCY_THRESHOLD_SOURCE_URL = "https://www.heart.org/en/health-topics/high-blood-pressure/understanding-blood-pressure-readings";
const OFFICIAL_THRESHOLD_ROWS = [
  ["NICE HBPM: poniżej progu", "średnia domowa poniżej 135/85 mmHg"],
  ["NICE HBPM: stage 1", "średnia domowa 135/85-149/94 mmHg"],
  ["NICE HBPM: stage 2", "średnia domowa od 150/95 mmHg"],
  ["Pilne / alarmowe", "około 180/120 mmHg; powtórz i reaguj na objawy alarmowe"],
];

export const MEASUREMENT_TAGS = [
  { id: "before-meds", label: "przed lekami", group: "before-meds" },
  { id: "after-concerta", label: "po Concertcie", group: "after-meds" },
  { id: "after-bupropion", label: "bupropion", group: "after-meds" },
  { id: "pregabalin", label: "pregabalina", group: "after-meds" },
  { id: "coffee", label: "kawa" },
  { id: "nicotine", label: "papieros/nikotyna" },
  { id: "alcohol-24h", label: "alkohol w ostatnich 24h" },
  { id: "stress", label: "stres" },
  { id: "after-exercise", label: "po wysiłku" },
  { id: "rested-5-min", label: "po 5 minutach odpoczynku" },
];

const TAG_LABELS = new Map(MEASUREMENT_TAGS.map((tag) => [tag.id, tag.label]));
const AFTER_MEDS_TAGS = new Set(MEASUREMENT_TAGS
  .filter((tag) => tag.group === "after-meds")
  .map((tag) => tag.id));

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function isInRange(value, range) {
  if (range.min !== undefined && value < range.min) return false;
  if (range.max !== undefined && value > range.max) return false;
  return true;
}

function categoryForValue(value, thresholds) {
  const number = toNumber(value);
  if (number === null) return null;
  const match = thresholds.find((range) => isInRange(number, range));
  return match?.key || null;
}

export function interpretBloodPressure(systolic, diastolic) {
  const systolicKey = categoryForValue(systolic, BLOOD_PRESSURE_THRESHOLDS.systolic);
  const diastolicKey = categoryForValue(diastolic, BLOOD_PRESSURE_THRESHOLDS.diastolic);
  if (!systolicKey || !diastolicKey) return null;

  const categories = BLOOD_PRESSURE_THRESHOLDS.categories;
  const worstKey = [systolicKey, diastolicKey]
    .sort((a, b) => categories[b].severity - categories[a].severity)[0];

  return {
    key: worstKey,
    ...categories[worstKey],
  };
}

export function interpretPulse(pulse) {
  const number = toNumber(pulse);
  if (number === null) return null;
  if (number < 50) return { key: "low", ...PULSE_THRESHOLDS.low };
  if (number <= 100) return { key: "normal", ...PULSE_THRESHOLDS.normal };
  return { key: "elevated", ...PULSE_THRESHOLDS.elevated };
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function todayInputValue(date = new Date()) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDaysToInputDate(day, amount) {
  const date = new Date(`${day || todayInputValue()}T12:00:00`);
  if (Number.isNaN(date.getTime())) return todayInputValue();
  date.setDate(date.getDate() + amount);
  return todayInputValue(date);
}

function timeInputValue(date = new Date()) {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function measurementDate(entry) {
  const date = new Date(`${entry.date || ""}T${entry.time || "00:00"}`);
  if (!Number.isNaN(date.getTime())) return date;
  const fallback = new Date(entry.createdAt || 0);
  return Number.isNaN(fallback.getTime()) ? new Date(0) : fallback;
}

function compareEntriesDesc(a, b) {
  return measurementDate(b).getTime() - measurementDate(a).getTime();
}

export function getVisibleBloodPressureEntries(entries, showHistory = false) {
  return showHistory ? entries : entries.slice(0, MAX_VISIBLE_ENTRIES);
}

function timeToMinutes(time) {
  const [hour, minute] = String(time || "").split(":").map((part) => Number.parseInt(part, 10));
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return 0;
  return Math.max(0, Math.min(1439, hour * 60 + minute));
}

function formatHourLabel(minutes) {
  const clamped = Math.max(0, Math.min(1440, Math.round(minutes)));
  const hour = Math.floor(clamped / 60);
  const minute = clamped % 60;
  return `${pad(hour)}:${pad(minute)}`;
}

function niceHourStep(spanMinutes) {
  if (spanMinutes <= 360) return 60;
  if (spanMinutes <= 720) return 120;
  return 240;
}

function clampChartX(value) {
  return Math.max(34, Math.min(CHART_WIDTH - 34, value));
}

export function getBloodPressureChartTimeLabels(points) {
  if (!points.length) return [];

  const clusters = [];
  points.forEach((point) => {
    const current = clusters[clusters.length - 1];
    const previous = current?.[current.length - 1];
    if (previous && point.x - previous.x <= CHART_TIME_CLUSTER_GAP) {
      current.push(point);
      return;
    }
    clusters.push([point]);
  });

  return clusters.map((cluster) => {
    const first = cluster[0];
    const last = cluster[cluster.length - 1];
    return {
      label: cluster.length > 1 ? `${first.entry.time}-${last.entry.time}` : first.entry.time,
      x: clampChartX((first.x + last.x) / 2),
      isCluster: cluster.length > 1,
    };
  });
}

export function getBloodPressureDailyChartModel(entries, day) {
  const dayEntries = entries
    .filter((entry) => entry.date === day)
    .slice()
    .sort((a, b) => timeToMinutes(a.time) - timeToMinutes(b.time));

  if (!dayEntries.length) {
    return {
      day,
      entries: [],
      points: [],
      timeLabels: [],
      ticks: [],
      yMin: 60,
      yMax: 180,
    };
  }

  const minutes = dayEntries.map((entry) => timeToMinutes(entry.time));
  const rawMinMinute = Math.min(...minutes);
  const rawMaxMinute = Math.max(...minutes);
  const minMinute = rawMinMinute === rawMaxMinute
    ? Math.max(0, rawMinMinute - 120)
    : Math.max(0, Math.floor((rawMinMinute - 45) / 60) * 60);
  const maxMinute = rawMinMinute === rawMaxMinute
    ? Math.min(1440, rawMaxMinute + 120)
    : Math.min(1440, Math.ceil((rawMaxMinute + 45) / 60) * 60);
  const spanMinutes = Math.max(60, maxMinute - minMinute);

  const values = dayEntries.flatMap((entry) => [entry.systolic, entry.diastolic]);
  let yMin = Math.max(40, Math.floor((Math.min(...values) - 10) / 10) * 10);
  let yMax = Math.ceil((Math.max(...values) + 10) / 10) * 10;
  if (yMax - yMin < 20) {
    yMax += 10;
    yMin = Math.max(40, yMin - 10);
  }
  const safeYSpan = yMax - yMin;

  const padX = 42;
  const padRight = 34;
  const padTop = 18;
  const padBottom = 42;
  const plotWidth = CHART_WIDTH - padX - padRight;
  const plotHeight = CHART_HEIGHT - padTop - padBottom;
  const xForMinute = (minute) => padX + ((minute - minMinute) / spanMinutes) * plotWidth;
  const yForValue = (value) => padTop + ((yMax - value) / safeYSpan) * plotHeight;

  const tickStep = niceHourStep(spanMinutes);
  const firstTick = Math.ceil(minMinute / tickStep) * tickStep;
  const ticks = [];
  for (let minute = firstTick; minute <= maxMinute; minute += tickStep) {
    ticks.push({
      minute,
      x: xForMinute(minute),
      label: formatHourLabel(minute),
    });
  }
  if (!ticks.length || ticks[0].minute > minMinute + 30) {
    ticks.unshift({ minute: minMinute, x: xForMinute(minMinute), label: formatHourLabel(minMinute) });
  }
  if (ticks[ticks.length - 1]?.minute < maxMinute - 30) {
    ticks.push({ minute: maxMinute, x: xForMinute(maxMinute), label: formatHourLabel(maxMinute) });
  }

  const points = dayEntries.map((entry) => {
    const minute = timeToMinutes(entry.time);
    const status = interpretBloodPressure(entry.systolic, entry.diastolic);
    return {
      entry,
      minute,
      x: xForMinute(minute),
      systolicY: yForValue(entry.systolic),
      diastolicY: yForValue(entry.diastolic),
      statusClass: status?.className || "",
      statusLabel: status?.label || "",
      statusColor: STATUS_COLORS[status?.key] || "#94a3b8",
    };
  });
  const timeLabels = getBloodPressureChartTimeLabels(points);

  return {
    day,
    entries: dayEntries,
    points,
    timeLabels,
    ticks,
    yLabels: [
      { value: yMax, y: yForValue(yMax), label: String(yMax) },
      { value: Math.round((yMin + yMax) / 2), y: yForValue(Math.round((yMin + yMax) / 2)), label: String(Math.round((yMin + yMax) / 2)) },
      { value: yMin, y: yForValue(yMin), label: String(yMin) },
    ],
    yMin,
    yMax,
    padX,
    padRight,
    padTop,
    padBottom,
    plotRight: CHART_WIDTH - padRight,
    plotBottom: CHART_HEIGHT - padBottom,
  };
}

function roundAverage(value) {
  if (!Number.isFinite(value)) return null;
  return Math.round(value * 10) / 10;
}

function averageGroup(entries) {
  if (!entries.length) {
    return { count: 0, systolic: null, diastolic: null, pulse: null };
  }
  const sums = entries.reduce((acc, entry) => {
    acc.systolic += entry.systolic;
    acc.diastolic += entry.diastolic;
    acc.pulse += entry.pulse;
    return acc;
  }, { systolic: 0, diastolic: 0, pulse: 0 });

  return {
    count: entries.length,
    systolic: roundAverage(sums.systolic / entries.length),
    diastolic: roundAverage(sums.diastolic / entries.length),
    pulse: roundAverage(sums.pulse / entries.length),
  };
}

export function getSevenDayAverages(entries, now = new Date()) {
  const end = now.getTime();
  const start = end - (7 * DAY_MS);
  const recent = entries.filter((entry) => {
    const time = measurementDate(entry).getTime();
    return time >= start && time <= end;
  });

  return {
    all: averageGroup(recent),
    beforeMeds: averageGroup(recent.filter((entry) => {
      const tags = Array.isArray(entry.tags) ? entry.tags : [];
      return tags.includes("before-meds");
    })),
    afterMeds: averageGroup(recent.filter((entry) => {
      const tags = Array.isArray(entry.tags) ? entry.tags : [];
      return tags.some((tag) => AFTER_MEDS_TAGS.has(tag));
    })),
  };
}

function normalizeEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const systolic = toNumber(raw.systolic);
  const diastolic = toNumber(raw.diastolic);
  const pulse = toNumber(raw.pulse);
  if (!raw.date || !raw.time || systolic === null || diastolic === null || pulse === null) return null;
  return {
    id: String(raw.id || `bp-${Date.now()}-${Math.random().toString(16).slice(2)}`),
    date: String(raw.date).slice(0, 10),
    time: String(raw.time).slice(0, 5),
    systolic,
    diastolic,
    pulse,
    note: String(raw.note || "").trim(),
    tags: Array.isArray(raw.tags)
      ? raw.tags.filter((tag) => TAG_LABELS.has(tag))
      : [],
    createdAt: String(raw.createdAt || new Date().toISOString()),
  };
}

function loadEntries() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(parsed)
      ? parsed.map(normalizeEntry).filter(Boolean).sort(compareEntriesDesc)
      : [];
  } catch {
    return [];
  }
}

function saveEntries(entries) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
}

function setDefaultDateTime(root, { force = false } = {}) {
  const now = new Date();
  const date = root.querySelector("#bp-date");
  const time = root.querySelector("#bp-time");
  if (date && (force || !date.value)) date.value = todayInputValue(now);
  if (time && (force || !time.value)) time.value = timeInputValue(now);
}

function tagLabel(id) {
  return TAG_LABELS.get(id) || id;
}

function averageText(group) {
  if (!group.count) return "-";
  return `${group.systolic}/${group.diastolic}, puls ${group.pulse}`;
}

function renderAverageCard(label, group) {
  const status = group.count
    ? interpretBloodPressure(group.systolic, group.diastolic)
    : null;
  const card = document.createElement("div");
  card.className = `blood-pressure-average ${status?.className || ""}`;

  const title = document.createElement("span");
  title.textContent = label;
  const value = document.createElement("strong");
  value.textContent = averageText(group);
  const count = document.createElement("em");
  count.textContent = group.count ? `${group.count} pom.` : "brak danych";

  card.append(title, value, count);
  return card;
}

function renderDailyChart(entries, day, { thresholdLegendOpen = false } = {}) {
  const model = getBloodPressureDailyChartModel(entries, day);
  if (!model.points.length) {
    return `
      <div class="blood-pressure-chart-empty">
        Brak pomiarów dla ${escapeHtml(day || "wybranego dnia")}.
      </div>
    `;
  }

  const ticksWithVisibleLabels = model.ticks.map((tick) => ({
    ...tick,
    showLabel: !model.timeLabels.some((label) => Math.abs(label.x - tick.x) < CHART_TIME_TICK_COLLISION_GAP),
  }));
  const segments = model.points.slice(1).map((point, index) => ({
    index,
    from: model.points[index],
    to: point,
    systolicGradientId: `bp-systolic-gradient-${index}`,
    diastolicGradientId: `bp-diastolic-gradient-${index}`,
  }));
  const latest = model.points[model.points.length - 1]?.entry;
  const latestText = latest
    ? `${latest.time} | ${latest.systolic}/${latest.diastolic}, puls ${latest.pulse}`
    : "";
  const statusLegend = [
    ["is-normal", "w normie"],
    ["is-elevated", "lekko podwyższone"],
    ["is-high", "wysokie"],
    ["is-very-high", "bardzo wysokie / pilne"],
    ["is-low", "niskie"],
  ];

  return `
    <div class="blood-pressure-chart-meta">
      <span>${escapeHtml(latestText)}</span>
      <span>${model.points.length} pom.</span>
    </div>
    <div class="blood-pressure-chart-wrap">
      <svg class="blood-pressure-chart-svg" viewBox="0 0 ${CHART_WIDTH} ${CHART_HEIGHT}" role="img" aria-label="Dzienny wykres ciśnienia dla ${escapeHtml(day)}">
        ${model.yLabels.map((label) => `
          <line class="blood-pressure-chart-grid" x1="${model.padX}" y1="${label.y.toFixed(1)}" x2="${model.plotRight}" y2="${label.y.toFixed(1)}" />
          <text class="blood-pressure-chart-scale" x="${model.plotRight + 8}" y="${label.y.toFixed(1)}" dominant-baseline="middle">${escapeHtml(label.label)}</text>
        `).join("")}
        ${ticksWithVisibleLabels.map((tick) => `
          <line class="blood-pressure-chart-hour-line" x1="${tick.x.toFixed(1)}" y1="${model.padTop}" x2="${tick.x.toFixed(1)}" y2="${model.plotBottom}" />
          ${tick.showLabel ? `<text class="blood-pressure-chart-label" x="${tick.x.toFixed(1)}" y="${CHART_HEIGHT - 10}" text-anchor="middle">${escapeHtml(tick.label)}</text>` : ""}
        `).join("")}
        ${segments.length ? `
          <defs>
            ${segments.map((segment) => `
              <linearGradient id="${segment.systolicGradientId}" gradientUnits="userSpaceOnUse" x1="${segment.from.x.toFixed(1)}" y1="${segment.from.systolicY.toFixed(1)}" x2="${segment.to.x.toFixed(1)}" y2="${segment.to.systolicY.toFixed(1)}">
                <stop offset="0%" stop-color="${segment.from.statusColor}" />
                <stop offset="100%" stop-color="${segment.to.statusColor}" />
              </linearGradient>
              <linearGradient id="${segment.diastolicGradientId}" gradientUnits="userSpaceOnUse" x1="${segment.from.x.toFixed(1)}" y1="${segment.from.diastolicY.toFixed(1)}" x2="${segment.to.x.toFixed(1)}" y2="${segment.to.diastolicY.toFixed(1)}">
                <stop offset="0%" stop-color="${segment.from.statusColor}" />
                <stop offset="100%" stop-color="${segment.to.statusColor}" />
              </linearGradient>
            `).join("")}
          </defs>
          ${segments.map((segment) => `
            <line class="blood-pressure-chart-line is-systolic" x1="${segment.from.x.toFixed(1)}" y1="${segment.from.systolicY.toFixed(1)}" x2="${segment.to.x.toFixed(1)}" y2="${segment.to.systolicY.toFixed(1)}" style="stroke:url(#${segment.systolicGradientId})" />
            <line class="blood-pressure-chart-line is-diastolic" x1="${segment.from.x.toFixed(1)}" y1="${segment.from.diastolicY.toFixed(1)}" x2="${segment.to.x.toFixed(1)}" y2="${segment.to.diastolicY.toFixed(1)}" style="stroke:url(#${segment.diastolicGradientId})" />
          `).join("")}
        ` : ""}
        ${model.points.map((point, index) => `
          <g
            class="blood-pressure-chart-point ${point.statusClass}"
            tabindex="0"
            aria-label="${escapeHtml(`${point.entry.time}, ${point.entry.systolic}/${point.entry.diastolic}, puls ${point.entry.pulse}, ${point.statusLabel}`)}"
            data-bp-date="${escapeHtml(point.entry.date)}"
            data-bp-time="${escapeHtml(point.entry.time)}"
            data-bp-reading="${escapeHtml(`${point.entry.systolic}/${point.entry.diastolic}`)}"
            data-bp-pulse="${escapeHtml(String(point.entry.pulse))}"
            data-bp-status="${escapeHtml(point.statusLabel)}"
            data-bp-tags="${escapeHtml(point.entry.tags.map(tagLabel).join(", "))}"
            data-bp-note="${escapeHtml(point.entry.note || "")}"
          >
            <title>${escapeHtml(`${point.entry.time} | ${point.entry.systolic}/${point.entry.diastolic}, puls ${point.entry.pulse} | ${point.statusLabel}`)}</title>
            <line class="blood-pressure-chart-point-guide" x1="${point.x.toFixed(1)}" y1="${point.systolicY.toFixed(1)}" x2="${point.x.toFixed(1)}" y2="${point.diastolicY.toFixed(1)}" />
            <circle class="blood-pressure-chart-dot is-systolic" cx="${point.x.toFixed(1)}" cy="${point.systolicY.toFixed(1)}" r="5.2" style="fill:${point.statusColor}" />
            <circle class="blood-pressure-chart-dot is-diastolic" cx="${point.x.toFixed(1)}" cy="${point.diastolicY.toFixed(1)}" r="4.2" style="fill:${point.statusColor}" />
            ${index === model.points.length - 1 ? `<text class="blood-pressure-chart-latest" x="${Math.min(model.plotRight - 8, point.x + 10).toFixed(1)}" y="${Math.max(model.padTop + 12, point.systolicY - 8).toFixed(1)}">${escapeHtml(`${point.entry.systolic}/${point.entry.diastolic}`)}</text>` : ""}
          </g>
        `).join("")}
        ${model.timeLabels.map((label) => `
          <text class="blood-pressure-chart-point-time ${label.isCluster ? "is-cluster" : ""}" x="${label.x.toFixed(1)}" y="${model.plotBottom + 18}" text-anchor="middle">${escapeHtml(label.label)}</text>
        `).join("")}
      </svg>
    </div>
    <div class="blood-pressure-chart-legend" aria-hidden="true">
      <span><i class="is-systolic"></i>większa/górna kropka = skurczowe</span>
      <span><i class="is-diastolic"></i>mniejsza/dolna kropka = rozkurczowe</span>
      <span><i class="is-status-gradient"></i>kolor/gradient = status</span>
      <span><i class="is-guide"></i>odległość = godzina pomiaru</span>
    </div>
    <div class="blood-pressure-status-legend" aria-label="Legenda kolorów statusu">
      <span>Kolor kropek i gradientu:</span>
      ${statusLegend.map(([className, label]) => `<span><i class="${className}"></i>${escapeHtml(label)}</span>`).join("")}
      <button class="blood-pressure-threshold-toggle" type="button" data-action="threshold-legend-toggle" aria-expanded="${thresholdLegendOpen ? "true" : "false"}">${thresholdLegendOpen ? "Ukryj progi" : "Pokaż progi"}</button>
    </div>
    ${thresholdLegendOpen ? `
      <div class="blood-pressure-threshold-legend">
        <strong>Progi z oficjalnych źródeł</strong>
        <div class="blood-pressure-threshold-grid">
          ${OFFICIAL_THRESHOLD_ROWS.map(([label, value]) => `
            <span>${escapeHtml(label)}</span>
            <em>${escapeHtml(value)}</em>
          `).join("")}
        </div>
        <p>
          Źródła: <a href="${OFFICIAL_THRESHOLD_SOURCE_URL}" target="_blank" rel="noopener">NICE NG136</a>
          oraz <a href="${EMERGENCY_THRESHOLD_SOURCE_URL}" target="_blank" rel="noopener">American Heart Association</a>.
          Wartości NICE dotyczą średniej HBPM, a kolor punktu tutaj ocenia pojedynczy wpis.
        </p>
      </div>
    ` : ""}
  `;
}

function ensureBloodPressureTooltip() {
  let tooltip = document.getElementById("blood-pressure-chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "blood-pressure-chart-tooltip";
    tooltip.className = "blood-pressure-chart-tooltip";
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function positionBloodPressureTooltip(tooltip, x, y) {
  const rect = tooltip.getBoundingClientRect();
  const nextX = Math.min(window.innerWidth - rect.width - 12, Math.max(12, x - rect.width / 2));
  const nextY = Math.max(12, y - rect.height - 14);
  tooltip.style.left = `${nextX}px`;
  tooltip.style.top = `${nextY}px`;
}

function bloodPressureTooltipHtml(target) {
  const tags = target.dataset.bpTags || "";
  const note = target.dataset.bpNote || "";
  return `
    <div class="blood-pressure-chart-tooltip-day">${escapeHtml(target.dataset.bpDate || "")} ${escapeHtml(target.dataset.bpTime || "")}</div>
    <div class="blood-pressure-chart-tooltip-reading">${escapeHtml(target.dataset.bpReading || "")}, puls ${escapeHtml(target.dataset.bpPulse || "-")}</div>
    <div class="blood-pressure-chart-tooltip-status">${escapeHtml(target.dataset.bpStatus || "")}</div>
    <div class="blood-pressure-chart-tooltip-meta">Wykres: większa/górna kropka = skurczowe; mniejsza/dolna = rozkurczowe.</div>
    ${tags ? `<div class="blood-pressure-chart-tooltip-meta">Tagi: ${escapeHtml(tags)}</div>` : ""}
    ${note ? `<div class="blood-pressure-chart-tooltip-meta">Notatka: ${escapeHtml(note)}</div>` : ""}
  `;
}

function showBloodPressureTooltip(event) {
  const target = event.currentTarget;
  const tooltip = ensureBloodPressureTooltip();
  tooltip.innerHTML = bloodPressureTooltipHtml(target);
  tooltip.classList.add("is-visible");
  const rect = target.getBoundingClientRect();
  positionBloodPressureTooltip(tooltip, rect.left + rect.width / 2, rect.top + rect.height / 2);
}

function moveBloodPressureTooltip(event) {
  const tooltip = document.getElementById("blood-pressure-chart-tooltip");
  if (!tooltip?.classList.contains("is-visible")) return;
  positionBloodPressureTooltip(tooltip, event.clientX, event.clientY);
}

function hideBloodPressureTooltip() {
  document.getElementById("blood-pressure-chart-tooltip")?.classList.remove("is-visible");
}

function bindBloodPressureChartTooltip(root) {
  root.querySelectorAll(".blood-pressure-chart-point").forEach((point) => {
    point.addEventListener("mouseenter", showBloodPressureTooltip);
    point.addEventListener("mousemove", moveBloodPressureTooltip);
    point.addEventListener("mouseleave", hideBloodPressureTooltip);
    point.addEventListener("focus", showBloodPressureTooltip);
    point.addEventListener("blur", hideBloodPressureTooltip);
  });
}

function createEntryElement(entry, onDelete, onEdit) {
  const status = interpretBloodPressure(entry.systolic, entry.diastolic);
  const pulse = interpretPulse(entry.pulse);
  const article = document.createElement("article");
  article.className = `blood-pressure-entry ${status?.className || ""}`;

  const header = document.createElement("div");
  header.className = "blood-pressure-entry-head";

  const main = document.createElement("strong");
  main.textContent = `[${entry.date} ${entry.time}] ${entry.systolic}/${entry.diastolic}, puls ${entry.pulse}`;

  const actions = document.createElement("div");
  actions.className = "blood-pressure-entry-actions";

  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.className = "blood-pressure-entry-action";
  editButton.textContent = "Edytuj";
  editButton.addEventListener("click", () => onEdit(entry.id));

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "blood-pressure-entry-action blood-pressure-delete";
  deleteButton.textContent = "Usuń";
  deleteButton.addEventListener("click", () => onDelete(entry.id));
  actions.append(editButton, deleteButton);
  header.append(main, actions);

  const statusLine = document.createElement("p");
  statusLine.className = "blood-pressure-status-line";
  statusLine.textContent = `Status: ${status?.label || "-"}`;

  const pulseLine = document.createElement("p");
  pulseLine.className = "blood-pressure-muted-line";
  pulseLine.textContent = `Puls: ${pulse?.label || "-"}`;

  const tagsLine = document.createElement("p");
  tagsLine.className = "blood-pressure-muted-line";
  tagsLine.textContent = `Tagi: ${entry.tags.length ? entry.tags.map(tagLabel).join(", ") : "-"}`;

  const noteLine = document.createElement("p");
  noteLine.className = "blood-pressure-muted-line";
  noteLine.textContent = `Notatka: ${entry.note || "-"}`;

  article.append(header, statusLine, pulseLine, tagsLine, noteLine);
  return article;
}

function csvEscape(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function entriesToCsv(entries) {
  const rows = [
    ["date", "time", "systolic", "diastolic", "pulse", "status", "pulse_status", "tags", "note"],
    ...entries.map((entry) => [
      entry.date,
      entry.time,
      entry.systolic,
      entry.diastolic,
      entry.pulse,
      interpretBloodPressure(entry.systolic, entry.diastolic)?.label || "",
      interpretPulse(entry.pulse)?.label || "",
      entry.tags.map(tagLabel).join("|"),
      entry.note,
    ]),
  ];
  return rows.map((row) => row.map(csvEscape).join(",")).join("\n");
}

function downloadFile(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function renderPreview(root) {
  const preview = root.querySelector("#bp-preview");
  if (!preview) return;
  const systolic = root.querySelector("#bp-systolic")?.value;
  const diastolic = root.querySelector("#bp-diastolic")?.value;
  const pulse = root.querySelector("#bp-pulse")?.value;
  const status = interpretBloodPressure(systolic, diastolic);
  const pulseStatus = interpretPulse(pulse);
  if (!status && !pulseStatus) {
    preview.textContent = "Wpisz wynik, a interpretacja pojawi się automatycznie.";
    preview.className = "blood-pressure-preview";
    return;
  }
  preview.textContent = [
    status ? `Ciśnienie: ${status.label}` : "",
    pulseStatus ? `Puls: ${pulseStatus.label}` : "",
  ].filter(Boolean).join(" | ");
  preview.className = `blood-pressure-preview ${status?.className || ""}`;
}

function createShell(root) {
  root.innerHTML = `
    <header class="blood-pressure-head header">
      <div class="title" id="blood-pressure-title">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M3 12h4l2-5 4 10 2-5h6"></path>
        </svg>
        <div>
          <div>Dziennik ciśnienia</div>
          <div class="dashboard-widget-subtitle">Pomiar domowy</div>
        </div>
      </div>
      <div class="blood-pressure-actions">
        <button class="card-cta" type="button" data-action="export-json">JSON</button>
        <button class="card-cta" type="button" data-action="export-csv">CSV</button>
      </div>
    </header>

    <form class="blood-pressure-form" id="bp-form">
      <label><span>Data</span><input id="bp-date" type="date" required></label>
      <label><span>Godzina</span><input id="bp-time" type="time" required></label>
      <label><span>Skurczowe</span><input id="bp-systolic" type="number" min="40" max="260" inputmode="numeric" required></label>
      <label><span>Rozkurczowe</span><input id="bp-diastolic" type="number" min="30" max="180" inputmode="numeric" required></label>
      <label><span>Puls</span><input id="bp-pulse" type="number" min="25" max="240" inputmode="numeric" required></label>
      <label class="blood-pressure-note-field"><span>Notatka</span><textarea id="bp-note" rows="2" placeholder="np. brak papierosów, 4h po lekach"></textarea></label>
      <div class="blood-pressure-tags" aria-label="Tagi pomiaru">
        ${MEASUREMENT_TAGS.map((tag) => `
          <label class="blood-pressure-tag">
            <input type="checkbox" value="${tag.id}">
            <span>${tag.label}</span>
          </label>
        `).join("")}
      </div>
      <div class="blood-pressure-form-footer">
        <p class="blood-pressure-preview" id="bp-preview" aria-live="polite">Wpisz wynik, a interpretacja pojawi się automatycznie.</p>
        <div class="blood-pressure-form-actions">
          <button class="blood-pressure-cancel" id="bp-cancel-edit" type="button" hidden>Anuluj</button>
          <button class="blood-pressure-submit" id="bp-submit" type="submit">Dodaj pomiar</button>
        </div>
      </div>
    </form>

    <section class="blood-pressure-summary" aria-labelledby="bp-summary-title">
      <div class="blood-pressure-section-head">
        <strong id="bp-summary-title">Średnia z ostatnich 7 dni</strong>
        <span id="bp-summary-count"></span>
      </div>
      <div class="blood-pressure-averages" id="bp-averages"></div>
    </section>

    <section class="blood-pressure-chart" aria-labelledby="bp-chart-title">
      <div class="blood-pressure-section-head">
        <strong id="bp-chart-title">Wykres dnia</strong>
        <div class="blood-pressure-chart-nav">
          <button type="button" data-action="chart-prev-day" aria-label="Poprzedni dzień wykresu">‹ Poprzedni dzień</button>
          <span id="bp-chart-day"></span>
          <button type="button" data-action="chart-next-day" aria-label="Następny dzień wykresu">Następny dzień ›</button>
        </div>
      </div>
      <div class="blood-pressure-chart-body" id="bp-daily-chart"></div>
    </section>

    <section class="blood-pressure-list-section" aria-labelledby="bp-list-title">
      <div class="blood-pressure-section-head">
        <strong id="bp-list-title">Ostatnie pomiary</strong>
        <span id="bp-list-count"></span>
      </div>
      <div class="blood-pressure-list" id="bp-list"></div>
      <p class="blood-pressure-empty" id="bp-empty">Brak zapisanych pomiarów.</p>
      <button class="blood-pressure-history-toggle" id="bp-history-toggle" type="button" hidden>Pokaż historię</button>
    </section>
  `;
}

function initBloodPressureWidget(root) {
  createShell(root);
  setDefaultDateTime(root, { force: true });

  let entries = loadEntries();
  let showHistory = false;
  let editingId = null;
  let autoDateTime = true;
  let thresholdLegendOpen = false;
  const form = root.querySelector("#bp-form");
  const dateInput = root.querySelector("#bp-date");
  const timeInput = root.querySelector("#bp-time");
  const submitButton = root.querySelector("#bp-submit");
  const cancelEditButton = root.querySelector("#bp-cancel-edit");
  const list = root.querySelector("#bp-list");
  const empty = root.querySelector("#bp-empty");
  const averages = root.querySelector("#bp-averages");
  const summaryCount = root.querySelector("#bp-summary-count");
  const chart = root.querySelector("#bp-daily-chart");
  const chartDay = root.querySelector("#bp-chart-day");
  const listCount = root.querySelector("#bp-list-count");
  const historyToggle = root.querySelector("#bp-history-toggle");

  function syncLiveDateTime() {
    if (!autoDateTime || editingId) return;
    setDefaultDateTime(root, { force: true });
  }

  function resetFormToAddMode() {
    editingId = null;
    autoDateTime = true;
    form.reset();
    setDefaultDateTime(root, { force: true });
    if (submitButton) submitButton.textContent = "Dodaj pomiar";
    if (cancelEditButton) cancelEditButton.hidden = true;
    renderPreview(root);
  }

  function setEditMode(id) {
    const entry = entries.find((item) => item.id === id);
    if (!entry) return;
    editingId = id;
    autoDateTime = false;
    if (dateInput) dateInput.value = entry.date;
    if (timeInput) timeInput.value = entry.time;
    root.querySelector("#bp-systolic").value = entry.systolic;
    root.querySelector("#bp-diastolic").value = entry.diastolic;
    root.querySelector("#bp-pulse").value = entry.pulse;
    root.querySelector("#bp-note").value = entry.note || "";
    root.querySelectorAll(".blood-pressure-tag input").forEach((input) => {
      input.checked = entry.tags.includes(input.value);
    });
    if (submitButton) submitButton.textContent = "Zapisz zmiany";
    if (cancelEditButton) cancelEditButton.hidden = false;
    renderPreview(root);
  }

  function render() {
    entries = entries.slice().sort(compareEntriesDesc);
    saveEntries(entries);

    const averageData = getSevenDayAverages(entries);
    averages.replaceChildren(
      renderAverageCard("Wszystkie", averageData.all),
      renderAverageCard("Przed lekami", averageData.beforeMeds),
      renderAverageCard("Po lekach", averageData.afterMeds),
    );
    summaryCount.textContent = averageData.all.count ? `${averageData.all.count} pom.` : "brak danych";
    const selectedChartDay = dateInput?.value || todayInputValue();
    if (chartDay) chartDay.textContent = selectedChartDay;
    if (chart) chart.innerHTML = renderDailyChart(entries, selectedChartDay, { thresholdLegendOpen });
    bindBloodPressureChartTooltip(root);
    listCount.textContent = entries.length
      ? (showHistory ? `${entries.length} razem` : `ostatnie ${Math.min(entries.length, MAX_VISIBLE_ENTRIES)} z ${entries.length}`)
      : "";

    const visibleEntries = getVisibleBloodPressureEntries(entries, showHistory);
    list.replaceChildren(...visibleEntries.map((entry) => createEntryElement(entry, (id) => {
      entries = entries.filter((item) => item.id !== id);
      if (editingId === id) resetFormToAddMode();
      render();
    }, setEditMode)));
    empty.hidden = entries.length > 0;
    historyToggle.hidden = entries.length <= MAX_VISIBLE_ENTRIES;
    historyToggle.textContent = showHistory ? "Ukryj historię" : "Pokaż historię";
    renderPreview(root);
  }

  form.addEventListener("input", () => renderPreview(root));
  [dateInput, timeInput].forEach((input) => {
    input?.addEventListener("focus", () => {
      autoDateTime = false;
    });
    input?.addEventListener("input", () => {
      autoDateTime = false;
    });
  });
  dateInput?.addEventListener("input", render);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const entry = normalizeEntry({
      id: editingId || `bp-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      date: root.querySelector("#bp-date")?.value,
      time: root.querySelector("#bp-time")?.value,
      systolic: root.querySelector("#bp-systolic")?.value,
      diastolic: root.querySelector("#bp-diastolic")?.value,
      pulse: root.querySelector("#bp-pulse")?.value,
      note: root.querySelector("#bp-note")?.value,
      tags: Array.from(root.querySelectorAll(".blood-pressure-tag input:checked")).map((input) => input.value),
      createdAt: new Date().toISOString(),
    });
    if (!entry) return;

    if (editingId) {
      entries = entries.map((item) => item.id === editingId ? { ...entry, createdAt: item.createdAt } : item);
    } else {
      entries = [entry, ...entries];
    }
    resetFormToAddMode();
    render();
  });

  root.addEventListener("click", (event) => {
    const action = event.target?.dataset?.action;
    if (action === "export-json") {
      downloadFile("blood-pressure-measurements.json", JSON.stringify(entries, null, 2), "application/json");
    }
    if (action === "export-csv") {
      downloadFile("blood-pressure-measurements.csv", entriesToCsv(entries), "text/csv;charset=utf-8");
    }
    if (action === "chart-prev-day" || action === "chart-next-day") {
      autoDateTime = false;
      if (dateInput) {
        dateInput.value = addDaysToInputDate(dateInput.value, action === "chart-prev-day" ? -1 : 1);
      }
      render();
    }
    if (action === "threshold-legend-toggle") {
      thresholdLegendOpen = !thresholdLegendOpen;
      render();
    }
  });
  cancelEditButton?.addEventListener("click", resetFormToAddMode);
  historyToggle?.addEventListener("click", () => {
    showHistory = !showHistory;
    render();
  });

  const liveClockTimer = window.setInterval(syncLiveDateTime, 1000);
  window.addEventListener("pagehide", () => window.clearInterval(liveClockTimer), { once: true });
  render();
}

if (typeof document !== "undefined") {
  const root = document.getElementById("blood-pressure-root");
  if (root) initBloodPressureWidget(root);
}
