import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class Bm365MetadataError(ValueError):
    def __init__(self, message, *, status=400, code="invalid_metadata"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self):
        return {"error": str(self), "code": self.code}


class Bm365MetadataStore:
    def __init__(self, db_path=None):
        root = Path(__file__).resolve().parent
        self.db_path = Path(db_path or root / "data" / "bm365-metadata.sqlite")
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def initialize(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS album_metadata (
                        row_id INTEGER PRIMARY KEY,
                        artist TEXT NOT NULL,
                        album TEXT NOT NULL,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_bm365_metadata_identity "
                    "ON album_metadata(artist COLLATE NOCASE, album COLLATE NOCASE)"
                )
            self._initialized = True

    @staticmethod
    def _parse_row_id(value):
        try:
            row_id = int(value)
        except (TypeError, ValueError) as exc:
            raise Bm365MetadataError("album id is required", code="invalid_album_id") from exc
        if row_id <= 0:
            raise Bm365MetadataError("album id is required", code="invalid_album_id")
        return row_id

    @staticmethod
    def _clean_identity(value, field):
        clean = str(value or "").strip()
        if not clean:
            raise Bm365MetadataError(f"{field} is required", code=f"missing_{field}")
        if len(clean) > 240:
            raise Bm365MetadataError(f"{field} is too long", code=f"invalid_{field}")
        return clean

    @staticmethod
    def _parse_description(value, *, enforce_sentence_limit=True):
        clean = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(clean) > 4000:
            raise Bm365MetadataError(
                "description must be at most 4000 characters",
                code="invalid_description",
            )
        sentences = [
            part for part in re.findall(r"[^.!?]+(?:[.!?]+|$)", clean)
            if re.search(r"\w", part)
        ]
        if enforce_sentence_limit and len(sentences) > 10:
            raise Bm365MetadataError(
                "description must be at most 10 sentences",
                code="invalid_description",
            )
        return clean

    @staticmethod
    def _row_payload(row):
        return {
            "rowId": row["row_id"],
            "artist": row["artist"],
            "album": row["album"],
            "description": row["description"] or "",
            "updatedAt": row["updated_at"],
        }

    def list(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM album_metadata ORDER BY row_id"
            ).fetchall()
        return [self._row_payload(row) for row in rows]

    def snapshot(self):
        rows = self.list()
        return {
            "ok": True,
            "metadata": rows,
            "count": len(rows),
            "storedPath": self.db_path.as_posix(),
        }

    def update(self, row_id, payload, *, artist, album):
        row_id = self._parse_row_id(row_id)
        artist = self._clean_identity(artist, "artist")
        album = self._clean_identity(album, "album")
        payload = payload if isinstance(payload, dict) else {}
        supported = {"description"}.intersection(payload)
        if not supported:
            raise Bm365MetadataError("No supported fields to update", code="empty_update")

        self.initialize()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM album_metadata WHERE row_id = ?", (row_id,)
            ).fetchone()
            description = (
                self._parse_description(payload.get("description"))
                if "description" in payload
                else (existing["description"] if existing else "")
            )
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO album_metadata (
                    row_id, artist, album, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(row_id) DO UPDATE SET
                    artist = excluded.artist,
                    album = excluded.album,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (row_id, artist, album, description, now, now),
            )
            row = connection.execute(
                "SELECT * FROM album_metadata WHERE row_id = ?", (row_id,)
            ).fetchone()
        return self._row_payload(row)

    def bulk_update_descriptions(self, descriptions, albums_by_id, *, overwrite=False):
        if not isinstance(descriptions, dict) or not descriptions:
            raise Bm365MetadataError(
                "descriptions must be a non-empty object keyed by album id",
                code="invalid_descriptions",
            )
        if len(descriptions) > 50:
            raise Bm365MetadataError(
                "a single import can contain at most 50 descriptions",
                code="too_many_descriptions",
            )

        albums_by_id = albums_by_id if isinstance(albums_by_id, dict) else {}
        prepared = []
        for raw_id, raw_description in descriptions.items():
            row_id = self._parse_row_id(raw_id)
            album_row = albums_by_id.get(row_id)
            if not album_row:
                raise Bm365MetadataError(
                    f"album not found: {row_id}", status=404, code="album_not_found"
                )
            description = self._parse_description(
                raw_description, enforce_sentence_limit=False
            )
            if not description:
                raise Bm365MetadataError(
                    f"description for album {row_id} is empty",
                    code="invalid_description",
                )
            prepared.append((row_id, album_row, description))

        self.initialize()
        now = datetime.now(timezone.utc).isoformat()
        updated_ids = []
        skipped_ids = []
        with self._connect() as connection:
            existing = {
                row["row_id"]: row
                for row in connection.execute(
                    f"SELECT * FROM album_metadata WHERE row_id IN ({', '.join('?' for _ in prepared)})",
                    [row_id for row_id, _, _ in prepared],
                ).fetchall()
            }
            for row_id, album_row, description in prepared:
                current = existing.get(row_id)
                if not overwrite and current and str(current["description"] or "").strip():
                    skipped_ids.append(row_id)
                    continue
                artist = self._clean_identity(album_row.get("artist"), "artist")
                album = self._clean_identity(album_row.get("album"), "album")
                created_at = current["created_at"] if current else now
                connection.execute(
                    """
                    INSERT INTO album_metadata (
                        row_id, artist, album, description, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(row_id) DO UPDATE SET
                        artist = excluded.artist,
                        album = excluded.album,
                        description = excluded.description,
                        updated_at = excluded.updated_at
                    """,
                    (row_id, artist, album, description, created_at, now),
                )
                updated_ids.append(row_id)

            updated = []
            if updated_ids:
                updated = connection.execute(
                    f"SELECT * FROM album_metadata WHERE row_id IN ({', '.join('?' for _ in updated_ids)}) ORDER BY row_id",
                    updated_ids,
                ).fetchall()

        return {
            "updated": [self._row_payload(row) for row in updated],
            "updatedCount": len(updated_ids),
            "skippedIds": skipped_ids,
        }


BM365_METADATA_STORE = Bm365MetadataStore()
