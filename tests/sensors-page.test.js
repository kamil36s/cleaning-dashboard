import { describe, expect, it } from "vitest";

import {
  buildSensorChartSvg,
  localDayRange,
  localMonthRange,
  normalizeSensorRows,
  summarizeSensorValues,
} from "../js/sensors-page.js";

const DAY = localDayRange("2026-09-12");

describe("sensor history page", () => {
  it("keeps and sorts every real reading from the selected calendar day", () => {
    const rows = normalizeSensorRows([
      { timestamp: "2026-09-12T19:40:00", temperature_c: 22.7, humidity_percent: 52.4 },
      { timestamp: "2026-09-11T19:00:00", temperature_c: 19, humidity_percent: 60 },
      { timestamp: "2026-09-12T19:35:00", temperature_c: 22.6, humidity_percent: 52.7 },
      { timestamp: "invalid", temperature_c: 99, humidity_percent: 99 },
    ], DAY);

    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.temperature)).toEqual([22.6, 22.7]);
  });

  it("builds a full local calendar-month range", () => {
    const range = localMonthRange("2026-09");

    expect(new Date(range.start).getDate()).toBe(1);
    expect(new Date(range.end).getMonth()).toBe(9);
    expect(new Date(range.end).getDate()).toBe(1);
  });

  it("calculates min, average and max from displayed readings", () => {
    expect(summarizeSensorValues([
      { temperature: 21 },
      { temperature: 22 },
      { temperature: 23 },
    ], "temperature")).toEqual({ minimum: 21, average: 22, maximum: 23 });
  });

  it("draws all readings as one line without a cloud of points", () => {
    const rows = normalizeSensorRows([
      { timestamp: "2026-09-12T18:00:00", temperature_c: 22.4, humidity_percent: 52.1 },
      { timestamp: "2026-09-12T18:01:00", temperature_c: 22.5, humidity_percent: 52.2 },
      { timestamp: "2026-09-12T19:00:00", temperature_c: 22.8, humidity_percent: 52.5 },
    ], DAY);

    const svg = buildSensorChartSvg(rows, {
      key: "temperature",
      color: "#ff8a65",
      unit: "°",
      label: "Temperatura",
      rangeStart: DAY.start,
      rangeEnd: DAY.end,
      mode: "day",
    });

    expect(svg).not.toContain("sensor-chart-point");
    expect(svg.match(/class="sensor-chart-line"/g)).toHaveLength(1);
    expect(svg).toContain("00:00");
    expect(svg).toContain("23:59");
  });
});
