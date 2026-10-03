// js/breathwork.js
// Moduł ćwiczeń oddechowych — silnik, UI (fullscreen overlay), historia sesji.
import { getProtocol } from './breathwork-protocols.js';

/* ─────────────────────── Historia sesji ─────────────────────── */

const STORAGE_KEY = 'breathwork.sessions.v1';

function loadSessions() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

function persistSessions(sessions) {
  if (sessions.length > 50) sessions.length = 50;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
}

function saveSession(protocolId, cycles) {
  const sessions = loadSessions();
  sessions.unshift({ ts: new Date().toISOString(), protocol: protocolId, cycles });
  persistSessions(sessions);
}

function deleteSession(index) {
  const sessions = loadSessions();
  sessions.splice(index, 1);
  persistSessions(sessions);
  renderHistory();
}

/* ─────────────────────── Silnik ─────────────────────── */

class BreathworkEngine {
  constructor(protocol, { onPhaseStart, onTick, onCycleComplete, onSessionEnd }) {
    this.protocol = protocol;
    this.onPhaseStart = onPhaseStart;
    this.onTick = onTick;
    this.onCycleComplete = onCycleComplete;
    this.onSessionEnd = onSessionEnd;

    this.running = false;
    this.phaseIdx = 0;
    this.cyclesCompleted = 0;
    this.targetCycles = protocol.defaultCycles;
    this._handle = null;
    this._phaseStart = 0;
    this._lastSec = -1;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this._beginPhase(0);
    this._handle = setInterval(() => this._tick(), 80);
  }

  stop() {
    this.running = false;
    clearInterval(this._handle);
    this._handle = null;
  }

  reset() {
    this.stop();
    this.phaseIdx = 0;
    this.cyclesCompleted = 0;
    this._lastSec = -1;
  }

  setCycles(n) {
    this.targetCycles = Math.max(1, Math.min(this.protocol.maxCycles, n));
  }

  _beginPhase(idx) {
    this.phaseIdx = idx;
    this._phaseStart = performance.now();
    this._lastSec = -1;
    const phase = this.protocol.phases[idx];
    this.onPhaseStart(phase, idx);
    this.onTick(phase.duration);
  }

  _tick() {
    if (!this.running) return;
    const phase = this.protocol.phases[this.phaseIdx];
    const elapsed = (performance.now() - this._phaseStart) / 1000;
    const secLeft = Math.max(0, Math.ceil(phase.duration - elapsed));

    if (secLeft !== this._lastSec) {
      this._lastSec = secLeft;
      this.onTick(secLeft);
    }

    if (elapsed >= phase.duration) {
      const next = this.phaseIdx + 1;
      if (next >= this.protocol.phases.length) {
        this.cyclesCompleted++;
        this.onCycleComplete(this.cyclesCompleted);
        if (this.cyclesCompleted >= this.targetCycles) {
          this.stop();
          this.onSessionEnd(this.cyclesCompleted);
        } else {
          this._beginPhase(0);
        }
      } else {
        this._beginPhase(next);
      }
    }
  }
}

/* ─────────────────────── Fullscreen API ─────────────────────── */

function requestFs() {
  const el = document.documentElement;
  try {
    (el.requestFullscreen || el.webkitRequestFullscreen || el.mozRequestFullScreen)?.call(el);
  } catch (_) {}
}

function exitFs() {
  try {
    (document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen)?.call(document);
  } catch (_) {}
}

/* ─────────────────────── DOM refs ─────────────────────── */

// Normal page
const startBtn     = document.getElementById('bw-start');
const cyclesInput  = document.getElementById('bw-cycles-input');
const historyList  = document.getElementById('bw-history-list');

// Fullscreen overlay
const fsOverlay    = document.getElementById('bw-fullscreen');
const fsInner      = document.getElementById('bw-fs-inner');
const fsCountdown  = document.getElementById('bw-fs-countdown');
const fsSublabel   = document.getElementById('bw-fs-sublabel');
const fsPhase      = document.getElementById('bw-fs-phase');
const fsInstruct   = document.getElementById('bw-fs-instruction');
const fsCycle      = document.getElementById('bw-fs-cycle');
const fsDots       = document.getElementById('bw-fs-dots');
const stopBtn      = document.getElementById('bw-stop');

// Prep overlay
const prepOverlay  = document.getElementById('bw-prep-overlay');
const prepNum      = document.getElementById('bw-prep-num');

/* ─────────────────────── UI helpers ─────────────────────── */

function setFsPhase(type) {
  fsOverlay.dataset.fsPhase = type;
}

function applyPhaseAnim(phase) {
  // Ustaw czas trwania jako CSS var (dla animacji)
  fsInner.style.setProperty('--phase-dur', `${phase.duration}s`);
  // Zdejmij stare klasy animacji, wymuś reflow, dodaj nową
  fsInner.classList.remove('bw-anim-inhale', 'bw-anim-hold', 'bw-anim-exhale');
  void fsInner.offsetHeight; // force reflow
  fsInner.classList.add(`bw-anim-${phase.type}`);
}

function renderDots(completed, total) {
  if (!fsDots) return;
  fsDots.innerHTML = Array.from({ length: total }, (_, i) =>
    `<span class="bw-fs-dot${i < completed ? ' done' : ''}"></span>`
  ).join('');
}

function showFullscreen() {
  fsOverlay.hidden = false;
  requestFs();
}

function hideFullscreen() {
  fsOverlay.hidden = true;
  exitFs();
}

