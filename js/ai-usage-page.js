import { fetchAiUsage } from "./ai-usage-api.js";
import {
  aggregateBurnHistory,
  buildQuotaSeries,
  estimateExhaustion,
  sessionRate,
  simulatePlans,
} from "./ai-usage-analytics.js";

const POLL_MS = 60_000;
const COLORS = { fiveHour: "#7dd3fc", weekly: "#a78bfa" };
const RANGE_LABELS = { 5: "5 hours", 24: "24 hours", 168: "7 days" };
const RISK_LABELS = {
  safe_until_reset: "SAFE UNTIL RESET",
  at_risk: "AT RISK",
  likely_to_hit_limit: "LIKELY TO HIT LIMIT",
  not_enough_data: "NOT ENOUGH DATA",
};

let data = null;
let pollTimer = 0;
let countdownTimer = 0;

const elements = {
  lastSync: document.getElementById("ai-page-last-sync"),
  providerSummary: document.getElementById("ai-page-provider-summary"),
  refresh: document.getElementById("ai-page-refresh"),
  error: document.getElementById("ai-page-error"),
  summary: document.getElementById("ai-page-summary"),
  exhaustion: document.getElementById("ai-page-exhaustion"),
  quotaProvider: document.getElementById("ai-page-quota-provider"),
  quotaWindow: document.getElementById("ai-page-quota-window"),
  quotaRange: document.getElementById("ai-page-quota-range"),
  quotaChart: document.getElementById("ai-page-quota-chart"),
  quotaLegend: document.getElementById("ai-page-quota-legend"),
  burnProvider: document.getElementById("ai-page-burn-provider"),
  burnRange: document.getElementById("ai-page-burn-range"),
  burnSummary: document.getElementById("ai-page-burn-summary"),
  burnChart: document.getElementById("ai-page-burn-chart"),
  plans: document.getElementById("ai-page-plans"),
  sessions: document.getElementById("ai-page-sessions"),
  history: document.getElementById("ai-page-history"),
  historyCount: document.getElementById("ai-page-history-count"),
};

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, digits = 1) {
  const number = finite(value);
  if (number == null) return "—";
  return Number.isInteger(number) ? String(number) : number.toFixed(digits);
}

function formatPercent(value, suffix = "") {
  const number = finite(value);
  return number == null ? "—" : `${formatNumber(number)}%${suffix}`;
}

