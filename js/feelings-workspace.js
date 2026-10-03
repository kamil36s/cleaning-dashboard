import { feelingsApi } from "./feelings-api.js";
import {
  emotionMeterItems,
  QUADRANT_META,
  escapeHtml,
  filterCheckins,
  groupCheckins,
  localDateTime,
  quickRange,
  searchEmotions,
} from "./feelings-model.js";
import {
  associationDetail,
  distributionRows,
  frequencyBars,
  heatmap,
  quadrantBars,
  trendSvg,
} from "./feelings-insights.js";

const FAMILY_ORDER = ["high_unpleasant", "high_pleasant", "low_unpleasant", "low_pleasant"];
const TIME_BUCKETS = ["morning", "afternoon", "evening", "night"];

function icon(name) {
  const paths = {
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    back: '<path d="M19 12H5m6-6-6 6 6 6"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/>',
    next: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name]}</svg>`;
}

function formatWhen(value, options = {}) {
  if (!value) return "—";
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: options.dateOnly ? "medium" : "medium",
    ...(options.dateOnly ? {} : { timeStyle: "short" }),
  }).format(date);
}

function colorGlyph(emotion, extra = "") {
  return `<i class="feelings-glyph shape-${escapeHtml(emotion?.shape || "circle")} ${extra}" style="--emotion-color:${escapeHtml(emotion?.color || "#777")}"></i>`;
}

function shellTemplate() {
  return `
    <section class="feelings-workspace" role="dialog" aria-modal="true" aria-labelledby="feelings-workspace-title">
      <header class="feelings-workspace-head">
        <div><span class="feelings-eyebrow">Private · local to this dashboard</span><h2 id="feelings-workspace-title">How I Feel</h2></div>
        <button class="feelings-round-button" type="button" data-feelings-action="close" aria-label="Close How I Feel">${icon("close")}</button>
      </header>
      <div class="feelings-workspace-layout">
        <nav class="feelings-workspace-nav" aria-label="How I Feel sections">
          <button type="button" data-feelings-view="checkin">Check in</button>
          <button type="button" data-feelings-view="history">History</button>
          <button type="button" data-feelings-view="insights">Insights</button>
          <button type="button" data-feelings-view="data">Data</button>
        </nav>
        <main class="feelings-workspace-main" data-feelings-main></main>
      </div>
      <div class="feelings-toast" data-feelings-toast role="status" aria-live="polite" hidden></div>
    </section>`;
}

