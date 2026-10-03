"""Independent, versioned reference database schema."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import sqlite3


REFERENCE_SCHEMA_VERSION = 3


SCHEMA_V1_SQL = r"""
CREATE TABLE reference_sources (
    source_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    language_code TEXT NOT NULL,
    version TEXT NOT NULL,
    release_date TEXT,
    landing_url TEXT NOT NULL,
    license_id TEXT,
    license_url TEXT,
    attribution_text TEXT,
    download_url TEXT,
    expected_filename TEXT,
    declared_size_bytes INTEGER CHECK (declared_size_bytes IS NULL OR declared_size_bytes >= 0),
    format TEXT,
    corpus_description TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE reference_source_artifacts (
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    filename TEXT NOT NULL,
    download_url TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL,
    required INTEGER NOT NULL CHECK (required IN (0,1)),
    parser_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    http_metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (source_id, filename)
);
CREATE INDEX idx_reference_artifacts_checksum
    ON reference_source_artifacts(source_id, sha256, filename);

CREATE TABLE reference_import_runs (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    importer_id TEXT NOT NULL,
    importer_version TEXT NOT NULL,
    reference_schema_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    source_checksum TEXT,
    rows_read INTEGER NOT NULL DEFAULT 0 CHECK (rows_read >= 0),
    rows_accepted INTEGER NOT NULL DEFAULT 0 CHECK (rows_accepted >= 0),
    rows_rejected INTEGER NOT NULL DEFAULT 0 CHECK (rows_rejected >= 0),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX idx_reference_import_runs_source
    ON reference_import_runs(source_id, started_at DESC, id);

CREATE TABLE reference_lexical_units (
    id TEXT PRIMARY KEY,
    stable_key TEXT NOT NULL UNIQUE,
    language_code TEXT NOT NULL,
    unit_type TEXT NOT NULL CHECK (unit_type IN ('LEMMA','PHRASE','IDIOM','COLLOCATION','FORMULA')),
    canonical_form TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    part_of_speech TEXT,
    subtype TEXT,
    identity_qualifier TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_reference_units_lookup
    ON reference_lexical_units(language_code, normalized_form, part_of_speech, unit_type, id);
CREATE INDEX idx_reference_units_prefix
    ON reference_lexical_units(language_code, normalized_form, id);
CREATE INDEX idx_reference_units_kind
    ON reference_lexical_units(language_code, unit_type, normalized_form, id);

CREATE TABLE reference_source_links (
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    source_local_id TEXT NOT NULL,
    import_run_id TEXT REFERENCES reference_import_runs(id),
    source_entry_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (lexical_unit_id, source_id, source_local_id)
);
CREATE INDEX idx_reference_source_links_local
    ON reference_source_links(source_id, source_local_id, lexical_unit_id);

CREATE TABLE reference_forms (
    id TEXT PRIMARY KEY,
    language_code TEXT NOT NULL,
    display_form TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(language_code, display_form, normalized_form)
);
CREATE INDEX idx_reference_forms_lookup
    ON reference_forms(language_code, normalized_form, id);

CREATE TABLE reference_form_links (
    form_id TEXT NOT NULL REFERENCES reference_forms(id) ON DELETE CASCADE,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    source_local_id TEXT NOT NULL,
    form_type TEXT,
    orthographic_status TEXT,
    morphology_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (form_id, lexical_unit_id, source_id, source_local_id)
);
CREATE INDEX idx_reference_form_links_unit
    ON reference_form_links(lexical_unit_id, form_id, source_id);

CREATE TABLE reference_compound_analyses (
    id TEXT PRIMARY KEY,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    source_local_id TEXT NOT NULL,
    analysis_text TEXT,
    first_component TEXT,
    first_component_grammar TEXT,
    joiner TEXT,
    final_component TEXT,
    final_component_grammar TEXT,
    raw_evidence_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (source_id, source_local_id)
);
CREATE INDEX idx_reference_compounds_unit
    ON reference_compound_analyses(lexical_unit_id, source_id, id);

CREATE TABLE reference_raw_observations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    source_local_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    raw_form TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    raw_count INTEGER CHECK (raw_count IS NULL OR raw_count >= 0),
    rank INTEGER CHECK (rank IS NULL OR rank > 0),
    language_label TEXT,
    normalized_pos TEXT,
    resolution_status TEXT NOT NULL CHECK (
        resolution_status IN ('PENDING','MATCHED','AMBIGUOUS','UNMATCHED','EXCLUDED_NONLEXICAL','EXCLUDED_LANGUAGE')
    ),
    matched_lexical_unit_id TEXT REFERENCES reference_lexical_units(id),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    raw_evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (source_id, metric_type, source_local_id)
);
CREATE INDEX idx_reference_raw_observation_lookup
    ON reference_raw_observations(source_id, metric_type, normalized_form, resolution_status, id);
CREATE INDEX idx_reference_raw_observation_rank
    ON reference_raw_observations(source_id, metric_type, rank, id);
CREATE INDEX idx_reference_raw_observation_match
    ON reference_raw_observations(matched_lexical_unit_id, source_id, metric_type, id);

CREATE TABLE reference_observation_candidates (
    observation_id TEXT NOT NULL REFERENCES reference_raw_observations(id) ON DELETE CASCADE,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    match_basis TEXT NOT NULL,
    PRIMARY KEY (observation_id, lexical_unit_id)
);
CREATE INDEX idx_reference_observation_candidates_unit
    ON reference_observation_candidates(lexical_unit_id, observation_id);

CREATE TABLE reference_frequency_observations (
    id TEXT PRIMARY KEY,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    observation_key TEXT NOT NULL,
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('RAW_SOURCE','DERIVED')),
    metric_type TEXT NOT NULL,
    raw_count INTEGER CHECK (raw_count IS NULL OR raw_count >= 0),
    rank INTEGER CHECK (rank IS NULL OR rank > 0),
    frequency_per_million REAL CHECK (frequency_per_million IS NULL OR frequency_per_million >= 0),
    zipf_score REAL,
    document_frequency INTEGER CHECK (document_frequency IS NULL OR document_frequency >= 0),
    dispersion REAL CHECK (dispersion IS NULL OR (dispersion >= 0 AND dispersion <= 1)),
    corpus_token_count INTEGER CHECK (corpus_token_count IS NULL OR corpus_token_count > 0),
    genre TEXT,
    period_start TEXT,
    period_end TEXT,
    method TEXT,
    method_version TEXT,
    raw_evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(lexical_unit_id, source_id, metric_type, observation_key)
);
CREATE INDEX idx_reference_frequency_source_rank
    ON reference_frequency_observations(source_id, metric_type, rank, lexical_unit_id);
CREATE INDEX idx_reference_frequency_unit
    ON reference_frequency_observations(lexical_unit_id, source_id, metric_type);

CREATE TABLE reference_cefr_evidence (
    id TEXT PRIMARY KEY,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('SOURCE_LABEL','LEARNER_CORPUS_DISTRIBUTION','TEXTBOOK_DISTRIBUTION','EXPERT','ESTIMATED')),
    best_level TEXT CHECK (best_level IS NULL OR best_level IN ('A1','A2','B1','B2','C1','C2')),
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH','MEDIUM','LOW','ESTIMATED')),
    a1_value REAL CHECK (a1_value IS NULL OR a1_value >= 0),
    a2_value REAL CHECK (a2_value IS NULL OR a2_value >= 0),
    b1_value REAL CHECK (b1_value IS NULL OR b1_value >= 0),
    b2_value REAL CHECK (b2_value IS NULL OR b2_value >= 0),
    c1_value REAL CHECK (c1_value IS NULL OR c1_value >= 0),
    c2_value REAL CHECK (c2_value IS NULL OR c2_value >= 0),
    method TEXT,
    method_version TEXT,
    raw_evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_reference_cefr_level
    ON reference_cefr_evidence(best_level, evidence_type, confidence, lexical_unit_id);
CREATE INDEX idx_reference_cefr_unit
    ON reference_cefr_evidence(lexical_unit_id, source_id, evidence_type);

CREATE TABLE reference_mwe_components (
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    component_text TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    lemma_constraint TEXT,
    pos_constraint TEXT,
    optional INTEGER NOT NULL DEFAULT 0 CHECK (optional IN (0,1)),
    variant_metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (lexical_unit_id, position)
);
CREATE INDEX idx_reference_mwe_sequence
    ON reference_mwe_components(normalized_form, position, lexical_unit_id);

CREATE TABLE reference_expression_variants (
    id TEXT PRIMARY KEY,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    source_local_id TEXT NOT NULL,
    display_form TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    variant_type TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_reference_variants_lookup
    ON reference_expression_variants(normalized_form, lexical_unit_id);

CREATE TABLE reference_derived_methods (
    method_id TEXT NOT NULL,
    method_version TEXT NOT NULL,
    policy_checksum TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (method_id, method_version)
);

CREATE TABLE reference_association_evidence (
    id TEXT PRIMARY KEY,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    related_lexical_unit_id TEXT REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    relation_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    metric_value REAL NOT NULL,
    raw_count INTEGER CHECK (raw_count IS NULL OR raw_count >= 0),
    context_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_reference_association_top
    ON reference_association_evidence(lexical_unit_id, relation_type, metric_name, metric_value DESC);

CREATE TABLE reference_domain_evidence (
    id TEXT PRIMARY KEY,
    lexical_unit_id TEXT NOT NULL REFERENCES reference_lexical_units(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    domain_key TEXT NOT NULL,
    weight REAL CHECK (weight IS NULL OR (weight >= 0 AND weight <= 1)),
    confidence TEXT CHECK (confidence IS NULL OR confidence IN ('HIGH','MEDIUM','LOW','ESTIMATED')),
    method TEXT NOT NULL,
    method_version TEXT NOT NULL,
    raw_evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_reference_domain
    ON reference_domain_evidence(domain_key, weight DESC, lexical_unit_id);
"""


@dataclass(frozen=True)
class ReferenceMigration:
    version: int
    sql: str

    @property
    def checksum(self) -> str:
        return "sha256:" + hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


SCHEMA_V2_SQL = r"""
CREATE TABLE reference_sentences (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    source_sentence_id TEXT NOT NULL,
    language_code TEXT NOT NULL,
    sentence_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    license_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    lexical_token_count INTEGER NOT NULL CHECK (lexical_token_count >= 0),
    matched_token_count INTEGER NOT NULL DEFAULT 0 CHECK (matched_token_count >= 0),
    ambiguous_token_count INTEGER NOT NULL DEFAULT 0 CHECK (ambiguous_token_count >= 0),
    unmatched_token_count INTEGER NOT NULL DEFAULT 0 CHECK (unmatched_token_count >= 0),
    quality_score REAL NOT NULL DEFAULT 0,
    usable INTEGER NOT NULL DEFAULT 0 CHECK (usable IN (0,1)),
    quality_flags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(source_id, source_sentence_id)
);
CREATE INDEX idx_reference_sentences_source
    ON reference_sentences(source_id, source_sentence_id);
CREATE INDEX idx_reference_sentences_quality
    ON reference_sentences(language_code, usable, quality_score DESC, id);

CREATE TABLE reference_sentence_occurrences (
    sentence_id TEXT NOT NULL REFERENCES reference_sentences(id) ON DELETE CASCADE,
    occurrence_index INTEGER NOT NULL CHECK (occurrence_index >= 0),
    lexical_unit_id TEXT REFERENCES reference_lexical_units(id) ON DELETE SET NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
    surface_form TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    resolution_status TEXT NOT NULL
        CHECK (resolution_status IN ('MATCHED','AMBIGUOUS','UNMATCHED')),
    resolution_basis TEXT NOT NULL,
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    candidate_unit_ids_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (sentence_id, occurrence_index)
);
CREATE INDEX idx_reference_sentence_occurrences_unit
    ON reference_sentence_occurrences(lexical_unit_id, resolution_status, sentence_id, occurrence_index)
    WHERE lexical_unit_id IS NOT NULL;
CREATE INDEX idx_reference_sentence_occurrences_sentence
    ON reference_sentence_occurrences(sentence_id, start_offset, occurrence_index);
CREATE INDEX idx_reference_sentence_occurrences_form
    ON reference_sentence_occurrences(normalized_form, resolution_status, sentence_id);
""".strip()


SCHEMA_V3_SQL = r"""
CREATE TABLE reference_sentence_translations (
    sentence_id TEXT NOT NULL REFERENCES reference_sentences(id) ON DELETE CASCADE,
    target_language_code TEXT NOT NULL,
    translation_sentence_id TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
    import_run_id TEXT REFERENCES reference_import_runs(id),
    license_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (sentence_id, target_language_code, translation_sentence_id)
);
CREATE INDEX idx_reference_sentence_translations_lookup
    ON reference_sentence_translations(sentence_id, target_language_code, translation_sentence_id);
CREATE INDEX idx_reference_sentence_translations_external
    ON reference_sentence_translations(target_language_code, translation_sentence_id, sentence_id);
""".strip()


MIGRATIONS = (
    ReferenceMigration(1, SCHEMA_V1_SQL),
    ReferenceMigration(2, SCHEMA_V2_SQL),
    ReferenceMigration(3, SCHEMA_V3_SQL),
)


def apply_reference_migrations(connection: sqlite3.Connection, *, applied_at: str) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS reference_schema_migrations("
        "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
    )
    connection.commit()
    recorded = {
        int(row[0]): str(row[1])
        for row in connection.execute("SELECT version,checksum FROM reference_schema_migrations")
    }
    unknown = set(recorded) - {item.version for item in MIGRATIONS}
    if unknown:
        raise RuntimeError(f"unsupported future reference schema versions: {sorted(unknown)}")
    for migration in MIGRATIONS:
        existing = recorded.get(migration.version)
        if existing is not None and existing != migration.checksum:
            raise RuntimeError(f"reference migration checksum mismatch for version {migration.version}")
        if existing is not None:
            continue
        safe_timestamp = applied_at.replace("'", "''")
        safe_checksum = migration.checksum.replace("'", "''")
        script = (
            "BEGIN IMMEDIATE;\n"
            + migration.sql
            + "\nINSERT INTO reference_schema_migrations(version,applied_at,checksum) "
            + f"VALUES({migration.version},'{safe_timestamp}','{safe_checksum}');\nCOMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error as exc:
            connection.rollback()
            raise RuntimeError(f"reference migration {migration.version} failed") from exc


__all__ = [
    "MIGRATIONS",
    "REFERENCE_SCHEMA_VERSION",
    "SCHEMA_V1_SQL",
    "SCHEMA_V2_SQL",
    "SCHEMA_V3_SQL",
    "ReferenceMigration",
    "apply_reference_migrations",
]
