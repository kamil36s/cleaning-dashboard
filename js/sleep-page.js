import { loadSleepHistoryData } from "./sleep-api.js";
import { analyzeSleepData, analyzeSleepHistory } from "./sleep-analysis.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const elements = {
  refresh: document.getElementById("sleep-refresh"),
  currentBadge: document.getElementById("sleep-current-badge"),
  nightLabel: document.getElementById("sleep-night-label"),
  source: document.getElementById("sleep-source"),
  rhr: document.getElementById("sleep-rhr-value"),
  rhrSource: document.getElementById("sleep-rhr-source"),
  duration: document.getElementById("sleep-duration-value"),
  durationSource: document.getElementById("sleep-duration-source"),
  window: document.getElementById("sleep-window-value"),
  start: document.getElementById("sleep-start-value"),
  startDetail: document.getElementById("sleep-start-detail"),
  wake: document.getElementById("sleep-wake-value"),
  wakeDetail: document.getElementById("sleep-wake-detail"),
  chart: document.getElementById("sleep-chart"),
  chartEmpty: document.getElementById("sleep-chart-empty"),
  chartStart: document.getElementById("sleep-chart-start"),
  chartEnd: document.getElementById("sleep-chart-end"),
  sampleCount: document.getElementById("sleep-sample-count"),
  average: document.getElementById("sleep-average-value"),
  chartSource: document.getElementById("sleep-chart-source"),
  insightCard: document.getElementById("sleep-insight-card"),
  insight: document.getElementById("sleep-insight-text"),
  insightDetail: document.getElementById("sleep-insight-detail"),
  spikeCount: document.getElementById("sleep-spike-count"),
  rhrPosition: document.getElementById("sleep-rhr-position"),
  sleepSamples: document.getElementById("sleep-sleep-samples"),
  totalNights: document.getElementById("sleep-total-nights"),
  averageDuration: document.getElementById("sleep-average-duration"),
  targetShare: document.getElementById("sleep-target-share"),
  targetShareDetail: document.getElementById("sleep-target-share-detail"),
  typicalWindow: document.getElementById("sleep-typical-window"),
  regularity: document.getElementById("sleep-regularity"),
  regularityDetail: document.getElementById("sleep-regularity-detail"),
  durationTrend: document.getElementById("sleep-duration-trend"),
  durationTrendDetail: document.getElementById("sleep-duration-trend-detail"),
  averageRhr: document.getElementById("sleep-average-rhr"),
  averageRhrDetail: document.getElementById("sleep-average-rhr-detail"),
  longestNight: document.getElementById("sleep-longest-night"),
  longestNightDetail: document.getElementById("sleep-longest-night-detail"),
  overviewRange: document.getElementById("sleep-overview-range"),
  historyInsight: document.getElementById("sleep-history-insight"),
  historyInsightText: document.getElementById("sleep-history-insight-text"),
  historyInsightDetail: document.getElementById("sleep-history-insight-detail"),
  historyList: document.getElementById("sleep-history-list"),
  historyEmpty: document.getElementById("sleep-history-empty"),
  historySourceNote: document.getElementById("sleep-history-source-note"),
  status: document.getElementById("sleep-page-status"),
};

const timeFormatter = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
});
const nightFormatter = new Intl.DateTimeFormat("pl-PL", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});
const historyDateFormatter = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

let activeRequest = null;

function createSvgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : timeFormatter.format(date);
}

