function formatTime(seconds) {
  const safe = Math.max(0, Math.ceil(Number(seconds) || 0));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function formatNumber(value, digits = 0, fallback = "--") {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : fallback;
}

export function createCalibrationPanel(documentRef = document) {
  const panel = documentRef.createElement("section");
  panel.className = "live-workout-calibration";
  panel.dataset.liveCalibration = "";
  panel.hidden = true;
  panel.innerHTML = `
    <header class="live-workout-calibration-head">
      <div>
        <div class="live-workout-focus-kicker">MAGENE CSC + HR · RAMP / STEP TEST</div>
        <h3>Kalibracja rowerka stacjonarnego</h3>
        <p>Empiryczna zależność poziom oporu → tętno przy stałej kadencji. To nie jest pomiar mocy.</p>
      </div>
      <div class="live-workout-calibration-sound-controls">
        <label class="live-workout-calibration-audio"><input type="checkbox" data-cal-audio checked> komunikaty głosowe</label>
        <label class="live-workout-calibration-metronome"><input type="checkbox" data-cal-metronome> metronom</label>
        <select data-cal-metronome-mode aria-label="Rytm metronomu"><option value="1:2">Rytm 1:2 · lewa / prawa</option><option value="1:1">Rytm 1:1 · pełny obrót</option></select>
        <span class="live-workout-calibration-metronome-tempo" data-cal-metronome-tempo>160 BPM</span>
        <button type="button" data-cal-close>WRÓĆ DO LIVE WORKOUT</button>
      </div>
    </header>

    <div class="live-workout-calibration-diagnostics">
      <span data-cal-hr-status><i></i> HR: brak sygnału</span>
      <span data-cal-cadence-status><i></i> Kadencja: rozłączona</span>
      <button type="button" data-cal-reconnect>POŁĄCZ / POŁĄCZ PONOWNIE CSC</button>
    </div>
    <div class="live-workout-calibration-alert" data-cal-alert hidden role="alert"></div>

    <section class="live-workout-calibration-guide">
      <header>
        <div><strong>Jak wykonać dobrą kalibrację</strong><span>Całość trwa około 30 minut. Jedź w pozycji siedzącej i nie zmieniaj ustawienia siodełka podczas testu.</span></div>
        <b>Najważniejsze: utrzymuj zadane RPM — zmieniaj tylko poziom oporu.</b>
      </header>
      <div class="live-workout-calibration-guide-steps">
        <article><b>1</b><div><strong>Przygotuj warunki</strong><p>Ustaw wentylator i temperaturę tak, jak podczas zwykłych treningów. Przygotuj wodę. Nie rozpoczynaj testu bezpośrednio po ciężkim treningu.</p></div></article>
        <article><b>2</b><div><strong>Uruchom oba sygnały</strong><p>Włącz transmisję HR z zegarka. Połącz Magene CSC, zakręć raz korbą, aż zobaczysz RPM, a następnie całkowicie zatrzymaj pedały.</p></div></article>
        <article><b>3</b><div><strong>Baseline · 60 sekund</strong><p>Usiądź spokojnie, nie pedałuj i nie rozmawiaj. Minuta zostanie naliczona tylko wtedy, gdy korba pozostaje nieruchoma.</p></div></article>
        <article><b>4</b><div><strong>Rozgrzewka · poziom 1</strong><p>Jedź 3–5 minut przy 70–80 RPM. Wybierz dłuższą rozgrzewkę, jeśli zaczynasz całkiem „na zimno”.</p></div></article>
        <article><b>5</b><div><strong>Poziomy 1–8</strong><p>Każdy poziom trwa 3 minuty. Po komunikacie zmień opór, wróć do kadencji ustawionej poniżej (domyślnie 80 RPM) i trzymaj się zielonego pasma. Ostatnia minuta wyznacza HR steady-state.</p></div></article>
        <article><b>6</b><div><strong>Schłodzenie i HRR</strong><p>Po ostatnim kroku ustaw poziom 1 i kręć lekko przez 2 minuty. Nie zatrzymuj się — system zapisze spadek HR po 60 i 120 sekundach.</p></div></article>
      </div>
      <div class="live-workout-calibration-metronome-help">
        <strong>Metronom kadencji</strong>
        <span><b>1:1</b> — jedno piknięcie na pełny obrót korby. Przy 80 RPM usłyszysz 80 BPM.</span>
        <span><b>1:2</b> — piknięcie na każde depnięcie: lewa, prawa, lewa, prawa. Przy 80 RPM usłyszysz 160 BPM. Ten rytm jest ustawiony domyślnie.</span>
        <small>Tempo automatycznie podąża za celem aktualnej fazy. Baseline i pauza wyciszają metronom.</small>
      </div>
      <aside>Przerwij test, jeśli pojawi się ból w klatce piersiowej, zawroty głowy, nietypowa duszność albo wyraźnie złe samopoczucie. Częściowy wynik możesz bezpiecznie zapisać.</aside>
    </section>

    <section class="live-workout-calibration-setup" data-cal-setup>
      <div>
        <strong>Ustawienia protokołu</strong>
        <label>Kadencja kroków <input type="number" min="60" max="100" step="1" value="80" data-cal-target-rpm> RPM</label>
        <label>Tolerancja <input type="number" min="2" max="10" step="1" value="4" data-cal-tolerance> RPM</label>
        <label>Rozgrzewka
          <select data-cal-warmup><option value="180">3 min</option><option value="240">4 min</option><option value="300">5 min</option></select>
        </label>
        <label class="live-workout-calibration-resume" data-cal-resume-wrap hidden>
          <input type="checkbox" data-cal-resume checked>
          <span data-cal-resume-text>Kontynuuj częściową kalibrację</span>
        </label>
      </div>
      <div class="live-workout-calibration-preflight">
        <strong>Kiedy przycisk START się odblokuje?</strong>
        <span><i></i> W nagłówku HR musi pojawić się zielona kropka i świeża wartość BPM.</span>
        <span><i></i> MAGENE CSC musi być połączony, a diagnostyka musi rozpoznać tryb kadencji.</span>
        <span><i></i> Jeśli widzisz zielone „Kadencja: 0 RPM”, wszystko jest gotowe — podczas baseline nie ruszaj korbą.</span>
      </div>
      <button type="button" class="is-primary" data-cal-start>ROZPOCZNIJ TEST KALIBRACYJNY</button>
    </section>

    <section class="live-workout-calibration-hud" data-cal-hud hidden>
      <div class="live-workout-calibration-phasebar">
        <span data-cal-phase-label>Faza 0/10</span>
        <div><i data-cal-phase-progress></i></div>
        <small data-cal-phase-purpose>Diagnostyka</small>
      </div>
      <div class="live-workout-calibration-hud-grid">
        <article class="live-workout-calibration-level">
          <span>USTAW OPÓR</span>
          <strong data-cal-level>—</strong>
          <small data-cal-level-caption>Nie pedałuj</small>
        </article>
        <article class="live-workout-calibration-clock">
          <span>DO KOŃCA ETAPU</span>
          <time data-cal-phase-time>01:00</time>
          <small>cały test: <b data-cal-total-time>29:00</b></small>
        </article>
        <article class="live-workout-calibration-cadence">
          <span>KADENCJA</span>
          <strong><b data-cal-rpm>--</b> RPM</strong>
          <div class="live-workout-calibration-gauge" data-cal-gauge>
            <i class="is-band" data-cal-gauge-band></i><i class="is-needle" data-cal-gauge-needle></i>
          </div>
          <small data-cal-rpm-guidance>Czekam na sensor</small>
        </article>
        <article class="live-workout-calibration-hr">
          <span>TĘTNO LIVE</span>
          <strong><b data-cal-hr>--</b> BPM</strong>
          <small data-cal-steady>Pomiar steady-state w ostatniej minucie</small>
        </article>
      </div>
      <div class="live-workout-calibration-controls">
        <button type="button" data-cal-action="pause">PAUZA</button>
        <button type="button" data-cal-action="resume" hidden>WZNÓW</button>
        <button type="button" data-cal-action="skip">POMIŃ KROK</button>
        <button type="button" data-cal-action="repeat">POWTÓRZ KROK</button>
        <button type="button" data-cal-action="partial">ZATRZYMAJ I ZAPISZ CZĘŚCIOWO</button>
        <button type="button" class="is-danger" data-cal-action="reset">RESET</button>
      </div>
      <section class="live-workout-calibration-chart">
        <div><strong>Tętno podczas testu</strong><span>markery pokazują zmianę poziomu oporu</span></div>
        <canvas data-cal-chart></canvas>
      </section>
      <div class="live-workout-calibration-step-results" data-cal-step-results></div>
    </section>

    <section class="live-workout-calibration-analysis" data-cal-analysis>
      <header><div><strong>Model i analiza</strong><span data-cal-model-summary>Brak zapisanej kalibracji</span></div><button type="button" data-cal-clear-learning>USUŃ PRÓBKI Z TRENINGÓW</button><button type="button" data-cal-clear>USUŃ KALIBRACJE</button></header>
      <div class="live-workout-calibration-analysis-grid">
        <div class="live-workout-calibration-curve" data-cal-curve></div>
        <div class="live-workout-calibration-zones" data-cal-zones></div>
        <div class="live-workout-calibration-advisor">
          <strong>Doradca treningowy</strong>
          <label>Cel
            <select data-cal-advisor-zone>
              <option value="Z2">Zone 2 · LISS / Aerobic</option>
              <option value="Z1">Zone 1 · Active Recovery</option>
              <option value="Z3">Zone 3 · Tempo</option>
              <option value="Z4">Zone 4 · Threshold</option>
              <option value="Z5">Zone 5 · VO2max</option>
              <option value="custom">Własne HR</option>
            </select>
          </label>
          <label>Docelowe HR <input type="number" min="70" max="220" data-cal-advisor-hr></label>
          <label>Aktualny poziom oporu <input type="number" min="1" max="8" value="1" data-cal-advisor-level></label>
          <output data-cal-advice>Najpierw wykonaj przynajmniej część testu.</output>
        </div>
      </div>
      <div class="live-workout-calibration-history" data-cal-history></div>
    </section>`;
  return panel;
}

export function getCalibrationElements(panel) {
  const find = (selector) => panel.querySelector(selector);
  return {
    panel,
    close: find("[data-cal-close]"),
    audio: find("[data-cal-audio]"),
    metronome: find("[data-cal-metronome]"),
    metronomeMode: find("[data-cal-metronome-mode]"),
    metronomeTempo: find("[data-cal-metronome-tempo]"),
    hrStatus: find("[data-cal-hr-status]"),
    cadenceStatus: find("[data-cal-cadence-status]"),
    reconnect: find("[data-cal-reconnect]"),
    alert: find("[data-cal-alert]"),
    setup: find("[data-cal-setup]"),
    targetRpm: find("[data-cal-target-rpm]"),
    tolerance: find("[data-cal-tolerance]"),
    warmup: find("[data-cal-warmup]"),
    resumeWrap: find("[data-cal-resume-wrap]"),
    resumeSaved: find("[data-cal-resume]"),
    resumeText: find("[data-cal-resume-text]"),
    start: find("[data-cal-start]"),
    hud: find("[data-cal-hud]"),
    phaseLabel: find("[data-cal-phase-label]"),
    phaseProgress: find("[data-cal-phase-progress]"),
    phasePurpose: find("[data-cal-phase-purpose]"),
    level: find("[data-cal-level]"),
    levelCaption: find("[data-cal-level-caption]"),
    phaseTime: find("[data-cal-phase-time]"),
    totalTime: find("[data-cal-total-time]"),
    rpm: find("[data-cal-rpm]"),
    rpmGuidance: find("[data-cal-rpm-guidance]"),
    gauge: find("[data-cal-gauge]"),
    gaugeBand: find("[data-cal-gauge-band]"),
    gaugeNeedle: find("[data-cal-gauge-needle]"),
    hr: find("[data-cal-hr]"),
    steady: find("[data-cal-steady]"),
    pause: find('[data-cal-action="pause"]'),
    resume: find('[data-cal-action="resume"]'),
    chart: find("[data-cal-chart]"),
    stepResults: find("[data-cal-step-results]"),
    modelSummary: find("[data-cal-model-summary]"),
    curve: find("[data-cal-curve]"),
    zones: find("[data-cal-zones]"),
    clear: find("[data-cal-clear]"),
    clearLearning: find("[data-cal-clear-learning]"),
    advisorZone: find("[data-cal-advisor-zone]"),
    advisorHr: find("[data-cal-advisor-hr]"),
    advisorLevel: find("[data-cal-advisor-level]"),
    advice: find("[data-cal-advice]"),
    history: find("[data-cal-history]"),
  };
}

function phasePurpose(phase) {
  if (!phase) return "Test zakończony";
  if (phase.kind === "baseline") return "Nie pedałuj · 60 s pomiaru tętna wyjściowego";
  if (phase.kind === "warmup") return "Luźna rozgrzewka na poziomie 1";
  if (phase.kind === "step") return "Ostatnie 60 s: średnie HR · ostatnie 45 s: stabilność";
  return "Luźne kręcenie · HRR po 60 i 120 sekundach";
}

export function renderCalibrationPanel(elements, view) {
  const { snapshot, heartRate, cadenceRpm, hrReady, cadenceReady, cadenceStale = false, model, calibrations, zones, advice } = view;
  const active = ["running", "paused"].includes(snapshot.status);
  const phase = snapshot.phase;
  elements.hrStatus.classList.toggle("is-ready", hrReady);
  elements.hrStatus.lastChild.textContent = ` HR: ${hrReady ? `${Math.round(heartRate)} BPM` : "brak świeżego sygnału"}`;
  elements.cadenceStatus.classList.toggle("is-ready", cadenceReady);
  elements.cadenceStatus.classList.toggle("is-stale", cadenceReady && cadenceStale);
  elements.cadenceStatus.lastChild.textContent = ` Kadencja: ${cadenceReady ? `${Math.round(cadenceRpm || 0)} RPM${cadenceStale ? " · chwilowy brak świeżych danych" : ""}` : "sensor CSC niegotowy"}`;
  elements.setup.hidden = active;
  elements.hud.hidden = !active;
  elements.start.disabled = !hrReady || !cadenceReady;
  elements.reconnect.hidden = cadenceReady;
  elements.alert.hidden = snapshot.pauseReason !== "signal";
  elements.alert.textContent = snapshot.pauseReason === "signal"
    ? `TEST WSTRZYMANY · brak sygnału: ${snapshot.signals.hrAvailable ? "" : "HR "}${snapshot.signals.cadenceAvailable ? "" : "CADENCE"}. Po odzyskaniu połączenia kliknij WZNÓW.`
    : "";

  if (active && phase) {
    const progress = phase.durationSeconds ? Math.min(100, snapshot.phaseElapsed / phase.durationSeconds * 100) : 0;
    elements.phaseLabel.textContent = `FAZA ${snapshot.phaseNumber}/${snapshot.phaseCount} · ${phase.name.toUpperCase()}`;
    elements.phaseProgress.style.width = `${progress}%`;
    elements.phasePurpose.textContent = snapshot.blockedReason === "stop-pedaling" ? "ZATRZYMAJ PEDAŁY — baseline jeszcze nie jest naliczany" : phasePurpose(phase);
    elements.level.textContent = phase.level || "—";
    elements.levelCaption.textContent = phase.kind === "baseline" ? "NIE PEDAŁUJ" : `MANETKA · POZIOM ${phase.level}`;
    elements.phaseTime.textContent = formatTime(snapshot.phaseRemaining);
    elements.totalTime.textContent = formatTime(snapshot.totalRemaining);
    elements.rpm.textContent = Number.isFinite(Number(cadenceRpm)) ? String(Math.round(cadenceRpm)) : "--";
    elements.rpm.classList.toggle("is-stale", cadenceStale);
    elements.hr.textContent = Number.isFinite(Number(heartRate)) ? String(Math.round(heartRate)) : "--";
    const low = phase.targetRpm - phase.toleranceRpm;
    const high = phase.targetRpm + phase.toleranceRpm;
    const rpm = Number(cadenceRpm);
    elements.gaugeBand.style.left = `${Math.max(0, low / 120 * 100)}%`;
    elements.gaugeBand.style.width = `${Math.max(0, (high - low) / 120 * 100)}%`;
    elements.gaugeNeedle.style.left = `${Math.min(100, Math.max(0, (Number.isFinite(rpm) ? rpm : 0) / 120 * 100))}%`;
    elements.gauge.dataset.state = phase.kind === "baseline" || !Number.isFinite(rpm)
      ? "neutral" : rpm < low ? "low" : rpm > high ? "high" : "target";
    elements.rpmGuidance.textContent = phase.kind === "baseline"
      ? rpm > 5 ? "Zatrzymaj pedały" : "Prawidłowo · pozostań w bezruchu"
      : !Number.isFinite(rpm) ? "Czekam na sensor"
      : rpm < low ? `Przyspiesz do ${phase.targetRpm} RPM`
      : rpm > high ? `Zwolnij do ${phase.targetRpm} RPM`
      : `W paśmie ${low}–${high} RPM`;
    const steadyRemaining = phase.kind === "step" ? snapshot.phaseRemaining - 60 : null;
    elements.steady.textContent = phase.kind === "step"
      ? steadyRemaining > 0 ? `Steady-state rozpocznie się za ${formatTime(steadyRemaining)}` : "TRWA POMIAR STEADY-STATE"
      : phasePurpose(phase);
    elements.pause.hidden = snapshot.status !== "running";
    elements.resume.hidden = snapshot.status !== "paused";
    elements.resume.textContent = snapshot.status === "paused" && snapshot.phaseElapsed > 0
      ? "WZNÓW OD POCZĄTKU ETAPU"
      : "WZNÓW";
  }

  renderStepResults(elements.stepResults, snapshot.results);
  renderAnalysis(elements, model, calibrations, zones, advice);
}

function renderStepResults(container, results = []) {
  const steps = results.filter((result) => result.kind === "step");
  if (!steps.length) {
    container.innerHTML = '<span class="live-workout-calibration-empty">Wyniki poziomów pojawią się tutaj po każdym kroku.</span>';
    return;
  }
  container.innerHTML = steps.map((result) => {
    const warning = result.skipped ? "pominięty"
      : result.warnings?.includes("hr-still-rising") ? "HR nadal rośnie"
      : result.warnings?.includes("high-hr-variability") ? "niestabilne HR"
      : result.warnings?.includes("cadence-out-of-band") ? "RPM poza pasmem"
      : result.warnings?.includes("insufficient-steady-data") ? "za mało danych"
      : "stabilny";
    return `
    <div class="${result.steadyState ? "is-good" : "is-warning"}">
      <b>P${result.level}</b><strong>${formatNumber(result.steadyHr)} BPM</strong>
      <span>${formatNumber(result.steadyCadence)} RPM · σ ${formatNumber(result.hrStdDev, 1)} · trend ${formatNumber(result.hrSlopeBpmPerMin, 1)} BPM/min · ${warning}</span>
    </div>`;
  }).join("");
}

function renderAnalysis(elements, model, calibrations, zones, advice) {
  elements.modelSummary.textContent = model
    ? `${model.calibrationCount} kalibracji · ${model.pointCount - model.adaptivePointCount} punktów testowych · ${model.adaptiveObservationCount} użytecznych odcinków z treningów · ref. ${Math.round(model.referenceRpm)} RPM`
    : "Brak zapisanej kalibracji";
  elements.clear.disabled = !calibrations.length;
  elements.clearLearning.disabled = !model?.adaptivePointCount;
  const measuredByLevel = new Map((model?.curve || []).map((point) => [point.level, point]));
  const referenceRpm = Math.round(model?.referenceRpm || 80);
  elements.curve.innerHTML = `
    <strong>Poziomy oporu przy ${referenceRpm} RPM</strong>
    ${Array.from({ length: 8 }, (_, index) => {
      const level = index + 1;
      const point = measuredByLevel.get(level);
      return point
        ? `<div class="is-measured"><span><b>Poziom ${level}</b><small>TEST ${point.calibrationSampleCount} · TRENING ${point.adaptiveObservationCount}</small></span><i><b style="width:${Math.min(100, Math.max(0, (point.predictedHr - 60) / 140 * 100))}%"></b></i><strong>${Math.round(point.predictedHr)} BPM</strong></div>`
        : `<div class="is-untested"><span><b>Poziom ${level}</b><small>NIEZBADANY</small></span><i></i><strong>-- BPM</strong></div>`;
    }).join("")}
    <small>${model
      ? model.cadenceSensitivityMeasured
        ? `Wpływ kadencji: ~${model.cadenceSensitivity.toFixed(2)} BPM / RPM, policzony z ${model.cadenceSensitivitySampleCount} porównań. Niezbadane poziomy pozostają oznaczone.`
        : `Wpływ kadencji nie jest jeszcze zmierzony — korekty RPM korzystają z ostrożnego założenia roboczego. Niezbadane poziomy pozostają oznaczone.`
      : "Po każdym ukończonym 3-minutowym kroku odpowiedni poziom zmieni się z NIEZBADANY na ZBADANY."}</small>
    <small>Żeby spersonalizować wpływ RPM, powtórz test w osobne, wypoczęte dni przy różnych kadencjach, np. 70 / 80 / 90 RPM. To model tętna i oporu, nie pomiar watów.</small>`;
  elements.zones.innerHTML = model
    ? `<strong>RPM dla aktualnego P${zones.find((zone) => zone.recommendation)?.recommendation.level || "--"}</strong>${zones.map((zone) => `
        <div><span>${zone.id} · ${zone.name}</span><strong>${zone.recommendation ? `${zone.recommendation.rpm} RPM${zone.recommendation.estimated ? " · EST." : ""}` : "--"}</strong><small>${zone.minHr}–${zone.maxHr} BPM</small></div>`).join("")}`
    : '<span class="live-workout-calibration-empty">Strefy zostaną zmapowane po kalibracji.</span>';
  elements.advice.textContent = advice?.message || "Najpierw wykonaj przynajmniej część testu.";
  elements.advice.dataset.state = advice?.kind || "idle";
  elements.history.innerHTML = calibrations.length
    ? calibrations.slice(0, 6).map((calibration) => `
        <span><b>${new Date(calibration.timestamp).toLocaleDateString("pl-PL")}</b> · ${calibration.status === "partial" ? "częściowa" : "pełna"} · ${calibration.dataPoints.length}/8 poziomów${calibration.restingHr != null ? ` · HR0 ${Math.round(calibration.restingHr)}` : ""}${calibration.hrr?.drop60 != null ? ` · HRR60 −${Math.round(calibration.hrr.drop60)}` : ""}${calibration.hrr?.drop120 != null ? ` · HRR120 −${Math.round(calibration.hrr.drop120)} BPM` : ""}</span>`).join("")
    : '<span class="live-workout-calibration-empty">Brak zapisanych prób.</span>';
}

export function drawCalibrationChart(canvas, samples = [], maxHr = 190) {
  if (!canvas || typeof canvas.getContext !== "function") return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(2, globalThis.devicePixelRatio || 1);
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const width = rect.width;
  const height = rect.height;
  const padding = { top: 14, right: 18, bottom: 24, left: 38 };
  ctx.clearRect(0, 0, width, height);
  if (!samples.length) return;
  const start = samples[0].timestamp;
  const end = Math.max(start + 1, samples.at(-1).timestamp);
  const minHr = 45;
  const maxY = Math.max(200, maxHr + 5);
  const xFor = (timestamp) => padding.left + (timestamp - start) / (end - start) * (width - padding.left - padding.right);
  const yFor = (hr) => padding.top + (1 - (hr - minHr) / (maxY - minHr)) * (height - padding.top - padding.bottom);
  ctx.font = "10px Inter, system-ui, sans-serif";
  ctx.strokeStyle = "rgba(255,255,255,.09)";
  ctx.fillStyle = "rgba(255,255,255,.42)";
  [60, 100, 140, 180].forEach((hr) => {
    const y = yFor(hr);
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillText(String(hr), 7, y + 3);
  });
  let previousPhase = null;
  samples.forEach((sample) => {
    if (sample.phaseId !== previousPhase) {
      const x = xFor(sample.timestamp);
      ctx.strokeStyle = "rgba(96,165,250,.38)";
      ctx.beginPath(); ctx.moveTo(x, padding.top); ctx.lineTo(x, height - padding.bottom); ctx.stroke();
      ctx.fillStyle = "rgba(147,197,253,.8)";
      ctx.fillText(sample.level ? `P${sample.level}` : "B", Math.min(width - 28, x + 3), padding.top + 10);
      previousPhase = sample.phaseId;
    }
  });
  ctx.strokeStyle = "#fb7185";
  ctx.lineWidth = 2;
  ctx.beginPath();
  samples.forEach((sample, index) => {
    const x = xFor(sample.timestamp);
    const y = yFor(sample.heartRate);
    if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y);
  });
  ctx.stroke();
}
