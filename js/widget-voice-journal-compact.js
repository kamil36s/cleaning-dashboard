import {
  cancelVoiceJournalJob,
  createVoiceJournalEntry,
  createVoiceJournalJob,
  fetchVoiceJournalEntries,
  fetchVoiceJournalHealth,
  fetchVoiceJournalJob,
  fetchVoiceJournalJobResult,
  resolveVoiceJournalModel,
} from "./voice-journal-api.js";
import {
  VOICE_JOURNAL_ACCEPT,
  audioFileExtension,
  formatVoiceJournalBytes,
  formatVoiceJournalDuration,
  organizeVoiceJournalTranscript,
} from "./voice-journal-format.js";

const ACCEPTED_EXTENSIONS = new Set(["aac", "m4a", "mp3", "wav", "ogg", "webm", "flac"]);
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "interrupted"]);
const STAGE_LABELS = {
  queued: "W kolejce",
  validating: "Walidacja audio",
  loading_model: "Ładowanie modelu",
  transcribing: "Transkrypcja",
  cancelling: "Anulowanie",
  completed: "Gotowe",
};

function compactMarkup() {
  return `
    <div class="voice-journal-compact-stats" aria-label="Statystyki dziennika głosowego">
      <div><span>Wpisy</span><strong id="voice-journal-compact-count">–</strong></div>
      <div><span>Łącznie audio</span><strong id="voice-journal-compact-duration">–</strong></div>
      <div><span>Ostatni wpis</span><strong id="voice-journal-compact-latest">–</strong></div>
    </div>

    <div class="voice-journal-compact-compose">
      <input id="voice-journal-compact-file" type="file" accept="${VOICE_JOURNAL_ACCEPT}" hidden>
      <div class="voice-journal-compact-upload" id="voice-journal-compact-upload" role="button" tabindex="0">
        <strong id="voice-journal-compact-file-name">Dodaj nagranie</strong>
        <span id="voice-journal-compact-file-meta">Kliknij lub upuść aac, m4a, mp3, wav, ogg, webm albo flac</span>
      </div>
      <label class="voice-journal-compact-title">Tytuł
        <input id="voice-journal-compact-title" type="text" maxlength="120" placeholder="Domyślnie nazwa pliku">
      </label>
      <div class="voice-journal-compact-actions">
        <button class="voice-journal-primary" id="voice-journal-compact-start" type="button" disabled>Transkrybuj i zapisz</button>
        <button class="voice-journal-entry-action is-danger" id="voice-journal-compact-cancel" type="button" hidden>Anuluj</button>
      </div>
      <div class="voice-journal-compact-status" id="voice-journal-compact-status" aria-live="polite">Łączenie z lokalnym backendem…</div>
    </div>
  `;
}

function latestEntry(entries) {
  return [...entries].sort((left, right) => new Date(right.recordedAt) - new Date(left.recordedAt))[0] || null;
}

