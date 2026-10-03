import { escapeHtml } from "./utils.js";

import {
  buildCallScript,
  buildCallScriptText,
  buildLeadCopyText,
  buildPreferenceHighlights,
  buildPreferenceStats,
  buildSearchPresets,
  DEFAULT_FLAT_HUNT_DRAFT,
  DEFAULT_FLAT_HUNT_PREFERENCES,
  FLAT_CATEGORY_LABELS,
  FLAT_FACTOR_DEFINITIONS,
  FLAT_IMPORTANCE_LABELS,
  formatFlatMoney,
  normalizeFlatPreferences,
  scoreFlatListing,
} from "./flat-hunt-model.js";

const STORAGE_KEY = "flatHuntWidget.v2";
const card = document.getElementById("flat-hunt-card");

function cloneDraft(input = DEFAULT_FLAT_HUNT_DRAFT) {
  return {
    title: String(input.title ?? ""),
    district: String(input.district ?? ""),
    notes: String(input.notes ?? ""),
    totalPrice: String(input.totalPrice ?? ""),
    totalArea: String(input.totalArea ?? ""),
    mainRoomArea: String(input.mainRoomArea ?? ""),
    windowsCount: String(input.windowsCount ?? ""),
    location: String(input.location ?? "unknown"),
    buildingType: String(input.buildingType ?? "unknown"),
    floor: String(input.floor ?? "unknown"),
    light: String(input.light ?? "unknown"),
    condition: String(input.condition ?? "unknown"),
    heatingType: String(input.heatingType ?? "unknown"),
    deskAndBed: String(input.deskAndBed ?? "unknown"),
    kitchen: String(input.kitchen ?? "unknown"),
    bathroom: String(input.bathroom ?? "unknown"),
    internetReady: String(input.internetReady ?? "unknown"),
    washingMachine: String(input.washingMachine ?? "unknown"),
    quiet: String(input.quiet ?? "unknown"),
    storage: String(input.storage ?? "unknown"),
    whiteWall: String(input.whiteWall ?? "unknown"),
    balcony: String(input.balcony ?? "unknown"),
    elevator: String(input.elevator ?? "unknown"),
  };
}

function clonePreferences(input = DEFAULT_FLAT_HUNT_PREFERENCES) {
  const normalized = normalizeFlatPreferences(input);
  const output = {};
  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    const value = normalized[definition.id] || { importance: "ignore" };
    output[definition.id] = {
      importance: String(value.importance || "ignore"),
    };
    if ("target" in value) {
      output[definition.id].target = value.target;
    }
  }
  return output;
}

