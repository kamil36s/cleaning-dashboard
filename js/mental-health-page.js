import {
  createAssessment,
  createCheckin,
  createCustomQuestionnaire,
  createMentalHealthEvent,
  deleteAllMentalHealthData,
  deleteMentalHealthEntry,
  fetchMentalHealthExport,
  fetchMentalHealthOverview,
  importMentalHealthData,
  saveAssessmentDraft,
  setAssessmentBaseline,
  updateAssessmentSchedule,
  updateMentalHealthSettings,
} from "./mental-health-api.js";

export const CHECKIN_LABELS = {
  mood: "Nastrój", anxiety: "Lęk / napięcie", stress: "Stres", energy: "Energia",
  motivation: "Motywacja", irritability: "Drażliwość", socialBattery: "Bateria społeczna",
  sensoryOverload: "Przeciążenie sensoryczne", focus: "Zdolność skupienia", sleepQuality: "Jakość snu",
};

const STATUS_LABELS = {
  not_started: "baseline do zrobienia", not_due: "nie teraz", due_soon: "w tym tygodniu",
  due: "dzisiaj", overdue: "po terminie", completed_today: "zrobione dziś", paused: "wstrzymane",
};
const FIELD_FLAGS = new Set(["important_event", "dose_changed", "illness", "alcohol", "unusual_sleep", "work_event"]);
const state = { data: null, trendInstrument: null, draftTimer: null, draftPromise: null };
const MODE_LABELS = { native: "Do wypełnienia", "external-score": "Wynik zewnętrzny" };

export const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

function formatDate(value, withTime = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pl-PL", withTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" }).format(date);
}

function scoreLabel(instrument, assessment) {
  if (!assessment) return "—";
  if (instrument.id === "who5") return `${assessment.rawScore}/25 · ${assessment.normalizedScore ?? assessment.subscaleScores?.percentage ?? Number(assessment.rawScore) * 4}/100`;
  if (assessment.rawScore == null) {
    const parts = Object.entries(assessment.subscaleScores || {}).map(([key, value]) => `${key} ${compactNumber(value)}`);
    return parts.join(" · ") || "profil zapisany";
  }
  return `${compactNumber(assessment.rawScore)}${instrument.scoreMax != null ? `/${instrument.scoreMax}` : ""}`;
}

function compactNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function directionCopy(instrument, delta) {
  if (delta == null || !Number.isFinite(Number(delta))) return "pierwszy pomiar";
  if (Number(delta) === 0) return "bez zmiany";
  const arrow = Number(delta) > 0 ? "↑" : "↓";
  return `${arrow} ${Math.abs(Number(delta)).toFixed(Number.isInteger(Number(delta)) ? 0 : 1)} od poprzedniego`;
}

function instrumentMap() {
  return Object.fromEntries((state.data?.registry || []).map((item) => [item.id, item]));
}

function scheduleMap() {
  return Object.fromEntries((state.data?.schedules || []).map((item) => [item.instrumentId, item]));
}

function latestMap() {
  return Object.fromEntries((state.data?.latest || []).map((item) => [item.instrument.id, item]));
}

