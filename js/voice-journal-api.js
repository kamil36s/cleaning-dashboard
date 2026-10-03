const HEALTH_URL = "/api/voice-journal/health";
const TRANSCRIBE_URL = "/api/voice-journal/transcribe";
const ENTRIES_URL = "/api/voice-journal/entries";
const JOBS_URL = "/api/voice-journal/jobs";

async function readJsonResponse(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || response.statusText || "Voice journal API error");
    error.code = payload.code || "api_error";
    error.status = response.status;
    throw error;
  }
  return payload;
}

export async function fetchVoiceJournalHealth(fetchImpl = fetch) {
  const response = await fetchImpl(HEALTH_URL, { cache: "no-store" });
  return readJsonResponse(response);
}

export async function transcribeVoiceJournal({
  file,
  model,
  language = "pl",
  task = "transcribe",
  device = "auto",
} = {}, fetchImpl = fetch) {
  if (!(file instanceof Blob)) throw new TypeError("Audio file is required");
  if (!model) throw new TypeError("Whisper model is required");

  const form = new FormData();
  form.append("file", file, file.name || "recording.webm");
  form.append("model", model);
  form.append("language", language);
  form.append("task", task);
  form.append("device", device);

  const response = await fetchImpl(TRANSCRIBE_URL, {
    method: "POST",
    body: form,
  });
  return readJsonResponse(response);
}