export function createFeelingsWorkspace({ onChanged = () => {} } = {}) {
  const overlay = document.createElement("div");
  overlay.className = "feelings-workspace-overlay";
  overlay.hidden = true;
  overlay.innerHTML = shellTemplate();
  document.body.appendChild(overlay);
  const main = overlay.querySelector("[data-feelings-main]");
  const state = {
    ready: false,
    loading: false,
    view: "checkin",
    flowStep: "quadrant",
    quadrant: null,
    meterFocus: null,
    meterZoom: 1.85,
    meterDragX: 0,
    meterDragY: 0,
    emotion: null,
    selectedTags: new Set(),
    note: "",
    occurredAt: localDateTime(),
    emotions: [],
    tags: [],
    checkins: [],
    insights: null,
    searchOpen: false,
    searchQuery: "",
    searchQuadrants: new Set(),
    searchIndex: 0,
    customEmotionOpen: false,
    historyFilters: {},
    detailId: null,
    detailEditing: false,
    insightRange: 0,
    associationType: "tag",
    associationName: "",
  };
  let meterGesture = null;
  let suppressMeterClick = false;

  function toast(message, isError = false) {
    const element = overlay.querySelector("[data-feelings-toast]");
    element.textContent = message;
    element.dataset.error = isError ? "true" : "false";
    element.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => { element.hidden = true; }, 4200);
  }

  async function load({ refresh = false } = {}) {
    if (state.loading || (state.ready && !refresh)) return;
    state.loading = true;
    render();
    try {
      const [emotionResult, tagResult, checkinResult, insightResult] = await Promise.all([
        feelingsApi.listEmotions(), feelingsApi.listTags(), feelingsApi.listCheckins({ limit: 5000 }),
        feelingsApi.insights(state.insightRange || undefined),
      ]);
      state.emotions = emotionResult.emotions || [];
      state.tags = tagResult.tags || [];
      state.checkins = checkinResult.checkins || [];
      state.insights = insightResult;
      state.ready = true;
    } catch (error) {
      toast(error.message || "Could not load How I Feel", true);
    } finally {
      state.loading = false;
      render();
    }
  }

  function resetFlow() {
    state.flowStep = "quadrant";
    state.quadrant = null;
    state.meterFocus = null;
    state.meterZoom = 1.85;
    state.meterDragX = 0;
    state.meterDragY = 0;
    state.emotion = null;
    state.selectedTags = new Set();
    state.note = "";
    state.occurredAt = localDateTime();
    state.searchOpen = false;
    state.searchQuery = "";
    state.searchQuadrants = new Set();
    state.customEmotionOpen = false;
  }

  function setView(view) {
    state.view = view;
    state.detailId = null;
    state.detailEditing = false;
    if (view === "checkin" && !state.emotion) resetFlow();
    render();
  }

  function renderNav() {
    overlay.querySelectorAll("[data-feelings-view]").forEach((button) => {
      button.dataset.active = button.dataset.feelingsView === state.view ? "true" : "false";
      button.setAttribute("aria-current", button.dataset.active === "true" ? "page" : "false");
    });
  }

  function render() {
    renderNav();
    if (state.loading && !state.ready) {
      main.innerHTML = '<div class="feelings-loading"><i></i><p>Preparing your private feelings history…</p></div>';
      return;
    }
    if (!state.ready) {
      main.innerHTML = '<div class="feelings-error-state"><h3>How I Feel could not start</h3><p>The local database or seed import was unavailable.</p><button type="button" data-feelings-action="retry">Try again</button></div>';
      return;
    }
    if (state.view === "history") main.innerHTML = historyView();
    else if (state.view === "insights") main.innerHTML = insightsView();
    else if (state.view === "data") main.innerHTML = dataView();
    else main.innerHTML = checkinView();
  }

  function checkinProgress() {
    const labels = ["Color", "Emotion", "Context", "Reflect", "Review"];
    const steps = ["quadrant", "meter", "tags", "note", "review"];
    const current = Math.max(0, steps.indexOf(state.flowStep));
    return `<ol class="feelings-flow-progress">${labels.map((label, index) => `<li data-current="${index === current}" data-done="${index < current}"><i></i><span>${label}</span></li>`).join("")}</ol>`;
  }

  function checkinView() {
    let content;
    if (state.flowStep === "meter") content = moodMeter();
    else if (state.flowStep === "tags") content = tagSelector();
    else if (state.flowStep === "note") content = reflectionEditor();
    else if (state.flowStep === "review") content = reviewStep();
    else if (state.flowStep === "success") content = successStep();
    else content = quadrantPicker();
    return `<div class="feelings-checkin-stage">${state.flowStep === "success" ? "" : checkinProgress()}${content}</div>${state.searchOpen ? emotionSearch() : ""}`;
  }

  function quadrantPicker() {
    return `
      <section class="feelings-quadrant-step">
        <div class="feelings-step-copy"><span>Start with the closest color</span><h3>How are you feeling right now?</h3><p>Choose by energy and pleasantness. You can search every emotion next.</p></div>
        <div class="feelings-quadrant-field">${FAMILY_ORDER.map((key) => {
          const [energy, pleasantness] = QUADRANT_META[key].label.split(" · ");
          return `<button class="feelings-quadrant is-${key}" type="button" data-quadrant="${key}"><span>${energy}<br><b>${pleasantness}</b></span></button>`;
        }).join("")}</div>
        <button class="feelings-text-action" type="button" data-feelings-action="open-search">${icon("search")} Search the emotion dictionary</button>
      </section>`;
  }

  function moodMeter() {
    const emotions = emotionMeterItems(state.emotions);
    const focusDirections = {
      high_unpleasant: [1, 1],
      high_pleasant: [-1, 1],
      low_unpleasant: [1, -1],
      low_pleasant: [-1, -1],
    };
    const zoom = Math.max(1, Math.min(2.5, state.meterZoom));
    const [directionX, directionY] = focusDirections[state.meterFocus] || [0, 0];
    const pan = state.meterFocus && zoom > 1 ? 25 * zoom : 0;
    const inverseZoom = (1 / zoom).toFixed(4);
    const contextLabel = state.meterFocus ? QUADRANT_META[state.meterFocus]?.label : "All energy · pleasantness quadrants";
    return `
      <section class="feelings-meter-step">
        <header class="feelings-step-toolbar">
          <button class="feelings-round-button" type="button" data-feelings-action="flow-back" aria-label="Back">${icon("back")}</button>
          <div><span>${escapeHtml(contextLabel)}</span><h3>Which emotion fits best?</h3></div>
          <button class="feelings-round-button" type="button" data-feelings-action="open-search" aria-label="Search emotions">${icon("search")}</button>
        </header>
        <div class="feelings-meter-viewport" data-meter-viewport aria-label="Emotion meter with four energy and pleasantness quadrants">
          <button class="feelings-meter-pan is-left" type="button" data-meter-pan-x="180" data-meter-pan-y="0" aria-label="Pan emotion map left">‹</button>
          <button class="feelings-meter-pan is-right" type="button" data-meter-pan-x="-180" data-meter-pan-y="0" aria-label="Pan emotion map right">›</button>
          <button class="feelings-meter-pan is-up" type="button" data-meter-pan-x="0" data-meter-pan-y="150" aria-label="Pan emotion map up">⌃</button>
          <button class="feelings-meter-pan is-down" type="button" data-meter-pan-x="0" data-meter-pan-y="-150" aria-label="Pan emotion map down">⌄</button>
          <div class="feelings-meter-field" data-focus="${escapeHtml(state.meterFocus || "all")}" style="--meter-zoom:${zoom};--meter-inverse-zoom:${inverseZoom};--meter-pan-x:${directionX * pan}%;--meter-pan-y:${directionY * pan}%;--meter-drag-x:${state.meterDragX}px;--meter-drag-y:${state.meterDragY}px">
            <i class="feelings-meter-center" aria-hidden="true"></i>
            ${emotions.map((emotion) => `
            <button class="feelings-emotion-node shape-${escapeHtml(emotion.shape)} is-${escapeHtml(emotion.quadrant)}" style="--emotion-color:${escapeHtml(emotion.color)};--label-length:${emotion.name.length};grid-column:${Number(emotion.x) + 1};grid-row:${Number(emotion.y) + 1}" type="button" data-emotion-id="${escapeHtml(emotion.id)}" data-definition="${escapeHtml(emotion.description)}" data-selected="${state.emotion?.id === emotion.id}" aria-label="${escapeHtml(emotion.name)}: ${escapeHtml(emotion.description)}"><span>${escapeHtml(emotion.name)}</span></button>`).join("")}</div>
        </div>
        <div class="feelings-meter-zoom" aria-label="Emotion map zoom controls">
          <button type="button" data-feelings-action="meter-zoom-out" aria-label="Zoom out">−</button>
          <span>${Math.round(zoom * 100)}%</span>
          <button type="button" data-feelings-action="meter-zoom-in" aria-label="Zoom in">+</button>
          <button type="button" data-feelings-action="meter-fit">Show all four</button>
        </div>
        ${state.emotion ? emotionInfoPanel(state.emotion) : '<p class="feelings-meter-hint">Choose one emotion.</p>'}
      </section>`;
  }

  function emotionInfoPanel(emotion) {
    return `<aside class="feelings-emotion-info" style="--emotion-color:${escapeHtml(emotion.color)}">
      <div>${colorGlyph(emotion)}<span><b>${escapeHtml(emotion.name)}</b><small>${escapeHtml(emotion.description)}</small></span></div>
      <button class="feelings-next-button" type="button" data-feelings-action="emotion-continue" aria-label="Continue with ${escapeHtml(emotion.name)}">${icon("next")}</button>
    </aside>`;
  }

  function meterFocusDirection() {
    return {
      high_unpleasant: [1, 1], high_pleasant: [-1, 1],
      low_unpleasant: [1, -1], low_pleasant: [-1, -1],
    }[state.meterFocus] || [0, 0];
  }

  function meterBasePan(field, zoom = state.meterZoom) {
    const [directionX, directionY] = meterFocusDirection();
    const amount = state.meterFocus && zoom > 1 ? field.offsetWidth * .25 * zoom : 0;
    return { x: directionX * amount, y: directionY * amount };
  }

  function applyMeterView() {
    const field = overlay.querySelector(".feelings-meter-field");
    if (!field) return;
    const [directionX, directionY] = meterFocusDirection();
    const pan = state.meterFocus && state.meterZoom > 1 ? 25 * state.meterZoom : 0;
    field.dataset.focus = state.meterFocus || "all";
    field.style.setProperty("--meter-zoom", state.meterZoom);
    field.style.setProperty("--meter-inverse-zoom", (1 / state.meterZoom).toFixed(4));
    field.style.setProperty("--meter-pan-x", `${directionX * pan}%`);
    field.style.setProperty("--meter-pan-y", `${directionY * pan}%`);
    field.style.setProperty("--meter-drag-x", `${state.meterDragX}px`);
    field.style.setProperty("--meter-drag-y", `${state.meterDragY}px`);
    const label = overlay.querySelector(".feelings-meter-zoom span");
    if (label) label.textContent = `${Math.round(state.meterZoom * 100)}%`;
  }

  function setMeterZoom(nextZoom, anchor = null) {
    const field = overlay.querySelector(".feelings-meter-field");
    const viewport = overlay.querySelector("[data-meter-viewport]");
    if (!field || !viewport) return;
    const oldZoom = state.meterZoom;
    const newZoom = Math.max(1, Math.min(2.5, nextZoom));
    if (newZoom === oldZoom) return;
    if (anchor) {
      const viewportRect = viewport.getBoundingClientRect();
      const cursor = { x: anchor.x - (viewportRect.left + viewportRect.width / 2), y: anchor.y - (viewportRect.top + viewportRect.height / 2) };
      const oldBase = meterBasePan(field, oldZoom);
      const mapPoint = {
        x: (cursor.x - oldBase.x - state.meterDragX) / oldZoom,
        y: (cursor.y - oldBase.y - state.meterDragY) / oldZoom,
      };
      const newBase = meterBasePan(field, newZoom);
      state.meterDragX = cursor.x - newZoom * mapPoint.x - newBase.x;
      state.meterDragY = cursor.y - newZoom * mapPoint.y - newBase.y;
    }
    state.meterZoom = newZoom;
    applyMeterView();
  }

  function panMeter(deltaX, deltaY) {
    state.meterDragX += deltaX;
    state.meterDragY += deltaY;
    applyMeterView();
  }

  function emotionSearch() {
    const matches = searchEmotions(state.emotions, state.searchQuery, [...state.searchQuadrants]);
    const exact = state.emotions.some((emotion) => emotion.name.toLocaleLowerCase() === state.searchQuery.trim().toLocaleLowerCase());
    state.searchIndex = Math.min(state.searchIndex, Math.max(0, matches.length - 1));
    return `<div class="feelings-search-layer" role="dialog" aria-modal="true" aria-label="Emotion dictionary">
      <section class="feelings-search-panel">
        <header><button class="feelings-round-button" type="button" data-feelings-action="close-search" aria-label="Close search">${icon("back")}</button><label>${icon("search")}<input type="search" data-emotion-search autocomplete="off" placeholder="Search feelings" value="${escapeHtml(state.searchQuery)}"></label></header>
        <div class="feelings-color-filters">${FAMILY_ORDER.map((key) => `<button type="button" data-search-quadrant="${key}" data-active="${state.searchQuadrants.has(key)}">${QUADRANT_META[key].short}</button>`).join("")}</div>
        <div class="feelings-dictionary" role="listbox">${matches.map((emotion, index) => `<button type="button" role="option" aria-selected="${index === state.searchIndex}" data-search-emotion="${escapeHtml(emotion.id)}" data-highlighted="${index === state.searchIndex}">${colorGlyph(emotion)}<b>${escapeHtml(emotion.name)}</b><span>${escapeHtml(emotion.description)}</span></button>`).join("") || '<p class="feelings-empty">No matching emotions.</p>'}</div>
        ${state.searchQuery.trim() && !exact ? `<div class="feelings-custom-emotion">${state.customEmotionOpen ? customEmotionForm() : `<button type="button" data-feelings-action="custom-emotion-open">+ Add “${escapeHtml(state.searchQuery.trim())}” as a custom emotion</button>`}</div>` : ""}
      </section>
    </div>`;
  }

  function customEmotionForm() {
    return `<form data-custom-emotion-form><h4>Add custom emotion</h4><label>Name<input name="name" required value="${escapeHtml(state.searchQuery.trim())}"></label><label>Color family<select name="quadrant" required>${FAMILY_ORDER.map((key) => `<option value="${key}">${escapeHtml(QUADRANT_META[key].label)}</option>`).join("")}</select></label><label>Definition <span>optional</span><textarea name="description" rows="2"></textarea></label><button type="submit">Add and select</button></form>`;
  }

  function tagSelector() {
    const groups = new Map();
    state.tags.forEach((tag) => {
      const key = tag.category || "other";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(tag);
    });
    return `<section class="feelings-context-step">
      <header class="feelings-step-toolbar"><button class="feelings-round-button" type="button" data-feelings-action="flow-back" aria-label="Back">${icon("back")}</button><div><span>${escapeHtml(state.emotion?.name)}</span><h3>What’s part of this moment?</h3></div><i></i></header>
      <label class="feelings-tag-search">${icon("search")}<input type="search" data-tag-search placeholder="Search tags"></label>
      <div class="feelings-tag-groups">${[...groups].map(([category, tags]) => `<section><h4>${escapeHtml(category)}</h4><div>${tags.map((tag) => `<button type="button" data-tag-id="${escapeHtml(tag.id)}" data-selected="${state.selectedTags.has(tag.id)}">${escapeHtml(tag.name)}<small>${tag.usageCount || 0}</small></button>`).join("")}</div></section>`).join("")}</div>
      <form class="feelings-add-tag" data-custom-tag-form><input name="name" placeholder="Create a new tag" aria-label="New tag name" required><button type="submit">Add tag</button></form>
      <footer><button type="button" data-feelings-action="flow-back">Back</button><button class="is-primary" type="button" data-feelings-action="tags-continue">Continue${state.selectedTags.size ? ` · ${state.selectedTags.size} selected` : ""}</button></footer>
    </section>`;
  }

  function reflectionEditor() {
    return `<section class="feelings-reflection-step">
      <header class="feelings-step-toolbar"><button class="feelings-round-button" type="button" data-feelings-action="flow-back" aria-label="Back">${icon("back")}</button><div><span>Optional reflection</span><h3>What’s going on?</h3></div><i></i></header>
      <textarea data-reflection-input rows="12" placeholder="Write exactly what you want to remember…">${escapeHtml(state.note)}</textarea>
      <p>Your words stay as entered. No analysis or rewriting is applied.</p>
      <footer><button type="button" data-feelings-action="flow-back">Back</button><button class="is-primary" type="button" data-feelings-action="note-continue">Review check-in</button></footer>
    </section>`;
  }

  function reviewStep() {
    const selected = state.tags.filter((tag) => state.selectedTags.has(tag.id));
    return `<section class="feelings-review-step">
      <header class="feelings-step-toolbar"><button class="feelings-round-button" type="button" data-feelings-action="flow-back" aria-label="Back">${icon("back")}</button><div><span>Review</span><h3>Save this check-in?</h3></div><i></i></header>
      <div class="feelings-review-emotion" style="--emotion-color:${escapeHtml(state.emotion?.color)}">${colorGlyph(state.emotion)}<div><span>${escapeHtml(QUADRANT_META[state.emotion?.quadrant]?.label)}</span><b>${escapeHtml(state.emotion?.name)}</b><p>${escapeHtml(state.emotion?.description)}</p></div></div>
      <label class="feelings-time-field"><span>Timestamp · Europe/Warsaw</span><input type="datetime-local" data-review-time value="${escapeHtml(state.occurredAt)}"></label>
      <div class="feelings-review-tags"><span>Context</span><div>${selected.length ? selected.map((tag) => `<i>${escapeHtml(tag.name)}</i>`).join("") : "No tags selected"}</div></div>
      <div class="feelings-review-note"><span>Reflection</span><p>${state.note ? escapeHtml(state.note).replaceAll("\n", "<br>") : "No reflection added"}</p></div>
      <footer><button type="button" data-feelings-action="flow-back">Back</button><button class="is-primary" type="button" data-feelings-action="save-checkin">Confirm and save</button></footer>
    </section>`;
  }

  function successStep() {
    return `<section class="feelings-success"><i style="--emotion-color:${escapeHtml(state.emotion?.color)}">${colorGlyph(state.emotion)}</i><span>Check-in saved</span><h3>${escapeHtml(state.emotion?.name)}</h3><p>Your widget, history, and insights are up to date.</p><div><button type="button" data-feelings-action="close">Done</button><button type="button" data-feelings-action="new-checkin">Check in again</button></div></section>`;
  }

  function historyView() {
    const filtered = filterCheckins(state.checkins, state.historyFilters);
    const groups = groupCheckins(filtered);
    const detail = state.detailId ? state.checkins.find((item) => item.id === state.detailId) : null;
    return `<section class="feelings-history-view">
      <header class="feelings-view-heading"><div><span>Your private timeline</span><h3>History</h3><p>${filtered.length} of ${state.checkins.length} check-ins</p></div></header>
      <form class="feelings-history-filters" data-history-filters>
        <label>Search<input name="q" type="search" value="${escapeHtml(state.historyFilters.q || "")}" placeholder="Emotion, tag, or note"></label>
        <label>Emotion<select name="emotion"><option value="">All emotions</option>${state.emotions.map((emotion) => `<option ${state.historyFilters.emotion === emotion.name ? "selected" : ""}>${escapeHtml(emotion.name)}</option>`).join("")}</select></label>
        <label>Color<select name="quadrant"><option value="">All colors</option>${FAMILY_ORDER.map((key) => `<option value="${key}" ${state.historyFilters.quadrant === key ? "selected" : ""}>${escapeHtml(QUADRANT_META[key].label)}</option>`).join("")}</select></label>
        <label>Tag<select name="tag"><option value="">All tags</option>${state.tags.map((tag) => `<option ${state.historyFilters.tag === tag.name ? "selected" : ""}>${escapeHtml(tag.name)}</option>`).join("")}</select></label>
        <label>From<input name="from" type="date" value="${escapeHtml(state.historyFilters.from || "")}"></label><label>To<input name="to" type="date" value="${escapeHtml(state.historyFilters.to || "")}"></label>
      </form>
      <div class="feelings-quick-ranges">${[[7, "7 days"], [30, "30 days"], [90, "90 days"], [365, "1 year"], [0, "All time"]].map(([days, label]) => `<button type="button" data-history-range="${days}">${label}</button>`).join("")}</div>
      <div class="feelings-history-list">${groups.map((group) => `<section><h4>${escapeHtml(group.label)}</h4>${group.items.map(historyRow).join("")}</section>`).join("") || '<p class="feelings-empty">No check-ins match these filters.</p>'}</div>
      ${detail ? checkinDetail(detail) : ""}
    </section>`;
  }

  function historyRow(item) {
    return `<button type="button" class="feelings-history-row" data-checkin-id="${escapeHtml(item.id)}">${colorGlyph(item.emotion)}<time>${formatWhen(item.occurredAt)}</time><div><b>${escapeHtml(item.emotion?.name)}</b><span>${item.tags.map((tag) => escapeHtml(tag.name)).join(" · ") || "No tags"}</span>${item.note ? `<p>${escapeHtml(item.note.slice(0, 150))}${item.note.length > 150 ? "…" : ""}</p>` : ""}</div>${icon("next")}</button>`;
  }

  function checkinDetail(item) {
    if (state.detailEditing) {
      return `<div class="feelings-detail-layer"><form class="feelings-detail" data-detail-edit-form><header><div><span>Edit check-in</span><h3>${escapeHtml(item.emotion?.name)}</h3></div><button type="button" data-feelings-action="detail-close">${icon("close")}</button></header><label>Emotion<select name="emotionId">${state.emotions.map((emotion) => `<option value="${escapeHtml(emotion.id)}" ${emotion.id === item.emotion?.id ? "selected" : ""}>${escapeHtml(emotion.name)} · ${escapeHtml(QUADRANT_META[emotion.quadrant]?.short)}</option>`).join("")}</select></label><label>Timestamp<input name="occurredAt" type="datetime-local" value="${escapeHtml(item.occurredAt.slice(0, 16))}"></label><fieldset><legend>Tags</legend><div class="feelings-detail-tags">${state.tags.map((tag) => `<label><input type="checkbox" name="tags" value="${escapeHtml(tag.name)}" ${item.tags.some((current) => current.id === tag.id) ? "checked" : ""}><span>${escapeHtml(tag.name)}</span></label>`).join("")}</div></fieldset><label>Reflection<textarea name="note" rows="8">${escapeHtml(item.note)}</textarea></label><footer><button type="button" data-feelings-action="detail-cancel-edit">Cancel</button><button class="is-primary" type="submit">Save changes</button></footer></form></div>`;
    }
    return `<div class="feelings-detail-layer"><article class="feelings-detail"><header><div><span>${escapeHtml(QUADRANT_META[item.emotion?.quadrant]?.label)}</span><h3>${escapeHtml(item.emotion?.name)}</h3></div><button type="button" data-feelings-action="detail-close">${icon("close")}</button></header><div class="feelings-detail-hero">${colorGlyph(item.emotion)}<time>${formatWhen(item.occurredAt)}<small>${escapeHtml(item.timezone)}</small></time></div><section><h4>Context</h4><div class="feelings-detail-pills">${item.tags.map((tag) => `<i>${escapeHtml(tag.name)}</i>`).join("") || "No tags"}</div></section><section><h4>Reflection</h4><p class="feelings-detail-note">${item.note ? escapeHtml(item.note).replaceAll("\n", "<br>") : "No reflection"}</p></section><small>Source: ${escapeHtml(item.source)}</small><footer><button class="is-danger" type="button" data-feelings-action="detail-delete">Delete</button><button class="is-primary" type="button" data-feelings-action="detail-edit">Edit</button></footer></article></div>`;
  }

  function insightsView() {
    const data = state.insights || {};
    const associationList = state.associationType === "tag" ? data.tagAssociations || [] : data.emotionAssociations || [];
    const selected = associationList.find((item) => (state.associationType === "tag" ? item.tag : item.emotion) === state.associationName) || associationList[0];
    return `<section class="feelings-insights-view">
      <header class="feelings-view-heading"><div><span>Descriptive, not diagnostic</span><h3>Insights</h3><p>${data.total || 0} check-ins in this range</p></div><label>Range<select data-insight-range><option value="0" ${!state.insightRange ? "selected" : ""}>All time</option><option value="30" ${state.insightRange === 30 ? "selected" : ""}>30 days</option><option value="90" ${state.insightRange === 90 ? "selected" : ""}>90 days</option><option value="365" ${state.insightRange === 365 ? "selected" : ""}>1 year</option></select></label></header>
      <div class="feelings-insights-grid">
        <article><span>Color distribution</span><h4>Energy × pleasantness</h4>${quadrantBars(data.quadrants || [])}</article>
        <article><span>Emotion frequency</span><h4>Most common</h4>${frequencyBars(data.emotions || [])}</article>
        <article><span>Time of day</span><h4>When you check in</h4>${distributionRows(data.timeOfDay || {}, TIME_BUCKETS)}</article>
        <article><span>Day of week</span><h4>Weekly rhythm</h4>${distributionRows(data.dayOfWeek || {}, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])}</article>
        <article class="is-wide"><span>Recent trend</span><h4>Daily average</h4>${trendSvg(data.trend || [])}</article>
        <article class="is-wide"><span>Check-in frequency</span><h4>Last 12 weeks</h4>${heatmap(data.heatmap || [])}<div class="feelings-frequency-summary"><span><b>${data.frequency?.byDay?.slice(-7).reduce((sum, item) => sum + item.count, 0) || 0}</b> last 7 active days</span><span><b>${data.frequency?.byWeek?.at(-1)?.count || 0}</b> latest active week</span><span><b>${data.frequency?.byMonth?.at(-1)?.count || 0}</b> latest active month</span></div></article>
        <article class="is-wide feelings-association-card"><div class="feelings-association-head"><div><span>Local associations</span><h4>Explore factual co-occurrence</h4></div><div><button type="button" data-association-type="tag" data-active="${state.associationType === "tag"}">By tag</button><button type="button" data-association-type="emotion" data-active="${state.associationType === "emotion"}">By emotion</button><select data-association-name>${associationList.map((item) => { const name = state.associationType === "tag" ? item.tag : item.emotion; return `<option ${name === (selected?.tag || selected?.emotion) ? "selected" : ""}>${escapeHtml(name)}</option>`; }).join("")}</select></div></div><div class="feelings-association-detail">${associationDetail(selected, state.associationType)}</div></article>
      </div>
      <p class="feelings-insights-note">These summaries describe entries in your local history. They do not establish causes or provide a diagnosis.</p>
    </section>`;
  }

  function dataView() {
    return `<section class="feelings-data-view"><header class="feelings-view-heading"><div><span>Portable and local</span><h3>Your data</h3><p>Export the complete model or a flat spreadsheet. Imports never overwrite matching IDs.</p></div></header><div class="feelings-data-cards"><article><h4>Export JSON</h4><p>Full check-ins, emotions, tags, IDs, timestamps, and sync-ready metadata.</p><a href="${feelingsApi.exportUrl("json")}" download="how-i-feel.json">Download JSON</a></article><article><h4>Export CSV</h4><p>Flattened timestamps, emotions, quadrants, tags, notes, and sources.</p><a href="${feelingsApi.exportUrl("csv")}" download="how-i-feel.csv">Download CSV</a></article><article><h4>Import How I Feel JSON</h4><p>Use a JSON file exported by this dashboard. Existing IDs are skipped.</p><label class="feelings-import-button">Choose JSON<input type="file" accept="application/json,.json" data-feelings-import></label></article></div><aside class="feelings-privacy-note"><b>Local-first</b><p>No check-in, tag, note, or insight is sent to an analytics service, LLM, cloud account, or remote API.</p></aside></section>`;
  }

  async function refreshAfterMutation(message) {
    await load({ refresh: true });
    onChanged();
    toast(message);
  }

  function selectEmotion(emotion, { focus = true } = {}) {
    state.emotion = emotion;
    state.quadrant = emotion.quadrant;
    if (focus) {
      state.meterFocus = emotion.quadrant;
      state.meterZoom = 1.85;
      state.meterDragX = 0;
      state.meterDragY = 0;
    }
    state.searchOpen = false;
    state.flowStep = "meter";
    render();
  }

  overlay.addEventListener("click", async (event) => {
    const target = event.target.closest("button, a, [data-feelings-import]");
    if (!target) {
      if (event.target === overlay) close();
      return;
    }
    const view = target.dataset.feelingsView;
    if (view) return setView(view);
    const action = target.dataset.feelingsAction;
    if (action === "close") return close();
    if (action === "retry") return load({ refresh: true });
    if (action === "new-checkin") { resetFlow(); return render(); }
    if (action === "open-search") { state.searchOpen = true; state.searchIndex = 0; render(); queueMicrotask(() => overlay.querySelector("[data-emotion-search]")?.focus()); return; }
    if (action === "close-search") { state.searchOpen = false; state.customEmotionOpen = false; render(); return; }
    if (action === "custom-emotion-open") { state.customEmotionOpen = true; render(); return; }
    if (target.dataset.quadrant) { state.quadrant = target.dataset.quadrant; state.meterFocus = target.dataset.quadrant; state.meterZoom = 1.85; state.meterDragX = 0; state.meterDragY = 0; state.flowStep = "meter"; render(); return; }
    if (target.dataset.emotionId) {
      if (suppressMeterClick) { suppressMeterClick = false; return; }
      return selectEmotion(state.emotions.find((emotion) => emotion.id === target.dataset.emotionId), { focus: false });
    }
    if (target.dataset.searchEmotion) return selectEmotion(state.emotions.find((emotion) => emotion.id === target.dataset.searchEmotion));
    if (target.dataset.searchQuadrant) {
      const key = target.dataset.searchQuadrant;
      state.searchQuadrants.has(key) ? state.searchQuadrants.delete(key) : state.searchQuadrants.add(key);
      state.searchIndex = 0; render(); return;
    }
    if (action === "emotion-continue") { state.flowStep = "tags"; render(); return; }
    if (target.dataset.meterPanX !== undefined) { panMeter(Number(target.dataset.meterPanX), Number(target.dataset.meterPanY)); return; }
    if (action === "meter-zoom-out") { setMeterZoom(state.meterZoom - .2); return; }
    if (action === "meter-zoom-in") { setMeterZoom(state.meterZoom + .2); return; }
    if (action === "meter-fit") { state.meterFocus = null; state.meterZoom = 1; state.meterDragX = 0; state.meterDragY = 0; render(); return; }
    if (target.dataset.tagId) { state.selectedTags.has(target.dataset.tagId) ? state.selectedTags.delete(target.dataset.tagId) : state.selectedTags.add(target.dataset.tagId); render(); return; }
    if (action === "tags-continue") { state.flowStep = "note"; render(); return; }
    if (action === "note-continue") { state.note = overlay.querySelector("[data-reflection-input]")?.value || state.note; state.flowStep = "review"; render(); return; }
    if (action === "flow-back") {
      const previous = { meter: "quadrant", tags: "meter", note: "tags", review: "note" };
      state.flowStep = previous[state.flowStep] || "quadrant"; render(); return;
    }
    if (action === "save-checkin") {
      state.occurredAt = overlay.querySelector("[data-review-time]")?.value || state.occurredAt;
      target.disabled = true;
      try {
        await feelingsApi.createCheckin({ emotionIds: [state.emotion.id], tags: state.tags.filter((tag) => state.selectedTags.has(tag.id)).map((tag) => tag.name), note: state.note, occurredAt: state.occurredAt, timezone: "Europe/Warsaw", source: "dashboard", sourceDevice: "desktop-dashboard", schemaVersion: 1 });
        state.flowStep = "success";
        await refreshAfterMutation("Check-in saved");
      } catch (error) { target.disabled = false; toast(error.message, true); }
      return;
    }
    if (target.dataset.historyRange !== undefined) {
      Object.assign(state.historyFilters, quickRange(Number(target.dataset.historyRange)));
      render(); return;
    }
    if (target.dataset.checkinId) { state.detailId = target.dataset.checkinId; state.detailEditing = false; render(); return; }
    if (action === "detail-close") { state.detailId = null; state.detailEditing = false; render(); return; }
    if (action === "detail-edit") { state.detailEditing = true; render(); return; }
    if (action === "detail-cancel-edit") { state.detailEditing = false; render(); return; }
    if (action === "detail-delete") {
      const item = state.checkins.find((checkin) => checkin.id === state.detailId);
      if (!window.confirm(`Delete the ${item?.emotion?.name || "selected"} check-in from ${formatWhen(item?.occurredAt)}? This removes it from history.`)) return;
      try { await feelingsApi.deleteCheckin(state.detailId); state.detailId = null; await refreshAfterMutation("Check-in deleted"); } catch (error) { toast(error.message, true); }
      return;
    }
    if (target.dataset.associationType) { state.associationType = target.dataset.associationType; state.associationName = ""; render(); }
  });

  overlay.addEventListener("pointerdown", (event) => {
    const viewport = event.target.closest?.("[data-meter-viewport]");
    if (!viewport || event.button !== 0 || event.target.closest?.(".feelings-meter-pan")) return;
    meterGesture = {
      viewport,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: state.meterDragX,
      originY: state.meterDragY,
      dragged: false,
    };
  });

  overlay.addEventListener("pointermove", (event) => {
    if (!meterGesture || event.pointerId !== meterGesture.pointerId) return;
    const deltaX = event.clientX - meterGesture.startX;
    const deltaY = event.clientY - meterGesture.startY;
    if (!meterGesture.dragged && Math.hypot(deltaX, deltaY) < 4) return;
    if (!meterGesture.dragged) {
      meterGesture.dragged = true;
      meterGesture.viewport.setPointerCapture?.(event.pointerId);
    }
    meterGesture.viewport.dataset.dragging = "true";
    state.meterDragX = meterGesture.originX + deltaX;
    state.meterDragY = meterGesture.originY + deltaY;
    applyMeterView();
    event.preventDefault();
  });

  function finishMeterGesture(event) {
    if (!meterGesture || event.pointerId !== meterGesture.pointerId) return;
    if (meterGesture.viewport.hasPointerCapture?.(event.pointerId)) {
      meterGesture.viewport.releasePointerCapture(event.pointerId);
    }
    delete meterGesture.viewport.dataset.dragging;
    if (meterGesture.dragged) {
      suppressMeterClick = true;
      window.setTimeout(() => { suppressMeterClick = false; }, 0);
    }
    meterGesture = null;
  }

  overlay.addEventListener("pointerup", finishMeterGesture);
  overlay.addEventListener("pointercancel", finishMeterGesture);

  overlay.addEventListener("wheel", (event) => {
    if (!event.target.closest?.("[data-meter-viewport]")) return;
    event.preventDefault();
    setMeterZoom(state.meterZoom + (event.deltaY < 0 ? .14 : -.14), { x: event.clientX, y: event.clientY });
  }, { passive: false });

  overlay.addEventListener("input", (event) => {
    if (event.target.matches("[data-emotion-search]")) {
      state.searchQuery = event.target.value;
      state.searchIndex = 0;
      render();
      queueMicrotask(() => { const input = overlay.querySelector("[data-emotion-search]"); input?.focus(); input?.setSelectionRange(input.value.length, input.value.length); });
    } else if (event.target.matches("[data-tag-search]")) {
      const needle = event.target.value.toLocaleLowerCase();
      overlay.querySelectorAll("[data-tag-id]").forEach((button) => { button.hidden = !button.textContent.toLocaleLowerCase().includes(needle); });
    } else if (event.target.matches("[data-reflection-input]")) state.note = event.target.value;
    else if (event.target.matches("[data-review-time]")) state.occurredAt = event.target.value;
  });

  overlay.addEventListener("change", async (event) => {
    if (event.target.closest("[data-history-filters]")) {
      state.historyFilters = Object.fromEntries(new FormData(event.target.closest("form")));
      render();
    } else if (event.target.matches("[data-insight-range]")) {
      state.insightRange = Number(event.target.value);
      try { state.insights = await feelingsApi.insights(state.insightRange || undefined); render(); } catch (error) { toast(error.message, true); }
    } else if (event.target.matches("[data-association-name]")) {
      state.associationName = event.target.value; render();
    } else if (event.target.matches("[data-feelings-import]")) {
      const file = event.target.files?.[0];
      if (!file || !window.confirm(`Import new records from ${file.name}? Existing check-in IDs will be skipped.`)) return;
      try {
        const result = await feelingsApi.importData(JSON.parse(await file.text()));
        await refreshAfterMutation(`Imported ${result.imported}; skipped ${result.skipped} existing records`);
      } catch (error) { toast(error.message || "Import failed", true); }
      event.target.value = "";
    }
  });

  overlay.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (event.target.matches("[data-custom-emotion-form]")) {
      const data = Object.fromEntries(new FormData(event.target));
      try {
        const result = await feelingsApi.createEmotion(data);
        state.emotions.push(result.emotion);
        selectEmotion(result.emotion);
        toast("Custom emotion added");
      } catch (error) { toast(error.message, true); }
    } else if (event.target.matches("[data-custom-tag-form]")) {
      const data = Object.fromEntries(new FormData(event.target));
      try {
        const result = await feelingsApi.createTag(data);
        state.tags.unshift(result.tag);
        state.selectedTags.add(result.tag.id);
        render(); toast("Custom tag added");
      } catch (error) { toast(error.message, true); }
    } else if (event.target.matches("[data-detail-edit-form]")) {
      const data = new FormData(event.target);
      const item = state.checkins.find((checkin) => checkin.id === state.detailId);
      if (item?.source === "legacy How We Feel import" && !window.confirm("Save changes to this imported legacy check-in?")) return;
      try {
        await feelingsApi.updateCheckin(state.detailId, { emotionId: data.get("emotionId"), occurredAt: data.get("occurredAt"), note: data.get("note"), tags: data.getAll("tags"), timezone: item.timezone });
        state.detailEditing = false;
        await refreshAfterMutation("Check-in updated");
      } catch (error) { toast(error.message, true); }
    }
  });

  overlay.addEventListener("keydown", (event) => {
    if (!event.target.matches("[data-emotion-search]")) return;
    const matches = searchEmotions(state.emotions, state.searchQuery, [...state.searchQuadrants]);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      state.searchIndex = (state.searchIndex + direction + matches.length) % Math.max(1, matches.length);
      render(); queueMicrotask(() => overlay.querySelector("[data-emotion-search]")?.focus());
    } else if (event.key === "Enter" && matches[state.searchIndex]) {
      event.preventDefault(); selectEmotion(matches[state.searchIndex]);
    }
  });

  function open(view = "checkin") {
    state.view = view;
    overlay.hidden = false;
    document.body.classList.add("feelings-workspace-open");
    load();
    render();
    queueMicrotask(() => overlay.querySelector("[data-feelings-action='close']")?.focus());
  }

  function close() {
    overlay.hidden = true;
    document.body.classList.remove("feelings-workspace-open");
  }

  document.addEventListener("keydown", (event) => {
    if (overlay.hidden || event.key !== "Escape") return;
    if (state.searchOpen) { state.searchOpen = false; render(); }
    else if (state.detailId) { state.detailId = null; state.detailEditing = false; render(); }
    else close();
  });

  return { open, close, refresh: () => load({ refresh: true }), element: overlay };
}
