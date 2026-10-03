import { fetchMentalHealthOverview } from "./mental-health-api.js";

const root = document.querySelector("#mental-health-root");
const card = document.querySelector("#mental-health-card");

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

function formatDate(value) {
  if (!value) return "brak";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "brak" : date.toLocaleDateString("pl-PL", { day: "2-digit", month: "short" });
}

function score(item) {
  if (!item) return "—";
  const current = item.current;
  if (item.instrument.id === "who5") return `${current.normalizedScore}/100`;
  if (current.rawScore != null) return `${Number.isInteger(current.rawScore) ? current.rawScore : current.rawScore.toFixed(1)}/${item.instrument.scoreMax}`;
  return Object.values(current.subscaleScores || {}).length ? Object.values(current.subscaleScores).map((value) => Number(value).toFixed(0)).join(" · ") : "—";
}

export function renderMentalHealthWidget(data) {
  const latest = Object.fromEntries((data.latest || []).map((item) => [item.instrument.id, item]));
  const snapshotIds = ["phq9", "gad7", "who5", "cbi"];
  const snapshot = snapshotIds.map((id) => {
    const item = latest[id];
    const label = id === "cbi" ? "Burnout" : item?.instrument.shortName || id.toUpperCase();
    const value = id === "cbi" && item ? item.current.subscaleScores?.personal : score(item);
    const delta = item?.changeFromPrevious;
    const trend = delta == null ? "" : delta === 0 ? "•" : delta > 0 ? "↑" : "↓";
    return `<div class="mh-widget-metric"><span>${escapeHtml(label)}</span><strong>${item ? escapeHtml(Number.isFinite(Number(value)) ? Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1) : value) : "—"}</strong><small>${escapeHtml(trend)}</small></div>`;
  }).join("");
  const next = data.nextScheduled;
  return `<div class="mh-widget-top"><div><span>Do zrobienia</span><strong>${Number(data.dueCount || 0)}</strong></div><div><span>Ostatni check-in</span><strong>${escapeHtml(formatDate(data.lastCheckin?.recordedAt))}</strong></div><div><span>Następne</span><strong>${escapeHtml(next ? data.registry.find((item) => item.id === next.instrumentId)?.shortName || next.instrumentId : "—")}</strong><small>${escapeHtml(formatDate(next?.nextDueAt))}</small></div></div><div class="mh-widget-snapshot">${snapshot}</div><p class="mh-widget-note">Oddzielne wymiary · screening nie jest diagnozą</p>`;
}

async function refresh() {
  if (!root) return;
  try {
    const data = await fetchMentalHealthOverview();
    root.innerHTML = renderMentalHealthWidget(data);
    card?.classList.remove("is-error");
  } catch {
    root.innerHTML = '<div class="mh-widget-empty">Mental Health backend jest niedostępny.</div>';
    card?.classList.add("is-error");
  }
}

refresh();

