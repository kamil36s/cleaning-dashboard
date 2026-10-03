import {
  fetchHtrStatus,
  startHtrServer,
  stopHtrServer,
} from "./journal-htr-api.js";
import { escapeHtml } from "./utils.js";

const root = document.getElementById("journal-htr-widget-root");
const action = document.getElementById("journal-htr-widget-action");
const service = document.getElementById("journal-htr-widget-service");
const toggle = document.getElementById("journal-htr-widget-toggle");
let currentState = "stopped";
let pollTimer = null;

function render(status) {
  if (!root) return;
  const stats = status.stats || {};
  const next = status.nextStep || {};
  const online = Boolean(status.services?.escriptorium?.online);
  const runtime = status.runtime || { state: online ? "online" : "stopped" };
  currentState = runtime.state || "stopped";
  const transitioning = currentState === "starting" || currentState === "stopping";
  const runtimeOnline = currentState === "online";

  if (service) {
    service.textContent = {
      online: online ? "HTR online" : "HTR wymaga uwagi",
      starting: "Uruchamianie…",
      stopping: "Zatrzymywanie…",
      error: "Błąd serwera OCR",
      stopped: "Serwer OCR wyłączony",
    }[currentState] || "Serwer OCR wyłączony";
    service.className = `journal-htr-widget-service ${runtimeOnline && online ? "is-online" : "is-offline"}`;
  }
  if (toggle) {
    toggle.disabled = transitioning;
    toggle.textContent = {
      online: "Wyłącz serwer",
      starting: "Uruchamianie…",
      stopping: "Zatrzymywanie…",
      error: runtime.canStop ? "Wyłącz serwer" : "Uruchom ponownie",
      stopped: "Uruchom serwer",
    }[currentState] || "Uruchom serwer";
    toggle.dataset.action = runtimeOnline || (currentState === "error" && runtime.canStop)
      ? "stop"
      : "start";
  }
  if (action) {
    action.href = next.actionUrl || "./journal-ocr.html";
    action.textContent = next.actionLabel || "Otwórz";
    action.hidden = !runtimeOnline;
  }
  const runtimeMessage = {
    starting: runtime.detail || "Docker, eScriptorium i workery Kraken są uruchamiane w tle.",
    stopping: runtime.detail || "Kontenery są zatrzymywane bez usuwania danych i modeli.",
    stopped: "OCR nie zajmuje pamięci. Uruchom serwer dopiero, gdy chcesz pracować z rękopisem.",
    error: runtime.detail || "Nie udało się zmienić stanu serwera OCR.",
  }[currentState];
  root.innerHTML = `
    <div class="journal-htr-widget-metrics">
      <div><strong>${Number(stats.totalPages || 0).toLocaleString("pl-PL")}</strong><span>stron</span></div>
      <div><strong>${Number(stats.pendingSegmentation || 0).toLocaleString("pl-PL")}</strong><span>do segmentacji</span></div>
      <div><strong>${Number(stats.pendingTranscription || 0).toLocaleString("pl-PL")}</strong><span>do transkrypcji</span></div>
      <div><strong>${Number(stats.unreviewedLines || 0).toLocaleString("pl-PL")}</strong><span>do sprawdzenia</span></div>
      <div><strong>${Number(stats.approvedTrainingLines || 0).toLocaleString("pl-PL")}</strong><span>ground truth</span></div>
      <div><strong>${escapeHtml(stats.activeModelVersion || "—")}</strong><span>model · CER ${stats.lastCer == null ? "—" : Number(stats.lastCer).toFixed(3)}</span></div>
    </div>
    <section class="journal-htr-widget-next">
      <span>${runtimeOnline ? "Następny krok" : "Serwer OCR"}</span>
      <strong>${escapeHtml(runtimeOnline ? (next.title || "Otwórz moduł OCR") : (
        currentState === "error" ? "Serwer wymaga uwagi" : "Uruchamiany na żądanie"
      ))}</strong>
      <p>${escapeHtml(runtimeOnline ? (next.reason || "") : runtimeMessage)}</p>
    </section>
  `;

  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  if (transitioning) {
    pollTimer = setTimeout(() => refresh().catch(renderError), 1500);
  }
}

function renderError(error) {
  if (!root) return;
  if (service) {
    service.textContent = "Backend offline";
    service.className = "journal-htr-widget-service is-offline";
  }
  if (toggle) toggle.disabled = true;
  if (action) action.hidden = true;
  root.innerHTML = `
    <div class="journal-htr-widget-error">
      <strong>Nie udało się pobrać stanu HTR.</strong>
      <span>${escapeHtml(error.message)}</span>
    </div>
  `;
}

async function refresh() {
  render(await fetchHtrStatus());
}

async function handleToggle() {
  if (!toggle || toggle.disabled) return;
  const stopping = toggle.dataset.action === "stop" || currentState === "online";
  currentState = stopping ? "stopping" : "starting";
  toggle.disabled = true;
  toggle.textContent = stopping ? "Zatrzymywanie…" : "Uruchamianie…";
  if (service) service.textContent = toggle.textContent;
  if (action) action.hidden = true;
  await (stopping ? stopHtrServer() : startHtrServer());
  await refresh();
}

async function init() {
  if (!root) return;
  try {
    await refresh();
  } catch (error) {
    renderError(error);
  }
}

toggle?.addEventListener("click", () => handleToggle().catch(renderError));
window.addEventListener("pagehide", () => {
  if (pollTimer) clearTimeout(pollTimer);
});
init();
