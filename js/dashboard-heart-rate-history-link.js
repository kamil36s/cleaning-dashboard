import {
  DASHBOARD_WIDGETS_CHANGED_EVENT,
  loadDashboardWidgetConfig,
} from "./dashboard-settings.js";

const link = document.getElementById("dashboard-heart-rate-history-link");

function applyVisibility(config) {
  if (!link) return;
  link.hidden = config?.layout?.showHeartRateHistoryShortcut === false;
}

if (link) {
  loadDashboardWidgetConfig()
    .then(applyVisibility)
    .catch(() => {
      link.hidden = false;
    });

  window.addEventListener(DASHBOARD_WIDGETS_CHANGED_EVENT, (event) => {
    applyVisibility(event.detail);
  });
}