export async function initCompactVoiceJournalWidget(root, dependencies = {}) {
  const fetchHealth = dependencies.fetchHealth || fetchVoiceJournalHealth;
  const fetchEntries = dependencies.fetchEntries || fetchVoiceJournalEntries;
  const createJob = dependencies.createJob || createVoiceJournalJob;
  const getJob = dependencies.getJob || fetchVoiceJournalJob;
  const getJobResult = dependencies.getJobResult || fetchVoiceJournalJobResult;
  const createEntry = dependencies.createEntry || createVoiceJournalEntry;
  const cancelJob = dependencies.cancelJob || cancelVoiceJournalJob;
  const waitForPoll = dependencies.waitForPoll || ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
  const pollInterval = dependencies.pollInterval ?? 750;

  root.innerHTML = compactMarkup();
  const card = root.closest(".voice-journal");
  const backendPill = card?.querySelector("#voice-journal-backend-pill");
  const fileInput = root.querySelector("#voice-journal-compact-file");
  const upload = root.querySelector("#voice-journal-compact-upload");
  const fileName = root.querySelector("#voice-journal-compact-file-name");
  const fileMeta = root.querySelector("#voice-journal-compact-file-meta");
  const titleInput = root.querySelector("#voice-journal-compact-title");
  const startButton = root.querySelector("#voice-journal-compact-start");
  const cancelButton = root.querySelector("#voice-journal-compact-cancel");
  const status = root.querySelector("#voice-journal-compact-status");
  const count = root.querySelector("#voice-journal-compact-count");
  const totalDuration = root.querySelector("#voice-journal-compact-duration");
  const latest = root.querySelector("#voice-journal-compact-latest");

  let health = null;
  let selectedFile = null;
  let activeJobId = null;
  let busy = false;
  let disposed = false;

  const setStatus = (message, kind = "") => {
    status.textContent = message;
    status.dataset.kind = kind;
  };

  const setBusy = (nextBusy) => {
    busy = nextBusy;
    fileInput.disabled = nextBusy;
    titleInput.disabled = nextBusy;
    startButton.disabled = nextBusy || !selectedFile || !health;
    cancelButton.hidden = !nextBusy;
  };

  const renderStats = (entries) => {
    const safeEntries = Array.isArray(entries) ? entries : [];
    const seconds = safeEntries.reduce((sum, entry) => sum + Math.max(0, Number(entry.durationSeconds) || 0), 0);
    const newest = latestEntry(safeEntries);
    count.textContent = String(safeEntries.length);
    totalDuration.textContent = formatVoiceJournalDuration(seconds);
    latest.textContent = newest
      ? new Date(newest.recordedAt).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" })
      : "Brak";
  };

  const refreshStats = async () => {
    try {
      renderStats(await fetchEntries());
    } catch {
      count.textContent = "–";
      totalDuration.textContent = "–";
      latest.textContent = "–";
    }
  };

  const selectFile = (file) => {
    const extension = audioFileExtension(file);
    if (!file || !ACCEPTED_EXTENSIONS.has(extension)) {
      setStatus("Nieobsługiwany format pliku.", "error");
      return false;
    }
    if (health?.maxUploadBytes && file.size > health.maxUploadBytes) {
      setStatus(`Plik przekracza limit ${formatVoiceJournalBytes(health.maxUploadBytes)}.`, "error");
      return false;
    }
    selectedFile = file;
    titleInput.value = file.name;
    fileName.textContent = file.name;
    fileMeta.textContent = `${formatVoiceJournalBytes(file.size)} · ${extension.toUpperCase()}`;
    upload.classList.add("has-file");
    setStatus("Nagranie gotowe do lokalnej transkrypcji.", "ok");
    setBusy(false);
    return true;
  };

  upload.addEventListener("click", () => { if (!busy) fileInput.click(); });
  upload.addEventListener("keydown", (event) => {
    if (!busy && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => selectFile(fileInput.files?.[0]));
  ["dragenter", "dragover"].forEach((name) => upload.addEventListener(name, (event) => {
    event.preventDefault();
    if (!busy) upload.classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach((name) => upload.addEventListener(name, (event) => {
    event.preventDefault();
    upload.classList.remove("is-dragging");
  }));
  upload.addEventListener("drop", (event) => {
    if (!busy && event.dataTransfer?.files?.length === 1) selectFile(event.dataTransfer.files[0]);
  });

  cancelButton.addEventListener("click", async () => {
    if (!activeJobId) return;
    cancelButton.disabled = true;
    setStatus("Anulowanie zadania…", "working");
    try {
      await cancelJob(activeJobId);
    } catch (error) {
      cancelButton.disabled = false;
      setStatus(error?.message || "Nie udało się anulować zadania.", "error");
    }
  });

  startButton.addEventListener("click", async () => {
    if (!selectedFile || !health || busy) return;
    const model = resolveVoiceJournalModel("auto", health);
    const cachedModels = Array.isArray(health.cachedModels) ? health.cachedModels : [];
    if (!model || !cachedModels.includes(model)) {
      setStatus("Brak modelu w cache. Otwórz pełny dziennik, aby potwierdzić pobranie modelu.", "error");
      return;
    }
    setBusy(true);
    cancelButton.disabled = false;
    setStatus("Wysyłanie nagrania…", "working");
    try {
      let job = await createJob({
        file: selectedFile,
        model,
        language: health.supportedLanguages?.includes("pl") ? "pl" : "auto",
        task: "transcribe",
        device: health.supportedDevices?.includes("auto") ? "auto" : "cpu",
        transcriptionOptions: {},
        allowModelDownload: false,
      }, {
        onUploadProgress: ({ percent }) => setStatus(`Wysyłanie: ${Math.round(percent)}%`, "working"),
      });
      activeJobId = job.id;
      while (!TERMINAL_STATUSES.has(job.status)) {
        setStatus(STAGE_LABELS[job.stage] || STAGE_LABELS[job.status] || "Przetwarzanie…", "working");
        await waitForPoll(pollInterval);
        if (disposed) return;
        job = await getJob(activeJobId);
      }
      if (job.status !== "completed") {
        throw new Error(job.error || (job.status === "cancelled" ? "Transkrypcja została anulowana." : "Transkrypcja została przerwana."));
      }
      const result = await getJobResult(activeJobId);
      const modified = Number(selectedFile.lastModified);
      const recordedAt = new Date(modified > 0 ? modified : Date.now()).toISOString();
      await createEntry({
        file: selectedFile,
        entry: {
          title: titleInput.value.trim() || selectedFile.name,
          entryCategory: "spontaneous",
          recordedAt,
          dateSource: modified > 0 ? "file_modified" : "upload_time",
          tags: [],
          transcript: organizeVoiceJournalTranscript(result.transcriptSegments, result.transcript),
          rawTranscript: result.transcript || "",
          transcriptSegments: Array.isArray(result.transcriptSegments) ? result.transcriptSegments : [],
          language: health.supportedLanguages?.includes("pl") ? "pl" : "auto",
          model: result.model,
          device: result.device,
          transcriptionDurationSeconds: result.transcriptionDurationSeconds,
          realTimeFactor: result.realTimeFactor,
        },
      });
      selectedFile = null;
      fileInput.value = "";
      titleInput.value = "";
      fileName.textContent = "Dodaj nagranie";
      fileMeta.textContent = "Kliknij lub upuść aac, m4a, mp3, wav, ogg, webm albo flac";
      upload.classList.remove("has-file");
      await refreshStats();
      setStatus("Transkrypcja została zapisana. Szczegóły są w pełnym dzienniku.", "ok");
    } catch (error) {
      setStatus(error?.message || "Nie udało się wykonać transkrypcji.", "error");
    } finally {
      activeJobId = null;
      cancelButton.disabled = false;
      setBusy(false);
    }
  });

  try {
    health = await fetchHealth();
    const cachedModel = resolveVoiceJournalModel("auto", health);
    const ready = health.status === "ok" && health.cachedModels?.includes(cachedModel);
    backendPill.textContent = ready ? "Backend OK" : "Wymaga konfiguracji";
    backendPill.dataset.kind = ready ? "ok" : "error";
    const uploadLimits = health.maxUploadBytes && health.maxDurationSeconds
      ? ` Limit: ${formatVoiceJournalBytes(health.maxUploadBytes)} / ${Math.round(health.maxDurationSeconds / 60)} min.`
      : "";
    setStatus(
      ready ? `Szybki zapis użyje modelu ${cachedModel}.${uploadLimits}` : "Otwórz pełny dziennik, aby skonfigurować Whispera.",
      ready ? "ok" : "error",
    );
    if (!ready) health = null;
  } catch (error) {
    health = null;
    backendPill.textContent = "Backend offline";
    backendPill.dataset.kind = "error";
    setStatus(error?.message || "Lokalny backend jest niedostępny.", "error");
  }
  await refreshStats();
  setBusy(false);

  const dispose = () => { disposed = true; };
  window.addEventListener("pagehide", dispose, { once: true });
  return { selectFile, refreshStats, dispose };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("voice-journal-root");
  if (root?.dataset.voiceJournalMode === "compact") initCompactVoiceJournalWidget(root);
}
