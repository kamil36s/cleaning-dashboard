#!/usr/bin/env python3
"""Import frozen direct Bokmal-English Tatoeba translations into the reference DB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.reference_core.config import resolve_reference_paths
from language_learning.reference_core.store import ReferenceStore
from language_learning.reference_core.tatoeba_importer import (
    TatoebaTranslationArtifacts,
    file_sha256,
    import_tatoeba_translations,
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
    report_path = args.report or ROOT / "data" / "reference" / "reports" / "tatoeba-translation-import.json"
    manifest_path = ROOT / "language_learning" / "reference_core" / "manifests" / "tatoeba-nob-eng-translations.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["name"]: item for item in manifest["expectedFiles"]}
    for item in files.values():
        path = source_directory / item["name"]
        if not path.is_file() or path.stat().st_size != item["sizeBytes"] or file_sha256(path) != item["sha256"]:
            raise ValueError(f"artifact checksum/size mismatch: {path}")
    artifacts = TatoebaTranslationArtifacts(
        source_id=manifest["sourceId"], title=manifest["title"], version=manifest["version"],
        links_path=source_directory / "nob-eng_links.tsv.bz2",
        english_sentences_path=source_directory / "eng_sentences.tsv.bz2",
        links_url=files["nob-eng_links.tsv.bz2"]["url"],
        english_sentences_url=files["eng_sentences.tsv.bz2"]["url"],
        landing_url=manifest["landingUrl"], license_id=manifest["license"]["id"],
        license_url=manifest["license"]["url"], attribution=manifest["attribution"],
        retrieved_at=max(item["retrievedAt"] for item in files.values()),
        artifacts_metadata={name: item.get("httpMetadata") or {} for name, item in files.items()},
    )
    store = ReferenceStore(database)
    store.initialize()
    report = {
        "reportVersion": "language.reference-tatoeba-translations/v1",
        "referenceSchemaVersion": 3,
        "import": import_tatoeba_translations(store, artifacts),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
