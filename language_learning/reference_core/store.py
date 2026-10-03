"""SQLite store for rebuildable reference facts only."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator

from .models import (
    ReferenceLexicalUnit,
    ReferenceSourceRecord,
    deterministic_id,
    make_stable_key,
    normalize_reference_lookup,
)
from .schema import MIGRATIONS, REFERENCE_SCHEMA_VERSION, apply_reference_migrations


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _unit(row: sqlite3.Row | dict[str, Any]) -> ReferenceLexicalUnit:
    return ReferenceLexicalUnit(
        id=str(row["id"]), stable_key=str(row["stable_key"]),
        language_code=str(row["language_code"]), unit_type=str(row["unit_type"]),
        canonical_form=str(row["canonical_form"]), normalized_form=str(row["normalized_form"]),
        part_of_speech=row["part_of_speech"], subtype=row["subtype"],
        identity_qualifier=row["identity_qualifier"],
    )


class ClosingReferenceConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class ReferenceStore:
    def __init__(self, database_path: str | Path, *, read_only: bool = False) -> None:
        self.database_path = Path(database_path)
        self.read_only = bool(read_only)
        self._initialize_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        target: str
        uri = False
        if self.read_only:
            target = self.database_path.resolve().as_uri() + "?mode=ro"
            uri = True
        else:
            target = str(self.database_path)
        connection = sqlite3.connect(
            target, timeout=15, factory=ClosingReferenceConnection, uri=uri
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def initialize(self) -> None:
        if self.read_only:
            raise RuntimeError("a read-only reference store cannot initialize a database")
        with self._initialize_lock:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                apply_reference_migrations(connection, applied_at=utc_now())
                connection.commit()
                versions = connection.execute(
                    "SELECT version,checksum FROM reference_schema_migrations ORDER BY version"
                ).fetchall()
                expected = [(item.version, item.checksum) for item in MIGRATIONS]
                if [(row[0], row[1]) for row in versions] != expected:
                    raise RuntimeError("reference migration ledger is incomplete")

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            version = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM reference_schema_migrations"
            ).fetchone()[0]
            sources = connection.execute("SELECT COUNT(*) FROM reference_sources").fetchone()[0]
            units = connection.execute("SELECT COUNT(*) FROM reference_lexical_units").fetchone()[0]
        return {"schemaVersion": int(version), "sources": int(sources), "lexicalUnits": int(units)}

    def register_source(self, source: ReferenceSourceRecord, **metadata: Any) -> None:
        now = utc_now()
        values = (
            source.source_id, source.canonical_name, source.provider, source.resource_type,
            source.language_code, source.version, metadata.get("release_date"), source.landing_url,
            source.license_id, source.license_url, source.attribution_text,
            metadata.get("download_url"), metadata.get("expected_filename"),
            metadata.get("declared_size_bytes"), metadata.get("format"),
            metadata.get("corpus_description"), metadata.get("notes"), now, now,
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO reference_sources(source_id,canonical_name,provider,resource_type,"
                "language_code,version,release_date,landing_url,license_id,license_url,attribution_text,"
                "download_url,expected_filename,declared_size_bytes,format,corpus_description,notes,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                "canonical_name=excluded.canonical_name,provider=excluded.provider,resource_type=excluded.resource_type,"
                "language_code=excluded.language_code,version=excluded.version,release_date=excluded.release_date,"
                "landing_url=excluded.landing_url,license_id=excluded.license_id,license_url=excluded.license_url,"
                "attribution_text=excluded.attribution_text,download_url=excluded.download_url,"
                "expected_filename=excluded.expected_filename,declared_size_bytes=excluded.declared_size_bytes,"
                "format=excluded.format,corpus_description=excluded.corpus_description,notes=excluded.notes,"
                "updated_at=excluded.updated_at",
                values,
            )

    def get_source(self, source_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM reference_sources WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        return dict(row)

    def begin_import_run(
        self, source_id: str, *, importer_id: str, importer_version: str, source_checksum: str | None
    ) -> str:
        started = utc_now()
        run_id = deterministic_id("reference-import", source_id, importer_id, importer_version, source_checksum or "", started)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO reference_import_runs(id,source_id,importer_id,importer_version,"
                "reference_schema_version,status,source_checksum,started_at) VALUES(?,?,?,?,?,'RUNNING',?,?)",
                (run_id, source_id, importer_id, importer_version, REFERENCE_SCHEMA_VERSION, source_checksum, started),
            )
        return run_id

    def complete_import_run(
        self, run_id: str, *, rows_read: int, rows_accepted: int, rows_rejected: int = 0,
        warnings: list[str] | None = None, errors: list[str] | None = None,
    ) -> None:
        status = "FAILED" if errors else "COMPLETED"
        with self.transaction() as connection:
            connection.execute(
                "UPDATE reference_import_runs SET status=?,rows_read=?,rows_accepted=?,rows_rejected=?,"
                "warnings_json=?,errors_json=?,completed_at=? WHERE id=?",
                (status, rows_read, rows_accepted, rows_rejected, canonical_json(warnings or []),
                 canonical_json(errors or []), utc_now(), run_id),
            )

    def upsert_lexical_unit(
        self, *, language_code: str, unit_type: str, canonical_form: str,
        part_of_speech: str | None = None, subtype: str | None = None,
        identity_qualifier: str | None = None,
    ) -> ReferenceLexicalUnit:
        normalized = normalize_reference_lookup(canonical_form)
        pos = str(part_of_speech).upper() if part_of_speech else None
        kind = str(unit_type).upper()
        stable_key = make_stable_key(
            language_code=language_code, unit_type=kind, normalized_form=normalized,
            part_of_speech=pos, identity_qualifier=identity_qualifier,
        )
        unit_id = deterministic_id("reference-unit", stable_key)
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO reference_lexical_units(id,stable_key,language_code,unit_type,canonical_form,"
                "normalized_form,part_of_speech,subtype,identity_qualifier,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(stable_key) DO UPDATE SET "
                "canonical_form=excluded.canonical_form,subtype=excluded.subtype,updated_at=excluded.updated_at",
                (unit_id, stable_key, language_code, kind, canonical_form, normalized, pos, subtype,
                 identity_qualifier, now, now),
            )
            row = connection.execute(
                "SELECT * FROM reference_lexical_units WHERE stable_key=?", (stable_key,)
            ).fetchone()
        return _unit(row)

    def link_source(
        self, lexical_unit_id: str, *, source_id: str, source_local_id: str,
        import_run_id: str | None = None, source_entry: dict[str, Any] | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO reference_source_links(lexical_unit_id,source_id,source_local_id,import_run_id,source_entry_json) "
                "VALUES(?,?,?,?,?) ON CONFLICT(lexical_unit_id,source_id,source_local_id) DO UPDATE SET "
                "import_run_id=excluded.import_run_id,source_entry_json=excluded.source_entry_json",
                (lexical_unit_id, source_id, source_local_id, import_run_id, canonical_json(source_entry or {})),
            )

    def link_form(
        self, lexical_unit_id: str, *, source_id: str, display_form: str,
        import_run_id: str | None = None, source_local_id: str | None = None,
        form_type: str | None = None, orthographic_status: str | None = None,
        morphology: dict[str, Any] | None = None,
    ) -> str:
        normalized = normalize_reference_lookup(display_form)
        stable_source_local_id = str(source_local_id or "")
        form_id = deterministic_id("reference-form", "nb", display_form, normalized)
        with self.transaction() as connection:
            unit = connection.execute(
                "SELECT language_code FROM reference_lexical_units WHERE id=?", (lexical_unit_id,)
            ).fetchone()
            if unit is None:
                raise KeyError(lexical_unit_id)
            form_id = deterministic_id("reference-form", unit["language_code"], display_form, normalized)
            connection.execute(
                "INSERT OR IGNORE INTO reference_forms(id,language_code,display_form,normalized_form,created_at) "
                "VALUES(?,?,?,?,?)", (form_id, unit["language_code"], display_form, normalized, utc_now()),
            )
            connection.execute(
                "INSERT INTO reference_form_links(form_id,lexical_unit_id,source_id,import_run_id,source_local_id,"
                "form_type,orthographic_status,morphology_json) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(form_id,lexical_unit_id,source_id,source_local_id) DO UPDATE SET "
                "import_run_id=excluded.import_run_id,form_type=excluded.form_type,"
                "orthographic_status=excluded.orthographic_status,morphology_json=excluded.morphology_json",
                (form_id, lexical_unit_id, source_id, import_run_id, stable_source_local_id, form_type,
                 orthographic_status, canonical_json(morphology or {})),
            )
        return form_id

    def add_frequency(self, lexical_unit_id: str, *, source_id: str, metric_type: str,
                      observation_key: str, evidence_kind: str = "RAW_SOURCE",
                      import_run_id: str | None = None, **values: Any) -> str:
        observation_id = deterministic_id(
            "reference-frequency", lexical_unit_id, source_id, metric_type, observation_key
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO reference_frequency_observations(id,lexical_unit_id,source_id,import_run_id,"
                "observation_key,evidence_kind,metric_type,raw_count,rank,frequency_per_million,zipf_score,"
                "document_frequency,dispersion,corpus_token_count,genre,period_start,period_end,method,"
                "method_version,raw_evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(lexical_unit_id,source_id,metric_type,observation_key) DO UPDATE SET "
                "raw_count=excluded.raw_count,rank=excluded.rank,frequency_per_million=excluded.frequency_per_million,"
                "zipf_score=excluded.zipf_score,document_frequency=excluded.document_frequency,"
                "dispersion=excluded.dispersion,method=excluded.method,method_version=excluded.method_version,"
                "raw_evidence_json=excluded.raw_evidence_json",
                (observation_id, lexical_unit_id, source_id, import_run_id, observation_key, evidence_kind,
                 metric_type, values.get("raw_count"), values.get("rank"), values.get("frequency_per_million"),
                 values.get("zipf_score"), values.get("document_frequency"), values.get("dispersion"),
                 values.get("corpus_token_count"), values.get("genre"), values.get("period_start"),
                 values.get("period_end"), values.get("method"), values.get("method_version"),
                 canonical_json(values.get("raw_evidence") or {}), utc_now()),
            )
        return observation_id

    def add_cefr(self, lexical_unit_id: str, *, source_id: str, evidence_type: str,
                 confidence: str, best_level: str | None = None, import_run_id: str | None = None,
                 distribution: dict[str, float] | None = None, method: str | None = None,
                 method_version: str | None = None, raw_evidence: dict[str, Any] | None = None) -> str:
        distribution = {str(k).upper(): v for k, v in (distribution or {}).items()}
        evidence_id = deterministic_id(
            "reference-cefr", lexical_unit_id, source_id, evidence_type, method_version or "", best_level or ""
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO reference_cefr_evidence(id,lexical_unit_id,source_id,import_run_id,evidence_type,"
                "best_level,confidence,a1_value,a2_value,b1_value,b2_value,c1_value,c2_value,method,method_version,"
                "raw_evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (evidence_id, lexical_unit_id, source_id, import_run_id, evidence_type,
                 best_level.upper() if best_level else None, confidence, distribution.get("A1"),
                 distribution.get("A2"), distribution.get("B1"), distribution.get("B2"),
                 distribution.get("C1"), distribution.get("C2"), method, method_version,
                 canonical_json(raw_evidence or {}), utc_now()),
            )
        return evidence_id

    def add_mwe_components(self, lexical_unit_id: str, components: list[dict[str, Any]]) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM reference_mwe_components WHERE lexical_unit_id=?", (lexical_unit_id,))
            for position, component in enumerate(components):
                text = str(component["text"])
                connection.execute(
                    "INSERT INTO reference_mwe_components(lexical_unit_id,position,component_text,normalized_form,"
                    "lemma_constraint,pos_constraint,optional,variant_metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                    (lexical_unit_id, position, text, normalize_reference_lookup(text),
                     component.get("lemmaConstraint"), component.get("posConstraint"),
                     1 if component.get("optional") else 0, canonical_json(component.get("metadata") or {})),
                )

    def add_association(self, lexical_unit_id: str, *, source_id: str, relation_type: str,
                        metric_name: str, metric_version: str, metric_value: float,
                        related_lexical_unit_id: str | None = None, raw_count: int | None = None,
                        context: dict[str, Any] | None = None, import_run_id: str | None = None) -> str:
        evidence_id = deterministic_id(
            "reference-association", lexical_unit_id, related_lexical_unit_id or "", source_id,
            relation_type, metric_name, metric_version
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO reference_association_evidence(id,lexical_unit_id,related_lexical_unit_id,source_id,"
                "import_run_id,relation_type,metric_name,metric_version,metric_value,raw_count,context_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (evidence_id, lexical_unit_id, related_lexical_unit_id, source_id, import_run_id,
                 relation_type, metric_name, metric_version, metric_value, raw_count, canonical_json(context or {})),
            )
        return evidence_id

    def lookup_lemma(self, *, language_code: str, normalized_form: str) -> list[ReferenceLexicalUnit]:
        normalized = normalize_reference_lookup(normalized_form)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reference_lexical_units WHERE language_code=? AND normalized_form=? "
                "AND unit_type='LEMMA' ORDER BY part_of_speech,stable_key",
                (language_code, normalized),
            ).fetchall()
        return [_unit(row) for row in rows]

    def lookup_lemmas_batch(
        self, *, language_code: str, normalized_forms: list[str] | tuple[str, ...] | set[str]
    ) -> dict[str, list[ReferenceLexicalUnit]]:
        normalized = sorted({normalize_reference_lookup(item) for item in normalized_forms if item})
        result = {item: [] for item in normalized}
        if not normalized:
            return result
        with self._connect() as connection:
            for offset in range(0, len(normalized), 400):
                batch = normalized[offset:offset + 400]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "SELECT * FROM reference_lexical_units WHERE language_code=? "
                    f"AND normalized_form IN ({placeholders}) AND unit_type='LEMMA' "
                    "ORDER BY normalized_form,part_of_speech,stable_key",
                    (language_code, *batch),
                ).fetchall()
                for row in rows:
                    result[str(row["normalized_form"])].append(_unit(row))
        return result

    def table_rows(self, table: str) -> list[dict[str, Any]]:
        allowed = {
            "reference_sources", "reference_source_artifacts", "reference_import_runs",
            "reference_lexical_units", "reference_source_links",
            "reference_forms", "reference_form_links", "reference_frequency_observations",
            "reference_compound_analyses",
            "reference_cefr_evidence", "reference_mwe_components", "reference_association_evidence",
            "reference_raw_observations", "reference_observation_candidates",
            "reference_expression_variants", "reference_derived_methods", "reference_domain_evidence",
        }
        if table not in allowed:
            raise ValueError("unsupported reference table")
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        return [dict(row) for row in rows]


__all__ = ["REFERENCE_SCHEMA_VERSION", "ReferenceStore", "canonical_json", "utc_now"]
