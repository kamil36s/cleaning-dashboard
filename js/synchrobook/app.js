import * as api from "./api.js";
import { SynchrobookAudioPlayer } from "./audio-player.js";
import { createFullscreenIdleController, fullscreenSupported, syncFullscreenSidebarUi, syncFullscreenUi, toggleFullscreen, toggleFullscreenSidebar } from "./fullscreen.js";
import { currentPageAtTime, loadPageTotals, normalizeTotalPages, savePageTotals } from "./page-progress.js";
import { SynchrobookReader } from "./reader.js";
import { ReadingGuideController } from "./reading-guide/ui.js";
import { HIGHLIGHT_PRESETS, PRESETS, applySettings, loadSettings, saveSettings } from "./settings.js";
import { estimateQueueRemainingSeconds, formatQueueEstimate, formatRemaining, playbackRemainingTimes } from "./utils.js";

const $ = (id) => document.getElementById(id);
const elements = {
  library: $("synchrobook-library"), chapters: $("synchrobook-chapters"), reader: $("synchrobook-reader"),
  readerEmpty: $("synchrobook-reader-empty"), text: $("synchrobook-text"), audio: $("synchrobook-audio"),
  play: $("synchrobook-play"), back: $("synchrobook-back-10"), forward: $("synchrobook-forward-10"),
  seek: $("synchrobook-seek"), currentTime: $("synchrobook-current-time"), duration: $("synchrobook-duration"),
  speed: $("synchrobook-speed"), importDialog: $("synchrobook-import-dialog"), importForm: $("synchrobook-import-form"),
  importSubmit: $("synchrobook-import-submit"), importError: $("synchrobook-import-error"), job: $("synchrobook-import-job"),
  jobStage: $("synchrobook-job-stage"), jobProgress: $("synchrobook-job-progress"), jobPercent: $("synchrobook-job-percent"),
  jobMessage: $("synchrobook-job-message"), settingsDialog: $("synchrobook-settings-dialog"), settingsForm: $("synchrobook-settings-form"),
  qualityOpen: $("synchrobook-quality-open"), qualityDialog: $("synchrobook-quality-dialog"), qualityReport: $("synchrobook-quality-report"),
  queue: $("synchrobook-queue"), queueList: $("synchrobook-queue-list"), queueCount: $("synchrobook-queue-count"),
  queueEstimate: $("synchrobook-queue-estimate"),
  fullscreen: $("synchrobook-fullscreen-toggle"),
  sidebarToggle: $("synchrobook-sidebar-toggle"), bookMenuOpen: $("synchrobook-book-menu-open"),
  bookMenuDialog: $("synchrobook-book-menu-dialog"), bookMenuTitle: $("synchrobook-book-menu-title"),
  bookMenuAuthor: $("synchrobook-book-menu-author"), deleteBook: $("synchrobook-delete-book"),
  chapterRemaining: $("synchrobook-chapter-remaining"),
  bookRemaining: $("synchrobook-book-remaining"),
  currentPage: $("synchrobook-current-page"),
  totalPages: $("synchrobook-total-pages"),
  audioSelection: $("synchrobook-audio-selection"),
  processingStatus: $("synchrobook-processing-status"),
};

const state = {
  books: [], jobs: [], book: null, alignment: null, report: null, activeSentence: null,
  settings: loadSettings(), processingSettings: null, saveTimer: null, pageTotals: loadPageTotals(),
};
applySettings(state.settings);

function stageLabel(stage) {
  return ({
    QUEUED: "W kolejce", BOOK_PROCESSING: "Czytanie książki", EPUB_PROCESSING: "Przetwarzanie EPUB",
    AUDIO_PREPARING: "Przygotowanie audiobooka", AUDIO_MERGING: "Scalanie części audio",
    TRANSCRIBING: "Transkrypcja Whisper", ALIGNING: "Dopasowanie zdań", FINALIZING: "Finalizacja",
    READY: "Gotowe", ERROR: "Błąd",
  })[stage] || stage;
}

