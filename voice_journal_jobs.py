"""Persistent single-worker queue for local Whisper transcription jobs."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from voice_journal import (
    VoiceJournalError,
    _whisper_module,
    _validate_options,
    parse_multipart_form,
    probe_audio,
    resolve_device,
    validate_audio_part,
)
from voice_journal_eta import estimate_eta, unavailable_eta
from voice_journal_options import (
    TranscriptionOptionsError,
    supported_transcription_option_names,
    validate_transcription_options,
)
from voice_journal_engines import (
    DEFAULT_ENGINE,
    FASTER_ENGINE,
    FASTER_MODELS,
    OPENAI_ENGINE,
    faster_whisper_health,
    normalize_engine,
    validate_faster_options,
)


ACTIVE_STATUSES = {"queued", "running", "cancelling"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class VoiceJournalJobManager:
    def __init__(
        self,
        db_path: Path,
        job_dir: Path,
        root: Path,
        *,
        worker_script: Path | None = None,
        process_factory=None,
        poll_interval: float = 0.2,
    ):
        self.db_path = Path(db_path).resolve()
        self.job_dir = Path(job_dir).resolve()
        self.root = Path(root).resolve()
        self.worker_script = Path(worker_script or (self.root / "scripts" / "voice_journal_worker.py")).resolve()
        self.process_factory = process_factory or self._default_process_factory
        self.poll_interval = poll_interval
        self._init_lock = threading.Lock()
        self._initialized = False
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._active_process = None
        self._active_job_id = None
        self._active_lock = threading.Lock()

    @staticmethod
    def _default_process_factory(command):
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.job_dir.mkdir(parents=True, exist_ok=True)
            interrupted_paths = []
            now = utc_now()
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS voice_journal_jobs (
                        id TEXT PRIMARY KEY,
                        engine TEXT NOT NULL DEFAULT 'openai-whisper',
                        status TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        model TEXT NOT NULL,
                        language TEXT NOT NULL,
                        task TEXT NOT NULL,
                        device TEXT NOT NULL,
                        compute_type TEXT NOT NULL DEFAULT 'auto',
                        options_json TEXT NOT NULL DEFAULT '{}',
                        allow_model_download INTEGER NOT NULL DEFAULT 0,
                        original_filename TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        duration_seconds REAL,
                        format TEXT,
                        codec TEXT,
                        sample_rate INTEGER,
                        channels INTEGER,
                        temp_audio_path TEXT NOT NULL,
                        result_json TEXT,
                        error TEXT,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        processed_audio_seconds REAL,
                        progress_percent REAL,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        transcription_started_at TEXT,
                        completed_at TEXT,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_voice_journal_jobs_queue
                    ON voice_journal_jobs(status, created_at);
                    CREATE TABLE IF NOT EXISTS voice_journal_performance (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL,
                        engine TEXT NOT NULL DEFAULT 'openai-whisper',
                        model TEXT NOT NULL,
                        device TEXT NOT NULL,
                        audio_duration_seconds REAL NOT NULL,
                        transcription_duration_seconds REAL NOT NULL,
                        real_time_factor REAL NOT NULL,
                        completed_at TEXT NOT NULL
                    );
                    """
                )
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(voice_journal_jobs)").fetchall()
                }
                if "transcription_started_at" not in columns:
                    connection.execute("ALTER TABLE voice_journal_jobs ADD COLUMN transcription_started_at TEXT")
                if "options_json" not in columns:
                    connection.execute("ALTER TABLE voice_journal_jobs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'")
                if "allow_model_download" not in columns:
                    connection.execute("ALTER TABLE voice_journal_jobs ADD COLUMN allow_model_download INTEGER NOT NULL DEFAULT 0")
                if "engine" not in columns:
                    connection.execute("ALTER TABLE voice_journal_jobs ADD COLUMN engine TEXT NOT NULL DEFAULT 'openai-whisper'")
                if "compute_type" not in columns:
                    connection.execute("ALTER TABLE voice_journal_jobs ADD COLUMN compute_type TEXT NOT NULL DEFAULT 'auto'")
                performance_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(voice_journal_performance)").fetchall()
                }
                if "engine" not in performance_columns:
                    connection.execute("ALTER TABLE voice_journal_performance ADD COLUMN engine TEXT NOT NULL DEFAULT 'openai-whisper'")
                rows = connection.execute(
                    "SELECT temp_audio_path FROM voice_journal_jobs WHERE status IN ('queued', 'running', 'cancelling')"
                ).fetchall()
                interrupted_paths = [row["temp_audio_path"] for row in rows]
                connection.execute(
                    """
                    UPDATE voice_journal_jobs
                    SET status = 'interrupted', stage = 'interrupted',
                        error = 'Backend restarted before the job completed',
                        completed_at = ?, updated_at = ?, progress_percent = NULL
                    WHERE status IN ('queued', 'running', 'cancelling')
                    """,
                    (now, now),
                )
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version < 5:
                    connection.execute("PRAGMA user_version = 5")
            for raw_path in interrupted_paths:
                self._cleanup_job_files(Path(raw_path))
            self._initialized = True

    def start(self):
        self.initialize()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="voice-journal-queue", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5):
        self._stop.set()
        self._wake.set()
        with self._active_lock:
            process = self._active_process
        if process and process.poll() is None:
            process.terminate()
        if self._thread:
            self._thread.join(timeout=timeout)

    def submit(self, content_type: str, body: bytes) -> dict:
        self.start()
        audio_part, fields = parse_multipart_form(
            content_type,
            body,
            allowed_fields={"engine", "model", "language", "task", "device", "computeType", "options", "allowModelDownload"},
            max_field_bytes=16 * 1024,
        )
        suffix = validate_audio_part(audio_part)
        try:
            engine = normalize_engine(fields.get("engine"))
        except ValueError as exc:
            raise VoiceJournalError(str(exc), code="unsupported_engine") from exc
        model, language_code, task, requested_device = _validate_options({
            **fields,
            "model": fields.get("model") if engine == OPENAI_ENGINE else "small",
        })
        if engine == FASTER_ENGINE:
            model = str(fields.get("model") or "").lower()
            faster_status = faster_whisper_health()
            if not faster_status["available"]:
                raise VoiceJournalError(faster_status["error"], status=503, code="engine_unavailable")
            if model not in faster_status["supportedModels"]:
                raise VoiceJournalError("Unsupported Faster-Whisper model", code="unsupported_model")
        language = language_code or "auto"
        device = resolve_device(requested_device)
        download_value = (fields.get("allowModelDownload") or "false").lower()
        if download_value not in {"true", "false"}:
            raise VoiceJournalError(
                "allowModelDownload must be true or false",
                code="invalid_model_download_confirmation",
            )
        allow_model_download = download_value == "true"
        try:
            raw_options = json.loads(fields.get("options") or "{}")
            if engine == FASTER_ENGINE:
                transcription_options, compute_type = validate_faster_options(
                    raw_options, device=device, compute_type=fields.get("computeType")
                )
            else:
                transcription_options = validate_transcription_options(
                    raw_options,
                    supported_names=supported_transcription_option_names(_whisper_module()),
                    device=device,
                )
                compute_type = "auto"
        except (json.JSONDecodeError, TranscriptionOptionsError, ValueError) as exc:
            raise VoiceJournalError(
                str(exc) or "Invalid transcription options",
                code="invalid_transcription_options",
            ) from exc
        job_id = uuid.uuid4().hex
        audio_path = (self.job_dir / f"{job_id}{suffix}").resolve()
        if audio_path.parent != self.job_dir:
            raise VoiceJournalError("Unsafe job audio path", status=500)
        audio_path.write_bytes(audio_part["content"])
        now = utc_now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO voice_journal_jobs (
                        id, status, stage, engine, model, language, task, device, compute_type, options_json, allow_model_download,
                        original_filename, mime_type, size_bytes, temp_audio_path,
                        created_at, updated_at
                    ) VALUES (?, 'queued', 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id, engine, model, language, task, device, compute_type,
                        json.dumps(transcription_options, ensure_ascii=False),
                        int(allow_model_download),
                        audio_part["filename"], audio_part["mime"], len(audio_part["content"]),
                        str(audio_path), now, now,
                    ),
                )
        except Exception:
            audio_path.unlink(missing_ok=True)
            raise
        self._wake.set()
        return self.get(job_id)

    def _row(self, job_id: str):
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM voice_journal_jobs WHERE id = ?", (str(job_id),)).fetchone()
        if row is None:
            raise VoiceJournalError("Transcription job not found", status=404, code="job_not_found")
        return row

    def get(self, job_id: str) -> dict:
        row = self._row(job_id)
        status = row["status"]
        now = datetime.now(timezone.utc)
        started = parse_utc(row["started_at"]) or parse_utc(row["created_at"])
        finished = parse_utc(row["completed_at"]) if status in TERMINAL_STATUSES else now
        elapsed = max(0.0, (finished - started).total_seconds()) if started and finished else 0.0
        queue_position = None
        if status == "queued":
            with self._connect() as connection:
                queue_position = int(connection.execute(
                    """
                    SELECT COUNT(*) FROM voice_journal_jobs
                    WHERE status = 'queued'
                      AND (created_at < ? OR (created_at = ? AND id <= ?))
                    """,
                    (row["created_at"], row["created_at"], row["id"]),
                ).fetchone()[0])
        elif status in {"running", "cancelling"}:
            queue_position = 0
        if status in TERMINAL_STATUSES:
            eta = unavailable_eta(status)
        else:
            transcription_started = parse_utc(row["transcription_started_at"])
            transcription_elapsed = max(0.0, (now - transcription_started).total_seconds()) if transcription_started else 0.0
            eta = estimate_eta(
                duration_seconds=row["duration_seconds"],
                historical_rtfs=self._similar_rtfs(row),
                transcription_elapsed_seconds=transcription_elapsed,
                processed_audio_seconds=row["processed_audio_seconds"],
            )
            eta.pop("basisRtf", None)
        return {
            "id": row["id"],
            "status": status,
            "stage": row["stage"],
            "elapsedSeconds": round(elapsed, 1),
            "queuePosition": queue_position,
            "engine": row["engine"],
            "model": row["model"],
            "device": row["device"],
            "computeType": row["compute_type"],
            "transcriptionOptions": json.loads(row["options_json"] or "{}"),
            "allowModelDownload": bool(row["allow_model_download"]),
            "processedAudioSeconds": row["processed_audio_seconds"],
            "progressPercent": row["progress_percent"],
            "eta": eta,
            "error": row["error"],
            "cancelRequested": bool(row["cancel_requested"]),
            "createdAt": row["created_at"],
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
        }

    def cancel(self, job_id: str) -> dict:
        row = self._row(job_id)
        if row["status"] in TERMINAL_STATUSES:
            return self.get(job_id)
        now = utc_now()
        if row["status"] == "queued":
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE voice_journal_jobs
                    SET status = 'cancelled', stage = 'cancelled', cancel_requested = 1,
                        completed_at = ?, updated_at = ? WHERE id = ? AND status = 'queued'
                    """,
                    (now, now, job_id),
                )
            self._cleanup_job_files(Path(row["temp_audio_path"]))
        else:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE voice_journal_jobs
                    SET status = 'cancelling', stage = 'cancelling', cancel_requested = 1,
                        updated_at = ? WHERE id = ?
                    """,
                    (now, job_id),
                )
        self._wake.set()
        return self.get(job_id)

    def result(self, job_id: str) -> dict:
        row = self._row(job_id)
        if row["status"] != "completed":
            raise VoiceJournalError(
                f"Job result is not available while status is {row['status']}",
                status=409,
                code="result_not_ready",
            )
        try:
            return json.loads(row["result_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise VoiceJournalError("Stored job result is invalid", status=500) from exc

    def _worker_loop(self):
        while not self._stop.is_set():
            row = self._next_queued()
            if row is None:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            try:
                self._execute(row)
            except Exception as exc:
                self._mark_failed(row["id"], str(exc) or exc.__class__.__name__)
                self._cleanup_job_files(Path(row["temp_audio_path"]))

    def _next_queued(self):
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM voice_journal_jobs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"
            ).fetchone()

    def _update_stage(self, job_id: str, stage: str):
        with self._connect() as connection:
            now = utc_now()
            if stage == "transcribing":
                connection.execute(
                    """
                    UPDATE voice_journal_jobs SET stage = ?, updated_at = ?,
                        transcription_started_at = COALESCE(transcription_started_at, ?)
                    WHERE id = ? AND status = 'running'
                    """,
                    (stage, now, now, job_id),
                )
            else:
                connection.execute(
                    "UPDATE voice_journal_jobs SET stage = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                    (stage, now, job_id),
                )

    def _similar_rtfs(self, row) -> list[float]:
        duration = float(row["duration_seconds"] or 0)
        if duration <= 0:
            return []
        with self._connect() as connection:
            measurements = connection.execute(
                """
                SELECT audio_duration_seconds, transcription_duration_seconds, real_time_factor
                FROM voice_journal_performance
                WHERE engine = ? AND model = ? AND device = ?
                ORDER BY completed_at DESC LIMIT 100
                """,
                (row["engine"], row["model"], row["device"]),
            ).fetchall()
        comparable = []
        for measurement in measurements:
            measured_duration = float(measurement["audio_duration_seconds"] or 0)
            transcription_duration = float(measurement["transcription_duration_seconds"] or 0)
            stored_rtf = float(measurement["real_time_factor"] or 0)
            if measured_duration <= 0 or transcription_duration <= 0 or stored_rtf <= 0:
                continue
            calculated_rtf = transcription_duration / measured_duration
            measured_rtf = statistics.median((stored_rtf, calculated_rtf))
            ratio = measured_duration / duration
            if 0.25 <= ratio <= 4:
                comparable.append((abs(math.log(ratio)), measured_rtf))
        comparable.sort(key=lambda item: item[0])
        return [rtf for _, rtf in comparable[:20]]

    def _execute(self, row):
        job_id = row["id"]
        audio_path = Path(row["temp_audio_path"]).resolve()
        status_path = self.job_dir / f"{job_id}.status.json"
        result_path = self.job_dir / f"{job_id}.result.json"
        options_path = self.job_dir / f"{job_id}.options.json"
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE voice_journal_jobs SET status = 'running', stage = 'validating',
                    started_at = ?, updated_at = ?
                WHERE id = ? AND status = 'queued' AND cancel_requested = 0
                """,
                (now, now, job_id),
            )
        if cursor.rowcount == 0:
            return

        metadata = probe_audio(audio_path)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE voice_journal_jobs SET duration_seconds = ?, format = ?, codec = ?,
                    sample_rate = ?, channels = ?, stage = 'loading_model', updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    metadata["durationSeconds"], metadata["format"], metadata["codec"],
                    metadata["sampleRate"], metadata["channels"], utc_now(), job_id,
                ),
            )

        if self._row(job_id)["cancel_requested"]:
            self._mark_cancelled(job_id)
            self._cleanup_job_files(audio_path)
            return

        options_path.write_text(row["options_json"] or "{}", encoding="utf-8")

        command = [
            sys.executable,
            str(self.worker_script),
            "--audio", str(audio_path),
            "--engine", row["engine"],
            "--model", row["model"],
            "--language", row["language"],
            "--task", row["task"],
            "--device", row["device"],
            "--compute-type", row["compute_type"],
            "--allow-model-download", "true" if row["allow_model_download"] else "false",
            "--options-file", str(options_path),
            "--status-file", str(status_path),
            "--result-file", str(result_path),
        ]
        process = self.process_factory(command)
        with self._active_lock:
            self._active_process = process
            self._active_job_id = job_id
        last_stage = "loading_model"
        cancelled = False
        try:
            while process.poll() is None:
                current = self._row(job_id)
                if current["cancel_requested"]:
                    cancelled = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    break
                if status_path.is_file():
                    try:
                        stage = json.loads(status_path.read_text(encoding="utf-8")).get("stage")
                    except (OSError, json.JSONDecodeError):
                        stage = None
                    if stage in {"loading_model", "transcribing"} and stage != last_stage:
                        self._update_stage(job_id, stage)
                        last_stage = stage
                time.sleep(self.poll_interval)
        finally:
            with self._active_lock:
                self._active_process = None
                self._active_job_id = None

        if cancelled:
            self._cleanup_job_files(audio_path)
            self._mark_cancelled(job_id)
            return

        # Preserve an in-flight row for startup recovery. initialize() will mark
        # it as interrupted and remove its temporary files after a restart.
        if self._stop.is_set():
            return

        if not result_path.is_file():
            raise RuntimeError("Whisper worker exited without a result")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if process.poll() != 0 or not result.get("ok"):
            raise RuntimeError(result.get("error") or "Whisper worker failed")

        duration = float(metadata["durationSeconds"])
        transcription_duration = float(result["transcriptionDurationSeconds"])
        real_time_factor = transcription_duration / duration
        response = {
            "transcript": str(result.get("transcript") or ""),
            "transcriptSegments": result.get("transcriptSegments")
            if isinstance(result.get("transcriptSegments"), list) else [],
            "transcriptionData": {
                "version": 1,
                "engine": row["engine"],
                "segments": result.get("transcriptionDataSegments")
                if isinstance(result.get("transcriptionDataSegments"), list) else (
                    result.get("transcriptSegments") if isinstance(result.get("transcriptSegments"), list) else []
                ),
                "engineMetadata": result.get("engineMetadata")
                if isinstance(result.get("engineMetadata"), dict) else {},
            },
            **metadata,
            "sizeBytes": int(row["size_bytes"]),
            "model": row["model"],
            "engine": row["engine"],
            "device": row["device"],
            "computeType": row["compute_type"],
            "transcriptionDurationSeconds": round(transcription_duration, 3),
            "realTimeFactor": round(real_time_factor, 4),
        }
        finished = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE voice_journal_jobs SET status = 'completed', stage = 'completed',
                    result_json = ?, processed_audio_seconds = ?, progress_percent = 100,
                    completed_at = ?, updated_at = ? WHERE id = ?
                """,
                (json.dumps(response, ensure_ascii=False), duration, finished, finished, job_id),
            )
            connection.execute(
                """
                INSERT INTO voice_journal_performance (
                    job_id, engine, model, device, audio_duration_seconds,
                    transcription_duration_seconds, real_time_factor, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, row["engine"], row["model"], row["device"], duration,
                    transcription_duration, real_time_factor, finished,
                ),
            )
        self._cleanup_job_files(audio_path)

    def _mark_failed(self, job_id: str, error: str):
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE voice_journal_jobs SET status = 'failed', stage = 'failed',
                    error = ?, completed_at = ?, updated_at = ?, progress_percent = NULL
                WHERE id = ? AND status NOT IN ('completed', 'cancelled', 'interrupted')
                """,
                (str(error)[:1000], now, now, job_id),
            )

    def _mark_cancelled(self, job_id: str):
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE voice_journal_jobs SET status = 'cancelled', stage = 'cancelled',
                    cancel_requested = 1, completed_at = ?, updated_at = ?, progress_percent = NULL
                WHERE id = ? AND status NOT IN ('completed', 'failed', 'cancelled', 'interrupted')
                """,
                (now, now, job_id),
            )

    def _cleanup_job_files(self, audio_path: Path):
        candidates = [audio_path]
        stem = audio_path.stem
        candidates.extend([
            self.job_dir / f"{stem}.status.json",
            self.job_dir / f"{stem}.status.json.tmp",
            self.job_dir / f"{stem}.result.json",
            self.job_dir / f"{stem}.result.json.tmp",
            self.job_dir / f"{stem}.options.json",
        ])
        for candidate in candidates:
            try:
                resolved = Path(candidate).resolve()
                if resolved.parent == self.job_dir:
                    resolved.unlink(missing_ok=True)
            except OSError:
                pass


PROJECT_ROOT = Path(__file__).resolve().parent
VOICE_JOURNAL_JOBS = VoiceJournalJobManager(
    PROJECT_ROOT / "data" / "voice-journal.sqlite",
    PROJECT_ROOT / "data" / "raw" / "voice-journal" / "jobs",
    PROJECT_ROOT,
)


__all__ = ["VoiceJournalJobManager", "VOICE_JOURNAL_JOBS"]
