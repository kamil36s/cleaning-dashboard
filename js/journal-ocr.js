import {
  activateHtrModel,
  archiveHtrModel,
  cancelHtrModelTraining,
  cancelHtrJob,
  createHtrDataset,
  deleteHtrModel,
  deleteHtrPage,
  exportHtrToJournal,
  fetchHtrDatasetStats,
  fetchHtrDatasets,
  fetchHtrJobs,
  fetchHtrLines,
  fetchHtrModels,
  fetchHtrPages,
  fetchHtrProjects,
  fetchHtrStatus,
  mergeHtrLines,
  preprocessHtrPage,
  rotateHtrPage,
  reorderHtrPages,
  startHtrSegmentation,
  startHtrTraining,
  startHtrTranscription,
  syncHtrProvider,
  updateHtrLine,
  uploadHtrPages,
} from "./journal-htr-api.js";
import {
  expandPolygon,
  geometryBounds,
  linePolygon,
  paddedCrop,
  selectedIndex,
  sourceBoundsToNatural,
  sourceToDisplayTransform,
  transformPoints,
} from "./journal-htr-geometry.js";
import { shouldRenderCorrectionAfterRefresh } from "./journal-htr-editor-state.js";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const state = {
  status: null,
  projects: [],
  pages: [],
  lines: [],
  datasets: [],
  models: [],
  jobs: [],
  datasetStats: null,
  selectedPages: new Set(),
  selectedLineId: null,
  showOriginal: false,
  unsavedLine: false,
  trainingOverride: false,
  pendingFiles: [],
  geometryView: null,
  drawMode: false,
  drawStart: null,
  perspectiveMode: false,
  perspectivePoints: [],
};

function setMessage(message = "", tone = "") {
  const element = $("#htr-message");
  element.textContent = message;
  element.className = `htr-status-message${tone ? ` is-${tone}` : ""}`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("pl-PL");
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pl-PL");
}

function pageStatusLabel(status) {
  return {
    uploaded: "Wgrane — czeka na segmentację",
    segmenting: "Wykrywanie linii…",
    segmented: "Linie gotowe — uruchom transkrypcję",
    transcribing: "Rozpoznawanie tekstu…",
    transcribed: "Tekst gotowy — sprawdź korektę",
    reviewed: "Sprawdzone i zatwierdzone",
    failed: "Błąd przetwarzania",
  }[status] || status;
}

function serviceLabel(name) {
  return {
    dashboardBackend: "Backend",
    escriptorium: "eScriptorium",
    krakenWorker: "Kraken",
    database: "Baza",
    storage: "Pliki",
  }[name] || name;
}

function jobErrorLabel(error) {
  if (error === "Choose a provider recognition model") {
    return "Wybrany model nie był jeszcze gotowy w eScriptorium.";
  }
  return error || "";
}

function modelStatusLabel(status) {
  return ({
    queued: "oczekuje w kolejce",
    training: "trening trwa",
    ready: "gotowy",
    active: "aktywny",
    evaluated: "oceniony",
    failed: "nieudany",
    cancelled: "anulowany",
    archived: "zarchiwizowany",
  })[status] || status;
}

function jobStatusLabel(status) {
  return ({
    pending: "oczekuje",
    running: "w toku",
    completed: "ukończone",
    failed: "nieudane",
    cancelled: "anulowane",
  })[status] || status;
}

function renderStatus() {
  const status = state.status;
  if (!status) return;
  const stats = status.stats || {};
  $("#htr-stat-pages").textContent = formatNumber(stats.totalPages);
  $("#htr-stat-lines").textContent = formatNumber(stats.approvedTrainingLines);
  $("#htr-stat-jobs").textContent = formatNumber(stats.runningJobs);
  $("#htr-stat-model").textContent = stats.activeModelVersion || "brak";

  $("#htr-service-strip").innerHTML = Object.entries(status.services || {}).map(([name, service]) => `
    <span class="htr-service-pill ${service.online ? "is-online" : "is-offline"}">
      ${escapeHtml(serviceLabel(name))}: ${service.online ? "online" : "offline"}
    </span>
  `).join("");

  $("#htr-diagnostics").innerHTML = Object.entries(status.services || {}).map(([name, service]) => `
    <div class="htr-diagnostic">
      <strong>${escapeHtml(serviceLabel(name))}</strong>
      <span class="htr-status-pill ${service.online ? "is-completed" : "is-failed"}">${service.online ? "Działa" : "Wymaga uwagi"}</span>
      <small>${escapeHtml(service.error || service.version || service.path || (service.freeBytes ? `${Math.round(service.freeBytes / 1024 / 1024 / 1024)} GB wolne` : ""))}</small>
    </div>
  `).join("") + `
    <div class="htr-diagnostic">
      <strong>Aktywne modele</strong>
      <span>Recognition: ${escapeHtml(stats.activeRecognitionModel?.name || "brak")}</span>
      <small>Segmentation: ${escapeHtml(stats.activeSegmentationModel?.name || "domyślny eScriptorium")}</small>
    </div>
  `;

  const next = status.nextStep || {};
  $("#htr-next-title").textContent = next.title || "Brak następnego kroku";
  $("#htr-next-description").textContent = next.description || "";
  $("#htr-next-action").textContent = next.actionLabel || "Otwórz";
  $("#htr-next-action").href = next.actionUrl || "#configuration";
  updateStepper();
}

