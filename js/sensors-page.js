const LATEST_URL = "/api/sensor/latest";
const PAGE_POLL_MS = 60 * 1000;

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function padNumber(value) {
  return String(value).padStart(2, "0");
}

function localDateKey(date) {
  return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`;
}

function localMonthKey(date) {
  return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}`;
}

function parseDayKey(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return localDateKey(date) === value ? date : null;
}

function parseMonthKey(value) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(value || ""));
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  return localMonthKey(date) === value ? date : null;
}

export function localDayRange(dayKey) {
  const startDate = parseDayKey(dayKey);
  if (!startDate) throw new Error("Nieprawidłowa data");
  const endDate = new Date(startDate);
  endDate.setDate(endDate.getDate() + 1);
  return {
    start: startDate.getTime(),
    end: endDate.getTime(),
    label: startDate.toLocaleDateString("pl-PL", {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    }),
  };
}

export function localMonthRange(monthKey) {
  const startDate = parseMonthKey(monthKey);
  if (!startDate) throw new Error("Nieprawidłowy miesiąc");
  const endDate = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 1);
  return {
    start: startDate.getTime(),
    end: endDate.getTime(),
    label: startDate.toLocaleDateString("pl-PL", { month: "long", year: "numeric" }),
  };
}

export function normalizeSensorRows(rows, rangeStart = -Infinity, rangeEnd = Infinity) {
  if (rangeStart && typeof rangeStart === "object") {
    rangeEnd = rangeStart.end;
    rangeStart = rangeStart.start;
  }
  return (Array.isArray(rows) ? rows : [])
    .map((row) => ({
      timestamp: new Date(row?.timestamp).getTime(),
      temperature: finiteNumber(row?.temperature_c ?? row?.temp_c),
      humidity: finiteNumber(row?.humidity_percent ?? row?.hum_pct),
      battery: finiteNumber(row?.battery_pct),
    }))
    .filter((row) => (
      Number.isFinite(row.timestamp)
      && row.timestamp >= rangeStart
      && row.timestamp < rangeEnd
    ))
    .sort((left, right) => left.timestamp - right.timestamp);
}

export function summarizeSensorValues(rows, key) {
  const values = rows.map((row) => row[key]).filter(Number.isFinite);
  if (!values.length) return null;
  return {
    minimum: Math.min(...values),
    average: values.reduce((sum, value) => sum + value, 0) / values.length,
    maximum: Math.max(...values),
  };
}

function formatAxisDate(timestamp) {
  return new Date(timestamp).toLocaleDateString("pl-PL", { day: "numeric", month: "short" });
}

function formatDateTime(timestamp) {
  return new Date(timestamp).toLocaleString("pl-PL", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function chartTicks(rangeStart, rangeEnd, mode) {
  if (mode === "day") {
    const startDate = new Date(rangeStart);
    return [0, 6, 12, 18].map((hour) => {
      const tick = new Date(startDate);
      tick.setHours(hour, 0, 0, 0);
      return { timestamp: tick.getTime(), label: `${padNumber(hour)}:00` };
    }).concat({ timestamp: rangeEnd, label: "23:59" });
  }
  return Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const timestamp = index === 4 ? rangeEnd - 1 : rangeStart + ratio * (rangeEnd - rangeStart);
    return { timestamp: index === 4 ? rangeEnd : timestamp, label: formatAxisDate(timestamp) };
  });
}