function setSideTab(name) {
  document.querySelectorAll("[data-side-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.sideTab === name));
  document.querySelectorAll("[data-side-panel]").forEach((panel) => { panel.hidden = panel.dataset.sidePanel !== name; });
}

function renderLibrary() {
  elements.library.replaceChildren();
  if (!state.books.length) {
    const empty = document.createElement("p");
    empty.className = "synchrobook-empty";
    empty.textContent = "Biblioteka jest pusta. Zaimportuj książkę EPUB/PDF/MOBI i audio MP3/WAV/M4B.";
    elements.library.append(empty);
    return;
  }
  for (const book of state.books) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `synchrobook-library-item${state.book?.id === book.id ? " is-active" : ""}`;
    button.dataset.bookId = book.id;
    const cover = document.createElement(book.coverUrl ? "img" : "span");
    cover.className = "synchrobook-library-cover";
    if (book.coverUrl) { cover.src = book.coverUrl; cover.alt = ""; }
    const copy = document.createElement("span");
    copy.className = "synchrobook-library-copy";
    const title = document.createElement("strong"); title.textContent = book.title;
    const author = document.createElement("span"); author.textContent = book.author;
    const status = document.createElement("span"); status.className = "synchrobook-library-state"; status.textContent = stageLabel(book.processingState);
    copy.append(title, author, status); button.append(cover, copy); elements.library.append(button);
  }
}

function renderChapters() {
  elements.chapters.replaceChildren();
  for (const chapter of state.book?.chapters || []) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "synchrobook-chapter"; button.dataset.chapterId = chapter.id; button.textContent = chapter.title;
    elements.chapters.append(button);
  }
}

function markChapter(chapterId) {
  elements.chapters.querySelectorAll("[data-chapter-id]").forEach((button) => button.classList.toggle("is-active", button.dataset.chapterId === chapterId));
}

function firstAlignedInChapter(chapterId) {
  return (state.alignment?.chapters || []).find((chapter) => chapter.id === chapterId)?.sentences?.find((sentence) => sentence.start != null);
}

function updatePagePosition(currentTime = elements.audio.currentTime) {
  elements.currentPage.textContent = currentPageAtTime(
    currentTime,
    elements.audio.duration,
    elements.totalPages.value,
  ) ?? "—";
}

function syncPageTotalForBook() {
  const pages = state.book ? state.pageTotals[state.book.id] : null;
  elements.totalPages.value = pages || "";
  elements.totalPages.disabled = !state.book;
  updatePagePosition();
}

const reader = new SynchrobookReader({
  scroller: elements.reader,
  article: elements.text,
  onSeek: (timestamp) => player.seek(timestamp, true),
  onChapter: (chapter) => {
    markChapter(chapter.id);
    guide?.chapterChanged();
    const sentence = firstAlignedInChapter(chapter.id);
    if (sentence) player.seek(sentence.start, true);
  },
});

const player = new SynchrobookAudioPlayer({
  audio: elements.audio, playButton: elements.play, seekBar: elements.seek,
  currentTime: elements.currentTime, duration: elements.duration, speed: elements.speed,
  back: elements.back, forward: elements.forward,
}, {
  onFrame: (time) => {
    const active = reader.sync(time);
    state.activeSentence = active || null;
    guide.sync(active?.id || null);
    const remaining = playbackRemainingTimes({
      alignment: state.alignment,
      currentTime: time,
      duration: elements.audio.duration,
      playbackRate: player.actualPlaybackRate(),
      fallbackChapterId: active?.chapterId || reader.chapterId,
    });
    if (remaining.chapterId) markChapter(remaining.chapterId);
    elements.chapterRemaining.textContent = formatRemaining(remaining.chapter);
    elements.bookRemaining.textContent = formatRemaining(remaining.book);
    updatePagePosition(time);
  },
  onPersist: () => scheduleProgressSave(true),
});