function updateStepper() {
  if (!state.status) return;
  const stats = state.status.stats || {};
  const servicesReady = state.status.enabled && state.status.services?.escriptorium?.online;
  const hasPages = Number(stats.totalPages) > 0;
  const segmentationRunning = state.pages.some((page) => page.status === "segmenting");
  const hasSegmented = state.pages.some((page) => ["segmented", "transcribing", "transcribed", "reviewed"].includes(page.status));
  const transcriptionRunning = state.pages.some((page) => page.status === "transcribing");
  const hasRecognizedText = state.pages.some((page) => ["transcribed", "reviewed"].includes(page.status));
  const hasLines = state.lines.length > 0;
  const hasDataset = state.datasets.length > 0;
  const hasTraining = state.jobs.some((job) => job.type === "training");
  const hasModels = state.models.some((model) => !model.id.startsWith("external-"));
  const exportable = Number(stats.exportablePages) > 0;
  const statuses = {
    configuration: servicesReady ? "completed" : "blocked",
    upload: hasPages ? "completed" : (servicesReady ? "ready" : "blocked"),
    segmentation: segmentationRunning ? "in_progress" : (hasSegmented ? "completed" : (hasPages ? "ready" : "not_started")),
    transcription: transcriptionRunning ? "in_progress" : (hasRecognizedText ? "completed" : (hasSegmented ? "ready" : "not_started")),
    correction: Number(stats.unreviewedLines) && hasRecognizedText ? "needs_attention" : (hasRecognizedText && hasLines ? "completed" : "not_started"),
    dataset: hasDataset ? "completed" : (Number(stats.approvedTrainingLines) ? "ready" : "not_started"),
    training: hasTraining ? "in_progress" : (hasDataset ? "ready" : "not_started"),
    models: hasModels ? "ready" : "not_started",
    export: exportable ? "ready" : "not_started",
  };
  $$("#htr-stepper a").forEach((link) => {
    const stepStatus = statuses[link.dataset.step] || "not_started";
    link.dataset.status = stepStatus;
    $("em", link).textContent = stepStatus;
  });
}

function pageImageUrl(page, variant = "thumbnail") {
  if (page.mimeType === "application/pdf") return "";
  return `/api/journal-htr/pages/${encodeURIComponent(page.id)}/file?variant=${variant}&v=${encodeURIComponent(page.updatedAt || "")}`;
}

function renderPages() {
  const root = $("#htr-page-list");
  if (!state.pages.length) {
    root.innerHTML = `<div class="htr-callout"><strong>Brak stron.</strong><p>Dodaj pierwsze zdjęcia lub PDF powyżej.</p></div>`;
    return;
  }
  root.innerHTML = state.pages.map((page) => `
    <div class="htr-page-row" data-page-id="${escapeHtml(page.id)}">
      <input type="checkbox" data-select-page aria-label="Zaznacz ${escapeHtml(page.originalFilename)}" ${state.selectedPages.has(page.id) ? "checked" : ""}>
      ${pageImageUrl(page) ? `<img loading="lazy" src="${pageImageUrl(page)}" alt="">` : `<span aria-hidden="true">PDF</span>`}
      <div><strong>${escapeHtml(page.originalFilename)}</strong><br><small>${escapeHtml(page.projectName || "")} · str. ${page.pageNumber || page.pageOrder + 1}</small></div>
      <span class="htr-status-pill is-${escapeHtml(page.status)}">${escapeHtml(pageStatusLabel(page.status))}</span>
      <span>${escapeHtml(page.language)} · ${escapeHtml(page.datePrecision)}</span>
      <div class="htr-page-actions">
        <button class="htr-button" type="button" data-page-action="rotate" ${page.mimeType === "application/pdf" ? "disabled title=\"Niedostępne dla PDF\"" : ""}>Obróć 90°</button>
        <button class="htr-button" type="button" data-page-action="up">↑</button>
        <button class="htr-button" type="button" data-page-action="down">↓</button>
        <button class="htr-button" type="button" data-page-action="delete">Usuń</button>
      </div>
    </div>
  `).join("");
}

function renderUploadPreview(files) {
  state.pendingFiles = [...files];
  $("#htr-upload-preview").innerHTML = state.pendingFiles.map((file, index) =>
    `<span>${escapeHtml(file.name)} · ${(file.size / 1024 / 1024).toFixed(1)} MB
      <button type="button" data-file-action="up" data-file-index="${index}" ${index === 0 ? "disabled" : ""}>↑</button>
      <button type="button" data-file-action="down" data-file-index="${index}" ${index === state.pendingFiles.length - 1 ? "disabled" : ""}>↓</button>
      <button type="button" data-file-action="remove" data-file-index="${index}">×</button>
    </span>`
  ).join("");
}

function renderDataset() {
  const stats = state.datasetStats || {};
  $("#htr-dataset-stats").innerHTML = [
    ["Linie", stats.lines],
    ["Znaki", stats.characters],
    ["Strony", stats.approvedPages],
    ["Cyfry", stats.digits],
    ["Interpunkcja", stats.punctuation],
    ["Niepewne", stats.uncertain],
  ].map(([label, value]) => `<div class="htr-dataset-stat"><strong>${formatNumber(value)}</strong><span>${label}</span></div>`).join("");
  if (stats.polishCharacters) {
    $("#htr-dataset-stats").insertAdjacentHTML("beforeend", `
      <div class="htr-dataset-stat"><strong>${Object.entries(stats.polishCharacters).map(([char, count]) => `${char}:${count}`).join(" ")}</strong><span>Polskie znaki</span></div>
    `);
  }
  $("#htr-dataset-list").innerHTML = state.datasets.length
    ? state.datasets.map((dataset) => `
        <div class="htr-dataset-row">
          <strong>${escapeHtml(dataset.name)} @ ${dataset.version}</strong>
          <span>${dataset.lineCount} linii</span>
          <span>${dataset.characterCount} znaków</span>
          <span>${dataset.split.train.length}/${dataset.split.validation.length}/${dataset.split.test.length} stron</span>
        </div>
      `).join("")
    : `<p class="htr-muted">Nie utworzono jeszcze wersji datasetu.</p>`;
  $("#htr-training-dataset").innerHTML = state.datasets.length
    ? state.datasets.map((dataset) => `<option value="${escapeHtml(dataset.id)}">${escapeHtml(dataset.name)} @ ${dataset.version}</option>`).join("")
    : `<option value="">Najpierw utwórz dataset</option>`;
}

