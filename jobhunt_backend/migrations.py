"""Ordered, checksummed SQLite migrations for the Job Hunt database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3

from .models import JobhuntError


SCHEMA_VERSION = 13


@dataclass(frozen=True)
class Migration:
    version: int
    sql: str
    requires_backup: bool = False
    disable_foreign_keys: bool = False

    @property
    def checksum(self) -> str:
        return "sha256:" + hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


MIGRATION_1_SQL = r"""
CREATE TABLE canonical_jobs (
    id TEXT PRIMARY KEY,
    legacy_id TEXT UNIQUE,
    legacy_fingerprint TEXT NOT NULL UNIQUE,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    seniority TEXT NOT NULL,
    location_city TEXT NOT NULL,
    location_country TEXT NOT NULL,
    work_mode TEXT NOT NULL,
    hybrid_details TEXT NOT NULL,
    contract_type TEXT NOT NULL,
    contract_details TEXT NOT NULL,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT NOT NULL,
    salary_period TEXT NOT NULL,
    salary_tax_type TEXT NOT NULL,
    salary_is_known INTEGER NOT NULL CHECK (salary_is_known IN (0, 1)),
    source_name TEXT NOT NULL,
    source_url TEXT,
    source_captured_at TEXT,
    expires_at TEXT,
    original_text TEXT NOT NULL,
    requirements_json TEXT NOT NULL DEFAULT '{}',
    branding_path TEXT,
    branding_mime TEXT,
    branding_sha256 TEXT,
    legacy_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    deleted_at TEXT
);
CREATE INDEX idx_jobhunt_jobs_visible
    ON canonical_jobs(deleted_at, archived_at, updated_at DESC, id);
CREATE INDEX idx_jobhunt_jobs_expiration
    ON canonical_jobs(expires_at, id);

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES canonical_jobs(id),
    current_status TEXT NOT NULL CHECK (current_status IN (
        'new','to_review','worth_applying','applied','follow_up',
        'interview','offer','rejected','archived'
    )),
    source_expired INTEGER NOT NULL DEFAULT 0 CHECK (source_expired IN (0, 1)),
    priority TEXT NOT NULL CHECK (priority IN ('P1','P2','P3','skip','unknown')),
    next_action TEXT NOT NULL CHECK (next_action IN (
        'analyze','tailor_cv','apply','follow_up','prepare_interview',
        'ask_recruiter','archive','none'
    )),
    date_applied TEXT,
    follow_up_date TEXT,
    recruiter_name TEXT,
    recruiter_contact TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_jobhunt_applications_status
    ON applications(current_status, priority, follow_up_date, job_id);

CREATE TABLE application_events (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    origin TEXT NOT NULL CHECK (origin IN ('migration','user','system'))
);
CREATE INDEX idx_jobhunt_application_events
    ON application_events(application_id, occurred_at, id);
CREATE TRIGGER jobhunt_application_events_no_update
BEFORE UPDATE ON application_events BEGIN
    SELECT RAISE(ABORT, 'application events are append-only');
END;
CREATE TRIGGER jobhunt_application_events_no_delete
BEFORE DELETE ON application_events BEGIN
    SELECT RAISE(ABORT, 'application events are append-only');
END;

CREATE TABLE legacy_evaluation_snapshots (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES canonical_jobs(id),
    snapshot_kind TEXT NOT NULL CHECK (snapshot_kind = 'legacy_imported'),
    match_score INTEGER CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 100),
    match_category TEXT NOT NULL,
    match_summary TEXT NOT NULL,
    is_experimental INTEGER NOT NULL CHECK (is_experimental IN (0, 1)),
    green_flags_json TEXT NOT NULL DEFAULT '[]',
    red_flags_json TEXT NOT NULL DEFAULT '[]',
    skill_gaps_json TEXT NOT NULL DEFAULT '[]',
    fit_reasons_json TEXT NOT NULL DEFAULT '[]',
    recommended_cv_version TEXT NOT NULL,
    cv_bullets_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE compatibility_settings (
    setting_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('legacy_imported','user')),
    updated_at TEXT NOT NULL
);

CREATE TABLE local_storage_migrations (
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('in_progress','succeeded','failed')),
    payload_sha256 TEXT NOT NULL,
    recovery_path TEXT NOT NULL,
    offers_submitted INTEGER NOT NULL DEFAULT 0,
    offers_imported INTEGER NOT NULL DEFAULT 0,
    offers_existing INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    failure_json TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE local_storage_migration_items (
    migration_id TEXT NOT NULL REFERENCES local_storage_migrations(id) ON DELETE CASCADE,
    item_index INTEGER NOT NULL,
    legacy_id TEXT,
    job_id TEXT REFERENCES canonical_jobs(id),
    outcome TEXT NOT NULL CHECK (outcome IN ('imported','already_existing','failed')),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (migration_id, item_index)
);
CREATE INDEX idx_jobhunt_migration_items_job
    ON local_storage_migration_items(job_id, migration_id);
