import { feelingsApi } from "./feelings-api.js";
import { createFeelingsWorkspace } from "./feelings-workspace.js";
import { escapeHtml, localDate, QUADRANT_META } from "./feelings-model.js";

const card = document.getElementById("feelings-card");
const root = document.getElementById("feelings-widget-root");
const openButton = document.getElementById("feelings-check-in");

if (card && root && openButton) {
  const workspace = createFeelingsWorkspace({ onChanged: refresh });

  function formatWhen(value) {
    if (!value) return "No check-ins yet";
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
  }

  function weekBars(checkins) {
    const today = new Date();
    const days = [];
    for (let offset = 6; offset >= 0; offset -= 1) {
      const date = new Date(today);
      date.setDate(date.getDate() - offset);
      const key = localDate(date);
      const items = checkins.filter((item) => item.occurredAt.startsWith(key));
      const counts = Object.fromEntries(Object.keys(QUADRANT_META).map((quadrant) => [quadrant, items.filter((item) => item.emotion?.quadrant === quadrant).length]));
      const total = items.length;
      days.push(`<div title="${key}: ${total} check-in${total === 1 ? "" : "s"}"><span>${Object.entries(counts).filter(([, count]) => count).map(([quadrant, count]) => `<i style="--segment:${QUADRANT_META[quadrant].color};--share:${count / total}"></i>`).join("")}</span><b>${new Intl.DateTimeFormat(undefined, { weekday: "narrow" }).format(date)}</b></div>`);
    }
    return days.join("");
  }

  async function refresh() {
    root.setAttribute("aria-busy", "true");
    try {
      const result = await feelingsApi.listCheckins({ limit: 5000 });
      const checkins = result.checkins || [];
      const latest = checkins[0];
      const todayKey = localDate(new Date());
      const todayCount = checkins.filter((item) => item.occurredAt.startsWith(todayKey)).length;
      if (!latest) {
        root.innerHTML = `<div class="feelings-widget-empty"><span>Your feelings journal is ready.</span><p>Choose a color, find the right word, and save your first check-in.</p></div>`;
      } else {
        const meta = QUADRANT_META[latest.emotion?.quadrant];
        root.innerHTML = `
          <button class="feelings-widget-latest" type="button" data-open-feelings aria-label="Open How I Feel">
            <i class="feelings-widget-orb shape-${escapeHtml(latest.emotion?.shape || "circle")}" style="--emotion-color:${escapeHtml(latest.emotion?.color)}"></i>
            <div><span>${escapeHtml(meta?.label || "Latest check-in")}</span><strong>${escapeHtml(latest.emotion?.name)}</strong><time>${escapeHtml(formatWhen(latest.occurredAt))}</time></div>
          </button>
          <div class="feelings-widget-week"><header><span>Last 7 days</span><b>${todayCount} check-in${todayCount === 1 ? "" : "s"} today</b></header><div>${weekBars(checkins)}</div></div>`;
      }
    } catch (error) {
      root.innerHTML = `<div class="feelings-widget-error"><b>How I Feel is unavailable</b><span>${escapeHtml(error.message)}</span><button type="button" data-retry-feelings>Retry</button></div>`;
    } finally {
      root.setAttribute("aria-busy", "false");
    }
  }

  openButton.addEventListener("click", () => workspace.open("checkin"));
  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-feelings]")) workspace.open("checkin");
    if (event.target.closest("[data-retry-feelings]")) refresh();
  });
  refresh();
}
