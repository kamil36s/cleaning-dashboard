"""Staged validation, benchmarking, reporting and publication for Phase 7.5B."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import time
from typing import Any, Iterable

from .artifacts import VerifiedArtifact
from .manifest import SourceManifest
from .production_importer import ProductionImporter
from .schema import REFERENCE_SCHEMA_VERSION
from .store import ReferenceStore, canonical_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _connect(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=30)
    else:
        connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def snapshot_user_database(path: str | Path) -> dict[str, Any]:
    database = Path(path)
    if not database.exists():
        return {"exists": False}
    with _connect(database, readonly=True) as connection:
        tables = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in tables}
        ledger_table = next(
            (name for name in ("language_schema_migrations", "schema_migrations") if name in tables),
            None,
        )
        version = int(connection.execute(
            f'SELECT COALESCE(MAX(version),0) FROM "{ledger_table}"'
        ).fetchone()[0]) if ledger_table else 0
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    return {
        "exists": True,
        "schemaVersion": version,
        "tableCount": len(tables),
        "rowCounts": counts,
        "integrityCheck": integrity,
        "foreignKeyViolations": foreign_keys,
    }


def _canonical_row_hash(connection: sqlite3.Connection, query: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(query):
        digest.update(canonical_json(list(row)).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


CANONICAL_QUERIES = {
    "schema": "SELECT version,checksum FROM reference_schema_migrations ORDER BY version",
    "sources": "SELECT source_id,canonical_name,provider,resource_type,language_code,version,release_date,"
               "landing_url,license_id,license_url,attribution_text FROM reference_sources ORDER BY source_id",
    "artifacts": "SELECT source_id,filename,download_url,size_bytes,sha256,required,parser_id,parser_version "
                 "FROM reference_source_artifacts ORDER BY source_id,filename",
    "imports": "SELECT source_id,importer_id,importer_version,reference_schema_version,status,source_checksum,"
               "rows_read,rows_accepted,rows_rejected,warnings_json,errors_json FROM reference_import_runs "
               "ORDER BY source_id",
    "units": "SELECT id,stable_key,language_code,unit_type,canonical_form,normalized_form,part_of_speech,subtype,"
             "identity_qualifier FROM reference_lexical_units ORDER BY id",
    "sourceLinks": "SELECT lexical_unit_id,source_id,source_local_id,source_entry_json FROM reference_source_links "
                   "ORDER BY lexical_unit_id,source_id,source_local_id",
    "forms": "SELECT id,language_code,display_form,normalized_form FROM reference_forms ORDER BY id",
    "formLinks": "SELECT form_id,lexical_unit_id,source_id,source_local_id,form_type,orthographic_status,"
                 "morphology_json FROM reference_form_links ORDER BY form_id,lexical_unit_id,source_id,source_local_id",
    "compounds": "SELECT id,lexical_unit_id,source_id,source_local_id,analysis_text,first_component,"
                 "first_component_grammar,joiner,final_component,final_component_grammar,raw_evidence_json "
                 "FROM reference_compound_analyses ORDER BY id",
    "rawObservations": "SELECT id,source_id,source_local_id,metric_type,raw_form,normalized_form,raw_count,rank,"
                       "language_label,normalized_pos,resolution_status,matched_lexical_unit_id,candidate_count,"
                       "raw_evidence_json FROM reference_raw_observations ORDER BY id",
    "frequency": "SELECT id,lexical_unit_id,source_id,observation_key,evidence_kind,metric_type,raw_count,rank,"
                 "frequency_per_million,zipf_score,document_frequency,dispersion,corpus_token_count,genre,period_start,"
                 "period_end,method,method_version,raw_evidence_json FROM reference_frequency_observations ORDER BY id",
    "candidates": "SELECT observation_id,lexical_unit_id,match_basis FROM reference_observation_candidates "
                  "ORDER BY observation_id,lexical_unit_id",
    "mweComponents": "SELECT lexical_unit_id,position,component_text,normalized_form,lemma_constraint,pos_constraint,"
                     "optional,variant_metadata_json FROM reference_mwe_components ORDER BY lexical_unit_id,position",
    "idiomVariants": "SELECT id,lexical_unit_id,source_id,source_local_id,display_form,normalized_form,variant_type,"
                     "metadata_json FROM reference_expression_variants ORDER BY id",
    "derivedMethods": "SELECT method_id,method_version,policy_checksum,policy_json FROM reference_derived_methods "
                      "ORDER BY method_id,method_version",
}


def canonical_fingerprint(path: str | Path) -> dict[str, Any]:
    components: dict[str, Any] = {}
    overall = hashlib.sha256()
    with _connect(path, readonly=True) as connection:
        for name, query in CANONICAL_QUERIES.items():
            count, checksum = _canonical_row_hash(connection, query)
            components[name] = {"rows": count, "sha256": checksum}
            overall.update(name.encode("utf-8"))
            overall.update(checksum.encode("ascii"))
    return {"sha256": overall.hexdigest(), "components": components}


def validate_reference_database(path: str | Path, *, expected_sources: int) -> dict[str, Any]:
    with _connect(path, readonly=True) as connection:
        integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        schema_version = int(connection.execute(
            "SELECT COALESCE(MAX(version),0) FROM reference_schema_migrations"
        ).fetchone()[0])
        sources = int(connection.execute("SELECT COUNT(*) FROM reference_sources").fetchone()[0])
        completed = int(connection.execute(
            "SELECT COUNT(*) FROM reference_import_runs WHERE status='COMPLETED'"
        ).fetchone()[0])
        failed = int(connection.execute(
            "SELECT COUNT(*) FROM reference_import_runs WHERE status!='COMPLETED'"
        ).fetchone()[0])
        pending = int(connection.execute(
            "SELECT COUNT(*) FROM reference_raw_observations WHERE resolution_status='PENDING'"
        ).fetchone()[0])
        cefr = int(connection.execute("SELECT COUNT(*) FROM reference_cefr_evidence").fetchone()[0])
        domains = int(connection.execute("SELECT COUNT(*) FROM reference_domain_evidence").fetchone()[0])
        associations = int(connection.execute("SELECT COUNT(*) FROM reference_association_evidence").fetchone()[0])
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "reference_lexical_units", "reference_forms", "reference_form_links",
                "reference_compound_analyses", "reference_raw_observations",
                "reference_observation_candidates", "reference_frequency_observations",
                "reference_expression_variants", "reference_mwe_components",
            )
        }
    result = {
        "schemaVersion": schema_version,
        "integrityCheck": integrity_rows,
        "foreignKeyViolations": foreign_keys,
        "sourceCount": sources,
        "completedImportCount": completed,
        "nonCompletedImportCount": failed,
        "pendingResolutionRows": pending,
        "cefrRows": cefr,
        "domainRows": domains,
        "associationRows": associations,
        "tier3Ingested": False,
        "rowCounts": counts,
    }
    failures = []
    if integrity_rows != ["ok"]:
        failures.append("integrity_check failed")
    if foreign_keys:
        failures.append("foreign_key_check failed")
    if schema_version != REFERENCE_SCHEMA_VERSION:
        failures.append("reference schema version mismatch")
    if sources != expected_sources or completed != expected_sources or failed:
        failures.append("source/import completion mismatch")
    if pending:
        failures.append("pending observation resolutions remain")
    if cefr or domains or associations:
        failures.append("forbidden Phase 7.5B evidence exists")
    if failures:
        raise RuntimeError("; ".join(failures))
    return result


def _benchmark_one(
    connection: sqlite3.Connection, name: str, sql: str, parameters: tuple[Any, ...]
) -> dict[str, Any]:
    connection.execute(sql, parameters).fetchall()
    elapsed: list[float] = []
    rows = 0
    for _ in range(9):
        started = time.perf_counter()
        result = connection.execute(sql, parameters).fetchall()
        elapsed.append((time.perf_counter() - started) * 1000)
        rows = len(result)
    plan = [" | ".join(str(value) for value in row) for row in connection.execute(
        "EXPLAIN QUERY PLAN " + sql, parameters
    )]
    return {
        "name": name,
        "rows": rows,
        "medianMs": round(statistics.median(elapsed), 4),
        "minMs": round(min(elapsed), 4),
        "plan": plan,
    }


def benchmark_reference_database(path: str | Path) -> list[dict[str, Any]]:
    with _connect(path, readonly=True) as connection:
        lemma = connection.execute(
            "SELECT normalized_form,part_of_speech FROM reference_lexical_units "
            "WHERE unit_type='LEMMA' AND part_of_speech IS NOT NULL ORDER BY id LIMIT 1"
        ).fetchone()
        surface = connection.execute(
            "SELECT normalized_form FROM reference_forms ORDER BY id LIMIT 1"
        ).fetchone()
        homograph = connection.execute(
            "SELECT normalized_form FROM reference_lexical_units WHERE unit_type='LEMMA' "
            "GROUP BY normalized_form HAVING COUNT(*)>1 ORDER BY normalized_form LIMIT 1"
        ).fetchone()
        idiom = connection.execute(
            "SELECT normalized_form FROM reference_lexical_units WHERE unit_type='IDIOM' ORDER BY id LIMIT 1"
        ).fetchone()
        prefix = (lemma[0][:2] if lemma else "a")
        benchmarks = [
            _benchmark_one(
                connection, "exact lemma + POS",
                "SELECT id,canonical_form FROM reference_lexical_units WHERE language_code='nb' "
                "AND normalized_form=? AND part_of_speech=? AND unit_type='LEMMA'",
                (lemma[0], lemma[1]),
            ),
            _benchmark_one(
                connection, "surface lookup",
                "SELECT f.id,l.lexical_unit_id FROM reference_forms f JOIN reference_form_links l ON l.form_id=f.id "
                "WHERE f.language_code='nb' AND f.normalized_form=? LIMIT 100",
                (surface[0],),
            ),
            _benchmark_one(
                connection, "homograph lookup",
                "SELECT id,part_of_speech,identity_qualifier FROM reference_lexical_units "
                "WHERE language_code='nb' AND normalized_form=? AND unit_type='LEMMA'",
                (homograph[0],),
            ),
            _benchmark_one(
                connection, "frequency evidence fetch",
                "SELECT metric_type,raw_count,rank FROM reference_frequency_observations "
                "WHERE lexical_unit_id=(SELECT id FROM reference_lexical_units ORDER BY id LIMIT 1) "
                "ORDER BY source_id,metric_type",
                (),
            ),
            _benchmark_one(
                connection, "top derived lemma rank",
                "SELECT lexical_unit_id,rank FROM reference_frequency_observations WHERE source_id=? "
                "AND metric_type='DERIVED_LEMMA_RANK' ORDER BY rank,lexical_unit_id LIMIT 100",
                ("nb-bokmal-ngram-2012",),
            ),
            _benchmark_one(
                connection, "idiom lookup",
                "SELECT id,canonical_form FROM reference_lexical_units WHERE language_code='nb' "
                "AND unit_type='IDIOM' AND normalized_form=?",
                (idiom[0],),
            ),
            _benchmark_one(
                connection, "lemma prefix range",
                "SELECT id,canonical_form FROM reference_lexical_units WHERE language_code='nb' "
                "AND normalized_form>=? AND normalized_form<? ORDER BY normalized_form,id LIMIT 100",
                (prefix, prefix + "\uffff"),
            ),
            _benchmark_one(
                connection, "surface prefix range",
                "SELECT id,display_form FROM reference_forms WHERE language_code='nb' "
                "AND normalized_form>=? AND normalized_form<? ORDER BY normalized_form,id LIMIT 100",
                (prefix, prefix + "\uffff"),
            ),
            _benchmark_one(
                connection, "source provenance",
                "SELECT lexical_unit_id,source_local_id FROM reference_source_links "
                "WHERE source_id=? ORDER BY source_local_id LIMIT 100",
                ("nb-norsk-ordbank-nob-2022-02-01",),
            ),
        ]
    return benchmarks


def database_storage(path: str | Path) -> dict[str, int | None]:
    database = Path(path)
    with _connect(database, readonly=True) as connection:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        index_bytes: int | None = None
        table_bytes: int | None = None
        try:
            index_bytes = int(connection.execute(
                "SELECT COALESCE(SUM(pgsize),0) FROM dbstat WHERE name IN "
                "(SELECT name FROM sqlite_master WHERE type='index')"
            ).fetchone()[0])
            table_bytes = int(connection.execute(
                "SELECT COALESCE(SUM(pgsize),0) FROM dbstat WHERE name IN "
                "(SELECT name FROM sqlite_master WHERE type='table')"
            ).fetchone()[0])
        except sqlite3.Error:
            pass
    return {
        "fileBytes": database.stat().st_size,
        "pageBytes": page_size * page_count,
        "freePageBytes": page_size * freelist,
        "indexBytes": index_bytes,
        "tableBytes": table_bytes,
    }


def write_reports(
    report_directory: str | Path,
    *,
    manifests: Iterable[SourceManifest],
    artifacts: dict[str, tuple[VerifiedArtifact, ...]],
    quality: dict[str, Any],
    validation: dict[str, Any],
    benchmarks: list[dict[str, Any]],
    storage: dict[str, Any],
    fingerprint: dict[str, Any],
    main_isolation: dict[str, Any],
    deterministic_rebuild: dict[str, Any] | None = None,
) -> dict[str, str]:
    root = Path(report_directory)
    root.mkdir(parents=True, exist_ok=True)
    attribution = {
        item.source_id: {
            "source": item.payload["title"],
            "provider": item.payload["provider"],
            "version": item.payload["version"],
            "license": item.payload["license"],
            "attribution": item.payload.get("attribution"),
            "landingPage": item.payload["landingUrl"],
        }
        for item in manifests
    }
    raw_sizes = {
        source_id: {item.path.name: item.size_bytes for item in source_artifacts}
        for source_id, source_artifacts in artifacts.items()
    }
    report = {
        "formatVersion": "language-reference-quality/v1",
        "generatedAt": utc_now(),
        "quality": quality,
        "validation": validation,
        "benchmarks": benchmarks,
        "storage": {**storage, "rawArtifactBytes": raw_sizes},
        "canonicalFingerprint": fingerprint,
        "mainDatabaseIsolation": main_isolation,
        "deterministicRebuild": deterministic_rebuild,
        "phaseBoundary": {
            "cefrExpectedEmpty": True,
            "tier3Ingested": False,
            "frontendIntegrated": False,
            "mainDatabaseMutated": False,
        },
    }
    attribution_path = root / "language-reference-attribution.json"
    quality_path = root / "language-reference-quality.json"
    summary_path = root / "language-reference-quality.md"
    attribution_path.write_text(json.dumps(attribution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    quality_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Language reference ingestion quality",
        "",
        f"Generated: {report['generatedAt']}",
        f"Schema: v{validation['schemaVersion']}",
        f"Integrity: {', '.join(validation['integrityCheck'])}",
        f"Foreign-key violations: {len(validation['foreignKeyViolations'])}",
        f"Production CEFR rows: {validation['cefrRows']}",
        f"Domain rows: {validation['domainRows']}",
        f"Tier 3 ingested: {validation['tier3Ingested']}",
        "",
        "## Sources",
        "",
    ]
    for source_id, item in quality.items():
        lines.extend([
            f"### {source_id}", "",
            "```json", json.dumps(item, ensure_ascii=False, indent=2), "```", "",
        ])
    lines.extend(["## Query benchmarks", ""])
    for item in benchmarks:
        lines.append(f"- {item['name']}: median {item['medianMs']} ms; rows {item['rows']}; plan: {'; '.join(item['plan'])}")
    lines.append("")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "attributionJson": str(attribution_path),
        "qualityJson": str(quality_path),
        "qualityMarkdown": str(summary_path),
    }


def build_staging_database(
    staging_path: str | Path,
    *,
    manifests: tuple[SourceManifest, ...],
    artifacts: dict[str, tuple[VerifiedArtifact, ...]],
    progress: Any = None,
) -> dict[str, Any]:
    path = Path(staging_path)
    if path.exists():
        raise FileExistsError(f"staging database already exists: {path}")
    store = ReferenceStore(path)
    store.initialize()
    with _connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("PRAGMA cache_size=-131072")
        importer = ProductionImporter(connection, manifests, artifacts, progress=progress)
        importer.register_sources()
        quality = importer.import_all()
        connection.execute("ANALYZE")
        connection.execute("PRAGMA optimize")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
    validation = validate_reference_database(path, expected_sources=len(manifests))
    benchmarks = benchmark_reference_database(path)
    fingerprint = canonical_fingerprint(path)
    storage = database_storage(path)
    return {
        "quality": quality,
        "validation": validation,
        "benchmarks": benchmarks,
        "fingerprint": fingerprint,
        "storage": storage,
    }


def publish_atomically(staging_path: str | Path, production_path: str | Path) -> None:
    staging = Path(staging_path)
    production = Path(production_path)
    if not staging.exists():
        raise FileNotFoundError(staging)
    production.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, production)


__all__ = [
    "benchmark_reference_database",
    "build_staging_database",
    "canonical_fingerprint",
    "database_storage",
    "publish_atomically",
    "snapshot_user_database",
    "validate_reference_database",
    "write_reports",
]