const guide = new ReadingGuideController({
  api,
  getBook: () => state.book,
  getReader: () => reader,
  seek: (timestamp) => player.seek(timestamp, true),
});

async function refreshBooks() {
  const result = await api.listBooks();
  state.books = result.books || [];
  renderLibrary();
}

function resetBookView() {
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  state.book = null;
  state.alignment = null;
  state.report = null;
  state.activeSentence = null;
  player.unload();
  reader.clear();
  guide.load(null);
  elements.readerEmpty.hidden = false;
  elements.qualityOpen.disabled = true;
  elements.bookMenuOpen.hidden = true;
  elements.chapterRemaining.textContent = "—";
  elements.bookRemaining.textContent = "—";
  syncPageTotalForBook();
  elements.chapters.replaceChildren();
  const empty = document.createElement("p");
  empty.className = "synchrobook-empty";
  empty.textContent = "Najpierw otwórz książkę.";
  elements.chapters.append(empty);
  setSideTab("library");
}

async function removeBook(bookId) {
  const book = state.books.find((row) => row.id === bookId);
  if (!book || !window.confirm(`Czy na pewno usunąć „${book.title}”?\n\nEPUB, audio i postęp zostaną usunięte. Plik dopasowania pozostanie w lokalnym archiwum.`)) return;
  const wasOpen = state.book?.id === bookId;
  if (wasOpen) player.unload();
  try {
    await api.deleteBook(bookId);
    if (wasOpen) resetBookView();
    await Promise.all([refreshBooks(), refreshJobs()]);
  } catch (error) {
    if (wasOpen) await openBook(bookId).catch(() => {});
    throw error;
  }
}

function renderQueue() {
  const activeStates = new Set(["QUEUED", "BOOK_PROCESSING", "EPUB_PROCESSING", "AUDIO_PREPARING", "AUDIO_MERGING", "TRANSCRIBING", "ALIGNING", "FINALIZING"]);
  const seenBooks = new Set();
  const visible = [];
  for (const job of state.jobs) {
    if (seenBooks.has(job.bookId)) continue;
    seenBooks.add(job.bookId);
    if (activeStates.has(job.status) || job.status === "ERROR") visible.push(job);
  }
  visible.splice(8);
  elements.queue.hidden = visible.length === 0;
  elements.queueCount.textContent = String(visible.length);
  elements.queueEstimate.textContent = formatQueueEstimate(estimateQueueRemainingSeconds(state.jobs));
  elements.queueList.replaceChildren();
  for (const job of visible) {
    const book = state.books.find((row) => row.id === job.bookId);
    const card = document.createElement("article");
    card.className = `synchrobook-queue-item${job.status === "ERROR" ? " is-error" : ""}`;
    const head = document.createElement("div"); head.className = "synchrobook-queue-item-head";
    const title = document.createElement("strong"); title.textContent = book?.title || "Importowana książka";
    const stage = document.createElement("span"); stage.textContent = stageLabel(job.stage);
    head.append(title, stage);
    const progress = document.createElement("progress"); progress.max = 100; progress.value = Number(job.progress) || 0;
    const message = document.createElement("small"); message.textContent = job.error || job.message || "Przetwarzanie w tle";
    card.append(head, progress, message);
    if (job.status === "ERROR") {
      const resume = document.createElement("button");
      resume.type = "button";
      resume.className = "synchrobook-queue-resume";
      resume.dataset.resumeJob = job.id;
      resume.textContent = "Wznów od zapisanego miejsca";
      card.append(resume);
    }
    elements.queueList.append(card);
  }
}

async function refreshJobs() {
  const result = await api.listJobs();
  const previous = new Map(state.jobs.map((job) => [job.id, job.status]));
  state.jobs = result.jobs || [];
  const changedToReady = state.jobs.some((job) => job.status === "READY" && previous.get(job.id) && previous.get(job.id) !== "READY");
  renderQueue();
  if (changedToReady || state.jobs.some((job) => !["READY", "ERROR"].includes(job.status))) {
    await refreshBooks();
    renderQueue();
  }
}

