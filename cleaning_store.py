from __future__ import annotations

import json
import hashlib
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = Path(os.environ.get("CLEANING_DB_PATH") or (ROOT / "data" / "cleaning.sqlite"))
WARSAW = ZoneInfo("Europe/Warsaw")
VALID_RANGES = {"week", "month", "year", "all"}
VALID_SOURCES = {"cleaning-page", "cleaning-widget", "android", "migration"}


class CleaningError(ValueError):
    def __init__(self, message: str, *, status: int = 400, code: str = "invalid_cleaning_request"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self) -> dict[str, Any]:
        return {"error": str(self), "code": self.code}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_datetime(value: Any, *, field: str = "date") -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip()
    if len(raw) == 10:
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=WARSAW)
        except ValueError as exc:
            raise CleaningError(f"{field} must be an ISO date or datetime", code="invalid_date") from exc
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CleaningError(f"{field} must be an ISO date or datetime", code="invalid_date") from exc
    return parsed.replace(tzinfo=WARSAW) if parsed.tzinfo is None else parsed


def _canonical_datetime(value: Any, *, field: str = "date") -> str | None:
    parsed = _parse_datetime(value, field=field)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _required_text(value: Any, field: str, *, max_length: int = 500) -> str:
    text = str(value or "").strip()
    if not text:
        raise CleaningError(f"{field} is required", code=f"missing_{field}")
    if len(text) > max_length:
        raise CleaningError(f"{field} is too long", code=f"invalid_{field}")
    return text


