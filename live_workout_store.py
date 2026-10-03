import json
import math
import sqlite3
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path


ZONE_KEYS = ("light", "intensive", "aerobic", "anaerobic", "vo2max")
DEFAULT_MAX_HR = 190
ZONE_LOAD_WEIGHTS = {"light": 1, "intensive": 2, "aerobic": 3, "anaerobic": 4, "vo2max": 5}
HR_FLATLINE_DURATION_MS = 60 * 1000
HR_FLATLINE_MIN_SAMPLES = 45
HR_FLATLINE_MAX_GAP_MS = 60 * 1000
HR_FLATLINE_MAX_RANGE_BPM = 2
HR_FLATLINE_MAX_STDDEV_BPM = 0.35
HR_FLATLINE_MAX_CHANGE_RATIO = 0.03
HR_FLATLINE_MIN_DOMINANT_RATIO = 0.98


def _epoch_ms(value):
    return int(datetime.fromisoformat(value).timestamp() * 1000)


SEED_WORKOUTS = [
    {
        "id": "mi-fitness-2026-08-22-0906",
        "title": "Indoor cycling",
        "started_at": _epoch_ms("2026-08-22T09:06:21+02:00"),
        "status": "finished",
        "duration_seconds": 2513,
        "active_calories": 301,
        "total_calories": 376,
        "avg_hr": 126,
        "max_hr": 185,
        "zones": {"light": 537, "intensive": 1258, "aerobic": 493, "anaerobic": 109, "vo2max": 66},
        "training_effect": {"aerobic": 2.1, "aerobic_label": "Maintaining", "anaerobic": 0.4, "anaerobic_label": "Minor"},
        "training_load": 34,
        "recovery_hours": 16,
        "source": "Xiaomi Watch 2 · Mi Fitness TCX + screenshot",
        "external_id": "2026-08-22T09:06:21.000Z",
        "import_file": "20260822Indoor cycling.tcx",
        "data_quality": {"summary": "tcx", "max_hr": "screenshot", "zones": "screenshot", "training_effect": "screenshot", "samples": "unavailable"},
        "sample_count": 0,
    },
    {
        "id": "mi-fitness-2026-08-21-2321",
        "title": "Indoor cycling",
        "started_at": _epoch_ms("2026-08-21T23:21:38+02:00"),
        "status": "finished",
        "duration_seconds": 1709,
        "active_calories": 302,
        "total_calories": 354,
        "avg_hr": 140,
        "max_hr": 174,
        "zones": {"light": 121, "intensive": 455, "aerobic": 786, "anaerobic": 324, "vo2max": 16},
        "training_effect": {"aerobic": 2.2, "aerobic_label": "Maintaining", "anaerobic": 0.3, "anaerobic_label": "Minor"},
        "training_load": 38,
        "recovery_hours": 13,
        "source": "Xiaomi Watch 2 · Mi Fitness TCX + screenshot",
        "external_id": "2026-08-21T23:21:38.000Z",
        "import_file": "20260821Indoor cycling.tcx",
        "data_quality": {"summary": "tcx", "max_hr": "screenshot", "zones": "screenshot", "training_effect": "screenshot", "samples": "unavailable"},
        "sample_count": 0,
    },
    {
        "id": "mi-fitness-2026-08-21-1523",
        "title": "Indoor cycling",
        "started_at": _epoch_ms("2026-08-21T15:23:44+02:00"),
        "status": "finished",
        "duration_seconds": 2415,
        "active_calories": 317,
        "total_calories": 389,
        "avg_hr": 119,
        "max_hr": 171,
        "zones": {"light": 1091, "intensive": 991, "aerobic": 201, "anaerobic": 121, "vo2max": 0},
        "training_effect": {"aerobic": 1.8, "aerobic_label": "Recovery", "anaerobic": None, "anaerobic_label": ""},
        "training_load": 24,
        "recovery_hours": 6,
        "source": "Xiaomi Watch 2 · Mi Fitness TCX + screenshot",
        "external_id": "2026-08-21T15:23:44.000Z",
        "import_file": "20260821Indoor cycling_01.tcx",
        "data_quality": {"summary": "tcx", "max_hr": "screenshot", "zones": "screenshot", "training_effect": "screenshot", "samples": "unavailable"},
        "sample_count": 0,
    },
    {
        "id": "mi-fitness-2026-08-20-1913",
        "title": "Indoor cycling",
        "started_at": _epoch_ms("2026-08-20T19:13:20+02:00"),
        "status": "finished",
        "duration_seconds": 2514,
        "active_calories": 443,
        "total_calories": 519,
        "avg_hr": 140,
        "max_hr": 179,
        "zones": {"light": 40, "intensive": 461, "aerobic": 1751, "anaerobic": 221, "vo2max": 36},
        "training_effect": {"aerobic": 2.7, "aerobic_label": "Maintaining", "anaerobic": 0.3, "anaerobic_label": "Minor"},
        "training_load": 57,
        "recovery_hours": 26,
        "source": "Xiaomi Watch 2 · Mi Fitness TCX + screenshot",
        "external_id": "2026-08-20T19:13:20.000Z",
        "import_file": "20260820Indoor cycling.tcx",
        "data_quality": {"summary": "tcx", "max_hr": "screenshot", "zones": "screenshot", "training_effect": "screenshot", "samples": "unavailable"},
        "sample_count": 0,
    },
    {
        "id": "mi-fitness-2026-08-20-1734",
        "title": "Indoor cycling",
        "started_at": _epoch_ms("2026-08-20T17:34:32+02:00"),
        "status": "finished",
        "duration_seconds": 522,
        "active_calories": 56,
        "total_calories": 70,
        "avg_hr": 121,
        "max_hr": 149,
        "zones": {"light": 108, "intensive": 315, "aerobic": 82, "anaerobic": 0, "vo2max": 0},
        "training_effect": {"aerobic": 1.3, "aerobic_label": "Recovery", "anaerobic": None, "anaerobic_label": ""},
        "training_load": 4,
        "recovery_hours": 8,
        "source": "Xiaomi Watch 2 · Mi Fitness TCX + screenshot",
        "external_id": "2026-08-20T17:34:32.000Z",
        "import_file": "20260820Indoor cycling_01.tcx",
        "data_quality": {"summary": "tcx", "max_hr": "screenshot", "zones": "screenshot", "training_effect": "screenshot", "samples": "unavailable"},
        "sample_count": 0,
    },
    {
        "id": "mi-fitness-2026-08-20-1140",
        "title": "Indoor cycling",
        "started_at": _epoch_ms("2026-08-20T11:40:25+02:00"),
        "status": "finished",
        "duration_seconds": 1258,
        "active_calories": 214,
        "total_calories": 248,
        "avg_hr": 151,
        "max_hr": 191,
        "zones": {"light": 39, "intensive": 34, "aerobic": 599, "anaerobic": 502, "vo2max": 72},
        "training_effect": {"aerobic": 2.2, "aerobic_label": "Maintaining", "anaerobic": 0.4, "anaerobic_label": "Minor"},
        "training_load": 40,
        "recovery_hours": 14,
        "source": "Xiaomi Watch 2 · Mi Fitness TCX + screenshot",
        "external_id": "2026-08-20T11:40:25.000Z",
        "import_file": "20260820Indoor cycling_02.tcx",
        "data_quality": {"summary": "tcx", "max_hr": "screenshot", "zones": "screenshot", "training_effect": "screenshot", "samples": "unavailable"},
        "sample_count": 0,
    },
]


