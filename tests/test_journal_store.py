import tempfile
import unittest
import sqlite3
from pathlib import Path

from journal_store import JournalError, JournalStore


class JournalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="journal-tests-")
        self.store = JournalStore(Path(self.temp.name) / "journal.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def test_manual_entry_crud(self):
        created = self.store.create({
            "title": "Pierwszy dzień",
            "content": "Treść wpisu",
            "entryDate": "2026-07-21T12:00:00Z",
            "tags": ["myśli", "myśli", "dom"],
            "location": "Kraków",
        })

        self.assertEqual(created["sourceType"], "manual")
        self.assertEqual(created["entryKind"], "journal")
        self.assertEqual(created["tags"], ["myśli", "dom"])
        self.assertEqual(created["location"], "Kraków")
        self.assertEqual(self.store.list()[0]["id"], created["id"])

        updated = self.store.update(created["id"], {"title": "Poprawiony", "content": "Nowa treść"})
        self.assertEqual(updated["title"], "Poprawiony")
        self.assertEqual(updated["content"], "Nowa treść")
        self.assertTrue(self.store.delete(created["id"])["deleted"])
        with self.assertRaises(JournalError):
            self.store.get(created["id"])

    def test_untitled_entries_use_three_asterisks(self):
        created = self.store.create({
            "title": "",
            "content": "Treść bez tytułu",
            "entryDate": "2026-07-21",
        })
        self.assertEqual(created["title"], "* * *")

        updated = self.store.update(created["id"], {"title": "Bez tytułu"})
        self.assertEqual(updated["title"], "* * *")

    def test_voice_publication_keeps_metadata_and_updates_without_duplicate(self):
        voice_entry = {
            "id": "a" * 32,
            "title": "Sen o jaskini",
            "transcript": "Uporządkowana wersja.",
            "rawTranscript": "brudny tekst",
            "transcriptSegments": [{"text": "brudny tekst"}],
            "recordedAt": "2026-07-20T08:30:00Z",
            "uploadedAt": "2026-07-21T10:00:00Z",
            "entryCategory": "spontaneous",
            "originalFilename": "sen.aac",
            "storedFilename": "stored.aac",
            "audioPath": "data/raw/voice-journal/audio/stored.aac",
            "audioUrl": "/api/voice-journal/entries/audio",
            "mimeType": "audio/aac",
            "sizeBytes": 1024,
            "durationSeconds": 46.2,
            "engine": "faster-whisper",
            "model": "turbo",
            "device": "cpu",
            "language": "pl",
            "realTimeFactor": 0.75,
            "tags": ["sen"],
            "updatedAt": "2026-07-21T11:00:00Z",
        }

        first = self.store.publish_voice_entry(voice_entry)
        self.assertEqual(first["content"], "Uporządkowana wersja.")
        self.assertEqual(first["sourceVoiceJournalEntryId"], voice_entry["id"])
        self.assertEqual(first["sourceMetadata"]["originalFilename"], "sen.aac")
        self.assertNotIn("rawTranscript", first["sourceMetadata"])

        voice_entry["transcript"] = "Lepsza uporządkowana wersja."
        second = self.store.publish_voice_entry(voice_entry)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["content"], "Lepsza uporządkowana wersja.")
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.voice_publication_lookup()[voice_entry["id"]], {
            "id": first["id"],
            "publishedAt": second["publishedAt"],
            "updatedAt": second["updatedAt"],
        })

        voice_entry["transcript"] = "[00:00] Pierwszy fragment.\n\n[01:02] Drugi fragment."
        without_timestamps = self.store.publish_voice_entry(voice_entry)
        self.assertEqual(without_timestamps["content"], "Pierwszy fragment.\n\nDrugi fragment.")

    def test_voice_publication_requires_organized_content(self):
        with self.assertRaises(JournalError):
            self.store.publish_voice_entry({
                "id": "b" * 32,
                "transcript": "",
                "recordedAt": "2026-07-21T10:00:00Z",
            })

    def test_rich_text_and_illustration_are_persisted(self):
        illustration = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
        created = self.store.create({
            "title": "Ilustrowany wpis",
            "content": "<p><strong>Ważne</strong></p>",
            "contentFormat": "html",
            "entryDate": "2026-07-21T12:00:00Z",
            "tags": [],
            "illustration": illustration,
            "illustrationAlt": "Mała ilustracja",
        })

        self.assertEqual(created["contentFormat"], "html")
        self.assertEqual(created["illustration"], illustration)
        self.assertEqual(created["illustrationAlt"], "Mała ilustracja")

        cleared = self.store.update(created["id"], {"illustration": ""})
        self.assertEqual(cleared["illustration"], "")
        self.assertEqual(cleared["illustrationAlt"], "")

    def test_external_poem_import_is_atomic_and_idempotent(self):
        illustration = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
        payload = {
            "title": "Ararat",
            "content": "<p>Pierwsza wersja</p>",
            "contentFormat": "html",
            "entryDate": "2023-07-19",
            "entryKind": "poem",
            "tags": ["poem"],
            "sourceType": "tumblr",
            "sourceExternalId": "723300786820579328",
            "sourceMetadata": {"tumblr": {"publishedAtUtc": "2023-07-19T19:03:03Z"}},
        }
        first = self.store.import_external_entries([payload])[0]
        payload["content"] = "<p>Wersja zaktualizowana</p>"
        second = self.store.import_external_entries([payload])[0]

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["entryKind"], "poem")
        self.assertEqual(second["sourceType"], "tumblr")
        self.assertEqual(second["sourceExternalId"], payload["sourceExternalId"])
        self.assertEqual(second["content"], "<p>Wersja zaktualizowana</p>")
        self.assertEqual(len(self.store.list()), 1)

        image_poem = {**payload, "sourceExternalId": "image-1", "content": "", "illustration": illustration}
        imported = self.store.import_external_entries([image_poem])[0]
        self.assertEqual(imported["illustration"], illustration)

        invalid = {**payload, "sourceExternalId": "invalid", "entryKind": "other"}
        with self.assertRaises(JournalError):
            self.store.import_external_entries([payload, invalid])
        self.assertEqual(len(self.store.list()), 2)

    def test_existing_database_is_migrated(self):
        legacy_path = Path(self.temp.name) / "legacy.sqlite"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute("""
                CREATE TABLE journal_entries (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
                    entry_date TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '[]',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_voice_journal_entry_id TEXT UNIQUE,
                    source_metadata_json TEXT NOT NULL DEFAULT '{}', published_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            connection.execute(
                """
                INSERT INTO journal_entries (
                    id, title, content, entry_date, source_type, created_at, updated_at
                ) VALUES ('legacy-untitled', '', 'Treść', '2020-01-01', 'manual', '2020-01-01', '2020-01-01')
                """
            )
        legacy_store = JournalStore(legacy_path)
        legacy_store.initialize()
        with sqlite3.connect(legacy_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(journal_entries)")}
            migrated_title = connection.execute(
                "SELECT title FROM journal_entries WHERE id = 'legacy-untitled'"
            ).fetchone()[0]

        self.assertTrue({
            "content_format", "illustration_data_url", "illustration_alt", "location",
            "entry_kind", "source_external_id",
        }.issubset(columns))
        self.assertEqual(migrated_title, "* * *")


if __name__ == "__main__":
    unittest.main()