function renderModels() {
  const visibleModels = state.models.filter((model) => model.status !== "archived");
  const recognition = visibleModels.filter((model) => model.type === "recognition");
  const usableRecognition = recognition
    .filter((model) =>
      model.externalModelId
      && ["ready", "evaluated", "active"].includes(model.status)
      && !model.provider?.training
    )
    .sort((first, second) => Number(second.isActive) - Number(first.isActive));
  const waitingRecognition = recognition.filter((model) => !usableRecognition.includes(model));
  $("#htr-recognition-model").innerHTML = usableRecognition.length
    ? `${usableRecognition.map((model) => `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)} · ${escapeHtml(model.version)}${model.isActive ? " · aktywny" : ""}</option>`).join("")}
       ${waitingRecognition.length ? `<optgroup label="Jeszcze niedostępne">${waitingRecognition.map((model) =>
         `<option value="" disabled>${escapeHtml(model.name)} · ${["queued", "training"].includes(model.status) ? modelStatusLabel(model.status) : "brak synchronizacji"}</option>`
       ).join("")}</optgroup>` : ""}`
    : `<option value="">Brak gotowego modelu</option>${waitingRecognition.map((model) =>
        `<option value="" disabled>${escapeHtml(model.name)} · ${["queued", "training"].includes(model.status) ? modelStatusLabel(model.status) : "brak synchronizacji"}</option>`
      ).join("")}`;
  $("#htr-transcribe-pending").disabled = !usableRecognition.length;
  $("#htr-transcribe-selected").disabled = !usableRecognition.length;
  const usableBaseModels = visibleModels.filter((model) =>
    model.externalModelId
    && ["ready", "evaluated", "active"].includes(model.status)
    && !model.provider?.training
  );
  $("#htr-base-model").innerHTML = `<option value="">Brak modelu bazowego</option>${usableBaseModels.map((model) =>
    `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)} · ${escapeHtml(model.type)}</option>`
  ).join("")}`;
  $("#htr-filter-model").innerHTML = `<option value="">Wszystkie modele</option>${visibleModels.map((model) =>
    `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)}</option>`
  ).join("")}`;
  $("#htr-model-list").innerHTML = state.models.length
    ? state.models.map((model) => `
        <div class="htr-model" data-model-id="${escapeHtml(model.id)}">
      <div><strong>${escapeHtml(model.name)} ${escapeHtml(model.version)}</strong><br><small>${escapeHtml(model.type)} · ${escapeHtml(modelStatusLabel(model.status))}</small></div>
          <span>CER: ${model.testCer == null ? "brak oceny" : Number(model.testCer).toFixed(4)}</span>
          <span>WER: ${model.testWer == null ? "brak oceny" : Number(model.testWer).toFixed(4)}</span>
          <div class="htr-page-actions">
            <button class="htr-button" data-model-action="activate" type="button" ${model.isActive || !model.externalModelId || model.provider?.training || !["ready", "evaluated", "active"].includes(model.status) ? "disabled" : ""}>${model.isActive ? "Aktywny" : (model.status === "training" ? "Trening trwa" : "Aktywuj")}</button>
            <button class="htr-button" data-model-action="cancel-training" type="button" ${["queued", "training"].includes(model.status) ? "" : "disabled"}>Anuluj trening</button>
            <button class="htr-button" data-model-action="archive" type="button" ${model.isActive || ["queued", "training", "archived"].includes(model.status) ? "disabled" : ""}>${model.status === "archived" ? "Zarchiwizowany" : "Archiwizuj"}</button>
            <button class="htr-button htr-button-danger" data-model-action="delete" type="button" ${model.isActive || model.status === "training" ? "disabled" : ""}>Usuń</button>
          </div>
        </div>
      `).join("")
    : `<p class="htr-muted">Brak modeli. Zaimportuj model bazowy w eScriptorium i użyj „Synchronizuj”.</p>`;
}

function renderReviewFilters() {
  const currentProject = $("#htr-filter-project").value;
  $("#htr-filter-project").innerHTML = `<option value="">Wszystkie zeszyty</option>${state.projects.map((project) =>
    `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`
  ).join("")}`;
  $("#htr-filter-project").value = currentProject;
}

function renderJobs() {
  $("#htr-job-list").innerHTML = state.jobs.length
    ? state.jobs.map((job) => `
        <div class="htr-job" data-job-id="${escapeHtml(job.id)}">
          <div><strong>${escapeHtml(job.type)}</strong><br><small>${escapeHtml(job.stage)} · ${formatDate(job.createdAt)}${job.error ? ` · ${escapeHtml(jobErrorLabel(job.error))}` : ""}</small></div>
          <span class="htr-status-pill is-${escapeHtml(job.status)}">${escapeHtml(jobStatusLabel(job.status))}</span>
          <span class="htr-progress"><i style="width:${Number(job.progress) || 0}%"></i></span>
          <button class="htr-button" data-job-action="cancel" type="button" ${["completed", "failed", "cancelled"].includes(job.status) ? "disabled" : ""}>Anuluj</button>
        </div>
      `).join("")
    : `<p class="htr-muted">Brak zadań.</p>`;
}

function currentLine() {
  return state.lines.find((line) => line.id === state.selectedLineId) || state.lines[0] || null;
}

function currentLineIndex() {
  return selectedIndex(state.lines, state.selectedLineId);
}

function ensureSelectedLine() {
  const line = currentLine();
  state.selectedLineId = line?.id || null;
  return line;
}