function createId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `lead-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function createLeadFingerprint(listing) {
  return [listing.title, listing.district, listing.totalPrice, listing.totalArea, listing.mainRoomArea]
    .join("::")
    .toLowerCase();
}

function formatDateTime(value) {
  const dt = new Date(value);
  if (!Number.isFinite(dt.getTime())) return "teraz";
  return dt.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return {
      preferences: clonePreferences(parsed?.preferences),
      draft: cloneDraft(parsed?.draft),
      leads: Array.isArray(parsed?.leads) ? parsed.leads : [],
    };
  } catch (error) {
    console.warn("flat-hunt widget: failed to read stored state", error);
    return null;
  }
}

function saveState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    console.warn("flat-hunt widget: failed to save state", error);
  }
}

function sortLeads(items) {
  return [...items].sort((a, b) =>
    (Number(b.score) || 0) - (Number(a.score) || 0)
    || String(b.updatedAt || "").localeCompare(String(a.updatedAt || ""))
    || String(a.title || "").localeCompare(String(b.title || ""), "pl"));
}

function groupDefinitionsByCategory() {
  const groups = new Map();
  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    if (!groups.has(definition.category)) groups.set(definition.category, []);
    groups.get(definition.category).push(definition);
  }
  return groups;
}

const GROUPS = groupDefinitionsByCategory();
const IMPORTANCE_OPTIONS = [
  { value: "ignore", label: FLAT_IMPORTANCE_LABELS.ignore },
  { value: "nice", label: FLAT_IMPORTANCE_LABELS.nice },
  { value: "important", label: FLAT_IMPORTANCE_LABELS.important },
  { value: "must", label: FLAT_IMPORTANCE_LABELS.must },
];

if (card) {
  const elements = {
    budgetChip: document.getElementById("flat-budget-chip"),
    kpis: document.getElementById("flat-kpis"),
    highlights: document.getElementById("flat-highlights"),
    preferencesGrid: document.getElementById("flat-preferences-grid"),
    resetPreferencesBtn: document.getElementById("flat-reset-preferences"),
    searchList: document.getElementById("flat-search-list"),
    form: document.getElementById("flat-form"),
    titleInput: document.getElementById("flat-title-input"),
    districtInput: document.getElementById("flat-district-input"),
    listingFields: document.getElementById("flat-listing-fields"),
    notesInput: document.getElementById("flat-notes-input"),
    scoreValue: document.getElementById("flat-score-value"),
    scoreVerdict: document.getElementById("flat-score-verdict"),
    scoreNote: document.getElementById("flat-score-note"),
    scoreBudget: document.getElementById("flat-score-budget"),
    positivesList: document.getElementById("flat-positives-list"),
    warningsList: document.getElementById("flat-warnings-list"),
    blockersList: document.getElementById("flat-blockers-list"),
    breakdown: document.getElementById("flat-breakdown"),
    saveLeadBtn: document.getElementById("flat-save-lead"),
    resetDraftBtn: document.getElementById("flat-reset-draft"),
    callScript: document.getElementById("flat-call-script"),
    copyScriptBtn: document.getElementById("flat-copy-script"),
    resetScriptBtn: document.getElementById("flat-reset-script"),
    leads: document.getElementById("flat-leads"),
    clearLeadsBtn: document.getElementById("flat-clear-leads"),
    status: document.getElementById("flat-status"),
  };

  let state = loadState() || {
    preferences: clonePreferences(),
    draft: cloneDraft(),
    leads: [],
  };
  let searchPresets = [];
  let searchPresetMap = new Map();
  let scriptSections = [];
  let scriptSectionMap = new Map();
  let statusTimer = 0;

  function setStatus(message, tone = "neutral") {
    if (!elements.status) return;
    if (statusTimer) clearTimeout(statusTimer);
    elements.status.textContent = message;
    elements.status.className = `flat-status${tone !== "neutral" ? ` is-${tone}` : ""}`;
    if (message) {
      statusTimer = window.setTimeout(() => {
        elements.status.textContent = "";
        elements.status.className = "flat-status";
      }, 2800);
    }
  }

  async function copyText(text, successMessage) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.top = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      setStatus(successMessage, "success");
    } catch (error) {
      console.warn("flat-hunt widget: failed to copy", error);
      setStatus("Nie udało się skopiować. Spróbuj jeszcze raz.", "danger");
    }
  }

  function renderList(target, items, emptyText) {
    if (!target) return;
    if (!items.length) {
      target.innerHTML = `<li class="flat-feedback-empty">${escapeHtml(emptyText)}</li>`;
      return;
    }
    target.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  }

  function populateStaticFields() {
    elements.titleInput.value = state.draft.title;
    elements.districtInput.value = state.draft.district;
    elements.notesInput.value = state.draft.notes;
  }

  function renderPreferenceSummary() {
    const stats = buildPreferenceStats(state.preferences);
    const highlights = buildPreferenceHighlights(state.preferences, 10);

    if (elements.budgetChip) {
      elements.budgetChip.textContent = stats.budget != null ? `budget ${formatFlatMoney(stats.budget)}` : "ustaw swoje kryteria";
    }

    if (elements.kpis) {
      const cards = [
        { label: "Must-have", value: stats.must, note: "kryteria twarde" },
        { label: "Ważne", value: stats.important, note: "mocno liczone w score" },
        { label: "Miło mieć", value: stats.nice, note: "bonusy i tie-breakery" },
        { label: "Aktywne", value: stats.active, note: "wszystkie liczące się rzeczy" },
        { label: "Budżet", value: stats.budget != null ? formatFlatMoney(stats.budget) : "-", note: "jeżeli ustawiony" },
      ];
      elements.kpis.innerHTML = cards.map((item) => `
        <article class="flat-kpi">
          <div class="flat-kpi-label">${escapeHtml(item.label)}</div>
          <div class="flat-kpi-value">${escapeHtml(item.value)}</div>
          <div class="flat-kpi-note">${escapeHtml(item.note)}</div>
        </article>
      `).join("");
    }

    if (elements.highlights) {
      elements.highlights.innerHTML = highlights.length
        ? highlights.map((chip) => `<span class="flat-highlight">${escapeHtml(chip)}</span>`).join("")
        : `<span class="flat-highlight">Najpierw ustaw kryteria, potem score zacznie mieć sens.</span>`;
    }
  }

  function renderPreferences() {
    if (!elements.preferencesGrid) return;
    const preferences = normalizeFlatPreferences(state.preferences);
    elements.preferencesGrid.innerHTML = [...GROUPS.entries()].map(([category, definitions]) => `
      <section class="flat-pref-section">
        <div class="flat-pref-section-head">
          <div class="flat-pref-section-title">${escapeHtml(FLAT_CATEGORY_LABELS[category] || category)}</div>
        </div>
        <div class="flat-pref-section-grid">
          ${definitions.map((definition) => {
            const preference = preferences[definition.id];
            const targetMarkup = definition.preferenceInput
              ? (definition.preferenceInput.type === "number"
                ? `
                  <label class="flat-field flat-field--compact">
                    <span class="flat-field-label">${escapeHtml(definition.preferenceInput.label)}</span>
                    <input
                      class="flat-input"
                      type="number"
                      step="${escapeHtml(definition.preferenceInput.step || "1")}"
                      placeholder="${escapeHtml(definition.preferenceInput.placeholder || "")}"
                      value="${escapeHtml(preference.target ?? "")}"
                      data-pref-id="${definition.id}"
                      data-pref-field="target"
                    />
                  </label>
                `
                : `
                  <label class="flat-field flat-field--compact">
                    <span class="flat-field-label">${escapeHtml(definition.preferenceInput.label)}</span>
                    <select class="flat-select" data-pref-id="${definition.id}" data-pref-field="target">
                      ${definition.preferenceInput.options.map((option) => `
                        <option value="${escapeHtml(option.value)}"${option.value === preference.target ? " selected" : ""}>${escapeHtml(option.label)}</option>
                      `).join("")}
                    </select>
                  </label>
                `)
              : `<div class="flat-pref-note">Tu wystarczy sama waga.</div>`;

            return `
              <article class="flat-pref-card">
                <div class="flat-pref-top">
                  <div>
                    <div class="flat-pref-name">${escapeHtml(definition.label)}</div>
                    <div class="flat-pref-desc">${escapeHtml(definition.description)}</div>
                  </div>
                  <label class="flat-field flat-field--compact">
                    <span class="flat-field-label">Waga</span>
                    <select class="flat-select" data-pref-id="${definition.id}" data-pref-field="importance">
                      ${IMPORTANCE_OPTIONS.map((option) => `
                        <option value="${escapeHtml(option.value)}"${option.value === preference.importance ? " selected" : ""}>${escapeHtml(option.label)}</option>
                      `).join("")}
                    </select>
                  </label>
                </div>
                <div class="flat-pref-controls">${targetMarkup}</div>
              </article>
            `;
          }).join("")}
        </div>
      </section>
    `).join("");
  }

  function renderListingFields() {
    if (!elements.listingFields) return;
    elements.listingFields.innerHTML = [...GROUPS.entries()].map(([category, definitions]) => `
      <section class="flat-factor-section">
        <div class="flat-factor-title">${escapeHtml(FLAT_CATEGORY_LABELS[category] || category)}</div>
        <div class="flat-factor-grid">
          ${definitions.map((definition) => {
            const value = state.draft[definition.listingKey] ?? "";
            if (definition.listingInput.type === "number") {
              return `
                <label class="flat-field" for="flat-listing-${definition.listingKey}">
                  <span class="flat-field-label">${escapeHtml(definition.listingInput.label)}</span>
                  <input
                    class="flat-input"
                    id="flat-listing-${definition.listingKey}"
                    type="number"
                    step="${escapeHtml(definition.listingInput.step || "1")}"
                    placeholder="${escapeHtml(definition.listingInput.placeholder || "")}"
                    value="${escapeHtml(value)}"
                    data-listing-key="${definition.listingKey}"
                  />
                </label>
              `;
            }
            return `
              <label class="flat-field" for="flat-listing-${definition.listingKey}">
                <span class="flat-field-label">${escapeHtml(definition.listingInput.label)}</span>
                <select class="flat-select" id="flat-listing-${definition.listingKey}" data-listing-key="${definition.listingKey}">
                  ${definition.listingInput.options.map((option) => `
                    <option value="${escapeHtml(option.value)}"${option.value === value ? " selected" : ""}>${escapeHtml(option.label)}</option>
                  `).join("")}
                </select>
              </label>
            `;
          }).join("")}
        </div>
      </section>
    `).join("");
  }

  function renderSearchPresets() {
    if (!elements.searchList) return;
    searchPresets = buildSearchPresets(state.preferences);
    searchPresetMap = new Map(searchPresets.map((preset) => [preset.key, preset]));
    elements.searchList.innerHTML = searchPresets.map((preset) => `
      <article class="flat-search-card">
        <div class="flat-search-card-head">
          <div>
            <div class="flat-search-label">${escapeHtml(preset.label)}</div>
            <div class="flat-search-desc">${escapeHtml(preset.description)}</div>
          </div>
          <div class="flat-search-site">${escapeHtml(preset.siteLabel)}</div>
        </div>
        <div class="flat-query">${escapeHtml(preset.query)}</div>
        <div class="flat-search-actions">
          <button class="budget-action" type="button" data-action="open-search" data-key="${preset.key}">Otwórz</button>
          <button class="budget-action budget-action--ghost" type="button" data-action="copy-query" data-key="${preset.key}">Kopiuj fraz?</button>
        </div>
      </article>
    `).join("");
  }

  function renderCallScript() {
    if (!elements.callScript) return;
    scriptSections = buildCallScript(state.preferences);
    scriptSectionMap = new Map(scriptSections.map((section) => [section.key, section]));
    elements.callScript.innerHTML = scriptSections.map((section) => `
      <article class="flat-script-block">
        <div class="flat-script-head">
          <div>
            <div class="flat-script-title">${escapeHtml(section.title)}</div>
            <div class="flat-script-meta">${escapeHtml(section.meta)}</div>
          </div>
          <button class="budget-action budget-action--ghost" type="button" data-action="copy-script-section" data-key="${section.key}">Kopiuj</button>
        </div>
        <div class="flat-script-items">
          ${section.items.map((item, index) => `
            <label class="flat-script-item">
              <input type="checkbox" data-script-key="${section.key}" data-script-index="${index}" />
              <span>${escapeHtml(item)}</span>
            </label>
          `).join("")}
        </div>
      </article>
    `).join("");
  }

  function collectDraftFromDom() {
    const next = cloneDraft(state.draft);
    next.title = elements.titleInput.value.trim();
    next.district = elements.districtInput.value.trim();
    next.notes = elements.notesInput.value.trim();
    elements.form.querySelectorAll("[data-listing-key]").forEach((input) => {
      next[input.dataset.listingKey] = input.value;
    });
    return next;
  }

  function collectPreferencesFromDom() {
    const next = clonePreferences(state.preferences);
    elements.preferencesGrid.querySelectorAll("[data-pref-id]").forEach((input) => {
      const id = input.dataset.prefId;
      const field = input.dataset.prefField;
      if (!next[id]) next[id] = {};
      next[id][field] = input.value;
    });
    return next;
  }

  function applyVerdictTone(target, tone) {
    if (!target) return;
    target.classList.remove("is-excellent", "is-good", "is-maybe", "is-bad");
    target.classList.add(`is-${tone}`);
  }

  function detailTone(detail) {
    if (detail.state === "match") return "match";
    if (detail.state === "fail" && detail.importance === "must") return "fail";
    if (detail.state === "unknown") return "unknown";
    return "warn";
  }

  function detailStateLabel(detail) {
    if (detail.state === "match") return "spełnia";
    if (detail.state === "unknown") return "brak danych";
    if (detail.importance === "must") return "nie spełnia";
    return "do sprawdzenia";
  }

  function getEvaluation() {
    return scoreFlatListing(state.draft, state.preferences);
  }

  function renderBreakdown(details) {
    if (!elements.breakdown) return;
    if (!details.length) {
      elements.breakdown.innerHTML = `<div class="flat-empty">Najpierw ustaw przynajmniej jedno aktywne kryterium.</div>`;
      return;
    }
    elements.breakdown.innerHTML = `
      <div class="flat-breakdown-head">
        <div class="flat-panel-title">Rozklad score</div>
        <div class="flat-panel-meta">Każde aktywne kryterium pokazuje, czy oferta je spełnia, oblewa, czy po prostu brakuje danych.</div>
      </div>
      <div class="flat-breakdown-list">
        ${details.map((detail) => `
          <article class="flat-detail is-${detailTone(detail)}">
            <div class="flat-detail-head">
              <div>
                <div class="flat-detail-name">${escapeHtml(detail.label)}</div>
                <div class="flat-detail-meta">${escapeHtml(detail.targetSummary || detail.categoryLabel)}</div>
              </div>
              <div class="flat-detail-pills">
                <span class="flat-detail-pill">${escapeHtml(detail.importanceLabel)}</span>
                <span class="flat-detail-pill is-${detailTone(detail)}">${escapeHtml(detailStateLabel(detail))}</span>
              </div>
            </div>
            <div class="flat-detail-copy">${escapeHtml(detail.message)}</div>
            <div class="flat-detail-copy flat-detail-copy--muted">Oferta: ${escapeHtml(detail.actualSummary || "brak danych")}</div>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderEvaluation() {
    const evaluation = getEvaluation();
    const primaryMessage =
      evaluation.blockers[0]
      || evaluation.warnings[0]
      || evaluation.positives[0]
      || "Ustaw kryteria i wrzuć dane mieszkania, a score zacznie mieć sens.";

    elements.scoreValue.textContent = String(evaluation.score);
    elements.scoreVerdict.textContent = evaluation.verdict;
    elements.scoreNote.textContent = primaryMessage;
    applyVerdictTone(elements.scoreVerdict, evaluation.verdictTone);

    if (evaluation.budgetSlack == null) {
      elements.scoreBudget.textContent = "Zapas do limitu: brak budżetu albo ceny";
    } else if (evaluation.budgetSlack >= 0) {
      elements.scoreBudget.textContent = `Zapas do limitu: ${formatFlatMoney(evaluation.budgetSlack)}`;
    } else {
      elements.scoreBudget.textContent = `Ponad limitem o ${formatFlatMoney(Math.abs(evaluation.budgetSlack))}`;
    }

    renderList(elements.positivesList, evaluation.positives.slice(0, 6), "Jeszcze brak potwierdzonych plusów.");
    renderList(elements.warningsList, evaluation.warnings.slice(0, 6), "Na razie czysto.");
    renderList(elements.blockersList, evaluation.blockers.slice(0, 6), "Brak twardych blockerów.");
    renderBreakdown(evaluation.details);
  }

  function leadMetaLine(lead) {
    const parts = [];
    if (lead.district) parts.push(lead.district);
    if (lead.totalPrice != null) parts.push(formatFlatMoney(lead.totalPrice));
    if (lead.totalArea != null) parts.push(`${lead.totalArea} m2 całość`);
    if (lead.mainRoomArea != null) parts.push(`${lead.mainRoomArea} m2 pokój`);
    if (lead.location && lead.location !== "unknown") parts.push(lead.location);
    return parts.join(" | ");
  }

  function renderLeads() {
    if (!elements.leads) return;
    const leads = sortLeads(state.leads);
    if (!leads.length) {
      elements.leads.innerHTML = `<div class="flat-empty">Tu będą siedzieć mieszkania, które przeszły przez Twój aktualny system preferencji.</div>`;
      return;
    }

    elements.leads.innerHTML = leads.map((lead) => {
      const note = lead.notes || lead.blockers?.[0] || lead.warnings?.[0] || lead.positives?.[0] || "Bez dodatkowych notatek.";
      return `
        <article class="flat-lead">
          <div class="flat-lead-score is-${escapeHtml(lead.verdictTone || "bad")}">${escapeHtml(lead.score)}</div>
          <div class="flat-lead-body">
            <div class="flat-lead-head">
              <div class="flat-lead-title">${escapeHtml(lead.title || "Bez nazwy")}</div>
              <div class="flat-score-pill is-${escapeHtml(lead.verdictTone || "bad")}">${escapeHtml(lead.verdict || "Raczej nie")}</div>
            </div>
            <div class="flat-lead-meta">${escapeHtml(leadMetaLine(lead) || "Brak podstawowych danych.")}</div>
            <div class="flat-lead-note">${escapeHtml(note)}</div>
            <div class="flat-lead-note">Zapisane: ${escapeHtml(formatDateTime(lead.updatedAt))}</div>
          </div>
          <div class="flat-lead-tools">
            <button class="budget-action budget-action--ghost" type="button" data-action="copy-lead" data-id="${lead.id}">Kopiuj</button>
            <button class="budget-action budget-action--ghost" type="button" data-action="remove-lead" data-id="${lead.id}">Usu?</button>
          </div>
        </article>
      `;
    }).join("");
  }

  function rerenderPreferenceDrivenViews() {
    state.preferences = normalizeFlatPreferences(state.preferences);
    renderPreferenceSummary();
    renderSearchPresets();
    renderCallScript();
    renderEvaluation();
  }

  function saveCurrentLead() {
    const evaluation = getEvaluation();
    const listing = evaluation.listing;
    const fingerprint = createLeadFingerprint(listing);
    const existing = state.leads.find((lead) => lead.fingerprint === fingerprint);

    const lead = {
      ...listing,
      id: existing?.id || createId(),
      fingerprint,
      score: evaluation.score,
      verdict: evaluation.verdict,
      verdictTone: evaluation.verdictTone,
      positives: evaluation.positives,
      warnings: evaluation.warnings,
      blockers: evaluation.blockers,
      updatedAt: new Date().toISOString(),
    };

    state.leads = [lead, ...state.leads.filter((item) => item.id !== lead.id)].slice(0, 12);
    saveState(state);
    renderLeads();
    setStatus(existing ? "Lead zaktualizowany pod obecne kryteria." : "Lead zapisany do shortlisty.", "success");
  }

  function wireEvents() {
    elements.form?.addEventListener("input", () => {
      state.draft = collectDraftFromDom();
      saveState(state);
      renderEvaluation();
    });
    elements.form?.addEventListener("change", () => {
      state.draft = collectDraftFromDom();
      saveState(state);
      renderEvaluation();
    });

    elements.preferencesGrid?.addEventListener("input", () => {
      state.preferences = collectPreferencesFromDom();
      saveState(state);
      rerenderPreferenceDrivenViews();
    });
    elements.preferencesGrid?.addEventListener("change", () => {
      state.preferences = collectPreferencesFromDom();
      saveState(state);
      rerenderPreferenceDrivenViews();
    });

    elements.searchList?.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]");
      if (!action) return;
      const preset = searchPresetMap.get(action.dataset.key || "");
      if (!preset) return;
      if (action.dataset.action === "open-search") {
        window.open(preset.url, "_blank", "noopener,noreferrer");
        setStatus(`Odpalam: ${preset.label}.`);
      }
      if (action.dataset.action === "copy-query") {
        copyText(preset.query, `Skopiowałem frazę: ${preset.label}.`);
      }
    });

    elements.callScript?.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]");
      if (!action || action.dataset.action !== "copy-script-section") return;
      const section = scriptSectionMap.get(action.dataset.key || "");
      if (!section) return;
      copyText(buildCallScriptText([section]), `Skopiowałem sekcję: ${section.title}.`);
    });

    elements.leads?.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]");
      if (!action) return;
      const lead = state.leads.find((item) => item.id === action.dataset.id);
      if (!lead) return;
      if (action.dataset.action === "remove-lead") {
        state.leads = state.leads.filter((item) => item.id !== lead.id);
        saveState(state);
        renderLeads();
        setStatus("Lead usunięty.");
      }
      if (action.dataset.action === "copy-lead") {
        copyText(buildLeadCopyText(lead, lead, state.preferences), `Skopiowałem brief: ${lead.title || "lead"}.`);
      }
    });

    elements.saveLeadBtn?.addEventListener("click", saveCurrentLead);
    elements.resetDraftBtn?.addEventListener("click", () => {
      state.draft = cloneDraft();
      saveState(state);
      populateStaticFields();
      renderListingFields();
      renderEvaluation();
      setStatus("Formularz oferty wyczyszczony.");
    });
    elements.resetPreferencesBtn?.addEventListener("click", () => {
      state.preferences = clonePreferences();
      saveState(state);
      renderPreferences();
      rerenderPreferenceDrivenViews();
      setStatus("Kryteria przywrócone do sensownych defaultów.");
    });
    elements.copyScriptBtn?.addEventListener("click", () => {
      copyText(buildCallScriptText(scriptSections), "Skopiowałem cały skrypt rozmowy.");
    });
    elements.resetScriptBtn?.addEventListener("click", () => {
      elements.callScript?.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
        checkbox.checked = false;
      });
      setStatus("Checklisty telefonu zresetowane.");
    });
    elements.clearLeadsBtn?.addEventListener("click", () => {
      state.leads = [];
      saveState(state);
      renderLeads();
      setStatus("Shortlista wyczyszczona.");
    });
  }

  renderPreferences();
  renderPreferenceSummary();
  populateStaticFields();
  renderListingFields();
  renderSearchPresets();
  renderCallScript();
  renderEvaluation();
  renderLeads();
  wireEvents();
}