function formatDuration(seconds) {
  const totalMinutes = Math.max(0, Math.round((finite(seconds) || 0) / 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h${minutes ? ` ${minutes}m` : ""}` : `${minutes}m`;
}

function formatActiveHours(hours) {
  if (!Number.isFinite(hours)) return "Not enough data";
  if (hours < 1) return `~${Math.max(1, Math.round(hours * 60))}m active use left`;
  if (hours < 24) {
    const whole = Math.floor(hours);
    const minutes = Math.round((hours - whole) * 60 / 5) * 5;
    return `~${whole}h${minutes ? ` ${minutes}m` : ""} active use left`;
  }
  return `~${Math.round(hours)}h active use left`;
}

function formatDateTime(value, date = false) {
  const timestamp = Date.parse(value || "");
  if (!Number.isFinite(timestamp)) return "—";
  return new Intl.DateTimeFormat("en-GB", date
    ? { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" }).format(timestamp);
}

function formatCountdown(value, status, now = Date.now()) {
  if (!["connected", "stale"].includes(String(status || "").toLowerCase())) return "—";
  const resetAt = Date.parse(value || "");
  if (!Number.isFinite(resetAt)) return "—";
  const remaining = resetAt - now;
  if (remaining <= 0) return "Resetting…";
  const seconds = Math.floor(remaining / 1000);
  if (seconds < 600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

function quotaState(value) {
  const number = finite(value);
  if (number == null) return "unavailable";
  if (number >= 80) return "healthy";
  if (number >= 50) return "normal";
  if (number >= 25) return "warning";
  return "critical";
}

function providerKey(item) {
  return `${item.provider}:${item.group}`;
}

function providerByKey(key) {
  return data?.providers?.find((item) => providerKey(item) === key) || data?.providers?.[0] || null;
}

function providerLabel(provider, group) {
  return data?.providers?.find((item) => item.provider === provider && item.group === group)?.label
    || (group === "main" ? "Codex" : group === "gemini" ? "Gemini" : "Claude / GPT");
}

function planChangesFor(item) {
  return (data?.config?.planChanges || []).filter((change) => (
    change.provider === item?.provider && change.group === item?.group
  ));
}

function currentPlanChange(item) {
  return planChangesFor(item)
    .filter((change) => Date.parse(change.activatedAt || "") <= Date.now())
    .sort((left, right) => Date.parse(right.activatedAt) - Date.parse(left.activatedAt))[0] || null;
}

function concisePlanName(value) {
  return String(value || "").replace(/^ChatGPT\s+/i, "") || "current plan";
}

function statusBadge(status) {
  const normalized = String(status || "unavailable").toLowerCase();
  return `<span class="ai-page-status" data-status="${escapeHtml(normalized)}">${escapeHtml(normalized.replaceAll("_", " "))}</span>`;
}

function resetMarkup(item, windowKey) {
  return `<time data-ai-page-reset data-provider="${escapeHtml(item.provider)}" data-group="${escapeHtml(item.group)}" data-window="${escapeHtml(windowKey)}">${escapeHtml(formatCountdown(item?.[windowKey]?.resetAt, item.status))}</time>`;
}

function renderWindow(item, windowKey, label) {
  const remaining = finite(item?.[windowKey]?.remaining);
  const width = remaining == null ? 0 : Math.max(0, Math.min(100, remaining));
  return `<div class="ai-page-window" data-state="${quotaState(remaining)}">
    <span>${escapeHtml(label)}</span>
    <strong>${formatPercent(remaining)} <small>remaining</small></strong>
    <div class="ai-page-window-bar"><i style="width:${width}%"></i></div>
    <em>Resets in ${resetMarkup(item, windowKey)}</em>
  </div>`;
}

function renderHeader() {
  const providers = data?.providers || [];
  const connected = providers.filter((item) => item.status === "connected").length;
  const stale = providers.filter((item) => item.status === "stale").length;
  const unavailable = providers.length - connected - stale;
  const latest = providers
    .map((item) => Date.parse(item.updatedAt || ""))
    .filter(Number.isFinite)
    .sort((left, right) => right - left)[0];
  elements.lastSync.textContent = Number.isFinite(latest) ? formatDateTime(new Date(latest).toISOString()) : "—";
  elements.providerSummary.textContent = [
    `${connected} connected`,
    stale ? `${stale} stale` : "",
    unavailable ? `${unavailable} unavailable` : "",
  ].filter(Boolean).join(" · ");
}

function renderSummary() {
  elements.summary.innerHTML = (data?.providers || []).map((item) => {
    const today = item.stats?.today || {};
    const currentFiveHour = Math.min(100, Math.max(0, Number(item.burn?.currentWindow?.fiveHour || 0)));
    const fiveHourConsumedToday = Math.max(0, Number(today.fiveHour || 0));
    const codexValue = item.provider === "codex"
      ? `<div><span>Quota value today</span><strong>~$${Number(item.quotaValue?.today?.usd || 0).toFixed(2)} / ~${Number(item.quotaValue?.today?.pln || 0).toFixed(2)} zł</strong></div>`
      : "";
    return `<article class="ai-page-provider-card">
      <div class="ai-page-card-head"><h3>${escapeHtml(item.label)}</h3>${statusBadge(item.status)}</div>
      <div class="ai-page-window-grid">
        ${renderWindow(item, "fiveHour", "5h")}
        ${renderWindow(item, "weekly", "Week")}
      </div>
      <div class="ai-page-provider-meta">
        <div><span>Weekly consumed today</span><strong>${formatPercent(today.weekly, " used")}</strong></div>
        <div><span>Active today</span><strong>${formatDuration(today.activeSeconds)}</strong></div>
        <div><span>Current 5h window</span><strong>${formatPercent(currentFiveHour, " used")}</strong></div>
        <div><span>5h consumed today</span><strong>${formatPercent(fiveHourConsumedToday, " used")}${fiveHourConsumedToday > 100 ? ` · ${formatNumber(fiveHourConsumedToday / 100)}× quota` : ""}</strong></div>
        ${codexValue}
      </div>
    </article>`;
  }).join("");
}

function exhaustionWindow(item, windowKey, label) {
  const planChange = item?.provider === "codex" ? currentPlanChange(item) : null;
  const rate = sessionRate(item, data?.sessions, windowKey, {
    since: planChange?.activatedAt || (item?.provider === "codex" ? data?.config?.planActivatedAt : null),
  });
  const estimate = estimateExhaustion({
    remaining: item?.[windowKey]?.remaining,
    burnPercent: rate.burnPercent,
    activeSeconds: rate.activeSeconds,
    sampleCount: rate.sampleCount,
    resetAt: item?.[windowKey]?.resetAt,
  });
  const confidence = estimate.confidence === "not_enough_data"
    ? "not enough data"
    : `${estimate.confidence} confidence`;
  const paceScope = planChange
    ? `${concisePlanName(planChange.toPlanName)} only · ${rate.sampleCount} post-upgrade ${rate.sampleCount === 1 ? "session" : "sessions"}`
    : `${rate.sampleCount} ${rate.sampleCount === 1 ? "session" : "sessions"}`;
  const paceRate = Number.isFinite(estimate.burnPerActiveHour)
    ? `${formatPercent(estimate.burnPerActiveHour, " / active h")} · `
    : "";
  return `<div class="ai-page-exhaustion-window">
    <div><span>${escapeHtml(label)} · ${formatPercent(item?.[windowKey]?.remaining, " remaining")}</span><strong>${escapeHtml(formatActiveHours(estimate.activeHoursLeft))}</strong></div>
    <em data-risk="${escapeHtml(estimate.status)}">${escapeHtml(RISK_LABELS[estimate.status] || RISK_LABELS.not_enough_data)}</em>
    <small>Reset in ${resetMarkup(item, windowKey)} · ${escapeHtml(confidence)}</small>
    <small class="ai-page-pace-scope">Pace: ${escapeHtml(paceRate + paceScope)}</small>
  </div>`;
}

function renderExhaustion() {
  elements.exhaustion.innerHTML = (data?.providers || []).map((item) => `
    <article class="ai-page-exhaustion-card">
      <div class="ai-page-card-head"><h3>${escapeHtml(item.label)}</h3>${statusBadge(item.status)}</div>
      <div class="ai-page-exhaustion-windows">
        ${exhaustionWindow(item, "fiveHour", "5h quota")}
        ${exhaustionWindow(item, "weekly", "Weekly quota")}
      </div>
    </article>`).join("");
}

function updateCountdowns() {
  document.querySelectorAll("[data-ai-page-reset]").forEach((node) => {
    const item = data?.providers?.find((provider) => (
      provider.provider === node.dataset.provider && provider.group === node.dataset.group
    ));
    node.textContent = formatCountdown(item?.[node.dataset.window]?.resetAt, item?.status);
  });
}

function populateProviderSelect(select) {
  const oldValue = select.value;
  select.innerHTML = (data?.providers || []).map((item) => (
    `<option value="${escapeHtml(providerKey(item))}">${escapeHtml(item.label)}</option>`
  )).join("");
  if ([...select.options].some((option) => option.value === oldValue)) select.value = oldValue;
}

function axisTimeLabel(timestamp, rangeHours) {
  return new Intl.DateTimeFormat("en-GB", rangeHours > 24
    ? { weekday: "short", day: "numeric" }
    : { hour: "2-digit", minute: "2-digit" }).format(timestamp);
}

function tooltipAttributes(title, lines, cx, cy, focusable = true) {
  return `${focusable ? 'tabindex="0" ' : ""}data-chart-tooltip data-tooltip-title="${escapeHtml(title)}" data-tooltip-lines="${escapeHtml(lines.join("|"))}" data-cx="${cx.toFixed(2)}" data-cy="${cy.toFixed(2)}"`;
}

function quotaMarkerPoints(entry, maximum = 9) {
  const selected = new Set();
  entry.segments.forEach((segment) => {
    if (segment[0]) selected.add(segment[0]);
    if (segment.at(-1)) selected.add(segment.at(-1));
  });
  const extraSlots = Math.max(0, maximum - selected.size);
  for (let slot = 1; slot <= extraSlots; slot += 1) {
    const index = Math.round(slot * (entry.points.length - 1) / (extraSlots + 1));
    if (entry.points[index]) selected.add(entry.points[index]);
  }
  return selected;
}

function clusterResetMarkers(timestamps, xPosition, minimumGap = 48) {
  const clusters = [];
  [...new Set(timestamps)].sort((left, right) => left - right).forEach((timestamp) => {
    const position = xPosition(timestamp);
    const previous = clusters.at(-1);
    if (!previous || position - previous.lastPosition >= minimumGap) {
      clusters.push({ timestamps: [timestamp], positions: [position], lastPosition: position });
      return;
    }
    previous.timestamps.push(timestamp);
    previous.positions.push(position);
    previous.lastPosition = position;
  });
  return clusters.map((cluster) => ({
    timestamp: cluster.timestamps.at(-1),
    position: cluster.positions.reduce((sum, value) => sum + value, 0) / cluster.positions.length,
  }));
}

function chartGrid({ width, height, pad, maxY = 100, rangeStart, rangeEnd, rangeHours }) {
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const horizontal = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const y = pad.top + ratio * plotHeight;
    const value = maxY - ratio * maxY;
    return `<line class="ai-chart-grid" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"/><text class="ai-chart-axis" x="${pad.left - 10}" y="${y + 4}" text-anchor="end">${formatNumber(value, 0)}%</text>`;
  }).join("");
  const vertical = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const x = pad.left + ratio * plotWidth;
    const timestamp = rangeStart + ratio * (rangeEnd - rangeStart);
    return `<line class="ai-chart-grid" x1="${x}" y1="${pad.top}" x2="${x}" y2="${height - pad.bottom}"/><text class="ai-chart-axis" x="${x}" y="${height - 15}" text-anchor="${index === 0 ? "start" : index === 4 ? "end" : "middle"}">${escapeHtml(axisTimeLabel(timestamp, rangeHours))}</text>`;
  }).join("");
  return horizontal + vertical;
}

