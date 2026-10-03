"""Private SQLite persistence and analytics for the Mental Health module."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

from mental_health_registry import (
    MentalHealthScoringError,
    get_registry,
    interpretation_for,
    score_instrument,
)


SCHEMA_VERSION = 1
CHECKIN_FIELDS = (
    "mood", "anxiety", "stress", "energy", "motivation", "irritability",
    "socialBattery", "sensoryOverload", "focus", "sleepQuality",
)
EVENT_TYPES = {
    "important_event", "medication_started", "medication_stopped", "dose_changed",
    "therapy_started", "therapy_session", "sick_leave_started", "sick_leave_ended",
    "job_change", "relationship_event", "travel", "illness", "alcohol",
    "unusual_sleep", "work_event", "social_event", "supplement_change", "custom",
}
DEFAULT_START_DELAYS = {"k6": 7, "cbi": 14, "spane": 21, "rses": 28, "swls": 35}


class MentalHealthError(ValueError):
    def __init__(self, message, *, status=400, code="mental_health_invalid"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self):
        return {"ok": False, "error": str(self), "code": self.code}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value=None):
    return (value or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value, field="date"):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise MentalHealthError(f"{field} is required")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MentalHealthError(f"Invalid {field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json(value, fallback):
    if value is None:
        return fallback
    try:
        decoded = json.loads(value)
        return decoded
    except (TypeError, json.JSONDecodeError):
        return fallback


def calculate_schedule_status(schedule, last_completed_at=None, *, now=None):
    now = parse_datetime(now or utc_now(), "now")
    if not schedule.get("enabled", True):
        return {"status": "paused", "nextDueAt": None, "lastCompletedAt": last_completed_at}
    if schedule.get("paused"):
        return {"status": "paused", "nextDueAt": None, "lastCompletedAt": last_completed_at}
    if not last_completed_at:
        return {"status": "not_started", "nextDueAt": iso(now), "lastCompletedAt": None}
    last = parse_datetime(last_completed_at, "lastCompletedAt")
    if last.date() == now.date():
        return {"status": "completed_today", "nextDueAt": None if schedule.get("baselineOnly") else iso(last + timedelta(days=int(schedule.get("userCadenceDays") or schedule.get("defaultCadenceDays") or 0))), "lastCompletedAt": iso(last)}
    if schedule.get("baselineOnly"):
        return {"status": "not_due", "nextDueAt": None, "lastCompletedAt": iso(last)}
    cadence = schedule.get("userCadenceDays") or schedule.get("defaultCadenceDays")
    if not cadence:
        return {"status": "not_due", "nextDueAt": None, "lastCompletedAt": iso(last)}
    due = last + timedelta(days=int(cadence))
    if due.date() < now.date():
        status = "overdue"
    elif due.date() == now.date():
        status = "due"
    elif due <= now + timedelta(days=7):
        status = "due_soon"
    else:
        status = "not_due"
    return {"status": status, "nextDueAt": iso(due), "lastCompletedAt": iso(last)}


def early_retest_warning(instrument, last_completed_at, *, now=None):
    if not last_completed_at or not instrument.get("minimumRetestDays"):
        return None
    now = parse_datetime(now or utc_now(), "now")
    last = parse_datetime(last_completed_at, "lastCompletedAt")
    available = last + timedelta(days=int(instrument["minimumRetestDays"]))
    if now < available:
        return {
            "message": "To badanie wykonano niedawno. Powtórzenie go teraz może wnieść niewiele informacji.",
            "recommendedAfter": iso(available),
        }
    return None


def _rank(values):
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor
        while end + 1 < len(order) and values[order[end + 1]] == values[order[cursor]]:
            end += 1
        average_rank = (cursor + end + 2) / 2
        for position in range(cursor, end + 1):
            ranks[order[position]] = average_rank
        cursor = end + 1
    return ranks


def spearman(values_a, values_b):
    if len(values_a) != len(values_b) or len(values_a) < 2:
        return None
    ranks_a, ranks_b = _rank(values_a), _rank(values_b)
    mean_a, mean_b = mean(ranks_a), mean(ranks_b)
    numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(ranks_a, ranks_b))
    denominator = math.sqrt(sum((a - mean_a) ** 2 for a in ranks_a) * sum((b - mean_b) ** 2 for b in ranks_b))
    return round(numerator / denominator, 3) if denominator else None


class MentalHealthStore:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS schedules (
                        instrument_id TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL DEFAULT 0,
                        paused INTEGER NOT NULL DEFAULT 0,
                        baseline_only INTEGER NOT NULL DEFAULT 0,
                        user_cadence_days INTEGER,
                        snoozed_until TEXT,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS assessments (
                        id TEXT PRIMARY KEY,
                        instrument_id TEXT NOT NULL,
                        instrument_version TEXT NOT NULL,
                        language TEXT NOT NULL,
                        scoring_version TEXT NOT NULL,
                        completed_at TEXT NOT NULL,
                        raw_score REAL,
                        normalized_score REAL,
                        subscale_scores_json TEXT NOT NULL,
                        interpretation_json TEXT,
                        responses_json TEXT NOT NULL,
                        context_snapshot_json TEXT NOT NULL,
                        notes TEXT NOT NULL DEFAULT '',
                        source_note TEXT NOT NULL DEFAULT '',
                        source_url TEXT NOT NULL DEFAULT '',
                        file_reference TEXT NOT NULL DEFAULT '',
                        definition_snapshot_json TEXT NOT NULL,
                        is_baseline INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mh_assessment_instrument_date
                        ON assessments(instrument_id, completed_at DESC);
                    CREATE TABLE IF NOT EXISTS responses (
                        assessment_id TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                        item_id TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        PRIMARY KEY (assessment_id, item_id)
                    );
                    CREATE TABLE IF NOT EXISTS checkins (
                        id TEXT PRIMARY KEY,
                        recorded_at TEXT NOT NULL,
                        values_json TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        tags_json TEXT NOT NULL,
                        flags_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mh_checkin_date ON checkins(recorded_at DESC);
                    CREATE TABLE IF NOT EXISTS events (
                        id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        title TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        tags_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_mh_event_date ON events(occurred_at DESC);
                    CREATE TABLE IF NOT EXISTS drafts (
                        instrument_id TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS custom_definitions (
                        id TEXT PRIMARY KEY,
                        definition_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                stamp = iso()
                for instrument in get_registry():
                    baseline_only = int(instrument["constructType"] == "trait" or instrument["defaultCadenceDays"] is None)
                    start_delay = DEFAULT_START_DELAYS.get(instrument["id"], 0)
                    snoozed_until = iso(utc_now() + timedelta(days=start_delay)) if start_delay else None
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO schedules(
                            instrument_id, enabled, paused, baseline_only, user_cadence_days, snoozed_until, updated_at
                        ) VALUES (?, ?, 0, ?, NULL, ?, ?)
                        """,
                        (instrument["id"], int(instrument["enabledByDefault"]), baseline_only, snoozed_until, stamp),
                    )
                defaults = {key: True for key in CHECKIN_FIELDS}
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value_json, updated_at) VALUES('checkin_fields', ?, ?)",
                    (json.dumps(defaults), stamp),
                )
            self._initialized = True

    def health(self):
        self.initialize()
        return {"ok": True, "schemaVersion": SCHEMA_VERSION, "database": self.database_path.name}

    def registry(self):
        self.initialize()
        items = get_registry()
        with self._connect() as connection:
            rows = connection.execute("SELECT definition_json FROM custom_definitions ORDER BY created_at").fetchall()
        for row in rows:
            definition = _json(row["definition_json"], None)
            if isinstance(definition, dict):
                items.append(definition)
        return items

    def _instrument(self, instrument_id):
        instrument_id = str(instrument_id or "")
        for instrument in self.registry():
            if instrument["id"] == instrument_id:
                return instrument
        raise MentalHealthError("Unknown instrument", code="unknown_instrument")

    def create_custom_definition(self, payload):
        self.initialize()
        name = str(payload.get("name") or "").strip()
        if not name:
            raise MentalHealthError("Custom questionnaire name is required")
        source_questions = payload.get("questions") or []
        if not isinstance(source_questions, list) or not source_questions:
            raise MentalHealthError("At least one custom question is required")
        if len(source_questions) > 100:
            raise MentalHealthError("Custom questionnaire can contain at most 100 questions")
        try:
            response_min = int(payload.get("responseMin", 0))
            response_max = int(payload.get("responseMax", 4))
            cadence = int(payload.get("defaultCadenceDays", 7))
        except (TypeError, ValueError) as exc:
            raise MentalHealthError("Custom scale and cadence must be whole numbers") from exc
        if response_min >= response_max or response_max - response_min > 10:
            raise MentalHealthError("Custom response range must be ordered and no wider than 10 points")
        if not 1 <= cadence <= 3650:
            raise MentalHealthError("Cadence must be between 1 and 3650 days")
        questions = []
        subscale_ids = set()
        for index, source in enumerate(source_questions, 1):
            source = source if isinstance(source, dict) else {"text": source}
            text = str(source.get("text") or "").strip()
            if not text:
                raise MentalHealthError(f"Custom question {index} is empty")
            subscale = str(source.get("subscale") or "").strip()[:80]
            if subscale:
                subscale_ids.add(subscale)
            questions.append({"id": str(index), "text": text[:500], "required": True, "reverse": bool(source.get("reverse")), "subscale": subscale or None})
        instrument_id = str(payload.get("id") or f"custom_{uuid.uuid4().hex[:12]}")
        if not instrument_id.startswith("custom_"):
            raise MentalHealthError("Custom questionnaire id must start with custom_")
        definition = {
            "id": instrument_id, "name": name[:160], "shortName": str(payload.get("shortName") or name)[:40],
            "category": "custom", "description": str(payload.get("description") or "Osobisty tracker trendu.")[:1000],
            "constructType": str(payload.get("constructType") or "state") if str(payload.get("constructType") or "state") in {"state", "trait", "mixed"} else "state",
            "questionnaireMode": "native", "questionTextStatus": "user_supplied", "defaultCadenceDays": cadence,
            "minimumRetestDays": max(1, int(payload.get("minimumRetestDays") or cadence)),
            "recallPeriod": str(payload.get("recallPeriod") or "user defined")[:160], "estimatedMinutes": max(1, math.ceil(len(questions) / 4)),
            "itemCount": len(questions), "language": str(payload.get("language") or "pl")[:20], "version": "1.0", "scoringVersion": "custom-sum@1",
            "source": "User-created definition", "licenseStatus": "user supplied", "licenseNotice": "",
            "scoreMin": response_min * len(questions), "scoreMax": response_max * len(questions), "higherIsBetter": bool(payload.get("higherIsBetter", False)),
            "requiresTotalScore": True,
            "subscales": [{"id": key, "name": key} for key in sorted(subscale_ids)],
            "responseOptions": [{"value": value, "label": str(value)} for value in range(response_min, response_max + 1)],
            "questions": questions, "scoring": {"type": "custom_sum", "responseMin": response_min, "responseMax": response_max},
            "interpretationBands": [], "specialFlags": [], "enabledByDefault": True, "custom": True,
            "disclaimer": "CUSTOM — niestandaryzowany tracker osobisty, nie test psychologiczny.",
        }
        stamp = iso()
        with self._lock, self._connect() as connection:
            if connection.execute("SELECT 1 FROM custom_definitions WHERE id=?", (instrument_id,)).fetchone():
                raise MentalHealthError("Custom questionnaire id already exists", status=409, code="duplicate_definition")
            connection.execute("INSERT INTO custom_definitions(id, definition_json, created_at, updated_at) VALUES (?, ?, ?, ?)", (instrument_id, json.dumps(definition, ensure_ascii=False), stamp, stamp))
            connection.execute("INSERT INTO schedules(instrument_id, enabled, paused, baseline_only, user_cadence_days, snoozed_until, updated_at) VALUES (?, 1, 0, ?, NULL, NULL, ?)", (instrument_id, int(definition["constructType"] == "trait"), stamp))
        return definition

    @staticmethod
    def _score_custom(instrument, responses):
        if not isinstance(responses, dict):
            raise MentalHealthError("Custom responses must be an object", code="invalid_responses")
        low = instrument["scoring"]["responseMin"]
        high = instrument["scoring"]["responseMax"]
        adjusted = []
        grouped = {}
        for question in instrument["questions"]:
            if question["id"] not in responses:
                raise MentalHealthError("All required responses must be answered", code="missing_answers")
            try:
                value = float(responses[question["id"]])
            except (TypeError, ValueError) as exc:
                raise MentalHealthError("Custom responses must be numeric", code="invalid_responses") from exc
            if value < low or value > high:
                raise MentalHealthError("Custom response is outside its scale", code="invalid_responses")
            value = low + high - value if question.get("reverse") else value
            adjusted.append(value)
            if question.get("subscale"):
                grouped.setdefault(question["subscale"], []).append(value)
        return {"rawScore": sum(adjusted), "normalizedScore": round((sum(adjusted) - instrument["scoreMin"]) / (instrument["scoreMax"] - instrument["scoreMin"]) * 100, 2), "subscaleScores": {key: sum(values) for key, values in grouped.items()}}

    @staticmethod
    def _assessment(row):
        return {
            "id": row["id"], "instrumentId": row["instrument_id"],
            "instrumentVersion": row["instrument_version"], "language": row["language"],
            "scoringVersion": row["scoring_version"], "completedAt": row["completed_at"],
            "rawScore": row["raw_score"], "normalizedScore": row["normalized_score"],
            "subscaleScores": _json(row["subscale_scores_json"], {}),
            "interpretation": _json(row["interpretation_json"], None),
            "responses": _json(row["responses_json"], {}),
            "contextSnapshot": _json(row["context_snapshot_json"], {}),
            "notes": row["notes"], "sourceNote": row["source_note"],
            "sourceUrl": row["source_url"], "fileReference": row["file_reference"],
            "isBaseline": bool(row["is_baseline"]), "createdAt": row["created_at"],
        }

    @staticmethod
    def _schedule(row, instrument, last_completed_at=None, now=None):
        schedule = {
            "instrumentId": row["instrument_id"], "enabled": bool(row["enabled"]),
            "paused": bool(row["paused"]), "baselineOnly": bool(row["baseline_only"]),
            "defaultCadenceDays": instrument.get("defaultCadenceDays"),
            "userCadenceDays": row["user_cadence_days"], "snoozedUntil": row["snoozed_until"],
        }
        calculated = calculate_schedule_status(schedule, last_completed_at, now=now)
        if row["snoozed_until"] and calculated["status"] in {"not_started", "due", "overdue"}:
            snoozed = parse_datetime(row["snoozed_until"], "snoozedUntil")
            if snoozed > parse_datetime(now or utc_now(), "now"):
                calculated.update({"status": "due_soon", "nextDueAt": iso(snoozed)})
        schedule.update(calculated)
        return schedule

    def schedules(self, *, now=None):
        self.initialize()
        registry = {item["id"]: item for item in self.registry()}
        with self._connect() as connection:
            last_rows = connection.execute(
                "SELECT instrument_id, MAX(completed_at) AS completed_at FROM assessments GROUP BY instrument_id"
            ).fetchall()
            last = {row["instrument_id"]: row["completed_at"] for row in last_rows}
            rows = connection.execute("SELECT * FROM schedules ORDER BY instrument_id").fetchall()
        return [self._schedule(row, registry[row["instrument_id"]], last.get(row["instrument_id"]), now) for row in rows if row["instrument_id"] in registry]

    def update_schedule(self, instrument_id, payload):
        self.initialize()
        self._instrument(instrument_id)
        enabled = int(bool(payload.get("enabled", True)))
        paused = int(bool(payload.get("paused", False)))
        baseline_only = int(bool(payload.get("baselineOnly", False)))
        cadence = payload.get("userCadenceDays")
        if cadence in (None, ""):
            cadence = None
        else:
            try:
                cadence = int(cadence)
            except (TypeError, ValueError) as exc:
                raise MentalHealthError("Cadence must be a whole number of days") from exc
            if not 1 <= cadence <= 3650:
                raise MentalHealthError("Cadence must be between 1 and 3650 days")
        snoozed = payload.get("snoozedUntil") or None
        if snoozed:
            snoozed = iso(parse_datetime(snoozed, "snoozedUntil"))
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE schedules SET enabled=?, paused=?, baseline_only=?, user_cadence_days=?,
                   snoozed_until=?, updated_at=? WHERE instrument_id=?""",
                (enabled, paused, baseline_only, cadence, snoozed, iso(), instrument_id),
            )
        return next(row for row in self.schedules() if row["instrumentId"] == instrument_id)

    def list_assessments(self, instrument_id=None, limit=500):
        self.initialize()
        limit = max(1, min(int(limit), 5000))
        query = "SELECT * FROM assessments"
        params = []
        if instrument_id:
            self._instrument(instrument_id)
            query += " WHERE instrument_id=?"
            params.append(instrument_id)
        query += " ORDER BY completed_at DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            return [self._assessment(row) for row in connection.execute(query, params).fetchall()]

    def create_assessment(self, payload):
        self.initialize()
        instrument_id = str(payload.get("instrumentId") or "").strip()
        instrument = self._instrument(instrument_id)
        completed = iso(parse_datetime(payload.get("completedAt") or utc_now(), "completedAt"))
        responses = payload.get("responses")
        if responses not in (None, {}, []):
            if instrument_id.startswith("custom_") and instrument["scoring"]["type"] == "custom_sum":
                result = self._score_custom(instrument, responses)
            else:
                try:
                    result = score_instrument(instrument_id, responses, scoring_override=payload.get("scoringOverride"))
                except MentalHealthScoringError as exc:
                    raise MentalHealthError(str(exc), code="invalid_responses") from exc
            raw_score = result.get("rawScore")
            normalized = result.get("normalizedScore")
            subscales = result.get("subscaleScores", {})
        else:
            if instrument["questionnaireMode"] != "external-score":
                raise MentalHealthError("All required responses must be answered", code="missing_answers")
            subscales = payload.get("subscaleScores") or {}
            if instrument.get("requiresTotalScore", True):
                try:
                    raw_score = float(payload["totalScore"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise MentalHealthError("A numeric total score is required", code="missing_score") from exc
                if not math.isfinite(raw_score):
                    raise MentalHealthError("Score must be finite")
                low, high = instrument.get("scoreMin"), instrument.get("scoreMax")
                if low is not None and raw_score < low or high is not None and raw_score > high:
                    raise MentalHealthError(f"Score must be between {low} and {high}")
                span = high - low if low is not None and high is not None else None
                normalized = round((raw_score - low) / span * 100, 2) if span else None
            else:
                raw_score = None
                normalized = None
                if not subscales:
                    raise MentalHealthError("At least one subscale score is required", code="missing_score")
            responses = {}
        if not isinstance(subscales, dict):
            raise MentalHealthError("Subscale scores must be an object")
        for key, value in subscales.items():
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise MentalHealthError(f"Invalid subscale score: {key}") from exc
            if not math.isfinite(number):
                raise MentalHealthError(f"Invalid subscale score: {key}")
            subscales[key] = number
        assessment_id = str(payload.get("id") or uuid.uuid4())
        interpretation = interpretation_for(instrument, raw_score, responses)
        stamp = iso()
        with self._lock, self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM assessments WHERE id=?", (assessment_id,)).fetchone()
            if exists:
                raise MentalHealthError("Assessment id already exists", status=409, code="duplicate_assessment")
            baseline_exists = connection.execute(
                "SELECT 1 FROM assessments WHERE instrument_id=? AND is_baseline=1", (instrument_id,)
            ).fetchone()
            is_baseline = int(bool(payload.get("isBaseline")) or baseline_exists is None)
            if is_baseline and baseline_exists is not None and payload.get("isBaseline"):
                connection.execute("UPDATE assessments SET is_baseline=0 WHERE instrument_id=?", (instrument_id,))
            connection.execute(
                """INSERT INTO assessments(
                    id, instrument_id, instrument_version, language, scoring_version, completed_at,
                    raw_score, normalized_score, subscale_scores_json, interpretation_json,
                    responses_json, context_snapshot_json, notes, source_note, source_url,
                    file_reference, definition_snapshot_json, is_baseline, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id, instrument_id, instrument["version"], payload.get("language") or instrument["language"],
                    instrument["scoringVersion"], completed, raw_score, normalized,
                    json.dumps(subscales, ensure_ascii=False), json.dumps(interpretation, ensure_ascii=False),
                    json.dumps(responses or {}, ensure_ascii=False), json.dumps(payload.get("contextSnapshot") or {}, ensure_ascii=False),
                    str(payload.get("notes") or "")[:5000], str(payload.get("sourceNote") or "")[:1000],
                    str(payload.get("sourceUrl") or "")[:2000], str(payload.get("fileReference") or "")[:2000],
                    json.dumps(instrument, ensure_ascii=False), is_baseline, stamp,
                ),
            )
            iterable = responses.items() if isinstance(responses, dict) else enumerate(responses, 1)
            for item_id, value in iterable:
                connection.execute(
                    "INSERT INTO responses(assessment_id, item_id, value_json) VALUES (?, ?, ?)",
                    (assessment_id, str(item_id), json.dumps(value, ensure_ascii=False)),
                )
            connection.execute("DELETE FROM drafts WHERE instrument_id=?", (instrument_id,))
        result = self.get_assessment(assessment_id)
        result["safetyNotice"] = self._safety_notice(instrument_id, responses)
        result["earlyRetestWarning"] = self._retest_warning_for(instrument_id, completed, exclude_id=assessment_id)
        return result

    def _retest_warning_for(self, instrument_id, completed, exclude_id=None):
        query = "SELECT completed_at FROM assessments WHERE instrument_id=?"
        params = [instrument_id]
        if exclude_id:
            query += " AND id<>?"
            params.append(exclude_id)
        query += " ORDER BY completed_at DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return early_retest_warning(self._instrument(instrument_id), row["completed_at"] if row else None, now=completed)

    @staticmethod
    def _safety_notice(instrument_id, responses):
        if instrument_id != "phq9" or not responses:
            return None
        value = responses.get("9", responses.get(9)) if isinstance(responses, dict) else responses[8]
        if float(value or 0) <= 0:
            return None
        return {
            "title": "Warto omówić tę odpowiedź z profesjonalistą",
            "message": "PHQ-9 jest kwestionariuszem przesiewowym. Odpowiedź na pozycję dotyczącą samouszkodzenia wymaga dalszej, indywidualnej oceny — nie jest wyliczeniem ryzyka.",
            "resources": [
                {"label": "Numer alarmowy", "value": "112"},
                {"label": "Ratownictwo medyczne", "value": "999"},
                {"label": "Całodobowe wsparcie dla dorosłych", "value": "800 70 2222"},
            ],
        }

    def get_assessment(self, assessment_id):
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
        if not row:
            raise MentalHealthError("Assessment not found", status=404, code="not_found")
        return self._assessment(row)

    def set_baseline(self, assessment_id):
        assessment = self.get_assessment(assessment_id)
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE assessments SET is_baseline=0 WHERE instrument_id=?", (assessment["instrumentId"],))
            connection.execute("UPDATE assessments SET is_baseline=1 WHERE id=?", (assessment_id,))
        return self.get_assessment(assessment_id)

    def delete_assessment(self, assessment_id):
        assessment = self.get_assessment(assessment_id)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM assessments WHERE id=?", (assessment_id,))
            if assessment["isBaseline"]:
                row = connection.execute(
                    "SELECT id FROM assessments WHERE instrument_id=? ORDER BY completed_at ASC LIMIT 1",
                    (assessment["instrumentId"],),
                ).fetchone()
                if row:
                    connection.execute("UPDATE assessments SET is_baseline=1 WHERE id=?", (row["id"],))
        return {"ok": True, "deleted": assessment_id}

    def save_draft(self, instrument_id, payload):
        self.initialize()
        instrument = self._instrument(instrument_id)
        if instrument["questionnaireMode"] != "native":
            raise MentalHealthError("Drafts are available only for native questionnaires")
        if not isinstance(payload, dict):
            raise MentalHealthError("Draft payload must be an object")
        responses = payload.get("responses") or {}
        if not isinstance(responses, dict):
            raise MentalHealthError("Draft responses must be an object")
        questions = {str(question["id"]): question for question in instrument.get("questions", [])}
        clean_responses = {}
        for item_id, value in responses.items():
            item_id = str(item_id)
            if item_id not in questions:
                raise MentalHealthError(f"Unknown draft item: {item_id}")
            options = questions[item_id].get("responseOptions") or instrument.get("responseOptions") or []
            allowed = {float(option["value"]) for option in options}
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise MentalHealthError(f"Invalid draft response: {item_id}") from exc
            if number not in allowed:
                raise MentalHealthError(f"Invalid draft response: {item_id}")
            clean_responses[item_id] = int(number) if number.is_integer() else number
        clean = {
            "responses": clean_responses,
            "notes": str(payload.get("notes") or "")[:5000],
            "completedAt": str(payload.get("completedAt") or "")[:80],
        }
        updated_at = iso()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO drafts(instrument_id, payload_json, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(instrument_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
                (instrument_id, json.dumps(clean, ensure_ascii=False), updated_at),
            )
        return {"ok": True, "instrumentId": instrument_id, "payload": clean, "updatedAt": updated_at}

    def list_drafts(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT instrument_id, payload_json, updated_at FROM drafts ORDER BY updated_at DESC").fetchall()
        return {
            row["instrument_id"]: {
                "instrumentId": row["instrument_id"],
                "payload": _json(row["payload_json"], {}),
                "updatedAt": row["updated_at"],
            }
            for row in rows
        }

    def list_checkins(self, limit=500):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM checkins ORDER BY recorded_at DESC LIMIT ?", (max(1, min(int(limit), 5000)),)).fetchall()
        return [{"id": row["id"], "recordedAt": row["recorded_at"], "values": _json(row["values_json"], {}), "note": row["note"], "tags": _json(row["tags_json"], []), "flags": _json(row["flags_json"], []), "createdAt": row["created_at"]} for row in rows]

    def create_checkin(self, payload):
        values = payload.get("values") or {}
        if not isinstance(values, dict) or not values:
            raise MentalHealthError("At least one check-in value is required")
        clean = {}
        for key, value in values.items():
            if key not in CHECKIN_FIELDS:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise MentalHealthError(f"Invalid check-in value: {key}") from exc
            if not 0 <= number <= 10:
                raise MentalHealthError("Check-in values must be between 0 and 10")
            clean[key] = number
        if not clean:
            raise MentalHealthError("At least one known check-in value is required")
        item = {
            "id": str(payload.get("id") or uuid.uuid4()),
            "recordedAt": iso(parse_datetime(payload.get("recordedAt") or utc_now(), "recordedAt")),
            "values": clean, "note": str(payload.get("note") or "")[:2000],
            "tags": [str(tag)[:80] for tag in (payload.get("tags") or [])][:30],
            "flags": [str(flag) for flag in (payload.get("flags") or []) if str(flag) in EVENT_TYPES],
            "createdAt": iso(),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO checkins(id, recorded_at, values_json, note, tags_json, flags_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item["id"], item["recordedAt"], json.dumps(clean), item["note"], json.dumps(item["tags"], ensure_ascii=False), json.dumps(item["flags"]), item["createdAt"]),
            )
        return item

    def list_events(self, limit=500):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM events ORDER BY occurred_at DESC LIMIT ?", (max(1, min(int(limit), 5000)),)).fetchall()
        return [{"id": row["id"], "eventType": row["event_type"], "occurredAt": row["occurred_at"], "title": row["title"], "note": row["note"], "tags": _json(row["tags_json"], []), "createdAt": row["created_at"]} for row in rows]

    def create_event(self, payload):
        event_type = str(payload.get("eventType") or "custom")
        if event_type not in EVENT_TYPES:
            raise MentalHealthError("Unknown event type")
        title = str(payload.get("title") or "").strip()
        if not title:
            raise MentalHealthError("Event title is required")
        item = {"id": str(payload.get("id") or uuid.uuid4()), "eventType": event_type, "occurredAt": iso(parse_datetime(payload.get("occurredAt") or utc_now(), "occurredAt")), "title": title[:200], "note": str(payload.get("note") or "")[:2000], "tags": [str(tag)[:80] for tag in (payload.get("tags") or [])][:30], "createdAt": iso()}
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO events(id, event_type, occurred_at, title, note, tags_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (item["id"], event_type, item["occurredAt"], item["title"], item["note"], json.dumps(item["tags"], ensure_ascii=False), item["createdAt"]))
        return item

    def delete_entry(self, table, entry_id):
        if table not in {"checkins", "events"}:
            raise MentalHealthError("Invalid entry type")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(f"DELETE FROM {table} WHERE id=?", (entry_id,))
        if not cursor.rowcount:
            raise MentalHealthError("Entry not found", status=404, code="not_found")
        return {"ok": True, "deleted": entry_id}

    def analytics(self, days=90):
        assessments = self.list_assessments(limit=5000)
        now = utc_now()
        cutoff = now - timedelta(days=max(1, int(days)))
        recent = [item for item in assessments if parse_datetime(item["completedAt"]) >= cutoff]
        grouped = {}
        for item in recent:
            if item["rawScore"] is not None:
                grouped.setdefault(item["instrumentId"], []).append((float(item["rawScore"]), item))
            for subscale_id, value in item["subscaleScores"].items():
                if subscale_id == "percentage":
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                grouped.setdefault(f'{item["instrumentId"]}:{subscale_id}', []).append((number, item))
        instruments = {item["id"]: item for item in self.registry()}
        summaries = []
        for dimension_id, points in grouped.items():
            instrument_id, _, subscale_id = dimension_id.partition(":")
            values = [point[0] for point in points]
            instrument = instruments[instrument_id]
            subscale_name = next((row["name"] for row in instrument.get("subscales", []) if row["id"] == subscale_id), subscale_id) if subscale_id else None
            values28 = [value for value, item in points if parse_datetime(item["completedAt"]) >= now - timedelta(days=28)]
            values90 = [value for value, item in points if parse_datetime(item["completedAt"]) >= now - timedelta(days=90)]
            baseline_point = next((value for value, item in points if item["isBaseline"]), values[-1])
            summaries.append({
                "dimensionId": dimension_id, "instrumentId": instrument_id, "subscaleId": subscale_id or None,
                "shortName": f'{instrument["shortName"]} · {subscale_name}' if subscale_name else instrument["shortName"],
                "count": len(values), "first": values[-1], "latest": values[0],
                "previous": values[1] if len(values) > 1 else None, "min": min(values), "max": max(values),
                "mean": round(mean(values), 2), "median": round(median(values), 2),
                "mean28": round(mean(values28), 2) if values28 else None,
                "mean90": round(mean(values90), 2) if values90 else None,
                "changeFromBaseline": round(values[0] - baseline_point, 2),
                "changeFromPrevious": round(values[0] - values[1], 2) if len(values) > 1 else None,
                "range": round(max(values) - min(values), 2),
            })
        stable = min((row for row in summaries if row["count"] >= 2), key=lambda row: row["range"], default=None)
        largest = max((row for row in summaries if row["changeFromPrevious"] is not None), key=lambda row: abs(row["changeFromPrevious"]), default=None)
        checkins_by_day = {}
        for checkin in self.list_checkins(limit=5000):
            checkins_by_day.setdefault(checkin["recordedAt"][:10], checkin)
        correlations = []
        for dimension in summaries:
            points = grouped[dimension["dimensionId"]]
            for field in CHECKIN_FIELDS:
                pairs = [
                    (value, checkins_by_day[item["completedAt"][:10]]["values"][field])
                    for value, item in points
                    if field in checkins_by_day.get(item["completedAt"][:10], {}).get("values", {})
                ]
                if len(pairs) < 10:
                    continue
                coefficient = spearman([pair[0] for pair in pairs], [pair[1] for pair in pairs])
                if coefficient is not None:
                    correlations.append({"dimensionId": dimension["dimensionId"], "dimension": dimension["shortName"], "checkinField": field, "n": len(pairs), "coefficient": coefficient, "method": "spearman", "notice": "Exploratory association — does not establish causation"})
        return {"days": int(days), "assessmentCount": len(recent), "instruments": summaries, "mostStableDimension": stable, "largestNumericChange": largest, "correlations": correlations, "correlationNotice": "Korelacje pojawią się po co najmniej 10–12 dopasowanych obserwacjach. Są eksploracyjne i nie dowodzą przyczynowości."}

    def overview(self, *, now=None):
        self.initialize()
        registry = self.registry()
        schedules = self.schedules(now=now)
        assessments = self.list_assessments(limit=5000)
        checkins = self.list_checkins(limit=366)
        events = self.list_events(limit=500)
        by_instrument = {}
        for item in assessments:
            by_instrument.setdefault(item["instrumentId"], []).append(item)
        latest = []
        for instrument in registry:
            rows = by_instrument.get(instrument["id"], [])
            if not rows:
                continue
            current, previous = rows[0], rows[1] if len(rows) > 1 else None
            baseline = next((row for row in rows if row["isBaseline"]), rows[-1])
            latest.append({"instrument": instrument, "current": current, "previous": previous, "baseline": baseline, "changeFromPrevious": current["rawScore"] - previous["rawScore"] if previous and current["rawScore"] is not None and previous["rawScore"] is not None else None, "history": [{"completedAt": row["completedAt"], "rawScore": row["rawScore"], "subscaleScores": row["subscaleScores"]} for row in reversed(rows[:20])]})
        actionable = [row for row in schedules if row["enabled"] and row["status"] in {"not_started", "due", "overdue"}]
        upcoming = sorted((row for row in schedules if row["enabled"] and row["nextDueAt"]), key=lambda row: row["nextDueAt"])
        return {"schemaVersion": SCHEMA_VERSION, "registry": registry, "schedules": schedules, "latest": latest, "assessments": assessments, "checkins": checkins, "events": events, "drafts": self.list_drafts(), "dueCount": len(actionable), "lastCheckin": checkins[0] if checkins else None, "nextScheduled": upcoming[0] if upcoming else None, "analytics90": self.analytics(90), "settings": self.settings()}

    def settings(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value_json FROM settings").fetchall()
        return {row["key"]: _json(row["value_json"], {}) for row in rows}

    def update_settings(self, payload):
        allowed = {}
        if "checkin_fields" in payload:
            source = payload["checkin_fields"] or {}
            allowed["checkin_fields"] = {key: bool(source.get(key, False)) for key in CHECKIN_FIELDS}
        with self._lock, self._connect() as connection:
            for key, value in allowed.items():
                connection.execute("INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at", (key, json.dumps(value), iso()))
        return self.settings()

    def export_data(self):
        self.initialize()
        registry = self.registry()
        return {"schemaVersion": SCHEMA_VERSION, "exportedAt": iso(), "assessments": self.list_assessments(limit=5000), "checkins": self.list_checkins(limit=5000), "events": self.list_events(limit=5000), "schedules": self.schedules(), "instrumentVersions": [{"id": item["id"], "version": item["version"], "scoringVersion": item["scoringVersion"], "questionTextStatus": item["questionTextStatus"]} for item in registry], "customDefinitions": [item for item in registry if item["id"].startswith("custom_")], "settings": self.settings()}

    def import_data(self, payload):
        if int(payload.get("schemaVersion", 0)) != SCHEMA_VERSION:
            raise MentalHealthError("Unsupported export schema version")
        imported = {"assessments": 0, "checkins": 0, "events": 0, "schedules": 0}
        for definition in payload.get("customDefinitions", []):
            try:
                self.create_custom_definition({
                    "id": definition.get("id"), "name": definition.get("name"), "shortName": definition.get("shortName"),
                    "description": definition.get("description"), "constructType": definition.get("constructType"),
                    "defaultCadenceDays": definition.get("defaultCadenceDays"), "minimumRetestDays": definition.get("minimumRetestDays"),
                    "recallPeriod": definition.get("recallPeriod"), "language": definition.get("language"),
                    "responseMin": definition.get("scoring", {}).get("responseMin", 0), "responseMax": definition.get("scoring", {}).get("responseMax", 4),
                    "higherIsBetter": definition.get("higherIsBetter"), "questions": definition.get("questions"),
                })
            except MentalHealthError as exc:
                if exc.code != "duplicate_definition":
                    raise
        for schedule in payload.get("schedules", []):
            instrument_id = schedule.get("instrumentId")
            if instrument_id in {item["id"] for item in self.registry()}:
                self.update_schedule(instrument_id, schedule)
                imported["schedules"] += 1
        for assessment in reversed(payload.get("assessments", [])):
            try:
                create = {"id": assessment.get("id"), "instrumentId": assessment.get("instrumentId"), "completedAt": assessment.get("completedAt"), "totalScore": assessment.get("rawScore"), "subscaleScores": assessment.get("subscaleScores"), "notes": assessment.get("notes"), "sourceNote": assessment.get("sourceNote"), "sourceUrl": assessment.get("sourceUrl"), "fileReference": assessment.get("fileReference"), "contextSnapshot": assessment.get("contextSnapshot"), "language": assessment.get("language"), "isBaseline": assessment.get("isBaseline")}
                if assessment.get("responses"):
                    create["responses"] = assessment["responses"]
                self.create_assessment(create)
                imported["assessments"] += 1
            except MentalHealthError as exc:
                if exc.code != "duplicate_assessment":
                    raise
        for item in payload.get("checkins", []):
            try:
                self.create_checkin({"id": item.get("id"), "recordedAt": item.get("recordedAt"), "values": item.get("values"), "note": item.get("note"), "tags": item.get("tags"), "flags": item.get("flags")})
                imported["checkins"] += 1
            except sqlite3.IntegrityError:
                pass
        for item in payload.get("events", []):
            try:
                self.create_event({"id": item.get("id"), "eventType": item.get("eventType"), "occurredAt": item.get("occurredAt"), "title": item.get("title"), "note": item.get("note"), "tags": item.get("tags")})
                imported["events"] += 1
            except sqlite3.IntegrityError:
                pass
        if payload.get("settings"):
            self.update_settings(payload["settings"])
        return {"ok": True, "imported": imported}

    def delete_all(self):
        self.initialize()
        with self._lock, self._connect() as connection:
            for table in ("responses", "assessments", "checkins", "events", "drafts", "custom_definitions", "schedules", "settings"):
                connection.execute(f"DELETE FROM {table}")
        self._initialized = False
        self.initialize()
        return {"ok": True}


MENTAL_HEALTH_STORE = MentalHealthStore(Path(__file__).resolve().parent / "data" / "mental-health.sqlite")
