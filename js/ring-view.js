export function formatDateTime(value) {
    if (!value) return "Brak";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Brak";
    return new Intl.DateTimeFormat("pl-PL", {
        dateStyle: "medium",
        timeStyle: "medium",
        timeZone: "Europe/Warsaw",
    }).format(date);
}

export function formatDuration(minutes) {
    if (minutes == null || minutes === "") return "—";
    const safe = Number(minutes);
    if (!Number.isFinite(safe) || safe < 0) return "—";
    return `${Math.floor(safe / 60)} h ${Math.round(safe % 60)} min`;
}

export function batteryPresentation(device, collectorStatus = "offline") {
    const rawPercentage = Number(device?.batteryPercentage);
    if (!Number.isFinite(rawPercentage)) {
        return {
            available: false,
            percentage: null,
            value: "—",
            label: "Bateria",
            level: "unknown",
        };
    }

    const percentage = Math.max(0, Math.min(100, Math.round(rawPercentage)));
    const charging = device?.charging === true;
    const active = ["connected", "syncing", "measuring", "phone-bridge"].includes(collectorStatus);
    const level = charging
        ? "charging"
        : percentage <= 15
            ? "critical"
            : percentage <= 30
                ? "low"
                : percentage <= 60
                    ? "medium"
                    : "good";

    return {
        available: true,
        percentage,
        value: `${percentage}%${charging ? " ⚡" : ""}`,
        label: charging ? "Ładowanie" : (active ? "Bateria" : "Ostatni odczyt"),
        level,
    };
}

export function consolidateSleepNights(nights = []) {
    const bestByNight = new Map();
    (Array.isArray(nights) ? nights : []).forEach((night, index) => {
        const key = String(night?.sleepDate || night?.sleepStartUtc || `night-${index}`);
        const current = bestByNight.get(key);
        const totalMinutes = Math.max(0, Number(night?.totalMinutes) || 0);
        const endTime = Date.parse(night?.sleepEndUtc) || 0;
        const createdTime = Date.parse(night?.createdAt) || 0;
        const score = createdTime
            ? [1, createdTime, endTime, totalMinutes]
            : [0, totalMinutes, endTime, 0];
        const isNewer = !current || score.some((value, scoreIndex) => (
            score.slice(0, scoreIndex).every(
                (prefix, prefixIndex) => prefix === current.score[prefixIndex],
            ) && value > current.score[scoreIndex]
        ));
        if (isNewer) bestByNight.set(key, { night, score });
    });
    return Array.from(bestByNight.values())
        .map(({ night }) => night)
        .sort((left, right) => {
            const dateOrder = String(right?.sleepDate || "").localeCompare(String(left?.sleepDate || ""));
            if (dateOrder) return dateOrder;
            return (Date.parse(right?.sleepEndUtc) || 0) - (Date.parse(left?.sleepEndUtc) || 0);
        });
}

export function connectionPresentation(state) {
    const status = state?.collector?.status || "offline";
    const device = state?.device || null;
    const active = ["connected", "syncing", "measuring", "phone-bridge"].includes(status);
    if (!device) {
        return {
            kind: "empty",
            title: "Brak połączonego pierścienia COLMI",
            copy: state?.collector?.bleDependencyAvailable === false
                ? "Collector działa, ale brakuje biblioteki BLE. Zainstaluj requirements-ring.txt i uruchom API ponownie."
                : "Włącz Bluetooth w Windows, połóż naładowany R10 obok komputera i rozpocznij skanowanie.",
            action: "Skanuj ring",
            status,
        };
    }
    return {
        kind: active ? "connected" : "known",
        title: device.advertisedName || device.model || "COLMI Ring",
        copy: active
            ? status === "phone-bridge"
                ? `Telefon jest mostkiem BLE · ${state?.collector?.message || "dane dotrą automatycznie przez Wi-Fi"}`
                : `Połączono · ${device.batteryPercentage ?? "—"}% baterii`
            : "Ring jest zapamiętany lokalnie. Połącz go ponownie, aby pobrać dane.",
        action: active ? null : "Połącz",
        status,
    };
}

export function capabilityLabel(value) {
    return ({
        supported: "obsługiwane",
        planned: "zaplanowane",
        experimental: "eksperymentalne",
        unknown: "nieznane",
        unsupported: "nieobsługiwane",
    })[value] || String(value || "nieznane");
}

export function sanitizeHeartRateRecords(records = []) {
    const seen = new Set();
    return records.map((record) => ({ ...record, bpm: Number(record.bpm) }))
        .filter((record) => {
            const timestamp = new Date(record.timestampUtc).getTime();
            if (!Number.isFinite(timestamp) || !Number.isFinite(record.bpm) || record.bpm < 30 || record.bpm > 220) return false;
            const key = `${timestamp}:${record.bpm}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        })
        .sort((left, right) => new Date(left.timestampUtc) - new Date(right.timestampUtc));
}

export function normalizeRingCalories(value) {
    const calories = Number(value);
    if (!Number.isFinite(calories) || calories < 0) return 0;
    if (calories >= 1000) return calories / 1000;
    if (calories >= 100) return calories / 100;
    return calories;
}

export function normalizeActivityRecords(records = []) {
    const slots = new Map();
    records.forEach((record) => {
        const timestamp = new Date(record.timestampUtc);
        if (Number.isNaN(timestamp.getTime())) return;
        const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw" }).format(timestamp);
        const key = `${day}:${record.sourceSlot ?? record.timestampUtc}`;
        const normalized = { ...record, caloriesKcal: normalizeRingCalories(record.caloriesKcal) };
        const current = slots.get(key);
        if (!current || Number(normalized.steps || 0) >= Number(current.steps || 0)) slots.set(key, normalized);
    });
    return [...slots.values()].sort((left, right) => new Date(left.timestampUtc) - new Date(right.timestampUtc));
}

export function heartRateZone(value) {
    const bpm = Number(value);
    if (bpm < 60) return { key: "deep", color: "#3b82f6" };
    if (bpm <= 85) return { key: "base", color: "#22c55e" };
    if (bpm <= 100) return { key: "light", color: "#eab308" };
    if (bpm <= 120) return { key: "high", color: "#f97316" };
    return { key: "alert", color: "#ef4444" };
}
