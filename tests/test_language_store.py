import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from language_learning.errors import LanguageStorageError
from language_learning.migrations import (
    MIGRATIONS,
    SCHEMA_VERSION,
    MIGRATION_1_SQL,
    MIGRATION_2_SQL,
    MIGRATION_3_SQL,
    MIGRATION_4_SQL,
    MIGRATION_5_SQL,
    MIGRATION_6_SQL,
    MIGRATION_7_SQL,
    Migration,
    apply_migrations,
)
from language_learning.service import LanguageService
from language_learning.store import LanguageStore, OFFSET_UNIT
from language_learning.schemas import text_fingerprint


class LanguageStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "language.sqlite"
        self.store = LanguageStore(self.path, backup_directory=Path(self.temp.name) / "backups")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile_id = self.service.ensure_bokmal_profile()["profile"]["id"]

    def tearDown(self):
        self.temp.cleanup()

    def lemma(self, name="jobb", pos="NOUN"):
        return self.service.upsert_lemma(self.profile_id, name, part_of_speech=pos)["lemma"]

    def test_fresh_and_repeated_initialization_have_deterministic_ledger(self):
        with sqlite3.connect(self.path) as connection:
            first = connection.execute(
                "SELECT version,checksum FROM language_schema_migrations ORDER BY version"
            ).fetchall()
        self.store.initialize()
        with sqlite3.connect(self.path) as connection:
            second = connection.execute(
                "SELECT version,checksum FROM language_schema_migrations ORDER BY version"
            ).fetchall()
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
        self.assertEqual(first, [(item.version, item.checksum) for item in MIGRATIONS])
        self.assertEqual(first, second)
        self.assertEqual(len(tables), 55)

    def test_version_zero_ledger_fixture_migrates_without_recreation(self):
        other = Path(self.temp.name) / "v0.sqlite"
        with sqlite3.connect(other) as connection:
            connection.execute(
                "CREATE TABLE language_schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
            )
            connection.execute("CREATE TABLE fixture_marker(value TEXT)")
            connection.execute("INSERT INTO fixture_marker VALUES('preserve-me')")
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            self.assertEqual(connection.execute("SELECT value FROM fixture_marker").fetchone()[0], "preserve-me")
            self.assertEqual(connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0], SCHEMA_VERSION)

    def test_schema_v1_data_migrates_additively_to_current_version(self):
        other = Path(self.temp.name) / "v1.sqlite"
        connection = sqlite3.connect(other)
        try:
            connection.executescript(MIGRATION_1_SQL)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO language_schema_migrations VALUES(1,'2026-09-15T00:00:00Z',?)",
                (MIGRATIONS[0].checksum,),
            )
            connection.execute(
                "INSERT INTO language_profiles("
                "id,language_code,locale,display_name,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("a" * 32, "nb", "nb-NO", "Bokmal", "then", "then"),
            )
            connection.execute(
                "INSERT INTO text_documents("
                "id,language_profile_id,title,raw_text,source_type,content_fingerprint,"
                "processing_state,offset_unit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    "b" * 32,
                    "a" * 32,
                    "Preserved",
                    "jobb",
                    "PASTED",
                    text_fingerprint("jobb"),
                    "DRAFT",
                    "UNICODE_CODE_POINT",
                    "then",
                    "then",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        migrated = LanguageStore(other)
        migrated.initialize()
        with migrated.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT raw_text FROM text_documents").fetchone()[0],
                "jobb",
            )
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM language_schema_migrations ORDER BY version"
                )
            ]
            self.assertEqual(versions, list(range(1, SCHEMA_VERSION + 1)))
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertIn("language_jobs", tables)
            self.assertIn("lemma_frequency", tables)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v2_sessions_migrate_additively_to_v3(self):
        other = Path(self.temp.name) / "v2.sqlite"
        with sqlite3.connect(other) as connection:
            connection.executescript(MIGRATION_1_SQL)
            connection.executescript(MIGRATION_2_SQL)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-15T00:00:00Z',?)",
                [(1, MIGRATIONS[0].checksum), (2, MIGRATIONS[1].checksum)],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                ("a" * 32, "nb", "nb-NO", "Bokmal", "then", "then"),
            )
            connection.execute(
                "INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,"
                "content_fingerprint,processing_state,offset_unit,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    "b" * 32, "a" * 32, "Reader", "jobb", "PASTED",
                    text_fingerprint("jobb"), "DRAFT", "UNICODE_CODE_POINT", "then", "then",
                ),
            )
            connection.execute(
                "INSERT INTO study_sessions(id,language_profile_id,text_document_id,session_type,status,"
                "client_session_id,started_at,active_seconds,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("c" * 32, "a" * 32, "b" * 32, "READER", "ACTIVE", "old", "then", 12, "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            session = connection.execute(
                "SELECT active_seconds,activity_state FROM study_sessions"
            ).fetchone()
            versions = connection.execute(
                "SELECT version FROM language_schema_migrations ORDER BY version"
            ).fetchall()
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertEqual(session, (12, "PAUSED"))
            self.assertEqual(versions, [(version,) for version in range(1, SCHEMA_VERSION + 1)])
            self.assertIn("text_reading_progress", tables)
            self.assertIn("topics", tables)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v3_data_migrates_additively_to_v4(self):
        other = Path(self.temp.name) / "v3.sqlite"
        with sqlite3.connect(other) as connection:
            connection.executescript(MIGRATION_1_SQL)
            connection.executescript(MIGRATION_2_SQL)
            connection.executescript(MIGRATION_3_SQL)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-16T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:3]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                ("a" * 32, "nb", "nb-NO", "Bokmal", "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertEqual(
                connection.execute("SELECT language_code FROM language_profiles").fetchone()[0],
                "nb",
            )
            self.assertEqual(
                connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertTrue({"topics", "topic_lemmas", "goal_definitions"}.issubset(tables))
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v4_data_migrates_additively_to_v5(self):
        other = Path(self.temp.name) / "v4.sqlite"
        with sqlite3.connect(other) as connection:
            for migration_sql in (MIGRATION_1_SQL, MIGRATION_2_SQL, MIGRATION_3_SQL, MIGRATION_4_SQL):
                connection.executescript(migration_sql)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-16T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:4]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)", ("a" * 32, "nb", "nb-NO", "Bokmal", "then", "then")
            )
            connection.execute(
                "INSERT INTO topics(id,language_profile_id,slug,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)", ("b" * 32, "a" * 32, "work", "Work", "then", "then")
            )
            connection.execute(
                "INSERT INTO goal_definitions(id,language_profile_id,metric,period,target_value,unit,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                ("c" * 32, "a" * 32, "NEW_WORDS", "WEEK", 5, "WORDS", "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            self.assertEqual(connection.execute("SELECT display_name FROM topics").fetchone()[0], "Work")
            self.assertEqual(connection.execute("SELECT target_value FROM goal_definitions").fetchone()[0], 5)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"anki_note_links", "anki_card_snapshots", "anki_sync_runs"}.issubset(tables))
            self.assertEqual(connection.execute("SELECT anki_config_json FROM language_profiles").fetchone()[0], "{}")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v5_data_migrates_additively_to_v6(self):
        other = Path(self.temp.name) / "v5.sqlite"
        with sqlite3.connect(other) as connection:
            for migration_sql in (MIGRATION_1_SQL, MIGRATION_2_SQL, MIGRATION_3_SQL, MIGRATION_4_SQL, MIGRATION_5_SQL):
                connection.executescript(migration_sql)
            connection.execute("CREATE TABLE language_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)")
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-16T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:5]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("a" * 32, "nb", "nb-NO", "Bokmal", "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"generation_requests", "generation_candidates"}.issubset(tables))
            self.assertEqual(connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("SELECT display_name FROM language_profiles").fetchone()[0], "Bokmal")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v6_data_migrates_additively_to_current(self):
        other = Path(self.temp.name) / "v6.sqlite"
        with sqlite3.connect(other) as connection:
            for migration_sql in (
                MIGRATION_1_SQL, MIGRATION_2_SQL, MIGRATION_3_SQL,
                MIGRATION_4_SQL, MIGRATION_5_SQL, MIGRATION_6_SQL,
            ):
                connection.executescript(migration_sql)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-16T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:6]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                ("a" * 32, "nb", "nb-NO", "Bokmal", "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertTrue(
                {"cloze_sessions", "cloze_attempts", "cloze_item_suppressions"}.issubset(tables)
            )
            self.assertEqual(
                connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertEqual(
                connection.execute("SELECT display_name FROM language_profiles").fetchone()[0],
                "Bokmal",
            )
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v7_cloze_data_migrates_additively_to_v8_audio_metadata(self):
        other = Path(self.temp.name) / "v7.sqlite"
        with sqlite3.connect(other) as connection:
            for migration_sql in (
                MIGRATION_1_SQL, MIGRATION_2_SQL, MIGRATION_3_SQL, MIGRATION_4_SQL,
                MIGRATION_5_SQL, MIGRATION_6_SQL, MIGRATION_7_SQL,
            ):
                connection.executescript(migration_sql)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-16T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:7]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                ("a" * 32, "nb", "nb-NO", "Bokmal", "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertIn("cloze_sentence_audio", tables)
            self.assertEqual(
                connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0], SCHEMA_VERSION,
            )
            self.assertEqual(connection.execute("SELECT display_name FROM language_profiles").fetchone()[0], "Bokmal")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v8_data_migrates_additively_to_v9_gamification(self):
        other = Path(self.temp.name) / "v8.sqlite"
        with sqlite3.connect(other) as connection:
            for migration in MIGRATIONS[:8]:
                connection.executescript(migration.sql)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-16T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:8]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                ("a" * 32, "nb", "nb-NO", "Preserved", "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            self.assertEqual(
                connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0], SCHEMA_VERSION,
            )
            self.assertEqual(
                connection.execute("SELECT display_name FROM language_profiles").fetchone()[0], "Preserved",
            )
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            self.assertTrue({
                "gamification_awards", "achievement_unlocks",
                "gamification_quest_snapshots", "campaign_definitions",
            }.issubset(tables))
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v9_data_migrates_additively_to_v10_user_lexical_tables(self):
        other = Path(self.temp.name) / "v9.sqlite"
        with sqlite3.connect(other) as connection:
            for migration in MIGRATIONS[:9]:
                connection.executescript(migration.sql)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-17T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:9]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)", ("a" * 32, "nb", "nb-NO", "Preserved v9", "then", "then")
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({
                "user_lemma_translations", "phrasebook_entries", "phrasebook_entry_links",
            }.issubset(tables))
            self.assertEqual(connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("SELECT display_name FROM language_profiles").fetchone()[0], "Preserved v9")
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v10_generation_data_migrates_additively_to_v11(self):
        other = Path(self.temp.name) / "v10.sqlite"
        with sqlite3.connect(other) as connection:
            for migration in MIGRATIONS[:10]:
                connection.executescript(migration.sql)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-17T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:10]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)", ("a" * 32, "nb", "nb-NO", "Preserved v10", "then", "then")
            )
            connection.execute(
                "INSERT INTO generation_requests("
                "id,language_profile_id,custom_topic,requested_length,requested_token_coverage,"
                "difficulty_preset,explicit_target_lemma_ids_json,selection_rule_version,"
                "coverage_policy_version,knowledge_snapshot_fingerprint,knowledge_snapshot_json,"
                "target_snapshot_json,prompt_version,prompt_fingerprint,context_pack_json,status,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("b" * 32, "a" * 32, "Preserve this", 200, 95, "BALANCED", "[]", "targets/v1",
                 "coverage/v1", "sha256:snapshot", "[]", '{"items":[]}', "prompt/v1",
                 "sha256:prompt", "{}", "READY", "then", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM generation_requests WHERE id=?", ("b" * 32,)).fetchone()
            self.assertEqual(row["custom_topic"], "Preserve this")
            self.assertEqual(row["generation_mode"], "MANUAL")
            self.assertEqual(row["automatic_status"], "NOT_REQUESTED")
            self.assertEqual(row["automatic_usage_json"], "{}")
            tables = {item[0] for item in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("generated_text_sentence_audio", tables)
            self.assertEqual(connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_schema_v11_cloze_history_migrates_additively_to_v12(self):
        other = Path(self.temp.name) / "v11.sqlite"
        with sqlite3.connect(other) as connection:
            for migration in MIGRATIONS[:11]:
                connection.executescript(migration.sql)
            connection.execute(
                "CREATE TABLE language_schema_migrations("
                "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO language_schema_migrations VALUES(?,'2026-09-17T00:00:00Z',?)",
                [(item.version, item.checksum) for item in MIGRATIONS[:11]],
            )
            connection.execute(
                "INSERT INTO language_profiles(id,language_code,locale,display_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)", ("a" * 32, "nb", "nb-NO", "Preserved v11", "then", "then")
            )
            connection.execute(
                "INSERT INTO vocabulary_lemmas(id,language_profile_id,lemma_display,lemma_normalized,"
                "part_of_speech,canonical_key,source_kind,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                ("b" * 32, "a" * 32, "jobb", "jobb", "NOUN", "jobb|NOUN", "MANUAL", "then", "then"),
            )
            connection.execute(
                "INSERT INTO lemma_knowledge(lemma_id,updated_at) VALUES(?,?)",
                ("b" * 32, "then"),
            )
            snapshot = '{"fingerprint":"sha256:old","targetLemmaId":"' + "b" * 32 + '","ruleVersions":{}}'
            connection.execute(
                "INSERT INTO cloze_sessions(id,language_profile_id,mode,track_key,track_version,"
                "requested_item_count,seed,items_json,status,started_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("c" * 32, "a" * 32, "FAST_TRACK", "FAST_TRACK_1", "v1", 10, "seed", f"[{snapshot}]", "ACTIVE", "then", "then"),
            )
            connection.execute(
                "INSERT INTO cloze_attempts(id,session_id,item_index,target_lemma_id,reference_target_stable_key,"
                "reference_sentence_source,reference_sentence_id,item_snapshot_json,item_fingerprint,"
                "expected_surface_form,options_json,chosen_option,outcome,response_ms,idempotency_key,attempted_at,rule_versions_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("d" * 32, "c" * 32, 0, "b" * 32, "reference-key", "fixture", "1", snapshot,
                 "sha256:old", "jobb", '["jobb"]', "jobb", "CORRECT", 10, "old-attempt", "then", "{}"),
            )
            connection.execute(
                "INSERT INTO cloze_item_suppressions(id,language_profile_id,reference_target_stable_key,"
                "reference_sentence_source,reference_sentence_id,reason,created_at) VALUES(?,?,?,?,?,?,?)",
                ("e" * 32, "a" * 32, "reference-key", "fixture", "1", "OTHER", "then"),
            )
        LanguageStore(other).initialize()
        with sqlite3.connect(other) as connection:
            connection.row_factory = sqlite3.Row
            session = connection.execute("SELECT * FROM cloze_sessions").fetchone()
            attempt = connection.execute("SELECT * FROM cloze_attempts").fetchone()
            suppression = connection.execute("SELECT * FROM cloze_item_suppressions").fetchone()
            self.assertEqual(session["items_json"], f"[{snapshot}]")
            self.assertEqual((session["practice_mode"], session["question_type"]), ("FAST_TRACK", "MULTIPLE_CHOICE"))
            self.assertEqual(attempt["question_type"], "MULTIPLE_CHOICE")
            self.assertEqual(attempt["normalization_version"], "language.cloze-answer-normalization/legacy-multiple-choice-v1")
            self.assertEqual(suppression["source_context_type"], "TATOEBA")
            self.assertEqual(connection.execute("SELECT MAX(version) FROM language_schema_migrations").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_checksum_mismatch_fails_cleanly(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE language_schema_migrations SET checksum='sha256:wrong' WHERE version=1")
        with self.assertRaises(LanguageStorageError):
            LanguageStore(self.path).initialize()

    def test_failed_migration_rolls_back_ddl_and_ledger_row(self):
        other = Path(self.temp.name) / "broken.sqlite"
        broken = Migration(1, "CREATE TABLE should_rollback(id INTEGER); THIS IS NOT SQL;")
        with sqlite3.connect(other) as connection, mock.patch("language_learning.migrations.MIGRATIONS", (broken,)):
            with self.assertRaises(LanguageStorageError):
                apply_migrations(connection, applied_at="2026-09-15T00:00:00Z")
        with sqlite3.connect(other) as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            count = connection.execute("SELECT COUNT(*) FROM language_schema_migrations").fetchone()[0]
        self.assertNotIn("should_rollback", names)
        self.assertEqual(count, 0)

    def test_connections_enable_foreign_keys_wal_timeout_and_expected_indexes(self):
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 15000)
            indexes = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )}
        self.assertTrue({
            "idx_language_lemmas_lookup",
            "idx_language_forms_lookup",
            "idx_language_knowledge_state",
            "idx_language_tokens_text",
            "idx_language_exposures_lemma",
        }.issubset(indexes))
        self.assertTrue(self.path.is_file())

    def test_profile_isolation_duplicate_identity_and_many_to_many_candidates(self):
        other = self.service.create_profile({
            "languageCode": "sv", "locale": "sv-SE", "displayName": "Swedish"
        })["data"]["profile"]["id"]
        first = self.lemma()
        duplicate = self.lemma()
        second = self.service.upsert_lemma(self.profile_id, "jobbe", part_of_speech="VERB")["lemma"]
        form = self.service.upsert_surface_form(self.profile_id, "jobber")["form"]
        self.service.upsert_form_lemma_mapping(self.profile_id, form["id"], first["id"])
        self.service.upsert_form_lemma_mapping(
            self.profile_id, form["id"], second["id"], ambiguity_state="AMBIGUOUS"
        )
        self.assertEqual(first["id"], duplicate["id"])
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM form_lemma_links WHERE form_id=?", (form["id"],)).fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO form_lemma_links(id,language_profile_id,form_id,lemma_id,mapping_provenance,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    ("a" * 32, other, form["id"], first["id"], "ANALYZER", "now", "now"),
                )

    def test_one_knowledge_snapshot_and_append_only_events(self):
        lemma = self.lemma()
        self.service.update_knowledge(lemma["id"], {"knowledgeStatus": "LEARNING"})
        self.service.update_knowledge(lemma["id"], {"recognition": 3})
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM lemma_knowledge WHERE lemma_id=?", (lemma["id"],)).fetchone()[0], 1)
            event_id = connection.execute("SELECT id FROM knowledge_events LIMIT 1").fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE knowledge_events SET source='changed' WHERE id=?", (event_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM knowledge_events WHERE id=?", (event_id,))

    def test_exact_unicode_text_and_code_point_offsets_survive(self):
        raw = "Ærlig 😊 jobb\n  jobbene — blåbær."
        text = self.store.create_text_draft({
            "language_profile_id": self.profile_id,
            "title": "Unicode",
            "raw_text": raw,
            "source_type": "PASTED",
            "content_fingerprint": text_fingerprint(raw),
        })
        lemma = self.lemma()
        form = self.service.upsert_surface_form(self.profile_id, "jobb")["form"]
        sentence_id = "b" * 32
        start = raw.index("jobb")
        self.store.insert_text_structure(
            text["id"],
            sentences=[{
                "id": sentence_id, "sentence_order": 0, "source_start": 0,
                "source_end": len(raw), "exact_text": raw, "fingerprint": text_fingerprint(raw),
            }],
            tokens=[{
                "id": "c" * 32, "sentence_id": sentence_id, "token_order": 0,
                "surface": "jobb", "source_start": start, "source_end": start + 4,
                "token_kind": "WORD", "normalized_lookup": "jobb",
                "surface_form_id": form["id"], "selected_lemma_id": lemma["id"],
            }],
            analysis_run={
                "id": "d" * 32, "analyzer_id": "synthetic-test", "analyzer_version": "1",
                "contract_version": "language.analysis/v1", "state": "COMPLETED",
            },
        )
        loaded = self.store.get_text(text["id"])
        self.assertEqual(loaded["document"]["raw_text"].encode(), raw.encode())
        self.assertEqual(loaded["document"]["offset_unit"], OFFSET_UNIT)
        self.assertEqual(loaded["tokens"][0]["offset_unit"], OFFSET_UNIT)
        self.assertEqual(raw[loaded["tokens"][0]["source_start"]:loaded["tokens"][0]["source_end"]], "jobb")

    def test_sessions_and_exposures_are_idempotent(self):
        lemma = self.lemma()
        session = self.service.create_study_session({
            "languageProfileId": self.profile_id,
            "sessionType": "MANUAL",
            "clientSessionId": "session-1",
        })["data"]["session"]
        command = {
            "languageProfileId": self.profile_id,
            "lemmaId": lemma["id"],
            "studySessionId": session["id"],
            "sourceType": "MANUAL",
            "occurrenceCount": 4,
            "idempotencyKey": "exposure-1",
        }
        first = self.service.record_exposure(command)["data"]
        second = self.service.record_exposure(command)["data"]
        detail = self.service.get_lemma(lemma["id"])["data"]
        self.assertTrue(first["created"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["exposure"]["id"], second["exposure"]["id"])
        self.assertEqual(detail["knowledge"]["totalExposures"], 4)
        self.assertEqual([event["eventType"] for event in detail["events"]], ["EXPOSURE_RECORDED"])

    def test_merge_repoints_current_references_redirects_and_audits(self):
        source = self.service.upsert_lemma(
            self.profile_id, "arbeider", part_of_speech="NOUN", user_notes="source note"
        )["lemma"]
        target = self.lemma("arbeid", "NOUN")
        form = self.service.upsert_surface_form(self.profile_id, "arbeider")["form"]
        self.service.lock_form_lemma_mapping(self.profile_id, form["id"], source["id"], source="USER")
        raw = "arbeider"
        text = self.store.create_text_draft({
            "language_profile_id": self.profile_id, "title": "Merge", "raw_text": raw,
            "source_type": "PASTED", "content_fingerprint": text_fingerprint(raw),
        })
        self.store.insert_text_structure(text["id"], sentences=[], tokens=[{
            "id": "e" * 32, "token_order": 0, "surface": raw, "source_start": 0,
            "source_end": len(raw), "token_kind": "WORD", "surface_form_id": form["id"],
            "selected_lemma_id": source["id"],
        }])
        session = self.service.create_study_session({
            "languageProfileId": self.profile_id, "sessionType": "READER",
            "textDocumentId": text["id"], "clientSessionId": "merge-session",
        })["data"]["session"]
        self.service.record_exposure({
            "languageProfileId": self.profile_id, "lemmaId": source["id"],
            "surfaceFormId": form["id"], "textDocumentId": text["id"],
            "tokenId": "e" * 32, "studySessionId": session["id"],
            "sourceType": "READER", "occurrenceCount": 2, "idempotencyKey": "merge-exposure",
        })
        self.store.merge_lemmas(source["id"], target["id"], source="USER")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT merged_into_id FROM vocabulary_lemmas WHERE id=?", (source["id"],)).fetchone()[0], target["id"])
            self.assertEqual(connection.execute("SELECT lemma_id FROM form_lemma_links WHERE form_id=?", (form["id"],)).fetchone()[0], target["id"])
            self.assertEqual(connection.execute("SELECT selected_lemma_id FROM text_tokens WHERE id=?", ("e" * 32,)).fetchone()[0], target["id"])
            self.assertEqual(connection.execute("SELECT lemma_id FROM exposure_events WHERE idempotency_key='merge-exposure'").fetchone()[0], target["id"])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM lemma_knowledge WHERE lemma_id=?", (source["id"],)).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_events WHERE lemma_id=? AND event_type='LEMMA_MERGED'", (target["id"],)).fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT user_notes FROM vocabulary_lemmas WHERE id=?", (target["id"],)).fetchone()[0], "source note")

    def test_merge_failure_rolls_back_all_changes(self):
        source = self.lemma("kilde", "NOUN")
        target = self.lemma("mål", "NOUN")
        raw = "kilde"
        text = self.store.create_text_draft({
            "language_profile_id": self.profile_id, "title": "Rollback", "raw_text": raw,
            "source_type": "PASTED", "content_fingerprint": text_fingerprint(raw),
        })
        self.store.insert_text_structure(text["id"], sentences=[], tokens=[{
            "id": "f" * 32, "token_order": 0, "surface": raw, "source_start": 0,
            "source_end": 5, "token_kind": "WORD", "selected_lemma_id": source["id"],
        }])
        with self.store.connection() as connection:
            connection.execute(
                "CREATE TRIGGER fail_merge BEFORE UPDATE OF selected_lemma_id ON text_tokens "
                "BEGIN SELECT RAISE(ABORT, 'synthetic merge failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.merge_lemmas(source["id"], target["id"], source="USER")
        with self.store.connection() as connection:
            self.assertIsNone(connection.execute("SELECT merged_into_id FROM vocabulary_lemmas WHERE id=?", (source["id"],)).fetchone()[0])
            self.assertEqual(connection.execute("SELECT selected_lemma_id FROM text_tokens WHERE id=?", ("f" * 32,)).fetchone()[0], source["id"])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_events WHERE event_type='LEMMA_MERGED'").fetchone()[0], 0)

    def test_backup_is_consistent_sqlite_snapshot(self):
        lemma = self.lemma()
        result = self.store.backup_database()
        backup = self.store.backup_directory / result["fileName"]
        with sqlite3.connect(backup) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT id FROM vocabulary_lemmas").fetchone()[0], lemma["id"])

    def test_operation_scoped_connections_allow_concurrent_read_smoke(self):
        self.lemma()
        results = []
        threads = [threading.Thread(target=lambda: results.append(len(self.store.list_profiles()))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(results, [1, 1, 1, 1])

    def test_text_history_pagination_is_bounded_and_deterministic(self):
        created = []
        for index in range(3):
            created.append(self.service.create_text_draft({
                "languageProfileId": self.profile_id,
                "title": f"Text {index}",
                "rawText": f"jobb {index}",
            })["data"]["text"])
        first = self.service.list_texts(self.profile_id, limit=2)["data"]
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(first["pagination"]["total"], 3)
        self.assertEqual(first["pagination"]["nextCursor"], "2")
        second = self.service.list_texts(
            self.profile_id, limit=2, cursor=first["pagination"]["nextCursor"]
        )["data"]
        self.assertEqual(len(second["items"]), 1)
        self.assertIsNone(second["pagination"]["nextCursor"])
        ids = [row["id"] for row in first["items"] + second["items"]]
        self.assertEqual(set(ids), {row["id"] for row in created})


if __name__ == "__main__":
    unittest.main()
