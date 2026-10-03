import { ReadingGuideRuntime } from "./runtime.js";

const byId = (id) => document.getElementById(id);
const emptyMemory = () => ({
  concepts_explained: [], concepts_developed: [], arguments_explained: [], historical_context_used: [],
  important_connections: [], open_threads: [], resolved_threads: [], terms_introduced: [],
});
const makeId = () => globalThis.crypto?.randomUUID?.()?.replaceAll("-", "") || `${Date.now()}${Math.random().toString(16).slice(2)}`;

function option(value, label) {
  const node = document.createElement("option");
  node.value = value; node.textContent = label;
  return node;
}

function replaceOptions(select, rows, selected, map = (row) => [row.id, row.name]) {
  select.replaceChildren(...rows.map((row) => {
    const [value, label] = map(row); return option(value, label);
  }));
  if (selected != null) select.value = selected;
}

function jsonText(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function appendStructured(container, value) {
  if (typeof value === "string") {
    const paragraph = document.createElement("p"); paragraph.textContent = value; container.append(paragraph); return;
  }
  if (Array.isArray(value)) {
    const list = document.createElement("ul");
    for (const item of value) {
      const entry = document.createElement("li");
      entry.textContent = typeof item === "string" ? item : Object.entries(item || {}).map(([key, cell]) => `${key}: ${typeof cell === "string" ? cell : JSON.stringify(cell)}`).join(" · ");
      list.append(entry);
    }
    container.append(list); return;
  }
  const pre = document.createElement("pre"); pre.textContent = jsonText(value); container.append(pre);
}

function readableStructuredItem(value) {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (typeof value !== "object") return String(value);
  return Object.entries(value).map(([key, cell]) => `${key.replaceAll("_", " ")}: ${typeof cell === "string" ? cell : JSON.stringify(cell)}`).join(" · ");
}

export function appendArgumentAnalysis(container, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) { appendStructured(container, value); return; }
  const wrapper = document.createElement("div"); wrapper.className = "synchrobook-guide-argument";
  const sections = [
    ["premises", "Przesłanki", true],
    ["implicit_premises", "Przesłanki ukryte", true],
    ["steps", "Kroki rozumowania", true],
    ["conclusion", "Wniosek", false],
    ["assessment_note", "Ocena argumentu", false],
  ];
  for (const [key, label, list] of sections) {
    const content = value[key];
    if (content == null || content === "" || (Array.isArray(content) && !content.length)) continue;
    const section = document.createElement("section"); section.className = `synchrobook-guide-argument-section synchrobook-guide-argument-${key}`; section.dataset.argumentField = key;
    const heading = document.createElement("strong"); heading.textContent = label; section.append(heading);
    if (list) {
      const items = Array.isArray(content) ? content : [content]; const listNode = document.createElement("ol");
      for (const item of items) { const entry = document.createElement("li"); entry.textContent = readableStructuredItem(item); listNode.append(entry); }
      section.append(listNode);
    } else {
      const paragraph = document.createElement("p"); paragraph.textContent = readableStructuredItem(content); section.append(paragraph);
    }
    wrapper.append(section);
  }
  if (!wrapper.childElementCount) { appendStructured(container, value); return; }
  container.append(wrapper);
}

