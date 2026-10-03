import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function sensorMarkup() {
  return `
    <span id="room-temp"></span>
    <span id="room-temp-f"></span>
    <span id="room-hum"></span>
    <span id="temp-trend"></span>
    <span id="hum-range-icon"></span>
    <span id="hum-range"></span>
    <span id="hum-target-range"></span>
    <span id="comfort-pill"></span>
    <span id="comfort-desc"></span>
    <span id="sensor-location-name">Biurko</span>
    <span id="sensor-freshness" class="sensor-live-status"><i></i><strong>Łączenie…</strong></span>
    <span id="sensor-battery" class="sensor-battery battery-unknown"><i></i><span id="room-batt"></span></span>
    <span id="room-updated"></span>
  `;
}

describe("sensor widget", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    document.body.innerHTML = sensorMarkup();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders the local BLE reading and presentation states", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        timestamp: "2026-09-12T19:35:15.876",
        sensor_id: "desk",
        temp_c: 22.68,
        hum_pct: 52.59,
        battery_pct: 68,
        age_seconds: 2,
      }),
    });

    const { initSensorWidget } = await import("../js/widget-sensors.js?test=local-ble");
    initSensorWidget({
      url: "/api/sensor/latest",
      historyUrl: "/api/sensor/history",
      pollMs: 30_000,
    });

    await vi.waitFor(() => expect(document.querySelector("#room-temp").textContent).toBe("22.7"));

    expect(document.querySelector("#room-hum").textContent).toBe("53");
    expect(document.querySelector("#temp-trend").textContent).toBe("Stabilna");
    expect(document.querySelector("#hum-range").textContent).toBe("W normie");
    expect(document.querySelector("#hum-target-range").textContent).toBe("40–60%");
    expect(document.querySelector("#comfort-pill").textContent).toBe("Optymalne");
    expect(document.querySelector("#room-batt").textContent).toBe("68");
    expect(document.querySelector("#room-updated").textContent).toMatch(/^\d{2}:\d{2}$/);
    expect(document.querySelector("#sensor-freshness").textContent).toBe("LIVE");
    expect(document.querySelector("#sensor-freshness").dataset.state).toBe("live");
    expect(document.querySelector("#sensor-battery").classList.contains("battery-high")).toBe(true);
    expect(document.querySelector("#sensor-battery").style.getPropertyValue("--sensor-battery-level")).toBe("68%");
    expect(document.querySelector("#sensor-location-name").textContent).toBe("Biurko");
    expect(global.fetch.mock.calls[0][0]).toContain("/api/sensor/latest?");
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
