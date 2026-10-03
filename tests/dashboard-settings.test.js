import path from "node:path";
import { pathToFileURL } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";

async function importFreshModule() {
  const modulePath = pathToFileURL(path.resolve("js/dashboard-settings.js")).href;
  return import(`${modulePath}?t=${Date.now()}`);
}

describe("dashboard widget settings helpers", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("fills missing values from defaults when reading stored config", async () => {
    const {
      readStoredDashboardWidgetConfig,
      saveDashboardWidgetConfig,
    } = await importFreshModule();

    saveDashboardWidgetConfig({
      order: {
        reading: 10,
        weather: 20,
      },
      visible: {
        weather: false,
      },
    });

    const config = readStoredDashboardWidgetConfig();

    expect(config.order.reading).toBe(10);
    expect(config.order.cleaning).toBeTypeOf("number");
    expect(config.visible.weather).toBe(false);
    expect(config.visible.cleaning).toBe(true);
    expect(config.visible.bills).toBe(true);
    expect(config.placement.bills.span).toBe("full");
  });

  it("moves widgets up and down without losing the rest of the order", async () => {
    const {
      getDefaultDashboardWidgetConfig,
      getOrderedDashboardWidgets,
      moveDashboardWidget,
    } = await importFreshModule();

    let config = getDefaultDashboardWidgetConfig();
    config = moveDashboardWidget(config, "reading", -1);

    let keys = getOrderedDashboardWidgets(config).map((widget) => widget.key);
    expect(keys.indexOf("reading")).toBe(3);
    expect(keys.indexOf("self-care")).toBe(4);
    expect(keys.indexOf("cleaning")).toBe(2);

    config = moveDashboardWidget(config, "weather", -1);
    keys = getOrderedDashboardWidgets(config).map((widget) => widget.key);
    expect(keys[0]).toBe("weather");
  });

  it("can enable or disable all widgets in one go", async () => {
    const {
      getDefaultDashboardWidgetConfig,
      setAllDashboardWidgetsVisibility,
    } = await importFreshModule();

    const hidden = setAllDashboardWidgetsVisibility(
      getDefaultDashboardWidgetConfig(),
      false,
    );
    const visible = setAllDashboardWidgetsVisibility(hidden, true);

    expect(Object.values(hidden.visible).every((value) => value === false)).toBe(true);
    expect(Object.values(visible.visible).every((value) => value === true)).toBe(true);
  });

  it("normalizes dashboard columns and widget spans", async () => {
    const {
      getDefaultDashboardWidgetConfig,
      setDashboardAutoFitEnabled,
      setDashboardColumnCount,
      setDashboardCleaningLockEnabled,
      setDashboardHeartRateHistoryShortcutEnabled,
      setDashboardWidgetSpan,
    } = await importFreshModule();

    let config = getDefaultDashboardWidgetConfig();
    config = setDashboardColumnCount(config, 4);
    config = setDashboardAutoFitEnabled(config, true);
    config = setDashboardWidgetSpan(config, "reading", "2");

    expect(config.layout.columns).toBe(4);
    expect(config.layout.autoFit).toBe(true);
    expect(config.layout.showHeartRateHistoryShortcut).toBe(true);
    expect(config.layout.cleaningLockEnabled).toBe(false);
    expect(config.placement.reading.span).toBe("2");

    config = setDashboardHeartRateHistoryShortcutEnabled(config, false);
    expect(config.layout.showHeartRateHistoryShortcut).toBe(false);
    config = setDashboardCleaningLockEnabled(config, true);
    expect(config.layout.cleaningLockEnabled).toBe(true);

    config = setDashboardColumnCount(config, 99);
    config = setDashboardAutoFitEnabled(config, false);
    config = setDashboardWidgetSpan(config, "reading", "banana");

    expect(config.layout.columns).toBe(4);
    expect(config.layout.autoFit).toBe(false);
    expect(config.layout.showHeartRateHistoryShortcut).toBe(false);
    expect(config.layout.cleaningLockEnabled).toBe(true);
    expect(config.placement.reading.span).toBe("auto");
  });

  it("preserves default full-width widget placement", async () => {
    const {
      getDefaultDashboardWidgetConfig,
      getOrderedDashboardWidgets,
    } = await importFreshModule();

    const widgets = getOrderedDashboardWidgets(getDefaultDashboardWidgetConfig());
    const weightCut = widgets.find((widget) => widget.key === "weight-cut");
    const bills = widgets.find((widget) => widget.key === "bills");

    expect(weightCut?.span).toBe("full");
    expect(bills).toMatchObject({
      label: "Rachunki, raty i subskrypcje",
      visible: true,
      span: "full",
    });
  });

  it("replaces focused app widgets with side shortcuts", async () => {
    const {
      getDefaultDashboardWidgetConfig,
      getOrderedDashboardWidgets,
      normalizeDashboardWidgetConfig,
    } = await importFreshModule();

    const defaults = getOrderedDashboardWidgets(getDefaultDashboardWidgetConfig());
    const migrated = getOrderedDashboardWidgets(normalizeDashboardWidgetConfig({
      visible: {
        journal: true,
        "great-timeline": true,
        "blood-pressure": true,
        "voice-journal": true,
      },
    }));

    for (const key of ["journal", "great-timeline", "blood-pressure", "voice-journal"]) {
      expect(defaults.some((widget) => widget.key === key)).toBe(false);
      expect(migrated.some((widget) => widget.key === key)).toBe(false);
    }
  });

  it("normalizes header font size and widget header text", async () => {
    const {
      getDefaultDashboardWidgetConfig,
      getOrderedDashboardWidgets,
      setDashboardHeaderFontSize,
      setDashboardWidgetHeaderText,
    } = await importFreshModule();

    let config = getDefaultDashboardWidgetConfig();
    config = setDashboardHeaderFontSize(config, 21);
    config = setDashboardWidgetHeaderText(config, "bm365", {
      title: "Moje albumy",
      subtitle: "Progress odsluchu albumow",
    });

    const widgets = getOrderedDashboardWidgets(config);
    const bm365 = widgets.find((widget) => widget.key === "bm365");

    expect(config.headers.titleFontSize).toBe(21);
    expect(bm365?.title).toBe("Moje albumy");
    expect(bm365?.subtitle).toBe("Postęp odsłuchu albumów");

    config = setDashboardHeaderFontSize(config, 99);
    expect(config.headers.titleFontSize).toBe(22);
  });

  it("persists custom widget headers through local storage", async () => {
    const {
      readStoredDashboardWidgetConfig,
      saveDashboardWidgetConfig,
    } = await importFreshModule();

    saveDashboardWidgetConfig({
      headers: {
        titleFontSize: 18,
        widgets: {
          weather: {
            title: "Moja pogoda",
            subtitle: "Teraz i zaraz",
          },
        },
      },
    });

    const config = readStoredDashboardWidgetConfig();

    expect(config.headers.titleFontSize).toBe(18);
    expect(config.headers.widgets.weather.title).toBe("Moja pogoda");
    expect(config.headers.widgets.weather.subtitle).toBe("Teraz i zaraz");
  });

  it("repairs legacy default header text without Polish characters", async () => {
    const {
      getOrderedDashboardWidgets,
      normalizeDashboardWidgetConfig,
    } = await importFreshModule();

    const config = normalizeDashboardWidgetConfig({
      headers: {
        widgets: {
          budget: { title: "Budzet", subtitle: "" },
          cleaning: { title: "Cleaning Dashboard", subtitle: "Dzisiejszy status sprzatania" },
        },
      },
    });
    const widgets = getOrderedDashboardWidgets(config);

    expect(widgets.find((widget) => widget.key === "budget")?.title).toBe("Budżet");
    expect(widgets.find((widget) => widget.key === "cleaning")?.subtitle).toBe("Dzisiejszy status sprzątania");
  });

  it("drops an accidental show-all layout from local storage", async () => {
    const {
      DASHBOARD_WIDGET_STORAGE_KEY,
      getDefaultDashboardWidgetConfig,
      readStoredDashboardWidgetConfig,
    } = await importFreshModule();

    const config = getDefaultDashboardWidgetConfig();
    Object.keys(config.visible).forEach((key) => {
      config.visible[key] = true;
    });
    localStorage.setItem(DASHBOARD_WIDGET_STORAGE_KEY, JSON.stringify(config));

    expect(readStoredDashboardWidgetConfig()).toBeNull();
    expect(localStorage.getItem(DASHBOARD_WIDGET_STORAGE_KEY)).toBeNull();
  });

  it("uses Polish characters in widget metadata", async () => {
    const {
      getDefaultDashboardWidgetConfig,
      getOrderedDashboardWidgets,
    } = await importFreshModule();

    const widgets = getOrderedDashboardWidgets(getDefaultDashboardWidgetConfig());
    const networkWidget = widgets.find((widget) => widget.key === "network-monitor");

    expect(networkWidget?.label).toBe("Sieć lokalna");
    expect(networkWidget?.description).toContain("Urządzenia");
  });

  it("emits a same-window event after saving config", async () => {
    const {
      DASHBOARD_WIDGETS_CHANGED_EVENT,
      saveDashboardWidgetConfig,
    } = await importFreshModule();

    const calls = [];
    const handler = (event) => {
      calls.push(event.detail);
    };

    window.addEventListener(DASHBOARD_WIDGETS_CHANGED_EVENT, handler);
    try {
      saveDashboardWidgetConfig({
        visible: { weather: false },
      });
    } finally {
      window.removeEventListener(DASHBOARD_WIDGETS_CHANGED_EVENT, handler);
    }

    expect(calls).toHaveLength(1);
    expect(calls[0].visible.weather).toBe(false);
  });
});
