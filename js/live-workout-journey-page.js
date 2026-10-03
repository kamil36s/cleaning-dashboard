import {
  fetchJourneyPostcards,
  fetchJourneySnapshot,
  journeyPostcardImageUrl,
  uploadJourneyPostcard,
} from "./live-workout-journey-api.js";

let leafletPromise = null;

function loadLeafletFromCdn() {
  if (globalThis.L) return Promise.resolve(globalThis.L);
  if (!document.querySelector('link[data-journey-leaflet]')) {
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    stylesheet.dataset.journeyLeaflet = "";
    document.head.append(stylesheet);
  }
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-journey-leaflet]');
    if (existing) {
      existing.addEventListener("load", () => resolve(globalThis.L), { once: true });
      existing.addEventListener("error", () => reject(new Error("Nie udało się załadować silnika mapy")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.dataset.journeyLeaflet = "";
    script.addEventListener("load", () => resolve(globalThis.L), { once: true });
    script.addEventListener("error", () => reject(new Error("Nie udało się załadować silnika mapy")), { once: true });
    document.head.append(script);
  });
}

function loadLeaflet() {
  if (!leafletPromise) {
    leafletPromise = Promise.all([
      import("leaflet"),
      import("leaflet/dist/leaflet.css"),
    ]).then(([module]) => module.default || module).catch(loadLeafletFromCdn);
  }
  return leafletPromise;
}

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const formatKm = (value, digits = 1) => Number(value || 0).toLocaleString("pl-PL", {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
});

function isReached(checkpoint, distanceKm) {
  return Number(checkpoint.routeDistanceKm) <= Number(distanceKm) + 0.001;
}

export function journeyCollectionEntries(checkpoints, distanceKm, postcards = []) {
  const postcardMap = new Map(postcards.map((item) => [item.checkpointId, item]));
  return checkpoints.map((checkpoint) => ({
    checkpoint,
    reached: isReached(checkpoint, distanceKm),
    postcard: postcardMap.get(checkpoint.id) || null,
  }));
}