export function appendArgumentMap(container, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) { appendStructured(container, value); return; }
  const nodes = Array.isArray(value.nodes) ? value.nodes : [];
  const relations = Array.isArray(value.edges) ? value.edges : (Array.isArray(value.relations) ? value.relations : []);
  if (!nodes.length && !relations.length) { appendStructured(container, value); return; }

  const wrapper = document.createElement("div"); wrapper.className = "synchrobook-guide-map";
  const labels = new Map(nodes.map((node) => [node.id, node.label || node.title || ""]));
  if (nodes.length) {
    const nodeList = document.createElement("div"); nodeList.className = "synchrobook-guide-map-nodes";
    for (const node of nodes) {
      const item = document.createElement("article"); item.className = "synchrobook-guide-map-node"; item.dataset.mapNode = node.id || "";
      const header = document.createElement("header"); const id = document.createElement("code"); id.textContent = node.id || "•"; header.append(id);
      if (node.source_range || node.sourceRange) { const source = document.createElement("span"); source.textContent = node.source_range || node.sourceRange; header.append(source); }
      const label = document.createElement("p"); label.textContent = node.label || node.title || readableStructuredItem(node); item.append(header, label); nodeList.append(item);
    }
    wrapper.append(nodeList);
  }
  if (relations.length) {
    const section = document.createElement("section"); section.className = "synchrobook-guide-map-relations";
    const heading = document.createElement("strong"); heading.textContent = "Relacje między tezami";
    const list = document.createElement("ul");
    for (const relation of relations) {
      const item = document.createElement("li");
      const path = document.createElement("span"); path.className = "synchrobook-guide-map-path"; path.textContent = `${relation.from || "?"} → ${relation.to || "?"}`;
      path.title = [labels.get(relation.from), labels.get(relation.to)].filter(Boolean).join(" → ");
      const kind = document.createElement("span"); kind.textContent = String(relation.relation || relation.type || "relates to").replaceAll("_", " ");
      item.append(path, kind); list.append(item);
    }
    section.append(heading, list); wrapper.append(section);
  }
  container.append(wrapper);
}

export class ReadingGuideController {
  constructor({ api, getBook, getReader, seek }) {
    this.api = api; this.getBook = getBook; this.getReader = getReader; this.seek = seek;
    this.book = null; this.data = null; this.generated = null; this.sidebarView = "current";
    this.runtime = new ReadingGuideRuntime({ onChange: (chunk) => this.renderSidebar(chunk) });
    this.elements = {
      open: byId("synchrobook-guide-open"), panel: byId("synchrobook-guide-panel"), panelToggle: byId("synchrobook-guide-panel-toggle"),
      panelTitle: byId("synchrobook-guide-title"), panelBody: byId("synchrobook-guide-body"), previous: byId("synchrobook-guide-previous"),
      next: byId("synchrobook-guide-next"), follow: byId("synchrobook-guide-follow"), go: byId("synchrobook-guide-go"),
      dialog: byId("synchrobook-guide-dialog"), tabs: byId("synchrobook-guide-dialog-tabs"), loadStatus: byId("synchrobook-guide-load-status"),
      setSelect: byId("synchrobook-guide-set-select"), setName: byId("synchrobook-guide-set-name"), setProfile: byId("synchrobook-guide-set-profile"),
      profileSelect: byId("synchrobook-guide-profile-select"), profileName: byId("synchrobook-guide-profile-name"), profileDescription: byId("synchrobook-guide-profile-description"),
      profileLanguage: byId("synchrobook-guide-profile-language"), profileSpoilers: byId("synchrobook-guide-profile-spoilers"), profileInstructions: byId("synchrobook-guide-profile-instructions"),
      profileContext: byId("synchrobook-guide-profile-context"),
      profileChunkTypes: byId("synchrobook-guide-profile-chunk-types"), profileSectionTypes: byId("synchrobook-guide-profile-section-types"), profileBookTypes: byId("synchrobook-guide-profile-book-types"),
      typeSelect: byId("synchrobook-guide-type-select"), typeName: byId("synchrobook-guide-type-name"), typeId: byId("synchrobook-guide-type-id"),
      typeDescription: byId("synchrobook-guide-type-description"), typeInstructions: byId("synchrobook-guide-type-instructions"), typeContext: byId("synchrobook-guide-type-context"),
      typeScope: byId("synchrobook-guide-type-scope"), typeRenderer: byId("synchrobook-guide-type-renderer"), typeSchema: byId("synchrobook-guide-type-schema"), typeEnabled: byId("synchrobook-guide-type-enabled"),
      mode: byId("synchrobook-guide-generation-mode"), section: byId("synchrobook-guide-generation-section"), range: byId("synchrobook-guide-custom-range"),
      start: byId("synchrobook-guide-range-start"), end: byId("synchrobook-guide-range-end"), stats: byId("synchrobook-guide-generation-stats"),
      generationContext: byId("synchrobook-guide-generation-context"),
      prompt: byId("synchrobook-guide-prompt"), importText: byId("synchrobook-guide-import-json"), importFile: byId("synchrobook-guide-import-file"),
      validation: byId("synchrobook-guide-validation"), importCommit: byId("synchrobook-guide-import-commit"),
      memory: byId("synchrobook-guide-memory"), intelligence: byId("synchrobook-guide-intelligence"), glossary: byId("synchrobook-guide-glossary"),
      builtinTypes: byId("synchrobook-guide-builtin-types"), builtinCount: byId("synchrobook-guide-builtin-count"),
    };
    this.bind();
  }

