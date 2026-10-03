import { ringApi } from "./ring-api.js";
import {
    batteryPresentation, capabilityLabel, connectionPresentation, consolidateSleepNights, formatDateTime, formatDuration, heartRateZone,
    normalizeActivityRecords, sanitizeHeartRateRecords,
} from "./ring-view.js";

const elements = {
    title: document.querySelector("#ring-page-title"),
    status: document.querySelector("#ring-status"),
    statusLabel: document.querySelector("#ring-status-label"),
    notice: document.querySelector("#ring-notice"),
    mode: document.querySelector("#ring-mode-banner"),
    connectCard: document.querySelector("#ring-connect-card"),
    sync: document.querySelector("#ring-sync"),
    disconnect: document.querySelector("#ring-disconnect"),
    deviceRefresh: document.querySelector("#ring-device-refresh"),
    diagnosticsRefresh: document.querySelector("#ring-diagnostics-refresh"),
    brandDeviceName: document.querySelector("#ring-brand-device-name"),
    sidebarBattery: document.querySelector("#ring-sidebar-battery"),
    sidebarBatteryLabel: document.querySelector("#ring-sidebar-battery-label"),
    sidebarBatteryValue: document.querySelector("#ring-sidebar-battery-value"),
    sidebarBatteryTrack: document.querySelector("#ring-sidebar-battery-track"),
    sidebarBatteryFill: document.querySelector("#ring-sidebar-battery-fill"),
    sidebarWear: document.querySelector("#ring-sidebar-wear"),
    sidebarWearLabel: document.querySelector("#ring-sidebar-wear-label"),
};

const titleByTab = {
    overview: "Przegląd", heart: "Serce", sleep: "Sen", spo2: "SpO₂",
    activity: "Aktywność", hrv: "HRV", device: "Urządzenie", diagnostics: "Diagnostyka",
};

let currentState = null;
let busy = false;
let refreshRunning = false;
const localDay = (value) => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw" }).format(new Date(value));
const chartTimeFormatter = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" });
let selectedHeartDay = localDay(Date.now());
let cachedHistory = {};

function setBusy(value, label) {
    busy = value;
    document.body.classList.toggle("is-ring-busy", value);
    if (label) setStatus(value ? "working" : currentState?.collector?.status, label);
    renderActions();
}

function setStatus(state, label) {
    elements.status.dataset.state = state || "offline";
    elements.statusLabel.textContent = label || "Collector offline";
}

function showNotice(message, kind = "error") {
    elements.notice.textContent = message;
    elements.notice.dataset.kind = kind;
    elements.notice.hidden = !message;
}

function text(selector, value) {
    const node = document.querySelector(selector);
    if (node) node.textContent = value;
}

function addDetail(list, label, value) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value ?? "Brak";
    row.append(term, description);
    list.append(row);
}

function renderActions() {
    const connected = ["connected", "syncing", "measuring"].includes(currentState?.collector?.status);
    elements.sync.disabled = busy || !connected;
    elements.disconnect.hidden = !connected;
    elements.disconnect.disabled = busy;
    elements.deviceRefresh.disabled = busy || !connected;
}

