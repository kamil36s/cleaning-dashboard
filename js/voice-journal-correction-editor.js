import {
  audioRangeForItem,
  confidenceState,
  correctedTranscript,
  correctionReviewItems,
  correctionSettings,
  exportCorrection,
  isTextEditingTarget,
  normalizeCorrectionData,
  restoreAllCorrections,
  updateCorrectionItem,
} from "./voice-journal-corrections.js";

const dirtyEditors = new Set();
if (typeof window !== "undefined") window.addEventListener("beforeunload", (event) => {
  if (!dirtyEditors.size) return;
  event.preventDefault();
  event.returnValue = "";
});

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function selectOption(label, value) {
  const option = document.createElement("option");
  option.textContent = label;
  option.value = value;
  return option;
}

function downloadText(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function createVoiceJournalCorrectionEditor(entry, {
  updateEntry,
  retranscribeEntry,
  confirmAction = globalThis.confirm,
  onTranscriptChange,
} = {}) {
  const details = element("details", "voice-journal-correction-editor");
  const summary = element("summary", "voice-journal-correction-summary", "Korekta transkrypcji");
  details.append(summary);
  let initialized = false;
  details.addEventListener("toggle", () => {
    if (!details.open || initialized) return;
    initialized = true;
    mount();
  });

  const mount = () => {
    let data = normalizeCorrectionData(entry);
    let persistedData = JSON.stringify(data);
    let settings = correctionSettings(entry.correctionSettings);
    let history = Array.isArray(entry.correctionHistory) ? [...entry.correctionHistory] : [];
    let selectedId = null;
    let selectedSegment = null;
    let autosaveTimer = null;
    let stopAt = null;

    const body = element("div", "voice-journal-correction-body");
    const player = document.createElement("audio");
    player.controls = true;
    player.preload = "metadata";
    player.src = entry.audioUrl;
    const saveStatus = element("span", "voice-journal-correction-save", "Zapisano");
    saveStatus.setAttribute("aria-live", "polite");
    const saveButton = element("button", "voice-journal-primary", "Zapisz");
    saveButton.type = "button";
    const undoButton = element("button", "voice-journal-entry-action", "Cofnij niezapisane");
    undoButton.type = "button";
    const restoreButton = element("button", "voice-journal-entry-action is-danger", "Przywróć całą oryginalną");
    restoreButton.type = "button";
    const actions = element("div", "voice-journal-correction-top-actions");
    actions.append(saveButton, undoButton, restoreButton, saveStatus);

    const settingsDetails = element("details", "voice-journal-correction-settings");
    settingsDetails.append(element("summary", "", "Ustawienia korekty i skróty"));
    const settingsGrid = element("div", "voice-journal-correction-settings-grid");
    const setting = (labelText, key, type = "number", step = "0.01") => {
      const label = element("label", "", labelText);
      const input = document.createElement("input");
      input.type = type;
      input.step = step;
      input.value = settings[key];
      input.addEventListener("change", () => {
        settings = correctionSettings({ ...settings, [key]: type === "number" ? Number(input.value) : input.value });
        markDirty();
        render();
      });
      label.append(input);
      return label;
    };
    settingsGrid.append(
      setting("Zielony od", "confidenceGood"),
      setting("Żółty od", "confidenceWarning"),
      setting("Niski avg_logprob poniżej", "segmentLogprobThreshold", "number", "0.1"),
      setting("Cofnięcie (s)", "rewindSeconds", "number", "0.5"),
      setting("Znacznik niezrozumiałego", "unintelligibleMarker", "text"),
    );
    const shortcuts = element("p", "voice-journal-shortcuts", "Skróty: Spacja — start/pauza · ←/→ — przewiń · Enter — zatwierdź · Tab/Shift+Tab — następny/poprzedni do sprawdzenia · Ctrl+S — zapisz");
    settingsDetails.append(settingsGrid, shortcuts);

    const legend = element("div", "voice-journal-confidence-legend");
    legend.innerHTML = `<strong>Confidence (wskaźnik pomocniczy, nie gwarancja):</strong>
      <span class="is-good">≥ ${settings.confidenceGood}: wyższe</span>
      <span class="is-warning">${settings.confidenceWarning}–${settings.confidenceGood}: sprawdź</span>
      <span class="is-danger">&lt; ${settings.confidenceWarning}: niskie</span>
      <span class="is-unknown">brak danych confidence</span>`;

    const toolbar = element("div", "voice-journal-correction-toolbar");
    const operationButton = (label, operation) => {
      const button = element("button", "voice-journal-entry-action", label);
      button.type = "button";
      button.dataset.operation = operation;
      return button;
    };
    toolbar.append(
      operationButton("Odtwórz ponownie", "replay"),
      operationButton("Popraw", "correct"),
      operationButton("Niezrozumiałe", "unintelligible"),
      operationButton("Do sprawdzenia", "review"),
      operationButton("Zatwierdź", "approved"),
      operationButton("Przywróć oryginał", "restore"),
    );

    const inlineEditor = element("div", "voice-journal-inline-editor");
    inlineEditor.hidden = true;
    const inlineEditorHeading = element("strong", "voice-journal-inline-editor-heading", "Edycja fragmentu");
    const inlineEditorConfidence = element("span", "voice-journal-inline-editor-confidence");
    const inlineEditorInput = document.createElement("input");
    inlineEditorInput.type = "text";
    inlineEditorInput.setAttribute("aria-label", "Poprawiony tekst wybranego fragmentu");
    const inlineEditorSave = element("button", "voice-journal-inline-editor-save", "✓");
    inlineEditorSave.type = "button";
    inlineEditorSave.title = "Zapisz poprawkę";
    inlineEditorSave.setAttribute("aria-label", "Zapisz poprawkę");
    const inlineEditorCancel = element("button", "voice-journal-inline-editor-cancel", "×");
    inlineEditorCancel.type = "button";
    inlineEditorCancel.title = "Anuluj edycję";
    inlineEditorCancel.setAttribute("aria-label", "Anuluj edycję");
    const inlineEditorActions = element("div", "voice-journal-inline-editor-actions");
    inlineEditorActions.append(inlineEditorInput, inlineEditorSave, inlineEditorCancel);
    inlineEditor.append(inlineEditorHeading, inlineEditorConfidence, inlineEditorActions);

    const confidenceCallout = element("div", "voice-journal-confidence-callout");
    const confidenceCalloutText = element("span", "", "Ten wpis nie zawiera timestampów słów ani confidence. Segmenty nadal możesz poprawiać ręcznie.");
    const confidenceCalloutButton = element("button", "voice-journal-entry-action", "Wygeneruj słowa i confidence");
    confidenceCalloutButton.type = "button";
    const confidenceCalloutStatus = element("span", "voice-journal-confidence-callout-status");
    confidenceCalloutStatus.setAttribute("aria-live", "polite");
    confidenceCallout.append(confidenceCalloutText, confidenceCalloutButton, confidenceCalloutStatus);

    const reviewPanel = element("aside", "voice-journal-review-panel");
    const reviewHead = element("div", "voice-journal-review-head");
    reviewHead.append(element("strong", "", "Do sprawdzenia"));
    const reviewFilter = document.createElement("select");
    reviewFilter.setAttribute("aria-label", "Filtr listy do sprawdzenia");
    [["all", "Wszystkie"], ["danger", "Czerwone"], ["warning", "Żółte"], ["manual", "Oznaczone ręcznie"], ["unintelligible", "Niezrozumiałe"], ["corrected", "Poprawione"], ["approved", "Zatwierdzone"]].forEach(([value, label]) => reviewFilter.add(selectOption(label, value)));
    reviewHead.append(reviewFilter);
    const reviewList = element("div", "voice-journal-review-list");
    reviewPanel.append(reviewHead, reviewList);

    const segmentsRoot = element("div", "voice-journal-correction-segments");
    const editorGrid = element("div", "voice-journal-correction-grid");
    editorGrid.append(reviewPanel, segmentsRoot);

    const exportRow = element("div", "voice-journal-export-row");
    const exportVersion = document.createElement("select");
    exportVersion.add(selectOption("Tekst po korekcie", "corrected"));
    exportVersion.add(selectOption("Tekst oryginalny", "original"));
    ["txt", "json", "srt", "vtt"].forEach((format) => {
      const button = operationButton(format.toUpperCase(), `export-${format}`);
      exportRow.append(button);
    });
    exportRow.prepend(element("span", "", "Eksport:"), exportVersion);

    const historyDetails = element("details", "voice-journal-correction-history");
    historyDetails.append(element("summary", "", `Historia zmian (${history.length})`));
    const historyList = element("ol");
    historyDetails.append(historyList);

    const playRange = (item, segment) => {
      const range = audioRangeForItem(item, segment, 1);
      player.currentTime = range.start;
      stopAt = range.end;
      player.play().catch(() => {});
    };
    player.addEventListener("timeupdate", () => {
      if (stopAt !== null && player.currentTime >= stopAt) {
        player.pause();
        stopAt = null;
      }
    });

    const selectedItem = () => {
      const segment = data.segments.find((candidate) => candidate.id === selectedSegment?.id);
      const item = segment?.id === selectedId ? segment : segment?.words.find((word) => word.id === selectedId);
      return { segment, item };
    };
    const closeInlineEditor = () => {
      inlineEditor.hidden = true;
      inlineEditorInput.value = "";
      body.append(inlineEditor);
    };
    const selectItem = (id, segment, item, shouldPlay = false) => {
      selectedId = id;
      selectedSegment = segment;
      segmentsRoot.querySelectorAll(".is-current").forEach((node) => node.classList.remove("is-current"));
      [...segmentsRoot.querySelectorAll("[data-correction-id]")]
        .find((node) => node.dataset.correctionId === id)
        ?.classList.add("is-current");
      if (shouldPlay) playRange(item, segment);
    };
    const openInlineEditor = (id, segment, item, anchor, shouldPlay = false) => {
      selectItem(id, segment, item, shouldPlay);
      inlineEditorHeading.textContent = item === segment ? "Edycja segmentu" : "Edycja słowa";
      inlineEditorInput.value = item.correctedText || item.originalText || "";
      inlineEditorConfidence.textContent = item === segment
        ? "Confidence słów nie dotyczy całego segmentu."
        : (item.probability === null || item.probability === undefined
          ? "Confidence: brak danych"
          : `Confidence: ${Math.round(item.probability * 100)}% (${item.probability.toFixed(3)})`);
      anchor.insertAdjacentElement("afterend", inlineEditor);
      inlineEditor.hidden = false;
      inlineEditorInput.focus();
      inlineEditorInput.select();
    };

    const save = async () => {
      clearTimeout(autosaveTimer);
      if (!dirtyEditors.has(details)) return;
      saveStatus.textContent = "Zapisywanie…";
      try {
        const transcript = correctedTranscript(data);
        const updatedEntry = await updateEntry(entry.id, { transcript, transcriptionData: data, correctionHistory: history, correctionSettings: settings });
        if (updatedEntry && typeof updatedEntry === "object") Object.assign(entry, updatedEntry);
        entry.transcript = transcript;
        entry.transcriptionData = data;
        entry.correctionHistory = history;
        entry.correctionSettings = settings;
        persistedData = JSON.stringify(data);
        dirtyEditors.delete(details);
        saveStatus.textContent = "Zapisano";
        onTranscriptChange?.({ entry, transcript, transcriptionData: data });
      } catch (error) {
        saveStatus.textContent = `Błąd zapisu: ${error?.message || "nieznany błąd"}`;
      }
    };
    const markDirty = () => {
      dirtyEditors.add(details);
      saveStatus.textContent = "Niezapisane zmiany";
      clearTimeout(autosaveTimer);
      autosaveTimer = setTimeout(save, 1200);
    };
    const applyOperation = (operation, value) => {
      if (!selectedId) return false;
      const result = updateCorrectionItem(data, selectedId, operation, operation === "unintelligible" ? settings.unintelligibleMarker : value);
      if (!result.historyItem) return false;
      data = result.data;
      history.push(result.historyItem);
      markDirty();
      render();
      return true;
    };

    const render = () => {
      if (inlineEditor.parentNode && inlineEditor.parentNode !== body) body.append(inlineEditor);
      inlineEditor.hidden = true;
      legend.querySelector(".is-good").textContent = `≥ ${settings.confidenceGood}: wyższe`;
      legend.querySelector(".is-warning").textContent = `${settings.confidenceWarning}–${settings.confidenceGood}: sprawdź`;
      legend.querySelector(".is-danger").textContent = `< ${settings.confidenceWarning}: niskie`;
      const wordCount = data.segments.reduce((count, segment) => count + segment.words.length, 0);
      confidenceCallout.hidden = wordCount > 0;
      confidenceCalloutButton.hidden = typeof retranscribeEntry !== "function";
      segmentsRoot.replaceChildren();
      data.segments.forEach((segment) => {
        const section = element("section", "voice-journal-correction-segment");
        section.id = `correction-${entry.id}-${segment.id}`;
        section.dataset.correctionId = segment.id;
        const timestamp = element("button", "voice-journal-timestamp", `[${Math.floor((segment.start || 0) / 60)}:${String(Math.floor((segment.start || 0) % 60)).padStart(2, "0")}]`);
        timestamp.type = "button";
        timestamp.addEventListener("click", () => openInlineEditor(segment.id, segment, segment, timestamp, true));
        section.append(timestamp);
        const words = element("div", "voice-journal-correction-words");
        if (segment.words.length) {
          segment.words.forEach((word) => {
            const state = confidenceState(word.probability, settings, word.correctionStatus);
            const button = element("button", `voice-journal-word is-${state}`);
            button.type = "button";
            button.dataset.correctionId = word.id;
            button.title = word.probability === null ? "Brak danych confidence" : `Confidence: ${word.probability.toFixed(3)}; status: ${word.correctionStatus}`;
            button.setAttribute("aria-label", `${word.correctedText || word.originalText}; ${button.title}`);
            button.append(
              document.createTextNode(word.correctedText || word.originalText),
              element("small", "voice-journal-word-confidence-value", word.probability === null ? "—" : `${Math.round(word.probability * 100)}%`),
            );
            button.addEventListener("click", () => openInlineEditor(word.id, segment, word, button, true));
            words.append(button);
          });
        } else {
          words.append(element("span", "voice-journal-confidence-missing", "Brak timestampów słów i danych confidence — dostępny jest czas segmentu."));
        }
        const segmentText = element("button", "voice-journal-segment-edit-trigger", segment.correctedText || segment.originalText);
        segmentText.type = "button";
        segmentText.dataset.correctionId = segment.id;
        segmentText.title = "Kliknij, aby poprawić cały segment";
        segmentText.setAttribute("aria-label", `Edytuj segment: ${segment.correctedText || segment.originalText}`);
        segmentText.addEventListener("click", () => openInlineEditor(segment.id, segment, segment, segmentText));
        section.append(words, segmentText);
        segmentsRoot.append(section);
      });
      const reviewItems = correctionReviewItems(data, settings, reviewFilter.value);
      reviewList.replaceChildren(...reviewItems.slice(0, 500).map((item) => {
        const button = element("button", `voice-journal-review-item is-${item.kind}`, item.label || item.id);
        button.type = "button";
        button.addEventListener("click", () => {
          const segment = data.segments.find((candidate) => candidate.id === item.segmentId);
          const target = item.wordId ? segment?.words.find((word) => word.id === item.wordId) : segment;
          if (!segment || !target) return;
          const section = document.getElementById(`correction-${entry.id}-${segment.id}`);
          section?.scrollIntoView({ behavior: "smooth", block: "center" });
          const anchor = [...(section?.querySelectorAll("[data-correction-id]") || [])]
            .find((node) => node.dataset.correctionId === item.id) || section?.querySelector(".voice-journal-segment-edit-trigger");
          if (anchor) openInlineEditor(item.id, segment, target, anchor, true);
        });
        return button;
      }));
      if (!reviewItems.length) reviewList.append(element("p", "", "Brak elementów w tym filtrze."));
      historyDetails.firstElementChild.textContent = `Historia zmian (${history.length})`;
      historyList.replaceChildren(...history.slice(-100).reverse().map((item) => element("li", "", `${new Date(item.at).toLocaleString("pl-PL")} · ${item.operation} · ${item.targetId}: „${item.previousValue}” → „${item.newValue}”`)));
    };

    toolbar.addEventListener("click", (event) => {
      const operation = event.target.closest("button")?.dataset.operation;
      if (!operation) return;
      if (operation === "replay") {
        const { segment, item } = selectedItem();
        if (item) playRange(item, segment);
      } else if (operation === "correct") {
        const { segment, item } = selectedItem();
        const anchor = [...segmentsRoot.querySelectorAll("[data-correction-id]")]
          .find((node) => node.dataset.correctionId === selectedId);
        if (segment && item && anchor) openInlineEditor(selectedId, segment, item, anchor);
      } else {
        closeInlineEditor();
        applyOperation(operation);
      }
    });
    inlineEditorSave.addEventListener("click", async () => {
      const value = inlineEditorInput.value;
      closeInlineEditor();
      if (applyOperation("correct", value)) await save();
    });
    inlineEditorCancel.addEventListener("click", closeInlineEditor);
    inlineEditorInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeInlineEditor();
      } else if (event.key === "Enter") {
        event.preventDefault();
        inlineEditorSave.click();
      }
    });
    confidenceCalloutButton.addEventListener("click", async () => {
      if (typeof retranscribeEntry !== "function") return;
      confidenceCalloutButton.disabled = true;
      confidenceCalloutStatus.textContent = "Przygotowywanie ponownej transkrypcji…";
      try {
        const updatedEntry = await retranscribeEntry(entry, (message) => {
          confidenceCalloutStatus.textContent = String(message || "Przetwarzanie…");
        });
        Object.assign(entry, updatedEntry);
        data = normalizeCorrectionData(entry);
        persistedData = JSON.stringify(data);
        history = Array.isArray(entry.correctionHistory) ? [...entry.correctionHistory] : history;
        dirtyEditors.delete(details);
        saveStatus.textContent = data.segments.some((segment) => segment.words.length)
          ? "Wygenerowano confidence słów"
          : "Transkrypcja nadal nie zwróciła confidence słów";
        onTranscriptChange?.({
          entry,
          transcript: correctedTranscript(data),
          transcriptionData: data,
        });
        render();
      } catch (error) {
        confidenceCalloutStatus.textContent = `Błąd: ${error?.message || "nie udało się przeliczyć wpisu"}`;
      } finally {
        confidenceCalloutButton.disabled = false;
      }
    });
    reviewFilter.addEventListener("change", render);
    saveButton.addEventListener("click", save);
    undoButton.addEventListener("click", () => {
      data = JSON.parse(persistedData);
      dirtyEditors.delete(details);
      saveStatus.textContent = "Cofnięto niezapisane zmiany";
      render();
    });
    restoreButton.addEventListener("click", () => {
      if (!confirmAction?.("Przywrócić całą transkrypcję do wersji pierwotnej? Audio nie zostanie usunięte.")) return;
      const restored = restoreAllCorrections(data);
      data = restored.data;
      history.push(...restored.history);
      markDirty();
      render();
    });
    exportRow.addEventListener("click", (event) => {
      const operation = event.target.closest("button")?.dataset.operation;
      if (!operation?.startsWith("export-")) return;
      const format = operation.slice(7);
      const content = exportCorrection(data, history, format, exportVersion.value);
      downloadText(`dziennik-${entry.id}-${exportVersion.value}.${format}`, content, format === "json" ? "application/json" : "text/plain");
    });
    body.addEventListener("keydown", (event) => {
      if (event.ctrlKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        save();
        return;
      }
      if (isTextEditingTarget(event.target)) return;
      if (event.code === "Space") {
        event.preventDefault();
        player.paused ? player.play().catch(() => {}) : player.pause();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        player.currentTime = Math.max(0, player.currentTime + (event.key === "ArrowLeft" ? -settings.rewindSeconds : settings.rewindSeconds));
      } else if (event.key === "Enter") {
        event.preventDefault();
        applyOperation("approved");
      } else if (event.key === "Tab") {
        const items = correctionReviewItems(data, settings, reviewFilter.value);
        if (!items.length) return;
        event.preventDefault();
        const index = Math.max(0, items.findIndex((item) => item.id === selectedId));
        const next = items[(index + (event.shiftKey ? -1 : 1) + items.length) % items.length];
        reviewList.querySelectorAll("button")[[...reviewList.querySelectorAll("button")].findIndex((button) => button.textContent === next.label)]?.click();
      }
    });

    body.append(player, actions, settingsDetails, legend, confidenceCallout, toolbar, editorGrid, inlineEditor, exportRow, historyDetails);
    details.append(body);
    render();
  };
  return details;
}
