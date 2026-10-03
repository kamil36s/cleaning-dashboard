const achievementState = new Map();

const VALID_STATES = new Set([
  "loading",
  "complete",
  "pending",
  "neutral",
  "streak",
  "error",
]);

export function normalizeDailyAchievement(value = {}) {
  const state = VALID_STATES.has(value.state) ? value.state : "loading";
  const rawProgress = value.progress === null || value.progress === undefined || value.progress === ""
    ? null
    : Number(value.progress);
  const maxProgress = state === "pending" ? 99 : 100;
  const progress = Number.isFinite(rawProgress)
    ? Math.min(maxProgress, Math.max(0, Math.floor(rawProgress)))
    : null;
  return {
    state,
    value: String(value.value ?? "—"),
    detail: String(value.detail ?? "Sprawdzam dane"),
    coverUrl: String(value.coverUrl ?? ""),
    eligible: value.eligible !== false && state !== "streak" && state !== "neutral" && state !== "error" && state !== "loading",
    progress,
  };
}

function renderAchievement(key) {
  const item = document.querySelector(`[data-daily-achievement="${key}"]`);
  if (!(item instanceof HTMLElement)) return;

  const entry = normalizeDailyAchievement(achievementState.get(key));
  item.dataset.state = entry.state;
  item.setAttribute("aria-label", `${item.dataset.label || key}: ${entry.value}. ${entry.detail}`);

  const value = item.querySelector("[data-daily-achievement-value]");
  const detail = item.querySelector("[data-daily-achievement-detail]");
  const mark = item.querySelector(".daily-achievement-mark");
  const artwork = item.querySelector(".daily-achievement-album-art");
  if (value) value.textContent = entry.value;
  if (detail) detail.textContent = entry.detail;
  if (artwork instanceof HTMLImageElement) {
    if (entry.coverUrl) {
      if (artwork.getAttribute("src") !== entry.coverUrl) {
        artwork.hidden = true;
        artwork.onload = () => { artwork.hidden = false; };
        artwork.onerror = () => { artwork.hidden = true; };
        artwork.src = entry.coverUrl;
      }
    } else {
      artwork.hidden = true;
      artwork.removeAttribute("src");
    }
  }
  if (entry.progress === null) {
    delete item.dataset.progress;
    item.style.removeProperty("--achievement-progress");
    if (mark) mark.textContent = "•";
  } else {
    item.dataset.progress = String(entry.progress);
    item.style.setProperty("--achievement-progress", `${entry.progress * 3.6}deg`);
    if (mark) mark.textContent = entry.state === "complete" ? "" : `${entry.progress}%`;
  }
}

function renderAll() {
  if (typeof document === "undefined") return;
  achievementState.forEach((_, key) => renderAchievement(key));
}

export function setDailyAchievement(key, value) {
  const normalizedKey = String(key);
  const next = normalizeDailyAchievement(value);
  const previous = achievementState.get(normalizedKey);
  if (previous
    && previous.state === next.state
    && previous.value === next.value
    && previous.detail === next.detail
    && previous.coverUrl === next.coverUrl
    && previous.eligible === next.eligible
    && previous.progress === next.progress) return;
  achievementState.set(normalizedKey, next);
  renderAchievement(normalizedKey);
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll, { once: true });
  } else {
    renderAll();
  }
}
