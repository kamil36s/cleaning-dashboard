import {
  availableVoiceJournalOptions,
  cancelVoiceJournalJob,
  createVoiceJournalEntry,
  createVoiceJournalJob,
  deleteVoiceJournalEntry,
  fetchVoiceJournalHealth,
  fetchVoiceJournalEntries,
  fetchVoiceJournalJob,
  fetchVoiceJournalJobResult,
  resolveVoiceJournalModel,
  updateVoiceJournalEntry,
  voiceJournalEngineHealth,
  voiceJournalEngines,
} from "./voice-journal-api.js";
import {
  VOICE_JOURNAL_PRESET_LABELS,
  effectiveTranscriptionSettings,
  loadTranscriptionDefaults,
  parseTranscriptionSetting,
  presetTranscriptionSettings,
  saveTranscriptionDefaults,
  supportedTranscriptionSettings,
} from "./voice-journal-settings.js";
import {
  filterVoiceJournalEntries,
  hasActiveVoiceJournalFilters,
  voiceJournalFilterOptions,
} from "./voice-journal-filters.js";
import {
  VOICE_JOURNAL_ACCEPT,
  audioFileExtension,
  formatVoiceJournalBytes,
  formatVoiceJournalDuration,
  formatVoiceJournalTimestamp,
  groupVoiceJournalSegments,
  organizeVoiceJournalTranscript,
  stripVoiceJournalTimestamps,
  voiceJournalEntryTitle,
} from "./voice-journal-format.js";
import { createVoiceJournalCorrectionEditor } from "./voice-journal-correction-editor.js";
import { publishVoiceJournalEntry } from "./journal-api.js";

export {
  VOICE_JOURNAL_ACCEPT,
  audioFileExtension,
  formatVoiceJournalBytes,
  formatVoiceJournalDuration,
  formatVoiceJournalTimestamp,
  groupVoiceJournalSegments,
  organizeVoiceJournalTranscript,
  stripVoiceJournalTimestamps,
};

const ACCEPTED_EXTENSIONS = new Set(["aac", "m4a", "mp3", "wav", "ogg", "webm", "flac"]);
const JOB_STAGE_INDEX = {
  queued: 1,
  validating: 2,
  loading_model: 3,
  transcribing: 4,
  completed: 5,
  cancelling: 4,
  cancelled: 4,
  failed: 4,
  interrupted: 4,
};
const TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "cancelled", "interrupted"]);
const CATEGORY_LABELS = {
  morning: "Poranny",
  evening: "Wieczorny",
  spontaneous: "Spontaniczny",
  "after-event": "Po wydarzeniu",
};

function pad(value) {
  return String(value).padStart(2, "0");
}

function localDateTimeParts(value) {
  const date = value instanceof Date && !Number.isNaN(value.getTime()) ? value : new Date();
  return {
    date: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  };
}

function formatEtaBound(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) return `${Math.max(5, Math.round(value / 5) * 5)} s`;
  if (value < 3600) return `${Math.max(1, Math.round(value / 60))} min`;
  const hours = Math.round((value / 3600) * 2) / 2;
  return `${hours.toLocaleString("pl-PL")} godz.`;
}

export function formatVoiceJournalEta(eta) {
  if (!eta?.available) {
    return eta?.reason === "audio_duration_unknown"
      ? "ETA: po walidacji audio"
      : "ETA: brak wystarczających danych";
  }
  const low = formatEtaBound(eta.minSeconds);
  const high = formatEtaBound(eta.maxSeconds);
  return `ETA: około ${low === high ? high : `${low}–${high}`}`;
}

export function detectedFileDateTime(file, now = new Date()) {
  const modified = Number(file?.lastModified);
  return localDateTimeParts(modified > 0 ? new Date(modified) : now);
}

export function readAudioMetadata(file) {
  return new Promise((resolve) => {
    if (!file || typeof Audio !== "function" || typeof URL?.createObjectURL !== "function") {
      resolve({ durationSeconds: null });
      return;
    }
    const url = URL.createObjectURL(file);
    const audio = new Audio();
    let settled = false;
    const finish = (durationSeconds = null) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      URL.revokeObjectURL(url);
      resolve({ durationSeconds });
    };
    const timeout = window.setTimeout(() => finish(), 5000);
    audio.preload = "metadata";
    audio.addEventListener("loadedmetadata", () => {
      const duration = Number(audio.duration);
      finish(Number.isFinite(duration) ? duration : null);
    }, { once: true });
    audio.addEventListener("error", () => finish(), { once: true });
    audio.src = url;
    audio.load?.();
  });
}

function setSelectOptions(select, values, labels) {
  select.replaceChildren(...values.map((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labels[value] || value;
    return option;
  }));
  select.disabled = values.length < 2;
}

function splitTags(value) {
  return Array.from(new Set(String(value || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean)))
    .slice(0, 12);
}