function lineSourceSize(line, page, image) {
  const coordinateSpace = line?.geometry?.coordinateSpace || {};
  const segmented = page?.imageInfo?.segmentation || page?.processing?.segmentationImage || {};
  return {
    width: Number(coordinateSpace.width || segmented.width || page?.imageInfo?.working?.width || image.naturalWidth),
    height: Number(coordinateSpace.height || segmented.height || page?.imageInfo?.working?.height || image.naturalHeight),
  };
}

function renderGeometryDiagnostics(details) {
  const panel = $("#htr-geometry-diagnostics");
  if (!panel) return;
  panel.textContent = JSON.stringify(details, null, 2);
  panel.closest("details")?.classList.toggle(
    "is-mismatch",
    details.selectedLineIdLeft !== details.selectedLineIdCrop
      || details.selectedLineIdLeft !== details.selectedLineIdTranscription
  );
}

function drawCrop(image, crop, lineId) {
  const canvas = $("#htr-editor-line-image");
  if (!(canvas instanceof HTMLCanvasElement) || !crop || !image.complete) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    image,
    crop.x,
    crop.y,
    crop.width,
    crop.height,
    0,
    0,
    canvas.width,
    canvas.height
  );
  canvas.dataset.lineId = lineId;
}

function renderCorrection() {
  const queue = $("#htr-review-queue");
  const line = ensureSelectedLine();
  const index = currentLineIndex();
  $("#htr-review-progress").textContent = `${index >= 0 ? index + 1 : 0} / ${state.lines.length}`;
  queue.innerHTML = state.lines.map((item) => `
    <button class="htr-queue-line ${item.id === state.selectedLineId ? "is-active" : ""}" type="button" data-line-id="${escapeHtml(item.id)}">
      ln ${item.lineOrder + 1}. ${escapeHtml(item.displayText || "(pusta linia)")} · ${item.confidence == null ? "?" : `${Math.round(item.confidence * 100)}%`}
    </button>
  `).join("");
  if (!line) {
    $("#htr-line-text").value = "";
    $("#htr-line-text").disabled = true;
    $("#htr-use-training").disabled = true;
    $("#htr-line-meta").textContent = "Brak linii dla wybranych filtrów.";
    $("#htr-editor-page").removeAttribute("src");
    const crop = $("#htr-editor-line-image");
    crop?.getContext?.("2d")?.clearRect(0, 0, crop.width, crop.height);
    $("#htr-line-highlight").replaceChildren();
    return;
  }
  $("#htr-line-text").disabled = false;
  $("#htr-use-training").disabled = false;
  $("#htr-line-text").value = line.displayText || "";
  $("#htr-use-training").checked = Boolean(line.useForTraining);
  $("#htr-line-meta").textContent = `Status: ${line.reviewStatus} · pewność: ${line.confidence == null ? "brak" : `${Math.round(line.confidence * 100)}%`} · język: ${line.language}`;
  const page = state.pages.find((item) => item.id === line.pageId);
  if (page && page.mimeType !== "application/pdf") {
    const workingWasTransformed = Boolean(
      page.processing?.rotation
      || page.processing?.transformRevision
      || page.processing?.deskewAngle
      || page.processing?.perspectiveCorners
    );
    const variant = state.showOriginal && !workingWasTransformed ? "original" : "working";
    const source = pageImageUrl(page, variant);
    const image = $("#htr-editor-page");
    image.dataset.lineId = line.id;
    image.dataset.pageId = page.id;
    if (image.getAttribute("src") !== source) image.src = source;
    const bounds = geometryBounds(line);
    const highlight = $("#htr-line-highlight");
    const applyGeometry = () => {
      if (state.selectedLineId !== line.id || image.dataset.lineId !== line.id) return;
      const polygon = linePolygon(line);
      if (!bounds || !polygon.length || !image.naturalWidth || !image.naturalHeight) {
        highlight.replaceChildren();
        return;
      }
      const pageCanvas = $(".htr-page-canvas");
      const canvasRect = pageCanvas.getBoundingClientRect();
      const imageRect = image.getBoundingClientRect();
      const sourceSize = lineSourceSize(line, page, image);
      const transform = sourceToDisplayTransform({
        sourceWidth: sourceSize.width,
        sourceHeight: sourceSize.height,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
        imageBox: {
          left: imageRect.left - canvasRect.left,
          top: imageRect.top - canvasRect.top,
          width: imageRect.width,
          height: imageRect.height,
        },
      });
      const displayPolygon = transformPoints(polygon, transform);
      const displayBaseline = transformPoints(line.geometry?.baseline || [], transform);
      highlight.setAttribute("viewBox", `0 0 ${canvasRect.width} ${canvasRect.height}`);
      highlight.innerHTML = `
        <polygon data-line-id="${escapeHtml(line.id)}" points="${displayPolygon.map((point) => point.join(",")).join(" ")}"></polygon>
        <polyline points="${displayBaseline.map((point) => point.join(",")).join(" ")}"></polyline>
      `;
      const naturalBounds = sourceBoundsToNatural(bounds, sourceSize, {
        width: image.naturalWidth,
        height: image.naturalHeight,
      });
      const crop = paddedCrop(naturalBounds, image.naturalWidth, image.naturalHeight);
      drawCrop(image, crop, line.id);
      state.geometryView = { lineId: line.id, pageId: page.id, sourceSize, transform, crop };
      renderGeometryDiagnostics({
        lineId: line.id,
        lineOrder: line.lineOrder,
        currentIndex: index,
        sourceImageWidth: sourceSize.width,
        sourceImageHeight: sourceSize.height,
        displayedImageWidth: transform.displayedWidth,
        displayedImageHeight: transform.displayedHeight,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
        polygon,
        baseline: line.geometry?.baseline || [],
        calculatedBoundingBox: bounds,
        scaleX: transform.scaleX,
        scaleY: transform.scaleY,
        renderOffsetX: transform.offsetX,
        renderOffsetY: transform.offsetY,
        cropCoordinates: crop,
        devicePixelRatio: window.devicePixelRatio || 1,
        selectedLineIdLeft: highlight.querySelector("polygon")?.dataset.lineId || null,
        selectedLineIdCrop: $("#htr-editor-line-image").dataset.lineId || null,
        selectedLineIdTranscription: line.id,
      });
    };
    image.onload = applyGeometry;
    if (image.complete) applyGeometry();
  }
  state.unsavedLine = false;
  state.trainingOverride = false;
}