function bindChartTooltip(container) {
  const hide = () => container.querySelector(".ai-page-chart-tooltip")?.remove();
  const show = (target) => {
    if (!target?.matches?.("[data-chart-tooltip]")) return;
    hide();
    const svg = target.ownerSVGElement;
    const rect = svg.getBoundingClientRect();
    const tooltip = document.createElement("div");
    tooltip.className = "ai-page-chart-tooltip";
    tooltip.innerHTML = `<strong>${escapeHtml(target.dataset.tooltipTitle)}</strong>${String(target.dataset.tooltipLines || "").split("|").map((line) => `<span>${escapeHtml(line)}</span>`).join("")}`;
    container.appendChild(tooltip);
    const gap = 10;
    const edge = 8;
    const pointLeft = (Number(target.dataset.cx) / 1000) * rect.width;
    const pointTop = (Number(target.dataset.cy) / 340) * rect.height;
    const halfWidth = tooltip.offsetWidth / 2;
    const left = Math.max(edge + halfWidth, Math.min(rect.width - edge - halfWidth, pointLeft));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${pointTop}px`;
    tooltip.classList.toggle("is-below", pointTop - tooltip.offsetHeight - gap < edge);
  };
  container.onpointerover = (event) => show(event.target.closest?.("[data-chart-tooltip]"));
  container.onfocusin = (event) => show(event.target.closest?.("[data-chart-tooltip]"));
  container.onclick = (event) => show(event.target.closest?.("[data-chart-tooltip]"));
  container.onpointerleave = hide;
  container.onfocusout = hide;
}

function renderQuotaChart() {
  const item = providerByKey(elements.quotaProvider.value);
  if (!item) return;
  const rangeHours = Number(elements.quotaRange.value || 24);
  const windows = elements.quotaWindow.value === "both"
    ? ["fiveHour", "weekly"]
    : [elements.quotaWindow.value];
  const series = windows.map((windowKey) => ({
    windowKey,
    ...buildQuotaSeries(data.history, {
      provider: item.provider,
      group: item.group,
      windowKey,
      rangeHours,
      planChanges: data?.config?.planChanges,
    }),
  }));
  if (!series.some((entry) => entry.points.length)) {
    elements.quotaChart.innerHTML = `<div class="ai-page-chart-empty">Not enough history for ${escapeHtml(item.label)} in this range.</div>`;
    elements.quotaLegend.innerHTML = "";
    return;
  }

  const width = 1000;
  const height = 340;
  const pad = { top: 43, right: 22, bottom: 42, left: 54 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const rangeEnd = Date.now();
  const rangeStart = rangeEnd - rangeHours * 3_600_000;
  const x = (timestamp) => pad.left + ((timestamp - rangeStart) / (rangeEnd - rangeStart)) * plotWidth;
  const y = (remaining) => pad.top + (1 - remaining / 100) * plotHeight;
  let chart = chartGrid({ width, height, pad, rangeStart, rangeEnd, rangeHours });
  const resetTimestamps = series.flatMap((entry) => entry.resets.map((point) => point.timestamp));
  clusterResetMarkers(resetTimestamps, x).forEach((marker) => {
    const cx = marker.position;
    const labelX = Math.max(pad.left + 23, Math.min(width - pad.right - 23, cx));
    chart += `<line class="ai-chart-reset" x1="${cx}" y1="${pad.top - 5}" x2="${cx}" y2="${height - pad.bottom}"/>
      <rect class="ai-chart-reset-pill" x="${labelX - 22}" y="8" width="44" height="19" rx="7"/>
      <text class="ai-chart-reset-label" x="${labelX}" y="21" text-anchor="middle">Reset</text>`;
  });
  const visiblePlanChanges = planChangesFor(item)
    .map((change) => ({ ...change, timestamp: Date.parse(change.activatedAt || "") }))
    .filter((change) => Number.isFinite(change.timestamp) && change.timestamp >= rangeStart && change.timestamp <= rangeEnd);
  visiblePlanChanges.forEach((change) => {
    const cx = x(change.timestamp);
    const label = `${concisePlanName(change.toPlanName)} ×${Number(change.quotaMultiplier || 1)}`;
    const labelWidth = 86;
    const labelX = Math.max(pad.left + labelWidth / 2, Math.min(width - pad.right - labelWidth / 2, cx));
    chart += `<line class="ai-chart-plan-change" x1="${cx}" y1="${pad.top - 5}" x2="${cx}" y2="${height - pad.bottom}"/>
      <rect class="ai-chart-plan-change-pill" x="${labelX - labelWidth / 2}" y="8" width="${labelWidth}" height="19" rx="7"/>
      <text class="ai-chart-plan-change-label" x="${labelX}" y="21" text-anchor="middle">${escapeHtml(label)}</text>`;
  });

  series.forEach((entry) => {
    const color = COLORS[entry.windowKey];
    const visibleMarkers = quotaMarkerPoints(entry);
    entry.segments.forEach((segment) => {
      if (segment.length < 2) return;
      const commands = segment.map((point, index) => `${index ? "L" : "M"}${x(point.timestamp).toFixed(2)},${y(point.remaining).toFixed(2)}`);
      chart += `<path class="ai-chart-line" stroke="${color}" d="${commands.join(" ")}"/>`;
    });
    entry.points.forEach((point) => {
      const cx = x(point.timestamp);
      const cy = y(point.remaining);
      const name = entry.windowKey === "fiveHour" ? "5h quota" : "Weekly quota";
      const title = formatDateTime(new Date(point.timestamp).toISOString(), true);
      const lines = [`${item.label} · ${name}`, `${formatPercent(point.remaining, " remaining")}`, `Change: ${formatPercent(point.usedSincePrevious, " used")}`];
      chart += `<circle class="ai-chart-hit" cx="${cx}" cy="${cy}" r="7" ${tooltipAttributes(title, lines, cx, cy, false)}/>`;
      if (!visibleMarkers.has(point)) return;
      chart += `<circle class="ai-chart-point" cx="${cx}" cy="${cy}" r="3" stroke="${color}" ${tooltipAttributes(
        title,
        lines,
        cx,
        cy,
      )}/>`;
    });
  });
  elements.quotaChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(item.label)} quota remaining over ${escapeHtml(RANGE_LABELS[rangeHours])}">${chart}</svg>`;
  elements.quotaLegend.innerHTML = windows.map((windowKey) => `<span><i style="background:${COLORS[windowKey]}"></i>${windowKey === "fiveHour" ? "5h remaining" : "Weekly remaining"}</span>`).join("")
    + (visiblePlanChanges.length ? '<span><i class="is-plan-change"></i>Plan upgrade</span>' : "")
    + `<small>Lines are intentionally split at resets and plan changes.</small>`;
  bindChartTooltip(elements.quotaChart);
}

function renderBurnChart() {
  const item = providerByKey(elements.burnProvider.value);
  if (!item) return;
  const range = elements.burnRange.value || "today";
  const activatedAt = item.provider === "codex" ? Date.parse(data.config?.planActivatedAt || "") : NaN;
  const history = Number.isFinite(activatedAt)
    ? data.history.filter((entry) => Date.parse(entry.checkedAt || entry.updatedAt || "") >= activatedAt)
    : data.history;
  const buckets = aggregateBurnHistory(history, {
    provider: item.provider,
    group: item.group,
    range,
  });
  const totalFive = buckets.reduce((sum, bucket) => sum + bucket.fiveHour, 0);
  const totalWeekly = buckets.reduce((sum, bucket) => sum + bucket.weekly, 0);
  const costUsd = item.provider === "codex" ? totalWeekly / 100 * Number(data.config?.weeklyQuotaUsd || 0) : null;
  const weeklyQuotaPln = Number(
    data.config?.weeklyQuotaPln
      || Number(data.config?.weeklyQuotaUsd || 0) * Number(data.config?.usdPlnRate || 1),
  );
  const costPln = costUsd == null ? null : totalWeekly / 100 * weeklyQuotaPln;
  elements.burnSummary.innerHTML = `
    <span>5h consumed <strong>${formatPercent(totalFive)}</strong></span>
    <span>Weekly consumed <strong>${formatPercent(totalWeekly)}</strong></span>
    ${costUsd == null ? "" : `<span>Quota value <strong>~$${costUsd.toFixed(2)} / ~${costPln.toFixed(2)} zł</strong></span>`}`;

  const width = 1000;
  const height = 340;
  const pad = { top: 25, right: 22, bottom: 42, left: 54 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const maximum = Math.max(25, ...buckets.flatMap((bucket) => [bucket.fiveHour, bucket.weekly]));
  const maxY = Math.ceil(maximum / 25) * 25;
  const rangeStart = buckets[0]?.start || Date.now() - 86_400_000;
  const rangeEnd = buckets.at(-1)?.end || Date.now();
  let chart = chartGrid({ width, height, pad, maxY, rangeStart, rangeEnd, rangeHours: range === "7d" ? 168 : 24 });
  const slot = plotWidth / Math.max(1, buckets.length);
  const barWidth = Math.max(3, Math.min(18, slot * .3));
  buckets.forEach((bucket, index) => {
    const center = pad.left + slot * (index + .5);
    [["fiveHour", -barWidth * .55], ["weekly", barWidth * .55]].forEach(([windowKey, offset]) => {
      const value = bucket[windowKey];
      const barHeight = value / maxY * plotHeight;
      const x = center + offset - barWidth / 2;
      const y = pad.top + plotHeight - barHeight;
      const quotaCost = item.provider === "codex" && windowKey === "weekly"
        ? value / 100 * Number(data.config?.weeklyQuotaUsd || 0)
        : null;
      const label = range === "7d"
        ? new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "short" }).format(bucket.start)
        : `${String(new Date(bucket.start).getHours()).padStart(2, "0")}:00–${String(new Date(bucket.end - 1).getHours()).padStart(2, "0")}:59`;
      const lines = [`${item.label} · ${windowKey === "fiveHour" ? "5h" : "weekly"}`, `${formatPercent(value, " used")}`];
      if (quotaCost != null) lines.push(`Quota value: ~$${quotaCost.toFixed(2)} / ~${(value / 100 * weeklyQuotaPln).toFixed(2)} zł`);
      chart += `<rect class="ai-chart-bar" x="${x}" y="${y}" width="${barWidth}" height="${Math.max(1, barHeight)}" rx="2" fill="${COLORS[windowKey]}" ${tooltipAttributes(label, lines, center, Math.max(pad.top + 8, y))}/>`;
    });
  });
  elements.burnChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(item.label)} usage burn by ${range === "7d" ? "day" : "hour"}">${chart}</svg>`;
  bindChartTooltip(elements.burnChart);
}

