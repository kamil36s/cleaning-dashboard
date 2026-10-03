"""Build the data-only Antigravity context from local dashboard state.

This exporter intentionally lives outside antigravity-context so that the
isolated workspace contains data and documentation, never application code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "antigravity-context"
CURRENT = OUT / "snapshots" / "current"
SCHEMAS = OUT / "schemas"
SUMMARY_DIR = OUT / "summaries"
LOCAL_TZ_NAME = "Europe/Warsaw"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        stamp = int(text)
        if stamp > 10_000_000_000:
            stamp /= 1000
        return datetime.fromtimestamp(stamp, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(text[:10]), datetime.min.time(), timezone.utc)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value: Any) -> date | None:
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, 2)


def trend(current: float | None, previous: float | None, tolerance_pct: float = 2.0) -> str:
    change = pct_change(current, previous)
    if change is None:
        return "unknown"
    if change > tolerance_pct:
        return "increasing"
    if change < -tolerance_pct:
        return "decreasing"
    return "stable"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        pass
    return rows


def connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def source_timestamp(*paths: Path) -> str | None:
    existing = [path.stat().st_mtime for path in paths if path.exists()]
    return iso_utc(datetime.fromtimestamp(max(existing), timezone.utc)) if existing else None


def envelope(dataset: str, generated_at: str, freshness: str | None, **payload: Any) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "schema_version": 1,
        "generated_at": generated_at,
        "source_freshness": freshness,
        **payload,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def alias(value: str, prefix: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


def window_dates(as_of: date, days: int, offset: int = 0) -> set[date]:
    end = as_of - timedelta(days=offset)
    return {end - timedelta(days=index) for index in range(days)}


def build_tasks(generated_at: str, today: date) -> dict[str, Any]:
    path = DATA / "settings" / "todo.json"
    items = [item for item in read_json(path, []) if isinstance(item, dict)]
    open_items = [item for item in items if not item.get("done")]
    due_items: list[dict[str, Any]] = []
    overdue = 0
    due_7d = 0
    for item in open_items:
        due = parse_date(item.get("due"))
        if due:
            delta = (due - today).days
            overdue += int(delta < 0)
            due_7d += int(0 <= delta <= 7)
            due_items.append({
                "id": alias(str(item.get("id", "unknown")), "task"),
                "bucket": item.get("bucket") or "unknown",
                "due_date": due.isoformat(),
                "days_until_due": delta,
            })
    by_bucket = Counter(str(item.get("bucket") or "unknown") for item in open_items)
    return envelope(
        "tasks",
        generated_at,
        source_timestamp(path),
        as_of=today.isoformat(),
        privacy={"titles_exported": False, "free_text_exported": False},
        metrics={
            "total": len(items),
            "open": len(open_items),
            "completed": len(items) - len(open_items),
            "completion_rate_pct": round((len(items) - len(open_items)) / len(items) * 100, 1) if items else None,
            "overdue": overdue,
            "due_next_7_days": due_7d,
            "open_by_bucket": dict(sorted(by_bucket.items())),
        },
        records=sorted(due_items, key=lambda row: (row["days_until_due"], row["id"])),
    )


def build_cleaning(generated_at: str, today: date) -> dict[str, Any]:
    path = DATA / "cleaning.sqlite"
    metrics: dict[str, Any] = {"active_tasks": 0, "overdue": 0, "never_completed": 0}
    records: list[dict[str, Any]] = []
    if path.exists():
        with connect_readonly(path) as connection:
            rows = connection.execute(
                "SELECT apartment_id, room, category, freq, last_done FROM tasks WHERE is_active = 1"
            ).fetchall()
            metrics["active_tasks"] = len(rows)
            by_room: Counter[str] = Counter()
            by_category: Counter[str] = Counter()
            for row in rows:
                by_room[str(row["room"] or "unknown")] += 1
                by_category[str(row["category"] or "unknown")] += 1
                last_done = parse_date(row["last_done"])
                if last_done is None:
                    metrics["never_completed"] += 1
                    continue
                due_date = last_done + timedelta(days=float(row["freq"]))
                days_overdue = (today - due_date).days
                if days_overdue > 0:
                    metrics["overdue"] += 1
                    records.append({
                        "apartment": alias(str(row["apartment_id"]), "location"),
                        "room": row["room"],
                        "category": row["category"],
                        "last_completed": last_done.isoformat(),
                        "frequency_days": row["freq"],
                        "days_overdue": days_overdue,
                    })
            metrics["active_by_room"] = dict(sorted(by_room.items()))
            metrics["active_by_category"] = dict(sorted(by_category.items()))
            metrics["overdue_rate_pct"] = round(metrics["overdue"] / len(rows) * 100, 1) if rows else None
    return envelope(
        "cleaning",
        generated_at,
        source_timestamp(path),
        as_of=today.isoformat(),
        privacy={"addresses_exported": False, "task_names_exported": False, "notes_exported": False},
        metrics=metrics,
        records=sorted(records, key=lambda row: (-row["days_overdue"], row["room"]))[:30],
    )


def build_habits(generated_at: str, today: date) -> dict[str, Any]:
    path = DATA / "habits.sqlite"
    records: list[dict[str, Any]] = []
    current_days = window_dates(today, 7)
    previous_days = window_dates(today, 7, 7)
    if path.exists():
        with connect_readonly(path) as connection:
            habits = connection.execute(
                "SELECT * FROM habits WHERE deleted_at IS NULL AND archived = 0 ORDER BY position, id"
            ).fetchall()
            entries: dict[str, dict[date, sqlite3.Row]] = defaultdict(dict)
            for row in connection.execute(
                "SELECT habit_id, date, status, value_milli FROM entries WHERE deleted_at IS NULL AND date >= ?",
                ((today - timedelta(days=45)).isoformat(),),
            ):
                day = parse_date(row["date"])
                if day:
                    entries[str(row["habit_id"])][day] = row

            for habit in habits:
                habit_entries = entries.get(str(habit["id"]), {})

                def positive(row: sqlite3.Row | None) -> bool:
                    if row is None:
                        return False
                    if str(habit["type"]).upper() == "BINARY":
                        return str(row["status"] or "").upper() == "DONE"
                    return (row["value_milli"] or 0) > 0

                current_positive = sum(positive(habit_entries.get(day)) for day in current_days)
                previous_positive = sum(positive(habit_entries.get(day)) for day in previous_days)
                streak = 0
                cursor = today
                while positive(habit_entries.get(cursor)):
                    streak += 1
                    cursor -= timedelta(days=1)
                records.append({
                    "id": alias(str(habit["id"]), "habit"),
                    "name": habit["name"],
                    "category": habit["category"],
                    "type": str(habit["type"]).lower(),
                    "unit": habit["unit"] or None,
                    "target": round_or_none(habit["target_value_milli"] / 1000) if habit["target_value_milli"] is not None else None,
                    "positive_days_7d": current_positive,
                    "positive_days_previous_7d": previous_positive,
                    "positive_days_delta": current_positive - previous_positive,
                    "current_streak_days": streak,
                })
    improving = sum(row["positive_days_delta"] > 0 for row in records)
    declining = sum(row["positive_days_delta"] < 0 for row in records)
    return envelope(
        "habits",
        generated_at,
        source_timestamp(path),
        as_of=today.isoformat(),
        privacy={"habit_names_exported": True, "notes_descriptions_and_questions_exported": False},
        metrics={"active_habits": len(records), "improving_7d": improving, "declining_7d": declining},
        records=records,
    )


def daily_weight_rows(path: Path) -> dict[date, float]:
    values: dict[date, tuple[datetime, float]] = {}
    for row in read_jsonl(path):
        when = parse_datetime(row.get("timestamp"))
        weight = row.get("weight_kg")
        if not when or not isinstance(weight, (int, float)) or not row.get("stable", True):
            continue
        existing = values.get(when.date())
        if existing is None or when > existing[0]:
            values[when.date()] = (when, float(weight))
    return {day: value for day, (_, value) in values.items()}


def period_average(values: dict[date, float], days: set[date]) -> float | None:
    selected = [value for day, value in values.items() if day in days]
    return mean(selected) if selected else None


def build_body_activity(generated_at: str, today: date) -> dict[str, Any]:
    weight_path = DATA / "scale" / "scale_measurements.jsonl"
    steps_path = DATA / "scale" / "steps.json"
    weights = daily_weight_rows(weight_path)
    steps_source = read_json(steps_path, {}).get("days", {})
    steps: dict[date, float] = {}
    for key, value in steps_source.items():
        day = parse_date(key)
        if not day or not isinstance(value, dict):
            continue
        if value.get("normal_mode") == "automatic" and value.get("automatic_steps") is not None:
            normal_steps = value.get("automatic_steps") or 0
        else:
            normal_steps = value.get("manual_steps", value.get("normal_steps", value.get("steps", 0))) or 0
        virtual_steps = sum(
            float(session.get("steps") or 0)
            for session in (value.get("virtual_walk_sessions") or {}).values()
            if isinstance(session, dict)
        )
        if isinstance(normal_steps, (int, float)):
            steps[day] = float(normal_steps) + virtual_steps
    latest_weight_day = max(weights) if weights else None
    latest_steps_day = max(steps) if steps else None
    steps_window_end = min(latest_steps_day, today - timedelta(days=1)) if latest_steps_day else today - timedelta(days=1)
    weight_current_7 = period_average(weights, window_dates(today, 7))
    weight_previous_7 = period_average(weights, window_dates(today, 7, 7))
    steps_current_7 = period_average(steps, window_dates(steps_window_end, 7))
    steps_previous_7 = period_average(steps, window_dates(steps_window_end, 7, 7))
    recent_days = sorted(set(weights) | set(steps), reverse=True)[:30]
    records = [
        {
            "date": day.isoformat(),
            "weight_kg": round_or_none(weights.get(day)),
            "steps": int(steps[day]) if day in steps else None,
        }
        for day in sorted(recent_days)
    ]
    return envelope(
        "body_activity",
        generated_at,
        source_timestamp(weight_path, steps_path),
        as_of=today.isoformat(),
        units={"weight": "kg", "steps": "count"},
        privacy={"device_identifiers_exported": False, "raw_packets_exported": False},
        metrics={
            "latest_weight_date": latest_weight_day.isoformat() if latest_weight_day else None,
            "latest_weight_kg": round_or_none(weights.get(latest_weight_day)) if latest_weight_day else None,
            "weight_ma7_kg": round_or_none(weight_current_7),
            "weight_previous_7d_avg_kg": round_or_none(weight_previous_7),
            "weight_7d_change_pct": pct_change(weight_current_7, weight_previous_7),
            "weight_ma30_kg": round_or_none(period_average(weights, window_dates(today, 30))),
            "weight_trend": trend(weight_current_7, weight_previous_7, tolerance_pct=0.25),
            "latest_steps_date": latest_steps_day.isoformat() if latest_steps_day else None,
            "latest_steps": int(steps[latest_steps_day]) if latest_steps_day else None,
            "steps_comparison_window_end": steps_window_end.isoformat(),
            "steps_7d_avg": round_or_none(steps_current_7, 0),
            "steps_previous_7d_avg": round_or_none(steps_previous_7, 0),
            "steps_7d_change_pct": pct_change(steps_current_7, steps_previous_7),
            "steps_trend": trend(steps_current_7, steps_previous_7, tolerance_pct=5),
        },
        records=records,
    )


def build_training(generated_at: str, today: date) -> dict[str, Any]:
    workout_path = DATA / "live-workout.sqlite"
    strength_path = DATA / "strength.sqlite"
    workouts: list[dict[str, Any]] = []
    if workout_path.exists():
        with connect_readonly(workout_path) as connection:
            for row in connection.execute(
                "SELECT started_at, status, payload_json FROM live_workout_sessions WHERE status = 'finished' ORDER BY started_at DESC LIMIT 120"
            ):
                started = parse_datetime(row["started_at"])
                if not started:
                    continue
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                workouts.append({
                    "date": started.date(),
                    "started_at": iso_utc(started),
                    "duration_minutes": round_or_none(float(payload.get("duration_seconds") or 0) / 60, 1),
                    "active_calories_kcal": round_or_none(float(payload.get("active_calories") or 0), 1),
                    "average_hr_bpm": round_or_none(float(payload.get("avg_hr") or 0), 0),
                    "training_load": round_or_none(float(payload.get("training_load") or 0), 1),
                    "source": "wear_os" if "wear os" in str(payload.get("source") or "").lower() else "dashboard",
                })
    current_days = window_dates(today, 7)
    previous_days = window_dates(today, 7, 7)

    def workout_summary(days: set[date]) -> dict[str, Any]:
        selected = [row for row in workouts if row["date"] in days]
        return {
            "sessions": len(selected),
            "duration_minutes": round(sum(row["duration_minutes"] or 0 for row in selected), 1),
            "active_calories_kcal": round(sum(row["active_calories_kcal"] or 0 for row in selected), 1),
            "training_load": round(sum(row["training_load"] or 0 for row in selected), 1),
        }

    strength = {"sessions_7d": 0, "sessions_previous_7d": 0, "sets_7d": 0, "sets_previous_7d": 0, "sets_by_muscle_7d": {}}
    if strength_path.exists():
        with connect_readonly(strength_path) as connection:
            session_rows = connection.execute("SELECT id, started_at FROM strength_sessions WHERE completed = 1").fetchall()
            session_days = {row["id"]: parse_datetime(row["started_at"]).date() for row in session_rows if parse_datetime(row["started_at"])}
            strength["sessions_7d"] = sum(day in current_days for day in session_days.values())
            strength["sessions_previous_7d"] = sum(day in previous_days for day in session_days.values())
            muscle_sets: Counter[str] = Counter()
            for row in connection.execute(
                "SELECT s.session_id, e.primary_muscle FROM strength_sets s JOIN strength_exercises e ON e.id = s.exercise_id"
            ):
                day = session_days.get(row["session_id"])
                if day in current_days:
                    strength["sets_7d"] += 1
                    muscle_sets[str(row["primary_muscle"])] += 1
                elif day in previous_days:
                    strength["sets_previous_7d"] += 1
            strength["sets_by_muscle_7d"] = dict(sorted(muscle_sets.items()))

    current = workout_summary(current_days)
    previous = workout_summary(previous_days)
    records = [{**row, "date": row["date"].isoformat()} for row in workouts[:12]]
    return envelope(
        "training",
        generated_at,
        source_timestamp(workout_path, strength_path),
        as_of=today.isoformat(),
        units={"duration": "minutes", "energy": "kcal", "heart_rate": "bpm"},
        metrics={
            "workouts_7d": current,
            "workouts_previous_7d": previous,
            "session_count_delta": current["sessions"] - previous["sessions"],
            "duration_change_pct": pct_change(current["duration_minutes"], previous["duration_minutes"]),
            "strength": strength,
        },
        records=records,
    )


def build_reading(generated_at: str, today: date) -> dict[str, Any]:
    path = DATA / "reading.sqlite"
    records: list[dict[str, Any]] = []
    current_pages = previous_pages = 0
    current_days: set[str] = set()
    previous_days: set[str] = set()
    if path.exists():
        with connect_readonly(path) as connection:
            for row in connection.execute(
                "SELECT id, title, author, pages_read, pages_total, source, return_date FROM books WHERE remote_active = 1 ORDER BY updated_at DESC"
            ):
                total = int(row["pages_total"] or 0)
                read = int(row["pages_read"] or 0)
                records.append({
                    "id": alias(str(row["id"]), "book"),
                    "title": row["title"],
                    "author": row["author"],
                    "ownership": row["source"],
                    "pages_read": read,
                    "pages_total": total,
                    "progress_pct": round(read / total * 100, 1) if total else None,
                    "return_date": row["return_date"],
                })
            for row in connection.execute(
                "SELECT day, pages FROM reading_logs WHERE day >= ?",
                ((today - timedelta(days=14)).isoformat(),),
            ):
                day = parse_date(row["day"])
                if day in window_dates(today, 7):
                    current_pages += int(row["pages"] or 0)
                    current_days.add(day.isoformat())
                elif day in window_dates(today, 7, 7):
                    previous_pages += int(row["pages"] or 0)
                    previous_days.add(day.isoformat())
    return envelope(
        "reading",
        generated_at,
        source_timestamp(path),
        as_of=today.isoformat(),
        units={"reading_volume": "pages"},
        privacy={"titles_and_authors_exported": True, "free_text_metadata_exported": False},
        metrics={
            "active_books": len(records),
            "pages_7d": current_pages,
            "pages_previous_7d": previous_pages,
            "pages_change_pct": pct_change(current_pages, previous_pages),
            "reading_days_7d": len(current_days),
            "reading_days_previous_7d": len(previous_days),
        },
        records=records,
    )


def build_events(generated_at: str, today: date) -> dict[str, Any]:
    path = DATA / "events.json"
    source = [row for row in read_json(path, []) if isinstance(row, dict)]
    records: list[dict[str, Any]] = []
    for row in source:
        event_date = parse_date(row.get("date"))
        if not event_date:
            continue
        delta = (event_date - today).days
        if -7 <= delta <= 60:
            records.append({
                "id": alias(str(row.get("id", row.get("date", "unknown"))), "event"),
                "date": event_date.isoformat(),
                "days_from_today": delta,
                "type": row.get("type") or "event",
                "source": row.get("source") or "local",
                "is_day_off": bool(row.get("isDayOff")),
                "is_short_day": bool(row.get("isShortDay")),
            })
    return envelope(
        "events",
        generated_at,
        source_timestamp(path),
        as_of=today.isoformat(),
        privacy={"titles_exported": False, "external_calendar_events_exported": False},
        metrics={
            "events_next_7_days": sum(0 <= row["days_from_today"] <= 7 for row in records),
            "events_next_30_days": sum(0 <= row["days_from_today"] <= 30 for row in records),
            "days_off_next_30_days": sum(0 <= row["days_from_today"] <= 30 and row["is_day_off"] for row in records),
        },
        records=sorted(records, key=lambda row: (row["date"], row["id"])),
    )


def build_ai_usage(generated_at: str, today: date) -> dict[str, Any]:
    path = DATA / "ai-usage.sqlite"
    records: list[dict[str, Any]] = []
    session_count_7d = 0
    if path.exists():
        with connect_readonly(path) as connection:
            latest: dict[tuple[str, str], sqlite3.Row] = {}
            for row in connection.execute("SELECT * FROM snapshots ORDER BY timestamp DESC"):
                key = (str(row["provider"]), str(row["group_name"]))
                latest.setdefault(key, row)
            for (provider, group), row in sorted(latest.items()):
                records.append({
                    "provider": provider,
                    "group": group,
                    "observed_at": row["timestamp"],
                    "status": row["status"],
                    "five_hour_remaining_pct": round_or_none(row["five_hour_remaining"]),
                    "five_hour_reset_at": row["five_hour_reset_at"],
                    "weekly_remaining_pct": round_or_none(row["weekly_remaining"]),
                    "weekly_reset_at": row["weekly_reset_at"],
                })
            session_count_7d = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE session_start >= ?",
                (iso_utc(datetime.combine(today - timedelta(days=6), datetime.min.time(), timezone.utc)),),
            ).fetchone()[0]
    return envelope(
        "ai_usage",
        generated_at,
        source_timestamp(path),
        as_of=today.isoformat(),
        units={"quota_remaining": "percent"},
        privacy={"credentials_exported": False, "prompts_and_content_exported": False},
        metrics={"tracked_groups": len(records), "sessions_7d": session_count_7d},
        records=records,
    )


def build_environment(generated_at: str, today: date) -> dict[str, Any]:
    latest_path = DATA / "sensor" / "latest.json"
    history_path = DATA / "sensor" / "readings.jsonl"
    latest = read_json(latest_path, {})
    rows = read_jsonl(history_path)
    latest_at = parse_datetime(latest.get("timestamp"))
    cutoff = (latest_at or utc_now()) - timedelta(hours=24)
    recent = [row for row in rows if (stamp := parse_datetime(row.get("timestamp"))) and stamp >= cutoff]
    temps = [float(row["temp_c"]) for row in recent if isinstance(row.get("temp_c"), (int, float))]
    humidity = [float(row["hum_pct"]) for row in recent if isinstance(row.get("hum_pct"), (int, float))]
    return envelope(
        "environment",
        generated_at,
        source_timestamp(latest_path, history_path),
        as_of=latest_at.date().isoformat() if latest_at else today.isoformat(),
        units={"temperature": "degrees Celsius", "relative_humidity": "percent", "battery": "percent"},
        privacy={"mac_address_exported": False, "raw_packets_exported": False},
        metrics={
            "observed_at": latest.get("timestamp"),
            "temperature_c": latest.get("temp_c"),
            "relative_humidity_pct": latest.get("hum_pct"),
            "battery_pct": latest.get("battery_pct"),
            "samples_24h": len(recent),
            "temperature_24h_avg_c": round_or_none(mean(temps)) if temps else None,
            "temperature_24h_min_c": round_or_none(min(temps)) if temps else None,
            "temperature_24h_max_c": round_or_none(max(temps)) if temps else None,
            "humidity_24h_avg_pct": round_or_none(mean(humidity)) if humidity else None,
            "humidity_24h_min_pct": round_or_none(min(humidity)) if humidity else None,
            "humidity_24h_max_pct": round_or_none(max(humidity)) if humidity else None,
        },
        records=[],
    )


def build_summary(generated_at: str, datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    tasks = datasets["tasks"]["metrics"]
    cleaning = datasets["cleaning"]["metrics"]
    body = datasets["body_activity"]["metrics"]
    habits = datasets["habits"]["metrics"]
    if tasks["overdue"]:
        signals.append({"kind": "threshold", "metric": "tasks.overdue", "value": tasks["overdue"], "condition": "greater_than_zero"})
    if cleaning["overdue"]:
        signals.append({"kind": "threshold", "metric": "cleaning.overdue", "value": cleaning["overdue"], "condition": "greater_than_zero"})
    if body["steps_trend"] in {"increasing", "decreasing"}:
        signals.append({"kind": "trend", "metric": "body_activity.steps_7d_avg", "value": body["steps_7d_change_pct"], "unit": "percent", "direction": body["steps_trend"]})
    if body["weight_trend"] in {"increasing", "decreasing"}:
        signals.append({"kind": "trend", "metric": "body_activity.weight_ma7_kg", "value": body["weight_7d_change_pct"], "unit": "percent", "direction": body["weight_trend"]})
    if habits["declining_7d"]:
        signals.append({"kind": "comparison", "metric": "habits.declining_7d", "value": habits["declining_7d"], "condition": "positive_days_below_previous_7d"})
    return envelope(
        "current_summary",
        generated_at,
        generated_at,
        dataset_freshness={key: value.get("source_freshness") for key, value in datasets.items()},
        deterministic_signals=signals,
        note="Signals are deterministic candidates for interpretation, not AI-written conclusions.",
    )


SCHEMA_DETAILS: dict[str, dict[str, Any]] = {
    "tasks": {
        "metrics": {
            "total": {"type": "integer"}, "open": {"type": "integer"}, "completed": {"type": "integer"},
            "completion_rate_pct": {"type": ["number", "null"], "description": "Completed share, percent."},
            "overdue": {"type": "integer"}, "due_next_7_days": {"type": "integer"},
            "open_by_bucket": {"type": "object", "additionalProperties": {"type": "integer"}},
        },
        "record": {"id": {"type": "string"}, "bucket": {"type": "string"}, "due_date": {"type": "string", "format": "date"}, "days_until_due": {"type": "integer"}},
    },
    "cleaning": {
        "metrics": {
            "active_tasks": {"type": "integer"}, "overdue": {"type": "integer"}, "never_completed": {"type": "integer"},
            "overdue_rate_pct": {"type": ["number", "null"], "description": "Overdue share of active tasks, percent."},
            "active_by_room": {"type": "object"}, "active_by_category": {"type": "object"},
        },
        "record": {"apartment": {"type": "string"}, "room": {"type": "string"}, "category": {"type": "string"}, "last_completed": {"type": "string", "format": "date"}, "frequency_days": {"type": "number"}, "days_overdue": {"type": "integer"}},
    },
    "habits": {
        "metrics": {"active_habits": {"type": "integer"}, "improving_7d": {"type": "integer"}, "declining_7d": {"type": "integer"}},
        "record": {"id": {"type": "string"}, "name": {"type": "string"}, "category": {"type": "string"}, "type": {"enum": ["binary", "numeric"]}, "unit": {"type": ["string", "null"]}, "target": {"type": ["number", "null"]}, "positive_days_7d": {"type": "integer"}, "positive_days_previous_7d": {"type": "integer"}, "positive_days_delta": {"type": "integer"}, "current_streak_days": {"type": "integer"}},
    },
    "body_activity": {
        "metrics": {
            "latest_weight_date": {"type": ["string", "null"], "format": "date"}, "latest_weight_kg": {"type": ["number", "null"]},
            "weight_ma7_kg": {"type": ["number", "null"]}, "weight_previous_7d_avg_kg": {"type": ["number", "null"]},
            "weight_7d_change_pct": {"type": ["number", "null"]}, "weight_ma30_kg": {"type": ["number", "null"]},
            "weight_trend": {"enum": ["increasing", "decreasing", "stable", "unknown"]},
            "latest_steps_date": {"type": ["string", "null"], "format": "date"}, "latest_steps": {"type": ["integer", "null"]},
            "steps_comparison_window_end": {"type": "string", "format": "date", "description": "Last complete day used for step rolling comparisons."},
            "steps_7d_avg": {"type": ["number", "null"]}, "steps_previous_7d_avg": {"type": ["number", "null"]},
            "steps_7d_change_pct": {"type": ["number", "null"]}, "steps_trend": {"enum": ["increasing", "decreasing", "stable", "unknown"]},
        },
        "record": {"date": {"type": "string", "format": "date"}, "weight_kg": {"type": ["number", "null"]}, "steps": {"type": ["integer", "null"]}},
    },
    "training": {
        "metrics": {"workouts_7d": {"type": "object"}, "workouts_previous_7d": {"type": "object"}, "session_count_delta": {"type": "integer"}, "duration_change_pct": {"type": ["number", "null"]}, "strength": {"type": "object"}},
        "record": {"date": {"type": "string", "format": "date"}, "started_at": {"type": "string", "format": "date-time"}, "duration_minutes": {"type": ["number", "null"]}, "active_calories_kcal": {"type": ["number", "null"]}, "average_hr_bpm": {"type": ["number", "null"]}, "training_load": {"type": ["number", "null"]}, "source": {"enum": ["wear_os", "dashboard"]}},
    },
    "reading": {
        "metrics": {"active_books": {"type": "integer"}, "pages_7d": {"type": "integer"}, "pages_previous_7d": {"type": "integer"}, "pages_change_pct": {"type": ["number", "null"]}, "reading_days_7d": {"type": "integer"}, "reading_days_previous_7d": {"type": "integer"}},
        "record": {"id": {"type": "string"}, "title": {"type": "string"}, "author": {"type": "string"}, "ownership": {"type": "string"}, "pages_read": {"type": "integer"}, "pages_total": {"type": "integer"}, "progress_pct": {"type": ["number", "null"]}, "return_date": {"type": ["string", "null"]}},
    },
    "events": {
        "metrics": {"events_next_7_days": {"type": "integer"}, "events_next_30_days": {"type": "integer"}, "days_off_next_30_days": {"type": "integer"}},
        "record": {"id": {"type": "string"}, "date": {"type": "string", "format": "date"}, "days_from_today": {"type": "integer"}, "type": {"type": "string"}, "source": {"type": "string"}, "is_day_off": {"type": "boolean"}, "is_short_day": {"type": "boolean"}},
    },
    "ai_usage": {
        "metrics": {"tracked_groups": {"type": "integer"}, "sessions_7d": {"type": "integer"}},
        "record": {"provider": {"type": "string"}, "group": {"type": "string"}, "observed_at": {"type": "string", "format": "date-time"}, "status": {"type": "string"}, "five_hour_remaining_pct": {"type": ["number", "null"]}, "five_hour_reset_at": {"type": ["string", "null"]}, "weekly_remaining_pct": {"type": ["number", "null"]}, "weekly_reset_at": {"type": ["string", "null"]}},
    },
    "environment": {
        "metrics": {"observed_at": {"type": ["string", "null"]}, "temperature_c": {"type": ["number", "null"]}, "relative_humidity_pct": {"type": ["number", "null"]}, "battery_pct": {"type": ["number", "null"]}, "samples_24h": {"type": "integer"}, "temperature_24h_avg_c": {"type": ["number", "null"]}, "temperature_24h_min_c": {"type": ["number", "null"]}, "temperature_24h_max_c": {"type": ["number", "null"]}, "humidity_24h_avg_pct": {"type": ["number", "null"]}, "humidity_24h_min_pct": {"type": ["number", "null"]}, "humidity_24h_max_pct": {"type": ["number", "null"]}},
        "record": {},
    },
}


def schema_for(dataset_id: str, description: str, has_records: bool = True) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "dataset": {"const": dataset_id},
        "schema_version": {"type": "integer", "const": 1},
        "generated_at": {"type": "string", "format": "date-time", "description": "UTC export timestamp."},
        "source_freshness": {"type": ["string", "null"], "format": "date-time", "description": "Newest source file modification time; not necessarily observation time."},
    }
    required = ["dataset", "schema_version", "generated_at", "source_freshness"]
    if dataset_id == "current_summary":
        properties.update({
            "dataset_freshness": {"type": "object", "additionalProperties": {"type": ["string", "null"]}},
            "deterministic_signals": {"type": "array", "items": {"type": "object"}},
            "note": {"type": "string"},
        })
        required.extend(["dataset_freshness", "deterministic_signals"])
    else:
        details = SCHEMA_DETAILS.get(dataset_id, {})
        metric_properties = details.get("metrics", {})
        properties.update({
            "as_of": {"type": "string", "format": "date"},
            "metrics": {
                "type": "object",
                "description": "Deterministically calculated facts documented in README.md.",
                "properties": metric_properties,
                "required": list(metric_properties),
                "additionalProperties": True,
            },
        })
        required.extend(["as_of", "metrics"])
        if has_records:
            record_properties = details.get("record", {})
            properties["records"] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": record_properties,
                    "required": list(record_properties),
                    "additionalProperties": True,
                },
            }
            required.append("records")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://local.invalid/antigravity-context/schemas/{dataset_id}.schema.json",
        "title": dataset_id.replace("_", " ").title(),
        "description": description,
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": True,
    }


DATASET_META = [
    ("tasks", "snapshots/current/tasks.json", "Task workload and deadline facts without task titles."),
    ("cleaning", "snapshots/current/cleaning.json", "Cleaning cadence and overdue facts without addresses or task text."),
    ("habits", "snapshots/current/habits.json", "Active habit consistency comparisons; notes and descriptions are omitted."),
    ("body_activity", "snapshots/current/body-activity.json", "Daily weight and step summaries with rolling comparisons."),
    ("training", "snapshots/current/training.json", "Workout and strength-volume aggregates without raw telemetry."),
    ("reading", "snapshots/current/reading.json", "Active-book progress and recent reading volume."),
    ("events", "snapshots/current/events.json", "Local event timing and day-off facts without event titles."),
    ("ai_usage", "snapshots/current/ai-usage.json", "Quota remaining and session counts without prompts or credentials."),
    ("environment", "snapshots/current/environment.json", "Current and 24-hour room temperature/humidity facts."),
    ("current_summary", "summaries/current.json", "Cross-dataset deterministic signal candidates and freshness."),
]


def validate_output() -> list[Path]:
    allowed_suffixes = {".json", ".md"}
    forbidden_names = {".git", ".env", "credentials.json", "token.json"}
    secret_patterns = [
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
        re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
        re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ]
    files = sorted(path for path in OUT.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(OUT)
        if path.suffix.lower() not in allowed_suffixes:
            raise RuntimeError(f"Unexpected file type inside context: {relative}")
        if any(part.lower() in forbidden_names for part in relative.parts):
            raise RuntimeError(f"Forbidden file inside context: {relative}")
        raw = path.read_bytes()
        if any(pattern.search(raw) for pattern in secret_patterns):
            raise RuntimeError(f"Secret-like value detected inside context: {relative}")
        if path.suffix.lower() == ".json":
            json.loads(raw.decode("utf-8"))
    manifest = read_json(OUT / "manifest.json", {})
    for entry in manifest.get("datasets", []):
        for key in ("path", "schema"):
            target = OUT / entry[key]
            if not target.is_file() or OUT.resolve() not in target.resolve().parents:
                raise RuntimeError(f"Manifest target is missing or outside context: {entry[key]}")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the isolated Antigravity data context.")
    parser.add_argument("--check-only", action="store_true", help="Validate the existing context without regenerating it.")
    args = parser.parse_args()
    if not args.check_only:
        generated_at = iso_utc()
        today = datetime.now().astimezone().date()
        datasets = {
            "tasks": build_tasks(generated_at, today),
            "cleaning": build_cleaning(generated_at, today),
            "habits": build_habits(generated_at, today),
            "body_activity": build_body_activity(generated_at, today),
            "training": build_training(generated_at, today),
            "reading": build_reading(generated_at, today),
            "events": build_events(generated_at, today),
            "ai_usage": build_ai_usage(generated_at, today),
            "environment": build_environment(generated_at, today),
        }
        output_paths = {
            "tasks": CURRENT / "tasks.json",
            "cleaning": CURRENT / "cleaning.json",
            "habits": CURRENT / "habits.json",
            "body_activity": CURRENT / "body-activity.json",
            "training": CURRENT / "training.json",
            "reading": CURRENT / "reading.json",
            "events": CURRENT / "events.json",
            "ai_usage": CURRENT / "ai-usage.json",
            "environment": CURRENT / "environment.json",
        }
        for key, path in output_paths.items():
            write_json(path, datasets[key])
        write_json(SUMMARY_DIR / "current.json", build_summary(generated_at, datasets))
        for dataset_id, _, description in DATASET_META:
            write_json(SCHEMAS / f"{dataset_id}.schema.json", schema_for(dataset_id, description))
        manifest = {
            "version": 1,
            "generated_at": generated_at,
            "timezone": LOCAL_TZ_NAME,
            "access_boundary": "This directory is complete and requires no parent-directory access.",
            "datasets": [
                {
                    "id": dataset_id,
                    "path": path,
                    "schema": f"schemas/{dataset_id}.schema.json",
                    "description": description,
                }
                for dataset_id, path, description in DATASET_META
            ],
        }
        write_json(OUT / "manifest.json", manifest)
    files = validate_output()
    print(f"Antigravity context valid: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
