import "./widget-live-workout.js";
import { loadFileBackedSetting, saveFileBackedSetting } from "./file-settings.js";
import { collectLocalStorage, downloadTextFile, exportWorkoutToTCX, importLocalStorageBackup, validateFullBackup } from "./live-workout-transfer.js";
import { HR_ZONE_CONFIG, resolveMaxHr } from "./live-workout-engine.js";
import {
  CORE_FUNCTION_LABELS,
  EXERCISE_LIBRARY,
  HOME_STRENGTH_EQUIPMENT,
  MUSCLE_LABELS,
  PLAN_TRACKING_KEY,
  STRENGTH_GLOSSARY,
  STRENGTH_WORKOUTS,
  WARMUP_V1,
  cloneStrengthPlan,
  formatDumbbellLoad,
  isStrengthPlanEnabled,
  normalizeStrengthPlan,
} from "./live-workout-strength-data.js";
import { initStrengthTrainer, openStrengthTrainer } from "./live-workout-strength.js";
import { initStrengthApp } from "./strength-app.js";
import { liveWorkoutRuntimeUrl } from "./live-workout-runtime-api.js";
import { initJourneyPage } from "./live-workout-journey-page.js";
import {
  buildCardioEfficiencyRanking,
  buildCyclingCalorieRanking,
  calorieRankMedal,
  normalizeCyclingCalorieRanking,
} from "./live-workout-ranking.js";

const PLAN_ENDPOINT = liveWorkoutRuntimeUrl("plan");
const HISTORY_ENDPOINT = liveWorkoutRuntimeUrl("history");
const RANKING_ENDPOINT = liveWorkoutRuntimeUrl("calorie-ranking");
const SESSION_ENDPOINT = "/api/live-workout/session";
const BACKUP_ENDPOINT = "/api/live-workout/backup";
const PROFILE_STORAGE_KEY = "liveWorkout.profile.v1";

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const formatClock = (seconds) => {
  const safe = Math.max(0, Math.round(Number(seconds) || 0));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
};

