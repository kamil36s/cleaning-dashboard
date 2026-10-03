import math
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


class BrutalAssaultError(ValueError):
    def __init__(self, message, *, status=400, code="invalid_album"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self):
        return {"error": str(self), "code": self.code}


class BrutalAssaultStore:
    def __init__(self, db_path=None):
        root = Path(__file__).resolve().parent
        self.db_path = Path(db_path or root / "data" / "brutal-assault-2027.sqlite")
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                    CREATE TABLE IF NOT EXISTS albums (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        artist TEXT NOT NULL,
                        album TEXT NOT NULL,
                        release_year INTEGER,
                        planned_date TEXT NOT NULL,
                        listened INTEGER NOT NULL DEFAULT 0 CHECK (listened IN (0, 1)),
                        rating REAL CHECK (rating IS NULL OR (rating >= 0.5 AND rating <= 5.0)),
                        minutes INTEGER CHECK (minutes IS NULL OR minutes > 0),
                        rym_rating REAL CHECK (rym_rating IS NULL OR (rym_rating >= 0.5 AND rym_rating <= 5.0)),
                        rym_rating_ignored INTEGER NOT NULL DEFAULT 0 CHECK (rym_rating_ignored IN (0, 1)),
                        community_rating REAL,
                        community_votes INTEGER,
                        community_source TEXT,
                        community_url TEXT,
                        community_checked_at TEXT,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE (artist COLLATE NOCASE, album COLLATE NOCASE)
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ba2027_albums_date ON albums(planned_date, id)"
                )
                existing_columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(albums)").fetchall()
                }
                for column, definition in {
                    "rym_rating": "REAL",
                    "rym_rating_ignored": "INTEGER NOT NULL DEFAULT 0",
                    "community_rating": "REAL",
                    "community_votes": "INTEGER",
                    "community_source": "TEXT",
                    "community_url": "TEXT",
                    "community_checked_at": "TEXT",
                    "description": "TEXT",
                }.items():
                    if column not in existing_columns:
                        connection.execute(f"ALTER TABLE albums ADD COLUMN {column} {definition}")
            self._initialized = True

    @staticmethod
    def _clean_required(value, field, max_length=240):
        clean = str(value or "").strip()
        if not clean:
            raise BrutalAssaultError(f"{field} is required", code=f"missing_{field}")
        if len(clean) > max_length:
            raise BrutalAssaultError(f"{field} is too long", code=f"invalid_{field}")
        return clean

    @staticmethod
    def _parse_date(value):
        raw = str(value or "").strip()
        if not raw:
            raise BrutalAssaultError("date must use YYYY-MM-DD", code="invalid_date")
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError as exc:
            raise BrutalAssaultError("date must use YYYY-MM-DD", code="invalid_date") from exc

    @staticmethod
    def _parse_year(value):
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise BrutalAssaultError("year must be a number", code="invalid_year") from exc
        if parsed < 1900 or parsed > 2100:
            raise BrutalAssaultError("year must be between 1900 and 2100", code="invalid_year")
        return parsed

    @staticmethod
    def _parse_minutes(value):
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise BrutalAssaultError("minutes must be a whole number", code="invalid_minutes") from exc
        if parsed <= 0 or parsed > 1440:
            raise BrutalAssaultError("minutes must be between 1 and 1440", code="invalid_minutes")
        return parsed

    @staticmethod
    def _parse_rating(value):
        if value in (None, ""):
            return None
        try:
            parsed = float(str(value).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise BrutalAssaultError("rating must be a number", code="invalid_rating") from exc
        if not math.isfinite(parsed) or parsed < 0.5 or parsed > 5 or parsed * 2 != int(parsed * 2):
            raise BrutalAssaultError(
                "rating must be between 0.5 and 5.0 in 0.5 steps",
                code="invalid_rating",
            )
        return parsed

    @staticmethod
    def _parse_rym_rating(value):
        if value in (None, ""):
            return None
        try:
            parsed = float(str(value).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise BrutalAssaultError(
                "RYM rating must be a number", code="invalid_rym_rating"
            ) from exc
        if not math.isfinite(parsed) or parsed < 0.5 or parsed > 5.0:
            raise BrutalAssaultError(
                "RYM rating must be between 0.5 and 5.0",
                code="invalid_rym_rating",
            )
        return round(parsed, 2)

    @staticmethod
    def _parse_listened(value):
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "tak"}

    @staticmethod
    def _parse_description(value, *, enforce_sentence_limit=True):
        clean = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(clean) > 4000:
            raise BrutalAssaultError(
                "description must be at most 4000 characters",
                code="invalid_description",
            )
        sentences = [
            part for part in re.findall(r"[^.!?]+(?:[.!?]+|$)", clean)
            if re.search(r"\w", part)
        ]
        if enforce_sentence_limit and len(sentences) > 10:
            raise BrutalAssaultError(
                "description must be at most 10 sentences",
                code="invalid_description",
            )
        return clean

    @staticmethod
    def _row_payload(row):
        return {
            "rowId": row["id"],
            "date": row["planned_date"],
            "artist": row["artist"],
            "album": row["album"],
            "year": str(row["release_year"]) if row["release_year"] else "",
            "listened": "TAK" if row["listened"] else "",
            "rating": row["rating"],
            "minutes": row["minutes"],
            "rymRating": row["rym_rating"],
            "rymRatingIgnored": bool(row["rym_rating_ignored"]),
            "communityRating": row["community_rating"],
            "communityVotes": row["community_votes"],
            "communitySource": row["community_source"],
            "communityUrl": row["community_url"],
            "communityCheckedAt": row["community_checked_at"],
            "description": row["description"] or "",
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def get(self, album_id):
        try:
            album_id = int(album_id)
        except (TypeError, ValueError):
            return None
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        return self._row_payload(row) if row else None

    def list(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM albums ORDER BY planned_date ASC, id ASC"
            ).fetchall()
        return [self._row_payload(row) for row in rows]

    def next_planned_date(self):
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(planned_date) AS last_date FROM albums"
            ).fetchone()
        last_date = str(row["last_date"] or "").strip() if row else ""
        if not last_date:
            return date.today().isoformat()
        return (date.fromisoformat(last_date) + timedelta(days=1)).isoformat()

    def snapshot(self):
        rows = self.list()
        return {
            "ok": True,
            "rows": rows,
            "count": len(rows),
            "storedPath": self.db_path.as_posix(),
        }

    def create(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        artist = self._clean_required(payload.get("artist"), "artist")
        album = self._clean_required(payload.get("album"), "album")
        release_year = self._parse_year(payload.get("year"))
        self.initialize()
        raw_date = str(payload.get("date") or "").strip()
        planned_date = self._parse_date(raw_date) if raw_date else self.next_planned_date()
        minutes = self._parse_minutes(payload.get("minutes"))
        rating = self._parse_rating(payload.get("rating"))
        rym_rating = self._parse_rym_rating(payload.get("rymRating"))
        rym_rating_ignored = self._parse_listened(payload.get("rymRatingIgnored"))
        listened = self._parse_listened(payload.get("listened")) or rating is not None
        description = self._parse_description(payload.get("description"))
        now = datetime.now(timezone.utc).isoformat()

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO albums (
                        artist, album, release_year, planned_date, listened,
                        rating, minutes, rym_rating, rym_rating_ignored,
                        description, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artist,
                        album,
                        release_year,
                        planned_date,
                        int(listened),
                        rating,
                        minutes,
                        rym_rating,
                        int(rym_rating_ignored),
                        description,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM albums WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise BrutalAssaultError(
                "This artist and album are already on the list",
                status=409,
                code="duplicate_album",
            ) from exc

        return self._row_payload(row)

    def update(self, album_id, payload):
        try:
            album_id = int(album_id)
        except (TypeError, ValueError) as exc:
            raise BrutalAssaultError("album id is required", code="invalid_album_id") from exc

        payload = payload if isinstance(payload, dict) else {}
        existing = self.get(album_id)
        if not existing:
            raise BrutalAssaultError("Album not found", status=404, code="album_not_found")
        assignments = []
        values = []
        identity_changed = False

        if "artist" in payload:
            artist = self._clean_required(payload.get("artist"), "artist")
            assignments.append("artist = ?")
            values.append(artist)
            identity_changed = artist.casefold() != existing["artist"].casefold()
        if "album" in payload:
            album = self._clean_required(payload.get("album"), "album")
            assignments.append("album = ?")
            values.append(album)
            identity_changed = identity_changed or album.casefold() != existing["album"].casefold()
        if "year" in payload:
            assignments.append("release_year = ?")
            values.append(self._parse_year(payload.get("year")))
        if "rating" in payload:
            rating = self._parse_rating(payload.get("rating"))
            assignments.append("rating = ?")
            values.append(rating)
            if rating is not None and "listened" not in payload:
                assignments.append("listened = 1")
        if "listened" in payload:
            assignments.append("listened = ?")
            values.append(int(self._parse_listened(payload.get("listened"))))
        if "minutes" in payload:
            assignments.append("minutes = ?")
            values.append(self._parse_minutes(payload.get("minutes")))
        if "rymRating" in payload:
            rym_rating = self._parse_rym_rating(payload.get("rymRating"))
            assignments.append("rym_rating = ?")
            values.append(rym_rating)
            if rym_rating is not None:
                assignments.append("rym_rating_ignored = 0")
                assignments.extend([
                    "community_rating = NULL",
                    "community_votes = NULL",
                    "community_source = NULL",
                    "community_url = NULL",
                    "community_checked_at = NULL",
                ])
        if "rymRatingIgnored" in payload:
            assignments.append("rym_rating_ignored = ?")
            values.append(int(self._parse_listened(payload.get("rymRatingIgnored"))))
        if "date" in payload:
            assignments.append("planned_date = ?")
            values.append(self._parse_date(payload.get("date")))
        if "description" in payload:
            assignments.append("description = ?")
            values.append(self._parse_description(payload.get("description")))

        if identity_changed:
            if "rymRating" not in payload:
                assignments.append("rym_rating = NULL")
            if "rymRatingIgnored" not in payload:
                assignments.append("rym_rating_ignored = 0")
            assignments.extend([
                "community_rating = NULL",
                "community_votes = NULL",
                "community_source = NULL",
                "community_url = NULL",
                "community_checked_at = NULL",
            ])

        if not assignments:
            raise BrutalAssaultError("No supported fields to update", code="empty_update")

        assignments.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(album_id)

        self.initialize()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    f"UPDATE albums SET {', '.join(assignments)} WHERE id = ?", values
                )
                if cursor.rowcount != 1:
                    raise BrutalAssaultError("Album not found", status=404, code="album_not_found")
                row = connection.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise BrutalAssaultError(
                "This artist and album are already on the list",
                status=409,
                code="duplicate_album",
            ) from exc
        return self._row_payload(row)

    def bulk_update_descriptions(self, descriptions, *, overwrite=False):
        if not isinstance(descriptions, dict) or not descriptions:
            raise BrutalAssaultError(
                "descriptions must be a non-empty object keyed by album id",
                code="invalid_descriptions",
            )
        if len(descriptions) > 50:
            raise BrutalAssaultError(
                "a single import can contain at most 50 descriptions",
                code="too_many_descriptions",
            )

        prepared = []
        seen_ids = set()
        for raw_id, raw_description in descriptions.items():
            try:
                album_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise BrutalAssaultError(
                    f"invalid album id: {raw_id}", code="invalid_album_id"
                ) from exc
            if album_id <= 0 or album_id in seen_ids:
                raise BrutalAssaultError(
                    f"invalid album id: {raw_id}", code="invalid_album_id"
                )
            description = self._parse_description(
                raw_description,
                enforce_sentence_limit=False,
            )
            if not description:
                raise BrutalAssaultError(
                    f"description for album {album_id} is empty",
                    code="invalid_description",
                )
            prepared.append((album_id, description))
            seen_ids.add(album_id)

        self.initialize()
        placeholders = ", ".join("?" for _ in prepared)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, description FROM albums WHERE id IN ({placeholders})",
                [album_id for album_id, _ in prepared],
            ).fetchall()
            by_id = {row["id"]: row for row in rows}
            missing = [album_id for album_id, _ in prepared if album_id not in by_id]
            if missing:
                raise BrutalAssaultError(
                    f"albums not found: {', '.join(map(str, missing))}",
                    status=404,
                    code="album_not_found",
                )

            skipped = []
            updated_ids = []
            for album_id, description in prepared:
                if not overwrite and str(by_id[album_id]["description"] or "").strip():
                    skipped.append(album_id)
                    continue
                connection.execute(
                    "UPDATE albums SET description = ?, updated_at = ? WHERE id = ?",
                    (description, now, album_id),
                )
                updated_ids.append(album_id)

            updated_rows = []
            if updated_ids:
                updated_placeholders = ", ".join("?" for _ in updated_ids)
                updated_rows = connection.execute(
                    f"SELECT * FROM albums WHERE id IN ({updated_placeholders}) ORDER BY id",
                    updated_ids,
                ).fetchall()

        return {
            "updated": [self._row_payload(row) for row in updated_rows],
            "updatedCount": len(updated_ids),
            "skippedIds": skipped,
        }

    def update_community_rating(self, album_id, *, rating, votes, source, url):
        try:
            album_id = int(album_id)
        except (TypeError, ValueError) as exc:
            raise BrutalAssaultError("album id is required", code="invalid_album_id") from exc

        clean_rating = None if rating in (None, "") else float(rating)
        clean_votes = max(0, int(votes or 0))
        checked_at = datetime.now(timezone.utc).isoformat()
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE albums
                SET community_rating = ?, community_votes = ?, community_source = ?,
                    community_url = ?, community_checked_at = ?, updated_at = ?
                WHERE id = ? AND rym_rating IS NULL
                """,
                (
                    clean_rating,
                    clean_votes,
                    str(source or "").strip() or None,
                    str(url or "").strip() or None,
                    checked_at,
                    checked_at,
                    album_id,
                ),
            )
            row = connection.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
            if not row:
                raise BrutalAssaultError("Album not found", status=404, code="album_not_found")
        return self._row_payload(row)


BRUTAL_ASSAULT_2027_STORE = BrutalAssaultStore()