async function refreshAll({ health = false } = {}) {
  const [status, projects, pages, lines, stats, datasets, models, jobs] = await Promise.all([
    fetchHtrStatus(health),
    fetchHtrProjects(),
    fetchHtrPages(),
    fetchHtrLines(),
    fetchHtrDatasetStats(),
    fetchHtrDatasets(),
    fetchHtrModels(),
    fetchHtrJobs(),
  ]);
  Object.assign(state, {
    status,
    projects: projects.projects || [],
    pages: pages.pages || [],
    lines: lines.lines || [],
    datasetStats: stats,
    datasets: datasets.datasets || [],
    models: models.models || [],
    jobs: jobs.jobs || [],
  });
  state.selectedPages = new Set([...state.selectedPages].filter((id) => state.pages.some((page) => page.id === id)));
  if (!state.lines.some((line) => line.id === state.selectedLineId)) {
    state.selectedLineId = state.lines[0]?.id || null;
  }
  renderStatus();
  renderPages();
  renderDataset();
  renderModels();
  renderReviewFilters();
  renderJobs();
  // Status modeli i zadań odświeża się co kilka sekund. Nigdy nie wolno przy
  // tym rerenderować pola, w którym użytkownik ma niezapisany tekst.
  if (shouldRenderCorrectionAfterRefresh(state)) {
    renderCorrection();
  }
}

async function applyLineFilters() {
  if (state.unsavedLine && !confirm("Masz niezapisaną korektę. Odrzucić ją i zmienić filtr?")) return;
  const filters = {
    status: $("#htr-filter-status").value,
    language: $("#htr-filter-language").value,
    useForTraining: $("#htr-filter-training").value,
    projectId: $("#htr-filter-project").value,
    modelId: $("#htr-filter-model").value,
    dateFrom: $("#htr-filter-date-from").value,
    dateTo: $("#htr-filter-date-to").value,
    segmentationIssue: $("#htr-filter-segmentation").checked ? "true" : "",
  };
  state.lines = (await fetchHtrLines(filters)).lines || [];
  if (!state.lines.some((line) => line.id === state.selectedLineId)) {
    state.selectedLineId = state.lines[0]?.id || null;
  }
  renderCorrection();
}

async function saveLine(reviewStatus, moveNext = false) {
  const line = currentLine();
  if (!line) return;
  const updated = await updateHtrLine(line.id, {
    correctedText: $("#htr-line-text").value,
    reviewStatus,
    useForTraining: state.trainingOverride
      ? $("#htr-use-training").checked
      : ["approved", "corrected"].includes(reviewStatus),
  });
  const index = currentLineIndex();
  state.lines[index] = { ...line, ...updated };
  state.unsavedLine = false;
  if (moveNext && index < state.lines.length - 1) {
    state.selectedLineId = state.lines[index + 1].id;
  }
  renderCorrection();
  setMessage("Korekta została zapisana i wersjonowana.", "success");
}

function moveLine(offset) {
  if (!state.lines.length) return;
  if (state.unsavedLine && !confirm("Masz niezapisaną korektę. Przejść dalej bez zapisu?")) return;
  const index = currentLineIndex();
  const target = Math.min(state.lines.length - 1, Math.max(0, index + offset));
  state.selectedLineId = state.lines[target].id;
  renderCorrection();
}

function selectedPageIds(predicate = () => true) {
  return [...state.selectedPages].filter((id) => predicate(state.pages.find((page) => page.id === id)));
}

async function handleAction(action, message) {
  setMessage(message);
  try {
    const result = await action();
    await refreshAll();
    setMessage("Operacja została przyjęta. Postęp jest widoczny w sekcji zadań.", "success");
    return result;
  } catch (error) {
    setMessage(`${error.message}${error.code ? ` (${error.code})` : ""}`, "error");
    throw error;
  }
}

function refreshGeometryView() {
  const image = $("#htr-editor-page");
  if (image?.complete && typeof image.onload === "function") image.onload();
}

async function replaceSelectedGeometry(geometry) {
  const line = currentLine();
  if (!line) return;
  const updated = await updateHtrLine(line.id, { geometry });
  const index = currentLineIndex();
  state.lines[index] = { ...line, ...updated };
  state.selectedLineId = updated.id;
  renderCorrection();
  setMessage("Geometria linii została zapisana.", "success");
}

function sourcePointFromPointer(event) {
  const view = state.geometryView;
  if (!view || view.lineId !== state.selectedLineId) return null;
  const rect = $(".htr-page-canvas").getBoundingClientRect();
  return [
    Math.max(0, Math.min(view.sourceSize.width, (event.clientX - rect.left - view.transform.offsetX) / view.transform.scaleX)),
    Math.max(0, Math.min(view.sourceSize.height, (event.clientY - rect.top - view.transform.offsetY) / view.transform.scaleY)),
  ];
}

function setDrawMode(active) {
  if (active) setPerspectiveMode(false);
  state.drawMode = active;
  state.drawStart = null;
  $(".htr-page-canvas").classList.toggle("is-drawing", active);
  $("#htr-draw-line").classList.toggle("is-primary", active);
  $("#htr-draw-line").textContent = active ? "Przeciągnij wokół linii…" : "Narysuj całą linię";
}