function formatDuration(totalMinutes) {
  if (!Number.isFinite(totalMinutes)) return "—";
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours} h ${String(minutes).padStart(2, "0")} min`;
}

function formatClockMinutes(totalMinutes) {
  if (!Number.isFinite(totalMinutes)) return "—";
  const normalized = ((Math.round(totalMinutes) % (24 * 60)) + 24 * 60) % (24 * 60);
  const hours = Math.floor(normalized / 60);
  const minutes = normalized % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function formatSignedDuration(totalMinutes) {
  if (!Number.isFinite(totalMinutes)) return "—";
  if (totalMinutes === 0) return "bez zmiany";
  const prefix = totalMinutes > 0 ? "+" : "−";
  return `${prefix}${formatDuration(Math.abs(totalMinutes))}`;
}

function formatNightLabel(dataset) {
  const start = new Date(dataset?.sleepWindow?.start);
  const end = new Date(dataset?.sleepWindow?.end);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Nieznana noc";
  if (typeof nightFormatter.formatRange === "function") {
    return nightFormatter.formatRange(start, end);
  }
  return `${nightFormatter.format(start)} — ${nightFormatter.format(end)}`;
}

function formatHistoryRange(datasets) {
  const dates = datasets
    .map((dataset) => new Date(dataset?.sleepWindow?.end))
    .filter((date) => !Number.isNaN(date.getTime()))
    .sort((left, right) => left - right);
  if (!dates.length) return "—";
  if (dates.length === 1) return historyDateFormatter.format(dates[0]);
  if (typeof historyDateFormatter.formatRange === "function") {
    return historyDateFormatter.formatRange(dates[0], dates.at(-1));
  }
  return `${historyDateFormatter.format(dates[0])} — ${historyDateFormatter.format(dates.at(-1))}`;
}

function downsample(samples, maxPoints = 260) {
  if (samples.length <= maxPoints) return samples;
  const bucketSize = samples.length / maxPoints;
  return Array.from({ length: maxPoints }, (_, bucket) => {
    const start = Math.floor(bucket * bucketSize);
    const end = Math.max(start + 1, Math.floor((bucket + 1) * bucketSize));
    const rows = samples.slice(start, end);
    return {
      time: rows[Math.floor(rows.length / 2)].time,
      bpm: rows.reduce((sum, row) => sum + row.bpm, 0) / rows.length,
    };
  });
}

function renderChart(analysis) {
  elements.chart.replaceChildren();
  const samples = downsample(analysis.sleepSamples || []);
  elements.chartEmpty.hidden = samples.length >= 2;
  if (samples.length < 2) return;

  const width = 960;
  const height = 300;
  const padding = { top: 18, right: 18, bottom: 34, left: 42 };
  const startTime = samples[0].time;
  const endTime = samples.at(-1).time;
  const values = samples.map((sample) => sample.bpm);
  const minBpm = Math.floor(Math.min(...values) - 4);
  const maxBpm = Math.ceil(Math.max(...values) + 4);
  const x = (time) => padding.left
    + ((time - startTime) / Math.max(1, endTime - startTime))
      * (width - padding.left - padding.right);
  const y = (bpm) => padding.top
    + ((maxBpm - bpm) / Math.max(1, maxBpm - minBpm))
      * (height - padding.top - padding.bottom);

  [0, 0.25, 0.5, 0.75, 1].forEach((ratio) => {
    const lineY = padding.top + ratio * (height - padding.top - padding.bottom);
    const labelValue = Math.round(maxBpm - ratio * (maxBpm - minBpm));
    elements.chart.append(createSvgElement("line", {
      x1: padding.left,
      x2: width - padding.right,
      y1: lineY,
      y2: lineY,
      class: "sleep-chart-gridline",
    }));
    const label = createSvgElement("text", {
      x: 7,
      y: lineY + 4,
      class: "sleep-chart-axis-label",
    });
    label.textContent = String(labelValue);
    elements.chart.append(label);
  });

  const durationHours = (endTime - startTime) / (60 * 60 * 1000);
  const tickHours = durationHours > 6 ? 2 : 1;
  const tickMs = tickHours * 60 * 60 * 1000;
  for (
    let tick = Math.ceil(startTime / tickMs) * tickMs;
    tick <= endTime;
    tick += tickMs
  ) {
    elements.chart.append(createSvgElement("line", {
      x1: x(tick),
      x2: x(tick),
      y1: padding.top,
      y2: height - padding.bottom,
      class: "sleep-chart-gridline sleep-chart-time-gridline",
    }));
    const label = createSvgElement("text", {
      x: x(tick),
      y: height - 9,
      class: "sleep-chart-axis-label sleep-chart-time-label",
      "text-anchor": "middle",
    });
    label.textContent = timeFormatter.format(new Date(tick));
    elements.chart.append(label);
  }

  const points = samples.map((sample) => `${x(sample.time)},${y(sample.bpm)}`).join(" ");
  elements.chart.append(createSvgElement("polygon", {
    points: `${padding.left},${height - padding.bottom} ${points} ${width - padding.right},${height - padding.bottom}`,
    class: "sleep-chart-area",
  }));
  elements.chart.append(createSvgElement("polyline", {
    points,
    class: "sleep-chart-line",
  }));

  if (Number.isFinite(analysis.rhrAt) && Number.isFinite(analysis.rhr)) {
    elements.chart.append(createSvgElement("circle", {
      cx: x(analysis.rhrAt),
      cy: y(analysis.rhr),
      r: 5,
      class: "sleep-chart-rhr",
    }));
  }

  elements.chart.setAttribute(
    "aria-label",
    `Tętno podczas snu od ${formatTime(analysis.sleepStart)} do ${formatTime(analysis.wakeTime)}, zakres ${Math.round(Math.min(...values))}–${Math.round(Math.max(...values))} BPM.`,
  );
}

function renderSources(dataset = {}) {
  const sleepSource = dataset.sourceLabel || "nieokreślone";
  const heartRateSource = dataset.heartRateSource || "brak próbek";
  elements.source.textContent = `Źródło: ${sleepSource}`;
  elements.rhrSource.textContent = `Źródło tętna: ${heartRateSource}`;
  elements.durationSource.textContent = `Źródło snu: ${sleepSource}`;
  elements.startDetail.textContent = `Źródło snu: ${sleepSource}`;
  elements.wakeDetail.textContent = `Źródło snu: ${sleepSource}`;
  elements.chartSource.textContent = `Źródło tętna: ${heartRateSource}`;
}

function resetView(message = "Czekam na próbki z urządzenia.", dataset = {}) {
  elements.rhr.textContent = "—";
  elements.duration.textContent = "—";
  elements.window.textContent = "Brak wykrytej nocy";
  elements.start.textContent = "—";
  elements.wake.textContent = "—";
  elements.sampleCount.textContent = "0";
  elements.average.textContent = "—";
  elements.chartStart.textContent = "—";
  elements.chartEnd.textContent = "—";
  elements.chart.replaceChildren();
  elements.chartEmpty.hidden = false;
  elements.chartEmpty.textContent = message;
  elements.insightCard.dataset.tone = "empty";
  elements.insight.textContent = "Brak pełnej nocy do analizy.";
  elements.insightDetail.textContent = "Potrzebne są poprawne próbki BPM i ruchu obejmujące okres snu.";
  elements.spikeCount.textContent = "—";
  elements.rhrPosition.textContent = "—";
  elements.sleepSamples.textContent = "—";
  renderSources(dataset);
}

export function renderSleepPage(input) {
  const dataset = Array.isArray(input)
    ? {
      sourceLabel: "zewnętrzny skrypt BLE",
      heartRateSource: "zewnętrzny skrypt BLE",
      samples: input,
      sleepWindow: null,
    }
    : (input || {});
  const analysis = analyzeSleepData(dataset.samples, { sleepWindow: dataset.sleepWindow });
  elements.sampleCount.textContent = String(analysis.samples.length);
  elements.average.textContent = Number.isFinite(analysis.dailyAverageBpm)
    ? String(Math.round(analysis.dailyAverageBpm))
    : "—";

  if (!analysis.hasSleep) {
    resetView("Nie udało się wykryć pełnego przedziału snu.", dataset);
    elements.sampleCount.textContent = String(analysis.samples.length);
    elements.average.textContent = Number.isFinite(analysis.dailyAverageBpm)
      ? String(Math.round(analysis.dailyAverageBpm))
      : "—";
    return analysis;
  }

  elements.nightLabel.textContent = formatNightLabel(dataset);
  elements.rhr.textContent = String(analysis.rhr ?? "—");
  elements.duration.textContent = formatDuration(analysis.durationMinutes);
  elements.window.textContent = `${formatTime(analysis.sleepStart)} — ${formatTime(analysis.wakeTime)}`;
  elements.start.textContent = formatTime(analysis.sleepStart);
  elements.wake.textContent = formatTime(analysis.wakeTime);
  elements.chartStart.textContent = formatTime(analysis.sleepStart);
  elements.chartEnd.textContent = formatTime(analysis.wakeTime);
  elements.sampleCount.textContent = String(analysis.samples.length);
  elements.average.textContent = Number.isFinite(analysis.dailyAverageBpm)
    ? String(Math.round(analysis.dailyAverageBpm))
    : "—";
  elements.insight.textContent = analysis.insight;
  elements.insightDetail.textContent = analysis.spikeCount >= 3
    ? "Powtarzające się skoki mogą wskazywać na fragmentację snu."
    : Number.isFinite(analysis.rhrAt)
      ? "Wniosek wynika z momentu wystąpienia najniższego RHR w przebiegu nocy."
      : "Czas snu pochodzi z urządzenia; brakuje próbek tętna do wyliczenia RHR.";
  elements.insightCard.dataset.tone = analysis.spikeCount >= 3 ? "restless" : "ready";
  elements.rhrPosition.textContent = Number.isFinite(analysis.rhrAt)
    ? (analysis.rhrAt <= analysis.sleepMidpoint ? "pierwsza połowa" : "druga połowa")
    : "brak danych";
  elements.sleepSamples.textContent = String(analysis.sleepSamples.length);
  elements.spikeCount.textContent = analysis.sleepSamples.length
    ? String(analysis.spikeCount)
    : "brak danych";
  elements.chartEmpty.textContent = analysis.sleepSamples.length
    ? "Za mało próbek tętna, aby narysować wykres."
    : "Brak próbek tętna w przedziale tej nocy.";
  renderSources(dataset);
  renderChart(analysis);
  return analysis;
}

function selectHistoryNight(dataset, index, { scroll = false } = {}) {
  const analysis = renderSleepPage(dataset);
  elements.currentBadge.textContent = index === 0 ? "Ostatnia noc" : "Noc z historii";
  elements.historyList.querySelectorAll(".sleep-history-item").forEach((button) => {
    const active = button.dataset.sleepId === dataset.id;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "true" : "false");
  });
  if (scroll) {
    document.querySelector(".sleep-current-head")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  return analysis;
}

function renderOverview(datasets) {
  const summary = analyzeSleepHistory(datasets);

  elements.totalNights.textContent = String(summary.nights);
  elements.averageDuration.textContent = Number.isFinite(summary.averageDurationMinutes)
    ? formatDuration(summary.averageDurationMinutes)
    : "—";
  elements.targetShare.textContent = Number.isFinite(summary.targetShare)
    ? `${summary.targetShare}%`
    : "—";
  elements.targetShareDetail.textContent = summary.nights
    ? `${summary.targetNights} z ${summary.nights} zarejestrowanych nocy`
    : "brak nocy do porównania";
  elements.typicalWindow.textContent = Number.isFinite(summary.typicalStartMinutes)
    && Number.isFinite(summary.typicalWakeMinutes)
    ? `${formatClockMinutes(summary.typicalStartMinutes)}–${formatClockMinutes(summary.typicalWakeMinutes)}`
    : "—";
  elements.regularity.textContent = Number.isFinite(summary.regularityMinutes)
    ? `± ${summary.regularityMinutes} min`
    : "—";
  elements.regularityDetail.textContent = Number.isFinite(summary.startVariabilityMinutes)
    && Number.isFinite(summary.wakeVariabilityMinutes)
    ? `sen ±${summary.startVariabilityMinutes} min · pobudka ±${summary.wakeVariabilityMinutes} min`
    : "potrzeba co najmniej jednej pełnej nocy";
  elements.durationTrend.textContent = formatSignedDuration(summary.durationTrendMinutes);
  elements.durationTrendDetail.textContent = Number.isFinite(summary.durationTrendMinutes)
    ? `średnia z ostatnich ${summary.recentNightCount} nocy vs poprzednie`
    : "potrzeba co najmniej 6 nocy";
  elements.averageRhr.textContent = Number.isFinite(summary.averageRhr)
    ? `${summary.averageRhr} bpm`
    : "—";
  elements.averageRhrDetail.textContent = summary.rhrNights
    ? `z ${summary.rhrNights} nocy z próbkami BPM`
    : "brak nocy z próbkami BPM";
  elements.longestNight.textContent = summary.longest
    ? formatDuration(summary.longest.analysis.durationMinutes)
    : "—";
  elements.longestNightDetail.textContent = summary.longest
    ? formatNightLabel(summary.longest.dataset)
    : "—";

  if (summary.nights < 2) {
    elements.historyInsight.dataset.tone = "empty";
    elements.historyInsightText.textContent = "Potrzeba więcej nocy, aby zobaczyć wzorzec.";
    elements.historyInsightDetail.textContent = "Pierwsza noc tworzy punkt odniesienia; wnioski pojawią się wraz z historią.";
  } else {
    const trendIsShorter = summary.durationTrendMinutes <= -30;
    const outsideTargetOften = summary.targetShare < 50;
    elements.historyInsight.dataset.tone = trendIsShorter || outsideTargetOften ? "attention" : "ready";
    elements.historyInsightText.textContent = trendIsShorter
      ? "Ostatnie noce są krótsze od wcześniejszych."
      : summary.durationTrendMinutes >= 30
        ? "Ostatnie noce są dłuższe od wcześniejszych."
        : summary.regularityMinutes <= 45
          ? "Godziny snu są dość regularne."
          : "Historia pokazuje zmienny rytm snu.";
    elements.historyInsightDetail.textContent = `${summary.targetShare}% nocy mieści się w zakresie 7–9 h. Typowe okno to ${formatClockMinutes(summary.typicalStartMinutes)}–${formatClockMinutes(summary.typicalWakeMinutes)}; odchylenie godzin wynosi około ${summary.regularityMinutes} min.`;
  }
  elements.overviewRange.textContent = formatHistoryRange(datasets);
}

function createHistoryItem(dataset, index) {
  const analysis = analyzeSleepData(dataset.samples, { sleepWindow: dataset.sleepWindow });
  const button = document.createElement("button");
  button.type = "button";
  button.className = `sleep-history-item${index === 0 ? " is-active" : ""}`;
  button.dataset.sleepId = dataset.id;
  button.setAttribute("aria-current", index === 0 ? "true" : "false");

  const date = document.createElement("span");
  date.className = "sleep-history-date";
  date.textContent = formatNightLabel(dataset);
  const source = document.createElement("span");
  source.className = `sleep-history-source is-${dataset.sourceKind}`;
  source.textContent = dataset.sourceKind === "watch" ? "Smartwatch" : "COLMI Ring";
  const duration = document.createElement("strong");
  duration.textContent = formatDuration(analysis.durationMinutes);
  const window = document.createElement("span");
  window.className = "sleep-history-window";
  window.textContent = `${formatTime(analysis.sleepStart)} — ${formatTime(analysis.wakeTime)}`;
  const rhr = document.createElement("span");
  rhr.className = "sleep-history-rhr";
  rhr.textContent = Number.isFinite(analysis.rhr) ? `RHR ${analysis.rhr} bpm` : "RHR —";

  button.append(date, source, duration, window, rhr);
  button.addEventListener("click", () => selectHistoryNight(dataset, index, { scroll: true }));
  return button;
}

function formatHealthSyncStatus(sources = {}) {
  const lastSync = new Date(sources.watch?.lastSync);
  if (Number.isNaN(lastSync.getTime())) {
    return "Smartwatch: brak synchronizacji Health Connect · użyj „Sync now” w Dashboard Steps";
  }
  const formatted = new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(lastSync);
  const stale = Date.now() - lastSync.getTime() > 48 * 60 * 60 * 1000;
  return stale
    ? `Smartwatch: dane nieaktualne · ostatnia synchronizacja ${formatted} · użyj „Sync now” w Dashboard Steps`
    : `Smartwatch: Health Connect zsynchronizowany ${formatted}`;
}

function renderHistory(datasets, sources) {
  elements.historyList.replaceChildren(...datasets.map(createHistoryItem));
  elements.historyEmpty.hidden = datasets.length > 0;
  elements.historySourceNote.textContent = formatHealthSyncStatus(sources);
  renderOverview(datasets);
}

export async function loadSleepPage() {
  activeRequest?.abort();
  activeRequest = new AbortController();
  elements.refresh.disabled = true;
  elements.source.textContent = "Źródło: sprawdzam ring i watch…";
  elements.status.dataset.tone = "loading";
  elements.status.textContent = "Ładuję dane snu…";

  try {
    const result = await loadSleepHistoryData({ signal: activeRequest.signal });
    renderHistory(result.datasets, result.sources);
    const dataset = result.latest;
    const analysis = selectHistoryNight(dataset, 0);
    elements.status.dataset.tone = analysis.hasSleep ? "ready" : "empty";
    elements.status.textContent = analysis.hasSleep
      ? analysis.sleepSamples.length
        ? `Analiza gotowa · ${dataset.sourceDetail}.`
        : `Czas snu pobrany · ${dataset.sourceDetail}. Brak nocnych próbek tętna, więc RHR i wykres pozostają puste.`
      : "Dane zostały pobrane, ale nie zawierają pełnego przedziału snu.";
  } catch (error) {
    if (error?.name === "AbortError") return;
    resetView("Brak danych z lokalnego API.", {
      sourceLabel: "niedostępne",
      heartRateSource: "niedostępne",
    });
    elements.status.dataset.tone = "error";
    elements.status.textContent = `Nie udało się pobrać danych: ${String(error?.message || error)}`;
  } finally {
    elements.refresh.disabled = false;
  }
}

elements.refresh?.addEventListener("click", loadSleepPage);
window.addEventListener("sleep:data", (event) => {
  if (!Array.isArray(event.detail) && !event.detail?.samples) return;
  const analysis = renderSleepPage(event.detail);
  elements.status.dataset.tone = analysis.hasSleep ? "ready" : "empty";
  elements.status.textContent = analysis.hasSleep
    ? "Dane zostały zaktualizowane."
    : "Przekazane dane nie zawierają pełnego przedziału snu.";
});
window.addEventListener("pagehide", () => activeRequest?.abort(), { once: true });

if (elements.chart) loadSleepPage();
