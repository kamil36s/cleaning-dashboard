from __future__ import annotations

import json
from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .scanning import (
    OWNER_ALIASES,
    DeviceObservation,
    ScanResult,
    normalize_device_category,
    normalize_mac,
    normalize_owner_label,
)


def device_key_for(observation: DeviceObservation) -> str:
    return observation.mac or f"ip:{observation.ip}"


class NetworkStore:
    def __init__(self, db_path: Path, names_path: Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.names_path = Path(names_path) if names_path else None
        if self.names_path:
            self.names_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_key TEXT PRIMARY KEY,
                    ip TEXT,
                    mac TEXT,
                    name TEXT,
                    detected_name TEXT,
                    custom_name TEXT,
                    custom_category TEXT,
                    custom_owner TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    is_online INTEGER NOT NULL DEFAULT 0,
                    online_since TEXT,
                    last_offline_at TEXT,
                    last_method TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_devices_last_seen
                ON devices(last_seen DESC);

                CREATE INDEX IF NOT EXISTS idx_devices_mac
                ON devices(mac);

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_finished_at TEXT NOT NULL,
                    device_key TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    mac TEXT,
                    name TEXT,
                    detected_name TEXT,
                    custom_name TEXT,
                    custom_category TEXT,
                    custom_owner TEXT,
                    is_online INTEGER NOT NULL,
                    method TEXT NOT NULL,
                    FOREIGN KEY (device_key) REFERENCES devices(device_key)
                );

                CREATE INDEX IF NOT EXISTS idx_observations_scan
                ON observations(scan_finished_at DESC);

                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    networks_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    discovered_count INTEGER NOT NULL,
                    online_count INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS device_state_intervals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds INTEGER,
                    FOREIGN KEY (device_key) REFERENCES devices(device_key)
                );

                CREATE INDEX IF NOT EXISTS idx_device_state_intervals_key_start
                ON device_state_intervals(device_key, started_at DESC);
                """
            )
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        device_columns = {row["name"] for row in conn.execute("PRAGMA table_info(devices)")}
        observation_columns = {row["name"] for row in conn.execute("PRAGMA table_info(observations)")}

        if "detected_name" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN detected_name TEXT")
        if "custom_name" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN custom_name TEXT")
        if "custom_category" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN custom_category TEXT")
        if "custom_owner" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN custom_owner TEXT")
        if "online_since" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN online_since TEXT")
        if "last_offline_at" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN last_offline_at TEXT")

        if "detected_name" not in observation_columns:
            conn.execute("ALTER TABLE observations ADD COLUMN detected_name TEXT")
        if "custom_name" not in observation_columns:
            conn.execute("ALTER TABLE observations ADD COLUMN custom_name TEXT")
        if "custom_category" not in observation_columns:
            conn.execute("ALTER TABLE observations ADD COLUMN custom_category TEXT")
        if "custom_owner" not in observation_columns:
            conn.execute("ALTER TABLE observations ADD COLUMN custom_owner TEXT")

        interval_columns = {row["name"] for row in conn.execute("PRAGMA table_info(device_state_intervals)")}
        if "duration_seconds" not in interval_columns:
            conn.execute("ALTER TABLE device_state_intervals ADD COLUMN duration_seconds INTEGER")

        conn.execute(
            """
            UPDATE devices
            SET detected_name = COALESCE(detected_name, name)
            WHERE COALESCE(detected_name, '') = '' AND COALESCE(name, '') <> ''
            """
        )
        self._migrate_owner_aliases(conn)
        self._sync_profile_metadata(conn)
        self._seed_intervals_from_devices(conn)
        self._purge_ignored_ip_only_devices(conn)

    def _migrate_owner_aliases(self, conn: sqlite3.Connection) -> None:
        for old_owner, new_owner in OWNER_ALIASES.items():
            conn.execute(
                """
                UPDATE devices
                SET custom_owner = ?
                WHERE LOWER(TRIM(COALESCE(custom_owner, ''))) = ?
                """,
                (new_owner, old_owner),
            )
            conn.execute(
                """
                UPDATE observations
                SET custom_owner = ?
                WHERE LOWER(TRIM(COALESCE(custom_owner, ''))) = ?
                """,
                (new_owner, old_owner),
            )

    def _sync_profile_metadata(self, conn: sqlite3.Connection) -> None:
        for mac, profile in self.get_device_profiles().items():
            profile_name = str(profile.get("name") or "").strip()
            profile_category = normalize_device_category(profile.get("category"))
            profile_owner = normalize_owner_label(profile.get("owner"))
            conn.execute(
                """
                UPDATE devices
                SET
                    custom_name = ?,
                    custom_category = ?,
                    custom_owner = ?,
                    name = COALESCE(?, detected_name, name)
                WHERE mac = ? OR device_key = ?
                """,
                (
                    profile_name or None,
                    profile_category or None,
                    profile_owner or None,
                    profile_name or None,
                    mac,
                    mac,
                ),
            )
            conn.execute(
                """
                UPDATE observations
                SET
                    custom_name = ?,
                    custom_category = ?,
                    custom_owner = ?,
                    name = COALESCE(?, detected_name, name)
                WHERE mac = ? OR device_key = ?
                """,
                (
                    profile_name or None,
                    profile_category or None,
                    profile_owner or None,
                    profile_name or None,
                    mac,
                    mac,
                ),
            )

    def record_scan(self, result: ScanResult) -> None:
        observations = list(result.observations)
        with self._lock:
            with self._connect() as conn:
                persisted_observations: list[tuple[DeviceObservation, str]] = []
                for item in observations:
                    device_key = self._resolve_observation_device_key(conn, result.finished_at, item)
                    if self._should_ignore_observation(item, device_key):
                        continue
                    persisted_observations.append((item, device_key))

                active_keys = [device_key for _, device_key in persisted_observations]
                self._mark_missing_devices_offline(conn, result.finished_at, active_keys)
                for observation, device_key in persisted_observations:
                    device_key = self._upsert_device(
                        conn,
                        result.finished_at,
                        observation,
                        device_key=device_key,
                    )
                    self._transition_device_state(conn, device_key, "online", result.finished_at)
                    conn.execute(
                        """
                        INSERT INTO observations (
                            scan_finished_at, device_key, ip, mac, name, detected_name, custom_name, custom_category, custom_owner, is_online, method
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            result.finished_at,
                            device_key,
                            observation.ip,
                            observation.mac,
                            preferred_name_for(observation),
                            observation.detected_name,
                            observation.custom_name,
                            observation.custom_category,
                            observation.custom_owner,
                            1 if observation.is_online else 0,
                            observation.last_method,
                        ),
                    )

                conn.execute(
                    """
                    INSERT INTO scans (
                        started_at, finished_at, networks_json, errors_json, discovered_count, online_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.started_at,
                        result.finished_at,
                        json.dumps(result.networks),
                        json.dumps(result.errors),
                        len(persisted_observations),
                        sum(1 for item, _device_key in persisted_observations if item.is_online),
                    ),
                )

    def _should_ignore_observation(self, observation: DeviceObservation, device_key: str) -> bool:
        if observation.mac:
            return False
        direct_key = device_key_for(observation)
        return str(device_key or "") == str(direct_key or "")

    def _purge_ignored_ip_only_devices(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT device_key
            FROM devices
            WHERE COALESCE(mac, '') = ''
              AND device_key LIKE 'ip:%'
            """
        ).fetchall()
        device_keys = [str(row["device_key"]) for row in rows if str(row["device_key"] or "").strip()]
        if not device_keys:
            return

        placeholders = ", ".join("?" for _ in device_keys)
        conn.execute(
            f"DELETE FROM device_state_intervals WHERE device_key IN ({placeholders})",
            device_keys,
        )
        conn.execute(
            f"DELETE FROM observations WHERE device_key IN ({placeholders})",
            device_keys,
        )
        conn.execute(
            f"DELETE FROM devices WHERE device_key IN ({placeholders})",
            device_keys,
        )
        self._recalculate_scan_counts(conn)

    def _recalculate_scan_counts(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE scans
            SET
                discovered_count = COALESCE((
                    SELECT COUNT(*)
                    FROM observations
                    WHERE observations.scan_finished_at = scans.finished_at
                ), 0),
                online_count = COALESCE((
                    SELECT SUM(CASE WHEN observations.is_online THEN 1 ELSE 0 END)
                    FROM observations
                    WHERE observations.scan_finished_at = scans.finished_at
                ), 0)
            """
        )

    def _mark_missing_devices_offline(
        self,
        conn: sqlite3.Connection,
        finished_at: str,
        active_keys: list[str],
    ) -> None:
        keys_to_offline = self._find_devices_to_offline(conn, active_keys)
        for device_key in keys_to_offline:
            self._transition_device_state(conn, device_key, "offline", finished_at)

        if not keys_to_offline:
            return

        placeholders = ", ".join("?" for _ in keys_to_offline)
        conn.execute(
            f"""
            UPDATE devices
            SET
                is_online = 0,
                online_since = NULL,
                last_offline_at = ?
            WHERE device_key IN ({placeholders})
            """,
            (finished_at, *keys_to_offline),
        )

    def _find_devices_to_offline(
        self,
        conn: sqlite3.Connection,
        active_keys: list[str],
    ) -> list[str]:
        if active_keys:
            placeholders = ", ".join("?" for _ in active_keys)
            rows = conn.execute(
                f"""
                SELECT device_key
                FROM devices
                WHERE is_online = 1
                  AND device_key NOT IN ({placeholders})
                """,
                active_keys,
            ).fetchall()
            return [row["device_key"] for row in rows]

        rows = conn.execute(
            """
            SELECT device_key
            FROM devices
            WHERE is_online = 1
            """
        ).fetchall()
        return [row["device_key"] for row in rows]

    def _upsert_device(
        self,
        conn: sqlite3.Connection,
        finished_at: str,
        observation: DeviceObservation,
        *,
        device_key: str | None = None,
    ) -> str:
        key = str(device_key or device_key_for(observation))
        row = conn.execute(
            """
            SELECT
                first_seen,
                ip,
                mac,
                name,
                detected_name,
                custom_name,
                custom_category,
                custom_owner,
                is_online,
                online_since
            FROM devices
            WHERE device_key = ?
            """,
            (key,),
        ).fetchone()
        first_seen = row["first_seen"] if row else finished_at
        was_online = bool(row["is_online"]) if row else False
        online_since = row["online_since"] if row and was_online and row["online_since"] else finished_at
        custom_name = observation.custom_name if observation.custom_name is not None else (row["custom_name"] if row else None)
        custom_category = (
            observation.custom_category
            if observation.custom_category is not None
            else (row["custom_category"] if row else None)
        )
        custom_owner = observation.custom_owner if observation.custom_owner is not None else (row["custom_owner"] if row else None)
        detected_name = observation.detected_name or (row["detected_name"] if row else None)
        mac_value = observation.mac or (row["mac"] if row else None)
        if not mac_value and not key.startswith("ip:"):
            mac_value = normalize_mac(key)
        display_name = custom_name or detected_name or (row["name"] if row else None)
        conn.execute(
            """
            INSERT INTO devices (
                device_key, ip, mac, name, detected_name, custom_name, custom_category, custom_owner, first_seen, last_seen,
                is_online, online_since, last_offline_at, last_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_key) DO UPDATE SET
                ip = excluded.ip,
                mac = excluded.mac,
                name = excluded.name,
                detected_name = excluded.detected_name,
                custom_name = excluded.custom_name,
                custom_category = excluded.custom_category,
                custom_owner = excluded.custom_owner,
                last_seen = excluded.last_seen,
                is_online = excluded.is_online,
                online_since = excluded.online_since,
                last_offline_at = excluded.last_offline_at,
                last_method = excluded.last_method
            """,
            (
                key,
                observation.ip or (row["ip"] if row else None),
                mac_value,
                display_name,
                detected_name,
                custom_name,
                custom_category,
                custom_owner,
                first_seen,
                finished_at,
                1 if observation.is_online else 0,
                online_since,
                None,
                observation.last_method,
            ),
        )
        return key

    def _resolve_observation_device_key(
        self,
        conn: sqlite3.Connection,
        finished_at: str,
        observation: DeviceObservation,
    ) -> str:
        direct_key = device_key_for(observation)
        if observation.mac:
            return direct_key

        ip = str(observation.ip or "").strip()
        if not ip:
            return direct_key

        finished_dt = parse_iso_utc(finished_at) or datetime.now(timezone.utc)
        recent_cutoff = finished_dt - timedelta(hours=24)
        candidate = conn.execute(
            """
            SELECT device_key, last_seen, is_online
            FROM devices
            WHERE ip = ?
              AND mac IS NOT NULL
            ORDER BY is_online DESC, last_seen DESC
            LIMIT 1
            """,
            (ip,),
        ).fetchone()
        if not candidate:
            return direct_key

        last_seen_dt = parse_iso_utc(candidate["last_seen"])
        if bool(candidate["is_online"]) or (last_seen_dt and last_seen_dt >= recent_cutoff):
            return str(candidate["device_key"])
        return direct_key

    def _visible_device_rows(
        self,
        rows: list[sqlite3.Row],
        *,
        now: datetime | None = None,
    ) -> list[sqlite3.Row]:
        current_time = now or datetime.now(timezone.utc)
        preferred_by_ip: dict[str, sqlite3.Row] = {}

        for row in rows:
            ip = str(row["ip"] or "").strip()
            if not ip:
                continue
            existing = preferred_by_ip.get(ip)
            if existing is None or self._device_row_rank(row) > self._device_row_rank(existing):
                preferred_by_ip[ip] = row

        visible_rows: list[sqlite3.Row] = []
        for row in rows:
            preferred = preferred_by_ip.get(str(row["ip"] or "").strip())
            if self._should_hide_ip_alias_row(row, preferred, now=current_time):
                continue
            visible_rows.append(row)
        return visible_rows

    def _device_row_rank(self, row: sqlite3.Row) -> tuple[int, int, int, float]:
        last_seen = parse_iso_utc(row["last_seen"])
        has_identity = bool(row["custom_name"] or row["custom_category"] or row["custom_owner"] or row["detected_name"] or row["name"])
        return (
            1 if row["mac"] else 0,
            1 if has_identity else 0,
            1 if bool(row["is_online"]) else 0,
            float(last_seen.timestamp()) if last_seen else 0.0,
        )

    def _should_hide_ip_alias_row(
        self,
        row: sqlite3.Row,
        preferred: sqlite3.Row | None,
        *,
        now: datetime,
    ) -> bool:
        ip = str(row["ip"] or "").strip()
        if not ip or row["mac"] or str(row["device_key"]) != f"ip:{ip}":
            return False
        if not preferred or str(preferred["device_key"]) == str(row["device_key"]) or not preferred["mac"]:
            return False

        alias_seen = parse_iso_utc(row["last_seen"])
        preferred_seen = parse_iso_utc(preferred["last_seen"])
        if bool(preferred["is_online"]):
            return bool(alias_seen and alias_seen >= (now - timedelta(hours=24)))
        if not alias_seen or not preferred_seen:
            return False
        if alias_seen < (now - timedelta(hours=24)):
            return False
        return preferred_seen >= alias_seen

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            timeline_now = datetime.now(timezone.utc).replace(microsecond=0)
            timeline_context = self._build_timeline_context(conn, now=timeline_now, hours=24)
            rows = conn.execute(
                """
                SELECT
                    device_key,
                    ip,
                    mac,
                    name,
                    detected_name,
                    custom_name,
                    custom_category,
                    custom_owner,
                    first_seen,
                    last_seen,
                    is_online,
                    online_since,
                    last_offline_at,
                    last_method
                FROM devices
                """
            ).fetchall()
            rows = self._visible_device_rows(list(rows), now=timeline_now)
            rows.sort(
                key=lambda row: (
                    0 if bool(row["is_online"]) else 1,
                    -(parse_iso_utc(row["last_seen"]) or datetime.fromtimestamp(0, tz=timezone.utc)).timestamp(),
                    str(row["name"] or row["mac"] or row["ip"] or "").lower(),
                )
            )
            devices = []
            for row in rows:
                history = self._history_summary_for_device(conn, row["device_key"])
                timeline_24h = self._timeline_for_device(
                    conn,
                    row["device_key"],
                    device_category=row["custom_category"],
                    device_mac=row["mac"],
                    hours=24,
                    now=timeline_now,
                    context=timeline_context,
                )
                devices.append(
                    {
                        "device_key": row["device_key"],
                        "ip": row["ip"],
                        "mac": row["mac"],
                        "name": row["name"],
                        "detected_name": row["detected_name"],
                        "custom_name": row["custom_name"],
                        "category": row["custom_category"],
                        "owner": row["custom_owner"],
                        "first_seen": row["first_seen"],
                        "last_seen": row["last_seen"],
                        "is_online": bool(row["is_online"]),
                        "online_since": row["online_since"],
                        "last_offline_at": row["last_offline_at"],
                        "online_for_seconds": online_duration_seconds(row["online_since"], bool(row["is_online"])),
                        "last_method": row["last_method"],
                        "history": history,
                        "timeline_24h": timeline_24h,
                    }
                )
            return devices

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    device_key,
                    ip,
                    mac,
                    name,
                    detected_name,
                    custom_name,
                    custom_category,
                    custom_owner,
                    last_seen,
                    is_online
                FROM devices
                """
            ).fetchall()
            visible_rows = self._visible_device_rows(list(rows))
            last_scan = conn.execute(
                "SELECT finished_at FROM scans ORDER BY id DESC LIMIT 1"
            ).fetchone()
            scan_interval_seconds = self._estimated_scan_interval_seconds(conn)

        return {
            "total_devices_seen": len(visible_rows),
            "currently_online": sum(1 for row in visible_rows if bool(row["is_online"])),
            "last_scan_at": last_scan["finished_at"] if last_scan else None,
            "scan_interval_seconds": scan_interval_seconds,
        }

    def list_device_history(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            timeline_now = datetime.now(timezone.utc).replace(microsecond=0)
            timeline_context = self._build_timeline_context(conn, now=timeline_now, hours=24)
            rows = self._history_device_rows(conn, now=timeline_now)
            return [
                {
                    "device_key": row["device_key"],
                    "name": row["name"],
                    "custom_name": row["custom_name"],
                    "category": row["custom_category"],
                    "owner": row["custom_owner"],
                    "detected_name": row["detected_name"],
                    "mac": row["mac"],
                    "ip": row["ip"],
                    "is_online": bool(row["is_online"]),
                    "online_since": row["online_since"],
                    "last_seen": row["last_seen"],
                    "history": self._history_summary_for_device(conn, row["device_key"]),
                    "timeline_24h": self._timeline_for_device(
                        conn,
                        row["device_key"],
                        device_category=row["custom_category"],
                        device_mac=row["mac"],
                        hours=24,
                        now=timeline_now,
                        context=timeline_context,
                    ),
                }
                for row in rows
            ]

    def _history_device_rows(
        self,
        conn: sqlite3.Connection,
        *,
        now: datetime,
    ) -> list[sqlite3.Row]:
        rows = conn.execute(
            """
            SELECT
                device_key,
                first_seen,
                last_seen,
                is_online,
                online_since,
                ip,
                mac,
                name,
                detected_name,
                custom_name,
                custom_category,
                custom_owner
            FROM devices
            """
        ).fetchall()
        visible_rows = self._visible_device_rows(list(rows), now=now)
        visible_rows.sort(
            key=lambda row: str(
                row["name"] or row["detected_name"] or row["custom_name"] or row["mac"] or row["ip"] or ""
            ).lower()
        )
        return visible_rows

    def get_device_profiles(self) -> dict[str, dict[str, str | None]]:
        if not self.names_path:
            return {}
        try:
            raw = json.loads(self.names_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

        if isinstance(raw, dict) and isinstance(raw.get("devices"), dict):
            raw = raw["devices"]
        if not isinstance(raw, dict):
            return {}

        profiles: dict[str, dict[str, str | None]] = {}
        for key, value in raw.items():
            mac = normalize_mac(str(key))
            if not mac:
                continue
            name = ""
            category = None
            owner = ""
            if isinstance(value, dict):
                name = str(value.get("name") or "").strip()
                category = normalize_device_category(value.get("category"))
                owner = normalize_owner_label(value.get("owner"))
            else:
                name = str(value or "").strip()
            if name or category or owner:
                profiles[mac] = {
                    "name": name or None,
                    "category": category or None,
                    "owner": owner or None,
                }
        return profiles

    def get_custom_names(self) -> dict[str, str]:
        profiles = self.get_device_profiles()
        return {
            mac: str(profile.get("name") or "")
            for mac, profile in profiles.items()
            if str(profile.get("name") or "").strip()
        }

    def save_device_profile(
        self,
        *,
        mac: str,
        name: str | None = None,
        category: str | None = None,
        owner: str | None = None,
    ) -> dict[str, dict[str, str | None]]:
        if not self.names_path:
            raise RuntimeError("Custom device names path is not configured.")

        normalized_mac = normalize_mac(mac)
        if not normalized_mac:
            raise ValueError("Invalid MAC address.")

        next_name = str(name or "").strip()
        next_category = normalize_device_category(category)
        next_owner = normalize_owner_label(owner)

        with self._lock:
            profiles = self.get_device_profiles()
            if next_name or next_category or next_owner:
                profiles[normalized_mac] = {
                    "name": next_name or None,
                    "category": next_category or None,
                    "owner": next_owner or None,
                }
            else:
                profiles.pop(normalized_mac, None)

            payload: dict[str, Any] = {}
            for key in sorted(profiles):
                profile = profiles[key]
                profile_name = str(profile.get("name") or "").strip()
                profile_category = normalize_device_category(profile.get("category"))
                profile_owner = str(profile.get("owner") or "").strip()
                if profile_category or profile_owner:
                    next_payload: dict[str, str] = {}
                    if profile_name:
                        next_payload["name"] = profile_name
                    if profile_category:
                        next_payload["category"] = profile_category
                    if profile_owner:
                        next_payload["owner"] = profile_owner
                    payload[key] = next_payload
                elif profile_name:
                    payload[key] = profile_name
            self.names_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE devices
                    SET
                        custom_name = ?,
                        custom_category = ?,
                        custom_owner = ?,
                        name = COALESCE(?, detected_name)
                    WHERE mac = ?
                    """,
                    (
                        next_name or None,
                        next_category or None,
                        next_owner or None,
                        next_name or None,
                        normalized_mac,
                    ),
                )
                conn.execute(
                    """
                    UPDATE observations
                    SET
                        custom_name = ?,
                        custom_category = ?,
                        custom_owner = ?,
                        name = COALESCE(?, detected_name, name)
                    WHERE mac = ? OR device_key = ?
                    """,
                    (
                        next_name or None,
                        next_category or None,
                        next_owner or None,
                        next_name or None,
                        normalized_mac,
                        normalized_mac,
                    ),
                )

        return profiles

    def save_custom_name(self, mac: str, name: str | None) -> dict[str, str]:
        profiles = self.save_device_profile(mac=mac, name=name)
        return {
            key: str(profile.get("name") or "")
            for key, profile in profiles.items()
            if str(profile.get("name") or "").strip()
        }

    def _seed_intervals_from_devices(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT
                device_key,
                is_online,
                online_since,
                last_offline_at,
                last_seen,
                first_seen
            FROM devices
            """
        ).fetchall()
        for row in rows:
            existing = conn.execute(
                """
                SELECT 1
                FROM device_state_intervals
                WHERE device_key = ?
                LIMIT 1
                """,
                (row["device_key"],),
            ).fetchone()
            if existing:
                continue
            state = "online" if bool(row["is_online"]) else "offline"
            started_at = (
                row["online_since"]
                if state == "online"
                else row["last_offline_at"]
            ) or row["last_seen"] or row["first_seen"] or utc_now_iso()
            conn.execute(
                """
                INSERT INTO device_state_intervals (
                    device_key, state, started_at, ended_at, duration_seconds
                ) VALUES (?, ?, ?, NULL, NULL)
                """,
                (row["device_key"], state, started_at),
            )

    def _transition_device_state(
        self,
        conn: sqlite3.Connection,
        device_key: str,
        next_state: str,
        at_iso: str,
    ) -> None:
        current = conn.execute(
            """
            SELECT id, state, started_at
            FROM device_state_intervals
            WHERE device_key = ? AND ended_at IS NULL
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (device_key,),
        ).fetchone()
        if current and current["state"] == next_state:
            return

        if current:
            duration = overlap_seconds(current["started_at"], at_iso, current["started_at"], at_iso)
            conn.execute(
                """
                UPDATE device_state_intervals
                SET ended_at = ?, duration_seconds = ?
                WHERE id = ?
                """,
                (at_iso, duration, current["id"]),
            )

        conn.execute(
            """
            INSERT INTO device_state_intervals (
                device_key, state, started_at, ended_at, duration_seconds
            ) VALUES (?, ?, ?, NULL, NULL)
            """,
            (device_key, next_state, at_iso),
        )

    def _history_summary_for_device(
        self,
        conn: sqlite3.Connection,
        device_key: str,
        *,
        windows: dict[str, dict[str, datetime]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        windows = windows or history_windows()
        earliest_start = min(window["start"] for window in windows.values())
        rows = conn.execute(
            """
            SELECT state, started_at, ended_at
            FROM device_state_intervals
            WHERE device_key = ?
              AND COALESCE(ended_at, ?) > ?
            ORDER BY started_at ASC
            """,
            (device_key, utc_now_iso(), earliest_start.isoformat()),
        ).fetchall()

        summary: dict[str, dict[str, Any]] = {}
        for key, window in windows.items():
            online_seconds = 0
            offline_seconds = 0
            online_sessions = 0
            offline_sessions = 0
            for row in rows:
                seconds = overlap_seconds(
                    row["started_at"],
                    row["ended_at"],
                    window["start"].isoformat(),
                    window["end"].isoformat(),
                )
                if seconds <= 0:
                    continue
                if row["state"] == "online":
                    online_seconds += seconds
                    online_sessions += 1
                else:
                    offline_seconds += seconds
                    offline_sessions += 1
            summary[key] = {
                "window_started_at": window["start"].isoformat(),
                "window_ended_at": window["end"].isoformat(),
                "online_seconds": online_seconds,
                "offline_seconds": offline_seconds,
                "online_sessions": online_sessions,
                "offline_sessions": offline_sessions,
            }
        return summary

    def _timeline_for_device(
        self,
        conn: sqlite3.Connection,
        device_key: str,
        *,
        device_category: str | None = None,
        device_mac: str | None = None,
        hours: int = 24,
        now: datetime | None = None,
        context: dict[str, Any] | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> dict[str, Any]:
        if window_start and window_end:
            safe_window_start = window_start.astimezone(timezone.utc).replace(microsecond=0)
            safe_window_end = window_end.astimezone(timezone.utc).replace(microsecond=0)
        else:
            safe_window_end = (now or datetime.now(timezone.utc)).replace(microsecond=0)
            safe_window_start = safe_window_end - timedelta(hours=max(1, int(hours)))

        effective_hours = max(
            1,
            int(round(max(1, (safe_window_end - safe_window_start).total_seconds()) / 3600)),
        )
        context_data = context or self._build_timeline_context(
            conn,
            window_start=safe_window_start,
            window_end=safe_window_end,
        )
        scan_interval_seconds = int(context_data.get("scan_interval_seconds") or 30)
        transition_counts = context_data.get("transition_counts") or {}
        scan_states = context_data.get("scan_states") or {}
        rows = conn.execute(
            """
            SELECT id, state, started_at, ended_at
            FROM device_state_intervals
            WHERE device_key = ?
              AND COALESCE(ended_at, ?) > ?
              AND started_at < ?
            ORDER BY started_at ASC, id ASC
            """,
            (
                device_key,
                safe_window_end.isoformat(),
                safe_window_start.isoformat(),
                safe_window_end.isoformat(),
            ),
        ).fetchall()

        segments: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        online_seconds = 0
        offline_seconds = 0
        connected_count = 0
        disconnected_count = 0
        raw_segments: list[dict[str, Any]] = []

        for row in rows:
            state = str(row["state"] or "offline")
            row_start = parse_iso_utc(row["started_at"])
            row_end = parse_iso_utc(row["ended_at"]) or safe_window_end
            if not row_start:
                continue

            segment_start = max(row_start, safe_window_start)
            segment_end = min(row_end, safe_window_end)
            if segment_end <= segment_start:
                continue

            duration_seconds = int((segment_end - segment_start).total_seconds())
            segments.append(
                {
                    "state": state,
                    "started_at": segment_start.isoformat(),
                    "ended_at": segment_end.isoformat(),
                    "duration_seconds": duration_seconds,
                }
            )
            raw_segments.append(
                {
                    "id": row["id"],
                    "state": state,
                    "started_at": row_start.isoformat(),
                    "ended_at": row_end.isoformat(),
                    "is_closed": bool(row["ended_at"]),
                    "duration_seconds": max(0, int((row_end - row_start).total_seconds())),
                }
            )

            if state == "online":
                online_seconds += duration_seconds
            else:
                offline_seconds += duration_seconds

        for index, segment in enumerate(raw_segments):
            event_at = parse_iso_utc(segment["started_at"])
            if not event_at or not (safe_window_start <= event_at <= safe_window_end):
                continue

            event_type = "connected" if segment["state"] == "online" else "disconnected"
            if event_type == "connected":
                connected_count += 1
            else:
                disconnected_count += 1

            previous_segment = raw_segments[index - 1] if index > 0 else None
            next_segment = raw_segments[index + 1] if index + 1 < len(raw_segments) else None
            simultaneous_count = int(transition_counts.get((segment["started_at"], segment["state"]), 1))
            scan_state = scan_states.get(segment["started_at"], {})
            reason = infer_transition_reason(
                event_type=event_type,
                device_category=device_category,
                device_mac=device_mac,
                segment=segment,
                previous_segment=previous_segment,
                next_segment=next_segment,
                simultaneous_count=simultaneous_count,
                scan_interval_seconds=scan_interval_seconds,
                scan_online_before=int(scan_state.get("previous_online_count") or 0),
                scan_online_after=int(scan_state.get("online_count") or 0),
            )
            events.append(
                {
                    "type": event_type,
                    "state": segment["state"],
                    "at": segment["started_at"],
                    "ended_at": segment["ended_at"] if segment.get("is_closed") else None,
                    "is_closed": bool(segment.get("is_closed")),
                    "duration_seconds": int(segment["duration_seconds"]),
                    "simultaneous_change_count": simultaneous_count,
                    "reason_code": reason["code"],
                    "reason_label": reason["label"],
                    "reason_detail": reason["detail"],
                    "confidence": reason["confidence"],
                }
            )

        first_known_started_at = parse_iso_utc(raw_segments[0]["started_at"]) if raw_segments else None
        effective_coverage_seconds = max(
            0,
            int((safe_window_end - max(safe_window_start, first_known_started_at or safe_window_start)).total_seconds()),
        )
        insight = summarize_timeline_insight(
            events=events,
            is_online=bool(raw_segments[-1]["state"] == "online") if raw_segments else False,
            online_seconds=online_seconds,
            offline_seconds=offline_seconds,
            coverage_seconds=effective_coverage_seconds,
        )

        return {
            "window_started_at": safe_window_start.isoformat(),
            "window_ended_at": safe_window_end.isoformat(),
            "window_hours": effective_hours,
            "online_seconds": online_seconds,
            "offline_seconds": offline_seconds,
            "connected_count": connected_count,
            "disconnected_count": disconnected_count,
            "segments": segments,
            "events": events,
            "insight": insight,
        }

    def get_device_history_snapshot(
        self,
        device_key: str,
        *,
        day: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    device_key,
                    ip,
                    mac,
                    name,
                    detected_name,
                    custom_name,
                    custom_category,
                    custom_owner,
                    first_seen,
                    last_seen,
                    is_online,
                    online_since,
                    last_offline_at,
                    last_method
                FROM devices
                WHERE device_key = ?
                LIMIT 1
                """,
                (device_key,),
            ).fetchone()
            if not row:
                return None

            selected_day = parse_local_day(day) or local_day_bounds()["day"]
            windows = history_windows(day=selected_day)
            day_window = windows["day"]
            timeline_context = self._build_timeline_context(
                conn,
                window_start=day_window["start"],
                window_end=day_window["end"],
            )
            history = self._history_summary_for_device(conn, device_key, windows=windows)
            timeline = self._timeline_for_device(
                conn,
                device_key,
                device_category=row["custom_category"],
                device_mac=row["mac"],
                window_start=day_window["start"],
                window_end=day_window["end"],
                context=timeline_context,
            )

            first_seen_dt = parse_iso_utc(row["first_seen"]) or datetime.now(timezone.utc)
            last_seen_dt = parse_iso_utc(row["last_seen"]) or first_seen_dt
            available_max_local_day = max(
                local_day_from_datetime(last_seen_dt),
                local_day_bounds()["day"],
            )

            return {
                "device_key": row["device_key"],
                "ip": row["ip"],
                "mac": row["mac"],
                "name": row["name"],
                "detected_name": row["detected_name"],
                "custom_name": row["custom_name"],
                "category": row["custom_category"],
                "owner": row["custom_owner"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "is_online": bool(row["is_online"]),
                "online_since": row["online_since"],
                "last_offline_at": row["last_offline_at"],
                "online_for_seconds": online_duration_seconds(row["online_since"], bool(row["is_online"])),
                "last_method": row["last_method"],
                "history": history,
                "timeline_24h": timeline,
                "selected_day": selected_day.isoformat(),
                "selected_day_label": format_local_day_label(selected_day),
                "available_day_min": local_day_from_datetime(first_seen_dt).isoformat(),
                "available_day_max": available_max_local_day.isoformat(),
            }

    def get_global_history_snapshot(
        self,
        *,
        day: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            timeline_now = datetime.now(timezone.utc).replace(microsecond=0)
            rows = self._history_device_rows(conn, now=timeline_now)
            if not rows:
                return None

            selected_day = parse_local_day(day) or local_day_bounds()["day"]
            windows = history_windows(day=selected_day)
            day_window = windows["day"]
            timeline_context = self._build_timeline_context(
                conn,
                window_start=day_window["start"],
                window_end=day_window["end"],
            )

            history = self._history_summary_for_all_devices(conn, rows, windows=windows)
            timeline = self._timeline_for_all_devices(
                conn,
                rows,
                window_start=day_window["start"],
                window_end=day_window["end"],
                context=timeline_context,
            )
            presence = self._presence_timeline_for_owners(
                conn,
                rows,
                window_start=day_window["start"],
                window_end=day_window["end"],
                context=timeline_context,
            )

            first_seen_candidates = [
                parse_iso_utc(row["first_seen"])
                for row in rows
                if parse_iso_utc(row["first_seen"])
            ]
            last_seen_candidates = [
                parse_iso_utc(row["last_seen"])
                for row in rows
                if parse_iso_utc(row["last_seen"])
            ]
            first_seen_dt = min(first_seen_candidates) if first_seen_candidates else timeline_now
            last_seen_dt = max(last_seen_candidates) if last_seen_candidates else first_seen_dt
            available_max_local_day = max(
                local_day_from_datetime(last_seen_dt),
                local_day_bounds()["day"],
            )

            return {
                "scope": "all",
                "device_key": "__all__",
                "name": "Wszystkie urządzenia",
                "selected_day": selected_day.isoformat(),
                "selected_day_label": format_local_day_label(selected_day),
                "available_day_min": local_day_from_datetime(first_seen_dt).isoformat(),
                "available_day_max": available_max_local_day.isoformat(),
                "history": history,
                "timeline_24h": timeline,
                "presence": presence,
            }

    def _history_summary_for_all_devices(
        self,
        conn: sqlite3.Connection,
        rows: list[sqlite3.Row],
        *,
        windows: dict[str, dict[str, datetime]],
    ) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        for key, window in windows.items():
            context = self._build_timeline_context(
                conn,
                window_start=window["start"],
                window_end=window["end"],
            )
            event_count = 0
            connected_count = 0
            disconnected_count = 0
            touched_devices: set[str] = set()

            for row in rows:
                timeline = self._timeline_for_device(
                    conn,
                    str(row["device_key"]),
                    device_category=row["custom_category"],
                    device_mac=row["mac"],
                    window_start=window["start"],
                    window_end=window["end"],
                    context=context,
                )
                current_events = list(timeline.get("events") or [])
                if current_events:
                    touched_devices.add(str(row["device_key"]))
                event_count += len(current_events)
                connected_count += int(timeline.get("connected_count") or 0)
                disconnected_count += int(timeline.get("disconnected_count") or 0)

            summary[key] = {
                "window_started_at": window["start"].isoformat(),
                "window_ended_at": window["end"].isoformat(),
                "event_count": event_count,
                "connected_count": connected_count,
                "disconnected_count": disconnected_count,
                "device_count": len(touched_devices),
            }
        return summary

    def _timeline_for_all_devices(
        self,
        conn: sqlite3.Connection,
        rows: list[sqlite3.Row],
        *,
        window_start: datetime,
        window_end: datetime,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_window_start = window_start.astimezone(timezone.utc).replace(microsecond=0)
        safe_window_end = window_end.astimezone(timezone.utc).replace(microsecond=0)
        context_data = context or self._build_timeline_context(
            conn,
            window_start=safe_window_start,
            window_end=safe_window_end,
        )

        merged_events: list[dict[str, Any]] = []
        timeline_segments: list[dict[str, Any]] = []
        count_changes: list[tuple[datetime, int]] = []
        touched_devices: set[str] = set()
        online_devices: set[str] = set()

        for row in rows:
            timeline = self._timeline_for_device(
                conn,
                str(row["device_key"]),
                device_category=row["custom_category"],
                device_mac=row["mac"],
                window_start=safe_window_start,
                window_end=safe_window_end,
                context=context_data,
            )

            for segment in timeline.get("segments") or []:
                if str(segment.get("state")) != "online":
                    continue
                segment_start = parse_iso_utc(segment.get("started_at"))
                segment_end = parse_iso_utc(segment.get("ended_at"))
                if not segment_start or not segment_end or segment_end <= segment_start:
                    continue
                count_changes.append((segment_start, 1))
                count_changes.append((segment_end, -1))
                online_devices.add(str(row["device_key"]))

            device_name = str(
                row["name"] or row["custom_name"] or row["detected_name"] or row["ip"] or row["mac"] or "Nieznane urządzenie"
            )
            for event in timeline.get("events") or []:
                touched_devices.add(str(row["device_key"]))
                merged_events.append(
                    {
                        **event,
                        "device_key": str(row["device_key"]),
                        "device_name": device_name,
                        "device_ip": row["ip"],
                        "device_mac": row["mac"],
                        "device_category": row["custom_category"],
                        "device_owner": row["custom_owner"],
                    }
                )

        count_changes.sort(key=lambda item: (item[0], 0 if item[1] < 0 else 1))
        active_count = 0
        last_point = safe_window_start
        weighted_online_seconds = 0
        max_online_count = 0

        for point, delta in count_changes:
            clamped_point = min(max(point, safe_window_start), safe_window_end)
            if clamped_point > last_point and active_count > 0:
                duration_seconds = int((clamped_point - last_point).total_seconds())
                timeline_segments.append(
                    {
                        "started_at": last_point.isoformat(),
                        "ended_at": clamped_point.isoformat(),
                        "duration_seconds": duration_seconds,
                        "online_count": active_count,
                    }
                )
                weighted_online_seconds += duration_seconds * active_count
                max_online_count = max(max_online_count, active_count)
            active_count += delta
            last_point = clamped_point

        if safe_window_end > last_point and active_count > 0:
            duration_seconds = int((safe_window_end - last_point).total_seconds())
            timeline_segments.append(
                {
                    "started_at": last_point.isoformat(),
                    "ended_at": safe_window_end.isoformat(),
                    "duration_seconds": duration_seconds,
                    "online_count": active_count,
                }
            )
            weighted_online_seconds += duration_seconds * active_count
            max_online_count = max(max_online_count, active_count)

        merged_events.sort(key=lambda event: str(event.get("at") or ""))
        coverage_seconds = max(0, int((safe_window_end - safe_window_start).total_seconds()))
        average_online_count = (
            round(weighted_online_seconds / max(1, coverage_seconds), 2)
            if coverage_seconds > 0
            else 0.0
        )
        insight = summarize_all_devices_timeline_insight(
            events=merged_events,
            coverage_seconds=coverage_seconds,
            device_count=len(rows),
            max_online_count=max_online_count,
        )

        return {
            "window_started_at": safe_window_start.isoformat(),
            "window_ended_at": safe_window_end.isoformat(),
            "window_hours": max(1, int(round(max(1, coverage_seconds) / 3600))),
            "segments": timeline_segments,
            "events": merged_events,
            "event_count": len(merged_events),
            "connected_count": sum(1 for event in merged_events if event.get("type") == "connected"),
            "disconnected_count": sum(1 for event in merged_events if event.get("type") == "disconnected"),
            "devices_with_events_count": len(touched_devices),
            "online_devices_count": len(online_devices),
            "max_online_count": max_online_count,
            "average_online_count": average_online_count,
            "insight": insight,
        }

    def _presence_timeline_for_owners(
        self,
        conn: sqlite3.Connection,
        rows: list[sqlite3.Row],
        *,
        window_start: datetime,
        window_end: datetime,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_window_start = window_start.astimezone(timezone.utc).replace(microsecond=0)
        safe_window_end = window_end.astimezone(timezone.utc).replace(microsecond=0)
        context_data = context or self._build_timeline_context(
            conn,
            window_start=safe_window_start,
            window_end=safe_window_end,
        )

        owner_meta: dict[str, dict[str, Any]] = {}
        owner_changes: dict[str, list[tuple[datetime, int]]] = {}

        for row in rows:
            owner = str(row["custom_owner"] or "").strip()
            if not owner:
                continue

            device_name = str(
                row["name"] or row["custom_name"] or row["detected_name"] or row["ip"] or row["mac"] or "Nieznane urządzenie"
            )
            meta = owner_meta.setdefault(
                owner,
                {
                    "owner": owner,
                    "device_names": set(),
                    "device_keys": set(),
                },
            )
            meta["device_names"].add(device_name)
            meta["device_keys"].add(str(row["device_key"]))

            timeline = self._timeline_for_device(
                conn,
                str(row["device_key"]),
                device_category=row["custom_category"],
                device_mac=row["mac"],
                window_start=safe_window_start,
                window_end=safe_window_end,
                context=context_data,
            )
            for segment in timeline.get("segments") or []:
                if str(segment.get("state") or "") != "online":
                    continue
                segment_start = parse_iso_utc(segment.get("started_at"))
                segment_end = parse_iso_utc(segment.get("ended_at"))
                if not segment_start or not segment_end or segment_end <= segment_start:
                    continue
                changes = owner_changes.setdefault(owner, [])
                changes.append((segment_start, 1))
                changes.append((segment_end, -1))

        owners: list[dict[str, Any]] = []
        for owner, meta in sorted(owner_meta.items(), key=lambda item: item[0].lower()):
            changes = sorted(owner_changes.get(owner, []), key=lambda item: (item[0], 0 if item[1] < 0 else 1))
            active_count = 0
            last_point = safe_window_start
            online_seconds = 0
            max_active_devices = 0
            segments: list[dict[str, Any]] = []

            for point, delta in changes:
                clamped_point = min(max(point, safe_window_start), safe_window_end)
                if clamped_point > last_point and active_count > 0:
                    duration_seconds = int((clamped_point - last_point).total_seconds())
                    segments.append(
                        {
                            "started_at": last_point.isoformat(),
                            "ended_at": clamped_point.isoformat(),
                            "duration_seconds": duration_seconds,
                            "active_device_count": active_count,
                        }
                    )
                    online_seconds += duration_seconds
                    max_active_devices = max(max_active_devices, active_count)
                active_count += delta
                last_point = clamped_point

            if safe_window_end > last_point and active_count > 0:
                duration_seconds = int((safe_window_end - last_point).total_seconds())
                segments.append(
                    {
                        "started_at": last_point.isoformat(),
                        "ended_at": safe_window_end.isoformat(),
                        "duration_seconds": duration_seconds,
                        "active_device_count": active_count,
                    }
                )
                online_seconds += duration_seconds
                max_active_devices = max(max_active_devices, active_count)

            owners.append(
                {
                    "owner": owner,
                    "device_count": len(meta["device_keys"]),
                    "device_names": sorted(meta["device_names"]),
                    "online_seconds": online_seconds,
                    "max_active_devices": max_active_devices,
                    "segments": segments,
                }
            )

        return {
            "window_started_at": safe_window_start.isoformat(),
            "window_ended_at": safe_window_end.isoformat(),
            "owners": owners,
        }

    def _build_timeline_context(
        self,
        conn: sqlite3.Connection,
        *,
        now: datetime | None = None,
        hours: int = 24,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> dict[str, Any]:
        if window_start and window_end:
            safe_window_start = window_start.astimezone(timezone.utc).replace(microsecond=0)
            safe_window_end = window_end.astimezone(timezone.utc).replace(microsecond=0)
        else:
            safe_window_end = (now or datetime.now(timezone.utc)).replace(microsecond=0)
            safe_window_start = safe_window_end - timedelta(hours=max(1, int(hours)))
        transition_rows = conn.execute(
            """
            SELECT started_at, state, COUNT(*) AS transition_count
            FROM device_state_intervals
            WHERE started_at BETWEEN ? AND ?
            GROUP BY started_at, state
            """,
            (safe_window_start.isoformat(), safe_window_end.isoformat()),
        ).fetchall()
        transition_counts = {
            (row["started_at"], row["state"]): int(row["transition_count"] or 0)
            for row in transition_rows
        }
        scan_states = self._scan_states_for_window(
            conn,
            now=safe_window_end,
            hours=hours,
            window_start=safe_window_start,
            window_end=safe_window_end,
        )
        return {
            "scan_interval_seconds": self._estimated_scan_interval_seconds(conn),
            "transition_counts": transition_counts,
            "scan_states": scan_states,
        }

    def _estimated_scan_interval_seconds(self, conn: sqlite3.Connection) -> int:
        rows = conn.execute(
            """
            SELECT finished_at
            FROM scans
            ORDER BY finished_at DESC
            LIMIT 12
            """
        ).fetchall()
        finished_times = [parse_iso_utc(row["finished_at"]) for row in rows]
        deltas: list[int] = []
        for first, second in zip(finished_times, finished_times[1:]):
            if not first or not second:
                continue
            delta = int((first - second).total_seconds())
            if delta > 0:
                deltas.append(delta)
        if not deltas:
            return 30
        deltas.sort()
        return max(5, deltas[len(deltas) // 2])

    def _scan_states_for_window(
        self,
        conn: sqlite3.Connection,
        *,
        now: datetime | None = None,
        hours: int = 24,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> dict[str, dict[str, int]]:
        if window_start and window_end:
            safe_window_start = window_start.astimezone(timezone.utc).replace(microsecond=0)
            safe_window_end = window_end.astimezone(timezone.utc).replace(microsecond=0)
        else:
            safe_window_end = (now or datetime.now(timezone.utc)).replace(microsecond=0)
            safe_window_start = safe_window_end - timedelta(hours=max(1, int(hours)))
        previous_row = conn.execute(
            """
            SELECT finished_at, online_count
            FROM scans
            WHERE finished_at < ?
            ORDER BY finished_at DESC
            LIMIT 1
            """,
            (safe_window_start.isoformat(),),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT finished_at, online_count
            FROM scans
            WHERE finished_at BETWEEN ? AND ?
            ORDER BY finished_at ASC
            """,
            (safe_window_start.isoformat(), safe_window_end.isoformat()),
        ).fetchall()

        ordered_rows: list[sqlite3.Row] = []
        if previous_row:
            ordered_rows.append(previous_row)
        ordered_rows.extend(rows)

        scan_states: dict[str, dict[str, int]] = {}
        previous_online_count: int | None = None
        for row in ordered_rows:
            current_online_count = int(row["online_count"] or 0)
            finished_at = str(row["finished_at"])
            scan_states[finished_at] = {
                "online_count": current_online_count,
                "previous_online_count": int(previous_online_count or 0),
            }
            previous_online_count = current_online_count
        return scan_states


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def online_duration_seconds(value: str | None, is_online: bool) -> int | None:
    if not is_online:
        return None
    dt = parse_iso_utc(value)
    if not dt:
        return None
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    return max(0, seconds)


def preferred_name_for(observation: DeviceObservation) -> str | None:
    return observation.custom_name or observation.detected_name or None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def overlap_seconds(
    start_a: str | None,
    end_a: str | None,
    start_b: str | None,
    end_b: str | None,
) -> int:
    a_start = parse_iso_utc(start_a)
    a_end = parse_iso_utc(end_a) or datetime.now(timezone.utc)
    b_start = parse_iso_utc(start_b)
    b_end = parse_iso_utc(end_b) or datetime.now(timezone.utc)
    if not a_start or not b_start:
        return 0
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds())


PLAY_SESSION_DEVICE_MACS = {
    "5C:84:3C:29:74:5F",
}


def is_play_session_device(device_mac: str | None) -> bool:
    normalized_mac = normalize_mac(device_mac)
    if not normalized_mac:
        return False
    return normalized_mac in PLAY_SESSION_DEVICE_MACS


def infer_transition_reason(
    *,
    event_type: str,
    device_category: str | None,
    device_mac: str | None,
    segment: dict[str, Any],
    previous_segment: dict[str, Any] | None,
    next_segment: dict[str, Any] | None,
    simultaneous_count: int,
    scan_interval_seconds: int,
    scan_online_before: int,
    scan_online_after: int,
) -> dict[str, str]:
    home_threshold = 10 * 60
    is_home_device = normalize_device_category(device_category) in {"personal", "household"}
    is_play_device = is_play_session_device(device_mac)
    previous_duration = int(previous_segment["duration_seconds"]) if previous_segment else 0
    current_duration = int(segment["duration_seconds"])
    network_drop = (
        event_type == "disconnected"
        and scan_online_before >= 2
        and scan_online_after == 0
        and simultaneous_count >= scan_online_before
    )
    network_recovery = (
        event_type == "connected"
        and scan_online_before == 0
        and scan_online_after >= 2
        and simultaneous_count >= scan_online_after
    )

    if network_drop or network_recovery:
        detail = (
            f"W tym samym skanie zniknęły wszystkie aktywne urządzenia ({scan_online_before})."
            if network_drop
            else f"Po chwili wróciło naraz {scan_online_after} urządzeń."
        )
        return {
            "code": "network_issue",
            "label": "Problem z siecią",
            "detail": detail,
            "confidence": "wysoka",
        }

    if event_type == "connected":
        if is_home_device and previous_duration >= home_threshold:
            if is_play_device:
                return {
                    "code": "started_playing",
                    "label": "Zaczęli grać",
                    "detail": f"Konsola znowu jest online po około {human_duration_compact(previous_duration)} offline i nie widać problemu całej sieci.",
                    "confidence": "wysoka",
                }
            return {
                "code": "returned_home",
                "label": "Wrócił do domu",
                "detail": f"Urządzenie znowu jest online po około {human_duration_compact(previous_duration)} offline i nie widać problemu całej sieci.",
                "confidence": "wysoka",
            }
        return {
            "code": "connected_generic",
            "label": "Połączono",
            "detail": "Urządzenie znowu odpowiada w lokalnej sieci, ale bez mocnej przesłanki, że to powrót do domu.",
            "confidence": "niska",
        }

    if is_home_device and current_duration >= home_threshold:
        if is_play_device:
            return {
                "code": "stopped_playing",
                "label": "Skończyli grać",
                "detail": f"Konsola jest offline od około {human_duration_compact(current_duration)} i nie widać problemu całej sieci.",
                "confidence": "wysoka",
            }
        return {
            "code": "left_home",
            "label": "Wyszedł z domu",
            "detail": f"Urządzenie jest offline od około {human_duration_compact(current_duration)} i nie widać problemu całej sieci.",
            "confidence": "wysoka",
        }
    return {
        "code": "disconnected_generic",
        "label": "Rozłączono",
        "detail": "Urządzenie przestało odpowiadać, ale to jeszcze za mało, żeby nazwać to wyjściem z domu.",
        "confidence": "niska",
    }


def summarize_timeline_insight(
    *,
    events: list[dict[str, Any]],
    is_online: bool,
    online_seconds: int,
    offline_seconds: int,
    coverage_seconds: int,
) -> dict[str, str | int]:
    total_changes = len(events)
    last_event = events[-1] if events else None
    if coverage_seconds < 10 * 60:
        return {
            "kind": "insufficient_data",
            "label": "Za mało danych",
            "detail": "Historia jest jeszcze za krótka, żeby sensownie zgadywać, czy to powrót albo wyjście z domu.",
            "confidence": "niska",
            "change_count": total_changes,
        }

    if last_event and last_event.get("reason_code") == "network_issue":
        return {
            "kind": "network_issue",
            "label": "Problem z siecią",
            "detail": str(last_event.get("reason_detail") or "Wiele urządzeń zmieniło stan naraz."),
            "confidence": str(last_event.get("confidence") or "wysoka"),
            "change_count": total_changes,
        }

    if last_event and last_event.get("reason_code") == "returned_home":
        return {
            "kind": "returned_home",
            "label": "Wrócił do domu",
            "detail": str(last_event.get("reason_detail") or ""),
            "confidence": str(last_event.get("confidence") or "wysoka"),
            "change_count": total_changes,
        }

    if last_event and last_event.get("reason_code") == "started_playing":
        return {
            "kind": "started_playing",
            "label": "Zaczęli grać",
            "detail": str(last_event.get("reason_detail") or ""),
            "confidence": str(last_event.get("confidence") or "wysoka"),
            "change_count": total_changes,
        }

    if last_event and last_event.get("reason_code") == "left_home" and not is_online:
        return {
            "kind": "left_home",
            "label": "Wyszedł z domu",
            "detail": str(last_event.get("reason_detail") or ""),
            "confidence": str(last_event.get("confidence") or "wysoka"),
            "change_count": total_changes,
        }

    if last_event and last_event.get("reason_code") == "stopped_playing" and not is_online:
        return {
            "kind": "stopped_playing",
            "label": "Skończyli grać",
            "detail": str(last_event.get("reason_detail") or ""),
            "confidence": str(last_event.get("confidence") or "wysoka"),
            "change_count": total_changes,
        }

    return {
        "kind": "online_now" if is_online else "offline_now",
        "label": "Obecnie online" if is_online else "Obecnie offline",
        "detail": "Na razie bez mocnej przesłanki, że to powrót do domu, wyjście z domu albo problem całej sieci.",
        "confidence": "niska",
        "change_count": total_changes,
    }


def summarize_all_devices_timeline_insight(
    *,
    events: list[dict[str, Any]],
    coverage_seconds: int,
    device_count: int,
    max_online_count: int,
) -> dict[str, str | int]:
    if coverage_seconds < 10 * 60:
        return {
            "kind": "insufficient_data",
            "label": "Za mało danych",
            "detail": "Historia całej sieci jest jeszcze za krótka, żeby wyciągać sensowne wnioski.",
            "confidence": "niska",
            "change_count": len(events),
        }

    if not events:
        return {
            "kind": "stable-network",
            "label": "Spokojna sieć",
            "detail": "W wybranym oknie nie zapisano żadnych zmian stanu urządzeń.",
            "confidence": "średnia",
            "change_count": 0,
        }

    last_event = events[-1]
    if str(last_event.get("reason_code") or "") == "network_issue":
        return {
            "kind": "network_issue",
            "label": "Problem z siecią",
            "detail": str(last_event.get("reason_detail") or "Wiele urządzeń zmieniło stan jednocześnie."),
            "confidence": str(last_event.get("confidence") or "wysoka"),
            "change_count": len(events),
        }

    changed_devices = len({str(event.get("device_key") or "") for event in events if event.get("device_key")})
    return {
        "kind": "network-activity",
        "label": "Wszystkie zdarzenia",
        "detail": (
            f"Zapisano {len(events)} zmian dla {changed_devices or device_count} urządzeń. "
            f"Maksymalnie online było jednocześnie {max(0, max_online_count)} urządzeń."
        ),
        "confidence": "średnia",
        "change_count": len(events),
    }


def human_duration_compact(seconds: int | float | None) -> str:
    safe = max(0, int(seconds or 0))
    days, rest = divmod(safe, 86_400)
    hours, rest = divmod(rest, 3_600)
    minutes, _ = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{safe}s"


def local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def parse_local_day(value: str | None) -> date_cls | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def local_day_from_datetime(value: datetime | None) -> date_cls:
    if not value:
        return local_day_bounds()["day"]
    return value.astimezone(local_timezone()).date()


def format_local_day_label(day: date_cls) -> str:
    return day.strftime("%d.%m.%Y")


def local_day_bounds(
    day: date_cls | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    tz = local_timezone()
    local_now = (now or datetime.now(tz)).astimezone(tz)
    target_day = day or local_now.date()
    start_local = datetime.combine(target_day, time_cls.min, tzinfo=tz)
    nominal_end_local = start_local + timedelta(days=1)
    end_local = min(nominal_end_local, local_now) if target_day == local_now.date() else nominal_end_local
    return {
        "day": target_day,
        "start_local": start_local,
        "end_local": end_local,
        "start_utc": start_local.astimezone(timezone.utc),
        "end_utc": end_local.astimezone(timezone.utc),
        "is_today": target_day == local_now.date(),
    }


def history_windows(
    now: datetime | None = None,
    *,
    day: date_cls | None = None,
) -> dict[str, dict[str, datetime]]:
    bounds = local_day_bounds(day=day, now=now)
    selected_start = bounds["start_local"]
    selected_end = bounds["end_local"]
    week_start = selected_start - timedelta(days=selected_start.weekday())
    month_start = selected_start.replace(day=1)
    return {
        "day": {
            "start": bounds["start_utc"],
            "end": bounds["end_utc"],
        },
        "week": {
            "start": week_start.astimezone(timezone.utc),
            "end": selected_end.astimezone(timezone.utc),
        },
        "month": {
            "start": month_start.astimezone(timezone.utc),
            "end": selected_end.astimezone(timezone.utc),
        },
    }
