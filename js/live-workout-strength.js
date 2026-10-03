import { loadFileBackedSetting, saveFileBackedSetting } from "./file-settings.js";
import {
  CORE_FUNCTION_LABELS,
  DUMBBELL_LOADOUTS,
  EXERCISE_LIBRARY,
  HOME_STRENGTH_EQUIPMENT,
  MUSCLE_LABELS,
  PLAN_TRACKING_KEY,
  STRENGTH_STORAGE_KEY,
  STRENGTH_WORKOUTS,
  classifyCalibrationSet,
  cloneStrengthPlan,
  formatDumbbellLoad,
  getProgressionSuggestion,
  normalizeStrengthPlan,
  loadoutForWeight,
} from "./live-workout-strength-data.js";
import {
  STRENGTH_STATES,
  beginStrengthSession,
  createStrengthSessionState,
  currentStrengthExercise,
  finishStrengthRest,
  markCurrentSetDone,
  pauseStrengthSession,
  prepareCurrentStrengthStep,
  resumeStrengthSession,
  saveCurrentSetReview,
  skipCurrentExercise,
  startCurrentSet,
  strengthExercisePosition,
  summarizeStrengthSession,
  tickStrengthSession,
} from "./live-workout-strength-engine.js";
import { liveWorkoutRuntimeUrl } from "./live-workout-runtime-api.js";

const SESSION_ENDPOINT = liveWorkoutRuntimeUrl("session");
const STREAM_ENDPOINT = liveWorkoutRuntimeUrl("stream");
const MUTE_KEY = "liveWorkout.strengthMute.v1";
let singleton = null;

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const formatClock = (seconds) => {
  const safe = Math.max(0, Math.ceil(Number(seconds) || 0));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
};

function loadEquipment() {
  try {
    const tracking = JSON.parse(localStorage.getItem(PLAN_TRACKING_KEY) || "{}");
    return { ...HOME_STRENGTH_EQUIPMENT, ...(tracking.strengthEquipment || {}), dumbbells: { ...HOME_STRENGTH_EQUIPMENT.dumbbells, ...(tracking.strengthEquipment?.dumbbells || {}) } };
  } catch {
    return structuredClone(HOME_STRENGTH_EQUIPMENT);
  }
}

function createOverlay() {
  const overlay = document.createElement("div");
  overlay.className = "strength-focus";
  overlay.id = "strength-workout-focus";
  overlay.hidden = true;
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", "strength-focus-title");
  overlay.innerHTML = `
    <div class="strength-focus-shell">
      <header class="strength-focus-header">
        <div><span class="strength-kicker">LIVE WORKOUT · STRENGTH</span><h2 id="strength-focus-title">Trening siłowy</h2></div>
        <div class="strength-focus-statuses">
          <span class="strength-hr-chip" data-strength-hr>♥ -- BPM</span>
          <span class="strength-elapsed" data-strength-elapsed>00:00</span>
          <button type="button" data-strength-action="mute" aria-pressed="false">DŹWIĘK</button>
          <button type="button" data-strength-action="close">ZAMKNIJ ×</button>
        </div>
      </header>
      <div class="strength-focus-progress" aria-hidden="true"><i data-strength-progress></i></div>
      <main class="strength-focus-main" data-strength-main></main>
      <footer class="strength-focus-toolbar" data-strength-toolbar></footer>
      <aside class="strength-technique-drawer" data-strength-technique hidden aria-label="Technika ćwiczenia"></aside>
      <dialog class="strength-weight-dialog" data-strength-weight-dialog>
        <form method="dialog">
          <header><strong>Zmień ciężar dla aktualnej serii</strong><button value="cancel" aria-label="Zamknij">×</button></header>
          <div data-strength-weight-options></div>
          <small>Zmiana dotyczy aktualnej sesji. Program nie zmieni się automatycznie.</small>
        </form>
      </dialog>
    </div>`;
  document.body.appendChild(overlay);
  return overlay;
}

function planTargetLabel(exercise) {
  if (!exercise) return "—";
  if (exercise.executionMode === "timed-per-side") return `${exercise.durationMin}–${exercise.durationMax} s / strona`;
  if (exercise.executionMode === "timed") return `${exercise.durationMin}–${exercise.durationMax} s`;
  const range = exercise.repMin === exercise.repMax ? exercise.repMin : `${exercise.repMin}–${exercise.repMax}`;
  return `${range} powt.${exercise.executionMode === "reps-per-side" ? " / strona" : ""}`;
}

function equipmentDiagram(exercise, equipment) {
  if (!exercise?.dumbbellCount) return `<div class="strength-bodyweight-note">Bez obciążenia · ${exercise.surface === "mat" ? "przygotuj matę" : "pozycja stojąca"}</div>`;
  const loadout = loadoutForWeight(exercise.weightPerDumbbellKg, equipment);
  const plates = loadout.platesPerSide.length
    ? loadout.platesPerSide.map((weight) => `<b>${weight}</b>`).join("")
    : `<em>bez talerzy</em>`;
  const actualNote = loadout.actualWeight !== Number(exercise.weightPerDumbbellKg)
    ? `<small>Przy masie gryfu ${loadout.handleWeightKg} kg rzeczywisty ciężar: ${formatDumbbellLoad(loadout.actualWeight, exercise.dumbbellCount)}</small>`
    : "";
  return `<div class="strength-loadout">
    <span>NA KAŻDY HANTEL</span>
    <div class="strength-dumbbell-diagram"><span>${plates}</span><i>GRYF</i><span>${plates}</span></div>
    <strong>${escapeHtml(loadout.label)}</strong>${actualNote}
  </div>`;
}

