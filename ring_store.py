"""Isolated SQLite persistence for COLMI ring data and BLE diagnostics."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RingStore:
    """Owns isolated Wearable Lab persistence; no table is shared with dashboard health data."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialized = False
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._init_lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS devices (
                        device_id TEXT PRIMARY KEY,
                        ble_id TEXT NOT NULL UNIQUE,
                        advertised_name TEXT,
                        model TEXT,
                        firmware_version TEXT,
                        hardware_version TEXT,
                        battery_percentage INTEGER CHECK (battery_percentage BETWEEN 0 AND 100),
                        charging INTEGER CHECK (charging IN (0, 1)),
                        rssi INTEGER,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        last_connected TEXT,
                        last_disconnected TEXT,
                        last_successful_sync TEXT,
                        selected INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0, 1)),
                        source_mode TEXT NOT NULL DEFAULT 'real'
                    );

                    CREATE TABLE IF NOT EXISTS heart_rate (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                        timestamp_utc TEXT NOT NULL,
                        bpm INTEGER NOT NULL,
                        source_mode TEXT NOT NULL,
                        source_slot INTEGER,
                        source_day_offset INTEGER,
                        source TEXT NOT NULL DEFAULT 'colmi-r10',
                        parser TEXT NOT NULL DEFAULT 'colmi-command',
                        protocol_confidence TEXT NOT NULL DEFAULT 'stable',
                        raw_json TEXT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS watch_heart_rate_reference (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ring_device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                        timestamp_utc TEXT NOT NULL,
                        bpm INTEGER NOT NULL,
                        data_origin TEXT NOT NULL,
                        device_type INTEGER,
                        manufacturer TEXT,
                        model TEXT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS spo2 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                        timestamp_utc TEXT,
                        source_slot INTEGER,
                        source_day_offset INTEGER,
                        spo2 INTEGER,
                        spo2_min INTEGER,
                        spo2_max INTEGER,
                        source_mode TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'colmi-r10',
                        parser TEXT NOT NULL,
                        protocol_confidence TEXT NOT NULL,
                        raw_json TEXT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS activity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                        timestamp_utc TEXT,
                        source_slot INTEGER,
                        source_day_offset INTEGER,
                        steps INTEGER,
                        distance_m REAL,
                        calories_kcal REAL,
                        source TEXT NOT NULL DEFAULT 'colmi-r10',
                        parser TEXT NOT NULL,
                        protocol_confidence TEXT NOT NULL,
                        raw_json TEXT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS hrv (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                        timestamp_utc TEXT,
                        source_slot INTEGER,
                        source_day_offset INTEGER,
                        ring_value REAL NOT NULL,
                        metric_label TEXT NOT NULL DEFAULT 'ring-provided HRV proxy',
                        source TEXT NOT NULL DEFAULT 'colmi-r10',
                        parser TEXT NOT NULL,
                        protocol_confidence TEXT NOT NULL DEFAULT 'experimental',
                        raw_json TEXT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sleep_nights (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                        sleep_date TEXT,
                        sleep_start_utc TEXT,
                        sleep_end_utc TEXT,
                        total_minutes INTEGER,
                        awake_minutes INTEGER,
                        light_minutes INTEGER,
                        deep_minutes INTEGER,
                        rem_minutes INTEGER,
                        source_day_offset INTEGER,
                        source TEXT NOT NULL DEFAULT 'colmi-r10',
                        parser TEXT NOT NULL,
                        protocol_confidence TEXT NOT NULL DEFAULT 'experimental',
                        raw_json TEXT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sleep_segments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sleep_night_id INTEGER NOT NULL REFERENCES sleep_nights(id) ON DELETE CASCADE,
                        sequence_no INTEGER NOT NULL,
                        stage TEXT NOT NULL CHECK (stage IN ('awake', 'light', 'deep', 'rem', 'unknown')),
                        duration_minutes INTEGER NOT NULL,
                        start_utc TEXT,
                        end_utc TEXT,
                        raw_json TEXT,
                        UNIQUE (sleep_night_id, sequence_no)
                    );

                    CREATE TABLE IF NOT EXISTS sync_runs (
                        sync_id TEXT PRIMARY KEY,
                        device_id TEXT REFERENCES devices(device_id) ON DELETE SET NULL,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        status TEXT NOT NULL,
                        requested_types_json TEXT NOT NULL,
                        current_dataset TEXT,
                        records_received INTEGER NOT NULL DEFAULT 0,
                        records_json TEXT NOT NULL DEFAULT '{}',
                        error_code TEXT,
                        error_message TEXT,
                        source_mode TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS ble_packets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_utc TEXT NOT NULL,
                        device_id TEXT REFERENCES devices(device_id) ON DELETE SET NULL,
                        direction TEXT NOT NULL CHECK (direction IN ('RX', 'TX')),
                        service_uuid TEXT,
                        characteristic_uuid TEXT,
                        opcode INTEGER,
                        payload_hex TEXT NOT NULL,
                        parsed_type TEXT,
                        parser_status TEXT NOT NULL,
                        error_message TEXT,
                        source_transport TEXT NOT NULL DEFAULT 'pc-ble',
                        external_id TEXT
                    );

                    CREATE TABLE IF NOT EXISTS collector_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_utc TEXT NOT NULL,
                        level TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details_json TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_ring_hr_device_time ON heart_rate(device_id, timestamp_utc);
                    CREATE INDEX IF NOT EXISTS idx_watch_reference_hr_time ON watch_heart_rate_reference(ring_device_id, timestamp_utc);
                    CREATE INDEX IF NOT EXISTS idx_ring_spo2_device_time ON spo2(device_id, timestamp_utc);
                    CREATE INDEX IF NOT EXISTS idx_ring_activity_device_time ON activity(device_id, timestamp_utc);
                    CREATE INDEX IF NOT EXISTS idx_ring_hrv_device_time ON hrv(device_id, timestamp_utc);
                    CREATE INDEX IF NOT EXISTS idx_ring_packets_time ON ble_packets(timestamp_utc DESC);
                    CREATE INDEX IF NOT EXISTS idx_ring_sync_time ON sync_runs(started_at DESC);
                    """
                )
                for table in ("heart_rate", "spo2", "activity", "hrv", "sleep_nights"):
                    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                    if "source" not in columns:
                        connection.execute(
                            f"ALTER TABLE {table} ADD COLUMN source TEXT NOT NULL DEFAULT 'colmi-r10'"
                        )
                packet_columns = {row[1] for row in connection.execute("PRAGMA table_info(ble_packets)")}
                if "source_transport" not in packet_columns:
                    connection.execute(
                        "ALTER TABLE ble_packets ADD COLUMN source_transport TEXT NOT NULL DEFAULT 'pc-ble'"
                    )
                if "external_id" not in packet_columns:
                    connection.execute("ALTER TABLE ble_packets ADD COLUMN external_id TEXT")
                connection.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS idx_ring_packets_external_id
                       ON ble_packets(external_id) WHERE external_id IS NOT NULL"""
                )
            self._initialized = True

    @staticmethod
    def device_id_for(ble_id: str) -> str:
        digest = hashlib.sha256(str(ble_id).strip().lower().encode("utf-8")).hexdigest()[:20]
        return f"colmi_{digest}"

    def upsert_device(
        self,
        *,
        ble_id: str,
        advertised_name: str | None,
        rssi: int | None,
        source_mode: str,
    ) -> dict[str, Any]:
        now = utc_now()
        device_id = self.device_id_for(ble_id)
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO devices(
                    device_id, ble_id, advertised_name, model, rssi,
                    first_seen, last_seen, source_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ble_id) DO UPDATE SET
                    advertised_name = COALESCE(excluded.advertised_name, devices.advertised_name),
                    model = COALESCE(devices.model, excluded.model),
                    rssi = COALESCE(excluded.rssi, devices.rssi),
                    last_seen = excluded.last_seen,
                    source_mode = excluded.source_mode
                """,
                (
                    device_id,
                    ble_id,
                    advertised_name,
                    advertised_name if advertised_name and advertised_name.upper().startswith("R10") else None,
                    rssi,
                    now,
                    now,
                    source_mode,
                ),
            )
            row = connection.execute("SELECT * FROM devices WHERE ble_id = ?", (ble_id,)).fetchone()
        return self._device_payload(row)

    def select_device(self, device_id: str) -> None:
        with self._write() as connection:
            connection.execute("UPDATE devices SET selected = 0")
            updated = connection.execute(
                "UPDATE devices SET selected = 1, last_connected = ? WHERE device_id = ?",
                (utc_now(), device_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Ring device was not found")

    def update_device_info(self, device_id: str, **values: Any) -> None:
        allowed = {
            "advertised_name", "model", "firmware_version", "hardware_version",
            "battery_percentage", "charging", "rssi", "last_successful_sync",
            "last_disconnected",
        }
        fields = []
        params = []
        for key, value in values.items():
            if key not in allowed:
                continue
            fields.append(f"{key} = ?")
            params.append(int(value) if key == "charging" and value is not None else value)
        if not fields:
            return
        params.append(device_id)
        with self._write() as connection:
            connection.execute(f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?", params)

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return self._device_payload(row) if row else None

    def selected_device(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM devices WHERE selected = 1 ORDER BY last_connected DESC LIMIT 1"
            ).fetchone()
        return self._device_payload(row) if row else None

    def list_devices(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM devices ORDER BY selected DESC, last_seen DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._device_payload(row) for row in rows]

    @staticmethod
    def _device_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "deviceId": row["device_id"],
            "bleId": row["ble_id"],
            "advertisedName": row["advertised_name"],
            "model": row["model"],
            "firmwareVersion": row["firmware_version"],
            "hardwareVersion": row["hardware_version"],
            "batteryPercentage": row["battery_percentage"],
            "charging": None if row["charging"] is None else bool(row["charging"]),
            "rssi": row["rssi"],
            "firstSeen": row["first_seen"],
            "lastSeen": row["last_seen"],
            "lastConnected": row["last_connected"],
            "lastDisconnected": row["last_disconnected"],
            "lastSuccessfulSync": row["last_successful_sync"],
            "selected": bool(row["selected"]),
            "sourceMode": row["source_mode"],
        }

    def start_sync(self, device_id: str | None, requested_types: list[str], source_mode: str) -> str:
        sync_id = uuid.uuid4().hex
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs(
                    sync_id, device_id, started_at, status, requested_types_json, source_mode
                ) VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (sync_id, device_id, utc_now(), json.dumps(requested_types), source_mode),
            )
        return sync_id

    def finish_sync(
        self,
        sync_id: str,
        *,
        success: bool,
        records: dict[str, int] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        record_counts = records or {}
        with self._write() as connection:
            connection.execute(
                """
                UPDATE sync_runs SET ended_at = ?, status = ?, current_dataset = NULL,
                    records_received = ?, records_json = ?, error_code = ?, error_message = ?
                WHERE sync_id = ?
                """,
                (
                    utc_now(),
                    "success" if success else "failure",
                    sum(int(value) for value in record_counts.values()),
                    json.dumps(record_counts, sort_keys=True),
                    error_code,
                    error_message,
                    sync_id,
                ),
            )

    def update_sync_progress(self, sync_id: str, current_dataset: str, records: dict[str, int]) -> None:
        with self._write() as connection:
            connection.execute(
                """
                UPDATE sync_runs SET current_dataset = ?, records_received = ?, records_json = ?
                WHERE sync_id = ? AND status = 'running'
                """,
                (
                    current_dataset,
                    sum(int(value) for value in records.values()),
                    json.dumps(records, sort_keys=True),
                    sync_id,
                ),
            )

    def record_packet(
        self,
        *,
        device_id: str | None,
        direction: str,
        service_uuid: str | None,
        characteristic_uuid: str | None,
        payload: bytes | bytearray,
        parsed_type: str | None,
        parser_status: str,
        error_message: str | None = None,
        timestamp_utc: str | None = None,
        source_transport: str = "pc-ble",
        external_id: str | None = None,
    ) -> int:
        raw = bytes(payload)
        with self._write() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ble_packets(
                    timestamp_utc, device_id, direction, service_uuid, characteristic_uuid,
                    opcode, payload_hex, parsed_type, parser_status, error_message,
                    source_transport, external_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp_utc or utc_now(), device_id, direction, service_uuid, characteristic_uuid,
                    raw[0] if raw else None, raw.hex(" ").upper(), parsed_type,
                    parser_status, error_message, source_transport, external_id,
                ),
            )
        return cursor.rowcount

    def record_event(self, level: str, event_type: str, message: str, details: Any = None) -> None:
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO collector_events(timestamp_utc, level, event_type, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utc_now(), level, event_type, message, json.dumps(details) if details is not None else None),
            )

    def ingest_heart_rate(self, device_id: str, records: list[dict[str, Any]]) -> int:
        inserted = 0
        now = utc_now()
        with self._write() as connection:
            for record in records:
                timestamp = str(record["timestampUtc"])
                source_mode = str(record.get("sourceMode") or "history")
                bpm = int(record["bpm"])
                if not 30 <= bpm <= 220:
                    continue
                identity = json.dumps(
                    [device_id, timestamp, source_mode, bpm, record.get("sourceSlot")],
                    separators=(",", ":"),
                )
                dedupe_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO heart_rate(
                        device_id, timestamp_utc, bpm, source_mode, source_slot,
                        source_day_offset, source, parser, protocol_confidence,
                        raw_json, dedupe_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id, timestamp, bpm, source_mode, record.get("sourceSlot"),
                        record.get("sourceDayOffset"), record.get("source", "colmi-r10"),
                        record.get("parser", "colmi-command"),
                        record.get("protocolConfidence", "stable"),
                        json.dumps(record.get("raw")) if record.get("raw") is not None else None,
                        dedupe_key, now,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def ingest_watch_heart_rate_reference(self, device_id: str, records: list[dict[str, Any]]) -> int:
        inserted = 0
        now = utc_now()
        with self._write() as connection:
            for record in records:
                timestamp = str(record["timestampUtc"])
                bpm = int(record["bpm"])
                if not 30 <= bpm <= 240:
                    continue
                data_origin = str(record.get("dataOrigin") or "health-connect")[:255]
                dedupe_key = self._dedupe_key([timestamp, bpm, data_origin])
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO watch_heart_rate_reference(
                        ring_device_id, timestamp_utc, bpm, data_origin, device_type,
                        manufacturer, model, dedupe_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id, timestamp, bpm, data_origin, record.get("deviceType"),
                        record.get("manufacturer"), record.get("model"), dedupe_key, now,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    @staticmethod
    def _dedupe_key(parts: list[Any]) -> str:
        identity = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def ingest_spo2(self, device_id: str, records: list[dict[str, Any]]) -> int:
        inserted = 0
        now = utc_now()
        with self._write() as connection:
            for record in records:
                dedupe_key = self._dedupe_key([
                    device_id, record.get("timestampUtc"), record.get("sourceMode"),
                    record.get("sourceSlot"), record.get("spo2"), record.get("spo2Min"),
                    record.get("spo2Max"),
                ])
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO spo2(
                        device_id, timestamp_utc, source_slot, source_day_offset, spo2,
                        spo2_min, spo2_max, source_mode, source, parser,
                        protocol_confidence, raw_json, dedupe_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id, record.get("timestampUtc"), record.get("sourceSlot"),
                        record.get("sourceDayOffset"), record.get("spo2"),
                        record.get("spo2Min"), record.get("spo2Max"),
                        record.get("sourceMode", "history"), record.get("source", "colmi-r10"),
                        record.get("parser", "colmi-command"),
                        record.get("protocolConfidence", "stable"),
                        json.dumps(record.get("raw")) if record.get("raw") is not None else None,
                        dedupe_key, now,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def ingest_activity(self, device_id: str, records: list[dict[str, Any]]) -> int:
        inserted = 0
        now = utc_now()
        with self._write() as connection:
            for record in records:
                dedupe_key = self._dedupe_key([
                    device_id, record.get("timestampUtc"), record.get("sourceSlot"),
                    record.get("steps"), record.get("distanceM"), record.get("caloriesKcal"),
                ])
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO activity(
                        device_id, timestamp_utc, source_slot, source_day_offset, steps,
                        distance_m, calories_kcal, source, parser, protocol_confidence,
                        raw_json, dedupe_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id, record.get("timestampUtc"), record.get("sourceSlot"),
                        record.get("sourceDayOffset"), record.get("steps"),
                        record.get("distanceM"), record.get("caloriesKcal"),
                        record.get("source", "colmi-r10"),
                        record.get("parser", "colmi-command"),
                        record.get("protocolConfidence", "stable"),
                        json.dumps(record.get("raw")) if record.get("raw") is not None else None,
                        dedupe_key, now,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def ingest_hrv(self, device_id: str, records: list[dict[str, Any]]) -> int:
        inserted = 0
        now = utc_now()
        with self._write() as connection:
            for record in records:
                dedupe_key = self._dedupe_key([
                    device_id, record.get("timestampUtc"), record.get("sourceSlot"), record.get("ringValue")
                ])
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO hrv(
                        device_id, timestamp_utc, source_slot, source_day_offset, ring_value,
                        metric_label, source, parser, protocol_confidence, raw_json,
                        dedupe_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id, record.get("timestampUtc"), record.get("sourceSlot"),
                        record.get("sourceDayOffset"), record.get("ringValue"),
                        "ring-provided HRV proxy", record.get("source", "colmi-r10"),
                        record.get("parser", "colmi-command"),
                        record.get("protocolConfidence", "experimental"),
                        json.dumps(record.get("raw")) if record.get("raw") is not None else None,
                        dedupe_key, now,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def ingest_sleep(self, device_id: str, nights: list[dict[str, Any]]) -> int:
        inserted = 0
        now = utc_now()
        with self._write() as connection:
            for night in nights:
                dedupe_key = self._dedupe_key([
                    device_id, night.get("sleepDate"), night.get("sleepStartUtc"),
                    night.get("sleepEndUtc"), night.get("stages"),
                ])
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO sleep_nights(
                        device_id, sleep_date, sleep_start_utc, sleep_end_utc, total_minutes,
                        awake_minutes, light_minutes, deep_minutes, rem_minutes,
                        source_day_offset, source, parser, protocol_confidence, raw_json,
                        dedupe_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id, night.get("sleepDate"), night.get("sleepStartUtc"),
                        night.get("sleepEndUtc"), night.get("totalMinutes"),
                        night.get("awakeMinutes"), night.get("lightMinutes"),
                        night.get("deepMinutes"), night.get("remMinutes"),
                        night.get("sourceDayOffset"), night.get("source", "colmi-r10"),
                        night.get("parser", "colmi-big-data"),
                        night.get("protocolConfidence", "experimental"),
                        json.dumps(night.get("raw")) if night.get("raw") is not None else None,
                        dedupe_key, now,
                    ),
                )
                inserted += cursor.rowcount
                row = connection.execute(
                    "SELECT id FROM sleep_nights WHERE dedupe_key = ?", (dedupe_key,)
                ).fetchone()
                if not row:
                    continue
                night_id = int(row["id"])
                cursor_time = night.get("sleepStartUtc")
                for sequence, segment in enumerate(night.get("stages") or []):
                    duration = max(0, int(segment.get("durationMinutes") or 0))
                    segment_end = None
                    if cursor_time and duration:
                        parsed_start = datetime.fromisoformat(cursor_time.replace("Z", "+00:00"))
                        segment_end = (
                            parsed_start + timedelta(minutes=duration)
                        ).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO sleep_segments(
                            sleep_night_id, sequence_no, stage, duration_minutes,
                            start_utc, end_utc, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            night_id, sequence, segment.get("stage"),
                            duration, cursor_time, segment_end,
                            json.dumps(segment, sort_keys=True),
                        ),
                    )
                    cursor_time = segment_end or cursor_time
        return inserted

    def history(self, device_id: str | None = None, limit: int = 2000) -> dict[str, Any]:
        selected = self.selected_device()
        active_id = device_id or (selected["deviceId"] if selected else None)
        if not active_id:
            return {
                "deviceId": None, "heartRate": [], "watchHeartRateReference": [],
                "spo2": [], "activity": [], "hrv": [], "sleep": [],
            }
        safe_limit = max(1, min(10000, int(limit)))
        with self._connect() as connection:
            heart_rate = connection.execute(
                """SELECT timestamp_utc AS timestampUtc, bpm, source_mode AS sourceMode
                   FROM heart_rate WHERE device_id = ? AND bpm BETWEEN 30 AND 220
                   ORDER BY timestamp_utc DESC LIMIT ?""",
                (active_id, safe_limit),
            ).fetchall()
            watch_heart_rate = connection.execute(
                """SELECT timestamp_utc AS timestampUtc, bpm, data_origin AS dataOrigin,
                          device_type AS deviceType, manufacturer, model
                   FROM watch_heart_rate_reference WHERE ring_device_id = ?
                   ORDER BY timestamp_utc DESC LIMIT ?""",
                (active_id, safe_limit),
            ).fetchall()
            spo2 = connection.execute(
                """SELECT timestamp_utc AS timestampUtc, spo2, spo2_min AS spo2Min,
                          spo2_max AS spo2Max, source_mode AS sourceMode
                   FROM spo2 WHERE device_id = ? ORDER BY timestamp_utc DESC LIMIT ?""",
                (active_id, safe_limit),
            ).fetchall()
            activity = connection.execute(
                """SELECT timestamp_utc AS timestampUtc, steps, distance_m AS distanceM,
                          calories_kcal AS caloriesKcal, source_slot AS sourceSlot
                   FROM activity WHERE device_id = ? ORDER BY timestamp_utc DESC LIMIT ?""",
                (active_id, safe_limit),
            ).fetchall()
            hrv = connection.execute(
                """SELECT timestamp_utc AS timestampUtc, ring_value AS ringValue,
                          metric_label AS metricLabel
                   FROM hrv WHERE device_id = ? ORDER BY timestamp_utc DESC LIMIT ?""",
                (active_id, safe_limit),
            ).fetchall()
            nights = connection.execute(
                """SELECT * FROM sleep_nights WHERE device_id = ?
                   ORDER BY sleep_date DESC, sleep_start_utc DESC""",
                (active_id,),
            ).fetchall()
            sleep = []
            for night in nights:
                segments = connection.execute(
                    """SELECT sequence_no AS sequenceNo, stage, duration_minutes AS durationMinutes,
                              start_utc AS startUtc, end_utc AS endUtc
                       FROM sleep_segments WHERE sleep_night_id = ? ORDER BY sequence_no""",
                    (night["id"],),
                ).fetchall()
                payload = {
                    "sleepDate": night["sleep_date"],
                    "sleepStartUtc": night["sleep_start_utc"],
                    "sleepEndUtc": night["sleep_end_utc"],
                    "totalMinutes": night["total_minutes"],
                    "awakeMinutes": night["awake_minutes"],
                    "lightMinutes": night["light_minutes"],
                    "deepMinutes": night["deep_minutes"],
                    "remMinutes": night["rem_minutes"],
                    "createdAt": night["created_at"],
                    "stages": [dict(segment) for segment in segments],
                }
                sleep.append(payload)
        return {
            "deviceId": active_id,
            "heartRate": list(reversed([dict(row) for row in heart_rate])),
            "watchHeartRateReference": list(reversed([dict(row) for row in watch_heart_rate])),
            "spo2": list(reversed([dict(row) for row in spo2])),
            "activity": list(reversed([dict(row) for row in activity])),
            "hrv": list(reversed([dict(row) for row in hrv])),
            "sleep": sleep,
        }

    def heart_rate_archive(
        self,
        device_id: str | None = None,
        *,
        limit: int = 10000,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Read ring HR and the smartwatch reference for one archive range."""
        selected = self.selected_device()
        active_id = device_id or (selected["deviceId"] if selected else None)
        if not active_id:
            return {"deviceId": None, "heartRate": [], "watchHeartRateReference": []}

        safe_limit = max(1, min(100000, int(limit)))
        clauses = ["device_id = ?", "bpm BETWEEN 30 AND 220"]
        reference_clauses = ["ring_device_id = ?", "bpm BETWEEN 30 AND 240"]
        values: list[Any] = [active_id]
        reference_values: list[Any] = [active_id]

        def utc_iso(timestamp: int) -> str:
            return (
                datetime.fromtimestamp(int(timestamp) / 1000, timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )

        if from_timestamp is not None:
            start = utc_iso(from_timestamp)
            clauses.append("timestamp_utc >= ?")
            reference_clauses.append("timestamp_utc >= ?")
            values.append(start)
            reference_values.append(start)
        if to_timestamp is not None:
            end = utc_iso(to_timestamp)
            clauses.append("timestamp_utc <= ?")
            reference_clauses.append("timestamp_utc <= ?")
            values.append(end)
            reference_values.append(end)
        values.append(safe_limit)
        reference_values.append(safe_limit)

        with self._connect() as connection:
            heart_rate = connection.execute(
                f"""SELECT id, timestamp_utc AS timestampUtc, bpm,
                           source_mode AS sourceMode, source, parser,
                           protocol_confidence AS protocolConfidence,
                           created_at AS createdAt
                    FROM heart_rate
                    WHERE {' AND '.join(clauses)}
                    ORDER BY timestamp_utc DESC, id DESC
                    LIMIT ?""",
                values,
            ).fetchall()
            watch_reference = connection.execute(
                f"""SELECT id, timestamp_utc AS timestampUtc, bpm,
                           data_origin AS dataOrigin, device_type AS deviceType,
                           manufacturer, model, created_at AS createdAt
                    FROM watch_heart_rate_reference
                    WHERE {' AND '.join(reference_clauses)}
                    ORDER BY timestamp_utc DESC, id DESC
                    LIMIT ?""",
                reference_values,
            ).fetchall()
        return {
            "deviceId": active_id,
            "heartRate": [dict(row) for row in heart_rate],
            "watchHeartRateReference": [dict(row) for row in watch_reference],
        }

    def overview(self) -> dict[str, Any]:
        device = self.selected_device()
        with self._connect() as connection:
            device_id = device["deviceId"] if device else ""
            latest_hr = connection.execute(
                "SELECT timestamp_utc, bpm, source_mode FROM heart_rate WHERE device_id = ? AND bpm BETWEEN 30 AND 220 ORDER BY timestamp_utc DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            latest_spo2 = connection.execute(
                "SELECT timestamp_utc, spo2, spo2_min, spo2_max, source_mode FROM spo2 WHERE device_id = ? ORDER BY timestamp_utc DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            latest_hrv = connection.execute(
                "SELECT timestamp_utc, ring_value, metric_label FROM hrv WHERE device_id = ? ORDER BY timestamp_utc DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            latest_activity = connection.execute(
                "SELECT timestamp_utc, steps, distance_m, calories_kcal FROM activity WHERE device_id = ? ORDER BY timestamp_utc DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            latest_sleep = connection.execute(
                "SELECT * FROM sleep_nights WHERE device_id = ? ORDER BY sleep_date DESC, created_at DESC LIMIT 1",
                (device_id,),
            ).fetchone()
        return {
            "device": device,
            "latest": {
                "heartRate": dict(latest_hr) if latest_hr else None,
                "spo2": dict(latest_spo2) if latest_spo2 else None,
                "hrv": dict(latest_hrv) if latest_hrv else None,
                "activity": dict(latest_activity) if latest_activity else None,
                "sleep": dict(latest_sleep) if latest_sleep else None,
            },
        }

    def diagnostics(self, limit: int = 100) -> dict[str, Any]:
        safe_limit = max(1, min(500, int(limit)))
        with self._connect() as connection:
            packets = connection.execute(
                "SELECT * FROM ble_packets ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM collector_events ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
            syncs = connection.execute(
                "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 25"
            ).fetchall()
        return {
            "packets": [dict(row) for row in packets],
            "events": [dict(row) for row in events],
            "syncRuns": [dict(row) for row in syncs],
        }
