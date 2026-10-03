import { strengthApi } from "./strength-api.js";
import {
  RIR_OPTIONS,
  STRENGTH_GROUPS,
  availableSymmetricLoads,
  buildMicroWorkout,
  calculateDumbbellLoad,
  chooseSuggestedMuscle,
  estimateMicroWorkoutMinutes,
  recoveryAdvice,
  rirLabel,
} from "./strength-model.js";
import {
  exerciseSeries,
  lineChartSvg,
  muscleMapHtml,
  recoveryGaugeSvg,
  recoveryScore,
  strengthIcon,
  weeklyBarsHtml,
  weeklySetBuckets,
} from "./strength-visuals.js";

const ACTIVE_KEY = "strength.activeMicroWorkout.v1";
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const groupLabel = (id) => STRENGTH_GROUPS.find((item) => item.id === id)?.label || id;
const formatDate = (timestamp) => new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(Number(timestamp)));
const formatTimer = (seconds) => `${String(Math.floor(Math.max(0, seconds) / 60)).padStart(2, "0")}:${String(Math.max(0, seconds) % 60).padStart(2, "0")}`;
const uniqueId = (prefix) => `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
const isTimedExercise = (exercise) => String(exercise?.executionMode || "").startsWith("seconds");
const isPerSideExercise = (exercise) => String(exercise?.executionMode || "").endsWith("-per-side");
const exerciseRange = (exercise) => `${exercise.repMin}–${exercise.repMax} ${isTimedExercise(exercise) ? "s" : "powt."}${isPerSideExercise(exercise) ? " / strona" : ""}`;
const loggedResult = (item, exercise) => `${item.reps ?? `${item.duration_seconds}s`}${isPerSideExercise(exercise) ? " / strona" : ""}`;

function perSideInstruction(exercise) {
  if (!isPerSideExercise(exercise)) return "";
  const unit = isTimedExercise(exercise) ? "czas" : "liczbę powtórzeń";
  const example = isTimedExercise(exercise)
    ? "60 s lewa + 60 s prawa = 1 seria; wpisujesz 60 s"
    : "10 powtórzeń lewa + 10 powtórzeń prawa = 1 seria; wpisujesz 10";
  return `<aside class="strength-v2-counting-note"><strong>Jak liczyć jedną serię?</strong><p><b>1 seria = lewa + prawa strona.</b> Wykonaj ten sam wynik na obu stronach, wpisz ${unit} dla jednej strony i zapisz tylko raz. Przykład: ${example}.</p></aside>`;
}

function loadActive() {
  try { return JSON.parse(localStorage.getItem(ACTIVE_KEY) || "null"); } catch { return null; }
}

export function initStrengthApp() {
  const root = document.getElementById("strength-app-root");
  if (!root || root.dataset.initialized) return null;
  root.dataset.initialized = "true";

  const state = {
    dashboard: null,
    exercises: [],
    history: [],
    equipment: [],
    screen: "dashboard",
    selectedMuscle: "abs",
    comboMuscles: [],
    active: loadActive(),
    setStarted: false,
    setStartedAt: null,
    saving: false,
    error: "",
    toast: "",
    detailExerciseId: null,
    detailChartMetric: "reps",
    progressMetric: "total",
    progressExerciseId: "standing-alternating-dumbbell-curl",
  };

  let timerHandle = null;

  function persistActive() {
    if (state.active) localStorage.setItem(ACTIVE_KEY, JSON.stringify(state.active));
    else localStorage.removeItem(ACTIVE_KEY);
  }

  function exerciseById(id) { return state.exercises.find((item) => item.id === id); }
  function activeExercise() { return exerciseById(state.active?.exerciseIds?.[state.active.exerciseIndex || 0]); }
  function recoveryFor(group) { return state.dashboard?.recovery?.find((item) => item.muscleGroup === group); }
  function historyForExercise(id) { return state.history.filter((item) => item.exercise_id === id); }

  function latestComparableSet(exercise) {
    return historyForExercise(exercise.id).find((item) => item.technique_variant_id === exercise.techniqueVariantId) || null;
  }

  function latestSessionSets(exercise) {
    const rows = historyForExercise(exercise.id).filter((item) => item.technique_variant_id === exercise.techniqueVariantId);
    if (!rows.length) return [];
    return rows.filter((item) => item.session_id === rows[0].session_id);
  }

  function previousSessionSets(exercise) {
    const rows = historyForExercise(exercise.id).filter((item) => item.technique_variant_id === (state.active?.techniqueVariantId || exercise.techniqueVariantId) && item.session_id !== state.active?.sessionId);
    if (!rows.length) return [];
    return rows.filter((item) => item.session_id === rows[0].session_id);
  }

  function progressionQuest(exercise) {
    const previous = previousSessionSets(exercise);
    const total = previous.reduce((sum, item) => sum + Number(item.reps || 0), 0);
    const quality = previous.filter((item) => item.quality);
    const atTop = quality.length >= Number(exercise.defaultSets || 1)
      && quality.every((item) => Number(item.reps || 0) >= Number(exercise.repMax || Infinity))
      && quality.every((item) => item.rir == null || (Number(item.rir) >= 1 && Number(item.rir) <= 2));
    if (atTop && exercise.equipment.some((item) => item.includes("dumbbell"))) {
      const current = Number(quality[0]?.plates_weight_kg || 0);
      const next = availableSymmetricLoads(state.equipment).find((item) => item.platesWeightKg > current);
      if (next) return { title: "LEVEL UP", text: `All quality sets reached the top range. Next: ${next.label}` };
      return { title: "LEVEL UP", text: "Add the smallest available plate increment." };
    }
    return { title: "TODAY'S QUEST", text: total ? `Beat ${total} total reps` : "Log one quality set" };
  }

  function defaultLoad(exercise) {
    const last = latestComparableSet(exercise);
    if (last) return {
      status: last.load_status, kg: last.load_kg, plates: last.plates_weight_kg,
      label: last.load_label,
    };
    if (!exercise.equipment.some((item) => item.includes("dumbbell"))) {
      return { status: "bodyweight", kg: null, plates: null, label: "Bodyweight" };
    }
    return { status: "partial", kg: null, plates: 5, label: "5 kg plates + uncalibrated hardware" };
  }

  function activeRemainingRest() {
    if (!state.active?.rest) return 0;
    if (state.active.rest.paused) return Math.max(0, Math.ceil(Number(state.active.rest.remaining || 0)));
    return Math.max(0, Math.ceil((Number(state.active.rest.endsAt) - Date.now()) / 1000));
  }

  function summaryHtml() {
    const xp = state.dashboard.xp;
    const weekSets = state.dashboard.scoreboard.reduce((sum, item) => sum + Number(item.sets || 0), 0);
    const metrics = [
      { icon: "layers", label: "THIS WEEK", value: weekSets, detail: "quality sets", tone: "green" },
      { icon: "medal", label: "RECENT PRs", value: state.dashboard.recentRecords.length, detail: "saved records", tone: "amber" },
      { icon: "dumbbell", label: "LIFETIME", value: state.dashboard.lifetimeQualitySets, detail: "quality sets", tone: "cyan" },
    ];
    return `<section class="strength-v2-summary" aria-label="Strength overview">
      <article class="strength-v2-level-card"><span class="strength-v2-metric-icon">${strengthIcon("trophy")}</span><div><span>STRENGTH LEVEL</span><strong>LEVEL ${xp.level}</strong><small>${xp.current} / ${xp.next} XP</small><i class="strength-v2-progress"><b style="width:${Math.min(100, xp.current / xp.next * 100)}%"></b></i></div></article>
      ${metrics.map((item) => `<article class="is-${item.tone}"><span class="strength-v2-metric-icon">${strengthIcon(item.icon)}</span><div><span>${item.label}</span><strong>${item.value}</strong><small>${item.detail}</small></div></article>`).join("")}
    </section>`;
  }

  function quickStartHtml() {
    const suggested = chooseSuggestedMuscle(state.dashboard.scoreboard, state.dashboard.recovery);
    const recent = state.history.map((item) => item.exercise_id);
    const preview = (minutes, muscle = suggested) => {
      const plan = buildMicroWorkout({ duration: minutes, muscleGroup: muscle, exercises: state.exercises, recentExerciseIds: recent });
      return { minutes: plan.estimatedMinutes, sets: plan.exercises.reduce((sum, item) => sum + Number(item.sets || 0), 0) };
    };
    const quickIcons = { 5: "bolt", 10: "clock", 15: "dumbbell" };
    return `<section class="strength-v2-panel strength-v2-quick">
      <header><div><span>LOW FRICTION · ONE SET COUNTS</span><h4>Szybki trening</h4><p>Wybierz okno czasowe. Plan powstaje z dostępnych ćwiczeń i faktycznej historii.</p></div><b>${strengthIcon("sparkles")} ${escapeHtml(groupLabel(suggested))} suggested</b></header>
      <div class="strength-v2-duration-grid">
        ${[5, 10, 15].map((minutes) => { const plan = preview(minutes); return `<button type="button" data-strength-quick="${minutes}"><span class="strength-v2-quick-icon">${strengthIcon(quickIcons[minutes])}</span><strong>${minutes}<small>min</small></strong><span>≈ ${plan.sets} ${plan.sets === 1 ? "set" : "sets"} · est. ${plan.minutes} min</span></button>`; }).join("")}
        <button type="button" class="is-utility" data-strength-muscle-picker><span class="strength-v2-quick-icon">${strengthIcon("body")}</span><strong>Partia</strong><span>Choose muscle</span></button>
        <button type="button" class="is-utility" data-strength-surprise><span class="strength-v2-quick-icon">${strengthIcon("sparkles")}</span><strong>Losuj</strong><span>Surprise me</span></button>
        <button type="button" class="is-utility" data-strength-freestyle><span class="strength-v2-quick-icon">${strengthIcon("infinity")}</span><strong>Dowolnie</strong><span>Freestyle</span></button>
      </div>
    </section>`;
  }

  function absPriorityHtml() {
    const score = state.dashboard.scoreboard.find((item) => item.muscle_group === "abs");
    const percentage = Math.min(100, Number(score?.sets || 0) / Math.max(1, Number(score?.target_sets || 1)) * 100);
    return `<section class="strength-v2-abs-card"><div class="strength-v2-abs-emblem">${strengthIcon("abs")}</div><div class="strength-v2-abs-copy"><span>PRIORITY MUSCLE</span><h4>ABS quick start</h4><p>${score?.sets || 0} of ${score?.target_sets || 10} weekly quality sets · ${score?.toMinimum ? `${score.toMinimum} to minimum` : "minimum complete"}</p><i class="strength-v2-progress"><b style="width:${percentage}%"></b></i></div><div class="strength-v2-abs-actions">${[5, 10, 15].map((minutes) => `<button type="button" data-strength-quick="${minutes}" data-muscle="abs"><strong>${minutes}</strong><span>min</span></button>`).join("")}</div></section>`;
  }

  function muscleCardsHtml() {
    return `<section class="strength-v2-panel strength-v2-muscle-panel"><header><div><span>QUICK TRAINING BY AREA</span><h4>Partie mięśniowe</h4><p>Status recovery jest wskazówką — każdy kafel nadal można wybrać.</p></div><button type="button" class="strength-v2-text-button" data-strength-combo>${strengthIcon("plus")} COMBO 20–25 MIN</button></header>
      <div class="strength-v2-muscles">${STRENGTH_GROUPS.map((group, index) => {
        const score = state.dashboard.scoreboard.find((item) => item.muscle_group === group.id);
        const recovery = recoveryAdvice(recoveryFor(group.id));
        const percent = Math.min(100, Number(score?.sets || 0) / Math.max(1, Number(score?.target_sets || 1)) * 100);
        return `<button type="button" data-strength-muscle="${group.id}" class="${index === 0 ? "is-priority" : ""}" style="--muscle-progress:${percent}%">
          <span class="strength-v2-muscle-icon">${strengthIcon(group.id)}</span><span class="strength-v2-muscle-name">${index === 0 ? "PRIORITY · " : ""}${group.label}</span><strong>${score?.sets || 0}<small> / ${score?.target_sets || 8}</small></strong><span class="strength-v2-status is-${recovery.status}"><i></i>${recovery.label}</span><i class="strength-v2-muscle-progress"><b></b></i>
        </button>`;
      }).join("")}</div></section>`;
  }

  function scoreboardHtml() {
    const buckets = weeklySetBuckets(state.history);
    const current = buckets.at(-1)?.sets || 0;
    const previous = buckets.at(-2)?.sets || 0;
    const comparison = previous > 0 ? `${current >= previous ? "+" : ""}${current - previous} vs previous week` : "Previous-week comparison appears after real sets";
    return `<section class="strength-v2-panel strength-v2-scoreboard-panel"><header><div><span>PRIMARY MUSCLE VOLUME</span><h4>Weekly scoreboard</h4><p>Tydzień od ${escapeHtml(state.dashboard.week)} · warm-up nie jest liczony.</p></div><div class="strength-v2-score-summary"><strong>${current}</strong><span>quality sets</span><small>${comparison}</small></div></header>
      <div class="strength-v2-scoreboard">${state.dashboard.scoreboard.map((item) => `<article>
        <div><strong>${escapeHtml(item.label)}</strong><span><b>${item.sets}</b> / ${item.target_sets} sets</span></div>
        <i class="strength-v2-volume-track" style="--fill:${Math.min(100, Number(item.sets) / Math.max(1, Number(item.maximum_sets)) * 100)}%;--minimum:${Number(item.minimum_sets) / Math.max(1, Number(item.maximum_sets)) * 100}%;--target:${Number(item.target_sets) / Math.max(1, Number(item.maximum_sets)) * 100}%"><b class="${item.sets >= item.minimum_sets ? "has-minimum" : ""}"></b><span class="is-min"><em>MIN ${item.minimum_sets}</em></span><span class="is-target"><em>TARGET ${item.target_sets}</em></span></i>
        <small>${item.toMinimum ? `${item.toMinimum} do minimum` : item.toTarget ? `${item.toTarget} do targetu` : "Target osiągnięty · bonus XP jest ograniczony"}</small>
      </article>`).join("")}</div></section>`;
  }

  function progressHtml() {
    const exercise = exerciseById(state.progressExerciseId) || state.exercises[0];
    const metricLabels = { total: "Total reps / time", max: "Best set", weight: "Exact weight", volume: "Exact volume", sets: "Quality sets" };
    const points = exerciseSeries(state.history, exercise?.id, state.progressMetric);
    const suffix = state.progressMetric === "weight" ? " kg" : state.progressMetric === "volume" ? " kg·rep" : "";
    const buckets = weeklySetBuckets(state.history);
    const previous = buckets.at(-2)?.sets || 0;
    const current = buckets.at(-1)?.sets || 0;
    return `<section class="strength-v2-panel strength-v2-progress-panel"><header><div><span>REAL TRAINING HISTORY</span><h4>Progress</h4><p>Każdy punkt pochodzi z zapisanej sesji; brak dokładnego ciężaru pozostaje brakiem danych.</p></div><div class="strength-v2-chart-controls"><label>Exercise<select data-strength-progress-exercise>${state.exercises.map((item) => `<option value="${item.id}" ${item.id === exercise?.id ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select></label><label>Metric<select data-strength-progress-metric>${Object.entries(metricLabels).map(([value, label]) => `<option value="${value}" ${value === state.progressMetric ? "selected" : ""}>${label}</option>`).join("")}</select></label></div></header><div class="strength-v2-progress-grid"><div><div class="strength-v2-chart-title"><strong>${escapeHtml(exercise?.name || "Exercise")}</strong><span>${escapeHtml(metricLabels[state.progressMetric])}</span></div>${lineChartSvg(points, { label: `${exercise?.name || "Exercise"}: ${metricLabels[state.progressMetric]}`, suffix })}</div><aside><span>LAST 4 WEEKS</span><strong>Weekly sets</strong>${weeklyBarsHtml(buckets)}<p>${previous > 0 ? `${current >= previous ? "+" : ""}${current - previous} jakościowych serii vs poprzedni tydzień.` : "Porównanie pojawi się, gdy poprzedni tydzień zawiera zapisane serie."}</p></aside></div></section>`;
  }

  function sidePanelsHtml() {
    const quest = state.dashboard.quest;
    const records = state.dashboard.recentRecords;
    const readiness = recoveryScore(state.dashboard.recovery);
    const equipmentSummary = state.equipment.filter((item) => Number(item.quantity) > 0).slice(0, 4);
    const achievementCopy = {
      "first-set": "Zapisz pierwszą jakościową serię.", "first-micro": "Ukończ pierwszy mikrotrening.", "abs-start": "Rozpocznij pracę nad priorytetem ABS.",
      "rep-hunter": "Pobij rekord powtórzeń.", "level-up": "Odblokuj kolejny poziom obciążenia.", consistency: "Buduj objętość w różnych tygodniach.", "100-sets": "Zapisz 100 jakościowych serii.",
    };
    return `<div class="strength-v2-side-grid">
      <section class="strength-v2-panel strength-v2-map-panel"><header><div><span>PRIORITY MUSCLE MAP</span><h4>Weekly focus</h4></div><span class="strength-v2-map-view">FRONT / BACK</span></header>${muscleMapHtml(state.dashboard.scoreboard, state.dashboard.recovery, quest.muscleGroup)}<div class="strength-v2-map-legend"><span class="is-green">Ready</span><span class="is-yellow">Recent</span><span class="is-red">Fatigue</span><span class="is-purple">Selected</span></div></section>
      <section class="strength-v2-panel strength-v2-recovery-panel"><span>RECOVERY HEURISTIC</span><h4>Gotowość</h4>${recoveryGaugeSvg(readiness)}<div class="strength-v2-recovery">${state.dashboard.recovery.map((item) => `<button type="button" data-strength-muscle="${item.muscleGroup}"><i class="is-${item.status}"></i><span>${escapeHtml(item.label)}</span><small>${recoveryAdvice(item).label}${item.sets24h ? ` · ${item.sets24h} sets / 24h` : ""}</small></button>`).join("")}</div><small class="strength-v2-heuristic-note">Heurystyka z ostatnich serii, RIR i soreness. Nie jest diagnozą i nigdy nie blokuje wyboru.</small></section>
      <section class="strength-v2-panel strength-v2-quest"><div class="strength-v2-quest-icon">${strengthIcon("target")}</div><span>CURRENT QUEST</span><h4>${escapeHtml(quest.title)}</h4><p>${escapeHtml(quest.description)}</p><button type="button" data-strength-exercise="${escapeHtml(quest.exerciseId)}">START QUEST ${strengthIcon("bolt")}</button></section>
      <section class="strength-v2-panel strength-v2-achievement-panel"><header><div><span>ACHIEVEMENTS · NO STREAKS</span><h4>Osiągnięcia</h4></div><b>${state.dashboard.achievements.filter((item) => item.unlocked).length} / ${state.dashboard.achievements.length}</b></header><div class="strength-v2-achievements">${state.dashboard.achievements.map((item) => `<article class="${item.unlocked ? "is-unlocked" : ""}"><span>${strengthIcon(item.unlocked ? "medal" : "shield")}</span><div><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(achievementCopy[item.id] || "Achievement")}</small>${item.id === "100-sets" ? `<i class="strength-v2-progress"><b style="width:${Math.min(100, state.dashboard.lifetimeQualitySets)}%"></b></i>` : ""}</div></article>`).join("")}</div></section>
      <section class="strength-v2-panel strength-v2-equipment-card"><div class="strength-v2-equipment-icon">${strengthIcon("dumbbell")}</div><span>EQUIPMENT STATUS</span><h4>Adjustable dumbbells</h4><p>${state.dashboard.equipmentCalibrated ? "Sprzęt skalibrowany — dokładna masa jest dostępna." : "Nie skalibrowano hardware. Talerze zapisujemy bez zgadywania masy gryfu i zacisków."}</p><div class="strength-v2-equipment-chips">${equipmentSummary.map((item) => `<span>${item.quantity} × ${escapeHtml(item.name)}</span>`).join("")}</div><button type="button" data-strength-equipment>${strengthIcon("gear")} ${state.dashboard.equipmentCalibrated ? "OPEN LOAD BUILDER" : "WEIGH EQUIPMENT"}</button></section>
      <section class="strength-v2-panel strength-v2-pr-panel"><header><div><span>RECENT PRs</span><h4>Ostatnie rekordy</h4></div>${strengthIcon("trophy")}</header>${records.length ? `<div class="strength-v2-records">${records.map((item) => `<article><span>${strengthIcon("medal")}</span><div><strong>${escapeHtml(item.exercise_name)}</strong><small>${escapeHtml(item.record_type.replaceAll("_", " ").toUpperCase())}</small></div><b>${item.value}</b></article>`).join("")}</div>` : `<div class="strength-v2-empty is-compact"><span>${strengthIcon("trophy")}</span><strong>Pierwszy rekord czeka</strong><p>Zapisz porównywalną serię lepszą od poprzedniej. Niczego tu nie udajemy.</p></div>`}</section>
    </div>`;
  }

  function recentHistoryHtml() {
    const rows = state.history.slice(0, 10);
    return `<section class="strength-v2-panel"><header><div><span>INDIVIDUAL SET LOG</span><h4>Ostatnie serie</h4></div><button class="strength-v2-text-button" type="button" data-strength-history>PEŁNA HISTORIA</button></header>
      <div class="strength-v2-recent">${rows.map((item) => `<button type="button" data-strength-detail="${item.exercise_id}"><time>${formatDate(item.completed_at)}</time><strong>${escapeHtml(item.exercise_name)}</strong><span>${loggedResult(item, exerciseById(item.exercise_id))} · ${escapeHtml(item.load_label)}${item.rir != null ? ` · RIR ${item.rir}` : ""}</span></button>`).join("")}</div></section>`;
  }

  function renderDashboard() {
    root.innerHTML = `<div class="strength-v2">${state.toast ? `<div class="strength-v2-toast">${escapeHtml(state.toast)}</div>` : ""}${summaryHtml()}<div class="strength-v2-main-grid"><div class="strength-v2-primary-column">${quickStartHtml()}${absPriorityHtml()}${muscleCardsHtml()}${scoreboardHtml()}${progressHtml()}</div><aside>${sidePanelsHtml()}</aside></div>${recentHistoryHtml()}</div>`;
  }

  function exercisePickerHtml() {
    const freestyle = state.screen === "freestyle";
    const exercises = freestyle ? state.exercises : state.exercises.filter((item) => item.primaryMuscle === state.selectedMuscle);
    const recovery = recoveryAdvice(recoveryFor(state.selectedMuscle));
    return `<div class="strength-v2 strength-v2-picker">
      <button type="button" class="strength-v2-back" data-strength-dashboard>← Strength</button>
      <header><span>${freestyle ? "FREESTYLE" : escapeHtml(groupLabel(state.selectedMuscle))}</span><h3>${freestyle ? "Wybierz dowolne ćwiczenie" : "Wybierz ćwiczenie"}</h3><p>Możesz zrobić jedną serię albo dowolnie wiele. Każda zostanie zapisana osobno.</p>${!freestyle && recovery.status !== "green" ? `<div class="strength-v2-fatigue is-${recovery.status}">${recovery.label}. Ręczny wybór pozostaje dostępny.</div>` : ""}${!freestyle ? `<label class="strength-v2-soreness">Optional soreness 0–5 <select data-strength-soreness data-muscle="${state.selectedMuscle}">${[0,1,2,3,4,5].map((value) => `<option value="${value}" ${Number(recoveryFor(state.selectedMuscle)?.soreness) === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>` : ""}</header>
      <div class="strength-v2-exercise-grid">${exercises.map((exercise) => {
        const last = latestSessionSets(exercise);
        const lastText = last.length ? last.slice().reverse().map((item) => loggedResult(item, exercise)).join(" · ") : "No history";
        const load = defaultLoad(exercise);
        return `<article><span>${escapeHtml(groupLabel(exercise.primaryMuscle))} · ${escapeHtml(exercise.focus)}</span><h4>${escapeHtml(exercise.name)}</h4><p>${exerciseRange(exercise)} · rest ${Math.round(exercise.restSeconds / 60 * 10) / 10} min</p><dl><div><dt>LAST</dt><dd>${escapeHtml(lastText)}</dd></div><div><dt>LOAD</dt><dd>${escapeHtml(load.label)}</dd></div></dl><div><button type="button" data-strength-exercise="${exercise.id}">START</button><button type="button" data-strength-detail="${exercise.id}">DETAIL</button></div></article>`;
      }).join("")}</div></div>`;
  }

  function comboPickerHtml() {
    return `<div class="strength-v2 strength-v2-picker"><button type="button" class="strength-v2-back" data-strength-dashboard>← Strength</button><header><span>COMBO · 20–25 MIN</span><h3>Połącz dwie partie</h3><p>Wybierz dokładnie dwa moduły. Recovery jest wskazówką, nie blokadą.</p></header><div class="strength-v2-combo-grid">${STRENGTH_GROUPS.map((group) => {
      const selected = state.comboMuscles.includes(group.id);
      const recovery = recoveryAdvice(recoveryFor(group.id));
      return `<button type="button" data-strength-combo-muscle="${group.id}" class="${selected ? "is-selected" : ""}"><strong>${group.label}</strong><span class="is-${recovery.status}">${recovery.label}</span></button>`;
    }).join("")}</div>${state.comboMuscles.length === 2 ? `<button class="strength-v2-start-set" type="button" data-strength-combo-start>START ${escapeHtml(state.comboMuscles.map(groupLabel).join(" + "))}</button>` : `<p>Wybrano ${state.comboMuscles.length} / 2</p>`}</div>`;
  }

  function activeHeader(exercise) {
    const plan = state.active.plan || [];
    const currentIndex = Number(state.active.exerciseIndex || 0);
    const plannedSets = Number(plan[currentIndex]?.sets || exercise.defaultSets || 1);
    const completed = Number(state.active.exerciseSetCount || 0);
    return `<header class="strength-v2-active-head"><div><span>${escapeHtml(state.active.modeLabel || "FREESTYLE")} · ${escapeHtml(groupLabel(exercise.primaryMuscle))}</span><h3>${escapeHtml(exercise.name)}</h3><p>Seria ${completed + 1}${state.active.mode === "freestyle" ? "" : ` / ${plannedSets}`} · ${exerciseRange(exercise)}</p></div><div><button type="button" data-strength-pause-session>${state.active.paused ? "RESUME" : "PAUSE"}</button><button type="button" data-strength-finish>FINISH ANYTIME</button></div></header>`;
  }

  function activeLastHtml(exercise) {
    const last = previousSessionSets(exercise).slice().reverse();
    const quest = progressionQuest(exercise);
    return `<div class="strength-v2-last"><article><span>LAST TIME</span><strong>${last.length ? last.map((item) => loggedResult(item, exercise)).join(" · ") : "—"}</strong><small>${last[0]?.load_label ? escapeHtml(last[0].load_label) : "First comparable set"}</small></article><article><span>${quest.title}</span><strong>${escapeHtml(quest.text)}</strong><small>Double progression · same load + technique</small></article></div>`;
  }

  function renderRest(exercise) {
    const remaining = activeRemainingRest();
    if (remaining <= 0 && !state.active.rest.paused) state.active.rest.done = true;
    root.innerHTML = `<div class="strength-v2 strength-v2-active">${activeHeader(exercise)}${activeLastHtml(exercise)}<section class="strength-v2-rest"><span>REST TIMER</span><time>${formatTimer(remaining)}</time><p>${state.active.rest.done ? "Odpoczynek zakończony. Możesz ruszyć dalej, gdy jesteś gotowy." : `Default for this exercise: ${exercise.restSeconds}s.`}</p><div><button type="button" data-strength-rest-pause>${state.active.rest.paused ? "RESUME" : "PAUSE"}</button><button type="button" data-strength-rest-adjust="-30">−30 SEC</button><button type="button" data-strength-rest-adjust="30">+30 SEC</button><button type="button" data-strength-next-set>${state.active.rest.done ? "START NEXT SET" : "SKIP REST"}</button></div></section><p class="strength-v2-pain-note">Normalne zmęczenie/pieczenie to nie to samo co ostry ból stawu lub ścięgna. Przy nietypowym bólu zakończ ten ruch; aplikacja nie stawia diagnozy.</p></div>`;
  }

  function renderActive() {
    const exercise = activeExercise();
    if (!exercise) { state.active = null; persistActive(); state.screen = "dashboard"; render(); return; }
    if (state.active.paused) {
      root.innerHTML = `<div class="strength-v2 strength-v2-active">${activeHeader(exercise)}<section class="strength-v2-rest"><span>SESSION PAUSED</span><time>PAUSE</time><p>Stan mikrotreningu jest zachowany. Zapisane wcześniej serie pozostają w historii.</p><div><button type="button" data-strength-pause-session>RESUME</button><button type="button" data-strength-finish>FINISH ANYTIME</button></div></section></div>`;
      return;
    }
    if (state.active.rest) { renderRest(exercise); return; }
    const last = latestComparableSet(exercise);
    const load = state.active.load || defaultLoad(exercise);
    state.active.load = load;
    const resultDefault = (isTimedExercise(exercise) ? last?.duration_seconds : last?.reps) || exercise.repMin;
    root.innerHTML = `<div class="strength-v2 strength-v2-active">${state.toast ? `<div class="strength-v2-toast">${escapeHtml(state.toast)}</div>` : ""}${activeHeader(exercise)}${activeLastHtml(exercise)}
      <section class="strength-v2-set-card">
        <div class="strength-v2-set-target"><span>${state.setStarted ? "SERIA W TOKU" : "GOTOWY"}</span><strong>${exerciseRange(exercise)}</strong><small>${escapeHtml(exercise.technique)}</small></div>
        ${perSideInstruction(exercise)}
        ${!state.setStarted ? `<button class="strength-v2-start-set" type="button" data-strength-start-set>START SET</button>` : `<form data-strength-set-form>
          <div class="strength-v2-set-fields"><label>${isTimedExercise(exercise) ? (isPerSideExercise(exercise) ? "SEKUNDY NA JEDNĄ STRONĘ" : "SEKUNDY") : (isPerSideExercise(exercise) ? "POWTÓRZENIA NA JEDNĄ STRONĘ" : "POWTÓRZENIA")}<div class="strength-v2-stepper"><button type="button" data-strength-step="-1">−</button><input name="result" type="number" min="1" max="9999" value="${resultDefault}" required><button type="button" data-strength-step="1">+</button></div></label>
          <label>LOAD<input name="loadLabel" value="${escapeHtml(load.label)}" required><small>${load.status === "exact" ? "Exact calibrated load" : load.status === "partial" ? "Hardware remains unknown" : "No external load"}</small></label></div>
          <fieldset><legend>RIR / EFFORT <button type="button" data-strength-rir-info>?</button></legend><div class="strength-v2-rir">${RIR_OPTIONS.map((item) => `<label><input type="radio" name="rir" value="${item.value}"><span>${item.range}<small>${item.label}</small></span></label>`).join("")}</div><small>RIR is an estimate. Możesz zostawić puste.</small></fieldset>
          <div class="strength-v2-set-meta"><label>SET TYPE<select name="setType"><option value="quality">Quality / working</option><option value="warmup">Warm-up</option></select></label><label>STOP REASON<select name="stopReason"><option value="">Completed normally</option><option value="fatigue">Normal fatigue</option><option value="discomfort">Discomfort</option><option value="pain">Sharp / joint / tendon pain</option></select></label><label>REST SECONDS<input name="restSeconds" type="number" min="0" max="3600" step="15" value="${exercise.restSeconds}"></label><label>TECHNIQUE<select name="techniqueVariant">${exercise.techniqueVariants.map((item) => `<option value="${item.id}" ${item.id === (state.active.techniqueVariantId || exercise.techniqueVariantId) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select></label><label><input type="checkbox" name="techniqueAccepted" checked> Technique comparable</label></div>
          <button class="strength-v2-save-set" type="submit" ${state.saving ? "disabled" : ""}>${state.saving ? "SAVING…" : "SAVE SET + START REST"}</button>
        </form>`}
      </section>
      <div class="strength-v2-active-tools"><button type="button" data-strength-change-exercise>CHANGE EXERCISE</button><button type="button" data-strength-detail="${exercise.id}">EXERCISE DETAIL</button><button type="button" data-strength-equipment>LOAD BUILDER</button></div>
      <p class="strength-v2-pain-note">Ostry, stawowy, ścięgnisty lub nietypowy ból to sygnał, by zakończyć dany ruch i odpocząć albo wybrać inne ćwiczenie.</p>
    </div>`;
  }

  function historyHtml() {
    const groups = new Map();
    state.history.forEach((item) => {
      const day = new Date(Number(item.completed_at)).toLocaleDateString("sv-SE");
      const key = `${day}|${item.session_id || item.id}|${item.exercise_id}`;
      if (!groups.has(key)) groups.set(key, { day, session: item.session_id, exercise: item.exercise_name, id: item.exercise_id, load: item.load_label, technique: item.technique_name, sets: [] });
      groups.get(key).sets.push(item);
    });
    return `<div class="strength-v2 strength-v2-history"><button class="strength-v2-back" type="button" data-strength-dashboard>← Strength</button><header><span>DAY → SESSION → EXERCISE → SET</span><h3>Historia siłowa</h3><p>Każdy zapis jest liczony jako osobna seria. W ćwiczeniach „/ strona” jeden zapis oznacza wykonanie lewej i prawej strony.</p></header><div>${[...groups.values()].map((group) => `<article><time>${escapeHtml(group.day)}</time><button type="button" data-strength-detail="${group.id}">${escapeHtml(group.exercise)}</button><strong>${escapeHtml(group.load)}</strong><p>${group.sets.slice().reverse().map((item) => `${loggedResult(item, exerciseById(group.id))}${item.rir != null ? ` @ RIR${item.rir}` : ""}${item.quality ? "" : " · warm-up"}`).join(" · ")}</p><small>Technique: ${escapeHtml(group.technique)}${group.sets[0].rest_seconds != null ? ` · Rest ${group.sets[0].rest_seconds}s` : ""}</small></article>`).join("")}</div></div>`;
  }

  function equipmentHtml() {
    const loads = availableSymmetricLoads(state.equipment);
    return `<div class="strength-v2 strength-v2-equipment"><button class="strength-v2-back" type="button" data-strength-back>← Back</button><header><span>CALIBRATE EQUIPMENT</span><h3>Sprzęt i load builder</h3><p>Brak pomiaru pozostaje brakiem pomiaru — nie pokazujemy fałszywej sumy.</p></header><form data-strength-equipment-form><div class="strength-v2-equipment-grid">${state.equipment.map((item) => `<label><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.item_type)}</span><input type="hidden" name="id" value="${item.id}"><small>Quantity</small><input name="quantity:${item.id}" type="number" min="0" max="100" value="${item.quantity}"><small>${item.item_type === "plate" ? "Actual / nominal kg" : "Measured kg (leave empty if unknown)"}</small><input name="weight:${item.id}" type="number" min="0" step="0.001" value="${item.measured_weight_kg ?? (item.item_type === "plate" ? item.nominal_weight_kg ?? "" : "")}" placeholder="unknown"></label>`).join("")}</div><button type="submit">SAVE CALIBRATION</button></form>
      <section class="strength-v2-loads"><span>AVAILABLE NEXT LOADS · TWO DUMBBELLS</span><div>${loads.map((load, index) => `<article><strong>${escapeHtml(load.label)}</strong><small>LEFT: ${load.platesPerSide.length ? load.platesPerSide.join(" + ") : "no plates"}</small><small>RIGHT: ${load.platesPerSide.length ? load.platesPerSide.join(" + ") : "no plates"} · symmetric ✓</small>${state.active ? `<button type="button" data-strength-load="${index}">USE THIS LOAD</button>` : ""}</article>`).join("")}</div></section>
      <form class="strength-v2-xp-settings" data-strength-xp-form><span>XP CONFIGURATION</span><div>${Object.entries(state.dashboard.xpConfig).map(([key, value]) => `<label>${escapeHtml(key)}<input name="${escapeHtml(key)}" type="number" min="0" max="1000" value="${value}"></label>`).join("")}</div><button type="submit">SAVE XP RULES</button></form></div>`;
  }

  function detailHtml() {
    const exercise = exerciseById(state.detailExerciseId);
    if (!exercise) { state.screen = "dashboard"; render(); return; }
    const rows = historyForExercise(exercise.id).slice().reverse();
    const values = rows.map((item) => state.detailChartMetric === "reps" ? Number(isTimedExercise(exercise) ? item.duration_seconds : item.reps || 0)
      : state.detailChartMetric === "weight" ? Number(item.load_kg || 0)
        : state.detailChartMetric === "volume" ? Number(item.load_kg || 0) * Number(item.reps || 0)
          : 1);
    const max = Math.max(1, ...values);
    return `<div class="strength-v2 strength-v2-detail"><button class="strength-v2-back" type="button" data-strength-back>← Back</button><header><span>${escapeHtml(groupLabel(exercise.primaryMuscle))} · ${escapeHtml(exercise.focus)}</span><h3>${escapeHtml(exercise.name)}</h3><p>${escapeHtml(exercise.why)}</p><button type="button" data-strength-exercise="${exercise.id}">${strengthIcon("bolt")} START SET</button></header><div class="strength-v2-detail-grid"><section><span class="strength-v2-detail-icon">${strengthIcon(exercise.primaryMuscle)}</span><h4>Prescription</h4><dl><div><dt>${isTimedExercise(exercise) ? "Czas" : "Powtórzenia"}${isPerSideExercise(exercise) ? " / strona" : ""}</dt><dd>${exercise.repMin}–${exercise.repMax}${isTimedExercise(exercise) ? "s" : ""}</dd></div><div><dt>${isPerSideExercise(exercise) ? "Odpoczynek po obu stronach" : "Odpoczynek"}</dt><dd>${exercise.restSeconds}s</dd></div><div><dt>Sprzęt</dt><dd>${escapeHtml(exercise.equipment.join(", "))}</dd></div><div><dt>Mięśnie dodatkowe</dt><dd>${escapeHtml(exercise.secondaryMuscles.join(", ") || "—")}</dd></div></dl>${perSideInstruction(exercise)}<h4>Technika</h4><p>${escapeHtml(exercise.technique)}</p><h4>Dlaczego ${exerciseRange(exercise)}?</h4><p>${isTimedExercise(exercise) ? "Wybierz czas, przez który utrzymujesz stabilną pozycję bez utraty techniki. Progresuj stopniowo w podanym zakresie." : "Rozwój mięśni może zachodzić w szerokim zakresie powtórzeń, gdy serie są odpowiednio wymagające. Ten zakres ułatwia kontrolowaną progresję."}</p></section><section><div class="strength-v2-chart-head"><h4>Progress</h4><select data-strength-chart><option value="reps" ${state.detailChartMetric === "reps" ? "selected" : ""}>${isTimedExercise(exercise) ? "MAX / SET TIME" : "MAX / SET REPS"}</option><option value="weight" ${state.detailChartMetric === "weight" ? "selected" : ""}>WEIGHT</option><option value="volume" ${state.detailChartMetric === "volume" ? "selected" : ""}>ESTIMATED VOLUME</option><option value="sets" ${state.detailChartMetric === "sets" ? "selected" : ""}>QUALITY SETS</option></select></div><div class="strength-v2-chart">${values.length ? values.map((value) => `<i style="height:${Math.max(5, value / max * 100)}%" title="${value}"></i>`).join("") : `<div class="strength-v2-empty"><span>${strengthIcon("chart")}</span><strong>No comparable history yet</strong><p>Complete a set to start this chart.</p></div>`}</div><div class="strength-v2-detail-history">${rows.slice(-8).reverse().map((item) => `<div><time>${formatDate(item.completed_at)}</time><strong>${loggedResult(item, exercise)} ${item.rir != null ? `@ RIR${item.rir}` : ""}</strong><span>${escapeHtml(item.load_label)}</span></div>`).join("")}</div></section></div><aside class="strength-v2-rir-info"><strong>RIR = Repetitions In Reserve</strong><p>Szacowana liczba poprawnych technicznie powtórzeń, które prawdopodobnie zostały w zapasie. 5+ easy · 3–4 medium · 2 hard · 1 very hard · 0 failure. RIR jest szacunkiem.</p></aside></div>`;
  }

  function render() {
    clearInterval(timerHandle);
    timerHandle = null;
    if (state.error) root.innerHTML = `<div class="strength-v2-error"><strong>Strength unavailable</strong><p>${escapeHtml(state.error)}</p><button data-strength-retry>RETRY</button></div>`;
    else if (!state.dashboard) root.innerHTML = '<div class="strength-v2-loading">Ładowanie Strength…</div>';
    else if (state.active && !["picker", "freestyle", "equipment", "detail", "history"].includes(state.screen)) {
      renderActive();
      if (state.active?.rest && !state.active.rest.paused) timerHandle = setInterval(() => renderActive(), 1000);
    } else if (["picker", "freestyle"].includes(state.screen)) root.innerHTML = exercisePickerHtml();
    else if (state.screen === "combo") root.innerHTML = comboPickerHtml();
    else if (state.screen === "history") root.innerHTML = historyHtml();
    else if (state.screen === "equipment") root.innerHTML = equipmentHtml();
    else if (state.screen === "detail") root.innerHTML = detailHtml();
    else renderDashboard();
  }

  async function load() {
    state.error = "";
    render();
    try {
      const [dashboard, exercises, history, equipment] = await Promise.all([
        strengthApi.dashboard(), strengthApi.exercises(), strengthApi.history(), strengthApi.equipment(),
      ]);
      state.dashboard = dashboard;
      state.exercises = exercises.exercises || [];
      state.history = history.sets || [];
      state.equipment = equipment.items || [];
      if (!state.exercises.some((item) => item.id === state.progressExerciseId)) state.progressExerciseId = state.exercises[0]?.id || null;
      if (state.active && !state.active.exerciseIds?.some((id) => exerciseById(id))) state.active = null;
      persistActive();
    } catch (error) { state.error = error.message; }
    render();
  }

  async function begin(exerciseIds, { mode = "freestyle", duration = null, plan = null, modeLabel = null } = {}) {
    const first = exerciseById(exerciseIds[0]);
    if (!first) return;
    const recovery = recoveryAdvice(recoveryFor(first.primaryMuscle));
    if (recovery.requiresConfirmation && !window.confirm("Recently trained / elevated fatigue. Continue anyway?")) return;
    try {
      const response = await strengthApi.startSession({ mode, plannedDurationMinutes: duration, metadata: { exerciseIds } });
      state.active = {
        sessionId: response.session.id, mode, duration, modeLabel: modeLabel || mode.replaceAll("_", " ").toUpperCase(),
        exerciseIds, exerciseIndex: 0, exerciseSetCount: 0, plan: plan || [], paused: false,
      };
      state.setStarted = false; state.setStartedAt = null; state.screen = "active"; state.toast = "";
      persistActive(); render();
    } catch (error) { state.toast = error.message; render(); }
  }

  async function beginQuick(duration, muscle) {
    const chosen = muscle || chooseSuggestedMuscle(state.dashboard.scoreboard, state.dashboard.recovery);
    const recent = state.history.map((item) => item.exercise_id);
    const plan = buildMicroWorkout({ duration, muscleGroup: chosen, exercises: state.exercises, recentExerciseIds: recent });
    await begin(plan.exercises.map((item) => item.id), { mode: `${duration}_min`, duration, plan: plan.exercises, modeLabel: `${duration} MIN · EST. ${plan.estimatedMinutes} MIN` });
  }

  async function saveSet(form) {
    if (state.saving) return;
    const exercise = activeExercise();
    const data = new FormData(form);
    const load = state.active.load || defaultLoad(exercise);
    const result = Number(data.get("result"));
    state.saving = true; render();
    try {
      const response = await strengthApi.saveSet({
        id: uniqueId("set"), sessionId: state.active.sessionId, exerciseId: exercise.id,
        techniqueVariantId: String(data.get("techniqueVariant") || exercise.techniqueVariantId),
        reps: exercise.executionMode.startsWith("seconds") ? null : result,
        durationSeconds: exercise.executionMode.startsWith("seconds") ? result : Math.max(1, Math.round((Date.now() - state.setStartedAt) / 1000)),
        loadKg: load.kg, platesWeightKg: load.plates, loadLabel: String(data.get("loadLabel") || load.label), loadStatus: load.status,
        rir: data.get("rir") === null ? null : data.get("rir"), effort: data.get("rir") === null ? null : rirLabel(data.get("rir")),
        setType: data.get("setType"), stopReason: data.get("stopReason"), techniqueAccepted: data.get("techniqueAccepted") === "on",
        restSeconds: Math.max(0, Number(data.get("restSeconds")) || 0),
      });
      state.active.exerciseSetCount = Number(state.active.exerciseSetCount || 0) + 1;
      const restSeconds = Math.max(0, Number(data.get("restSeconds")) || 0);
      state.active.techniqueVariantId = String(data.get("techniqueVariant") || exercise.techniqueVariantId);
      state.active.rest = { endsAt: Date.now() + restSeconds * 1000, paused: false, remaining: restSeconds, total: restSeconds, done: restSeconds === 0 };
      state.setStarted = false; state.setStartedAt = null;
      const pr = response.records.map((item) => item.record_type.replaceAll("_", " ").toUpperCase()).join(" · ");
      state.toast = `${result}${isTimedExercise(exercise) ? " s" : " powt."}${isPerSideExercise(exercise) ? " / strona" : ""} saved · +${response.xpAwarded} XP${pr ? ` · ${pr}` : ""}`;
      if (data.get("stopReason") === "pain") state.toast = "Set saved. Zakończ ten ruch; wybierz odpoczynek lub inne ćwiczenie.";
      persistActive();
      const [dashboard, history] = await Promise.all([strengthApi.dashboard(), strengthApi.history()]);
      state.dashboard = dashboard; state.history = history.sets || [];
    } catch (error) { state.toast = `Set was not saved: ${error.message}`; }
    finally { state.saving = false; render(); }
  }

  function moveAfterRest() {
    const exercise = activeExercise();
    const planned = Number(state.active.plan?.[state.active.exerciseIndex]?.sets || exercise.defaultSets || 1);
    if (state.active.mode !== "freestyle" && state.active.exerciseSetCount >= planned && state.active.exerciseIndex + 1 < state.active.exerciseIds.length) {
      state.active.exerciseIndex += 1; state.active.exerciseSetCount = 0; state.active.load = null;
    }
    state.active.rest = null; state.setStarted = false; state.toast = ""; persistActive(); render();
  }

  async function finish() {
    try { await strengthApi.completeSession(state.active.sessionId); }
    catch (error) { state.toast = `Sets are safe, but session summary failed: ${error.message}`; render(); return; }
    state.active = null; state.setStarted = false; state.screen = "dashboard"; persistActive();
    await load();
  }

  root.addEventListener("submit", async (event) => {
    if (event.target.matches("[data-strength-set-form]")) { event.preventDefault(); await saveSet(event.target); }
    if (event.target.matches("[data-strength-equipment-form]")) {
      event.preventDefault();
      const data = new FormData(event.target);
      const items = state.equipment.map((item) => ({
        id: item.id, quantity: Number(data.get(`quantity:${item.id}`)),
        measuredWeightKg: data.get(`weight:${item.id}`) === "" ? null : Number(data.get(`weight:${item.id}`)),
        nominalWeightKg: item.nominal_weight_kg,
      }));
      try { state.equipment = (await strengthApi.saveEquipment(items)).items; state.dashboard = await strengthApi.dashboard(); state.toast = "Equipment saved"; state.screen = "dashboard"; }
      catch (error) { state.toast = error.message; }
      render();
    }
    if (event.target.matches("[data-strength-xp-form]")) {
      event.preventDefault();
      const data = new FormData(event.target);
      const xp = Object.fromEntries(Object.keys(state.dashboard.xpConfig).map((key) => [key, Number(data.get(key))]));
      try { await strengthApi.saveSettings(xp); state.dashboard = await strengthApi.dashboard(); state.toast = "XP configuration saved"; state.screen = "dashboard"; }
      catch (error) { state.toast = error.message; }
      render();
    }
  });

  root.addEventListener("change", async (event) => {
    if (event.target.matches("[data-strength-chart]")) { state.detailChartMetric = event.target.value; render(); }
    if (event.target.matches("[data-strength-progress-metric]")) { state.progressMetric = event.target.value; render(); }
    if (event.target.matches("[data-strength-progress-exercise]")) { state.progressExerciseId = event.target.value; render(); }
    if (event.target.matches("[data-strength-soreness]")) {
      try {
        await strengthApi.reportRecovery(event.target.dataset.muscle, Number(event.target.value));
        state.dashboard = await strengthApi.dashboard();
        render();
      } catch (error) { state.toast = error.message; render(); }
    }
  });

  root.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.matches("[data-strength-retry]")) { await load(); return; }
    if (button.matches("[data-strength-dashboard]")) { state.screen = "dashboard"; state.toast = ""; render(); return; }
    if (button.matches("[data-strength-back]")) { state.screen = state.active ? "active" : "dashboard"; render(); return; }
    if (button.matches("[data-strength-quick]")) { await beginQuick(Number(button.dataset.strengthQuick), button.dataset.muscle); return; }
    if (button.matches("[data-strength-surprise]")) { await beginQuick(10); return; }
    if (button.matches("[data-strength-muscle-picker]")) { state.selectedMuscle = "abs"; state.screen = "picker"; render(); return; }
    if (button.matches("[data-strength-freestyle]")) { state.screen = "freestyle"; render(); return; }
    if (button.matches("[data-strength-combo]")) { state.comboMuscles = []; state.screen = "combo"; render(); return; }
    if (button.matches("[data-strength-combo-muscle]")) {
      const muscle = button.dataset.strengthComboMuscle;
      state.comboMuscles = state.comboMuscles.includes(muscle)
        ? state.comboMuscles.filter((item) => item !== muscle)
        : state.comboMuscles.length < 2 ? [...state.comboMuscles, muscle] : [state.comboMuscles[1], muscle];
      render(); return;
    }
    if (button.matches("[data-strength-combo-start]")) {
      const plans = state.comboMuscles.flatMap((muscle) => buildMicroWorkout({ duration: 10, muscleGroup: muscle, exercises: state.exercises }).exercises);
      await begin(plans.map((item) => item.id), { mode: "combo", duration: 22, plan: plans, modeLabel: `${state.comboMuscles.map(groupLabel).join(" + ")} · EST. ${estimateMicroWorkoutMinutes(plans)} MIN` });
      return;
    }
    if (button.matches("[data-strength-muscle]")) { state.selectedMuscle = button.dataset.strengthMuscle; state.screen = "picker"; render(); return; }
    if (button.matches("[data-strength-exercise]")) {
      if (state.active) {
        state.active.exerciseIds = [button.dataset.strengthExercise]; state.active.exerciseIndex = 0;
        state.active.exerciseSetCount = 0; state.active.load = null; state.active.rest = null;
        state.active.techniqueVariantId = null; state.screen = "active"; state.setStarted = false;
        persistActive(); render();
      } else await begin([button.dataset.strengthExercise], { mode: "freestyle", modeLabel: "FREESTYLE · ONE SET IS VALID" });
      return;
    }
    if (button.matches("[data-strength-history]")) { state.screen = "history"; render(); return; }
    if (button.matches("[data-strength-equipment]")) { state.screen = "equipment"; render(); return; }
    if (button.matches("[data-strength-load]")) {
      const load = availableSymmetricLoads(state.equipment)[Number(button.dataset.strengthLoad)];
      if (state.active && load) {
        state.active.load = { status: load.exact ? "exact" : "partial", kg: load.totalWeightKg, plates: load.platesWeightKg, label: load.label };
        state.screen = "active"; persistActive(); render();
      }
      return;
    }
    if (button.matches("[data-strength-detail]")) { state.detailExerciseId = button.dataset.strengthDetail; state.screen = "detail"; render(); return; }
    if (button.matches("[data-strength-start-set]")) { state.setStarted = true; state.setStartedAt = Date.now(); state.active.paused = false; persistActive(); render(); return; }
    if (button.matches("[data-strength-step]")) { const input = root.querySelector('[name="result"]'); input.value = Math.max(1, Number(input.value) + Number(button.dataset.strengthStep)); return; }
    if (button.matches("[data-strength-rir-info]")) { window.alert("RIR = Repetitions In Reserve. To szacowana liczba poprawnych powtórzeń w zapasie: 5+ easy, 3–4 medium, 2 hard, 1 very hard, 0 failure. RIR jest szacunkiem."); return; }
    if (button.matches("[data-strength-rest-pause]")) {
      const remaining = activeRemainingRest(); state.active.rest.paused = !state.active.rest.paused;
      state.active.rest.remaining = remaining; if (!state.active.rest.paused) state.active.rest.endsAt = Date.now() + remaining * 1000;
      persistActive(); render(); return;
    }
    if (button.matches("[data-strength-rest-adjust]")) {
      const remaining = Math.max(0, activeRemainingRest() + Number(button.dataset.strengthRestAdjust));
      state.active.rest.remaining = remaining; state.active.rest.endsAt = Date.now() + remaining * 1000; state.active.rest.done = remaining === 0;
      persistActive(); render(); return;
    }
    if (button.matches("[data-strength-next-set]")) { moveAfterRest(); return; }
    if (button.matches("[data-strength-pause-session]")) { state.active.paused = !state.active.paused; persistActive(); render(); return; }
    if (button.matches("[data-strength-change-exercise]")) { state.screen = "freestyle"; render(); return; }
    if (button.matches("[data-strength-finish]")) { await finish(); }
  });

  load();
  return { reload: load, getState: () => state };
}
