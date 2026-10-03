#!/usr/bin/env python3
"""Import a bank CSV through the canonical finance service.

This command never overwrites ``data/budget.json``. The legacy JSON is backed
up and migrated by FinanceService before an import when necessary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finance_service import FinanceService, FinanceValidationError  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Budget CSV into the canonical local SQLite finance database."
    )
    parser.add_argument("csv_path", type=Path, help="Path to the bank CSV export.")
    parser.add_argument(
        "--database",
        type=Path,
        default=ROOT / "data" / "finance.sqlite",
        help="SQLite database path (default: data/finance.sqlite).",
    )
    parser.add_argument("--source-name", help="Filename recorded in import history.")
    parser.add_argument(
        "--from-date",
        help="Import transactions on or after this date (YYYY-MM-DD or DD.MM.YYYY).",
    )
    parser.add_argument(
        "--to-date",
        help="Import transactions on or before this date (YYYY-MM-DD or DD.MM.YYYY).",
    )
    args = parser.parse_args()

    if not args.csv_path.is_file():
        raise SystemExit(f"CSV file does not exist: {args.csv_path}")
    service = FinanceService(
        args.database,
        legacy_json_path=ROOT / "data" / "budget.json",
        backup_directory=ROOT / "data" / "budget-backups",
    )
    try:
        result = service.import_csv(
            args.csv_path.read_bytes(),
            args.source_name or args.csv_path.name,
            date_from=args.from_date,
            date_to=args.to_date,
        )
    except FinanceValidationError as exc:
        result = exc.result
        raise SystemExit(
            "Import rejected: "
            f"imported={result.get('imported', 0)}, "
            f"duplicates={result.get('duplicates', 0)}, "
            f"invalid={result.get('invalid', 0)}"
        ) from exc

    print(
        "Import complete: "
        f"imported={result['imported']}, "
        f"duplicates={result['duplicates']}, "
        f"invalid={result['invalid']}, "
        f"filtered={result['filteredOut']}, "
        f"batch={result['batchId']}"
    )


if __name__ == "__main__":
    main()