  bind() {
    const e = this.elements;
    e.open.addEventListener("click", () => { if (this.book) { document.body.classList.remove("is-guide-hidden"); this.renderManager(); e.dialog.showModal(); } });
    e.panelToggle.addEventListener("click", () => document.body.classList.toggle("is-guide-hidden"));
    e.previous.addEventListener("click", () => this.runtime.move(-1));
    e.next.addEventListener("click", () => this.runtime.move(1));
    e.follow.addEventListener("click", () => this.runtime.follow());
    e.go.addEventListener("click", () => {
      const chunk = this.runtime.current(); const aligned = this.getReader()?.alignmentById.get(chunk?.start_source_id);
      if (aligned?.start != null) this.seek(Number(aligned.start));
    });
    document.querySelectorAll("[data-guide-sidebar-view]").forEach((button) => button.addEventListener("click", () => {
      this.sidebarView = button.dataset.guideSidebarView; this.renderSidebar(this.runtime.current());
    }));
    e.tabs.addEventListener("click", (event) => {
      const button = event.target.closest("[data-guide-manager-tab]"); if (!button) return;
      document.querySelectorAll("[data-guide-manager-tab]").forEach((node) => node.classList.toggle("is-active", node === button));
      document.querySelectorAll("[data-guide-manager-panel]").forEach((node) => { node.hidden = node.dataset.guideManagerPanel !== button.dataset.guideManagerTab; });
    });
    e.setSelect.addEventListener("change", () => this.action("activate_set", { id: e.setSelect.value }));
    byId("synchrobook-guide-set-create").addEventListener("click", () => this.action("save_set", { name: e.setName.value || "Reading Guide", profile_id: e.setProfile.value }));
    byId("synchrobook-guide-set-rename").addEventListener("click", () => {
      const current = this.activeSet(); if (current) this.action("save_set", { id: current.id, name: e.setName.value || current.name, profile_id: e.setProfile.value, metadata: current.metadata });
    });
    byId("synchrobook-guide-set-duplicate").addEventListener("click", () => { const current = this.activeSet(); if (current) this.action("duplicate_set", { id: current.id, name: e.setName.value || `${current.name} — Copy` }); });
    byId("synchrobook-guide-set-delete").addEventListener("click", () => { const current = this.activeSet(); if (current && confirm(`Delete commentary set “${current.name}”?`)) this.action("delete_set", { id: current.id }); });
    e.profileSelect.addEventListener("change", () => this.fillProfile(e.profileSelect.value));
    byId("synchrobook-guide-profile-new").addEventListener("click", () => this.fillProfile(null));
    byId("synchrobook-guide-profile-duplicate").addEventListener("click", () => { const profile = this.profileFromForm(); profile.id = makeId(); profile.name += " — Copy"; this.action("save_profile", profile); });
    byId("synchrobook-guide-profile-save").addEventListener("click", () => this.action("save_profile", this.profileFromForm()));
    byId("synchrobook-guide-profile-delete").addEventListener("click", () => { if (e.profileSelect.value && confirm("Delete this reading profile?")) this.action("delete_profile", { id: e.profileSelect.value }); });
    e.typeSelect.addEventListener("change", () => this.fillType(e.typeSelect.value));
    e.typeName.addEventListener("input", () => { if (!e.typeSelect.value) e.typeId.value = e.typeName.value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""); });
    byId("synchrobook-guide-type-new").addEventListener("click", () => this.fillType(null));
    byId("synchrobook-guide-type-save").addEventListener("click", () => this.saveType());
    byId("synchrobook-guide-type-delete").addEventListener("click", () => { const id = e.typeSelect.value; if (id && confirm("Delete this custom type? Existing imported blocks will be preserved.")) this.action("delete_type", { id }); });
    e.mode.addEventListener("change", () => { e.range.hidden = e.mode.value !== "custom_range"; this.updateGenerationEstimate(); });
    for (const select of [e.section, e.start, e.end]) select.addEventListener("change", () => this.updateGenerationEstimate());
    byId("synchrobook-guide-generate").addEventListener("click", () => this.generate());
    byId("synchrobook-guide-copy").addEventListener("click", async () => {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(e.prompt.value);
      else { e.prompt.focus(); e.prompt.select(); document.execCommand("copy"); }
      this.message("Prompt copied.");
    });
    byId("synchrobook-guide-save-prompt").addEventListener("click", () => this.downloadPrompt());
    e.importText.addEventListener("input", () => { e.importCommit.disabled = true; });
    e.importFile.addEventListener("change", async () => { if (e.importFile.files?.[0]) { e.importText.value = await e.importFile.files[0].text(); e.importCommit.disabled = true; } });
    byId("synchrobook-guide-import-validate").addEventListener("click", () => this.validateImport(false));
    e.importCommit.addEventListener("click", () => this.validateImport(true));
    byId("synchrobook-guide-memory-save").addEventListener("click", () => this.saveMemory());
    byId("synchrobook-guide-memory-rebuild").addEventListener("click", () => this.action("rebuild_memory", { commentary_set_id: this.data.activeSetId }));
    byId("synchrobook-guide-memory-reset").addEventListener("click", () => { if (confirm("Reset commentary memory for this set?")) this.action("reset_memory", { commentary_set_id: this.data.activeSetId }); });
  }

  activeSet() { return this.data?.sets.find((row) => row.id === this.data.activeSetId) || null; }

  async load(book) {
    this.book = book || null; this.generated = null;
    this.elements.open.disabled = true;
    this.elements.panel.hidden = !book;
    if (!book) { this.data = null; this.elements.loadStatus.hidden = true; document.body.classList.remove("has-reading-guide", "is-guide-hidden"); this.runtime.clear(); return; }
    this.elements.loadStatus.hidden = false; this.elements.loadStatus.textContent = "Loading Reading Guide data…";
    try { this.applyState(await this.api.getReadingGuide(book.id)); this.elements.open.disabled = false; }
    catch (error) {
      this.data = null; this.elements.open.disabled = false;
      const message = `Reading Guide data could not be loaded: ${error.message}. Restart the Python backend and reload the page.`;
      this.elements.loadStatus.hidden = false; this.elements.loadStatus.textContent = message;
      this.elements.panelBody.textContent = message;
    }
  }

  async action(action, data) {
    if (!this.book) return;
    try {
      const response = await this.api.readingGuideAction(this.book.id, action, data);
      const nextState = response.state || (Array.isArray(response.sets) ? response : null);
      if (nextState) { this.applyState(nextState); this.renderManager(); }
      if (response.preservedReferences) alert(`${response.preservedReferences} imported block(s) kept their deleted type ID.`);
      return response;
    } catch (error) { alert(error.message); return null; }
  }

  applyState(data) {
    this.data = data;
    this.elements.loadStatus.hidden = true;
    document.body.classList.add("has-reading-guide");
    this.runtime.load(this.book, data.chunks || []);
    this.runtime.sync(this.getReader()?.activeId || null);
    this.elements.panel.hidden = false;
    this.renderSidebar(this.runtime.current());
  }

  sync(anchorId) { if (this.book) this.runtime.sync(anchorId); }
  chapterChanged() { if (this.runtime.followReading) this.renderSidebar(this.runtime.current()); }

  guideForCurrentSection(chunk) {
    const sectionId = chunk?.section_id || this.getReader()?.chapterId;
    return this.data?.sectionGuides?.[sectionId] || {};
  }

  renderSidebar(chunk) {
    const e = this.elements; if (!e.panelBody) return;
    this.getReader()?.setCommentaryRange(chunk || null);
    document.querySelectorAll("[data-guide-sidebar-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.guideSidebarView === this.sidebarView));
    e.follow.classList.toggle("is-active", this.runtime.followReading); e.follow.setAttribute("aria-pressed", String(this.runtime.followReading));
    e.previous.disabled = !this.runtime.index.length; e.next.disabled = !this.runtime.index.length; e.go.disabled = !chunk;
    e.panelBody.replaceChildren();
    const guide = this.guideForCurrentSection(chunk);
    if (!this.data?.activeSetId) { e.panelTitle.textContent = "Reading Guide"; this.appendEmpty("Create a commentary set to begin."); return; }
    if (this.sidebarView === "before") { e.panelTitle.textContent = "Before Reading"; this.renderValue(guide.before_reading, "No introduction imported for this section."); return; }
    if (this.sidebarView === "after") {
      e.panelTitle.textContent = "After Reading"; this.renderValue(guide.section_summary, "No section summary imported.");
      if (guide.argument_map) { const card = document.createElement("section"); card.className = "synchrobook-guide-block"; const heading = document.createElement("h4"); heading.textContent = "Argument Map"; card.append(heading); appendArgumentMap(card, guide.argument_map); e.panelBody.append(card); }
      this.renderCustomSectionContent(guide); return;
    }
    if (this.sidebarView === "terms") { e.panelTitle.textContent = "Terms"; this.renderTerms(this.data.glossary || []); return; }
    if (!chunk) { e.panelTitle.textContent = "Current Commentary"; this.appendEmpty(this.data.chunks?.length ? "No imported commentary covers the current sentence." : "No commentary chunks exist yet. Generate a prompt and import LLM JSON."); return; }
    e.panelTitle.textContent = chunk.title || "Current Commentary";
    const typeMap = new Map((this.data.types || []).map((row) => [row.id, row]));
    for (const block of chunk.blocks || []) {
      const card = document.createElement("section"); card.className = "synchrobook-guide-block";
      const title = document.createElement("h4"); title.textContent = typeMap.get(block.type)?.name || block.type; card.append(title);
      const value = Object.hasOwn(block, "content") ? block.content : block.data;
      if (block.renderer === "argument") appendArgumentAnalysis(card, value); else appendStructured(card, value);
      e.panelBody.append(card);
    }
  }

  appendEmpty(message) { const p = document.createElement("p"); p.className = "synchrobook-empty"; p.textContent = message; this.elements.panelBody.append(p); }
  renderValue(value, fallback) { if (value == null || value === "" || (Array.isArray(value) && !value.length)) this.appendEmpty(fallback); else appendStructured(this.elements.panelBody, value); }
  renderTerms(rows) {
    if (!rows.length) { this.appendEmpty("No terminology has been imported."); return; }
    for (const row of rows) { const card = document.createElement("section"); card.className = "synchrobook-guide-block"; const title = document.createElement("h4"); title.textContent = row.term; const definition = document.createElement("p"); definition.textContent = row.definition || row.latestDevelopment || ""; card.append(title, definition); this.elements.panelBody.append(card); }
  }

  renderCustomSectionContent(guide) {
    const fixed = new Set(["before_reading", "section_summary", "section_terminology", "argument_map"]);
    const types = new Map((this.data?.types || []).map((row) => [row.id, row]));
    for (const [identifier, value] of Object.entries(guide || {})) {
      if (fixed.has(identifier) || value == null || value === "") continue;
      const card = document.createElement("section"); card.className = "synchrobook-guide-block";
      const heading = document.createElement("h4"); heading.textContent = types.get(identifier)?.name || identifier.replaceAll("_", " "); card.append(heading);
      appendStructured(card, value); this.elements.panelBody.append(card);
    }
  }

  renderManager() {
    if (!this.data || !this.book) return;
    const e = this.elements; const active = this.activeSet();
    replaceOptions(e.setSelect, this.data.sets || [], this.data.activeSetId);
    replaceOptions(e.setProfile, this.data.profiles || [], active?.profile_id);
    e.setName.value = active?.name || "";
    replaceOptions(e.profileSelect, this.data.profiles || [], active?.profile_id);
    this.fillProfile(e.profileSelect.value || this.data.profiles?.[0]?.id);
    const custom = (this.data.types || []).filter((row) => !row.builtin);
    e.typeSelect.replaceChildren(option("", "New custom type"), ...custom.map((row) => option(row.id, row.name)));
    this.fillType(e.typeSelect.value || null);
    const builtin = (this.data.types || []).filter((row) => row.builtin);
    e.builtinCount.textContent = `${builtin.length} available`;
    e.builtinTypes.replaceChildren();
    for (const type of builtin) {
      const details = document.createElement("details"); details.className = "synchrobook-guide-builtin-type";
      const summary = document.createElement("summary");
      const identity = document.createElement("span"); const name = document.createElement("strong"); const id = document.createElement("code");
      name.textContent = type.name; id.textContent = type.id; identity.append(name, id);
      const metadata = document.createElement("span"); metadata.textContent = `${type.default_scope} · ${type.default_renderer}`;
      summary.append(identity, metadata);
      const body = document.createElement("div");
      if (type.description) { const description = document.createElement("p"); description.textContent = type.description; body.append(description); }
      const heading = document.createElement("strong"); heading.textContent = "Generation instruction";
      const instruction = document.createElement("p"); instruction.textContent = type.generation_instruction;
      body.append(heading, instruction); details.append(summary, body); e.builtinTypes.append(details);
    }
    replaceOptions(e.section, this.book.chapters || [], this.getReader()?.chapterId, (row) => [row.id, row.title]);
    const units = this.sourceUnits();
    replaceOptions(e.start, units, units[0]?.id, (row) => [row.id, `${row.id} — ${row.text.slice(0, 70)}`]);
    replaceOptions(e.end, units, units.at(-1)?.id, (row) => [row.id, `${row.id} — ${row.text.slice(0, 70)}`]);
    this.updateGenerationEstimate();
    e.memory.value = jsonText(this.data.memory || emptyMemory());
    e.intelligence.value = jsonText(this.data.bookIntelligence || {});
    e.glossary.replaceChildren();
    for (const term of this.data.glossary || []) { const row = document.createElement("div"); row.className = "synchrobook-guide-glossary-row"; const strong = document.createElement("strong"); strong.textContent = term.term; const span = document.createElement("span"); span.textContent = term.definition || term.latestDevelopment || ""; row.append(strong, span); e.glossary.append(row); }
  }

  sourceUnits() {
    return (this.book?.chapters || []).flatMap((chapter) => (chapter.paragraphs || []).flatMap((paragraph) => (paragraph.sentences || []).map((sentence) => ({ id: sentence.id, text: sentence.originalText || sentence.text || "", chapterId: chapter.id }))));
  }

  updateGenerationEstimate() {
    if (!this.book) return;
    const e = this.elements; const all = this.sourceUnits(); let units = all;
    if (e.mode.value !== "book_analysis") {
      if (e.mode.value === "custom_range") {
        const order = new Map(all.map((row, index) => [row.id, index])); const start = order.get(e.start.value); const end = order.get(e.end.value);
        units = Number.isInteger(start) && Number.isInteger(end) && start <= end ? all.slice(start, end + 1) : [];
      } else units = all.filter((row) => row.chapterId === e.section.value);
    }
    const text = units.map((row) => row.text).join(" "); const characters = text.length; const words = text.trim() ? text.trim().split(/\s+/).length : 0; const tokens = Math.round(characters / 4);
    const size = tokens < 2000 ? "Small" : tokens < 6000 ? "Good" : tokens < 12000 ? "Large" : "Very large";
    const active = this.activeSet(); const profile = this.data?.profiles.find((row) => row.id === active?.profile_id);
    const source = units.length ? `${units[0].id} → ${units.at(-1).id}` : "invalid range";
    e.generationContext.textContent = `Book: ${this.book.title} · Commentary Set: ${active?.name || "none"} · Reading Profile: ${profile?.name || "none"} · Source range: ${source}`;
    e.stats.textContent = `${characters.toLocaleString()} chars · ${words.toLocaleString()} words · ≈${tokens.toLocaleString()} tokens · ${size}${tokens >= 6000 ? " — consider a smaller range; Synchrobook will not split it automatically." : ""}`;
  }

  fillProfile(identifier) {
    const e = this.elements; const profile = this.data?.profiles.find((row) => row.id === identifier) || { id: "", name: "", description: "", commentary_language: "Polish", spoiler_policy: "avoid_unnecessary", custom_global_instructions: "", enabled_chunk_types: [], enabled_section_types: [], enabled_book_types: [], type_order: [] };
    e.profileSelect.value = profile.id || ""; e.profileName.value = profile.name; e.profileDescription.value = profile.description || ""; e.profileLanguage.value = profile.commentary_language || "Polish"; e.profileSpoilers.value = profile.spoiler_policy || "avoid_unnecessary"; e.profileInstructions.value = profile.custom_global_instructions || ""; e.profileContext.value = profile.context || "";
    const custom = (this.data?.types || []).filter((row) => !row.builtin);
    this.renderChecks(e.profileChunkTypes, (this.data?.types || []).filter((row) => row.default_scope === "chunk"), profile.enabled_chunk_types, profile.type_order);
    this.renderChecks(e.profileSectionTypes, [...Object.keys(this.data?.sectionTypes || {}).map((id) => ({ id, name: id.replaceAll("_", " ") })), ...custom.filter((row) => row.default_scope === "section")], profile.enabled_section_types);
    this.renderChecks(e.profileBookTypes, [...Object.keys(this.data?.bookTypes || {}).map((id) => ({ id, name: id.replaceAll("_", " ") })), ...custom.filter((row) => row.default_scope === "book")], profile.enabled_book_types);
  }

  renderChecks(container, rows, enabled = [], order = []) {
    const ordered = [...rows].sort((a, b) => {
      const ai = order.indexOf(a.id), bi = order.indexOf(b.id); return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
    });
    container.replaceChildren();
    for (const row of ordered) { const label = document.createElement("label"); label.className = "checkline"; label.dataset.typeId = row.id; const input = document.createElement("input"); input.type = "checkbox"; input.checked = enabled.includes(row.id); const span = document.createElement("span"); span.textContent = row.name; const controls = document.createElement("span"); controls.className = "synchrobook-guide-order"; for (const [text, delta] of [["↑", -1], ["↓", 1]]) { const button = document.createElement("button"); button.type = "button"; button.textContent = text; button.addEventListener("click", () => { const sibling = delta < 0 ? label.previousElementSibling : label.nextElementSibling; if (sibling) container.insertBefore(delta < 0 ? label : sibling, delta < 0 ? sibling : label); }); controls.append(button); } label.append(input, span, controls); container.append(label); }
  }

  profileFromForm() {
    const e = this.elements; const selected = this.data?.profiles.find((row) => row.id === e.profileSelect.value);
    const checked = (container) => [...container.querySelectorAll("label")].filter((row) => row.querySelector("input").checked).map((row) => row.dataset.typeId);
    const chunkTypes = checked(e.profileChunkTypes);
    return { id: selected?.id || makeId(), name: e.profileName.value, description: e.profileDescription.value, commentary_language: e.profileLanguage.value, spoiler_policy: e.profileSpoilers.value, custom_global_instructions: e.profileInstructions.value, enabled_chunk_types: chunkTypes, enabled_section_types: checked(e.profileSectionTypes), enabled_book_types: checked(e.profileBookTypes), type_order: [...e.profileChunkTypes.querySelectorAll("label")].map((row) => row.dataset.typeId).filter((id) => chunkTypes.includes(id)), source_language: "unchanged", context: e.profileContext.value };
  }

  fillType(identifier) {
    const e = this.elements; const row = this.data?.types.find((item) => item.id === identifier && !item.builtin) || {};
    e.typeSelect.value = row.id || ""; e.typeName.value = row.name || ""; e.typeId.value = row.id || ""; e.typeId.disabled = Boolean(row.id); e.typeDescription.value = row.description || ""; e.typeInstructions.value = row.generation_instruction || ""; e.typeContext.value = row.custom_context || ""; e.typeScope.value = row.default_scope || "chunk"; e.typeRenderer.value = row.default_renderer || "prose"; e.typeSchema.value = row.output_schema ? jsonText(row.output_schema) : ""; e.typeEnabled.checked = row.enabled_by_default !== false;
  }

  async saveType() {
    const e = this.elements; let outputSchema = null;
    try { outputSchema = e.typeSchema.value.trim() ? JSON.parse(e.typeSchema.value) : null; } catch { alert("Optional output schema must be valid JSON."); return; }
    await this.action("save_type", { id: e.typeId.value, name: e.typeName.value, description: e.typeDescription.value, generation_instruction: e.typeInstructions.value, custom_context: e.typeContext.value, default_scope: e.typeScope.value, default_renderer: e.typeRenderer.value, output_schema: outputSchema, enabled_by_default: e.typeEnabled.checked });
  }

  async generate() {
    const e = this.elements; const active = this.activeSet(); if (!active) { alert("Create a commentary set first."); return; }
    const data = { mode: e.mode.value, commentary_set_id: active.id, reading_profile_id: active.profile_id, chapter_id: e.section.value || this.getReader()?.chapterId };
    if (e.mode.value === "custom_range") Object.assign(data, { start_source_id: e.start.value, end_source_id: e.end.value });
    const result = await this.action("build_prompt", data); if (!result?.prompt) return;
    this.generated = result; e.prompt.value = result.prompt;
    const t = result.target; e.stats.textContent = `${t.characters.toLocaleString()} chars · ${t.words.toLocaleString()} words · ≈${t.estimatedTokens.toLocaleString()} tokens · ${t.size}${t.warning ? " — consider a smaller range" : ""}. Previous: ${result.context.previous.endingExcerpt ? "included" : "not available"}; next: ${result.context.next.openingExcerpt ? "included" : "not available"}; Book Intelligence: ${result.context.bookIntelligenceIncluded ? "included" : "not available"}; Memory: included.`;
  }

  async validateImport(commit) {
    const e = this.elements; const active = this.activeSet(); if (!active) return;
    const result = await this.api.readingGuideAction(this.book.id, commit ? "import_json" : "validate_import", { json: e.importText.value, destination_set_id: active.id }).catch((error) => ({ valid: false, errors: [error.message], warnings: [] }));
    e.validation.replaceChildren();
    const status = document.createElement("strong"); status.textContent = result.valid ? "VALID" : "ERRORS"; status.dataset.valid = String(result.valid); e.validation.append(status);
    for (const message of result.errors || []) { const row = document.createElement("p"); row.textContent = message; row.className = "is-error"; e.validation.append(row); }
    if (result.warnings?.length) { const heading = document.createElement("strong"); heading.textContent = "WARNINGS"; e.validation.append(heading); }
    for (const message of result.warnings || []) { const row = document.createElement("p"); row.textContent = message; row.className = "is-warning"; e.validation.append(row); }
    e.importCommit.disabled = !result.valid;
    if (result.imported && result.state) { this.applyState(result.state); this.renderManager(); this.message("Commentary imported."); }
  }

  async saveMemory() { try { await this.action("save_memory", { commentary_set_id: this.data.activeSetId, memory: JSON.parse(this.elements.memory.value) }); } catch { alert("Memory must be valid JSON."); } }
  message(text) { this.elements.stats.textContent = text; }
  downloadPrompt() { if (!this.elements.prompt.value) return; const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([this.elements.prompt.value], { type: "text/plain;charset=utf-8" })); link.download = `synchrobook-${this.generated?.operation || "prompt"}.txt`; link.click(); URL.revokeObjectURL(link.href); }
}