export function buildSensorChartSvg(rows, {
  key,
  color,
  unit,
  label,
  rangeStart,
  rangeEnd,
  mode = "day",
} = {}) {
  const points = rows.filter((row) => Number.isFinite(row[key]));
  if (!points.length || !Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd)) return "";

  const width = 1000;
  const height = 310;
  const pad = { top: 24, right: 22, bottom: 42, left: 64 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const timeRange = Math.max(1, rangeEnd - rangeStart);
  const values = points.map((point) => point[key]);
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  const minimumPadding = key === "humidity" ? 2 : .5;
  const padding = Math.max((maximum - minimum) * .15, minimumPadding);
  minimum -= padding;
  maximum += padding;
  if (key === "humidity") {
    minimum = Math.max(0, minimum);
    maximum = Math.min(100, maximum);
  }
  const valueRange = maximum - minimum || 1;

  const x = (timestamp) => pad.left + ((timestamp - rangeStart) / timeRange) * plotWidth;
  const y = (value) => pad.top + (1 - (value - minimum) / valueRange) * plotHeight;

  const horizontalGrid = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const yPos = pad.top + ratio * plotHeight;
    const value = maximum - ratio * valueRange;
    return `<line class="sensor-chart-grid" x1="${pad.left}" y1="${yPos.toFixed(2)}" x2="${width - pad.right}" y2="${yPos.toFixed(2)}" />`
      + `<text class="sensor-chart-axis-label" x="${pad.left - 10}" y="${(yPos + 4).toFixed(2)}" text-anchor="end">${value.toFixed(1)}${unit}</text>`;
  }).join("");

  const ticks = chartTicks(rangeStart, rangeEnd, mode);
  const verticalGrid = ticks.map((tick, index) => {
    const xPos = x(tick.timestamp);
    const anchor = index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle";
    return `<line class="sensor-chart-grid" x1="${xPos.toFixed(2)}" y1="${pad.top}" x2="${xPos.toFixed(2)}" y2="${height - pad.bottom}" />`
      + `<text class="sensor-chart-axis-label" x="${xPos.toFixed(2)}" y="${height - 15}" text-anchor="${anchor}">${tick.label}</text>`;
  }).join("");

  let commands = points.map((point, index) => (
    `${index ? "L" : "M"}${x(point.timestamp).toFixed(2)},${y(point[key]).toFixed(2)}`
  ));
  if (points.length === 1) {
    const xPos = x(points[0].timestamp);
    const yPos = y(points[0][key]);
    commands = [`M${(xPos - 2).toFixed(2)},${yPos.toFixed(2)}`, `L${(xPos + 2).toFixed(2)},${yPos.toFixed(2)}`];
  }
  const path = `<path class="sensor-chart-line" d="${commands.join(" ")}" stroke="${color}"><title>${points.length} odczytów · ${formatDateTime(points.at(-1).timestamp)}</title></path>`;

  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${label}">`
    + horizontalGrid + verticalGrid + path + `</svg>`;
}

