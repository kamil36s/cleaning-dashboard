"""Ordered, checksummed migrations for the one Language Learning database."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import sqlite3

from .errors import LanguageStorageError


SCHEMA_VERSION = 22


@dataclass(frozen=True)
class Migration:
    version: int
    sql: str

    @property
    def checksum(self) -> str:
        return "sha256:" + hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


MIGRATION_1_SQL = r"""
CREATE TABLE language_profiles (
    id TEXT PRIMARY KEY,
    language_code TEXT NOT NULL,
    locale TEXT NOT NULL,
    display_name TEXT NOT NULL,
    translation_locales_json TEXT NOT NULL DEFAULT '[]',
    analyzer_id TEXT,
    analyzer_version TEXT,
    analyzer_settings_json TEXT NOT NULL DEFAULT '{}',
    reference_provider_config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(language_code, locale)
);

CREATE TABLE vocabulary_lemmas (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    lemma_display TEXT NOT NULL,
    lemma_normalized TEXT NOT NULL,
    part_of_speech TEXT,
    canonical_key TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('MANUAL', 'ANALYZER', 'IMPORT')),
    source_id TEXT,
    source_version TEXT,
    user_notes TEXT,
    merged_into_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(language_profile_id, canonical_key),
    UNIQUE(id, language_profile_id),
    CHECK (merged_into_id IS NULL OR merged_into_id <> id),
    FOREIGN KEY (merged_into_id, language_profile_id)
        REFERENCES vocabulary_lemmas(id, language_profile_id)
);
CREATE INDEX idx_language_lemmas_lookup
    ON vocabulary_lemmas(language_profile_id, lemma_normalized, id);
CREATE INDEX idx_language_lemmas_redirect
    ON vocabulary_lemmas(merged_into_id) WHERE merged_into_id IS NOT NULL;

CREATE TABLE surface_forms (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    form_display TEXT NOT NULL,
    form_normalized TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(language_profile_id, form_normalized),
    UNIQUE(id, language_profile_id)
);
CREATE INDEX idx_language_forms_lookup
    ON surface_forms(language_profile_id, form_normalized, id);

