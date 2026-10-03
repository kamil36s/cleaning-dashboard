import { afterEach, describe, expect, it, vi } from "vitest";

const dashboardConfig = {
  order: { cleaning: 10 },
  visible: { cleaning: true },
  layout: { columns: 2, autoFit: false },
  placement: { cleaning: { span: "1" } },
  headers: {
    titleFontSize: 16,
    widgets: {
      cleaning: { title: "Cleaning Dashboard", subtitle: "" },
    },
  },
};

async function waitFor(selector) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const element = document.querySelector(selector);
    if (element) return element;
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  }
  return null;
}

describe("settings widget header editor", () => {
  afterEach(() => {
    document.body.className = "";
    document.body.innerHTML = "";
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("keeps title editing and removes the subtitle control", async () => {
    document.body.innerHTML = `
      <button id="dashboard-settings-trigger" type="button">Ustawienia</button>
      <div id="settings-overlay" hidden>
        <button id="settings-close-btn" type="button">Zapisz i zamknij</button>
        <div id="settings-save-note"></div>
        <div id="settings-widget-list"></div>
      </div>
    `;

    vi.stubGlobal("fetch", vi.fn(async (input, options = {}) => {
      const url = String(input);
      if (options.method === "POST") {
        const payload = JSON.parse(options.body);
        return { ok: true, json: async () => ({ ok: true, data: payload.data }) };
      }
      if (url.includes("widget-order.json")) {
        return { ok: true, json: async () => dashboardConfig };
      }
      return { ok: true, json: async () => ({ ok: true, data: dashboardConfig }) };
    }));

    await import("../js/settings.js");
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    document.querySelector("#dashboard-settings-trigger")?.click();

    const titleInput = await waitFor('[data-key="cleaning"] input[data-action="header-title"]');
    expect(titleInput).toBeInstanceOf(HTMLInputElement);
    expect(document.querySelector('[data-key="cleaning"] input[data-action="header-subtitle"]')).toBeNull();
    titleInput.value = "Mój plan";
    titleInput.dispatchEvent(new Event("input", { bubbles: true }));
    document.querySelector("#settings-close-btn")?.click();

    const stored = JSON.parse(localStorage.getItem("dashboard.widget-settings.v1"));
    expect(stored.headers.widgets.cleaning.title).toBe("Mój plan");
    expect(stored.headers.widgets.cleaning.subtitle).toBe("");
  });
});
