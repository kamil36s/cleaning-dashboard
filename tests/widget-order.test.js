import { afterEach, describe, expect, it, vi } from "vitest";

describe("dashboard widget header customization", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
  });

  it("applies changed titles and removes widget subtitles", async () => {
    document.body.innerHTML = `
      <section class="dash" style="display:grid;grid-template-columns:1fr 1fr;grid-auto-rows:8px;gap:8px">
        <article class="card cleaning" id="cleaning-card" data-widget="cleaning">
          <div class="header">
            <div class="title" id="cl-title">
              <svg></svg>
              <div>Cleaning Dashboard<div class="meta">Dzisiejszy status</div></div>
            </div>
          </div>
        </article>
        <article class="card event-countdowns" data-widget="event-countdowns">
          <header class="event-countdowns-head">
            <div>
              <div class="event-countdowns-title">Event Countdowns</div>
              <div class="meta">Najbliższe wydarzenia</div>
            </div>
          </header>
        </article>
        <article class="card sensors" data-widget="sensors">
          <header class="sensor-head">
            <div class="sensor-head-main">
              <svg></svg>
              <div class="sensor-title">Temperatura w mieszkaniu</div>
            </div>
          </header>
        </article>
      </section>
    `;

    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({ data: null }),
    })));
    await import("../js/widget-order.js");
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    window.dispatchEvent(new CustomEvent("dashboard:widgets-changed", { detail: {
      order: {},
      visible: {},
      layout: { columns: 2, autoFit: false },
      placement: {},
      headers: {
        titleFontSize: 18,
        widgets: {
          cleaning: { title: "Dom", subtitle: "Plan na dziś" },
          "event-countdowns": { title: "Odliczanie", subtitle: "Ważne daty" },
          sensors: { title: "Salon", subtitle: "Warunki teraz" },
        },
      },
    } }));

    expect(document.querySelector('[data-widget="cleaning"] .dashboard-widget-title-text')?.textContent).toBe("Dom");
    expect(document.querySelector('[data-widget="cleaning"] .dashboard-widget-subtitle')).toBeNull();
    expect(document.querySelector('[data-widget="event-countdowns"] .event-countdowns-title')?.textContent).toBe("Odliczanie");
    expect(document.querySelector('[data-widget="event-countdowns"] .dashboard-widget-subtitle')).toBeNull();
    expect(document.querySelector('[data-widget="sensors"] .sensor-title')?.textContent).toBe("Salon");
    expect(document.querySelector('[data-widget="sensors"] .dashboard-widget-subtitle')).toBeNull();
    expect(document.querySelector(".dash")?.style.getPropertyValue("--dashboard-header-font-size")).toBe("18px");

    const grid = document.querySelector(".dash");
    const cleaning = document.getElementById("cleaning-card");
    cleaning.dataset.placementSpan = "1";
    grid.dataset.cleaningLocked = "true";
    window.dispatchEvent(new CustomEvent("dashboard:cleaning-lock-changed", {
      detail: { locked: true },
    }));
    await new Promise((resolve) => window.setTimeout(resolve, 20));

    expect(cleaning.style.gridColumn).toBe("1 / -1");
    expect(cleaning.dataset.placementSpan).toBe("1");

    grid.dataset.cleaningLocked = "false";
    window.dispatchEvent(new CustomEvent("dashboard:cleaning-lock-changed", {
      detail: { locked: false },
    }));
    await new Promise((resolve) => window.setTimeout(resolve, 20));

    expect(cleaning.style.gridColumn).toBe("");
    expect(cleaning.dataset.placementSpan).toBe("1");
  });
});
