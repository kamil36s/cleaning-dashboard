import argparse
from pathlib import Path

from .builder import IndexErrorClosed, build, validate
from .coverage import coverage_check


def main():
    parser = argparse.ArgumentParser(description="Build or validate the derived Kermit L2 index")
    parser.add_argument("command", choices=("build", "validate", "coverage-check"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = args.manifest or root / "kermit_index" / "admission.json"
    output = args.output or root / "data" / "generated" / "kermit-index"
    try:
        if args.command == "coverage-check":
            import json
            report = coverage_check(root, manifest, output)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
            if report["findings"]:
                parser.exit(1)
            return
        report = (build if args.command == "build" else validate)(root, manifest, output)
    except (IndexErrorClosed, OSError, ValueError) as exc:
        parser.exit(1, f"Kermit index {args.command} failed: {exc}\n")
    print(report)


if __name__ == "__main__":
    main()
