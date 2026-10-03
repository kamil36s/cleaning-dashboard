"""SQLite metadata and local audio storage for voice journal entries."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from voice_journal import (
    MAX_MULTIPART_BYTES,
    SUPPORTED_MODELS,
    VoiceJournalError,
    parse_multipart_form,
    probe_audio,
    validate_audio_part,
)
from voice_journal_engines import DEFAULT_ENGINE, FASTER_ENGINE, FASTER_MODELS, OPENAI_ENGINE


ENTRY_CATEGORIES = {"morning", "evening", "spontaneous", "after-event"}
DATE_SOURCES = {"file_modified", "user_corrected", "upload_time"}
MUTABLE_FIELDS = {
    "title", "entryCategory", "recordedAt", "tags", "transcript",
    "transcriptionData", "correctionHistory", "correctionSettings",
}
MAX_ENTRY_JSON_BYTES = 8 * 1024 * 1024
MAX_TRANSCRIPT_SEGMENTS = 20_000
MAX_CORRECTION_JSON_BYTES = 8 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_iso_datetime(value, field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise VoiceJournalError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VoiceJournalError(f"{field_name} must be an ISO date-time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_text(value, *, field_name: str, max_length: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise VoiceJournalError(f"{field_name} is required")
    if len(text) > max_length:
        raise VoiceJournalError(f"{field_name} is too long")
    return text


def normalize_tags(value) -> list[str]:
    if not isinstance(value, list):
        raise VoiceJournalError("tags must be an array")
    tags = []
    for item in value:
        tag = normalize_text(item, field_name="tag", max_length=40)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 12:
            break
    return tags


def normalize_transcript_segments(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise VoiceJournalError("transcriptSegments must be an array")
    if len(value) > MAX_TRANSCRIPT_SEGMENTS:
        raise VoiceJournalError("transcriptSegments is too long")
    segments = []
    for item in value:
        if not isinstance(item, dict):
            raise VoiceJournalError("Invalid transcript segment")
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError) as exc:
            raise VoiceJournalError("Invalid transcript segment timestamp") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise VoiceJournalError("Invalid transcript segment timestamp")
        text = normalize_text(item.get("text"), field_name="segment text", max_length=10_000)
        if text:
            normalized = dict(item)
            normalized.update({"start": round(start, 3), "end": round(end, 3), "text": text})
            segments.append(normalized)
    return segments


def normalize_json_document(value, field_name: str, *, expected_type, default):
    if value is None:
        return default
    if not isinstance(value, expected_type):
        raise VoiceJournalError(f"{field_name} has an invalid type")
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise VoiceJournalError(f"{field_name} must contain valid JSON data") from exc
    if len(encoded.encode("utf-8")) > MAX_CORRECTION_JSON_BYTES:
        raise VoiceJournalError(f"{field_name} is too large", status=413, code="payload_too_large")
    return value


def parse_create_entry_request(content_type: str, body: bytes) -> tuple[dict, dict]:
    audio_part, fields = parse_multipart_form(
        content_type,
        body,
        allowed_fields={"entry"},
        max_field_bytes=MAX_ENTRY_JSON_BYTES,
    )
    try:
        entry = json.loads(fields.get("entry") or "")
    except json.JSONDecodeError as exc:
        raise VoiceJournalError("entry must contain valid JSON") from exc
    if not isinstance(entry, dict):
        raise VoiceJournalError("entry must be a JSON object")
    return audio_part, entry


class VoiceJournalStore:
    def __init__(self, db_path: Path, audio_dir: Path, root: Path):
        self.db_path = Path(db_path).resolve()
        self.audio_dir = Path(audio_dir).resolve()
        self.root = Path(root).resolve()
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.audio_dir.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS voice_journal_entries (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL DEFAULT '',
                        entry_category TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        uploaded_at TEXT NOT NULL,
                        date_source TEXT NOT NULL,
                        original_filename TEXT NOT NULL,
                        stored_filename TEXT NOT NULL UNIQUE,
                        mime_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        duration_seconds REAL NOT NULL,
                        audio_path TEXT NOT NULL,
                        transcript TEXT NOT NULL DEFAULT '',
                        raw_transcript TEXT NOT NULL DEFAULT '',
                        transcript_segments_json TEXT NOT NULL DEFAULT '[]',
                        engine TEXT NOT NULL DEFAULT 'openai-whisper',
                        transcription_data_json TEXT NOT NULL DEFAULT '{}',
                        correction_history_json TEXT NOT NULL DEFAULT '[]',
                        correction_settings_json TEXT NOT NULL DEFAULT '{}',
                        tags_json TEXT NOT NULL DEFAULT '[]',
                        language TEXT NOT NULL,
                        model TEXT NOT NULL,
                        device TEXT NOT NULL,
                        transcription_duration_seconds REAL NOT NULL,
                        real_time_factor REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_voice_journal_recorded_at
                    ON voice_journal_entries(recorded_at DESC, created_at DESC);
                    """
                )
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(voice_journal_entries)")
                }
                if "raw_transcript" not in columns:
                    connection.execute(
                        "ALTER TABLE voice_journal_entries ADD COLUMN raw_transcript TEXT NOT NULL DEFAULT ''"
                    )
                if "transcript_segments_json" not in columns:
                    connection.execute(
                        "ALTER TABLE voice_journal_entries ADD COLUMN transcript_segments_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if "engine" not in columns:
                    connection.execute("ALTER TABLE voice_journal_entries ADD COLUMN engine TEXT NOT NULL DEFAULT 'openai-whisper'")
                if "transcription_data_json" not in columns:
                    connection.execute("ALTER TABLE voice_journal_entries ADD COLUMN transcription_data_json TEXT NOT NULL DEFAULT '{}'")
                if "correction_history_json" not in columns:
                    connection.execute("ALTER TABLE voice_journal_entries ADD COLUMN correction_history_json TEXT NOT NULL DEFAULT '[]'")
                if "correction_settings_json" not in columns:
                    connection.execute("ALTER TABLE voice_journal_entries ADD COLUMN correction_settings_json TEXT NOT NULL DEFAULT '{}'")
                connection.execute(
                    "UPDATE voice_journal_entries SET raw_transcript = transcript WHERE raw_transcript = ''"
                )
                if version < 2:
                    connection.execute("PRAGMA user_version = 2")
            self._initialized = True

    def _audio_relative_path(self, stored_filename: str) -> str:
        path = (self.audio_dir / stored_filename).resolve()
        if path.parent != self.audio_dir:
            raise VoiceJournalError("Unsafe audio storage path", status=500, code="unsafe_audio_path")
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise VoiceJournalError("Audio directory must be inside the project root", status=500) from exc

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict:
        entry_id = row["id"]
        return {
            "id": entry_id,
            "title": row["title"],
            "entryCategory": row["entry_category"],
            "recordedAt": row["recorded_at"],
            "uploadedAt": row["uploaded_at"],
            "dateSource": row["date_source"],
            "originalFilename": row["original_filename"],
            "storedFilename": row["stored_filename"],
            "mimeType": row["mime_type"],
            "sizeBytes": row["size_bytes"],
            "durationSeconds": row["duration_seconds"],
            "audioPath": row["audio_path"],
            "audioUrl": f"/api/voice-journal/entries/{entry_id}/audio",
            "transcript": row["transcript"],
            "rawTranscript": row["raw_transcript"],
            "transcriptSegments": json.loads(row["transcript_segments_json"] or "[]"),
            "engine": row["engine"],
            "transcriptionData": json.loads(row["transcription_data_json"] or "{}"),
            "correctionHistory": json.loads(row["correction_history_json"] or "[]"),
            "correctionSettings": json.loads(row["correction_settings_json"] or "{}"),
            "tags": json.loads(row["tags_json"] or "[]"),
            "language": row["language"],
            "model": row["model"],
            "device": row["device"],
            "transcriptionDurationSeconds": row["transcription_duration_seconds"],
            "realTimeFactor": row["real_time_factor"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def create(self, audio_part: dict, raw_entry: dict) -> dict:
        self.initialize()
        suffix = validate_audio_part(audio_part)
        title = normalize_text(raw_entry.get("title"), field_name="title", max_length=120)
        if not title:
            title = str(audio_part.get("filename") or "").strip()[:120]
        category = str(raw_entry.get("entryCategory") or "").strip()
        if category not in ENTRY_CATEGORIES:
            raise VoiceJournalError("Unsupported entryCategory")
        recorded_at = normalize_iso_datetime(raw_entry.get("recordedAt"), "recordedAt")
        date_source = str(raw_entry.get("dateSource") or "").strip()
        if date_source not in DATE_SOURCES:
            raise VoiceJournalError("Unsupported dateSource")
        transcript = normalize_text(raw_entry.get("transcript"), field_name="transcript", max_length=500_000)
        raw_transcript = normalize_text(
            raw_entry.get("rawTranscript", transcript), field_name="rawTranscript", max_length=500_000
        )
        transcript_segments = normalize_transcript_segments(raw_entry.get("transcriptSegments", []))
        engine = str(raw_entry.get("engine") or DEFAULT_ENGINE).strip().lower()
        if engine not in {OPENAI_ENGINE, FASTER_ENGINE}:
            raise VoiceJournalError("Unsupported transcription engine")
        transcription_data = normalize_json_document(
            raw_entry.get("transcriptionData") or {
                "version": 1, "engine": engine, "segments": transcript_segments,
            },
            "transcriptionData", expected_type=dict, default={},
        )
        correction_history = normalize_json_document(
            raw_entry.get("correctionHistory", []), "correctionHistory", expected_type=list, default=[]
        )
        correction_settings = normalize_json_document(
            raw_entry.get("correctionSettings", {}), "correctionSettings", expected_type=dict, default={}
        )
        tags = normalize_tags(raw_entry.get("tags", []))
        language = normalize_text(raw_entry.get("language"), field_name="language", max_length=16, required=True)
        if language not in {"auto", "pl"}:
            raise VoiceJournalError("Unsupported language")
        model = normalize_text(raw_entry.get("model"), field_name="model", max_length=32, required=True)
        allowed_models = FASTER_MODELS if engine == FASTER_ENGINE else SUPPORTED_MODELS
        if model not in allowed_models:
            raise VoiceJournalError("Unsupported model")
        device = normalize_text(raw_entry.get("device"), field_name="device", max_length=16, required=True)
        if device not in {"cpu", "cuda"}:
            raise VoiceJournalError("Unsupported device")
        try:
            transcription_duration = float(raw_entry.get("transcriptionDurationSeconds"))
            real_time_factor = float(raw_entry.get("realTimeFactor"))
        except (TypeError, ValueError) as exc:
            raise VoiceJournalError("Invalid transcription metrics") from exc
        if (
            not math.isfinite(transcription_duration)
            or not math.isfinite(real_time_factor)
            or transcription_duration < 0
            or real_time_factor < 0
        ):
            raise VoiceJournalError("Invalid transcription metrics")

        entry_id = uuid.uuid4().hex
        stored_filename = f"{uuid.uuid4().hex}{suffix}"
        final_path = (self.audio_dir / stored_filename).resolve()
        if final_path.parent != self.audio_dir:
            raise VoiceJournalError("Unsafe audio storage path", status=500, code="unsafe_audio_path")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", suffix=suffix, dir=self.audio_dir)
        os.close(descriptor)
        temporary_path = Path(temporary_name).resolve()
        moved = False
        try:
            temporary_path.write_bytes(audio_part["content"])
            metadata = probe_audio(temporary_path)
            os.replace(temporary_path, final_path)
            moved = True
            now = utc_now()
            uploaded_at = now
            audio_path = self._audio_relative_path(stored_filename)
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO voice_journal_entries (
                        id, title, entry_category, recorded_at, uploaded_at, date_source,
                        original_filename, stored_filename, mime_type, size_bytes,
                        duration_seconds, audio_path, transcript, raw_transcript,
                        transcript_segments_json, engine, transcription_data_json,
                        correction_history_json, correction_settings_json, tags_json, language,
                        model, device, transcription_duration_seconds, real_time_factor,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id, title, category, recorded_at, uploaded_at, date_source,
                        audio_part["filename"], stored_filename, audio_part["mime"],
                        len(audio_part["content"]), metadata["durationSeconds"], audio_path,
                        transcript, raw_transcript,
                        json.dumps(transcript_segments, ensure_ascii=False),
                        engine,
                        json.dumps(transcription_data, ensure_ascii=False),
                        json.dumps(correction_history, ensure_ascii=False),
                        json.dumps(correction_settings, ensure_ascii=False),
                        json.dumps(tags, ensure_ascii=False), language, model,
                        device, transcription_duration, real_time_factor, now, now,
                    ),
                )
            return self.get(entry_id)
        except Exception:
            if moved:
                final_path.unlink(missing_ok=True)
            raise
        finally:
            temporary_path.unlink(missing_ok=True)

    def list(self, limit: int = 200) -> list[dict]:
        self.initialize()
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM voice_journal_entries ORDER BY recorded_at DESC, created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get(self, entry_id: str) -> dict:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM voice_journal_entries WHERE id = ?",
                (str(entry_id),),
            ).fetchone()
        if row is None:
            raise VoiceJournalError("Voice journal entry not found", status=404, code="entry_not_found")
        return self._row_to_entry(row)

    def update(self, entry_id: str, payload: dict) -> dict:
        self.initialize()
        if not isinstance(payload, dict) or not payload:
            raise VoiceJournalError("Update payload is required")
        unknown = set(payload) - MUTABLE_FIELDS
        if unknown:
            raise VoiceJournalError(f"Unsupported update fields: {', '.join(sorted(unknown))}")
        updates = {}
        if "title" in payload:
            updates["title"] = normalize_text(payload["title"], field_name="title", max_length=120)
        if "entryCategory" in payload:
            category = str(payload["entryCategory"] or "").strip()
            if category not in ENTRY_CATEGORIES:
                raise VoiceJournalError("Unsupported entryCategory")
            updates["entry_category"] = category
        if "recordedAt" in payload:
            updates["recorded_at"] = normalize_iso_datetime(payload["recordedAt"], "recordedAt")
            updates["date_source"] = "user_corrected"
        if "tags" in payload:
            updates["tags_json"] = json.dumps(normalize_tags(payload["tags"]), ensure_ascii=False)
        if "transcript" in payload:
            updates["transcript"] = normalize_text(payload["transcript"], field_name="transcript", max_length=500_000)
        if "transcriptionData" in payload:
            value = normalize_json_document(payload["transcriptionData"], "transcriptionData", expected_type=dict, default={})
            updates["transcription_data_json"] = json.dumps(value, ensure_ascii=False)
        if "correctionHistory" in payload:
            value = normalize_json_document(payload["correctionHistory"], "correctionHistory", expected_type=list, default=[])
            updates["correction_history_json"] = json.dumps(value, ensure_ascii=False)
        if "correctionSettings" in payload:
            value = normalize_json_document(payload["correctionSettings"], "correctionSettings", expected_type=dict, default={})
            updates["correction_settings_json"] = json.dumps(value, ensure_ascii=False)
        updates["updated_at"] = utc_now()

        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = [*updates.values(), str(entry_id)]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE voice_journal_entries SET {assignments} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise VoiceJournalError("Voice journal entry not found", status=404, code="entry_not_found")
        return self.get(entry_id)

    def delete(self, entry_id: str, *, delete_audio: bool) -> dict:
        entry = self.get(entry_id)
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM voice_journal_entries WHERE id = ?", (str(entry_id),))
            if cursor.rowcount == 0:
                raise VoiceJournalError("Voice journal entry not found", status=404, code="entry_not_found")
        audio_deleted = False
        if delete_audio:
            path = self._resolved_audio_path(entry["audioPath"])
            path.unlink(missing_ok=True)
            audio_deleted = not path.exists()
        return {
            "deleted": True,
            "id": str(entry_id),
            "audioDeleted": audio_deleted,
            "preservedAudioPath": None if delete_audio else entry["audioPath"],
        }

    def _resolved_audio_path(self, audio_path: str) -> Path:
        path = (self.root / str(audio_path)).resolve()
        if path.parent != self.audio_dir:
            raise VoiceJournalError("Unsafe audio path", status=500, code="unsafe_audio_path")
        return path

    def audio_file(self, entry_id: str) -> tuple[Path, str, int]:
        entry = self.get(entry_id)
        path = self._resolved_audio_path(entry["audioPath"])
        if not path.is_file():
            raise VoiceJournalError("Audio file not found", status=404, code="audio_not_found")
        return path, entry["mimeType"], path.stat().st_size


PROJECT_ROOT = Path(__file__).resolve().parent
VOICE_JOURNAL_STORE = VoiceJournalStore(
    PROJECT_ROOT / "data" / "voice-journal.sqlite",
    PROJECT_ROOT / "data" / "raw" / "voice-journal" / "audio",
    PROJECT_ROOT,
)


__all__ = [
    "MAX_MULTIPART_BYTES",
    "VoiceJournalStore",
    "VOICE_JOURNAL_STORE",
    "parse_create_entry_request",
]