def normalize_timestamp_ms(value):
    timestamp = int(value)
    return timestamp * 1000 if timestamp < 1_000_000_000_000 else timestamp


def filter_unworn_heart_rate_samples(
    samples,
    minimum_duration_ms=HR_FLATLINE_DURATION_MS,
    minimum_samples=HR_FLATLINE_MIN_SAMPLES,
    maximum_gap_ms=HR_FLATLINE_MAX_GAP_MS,
):
    """Hide long, statistically implausible low-variability optical-sensor streams."""
    indexed = sorted(
        enumerate(samples or []),
        key=lambda item: normalize_timestamp_ms(item[1]["timestamp"]),
    )
    rejected = set()
    run = []
    exact_run = []
    run_minimum = None
    run_maximum = None

    def finish_exact_run():
        if not exact_run:
            return
        first_timestamp = normalize_timestamp_ms(exact_run[0][1]["timestamp"])
        last_timestamp = normalize_timestamp_ms(exact_run[-1][1]["timestamp"])
        distinct_timestamps = len({
            normalize_timestamp_ms(item[1]["timestamp"]) for item in exact_run
        })
        if (
            last_timestamp - first_timestamp >= minimum_duration_ms
            and distinct_timestamps >= minimum_samples
        ):
            rejected.update(index for index, _sample in exact_run)

    def finish_run():
        if not run:
            return
        first_timestamp = normalize_timestamp_ms(run[0][1]["timestamp"])
        last_timestamp = normalize_timestamp_ms(run[-1][1]["timestamp"])
        distinct_timestamps = len({normalize_timestamp_ms(item[1]["timestamp"]) for item in run})
        heart_rates = [int(item[1]["heart_rate"]) for item in run]
        counts = Counter(heart_rates)
        average = sum(heart_rates) / len(heart_rates)
        variance = sum((heart_rate - average) ** 2 for heart_rate in heart_rates) / len(heart_rates)
        changes = sum(left != right for left, right in zip(heart_rates, heart_rates[1:]))
        change_ratio = changes / max(1, len(heart_rates) - 1)
        dominant_ratio = max(counts.values()) / len(heart_rates)
        heart_rate_range = max(heart_rates) - min(heart_rates)
        if (
            last_timestamp - first_timestamp >= minimum_duration_ms
            and distinct_timestamps >= minimum_samples
            and heart_rate_range <= HR_FLATLINE_MAX_RANGE_BPM
            and math.sqrt(variance) <= HR_FLATLINE_MAX_STDDEV_BPM
            and change_ratio <= HR_FLATLINE_MAX_CHANGE_RATIO
            and dominant_ratio >= HR_FLATLINE_MIN_DOMINANT_RATIO
        ):
            rejected.update(index for index, _sample in run)

    for item in indexed:
        sample = item[1]
        timestamp = normalize_timestamp_ms(sample["timestamp"])
        heart_rate = int(sample["heart_rate"])
        if exact_run:
            previous_exact = exact_run[-1][1]
            exact_gap = timestamp - normalize_timestamp_ms(previous_exact["timestamp"])
            if (
                heart_rate != int(previous_exact["heart_rate"])
                or exact_gap < 0
                or exact_gap > maximum_gap_ms
            ):
                finish_exact_run()
                exact_run = []
        exact_run.append(item)
        if run:
            previous = run[-1][1]
            previous_timestamp = normalize_timestamp_ms(previous["timestamp"])
            if (
                timestamp - previous_timestamp < 0
                or timestamp - previous_timestamp > maximum_gap_ms
                or max(run_maximum, heart_rate) - min(run_minimum, heart_rate)
                    > HR_FLATLINE_MAX_RANGE_BPM
            ):
                finish_run()
                run = []
                run_minimum = None
                run_maximum = None
        run.append(item)
        run_minimum = heart_rate if run_minimum is None else min(run_minimum, heart_rate)
        run_maximum = heart_rate if run_maximum is None else max(run_maximum, heart_rate)
    finish_exact_run()
    finish_run()
    return [sample for index, sample in enumerate(samples or []) if index not in rejected]


class HeartRateWearDetector:
    """Track live HR and suspend collection after confirmed non-human variability."""

    def __init__(
        self,
        minimum_duration_ms=HR_FLATLINE_DURATION_MS,
        minimum_samples=HR_FLATLINE_MIN_SAMPLES,
        maximum_gap_ms=HR_FLATLINE_MAX_GAP_MS,
    ):
        self.minimum_duration_ms = int(minimum_duration_ms)
        self.minimum_samples = int(minimum_samples)
        self.maximum_gap_ms = int(maximum_gap_ms)
        self._lock = threading.Lock()
        self._heart_rate = None
        self._started_at = None
        self._last_timestamp = None
        self._sample_count = 0
        self._minimum_hr = None
        self._maximum_hr = None
        self._hr_counts = Counter()
        self._hr_sum = 0
        self._hr_sum_sq = 0
        self._change_count = 0
        self._off_wrist = False

    def observe(self, telemetry):
        timestamp = normalize_timestamp_ms(telemetry["timestamp"])
        heart_rate = int(telemetry["heart_rate"])
        with self._lock:
            if timestamp == self._last_timestamp and heart_rate == self._heart_rate:
                return {
                    "wear_state": "off_wrist" if self._off_wrist else "worn",
                    "became_off_wrist": False,
                    "became_worn": False,
                    "flatline_start": self._started_at if self._off_wrist else None,
                    "flatline_heart_rates": tuple(sorted(self._hr_counts)) if self._off_wrist else (),
                    "timestamp": timestamp,
                    "heart_rate": heart_rate,
                }
            continues_run = (
                self._last_timestamp is not None
                and timestamp > self._last_timestamp
                and timestamp - self._last_timestamp <= self.maximum_gap_ms
                and (not self._off_wrist or heart_rate == self._heart_rate)
                and max(self._maximum_hr, heart_rate) - min(self._minimum_hr, heart_rate)
                    <= HR_FLATLINE_MAX_RANGE_BPM
            )
            was_off_wrist = self._off_wrist
            if continues_run:
                self._sample_count += 1
                if heart_rate != self._heart_rate:
                    self._change_count += 1
                self._minimum_hr = min(self._minimum_hr, heart_rate)
                self._maximum_hr = max(self._maximum_hr, heart_rate)
                self._hr_counts[heart_rate] += 1
                self._hr_sum += heart_rate
                self._hr_sum_sq += heart_rate * heart_rate
            else:
                self._started_at = timestamp
                self._sample_count = 1
                self._minimum_hr = heart_rate
                self._maximum_hr = heart_rate
                self._hr_counts = Counter({heart_rate: 1})
                self._hr_sum = heart_rate
                self._hr_sum_sq = heart_rate * heart_rate
                self._change_count = 0
                self._off_wrist = False
            self._last_timestamp = timestamp
            self._heart_rate = heart_rate
            average = self._hr_sum / self._sample_count
            variance = max(0, self._hr_sum_sq / self._sample_count - average * average)
            if (
                self._sample_count >= self.minimum_samples
                and timestamp - self._started_at >= self.minimum_duration_ms
                and math.sqrt(variance) <= HR_FLATLINE_MAX_STDDEV_BPM
                and self._change_count / max(1, self._sample_count - 1)
                    <= HR_FLATLINE_MAX_CHANGE_RATIO
                and max(self._hr_counts.values()) / self._sample_count
                    >= HR_FLATLINE_MIN_DOMINANT_RATIO
            ):
                self._off_wrist = True
            return {
                "wear_state": "off_wrist" if self._off_wrist else "worn",
                "became_off_wrist": self._off_wrist and not was_off_wrist,
                "became_worn": was_off_wrist and not self._off_wrist,
                "flatline_start": self._started_at if self._off_wrist else None,
                "flatline_heart_rates": tuple(sorted(self._hr_counts)) if self._off_wrist else (),
                "timestamp": timestamp,
                "heart_rate": heart_rate,
            }