async function openBook(bookId) {
  const listing = state.books.find((book) => book.id === bookId);
  if (listing?.processingState !== "READY") {
    if (listing?.error) window.alert(listing.error);
    return;
  }
  if (state.book && state.book.id !== bookId) {
    elements.audio.pause();
    await persistProgress({ keepalive: false });
  }
  const [book, alignment, report] = await Promise.all([api.getBook(bookId), api.getAlignment(bookId), api.getReport(bookId)]);
  state.book = book; state.alignment = alignment; state.report = report; state.activeSentence = null;
  syncPageTotalForBook();
  elements.currentPage.textContent = "—";
  elements.bookMenuOpen.hidden = false;
  elements.bookMenuTitle.textContent = book.title;
  elements.bookMenuAuthor.textContent = book.author;
  reader.load(book, alignment);
  reader.autoScroll = state.settings.autoScroll;
  renderLibrary(); renderChapters();
  elements.readerEmpty.hidden = true;
  const initialChapter = book.progress?.chapterId || alignment.chapters?.find((chapter) => chapter.sentences?.some((row) => row.start != null))?.id || book.chapters?.[0]?.id;
  if (initialChapter) { reader.renderChapter(initialChapter, { notify: false }); markChapter(initialChapter); }
  await guide.load(book);
  player.load(book.audioUrl, { timestamp: book.progress?.timestamp || 0, speed: book.progress?.playbackSpeed || 1 });
  elements.qualityOpen.disabled = false;
  setSideTab("chapters");
}

function progressPayload() {
  return {
    timestamp: elements.audio.currentTime || 0,
    chapterId: state.activeSentence?.chapterId || reader.chapterId,
    sentenceId: state.activeSentence?.id || reader.activeId,
    playbackSpeed: player.actualPlaybackRate(),
    readingMode: state.settings.mode,
  };
}

function persistProgress({ keepalive = false } = {}) {
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  if (!state.book) return Promise.resolve();
  const bookId = state.book.id;
  const payload = progressPayload();
  return api.saveProgress(bookId, payload, { keepalive }).catch(() => {});
}

function scheduleProgressSave(immediate = false) {
  if (!state.book) return;
  clearTimeout(state.saveTimer);
  if (immediate) persistProgress({ keepalive: true });
  else state.saveTimer = window.setTimeout(() => persistProgress(), 1000);
}

window.setInterval(() => { if (state.book && !elements.audio.paused) scheduleProgressSave(); }, 5000);
window.addEventListener("beforeunload", () => scheduleProgressSave(true));
window.addEventListener("pagehide", () => scheduleProgressSave(true));
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") scheduleProgressSave(true);
});

elements.importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.importError.hidden = true;
  try {
    const data = new FormData(elements.importForm);
    elements.job.hidden = false;
    elements.jobStage.textContent = "Wysyłanie plików";
    const audioCount = data.getAll("audiobook").filter((file) => file?.name).length;
    elements.jobMessage.textContent = `Wysyłanie książki i ${audioCount} ${audioCount === 1 ? "pliku audio" : "plików audio"}.`;
    elements.importSubmit.disabled = true;
    const result = await api.importBook(data, (progress) => {
      elements.jobProgress.value = progress;
      elements.jobPercent.textContent = `${progress}%`;
    });
    elements.importDialog.close();
    elements.importForm.reset();
    elements.audioSelection.replaceChildren();
    elements.audioSelection.hidden = true;
    elements.importSubmit.disabled = false;
    elements.job.hidden = true;
    await Promise.all([refreshBooks(), refreshJobs()]);
  } catch (error) {
    elements.importError.textContent = error.message;
    elements.importError.hidden = false;
    elements.importSubmit.disabled = false;
    await refreshBooks().catch(() => {});
  }
});

