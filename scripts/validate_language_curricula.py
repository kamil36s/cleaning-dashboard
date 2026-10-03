"""Validate tracked curriculum manifests without network access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.curricula import CurriculumService, validate_curriculum_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "language_learning" / "curriculum_packs")
    parser.add_argument("--json", action="store_true", help="Emit one JSON report instead of readable lines")
    args = parser.parse_args()
    reports = []
    failed = False
    for path in sorted(args.directory.glob("*.json")):
        if path.name in {"manifest.schema.json", "catalog.json"}:
            continue
        try:
            manifest = validate_curriculum_manifest(json.loads(path.read_text(encoding="utf-8")))
            pack = manifest["pack"]
            counts = pack["denominatorCounts"]
            reports.append({
                "file": path.name, "packId": pack["id"], "version": pack["version"],
                "status": pack["status"], "fingerprint": pack["fingerprint"],
                "sourceId": manifest["source"]["id"], "sourceVersion": manifest["source"]["version"],
                **counts,
            })
        except Exception as exc:  # CLI reports every malformed manifest in one pass.
            failed = True
            reports.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
    try:
        CurriculumService(None, manifest_directory=args.directory).active_packs()
    except Exception as exc:
        failed = True
        reports.append({"file": "catalog.json", "error": f"{type(exc).__name__}: {exc}"})
    if args.json:
        print(json.dumps({"ok": not failed, "packs": reports}, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            if "error" in report:
                print(f"FAIL {report['file']}: {report['error']}")
            else:
                print(
                    f"OK {report['packId']} v{report['version']} {report['status']} "
                    f"source={report['sourceItemTotal']} approved={report['approvedTotal']} "
                    f"mapped={report['mappedTotal']} ambiguous={report['ambiguousTotal']} "
                    f"unresolved={report['unresolvedTotal']} excluded={report['excludedTotal']} "
                    f"eligible={report['eligibleDenominator']} {report['fingerprint']}"
                )
    return 1 if failed or not reports else 0


if __name__ == "__main__":
    raise SystemExit(main())
