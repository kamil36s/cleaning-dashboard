"""Download, build, verify and atomically publish the Phase 7.5B reference DB."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from language_learning.reference_core import resolve_reference_paths
from language_learning.reference_core.artifacts import acquire_sources, require_free_space
from language_learning.reference_core.build import (
    benchmark_reference_database,
    build_staging_database,
    canonical_fingerprint,
    database_storage,
    publish_atomically,
    snapshot_user_database,
    validate_reference_database,
    write_reports,
)
from language_learning.reference_core.manifest import load_manifests, select_manifests


MANIFEST_DIRECTORY = PROJECT_ROOT / "language_learning" / "reference_core" / "manifests"


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _staging_path(database: Path, label: str) -> Path:
    return database.with_name(f".{database.name}.{label}-{uuid.uuid4().hex}.sqlite")


def parse_args() -> argparse.Namespace:
    defaults = resolve_reference_paths(project_root=PROJECT_ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=defaults.source_directory)
    parser.add_argument("--db", type=Path, default=defaults.database)
    parser.add_argument("--main-db", type=Path, default=PROJECT_ROOT / "data" / "language-learning.sqlite")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "data" / "reference" / "reports")
    parser.add_argument("--tier", type=int, choices=(1, 2), default=2)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--allow-unfrozen", action="store_true", help="Acquisition audit only; production builds reject it")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--rebuild-check", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifests = select_manifests(load_manifests(MANIFEST_DIRECTORY), args.tier)
    if args.verify_only:
        validation = validate_reference_database(args.db, expected_sources=len(manifests))
        result = {
            "validation": validation,
            "benchmarks": benchmark_reference_database(args.db),
            "fingerprint": canonical_fingerprint(args.db),
            "storage": database_storage(args.db),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    minimum = 5 * 1024**3 if args.tier == 2 else 3 * 1024**3
    disk = require_free_space((args.source_dir, args.db.parent), minimum_bytes=minimum)
    artifacts = acquire_sources(
        manifests, args.source_dir,
        allow_unfrozen=args.allow_unfrozen,
        progress=_progress,
    )
    acquisition = {
        source_id: [
            {
                "filename": item.path.name,
                "sizeBytes": item.size_bytes,
                "sha256": item.sha256,
                "retrievedAt": item.retrieved_at,
                "httpMetadata": item.http_metadata,
            }
            for item in source_artifacts
        ]
        for source_id, source_artifacts in artifacts.items()
    }
    if args.download_only:
        print(json.dumps({"diskFreeBytes": disk, "artifacts": acquisition}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.allow_unfrozen:
        raise RuntimeError("--allow-unfrozen is permitted only with --download-only")
    if args.db.exists() and not args.force_rebuild:
        raise FileExistsError("production reference DB exists; use --force-rebuild for atomic replacement")

    before = snapshot_user_database(args.main_db)
    if before.get("exists") and before.get("schemaVersion") != 6:
        raise RuntimeError(f"main Language DB must remain at schema v6; observed {before.get('schemaVersion')}")

    first = _staging_path(args.db, "staging")
    first.parent.mkdir(parents=True, exist_ok=True)
    _progress(f"build staging database: {first.name}")
    first_result = build_staging_database(first, manifests=manifests, artifacts=artifacts, progress=_progress)
    rebuild_result = None
    second: Path | None = None
    if args.rebuild_check:
        second = _staging_path(args.db, "rebuild-check")
        _progress(f"build deterministic comparison database: {second.name}")
        second_result = build_staging_database(second, manifests=manifests, artifacts=artifacts, progress=_progress)
        equal = first_result["fingerprint"] == second_result["fingerprint"]
        rebuild_result = {
            "logicalContentEqual": equal,
            "firstFingerprint": first_result["fingerprint"]["sha256"],
            "secondFingerprint": second_result["fingerprint"]["sha256"],
            "secondStorage": second_result["storage"],
        }
        if not equal:
            raise RuntimeError("deterministic rebuild check failed; production DB was not replaced")

    after = snapshot_user_database(args.main_db)
    main_isolation = {
        "before": before,
        "after": after,
        "unchanged": before == after,
    }
    if not main_isolation["unchanged"]:
        raise RuntimeError("main Language DB changed during reference build; production DB was not replaced")

    raw_bytes = sum(item.size_bytes for source in artifacts.values() for item in source)
    storage = dict(first_result["storage"])
    storage.update({
        "rawCompressedBytes": raw_bytes,
        "temporaryExtractionBytes": 0,
        "stagingDatabaseBytes": first.stat().st_size,
        "comparisonDatabaseBytes": second.stat().st_size if second else 0,
        "estimatedMeasuredPeakBytes": raw_bytes + first.stat().st_size + (second.stat().st_size if second else 0),
    })
    if not args.no_publish:
        publish_atomically(first, args.db)
        storage["finalDatabaseBytes"] = args.db.stat().st_size
        published = True
    else:
        storage["finalDatabaseBytes"] = None
        published = False

    if second and second.exists():
        os.unlink(second)

    report_paths = write_reports(
        args.report_dir,
        manifests=manifests,
        artifacts=artifacts,
        quality=first_result["quality"],
        validation=first_result["validation"],
        benchmarks=first_result["benchmarks"],
        storage=storage,
        fingerprint=first_result["fingerprint"],
        main_isolation=main_isolation,
        deterministic_rebuild=rebuild_result,
    )
    result = {
        "phase": "7.5B",
        "published": published,
        "schemaVersion": first_result["validation"]["schemaVersion"],
        "diskFreeBytes": disk,
        "artifacts": acquisition,
        "quality": first_result["quality"],
        "validation": first_result["validation"],
        "benchmarks": first_result["benchmarks"],
        "storage": storage,
        "fingerprint": first_result["fingerprint"],
        "deterministicRebuild": rebuild_result,
        "mainDatabaseIsolation": main_isolation,
        "reports": report_paths,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
