import { beforeEach, describe, expect, it } from "vitest";
import { HIGHLIGHT_PRESETS, applySettings, loadSettings } from "../js/synchrobook/settings.js";

describe("Synchrobook highlight settings", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("style");
  });

  it("uses a readable high-contrast highlight by default", () => {
    const settings = loadSettings();
    expect(settings.highlightPreset).toBe("yellow");
    expect(settings.highlightBackground).toBe("#ffd84d");
    expect(settings.highlightText).toBe("#111111");
  });

  it("adds highlight defaults to settings saved before customization existed", () => {
    localStorage.setItem("dashboard.synchrobook.settings.v1", JSON.stringify({ mode: "relax", fontSize: 30 }));
    const settings = loadSettings();
    expect(settings.highlightBackground).toBe(HIGHLIGHT_PRESETS.yellow.highlightBackground);
    expect(settings.highlightText).toBe(HIGHLIGHT_PRESETS.yellow.highlightText);
  });

  it("migrates the old BIKE defaults to the larger reading preset", () => {
    localStorage.setItem("dashboard.synchrobook.settings.v1", JSON.stringify({ mode: "bike", fontSize: 44, columnWidth: 1040 }));
    const settings = loadSettings();
    expect(settings.fontSize).toBe(48);
    expect(settings.columnWidth).toBe(1160);
  });

  it("applies custom highlight colors, glow and weight as CSS variables", () => {
    applySettings({
      ...loadSettings(),
      highlightBackground: "#67e8f9",
      highlightText: "#071318",
      highlightGlow: 24,
      highlightBold: false,
    });
    const style = document.documentElement.style;
    expect(style.getPropertyValue("--synchrobook-highlight-bg")).toBe("#67e8f9");
    expect(style.getPropertyValue("--synchrobook-highlight-text")).toBe("#071318");
    expect(style.getPropertyValue("--synchrobook-highlight-glow")).toBe("24px");
    expect(style.getPropertyValue("--synchrobook-highlight-weight")).toBe("400");
  });
});
