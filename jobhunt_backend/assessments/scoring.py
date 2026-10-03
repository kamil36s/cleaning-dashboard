"""Explainable deterministic scoring for manifest-backed assessments."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .loader import ManifestValidationError, validate_manifest


def score_assessment(
    manifest: dict[str, Any], responses: dict[str, Any]
) -> list[dict[str, Any]]:
    definition = validate_manifest(manifest)
    scale = definition["answerScale"]
    minimum = float(scale["min"])
    maximum = float(scale["max"])
    item_ids = {item["id"] for item in definition["items"]}
    missing = [item["id"] for item in definition["items"] if item["id"] not in responses]
    if missing:
        raise ManifestValidationError("missing required responses: " + ", ".join(missing))
    unexpected = sorted(set(responses) - item_ids)
    if unexpected:
        raise ManifestValidationError("unknown response items: " + ", ".join(unexpected))
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in definition["items"]:
        answer = responses[item["id"]]
        if isinstance(answer, bool) or not isinstance(answer, (int, float)):
            raise ManifestValidationError(f"response {item['id']} must be numeric")
        answer = float(answer)
        if answer < minimum or answer > maximum or answer != int(answer):
            raise ManifestValidationError(f"response {item['id']} is outside the answer scale")
        scored = minimum + maximum - answer if item.get("reverse", False) else answer
        grouped[item["dimension"]].append(scored)
    results = []
    for dimension in definition["dimensions"]:
        values = grouped[dimension["id"]]
        raw_score = sum(values)
        raw_minimum = len(values) * minimum
        raw_maximum = len(values) * maximum
        normalized = (
            ((raw_score - raw_minimum) / (raw_maximum - raw_minimum)) * 100
            if raw_maximum > raw_minimum else None
        )
        results.append({
            "dimension": dimension["id"],
            "label": dimension["label"],
            "rawScore": round(raw_score, 6),
            "normalizedScore": round(normalized, 6) if normalized is not None else None,
            "interpretationBand": None,
            "scoringVersion": definition["scoringVersion"],
        })
    return results