def _optional_text(value: Any, *, max_length: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise CleaningError("Text value is too long", code="text_too_long")
    return text


def _frequency(value: Any) -> float:
    try:
        result = float(str(value).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise CleaningError("freq must be a positive number", code="invalid_frequency") from exc
    if not math.isfinite(result) or result <= 0 or result > 36500:
        raise CleaningError("freq must be a positive number", code="invalid_frequency")
    return result


def _display_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


class CleaningStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS apartments (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apartment_id TEXT NOT NULL REFERENCES apartments(id),
                    legacy_row INTEGER,
                    room TEXT NOT NULL,
                    category TEXT NOT NULL,
                    task TEXT NOT NULL,
                    freq REAL NOT NULL CHECK (freq > 0),
                    last_done TEXT,
                    articles TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (apartment_id, legacy_row)
                );

                CREATE TABLE IF NOT EXISTS cleaning_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apartment_id TEXT NOT NULL REFERENCES apartments(id),
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    task_name TEXT NOT NULL,
                    room TEXT,
                    category TEXT,
                    status TEXT,
                    source TEXT NOT NULL,
                    done_at TEXT NOT NULL,
                    previous_last_done TEXT,
                    reverted_at TEXT,
                    import_key TEXT UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cleaning_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_cleaning_tasks_apartment_active
                    ON tasks(apartment_id, is_active);
                CREATE INDEX IF NOT EXISTS idx_cleaning_actions_apartment_done
                    ON cleaning_actions(apartment_id, done_at DESC);
                CREATE INDEX IF NOT EXISTS idx_cleaning_actions_task_done
                    ON cleaning_actions(task_id, done_at DESC);
                """
            )
            now = utc_now()
            conn.executemany(
                """
                INSERT INTO apartments(id, label, is_active, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET label = excluded.label, updated_at = excluded.updated_at
                """,
                [
                    ("aleja-pokoju6", "Mieszkanie", now, now),
                    ("classic", "Poprzedni setup", now, now),
                ],
            )

    def _require_apartment(self, conn: sqlite3.Connection, apartment_id: Any) -> str:
        normalized = _required_text(apartment_id, "apartment_id", max_length=100)
        row = conn.execute(
            "SELECT id FROM apartments WHERE id = ? AND is_active = 1", (normalized,)
        ).fetchone()
        if not row:
            raise CleaningError("Apartment not found", status=404, code="apartment_not_found")
        return normalized

    def list_apartments(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, label FROM apartments WHERE is_active = 1 ORDER BY created_at, id"
            ).fetchall()
        return [{"id": row["id"], "label": row["label"]} for row in rows]

    def _task_payload(self, row: sqlite3.Row, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(WARSAW)).astimezone(WARSAW)
        last = _parse_datetime(row["last_done"], field="last_done")
        days_since = None
        if last is not None:
            days_since = max(0, (current.date() - last.astimezone(WARSAW).date()).days)
        freq = float(row["freq"])
        if days_since is None:
            overdue = True
            next_due = 0
            status = "OVERDUE"
        else:
            overdue = days_since > freq
            next_due = max(0, int(math.ceil(freq - days_since)))
            overdue_by = max(0.0, days_since - freq)
            if overdue and overdue_by > 7:
                status = "DEAD"
            elif overdue:
                status = "OVERDUE"
            elif next_due == 0:
                status = "DUE"
            elif days_since / freq >= 0.92:
                status = "COMING"
            else:
                status = "FRESH"
        task_id = int(row["id"])
        return {
            "id": task_id,
            "row": task_id,
            "row_id": task_id,
            "legacyRow": row["legacy_row"],
            "apartmentId": row["apartment_id"],
            "room": row["room"],
            "category": row["category"],
            "task": row["task"],
            "freq": _display_number(freq),
            "lastDone": row["last_done"],
            "articles": row["articles"] or "",
            "items": row["articles"] or "",
            "notes": row["notes"] or "",
            "daysSince": days_since,
            "nextDueIn": next_due,
            "overdue": overdue,
            "status": status,
        }

    def get_tasks(self, apartment_id: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        with self._connect() as conn:
            apartment_id = self._require_apartment(conn, apartment_id)
            clauses = ["apartment_id = ?", "is_active = 1"]
            params: list[Any] = [apartment_id]
            for query_key, column in (("room", "room"), ("category", "category")):
                value = str(filters.get(query_key) or "").strip()
                if value and value.upper() != "ALL":
                    clauses.append(f"{column} = ?")
                    params.append(value)
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY room, category, task, id",
                params,
            ).fetchall()
        tasks = [self._task_payload(row) for row in rows]
        status = str(filters.get("status") or "").strip().upper()
        if status:
            tasks = [task for task in tasks if task["status"] == status]
        if str(filters.get("dueOnly") or "").lower() in {"1", "true", "yes"}:
            tasks = [task for task in tasks if task["overdue"] or task["nextDueIn"] == 0]
        supply = str(filters.get("supply") or filters.get("articles") or "").strip().lower()
        if supply:
            tasks = [task for task in tasks if supply in task["articles"].lower()]
        return tasks

    def get_state(self, apartment_id: str) -> dict[str, Any]:
        tasks = self.get_tasks(apartment_id)
        due_today = sum(1 for task in tasks if not task["overdue"] and task["nextDueIn"] == 0)
        overdue = sum(1 for task in tasks if task["overdue"])
        delays = [
            max(0.0, float(task["daysSince"]) - float(task["freq"]))
            for task in tasks
            if task["overdue"] and task["daysSince"] is not None
        ]
        avg_delay = round(sum(delays) / len(delays), 1) if delays else 0
        today = datetime.now(WARSAW).date()
        start_utc = datetime.combine(today, datetime.min.time(), tzinfo=WARSAW).astimezone(timezone.utc)
        end_utc = start_utc + timedelta(days=1)
        with self._connect() as conn:
            actions = conn.execute(
                """
                SELECT * FROM cleaning_actions
                WHERE apartment_id = ? AND reverted_at IS NULL
                  AND done_at >= ? AND done_at < ?
                ORDER BY done_at DESC, id DESC
                """,
                (
                    apartment_id,
                    start_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    end_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                ),
            ).fetchall()
        return {
            "ok": True,
            "apartmentId": apartment_id,
            "apartments": self.list_apartments(),
            "tasks": tasks,
            "kpi": {
                "dueToday": due_today,
                "overdue": overdue,
                "total": len(tasks),
                "avgDelay": avg_delay,
            },
            "doneToday": [self._action_payload(row) for row in actions],
        }

    def count_actions_for_day(self, apartment_id: str, day: str, rollover_hour: int = 6) -> int:
        day_date = date.fromisoformat(day)
        start = datetime.combine(day_date, datetime.min.time(), tzinfo=WARSAW) + timedelta(hours=rollover_hour)
        end = datetime.combine(day_date + timedelta(days=1), datetime.min.time(), tzinfo=WARSAW) + timedelta(hours=rollover_hour)
        start_utc = start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        end_utc = end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._connect() as conn:
            apartment_id = self._require_apartment(conn, apartment_id)
            return conn.execute("""SELECT COUNT(*) FROM cleaning_actions
                WHERE apartment_id = ? AND reverted_at IS NULL AND done_at >= ? AND done_at < ?""",
                (apartment_id, start_utc, end_utc)).fetchone()[0]

    def _task_row(self, conn: sqlite3.Connection, task_id: Any, apartment_id: str | None = None) -> sqlite3.Row:
        try:
            normalized_id = int(task_id)
        except (TypeError, ValueError) as exc:
            raise CleaningError("Invalid task id", code="invalid_task_id") from exc
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (normalized_id,)).fetchone()
        if not row or (apartment_id and row["apartment_id"] != apartment_id):
            raise CleaningError("Task not found", status=404, code="task_not_found")
        return row

    def add_task(self, apartment_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise CleaningError("Task body must be an object", code="invalid_task")
        now = utc_now()
        with self._write() as conn:
            apartment_id = self._require_apartment(conn, apartment_id)
            cursor = conn.execute(
                """
                INSERT INTO tasks(
                    apartment_id, room, category, task, freq, last_done,
                    articles, notes, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    apartment_id,
                    _required_text(data.get("room"), "room", max_length=200),
                    _required_text(data.get("category"), "category", max_length=200),
                    _required_text(data.get("task"), "task"),
                    _frequency(data.get("freq")),
                    _canonical_datetime(data.get("lastDone", data.get("last_done")), field="last_done"),
                    _optional_text(data.get("articles", data.get("items"))),
                    _optional_text(data.get("notes")),
                    now,
                    now,
                ),
            )
            row = self._task_row(conn, cursor.lastrowid)
        return self._task_payload(row)

    def update_task(self, task_id: Any, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise CleaningError("Task body must be an object", code="invalid_task")
        aliases = {"last_done": "lastDone", "items": "articles"}
        normalized = {aliases.get(key, key): value for key, value in data.items()}
        allowed = {"room", "category", "task", "freq", "lastDone", "articles", "notes", "isActive"}
        changes = {key: value for key, value in normalized.items() if key in allowed}
        if not changes:
            raise CleaningError("No editable task fields supplied", code="empty_patch")
        columns: list[str] = []
        values: list[Any] = []
        for key, value in changes.items():
            if key in {"room", "category", "task"}:
                columns.append(f"{key} = ?")
                values.append(_required_text(value, key, max_length=500))
            elif key == "freq":
                columns.append("freq = ?")
                values.append(_frequency(value))
            elif key == "lastDone":
                columns.append("last_done = ?")
                values.append(_canonical_datetime(value, field="last_done"))
            elif key in {"articles", "notes"}:
                columns.append(f"{key} = ?")
                values.append(_optional_text(value))
            elif key == "isActive":
                columns.append("is_active = ?")
                values.append(1 if bool(value) else 0)
        columns.append("updated_at = ?")
        values.append(utc_now())
        values.append(int(task_id))
        with self._write() as conn:
            self._task_row(conn, task_id)
            conn.execute(f"UPDATE tasks SET {', '.join(columns)} WHERE id = ?", values)
            row = self._task_row(conn, task_id)
        return self._task_payload(row)

    def delete_task(self, task_id: Any, soft_delete: bool = True) -> dict[str, Any]:
        if not soft_delete:
            raise CleaningError(
                "Permanent task deletion is disabled to protect cleaning history",
                status=409,
                code="hard_delete_disabled",
            )
        with self._write() as conn:
            row = self._task_row(conn, task_id)
            conn.execute(
                "UPDATE tasks SET is_active = 0, updated_at = ? WHERE id = ?",
                (utc_now(), int(task_id)),
            )
        return {"ok": True, "deleted": int(task_id), "softDeleted": True, "task": self._task_payload(row)}

    def mark_done(
        self,
        task_id: Any,
        apartment_id: str,
        done_at: Any = None,
        source: str = "cleaning-page",
    ) -> dict[str, Any]:
        normalized_done_at = _canonical_datetime(done_at or utc_now(), field="done_at")
        normalized_source = str(source or "cleaning-page").strip().lower()
        if normalized_source not in VALID_SOURCES:
            raise CleaningError("Invalid cleaning action source", code="invalid_source")
        with self._write() as conn:
            apartment_id = self._require_apartment(conn, apartment_id)
            row = self._task_row(conn, task_id, apartment_id)
            if not row["is_active"]:
                raise CleaningError("Task is inactive", status=409, code="task_inactive")
            task_before = self._task_payload(row, now=_parse_datetime(normalized_done_at))
            cursor = conn.execute(
                """
                INSERT INTO cleaning_actions(
                    apartment_id, task_id, task_name, room, category, status,
                    source, done_at, previous_last_done, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    apartment_id,
                    int(row["id"]),
                    row["task"],
                    row["room"],
                    row["category"],
                    task_before["status"],
                    normalized_source,
                    normalized_done_at,
                    row["last_done"],
                    utc_now(),
                ),
            )
            conn.execute(
                "UPDATE tasks SET last_done = ?, updated_at = ? WHERE id = ?",
                (normalized_done_at, utc_now(), int(row["id"])),
            )
            updated = self._task_row(conn, task_id)
            action = conn.execute("SELECT * FROM cleaning_actions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return {"ok": True, "task": self._task_payload(updated), "action": self._action_payload(action)}

    def _action_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "actionId": int(row["id"]),
            "apartmentId": row["apartment_id"],
            "taskId": row["task_id"],
            "row": row["task_id"],
            "task": row["task_name"],
            "taskName": row["task_name"],
            "room": row["room"] or "",
            "category": row["category"] or "",
            "status": row["status"] or "",
            "source": row["source"],
            "at": row["done_at"],
            "doneAt": row["done_at"],
            "revertedAt": row["reverted_at"],
        }

    @staticmethod
    def _history_window(range_name: str, offset: int) -> tuple[date | None, date | None]:
        today = datetime.now(WARSAW).date()
        if range_name == "all":
            return None, None
        if range_name == "week":
            start = today - timedelta(days=today.weekday()) + timedelta(days=offset * 7)
            return start, start + timedelta(days=6)
        if range_name == "month":
            month_index = today.year * 12 + today.month - 1 + offset
            year, month_zero = divmod(month_index, 12)
            start = date(year, month_zero + 1, 1)
            next_month = date(year + 1, 1, 1) if month_zero == 11 else date(year, month_zero + 2, 1)
            return start, next_month - timedelta(days=1)
        start = date(today.year + offset, 1, 1)
        return start, date(today.year + offset, 12, 31)

    def get_history(self, apartment_id: str, range_name: str = "month", offset: int = 0) -> dict[str, Any]:
        normalized_range = str(range_name or "month").strip().lower()
        if normalized_range not in VALID_RANGES:
            raise CleaningError("range must be week, month, year or all", code="invalid_history_range")
        try:
            normalized_offset = int(offset)
        except (TypeError, ValueError) as exc:
            raise CleaningError("offset must be an integer", code="invalid_history_offset") from exc
        if abs(normalized_offset) > 100:
            raise CleaningError("offset is outside the supported range", code="invalid_history_offset")
        start, end = self._history_window(normalized_range, normalized_offset)
        with self._connect() as conn:
            apartment_id = self._require_apartment(conn, apartment_id)
            params: list[Any] = [apartment_id]
            where = ["apartment_id = ?", "reverted_at IS NULL"]
            if start is not None and end is not None:
                start_utc = datetime.combine(start, datetime.min.time(), tzinfo=WARSAW).astimezone(timezone.utc)
                end_utc = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=WARSAW).astimezone(timezone.utc)
                where.append("done_at >= ? AND done_at < ?")
                params.extend([
                    start_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    end_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                ])
            rows = conn.execute(
                f"SELECT * FROM cleaning_actions WHERE {' AND '.join(where)} ORDER BY done_at DESC, id DESC",
                params,
            ).fetchall()
        actions = [self._action_payload(row) for row in rows]
        counts: dict[str, int] = {}
        for action in actions:
            day = _parse_datetime(action["doneAt"], field="done_at").astimezone(WARSAW).date().isoformat()
            counts[day] = counts.get(day, 0) + 1
        series: list[dict[str, Any]] = []
        if start is not None and end is not None:
            cursor = start
            while cursor <= end:
                key = cursor.isoformat()
                series.append({"date": key, "count": counts.get(key, 0)})
                cursor += timedelta(days=1)
        return {
            "ok": True,
            "apartmentId": apartment_id,
            "range": normalized_range,
            "offset": normalized_offset,
            "window": {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
            "actions": actions,
            "series": series,
            "summary": {
                "total": len(actions),
                "activeDays": sum(1 for value in counts.values() if value > 0),
            },
        }

    def revert_last_action(self, action_id: Any = None) -> dict[str, Any]:
        with self._write() as conn:
            if action_id is None:
                action = conn.execute(
                    "SELECT * FROM cleaning_actions WHERE reverted_at IS NULL ORDER BY done_at DESC, id DESC LIMIT 1"
                ).fetchone()
            else:
                try:
                    normalized_id = int(action_id)
                except (TypeError, ValueError) as exc:
                    raise CleaningError("Invalid action id", code="invalid_action_id") from exc
                action = conn.execute(
                    "SELECT * FROM cleaning_actions WHERE id = ? AND reverted_at IS NULL", (normalized_id,)
                ).fetchone()
            if not action:
                raise CleaningError("Cleaning action not found", status=404, code="action_not_found")
            if action["task_id"] is not None:
                latest = conn.execute(
                    """
                    SELECT id FROM cleaning_actions
                    WHERE task_id = ? AND reverted_at IS NULL
                    ORDER BY done_at DESC, id DESC LIMIT 1
                    """,
                    (action["task_id"],),
                ).fetchone()
                if not latest or latest["id"] != action["id"]:
                    raise CleaningError(
                        "Only the latest action for a task can be undone",
                        status=409,
                        code="action_not_latest",
                    )
                conn.execute(
                    "UPDATE tasks SET last_done = ?, updated_at = ? WHERE id = ?",
                    (action["previous_last_done"], utc_now(), action["task_id"]),
                )
            reverted_at = utc_now()
            conn.execute("UPDATE cleaning_actions SET reverted_at = ? WHERE id = ?", (reverted_at, action["id"]))
            updated_action = conn.execute("SELECT * FROM cleaning_actions WHERE id = ?", (action["id"],)).fetchone()
            task = self._task_row(conn, action["task_id"]) if action["task_id"] is not None else None
        return {
            "ok": True,
            "action": self._action_payload(updated_action),
            "task": self._task_payload(task) if task else None,
        }

    def remove_action(self, action_id: Any, apartment_id: Any = None) -> dict[str, Any]:
        try:
            normalized_id = int(action_id)
        except (TypeError, ValueError) as exc:
            raise CleaningError("Invalid action id", code="invalid_action_id") from exc

        with self._write() as conn:
            action = conn.execute(
                "SELECT * FROM cleaning_actions WHERE id = ? AND reverted_at IS NULL",
                (normalized_id,),
            ).fetchone()
            if not action:
                raise CleaningError("Cleaning action not found", status=404, code="action_not_found")
            if apartment_id is not None:
                normalized_apartment = self._require_apartment(conn, apartment_id)
                if action["apartment_id"] != normalized_apartment:
                    raise CleaningError("Cleaning action not found", status=404, code="action_not_found")

            task_id = action["task_id"]
            was_latest = False
            if task_id is not None:
                latest = conn.execute(
                    """
                    SELECT id FROM cleaning_actions
                    WHERE task_id = ? AND reverted_at IS NULL
                    ORDER BY done_at DESC, id DESC LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                was_latest = bool(latest and latest["id"] == action["id"])

            reverted_at = utc_now()
            conn.execute(
                "UPDATE cleaning_actions SET reverted_at = ? WHERE id = ?",
                (reverted_at, action["id"]),
            )

            if task_id is not None and was_latest:
                previous = conn.execute(
                    """
                    SELECT done_at FROM cleaning_actions
                    WHERE task_id = ? AND reverted_at IS NULL
                    ORDER BY done_at DESC, id DESC LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                restored_last_done = previous["done_at"] if previous else action["previous_last_done"]
                conn.execute(
                    "UPDATE tasks SET last_done = ?, updated_at = ? WHERE id = ?",
                    (restored_last_done, utc_now(), task_id),
                )

            updated_action = conn.execute(
                "SELECT * FROM cleaning_actions WHERE id = ?", (action["id"],)
            ).fetchone()
            task = self._task_row(conn, task_id) if task_id is not None else None

        return {
            "ok": True,
            "deleted": int(action["id"]),
            "softDeleted": True,
            "action": self._action_payload(updated_action),
            "task": self._task_payload(task) if task else None,
        }

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM cleaning_settings ORDER BY key").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        result.setdefault("activeApartmentId", "aleja-pokoju6")
        return {"ok": True, "settings": result, **result, "apartments": self.list_apartments()}

    def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise CleaningError("Settings body must be an object", code="invalid_settings")
        payload = data.get("settings") if isinstance(data.get("settings"), dict) else data
        if "activeApartmentId" in payload:
            with self._connect() as conn:
                self._require_apartment(conn, payload["activeApartmentId"])
        now = utc_now()
        with self._write() as conn:
            for key, value in payload.items():
                clean_key = _required_text(key, "setting key", max_length=100)
                conn.execute(
                    """
                    INSERT INTO cleaning_settings(key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (clean_key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), now),
                )
        return self.get_settings()

    def integrity_check(self) -> str:
        with self._connect() as conn:
            return str(conn.execute("PRAGMA integrity_check").fetchone()[0])

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "apartments": int(conn.execute("SELECT COUNT(*) FROM apartments").fetchone()[0]),
                "tasks": int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]),
                "activeTasks": int(conn.execute("SELECT COUNT(*) FROM tasks WHERE is_active = 1").fetchone()[0]),
                "actions": int(conn.execute("SELECT COUNT(*) FROM cleaning_actions").fetchone()[0]),
                "activeActions": int(conn.execute("SELECT COUNT(*) FROM cleaning_actions WHERE reverted_at IS NULL").fetchone()[0]),
            }

    def import_initial(
        self,
        task_sets: dict[str, list[dict[str, Any]]],
        history_sets: dict[str, list[dict[str, Any]]],
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Idempotently import the legacy GAS rows and file-backed action history."""
        now = utc_now()
        imported_tasks = 0
        imported_actions = 0
        with self._write() as conn:
            for apartment_id, tasks in task_sets.items():
                apartment_id = self._require_apartment(conn, apartment_id)
                for raw in tasks:
                    if not isinstance(raw, dict) or not str(raw.get("task") or "").strip():
                        continue
                    try:
                        legacy_row = int(raw.get("row", raw.get("row_id")))
                    except (TypeError, ValueError):
                        continue
                    freq = _frequency(raw.get("freq"))
                    last_done = _canonical_datetime(raw.get("lastDone", raw.get("last_done")), field="last_done")
                    articles = raw.get("articles", raw.get("items", raw.get("Artykuly", "")))
                    existing = conn.execute(
                        "SELECT id, last_done FROM tasks WHERE apartment_id = ? AND legacy_row = ?",
                        (apartment_id, legacy_row),
                    ).fetchone()
                    if existing:
                        existing_last = existing["last_done"]
                        safest_last = max(filter(None, [existing_last, last_done]), default=None)
                        conn.execute(
                            """
                            UPDATE tasks SET room = ?, category = ?, task = ?, freq = ?, last_done = ?,
                                articles = ?, notes = CASE WHEN notes = '' THEN ? ELSE notes END,
                                is_active = 1, updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                _required_text(raw.get("room"), "room", max_length=200),
                                _required_text(raw.get("category"), "category", max_length=200),
                                _required_text(raw.get("task"), "task"),
                                freq,
                                safest_last,
                                _optional_text(articles),
                                _optional_text(raw.get("notes")),
                                now,
                                existing["id"],
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO tasks(
                                apartment_id, legacy_row, room, category, task, freq, last_done,
                                articles, notes, is_active, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                            """,
                            (
                                apartment_id,
                                legacy_row,
                                _required_text(raw.get("room"), "room", max_length=200),
                                _required_text(raw.get("category"), "category", max_length=200),
                                _required_text(raw.get("task"), "task"),
                                freq,
                                last_done,
                                _optional_text(articles),
                                _optional_text(raw.get("notes")),
                                now,
                                now,
                            ),
                        )
                        imported_tasks += 1

            for apartment_id, actions in history_sets.items():
                apartment_id = self._require_apartment(conn, apartment_id)
                for raw in actions:
                    if not isinstance(raw, dict):
                        continue
                    done_at = _canonical_datetime(raw.get("at", raw.get("doneAt")), field="done_at")
                    task_name = _required_text(raw.get("task", raw.get("taskName")), "task")
                    try:
                        legacy_row = int(raw.get("row"))
                    except (TypeError, ValueError):
                        legacy_row = None
                    task_row = None
                    if legacy_row is not None:
                        task_row = conn.execute(
                            "SELECT id FROM tasks WHERE apartment_id = ? AND legacy_row = ?",
                            (apartment_id, legacy_row),
                        ).fetchone()
                    fingerprint_payload = {
                        "apartmentId": apartment_id,
                        "at": done_at,
                        "row": legacy_row,
                        "task": task_name,
                        "room": str(raw.get("room") or "").strip(),
                        "category": str(raw.get("category") or "").strip(),
                        "source": str(raw.get("source") or "migration").strip(),
                    }
                    import_key = hashlib.sha256(
                        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO cleaning_actions(
                            apartment_id, task_id, task_name, room, category, status,
                            source, done_at, previous_last_done, import_key, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                        """,
                        (
                            apartment_id,
                            task_row["id"] if task_row else None,
                            task_name,
                            _optional_text(raw.get("room"), max_length=500),
                            _optional_text(raw.get("category"), max_length=500),
                            _optional_text(raw.get("status"), max_length=50).upper(),
                            _optional_text(raw.get("source"), max_length=100) or "migration",
                            done_at,
                            import_key,
                            now,
                        ),
                    )
                    imported_actions += max(0, cursor.rowcount)

            for key, value in (settings or {}).items():
                conn.execute(
                    """
                    INSERT INTO cleaning_settings(key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (str(key), json.dumps(value, ensure_ascii=False, separators=(",", ":")), now),
                )

        return {
            "insertedTasks": imported_tasks,
            "insertedActions": imported_actions,
            "counts": self.counts(),
            "integrityCheck": self.integrity_check(),
        }


CLEANING_STORE = CleaningStore()