""".strip()


MIGRATION_2_SQL = r"""
CREATE TABLE career_profile (
    id TEXT PRIMARY KEY CHECK (id = 'default'),
    current_role_title TEXT,
    headline TEXT,
    professional_summary TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE career_experience (
    id TEXT PRIMARY KEY,
    job_title TEXT NOT NULL,
    employer TEXT,
    start_date TEXT,
    end_date TEXT,
    is_current INTEGER CHECK (is_current IS NULL OR is_current IN (0, 1)),
    location TEXT,
    employment_type TEXT,
    description TEXT,
    domains_json TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE career_education (
    id TEXT PRIMARY KEY,
    institution TEXT NOT NULL,
    field_program TEXT,
    qualification TEXT,
    start_date TEXT,
    end_date TEXT,
    completion_status TEXT,
    origin TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE career_certifications (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    issuer TEXT,
    issued_date TEXT,
    expiration_date TEXT,
    credential_reference TEXT,
    origin TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE career_languages (
    id TEXT PRIMARY KEY,
    language_name TEXT NOT NULL,
    proficiency TEXT,
    proficiency_scheme TEXT,
    confidence INTEGER CHECK (confidence IS NULL OR confidence BETWEEN 1 AND 5),
    origin TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE career_skills (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    normalized_key TEXT,
    level INTEGER CHECK (level IS NULL OR level BETWEEN 0 AND 5),
    confidence INTEGER CHECK (confidence IS NULL OR confidence BETWEEN 1 AND 5),
    development_interest INTEGER CHECK (development_interest IS NULL OR development_interest BETWEEN 1 AND 5),
    evidence_notes TEXT,
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_career_skills_name ON career_skills(display_name COLLATE NOCASE, id);
CREATE TABLE career_preferences (
    id TEXT PRIMARY KEY,
    dimension_key TEXT NOT NULL UNIQUE,
    value_json TEXT NOT NULL,
    importance INTEGER CHECK (importance IS NULL OR importance BETWEEN 1 AND 5),
    confidence INTEGER CHECK (confidence IS NULL OR confidence BETWEEN 1 AND 5),
    origin TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE career_constraints (
    id TEXT PRIMARY KEY,
    constraint_key TEXT NOT NULL UNIQUE,
    value_json TEXT NOT NULL,
    is_hard INTEGER NOT NULL DEFAULT 1 CHECK (is_hard IN (0, 1)),
    origin TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE career_profile_evidence (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT,
    field_name TEXT,
    origin TEXT NOT NULL,
    source_reference TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_career_profile_evidence_target
    ON career_profile_evidence(target_type, target_id, created_at, id);
CREATE TABLE career_profile_revisions (
    revision INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    snapshot_json TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE assessment_runs (
    id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','completed','abandoned')),
    scoring_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_assessment_runs_instrument
    ON assessment_runs(instrument_id, created_at DESC, id);
CREATE TABLE assessment_responses (
    run_id TEXT NOT NULL REFERENCES assessment_runs(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    raw_answer_json TEXT NOT NULL,
    answered_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id)
);
CREATE TABLE assessment_scores (
    run_id TEXT NOT NULL REFERENCES assessment_runs(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    raw_score REAL NOT NULL,
    normalized_score REAL,
    interpretation_band TEXT,
    scoring_version TEXT NOT NULL,
    PRIMARY KEY (run_id, dimension)
);

CREATE TRIGGER assessment_responses_completed_no_insert
BEFORE INSERT ON assessment_responses
WHEN (SELECT status FROM assessment_runs WHERE id=NEW.run_id) = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment responses are immutable'); END;
CREATE TRIGGER assessment_responses_completed_no_update
BEFORE UPDATE ON assessment_responses
WHEN (SELECT status FROM assessment_runs WHERE id=OLD.run_id) = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment responses are immutable'); END;
CREATE TRIGGER assessment_responses_completed_no_delete
BEFORE DELETE ON assessment_responses
WHEN (SELECT status FROM assessment_runs WHERE id=OLD.run_id) = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment responses are immutable'); END;
CREATE TRIGGER assessment_scores_completed_no_insert
BEFORE INSERT ON assessment_scores
WHEN (SELECT status FROM assessment_runs WHERE id=NEW.run_id) = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment scores are immutable'); END;
CREATE TRIGGER assessment_scores_completed_no_update
BEFORE UPDATE ON assessment_scores
WHEN (SELECT status FROM assessment_runs WHERE id=OLD.run_id) = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment scores are immutable'); END;
CREATE TRIGGER assessment_scores_completed_no_delete
BEFORE DELETE ON assessment_scores
WHEN (SELECT status FROM assessment_runs WHERE id=OLD.run_id) = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment scores are immutable'); END;
CREATE TRIGGER assessment_runs_completed_no_update
BEFORE UPDATE ON assessment_runs WHEN OLD.status = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment runs are immutable'); END;
CREATE TRIGGER assessment_runs_completed_no_delete
BEFORE DELETE ON assessment_runs WHEN OLD.status = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed assessment runs are immutable'); END;
""".strip()


MIGRATION_3_SQL = r"""
CREATE TABLE career_profile_revisions_v3 (
    revision INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
INSERT INTO career_profile_revisions_v3(revision, fingerprint, snapshot_json, changed_at)
SELECT revision, fingerprint, snapshot_json, changed_at
FROM career_profile_revisions;
DROP TABLE career_profile_revisions;
ALTER TABLE career_profile_revisions_v3 RENAME TO career_profile_revisions;
CREATE INDEX idx_career_profile_revisions_fingerprint
    ON career_profile_revisions(fingerprint, revision);
""".strip()


MIGRATION_4_SQL = r"""
CREATE TABLE career_tracks (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('exploring','active','paused','archived')),
    countries_json TEXT NOT NULL DEFAULT '[]',
    regions_cities_json TEXT NOT NULL DEFAULT '[]',
    remote_allowed INTEGER CHECK (remote_allowed IS NULL OR remote_allowed IN (0, 1)),
    relocation_relevant INTEGER CHECK (relocation_relevant IS NULL OR relocation_relevant IN (0, 1)),
    primary_currency TEXT,
    evaluation_policy_version TEXT,
    rationale TEXT,
    notes TEXT,
    seed_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_career_tracks_status
    ON career_tracks(status, updated_at DESC, id);

CREATE TABLE track_search_profiles (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES career_tracks(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('enabled','paused','archived')),
    include_keywords_json TEXT NOT NULL DEFAULT '[]',
    exclude_keywords_json TEXT NOT NULL DEFAULT '[]',
    role_intent TEXT,
    countries_json TEXT NOT NULL DEFAULT '[]',
    regions_cities_json TEXT NOT NULL DEFAULT '[]',
    work_models_json TEXT NOT NULL DEFAULT '[]',
    schedule_hints_json TEXT NOT NULL DEFAULT '[]',
    contract_hints_json TEXT NOT NULL DEFAULT '[]',
    language_hints_json TEXT NOT NULL DEFAULT '[]',
    seniority_hints_json TEXT NOT NULL DEFAULT '[]',
    planned_source_keys_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    seed_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_track_search_profiles_track
    ON track_search_profiles(track_id, status, updated_at DESC, id);

CREATE TABLE track_job_assignments (
    track_id TEXT NOT NULL REFERENCES career_tracks(id),
    job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    origin TEXT NOT NULL CHECK (origin IN ('manual','seed','legacy_reviewed')),
    note TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (track_id, job_id)
);
CREATE INDEX idx_track_job_assignments_job
    ON track_job_assignments(job_id, active, track_id);
CREATE INDEX idx_track_job_assignments_track
    ON track_job_assignments(track_id, active, updated_at DESC, job_id);
""".strip()


MIGRATION_5_SQL = r"""
CREATE TABLE source_definitions (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    source_category TEXT NOT NULL CHECK (source_category IN (
        'manual','official_api','official_feed','job_board','company_site','email_alert','other'
    )),
    expected_access_method TEXT NOT NULL CHECK (expected_access_method IN (
        'manual','official_api','official_feed','email','public_html','browser_automation','unknown'
    )),
    home_url TEXT,
    definition_state TEXT NOT NULL CHECK (definition_state IN ('active','planned')),
    adapter_key TEXT,
    adapter_version TEXT,
    adapter_implemented INTEGER NOT NULL DEFAULT 0 CHECK (adapter_implemented IN (0,1)),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE source_policies (
    source_id TEXT PRIMARY KEY REFERENCES source_definitions(id),
    access_method TEXT NOT NULL CHECK (access_method IN (
        'manual','official_api','official_feed','email','public_html','browser_automation','unknown'
    )),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    operational_state TEXT NOT NULL CHECK (operational_state IN (
        'manual_only','planned','enabled','paused','degraded','disabled'
    )),
    polling_cadence_seconds INTEGER CHECK (polling_cadence_seconds IS NULL OR polling_cadence_seconds > 0),
    maximum_request_budget INTEGER CHECK (maximum_request_budget IS NULL OR maximum_request_budget >= 0),
    concurrency_limit INTEGER CHECK (concurrency_limit IS NULL OR concurrency_limit > 0),
    conditional_requests_supported INTEGER CHECK (conditional_requests_supported IS NULL OR conditional_requests_supported IN (0,1)),
    last_attempt_at TEXT,
    last_success_at TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    backoff_until TEXT,
    last_error_class TEXT,
    terms_reviewed_at TEXT,
    robots_reviewed_at TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE search_profile_sources (
    search_profile_id TEXT NOT NULL REFERENCES track_search_profiles(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES source_definitions(id),
    legacy_source_key TEXT NOT NULL,
    resolved_at TEXT NOT NULL,
    PRIMARY KEY (search_profile_id, source_id)
);
CREATE INDEX idx_search_profile_sources_source
    ON search_profile_sources(source_id, search_profile_id);

CREATE TABLE source_listings (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_definitions(id),
    identity_key TEXT NOT NULL,
    external_id TEXT,
    canonical_url TEXT,
    observed_url TEXT,
    title_hint TEXT,
    company_hint TEXT,
    location_hint TEXT,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active','expired','removed','unknown')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    source_ended_at TEXT,
    canonical_job_id TEXT REFERENCES canonical_jobs(id),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, identity_key)
);
CREATE INDEX idx_source_listings_source_seen
    ON source_listings(source_id, last_seen_at DESC, id);
CREATE INDEX idx_source_listings_job
    ON source_listings(canonical_job_id, id);

CREATE TABLE source_listing_tracks (
    listing_id TEXT NOT NULL REFERENCES source_listings(id) ON DELETE CASCADE,
    track_id TEXT NOT NULL REFERENCES career_tracks(id),
    discovered_at TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (listing_id, track_id)
);

CREATE TABLE source_listing_search_profiles (
    listing_id TEXT NOT NULL REFERENCES source_listings(id) ON DELETE CASCADE,
    search_profile_id TEXT NOT NULL REFERENCES track_search_profiles(id),
    discovered_at TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (listing_id, search_profile_id)
);

CREATE TABLE raw_blobs (
    sha256 TEXT PRIMARY KEY CHECK (length(sha256) = 64),
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    mime_type TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE raw_captures (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES source_listings(id),
    blob_sha256 TEXT NOT NULL REFERENCES raw_blobs(sha256),
    mime_type TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    input_method TEXT NOT NULL CHECK (input_method IN ('manual_paste','manual_file','legacy_migration')),
    source_url TEXT,
    http_status INTEGER,
    safe_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_raw_captures_listing
    ON raw_captures(listing_id, captured_at DESC, id DESC);
CREATE INDEX idx_raw_captures_blob
    ON raw_captures(blob_sha256, id);

CREATE TRIGGER raw_captures_no_update
BEFORE UPDATE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;
CREATE TRIGGER raw_captures_no_delete
BEFORE DELETE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;
CREATE TRIGGER raw_blobs_no_update
BEFORE UPDATE ON raw_blobs BEGIN
    SELECT RAISE(ABORT, 'raw blobs are immutable');
END;
CREATE TRIGGER raw_blobs_no_delete
BEFORE DELETE ON raw_blobs BEGIN
    SELECT RAISE(ABORT, 'raw blobs are immutable');
END;
""".strip()


MIGRATION_6_SQL = r"""
CREATE TABLE extraction_runs (
    id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL REFERENCES raw_captures(id),
    extractor_kind TEXT NOT NULL CHECK (extractor_kind IN (
        'json_structured','json_ld_jobposting','html_metadata','manual_hints'
    )),
    extractor_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (length(input_hash) = 64),
    output_schema_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'running','completed','completed_with_warnings','failed'
    )),
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'pending','valid','valid_with_warnings','invalid'
    )),
    fact_count INTEGER NOT NULL DEFAULT 0 CHECK (fact_count >= 0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error_class TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(capture_id, extractor_kind, extractor_version, input_hash)
);
CREATE INDEX idx_extraction_runs_capture
    ON extraction_runs(capture_id, created_at DESC, id);

CREATE TABLE extracted_facts (
    id TEXT PRIMARY KEY,
    extraction_run_id TEXT NOT NULL REFERENCES extraction_runs(id),
    capture_id TEXT NOT NULL REFERENCES raw_captures(id),
    namespace TEXT NOT NULL,
    fact_type TEXT NOT NULL,
    source_field TEXT NOT NULL,
    label TEXT,
    source_wording TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('text','number','boolean','json')),
    value_text TEXT,
    value_number REAL,
    value_boolean INTEGER CHECK (value_boolean IS NULL OR value_boolean IN (0,1)),
    value_json TEXT,
    unit TEXT,
    currency TEXT,
    period TEXT,
    requirement_preference TEXT NOT NULL DEFAULT 'unknown' CHECK (
        requirement_preference IN ('required','preferred','optional','unknown')
    ),
    state TEXT NOT NULL CHECK (state IN (
        'explicit_positive','explicit_negative','derived','inferred'
    )),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence_locator_json TEXT NOT NULL,
    validation_state TEXT NOT NULL CHECK (validation_state IN ('valid','invalid','warning')),
    validation_message TEXT,
    normalization_state TEXT NOT NULL DEFAULT 'unmapped' CHECK (
        normalization_state IN ('unmapped','mapped','ambiguous','not_applicable')
    ),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_extracted_facts_run
    ON extracted_facts(extraction_run_id, fact_type, id);
CREATE INDEX idx_extracted_facts_capture
    ON extracted_facts(capture_id, fact_type, created_at DESC, id);

CREATE TABLE normalization_concepts (
    id TEXT PRIMARY KEY,
    concept_type TEXT NOT NULL,
    concept_key TEXT NOT NULL,
    display_label TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(concept_type, concept_key)
);

CREATE TABLE fact_normalizations (
    id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES extracted_facts(id),
    concept_id TEXT NOT NULL REFERENCES normalization_concepts(id),
    rule_version TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    mapping_origin TEXT NOT NULL CHECK (mapping_origin IN ('deterministic_rule','manual')),
    is_manual INTEGER NOT NULL DEFAULT 0 CHECK (is_manual IN (0,1)),
    state TEXT NOT NULL CHECK (state IN ('active','superseded')),
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    UNIQUE(fact_id, concept_id, rule_version)
);
CREATE INDEX idx_fact_normalizations_fact
    ON fact_normalizations(fact_id, state, created_at DESC);

CREATE TABLE canonical_job_projections (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    capture_id TEXT NOT NULL REFERENCES raw_captures(id),
    projection_version INTEGER NOT NULL CHECK (projection_version > 0),
    rule_version TEXT NOT NULL,
    selected_fact_ids_json TEXT NOT NULL,
    applied_override_ids_json TEXT NOT NULL DEFAULT '[]',
    snapshot_json TEXT NOT NULL,
    snapshot_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(job_id, projection_version),
    UNIQUE(job_id, snapshot_fingerprint)
);
CREATE INDEX idx_canonical_job_projections_job
    ON canonical_job_projections(job_id, projection_version DESC);

CREATE TABLE review_items (
    id TEXT PRIMARY KEY,
    reason TEXT NOT NULL CHECK (reason IN (
        'low_confidence','conflicting_salary','conflicting_location',
        'conflicting_company_title','unsupported_unexpected_fact',
        'normalization_ambiguity','malformed_structured_metadata',
        'insufficient_identity','source_disagreement','missing_corrupt_raw_capture'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','error')),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('capture','listing','job','fact','extraction_run')),
    entity_id TEXT NOT NULL,
    related_fact_ids_json TEXT NOT NULL DEFAULT '[]',
    evidence_summary TEXT NOT NULL,
    candidate_resolutions_json TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL CHECK (state IN ('open','resolved','dismissed')),
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    note TEXT
);
CREATE INDEX idx_review_items_state
    ON review_items(state, severity, created_at DESC, id);

CREATE TABLE human_overrides (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    field_name TEXT NOT NULL,
    previous_value_json TEXT,
    replacement_value_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    note TEXT,
    author TEXT NOT NULL CHECK (author = 'local_user'),
    state TEXT NOT NULL CHECK (state IN ('active','retired')),
    created_at TEXT NOT NULL,
    retired_at TEXT
);
CREATE UNIQUE INDEX idx_human_overrides_active_field
    ON human_overrides(job_id, field_name) WHERE state='active';
CREATE INDEX idx_human_overrides_job
    ON human_overrides(job_id, state, created_at DESC);

CREATE TRIGGER extraction_runs_completed_no_update
BEFORE UPDATE ON extraction_runs WHEN OLD.status != 'running'
BEGIN SELECT RAISE(ABORT, 'completed extraction runs are immutable'); END;
CREATE TRIGGER extraction_runs_no_delete
BEFORE DELETE ON extraction_runs
BEGIN SELECT RAISE(ABORT, 'extraction runs are immutable'); END;
CREATE TRIGGER extracted_facts_no_update
BEFORE UPDATE ON extracted_facts
BEGIN SELECT RAISE(ABORT, 'extracted facts are immutable'); END;
CREATE TRIGGER extracted_facts_no_delete
BEFORE DELETE ON extracted_facts
BEGIN SELECT RAISE(ABORT, 'extracted facts are immutable'); END;
CREATE TRIGGER canonical_job_projections_no_update
BEFORE UPDATE ON canonical_job_projections
BEGIN SELECT RAISE(ABORT, 'canonical projections are immutable'); END;
CREATE TRIGGER canonical_job_projections_no_delete
BEFORE DELETE ON canonical_job_projections
BEGIN SELECT RAISE(ABORT, 'canonical projections are immutable'); END;
CREATE TRIGGER human_overrides_no_update
BEFORE UPDATE ON human_overrides
WHEN NOT (OLD.state='active' AND NEW.state='retired'
          AND OLD.id=NEW.id AND OLD.job_id=NEW.job_id AND OLD.field_name=NEW.field_name
          AND OLD.previous_value_json IS NEW.previous_value_json
          AND OLD.replacement_value_json=NEW.replacement_value_json
          AND OLD.reason=NEW.reason AND OLD.note IS NEW.note
          AND OLD.author=NEW.author AND OLD.created_at=NEW.created_at
          AND NEW.retired_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'human override history is immutable'); END;
CREATE TRIGGER human_overrides_no_delete
BEFORE DELETE ON human_overrides
BEGIN SELECT RAISE(ABORT, 'human override history is immutable'); END;
""".strip()


MIGRATION_7_SQL = r"""
DROP TRIGGER extraction_runs_completed_no_update;
DROP TRIGGER extraction_runs_no_delete;
DROP TRIGGER extracted_facts_no_update;
DROP TRIGGER extracted_facts_no_delete;

CREATE TABLE extraction_runs_v7 (
    id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL REFERENCES raw_captures(id),
    extractor_kind TEXT NOT NULL CHECK (extractor_kind IN (
        'json_structured','json_ld_jobposting','html_metadata','manual_hints','ai'
    )),
    extractor_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (length(input_hash) = 64),
    output_schema_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'running','completed','completed_with_warnings','failed'
    )),
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'pending','valid','valid_with_warnings','invalid'
    )),
    fact_count INTEGER NOT NULL DEFAULT 0 CHECK (fact_count >= 0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error_class TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    ai_provider TEXT,
    ai_provider_adapter_version TEXT,
    ai_model TEXT,
    ai_model_version TEXT,
    ai_prompt_id TEXT,
    ai_prompt_version TEXT,
    ai_prompt_fingerprint TEXT,
    ai_response_schema_version TEXT,
    ai_requested_at TEXT,
    ai_responded_at TEXT,
    ai_latency_ms REAL CHECK (ai_latency_ms IS NULL OR ai_latency_ms >= 0),
    ai_attempt_count INTEGER CHECK (ai_attempt_count IS NULL OR ai_attempt_count >= 0),
    ai_finish_reason TEXT,
    ai_provider_request_id TEXT,
    ai_input_tokens INTEGER CHECK (ai_input_tokens IS NULL OR ai_input_tokens >= 0),
    ai_output_tokens INTEGER CHECK (ai_output_tokens IS NULL OR ai_output_tokens >= 0),
    ai_total_tokens INTEGER CHECK (ai_total_tokens IS NULL OR ai_total_tokens >= 0),
    ai_cached_tokens INTEGER CHECK (ai_cached_tokens IS NULL OR ai_cached_tokens >= 0),
    ai_estimated_cost REAL CHECK (ai_estimated_cost IS NULL OR ai_estimated_cost >= 0),
    ai_cost_currency TEXT,
    ai_price_version TEXT,
    ai_raw_response_json TEXT,
    ai_validation_result_json TEXT,
    ai_idempotency_key TEXT,
    ai_run_variant TEXT,
    ai_input_char_count INTEGER CHECK (ai_input_char_count IS NULL OR ai_input_char_count >= 0),
    ai_sent_char_count INTEGER CHECK (ai_sent_char_count IS NULL OR ai_sent_char_count >= 0),
    ai_input_truncated INTEGER CHECK (ai_input_truncated IS NULL OR ai_input_truncated IN (0,1)),
    ai_source_preparation TEXT,
    UNIQUE(ai_idempotency_key, ai_run_variant)
);
INSERT INTO extraction_runs_v7(
    id,capture_id,extractor_kind,extractor_version,input_hash,output_schema_version,
    started_at,completed_at,status,validation_status,fact_count,warning_count,
    warnings_json,error_class,error_message,created_at
)
SELECT id,capture_id,extractor_kind,extractor_version,input_hash,output_schema_version,
       started_at,completed_at,status,validation_status,fact_count,warning_count,
       warnings_json,error_class,error_message,created_at
FROM extraction_runs;

CREATE TABLE extracted_facts_v7 (
    id TEXT PRIMARY KEY,
    extraction_run_id TEXT NOT NULL REFERENCES extraction_runs_v7(id),
    capture_id TEXT NOT NULL REFERENCES raw_captures(id),
    namespace TEXT NOT NULL,
    fact_type TEXT NOT NULL,
    source_field TEXT NOT NULL,
    label TEXT,
    source_wording TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('text','number','boolean','json')),
    value_text TEXT,
    value_number REAL,
    value_boolean INTEGER CHECK (value_boolean IS NULL OR value_boolean IN (0,1)),
    value_json TEXT,
    unit TEXT,
    currency TEXT,
    period TEXT,
    requirement_preference TEXT NOT NULL DEFAULT 'unknown' CHECK (
        requirement_preference IN ('required','preferred','optional','unknown')
    ),
    state TEXT NOT NULL CHECK (state IN (
        'explicit_positive','explicit_negative','derived','inferred'
    )),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence_locator_json TEXT NOT NULL,
    validation_state TEXT NOT NULL CHECK (validation_state IN ('valid','invalid','warning')),
    validation_message TEXT,
    normalization_state TEXT NOT NULL DEFAULT 'unmapped' CHECK (
        normalization_state IN ('unmapped','mapped','ambiguous','not_applicable')
    ),
    created_at TEXT NOT NULL
);
INSERT INTO extracted_facts_v7 SELECT * FROM extracted_facts;

CREATE TABLE fact_normalizations_v7 (
    id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES extracted_facts_v7(id),
    concept_id TEXT NOT NULL REFERENCES normalization_concepts(id),
    rule_version TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    mapping_origin TEXT NOT NULL CHECK (mapping_origin IN ('deterministic_rule','manual')),
    is_manual INTEGER NOT NULL DEFAULT 0 CHECK (is_manual IN (0,1)),
    state TEXT NOT NULL CHECK (state IN ('active','superseded')),
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    UNIQUE(fact_id, concept_id, rule_version)
);
INSERT INTO fact_normalizations_v7 SELECT * FROM fact_normalizations;

DROP TABLE fact_normalizations;
DROP TABLE extracted_facts;
DROP TABLE extraction_runs;
ALTER TABLE extraction_runs_v7 RENAME TO extraction_runs;
ALTER TABLE extracted_facts_v7 RENAME TO extracted_facts;
ALTER TABLE fact_normalizations_v7 RENAME TO fact_normalizations;

CREATE UNIQUE INDEX idx_extraction_runs_deterministic_identity
    ON extraction_runs(capture_id,extractor_kind,extractor_version,input_hash)
    WHERE extractor_kind != 'ai';
CREATE INDEX idx_extraction_runs_capture
    ON extraction_runs(capture_id, created_at DESC, id);
CREATE INDEX idx_extraction_runs_ai_identity
    ON extraction_runs(ai_idempotency_key, created_at DESC)
    WHERE extractor_kind='ai';
CREATE INDEX idx_extracted_facts_run
    ON extracted_facts(extraction_run_id, fact_type, id);
CREATE INDEX idx_extracted_facts_capture
    ON extracted_facts(capture_id, fact_type, created_at DESC, id);
CREATE INDEX idx_fact_normalizations_fact
    ON fact_normalizations(fact_id, state, created_at DESC);

CREATE TABLE ai_extraction_attempts (
    id TEXT PRIMARY KEY,
    extraction_run_id TEXT NOT NULL REFERENCES extraction_runs(id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    provider_status TEXT NOT NULL,
    error_class TEXT,
    error_message TEXT,
    provider_request_id TEXT,
    finish_reason TEXT,
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
    cached_tokens INTEGER CHECK (cached_tokens IS NULL OR cached_tokens >= 0),
    latency_ms REAL CHECK (latency_ms IS NULL OR latency_ms >= 0),
    retryable INTEGER NOT NULL CHECK (retryable IN (0,1)),
    UNIQUE(extraction_run_id, attempt_number)
);
CREATE INDEX idx_ai_extraction_attempts_run
    ON ai_extraction_attempts(extraction_run_id, attempt_number);

CREATE TABLE review_items_v7 (
    id TEXT PRIMARY KEY,
    reason TEXT NOT NULL CHECK (reason IN (
        'low_confidence','conflicting_salary','conflicting_location',
        'conflicting_company_title','unsupported_unexpected_fact',
        'normalization_ambiguity','malformed_structured_metadata',
        'insufficient_identity','source_disagreement','missing_corrupt_raw_capture',
        'unsupported_ai_fact','ai_evidence_not_found','malformed_ai_response',
        'ai_input_truncated','ai_provider_incomplete','ai_provider_failure'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','error')),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('capture','listing','job','fact','extraction_run')),
    entity_id TEXT NOT NULL,
    related_fact_ids_json TEXT NOT NULL DEFAULT '[]',
    evidence_summary TEXT NOT NULL,
    candidate_resolutions_json TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL CHECK (state IN ('open','resolved','dismissed')),
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    note TEXT
);
INSERT INTO review_items_v7 SELECT * FROM review_items;
DROP TABLE review_items;
ALTER TABLE review_items_v7 RENAME TO review_items;
CREATE INDEX idx_review_items_state
    ON review_items(state, severity, created_at DESC, id);

CREATE TRIGGER extraction_runs_completed_no_update
BEFORE UPDATE ON extraction_runs WHEN OLD.status != 'running'
BEGIN SELECT RAISE(ABORT, 'completed extraction runs are immutable'); END;
CREATE TRIGGER extraction_runs_no_delete
BEFORE DELETE ON extraction_runs
BEGIN SELECT RAISE(ABORT, 'extraction runs are immutable'); END;
CREATE TRIGGER extracted_facts_no_update
BEFORE UPDATE ON extracted_facts
BEGIN SELECT RAISE(ABORT, 'extracted facts are immutable'); END;
CREATE TRIGGER extracted_facts_no_delete
BEFORE DELETE ON extracted_facts
BEGIN SELECT RAISE(ABORT, 'extracted facts are immutable'); END;
""".strip()


MIGRATION_8_SQL = r"""
DROP TRIGGER raw_captures_no_update;
DROP TRIGGER raw_captures_no_delete;

CREATE TABLE raw_captures_v8 (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES source_listings(id),
    blob_sha256 TEXT NOT NULL REFERENCES raw_blobs(sha256),
    mime_type TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    input_method TEXT NOT NULL CHECK (input_method IN (
        'manual_paste','manual_file','legacy_migration','nav_api'
    )),
    source_url TEXT,
    http_status INTEGER,
    safe_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
INSERT INTO raw_captures_v8 SELECT * FROM raw_captures;
DROP TABLE raw_captures;
ALTER TABLE raw_captures_v8 RENAME TO raw_captures;
CREATE INDEX idx_raw_captures_listing
    ON raw_captures(listing_id, captured_at DESC, id DESC);
CREATE INDEX idx_raw_captures_blob
    ON raw_captures(blob_sha256, id);
CREATE TRIGGER raw_captures_no_update
BEFORE UPDATE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;
CREATE TRIGGER raw_captures_no_delete
BEFORE DELETE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;

ALTER TABLE source_policies ADD COLUMN last_error_message TEXT;
ALTER TABLE source_policies ADD COLUMN terms_reference TEXT;
ALTER TABLE source_policies ADD COLUMN terms_version TEXT;

CREATE TABLE worker_jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL CHECK (job_type IN (
        'nav_feed_poll','nav_fetch_listing','extract_capture','ai_extract_capture'
    )),
    payload_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_version > 0),
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN (
        'queued','running','retry_wait','completed','failed','cancelled'
    )),
    stage TEXT NOT NULL,
    progress REAL CHECK (progress IS NULL OR (progress >= 0 AND progress <= 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    next_attempt_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0,1)),
    parent_job_id TEXT REFERENCES worker_jobs(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error_class TEXT,
    error_message TEXT,
    result_json TEXT
);
CREATE UNIQUE INDEX idx_worker_jobs_active_idempotency
    ON worker_jobs(idempotency_key)
    WHERE state IN ('queued','running','retry_wait');
CREATE INDEX idx_worker_jobs_claim
    ON worker_jobs(state,next_attempt_at,priority DESC,created_at,id);
CREATE INDEX idx_worker_jobs_parent
    ON worker_jobs(parent_job_id,created_at,id);

CREATE TABLE source_sync_state (
    source_id TEXT PRIMARY KEY REFERENCES source_definitions(id),
    adapter_version TEXT NOT NULL,
    feed_path TEXT,
    current_feed_page_id TEXT,
    next_feed_page_id TEXT,
    etag TEXT,
    last_modified TEXT,
    conditional_feed_path TEXT,
    bootstrap_if_modified_since TEXT,
    bootstrap_started_at TEXT,
    bootstrap_completed_at TEXT,
    bootstrap_horizon_days INTEGER CHECK (
        bootstrap_horizon_days IS NULL OR bootstrap_horizon_days > 0
    ),
    last_feed_event_at TEXT,
    last_poll_at TEXT,
    last_success_at TEXT,
    last_error_class TEXT,
    last_error_message TEXT,
    feed_version TEXT,
    listings_observed INTEGER CHECK (listings_observed IS NULL OR listings_observed >= 0),
    active_listings INTEGER CHECK (active_listings IS NULL OR active_listings >= 0),
    matched_listings INTEGER CHECK (matched_listings IS NULL OR matched_listings >= 0),
    captures_created INTEGER CHECK (captures_created IS NULL OR captures_created >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE source_request_observations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_definitions(id),
    operation_type TEXT NOT NULL,
    request_path TEXT NOT NULL,
    status_code INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    duration_ms REAL CHECK (duration_ms IS NULL OR duration_ms >= 0),
    response_bytes INTEGER CHECK (response_bytes IS NULL OR response_bytes >= 0),
    retry_classification TEXT,
    etag TEXT,
    last_modified TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_source_request_observations_source
    ON source_request_observations(source_id,created_at DESC,id);
""".strip()


MIGRATION_9_SQL = r"""
ALTER TABLE canonical_jobs
    ADD COLUMN merged_into_job_id TEXT REFERENCES canonical_jobs(id);
ALTER TABLE canonical_jobs
    ADD COLUMN merged_at TEXT;
CREATE INDEX idx_jobhunt_jobs_merge_state
    ON canonical_jobs(merged_into_job_id, deleted_at, archived_at, updated_at DESC, id);

CREATE TABLE dedupe_job_keys (
    job_id TEXT PRIMARY KEY REFERENCES canonical_jobs(id),
    company_key TEXT NOT NULL,
    title_key TEXT NOT NULL,
    title_tokens_json TEXT NOT NULL DEFAULT '[]',
    city_key TEXT NOT NULL,
    country_key TEXT NOT NULL,
    publication_at TEXT,
    expiration_at TEXT,
    identity_fingerprint TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_dedupe_job_keys_company_time
    ON dedupe_job_keys(company_key, publication_at, job_id);
CREATE INDEX idx_dedupe_job_keys_company_location
    ON dedupe_job_keys(company_key, country_key, city_key, job_id);
CREATE INDEX idx_dedupe_job_keys_title
    ON dedupe_job_keys(title_key, company_key, job_id);

CREATE TABLE dedupe_job_urls (
    job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    normalized_url TEXT NOT NULL,
    url_kind TEXT NOT NULL CHECK (url_kind IN ('listing','application','source_fact')),
    rule_version TEXT NOT NULL,
    PRIMARY KEY(job_id, normalized_url, url_kind)
);
CREATE INDEX idx_dedupe_job_urls_identity
    ON dedupe_job_urls(normalized_url, job_id);

CREATE TABLE duplicate_candidates (
    id TEXT PRIMARY KEY,
    left_job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    right_job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    pair_key TEXT NOT NULL UNIQUE,
    rule_version TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    left_identity_fingerprint TEXT NOT NULL,
    right_identity_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'open','merged','not_duplicate','dismissed','stale'
    )),
    confidence_class TEXT NOT NULL CHECK (confidence_class IN (
        'exact','strong','review','weak'
    )),
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    hard_contradictions_json TEXT NOT NULL DEFAULT '[]',
    generated_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT,
    resolution TEXT,
    reviewer TEXT,
    CHECK (left_job_id < right_job_id)
);
CREATE INDEX idx_duplicate_candidates_state
    ON duplicate_candidates(state, updated_at DESC, id);
CREATE INDEX idx_duplicate_candidates_jobs
    ON duplicate_candidates(left_job_id, right_job_id, state);

CREATE TABLE duplicate_candidate_events (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES duplicate_candidates(id),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'generated','evidence_changed','marked_not_duplicate','dismissed',
        'merged','reopened','stale','unmerged'
    )),
    origin TEXT NOT NULL CHECK (origin IN ('deterministic_policy','manual_user','system')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_duplicate_candidate_events_candidate
    ON duplicate_candidate_events(candidate_id, created_at, id);
CREATE TRIGGER duplicate_candidate_events_no_update
BEFORE UPDATE ON duplicate_candidate_events BEGIN
    SELECT RAISE(ABORT, 'duplicate candidate events are append-only');
END;
CREATE TRIGGER duplicate_candidate_events_no_delete
BEFORE DELETE ON duplicate_candidate_events BEGIN
    SELECT RAISE(ABORT, 'duplicate candidate events are append-only');
END;

CREATE TABLE canonical_job_merges (
    id TEXT PRIMARY KEY,
    candidate_id TEXT REFERENCES duplicate_candidates(id),
    survivor_job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    absorbed_job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    origin TEXT NOT NULL CHECK (origin IN ('deterministic_auto','manual_user')),
    rule_version TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active','reverted')),
    affected_listing_ids_json TEXT NOT NULL,
    before_state_json TEXT NOT NULL,
    application_handling_json TEXT NOT NULL,
    track_handling_json TEXT NOT NULL,
    override_handling_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    note TEXT,
    merged_at TEXT NOT NULL,
    reverted_at TEXT,
    CHECK (survivor_job_id != absorbed_job_id)
);
CREATE UNIQUE INDEX idx_canonical_job_merges_active_absorbed
    ON canonical_job_merges(absorbed_job_id) WHERE state='active';
CREATE INDEX idx_canonical_job_merges_state
    ON canonical_job_merges(state, merged_at DESC, id);
CREATE INDEX idx_canonical_job_merges_survivor
    ON canonical_job_merges(survivor_job_id, state, merged_at DESC, id);

CREATE TABLE canonical_job_merge_events (
    id TEXT PRIMARY KEY,
    merge_id TEXT NOT NULL REFERENCES canonical_job_merges(id),
    event_type TEXT NOT NULL CHECK (event_type IN ('merged','reverted')),
    origin TEXT NOT NULL CHECK (origin IN ('deterministic_auto','manual_user')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_canonical_job_merge_events_merge
    ON canonical_job_merge_events(merge_id, created_at, id);
CREATE TRIGGER canonical_job_merge_events_no_update
BEFORE UPDATE ON canonical_job_merge_events BEGIN
    SELECT RAISE(ABORT, 'canonical job merge events are append-only');
END;
CREATE TRIGGER canonical_job_merge_events_no_delete
BEFORE DELETE ON canonical_job_merge_events BEGIN
    SELECT RAISE(ABORT, 'canonical job merge events are append-only');
END;

CREATE TABLE worker_jobs_v9 (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL CHECK (job_type IN (
        'nav_feed_poll','nav_fetch_listing','extract_capture','ai_extract_capture',
        'dedupe_scan_job'
    )),
    payload_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_version > 0),
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN (
        'queued','running','retry_wait','completed','failed','cancelled'
    )),
    stage TEXT NOT NULL,
    progress REAL CHECK (progress IS NULL OR (progress >= 0 AND progress <= 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    next_attempt_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0,1)),
    parent_job_id TEXT REFERENCES worker_jobs_v9(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error_class TEXT,
    error_message TEXT,
    result_json TEXT
);
INSERT INTO worker_jobs_v9 SELECT * FROM worker_jobs;
DROP TABLE worker_jobs;
ALTER TABLE worker_jobs_v9 RENAME TO worker_jobs;
CREATE UNIQUE INDEX idx_worker_jobs_active_idempotency
    ON worker_jobs(idempotency_key)
    WHERE state IN ('queued','running','retry_wait');
CREATE INDEX idx_worker_jobs_claim
    ON worker_jobs(state,next_attempt_at,priority DESC,created_at,id);
CREATE INDEX idx_worker_jobs_parent
    ON worker_jobs(parent_job_id,created_at,id);
""".strip()


MIGRATION_10_SQL = r"""
DROP TRIGGER raw_captures_no_update;
DROP TRIGGER raw_captures_no_delete;

CREATE TABLE raw_captures_v10 (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES source_listings(id),
    blob_sha256 TEXT NOT NULL REFERENCES raw_blobs(sha256),
    mime_type TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    input_method TEXT NOT NULL CHECK (input_method IN (
        'manual_paste','manual_file','legacy_migration','nav_api','pracuj_jobalert'
    )),
    source_url TEXT,
    http_status INTEGER,
    safe_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
INSERT INTO raw_captures_v10 SELECT * FROM raw_captures;
DROP TABLE raw_captures;
ALTER TABLE raw_captures_v10 RENAME TO raw_captures;
CREATE INDEX idx_raw_captures_listing
    ON raw_captures(listing_id, captured_at DESC, id DESC);
CREATE INDEX idx_raw_captures_blob
    ON raw_captures(blob_sha256, id);
CREATE TRIGGER raw_captures_no_update
BEFORE UPDATE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;
CREATE TRIGGER raw_captures_no_delete
BEFORE DELETE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;

CREATE TABLE worker_jobs_v10 (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL CHECK (job_type IN (
        'nav_feed_poll','nav_fetch_listing','extract_capture','ai_extract_capture',
        'dedupe_scan_job','pracuj_mail_poll','pracuj_process_message'
    )),
    payload_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_version > 0),
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN (
        'queued','running','retry_wait','completed','failed','cancelled'
    )),
    stage TEXT NOT NULL,
    progress REAL CHECK (progress IS NULL OR (progress >= 0 AND progress <= 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    next_attempt_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0,1)),
    parent_job_id TEXT REFERENCES worker_jobs_v10(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error_class TEXT,
    error_message TEXT,
    result_json TEXT
);
INSERT INTO worker_jobs_v10 SELECT * FROM worker_jobs;
DROP TABLE worker_jobs;
ALTER TABLE worker_jobs_v10 RENAME TO worker_jobs;
CREATE UNIQUE INDEX idx_worker_jobs_active_idempotency
    ON worker_jobs(idempotency_key)
    WHERE state IN ('queued','running','retry_wait');
CREATE INDEX idx_worker_jobs_claim
    ON worker_jobs(state,next_attempt_at,priority DESC,created_at,id);
CREATE INDEX idx_worker_jobs_parent
    ON worker_jobs(parent_job_id,created_at,id);

CREATE TABLE source_mail_sync_state (
    source_id TEXT PRIMARY KEY REFERENCES source_definitions(id),
    adapter_version TEXT NOT NULL,
    mailbox TEXT NOT NULL,
    uidvalidity TEXT,
    last_processed_uid INTEGER NOT NULL DEFAULT 0 CHECK (last_processed_uid >= 0),
    highest_observed_uid INTEGER NOT NULL DEFAULT 0 CHECK (highest_observed_uid >= 0),
    bootstrap_started_at TEXT,
    bootstrap_completed_at TEXT,
    bootstrap_days INTEGER NOT NULL CHECK (bootstrap_days > 0),
    bootstrap_max_messages INTEGER NOT NULL CHECK (bootstrap_max_messages > 0),
    last_poll_at TEXT,
    last_success_at TEXT,
    last_successful_message_at TEXT,
    messages_inspected INTEGER NOT NULL DEFAULT 0 CHECK (messages_inspected >= 0),
    alerts_recognized INTEGER NOT NULL DEFAULT 0 CHECK (alerts_recognized >= 0),
    listings_discovered INTEGER NOT NULL DEFAULT 0 CHECK (listings_discovered >= 0),
    captures_created INTEGER NOT NULL DEFAULT 0 CHECK (captures_created >= 0),
    last_error_class TEXT,
    last_error_message TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE source_email_messages (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_definitions(id),
    mailbox TEXT NOT NULL,
    uidvalidity TEXT NOT NULL,
    uid INTEGER NOT NULL CHECK (uid > 0),
    message_id TEXT,
    raw_blob_sha256 TEXT NOT NULL REFERENCES raw_blobs(sha256),
    received_at TEXT,
    sender TEXT,
    subject TEXT,
    trust_state TEXT NOT NULL CHECK (trust_state IN (
        'verified_transport_metadata','recognized','uncertain'
    )),
    parser_version TEXT NOT NULL,
    processing_state TEXT NOT NULL CHECK (processing_state IN (
        'pending','processing','processed','failed'
    )),
    item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    error_class TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, mailbox, uidvalidity, uid)
);
CREATE INDEX idx_source_email_messages_source_state
    ON source_email_messages(source_id, processing_state, uid, id);
CREATE INDEX idx_source_email_messages_blob
    ON source_email_messages(raw_blob_sha256, id);

CREATE TABLE pracuj_alert_bindings (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_definitions(id),
    subject_matcher TEXT,
    search_profile_id TEXT NOT NULL REFERENCES track_search_profiles(id),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, subject_matcher, search_profile_id)
);
CREATE INDEX idx_pracuj_alert_bindings_profile
    ON pracuj_alert_bindings(search_profile_id, enabled, id);
""".strip()


MIGRATION_11_SQL = r"""
CREATE TABLE track_evaluation_policies (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES career_tracks(id),
    schema_version TEXT NOT NULL CHECK (schema_version = 'track-evaluation-policy@1'),
    policy_version INTEGER NOT NULL CHECK (policy_version > 0),
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) = 71 AND fingerprint LIKE 'sha256:%'),
    policy_json TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('seed','user','legacy_reviewed')),
    created_at TEXT NOT NULL,
    UNIQUE(track_id, policy_version),
    UNIQUE(track_id, fingerprint)
);
CREATE INDEX idx_track_evaluation_policies_track
    ON track_evaluation_policies(track_id, policy_version DESC);

CREATE TABLE evaluations (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    track_id TEXT NOT NULL REFERENCES career_tracks(id),
    profile_revision INTEGER NOT NULL,
    profile_fingerprint TEXT NOT NULL,
    projection_id TEXT REFERENCES canonical_job_projections(id),
    projection_version INTEGER NOT NULL DEFAULT 0 CHECK (projection_version >= 0),
    projection_fingerprint TEXT NOT NULL,
    policy_id TEXT NOT NULL REFERENCES track_evaluation_policies(id),
    policy_version INTEGER NOT NULL CHECK (policy_version > 0),
    policy_fingerprint TEXT NOT NULL,
    track_context_fingerprint TEXT NOT NULL,
    evaluator_version TEXT NOT NULL,
    evaluation_schema_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building','completed','failed')),
    evaluation_basis_json TEXT NOT NULL DEFAULT '{}',
    blocker_count INTEGER NOT NULL DEFAULT 0 CHECK (blocker_count >= 0),
    gap_count INTEGER NOT NULL DEFAULT 0 CHECK (gap_count >= 0),
    unknown_count INTEGER NOT NULL DEFAULT 0 CHECK (unknown_count >= 0),
    required_gap_count INTEGER NOT NULL DEFAULT 0 CHECK (required_gap_count >= 0),
    supported_required_count INTEGER NOT NULL DEFAULT 0 CHECK (supported_required_count >= 0),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(job_id, track_id, input_fingerprint)
);
CREATE INDEX idx_evaluations_job_track
    ON evaluations(job_id, track_id, created_at DESC, id);
CREATE INDEX idx_evaluations_track
    ON evaluations(track_id, created_at DESC, job_id);
CREATE INDEX idx_evaluations_profile
    ON evaluations(profile_fingerprint, created_at DESC, id);
CREATE INDEX idx_evaluations_policy
    ON evaluations(policy_id, created_at DESC, id);

CREATE TABLE evaluation_dimensions (
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
    dimension TEXT NOT NULL CHECK (dimension IN (
        'skills','experience','compensation','geography','preferences'
    )),
    state TEXT NOT NULL CHECK (state IN (
        'supported','partial','gap','blocker','unknown','not_applicable'
    )),
    importance TEXT NOT NULL CHECK (importance IN ('primary','secondary','informational')),
    finding_count INTEGER NOT NULL DEFAULT 0 CHECK (finding_count >= 0),
    explanation_code TEXT NOT NULL,
    display_params_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(evaluation_id, dimension)
);
CREATE INDEX idx_evaluation_dimensions_state
    ON evaluation_dimensions(dimension, state, evaluation_id);

CREATE TABLE evaluation_findings (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
    dimension TEXT NOT NULL CHECK (dimension IN (
        'skills','experience','compensation','geography','preferences'
    )),
    finding_type TEXT NOT NULL CHECK (finding_type IN (
        'support','partial','gap','blocker','unknown_requirement','informational'
    )),
    status TEXT NOT NULL CHECK (status IN (
        'supported','partial','gap','blocker','unknown','not_applicable'
    )),
    importance TEXT NOT NULL CHECK (importance IN ('primary','secondary','informational')),
    requirement_class TEXT NOT NULL CHECK (requirement_class IN (
        'required','preferred','optional','unknown','not_applicable'
    )),
    concept_key TEXT,
    job_fact_ids_json TEXT NOT NULL DEFAULT '[]',
    job_evidence_json TEXT NOT NULL DEFAULT '[]',
    profile_evidence_json TEXT NOT NULL DEFAULT '[]',
    policy_evidence_json TEXT NOT NULL DEFAULT '{}',
    explanation_code TEXT NOT NULL,
    display_params_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_evaluation_findings_evaluation
    ON evaluation_findings(evaluation_id, dimension, status, id);
CREATE INDEX idx_evaluation_findings_concept
    ON evaluation_findings(concept_key, status, evaluation_id);

CREATE TABLE evaluation_current (
    job_id TEXT NOT NULL REFERENCES canonical_jobs(id),
    track_id TEXT NOT NULL REFERENCES career_tracks(id),
    evaluation_id TEXT NOT NULL UNIQUE REFERENCES evaluations(id),
    evaluation_basis_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(job_id, track_id)
);
CREATE INDEX idx_evaluation_current_track
    ON evaluation_current(track_id, updated_at DESC, job_id);

CREATE TRIGGER track_evaluation_policies_no_update
BEFORE UPDATE ON track_evaluation_policies BEGIN
    SELECT RAISE(ABORT, 'Track Evaluation Policies are immutable');
END;
CREATE TRIGGER track_evaluation_policies_no_delete
BEFORE DELETE ON track_evaluation_policies BEGIN
    SELECT RAISE(ABORT, 'Track Evaluation Policies are immutable');
END;
CREATE TRIGGER evaluations_completed_no_update
BEFORE UPDATE ON evaluations WHEN OLD.status = 'completed' BEGIN
    SELECT RAISE(ABORT, 'completed Evaluations are immutable');
END;
CREATE TRIGGER evaluations_no_delete
BEFORE DELETE ON evaluations BEGIN
    SELECT RAISE(ABORT, 'Evaluations are immutable');
END;
CREATE TRIGGER evaluation_dimensions_no_insert_after_completion
BEFORE INSERT ON evaluation_dimensions
WHEN (SELECT status FROM evaluations WHERE id=NEW.evaluation_id) = 'completed' BEGIN
    SELECT RAISE(ABORT, 'completed Evaluation dimensions are immutable');
END;
CREATE TRIGGER evaluation_dimensions_no_update
BEFORE UPDATE ON evaluation_dimensions BEGIN
    SELECT RAISE(ABORT, 'Evaluation dimensions are immutable');
END;
CREATE TRIGGER evaluation_dimensions_no_delete
BEFORE DELETE ON evaluation_dimensions BEGIN
    SELECT RAISE(ABORT, 'Evaluation dimensions are immutable');
END;
CREATE TRIGGER evaluation_findings_no_insert_after_completion
BEFORE INSERT ON evaluation_findings
WHEN (SELECT status FROM evaluations WHERE id=NEW.evaluation_id) = 'completed' BEGIN
    SELECT RAISE(ABORT, 'completed Evaluation findings are immutable');
END;
CREATE TRIGGER evaluation_findings_no_update
BEFORE UPDATE ON evaluation_findings BEGIN
    SELECT RAISE(ABORT, 'Evaluation findings are immutable');
END;
CREATE TRIGGER evaluation_findings_no_delete
BEFORE DELETE ON evaluation_findings BEGIN
    SELECT RAISE(ABORT, 'Evaluation findings are immutable');
END;

CREATE TABLE worker_jobs_v11 (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL CHECK (job_type IN (
        'nav_feed_poll','nav_fetch_listing','extract_capture','ai_extract_capture',
        'dedupe_scan_job','pracuj_mail_poll','pracuj_process_message',
        'evaluation_recompute'
    )),
    payload_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_version > 0),
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN (
        'queued','running','retry_wait','completed','failed','cancelled'
    )),
    stage TEXT NOT NULL,
    progress REAL CHECK (progress IS NULL OR (progress >= 0 AND progress <= 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    next_attempt_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0,1)),
    parent_job_id TEXT REFERENCES worker_jobs_v11(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error_class TEXT,
    error_message TEXT,
    result_json TEXT
);
INSERT INTO worker_jobs_v11 SELECT * FROM worker_jobs;
DROP TABLE worker_jobs;
ALTER TABLE worker_jobs_v11 RENAME TO worker_jobs;
CREATE UNIQUE INDEX idx_worker_jobs_active_idempotency
    ON worker_jobs(idempotency_key)
    WHERE state IN ('queued','running','retry_wait');
CREATE INDEX idx_worker_jobs_claim
    ON worker_jobs(state,next_attempt_at,priority DESC,created_at,id);
CREATE INDEX idx_worker_jobs_parent
    ON worker_jobs(parent_job_id,created_at,id);
""".strip()


MIGRATION_12_SQL = r"""
DROP TRIGGER raw_captures_no_update;
DROP TRIGGER raw_captures_no_delete;

CREATE TABLE raw_captures_v12 (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES source_listings(id),
    blob_sha256 TEXT NOT NULL REFERENCES raw_blobs(sha256),
    mime_type TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    input_method TEXT NOT NULL CHECK (input_method IN (
        'manual_paste','manual_file','legacy_migration','nav_api','pracuj_jobalert',
        'jobbnorge_api_derived'
    )),
    source_url TEXT,
    http_status INTEGER,
    safe_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
INSERT INTO raw_captures_v12 SELECT * FROM raw_captures;
DROP TABLE raw_captures;
ALTER TABLE raw_captures_v12 RENAME TO raw_captures;
CREATE INDEX idx_raw_captures_listing
    ON raw_captures(listing_id, captured_at DESC, id DESC);
CREATE INDEX idx_raw_captures_blob
    ON raw_captures(blob_sha256, id);
CREATE TRIGGER raw_captures_no_update
BEFORE UPDATE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;
CREATE TRIGGER raw_captures_no_delete
BEFORE DELETE ON raw_captures BEGIN
    SELECT RAISE(ABORT, 'raw captures are immutable');
END;

CREATE TABLE source_collection_captures (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_definitions(id),
    blob_sha256 TEXT NOT NULL REFERENCES raw_blobs(sha256),
    operation_type TEXT NOT NULL,
    request_path TEXT NOT NULL,
    query_fingerprint TEXT NOT NULL,
    page_number INTEGER CHECK (page_number IS NULL OR page_number > 0),
    http_status INTEGER,
    mime_type TEXT NOT NULL,
    response_bytes INTEGER NOT NULL CHECK (response_bytes >= 0),
    duration_ms REAL CHECK (duration_ms IS NULL OR duration_ms >= 0),
    etag TEXT,
    last_modified TEXT,
    safe_metadata_json TEXT NOT NULL DEFAULT '{}',
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id,operation_type,request_path,blob_sha256)
);
CREATE INDEX idx_source_collection_captures_source
    ON source_collection_captures(source_id,captured_at DESC,id);
CREATE INDEX idx_source_collection_captures_blob
    ON source_collection_captures(blob_sha256,id);
CREATE TRIGGER source_collection_captures_no_update
BEFORE UPDATE ON source_collection_captures BEGIN
    SELECT RAISE(ABORT, 'source collection captures are immutable');
END;
CREATE TRIGGER source_collection_captures_no_delete
BEFORE DELETE ON source_collection_captures BEGIN
    SELECT RAISE(ABORT, 'source collection captures are immutable');
END;

CREATE TABLE source_listing_collection_evidence (
    listing_id TEXT NOT NULL REFERENCES source_listings(id),
    collection_capture_id TEXT NOT NULL REFERENCES source_collection_captures(id),
    item_index INTEGER NOT NULL CHECK (item_index >= 0),
    json_pointer TEXT NOT NULL,
    external_id TEXT NOT NULL,
    derived_capture_id TEXT REFERENCES raw_captures(id),
    linked_at TEXT NOT NULL,
    PRIMARY KEY(listing_id,collection_capture_id,item_index)
);
CREATE INDEX idx_source_listing_collection_evidence_capture
    ON source_listing_collection_evidence(collection_capture_id,item_index,listing_id);
CREATE INDEX idx_source_listing_collection_evidence_derived
    ON source_listing_collection_evidence(derived_capture_id,listing_id);

CREATE TABLE source_query_sync_state (
    source_id TEXT PRIMARY KEY REFERENCES source_definitions(id),
    adapter_version TEXT NOT NULL,
    cycle_id TEXT,
    query_fingerprint TEXT,
    current_query_index INTEGER NOT NULL DEFAULT 0 CHECK (current_query_index >= 0),
    current_page INTEGER NOT NULL DEFAULT 1 CHECK (current_page > 0),
    pages_fetched INTEGER NOT NULL DEFAULT 0 CHECK (pages_fetched >= 0),
    requests_made INTEGER NOT NULL DEFAULT 0 CHECK (requests_made >= 0),
    jobs_observed_cycle INTEGER NOT NULL DEFAULT 0 CHECK (jobs_observed_cycle >= 0),
    response_bytes_cycle INTEGER NOT NULL DEFAULT 0 CHECK (response_bytes_cycle >= 0),
    query_count INTEGER NOT NULL DEFAULT 0 CHECK (query_count >= 0),
    last_request_path TEXT,
    last_collection_capture_id TEXT REFERENCES source_collection_captures(id),
    cycle_started_at TEXT,
    cycle_completed_at TEXT,
    last_poll_at TEXT,
    last_success_at TEXT,
    last_error_class TEXT,
    last_error_message TEXT,
    listings_observed INTEGER NOT NULL DEFAULT 0 CHECK (listings_observed >= 0),
    matched_listings INTEGER NOT NULL DEFAULT 0 CHECK (matched_listings >= 0),
    captures_created INTEGER NOT NULL DEFAULT 0 CHECK (captures_created >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE worker_jobs_v12 (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL CHECK (job_type IN (
        'nav_feed_poll','nav_fetch_listing','extract_capture','ai_extract_capture',
        'dedupe_scan_job','pracuj_mail_poll','pracuj_process_message',
        'evaluation_recompute','jobbnorge_poll'
    )),
    payload_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_version > 0),
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN (
        'queued','running','retry_wait','completed','failed','cancelled'
    )),
    stage TEXT NOT NULL,
    progress REAL CHECK (progress IS NULL OR (progress >= 0 AND progress <= 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    next_attempt_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0,1)),
    parent_job_id TEXT REFERENCES worker_jobs_v12(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error_class TEXT,
    error_message TEXT,
    result_json TEXT
);
INSERT INTO worker_jobs_v12 SELECT * FROM worker_jobs;
DROP TABLE worker_jobs;
ALTER TABLE worker_jobs_v12 RENAME TO worker_jobs;
CREATE UNIQUE INDEX idx_worker_jobs_active_idempotency
    ON worker_jobs(idempotency_key)
    WHERE state IN ('queued','running','retry_wait');
CREATE INDEX idx_worker_jobs_claim
    ON worker_jobs(state,next_attempt_at,priority DESC,created_at,id);
CREATE INDEX idx_worker_jobs_parent
    ON worker_jobs(parent_job_id,created_at,id);
""".strip()


MIGRATION_13_SQL = r"""
CREATE TABLE application_attributions (
    application_id TEXT PRIMARY KEY REFERENCES applications(id),
    track_id TEXT REFERENCES career_tracks(id),
    discovery_source_id TEXT REFERENCES source_definitions(id),
    attribution_basis TEXT NOT NULL CHECK (attribution_basis IN (
        'captured_at_application','fallback_current_assignment','multiple_current_tracks','unattributed'
    )),
    captured_at TEXT NOT NULL
);
CREATE INDEX idx_application_attributions_track
    ON application_attributions(track_id,captured_at,application_id);
CREATE INDEX idx_application_attributions_source
    ON application_attributions(discovery_source_id,captured_at,application_id);

CREATE TABLE economic_scenarios (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES career_tracks(id),
    schema_version TEXT NOT NULL CHECK (schema_version = 'economic-scenario@1'),
    scenario_version INTEGER NOT NULL CHECK (scenario_version > 0),
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) = 71 AND fingerprint LIKE 'sha256:%'),
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin = 'manual_user'),
    created_at TEXT NOT NULL,
    UNIQUE(track_id,scenario_version),
    UNIQUE(track_id,fingerprint)
);
CREATE INDEX idx_economic_scenarios_track
    ON economic_scenarios(track_id,scenario_version DESC,id);
CREATE TABLE economic_scenario_current (
    track_id TEXT PRIMARY KEY REFERENCES career_tracks(id),
    scenario_id TEXT NOT NULL UNIQUE REFERENCES economic_scenarios(id),
    updated_at TEXT NOT NULL
);

CREATE TABLE career_track_proposals (
    id TEXT PRIMARY KEY,
    proposal_key TEXT NOT NULL UNIQUE,
    method_version TEXT NOT NULL CHECK (method_version = 'career-intelligence@1'),
    role_family TEXT NOT NULL,
    proposed_name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('saved_for_review','accepted','dismissed')),
    evidence_json TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL CHECK (
        length(evidence_fingerprint) = 71 AND evidence_fingerprint LIKE 'sha256:%'
    ),
    accepted_track_id TEXT REFERENCES career_tracks(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX idx_career_track_proposals_state
    ON career_track_proposals(state,updated_at DESC,id);
CREATE TABLE career_track_proposal_events (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES career_track_proposals(id),
    event_type TEXT NOT NULL CHECK (event_type IN ('saved_for_review','accepted','dismissed')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);
CREATE INDEX idx_career_track_proposal_events
    ON career_track_proposal_events(proposal_id,occurred_at,id);
CREATE TRIGGER career_track_proposal_events_no_update
BEFORE UPDATE ON career_track_proposal_events BEGIN
    SELECT RAISE(ABORT, 'career Track proposal events are append-only');
END;
CREATE TRIGGER career_track_proposal_events_no_delete
BEFORE DELETE ON career_track_proposal_events BEGIN
    SELECT RAISE(ABORT, 'career Track proposal events are append-only');
END;

CREATE TABLE career_experiments (
    id TEXT PRIMARY KEY,
    track_id TEXT REFERENCES career_tracks(id),
    proposal_id TEXT REFERENCES career_track_proposals(id),
    skill_reference TEXT,
    hypothesis TEXT NOT NULL,
    title TEXT NOT NULL,
    task_definition TEXT NOT NULL,
    task_definition_version TEXT NOT NULL,
    template_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('planned','active','completed','abandoned')),
    planned_minutes INTEGER CHECK (planned_minutes IS NULL OR planned_minutes > 0),
    actual_minutes INTEGER CHECK (actual_minutes IS NULL OR actual_minutes >= 0),
    started_at TEXT,
    completed_at TEXT,
    abandoned_at TEXT,
    interest_rating INTEGER CHECK (interest_rating IS NULL OR interest_rating BETWEEN 1 AND 5),
    difficulty_rating INTEGER CHECK (difficulty_rating IS NULL OR difficulty_rating BETWEEN 1 AND 5),
    frustration_rating INTEGER CHECK (frustration_rating IS NULL OR frustration_rating BETWEEN 1 AND 5),
    confidence_change_rating INTEGER CHECK (
        confidence_change_rating IS NULL OR confidence_change_rating BETWEEN -2 AND 2
    ),
    desire_to_continue INTEGER CHECK (desire_to_continue IS NULL OR desire_to_continue IN (0,1)),
    notes TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_career_experiments_status
    ON career_experiments(status,updated_at DESC,id);
CREATE INDEX idx_career_experiments_track
    ON career_experiments(track_id,status,updated_at DESC,id);
CREATE TABLE career_experiment_events (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES career_experiments(id),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'created','updated','started','completed','abandoned','note_added','insight_applied'
    )),
    payload_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);
CREATE INDEX idx_career_experiment_events
    ON career_experiment_events(experiment_id,occurred_at,id);
CREATE TRIGGER career_experiment_events_no_update
BEFORE UPDATE ON career_experiment_events BEGIN
    SELECT RAISE(ABORT, 'career experiment events are append-only');
END;
CREATE TRIGGER career_experiment_events_no_delete
BEFORE DELETE ON career_experiment_events BEGIN
    SELECT RAISE(ABORT, 'career experiment events are append-only');
END;
CREATE TRIGGER career_experiments_completed_no_update
BEFORE UPDATE ON career_experiments WHEN OLD.status = 'completed' BEGIN
    SELECT RAISE(ABORT, 'completed career experiment observations are immutable');
END;
CREATE TRIGGER career_experiments_completed_no_delete
BEFORE DELETE ON career_experiments WHEN OLD.status = 'completed' BEGIN
    SELECT RAISE(ABORT, 'completed career experiment observations are immutable');
END;
""".strip()


MIGRATIONS = (
    Migration(1, MIGRATION_1_SQL),
    Migration(2, MIGRATION_2_SQL),
    Migration(3, MIGRATION_3_SQL, requires_backup=True),
    Migration(4, MIGRATION_4_SQL),
    Migration(5, MIGRATION_5_SQL),
    Migration(6, MIGRATION_6_SQL),
    Migration(7, MIGRATION_7_SQL, requires_backup=True, disable_foreign_keys=True),
    Migration(8, MIGRATION_8_SQL, requires_backup=True, disable_foreign_keys=True),
    Migration(9, MIGRATION_9_SQL, requires_backup=True, disable_foreign_keys=True),
    Migration(10, MIGRATION_10_SQL, requires_backup=True, disable_foreign_keys=True),
    Migration(11, MIGRATION_11_SQL, requires_backup=True, disable_foreign_keys=True),
    Migration(12, MIGRATION_12_SQL, requires_backup=True, disable_foreign_keys=True),
    Migration(13, MIGRATION_13_SQL),
)

REQUIRED_TABLES = {
    "jobhunt_schema_migrations",
    "canonical_jobs",
    "applications",
    "application_events",
    "legacy_evaluation_snapshots",
    "compatibility_settings",
    "local_storage_migrations",
    "local_storage_migration_items",
    "career_profile",
    "career_experience",
    "career_education",
    "career_certifications",
    "career_languages",
    "career_skills",
    "career_preferences",
    "career_constraints",
    "career_profile_evidence",
    "career_profile_revisions",
    "assessment_runs",
    "assessment_responses",
    "assessment_scores",
    "career_tracks",
    "track_search_profiles",
    "track_job_assignments",
    "source_definitions",
    "source_policies",
    "search_profile_sources",
    "source_listings",
    "source_listing_tracks",
    "source_listing_search_profiles",
    "raw_blobs",
    "raw_captures",
    "extraction_runs",
    "extracted_facts",
    "normalization_concepts",
    "fact_normalizations",
    "canonical_job_projections",
    "review_items",
    "human_overrides",
    "ai_extraction_attempts",
    "worker_jobs",
    "source_sync_state",
    "source_request_observations",
    "dedupe_job_keys",
    "dedupe_job_urls",
    "duplicate_candidates",
    "duplicate_candidate_events",
    "canonical_job_merges",
    "canonical_job_merge_events",
    "source_mail_sync_state",
    "source_email_messages",
    "pracuj_alert_bindings",
    "track_evaluation_policies",
    "evaluations",
    "evaluation_dimensions",
    "evaluation_findings",
    "evaluation_current",
    "source_collection_captures",
    "source_listing_collection_evidence",
    "source_query_sync_state",
    "application_attributions",
    "economic_scenarios",
    "economic_scenario_current",
    "career_track_proposals",
    "career_track_proposal_events",
    "career_experiments",
    "career_experiment_events",
}


def _ledger_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS jobhunt_schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL,
        checksum TEXT NOT NULL,
        backup_path TEXT
    )
    """


def _verified_backup(
    connection: sqlite3.Connection,
    database_path: Path,
    backup_directory: Path,
    version: int,
) -> str:
    backup_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_directory / f"jobhunt-pre-schema-{version}-{stamp}.sqlite"
    target_connection = sqlite3.connect(target)
    try:
        connection.backup(target_connection)
    finally:
        target_connection.close()
    if not target.exists() or target.stat().st_size <= 0:
        raise JobhuntError(
            "Job Hunt database backup verification failed",
            status=500,
            code="jobhunt_backup_failed",
        )
    with sqlite3.connect(target) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise JobhuntError(
                "Job Hunt database backup is not readable",
                status=500,
                code="jobhunt_backup_failed",
            )
    return str(target.relative_to(database_path.parent))


def apply_migrations(
    connection: sqlite3.Connection,
    *,
    database_path: Path,
    backup_directory: Path,
    applied_at: str,
) -> None:
    connection.execute(_ledger_sql())
    connection.commit()
    applied = {
        int(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT version, checksum FROM jobhunt_schema_migrations ORDER BY version"
        )
    }
    known = {migration.version: migration for migration in MIGRATIONS}
    if set(applied) - set(known):
        raise JobhuntError(
            "Job Hunt database schema is newer than this application",
            status=500,
            code="jobhunt_schema_newer",
        )
    for version, checksum in applied.items():
        if checksum != known[version].checksum:
            raise JobhuntError(
                "Job Hunt database migration checksum mismatch",
                status=500,
                code="jobhunt_schema_checksum_mismatch",
            )

    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        backup_path = None
        if migration.requires_backup and database_path.exists() and database_path.stat().st_size:
            backup_path = _verified_backup(
                connection, database_path, backup_directory, migration.version
            )
        safe_timestamp = applied_at.replace("'", "''")
        safe_checksum = migration.checksum.replace("'", "''")
        safe_backup = "NULL" if backup_path is None else "'" + backup_path.replace("'", "''") + "'"
        script = (
            "BEGIN IMMEDIATE;\n"
            + migration.sql
            + "\nINSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) "
            + f"VALUES({migration.version},'{safe_timestamp}','{safe_checksum}',{safe_backup});\nCOMMIT;"
        )
        try:
            if migration.disable_foreign_keys:
                connection.commit()
                connection.execute("PRAGMA foreign_keys = OFF")
            connection.executescript(script)
            if migration.disable_foreign_keys:
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise sqlite3.IntegrityError("foreign key check failed after migration")
        except sqlite3.Error as exc:
            connection.rollback()
            raise JobhuntError(
                "Job Hunt database migration failed",
                status=500,
                code="jobhunt_schema_migration_failed",
            ) from exc
        finally:
            if migration.disable_foreign_keys:
                connection.execute("PRAGMA foreign_keys = ON")


def validate_schema(connection: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not REQUIRED_TABLES.issubset(tables):
        raise JobhuntError(
            "Job Hunt database schema validation failed",
            status=500,
            code="jobhunt_schema_invalid",
        )
    latest = int(connection.execute(
        "SELECT COALESCE(MAX(version),0) FROM jobhunt_schema_migrations"
    ).fetchone()[0])
    if latest != SCHEMA_VERSION:
        raise JobhuntError(
            "Job Hunt database schema version is invalid",
            status=500,
            code="jobhunt_schema_invalid",
        )