function nearestRouteIndex(route, position) {
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  route.forEach(([lon, lat], index) => {
    const distance = (Number(lon) - Number(position.lon)) ** 2 + (Number(lat) - Number(position.lat)) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

async function createJourneyMap(container, route, snapshot, previousMap) {
  previousMap?.remove();
  container.replaceChildren();
  if (!Array.isArray(route) || route.length < 2) {
    container.innerHTML = '<p class="workout-journey-empty">Mapa trasy jest niedostępna.</p>';
    return null;
  }

  const L = await loadLeaflet();
  const map = L.map(container, {
    zoomControl: true,
    attributionControl: true,
    preferCanvas: true,
    minZoom: 3,
    worldCopyJump: true,
  });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

  const latLngs = route.map(([lon, lat]) => [Number(lat), Number(lon)]);
  const routeLine = L.polyline(latLngs, { color: "#38bdf8", weight: 4, opacity: .72 }).addTo(map);
  const currentIndex = nearestRouteIndex(route, snapshot.position || {});
  if (currentIndex > 0) {
    L.polyline(latLngs.slice(0, currentIndex + 1), { color: "#f5cf72", weight: 6, opacity: .94 }).addTo(map);
  }

  (snapshot.checkpoints || []).forEach((checkpoint) => {
    const reached = isReached(checkpoint, snapshot.liveDistanceKm);
    L.circleMarker([Number(checkpoint.lat), Number(checkpoint.lon)], {
      radius: reached ? 5 : 3,
      weight: reached ? 2 : 1,
      color: reached ? "#fff1b8" : "#64748b",
      fillColor: reached ? "#f5cf72" : "#172033",
      fillOpacity: reached ? 1 : .72,
    }).bindTooltip(
      `<strong>#${checkpoint.index} · ${escapeHtml(checkpoint.name)}</strong><small>${escapeHtml(checkpoint.country)} · ${formatKm(checkpoint.routeDistanceKm)} km</small>`,
      { direction: "top", className: "workout-journey-map-tooltip" },
    ).addTo(map);
  });

  const currentIcon = L.divIcon({
    className: "workout-journey-current-icon",
    html: '<span aria-hidden="true"></span><b>TY</b>',
    iconSize: [46, 46],
    iconAnchor: [23, 23],
  });
  L.marker([Number(snapshot.position?.lat), Number(snapshot.position?.lon)], { icon: currentIcon, zIndexOffset: 1000 })
    .bindTooltip(`Twój punkt · ${formatKm(snapshot.liveDistanceKm)} km`, { direction: "top" })
    .addTo(map);
  map.fitBounds(routeLine.getBounds(), { padding: [28, 28] });
  window.setTimeout(() => map.invalidateSize(), 0);
  return map;
}

export function renderJourneyCollection(entries, filter) {
  const filtered = entries.filter((entry) => filter === "all" || (filter === "unlocked" ? entry.reached : !entry.reached));
  return filtered.map(({ checkpoint, reached, postcard }) => {
    if (!reached) {
      return `<article class="workout-postcard is-locked ${postcard ? "is-sealed" : "is-empty"}"><div class="workout-postcard-art"><div class="workout-postcard-lock" aria-hidden="true">${postcard ? "✓" : "✦"}</div><small>${postcard ? "POCZTÓWKA ZAPIECZĘTOWANA" : "GRAFIKA UKRYTA"}</small></div><div class="workout-postcard-copy"><span>ZABLOKOWANA · #${checkpoint.index}</span><strong>${escapeHtml(checkpoint.name)}</strong><small>${escapeHtml(checkpoint.country)} · ${formatKm(checkpoint.routeDistanceKm)} km trasy<br>${postcard ? "Projekt jest gotowy — odsłoni się po dotarciu" : "Możesz przygotować ją już teraz bez odsłaniania"}</small><button type="button" data-postcard-upload="${escapeHtml(checkpoint.id)}">${postcard ? "ZMIEŃ ZAPIECZĘTOWANĄ" : "WGRAJ W CIEMNO"}</button></div></article>`;
    }
    const image = postcard
      ? `<button type="button" class="workout-postcard-preview" data-postcard-preview="${escapeHtml(checkpoint.id)}" aria-label="Powiększ pocztówkę: ${escapeHtml(checkpoint.name)}"><img src="${journeyPostcardImageUrl(checkpoint.id, postcard.uploadedAt)}" alt="Pocztówka: ${escapeHtml(checkpoint.name)}" loading="lazy"><span>POWIĘKSZ</span></button>`
      : `<div class="workout-postcard-placeholder"><b>+</b><small>Dodaj własny projekt pocztówki</small></div>`;
    return `<article class="workout-postcard is-unlocked ${postcard ? "has-image" : "is-empty"}">
      <div class="workout-postcard-art">${image}</div>
      <div class="workout-postcard-copy"><span>ODKRYTO · #${checkpoint.index}</span><strong>${escapeHtml(checkpoint.name)}</strong><small>${escapeHtml(checkpoint.country)} · ${formatKm(checkpoint.routeDistanceKm)} km trasy</small><button type="button" data-postcard-upload="${escapeHtml(checkpoint.id)}">${postcard ? "ZMIEŃ POCZTÓWKĘ" : "WGRAJ POCZTÓWKĘ"}</button></div>
    </article>`;
  }).join("") || '<p class="workout-journey-empty">Brak pocztówek w tym filtrze.</p>';
}

export function initJourneyPage() {
  const root = document.getElementById("workout-journey-page");
  if (!root) return { refresh: async () => {} };
  const elements = {
    summary: document.getElementById("workout-journey-summary"),
    map: document.getElementById("workout-journey-map"),
    collection: document.getElementById("workout-postcard-collection"),
    status: document.getElementById("workout-journey-status"),
    file: document.getElementById("workout-postcard-file"),
    filters: document.getElementById("workout-postcard-filters"),
    refresh: document.getElementById("workout-journey-refresh"),
    previewDialog: document.getElementById("workout-postcard-preview-dialog"),
    previewImage: document.getElementById("workout-postcard-preview-image"),
    previewTitle: document.getElementById("workout-postcard-preview-title"),
    previewMeta: document.getElementById("workout-postcard-preview-meta"),
  };
  const state = { loaded: false, loading: false, filter: "all", entries: [], checkpointId: null, map: null };

  function renderCards() {
    elements.collection.innerHTML = renderJourneyCollection(state.entries, state.filter);
  }

  function showUploadFeedback(checkpointId, message, error = false) {
    const button = [...elements.collection.querySelectorAll("[data-postcard-upload]")]
      .find((item) => item.dataset.postcardUpload === checkpointId);
    if (!button) return;
    let feedback = button.parentElement.querySelector("[data-postcard-upload-status]");
    if (!feedback) {
      feedback = document.createElement("small");
      feedback.dataset.postcardUploadStatus = "";
      feedback.setAttribute("role", "status");
      button.insertAdjacentElement("afterend", feedback);
    }
    feedback.textContent = message;
    feedback.dataset.state = error ? "error" : "success";
  }

  async function refresh({ force = false } = {}) {
    if (state.loading || (state.loaded && !force)) return;
    state.loading = true;
    delete elements.status.dataset.state;
    elements.status.textContent = "Ładowanie podróży…";
    try {
      const [snapshot, postcards, routeResponse] = await Promise.all([
        fetchJourneySnapshot({ includeCheckpoints: true }),
        fetchJourneyPostcards(),
        fetch(new URL("../data/journeys/santiago/route.geojson", import.meta.url), { cache: "no-cache" }),
      ]);
      if (!routeResponse.ok) throw new Error("Mapa trasy jest niedostępna");
      const routeDocument = await routeResponse.json();
      state.entries = journeyCollectionEntries(snapshot.checkpoints || [], snapshot.liveDistanceKm, postcards);
      const unlocked = state.entries.filter((item) => item.reached).length;
      const withPostcard = state.entries.filter((item) => item.postcard).length;
      const sealed = state.entries.filter((item) => !item.reached && item.postcard).length;
      const next = snapshot.nextCheckpoint;
      elements.summary.innerHTML = `
        <article class="is-distance"><span>PRZEBYTA TRASA</span><strong>${formatKm(snapshot.liveDistanceKm)} <small>/ ${formatKm(snapshot.totalDistanceKm)} km</small></strong><div><i style="width:${Math.min(100, snapshot.progress * 100)}%"></i></div></article>
        <article><span>ODKRYTE MIEJSCA</span><strong>${unlocked}<small> / ${snapshot.checkpointCount}</small></strong><p>${snapshot.checkpointCount - unlocked} pozostaje zablokowanych</p></article>
        <article><span>GOTOWE POCZTÓWKI</span><strong>${withPostcard}<small> / ${snapshot.checkpointCount}</small></strong><p>${sealed} czeka zapieczętowanych</p></article>
        <article><span>NASTĘPNY CEL</span><strong class="is-place">${escapeHtml(next?.name || "Santiago de Compostela")}</strong><p>${next ? `${formatKm(next.distanceAwayKm)} km do punktu` : "Podróż ukończona"}</p></article>`;
      state.map = await createJourneyMap(elements.map, routeDocument.geometry?.coordinates, snapshot, state.map);
      renderCards();
      elements.status.textContent = `${unlocked} odkrytych miejsc · ${withPostcard} gotowych pocztówek · ${sealed} zapieczętowanych`;
      delete elements.status.dataset.state;
      state.loaded = true;
    } catch (error) {
      elements.status.textContent = error.message;
      elements.status.dataset.state = "error";
    } finally {
      state.loading = false;
    }
  }

  root.addEventListener("click", (event) => {
    const preview = event.target.closest("[data-postcard-preview]");
    if (preview) {
      const entry = state.entries.find((item) => item.checkpoint.id === preview.dataset.postcardPreview);
      if (!entry?.reached || !entry.postcard) return;
      elements.previewImage.src = journeyPostcardImageUrl(entry.checkpoint.id, entry.postcard.uploadedAt);
      elements.previewImage.alt = `Pocztówka: ${entry.checkpoint.name}`;
      elements.previewTitle.textContent = entry.checkpoint.name;
      elements.previewMeta.textContent = `${entry.checkpoint.country} · punkt #${entry.checkpoint.index} · ${formatKm(entry.checkpoint.routeDistanceKm)} km trasy`;
      elements.previewDialog.showModal();
      return;
    }
    const upload = event.target.closest("[data-postcard-upload]");
    if (!upload) return;
    state.checkpointId = upload.dataset.postcardUpload;
    elements.file.click();
  });
  elements.file.addEventListener("change", async () => {
    const file = elements.file.files?.[0];
    elements.file.value = "";
    if (!file || !state.checkpointId) return;
    const checkpointId = state.checkpointId;
    showUploadFeedback(checkpointId, `Wysyłanie ${file.name}…`);
    elements.status.textContent = `Wysyłanie ${file.name}…`;
    try {
      const postcard = await uploadJourneyPostcard(checkpointId, file);
      const entry = state.entries.find((item) => item.checkpoint.id === checkpointId);
      if (entry) entry.postcard = postcard;
      renderCards();
      showUploadFeedback(checkpointId, "Pocztówka zapisana");
      state.loaded = false;
      await refresh({ force: true });
      showUploadFeedback(checkpointId, "Pocztówka zapisana");
      window.dispatchEvent(new CustomEvent("live-workout:postcards-changed"));
    } catch (error) {
      elements.status.textContent = error.message;
      elements.status.dataset.state = "error";
      showUploadFeedback(checkpointId, error.message, true);
    }
  });
  elements.filters.addEventListener("click", (event) => {
    const filter = event.target.closest("[data-postcard-filter]")?.dataset.postcardFilter;
    if (!filter) return;
    state.filter = filter;
    elements.filters.querySelectorAll("button").forEach((button) => button.classList.toggle("is-active", button.dataset.postcardFilter === filter));
    renderCards();
  });
  elements.refresh.addEventListener("click", () => refresh({ force: true }));
  elements.previewDialog.addEventListener("click", (event) => {
    if (event.target === elements.previewDialog || event.target.closest("[data-postcard-preview-close]")) {
      elements.previewDialog.close();
    }
  });
  return { refresh };
}
