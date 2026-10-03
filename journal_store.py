"""Persistent local storage for the standalone written journal."""

from __future__ import annotations

import base64
import binascii
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dashboard_sync.migration import backup_before_migration, migrate


MAX_CONTENT_LENGTH = 1_000_000
MAX_SOURCE_METADATA_BYTES = 1_000_000
MAX_ILLUSTRATION_BYTES = 2 * 1024 * 1024
UNTITLED_ENTRY_TITLE = "* * *"
MUTABLE_FIELDS = {
    "title", "content", "contentFormat", "entryDate", "entryKind", "tags", "location", "illustration", "illustrationAlt",
}
VOICE_TIMESTAMP_PATTERN = re.compile(r"\[\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?\s*\]")
DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ILLUSTRATION_PATTERN = re.compile(
    r"data:image/(?:jpeg|png|webp|gif);base64,([A-Za-z0-9+/=]+)",
    re.IGNORECASE,
)


class JournalError(ValueError):
    def __init__(self, message: str, *, status: int = 400, code: str = "journal_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self) -> dict:
        return {"error": str(self), "code": self.code}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_datetime(value, field_name: str, *, default_now: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw and default_now:
        return utc_now()
    if not raw:
        raise JournalError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalError(f"{field_name} must be an ISO date-time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_entry_date(value, field_name: str, *, default_now: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw and default_now:
        return utc_now()
    if DATE_ONLY_PATTERN.fullmatch(raw):
        try:
            datetime.strptime(raw, "%Y-%m-%d")
        except ValueError as exc:
            raise JournalError(f"{field_name} must be an ISO date or date-time") from exc
        return raw
    return normalize_datetime(raw, field_name)


def normalize_text(value, field_name: str, max_length: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise JournalError(f"{field_name} is required")
    if len(text) > max_length:
        raise JournalError(f"{field_name} is too long", status=413, code="payload_too_large")
    return text


def normalize_title(value) -> str:
    title = normalize_text(value, "title", 160)
    if not title or title.casefold() == "bez tytułu":
        return UNTITLED_ENTRY_TITLE
    return title


def strip_voice_transcript_timestamps(value) -> str:
    text = VOICE_TIMESTAMP_PATTERN.sub("", str(value or ""))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def normalize_tags(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise JournalError("tags must be an array")
    tags = []
    for raw in value:
        tag = normalize_text(raw, "tag", 40)
        if tag and tag.casefold() not in {item.casefold() for item in tags}:
            tags.append(tag)
        if len(tags) >= 20:
            break
    return tags


def normalize_content_format(value) -> str:
    content_format = str(value or "text").strip().lower()
    if content_format not in {"text", "html"}:
        raise JournalError("contentFormat must be text or html")
    return content_format


def normalize_entry_kind(value) -> str:
    entry_kind = str(value or "journal").strip().lower()
    if entry_kind not in {"journal", "poem"}:
        raise JournalError("entryKind must be journal or poem")
    return entry_kind


def normalize_source_metadata(value) -> tuple[dict, str]:
    if not isinstance(value, dict):
        raise JournalError("sourceMetadata must be an object")
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_SOURCE_METADATA_BYTES:
        raise JournalError("Source metadata is too large", status=413, code="payload_too_large")
    return value, encoded


def normalize_illustration(value) -> str:
    data_url = str(value or "").strip()
    if not data_url:
        return ""
    match = ILLUSTRATION_PATTERN.fullmatch(data_url)
    if not match:
        raise JournalError("illustration must be a base64 JPG, PNG, WebP or GIF")
    try:
        image_bytes = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise JournalError("illustration contains invalid base64 data") from exc
    if len(image_bytes) > MAX_ILLUSTRATION_BYTES:
        raise JournalError("illustration is too large", status=413, code="payload_too_large")
    return data_url


def voice_source_metadata(entry: dict) -> dict:
    excluded = {
        "id", "title", "transcript", "rawTranscript", "transcriptSegments",
        "transcriptionData", "correctionHistory", "correctionSettings", "tags",
    }
    metadata = {
        key: value for key, value in entry.items()
        if key not in excluded and isinstance(value, (str, int, float, bool, type(None)))
    }
    metadata["voiceJournalEntryId"] = str(entry.get("id") or "")
    metadata["voiceJournalTitle"] = str(entry.get("title") or "")
    encoded = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_SOURCE_METADATA_BYTES:
        raise JournalError("Voice journal metadata is too large", status=413, code="payload_too_large")
    return metadata


class JournalStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self._init_lock = threading.Lock()
        self._initialized = False

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            backup_before_migration(self.db_path)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS journal_entries (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL,
                        content_format TEXT NOT NULL DEFAULT 'text',
                        entry_date TEXT NOT NULL,
                        entry_kind TEXT NOT NULL DEFAULT 'journal',
                        tags_json TEXT NOT NULL DEFAULT '[]',
                        location TEXT NOT NULL DEFAULT '',
                        illustration_data_url TEXT NOT NULL DEFAULT '',
                        illustration_alt TEXT NOT NULL DEFAULT '',
                        source_type TEXT NOT NULL DEFAULT 'manual',
                        source_external_id TEXT,
                        source_voice_journal_entry_id TEXT UNIQUE,
                        source_metadata_json TEXT NOT NULL DEFAULT '{}',
                        published_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_journal_entry_date
                    ON journal_entries(entry_date DESC, created_at DESC);
                    """
                )
                connection.execute("BEGIN IMMEDIATE")
                columns = {row[1] for row in connection.execute("PRAGMA table_info(journal_entries)")}
                if "content_format" not in columns:
                    connection.execute(
                        "ALTER TABLE journal_entries ADD COLUMN content_format TEXT NOT NULL DEFAULT 'text'"
                    )
                if "illustration_data_url" not in columns:
                    connection.execute(
                        "ALTER TABLE journal_entries ADD COLUMN illustration_data_url TEXT NOT NULL DEFAULT ''"
                    )
                if "illustration_alt" not in columns:
                    connection.execute(
                        "ALTER TABLE journal_entries ADD COLUMN illustration_alt TEXT NOT NULL DEFAULT ''"
                    )
                if "location" not in columns:
                    connection.execute(
                        "ALTER TABLE journal_entries ADD COLUMN location TEXT NOT NULL DEFAULT ''"
                    )
                if "entry_kind" not in columns:
                    connection.execute(
                        "ALTER TABLE journal_entries ADD COLUMN entry_kind TEXT NOT NULL DEFAULT 'journal'"
                    )
                if "source_external_id" not in columns:
                    connection.execute(
                        "ALTER TABLE journal_entries ADD COLUMN source_external_id TEXT"
                    )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_external_source "
                    "ON journal_entries(source_type, source_external_id) "
                    "WHERE source_external_id IS NOT NULL"
                )
                connection.execute(
                    "UPDATE journal_entries SET title = ? "
                    "WHERE TRIM(title) = '' OR LOWER(TRIM(title)) = LOWER(?)",
                    (UNTITLED_ENTRY_TITLE, "Bez tytułu"),
                )
                migrate(connection)
            self._initialized = True

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "contentFormat": row["content_format"],
            "entryDate": row["entry_date"],
            "entryKind": row["entry_kind"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "location": row["location"],
            "illustration": row["illustration_data_url"],
            "illustrationAlt": row["illustration_alt"],
            "sourceType": row["source_type"],
            "sourceExternalId": row["source_external_id"],
            "sourceVoiceJournalEntryId": row["source_voice_journal_entry_id"],
            "sourceMetadata": json.loads(row["source_metadata_json"] or "{}"),
            "publishedAt": row["published_at"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "version": row["sync_version"],
            "deletedAt": None,
        }

    def create(self, payload: dict, *, _entry_id=None) -> dict:
        self.initialize()
        if not isinstance(payload, dict):
            raise JournalError("Entry must be a JSON object")
        unknown = set(payload) - MUTABLE_FIELDS
        if unknown:
            raise JournalError(f"Unsupported fields: {', '.join(sorted(unknown))}")
        title = normalize_title(payload.get("title"))
        content = normalize_text(payload.get("content"), "content", MAX_CONTENT_LENGTH)
        content_format = normalize_content_format(payload.get("contentFormat"))
        entry_date = normalize_entry_date(payload.get("entryDate"), "entryDate", default_now=True)
        entry_kind = normalize_entry_kind(payload.get("entryKind"))
        tags = normalize_tags(payload.get("tags", []))
        location = normalize_text(payload.get("location"), "location", 160)
        illustration = normalize_illustration(payload.get("illustration"))
        illustration_alt = normalize_text(payload.get("illustrationAlt"), "illustrationAlt", 240)
        if not content and not illustration:
            raise JournalError("Entry requires content or an illustration")
        if not illustration:
            illustration_alt = ""
        entry_id = _entry_id or uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO journal_entries (
                    id, title, content, content_format, entry_date, entry_kind, tags_json, location,
                    illustration_data_url, illustration_alt, source_type,
                    source_metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', '{}', ?, ?)
                """,
                (
                    entry_id, title, content, content_format, entry_date, entry_kind,
                    json.dumps(tags, ensure_ascii=False), location, illustration, illustration_alt, now, now,
                ),
            )
        return self.get(entry_id)

    def publish_voice_entry(self, voice_entry: dict) -> dict:
        self.initialize()
        voice_id = str(voice_entry.get("id") or "").strip()
        if not voice_id:
            raise JournalError("Voice journal entry id is required")
        content = normalize_text(
            strip_voice_transcript_timestamps(voice_entry.get("transcript")),
            "organized transcript",
            MAX_CONTENT_LENGTH,
            required=True,
        )
        title = normalize_title(voice_entry.get("title"))
        entry_date = normalize_datetime(voice_entry.get("recordedAt"), "recordedAt")
        tags = normalize_tags(voice_entry.get("tags", []))
        metadata = voice_source_metadata(voice_entry)
        now = utc_now()
        entry_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO journal_entries (
                    id, title, content, content_format, entry_date, tags_json, source_type,
                    source_voice_journal_entry_id, source_metadata_json,
                    published_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'text', ?, ?, 'voice-journal', ?, ?, ?, ?, ?)
                ON CONFLICT(source_voice_journal_entry_id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    content_format = excluded.content_format,
                    entry_date = excluded.entry_date,
                    tags_json = excluded.tags_json,
                    source_metadata_json = excluded.source_metadata_json,
                    published_at = excluded.published_at,
                    updated_at = excluded.updated_at
                """,
                (
                    entry_id, title, content, entry_date, json.dumps(tags, ensure_ascii=False),
                    voice_id, json.dumps(metadata, ensure_ascii=False), now, now, now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM journal_entries WHERE source_voice_journal_entry_id = ?", (voice_id,)
            ).fetchone()
        return self._row_to_entry(row)

    def publish_htr_entry(self, payload: dict) -> dict:
        """Create a written-journal entry while retaining local HTR provenance."""
        self.initialize()
        if not isinstance(payload, dict):
            raise JournalError("HTR entry must be a JSON object")
        title = normalize_title(payload.get("title"))
        content = normalize_text(
            payload.get("content"), "content", MAX_CONTENT_LENGTH, required=True
        )
        entry_date = normalize_entry_date(
            payload.get("entryDate"), "entryDate", default_now=True
        )
        tags = normalize_tags(payload.get("tags", []))
        metadata = payload.get("sourceMetadata")
        if not isinstance(metadata, dict):
            raise JournalError("HTR sourceMetadata must be an object")
        encoded_metadata = json.dumps(metadata, ensure_ascii=False)
        if len(encoded_metadata.encode("utf-8")) > MAX_SOURCE_METADATA_BYTES:
            raise JournalError(
                "HTR source metadata is too large",
                status=413,
                code="payload_too_large",
            )
        entry_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO journal_entries (
                    id, title, content, content_format, entry_date, tags_json,
                    source_type, source_metadata_json, published_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'text', ?, ?, 'journal-htr', ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    title,
                    content,
                    entry_date,
                    json.dumps(tags, ensure_ascii=False),
                    encoded_metadata,
                    now,
                    now,
                    now,
                ),
            )
        return self.get(entry_id)

    @staticmethod
    def _prepare_external_entry(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise JournalError("External entry must be a JSON object")
        source_type = normalize_text(payload.get("sourceType"), "sourceType", 80, required=True)
        source_external_id = normalize_text(
            payload.get("sourceExternalId"), "sourceExternalId", 240, required=True
        )
        title = normalize_title(payload.get("title"))
        content = normalize_text(payload.get("content"), "content", MAX_CONTENT_LENGTH)
        content_format = normalize_content_format(payload.get("contentFormat"))
        entry_date = normalize_entry_date(payload.get("entryDate"), "entryDate")
        entry_kind = normalize_entry_kind(payload.get("entryKind"))
        tags = normalize_tags(payload.get("tags", []))
        location = normalize_text(payload.get("location"), "location", 160)
        illustration = normalize_illustration(payload.get("illustration"))
        illustration_alt = normalize_text(payload.get("illustrationAlt"), "illustrationAlt", 240)
        if not content and not illustration:
            raise JournalError("External entry requires content or an illustration")
        if not illustration:
            illustration_alt = ""
        _, encoded_metadata = normalize_source_metadata(payload.get("sourceMetadata", {}))
        return {
            "source_type": source_type,
            "source_external_id": source_external_id,
            "title": title,
            "content": content,
            "content_format": content_format,
            "entry_date": entry_date,
            "entry_kind": entry_kind,
            "tags_json": json.dumps(tags, ensure_ascii=False),
            "location": location,
            "illustration": illustration,
            "illustration_alt": illustration_alt,
            "metadata_json": encoded_metadata,
        }

    def import_external_entries(self, payloads: list[dict]) -> list[dict]:
        """Atomically and idempotently import trusted external journal items."""
        self.initialize()
        if not isinstance(payloads, list) or not payloads:
            raise JournalError("External entries must be a non-empty array")
        prepared = [self._prepare_external_entry(payload) for payload in payloads]
        identities = [(row["source_type"], row["source_external_id"]) for row in prepared]
        if len(set(identities)) != len(identities):
            raise JournalError("External entries contain duplicate source identities")
        now = utc_now()
        entry_ids = []
        with self._connect() as connection:
            for row in prepared:
                existing = connection.execute(
                    "SELECT id FROM journal_entries WHERE source_type = ? AND source_external_id = ?",
                    (row["source_type"], row["source_external_id"]),
                ).fetchone()
                if existing:
                    entry_id = existing["id"]
                    connection.execute(
                        """
                        UPDATE journal_entries SET
                            title = ?, content = ?, content_format = ?, entry_date = ?, entry_kind = ?,
                            tags_json = ?, location = ?, illustration_data_url = ?, illustration_alt = ?,
                            source_metadata_json = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            row["title"], row["content"], row["content_format"], row["entry_date"],
                            row["entry_kind"], row["tags_json"], row["location"], row["illustration"],
                            row["illustration_alt"], row["metadata_json"], now, entry_id,
                        ),
                    )
                else:
                    entry_id = uuid.uuid4().hex
                    connection.execute(
                        """
                        INSERT INTO journal_entries (
                            id, title, content, content_format, entry_date, entry_kind, tags_json, location,
                            illustration_data_url, illustration_alt, source_type, source_external_id,
                            source_metadata_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry_id, row["title"], row["content"], row["content_format"], row["entry_date"],
                            row["entry_kind"], row["tags_json"], row["location"], row["illustration"],
                            row["illustration_alt"], row["source_type"], row["source_external_id"],
                            row["metadata_json"], now, now,
                        ),
                    )
                entry_ids.append(entry_id)
            placeholders = ",".join("?" for _ in entry_ids)
            rows = connection.execute(
                f"SELECT * FROM journal_entries WHERE id IN ({placeholders})", entry_ids
            ).fetchall()
        by_id = {row["id"]: self._row_to_entry(row) for row in rows}
        return [by_id[entry_id] for entry_id in entry_ids]

    def import_external_entry(self, payload: dict) -> dict:
        return self.import_external_entries([payload])[0]

    def list(self, limit: int = 500) -> list[dict]:
        self.initialize()
        safe_limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM journal_entries ORDER BY entry_date DESC, created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def voice_publication_lookup(self) -> dict[str, dict]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_voice_journal_entry_id, published_at, updated_at
                FROM journal_entries
                WHERE source_voice_journal_entry_id IS NOT NULL
                """
            ).fetchall()
        return {
            row["source_voice_journal_entry_id"]: {
                "id": row["id"],
                "publishedAt": row["published_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        }

    def get(self, entry_id: str) -> dict:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM journal_entries WHERE id = ?", (str(entry_id),)).fetchone()
        if row is None:
            raise JournalError("Journal entry not found", status=404, code="entry_not_found")
        return self._row_to_entry(row)

    def update(self, entry_id: str, payload: dict, *, expected_version=None) -> dict:
        self.initialize()
        if not isinstance(payload, dict) or not payload:
            raise JournalError("Update payload is required")
        unknown = set(payload) - MUTABLE_FIELDS
        if unknown:
            raise JournalError(f"Unsupported fields: {', '.join(sorted(unknown))}")
        updates = {}
        if "title" in payload:
            updates["title"] = normalize_title(payload["title"])
        if "content" in payload:
            updates["content"] = normalize_text(payload["content"], "content", MAX_CONTENT_LENGTH)
        if "contentFormat" in payload:
            updates["content_format"] = normalize_content_format(payload["contentFormat"])
        if "entryDate" in payload:
            updates["entry_date"] = normalize_entry_date(payload["entryDate"], "entryDate")
        if "entryKind" in payload:
            updates["entry_kind"] = normalize_entry_kind(payload["entryKind"])
        if "tags" in payload:
            updates["tags_json"] = json.dumps(normalize_tags(payload["tags"]), ensure_ascii=False)
        if "location" in payload:
            updates["location"] = normalize_text(payload["location"], "location", 160)
        if "illustration" in payload:
            updates["illustration_data_url"] = normalize_illustration(payload["illustration"])
            if not updates["illustration_data_url"] and "illustrationAlt" not in payload:
                updates["illustration_alt"] = ""
        if "illustrationAlt" in payload:
            updates["illustration_alt"] = normalize_text(payload["illustrationAlt"], "illustrationAlt", 240)
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{column} = ?" for column in updates)
        with self._connect() as connection:
            if expected_version is not None:
                connection.execute("BEGIN IMMEDIATE")
                self._check_version(connection, entry_id, expected_version)
            existing = connection.execute(
                "SELECT content, illustration_data_url FROM journal_entries WHERE id = ?",
                (str(entry_id),),
            ).fetchone()
            if existing is None:
                raise JournalError("Journal entry not found", status=404, code="entry_not_found")
            next_content = updates.get("content", existing["content"])
            next_illustration = updates.get("illustration_data_url", existing["illustration_data_url"])
            if not next_content and not next_illustration:
                raise JournalError("Entry requires content or an illustration")
            cursor = connection.execute(
                f"UPDATE journal_entries SET {assignments} WHERE id = ?",
                [*updates.values(), str(entry_id)],
            )
            if cursor.rowcount == 0:
                raise JournalError("Journal entry not found", status=404, code="entry_not_found")
        return self.get(entry_id)

    def delete(self, entry_id: str, *, expected_version=None) -> dict:
        self.initialize()
        with self._connect() as connection:
            if expected_version is not None:
                connection.execute("BEGIN IMMEDIATE")
                self._check_version(connection, entry_id, expected_version)
            cursor = connection.execute("DELETE FROM journal_entries WHERE id = ?", (str(entry_id),))
            if cursor.rowcount == 0:
                raise JournalError("Journal entry not found", status=404, code="entry_not_found")
        return {"deleted": True, "id": str(entry_id)}

    def _check_version(self, connection, entry_id, expected):
        from dashboard_sync.core import SyncError
        from dashboard_sync.journal import JournalAdapter
        if type(expected) is not int or expected < 1:
            raise SyncError("VALIDATION_ERROR", "expectedVersion must be a positive integer")
        record = JournalAdapter(self).get(connection, entry_id)
        if record and (record["version"] != expected or record.get("deletedAt")):
            raise SyncError("VERSION_CONFLICT", "Journal entry changed; reload before saving", 409,
                            id=entry_id, clientVersion=expected, serverVersion=record["version"], serverRecord=record)


PROJECT_ROOT = Path(__file__).resolve().parent
JOURNAL_STORE = JournalStore(PROJECT_ROOT / "data" / "journal.sqlite")


__all__ = ["JournalError", "JournalStore", "JOURNAL_STORE", "voice_source_metadata"]
