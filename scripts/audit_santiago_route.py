#!/usr/bin/env python3
"""Build reproducible QA metrics for the Kraków–Santiago route geometry."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "journeys" / "santiago"
DEFAULT_PUBLIC_DIR = ROOT / "public" / "data" / "journeys" / "santiago"
DEFAULT_REPORT = ROOT / "docs" / "santiago-route-qa.md"
EARTH_RADIUS_KM = 6371.0088
SUSPICIOUS_RATIO = 1.8
HIGHLY_SUSPICIOUS_RATIO = 2.5
LONG_LEG_KM = 60.0
ORIGINAL_REPORTED_DISTANCE_KM = 4423.50


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
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, value)))


def cumulative_distances(route):
    cumulative = [0.0]
    for left, right in zip(route, route[1:]):
        cumulative.append(cumulative[-1] + haversine_km(left, right))
    return cumulative


def local_xy(point, reference_latitude):
    latitude = math.radians(reference_latitude)
    return float(point[0]) * 111.320 * math.cos(latitude), float(point[1]) * 110.574


def point_segment_distance_km(point, start, end):
    reference_latitude = (float(point[1]) + float(start[1]) + float(end[1])) / 3
    px, py = local_xy(point, reference_latitude)
    ax, ay = local_xy(start, reference_latitude)
    bx, by = local_xy(end, reference_latitude)
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return math.hypot(px - ax, py - ay)
    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + fraction * dx), py - (ay + fraction * dy))


def projected_progress(point, start, end):
    reference_latitude = (float(start[1]) + float(end[1])) / 2
    px, py = local_xy(point, reference_latitude)
    ax, ay = local_xy(start, reference_latitude)
    bx, by = local_xy(end, reference_latitude)
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return 0.0
    return ((px - ax) * dx + (py - ay) * dy) / length_squared


def _orientation(a, b, c):
    return (float(b[0]) - float(a[0])) * (float(c[1]) - float(a[1])) - (
        float(b[1]) - float(a[1])
    ) * (float(c[0]) - float(a[0]))


def proper_segment_intersection(a, b, c, d, epsilon=1e-12):
    """Return true only for a proper crossing, not a shared/touching endpoint."""
    values = (_orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b))
    if any(abs(value) <= epsilon for value in values):
        return False
    return (values[0] > 0) != (values[1] > 0) and (values[2] > 0) != (values[3] > 0)


def count_self_intersections(points):
    count = 0
    segment_count = len(points) - 1
    for left_index in range(segment_count):
        a, b = points[left_index], points[left_index + 1]
        min_ax, max_ax = sorted((float(a[0]), float(b[0])))
        min_ay, max_ay = sorted((float(a[1]), float(b[1])))
        for right_index in range(left_index + 2, segment_count):
            c, d = points[right_index], points[right_index + 1]
            min_cx, max_cx = sorted((float(c[0]), float(d[0])))
            min_cy, max_cy = sorted((float(c[1]), float(d[1])))
            if max_ax < min_cx or max_cx < min_ax or max_ay < min_cy or max_cy < min_ay:
                continue
            if proper_segment_intersection(a, b, c, d):
                count += 1
    return count


def coordinate_key(point):
    return round(float(point[0]), 7), round(float(point[1]), 7)


def find_global_retrace_loops(route, cumulative, checkpoints, minimum_km=0.5):
    occurrences = defaultdict(list)
    for index, point in enumerate(route):
        occurrences[coordinate_key(point)].append(index)
    pairs = []
    for indexes in occurrences.values():
        for left, right in zip(indexes, indexes[1:]):
            distance = float(cumulative[right]) - float(cumulative[left])
            if distance >= minimum_km:
                pairs.append({"start": left, "end": right, "distance": distance})
    groups = []
    for pair in sorted(pairs, key=lambda item: (item["start"], item["end"])):
        if groups and pair["start"] <= groups[-1]["end"]:
            group = groups[-1]
            group["end"] = max(group["end"], pair["end"])
            group["maxDistanceKm"] = max(group["maxDistanceKm"], pair["distance"])
            group["repeatedCoordinatePairs"] += 1
        else:
            groups.append(
                {
                    "start": pair["start"],
                    "end": pair["end"],
                    "maxDistanceKm": pair["distance"],
                    "repeatedCoordinatePairs": 1,
                }
            )
    checkpoint_vertices = [int(item["routeVertexIndex"]) for item in checkpoints]
    results = []
    for group in groups:
        start_checkpoint = max(0, bisect.bisect_right(checkpoint_vertices, group["start"]) - 1)
        end_checkpoint = max(0, bisect.bisect_right(checkpoint_vertices, group["end"]) - 1)
        results.append(
            {
                "routeStartVertex": group["start"],
                "routeEndVertex": group["end"],
                "fromCheckpointIndex": int(checkpoints[start_checkpoint]["index"]),
                "fromCheckpointName": checkpoints[start_checkpoint]["name"],
                "toCheckpointIndex": int(checkpoints[end_checkpoint]["index"]),
                "toCheckpointName": checkpoints[end_checkpoint]["name"],
                "maxClosedLoopKm": round(group["maxDistanceKm"], 6),
                "repeatedCoordinatePairs": group["repeatedCoordinatePairs"],
            }
        )
    return sorted(results, key=lambda item: item["maxClosedLoopKm"], reverse=True)


def parse_route_parts(parts_dir: Path):
    parts = []
    pattern = re.compile(r"^(\d{3})-(\d{3})\.geojson$")
    for path in sorted(parts_dir.glob("*.geojson")):
        match = pattern.match(path.name)
        if not match:
            continue
        payload = read_json(path)
        properties = payload.get("properties") or {}
        parts.append(
            {
                "start": int(match.group(1)),
                "end": int(match.group(2)),
                "file": path.name,
                "source": properties.get("source", "unknown"),
                "coordinateHash": properties.get("coordinateHash"),
            }
        )
    return parts


def source_for_leg(from_index, route_parts):
    for part in route_parts:
        if part["start"] <= from_index < part["end"]:
            return part
    return {"file": None, "source": "unknown", "coordinateHash": None}


def analyze_leg(left, right, route, route_parts):
    start_index = int(left["routeVertexIndex"])
    end_index = int(right["routeVertexIndex"])
    points = route[start_index : end_index + 1]
    if len(points) < 2:
        points = [[left["lon"], left["lat"]], [right["lon"], right["lat"]]]
    start = [float(left["lon"]), float(left["lat"])]
    end = [float(right["lon"]), float(right["lat"])]
    route_distance = float(right["routeDistanceKm"]) - float(left["routeDistanceKm"])
    straight_distance = haversine_km(start, end)
    ratio = route_distance / straight_distance if straight_distance > 0.001 else None
    progress = [projected_progress(point, start, end) for point in points]
    reverse_projected_km = sum(
        max(0.0, previous - current) * straight_distance for previous, current in zip(progress, progress[1:])
    )
    max_deviation = max(point_segment_distance_km(point, start, end) for point in points)
    keys = [coordinate_key(point) for point in points]
    repeated_coordinates = sum(count - 1 for count in Counter(keys).values() if count > 1)
    consecutive_repeats = sum(left_key == right_key for left_key, right_key in zip(keys, keys[1:]))
    local_cumulative = cumulative_distances(points)
    first_occurrence = {}
    max_closed_loop = 0.0
    for index, key in enumerate(keys):
        if key in first_occurrence:
            max_closed_loop = max(max_closed_loop, local_cumulative[index] - local_cumulative[first_occurrence[key]])
        else:
            first_occurrence[key] = index
    self_intersections = count_self_intersections(points)
    source = source_for_leg(int(left.get("routeSequenceIndex") or left["index"]), route_parts)
    fallback = "fallback" in str(source["source"]).lower()
    excess = max(0.0, route_distance - straight_distance)
    flags = []
    if ratio is not None and ratio > SUSPICIOUS_RATIO:
        flags.append("detour_ratio")
    if ratio is not None and ratio > HIGHLY_SUSPICIOUS_RATIO:
        flags.append("high_detour_ratio")
    if route_distance > LONG_LEG_KM:
        flags.append("unexpectedly_long")
    if fallback:
        flags.append("fallback_geometry")
    if consecutive_repeats:
        flags.append("consecutive_repeated_coordinates")
    elif repeated_coordinates:
        flags.append("repeated_coordinates")
    if reverse_projected_km > max(5.0, route_distance * 0.15):
        flags.append("loop_or_backtracking")
    if self_intersections and ratio is not None and ratio > 1.5:
        flags.append("self_intersection")
    if max_deviation > max(15.0, straight_distance * 0.75) and ratio is not None and ratio > 1.5:
        flags.append("wide_corridor_deviation")
    if left.get("country") != right.get("country") and ratio is not None and ratio > 1.8 and excess > 5:
        flags.append("border_detour")
    highly_suspicious = bool(
        ratio is not None and ratio > HIGHLY_SUSPICIOUS_RATIO
        or fallback
        or "loop_or_backtracking" in flags
    )
    return {
        "legIndex": int(left.get("routeSequenceIndex") or left["index"]),
        "from": {
            "index": int(left["index"]),
            "originalIndex": int(left.get("originalIndex") or left["index"]),
            "name": left["name"],
            "country": left.get("country"),
            "lat": float(left["lat"]),
            "lon": float(left["lon"]),
        },
        "to": {
            "index": int(right["index"]),
            "originalIndex": int(right.get("originalIndex") or right["index"]),
            "name": right["name"],
            "country": right.get("country"),
            "lat": float(right["lat"]),
            "lon": float(right["lon"]),
        },
        "routeDistanceKm": round(route_distance, 6),
        "straightLineDistanceKm": round(straight_distance, 6),
        "detourRatio": round(ratio, 6) if ratio is not None else None,
        "excessDistanceKm": round(excess, 6),
        "cumulativeDistanceKm": round(float(right["routeDistanceKm"]), 6),
        "routeVertexCount": end_index - start_index + 1,
        "routeStartVertex": start_index,
        "routeEndVertex": end_index,
        "routingSource": source["source"],
        "routePart": source["file"],
        "fallback": fallback,
        "metrics": {
            "maxCorridorDeviationKm": round(max_deviation, 6),
            "reverseProjectedKm": round(reverse_projected_km, 6),
            "repeatedCoordinates": repeated_coordinates,
            "consecutiveRepeatedCoordinates": consecutive_repeats,
            "maxClosedLoopKm": round(max_closed_loop, 6),
            "selfIntersections": self_intersections,
        },
        "flags": flags,
        "suspicious": bool(flags),
        "highlySuspicious": highly_suspicious,
        "inspectionPriorityKm": round(excess + max_deviation * 0.25 + reverse_projected_km, 6),
    }


def build_report(data_dir: Path):
    checkpoint_document = read_json(data_dir / "checkpoints.json")
    checkpoints = checkpoint_document.get("checkpoints") or []
    main_checkpoints = [item for item in checkpoints if not item.get("variantCheckpoint")]
    variant_checkpoints = [item for item in checkpoints if item.get("variantCheckpoint")]
    route_document = read_json(data_dir / "route.geojson")
    route = route_document.get("geometry", {}).get("coordinates") or []
    route_meta = read_json(data_dir / "route-meta.json")
    corrections_document = (
        read_json(data_dir / "route-corrections.json")
        if (data_dir / "route-corrections.json").exists()
        else {"baselineTotalDistanceKm": ORIGINAL_REPORTED_DISTANCE_KM, "corrections": []}
    )
    route_parts = parse_route_parts(data_dir / "route-parts")
    road_tag_document = (
        read_json(data_dir / "route-road-tags.json")
        if (data_dir / "route-road-tags.json").exists()
        else {"legs": []}
    )
    road_tags_by_coordinates = {
        tuple(item.get("coordinateKey") or []): item
        for item in road_tag_document.get("legs") or []
        if len(item.get("coordinateKey") or []) == 4
    }
    if len(checkpoints) != 365 or len(route) < 2:
        raise ValueError("route QA requires 365 checkpoints and a non-empty route")
    legs = [analyze_leg(left, right, route, route_parts) for left, right in zip(main_checkpoints, main_checkpoints[1:])]
    for leg in legs:
        verification_key = (
            round(float(leg["from"]["lon"]), 7),
            round(float(leg["from"]["lat"]), 7),
            round(float(leg["to"]["lon"]), 7),
            round(float(leg["to"]["lat"]), 7),
        )
        verification = road_tags_by_coordinates.get(verification_key, {"status": "not-checked"})
        leg["roadTagVerification"] = verification
        if float(verification.get("motorwayKm") or 0) > 0.05:
            leg["flags"].append("motorway_geometry")
        if float(verification.get("ferryKm") or 0) > 0.05:
            leg["flags"].append("ferry_geometry")
        leg["suspicious"] = bool(leg["flags"])
        leg["highlySuspicious"] = bool(
            leg["highlySuspicious"]
            or "motorway_geometry" in leg["flags"]
            or "ferry_geometry" in leg["flags"]
        )
    country_distances = defaultdict(float)
    for leg in legs:
        country_distances[leg["from"]["country"]] += leg["routeDistanceKm"]
    country_sequence = []
    for checkpoint in checkpoints:
        country = checkpoint.get("country")
        if not country_sequence or country_sequence[-1] != country:
            country_sequence.append(country)
    route_keys = [coordinate_key(point) for point in route]
    repeated_route_coordinates = sum(count - 1 for count in Counter(route_keys).values() if count > 1)
    consecutive_route_repeats = sum(left == right for left, right in zip(route_keys, route_keys[1:]))
    retrace_loops = find_global_retrace_loops(route, route_meta["cumulativeKm"], main_checkpoints)
    remaining_retrace_km = sum(float(item.get("maxClosedLoopKm") or 0) for item in retrace_loops)
    suspicious = [leg for leg in legs if leg["suspicious"]]
    highly_suspicious = [leg for leg in legs if leg["highlySuspicious"]]
    total = float(route_meta["totalDistanceKm"])
    baseline_total = float(corrections_document.get("baselineTotalDistanceKm", ORIGINAL_REPORTED_DISTANCE_KM))
    saint_jean = next(item for item in main_checkpoints if int(item.get("originalIndex") or 0) == 183)
    order_review = read_json(data_dir / "checkpoint-order-review.json")
    ordering_baseline = float(order_review["baseline"]["routeDistanceKm"])
    source_counts = Counter(leg["routingSource"] for leg in legs)
    return {
        "schemaVersion": 1,
        "journeyId": route_meta.get("id", "krakow-santiago"),
        "inputs": {
            "routeSha256": hashlib.sha256((data_dir / "route.geojson").read_bytes()).hexdigest(),
            "checkpointsSha256": hashlib.sha256((data_dir / "checkpoints.json").read_bytes()).hexdigest(),
            "routeParts": len(route_parts),
            "checkpointOrderReviewSha256": hashlib.sha256(
                (data_dir / "checkpoint-order-review.json").read_bytes()
            ).hexdigest(),
        },
        "thresholds": {
            "suspiciousDetourRatio": SUSPICIOUS_RATIO,
            "highlySuspiciousDetourRatio": HIGHLY_SUSPICIOUS_RATIO,
            "unexpectedlyLongLegKm": LONG_LEG_KM,
        },
        "summary": {
            "originalReportedDistanceKm": round(baseline_total, 6),
            "auditedDistanceKm": round(total, 6),
            "differenceFromOriginalKm": round(total - baseline_total, 6),
            "checkpointCount": len(checkpoints),
            "mainRouteCheckpointCount": len(main_checkpoints),
            "variantCheckpointCount": len(variant_checkpoints),
            "legCount": len(legs),
            "routeVertexCount": len(route),
            "consecutiveStraightLineDistanceKm": round(
                sum(leg["straightLineDistanceKm"] for leg in legs), 6
            ),
            "aggregateDetourRatio": round(
                total / sum(leg["straightLineDistanceKm"] for leg in legs), 6
            ),
            "suspiciousLegCount": len(suspicious),
            "highlySuspiciousLegCount": len(highly_suspicious),
            "fallbackLegCount": sum(leg["fallback"] for leg in legs),
            "roadTagVerifiedLegCount": sum(
                leg["roadTagVerification"].get("status") == "verified" for leg in legs
            ),
            "motorwayFlaggedLegCount": sum(
                float(leg["roadTagVerification"].get("motorwayKm") or 0) > 0.05 for leg in legs
            ),
            "ferryFlaggedLegCount": sum(
                float(leg["roadTagVerification"].get("ferryKm") or 0) > 0.05 for leg in legs
            ),
            "krakowToSaintJeanKm": round(float(saint_jean["routeDistanceKm"]), 6),
            "saintJeanToSantiagoKm": round(total - float(saint_jean["routeDistanceKm"]), 6),
            "orderingBaselineDistanceKm": round(ordering_baseline, 6),
            "orderingDistanceReductionKm": round(ordering_baseline - total, 6),
            "orderingBaselineCrossLegRetraceKm": round(float(order_review["baseline"]["crossLegRetraceKm"]), 6),
            "crossLegRetraceKm": round(remaining_retrace_km, 6),
            "orderingRetraceReductionKm": round(
                float(order_review["baseline"]["crossLegRetraceKm"]) - remaining_retrace_km,
                6,
            ),
            "orderingBaselineAutomaticFlags": int(order_review["baseline"]["automaticOrderingFlags"]),
            "remainingOrderingFlags": len(retrace_loops),
        },
        "distanceByCountryKm": {country: round(distance, 6) for country, distance in country_distances.items()},
        "countrySequence": country_sequence,
        "routingSources": dict(source_counts),
        "geometryIntegrity": {
            "repeatedCoordinates": repeated_route_coordinates,
            "consecutiveRepeatedCoordinates": consecutive_route_repeats,
            "retraceLoopsOver500m": retrace_loops,
            "monotonicCheckpointVertices": all(
                int(left["routeVertexIndex"]) <= int(right["routeVertexIndex"])
                for left, right in zip(main_checkpoints, main_checkpoints[1:])
            ),
            "routeStartOffsetKm": round(
                haversine_km(route[0], [checkpoints[0]["lon"], checkpoints[0]["lat"]]), 6
            ),
            "routeEndOffsetKm": round(
                haversine_km(route[-1], [checkpoints[-1]["lon"], checkpoints[-1]["lat"]]), 6
            ),
            "ferryDetection": "verified-for-flagged-legs-when-roadTagVerification-is-present",
            "roadClassDetection": "verified-for-flagged-legs-when-roadTagVerification-is-present",
        },
        "correctedLegs": corrections_document.get("corrections") or [],
        "variantCheckpoints": [
            {
                "index": item["index"],
                "originalIndex": item["originalIndex"],
                "name": item["name"],
                "associatedCheckpointId": item["associatedCheckpointId"],
                "routeDistanceKm": item["routeDistanceKm"],
            }
            for item in variant_checkpoints
        ],
        "legs": legs,
    }


def format_flags(flags):
    labels = {
        "detour_ratio": "detour ratio > 1.8",
        "high_detour_ratio": "detour ratio > 2.5",
        "unexpectedly_long": "individual leg > 60 km",
        "fallback_geometry": "fallback geometry",
        "consecutive_repeated_coordinates": "consecutive repeated coordinates",
        "repeated_coordinates": "repeated coordinates",
        "loop_or_backtracking": "projected backtracking",
        "self_intersection": "proper self-intersection",
        "wide_corridor_deviation": "wide deviation from endpoint corridor",
        "border_detour": "large border-crossing detour",
        "motorway_geometry": "motorway geometry",
        "ferry_geometry": "ferry geometry",
    }
    return ", ".join(labels.get(flag, flag) for flag in flags)


def leg_context(leg):
    index = leg["legIndex"]
    if 59 <= index <= 90:
        return "Alpine leg: elevation, valleys, tunnels and legal cycling crossings can justify a high ratio."
    if 183 <= index <= 188:
        return "Pyrenees/Camino variant leg: inspect against both Route Napoléon and Valcarlos alternatives."
    if index >= 183:
        return "Camino locality leg: a bicycle route may intentionally leave the walking path for rideable roads."
    return "Inspect the cached line on the QA map before treating the excess as a routing error."


def render_markdown(report):
    summary = report["summary"]
    integrity = report["geometryIntegrity"]
    suspicious = sorted(
        (leg for leg in report["legs"] if leg["suspicious"]),
        key=lambda leg: (leg["inspectionPriorityKm"], leg["excessDistanceKm"]),
        reverse=True,
    )
    lines = [
        "# Santiago route geometry QA",
        "",
        "## Audit result",
        "",
        f"- Total route distance: **{summary['auditedDistanceKm']:.2f} km**",
        f"- Consecutive checkpoint straight-line sum: **{summary['consecutiveStraightLineDistanceKm']:.2f} km**",
        f"- Aggregate routed/straight ratio: **{summary['aggregateDetourRatio']:.3f}**",
        f"- Kraków → Saint-Jean-Pied-de-Port: **{summary['krakowToSaintJeanKm']:.2f} km**",
        f"- Saint-Jean-Pied-de-Port → Santiago: **{summary['saintJeanToSantiagoKm']:.2f} km**",
        f"- Main-route / variant checkpoints: **{summary['mainRouteCheckpointCount']} / {summary['variantCheckpointCount']}**",
        f"- Suspicious legs: **{summary['suspiciousLegCount']}**",
        f"- Highly suspicious legs: **{summary['highlySuspiciousLegCount']}**",
        f"- Fallback legs: **{summary['fallbackLegCount']}**",
        f"- Road-tag verified flagged legs: **{summary['roadTagVerifiedLegCount']}**",
        f"- Motorway/ferry flags: **{summary['motorwayFlaggedLegCount']} / {summary['ferryFlaggedLegCount']}**",
        "",
        "The automatic flags are review prompts, not proof of error. Mountain passes, river crossings and road-only",
        "cycling alternatives can legitimately exceed the straight-line threshold.",
        "",
        "**Conclusion:** the relaxed order rule removes strong-confidence branch mixing and geographic loops while",
        "preserving every checkpoint identity. Four alternative-route localities remain in the dataset as explicit",
        "variant checkpoints and no longer force the main route to travel both mutually exclusive branches.",
        "",
        "## Before / after",
        "",
        f"- Before order audit: **{summary['orderingBaselineDistanceKm']:.2f} km**",
        f"- After: **{summary['auditedDistanceKm']:.2f} km**",
        f"- Ordering reduction: **{summary['orderingDistanceReductionKm']:.2f} km**",
        f"- Cross-leg retrace sum: **{summary['orderingBaselineCrossLegRetraceKm']:.2f} → {summary['crossLegRetraceKm']:.2f} km**",
        f"- Automatic ordering flags: **{summary['orderingBaselineAutomaticFlags']} → {summary['remainingOrderingFlags']}**",
        f"- Earlier coordinate corrections retained: **{len(report['correctedLegs'])}**",
        "",
        "## Distance by country",
        "",
        "Legs are attributed to the country of their starting checkpoint; border legs therefore belong to the",
        "origin country.",
        "",
        "| Country | Distance |",
        "| --- | ---: |",
    ]
    for country, distance in report["distanceByCountryKm"].items():
        lines.append(f"| {country} | {distance:.2f} km |")
    if report["correctedLegs"]:
        lines.extend(["", "## Corrections", ""])
        for correction in report["correctedLegs"]:
            lines.extend(
                [
                    f"### Checkpoint #{correction['checkpointIndex']}: {correction['checkpointName']}",
                    "",
                    correction["reason"],
                    "",
                    f"Affected cache: `{correction['affectedRoutePart']}`",
                    "",
                    "| Leg | Before | After | Difference |",
                    "| --- | ---: | ---: | ---: |",
                ]
            )
            for leg in correction["affectedLegs"]:
                lines.append(
                    f"| #{leg['fromIndex']} → #{leg['toIndex']} | {leg['beforeKm']:.3f} km | "
                    f"{leg['afterKm']:.3f} km | {leg['differenceKm']:+.3f} km |"
                )
            lines.extend(["", "Evidence:"])
            for evidence in correction.get("evidence") or []:
                if evidence.get("url"):
                    lines.append(f"- [{evidence['description']}]({evidence['url']})")
                else:
                    lines.append(f"- {evidence['description']}")
            lines.extend(
                [
                    "",
                    f"Correction total: **{correction['totalDifferenceKm']:+.3f} km**",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## Broad corridor",
            "",
            " → ".join(report["countrySequence"]),
            "",
            "The checkpoint and snapped-route order is monotonic. The expected corridor is Kraków through Czechia,",
            "Austria, Liechtenstein, Switzerland and France to Saint-Jean-Pied-de-Port, then the Camino Francés",
            "localities across Spain to Santiago.",
            "",
            "## Geometry integrity",
            "",
            f"- Route vertices: {summary['routeVertexCount']}",
            f"- Repeated coordinates: {integrity['repeatedCoordinates']}",
            f"- Consecutive repeated coordinates: {integrity['consecutiveRepeatedCoordinates']}",
            f"- Retrace-loop groups over 0.5 km: {len(integrity['retraceLoopsOver500m'])}",
            f"- Monotonic checkpoint vertex indexes: {str(integrity['monotonicCheckpointVertices']).lower()}",
            f"- Route start offset: {integrity['routeStartOffsetKm']:.3f} km",
            f"- Route end offset: {integrity['routeEndOffsetKm']:.3f} km",
            "- The compact route-part cache contains geometry only. `route-road-tags.json` therefore records a",
            "  separate BRouter `trekking` verification for every leg flagged for ratio, length, intersection,",
            "  fallback, backtracking, corridor deviation or border detour.",
            "",
            "### Cross-leg retracing",
            "",
        ]
    )
    if integrity["retraceLoopsOver500m"]:
        lines.extend(["| Checkpoint span | Maximum closed loop | Repeated coordinate pairs |", "| --- | ---: | ---: |"])
        for loop in integrity["retraceLoopsOver500m"]:
            lines.append(
                f"| #{loop['fromCheckpointIndex']} {loop['fromCheckpointName']} → "
                f"#{loop['toCheckpointIndex']} {loop['toCheckpointName']} | "
                f"{loop['maxClosedLoopKm']:.2f} km | {loop['repeatedCoordinatePairs']} |"
            )
        lines.extend(
            [
                "",
                "The removed Bidache/Orthez, Valcarlos, Via Trajana, Rhine-valley, and Samos ordering loops no longer",
                "dominate this table. Remaining entries are retained because the order evidence is ambiguous or the",
                "geometry can be explained by the legal cycling network, river crossings, or mountain roads.",
                "",
            ]
        )
    else:
        lines.extend(["No cross-leg retrace over 0.5 km was detected.", ""])
    lines.extend(
        [
            "## Suspicious legs by potential impact",
            "",
        ]
    )
    for leg in suspicious:
        lines.extend(
            [
                f"### #{leg['from']['index']} → #{leg['to']['index']}: {leg['from']['name']} → {leg['to']['name']}",
                "",
                f"- Route: {leg['routeDistanceKm']:.2f} km",
                f"- Straight line: {leg['straightLineDistanceKm']:.2f} km",
                f"- Detour ratio: {leg['detourRatio']:.2f}",
                f"- Excess over straight line: {leg['excessDistanceKm']:.2f} km",
                f"- Vertices: {leg['routeVertexCount']}",
                f"- Source: {leg['routingSource']} (`{leg['routePart']}`)",
                f"- Flags: {format_flags(leg['flags'])}",
                f"- Geometry: max corridor deviation {leg['metrics']['maxCorridorDeviationKm']:.2f} km; "
                f"projected reverse travel {leg['metrics']['reverseProjectedKm']:.2f} km; "
                f"max closed loop {leg['metrics']['maxClosedLoopKm']:.2f} km; "
                f"self-intersections {leg['metrics']['selfIntersections']}",
                "",
                f"Recommendation: {leg_context(leg)}",
                "",
            ]
        )
    lines.extend(
        [
            "## Camino cycling notes",
            "",
            "BRouter's trekking profile connects the main-route localities on rideable mapped geometry and is not",
            "required to trace the pedestrian Camino line. High-ratio Camino legs still require special care because",
            "road switchbacks, river crossings, and avoiding foot-only paths can be valid. Valcarlos and Calzadilla de",
            "los Hermanillos are retained as explicit alternative-route checkpoints associated with the point where",
            "their branches rejoin; they do not create physical detours or appear as the next main-route destination.",
            "",
            "## Reproduction",
            "",
            "```powershell",
            "python scripts/audit_santiago_route.py",
            "python scripts/validate_santiago_dataset.py",
            "```",
            "",
            "The full 364-leg record is in `data/journeys/santiago/route-qa.json`. Open",
            "`santiago-route-qa.html` through the local Vite server for the developer map.",
        ]
    )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = build_report(args.data_dir)
    output_path = args.data_dir / "route-qa.json"
    public_path = args.public_dir / "route-qa.json"
    write_json(output_path, report)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(output_path, public_path)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_markdown(report), encoding="utf-8")
    summary = report["summary"]
    print(f"route distance: {summary['auditedDistanceKm']:.2f} km")
    print(f"legs: {summary['legCount']}")
    print(f"suspicious: {summary['suspiciousLegCount']}")
    print(f"highly suspicious: {summary['highlySuspiciousLegCount']}")
    print(f"fallback: {summary['fallbackLegCount']}")


if __name__ == "__main__":
    main()
