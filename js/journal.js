import {
  createJournalEntry,
  deleteJournalEntry,
  fetchJournalContexts,
  fetchJournalEntries,
  updateJournalEntry,
} from "./journal-api.js";
import {
  journalEntryText,
  journalMarkupToHtml,
  prepareJournalIllustration,
  sanitizeJournalHtml,
} from "./journal-rich-text.js";

const JOURNAL_CHANGED_EVENT = "journal:changed";
const JOURNAL_DRAFT_PREFIX = "journal:draft:v1:";
const JOURNAL_SHOW_POEMS_KEY = "journal:show-poems:v1";
const JOURNAL_SHOW_CONTEXT_KEY = "journal:show-context:v1";
const JOURNAL_DRAFT_SAVE_DELAY = 300;
const UNTITLED_ENTRY_TITLE = "* * *";

function isPoem(entry) {
  return entry?.entryKind === "poem";
}

function journalContextDay(entry) {
  return journalLocalDate(entry?.entryDate);
}

export function journalDraftStorageKey(entryId = null) {
  return `${JOURNAL_DRAFT_PREFIX}${entryId ? `entry:${entryId}` : "new"}`;
}

function node(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function optionNode(text, value = "") {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = text;
  return option;
}

export function splitJournalTags(value) {
  return [...new Set(String(value || "").split(",").map((tag) => tag.trim()).filter(Boolean))].slice(0, 20);
}

export function journalLocalDateTime(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function isDateOnly(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
}

function journalDateObject(value) {
  const raw = String(value || "");
  return new Date(isDateOnly(raw) ? `${raw}T00:00:00` : raw);
}

export function formatJournalDate(value, { includeTime = true, monthStyle = "numeric" } = {}) {
  const date = journalDateObject(value);
  if (Number.isNaN(date.getTime())) return "—";
  const formatted = monthStyle === "long"
    ? date.toLocaleDateString("pl-PL", { day: "2-digit", month: "long", year: "numeric" })
    : [date.getDate(), date.getMonth() + 1, date.getFullYear()]
      .map((part, index) => index < 2 ? String(part).padStart(2, "0") : String(part))
      .join("/");
  if (!includeTime || isDateOnly(value)) return formatted;
  return `${formatted}, ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function parseJournalDateInput(value) {
  const raw = String(value || "").trim().toLocaleLowerCase("pl-PL");
  const numericMatch = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(raw);
  const longMatch = /^(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})$/.exec(raw);
  let day;
  let month;
  let year;
  if (numericMatch) {
    [, day, month, year] = numericMatch;
  } else if (longMatch) {
    const months = [
      "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
      "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
    ];
    [, day, month, year] = longMatch;
    month = String(months.indexOf(month) + 1);
    if (month === "0") return null;
  } else return null;
  day = String(day).padStart(2, "0");
  month = String(month).padStart(2, "0");
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  if (
    date.getFullYear() !== Number(year)
    || date.getMonth() !== Number(month) - 1
    || date.getDate() !== Number(day)
  ) return null;
  return { date, isoDate: `${year}-${month}-${day}` };
}

export function journalLocalDate(value = new Date()) {
  const raw = String(value || "");
  if (isDateOnly(raw)) return raw;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function journalLocalTime(value) {
  if (!value || isDateOnly(value)) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(11, 16);
}

function dateParts(value) {
  const date = journalDateObject(value);
  const hasTime = !isDateOnly(value);
  return {
    day: date.toLocaleDateString("pl-PL", { day: "2-digit" }),
    month: date.toLocaleDateString("pl-PL", { month: "short" }).replace(".", ""),
    year: date.toLocaleDateString("pl-PL", { year: "numeric" }),
    full: hasTime
      ? date.toLocaleString("pl-PL", { dateStyle: "long", timeStyle: "short" })
      : date.toLocaleDateString("pl-PL", { dateStyle: "long" }),
  };
}

function entryDateParts(entry) {
  const publishedLocal = String(entry?.sourceMetadata?.tumblr?.publishedLocal || "");
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(publishedLocal);
  if (!match) return dateParts(entry?.entryDate);
  const local = new Date(
    Number(match[1]), Number(match[2]) - 1, Number(match[3]),
    Number(match[4]), Number(match[5]), Number(match[6] || 0),
  );
  return dateParts(local);
}

function journalPeriod(value) {
  const date = journalDateObject(value);
  if (Number.isNaN(date.getTime())) return null;
  return { year: String(date.getFullYear()), month: String(date.getMonth() + 1).padStart(2, "0") };
}

function journalMonthName(month) {
  return new Intl.DateTimeFormat("pl-PL", { month: "long" })
    .format(new Date(2020, Number(month) - 1, 1));
}

function metadataLine(entry) {
  const metadata = entry.sourceMetadata || {};
  return [
    metadata.originalFilename,
    metadata.engine && metadata.model ? `${metadata.engine} / ${metadata.model}` : metadata.model,
    metadata.device ? String(metadata.device).toUpperCase() : "",
    Number.isFinite(Number(metadata.durationSeconds)) ? `${Math.round(Number(metadata.durationSeconds))} s audio` : "",
    Number.isFinite(Number(metadata.realTimeFactor)) ? `RTF ${Number(metadata.realTimeFactor).toLocaleString("pl-PL")}` : "",
  ].filter(Boolean).join(" · ");
}

function insertEditorHtml(editor, html) {
  editor.focus();
  if (typeof document.execCommand === "function") {
    document.execCommand("insertHTML", false, html);
    return;
  }
  const selection = window.getSelection?.();
  if (!selection?.rangeCount) {
    editor.insertAdjacentHTML("beforeend", html);
    return;
  }
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const fragment = range.createContextualFragment(html);
  range.insertNode(fragment);
  range.collapse(false);
}

export async function initJournalApp(root, dependencies = {}) {
  if (!root) return null;
  const fetchEntries = dependencies.fetchEntries || fetchJournalEntries;
  const fetchContexts = dependencies.fetchContexts || fetchJournalContexts;
  const createEntry = dependencies.createEntry || createJournalEntry;
  const updateEntry = dependencies.updateEntry || updateJournalEntry;
  const removeEntry = dependencies.deleteEntry || deleteJournalEntry;
  const confirmAction = dependencies.confirmAction || ((message) => window.confirm(message));
  let draftStorage = dependencies.draftStorage;
  if (draftStorage === undefined) {
    try {
      draftStorage = window.localStorage;
    } catch {
      draftStorage = null;
    }
  }

  const form = root.querySelector("#journal-form");
  const composer = root.querySelector("#journal-composer-panel");
  const composerShell = root.querySelector("#journal-composer-shell") || form.parentElement;
  const composerSlot = root.querySelector("#journal-composer-slot");
  const composerAnchor = document.createComment("journal-composer-home");
  composerShell.before(composerAnchor);
  const formTitle = root.querySelector("#journal-form-title");
  const formKicker = root.querySelector("#journal-form-kicker");
  const formStatus = root.querySelector("#journal-form-status");
  const cancelEdit = root.querySelector("#journal-cancel-edit");
  const newEntry = root.querySelector("#journal-new-entry");
  const newPoem = root.querySelector("#journal-new-poem");
  const search = root.querySelector("#journal-search");
  const list = root.querySelector("#journal-entry-list");
  const empty = root.querySelector("#journal-empty");
  const listStatus = root.querySelector("#journal-list-status");
  const yearFilter = root.querySelector("#journal-year-filter");
  const monthFilter = root.querySelector("#journal-month-filter");
  const filterReset = root.querySelector("#journal-filter-reset");
  const showPoemsInput = root.querySelector("#journal-show-poems");
  const showContextInput = root.querySelector("#journal-show-context");
  const countStat = root.querySelector("#journal-stat-count");
  const poemsStat = root.querySelector("#journal-stat-poems");
  const voiceStat = root.querySelector("#journal-stat-voice");
  const latestStat = root.querySelector("#journal-stat-latest");
  const submit = root.querySelector("#journal-save-entry");
  const titleInput = form.elements.title;
  const kindInput = form.elements.entryKind;
  const dateInput = form.elements.entryDate;
  const timeInput = form.elements.entryTime;
  const tagsInput = form.elements.tags;
  const locationInput = form.elements.location;
  const contentInput = form.elements.content;
  const richEditor = root.querySelector("#journal-rich-editor");
  const editorToolbar = root.querySelector("#journal-editor-toolbar");
  const sourceToggle = root.querySelector("#journal-editor-source-toggle");
  const blockSelect = root.querySelector("#journal-editor-block");
  const illustrationInput = form.elements.illustrationFile;
  const illustrationAltInput = form.elements.illustrationAlt;
  const illustrationPreview = root.querySelector("#journal-illustration-preview");
  const illustrationImage = root.querySelector("#journal-illustration-image");
  const removeIllustration = root.querySelector("#journal-remove-illustration");
  const editAudio = root.querySelector("#journal-edit-audio");
  const editAudioPlayer = root.querySelector("#journal-edit-audio-player");
  const editAudioMeta = root.querySelector("#journal-edit-audio-meta");
  const draftStatus = root.querySelector("#journal-draft-status");

  let entries = [];
  let showPoems = false;
  let showContext = false;
  let contexts = {};
  let contextLoading = false;
  let contextError = "";
  let editingId = null;
  let editingVersion = null;
  let sourceMode = false;
  let illustrationData = "";
  let illustrationDirty = false;
  let dateFiltersInitialized = false;

  try {
    showPoems = draftStorage?.getItem(JOURNAL_SHOW_POEMS_KEY) === "1";
    showContext = draftStorage?.getItem(JOURNAL_SHOW_CONTEXT_KEY) === "1";
  } catch { /* storage unavailable */ }
  if (showPoemsInput) showPoemsInput.checked = showPoems;
  if (showContextInput) showContextInput.checked = showContext;
  let draftDirty = false;
  let draftTimer = null;

  const setFormStatus = (message, kind = "") => {
    formStatus.textContent = message;
    formStatus.dataset.kind = kind;
  };

  const setSourceMode = (enabled, { focus = true } = {}) => {
    if (!richEditor || !sourceToggle) return;
    sourceMode = Boolean(enabled);
    if (sourceMode) contentInput.value = sanitizeJournalHtml(richEditor.innerHTML);
    else richEditor.innerHTML = journalMarkupToHtml(contentInput.value);
    richEditor.hidden = sourceMode;
    contentInput.hidden = !sourceMode;
    sourceToggle.classList.toggle("is-active", sourceMode);
    sourceToggle.setAttribute("aria-pressed", String(sourceMode));
    sourceToggle.textContent = sourceMode ? "Wizualny" : "Kod";
    if (focus) (sourceMode ? contentInput : richEditor).focus();
  };

  const setEditorContent = (entry = null) => {
    const value = entry?.content || "";
    if (!richEditor) {
      contentInput.value = entry?.contentFormat === "html" ? journalEntryText(entry) : value;
      return;
    }
    richEditor.innerHTML = entry?.contentFormat === "html"
      ? sanitizeJournalHtml(value)
      : journalMarkupToHtml(value);
    contentInput.value = richEditor.innerHTML;
    setSourceMode(false, { focus: false });
  };

  const editorContent = () => {
    if (!richEditor) return { content: contentInput.value.trim(), contentFormat: "text" };
    const html = sourceMode
      ? journalMarkupToHtml(contentInput.value)
      : sanitizeJournalHtml(richEditor.innerHTML);
    return { content: html.trim(), contentFormat: "html" };
  };

  const setIllustration = (dataUrl = "", alt = "", { changed = false } = {}) => {
    illustrationData = /^data:image\/(?:jpeg|png|webp|gif);base64,/i.test(dataUrl) ? dataUrl : "";
    illustrationDirty = Boolean(changed);
    if (illustrationAltInput) illustrationAltInput.value = illustrationData ? String(alt || "") : "";
    if (illustrationInput) illustrationInput.value = "";
    if (illustrationPreview) illustrationPreview.hidden = !illustrationData;
    if (illustrationImage) {
      if (illustrationData) illustrationImage.src = illustrationData;
      else illustrationImage.removeAttribute("src");
    }
  };

  const setDraftStatus = (message, kind = "") => {
    if (!draftStatus) return;
    draftStatus.textContent = message;
    draftStatus.dataset.kind = kind;
  };

  const readDraft = (entryId = null) => {
    if (!draftStorage) return null;
    const key = journalDraftStorageKey(entryId);
    try {
      const draft = JSON.parse(draftStorage.getItem(key) || "null");
      return draft?.version === 1 ? draft : null;
    } catch {
      try { draftStorage.removeItem(key); } catch { /* storage unavailable */ }
      return null;
    }
  };

  const clearDraft = (entryId = null) => {
    if (!draftStorage) return;
    try { draftStorage.removeItem(journalDraftStorageKey(entryId)); } catch { /* storage unavailable */ }
  };

  const draftSnapshot = () => ({
    version: 1,
    baseVersion: editingVersion,
    savedAt: new Date().toISOString(),
    entryKind: kindInput?.value || "journal",
    title: titleInput.value,
    entryDate: dateInput.value,
    entryTime: timeInput?.value || "",
    tags: tagsInput.value,
    location: locationInput?.value || "",
    ...editorContent(),
    illustrationChanged: illustrationDirty,
    illustration: illustrationDirty ? illustrationData : "",
    illustrationAlt: illustrationAltInput?.value || "",
  });

  const draftHasNewEntryContent = (draft) => Boolean(
    draft.title.trim()
    || journalEntryText(draft)
    || draft.tags.trim()
    || draft.location.trim()
    || draft.illustrationChanged
  );

  const writeDraft = (entryId, draft) => {
    if (!draftStorage) {
      setDraftStatus("Autosave jest niedostępny w tej przeglądarce.", "error");
      return false;
    }
    const key = journalDraftStorageKey(entryId);
    try {
      draftStorage.setItem(key, JSON.stringify(draft));
    } catch {
      if (!draft.illustration) {
        setDraftStatus("Nie udało się zapisać szkicu w przeglądarce.", "error");
        return false;
      }
      try {
        draftStorage.setItem(key, JSON.stringify({
          ...draft,
          illustration: "",
          illustrationChanged: false,
          illustrationOmitted: true,
        }));
        setDraftStatus("Tekst szkicu zapisany; obraz nie zmieścił się w pamięci przeglądarki.", "warning");
        return true;
      } catch {
        setDraftStatus("Nie udało się zapisać szkicu w przeglądarce.", "error");
        return false;
      }
    }
    const time = new Date(draft.savedAt).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
    setDraftStatus(`Szkic zapisany automatycznie o ${time}.`, "saved");
    return true;
  };

  const persistCurrentDraft = () => {
    if (draftTimer) clearTimeout(draftTimer);
    draftTimer = null;
    if (!draftDirty) return;
    const draft = draftSnapshot();
    if (!editingId && !draftHasNewEntryContent(draft)) {
      clearDraft();
      setDraftStatus("Autosave szkicu jest włączony.");
      draftDirty = false;
    } else if (writeDraft(editingId, draft)) {
      draftDirty = false;
    }
  };

  const scheduleDraftSave = () => {
    draftDirty = true;
    if (draftTimer) clearTimeout(draftTimer);
    draftTimer = setTimeout(persistCurrentDraft, JOURNAL_DRAFT_SAVE_DELAY);
  };

  const restoreDraft = (entryId = null) => {
    const draft = readDraft(entryId);
    if (!draft) {
      draftDirty = false;
      setDraftStatus("Autosave szkicu jest włączony.");
      return false;
    }
    if (entryId) editingVersion = Number.isInteger(draft.baseVersion) ? draft.baseVersion : 1;
    if (kindInput) kindInput.value = draft.entryKind === "poem" ? "poem" : "journal";
    titleInput.value = String(draft.title || "");
    if (draft.entryDate) dateInput.value = String(draft.entryDate);
    if (timeInput) timeInput.value = String(draft.entryTime || "");
    tagsInput.value = String(draft.tags || "");
    if (locationInput) locationInput.value = String(draft.location || "");
    setEditorContent(draft);
    if (draft.illustrationChanged && !draft.illustrationOmitted) {
      setIllustration(draft.illustration, draft.illustrationAlt, { changed: true });
    } else if (illustrationAltInput && illustrationData) {
      illustrationAltInput.value = String(draft.illustrationAlt || "");
    }
    draftDirty = false;
    const saved = new Date(draft.savedAt);
    const timestamp = Number.isNaN(saved.getTime())
      ? ""
      : ` z ${saved.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" })}`;
    setDraftStatus(
      draft.illustrationOmitted
        ? `Przywrócono tekst szkicu${timestamp}; obraz nie był zapisany.`
        : `Przywrócono autoszkic${timestamp}.`,
      "restored",
    );
    return true;
  };

  const restoreComposer = () => {
    if (composerShell.parentElement !== composer) composerAnchor.after(composerShell);
    composerShell.classList.remove("is-inline");
    root.classList.remove("is-inline-editing");
    root.querySelectorAll(".journal-entry-card.is-editing").forEach((card) => card.classList.remove("is-editing"));
    search.disabled = false;
    yearFilter && (yearFilter.disabled = false);
    monthFilter && (monthFilter.disabled = false);
    filterReset && (filterReset.disabled = false);
    showPoemsInput && (showPoemsInput.disabled = false);
    showContextInput && (showContextInput.disabled = false);
  };

  const showComposer = ({ focus = false } = {}) => {
    if (!composerSlot) return;
    composerSlot.append(composerShell);
    composerShell.classList.add("is-inline");
    if (focus) {
      composerShell.scrollIntoView?.({ behavior: "smooth", block: "start" });
      titleInput.focus();
    }
  };

  const setEditAudio = (entry = null) => {
    if (!editAudio || !editAudioPlayer) return;
    const voiceId = String(entry?.sourceVoiceJournalEntryId || entry?.sourceMetadata?.voiceJournalEntryId || "");
    const metadataUrl = String(entry?.sourceMetadata?.audioUrl || "");
    const safeMetadataUrl = /^\/api\/voice-journal\/entries\/[a-f0-9]{32}\/audio$/i.test(metadataUrl)
      ? metadataUrl
      : "";
    const audioUrl = safeMetadataUrl || (/^[a-f0-9]{32}$/i.test(voiceId)
      ? `/api/voice-journal/entries/${voiceId}/audio`
      : "");
    const isVoiceEntry = entry?.sourceType === "voice-journal" && audioUrl;
    editAudio.hidden = !isVoiceEntry;
    if (isVoiceEntry) {
      editAudioPlayer.src = audioUrl;
      editAudioPlayer.setAttribute("aria-label", `Oryginalne nagranie: ${entry.title || UNTITLED_ENTRY_TITLE}`);
      if (editAudioMeta) editAudioMeta.textContent = metadataLine(entry);
    } else {
      editAudioPlayer.removeAttribute("src");
      editAudioPlayer.removeAttribute("aria-label");
      if (editAudioMeta) editAudioMeta.textContent = "";
    }
  };

  const setDateInputs = (value = new Date()) => {
    if (dateInput.type === "date") {
      dateInput.value = journalLocalDate(value);
      if (timeInput) timeInput.value = journalLocalTime(value);
    } else if (dateInput.type === "text") {
      dateInput.value = formatJournalDate(value, { includeTime: false, monthStyle: "long" });
      if (timeInput) timeInput.value = journalLocalTime(value);
    } else {
      dateInput.value = journalLocalDateTime(value);
    }
  };

  const resetForm = ({ focus = false, entryKind = "journal", open = false } = {}) => {
    if (draftTimer) clearTimeout(draftTimer);
    draftTimer = null;
    restoreComposer();
    editingId = null;
    editingVersion = null;
    draftDirty = false;
    form.reset();
    if (kindInput) kindInput.value = entryKind;
    setEditorContent();
    setIllustration();
    setEditAudio();
    setDateInputs();
    formTitle.textContent = entryKind === "poem" ? "Dodaj wiersz" : "Dodaj wpis";
    formKicker.textContent = entryKind === "poem" ? "Nowy wiersz" : "Nowa strona";
    submit.textContent = entryKind === "poem" ? "Zapisz wiersz" : "Zapisz wpis";
    cancelEdit.hidden = !open;
    cancelEdit.textContent = "Anuluj";
    setFormStatus("");
    restoreDraft();
    if (open) showComposer({ focus });
  };

  const startEdit = (entry, article) => {
    persistCurrentDraft();
    editingId = entry.id;
    editingVersion = entry.version ?? null;
    draftDirty = false;
    if (kindInput) kindInput.value = isPoem(entry) ? "poem" : "journal";
    titleInput.value = entry.title || "";
    setDateInputs(entry.entryDate);
    tagsInput.value = (entry.tags || []).join(", ");
    if (locationInput) locationInput.value = entry.location || "";
    setEditorContent(entry);
    setIllustration(entry.illustration, entry.illustrationAlt);
    formTitle.textContent = isPoem(entry) ? "Edytuj wiersz" : "Edytuj wpis";
    formKicker.textContent = entry.sourceType === "voice-journal"
      ? "Opublikowane z głosu"
      : isPoem(entry) ? "Wiersz" : "Własny wpis";
    submit.textContent = "Zapisz zmiany";
    cancelEdit.hidden = false;
    cancelEdit.textContent = "Anuluj edycję";
    setFormStatus("");
    setEditAudio(entry);
    restoreDraft(entry.id);
    showComposer();
    root.classList.add("is-inline-editing");
    root.querySelectorAll(".journal-entry-card.is-editing").forEach((card) => card.classList.remove("is-editing"));
    article.classList.add("is-editing");
    search.disabled = true;
    yearFilter && (yearFilter.disabled = true);
    monthFilter && (monthFilter.disabled = true);
    filterReset && (filterReset.disabled = true);
    showPoemsInput && (showPoemsInput.disabled = true);
    showContextInput && (showContextInput.disabled = true);
    composerShell.scrollIntoView?.({ behavior: "smooth", block: "start" });
    titleInput.focus();
  };

  const renderStats = () => {
    const journalEntries = entries.filter((entry) => !isPoem(entry));
    countStat.textContent = String(journalEntries.length);
    if (poemsStat) poemsStat.textContent = String(entries.filter(isPoem).length);
    voiceStat.textContent = String(journalEntries.filter((entry) => entry.sourceType === "voice-journal").length);
    latestStat.textContent = journalEntries.length
      ? formatJournalDate(journalEntries[0].entryDate, { includeTime: false, monthStyle: "long" })
      : "Brak";
  };

  const renderEntryContext = (entry) => {
    const section = node("section", "journal-entry-context");
    section.append(node("h4", "", "Kontekst"));
    if (contextLoading) {
      section.append(node("p", "journal-context-status", "Wczytywanie kontekstu z Great Timeline…"));
      return section;
    }
    if (contextError) {
      section.append(node("p", "journal-context-status is-error", contextError));
      return section;
    }
    const context = contexts[journalContextDay(entry)] || {};
    const timelineGroups = Array.isArray(context.timelineGroups) ? context.timelineGroups : [];
    const activityGroups = Array.isArray(context.activityGroups) ? context.activityGroups : [];
    if (!timelineGroups.length && !activityGroups.length) {
      section.append(node("p", "journal-context-status", "Brak danych kontekstowych dla tego dnia."));
      return section;
    }

    if (timelineGroups.length) {
      const block = node("div", "journal-context-block");
      block.append(node("h5", "", "Great Timeline"));
      timelineGroups.forEach((group) => {
        const row = node("div", "journal-context-group");
        row.style.setProperty("--context-color", group.color || "#858585");
        row.append(node("strong", "journal-context-label", group.label || group.id));
        const list = node("div", "journal-context-values");
        (group.items || []).forEach((item) => {
          const value = node("div", "journal-context-value");
          value.append(node("span", "", item.title || UNTITLED_ENTRY_TITLE));
          const details = [item.subcategory, item.location, ...(item.people || [])]
            .map((part) => String(part || "").trim())
            .filter((part, index, values) => part && values.indexOf(part) === index && part !== item.title);
          if (details.length) value.append(node("small", "", details.join(" · ")));
          list.append(value);
        });
        row.append(list);
        block.append(row);
      });
      section.append(block);
    }

    if (activityGroups.length) {
      const block = node("div", "journal-context-block");
      block.append(node("h5", "", "Sygnały dnia"));
      activityGroups.forEach((group) => {
        const row = node("div", "journal-context-group is-activity");
        row.style.setProperty("--context-color", group.color || "#858585");
        row.append(node("strong", "journal-context-label", group.label || group.id));
        const list = node("div", "journal-context-values");
        (group.events || []).forEach((event) => {
          const value = node("div", "journal-context-value");
          value.append(node("span", "", event.title || event.kind || "Zdarzenie"));
          if (event.summary && event.summary !== event.title) {
            value.append(node("small", "", event.summary));
          }
          list.append(value);
        });
        row.append(list);
        block.append(row);
      });
      section.append(block);
    }
    return section;
  };

  const renderCard = (entry) => {
    const article = node("article", "journal-entry-card");
    article.classList.toggle("is-poem", isPoem(entry));
    article.dataset.entryId = entry.id;
    const date = entryDateParts(entry);
    const dateBlock = node("time", "journal-entry-date");
    dateBlock.dateTime = entry.sourceMetadata?.tumblr?.publishedAtUtc || entry.entryDate;
    dateBlock.append(node("strong", "", date.day), node("span", "", date.month), node("small", "", date.year));

    const body = node("div", "journal-entry-body");
    const top = node("div", "journal-entry-topline");
    const sourceLabel = isPoem(entry)
      ? entry.sourceType === "tumblr" ? "Wiersz · Tumblr" : "Wiersz"
      : entry.sourceType === "voice-journal" ? "Z dziennika głosowego" : "Wpis własny";
    top.append(node("span", "journal-entry-source", sourceLabel));
    const topMeta = node("div", "journal-entry-top-meta");
    topMeta.append(node("span", "journal-entry-time", date.full));
    const heading = node("h3", "", entry.title || UNTITLED_ENTRY_TITLE);
    const location = entry.location ? node("div", "journal-entry-location", `⌖ ${entry.location}`) : null;
    const content = node("div", "journal-entry-content");
    if (entry.contentFormat === "html") content.innerHTML = sanitizeJournalHtml(entry.content);
    else {
      content.classList.add("is-plain");
      content.textContent = entry.content || "";
    }
    const tags = node("div", "journal-entry-tags");
    (entry.tags || []).forEach((tag) => tags.append(node("span", "", `#${tag}`)));
    body.append(top, heading);
    if (location) body.append(location);
    if (/^data:image\/(?:jpeg|png|webp|gif);base64,/i.test(entry.illustration || "")) {
      const figure = node("figure", "journal-entry-illustration");
      const image = node("img");
      image.src = entry.illustration;
      image.alt = entry.illustrationAlt || "";
      image.loading = "lazy";
      figure.append(image);
      if (entry.illustrationAlt) figure.append(node("figcaption", "", entry.illustrationAlt));
      body.append(figure);
    }
    body.append(content);
    if (tags.childElementCount) body.append(tags);

    if (entry.sourceType === "voice-journal") {
      const details = node("details", "journal-source-details");
      details.append(node("summary", "", "Metadane nagrania"));
      details.append(node("p", "", metadataLine(entry) || "Zachowano metadane wpisu źródłowego."));
      body.append(details);
    }
    if (entry.sourceType === "tumblr") {
      const metadata = entry.sourceMetadata?.tumblr || {};
      const details = node("details", "journal-source-details");
      details.append(node("summary", "", "Źródło: Tumblr"));
      const line = node("p", "", metadata.publishedOriginal || "Zachowano metadane źródłowe Tumblra.");
      details.append(line);
      if (/^https:\/\//i.test(metadata.url || "")) {
        const link = node("a", "", "Otwórz oryginalny post");
        link.href = metadata.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        details.append(link);
      }
      body.append(details);
    }
    if (showContext) body.append(renderEntryContext(entry));

    const makeActions = ({ compact = false } = {}) => {
      const actions = node("div", `journal-entry-actions ${compact ? "is-top" : "is-bottom"}`);
      const edit = node("button", `journal-text-button${compact ? " is-icon" : ""}`, compact ? "✎" : "Edytuj");
      edit.type = "button";
      edit.title = "Edytuj wpis";
      edit.setAttribute("aria-label", "Edytuj wpis");
      edit.addEventListener("click", () => startEdit(entry, article));
      const remove = node("button", `journal-text-button is-danger${compact ? " is-icon" : ""}`, compact ? "×" : "Usuń");
      remove.type = "button";
      remove.title = "Usuń wpis";
      remove.setAttribute("aria-label", "Usuń wpis");
      remove.addEventListener("click", async () => {
      if (!confirmAction(`Usunąć wpis „${entry.title || UNTITLED_ENTRY_TITLE}”?`)) return;
      remove.disabled = true;
      try {
        await removeEntry(entry.id, undefined, entry.version);
        clearDraft(entry.id);
        if (editingId) resetForm();
        await loadEntries();
        listStatus.textContent = "Wpis został usunięty.";
      } catch (error) {
        listStatus.textContent = error?.message || "Nie udało się usunąć wpisu.";
        remove.disabled = false;
      }
      });
      actions.append(edit, remove);
      return actions;
    };
    topMeta.append(makeActions({ compact: true }));
    top.append(topMeta);
    body.append(makeActions());
    article.append(dateBlock, body);
    return article;
  };

  const refreshDateFilters = () => {
    if (!yearFilter || !monthFilter) return;
    const selectedYear = yearFilter.value;
    const selectedMonth = monthFilter.value;
    const viewEntries = entries.filter((entry) => showPoems || !isPoem(entry));
    const periods = viewEntries.map((entry) => journalPeriod(entry.entryDate)).filter(Boolean);
    const years = new Map();
    periods.forEach(({ year }) => years.set(year, (years.get(year) || 0) + 1));
    yearFilter.replaceChildren(optionNode("Wszystkie"));
    [...years.entries()].sort(([a], [b]) => b.localeCompare(a)).forEach(([year, count]) => {
      yearFilter.append(optionNode(`${year} · ${count}`, year));
    });
    if (selectedYear && [...yearFilter.options].some((option) => option.value === selectedYear)) {
      yearFilter.value = selectedYear;
    } else if (!dateFiltersInitialized) {
      const currentYear = String(new Date().getFullYear());
      if ([...yearFilter.options].some((option) => option.value === currentYear)) yearFilter.value = currentYear;
    }
    dateFiltersInitialized = true;

    const months = new Map();
    periods
      .filter(({ year }) => !yearFilter.value || year === yearFilter.value)
      .forEach(({ month }) => months.set(month, (months.get(month) || 0) + 1));
    monthFilter.replaceChildren(optionNode("Wszystkie"));
    [...months.entries()].sort(([a], [b]) => a.localeCompare(b)).forEach(([month, count]) => {
      monthFilter.append(optionNode(`${journalMonthName(month)} · ${count}`, month));
    });
    if ([...monthFilter.options].some((option) => option.value === selectedMonth)) monthFilter.value = selectedMonth;
    else monthFilter.value = "";
    monthFilter.disabled = !months.size;
    filterReset.hidden = !search.value.trim() && !yearFilter.value && !monthFilter.value;
  };

  const renderEntries = () => {
    const query = search.value.trim().toLocaleLowerCase("pl-PL");
    const selectedYear = yearFilter?.value || "";
    const selectedMonth = monthFilter?.value || "";
    const viewEntries = entries.filter((entry) => showPoems || !isPoem(entry));
    const filtered = query
      ? viewEntries.filter((entry) => {
        const period = journalPeriod(entry.entryDate);
        return (!selectedYear || period?.year === selectedYear)
          && (!selectedMonth || period?.month === selectedMonth)
          && [entry.title, entry.location, journalEntryText(entry), entry.illustrationAlt, ...(entry.tags || [])]
            .some((value) => String(value || "").toLocaleLowerCase("pl-PL").includes(query));
      })
      : viewEntries.filter((entry) => {
        const period = journalPeriod(entry.entryDate);
        return (!selectedYear || period?.year === selectedYear)
          && (!selectedMonth || period?.month === selectedMonth);
      });
    list.replaceChildren(...filtered.map(renderCard));
    empty.hidden = filtered.length > 0;
    if (!filtered.length && entries.length) {
      empty.querySelector("strong").textContent = !showPoems && entries.some(isPoem) && !query && !selectedYear && !selectedMonth
        ? "Wiersze są ukryte."
        : "Brak wpisów pasujących do wyszukiwania.";
      empty.querySelector("p").textContent = !showPoems && entries.some(isPoem) && !query && !selectedYear && !selectedMonth
        ? "Włącz „Pokaż wiersze”, aby zobaczyć archiwum poezji."
        : "Spróbuj użyć innego słowa.";
    } else {
      empty.querySelector("strong").textContent = "Jeszcze nie ma tu żadnej strony.";
      empty.querySelector("p").textContent = "Napisz pierwszy wpis albo opublikuj uporządkowaną transkrypcję.";
    }
    if (filterReset) filterReset.hidden = !query && !selectedYear && !selectedMonth;
  };

  const loadContexts = async () => {
    if (!showContext || !entries.length) {
      contexts = {};
      contextError = "";
      contextLoading = false;
      renderEntries();
      return;
    }
    const dates = [...new Set(entries.map(journalContextDay).filter(Boolean))].sort();
    contextLoading = true;
    contextError = "";
    renderEntries();
    try {
      contexts = await fetchContexts(dates);
    } catch (error) {
      contexts = {};
      contextError = error?.message || "Nie udało się wczytać kontekstu z Great Timeline.";
    } finally {
      contextLoading = false;
      renderEntries();
    }
  };

  const loadEntries = async () => {
    listStatus.textContent = "Wczytywanie wpisów…";
    try {
      entries = await fetchEntries();
      refreshDateFilters();
      renderStats();
      renderEntries();
      listStatus.textContent = "";
      if (showContext) await loadContexts();
    } catch (error) {
      listStatus.textContent = error?.message || "Nie udało się wczytać Dziennika.";
      empty.hidden = true;
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    persistCurrentDraft();
    const formattedContent = editorContent();
    let entryDate = "";
    if (dateInput.type === "date") {
      const dateValue = dateInput.value.trim();
      const timeValue = timeInput?.value.trim() || "";
      const date = new Date(`${dateValue}T${timeValue || "00:00"}:00`);
      if (dateValue && !Number.isNaN(date.getTime())) {
        entryDate = timeValue ? date.toISOString() : dateValue;
      }
    } else if (dateInput.type === "text") {
      const parsed = parseJournalDateInput(dateInput.value);
      const timeValue = timeInput?.value.trim() || "";
      const date = parsed && new Date(`${parsed.isoDate}T${timeValue || "00:00"}:00`);
      if (parsed && date && !Number.isNaN(date.getTime())) {
        entryDate = timeValue ? date.toISOString() : parsed.isoDate;
      }
    } else {
      const date = new Date(dateInput.value);
      if (!Number.isNaN(date.getTime())) entryDate = date.toISOString();
    }
    if ((!journalEntryText(formattedContent) && !illustrationData) || !entryDate) {
      setFormStatus("Wpis wymaga treści lub ilustracji oraz prawidłowej daty.", "error");
      return;
    }
    const payload = {
      entryKind: kindInput?.value === "poem" ? "poem" : "journal",
      title: titleInput.value.trim(),
      ...formattedContent,
      entryDate,
      tags: splitJournalTags(tagsInput.value),
      location: locationInput?.value.trim() || "",
      illustration: illustrationData,
      illustrationAlt: illustrationData ? illustrationAltInput?.value.trim() || "" : "",
    };
    submit.disabled = true;
    setFormStatus(editingId ? "Zapisywanie zmian…" : "Zapisywanie wpisu…", "working");
    try {
      const savedDraftId = editingId;
      if (editingId) await updateEntry(editingId, {
        ...payload,
        ...(Number.isInteger(editingVersion) ? { expectedVersion: editingVersion } : {}),
      });
      else await createEntry(payload);
      clearDraft(savedDraftId);
      draftDirty = false;
      resetForm();
      await loadEntries();
      setFormStatus("Zapisano.", "ok");
      window.dispatchEvent(new CustomEvent(JOURNAL_CHANGED_EVENT));
    } catch (error) {
      if (error?.code === "VERSION_CONFLICT") {
        draftDirty = true;
        persistCurrentDraft();
      }
      setFormStatus(error?.message || "Nie udało się zapisać wpisu.", "error");
    } finally {
      submit.disabled = false;
    }
  });
  form.addEventListener("input", scheduleDraftSave);
  form.addEventListener("change", scheduleDraftSave);
  cancelEdit.addEventListener("click", () => {
    persistCurrentDraft();
    resetForm();
  });
  newEntry.addEventListener("click", () => {
    persistCurrentDraft();
    resetForm({ focus: true, open: true });
  });
  newPoem?.addEventListener("click", () => {
    persistCurrentDraft();
    resetForm({ focus: true, entryKind: "poem", open: true });
  });
  kindInput?.addEventListener("change", () => {
    if (editingId) return;
    const poem = kindInput.value === "poem";
    formTitle.textContent = poem ? "Dodaj wiersz" : "Dodaj wpis";
    formKicker.textContent = poem ? "Nowy wiersz" : "Nowa strona";
    submit.textContent = poem ? "Zapisz wiersz" : "Zapisz wpis";
  });
  sourceToggle?.addEventListener("click", () => setSourceMode(!sourceMode));
  editorToolbar?.addEventListener("mousedown", (event) => {
    if (event.target.closest("button")) event.preventDefault();
  });
  editorToolbar?.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || button === sourceToggle || sourceMode) return;
    if (button.dataset.action === "link") {
      const href = (dependencies.promptAction || window.prompt)("Adres linku (https://…):", "https://");
      if (href) {
        document.execCommand?.("createLink", false, href);
        scheduleDraftSave();
      }
      return;
    }
    const command = button.dataset.command;
    if (command) document.execCommand?.(command, false, button.dataset.value || null);
    scheduleDraftSave();
    richEditor?.focus();
  });
  blockSelect?.addEventListener("change", () => {
    if (!sourceMode) document.execCommand?.("formatBlock", false, blockSelect.value);
    scheduleDraftSave();
    richEditor?.focus();
  });
  richEditor?.addEventListener("paste", (event) => {
    const clipboard = event.clipboardData;
    if (!clipboard) return;
    event.preventDefault();
    const html = clipboard.getData("text/html");
    const text = clipboard.getData("text/plain");
    insertEditorHtml(richEditor, html ? sanitizeJournalHtml(html) : journalMarkupToHtml(text));
    scheduleDraftSave();
  });
  illustrationInput?.addEventListener("change", async () => {
    const [file] = illustrationInput.files || [];
    if (!file) return;
    illustrationInput.disabled = true;
    setFormStatus("Przygotowywanie ilustracji…", "working");
    try {
      const dataUrl = await prepareJournalIllustration(file);
      setIllustration(dataUrl, illustrationAltInput?.value || file.name.replace(/\.[^.]+$/, ""), { changed: true });
      scheduleDraftSave();
      setFormStatus("Ilustracja jest gotowa.", "ok");
    } catch (error) {
      setIllustration();
      setFormStatus(error?.message || "Nie udało się przygotować ilustracji.", "error");
    } finally {
      illustrationInput.disabled = false;
    }
  });
  removeIllustration?.addEventListener("click", () => {
    setIllustration("", "", { changed: true });
    scheduleDraftSave();
  });
  search.addEventListener("input", renderEntries);
  yearFilter?.addEventListener("change", () => {
    refreshDateFilters();
    renderEntries();
  });
  monthFilter?.addEventListener("change", renderEntries);
  showPoemsInput?.addEventListener("change", () => {
    showPoems = showPoemsInput.checked;
    try { draftStorage?.setItem(JOURNAL_SHOW_POEMS_KEY, showPoems ? "1" : "0"); } catch { /* storage unavailable */ }
    refreshDateFilters();
    renderEntries();
  });
  showContextInput?.addEventListener("change", async () => {
    showContext = showContextInput.checked;
    try { draftStorage?.setItem(JOURNAL_SHOW_CONTEXT_KEY, showContext ? "1" : "0"); } catch { /* storage unavailable */ }
    if (showContext) await loadContexts();
    else {
      contexts = {};
      contextError = "";
      renderEntries();
    }
  });
  filterReset?.addEventListener("click", () => {
    search.value = "";
    if (yearFilter) yearFilter.value = "";
    if (monthFilter) monthFilter.value = "";
    refreshDateFilters();
    renderEntries();
  });
  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      search.value = "";
      renderEntries();
    }
  });
  window.addEventListener("beforeunload", persistCurrentDraft);

  resetForm();
  await loadEntries();
  return { loadEntries, resetForm, getEntries: () => [...entries] };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("journal-app");
  if (root) initJournalApp(root);
}