function recordedAtFromInputs(dateValue, timeValue) {
  const parsed = new Date(`${dateValue}T${timeValue || "00:00"}:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function entryLocalDateTime(recordedAt) {
  const parsed = new Date(recordedAt);
  return localDateTimeParts(Number.isNaN(parsed.getTime()) ? new Date() : parsed);
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function seekVoiceJournalAudio(audio, seconds) {
  const seek = () => {
    audio.currentTime = Math.max(0, Number(seconds) || 0);
    const playback = audio.play?.();
    playback?.catch?.(() => {});
  };
  if (audio.readyState > 0) seek();
  else audio.addEventListener("loadedmetadata", seek, { once: true });
}

function renderTimestampedTranscript(container, segments, fallbackText, audio) {
  const usableSegments = groupVoiceJournalSegments(segments);
  if (!usableSegments.length) {
    container.textContent = fallbackText || "Brak surowej transkrypcji.";
    return;
  }
  container.replaceChildren(...usableSegments.map((segment) => {
    const line = createElement("span", "voice-journal-transcript-segment");
    const timestamp = createElement("button", "voice-journal-timestamp", `[${formatVoiceJournalTimestamp(segment.start)}]`);
    timestamp.type = "button";
    timestamp.title = `Przejdź do ${formatVoiceJournalTimestamp(segment.start)}`;
    timestamp.setAttribute("aria-label", `Odtwórz od ${formatVoiceJournalTimestamp(segment.start)}`);
    timestamp.addEventListener("click", () => seekVoiceJournalAudio(audio, segment.start));
    line.append(timestamp, document.createTextNode(` ${String(segment.text).trim()}`));
    return line;
  }));
}

function correctionAwareSegments(entry) {
  const source = Array.isArray(entry?.transcriptionData?.segments)
    ? entry.transcriptionData.segments
    : (Array.isArray(entry?.transcriptSegments) ? entry.transcriptSegments : []);
  return source.map((segment) => ({
    ...segment,
    text: String(segment?.correctedText ?? segment?.text ?? segment?.originalText ?? ""),
  }));
}

function widgetMarkup() {
  return `
    <div class="voice-journal-status" id="voice-journal-status" aria-live="polite">
      <strong>Backend</strong>
      <span id="voice-journal-health-text">Łączenie z lokalnym Whisperem…</span>
    </div>

    <div class="voice-journal-upload-row">
      <input id="voice-journal-file" type="file" accept="${VOICE_JOURNAL_ACCEPT}" hidden>
      <button class="card-cta voice-journal-add" id="voice-journal-add" type="button">Dodaj nagranie</button>
      <div class="voice-journal-dropzone" id="voice-journal-dropzone" role="button" tabindex="0" aria-label="Upuść plik audio lub wybierz go z dysku">
        <strong>Upuść plik audio tutaj</strong>
        <span>aac, m4a, mp3, wav, ogg, webm lub flac</span>
      </div>
    </div>

    <section class="voice-journal-workspace" id="voice-journal-workspace" hidden>
      <div class="voice-journal-file-summary">
        <div><span>Nazwa</span><strong id="voice-journal-file-name">-</strong></div>
        <div><span>Rozmiar</span><strong id="voice-journal-file-size">-</strong></div>
        <div><span>Format</span><strong id="voice-journal-file-format">-</strong></div>
        <div><span>Długość</span><strong id="voice-journal-file-duration">-</strong></div>
      </div>

      <div class="voice-journal-form-grid">
        <label>Tytuł <input id="voice-journal-title-input" type="text" maxlength="120" placeholder="Domyślnie nazwa pliku"></label>
        <label>Data <input id="voice-journal-date" type="date"></label>
        <label>Godzina <input id="voice-journal-time" type="time"></label>
        <label>Typ
          <select id="voice-journal-type">
            <option value="morning">Poranny</option>
            <option value="evening">Wieczorny</option>
            <option value="spontaneous" selected>Spontaniczny</option>
            <option value="after-event">Po wydarzeniu</option>
          </select>
        </label>
        <label class="voice-journal-tags-field">Tagi <input id="voice-journal-tags" type="text" maxlength="240" placeholder="np. pomysły, praca, spacer"></label>
      </div>
      <div class="voice-journal-detected-note">Data i godzina są wykrywane z daty modyfikacji pliku i można je poprawić.</div>

      <div class="voice-journal-options">
        <label>Silnik transkrypcji <select id="voice-journal-engine"></select></label>
        <label>Model <select id="voice-journal-model"></select></label>
        <label>Język <select id="voice-journal-language"></select></label>
        <label>Task <select id="voice-journal-task"></select></label>
        <label>Urządzenie <select id="voice-journal-device"></select></label>
        <label id="voice-journal-compute-field" hidden>Compute type <select id="voice-journal-compute-type"></select></label>
        <label class="voice-journal-word-confidence" id="voice-journal-word-confidence-field" hidden>
          <span>Dokładna korekta</span>
          <span><input id="voice-journal-word-confidence" type="checkbox" checked> Timestampy słów + confidence</span>
        </label>
      </div>
      <div class="voice-journal-engine-diagnostic" id="voice-journal-engine-diagnostic" aria-live="polite"></div>

      <details class="voice-journal-transcription-settings" id="voice-journal-transcription-settings" hidden>
        <summary>Ustawienia transkrypcji <span>Zaawansowane</span></summary>
        <div class="voice-journal-settings-toolbar">
          <label>Preset <select id="voice-journal-settings-preset"></select></label>
          <button class="voice-journal-entry-action" id="voice-journal-settings-save" type="button">Zapisz jako domyślne</button>
          <button class="voice-journal-entry-action" id="voice-journal-settings-restore" type="button">Przywróć zalecane</button>
        </div>
        <div class="voice-journal-advanced-options" id="voice-journal-advanced-options"></div>
        <div class="voice-journal-settings-preview">
          <strong>Efektywna konfiguracja</strong>
          <pre id="voice-journal-settings-preview"></pre>
        </div>
        <div class="voice-journal-settings-status" id="voice-journal-settings-status" aria-live="polite"></div>
      </details>

      <button class="voice-journal-primary" id="voice-journal-transcribe" type="button" disabled>Transkrybuj</button>
    </section>

    <section class="voice-journal-progress" id="voice-journal-progress" aria-live="polite" hidden>
      <div class="voice-journal-indeterminate" aria-hidden="true"><span></span></div>
      <ol>
        <li data-stage="0">Wysyłanie</li>
        <li data-stage="1">W kolejce</li>
        <li data-stage="2">Walidacja</li>
        <li data-stage="3">Ładowanie modelu</li>
        <li data-stage="4">Transkrypcja</li>
        <li data-stage="5">Gotowe</li>
      </ol>
      <div class="voice-journal-job-meta" id="voice-journal-job-meta"></div>
      <button class="voice-journal-entry-action is-danger" id="voice-journal-cancel-job" type="button">Anuluj</button>
    </section>

    <section class="voice-journal-result" id="voice-journal-result" hidden>
      <audio id="voice-journal-player" controls preload="metadata"></audio>
      <div class="voice-journal-transcript-workbench">
        <section class="voice-journal-transcript-pane voice-journal-result-raw">
          <div class="voice-journal-transcript-pane-head">
            <strong>Dirty + timestampy</strong>
            <span>Oryginał Whispera</span>
          </div>
          <div class="voice-journal-transcript-segments" id="voice-journal-result-raw-transcript"></div>
        </section>
        <label class="voice-journal-transcript-pane voice-journal-transcript-field">
          <span class="voice-journal-transcript-pane-head">
            <strong>Wersja uporządkowana</strong>
            <span>Możesz ją poprawić przed zapisem</span>
          </span>
          <textarea id="voice-journal-transcript" rows="12" spellcheck="true"></textarea>
        </label>
      </div>
      <div class="voice-journal-result-meta" id="voice-journal-result-meta"></div>
      <div class="voice-journal-result-actions">
        <button class="voice-journal-primary" id="voice-journal-save" type="button">Zapisz szkic</button>
        <span id="voice-journal-save-status" aria-live="polite"></span>
      </div>
    </section>

    <section class="voice-journal-entries">
      <div class="voice-journal-entries-head">
        <div><strong>Ostatnie wpisy</strong><span id="voice-journal-entry-count">0</span></div>
        <button class="card-cta" id="voice-journal-refresh" type="button">Odśwież</button>
      </div>
      <form class="voice-journal-filters" id="voice-journal-filters" role="search">
        <label class="voice-journal-filter-search">Szukaj
          <input id="voice-journal-filter-query" type="search" placeholder="Tytuł lub treść transkrypcji" autocomplete="off">
        </label>
        <label>Od <input id="voice-journal-filter-from" type="date"></label>
        <label>Do <input id="voice-journal-filter-to" type="date"></label>
        <label>Typ
          <select id="voice-journal-filter-category">
            <option value="">Wszystkie</option>
            <option value="morning">Poranny</option>
            <option value="evening">Wieczorny</option>
            <option value="spontaneous">Spontaniczny</option>
            <option value="after-event">Po wydarzeniu</option>
          </select>
        </label>
        <label>Tag <select id="voice-journal-filter-tag"><option value="">Wszystkie</option></select></label>
        <label>Model <select id="voice-journal-filter-model"><option value="">Wszystkie</option></select></label>
        <label>Sortowanie
          <select id="voice-journal-filter-sort">
            <option value="newest">Najnowsze</option>
            <option value="oldest">Najstarsze</option>
            <option value="longest">Najdłuższe</option>
            <option value="shortest">Najkrótsze</option>
          </select>
        </label>
        <button class="voice-journal-entry-action" id="voice-journal-filter-reset" type="reset">Wyczyść filtry</button>
      </form>
      <div class="voice-journal-list-status" id="voice-journal-list-status" aria-live="polite">
        <span id="voice-journal-list-status-text">Ładowanie wpisów…</span>
        <button class="voice-journal-entry-action" id="voice-journal-list-retry" type="button" hidden>Spróbuj ponownie</button>
      </div>
      <div class="voice-journal-entry-list" id="voice-journal-entry-list"></div>
      <div class="voice-journal-empty" id="voice-journal-empty" hidden>
        <strong id="voice-journal-empty-title">Brak zapisanych wpisów</strong>
        <span id="voice-journal-empty-description">Dodaj pierwsze nagranie, aby rozpocząć dziennik.</span>
        <button class="voice-journal-entry-action" id="voice-journal-empty-reset" type="button" hidden>Wyczyść filtry</button>
      </div>
    </section>
  `;
}

export async function initVoiceJournalWidget(root, dependencies = {}) {
  if (!root) return null;
  const fetchHealth = dependencies.fetchHealth || fetchVoiceJournalHealth;
  const createJob = dependencies.createJob || createVoiceJournalJob;
  const getJob = dependencies.getJob || fetchVoiceJournalJob;
  const getJobResult = dependencies.getJobResult || fetchVoiceJournalJobResult;
  const cancelJob = dependencies.cancelJob || cancelVoiceJournalJob;
  const waitForPoll = dependencies.waitForPoll || ((milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds)));
  const pollInterval = dependencies.pollInterval ?? 750;
  const metadataReader = dependencies.metadataReader || readAudioMetadata;
  const fetchEntries = dependencies.fetchEntries || fetchVoiceJournalEntries;
  const fetchAudio = dependencies.fetchAudio || ((url) => fetch(url, { cache: "no-store" }));
  const createEntry = dependencies.createEntry || createVoiceJournalEntry;
  const updateEntry = dependencies.updateEntry || updateVoiceJournalEntry;
  const removeEntry = dependencies.deleteEntry || deleteVoiceJournalEntry;
  const publishEntry = dependencies.publishEntry || publishVoiceJournalEntry;
  const confirmAction = dependencies.confirmAction || ((message) => window.confirm(message));
  const settingsStorage = dependencies.settingsStorage || globalThis.localStorage;

  root.innerHTML = widgetMarkup();
  const card = root.closest(".voice-journal");
  const backendPill = card?.querySelector("#voice-journal-backend-pill");
  const healthText = root.querySelector("#voice-journal-health-text");
  const status = root.querySelector("#voice-journal-status");
  const fileInput = root.querySelector("#voice-journal-file");
  const addButton = root.querySelector("#voice-journal-add");
  const dropzone = root.querySelector("#voice-journal-dropzone");
  const workspace = root.querySelector("#voice-journal-workspace");
  const transcribeButton = root.querySelector("#voice-journal-transcribe");
  const progress = root.querySelector("#voice-journal-progress");
  const progressBar = progress.querySelector(".voice-journal-indeterminate");
  const progressBarFill = progressBar.querySelector("span");
  const jobMeta = root.querySelector("#voice-journal-job-meta");
  const cancelJobButton = root.querySelector("#voice-journal-cancel-job");
  const resultSection = root.querySelector("#voice-journal-result");
  const player = root.querySelector("#voice-journal-player");
  const rawResultTranscript = root.querySelector("#voice-journal-result-raw-transcript");
  const transcript = root.querySelector("#voice-journal-transcript");
  const resultMeta = root.querySelector("#voice-journal-result-meta");
  const saveButton = root.querySelector("#voice-journal-save");
  const saveStatus = root.querySelector("#voice-journal-save-status");
  const refreshButton = root.querySelector("#voice-journal-refresh");
  const entryList = root.querySelector("#voice-journal-entry-list");
  const entryCount = root.querySelector("#voice-journal-entry-count");
  const listStatus = root.querySelector("#voice-journal-list-status");
  const listStatusText = root.querySelector("#voice-journal-list-status-text");
  const listRetryButton = root.querySelector("#voice-journal-list-retry");
  const emptyEntries = root.querySelector("#voice-journal-empty");
  const emptyTitle = root.querySelector("#voice-journal-empty-title");
  const emptyDescription = root.querySelector("#voice-journal-empty-description");
  const emptyResetButton = root.querySelector("#voice-journal-empty-reset");
  const filtersForm = root.querySelector("#voice-journal-filters");
  const filterQuery = root.querySelector("#voice-journal-filter-query");
  const filterFrom = root.querySelector("#voice-journal-filter-from");
  const filterTo = root.querySelector("#voice-journal-filter-to");
  const filterCategory = root.querySelector("#voice-journal-filter-category");
  const filterTag = root.querySelector("#voice-journal-filter-tag");
  const filterModel = root.querySelector("#voice-journal-filter-model");
  const filterSort = root.querySelector("#voice-journal-filter-sort");
  const filterResetButton = root.querySelector("#voice-journal-filter-reset");
  const modelSelect = root.querySelector("#voice-journal-model");
  const engineSelect = root.querySelector("#voice-journal-engine");
  const languageSelect = root.querySelector("#voice-journal-language");
  const taskSelect = root.querySelector("#voice-journal-task");
  const deviceSelect = root.querySelector("#voice-journal-device");
  const computeTypeSelect = root.querySelector("#voice-journal-compute-type");
  const computeTypeField = root.querySelector("#voice-journal-compute-field");
  const engineDiagnostic = root.querySelector("#voice-journal-engine-diagnostic");
  const wordConfidenceField = root.querySelector("#voice-journal-word-confidence-field");
  const wordConfidenceToggle = root.querySelector("#voice-journal-word-confidence");
  const settingsSection = root.querySelector("#voice-journal-transcription-settings");
  const presetSelect = root.querySelector("#voice-journal-settings-preset");
  const advancedOptions = root.querySelector("#voice-journal-advanced-options");
  const settingsPreview = root.querySelector("#voice-journal-settings-preview");
  const settingsStatus = root.querySelector("#voice-journal-settings-status");
  const saveSettingsButton = root.querySelector("#voice-journal-settings-save");
  const restoreSettingsButton = root.querySelector("#voice-journal-settings-restore");
  const configurableInputs = [engineSelect, modelSelect, languageSelect, taskSelect, deviceSelect, computeTypeSelect, wordConfidenceToggle, presetSelect];
  const settingsControls = new Map();

  let health = null;
  let selectedFile = null;
  let latestResult = null;
  let playerUrl = null;
  let selectionToken = 0;
  let busy = false;
  let backendReady = false;
  let detectedDateTime = null;
  let entries = [];
  let entriesLoading = false;
  let activeJobId = null;
  let activeUploadController = null;
  let transcriptionToken = 0;
  let transcriptionCapabilities = {};
  let selectedPreset = "balanced";
  const entryFilterControls = [filterQuery, filterFrom, filterTo, filterCategory, filterTag, filterModel, filterSort, filterResetButton];

  const setStatus = (message, kind = "") => {
    healthText.textContent = message;
    status.dataset.kind = kind;
  };

  const showListMessage = (message, kind = "info") => {
    listStatus.hidden = false;
    listStatus.dataset.kind = kind;
    listStatusText.textContent = message;
    listRetryButton.hidden = true;
  };

  const readRawTranscriptionSettings = () => {
    const raw = {};
    settingsControls.forEach(({ control, spec }, name) => {
      if (spec.requires === "vad_filter" && settingsControls.get("vad_filter")?.control.checked !== true) return;
      if (name === "best_of" && engineSelect.value === "faster-whisper") {
        const temperature = Number(String(settingsControls.get("temperature")?.control.value || "0").split(",")[0]);
        if (temperature === 0) return;
      }
      raw[name] = parseTranscriptionSetting(spec, spec.type === "boolean" ? control.checked : control.value);
    });
    return raw;
  };

  const readTranscriptionSettings = () => effectiveTranscriptionSettings(
    readRawTranscriptionSettings(),
    transcriptionCapabilities,
    {
      device: deviceSelect.value,
      cudaAvailable: Boolean(health?.gpu?.available),
    },
  );

  const syncSettingsCompatibility = () => {
    const vadEnabled = settingsControls.get("vad_filter")?.control.checked === true;
    settingsControls.forEach(({ control, spec }) => {
      if (spec.requires === "vad_filter") {
        control.disabled = busy || !vadEnabled;
        control.title = vadEnabled ? (spec.tooltip || "") : "Włącz filtr VAD, aby użyć tej opcji.";
      }
    });
    const bestOf = settingsControls.get("best_of")?.control;
    const temperature = settingsControls.get("temperature")?.control;
    if (engineSelect.value === "faster-whisper" && bestOf && temperature) {
      const firstTemperature = Number(String(temperature.value).split(",")[0]);
      bestOf.disabled = busy || firstTemperature === 0;
      bestOf.title = firstTemperature === 0
        ? "Best of nie jest używany przy temperaturze 0 i dekodowaniu beam search."
        : "Liczba kandydatów dekodowania.";
    }
  };

  const updateSettingsPreview = () => {
    syncSettingsCompatibility();
    try {
      settingsPreview.textContent = JSON.stringify(readTranscriptionSettings(), null, 2);
      settingsStatus.textContent = "";
      return true;
    } catch (error) {
      settingsPreview.textContent = "Nieprawidłowa konfiguracja";
      settingsStatus.textContent = error?.message || "Sprawdź ustawienia transkrypcji.";
      return false;
    }
  };

  const setControlValue = (control, spec, value) => {
    if (spec.type === "boolean") {
      control.checked = Boolean(value);
    } else if (spec.type === "temperature" && Array.isArray(value)) {
      control.value = value.join(", ");
    } else {
      control.value = value ?? "";
    }
  };

  const applyTranscriptionSettings = (options, preset = "custom") => {
    settingsControls.forEach(({ control, spec }, name) => {
      setControlValue(control, spec, Object.hasOwn(options || {}, name) ? options[name] : spec.default);
    });
    selectedPreset = preset;
    presetSelect.value = preset;
    const wordControl = settingsControls.get("word_timestamps")?.control;
    if (wordControl) wordConfidenceToggle.checked = wordControl.checked;
    updateSettingsPreview();
  };

  const renderTranscriptionSettings = () => {
    settingsControls.clear();
    advancedOptions.replaceChildren();
    const supported = supportedTranscriptionSettings(transcriptionCapabilities);
    settingsSection.hidden = supported.length === 0;
    if (!supported.length) return;
    presetSelect.replaceChildren(...Object.keys(VOICE_JOURNAL_PRESET_LABELS).map((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = VOICE_JOURNAL_PRESET_LABELS[value];
      option.disabled = value !== "custom" && !transcriptionCapabilities.presets?.[value];
      return option;
    }));
    supported.forEach(([name, spec]) => {
      const label = createElement("label", "voice-journal-advanced-field");
      const caption = createElement("span", "voice-journal-setting-label", spec.label || name);
      const tooltip = createElement("span", "voice-journal-setting-tooltip", "?");
      tooltip.title = spec.tooltip || "";
      tooltip.setAttribute("aria-label", spec.tooltip || `Informacja o ${spec.label || name}`);
      caption.append(tooltip);
      let control;
      if (spec.type === "boolean") {
        control = document.createElement("input");
        control.type = "checkbox";
        label.classList.add("is-boolean");
      } else if (name === "initial_prompt") {
        control = document.createElement("textarea");
        control.rows = 3;
        control.maxLength = spec.maxLength || 2000;
      } else {
        control = document.createElement("input");
        control.type = ["number", "integer"].includes(spec.type) ? "number" : "text";
        if (control.type === "number") {
          control.min = String(spec.min);
          control.max = String(spec.max);
          control.step = spec.type === "integer" ? "1" : "0.1";
        }
        if (spec.maxLength) control.maxLength = spec.maxLength;
      }
      control.dataset.transcriptionOption = name;
      control.addEventListener("input", () => {
        selectedPreset = "custom";
        presetSelect.value = "custom";
        if (name === "word_timestamps") wordConfidenceToggle.checked = control.checked;
        updateSettingsPreview();
      });
      label.append(caption, control);
      advancedOptions.append(label);
      settingsControls.set(name, { control, spec });
      configurableInputs.push(control);
    });

    const stored = loadTranscriptionDefaults(transcriptionCapabilities, settingsStorage);
    const recommended = transcriptionCapabilities.recommendedPreset || "balanced";
    applyTranscriptionSettings(
      stored?.options || presetTranscriptionSettings(transcriptionCapabilities, recommended),
      stored?.preset || recommended,
    );
    const wordControl = settingsControls.get("word_timestamps")?.control;
    wordConfidenceField.hidden = !wordControl;
    if (wordControl && !stored) {
      wordControl.checked = true;
      wordConfidenceToggle.checked = true;
      updateSettingsPreview();
    }
  };

  wordConfidenceToggle.addEventListener("change", () => {
    const wordControl = settingsControls.get("word_timestamps")?.control;
    if (!wordControl) return;
    wordControl.checked = wordConfidenceToggle.checked;
    wordControl.dispatchEvent(new Event("input", { bubbles: true }));
  });

  presetSelect.addEventListener("change", () => {
    if (presetSelect.value === "custom") {
      selectedPreset = "custom";
      return;
    }
    applyTranscriptionSettings(
      presetTranscriptionSettings(transcriptionCapabilities, presetSelect.value),
      presetSelect.value,
    );
  });
  saveSettingsButton.addEventListener("click", () => {
    try {
      const options = readRawTranscriptionSettings();
      saveTranscriptionDefaults({ preset: selectedPreset, options }, settingsStorage);
      settingsStatus.textContent = "Zapisano ustawienia domyślne.";
    } catch (error) {
      settingsStatus.textContent = error?.message || "Nie udało się zapisać ustawień.";
    }
  });
  restoreSettingsButton.addEventListener("click", () => {
    const recommended = transcriptionCapabilities.recommendedPreset || "balanced";
    applyTranscriptionSettings(presetTranscriptionSettings(transcriptionCapabilities, recommended), recommended);
    settingsStatus.textContent = "Przywrócono ustawienia zalecane.";
  });

  const updateTranscribeAvailability = () => {
    const engine = engineSelect.value || "openai-whisper";
    const actualModel = resolveVoiceJournalModel(modelSelect.value, health || {}, engine);
    const engineAvailable = voiceJournalEngineHealth(health || {}, engine)?.available !== false;
    transcribeButton.disabled = busy || !backendReady || !selectedFile || !actualModel || !engineAvailable;
  };

  const renderEngineConfiguration = ({ preserveModel = false } = {}) => {
    const engine = engineSelect.value || "openai-whisper";
    const engineHealth = voiceJournalEngineHealth(health || {}, engine) || {};
    const options = availableVoiceJournalOptions(health || {}, engine);
    const previousModel = modelSelect.value;
    const autoModel = resolveVoiceJournalModel("auto", health || {}, engine);
    setSelectOptions(modelSelect, options.models, {
      auto: `Auto${autoModel ? ` (${autoModel})` : ""}`,
      ...Object.fromEntries(options.supportedModels.map((model) => [
        model,
        `${model[0].toUpperCase()}${model.slice(1)}${options.cachedModels.includes(model) ? "" : " (wymaga pobrania)"}`,
      ])),
    });
    if (preserveModel && options.models.includes(previousModel)) modelSelect.value = previousModel;
    transcriptionCapabilities = engineHealth.transcriptionOptions || {};
    renderTranscriptionSettings();
    computeTypeField.hidden = engine !== "faster-whisper";
    setSelectOptions(computeTypeSelect, options.computeTypes.length ? options.computeTypes : ["auto"], {
      auto: "Auto", float16: "float16", float32: "float32", int8: "int8", int8_float16: "int8_float16",
    });
    if (engine === "faster-whisper" && deviceSelect.value === "cpu") {
      [...computeTypeSelect.options].forEach((option) => {
        if (["float16", "int8_float16"].includes(option.value)) {
          option.disabled = true;
          option.title = "Ten compute_type wymaga CUDA.";
        }
      });
    }
    const unavailableEngines = voiceJournalEngines(health || {}).filter((item) => item.available === false);
    engineDiagnostic.textContent = engineHealth.available === false
      ? `Silnik niedostępny: ${engineHealth.error || "brak wymaganej biblioteki"}`
      : unavailableEngines.map((item) => `${item.label || item.id}: ${item.error || "silnik niedostępny"}`).join(" · ");
    engineDiagnostic.dataset.kind = unavailableEngines.length ? "error" : "";
    updateTranscribeAvailability();
  };

  const clearPlayerUrl = () => {
    if (playerUrl && typeof URL?.revokeObjectURL === "function") URL.revokeObjectURL(playerUrl);
    playerUrl = null;
    player.removeAttribute("src");
  };

  const showProgressStage = (activeStage, completed = false) => {
    progress.querySelectorAll("[data-stage]").forEach((item) => {
      const index = Number(item.dataset.stage);
      item.classList.toggle("is-done", completed ? index <= activeStage : index < activeStage);
      item.classList.toggle("is-active", !completed && index === activeStage);
    });
  };

  const setProgressValue = (value) => {
    const percent = value === null || value === undefined ? Number.NaN : Number(value);
    const determinate = Number.isFinite(percent);
    progress.classList.toggle("is-determinate", determinate);
    if (determinate) {
      const bounded = Math.max(0, Math.min(100, percent));
      progressBarFill.style.width = `${bounded}%`;
      progressBar.setAttribute("role", "progressbar");
      progressBar.setAttribute("aria-valuemin", "0");
      progressBar.setAttribute("aria-valuemax", "100");
      progressBar.setAttribute("aria-valuenow", String(Math.round(bounded)));
    } else {
      progressBarFill.style.removeProperty("width");
      progressBar.removeAttribute("role");
      progressBar.removeAttribute("aria-valuemin");
      progressBar.removeAttribute("aria-valuemax");
      progressBar.removeAttribute("aria-valuenow");
    }
  };

  const startProgress = () => {
    progress.hidden = false;
    progress.classList.remove("is-complete");
    cancelJobButton.hidden = false;
    cancelJobButton.disabled = false;
    jobMeta.textContent = "Wysyłanie pliku…";
    setProgressValue(null);
    showProgressStage(0);
  };

  const renderJobProgress = (job) => {
    const stageIndex = JOB_STAGE_INDEX[job.stage] ?? JOB_STAGE_INDEX[job.status] ?? 1;
    const completed = job.status === "completed";
    showProgressStage(stageIndex, completed);
    setProgressValue(job.progressPercent);
    progress.classList.toggle("is-complete", completed);
    const details = [`Czas: ${Number(job.elapsedSeconds || 0).toLocaleString("pl-PL")} s`];
    if (Number.isInteger(job.queuePosition) && job.queuePosition > 0) details.push(`Pozycja w kolejce: ${job.queuePosition}`);
    if (job.processedAudioSeconds !== null && Number.isFinite(Number(job.processedAudioSeconds))) {
      details.push(`Przetworzono: ${formatVoiceJournalDuration(job.processedAudioSeconds)}`);
    }
    if (job.status !== "completed") details.push(formatVoiceJournalEta(job.eta));
    details.push(`${job.model} · ${String(job.device || "").toUpperCase()}`);
    jobMeta.textContent = details.join(" · ");
  };

  const setBusy = (nextBusy) => {
    busy = nextBusy;
    addButton.disabled = nextBusy;
    fileInput.disabled = nextBusy;
    saveSettingsButton.disabled = nextBusy;
    restoreSettingsButton.disabled = nextBusy;
    configurableInputs.forEach((input) => {
      input.disabled = nextBusy || (input.tagName === "SELECT" && input.options.length < 2);
    });
    syncSettingsCompatibility();
    updateTranscribeAvailability();
  };

  const makeEditField = (labelText, control) => {
    const label = createElement("label", "voice-journal-entry-edit-field");
    label.append(createElement("span", "", labelText), control);
    return label;
  };

  const retranscribeEntryWithConfidence = async (entry, onProgress = () => {}) => {
    const engine = entry.engine || "openai-whisper";
    const engineHealth = voiceJournalEngineHealth(health || {}, engine);
    if (!engineHealth?.available) throw new Error("Wybrany silnik transkrypcji nie jest dostępny.");
    if (!engineHealth.transcriptionOptions?.supported?.includes("word_timestamps")) {
      throw new Error("Ten silnik nie obsługuje timestampów słów.");
    }
    onProgress("Pobieram lokalne audio…");
    const audioResponse = await fetchAudio(entry.audioUrl);
    if (!audioResponse?.ok) throw new Error("Nie udało się odczytać lokalnego pliku audio.");
    const blob = await audioResponse.blob();
    const file = new File([blob], entry.originalFilename || `voice-journal-${entry.id}.webm`, {
      type: entry.mimeType || blob.type || "application/octet-stream",
    });
    const capabilities = engineHealth.transcriptionOptions || {};
    const transcriptionOptions = {
      ...presetTranscriptionSettings(capabilities, capabilities.recommendedPreset || "balanced"),
      word_timestamps: true,
    };
    onProgress("Dodaję ponowną analizę do kolejki…");
    let job = await createJob({
      file,
      engine,
      model: entry.model,
      language: entry.language || "pl",
      task: "transcribe",
      device: entry.device || "auto",
      computeType: "auto",
      transcriptionOptions,
      allowModelDownload: false,
    });
    while (!TERMINAL_JOB_STATUSES.has(job.status)) {
      onProgress(`Analiza: ${job.stage || job.status} · ${Number(job.elapsedSeconds || 0).toLocaleString("pl-PL")} s`);
      await waitForPoll(pollInterval);
      job = await getJob(job.id);
    }
    if (job.status !== "completed") throw new Error(job.error || "Ponowna analiza nie powiodła się.");
    const result = await getJobResult(job.id);
    const history = [
      ...(Array.isArray(entry.correctionHistory) ? entry.correctionHistory : []),
      {
        at: new Date().toISOString(),
        operation: "retranscribe_with_word_confidence",
        targetId: entry.id,
        segmentId: null,
        previousValue: "bez danych słów",
        newValue: `${result.transcriptionData?.segments?.length || 0} segmentów z danymi słów`,
      },
    ];
    onProgress("Zapisuję timestampy i confidence…");
    return updateEntry(entry.id, {
      transcriptionData: result.transcriptionData || {
        version: 1,
        engine,
        segments: result.transcriptSegments || [],
      },
      correctionHistory: history,
    });
  };

  const renderEntryCard = (entry) => {
    const article = createElement("article", "voice-journal-entry");
    article.dataset.entryId = entry.id;
    const entryTitle = voiceJournalEntryTitle(entry);
    const head = createElement("div", "voice-journal-entry-head");
    const heading = createElement("div", "voice-journal-entry-heading");
    heading.append(
      createElement("strong", "voice-journal-entry-title", entryTitle),
      createElement("span", "", new Date(entry.recordedAt).toLocaleString("pl-PL")),
    );
    const category = createElement("span", "voice-journal-entry-category", CATEGORY_LABELS[entry.entryCategory] || entry.entryCategory);
    const publicationBadge = createElement("span", "voice-journal-entry-published", "W Dzienniku");
    const collapseButton = createElement("button", "voice-journal-entry-action voice-journal-entry-toggle");
    collapseButton.type = "button";
    const headActions = createElement("div", "voice-journal-entry-head-actions");
    headActions.append(category, publicationBadge, collapseButton);
    head.append(heading, headActions);

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = entry.audioUrl;
    audio.setAttribute("aria-label", `Nagranie: ${entryTitle}`);

    const transcriptWorkbench = createElement("div", "voice-journal-transcript-workbench voice-journal-entry-workbench");
    transcriptWorkbench.id = `voice-journal-entry-workbench-${entry.id}`;
    const dirtyPane = createElement("section", "voice-journal-transcript-pane");
    const dirtyHead = createElement("div", "voice-journal-transcript-pane-head");
    dirtyHead.append(
      createElement("strong", "", "Dirty + timestampy"),
      createElement("span", "", "Uwzględnia zapisaną korektę · kliknij czas, aby przewinąć audio"),
    );
    const dirtyPreview = createElement("div", "voice-journal-transcript-segments");
    dirtyPreview.id = `voice-journal-entry-dirty-${entry.id}`;
    renderTimestampedTranscript(
      dirtyPreview,
      correctionAwareSegments(entry),
      entry.rawTranscript || entry.transcript || "Brak transkrypcji.",
      audio,
    );
    dirtyPane.append(dirtyHead, dirtyPreview);

    const organizedPane = createElement("section", "voice-journal-transcript-pane");
    const organizedHead = createElement("div", "voice-journal-transcript-pane-head");
    organizedHead.append(
      createElement("strong", "", "Wersja uporządkowana"),
      createElement("span", "", "Publikowany tekst nie zawiera timestampów"),
    );
    const organizedInput = document.createElement("textarea");
    organizedInput.className = "voice-journal-entry-organized";
    organizedInput.id = `voice-journal-entry-transcript-${entry.id}`;
    organizedInput.rows = 12;
    organizedInput.spellcheck = true;
    let persistedOrganizedText = stripVoiceJournalTimestamps(entry.transcript || entry.rawTranscript || "");
    organizedInput.value = persistedOrganizedText;
    organizedInput.setAttribute("aria-label", "Wersja uporządkowana transkrypcji");
    const organizedActions = createElement("div", "voice-journal-organized-actions");
    const saveOrganizedButton = createElement("button", "voice-journal-primary", "Zapisz wersję uporządkowaną");
    saveOrganizedButton.type = "button";
    saveOrganizedButton.disabled = true;
    const publishOrganizedButton = createElement("button", "voice-journal-entry-action voice-journal-publish-action", "Opublikuj w Dzienniku");
    publishOrganizedButton.type = "button";
    publishOrganizedButton.disabled = !organizedInput.value.trim();
    const organizedStatus = createElement("span", "voice-journal-organized-status");
    organizedStatus.setAttribute("aria-live", "polite");
    organizedActions.append(saveOrganizedButton, publishOrganizedButton, organizedStatus);
    organizedPane.append(organizedHead, organizedInput, organizedActions);
    transcriptWorkbench.append(dirtyPane, organizedPane);

    organizedInput.addEventListener("input", () => {
      const hasUnsavedChanges = organizedInput.value.trim() !== persistedOrganizedText;
      saveOrganizedButton.disabled = !hasUnsavedChanges;
      publishOrganizedButton.disabled = hasUnsavedChanges || !organizedInput.value.trim();
      organizedStatus.textContent = "";
    });
    saveOrganizedButton.addEventListener("click", async () => {
      saveOrganizedButton.disabled = true;
      organizedStatus.textContent = "Zapisuję…";
      try {
        const cleanTranscript = stripVoiceJournalTimestamps(organizedInput.value);
        const updated = await updateEntry(entry.id, { transcript: cleanTranscript });
        entry.transcript = stripVoiceJournalTimestamps(updated?.transcript ?? cleanTranscript);
        persistedOrganizedText = entry.transcript;
        organizedInput.value = persistedOrganizedText;
        publishOrganizedButton.disabled = !entry.transcript;
        organizedStatus.textContent = "Zapisano.";
      } catch (error) {
        organizedStatus.textContent = error?.message || "Nie udało się zapisać.";
        saveOrganizedButton.disabled = false;
      }
    });
    publishOrganizedButton.addEventListener("click", async () => {
      if (!entry.transcript?.trim()) return;
      publishOrganizedButton.disabled = true;
      organizedStatus.textContent = "Publikowanie w Dzienniku…";
      try {
        const publication = await publishEntry(entry.id);
        setPublicationDisplay(publication || { publishedAt: new Date().toISOString() });
        organizedStatus.textContent = "Opublikowano w Dzienniku. Ponowna publikacja zaktualizuje ten sam wpis.";
        setEntryExpanded(false);
        collapseButton.focus();
      } catch (error) {
        organizedStatus.textContent = error?.message || "Nie udało się opublikować wpisu.";
      } finally {
        publishOrganizedButton.disabled = false;
      }
    });
    const tags = createElement("div", "voice-journal-entry-tags");
    (entry.tags || []).forEach((tag) => tags.append(createElement("span", "", tag)));
    const technical = createElement(
      "div",
      "voice-journal-entry-technical",
      `${entry.originalFilename} · ${formatVoiceJournalDuration(entry.durationSeconds)} · ${entry.engine || "openai-whisper"} / ${entry.model} · ${String(entry.device || "").toUpperCase()} · RTF ${Number(entry.realTimeFactor || 0).toLocaleString("pl-PL")}`,
    );

    const actions = createElement("div", "voice-journal-entry-actions");
    const expandButton = createElement("button", "voice-journal-entry-action", "Rozwiń tekst");
    expandButton.type = "button";
    const transcriptLength = Math.max(
      String(entry.rawTranscript || "").length,
      String(entry.transcript || "").length,
    );
    expandButton.hidden = transcriptLength <= 220;
    expandButton.setAttribute("aria-expanded", "false");
    expandButton.setAttribute("aria-controls", transcriptWorkbench.id);
    expandButton.addEventListener("click", () => {
      const expanded = transcriptWorkbench.classList.toggle("is-expanded");
      dirtyPreview.classList.toggle("is-expanded", expanded);
      expandButton.textContent = expanded ? "Zwiń tekst" : "Rozwiń tekst";
      expandButton.setAttribute("aria-expanded", String(expanded));
    });
    const editButton = createElement("button", "voice-journal-entry-action", "Edytuj");
    editButton.type = "button";
    editButton.setAttribute("aria-label", `Edytuj wpis: ${entryTitle}`);
    const deleteButton = createElement("button", "voice-journal-entry-action is-danger", "Usuń");
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", `Usuń wpis: ${entryTitle}`);
    actions.append(expandButton, editButton, deleteButton);

    const editForm = createElement("form", "voice-journal-entry-edit");
    editForm.id = `voice-journal-entry-edit-${entry.id}`;
    editForm.hidden = true;
    const titleInput = document.createElement("input");
    titleInput.name = "title";
    titleInput.maxLength = 120;
    titleInput.value = entryTitle;
    const local = entryLocalDateTime(entry.recordedAt);
    const dateInput = document.createElement("input");
    dateInput.name = "date";
    dateInput.type = "date";
    dateInput.value = local.date;
    const timeInput = document.createElement("input");
    timeInput.name = "time";
    timeInput.type = "time";
    timeInput.value = local.time;
    const categorySelect = document.createElement("select");
    categorySelect.name = "entryCategory";
    Object.entries(CATEGORY_LABELS).forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      categorySelect.append(option);
    });
    categorySelect.value = entry.entryCategory;
    const tagsInput = document.createElement("input");
    tagsInput.name = "tags";
    tagsInput.maxLength = 240;
    tagsInput.value = (entry.tags || []).join(", ");
    const editFields = createElement("div", "voice-journal-entry-edit-grid");
    editFields.append(
      makeEditField("Tytuł", titleInput),
      makeEditField("Data", dateInput),
      makeEditField("Godzina", timeInput),
      makeEditField("Typ", categorySelect),
      makeEditField("Tagi", tagsInput),
    );
    const editActions = createElement("div", "voice-journal-entry-edit-actions");
    const updateButton = createElement("button", "voice-journal-primary", "Zapisz zmiany");
    updateButton.type = "submit";
    const cancelButton = createElement("button", "voice-journal-entry-action", "Anuluj");
    cancelButton.type = "button";
    editActions.append(updateButton, cancelButton);
    editForm.append(editFields, editActions);

    editButton.setAttribute("aria-expanded", "false");
    editButton.setAttribute("aria-controls", editForm.id);
    const closeEditForm = () => {
      editForm.hidden = true;
      editButton.setAttribute("aria-expanded", "false");
      editButton.focus();
    };
    editButton.addEventListener("click", () => {
      editForm.hidden = false;
      editButton.setAttribute("aria-expanded", "true");
      titleInput.focus();
    });
    cancelButton.addEventListener("click", closeEditForm);
    editForm.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeEditForm();
      }
    });
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const recordedAt = recordedAtFromInputs(dateInput.value, timeInput.value);
      if (!recordedAt) {
        showListMessage("Nieprawidłowa data wpisu.", "error");
        return;
      }
      updateButton.disabled = true;
      try {
        const patch = {
          title: titleInput.value.trim(),
          entryCategory: categorySelect.value,
          tags: splitTags(tagsInput.value),
        };
        if (dateInput.value !== local.date || timeInput.value !== local.time) {
          patch.recordedAt = recordedAt;
        }
        await updateEntry(entry.id, patch);
        await loadEntries();
      } catch (error) {
        showListMessage(error?.message || "Nie udało się zaktualizować wpisu.", "error");
      } finally {
        updateButton.disabled = false;
      }
    });
    deleteButton.addEventListener("click", async () => {
      if (!confirmAction(`Usunąć wpis „${entryTitle}” wraz z jego transkrypcją? Tej operacji nie można cofnąć.`)) return;
      const deleteAudio = confirmAction("Czy usunąć także lokalny plik audio? Wybierz „Anuluj”, aby zachować nagranie na dysku.");
      deleteButton.disabled = true;
      try {
        await removeEntry(entry.id, { deleteAudio });
        await loadEntries();
        showListMessage(deleteAudio
          ? "Wpis i audio zostały usunięte."
          : "Wpis usunięty; plik audio pozostawiono na dysku.", "success");
      } catch (error) {
        showListMessage(error?.message || "Nie udało się usunąć wpisu.", "error");
        deleteButton.disabled = false;
      }
    });

    const correctionEditor = createVoiceJournalCorrectionEditor(entry, {
      updateEntry,
      confirmAction,
      retranscribeEntry: retranscribeEntryWithConfidence,
      onTranscriptChange: ({ transcript: correctedText, transcriptionData }) => {
        entry.transcriptionData = transcriptionData;
        entry.transcript = stripVoiceJournalTimestamps(correctedText);
        persistedOrganizedText = entry.transcript;
        organizedInput.value = persistedOrganizedText;
        saveOrganizedButton.disabled = true;
        publishOrganizedButton.disabled = !persistedOrganizedText;
        organizedStatus.textContent = "Zaktualizowano po korekcie.";
        const correctedSegments = correctionAwareSegments(entry);
        renderTimestampedTranscript(
          dirtyPreview,
          correctedSegments,
          entry.transcript || "Brak transkrypcji.",
          audio,
        );
      },
    });
    const content = createElement("div", "voice-journal-entry-content");
    content.id = `voice-journal-entry-content-${entry.id}`;
    content.append(audio, transcriptWorkbench, correctionEditor, tags, technical, actions, editForm);
    collapseButton.setAttribute("aria-controls", content.id);

    const setEntryExpanded = (expanded) => {
      content.hidden = !expanded;
      article.classList.toggle("is-collapsed", !expanded);
      collapseButton.textContent = expanded ? "Zwiń wpis" : "Rozwiń wpis";
      collapseButton.setAttribute("aria-expanded", String(expanded));
    };
    const setPublicationDisplay = (publication) => {
      entry.journalPublication = publication || null;
      const published = Boolean(entry.journalPublication);
      article.classList.toggle("is-published", published);
      publicationBadge.hidden = !published;
      if (!published) {
        publicationBadge.removeAttribute("title");
        return;
      }
      const publishedAt = entry.journalPublication.publishedAt;
      publicationBadge.title = publishedAt
        ? `Opublikowano w Dzienniku: ${new Date(publishedAt).toLocaleString("pl-PL")}`
        : "Opublikowano w Dzienniku";
    };
    collapseButton.addEventListener("click", () => {
      setEntryExpanded(collapseButton.getAttribute("aria-expanded") !== "true");
    });

    setPublicationDisplay(entry.journalPublication);
    setEntryExpanded(false);
    article.append(head, content);
    return article;
  };

  const currentEntryFilters = () => ({
    query: filterQuery.value,
    dateFrom: filterFrom.value,
    dateTo: filterTo.value,
    entryCategory: filterCategory.value,
    tag: filterTag.value,
    model: filterModel.value,
    sort: filterSort.value,
  });

  const replaceFilterOptions = (select, values) => {
    const previous = select.value;
    const first = select.options[0]?.cloneNode(true) || document.createElement("option");
    first.value = "";
    first.textContent = "Wszystkie";
    select.replaceChildren(first, ...values.map((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      return option;
    }));
    select.value = values.includes(previous) ? previous : "";
  };

  const updateEntryFilterOptions = () => {
    const options = voiceJournalFilterOptions(entries);
    replaceFilterOptions(filterTag, options.tags);
    replaceFilterOptions(filterModel, options.models);
  };

  const setEntryFiltersDisabled = (disabled) => {
    entryFilterControls.forEach((control) => { control.disabled = disabled; });
  };

  const renderEntries = () => {
    const filters = currentEntryFilters();
    const invalidDateRange = Boolean(filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo);
    filterTo.setCustomValidity(invalidDateRange ? "Data końcowa nie może być wcześniejsza niż początkowa." : "");
    const visibleEntries = invalidDateRange ? [] : filterVoiceJournalEntries(entries, filters);
    entryCount.textContent = visibleEntries.length === entries.length
      ? String(entries.length)
      : `${visibleEntries.length}/${entries.length}`;
    entryList.replaceChildren(...visibleEntries.map(renderEntryCard));
    emptyEntries.hidden = visibleEntries.length > 0;
    emptyResetButton.hidden = !hasActiveVoiceJournalFilters(filters);
    if (!entries.length) {
      emptyTitle.textContent = "Brak zapisanych wpisów";
      emptyDescription.textContent = "Dodaj pierwsze nagranie, aby rozpocząć dziennik głosowy.";
    } else if (invalidDateRange) {
      emptyTitle.textContent = "Nieprawidłowy zakres dat";
      emptyDescription.textContent = "Data końcowa nie może być wcześniejsza niż początkowa.";
    } else if (!visibleEntries.length) {
      emptyTitle.textContent = "Brak pasujących wpisów";
      emptyDescription.textContent = "Zmień kryteria wyszukiwania lub wyczyść filtry.";
    }
    setEntryFiltersDisabled(entriesLoading || entries.length === 0);
  };

  const resetEntryFilters = ({ focus = true } = {}) => {
    filterQuery.value = "";
    filterFrom.value = "";
    filterTo.value = "";
    filterCategory.value = "";
    filterTag.value = "";
    filterModel.value = "";
    filterSort.value = "newest";
    renderEntries();
    if (focus) filterQuery.focus();
  };

  const loadEntries = async () => {
    entriesLoading = true;
    refreshButton.disabled = true;
    setEntryFiltersDisabled(true);
    entryList.setAttribute("aria-busy", "true");
    listStatus.hidden = false;
    listStatus.dataset.kind = "loading";
    listStatusText.textContent = entries.length ? "Odświeżanie wpisów…" : "Ładowanie wpisów…";
    listRetryButton.hidden = true;
    try {
      entries = await fetchEntries();
      updateEntryFilterOptions();
      renderEntries();
      listStatus.hidden = true;
    } catch (error) {
      listStatus.dataset.kind = "error";
      listStatusText.textContent = error?.message || "Nie udało się pobrać wpisów. Sprawdź połączenie z lokalnym backendem.";
      listRetryButton.hidden = false;
      if (!entries.length) {
        entryList.replaceChildren();
        emptyEntries.hidden = true;
      }
    } finally {
      entriesLoading = false;
      entryList.removeAttribute("aria-busy");
      refreshButton.disabled = false;
      setEntryFiltersDisabled(entries.length === 0);
    }
  };

  refreshButton.addEventListener("click", loadEntries);
  listRetryButton.addEventListener("click", loadEntries);
  filtersForm.addEventListener("submit", (event) => event.preventDefault());
  filtersForm.addEventListener("input", renderEntries);
  filtersForm.addEventListener("change", renderEntries);
  filtersForm.addEventListener("reset", (event) => {
    event.preventDefault();
    resetEntryFilters();
  });
  emptyResetButton.addEventListener("click", () => resetEntryFilters());
  filterQuery.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && filterQuery.value) {
      event.preventDefault();
      filterQuery.value = "";
      renderEntries();
    }
  });

  const selectFile = async (file) => {
    const token = ++selectionToken;
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
    latestResult = null;
    progress.hidden = true;
    resultSection.hidden = true;
    clearPlayerUrl();
    workspace.hidden = false;
    root.querySelector("#voice-journal-file-name").textContent = file.name;
    root.querySelector("#voice-journal-title-input").value = file.name;
    root.querySelector("#voice-journal-file-size").textContent = formatVoiceJournalBytes(file.size);
    root.querySelector("#voice-journal-file-format").textContent = extension.toUpperCase();
    root.querySelector("#voice-journal-file-duration").textContent = "Odczytuję…";
    const detected = detectedFileDateTime(file);
    detectedDateTime = {
      ...detected,
      source: Number(file.lastModified) > 0 ? "file_modified" : "upload_time",
    };
    root.querySelector("#voice-journal-date").value = detected.date;
    root.querySelector("#voice-journal-time").value = detected.time;
    saveStatus.textContent = "";
    dropzone.classList.add("has-file");
    setStatus(`Wybrano ${file.name}.`, "ok");
    updateTranscribeAvailability();

    const metadata = await metadataReader(file).catch(() => ({ durationSeconds: null }));
    if (token !== selectionToken) return false;
    root.querySelector("#voice-journal-file-duration").textContent = formatVoiceJournalDuration(metadata?.durationSeconds);
    return true;
  };

  addButton.addEventListener("click", () => {
    fileInput.value = "";
    fileInput.click();
  });
  fileInput.addEventListener("change", () => selectFile(fileInput.files?.[0]));
  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (!busy) dropzone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("is-dragging");
    });
  });
  dropzone.addEventListener("drop", (event) => {
    if (busy) return;
    const files = event.dataTransfer?.files;
    if (files?.length !== 1) {
      setStatus("Upuść dokładnie jeden plik audio.", "error");
      return;
    }
    selectFile(files[0]);
  });
  dropzone.addEventListener("click", () => { if (!busy) fileInput.click(); });
  dropzone.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && !busy) {
      event.preventDefault();
      fileInput.click();
    }
  });
  engineSelect.addEventListener("change", () => renderEngineConfiguration());
  modelSelect.addEventListener("change", updateTranscribeAvailability);
  deviceSelect.addEventListener("change", () => renderEngineConfiguration({ preserveModel: true }));
  deviceSelect.addEventListener("change", updateSettingsPreview);

  cancelJobButton.addEventListener("click", async () => {
    cancelJobButton.disabled = true;
    cancelJobButton.textContent = "Anulowanie…";
    if (!activeJobId) {
      activeUploadController?.abort();
      return;
    }
    try {
      const job = await cancelJob(activeJobId);
      renderJobProgress(job);
      setStatus("Anulowanie transkrypcji…", "working");
    } catch (error) {
      cancelJobButton.disabled = false;
      cancelJobButton.textContent = "Anuluj";
      setStatus(error?.message || "Nie udało się anulować zadania.", "error");
    }
  });

  transcribeButton.addEventListener("click", async () => {
    const selectedEngine = engineSelect.value || "openai-whisper";
    const selectedEngineHealth = voiceJournalEngineHealth(health || {}, selectedEngine) || {};
    const actualModel = resolveVoiceJournalModel(modelSelect.value, health || {}, selectedEngine);
    if (!selectedFile || !actualModel || busy) return;
    const modelCached = Array.isArray(selectedEngineHealth.cachedModels) && selectedEngineHealth.cachedModels.includes(actualModel);
    let allowModelDownload = false;
    if (!modelCached) {
      allowModelDownload = confirmAction(
        `Model Whisper „${actualModel}” nie jest jeszcze zapisany lokalnie i może wymagać pobrania dużego pliku. Pobrać go teraz i kontynuować?`,
      );
      if (!allowModelDownload) {
        setStatus("Pobieranie modelu anulowane. Wybierz model zapisany w cache albo potwierdź pobranie.", "");
        return;
      }
    }
    let transcriptionOptions;
    try {
      transcriptionOptions = readRawTranscriptionSettings();
    } catch (error) {
      settingsSection.open = true;
      settingsStatus.textContent = error?.message || "Sprawdź ustawienia transkrypcji.";
      return;
    }
    setBusy(true);
    resultSection.hidden = true;
    startProgress();
    setStatus(
      allowModelDownload
        ? `Wysyłam nagranie; model ${actualModel} zostanie pobrany po stronie lokalnego backendu…`
        : "Wysyłam nagranie do lokalnego backendu…",
      "working",
    );
    const token = ++transcriptionToken;
    activeJobId = null;
    activeUploadController = new AbortController();
    try {
      let job = await createJob({
        file: selectedFile,
        engine: selectedEngine,
        model: actualModel,
        language: languageSelect.value,
        task: taskSelect.value,
        device: deviceSelect.value,
        computeType: computeTypeSelect.value || "auto",
        transcriptionOptions,
        allowModelDownload,
      }, {
        signal: activeUploadController.signal,
        onUploadProgress: ({ percent }) => {
          if (token !== transcriptionToken) return;
          setProgressValue(percent);
          jobMeta.textContent = `Wysłano ${Math.round(percent)}%`;
        },
      });
      if (token !== transcriptionToken) return;
      activeJobId = job.id;
      renderJobProgress(job);
      while (!TERMINAL_JOB_STATUSES.has(job.status)) {
        await waitForPoll(pollInterval);
        if (token !== transcriptionToken) return;
        job = await getJob(activeJobId);
        renderJobProgress(job);
      }
      if (job.status !== "completed") {
        const error = new Error(job.error || (job.status === "cancelled" ? "Transkrypcja została anulowana." : "Transkrypcja została przerwana."));
        error.jobStatus = job.status;
        throw error;
      }
      latestResult = await getJobResult(activeJobId);
      showProgressStage(5, true);
      setProgressValue(100);
      progress.classList.add("is-complete");
      transcript.value = organizeVoiceJournalTranscript(
        latestResult.transcriptSegments,
        latestResult.transcript,
      );
      renderTimestampedTranscript(
        rawResultTranscript,
        latestResult.transcriptSegments,
        latestResult.transcript,
        player,
      );
      resultMeta.replaceChildren(...[
        `Silnik: ${latestResult.engine || "openai-whisper"}`,
        `Model: ${latestResult.model}`,
        `Urządzenie: ${String(latestResult.device || "").toUpperCase()}`,
        `Czas: ${Number(latestResult.transcriptionDurationSeconds || 0).toLocaleString("pl-PL")} s`,
        `RTF: ${Number(latestResult.realTimeFactor || 0).toLocaleString("pl-PL")}`,
      ].map((text) => {
        const span = document.createElement("span");
        span.textContent = text;
        return span;
      }));
      root.querySelector("#voice-journal-file-format").textContent = latestResult.format || audioFileExtension(selectedFile).toUpperCase();
      root.querySelector("#voice-journal-file-duration").textContent = formatVoiceJournalDuration(latestResult.durationSeconds);
      if (typeof URL?.createObjectURL === "function") {
        playerUrl = URL.createObjectURL(selectedFile);
        player.src = playerUrl;
      }
      resultSection.hidden = false;
      saveButton.disabled = false;
      transcribeButton.textContent = "Transkrybuj ponownie";
      setStatus("Transkrypcja gotowa.", "ok");
    } catch (error) {
      if (error?.name === "AbortError" || error?.jobStatus === "cancelled") {
        setStatus("Transkrypcja została anulowana.", "");
      } else {
        setStatus(error?.message || "Nie udało się wykonać transkrypcji.", "error");
      }
    } finally {
      if (token === transcriptionToken) {
        activeJobId = null;
        activeUploadController = null;
        cancelJobButton.hidden = true;
        cancelJobButton.disabled = false;
        cancelJobButton.textContent = "Anuluj";
        setBusy(false);
      }
    }
  });

  saveButton.addEventListener("click", async () => {
    if (!latestResult || !selectedFile) return;
    const date = root.querySelector("#voice-journal-date").value;
    const time = root.querySelector("#voice-journal-time").value;
    const recordedAt = recordedAtFromInputs(date, time);
    if (!recordedAt) {
      saveStatus.textContent = "Uzupełnij prawidłową datę i godzinę.";
      return;
    }
    const entry = {
      title: root.querySelector("#voice-journal-title-input").value.trim() || selectedFile.name,
      entryCategory: root.querySelector("#voice-journal-type").value,
      recordedAt,
      dateSource: detectedDateTime && detectedDateTime.date === date && detectedDateTime.time === time
        ? detectedDateTime.source
        : "user_corrected",
      tags: splitTags(root.querySelector("#voice-journal-tags").value),
      transcript: transcript.value.trim(),
      rawTranscript: latestResult.transcript || "",
      transcriptSegments: Array.isArray(latestResult.transcriptSegments) ? latestResult.transcriptSegments : [],
      transcriptionData: latestResult.transcriptionData || {
        version: 1,
        engine: latestResult.engine || "openai-whisper",
        segments: latestResult.transcriptSegments || [],
      },
      correctionHistory: [],
      correctionSettings: {},
      language: languageSelect.value,
      engine: latestResult.engine || "openai-whisper",
      model: latestResult.model,
      device: latestResult.device,
      transcriptionDurationSeconds: latestResult.transcriptionDurationSeconds,
      realTimeFactor: latestResult.realTimeFactor,
    };
    saveButton.disabled = true;
    saveStatus.textContent = "Zapisuję wpis i audio…";
    try {
      await createEntry({ file: selectedFile, entry });
      await loadEntries();
      saveStatus.textContent = "Wpis i audio zapisane lokalnie.";
    } catch (error) {
      saveStatus.textContent = error?.message || "Nie udało się zapisać wpisu.";
      saveButton.disabled = false;
    }
  });

  try {
    health = await fetchHealth();
    const engines = voiceJournalEngines(health);
    engineSelect.replaceChildren(...engines.map((engine) => {
      const option = document.createElement("option");
      option.value = engine.id;
      option.textContent = engine.label || engine.id;
      option.disabled = engine.available === false;
      option.title = engine.available === false ? (engine.error || "Silnik niedostępny") : "";
      return option;
    }));
    engineSelect.value = health.defaultEngine || "openai-whisper";
    const options = availableVoiceJournalOptions(health, engineSelect.value);
    setSelectOptions(languageSelect, options.languages, { auto: "Auto", pl: "Polski" });
    setSelectOptions(taskSelect, options.tasks, { transcribe: "Transcribe", translate: "Translate" });
    setSelectOptions(deviceSelect, options.devices, { auto: "Auto", cpu: "CPU", cuda: "CUDA" });
    if (options.languages.includes("pl")) languageSelect.value = "pl";
    if (options.tasks.includes("transcribe")) taskSelect.value = "transcribe";
    if (options.devices.includes("auto")) deviceSelect.value = "auto";
    renderEngineConfiguration();
    backendReady = health.status === "ok"
      && options.supportedModels.length > 0
      && options.languages.length > 0
      && options.tasks.length > 0
      && options.devices.length > 0;
    backendPill.textContent = backendReady ? "Backend OK" : "Backend niedostępny";
    backendPill.dataset.kind = backendReady ? "ok" : "error";
    const uploadLimits = health.maxUploadBytes && health.maxDurationSeconds
      ? ` Limit pliku: ${formatVoiceJournalBytes(health.maxUploadBytes)} i ${Math.round(health.maxDurationSeconds / 60)} min.`
      : "";
    setStatus(
      backendReady
        ? `Whisper ${health.whisperVersion}; w cache: ${options.cachedModels.join(", ") || "brak"}; dostępne: ${options.supportedModels.join(", ")}.${uploadLimits}`
        : (health.errors?.join("; ") || "Brak lokalnego modelu Whispera."),
      backendReady ? "ok" : "error",
    );
  } catch (error) {
    backendReady = false;
    [modelSelect, languageSelect, taskSelect, deviceSelect].forEach((select) => { select.disabled = true; });
    backendPill.textContent = "Backend offline";
    backendPill.dataset.kind = "error";
    setStatus(error?.message || "Nie można połączyć się z backendem.", "error");
  }
  updateTranscribeAvailability();
  await loadEntries();

  const dispose = () => {
    transcriptionToken += 1;
    activeUploadController?.abort();
    clearPlayerUrl();
  };
  window.addEventListener("pagehide", dispose, { once: true });
  return { selectFile, loadEntries, dispose };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("voice-journal-root");
  if (root && root.dataset.voiceJournalMode !== "compact") initVoiceJournalWidget(root);
}