function compactStrengthData(session) {
  const summary = summarizeStrengthSession(session);
  const grouped = [];
  session.sequence.filter((item) => item.section !== "warmup").forEach((item) => {
    const sets = session.executions.filter((entry) => entry.exerciseId === item.exerciseId);
    grouped.push({ exerciseId: item.exerciseId, section: item.section, plannedSets: item.plannedSets, completedSets: sets.filter((set) => !set.skipped).length, sets });
  });
  return {
    schemaVersion: session.schemaVersion,
    workoutId: session.workoutId,
    workoutLabel: session.workoutLabel,
    workoutVariant: session.variant,
    planSessionId: session.planSessionId,
    planDate: session.planDate,
    preWorkout: session.preWorkout,
    timers: session.timers,
    exercises: grouped,
    skippedExercises: session.skippedExercises,
    sessionRpe: session.sessionRpe,
    notes: session.notes,
    summary,
  };
}

async function updatePlanCompletion(session) {
  if (!session.planSessionId) return;
  const value = await loadFileBackedSetting({
    name: "live-workout-plan",
    storageKey: PLAN_TRACKING_KEY,
    fallback: {},
    normalize: (item) => item && typeof item === "object" ? item : {},
  });
  const summary = summarizeStrengthSession(session);
  const strengthSessions = normalizeStrengthPlan(value.strengthSessions || cloneStrengthPlan()).map((item) => item.id === session.planSessionId
    ? { ...item, status: summary.partial ? "partial" : "completed" }
    : item);
  saveFileBackedSetting({ name: "live-workout-plan", storageKey: PLAN_TRACKING_KEY, value: { ...value, strengthSessions } });
}