async function fetchJson(url) {
  const separator = url.includes("?") ? "&" : "?";
  const response = await fetch(`${url}${separator}t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function humidityDescription(value) {
  if (!Number.isFinite(value)) return "Brak odczytu w wybranym okresie";
  if (value >= 40 && value <= 60) return "wilgotność w normie · 40–60%";
  if (value < 40) return "poniżej zalecanego zakresu";
  return "powyżej zalecanego zakresu";
}

function setLiveState(element, ageSeconds) {
  if (!element) return;
  const label = element.querySelector("strong");
  if (!Number.isFinite(ageSeconds)) {
    element.dataset.state = "offline";
    label.textContent = "BRAK SYGNAŁU";
  } else if (ageSeconds > 150) {
    element.dataset.state = "stale";
    label.textContent = "NIEAKTUALNY";
  } else {
    element.dataset.state = "live";
    label.textContent = "LIVE";
  }
}

function setBattery(element, valueElement, value) {
  if (!element || !valueElement || !Number.isFinite(value)) return;
  const level = Math.max(0, Math.min(100, Math.round(value)));
  valueElement.textContent = `${level}%`;
  element.style.setProperty("--sensors-battery-level", `${level}%`);
  element.classList.remove("battery-unknown", "battery-high", "battery-medium", "battery-low");
  element.classList.add(level >= 60 ? "battery-high" : level >= 30 ? "battery-medium" : "battery-low");
  element.setAttribute("aria-label", `Poziom baterii ${level}%`);
}

function renderSummary(element, summary, unit) {
  const values = element?.querySelectorAll("dd");
  if (!values?.length) return;
  const rendered = summary
    ? [summary.minimum, summary.average, summary.maximum].map((value) => `${value.toFixed(1)}${unit}`)
    : ["—", "—", "—"];
  values.forEach((node, index) => { node.textContent = rendered[index]; });
}

export function initSensorsPage() {
  const today = new Date();
  const state = {
    mode: "day",
    day: localDateKey(today),
    month: localMonthKey(today),
  };
  const elements = {
    refresh: document.getElementById("sensors-page-refresh"),
    modeDay: document.getElementById("sensors-page-mode-day"),
    modeMonth: document.getElementById("sensors-page-mode-month"),
    previous: document.getElementById("sensors-page-previous"),
    next: document.getElementById("sensors-page-next"),
    today: document.getElementById("sensors-page-today"),
    day: document.getElementById("sensors-page-day"),
    month: document.getElementById("sensors-page-month"),
    periodLabel: document.getElementById("sensors-page-period-label"),
    periodTemperature: document.getElementById("sensors-temperature-period"),
    periodHumidity: document.getElementById("sensors-humidity-period"),
    countLabel: document.getElementById("sensors-page-count-label"),
    live: document.getElementById("sensors-page-live"),
    battery: document.getElementById("sensors-page-battery"),
    batteryValue: document.getElementById("sensors-page-battery-value"),
    updated: document.getElementById("sensors-page-updated"),
    deviceTitle: document.getElementById("sensors-page-device-title"),
    deviceId: document.getElementById("sensors-page-device-id"),
    temperature: document.getElementById("sensors-page-temperature"),
    temperatureF: document.getElementById("sensors-page-temperature-f"),
    humidity: document.getElementById("sensors-page-humidity"),
    humidityRange: document.getElementById("sensors-page-humidity-range"),
    count: document.getElementById("sensors-page-count"),
    temperatureChart: document.getElementById("sensors-temperature-chart"),
    temperatureEmpty: document.getElementById("sensors-temperature-empty"),
    temperatureSummary: document.getElementById("sensors-temperature-summary"),
    humidityChart: document.getElementById("sensors-humidity-chart"),
    humidityEmpty: document.getElementById("sensors-humidity-empty"),
    humiditySummary: document.getElementById("sensors-humidity-summary"),
  };

  function selectedRange() {
    return state.mode === "day" ? localDayRange(state.day) : localMonthRange(state.month);
  }

  function historyUrl() {
    const value = state.mode === "day" ? state.day : state.month;
    return `/api/sensor/history?${state.mode === "day" ? "date" : "month"}=${encodeURIComponent(value)}`;
  }

  function syncControls() {
    const range = selectedRange();
    elements.modeDay.setAttribute("aria-pressed", String(state.mode === "day"));
    elements.modeMonth.setAttribute("aria-pressed", String(state.mode === "month"));
    elements.day.hidden = state.mode !== "day";
    elements.month.hidden = state.mode !== "month";
    elements.day.value = state.day;
    elements.month.value = state.month;
    elements.periodLabel.textContent = range.label;
    const periodText = state.mode === "day" ? "Wybrany dzień · 00:00–23:59" : "Wybrany miesiąc";
    elements.periodTemperature.textContent = periodText;
    elements.periodHumidity.textContent = periodText;
    elements.countLabel.textContent = state.mode === "day" ? "Próbki · dzień" : "Próbki · miesiąc";
  }

  async function load() {
    elements.refresh.disabled = true;
    const range = selectedRange();
    try {
      const [latest, history] = await Promise.all([fetchJson(LATEST_URL), fetchJson(historyUrl())]);
      const rows = normalizeSensorRows(history, range);
      const latestPoint = normalizeSensorRows([latest], range).at(-1);
      if (latestPoint && !rows.some((row) => row.timestamp === latestPoint.timestamp)) rows.push(latestPoint);
      rows.sort((left, right) => left.timestamp - right.timestamp);

      const selectedLatest = rows.at(-1);
      const temperature = selectedLatest?.temperature ?? null;
      const humidity = selectedLatest?.humidity ?? null;
      const battery = finiteNumber(latest?.battery_pct);
      const ageSeconds = finiteNumber(latest?.age_seconds);
      const timestamp = new Date(latest?.timestamp).getTime();
      const sensorId = String(latest?.sensor_id || "desk");

      elements.deviceTitle.textContent = sensorId === "desk" ? "Biurko" : sensorId;
      elements.deviceId.textContent = sensorId;
      elements.temperature.textContent = Number.isFinite(temperature) ? temperature.toFixed(1) : "—";
      elements.temperatureF.textContent = Number.isFinite(temperature) ? `${((temperature * 9 / 5) + 32).toFixed(1)} °F` : "— °F";
      elements.humidity.textContent = Number.isFinite(humidity) ? String(Math.round(humidity)) : "—";
      elements.humidityRange.textContent = humidityDescription(humidity);
      elements.count.textContent = String(rows.length);
      elements.updated.textContent = Number.isFinite(timestamp) ? `Odczyt ${formatDateTime(timestamp)}` : "Brak odczytu";
      setLiveState(elements.live, ageSeconds);
      setBattery(elements.battery, elements.batteryValue, battery);

      const rangeLabel = state.mode === "day" ? `${range.label}, od 00:00 do 23:59` : range.label;
      const temperatureSvg = buildSensorChartSvg(rows, {
        key: "temperature", color: "#ff8a65", unit: "°", label: `Temperatura · ${rangeLabel}`,
        rangeStart: range.start, rangeEnd: range.end, mode: state.mode,
      });
      const humiditySvg = buildSensorChartSvg(rows, {
        key: "humidity", color: "#5ca9ff", unit: "%", label: `Wilgotność · ${rangeLabel}`,
        rangeStart: range.start, rangeEnd: range.end, mode: state.mode,
      });
      elements.temperatureChart.innerHTML = temperatureSvg;
      elements.humidityChart.innerHTML = humiditySvg;
      elements.temperatureEmpty.hidden = Boolean(temperatureSvg);
      elements.humidityEmpty.hidden = Boolean(humiditySvg);
      renderSummary(elements.temperatureSummary, summarizeSensorValues(rows, "temperature"), "°");
      renderSummary(elements.humiditySummary, summarizeSensorValues(rows, "humidity"), "%");
    } catch (error) {
      console.warn("sensor history page fetch error", error);
      setLiveState(elements.live, null);
    } finally {
      elements.refresh.disabled = false;
    }
  }

  function changeMode(mode) {
    if (mode === state.mode) return;
    if (mode === "month") {
      state.month = state.day.slice(0, 7);
    } else if (!state.day.startsWith(state.month)) {
      state.day = `${state.month}-01`;
    }
    state.mode = mode;
    syncControls();
    load();
  }

  function movePeriod(delta) {
    if (state.mode === "day") {
      const date = parseDayKey(state.day);
      date.setDate(date.getDate() + delta);
      state.day = localDateKey(date);
    } else {
      const date = parseMonthKey(state.month);
      date.setMonth(date.getMonth() + delta);
      state.month = localMonthKey(date);
    }
    syncControls();
    load();
  }

  elements.refresh.addEventListener("click", load);
  elements.modeDay.addEventListener("click", () => changeMode("day"));
  elements.modeMonth.addEventListener("click", () => changeMode("month"));
  elements.previous.addEventListener("click", () => movePeriod(-1));
  elements.next.addEventListener("click", () => movePeriod(1));
  elements.today.addEventListener("click", () => {
    const now = new Date();
    state.day = localDateKey(now);
    state.month = localMonthKey(now);
    syncControls();
    load();
  });
  elements.day.addEventListener("change", () => {
    if (!parseDayKey(elements.day.value)) return;
    state.day = elements.day.value;
    state.month = state.day.slice(0, 7);
    syncControls();
    load();
  });
  elements.month.addEventListener("change", () => {
    if (!parseMonthKey(elements.month.value)) return;
    state.month = elements.month.value;
    syncControls();
    load();
  });

  syncControls();
  load();
  window.setInterval(load, PAGE_POLL_MS);
}

if (document.querySelector("[data-sensors-page]")) initSensorsPage();
