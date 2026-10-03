import math
import re
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path


class Bm365Error(ValueError):
    def __init__(self, message, *, status=400, code="invalid_album"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self):
        return {"error": str(self), "code": self.code}


def _identity_part(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _identity_key(artist, album):
    return _identity_part(artist), _identity_part(album)


class Bm365Store:
    def __init__(self, db_path=None):
        root = Path(__file__).resolve().parent
        self.db_path = Path(db_path or root / "data" / "bm365.sqlite")
        self._init_lock = threading.Lock()
        self._initialized = False
        self._connection_lock = threading.RLock()
        self._connection = None
        self._cross_cache_lock = threading.Lock()
        self._cross_rating_targets = None

    @contextmanager
    def _connect(self):
        with self._connection_lock:
            if self._connection is None:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(
                    self.db_path,
                    timeout=15,
                    check_same_thread=False,
                )
                self._connection.row_factory = sqlite3.Row
                self._connection.execute("PRAGMA foreign_keys = ON")
                self._connection.execute("PRAGMA busy_timeout = 15000")
                self._connection.execute("PRAGMA synchronous = NORMAL")
            try:
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self):
        with self._connection_lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def invalidate_cross_cache(self):
        with self._cross_cache_lock:
            self._cross_rating_targets = None

    def initialize(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS albums (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        row_id INTEGER UNIQUE,
                        planned_date TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        album TEXT NOT NULL,
                        release_year INTEGER,
                        listened INTEGER NOT NULL DEFAULT 0 CHECK(listened IN (0, 1)),
                        rating REAL CHECK(rating IS NULL OR (rating >= 0.5 AND rating <= 5.0)),
                        minutes INTEGER,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_bm365_albums_date
                        ON albums(planned_date, row_id);
                    CREATE INDEX IF NOT EXISTS idx_bm365_albums_identity
                        ON albums(artist COLLATE NOCASE, album COLLATE NOCASE);
                    CREATE INDEX IF NOT EXISTS idx_bm365_albums_rating
                        ON albums(rating DESC) WHERE rating IS NOT NULL;

                    CREATE TABLE IF NOT EXISTS sheets_sync_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT NOT NULL CHECK(action IN ('mark', 'rate')),
                        row_id INTEGER,
                        planned_date TEXT,
                        rating REAL,
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending', 'synced', 'failed')),
                        attempts INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        synced_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_bm365_sync_queue_status
                        ON sheets_sync_queue(status, id);

                    CREATE TABLE IF NOT EXISTS bm365_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
            self._initialized = True

    @staticmethod
    def _parse_date(value):
        try:
            return date.fromisoformat(str(value or "").strip()).isoformat()
        except ValueError as exc:
            raise Bm365Error("date must use YYYY-MM-DD", code="invalid_date") from exc

    @staticmethod
    def _parse_row_id(value):
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise Bm365Error("album id must be a positive integer", code="invalid_album_id") from exc
        if parsed <= 0:
            raise Bm365Error("album id must be a positive integer", code="invalid_album_id")
        return parsed

    @staticmethod
    def _parse_year(value):
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise Bm365Error("year must be a number", code="invalid_year") from exc
        if parsed < 1900 or parsed > 2100:
            raise Bm365Error("year must be between 1900 and 2100", code="invalid_year")
        return parsed

    @staticmethod
    def _parse_rating(value):
        if value in (None, ""):
            return None
        try:
            parsed = float(str(value).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise Bm365Error("rating must be a number", code="invalid_rating") from exc
        if not math.isfinite(parsed) or parsed < 0.5 or parsed > 5 or parsed * 2 != int(parsed * 2):
            raise Bm365Error(
                "rating must be between 0.5 and 5.0 in 0.5 steps",
                code="invalid_rating",
            )
        return parsed

    @staticmethod
    def _parse_minutes(value):
        if value in (None, ""):
            return None
        try:
            parsed = int(float(str(value).replace(",", ".")))
        except (TypeError, ValueError) as exc:
            raise Bm365Error("minutes must be a number", code="invalid_minutes") from exc
        if parsed < 0 or parsed > 1440:
            raise Bm365Error("minutes must be between 0 and 1440", code="invalid_minutes")
        return parsed

    @staticmethod
    def _parse_listened(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value or "").strip().upper() in {"TAK", "TRUE", "YES", "1"}

    @staticmethod
    def _parse_description(value):
        clean = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(clean) > 4000:
            raise Bm365Error(
                "description must be at most 4000 characters",
                code="invalid_description",
            )
        return clean

    @staticmethod
    def _row_payload(row):
        return {
            "rowId": row["row_id"],
            "date": row["planned_date"],
            "artist": row["artist"],
            "album": row["album"],
            "year": str(row["release_year"]) if row["release_year"] else "",
            "releaseYear": row["release_year"],
            "listened": "TAK" if row["listened"] else "",
            "rating": row["rating"],
            "minutes": row["minutes"],
            "description": row["description"] or "",
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _find_row(self, connection, date_or_row_id):
        row_id = None
        planned_date = None
        if isinstance(date_or_row_id, dict):
            row_id = date_or_row_id.get("rowId", date_or_row_id.get("id"))
            planned_date = date_or_row_id.get("date", date_or_row_id.get("plannedDate"))
        elif isinstance(date_or_row_id, int) or str(date_or_row_id or "").strip().isdigit():
            row_id = date_or_row_id
        else:
            planned_date = date_or_row_id

        if row_id not in (None, ""):
            row = connection.execute(
                "SELECT * FROM albums WHERE row_id = ?", (self._parse_row_id(row_id),)
            ).fetchone()
        elif planned_date:
            row = connection.execute(
                "SELECT * FROM albums WHERE planned_date = ?", (self._parse_date(planned_date),)
            ).fetchone()
        else:
            raise Bm365Error("rowId or date is required", code="missing_album_target")
        if not row:
            raise Bm365Error("Album not found", status=404, code="album_not_found")
        return row

    @staticmethod
    def _queue(connection, action, row, *, rating=None):
        connection.execute(
            """
            INSERT INTO sheets_sync_queue (
                action, row_id, planned_date, rating, status, attempts, created_at
            ) VALUES (?, ?, ?, ?, 'pending', 0, ?)
            """,
            (
                action,
                row["row_id"],
                row["planned_date"],
                rating,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def count(self):
        self.initialize()
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM albums").fetchone()[0])

    def get(self, row_id):
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM albums WHERE row_id = ?", (self._parse_row_id(row_id),)
            ).fetchone()
        return self._row_payload(row) if row else None

    def _cross_lists(self, rows):
        with self._cross_cache_lock:
            targets = self._cross_rating_targets
        if targets is None:
            try:
                from brutal_assault_store import BRUTAL_ASSAULT_2027_STORE
                from rym_polish_black_metal_store import RYM_POLISH_BLACK_METAL_STORE

                ba_rows = BRUTAL_ASSAULT_2027_STORE.list()
                rym_rows = RYM_POLISH_BLACK_METAL_STORE.list()
            except Exception:
                return rows
            ba_by_key = {_identity_key(row.get("artist"), row.get("album")): row for row in ba_rows}
            rym_by_key = {_identity_key(row.get("artist"), row.get("album")): row for row in rym_rows}
            targets = (
                (BRUTAL_ASSAULT_2027_STORE, ba_by_key),
                (RYM_POLISH_BLACK_METAL_STORE, rym_by_key),
            )
            with self._cross_cache_lock:
                self._cross_rating_targets = targets
        else:
            ba_by_key = targets[0][1]
            rym_by_key = targets[1][1]
        for row in rows:
            key = _identity_key(row.get("artist"), row.get("album"))
            cross_lists = []
            ba_row = ba_by_key.get(key)
            if ba_row:
                cross_lists.append({
                    "key": "brutal-assault-2027",
                    "label": "Brutal Assault 2027",
                    "rowId": ba_row.get("rowId"),
                    "date": ba_row.get("date"),
                    "rating": ba_row.get("rating"),
                })
            rym_row = rym_by_key.get(key)
            if rym_row:
                cross_lists.append({
                    "key": "rym-polish-black-metal-top-100",
                    "label": "Top 100 RYM Polish BM",
                    "rowId": rym_row.get("rowId"),
                    "rank": rym_row.get("sourceRank"),
                    "rating": rym_row.get("rating"),
                })
            if cross_lists:
                row["crossLists"] = cross_lists
                row["crossList"] = cross_lists[0]
        return rows

    def get_albums(self, filters=None):
        self.initialize()
        filters = filters if isinstance(filters, dict) else {}
        where = []
        values = []
        if filters.get("listened") not in (None, ""):
            where.append("listened = ?")
            values.append(int(self._parse_listened(filters["listened"])))
        if filters.get("rated") not in (None, ""):
            where.append("rating IS NOT NULL" if self._parse_listened(filters["rated"]) else "rating IS NULL")
        if filters.get("year") not in (None, "", "ALL"):
            where.append("release_year = ?")
            values.append(self._parse_year(filters["year"]))
        search = str(filters.get("search") or filters.get("q") or "").strip()
        if search:
            where.append("(artist LIKE ? COLLATE NOCASE OR album LIKE ? COLLATE NOCASE)")
            values.extend([f"%{search}%", f"%{search}%"])

        sort_sql = {
            "date_desc": "planned_date DESC, row_id DESC",
            "rating_desc": "rating IS NULL, rating DESC, planned_date ASC",
            "artist_asc": "artist COLLATE NOCASE ASC, album COLLATE NOCASE ASC",
            "year_desc": "release_year IS NULL, release_year DESC, planned_date ASC",
        }.get(str(filters.get("sort") or "date_asc"), "planned_date ASC, row_id ASC")
        sql = "SELECT * FROM albums"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {sort_sql}"
        with self._connect() as connection:
            db_rows = connection.execute(sql, values).fetchall()
        return self._cross_lists([self._row_payload(row) for row in db_rows])

    def snapshot(self, filters=None):
        rows = self.get_albums(filters)
        return {
            "ok": True,
            "rows": rows,
            "count": len(rows),
            "storedPath": self.db_path.as_posix(),
        }

    @staticmethod
    def _stats(rows):
        total = len(rows)
        done = sum(1 for row in rows if row.get("listened") == "TAK")
        rated = [float(row["rating"]) for row in rows if row.get("rating") is not None]
        minute_rows = [int(row["minutes"]) for row in rows if row.get("listened") == "TAK" and row.get("minutes") is not None]
        return {
            "total": total,
            "done": done,
            "left": max(0, total - done),
            "pct": round((done / total) * 100) if total else 0,
            "avgRating": sum(rated) / len(rated) if rated else None,
            "ratedCount": len(rated),
            "totalMinutes": sum(minute_rows),
            "timeCount": len(minute_rows),
        }

    def get_state(self, today=None):
        today = self._parse_date(today or date.today().isoformat())
        rows = self.get_albums()
        stats = self._stats(rows)
        album_today = next((row for row in rows if row.get("date") == today), None)
        catch_up = [row for row in rows if row.get("date", "") <= today and row.get("listened") != "TAK"]
        recently_rated = sorted(
            (row for row in rows if row.get("rating") is not None),
            key=lambda row: (row.get("updatedAt") or "", row.get("date") or ""),
            reverse=True,
        )[:5]
        return {
            "ok": True,
            "today": today,
            "albumToday": album_today,
            "stats": stats,
            "catchUp": catch_up,
            "recentlyRated": recently_rated,
            "rows": rows,
        }

    def get_summary(self):
        rows = self.get_albums()
        rated = sorted(
            (row for row in rows if row.get("rating") is not None),
            key=lambda row: (-float(row["rating"]), row.get("date") or ""),
        )
        return {
            "ok": True,
            "stats": self._stats(rows),
            "topRated": rated[:10],
            "rows": rows,
        }

    def mark_listened(self, date_or_row_id, listened=True):
        self.initialize()
        listened = self._parse_listened(listened)
        with self._connect() as connection:
            existing = self._find_row(connection, date_or_row_id)
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE albums SET listened = ?, updated_at = ? WHERE id = ?",
                (int(listened), now, existing["id"]),
            )
            updated = connection.execute("SELECT * FROM albums WHERE id = ?", (existing["id"],)).fetchone()
            if bool(existing["listened"]) != listened:
                self._queue(connection, "mark", updated)
        return self._row_payload(updated)

    def rate_album(self, date_or_row_id, rating, *, propagate=True):
        self.initialize()
        rating = self._parse_rating(rating)
        if rating is None:
            raise Bm365Error("rating is required", code="invalid_rating")
        with self._connect() as connection:
            existing = self._find_row(connection, date_or_row_id)
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE albums SET rating = ?, listened = 1, updated_at = ? WHERE id = ?",
                (rating, now, existing["id"]),
            )
            updated = connection.execute("SELECT * FROM albums WHERE id = ?", (existing["id"],)).fetchone()
            if existing["rating"] != rating:
                self._queue(connection, "rate", updated, rating=rating)
        payload = self._row_payload(updated)
        if propagate:
            try:
                self._propagate_rating(payload, rating)
            except Exception as exc:
                payload["crossListError"] = str(exc)
        return payload

    def _propagate_rating(self, album, rating):
        from brutal_assault_store import BRUTAL_ASSAULT_2027_STORE
        from rym_polish_black_metal_store import RYM_POLISH_BLACK_METAL_STORE

        key = _identity_key(album.get("artist"), album.get("album"))
        with self._cross_cache_lock:
            targets = self._cross_rating_targets
        if targets is None:
            targets = (
                (BRUTAL_ASSAULT_2027_STORE, {
                    _identity_key(row.get("artist"), row.get("album")): row
                    for row in BRUTAL_ASSAULT_2027_STORE.list()
                }),
                (RYM_POLISH_BLACK_METAL_STORE, {
                    _identity_key(row.get("artist"), row.get("album")): row
                    for row in RYM_POLISH_BLACK_METAL_STORE.list()
                }),
            )
            with self._cross_cache_lock:
                self._cross_rating_targets = targets
        for store, rows_by_key in targets:
            match = rows_by_key.get(key)
            if match and match.get("rating") != rating:
                updated = store.update(match.get("rowId"), {"rating": rating})
                rows_by_key[key] = updated

    def update_metadata(self, row_id, year=None, description=None):
        self.initialize()
        assignments = []
        values = []
        if year is not None:
            assignments.append("release_year = ?")
            values.append(self._parse_year(year))
        if description is not None:
            assignments.append("description = ?")
            values.append(self._parse_description(description))
        if not assignments:
            raise Bm365Error("No supported fields to update", code="empty_update")
        assignments.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(self._parse_row_id(row_id))
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE albums SET {', '.join(assignments)} WHERE row_id = ?", values
            )
            if cursor.rowcount != 1:
                raise Bm365Error("Album not found", status=404, code="album_not_found")
            row = connection.execute("SELECT * FROM albums WHERE row_id = ?", (values[-1],)).fetchone()
        return self._row_payload(row)

    def bulk_update_descriptions(self, descriptions, *, overwrite=False):
        if not isinstance(descriptions, dict) or not descriptions:
            raise Bm365Error("descriptions must be a non-empty object", code="invalid_descriptions")
        if len(descriptions) > 50:
            raise Bm365Error("a single import can contain at most 50 descriptions", code="too_many_descriptions")
        prepared = [(self._parse_row_id(row_id), self._parse_description(value)) for row_id, value in descriptions.items()]
        now = datetime.now(timezone.utc).isoformat()
        updated_ids = []
        skipped_ids = []
        with self._connect() as connection:
            for row_id, description in prepared:
                row = connection.execute("SELECT description FROM albums WHERE row_id = ?", (row_id,)).fetchone()
                if not row:
                    raise Bm365Error(f"album not found: {row_id}", status=404, code="album_not_found")
                if not overwrite and str(row["description"] or "").strip():
                    skipped_ids.append(row_id)
                    continue
                connection.execute(
                    "UPDATE albums SET description = ?, updated_at = ? WHERE row_id = ?",
                    (description, now, row_id),
                )
                updated_ids.append(row_id)
        updated = [self.get(row_id) for row_id in updated_ids]
        return {"updated": updated, "updatedCount": len(updated), "skippedIds": skipped_ids}

    def replace_all(self, albums, *, expected_count=365):
        albums = list(albums or [])
        if expected_count is not None and len(albums) != expected_count:
            raise Bm365Error(
                f"BM365 import requires exactly {expected_count} albums (got {len(albums)})",
                code="invalid_album_count",
            )
        now = datetime.now(timezone.utc).isoformat()
        prepared = []
        seen_row_ids = set()
        seen_dates = set()
        for item in albums:
            row_id = self._parse_row_id(item.get("rowId"))
            planned_date = self._parse_date(item.get("date"))
            if row_id in seen_row_ids or planned_date in seen_dates:
                raise Bm365Error("row ids and dates must be unique", code="duplicate_album")
            artist = str(item.get("artist") or "").strip()
            album = str(item.get("album") or "").strip()
            if not artist or not album:
                raise Bm365Error("artist and album are required", code="missing_identity")
            rating = self._parse_rating(item.get("rating"))
            prepared.append((
                row_id,
                planned_date,
                artist,
                album,
                self._parse_year(item.get("year", item.get("releaseYear"))),
                int(self._parse_listened(item.get("listened")) or rating is not None),
                rating,
                self._parse_minutes(item.get("minutes")),
                self._parse_description(item.get("description")),
                str(item.get("createdAt") or now),
                now,
            ))
            seen_row_ids.add(row_id)
            seen_dates.add(planned_date)

        self.initialize()
        with self._connect() as connection:
            connection.execute("DELETE FROM albums")
            connection.executemany(
                """
                INSERT INTO albums (
                    row_id, planned_date, artist, album, release_year, listened,
                    rating, minutes, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                prepared,
            )
            count = int(connection.execute("SELECT COUNT(*) FROM albums").fetchone()[0])
            if expected_count is not None and count != expected_count:
                raise Bm365Error("BM365 import verification failed", code="invalid_album_count")
        return count

    def pending_sync_tasks(self, *, limit=20, include_failed=True):
        self.initialize()
        statuses = ("pending", "failed") if include_failed else ("pending",)
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM sheets_sync_queue WHERE status IN ({placeholders}) ORDER BY id LIMIT ?",
                (*statuses, max(1, min(int(limit), 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def finish_sync_task(self, task_id, *, error=None):
        self.initialize()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            if error:
                connection.execute(
                    """
                    UPDATE sheets_sync_queue
                    SET status = 'failed', attempts = attempts + 1, last_error = ?, synced_at = NULL
                    WHERE id = ?
                    """,
                    (str(error)[:1000], int(task_id)),
                )
            else:
                connection.execute(
                    """
                    UPDATE sheets_sync_queue
                    SET status = 'synced', attempts = attempts + 1, last_error = NULL, synced_at = ?
                    WHERE id = ?
                    """,
                    (now, int(task_id)),
                )

    def sync_queue_stats(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM sheets_sync_queue GROUP BY status"
            ).fetchall()
        result = {"pending": 0, "synced": 0, "failed": 0}
        result.update({row["status"]: int(row["count"]) for row in rows})
        return result


BM365_STORE = Bm365Store()