export function initStrengthTrainer() {
  if (singleton || typeof document === "undefined") return singleton;
  const overlay = document.getElementById("strength-workout-focus") || createOverlay();
  const main = overlay.querySelector("[data-strength-main]");
  const toolbar = overlay.querySelector("[data-strength-toolbar]");
  const technique = overlay.querySelector("[data-strength-technique]");
  const weightDialog = overlay.querySelector("[data-strength-weight-dialog]");
  const weightOptions = overlay.querySelector("[data-strength-weight-options]");
  const title = overlay.querySelector("#strength-focus-title");
  const hr = overlay.querySelector("[data-strength-hr]");
  const elapsed = overlay.querySelector("[data-strength-elapsed]");
  const progress = overlay.querySelector("[data-strength-progress]");
  let equipment = loadEquipment();
  let session = null;
  let heartRate = null;
  let heartRateAt = 0;
  let muted = localStorage.getItem(MUTE_KEY) === "1";
  let lastTick = performance.now();
  let persistAt = 0;
  let context = { sleep: null, cycling: null };
  let previousByExercise = new Map();
  let actualWeightOverride = null;
  let checkpointInFlight = false;
  let lastCheckpointAt = 0;
  let pendingStartRequestId = null;

  function persist() {
    if (!session || [STRENGTH_STATES.SESSION_COMPLETE].includes(session.state)) localStorage.removeItem(STRENGTH_STORAGE_KEY);
    else localStorage.setItem(STRENGTH_STORAGE_KEY, JSON.stringify(session));
    checkpoint();
  }

  async function checkpoint({ keepalive = false, force = false } = {}) {
    if (!session?.serverSessionId || checkpointInFlight || (!force && Date.now() - lastCheckpointAt < 2000)) return;
    checkpointInFlight = true;
    lastCheckpointAt = Date.now();
    try {
      const response = await fetch(SESSION_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "checkpoint",
          session_id: session.serverSessionId,
          timestamp: Date.now(),
          elapsed_seconds: session.timers.totalElapsed,
          strength_data: compactStrengthData(session),
          runtime_state: session,
        }),
        keepalive,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch {
      lastCheckpointAt = 0;
    } finally {
      checkpointInFlight = false;
    }
  }

  function beep() {
    if (muted) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      const audio = new AudioContext();
      const oscillator = audio.createOscillator();
      const gain = audio.createGain();
      oscillator.frequency.value = 660;
      gain.gain.setValueAtTime(.04, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(.001, audio.currentTime + .22);
      oscillator.connect(gain).connect(audio.destination);
      oscillator.start();
      oscillator.stop(audio.currentTime + .22);
    } catch {}
  }

  async function api(action, extra = {}) {
    const sessionId = action === "start" ? null : session?.serverSessionId;
    if (action === "start" && !pendingStartRequestId) {
      pendingStartRequestId = globalThis.crypto?.randomUUID?.() || `strength-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    const response = await fetch(SESSION_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, request_id: action === "start" ? pendingStartRequestId : undefined, session_id: sessionId || undefined, timestamp: Date.now(), ...extra }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    if (action === "start") pendingStartRequestId = null;
    return payload.session;
  }

  async function loadContext() {
    try {
      const [healthResponse, planResponse, historyResponse] = await Promise.all([
        fetch("/api/health-connect/latest", { cache: "no-store" }),
        fetch(liveWorkoutRuntimeUrl("plan"), { cache: "no-store" }),
        fetch(`${liveWorkoutRuntimeUrl("history")}?limit=200`, { cache: "no-store" }),
      ]);
      const [health, plan, history] = await Promise.all([healthResponse.json().catch(() => ({})), planResponse.json().catch(() => ({})), historyResponse.json().catch(() => ({}))]);
      const sleepSessions = health?.snapshot?.payload?.sleep?.sessions || [];
      const sleepMs = sleepSessions.reduce((sum, item) => sum + Math.max(0, new Date(item.end).getTime() - new Date(item.start).getTime()), 0);
      context.sleep = sleepMs > 0 ? { minutes: Math.round(sleepMs / 60000), source: health?.snapshot?.payload?.source || "Health Connect" } : null;
      const today = session?.planDate || new Date().toLocaleDateString("sv-SE");
      context.cycling = plan?.schedule?.find((item) => item.date === today) || null;
      previousByExercise = new Map();
      (history?.sessions || []).filter((item) => item.status === "finished" && item.workout_type === "strength").forEach((item) => {
        (item.strength_data?.exercises || []).forEach((entry) => {
          if (!previousByExercise.has(entry.exerciseId) && entry.sets?.length) {
            previousByExercise.set(entry.exerciseId, { date: Number(item.started_at), sets: entry.sets.filter((set) => !set.skipped) });
          }
        });
      });
    } catch {}
    render();
  }

  async function hydrateFromRuntime() {
    try {
      const response = await fetch(SESSION_ENDPOINT, { cache: "no-store" });
      if (!response.ok) return;
      const remote = (await response.json())?.session;
      const remoteState = remote?.workout_type === "strength" ? remote.runtime_state : null;
      if (!remoteState || remoteState.schemaVersion !== 1) return;
      if (!session?.serverSessionId || Number(remoteState.updatedAt || 0) >= Number(session.updatedAt || 0)) {
        session = { ...remoteState, serverSessionId: remote.id };
        persist();
        render();
      }
    } catch {}
  }

  function renderTechnique(exercise) {
    if (!exercise) return;
    const tutorial = exercise.tutorial;
    const muscles = [...exercise.primaryMuscles, ...exercise.secondaryMuscles].map((id) => MUSCLE_LABELS[id] || id).join(" · ");
    technique.innerHTML = `
      <header><div><span>TECHNIKA · ${escapeHtml(tutorial?.tutorialMatch || "tekst")}</span><h3>${escapeHtml(exercise.namePl)}</h3><small>${escapeHtml(exercise.nameEn)}</small></div><button type="button" data-strength-action="close-technique">×</button></header>
      ${tutorial?.videoId ? `<div class="strength-video"><iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(tutorial.videoId)}" title="${escapeHtml(tutorial.title)}" loading="lazy" allow="encrypted-media; picture-in-picture" allowfullscreen></iframe></div><a href="https://www.youtube.com/watch?v=${encodeURIComponent(tutorial.videoId)}" target="_blank" rel="noopener noreferrer">OTWÓRZ NA YOUTUBE ↗</a>` : `<div class="strength-video-fallback">Film jest obecnie niedostępny. Instrukcja tekstowa pozostaje dostępna.</div>`}
      ${tutorial?.appSpecificNote ? `<p class="strength-app-note">${escapeHtml(tutorial.appSpecificNote)}</p>` : ""}
      <section><h4>Instrukcja</h4><ol>${exercise.instructions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></section>
      <section><h4>Oddychanie</h4><p>${escapeHtml(exercise.breathingInstructions)}</p></section>
      <section><h4>Najczęstsze błędy</h4><ul>${exercise.commonMistakes.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>
      <section class="strength-technique-facts"><span><b>Tempo</b>${escapeHtml(exercise.tempo || "kontrolowane")}</span><span><b>Mięśnie</b>${escapeHtml(muscles || "mobilizacja / rozgrzewka")}</span>${exercise.coreFunction.length ? `<span><b>Funkcja core</b>${exercise.coreFunction.map((id) => CORE_FUNCTION_LABELS[id]).join(" · ")}</span>` : ""}</section>`;
  }

  function renderPreWorkout() {
    const workout = STRENGTH_WORKOUTS[session.workoutId];
    const sleep = context.sleep ? `${Math.floor(context.sleep.minutes / 60)} h ${context.sleep.minutes % 60} min · ${context.sleep.source}` : "Brak aktualnych danych";
    const cycling = context.cycling ? `${context.cycling.type} · ${context.cycling.duration} min` : "Brak sesji cycling";
    const cyclingHeavy = ["tempo", "intervals", "long"].includes(context.cycling?.type);
    main.innerHTML = `<section class="strength-preworkout">
      <div class="strength-preworkout-copy"><span class="strength-kicker">DZISIAJ</span><h3>${workout.label}${session.variant === "LIGHT" ? " · LIGHT" : ""}</h3><p>${workout.estimatedDurationMin}–${workout.estimatedDurationMax} min · rozgrzewka 6–7 min · FBW + core</p></div>
      <div class="strength-context-grid"><article><span>CYCLING</span><strong>${escapeHtml(cycling)}</strong></article><article><span>SEN</span><strong>${escapeHtml(sleep)}</strong></article></div>
      <form class="strength-check" data-strength-check>
        <fieldset><legend>Nogi</legend><label><input type="radio" name="legs" value="fresh" checked> świeże</label><label><input type="radio" name="legs" value="slightly_tired"> lekko zmęczone</label><label><input type="radio" name="legs" value="very_tired"> mocno zmęczone</label></fieldset>
        <label>Energia <select name="energy">${[1,2,3,4,5].map((value) => `<option ${value === 3 ? "selected" : ""}>${value}</option>`).join("")}</select></label>
        <div class="strength-recovery-suggestion" data-strength-recovery-suggestion ${cyclingHeavy ? "" : "hidden"}>${cyclingHeavy ? "Plan cycling na dziś jest wymagający." : "Mocno zmęczone nogi:"} Zmniejszyć dzisiejszą objętość nóg o jedną serię? <label><input type="checkbox" name="reducedLegVolume" checked> Tak, zastosuj</label></div>
      </form>
      <button class="strength-primary" type="button" data-strength-action="begin">ROZPOCZNIJ ROZGRZEWKĘ</button>
    </section>`;
    toolbar.innerHTML = `<span>Plan nie zmieni się bez Twojego potwierdzenia.</span>`;
  }

  function metricTiles(exercise) {
    const previous = previousByExercise.get(exercise.exerciseId);
    const previousSets = previous?.sets || [];
    const previousLabel = previousSets.length
      ? previousSets.map((set) => set.actualReps != null ? `${set.actualReps} powt. / RIR ${set.actualRir ?? "—"}` : `${Math.round(set.actualDuration || 0)} s`).join(" · ")
      : "Pierwsze wykonanie — ciężar jest punktem startowym";
    const suggestion = getProgressionSuggestion(exercise, previousSets);
    return `<div class="strength-targets">
      <article><span>CEL</span><strong>${escapeHtml(planTargetLabel(exercise))}</strong></article>
      <article><span>CIĘŻAR</span><strong>${escapeHtml(formatDumbbellLoad(actualWeightOverride ?? exercise.weightPerDumbbellKg, exercise.dumbbellCount))}</strong></article>
      <article><span>RIR</span><strong>${escapeHtml(exercise.rirTarget || "—")}</strong></article>
      <article><span>TEMPO</span><strong>${escapeHtml(exercise.tempo || "kontrolowane")}</strong></article>
    </div><div class="strength-last-performance"><span>OSTATNIO</span><strong>${escapeHtml(previousLabel)}</strong>${suggestion ? `<small>${escapeHtml(suggestion.label)} Bez automatycznej zmiany.</small>` : ""}</div>`;
  }

  function renderExerciseBase(exercise, body) {
    const position = strengthExercisePosition(session);
    const isWarmup = exercise.section === "warmup";
    const next = session.sequence[session.exerciseIndex + 1];
    main.innerHTML = `<section class="strength-active-card" data-section="${exercise.section}">
      <header><div><span>${isWarmup ? `ROZGRZEWKA ${position.current}/${position.total}` : `ĆWICZENIE ${position.current}/${position.total}`}</span><h3>${escapeHtml(exercise.namePl)}</h3><small>${escapeHtml(exercise.nameEn)}</small></div><b>SERIA ${session.setIndex + 1}/${exercise.plannedSets}</b></header>
      ${metricTiles(exercise)}
      <div class="strength-cues">${exercise.cues.slice(0, 3).map((cue) => `<strong>${escapeHtml(cue)}</strong>`).join("")}</div>
      ${body}
      <div class="strength-next">NASTĘPNE: <strong>${escapeHtml(next?.namePl || "Podsumowanie treningu")}</strong></div>
    </section>`;
  }

  function renderSession() {
    const exercise = currentStrengthExercise(session);
    if (!exercise) return;
    const timed = exercise.executionMode.startsWith("timed");
    if (session.state === STRENGTH_STATES.EQUIPMENT_TRANSITION) {
      const matCopy = exercise.surface === "mat" ? `<span class="strength-mat-cue">PRZYGOTUJ / ZOSTAW ROZŁOŻONĄ MATĘ</span>` : "";
      renderExerciseBase(exercise, `<div class="strength-transition"><span>PRZYGOTUJ</span><h4>${escapeHtml(formatDumbbellLoad(exercise.weightPerDumbbellKg, exercise.dumbbellCount))}</h4>${matCopy}${equipmentDiagram(exercise, equipment)}<button class="strength-primary" type="button" data-strength-action="equipment-ready">GOTOWY — ZACZYNAM</button></div>`);
      return;
    }
    if ([STRENGTH_STATES.SET_READY, STRENGTH_STATES.WARMUP_INTRO].includes(session.state)) {
      renderExerciseBase(exercise, `<div class="strength-set-ready"><p>${escapeHtml(exercise.instructions[0] || "Przygotuj stabilną pozycję.")}</p><button class="strength-primary" type="button" data-strength-action="start-set">${timed ? "START ODLICZANIA" : "START SERII"}</button></div>`);
      return;
    }
    if ([STRENGTH_STATES.SET_ACTIVE, STRENGTH_STATES.WARMUP_ACTIVE].includes(session.state)) {
      const activeBody = timed
        ? `<div class="strength-countdown"><span>${session.side ? `STRONA ${session.side === "left" ? "LEWA" : "PRAWA"}` : "UTRZYMAJ POZYCJĘ"}</span><time>${formatClock(session.countdownRemaining)}</time><small>Przerwij wcześniej, jeśli tracisz poprawną pozycję.</small><button type="button" data-strength-action="set-done">ZAKOŃCZ WCZEŚNIEJ</button></div>`
        : `<div class="strength-rep-active"><span>WYKONAJ SERIĘ</span><strong>${escapeHtml(planTargetLabel(exercise))}</strong><time>${formatClock(session.setElapsed)}</time><button class="strength-primary" type="button" data-strength-action="set-done">SERIA ZAKOŃCZONA</button></div>`;
      renderExerciseBase(exercise, activeBody);
      return;
    }
    if (session.state === STRENGTH_STATES.SIDE_TRANSITION) {
      renderExerciseBase(exercise, `<div class="strength-transition"><span>ZMIANA STRONY</span><h4>Teraz strona prawa</h4><p>Ustaw pozycję ponownie. Odliczanie nie rozpocznie się bez Ciebie.</p><button class="strength-primary" type="button" data-strength-action="start-set">GOTOWY — START</button></div>`);
      return;
    }
    if (session.state === STRENGTH_STATES.SET_REVIEW) {
      renderExerciseBase(exercise, `<form class="strength-review" data-strength-review>
        <div><label>${timed ? "Wykonano sekund łącznie" : "Ile powtórzeń?"}<input name="actual" type="number" min="0" max="999" value="${timed ? Math.round(Number(session.completedSideDuration || 0) + Number(session.setElapsed || 0)) : exercise.repMin}" required></label>
        ${timed || exercise.section === "warmup" ? "" : `<label>RIR<select name="rir">${[0,1,2,3,4,5].map((value) => `<option value="${value}" ${String(exercise.rirTarget || "").startsWith(String(value)) ? "selected" : ""}>${value === 5 ? "5+" : value}</option>`).join("")}</select></label>`}
        ${exercise.dumbbellCount ? `<label>kg / hantel<select name="weight">${Object.keys(DUMBBELL_LOADOUTS).map((value) => `<option value="${value}" ${Number(value) === Number(actualWeightOverride ?? exercise.weightPerDumbbellKg) ? "selected" : ""}>${value} kg</option>`).join("")}</select></label>` : ""}</div>
        <label class="strength-technique-check"><input type="checkbox" name="techniqueAccepted" checked> Technika była pod kontrolą</label>
        <button class="strength-primary" type="submit">ZAPISZ SERIĘ</button>
      </form>`);
      return;
    }
    if (session.state === STRENGTH_STATES.REST) {
      renderExerciseBase(exercise, `<div class="strength-rest"><span>ODPOCZYNEK</span><time>${formatClock(session.restRemaining)}</time><p>Następna: ${escapeHtml(exercise.namePl)} · seria ${session.setIndex + 1}/${exercise.plannedSets} · ${escapeHtml(planTargetLabel(exercise))}</p><div><button type="button" data-strength-action="rest-ready">GOTOWY WCZEŚNIEJ</button><button type="button" data-strength-action="rest-add">+30 S</button></div></div>`);
    }
  }

  function renderSummary() {
    const summary = summarizeStrengthSession(session);
    if (session.state === STRENGTH_STATES.SESSION_REVIEW) {
      main.innerHTML = `<section class="strength-summary"><span class="strength-kicker">PODSUMOWANIE</span><h3>${escapeHtml(session.workoutLabel)}</h3>
        <div class="strength-summary-grid"><article><strong>${summary.completedExercises}/${summary.plannedExercises}</strong><span>ćwiczenia</span></article><article><strong>${summary.completedSets}/${summary.plannedSets}</strong><span>serie</span></article><article><strong>${summary.totalReps}</strong><span>powtórzenia</span></article><article><strong>${formatClock(summary.timers.totalElapsed)}</strong><span>czas łączny</span></article><article><strong>${formatClock(summary.timers.restTime)}</strong><span>odpoczynek</span></article><article><strong>${formatClock(summary.timers.equipmentTransitionTime)}</strong><span>setup</span></article></div>
        <form data-strength-summary-form><label>SESSION RPE 1–10<input name="sessionRpe" type="range" min="1" max="10" value="6"><output>6</output></label><label>Notatka<textarea name="notes" rows="3" placeholder="DOMS, technika, samopoczucie…"></textarea></label><div><button class="strength-primary" type="submit">ZAPISZ TRENING</button></div></form>
      </section>`;
      toolbar.innerHTML = `<button type="button" data-strength-action="technique">OSTATNIA TECHNIKA</button><span>Dane serii są gotowe do zapisania.</span>`;
      return;
    }
    main.innerHTML = `<section class="strength-summary is-complete"><span class="strength-kicker">TRENING ZAPISANY</span><h3>${escapeHtml(session.workoutLabel)}</h3><p>${summary.partial ? "Sesja częściowa — pominięcia zostały zachowane." : "Wszystkie zaplanowane serie zostały zapisane."}</p><div class="strength-summary-grid"><article><strong>${summary.completedSets}</strong><span>serie</span></article><article><strong>${summary.totalReps}</strong><span>powtórzenia</span></article><article><strong>${formatClock(summary.timers.totalElapsed)}</strong><span>czas</span></article><article><strong>${summary.averageRir == null ? "—" : summary.averageRir.toFixed(1)}</strong><span>średni RIR</span></article></div><a class="strength-primary" href="./live-workout.html#history">OTWÓRZ HISTORIĘ</a></section>`;
    toolbar.innerHTML = `<button type="button" data-strength-action="close">ZAMKNIJ</button>`;
  }

  function renderToolbar(exercise) {
    if ([STRENGTH_STATES.PRE_WORKOUT, STRENGTH_STATES.SESSION_REVIEW, STRENGTH_STATES.SESSION_COMPLETE].includes(session.state)) return;
    if (session.state === STRENGTH_STATES.PAUSED) {
      toolbar.innerHTML = `<strong>PAUZA · wszystkie liczniki zatrzymane</strong><button class="strength-primary" type="button" data-strength-action="resume">WZNÓW</button><button type="button" data-strength-action="finish-early">ZAKOŃCZ TRENING</button>`;
      return;
    }
    toolbar.innerHTML = `<button type="button" data-strength-action="technique">TECHNIKA</button>${exercise?.dumbbellCount ? `<button type="button" data-strength-action="change-weight">ZMIEŃ CIĘŻAR</button>` : ""}<button type="button" data-strength-action="pause">PAUZA</button><button type="button" data-strength-action="skip-set">POMIŃ SERIĘ</button><button type="button" data-strength-action="skip-exercise">POMIŃ ĆWICZENIE</button><button type="button" data-strength-action="finish-early">ZAKOŃCZ TRENING</button>`;
  }

  function render() {
    if (!session) return;
    const exercise = currentStrengthExercise(session);
    title.textContent = `${session.workoutLabel}${session.variant === "LIGHT" ? " · LIGHT" : ""}`;
    elapsed.textContent = formatClock(session.timers.totalElapsed);
    hr.textContent = Date.now() - heartRateAt < 5000 && heartRate ? `♥ ${heartRate} BPM` : "♥ -- BPM";
    const position = strengthExercisePosition(session);
    progress.style.width = `${session.state === STRENGTH_STATES.SESSION_COMPLETE ? 100 : session.sequence.length ? Math.max(2, session.exerciseIndex / session.sequence.length * 100) : 0}%`;
    progress.parentElement.setAttribute("aria-label", `Postęp: ${position.current} z ${position.total}`);
    if (session.state === STRENGTH_STATES.PRE_WORKOUT) renderPreWorkout();
    else if ([STRENGTH_STATES.SESSION_REVIEW, STRENGTH_STATES.SESSION_COMPLETE].includes(session.state)) renderSummary();
    else if (session.state === STRENGTH_STATES.PAUSED) {
      main.innerHTML = `<section class="strength-paused"><span>PAUZA</span><strong>${formatClock(session.timers.pausedTime)}</strong><p>${escapeHtml(exercise?.namePl || session.workoutLabel)} · stan sesji został zachowany.</p></section>`;
      renderToolbar(exercise);
    } else {
      renderSession();
      renderToolbar(exercise);
    }
    overlay.querySelector('[data-strength-action="mute"]').textContent = muted ? "WYCISZONO" : "DŹWIĘK";
    overlay.querySelector('[data-strength-action="mute"]').setAttribute("aria-pressed", String(muted));
  }

  async function begin() {
    const form = main.querySelector("[data-strength-check]");
    const data = new FormData(form);
    const legs = data.get("legs") || "fresh";
    const cyclingHeavy = ["tempo", "intervals", "long"].includes(context.cycling?.type);
    const reducedLegVolume = (legs === "very_tired" || cyclingHeavy) && data.get("reducedLegVolume") === "on";
    if (reducedLegVolume) {
      const legId = session.workoutId === "A" ? "goblet-squat" : "dumbbell-romanian-deadlift";
      session.sequence = session.sequence.map((item) => item.exerciseId === legId ? { ...item, plannedSets: 1 } : item);
    }
    session.preWorkout = { ...session.preWorkout, legs, energy: Number(data.get("energy") || 3), reducedLegVolume, sleep: context.sleep };
    const started = await api("start", {
      title: `${session.workoutLabel}${session.variant === "LIGHT" ? " · LIGHT" : ""}`,
      workout_type: "strength",
      sub_type: session.workoutId.toLowerCase(),
      plan_id: "strength-adaptation-2026-09",
      plan_date: session.planDate,
      planned_duration_minutes: STRENGTH_WORKOUTS[session.workoutId].estimatedDurationMax,
      strength_data: compactStrengthData(session),
    });
    if (started?.workout_type !== "strength") throw new Error("Inna sesja Live Workout jest już aktywna. Najpierw ją zakończ albo anuluj.");
    session = beginStrengthSession(session);
    session.serverSessionId = started.id;
    session = prepareCurrentStrengthStep(session);
    persist();
    window.dispatchEvent(new CustomEvent("live-workout:session-changed"));
    render();
  }

  async function finalize() {
    const strengthData = compactStrengthData(session);
    await api("finish", {
      elapsed_seconds: session.timers.totalElapsed,
      workout_type: "strength",
      plan_completed: !strengthData.summary.partial,
      strength_data: strengthData,
      session_rpe: session.sessionRpe,
      notes: session.notes,
    });
    session.finishedAt = Date.now();
    session.state = STRENGTH_STATES.SESSION_COMPLETE;
    await updatePlanCompletion(session);
    persist();
    window.dispatchEvent(new CustomEvent("live-workout:history-changed"));
    window.dispatchEvent(new CustomEvent("live-workout:session-changed"));
    render();
  }

  function open(options = {}) {
    let restored = null;
    try { restored = JSON.parse(localStorage.getItem(STRENGTH_STORAGE_KEY) || "null"); } catch {}
    session = restored?.schemaVersion === 1 && ![STRENGTH_STATES.SESSION_COMPLETE].includes(restored.state)
      ? restored
      : createStrengthSessionState(options);
    actualWeightOverride = null;
    equipment = loadEquipment();
    overlay.hidden = false;
    document.body.classList.add("strength-focus-open");
    render();
    hydrateFromRuntime();
    loadContext();
  }

  async function close() {
    if (session?.startedAt && ![STRENGTH_STATES.PAUSED, STRENGTH_STATES.SESSION_REVIEW, STRENGTH_STATES.SESSION_COMPLETE].includes(session.state)) {
      const paused = pauseStrengthSession(session);
      try {
        await api("pause", { elapsed_seconds: paused.timers.totalElapsed, strength_data: compactStrengthData(paused) });
        session = paused;
        persist();
        window.dispatchEvent(new CustomEvent("live-workout:session-changed"));
      } catch (error) {
        window.alert(`Nie udało się wstrzymać treningu: ${error.message}`);
        return;
      }
    }
    overlay.hidden = true;
    technique.hidden = true;
    if (session) session.tutorialOpen = false;
    document.body.classList.remove("strength-focus-open");
  }

  function openTechnique() {
    const exercise = currentStrengthExercise(session) || session?.sequence?.at(-1);
    if (!exercise) return;
    renderTechnique(exercise);
    technique.hidden = false;
    session.tutorialOpen = true;
    persist();
  }

  async function pause() {
    const paused = pauseStrengthSession(session);
    try {
      await api("pause", { elapsed_seconds: paused.timers.totalElapsed, strength_data: compactStrengthData(paused) });
      session = paused;
      persist();
      render();
      window.dispatchEvent(new CustomEvent("live-workout:session-changed"));
    } catch (error) {
      window.alert(`Nie udało się wstrzymać treningu: ${error.message}`);
    }
  }

  async function resume() {
    const resumedState = resumeStrengthSession(session);
    try {
      const resumed = await api("resume", { elapsed_seconds: resumedState.timers.totalElapsed, strength_data: compactStrengthData(resumedState) });
      session = resumedState;
      if (resumed?.id) session.serverSessionId = resumed.id;
      persist();
      render();
      window.dispatchEvent(new CustomEvent("live-workout:session-changed"));
    } catch (error) {
      window.alert(`Nie udało się wznowić treningu: ${error.message}`);
    }
  }

  async function cancel() {
    await api("cancel");
    session = null;
    persist();
    overlay.hidden = true;
    technique.hidden = true;
    document.body.classList.remove("strength-focus-open");
    window.dispatchEvent(new CustomEvent("live-workout:session-changed"));
    window.dispatchEvent(new CustomEvent("live-workout:history-changed"));
  }

  overlay.addEventListener("change", (event) => {
    if (event.target.name === "legs") main.querySelector("[data-strength-recovery-suggestion]").hidden = event.target.value !== "very_tired" && !["tempo", "intervals", "long"].includes(context.cycling?.type);
  });
  overlay.addEventListener("input", (event) => {
    if (event.target.name === "sessionRpe") event.target.nextElementSibling.value = event.target.value;
  });
  overlay.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (event.target.matches("[data-strength-review]")) {
      const data = new FormData(event.target);
      const exercise = currentStrengthExercise(session);
      const timed = exercise.executionMode.startsWith("timed");
      const reviewedSetIndex = session.setIndex;
      const actualReps = timed ? null : Number(data.get("actual"));
      const actualRir = data.get("rir");
      const actualWeight = Number(data.get("weight") || actualWeightOverride || exercise.weightPerDumbbellKg);
      session = saveCurrentSetReview(session, {
        actualReps,
        actualDuration: timed ? Number(data.get("actual")) : session.setElapsed,
        actualRir,
        actualWeightPerDumbbellKg: actualWeight,
        techniqueAccepted: data.get("techniqueAccepted") === "on",
      });
      if (!timed && exercise.section !== "warmup" && reviewedSetIndex === 0 && reviewedSetIndex + 1 < exercise.plannedSets && exercise.dumbbellCount) {
        const classification = classifyCalibrationSet({ actualRir, actualReps, repMin: exercise.repMin, targetRir: exercise.rirTarget });
        const weights = Object.keys(DUMBBELL_LOADOUTS).map(Number).sort((a, b) => a - b);
        const currentIndex = weights.indexOf(actualWeight);
        const suggested = classification === "TOO_HEAVY" ? weights[Math.max(0, currentIndex - 1)] : classification === "TOO_LIGHT" ? weights[Math.min(weights.length - 1, currentIndex + 1)] : null;
        if (suggested != null && suggested !== actualWeight) {
          const copy = classification === "TOO_HEAVY" ? `${actualWeight} kg było wyraźnie za ciężkie.` : `${actualWeight} kg było wyraźnie za lekkie.`;
          if (window.confirm(`${copy}\nNastępna seria: spróbować ${suggested} kg na hantel?`)) {
            session.sequence[session.exerciseIndex].weightPerDumbbellKg = suggested;
          }
        }
      }
      actualWeightOverride = null;
      persist();
      render();
    }
    if (event.target.matches("[data-strength-summary-form]")) {
      const data = new FormData(event.target);
      session.sessionRpe = Number(data.get("sessionRpe"));
      session.notes = String(data.get("notes") || "").trim();
      event.target.querySelector("button").disabled = true;
      try { await finalize(); } catch (error) { window.alert(`Nie udało się zapisać treningu: ${error.message}`); event.target.querySelector("button").disabled = false; }
    }
  });
  overlay.addEventListener("click", async (event) => {
    const action = event.target.closest("[data-strength-action]")?.dataset.strengthAction;
    if (!action) return;
    if (action === "close") await close();
    if (action === "mute") { muted = !muted; localStorage.setItem(MUTE_KEY, muted ? "1" : "0"); render(); }
    if (action === "begin") { event.target.disabled = true; try { await begin(); } catch (error) { window.alert(`Nie udało się rozpocząć treningu: ${error.message}`); event.target.disabled = false; } }
    if (action === "equipment-ready") { session.state = STRENGTH_STATES.SET_READY; persist(); render(); }
    if (action === "start-set") { session = startCurrentSet(session); persist(); render(); }
    if (action === "set-done") { session = markCurrentSetDone(session); persist(); render(); }
    if (action === "rest-ready") { session = finishStrengthRest(session); persist(); render(); }
    if (action === "rest-add") { session.restRemaining = Number(session.restRemaining || 0) + 30; persist(); render(); }
    if (action === "pause") await pause();
    if (action === "resume") await resume();
    if (action === "technique") openTechnique();
    if (action === "close-technique") { technique.hidden = true; session.tutorialOpen = false; persist(); }
    if (action === "skip-set") { if (window.confirm("Pominąć tę serię? Zostanie zapisana jako pominięta.")) { session = saveCurrentSetReview(session, { skipped: true, actualReps: 0, actualDuration: 0 }); persist(); render(); } }
    if (action === "skip-exercise") { if (window.confirm("Pominąć całe ćwiczenie? Pominięcie pozostanie w historii.")) { session = skipCurrentExercise(session); persist(); render(); } }
    if (action === "finish-early") { const remaining = Math.max(0, session.sequence.length - session.exerciseIndex); if (window.confirm(`Na pewno zakończyć trening? Pozostało około ${remaining} ćwiczeń.`)) { session.state = STRENGTH_STATES.SESSION_REVIEW; persist(); render(); } }
    if (action === "change-weight") {
      const exercise = currentStrengthExercise(session);
      weightOptions.innerHTML = Object.keys(DUMBBELL_LOADOUTS).map((weight) => `<button type="button" value="${weight}" data-strength-weight="${weight}">${escapeHtml(formatDumbbellLoad(Number(weight), exercise.dumbbellCount))}</button>`).join("");
      weightDialog.showModal();
    }
  });
  weightDialog.addEventListener("click", (event) => {
    const button = event.target.closest("[data-strength-weight]");
    if (!button) return;
    actualWeightOverride = Number(button.dataset.strengthWeight);
    const exercise = currentStrengthExercise(session);
    if (exercise) exercise.weightPerDumbbellKg = actualWeightOverride;
    weightDialog.close();
    persist();
    render();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || overlay.hidden || weightDialog.open) return;
    if (!technique.hidden) { technique.hidden = true; session.tutorialOpen = false; persist(); }
    else close();
  });
  window.addEventListener("pagehide", () => checkpoint({ keepalive: true, force: true }));

  if (typeof EventSource === "function") {
    const stream = new EventSource(STREAM_ENDPOINT);
    stream.addEventListener("telemetry", (event) => {
      try {
        const payload = JSON.parse(event.data);
        const value = Number(payload.heart_rate);
        if (Number.isInteger(value) && value >= 30 && value <= 240) { heartRate = value; heartRateAt = Date.now(); render(); }
      } catch {}
    });
  }

  window.setInterval(() => {
    if (!session || overlay.hidden || [STRENGTH_STATES.PRE_WORKOUT, STRENGTH_STATES.SESSION_COMPLETE].includes(session.state)) { lastTick = performance.now(); return; }
    const now = performance.now();
    const before = session.state;
    session = tickStrengthSession(session, (now - lastTick) / 1000);
    lastTick = now;
    if (before !== session.state && [STRENGTH_STATES.SET_REVIEW, STRENGTH_STATES.SIDE_TRANSITION, STRENGTH_STATES.SET_READY].includes(session.state)) beep();
    if (Date.now() - persistAt > 1000) { persistAt = Date.now(); persist(); }
    if ([STRENGTH_STATES.SET_ACTIVE, STRENGTH_STATES.WARMUP_ACTIVE, STRENGTH_STATES.REST, STRENGTH_STATES.EQUIPMENT_TRANSITION, STRENGTH_STATES.PAUSED].includes(session.state)) render();
  }, 250);

  singleton = { open, close, getSession: () => session };
  return singleton;
}

export function openStrengthTrainer(options = {}) {
  return initStrengthTrainer()?.open(options);
}