export function createVoiceJournalJob({
  file,
  engine = "openai-whisper",
  model,
  language = "pl",
  task = "transcribe",
  device = "auto",
  computeType = "auto",
  transcriptionOptions = {},
  allowModelDownload = false,
} = {}, options = {}) {
  if (!(file instanceof Blob)) return Promise.reject(new TypeError("Audio file is required"));
  if (!model) return Promise.reject(new TypeError("Whisper model is required"));
  const xhrFactory = options.xhrFactory || (() => new XMLHttpRequest());
  const form = new FormData();
  form.append("file", file, file.name || "recording.webm");
  form.append("engine", engine);
  form.append("model", model);
  form.append("language", language);
  form.append("task", task);
  form.append("device", device);
  form.append("computeType", computeType);
  form.append("options", JSON.stringify(transcriptionOptions));
  form.append("allowModelDownload", allowModelDownload ? "true" : "false");

  return new Promise((resolve, reject) => {
    const xhr = xhrFactory();
    const abort = () => xhr.abort();
    const rejectFromPayload = () => {
      let payload = {};
      try { payload = JSON.parse(xhr.responseText || "{}"); } catch { /* invalid error body */ }
      const error = new Error(payload.error || xhr.statusText || "Voice journal API error");
      error.code = payload.code || "api_error";
      error.status = xhr.status;
      reject(error);
    };
    xhr.open("POST", JOBS_URL);
    xhr.responseType = "text";
    xhr.upload?.addEventListener("progress", (event) => {
      if (!event.lengthComputable || !event.total) return;
      options.onUploadProgress?.({
        loaded: event.loaded,
        total: event.total,
        percent: Math.min(100, (event.loaded / event.total) * 100),
      });
    });
    xhr.addEventListener("load", () => {
      options.signal?.removeEventListener("abort", abort);
      if (xhr.status < 200 || xhr.status >= 300) {
        rejectFromPayload();
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText || "{}"));
      } catch {
        reject(new Error("Backend returned invalid JSON"));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Could not connect to the voice journal backend")));
    xhr.addEventListener("abort", () => {
      const error = new Error("Upload cancelled");
      error.name = "AbortError";
      reject(error);
    });
    if (options.signal?.aborted) {
      const error = new Error("Upload cancelled");
      error.name = "AbortError";
      reject(error);
      return;
    }
    options.signal?.addEventListener("abort", abort, { once: true });
    xhr.send(form);
  });
}

export async function fetchVoiceJournalJob(id, fetchImpl = fetch) {
  const response = await fetchImpl(`${JOBS_URL}/${encodeURIComponent(id)}`, { cache: "no-store" });
  return readJsonResponse(response);
}

export async function cancelVoiceJournalJob(id, fetchImpl = fetch) {
  const response = await fetchImpl(`${JOBS_URL}/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  return readJsonResponse(response);
}

export async function fetchVoiceJournalJobResult(id, fetchImpl = fetch) {
  const response = await fetchImpl(`${JOBS_URL}/${encodeURIComponent(id)}/result`, { cache: "no-store" });
  return readJsonResponse(response);
}

export async function fetchVoiceJournalEntries(fetchImpl = fetch) {
  const response = await fetchImpl(ENTRIES_URL, { cache: "no-store" });
  const payload = await readJsonResponse(response);
  return Array.isArray(payload.entries) ? payload.entries : [];
}

export async function createVoiceJournalEntry({ file, entry } = {}, fetchImpl = fetch) {
  if (!(file instanceof Blob)) throw new TypeError("Audio file is required");
  if (!entry || typeof entry !== "object") throw new TypeError("Entry metadata is required");
  const form = new FormData();
  form.append("entry", JSON.stringify(entry));
  form.append("file", file, file.name || "recording.webm");
  const response = await fetchImpl(ENTRIES_URL, { method: "POST", body: form });
  return readJsonResponse(response);
}

export async function updateVoiceJournalEntry(id, patch, fetchImpl = fetch) {
  const response = await fetchImpl(`${ENTRIES_URL}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return readJsonResponse(response);
}

export async function deleteVoiceJournalEntry(id, { deleteAudio = false } = {}, fetchImpl = fetch) {
  const response = await fetchImpl(
    `${ENTRIES_URL}/${encodeURIComponent(id)}?deleteAudio=${deleteAudio ? "true" : "false"}`,
    { method: "DELETE" },
  );
  return readJsonResponse(response);
}

export function voiceJournalEngines(health = {}) {
  if (Array.isArray(health.engines) && health.engines.length) return health.engines;
  return [{
    id: "openai-whisper",
    label: "OpenAI Whisper (dotychczasowy)",
    available: health.status === "ok" || Boolean(health.whisperVersion),
    supportedModels: health.supportedModels || [],
    cachedModels: health.cachedModels || [],
    recommendedModel: health.recommendedModel,
    supportedLanguages: health.supportedLanguages || [],
    supportedTasks: health.supportedTasks || [],
    transcriptionOptions: health.transcriptionOptions || {},
    computeTypes: [],
  }];
}

export function voiceJournalEngineHealth(health = {}, engine = "openai-whisper") {
  return voiceJournalEngines(health).find((item) => item.id === engine) || null;
}

export function availableVoiceJournalOptions(health = {}, engine = "openai-whisper") {
  const engineHealth = voiceJournalEngineHealth(health, engine) || {};
  const supportedModels = Array.isArray(engineHealth.supportedModels)
    ? engineHealth.supportedModels
    : [];
  const cachedModels = Array.isArray(engineHealth.cachedModels)
    ? engineHealth.cachedModels
    : [];
  const languages = Array.isArray(engineHealth.supportedLanguages)
    ? engineHealth.supportedLanguages.filter((language) => ["auto", "pl"].includes(language))
    : [];
  const tasks = Array.isArray(engineHealth.supportedTasks)
    ? engineHealth.supportedTasks.filter((task) => ["transcribe", "translate"].includes(task))
    : [];
  const devices = Array.isArray(health.supportedDevices)
    ? health.supportedDevices.filter((device) => ["auto", "cpu", "cuda"].includes(device))
    : [];

  return {
    models: supportedModels.length ? ["auto", ...supportedModels] : (cachedModels.length ? ["auto", ...cachedModels] : []),
    supportedModels: supportedModels.length ? supportedModels : cachedModels,
    cachedModels,
    languages,
    tasks,
    devices,
    computeTypes: Array.isArray(engineHealth.computeTypes) ? engineHealth.computeTypes : [],
    available: engineHealth.available !== false,
    diagnostic: engineHealth.error || "",
  };
}

export function resolveVoiceJournalModel(selection, health = {}, engine = "openai-whisper") {
  const engineHealth = voiceJournalEngineHealth(health, engine) || {};
  const supportedModels = Array.isArray(engineHealth.supportedModels) ? engineHealth.supportedModels : [];
  const cachedModels = Array.isArray(engineHealth.cachedModels) ? engineHealth.cachedModels : [];
  if (selection && selection !== "auto") return supportedModels.includes(selection) || cachedModels.includes(selection) ? selection : null;
  if (cachedModels.includes(engineHealth.recommendedModel)) return engineHealth.recommendedModel;
  return cachedModels[0] || (supportedModels.includes(engineHealth.recommendedModel) ? engineHealth.recommendedModel : supportedModels[0]) || null;
}