function showPrep(callback) {
  prepOverlay.hidden = false;
  let count = 3;
  if (prepNum) prepNum.textContent = count;

  const iv = setInterval(() => {
    count--;
    if (count <= 0) {
      clearInterval(iv);
      prepOverlay.hidden = true;
      callback();
    } else {
      if (prepNum) prepNum.textContent = count;
    }
  }, 1000);
}

/* ─────────────────────── Historia ─────────────────────── */

function renderHistory() {
  if (!historyList) return;
  const sessions = loadSessions();

  if (!sessions.length) {
    historyList.innerHTML = '<li class="bw-history-empty">Brak ukończonych sesji.</li>';
    return;
  }

  historyList.innerHTML = sessions.map((s, i) => {
    const dt = new Date(s.ts);
    const dateStr = dt.toLocaleDateString('pl-PL', { day: 'numeric', month: 'short', year: 'numeric' });
    const timeStr = dt.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
    const cycleWord = s.cycles === 1 ? 'cykl' : s.cycles < 5 ? 'cykle' : 'cykli';
    return `<li class="bw-history-item">
      <div class="bw-history-icon" aria-hidden="true">🌬️</div>
      <div class="bw-history-meta">
        <span class="bw-history-date">${dateStr}, ${timeStr}</span>
        <span class="bw-history-detail">${s.protocol} · ${s.cycles} ${cycleWord}</span>
      </div>
      <button class="bw-history-delete" data-delete-idx="${i}" type="button" aria-label="Usuń sesję z ${dateStr}">✕</button>
    </li>`;
  }).join('');
}

/* ─────────────────────── Session flow ─────────────────────── */

let engine = null;
let sessionStartTime = null;

function buildEngine(targetCycles) {
  const protocol = getProtocol('4-7-8');
  engine = new BreathworkEngine(protocol, {
    onPhaseStart: (phase) => {
      setFsPhase(phase.type);
      applyPhaseAnim(phase);
      if (fsPhase)   fsPhase.textContent   = phase.label;
      if (fsInstruct) fsInstruct.textContent = phase.instruction;
      if (fsSublabel) fsSublabel.textContent = phase.type === 'inhale' ? 'przez nos' :
                                               phase.type === 'hold'   ? 'wstrzymaj' : 'przez usta';
    },
    onTick: (s) => {
      if (fsCountdown) fsCountdown.textContent = s;
    },
    onCycleComplete: (n) => {
      if (fsCycle) fsCycle.textContent = `Cykl ${n} / ${engine.targetCycles}`;
      renderDots(n, engine.targetCycles);
    },
    onSessionEnd: (n) => {
      handleSessionEnd(n);
    },
  });
  engine.setCycles(targetCycles);
}

function handleStart() {
  const target = Math.max(1, Math.min(8, parseInt(cyclesInput?.value, 10) || 4));
  buildEngine(target);

  // Przygotuj dots
  renderDots(0, target);
  if (fsCycle) fsCycle.textContent = `Cykl 0 / ${target}`;
  setFsPhase('idle');
  if (fsPhase)   fsPhase.textContent    = 'Przygotuj się';
  if (fsInstruct) fsInstruct.textContent = 'Ułóż język za górnymi zębami';
  if (fsCountdown) fsCountdown.textContent = '';

  // Pokaż overlay + fullscreen, potem prep countdown, potem start
  showFullscreen();
  showPrep(() => {
    sessionStartTime = Date.now();
    engine.start();
  });
}

function handleStop() {
  if (!engine) return;
  const completed = engine.cyclesCompleted;
  engine.stop();
  engine.reset();

  if (completed > 0) {
    saveSession('4-7-8', completed);
    renderHistory();
  }

  hideFullscreen();
}

function handleSessionEnd(cycles) {
  saveSession('4-7-8', cycles);
  renderHistory();

  // Pokaż "done" chwilę zanim zamknie fullscreen
  setFsPhase('done');
  fsInner.classList.remove('bw-anim-inhale', 'bw-anim-hold', 'bw-anim-exhale');
  if (fsCountdown) fsCountdown.textContent = '✓';
  if (fsPhase)   fsPhase.textContent   = 'Sesja ukończona!';
  if (fsInstruct) fsInstruct.textContent = `${cycles} ${cycles < 5 ? 'cykle' : 'cykli'} · ${Math.round((Date.now() - sessionStartTime) / 1000)}s`;
  if (fsCycle)   fsCycle.textContent   = '';
  renderDots(cycles, engine.targetCycles);

  // Auto-zamknij po 2.5s
  setTimeout(() => {
    engine.reset();
    hideFullscreen();
  }, 2500);
}

/* ─────────────────────── Listeners ─────────────────────── */

startBtn?.addEventListener('click', handleStart);

stopBtn?.addEventListener('click', handleStop);

// Historia — delegacja (delete buttons)
historyList?.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-delete-idx]');
  if (!btn) return;
  deleteSession(parseInt(btn.dataset.deleteIdx, 10));
});

// Jeśli user wyjdzie z fullscreen przez Escape — zatrzymaj sesję
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && engine?.running) {
    handleStop();
  }
});
document.addEventListener('webkitfullscreenchange', () => {
  if (!document.webkitFullscreenElement && engine?.running) {
    handleStop();
  }
});

/* ─── Init ─── */
document.addEventListener('DOMContentLoaded', () => {
  if (cyclesInput) {
    cyclesInput.value = 4;
    cyclesInput.max   = 8;
  }
  renderHistory();
});