function sparkline(history, instrument) {
  const rows = (history || []).filter((item) => item.rawScore != null);
  if (rows.length < 2) return '<span class="mh-spark-empty">trend po 2. pomiarze</span>';
  const width = 126; const height = 34; const pad = 3;
  const low = Number(instrument.scoreMin ?? Math.min(...rows.map((row) => row.rawScore)));
  const high = Number(instrument.scoreMax ?? Math.max(...rows.map((row) => row.rawScore)));
  const span = high - low || 1;
  const points = rows.map((row, index) => {
    const x = pad + index * ((width - pad * 2) / Math.max(1, rows.length - 1));
    const y = height - pad - ((Number(row.rawScore) - low) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="mh-spark" viewBox="0 0 ${width} ${height}" aria-label="Trend ${escapeHtml(instrument.shortName)}"><polyline points="${points}" /></svg>`;
}

export function buildTrendSvg(history, instrument, mode = "raw") {
  const rows = (history || []).filter((row) => row.rawScore != null);
  if (!rows.length) return '<div class="mh-empty">Brak wyników do narysowania.</div>';
  const width = 920; const height = 300; const left = 46; const right = 18; const top = 24; const bottom = 42;
  const values = rows.map((row) => mode === "normalized"
    ? ((Number(row.rawScore) - Number(instrument.scoreMin || 0)) / ((Number(instrument.scoreMax) - Number(instrument.scoreMin || 0)) || 1)) * 100
    : Number(row.rawScore));
  const yMin = mode === "normalized" ? 0 : Number(instrument.scoreMin ?? Math.min(...values));
  const yMax = mode === "normalized" ? 100 : Number(instrument.scoreMax ?? Math.max(...values));
  const ySpan = yMax - yMin || 1;
  const coords = values.map((value, index) => ({
    x: left + index * ((width - left - right) / Math.max(1, values.length - 1)),
    y: top + (1 - (value - yMin) / ySpan) * (height - top - bottom), value, row: rows[index],
  }));
  const grid = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4; const y = top + ratio * (height - top - bottom);
    const label = yMax - ratio * ySpan;
    return `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"/><text x="${left - 8}" y="${y + 4}">${compactNumber(label)}</text>`;
  }).join("");
  const labels = coords.map((point, index) => index % Math.max(1, Math.ceil(coords.length / 6)) === 0
    ? `<text x="${point.x}" y="${height - 16}" text-anchor="middle">${escapeHtml(new Date(point.row.completedAt).toLocaleDateString("pl-PL", { day: "2-digit", month: "short" }))}</text>` : "").join("");
  const points = coords.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const circles = coords.map((point) => `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${escapeHtml(formatDate(point.row.completedAt))}: ${compactNumber(point.value)}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Trend ${escapeHtml(instrument.shortName)}"><g class="mh-chart-grid">${grid}${labels}</g><polyline class="mh-chart-line" points="${points}"/>${circles}</svg>`;
}

function renderSummary() {
  const data = state.data;
  const next = data.nextScheduled;
  document.getElementById("mh-due-badge").textContent = String(data.dueCount || 0);
  document.getElementById("mh-summary-strip").innerHTML = `
    <article><span>Do zrobienia</span><strong>${data.dueCount || 0}</strong><small>aktywnych badań</small></article>
    <article><span>Ostatni check-in</span><strong>${data.lastCheckin ? formatDate(data.lastCheckin.recordedAt) : "brak"}</strong><small>${data.lastCheckin ? Object.keys(data.lastCheckin.values || {}).length : 0} wymiarów</small></article>
    <article><span>Następne</span><strong>${next ? instrumentMap()[next.instrumentId]?.shortName || next.instrumentId : "—"}</strong><small>${next ? formatDate(next.nextDueAt) : "brak terminu"}</small></article>`;

  const preferred = ["phq9", "gad7", "who5", "k6", "cbi", "swls", "rses"];
  const latest = latestMap();
  document.getElementById("mh-score-grid").innerHTML = preferred.filter((id) => latest[id]).map((id) => scoreCard(latest[id])).join("")
    || '<div class="mh-empty mh-card">Pierwsze wyniki pojawią się tu jako oddzielne wymiary.</div>';
}

function scoreCard(item) {
  const { instrument, current, previous, baseline, history } = item;
  const interpretation = current.interpretation?.label ? `<span class="mh-band">${escapeHtml(current.interpretation.label)}</span>` : "";
  const subscales = Object.entries(current.subscaleScores || {}).filter(([key]) => key !== "percentage")
    .map(([key, value]) => `<span>${escapeHtml(instrument.subscales.find((sub) => sub.id === key)?.name || key)} <strong>${compactNumber(value)}</strong></span>`).join("");
  return `<article class="mh-score-card" data-instrument="${escapeHtml(instrument.id)}">
    <div class="mh-score-card-head"><div><span>${escapeHtml(instrument.category)}</span><h3>${escapeHtml(instrument.shortName)}</h3></div><button type="button" data-action="info" data-id="${escapeHtml(instrument.id)}">i</button></div>
    <strong class="mh-score-value">${escapeHtml(scoreLabel(instrument, current))}</strong>${interpretation}
    <div class="mh-subscale-row">${subscales}</div>
    <div class="mh-score-trend"><span>${escapeHtml(directionCopy(instrument, item.changeFromPrevious))}</span>${sparkline(history, instrument)}</div>
    <small>${formatDate(current.completedAt)} · baseline ${escapeHtml(scoreLabel(instrument, baseline))}</small>
    ${previous ? "" : '<small class="mh-muted">Potrzebny drugi pomiar do porównania.</small>'}
  </article>`;
}

function renderDue() {
  const instruments = instrumentMap();
  const schedules = state.data.schedules.filter((row) => row.enabled && !row.paused);
  const rank = { overdue: 0, due: 1, not_started: 2, due_soon: 3, not_due: 4, completed_today: 5 };
  schedules.sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || String(a.nextDueAt).localeCompare(String(b.nextDueAt)));
  const actionable = schedules.filter((row) => ["overdue", "due", "not_started"].includes(row.status));
  const minutes = actionable.reduce((total, row) => total + Number(instruments[row.instrumentId]?.estimatedMinutes || 0), 0);
  const burden = minutes <= 5 ? "lekka" : minutes <= 12 ? "średnia" : "duża";
  document.getElementById("mh-burden").textContent = `${actionable.length} pozycji · ok. ${minutes} min · ${burden}`;
  document.getElementById("mh-due-list").innerHTML = schedules.map((schedule) => {
    const instrument = instruments[schedule.instrumentId];
    return `<article class="mh-due-card" data-status="${schedule.status}">
      <div class="mh-due-main"><span class="mh-status">${escapeHtml(STATUS_LABELS[schedule.status] || schedule.status)}</span><h3>${escapeHtml(instrument.name)}</h3><p>${escapeHtml(instrument.description)}</p><div class="mh-meta-row"><span>${escapeHtml(instrument.constructType.toUpperCase())}</span><span>${instrument.itemCount ?? "—"} pozycji</span><span>~${instrument.estimatedMinutes} min</span><span>${escapeHtml(instrument.recallPeriod)}</span></div></div>
      <div class="mh-due-side"><small>Ostatnio: ${formatDate(schedule.lastCompletedAt)}</small><small>Termin: ${formatDate(schedule.nextDueAt)}</small><button class="mh-button mh-button--primary" type="button" data-action="start" data-id="${instrument.id}">${instrument.questionnaireMode === "native" ? "Wypełnij" : "Wpisz wynik zewnętrzny"}</button><div><button class="mh-link-button" type="button" data-action="snooze" data-id="${instrument.id}">+3 dni</button><button class="mh-link-button" type="button" data-action="pause" data-id="${instrument.id}">Wstrzymaj</button></div></div>
    </article>`;
  }).join("") || '<div class="mh-empty mh-card">Brak aktywnych harmonogramów.</div>';
}

function renderCheckins() {
  const enabled = state.data.settings?.checkin_fields || {};
  document.getElementById("mh-checkin-fields").innerHTML = Object.entries(CHECKIN_LABELS).filter(([key]) => enabled[key] !== false).map(([key, label]) => `
    <label class="mh-slider"><span>${escapeHtml(label)}</span><output data-output="${key}">5</output><input name="${key}" type="range" min="0" max="10" value="5" /></label>`).join("");
  document.getElementById("mh-checkin-history").innerHTML = state.data.checkins.slice(0, 30).map((item) => {
    const values = Object.entries(item.values || {}).map(([key, value]) => `<span>${escapeHtml(CHECKIN_LABELS[key] || key)} <strong>${compactNumber(value)}</strong></span>`).join("");
    return `<article class="mh-history-item"><div><strong>${formatDate(item.recordedAt, true)}</strong><small>${escapeHtml(item.tags.join(" · "))}</small></div><div class="mh-value-chips">${values}</div>${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}<button type="button" data-action="delete-entry" data-kind="checkins" data-id="${item.id}">Usuń</button></article>`;
  }).join("") || '<div class="mh-empty">Brak check-inów.</div>';
}

function renderLibrary() {
  const search = document.getElementById("mh-library-search").value.trim().toLowerCase();
  const filter = document.getElementById("mh-library-filter").value;
  const schedules = scheduleMap();
  const latest = latestMap();
  const matches = state.data.registry.filter((instrument) => {
    const haystack = `${instrument.name} ${instrument.shortName} ${instrument.category} ${instrument.description}`.toLowerCase();
    if (search && !haystack.includes(search)) return false;
    if (filter === "enabled" && !schedules[instrument.id]?.enabled) return false;
    if (["state", "trait"].includes(filter) && instrument.constructType !== filter) return false;
    if (["native", "external-score"].includes(filter) && instrument.questionnaireMode !== filter) return false;
    return instrument.constructType !== "trait" && instrument.category !== "personality";
  });
  document.getElementById("mh-library").innerHTML = matches.map((instrument) => libraryCard(instrument, schedules[instrument.id], latest[instrument.id])).join("") || '<div class="mh-empty mh-card">Brak wyników filtra.</div>';
  renderAssessmentHistory();
}

function libraryCard(instrument, schedule, latest) {
  const draft = state.data.drafts?.[instrument.id];
  return `<article class="mh-library-card" data-enabled="${Boolean(schedule?.enabled)}">
    <div class="mh-library-head"><div><span>${escapeHtml(instrument.category)} · ${escapeHtml(instrument.constructType.toUpperCase())}</span><h3>${escapeHtml(instrument.shortName)}</h3><small>${escapeHtml(instrument.name)}</small></div><div class="mh-badges"><span>${escapeHtml(MODE_LABELS[instrument.questionnaireMode] || instrument.questionnaireMode)}</span>${draft ? "<span>SZKIC</span>" : ""}${instrument.custom ? "<span>CUSTOM</span>" : ""}</div></div>
    <p>${escapeHtml(instrument.description)}</p><div class="mh-meta-row"><span>${instrument.questionCount ?? instrument.itemCount ?? "—"} pytań${instrument.scoredItemCount && instrument.scoredItemCount !== instrument.questionCount ? ` · ${instrument.scoredItemCount} punktowanych` : ""}</span><span>${escapeHtml(instrument.recallPeriod)}</span><span>${instrument.defaultCadenceDays ? `co ${instrument.defaultCadenceDays} dni` : "baseline"}</span></div>
    <div class="mh-library-foot"><small>${draft ? `Szkic zapisany ${formatDate(draft.updatedAt, true)}` : latest ? `Ostatnio ${formatDate(latest.current.completedAt)} · ${escapeHtml(scoreLabel(instrument, latest.current))}` : "Brak wyniku"}</small><div><button type="button" class="mh-link-button" data-action="info" data-id="${instrument.id}">Info</button><button type="button" class="mh-button mh-button--primary" data-action="start" data-id="${instrument.id}">${instrument.questionnaireMode === "external-score" ? "Wpisz wynik" : draft ? "Wznów" : "Rozpocznij"}</button></div></div>
  </article>`;
}

function renderAssessmentHistory() {
  const query = document.getElementById("mh-history-search").value.trim().toLowerCase();
  const instruments = instrumentMap();
  const rows = state.data.assessments.filter((item) => {
    const instrument = instruments[item.instrumentId];
    return !query || `${instrument?.name} ${instrument?.shortName} ${item.notes} ${formatDate(item.completedAt)}`.toLowerCase().includes(query);
  });
  document.getElementById("mh-assessment-history").innerHTML = rows.slice(0, 200).map((item) => {
    const instrument = instruments[item.instrumentId] || { shortName: item.instrumentId };
    return `<article class="mh-history-item"><div><strong>${escapeHtml(instrument.shortName)} · ${escapeHtml(scoreLabel(instrument, item))}</strong><small>${formatDate(item.completedAt)} · v${escapeHtml(item.instrumentVersion)} / scoring ${escapeHtml(item.scoringVersion)}${item.isBaseline ? " · BASELINE" : ""}</small></div>${item.notes ? `<p>${escapeHtml(item.notes)}</p>` : ""}<div><button type="button" data-action="baseline" data-id="${item.id}">Ustaw baseline</button><button type="button" data-action="delete-entry" data-kind="assessments" data-id="${item.id}">Usuń</button></div></article>`;
  }).join("") || '<div class="mh-empty">Brak zapisanych badań.</div>';
}

function renderTrends() {
  const select = document.getElementById("mh-trend-instrument");
  const available = state.data.latest.flatMap((item) => {
    const dimensions = [];
    if (item.current.rawScore != null) dimensions.push({ key: item.instrument.id, label: item.instrument.shortName, instrument: item.instrument, history: item.history, source: item });
    item.instrument.subscales.forEach((subscale) => {
      if (!item.history.some((row) => Number.isFinite(Number(row.subscaleScores?.[subscale.id])))) return;
      const [scoreMin, scoreMax] = subscaleRange(item.instrument.id, subscale.id, item.instrument);
      dimensions.push({ key: `${item.instrument.id}:${subscale.id}`, label: `${item.instrument.shortName} · ${subscale.name}`, instrument: { ...item.instrument, shortName: `${item.instrument.shortName} · ${subscale.name}`, scoreMin, scoreMax, higherIsBetter: subscale.higherIsBetter ?? item.instrument.higherIsBetter }, history: item.history.filter((row) => Number.isFinite(Number(row.subscaleScores?.[subscale.id]))).map((row) => ({ ...row, rawScore: Number(row.subscaleScores[subscale.id]) })), source: item });
    });
    return dimensions;
  });
  if (!state.trendInstrument || !available.some((item) => item.key === state.trendInstrument)) state.trendInstrument = available[0]?.key || null;
  select.innerHTML = available.map((item) => `<option value="${item.key}" ${item.key === state.trendInstrument ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("");
  const item = available.find((entry) => entry.key === state.trendInstrument);
  const mode = document.getElementById("mh-trend-mode").value;
  document.getElementById("mh-trend-chart").innerHTML = item ? buildTrendSvg(item.history, item.instrument, mode) : '<div class="mh-empty">Dodaj co najmniej jeden wynik.</div>';
  renderHeatmap(item?.source);
}

function subscaleRange(instrumentId, subscaleId, instrument) {
  if (instrumentId === "cbi") return [0, 100];
  if (instrumentId === "spane") return subscaleId === "balance" ? [-24, 24] : [6, 30];
  if (instrumentId === "dass21") return [0, 42];
  if (instrumentId === "pcl5") return [0, 28];
  return [instrument.scoreMin ?? 0, instrument.scoreMax ?? 100];
}

function renderHeatmap(latest) {
  const root = document.getElementById("mh-item-heatmap");
  if (!latest) { root.innerHTML = '<div class="mh-empty">Wybierz skalę z historią odpowiedzi.</div>'; return; }
  const rows = state.data.assessments.filter((item) => item.instrumentId === latest.instrument.id && Object.keys(item.responses || {}).length).slice(0, 12).reverse();
  if (!rows.length) { root.innerHTML = `<div class="mh-empty">${escapeHtml(latest.instrument.shortName)} działa teraz jako external-score, więc nie zapisuje pozycji. Heatmapa uaktywni się po instalacji autoryzowanego pakietu pytań lub dla trackerów CUSTOM.</div>`; return; }
  const itemIds = [...new Set(rows.flatMap((row) => Object.keys(row.responses || {})))];
  const max = Math.max(1, ...rows.flatMap((row) => Object.values(row.responses || {}).map(Number).filter(Number.isFinite)));
  root.innerHTML = `<table><thead><tr><th>Pozycja</th>${rows.map((row) => `<th>${escapeHtml(new Date(row.completedAt).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" }))}</th>`).join("")}</tr></thead><tbody>${itemIds.map((id) => `<tr><th>${escapeHtml(latest.instrument.questions.find((q) => q.id === id)?.text || `#${id}`)}</th>${rows.map((row) => { const value = Number(row.responses?.[id]); return `<td style="--heat:${Number.isFinite(value) ? value / max : 0}" title="${Number.isFinite(value) ? value : "brak"}">${Number.isFinite(value) ? compactNumber(value) : "—"}</td>`; }).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderTraits() {
  const schedules = scheduleMap(); const latest = latestMap();
  const traits = state.data.registry.filter((instrument) => instrument.constructType === "trait" || instrument.category === "personality");
  document.getElementById("mh-trait-grid").innerHTML = traits.filter((instrument) => latest[instrument.id]).map((instrument) => scoreCard(latest[instrument.id])).join("") || '<div class="mh-empty mh-card">Profil cech pojawi się po zapisaniu pierwszego pomiaru.</div>';
  document.getElementById("mh-trait-library").innerHTML = traits.map((instrument) => libraryCard(instrument, schedules[instrument.id], latest[instrument.id])).join("");
}

function renderContext() {
  const entries = [
    ...state.data.events.map((item) => ({ ...item, kind: "event", date: item.occurredAt })),
    ...state.data.assessments.map((item) => ({ ...item, kind: "assessment", date: item.completedAt })),
  ].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 200);
  const instruments = instrumentMap();
  document.getElementById("mh-context-timeline").innerHTML = entries.map((item) => item.kind === "event"
    ? `<article class="mh-timeline-item"><i></i><div><span>${escapeHtml(item.eventType.replaceAll("_", " "))}</span><strong>${escapeHtml(item.title)}</strong><small>${formatDate(item.date, true)}</small>${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}</div><button type="button" data-action="delete-entry" data-kind="events" data-id="${item.id}">Usuń</button></article>`
    : `<article class="mh-timeline-item is-assessment"><i></i><div><span>assessment</span><strong>${escapeHtml(instruments[item.instrumentId]?.shortName || item.instrumentId)} · ${escapeHtml(scoreLabel(instruments[item.instrumentId] || {}, item))}</strong><small>${formatDate(item.date)}</small></div></article>`).join("") || '<div class="mh-empty">Brak zdarzeń i pomiarów.</div>';
}

function renderInsights() {
  const analytics = state.data.analytics90;
  const stable = analytics.mostStableDimension;
  const largest = analytics.largestNumericChange;
  document.getElementById("mh-insight-summary").innerHTML = `
    <article><span>Pomiary</span><strong>${analytics.assessmentCount}</strong><small>ostatnie 90 dni</small></article>
    <article><span>Najstabilniejszy wymiar</span><strong>${escapeHtml(stable?.shortName || "—")}</strong><small>${stable ? `zakres ${compactNumber(stable.range)}` : "potrzeba danych"}</small></article>
    <article><span>Największa zmiana liczbowa</span><strong>${escapeHtml(largest?.shortName || "—")}</strong><small>${largest ? `${largest.changeFromPrevious > 0 ? "+" : ""}${compactNumber(largest.changeFromPrevious)}` : "potrzeba 2 pomiarów"}</small></article>`;
  document.getElementById("mh-correlations").innerHTML = analytics.correlations?.length
    ? analytics.correlations.map((row) => `<article class="mh-correlation"><strong>${escapeHtml(row.dimension)} ↔ ${escapeHtml(CHECKIN_LABELS[row.checkinField] || row.checkinField)}</strong><span>Spearman ρ ${compactNumber(row.coefficient)} · N=${row.n}</span><small>Eksploracyjna zależność — nie dowodzi przyczynowości.</small></article>`).join("")
    : escapeHtml(analytics.correlationNotice);
}

function renderSettings() {
  const instruments = instrumentMap();
  document.getElementById("mh-schedule-settings").innerHTML = state.data.schedules.map((schedule) => {
    const instrument = instruments[schedule.instrumentId];
    return `<form class="mh-schedule-row" data-schedule="${schedule.instrumentId}"><label><input type="checkbox" name="enabled" ${schedule.enabled ? "checked" : ""}/> <strong>${escapeHtml(instrument.shortName)}</strong></label><label>co <input type="number" name="cadence" min="1" max="3650" value="${schedule.userCadenceDays || schedule.defaultCadenceDays || ""}" ${schedule.baselineOnly ? "disabled" : ""}/> dni</label><label><input type="checkbox" name="baselineOnly" ${schedule.baselineOnly ? "checked" : ""}/> baseline only</label><label><input type="checkbox" name="paused" ${schedule.paused ? "checked" : ""}/> pauza</label><button type="submit">Zapisz</button></form>`;
  }).join("");
  const enabled = state.data.settings?.checkin_fields || {};
  document.getElementById("mh-checkin-settings").innerHTML = Object.entries(CHECKIN_LABELS).map(([key, label]) => `<label><input type="checkbox" data-checkin-field="${key}" ${enabled[key] !== false ? "checked" : ""}/> ${escapeHtml(label)}</label>`).join("");
}

function renderCalendar() {
  const days = new Map();
  state.data.checkins.forEach((item) => { const key = item.recordedAt.slice(0, 10); days.set(key, { ...(days.get(key) || {}), checkin: true }); });
  state.data.assessments.forEach((item) => { const key = item.completedAt.slice(0, 10); days.set(key, { ...(days.get(key) || {}), assessment: true }); });
  const today = new Date(); const cells = [];
  for (let offset = 364; offset >= 0; offset -= 1) {
    const date = new Date(today); date.setHours(12, 0, 0, 0); date.setDate(date.getDate() - offset);
    const key = date.toISOString().slice(0, 10); const activity = days.get(key) || {};
    const level = activity.assessment && activity.checkin ? 3 : activity.assessment ? 2 : activity.checkin ? 1 : 0;
    cells.push(`<button type="button" data-calendar-date="${key}" data-level="${level}" title="${formatDate(key)} · ${level ? activity.assessment && activity.checkin ? "badanie i check-in" : activity.assessment ? "badanie" : "check-in" : "brak danych"}"></button>`);
  }
  document.getElementById("mh-calendar").innerHTML = cells.join("");
}

function renderAll() {
  renderSummary(); renderDue(); renderCheckins(); renderLibrary(); renderTrends();
  renderTraits(); renderContext(); renderInsights(); renderSettings(); renderCalendar();
}

function localDateTimeValue(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return localDateTimeValue(new Date());
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function nativeDraftPayload(form, instrument) {
  const responses = {};
  instrument.questions.forEach((question) => {
    const input = form.elements.namedItem(`response-${question.id}`);
    if (input && !input.disabled && input.value !== "") responses[question.id] = Number(input.value);
  });
  const completedAt = form.elements.namedItem("completedAt")?.value;
  return {
    responses,
    completedAt: completedAt ? new Date(completedAt).toISOString() : "",
    notes: form.elements.namedItem("notes")?.value || "",
  };
}

function questionConditionMet(question, responses) {
  if (question.visibleWhen) return question.visibleWhen.values.map(Number).includes(responses[question.visibleWhen.itemId]);
  if (question.visibleWhenAny) return question.visibleWhenAny.itemIds.some((id) => Number(responses[id]) >= Number(question.visibleWhenAny.minValue));
  return true;
}

function updateNativeQuestionState(instrument) {
  const form = document.getElementById("mh-assessment-form");
  const responses = nativeDraftPayload(form, instrument).responses;
  let visible = 0; let answered = 0;
  instrument.questions.forEach((question) => {
    const row = [...form.querySelectorAll("[data-question-id]")].find((node) => node.dataset.questionId === String(question.id));
    const input = form.elements.namedItem(`response-${question.id}`);
    const isVisible = questionConditionMet(question, responses);
    if (row) row.hidden = !isVisible;
    if (input) { input.disabled = !isVisible; input.required = isVisible && question.required !== false; }
    if (isVisible) { visible += 1; if (input?.value !== "") answered += 1; }
  });
  const progress = form.querySelector("[data-assessment-progress]");
  const bar = form.querySelector("[data-assessment-progress-bar]");
  if (progress) progress.textContent = `${answered}/${visible}`;
  if (bar) bar.style.width = `${visible ? (answered / visible) * 100 : 0}%`;
}

async function persistCurrentDraft(closeAfter = false) {
  const form = document.getElementById("mh-assessment-form");
  const instrumentId = form.elements.namedItem("instrumentId")?.value;
  const instrument = instrumentMap()[instrumentId];
  if (!instrument || instrument.questionnaireMode !== "native" || form.dataset.result === "true") {
    if (closeAfter) document.getElementById("mh-assessment-dialog").close();
    return;
  }
  const saved = await saveAssessmentDraft(instrument.id, nativeDraftPayload(form, instrument));
  state.data.drafts ||= {};
  state.data.drafts[instrument.id] = saved;
  if (closeAfter) { document.getElementById("mh-assessment-dialog").close(); renderLibrary(); }
}

function openAssessment(instrumentId) {
  const instrument = instrumentMap()[instrumentId]; const schedule = scheduleMap()[instrumentId];
  if (!instrument) return;
  const form = document.getElementById("mh-assessment-form");
  form.dataset.result = "false";
  const mode = instrument.questionnaireMode;
  const draft = state.data.drafts?.[instrument.id]?.payload || {};
  const warning = schedule?.lastCompletedAt && instrument.minimumRetestDays && (Date.now() - Date.parse(schedule.lastCompletedAt)) / 86400000 < instrument.minimumRetestDays
    ? '<div class="mh-inline-note">To badanie wykonano niedawno. Powtórzenie go teraz może wnieść niewiele informacji. Nadal możesz zapisać wynik.</div>' : "";
  const questions = mode === "native" ? `<div class="mh-question-progress"><div><strong>Postęp</strong><span data-assessment-progress>0/0</span></div><i><b data-assessment-progress-bar></b></i></div><fieldset class="mh-native-questions"><legend>${escapeHtml(instrument.instructions || "Odpowiedz na wszystkie widoczne pozycje")}</legend>${instrument.questions.map((question) => {
    const options = question.responseOptions || instrument.responseOptions;
    const saved = draft.responses?.[question.id];
    return `<label data-question-id="${escapeHtml(question.id)}"><span>${question.promptBefore ? `<strong class="mh-question-prompt">${escapeHtml(question.promptBefore)}</strong>` : ""}${escapeHtml(question.text)}${question.helpText ? `<small>${escapeHtml(question.helpText)}</small>` : ""}</span><select name="response-${escapeHtml(question.id)}"><option value="">Wybierz</option>${options.map((option) => `<option value="${option.value}" ${Number(saved) === Number(option.value) ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select></label>`;
  }).join("")}</fieldset>` : "";
  const totalInput = instrument.requiresTotalScore === false ? "" : `<label class="mh-field">Wynik całkowity <span>${instrument.scoreMin ?? "?"}–${instrument.scoreMax ?? "?"}</span><input type="number" name="totalScore" required step="any" ${instrument.scoreMin != null ? `min="${instrument.scoreMin}"` : ""} ${instrument.scoreMax != null ? `max="${instrument.scoreMax}"` : ""}/></label>`;
  const external = mode === "external-score" ? `<div class="mh-inline-note"><strong>Wynik zewnętrzny.</strong> Brak kompletnego, zweryfikowanego pakietu pytań. Wykonaj skalę w legalnym źródle i wpisz wynik bez reprodukowania pozycji.</div>${totalInput}${instrument.subscales.map((subscale) => `<label class="mh-field">${escapeHtml(subscale.name)}${subscale.optional ? " (opcjonalne)" : ""}<input type="number" step="any" name="subscale-${escapeHtml(subscale.id)}" ${instrument.requiresTotalScore === false && !subscale.optional ? "required" : ""}/></label>`).join("")}<label class="mh-field">Źródło wyniku<input name="sourceNote" placeholder="np. nazwa legalnego formularza" /></label><label class="mh-field">URL / referencja<input name="sourceUrl" type="url" /></label>` : questions;
  document.getElementById("mh-assessment-content").innerHTML = `
    <span class="mh-kicker">${escapeHtml(instrument.constructType.toUpperCase())} · ${escapeHtml(MODE_LABELS[mode] || mode)}</span><h2>${escapeHtml(instrument.name)}</h2><p>${escapeHtml(instrument.description)}</p>
    <div class="mh-assessment-intro"><span>${instrument.questionCount ?? instrument.itemCount ?? "—"} pytań${instrument.scoredItemCount && instrument.scoredItemCount !== instrument.questionCount ? ` · ${instrument.scoredItemCount} punktowanych` : ""}</span><span>~${instrument.estimatedMinutes} min</span><span>${escapeHtml(instrument.recallPeriod)}</span><span>${escapeHtml(instrument.language)}</span></div>
    <div class="mh-inline-note">To narzędzie screeningowe/samoopisowe, nie diagnoza.</div>${warning}${draft.responses && Object.keys(draft.responses).length ? `<div class="mh-inline-note">Wznowiono zapisany szkic.</div>` : ""}${external}
    <label class="mh-field">Data pomiaru<input name="completedAt" type="datetime-local" value="${escapeHtml(localDateTimeValue(draft.completedAt || new Date()))}" /></label>
    <label class="mh-field">Notatka<textarea name="notes" rows="3">${escapeHtml(draft.notes || "")}</textarea></label>
    <input type="hidden" name="instrumentId" value="${escapeHtml(instrument.id)}" />
    <div class="mh-dialog-actions">${mode === "native" ? '<button class="mh-button" type="button" data-action="save-draft">Zapisz szkic i zamknij</button>' : '<button class="mh-button" type="button" data-action="close-assessment">Anuluj</button>'}<button class="mh-button mh-button--primary" type="submit">Zapisz pomiar</button></div>`;
  document.getElementById("mh-assessment-dialog").showModal();
  if (mode === "native") updateNativeQuestionState(instrument);
}

function openInfo(instrumentId) {
  const instrument = instrumentMap()[instrumentId]; if (!instrument) return;
  const source = instrument.sourceMetadata;
  const sourceCopy = source?.url ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title)}</a>` : escapeHtml(instrument.source);
  const packs = (instrument.languagePacks || []).map((pack) => `${pack.language} · ${pack.scoringVersion}`).join("; ") || "brak lokalnego pakietu";
  document.getElementById("mh-info-content").innerHTML = `<span class="mh-kicker">Źródło i licencja</span><h2>${escapeHtml(instrument.name)} (${escapeHtml(instrument.shortName)})</h2><dl class="mh-info-list"><dt>Cel</dt><dd>${escapeHtml(instrument.description)}</dd><dt>Konstrukt</dt><dd>${escapeHtml(instrument.constructType)}</dd><dt>Pytania / recall</dt><dd>${instrument.questionCount ?? instrument.itemCount ?? "—"}${instrument.scoredItemCount ? ` (${instrument.scoredItemCount} punktowanych)` : ""} · ${escapeHtml(instrument.recallPeriod)}</dd><dt>Zakres</dt><dd>${instrument.scoreMin ?? "—"}–${instrument.scoreMax ?? "—"}</dd><dt>Źródło</dt><dd>${sourceCopy}</dd><dt>Licencja/użycie</dt><dd>${escapeHtml(instrument.licenseStatus)} · ${escapeHtml(instrument.licenseNotice)}</dd><dt>Atrybucja</dt><dd>${escapeHtml(instrument.attribution || "—")}</dd><dt>Tekst pytań</dt><dd>${escapeHtml(instrument.questionTextStatus)} · ${escapeHtml(MODE_LABELS[instrument.questionnaireMode] || instrument.questionnaireMode)}</dd><dt>Pakiety językowe</dt><dd>${escapeHtml(packs)}</dd><dt>Wersje</dt><dd>instrument ${escapeHtml(instrument.version)} · scoring ${escapeHtml(instrument.scoringVersion)}</dd></dl><p class="mh-inline-note">${escapeHtml(instrument.disclaimer)}</p>`;
  document.getElementById("mh-info-dialog").showModal();
}

function renderAssessmentResult(instrument, result) {
  const latest = latestMap()[instrument.id];
  const interpretation = result.interpretation?.label ? `<p><strong>Interpretacja:</strong> ${escapeHtml(result.interpretation.label)}</p>` : "";
  const notices = (result.interpretation?.notices || []).map((notice) => `<li>${escapeHtml(notice)}</li>`).join("");
  const history = (latest?.history || []).slice(-5).reverse().map((row) => `<li>${formatDate(row.completedAt)} · ${escapeHtml(scoreLabel(instrument, row))}</li>`).join("");
  document.getElementById("mh-assessment-form").dataset.result = "true";
  document.getElementById("mh-assessment-content").innerHTML = `<span class="mh-kicker">Pomiar zapisany</span><h2>${escapeHtml(instrument.name)}</h2><strong class="mh-result-score">${escapeHtml(scoreLabel(instrument, result))}</strong>${interpretation}${notices ? `<ul class="mh-result-notices">${notices}</ul>` : ""}<dl class="mh-info-list"><dt>Poprzedni wynik</dt><dd>${latest?.previous ? escapeHtml(scoreLabel(instrument, latest.previous)) : "—"}</dd><dt>Baseline</dt><dd>${latest?.baseline ? escapeHtml(scoreLabel(instrument, latest.baseline)) : "—"}</dd><dt>Data</dt><dd>${formatDate(result.completedAt, true)}</dd></dl><div class="mh-result-history"><strong>Historia</strong><ul>${history || "<li>Pierwszy pomiar</li>"}</ul></div><div class="mh-dialog-actions"><button class="mh-button mh-button--primary" type="button" data-action="close-assessment">Zamknij</button></div>`;
}

async function refresh() {
  state.data = await fetchMentalHealthOverview();
  renderAll();
}

function setError(error) {
  const node = document.getElementById("mh-error");
  node.textContent = error?.message || String(error || "Nieznany błąd"); node.hidden = false;
  window.scrollTo?.({ top: 0, behavior: "smooth" });
}

function clearError() { document.getElementById("mh-error").hidden = true; }

function switchTab(name) {
  document.querySelectorAll("[data-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.tab === name));
  document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === name));
  history.replaceState(null, "", `#${name}`);
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
function exportCsv(kind) {
  if (kind === "assessments") {
    const rows = [["completedAt", "instrumentId", "instrumentVersion", "scoringVersion", "rawScore", "normalizedScore", "subscales", "notes"], ...state.data.assessments.map((item) => [item.completedAt, item.instrumentId, item.instrumentVersion, item.scoringVersion, item.rawScore, item.normalizedScore, JSON.stringify(item.subscaleScores), item.notes])];
    download("mental-health-assessments.csv", rows.map((row) => row.map(csvCell).join(",")).join("\n"), "text/csv;charset=utf-8");
  } else {
    const fields = Object.keys(CHECKIN_LABELS); const rows = [["recordedAt", ...fields, "tags", "flags", "note"], ...state.data.checkins.map((item) => [item.recordedAt, ...fields.map((field) => item.values[field] ?? ""), item.tags.join("|"), item.flags.join("|"), item.note])];
    download("mental-health-checkins.csv", rows.map((row) => row.map(csvCell).join(",")).join("\n"), "text/csv;charset=utf-8");
  }
}

document.addEventListener("click", async (event) => {
  const tab = event.target.closest("[data-tab]"); if (tab) { switchTab(tab.dataset.tab); return; }
  const action = event.target.closest("[data-action]"); if (!action) return;
  clearError();
  try {
    if (action.dataset.action === "quick-checkin") switchTab("checkins");
    if (action.dataset.action === "start") openAssessment(action.dataset.id);
    if (action.dataset.action === "info") openInfo(action.dataset.id);
    if (action.dataset.action === "close-assessment") document.getElementById("mh-assessment-dialog").close();
    if (action.dataset.action === "save-draft") await persistCurrentDraft(true);
    if (["pause", "snooze"].includes(action.dataset.action)) {
      const current = scheduleMap()[action.dataset.id];
      const snooze = new Date(Date.now() + 3 * 86400000).toISOString();
      await updateAssessmentSchedule(action.dataset.id, { ...current, paused: action.dataset.action === "pause" ? true : current.paused, snoozedUntil: action.dataset.action === "snooze" ? snooze : current.snoozedUntil });
      await refresh();
    }
    if (action.dataset.action === "delete-entry") {
      if (!confirm("Usunąć ten wpis?")) return;
      await deleteMentalHealthEntry(action.dataset.kind, action.dataset.id); await refresh();
    }
    if (action.dataset.action === "baseline") { await setAssessmentBaseline(action.dataset.id); await refresh(); }
    if (action.dataset.action === "print-report") { document.body.dataset.reportRange = "90"; window.print(); }
    if (action.dataset.action === "export-json") {
      const payload = await fetchMentalHealthExport(); download(`mental-health-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(payload, null, 2), "application/json");
    }
    if (action.dataset.action === "export-assessments-csv") exportCsv("assessments");
    if (action.dataset.action === "export-checkins-csv") exportCsv("checkins");
    if (action.dataset.action === "delete-all") {
      if (!confirm("Usunąć WSZYSTKIE badania, check-iny i zdarzenia Mental Health? Tej operacji nie można cofnąć.")) return;
      if (prompt('Wpisz dokładnie "USUŃ"') !== "USUŃ") return;
      await deleteAllMentalHealthData(); await refresh();
    }
  } catch (error) { setError(error); }
});

document.addEventListener("input", (event) => {
  if (event.target.matches("#mh-checkin-fields input[type=range]")) document.querySelector(`[data-output="${event.target.name}"]`).textContent = event.target.value;
  if (event.target.closest("#mh-assessment-form") && event.target.name?.startsWith("response-")) {
    const instrumentId = document.getElementById("mh-assessment-form").elements.namedItem("instrumentId")?.value;
    const instrument = instrumentMap()[instrumentId];
    if (instrument?.questionnaireMode === "native") {
      updateNativeQuestionState(instrument);
      clearTimeout(state.draftTimer);
      state.draftTimer = setTimeout(() => { state.draftPromise = persistCurrentDraft().catch(setError); }, 400);
    }
  }
});

document.getElementById("mh-checkin-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearError(); const form = event.currentTarget; const data = new FormData(form);
  const values = {}; Object.keys(CHECKIN_LABELS).forEach((key) => { if (data.has(key)) values[key] = Number(data.get(key)); });
  const flags = [...form.querySelectorAll(".mh-flag-grid input:checked")].map((input) => input.value).filter((value) => FIELD_FLAGS.has(value));
  try { await createCheckin({ values, note: data.get("note"), tags: String(data.get("tags") || "").split(",").map((tag) => tag.trim()).filter(Boolean), flags }); form.reset(); await refresh(); } catch (error) { setError(error); }
});

document.getElementById("mh-event-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearError(); const data = Object.fromEntries(new FormData(event.currentTarget));
  if (data.occurredAt) data.occurredAt = new Date(data.occurredAt).toISOString();
  try { await createMentalHealthEvent(data); event.currentTarget.reset(); await refresh(); } catch (error) { setError(error); }
});

document.getElementById("mh-assessment-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearError(); const data = new FormData(event.currentTarget); const instrument = instrumentMap()[data.get("instrumentId")];
  const completedValue = data.get("completedAt");
  const payload = { instrumentId: instrument.id, completedAt: completedValue ? new Date(completedValue).toISOString() : undefined, notes: data.get("notes"), sourceNote: data.get("sourceNote"), sourceUrl: data.get("sourceUrl") };
  if (instrument.questionnaireMode === "native") {
    payload.responses = nativeDraftPayload(event.currentTarget, instrument).responses;
  } else {
    if (instrument.requiresTotalScore !== false) payload.totalScore = Number(data.get("totalScore"));
    payload.subscaleScores = {};
    instrument.subscales.forEach((subscale) => { const value = data.get(`subscale-${subscale.id}`); if (value !== "" && value != null) payload.subscaleScores[subscale.id] = Number(value); });
  }
  try {
    clearTimeout(state.draftTimer);
    if (state.draftPromise) await state.draftPromise;
    const result = await createAssessment(payload); await refresh(); renderAssessmentResult(instrumentMap()[instrument.id] || instrument, result);
    if (result.safetyNotice) alert(`${result.safetyNotice.title}\n\n${result.safetyNotice.message}\n\n112 · 999 · 800 70 2222`);
  } catch (error) { setError(error); }
});

document.getElementById("mh-library-search").addEventListener("input", renderLibrary);
document.getElementById("mh-library-filter").addEventListener("change", renderLibrary);
document.getElementById("mh-history-search").addEventListener("input", renderAssessmentHistory);
document.getElementById("mh-trend-instrument").addEventListener("change", (event) => { state.trendInstrument = event.target.value; renderTrends(); });
document.getElementById("mh-trend-mode").addEventListener("change", renderTrends);

document.getElementById("mh-schedule-settings").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-schedule]"); if (!form) return; event.preventDefault(); clearError();
  try { await updateAssessmentSchedule(form.dataset.schedule, { enabled: form.enabled.checked, paused: form.paused.checked, baselineOnly: form.baselineOnly.checked, userCadenceDays: form.cadence.disabled || !form.cadence.value ? null : Number(form.cadence.value) }); await refresh(); } catch (error) { setError(error); }
});

document.getElementById("mh-checkin-settings").addEventListener("change", async () => {
  const fields = Object.fromEntries([...document.querySelectorAll("[data-checkin-field]")].map((input) => [input.dataset.checkinField, input.checked]));
  try { await updateMentalHealthSettings({ checkin_fields: fields }); await refresh(); } catch (error) { setError(error); }
});

document.getElementById("mh-custom-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearError();
  const form = event.currentTarget; const data = new FormData(form);
  const questions = String(data.get("questions") || "").split(/\r?\n/).map((text) => text.trim()).filter(Boolean).map((text) => ({ text, reverse: false, subscale: "" }));
  const reverse = new Set(String(data.get("reverseItems") || "").split(",").map((value) => Number(value.trim())).filter((value) => Number.isInteger(value) && value >= 1));
  questions.forEach((question, index) => { question.reverse = reverse.has(index + 1); });
  String(data.get("subscales") || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).forEach((line) => {
    const separator = line.indexOf(":"); if (separator < 1) return;
    const name = line.slice(0, separator).trim();
    line.slice(separator + 1).split(",").map((value) => Number(value.trim())).forEach((number) => { if (questions[number - 1]) questions[number - 1].subscale = name; });
  });
  try {
    await createCustomQuestionnaire({ name: data.get("name"), shortName: data.get("shortName"), recallPeriod: data.get("recallPeriod"), defaultCadenceDays: Number(data.get("defaultCadenceDays")), responseMin: Number(data.get("responseMin")), responseMax: Number(data.get("responseMax")), questions });
    form.reset(); await refresh(); switchTab("assessments");
  } catch (error) { setError(error); }
});

document.getElementById("mh-import-file").addEventListener("change", async (event) => {
  const [file] = event.target.files; if (!file) return;
  try { const payload = JSON.parse(await file.text()); await importMentalHealthData(payload); await refresh(); } catch (error) { setError(error); } finally { event.target.value = ""; }
});

const initialTab = location.hash.slice(1);
if ([...document.querySelectorAll("[data-tab]")].some((node) => node.dataset.tab === (initialTab || "overview"))) switchTab(initialTab || "overview");
refresh().catch(setError);