function renderConnectCard(state) {
    const presentation = connectionPresentation(state);
    if (state.collector?.automatic && ["scanning", "searching", "connecting"].includes(state.collector.status)) {
        presentation.action = null;
        presentation.copy = state.collector.message;
    }
    elements.connectCard.replaceChildren();
    elements.connectCard.dataset.kind = presentation.kind;
    const icon = document.createElement("div");
    icon.className = "ring-connect-icon";
    icon.textContent = presentation.kind === "connected" ? "✓" : "○";
    const copy = document.createElement("div");
    const title = document.createElement("h3");
    const paragraph = document.createElement("p");
    title.textContent = presentation.title;
    paragraph.textContent = presentation.copy;
    copy.append(title, paragraph);
    if (state.collector?.recovery) {
        const recovery = document.createElement("p");
        recovery.className = "ring-recovery";
        recovery.textContent = state.collector.recovery;
        copy.append(recovery);
    }
    elements.connectCard.append(icon, copy);

    if (presentation.action) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ring-button";
        button.textContent = presentation.action;
        button.disabled = busy;
        button.addEventListener("click", () => presentation.kind === "empty" ? scan() : connect(state.device.deviceId));
        elements.connectCard.append(button);
    }

    const found = (state.devices || []).filter((device) => device.deviceId !== state.device?.deviceId);
    if (found.length) {
        const list = document.createElement("div");
        list.className = "ring-found-devices";
        found.forEach((device) => list.append(deviceButton(device)));
        elements.connectCard.append(list);
    }
}

function deviceButton(device) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ring-device-option";
    const name = document.createElement("strong");
    const meta = document.createElement("span");
    name.textContent = device.advertisedName || "COLMI Ring";
    meta.textContent = `${device.bleId} · RSSI ${device.rssi ?? "—"} dBm`;
    button.append(name, meta);
    button.addEventListener("click", () => connect(device.deviceId));
    return button;
}

function renderDevice(state) {
    const device = state.device;
    const battery = batteryPresentation(device, state.collector?.status);
    const wear = state.wear || { state: "unknown" };
    elements.brandDeviceName.textContent = device?.advertisedName || device?.model || "COLMI Ring";
    elements.sidebarBattery.dataset.level = battery.level;
    elements.sidebarBatteryLabel.textContent = battery.label;
    elements.sidebarBatteryValue.textContent = battery.value;
    elements.sidebarBatteryFill.style.width = `${battery.percentage ?? 0}%`;
    elements.sidebarBatteryTrack.setAttribute("aria-valuetext", battery.available
        ? `${battery.percentage}%${device?.charging ? ", ładowanie" : ""}`
        : "Brak danych");
    if (battery.available) elements.sidebarBatteryTrack.setAttribute("aria-valuenow", String(battery.percentage));
    else elements.sidebarBatteryTrack.removeAttribute("aria-valuenow");
    elements.sidebarWear.dataset.state = wear.state || "unknown";
    elements.sidebarWearLabel.textContent = wear.state === "off_wrist"
        ? "Ring zdjęty · HR odfiltrowane"
        : wear.state === "worn"
            ? "Ring założony · kontakt potwierdzony"
            : "Status noszenia: czekam na pomiar";
    text("#ring-battery", device?.batteryPercentage == null ? "—" : `${device.batteryPercentage}%${device.charging ? " · ładowanie" : ""}`);
    const overview = document.querySelector("#ring-overview-device");
    const details = document.querySelector("#ring-device-details");
    overview.replaceChildren();
    details.replaceChildren();
    const rows = [
        ["Status", state.collector.message],
        ["Kontakt ze skórą", wear.state === "off_wrist" ? "Ring zdjęty" : wear.state === "worn" ? "Potwierdzony" : "Ustalanie"],
        ["Nazwa", device?.advertisedName],
        ["Model", device?.model],
        ["BLE ID", device?.bleId],
        ["Firmware", device?.firmwareVersion],
        ["Hardware", device?.hardwareVersion],
        ["Bateria", device?.batteryPercentage == null ? null : `${device.batteryPercentage}%`],
        ["Ładowanie", device?.charging == null ? null : (device.charging ? "Tak" : "Nie")],
        ["RSSI", device?.rssi == null ? null : `${device.rssi} dBm`],
        ["Ostatnie połączenie", formatDateTime(device?.lastConnected)],
        ["Ostatnia synchronizacja", formatDateTime(device?.lastSuccessfulSync)],
        ["Automatyczne łączenie", state.collector.automatic ? "Tak" : "Nie"],
        ["Synchronizacja historii", state.collector.syncIntervalSeconds ? `co ${Math.round(state.collector.syncIntervalSeconds / 60)} min` : null],
        ["Pomiary live", state.collector.uiLiveActive ? "Aktywne — strona otwarta" : "Uśpione — otwórz stronę Ring"],
        ["Sposób pomiaru", ({
            ring_primary: "Pierścień jest głównym źródłem danych o tętnie i śnie",
            watch_present: "Smartwatch jest głównym źródłem tętna; pierścień uzupełnia pomiary",
        })[state.collector.phoneCollectionProfile] || "Sprawdzam dostępne urządzenia"],
        ["Ostatni HR smartwatcha", formatDateTime(state.collector.phoneWatchLastSeenAt)],
        ["Źródło", device?.sourceMode || state.mode],
    ];
    rows.slice(0, 6).forEach(([label, value]) => addDetail(overview, label, value));
    rows.forEach(([label, value]) => addDetail(details, label, value));
}

