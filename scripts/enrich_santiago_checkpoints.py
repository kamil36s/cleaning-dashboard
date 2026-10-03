#!/usr/bin/env python3
"""Build the static Kraków–Santiago journey assets.

The supplied 365 checkpoint identities remain authoritative. ``originalIndex``
preserves their source order while the accepted order review controls runtime
journey order and the small set of alternative-route milestones.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "journeys" / "santiago"
DEFAULT_PUBLIC_OUTPUT = ROOT / "public" / "data" / "journeys" / "santiago"
DEFAULT_SOURCE = DEFAULT_OUTPUT / "checkpoints-source.json"
USER_AGENT = "cleaning-dashboard-santiago-journey/1.0 (local personal dashboard)"
COUNTRY_CODES = {
    "Poland": "pl",
    "Czechia": "cz",
    "Austria": "at",
    "Liechtenstein": "li",
    "Switzerland": "ch",
    "France": "fr",
    "Spain": "es",
}
GEOCODE_QUERY_ALIASES = {
    184: ["Honto", "Honto Uhart-Cize"],
    187: ["Lepoeder"],
    191: ["Bizkarreta-Gerendiain"],
    250: ["Convento de San Antón Castrojeriz"],
    258: ["Villalcázar de Sirga"],
    283: ["Santibáñez de Valdeiglesias"],
    309: ["Las Herrerías de Valcarce"],
    311: ["Laguna de Castilla Vega de Valcarce"],
    313: ["Liñares Pedrafita do Cebreiro"],
    316: ["Fonfría Triacastela Lugo"],
    317: ["Biduedo Triacastela Lugo"],
    320: ["San Cristovo do Real", "San Cristovo do Real Samos"],
    322: ["Samos Lugo Galicia"],
    331: ["Vilachá Paradela Lugo"],
    334: ["Castromaior Portomarín Lugo"],
    337: ["Ligonde Monterroso Lugo"],
    338: ["Eirexe Ligonde Monterroso Lugo"],
    344: ["Ponte Campaña", "Ponte Campaña Palas de Rei"],
    346: ["O Coto Leboreiro Melide"],
    349: ["Castañeda Arzúa Galicia"],
    355: ["Brea O Pino A Coruña", "San Miguel de Cerceda O Pino"],
    356: ["O Empalme O Pino A Coruña"],
    358: ["A Rúa O Pino A Coruña"],
    352: ["Taberna Vella O Pino", "Taberna Vella Arzúa", "Tabernavella"],
}
NOMINATIM_PREFERRED = {250, 309, 311, 313, 316, 317, 322, 331, 334, 337, 338, 346, 349, 355, 356, 358}
REFERENCE_COORDINATES = {
    # Wikipedia's municipality coordinate is on the ski slope south of the
    # settlement and makes BRouter leave the road corridor.  This is the
    # geocoded official town-hall address (Dorfstraße 46).
    84: {
        "lat": 47.1286596,
        "lon": 10.2659990,
        "source": "reference",
        "reference": "https://www.tirol.gv.at/gemeinden/gemeinde/70621/",
        "resolvedTitle": "St. Anton am Arlberg town hall",
    },
    # The authoritative dataset spelling is retained; Honto/Huntto is the
    # documented local spelling of this Camino hamlet.
    184: {
        "lat": 43.124070,
        "lon": -1.244490,
        "source": "reference",
        "reference": "https://fr.wikipedia.org/wiki/Honto",
        "resolvedTitle": "Honto",
    },
}
EARTH_RADIUS_KM = 6371.0088


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def haversine_km(left, right):
    lon1, lat1 = map(math.radians, left[:2])
    lon2, lat2 = map(math.radians, right[:2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1, math.sqrt(value)))


def request_json(url, *, retries=4, timeout=90):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if attempt + 1 == retries:
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 15 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 == retries:
                raise
            time.sleep(2 ** attempt)


def source_title(checkpoint):
    reference = str(checkpoint.get("place_reference") or "")
    parsed = urllib.parse.urlparse(reference)
    marker = "/wiki/"
    if marker not in parsed.path:
        return checkpoint["name"]
    return urllib.parse.unquote(parsed.path.split(marker, 1)[1]).replace("_", " ")


def normalize_source_checkpoints(checkpoints):
    normalized = []
    for position, checkpoint in enumerate(checkpoints, start=1):
        original_index = int(checkpoint.get("originalIndex") or checkpoint.get("index") or position)
        normalized.append({
            **checkpoint,
            "id": checkpoint.get("id") or f"santiago-{original_index:03d}",
            "originalIndex": original_index,
            "index": original_index,
        })
    return normalized


def validate_authoritative(checkpoints):
    errors = []
    if len(checkpoints) != 365:
        errors.append(f"checkpoint count is {len(checkpoints)}, expected 365")
    if [item.get("index") for item in checkpoints] != list(range(1, 366)):
        errors.append("checkpoint indexes are not exactly 1..365")
    if [item.get("originalIndex") for item in checkpoints] != list(range(1, 366)):
        errors.append("originalIndex values are not exactly 1..365")
    if len({item.get("id") for item in checkpoints}) != 365:
        errors.append("stable checkpoint IDs are not unique")
    anchors = ((1, "Kraków"), (183, "St Jean Pied de Port"), (365, "Santiago de Compostela"))
    for index, name in anchors:
        actual = checkpoints[index - 1].get("name") if len(checkpoints) >= index else None
        if actual != name:
            errors.append(f"checkpoint {index} is {actual!r}, expected {name!r}")
    if errors:
        raise ValueError("Authoritative checkpoint validation failed: " + "; ".join(errors))


def apply_order_review(checkpoints, review):
    by_original_index = {int(item["originalIndex"]): item for item in checkpoints}
    order = [int(value) for value in review.get("runtimeOrderOriginalIndexes") or []]
    if len(order) != 365 or set(order) != set(by_original_index):
        raise ValueError("Checkpoint order review must contain every originalIndex exactly once")
    variants = {
        int(item["originalIndex"]): item
        for item in review.get("variantCheckpoints") or []
    }
    ordered = []
    for journey_index, original_index in enumerate(order, start=1):
        checkpoint = {
            **by_original_index[original_index],
            "index": journey_index,
            "journeyIndex": journey_index,
        }
        variant = variants.get(original_index)
        if variant:
            checkpoint.update({
                "variantCheckpoint": True,
                "associatedCheckpointId": variant["associatedCheckpointId"],
                "associatedOriginalIndex": int(variant["associatedOriginalIndex"]),
                "variantReason": variant["reason"],
            })
        ordered.append(checkpoint)
    return ordered


def wikipedia_coordinates(checkpoints, cache, offline=False):
    missing = [
        item for item in checkpoints
        if str(item["index"]) not in cache and item["index"] not in NOMINATIM_PREFERRED
    ]
    if offline or not missing:
        return
    for offset in range(0, len(missing), 25):
        batch = missing[offset:offset + 25]
        titles = [source_title(item) for item in batch]
        query = urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "redirects": "1",
            "prop": "coordinates|pageimages",
            "piprop": "original",
            "titles": "|".join(titles),
        })
        payload = request_json(f"https://en.wikipedia.org/w/api.php?{query}")
        aliases = {title: title for title in titles}
        for item in payload.get("query", {}).get("normalized", []):
            aliases[item["from"]] = item["to"]
        for item in payload.get("query", {}).get("redirects", []):
            for original, current in list(aliases.items()):
                if current == item["from"]:
                    aliases[original] = item["to"]
        pages = {page.get("title"): page for page in payload.get("query", {}).get("pages", {}).values()}
        for checkpoint, title in zip(batch, titles):
            page = pages.get(aliases.get(title, title), {})
            coordinates = page.get("coordinates") or []
            if coordinates:
                coordinate = coordinates[0]
                cache[str(checkpoint["index"])] = {
                    "lat": float(coordinate["lat"]),
                    "lon": float(coordinate["lon"]),
                    "source": "wikipedia",
                    "resolvedTitle": page.get("title"),
                    "imageUrl": (page.get("original") or {}).get("source"),
                }
        print(f"Wikipedia coordinates: {min(offset + len(batch), len(missing))}/{len(missing)}", flush=True)
        time.sleep(1.1)


def nearby_known(checkpoints, cache, position, direction):
    cursor = position + direction
    while 0 <= cursor < len(checkpoints):
        result = cache.get(str(checkpoints[cursor]["index"]))
        if result and result.get("lat") is not None and result.get("lon") is not None:
            return (float(result["lon"]), float(result["lat"]))
        cursor += direction
    return None


def nominatim_coordinates(checkpoints, cache, cache_path, offline=False):
    unresolved = [item for item in checkpoints if str(item["index"]) not in cache]
    if offline:
        return
    last_request = 0.0
    for number, checkpoint in enumerate(unresolved, start=1):
        position = checkpoint["index"] - 1
        previous = nearby_known(checkpoints, cache, position, -1)
        following = nearby_known(checkpoints, cache, position, 1)
        aliases = GEOCODE_QUERY_ALIASES.get(checkpoint["index"], [])
        names = [*aliases, checkpoint["name"]] if checkpoint["index"] in NOMINATIM_PREFERRED else [checkpoint["name"], *aliases]
        if "," in checkpoint["name"]:
            names.append(checkpoint["name"].split(",", 1)[0].strip())
        if "(" in checkpoint["name"]:
            names.append(checkpoint["name"].split("(", 1)[0].strip())
        for separator in (" / ", "/"):
            if separator in checkpoint["name"]:
                names.extend(part.strip() for part in checkpoint["name"].split(separator) if part.strip())
        candidates = []
        for name in dict.fromkeys(names):
            delay = 1.05 - (time.monotonic() - last_request)
            if delay > 0:
                time.sleep(delay)
            query = urllib.parse.urlencode({
                "q": f"{name}, {checkpoint['country']}",
                "format": "jsonv2",
                "limit": "8",
                "addressdetails": "1",
                "countrycodes": COUNTRY_CODES[checkpoint["country"]],
            })
            last_request = time.monotonic()
            results = request_json(f"https://nominatim.openstreetmap.org/search?{query}")
            candidates.extend(results)
            if results:
                break
        scored = []
        for candidate in candidates:
            coordinate = (float(candidate["lon"]), float(candidate["lat"]))
            distances = [haversine_km(coordinate, anchor) for anchor in (previous, following) if anchor]
            score = sum(distances) if distances else 0
            scored.append((score, coordinate, candidate))
        if scored:
            _score, coordinate, candidate = min(scored, key=lambda item: item[0])
            cache[str(checkpoint["index"])] = {
                "lat": coordinate[1],
                "lon": coordinate[0],
                "source": "nominatim",
                "displayName": candidate.get("display_name"),
                "osmType": candidate.get("osm_type"),
                "osmId": candidate.get("osm_id"),
                "query": name,
            }
            write_json(cache_path, cache)
        print(f"Nominatim coordinates: {number}/{len(unresolved)} - checkpoint {checkpoint['index']}", flush=True)


def fetch_bicycle_route(coordinates, cache_path: Path, offline=False, chunk_size=24):
    coordinates_hash = hashlib.sha256(json.dumps(coordinates, separators=(",", ":")).encode("utf-8")).hexdigest()
    if cache_path.exists():
        payload = read_json(cache_path)
        geometry = payload.get("geometry", payload)
        properties = payload.get("properties") or {}
        if properties.get("coordinateHash") == coordinates_hash and geometry.get("type") == "LineString" and len(geometry.get("coordinates") or []) >= 2:
            return geometry["coordinates"]
    if offline:
        raise RuntimeError("route cache is missing and --offline was requested")
    route = []
    parts_dir = cache_path.parent / "route-parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    route_sources = set()
    expected_part_paths = set()
    for start in range(0, len(coordinates) - 1, chunk_size - 1):
        chunk = coordinates[start:min(len(coordinates), start + chunk_size)]
        if len(chunk) < 2:
            break
        part_path = parts_dir / f"{start + 1:03d}-{start + len(chunk):03d}.geojson"
        expected_part_paths.add(part_path)
        part_hash = hashlib.sha256(json.dumps(chunk, separators=(",", ":")).encode("utf-8")).hexdigest()
        part_cached = read_json(part_path) if part_path.exists() else None
        if part_cached and (part_cached.get("properties") or {}).get("coordinateHash") == part_hash:
            part_payload = part_cached
            geometry = part_payload.get("geometry") or {}
            source = (part_payload.get("properties") or {}).get("source", "cached")
        elif offline:
            raise RuntimeError(f"route part cache is missing: {part_path.name}")
        else:
            source = "BRouter trekking"
            lonlats = "|".join(f"{lon:.6f},{lat:.6f}" for lon, lat in chunk)
            query = urllib.parse.urlencode({
                "lonlats": lonlats,
                "profile": "trekking",
                "alternativeidx": "0",
                "format": "geojson",
            }, safe="|,")
            try:
                payload = request_json(f"https://brouter.de/brouter?{query}", retries=2, timeout=180)
                geometry = payload.get("geometry") or payload.get("features", [{}])[0].get("geometry") or {}
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                source = "OSRM bicycle fallback"
                osrm_points = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in chunk)
                osrm_query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
                payload = request_json(
                    f"https://routing.openstreetmap.de/routed-bike/route/v1/driving/{osrm_points}?{osrm_query}",
                    retries=3,
                    timeout=180,
                )
                geometry = (payload.get("routes") or [{}])[0].get("geometry") or {}
            write_json(part_path, {"type": "Feature", "properties": {"source": source, "coordinateHash": part_hash}, "geometry": geometry})
        points = geometry.get("coordinates") or []
        if geometry.get("type") != "LineString" or len(points) < 2:
            raise RuntimeError(f"BRouter returned no LineString for checkpoints {start + 1}..{start + len(chunk)}")
        if route and points[0] == route[-1]:
            points = points[1:]
        route.extend(points)
        route_sources.add(source)
        print(f"Bicycle route: checkpoints {start + 1}..{start + len(chunk)}", flush=True)
        time.sleep(2)
    for stale_path in parts_dir.glob("*.geojson"):
        if stale_path not in expected_part_paths:
            stale_path.unlink()
    geometry = {"type": "LineString", "coordinates": route}
    write_json(cache_path, {"type": "Feature", "properties": {"source": " / ".join(sorted(route_sources)), "coordinateHash": coordinates_hash}, "geometry": geometry})
    return route


def cumulative_distances(route):
    values = [0.0]
    for left, right in zip(route, route[1:]):
        values.append(values[-1] + haversine_km(left, right))
    return values


def point_segment_distance_km(point, start, end):
    latitude = math.radians((float(start[1]) + float(end[1]) + float(point[1])) / 3)
    scale_x = 111.320 * math.cos(latitude)
    scale_y = 110.574
    px, py = (float(point[0]) - float(start[0])) * scale_x, (float(point[1]) - float(start[1])) * scale_y
    ex, ey = (float(end[0]) - float(start[0])) * scale_x, (float(end[1]) - float(start[1])) * scale_y
    length_squared = ex * ex + ey * ey
    if length_squared <= 0:
        return math.hypot(px, py)
    ratio = max(0.0, min(1.0, (px * ex + py * ey) / length_squared))
    return math.hypot(px - ratio * ex, py - ratio * ey)


def simplify_route(route, tolerance_km=0.025):
    """Douglas-Peucker simplification for a compact runtime route asset."""
    if len(route) <= 2:
        return route
    keep = {0, len(route) - 1}
    pending = [(0, len(route) - 1)]
    while pending:
        start, end = pending.pop()
        furthest_index = None
        furthest_distance = tolerance_km
        for index in range(start + 1, end):
            distance = point_segment_distance_km(route[index], route[start], route[end])
            if distance > furthest_distance:
                furthest_distance = distance
                furthest_index = index
        if furthest_index is not None:
            keep.add(furthest_index)
            pending.append((start, furthest_index))
            pending.append((furthest_index, end))
    return [route[index] for index in sorted(keep)]


def snap_checkpoints(checkpoints, route, cumulative):
    enriched = []
    previous_vertex = 0
    for checkpoint in checkpoints:
        target = (float(checkpoint["lon"]), float(checkpoint["lat"]))
        best_index = previous_vertex
        best_distance = float("inf")
        for index in range(previous_vertex, len(route)):
            distance = haversine_km(target, route[index])
            if distance < best_distance:
                best_distance = distance
                best_index = index
            if distance <= 0.06:
                best_index = index
                best_distance = distance
                break
        previous_vertex = best_index
        route_distance = cumulative[best_index]
        enriched.append({
            **checkpoint,
            "routeDistanceKm": round(route_distance, 6),
            "routeVertexIndex": best_index,
            "routeOffsetKm": round(best_distance, 6),
        })
    return enriched


def attach_variant_checkpoints(checkpoints, enriched_main, route):
    main_by_id = {item["id"]: item for item in enriched_main}
    enriched_by_id = dict(main_by_id)
    for checkpoint in checkpoints:
        if not checkpoint.get("variantCheckpoint"):
            continue
        associated = main_by_id.get(checkpoint.get("associatedCheckpointId"))
        if not associated:
            raise ValueError(f"Variant checkpoint {checkpoint['name']} has no main-route association")
        vertex_index = int(associated["routeVertexIndex"])
        geographic_offset = haversine_km(
            [float(checkpoint["lon"]), float(checkpoint["lat"])],
            route[vertex_index],
        )
        enriched_by_id[checkpoint["id"]] = {
            **checkpoint,
            "routeDistanceKm": associated["routeDistanceKm"],
            "routeVertexIndex": vertex_index,
            "routeOffsetKm": associated["routeOffsetKm"],
            "variantGeographicOffsetKm": round(geographic_offset, 6),
            "associatedJourneyIndex": associated["journeyIndex"],
            "routeSequenceIndex": associated["routeSequenceIndex"],
        }
    return [enriched_by_id[item["id"]] for item in checkpoints]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--public-output-dir", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
    parser.add_argument("--offline", action="store_true", help="Use cached coordinates and route only")
    parser.add_argument(
        "--source-copy-only",
        action="store_true",
        help="Refresh the immutable authoritative source copy without rebuilding route assets",
    )
    args = parser.parse_args()

    source_document = read_json(args.source)
    checkpoints = normalize_source_checkpoints(source_document.get("checkpoints") or source_document)
    validate_authoritative(checkpoints)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_copy = args.output_dir / "checkpoints-source.json"
    normalized_source_document = {
        **(source_document if isinstance(source_document, dict) else {}),
        "checkpoint_count": len(checkpoints),
        "checkpoints": checkpoints,
    }
    write_json(source_copy, normalized_source_document)
    if args.source_copy_only:
        print(f"Copied authoritative source to {source_copy}.")
        return

    cache_path = args.output_dir / "geocode-cache.json"
    cache = read_json(cache_path) if cache_path.exists() else {}
    if not args.offline:
        for index in NOMINATIM_PREFERRED:
            expected_query = GEOCODE_QUERY_ALIASES[index][0]
            if (cache.get(str(index)) or {}).get("query") != expected_query:
                cache.pop(str(index), None)
    for index, resolved in REFERENCE_COORDINATES.items():
        cache[str(index)] = {**cache.get(str(index), {}), **resolved}
    write_json(cache_path, cache)
    wikipedia_coordinates(checkpoints, cache, offline=args.offline)
    write_json(cache_path, cache)
    nominatim_coordinates(checkpoints, cache, cache_path, offline=args.offline)
    write_json(cache_path, cache)

    unresolved = [item for item in checkpoints if str(item["index"]) not in cache]
    if unresolved:
        names = ", ".join(f"{item['index']} {item['name']}" for item in unresolved)
        raise RuntimeError(f"Unresolved checkpoint coordinates: {names}")

    located_source = []
    for checkpoint in checkpoints:
        resolved = cache[str(checkpoint["index"])]
        located_source.append({
            **checkpoint,
            "lat": round(float(resolved["lat"]), 7),
            "lon": round(float(resolved["lon"]), 7),
            "coordinateSource": resolved.get("source"),
            **({"imageUrl": resolved["imageUrl"]} if resolved.get("imageUrl") else {}),
        })
    review = read_json(args.output_dir / "checkpoint-order-review.json")
    located = apply_order_review(located_source, review)
    main_checkpoints = [item for item in located if not item.get("variantCheckpoint")]
    for route_sequence_index, checkpoint in enumerate(main_checkpoints, start=1):
        checkpoint["routeSequenceIndex"] = route_sequence_index
    coordinates = [(item["lon"], item["lat"]) for item in main_checkpoints]
    route_path = args.output_dir / "route.geojson"
    route = fetch_bicycle_route(coordinates, route_path, offline=args.offline)
    route = simplify_route(route)
    route_payload = read_json(route_path)
    route_properties = dict(route_payload.get("properties") or {})
    route_properties.update({"simplificationToleranceM": 25, "vertexCount": len(route)})
    write_json(route_path, {"type": "Feature", "properties": route_properties, "geometry": {"type": "LineString", "coordinates": route}})
    cumulative = cumulative_distances(route)
    enriched_main = snap_checkpoints(main_checkpoints, route, cumulative)
    enriched = attach_variant_checkpoints(located, enriched_main, route)
    checkpoint_output = {
        "dataset": source_document.get("dataset", "Kraków to Santiago de Compostela"),
        "version": source_document.get("version", 1),
        "checkpoint_count": len(enriched),
        "source": "checkpoints-source.json",
        "orderReview": "checkpoint-order-review.json",
        "checkpoints": enriched,
    }
    route_meta_output = {
        "id": "krakow-santiago",
        "displayName": "Kraków → Santiago",
        "checkpointCount": len(enriched),
        "mainRouteCheckpointCount": len(main_checkpoints),
        "variantCheckpointCount": len(enriched) - len(main_checkpoints),
        "routeSource": "BRouter trekking (OpenStreetMap data), cached at build time",
        "vertexCount": len(route),
        "totalDistanceKm": round(cumulative[-1], 6),
        "cumulativeKm": [round(value, 6) for value in cumulative],
    }
    write_json(args.output_dir / "checkpoints.json", checkpoint_output)
    write_json(args.output_dir / "route-meta.json", route_meta_output)
    args.public_output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.public_output_dir / "checkpoints.json", checkpoint_output)
    write_json(args.public_output_dir / "route-meta.json", route_meta_output)
    write_json(args.public_output_dir / "route.geojson", read_json(route_path))
    print(f"Wrote {len(enriched)} checkpoints and {len(route)} route vertices ({cumulative[-1]:.2f} km).")


if __name__ == "__main__":
    main()
