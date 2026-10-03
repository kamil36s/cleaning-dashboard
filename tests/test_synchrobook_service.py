import io
import json
import logging
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

import synchrobook_backend.service as service_module


class SynchrobookServiceTests(unittest.TestCase):
    @staticmethod
    def _multipart(parts):
        boundary = "----synchrobook-test-boundary"
        body = bytearray()
        for name, filename, content, content_type in parts:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.extend(content)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        return f"multipart/form-data; boundary={boundary}", bytes(body)

    def test_import_accepts_pdf_and_naturally_orders_mp3_wav_m4b_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "synchrobook"
            books_root = data_root / "books"
            db_path = data_root / "library.db"
            with (
                mock.patch.object(service_module, "DATA_ROOT", data_root),
                mock.patch.object(service_module, "BOOKS_ROOT", books_root),
                mock.patch.object(service_module, "DB_PATH", db_path),
            ):
                service = service_module.SynchrobookService()
                service._logger = logging.getLogger(f"synchrobook-test-{uuid.uuid4().hex}")
                service._logger.addHandler(logging.NullHandler())
                service.initialize()
                content_type, body = self._multipart([
                    ("book", "Novel.pdf", b"pdf-data", "application/pdf"),
                    ("audiobook", "Chapter 10.m4b", b"audio-ten", "audio/mp4"),
                    ("audiobook", "Chapter 2.mp3", b"audio-two", "audio/mpeg"),
                    ("audiobook", "Chapter 3.wav", b"audio-three", "audio/wav"),
                ])
                with mock.patch.object(service, "start"):
                    result = service.import_book(content_type, len(body), io.BytesIO(body))
                book_dir = books_root / result["bookId"]
                manifest = json.loads((book_dir / "audio-sources.json").read_text(encoding="utf-8"))
                self.assertTrue((book_dir / "source.pdf").is_file())
                self.assertEqual(
                    [row["originalName"] for row in manifest["sources"]],
                    ["Chapter 2.mp3", "Chapter 3.wav", "Chapter 10.m4b"],
                )
                self.assertTrue((book_dir / "audio-sources" / "part-0001.mp3").is_file())
                self.assertTrue((book_dir / "audio-sources" / "part-0002.wav").is_file())
                self.assertTrue((book_dir / "audio-sources" / "part-0003.m4b").is_file())

    def test_processing_mode_is_persisted_and_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "synchrobook"
            books_root = data_root / "books"
            db_path = data_root / "library.db"
            with (
                mock.patch.object(service_module, "DATA_ROOT", data_root),
                mock.patch.object(service_module, "BOOKS_ROOT", books_root),
                mock.patch.object(service_module, "DB_PATH", db_path),
            ):
                service = service_module.SynchrobookService()
                service._logger = logging.getLogger(f"synchrobook-test-{uuid.uuid4().hex}")
                service._logger.addHandler(logging.NullHandler())

                self.assertFalse(service.get_processing_settings()["highMemory"])
                saved = service.save_processing_settings({"highMemory": True})

                self.assertTrue(saved["highMemory"])
                self.assertGreater(saved["transcriptionThreads"], 1)
                restarted = service_module.SynchrobookService()
                self.assertTrue(restarted.get_processing_settings()["highMemory"])
                with self.assertRaises(service_module.SynchrobookError):
                    restarted.save_processing_settings({"highMemory": "yes"})

    def test_delete_book_removes_database_state_and_book_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "synchrobook"
            books_root = data_root / "books"
            db_path = data_root / "library.db"
            with (
                mock.patch.object(service_module, "DATA_ROOT", data_root),
                mock.patch.object(service_module, "BOOKS_ROOT", books_root),
                mock.patch.object(service_module, "DB_PATH", db_path),
            ):
                service = service_module.SynchrobookService()
                service._logger = logging.getLogger(f"synchrobook-test-{uuid.uuid4().hex}")
                service._logger.addHandler(logging.NullHandler())
                service.initialize()
                book_id = "a" * 32
                book_dir = books_root / book_id
                book_dir.mkdir(parents=True)
                (book_dir / "source.epub").write_bytes(b"epub")
                alignment_dir = book_dir / "alignment"
                alignment_dir.mkdir()
                (alignment_dir / "alignment.json").write_text('{"chapters": []}', encoding="utf-8")
                (alignment_dir / "report.json").write_text('{"summary": {}}', encoding="utf-8")
                with closing(service._connect()) as connection:
                    with connection:
                        connection.execute(
                            "INSERT INTO books VALUES (?, ?, ?, NULL, ?, ?, NULL, '', NULL, ?, 'READY', NULL)",
                            (book_id, "Test book", "Test author", "source.epub", "source.m4b", service_module.utc_now()),
                        )
                        connection.execute(
                            "INSERT INTO progress VALUES (?, 12, NULL, NULL, 1, 'desk', ?)",
                            (book_id, service_module.utc_now()),
                        )
                        connection.execute(
                            """INSERT INTO jobs
                               (id, book_id, kind, status, stage, progress, message, error, created_at, updated_at, priority)
                               VALUES (?, ?, 'import', 'READY', 'READY', 100, '', NULL, ?, ?, 0)""",
                            ("b" * 32, book_id, service_module.utc_now(), service_module.utc_now()),
                        )

                result = service.delete_book(book_id)

                self.assertEqual(result["deleted"], book_id)
                self.assertFalse(result["filesPending"])
                self.assertFalse(book_dir.exists())
                archive_dir = data_root / "archive" / book_id
                self.assertTrue((archive_dir / "alignment.json").is_file())
                self.assertTrue((archive_dir / "report.json").is_file())
                self.assertTrue((archive_dir / "metadata.json").is_file())
                with closing(service._connect()) as connection:
                    self.assertIsNone(connection.execute("SELECT 1 FROM books WHERE id=?", (book_id,)).fetchone())
                    self.assertIsNone(connection.execute("SELECT 1 FROM progress WHERE book_id=?", (book_id,)).fetchone())
                    self.assertIsNone(connection.execute("SELECT 1 FROM jobs WHERE book_id=?", (book_id,)).fetchone())

    def test_restart_requeues_interrupted_job_and_priority_controls_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "synchrobook"
            books_root = data_root / "books"
            db_path = data_root / "library.db"
            with (
                mock.patch.object(service_module, "DATA_ROOT", data_root),
                mock.patch.object(service_module, "BOOKS_ROOT", books_root),
                mock.patch.object(service_module, "DB_PATH", db_path),
            ):
                service = service_module.SynchrobookService()
                service._logger = logging.getLogger(f"synchrobook-test-{uuid.uuid4().hex}")
                service._logger.addHandler(logging.NullHandler())
                service.initialize()
                now = service_module.utc_now()
                interrupted_book = "c" * 32
                queued_book = "d" * 32
                interrupted_job = "e" * 32
                queued_job = "f" * 32
                for book_id, title, state in (
                    (interrupted_book, "Interrupted", "TRANSCRIBING"),
                    (queued_book, "Priority", "ERROR"),
                ):
                    (books_root / book_id).mkdir(parents=True)
                    with closing(service._connect()) as connection:
                        with connection:
                            connection.execute(
                                "INSERT INTO books VALUES (?, ?, ?, NULL, ?, ?, NULL, '', NULL, ?, ?, ?)",
                                (book_id, title, "Author", "source.epub", "audio-sources.json", now, state, "old error"),
                            )
                            connection.execute(
                                "INSERT INTO progress VALUES (?, 0, NULL, NULL, 1, 'desk', ?)",
                                (book_id, now),
                            )
                with closing(service._connect()) as connection:
                    with connection:
                        connection.execute(
                            """INSERT INTO jobs
                               (id, book_id, kind, status, stage, progress, message, error, created_at, updated_at, priority)
                               VALUES (?, ?, 'import', 'TRANSCRIBING', 'TRANSCRIBING', 42, 'chunk 4', NULL, ?, ?, 0)""",
                            (interrupted_job, interrupted_book, now, now),
                        )
                        connection.execute(
                            """INSERT INTO jobs
                               (id, book_id, kind, status, stage, progress, message, error, created_at, updated_at, priority)
                               VALUES (?, ?, 'import', 'ERROR', 'ERROR', 0, 'failed', 'failure', ?, ?, 0)""",
                            (queued_job, queued_book, now, now),
                        )

                restarted = service_module.SynchrobookService()
                restarted._logger = service._logger
                restarted.initialize()
                with closing(restarted._connect()) as connection:
                    recovered = connection.execute("SELECT * FROM jobs WHERE id=?", (interrupted_job,)).fetchone()
                self.assertEqual(recovered["status"], "QUEUED")
                self.assertEqual(recovered["progress"], 42)
                self.assertIsNone(recovered["error"])

                with mock.patch.object(restarted, "start"):
                    result = restarted.resume_job(queued_job, priority=100)
                self.assertEqual(result["job"]["priority"], 100)
                self.assertEqual(restarted._next_job()["id"], queued_job)

    def test_rebuild_keeps_existing_book_readable_while_queued_and_processing(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "synchrobook"
            books_root = data_root / "books"
            db_path = data_root / "library.db"
            with (
                mock.patch.object(service_module, "DATA_ROOT", data_root),
                mock.patch.object(service_module, "BOOKS_ROOT", books_root),
                mock.patch.object(service_module, "DB_PATH", db_path),
            ):
                service = service_module.SynchrobookService()
                service._logger = logging.getLogger(f"synchrobook-test-{uuid.uuid4().hex}")
                service._logger.addHandler(logging.NullHandler())
                service.initialize()
                book_id = "1" * 32
                book_dir = books_root / book_id
                for relative, content in (
                    ("text/book.json", "{}"),
                    ("audio/playback.m4a", "audio"),
                    ("alignment/alignment.json", '{"chapters": []}'),
                    ("alignment/report.json", '{"summary": {}}'),
                ):
                    path = book_dir / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                now = service_module.utc_now()
                with closing(service._connect()) as connection:
                    with connection:
                        connection.execute(
                            "INSERT INTO books VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 'READY', NULL)",
                            (book_id, "Readable", "Author", "source.epub", "source.m4b", "audio/playback.m4a", "en", 10, now),
                        )

                with mock.patch.object(service, "start"):
                    result = service.queue_action(book_id, "alignment")
                with closing(service._connect()) as connection:
                    book = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
                self.assertEqual(book["processing_state"], "READY")

                service._set_job(result["jobId"], "ALIGNING", 80, "Rebuilding")
                with closing(service._connect()) as connection:
                    book = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
                self.assertEqual(book["processing_state"], "READY")

                restarted = service_module.SynchrobookService()
                restarted._logger = service._logger
                restarted.initialize()
                with closing(restarted._connect()) as connection:
                    book = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
                    job = connection.execute("SELECT * FROM jobs WHERE id=?", (result["jobId"],)).fetchone()
                self.assertEqual(job["status"], "QUEUED")
                self.assertEqual(book["processing_state"], "READY")


if __name__ == "__main__":
    unittest.main()