def zone_key_for_hr(heart_rate, max_hr=DEFAULT_MAX_HR):
    bpm = int(heart_rate)
    if bpm < round(max_hr * 0.6):
        return "light"
    if bpm < round(max_hr * 0.7):
        return "intensive"
    if bpm < round(max_hr * 0.8):
        return "aerobic"
    if bpm < round(max_hr * 0.9):
        return "anaerobic"
    return "vo2max"


def calculate_zone_load(zone_seconds):
    values = dict(zone_seconds or {})
    return sum(max(0, float(values.get(key, 0) or 0)) / 60 * weight for key, weight in ZONE_LOAD_WEIGHTS.items())


def _training_effect_label(value):
    if value < 1:
        return "Minimalny"
    if value < 2:
        return "Regeneracja"
    if value < 3:
        return "Podtrzymanie"
    if value < 4:
        return "Rozwój"
    if value < 4.7:
        return "Mocny bodziec"
    return "Przeciążenie"


def estimate_training_metrics(zone_seconds, duration_seconds=None, training_load=None):
    zones = {key: max(0, float(dict(zone_seconds or {}).get(key, 0) or 0)) / 60 for key in ZONE_KEYS}
    duration_minutes = max(0, float(duration_seconds or 0) / 60) or sum(zones.values())
    if duration_minutes <= 0:
        return {
            "training_effect": {"aerobic": 0.0, "aerobic_label": "Minimalny", "anaerobic": 0.0, "anaerobic_label": "Minimalny", "estimated": True},
            "training_load": 0.0,
            "recovery_hours": 0,
        }
    aerobic_stimulus = (
        zones["light"] * 0.20
        + zones["intensive"] * 0.55
        + zones["aerobic"]
        + zones["anaerobic"] * 0.80
        + zones["vo2max"] * 0.50
    )
    anaerobic_stimulus = zones["anaerobic"] + zones["vo2max"] * 2
    aerobic_effect = min(5.0, round(0.75 * math.log1p(aerobic_stimulus), 1))
    anaerobic_effect = min(5.0, round(0.25 * (anaerobic_stimulus ** 0.70), 1)) if anaerobic_stimulus > 0 else 0.0
    load = max(0, float(training_load)) if training_load is not None else calculate_zone_load(zone_seconds)
    recovery = round(min(72, max(2, 2 + load * 0.14 + aerobic_effect ** 2 * 0.65 + anaerobic_effect ** 2 * 1.5)))
    return {
        "training_effect": {
            "aerobic": aerobic_effect,
            "aerobic_label": _training_effect_label(aerobic_effect),
            "anaerobic": anaerobic_effect,
            "anaerobic_label": _training_effect_label(anaerobic_effect),
            "estimated": True,
        },
        "training_load": round(load, 2),
        "recovery_hours": recovery,
    }


def complete_estimated_metrics(payload):
    if payload.get("workout_type") == "virtual_walk":
        duration_minutes = max(0, float(payload.get("duration_seconds") or 0)) / 60
        active_minutes = max(0, float(payload.get("virtual_walk_active_seconds") or 0)) / 60
        payload["training_load"] = round(max(0, float(payload.get("training_load") or duration_minutes * .25)), 2)
        payload["training_effect"] = {
            "aerobic": round(min(1.0, active_minutes / 45), 1),
            "aerobic_label": "Regeneracja / NEAT",
            "anaerobic": 0.0,
            "anaerobic_label": "Brak",
            "estimated": True,
        }
        payload["recovery_hours"] = 0
        quality = dict(payload.get("data_quality") or {})
        quality["training_load"] = "virtual_walk_symbolic_v1"
        quality["training_effect"] = "virtual_walk_recovery_v1"
        quality["recovery_hours"] = "virtual_walk_no_recovery_debt_v1"
        payload["data_quality"] = quality
        if payload.get("active_calories") is not None and not payload.get("calorie_method"):
            payload["calorie_method"] = "indoor_cycling_mi_calibrated_v1"
        return payload
    metrics = estimate_training_metrics(
        payload.get("zones") or {},
        payload.get("duration_seconds"),
        payload.get("training_load"),
    )
    quality = dict(payload.get("data_quality") or {})
    if payload.get("training_load") is None:
        payload["training_load"] = metrics["training_load"]
        quality["training_load"] = "estimated_zone_minutes_v1"
    if payload.get("training_effect") is None:
        payload["training_effect"] = metrics["training_effect"]
        quality["training_effect"] = "estimated_zone_model_v1"
    if payload.get("recovery_hours") is None:
        payload["recovery_hours"] = metrics["recovery_hours"]
        quality["recovery_hours"] = "estimated_zone_model_v1"
    if payload.get("active_calories") is not None and not payload.get("calorie_method"):
        payload["calorie_method"] = "keytel_hr_profile"
        quality["active_calories"] = "estimated_keytel_hr_profile"
    payload["data_quality"] = quality
    return payload


class LiveWorkoutStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA wal_autocheckpoint = 1000")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS live_workout_sessions (
                        id TEXT PRIMARY KEY,
                        started_at INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        hr_sum INTEGER NOT NULL DEFAULT 0,
                        last_sample_at INTEGER,
                        last_heart_rate INTEGER,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_live_workout_started
                        ON live_workout_sessions(started_at DESC);
                    CREATE TABLE IF NOT EXISTS live_workout_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        heart_rate INTEGER NOT NULL,
                        FOREIGN KEY(session_id) REFERENCES live_workout_sessions(id) ON DELETE CASCADE,
                        UNIQUE(session_id, timestamp)
                    );
                    CREATE INDEX IF NOT EXISTS idx_live_workout_samples_session
                        ON live_workout_samples(session_id, timestamp);
                    CREATE TABLE IF NOT EXISTS live_workout_sensor_samples (
                        event_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        recorded_at INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        csc_status TEXT NOT NULL,
                        csc_mode TEXT,
                        csc_stale INTEGER NOT NULL,
                        cadence_rpm REAL,
                        speed_kmh REAL,
                        distance_km REAL NOT NULL,
                        distance_source TEXT,
                        heart_rate INTEGER,
                        FOREIGN KEY(session_id) REFERENCES live_workout_sessions(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_live_workout_sensor_samples_session
                        ON live_workout_sensor_samples(session_id, recorded_at);
                    CREATE TABLE IF NOT EXISTS heart_rate_telemetry (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_at INTEGER NOT NULL,
                        received_at INTEGER NOT NULL,
                        heart_rate INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_heart_rate_telemetry_recorded
                        ON heart_rate_telemetry(recorded_at DESC, id DESC);
                    CREATE INDEX IF NOT EXISTS idx_heart_rate_telemetry_received
                        ON heart_rate_telemetry(received_at DESC, id DESC);
                    CREATE TABLE IF NOT EXISTS live_workout_outbox (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_live_workout_outbox_pending
                        ON live_workout_outbox(status, created_at);
                    CREATE TABLE IF NOT EXISTS journey_progress (
                        journey_id TEXT PRIMARY KEY,
                        route_id TEXT NOT NULL,
                        committed_distance_km REAL NOT NULL DEFAULT 0,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS journey_session_commits (
                        journey_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        distance_km REAL NOT NULL,
                        committed_at INTEGER NOT NULL,
                        PRIMARY KEY (journey_id, session_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_journey_session_commits_time
                        ON journey_session_commits(journey_id, committed_at);
                    """
                )
                now_ms = int(time.time() * 1000)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO journey_progress
                        (journey_id, route_id, committed_distance_km, updated_at)
                    VALUES ('krakow-santiago', 'krakow-santiago-bicycle-v1', 0, ?)
                    """,
                    (now_ms,),
                )
                for workout in SEED_WORKOUTS:
                    connection.execute(
                        """
                        INSERT INTO live_workout_sessions
                            (id, started_at, status, payload_json, sample_count, hr_sum, updated_at)
                        VALUES (?, ?, ?, ?, 0, 0, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            started_at = excluded.started_at,
                            status = excluded.status,
                            payload_json = excluded.payload_json,
                            updated_at = excluded.updated_at
                        WHERE live_workout_sessions.sample_count = 0
                        """,
                        (
                            workout["id"],
                            workout["started_at"],
                            workout["status"],
                            json.dumps(workout, ensure_ascii=False),
                            workout["started_at"] + workout["duration_seconds"] * 1000,
                        ),
                    )
                legacy_rows = connection.execute(
                    "SELECT id, payload_json, updated_at FROM live_workout_sessions WHERE status IN ('running', 'paused')"
                ).fetchall()
                for row in legacy_rows:
                    payload = json.loads(row["payload_json"])
                    if payload.get("started_by") == "dashboard":
                        if payload.get("status") == "running" and payload.get("runtime_anchor_at") is None:
                            payload["runtime_anchor_at"] = int(row["updated_at"] or payload.get("started_at"))
                            connection.execute(
                                "UPDATE live_workout_sessions SET payload_json = ? WHERE id = ?",
                                (json.dumps(payload, ensure_ascii=False), row["id"]),
                            )
                        continue
                    if "Live telemetry" not in str(payload.get("source") or ""):
                        continue
                    payload["status"] = "monitoring"
                    connection.execute(
                        "UPDATE live_workout_sessions SET status = 'monitoring', payload_json = ? WHERE id = ?",
                        (json.dumps(payload, ensure_ascii=False), row["id"]),
                    )
                finished_rows = connection.execute(
                    "SELECT id, payload_json FROM live_workout_sessions WHERE status = 'finished'"
                ).fetchall()
                for row in finished_rows:
                    payload = json.loads(row["payload_json"])
                    source = str(payload.get("source") or "").lower()
                    if payload.get("started_by") != "dashboard" and not source.startswith("wear os"):
                        continue
                    before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    complete_estimated_metrics(payload)
                    after = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    if before != after:
                        connection.execute(
                            "UPDATE live_workout_sessions SET payload_json = ? WHERE id = ?",
                            (json.dumps(payload, ensure_ascii=False), row["id"]),
                        )
            self._initialized = True

    @staticmethod
    def _decode(row):
        return json.loads(row["payload_json"])

    @staticmethod
    def _materialize_runtime_clock(payload, now_ms=None):
        """Materialize an active dashboard timer without relying on browser state."""
        result = dict(payload or {})
        if result.get("started_by") != "dashboard" or result.get("status") != "running":
            return result
        anchor = result.get("runtime_anchor_at", result.get("started_at"))
        try:
            anchor = int(anchor)
            current = int(now_ms if now_ms is not None else time.time() * 1000)
        except (TypeError, ValueError):
            return result
        if current > anchor:
            result["duration_seconds"] = round(
                max(0, float(result.get("duration_seconds") or 0)) + (current - anchor) / 1000,
                3,
            )
            result["runtime_anchor_at"] = current
        return result

    @staticmethod
    def _apply_dashboard_summary(active, summary):
        summary = dict(summary or {})
        if summary.get("duration_seconds") is not None:
            active["duration_seconds"] = max(
                max(0, float(active.get("duration_seconds") or 0)),
                max(0, round(float(summary["duration_seconds"]), 3)),
            )
        if isinstance(summary.get("zones"), dict):
            active["zones"] = {
                key: max(
                    max(0, float(active.get("zones", {}).get(key, 0) or 0)),
                    max(0, round(float(summary["zones"].get(key, 0) or 0), 3)),
                )
                for key in ZONE_KEYS
            }
        if summary.get("active_calories") is not None:
            active["active_calories"] = max(0, round(float(summary["active_calories"]), 2))
        if summary.get("active_calories_keytel_raw") is not None:
            active["active_calories_keytel_raw"] = max(0, round(float(summary["active_calories_keytel_raw"]), 2))
        if summary.get("calorie_calibration_factor") is not None:
            active["calorie_calibration_factor"] = max(.45, min(.95, round(float(summary["calorie_calibration_factor"]), 6)))
        if summary.get("calorie_method"):
            active["calorie_method"] = str(summary["calorie_method"])
            if active["calorie_method"] == "indoor_cycling_mi_calibrated_v1":
                quality = dict(active.get("data_quality") or {})
                quality["active_calories"] = "estimated_indoor_cycling_mi_calibrated_v1"
                active["data_quality"] = quality
        if isinstance(summary.get("interval_progress_seconds"), list):
            previous = list(active.get("interval_progress_seconds") or [])
            active["interval_progress_seconds"] = [
                max(
                    max(0, float(previous[index] or 0)) if index < len(previous) else 0,
                    max(0, round(float(value or 0), 3)),
                )
                for index, value in enumerate(summary["interval_progress_seconds"])
            ]
        if summary.get("plan_completed_at_elapsed") is not None:
            active["plan_completed_at_elapsed"] = max(0, round(float(summary["plan_completed_at_elapsed"]), 3))
        if summary.get("plan_completed") is not None:
            active["plan_completed"] = bool(summary["plan_completed"])
        for key in ("virtual_walk_active_seconds", "virtual_walk_outside_seconds"):
            if summary.get(key) is not None:
                active[key] = max(
                    max(0, float(active.get(key) or 0)),
                    max(0, round(float(summary[key]), 3)),
                )
        if summary.get("virtual_steps") is not None:
            active["virtual_steps"] = max(0, int(round(float(summary["virtual_steps"]))))
        if summary.get("cadence_rpm_avg") is not None:
            active["cadence_rpm_avg"] = max(0, round(float(summary["cadence_rpm_avg"]), 1))
        if summary.get("distance_km") is not None:
            distance = float(summary["distance_km"])
            if not math.isfinite(distance):
                raise ValueError("distance_km must be finite")
            active["distance_km"] = max(
                max(0, float(active.get("distance_km") or 0)),
                max(0, round(distance, 6)),
            )
        if summary.get("training_load") is not None:
            active["training_load"] = max(0, round(float(summary["training_load"]), 2))
        if isinstance(summary.get("strength_data"), dict):
            active["strength_data"] = summary["strength_data"]
        if isinstance(summary.get("runtime_state"), dict):
            active["runtime_state"] = summary["runtime_state"]
        if summary.get("session_rpe") is not None:
            active["session_rpe"] = max(1, min(10, int(summary["session_rpe"])))
        if summary.get("notes") is not None:
            active["notes"] = str(summary["notes"])[:10000]
        return active

    def history(self, limit=30):
        self.initialize()
        safe_limit = max(1, min(10000, int(limit)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM live_workout_sessions WHERE status != 'monitoring' ORDER BY started_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._materialize_runtime_clock(self._decode(row)) for row in rows]

    def calorie_ranking(self):
        """Return daily active-kcal totals for all completed cardio sessions."""
        self.initialize()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM live_workout_sessions WHERE status = 'finished'"
            ).fetchall()

        days = {}
        for row in rows:
            payload = self._decode(row)
            if payload.get("workout_type") == "strength":
                continue
            try:
                calories = max(0.0, float(payload.get("active_calories") or 0))
                started_at = int(payload.get("started_at"))
            except (TypeError, ValueError):
                continue
            try:
                duration_seconds = max(0.0, float(payload.get("duration_seconds") or 0))
            except (TypeError, ValueError):
                duration_seconds = 0.0
            if not math.isfinite(duration_seconds):
                duration_seconds = 0.0
            if calories <= 0 or started_at <= 0 or not math.isfinite(calories):
                continue
            date = datetime.fromtimestamp(started_at / 1000).date().isoformat()
            day = days.setdefault(date, {
                "date": date,
                "active_calories": 0.0,
                "cycling_calories": 0.0,
                "walking_calories": 0.0,
                "duration_seconds": 0.0,
                "session_count": 0,
                "cycling_session_count": 0,
                "walking_session_count": 0,
            })
            day["active_calories"] += calories
            day["duration_seconds"] += duration_seconds
            day["session_count"] += 1
            if payload.get("workout_type") == "virtual_walk":
                day["walking_calories"] += calories
                day["walking_session_count"] += 1
            else:
                day["cycling_calories"] += calories
                day["cycling_session_count"] += 1

        ranking = sorted(days.values(), key=lambda day: (-day["active_calories"], -int(day["date"].replace("-", ""))))
        for position, day in enumerate(ranking, start=1):
            day["active_calories"] = round(day["active_calories"], 2)
            day["cycling_calories"] = round(day["cycling_calories"], 2)
            day["walking_calories"] = round(day["walking_calories"], 2)
            day["duration_seconds"] = round(day["duration_seconds"], 3)
            day["position"] = position
        return ranking

    def journey_progress(self, journey_id="krakow-santiago"):
        self.initialize()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM journey_progress WHERE journey_id = ?",
                (str(journey_id),),
            ).fetchone()
            commit_count = connection.execute(
                "SELECT COUNT(*) FROM journey_session_commits WHERE journey_id = ?",
                (str(journey_id),),
            ).fetchone()[0]
        return {**dict(row), "committed_session_count": int(commit_count)} if row else None

    @staticmethod
    def _commit_journey_session(
        connection,
        session_id,
        distance_km,
        committed_at,
        journey_id="krakow-santiago",
        route_id="krakow-santiago-bicycle-v1",
    ):
        distance = max(0.0, float(distance_km or 0))
        if not math.isfinite(distance):
            raise ValueError("Journey session distance must be finite")
        connection.execute(
            """
            INSERT OR IGNORE INTO journey_progress
                (journey_id, route_id, committed_distance_km, updated_at)
            VALUES (?, ?, 0, ?)
            """,
            (journey_id, route_id, committed_at),
        )
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO journey_session_commits
                (journey_id, session_id, distance_km, committed_at)
            VALUES (?, ?, ?, ?)
            """,
            (journey_id, str(session_id), distance, committed_at),
        )
        if cursor.rowcount:
            connection.execute(
                """
                UPDATE journey_progress
                SET committed_distance_km = committed_distance_km + ?,
                    route_id = ?, updated_at = ?
                WHERE journey_id = ?
                """,
                (distance, route_id, committed_at, journey_id),
            )
        row = connection.execute(
            "SELECT * FROM journey_progress WHERE journey_id = ?",
            (journey_id,),
        ).fetchone()
        return {**dict(row), "committed": bool(cursor.rowcount), "distance_km": distance}

    def commit_journey_session(self, session_id, distance_km, committed_at=None):
        self.initialize()
        timestamp = normalize_timestamp_ms(committed_at or int(time.time() * 1000))
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = self._commit_journey_session(connection, session_id, distance_km, timestamp)
            connection.commit()
        return result

    def archive_heart_rate(self, payload, received_at=None):
        """Persist one accepted telemetry transmission independently of workout sessions."""
        return self.archive_heart_rates([payload], received_at=received_at)[0]

    def archive_heart_rates(self, payloads, received_at=None):
        """Persist one telemetry batch atomically, preserving each watch timestamp and status."""
        self.initialize()
        received_at = normalize_timestamp_ms(
            received_at or int(__import__("time").time() * 1000)
        )
        samples = []
        for payload in payloads:
            raw_payload = dict(payload)
            samples.append(
                {
                    "timestamp": normalize_timestamp_ms(raw_payload["timestamp"]),
                    "heart_rate": int(raw_payload["heart_rate"]),
                    "status": str(raw_payload["status"]).strip().lower(),
                    "payload": raw_payload,
                }
            )

        archived = []
        with self._lock, self._connect() as connection:
            for sample in samples:
                cursor = connection.execute(
                    """
                    INSERT INTO heart_rate_telemetry
                        (recorded_at, received_at, heart_rate, status, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        sample["timestamp"],
                        received_at,
                        sample["heart_rate"],
                        sample["status"],
                        json.dumps(sample["payload"], ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                archived.append({"id": cursor.lastrowid, "received_at": received_at, **sample})
        return archived

    def heart_rate_history(self, limit=1000, from_timestamp=None, to_timestamp=None):
        self.initialize()
        safe_limit = max(1, min(100000, int(limit)))
        clauses = []
        values = []
        if from_timestamp is not None:
            clauses.append("recorded_at >= ?")
            values.append(normalize_timestamp_ms(from_timestamp))
        if to_timestamp is not None:
            clauses.append("recorded_at <= ?")
            values.append(normalize_timestamp_ms(to_timestamp))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(safe_limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, recorded_at, received_at, heart_rate, status, payload_json
                FROM heart_rate_telemetry
                {where}
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
        samples = [
            {
                "id": row["id"],
                "timestamp": row["recorded_at"],
                "received_at": row["received_at"],
                "heart_rate": row["heart_rate"],
                "status": row["status"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]
        return filter_unworn_heart_rate_samples(samples)

    def latest_heart_rate(self):
        self.initialize()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM heart_rate_telemetry ORDER BY recorded_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def enqueue_outbox(self, event_id, event_type, payload, created_at=None):
        self.initialize()
        now_ms = normalize_timestamp_ms(created_at or int(time.time() * 1000))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO live_workout_outbox
                    (event_id, event_type, payload_json, status, attempts, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', 0, ?, ?)
                """,
                (str(event_id), str(event_type), json.dumps(payload, ensure_ascii=False), now_ms, now_ms),
            )

    def pending_outbox(self, limit=20):
        self.initialize()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM live_workout_outbox WHERE status = 'pending' ORDER BY created_at LIMIT ?",
                (max(1, min(100, int(limit))),),
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def mark_outbox(self, event_id, delivered, error=None):
        self.initialize()
        now_ms = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE live_workout_outbox
                SET status = ?, attempts = attempts + 1, last_error = ?, updated_at = ?
                WHERE event_id = ?
                """,
                ("delivered" if delivered else "pending", str(error or "")[:1000] or None, now_ms, str(event_id)),
            )

    def discard_heart_rate_flatline(self, from_timestamp, to_timestamp, heart_rates):
        """Remove the short confirmation window once a live flatline is confirmed."""
        self.initialize()
        start = normalize_timestamp_ms(from_timestamp)
        end = normalize_timestamp_ms(to_timestamp)
        values = sorted({int(value) for value in (
            heart_rates if isinstance(heart_rates, (list, tuple, set)) else [heart_rates]
        )})
        if not values:
            return 0
        placeholders = ",".join("?" for _value in values)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM heart_rate_telemetry
                WHERE recorded_at >= ? AND recorded_at <= ?
                    AND heart_rate IN ({placeholders})
                """,
                (start, end, *values),
            )
        return cursor.rowcount

    def session(self, session_id):
        self.initialize()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM live_workout_sessions WHERE id = ?",
                (str(session_id),),
            ).fetchone()
            if not row:
                return None
            payload = self._materialize_runtime_clock(self._decode(row))
            samples = connection.execute(
                "SELECT timestamp, heart_rate FROM live_workout_samples WHERE session_id = ? ORDER BY timestamp",
                (str(session_id),),
            ).fetchall()
        payload["samples"] = [dict(sample) for sample in samples]
        return payload

    def delete_session(self, session_id):
        self.initialize()
        safe_id = str(session_id or "").strip()
        if not safe_id:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM live_workout_sessions WHERE id = ?",
                (safe_id,),
            ).fetchone()
            if not row:
                return None
            payload = self._decode(row)
            connection.execute("DELETE FROM live_workout_samples WHERE session_id = ?", (safe_id,))
            connection.execute("DELETE FROM live_workout_sessions WHERE id = ?", (safe_id,))
        return payload

    def cancel_dashboard_session(self, session_id=None):
        active = self.active_dashboard_session()
        if not active:
            return None
        if session_id and str(active["id"]) != str(session_id):
            raise ValueError("Active workout session does not match the requested session")
        return self.delete_session(active["id"])

    def active_dashboard_session(self, now_ms=None):
        self.initialize()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM live_workout_sessions
                WHERE status IN ('running', 'paused')
                ORDER BY started_at DESC
                """
            ).fetchall()
        for row in rows:
            payload = self._decode(row)
            if payload.get("started_by") == "dashboard":
                return self._materialize_runtime_clock(payload, now_ms)
        return None

    def start_dashboard_session(self, metadata=None, timestamp=None, request_id=None):
        self.initialize()
        metadata = dict(metadata or {})
        started_at = normalize_timestamp_ms(timestamp or int(time.time() * 1000))
        session_id = f"dashboard-{uuid.uuid4().hex}"
        payload = {
            "id": session_id,
            "title": metadata.get("title") or "Indoor cycling",
            "started_at": started_at,
            "status": "running",
            "duration_seconds": 0,
            "active_calories": None,
            "active_calories_keytel_raw": None,
            "calorie_calibration_factor": None,
            "total_calories": None,
            "avg_hr": None,
            "max_hr": None,
            "zones": {key: 0 for key in ZONE_KEYS},
            "training_effect": None,
            "training_load": None,
            "recovery_hours": None,
            "source": "Wear OS · sesja sterowana z dashboardu",
            "sample_count": 0,
            "started_by": "dashboard",
            "workout_type": metadata.get("workout_type") or "indoor_cycling",
            "sub_type": metadata.get("sub_type"),
            "plan_id": metadata.get("plan_id"),
            "plan_date": metadata.get("plan_date"),
            "planned_duration_minutes": metadata.get("planned_duration_minutes"),
            "target_zones": metadata.get("target_zones") or {},
            "interval_progress_seconds": [],
            "plan_completed_at_elapsed": None,
            "plan_completed": False,
            "runtime_anchor_at": started_at,
            "start_request_id": str(request_id or "").strip() or None,
        }
        if isinstance(metadata.get("strength_data"), dict):
            payload["strength_data"] = metadata["strength_data"]
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT payload_json FROM live_workout_sessions WHERE status IN ('running', 'paused') ORDER BY started_at DESC"
            ).fetchall()
            active = None
            for row in rows:
                candidate = self._decode(row)
                if candidate.get("started_by") == "dashboard":
                    active = candidate
                    break
            if active:
                if payload["start_request_id"] and active.get("start_request_id") == payload["start_request_id"]:
                    connection.commit()
                    return self._materialize_runtime_clock(active, started_at)
                connection.rollback()
                raise ValueError("Another workout session is already active")
            connection.execute(
                """
                INSERT INTO live_workout_sessions
                    (id, started_at, status, payload_json, sample_count, hr_sum,
                     last_sample_at, last_heart_rate, updated_at)
                VALUES (?, ?, 'running', ?, 0, 0, NULL, NULL, ?)
                """,
                (session_id, started_at, json.dumps(payload, ensure_ascii=False), started_at),
            )
            connection.commit()
        return payload

    def _save_sensor_samples(self, connection, session_id, samples):
        if samples is None:
            return
        if not isinstance(samples, list) or len(samples) > 100:
            raise ValueError("sensor_samples must contain at most 100 events")
        for sample in samples:
            if not isinstance(sample, dict):
                raise ValueError("Invalid sensor sample")
            event_id = str(sample.get("id") or "")
            if not event_id or len(event_id) > 80:
                raise ValueError("Invalid sensor event ID")
            recorded_at = normalize_timestamp_ms(sample.get("timestamp"))
            kind = sample.get("kind")
            status = sample.get("status")
            mode = sample.get("mode")
            if kind not in {"measurement", "state", "distance"} or status not in {"connected", "connecting", "reconnecting", "disconnected"}:
                raise ValueError("Invalid sensor event kind or status")
            if mode not in {None, "CADENCE", "SPEED"}:
                raise ValueError("Invalid sensor mode")
            def optional_number(key, maximum):
                value = sample.get(key)
                if value is None:
                    return None
                number = float(value)
                if not math.isfinite(number) or not 0 <= number <= maximum:
                    raise ValueError(f"Invalid sensor {key}")
                return number
            rpm = optional_number("rpm", 250)
            speed = optional_number("speed_kmh", 120)
            distance = optional_number("distance_km", 1_000_000)
            if distance is None:
                raise ValueError("Sensor distance_km is required")
            heart_rate = optional_number("heart_rate", 240)
            source = str(sample.get("distance_source") or "")[:80]
            connection.execute(
                """INSERT OR IGNORE INTO live_workout_sensor_samples
                   (event_id, session_id, recorded_at, kind, csc_status, csc_mode, csc_stale,
                    cadence_rpm, speed_kmh, distance_km, distance_source, heart_rate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, session_id, recorded_at, kind, status, mode, int(bool(sample.get("stale"))),
                rpm, speed, distance, source, int(heart_rate) if heart_rate is not None else None),
            )

    def sensor_history(self, session_id):
        self.initialize()
        with self._lock, self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM live_workout_sensor_samples WHERE session_id = ? ORDER BY recorded_at, rowid",
                (str(session_id),),
            ).fetchall()]

    def checkpoint_dashboard_session(self, timestamp=None, summary=None, session_id=None, sensor_samples=None):
        changed_at = normalize_timestamp_ms(timestamp or int(time.time() * 1000))
        active = self.active_dashboard_session(changed_at)
        if not active:
            return None
        if session_id and str(active["id"]) != str(session_id):
            raise ValueError("Active workout session does not match the requested session")
        self._apply_dashboard_summary(active, summary)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE live_workout_sessions SET payload_json = ?, updated_at = ? WHERE id = ? AND status IN ('running', 'paused')",
                (json.dumps(active, ensure_ascii=False), changed_at, active["id"]),
            )
            self._save_sensor_samples(connection, active["id"], sensor_samples)
            connection.commit()
        return active

    def control_dashboard_session(self, action, timestamp=None, summary=None, session_id=None, sensor_samples=None):
        changed_at = normalize_timestamp_ms(timestamp or int(time.time() * 1000))
        active = self.active_dashboard_session(changed_at)
        if not active:
            return None
        if session_id and str(active["id"]) != str(session_id):
            raise ValueError("Active workout session does not match the requested session")
        statuses = {"pause": "paused", "resume": "running", "finish": "finished"}
        normalized_action = str(action or "").lower()
        status = statuses.get(normalized_action)
        if not status:
            raise ValueError("Session action must be pause, resume or finish")
        allowed_from = {
            "pause": {"running"},
            "resume": {"paused"},
            "finish": {"running", "paused"},
        }
        if active.get("status") not in allowed_from[normalized_action]:
            raise ValueError(
                f"Cannot {normalized_action} workout session while it is {active.get('status') or 'unknown'}"
            )
        active["status"] = status
        active["runtime_anchor_at"] = changed_at if status == "running" else None
        self._apply_dashboard_summary(active, summary)
        if status == "finished":
            active["ended_at"] = changed_at
            complete_estimated_metrics(active)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE live_workout_sessions
                SET status = ?, payload_json = ?, last_sample_at = NULL,
                    last_heart_rate = NULL, updated_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(active, ensure_ascii=False), changed_at, active["id"]),
            )
            self._save_sensor_samples(connection, active["id"], sensor_samples)
            if status == "finished" and active.get("workout_type") in {"indoor_cycling", "virtual_walk"}:
                self._commit_journey_session(
                    connection,
                    active["id"],
                    active.get("distance_km") or 0,
                    changed_at,
                )
            connection.commit()
        return active

    def ingest_dashboard(self, telemetry):
        active = self.active_dashboard_session()
        if not active or active.get("status") != "running":
            return None
        normalized = dict(telemetry)
        normalized["status"] = "running"
        return self.ingest(normalized, session_id=active["id"])

    def import_summary(self, imported):
        self.initialize()
        started_at = normalize_timestamp_ms(imported["started_at"])
        samples = list(imported.get("samples") or [])
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM live_workout_sessions
                WHERE ABS(started_at - ?) <= 120000
                ORDER BY ABS(started_at - ?) ASC LIMIT 1
                """,
                (started_at, started_at),
            ).fetchone()
            payload = self._decode(row) if row else {
                "id": imported["id"],
                "title": "Indoor cycling",
                "status": "finished",
                "zones": {key: 0 for key in ZONE_KEYS},
                "training_effect": None,
                "training_load": None,
                "recovery_hours": None,
                "sample_count": 0,
            }
            session_id = payload["id"]
            for key in (
                "title",
                "duration_seconds",
                "active_calories",
                "active_calories_keytel_raw",
                "calorie_method",
                "calorie_calibration_factor",
                "total_calories",
                "avg_hr",
                "max_hr",
                "training_effect",
                "training_load",
                "recovery_hours",
                "zones",
                "plan_id",
                "plan_date",
                "planned_duration_minutes",
                "target_zones",
                "workout_type",
                "sub_type",
                "interval_progress_seconds",
                "plan_completed_at_elapsed",
                "plan_completed",
                "virtual_walk_active_seconds",
                "virtual_walk_outside_seconds",
                "virtual_steps",
                "cadence_rpm_avg",
                "strength_data",
                "session_rpe",
                "notes",
                "external_id",
                "import_file",
            ):
                if imported.get(key) is not None:
                    payload[key] = imported[key]
            payload["started_at"] = started_at
            payload["status"] = "finished"
            if payload.get("duration_seconds") is not None:
                payload["ended_at"] = started_at + round(float(payload["duration_seconds"]) * 1000)
            if not row or "screenshot" not in str(payload.get("source") or "").lower():
                payload["source"] = imported.get("source") or "TCX"
            quality = dict(payload.get("data_quality") or {})
            for key, value in (imported.get("data_quality") or {}).items():
                if value != "unavailable" or key not in quality:
                    quality[key] = value
            payload["data_quality"] = quality

            previous_sample_count = int(row["sample_count"]) if row else 0
            previous_hr_sum = int(row["hr_sum"]) if row else 0
            connection.execute(
                """
                INSERT INTO live_workout_sessions
                    (id, started_at, status, payload_json, sample_count, hr_sum,
                     last_sample_at, last_heart_rate, updated_at)
                VALUES (?, ?, 'finished', ?, ?, ?, NULL, NULL, ?)
                ON CONFLICT(id) DO UPDATE SET
                    started_at = excluded.started_at,
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    started_at,
                    json.dumps(payload, ensure_ascii=False),
                    previous_sample_count,
                    previous_hr_sum,
                    started_at,
                ),
            )
            for sample in samples:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO live_workout_samples
                        (session_id, timestamp, heart_rate)
                    VALUES (?, ?, ?)
                    """,
                    (
                        session_id,
                        normalize_timestamp_ms(sample["timestamp"]),
                        int(sample["heart_rate"]),
                    ),
                )

            stored_samples = connection.execute(
                """
                SELECT timestamp, heart_rate FROM live_workout_samples
                WHERE session_id = ? ORDER BY timestamp
                """,
                (session_id,),
            ).fetchall()
            sample_count = len(stored_samples)
            hr_sum = sum(int(sample["heart_rate"]) for sample in stored_samples)
            last_sample_at = stored_samples[-1]["timestamp"] if stored_samples else None
            last_heart_rate = stored_samples[-1]["heart_rate"] if stored_samples else None
            if stored_samples:
                payload["max_hr"] = max(int(sample["heart_rate"]) for sample in stored_samples)
                if imported.get("avg_hr") is None:
                    payload["avg_hr"] = round(hr_sum / sample_count)
                imported_zones = {key: 0.0 for key in ZONE_KEYS}
                for previous, current in zip(stored_samples, stored_samples[1:]):
                    delta = max(0, min(5, (current["timestamp"] - previous["timestamp"]) / 1000))
                    imported_zones[zone_key_for_hr(previous["heart_rate"])] += delta
                payload["zones"] = {key: round(value, 3) for key, value in imported_zones.items()}
                payload["data_quality"]["zones"] = "tcx_samples"
            payload["sample_count"] = sample_count
            connection.execute(
                """
                UPDATE live_workout_sessions
                SET payload_json = ?, sample_count = ?, hr_sum = ?,
                    last_sample_at = ?, last_heart_rate = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(payload, ensure_ascii=False),
                    sample_count,
                    hr_sum,
                    last_sample_at,
                    last_heart_rate,
                    started_at,
                    session_id,
                ),
            )
            connection.commit()
        return payload

    def ingest(self, telemetry, session_id=None):
        self.initialize()
        timestamp = normalize_timestamp_ms(telemetry["timestamp"])
        heart_rate = int(telemetry["heart_rate"])
        status = telemetry["status"]
        if status == "ready":
            return None

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if session_id:
                row = connection.execute(
                    "SELECT * FROM live_workout_sessions WHERE id = ? AND status IN ('running', 'paused')",
                    (str(session_id),),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM live_workout_sessions
                    WHERE status IN ('running', 'paused')
                    ORDER BY started_at DESC LIMIT 1
                    """
                ).fetchone()
            if row is None:
                if session_id:
                    connection.commit()
                    return None
                if status != "running":
                    connection.commit()
                    return None
                session_id = f"wear-{uuid.uuid4().hex}"
                payload = {
                    "id": session_id,
                    "title": "Indoor cycling",
                    "started_at": timestamp,
                    "status": "running",
                    "duration_seconds": 0,
                    "active_calories": None,
                    "total_calories": None,
                    "avg_hr": heart_rate,
                    "max_hr": heart_rate,
                    "zones": {key: 0 for key in ZONE_KEYS},
                    "training_effect": None,
                    "training_load": None,
                    "recovery_hours": None,
                    "source": "Wear OS · Live telemetry",
                    "sample_count": 0,
                }
                connection.execute(
                    """
                    INSERT INTO live_workout_sessions
                        (id, started_at, status, payload_json, sample_count, hr_sum,
                         last_sample_at, last_heart_rate, updated_at)
                    VALUES (?, ?, ?, ?, 0, 0, NULL, NULL, ?)
                    """,
                    (session_id, timestamp, "running", json.dumps(payload, ensure_ascii=False), timestamp),
                )
                row = connection.execute(
                    "SELECT * FROM live_workout_sessions WHERE id = ?", (session_id,)
                ).fetchone()

            inserted = connection.execute(
                "INSERT OR IGNORE INTO live_workout_samples (session_id, timestamp, heart_rate) VALUES (?, ?, ?)",
                (row["id"], timestamp, heart_rate),
            ).rowcount
            if not inserted:
                payload = self._decode(row)
                if status != row["status"]:
                    payload["status"] = status
                    if status == "finished":
                        payload["ended_at"] = timestamp
                        complete_estimated_metrics(payload)
                    connection.execute(
                        """
                        UPDATE live_workout_sessions
                        SET status = ?, payload_json = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (status, json.dumps(payload, ensure_ascii=False), timestamp, row["id"]),
                    )
                connection.commit()
                return payload

            payload = self._decode(row)
            zones = {key: float(payload.get("zones", {}).get(key, 0) or 0) for key in ZONE_KEYS}
            dashboard_owned = payload.get("started_by") == "dashboard"
            if dashboard_owned:
                payload = self._materialize_runtime_clock(payload, timestamp)
            duration = float(payload.get("duration_seconds", 0) or 0)
            if row["last_sample_at"] is not None and row["status"] == "running":
                delta = max(0, min(5, (timestamp - row["last_sample_at"]) / 1000))
                if delta:
                    zones[zone_key_for_hr(row["last_heart_rate"])] += delta
                    if not dashboard_owned:
                        duration += delta

            sample_count = int(row["sample_count"]) + 1
            hr_sum = int(row["hr_sum"]) + heart_rate
            payload.update(
                {
                    "status": status,
                    "duration_seconds": round(duration, 3),
                    "avg_hr": round(hr_sum / sample_count),
                    "max_hr": max(int(payload.get("max_hr") or 0), heart_rate),
                    "zones": {key: round(value, 3) for key, value in zones.items()},
                    "sample_count": sample_count,
                }
            )
            if status == "finished":
                payload["ended_at"] = timestamp
                complete_estimated_metrics(payload)

            connection.execute(
                """
                UPDATE live_workout_sessions
                SET status = ?, payload_json = ?, sample_count = ?, hr_sum = ?,
                    last_sample_at = ?, last_heart_rate = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    sample_count,
                    hr_sum,
                    timestamp,
                    heart_rate,
                    timestamp,
                    row["id"],
                ),
            )
            connection.commit()
        return payload
