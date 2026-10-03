import L from "leaflet";
import "leaflet/dist/leaflet.css";

const DATA_ROOT = "./data/journeys/santiago";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function popupForLeg(leg) {
  return `
    <div class="route-qa-popup">
      <strong>#${leg.from.index} ${escapeHtml(leg.from.name)} → #${leg.to.index} ${escapeHtml(leg.to.name)}</strong>
      <dl>
        <dt>Route</dt><dd>${leg.routeDistanceKm.toFixed(2)} km</dd>
        <dt>Straight line</dt><dd>${leg.straightLineDistanceKm.toFixed(2)} km</dd>
        <dt>Detour ratio</dt><dd>${leg.detourRatio.toFixed(2)}</dd>
        <dt>Vertices</dt><dd>${leg.routeVertexCount}</dd>
        <dt>Source</dt><dd>${escapeHtml(leg.routingSource)}</dd>
      </dl>
      ${leg.flags.length ? `<p>${escapeHtml(leg.flags.join(", "))}</p>` : ""}
    </div>`;
}

function layerKind(leg) {
  if (leg.highlySuspicious) return "high";
  if (leg.suspicious) return "suspicious";
  return "normal";
}

function layerStyle(kind) {
  if (kind === "high") return { color: "#ef4444", weight: 6, opacity: 0.95 };
  if (kind === "suspicious") return { color: "#f59e0b", weight: 5, opacity: 0.92 };
  return { color: "#475569", weight: 3, opacity: 0.68 };
}

function renderSummary(report) {
  const summary = report.summary;
  document.querySelector("[data-qa-summary]").innerHTML = `
    <div><span>Total route</span><strong>${summary.auditedDistanceKm.toFixed(2)} km</strong></div>
    <div><span>Vertices</span><strong>${summary.routeVertexCount.toLocaleString()}</strong></div>
    <div><span>Suspicious</span><strong>${summary.suspiciousLegCount}</strong></div>
    <div><span>Highly suspicious</span><strong>${summary.highlySuspiciousLegCount}</strong></div>
    <div><span>Fallback</span><strong>${summary.fallbackLegCount}</strong></div>
    <div><span>Aggregate ratio</span><strong>${summary.aggregateDetourRatio.toFixed(3)}</strong></div>`;
}

async function start() {
  const [routeResponse, checkpointResponse, qaResponse] = await Promise.all([
    fetch(`${DATA_ROOT}/route.geojson`),
    fetch(`${DATA_ROOT}/checkpoints.json`),
    fetch(`${DATA_ROOT}/route-qa.json`),
  ]);
  if (![routeResponse, checkpointResponse, qaResponse].every((response) => response.ok)) {
    throw new Error("Journey QA assets could not be loaded");
  }
  const [routeDocument, checkpointDocument, report] = await Promise.all([
    routeResponse.json(),
    checkpointResponse.json(),
    qaResponse.json(),
  ]);
  const coordinates = routeDocument.geometry.coordinates;
  const checkpoints = checkpointDocument.checkpoints;
  renderSummary(report);

  const map = L.map("santiago-route-qa-map", { preferCanvas: true, zoomControl: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
  }).addTo(map);

  const groups = {
    normal: L.layerGroup().addTo(map),
    suspicious: L.layerGroup().addTo(map),
    high: L.layerGroup().addTo(map),
    checkpoints: L.layerGroup().addTo(map),
  };
  const layersByLeg = new Map();
  const routeBounds = L.latLngBounds([]);

  report.legs.forEach((leg) => {
    const kind = layerKind(leg);
    const points = coordinates
      .slice(leg.routeStartVertex, leg.routeEndVertex + 1)
      .map((point) => [point[1], point[0]]);
    const layer = L.polyline(points, layerStyle(kind))
      .bindTooltip(popupForLeg(leg), { sticky: true })
      .bindPopup(popupForLeg(leg));
    layer.addTo(groups[kind]);
    layersByLeg.set(leg.legIndex, layer);
    points.forEach((point) => routeBounds.extend(point));
  });

  checkpoints.forEach((checkpoint) => {
    const marker = L.marker([checkpoint.lat, checkpoint.lon], {
      icon: L.divIcon({
        className: "route-qa-checkpoint",
        html: String(checkpoint.index),
        iconSize: [22, 22],
      }),
      keyboard: true,
      title: `#${checkpoint.index} ${checkpoint.name}`,
    });
    marker.bindTooltip(`<strong>#${checkpoint.index}</strong> ${escapeHtml(checkpoint.name)}`, { direction: "top" });
    marker.addTo(groups.checkpoints);
  });
  map.fitBounds(routeBounds, { padding: [20, 20] });

  const flagged = report.legs
    .filter((leg) => leg.suspicious)
    .sort((left, right) => right.inspectionPriorityKm - left.inspectionPriorityKm);
  const list = document.querySelector("[data-qa-leg-list]");
  flagged.forEach((leg) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `route-qa-leg${leg.highlySuspicious ? " is-high" : ""}`;
    button.innerHTML = `
      <strong>#${leg.from.index} ${escapeHtml(leg.from.name)} → #${leg.to.index} ${escapeHtml(leg.to.name)}</strong>
      <small>${leg.routeDistanceKm.toFixed(2)} km · straight ${leg.straightLineDistanceKm.toFixed(2)} km · ${leg.detourRatio.toFixed(2)}×</small>`;
    button.addEventListener("click", () => {
      const layer = layersByLeg.get(leg.legIndex);
      map.fitBounds(layer.getBounds(), { padding: [40, 40], maxZoom: 14 });
      layer.openPopup();
    });
    list.append(button);
  });

  const toggles = [
    ["[data-qa-show-normal]", "normal"],
    ["[data-qa-show-suspicious]", "suspicious"],
    ["[data-qa-show-high]", "high"],
    ["[data-qa-show-checkpoints]", "checkpoints"],
  ];
  toggles.forEach(([selector, key]) => {
    document.querySelector(selector).addEventListener("change", (event) => {
      if (event.currentTarget.checked) groups[key].addTo(map);
      else groups[key].removeFrom(map);
    });
  });

  const requestedLeg = Number(new URLSearchParams(window.location.search).get("leg"));
  const requestedLayer = layersByLeg.get(requestedLeg);
  if (requestedLayer) {
    map.fitBounds(requestedLayer.getBounds(), { padding: [60, 60], maxZoom: 14 });
    requestedLayer.openPopup();
  }
}

start().catch((error) => {
  document.querySelector("[data-qa-summary]").innerHTML = `<p>${escapeHtml(error.message)}</p>`;
  console.error(error);
});