elements.library.addEventListener("click", (event) => {
  const button = event.target.closest("[data-book-id]");
  if (button) openBook(button.dataset.bookId).catch((error) => window.alert(error.message));
});
elements.queueList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-resume-job]");
  if (!button) return;
  button.disabled = true;
  try {
    await api.resumeJob(button.dataset.resumeJob);
    await Promise.all([refreshBooks(), refreshJobs()]);
  } catch (error) {
    window.alert(error.message);
    button.disabled = false;
  }
});
elements.chapters.addEventListener("click", (event) => {
  const button = event.target.closest("[data-chapter-id]");
  if (button) reader.renderChapter(button.dataset.chapterId);
});
elements.totalPages.addEventListener("input", () => {
  if (!state.book) return;
  const pages = normalizeTotalPages(elements.totalPages.value);
  if (pages != null) {
    state.pageTotals[state.book.id] = pages;
    savePageTotals(state.pageTotals);
  } else if (elements.totalPages.value === "") {
    delete state.pageTotals[state.book.id];
    savePageTotals(state.pageTotals);
  }
  updatePagePosition();
});
elements.totalPages.addEventListener("change", () => {
  const pages = state.book ? state.pageTotals[state.book.id] : null;
  elements.totalPages.value = pages || "";
  updatePagePosition();
});
document.querySelectorAll("[data-side-tab]").forEach((button) => button.addEventListener("click", () => setSideTab(button.dataset.sideTab)));

$("synchrobook-import-open").addEventListener("click", () => {
  elements.job.hidden = true; elements.importError.hidden = true; elements.importDialog.showModal();
});
$("synchrobook-settings-open").addEventListener("click", () => { syncSettingsForm(); elements.settingsDialog.showModal(); });
elements.bookMenuOpen.addEventListener("click", () => {
  if (state.book) elements.bookMenuDialog.showModal();
});
elements.deleteBook.addEventListener("click", () => {
  if (!state.book) return;
  const bookId = state.book.id;
  elements.bookMenuDialog.close();
  removeBook(bookId).catch((error) => window.alert(error.message));
});
const fullscreenIdle = createFullscreenIdleController({
  page: document.body,
  delay: 15000,
  onVisibilityChange: () => requestAnimationFrame(() => reader.sync(elements.audio.currentTime || 0, { forceScroll: true })),
});
let fullscreenWasActive = false;