CREATE TABLE form_lemma_links (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    form_id TEXT NOT NULL,
    lemma_id TEXT NOT NULL,
    provider_id TEXT,
    provider_version TEXT,
    morphology_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    ambiguity_state TEXT NOT NULL DEFAULT 'NOT_REPORTED'
        CHECK (ambiguity_state IN ('NOT_REPORTED', 'UNAMBIGUOUS', 'AMBIGUOUS')),
    lexical_status TEXT NOT NULL DEFAULT 'NOT_ASSESSED'
        CHECK (lexical_status IN ('NOT_ASSESSED', 'KNOWN', 'UNKNOWN')),
    mapping_provenance TEXT NOT NULL CHECK (mapping_provenance IN ('MANUAL', 'ANALYZER', 'IMPORT')),
    manual_locked INTEGER NOT NULL DEFAULT 0 CHECK (manual_locked IN (0, 1)),
    manual_provenance TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(form_id, lemma_id),
    UNIQUE(id, language_profile_id),
    CHECK (manual_locked = 0 OR (mapping_provenance = 'MANUAL' AND manual_provenance IS NOT NULL)),
    FOREIGN KEY (form_id, language_profile_id)
        REFERENCES surface_forms(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (lemma_id, language_profile_id)
        REFERENCES vocabulary_lemmas(id, language_profile_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_form_links_lemma ON form_lemma_links(lemma_id, form_id);

CREATE TABLE lemma_knowledge (
    lemma_id TEXT PRIMARY KEY REFERENCES vocabulary_lemmas(id) ON DELETE CASCADE,
    knowledge_status TEXT NOT NULL DEFAULT 'NEW'
        CHECK (knowledge_status IN ('NEW', 'LEARNING', 'KNOWN', 'MASTERED')),
    disposition TEXT NOT NULL DEFAULT 'TRACKED'
        CHECK (disposition IN ('TRACKED', 'IGNORED', 'EXCLUDED')),
    recognition INTEGER CHECK (recognition IS NULL OR recognition BETWEEN 0 AND 5),
    recall INTEGER CHECK (recall IS NULL OR recall BETWEEN 0 AND 5),
    production INTEGER CHECK (production IS NULL OR production BETWEEN 0 AND 5),
    total_exposures INTEGER NOT NULL DEFAULT 0 CHECK (total_exposures >= 0),
    first_seen_at TEXT,
    last_seen_at TEXT,
    last_review_at TEXT,
    manual_status_override INTEGER NOT NULL DEFAULT 0 CHECK (manual_status_override IN (0, 1)),
    manual_scores_override INTEGER NOT NULL DEFAULT 0 CHECK (manual_scores_override IN (0, 1)),
    manual_override_source TEXT,
    rule_version TEXT NOT NULL DEFAULT 'language-knowledge/v1',
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_language_knowledge_state
    ON lemma_knowledge(knowledge_status, disposition, updated_at, lemma_id);

CREATE TABLE knowledge_events (
    id TEXT PRIMARY KEY,
    lemma_id TEXT NOT NULL REFERENCES vocabulary_lemmas(id),
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    idempotency_key TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(source, idempotency_key)
);
CREATE INDEX idx_language_knowledge_events_lemma
    ON knowledge_events(lemma_id, created_at, id);
CREATE TRIGGER knowledge_events_no_update
BEFORE UPDATE ON knowledge_events BEGIN
    SELECT RAISE(ABORT, 'knowledge events are append-only');
END;
CREATE TRIGGER knowledge_events_no_delete
BEFORE DELETE ON knowledge_events BEGIN
    SELECT RAISE(ABORT, 'knowledge events are append-only');
END;

CREATE TABLE text_documents (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT,
    content_fingerprint TEXT NOT NULL,
    processing_state TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (processing_state IN ('DRAFT', 'ANALYZED', 'ANALYSIS_FAILED')),
    offset_unit TEXT NOT NULL DEFAULT 'UNICODE_CODE_POINT'
        CHECK (offset_unit = 'UNICODE_CODE_POINT'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id)
);
CREATE INDEX idx_language_texts_profile
    ON text_documents(language_profile_id, created_at, id);

CREATE TABLE text_sentences (
    id TEXT PRIMARY KEY,
    text_document_id TEXT NOT NULL REFERENCES text_documents(id) ON DELETE CASCADE,
    sentence_order INTEGER NOT NULL CHECK (sentence_order >= 0),
    source_start INTEGER NOT NULL CHECK (source_start >= 0),
    source_end INTEGER NOT NULL CHECK (source_end >= source_start),
    offset_unit TEXT NOT NULL CHECK (offset_unit = 'UNICODE_CODE_POINT'),
    exact_text TEXT,
    fingerprint TEXT NOT NULL,
    UNIQUE(text_document_id, sentence_order),
    UNIQUE(id, text_document_id)
);
CREATE INDEX idx_language_sentences_text
    ON text_sentences(text_document_id, sentence_order);

CREATE TABLE text_tokens (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    sentence_id TEXT,
    token_order INTEGER NOT NULL CHECK (token_order >= 0),
    surface TEXT NOT NULL,
    source_start INTEGER NOT NULL CHECK (source_start >= 0),
    source_end INTEGER NOT NULL CHECK (source_end >= source_start),
    offset_unit TEXT NOT NULL CHECK (offset_unit = 'UNICODE_CODE_POINT'),
    token_kind TEXT NOT NULL,
    normalized_lookup TEXT,
    surface_form_id TEXT,
    selected_lemma_id TEXT,
    mapping_evidence_reference TEXT,
    part_of_speech TEXT,
    morphology_json TEXT NOT NULL DEFAULT '{}',
    provider_id TEXT,
    provider_version TEXT,
    ambiguity_state TEXT NOT NULL,
    lexical_status TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    UNIQUE(text_document_id, token_order),
    UNIQUE(id, text_document_id),
    FOREIGN KEY (text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id, text_document_id)
        REFERENCES text_sentences(id, text_document_id) ON DELETE CASCADE,
    FOREIGN KEY (surface_form_id, language_profile_id)
        REFERENCES surface_forms(id, language_profile_id),
    FOREIGN KEY (selected_lemma_id, language_profile_id)
        REFERENCES vocabulary_lemmas(id, language_profile_id)
);
CREATE INDEX idx_language_tokens_text ON text_tokens(text_document_id, token_order);
CREATE INDEX idx_language_tokens_lemma ON text_tokens(selected_lemma_id, text_document_id);

CREATE TABLE analysis_runs (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    analyzer_id TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PENDING', 'COMPLETED', 'FAILED')),
    content_fingerprint TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_code TEXT,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_analysis_runs_text
    ON analysis_runs(text_document_id, created_at, id);

CREATE TABLE study_sessions (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    text_document_id TEXT,
    session_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')),
    client_session_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    active_seconds INTEGER NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(language_profile_id, client_session_id),
    UNIQUE(id, language_profile_id),
    FOREIGN KEY (text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id)
);
CREATE INDEX idx_language_sessions_profile
    ON study_sessions(language_profile_id, started_at, id);

CREATE TABLE exposure_events (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    language_profile_id TEXT NOT NULL,
    lemma_id TEXT NOT NULL,
    surface_form_id TEXT,
    text_document_id TEXT,
    sentence_id TEXT,
    token_id TEXT,
    study_session_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(language_profile_id, idempotency_key),
    FOREIGN KEY (lemma_id, language_profile_id)
        REFERENCES vocabulary_lemmas(id, language_profile_id),
    FOREIGN KEY (surface_form_id, language_profile_id)
        REFERENCES surface_forms(id, language_profile_id),
    FOREIGN KEY (text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id),
    FOREIGN KEY (sentence_id, text_document_id)
        REFERENCES text_sentences(id, text_document_id),
    FOREIGN KEY (token_id, text_document_id)
        REFERENCES text_tokens(id, text_document_id),
    FOREIGN KEY (study_session_id, language_profile_id)
        REFERENCES study_sessions(id, language_profile_id)
);
CREATE INDEX idx_language_exposures_lemma
    ON exposure_events(lemma_id, occurred_at, id);
CREATE INDEX idx_language_exposures_session
    ON exposure_events(study_session_id, occurred_at, id);
""".strip()


MIGRATION_2_SQL = r"""
CREATE TABLE language_jobs (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    job_type TEXT NOT NULL
        CHECK (job_type IN ('ANALYZE', 'REANALYSIS_PREVIEW', 'REANALYSIS_COMMIT')),
    job_version TEXT NOT NULL DEFAULT 'language.analysis-job/v1',
    analyzer_id TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    analysis_policy_version TEXT NOT NULL,
    frequency_provider_id TEXT NOT NULL,
    frequency_provider_version TEXT NOT NULL,
    coverage_policy_version TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    analysis_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    stage TEXT NOT NULL,
    progress REAL CHECK (progress IS NULL OR (progress >= 0 AND progress <= 1)),
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id),
    FOREIGN KEY (text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_jobs_queue
    ON language_jobs(state, created_at, id);
CREATE INDEX idx_language_jobs_text
    ON language_jobs(text_document_id, created_at, id);
CREATE INDEX idx_language_jobs_fingerprint
    ON language_jobs(job_type, analysis_fingerprint, state, created_at, id);
CREATE UNIQUE INDEX idx_language_jobs_one_active_fingerprint
    ON language_jobs(job_type, analysis_fingerprint)
    WHERE state IN ('QUEUED', 'RUNNING');

CREATE TABLE lemma_frequency (
    lemma_id TEXT NOT NULL,
    language_profile_id TEXT NOT NULL,
    metric TEXT NOT NULL CHECK (metric = 'ZIPF_FREQUENCY'),
    score REAL NOT NULL,
    lookup_value TEXT NOT NULL,
    match_kind TEXT NOT NULL CHECK (match_kind IN ('LEMMA', 'SURFACE')),
    provider_id TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    retrieval_version TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (lemma_id, metric, provider_id),
    FOREIGN KEY (lemma_id, language_profile_id)
        REFERENCES vocabulary_lemmas(id, language_profile_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_frequency_profile
    ON lemma_frequency(language_profile_id, provider_id, metric, score, lemma_id);

ALTER TABLE text_tokens ADD COLUMN resolution_state TEXT NOT NULL DEFAULT 'NOT_APPLICABLE'
    CHECK (resolution_state IN ('MODEL_SELECTED', 'AMBIGUOUS', 'UNRESOLVED', 'NOT_APPLICABLE'));
ALTER TABLE text_tokens ADD COLUMN confidence_basis TEXT;
ALTER TABLE text_tokens ADD COLUMN provenance TEXT;

ALTER TABLE analysis_runs ADD COLUMN job_id TEXT REFERENCES language_jobs(id);
ALTER TABLE analysis_runs ADD COLUMN analysis_fingerprint TEXT;
ALTER TABLE analysis_runs ADD COLUMN analysis_policy_version TEXT;
ALTER TABLE analysis_runs ADD COLUMN frequency_provider_id TEXT;
ALTER TABLE analysis_runs ADD COLUMN frequency_provider_version TEXT;
ALTER TABLE analysis_runs ADD COLUMN coverage_policy_version TEXT;
CREATE INDEX idx_language_analysis_runs_fingerprint
    ON analysis_runs(text_document_id, analysis_fingerprint, state, created_at, id);
""".strip()


MIGRATION_3_SQL = r"""
ALTER TABLE study_sessions ADD COLUMN activity_state TEXT NOT NULL DEFAULT 'PAUSED'
    CHECK (activity_state IN ('ACTIVE', 'PAUSED'));
ALTER TABLE study_sessions ADD COLUMN last_heartbeat_at TEXT;
ALTER TABLE study_sessions ADD COLUMN last_active_at TEXT;
ALTER TABLE study_sessions ADD COLUMN last_command_id TEXT;

ALTER TABLE exposure_events ADD COLUMN batch_idempotency_key TEXT;
CREATE INDEX idx_language_exposures_batch
    ON exposure_events(language_profile_id, batch_idempotency_key);

CREATE TABLE text_reading_progress (
    text_document_id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (status IN ('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED')),
    progress_source_offset INTEGER NOT NULL DEFAULT 0 CHECK (progress_source_offset >= 0),
    progress_sentence_id TEXT,
    last_read_at TEXT,
    completed_at TEXT,
    coverage_snapshot_json TEXT,
    analysis_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(text_document_id, language_profile_id),
    FOREIGN KEY (text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (progress_sentence_id, text_document_id)
        REFERENCES text_sentences(id, text_document_id),
    FOREIGN KEY (analysis_run_id)
        REFERENCES analysis_runs(id)
);
CREATE INDEX idx_language_reading_progress_profile
    ON text_reading_progress(language_profile_id, last_read_at, text_document_id);
""".strip()


MIGRATION_4_SQL = r"""
CREATE TABLE topics (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    parent_topic_id TEXT,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(language_profile_id, slug),
    UNIQUE(id, language_profile_id),
    CHECK (parent_topic_id IS NULL OR parent_topic_id <> id),
    FOREIGN KEY (parent_topic_id, language_profile_id)
        REFERENCES topics(id, language_profile_id)
);
CREATE INDEX idx_language_topics_profile
    ON topics(language_profile_id, archived, display_name, id);

CREATE TABLE topic_lemmas (
    topic_id TEXT NOT NULL,
    lemma_id TEXT NOT NULL,
    language_profile_id TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1 CHECK (weight > 0 AND weight <= 10),
    provenance TEXT NOT NULL CHECK (provenance IN ('MANUAL', 'IMPORT')),
    membership_state TEXT NOT NULL CHECK (membership_state IN ('MANUAL', 'IMPORTED')),
    source_reference TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, lemma_id),
    FOREIGN KEY (topic_id, language_profile_id)
        REFERENCES topics(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (lemma_id, language_profile_id)
        REFERENCES vocabulary_lemmas(id, language_profile_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_topic_lemmas_lemma
    ON topic_lemmas(lemma_id, topic_id);

CREATE TABLE goal_definitions (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    metric TEXT NOT NULL CHECK (metric IN (
        'NEW_WORDS', 'ACTIVE_READING_MINUTES', 'TEXTS_COMPLETED', 'READER_EXPOSURES'
    )),
    period TEXT NOT NULL CHECK (period IN ('WEEK')),
    target_value REAL NOT NULL CHECK (target_value > 0),
    unit TEXT NOT NULL CHECK (unit IN ('WORDS', 'MINUTES', 'TEXTS', 'EXPOSURES')),
    active_from TEXT,
    active_until TEXT,
    week_start INTEGER NOT NULL DEFAULT 1 CHECK (week_start BETWEEN 1 AND 7),
    timezone TEXT NOT NULL DEFAULT 'Europe/Warsaw',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    rule_version TEXT NOT NULL DEFAULT 'language.goals/v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id)
);
CREATE INDEX idx_language_goals_profile
    ON goal_definitions(language_profile_id, enabled, metric, id);
""".strip()


MIGRATION_5_SQL = r"""
ALTER TABLE language_profiles ADD COLUMN anki_config_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE anki_note_links (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL,
    lemma_id TEXT NOT NULL,
    template_purpose TEXT NOT NULL,
    external_note_id INTEGER NOT NULL,
    deck_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dashboard_key TEXT NOT NULL,
    source_document_id TEXT,
    source_sentence_id TEXT,
    last_pushed_hash TEXT,
    last_pulled_hash TEXT,
    last_local_fields_json TEXT NOT NULL DEFAULT '{}',
    last_remote_fields_json TEXT NOT NULL DEFAULT '{}',
    conflict_state TEXT NOT NULL DEFAULT 'NONE'
        CHECK (conflict_state IN ('NONE', 'LOCAL_CHANGED', 'REMOTE_CHANGED', 'BOTH_CHANGED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_sync_at TEXT,
    UNIQUE(lemma_id, template_purpose),
    UNIQUE(external_note_id),
    UNIQUE(dashboard_key),
    UNIQUE(id, language_profile_id),
    FOREIGN KEY (lemma_id, language_profile_id)
        REFERENCES vocabulary_lemmas(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (source_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id),
    FOREIGN KEY (source_sentence_id, source_document_id)
        REFERENCES text_sentences(id, text_document_id)
);
CREATE INDEX idx_language_anki_links_profile
    ON anki_note_links(language_profile_id, conflict_state, updated_at, id);

CREATE TABLE anki_card_snapshots (
    external_card_id INTEGER PRIMARY KEY,
    note_link_id TEXT NOT NULL REFERENCES anki_note_links(id) ON DELETE CASCADE,
    external_note_id INTEGER NOT NULL,
    deck_name TEXT,
    queue INTEGER,
    card_type INTEGER,
    due INTEGER,
    interval INTEGER,
    ease INTEGER,
    reviews INTEGER,
    lapses INTEGER,
    observed_at TEXT NOT NULL,
    raw_supported_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_language_anki_cards_link
    ON anki_card_snapshots(note_link_id, observed_at, external_card_id);

CREATE TABLE anki_sync_runs (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('TEST', 'PUSH', 'PULL', 'LINK')),
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')),
    counts_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]',
    capability_snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX idx_language_anki_runs_profile
    ON anki_sync_runs(language_profile_id, started_at DESC, id);
""".strip()


MIGRATION_6_SQL = r"""
CREATE TABLE generation_requests (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    topic_id TEXT,
    custom_topic TEXT,
    requested_length INTEGER NOT NULL CHECK (requested_length BETWEEN 50 AND 5000),
    requested_token_coverage REAL NOT NULL CHECK (requested_token_coverage BETWEEN 50 AND 100),
    difficulty_preset TEXT NOT NULL CHECK (difficulty_preset IN ('VERY_EASY','EASY','BALANCED','CHALLENGING')),
    explicit_target_lemma_ids_json TEXT NOT NULL DEFAULT '[]',
    grammar_focus TEXT,
    style_instruction TEXT,
    selection_rule_version TEXT NOT NULL,
    coverage_policy_version TEXT NOT NULL,
    knowledge_snapshot_fingerprint TEXT NOT NULL,
    knowledge_snapshot_json TEXT NOT NULL,
    target_snapshot_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_fingerprint TEXT NOT NULL,
    context_pack_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'READY' CHECK (status IN ('READY','HAS_CANDIDATES','ACCEPTED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id),
    FOREIGN KEY (topic_id, language_profile_id)
        REFERENCES topics(id, language_profile_id)
);
CREATE INDEX idx_language_generation_requests_profile
    ON generation_requests(language_profile_id, created_at DESC, id);

CREATE TABLE generation_candidates (
    id TEXT PRIMARY KEY,
    generation_request_id TEXT NOT NULL REFERENCES generation_requests(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    source TEXT NOT NULL CHECK (source = 'MANUAL_EXTERNAL_LLM'),
    provider_label TEXT,
    model_label TEXT,
    raw_response TEXT NOT NULL,
    import_format TEXT NOT NULL CHECK (import_format IN ('JSON','PLAIN_TEXT')),
    title TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK (validation_status IN ('VALID','INVALID')),
    status TEXT NOT NULL CHECK (status IN ('IMPORTED','QUEUED','ANALYZING','IN_TOLERANCE','OUT_OF_TOLERANCE','REJECTED','ACCEPTED','FAILED')),
    analysis_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (analysis_attempt_count >= 0),
    analysis_json TEXT,
    analyzer_id TEXT,
    analyzer_version TEXT,
    accepted_text_document_id TEXT REFERENCES text_documents(id),
    accepted_analysis_job_id TEXT REFERENCES language_jobs(id),
    rejection_reason TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    analyzed_at TEXT,
    accepted_at TEXT,
    rejected_at TEXT,
    UNIQUE(generation_request_id, attempt_number)
);
CREATE INDEX idx_language_generation_candidates_queue
    ON generation_candidates(status, created_at, id);
CREATE INDEX idx_language_generation_candidates_request
    ON generation_candidates(generation_request_id, attempt_number DESC, id);
""".strip()


MIGRATION_7_SQL = r"""
CREATE TABLE cloze_sessions (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('FAST_TRACK','RECYCLE_MISTAKES')),
    track_key TEXT NOT NULL,
    track_version TEXT NOT NULL,
    requested_item_count INTEGER NOT NULL CHECK (requested_item_count IN (10,20,50)),
    seed TEXT NOT NULL,
    items_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','COMPLETED','CANCELLED')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id)
);
CREATE INDEX idx_language_cloze_sessions_profile
    ON cloze_sessions(language_profile_id, started_at DESC, id);

CREATE TABLE cloze_attempts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cloze_sessions(id) ON DELETE CASCADE,
    item_index INTEGER NOT NULL CHECK (item_index >= 0),
    target_lemma_id TEXT NOT NULL REFERENCES vocabulary_lemmas(id),
    reference_target_stable_key TEXT NOT NULL,
    reference_sentence_source TEXT NOT NULL,
    reference_sentence_id TEXT NOT NULL,
    item_snapshot_json TEXT NOT NULL,
    item_fingerprint TEXT NOT NULL,
    expected_surface_form TEXT NOT NULL,
    options_json TEXT NOT NULL,
    chosen_option TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('CORRECT','INCORRECT','REVEALED','SKIPPED')),
    response_ms INTEGER NOT NULL CHECK (response_ms BETWEEN 0 AND 600000),
    idempotency_key TEXT NOT NULL UNIQUE,
    attempted_at TEXT NOT NULL,
    rule_versions_json TEXT NOT NULL,
    UNIQUE(session_id, item_index)
);
CREATE INDEX idx_language_cloze_attempts_target
    ON cloze_attempts(reference_target_stable_key, attempted_at DESC, id);
CREATE INDEX idx_language_cloze_attempts_lemma
    ON cloze_attempts(target_lemma_id, attempted_at DESC, id);
CREATE INDEX idx_language_cloze_attempts_session
    ON cloze_attempts(session_id, item_index);

CREATE TABLE cloze_item_suppressions (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    reference_target_stable_key TEXT NOT NULL,
    reference_sentence_source TEXT NOT NULL,
    reference_sentence_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('AMBIGUOUS_ANSWER','UNNATURAL_SENTENCE','BAD_DISTRACTORS','OTHER')),
    created_at TEXT NOT NULL,
    UNIQUE(language_profile_id, reference_target_stable_key, reference_sentence_source, reference_sentence_id)
);
CREATE INDEX idx_language_cloze_suppressions_profile
    ON cloze_item_suppressions(language_profile_id, reference_target_stable_key, reference_sentence_id);
""".strip()


MIGRATION_8_SQL = r"""
CREATE TABLE cloze_sentence_audio (
    cache_key TEXT PRIMARY KEY CHECK (length(cache_key) = 64),
    reference_sentence_source TEXT NOT NULL,
    reference_sentence_id TEXT NOT NULL,
    sentence_text TEXT NOT NULL,
    audio_path TEXT NOT NULL UNIQUE,
    language_code TEXT NOT NULL,
    provider TEXT NOT NULL,
    voice_id TEXT NOT NULL,
    audio_encoding TEXT NOT NULL,
    text_hash TEXT NOT NULL CHECK (length(text_hash) = 64),
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_language_cloze_audio_sentence
    ON cloze_sentence_audio(reference_sentence_source, reference_sentence_id, created_at DESC);
""".strip()


MIGRATION_9_SQL = r"""
CREATE TABLE gamification_awards (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reward_key TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    xp_amount INTEGER NOT NULL CHECK (xp_amount > 0),
    awarded_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(language_profile_id, source_type, source_id, reward_key, rule_version)
);
CREATE INDEX idx_language_gamification_awards_profile
    ON gamification_awards(language_profile_id, awarded_at, id);

CREATE TABLE achievement_unlocks (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    achievement_key TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    unlocked_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(language_profile_id, achievement_key, definition_version)
);
CREATE INDEX idx_language_achievement_unlocks_profile
    ON achievement_unlocks(language_profile_id, unlocked_at DESC, id);

CREATE TABLE gamification_quest_snapshots (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    local_study_date TEXT NOT NULL,
    timezone TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    canonical_fingerprint TEXT NOT NULL,
    quests_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(language_profile_id, local_study_date, rule_version)
);
CREATE INDEX idx_language_quest_snapshots_profile
    ON gamification_quest_snapshots(language_profile_id, local_study_date DESC, id);

CREATE TABLE campaign_definitions (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    target_date TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    milestones_json TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id)
);
CREATE INDEX idx_language_campaigns_profile
    ON campaign_definitions(language_profile_id, enabled, target_date, id);
""".strip()


MIGRATION_10_SQL = r"""
CREATE TABLE user_lemma_translations (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    lemma_id TEXT NOT NULL REFERENCES vocabulary_lemmas(id) ON DELETE CASCADE,
    target_locale TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(lemma_id, target_locale)
);
CREATE INDEX idx_language_user_translations_profile
    ON user_lemma_translations(language_profile_id, target_locale, lemma_id);

CREATE TABLE phrasebook_entries (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    expression_text TEXT NOT NULL,
    expression_normalized TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('READER','CLOZE','GENERATED','MANUAL')),
    source_entity_id TEXT,
    source_context TEXT,
    source_provenance_json TEXT NOT NULL DEFAULT '{}',
    source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint) = 64),
    note TEXT,
    user_translation TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(language_profile_id, expression_normalized, source_type, source_fingerprint)
);
CREATE INDEX idx_language_phrasebook_profile
    ON phrasebook_entries(language_profile_id, updated_at DESC, id);
CREATE INDEX idx_language_phrasebook_search
    ON phrasebook_entries(language_profile_id, expression_normalized, id);

CREATE TABLE phrasebook_entry_links (
    entry_id TEXT NOT NULL REFERENCES phrasebook_entries(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL CHECK (link_type IN ('LEMMA','REFERENCE_UNIT','TOKEN_SPAN')),
    link_value TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY(entry_id, link_type, link_value)
);
CREATE INDEX idx_language_phrasebook_links_value
    ON phrasebook_entry_links(link_type, link_value, entry_id);
""".strip()


MIGRATION_11_SQL = r"""
ALTER TABLE generation_requests ADD COLUMN generation_mode TEXT NOT NULL DEFAULT 'MANUAL';
ALTER TABLE generation_requests ADD COLUMN provider_id TEXT;
ALTER TABLE generation_requests ADD COLUMN provider_adapter_version TEXT;
ALTER TABLE generation_requests ADD COLUMN model_id TEXT;
ALTER TABLE generation_requests ADD COLUMN provider_policy TEXT;
ALTER TABLE generation_requests ADD COLUMN max_provider_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE generation_requests ADD COLUMN automatic_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED';
ALTER TABLE generation_requests ADD COLUMN automatic_stage TEXT;
ALTER TABLE generation_requests ADD COLUMN automatic_progress REAL;
ALTER TABLE generation_requests ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0;
ALTER TABLE generation_requests ADD COLUMN best_candidate_id TEXT;
ALTER TABLE generation_requests ADD COLUMN automatic_error_code TEXT;
ALTER TABLE generation_requests ADD COLUMN automatic_error_message TEXT;
ALTER TABLE generation_requests ADD COLUMN automatic_usage_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE generation_requests ADD COLUMN context_preparation_ms REAL;
ALTER TABLE generation_requests ADD COLUMN revision_preparation_ms REAL;
ALTER TABLE generation_requests ADD COLUMN automatic_started_at TEXT;
ALTER TABLE generation_requests ADD COLUMN automatic_completed_at TEXT;

ALTER TABLE generation_candidates ADD COLUMN origin_mode TEXT NOT NULL DEFAULT 'MANUAL';
ALTER TABLE generation_candidates ADD COLUMN provider_request_id TEXT;
ALTER TABLE generation_candidates ADD COLUMN provider_model_version TEXT;
ALTER TABLE generation_candidates ADD COLUMN finish_reason TEXT;
ALTER TABLE generation_candidates ADD COLUMN usage_metadata_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE generation_candidates ADD COLUMN provider_latency_ms REAL;
ALTER TABLE generation_candidates ADD COLUMN transport_attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE generation_candidates ADD COLUMN provider_status TEXT;
ALTER TABLE generation_candidates ADD COLUMN error_class TEXT;
ALTER TABLE generation_candidates ADD COLUMN revision_prompt_fingerprint TEXT;

CREATE INDEX idx_language_generation_requests_automatic
    ON generation_requests(automatic_status, created_at, id);

CREATE TABLE generated_text_sentence_audio (
    text_document_id TEXT NOT NULL REFERENCES text_documents(id) ON DELETE CASCADE,
    sentence_id TEXT NOT NULL,
    cache_key TEXT NOT NULL REFERENCES cloze_sentence_audio(cache_key) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(text_document_id, sentence_id, cache_key),
    FOREIGN KEY(sentence_id, text_document_id)
        REFERENCES text_sentences(id, text_document_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_generated_audio_sentence
    ON generated_text_sentence_audio(text_document_id, sentence_id, created_at DESC);
""".strip()


MIGRATION_12_SQL = r"""
ALTER TABLE cloze_sessions ADD COLUMN practice_mode TEXT NOT NULL DEFAULT 'FAST_TRACK';
ALTER TABLE cloze_sessions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'MULTIPLE_CHOICE';
ALTER TABLE cloze_sessions ADD COLUMN selection_policy_version TEXT NOT NULL DEFAULT 'language.cloze-target-selection/v1';
ALTER TABLE cloze_sessions ADD COLUMN source_policy_version TEXT NOT NULL DEFAULT 'language.cloze-sentence-selection/v2';
ALTER TABLE cloze_sessions ADD COLUMN curriculum_snapshot_json TEXT;
UPDATE cloze_sessions SET practice_mode=mode;

ALTER TABLE cloze_attempts ADD COLUMN question_type TEXT NOT NULL DEFAULT 'MULTIPLE_CHOICE';
ALTER TABLE cloze_attempts ADD COLUMN source_context_type TEXT NOT NULL DEFAULT 'TATOEBA';
ALTER TABLE cloze_attempts ADD COLUMN normalization_version TEXT NOT NULL DEFAULT 'language.cloze-answer-normalization/legacy-multiple-choice-v1';
ALTER TABLE cloze_attempts ADD COLUMN user_answer TEXT;
ALTER TABLE cloze_attempts ADD COLUMN normalized_answer TEXT;

ALTER TABLE cloze_item_suppressions RENAME TO cloze_item_suppressions_phase9a;
CREATE TABLE cloze_item_suppressions (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    reference_target_stable_key TEXT NOT NULL,
    reference_sentence_source TEXT NOT NULL,
    reference_sentence_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN (
        'WRONG_ANSWER','AMBIGUOUS_ANSWER','MULTIPLE_VALID_ANSWERS','UNNATURAL_SENTENCE',
        'BAD_DISTRACTORS','BAD_SENTENCE','BAD_MAPPING','UNNATURAL_GENERATED_CONTEXT','OTHER'
    )),
    created_at TEXT NOT NULL,
    source_context_type TEXT NOT NULL DEFAULT 'TATOEBA',
    UNIQUE(language_profile_id, reference_target_stable_key, reference_sentence_source, reference_sentence_id)
);
INSERT INTO cloze_item_suppressions(
    id,language_profile_id,reference_target_stable_key,reference_sentence_source,
    reference_sentence_id,reason,created_at,source_context_type
)
SELECT id,language_profile_id,reference_target_stable_key,reference_sentence_source,
       reference_sentence_id,reason,created_at,'TATOEBA'
FROM cloze_item_suppressions_phase9a;
DROP TABLE cloze_item_suppressions_phase9a;
CREATE INDEX idx_language_cloze_suppressions_profile
    ON cloze_item_suppressions(language_profile_id, reference_target_stable_key, reference_sentence_id);

CREATE INDEX idx_language_cloze_attempts_profile_source
    ON cloze_attempts(source_context_type, attempted_at DESC, id);
CREATE INDEX idx_language_cloze_sessions_practice
    ON cloze_sessions(language_profile_id, practice_mode, started_at DESC, id);
""".strip()


MIGRATION_13_SQL = r"""
CREATE TABLE listening_sessions (
    study_session_id TEXT PRIMARY KEY REFERENCES study_sessions(id) ON DELETE CASCADE,
    language_profile_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('READ_LISTEN', 'LISTENING_ONLY')),
    activity_policy_version TEXT NOT NULL,
    exposure_policy_version TEXT NOT NULL,
    completion_policy_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(study_session_id, language_profile_id),
    FOREIGN KEY(study_session_id, language_profile_id)
        REFERENCES study_sessions(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY(text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_listening_sessions_profile
    ON listening_sessions(language_profile_id, started_at, study_session_id);
CREATE INDEX idx_language_listening_sessions_text
    ON listening_sessions(text_document_id, started_at, study_session_id);

CREATE TABLE listening_sentence_events (
    id TEXT PRIMARY KEY,
    study_session_id TEXT NOT NULL,
    language_profile_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('ENDED', 'CANCELLED', 'ERROR')),
    playback_source TEXT NOT NULL CHECK (playback_source IN ('BROWSER_TTS', 'CLOUD_TTS')),
    active_ms INTEGER NOT NULL CHECK (active_ms >= 0 AND active_ms <= 600000),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR (duration_ms > 0 AND duration_ms <= 600000)),
    completion_ratio REAL NOT NULL CHECK (completion_ratio >= 0 AND completion_ratio <= 1),
    qualified INTEGER NOT NULL CHECK (qualified IN (0, 1)),
    exposure_awarded INTEGER NOT NULL CHECK (exposure_awarded IN (0, 1)),
    local_study_date TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(study_session_id, idempotency_key),
    FOREIGN KEY(study_session_id, language_profile_id)
        REFERENCES listening_sessions(study_session_id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY(text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY(sentence_id, text_document_id)
        REFERENCES text_sentences(id, text_document_id) ON DELETE CASCADE
);
CREATE INDEX idx_language_listening_events_profile
    ON listening_sentence_events(language_profile_id, occurred_at, id);
CREATE INDEX idx_language_listening_events_text
    ON listening_sentence_events(text_document_id, sentence_id, occurred_at, id);
CREATE UNIQUE INDEX idx_language_listening_exposure_daily_bound
    ON listening_sentence_events(language_profile_id, text_document_id, sentence_id, local_study_date)
    WHERE exposure_awarded = 1;

CREATE TABLE listening_progress (
    language_profile_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    current_sentence_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('IN_PROGRESS', 'COMPLETED')),
    policy_version TEXT NOT NULL,
    last_listened_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(language_profile_id, text_document_id),
    FOREIGN KEY(text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY(current_sentence_id, text_document_id)
        REFERENCES text_sentences(id, text_document_id)
);
CREATE INDEX idx_language_listening_progress_profile
    ON listening_progress(language_profile_id, last_listened_at DESC, text_document_id);

ALTER TABLE goal_definitions RENAME TO goal_definitions_phase12;
CREATE TABLE goal_definitions (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    metric TEXT NOT NULL CHECK (metric IN (
        'NEW_WORDS', 'ACTIVE_READING_MINUTES', 'TEXTS_COMPLETED', 'READER_EXPOSURES',
        'LISTENING_ACTIVE_MINUTES', 'LISTENING_SESSIONS', 'LISTENING_TEXTS_COMPLETED'
    )),
    period TEXT NOT NULL CHECK (period IN ('WEEK')),
    target_value REAL NOT NULL CHECK (target_value > 0),
    unit TEXT NOT NULL CHECK (unit IN ('WORDS', 'MINUTES', 'TEXTS', 'EXPOSURES', 'SESSIONS')),
    active_from TEXT,
    active_until TEXT,
    week_start INTEGER NOT NULL DEFAULT 1 CHECK (week_start BETWEEN 1 AND 7),
    timezone TEXT NOT NULL DEFAULT 'Europe/Warsaw',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    rule_version TEXT NOT NULL DEFAULT 'language.goals/v2',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id)
);
INSERT INTO goal_definitions(
    id,language_profile_id,metric,period,target_value,unit,active_from,active_until,
    week_start,timezone,enabled,rule_version,created_at,updated_at
)
SELECT id,language_profile_id,metric,period,target_value,unit,active_from,active_until,
       week_start,timezone,enabled,rule_version,created_at,updated_at
FROM goal_definitions_phase12;
DROP TABLE goal_definitions_phase12;
CREATE INDEX idx_language_goals_profile
    ON goal_definitions(language_profile_id, enabled, metric, id);
""".strip()


MIGRATION_14_SQL = r"""
CREATE TABLE content_items (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    content_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    source_name TEXT,
    author_publisher TEXT,
    language_code TEXT NOT NULL DEFAULT 'nb',
    rights_status TEXT NOT NULL CHECK (rights_status IN (
        'USER_PROVIDED_STORAGE_ALLOWED','USER_OWNED_STORAGE_ALLOWED','LICENSED_STORAGE_ALLOWED',
        'REFERENCE_ONLY','STORAGE_NOT_AUTHORIZED','UNKNOWN_RIGHTS'
    )),
    license TEXT,
    attribution TEXT,
    retention_policy TEXT NOT NULL,
    rights_policy_version TEXT NOT NULL,
    ingestion_policy_version TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'IMPORTED','ANALYZING','READY_READER','NEEDS_TRANSCRIPT','NEEDS_ALIGNMENT',
        'ALIGNING','READY_LISTENING','REFERENCE_ONLY','FAILED','UNSUPPORTED'
    )),
    text_document_id TEXT REFERENCES text_documents(id),
    media_artifact_id TEXT,
    current_transcript_id TEXT,
    user_notes TEXT,
    created_at TEXT NOT NULL,
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id)
);
CREATE UNIQUE INDEX idx_language_content_fingerprint
    ON content_items(language_profile_id, source_type, content_fingerprint);
CREATE INDEX idx_language_content_profile
    ON content_items(language_profile_id, added_at DESC, id);

CREATE TABLE content_artifacts (
    id TEXT PRIMARY KEY,
    content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('AUDIO')),
    original_display_name TEXT NOT NULL,
    managed_relpath TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 67108864),
    checksum TEXT NOT NULL,
    storage_policy TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(content_id, artifact_type)
);
CREATE INDEX idx_language_content_artifact_checksum ON content_artifacts(checksum, id);

CREATE TABLE transcripts (
    id TEXT PRIMARY KEY,
    content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    text_document_id TEXT NOT NULL REFERENCES text_documents(id),
    version INTEGER NOT NULL CHECK (version > 0),
    source_type TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('PLAIN','SRT','VTT')),
    source_fingerprint TEXT NOT NULL,
    method TEXT NOT NULL,
    confidence_basis TEXT NOT NULL,
    edit_state TEXT NOT NULL CHECK (edit_state IN ('ORIGINAL','USER_EDITED')),
    attribution TEXT,
    segmentation_version TEXT NOT NULL,
    is_current INTEGER NOT NULL CHECK (is_current IN (0,1)),
    created_at TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE(content_id, version),
    UNIQUE(content_id, source_fingerprint)
);
CREATE UNIQUE INDEX idx_language_transcript_current
    ON transcripts(content_id) WHERE is_current=1;
CREATE INDEX idx_language_transcript_text ON transcripts(text_document_id, version);

CREATE TABLE transcript_cues (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    cue_order INTEGER NOT NULL CHECK (cue_order >= 0),
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    cue_text TEXT NOT NULL,
    source_identifier TEXT,
    text_start INTEGER NOT NULL CHECK (text_start >= 0),
    text_end INTEGER NOT NULL CHECK (text_end >= text_start),
    created_at TEXT NOT NULL,
    UNIQUE(transcript_id, cue_order)
);
CREATE INDEX idx_language_transcript_cues_time ON transcript_cues(transcript_id, start_ms, end_ms);

CREATE TABLE sentence_alignments (
    id TEXT PRIMARY KEY,
    content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    text_document_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    source_start_ms INTEGER,
    source_end_ms INTEGER,
    method TEXT NOT NULL CHECK (method IN ('SOURCE_TIMESTAMPS','IMPORTED_SRT','IMPORTED_VTT','FORCED_ALIGNMENT','MANUAL','USER_CORRECTED')),
    policy_version TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    confidence_basis TEXT NOT NULL,
    exposure_eligible INTEGER NOT NULL CHECK (exposure_eligible IN (0,1)),
    source_cue_ids_json TEXT NOT NULL DEFAULT '[]',
    supersedes_alignment_id TEXT REFERENCES sentence_alignments(id),
    is_current INTEGER NOT NULL CHECK (is_current IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(sentence_id, text_document_id) REFERENCES text_sentences(id, text_document_id) ON DELETE CASCADE,
    UNIQUE(transcript_id, sentence_id, version)
);
CREATE UNIQUE INDEX idx_language_alignment_current
    ON sentence_alignments(transcript_id, sentence_id) WHERE is_current=1;
CREATE INDEX idx_language_alignment_timeline
    ON sentence_alignments(content_id, is_current, start_ms, end_ms);

ALTER TABLE listening_sentence_events RENAME TO listening_sentence_events_v13;
CREATE TABLE listening_sentence_events (
    id TEXT PRIMARY KEY,
    study_session_id TEXT NOT NULL,
    language_profile_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('ENDED', 'CANCELLED', 'ERROR')),
    playback_source TEXT NOT NULL CHECK (playback_source IN ('BROWSER_TTS', 'CLOUD_TTS', 'AUTHENTIC_MEDIA')),
    active_ms INTEGER NOT NULL CHECK (active_ms >= 0 AND active_ms <= 600000),
    coverage_ms INTEGER NOT NULL CHECK (coverage_ms >= 0 AND coverage_ms <= 600000),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR (duration_ms > 0 AND duration_ms <= 600000)),
    completion_ratio REAL NOT NULL CHECK (completion_ratio >= 0 AND completion_ratio <= 1),
    qualified INTEGER NOT NULL CHECK (qualified IN (0, 1)),
    exposure_awarded INTEGER NOT NULL CHECK (exposure_awarded IN (0, 1)),
    alignment_id TEXT REFERENCES sentence_alignments(id),
    local_study_date TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(study_session_id, idempotency_key),
    FOREIGN KEY(study_session_id, language_profile_id)
        REFERENCES listening_sessions(study_session_id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY(text_document_id, language_profile_id)
        REFERENCES text_documents(id, language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY(sentence_id, text_document_id)
        REFERENCES text_sentences(id, text_document_id) ON DELETE CASCADE
);
INSERT INTO listening_sentence_events(
    id,study_session_id,language_profile_id,text_document_id,sentence_id,idempotency_key,
    outcome,playback_source,active_ms,coverage_ms,duration_ms,completion_ratio,qualified,
    exposure_awarded,alignment_id,local_study_date,occurred_at,metadata_json,created_at
)
SELECT id,study_session_id,language_profile_id,text_document_id,sentence_id,idempotency_key,
       outcome,playback_source,active_ms,active_ms,duration_ms,completion_ratio,qualified,
       exposure_awarded,NULL,local_study_date,occurred_at,metadata_json,created_at
FROM listening_sentence_events_v13;
DROP TABLE listening_sentence_events_v13;
CREATE INDEX idx_language_listening_events_profile
    ON listening_sentence_events(language_profile_id, occurred_at, id);
CREATE INDEX idx_language_listening_events_text
    ON listening_sentence_events(text_document_id, sentence_id, occurred_at, id);
CREATE UNIQUE INDEX idx_language_listening_exposure_daily_bound
    ON listening_sentence_events(language_profile_id, text_document_id, sentence_id, local_study_date)
    WHERE exposure_awarded = 1;
""".strip()


MIGRATION_15_SQL = r"""
ALTER TABLE language_jobs ADD COLUMN analysis_domain TEXT NOT NULL DEFAULT 'TEXT'
    CHECK (analysis_domain IN ('TEXT','GRAMMAR'));
CREATE TABLE grammar_analysis_runs (
    id TEXT PRIMARY KEY REFERENCES language_jobs(id),
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id),
    text_document_id TEXT NOT NULL REFERENCES text_documents(id),
    canonical_analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id),
    parser_provenance_json TEXT NOT NULL,
    analyzer_provenance_json TEXT NOT NULL,
    source_provenance_json TEXT NOT NULL,
    registry_json TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_grammar_runs_text ON grammar_analysis_runs(text_document_id,created_at,id);
CREATE TABLE grammar_occurrences (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES grammar_analysis_runs(id),
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id),
    text_document_id TEXT NOT NULL REFERENCES text_documents(id),
    sentence_id TEXT NOT NULL REFERENCES text_sentences(id),
    pattern_id TEXT NOT NULL,
    pattern_version TEXT NOT NULL,
    detector_id TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    support_status TEXT NOT NULL CHECK(support_status IN ('SUPPORTED','EXPERIMENTAL')),
    evidence_status TEXT NOT NULL,
    source_start INTEGER NOT NULL,
    source_end INTEGER NOT NULL CHECK(source_end > source_start),
    evidence_json TEXT NOT NULL,
    semantic_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id,semantic_key)
);
CREATE INDEX idx_grammar_occurrences_profile ON grammar_occurrences(language_profile_id,pattern_id,run_id);
CREATE INDEX idx_grammar_occurrences_semantic ON grammar_occurrences(language_profile_id,semantic_key);
CREATE TABLE grammar_occurrence_reviews (
    id TEXT PRIMARY KEY,
    occurrence_id TEXT NOT NULL REFERENCES grammar_occurrences(id),
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id),
    semantic_key TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('CONFIRMED','REJECTED','UNREVIEWED')),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_grammar_reviews_semantic ON grammar_occurrence_reviews(language_profile_id,semantic_key,created_at,id);
""".strip()

MIGRATION_16_SQL = r"""
CREATE TABLE benchmark_runs (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id),
    kind TEXT NOT NULL CHECK(kind IN ('BASELINE','CHECKPOINT')),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','COMPLETED')),
    benchmark_family_id TEXT NOT NULL,
    benchmark_version INTEGER NOT NULL,
    form_id TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    selected_item_ids_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    scores_json TEXT,
    comparison_json TEXT
);
CREATE INDEX idx_benchmark_runs_profile ON benchmark_runs(language_profile_id,started_at,id);
CREATE TABLE benchmark_responses (
    run_id TEXT NOT NULL REFERENCES benchmark_runs(id),
    item_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    response_json TEXT NOT NULL,
    environment_json TEXT,
    answered_at TEXT NOT NULL,
    PRIMARY KEY(run_id,item_id)
);
""".strip()

MIGRATION_17_SQL = r"""
CREATE TABLE reader_sentence_translations (
    sentence_id TEXT NOT NULL,
    text_document_id TEXT NOT NULL,
    target_language TEXT NOT NULL CHECK (target_language IN ('en','pl')),
    source_hash TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(sentence_id,target_language),
    FOREIGN KEY (sentence_id,text_document_id)
        REFERENCES text_sentences(id,text_document_id) ON DELETE CASCADE
);
CREATE INDEX idx_reader_sentence_translations_text
    ON reader_sentence_translations(text_document_id,target_language,sentence_id);
""".strip()

MIGRATION_18_SQL = r"""
CREATE TABLE anki_daily_plans (
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    local_day TEXT NOT NULL,
    deck_name TEXT NOT NULL,
    planned_new INTEGER NOT NULL CHECK (planned_new >= 0),
    planned_reviews INTEGER NOT NULL CHECK (planned_reviews >= 0),
    observed_at TEXT NOT NULL,
    PRIMARY KEY (language_profile_id, local_day, deck_name)
);
""".strip()

MIGRATION_19_SQL = r"""
CREATE TABLE reading_series (
    id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL REFERENCES language_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    premise TEXT NOT NULL DEFAULT '',
    continuity_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, language_profile_id)
);
CREATE INDEX idx_reading_series_profile ON reading_series(language_profile_id,created_at,id);
CREATE TABLE reading_series_episodes (
    text_document_id TEXT PRIMARY KEY,
    language_profile_id TEXT NOT NULL,
    series_id TEXT NOT NULL,
    episode_number INTEGER NOT NULL CHECK (episode_number > 0),
    previous_text_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(series_id,episode_number),
    FOREIGN KEY (text_document_id,language_profile_id) REFERENCES text_documents(id,language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (series_id,language_profile_id) REFERENCES reading_series(id,language_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (previous_text_id) REFERENCES text_documents(id)
);
CREATE INDEX idx_reading_series_episodes_series ON reading_series_episodes(series_id,episode_number);
""".strip()

MIGRATION_20_SQL = r"""
CREATE TABLE reader_sentence_grammar_notes (
    sentence_id TEXT PRIMARY KEY,
    text_document_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    grammar_hint TEXT NOT NULL,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (sentence_id,text_document_id)
        REFERENCES text_sentences(id,text_document_id) ON DELETE CASCADE
);
CREATE INDEX idx_reader_sentence_grammar_notes_text
    ON reader_sentence_grammar_notes(text_document_id,sentence_id);
""".strip()

MIGRATION_21_SQL = r"""
CREATE TABLE word_audio_jobs (
    cache_key TEXT PRIMARY KEY CHECK (length(cache_key) = 64),
    word_text TEXT NOT NULL,
    voice_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'READY', 'FAILED')),
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_word_audio_jobs_queue ON word_audio_jobs(state,priority DESC,created_at,cache_key);
""".strip()

MIGRATION_22_SQL = r"""
ALTER TABLE reader_sentence_grammar_notes
    ADD COLUMN glosses_json TEXT NOT NULL DEFAULT '[]';
""".strip()

MIGRATIONS = (
    Migration(1, MIGRATION_1_SQL),
    Migration(2, MIGRATION_2_SQL),
    Migration(3, MIGRATION_3_SQL),
    Migration(4, MIGRATION_4_SQL),
    Migration(5, MIGRATION_5_SQL),
    Migration(6, MIGRATION_6_SQL),
    Migration(7, MIGRATION_7_SQL),
    Migration(8, MIGRATION_8_SQL),
    Migration(9, MIGRATION_9_SQL),
    Migration(10, MIGRATION_10_SQL),
    Migration(11, MIGRATION_11_SQL),
    Migration(12, MIGRATION_12_SQL),
    Migration(13, MIGRATION_13_SQL),
    Migration(14, MIGRATION_14_SQL),
    Migration(15, MIGRATION_15_SQL),
    Migration(16, MIGRATION_16_SQL),
    Migration(17, MIGRATION_17_SQL),
    Migration(18, MIGRATION_18_SQL),
    Migration(19, MIGRATION_19_SQL),
    Migration(20, MIGRATION_20_SQL),
    Migration(21, MIGRATION_21_SQL),
    Migration(22, MIGRATION_22_SQL),
)

REQUIRED_TABLES = {
    "reading_series", "reading_series_episodes",
    "reader_sentence_grammar_notes",
    "word_audio_jobs",
    "benchmark_runs", "benchmark_responses",
    "reader_sentence_translations",
    "grammar_analysis_runs", "grammar_occurrences", "grammar_occurrence_reviews",
    "language_schema_migrations",
    "language_profiles",
    "vocabulary_lemmas",
    "surface_forms",
    "form_lemma_links",
    "lemma_knowledge",
    "knowledge_events",
    "text_documents",
    "text_sentences",
    "text_tokens",
    "analysis_runs",
    "language_jobs",
    "lemma_frequency",
    "study_sessions",
    "exposure_events",
    "text_reading_progress",
    "topics",
    "topic_lemmas",
    "goal_definitions",
    "anki_note_links",
    "anki_card_snapshots",
    "anki_sync_runs",
    "anki_daily_plans",
    "generation_requests",
    "generation_candidates",
    "cloze_sessions",
    "cloze_attempts",
    "cloze_item_suppressions",
    "cloze_sentence_audio",
    "gamification_awards",
    "achievement_unlocks",
    "gamification_quest_snapshots",
    "campaign_definitions",
    "user_lemma_translations",
    "phrasebook_entries",
    "phrasebook_entry_links",
    "generated_text_sentence_audio",
    "listening_sessions",
    "listening_sentence_events",
    "listening_progress",
    "content_items",
    "content_artifacts",
    "transcripts",
    "transcript_cues",
    "sentence_alignments",
}


def _ledger_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS language_schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL,
        checksum TEXT NOT NULL
    )
    """


def apply_migrations(connection: sqlite3.Connection, *, applied_at: str) -> None:
    connection.execute(_ledger_sql())
    connection.commit()
    applied = {
        int(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT version, checksum FROM language_schema_migrations ORDER BY version"
        )
    }
    known = {migration.version: migration for migration in MIGRATIONS}
    unknown = sorted(set(applied) - set(known))
    if unknown:
        raise LanguageStorageError("Language database schema is newer than this application")
    for version, checksum in applied.items():
        if checksum != known[version].checksum:
            raise LanguageStorageError("Language database migration checksum mismatch")

    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        safe_timestamp = applied_at.replace("'", "''")
        safe_checksum = migration.checksum.replace("'", "''")
        script = (
            "BEGIN IMMEDIATE;\n"
            + migration.sql
            + "\nINSERT INTO language_schema_migrations(version, applied_at, checksum) "
            + f"VALUES({migration.version}, '{safe_timestamp}', '{safe_checksum}');\nCOMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error as exc:
            connection.rollback()
            raise LanguageStorageError("Language database migration failed") from exc


def validate_schema(connection: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not REQUIRED_TABLES.issubset(tables):
        raise LanguageStorageError("Language database schema validation failed")
    latest = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM language_schema_migrations"
    ).fetchone()[0]
    if int(latest) != SCHEMA_VERSION:
        raise LanguageStorageError("Language database schema version is invalid")