function renderLatest(latest = {}) {
    const hr = sanitizeHeartRateRecords(latest.heartRate ? [{
        ...latest.heartRate,
        timestampUtc: latest.heartRate.timestamp_utc || latest.heartRate.timestampUtc,
    }] : [])[0];
    const spo2 = latest.spo2;
    const hrv = latest.hrv;
    const activity = latest.activity;
    const sleep = latest.sleep;
    text("#ring-latest-hr", hr ? `${hr.bpm} bpm` : "—");
    text("#ring-latest-hr-time", hr ? formatDateTime(hr.timestamp_utc || hr.timestampUtc) : "Brak danych");
    text("#ring-heart-latest", hr ? `${hr.bpm} bpm` : "—");
    text("#ring-latest-spo2", spo2 ? `${spo2.spo2 ?? spo2.spo2_max ?? "—"}%` : "—");
    text("#ring-latest-spo2-time", spo2 ? formatDateTime(spo2.timestamp_utc || spo2.timestampUtc) : "Brak danych");
    text("#ring-latest-hrv", hrv ? String(hrv.ring_value ?? hrv.ringValue) : "—");
    text("#ring-latest-steps", activity?.steps == null ? "—" : Number(activity.steps).toLocaleString("pl-PL"));
    text("#ring-latest-sleep", sleep ? formatDuration(sleep.total_minutes ?? sleep.totalMinutes) : "—");
}

function emptyChart(root, message = "Brak zapisanych odczytów.") {
    root.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "ring-chart-empty";
    empty.textContent = message;
    root.append(empty);
}

