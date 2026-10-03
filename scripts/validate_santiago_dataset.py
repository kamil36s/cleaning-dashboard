#!/usr/bin/env python3
"""Validate the generated Kraków–Santiago route and 365 checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "journeys" / "santiago"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    checkpoint_document = read_json(args.data_dir / "checkpoints.json")
    route_meta = read_json(args.data_dir / "route-meta.json")
    route = read_json(args.data_dir / "route.geojson").get("geometry", {}).get("coordinates", [])
    checkpoints = checkpoint_document.get("checkpoints") or []
    source_document = read_json(args.data_dir / "checkpoints-source.json")
    source_checkpoints = source_document.get("checkpoints") or []
    main_checkpoints = [item for item in checkpoints if not item.get("variantCheckpoint")]
    variant_checkpoints = [item for item in checkpoints if item.get("variantCheckpoint")]
    errors = []
    warnings = []

    if len(checkpoints) != 365:
        errors.append(f"checkpoint count is {len(checkpoints)}, expected 365")
    indexes = [item.get("index") for item in checkpoints]
    if indexes != list(range(1, 366)):
        errors.append("indexes are not exactly 1..365")
    original_indexes = [item.get("originalIndex") for item in checkpoints]
    stable_ids = [item.get("id") for item in checkpoints]
    if len(set(original_indexes)) != 365 or set(original_indexes) != set(range(1, 366)):
        errors.append("originalIndex identities are not exactly the unique set 1..365")
    if len(set(stable_ids)) != 365 or any(not value for value in stable_ids):
        errors.append("stable checkpoint IDs are missing or duplicated")
    source_identities = {(item.get("originalIndex") or item.get("index"), item.get("name")) for item in source_checkpoints}
    runtime_identities = {(item.get("originalIndex"), item.get("name")) for item in checkpoints}
    if source_identities != runtime_identities:
        errors.append("runtime checkpoint identities differ from the 365 source identities")
    by_original_index = {item.get("originalIndex"): item for item in checkpoints}
    anchors = ((1, "Kraków"), (183, "St Jean Pied de Port"), (365, "Santiago de Compostela"))
    for original_index, expected in anchors:
        actual = (by_original_index.get(original_index) or {}).get("name")
        if actual != expected:
            errors.append(f"original checkpoint {original_index} is {actual!r}, expected {expected!r}")

    distances = [float(item.get("routeDistanceKm", -1)) for item in checkpoints]
    main_distances = [float(item.get("routeDistanceKm", -1)) for item in main_checkpoints]
    gaps = [right - left for left, right in zip(main_distances, main_distances[1:])]
    if any(gap <= 0 for gap in gaps):
        errors.append("main-route routeDistanceKm values are not strictly increasing")
    if any(right < left for left, right in zip(distances, distances[1:])):
        errors.append("journey routeDistanceKm values decrease")
    main_by_id = {item.get("id"): item for item in main_checkpoints}
    for variant in variant_checkpoints:
        associated = main_by_id.get(variant.get("associatedCheckpointId"))
        if not associated:
            errors.append(f"variant checkpoint {variant.get('name')} has no main-route association")
        elif float(variant.get("routeDistanceKm", -1)) != float(associated.get("routeDistanceKm", -2)):
            errors.append(f"variant checkpoint {variant.get('name')} does not share its association distance")
    total = float(route_meta.get("totalDistanceKm") or 0)
    if not route or len(route) != len(route_meta.get("cumulativeKm") or []):
        errors.append("route geometry and cumulative metadata lengths differ")
    if not distances or abs(distances[-1] - total) > 1:
        errors.append("Santiago routeDistanceKm differs from route total by more than 1 km")

    missing_coordinates = [item["index"] for item in checkpoints if item.get("lat") is None or item.get("lon") is None]
    if missing_coordinates:
        errors.append(f"missing coordinates: {missing_coordinates}")
    far = [(item["index"], item.get("routeOffsetKm")) for item in main_checkpoints if float(item.get("routeOffsetKm") or 0) > 2]
    if far:
        errors.append(f"checkpoints more than 2 km from route: {far}")

    missing_images = [item["index"] for item in checkpoints if not item.get("imageUrl")]
    duplicate_indexes = [value for value, count in Counter(indexes).items() if count > 1]
    duplicate_names = [value for value, count in Counter(item.get("name") for item in checkpoints).items() if count > 1]
    large_gaps = [(index + 1, round(gap, 3)) for index, gap in enumerate(gaps, start=1) if gap > 80]
    tiny_gaps = [(index + 1, round(gap, 3)) for index, gap in enumerate(gaps, start=1) if gap < 0.25]
    qa_path = args.data_dir / "route-qa.json"
    if qa_path.exists():
        qa = read_json(qa_path)
        qa_legs = qa.get("legs") or []
        qa_summary = qa.get("summary") or {}
        if len(qa_legs) != len(main_checkpoints) - 1:
            errors.append(f"route QA leg count is {len(qa_legs)}, expected {len(main_checkpoints) - 1}")
        if abs(float(qa_summary.get("auditedDistanceKm") or 0) - total) > 0.001:
            errors.append("route QA total differs from route metadata")
        if abs(sum(float(leg.get("routeDistanceKm") or 0) for leg in qa_legs) - total) > 0.01:
            errors.append("route QA leg distances do not reconstruct route total")
        if [int(leg.get("legIndex", -1)) for leg in qa_legs] != list(range(1, len(qa_legs) + 1)):
            errors.append("route QA leg indexes are not consecutive main-route pairs")
        route_hash = hashlib.sha256((args.data_dir / "route.geojson").read_bytes()).hexdigest()
        checkpoint_hash = hashlib.sha256((args.data_dir / "checkpoints.json").read_bytes()).hexdigest()
        if qa.get("inputs", {}).get("routeSha256") != route_hash:
            errors.append("route QA route hash is stale")
        if qa.get("inputs", {}).get("checkpointsSha256") != checkpoint_hash:
            errors.append("route QA checkpoint hash is stale")
    if missing_images:
        warnings.append(f"{len(missing_images)} checkpoints have unresolved image metadata")
    if duplicate_names:
        warnings.append(f"duplicate names: {duplicate_names}")
    if duplicate_indexes:
        errors.append(f"duplicate indexes: {duplicate_indexes}")
    if large_gaps:
        warnings.append(f"large route gaps (>80 km): {large_gaps}")
    if tiny_gaps:
        warnings.append(f"tiny route gaps (<0.25 km): {tiny_gaps}")

    print(f"checkpoints: {len(checkpoints)}")
    print(f"main-route checkpoints: {len(main_checkpoints)}")
    print(f"variant checkpoints: {len(variant_checkpoints)}")
    print(f"route vertices: {len(route)}")
    print(f"route distance: {total:.2f} km")
    print(f"missing coordinates: {len(missing_coordinates)}")
    print(f"missing images: {len(missing_images)}")
    print(f"duplicate names: {len(duplicate_names)}")
    print(f"duplicate indexes: {len(duplicate_indexes)}")
    print(f"large gaps: {len(large_gaps)}")
    print(f"tiny gaps: {len(tiny_gaps)}")
    print(f"route QA legs: {len(qa_legs) if qa_path.exists() else 'not generated'}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
