import {
  DASHBOARD_WIDGETS_CHANGED_EVENT,
  loadDashboardWidgetConfig,
} from "./dashboard-settings.js";
import { onDomReady } from "./dom-ready.js";
import { filterVisibleWidgetKeys } from "./dashboard-widget-visibility.js";

const PRIORITY_WIDGETS = new Set([
  "weather",
  "aqi",
  "cleaning",
  "reading",
  "jobhunt",
  "bm365",
  "weight-cut",
  "live-workout",
]);

const widgetLoaders = {
  weather: () => import("./main_weather.js"),
  aqi: () => import("./init-aqi.js"),
  cleaning: () => import("./widget-cleaning.js"),
  "self-care": () => import("./widget-self-care.js"),
  feelings: () => import("./widget-feelings.js"),
  reading: () => import("./widget-reading.js"),
  "language-learning": () => import("./widget-language-learning.js"),
  "phone-telemetry": () => import("./widget-phone-telemetry.js"),
  "phone-activity": () => import("./widget-phone-activity.js"),
  todo: () => import("./widget-todo.js"),
  bills: () => import("./widget-bills.js"),
  budget: () => import("./widget-budget.js"),
  "weight-cut": () => import("./widget-weight-cut.js"),
  "live-workout": () => import("./widget-live-workout.js"),
  diet: () => import("./widget-diet.js"),
  "journal-htr": () => import("./widget-journal-htr.js"),
  jobhunt: () => import("./widget-jobhunt.js"),
  "ai-usage": () => import("./widget-ai-usage.js"),
  "mental-health": () => import("./widget-mental-health.js"),
  "weekly-insights": () => import("./widget-weekly-insights.js"),
  quote: () => import("./widget-quote.js"),
  films: () => import("./widget-films.js"),
  "cinema-city": () => import("./widget-cinema-city.js"),
  "classical-library": () => import("./widget-classical-library.js"),
  "network-monitor": () => import("./widget-network.js"),
  events: () => import("./widget-events.js"),
  "event-countdowns": () => import("./widget-event-countdowns.js"),
  bm365: () => import("./bm365.js"),
  "brutal-assault-2027": () => import("./widget-brutal-assault-2027.js"),
  "rym-polish-black-metal-top-100": () => import("./widget-rym-polish-black-metal.js"),
  habits: () => import("./habits.js"),
  "habits-app": () => import("./widget-habits-app.js"),
  "habits-timeline": async () => {
    await import("./habit-data.js");
    await Promise.all([
      import("./habit-timelines.js"),
      import("./habit-upload.js"),
    ]);
  },
  sensors: async () => {
    const { initSensorWidget } = await import("./widget-sensors.js");
    initSensorWidget({
      url: "/api/sensor/latest",
      historyUrl: "/api/sensor/history",
      pollMs: 30000,
      // Legacy fallback (Gist): "https://gist.githubusercontent.com/kamil36s/fae9b26f7ffce459eceb203fb130f250/raw/room.json"
    });
  },
};

const loadPromises = new Map();

function applyInitialLayout(config) {
  const dash = document.querySelector(".dash");
  if (!dash) return;

  const columns = Math.min(4, Math.max(2, Number(config?.layout?.columns) || 2));
  document.documentElement.dataset.dashboardColumns = String(columns);
  dash.dataset.columns = String(columns);
  dash.dataset.autoFit = config?.layout?.autoFit === true ? "true" : "false";
  dash.style.setProperty("--dashboard-columns", String(columns));

  dash.querySelectorAll(":scope > [data-widget]").forEach((card) => {
    card.hidden = config?.visible?.[card.dataset.widget] === false;
  });
}

function loadWidget(key) {
  if (!widgetLoaders[key]) return Promise.resolve();
  if (!loadPromises.has(key)) {
    const promise = widgetLoaders[key]().catch((error) => {
      console.error(`Nie udało się załadować widgetu ${key}:`, error);
      throw error;
    });
    loadPromises.set(key, promise);
  }
  return loadPromises.get(key);
}

function loadVisibleWidgets(config) {
  return Promise.allSettled(
    filterVisibleWidgetKeys(Object.keys(widgetLoaders), config).map(loadWidget),
  );
}

function visibleWidgetKeys(config) {
  return filterVisibleWidgetKeys(Object.keys(widgetLoaders), config);
}

function loadWidgets(keys) {
  return Promise.allSettled(keys.map(loadWidget));
}

function waitForNetworkIdle({ timeoutMs = 4500, stableMs = 120 } = {}) {
  return new Promise((resolve) => {
    const startedAt = performance.now();
    let idleSince = null;
    const check = () => {
      const now = performance.now();
      if (Number(window.__pendingRequests || 0) === 0) {
        idleSince ??= now;
        if (now - idleSince >= stableMs) {
          resolve();
          return;
        }
      } else {
        idleSince = null;
      }
      if (now - startedAt >= timeoutMs) {
        resolve();
        return;
      }
      window.setTimeout(check, 40);
    };
    check();
  });
}

window.addEventListener(DASHBOARD_WIDGETS_CHANGED_EVENT, (event) => {
  applyInitialLayout(event.detail || {});
  loadVisibleWidgets(event.detail || {});
});

async function startDashboard() {
  const config = await loadDashboardWidgetConfig();
  applyInitialLayout(config);

  const visibleKeys = visibleWidgetKeys(config);
  const priorityKeys = visibleKeys.filter((key) => PRIORITY_WIDGETS.has(key));
  const deferredKeys = visibleKeys.filter((key) => !PRIORITY_WIDGETS.has(key) && key !== "habits");

  await Promise.allSettled([
    import("./widget-order.js"),
    import("./settings.js"),
    import("./dashboard-heart-rate-history-link.js"),
    import("./dashboard-screensaver-launcher.js"),
    // Trzeźwość jest częścią paska osiągnięć także wtedy, gdy karta habits jest ukryta.
    loadWidget("habits"),
    loadWidgets(priorityKeys),
  ]);

  await waitForNetworkIdle();
  await loadWidgets(deferredKeys);
}

onDomReady(() => {
  startDashboard().catch((error) => {
    console.error("Nie udało się uruchomić dashboardu:", error);
  });
});
