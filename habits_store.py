import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
SERVICE_NAME = "cleaning-dashboard-habits"
LOOP_NAMESPACE = uuid.UUID("7fd9e25e-89a8-47a0-b7ac-4e59e520de3e")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DEFAULT_TIME_GROUPS = (
    ("morning", "Morning", "09:00", 0),
    ("afternoon", "Afternoon", "15:00", 1),
    ("evening", "Evening", "21:00", 2),
    ("bedtime", "Bedtime", "23:00", 3),
)
DEFAULT_REMINDER_CONFIG = {
    "enabled": False,
    "scheduleType": "daily",
    "selectedWeekdays": [],
    "intervalDays": 2,
    "intervalAnchorDate": None,
    "timeGroupIds": [],
    "customTimes": [],
    "snoozeMinutes": 10,
    "skipIfCompleted": True,
    "completionPolicy": "day",
}

PROFILES = {
    "don't drink": ("HABIT", "#1976d2", "Did you have an alcohol-free day?", 1, 1, None),
    "don't smoke cigarettes": ("HABIT", "#aaaaaa", "Did you have a smoke-free day?", 1, 1, None),
    "don't eat chips": ("HABIT", "#8d6e63", "Did you eat chips today?", 1, 1, None),
    "don't smoke weed": ("HABIT", "#c0ca33", "Did you have a weed-free day today?", 1, 1, None),
    "meditation": ("HABIT", "#29b6f6", "Did you meditate today?", 5, 7, None),
    "push-ups": ("HABIT", "#5c6bc0", "", 1, 1, 10_000),
    "squats": ("HABIT", "#5c6bc0", "", 1, 1, 15_000),
    "pregabalin": ("MEDICATION", "#eeeeee", "", 1, 1, 1_000),
    "concerta/atenza": ("MEDICATION", "#26a69a", "", 1, 1, 1_000),
    "creatine": ("SUPPLEMENT", "#90a4ae", "", 1, 1, None),
    "bupropion": ("MEDICATION", "#29b6f6", "", 1, 1, None),
    "duloxetine": ("MEDICATION", "#ab47bc", "", 1, 1, None),
    "biotyna/b complex": ("SUPPLEMENT", "#ef5350", "", 1, 1, None),
    "b12": ("SUPPLEMENT", "#29b6f6", "", 1, 1, None),
    "vitamin c": ("SUPPLEMENT", "#ffa726", "", 1, 1, None),
    "vitamin d": ("SUPPLEMENT", "#ffee58", "Did you take vitamin D today?", 1, 1, None),
    "zinc": ("SUPPLEMENT", "#bcaaa4", "", 1, 2, None),
    "magnesium": ("SUPPLEMENT", "#eeeeee", "", 1, 1, None),
    "omega 3": ("SUPPLEMENT", "#ec407a", "", 1, 1, None),
    "melatonin": ("MEDICATION", "#29b6f6", "", 1, 1, 1_000),
    "medikinet ir": ("MEDICATION", "#ab47bc", "", 1, 1, 1_000),
    "medikinet cr": ("MEDICATION", "#c0ca33", "", 1, 1, 1_000),
    "l-theanine": ("SUPPLEMENT", "#42a5f5", "", 1, 1, None),
    "heviran morning": ("MEDICATION", "#ab47bc", "", 1, 1, None),
    "heviran evening": ("MEDICATION", "#ab47bc", "", 1, 1, None),
    "collagen": ("SUPPLEMENT", "#26c6da", "", 1, 1, None),
    "lion's mane": ("SUPPLEMENT", "#bcaaa4", "", 1, 1, None),
    "ashwaganda": ("SUPPLEMENT", "#bcaaa4", "", 1, 1, None),
}
PROFILE_POSITIONS = {name: position for position, name in enumerate(PROFILES)}


class HabitsError(ValueError):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bool(value, default=False):
    return bool(default if value is None else value)


class HabitsStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self, seed_path=None):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS habits (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
                    category TEXT NOT NULL, question TEXT NOT NULL, description TEXT NOT NULL,
                    color_hex TEXT NOT NULL, unit TEXT NOT NULL, target_type TEXT,
                    target_value_milli INTEGER, frequency_numerator INTEGER NOT NULL,
                    frequency_denominator INTEGER NOT NULL, position INTEGER NOT NULL,
                    archived INTEGER NOT NULL, reminder_hour INTEGER, reminder_minute INTEGER,
                    reminder_days_mask INTEGER NOT NULL, revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY, habit_id TEXT NOT NULL, date TEXT NOT NULL,
                    status TEXT, value_milli INTEGER, note TEXT, revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, deleted_at TEXT,
                    UNIQUE(habit_id, date), FOREIGN KEY(habit_id) REFERENCES habits(id)
                );
                CREATE TABLE IF NOT EXISTS changes (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL, operation TEXT NOT NULL,
                    entity_json TEXT NOT NULL, changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_mutations (
                    mutation_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                    result_kind TEXT NOT NULL, response_json TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminder_time_groups (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, local_time TEXT NOT NULL,
                    sort_order INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminder_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    browser_notifications_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminder_occurrences (
                    occurrence_key TEXT PRIMARY KEY, habit_id TEXT NOT NULL,
                    local_date TEXT NOT NULL, source_key TEXT NOT NULL,
                    scheduled_local_time TEXT NOT NULL, status TEXT NOT NULL,
                    fired_at TEXT, snoozed_until TEXT, updated_at TEXT NOT NULL,
                    FOREIGN KEY(habit_id) REFERENCES habits(id)
                );
                CREATE INDEX IF NOT EXISTS changes_entity_idx ON changes(entity_type, entity_id);
                CREATE INDEX IF NOT EXISTS entries_date_idx ON entries(date);
                CREATE INDEX IF NOT EXISTS reminder_occurrences_date_idx
                    ON reminder_occurrences(local_date, habit_id);
                """
            )
            habit_columns = {row[1] for row in connection.execute("PRAGMA table_info(habits)")}
            if "reminder_config_json" not in habit_columns:
                connection.execute(
                    "ALTER TABLE habits ADD COLUMN reminder_config_json TEXT NOT NULL DEFAULT '{}'"
                )
            reminder_settings_exists = connection.execute(
                "SELECT 1 FROM reminder_settings WHERE id = 1"
            ).fetchone() is not None
            if not reminder_settings_exists and connection.execute("SELECT COUNT(*) FROM reminder_time_groups").fetchone()[0] == 0:
                now = utc_now()
                connection.executemany(
                    "INSERT INTO reminder_time_groups(id, name, local_time, sort_order, updated_at) VALUES (?, ?, ?, ?, ?)",
                    [(*group, now) for group in DEFAULT_TIME_GROUPS],
                )
            connection.execute(
                "INSERT OR IGNORE INTO reminder_settings(id, browser_notifications_enabled, updated_at) VALUES (1, 0, ?)",
                (utc_now(),),
            )
            entry_columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)")}
            if "taken_at" not in entry_columns:
                connection.execute("ALTER TABLE entries ADD COLUMN taken_at TEXT")
            count = connection.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
            if count == 0 and seed_path and Path(seed_path).exists():
                self._seed(connection, Path(seed_path))
            from supplements_store import initialize_supplements
            initialize_supplements(connection)
            creatine = connection.execute(
                "SELECT * FROM habits WHERE name='Creatine' AND category='SUPPLEMENT' AND unit='mg' AND deleted_at IS NULL"
            ).fetchone()
            if creatine is not None:
                # Milli values stay untouched; the existing displayed value 5 is grams.
                entity = self._habit_entity(creatine)
                entity.update(unit="g", revision=entity["revision"] + 1, updatedAt=utc_now())
                self._insert_habit(connection, entity)
                self._append_change(connection, "HABIT", "UPSERT", entity)

    def _append_change(self, connection, entity_type, operation, entity):
        now = utc_now()
        cursor = connection.execute(
            "INSERT INTO changes(entity_type, entity_id, operation, entity_json, changed_at) VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity["id"], operation, json.dumps(entity, separators=(",", ":")), now),
        ).lastrowid
        return {"cursor": str(cursor), "entityType": entity_type, "operation": operation, "entity": entity}

    def _seed(self, connection, seed_path):
        source = json.loads(seed_path.read_text(encoding="utf-8"))
        now = utc_now()
        for position, raw in enumerate(source.get("habits") or []):
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            habit_id = str(uuid.uuid5(LOOP_NAMESPACE, f"loop-habit:{raw.get('id', name)}"))
            category, color, question, numerator, denominator, target = PROFILES.get(
                name.lower(), ("HABIT", "#60a5fa", "", 1, 1, None)
            )
            habit = {
                "id": habit_id,
                "name": name,
                "type": "NUMERIC" if int(raw.get("type") or 0) == 1 else "BINARY",
                "category": category,
                "question": question,
                "description": "",
                "colorHex": color,
                "unit": str(raw.get("unit") or ""),
                "targetType": "AT_LEAST" if target is not None else None,
                "targetValueMilli": target,
                "frequencyNumerator": numerator,
                "frequencyDenominator": denominator,
                "position": PROFILE_POSITIONS.get(name.lower(), 1000 + position),
                "archived": False,
                "reminderHour": None,
                "reminderMinute": None,
                "reminderDaysMask": 0,
                "reminderConfig": dict(DEFAULT_REMINDER_CONFIG),
                "revision": 1,
                "updatedAt": now,
                "deletedAt": None,
            }
            self._insert_habit(connection, habit)
            self._append_change(connection, "HABIT", "UPSERT", habit)
            for point in raw.get("points") or []:
                if not isinstance(point, list) or len(point) < 2:
                    continue
                try:
                    timestamp = int(point[0]) / 1000
                    day = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
                    value = int(round(float(point[1])))
                except (TypeError, ValueError, OSError):
                    continue
                entry_id = f"{habit_id}:{day}"
                entry = {
                    "id": entry_id,
                    "habitId": habit_id,
                    "date": day,
                    "status": None if habit["type"] == "NUMERIC" else ("DONE" if value > 0 else "MISSED"),
                    "valueMilli": value if habit["type"] == "NUMERIC" else None,
                    "note": None,
                    "revision": 1,
                    "updatedAt": now,
                    "deletedAt": None,
                }
                self._insert_entry(connection, entry)
                self._append_change(connection, "ENTRY", "UPSERT", entry)

    def _insert_habit(self, connection, entity):
        connection.execute(
            """INSERT INTO habits(
             id,name,type,category,question,description,color_hex,unit,target_type,
             target_value_milli,frequency_numerator,frequency_denominator,position,archived,
             reminder_hour,reminder_minute,reminder_days_mask,revision,updated_at,deleted_at,
             reminder_config_json) VALUES
            (:id,:name,:type,:category,:question,:description,:colorHex,:unit,:targetType,
             :targetValueMilli,:frequencyNumerator,:frequencyDenominator,:position,:archived,
             :reminderHour,:reminderMinute,:reminderDaysMask,:revision,:updatedAt,:deletedAt,
             :reminderConfigJson)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, type=excluded.type, category=excluded.category,
                question=excluded.question, description=excluded.description,
                color_hex=excluded.color_hex, unit=excluded.unit,
                target_type=excluded.target_type, target_value_milli=excluded.target_value_milli,
                frequency_numerator=excluded.frequency_numerator,
                frequency_denominator=excluded.frequency_denominator,
                position=excluded.position, archived=excluded.archived,
                reminder_hour=excluded.reminder_hour, reminder_minute=excluded.reminder_minute,
                reminder_days_mask=excluded.reminder_days_mask, revision=excluded.revision,
                updated_at=excluded.updated_at, deleted_at=excluded.deleted_at,
                reminder_config_json=excluded.reminder_config_json""",
            {
                **entity,
                "archived": int(entity["archived"]),
                "reminderConfigJson": json.dumps(
                    entity.get("reminderConfig") or DEFAULT_REMINDER_CONFIG,
                    separators=(",", ":"),
                ),
            },
        )

    def _insert_entry(self, connection, entity):
        connection.execute(
            """INSERT OR REPLACE INTO entries
            (id,habit_id,date,status,value_milli,note,revision,updated_at,deleted_at,taken_at)
            VALUES (:id,:habitId,:date,:status,:valueMilli,:note,:revision,:updatedAt,:deletedAt,:takenAt)""",
            {**entity, "takenAt": entity.get("takenAt")},
        )

    @staticmethod
    def _habit_entity(row):
        if row is None:
            return None
        try:
            reminder_config = json.loads(row["reminder_config_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            reminder_config = {}
        reminder_config = {**DEFAULT_REMINDER_CONFIG, **reminder_config}
        return {
            "id": row["id"], "name": row["name"], "type": row["type"],
            "category": row["category"], "question": row["question"],
            "description": row["description"], "colorHex": row["color_hex"],
            "unit": row["unit"], "targetType": row["target_type"],
            "targetValueMilli": row["target_value_milli"],
            "frequencyNumerator": row["frequency_numerator"],
            "frequencyDenominator": row["frequency_denominator"],
            "position": row["position"], "archived": bool(row["archived"]),
            "reminderHour": row["reminder_hour"], "reminderMinute": row["reminder_minute"],
            "reminderDaysMask": row["reminder_days_mask"], "revision": row["revision"],
            "reminderConfig": reminder_config,
            "updatedAt": row["updated_at"], "deletedAt": row["deleted_at"],
        }

    @staticmethod
    def _entry_entity(row):
        if row is None:
            return None
        return {
            "id": row["id"], "habitId": row["habit_id"], "date": row["date"],
            "status": row["status"], "valueMilli": row["value_milli"], "note": row["note"],
            "takenAt": row["taken_at"],
            "revision": row["revision"], "updatedAt": row["updated_at"],
            "deletedAt": row["deleted_at"],
        }

    def health(self):
        return {"ok": True, "service": SERVICE_NAME, "schemaVersion": SCHEMA_VERSION, "deviceName": "Cleaning Dashboard PC"}

    def snapshot(self, from_date=None, to_date=None):
        with self._lock, self._connect() as connection:
            habits = [self._habit_entity(row) for row in connection.execute("SELECT * FROM habits WHERE deleted_at IS NULL ORDER BY position, name")]
            where = ["deleted_at IS NULL"]
            params = []
            if from_date:
                self._validate_date(from_date)
                where.append("date >= ?")
                params.append(from_date)
            if to_date:
                self._validate_date(to_date)
                where.append("date <= ?")
                params.append(to_date)
            entries = [self._entry_entity(row) for row in connection.execute(f"SELECT * FROM entries WHERE {' AND '.join(where)} ORDER BY date", params)]
            time_groups = [
                {"id": row["id"], "name": row["name"], "localTime": row["local_time"], "sortOrder": row["sort_order"]}
                for row in connection.execute("SELECT * FROM reminder_time_groups ORDER BY sort_order, name")
            ]
            reminder_settings_row = connection.execute("SELECT * FROM reminder_settings WHERE id = 1").fetchone()
            reminder_states = [self._reminder_occurrence_entity(row) for row in connection.execute(
                "SELECT * FROM reminder_occurrences ORDER BY updated_at DESC LIMIT 500"
            )]
            cursor = connection.execute("SELECT MAX(cursor) FROM changes").fetchone()[0]
        return {
            "schemaVersion": SCHEMA_VERSION,
            "serverTime": utc_now(),
            "cursor": str(cursor) if cursor else None,
            "habits": habits,
            "entries": entries,
            "reminderTimeGroups": time_groups,
            "reminderSettings": {
                "browserNotificationsEnabled": bool(reminder_settings_row["browser_notifications_enabled"]),
            },
            "reminderStates": reminder_states,
        }

    @staticmethod
    def _reminder_occurrence_entity(row):
        return {
            "occurrenceKey": row["occurrence_key"],
            "habitId": row["habit_id"],
            "localDate": row["local_date"],
            "sourceKey": row["source_key"],
            "scheduledLocalTime": row["scheduled_local_time"],
            "status": row["status"],
            "firedAt": row["fired_at"],
            "snoozedUntil": row["snoozed_until"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _normalize_reminder_config(raw, connection=None):
        if raw is None:
            return dict(DEFAULT_REMINDER_CONFIG)
        if not isinstance(raw, dict):
            raise HabitsError("reminderConfig must be an object")
        config = {**DEFAULT_REMINDER_CONFIG, **raw}
        schedule_type = str(config.get("scheduleType") or "daily")
        if schedule_type not in {"daily", "weekdays", "interval_days", "custom"}:
            raise HabitsError("Invalid reminder schedule type")
        try:
            selected_weekdays = sorted({int(day) for day in (config.get("selectedWeekdays") or [])})
            interval_days = int(config.get("intervalDays") or 0)
            snooze_minutes = int(config.get("snoozeMinutes") or 0)
        except (TypeError, ValueError) as exc:
            raise HabitsError("Invalid reminder schedule values") from exc
        if any(day < 0 or day > 6 for day in selected_weekdays):
            raise HabitsError("Reminder weekdays must be between 0 and 6")
        if schedule_type in {"weekdays", "custom"} and not selected_weekdays:
            raise HabitsError("Select at least one reminder weekday")
        anchor = config.get("intervalAnchorDate")
        if schedule_type == "interval_days":
            if interval_days < 1 or interval_days > 365:
                raise HabitsError("Reminder interval must be between 1 and 365 days")
            HabitsStore._validate_date(anchor)
        elif anchor is not None and anchor != "":
            HabitsStore._validate_date(anchor)
        group_ids = []
        for group_id in config.get("timeGroupIds") or []:
            group_id = str(group_id).strip()
            if group_id and group_id not in group_ids:
                group_ids.append(group_id)
        custom_times = sorted({str(value).strip() for value in (config.get("customTimes") or [])})
        if any(not TIME_RE.fullmatch(value) for value in custom_times):
            raise HabitsError("Reminder times must use HH:MM")
        if connection is not None and group_ids:
            known = {
                row[0]
                for row in connection.execute(
                    f"SELECT id FROM reminder_time_groups WHERE id IN ({','.join('?' for _ in group_ids)})",
                    group_ids,
                )
            }
            missing = [group_id for group_id in group_ids if group_id not in known]
            if missing:
                raise HabitsError(f"Unknown reminder time group: {missing[0]}")
        if bool(config.get("enabled")) and not (group_ids or custom_times):
            raise HabitsError("An enabled reminder needs at least one time")
        if snooze_minutes not in {10, 15, 30, 60}:
            raise HabitsError("Snooze must be 10, 15, 30 or 60 minutes")
        completion_policy = str(config.get("completionPolicy") or "day")
        if completion_policy not in {"day", "occurrence"}:
            raise HabitsError("Invalid reminder completion policy")
        return {
            "enabled": bool(config.get("enabled")),
            "scheduleType": schedule_type,
            "selectedWeekdays": selected_weekdays,
            "intervalDays": interval_days or 2,
            "intervalAnchorDate": anchor or None,
            "timeGroupIds": group_ids,
            "customTimes": custom_times,
            "snoozeMinutes": snooze_minutes,
            "skipIfCompleted": bool(config.get("skipIfCompleted")),
            "completionPolicy": completion_policy,
        }

    @staticmethod
    def _validate_date(value):
        if not isinstance(value, str) or not DATE_RE.fullmatch(value):
            raise HabitsError("Date must use YYYY-MM-DD")
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise HabitsError("Invalid calendar date") from exc

    @staticmethod
    def _required_string(payload, name):
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise HabitsError(f"{name} is required")
        return value.strip()

    def _apply_habit(self, connection, mutation, current):
        payload = mutation["payload"]
        now = utc_now()
        if mutation["operation"] == "DELETE":
            if current is None:
                raise HabitsError("Cannot delete a habit that does not exist", 409, "entity_not_found")
            entity = {**current, "revision": current["revision"] + 1, "updatedAt": now, "deletedAt": now}
        else:
            def value(name, default=None):
                if name in payload:
                    return payload[name]
                return (current or {}).get(name, default)

            name = value("name")
            if not isinstance(name, str) or not name.strip():
                raise HabitsError("name is required")
            name = name.strip()
            habit_type = str(value("type", "BINARY") or "BINARY").upper()
            category = str(value("category", "HABIT") or "HABIT").upper()
            if habit_type not in {"BINARY", "NUMERIC"}:
                raise HabitsError("Habit type must be BINARY or NUMERIC")
            if category not in {"HABIT", "MEDICATION", "SUPPLEMENT"}:
                raise HabitsError("Invalid habit category")
            entity = {
                "id": mutation["entityId"], "name": name, "type": habit_type, "category": category,
                "question": str(value("question", "") or ""), "description": str(value("description", "") or ""),
                "colorHex": str(value("colorHex", "#60a5fa") or "#60a5fa"), "unit": str(value("unit", "") or ""),
                "targetType": value("targetType"), "targetValueMilli": value("targetValueMilli"),
                "frequencyNumerator": int(value("frequencyNumerator", 1) or 1),
                "frequencyDenominator": int(value("frequencyDenominator", 1) or 1),
                "position": int(value("position", 0)),
                "archived": _bool(value("archived", False)), "reminderHour": value("reminderHour"),
                "reminderMinute": value("reminderMinute"), "reminderDaysMask": int(value("reminderDaysMask", 0) or 0),
                "reminderConfig": self._normalize_reminder_config(
                    value("reminderConfig", DEFAULT_REMINDER_CONFIG), connection
                ),
                "revision": (current["revision"] + 1) if current else 1, "updatedAt": now, "deletedAt": None,
            }
        self._insert_habit(connection, entity)
        return entity

    def _apply_entry(self, connection, mutation, current):
        payload = mutation["payload"]
        now = utc_now()
        if mutation["operation"] == "DELETE":
            if current is None:
                habit_id = self._required_string(payload, "habitId")
                day = self._required_string(payload, "date")
                self._validate_date(day)
                entity = {"id": mutation["entityId"], "habitId": habit_id, "date": day, "status": None,
                          "valueMilli": None, "note": None, "takenAt": None,
                          "revision": 1, "updatedAt": now, "deletedAt": now}
                self._insert_entry(connection, entity)
                return entity
            entity = {**current, "revision": current["revision"] + 1, "updatedAt": now, "deletedAt": now}
        else:
            habit_id = self._required_string(payload, "habitId")
            day = self._required_string(payload, "date")
            self._validate_date(day)
            parent = connection.execute("SELECT deleted_at, category FROM habits WHERE id = ?", (habit_id,)).fetchone()
            if parent is None or parent["deleted_at"] is not None:
                raise HabitsError("Entry habit does not exist", 409, "habit_not_found")
            status = payload.get("status")
            if status is not None:
                status = str(status).upper()
                if status not in {"DONE", "MISSED", "SKIPPED"}:
                    raise HabitsError("Invalid entry status")
            value_milli = payload.get("valueMilli")
            if value_milli is not None:
                value_milli = int(value_milli)
            taken = parent["category"] == "SUPPLEMENT" and (
                status == "DONE" or (value_milli is not None and value_milli > 0)
            )
            taken_at = payload.get("takenAt") if taken else None
            if taken_at is not None:
                try:
                    parsed = datetime.fromisoformat(str(taken_at).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError()
                except ValueError as exc:
                    raise HabitsError("takenAt must be an ISO timestamp with timezone") from exc
                taken_at = parsed.isoformat()
            elif taken:
                taken_at = current.get("takenAt") if current else None
                if taken_at is None:
                    taken_at = now
            entity = {"id": mutation["entityId"], "habitId": habit_id, "date": day, "status": status,
                      "valueMilli": value_milli, "note": payload.get("note"), "takenAt": taken_at,
                      "revision": (current["revision"] + 1) if current else 1, "updatedAt": now, "deletedAt": None}
        self._insert_entry(connection, entity)
        return entity

    @staticmethod
    def _normalize_time_groups(raw_groups):
        if not isinstance(raw_groups, list) or len(raw_groups) > 24:
            raise HabitsError("timeGroups must be an array with at most 24 items")
        normalized = []
        seen = set()
        for position, raw in enumerate(raw_groups):
            if not isinstance(raw, dict):
                raise HabitsError("Each reminder time group must be an object")
            group_id = str(raw.get("id") or "").strip().lower()
            name = str(raw.get("name") or "").strip()
            local_time = str(raw.get("localTime") or "").strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", group_id):
                raise HabitsError("Time group id must use lowercase letters, numbers, _ or -")
            if group_id in seen:
                raise HabitsError("Time group ids must be unique")
            if not name or len(name) > 80:
                raise HabitsError("Time group name is required and must be at most 80 characters")
            if not TIME_RE.fullmatch(local_time):
                raise HabitsError("Time group time must use HH:MM")
            seen.add(group_id)
            normalized.append({
                "id": group_id,
                "name": name,
                "localTime": local_time,
                "sortOrder": position,
            })
        return normalized

    def save_reminder_settings(self, payload):
        if not isinstance(payload, dict):
            raise HabitsError("JSON object expected")
        groups = self._normalize_time_groups(payload.get("timeGroups"))
        browser_enabled = bool(payload.get("browserNotificationsEnabled"))
        resolutions = payload.get("deletedGroupResolutions") or {}
        if not isinstance(resolutions, dict):
            raise HabitsError("deletedGroupResolutions must be an object")
        next_ids = {group["id"] for group in groups}
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current_ids = {row[0] for row in connection.execute("SELECT id FROM reminder_time_groups")}
                deleted_ids = current_ids - next_ids
                changed_habits = []
                if deleted_ids:
                    for row in connection.execute("SELECT * FROM habits WHERE deleted_at IS NULL"):
                        habit = self._habit_entity(row)
                        config = dict(habit["reminderConfig"])
                        referenced = [group_id for group_id in config["timeGroupIds"] if group_id in deleted_ids]
                        if not referenced:
                            continue
                        next_references = list(config["timeGroupIds"])
                        for deleted_id in referenced:
                            if deleted_id not in resolutions:
                                raise HabitsError(
                                    f"Time group {deleted_id} is still referenced",
                                    409,
                                    "time_group_in_use",
                                )
                            replacement = resolutions[deleted_id]
                            next_references = [value for value in next_references if value != deleted_id]
                            if replacement is not None:
                                replacement = str(replacement)
                                if replacement not in next_ids:
                                    raise HabitsError("Replacement time group does not exist")
                                if replacement not in next_references:
                                    next_references.append(replacement)
                        config["timeGroupIds"] = next_references
                        if config["enabled"] and not (next_references or config["customTimes"]):
                            config["enabled"] = False
                        habit.update({
                            "reminderConfig": config,
                            "revision": habit["revision"] + 1,
                            "updatedAt": now,
                        })
                        self._insert_habit(connection, habit)
                        changed_habits.append(self._append_change(connection, "HABIT", "UPSERT", habit))
                connection.execute("DELETE FROM reminder_time_groups")
                connection.executemany(
                    "INSERT INTO reminder_time_groups(id, name, local_time, sort_order, updated_at) VALUES (?, ?, ?, ?, ?)",
                    [(group["id"], group["name"], group["localTime"], group["sortOrder"], now) for group in groups],
                )
                connection.execute(
                    "UPDATE reminder_settings SET browser_notifications_enabled = ?, updated_at = ? WHERE id = 1",
                    (int(browser_enabled), now),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {
            "ok": True,
            "timeGroups": groups,
            "browserNotificationsEnabled": browser_enabled,
            "changedHabits": [change["entity"] for change in changed_habits],
        }

    def reminder_action(self, payload):
        if not isinstance(payload, dict):
            raise HabitsError("JSON object expected")
        action = str(payload.get("action") or "").lower()
        occurrence_key = self._required_string(payload, "occurrenceKey")
        if len(occurrence_key) > 300:
            raise HabitsError("Occurrence key is too long")
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM reminder_occurrences WHERE occurrence_key = ?",
                    (occurrence_key,),
                ).fetchone()
                if action == "claim":
                    habit_id = self._required_string(payload, "habitId")
                    local_date = self._required_string(payload, "localDate")
                    self._validate_date(local_date)
                    source_key = self._required_string(payload, "sourceKey")
                    scheduled_time = self._required_string(payload, "scheduledLocalTime")
                    if not TIME_RE.fullmatch(scheduled_time):
                        raise HabitsError("scheduledLocalTime must use HH:MM")
                    habit = connection.execute(
                        "SELECT id FROM habits WHERE id = ? AND deleted_at IS NULL",
                        (habit_id,),
                    ).fetchone()
                    if habit is None:
                        raise HabitsError("Reminder habit does not exist", 404, "habit_not_found")
                    can_claim = row is None or (
                        row["status"] == "snoozed"
                        and row["snoozed_until"]
                        and row["snoozed_until"] <= now
                    )
                    if can_claim:
                        connection.execute(
                            """INSERT INTO reminder_occurrences(
                                occurrence_key, habit_id, local_date, source_key,
                                scheduled_local_time, status, fired_at, snoozed_until, updated_at
                            ) VALUES (?, ?, ?, ?, ?, 'fired', ?, NULL, ?)
                            ON CONFLICT(occurrence_key) DO UPDATE SET
                                status='fired', fired_at=excluded.fired_at,
                                snoozed_until=NULL, updated_at=excluded.updated_at""",
                            (occurrence_key, habit_id, local_date, source_key, scheduled_time, now, now),
                        )
                    connection.commit()
                    saved = connection.execute(
                        "SELECT * FROM reminder_occurrences WHERE occurrence_key = ?",
                        (occurrence_key,),
                    ).fetchone()
                    return {"claimed": can_claim, "state": self._reminder_occurrence_entity(saved)}
                if row is None:
                    raise HabitsError("Reminder occurrence does not exist", 404, "occurrence_not_found")
                if action == "snooze":
                    snoozed_until = self._required_string(payload, "snoozedUntil")
                    try:
                        datetime.fromisoformat(snoozed_until.replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise HabitsError("Invalid snoozedUntil timestamp") from exc
                    status = "snoozed"
                elif action in {"dismiss", "satisfied"}:
                    snoozed_until = None
                    status = "dismissed" if action == "dismiss" else "satisfied"
                else:
                    raise HabitsError("Invalid reminder action")
                connection.execute(
                    "UPDATE reminder_occurrences SET status = ?, snoozed_until = ?, updated_at = ? WHERE occurrence_key = ?",
                    (status, snoozed_until, now, occurrence_key),
                )
                connection.commit()
                saved = connection.execute(
                    "SELECT * FROM reminder_occurrences WHERE occurrence_key = ?",
                    (occurrence_key,),
                ).fetchone()
                return {"ok": True, "state": self._reminder_occurrence_entity(saved)}
            except Exception:
                connection.rollback()
                raise

    def sync(self, request):
        if not isinstance(request, dict):
            raise HabitsError("JSON object expected")
        if request.get("schemaVersion") != SCHEMA_VERSION:
            raise HabitsError("Unsupported schemaVersion", 409, "schema_version_mismatch")
        device_id = self._required_string(request, "deviceId")
        mutations = request.get("mutations") or []
        if not isinstance(mutations, list) or len(mutations) > 500:
            raise HabitsError("mutations must be an array with at most 500 items")
        try:
            incoming_cursor = int(request.get("lastPulledCursor") or 0)
            limit = max(1, min(500, int(request.get("limit") or 200)))
        except (TypeError, ValueError) as exc:
            raise HabitsError("Invalid cursor or limit") from exc

        acknowledged = []
        conflicts = []
        replay_changes = []
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for raw in mutations:
                    mutation = self._normalize_mutation(raw)
                    saved = connection.execute("SELECT result_kind, response_json FROM processed_mutations WHERE mutation_id = ?", (mutation["mutationId"],)).fetchone()
                    if saved:
                        response = json.loads(saved["response_json"])
                        if saved["result_kind"] == "ACK":
                            acknowledged.append(mutation["mutationId"])
                            replay_changes.append(response)
                        else:
                            conflicts.append(response)
                        continue
                    table = "habits" if mutation["entityType"] == "HABIT" else "entries"
                    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (mutation["entityId"],)).fetchone()
                    current = self._habit_entity(row) if mutation["entityType"] == "HABIT" else self._entry_entity(row)
                    base_revision = mutation.get("baseRevision")
                    if current is None and mutation["entityType"] == "ENTRY" and base_revision not in (None, 0):
                        previous = connection.execute(
                            "SELECT entity_json FROM changes WHERE entity_type='ENTRY' AND entity_id=? "
                            "ORDER BY cursor DESC LIMIT 1", (mutation["entityId"],)
                        ).fetchone()
                        if previous:
                            tombstone = json.loads(previous["entity_json"])
                            if tombstone.get("deletedAt") is not None and tombstone.get("revision") == base_revision:
                                self._insert_entry(connection, tombstone)
                                current = tombstone
                    revision_matches = (current is None and base_revision in (None, 0)) or (current is not None and base_revision == current["revision"])
                    if not revision_matches:
                        conflict = {"mutationId": mutation["mutationId"], "entityType": mutation["entityType"],
                                    "entityId": mutation["entityId"], "reason": "REVISION_MISMATCH",
                                    "clientEntity": mutation["payload"], "serverEntity": current}
                        if current is None:
                            conflict["reason"] = "ENTITY_NOT_FOUND"
                            conflict["serverEntity"] = {"id": mutation["entityId"], "revision": 0, "updatedAt": utc_now(), "deletedAt": utc_now()}
                        conflicts.append(conflict)
                        connection.execute("INSERT INTO processed_mutations VALUES (?, ?, ?, ?, ?)",
                                           (mutation["mutationId"], device_id, "CONFLICT", json.dumps(conflict), utc_now()))
                        continue
                    entity = self._apply_habit(connection, mutation, current) if mutation["entityType"] == "HABIT" else self._apply_entry(connection, mutation, current)
                    change = self._append_change(connection, mutation["entityType"], mutation["operation"], entity)
                    acknowledged.append(mutation["mutationId"])
                    connection.execute("INSERT INTO processed_mutations VALUES (?, ?, ?, ?, ?)",
                                       (mutation["mutationId"], device_id, "ACK", json.dumps(change), utc_now()))

                rows = connection.execute("SELECT cursor, entity_type, operation, entity_json FROM changes WHERE cursor > ? ORDER BY cursor LIMIT ?", (incoming_cursor, limit)).fetchall()
                changes = [{"cursor": str(row["cursor"]), "entityType": row["entity_type"], "operation": row["operation"], "entity": json.loads(row["entity_json"])} for row in rows]
                known = {(item["cursor"], item["entityType"], item["entity"]["id"]) for item in changes}
                for item in replay_changes:
                    key = (item["cursor"], item["entityType"], item["entity"]["id"])
                    if key not in known and len(changes) < limit:
                        changes.append(item)
                        known.add(key)
                changes.sort(key=lambda item: int(item["cursor"]))
                next_cursor = max([incoming_cursor, *[int(item["cursor"]) for item in changes]])
                has_more = connection.execute("SELECT 1 FROM changes WHERE cursor > ? LIMIT 1", (next_cursor,)).fetchone() is not None
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"schemaVersion": SCHEMA_VERSION, "serverTime": utc_now(),
                "nextCursor": str(next_cursor) if next_cursor else None, "hasMore": has_more,
                "acknowledgedMutationIds": acknowledged, "changes": changes, "conflicts": conflicts}

    @staticmethod
    def _normalize_mutation(raw):
        if not isinstance(raw, dict):
            raise HabitsError("Each mutation must be an object")
        mutation_id = HabitsStore._required_string(raw, "mutationId")
        entity_type = str(raw.get("entityType") or "").upper()
        operation = str(raw.get("operation") or "").upper()
        entity_id = HabitsStore._required_string(raw, "entityId")
        payload = raw.get("payload")
        if entity_type not in {"HABIT", "ENTRY"} or operation not in {"UPSERT", "DELETE"}:
            raise HabitsError("Invalid entityType or operation")
        if not isinstance(payload, dict):
            raise HabitsError("Mutation payload must be an object")
        base = raw.get("baseRevision")
        if base is not None:
            try:
                base = int(base)
            except (TypeError, ValueError) as exc:
                raise HabitsError("baseRevision must be an integer or null") from exc
        return {**raw, "mutationId": mutation_id, "entityType": entity_type, "operation": operation,
                "entityId": entity_id, "baseRevision": base, "payload": payload}


HABITS_STORE = HabitsStore(Path(__file__).resolve().parent / "data" / "habits.sqlite")
