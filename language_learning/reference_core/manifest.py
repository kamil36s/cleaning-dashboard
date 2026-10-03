"""Strict source-manifest loading for the Phase 7.5B reference build."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .store import canonical_json


MANIFEST_VERSION = "language-reference-source-manifest/v1"
ACCEPTED_LICENSES = {
    "nb-norsk-ordbank-nob-2022-02-01": "CC-BY-4.0",
    "uio-norwegian-kelly-shu-wang": "CC-BY-SA-4.0",
    "clarino-norsk-aviskorpus-nob-frequency-2025-08-25": "CC-BY-3.0",
    "nb-norwegian-idioms-2024-10-10": "CC0-1.0",
    "nb-bokmal-ngram-2012": "CC0-1.0",
}


@dataclass(frozen=True)
class ArtifactManifest:
    name: str
    url: str
    size_bytes: int | None
    sha256: str | None
    format: str
    required: bool
    retrieved_at: str | None
    http_metadata: dict[str, str]

    @property
    def checksum(self) -> str | None:
        return f"sha256:{self.sha256.lower()}" if self.sha256 else None


@dataclass(frozen=True)
class SourceManifest:
    path: Path
    payload: dict[str, Any]
    artifacts: tuple[ArtifactManifest, ...]

    @property
    def source_id(self) -> str:
        return str(self.payload["sourceId"])

    @property
    def parser_id(self) -> str:
        return str(self.payload["parser"]["id"])

    @property
    def parser_version(self) -> str:
        return str(self.payload["parser"]["version"])

    @property
    def priority(self) -> str:
        return str(self.payload["priority"])

    @property
    def required_artifacts(self) -> tuple[ArtifactManifest, ...]:
        return tuple(item for item in self.artifacts if item.required)

    def source_checksum(self) -> str:
        frozen = [
            {"name": item.name, "sizeBytes": item.size_bytes, "sha256": item.sha256}
            for item in sorted(self.required_artifacts, key=lambda item: item.name)
        ]
        if any(not item["sha256"] or item["sizeBytes"] is None for item in frozen):
            raise ValueError(f"manifest {self.source_id} has unfrozen required artifacts")
        return "sha256:" + hashlib.sha256(canonical_json(frozen).encode("utf-8")).hexdigest()


def _artifact(item: dict[str, Any], *, source_id: str) -> ArtifactManifest:
    required = {"name", "url", "sizeBytes", "sha256", "format", "required"}
    missing = sorted(required - set(item))
    if missing:
        raise ValueError(f"manifest {source_id} artifact is missing {missing}")
    checksum = item.get("sha256")
    if checksum is not None:
        checksum = str(checksum).lower()
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise ValueError(f"manifest {source_id} has invalid SHA-256 for {item['name']}")
    size = item.get("sizeBytes")
    if size is not None and (not isinstance(size, int) or size < 0):
        raise ValueError(f"manifest {source_id} has invalid size for {item['name']}")
    return ArtifactManifest(
        name=str(item["name"]),
        url=str(item["url"]),
        size_bytes=size,
        sha256=checksum,
        format=str(item["format"]),
        required=bool(item["required"]),
        retrieved_at=item.get("retrievedAt"),
        http_metadata={str(key): str(value) for key, value in (item.get("httpMetadata") or {}).items()},
    )


def load_manifests(directory: str | Path) -> tuple[SourceManifest, ...]:
    root = Path(directory)
    manifests: list[SourceManifest] = []
    source_ids: set[str] = set()
    for path in sorted(root.glob("*.json")):
        if path.name == "manifest.schema.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("manifestVersion") != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest version in {path.name}")
        source_id = str(payload.get("sourceId") or "")
        if not source_id or source_id in source_ids:
            raise ValueError(f"missing or duplicate source identity: {source_id!r}")
        source_ids.add(source_id)
        if payload.get("decision") != "ACCEPT_PHASE_7_5B":
            continue
        expected_license = ACCEPTED_LICENSES.get(source_id)
        if expected_license is None or payload.get("license", {}).get("id") != expected_license:
            raise ValueError(f"license snapshot mismatch for {source_id}")
        artifacts = tuple(_artifact(item, source_id=source_id) for item in payload.get("expectedFiles", []))
        if not artifacts or not any(item.required for item in artifacts):
            raise ValueError(f"manifest {source_id} has no required artifacts")
        manifests.append(SourceManifest(path=path, payload=payload, artifacts=artifacts))
    expected = set(ACCEPTED_LICENSES)
    actual = {item.source_id for item in manifests}
    if actual != expected:
        raise ValueError(f"accepted manifest set mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    return tuple(manifests)


def select_manifests(manifests: Iterable[SourceManifest], tier: int) -> tuple[SourceManifest, ...]:
    if tier not in {1, 2}:
        raise ValueError("Phase 7.5B supports Tier 1 or Tier 1+2 only")
    allowed = {"TIER_1"} | ({"TIER_2"} if tier == 2 else set())
    return tuple(item for item in manifests if item.priority in allowed)


__all__ = [
    "ACCEPTED_LICENSES",
    "ArtifactManifest",
    "MANIFEST_VERSION",
    "SourceManifest",
    "load_manifests",
    "select_manifests",
]