const localDate = (timestamp) => new Date(Number(timestamp)).toLocaleDateString("sv-SE");
const dayLabel = (date) => new Intl.DateTimeFormat("pl-PL", { weekday: "long", day: "numeric", month: "long" }).format(new Date(`${date}T12:00:00`));
const rankingDateLabel = (date) => new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "long" }).format(new Date(`${date}T12:00:00`)).toLocaleLowerCase("pl-PL");
const rankingDurationLabel = (seconds) => {
  const minutes = Math.max(0, Math.round(Number(seconds) / 60) || 0);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${minutes} min`;
  return `${hours} h${rest ? ` ${rest} min` : ""}`;
};
const rankingSessionLabel = (count) => {
  const safe = Math.max(0, Math.round(Number(count) || 0));
  if (safe === 1) return "1 sesja";
  if (safe >= 2 && safe <= 4) return `${safe} sesje`;
  return `${safe} sesji`;
};
const cyclingLabels = { recovery: "Regeneracja", base: "Baza tlenowa", tempo: "Tempo", intervals: "Interwały", long: "Długi trening", rest: "Odpoczynek" };
const zoneLabels = { light: "LIGHT", intensive: "INTENSIVE", aerobic: "AEROBIC", anaerobic: "ANAEROBIC", vo2max: "VO₂MAX" };
const cyclingStatusLabels = { completed: "✓ Wykonany", partial: "Częściowy", skipped: "Pominięty", planned: "Plan", rest: "Odpoczynek" };

function zoneEntries(values = {}) {
  return HR_ZONE_CONFIG
    .map((zone) => ({ ...zone, value: Math.max(0, Number(values?.[zone.key]) || 0) }))
    .filter((zone) => zone.value > 0);
}

function renderZoneStrip(values, total, extraClass = "") {
  const entries = zoneEntries(values);
  if (!entries.length) return "";
  const safeTotal = Math.max(1, Number(total) || entries.reduce((sum, zone) => sum + zone.value, 0));
  return `<div class="workout-zone-strip ${extraClass}" aria-label="Rozkład stref tętna">${entries.map((zone) => `<i style="--zone-color:${zone.color};width:${zone.value / safeTotal * 100}%" title="${zoneLabels[zone.key]}: ${zone.value}"></i>`).join("")}</div>`;
}

function renderPlanZoneChips(values) {
  return `<div class="workout-plan-zone-chips">${zoneEntries(values).map((zone) => `<span style="--zone-color:${zone.color}"><i></i><b>${zoneLabels[zone.key]}</b><em>${zone.value}m</em></span>`).join("")}</div>`;
}

function renderHistoryZones(session) {
  const entries = zoneEntries(session?.zones);
  if (!entries.length) return "";
  const total = Math.max(1, Number(session.duration_seconds) || entries.reduce((sum, zone) => sum + zone.value, 0));
  return `<div class="workout-history-zone-block">${renderZoneStrip(session.zones, total, "is-history")}<div class="workout-history-zone-chips">${entries.map((zone) => `<span style="--zone-color:${zone.color}"><i></i><b>${zoneLabels[zone.key]}</b><strong>${formatClock(zone.value)}</strong></span>`).join("")}</div></div>`;
}

const elements = {
  status: document.getElementById("workout-app-status"),
  title: document.getElementById("workout-page-title"),
  kicker: document.getElementById("workout-page-kicker"),
  subtitle: document.getElementById("workout-page-subtitle"),
  todayStrength: document.getElementById("workout-today-strength"),
  nextStrip: document.getElementById("workout-next-strip"),
  planCalendar: document.getElementById("workout-plan-calendar"),
  planDetail: document.getElementById("workout-plan-detail"),
  programGrid: document.getElementById("workout-program-grid"),
  history: document.getElementById("workout-history"),
  rankingSummary: document.getElementById("workout-ranking-summary"),
  rankingColumn: document.getElementById("workout-ranking-column"),
  rankingKicker: document.getElementById("workout-ranking-kicker"),
  rankingTitle: document.getElementById("workout-ranking-title"),
  rankingList: document.getElementById("workout-ranking-list"),
  progressSummary: document.getElementById("workout-progress-summary"),
  progressList: document.getElementById("workout-progress-list"),
  libraryGrid: document.getElementById("workout-library-grid"),
  librarySearch: document.getElementById("workout-library-search"),
  libraryFilters: document.getElementById("workout-library-filters"),
  libraryDialog: document.getElementById("workout-library-dialog"),
  libraryDialogContent: document.getElementById("workout-library-dialog-content"),
  equipmentForm: document.getElementById("workout-equipment-form"),
  profileForm: document.getElementById("workout-profile-form"),
  glossary: document.getElementById("workout-glossary"),
  rescheduleDialog: document.getElementById("workout-reschedule-dialog"),
  rescheduleDate: document.getElementById("workout-reschedule-date"),
};

function loadWorkoutProfile() {
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(PROFILE_STORAGE_KEY) || "{}"); } catch {}
  const ageYears = Math.max(14, Math.min(100, Number(stored.ageYears) || 30));
  return {
    sex: stored.sex === "female" ? "female" : "male",
    ageYears,
    weightKg: Math.max(30, Math.min(300, Number(stored.weightKg) || 75)),
    maxHr: resolveMaxHr({ ageYears, maxHr: Number(stored.maxHr) || Number(localStorage.getItem("liveWorkout.maxHr")) }),
    bmrKcal: Math.max(800, Math.min(4000, Number(stored.bmrKcal) || 1800)),
  };
}

const state = {
  plan: null,
  history: [],
  ranking: [],
  rankingMode: "calories",
  tracking: { statuses: {}, notes: {}, strengthSessions: cloneStrengthPlan(), techniqueReviewed: {}, strengthEquipment: HOME_STRENGTH_EQUIPMENT },
  selectedSessionId: null,
  rescheduleSessionId: null,
  libraryFilter: "all",
  query: "",
};

const journeyPage = initJourneyPage();

function normalizeTracking(value) {
  const source = value && typeof value === "object" ? value : {};
  return {
    ...source,
    statuses: source.statuses && typeof source.statuses === "object" ? source.statuses : {},
    notes: source.notes && typeof source.notes === "object" ? source.notes : {},
    strengthSessions: normalizeStrengthPlan(source.strengthSessions || cloneStrengthPlan()),
    techniqueReviewed: source.techniqueReviewed && typeof source.techniqueReviewed === "object" ? source.techniqueReviewed : {},
    strengthEquipment: {
      ...HOME_STRENGTH_EQUIPMENT,
      ...(source.strengthEquipment || {}),
      dumbbells: { ...HOME_STRENGTH_EQUIPMENT.dumbbells, ...(source.strengthEquipment?.dumbbells || {}) },
    },
  };
}

function saveTracking() {
  state.tracking = normalizeTracking(state.tracking);
  saveFileBackedSetting({ name: "live-workout-plan", storageKey: PLAN_TRACKING_KEY, value: state.tracking });
}

function strengthHistoryFor(planSession) {
  return state.history.find((item) => item.workout_type === "strength" && item.strength_data?.planSessionId === planSession.id);
}

function strengthStatus(planSession) {
  const history = strengthHistoryFor(planSession);
  if (history?.status === "finished") return history.strength_data?.summary?.partial ? "partial" : "completed";
  return planSession.status || "planned";
}

function cyclingStatus(workout) {
  if (workout.type === "rest") return "rest";
  const actual = state.history.find((item) => item.status === "finished" && item.workout_type !== "strength" && item.workout_type !== "virtual_walk" && item.plan_date === workout.date && item.plan_id !== "free-ride");
  if (actual) return actual.plan_completed === false ? "partial" : "completed";
  return state.tracking.statuses?.[workout.date] || "planned";
}

function sessionsForDate(date) {
  const result = [];
  const cycling = state.plan?.schedule?.find((item) => item.date === date);
  if (cycling) result.push({ id: `cycling-${date}`, workoutType: "cycling", date, workout: cycling, status: cyclingStatus(cycling) });
  if (isStrengthPlanEnabled(state.tracking)) {
    state.tracking.strengthSessions.filter((item) => item.date === date).forEach((item) => result.push({ ...item, status: strengthStatus(item) }));
  }
  return result;
}

function setTab(tab, updateHash = true) {
  const valid = [...document.querySelectorAll("[data-workout-view]")].some((view) => view.dataset.workoutView === tab) ? tab : "today";
  if (valid === "ranking") state.rankingMode = "calories";
  document.querySelectorAll("[data-workout-view]").forEach((view) => {
    const active = view.dataset.workoutView === valid;
    view.hidden = !active;
    view.classList.toggle("is-active", active);
  });
  document.querySelectorAll("[data-workout-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.workoutTab === valid));
  const copy = {
    today: ["DZISIAJ", "Centrum treningowe", "Wybierz sesję i przejdź do trybu Focus."],
    plan: ["PLAN", "Kalendarz wielosesyjny", "Cycling i strength są niezależnymi jednostkami tego samego dnia."],
    strength: ["STRENGTH", "Micro-workouts", "Pojedyncze serie, tygodniowa objętość i progresja."],
    history: ["HISTORIA", "Dziennik treningowy", "Wszystkie zapisane aktywności w jednym miejscu."],
    ranking: ["RANKING", "Najmocniejsze dni cardio", "Trening, Free Ride i spacer składają się na jeden dzienny wynik."],
    progress: ["PROGRES", "Progres siłowy", "Rzeczywiste serie, ciężary i powtórzenia."],
    journey: ["PODRÓŻ", "Kraków → Santiago", "Mapa wyprawy, odkryte miejsca i kolekcja pocztówek."],
    library: ["BIBLIOTEKA", "Naucz się ćwiczeń", "Instrukcje działają także bez filmu."],
    settings: ["KONFIGURACJA", "Sprzęt i terminologia", "Profil domowego zestawu i słowniczek."],
  }[valid];
  [elements.kicker.textContent, elements.title.textContent, elements.subtitle.textContent] = copy;
  if (valid === "ranking") renderRanking();
  if (valid === "journey") journeyPage.refresh({ force: true });
  if (updateHash) history.replaceState(null, "", `#${valid}`);
}

