"""Create, validate, preview, and clean-restore a Language recovery package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.backup import (  # noqa: E402
    BackupError, create_backup, preview_restore, restore_backup, validate_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--reference-db", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--db", type=Path)
    backup.add_argument("--output", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("package", type=Path)
    preview = commands.add_parser("preview")
    preview.add_argument("package", type=Path)
    preview.add_argument("target", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("package", type=Path)
    restore.add_argument("target", type=Path)
    args = parser.parse_args()
    root = args.project_root
    try:
        if args.command == "backup":
            package = create_backup(args.db or root / "data/language-learning.sqlite",
                                    args.output or root / "data/backups", project_root=root,
                                    reference_db=args.reference_db)
            result = {"status": "CREATED", "package": str(package)}
        elif args.command == "validate":
            result = validate_backup(args.package, project_root=root, reference_db=args.reference_db)
        elif args.command == "preview":
            result = preview_restore(args.package, args.target, project_root=root,
                                     reference_db=args.reference_db)
        else:
            result = restore_backup(args.package, args.target, project_root=root,
                                    reference_db=args.reference_db)
    except (BackupError, OSError) as exc:
        result = {"status": "INVALID", "errors": [str(exc)]}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["status"] == "INVALID" else 0


if __name__ == "__main__":
    raise SystemExit(main())
