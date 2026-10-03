"""Inspect or initialize the isolated Language reference database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from language_learning.reference_core import ReferenceStore, resolve_reference_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true", help="Create/upgrade reference schema v1")
    parser.add_argument("--verbose", action="store_true", help="Include configured local paths")
    args = parser.parse_args()
    paths = resolve_reference_paths()
    result = {
        "configured": True,
        "databaseExists": paths.database.exists(),
        "sourceDirectoryExists": paths.source_directory.exists(),
        "initialized": False,
    }
    if args.initialize:
        store = ReferenceStore(paths.database)
        store.initialize()
        result.update(store.health())
        result["initialized"] = True
        result["databaseExists"] = True
    if paths.database.exists():
        try:
            uri = paths.database.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if "reference_schema_migrations" in tables:
                    result["schemaVersion"] = int(connection.execute(
                        "SELECT COALESCE(MAX(version),0) FROM reference_schema_migrations"
                    ).fetchone()[0])
                    result["integrityCheck"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    result["foreignKeyViolations"] = len(connection.execute("PRAGMA foreign_key_check").fetchall())
                    result["sources"] = [
                        {
                            "sourceId": row[0], "version": row[1], "license": row[2],
                            "checksumPrefix": row[3][:19] if row[3] else None,
                            "importStatus": row[4],
                        }
                        for row in connection.execute(
                            "SELECT s.source_id,s.version,s.license_id,r.source_checksum,r.status "
                            "FROM reference_sources s LEFT JOIN reference_import_runs r ON r.source_id=s.source_id "
                            "ORDER BY s.source_id"
                        )
                    ]
                    count_tables = (
                        "reference_lexical_units", "reference_forms", "reference_form_links",
                        "reference_raw_observations", "reference_frequency_observations",
                        "reference_expression_variants", "reference_cefr_evidence",
                        "reference_domain_evidence", "reference_association_evidence",
                    )
                    result["rowCounts"] = {
                        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                        for table in count_tables if table in tables
                    }
                    result["cefrSourceAvailable"] = result["rowCounts"].get("reference_cefr_evidence", 0) > 0
                    result["tier3Ingested"] = result["rowCounts"].get("reference_association_evidence", 0) > 0
        except sqlite3.Error as exc:
            result["databaseError"] = str(exc)
    if args.verbose:
        result["databasePath"] = str(paths.database)
        result["sourceDirectoryPath"] = str(paths.source_directory)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