function setPerspectiveMode(active) {
  state.perspectiveMode = active;
  state.perspectivePoints = [];
  if (active) {
    state.drawMode = false;
    state.drawStart = null;
    $("#htr-draw-line").classList.remove("is-primary");
    $("#htr-draw-line").textContent = "Narysuj całą linię";
  }
  $(".htr-page-canvas").classList.toggle("is-drawing", active || state.drawMode);
  $("#htr-perspective-page").classList.toggle("is-primary", active);
  $("#htr-perspective-page").textContent = active
    ? "Kliknij róg 1/4…"
    : "Perspektywa: wskaż 4 rogi";
}

function bindEvents() {
  $("#htr-open-help").addEventListener("click", () => $("#htr-help-dialog").showModal());
  $("#htr-refresh-health").addEventListener("click", () => handleAction(() => refreshAll({ health: true }), "Sprawdzam usługi…").catch(() => {}));
  $("#htr-sync").addEventListener("click", () => handleAction(syncHtrProvider, "Synchronizacja z eScriptorium…").catch(() => {}));

  const input = $("#htr-file-input");
  input.addEventListener("change", () => renderUploadPreview(input.files));
  $("#htr-upload-preview").addEventListener("click", (event) => {
    const button = event.target.closest("[data-file-action]");
    if (!button) return;
    const index = Number(button.dataset.fileIndex);
    if (button.dataset.fileAction === "remove") state.pendingFiles.splice(index, 1);
    if (button.dataset.fileAction === "up" && index > 0) {
      [state.pendingFiles[index - 1], state.pendingFiles[index]] = [state.pendingFiles[index], state.pendingFiles[index - 1]];
    }
    if (button.dataset.fileAction === "down" && index < state.pendingFiles.length - 1) {
      [state.pendingFiles[index + 1], state.pendingFiles[index]] = [state.pendingFiles[index], state.pendingFiles[index + 1]];
    }
    renderUploadPreview(state.pendingFiles);
  });
  const dropzone = $("#htr-dropzone");
  ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
  }));
  dropzone.addEventListener("drop", (event) => {
    if (event.dataTransfer?.files?.length) {
      renderUploadPreview(event.dataTransfer.files);
    }
  });
  $("#htr-upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.pendingFiles.length) {
      setMessage("Wybierz co najmniej jeden plik.", "error");
      return;
    }
    const formData = new FormData(event.currentTarget);
    state.pendingFiles.forEach((file) => formData.append("files", file, file.name));
    try {
      await handleAction(() => uploadHtrPages(formData), "Zapisuję oryginały i przygotowuję kopie robocze…");
      event.currentTarget.reset();
      renderUploadPreview([]);
    } catch {}
  });

  $("#htr-page-list").addEventListener("change", (event) => {
    const row = event.target.closest("[data-page-id]");
    if (!row || !event.target.matches("[data-select-page]")) return;
    if (event.target.checked) state.selectedPages.add(row.dataset.pageId);
    else state.selectedPages.delete(row.dataset.pageId);
  });
  $("#htr-page-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-page-action]");
    const row = event.target.closest("[data-page-id]");
    if (!button || !row) return;
    try {
      if (button.dataset.pageAction === "rotate") {
        await handleAction(() => rotateHtrPage(row.dataset.pageId, 90), "Obracam kopię roboczą…");
      } else if (["up", "down"].includes(button.dataset.pageAction)) {
        const page = state.pages.find((item) => item.id === row.dataset.pageId);
        const projectPages = state.pages.filter((item) => item.projectId === page.projectId).sort((a, b) => a.pageOrder - b.pageOrder);
        const index = projectPages.findIndex((item) => item.id === page.id);
        const target = button.dataset.pageAction === "up" ? index - 1 : index + 1;
        if (target < 0 || target >= projectPages.length) return;
        [projectPages[index], projectPages[target]] = [projectPages[target], projectPages[index]];
        await handleAction(() => reorderHtrPages(projectPages.map((item) => item.id)), "Zmieniam kolejność stron…");
      } else if (button.dataset.pageAction === "delete" && confirm("Trwale usunąć stronę, obrazy, linie i historię korekt?")) {
        await handleAction(() => deleteHtrPage(row.dataset.pageId), "Usuwam stronę…");
      }
    } catch {}
  });
  $("#htr-segment-selected").addEventListener("click", () => {
    const ids = selectedPageIds((page) => ["uploaded", "failed"].includes(page?.status));
    handleAction(() => startHtrSegmentation({ pageIds: ids }), "Kolejkuję segmentację…").catch(() => {});
  });
  $("#htr-segment-pending").addEventListener("click", () => {
    const ids = state.pages.filter((page) => ["uploaded", "failed"].includes(page.status)).map((page) => page.id);
    handleAction(() => startHtrSegmentation({ pageIds: ids }), "Kolejkuję segmentację wszystkich oczekujących stron…").catch(() => {});
  });
  $("#htr-transcribe-selected").addEventListener("click", () => {
    const modelId = $("#htr-recognition-model").value;
    const ids = selectedPageIds((page) => ["segmented", "transcribed", "failed"].includes(page?.status));
    handleAction(() => startHtrTranscription({ pageIds: ids, modelId }), "Kolejkuję transkrypcję…").catch(() => {});
  });
  $("#htr-transcribe-pending").addEventListener("click", () => {
    const modelId = $("#htr-recognition-model").value;
    const ids = state.pages.filter((page) => ["segmented", "failed"].includes(page.status)).map((page) => page.id);
    handleAction(() => startHtrTranscription({ pageIds: ids, modelId }), "Kolejkuję transkrypcję wszystkich oczekujących stron…").catch(() => {});
  });

  $("#htr-apply-filters").addEventListener("click", () => applyLineFilters().catch((error) => setMessage(error.message, "error")));
  $("#htr-review-queue").addEventListener("click", (event) => {
    const button = event.target.closest("[data-line-id]");
    if (!button) return;
    if (state.unsavedLine && !confirm("Odrzucić niezapisaną zmianę?")) return;
    state.selectedLineId = button.dataset.lineId;
    renderCorrection();
  });
  $("#htr-expand-line").addEventListener("click", () => {
    const line = currentLine();
    if (!line || !state.geometryView) return;
    const raw = prompt("O ile pikseli obrazu rozszerzyć polygon?", "40");
    if (raw === null) return;
    const amount = Math.max(1, Math.min(500, Number(raw) || 40));
    const polygon = expandPolygon(
      linePolygon(line),
      amount,
      state.geometryView.sourceSize.width,
      state.geometryView.sourceSize.height
    );
    replaceSelectedGeometry({ ...line.geometry, mask: polygon, manuallyEdited: true }).catch((error) =>
      setMessage(error.message, "error")
    );
  });
  $("#htr-merge-next-line").addEventListener("click", () => {
    const line = currentLine();
    if (!line) return;
    const other = state.lines
      .filter((item) => item.pageId === line.pageId && item.id !== line.id && item.lineOrder > line.lineOrder)
      .sort((a, b) => a.lineOrder - b.lineOrder)[0];
    if (!other) {
      setMessage("Na tej stronie nie ma następnego fragmentu.", "error");
      return;
    }
    if (!confirm(`Połączyć ln ${line.lineOrder + 1} z ln ${other.lineOrder + 1}? Drugi fragment zostanie oznaczony jako wykluczony.`)) return;
    mergeHtrLines(line.id, other.id)
      .then(async () => {
        state.selectedLineId = line.id;
        await refreshAll();
        setMessage("Fragmenty zostały połączone w jedną linię.", "success");
      })
      .catch((error) => setMessage(error.message, "error"));
  });
  $("#htr-draw-line").addEventListener("click", () => setDrawMode(!state.drawMode));
  $("#htr-deskew-page").addEventListener("click", () => {
    const line = currentLine();
    if (!line) return;
    const raw = prompt("Kąt pochylenia tekstu w stopniach (-20 do 20). Dodatnia wartość obraca obraz zgodnie z ruchem wskazówek.", "0");
    if (raw === null || !Number(raw)) return;
    if (!confirm("Kopia robocza zostanie zastąpiona, a dotychczasowa segmentacja tej strony unieważniona. Oryginał pozostanie bez zmian. Kontynuować?")) return;
    handleAction(
      () => preprocessHtrPage(line.pageId, { deskewAngle: Number(raw) }),
      "Koryguję pochylenie i przygotowuję ponowną segmentację…"
    ).catch(() => {});
  });
  $("#htr-perspective-page").addEventListener("click", () => {
    if (state.perspectiveMode) {
      setPerspectiveMode(false);
      refreshGeometryView();
      return;
    }
    if (!confirm("Po wskazaniu czterech rogów kopia robocza zostanie zastąpiona, a segmentacja tej strony wykonana od nowa. Oryginał pozostanie bez zmian. Kontynuować?")) return;
    setPerspectiveMode(true);
  });
  $("#htr-resegment-page").addEventListener("click", () => {
    const line = currentLine();
    if (!line) return;
    if (!confirm("Ponowna segmentacja zastąpi geometrię tej strony. Zrób to po deskew/korekcie perspektywy albo gdy obecny podział jest błędny. Kontynuować?")) return;
    handleAction(
      () => startHtrSegmentation({ pageIds: [line.pageId], replaceExisting: true }),
      "Uruchamiam ponowną segmentację strony…"
    ).catch(() => {});
  });
  const pageCanvas = $(".htr-page-canvas");
  pageCanvas.addEventListener("pointerdown", (event) => {
    if (state.perspectiveMode) {
      const point = sourcePointFromPointer(event);
      if (!point) return;
      state.perspectivePoints.push(point);
      const displayPoints = transformPoints(
        state.perspectivePoints,
        state.geometryView.transform
      );
      $("#htr-line-highlight").innerHTML = `
        ${displayPoints.length > 1 ? `<polyline points="${displayPoints.map((item) => item.join(",")).join(" ")}"></polyline>` : ""}
        ${displayPoints.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5"></circle>`).join("")}
      `;
      $("#htr-perspective-page").textContent = `Kliknij róg ${Math.min(4, state.perspectivePoints.length + 1)}/4…`;
      if (state.perspectivePoints.length === 4) {
        const line = currentLine();
        const corners = [...state.perspectivePoints];
        setPerspectiveMode(false);
        handleAction(
          () => preprocessHtrPage(line.pageId, { perspectiveCorners: corners }),
          "Koryguję perspektywę i przygotowuję ponowną segmentację…"
        ).catch(() => refreshGeometryView());
      }
      event.preventDefault();
      return;
    }
    if (!state.drawMode) return;
    const point = sourcePointFromPointer(event);
    if (!point) return;
    state.drawStart = point;
    pageCanvas.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  });
  pageCanvas.addEventListener("pointermove", (event) => {
    if (!state.drawMode || !state.drawStart) return;
    const point = sourcePointFromPointer(event);
    if (!point) return;
    const [x1, y1] = state.drawStart;
    const [x2, y2] = point;
    const preview = transformPoints(
      [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
      state.geometryView.transform
    );
    $("#htr-line-highlight").innerHTML = `<polygon data-line-id="${escapeHtml(state.selectedLineId)}" points="${preview.map((item) => item.join(",")).join(" ")}"></polygon>`;
  });
  pageCanvas.addEventListener("pointerup", (event) => {
    if (!state.drawMode || !state.drawStart) return;
    const end = sourcePointFromPointer(event);
    const start = state.drawStart;
    setDrawMode(false);
    if (!end || Math.abs(end[0] - start[0]) < 5 || Math.abs(end[1] - start[1]) < 5) {
      refreshGeometryView();
      return;
    }
    const x1 = Math.min(start[0], end[0]);
    const x2 = Math.max(start[0], end[0]);
    const y1 = Math.min(start[1], end[1]);
    const y2 = Math.max(start[1], end[1]);
    const line = currentLine();
    replaceSelectedGeometry({
      ...line.geometry,
      mask: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
      baseline: [[x1, y2 - (y2 - y1) * 0.25], [x2, y2 - (y2 - y1) * 0.25]],
      manuallyEdited: true,
    }).catch((error) => setMessage(error.message, "error"));
  });
  $("#htr-line-text").addEventListener("input", () => { state.unsavedLine = true; });
  $("#htr-use-training").addEventListener("change", () => {
    state.unsavedLine = true;
    state.trainingOverride = true;
  });
  $$(".htr-editor-actions [data-review-status]").forEach((button) => button.addEventListener("click", () =>
    saveLine(button.dataset.reviewStatus, ["approved", "corrected"].includes(button.dataset.reviewStatus)).catch((error) => setMessage(error.message, "error"))
  ));
  $("#htr-prev-line").addEventListener("click", () => moveLine(-1));
  $("#htr-next-line").addEventListener("click", () => moveLine(1));

  $("#htr-dataset-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const ratios = {
      train: Number(data.get("train")) / 100,
      validation: Number(data.get("validation")) / 100,
      test: Number(data.get("test")) / 100,
    };
    try {
      await handleAction(() => createHtrDataset({ name: data.get("name"), ratios }), "Tworzę deterministyczny podział według stron…");
    } catch {}
  });
  $("#htr-training-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await handleAction(() => startHtrTraining(data), "Kolejkuję trening…");
    } catch {}
  });
  $("#htr-job-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-job-action='cancel']");
    const row = event.target.closest("[data-job-id]");
    if (button && row) handleAction(() => cancelHtrJob(row.dataset.jobId), "Anuluję zadanie…").catch(() => {});
  });
  $("#htr-model-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-model-action]");
    const row = event.target.closest("[data-model-id]");
    if (!button || !row) return;
    if (
      button.dataset.modelAction === "delete"
      && !window.confirm("Usunąć ten model i powiązany wpis treningu? Tej operacji nie można cofnąć.")
    ) return;
    const action = button.dataset.modelAction === "activate"
      ? () => activateHtrModel(row.dataset.modelId)
      : button.dataset.modelAction === "cancel-training"
        ? () => cancelHtrModelTraining(row.dataset.modelId)
        : button.dataset.modelAction === "delete"
          ? () => deleteHtrModel(row.dataset.modelId)
          : () => archiveHtrModel(row.dataset.modelId);
    handleAction(action, "Aktualizuję model…").catch(() => {});
  });
  $("#htr-export-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    data.pageIds = selectedPageIds((page) => page?.status === "reviewed");
    if (data.entryDate) data.entryDate = new Date(data.entryDate).toISOString();
    try {
      const entry = await handleAction(() => exportHtrToJournal(data), "Tworzę wpis w dzienniku…");
      setMessage(`Utworzono wpis „${entry.title || "OCR dziennika"}”.`, "success");
    } catch {}
  });

  document.addEventListener("keydown", (event) => {
    if (!$("#correction").contains(document.activeElement)) return;
    const isText = document.activeElement === $("#htr-line-text");
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      saveLine($("#htr-line-text").value === currentLine()?.predictedText ? "approved" : "corrected", !event.ctrlKey).catch((error) => setMessage(error.message, "error"));
    } else if (event.key === "Tab") {
      event.preventDefault();
      moveLine(event.shiftKey ? -1 : 1);
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveLine($("#htr-line-text").value === currentLine()?.predictedText ? "approved" : "corrected").catch((error) => setMessage(error.message, "error"));
    } else if (event.altKey && event.key.toLowerCase() === "i") {
      event.preventDefault();
      saveLine("illegible", true).catch((error) => setMessage(error.message, "error"));
    } else if (event.altKey && event.key.toLowerCase() === "t") {
      event.preventDefault();
      $("#htr-use-training").checked = !$("#htr-use-training").checked;
      state.unsavedLine = true;
      state.trainingOverride = true;
    } else if (event.altKey && event.key.toLowerCase() === "o") {
      event.preventDefault();
      state.showOriginal = !state.showOriginal;
      renderCorrection();
    } else if (isText && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      // Preserve the browser's native textarea undo behavior.
    }
  });
  window.addEventListener("beforeunload", (event) => {
    if (!state.unsavedLine) return;
    event.preventDefault();
    event.returnValue = "";
  });
  window.addEventListener("resize", refreshGeometryView);
}

async function init() {
  bindEvents();
  try {
    await refreshAll({ health: true });
    if (location.hash) document.querySelector(location.hash)?.scrollIntoView();
  } catch (error) {
    setMessage(`Nie udało się uruchomić modułu: ${error.message}`, "error");
  }
  window.setInterval(async () => {
    const providerWorkInProgress = state.pages.some((page) => ["segmenting", "transcribing"].includes(page.status));
    const trainingInProgress = state.models.some((model) =>
      model.status === "training" || model.provider?.training
    );
    if (!providerWorkInProgress && !trainingInProgress && !state.jobs.some((job) => ["pending", "running"].includes(job.status))) return;
    try { await refreshAll(); } catch {}
  }, 3000);
}

init();