function weekProjection(item, planActivatedAt = null) {
  const now = new Date();
  const weekStart = new Date(now);
  const day = (now.getDay() + 6) % 7;
  weekStart.setDate(now.getDate() - day);
  weekStart.setHours(0, 0, 0, 0);
  const activatedTimestamp = Date.parse(planActivatedAt || "");
  const projectionStart = Number.isFinite(activatedTimestamp) && activatedTimestamp > weekStart.getTime()
    ? activatedTimestamp
    : weekStart.getTime();
  const elapsedDays = Math.max(.25, (now.getTime() - projectionStart) / 86_400_000);
  const used = finite(item?.stats?.thisWeek?.weekly);
  return {
    projectedWeeklyUsage: used == null ? null : used / Math.min(1, elapsedDays / 7),
    averageActiveHoursPerDay: Number(item?.stats?.thisWeek?.activeSeconds || 0) / 3600 / elapsedDays,
  };
}

function renderPlans() {
  const codex = data?.providers?.find((item) => item.provider === "codex");
  if (!codex) {
    elements.plans.innerHTML = '<div class="ai-page-chart-empty">Codex data unavailable.</div>';
    return;
  }
  const rate = sessionRate(codex, data.sessions, "weekly", {
    since: data.config?.planActivatedAt,
  });
  const burnPerHour = rate.activeSeconds > 0 ? rate.burnPercent / (rate.activeSeconds / 3600) : null;
  const plans = simulatePlans({
    currentBurnPerActiveHour: burnPerHour,
    currentPlanName: data.config?.planName,
    vatRate: data.config?.vatRate,
    usdPlnRate: data.config?.usdPlnRate,
    ...weekProjection(codex, data.config?.planActivatedAt),
  });
  elements.plans.innerHTML = plans.map((plan) => `<article class="ai-page-plan-card${plan.current ? " is-current" : ""}">
    <div class="ai-page-card-head"><h3>${escapeHtml(plan.name)}</h3>${plan.current ? '<span class="ai-page-current-plan">Current</span>' : ""}</div>
    <div class="ai-page-plan-price"><strong>$${plan.grossMonthlyUsd.toFixed(2)}</strong> <span>gross / month</span><small>~${plan.grossMonthlyPln.toFixed(0)} zł · ${plan.multiplier}× relative quota</small></div>
    <dl>
      <dt>Equivalent burn</dt><dd>${plan.equivalentBurnPerHour == null ? "—" : `~${formatNumber(plan.equivalentBurnPerHour)}% / active h`}</dd>
      <dt>Active capacity</dt><dd>${plan.activeHoursCapacity == null ? "—" : `~${formatNumber(plan.activeHoursCapacity)}h`}</dd>
      <dt>Days at current average</dt><dd>${plan.estimatedDays == null ? "—" : `~${formatNumber(plan.estimatedDays)}d`}</dd>
      <dt>Projected weekly usage</dt><dd>${formatPercent(plan.projectedWeeklyUsage)}</dd>
      <dt>Difference vs current</dt><dd>${plan.current ? "—" : `+$${plan.grossDeltaUsd.toFixed(2)} / ~${plan.grossDeltaPln.toFixed(0)} zł`}</dd>
      <dt>Risk</dt><dd>${escapeHtml(plan.risk)}</dd>
    </dl>
    <p class="ai-page-plan-fit">Current plan fit<strong>${escapeHtml(plan.fit)}</strong></p>
  </article>`).join("");
}