function renderToday() {
  const strengthPlanEnabled = isStrengthPlanEnabled(state.tracking);
  elements.todayStrength.hidden = !strengthPlanEnabled;
  elements.nextStrip.hidden = !strengthPlanEnabled;
  const topbarStrengthStart = document.querySelector(".workout-app-topbar [data-strength-start]");
  if (topbarStrengthStart) topbarStrengthStart.hidden = !strengthPlanEnabled;
  if (!strengthPlanEnabled) return;
  const today = new Date().toLocaleDateString("sv-SE");
  const strength = state.tracking.strengthSessions.filter((item) => item.date === today);
  if (!strength.length) {
    const next = state.tracking.strengthSessions.filter((item) => item.date >= today && !["completed", "skipped"].includes(strengthStatus(item))).sort((a, b) => a.date.localeCompare(b.date))[0];
    elements.todayStrength.innerHTML = `<span class="workout-card-overline">STRENGTH · ${next ? `NASTĘPNA ${next.date}` : "BRAK NA DZIŚ"}</span><h3>${next ? `Workout ${next.workoutId}${next.workoutVariant === "LIGHT" ? " · LIGHT" : ""}` : "Dzień bez sesji siłowej"}</h3><p>${next ? "45–55 min · rozgrzewka + FBW + core" : "Możesz uruchomić dowolny trening A lub B poza planem."}</p><div><button type="button" data-strength-start="${next?.workoutId || "A"}" data-strength-variant="${next?.workoutVariant || "STANDARD"}" data-strength-plan-id="${next?.id || ""}" data-strength-plan-date="${next?.date || today}">START ${next ? `WORKOUT ${next.workoutId}` : "STRENGTH A"}</button><button type="button" data-workout-tab-jump="strength">ZOBACZ PROGRAM</button></div>`;
  } else {
    elements.todayStrength.innerHTML = strength.map((item) => {
      const status = strengthStatus(item);
      const action = status === "completed"
        ? `<button type="button" data-workout-tab-jump="history">OTWÓRZ PODSUMOWANIE</button>`
        : `<button type="button" data-strength-start="${item.workoutId}" data-strength-variant="${item.workoutVariant}" data-strength-plan-id="${item.id}" data-strength-plan-date="${item.date}">START STRENGTH</button>`;
      return `<article><span class="workout-card-overline">STRENGTH · ${escapeHtml(status)}</span><h3>Workout ${item.workoutId}${item.workoutVariant === "LIGHT" ? " · LIGHT" : ""}</h3><p>45–55 min · rozgrzewka + FBW + core</p>${action}</article>`;
    }).join("");
  }
  const upcoming = state.tracking.strengthSessions.filter((item) => item.date >= today).sort((a, b) => a.date.localeCompare(b.date)).slice(0, 3);
  elements.nextStrip.innerHTML = `<div><span>NAJBLIŻSZE SESJE SIŁOWE</span><strong>Faza adaptacji</strong></div>${upcoming.map((item) => `<article><time>${escapeHtml(item.date.slice(5))}</time><b>Workout ${item.workoutId}</b><small>${item.workoutVariant === "LIGHT" ? "LIGHT · reduced legs" : "standard"}</small></article>`).join("")}`;
}

function renderPlanDetail(id) {
  state.selectedSessionId = id;
  const cycling = id?.startsWith("cycling-") ? state.plan?.schedule?.find((item) => item.date === id.slice(8)) : null;
  if (cycling) {
    const status = cyclingStatus(cycling);
    elements.planDetail.innerHTML = `<span class="workout-card-overline is-cycling">CYCLING · ${escapeHtml(status)}</span><h3>${escapeHtml(cyclingLabels[cycling.type] || cycling.type)}</h3><time>${escapeHtml(cycling.date)} · ${cycling.duration} min</time><p>${escapeHtml(cycling.purpose)}</p>${cycling.type === "rest" ? "" : `${renderZoneStrip(cycling.zones, cycling.duration, "is-detail")}<div class="workout-zone-mini">${zoneEntries(cycling.zones).map((zone) => `<span style="--zone-color:${zone.color}" data-zone="${zone.key}"><i></i><b>${zoneLabels[zone.key]}</b><strong>${zone.value} min</strong></span>`).join("")}</div><div class="workout-detail-actions"><button data-cycling-status="completed" data-cycling-date="${cycling.date}">UKOŃCZONY</button><button data-cycling-status="partial" data-cycling-date="${cycling.date}">CZĘŚCIOWY</button><button data-cycling-status="skipped" data-cycling-date="${cycling.date}">POMINIĘTY</button></div>`}`;
    return;
  }
  const strength = state.tracking.strengthSessions.find((item) => item.id === id);
  if (!strength) { elements.planDetail.innerHTML = "<p>Wybierz sesję z planu.</p>"; return; }
  elements.planDetail.innerHTML = `<span class="workout-card-overline is-strength">STRENGTH · ${escapeHtml(strengthStatus(strength))}</span><h3>Workout ${strength.workoutId}${strength.workoutVariant === "LIGHT" ? " · LIGHT" : ""}</h3><time>${escapeHtml(strength.date)} · 45–55 min</time><p>Adaptacja techniczna · bez treningu do upadku.</p><div class="workout-detail-actions"><button data-strength-start="${strength.workoutId}" data-strength-variant="${strength.workoutVariant}" data-strength-plan-id="${strength.id}" data-strength-plan-date="${strength.date}">START</button><button data-strength-plan-action="reschedule" data-plan-session-id="${strength.id}">PRZENIEŚ</button><button data-strength-plan-action="partial" data-plan-session-id="${strength.id}">CZĘŚCIOWY</button><button data-strength-plan-action="skipped" data-plan-session-id="${strength.id}">POMIŃ</button><button data-strength-plan-action="planned" data-plan-session-id="${strength.id}">WYCZYŚĆ STATUS</button></div>`;
}

function renderPlan() {
  if (!state.plan?.schedule?.length) { elements.planCalendar.innerHTML = "<p>Plan jest niedostępny.</p>"; return; }
  const weeks = state.plan.weeks || [];
  elements.planCalendar.innerHTML = weeks.map((week) => {
    const dates = state.plan.schedule.filter((item) => item.date >= week.start_date && item.date <= week.end_date);
    const range = `${new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "short" }).format(new Date(`${week.start_date}T12:00:00`))} – ${new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "short" }).format(new Date(`${week.end_date}T12:00:00`))}`;
    return `<section class="workout-plan-week"><header><div><span>${escapeHtml(week.theme)}</span><strong>${escapeHtml(week.label)}</strong><small>${escapeHtml(range)}</small></div><b>${week.planned_minutes} min cycling</b></header><div>${dates.map((day) => {
      const date = new Date(`${day.date}T12:00:00`);
      const strength = isStrengthPlanEnabled(state.tracking)
        ? state.tracking.strengthSessions.filter((item) => item.date === day.date)
        : [];
      const status = cyclingStatus(day);
      const month = new Intl.DateTimeFormat("pl-PL", { month: "short" }).format(date).replace(".", "");
      return `<article class="workout-plan-day ${day.date === new Date().toLocaleDateString("sv-SE") ? "is-today" : ""}"><div class="workout-plan-date"><span>${new Intl.DateTimeFormat("pl-PL", { weekday: "short" }).format(date)}</span><strong>${date.getDate()}<em>${month}</em></strong></div><button class="workout-plan-session is-cycling is-${status}" data-plan-session="cycling-${day.date}"><span class="workout-plan-session-head"><b>${escapeHtml(cyclingLabels[day.type] || day.type)}</b><small>${day.type === "rest" ? "REST" : `${day.duration} min`}</small></span>${day.type === "rest" ? `<span class="workout-plan-rest-copy">Pełna regeneracja</span>` : `${renderZoneStrip(day.zones, day.duration)}${renderPlanZoneChips(day.zones)}`}<span class="workout-plan-session-status">${cyclingStatusLabels[status] || status}</span></button>${strength.map((item) => `<button class="workout-plan-session is-strength is-${strengthStatus(item)}" data-plan-session="${item.id}"><b>Strength ${item.workoutId}</b><small>${item.workoutVariant === "LIGHT" ? "LIGHT" : "~50 min"}</small></button>`).join("")}</article>`;
    }).join("")}</div></section>`;
  }).join("");
  if (state.selectedSessionId) renderPlanDetail(state.selectedSessionId);
}

