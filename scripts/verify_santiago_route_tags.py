#!/usr/bin/env python3
"""Verify road/ferry tags for flagged Santiago legs with BRouter."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "journeys" / "santiago"
USER_AGENT = "cleaning-dashboard-santiago-route-qa/1.0 (local personal dashboard)"
REVIEW_FLAGS = {
    "detour_ratio",
    "high_detour_ratio",
    "unexpectedly_long",
    "fallback_geometry",
    "loop_or_backtracking",
    "self_intersection",
    "wide_corridor_deviation",
    "border_detour",
}
ROUGH_SURFACES = {"mud", "sand", "ground", "dirt", "unpaved"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_route(left, right, retries=3):
    lonlats = "|".join(
        (
            f"{float(left['lon']):.7f},{float(left['lat']):.7f}",
            f"{float(right['lon']):.7f},{float(right['lat']):.7f}",
        )
    )
    query = urllib.parse.urlencode(
        {
            "lonlats": lonlats,
            "profile": "trekking",
            "alternativeidx": "0",
            "format": "geojson",
        },
        safe="|,",
    )
    request = urllib.request.Request(
        f"https://brouter.de/brouter?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # network/build-time tool; preserve the final failure in output
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(str(last_error))


def meters_for(rows, predicate):
    total = 0.0
    count = 0
    for row in rows:
        if len(row) < 10 or not predicate(str(row[9])):
            continue
        count += 1
        try:
            total += float(row[3])
        except (TypeError, ValueError):
            pass
    return count, total


def summarize_feature(feature, leg):
    properties = feature.get("properties") or {}
    rows = list(properties.get("messages") or [])[1:]

    def tokens(tags):
        return set(tags.split())

    motorway_count, motorway_meters = meters_for(
        rows,
        lambda tags: "highway=motorway" in tokens(tags) or "highway=motorway_link" in tokens(tags),
    )
    ferry_count, ferry_meters = meters_for(
        rows,
        lambda tags: "route=ferry" in tokens(tags) or any(token.startswith("ferry=") for token in tokens(tags)),
    )
    bicycle_no_count, bicycle_no_meters = meters_for(rows, lambda tags: "bicycle=no" in tokens(tags))
    rough_count, rough_meters = meters_for(
        rows,
        lambda tags: any(f"surface={surface}" in tokens(tags) for surface in ROUGH_SURFACES),
    )
    return {
        "legIndex": leg["legIndex"],
        "fromIndex": leg["from"]["index"],
        "toIndex": leg["to"]["index"],
        "coordinateKey": [
            round(float(leg["from"]["lon"]), 7),
            round(float(leg["from"]["lat"]), 7),
            round(float(leg["to"]["lon"]), 7),
            round(float(leg["to"]["lat"]), 7),
        ],
        "status": "verified",
        "backend": properties.get("creator", "BRouter"),
        "profile": "trekking",
        "routeDistanceKm": round(float(properties.get("track-length") or 0) / 1000, 6),
        "motorwaySegments": motorway_count,
        "motorwayKm": round(motorway_meters / 1000, 6),
        "ferrySegments": ferry_count,
        "ferryKm": round(ferry_meters / 1000, 6),
        "bicycleNoSegments": bicycle_no_count,
        "bicycleNoKm": round(bicycle_no_meters / 1000, 6),
        "roughSurfaceSegments": rough_count,
        "roughSurfaceKm": round(rough_meters / 1000, 6),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--delay", type=float, default=1.05)
    args = parser.parse_args()
    qa_path = args.data_dir / "route-qa.json"
    qa = read_json(qa_path)
    output_path = args.data_dir / "route-road-tags.json"
    existing_document = read_json(output_path) if output_path.exists() else {"legs": []}
    existing = {
        tuple(item.get("coordinateKey") or []): item
        for item in existing_document.get("legs") or []
        if len(item.get("coordinateKey") or []) == 4
    }
    selected = [leg for leg in qa["legs"] if REVIEW_FLAGS.intersection(leg["flags"])]
    results = []
    for position, leg in enumerate(selected, start=1):
        coordinate_key = [
            round(float(leg["from"]["lon"]), 7),
            round(float(leg["from"]["lat"]), 7),
            round(float(leg["to"]["lon"]), 7),
            round(float(leg["to"]["lat"]), 7),
        ]
        cached = existing.get(tuple(coordinate_key))
        if cached and cached.get("coordinateKey") == coordinate_key and cached.get("status") == "verified":
            result = cached
        else:
            try:
                payload = request_route(leg["from"], leg["to"])
                feature = (payload.get("features") or [None])[0]
                if not feature:
                    raise RuntimeError("BRouter returned no feature")
                result = summarize_feature(feature, leg)
            except Exception as error:
                result = {
                    "legIndex": leg["legIndex"],
                    "fromIndex": leg["from"]["index"],
                    "toIndex": leg["to"]["index"],
                    "coordinateKey": coordinate_key,
                    "status": "error",
                    "error": str(error),
                }
            write_json(output_path, {"schemaVersion": 1, "reviewedLegCount": len(results) + 1, "legs": results + [result]})
            time.sleep(max(0.0, args.delay))
        results.append(result)
        print(f"road tags: {position}/{len(selected)} - leg {leg['legIndex']}", flush=True)
    write_json(output_path, {"schemaVersion": 1, "reviewedLegCount": len(results), "legs": results})
    errors = sum(item.get("status") != "verified" for item in results)
    motorway = sum(float(item.get("motorwayKm") or 0) for item in results)
    ferry = sum(float(item.get("ferryKm") or 0) for item in results)
    print(f"verified legs: {len(results) - errors}/{len(results)}")
    print(f"motorway distance: {motorway:.3f} km")
    print(f"ferry distance: {ferry:.3f} km")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