function renderSessions() {
  const sessions = data?.sessions || [];
  elements.sessions.innerHTML = sessions.length ? sessions.map((session) => {
    const start = formatDateTime(session.session_start, true);
    const end = session.status === "active" ? "active" : formatDateTime(session.session_end);
    const value = session.quotaValue
      ? `~$${Number(session.quotaValue.usd || 0).toFixed(2)} / ~${Number(session.quotaValue.pln || 0).toFixed(2)} zł`
      : "—";
    return `<tr><td>${escapeHtml(start)}–${escapeHtml(end)}</td><td>${escapeHtml(providerLabel(session.provider, session.group))}</td><td>${formatDuration(session.duration_seconds)}</td><td>${formatPercent(session.five_hour_burn, " used")}</td><td>${formatPercent(session.weekly_burn, " used")}</td><td>${escapeHtml(value)}</td></tr>`;
  }).join("") : '<tr><td class="ai-page-table-empty" colspan="6">No sessions detected yet.</td></tr>';
}

function compactHistory(history) {
  const lastVisibleState = new Map();
  return (history || []).filter((item) => {
    const providerKey = `${item.provider || ""}:${item.group || ""}`;
    const state = JSON.stringify([
      finite(item.fiveHour?.remaining),
      finite(item.weekly?.remaining),
      item.status || "",
    ]);
    if (lastVisibleState.get(providerKey) === state) return false;
    lastVisibleState.set(providerKey, state);
    return true;
  });
}

