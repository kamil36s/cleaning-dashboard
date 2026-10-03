from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from language_learning.backup import (
    BackupError, create_backup, preview_restore, restore_backup, validate_backup,
)
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from language_learning.jobs import LanguageJobManager
from language_learning.migrations import SCHEMA_VERSION
from tests.language_phase2_fakes import FakeAnalyzer, FakeFrequencyProvider, registry_for, wait_for_job


ROOT = Path(__file__).resolve().parents[1]
AUDIO = b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40


class LanguageBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "source/data/language-learning.sqlite"
        self.store = LanguageStore(self.db)
        self.service = LanguageService(
            self.store, analyzer_registry=registry_for(FakeAnalyzer()),
            frequency_provider=FakeFrequencyProvider(),
        )
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.lemma = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        self.media = self.service.import_content_audio(
            self.profile["id"], data=AUDIO, title="Owned audio",
            original_name="owned.wav", mime_type="audio/wav",
        )["data"]
        self.reference = self.root / "absent-reference.sqlite"

    def _backup(self):
        return create_backup(self.db, self.root / "packages", project_root=ROOT,
                             reference_db=self.reference)

    def _validate(self, package):
        return validate_backup(package, project_root=ROOT, reference_db=self.reference)

    def test_wal_snapshot_clean_restore_and_canonical_facts(self):
        self.service.update_knowledge(self.lemma["id"], {"knowledgeStatus": "KNOWN", "recognition": 4})
        topic = self.service.create_topic(self.profile["id"], {"displayName": "Work"})["data"]["topic"]
        self.service.assign_topic_lemma(topic["id"], {"lemmaId": self.lemma["id"]})
        self.service.create_goal(self.profile["id"], {
            "metric": "NEW_WORDS", "targetValue": 2, "unit": "WORDS",
        })
        campaign = self.service.create_campaign(self.profile["id"], {
            "name": "Recovery campaign", "targetDate": "2027-05-01",
            "milestones": [{"type": "READER_TEXTS_COMPLETED", "target": 2}],
        })["data"]["campaign"]
        self.service.create_phrasebook_entry(self.profile["id"], {
            "expression": "på jobb", "sourceType": "MANUAL", "sourceEntityId": "synthetic",
            "sourceContext": "Han er på jobb.", "sourceProvenance": {"fixture": True},
            "links": [{"type": "LEMMA", "value": self.lemma["id"], "metadata": {}}],
        })
        benchmark = self.service.start_benchmark(self.profile["id"])["data"]
        self.service.benchmark_response(self.profile["id"], benchmark["id"], {
            "itemId": benchmark["items"][0]["id"], "response": benchmark["items"][0]["options"][0],
        })
        manager = LanguageJobManager(self.service, poll_interval=0.01)
        manager.start()
        try:
            attached = self.service.add_content_transcript(self.media["item"]["id"], {
                "format": "SRT", "transcriptText": "1\n00:00:00,000 --> 00:00:02,000\nJeg har en jobb.\n",
            })["data"]
            wait_for_job(self.service, attached["latestJob"]["id"])
        finally:
            manager.stop()
        with sqlite3.connect(self.db) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("UPDATE vocabulary_lemmas SET user_notes='committed WAL' WHERE id=?",
                           (self.lemma["id"],))
        self.assertTrue(Path(str(self.db) + "-wal").is_file())
        before_export = self.store.export_data()["data"]
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "PHASE12_PRIVATE_SENTINEL",
                                       "LANGUAGE_ANKI_CONNECT_API_KEY": "PHASE12_PRIVATE_SENTINEL"}):
            package = self._backup()
        writer.close()
        self.assertEqual(self.store.export_data()["data"], before_export)
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["backupFormatVersion"], "language-backup/v1")
        self.assertEqual(manifest["mainSchemaVersion"], SCHEMA_VERSION)
        self.assertEqual(len(manifest["managedArtifacts"]), 1)
        self.assertEqual(manifest["reference"]["state"], "UNAVAILABLE")
        self.assertFalse(any("key" in name.lower() for name in manifest))
        self.assertNotIn("PHASE12_PRIVATE_SENTINEL", json.dumps(manifest))
        self.assertEqual(self._validate(package)["status"], "VALID_WITH_WARNINGS")
        files_before = {path.relative_to(package).as_posix(): path.read_bytes()
                        for path in package.rglob("*") if path.is_file()}
        self._validate(package)
        files_after = {path.relative_to(package).as_posix(): path.read_bytes()
                       for path in package.rglob("*") if path.is_file()}
        self.assertEqual(files_before, files_after)
        self.assertFalse((package / "language-learning.sqlite-wal").exists())
        self.assertFalse((package / "language-learning.sqlite-shm").exists())
        destination = self.root / "recovered"
        before = preview_restore(package, destination, project_root=ROOT, reference_db=self.reference)
        self.assertTrue(before["targetEmpty"])
        self.assertFalse(destination.exists())
        restored = restore_backup(package, destination, project_root=ROOT,
                                  reference_db=self.reference)
        self.assertEqual(restored["status"], "RESTORED")
        recovered_store = LanguageStore(destination / "data/language-learning.sqlite")
        recovered_service = LanguageService(recovered_store,
            analyzer_registry=registry_for(FakeAnalyzer()), frequency_provider=FakeFrequencyProvider())
        recovered_service.initialize()
        self.assertEqual(recovered_service.get_lemma(self.lemma["id"])["data"]["lemma"]["userNotes"],
                         "committed WAL")
        artifact_id = self.media["media"]["id"]
        self.assertEqual(recovered_service.content_media_file(artifact_id)[0].read_bytes(), AUDIO)
        self.assertEqual(recovered_store.export_data()["data"], before_export)
        self.assertEqual(recovered_service.campaigns(self.profile["id"])["data"]["items"][0]["id"],
                         campaign["id"])
        self.assertEqual(len(recovered_service.content_detail(self.media["item"]["id"])["data"]["alignments"]), 1)
        with recovered_store.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaises(BackupError):
            restore_backup(package, destination, project_root=ROOT, reference_db=self.reference)

    def test_tamper_traversal_duplicate_and_unsupported_version(self):
        package = self._backup()
        manifest_file = package / "manifest.json"
        original = manifest_file.read_text(encoding="utf-8")
        entry = json.loads(original)["managedArtifacts"][0]
        artifact = package / entry["path"]
        artifact.write_bytes(b"changed")
        self.assertEqual(self._validate(package)["status"], "INVALID")
        artifact.write_bytes(AUDIO)
        for changed in (
            {"backupFormatVersion": "language-backup/v2"},
            {"mainSchemaVersion": SCHEMA_VERSION + 1},
            {"mainDb": {"path": "language-learning.sqlite", "size": 1, "sha256": "0" * 64}},
            {"managedArtifacts": [{**entry, "path": "../escape"}]},
            {"managedArtifacts": [{**entry, "path": "C:/escape"}]},
            {"managedArtifacts": [entry, entry]},
            {"staticContracts": {"benchmarkContent": "0" * 64}},
        ):
            manifest = json.loads(original)
            manifest.update(changed)
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self._validate(package)["status"], "INVALID")
        manifest_file.write_text(original, encoding="utf-8")
        self.assertEqual(self._validate(package)["status"], "VALID_WITH_WARNINGS")

    def test_missing_required_media_refuses_backup_and_orphan_warns(self):
        file = self.service.content_media_file(self.media["media"]["id"])[0]
        file.unlink()
        with self.assertRaises(BackupError):
            self._backup()
        self.assertFalse(list((self.root / "packages").iterdir()))
        file.write_bytes(AUDIO)
        package = self._backup()
        (package / "artifacts/orphan.wav").write_bytes(AUDIO)
        result = self._validate(package)
        self.assertEqual(result["status"], "VALID_WITH_WARNINGS")
        self.assertTrue(any("Unreferenced" in item for item in result["warnings"]))

    def test_escaping_symlink_cannot_be_copied(self):
        media = self.service.content_media_file(self.media["media"]["id"])[0]
        external = self.root / "outside.wav"
        external.write_bytes(AUDIO)
        media.unlink()
        try:
            media.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("File symlinks are unavailable on this host")
        with self.assertRaises(BackupError):
            self._backup()

    def test_unsafe_database_media_path_and_nonempty_restore_target_are_refused(self):
        package = self._backup()
        destination = self.root / "occupied"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        preview = preview_restore(package, destination, project_root=ROOT,
                                  reference_db=self.reference)
        self.assertEqual(preview["status"], "INVALID")
        with self.assertRaises(BackupError):
            restore_backup(package, destination, project_root=ROOT,
                           reference_db=self.reference)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse(list(self.root.glob(".language-restore-*")))
        with sqlite3.connect(self.db) as writer:
            writer.execute("UPDATE content_artifacts SET managed_relpath='../outside.wav'")
        with self.assertRaises(BackupError):
            self._backup()


if __name__ == "__main__":
    unittest.main()
