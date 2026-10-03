import { fetchTimelineSummary } from "./timeline-api.js";

const card = document.getElementById("great-timeline-card");
const root = document.getElementById("great-timeline-root");

function escapeHtml(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function formatUpdated(value) {
  if (!value) return "No updates yet";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return `${String(parsed.getDate()).padStart(2, "0")}/${String(parsed.getMonth() + 1).padStart(2, "0")}/${parsed.getFullYear()}`;
}

function renderSummary(summary) {
  root.innerHTML = `
    <div class="great-timeline-widget-metrics">
      <div><strong>${escapeHtml(summary.total || 0)}</strong><span>all entries</span></div>
      <div><strong>${escapeHtml(summary.active || 0)}</strong><span>active periods</span></div>
      <div><strong>${escapeHtml(formatUpdated(summary.updatedAt))}</strong><span>last update</span></div>
    </div>
    ${(summary.recent || []).length ? `<div class="great-timeline-widget-recent">${summary.recent.slice(0, 3).map((item) => `<span>${escapeHtml(item.title)}</span>`).join("")}</div>` : ""}
  `;
}

async function loadSummary() {
  if (!card || !root) return;
  try {
    renderSummary(await fetchTimelineSummary());
  } catch {
    root.innerHTML = `<div class="great-timeline-widget-empty"><strong>Timeline is offline</strong><span>Open the page after starting the local API.</span></div>`;
  }
}

loadSummary();
window.addEventListener("focus", loadSummary);
