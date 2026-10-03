#!/usr/bin/env python3
"""Import the frozen Phase 9A Tatoeba Bokmal sentence artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.reference_core.config import resolve_reference_paths
from language_learning.reference_core.schema import REFERENCE_SCHEMA_VERSION
from language_learning.reference_core.store import ReferenceStore
from language_learning.reference_core.tatoeba_importer import (
    TatoebaArtifact,
    fast_track_coverage,
    file_sha256,
    import_tatoeba_artifact,
)


MANIFEST_NAMES = ("tatoeba-nob-cc0.json", "tatoeba-nob-cc-by-2-fr.json")


def artifact_from_manifest(manifest_path: Path, source_directory: Path) -> TatoebaArtifact:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    file = payload["expectedFiles"][0]
    path = source_directory / file["name"]
    if not path.is_file():
        raise FileNotFoundError(f"missing frozen artifact: {path}")
    actual_size = path.stat().st_size
    actual_sha = file_sha256(path)
    if actual_size != file["sizeBytes"] or actual_sha != file["sha256"]:
        raise ValueError(f"artifact checksum/size mismatch: {path.name}")
    return TatoebaArtifact(
        source_id=payload["sourceId"],
        title=payload["title"],
        version=payload["version"],
        path=path,
        download_url=file["url"],
        landing_url=payload["landingUrl"],
        license_id=payload["license"]["id"],
        license_url=payload["license"]["url"],
        attribution=payload["attribution"],
        retrieved_at=file["retrievedAt"],
        http_metadata=file.get("httpMetadata") or {},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    paths = resolve_reference_paths(project_root=ROOT)
    database = args.database or paths.database
    source_directory = args.source_directory or paths.source_directory
    report_path = args.report or ROOT / "data" / "reference" / "reports" / "tatoeba-phase9a-import.json"
    store = ReferenceStore(database)
    store.initialize()
    manifests = ROOT / "language_learning" / "reference_core" / "manifests"
    imports = [
        import_tatoeba_artifact(store, artifact_from_manifest(manifests / name, source_directory))
        for name in MANIFEST_NAMES
    ]
    report = {
        "reportVersion": "language.reference-tatoeba-import/v1",
        "referenceSchemaVersion": REFERENCE_SCHEMA_VERSION,
        "imports": imports,
        "coverage": fast_track_coverage(store),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