function historyTimeline(readings) {
  const changes = (data?.config?.planChanges || []).map((change) => ({
    type: "plan-change",
    timestamp: change.activatedAt,
    ...change,
  }));
  return [
    ...readings.map((item) => ({ type: "reading", timestamp: item.checkedAt, item })),
    ...changes,
  ].sort((left, right) => Date.parse(right.timestamp || "") - Date.parse(left.timestamp || ""));
}

function renderHistory() {
  const allHistory = data?.history || [];
  const compactedHistory = compactHistory(allHistory);
  const timeline = historyTimeline(compactedHistory);
  const history = timeline.slice(0, 40);
  const hiddenUnchanged = allHistory.length - compactedHistory.length;
  if (elements.historyCount) {
    const unchangedText = hiddenUnchanged
      ? ` · ${hiddenUnchanged} unchanged ${hiddenUnchanged === 1 ? "reading" : "readings"} hidden`
      : "";
    const planChangeCount = timeline.length - compactedHistory.length;
    const planText = planChangeCount ? ` · ${planChangeCount} plan change` : "";
    elements.historyCount.textContent = timeline.length > history.length
      ? `Latest ${history.length} of ${timeline.length} events${planText}${unchangedText}`
      : `${history.length} events${planText}${unchangedText}`;
  }
  elements.history.innerHTML = history.length ? history.map((entry) => {
    if (entry.type === "plan-change") {
      return `<tr class="ai-page-history-plan-change">
        <td>${escapeHtml(formatDateTime(entry.activatedAt, true))}</td>
        <td>${escapeHtml(providerLabel(entry.provider, entry.group))}</td>
        <td colspan="2"><strong>Plan upgrade</strong> ${escapeHtml(concisePlanName(entry.fromPlanName))} → ${escapeHtml(concisePlanName(entry.toPlanName))} · weekly quota ×${escapeHtml(entry.quotaMultiplier)}</td>
        <td>PLAN CHANGE</td>
      </tr>`;
    }
    const item = entry.item;
    return `<tr>
      <td>${escapeHtml(formatDateTime(item.checkedAt, true))}</td>
      <td>${escapeHtml(providerLabel(item.provider, item.group))}</td>
      <td>${formatPercent(item.fiveHour?.remaining)}</td>
      <td>${formatPercent(item.weekly?.remaining)}</td>
      <td>${escapeHtml(String(item.status || "").replaceAll("_", " ").toUpperCase())}</td>
    </tr>`;
  }).join("") : '<tr><td class="ai-page-table-empty" colspan="5">No quota changes recorded yet.</td></tr>';
}

