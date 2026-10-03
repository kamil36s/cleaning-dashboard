#!/usr/bin/env python3
"""Build the reviewable Santiago checkpoint-order proposal from existing QA data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "journeys" / "santiago"
DEFAULT_REPORT = ROOT / "docs" / "santiago-checkpoint-order-review.md"

ORDER_GROUPS = (
    {
        "id": "alpine-rhine-valley",
        "originalIndexes": [98, 99, 100, 101],
        "optimizedOriginalIndexes": [98, 101, 100, 99],
        "estimatedDistanceSavedKm": 23.939377,
        "reason": (
            "The existing Balzers → Sargans → Bad Ragaz → Maienfeld order crosses the Rhine valley twice. "
            "Balzers → Maienfeld → Bad Ragaz → Sargans continues toward Flums without the detected closed loop."
        ),
    },
    {
        "id": "lower-navarre-alternative",
        "originalIndexes": [179, 180, 181],
        "optimizedOriginalIndexes": [181, 179, 180],
        "estimatedDistanceSavedKm": 54.585051,
        "reason": (
            "Orthez and Sauveterre form the eastern approach to Saint-Palais, while the active journey arrives "
            "through Peyrehorade and Bidache. Keeping both approaches in the physical line causes the 46.86 km "
            "Bidache retrace plus the following 7.73 km repeated corridor."
        ),
    },
    {
        "id": "pyrenees-alternative",
        "originalIndexes": [186, 187, 188],
        "optimizedOriginalIndexes": [187, 188, 186],
        "estimatedDistanceSavedKm": 7.374489,
        "reason": (
            "Valcarlos is the valley alternative to the Hontto → Orisson → Lepoeder Route Napoléon. "
            "It is associated with Roncesvalles, where both approaches rejoin, instead of forcing both branches."
        ),
    },
    {
        "id": "meseta-alternative",
        "originalIndexes": [268, 269],
        "optimizedOriginalIndexes": [269, 268],
        "estimatedDistanceSavedKm": 11.631898,
        "reason": (
            "Calzadilla de los Hermanillos belongs to the Via Trajana alternative after Calzada del Coto; "
            "Bercianos del Real Camino belongs to the main Camino branch. It remains a milestone associated "
            "with the nearby main-route position at El Burgo Ranero."
        ),
    },
    {
        "id": "samos-local-order",
        "originalIndexes": [320, 321],
        "optimizedOriginalIndexes": [321, 320],
        "estimatedDistanceSavedKm": 14.671023,
        "reason": (
            "From Triacastela the coordinates place A Balsa before San Cristovo do Real on the selected Samos "
            "branch. Their previous order creates the detected north/south return before continuing to Samos."
        ),
    },
)

VARIANTS = {
    179: {
        "associatedOriginalIndex": 181,
        "reason": "Eastern Orthez/Sauveterre approach; associated where it rejoins at Saint-Palais.",
    },
    180: {
        "associatedOriginalIndex": 181,
        "reason": "Eastern Orthez/Sauveterre approach; associated where it rejoins at Saint-Palais.",
    },
    186: {
        "associatedOriginalIndex": 188,
        "reason": "Valcarlos approach; associated where it rejoins the Route Napoléon at Roncesvalles.",
    },
    268: {
        "associatedOriginalIndex": 269,
        "reason": "Via Trajana branch; associated with the nearby main Camino position at El Burgo Ranero.",
    },
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_id(original_index: int) -> str:
    return f"santiago-{original_index:03d}"


def apply_order_groups(original_indexes):
    result = list(original_indexes)
    for group in ORDER_GROUPS:
        positions = [result.index(value) for value in group["originalIndexes"]]
        if positions != list(range(min(positions), max(positions) + 1)):
            raise ValueError(f"Order group {group['id']} is not contiguous")
        start = min(positions)
        result[start:start + len(positions)] = group["optimizedOriginalIndexes"]
    return result


def neighbor_names(order, position, by_original_index):
    return {
        "previous": by_original_index[order[position - 1]]["name"] if position > 0 else None,
        "next": by_original_index[order[position + 1]]["name"] if position + 1 < len(order) else None,
    }


def build_review(data_dir: Path):
    source_path = data_dir / "checkpoints-source.json"
    existing_review_path = data_dir / "checkpoint-order-review.json"
    existing_review = read_json(existing_review_path) if existing_review_path.exists() else None
    source_document = read_json(source_path)
    checkpoints = source_document.get("checkpoints") or source_document
    qa = read_json(data_dir / "route-qa.json")
    if len(checkpoints) != 365:
        raise ValueError("Checkpoint order review requires exactly 365 source identities")
    by_original_index = {int(item["index"]): item for item in checkpoints}
    original_order = list(range(1, 366))
    runtime_order = apply_order_groups(original_order)
    group_by_original_index = {
        original_index: group
        for group in ORDER_GROUPS
        for original_index in group["originalIndexes"]
    }
    changes = []
    for original_index in sorted(group_by_original_index):
        old_position = original_order.index(original_index)
        new_position = runtime_order.index(original_index)
        old_neighbors = neighbor_names(original_order, old_position, by_original_index)
        new_neighbors = neighbor_names(runtime_order, new_position, by_original_index)
        if old_position == new_position and old_neighbors == new_neighbors:
            continue
        group = group_by_original_index[original_index]
        representative = group["optimizedOriginalIndexes"][0]
        changes.append({
            "checkpointId": stable_id(original_index),
            "checkpoint": by_original_index[original_index]["name"],
            "originalIndex": original_index,
            "oldJourneyIndex": old_position + 1,
            "newJourneyIndex": new_position + 1,
            "oldNeighbors": old_neighbors,
            "newNeighbors": new_neighbors,
            "reason": group["reason"],
            "estimatedDistanceSavedKm": group["estimatedDistanceSavedKm"] if original_index == representative else 0,
            "changeGroup": group["id"],
        })

    variants = []
    for original_index, variant in VARIANTS.items():
        associated = int(variant["associatedOriginalIndex"])
        variants.append({
            "checkpointId": stable_id(original_index),
            "checkpoint": by_original_index[original_index]["name"],
            "originalIndex": original_index,
            "variantCheckpoint": True,
            "associatedCheckpointId": stable_id(associated),
            "associatedCheckpoint": by_original_index[associated]["name"],
            "associatedOriginalIndex": associated,
            "reason": variant["reason"],
        })

    loops = qa.get("geometryIntegrity", {}).get("retraceLoopsOver500m") or []
    if existing_review:
        preserved_flags = existing_review.get("manualReview", {}).get("allBaselineRetraceFlags") or []
        if preserved_flags:
            loops = preserved_flags
    accepted_indexes = {
        original_index
        for group in ORDER_GROUPS
        for original_index in group["originalIndexes"]
    }
    retrace_review = []
    for loop in loops:
        start = int(loop["fromCheckpointIndex"])
        end = int(loop["toCheckpointIndex"])
        accepted = any(start <= index <= end for index in accepted_indexes)
        retrace_review.append({
            **loop,
            "decision": "accepted-order-correction" if accepted else "unchanged-manual-review",
            "reason": (
                "Covered by an accepted strong-confidence order/variant correction."
                if accepted
                else "No strong checkpoint-order evidence; retain until a route-specific manual review proves otherwise."
            ),
        })

    summary = qa["summary"]
    baseline_retrace = sum(float(item.get("maxClosedLoopKm") or 0) for item in loops)
    existing_baseline = (existing_review or {}).get("baseline") or {}
    review = {
        "schemaVersion": 1,
        "status": "accepted-for-runtime-rebuild",
        "sourceCheckpointSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "baseline": {
            "routeDistanceKm": existing_baseline.get("routeDistanceKm", summary["auditedDistanceKm"]),
            "crossLegRetraceKm": existing_baseline.get("crossLegRetraceKm", round(baseline_retrace, 6)),
            "automaticOrderingFlags": existing_baseline.get("automaticOrderingFlags", len(loops)),
        },
        "identity": {
            "checkpointCount": 365,
            "stableIdFormat": "santiago-{originalIndex:03d}",
            "originalOrderField": "originalIndex",
            "runtimeOrderField": "index",
        },
        "runtimeOrderOriginalIndexes": runtime_order,
        "changes": changes,
        "variantCheckpoints": variants,
        "manualReview": {
            "ambiguousKnownArea": {
                "checkpoints": ["Krems an der Donau", "Herzogenburg", "Sankt Pölten"],
                "decision": "unchanged",
                "reason": (
                    "Krems is a genuine Danube milestone and Herzogenburg lies on the southbound transition. "
                    "The 25.44 km retrace is real, but none of the alternative orders is clearly more coherent."
                ),
            },
            "allBaselineRetraceFlags": retrace_review,
        },
    }
    current_distance = float(summary["auditedDistanceKm"])
    baseline_distance = float(review["baseline"]["routeDistanceKm"])
    if abs(current_distance - baseline_distance) > 0.001:
        review["result"] = {
            "routeDistanceKm": current_distance,
            "distanceReductionKm": round(baseline_distance - current_distance, 6),
            "crossLegRetraceKm": summary.get("crossLegRetraceKm"),
            "crossLegRetraceReductionKm": summary.get("orderingRetraceReductionKm"),
            "remainingOrderingFlags": summary.get("remainingOrderingFlags"),
        }
    return review


def render_markdown(review):
    baseline = review["baseline"]
    lines = [
        "# Santiago checkpoint order review",
        "",
        "## Decision",
        "",
        "The source identity set remains exactly 365 checkpoints. `originalIndex` preserves the supplied order;",
        "runtime `index` is the optimized journey order. Only strong-confidence geographic corrections are accepted.",
        "",
        "## Baseline",
        "",
        f"- Route distance: **{baseline['routeDistanceKm']:.2f} km**",
        f"- Sum of detected cross-leg closed loops over 0.5 km: **{baseline['crossLegRetraceKm']:.2f} km**",
        f"- Automatic retrace/order flags: **{baseline['automaticOrderingFlags']}**",
    ]
    if review.get("result"):
        result = review["result"]
        lines.extend([
            "",
            "## Applied result",
            "",
            f"- Route distance: **{result['routeDistanceKm']:.2f} km**",
            f"- Distance reduction: **{result['distanceReductionKm']:.2f} km**",
            f"- Cross-leg retrace sum: **{result['crossLegRetraceKm']:.2f} km**",
            f"- Cross-leg retrace reduction: **{result['crossLegRetraceReductionKm']:.2f} km**",
            f"- Remaining automatic ordering flags: **{result['remainingOrderingFlags']}**",
        ])
    lines.extend([
        "",
        "## Accepted order changes",
        "",
        "| Checkpoint | Original | Old neighbors | New neighbors | Estimated saving | Reason |",
        "| --- | ---: | --- | --- | ---: | --- |",
    ])
    for change in review["changes"]:
        old = f"{change['oldNeighbors']['previous']} → {change['oldNeighbors']['next']}"
        new = f"{change['newNeighbors']['previous']} → {change['newNeighbors']['next']}"
        lines.append(
            f"| {change['checkpoint']} | {change['originalIndex']} | {old} | {new} | "
            f"{change['estimatedDistanceSavedKm']:.2f} km | {change['reason']} |"
        )
    lines.extend(["", "## Variant checkpoints", ""])
    for variant in review["variantCheckpoints"]:
        lines.append(
            f"- **{variant['checkpoint']}** (original #{variant['originalIndex']}) → associated with "
            f"**{variant['associatedCheckpoint']}**: {variant['reason']}"
        )
    ambiguous = review["manualReview"]["ambiguousKnownArea"]
    lines.extend([
        "",
        "## Manual review retained",
        "",
        f"- **{' / '.join(ambiguous['checkpoints'])}:** {ambiguous['reason']}",
        "- Every baseline cross-leg retrace remains listed with an explicit decision in",
        "  `data/journeys/santiago/checkpoint-order-review.json`.",
        "",
        "## Persistence",
        "",
        "Committed journey progress remains a kilometre value. Rebuilding the route does not rewrite or reset",
        "`committed_distance_km`; only percentage, interpolated position, and future checkpoint timing can change.",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    review = build_review(args.data_dir)
    write_json(args.data_dir / "checkpoint-order-review.json", review)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_markdown(review), encoding="utf-8")
    print(f"Reviewed 365 checkpoints; proposed {len(review['changes'])} documented order changes and "
          f"{len(review['variantCheckpoints'])} variants.")


if __name__ == "__main__":
    main()