function renderLineChart(selector, records, valueKey, unit, color = "#72e1c2", colorByValue = null) {
    const root = document.querySelector(selector);
    const points = (records || []).map((record) => ({
        timestamp: new Date(record.timestampUtc).getTime(),
        value: Number(record[valueKey]),
    })).filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.value)).slice(-500);
    if (!points.length) {
        emptyChart(root);
        return;
    }
    root.replaceChildren();
    const width = 1000;
    const height = 230;
    const padding = 28;
    const minTime = points[0].timestamp;
    const maxTime = points.at(-1).timestamp;
    let minValue = Math.min(...points.map((point) => point.value));
    let maxValue = Math.max(...points.map((point) => point.value));
    if (minValue === maxValue) {
        minValue -= 1;
        maxValue += 1;
    }
    const x = (timestamp) => padding + ((timestamp - minTime) / Math.max(1, maxTime - minTime)) * (width - padding * 2);
    const y = (value) => height - padding - ((value - minValue) / (maxValue - minValue)) * (height - padding * 2);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Wykres ${valueKey}`);
    for (let grid = 0; grid <= 4; grid += 1) {
        const line = document.createElementNS(svg.namespaceURI, "line");
        const gridY = padding + grid * ((height - padding * 2) / 4);
        line.setAttribute("x1", padding);
        line.setAttribute("x2", width - padding);
        line.setAttribute("y1", gridY);
        line.setAttribute("y2", gridY);
        line.setAttribute("class", "ring-chart-grid");
        svg.append(line);
        const label = document.createElementNS(svg.namespaceURI, "text");
        label.setAttribute("x", "2");
        label.setAttribute("y", String(gridY + 4));
        label.setAttribute("class", "ring-chart-axis");
        label.textContent = String(Math.round(maxValue - grid * ((maxValue - minValue) / 4)));
        svg.append(label);
    }
    const durationHours = (maxTime - minTime) / (60 * 60 * 1000);
    const tickHours = durationHours > 16 ? 4 : durationHours > 8 ? 2 : 1;
    const tickMs = tickHours * 60 * 60 * 1000;
    for (let tick = Math.ceil(minTime / tickMs) * tickMs; tick <= maxTime; tick += tickMs) {
        const gridX = x(tick);
        const line = document.createElementNS(svg.namespaceURI, "line");
        line.setAttribute("x1", gridX);
        line.setAttribute("x2", gridX);
        line.setAttribute("y1", padding);
        line.setAttribute("y2", height - padding);
        line.setAttribute("class", "ring-chart-grid ring-chart-time-grid");
        svg.append(line);
        const label = document.createElementNS(svg.namespaceURI, "text");
        label.setAttribute("x", gridX);
        label.setAttribute("y", height - 7);
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("class", "ring-chart-axis ring-chart-time-axis");
        label.textContent = chartTimeFormatter.format(new Date(tick));
        svg.append(label);
    }
    if (colorByValue) {
        points.slice(1).forEach((point, index) => {
            const previous = points[index];
            const segment = document.createElementNS(svg.namespaceURI, "line");
            segment.setAttribute("x1", x(previous.timestamp));
            segment.setAttribute("y1", y(previous.value));
            segment.setAttribute("x2", x(point.timestamp));
            segment.setAttribute("y2", y(point.value));
            segment.setAttribute("stroke", colorByValue(point.value));
            segment.setAttribute("stroke-width", "3");
            segment.setAttribute("stroke-linecap", "round");
            svg.append(segment);
        });
    } else {
        const path = document.createElementNS(svg.namespaceURI, "path");
        path.setAttribute("d", points.map((point, index) => `${index ? "L" : "M"}${x(point.timestamp).toFixed(1)},${y(point.value).toFixed(1)}`).join(" "));
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", "3");
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-linejoin", "round");
        svg.append(path);
    }
    const last = points.at(-1);
    const dot = document.createElementNS(svg.namespaceURI, "circle");
    dot.setAttribute("cx", x(last.timestamp));
    dot.setAttribute("cy", y(last.value));
    dot.setAttribute("r", "5");
    dot.setAttribute("fill", colorByValue ? colorByValue(last.value) : color);
    dot.setAttribute("class", "ring-chart-last-dot");
    svg.append(dot);
    root.append(svg);
    const legend = document.createElement("div");
    legend.className = "ring-chart-legend";
    legend.textContent = `${minValue}–${maxValue} ${unit} · ${points.length} próbek · ${formatDateTime(points.at(-1).timestamp)}`;
    root.append(legend);
}

function renderActivityChart(records) {
    const root = document.querySelector("#ring-activity-chart");
    if (!records.length) {
        emptyChart(root);
        return;
    }
    root.replaceChildren();
    const bars = document.createElement("div");
    bars.className = "ring-activity-bars";
    const maximum = Math.max(1, ...records.map((record) => Number(record.steps) || 0));
    records.forEach((record) => {
        const bar = document.createElement("i");
        bar.style.height = `${Math.max(2, ((Number(record.steps) || 0) / maximum) * 100)}%`;
        bar.title = `${new Date(record.timestampUtc).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}: ${record.steps || 0} kroków`;
        bars.append(bar);
    });
    root.append(bars);
}

function renderSleep(nights = []) {
    const consolidatedNights = consolidateSleepNights(nights);
    const latest = consolidatedNights[0];
    const timeline = document.querySelector("#ring-sleep-timeline");
    const history = document.querySelector("#ring-sleep-history");
    timeline.replaceChildren();
    history.replaceChildren();
    if (!latest) {
        emptyChart(timeline, "Ring nie zwrócił jeszcze zapisanej nocy.");
        text("#ring-sleep-duration", "—");
        text("#ring-sleep-date", "Brak nocy");
        text("#ring-sleep-window", "—");
        text("#ring-sleep-stages-total", "—");
        return;
    }
    text("#ring-sleep-duration", formatDuration(latest.totalMinutes));
    text("#ring-sleep-date", latest.sleepDate || "—");
    const timeFormat = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Warsaw" });
    text("#ring-sleep-window", `${timeFormat.format(new Date(latest.sleepStartUtc))}–${timeFormat.format(new Date(latest.sleepEndUtc))}`);
    text("#ring-sleep-stages-total", String(latest.stages?.length || 0));
    (latest.stages || []).forEach((segment) => {
        const block = document.createElement("i");
        block.dataset.stage = segment.stage;
        block.style.flexGrow = String(Math.max(1, segment.durationMinutes || 1));
        block.title = `${segment.stage}: ${segment.durationMinutes} min`;
        timeline.append(block);
    });
    consolidatedNights.slice(0, 14).forEach((night) => {
        const row = document.createElement("div");
        const label = document.createElement("strong");
        const total = document.createElement("span");
        label.textContent = night.sleepDate || "Noc";
        total.textContent = `${formatDuration(night.totalMinutes)} · light ${night.lightMinutes || 0} · deep ${night.deepMinutes || 0} · REM ${night.remMinutes || 0} · awake ${night.awakeMinutes || 0} min`;
        row.append(label, total);
        history.append(row);
    });
}

function renderHistory(history) {
    cachedHistory = history;
    const heartRate = sanitizeHeartRateRecords(history.heartRate || []);
    const watchHeartRate = history.watchHeartRateReference || [];
    const spo2 = history.spo2 || [];
    const activity = normalizeActivityRecords(history.activity || []);
    const hrv = history.hrv || [];
    const heartDay = heartRate.filter((item) => localDay(item.timestampUtc) === selectedHeartDay);
    const watchHeartDay = watchHeartRate.filter((item) => localDay(item.timestampUtc) === selectedHeartDay);
    const latestHr = heartDay.at(-1);
    const hrValues = heartDay.map((item) => Number(item.bpm)).filter(Number.isFinite);
    text("#ring-heart-latest", latestHr ? `${latestHr.bpm} bpm` : "—");
    text("#ring-heart-latest-time", latestHr ? formatDateTime(latestHr.timestampUtc) : "Brak próbek");
    text("#ring-heart-range", hrValues.length ? `${Math.min(...hrValues)}–${Math.max(...hrValues)} bpm` : "—");
    text("#ring-heart-average", hrValues.length ? `${Math.round(hrValues.reduce((sum, value) => sum + value, 0) / hrValues.length)} bpm` : "—");
    text("#ring-heart-samples", hrValues.length ? String(hrValues.length) : "—");
    text("#ring-heart-mode", latestHr?.sourceMode || "—");
    text("#ring-watch-heart-samples", watchHeartDay.length ? String(watchHeartDay.length) : "—");
    text("#ring-watch-heart-latest", watchHeartDay.length
        ? `ostatnia ${formatDateTime(watchHeartDay.at(-1).timestampUtc)} · osobny strumień`
        : "osobny strumień · bez mieszania");
    text("#ring-heart-day-label", new Intl.DateTimeFormat("pl-PL", { dateStyle: "full", timeZone: "Europe/Warsaw" }).format(new Date(`${selectedHeartDay}T12:00:00`)));
    const age = latestHr ? Date.now() - new Date(latestHr.timestampUtc).getTime() : Infinity;
    const live = document.querySelector("#ring-heart-live-state");
    if (live) {
        const viewingToday = selectedHeartDay === localDay(Date.now());
        const watchPresent = currentState?.collector?.phoneCollectionProfile === "watch_present";
        live.dataset.live = viewingToday && age < 120_000 ? "true" : "false";
        live.textContent = !viewingToday
            ? "Historia wybranego dnia"
            : age < 120_000
                ? "LIVE · aktualizacja co 2 s"
                : watchPresent
                    ? "Oszczędzanie · smartwatch aktywny"
                    : Number.isFinite(age)
                        ? `Ostatnia próbka ${Math.max(2, Math.floor(age / 60_000))} min temu · ponawiam pomiar`
                        : "Oczekiwanie na pierwszą próbkę";
    }
    renderLineChart("#ring-heart-chart", heartDay, "bpm", "bpm", "#fb7185", (value) => heartRateZone(value).color);

    const validSpo2 = spo2.filter((item) => Number.isFinite(Number(item.spo2 ?? item.spo2Max)));
    const latestSpo2 = validSpo2.at(-1);
    const minimums = validSpo2.map((item) => Number(item.spo2Min ?? item.spo2)).filter(Number.isFinite);
    const maximums = validSpo2.map((item) => Number(item.spo2Max ?? item.spo2)).filter(Number.isFinite);
    text("#ring-spo2-latest", latestSpo2 ? `${latestSpo2.spo2 ?? latestSpo2.spo2Max}%` : "—");
    text("#ring-spo2-latest-time", latestSpo2 ? formatDateTime(latestSpo2.timestampUtc) : "Brak danych");
    text("#ring-spo2-min", minimums.length ? `${Math.min(...minimums)}%` : "—");
    text("#ring-spo2-max", maximums.length ? `${Math.max(...maximums)}%` : "—");
    renderLineChart("#ring-spo2-chart", validSpo2.map((item) => ({ ...item, value: item.spo2 ?? item.spo2Max })), "value", "%", "#60a5fa");

    const today = localDay(Date.now());
    const todayActivity = activity.filter((item) => localDay(item.timestampUtc) === today);
    const sum = (key) => todayActivity.reduce((total, item) => total + (Number(item[key]) || 0), 0);
    const steps = sum("steps");
    text("#ring-activity-steps", todayActivity.length ? steps.toLocaleString("pl-PL") : "—");
    text("#ring-activity-distance", todayActivity.length ? `${Math.round(sum("distanceM"))} m` : "—");
    text("#ring-activity-calories", todayActivity.length ? `${sum("caloriesKcal").toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal` : "—");
    text("#ring-latest-steps", todayActivity.length ? steps.toLocaleString("pl-PL") : "—");
    renderActivityChart(todayActivity);

    renderLineChart("#ring-hrv-chart", hrv, "ringValue", "proxy", "#fbbf24");
    renderSleep(history.sleep || []);
}

function friendlyCollectorMessage(state) {
    if (state.collector?.status !== "phone-bridge") return state.collector?.message;
    if (state.collector.phoneCollectionProfile === "ring_primary") {
        return "Dane pochodzą z pierścienia · tętno i sen";
    }
    if (state.collector.phoneCollectionProfile === "watch_present") {
        return "Tętno pochodzi ze smartwatcha · pierścień uzupełnia dane";
    }
    return "Telefon odbiera dane z pierścienia";
}

function renderState(state) {
    state = {
        ...state,
        collector: {
            ...state.collector,
            message: friendlyCollectorMessage(state),
        },
    };
    currentState = state;
    elements.mode.dataset.mode = state.mode;
    elements.mode.textContent = state.mode === "mock" ? "TRYB MOCK · osobna baza" : "TRYB REAL · lokalny BLE";
    setStatus(
        state.wear?.state === "off_wrist" ? "off-wrist" : state.collector.status,
        state.wear?.state === "off_wrist" ? "Ring zdjęty · pomiary HR wstrzymane" : state.collector.message,
    );
    renderConnectCard(state);
    renderDevice(state);
    renderLatest(state.latest);
    renderCapabilities(state.capabilities);
    renderServices(state.services);
    renderActions();
}

function renderCapabilities(capabilities = {}) {
    const root = document.querySelector("#ring-capabilities");
    root.replaceChildren();
    Object.entries(capabilities).forEach(([name, status]) => {
        const row = document.createElement("div");
        const label = document.createElement("span");
        const chip = document.createElement("b");
        label.textContent = name;
        chip.textContent = capabilityLabel(status);
        chip.dataset.status = status;
        row.append(label, chip);
        root.append(row);
    });
}

function renderServices(services = []) {
    const root = document.querySelector("#ring-services");
    root.replaceChildren();
    if (!services.length) {
        root.textContent = "Brak aktywnego połączenia.";
        return;
    }
    services.forEach((service) => {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = service.description || service.uuid;
        const code = document.createElement("code");
        code.textContent = service.uuid;
        details.append(summary, code);
        (service.characteristics || []).forEach((characteristic) => {
            const line = document.createElement("p");
            line.textContent = `${characteristic.uuid} · ${(characteristic.properties || []).join(", ")}`;
            details.append(line);
        });
        root.append(details);
    });
}

async function loadState() {
    try {
        renderState(await ringApi.state());
        showNotice("");
    } catch (error) {
        setStatus("offline", "Collector/API niedostępny");
        showNotice(`${error.message}. Uruchom lokalny backend poleceniem npm run dev:all.`);
    }
}

async function loadHistory() {
    try {
        renderHistory(await ringApi.history(4000));
    } catch (error) {
        showNotice(error.message);
    }
}

async function automaticRefresh() {
    if (refreshRunning || document.hidden) return;
    refreshRunning = true;
    try {
        const [presence, history] = await Promise.all([ringApi.presence(), ringApi.history(4000)]);
        renderState({
            ...presence.state,
            wear: presence.state?.wear || currentState?.wear || { state: "unknown" },
        });
        renderHistory(history);
    } catch (error) {
        setStatus("offline", "Collector/API niedostępny");
        showNotice(error.message);
    } finally {
        refreshRunning = false;
    }
}

async function scan() {
    if (busy) return;
    setBusy(true, "Skanowanie BLE…");
    showNotice("");
    try {
        const result = await ringApi.scan(8);
        await Promise.all([loadState(), loadHistory()]);
        if (!result.devices.length) showNotice("Nie znaleziono zgodnego ringa. Sprawdź Bluetooth i odległość, po czym spróbuj ponownie.", "warning");
    } catch (error) {
        showNotice(error.message);
        await loadState();
    } finally {
        setBusy(false);
    }
}

async function connect(deviceId) {
    if (busy) return;
    setBusy(true, "Łączenie z ringiem…");
    showNotice("");
    try {
        const result = await ringApi.connect(deviceId);
        renderState(result.state);
        showNotice("Połączono. Odczytano dane urządzenia i baterii oraz ustawiono zegar ringa.", "success");
    } catch (error) {
        showNotice(error.message);
        await loadState();
    } finally {
        setBusy(false);
    }
}

async function sync() {
    if (busy) return;
    setBusy(true, "Synchronizacja urządzenia…");
    showNotice("");
    try {
        await ringApi.sync();
        await Promise.all([loadState(), loadHistory()]);
        showNotice("Synchronizacja zakończona. Nowe rekordy historii zostały zapisane bez duplikatów.", "success");
    } catch (error) {
        showNotice(error.message);
        await loadState();
    } finally {
        setBusy(false);
    }
}

async function disconnect() {
    if (busy) return;
    setBusy(true, "Rozłączanie…");
    try {
        const result = await ringApi.disconnect();
        renderState(result.state);
    } catch (error) {
        showNotice(error.message);
    } finally {
        setBusy(false);
    }
}

async function loadDiagnostics() {
    try {
        const result = await ringApi.diagnostics(150);
        renderCapabilities(result.capabilities);
        renderServices(result.services);
        const eventRoot = document.querySelector("#ring-event-log");
        eventRoot.replaceChildren();
        if (!result.events?.length) eventRoot.textContent = "Brak zdarzeń.";
        (result.events || []).forEach((event) => {
            const row = document.createElement("div");
            const stamp = document.createElement("time");
            const message = document.createElement("span");
            stamp.textContent = formatDateTime(event.timestamp_utc);
            message.textContent = `${event.event_type}: ${event.message}`;
            row.dataset.level = event.level;
            row.append(stamp, message);
            eventRoot.append(row);
        });
        const packetRoot = document.querySelector("#ring-packet-log");
        packetRoot.replaceChildren();
        text("#ring-packet-count", String(result.packets?.length || 0));
        (result.packets || []).forEach((packet) => {
            const row = document.createElement("tr");
            [
                formatDateTime(packet.timestamp_utc), packet.direction, packet.opcode ?? "—",
                packet.parsed_type || "—", packet.parser_status, packet.payload_hex,
            ].forEach((value) => {
                const cell = document.createElement("td");
                cell.textContent = value;
                row.append(cell);
            });
            packetRoot.append(row);
        });
    } catch (error) {
        showNotice(error.message);
    }
}

document.querySelectorAll("[data-ring-tab]").forEach((button) => {
    button.addEventListener("click", () => {
        const tab = button.dataset.ringTab;
        document.querySelectorAll("[data-ring-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
        document.querySelectorAll("[data-ring-view]").forEach((view) => {
            const active = view.dataset.ringView === tab;
            view.classList.toggle("is-active", active);
            view.hidden = !active;
        });
        elements.title.textContent = titleByTab[tab] || "COLMI Ring";
        history.replaceState(null, "", `#${tab}`);
        if (tab === "diagnostics") loadDiagnostics();
    });
});

