import { fetchAiUsage } from "./ai-usage-api.js";
import { addDashboardNotification } from "./dashboard-notifications-store.js";

const POLL_MS = 60_000;
const RESET_BASELINES_KEY = "aiUsage.resetBaselines.v1";
const root = document.querySelector("#ai-usage-root");
const card = document.querySelector("#ai-usage-card");
const detailButton = document.querySelector("#ai-usage-details");
let state = null;
let timer = 0;
let countdownTimer = 0;

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function formatPercent(value) {
  if (!Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  return `${Number.isInteger(number) ? number : number.toFixed(1)}%`;
}

function formatBurn(value) {
  const number = Math.abs(Number(value || 0));
  const formatted = Number.isInteger(number) ? number : number.toFixed(1);
  return `${formatted}% used`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return "0m";
  const minutes = Math.max(1, Math.round(Number(seconds) / 60));
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours ? `${hours}h${rest ? ` ${rest}m` : ""}` : `${rest}m`;
}

function formatResetCountdown(value, providerStatus, now = Date.now()) {
  const normalizedStatus = String(providerStatus || "unavailable").toLowerCase();
  if (["unavailable", "error", "not_logged_in"].includes(normalizedStatus) || !value) return "—";
  const resetAt = Date.parse(value);
  if (!Number.isFinite(resetAt)) return "—";

  const remainingMs = resetAt - now;
  if (remainingMs <= 0) return "Resetting…";

  const totalSeconds = Math.floor(remainingMs / 1000);
  if (totalSeconds < 10 * 60) {
    return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
  }

  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${totalMinutes}m`;

  const totalHours = Math.floor(totalMinutes / 60);
  if (totalHours < 24) return `${totalHours}h ${totalMinutes % 60}m`;
  return `${Math.floor(totalHours / 24)}d ${totalHours % 24}h`;
}

function countdownTime(item, windowKey) {
  const value = item?.[windowKey]?.resetAt;
  return `<time data-ai-usage-countdown data-provider="${escapeHtml(item?.provider)}" data-group="${escapeHtml(item?.group)}" data-window="${escapeHtml(windowKey)}">${escapeHtml(formatResetCountdown(value, item?.status))}</time>`;
}

function updateCountdowns() {
  document.querySelectorAll("[data-ai-usage-countdown]").forEach((node) => {
    const item = state?.providers?.find((provider) => (
      provider.provider === node.dataset.provider && provider.group === node.dataset.group
    ));
    const windowData = item?.[node.dataset.window];
    node.textContent = formatResetCountdown(windowData?.resetAt, item?.status);
  });
}

function startCountdownTimer() {
  if (countdownTimer) return;
  countdownTimer = window.setInterval(updateCountdowns, 1000);
}

function readResetBaselines() {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(RESET_BASELINES_KEY) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function detectQuotaResets(providers) {
  const previous = readResetBaselines();
  const next = { ...previous };
  const windowLabels = { fiveHour: "5h", weekly: "weekly" };

  (providers || []).forEach((item) => {
    if (String(item?.status || "").toLowerCase() !== "connected") return;
    Object.entries(windowLabels).forEach(([windowKey, windowLabel]) => {
      const remaining = Number(item?.[windowKey]?.remaining);
      if (!Number.isFinite(remaining)) return;

      const baselineKey = `${item.provider}:${item.group}:${windowKey}`;
      const oldRemaining = Number(previous[baselineKey]?.remaining);
      if (Number.isFinite(oldRemaining) && oldRemaining === 0 && remaining === 100) {
        const resetToken = item[windowKey]?.resetAt || item.updatedAt || "reset";
        addDashboardNotification({
          id: `ai-usage:${baselineKey}:${resetToken}`,
          category: "AI Usage",
          title: `${item.label} ${windowLabel} limit reset — 100% available`,
          message: `${item.label} ${windowLabel} quota has reset from 0% to 100%.`,
          targetId: "ai-usage-card",
          createdAt: item.updatedAt,
        });
      }
      next[baselineKey] = { remaining, resetAt: item[windowKey]?.resetAt || null };
    });
  });

  try {
    globalThis.localStorage?.setItem(RESET_BASELINES_KEY, JSON.stringify(next));
  } catch {}
}

function quotaState(remaining) {
  const number = Number(remaining);
  if (!Number.isFinite(number)) return { key: "unavailable", label: "unavailable" };
  if (number >= 80) return { key: "healthy", label: "healthy" };
  if (number >= 50) return { key: "normal", label: "normal" };
  if (number >= 25) return { key: "warning", label: "warning" };
  return { key: "critical", label: "critical" };
}

function quotaLine(label, window, item, windowKey) {
  const status = quotaState(window?.remaining);
  const width = Number.isFinite(Number(window?.remaining)) ? Math.max(0, Math.min(100, Number(window.remaining))) : 0;
  return `
    <div class="ai-usage-quota-row" data-state="${status.key}">
      <span class="ai-usage-quota-label">${escapeHtml(label)}</span>
      <div class="ai-usage-progress" role="progressbar" aria-label="${escapeHtml(label)} remaining: ${escapeHtml(formatPercent(window?.remaining))}, ${status.label}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${width}">
        <span style="width:${width}%"></span>
      </div>
      <strong>${escapeHtml(formatPercent(window?.remaining))}</strong>
      <span class="ai-usage-reset"><span>Resets in</span>${countdownTime(item, windowKey)}</span>
      <small>${status.label}</small>
    </div>`;
}

function statusBadge(status) {
  const normalized = String(status || "unavailable").toLowerCase();
  return `<span class="ai-usage-status" data-status="${escapeHtml(normalized)}">${escapeHtml(normalized.replaceAll("_", " ").toUpperCase())}</span>`;
}

function groupLabel(provider, group) {
  return state?.providers?.find((item) => item.provider === provider && item.group === group)?.label
    || (group === "main" ? "Codex" : group === "gemini" ? "Gemini" : "Claude / GPT");
}

function renderProviderCompact(item) {
  const today = item.stats?.today || {};
  const codexExtra = item.provider === "codex" ? `
    <div class="ai-usage-compact-meta">
      <span>Active <strong>${formatDuration(today.activeSeconds)}</strong></span>
      <span>Quota value <strong>~$${Number(item.quotaValue?.today?.usd || 0).toFixed(2)} / ~${Number(item.quotaValue?.today?.pln || 0).toFixed(2)} zł</strong></span>
    </div>` : "";
  return `
    <section class="ai-usage-provider-compact">
      <div class="ai-usage-provider-head"><strong>${escapeHtml(item.label)}</strong>${statusBadge(item.status)}</div>
      ${quotaLine("5h", item.fiveHour, item, "fiveHour")}
      ${quotaLine("week", item.weekly, item, "weekly")}
      <div class="ai-usage-today-row"><span>Today</span><strong>${formatBurn(today.weekly)}</strong></div>
      ${codexExtra}
    </section>`;
}

function renderLastSession(session) {
  if (!session) return `<div class="ai-usage-empty">No usage session detected yet.</div>`;
  const value = session.quotaValue
    ? `<span>Quota value <strong>~$${Number(session.quotaValue.usd || 0).toFixed(2)} / ~${Number(session.quotaValue.pln || 0).toFixed(2)} zł</strong></span>`
    : "";
  return `
    <div class="ai-usage-last-session">
      <div><strong>${escapeHtml(groupLabel(session.provider, session.group))}</strong><span>${formatDuration(session.duration_seconds)}</span></div>
      <span>Weekly used <strong>${formatBurn(session.weekly_burn)}</strong></span>
      ${value}
    </div>`;
}

function renderCompact() {
  if (!root || !state) return;
  root.innerHTML = `
    <div class="ai-usage-providers">${state.providers.map(renderProviderCompact).join("")}</div>
    <section class="ai-usage-last">
      <div class="ai-usage-section-label">Last session</div>
      ${renderLastSession(state.sessions?.[0])}
    </section>`;
}

async function refresh() {
  try {
    state = await fetchAiUsage();
    detectQuotaResets(state.providers);
    renderCompact();
    startCountdownTimer();
    card?.classList.remove("is-error");
  } catch {
    if (root) root.innerHTML = '<div class="ai-usage-empty">AI Usage backend unavailable.</div>';
    card?.classList.add("is-error");
  } finally {
    window.clearTimeout(timer);
    timer = window.setTimeout(refresh, POLL_MS);
  }
}

card?.addEventListener("click", (event) => {
  if (!event.target.closest("button, a")) detailButton?.click();
});
window.addEventListener("beforeunload", () => {
  window.clearTimeout(timer);
  window.clearInterval(countdownTimer);
}, { once: true });
refresh();
