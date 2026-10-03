"""Persistent library, streaming import, and background pipeline for Synchrobook."""

from __future__ import annotations

import cgi
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from voice_journal import voice_journal_health

from .alignment import build_alignment
from .document import extract_book
from .epub import repair_fragmented_words
from .media import ANALYSIS_CHUNK_SECONDS, prepare_analysis_chunks, prepare_audiobook, prepare_playback


ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("SYNCHROBOOK_DATA_DIR", ROOT / "data" / "synchrobook")).resolve()
BOOKS_ROOT = DATA_ROOT / "books"
DB_PATH = DATA_ROOT / "library.db"
MAX_BOOK_BYTES = 512 * 1024 * 1024
MAX_M4B_BYTES = 8 * 1024 * 1024 * 1024
MAX_IMPORT_BYTES = MAX_BOOK_BYTES + MAX_M4B_BYTES + 4 * 1024 * 1024
BOOK_EXTENSIONS = {".epub", ".pdf", ".mobi"}
AUDIO_EXTENSIONS = {".m4b", ".mp3", ".wav"}
ACTIVE_JOB_STATES = {"QUEUED", "BOOK_PROCESSING", "EPUB_PROCESSING", "AUDIO_PREPARING", "AUDIO_MERGING", "TRANSCRIBING", "ALIGNING", "FINALIZING"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class SynchrobookError(RuntimeError):
    def __init__(self, message: str, *, status: int = 400, code: str = "synchrobook_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self) -> dict:
        return {"ok": False, "error": str(self), "code": self.code}


class SynchrobookService:
    def __init__(self):
        self._initialized = False
        self._init_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_process: subprocess.Popen | None = None
        self._logger = logging.getLogger("synchrobook")

    def _connect(self):
        connection = sqlite3.connect(DB_PATH, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 20000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            BOOKS_ROOT.mkdir(parents=True, exist_ok=True)
            if not self._logger.handlers:
                # Open lazily: read-only service initialization (and its tests) must
                # not keep a Windows handle on a temporary data directory.
                handler = logging.FileHandler(DATA_ROOT / "synchrobook.log", encoding="utf-8", delay=True)
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                self._logger.addHandler(handler)
                self._logger.setLevel(logging.INFO)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS books (
                        id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
                        cover_file TEXT, epub_file TEXT NOT NULL, audiobook_file TEXT NOT NULL,
                        playback_file TEXT, language TEXT, duration REAL,
                        imported_at TEXT NOT NULL, processing_state TEXT NOT NULL, error TEXT
                    );
                    CREATE TABLE IF NOT EXISTS progress (
                        book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
                        audio_timestamp REAL NOT NULL DEFAULT 0, chapter_id TEXT,
                        sentence_id TEXT, playback_speed REAL NOT NULL DEFAULT 1,
                        reading_mode TEXT NOT NULL DEFAULT 'desk', last_opened TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                        kind TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                        progress REAL, message TEXT, error TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS idx_synchrobook_jobs_queue ON jobs(status, created_at);
                    """
                )
                job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
                if "priority" not in job_columns:
                    connection.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
                now = utc_now()
                connection.execute(
                    """UPDATE jobs SET status='QUEUED', stage='QUEUED',
                       message='Wznawianie od ostatniego zapisanego etapu po restarcie backendu',
                       error=NULL, updated_at=?
                       WHERE status IN ('BOOK_PROCESSING','EPUB_PROCESSING','AUDIO_PREPARING','AUDIO_MERGING','TRANSCRIBING','ALIGNING','FINALIZING')""",
                    (now,),
                )
                connection.execute(
                    """UPDATE books SET processing_state='QUEUED', error=NULL
                       WHERE id IN (SELECT book_id FROM jobs WHERE status='QUEUED')"""
                )
                queued_rebuilds = connection.execute(
                    "SELECT DISTINCT book_id FROM jobs WHERE status='QUEUED' AND kind<>'import'"
                ).fetchall()
                for row in queued_rebuilds:
                    if self._has_readable_artifacts(row["book_id"]):
                        connection.execute(
                            "UPDATE books SET processing_state='READY', error=NULL WHERE id=?",
                            (row["book_id"],),
                        )
            self._initialized = True

    def start(self) -> None:
        self.initialize()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="synchrobook-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        self._wake.set()
        if self._active_process and self._active_process.poll() is None:
            self._active_process.terminate()
        if self._thread:
            self._thread.join(timeout=timeout)

    @staticmethod
    def _validate_id(value: str, label: str = "identifier") -> str:
        if not re.fullmatch(r"[a-f0-9]{32}", str(value or "")):
            raise SynchrobookError(f"Invalid {label}", status=404, code="not_found")
        return value

    def _book_dir(self, book_id: str) -> Path:
        return BOOKS_ROOT / self._validate_id(book_id, "book identifier")

    def _has_readable_artifacts(self, book_id: str) -> bool:
        book_dir = self._book_dir(book_id)
        return all(path.is_file() for path in (
            book_dir / "text" / "book.json",
            book_dir / "audio" / "playback.m4a",
            book_dir / "alignment" / "alignment.json",
            book_dir / "alignment" / "report.json",
        ))

    @staticmethod
    def _copy_upload(field, destination: Path, limit: int) -> int:
        filename = str(getattr(field, "filename", "") or "")
        if not filename or Path(filename).name != filename or any(char in filename for char in ("/", "\\", "\0")):
            raise SynchrobookError("Unsafe upload filename", code="unsafe_filename")
        size = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as target:
            while True:
                chunk = field.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise SynchrobookError("Uploaded file is too large", status=413, code="payload_too_large")
                target.write(chunk)
        if size == 0:
            raise SynchrobookError("Uploaded file is empty", code="empty_file")
        return size

    @staticmethod
    def _natural_filename_key(field) -> list:
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(field.filename or ""))]

    def import_book(self, content_type: str, content_length: int, stream) -> dict:
        self.start()
        if not content_type.lower().startswith("multipart/form-data"):
            raise SynchrobookError("Content-Type must be multipart/form-data", status=415, code="unsupported_media_type")
        if content_length <= 0:
            raise SynchrobookError("Import body is required", code="empty_body")
        if content_length > MAX_IMPORT_BYTES:
            raise SynchrobookError("Import is too large", status=413, code="payload_too_large")
        try:
            form = cgi.FieldStorage(
                fp=stream,
                headers={"content-type": content_type, "content-length": str(content_length)},
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(content_length)},
                keep_blank_values=False,
            )
        except Exception as exc:
            raise SynchrobookError("Malformed multipart import", code="invalid_multipart") from exc
        book_key = "book" if "book" in form else "epub" if "epub" in form else None
        if not book_key or "audiobook" not in form:
            raise SynchrobookError("One book and at least one audio file are required", code="missing_files")
        book_field, audio_value = form[book_key], form["audiobook"]
        if isinstance(book_field, list):
            raise SynchrobookError("Select exactly one EPUB, PDF, or MOBI book", code="duplicate_files")
        audio_fields = audio_value if isinstance(audio_value, list) else [audio_value]
        if not audio_fields or len(audio_fields) > 250:
            raise SynchrobookError("Select between 1 and 250 audiobook files", code="invalid_audio_count")
        book_extension = Path(book_field.filename or "").suffix.lower()
        if book_extension not in BOOK_EXTENSIONS:
            raise SynchrobookError("Book file must be EPUB, PDF, or MOBI", status=415, code="invalid_book")
        for audio_field in audio_fields:
            if Path(audio_field.filename or "").suffix.lower() not in AUDIO_EXTENSIONS:
                raise SynchrobookError("Audio files must be MP3, WAV, or M4B", status=415, code="invalid_audio")
        audio_fields.sort(key=self._natural_filename_key)
        book_id, job_id, now = uuid.uuid4().hex, uuid.uuid4().hex, utc_now()
        book_dir = self._book_dir(book_id)
        try:
            book_source = book_dir / f"source{book_extension}"
            self._copy_upload(book_field, book_source, MAX_BOOK_BYTES)
            audio_manifest = []
            for index, audio_field in enumerate(audio_fields, 1):
                extension = Path(audio_field.filename).suffix.lower()
                relative = "source.m4b" if len(audio_fields) == 1 and extension == ".m4b" else f"audio-sources/part-{index:04d}{extension}"
                self._copy_upload(audio_field, book_dir / relative, MAX_M4B_BYTES)
                audio_manifest.append({
                    "path": relative,
                    "originalName": Path(audio_field.filename).name,
                    "title": Path(audio_field.filename).stem.strip() or f"Chapter {index}",
                })
            atomic_json(book_dir / "audio-sources.json", {"sources": audio_manifest})
            placeholder = Path(book_field.filename).stem.strip() or "Imported book"
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO books VALUES (?, ?, ?, NULL, ?, ?, NULL, '', NULL, ?, 'QUEUED', NULL)",
                    (book_id, placeholder, "Unknown author", book_source.name, "audio-sources.json", now),
                )
                connection.execute(
                    "INSERT INTO progress VALUES (?, 0, NULL, NULL, 1, 'desk', ?)", (book_id, now)
                )
                connection.execute(
                    """INSERT INTO jobs
                       (id, book_id, kind, status, stage, progress, message, error, created_at, updated_at, priority)
                       VALUES (?, ?, 'import', 'QUEUED', 'QUEUED', 0, ?, NULL, ?, ?, 0)""",
                    (job_id, book_id, "Import queued", now, now),
                )
        except Exception:
            if book_dir.exists():
                shutil.rmtree(book_dir, ignore_errors=True)
            raise
        self._logger.info("Queued import job %s for book %s", job_id, book_id)
        self._wake.set()
        return {"ok": True, "bookId": book_id, "jobId": job_id, "status": "QUEUED"}

    def list_books(self) -> dict:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM books ORDER BY imported_at DESC").fetchall()
            return {"books": [self._book_row(row) for row in rows]}

    def _book_row(self, row) -> dict:
        payload = dict(row)
        return {
            "id": payload["id"], "title": payload["title"], "author": payload["author"],
            "language": payload["language"], "duration": payload["duration"],
            "importedAt": payload["imported_at"], "processingState": payload["processing_state"],
            "error": payload["error"],
            "coverUrl": f"/api/synchrobook/books/{payload['id']}/cover" if payload["cover_file"] else None,
        }

    def get_book(self, book_id: str) -> dict:
        book_dir = self._book_dir(book_id)
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
            progress = connection.execute("SELECT * FROM progress WHERE book_id=?", (book_id,)).fetchone()
        if not row:
            raise SynchrobookError("Book not found", status=404, code="not_found")
        structure = {}
        structure_path = book_dir / "text" / "book.json"
        if structure_path.exists():
            structure = json.loads(structure_path.read_text(encoding="utf-8"))
        progress_payload = dict(progress) if progress else {}
        return {
            **self._book_row(row),
            "chapters": structure.get("chapters", []),
            "progress": {
                "timestamp": progress_payload.get("audio_timestamp", 0),
                "chapterId": progress_payload.get("chapter_id"),
                "sentenceId": progress_payload.get("sentence_id"),
                "playbackSpeed": progress_payload.get("playback_speed", 1),
                "readingMode": progress_payload.get("reading_mode", "desk"),
                "lastOpened": progress_payload.get("last_opened"),
            },
            "audioUrl": f"/api/synchrobook/books/{book_id}/audio" if row["playback_file"] else None,
        }

    def delete_book(self, book_id: str) -> dict:
        book_dir = self._book_dir(book_id)
        with self._connect() as connection:
            book_row = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
            book = dict(book_row) if book_row else None
            if not book:
                raise SynchrobookError("Book not found", status=404, code="not_found")
            active = connection.execute(
                "SELECT 1 FROM jobs WHERE book_id=? AND status IN ('QUEUED','BOOK_PROCESSING','EPUB_PROCESSING','AUDIO_PREPARING','AUDIO_MERGING','TRANSCRIBING','ALIGNING','FINALIZING')",
                (book_id,),
            ).fetchone()
            if active:
                raise SynchrobookError(
                    "Nie można usunąć książki podczas przetwarzania",
                    status=409,
                    code="job_active",
                )
        archive_dir = DATA_ROOT / "archive" / book_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        alignment_dir = book_dir / "alignment"
        archived_files = []
        for filename in ("alignment.json", "report.json"):
            source = alignment_dir / filename
            if source.is_file():
                shutil.copy2(source, archive_dir / filename)
                archived_files.append(filename)
        atomic_json(archive_dir / "metadata.json", {
            "id": book_id,
            "title": book["title"],
            "author": book["author"],
            "language": book["language"],
            "duration": book["duration"],
            "importedAt": book["imported_at"],
            "deletedAt": utc_now(),
            "files": archived_files,
        })
        with self._connect() as connection:
            deleted = connection.execute("DELETE FROM books WHERE id=?", (book_id,)).rowcount
            if not deleted:
                raise SynchrobookError("Book not found", status=404, code="not_found")
        files_pending = not self._remove_book_files(book_dir, attempts=4)
        if files_pending:
            threading.Thread(
                target=self._remove_book_files,
                args=(book_dir,),
                kwargs={"attempts": 60, "delay": 0.5},
                name=f"synchrobook-delete-{book_id[:8]}",
                daemon=True,
            ).start()
        self._logger.info("Deleted book %s", book_id)
        return {
            "ok": True,
            "deleted": book_id,
            "title": book["title"],
            "archived": f"archive/{book_id}",
            "filesPending": files_pending,
        }

    def _remove_book_files(self, book_dir: Path, *, attempts: int = 1, delay: float = 0.15) -> bool:
        for attempt in range(max(1, attempts)):
            if not book_dir.exists():
                return True
            try:
                shutil.rmtree(book_dir)
                return True
            except OSError as exc:
                if attempt + 1 >= attempts:
                    self._logger.warning("Book file cleanup pending for %s: %s", book_dir.name, exc)
                    return False
                time.sleep(delay)
        return not book_dir.exists()

    def get_job(self, job_id: str) -> dict:
        self._validate_id(job_id, "job identifier")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise SynchrobookError("Job not found", status=404, code="not_found")
        return self._job_row(row)

    @staticmethod
    def _job_row(row) -> dict:
        payload = dict(row)
        return {
            "id": payload["id"], "bookId": payload["book_id"], "kind": payload["kind"],
            "status": payload["status"], "stage": payload["stage"], "progress": payload["progress"],
            "message": payload["message"], "error": payload["error"],
            "priority": payload.get("priority", 0),
            "createdAt": payload["created_at"], "updatedAt": payload["updated_at"],
        }

    def list_jobs(self, limit: int = 30) -> dict:
        self.initialize()
        limit = max(1, min(100, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return {"jobs": [self._job_row(row) for row in rows]}

    @staticmethod
    def _processing_settings_path() -> Path:
        return DATA_ROOT / "processing-settings.json"

    def _read_processing_settings(self) -> dict:
        try:
            payload = json.loads(self._processing_settings_path().read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return {"highMemory": payload.get("highMemory") is True}

    @staticmethod
    def _transcription_threads(high_memory: bool) -> int:
        if not high_memory:
            return 1
        return max(2, min(4, max(1, (os.cpu_count() or 2) // 2)))

    def get_processing_settings(self) -> dict:
        self.initialize()
        settings = self._read_processing_settings()
        return {
            "ok": True,
            **settings,
            "transcriptionThreads": self._transcription_threads(settings["highMemory"]),
        }

    def save_processing_settings(self, payload: dict) -> dict:
        self.initialize()
        high_memory = payload.get("highMemory")
        if not isinstance(high_memory, bool):
            raise SynchrobookError(
                "highMemory must be true or false",
                code="invalid_processing_settings",
            )
        atomic_json(self._processing_settings_path(), {
            "version": 1,
            "highMemory": high_memory,
            "updatedAt": utc_now(),
        })
        self._logger.info("Synchrobook high-memory processing mode set to %s", high_memory)
        return self.get_processing_settings()

    def artifact(self, book_id: str, kind: str) -> dict:
        book_dir = self._book_dir(book_id)
        filename = "alignment.json" if kind == "alignment" else "report.json"
        path = book_dir / "alignment" / filename
        if not path.exists():
            raise SynchrobookError(f"{kind.title()} is not ready", status=409, code="not_ready")
        return json.loads(path.read_text(encoding="utf-8"))

    def media_file(self, book_id: str, kind: str) -> tuple[Path, str]:
        book_dir = self._book_dir(book_id)
        with self._connect() as connection:
            row = connection.execute("SELECT cover_file, playback_file FROM books WHERE id=?", (book_id,)).fetchone()
        if not row:
            raise SynchrobookError("Book not found", status=404, code="not_found")
        if kind == "audio":
            relative, mime = row["playback_file"], "audio/mp4"
        else:
            relative = row["cover_file"]
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
                Path(relative or "").suffix.lower(), "application/octet-stream"
            )
        path = book_dir / str(relative or "")
        if not relative or not path.is_file() or book_dir not in path.resolve().parents:
            raise SynchrobookError(f"Book {kind} is not available", status=404, code="not_found")
        return path, mime

    def save_progress(self, book_id: str, payload: dict) -> dict:
        self._book_dir(book_id)
        try:
            timestamp = max(0.0, float(payload.get("timestamp", 0)))
            speed = float(payload.get("playbackSpeed", 1))
        except (TypeError, ValueError) as exc:
            raise SynchrobookError("Invalid playback progress", code="invalid_progress") from exc
        if not math.isfinite(timestamp) or speed not in {0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0}:
            raise SynchrobookError("Invalid playback progress", code="invalid_progress")
        chapter_id = str(payload.get("chapterId") or "") or None
        sentence_id = str(payload.get("sentenceId") or "") or None
        mode = str(payload.get("readingMode") or "desk").lower()
        if mode not in {"desk", "relax", "bike"}:
            raise SynchrobookError("Invalid reading mode", code="invalid_reading_mode")
        now = utc_now()
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM books WHERE id=?", (book_id,)).fetchone()
            if not exists:
                raise SynchrobookError("Book not found", status=404, code="not_found")
            connection.execute(
                """INSERT INTO progress VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(book_id) DO UPDATE SET audio_timestamp=excluded.audio_timestamp,
                   chapter_id=excluded.chapter_id, sentence_id=excluded.sentence_id,
                   playback_speed=excluded.playback_speed, reading_mode=excluded.reading_mode,
                   last_opened=excluded.last_opened""",
                (book_id, timestamp, chapter_id, sentence_id, speed, mode, now),
            )
        return {"ok": True, "savedAt": now}

    def queue_action(self, book_id: str, kind: str) -> dict:
        self.start()
        if kind not in {"alignment", "transcription"}:
            raise SynchrobookError("Unsupported processing action")
        self._book_dir(book_id)
        now, job_id = utc_now(), uuid.uuid4().hex
        with self._connect() as connection:
            book = connection.execute("SELECT 1 FROM books WHERE id=?", (book_id,)).fetchone()
            if not book:
                raise SynchrobookError("Book not found", status=404, code="not_found")
            active = connection.execute(
                "SELECT 1 FROM jobs WHERE book_id=? AND status IN ('QUEUED','BOOK_PROCESSING','EPUB_PROCESSING','AUDIO_PREPARING','AUDIO_MERGING','TRANSCRIBING','ALIGNING','FINALIZING')",
                (book_id,),
            ).fetchone()
            if active:
                raise SynchrobookError("This book already has an active processing job", status=409, code="job_active")
            next_book_state = "READY" if self._has_readable_artifacts(book_id) else "QUEUED"
            connection.execute(
                "UPDATE books SET processing_state=?, error=NULL WHERE id=?",
                (next_book_state, book_id),
            )
            connection.execute(
                """INSERT INTO jobs
                   (id, book_id, kind, status, stage, progress, message, error, created_at, updated_at, priority)
                   VALUES (?, ?, ?, 'QUEUED', 'QUEUED', 0, ?, NULL, ?, ?, 0)""",
                (job_id, book_id, kind, f"{kind.title()} queued", now, now),
            )
        self._wake.set()
        return {"ok": True, "bookId": book_id, "jobId": job_id, "status": "QUEUED"}

    def _set_job(self, job_id: str, stage: str, progress: float | None, message: str, error: str | None = None) -> None:
        status = "ERROR" if error else stage
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute("SELECT book_id, kind FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return
            connection.execute(
                "UPDATE jobs SET status=?, stage=?, progress=?, message=?, error=?, updated_at=? WHERE id=?",
                (status, stage, progress, message, error, now, job_id),
            )
            keep_readable = row["kind"] != "import" and self._has_readable_artifacts(row["book_id"])
            book_status = "READY" if keep_readable else status
            connection.execute(
                "UPDATE books SET processing_state=?, error=? WHERE id=?",
                (book_status, error, row["book_id"]),
            )

    def resume_job(self, job_id: str, priority: int = 0) -> dict:
        self.start()
        self._validate_id(job_id, "job identifier")
        priority = max(-1000, min(1000, int(priority)))
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise SynchrobookError("Job not found", status=404, code="not_found")
            if row["status"] == "READY":
                raise SynchrobookError("Completed job cannot be resumed", status=409, code="job_ready")
            active = connection.execute(
                "SELECT 1 FROM jobs WHERE book_id=? AND id<>? AND status IN ('QUEUED','BOOK_PROCESSING','EPUB_PROCESSING','AUDIO_PREPARING','AUDIO_MERGING','TRANSCRIBING','ALIGNING','FINALIZING')",
                (row["book_id"], job_id),
            ).fetchone()
            if active:
                raise SynchrobookError("This book already has an active processing job", status=409, code="job_active")
            connection.execute(
                """UPDATE jobs SET status='QUEUED', stage='QUEUED',
                   message='W kolejce — zachowano ukończone etapy i checkpointy', error=NULL,
                   priority=?, updated_at=? WHERE id=?""",
                (priority, now, job_id),
            )
            next_book_state = (
                "READY"
                if row["kind"] != "import" and self._has_readable_artifacts(row["book_id"])
                else "QUEUED"
            )
            connection.execute(
                "UPDATE books SET processing_state=?, error=NULL WHERE id=?",
                (next_book_state, row["book_id"]),
            )
            queued = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        self._wake.set()
        return {"ok": True, "job": self._job_row(queued)}

    def _next_job(self):
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE status='QUEUED' ORDER BY priority DESC, created_at LIMIT 1"
            ).fetchone()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            row = self._next_job()
            if not row:
                self._wake.wait(2)
                self._wake.clear()
                continue
            job = dict(row)
            try:
                self._process(job)
            except Exception as exc:
                self._logger.exception("Job %s failed", job["id"])
                self._set_job(job["id"], "ERROR", None, "Processing failed", str(exc) or exc.__class__.__name__)
                if job["kind"] != "import" and (self._book_dir(job["book_id"]) / "alignment" / "alignment.json").exists():
                    with self._connect() as connection:
                        connection.execute(
                            "UPDATE books SET processing_state='READY', error=? WHERE id=?",
                            (f"Last {job['kind']} job failed: {exc}", job["book_id"]),
                        )

    def _select_pipeline(self) -> dict:
        health = voice_journal_health()
        engines = {row["id"]: row for row in health.get("engines", [])}
        cuda = bool((health.get("gpu") or {}).get("available"))
        faster = engines.get("faster-whisper") or {}
        openai = engines.get("openai-whisper") or {}
        if faster.get("available") and faster.get("cachedModels"):
            cached = faster["cachedModels"]
            model = "small" if "small" in cached else cached[0]
            return {"engine": "faster-whisper", "model": model, "device": "cuda" if cuda else "cpu", "computeType": "float16" if cuda else "int8"}
        if openai.get("available") and openai.get("cachedModels"):
            cached = openai["cachedModels"]
            model = "turbo" if "turbo" in cached else cached[0]
            return {"engine": "openai-whisper", "model": model, "device": "cuda" if cuda else "cpu", "computeType": "auto"}
        raise SynchrobookError(
            "No locally cached Whisper model is available; configure one in Voice Journal first",
            status=503, code="whisper_model_missing",
        )

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            except (AttributeError, OSError, ValueError):
                return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _read_worker_status(status_path: Path) -> dict:
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _load_pending_transcript(pending: Path, pipeline: dict) -> dict | None:
        try:
            payload = json.loads(pending.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("segments"), list)
            or payload.get("engine") != pipeline.get("engine")
            or payload.get("model") != pipeline.get("model")
        ):
            return None
        return payload

    def _wait_for_external_transcription(
        self, job_id: str, status_path: Path, pending: Path, pipeline: dict,
    ) -> dict | None:
        worker = self._read_worker_status(status_path)
        try:
            pid = int(worker.get("pid") or 0)
            age = max(0, time.time() - float(worker.get("updatedAt") or 0))
        except (TypeError, ValueError):
            return None
        active_stages = {"paused_for_user", "waiting_for_memory", "loading_model", "transcribing"}
        if worker.get("stage") not in active_stages or age > 30 * 60 or not self._pid_is_running(pid):
            return None
        self._logger.info("Waiting for existing transcription worker %s for job %s", pid, job_id)
        while self._pid_is_running(pid):
            if self._stop.wait(1):
                raise RuntimeError("Synchrobook processing stopped")
            worker = self._read_worker_status(status_path)
            progress = float(worker.get("progress") or 0)
            chunk_note = f" {worker.get('chunk')}/{worker.get('chunks')}" if worker.get("chunk") else ""
            self._set_job(
                job_id, "TRANSCRIBING", 25 + progress * 0.5,
                f"Kontynuowanie istniejącej transkrypcji{chunk_note}",
            )
        return self._load_pending_transcript(pending, pipeline)

    def _transcribe(self, job_id: str, book_dir: Path, language: str) -> dict:
        transcript_dir = book_dir / "transcription"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = transcript_dir / "transcript.json"
        chunks = prepare_analysis_chunks(book_dir / "source.m4b", book_dir / "audio" / "analysis")
        manifest_path = transcript_dir / "chunks.json"
        atomic_json(manifest_path, {"chunks": [
            {"path": str(path.resolve()), "offset": index * ANALYSIS_CHUNK_SECONDS}
            for index, path in enumerate(chunks)
        ]})
        pipeline = self._select_pipeline()
        pending = transcript_dir / "transcript.pending.json"
        status_path = transcript_dir / "worker-status.json"
        resumed_transcript = self._wait_for_external_transcription(
            job_id, status_path, pending, pipeline,
        ) or self._load_pending_transcript(pending, pipeline)
        if resumed_transcript is not None:
            os.replace(pending, transcript_path)
            return resumed_transcript
        command = [
            sys.executable, str(ROOT / "scripts" / "synchrobook_transcribe_worker.py"),
            "--manifest", str(manifest_path), "--output", str(pending), "--status", str(status_path),
            "--engine", pipeline["engine"], "--model", pipeline["model"], "--device", pipeline["device"],
            "--compute-type", pipeline["computeType"], "--language", language or "auto",
            "--resource-settings", str(self._processing_settings_path()),
        ]
        processing_settings = self._read_processing_settings()
        worker_environment = os.environ.copy()
        worker_environment["SYNCHROBOOK_TRANSCRIBE_THREADS"] = str(
            self._transcription_threads(processing_settings["highMemory"])
        )
        self._logger.info("Starting %s/%s on %s for job %s", pipeline["engine"], pipeline["model"], pipeline["device"], job_id)
        self._active_process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=worker_environment,
        )
        while self._active_process.poll() is None:
            if self._stop.wait(1):
                self._active_process.terminate()
                raise RuntimeError("Synchrobook processing stopped")
            if status_path.exists():
                try:
                    worker = json.loads(status_path.read_text(encoding="utf-8"))
                    worker_progress = float(worker.get("progress") or 0)
                    chunk_note = f" chunk {worker.get('chunk')}/{worker.get('chunks')}" if worker.get("chunk") else ""
                    resume_note = " (saved)" if worker.get("resumed") else ""
                    if worker.get("stage") == "paused_for_user":
                        idle_target = int(worker.get("resumeAfterIdleSeconds") or 120)
                        message = f"Paused while computer is in use — resumes after {idle_target}s idle"
                    elif worker.get("stage") == "waiting_for_memory":
                        free_mb = int(worker.get("availableCommitMb") or 0)
                        message = f"Waiting for free memory ({free_mb} MB available)"
                    else:
                        message = f"Transcribing audiobook{chunk_note}{resume_note}"
                    self._set_job(job_id, "TRANSCRIBING", 25 + worker_progress * 0.5, message)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
        return_code = self._active_process.returncode
        self._active_process = None
        if return_code or not pending.exists():
            detail = "Whisper worker failed"
            if status_path.exists():
                try:
                    detail = json.loads(status_path.read_text(encoding="utf-8")).get("error") or detail
                except Exception:
                    pass
            raise RuntimeError(detail)
        os.replace(pending, transcript_path)
        return json.loads(transcript_path.read_text(encoding="utf-8"))

    def _process(self, job: dict) -> None:
        job_id, book_id, kind = job["id"], job["book_id"], job["kind"]
        book_dir = self._book_dir(book_id)
        text_path = book_dir / "text" / "book.json"
        audio_metadata_path = book_dir / "audio" / "metadata.json"
        transcript_path = book_dir / "transcription" / "transcript.json"
        with self._connect() as connection:
            source_row = connection.execute(
                "SELECT epub_file, audiobook_file FROM books WHERE id=?", (book_id,)
            ).fetchone()
        if not source_row:
            raise SynchrobookError("Book not found", status=404, code="not_found")
        book_source = book_dir / source_row["epub_file"]
        cached_book = None
        if text_path.exists():
            try:
                cached_book = json.loads(text_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached_book = None
        if not cached_book or int(cached_book.get("extractionVersion") or 0) < 4:
            format_name = book_source.suffix.lstrip(".").upper()
            self._set_job(job_id, "BOOK_PROCESSING", 4, f"Czytanie {format_name} i wykrywanie rozdziałów")
            book = extract_book(book_source, book_dir / "text")
        else:
            book = cached_book
        if not audio_metadata_path.exists() or not (book_dir / "source.m4b").exists():
            manifest_path = book_dir / source_row["audiobook_file"]
            if manifest_path.suffix.lower() == ".json":
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                sources = [{**row, "path": book_dir / row["path"]} for row in manifest.get("sources", [])]
            else:
                sources = [{"path": manifest_path, "title": manifest_path.stem, "originalName": manifest_path.name}]
            self._set_job(job_id, "AUDIO_PREPARING", 12, f"Sprawdzanie {len(sources)} plików audio")
            def audio_progress(completed: int, total: int, message: str) -> None:
                # Probing and conversion are two separate passes. Keep their
                # progress ranges disjoint so the queue never appears to move
                # backwards when conversion starts.
                if message.startswith("Sprawdzanie"):
                    percent = 12 + (2 * completed / max(1, total))
                else:
                    percent = 14 + (8 * completed / max(1, total))
                stage = "AUDIO_MERGING" if len(sources) > 1 or Path(sources[0]["path"]).suffix.lower() != ".m4b" else "AUDIO_PREPARING"
                self._set_job(job_id, stage, round(percent, 2), message)
            audio = prepare_audiobook(
                sources, book_dir / "source.m4b", book_dir / "audio" / "assembly",
                progress_callback=audio_progress,
            )
            atomic_json(audio_metadata_path, audio)
            self._set_job(job_id, "AUDIO_PREPARING", 23, "Przygotowanie audio do odtwarzania")
            prepare_playback(book_dir / "source.m4b", book_dir / "audio" / "playback.m4a", audio.get("codec"))
        else:
            audio = json.loads(audio_metadata_path.read_text(encoding="utf-8"))
            prepare_playback(book_dir / "source.m4b", book_dir / "audio" / "playback.m4a", audio.get("codec"))
        should_transcribe = kind == "transcription" or not transcript_path.exists()
        if should_transcribe:
            self._set_job(job_id, "TRANSCRIBING", 25, "Preparing chunked audio for Whisper")
            language = book.get("language") or audio.get("language") or "auto"
            language = str(language).replace("_", "-").split("-", 1)[0].lower()
            transcript = self._transcribe(job_id, book_dir, language)
        else:
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        book = repair_fragmented_words(book, transcript, book_dir / "text")
        self._set_job(job_id, "ALIGNING", 80, "Dopasowywanie transkrypcji do tekstu książki")
        def alignment_progress(processed: int, total: int) -> None:
            percent = 80 + (15 * processed / max(1, total))
            self._set_job(
                job_id, "ALIGNING", round(percent, 2),
                f"Dopasowywanie zdań książki ({processed}/{total})",
            )

        alignment, report = build_alignment(
            book_id, book, transcript, audio.get("chapters") or [],
            progress_callback=alignment_progress,
        )
        atomic_json(book_dir / "alignment" / "alignment.json", alignment)
        atomic_json(book_dir / "alignment" / "report.json", report)
        self._set_job(job_id, "FINALIZING", 96, "Finalizing library metadata")
        title = book.get("title") if book.get("title") != "Unknown title" else audio.get("title") or "Unknown title"
        author = book.get("author") if book.get("author") != "Unknown author" else audio.get("author") or "Unknown author"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE books SET title=?, author=?, cover_file=?, playback_file=?, language=?, duration=?,
                   processing_state='READY', error=NULL WHERE id=?""",
                (title, author, f"text/{book['coverFile']}" if book.get("coverFile") else None, "audio/playback.m4a", book.get("language") or audio.get("language"), audio["duration"], book_id),
            )
            connection.execute(
                "UPDATE jobs SET status='READY', stage='READY', progress=100, message='Ready', error=NULL, updated_at=? WHERE id=?",
                (now, job_id),
            )
        self._logger.info("Completed job %s for book %s", job_id, book_id)


SYNCHROBOOK = SynchrobookService()
