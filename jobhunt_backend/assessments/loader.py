"""Load and validate immutable assessment manifests from the repository."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


class ManifestValidationError(ValueError):
    pass


def canonical_manifest_bytes(value: dict[str, Any]) -> bytes:
    content = {key: item for key, item in value.items() if key != "definitionHash"}
    return json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def definition_hash(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_manifest_bytes(value)).hexdigest()


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestValidationError("manifest must be an object")
    required = {
        "instrumentId", "instrumentVersion", "title", "description", "locale",
        "source", "definitionHash", "scoringVersion", "answerScale", "dimensions",
        "items", "interpretationLimits",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ManifestValidationError(f"missing fields: {', '.join(missing)}")
    for key in ("instrumentId", "instrumentVersion", "title", "description", "locale", "scoringVersion"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ManifestValidationError(f"{key} must be a non-empty string")
    source = value.get("source")
    source_required = {
        "name", "authoritativeReference", "license", "licenseReference",
        "attribution", "requiredNotices",
    }
    if not isinstance(source, dict) or source_required - set(source):
        raise ManifestValidationError("source metadata is incomplete")
    if not isinstance(source.get("requiredNotices"), list):
        raise ManifestValidationError("source.requiredNotices must be an array")
    scale = value.get("answerScale")
    if not isinstance(scale, dict) or not isinstance(scale.get("options"), list):
        raise ManifestValidationError("answerScale.options must be an array")
    minimum = scale.get("min")
    maximum = scale.get("max")
    if not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)) or minimum >= maximum:
        raise ManifestValidationError("answerScale min/max are invalid")
    option_values = [option.get("value") for option in scale["options"] if isinstance(option, dict)]
    if sorted(option_values) != list(range(int(minimum), int(maximum) + 1)):
        raise ManifestValidationError("answerScale options must cover every integer value")
    dimensions = value.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ManifestValidationError("dimensions must be a non-empty array")
    dimension_ids = [item.get("id") for item in dimensions if isinstance(item, dict)]
    if len(dimension_ids) != len(dimensions) or len(set(dimension_ids)) != len(dimension_ids):
        raise ManifestValidationError("dimension IDs must be present and unique")
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise ManifestValidationError("items must be a non-empty array")
    item_ids: set[str] = set()
    orders: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            raise ManifestValidationError("every item must be an object")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in item_ids:
            raise ManifestValidationError("item IDs must be present and unique")
        item_ids.add(item_id)
        if item.get("dimension") not in dimension_ids:
            raise ManifestValidationError(f"item {item_id} has an unknown dimension")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ManifestValidationError(f"item {item_id} has no text")
        if not isinstance(item.get("order"), int):
            raise ManifestValidationError(f"item {item_id} has an invalid order")
        orders.append(item["order"])
        if not isinstance(item.get("reverse", False), bool):
            raise ManifestValidationError(f"item {item_id} has an invalid reverse flag")
    if sorted(orders) != list(range(1, len(items) + 1)):
        raise ManifestValidationError("item order must be consecutive from 1")
    calculated = definition_hash(value)
    if value.get("definitionHash") != calculated:
        raise ManifestValidationError("definitionHash does not match manifest content")
    result = deepcopy(value)
    result["items"].sort(key=lambda item: item["order"])
    return result


class AssessmentManifestLoader:
    def __init__(self, manifests_directory: str | Path | None = None) -> None:
        self.manifests_directory = Path(
            manifests_directory or Path(__file__).parent / "manifests"
        )
        self._manifests: dict[tuple[str, str], dict[str, Any]] | None = None
        self.errors: list[dict[str, str]] = []

    def load(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if self._manifests is not None and not refresh:
            return [deepcopy(item) for item in self._manifests.values()]
        manifests: dict[tuple[str, str], dict[str, Any]] = {}
        self.errors = []
        for path in sorted(self.manifests_directory.rglob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                manifest = validate_manifest(raw)
                key = (manifest["instrumentId"], manifest["instrumentVersion"])
                if key in manifests:
                    raise ManifestValidationError("duplicate instrument/version")
                manifests[key] = manifest
            except (OSError, json.JSONDecodeError, ManifestValidationError) as exc:
                self.errors.append({"path": str(path), "error": str(exc)})
        self._manifests = manifests
        return [deepcopy(item) for item in manifests.values()]

    def get(self, instrument_id: str, version: str | None = None) -> dict[str, Any] | None:
        manifests = self.load()
        candidates = [item for item in manifests if item["instrumentId"] == instrument_id]
        if version is not None:
            candidates = [item for item in candidates if item["instrumentVersion"] == version]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item["instrumentVersion"])
        return deepcopy(candidates[-1])
