"""SQLite persistence and validation for the reading dashboard."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
BOOK_SOURCES = {"owned", "library", "wanted"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ReadingError(ValueError):
    def __init__(self, message: str, *, status: int = 400, code: str = "reading_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self) -> dict:
        return {"error": str(self), "code": self.code}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_text(value, field: str, max_length: int, *, required: bool = False) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    if required and not text:
        raise ReadingError(f"{field} is required", code="validation_error")
    if len(text) > max_length:
        raise ReadingError(f"{field} is too long", status=413, code="payload_too_large")
    return text


def normalize_integer(value, field: str, *, minimum: int = 0, default=None) -> int | None:
    if value is None or value == "":
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ReadingError(f"{field} must be a number", code="validation_error") from exc
    if not math.isfinite(numeric):
        raise ReadingError(f"{field} must be a finite number", code="validation_error")
    result = round(numeric)
    if result < minimum:
        raise ReadingError(f"{field} must be at least {minimum}", code="validation_error")
    return result


def normalize_date(value, field: str, *, allow_empty: bool = True) -> str | None:
    raw = str(value or "").strip()
    if not raw and allow_empty:
        return None
    candidate = raw[:10] if len(raw) > 10 and raw[10:11] in {"T", " "} else raw
    if not DATE_PATTERN.fullmatch(candidate):
        raise ReadingError(f"{field} must be an ISO date", code="validation_error")
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError as exc:
        raise ReadingError(f"{field} must be an ISO date", code="validation_error") from exc


def slugify(value) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def safe_book_id(value, title="", author="") -> str:
    raw = str(value or "").strip()
    if raw and len(raw) <= 160 and re.fullmatch(r"[A-Za-z0-9._:-]+", raw):
        return raw
    base = slugify(" ".join(part for part in (title, author) if part))[:120]
    return base or f"book_{uuid.uuid4().hex}"


def normalize_source(value, return_date=None) -> str:
    source = str(value or "").strip().lower()
    aliases = {
        "wishlist": "wanted",
        "want": "wanted",
        "to-read": "wanted",
        "to_read": "wanted",
        "home": "owned",
    }
    source = aliases.get(source, source)
    if source in BOOK_SOURCES:
        return source
    return "library" if return_date else "owned"


def json_object(value, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ReadingError(f"{field} must be an object", code="validation_error")
    return value


class ClosingSQLiteConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3.Connection and release Windows file handles."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class ReadingStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10, factory=ClosingSQLiteConnection)
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
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS books (
                        id TEXT PRIMARY KEY,
                        legacy_row INTEGER,
                        title TEXT NOT NULL,
                        author TEXT NOT NULL,
                        pages_read INTEGER NOT NULL DEFAULT 0 CHECK (pages_read >= 0),
                        pages_total INTEGER NOT NULL DEFAULT 0 CHECK (pages_total >= 0),
                        source TEXT NOT NULL DEFAULT 'owned',
                        return_date TEXT,
                        remote_active INTEGER NOT NULL DEFAULT 1 CHECK (remote_active IN (0, 1)),
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_reading_books_legacy_row
                    ON books(legacy_row) WHERE legacy_row IS NOT NULL;
                    CREATE INDEX IF NOT EXISTS idx_reading_books_title_author
                    ON books(title COLLATE NOCASE, author COLLATE NOCASE);

                    CREATE TABLE IF NOT EXISTS reading_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        day TEXT NOT NULL,
                        book_key TEXT NOT NULL,
                        book_id TEXT REFERENCES books(id) ON UPDATE CASCADE ON DELETE SET NULL,
                        label TEXT NOT NULL,
                        title TEXT NOT NULL DEFAULT '',
                        author TEXT NOT NULL DEFAULT '',
                        pages INTEGER NOT NULL DEFAULT 0 CHECK (pages >= 0),
                        start_page INTEGER,
                        current_page INTEGER,
                        tracking_version INTEGER,
                        save_count INTEGER,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(day, book_key)
                    );
                    CREATE INDEX IF NOT EXISTS idx_reading_logs_day
                    ON reading_logs(day DESC);
                    CREATE INDEX IF NOT EXISTS idx_reading_logs_book
                    ON reading_logs(book_id, day DESC);

                    CREATE TABLE IF NOT EXISTS reading_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO reading_settings(key, value_json, updated_at) VALUES('schema.version', ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                    (json.dumps(SCHEMA_VERSION), utc_now()),
                )
            self._initialized = True

    @staticmethod
    def _days_to_return(return_date: str | None) -> int | None:
        if not return_date:
            return None
        try:
            return (date.fromisoformat(return_date) - date.today()).days
        except ValueError:
            return None

    @classmethod
    def _row_to_book(cls, row: sqlite3.Row) -> dict:
        total = int(row["pages_total"] or 0)
        read = int(row["pages_read"] or 0)
        percent = round((read / total) * 100) if total > 0 else 0
        due_days = cls._days_to_return(row["return_date"])
        metadata = json.loads(row["metadata_json"] or "{}")
        payload = {
            **metadata,
            "id": row["id"],
            "book_id": row["id"],
            "bookId": row["id"],
            "title": row["title"],
            "author": row["author"],
            "pagesRead": read,
            "pagesTotal": total,
            "pagesAll": total,
            "pagesLeft": max(0, total - read),
            "percent": percent,
            "completedPct": (read / total) if total > 0 else 0,
            "source": row["source"],
            "ownership": row["source"],
            "returnDate": row["return_date"],
            "dueDate": row["return_date"],
            "daysToReturn": due_days,
            "dueInDays": due_days,
            "remoteActive": bool(row["remote_active"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if row["legacy_row"] is not None:
            payload["row"] = row["legacy_row"]
            payload["row_id"] = row["legacy_row"]
        return payload

    @staticmethod
    def _book_identity_key(book: dict) -> str:
        title = unicodedata.normalize("NFC", str(book.get("title") or "")).strip().casefold()
        author = unicodedata.normalize("NFC", str(book.get("author") or "")).strip().casefold()
        return f"{title}|{author}" if title and author else title

    def count_books(self) -> int:
        self.initialize()
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM books").fetchone()[0])

    def list_books(self, *, active_only: bool = False) -> list[dict]:
        self.initialize()
        query = "SELECT * FROM books"
        params = ()
        if active_only:
            query += " WHERE remote_active = ?"
            params = (1,)
        query += " ORDER BY CASE WHEN legacy_row IS NULL THEN 1 ELSE 0 END, legacy_row, title COLLATE NOCASE"
        with self._connect() as connection:
            return [self._row_to_book(row) for row in connection.execute(query, params)]

    def get_book(self, book_id: str) -> dict:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM books WHERE id = ?", (str(book_id),)).fetchone()
        if not row:
            raise ReadingError("Book not found", status=404, code="book_not_found")
        return self._row_to_book(row)

    def _normalize_book(self, payload: dict, *, existing: sqlite3.Row | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ReadingError("Book must be an object", code="validation_error")
        base = dict(existing) if existing is not None else {}
        title = normalize_text(payload.get("title", base.get("title")), "title", 500, required=True)
        author = normalize_text(payload.get("author", base.get("author")), "author", 500, required=True)
        book_id = safe_book_id(
            payload.get("book_id") or payload.get("bookId") or payload.get("id") or base.get("id"),
            title,
            author,
        )
        pages_total = normalize_integer(
            payload.get("pagesTotal", payload.get("pagesAll", payload.get("page_total", base.get("pages_total", 0)))),
            "pagesTotal",
            default=0,
        )
        pages_read = normalize_integer(
            payload.get("pagesRead", payload.get("page_current", base.get("pages_read", 0))),
            "pagesRead",
            default=0,
        )
        if pages_total and pages_read > pages_total:
            raise ReadingError("pagesRead cannot exceed pagesTotal", code="validation_error")
        return_date = normalize_date(
            payload.get("returnDate", payload.get("dueDate", payload.get("return_date", base.get("return_date")))),
            "returnDate",
        )
        legacy_row = normalize_integer(
            payload.get("row", payload.get("row_id", base.get("legacy_row"))),
            "row",
            minimum=1,
            default=None,
        )
        source = normalize_source(
            payload.get("source", payload.get("ownership", base.get("source"))),
            return_date,
        )
        remote_active = payload.get("remoteActive", payload.get("remote_active", base.get("remote_active", True)))
        metadata = json_object(payload.get("metadata", {}), "metadata")
        return {
            "id": book_id,
            "legacy_row": legacy_row,
            "title": title,
            "author": author,
            "pages_read": pages_read,
            "pages_total": pages_total,
            "source": source,
            "return_date": return_date,
            "remote_active": 1 if bool(remote_active) else 0,
            "metadata_json": json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
        }

    def create_book(self, payload: dict) -> dict:
        self.initialize()
        normalized = self._normalize_book(payload)
        now = utc_now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO books(
                        id, legacy_row, title, author, pages_read, pages_total, source,
                        return_date, remote_active, metadata_json, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized["id"], normalized["legacy_row"], normalized["title"], normalized["author"],
                        normalized["pages_read"], normalized["pages_total"], normalized["source"],
                        normalized["return_date"], normalized["remote_active"], normalized["metadata_json"], now, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ReadingError("Book already exists", status=409, code="book_exists") from exc
        return self.get_book(normalized["id"])

    def update_book(self, book_id: str, payload: dict) -> dict:
        self.initialize()
        if not isinstance(payload, dict):
            raise ReadingError("Book must be an object", code="validation_error")
        stable_id = str(book_id)
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM books WHERE id = ?", (stable_id,)).fetchone()
            if not row:
                raise ReadingError("Book not found", status=404, code="book_not_found")
            normalized = self._normalize_book({
                **payload,
                "book_id": stable_id,
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }, existing=row)
            connection.execute(
                """
                UPDATE books
                SET legacy_row = ?, title = ?, author = ?, pages_read = ?, pages_total = ?,
                    source = ?, return_date = ?, remote_active = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized["legacy_row"], normalized["title"], normalized["author"],
                    normalized["pages_read"], normalized["pages_total"], normalized["source"],
                    normalized["return_date"], normalized["remote_active"],
                    normalized["metadata_json"], now, stable_id,
                ),
            )
        return self.get_book(stable_id)

    def update_progress(
        self,
        book_id: str,
        page_current,
        *,
        record_history: bool = True,
        day: str | None = None,
    ) -> dict:
        self.initialize()
        page = normalize_integer(page_current, "pageCurrent", default=0)
        day_key = normalize_date(day or date.today().isoformat(), "day", allow_empty=False)
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM books WHERE id = ?", (str(book_id),)).fetchone()
            if not row:
                raise ReadingError("Book not found", status=404, code="book_not_found")
            total = int(row["pages_total"] or 0)
            if total > 0 and page > total:
                raise ReadingError("pageCurrent cannot exceed pagesTotal", code="validation_error")
            previous = int(row["pages_read"] or 0)
            connection.execute(
                "UPDATE books SET pages_read = ?, updated_at = ? WHERE id = ?",
                (page, now, str(book_id)),
            )
            if record_history and page > previous:
                self._record_progress_row(connection, row, previous, page, day_key, now)
        book = self.get_book(str(book_id))
        return {
            "ok": True,
            "book_id": book["book_id"],
            "page_current": book["pagesRead"],
            "percent": book["percent"],
            "previous_page": previous,
            "book": book,
        }

    def _record_progress_row(self, connection, book_row, previous: int, current: int, day_key: str, now: str):
        book_key = f"remote:{book_row['id']}"
        label = f"{book_row['title']} - {book_row['author']}"
        existing = connection.execute(
            "SELECT * FROM reading_logs WHERE day = ? AND book_key = ?",
            (day_key, book_key),
        ).fetchone()
        if existing:
            start_page = existing["start_page"] if existing["start_page"] is not None else previous
            next_current = max(int(existing["current_page"] or 0), current)
            pages = max(0, next_current - int(start_page))
            connection.execute(
                """
                UPDATE reading_logs
                SET pages = ?, current_page = ?, tracking_version = 2,
                    save_count = COALESCE(save_count, 0) + 1, updated_at = ?
                WHERE id = ?
                """,
                (pages, next_current, now, existing["id"]),
            )
            return
        connection.execute(
            """
            INSERT INTO reading_logs(
                day, book_key, book_id, label, title, author, pages,
                start_page, current_page, tracking_version, save_count,
                metadata_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 2, 1, '{}', ?, ?)
            """,
            (
                day_key, book_key, book_row["id"], label, book_row["title"], book_row["author"],
                current - previous, previous, current, now, now,
            ),
        )

    def _setting(self, connection, key: str, default=None):
        row = connection.execute("SELECT value_json FROM reading_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default

    def _set_setting(self, connection, key: str, value, now: str | None = None):
        timestamp = now or utc_now()
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            """
            INSERT INTO reading_settings(key, value_json, updated_at) VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (key, encoded, timestamp),
        )

    def get_settings(self) -> dict:
        self.initialize()
        with self._connect() as connection:
            value = self._setting(connection, "dashboard.settings", {})
        return value if isinstance(value, dict) else {}

    def replace_settings(self, payload: dict) -> dict:
        settings = json_object(payload, "settings")
        now = utc_now()
        normalized = {**settings, "updatedAt": settings.get("updatedAt") or int(datetime.now().timestamp() * 1000)}
        self.initialize()
        with self._connect() as connection:
            self._set_setting(connection, "dashboard.settings", normalized, now)
        return normalized

    @staticmethod
    def _history_identity(label: str, progress: dict | None = None) -> tuple[str, str, str, str | None]:
        progress = progress or {}
        key = str(progress.get("bookKey") or progress.get("key") or "").strip()
        title = str(progress.get("title") or "").strip()
        author = str(progress.get("author") or "").strip()
        remote_id = str(progress.get("bookId") or progress.get("book_id") or "").strip() or None
        if not title and " - " in label:
            title, author_from_label = label.rsplit(" - ", 1)
            author = author or author_from_label
        if not key:
            key = f"label:{unicodedata.normalize('NFC', str(label)).strip().casefold()}"
        if not remote_id and key.startswith("remote:"):
            remote_id = key.removeprefix("remote:")
        return key, title, author, remote_id

    def history(self) -> dict:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM reading_logs ORDER BY day, id").fetchall()
            start_key = self._setting(connection, "history.start_key", "")
            forecast_plan = self._setting(connection, "history.forecast_plan", None)
        log = {}
        for row in rows:
            entry = log.setdefault(row["day"], {"total": 0, "books": {}, "progress": {}})
            pages = int(row["pages"] or 0)
            entry["books"][row["label"]] = entry["books"].get(row["label"], 0) + pages
            entry["total"] += pages
            if row["start_page"] is not None and row["current_page"] is not None:
                progress = {
                    "key": row["book_key"],
                    "label": row["label"],
                    "title": row["title"],
                    "author": row["author"],
                    "start": row["start_page"],
                    "current": row["current_page"],
                    "trackingVersion": row["tracking_version"],
                    "saveCount": row["save_count"],
                }
                entry["progress"][row["book_key"]] = progress
        return {"log": log, "startKey": start_key or "", "forecastPlan": forecast_plan}

    def replace_history(self, payload: dict) -> dict:
        self.initialize()
        with self._connect() as connection:
            self._replace_history_in_connection(connection, payload)
        return self.history()

    def _replace_history_in_connection(self, connection, payload: dict) -> None:
        history = json_object(payload, "history")
        raw_log = json_object(history.get("log", {}), "history.log")
        start_key = normalize_date(history.get("startKey"), "startKey") if history.get("startKey") else ""
        forecast_plan = history.get("forecastPlan")
        if forecast_plan is not None and not isinstance(forecast_plan, dict):
            raise ReadingError("forecastPlan must be an object or null", code="validation_error")
        now = utc_now()
        connection.execute("DELETE FROM reading_logs")
        for day_key, raw_entry in sorted(raw_log.items()):
            day_value = normalize_date(day_key, "history day", allow_empty=False)
            entry = json_object(raw_entry, "history entry")
            books = json_object(entry.get("books", {}), "history books")
            progress_map = json_object(entry.get("progress", {}), "history progress")
            if not books and normalize_integer(entry.get("total"), "history total", default=0):
                books = {"Nieznana książka": normalize_integer(entry.get("total"), "history total", default=0)}
            used_progress = set()
            for label, raw_pages in books.items():
                pages = normalize_integer(raw_pages, "history pages", default=0)
                if pages <= 0:
                    continue
                progress_key = next(
                    (
                        key for key, value in progress_map.items()
                        if key not in used_progress and str(value.get("label") or "").strip() == str(label).strip()
                    ),
                    None,
                )
                progress = progress_map.get(progress_key, {}) if progress_key else {}
                key, title, author, remote_id = self._history_identity(str(label), progress)
                used_progress.add(progress_key) if progress_key else None
                connection.execute(
                    """
                    INSERT INTO reading_logs(
                        day, book_key, book_id, label, title, author, pages,
                        start_page, current_page, tracking_version, save_count,
                        metadata_json, created_at, updated_at
                    ) VALUES(?, ?, (SELECT id FROM books WHERE id = ?), ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                    """,
                    (
                        day_value, key, remote_id, str(label), title, author, pages,
                        normalize_integer(progress.get("start"), "progress start", default=None),
                        normalize_integer(progress.get("current"), "progress current", default=None),
                        normalize_integer(progress.get("trackingVersion"), "trackingVersion", minimum=1, default=None),
                        normalize_integer(progress.get("saveCount"), "saveCount", default=None),
                        now, now,
                    ),
                )
            for progress_key, progress in progress_map.items():
                if progress_key in used_progress:
                    continue
                key, title, author, remote_id = self._history_identity(
                    str(progress.get("label") or progress_key), progress,
                )
                start_page = normalize_integer(progress.get("start"), "progress start", default=None)
                current_page = normalize_integer(progress.get("current"), "progress current", default=None)
                pages = max(0, (current_page or 0) - (start_page or 0))
                if pages <= 0:
                    continue
                label = str(progress.get("label") or progress_key)
                connection.execute(
                    """
                    INSERT INTO reading_logs(
                        day, book_key, book_id, label, title, author, pages,
                        start_page, current_page, tracking_version, save_count,
                        metadata_json, created_at, updated_at
                    ) VALUES(?, ?, (SELECT id FROM books WHERE id = ?), ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                    """,
                    (
                        day_value, key, remote_id, label, title, author, pages, start_page, current_page,
                        normalize_integer(progress.get("trackingVersion"), "trackingVersion", minimum=1, default=None),
                        normalize_integer(progress.get("saveCount"), "saveCount", default=None), now, now,
                    ),
                )
        self._set_setting(connection, "history.start_key", start_key, now)
        self._set_setting(connection, "history.forecast_plan", forecast_plan, now)

    def daily_stats(self) -> dict:
        history = self.history()
        today = date.today()
        start_key = history.get("startKey") or today.isoformat()
        try:
            start_day = date.fromisoformat(start_key)
        except ValueError:
            start_day = today
        days_since_start = max(1, (today - start_day).days + 1)
        window_days = min(7, days_since_start)
        totals = {key: int(value.get("total") or 0) for key, value in history["log"].items()}
        recent_total = sum(totals.get((today.fromordinal(today.toordinal() - offset)).isoformat(), 0) for offset in range(window_days))
        streak = 0
        for offset in range(days_since_start):
            key = today.fromordinal(today.toordinal() - offset).isoformat()
            if totals.get(key, 0) <= 0:
                break
            streak += 1
        today_read = totals.get(today.isoformat(), 0)
        return {
            "todayRead": today_read,
            "avgPerDay7d": round(recent_total / window_days),
            "avgPagesPerDay": round(recent_total / window_days),
            "streakDays": streak,
        }

    def _library_target(self, books: list[dict], settings: dict) -> int:
        active_map = settings.get("activeMap") if isinstance(settings.get("activeMap"), dict) else {}
        ownership_map = settings.get("ownershipMap") if isinstance(settings.get("ownershipMap"), dict) else {}
        total_target = 0
        today_value = date.today()
        for book in books:
            source_key = f"remote:{book['id']}"
            if active_map.get(source_key) is False:
                continue
            ownership = ownership_map.get(source_key, book.get("source"))
            if ownership != "library" or not book.get("returnDate"):
                continue
            remaining = max(0, int(book.get("pagesTotal") or 0) - int(book.get("pagesRead") or 0))
            if remaining <= 0:
                continue
            days = max(1, (date.fromisoformat(book["returnDate"]) - today_value).days)
            total_target += math.ceil(remaining / days)
        return total_target

    def state(self) -> dict:
        books = self.list_books()
        active_books = [book for book in books if book.get("remoteActive")]
        settings = self.get_settings()
        daily_stats = self.daily_stats()
        today_target = self._library_target(books, settings)
        daily_stats.update({
            "todayTarget": today_target,
            "pagesLeftToday": max(0, today_target - daily_stats["todayRead"]),
        })
        selected_id = str((settings.get("selectedBook") or {}).get("remoteId") or "")
        current_index = next((index for index, book in enumerate(active_books) if book["id"] == selected_id), 0)
        next_returns = [book for book in books if book.get("returnDate") and book.get("pagesRead", 0) < book.get("pagesTotal", 0)]
        next_returns.sort(key=lambda book: book["returnDate"])
        stats = {
            "updated": date.today().isoformat(),
            "booksActive": len(active_books),
            "avgPagesPerDay": daily_stats["avgPerDay7d"],
            "pagesLeftAll": sum(max(0, book["pagesTotal"] - book["pagesRead"]) for book in books),
            "nextReturnDate": next_returns[0]["returnDate"] if next_returns else None,
            "nextReturnInDays": next_returns[0]["daysToReturn"] if next_returns else None,
        }
        return {
            "books": books,
            "activeBooks": active_books,
            "currentIndex": current_index,
            "dailyStats": daily_stats,
            "stats": stats,
            "settings": settings,
        }

    def import_initial(self, primary: dict, remote_state: dict, history: dict, settings: dict) -> dict:
        """Import legacy sources into an empty store in one transaction."""
        self.initialize()
        primary_books = primary.get("books") if isinstance(primary, dict) else []
        remote_books = remote_state.get("activeBooks") if isinstance(remote_state, dict) else []
        primary_books = primary_books if isinstance(primary_books, list) else []
        remote_books = remote_books if isinstance(remote_books, list) else []
        remote_by_identity = {
            self._book_identity_key(book): book for book in remote_books if self._book_identity_key(book)
        }
        seen_remote = set()
        now = utc_now()
        with self._connect() as connection:
            has_books = connection.execute("SELECT 1 FROM books LIMIT 1").fetchone()
            has_history = connection.execute("SELECT 1 FROM reading_logs LIMIT 1").fetchone()
            if has_books or has_history:
                raise ReadingError(
                    "Reading database is not empty; refusing to overwrite it",
                    status=409,
                    code="database_not_empty",
                )
            for index, primary_book in enumerate(primary_books, start=1):
                identity = self._book_identity_key(primary_book)
                remote = remote_by_identity.get(identity)
                if remote:
                    seen_remote.add(identity)
                merged = {**primary_book, **(remote or {})}
                legacy_row = primary_book.get("row") or index
                book_id = (
                    (remote or {}).get("book_id")
                    or (remote or {}).get("bookId")
                    or (remote or {}).get("id")
                    or f"legacy_row_{legacy_row}"
                )
                return_date = merged.get("dueDate") or merged.get("returnDate")
                normalized = self._normalize_book({
                    **merged,
                    "book_id": book_id,
                    "row": legacy_row,
                    "source": (settings.get("ownershipMap") or {}).get(f"remote:{book_id}") or merged.get("source"),
                    "remoteActive": bool(remote),
                    "metadata": {"primary": primary_book, "remoteState": remote} if remote else {"primary": primary_book},
                    "returnDate": return_date,
                })
                connection.execute(
                    """
                    INSERT INTO books(
                        id, legacy_row, title, author, pages_read, pages_total, source,
                        return_date, remote_active, metadata_json, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized["id"], normalized["legacy_row"], normalized["title"], normalized["author"],
                        normalized["pages_read"], normalized["pages_total"], normalized["source"],
                        normalized["return_date"], normalized["remote_active"], normalized["metadata_json"], now, now,
                    ),
                )
            for remote in remote_books:
                identity = self._book_identity_key(remote)
                if identity in seen_remote:
                    continue
                normalized = self._normalize_book({
                    **remote,
                    "source": (settings.get("ownershipMap") or {}).get(f"remote:{remote.get('book_id')}") or remote.get("source"),
                    "remoteActive": True,
                    "metadata": {"remoteState": remote},
                })
                connection.execute(
                    """
                    INSERT INTO books(
                        id, legacy_row, title, author, pages_read, pages_total, source,
                        return_date, remote_active, metadata_json, created_at, updated_at
                    ) VALUES(?, NULL, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        normalized["id"], normalized["title"], normalized["author"], normalized["pages_read"],
                        normalized["pages_total"], normalized["source"], normalized["return_date"],
                        normalized["metadata_json"], now, now,
                    ),
                )
            self._set_setting(connection, "dashboard.settings", settings, now)
            self._set_setting(connection, "import.primary_snapshot", primary, now)
            self._set_setting(connection, "import.remote_state_snapshot", remote_state, now)
            self._set_setting(connection, "import.completed_at", now, now)
            self._replace_history_in_connection(connection, history)
        return {
            "ok": True,
            "books": self.count_books(),
            "activeBooks": len(self.list_books(active_only=True)),
            "historyDays": len(self.history()["log"]),
            "historyPages": sum(entry["total"] for entry in self.history()["log"].values()),
        }


READING_STORE = ReadingStore(Path(__file__).resolve().parent / "data" / "reading.sqlite")