function syncFullscreenState() {
  const active = syncFullscreenUi(elements.fullscreen, document.body);
  syncFullscreenSidebarUi(elements.sidebarToggle, document.body, active, {
    defaultHidden: active && !fullscreenWasActive,
  });
  fullscreenWasActive = active;
  fullscreenIdle.setFullscreen(active);
  requestAnimationFrame(() => reader.sync(elements.audio.currentTime || 0, { forceScroll: true }));
}
if (fullscreenSupported()) {
  elements.fullscreen.addEventListener("click", async () => {
    try { await toggleFullscreen(); } catch { /* The browser may reject fullscreen outside an allowed user gesture. */ }
    syncFullscreenState();
  });
  elements.sidebarToggle.addEventListener("click", () => {
    toggleFullscreenSidebar(elements.sidebarToggle, document.body);
    requestAnimationFrame(() => reader.sync(elements.audio.currentTime || 0, { forceScroll: true }));
  });
  document.addEventListener("fullscreenchange", syncFullscreenState);
  document.addEventListener("webkitfullscreenchange", syncFullscreenState);
  syncFullscreenState();
} else {
  elements.fullscreen.hidden = true;
}
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => button.closest("dialog")?.close()));
document.querySelectorAll("input[type='file']").forEach((input) => input.addEventListener("change", () => {
  const label = document.querySelector(`[data-file-label="${input.name}"]`);
  const files = [...(input.files || [])];
  if (label) {
    label.textContent = files.length > 1 ? `${files.length} plików — kolejność według nazw` : files[0]?.name || (input.name === "book" ? "EPUB, PDF albo MOBI" : "MP3, WAV lub M4B");
  }
  if (input.name === "audiobook") {
    elements.audioSelection.replaceChildren();
    const sorted = files.sort((left, right) => left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" }));
    for (const file of sorted) {
      const item = document.createElement("li");
      item.textContent = file.name;
      elements.audioSelection.append(item);
    }
    elements.audioSelection.hidden = sorted.length < 2;
  }
}));

function syncSettingsForm() {
  const form = elements.settingsForm;
  form.elements.mode.value = state.settings.mode;
  form.elements.fontSize.value = state.settings.fontSize;
  form.elements.lineHeight.value = state.settings.lineHeight;
  form.elements.columnWidth.value = state.settings.columnWidth;
  form.elements.autoScroll.checked = state.settings.autoScroll;
  form.elements.highlightPreset.value = state.settings.highlightPreset;
  form.elements.highlightBackground.value = state.settings.highlightBackground;
  form.elements.highlightText.value = state.settings.highlightText;
  form.elements.highlightGlow.value = state.settings.highlightGlow;
  form.elements.highlightBold.checked = state.settings.highlightBold;
  form.elements.highMemory.checked = state.processingSettings?.highMemory === true;
  form.elements.highMemory.disabled = state.processingSettings == null;
  $("synchrobook-font-output").textContent = `${state.settings.fontSize}px`;
  $("synchrobook-line-output").textContent = state.settings.lineHeight;
  $("synchrobook-width-output").textContent = `${state.settings.columnWidth}px`;
  $("synchrobook-highlight-glow-output").textContent = `${state.settings.highlightGlow}px`;
}

async function refreshProcessingSettings() {
  const checkbox = elements.settingsForm.elements.highMemory;
  checkbox.disabled = true;
  elements.processingStatus.textContent = "Ładowanie ustawień serwera…";
  try {
    state.processingSettings = await api.getProcessingSettings();
    checkbox.checked = state.processingSettings.highMemory === true;
    checkbox.disabled = false;
    elements.processingStatus.textContent = state.processingSettings.highMemory
      ? `Tryb szybszy jest włączony (${state.processingSettings.transcriptionThreads} wątki transkrypcji).`
      : "Tryb bezpieczny jest włączony.";
  } catch (error) {
    elements.processingStatus.textContent = `Nie udało się wczytać ustawienia: ${error.message}`;
  }
}

async function saveProcessingMode(highMemory) {
  const checkbox = elements.settingsForm.elements.highMemory;
  const previous = state.processingSettings?.highMemory === true;
  checkbox.disabled = true;
  elements.processingStatus.textContent = "Zapisywanie…";
  try {
    state.processingSettings = await api.saveProcessingSettings(highMemory);
    checkbox.checked = state.processingSettings.highMemory === true;
    elements.processingStatus.textContent = highMemory
      ? `Tryb szybszy włączony (${state.processingSettings.transcriptionThreads} wątki). Aktywna transkrypcja od razu użyje mniej zachowawczych limitów RAM.`
      : "Tryb bezpieczny włączony. Aktywna transkrypcja wróci do oszczędzania zasobów od następnego fragmentu.";
  } catch (error) {
    checkbox.checked = previous;
    elements.processingStatus.textContent = `Nie udało się zapisać: ${error.message}`;
  } finally {
    checkbox.disabled = false;
  }
}

function updateSettingsFromForm() {
  const form = elements.settingsForm;
  state.settings = {
    mode: form.elements.mode.value,
    fontSize: Number(form.elements.fontSize.value), lineHeight: Number(form.elements.lineHeight.value),
    columnWidth: Number(form.elements.columnWidth.value), autoScroll: form.elements.autoScroll.checked,
    highlightPreset: form.elements.highlightPreset.value,
    highlightBackground: form.elements.highlightBackground.value,
    highlightText: form.elements.highlightText.value,
    highlightGlow: Number(form.elements.highlightGlow.value),
    highlightBold: form.elements.highlightBold.checked,
  };
  applySettings(state.settings); saveSettings(state.settings); reader.autoScroll = state.settings.autoScroll;
  requestAnimationFrame(() => reader.sync(elements.audio.currentTime || 0, { forceScroll: true }));
  syncSettingsForm(); scheduleProgressSave();
}

elements.settingsForm.addEventListener("input", (event) => {
  if (event.target.name === "highMemory") {
    saveProcessingMode(event.target.checked);
    return;
  }
  if (event.target.name === "mode") {
    const highlightSettings = {
      highlightPreset: state.settings.highlightPreset,
      highlightBackground: state.settings.highlightBackground,
      highlightText: state.settings.highlightText,
      highlightGlow: state.settings.highlightGlow,
      highlightBold: state.settings.highlightBold,
    };
    state.settings = { ...PRESETS[event.target.value], ...highlightSettings };
    syncSettingsForm();
  }
  if (event.target.name === "highlightPreset" && HIGHLIGHT_PRESETS[event.target.value]) {
    const preset = HIGHLIGHT_PRESETS[event.target.value];
    elements.settingsForm.elements.highlightBackground.value = preset.highlightBackground;
    elements.settingsForm.elements.highlightText.value = preset.highlightText;
  }
  if (event.target.name === "highlightBackground" || event.target.name === "highlightText") {
    elements.settingsForm.elements.highlightPreset.value = "custom";
  }
  updateSettingsFromForm();
});

function renderQuality() {
  const report = state.report;
  if (!report) return;
  elements.qualityReport.replaceChildren();
  const summary = document.createElement("div"); summary.className = "synchrobook-quality-summary";
  for (const [value, label] of [
    [`${report.summary.percentageAligned}%`, "dopasowano"], [report.summary.alignedSentences, "zdań"], [report.summary.averageConfidence, "średnia pewność"],
  ]) {
    const card = document.createElement("div"); const strong = document.createElement("strong"); strong.textContent = value;
    const span = document.createElement("span"); span.textContent = label; card.append(strong, span); summary.append(card);
  }
  const list = document.createElement("div"); list.className = "synchrobook-quality-list";
  for (const chapter of report.chapters || []) {
    const row = document.createElement("div"); row.className = "synchrobook-quality-row";
    const title = document.createElement("strong"); title.textContent = chapter.title;
    const percent = document.createElement("span"); percent.textContent = `${chapter.percentageAligned}%`;
    const quality = document.createElement("strong"); quality.dataset.quality = chapter.quality;
    quality.textContent = chapter.quality === "NOT_IN_AUDIO" ? "BRAK W AUDIO" : chapter.quality;
    row.append(title, percent, quality); list.append(row);
  }
  elements.qualityReport.append(summary, list);
}

elements.qualityOpen.addEventListener("click", () => { renderQuality(); elements.qualityDialog.showModal(); });
async function runBookAction(action) {
  if (!state.book) return;
  elements.qualityDialog.close();
  await action(state.book.id);
  await Promise.all([refreshBooks(), refreshJobs()]);
}
$("synchrobook-rebuild").addEventListener("click", () => runBookAction(api.rebuildAlignment).catch((error) => window.alert(error.message)));
$("synchrobook-retranscribe").addEventListener("click", () => runBookAction(api.retranscribeAudio).catch((error) => window.alert(error.message)));

refreshProcessingSettings();
Promise.all([refreshBooks(), refreshJobs()]).catch((error) => {
  elements.library.innerHTML = "";
  const message = document.createElement("p"); message.className = "synchrobook-empty"; message.textContent = `Backend Synchrobook jest niedostępny: ${error.message}`; elements.library.append(message);
});
window.setInterval(() => refreshJobs().catch(() => {}), 1500);