function exerciseRow(id) {
  const item = EXERCISE_LIBRARY[id];
  return `<li><span>${escapeHtml(item.namePl)}<small>${escapeHtml(item.nameEn)}</small></span><b>${escapeHtml(item.executionMode.startsWith("timed") ? `${item.defaultSets} × ${item.durationMin}–${item.durationMax} s` : `${item.defaultSets} × ${item.repMin}–${item.repMax}`)}</b><strong>${escapeHtml(formatDumbbellLoad(item.weightPerDumbbellKg, item.dumbbellCount))}</strong></li>`;
}

function renderPrograms() {
  elements.programGrid.innerHTML = Object.values(STRENGTH_WORKOUTS).map((workout) => `<article class="workout-program-card"><header><div><span>FULL BODY · ${workout.phase}</span><h3>${workout.label}</h3><p>${workout.estimatedDurationMin}–${workout.estimatedDurationMax} min</p></div><button data-strength-start="${workout.id.endsWith("b") ? "B" : "A"}">START</button></header><div class="workout-program-warmup"><b>ROZGRZEWKA · 6–7 MIN</b><span>${WARMUP_V1.map((id) => EXERCISE_LIBRARY[id].namePl).join(" · ")}</span></div><ol>${workout.exerciseIds.map(exerciseRow).join("")}</ol></article>`).join("");
}

function strengthHistoryCard(session) {
  const data = session.strength_data || {};
  const summary = data.summary || {};
  return `<article class="workout-history-card is-strength"><header><div><span>STRENGTH</span><h4>${escapeHtml(data.workoutLabel || session.title || "Trening siłowy")}${data.workoutVariant === "LIGHT" ? " · LIGHT" : ""}</h4></div><b>${formatClock(session.duration_seconds)}</b></header><div class="workout-history-kpis"><span><strong>${summary.completedSets ?? "—"}/${summary.plannedSets ?? "—"}</strong>serie</span><span><strong>${summary.totalReps ?? "—"}</strong>powt.</span><span><strong>${session.session_rpe ?? "—"}</strong>RPE</span><span><strong>${session.avg_hr ?? "—"}</strong>śr. HR</span></div><details><summary>Ćwiczenia i serie</summary>${(data.exercises || []).map((exercise) => `<section><h5>${escapeHtml(EXERCISE_LIBRARY[exercise.exerciseId]?.namePl || exercise.exerciseId)}</h5>${(exercise.sets || []).map((set) => `<p class="${set.skipped ? "is-skipped" : ""}"><b>SERIA ${set.setNumber}</b><span>${set.skipped ? "Pominięta" : set.actualReps != null ? `${set.dumbbellCount ? `${set.dumbbellCount} × ${set.actualWeightPerDumbbellKg} kg · ` : ""}${set.actualReps} powt. · RIR ${set.actualRir ?? "—"}` : `${Math.round(set.actualDuration || 0)} s`}</span></p>`).join("") || "<p>Brak zapisanych serii.</p>"}</section>`).join("")}</details>${session.notes ? `<blockquote>${escapeHtml(session.notes)}</blockquote>` : ""}<footer class="workout-history-actions"><button type="button" data-history-delete="${escapeHtml(session.id)}">USUŃ SESJĘ</button></footer></article>`;
}

function cardioHistoryCard(session) {
  const walking = session.workout_type === "virtual_walk";
  return `<article class="workout-history-card ${walking ? "is-walking" : "is-cycling"}"><header><div><span>${walking ? "WALKING" : "CYCLING"}</span><h4>${escapeHtml(session.title || (walking ? "Sesja spacerowa" : "Indoor cycling"))}</h4></div><b>${formatClock(session.duration_seconds)}</b></header><div class="workout-history-kpis"><span><strong>${session.active_calories == null ? "—" : session.active_calories}</strong>kcal</span><span><strong>${session.avg_hr ?? "—"}</strong>śr. HR</span><span><strong>${session.max_hr ?? "—"}</strong>max HR</span><span><strong>${walking ? session.virtual_steps ?? "—" : session.training_load ?? "—"}</strong>${walking ? "kroki" : "load"}</span></div>${renderHistoryZones(session)}<footer class="workout-history-actions"><button type="button" data-history-tcx="${escapeHtml(session.id)}">POBIERZ TCX</button><button type="button" data-history-delete="${escapeHtml(session.id)}">USUŃ SESJĘ</button></footer></article>`;
}

function renderHistory() {
  const finished = state.history.filter((item) => item.status === "finished");
  if (!finished.length) { elements.history.innerHTML = '<div class="workout-empty">Historia jest jeszcze pusta.</div>'; return; }
  const groups = Map.groupBy ? Map.groupBy(finished, (item) => localDate(item.started_at)) : finished.reduce((map, item) => map.set(localDate(item.started_at), [...(map.get(localDate(item.started_at)) || []), item]), new Map());
  elements.history.innerHTML = [...groups.entries()].map(([date, sessions]) => `<section class="workout-history-day"><header><div><span>${escapeHtml(date)}</span><h3>${escapeHtml(dayLabel(date))}</h3></div><b>${sessions.length} ${sessions.length === 1 ? "sesja" : "sesje"}</b></header><div>${sessions.map((item) => item.workout_type === "strength" ? strengthHistoryCard(item) : cardioHistoryCard(item)).join("")}</div></section>`).join("");
}

function rankingChartDateLabel(date) {
  return new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", year: "numeric" })
    .format(new Date(`${date}T12:00:00`))
    .replaceAll(".", "")
    .toLocaleLowerCase("pl-PL");
}