elements.sync.addEventListener("click", sync);
elements.disconnect.addEventListener("click", disconnect);
elements.deviceRefresh.addEventListener("click", sync);
elements.diagnosticsRefresh.addEventListener("click", loadDiagnostics);

const initialTab = location.hash.slice(1);
if (titleByTab[initialTab]) document.querySelector(`[data-ring-tab="${initialTab}"]`)?.click();
loadState();
loadHistory();
ringApi.presence().catch(() => {});
const heartDate = document.querySelector("#ring-heart-date");
if (heartDate) {
    heartDate.value = selectedHeartDay;
    heartDate.max = localDay(Date.now());
    heartDate.addEventListener("change", () => {
        if (!heartDate.value) return;
        selectedHeartDay = heartDate.value;
        renderHistory(cachedHistory);
    });
}

function shiftHeartDay(days) {
    const date = new Date(`${selectedHeartDay}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    const next = date.toISOString().slice(0, 10);
    if (next > localDay(Date.now())) return;
    selectedHeartDay = next;
    if (heartDate) heartDate.value = next;
    renderHistory(cachedHistory);
}

document.querySelector("#ring-heart-previous")?.addEventListener("click", () => shiftHeartDay(-1));
document.querySelector("#ring-heart-next")?.addEventListener("click", () => shiftHeartDay(1));
document.querySelector("#ring-heart-today")?.addEventListener("click", () => {
    selectedHeartDay = localDay(Date.now());
    if (heartDate) heartDate.value = selectedHeartDay;
    renderHistory(cachedHistory);
});

setInterval(automaticRefresh, 2_000);
document.addEventListener("visibilitychange", () => {
    if (!document.hidden) automaticRefresh();
});
