const EARTH_RADIUS_KM = 6371.0088;

export function haversineKm(left, right) {
  const toRadians = (value) => Number(value) * Math.PI / 180;
  const [lon1, lat1] = left.map(toRadians);
  const [lon2, lat2] = right.map(toRadians);
  const dLat = lat2 - lat1;
  const dLon = lon2 - lon1;
  const value = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(value)));
}

export function buildCumulativeRouteDistance(route) {
  const cumulativeKm = [0];
  for (let index = 1; index < route.length; index += 1) {
    cumulativeKm.push(cumulativeKm[index - 1] + haversineKm(route[index - 1], route[index]));
  }
  return cumulativeKm;
}

function upperBound(values, target) {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = low + Math.floor((high - low) / 2);
    if (Number(values[middle]) <= target) low = middle + 1;
    else high = middle;
  }
  return low;
}

export function createJourneyEngine({ route, cumulativeKm, checkpoints }) {
  if (!Array.isArray(route) || route.length < 2) throw new Error("Journey route requires at least two points");
  const cumulative = Array.isArray(cumulativeKm) && cumulativeKm.length === route.length
    ? cumulativeKm.map(Number)
    : buildCumulativeRouteDistance(route);
  const orderedCheckpoints = [...(checkpoints || [])].sort((left, right) => left.index - right.index);
  const checkpointDistances = orderedCheckpoints.map((item) => Number(item.routeDistanceKm));
  const mainCheckpoints = orderedCheckpoints.filter((item) => !item.variantCheckpoint);
  const mainCheckpointDistances = mainCheckpoints.map((item) => Number(item.routeDistanceKm));
  const totalDistanceKm = cumulative.at(-1);

  function clampDistance(distanceKm) {
    return Math.max(0, Math.min(totalDistanceKm, Number(distanceKm) || 0));
  }

  function getPositionAtDistance(distanceKm) {
    const distance = clampDistance(distanceKm);
    const upper = upperBound(cumulative, distance);
    const lowerIndex = Math.max(0, Math.min(route.length - 1, upper - 1));
    const upperIndex = Math.max(0, Math.min(route.length - 1, upper));
    const startDistance = cumulative[lowerIndex];
    const span = cumulative[upperIndex] - startDistance;
    const ratio = span > 0 ? (distance - startDistance) / span : 0;
    const start = route[lowerIndex];
    const end = route[upperIndex];
    return {
      distanceKm: distance,
      routeDistanceKm: totalDistanceKm,
      remainingKm: Math.max(0, totalDistanceKm - distance),
      progress: totalDistanceKm > 0 ? distance / totalDistanceKm : 0,
      latitude: Number(start[1]) + (Number(end[1]) - Number(start[1])) * ratio,
      longitude: Number(start[0]) + (Number(end[0]) - Number(start[0])) * ratio,
    };
  }

  function getPreviousCheckpoint(distanceKm) {
    const index = Math.max(0, upperBound(mainCheckpointDistances, clampDistance(distanceKm)) - 1);
    return mainCheckpoints[index] || null;
  }

  function getNextCheckpoint(distanceKm) {
    const distance = clampDistance(distanceKm);
    const checkpoint = mainCheckpoints[upperBound(mainCheckpointDistances, distance)] || null;
    return checkpoint ? { ...checkpoint, distanceAwayKm: Math.max(0, Number(checkpoint.routeDistanceKm) - distance) } : null;
  }

  function getCrossedCheckpoints(previousDistanceKm, newDistanceKm) {
    const previous = clampDistance(previousDistanceKm);
    const current = clampDistance(newDistanceKm);
    if (current <= previous) return [];
    return orderedCheckpoints.slice(
      upperBound(checkpointDistances, previous),
      upperBound(checkpointDistances, current),
    );
  }

  function getJourneyProgress(committedDistanceKm, liveSessionDistanceKm = 0) {
    return getPositionAtDistance((Number(committedDistanceKm) || 0) + (Number(liveSessionDistanceKm) || 0));
  }

  return {
    checkpoints: orderedCheckpoints,
    getRouteTotalDistance: () => totalDistanceKm,
    getJourneyProgress,
    getPositionAtDistance,
    getCurrentCheckpoint: getPreviousCheckpoint,
    getPreviousCheckpoint,
    getNextCheckpoint,
    getCrossedCheckpoints,
    getJourneySegment(distanceKm) {
      return {
        previousCheckpoint: getPreviousCheckpoint(distanceKm),
        nextCheckpoint: getNextCheckpoint(distanceKm),
      };
    },
  };
}

export async function loadSantiagoJourneyEngine(fetchImpl = globalThis.fetch, baseUrl = globalThis.document?.baseURI) {
  const assetBase = new URL("./data/journeys/santiago/", baseUrl);
  const [routeResponse, metaResponse, checkpointResponse] = await Promise.all([
    fetchImpl(new URL("route.geojson", assetBase), { cache: "no-cache" }),
    fetchImpl(new URL("route-meta.json", assetBase), { cache: "no-cache" }),
    fetchImpl(new URL("checkpoints.json", assetBase), { cache: "no-cache" }),
  ]);
  if (![routeResponse, metaResponse, checkpointResponse].every((response) => response.ok)) {
    throw new Error("Santiago journey assets are unavailable");
  }
  const [routeDocument, meta, checkpointDocument] = await Promise.all([
    routeResponse.json(),
    metaResponse.json(),
    checkpointResponse.json(),
  ]);
  return createJourneyEngine({
    route: routeDocument.geometry?.coordinates,
    cumulativeKm: meta.cumulativeKm,
    checkpoints: checkpointDocument.checkpoints,
  });
}