function renderRankingChart(ranking) {
  const today = new Date().toLocaleDateString("sv-SE");
  const endDate = state.rankingChartEndDate > today ? today : state.rankingChartEndDate;
  const series = buildCardioCalorieChartSeries(ranking, { endDate, dayCount: 30 });
  if (!ranking.length) {
    elements.rankingChart.innerHTML = '<div class="workout-ranking-chart-empty">Wykres pojawi się po pierwszej aktywności cardio.</div>';
    return;
  }
  const trend = summarizeCardioCalorieTrend(series);
  const canGoBack = ranking.some((day) => day.date < series[0].date);
  const canGoForward = endDate < today;
  const width = 900;
  const height = 300;
  const padX = 34;
  const padTop = 24;
  const padBottom = 42;
  const plotRight = width - 82;
  const plotWidth = plotRight - padX;
  const plotHeight = height - padTop - padBottom;
  const axisMax = Math.max(100, Math.ceil(Math.max(...series.map((day) => day.activeCalories)) / 100) * 100);
  const x = (index) => padX + (series.length === 1 ? 0 : index / (series.length - 1) * plotWidth);
  const y = (value) => padTop + (1 - Math.max(0, Number(value) || 0) / axisMax) * plotHeight;
  const linePath = series.map((day, index) => `${index ? "L" : "M"}${x(index).toFixed(1)} ${y(day.activeCalories).toFixed(1)}`).join(" ");
  const averagePath = series.map((day, index) => `${index ? "L" : "M"}${x(index).toFixed(1)} ${y(day.movingAverage).toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${x(series.length - 1).toFixed(1)} ${(height - padBottom).toFixed(1)} L${x(0).toFixed(1)} ${(height - padBottom).toFixed(1)} Z`;
  const gradients = series.map((day, index) => {
    const cyclingPercent = day.activeCalories ? day.cyclingCalories / day.activeCalories * 100 : 100;
    return `<linearGradient id="workout-rank-point-${index}"><stop offset="${cyclingPercent}%" stop-color="#fb7185"/><stop offset="${cyclingPercent}%" stop-color="#60a5fa"/></linearGradient>`;
  }).join("");
  const points = series.map((day, index) => {
    const cyclingPercent = day.activeCalories ? Math.round(day.cyclingCalories / day.activeCalories * 100) : 0;
    const walkingPercent = day.activeCalories ? 100 - cyclingPercent : 0;
    return `<circle class="workout-ranking-chart-dot ${day.activeCalories > 0 ? "has-value" : ""}" cx="${x(index).toFixed(1)}" cy="${y(day.activeCalories).toFixed(1)}" r="${day.activeCalories > 0 ? 5 : 2.5}" fill="${day.activeCalories > 0 ? `url(#workout-rank-point-${index})` : "#3f3f46"}"><title>${escapeHtml(rankingDateLabel(day.date))}: ${day.activeCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal · rowerek ${cyclingPercent}% · spacer ${walkingPercent}%</title></circle>`;
  }).join("");
  const trendCopy = trend.direction === "up"
    ? `MA7 rośnie o ${Math.abs(trend.delta).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal (${Math.abs(trend.changePercent).toLocaleString("pl-PL", { maximumFractionDigits: 0 })}%) względem tygodnia wcześniej.`
    : trend.direction === "down"
      ? `MA7 spada o ${Math.abs(trend.delta).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal (${Math.abs(trend.changePercent).toLocaleString("pl-PL", { maximumFractionDigits: 0 })}%) względem tygodnia wcześniej.`
      : "MA7 jest stabilna względem tygodnia wcześniej.";
  elements.rankingChart.innerHTML = `
    <header class="workout-ranking-chart-head"><div><strong>Dzienne kcal cardio</strong><span>${escapeHtml(rankingChartDateLabel(series[0].date))} – ${escapeHtml(rankingChartDateLabel(series.at(-1).date))}</span></div><div class="workout-ranking-chart-toolbar"><button type="button" data-ranking-chart-shift="-30" aria-label="Poprzednie 30 dni" ${canGoBack ? "" : "disabled"}>‹</button><button type="button" data-ranking-chart-shift="30" aria-label="Następne 30 dni" ${canGoForward ? "" : "disabled"}>›</button><b>30 dni</b></div></header>
    <div class="workout-ranking-chart-legend"><span class="is-cycling">Rower / trening / Free Ride</span><span class="is-walking">Spacer</span><span class="is-average">MA7</span></div>
    <svg class="workout-ranking-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Dzienne aktywne kalorie cardio z ostatnich 30 dni">
      <defs>${gradients}<linearGradient id="workout-rank-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fb7185" stop-opacity=".18"/><stop offset="1" stop-color="#fb7185" stop-opacity="0"/></linearGradient></defs>
      ${[0, .5, 1].map((ratio) => `<line class="workout-ranking-chart-grid" x1="${padX}" y1="${(padTop + plotHeight * ratio).toFixed(1)}" x2="${plotRight}" y2="${(padTop + plotHeight * ratio).toFixed(1)}"/>`).join("")}
      <path class="workout-ranking-chart-area" d="${areaPath}"/>
      <path class="workout-ranking-chart-line" d="${linePath}"/>
      <path class="workout-ranking-chart-average" d="${averagePath}"/>
      ${points}
      <text class="workout-ranking-chart-scale" x="${plotRight + 12}" y="${padTop + 5}">${axisMax.toLocaleString("pl-PL")} kcal</text>
      <text class="workout-ranking-chart-scale" x="${plotRight + 12}" y="${height - padBottom + 5}">0</text>
      <text class="workout-ranking-chart-label" x="${padX}" y="${height - 8}">${escapeHtml(rankingChartDateLabel(series[0].date))}</text>
      <text class="workout-ranking-chart-label" x="${plotRight}" y="${height - 8}" text-anchor="end">${escapeHtml(rankingChartDateLabel(series.at(-1).date))}</text>
    </svg>
    <div class="workout-ranking-chart-insights">
      <article data-trend="${trend.direction}"><span>TREND MA7</span><strong>${trend.latestMa7.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal/dzień</strong><small>${escapeHtml(trendCopy)}</small></article>
      <article><span>REGULARNOŚĆ · 7 DNI</span><strong>${trend.recentActiveDays}/7 aktywnych dni</strong><small>${trend.recentActiveDays > trend.previousActiveDays ? `+${trend.recentActiveDays - trend.previousActiveDays}` : trend.recentActiveDays - trend.previousActiveDays} względem poprzednich 7 dni</small></article>
      <article><span>MIX · 7 DNI</span><strong>🚴 ${Math.round(trend.cyclingPercent)}% · 🚶 ${Math.round(trend.walkingPercent)}%</strong><small>udział w aktywnych kcal cardio</small></article>
    </div>`;
}

function rankingRowsMarkup(days, today, efficiencyMode = false) {
  return days.map((day) => {
    const medal = calorieRankMedal(day.position);
    const cyclingPercent = day.activeCalories ? day.cyclingCalories / day.activeCalories * 100 : 0;
    const walkingPercent = day.activeCalories ? day.walkingCalories / day.activeCalories * 100 : 0;
    const caloriesPerHour = day.durationSeconds > 0 ? day.activeCalories / day.durationSeconds * 3600 : 0;
    const detail = efficiencyMode
      ? `${rankingSessionLabel(day.sessionCount)} · ${rankingDurationLabel(day.durationSeconds)} · ${day.activeCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal łącznie`
      : `${rankingSessionLabel(day.sessionCount)} · ${rankingDurationLabel(day.durationSeconds)} · ${day.durationSeconds > 0 ? `${Math.round(caloriesPerHour).toLocaleString("pl-PL")} kcal/h` : "brak danych kcal/h"}`;
    const score = efficiencyMode ? day.caloriesPerHour : day.activeCalories;
    return `<article class="workout-ranking-row ${efficiencyMode ? "is-efficiency" : ""} ${day.position <= 3 ? `is-podium is-place-${day.position}` : ""} ${day.date === today ? "is-today" : ""}">
      <div class="workout-ranking-position">${medal ? `<span aria-label="Miejsce ${day.position}">${medal}</span>` : `<strong>${day.position}</strong>`}</div>
      <div class="workout-ranking-date"><span>${day.date === today ? "DZISIAJ" : escapeHtml(day.date)}</span><strong>${escapeHtml(rankingDateLabel(day.date))}</strong><small>${detail}</small><div class="workout-ranking-mix"><i style="width:${cyclingPercent}%"></i><b style="width:${walkingPercent}%"></b></div><small>🚴 ${Math.round(cyclingPercent)}% · 🚶 ${Math.round(walkingPercent)}%</small></div>
      <div class="workout-ranking-score"><strong>${score.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}</strong><span>${efficiencyMode ? "kcal/h" : "kcal"}</span></div>
    </article>`;
  }).join("");
}

function renderRanking() {
  const ranking = normalizeCyclingCalorieRanking(state.ranking);
  const efficiencyRanking = buildCardioEfficiencyRanking(ranking);
  const efficiencyMode = state.rankingMode === "efficiency";
  document.querySelectorAll("[data-ranking-mode]").forEach((button) => {
    const active = button.dataset.rankingMode === state.rankingMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  elements.rankingColumn.classList.toggle("is-efficiency", efficiencyMode);
  elements.rankingKicker.textContent = efficiencyMode ? "WYDAJNOŚĆ" : "KLASYFIKACJA";
  elements.rankingTitle.textContent = efficiencyMode ? "Najlepsze dni · kcal/h" : "Najlepsze dni · łączne kcal";
  if (!ranking.length) {
    elements.rankingSummary.innerHTML = "";
    elements.rankingList.innerHTML = '<div class="workout-empty">Ranking pojawi się po pierwszym dniu z wynikiem większym niż 0 kcal.</div>';
    return;
  }
  const today = new Date().toLocaleDateString("sv-SE");
  const todayEntry = ranking.find((day) => day.date === today);
  const totalCalories = ranking.reduce((sum, day) => sum + day.activeCalories, 0);
  elements.rankingSummary.innerHTML = `
    <article><span>REKORD DNIA</span><strong>${ranking[0].activeCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal</strong><small>${escapeHtml(rankingDateLabel(ranking[0].date))}</small></article>
    <article><span>SKLASYFIKOWANE DNI</span><strong>${ranking.length}</strong><small>tylko wyniki &gt; 0 kcal</small></article>
    <article><span>ŁĄCZNIE CARDIO</span><strong>${Math.round(totalCalories).toLocaleString("pl-PL")} kcal</strong><small>trening + Free Ride + spacer</small></article>
    <article class="${todayEntry ? "is-today" : ""}"><span>DZISIAJ</span><strong>${todayEntry ? `#${todayEntry.position}` : "—"}</strong><small>${todayEntry ? `${todayEntry.activeCalories.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} kcal` : "jeszcze bez wyniku"}</small></article>`;
  const visibleRanking = efficiencyMode ? efficiencyRanking : ranking;
  elements.rankingList.innerHTML = visibleRanking.length
    ? rankingRowsMarkup(visibleRanking, today, efficiencyMode)
    : '<div class="workout-empty">Brak dni z zapisanym czasem potrzebnym do obliczenia kcal/h.</div>';
}

function renderProgress() {
  const strength = state.history.filter((item) => item.status === "finished" && item.workout_type === "strength" && item.strength_data);
  const allSets = strength.flatMap((session) => (session.strength_data.exercises || []).flatMap((exercise) => (exercise.sets || []).filter((set) => !set.skipped).map((set) => ({ ...set, exerciseId: exercise.exerciseId, date: localDate(session.started_at) }))));
  const coreSets = allSets.filter((set) => EXERCISE_LIBRARY[set.exerciseId]?.isCore).length;
  elements.progressSummary.innerHTML = `<article><span>SESJE</span><strong>${strength.length}</strong></article><article><span>SERIE</span><strong>${allSets.length}</strong></article><article><span>CORE</span><strong>${coreSets} serii</strong></article><article><span>OSTATNIE 7 DNI</span><strong>${strength.filter((item) => Date.now() - Number(item.started_at) <= 7 * 86400000).length}</strong></article>`;
  const grouped = allSets.reduce((map, set) => map.set(set.exerciseId, [...(map.get(set.exerciseId) || []), set]), new Map());
  elements.progressList.innerHTML = grouped.size ? [...grouped.entries()].map(([id, sets]) => {
    const exercise = EXERCISE_LIBRARY[id];
    const recent = sets.slice(-8);
    return `<article><header><div><span>${exercise?.isCore ? "CORE" : "STRENGTH"}</span><h4>${escapeHtml(exercise?.namePl || id)}</h4></div><strong>${sets.length} serii</strong></header><div class="workout-progress-series">${recent.map((set) => `<span><time>${escapeHtml(set.date.slice(5))}</time><b>${set.actualReps != null ? `${set.actualReps} powt.` : `${Math.round(set.actualDuration || 0)} s`}</b><small>${set.dumbbellCount ? `${set.dumbbellCount} × ${set.actualWeightPerDumbbellKg} kg · ` : ""}${set.actualRir != null ? `RIR ${set.actualRir}` : ""}</small></span>`).join("")}</div></article>`;
  }).join("") : '<div class="workout-empty">Progres pojawi się po pierwszym zapisanym treningu siłowym.</div>';
}

function libraryMembership(id) {
  if (WARMUP_V1.includes(id)) return "warmup";
  if (EXERCISE_LIBRARY[id].isCore) return "core";
  if (STRENGTH_WORKOUTS.A.exerciseIds.includes(id)) return "A";
  if (STRENGTH_WORKOUTS.B.exerciseIds.includes(id)) return "B";
  return "all";
}

function renderLibrary() {
  const items = Object.values(EXERCISE_LIBRARY).filter((item) => {
    const haystack = `${item.namePl} ${item.nameEn} ${item.category} ${item.primaryMuscles.join(" ")}`.toLowerCase();
    return (!state.query || haystack.includes(state.query)) && (state.libraryFilter === "all" || libraryMembership(item.id) === state.libraryFilter || (state.libraryFilter === "A" && STRENGTH_WORKOUTS.A.exerciseIds.includes(item.id)) || (state.libraryFilter === "B" && STRENGTH_WORKOUTS.B.exerciseIds.includes(item.id)));
  });
  elements.libraryGrid.innerHTML = items.map((item) => {
    const learned = Boolean(state.tracking.techniqueReviewed[item.id]);
    const videoId = item.tutorial?.videoId;
    return `<article class="workout-library-card ${learned ? "is-learned" : ""}" data-exercise-id="${item.id}"><div class="workout-library-thumb">${videoId ? `<img src="https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg" alt="" loading="lazy">` : ""}<span>${learned ? "✓ POZNANE" : escapeHtml(libraryMembership(item.id).toUpperCase())}</span></div><div><h4>${escapeHtml(item.namePl)}</h4><small>${escapeHtml(item.nameEn)}</small><p>${escapeHtml(item.instructions[0] || "Instrukcja tekstowa dostępna.")}</p><dl><div><dt>Mięśnie</dt><dd>${escapeHtml(item.primaryMuscles.map((id) => MUSCLE_LABELS[id]).join(" · ") || "Mobilizacja")}</dd></div><div><dt>Start</dt><dd>${escapeHtml(formatDumbbellLoad(item.weightPerDumbbellKg, item.dumbbellCount))}</dd></div></dl><footer><button data-library-open="${item.id}">OBEJRZYJ / TECHNIKA</button><button data-library-learned="${item.id}">${learned ? "COFNIJ POZNANE" : "OZNACZ JAKO POZNANE"}</button></footer></div></article>`;
  }).join("");
}

function openLibraryExercise(id) {
  const item = EXERCISE_LIBRARY[id];
  if (!item) return;
  const tutorial = item.tutorial;
  elements.libraryDialogContent.innerHTML = `<header><div><span>TECHNIKA · ${escapeHtml(tutorial?.source || "tutorial")}</span><h3>${escapeHtml(item.namePl)}</h3><small>${escapeHtml(item.nameEn)}</small></div><button type="button" data-library-close>×</button></header>${tutorial?.videoId ? `<div class="workout-library-video"><iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(tutorial.videoId)}" title="${escapeHtml(tutorial.title)}" loading="lazy" allow="encrypted-media; picture-in-picture" allowfullscreen></iframe></div><a href="https://www.youtube.com/watch?v=${encodeURIComponent(tutorial.videoId)}" target="_blank" rel="noopener noreferrer">OTWÓRZ NA YOUTUBE ↗</a>` : ""}${tutorial?.appSpecificNote ? `<p class="workout-library-note">${escapeHtml(tutorial.appSpecificNote)}</p>` : ""}<div class="workout-library-dialog-grid"><section><h4>Instrukcja</h4><ol>${item.instructions.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ol></section><section><h4>Cues</h4><ul>${item.cues.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul></section><section><h4>Oddychanie</h4><p>${escapeHtml(item.breathingInstructions)}</p></section><section><h4>Najczęstsze błędy</h4><ul>${item.commonMistakes.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul></section></div>`;
  elements.libraryDialog.showModal();
}

function renderSettings() {
  elements.equipmentForm.elements.handleWeight.value = state.tracking.strengthEquipment.dumbbells.estimatedHandleWeightKg;
  const profile = loadWorkoutProfile();
  Object.entries(profile).forEach(([name, value]) => { const field = elements.profileForm.elements.namedItem(name); if (field) field.value = value; });
  elements.glossary.innerHTML = Object.entries(STRENGTH_GLOSSARY).map(([term, explanation]) => `<details><summary>${escapeHtml(term)}</summary><p>${escapeHtml(explanation)}</p></details>`).join("");
}

function renderAll() {
  renderToday();
  renderPlan();
  renderPrograms();
  renderHistory();
  renderRanking();
  renderProgress();
  renderLibrary();
  renderSettings();
}

async function loadAll() {
  elements.status.textContent = "Synchronizacja…";
  try {
    const [planResponse, historyResponse, rankingResponse, tracking] = await Promise.all([
      fetch(PLAN_ENDPOINT, { cache: "no-store" }),
      fetch(`${HISTORY_ENDPOINT}?limit=200`, { cache: "no-store" }),
      fetch(RANKING_ENDPOINT, { cache: "no-store" }).catch(() => null),
      loadFileBackedSetting({ name: "live-workout-plan", storageKey: PLAN_TRACKING_KEY, fallback: {}, normalize: normalizeTracking }),
    ]);
    if (!planResponse.ok || !historyResponse.ok) throw new Error("API Live Workout jest niedostępne");
    state.plan = await planResponse.json();
    state.history = (await historyResponse.json()).sessions || [];
    state.ranking = rankingResponse?.ok
      ? normalizeCyclingCalorieRanking((await rankingResponse.json()).days)
      : buildCyclingCalorieRanking(state.history);
    state.tracking = normalizeTracking(tracking);
    saveTracking();
    renderAll();
    elements.status.textContent = `${state.history.length} sesji · dane aktualne`;
  } catch (error) {
    state.tracking = normalizeTracking(JSON.parse(localStorage.getItem(PLAN_TRACKING_KEY) || "{}"));
    renderAll();
    elements.status.textContent = error.message;
    elements.status.dataset.state = "error";
  }
}

document.addEventListener("click", async (event) => {
  const tab = event.target.closest("[data-workout-tab]")?.dataset.workoutTab || event.target.closest("[data-workout-tab-jump]")?.dataset.workoutTabJump;
  if (tab) setTab(tab);
  const rankingMode = event.target.closest("[data-ranking-mode]")?.dataset.rankingMode;
  if (["calories", "efficiency"].includes(rankingMode)) {
    state.rankingMode = rankingMode;
    renderRanking();
    return;
  }
  const strengthButton = event.target.closest("[data-strength-start]");
  if (strengthButton) openStrengthTrainer({ workoutId: strengthButton.dataset.strengthStart, variant: strengthButton.dataset.strengthVariant, planSessionId: strengthButton.dataset.strengthPlanId || null, planDate: strengthButton.dataset.strengthPlanDate || null });
  const planSession = event.target.closest("[data-plan-session]")?.dataset.planSession;
  if (planSession) { renderPlanDetail(planSession); document.querySelectorAll("[data-plan-session]").forEach((item) => item.classList.toggle("is-selected", item.dataset.planSession === planSession)); }
  const strengthAction = event.target.closest("[data-strength-plan-action]");
  if (strengthAction) {
    const item = state.tracking.strengthSessions.find((session) => session.id === strengthAction.dataset.planSessionId);
    if (!item) return;
    if (strengthAction.dataset.strengthPlanAction === "reschedule") {
      state.rescheduleSessionId = item.id;
      elements.rescheduleDate.value = item.date;
      elements.rescheduleDialog.showModal();
    } else {
      item.status = strengthAction.dataset.strengthPlanAction;
      saveTracking(); renderAll(); renderPlanDetail(item.id);
    }
  }
  const cyclingStatusButton = event.target.closest("[data-cycling-status]");
  if (cyclingStatusButton) { state.tracking.statuses[cyclingStatusButton.dataset.cyclingDate] = cyclingStatusButton.dataset.cyclingStatus; saveTracking(); renderAll(); renderPlanDetail(`cycling-${cyclingStatusButton.dataset.cyclingDate}`); }
  const libraryOpen = event.target.closest("[data-library-open]")?.dataset.libraryOpen;
  if (libraryOpen) openLibraryExercise(libraryOpen);
  const learned = event.target.closest("[data-library-learned]")?.dataset.libraryLearned;
  if (learned) { if (state.tracking.techniqueReviewed[learned]) delete state.tracking.techniqueReviewed[learned]; else state.tracking.techniqueReviewed[learned] = new Date().toISOString(); saveTracking(); renderLibrary(); }
  if (event.target.closest("[data-library-close]")) elements.libraryDialog.close();
  const tcxButton = event.target.closest("[data-history-tcx]");
  if (tcxButton) {
    tcxButton.disabled = true;
    try {
      const response = await fetch(`${HISTORY_ENDPOINT}/${encodeURIComponent(tcxButton.dataset.historyTcx)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const session = await response.json();
      downloadTextFile(`live-workout-${localDate(session.started_at)}-${session.id}.tcx`, exportWorkoutToTCX(session), "application/vnd.garmin.tcx+xml;charset=utf-8");
    } catch (error) { elements.status.textContent = `TCX: ${error.message}`; }
    finally { tcxButton.disabled = false; }
  }
  const deleteButton = event.target.closest("[data-history-delete]");
  if (deleteButton) {
    const item = state.history.find((session) => String(session.id) === deleteButton.dataset.historyDelete);
    if (!item || !window.confirm(`Usunąć sesję „${item.title || "Live Workout"}”? Tej operacji nie można cofnąć.`)) return;
    deleteButton.disabled = true;
    try {
      const response = await fetch(`${SESSION_ENDPOINT}/${encodeURIComponent(item.id)}?confirm=delete`, { method: "DELETE" });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || `HTTP ${response.status}`);
      if (item.workout_type === "strength" && item.strength_data?.planSessionId) {
        const planSession = state.tracking.strengthSessions.find((session) => session.id === item.strength_data.planSessionId);
        if (planSession) planSession.status = "planned";
        saveTracking();
      }
      await loadAll();
    } catch (error) { elements.status.textContent = `Usuwanie: ${error.message}`; deleteButton.disabled = false; }
  }
});

elements.libraryFilters.addEventListener("click", (event) => {
  const filter = event.target.closest("[data-library-filter]")?.dataset.libraryFilter;
  if (!filter) return;
  state.libraryFilter = filter;
  elements.libraryFilters.querySelectorAll("button").forEach((button) => button.classList.toggle("is-active", button.dataset.libraryFilter === filter));
  renderLibrary();
});
elements.librarySearch.addEventListener("input", () => { state.query = elements.librarySearch.value.trim().toLowerCase(); renderLibrary(); });
elements.libraryDialog.addEventListener("click", (event) => { if (event.target === elements.libraryDialog) elements.libraryDialog.close(); });
elements.rescheduleDialog.addEventListener("close", () => {
  if (elements.rescheduleDialog.returnValue !== "save") return;
  const item = state.tracking.strengthSessions.find((session) => session.id === state.rescheduleSessionId);
  if (item && /^\d{4}-\d{2}-\d{2}$/.test(elements.rescheduleDate.value)) { item.date = elements.rescheduleDate.value; item.status = "planned"; saveTracking(); renderAll(); renderPlanDetail(item.id); }
});
elements.equipmentForm.addEventListener("submit", (event) => {
  event.preventDefault();
  state.tracking.strengthEquipment.dumbbells.estimatedHandleWeightKg = Math.max(.5, Math.min(10, Number(new FormData(elements.equipmentForm).get("handleWeight")) || 2.5));
  saveTracking();
  elements.status.textContent = "Profil sprzętu zapisany";
});
elements.profileForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(elements.profileForm);
  const ageYears = Math.max(14, Math.min(100, Number(data.get("ageYears")) || 30));
  const profile = {
    sex: data.get("sex") === "female" ? "female" : "male",
    ageYears,
    weightKg: Math.max(30, Math.min(300, Number(data.get("weightKg")) || 75)),
    maxHr: resolveMaxHr({ ageYears, maxHr: Number(data.get("maxHr")) }),
    bmrKcal: Math.max(800, Math.min(4000, Number(data.get("bmrKcal")) || 1800)),
  };
  localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
  localStorage.setItem("liveWorkout.maxHr", String(profile.maxHr));
  window.dispatchEvent(new CustomEvent("live-workout:profile-changed", { detail: profile }));
  elements.status.textContent = `Profil zapisany · HRmax ${profile.maxHr}`;
});
document.getElementById("workout-history-refresh").addEventListener("click", loadAll);
document.getElementById("workout-ranking-refresh").addEventListener("click", loadAll);
document.getElementById("workout-backup-export").addEventListener("click", async () => {
  try {
    const response = await fetch(BACKUP_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const server = await response.json();
    downloadTextFile(`cleaning-dashboard-backup-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify({ kind: "cleaning-dashboard-full-backup", schemaVersion: 1, exportedAt: new Date().toISOString(), localStorage: collectLocalStorage(), ...server }, null, 2), "application/json");
  } catch (error) { elements.status.textContent = `Backup: ${error.message}`; }
});
document.getElementById("workout-backup-import").addEventListener("click", () => document.getElementById("workout-backup-file").click());
document.getElementById("workout-backup-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
  try {
    const backup = validateFullBackup(JSON.parse(await file.text()));
    const response = await fetch("/api/live-workout/backup/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(backup) });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || `HTTP ${response.status}`);
    importLocalStorageBackup(backup);
    await loadAll();
  } catch (error) { elements.status.textContent = `Import: ${error.message}`; }
});
window.addEventListener("hashchange", () => setTab(location.hash.slice(1), false));
window.addEventListener("live-workout:history-changed", loadAll);

initStrengthTrainer();
initStrengthApp();
setTab(location.hash.slice(1) || "today", false);
loadAll();
