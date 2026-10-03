import json
import tempfile
import threading
import unittest
import urllib.request
import sqlite3
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import server as dashboard_server
import voice_journal_store
from journal_store import JournalStore


def entry_payload(**overrides):
    payload = {
        "title": "Poranna notatka",
        "entryCategory": "morning",
        "recordedAt": "2026-07-21T06:30:00.000Z",
        "dateSource": "file_modified",
        "transcript": "Treść wpisu.",
        "rawTranscript": "Ee, treść wpisu.",
        "transcriptSegments": [
            {"start": 0.25, "end": 2.0, "text": "Ee, treść wpisu."},
        ],
        "tags": ["dzień", "plan"],
        "language": "pl",
        "model": "turbo",
        "device": "cpu",
        "transcriptionDurationSeconds": 4.2,
        "realTimeFactor": 0.42,
    }
    payload.update(overrides)
    return payload


def multipart_entry(payload, content=b"wave-bytes"):
    boundary = "VoiceJournalCrudBoundary"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"entry\"\r\n\r\n".encode(),
        json.dumps(payload, ensure_ascii=False).encode(),
        b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"memo.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return f"multipart/form-data; boundary={boundary}", body


class VoiceJournalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="voice-journal-store-test-")
        self.root = Path(self.temp_dir.name)
        self.store = voice_journal_store.VoiceJournalStore(
            self.root / "voice-journal.sqlite",
            self.root / "audio",
            self.root,
        )
        self.probe_patch = mock.patch.object(voice_journal_store, "probe_audio", return_value={
            "durationSeconds": 10.0,
            "format": "wav",
            "codec": "pcm_s16le",
            "sampleRate": 16000,
            "channels": 1,
        })
        self.probe_patch.start()

    def tearDown(self):
        self.probe_patch.stop()
        self.temp_dir.cleanup()

    def test_sqlite_create_list_update_and_delete_audio(self):
        audio = {"filename": "memo.wav", "mime": "audio/wav", "content": b"wave-bytes"}
        created = self.store.create(audio, entry_payload(title=""))

        self.assertTrue((self.root / created["audioPath"]).is_file())
        self.assertEqual(created["title"], "memo.wav")
        self.assertEqual(created["originalFilename"], "memo.wav")
        self.assertEqual(created["durationSeconds"], 10.0)
        self.assertEqual(created["rawTranscript"], "Ee, treść wpisu.")
        self.assertEqual(created["transcriptSegments"][0]["start"], 0.25)
        self.assertEqual(self.store.list()[0]["id"], created["id"])

        updated = self.store.update(created["id"], {
            "title": "Poprawiony tytuł",
            "recordedAt": "2026-07-21T07:00:00.000Z",
            "entryCategory": "spontaneous",
            "tags": ["nowy"],
            "transcript": "Tekst po korekcie.",
        })
        self.assertEqual(updated["title"], "Poprawiony tytuł")
        self.assertEqual(updated["dateSource"], "user_corrected")
        self.assertEqual(updated["tags"], ["nowy"])
        self.assertEqual(updated["transcript"], "Tekst po korekcie.")
        self.assertEqual(updated["rawTranscript"], "Ee, treść wpisu.")
        self.assertEqual(updated["transcriptSegments"][0]["text"], "Ee, treść wpisu.")

        audio_path = self.root / updated["audioPath"]
        deleted = self.store.delete(created["id"], delete_audio=True)
        self.assertTrue(deleted["deleted"])
        self.assertTrue(deleted["audioDeleted"])
        self.assertFalse(audio_path.exists())
        self.assertEqual(self.store.list(), [])

    def test_migrates_existing_transcript_without_losing_it(self):
        legacy_db = self.root / "legacy.sqlite"
        with sqlite3.connect(legacy_db) as connection:
            connection.executescript(
                """
                CREATE TABLE voice_journal_entries (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', entry_category TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, uploaded_at TEXT NOT NULL, date_source TEXT NOT NULL,
                    original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL UNIQUE,
                    mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, duration_seconds REAL NOT NULL,
                    audio_path TEXT NOT NULL, transcript TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                    language TEXT NOT NULL, model TEXT NOT NULL, device TEXT NOT NULL,
                    transcription_duration_seconds REAL NOT NULL, real_time_factor REAL NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT INTO voice_journal_entries VALUES (
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '', 'spontaneous',
                    '2026-07-21T06:30:00.000Z', '2026-07-21T06:31:00.000Z', 'file_modified',
                    'memo.wav', 'stored.wav', 'audio/wav', 10, 2.0, 'audio/stored.wav',
                    'Zachowany tekst.', '[]', 'pl', 'turbo', 'cpu', 1.0, 0.5,
                    '2026-07-21T06:31:00.000Z', '2026-07-21T06:31:00.000Z'
                );
                PRAGMA user_version = 1;
                """
            )
        legacy_store = voice_journal_store.VoiceJournalStore(legacy_db, self.root / "audio", self.root)

        entry = legacy_store.get("a" * 32)

        self.assertEqual(entry["transcript"], "Zachowany tekst.")
        self.assertEqual(entry["rawTranscript"], "Zachowany tekst.")
        self.assertEqual(entry["transcriptSegments"], [])
        self.assertEqual(entry["engine"], "openai-whisper")
        self.assertEqual(entry["correctionHistory"], [])

    def test_persists_corrections_without_overwriting_raw_transcript(self):
        audio = {"filename": "memo.wav", "mime": "audio/wav", "content": b"wave-bytes"}
        created = self.store.create(audio, entry_payload())
        correction_data = {
            "version": 1,
            "engine": "openai-whisper",
            "segments": [{
                "id": "segment-1", "start": 0.25, "end": 2.0,
                "originalText": "Ee, treść wpisu.", "correctedText": "Treść wpisu.",
                "words": [],
            }],
        }
        history = [{
            "at": "2026-07-21T07:00:00Z", "operation": "correct",
            "targetId": "segment-1", "previousValue": "Ee, treść wpisu.",
            "newValue": "Treść wpisu.",
        }]

        updated = self.store.update(created["id"], {
            "transcript": "Treść wpisu.",
            "transcriptionData": correction_data,
            "correctionHistory": history,
            "correctionSettings": {"confidenceGood": 0.75},
        })

        self.assertEqual(updated["rawTranscript"], created["rawTranscript"])
        self.assertEqual(updated["transcriptionData"], correction_data)
        self.assertEqual(updated["correctionHistory"], history)
        self.assertEqual(updated["correctionSettings"]["confidenceGood"], 0.75)


class VoiceJournalCrudEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="voice-journal-http-test-")
        cls.root = Path(cls.temp_dir.name)
        cls.store = voice_journal_store.VoiceJournalStore(
            cls.root / "voice-journal.sqlite",
            cls.root / "audio",
            cls.root,
        )
        cls.journal_store = JournalStore(cls.root / "journal.sqlite")
        cls.store_patch = mock.patch.object(dashboard_server, "VOICE_JOURNAL_STORE", cls.store)
        cls.journal_store_patch = mock.patch.object(dashboard_server, "JOURNAL_STORE", cls.journal_store)
        cls.log_patch = mock.patch.object(dashboard_server, "log_line", return_value=None)
        cls.probe_patch = mock.patch.object(voice_journal_store, "probe_audio", return_value={
            "durationSeconds": 10.0,
            "format": "wav",
            "codec": "pcm_s16le",
            "sampleRate": 16000,
            "channels": 1,
        })
        cls.store_patch.start()
        cls.journal_store_patch.start()
        cls.log_patch.start()
        cls.probe_patch.start()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.probe_patch.stop()
        cls.log_patch.stop()
        cls.journal_store_patch.stop()
        cls.store_patch.stop()
        cls.temp_dir.cleanup()

    def test_http_crud_and_controlled_audio_range(self):
        content_type, body = multipart_entry(entry_payload())
        create_request = urllib.request.Request(
            f"{self.base_url}/api/voice-journal/entries",
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        with urllib.request.urlopen(create_request, timeout=10) as response:
            created = json.load(response)
            self.assertEqual(response.status, 201)

        with urllib.request.urlopen(f"{self.base_url}/api/voice-journal/entries", timeout=10) as response:
            listed = json.load(response)["entries"]
        self.assertEqual([entry["id"] for entry in listed], [created["id"]])

        update_request = urllib.request.Request(
            f"{self.base_url}/api/voice-journal/entries/{created['id']}",
            data=json.dumps({"title": "Tytuł z PATCH", "transcript": "Nowa treść"}).encode(),
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(update_request, timeout=10) as response:
            updated = json.load(response)
        self.assertEqual(updated["title"], "Tytuł z PATCH")
        self.assertEqual(updated["transcript"], "Nowa treść")

        publication = self.journal_store.publish_voice_entry(updated)
        with urllib.request.urlopen(f"{self.base_url}/api/voice-journal/entries", timeout=10) as response:
            published_entry = json.load(response)["entries"][0]
        self.assertEqual(published_entry["journalPublication"]["id"], publication["id"])
        self.assertEqual(published_entry["journalPublication"]["publishedAt"], publication["publishedAt"])

        audio_request = urllib.request.Request(
            f"{self.base_url}{created['audioUrl']}",
            headers={"Range": "bytes=0-3"},
        )
        with urllib.request.urlopen(audio_request, timeout=10) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 0-3/10")
            self.assertEqual(response.read(), b"wave")

        audio_path = self.root / created["audioPath"]
        delete_request = urllib.request.Request(
            f"{self.base_url}/api/voice-journal/entries/{created['id']}?deleteAudio=true",
            method="DELETE",
        )
        with urllib.request.urlopen(delete_request, timeout=10) as response:
            deleted = json.load(response)
        self.assertTrue(deleted["audioDeleted"])
        self.assertFalse(audio_path.exists())


if __name__ == "__main__":
    unittest.main()
