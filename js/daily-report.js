const REPORT_ALL_FALLBACK_DAYS = 1095;

function todayIso(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function readNumber(value) {
  const parsed = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function reportDays(days, fallback = 30) {
  if (days === "all") return REPORT_ALL_FALLBACK_DAYS;
  return Math.max(1, Math.round(readNumber(days) || fallback));
}

function reportEnd(day) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(day || "")) ? String(day) : todayIso();
}

function formatInt(value) {
  return Math.round(readNumber(value) || 0).toLocaleString("pl-PL");
}

function formatKg(value) {
  const number = readNumber(value);
  return Number.isFinite(number) ? `${number.toFixed(2).replace(".", ",")} kg` : "brak danych";
}

function normalizeWeightRows(payload) {
  return (Array.isArray(payload?.daily) ? payload.daily : [])
    .map((row) => ({
      day: String(row.day || ""),
      avgWeightKg: readNumber(row.avg_weight_kg ?? row.avgWeightKg),
      count: Math.max(0, Math.round(readNumber(row.count) || 0)),
      filled: row.filled === true,
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day) && Number.isFinite(row.avgWeightKg));
}

function normalizeStepsRows(payload) {
  return (Array.isArray(payload?.daily) ? payload.daily : [])
    .map((row) => ({
      day: String(row.day || ""),
      steps: Math.max(0, Math.round(readNumber(row.steps) || 0)),
      filled: row.filled === true,
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day));
}

function normalizeDietRows(payload) {
  return (Array.isArray(payload?.daily) ? payload.daily : [])
    .map((row) => {
      const totalKcal = Math.max(0, Math.round(readNumber(row.total_kcal ?? row.totalKcal) || 0));
      const mealCount = Math.max(0, Math.round(readNumber(row.meal_count ?? row.mealCount) || 0));
      const goalKcal = Math.max(0, Math.round(readNumber(row.goal_kcal ?? row.goalKcal) || 0));
      const estimatedKcal = Math.max(0, Math.round(readNumber(row.estimated_kcal ?? row.estimatedCalories) || 0));
      const caloriesSource = row.calories_source || row.caloriesSource || (mealCount > 0 && totalKcal > 0 ? "manual" : estimatedKcal > 0 ? "estimated" : "missing");
      return {
        day: String(row.day || ""),
        totalKcal,
        mealCount,
        goalKcal,
        estimatedKcal,
        caloriesSource,
        filled: row.filled === true || caloriesSource !== "manual",
      };
    })
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.day));
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function paramsFor(days, end, extra = {}) {
  return new URLSearchParams({
    days: String(reportDays(days)),
    end: reportEnd(end),
    ...extra,
  }).toString();
}

async function fetchWeightDailyRows(days, end) {
  return normalizeWeightRows(await fetchJson(`/api/weight/history?${paramsFor(days, end, { fill: "1" })}`));
}

async function fetchStepsDailyRows(days, end) {
  return normalizeStepsRows(await fetchJson(`/api/steps/history?${paramsFor(days, end)}`));
}

async function fetchDietDailyRows(days, end) {
  return normalizeDietRows(await fetchJson(`/api/diet/history?${paramsFor(days, end)}`));
}

function downloadTxt(filename, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function reportHeader(title, days, end) {
  return [
    title,
    `Zakres: ${reportDays(days)} dni do ${reportEnd(end)}`,
    `Wygenerowano: ${new Date().toLocaleString("pl-PL")}`,
    "",
  ];
}

function weightLine(row) {
  if (!row) return "waga: brak danych";
  const source = row.filled ? "interpolacja / brak pomiaru" : `${formatInt(row.count)} pom.`;
  return `waga: ${formatKg(row.avgWeightKg)} (${source})`;
}

function stepsLine(row) {
  if (!row || row.filled) return "kroki: brak danych";
  return `kroki: ${formatInt(row.steps)}`;
}

function dietLine(row) {
  if (!row || (row.filled && row.caloriesSource !== "estimated")) return "kalorie: brak pomiaru";
  if (row.caloriesSource === "estimated") return `kalorie: ~${formatInt(row.totalKcal)} kcal (estymacja)`;
  const goal = row.goalKcal > 0 ? `; cel ${formatInt(row.goalKcal)} kcal` : "";
  return `kalorie: ${formatInt(row.totalKcal)} kcal; posilki ${formatInt(row.mealCount)}${goal}`;
}

function filename(prefix, end) {
  return `${prefix}-${reportEnd(end)}.txt`;
}

export async function generateWeightDailyReport({ days = 30, end = todayIso() } = {}) {
  const rows = await fetchWeightDailyRows(days, end);
  const lines = reportHeader("Raport: srednia dzienna waga", days, end);
  rows.forEach((row) => lines.push(`${row.day} - ${weightLine(row)}`));
  downloadTxt(filename("raport-waga-dzienna", end), `${lines.join("\n")}\n`);
}

export async function generateStepsDailyReport({ days = 30, end = todayIso() } = {}) {
  const rows = await fetchStepsDailyRows(days, end);
  const lines = reportHeader("Raport: kroki dzienne", days, end);
  rows.forEach((row) => lines.push(`${row.day} - ${stepsLine(row)}`));
  downloadTxt(filename("raport-kroki-dzienne", end), `${lines.join("\n")}\n`);
}

export async function generateDietDailyReport({ days = 30, end = todayIso() } = {}) {
  const rows = await fetchDietDailyRows(days, end);
  const lines = reportHeader("Raport: kalorie dzienne", days, end);
  rows.forEach((row) => lines.push(`${row.day} - ${dietLine(row)}`));
  downloadTxt(filename("raport-kalorie-dzienne", end), `${lines.join("\n")}\n`);
}

export async function generateCombinedDailyReport({ days = 30, end = todayIso() } = {}) {
  const [weightRows, stepsRows, dietRows] = await Promise.all([
    fetchWeightDailyRows(days, end),
    fetchStepsDailyRows(days, end),
    fetchDietDailyRows(days, end),
  ]);
  const weightByDay = new Map(weightRows.map((row) => [row.day, row]));
  const stepsByDay = new Map(stepsRows.map((row) => [row.day, row]));
  const dietByDay = new Map(dietRows.map((row) => [row.day, row]));
  const daysInOrder = [...new Set([
    ...weightRows.map((row) => row.day),
    ...stepsRows.map((row) => row.day),
    ...dietRows.map((row) => row.day),
  ])].sort((a, b) => a.localeCompare(b));
  const lines = reportHeader("Raport zbiorczy: waga, kroki, kalorie", days, end);
  daysInOrder.forEach((day) => {
    lines.push(day);
    lines.push(weightLine(weightByDay.get(day)));
    lines.push(stepsLine(stepsByDay.get(day)));
    lines.push(dietLine(dietByDay.get(day)));
    lines.push("");
  });
  downloadTxt(filename("raport-zbiorczy-dzienny", end), `${lines.join("\n").trimEnd()}\n`);
}
