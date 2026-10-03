"""SQLite persistence for the canonical Language Learning backend."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .errors import LanguageConflictError, LanguageNotFoundError, LanguageStorageError
from .migrations import MIGRATIONS, SCHEMA_VERSION, apply_migrations, validate_schema
from .schemas import text_fingerprint


EXPORT_VERSION = "language-learning-export/v20"
OFFSET_UNIT = "UNICODE_CODE_POINT"
READER_HEARTBEAT_CAP_SECONDS = 30


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return uuid.uuid4().hex


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class LanguageStore:
    """Low-level store; callers mutate language data through LanguageService."""

    EXPORT_TABLES = (
        "language_profiles",
        "vocabulary_lemmas",
        "surface_forms",
        "form_lemma_links",
        "lemma_knowledge",
        "knowledge_events",
        "text_documents",
        "reading_series",
        "reading_series_episodes",
        "text_sentences",
        "reader_sentence_translations",
        "reader_sentence_grammar_notes",
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
        "grammar_analysis_runs",
        "grammar_occurrences",
        "grammar_occurrence_reviews",
        "benchmark_runs",
        "benchmark_responses",
    )

    def __init__(self, database_path: str | Path, *, backup_directory: str | Path | None = None):
        self.database_path = Path(database_path)
        self.backup_directory = Path(backup_directory) if backup_directory else self.database_path.parent / "backups"
        self._initialize_lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> ClosingConnection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.database_path,
            timeout=15,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        with self._initialize_lock:
            with self._connect() as connection:
                apply_migrations(connection, applied_at=utc_now())
                validate_schema(connection)
            self._initialized = True

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    @contextmanager
    def connection(self) -> Iterator[ClosingConnection]:
        self._ensure_initialized()
        with self._connect() as connection:
            yield connection

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        *,
        lemma_id: str,
        event_type: str,
        source: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        created_at: str | None = None,
    ) -> str:
        event_id = new_id()
        connection.execute(
            "INSERT INTO knowledge_events"
            "(id,lemma_id,event_type,source,idempotency_key,payload_json,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                event_id,
                lemma_id,
                event_type,
                source,
                idempotency_key,
                canonical_json(payload),
                created_at or utc_now(),
            ),
        )
        return event_id

    def schema_info(self) -> dict[str, Any]:
        self._ensure_initialized()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT version, applied_at, checksum FROM language_schema_migrations ORDER BY version"
            ).fetchall()
            profile_count = int(connection.execute("SELECT COUNT(*) FROM language_profiles").fetchone()[0])
        return {
            "schemaVersion": SCHEMA_VERSION,
            "databaseInitialized": True,
            "profileCount": profile_count,
            "migrations": [dict(row) for row in rows],
        }

    def create_profile(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        profile_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM language_profiles WHERE language_code=? AND locale=?",
                (values["language_code"], values["locale"]),
            ).fetchone()
            if existing:
                return dict(existing), False
            connection.execute(
                "INSERT INTO language_profiles"
                "(id,language_code,locale,display_name,translation_locales_json,analyzer_id,"
                "analyzer_version,analyzer_settings_json,reference_provider_config_json,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    profile_id,
                    values["language_code"],
                    values["locale"],
                    values["display_name"],
                    canonical_json(values.get("translation_locales", [])),
                    values.get("analyzer_id"),
                    values.get("analyzer_version"),
                    canonical_json(values.get("analyzer_settings", {})),
                    canonical_json(values.get("reference_provider_config", {})),
                    values.get("status", "ACTIVE"),
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM language_profiles WHERE id=?", (profile_id,)).fetchone()
        return dict(row), True

    def list_profiles(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM language_profiles ORDER BY language_code, locale, id"
            )]

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM language_profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Language profile was not found", code="language_profile_not_found")
        return dict(row)

    def update_profile(self, profile_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "display_name",
            "translation_locales_json",
            "analyzer_id",
            "analyzer_version",
            "analyzer_settings_json",
            "reference_provider_config_json",
            "anki_config_json",
            "status",
        }
        assignments = [(key, value) for key, value in changes.items() if key in allowed]
        with self.connection() as connection:
            if not connection.execute("SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)).fetchone():
                raise LanguageNotFoundError("Language profile was not found", code="language_profile_not_found")
            if assignments:
                values = [value for _, value in assignments]
                sql = ",".join(f"{key}=?" for key, _ in assignments)
                connection.execute(
                    f"UPDATE language_profiles SET {sql},updated_at=? WHERE id=?",
                    (*values, utc_now(), profile_id),
                )
            row = connection.execute("SELECT * FROM language_profiles WHERE id=?", (profile_id,)).fetchone()
        return dict(row)

    def upsert_lemma(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        lemma_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            profile = connection.execute("SELECT 1 FROM language_profiles WHERE id=?", (values["language_profile_id"],)).fetchone()
            if not profile:
                raise LanguageNotFoundError("Language profile was not found", code="language_profile_not_found")
            existing = connection.execute(
                "SELECT * FROM vocabulary_lemmas WHERE language_profile_id=? AND canonical_key=?",
                (values["language_profile_id"], values["canonical_key"]),
            ).fetchone()
            if existing:
                return dict(existing), False
            connection.execute(
                "INSERT INTO vocabulary_lemmas"
                "(id,language_profile_id,lemma_display,lemma_normalized,part_of_speech,canonical_key,"
                "source_kind,source_id,source_version,user_notes,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lemma_id,
                    values["language_profile_id"],
                    values["lemma_display"],
                    values["lemma_normalized"],
                    values.get("part_of_speech"),
                    values["canonical_key"],
                    values.get("source_kind", "MANUAL"),
                    values.get("source_id"),
                    values.get("source_version"),
                    values.get("user_notes"),
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO lemma_knowledge(lemma_id,updated_at) VALUES(?,?)",
                (lemma_id, now),
            )
            row = connection.execute("SELECT * FROM vocabulary_lemmas WHERE id=?", (lemma_id,)).fetchone()
        return dict(row), True

    def upsert_surface_form(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        form_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM surface_forms WHERE language_profile_id=? AND form_normalized=?",
                (values["language_profile_id"], values["form_normalized"]),
            ).fetchone()
            if existing:
                return dict(existing), False
            try:
                connection.execute(
                    "INSERT INTO surface_forms"
                    "(id,language_profile_id,form_display,form_normalized,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (
                        form_id,
                        values["language_profile_id"],
                        values["form_display"],
                        values["form_normalized"],
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError("Surface form relationship is invalid", code="invalid_form_relationship") from exc
            row = connection.execute("SELECT * FROM surface_forms WHERE id=?", (form_id,)).fetchone()
        return dict(row), True

    def upsert_form_lemma_link(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        now = utc_now()
        link_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM form_lemma_links WHERE form_id=? AND lemma_id=?",
                (values["form_id"], values["lemma_id"]),
            ).fetchone()
            if existing and existing["language_profile_id"] != values["language_profile_id"]:
                raise LanguageConflictError(
                    "Form and lemma must belong to the requested language profile",
                    code="cross_profile_relationship",
                )
            if existing and int(existing["manual_locked"]) and values.get("mapping_provenance") != "MANUAL":
                return dict(existing), False, True
            columns = (
                values.get("provider_id"),
                values.get("provider_version"),
                canonical_json(values.get("morphology", {})),
                values.get("confidence"),
                values.get("ambiguity_state", "NOT_REPORTED"),
                values.get("lexical_status", "NOT_ASSESSED"),
                values.get("mapping_provenance", "ANALYZER"),
                1 if values.get("manual_locked") else 0,
                values.get("manual_provenance"),
                now,
            )
            try:
                if existing:
                    connection.execute(
                        "UPDATE form_lemma_links SET provider_id=?,provider_version=?,morphology_json=?,"
                        "confidence=?,ambiguity_state=?,lexical_status=?,mapping_provenance=?,manual_locked=?,"
                        "manual_provenance=?,updated_at=? WHERE id=?",
                        (*columns, existing["id"]),
                    )
                    link_id = str(existing["id"])
                    created = False
                else:
                    connection.execute(
                        "INSERT INTO form_lemma_links"
                        "(id,language_profile_id,form_id,lemma_id,provider_id,provider_version,morphology_json,"
                        "confidence,ambiguity_state,lexical_status,mapping_provenance,manual_locked,manual_provenance,"
                        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            link_id,
                            values["language_profile_id"],
                            values["form_id"],
                            values["lemma_id"],
                            *columns[:-1],
                            now,
                            now,
                        ),
                    )
                    created = True
                row = connection.execute("SELECT * FROM form_lemma_links WHERE id=?", (link_id,)).fetchone()
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError(
                    "Form and lemma must belong to the same language profile",
                    code="cross_profile_relationship",
                ) from exc
        return dict(row), created, False

    def update_knowledge(self, lemma_id: str, changes: dict[str, Any], *, source: str, manual: bool) -> dict[str, Any]:
        with self.connection() as connection:
            current = connection.execute("SELECT * FROM lemma_knowledge WHERE lemma_id=?", (lemma_id,)).fetchone()
            if current is None:
                raise LanguageNotFoundError("Lemma was not found", code="language_lemma_not_found")
            current = dict(current)
            applied: dict[str, Any] = {}
            protected_fields: list[str] = []
            status_fields = {"knowledge_status", "disposition"}
            score_fields = {"recognition", "recall", "production"}
            for key, value in changes.items():
                if key in status_fields:
                    if not manual and current["manual_status_override"]:
                        protected_fields.append(key)
                    else:
                        applied[key] = value
                if key in score_fields:
                    if not manual and current["manual_scores_override"]:
                        protected_fields.append(key)
                    else:
                        applied[key] = value
            if manual and status_fields.intersection(changes):
                applied["manual_status_override"] = 1
            if manual and score_fields.intersection(changes):
                applied["manual_scores_override"] = 1
            if manual and applied:
                applied["manual_override_source"] = source
            if applied:
                applied["updated_at"] = utc_now()
                sql = ",".join(f"{key}=?" for key in applied)
                connection.execute(
                    f"UPDATE lemma_knowledge SET {sql} WHERE lemma_id=?",
                    (*applied.values(), lemma_id),
                )
                self._event(
                    connection,
                    lemma_id=lemma_id,
                    event_type="MANUAL_KNOWLEDGE_UPDATE" if manual else "KNOWLEDGE_RECALCULATION",
                    source=source,
                    payload={"before": current, "changes": changes, "applied": applied},
                )
            row = connection.execute("SELECT * FROM lemma_knowledge WHERE lemma_id=?", (lemma_id,)).fetchone()
        result = dict(row)
        result["protected"] = bool(protected_fields)
        result["protected_fields"] = protected_fields
        return result

    def update_lemma(self, lemma_id: str, changes: dict[str, Any], *, source: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM vocabulary_lemmas WHERE id=?", (lemma_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Lemma was not found", code="language_lemma_not_found")
            if row["merged_into_id"]:
                raise LanguageConflictError("Merged lemma cannot be edited", code="lemma_is_merged")
            allowed = {"lemma_display", "lemma_normalized", "part_of_speech", "canonical_key", "user_notes"}
            applied = {key: value for key, value in changes.items() if key in allowed}
            if applied:
                applied["updated_at"] = utc_now()
                sql = ",".join(f"{key}=?" for key in applied)
                try:
                    connection.execute(
                        f"UPDATE vocabulary_lemmas SET {sql} WHERE id=?",
                        (*applied.values(), lemma_id),
                    )
                except sqlite3.IntegrityError as exc:
                    raise LanguageConflictError("Lemma identity already exists", code="duplicate_lemma") from exc
                self._event(
                    connection,
                    lemma_id=lemma_id,
                    event_type="MANUAL_LEMMA_UPDATE",
                    source=source,
                    payload={"changes": changes},
                )
            updated = connection.execute("SELECT * FROM vocabulary_lemmas WHERE id=?", (lemma_id,)).fetchone()
        return dict(updated)

    def get_lemma_detail(self, lemma_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            lemma = connection.execute("SELECT * FROM vocabulary_lemmas WHERE id=?", (lemma_id,)).fetchone()
            if lemma is None:
                raise LanguageNotFoundError("Lemma was not found", code="language_lemma_not_found")
            knowledge = connection.execute("SELECT * FROM lemma_knowledge WHERE lemma_id=?", (lemma_id,)).fetchone()
            forms = connection.execute(
                "SELECT f.*,l.id AS link_id,l.provider_id,l.provider_version,l.morphology_json,l.confidence,"
                "l.ambiguity_state,l.lexical_status,l.mapping_provenance,l.manual_locked,l.manual_provenance "
                "FROM form_lemma_links l JOIN surface_forms f ON f.id=l.form_id "
                "WHERE l.lemma_id=? ORDER BY f.form_normalized,f.id",
                (lemma_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM knowledge_events WHERE lemma_id=? ORDER BY created_at,id",
                (lemma_id,),
            ).fetchall()
            frequencies = connection.execute(
                "SELECT * FROM lemma_frequency WHERE lemma_id=? "
                "ORDER BY metric,provider_id,observed_at DESC",
                (lemma_id,),
            ).fetchall()
            form_ids = [str(row["id"]) for row in forms]
            candidates_by_form: dict[str, list[dict[str, Any]]] = {
                form_id: [] for form_id in form_ids
            }
            if form_ids:
                placeholders = ",".join("?" for _ in form_ids)
                candidates = connection.execute(
                    "SELECT l.*,v.lemma_display,v.lemma_normalized,v.part_of_speech,v.merged_into_id "
                    "FROM form_lemma_links l "
                    "JOIN vocabulary_lemmas v ON v.id=l.lemma_id "
                    f"WHERE l.form_id IN ({placeholders}) "
                    "ORDER BY l.form_id,l.manual_locked DESC,v.lemma_normalized,v.id",
                    form_ids,
                ).fetchall()
                for candidate in candidates:
                    candidates_by_form[str(candidate["form_id"])].append(dict(candidate))
        return {
            "lemma": dict(lemma),
            "knowledge": dict(knowledge) if knowledge else None,
            "forms": [dict(row) for row in forms],
            "events": [dict(row) for row in events],
            "frequencies": [dict(row) for row in frequencies],
            "candidates_by_form": candidates_by_form,
        }

    def curriculum_knowledge_snapshot(
        self, profile_id: str, identities: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Resolve a bounded set of exact curriculum identities in bulk.

        Absence is meaningful (UNSEEN), so this method never creates a lemma or
        knowledge row and never performs one query per curriculum item.
        """
        normalized = sorted({str(item.get("normalizedLookup") or "") for item in identities if item.get("normalizedLookup")})
        if not normalized:
            return []
        rows: list[dict[str, Any]] = []
        with self.connection() as connection:
            for offset in range(0, len(normalized), 300):
                batch = normalized[offset:offset + 300]
                placeholders = ",".join("?" for _ in batch)
                found = connection.execute(
                    "SELECT l.id,l.lemma_display,l.lemma_normalized,l.part_of_speech,l.canonical_key,"
                    "k.knowledge_status,k.disposition,k.manual_status_override,k.updated_at "
                    "FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id "
                    "WHERE l.language_profile_id=? AND l.merged_into_id IS NULL "
                    f"AND l.lemma_normalized IN ({placeholders}) "
                    "ORDER BY l.lemma_normalized,l.part_of_speech,l.id",
                    (profile_id, *batch),
                ).fetchall()
                rows.extend(dict(row) for row in found)
        return rows

    def get_form_mapping_detail(self, form_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            form = connection.execute(
                "SELECT * FROM surface_forms WHERE id=?", (form_id,)
            ).fetchone()
            if form is None:
                raise LanguageNotFoundError(
                    "Surface form was not found", code="language_form_not_found"
                )
            mappings = connection.execute(
                "SELECT l.*,v.lemma_display,v.lemma_normalized,v.part_of_speech,v.merged_into_id "
                "FROM form_lemma_links l "
                "JOIN vocabulary_lemmas v ON v.id=l.lemma_id "
                "WHERE l.form_id=? "
                "ORDER BY l.manual_locked DESC,v.lemma_normalized,v.id",
                (form_id,),
            ).fetchall()
        return {"form": dict(form), "mappings": [dict(row) for row in mappings]}

    def search_lemmas(
        self,
        profile_id: str,
        *,
        query: str = "",
        status: str | None = None,
        disposition: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["l.language_profile_id=?", "l.merged_into_id IS NULL"]
        params: list[Any] = [profile_id]
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append(
                "(l.lemma_normalized LIKE ? ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM form_lemma_links fl JOIN surface_forms sf ON sf.id=fl.form_id "
                "WHERE fl.lemma_id=l.id AND sf.form_normalized LIKE ? ESCAPE '\\'))"
            )
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        if status:
            where.append("k.knowledge_status=?")
            params.append(status)
        if disposition:
            where.append("k.disposition=?")
            params.append(disposition)
        where_sql = " AND ".join(where)
        with self.connection() as connection:
            if not connection.execute("SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)).fetchone():
                raise LanguageNotFoundError("Language profile was not found", code="language_profile_not_found")
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id WHERE {where_sql}",
                params,
            ).fetchone()[0])
            rows = connection.execute(
                "SELECT l.*,k.knowledge_status,k.disposition,k.recognition,k.recall,k.production,"
                "k.total_exposures,k.first_seen_at,k.last_seen_at,k.last_review_at,"
                "k.manual_status_override,k.manual_scores_override,k.updated_at AS knowledge_updated_at,"
                "(SELECT COUNT(*) FROM form_lemma_links fl WHERE fl.lemma_id=l.id) AS forms_count,"
                "(SELECT lf.score FROM lemma_frequency lf WHERE lf.lemma_id=l.id "
                " ORDER BY lf.observed_at DESC,lf.provider_id LIMIT 1) AS frequency_score,"
                "(SELECT lf.provider_id FROM lemma_frequency lf WHERE lf.lemma_id=l.id "
                " ORDER BY lf.observed_at DESC,lf.provider_id LIMIT 1) AS frequency_provider_id,"
                "(SELECT lf.provider_version FROM lemma_frequency lf WHERE lf.lemma_id=l.id "
                " ORDER BY lf.observed_at DESC,lf.provider_id LIMIT 1) AS frequency_provider_version "
                "FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id "
                f"WHERE {where_sql} ORDER BY l.lemma_normalized,l.id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def create_text_draft(self, values: dict[str, Any]) -> dict[str, Any]:
        text_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO text_documents"
                    "(id,language_profile_id,title,raw_text,source_type,source_reference,content_fingerprint,"
                    "processing_state,offset_unit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        text_id,
                        values["language_profile_id"],
                        values["title"],
                        values["raw_text"],
                        values["source_type"],
                        values.get("source_reference"),
                        values["content_fingerprint"],
                        "DRAFT",
                        OFFSET_UNIT,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError("Text profile relationship is invalid", code="invalid_text_relationship") from exc
            row = connection.execute("SELECT * FROM text_documents WHERE id=?", (text_id,)).fetchone()
        return dict(row)

    def get_text(self, text_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            document = connection.execute("SELECT * FROM text_documents WHERE id=?", (text_id,)).fetchone()
            if document is None:
                raise LanguageNotFoundError("Text was not found", code="language_text_not_found")
            sentences = connection.execute(
                "SELECT * FROM text_sentences WHERE text_document_id=? ORDER BY sentence_order,id", (text_id,)
            ).fetchall()
            tokens = connection.execute(
                "SELECT t.*,l.lemma_display AS selected_lemma_display,"
                "l.lemma_normalized AS selected_lemma_normalized,l.part_of_speech AS selected_lemma_pos,"
                "k.knowledge_status,k.disposition,k.recognition,k.updated_at AS knowledge_updated_at "
                "FROM text_tokens t "
                "LEFT JOIN vocabulary_lemmas l ON l.id=t.selected_lemma_id "
                "LEFT JOIN lemma_knowledge k ON k.lemma_id=t.selected_lemma_id "
                "WHERE t.text_document_id=? ORDER BY t.token_order,t.id",
                (text_id,),
            ).fetchall()
            runs = connection.execute(
                "SELECT * FROM analysis_runs WHERE text_document_id=? ORDER BY created_at,id", (text_id,)
            ).fetchall()
            frequencies = connection.execute(
                "SELECT f.* FROM lemma_frequency f WHERE f.lemma_id IN ("
                "SELECT DISTINCT selected_lemma_id FROM text_tokens "
                "WHERE text_document_id=? AND selected_lemma_id IS NOT NULL) "
                "ORDER BY f.lemma_id,f.provider_id,f.metric",
                (text_id,),
            ).fetchall()
            latest_job = connection.execute(
                "SELECT * FROM language_jobs WHERE text_document_id=? AND analysis_domain='TEXT' "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (text_id,),
            ).fetchone()
            progress = connection.execute(
                "SELECT p.*,(SELECT COALESCE(SUM(s.active_seconds),0) FROM study_sessions s "
                "WHERE s.text_document_id=p.text_document_id AND s.session_type='READER') AS active_seconds "
                "FROM text_reading_progress p WHERE p.text_document_id=?",
                (text_id,),
            ).fetchone()
            sessions = connection.execute(
                "SELECT * FROM study_sessions WHERE text_document_id=? AND session_type='READER' "
                "ORDER BY started_at DESC,id DESC LIMIT 20",
                (text_id,),
            ).fetchall()
        return {
            "document": dict(document),
            "sentences": [dict(row) for row in sentences],
            "tokens": [dict(row) for row in tokens],
            "analysisRuns": [dict(row) for row in runs],
            "frequencies": [dict(row) for row in frequencies],
            "latestJob": dict(latest_job) if latest_job else None,
            "readingProgress": dict(progress) if progress else None,
            "studySessions": [dict(row) for row in sessions],
        }

    def reader_sentence_translation(self, text_id: str, sentence_id: str, target_language: str) -> dict[str, Any]:
        with self.connection() as connection:
            sentence = connection.execute(
                "SELECT s.id,s.text_document_id,s.exact_text,s.sentence_order,d.processing_state "
                "FROM text_sentences s JOIN text_documents d ON d.id=s.text_document_id "
                "WHERE s.id=? AND s.text_document_id=?",
                (sentence_id, text_id),
            ).fetchone()
            if sentence is None:
                raise LanguageNotFoundError("Reader sentence was not found", code="reader_sentence_not_found")
            translation = connection.execute(
                "SELECT * FROM reader_sentence_translations WHERE sentence_id=? AND target_language=?",
                (sentence_id, target_language),
            ).fetchone()
        return {"sentence": dict(sentence), "translation": self._row(translation)}

    def save_reader_sentence_translation(
        self, text_id: str, sentence_id: str, *, target_language: str,
        source_hash: str, translation: str, provider: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO reader_sentence_translations(sentence_id,text_document_id,target_language,"
                "source_hash,translation_text,provider,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(sentence_id,target_language) DO UPDATE SET source_hash=excluded.source_hash,"
                "translation_text=excluded.translation_text,provider=excluded.provider,updated_at=excluded.updated_at",
                (sentence_id, text_id, target_language, source_hash, translation, provider, now, now),
            )
            row = connection.execute(
                "SELECT * FROM reader_sentence_translations WHERE sentence_id=? AND target_language=?",
                (sentence_id, target_language),
            ).fetchone()
        return dict(row)

    def reader_study_notes(self, text_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT s.id,s.sentence_order,s.exact_text,t.translation_text,t.source_hash AS translation_hash,"
                "g.grammar_hint,g.glosses_json,g.source_hash AS grammar_hash "
                "FROM text_sentences s "
                "LEFT JOIN reader_sentence_translations t ON t.sentence_id=s.id AND t.target_language='en' "
                "LEFT JOIN reader_sentence_grammar_notes g ON g.sentence_id=s.id "
                "WHERE s.text_document_id=? ORDER BY s.sentence_order,s.id",
                (text_id,),
            ).fetchall()
        items = []
        for row in rows:
            source_hash = text_fingerprint(row["exact_text"])
            items.append({"sentenceId": row["id"], "sentenceOrder": row["sentence_order"],
                          "source": row["exact_text"],
                          "english": row["translation_text"] if row["translation_hash"] == source_hash else None,
                          "grammarHint": row["grammar_hint"] if row["grammar_hash"] == source_hash else None,
                          "glosses": json.loads(row["glosses_json"]) if row["grammar_hash"] == source_hash and row["glosses_json"] else []})
        return items

    def import_reader_study_notes(self, text_id: str, items: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self.connection() as connection:
            for item in items:
                source_hash = text_fingerprint(item["source"])
                connection.execute(
                    "INSERT INTO reader_sentence_translations(sentence_id,text_document_id,target_language,"
                    "source_hash,translation_text,provider,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(sentence_id,target_language) DO UPDATE SET source_hash=excluded.source_hash,"
                    "translation_text=excluded.translation_text,provider=excluded.provider,updated_at=excluded.updated_at",
                    (item["sentenceId"], text_id, "en", source_hash, item["english"], "EXTERNAL_IMPORT", now, now),
                )
                connection.execute(
                    "INSERT INTO reader_sentence_grammar_notes(sentence_id,text_document_id,source_hash,grammar_hint,"
                    "glosses_json,provider,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(sentence_id) DO UPDATE SET source_hash=excluded.source_hash,"
                    "grammar_hint=excluded.grammar_hint,glosses_json=excluded.glosses_json,"
                    "provider=excluded.provider,updated_at=excluded.updated_at",
                    (item["sentenceId"], text_id, source_hash, item["grammarHint"],
                     canonical_json(item["glosses"]), "EXTERNAL_IMPORT", now, now),
                )

    def list_texts(self, profile_id: str, *, limit: int, offset: int) -> dict[str, Any]:
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)
            ).fetchone():
                raise LanguageNotFoundError(
                    "Language profile was not found", code="language_profile_not_found"
                )
            total = int(connection.execute(
                "SELECT COUNT(*) FROM text_documents WHERE language_profile_id=?",
                (profile_id,),
            ).fetchone()[0])
            rows = connection.execute(
                "SELECT d.*,e.series_id,e.episode_number,e.previous_text_id,rs.title AS series_title,"
                "(SELECT j.id FROM language_jobs j WHERE j.text_document_id=d.id AND j.analysis_domain='TEXT' "
                " ORDER BY j.created_at DESC,j.id DESC LIMIT 1) AS latest_job_id,"
                "(SELECT j.state FROM language_jobs j WHERE j.text_document_id=d.id AND j.analysis_domain='TEXT' "
                " ORDER BY j.created_at DESC,j.id DESC LIMIT 1) AS latest_job_state,"
                "(SELECT j.stage FROM language_jobs j WHERE j.text_document_id=d.id AND j.analysis_domain='TEXT' "
                " ORDER BY j.created_at DESC,j.id DESC LIMIT 1) AS latest_job_stage,"
                "(SELECT j.progress FROM language_jobs j WHERE j.text_document_id=d.id AND j.analysis_domain='TEXT' "
                " ORDER BY j.created_at DESC,j.id DESC LIMIT 1) AS latest_job_progress,"
                "(SELECT j.error_message FROM language_jobs j WHERE j.text_document_id=d.id AND j.analysis_domain='TEXT' "
                " ORDER BY j.created_at DESC,j.id DESC LIMIT 1) AS latest_job_error,"
                "(SELECT r.completed_at FROM analysis_runs r WHERE r.text_document_id=d.id "
                " AND r.state='COMPLETED' ORDER BY r.created_at DESC,r.id DESC LIMIT 1) AS analyzed_at,"
                "(SELECT COUNT(*) FROM text_tokens t WHERE t.text_document_id=d.id) AS token_count,"
                "(SELECT COUNT(DISTINCT t.selected_lemma_id) FROM text_tokens t "
                " WHERE t.text_document_id=d.id AND t.selected_lemma_id IS NOT NULL) AS unique_lemma_count,"
                "p.status AS reading_status,p.progress_source_offset,p.last_read_at,p.completed_at,"
                "p.coverage_snapshot_json,p.analysis_run_id AS completion_analysis_run_id,"
                "(SELECT COALESCE(SUM(s.active_seconds),0) FROM study_sessions s "
                " WHERE s.text_document_id=d.id AND s.session_type='READER') AS active_seconds "
                "FROM text_documents d LEFT JOIN text_reading_progress p ON p.text_document_id=d.id "
                "LEFT JOIN reading_series_episodes e ON e.text_document_id=d.id "
                "LEFT JOIN reading_series rs ON rs.id=e.series_id "
                "WHERE d.language_profile_id=? "
                "ORDER BY d.created_at DESC,d.id DESC LIMIT ? OFFSET ?",
                (profile_id, limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def create_reading_series(self, profile_id: str, title: str, premise: str, continuity_notes: str) -> dict[str, Any]:
        series_id, now = new_id(), utc_now()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO reading_series(id,language_profile_id,title,premise,continuity_notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (series_id, profile_id, title, premise, continuity_notes, now, now),
            )
            row = connection.execute("SELECT * FROM reading_series WHERE id=?", (series_id,)).fetchone()
        return dict(row)

    def get_reading_series(self, series_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM reading_series WHERE id=?", (series_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Reading series was not found", code="reading_series_not_found")
        return dict(row)

    def list_reading_series(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT s.*,COUNT(e.text_document_id) AS episode_count "
                "FROM reading_series s LEFT JOIN reading_series_episodes e ON e.series_id=s.id "
                "WHERE s.language_profile_id=? GROUP BY s.id ORDER BY s.created_at DESC,s.id DESC",
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_reading_series_episodes(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT e.series_id,e.text_document_id,e.episode_number,d.title "
                "FROM reading_series_episodes e JOIN text_documents d ON d.id=e.text_document_id "
                "WHERE e.language_profile_id=? ORDER BY e.series_id,e.episode_number",
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_text_series_membership(self, text_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT e.series_id,e.episode_number,e.previous_text_id,s.title AS series_title "
                "FROM reading_series_episodes e JOIN reading_series s ON s.id=e.series_id "
                "WHERE e.text_document_id=?", (text_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_reading_series(self, series_id: str, title: str, premise: str, continuity_notes: str) -> dict[str, Any]:
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE reading_series SET title=?,premise=?,continuity_notes=?,updated_at=? WHERE id=?",
                (title, premise, continuity_notes, utc_now(), series_id),
            )
            if not cursor.rowcount:
                raise LanguageNotFoundError("Reading series was not found", code="reading_series_not_found")
            row = connection.execute("SELECT * FROM reading_series WHERE id=?", (series_id,)).fetchone()
        return dict(row)

    def assign_text_to_series(self, profile_id: str, text_id: str, series_id: str | None) -> dict[str, Any] | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            text = connection.execute("SELECT id FROM text_documents WHERE id=? AND language_profile_id=?", (text_id, profile_id)).fetchone()
            if text is None:
                raise LanguageNotFoundError("Text was not found", code="language_text_not_found")
            if series_id is None:
                connection.execute("DELETE FROM reading_series_episodes WHERE text_document_id=?", (text_id,))
                return None
            series = connection.execute("SELECT id FROM reading_series WHERE id=? AND language_profile_id=?", (series_id, profile_id)).fetchone()
            if series is None:
                raise LanguageNotFoundError("Reading series was not found", code="reading_series_not_found")
            old = connection.execute("SELECT series_id,episode_number FROM reading_series_episodes WHERE text_document_id=?", (text_id,)).fetchone()
            if old and old["series_id"] == series_id:
                return {"seriesId": series_id, "episodeNumber": old["episode_number"]}
            connection.execute("DELETE FROM reading_series_episodes WHERE text_document_id=?", (text_id,))
            number = connection.execute("SELECT COALESCE(MAX(episode_number),0)+1 FROM reading_series_episodes WHERE series_id=?", (series_id,)).fetchone()[0]
            connection.execute(
                "INSERT INTO reading_series_episodes(text_document_id,language_profile_id,series_id,episode_number,previous_text_id,created_at) VALUES(?,?,?,?,NULL,?)",
                (text_id, profile_id, series_id, number, utc_now()),
            )
        return {"seriesId": series_id, "episodeNumber": number}

    def reading_series_context(self, profile_id: str, series_id: str, previous_text_id: str | None) -> dict[str, Any]:
        with self.connection() as connection:
            series = connection.execute("SELECT * FROM reading_series WHERE id=? AND language_profile_id=?", (series_id, profile_id)).fetchone()
            if series is None:
                raise LanguageNotFoundError("Reading series was not found", code="reading_series_not_found")
            episode_count = connection.execute("SELECT COUNT(*) FROM reading_series_episodes WHERE series_id=?", (series_id,)).fetchone()[0]
            previous = None
            if previous_text_id:
                previous = connection.execute(
                    "SELECT e.episode_number FROM reading_series_episodes e WHERE e.series_id=? AND e.text_document_id=?",
                    (series_id, previous_text_id),
                ).fetchone()
                if previous is None:
                    raise LanguageNotFoundError("Previous text is not in this series", code="reading_series_previous_not_found")
            rows = connection.execute(
                "SELECT e.episode_number,d.id,d.title,d.raw_text FROM reading_series_episodes e "
                "JOIN text_documents d ON d.id=e.text_document_id WHERE e.series_id=? "
                "AND e.episode_number<=? ORDER BY e.episode_number DESC LIMIT 4",
                (series_id, previous["episode_number"] if previous else 0),
            ).fetchall()
        return {"series": dict(series), "episodeCount": episode_count, "previous": [dict(row) for row in rows]}

    def coverage_rows(self, text_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM text_documents WHERE id=?", (text_id,)
            ).fetchone():
                raise LanguageNotFoundError("Text was not found", code="language_text_not_found")
            rows = connection.execute(
                "SELECT t.*,k.knowledge_status,k.disposition,k.updated_at AS knowledge_updated_at "
                "FROM text_tokens t LEFT JOIN lemma_knowledge k ON k.lemma_id=t.selected_lemma_id "
                "WHERE t.text_document_id=? ORDER BY t.token_order,t.id",
                (text_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def coverage_rows_batch(self, text_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Read one paginated Reader library's coverage inputs in one query."""
        ids = list(dict.fromkeys(text_ids))
        if len(ids) > 100:
            raise ValueError("Reader coverage batch exceeds page limit")
        result: dict[str, list[dict[str, Any]]] = {text_id: [] for text_id in ids}
        if not ids:
            return result
        placeholders = ",".join("?" for _ in ids)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT t.*,k.knowledge_status,k.disposition,k.updated_at AS knowledge_updated_at "
                "FROM text_tokens t LEFT JOIN lemma_knowledge k ON k.lemma_id=t.selected_lemma_id "
                "WHERE t.text_document_id IN (" + placeholders + ") "
                "ORDER BY t.text_document_id,t.token_order,t.id", ids,
            ).fetchall()
        for row in rows:
            result[row["text_document_id"]].append(dict(row))
        return result

    def analysis_snapshot(self, text_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            document = connection.execute(
                "SELECT * FROM text_documents WHERE id=?", (text_id,)
            ).fetchone()
            if document is None:
                raise LanguageNotFoundError("Text was not found", code="language_text_not_found")
            tokens = connection.execute(
                "SELECT t.*,l.lemma_display AS selected_lemma_display,"
                "l.lemma_normalized AS selected_lemma_normalized,l.part_of_speech AS selected_lemma_pos "
                "FROM text_tokens t LEFT JOIN vocabulary_lemmas l ON l.id=t.selected_lemma_id "
                "WHERE t.text_document_id=? ORDER BY t.token_order,t.id",
                (text_id,),
            ).fetchall()
            run = connection.execute(
                "SELECT * FROM analysis_runs WHERE text_document_id=? AND state='COMPLETED' "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (text_id,),
            ).fetchone()
            locks = connection.execute(
                "SELECT sf.form_normalized,fl.lemma_id,l.lemma_display,l.lemma_normalized,l.part_of_speech,"
                "fl.id AS mapping_id,fl.updated_at AS mapping_updated_at "
                "FROM form_lemma_links fl JOIN surface_forms sf ON sf.id=fl.form_id "
                "JOIN vocabulary_lemmas l ON l.id=fl.lemma_id "
                "WHERE sf.language_profile_id=? AND fl.manual_locked=1 "
                "ORDER BY sf.form_normalized,fl.created_at,fl.id",
                (document["language_profile_id"],),
            ).fetchall()
        return {
            "document": dict(document),
            "tokens": [dict(row) for row in tokens],
            "analysisRun": dict(run) if run else None,
            "manualLocks": [dict(row) for row in locks],
        }

    def insert_text_structure(
        self,
        text_id: str,
        *,
        sentences: list[dict[str, Any]],
        tokens: list[dict[str, Any]],
        analysis_run: dict[str, Any] | None = None,
    ) -> None:
        """Persist already-produced synthetic/analyzer output; never invokes an analyzer."""
        with self.connection() as connection:
            document = connection.execute("SELECT * FROM text_documents WHERE id=?", (text_id,)).fetchone()
            if document is None:
                raise LanguageNotFoundError("Text was not found", code="language_text_not_found")
            for sentence in sentences:
                connection.execute(
                    "INSERT INTO text_sentences"
                    "(id,text_document_id,sentence_order,source_start,source_end,offset_unit,exact_text,fingerprint) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        sentence.get("id") or new_id(), text_id, sentence["sentence_order"], sentence["source_start"],
                        sentence["source_end"], OFFSET_UNIT, sentence.get("exact_text"), sentence["fingerprint"],
                    ),
                )
            for token in tokens:
                connection.execute(
                    "INSERT INTO text_tokens"
                    "(id,language_profile_id,text_document_id,sentence_id,token_order,surface,source_start,source_end,"
                    "offset_unit,token_kind,normalized_lookup,surface_form_id,selected_lemma_id,mapping_evidence_reference,"
                    "part_of_speech,morphology_json,provider_id,provider_version,ambiguity_state,lexical_status,confidence) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        token.get("id") or new_id(), document["language_profile_id"], text_id, token.get("sentence_id"),
                        token["token_order"], token["surface"], token["source_start"], token["source_end"], OFFSET_UNIT,
                        token["token_kind"], token.get("normalized_lookup"), token.get("surface_form_id"),
                        token.get("selected_lemma_id"), token.get("mapping_evidence_reference"), token.get("part_of_speech"),
                        canonical_json(token.get("morphology", {})), token.get("provider_id"), token.get("provider_version"),
                        token.get("ambiguity_state", "NOT_REPORTED"), token.get("lexical_status", "NOT_ASSESSED"),
                        token.get("confidence"),
                    ),
                )
            if analysis_run:
                connection.execute(
                    "INSERT INTO analysis_runs"
                    "(id,language_profile_id,text_document_id,analyzer_id,analyzer_version,contract_version,state,"
                    "content_fingerprint,started_at,completed_at,error_code,provenance_json,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        analysis_run.get("id") or new_id(), document["language_profile_id"], text_id,
                        analysis_run["analyzer_id"], analysis_run["analyzer_version"], analysis_run["contract_version"],
                        analysis_run["state"], document["content_fingerprint"], analysis_run.get("started_at"),
                        analysis_run.get("completed_at"), analysis_run.get("error_code"),
                        canonical_json(analysis_run.get("provenance", {})), utc_now(),
                    ),
                )

    def create_analysis_job(self, values: dict[str, Any], *, max_pending: int = 100) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        with self.connection() as connection:
            document = connection.execute(
                "SELECT * FROM text_documents WHERE id=?", (values["text_document_id"],)
            ).fetchone()
            if document is None:
                raise LanguageNotFoundError("Text was not found", code="language_text_not_found")
            if document["language_profile_id"] != values["language_profile_id"]:
                raise LanguageConflictError(
                    "Text belongs to another language profile", code="cross_profile_relationship"
                )
            reusable = connection.execute(
                "SELECT * FROM language_jobs WHERE job_type=? AND analysis_fingerprint=? "
                "AND state IN ('QUEUED','RUNNING','COMPLETED') "
                "ORDER BY CASE state WHEN 'COMPLETED' THEN 0 WHEN 'RUNNING' THEN 1 ELSE 2 END,"
                "created_at DESC,id DESC LIMIT 1",
                (values["job_type"], values["analysis_fingerprint"]),
            ).fetchone()
            if reusable is not None:
                return dict(reusable), False
            pending = int(connection.execute(
                "SELECT COUNT(*) FROM language_jobs WHERE state IN ('QUEUED','RUNNING')"
            ).fetchone()[0])
            if pending >= max_pending:
                raise LanguageConflictError(
                    "Language analysis queue is full", code="language_job_queue_full"
                )
            job_id = str(values.get("id") or new_id())
            try:
                connection.execute(
                    "INSERT INTO language_jobs("
                    "id,language_profile_id,text_document_id,job_type,job_version,analyzer_id,analyzer_version,"
                    "contract_version,analysis_policy_version,frequency_provider_id,frequency_provider_version,"
                    "coverage_policy_version,content_fingerprint,analysis_fingerprint,state,stage,progress,"
                    "request_json,created_at,updated_at,analysis_domain) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        values["language_profile_id"],
                        values["text_document_id"],
                        values["job_type"],
                        values.get("job_version", "language.analysis-job/v1"),
                        values["analyzer_id"],
                        values["analyzer_version"],
                        values["contract_version"],
                        values["analysis_policy_version"],
                        values["frequency_provider_id"],
                        values["frequency_provider_version"],
                        values["coverage_policy_version"],
                        values["content_fingerprint"],
                        values["analysis_fingerprint"],
                        "QUEUED",
                        "QUEUED",
                        0.0,
                        canonical_json(values.get("request", {})),
                        now,
                        now,
                        values.get("analysis_domain", "TEXT"),
                    ),
                )
            except sqlite3.IntegrityError:
                reusable = connection.execute(
                    "SELECT * FROM language_jobs WHERE job_type=? AND analysis_fingerprint=? "
                    "AND state IN ('QUEUED','RUNNING') ORDER BY created_at DESC,id DESC LIMIT 1",
                    (values["job_type"], values["analysis_fingerprint"]),
                ).fetchone()
                if reusable is None:
                    raise
                return dict(reusable), False
            row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row), True

    def get_analysis_job(self, job_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Language job was not found", code="language_job_not_found")
        return dict(row)

    def recover_analysis_jobs(self, *, max_attempts: int = 3) -> dict[str, int]:
        now = utc_now()
        with self.connection() as connection:
            cancelled = connection.execute(
                "UPDATE language_jobs SET state='CANCELLED',stage='CANCELLED',progress=NULL,"
                "completed_at=?,updated_at=? WHERE state='RUNNING' AND cancel_requested=1",
                (now, now),
            ).rowcount
            failed = connection.execute(
                "UPDATE language_jobs SET state='FAILED',stage='FAILED',progress=NULL,"
                "error_code='language_job_recovery_exhausted',"
                "error_message='Language job exceeded the restart recovery limit',"
                "completed_at=?,updated_at=? WHERE state='RUNNING' AND cancel_requested=0 "
                "AND attempt_count>=?",
                (now, now, max_attempts),
            ).rowcount
            requeued = connection.execute(
                "UPDATE language_jobs SET state='QUEUED',stage='QUEUED',progress=0,started_at=NULL,"
                "error_code=NULL,error_message=NULL,updated_at=? "
                "WHERE state='RUNNING' AND cancel_requested=0 AND attempt_count<?",
                (now, max_attempts),
            ).rowcount
        return {
            "requeued": int(requeued),
            "cancelled": int(cancelled),
            "failed": int(failed),
        }

    def claim_next_analysis_job(self) -> dict[str, Any] | None:
        now = utc_now()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM language_jobs WHERE state='QUEUED' AND cancel_requested=0 "
                "ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                "UPDATE language_jobs SET state='RUNNING',stage='STARTING',progress=0.02,"
                "attempt_count=attempt_count+1,started_at=?,completed_at=NULL,updated_at=? "
                "WHERE id=? AND state='QUEUED'",
                (now, now, row["id"]),
            ).rowcount
            if changed != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM language_jobs WHERE id=?", (row["id"],)
            ).fetchone()
        return dict(claimed)

    def update_analysis_job_stage(self, job_id: str, stage: str, progress: float | None) -> dict[str, Any]:
        with self.connection() as connection:
            changed = connection.execute(
                "UPDATE language_jobs SET stage=?,progress=?,updated_at=? "
                "WHERE id=? AND state='RUNNING'",
                (stage, progress, utc_now(), job_id),
            ).rowcount
            if changed != 1:
                row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
                if row is None:
                    raise LanguageNotFoundError("Language job was not found", code="language_job_not_found")
                return dict(row)
            row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row)

    def request_analysis_job_cancellation(self, job_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Language job was not found", code="language_job_not_found")
            if row["state"] == "QUEUED":
                connection.execute(
                    "UPDATE language_jobs SET state='CANCELLED',stage='CANCELLED',cancel_requested=1,"
                    "progress=NULL,completed_at=?,updated_at=? WHERE id=?",
                    (now, now, job_id),
                )
            elif row["state"] == "RUNNING":
                connection.execute(
                    "UPDATE language_jobs SET stage='CANCELLING',cancel_requested=1,updated_at=? WHERE id=?",
                    (now, job_id),
                )
            updated = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(updated)

    def mark_analysis_job_cancelled(self, job_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "UPDATE language_jobs SET state='CANCELLED',stage='CANCELLED',cancel_requested=1,"
                "progress=NULL,completed_at=?,updated_at=? WHERE id=? AND state IN ('QUEUED','RUNNING')",
                (now, now, job_id),
            )
            row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Language job was not found", code="language_job_not_found")
        return dict(row)

    def complete_preview_job(self, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Language job was not found", code="language_job_not_found")
            if row["state"] != "RUNNING":
                raise LanguageConflictError("Language job is not running", code="invalid_language_job_transition")
            if row["cancel_requested"]:
                connection.execute(
                    "UPDATE language_jobs SET state='CANCELLED',stage='CANCELLED',progress=NULL,"
                    "completed_at=?,updated_at=? WHERE id=?",
                    (now, now, job_id),
                )
            else:
                connection.execute(
                    "UPDATE language_jobs SET state='COMPLETED',stage='COMPLETED',progress=1,"
                    "result_json=?,completed_at=?,updated_at=? WHERE id=?",
                    (canonical_json(result), now, now, job_id),
                )
            updated = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(updated)

    def fail_analysis_job(self, job_id: str, *, error_code: str, error_message: str) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Language job was not found", code="language_job_not_found")
            if row["state"] != "RUNNING":
                return dict(row)
            if row["cancel_requested"]:
                state, stage = "CANCELLED", "CANCELLED"
                error_code = error_message = None
            else:
                state, stage = "FAILED", "FAILED"
                if row["job_type"] != "REANALYSIS_PREVIEW" and row["analysis_domain"] == "TEXT":
                    connection.execute(
                        "INSERT INTO analysis_runs("
                        "id,language_profile_id,text_document_id,analyzer_id,analyzer_version,contract_version,"
                        "state,content_fingerprint,started_at,completed_at,error_code,provenance_json,created_at,"
                        "job_id,analysis_fingerprint,analysis_policy_version,frequency_provider_id,"
                        "frequency_provider_version,coverage_policy_version) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            new_id(), row["language_profile_id"], row["text_document_id"], row["analyzer_id"],
                            row["analyzer_version"], row["contract_version"], "FAILED",
                            row["content_fingerprint"], row["started_at"], now, error_code, "{}", now,
                            row["id"], row["analysis_fingerprint"], row["analysis_policy_version"],
                            row["frequency_provider_id"], row["frequency_provider_version"],
                            row["coverage_policy_version"],
                        ),
                    )
                    connection.execute(
                        "UPDATE text_documents SET processing_state='ANALYSIS_FAILED',updated_at=? WHERE id=? "
                        "AND NOT EXISTS(SELECT 1 FROM analysis_runs WHERE text_document_id=? AND state='COMPLETED')",
                        (now, row["text_document_id"], row["text_document_id"]),
                    )
            connection.execute(
                "UPDATE language_jobs SET state=?,stage=?,progress=NULL,error_code=?,error_message=?,"
                "completed_at=?,updated_at=? WHERE id=?",
                (state, stage, error_code, error_message, now, now, job_id),
            )
            updated = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(updated)

    @staticmethod
    def _analysis_lemma(
        connection: sqlite3.Connection,
        profile_id: str,
        candidate: Any,
        now: str,
    ) -> dict[str, Any]:
        canonical_key = f"{candidate.normalized_lemma}|{candidate.pos or ''}"
        row = connection.execute(
            "SELECT * FROM vocabulary_lemmas WHERE language_profile_id=? AND canonical_key=?",
            (profile_id, canonical_key),
        ).fetchone()
        if row is None:
            lemma_id = new_id()
            connection.execute(
                "INSERT INTO vocabulary_lemmas("
                "id,language_profile_id,lemma_display,lemma_normalized,part_of_speech,canonical_key,"
                "source_kind,source_id,source_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lemma_id, profile_id, candidate.lemma, candidate.normalized_lemma, candidate.pos,
                    canonical_key, "ANALYZER", candidate.source_id, candidate.source_version, now, now,
                ),
            )
            connection.execute(
                "INSERT INTO lemma_knowledge(lemma_id,updated_at) VALUES(?,?)", (lemma_id, now)
            )
            row = connection.execute(
                "SELECT * FROM vocabulary_lemmas WHERE id=?", (lemma_id,)
            ).fetchone()
        if row["merged_into_id"]:
            row = connection.execute(
                "SELECT * FROM vocabulary_lemmas WHERE id=?", (row["merged_into_id"],)
            ).fetchone()
        return dict(row)

    @staticmethod
    def _analysis_form(
        connection: sqlite3.Connection,
        profile_id: str,
        display: str,
        normalized: str,
        now: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM surface_forms WHERE language_profile_id=? AND form_normalized=?",
            (profile_id, normalized),
        ).fetchone()
        if row is None:
            form_id = new_id()
            connection.execute(
                "INSERT INTO surface_forms(id,language_profile_id,form_display,form_normalized,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (form_id, profile_id, display, normalized, now, now),
            )
            row = connection.execute("SELECT * FROM surface_forms WHERE id=?", (form_id,)).fetchone()
        return dict(row)

    @staticmethod
    def _analysis_mapping(
        connection: sqlite3.Connection,
        profile_id: str,
        form_id: str,
        lemma_id: str,
        token: Any,
        candidate: Any,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        row = connection.execute(
            "SELECT * FROM form_lemma_links WHERE form_id=? AND lemma_id=?", (form_id, lemma_id)
        ).fetchone()
        if row is not None and int(row["manual_locked"]):
            return dict(row), True
        values = (
            candidate.source_id,
            candidate.source_version,
            canonical_json(dict(candidate.morphology)),
            candidate.confidence,
            token.ambiguity_state.value,
            token.lexical_status.value,
            "ANALYZER",
            now,
        )
        if row is None:
            link_id = new_id()
            connection.execute(
                "INSERT INTO form_lemma_links("
                "id,language_profile_id,form_id,lemma_id,provider_id,provider_version,morphology_json,"
                "confidence,ambiguity_state,lexical_status,mapping_provenance,manual_locked,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (link_id, profile_id, form_id, lemma_id, *values[:-1], now, now),
            )
            row = connection.execute("SELECT * FROM form_lemma_links WHERE id=?", (link_id,)).fetchone()
        else:
            connection.execute(
                "UPDATE form_lemma_links SET provider_id=?,provider_version=?,morphology_json=?,confidence=?,"
                "ambiguity_state=?,lexical_status=?,mapping_provenance=?,updated_at=? WHERE id=?",
                (*values, row["id"]),
            )
            row = connection.execute("SELECT * FROM form_lemma_links WHERE id=?", (row["id"],)).fetchone()
        return dict(row), False

    @staticmethod
    def _analysis_frequency(
        connection: sqlite3.Connection,
        profile_id: str,
        lemma_id: str,
        frequency: dict[str, Any],
        now: str,
    ) -> None:
        connection.execute(
            "INSERT INTO lemma_frequency(lemma_id,language_profile_id,metric,score,lookup_value,match_kind,"
            "provider_id,provider_version,retrieval_version,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(lemma_id,metric,provider_id) DO UPDATE SET score=excluded.score,"
            "lookup_value=excluded.lookup_value,match_kind=excluded.match_kind,"
            "provider_version=excluded.provider_version,retrieval_version=excluded.retrieval_version,"
            "observed_at=excluded.observed_at",
            (
                lemma_id, profile_id, frequency["metric"], frequency["score"], frequency["lookup_value"],
                frequency["match_kind"], frequency["provider_id"], frequency["provider_version"],
                frequency["retrieval_version"], frequency.get("observed_at") or now,
            ),
        )

    def commit_analysis_job(
        self,
        job_id: str,
        analysis: Any,
        *,
        frequencies: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace one text's analyzed structure and complete its job in one transaction."""
        now = utc_now()
        with self.connection() as connection:
            job = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
            if job is None:
                raise LanguageNotFoundError("Language job was not found", code="language_job_not_found")
            if job["state"] != "RUNNING":
                raise LanguageConflictError("Language job is not running", code="invalid_language_job_transition")
            document = connection.execute(
                "SELECT * FROM text_documents WHERE id=?", (job["text_document_id"],)
            ).fetchone()
            if document is None:
                raise LanguageNotFoundError("Text was not found", code="language_text_not_found")
            if (
                analysis.original_text != document["raw_text"]
                or analysis.original_text_fingerprint != document["content_fingerprint"]
                or analysis.offset_unit != OFFSET_UNIT
            ):
                raise LanguageConflictError(
                    "Analysis no longer matches the stored text", code="stale_language_analysis"
                )
            if job["cancel_requested"]:
                connection.execute(
                    "UPDATE language_jobs SET state='CANCELLED',stage='CANCELLED',progress=NULL,"
                    "completed_at=?,updated_at=? WHERE id=?",
                    (now, now, job_id),
                )
                return {"cancelled": True, "job": dict(connection.execute(
                    "SELECT * FROM language_jobs WHERE id=?", (job_id,)
                ).fetchone())}

            if connection.execute("SELECT 1 FROM grammar_analysis_runs WHERE text_document_id=? LIMIT 1", (document["id"],)).fetchone():
                raise LanguageConflictError("Grammar history protects canonical sentence identity; import a new text revision", code="grammar_text_reanalysis_blocked")
            connection.execute("DELETE FROM text_sentences WHERE text_document_id=?", (document["id"],))
            token_order = 0
            protected_conflicts = 0
            for sentence_order, sentence in enumerate(analysis.sentences):
                sentence_id = new_id()
                connection.execute(
                    "INSERT INTO text_sentences("
                    "id,text_document_id,sentence_order,source_start,source_end,offset_unit,exact_text,fingerprint) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        sentence_id, document["id"], sentence_order, sentence.start, sentence.end,
                        OFFSET_UNIT, sentence.text, text_fingerprint(sentence.text),
                    ),
                )
                for token in sentence.tokens:
                    form = None
                    candidate_rows: dict[str, dict[str, Any]] = {}
                    selected_lemma_id = None
                    mapping_reference: dict[str, Any] = {
                        "analyzerResolution": token.resolution_state.value,
                        "analyzerSelectedLemma": token.selected_lemma,
                        "selectionProvenance": "ANALYZER" if token.selected_lemma else None,
                        "effectiveResolution": token.resolution_state.value,
                    }
                    resolution_state = token.resolution_state.value
                    ambiguity_state = token.ambiguity_state.value
                    part_of_speech = token.pos
                    occurrence_provenance = token.provenance
                    if token.kind.value == "WORD" and token.normalized_lookup:
                        form = self._analysis_form(
                            connection,
                            document["language_profile_id"],
                            token.surface,
                            token.normalized_lookup,
                            now,
                        )
                        for candidate in token.lemma_candidates:
                            lemma = self._analysis_lemma(
                                connection, document["language_profile_id"], candidate, now
                            )
                            key = f"{candidate.normalized_lemma}|{candidate.pos or ''}"
                            candidate_rows[key] = lemma
                            self._analysis_mapping(
                                connection,
                                document["language_profile_id"],
                                form["id"],
                                lemma["id"],
                                token,
                                candidate,
                                now,
                            )
                            frequency = frequencies.get(key)
                            if frequency:
                                self._analysis_frequency(
                                    connection,
                                    document["language_profile_id"],
                                    lemma["id"],
                                    frequency,
                                    now,
                                )
                        locked = connection.execute(
                            "SELECT fl.lemma_id,l.lemma_display,l.lemma_normalized,l.part_of_speech "
                            "FROM form_lemma_links fl JOIN vocabulary_lemmas l ON l.id=fl.lemma_id "
                            "WHERE fl.form_id=? AND fl.manual_locked=1 ORDER BY fl.created_at,fl.id",
                            (form["id"],),
                        ).fetchall()
                        if len(locked) == 1:
                            selected_lemma_id = locked[0]["lemma_id"]
                            resolution_state = "MODEL_SELECTED"
                            ambiguity_state = "NOT_REPORTED"
                            part_of_speech = locked[0]["part_of_speech"]
                            occurrence_provenance = (
                                "manual_lock_selected; analyzer_evidence=" + token.provenance
                            )
                            mapping_reference["manualLockProtected"] = True
                            mapping_reference["manualLemmaId"] = selected_lemma_id
                            mapping_reference["selectionProvenance"] = "MANUAL_LOCK"
                            mapping_reference["effectiveResolution"] = "MANUAL_SELECTED"
                            analyzer_ids = {row["id"] for row in candidate_rows.values()}
                            mapping_reference["analyzerDisagreed"] = selected_lemma_id not in analyzer_ids
                            if mapping_reference["analyzerDisagreed"]:
                                protected_conflicts += 1
                        elif len(locked) > 1:
                            resolution_state = "AMBIGUOUS"
                            ambiguity_state = "AMBIGUOUS"
                            mapping_reference["manualLockConflict"] = [row["lemma_id"] for row in locked]
                            mapping_reference["selectionProvenance"] = None
                            mapping_reference["effectiveResolution"] = "AMBIGUOUS"
                            protected_conflicts += 1
                        elif token.selected_lemma is not None:
                            for candidate in token.lemma_candidates:
                                if candidate.lemma == token.selected_lemma:
                                    key = f"{candidate.normalized_lemma}|{candidate.pos or ''}"
                                    selected_lemma_id = candidate_rows[key]["id"]
                                    break

                    connection.execute(
                        "INSERT INTO text_tokens("
                        "id,language_profile_id,text_document_id,sentence_id,token_order,surface,source_start,source_end,"
                        "offset_unit,token_kind,normalized_lookup,surface_form_id,selected_lemma_id,"
                        "mapping_evidence_reference,part_of_speech,morphology_json,provider_id,provider_version,"
                        "ambiguity_state,lexical_status,confidence,resolution_state,confidence_basis,provenance) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            new_id(), document["language_profile_id"], document["id"], sentence_id,
                            token_order, token.surface, token.start, token.end, OFFSET_UNIT, token.kind.value,
                            token.normalized_lookup, form["id"] if form else None, selected_lemma_id,
                            canonical_json(mapping_reference), part_of_speech, canonical_json(dict(token.morphology)),
                            analysis.analyzer.analyzer_id, analysis.analyzer.implementation_version,
                            ambiguity_state, token.lexical_status.value, token.confidence, resolution_state,
                            token.confidence_basis, occurrence_provenance,
                        ),
                    )
                    token_order += 1

            run_id = new_id()
            connection.execute(
                "INSERT INTO analysis_runs("
                "id,language_profile_id,text_document_id,analyzer_id,analyzer_version,contract_version,state,"
                "content_fingerprint,started_at,completed_at,error_code,provenance_json,created_at,job_id,"
                "analysis_fingerprint,analysis_policy_version,frequency_provider_id,frequency_provider_version,"
                "coverage_policy_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, document["language_profile_id"], document["id"],
                    analysis.analyzer.analyzer_id, analysis.analyzer.implementation_version,
                    analysis.contract_version, "COMPLETED", document["content_fingerprint"], job["started_at"],
                    now, None, canonical_json(analysis.analyzer.to_dict()), now, job["id"],
                    job["analysis_fingerprint"], job["analysis_policy_version"],
                    job["frequency_provider_id"], job["frequency_provider_version"],
                    job["coverage_policy_version"],
                ),
            )
            connection.execute(
                "UPDATE text_documents SET processing_state='ANALYZED',updated_at=? WHERE id=?",
                (now, document["id"]),
            )
            result = {
                "textDocumentId": document["id"],
                "analysisRunId": run_id,
                "tokenCount": token_order,
                "sentenceCount": len(analysis.sentences),
                "manualLockConflictsProtected": protected_conflicts,
            }
            connection.execute(
                "UPDATE language_jobs SET state='COMPLETED',stage='COMPLETED',progress=1,result_json=?,"
                "error_code=NULL,error_message=NULL,completed_at=?,updated_at=? WHERE id=?",
                (canonical_json(result), now, now, job_id),
            )
            completed = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        return {"cancelled": False, "job": dict(completed), "analysisRunId": run_id}

    def create_session(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        session_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            client_id = values.get("client_session_id")
            if client_id:
                existing = connection.execute(
                    "SELECT * FROM study_sessions WHERE language_profile_id=? AND client_session_id=?",
                    (values["language_profile_id"], client_id),
                ).fetchone()
                if existing:
                    return dict(existing), False
            try:
                connection.execute(
                    "INSERT INTO study_sessions"
                    "(id,language_profile_id,text_document_id,session_type,status,client_session_id,started_at,ended_at,"
                    "active_seconds,created_at,updated_at,activity_state,last_heartbeat_at,last_active_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        session_id, values["language_profile_id"], values.get("text_document_id"), values["session_type"],
                        values.get("status", "ACTIVE"), client_id, values.get("started_at") or now, values.get("ended_at"),
                        values.get("active_seconds", 0), now, now,
                        values.get("activity_state", "PAUSED"),
                        now if values.get("activity_state") == "ACTIVE" else None,
                        now if values.get("activity_state") == "ACTIVE" else None,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError("Study session relationship is invalid", code="invalid_session_relationship") from exc
            row = connection.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row), True

    @staticmethod
    def _elapsed_reader_seconds(previous: str | None, current: str) -> int:
        if not previous:
            return 0
        try:
            before = datetime.fromisoformat(previous.replace("Z", "+00:00"))
            after = datetime.fromisoformat(current.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return 0
        return min(READER_HEARTBEAT_CAP_SECONDS, max(0, int((after - before).total_seconds())))

    def update_reader_session(
        self,
        session_id: str,
        *,
        action: str,
        command_id: str,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM study_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise LanguageNotFoundError(
                    "Study session was not found", code="language_study_session_not_found"
                )
            current = dict(row)
            if current["session_type"] != "READER":
                raise LanguageConflictError(
                    "Only Reader sessions support this lifecycle",
                    code="invalid_reader_session",
                )
            if current.get("last_command_id") == command_id:
                return current, False

            status = current["status"]
            activity_state = current.get("activity_state") or "PAUSED"
            active_seconds = int(current.get("active_seconds") or 0)
            ended_at = current.get("ended_at")
            last_heartbeat = current.get("last_heartbeat_at")
            last_active = current.get("last_active_at")

            if status == "COMPLETED" and action != "COMPLETE":
                raise LanguageConflictError(
                    "Completed Reader sessions cannot be resumed",
                    code="reader_session_completed",
                )
            if action in {"HEARTBEAT", "PAUSE", "COMPLETE"} and activity_state == "ACTIVE":
                elapsed = self._elapsed_reader_seconds(last_heartbeat, now)
                active_seconds += elapsed
                if elapsed:
                    last_active = now
            if action == "RESUME":
                if status != "ACTIVE":
                    raise LanguageConflictError(
                        "Only an active Reader session can be resumed",
                        code="invalid_reader_session_state",
                    )
                activity_state = "ACTIVE"
                last_heartbeat = now
            elif action == "HEARTBEAT":
                if status != "ACTIVE" or activity_state != "ACTIVE":
                    raise LanguageConflictError(
                        "Paused Reader sessions do not accept heartbeats",
                        code="reader_session_paused",
                    )
                last_heartbeat = now
            elif action == "PAUSE":
                if status != "ACTIVE":
                    raise LanguageConflictError(
                        "Only an active Reader session can be paused",
                        code="invalid_reader_session_state",
                    )
                activity_state = "PAUSED"
                last_heartbeat = None
            elif action == "COMPLETE":
                status = "COMPLETED"
                activity_state = "PAUSED"
                ended_at = ended_at or now
                last_heartbeat = None
            else:
                raise LanguageConflictError(
                    "Reader session action is invalid", code="invalid_reader_session_action"
                )

            connection.execute(
                "UPDATE study_sessions SET status=?,activity_state=?,active_seconds=?,ended_at=?,"
                "last_heartbeat_at=?,last_active_at=?,last_command_id=?,updated_at=? WHERE id=?",
                (
                    status,
                    activity_state,
                    active_seconds,
                    ended_at,
                    last_heartbeat,
                    last_active,
                    command_id,
                    now,
                    session_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM study_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return dict(updated), True

    def get_reader_session(self, session_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM study_sessions WHERE id=? AND session_type='READER'",
                (session_id,),
            ).fetchone()
        if row is None:
            raise LanguageNotFoundError(
                "Study session was not found", code="language_study_session_not_found"
            )
        return dict(row)

    def record_exposure(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        occurred_at = values.get("occurred_at") or now
        exposure_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM exposure_events WHERE language_profile_id=? AND idempotency_key=?",
                (values["language_profile_id"], values["idempotency_key"]),
            ).fetchone()
            if existing:
                return dict(existing), False
            lemma = connection.execute(
                "SELECT merged_into_id FROM vocabulary_lemmas WHERE id=? AND language_profile_id=?",
                (values["lemma_id"], values["language_profile_id"]),
            ).fetchone()
            if not lemma:
                raise LanguageConflictError("Exposure lemma belongs to another profile", code="cross_profile_relationship")
            lemma_id = str(lemma["merged_into_id"] or values["lemma_id"])
            try:
                connection.execute(
                    "INSERT INTO exposure_events"
                    "(id,idempotency_key,language_profile_id,lemma_id,surface_form_id,text_document_id,sentence_id,token_id,"
                    "study_session_id,source_type,occurrence_count,occurred_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        exposure_id, values["idempotency_key"], values["language_profile_id"], lemma_id,
                        values.get("surface_form_id"), values.get("text_document_id"), values.get("sentence_id"),
                        values.get("token_id"), values["study_session_id"], values["source_type"],
                        values["occurrence_count"], occurred_at, now,
                    ),
                )
                connection.execute(
                    "UPDATE lemma_knowledge SET total_exposures=total_exposures+?,"
                    "first_seen_at=COALESCE(first_seen_at,?),last_seen_at=?,updated_at=? WHERE lemma_id=?",
                    (values["occurrence_count"], occurred_at, occurred_at, now, lemma_id),
                )
                self._event(
                    connection,
                    lemma_id=lemma_id,
                    event_type="EXPOSURE_RECORDED",
                    source="EXPOSURE",
                    idempotency_key=f"{values['language_profile_id']}:{values['idempotency_key']}",
                    payload={
                        "exposureId": exposure_id,
                        "occurrenceCount": values["occurrence_count"],
                        "sourceType": values["source_type"],
                        "studySessionId": values["study_session_id"],
                    },
                    created_at=occurred_at,
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError("Exposure relationships are invalid", code="invalid_exposure_relationship") from exc
            row = connection.execute("SELECT * FROM exposure_events WHERE id=?", (exposure_id,)).fetchone()
        return dict(row), True

    def record_reader_exposure_batch(
        self,
        *,
        session_id: str,
        text_id: str,
        sentence_id: str,
        idempotency_key: str,
        submitted_occurrences: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            session = connection.execute(
                "SELECT * FROM study_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if session is None:
                raise LanguageNotFoundError(
                    "Study session was not found", code="language_study_session_not_found"
                )
            if (
                session["session_type"] != "READER"
                or session["text_document_id"] != text_id
            ):
                raise LanguageConflictError(
                    "Exposure batch does not match the Reader session",
                    code="invalid_reader_exposure_relationship",
                )

            existing = connection.execute(
                "SELECT * FROM exposure_events WHERE language_profile_id=? "
                "AND batch_idempotency_key=? ORDER BY lemma_id,id",
                (session["language_profile_id"], idempotency_key),
            ).fetchall()
            if existing:
                if any(
                    row["study_session_id"] != session_id
                    or row["text_document_id"] != text_id
                    or row["sentence_id"] != sentence_id
                    for row in existing
                ):
                    raise LanguageConflictError(
                        "Exposure idempotency key was already used for another segment",
                        code="exposure_idempotency_conflict",
                    )
                return {
                    "created": False,
                    "duplicate": True,
                    "events": [dict(row) for row in existing],
                }

            sentence = connection.execute(
                "SELECT * FROM text_sentences WHERE id=? AND text_document_id=?",
                (sentence_id, text_id),
            ).fetchone()
            if sentence is None:
                raise LanguageConflictError(
                    "Exposure sentence does not belong to the analyzed text",
                    code="invalid_reader_exposure_relationship",
                )
            if session["status"] != "ACTIVE" or session["activity_state"] != "ACTIVE":
                raise LanguageConflictError(
                    "Reader exposures require an active session",
                    code="reader_session_paused",
                )

            canonical_rows = connection.execute(
                "SELECT selected_lemma_id,COUNT(*) AS occurrence_count "
                "FROM text_tokens WHERE text_document_id=? AND sentence_id=? "
                "AND token_kind='WORD' AND selected_lemma_id IS NOT NULL "
                "GROUP BY selected_lemma_id ORDER BY selected_lemma_id",
                (text_id, sentence_id),
            ).fetchall()
            canonical = [
                {
                    "lemma_id": str(row["selected_lemma_id"]),
                    "occurrence_count": int(row["occurrence_count"]),
                }
                for row in canonical_rows
            ]
            submitted = sorted(
                (
                    {
                        "lemma_id": str(item["lemma_id"]),
                        "occurrence_count": int(item["occurrence_count"]),
                    }
                    for item in submitted_occurrences
                ),
                key=lambda item: item["lemma_id"],
            )
            if submitted != canonical:
                raise LanguageConflictError(
                    "Exposure counts do not match the analyzed sentence",
                    code="invalid_reader_exposure_claim",
                )

            events: list[dict[str, Any]] = []
            for item in canonical:
                exposure_id = new_id()
                row_key = f"{idempotency_key}:{item['lemma_id']}"
                connection.execute(
                    "INSERT INTO exposure_events("
                    "id,idempotency_key,language_profile_id,lemma_id,text_document_id,sentence_id,"
                    "study_session_id,source_type,occurrence_count,occurred_at,created_at,batch_idempotency_key) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        exposure_id,
                        row_key,
                        session["language_profile_id"],
                        item["lemma_id"],
                        text_id,
                        sentence_id,
                        session_id,
                        "READER",
                        item["occurrence_count"],
                        now,
                        now,
                        idempotency_key,
                    ),
                )
                connection.execute(
                    "UPDATE lemma_knowledge SET total_exposures=total_exposures+?,"
                    "first_seen_at=COALESCE(first_seen_at,?),last_seen_at=?,updated_at=? WHERE lemma_id=?",
                    (
                        item["occurrence_count"],
                        now,
                        now,
                        now,
                        item["lemma_id"],
                    ),
                )
                self._event(
                    connection,
                    lemma_id=item["lemma_id"],
                    event_type="EXPOSURE_RECORDED",
                    source="EXPOSURE",
                    idempotency_key=f"{session['language_profile_id']}:{row_key}",
                    payload={
                        "exposureId": exposure_id,
                        "occurrenceCount": item["occurrence_count"],
                        "sourceType": "READER",
                        "studySessionId": session_id,
                        "sentenceId": sentence_id,
                        "batchIdempotencyKey": idempotency_key,
                    },
                    created_at=now,
                )
                events.append(
                    dict(
                        connection.execute(
                            "SELECT * FROM exposure_events WHERE id=?", (exposure_id,)
                        ).fetchone()
                    )
                )
        return {"created": True, "duplicate": False, "events": events}

    def create_listening_session(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        session_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT s.*,ls.mode,ls.activity_policy_version,ls.exposure_policy_version,"
                "ls.completion_policy_version FROM study_sessions s "
                "JOIN listening_sessions ls ON ls.study_session_id=s.id "
                "WHERE s.language_profile_id=? AND s.client_session_id=?",
                (values["language_profile_id"], values["client_session_id"]),
            ).fetchone()
            if existing:
                return dict(existing), False
            try:
                connection.execute(
                    "INSERT INTO study_sessions(id,language_profile_id,text_document_id,session_type,status,"
                    "client_session_id,started_at,active_seconds,created_at,updated_at,activity_state) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        session_id, values["language_profile_id"], values["text_document_id"],
                        "LISTENING", "ACTIVE", values["client_session_id"], now, 0, now, now, "ACTIVE",
                    ),
                )
                connection.execute(
                    "INSERT INTO listening_sessions(study_session_id,language_profile_id,text_document_id,mode,"
                    "activity_policy_version,exposure_policy_version,completion_policy_version,started_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        session_id, values["language_profile_id"], values["text_document_id"], values["mode"],
                        values["activity_policy_version"], values["exposure_policy_version"],
                        values["completion_policy_version"], now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError(
                    "Listening session relationship is invalid", code="invalid_listening_session_relationship"
                ) from exc
            row = connection.execute(
                "SELECT s.*,ls.mode,ls.activity_policy_version,ls.exposure_policy_version,"
                "ls.completion_policy_version FROM study_sessions s "
                "JOIN listening_sessions ls ON ls.study_session_id=s.id WHERE s.id=?",
                (session_id,),
            ).fetchone()
        return dict(row), True

    def get_listening_session(self, session_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT s.*,ls.mode,ls.activity_policy_version,ls.exposure_policy_version,"
                "ls.completion_policy_version FROM study_sessions s "
                "JOIN listening_sessions ls ON ls.study_session_id=s.id WHERE s.id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise LanguageNotFoundError(
                "Listening session was not found", code="listening_session_not_found"
            )
        return dict(row)

    def close_listening_session(
        self, session_id: str, *, command_id: str
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT s.* FROM study_sessions s JOIN listening_sessions ls "
                "ON ls.study_session_id=s.id WHERE s.id=?", (session_id,),
            ).fetchone()
            if row is None:
                raise LanguageNotFoundError(
                    "Listening session was not found", code="listening_session_not_found"
                )
            if row["last_command_id"] == command_id:
                return dict(row), False
            if row["status"] == "ACTIVE":
                progress = connection.execute(
                    "SELECT status FROM listening_progress WHERE language_profile_id=? AND text_document_id=?",
                    (row["language_profile_id"], row["text_document_id"]),
                ).fetchone()
                status = "COMPLETED" if progress and progress["status"] == "COMPLETED" else "CANCELLED"
                connection.execute(
                    "UPDATE study_sessions SET status=?,activity_state='PAUSED',ended_at=?,"
                    "last_command_id=?,updated_at=? WHERE id=?",
                    (status, now, command_id, now, session_id),
                )
            else:
                connection.execute(
                    "UPDATE study_sessions SET last_command_id=?,updated_at=? WHERE id=?",
                    (command_id, now, session_id),
                )
            updated = connection.execute(
                "SELECT * FROM study_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return dict(updated), True

    @staticmethod
    def _listening_progress_payload(
        connection: sqlite3.Connection, profile_id: str, text_id: str
    ) -> dict[str, Any]:
        document = connection.execute(
            "SELECT id,title,source_type,processing_state FROM text_documents "
            "WHERE id=? AND language_profile_id=?", (text_id, profile_id),
        ).fetchone()
        if document is None:
            raise LanguageNotFoundError("Language text was not found", code="language_text_not_found")
        sentence_count = int(connection.execute(
            "SELECT COUNT(*) FROM text_sentences WHERE text_document_id=?", (text_id,)
        ).fetchone()[0])
        completed_count = int(connection.execute(
            "SELECT COUNT(DISTINCT sentence_id) FROM listening_sentence_events "
            "WHERE language_profile_id=? AND text_document_id=? AND qualified=1",
            (profile_id, text_id),
        ).fetchone()[0])
        row = connection.execute(
            "SELECT lp.*,s.sentence_order FROM listening_progress lp "
            "LEFT JOIN text_sentences s ON s.id=lp.current_sentence_id "
            "WHERE lp.language_profile_id=? AND lp.text_document_id=?",
            (profile_id, text_id),
        ).fetchone()
        progress = dict(row) if row else {}
        status = progress.get("status") or "NOT_STARTED"
        return {
            "language_profile_id": profile_id,
            "text_document_id": text_id,
            "title": document["title"],
            "source_type": document["source_type"],
            "status": status,
            "current_sentence_id": progress.get("current_sentence_id"),
            "current_sentence_order": progress.get("sentence_order"),
            "eligible_sentence_count": sentence_count,
            "completed_sentence_count": completed_count,
            "completion_percent": round(completed_count * 100 / sentence_count, 1) if sentence_count else 0.0,
            "last_listened_at": progress.get("last_listened_at"),
            "completed_at": progress.get("completed_at"),
            "policy_version": progress.get("policy_version"),
        }

    def listening_progress(self, profile_id: str, text_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            return self._listening_progress_payload(connection, profile_id, text_id)

    def list_listening_materials(self, profile_id: str, *, limit: int = 100) -> dict[str, Any]:
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)
            ).fetchone():
                raise LanguageNotFoundError(
                    "Language profile was not found", code="language_profile_not_found"
                )
            rows = connection.execute(
                "SELECT d.id,d.title,d.source_type,d.updated_at,COUNT(DISTINCT s.id) AS sentence_count,"
                "lp.status AS listening_status,lp.current_sentence_id,lp.last_listened_at,lp.completed_at "
                "FROM text_documents d JOIN text_sentences s ON s.text_document_id=d.id "
                "LEFT JOIN listening_progress lp ON lp.text_document_id=d.id AND lp.language_profile_id=d.language_profile_id "
                "WHERE d.language_profile_id=? AND d.processing_state='ANALYZED' "
                "GROUP BY d.id ORDER BY COALESCE(lp.last_listened_at,d.updated_at) DESC,d.id LIMIT ?",
                (profile_id, max(1, min(int(limit), 200))),
            ).fetchall()
            items = []
            for row in rows:
                progress = self._listening_progress_payload(connection, profile_id, str(row["id"]))
                sessions = connection.execute(
                    "SELECT COUNT(DISTINCT ls.study_session_id) AS session_count,COALESCE(SUM(e.active_ms),0) AS active_ms "
                    "FROM listening_sessions ls LEFT JOIN listening_sentence_events e "
                    "ON e.study_session_id=ls.study_session_id "
                    "WHERE ls.language_profile_id=? AND ls.text_document_id=?",
                    (profile_id, row["id"]),
                ).fetchone()
                items.append({
                    **dict(row), **progress, **dict(sessions),
                    "listening_status": progress["status"],
                })
        return {"items": items, "total": len(items)}

    def record_listening_sentence_event(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        occurred_at = values.get("occurred_at") or now
        try:
            occurred = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
            if occurred.tzinfo is None:
                occurred = occurred.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise LanguageConflictError(
                "Listening event timestamp is invalid", code="invalid_listening_event_time"
            ) from exc
        local_day = occurred.astimezone(ZoneInfo("Europe/Warsaw")).date().isoformat()
        event_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            session = connection.execute(
                "SELECT s.*,ls.mode FROM study_sessions s JOIN listening_sessions ls "
                "ON ls.study_session_id=s.id WHERE s.id=?", (values["study_session_id"],),
            ).fetchone()
            if session is None:
                raise LanguageNotFoundError(
                    "Listening session was not found", code="listening_session_not_found"
                )
            existing = connection.execute(
                "SELECT * FROM listening_sentence_events WHERE study_session_id=? AND idempotency_key=?",
                (values["study_session_id"], values["idempotency_key"]),
            ).fetchone()
            if existing:
                if (
                    existing["sentence_id"] != values["sentence_id"]
                    or existing["outcome"] != values["outcome"]
                    or existing["playback_source"] != values["playback_source"]
                    or int(existing["active_ms"]) != int(values["active_ms"])
                    or int(existing["coverage_ms"]) != int(values["coverage_ms"])
                    or existing["duration_ms"] != values.get("duration_ms")
                    or existing["alignment_id"] != values.get("alignment_id")
                    or str(existing["metadata_json"]) != canonical_json(values.get("metadata") or {})
                ):
                    raise LanguageConflictError(
                        "Listening event idempotency key was reused for different evidence",
                        code="listening_event_idempotency_conflict",
                    )
                progress = self._listening_progress_payload(
                    connection, str(existing["language_profile_id"]), str(existing["text_document_id"])
                )
                exposures = connection.execute(
                    "SELECT * FROM exposure_events WHERE batch_idempotency_key=? ORDER BY lemma_id,id",
                    (f"listening:{existing['id']}",),
                ).fetchall()
                return {
                    "event": dict(existing), "created": False, "duplicate": True,
                    "progress": progress, "exposures": [dict(row) for row in exposures],
                }
            if session["status"] != "ACTIVE":
                raise LanguageConflictError(
                    "Listening session is no longer active", code="listening_session_closed"
                )
            if (
                session["language_profile_id"] != values["language_profile_id"]
                or session["text_document_id"] != values["text_document_id"]
            ):
                raise LanguageConflictError(
                    "Listening event does not match its session",
                    code="invalid_listening_event_relationship",
                )
            sentence = connection.execute(
                "SELECT 1 FROM text_sentences WHERE id=? AND text_document_id=?",
                (values["sentence_id"], values["text_document_id"]),
            ).fetchone()
            if sentence is None:
                raise LanguageConflictError(
                    "Listening sentence does not belong to the analyzed text",
                    code="invalid_listening_event_relationship",
                )
            exposure_awarded = bool(values["qualified"]) and bool(values.get("exposure_eligible", True)) and not connection.execute(
                "SELECT 1 FROM listening_sentence_events WHERE language_profile_id=? "
                "AND text_document_id=? AND sentence_id=? AND local_study_date=? AND exposure_awarded=1",
                (
                    values["language_profile_id"], values["text_document_id"],
                    values["sentence_id"], local_day,
                ),
            ).fetchone()
            connection.execute(
                "INSERT INTO listening_sentence_events(id,study_session_id,language_profile_id,text_document_id,"
                "sentence_id,idempotency_key,outcome,playback_source,active_ms,coverage_ms,duration_ms,completion_ratio,"
                "qualified,exposure_awarded,alignment_id,local_study_date,occurred_at,metadata_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id, values["study_session_id"], values["language_profile_id"],
                    values["text_document_id"], values["sentence_id"], values["idempotency_key"],
                    values["outcome"], values["playback_source"], values["active_ms"],
                    values["coverage_ms"], values.get("duration_ms"), values["completion_ratio"],
                    1 if values["qualified"] else 0, 1 if exposure_awarded else 0,
                    values.get("alignment_id"), local_day, occurred_at,
                    canonical_json(values.get("metadata") or {}), now,
                ),
            )
            total_active_ms = int(connection.execute(
                "SELECT COALESCE(SUM(active_ms),0) FROM listening_sentence_events WHERE study_session_id=?",
                (values["study_session_id"],),
            ).fetchone()[0])
            connection.execute(
                "UPDATE study_sessions SET active_seconds=?,last_active_at=?,updated_at=? WHERE id=?",
                (total_active_ms // 1000, occurred_at if values["active_ms"] else None, now, values["study_session_id"]),
            )
            exposures: list[dict[str, Any]] = []
            batch_key = f"listening:{event_id}"
            if exposure_awarded:
                canonical_rows = connection.execute(
                    "SELECT selected_lemma_id,COUNT(*) AS occurrence_count FROM text_tokens "
                    "WHERE text_document_id=? AND sentence_id=? AND token_kind='WORD' "
                    "AND selected_lemma_id IS NOT NULL GROUP BY selected_lemma_id ORDER BY selected_lemma_id",
                    (values["text_document_id"], values["sentence_id"]),
                ).fetchall()
                for item in canonical_rows:
                    exposure_id = new_id()
                    row_key = f"{batch_key}:{item['selected_lemma_id']}"
                    connection.execute(
                        "INSERT INTO exposure_events(id,idempotency_key,language_profile_id,lemma_id,text_document_id,"
                        "sentence_id,study_session_id,source_type,occurrence_count,occurred_at,created_at,batch_idempotency_key) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            exposure_id, row_key, values["language_profile_id"], item["selected_lemma_id"],
                            values["text_document_id"], values["sentence_id"], values["study_session_id"],
                            "LISTENING", int(item["occurrence_count"]), occurred_at, now, batch_key,
                        ),
                    )
                    connection.execute(
                        "UPDATE lemma_knowledge SET total_exposures=total_exposures+?,"
                        "first_seen_at=COALESCE(first_seen_at,?),last_seen_at=?,updated_at=? WHERE lemma_id=?",
                        (int(item["occurrence_count"]), occurred_at, occurred_at, now, item["selected_lemma_id"]),
                    )
                    self._event(
                        connection,
                        lemma_id=str(item["selected_lemma_id"]),
                        event_type="EXPOSURE_RECORDED",
                        source="EXPOSURE",
                        idempotency_key=f"{values['language_profile_id']}:{row_key}",
                        payload={
                            "exposureId": exposure_id,
                            "occurrenceCount": int(item["occurrence_count"]),
                            "sourceType": "LISTENING",
                            "studySessionId": values["study_session_id"],
                            "sentenceId": values["sentence_id"],
                            "batchIdempotencyKey": batch_key,
                        },
                        created_at=occurred_at,
                    )
                    exposures.append(dict(connection.execute(
                        "SELECT * FROM exposure_events WHERE id=?", (exposure_id,)
                    ).fetchone()))
            completed_count = int(connection.execute(
                "SELECT COUNT(DISTINCT sentence_id) FROM listening_sentence_events "
                "WHERE language_profile_id=? AND text_document_id=? AND qualified=1",
                (values["language_profile_id"], values["text_document_id"]),
            ).fetchone()[0])
            sentence_count = int(connection.execute(
                "SELECT COUNT(*) FROM text_sentences WHERE text_document_id=?",
                (values["text_document_id"],),
            ).fetchone()[0])
            progress_status = "COMPLETED" if sentence_count and completed_count >= sentence_count else "IN_PROGRESS"
            completed_at = occurred_at if progress_status == "COMPLETED" else None
            connection.execute(
                "INSERT INTO listening_progress(language_profile_id,text_document_id,current_sentence_id,status,"
                "policy_version,last_listened_at,completed_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(language_profile_id,text_document_id) DO UPDATE SET "
                "current_sentence_id=excluded.current_sentence_id,"
                "status=CASE WHEN listening_progress.status='COMPLETED' THEN 'COMPLETED' ELSE excluded.status END,"
                "policy_version=excluded.policy_version,last_listened_at=excluded.last_listened_at,"
                "completed_at=COALESCE(listening_progress.completed_at,excluded.completed_at),updated_at=excluded.updated_at",
                (
                    values["language_profile_id"], values["text_document_id"], values["sentence_id"],
                    progress_status, values["completion_policy_version"], occurred_at, completed_at, now,
                ),
            )
            if progress_status == "COMPLETED":
                connection.execute(
                    "UPDATE study_sessions SET status='COMPLETED',activity_state='PAUSED',ended_at=COALESCE(ended_at,?),"
                    "updated_at=? WHERE id=?", (occurred_at, now, values["study_session_id"]),
                )
            event = connection.execute(
                "SELECT * FROM listening_sentence_events WHERE id=?", (event_id,)
            ).fetchone()
            progress = self._listening_progress_payload(
                connection, values["language_profile_id"], values["text_document_id"]
            )
        return {
            "event": dict(event), "created": True, "duplicate": False,
            "progress": progress, "exposures": exposures,
        }

    def update_reading_progress(
        self,
        *,
        text_id: str,
        language_profile_id: str,
        progress_source_offset: int,
        progress_sentence_id: str | None,
        status: str,
        coverage_snapshot: dict[str, Any] | None,
        analysis_run_id: str | None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            document = connection.execute(
                "SELECT * FROM text_documents WHERE id=? AND language_profile_id=?",
                (text_id, language_profile_id),
            ).fetchone()
            if document is None:
                raise LanguageConflictError(
                    "Reading progress does not match the language profile",
                    code="invalid_reading_progress_relationship",
                )
            if progress_source_offset > len(document["raw_text"]):
                raise LanguageConflictError(
                    "Reading progress is outside the source text",
                    code="invalid_reading_progress_offset",
                )
            if progress_sentence_id and not connection.execute(
                "SELECT 1 FROM text_sentences WHERE id=? AND text_document_id=?",
                (progress_sentence_id, text_id),
            ).fetchone():
                raise LanguageConflictError(
                    "Reading progress sentence does not belong to the text",
                    code="invalid_reading_progress_relationship",
                )
            existing = connection.execute(
                "SELECT * FROM text_reading_progress WHERE text_document_id=?", (text_id,)
            ).fetchone()
            effective_status = status
            if existing and existing["status"] == "COMPLETED" and status != "COMPLETED":
                effective_status = "COMPLETED"
            completed_at = (
                (existing["completed_at"] if existing else None)
                or (now if effective_status == "COMPLETED" else None)
            )
            existing_snapshot = existing["coverage_snapshot_json"] if existing else None
            snapshot_json = existing_snapshot or (
                canonical_json(coverage_snapshot) if coverage_snapshot is not None else None
            )
            existing_run = existing["analysis_run_id"] if existing else None
            completion_run = existing_run or (
                analysis_run_id if effective_status == "COMPLETED" else None
            )
            if existing:
                connection.execute(
                    "UPDATE text_reading_progress SET status=?,progress_source_offset=?,"
                    "progress_sentence_id=?,last_read_at=?,completed_at=?,coverage_snapshot_json=?,"
                    "analysis_run_id=?,updated_at=? WHERE text_document_id=?",
                    (
                        effective_status,
                        progress_source_offset,
                        progress_sentence_id,
                        now,
                        completed_at,
                        snapshot_json,
                        completion_run,
                        now,
                        text_id,
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO text_reading_progress("
                    "text_document_id,language_profile_id,status,progress_source_offset,"
                    "progress_sentence_id,last_read_at,completed_at,coverage_snapshot_json,"
                    "analysis_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        text_id,
                        language_profile_id,
                        effective_status,
                        progress_source_offset,
                        progress_sentence_id,
                        now,
                        completed_at,
                        snapshot_json,
                        completion_run,
                        now,
                        now,
                    ),
                )
            row = connection.execute(
                "SELECT p.*,(SELECT COALESCE(SUM(s.active_seconds),0) FROM study_sessions s "
                "WHERE s.text_document_id=p.text_document_id AND s.session_type='READER') AS active_seconds "
                "FROM text_reading_progress p WHERE p.text_document_id=?",
                (text_id,),
            ).fetchone()
        return dict(row)

    def text_has_study_evidence(self, text_id: str) -> bool:
        with self.connection() as connection:
            exposure = connection.execute(
                "SELECT 1 FROM exposure_events WHERE text_document_id=? LIMIT 1", (text_id,)
            ).fetchone()
            progress = connection.execute(
                "SELECT 1 FROM text_reading_progress WHERE text_document_id=? "
                "AND status IN ('IN_PROGRESS','COMPLETED') LIMIT 1",
                (text_id,),
            ).fetchone()
            active_time = connection.execute(
                "SELECT 1 FROM study_sessions WHERE text_document_id=? AND active_seconds>0 LIMIT 1",
                (text_id,),
            ).fetchone()
        return bool(exposure or progress or active_time)

    def classifier_rows(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)
            ).fetchone():
                raise LanguageNotFoundError(
                    "Language profile was not found", code="language_profile_not_found"
                )
            rows = connection.execute(
                "SELECT l.id,l.lemma_display,l.lemma_normalized,l.part_of_speech,l.created_at,"
                "k.knowledge_status,k.disposition,k.recognition,k.recall,k.production,"
                "k.total_exposures,k.first_seen_at,k.last_seen_at,k.last_review_at,k.updated_at,"
                "(SELECT MIN(e.created_at) FROM knowledge_events e WHERE e.lemma_id=l.id "
                " AND e.event_type='MANUAL_KNOWLEDGE_UPDATE' "
                " AND (json_extract(e.payload_json,'$.applied.knowledge_status') IN "
                " ('LEARNING','KNOWN','MASTERED'))) AS first_advanced_at,"
                "(SELECT lf.score FROM lemma_frequency lf WHERE lf.lemma_id=l.id "
                " ORDER BY lf.observed_at DESC,lf.provider_id LIMIT 1) AS frequency_score "
                "FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id "
                "WHERE l.language_profile_id=? AND l.merged_into_id IS NULL "
                "ORDER BY l.lemma_normalized,l.id",
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def statistics_facts(self, profile_id: str) -> dict[str, list[dict[str, Any]]]:
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)
            ).fetchone():
                raise LanguageNotFoundError(
                    "Language profile was not found", code="language_profile_not_found"
                )
            lemmas = connection.execute(
                "SELECT l.id,l.created_at,l.merged_into_id,k.knowledge_status,k.disposition,"
                "k.recognition,k.recall,k.production,k.total_exposures,k.first_seen_at,"
                "k.last_seen_at,k.last_review_at FROM vocabulary_lemmas l "
                "JOIN lemma_knowledge k ON k.lemma_id=l.id "
                "WHERE l.language_profile_id=? AND l.merged_into_id IS NULL",
                (profile_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT e.* FROM knowledge_events e JOIN vocabulary_lemmas l ON l.id=e.lemma_id "
                "WHERE l.language_profile_id=? ORDER BY e.created_at,e.id",
                (profile_id,),
            ).fetchall()
            exposures = connection.execute(
                "SELECT e.* FROM exposure_events e WHERE e.language_profile_id=? "
                "ORDER BY e.occurred_at,e.id",
                (profile_id,),
            ).fetchall()
            sessions = connection.execute(
                "SELECT s.* FROM study_sessions s WHERE s.language_profile_id=? "
                "ORDER BY s.started_at,s.id",
                (profile_id,),
            ).fetchall()
            progress = connection.execute(
                "SELECT p.*,d.title,(SELECT COUNT(*) FROM text_tokens t "
                "WHERE t.text_document_id=p.text_document_id) AS token_count "
                "FROM text_reading_progress p JOIN text_documents d ON d.id=p.text_document_id "
                "WHERE p.language_profile_id=? ORDER BY p.updated_at,p.text_document_id",
                (profile_id,),
            ).fetchall()
            texts = connection.execute(
                "SELECT d.*,p.status AS reading_status,p.last_read_at,p.completed_at,"
                "p.progress_source_offset,(SELECT COALESCE(SUM(s.active_seconds),0) "
                "FROM study_sessions s WHERE s.text_document_id=d.id AND s.session_type='READER') "
                "AS active_seconds FROM text_documents d "
                "LEFT JOIN text_reading_progress p ON p.text_document_id=d.id "
                "WHERE d.language_profile_id=? ORDER BY d.updated_at DESC,d.id DESC",
                (profile_id,),
            ).fetchall()
            listening_events = connection.execute(
                "SELECT * FROM listening_sentence_events WHERE language_profile_id=? "
                "ORDER BY occurred_at,id", (profile_id,),
            ).fetchall()
            listening_progress = connection.execute(
                "SELECT lp.*,d.title,d.source_type FROM listening_progress lp "
                "JOIN text_documents d ON d.id=lp.text_document_id "
                "WHERE lp.language_profile_id=? ORDER BY lp.updated_at,lp.text_document_id",
                (profile_id,),
            ).fetchall()
        return {
            "lemmas": [dict(row) for row in lemmas],
            "events": [dict(row) for row in events],
            "exposures": [dict(row) for row in exposures],
            "sessions": [dict(row) for row in sessions],
            "progress": [dict(row) for row in progress],
            "texts": [dict(row) for row in texts],
            "listeningEvents": [dict(row) for row in listening_events],
            "listeningProgress": [dict(row) for row in listening_progress],
        }

    def create_topic(self, values: dict[str, Any]) -> dict[str, Any]:
        topic_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO topics(id,language_profile_id,slug,display_name,description,"
                    "parent_topic_id,archived,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        topic_id, values["language_profile_id"], values["slug"],
                        values["display_name"], values.get("description"),
                        values.get("parent_topic_id"), 1 if values.get("archived") else 0,
                        now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError(
                    "Topic identity or profile relationship is invalid",
                    code="invalid_topic_relationship",
                ) from exc
            row = connection.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
        return dict(row)

    def update_topic(self, topic_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {"slug", "display_name", "description", "parent_topic_id", "archived"}
        applied = {key: value for key, value in changes.items() if key in allowed}
        with self.connection() as connection:
            current = connection.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
            if current is None:
                raise LanguageNotFoundError("Topic was not found", code="language_topic_not_found")
            if applied:
                applied["updated_at"] = utc_now()
                sql = ",".join(f"{key}=?" for key in applied)
                try:
                    connection.execute(
                        f"UPDATE topics SET {sql} WHERE id=?", (*applied.values(), topic_id)
                    )
                except sqlite3.IntegrityError as exc:
                    raise LanguageConflictError(
                        "Topic identity or hierarchy is invalid", code="invalid_topic_relationship"
                    ) from exc
            row = connection.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
        return dict(row)

    def list_topics(self, profile_id: str, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "t.language_profile_id=?" + ("" if include_archived else " AND t.archived=0")
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)
            ).fetchone():
                raise LanguageNotFoundError(
                    "Language profile was not found", code="language_profile_not_found"
                )
            rows = connection.execute(
                "SELECT t.*,(SELECT COUNT(*) FROM topic_lemmas tl WHERE tl.topic_id=t.id) "
                f"AS mapped_lemma_count FROM topics t WHERE {where} "
                "ORDER BY t.archived,t.display_name,t.id",
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_topic(self, topic_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            topic = connection.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
            if topic is None:
                raise LanguageNotFoundError("Topic was not found", code="language_topic_not_found")
            lemmas = connection.execute(
                "SELECT tl.*,l.lemma_display,l.lemma_normalized,l.part_of_speech,"
                "k.knowledge_status,k.disposition,k.recognition,k.recall,k.production,"
                "k.total_exposures,k.first_seen_at,k.last_seen_at,"
                "(SELECT lf.score FROM lemma_frequency lf WHERE lf.lemma_id=l.id "
                " ORDER BY lf.observed_at DESC,lf.provider_id LIMIT 1) AS frequency_score "
                "FROM topic_lemmas tl JOIN vocabulary_lemmas l ON l.id=tl.lemma_id "
                "JOIN lemma_knowledge k ON k.lemma_id=l.id WHERE tl.topic_id=? "
                "ORDER BY l.lemma_normalized,l.id",
                (topic_id,),
            ).fetchall()
        return {"topic": dict(topic), "lemmas": [dict(row) for row in lemmas]}

    def upsert_topic_lemma(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM topic_lemmas WHERE topic_id=? AND lemma_id=?",
                (values["topic_id"], values["lemma_id"]),
            ).fetchone()
            try:
                if existing:
                    connection.execute(
                        "UPDATE topic_lemmas SET weight=?,provenance=?,membership_state=?,"
                        "source_reference=?,updated_at=? WHERE topic_id=? AND lemma_id=?",
                        (
                            values["weight"], values["provenance"], values["membership_state"],
                            values.get("source_reference"), now, values["topic_id"], values["lemma_id"],
                        ),
                    )
                else:
                    connection.execute(
                        "INSERT INTO topic_lemmas(topic_id,lemma_id,language_profile_id,weight,"
                        "provenance,membership_state,source_reference,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            values["topic_id"], values["lemma_id"], values["language_profile_id"],
                            values["weight"], values["provenance"], values["membership_state"],
                            values.get("source_reference"), now, now,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError(
                    "Topic and lemma must belong to the same profile",
                    code="cross_profile_relationship",
                ) from exc
            row = connection.execute(
                "SELECT * FROM topic_lemmas WHERE topic_id=? AND lemma_id=?",
                (values["topic_id"], values["lemma_id"]),
            ).fetchone()
        return dict(row), existing is None

    def remove_topic_lemma(self, topic_id: str, lemma_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM topic_lemmas WHERE topic_id=? AND lemma_id=?", (topic_id, lemma_id)
            )
        return cursor.rowcount > 0

    def create_goal(self, values: dict[str, Any]) -> dict[str, Any]:
        goal_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO goal_definitions(id,language_profile_id,metric,period,target_value,unit,"
                    "active_from,active_until,week_start,timezone,enabled,rule_version,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        goal_id, values["language_profile_id"], values["metric"], values["period"],
                        values["target_value"], values["unit"], values.get("active_from"),
                        values.get("active_until"), values["week_start"], values["timezone"],
                        1 if values.get("enabled", True) else 0, values["rule_version"], now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError("Goal relationship is invalid", code="invalid_goal_relationship") from exc
            row = connection.execute("SELECT * FROM goal_definitions WHERE id=?", (goal_id,)).fetchone()
        return dict(row)

    def update_goal(self, goal_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "metric", "period", "target_value", "unit", "active_from", "active_until",
            "week_start", "timezone", "enabled", "rule_version",
        }
        applied = {key: value for key, value in changes.items() if key in allowed}
        with self.connection() as connection:
            current = connection.execute("SELECT * FROM goal_definitions WHERE id=?", (goal_id,)).fetchone()
            if current is None:
                raise LanguageNotFoundError("Goal was not found", code="language_goal_not_found")
            if applied:
                applied["updated_at"] = utc_now()
                sql = ",".join(f"{key}=?" for key in applied)
                try:
                    connection.execute(
                        f"UPDATE goal_definitions SET {sql} WHERE id=?", (*applied.values(), goal_id)
                    )
                except sqlite3.IntegrityError as exc:
                    raise LanguageConflictError("Goal update is invalid", code="invalid_goal_relationship") from exc
            row = connection.execute("SELECT * FROM goal_definitions WHERE id=?", (goal_id,)).fetchone()
        return dict(row)

    def list_goals(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)
            ).fetchone():
                raise LanguageNotFoundError(
                    "Language profile was not found", code="language_profile_not_found"
                )
            rows = connection.execute(
                "SELECT * FROM goal_definitions WHERE language_profile_id=? "
                "ORDER BY enabled DESC,created_at,id",
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_goal(self, goal_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM goal_definitions WHERE id=?", (goal_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Goal was not found", code="language_goal_not_found")
        return dict(row)

    def get_anki_config(self, profile_id: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id)
        try:
            value = json.loads(profile.get("anki_config_json") or "{}")
        except json.JSONDecodeError:
            value = {}
        return value if isinstance(value, dict) else {}

    def update_anki_config(self, profile_id: str, config: dict[str, Any]) -> dict[str, Any]:
        return self.update_profile(profile_id, {"anki_config_json": canonical_json(config)})

    def observe_anki_daily_plans(self, profile_id: str, local_day: str,
                                 decks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Keep the first observed daily plan fixed as Anki's queue changes."""
        observed_at = utc_now()
        with self.connection() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO anki_daily_plans"
                "(language_profile_id,local_day,deck_name,planned_new,planned_reviews,observed_at) "
                "VALUES(?,?,?,?,?,?)",
                [(profile_id, local_day, deck["name"],
                  deck["newCompletedToday"] + deck["new"],
                  deck["reviewsCompletedToday"] + deck["due"], observed_at)
                 for deck in decks if "newCompletedToday" in deck],
            )
            rows = connection.execute(
                "SELECT deck_name,planned_new,planned_reviews,observed_at FROM anki_daily_plans "
                "WHERE language_profile_id=? AND local_day=?", (profile_id, local_day),
            ).fetchall()
        return {row["deck_name"]: dict(row) for row in rows}

    def recent_anki_daily_plans(self, profile_id: str, first_day: str) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT local_day,deck_name,planned_new+planned_reviews AS planned "
                "FROM anki_daily_plans WHERE language_profile_id=? AND local_day>=?",
                (profile_id, first_day),
            ).fetchall()
        by_day: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_day.setdefault(row["local_day"], []).append(dict(row))
        return {day: sum(row["planned"] for row in items
                         if row["deck_name"].casefold() != "default" and not any(
                             row["deck_name"].startswith(parent["deck_name"] + "::")
                             for parent in items if parent is not row
                         )) for day, items in by_day.items()}

    def anki_context(self, lemma_id: str, sentence_id: str | None = None) -> dict[str, Any] | None:
        with self.connection() as connection:
            parameters: list[Any] = [lemma_id]
            where = "t.selected_lemma_id=?"
            if sentence_id:
                where += " AND s.id=?"
                parameters.append(sentence_id)
            row = connection.execute(
                "SELECT s.id AS sentence_id,s.text_document_id,s.exact_text,s.source_start,s.source_end,"
                "d.title,d.source_type,d.source_reference,d.raw_text "
                "FROM text_tokens t JOIN text_sentences s ON s.id=t.sentence_id "
                "JOIN text_documents d ON d.id=s.text_document_id "
                f"WHERE {where} ORDER BY d.updated_at DESC,s.sentence_order ASC LIMIT 1",
                parameters,
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("exact_text") is None:
            text = str(result.get("raw_text") or "")
            result["exact_text"] = text[int(result["source_start"]):int(result["source_end"])]
        result.pop("raw_text", None)
        return result

    def get_anki_note_link(
        self, lemma_id: str, template_purpose: str = "VOCABULARY"
    ) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM anki_note_links WHERE lemma_id=? AND template_purpose=?",
                (lemma_id, template_purpose),
            ).fetchone()
        return self._row(row)

    def get_anki_note_link_by_external(self, external_note_id: int) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM anki_note_links WHERE external_note_id=?", (external_note_id,)
            ).fetchone()
        return self._row(row)

    def upsert_anki_note_link(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        link_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO anki_note_links(id,language_profile_id,lemma_id,template_purpose,"
                "external_note_id,deck_name,model_name,dashboard_key,source_document_id,source_sentence_id,"
                "last_pushed_hash,last_pulled_hash,last_local_fields_json,last_remote_fields_json,"
                "conflict_state,created_at,updated_at,last_sync_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(lemma_id,template_purpose) DO UPDATE SET "
                "external_note_id=excluded.external_note_id,deck_name=excluded.deck_name,model_name=excluded.model_name,"
                "dashboard_key=excluded.dashboard_key,source_document_id=excluded.source_document_id,"
                "source_sentence_id=excluded.source_sentence_id,last_pushed_hash=excluded.last_pushed_hash,"
                "last_pulled_hash=excluded.last_pulled_hash,last_local_fields_json=excluded.last_local_fields_json,"
                "last_remote_fields_json=excluded.last_remote_fields_json,conflict_state=excluded.conflict_state,"
                "updated_at=excluded.updated_at,last_sync_at=excluded.last_sync_at",
                (
                    link_id, values["language_profile_id"], values["lemma_id"], values["template_purpose"],
                    int(values["external_note_id"]), values["deck_name"], values["model_name"],
                    values["dashboard_key"], values.get("source_document_id"), values.get("source_sentence_id"),
                    values.get("last_pushed_hash"), values.get("last_pulled_hash"),
                    canonical_json(values.get("last_local_fields", {})),
                    canonical_json(values.get("last_remote_fields", {})), values.get("conflict_state", "NONE"),
                    values.get("created_at", now), now, values.get("last_sync_at", now),
                ),
            )
            row = connection.execute(
                "SELECT * FROM anki_note_links WHERE lemma_id=? AND template_purpose=?",
                (values["lemma_id"], values["template_purpose"]),
            ).fetchone()
        return dict(row)

    def set_anki_link_conflict(
        self,
        link_id: str,
        *,
        state: str,
        local_fields: dict[str, Any],
        remote_fields: dict[str, Any],
        local_hash: str | None = None,
        remote_hash: str | None = None,
        synced: bool = False,
    ) -> dict[str, Any]:
        now = utc_now()
        assignments = [
            "conflict_state=?", "last_local_fields_json=?", "last_remote_fields_json=?", "updated_at=?"
        ]
        values: list[Any] = [state, canonical_json(local_fields), canonical_json(remote_fields), now]
        if synced:
            assignments.extend(["last_pushed_hash=?", "last_pulled_hash=?", "last_sync_at=?"])
            values.extend([local_hash, remote_hash, now])
        values.append(link_id)
        with self.connection() as connection:
            connection.execute(f"UPDATE anki_note_links SET {','.join(assignments)} WHERE id=?", values)
            row = connection.execute("SELECT * FROM anki_note_links WHERE id=?", (link_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Anki note link was not found", code="anki_link_not_found")
        return dict(row)

    def anki_link_detail(self, lemma_id: str, template_purpose: str = "VOCABULARY") -> dict[str, Any] | None:
        link = self.get_anki_note_link(lemma_id, template_purpose)
        if link is None:
            return None
        with self.connection() as connection:
            cards = [dict(row) for row in connection.execute(
                "SELECT * FROM anki_card_snapshots WHERE note_link_id=? ORDER BY external_card_id",
                (link["id"],),
            )]
        return {"link": link, "cards": cards}

    def replace_anki_card_snapshots(
        self, link_id: str, external_note_id: int, cards: list[dict[str, Any]], observed_at: str
    ) -> list[dict[str, Any]]:
        with self.connection() as connection:
            connection.execute("DELETE FROM anki_card_snapshots WHERE note_link_id=?", (link_id,))
            for card in cards:
                connection.execute(
                    "INSERT INTO anki_card_snapshots(external_card_id,note_link_id,external_note_id,deck_name,"
                    "queue,card_type,due,interval,ease,reviews,lapses,observed_at,raw_supported_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        int(card["cardId"]), link_id, int(external_note_id), card.get("deckName"),
                        card.get("queue"), card.get("type"), card.get("due"), card.get("interval"),
                        card.get("factor"), card.get("reps", card.get("reviews")), card.get("lapses"), observed_at,
                        canonical_json(card),
                    ),
                )
            rows = connection.execute(
                "SELECT * FROM anki_card_snapshots WHERE note_link_id=? ORDER BY external_card_id", (link_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def create_anki_sync_run(self, profile_id: str, mode: str, capability: dict[str, Any]) -> dict[str, Any]:
        run_id = new_id()
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO anki_sync_runs(id,language_profile_id,mode,status,counts_json,warnings_json,"
                "errors_json,capability_snapshot_json,result_json,started_at) VALUES(?,?,?,'RUNNING','{}','[]','[]',?,'{}',?)",
                (run_id, profile_id, mode, canonical_json(capability), now),
            )
            row = connection.execute("SELECT * FROM anki_sync_runs WHERE id=?", (run_id,)).fetchone()
        return dict(row)

    def finish_anki_sync_run(
        self, run_id: str, *, status: str, counts: dict[str, Any], warnings: list[Any],
        errors: list[Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute(
                "UPDATE anki_sync_runs SET status=?,counts_json=?,warnings_json=?,errors_json=?,"
                "result_json=?,completed_at=? WHERE id=?",
                (status, canonical_json(counts), canonical_json(warnings), canonical_json(errors),
                 canonical_json(result), utc_now(), run_id),
            )
            row = connection.execute("SELECT * FROM anki_sync_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Anki sync run was not found", code="anki_sync_run_not_found")
        return dict(row)

    def list_anki_sync_runs(self, profile_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM anki_sync_runs WHERE language_profile_id=? "
                "ORDER BY started_at DESC,id DESC LIMIT ?", (profile_id, max(1, min(limit, 100)))
            )]

    def anki_profile_summary(self, profile_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            linked = int(connection.execute(
                "SELECT COUNT(*) FROM anki_note_links WHERE language_profile_id=?", (profile_id,)
            ).fetchone()[0])
            conflicts = int(connection.execute(
                "SELECT COUNT(*) FROM anki_note_links WHERE language_profile_id=? AND conflict_state='BOTH_CHANGED'",
                (profile_id,),
            ).fetchone()[0])
            last = connection.execute(
                "SELECT * FROM anki_sync_runs WHERE language_profile_id=? ORDER BY started_at DESC,id DESC LIMIT 1",
                (profile_id,),
            ).fetchone()
        return {"linkedVocabulary": linked, "conflicts": conflicts, "lastRun": self._row(last)}

    def record_anki_evidence(
        self, lemma_id: str, *, idempotency_key: str, payload: dict[str, Any], created_at: str
    ) -> tuple[dict[str, Any], bool]:
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM knowledge_events WHERE source='ANKI' AND idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing:
                return dict(existing), False
            event_id = self._event(
                connection, lemma_id=lemma_id, event_type="ANKI_CARD_SNAPSHOT", source="ANKI",
                idempotency_key=idempotency_key, payload=payload, created_at=created_at,
            )
            row = connection.execute("SELECT * FROM knowledge_events WHERE id=?", (event_id,)).fetchone()
        return dict(row), True

    def apply_anki_knowledge_signal(
        self, lemma_id: str, *, idempotency_key: str, status: str,
        recognition: int, payload: dict[str, Any]
    ) -> bool:
        """Import a new Anki answer signal once; explicit Reader overrides keep priority."""
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT 1 FROM knowledge_events WHERE source='ANKI_REVIEW' AND idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return False
            current = connection.execute(
                "SELECT * FROM lemma_knowledge WHERE lemma_id=?", (lemma_id,)
            ).fetchone()
            if current is None:
                raise LanguageNotFoundError("Lemma was not found", code="language_lemma_not_found")
            changes: dict[str, Any] = {}
            if not current["manual_status_override"] and current["knowledge_status"] != status:
                changes["knowledge_status"] = status
            if not current["manual_scores_override"] and current["recognition"] != recognition:
                changes["recognition"] = recognition
            if changes:
                changes["updated_at"] = utc_now()
                sql = ",".join(f"{key}=?" for key in changes)
                connection.execute(f"UPDATE lemma_knowledge SET {sql} WHERE lemma_id=?", (*changes.values(), lemma_id))
            self._event(
                connection, lemma_id=lemma_id, event_type="ANKI_KNOWLEDGE_SIGNAL",
                source="ANKI_REVIEW", idempotency_key=idempotency_key,
                payload={"ruleVersion": "language.anki-knowledge/v1", "estimate": payload,
                         "applied": changes, "manualStatusProtected": bool(current["manual_status_override"]),
                         "manualScoresProtected": bool(current["manual_scores_override"])},
            )
        return True

    def merge_lemmas(self, source_id: str, target_id: str, *, source: str, note: str | None = None) -> dict[str, Any]:
        if source_id == target_id:
            raise LanguageConflictError("A lemma cannot be merged into itself", code="invalid_lemma_merge")
        with self.connection() as connection:
            source_row = connection.execute("SELECT * FROM vocabulary_lemmas WHERE id=?", (source_id,)).fetchone()
            target_row = connection.execute("SELECT * FROM vocabulary_lemmas WHERE id=?", (target_id,)).fetchone()
            if source_row is None or target_row is None:
                raise LanguageNotFoundError("Lemma was not found", code="language_lemma_not_found")
            if source_row["language_profile_id"] != target_row["language_profile_id"]:
                raise LanguageConflictError("Lemmas must belong to the same profile", code="cross_profile_relationship")
            if source_row["merged_into_id"]:
                raise LanguageConflictError("Source lemma is already merged", code="lemma_is_merged")
            if target_row["merged_into_id"]:
                raise LanguageConflictError("Target lemma is merged", code="lemma_is_merged")

            source_anki_links = connection.execute(
                "SELECT * FROM anki_note_links WHERE lemma_id=?", (source_id,)
            ).fetchall()
            for anki_link in source_anki_links:
                duplicate = connection.execute(
                    "SELECT 1 FROM anki_note_links WHERE lemma_id=? AND template_purpose=?",
                    (target_id, anki_link["template_purpose"]),
                ).fetchone()
                if duplicate:
                    raise LanguageConflictError(
                        "Both lemmas have an Anki link for the same purpose",
                        code="anki_link_merge_conflict",
                    )
                connection.execute(
                    "UPDATE anki_note_links SET lemma_id=?,conflict_state='LOCAL_CHANGED',updated_at=? WHERE id=?",
                    (target_id, utc_now(), anki_link["id"]),
                )

            source_links = connection.execute("SELECT * FROM form_lemma_links WHERE lemma_id=?", (source_id,)).fetchall()
            for link in source_links:
                target_link = connection.execute(
                    "SELECT * FROM form_lemma_links WHERE form_id=? AND lemma_id=?", (link["form_id"], target_id)
                ).fetchone()
                if target_link:
                    if int(link["manual_locked"]) and not int(target_link["manual_locked"]):
                        connection.execute(
                            "UPDATE form_lemma_links SET provider_id=?,provider_version=?,morphology_json=?,confidence=?,"
                            "ambiguity_state=?,lexical_status=?,mapping_provenance='MANUAL',manual_locked=1,"
                            "manual_provenance=?,updated_at=? WHERE id=?",
                            (
                                link["provider_id"], link["provider_version"], link["morphology_json"], link["confidence"],
                                link["ambiguity_state"], link["lexical_status"], link["manual_provenance"], utc_now(),
                                target_link["id"],
                            ),
                        )
                    connection.execute("DELETE FROM form_lemma_links WHERE id=?", (link["id"],))
                else:
                    connection.execute("UPDATE form_lemma_links SET lemma_id=?,updated_at=? WHERE id=?", (target_id, utc_now(), link["id"]))

            connection.execute("UPDATE text_tokens SET selected_lemma_id=? WHERE selected_lemma_id=?", (target_id, source_id))
            connection.execute("UPDATE exposure_events SET lemma_id=? WHERE lemma_id=?", (target_id, source_id))
            connection.execute("UPDATE cloze_attempts SET target_lemma_id=? WHERE target_lemma_id=?", (target_id, source_id))
            source_topics = connection.execute(
                "SELECT * FROM topic_lemmas WHERE lemma_id=?", (source_id,)
            ).fetchall()
            for membership in source_topics:
                target_membership = connection.execute(
                    "SELECT * FROM topic_lemmas WHERE topic_id=? AND lemma_id=?",
                    (membership["topic_id"], target_id),
                ).fetchone()
                if target_membership:
                    connection.execute(
                        "UPDATE topic_lemmas SET weight=?,provenance=?,membership_state=?,"
                        "source_reference=COALESCE(source_reference,?),updated_at=? "
                        "WHERE topic_id=? AND lemma_id=?",
                        (
                            max(float(target_membership["weight"]), float(membership["weight"])),
                            "MANUAL" if "MANUAL" in {target_membership["provenance"], membership["provenance"]} else "IMPORT",
                            "MANUAL" if "MANUAL" in {target_membership["membership_state"], membership["membership_state"]} else "IMPORTED",
                            membership["source_reference"], utc_now(), membership["topic_id"], target_id,
                        ),
                    )
                    connection.execute(
                        "DELETE FROM topic_lemmas WHERE topic_id=? AND lemma_id=?",
                        (membership["topic_id"], source_id),
                    )
                else:
                    connection.execute(
                        "UPDATE topic_lemmas SET lemma_id=?,updated_at=? WHERE topic_id=? AND lemma_id=?",
                        (target_id, utc_now(), membership["topic_id"], source_id),
                    )
            source_knowledge = connection.execute("SELECT * FROM lemma_knowledge WHERE lemma_id=?", (source_id,)).fetchone()
            target_knowledge = connection.execute("SELECT * FROM lemma_knowledge WHERE lemma_id=?", (target_id,)).fetchone()
            if source_knowledge and target_knowledge:
                status = target_knowledge["knowledge_status"]
                disposition = target_knowledge["disposition"]
                if source_knowledge["manual_status_override"] and not target_knowledge["manual_status_override"]:
                    status = source_knowledge["knowledge_status"]
                    disposition = source_knowledge["disposition"]
                score_values = {}
                for field in ("recognition", "recall", "production"):
                    values = [value for value in (target_knowledge[field], source_knowledge[field]) if value is not None]
                    score_values[field] = max(values) if values else None
                connection.execute(
                    "UPDATE lemma_knowledge SET knowledge_status=?,disposition=?,recognition=?,recall=?,production=?,"
                    "total_exposures=?,first_seen_at=COALESCE(first_seen_at,?),"
                    "last_seen_at=CASE WHEN last_seen_at IS NULL OR last_seen_at<? THEN ? ELSE last_seen_at END,"
                    "manual_status_override=?,manual_scores_override=?,manual_override_source=COALESCE(manual_override_source,?),"
                    "updated_at=? WHERE lemma_id=?",
                    (
                        status, disposition, score_values["recognition"], score_values["recall"], score_values["production"],
                        int(target_knowledge["total_exposures"]) + int(source_knowledge["total_exposures"]),
                        source_knowledge["first_seen_at"], source_knowledge["last_seen_at"], source_knowledge["last_seen_at"],
                        int(target_knowledge["manual_status_override"] or source_knowledge["manual_status_override"]),
                        int(target_knowledge["manual_scores_override"] or source_knowledge["manual_scores_override"]),
                        source_knowledge["manual_override_source"], utc_now(), target_id,
                    ),
                )
                connection.execute("DELETE FROM lemma_knowledge WHERE lemma_id=?", (source_id,))
            source_notes = source_row["user_notes"]
            target_notes = target_row["user_notes"]
            if source_notes and source_notes != target_notes:
                merged_notes = source_notes if not target_notes else f"{target_notes}\n\n{source_notes}"
                connection.execute(
                    "UPDATE vocabulary_lemmas SET user_notes=?,updated_at=? WHERE id=?",
                    (merged_notes, utc_now(), target_id),
                )
            connection.execute(
                "UPDATE vocabulary_lemmas SET merged_into_id=?,updated_at=? WHERE id=?",
                (target_id, utc_now(), source_id),
            )
            event_id = self._event(
                connection,
                lemma_id=target_id,
                event_type="LEMMA_MERGED",
                source=source,
                payload={"sourceLemmaId": source_id, "targetLemmaId": target_id, "note": note},
            )
        return {"sourceLemmaId": source_id, "targetLemmaId": target_id, "eventId": event_id}

    # Generation candidates remain outside the Reader until explicit acceptance.
    def create_generation_request(self, values: dict[str, Any]) -> dict[str, Any]:
        request_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO generation_requests(id,language_profile_id,topic_id,custom_topic,"
                    "requested_length,requested_token_coverage,difficulty_preset,explicit_target_lemma_ids_json,"
                    "grammar_focus,style_instruction,selection_rule_version,coverage_policy_version,"
                    "knowledge_snapshot_fingerprint,knowledge_snapshot_json,target_snapshot_json,prompt_version,"
                    "prompt_fingerprint,context_pack_json,status,created_at,updated_at,generation_mode,"
                    "provider_id,provider_adapter_version,model_id,provider_policy,max_provider_attempts,"
                    "automatic_status,automatic_stage,automatic_progress,context_preparation_ms) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (request_id, values["language_profile_id"], values.get("topic_id"), values.get("custom_topic"),
                     values["requested_length"], values["requested_token_coverage"], values["difficulty_preset"],
                     canonical_json(values.get("explicit_target_lemma_ids", [])), values.get("grammar_focus"),
                     values.get("style_instruction"), values["selection_rule_version"], values["coverage_policy_version"],
                     values["knowledge_snapshot_fingerprint"], canonical_json(values["knowledge_snapshot"]),
                     canonical_json(values["target_snapshot"]), values["prompt_version"], values["prompt_fingerprint"],
                     canonical_json(values["context_pack"]), "READY", now, now,
                     values.get("generation_mode", "MANUAL"), values.get("provider_id"),
                     values.get("provider_adapter_version"), values.get("model_id"),
                     values.get("provider_policy"), int(values.get("max_provider_attempts") or 0),
                     values.get("automatic_status", "NOT_REQUESTED"), values.get("automatic_stage"),
                     values.get("automatic_progress"), values.get("context_preparation_ms")),
                )
            except sqlite3.IntegrityError as exc:
                raise LanguageConflictError("Generation request references invalid profile data", code="invalid_generation_request_relationship") from exc
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
        return dict(row)

    def get_generation_request(self, request_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Generation request was not found", code="generation_request_not_found")
        return dict(row)

    def list_generation_candidates(self, request_id: str) -> list[dict[str, Any]]:
        self.get_generation_request(request_id)
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM generation_candidates WHERE generation_request_id=? ORDER BY attempt_number DESC,id", (request_id,)).fetchall()
        return [dict(row) for row in rows]

    def create_generation_candidate(self, values: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            if not connection.execute("SELECT 1 FROM generation_requests WHERE id=?", (values["generation_request_id"],)).fetchone():
                raise LanguageNotFoundError("Generation request was not found", code="generation_request_not_found")
            attempt = int(connection.execute("SELECT COALESCE(MAX(attempt_number),0)+1 FROM generation_candidates WHERE generation_request_id=?", (values["generation_request_id"],)).fetchone()[0])
            connection.execute(
                "INSERT INTO generation_candidates(id,generation_request_id,attempt_number,source,provider_label,model_label,"
                "raw_response,import_format,title,extracted_text,validation_status,status,created_at,updated_at,"
                "origin_mode,provider_request_id,provider_model_version,finish_reason,usage_metadata_json,"
                "provider_latency_ms,transport_attempt_count,provider_status,error_class,revision_prompt_fingerprint) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (candidate_id,values["generation_request_id"],attempt,"MANUAL_EXTERNAL_LLM",values.get("provider_label"),
                 values.get("model_label"),values["raw_response"],values["import_format"],values["title"],
                 values["extracted_text"],values.get("validation_status", "VALID"),values.get("status", "IMPORTED"),now,now,
                 values.get("origin_mode", "MANUAL"), values.get("provider_request_id"),
                 values.get("provider_model_version"), values.get("finish_reason"),
                 canonical_json(values.get("usage_metadata") or {}), values.get("provider_latency_ms"),
                 int(values.get("transport_attempt_count") or 0), values.get("provider_status"),
                 values.get("error_class"), values.get("revision_prompt_fingerprint")),
            )
            connection.execute("UPDATE generation_requests SET status='HAS_CANDIDATES',updated_at=? WHERE id=?", (now,values["generation_request_id"]))
            row = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row)

    def queue_automatic_generation(self, request_id: str, *, max_pending: int = 100) -> tuple[dict[str, Any], bool]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Generation request was not found", code="generation_request_not_found")
            if row["generation_mode"] != "AUTOMATIC":
                raise LanguageConflictError("Request is not configured for automatic generation", code="generation_request_not_automatic")
            if row["automatic_status"] in {
                "QUEUED", "RUNNING", "READY", "OUT_OF_TOLERANCE", "FAILED", "CANCELLED",
            }:
                return dict(row), False
            pending = int(connection.execute(
                "SELECT COUNT(*) FROM generation_requests WHERE automatic_status IN ('QUEUED','RUNNING')"
            ).fetchone()[0])
            if pending >= max_pending:
                raise LanguageConflictError("Language generation queue is full", code="language_job_queue_full")
            now = utc_now()
            connection.execute(
                "UPDATE generation_requests SET automatic_status='QUEUED',automatic_stage='PREPARING_CONTEXT',"
                "automatic_progress=0,cancel_requested=0,automatic_error_code=NULL,automatic_error_message=NULL,"
                "automatic_started_at=COALESCE(automatic_started_at,?),automatic_completed_at=NULL,updated_at=? WHERE id=?",
                (now, now, request_id),
            )
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
        return dict(row), True

    def claim_next_automatic_generation(self) -> dict[str, Any] | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM generation_requests WHERE automatic_status='QUEUED' ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            connection.execute(
                "UPDATE generation_requests SET automatic_status='RUNNING',automatic_stage='PREPARING_CONTEXT',"
                "automatic_progress=.02,updated_at=? WHERE id=? AND automatic_status='QUEUED'",
                (now, row["id"]),
            )
            claimed = connection.execute("SELECT * FROM generation_requests WHERE id=?", (row["id"],)).fetchone()
        return dict(claimed)

    def update_automatic_generation(
        self, request_id: str, *, stage: str, progress: float | None = None,
        usage: dict[str, Any] | None = None, revision_preparation_ms: float | None = None,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute(
                "UPDATE generation_requests SET automatic_stage=?,automatic_progress=?,"
                "automatic_usage_json=COALESCE(?,automatic_usage_json),"
                "revision_preparation_ms=COALESCE(?,revision_preparation_ms),updated_at=? WHERE id=?",
                (stage, progress, canonical_json(usage) if usage is not None else None,
                 revision_preparation_ms, utc_now(), request_id),
            )
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
        return dict(row)

    def cancel_automatic_generation(self, request_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Generation request was not found", code="generation_request_not_found")
            now = utc_now()
            if row["automatic_status"] == "QUEUED":
                connection.execute(
                    "UPDATE generation_requests SET cancel_requested=1,automatic_status='CANCELLED',"
                    "automatic_stage='CANCELLED',automatic_progress=NULL,automatic_completed_at=?,updated_at=? WHERE id=?",
                    (now, now, request_id),
                )
            elif row["automatic_status"] == "RUNNING":
                connection.execute(
                    "UPDATE generation_requests SET cancel_requested=1,automatic_stage='CANCELLING',updated_at=? WHERE id=?",
                    (now, request_id),
                )
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
        return dict(row)

    def automatic_generation_cancelled(self, request_id: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM generation_requests WHERE id=?", (request_id,)
            ).fetchone()
        return bool(row and row[0])

    def finish_automatic_generation(
        self, request_id: str, *, status: str, stage: str, best_candidate_id: str | None = None,
        error_code: str | None = None, error_message: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "UPDATE generation_requests SET automatic_status=?,automatic_stage=?,automatic_progress=?,"
                "best_candidate_id=?,automatic_error_code=?,automatic_error_message=?,"
                "automatic_usage_json=COALESCE(?,automatic_usage_json),automatic_completed_at=?,updated_at=? WHERE id=?",
                (status, stage, 1.0 if status in {"READY", "OUT_OF_TOLERANCE"} else None,
                 best_candidate_id, error_code, error_message,
                 canonical_json(usage) if usage is not None else None, now, now, request_id),
            )
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", (request_id,)).fetchone()
        return dict(row)

    def recover_automatic_generation_requests(self) -> dict[str, int]:
        now = utc_now()
        with self.connection() as connection:
            cancelled = connection.execute(
                "UPDATE generation_requests SET automatic_status='CANCELLED',automatic_stage='CANCELLED',"
                "automatic_completed_at=?,updated_at=? WHERE automatic_status='RUNNING' AND cancel_requested=1",
                (now, now),
            ).rowcount
            requeued = connection.execute(
                "UPDATE generation_requests SET automatic_status='QUEUED',automatic_stage='RECOVERED',"
                "updated_at=? WHERE automatic_status='RUNNING' AND cancel_requested=0",
                (now,),
            ).rowcount
        return {"requeued": requeued, "cancelled": cancelled}

    def generation_candidate_rows(self, request_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM generation_candidates WHERE generation_request_id=? ORDER BY attempt_number,id",
                (request_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_generation_candidate(self, candidate_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT c.*,r.language_profile_id,r.requested_length,r.requested_token_coverage,r.knowledge_snapshot_json,"
                "r.target_snapshot_json,r.coverage_policy_version,r.prompt_version,r.prompt_fingerprint "
                "FROM generation_candidates c JOIN generation_requests r ON r.id=c.generation_request_id WHERE c.id=?", (candidate_id,)
            ).fetchone()
        if row is None:
            raise LanguageNotFoundError("Generation candidate was not found", code="generation_candidate_not_found")
        return dict(row)

    def queue_generation_candidate(self, candidate_id: str, *, max_pending: int = 100) -> tuple[dict[str, Any], bool]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (candidate_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Generation candidate was not found", code="generation_candidate_not_found")
            if row["status"] in {"QUEUED","ANALYZING","IN_TOLERANCE","OUT_OF_TOLERANCE","ACCEPTED"}:
                return dict(row), False
            if row["status"] == "REJECTED":
                raise LanguageConflictError("Rejected candidate cannot be analyzed", code="generation_candidate_rejected")
            pending = int(connection.execute("SELECT COUNT(*) FROM generation_candidates WHERE status IN ('QUEUED','ANALYZING')").fetchone()[0])
            if pending >= max_pending:
                raise LanguageConflictError("Language analysis queue is full", code="language_job_queue_full")
            connection.execute("UPDATE generation_candidates SET status='QUEUED',error_code=NULL,error_message=NULL,updated_at=? WHERE id=?", (utc_now(),candidate_id))
            row = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row), True

    def recover_generation_candidates(self, *, max_attempts: int = 3) -> dict[str, int]:
        now = utc_now()
        with self.connection() as connection:
            failed = connection.execute("UPDATE generation_candidates SET status='FAILED',error_code='generation_recovery_limit',error_message='Generation analysis exceeded the recovery limit',updated_at=? WHERE status='ANALYZING' AND analysis_attempt_count>=?", (now,max_attempts)).rowcount
            requeued = connection.execute("UPDATE generation_candidates SET status='QUEUED',updated_at=? WHERE status='ANALYZING' AND analysis_attempt_count<?", (now,max_attempts)).rowcount
        return {"requeued": failed * 0 + requeued, "failed": failed}

    def claim_next_generation_candidate(self) -> dict[str, Any] | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM generation_candidates WHERE status='QUEUED' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:
                return None
            connection.execute("UPDATE generation_candidates SET status='ANALYZING',analysis_attempt_count=analysis_attempt_count+1,updated_at=? WHERE id=? AND status='QUEUED'", (utc_now(),row["id"]))
            claimed = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (row["id"],)).fetchone()
        return dict(claimed)

    def complete_generation_candidate(self, candidate_id: str, result: dict[str, Any], *, status: str) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            connection.execute("UPDATE generation_candidates SET status=?,analysis_json=?,analyzer_id=?,analyzer_version=?,error_code=NULL,error_message=NULL,analyzed_at=?,updated_at=? WHERE id=?", (status,canonical_json(result),result["analyzer"]["analyzerId"],result["analyzer"]["implementationVersion"],now,now,candidate_id))
            row = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row)

    def fail_generation_candidate(self, candidate_id: str, *, error_code: str, error_message: str) -> None:
        with self.connection() as connection:
            connection.execute("UPDATE generation_candidates SET status='FAILED',error_code=?,error_message=?,updated_at=? WHERE id=?", (error_code,error_message,utc_now(),candidate_id))

    def reject_generation_candidate(self, candidate_id: str, reason: str | None) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (candidate_id,)).fetchone()
            if row is None:
                raise LanguageNotFoundError("Generation candidate was not found", code="generation_candidate_not_found")
            if row["status"] == "ACCEPTED":
                raise LanguageConflictError("Accepted candidate cannot be rejected", code="generation_candidate_accepted")
            if row["status"] in {"QUEUED", "ANALYZING"}:
                raise LanguageConflictError("Candidate analysis must finish before rejection", code="generation_candidate_busy")
            connection.execute("UPDATE generation_candidates SET status='REJECTED',rejection_reason=?,rejected_at=?,updated_at=? WHERE id=?", (reason,now,now,candidate_id))
            row = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row)

    def accept_generation_candidate(self, candidate_id: str, text_values: dict[str, Any], job_values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
        now = utc_now()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute("SELECT * FROM generation_candidates WHERE id=?", (candidate_id,)).fetchone()
            if candidate is None:
                raise LanguageNotFoundError("Generation candidate was not found", code="generation_candidate_not_found")
            if candidate["accepted_text_document_id"]:
                document = connection.execute("SELECT * FROM text_documents WHERE id=?", (candidate["accepted_text_document_id"],)).fetchone()
                job = connection.execute("SELECT * FROM language_jobs WHERE id=?", (candidate["accepted_analysis_job_id"],)).fetchone()
                return dict(document), dict(job), False
            if candidate["status"] not in {"IN_TOLERANCE","OUT_OF_TOLERANCE"}:
                raise LanguageConflictError("Candidate must finish analysis before acceptance", code="generation_candidate_not_ready")
            text_id = new_id()
            connection.execute("INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,source_reference,content_fingerprint,processing_state,offset_unit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (text_id,text_values["language_profile_id"],text_values["title"],text_values["raw_text"],text_values.get("source_type", "GENERATED_MANUAL_LLM"),text_values.get("source_reference"),text_values["content_fingerprint"],"DRAFT",OFFSET_UNIT,now,now))
            if text_values.get("series_id"):
                series_id = text_values["series_id"]
                if connection.execute("SELECT 1 FROM reading_series WHERE id=? AND language_profile_id=?", (series_id, text_values["language_profile_id"])).fetchone() is None:
                    raise LanguageNotFoundError("Reading series was not found", code="reading_series_not_found")
                previous_id = text_values.get("previous_text_id")
                if previous_id and connection.execute("SELECT 1 FROM reading_series_episodes WHERE series_id=? AND text_document_id=?", (series_id, previous_id)).fetchone() is None:
                    raise LanguageConflictError("Previous episode is no longer in this series", code="reading_series_previous_changed")
                episode_number = connection.execute("SELECT COALESCE(MAX(episode_number),0)+1 FROM reading_series_episodes WHERE series_id=?", (series_id,)).fetchone()[0]
                connection.execute("INSERT INTO reading_series_episodes(text_document_id,language_profile_id,series_id,episode_number,previous_text_id,created_at) VALUES(?,?,?,?,?,?)", (text_id,text_values["language_profile_id"],series_id,episode_number,previous_id,now))
            job_id = new_id()
            connection.execute("INSERT INTO language_jobs(id,language_profile_id,text_document_id,job_type,job_version,analyzer_id,analyzer_version,contract_version,analysis_policy_version,frequency_provider_id,frequency_provider_version,coverage_policy_version,content_fingerprint,analysis_fingerprint,state,stage,progress,request_json,cancel_requested,attempt_count,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id,job_values["language_profile_id"],text_id,"ANALYZE",job_values["job_version"],job_values["analyzer_id"],job_values["analyzer_version"],job_values["contract_version"],job_values["analysis_policy_version"],job_values["frequency_provider_id"],job_values["frequency_provider_version"],job_values["coverage_policy_version"],job_values["content_fingerprint"],job_values["analysis_fingerprint"],"QUEUED","QUEUED",0,canonical_json(job_values["request"]),0,0,now,now))
            connection.execute("UPDATE generation_candidates SET status='ACCEPTED',accepted_text_document_id=?,accepted_analysis_job_id=?,accepted_at=?,updated_at=? WHERE id=?", (text_id,job_id,now,now,candidate_id))
            connection.execute("UPDATE generation_requests SET status='ACCEPTED',updated_at=? WHERE id=?", (now,candidate["generation_request_id"]))
            document = connection.execute("SELECT * FROM text_documents WHERE id=?", (text_id,)).fetchone()
            job = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(document), dict(job), True

    def cloze_shared_targets(self, profile_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return bounded canonical learner targets with direct Cloze evidence in one query."""
        bounded = max(1, min(int(limit), 1000))
        with self.connection() as connection:
            rows = connection.execute(
                "WITH ranked_attempts AS ("
                " SELECT a.target_lemma_id,a.outcome,a.attempted_at,a.id,"
                " ROW_NUMBER() OVER (PARTITION BY a.target_lemma_id ORDER BY a.attempted_at DESC,a.id DESC) AS rn"
                " FROM cloze_attempts a JOIN cloze_sessions s ON s.id=a.session_id"
                " WHERE s.language_profile_id=?),"
                " attempt_counts AS (SELECT target_lemma_id,COUNT(*) AS attempt_count,"
                " SUM(CASE WHEN outcome='CORRECT' THEN 1 ELSE 0 END) AS correct_count,"
                " SUM(CASE WHEN outcome IN ('INCORRECT','REVEALED') THEN 1 ELSE 0 END) AS negative_count"
                " FROM ranked_attempts GROUP BY target_lemma_id)"
                " SELECT l.id,l.lemma_display,l.lemma_normalized,l.part_of_speech,l.source_kind,l.source_id,"
                " l.source_version,l.created_at,k.knowledge_status,k.disposition,k.recognition,k.recall,"
                " k.production,k.total_exposures,k.first_seen_at,k.last_seen_at,k.last_review_at,"
                " COALESCE(c.attempt_count,0) AS attempt_count,COALESCE(c.correct_count,0) AS correct_count,"
                " COALESCE(c.negative_count,0) AS negative_count,r.outcome AS last_outcome,"
                " r.attempted_at AS last_attempted_at"
                " FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id"
                " LEFT JOIN attempt_counts c ON c.target_lemma_id=l.id"
                " LEFT JOIN ranked_attempts r ON r.target_lemma_id=l.id AND r.rn=1"
                " WHERE l.language_profile_id=? AND l.merged_into_id IS NULL AND k.disposition='TRACKED'"
                " ORDER BY l.lemma_normalized,l.part_of_speech,l.id LIMIT ?",
                (profile_id, profile_id, bounded),
            ).fetchall()
        return [dict(row) for row in rows]

    def cloze_reader_contexts(
        self, profile_id: str, lemma_ids: list[str], *, maximum_rows: int = 4000,
    ) -> list[dict[str, Any]]:
        """Fetch exact analyzed sentence/token contexts in bounded batches, never per target."""
        unique_ids = sorted({str(value) for value in lemma_ids if value})[:1000]
        if not unique_ids:
            return []
        rows: list[dict[str, Any]] = []
        with self.connection() as connection:
            for offset in range(0, len(unique_ids), 250):
                batch = unique_ids[offset:offset + 250]
                placeholders = ",".join("?" for _ in batch)
                found = connection.execute(
                    "SELECT t.id AS token_id,t.selected_lemma_id,t.surface,t.source_start AS token_start,"
                    "t.source_end AS token_end,t.token_order,t.token_kind,t.part_of_speech,t.morphology_json,"
                    "t.ambiguity_state,t.lexical_status,t.resolution_state,t.provider_id,t.provider_version,"
                    "s.id AS sentence_id,s.sentence_order,s.source_start AS sentence_start,"
                    "s.source_end AS sentence_end,s.exact_text AS sentence_text,s.fingerprint AS sentence_fingerprint,"
                    "d.id AS text_document_id,d.title AS document_title,d.source_type AS document_source_type,"
                    "d.source_reference,d.content_fingerprint,d.updated_at AS document_updated_at,"
                    "l.lemma_display,l.lemma_normalized,l.part_of_speech AS lemma_part_of_speech,"
                    "gc.id AS generation_candidate_id,gc.generation_request_id"
                    " FROM text_tokens t JOIN text_sentences s ON s.id=t.sentence_id"
                    " JOIN text_documents d ON d.id=t.text_document_id"
                    " JOIN vocabulary_lemmas l ON l.id=t.selected_lemma_id"
                    " LEFT JOIN generation_candidates gc ON gc.accepted_text_document_id=d.id"
                    " WHERE t.language_profile_id=? AND d.processing_state='ANALYZED'"
                    " AND (d.source_type NOT LIKE 'GENERATED_%' OR gc.id IS NOT NULL)"
                    " AND t.token_kind='WORD' AND t.selected_lemma_id IN (" + placeholders + ")"
                    " ORDER BY t.selected_lemma_id,d.updated_at DESC,d.id,s.sentence_order,t.token_order"
                    " LIMIT ?",
                    (profile_id, *batch, max(1, min(int(maximum_rows), 10000))),
                ).fetchall()
                rows.extend(dict(row) for row in found)
        return rows

    def cloze_phrasebook_contexts(
        self, profile_id: str, lemma_ids: list[str], *, maximum_rows: int = 1000,
    ) -> list[dict[str, Any]]:
        unique_ids = sorted({str(value) for value in lemma_ids if value})[:1000]
        if not unique_ids:
            return []
        rows: list[dict[str, Any]] = []
        with self.connection() as connection:
            for offset in range(0, len(unique_ids), 250):
                batch = unique_ids[offset:offset + 250]
                placeholders = ",".join("?" for _ in batch)
                found = connection.execute(
                    "SELECT p.*,link.link_value AS target_lemma_id,link.metadata_json AS link_metadata_json"
                    " FROM phrasebook_entries p JOIN phrasebook_entry_links link ON link.entry_id=p.id"
                    " WHERE p.language_profile_id=? AND link.link_type='LEMMA'"
                    " AND link.link_value IN (" + placeholders + ")"
                    " ORDER BY link.link_value,p.updated_at DESC,p.id LIMIT ?",
                    (profile_id, *batch, max(1, min(int(maximum_rows), 5000))),
                ).fetchall()
                rows.extend(dict(row) for row in found)
        return rows

    def create_cloze_session(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        session_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO cloze_sessions(id,language_profile_id,mode,track_key,track_version,"
                "requested_item_count,seed,items_json,status,started_at,updated_at,practice_mode,"
                "question_type,selection_policy_version,source_policy_version,curriculum_snapshot_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id, values["language_profile_id"], values["mode"], values["track_key"],
                    values["track_version"], values["requested_item_count"], values["seed"],
                    canonical_json(values["items"]), "ACTIVE", now, now,
                    values.get("practice_mode", values["mode"]),
                    values.get("question_type", "MULTIPLE_CHOICE"),
                    values.get("selection_policy_version", "language.cloze-target-selection/v1"),
                    values.get("source_policy_version", "language.cloze-sentence-selection/v2"),
                    canonical_json(values["curriculum_snapshot"]) if values.get("curriculum_snapshot") else None,
                ),
            )
            row = connection.execute("SELECT * FROM cloze_sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row)

    def get_cloze_session(self, session_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            session = connection.execute("SELECT * FROM cloze_sessions WHERE id=?", (session_id,)).fetchone()
            if session is None:
                raise LanguageNotFoundError("Cloze session was not found", code="cloze_session_not_found")
            attempts = connection.execute(
                "SELECT * FROM cloze_attempts WHERE session_id=? ORDER BY item_index,id", (session_id,)
            ).fetchall()
        return {"session": dict(session), "attempts": [dict(row) for row in attempts]}

    def latest_cloze_session(self, profile_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM cloze_sessions WHERE language_profile_id=? AND status='ACTIVE' "
                "ORDER BY started_at DESC,id DESC LIMIT 1", (profile_id,),
            ).fetchone()
        return self._row(row)

    def cloze_target_evidence(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT a.*,k.knowledge_status,k.disposition,k.recognition,k.recall,k.production,"
                "k.total_exposures FROM cloze_attempts a "
                "JOIN cloze_sessions s ON s.id=a.session_id "
                "JOIN lemma_knowledge k ON k.lemma_id=a.target_lemma_id "
                "WHERE s.language_profile_id=? ORDER BY a.attempted_at,a.id", (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cloze_mistake_signature(self, profile_id: str) -> tuple[int, str | None, str | None]:
        """Cheap cache signature for the append-only Cloze attempt history."""
        with self.connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS attempt_count,MAX(a.attempted_at) AS latest_at,MAX(a.id) AS latest_id "
                "FROM cloze_attempts a JOIN cloze_sessions s ON s.id=a.session_id "
                "WHERE s.language_profile_id=?",
                (profile_id,),
            ).fetchone()
        return int(row["attempt_count"] or 0), row["latest_at"], row["latest_id"]

    def cloze_mistake_inputs(self, profile_id: str) -> dict[str, list[dict[str, Any]]]:
        """Load all canonical attempt facts and exact local form mappings in two batched queries."""
        with self.connection() as connection:
            attempts = connection.execute(
                "SELECT a.*,s.language_profile_id,l.lemma_display,l.lemma_normalized,l.part_of_speech,"
                "k.knowledge_status,k.disposition,k.recognition,k.recall,k.production,k.total_exposures "
                "FROM cloze_attempts a JOIN cloze_sessions s ON s.id=a.session_id "
                "JOIN vocabulary_lemmas l ON l.id=a.target_lemma_id "
                "JOIN lemma_knowledge k ON k.lemma_id=a.target_lemma_id "
                "WHERE s.language_profile_id=? ORDER BY a.attempted_at,a.id",
                (profile_id,),
            ).fetchall()
            forms = connection.execute(
                "SELECT sf.form_normalized AS normalized_form,sf.form_display AS display_form,"
                "fl.lemma_id,fl.morphology_json,"
                "fl.provider_id,fl.provider_version,fl.ambiguity_state,fl.lexical_status,"
                "l.lemma_display,l.lemma_normalized,l.part_of_speech "
                "FROM surface_forms sf JOIN form_lemma_links fl ON fl.form_id=sf.id "
                "JOIN vocabulary_lemmas l ON l.id=fl.lemma_id "
                "WHERE sf.language_profile_id=? AND l.merged_into_id IS NULL "
                "ORDER BY sf.form_normalized,fl.manual_locked DESC,l.lemma_normalized,l.id",
                (profile_id,),
            ).fetchall()
        return {
            "attempts": [dict(row) for row in attempts],
            "forms": [dict(row) for row in forms],
        }

    def cloze_suppressions(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM cloze_item_suppressions WHERE language_profile_id=? "
                "ORDER BY created_at,id", (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_cloze_sentence_audio(self, cache_key: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM cloze_sentence_audio WHERE cache_key=?", (cache_key,)
            ).fetchone()
        return self._row(row)

    def word_audio_source(self, *, lemma_id: str | None = None, token_id: str | None = None) -> str:
        with self.connection() as connection:
            if lemma_id:
                row = connection.execute(
                    "SELECT lemma_display AS word_text FROM vocabulary_lemmas "
                    "WHERE id=? AND merged_into_id IS NULL", (lemma_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT surface AS word_text FROM text_tokens WHERE id=? AND token_kind='WORD'",
                    (token_id,),
                ).fetchone()
        if row is None:
            raise LanguageNotFoundError("Word was not found", code="word_audio_source_not_found")
        return str(row["word_text"])

    def word_audio_candidates(self, text_id: str | None = None) -> list[str]:
        with self.connection() as connection:
            if text_id:
                rows = connection.execute(
                    "SELECT DISTINCT t.surface AS word_text FROM text_tokens t "
                    "LEFT JOIN lemma_knowledge k ON k.lemma_id=t.selected_lemma_id "
                    "WHERE t.text_document_id=? AND t.token_kind='WORD' "
                    "AND (t.selected_lemma_id IS NULL OR k.knowledge_status='NEW')",
                    (text_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT lemma_display AS word_text FROM vocabulary_lemmas WHERE merged_into_id IS NULL "
                    "UNION SELECT DISTINCT t.surface AS word_text FROM text_tokens t "
                    "LEFT JOIN lemma_knowledge k ON k.lemma_id=t.selected_lemma_id "
                    "WHERE t.token_kind='WORD' "
                    "AND (t.selected_lemma_id IS NULL OR k.knowledge_status='NEW')"
                ).fetchall()
        return [str(row["word_text"]) for row in rows]

    def word_audio_forms_for_lemma(self, lemma_id: str) -> list[str]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT surface FROM text_tokens WHERE selected_lemma_id=? AND token_kind='WORD'",
                (lemma_id,),
            ).fetchall()
        return [str(row["surface"]) for row in rows]

    def queue_word_audio_jobs(self, jobs: list[tuple[str, str, str]]) -> int:
        if not jobs:
            return 0
        now = utc_now()
        with self.connection() as connection:
            before = connection.total_changes
            connection.executemany(
                "INSERT OR IGNORE INTO word_audio_jobs"
                "(cache_key,word_text,voice_id,state,attempts,created_at,updated_at) "
                "VALUES(?,?,?,'QUEUED',0,?,?)",
                [(key, word, voice, now, now) for key, word, voice in jobs],
            )
            return connection.total_changes - before

    def get_word_audio_job(self, cache_key: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM word_audio_jobs WHERE cache_key=?", (cache_key,),
            ).fetchone()
        return self._row(row)

    def retry_word_audio_job(self, cache_key: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE word_audio_jobs SET state='QUEUED',attempts=0,error_code=NULL,updated_at=? "
                "WHERE cache_key=? AND state IN ('FAILED','READY')",
                (utc_now(), cache_key),
            )

    def prioritize_word_audio_job(self, cache_key: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE word_audio_jobs SET priority=100,updated_at=? "
                "WHERE cache_key=? AND state='QUEUED'",
                (utc_now(), cache_key),
            )

    def recover_word_audio_jobs(self, *, max_attempts: int = 3) -> int:
        with self.connection() as connection:
            connection.execute(
                "UPDATE word_audio_jobs SET state='FAILED',error_code='word_audio_attempts_exhausted',updated_at=? "
                "WHERE state='RUNNING' AND attempts>=?", (utc_now(), max_attempts),
            )
            changed = connection.execute(
                "UPDATE word_audio_jobs SET state='QUEUED',updated_at=? "
                "WHERE state='RUNNING' AND attempts<?", (utc_now(), max_attempts),
            )
            return changed.rowcount

    def claim_next_word_audio_job(self) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM word_audio_jobs WHERE state='QUEUED' "
                "ORDER BY priority DESC,created_at,cache_key LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE word_audio_jobs SET state='RUNNING',attempts=attempts+1,updated_at=? "
                "WHERE cache_key=? AND state='QUEUED'", (utc_now(), row["cache_key"]),
            )
            return dict(row)

    def finish_word_audio_job(self, cache_key: str, *, error_code: str | None = None) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE word_audio_jobs SET state=?,error_code=?,updated_at=? WHERE cache_key=?",
                ("FAILED" if error_code else "READY", error_code, utc_now(), cache_key),
            )

    def upsert_cloze_sentence_audio(self, values: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO cloze_sentence_audio(cache_key,reference_sentence_source,"
                "reference_sentence_id,sentence_text,audio_path,language_code,provider,voice_id,"
                "audio_encoding,text_hash,settings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(cache_key) DO UPDATE SET audio_path=excluded.audio_path,"
                "sentence_text=excluded.sentence_text,settings_json=excluded.settings_json,"
                "created_at=excluded.created_at",
                (
                    values["cache_key"], values["reference_sentence_source"],
                    values["reference_sentence_id"], values["sentence_text"], values["audio_path"],
                    values["language_code"], values["provider"], values["voice_id"],
                    values["audio_encoding"], values["text_hash"],
                    canonical_json(values.get("settings") or {}), values.get("created_at") or utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM cloze_sentence_audio WHERE cache_key=?", (values["cache_key"],)
            ).fetchone()
        return dict(row)

    def generated_text_sentence(self, text_id: str, sentence_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT d.id AS text_document_id,d.source_type,d.processing_state,s.id AS sentence_id,"
                "s.sentence_order,s.exact_text FROM text_documents d JOIN text_sentences s "
                "ON s.text_document_id=d.id WHERE d.id=? AND s.id=?",
                (text_id, sentence_id),
            ).fetchone()
        if row is None:
            raise LanguageNotFoundError("Generated Reader sentence was not found", code="generated_audio_sentence_not_found")
        return dict(row)

    def link_generated_text_sentence_audio(
        self, *, text_document_id: str, sentence_id: str, cache_key: str, source_type: str,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO generated_text_sentence_audio(text_document_id,sentence_id,cache_key,source_type,created_at) "
                "VALUES(?,?,?,?,?)",
                (text_document_id, sentence_id, cache_key, source_type, utc_now()),
            )
            row = connection.execute(
                "SELECT * FROM generated_text_sentence_audio WHERE text_document_id=? AND sentence_id=? AND cache_key=?",
                (text_document_id, sentence_id, cache_key),
            ).fetchone()
        return dict(row)

    def record_cloze_attempt(self, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM cloze_attempts WHERE idempotency_key=?", (values["idempotency_key"],)
            ).fetchone()
            if existing is None:
                existing = connection.execute(
                    "SELECT * FROM cloze_attempts WHERE session_id=? AND item_index=?",
                    (values["session_id"], values["item_index"]),
                ).fetchone()
            session = connection.execute(
                "SELECT * FROM cloze_sessions WHERE id=?", (values["session_id"],)
            ).fetchone()
            if session is None:
                raise LanguageNotFoundError("Cloze session was not found", code="cloze_session_not_found")
            if existing is not None:
                if (
                    str(existing["session_id"]) != str(values["session_id"])
                    or int(existing["item_index"]) != int(values["item_index"])
                    or str(existing["item_fingerprint"]) != str(values["item_fingerprint"])
                ):
                    raise LanguageConflictError(
                        "Cloze idempotency key was already used for another item",
                        code="cloze_idempotency_conflict",
                    )
                return dict(existing), dict(session), False
            if session["status"] != "ACTIVE":
                raise LanguageConflictError("Cloze session is not active", code="cloze_session_not_active")
            completed_indexes = {
                int(row[0]) for row in connection.execute(
                    "SELECT item_index FROM cloze_attempts WHERE session_id=?", (values["session_id"],)
                )
            }
            next_index = next(
                (index for index in range(len(json.loads(session["items_json"]))) if index not in completed_indexes),
                len(completed_indexes),
            )
            if int(values["item_index"]) != next_index:
                raise LanguageConflictError("Cloze item is not the next unanswered item", code="cloze_item_out_of_order")
            attempt_id = str(values.get("id") or new_id())
            attempted_at = str(values.get("attempted_at") or utc_now())
            connection.execute(
                "INSERT INTO cloze_attempts(id,session_id,item_index,target_lemma_id,"
                "reference_target_stable_key,reference_sentence_source,reference_sentence_id,"
                "item_snapshot_json,item_fingerprint,expected_surface_form,options_json,chosen_option,"
                "outcome,response_ms,idempotency_key,attempted_at,rule_versions_json,question_type,"
                "source_context_type,normalization_version,user_answer,normalized_answer) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id, values["session_id"], values["item_index"], values["target_lemma_id"],
                    values["reference_target_stable_key"], values["reference_sentence_source"],
                    values["reference_sentence_id"], canonical_json(values["item_snapshot"]),
                    values["item_fingerprint"], values["expected_surface_form"],
                    canonical_json(values["options"]), values.get("chosen_option"), values["outcome"],
                    values["response_ms"], values["idempotency_key"], attempted_at,
                    canonical_json(values["rule_versions"]), values.get("question_type", "MULTIPLE_CHOICE"),
                    values.get("source_context_type", "TATOEBA"),
                    values.get("normalization_version", "language.cloze-answer-normalization/legacy-multiple-choice-v1"),
                    values.get("user_answer"), values.get("normalized_answer"),
                ),
            )
            item_count = len(json.loads(session["items_json"]))
            attempt_count = int(connection.execute(
                "SELECT COUNT(*) FROM cloze_attempts WHERE session_id=?", (values["session_id"],)
            ).fetchone()[0])
            if attempt_count >= item_count:
                connection.execute(
                    "UPDATE cloze_sessions SET status='COMPLETED',completed_at=?,updated_at=? WHERE id=?",
                    (attempted_at, attempted_at, values["session_id"]),
                )
            else:
                connection.execute(
                    "UPDATE cloze_sessions SET updated_at=? WHERE id=?", (attempted_at, values["session_id"])
                )
            attempt = connection.execute("SELECT * FROM cloze_attempts WHERE id=?", (attempt_id,)).fetchone()
            updated = connection.execute("SELECT * FROM cloze_sessions WHERE id=?", (values["session_id"],)).fetchone()
        return dict(attempt), dict(updated), True

    def record_cloze_evidence(
        self, lemma_id: str, *, event_type: str, idempotency_key: str,
        payload: dict[str, Any], created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM knowledge_events WHERE source='CLOZE' AND idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return dict(existing), False
            event_id = self._event(
                connection, lemma_id=lemma_id, event_type=event_type, source="CLOZE",
                idempotency_key=idempotency_key, payload=payload, created_at=created_at,
            )
            row = connection.execute("SELECT * FROM knowledge_events WHERE id=?", (event_id,)).fetchone()
        return dict(row), True

    def report_cloze_item(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        suppression_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM cloze_item_suppressions WHERE language_profile_id=? "
                "AND reference_target_stable_key=? AND reference_sentence_source=? "
                "AND reference_sentence_id=?",
                (
                    values["language_profile_id"], values["reference_target_stable_key"],
                    values["reference_sentence_source"], values["reference_sentence_id"],
                ),
            ).fetchone()
            if existing:
                return dict(existing), False
            connection.execute(
                "INSERT INTO cloze_item_suppressions(id,language_profile_id,reference_target_stable_key,"
                "reference_sentence_source,reference_sentence_id,reason,created_at,source_context_type) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    suppression_id, values["language_profile_id"], values["reference_target_stable_key"],
                    values["reference_sentence_source"], values["reference_sentence_id"],
                    values["reason"], now, values.get("source_context_type", "TATOEBA"),
                ),
            )
            row = connection.execute(
                "SELECT * FROM cloze_item_suppressions WHERE id=?", (suppression_id,)
            ).fetchone()
        return dict(row), True

    def cloze_summary(self, profile_id: str, *, recent_limit: int = 10) -> dict[str, Any]:
        evidence = self.cloze_target_evidence(profile_id)
        counts = {key: 0 for key in ("CORRECT", "INCORRECT", "REVEALED", "SKIPPED")}
        latest_by_target: dict[str, dict[str, Any]] = {}
        for row in evidence:
            counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
            latest_by_target[str(row["reference_target_stable_key"])] = row
        correct = counts["CORRECT"]
        incorrect = counts["INCORRECT"]
        scored = correct + incorrect
        recent = list(reversed(evidence[-max(0, min(int(recent_limit), 50)):]))
        sources: dict[str, int] = {}
        practiced_lemmas: set[str] = set()
        for row in evidence:
            source = str(row.get("source_context_type") or "TATOEBA")
            sources[source] = sources.get(source, 0) + 1
            practiced_lemmas.add(str(row["target_lemma_id"]))
        return {
            "attempts": len(evidence),
            "correct": correct,
            "incorrect": incorrect,
            "revealed": counts["REVEALED"],
            "skipped": counts["SKIPPED"],
            "accuracy": round(correct * 100 / scored, 1) if scored else None,
            "encounteredTargets": len(latest_by_target),
            "mistakeTargets": sum(1 for row in latest_by_target.values() if row["outcome"] == "INCORRECT"),
            "sources": sources,
            "targetsPracticed": len(practiced_lemmas),
            "lastAttemptedAt": evidence[-1]["attempted_at"] if evidence else None,
            "recent": [self.api_row(row) for row in recent],
        }

    def gamification_facts(self, profile_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return canonical evidence needed by the derived gamification overlay."""
        with self.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)
            ).fetchone():
                raise LanguageNotFoundError(
                    "Language profile was not found", code="language_profile_not_found"
                )
            sessions = connection.execute(
                "SELECT id,text_document_id,session_type,status,active_seconds,started_at,ended_at "
                "FROM study_sessions WHERE language_profile_id=? ORDER BY started_at,id",
                (profile_id,),
            ).fetchall()
            exposures = connection.execute(
                "SELECT id,lemma_id,text_document_id,study_session_id,source_type,occurrence_count,"
                "occurred_at FROM exposure_events WHERE language_profile_id=? ORDER BY occurred_at,id",
                (profile_id,),
            ).fetchall()
            progress = connection.execute(
                "SELECT p.text_document_id,p.status,p.last_read_at,p.completed_at,d.source_type,d.title "
                "FROM text_reading_progress p JOIN text_documents d ON d.id=p.text_document_id "
                "WHERE p.language_profile_id=? ORDER BY COALESCE(p.completed_at,p.last_read_at),p.text_document_id",
                (profile_id,),
            ).fetchall()
            attempts = connection.execute(
                "SELECT a.*,s.language_profile_id,s.track_key,s.track_version "
                "FROM cloze_attempts a JOIN cloze_sessions s ON s.id=a.session_id "
                "WHERE s.language_profile_id=? ORDER BY a.attempted_at,a.id",
                (profile_id,),
            ).fetchall()
            completed_sessions = connection.execute(
                "SELECT id,track_key,track_version,requested_item_count,started_at,completed_at "
                "FROM cloze_sessions WHERE language_profile_id=? AND status='COMPLETED' "
                "ORDER BY completed_at,id",
                (profile_id,),
            ).fetchall()
            lemmas = connection.execute(
                "SELECT l.id,l.created_at,k.knowledge_status,k.disposition FROM vocabulary_lemmas l "
                "JOIN lemma_knowledge k ON k.lemma_id=l.id WHERE l.language_profile_id=? "
                "AND l.merged_into_id IS NULL ORDER BY l.created_at,l.id",
                (profile_id,),
            ).fetchall()
            anki_links = connection.execute(
                "SELECT id,lemma_id,created_at FROM anki_note_links WHERE language_profile_id=? "
                "ORDER BY created_at,id", (profile_id,),
            ).fetchall()
            topics = connection.execute(
                "SELECT t.id,t.display_name,t.archived,tl.lemma_id,k.knowledge_status,k.disposition "
                "FROM topics t LEFT JOIN topic_lemmas tl ON tl.topic_id=t.id "
                "LEFT JOIN lemma_knowledge k ON k.lemma_id=tl.lemma_id "
                "WHERE t.language_profile_id=? ORDER BY t.display_name,t.id,tl.lemma_id",
                (profile_id,),
            ).fetchall()
            listening_events = connection.execute(
                "SELECT id,study_session_id,text_document_id,sentence_id,playback_source,active_ms,coverage_ms,qualified,"
                "exposure_awarded,local_study_date,occurred_at FROM listening_sentence_events "
                "WHERE language_profile_id=? ORDER BY occurred_at,id", (profile_id,),
            ).fetchall()
            listening_progress = connection.execute(
                "SELECT lp.*,d.source_type,d.title FROM listening_progress lp "
                "JOIN text_documents d ON d.id=lp.text_document_id "
                "WHERE lp.language_profile_id=? ORDER BY lp.last_listened_at,lp.text_document_id",
                (profile_id,),
            ).fetchall()
        return {
            "sessions": [dict(row) for row in sessions],
            "exposures": [dict(row) for row in exposures],
            "progress": [dict(row) for row in progress],
            "attempts": [dict(row) for row in attempts],
            "completedClozeSessions": [dict(row) for row in completed_sessions],
            "lemmas": [dict(row) for row in lemmas],
            "ankiLinks": [dict(row) for row in anki_links],
            "topics": [dict(row) for row in topics],
            "listeningEvents": [dict(row) for row in listening_events],
            "listeningProgress": [dict(row) for row in listening_progress],
        }

    def gamification_activity_window(self, profile_id: str, start: str, end: str) -> dict[str, Any]:
        """Bounded canonical activity for one quest/streak window."""
        with self.connection() as connection:
            sessions = connection.execute(
                "SELECT id,text_document_id,active_seconds,started_at FROM study_sessions "
                "WHERE language_profile_id=? AND session_type='READER' AND started_at>=? AND started_at<? "
                "ORDER BY started_at,id", (profile_id, start, end),
            ).fetchall()
            exposures = connection.execute(
                "SELECT id,occurrence_count,occurred_at FROM exposure_events "
                "WHERE language_profile_id=? AND source_type='READER' AND occurred_at>=? AND occurred_at<? "
                "ORDER BY occurred_at,id", (profile_id, start, end),
            ).fetchall()
            completed = connection.execute(
                "SELECT text_document_id,completed_at FROM text_reading_progress "
                "WHERE language_profile_id=? AND completed_at>=? AND completed_at<? "
                "ORDER BY completed_at,text_document_id", (profile_id, start, end),
            ).fetchall()
            attempts = connection.execute(
                "SELECT a.id,a.outcome,a.attempted_at FROM cloze_attempts a "
                "JOIN cloze_sessions s ON s.id=a.session_id WHERE s.language_profile_id=? "
                "AND a.attempted_at>=? AND a.attempted_at<? ORDER BY a.attempted_at,a.id",
                (profile_id, start, end),
            ).fetchall()
        return {
            "readerActiveSeconds": sum(int(row["active_seconds"] or 0) for row in sessions),
            "readerExposureEvents": len(exposures),
            "readerExposureOccurrences": sum(int(row["occurrence_count"] or 0) for row in exposures),
            "readerTextsCompleted": len(completed),
            "clozeAttempts": len(attempts),
            "clozeCorrect": sum(1 for row in attempts if row["outcome"] == "CORRECT"),
        }

    def record_gamification_award(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        award_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO gamification_awards(id,language_profile_id,source_type,"
                "source_id,reward_key,rule_version,xp_amount,awarded_at,metadata_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    award_id, values["language_profile_id"], values["source_type"],
                    values["source_id"], values["reward_key"], values["rule_version"],
                    int(values["xp_amount"]), values.get("awarded_at") or utc_now(),
                    canonical_json(values.get("metadata") or {}),
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT * FROM gamification_awards WHERE language_profile_id=? AND source_type=? "
                "AND source_id=? AND reward_key=? AND rule_version=?",
                (
                    values["language_profile_id"], values["source_type"], values["source_id"],
                    values["reward_key"], values["rule_version"],
                ),
            ).fetchone()
        return dict(row), created

    def gamification_ledger(self, profile_id: str, *, recent_limit: int = 12) -> dict[str, Any]:
        with self.connection() as connection:
            total = int(connection.execute(
                "SELECT COALESCE(SUM(xp_amount),0) FROM gamification_awards WHERE language_profile_id=?",
                (profile_id,),
            ).fetchone()[0])
            rows = connection.execute(
                "SELECT * FROM gamification_awards WHERE language_profile_id=? "
                "ORDER BY awarded_at DESC,id DESC LIMIT ?",
                (profile_id, max(0, min(int(recent_limit), 50))),
            ).fetchall()
        return {"lifetimeXp": total, "recent": [self.api_row(dict(row)) for row in rows]}

    def unlock_achievement(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        unlock_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO achievement_unlocks(id,language_profile_id,achievement_key,"
                "definition_version,unlocked_at,snapshot_json) VALUES(?,?,?,?,?,?)",
                (
                    unlock_id, values["language_profile_id"], values["achievement_key"],
                    values["definition_version"], values["unlocked_at"],
                    canonical_json(values.get("snapshot") or {}),
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT * FROM achievement_unlocks WHERE language_profile_id=? "
                "AND achievement_key=? AND definition_version=?",
                (values["language_profile_id"], values["achievement_key"], values["definition_version"]),
            ).fetchone()
        return dict(row), created

    def achievement_unlocks(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM achievement_unlocks WHERE language_profile_id=? "
                "ORDER BY unlocked_at,id", (profile_id,),
            ).fetchall()
        return [self.api_row(dict(row)) for row in rows]

    def get_quest_snapshot(self, profile_id: str, local_date: str, rule_version: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM gamification_quest_snapshots WHERE language_profile_id=? "
                "AND local_study_date=? AND rule_version=?",
                (profile_id, local_date, rule_version),
            ).fetchone()
        return self.api_row(dict(row)) if row else None

    def create_quest_snapshot(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        snapshot_id = str(values.get("id") or new_id())
        with self.connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO gamification_quest_snapshots(id,language_profile_id,"
                "local_study_date,timezone,rule_version,canonical_fingerprint,quests_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    snapshot_id, values["language_profile_id"], values["local_study_date"],
                    values["timezone"], values["rule_version"], values["canonical_fingerprint"],
                    canonical_json(values["quests"]), values.get("created_at") or utc_now(),
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT * FROM gamification_quest_snapshots WHERE language_profile_id=? "
                "AND local_study_date=? AND rule_version=?",
                (values["language_profile_id"], values["local_study_date"], values["rule_version"]),
            ).fetchone()
        return self.api_row(dict(row)), created

    def list_quest_snapshots(self, profile_id: str, *, limit: int = 40) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM gamification_quest_snapshots WHERE language_profile_id=? "
                "ORDER BY local_study_date DESC,id DESC LIMIT ?",
                (profile_id, max(0, min(int(limit), 400))),
            ).fetchall()
        return [self.api_row(dict(row)) for row in rows]

    def create_campaign(self, values: dict[str, Any]) -> dict[str, Any]:
        campaign_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO campaign_definitions(id,language_profile_id,name,description,target_date,"
                "enabled,milestones_json,rule_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    campaign_id, values["language_profile_id"], values["name"], values.get("description"),
                    values["target_date"], 1 if values.get("enabled", True) else 0,
                    canonical_json(values["milestones"]), values["rule_version"], now, now,
                ),
            )
            row = connection.execute("SELECT * FROM campaign_definitions WHERE id=?", (campaign_id,)).fetchone()
        return self.api_row(dict(row))

    def update_campaign(self, campaign_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "description", "target_date", "enabled", "milestones_json", "rule_version"}
        assignments = [(key, value) for key, value in changes.items() if key in allowed]
        with self.connection() as connection:
            if not connection.execute("SELECT 1 FROM campaign_definitions WHERE id=?", (campaign_id,)).fetchone():
                raise LanguageNotFoundError("Campaign was not found", code="campaign_not_found")
            if assignments:
                connection.execute(
                    f"UPDATE campaign_definitions SET {','.join(f'{key}=?' for key, _ in assignments)},updated_at=? WHERE id=?",
                    (*[value for _, value in assignments], utc_now(), campaign_id),
                )
            row = connection.execute("SELECT * FROM campaign_definitions WHERE id=?", (campaign_id,)).fetchone()
        return self.api_row(dict(row))

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM campaign_definitions WHERE id=?", (campaign_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Campaign was not found", code="campaign_not_found")
        return self.api_row(dict(row))

    def list_campaigns(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM campaign_definitions WHERE language_profile_id=? "
                "ORDER BY enabled DESC,target_date,id", (profile_id,),
            ).fetchall()
        return [self.api_row(dict(row)) for row in rows]

    def lemma_user_translations(self, lemma_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM user_lemma_translations WHERE lemma_id=? "
                "ORDER BY target_locale,id", (lemma_id,),
            ).fetchall()
        return [self.api_row(dict(row)) for row in rows]

    def upsert_lemma_user_translation(
        self, lemma_id: str, profile_id: str, target_locale: str, translation_text: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO user_lemma_translations(id,language_profile_id,lemma_id,target_locale,"
                "translation_text,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(lemma_id,target_locale) DO UPDATE SET "
                "translation_text=excluded.translation_text,updated_at=excluded.updated_at",
                (new_id(), profile_id, lemma_id, target_locale, translation_text, now, now),
            )
            row = connection.execute(
                "SELECT * FROM user_lemma_translations WHERE lemma_id=? AND target_locale=?",
                (lemma_id, target_locale),
            ).fetchone()
        return self.api_row(dict(row))

    def delete_lemma_user_translation(self, lemma_id: str, target_locale: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM user_lemma_translations WHERE lemma_id=? AND target_locale=?",
                (lemma_id, target_locale),
            )
        return cursor.rowcount == 1

    def create_phrasebook_entry(
        self, values: dict[str, Any], links: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        entry_id = str(values.get("id") or new_id())
        now = utc_now()
        with self.connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO phrasebook_entries(id,language_profile_id,expression_text,"
                "expression_normalized,source_type,source_entity_id,source_context,source_provenance_json,"
                "source_fingerprint,note,user_translation,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    entry_id, values["language_profile_id"], values["expression_text"],
                    values["expression_normalized"], values["source_type"], values.get("source_entity_id"),
                    values.get("source_context"), canonical_json(values.get("source_provenance") or {}),
                    values["source_fingerprint"], values.get("note"), values.get("user_translation"),
                    now, now,
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT * FROM phrasebook_entries WHERE language_profile_id=? AND "
                "expression_normalized=? AND source_type=? AND source_fingerprint=?",
                (values["language_profile_id"], values["expression_normalized"],
                 values["source_type"], values["source_fingerprint"]),
            ).fetchone()
            if created:
                for link in links:
                    connection.execute(
                        "INSERT OR IGNORE INTO phrasebook_entry_links(entry_id,link_type,link_value,"
                        "metadata_json,created_at) VALUES(?,?,?,?,?)",
                        (row["id"], link["link_type"], link["link_value"],
                         canonical_json(link.get("metadata") or {}), now),
                    )
        return self.get_phrasebook_entry(str(row["id"])), created

    def get_phrasebook_entry(self, entry_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM phrasebook_entries WHERE id=?", (entry_id,),
            ).fetchone()
            if row is None:
                raise LanguageNotFoundError("Phrasebook entry was not found", code="phrasebook_entry_not_found")
            links = connection.execute(
                "SELECT * FROM phrasebook_entry_links WHERE entry_id=? "
                "ORDER BY link_type,link_value", (entry_id,),
            ).fetchall()
        entry = self.api_row(dict(row))
        entry["links"] = [self.api_row(dict(item)) for item in links]
        return entry

    def list_phrasebook_entries(
        self, profile_id: str, *, query: str = "", source_type: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        conditions = ["language_profile_id=?"]
        parameters: list[Any] = [profile_id]
        if query:
            conditions.append("(instr(expression_normalized,?)>0 OR instr(lower(COALESCE(note,'')),?)>0 "
                              "OR instr(lower(COALESCE(user_translation,'')),?)>0)")
            parameters.extend((query, query, query))
        if source_type:
            conditions.append("source_type=?")
            parameters.append(source_type)
        where = " AND ".join(conditions)
        with self.connection() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM phrasebook_entries WHERE {where}", parameters,
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM phrasebook_entries WHERE {where} "
                "ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
            links_by_entry: dict[str, list[dict[str, Any]]] = {}
            if rows:
                placeholders = ",".join("?" for _ in rows)
                link_rows = connection.execute(
                    "SELECT * FROM phrasebook_entry_links WHERE entry_id IN "
                    f"({placeholders}) ORDER BY entry_id,link_type,link_value",
                    tuple(str(row["id"]) for row in rows),
                ).fetchall()
                for link in link_rows:
                    links_by_entry.setdefault(str(link["entry_id"]), []).append(self.api_row(dict(link)))
        items = []
        for row in rows:
            item = self.api_row(dict(row))
            item["links"] = links_by_entry.get(str(row["id"]), [])
            items.append(item)
        return {"items": items, "total": total}

    def update_phrasebook_entry(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        assignments = [(key, value) for key, value in changes.items() if key in {"note", "user_translation"}]
        with self.connection() as connection:
            if connection.execute("SELECT 1 FROM phrasebook_entries WHERE id=?", (entry_id,)).fetchone() is None:
                raise LanguageNotFoundError("Phrasebook entry was not found", code="phrasebook_entry_not_found")
            if assignments:
                connection.execute(
                    f"UPDATE phrasebook_entries SET {','.join(f'{key}=?' for key, _ in assignments)},"
                    "updated_at=? WHERE id=?",
                    (*[value for _, value in assignments], utc_now(), entry_id),
                )
        return self.get_phrasebook_entry(entry_id)

    def delete_phrasebook_entry(self, entry_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM phrasebook_entries WHERE id=?", (entry_id,))
        if cursor.rowcount != 1:
            raise LanguageNotFoundError("Phrasebook entry was not found", code="phrasebook_entry_not_found")
        return True

    @staticmethod
    def _api_key(name: str) -> str:
        parts = name.split("_")
        return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])

    @classmethod
    def api_row(cls, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result: dict[str, Any] = {}
        for key, value in row.items():
            output_key = key[:-5] if key.endswith("_json") else key
            if key.endswith("_json") or key == "mapping_evidence_reference":
                try:
                    value = json.loads(value or "null")
                except (TypeError, json.JSONDecodeError):
                    value = None
            elif key.startswith("manual_") or key in {
                "manual_locked", "cancel_requested", "archived", "enabled",
                "qualified", "exposure_awarded", "is_current", "exposure_eligible",
            }:
                if isinstance(value, int):
                    value = bool(value)
            result[cls._api_key(output_key)] = value
        return result

    @classmethod
    def api_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: cls.api_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls.api_value(item) for item in value]
        return value

    def export_data(self) -> dict[str, Any]:
        order_by = {
            "lemma_knowledge": "lemma_id",
            "lemma_frequency": "lemma_id,metric,provider_id",
            "text_reading_progress": "text_document_id",
            "topic_lemmas": "topic_id,lemma_id",
            "anki_card_snapshots": "external_card_id",
            "anki_daily_plans": "language_profile_id,local_day,deck_name",
            "cloze_sentence_audio": "cache_key",
            "user_lemma_translations": "lemma_id,target_locale",
            "phrasebook_entry_links": "entry_id,link_type,link_value",
            "generated_text_sentence_audio": "text_document_id,sentence_id,cache_key",
            "reader_sentence_translations": "text_document_id,sentence_id,target_language",
            "reader_sentence_grammar_notes": "text_document_id,sentence_id",
            "reading_series_episodes": "series_id,episode_number",
            "listening_sessions": "study_session_id",
            "listening_sentence_events": "occurred_at,id",
            "listening_progress": "language_profile_id,text_document_id",
            "content_items": "added_at,id",
            "content_artifacts": "content_id,id",
            "transcripts": "content_id,version",
            "transcript_cues": "transcript_id,cue_order",
            "sentence_alignments": "content_id,transcript_id,sentence_id,version",
            "benchmark_runs": "started_at,id",
            "benchmark_responses": "run_id,item_id",
        }
        with self.connection() as connection:
            data: dict[str, Any] = {}
            for table in self.EXPORT_TABLES:
                rows = connection.execute(
                    f"SELECT * FROM {table} ORDER BY {order_by.get(table, 'id')}"
                ).fetchall()
                data[self._api_key(table)] = [self.api_row(dict(row)) for row in rows]
        return {
            "exportVersion": EXPORT_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": utc_now(),
            "offsetUnit": OFFSET_UNIT,
            "data": data,
        }

    def backup_database(self) -> dict[str, Any]:
        self._ensure_initialized()
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"language-learning-v{SCHEMA_VERSION}-{stamp}.sqlite"
        destination = self.backup_directory / filename
        try:
            with self._connect() as source, sqlite3.connect(destination, factory=ClosingConnection) as target:
                source.backup(target)
                valid = target.execute("PRAGMA integrity_check").fetchone()[0]
                if valid != "ok":
                    raise sqlite3.DatabaseError("backup integrity check failed")
        except sqlite3.Error as exc:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise LanguageStorageError("Language database backup failed") from exc
        return {
            "fileName": filename,
            "schemaVersion": SCHEMA_VERSION,
            "createdAt": utc_now(),
        }


__all__ = [
    "EXPORT_VERSION",
    "LanguageStore",
    "MIGRATIONS",
    "OFFSET_UNIT",
    "SCHEMA_VERSION",
]