function renderAll() {
  renderHeader();
  populateProviderSelect(elements.quotaProvider);
  populateProviderSelect(elements.burnProvider);
  renderSummary();
  renderExhaustion();
  renderQuotaChart();
  renderBurnChart();
  renderPlans();
  renderSessions();
  renderHistory();
  updateCountdowns();
}

async function refresh() {
  elements.refresh.disabled = true;
  try {
    data = await fetchAiUsage(globalThis.fetch, { historyHours: 168, sessionLimit: 100 });
    elements.error.hidden = true;
    renderAll();
    if (!countdownTimer) countdownTimer = window.setInterval(updateCountdowns, 1000);
  } catch (error) {
    elements.error.textContent = `AI Usage could not be loaded: ${error.message || error}`;
    elements.error.hidden = false;
  } finally {
    elements.refresh.disabled = false;
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(refresh, POLL_MS);
  }
}

elements.refresh.addEventListener("click", refresh);
elements.quotaProvider.addEventListener("change", renderQuotaChart);
elements.quotaWindow.addEventListener("change", renderQuotaChart);
elements.quotaRange.addEventListener("change", renderQuotaChart);
elements.burnProvider.addEventListener("change", renderBurnChart);
elements.burnRange.addEventListener("change", renderBurnChart);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
window.addEventListener("beforeunload", () => {
  window.clearTimeout(pollTimer);
  window.clearInterval(countdownTimer);
}, { once: true });

refresh();
