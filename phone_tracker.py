"""Local-only phone event store and deterministic read models.

All stored instants are UTC. Calendar windows are constructed in the caller's
IANA timezone, then converted to UTC before querying SQLite.
"""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import math
import secrets
import sqlite3
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MAX_BATCH = 500
EVENT_TYPES = {
    "app_foreground", "app_background", "screen_on", "screen_off", "unlock",
    "notification_posted", "notification_removed", "battery", "location",
    "app_installed", "app_removed", "device_boot", "block", "override",
}


class PhoneTrackerError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def utc_iso(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError) as exc:
        raise PhoneTrackerError("timestamp must be an ISO 8601 instant with an offset") from exc


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _tz(name):
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise PhoneTrackerError("Unknown IANA timezone") from exc


def time_window(range_key="today", tz_name="UTC", start=None, end=None, now=None):
    zone = _tz(tz_name)
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    today = local_now.date()
    if range_key == "all":
        return None, None
    if range_key == "custom":
        try:
            begin_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)
        except (TypeError, ValueError) as exc:
            raise PhoneTrackerError("Custom range needs start/end YYYY-MM-DD") from exc
        if end_date <= begin_date or (end_date - begin_date).days > 366:
            raise PhoneTrackerError("Custom range must span 1 to 366 days")
    elif range_key == "today":
        begin_date, end_date = today, today + timedelta(days=1)
    elif range_key == "yesterday":
        begin_date, end_date = today - timedelta(days=1), today
    elif range_key == "previous_day":
        begin_date, end_date = today - timedelta(days=2), today - timedelta(days=1)
    elif range_key == "7d":
        begin_date, end_date = today - timedelta(days=6), today + timedelta(days=1)
    elif range_key == "previous_7d":
        begin_date, end_date = today - timedelta(days=13), today - timedelta(days=6)
    elif range_key == "30d":
        begin_date, end_date = today - timedelta(days=29), today + timedelta(days=1)
    elif range_key == "previous_30d":
        begin_date, end_date = today - timedelta(days=59), today - timedelta(days=29)
    elif range_key == "month":
        begin_date, end_date = today.replace(day=1), (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif range_key == "previous_month":
        end_date = today.replace(day=1)
        begin_date = (end_date - timedelta(days=1)).replace(day=1)
    else:
        raise PhoneTrackerError("Unknown time range")
    beginning = datetime.combine(begin_date, datetime.min.time(), zone)
    ending = datetime.combine(end_date, datetime.min.time(), zone)
    return utc_iso(beginning.isoformat()), utc_iso(ending.isoformat())


def _event_row(row):
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json"))
    return result


def reconstruct(events, end_at=None):
    """Pair explicit foreground/background; screen-off closes an open app.

    An unmatched foreground is left open until the next foreground or screen-off.
    An unmatched trailing foreground is omitted, never guessed from wall time.
    """
    ordered = sorted(events, key=lambda e: (e["timestamp"], e["event_id"]))
    apps, phones = [], []
    current_app = None
    phone_start = None
    phone_device = None
    for event in ordered:
        kind, at = event["event_type"], event["timestamp"]
        if kind == "unlock" and phone_start is None:
            phone_start = at
            phone_device = event.get("device_id")
        if kind == "screen_off" and phone_start is not None:
            if at > phone_start:
                phones.append({"start": phone_start, "end": at, "device_id":phone_device,
                               "seconds": (datetime.fromisoformat(at.replace("Z", "+00:00")) - datetime.fromisoformat(phone_start.replace("Z", "+00:00"))).total_seconds()})
            phone_start = None
            phone_device = None
        if kind == "app_foreground":
            if current_app and at > current_app["start"]:
                apps.append(_close_app(current_app, at))
            current_app = {"device_id":event.get("device_id"),"package_name": event.get("package_name"), "app_name": event.get("app_name"), "start": at, "session_id": event.get("session_id")}
        elif kind in {"app_background", "screen_off"} and current_app:
            if kind == "screen_off" or event.get("package_name") == current_app["package_name"]:
                if at > current_app["start"]:
                    apps.append(_close_app(current_app, at))
                current_app = None
    if end_at and current_app and end_at > current_app["start"]:
        # Used only for bounded historical windows; never extend an active session to now.
        current_app = None
    return apps, phones


def _close_app(app, end):
    seconds = (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(app["start"].replace("Z", "+00:00"))).total_seconds()
    return {**app, "end": end, "seconds": seconds}


def _clip_session(session, begin, finish):
    start = max(session["start"], begin) if begin else session["start"]
    end = min(session["end"], finish) if finish else session["end"]
    if end <= start:
        return None
    seconds = (datetime.fromisoformat(end.replace("Z", "+00:00")) -
               datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
    return {**session, "start": start, "end": end, "seconds": seconds}


def notification_attribution(events, window_seconds=120):
    if not 1 <= window_seconds <= 3600:
        raise PhoneTrackerError("Attribution window must be 1 to 3600 seconds")
    posted = sorted((e for e in events if e["event_type"] == "notification_posted"), key=lambda e: e["timestamp"])
    opened = sorted((e for e in events if e["event_type"] == "app_foreground"), key=lambda e: e["timestamp"])
    used = set()
    matches = []
    for app in opened:
        app_time = datetime.fromisoformat(app["timestamp"].replace("Z", "+00:00"))
        candidates = []
        for notification in posted:
            if notification["event_id"] in used or notification.get("package_name") != app.get("package_name"):
                continue
            lag = (app_time - datetime.fromisoformat(notification["timestamp"].replace("Z", "+00:00"))).total_seconds()
            if 0 <= lag <= window_seconds:
                candidates.append((lag, notification))
        if candidates:
            lag, notification = min(candidates, key=lambda pair: pair[0])
            used.add(notification["event_id"])
            matches.append({"notification_id": notification["event_id"], "open_id": app["event_id"], "latency_seconds": lag})
    return matches


def _cluster_key(latitude, longitude):
    return f"{round(latitude/0.005)*0.005:.3f}:{round(longitude/0.005)*0.005:.3f}"


def location_breakdown(events, app_sessions, names=None):
    """Conservative dwell lower bound from consecutive points in one ~500m cell."""
    names = names or {}
    points = []
    for event in events:
        if event["event_type"] != "location":
            continue
        meta = event.get("metadata") or {}
        try:
            lat,lon,accuracy = float(meta["latitude"]),float(meta["longitude"]),float(meta["accuracy_m"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= accuracy <= 1000):
                continue
            device = event.get("device_id")
            points.append((event["timestamp"],f"{device}:{_cluster_key(lat,lon)}",lat,lon,accuracy,device))
        except (KeyError,TypeError,ValueError):
            continue
    points.sort(key=lambda point:(str(point[-1]),point[0]))
    clusters = defaultdict(lambda: {"dwell_seconds_lower_bound":0,"screen_time_seconds_estimate":0,"points":0,
                                    "latitude":None,"longitude":None,"last_accuracy_m":None})
    for _,key,lat,lon,accuracy,_device in points:
        item = clusters[key]
        item["points"] += 1
        item["latitude"],item["longitude"] = lat,lon
        item["last_accuracy_m"] = accuracy
    for current,next_point in zip(points,points[1:]):
        if current[-1] != next_point[-1]:
            continue
        start,key,*_ = current
        end,next_key,*_ = next_point
        delta = (datetime.fromisoformat(end.replace("Z","+00:00")) -
                 datetime.fromisoformat(start.replace("Z","+00:00"))).total_seconds()
        if key != next_key or not 0 < delta <= 7200:
            continue
        clusters[key]["dwell_seconds_lower_bound"] += delta
        for session in app_sessions:
            if session.get("device_id") != current[-1]:
                continue
            overlap_start = max(start,session["start"])
            overlap_end = min(end,session["end"])
            if overlap_end > overlap_start:
                clusters[key]["screen_time_seconds_estimate"] += (
                    datetime.fromisoformat(overlap_end.replace("Z","+00:00")) -
                    datetime.fromisoformat(overlap_start.replace("Z","+00:00"))).total_seconds()
    return [{"cluster_key":key,"label":names.get(key) or f"Place {key.split(':',1)[-1]}",**value,
             "quality":"estimated from sparse location points"} for key,value in clusters.items()]


def behavior_patterns(events, app_sessions, zone):
    foreground = [e for e in events if e["event_type"] == "app_foreground"]
    doomscroll = [s for s in app_sessions if s["seconds"] >= 1200]
    rapid = []
    for index,opening in enumerate(foreground):
        if index < 11:
            continue
        first = foreground[index-11]
        span = (datetime.fromisoformat(opening["timestamp"].replace("Z","+00:00")) -
                datetime.fromisoformat(first["timestamp"].replace("Z","+00:00"))).total_seconds()
        if span <= 600 and (not rapid or rapid[-1] != first["timestamp"]):
            rapid.append(first["timestamp"])
    late_seconds = 0
    for session in app_sessions:
        cursor = datetime.fromisoformat(session["start"].replace("Z","+00:00"))
        end = datetime.fromisoformat(session["end"].replace("Z","+00:00"))
        while cursor < end:
            next_minute = min(end,cursor.replace(second=0,microsecond=0)+timedelta(minutes=1))
            if cursor.astimezone(zone).hour < 5:
                late_seconds += (next_minute-cursor).total_seconds()
            cursor = next_minute
    return {"doomscroll_sessions":len(doomscroll),"doomscroll_threshold_minutes":20,
            "rapid_switch_windows":len(rapid),"rapid_switch_threshold":{"opens":12,"minutes":10},
            "late_night_seconds":late_seconds,
            "first_app":foreground[0]["package_name"] if foreground else None}


def session_facts(events, app_sessions, phone_sessions):
    first_app_latencies = []
    empty_unlocks = 0
    sequences = []
    for phone in phone_sessions:
        entries = [app for app in app_sessions if app.get("device_id") == phone.get("device_id")
                   and phone["start"] <= app["start"] < phone["end"]]
        if not entries:
            empty_unlocks += 1
            continue
        first_app_latencies.append((datetime.fromisoformat(entries[0]["start"].replace("Z","+00:00")) -
            datetime.fromisoformat(phone["start"].replace("Z","+00:00"))).total_seconds())
        sequence = [app["package_name"] for app in entries if app.get("package_name")]
        if sequence:
            sequences.append({"start":phone["start"],"packages":sequence})
    reopen = defaultdict(list)
    per_app = defaultdict(list)
    for app in app_sessions:
        if app.get("package_name"):
            per_app[(app.get("device_id"),app["package_name"])].append(app)
    for (_,package),sessions in per_app.items():
        sessions.sort(key=lambda value:value["start"])
        for previous,current in zip(sessions,sessions[1:]):
            gap = (datetime.fromisoformat(current["start"].replace("Z","+00:00")) -
                   datetime.fromisoformat(previous["end"].replace("Z","+00:00"))).total_seconds()
            if gap >= 0:
                reopen[package].append(gap)
    return {"empty_unlocks":empty_unlocks,"short_phone_sessions_under_2m":sum(p["seconds"] < 120 for p in phone_sessions),
            "average_first_app_latency_seconds":sum(first_app_latencies)/len(first_app_latencies) if first_app_latencies else None,
            "sequences":sequences,"average_reopen_gap_seconds_by_package":{
                package:sum(gaps)/len(gaps) for package,gaps in reopen.items()}}


def battery_exposure(events, app_sessions):
    samples_by_device = defaultdict(list)
    for event in events:
        if event["event_type"] != "battery":
            continue
        meta = event.get("metadata") or {}
        try:
            percent = float(meta["percent"])
            if not 0 <= percent <= 100:
                continue
            samples_by_device[event.get("device_id")].append((event["timestamp"],percent,bool(meta.get("charging"))))
        except (KeyError,TypeError,ValueError):
            continue
    app_drop = defaultdict(float)
    total_drop = 0.0
    for device,samples in samples_by_device.items():
        samples.sort()
        for (start,first,charging),(end,second,next_charging) in zip(samples,samples[1:]):
            duration = (datetime.fromisoformat(end.replace("Z","+00:00")) -
                        datetime.fromisoformat(start.replace("Z","+00:00"))).total_seconds()
            if charging or next_charging or duration <= 0 or duration > 7200 or second >= first:
                continue
            drop = first-second
            total_drop += drop
            for session in app_sessions:
                if session.get("device_id") != device:
                    continue
                overlap_start,overlap_end = max(start,session["start"]),min(end,session["end"])
                if overlap_end > overlap_start and session.get("package_name"):
                    overlap = (datetime.fromisoformat(overlap_end.replace("Z","+00:00")) -
                               datetime.fromisoformat(overlap_start.replace("Z","+00:00"))).total_seconds()
                    app_drop[session["package_name"]] += drop * overlap/duration
    return {"observed_drop_percent":total_drop,
            "estimated_exposure_percent_by_package":dict(app_drop),
            "quality":"time-proportional exposure estimate; not per-app power measurement"}


class PhoneTrackerStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _migrate(self):
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 5:
                raise RuntimeError("Phone Tracker database is newer than this application")
            if version == 0:
                db.executescript("""
                    CREATE TABLE devices(device_id TEXT PRIMARY KEY, label TEXT NOT NULL,
                        token_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_sync TEXT,
                        last_ip TEXT, is_sample INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE apps(device_id TEXT NOT NULL, package_name TEXT NOT NULL,
                        app_name TEXT NOT NULL, category TEXT, icon_base64 TEXT,
                        PRIMARY KEY(device_id, package_name),
                        FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
                    CREATE TABLE events(event_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
                        package_name TEXT, app_name TEXT, session_id TEXT,
                        value_numeric REAL, value_text TEXT, metadata_json TEXT NOT NULL,
                        received_at TEXT NOT NULL,
                        FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
                    CREATE INDEX idx_phone_events_device_time ON events(device_id,timestamp);
                    CREATE INDEX idx_phone_events_type_time ON events(event_type,timestamp);
                    CREATE INDEX idx_phone_events_package_time ON events(package_name,timestamp);
                    CREATE INDEX idx_phone_events_session ON events(session_id);
                    CREATE TABLE sync_batches(device_id TEXT NOT NULL, batch_id TEXT NOT NULL,
                        received_at TEXT NOT NULL, result_json TEXT NOT NULL,
                        PRIMARY KEY(device_id,batch_id));
                    CREATE TABLE rules(rule_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                        name TEXT NOT NULL, target TEXT NOT NULL, enabled INTEGER NOT NULL,
                        definition_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                        FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
                    CREATE TABLE external_conditions(device_id TEXT NOT NULL, name TEXT NOT NULL,
                        value_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY(device_id,name));
                    CREATE TABLE place_names(device_id TEXT NOT NULL, cluster_key TEXT NOT NULL,
                        label TEXT NOT NULL, PRIMARY KEY(device_id,cluster_key));
                    PRAGMA user_version=1;
                """)
            if version < 2:
                db.executescript("""
                    CREATE TABLE settings(key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
                    INSERT INTO settings(key,value_json) VALUES('raw_notification_text_days','30');
                    INSERT INTO settings(key,value_json) VALUES('usage_events_days','null');
                    PRAGMA user_version=2;
                """)
            if version < 3:
                db.executescript("""
                    ALTER TABLE devices ADD COLUMN last_reported_pending INTEGER;
                    PRAGMA user_version=3;
                """)
            if version < 4:
                db.executescript("""
                    CREATE TABLE override_settings(device_id TEXT PRIMARY KEY, mode TEXT NOT NULL,
                        duration_minutes INTEGER NOT NULL, cooldown_minutes INTEGER NOT NULL,
                        pin_salt TEXT, pin_hash TEXT,
                        FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
                    PRAGMA user_version=4;
                """)
            if version < 5:
                db.executescript("""
                    ALTER TABLE devices ADD COLUMN last_blocker_enabled INTEGER;
                    ALTER TABLE devices ADD COLUMN last_config_version INTEGER;
                    PRAGMA user_version=5;
                """)

    def pair(self, label):
        label = str(label or "Phone").strip()[:80]
        device_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("INSERT INTO devices(device_id,label,token_hash,created_at) VALUES(?,?,?,?)",
                       (device_id, label, hashlib.sha256(token.encode()).hexdigest(), _now()))
        return {"device_id": device_id, "token": token, "label": label}

    def authenticate(self, device_id, token):
        if not device_id or not token:
            return False
        with self._connect() as db:
            row = db.execute("SELECT token_hash FROM devices WHERE device_id=? AND is_sample=0", (device_id,)).fetchone()
        return bool(row and hmac.compare_digest(row[0], hashlib.sha256(token.encode()).hexdigest()))

    def devices(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT device_id,label,created_at,last_sync,last_ip,last_reported_pending,last_blocker_enabled,last_config_version,is_sample FROM devices ORDER BY created_at DESC")]

    def revoke(self, device_id):
        with self._connect() as db:
            cur = db.execute("UPDATE devices SET token_hash=? WHERE device_id=? AND is_sample=0",
                             ("revoked:"+secrets.token_hex(32),device_id))
            return {"revoked":cur.rowcount}

    def save_rule(self, device_id, definition):
        from phone_tracker_rules import validate_rule
        validate_rule(definition)
        rule_id = definition.get("rule_id") or str(uuid.uuid4())
        try:
            uuid.UUID(rule_id)
        except (ValueError,TypeError) as exc:
            raise PhoneTrackerError("rule_id must be a UUID") from exc
        clean = {"rule_id":rule_id,"name":definition["name"].strip(),"target":definition["target"],
                 "action":"block","when":definition["when"],"enabled":bool(definition.get("enabled",True))}
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=? AND is_sample=0",(device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device",404)
            owner = db.execute("SELECT device_id FROM rules WHERE rule_id=?",(rule_id,)).fetchone()
            if owner and owner[0] != device_id:
                raise PhoneTrackerError("Rule belongs to another device",409)
            db.execute("""INSERT INTO rules(rule_id,device_id,name,target,enabled,definition_json,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(rule_id) DO UPDATE SET name=excluded.name,target=excluded.target,
                enabled=excluded.enabled,definition_json=excluded.definition_json,updated_at=excluded.updated_at""",
                (rule_id,device_id,clean["name"],clean["target"],int(clean["enabled"]),json.dumps(clean),_now()))
        return clean

    def rules(self, device_id):
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT definition_json FROM rules WHERE device_id=? ORDER BY name",(device_id,))]

    def delete_rule(self, rule_id):
        with self._connect() as db:
            cur = db.execute("DELETE FROM rules WHERE rule_id=?",(rule_id,))
            return {"deleted":cur.rowcount}

    def set_external_condition(self, device_id, name, value):
        if not isinstance(name,str) or not 1 <= len(name) <= 80 or not all(c.isalnum() or c == "_" for c in name):
            raise PhoneTrackerError("Invalid external condition name")
        if not isinstance(value,(bool,int,float)):
            raise PhoneTrackerError("External condition value must be boolean or numeric")
        if isinstance(value,float) and not math.isfinite(value):
            raise PhoneTrackerError("External condition must be finite")
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=? AND is_sample=0",(device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device",404)
            db.execute("""INSERT INTO external_conditions(device_id,name,value_json,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(device_id,name) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",
                (device_id,name,json.dumps(value),_now()))
        return {"name":name,"value":value}

    def config(self, device_id):
        with self._connect() as db:
            apps = [dict(row) for row in db.execute("SELECT package_name,category FROM apps WHERE device_id=?",(device_id,))]
            condition_rows = list(db.execute(
                "SELECT name,value_json,updated_at FROM external_conditions WHERE device_id=?",(device_id,)))
            conditions = {row["name"]:json.loads(row["value_json"]) for row in condition_rows}
            from zoneinfo import ZoneInfo
            dates = {row["name"]:(datetime.fromisoformat(row["updated_at"].replace("Z","+00:00"))
                .astimezone(ZoneInfo("Europe/Warsaw")) - timedelta(hours=6)).date().isoformat()
                for row in condition_rows if row["name"] == "cleaning_done_today"}
        return {"schema_version":1,"rules":self.rules(device_id),"external_conditions":conditions,
                "external_condition_dates":dates,
                "categories":{row["package_name"]:row["category"] for row in apps if row["category"]},
                "retention":self.retention(),"override_policy":self.override_policy(device_id)}

    def override_policy(self, device_id):
        with self._connect() as db:
            row = db.execute("""SELECT mode,duration_minutes,cooldown_minutes,pin_salt,pin_hash
                FROM override_settings WHERE device_id=?""",(device_id,)).fetchone()
        return dict(row) if row else {"mode":"always","duration_minutes":5,"cooldown_minutes":0,
                                      "pin_salt":None,"pin_hash":None}

    def set_override_policy(self, device_id, body):
        if not isinstance(body,dict) or body.get("mode") not in {"disabled","always","pin","cooldown"}:
            raise PhoneTrackerError("Invalid override mode")
        try:
            duration = int(body.get("duration_minutes",5))
            cooldown = int(body.get("cooldown_minutes",0))
        except (TypeError,ValueError) as exc:
            raise PhoneTrackerError("Invalid override duration") from exc
        if not 1 <= duration <= 60 or not 0 <= cooldown <= 1440:
            raise PhoneTrackerError("Override duration must be 1–60 min and cooldown 0–1440 min")
        salt = pin_hash = None
        if body["mode"] == "pin":
            pin = body.get("pin")
            if not isinstance(pin,str) or not pin.isdigit() or not 4 <= len(pin) <= 12:
                raise PhoneTrackerError("PIN must contain 4–12 digits")
            salt = secrets.token_hex(16)
            pin_hash = hashlib.pbkdf2_hmac("sha256",pin.encode(),bytes.fromhex(salt),120_000).hex()
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=? AND is_sample=0",(device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device",404)
            db.execute("""INSERT INTO override_settings(device_id,mode,duration_minutes,cooldown_minutes,pin_salt,pin_hash)
                VALUES(?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET mode=excluded.mode,
                duration_minutes=excluded.duration_minutes,cooldown_minutes=excluded.cooldown_minutes,
                pin_salt=excluded.pin_salt,pin_hash=excluded.pin_hash""",
                (device_id,body["mode"],duration,cooldown,salt,pin_hash))
        return {"mode":body["mode"],"duration_minutes":duration,"cooldown_minutes":cooldown}

    def retention(self):
        with self._connect() as db:
            return {row["key"]:json.loads(row["value_json"]) for row in db.execute("SELECT key,value_json FROM settings")}

    def set_retention(self, values):
        if not isinstance(values,dict):
            raise PhoneTrackerError("Retention settings must be an object")
        allowed = {"raw_notification_text_days","usage_events_days"}
        if not set(values).issubset(allowed):
            raise PhoneTrackerError("Unknown retention setting")
        for key,value in values.items():
            if value is not None and (not isinstance(value,int) or isinstance(value,bool) or not 1 <= value <= 3650):
                raise PhoneTrackerError("Retention days must be 1 to 3650 or null")
            if key == "raw_notification_text_days" and value is None:
                raise PhoneTrackerError("Notification text retention needs a number of days")
        with self._connect() as db:
            for key,value in values.items():
                db.execute("UPDATE settings SET value_json=? WHERE key=?",(json.dumps(value),key))
        self.prune_retention(force=True)
        return self.retention()

    def prune_retention(self, force=False):
        settings = self.retention()
        now = datetime.now(timezone.utc)
        with self._connect() as db:
            last = db.execute("SELECT value_json FROM settings WHERE key='last_retention_prune'").fetchone()
        if not force and last and json.loads(last[0]) == now.date().isoformat():
            return {"notification_bodies_scrubbed":0,"events_removed":0}
        cutoff = utc_iso((now-timedelta(days=settings["raw_notification_text_days"])).isoformat())
        scrubbed = 0
        with self._connect() as db:
            for row in db.execute("SELECT event_id,metadata_json FROM events WHERE event_type='notification_posted' AND timestamp<?",(cutoff,)).fetchall():
                metadata = json.loads(row["metadata_json"])
                if "title" in metadata or "text" in metadata:
                    metadata.pop("title",None); metadata.pop("text",None)
                    db.execute("UPDATE events SET metadata_json=? WHERE event_id=?",(json.dumps(metadata),row["event_id"]))
                    scrubbed += 1
            removed = 0
            if settings["usage_events_days"] is not None:
                cutoff = utc_iso((now-timedelta(days=settings["usage_events_days"])).isoformat())
                removed = db.execute("DELETE FROM events WHERE timestamp<?",(cutoff,)).rowcount
            db.execute("""INSERT INTO settings(key,value_json) VALUES('last_retention_prune',?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json""",(json.dumps(now.date().isoformat()),))
        return {"notification_bodies_scrubbed":scrubbed,"events_removed":removed}

    def set_category(self, device_id, package_name, category):
        if not isinstance(package_name,str) or not 1 <= len(package_name) <= 256:
            raise PhoneTrackerError("Invalid package")
        if not isinstance(category,str) or len(category) > 60:
            raise PhoneTrackerError("Invalid category")
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=? AND is_sample=0",(device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device",404)
            db.execute("""INSERT INTO apps(device_id,package_name,app_name,category) VALUES(?,?,?,?)
                ON CONFLICT(device_id,package_name) DO UPDATE SET category=excluded.category""",
                (device_id,package_name,package_name,category.strip()))
        return {"package_name":package_name,"category":category.strip()}

    def save_apps(self, device_id, apps):
        if not isinstance(apps,list) or len(apps) > 50:
            raise PhoneTrackerError("App registry batch must contain at most 50 apps")
        accepted = []
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=? AND is_sample=0",(device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device",404)
            for app in apps:
                if not isinstance(app,dict):
                    raise PhoneTrackerError("Invalid app registry entry")
                package = app.get("package_name")
                name = app.get("app_name")
                icon = app.get("icon_base64")
                if not isinstance(package,str) or not 1 <= len(package) <= 256 or not isinstance(name,str) or not 1 <= len(name) <= 200:
                    raise PhoneTrackerError("Invalid app identity")
                if icon is not None:
                    if not isinstance(icon,str) or len(icon) > 90_000:
                        raise PhoneTrackerError("App icon too large")
                    try:
                        binary = base64.b64decode(icon,validate=True)
                    except (ValueError,base64.binascii.Error) as exc:
                        raise PhoneTrackerError("Invalid app icon encoding") from exc
                    if not binary.startswith(b"\x89PNG\r\n\x1a\n") or len(binary) > 65_536:
                        raise PhoneTrackerError("App icon must be a PNG under 64 KiB")
                db.execute("""INSERT INTO apps(device_id,package_name,app_name,icon_base64) VALUES(?,?,?,?)
                    ON CONFLICT(device_id,package_name) DO UPDATE SET app_name=excluded.app_name,
                    icon_base64=COALESCE(excluded.icon_base64,apps.icon_base64)""",
                    (device_id,package,name,icon))
                accepted.append(package)
        return {"accepted":accepted}

    def rename_place(self, device_id, cluster_key, label):
        if not isinstance(cluster_key,str) or len(cluster_key) > 80 or not isinstance(label,str) or not 1 <= len(label.strip()) <= 80:
            raise PhoneTrackerError("Invalid place label")
        if not cluster_key.startswith(f"{device_id}:"):
            raise PhoneTrackerError("Place does not belong to device")
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=?",(device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device",404)
            db.execute("""INSERT INTO place_names(device_id,cluster_key,label) VALUES(?,?,?)
                ON CONFLICT(device_id,cluster_key) DO UPDATE SET label=excluded.label""",
                (device_id,cluster_key,label.strip()))
        return {"device_id":device_id,"cluster_key":cluster_key,"label":label.strip()}

    def ingest(self, payload, client_ip=None):
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise PhoneTrackerError("Unsupported sync schema_version")
        device_id, batch_id = payload.get("device_id"), payload.get("batch_id")
        try:
            uuid.UUID(str(device_id)); uuid.UUID(str(batch_id))
        except (ValueError, TypeError) as exc:
            raise PhoneTrackerError("device_id and batch_id must be UUIDs") from exc
        events = payload.get("events")
        if not isinstance(events, list) or len(events) > MAX_BATCH:
            raise PhoneTrackerError(f"events must be a list of at most {MAX_BATCH}")
        utc_iso(payload.get("sent_at"))
        pending_count = payload.get("pending_count")
        if pending_count is not None and (not isinstance(pending_count,int) or isinstance(pending_count,bool) or not 0 <= pending_count <= 10_000_000):
            raise PhoneTrackerError("Invalid pending_count")
        blocker_enabled = payload.get("blocker_enabled")
        if blocker_enabled is not None and not isinstance(blocker_enabled,bool):
            raise PhoneTrackerError("Invalid blocker_enabled")
        config_version = payload.get("config_version")
        if config_version is not None and (not isinstance(config_version,int) or isinstance(config_version,bool) or config_version < 0):
            raise PhoneTrackerError("Invalid config_version")
        accepted, duplicates, rejected = [], [], []
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=? AND is_sample=0", (device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device", 401)
            previous = db.execute("SELECT result_json FROM sync_batches WHERE device_id=? AND batch_id=?", (device_id,batch_id)).fetchone()
            if previous:
                return json.loads(previous[0])
            for item in events:
                event_id = item.get("event_id") if isinstance(item, dict) else None
                try:
                    uuid.UUID(str(event_id))
                    kind = item.get("event_type")
                    if kind not in EVENT_TYPES:
                        raise PhoneTrackerError("Unknown event_type")
                    timestamp = utc_iso(item.get("timestamp"))
                    package_name = item.get("package_name") or None
                    app_name = item.get("app_name") or None
                    if package_name is not None and (not isinstance(package_name, str) or len(package_name) > 256):
                        raise PhoneTrackerError("Invalid package_name")
                    if app_name is not None and (not isinstance(app_name, str) or len(app_name) > 200):
                        raise PhoneTrackerError("Invalid app_name")
                    metadata = item.get("metadata") or {}
                    if not isinstance(metadata, dict) or len(json.dumps(metadata)) > 8192:
                        raise PhoneTrackerError("Invalid metadata")
                    numeric = item.get("value_numeric")
                    if numeric is not None and (not isinstance(numeric,(int,float)) or isinstance(numeric,bool)
                                                or abs(numeric) > 1e12 or (isinstance(numeric,float) and not math.isfinite(numeric))):
                        raise PhoneTrackerError("Invalid value_numeric")
                    session_id = item.get("session_id")
                    if session_id is not None and (not isinstance(session_id,str) or len(session_id) > 128):
                        raise PhoneTrackerError("Invalid session_id")
                    existing = db.execute("SELECT device_id FROM events WHERE event_id=?", (event_id,)).fetchone()
                    if existing:
                        if existing[0] != device_id:
                            raise PhoneTrackerError("event_id belongs to another device")
                        duplicates.append(event_id)
                        continue
                    db.execute("""INSERT INTO events(event_id,device_id,timestamp,event_type,package_name,app_name,
                        session_id,value_numeric,value_text,metadata_json,received_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (event_id,device_id,timestamp,kind,package_name,app_name,session_id,
                         numeric,str(item.get("value_text"))[:4096] if item.get("value_text") is not None else None,
                         json.dumps(metadata,ensure_ascii=False),_now()))
                    if package_name and app_name:
                        db.execute("""INSERT INTO apps(device_id,package_name,app_name) VALUES(?,?,?)
                            ON CONFLICT(device_id,package_name) DO UPDATE SET app_name=excluded.app_name""",
                            (device_id,package_name,app_name))
                    accepted.append(event_id)
                except (PhoneTrackerError, ValueError, TypeError, sqlite3.Error) as exc:
                    rejected.append({"event_id": event_id, "reason": str(exc)[:160]})
            result = {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}
            db.execute("INSERT INTO sync_batches(device_id,batch_id,received_at,result_json) VALUES(?,?,?,?)",
                       (device_id,batch_id,_now(),json.dumps(result)))
            reported_pending = max(0,pending_count-len(accepted)-len(duplicates)-len(rejected)) if pending_count is not None else None
            db.execute("""UPDATE devices SET last_sync=?,last_ip=?,last_reported_pending=COALESCE(?,last_reported_pending),
                last_blocker_enabled=COALESCE(?,last_blocker_enabled),last_config_version=COALESCE(?,last_config_version)
                WHERE device_id=?""",
                (_now(),client_ip,reported_pending,int(blocker_enabled) if blocker_enabled is not None else None,
                 config_version,device_id))
        self.prune_retention()
        return result

    def events(self, device_id=None, start=None, end=None, limit=5000, types=None, sample=False):
        self.prune_retention()
        clauses, args = ["device_id IN (SELECT device_id FROM devices WHERE is_sample=?)"], [int(sample)]
        if device_id:
            clauses.append("device_id=?"); args.append(device_id)
        if start:
            clauses.append("timestamp>=?"); args.append(start)
        if end:
            clauses.append("timestamp<?"); args.append(end)
        if types:
            placeholders = ",".join("?" for _ in types)
            clauses.append(f"event_type IN ({placeholders})"); args.extend(types)
        tail = " LIMIT ?" if limit is not None else ""
        if limit is not None:
            args.append(min(max(int(limit),1),10000))
        with self._connect() as db:
            return [_event_row(row) for row in db.execute(
                f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY timestamp,event_id{tail}", args)]

    def summary(self, range_key="today", tz_name="UTC", device_id=None, start=None, end=None, attribution_seconds=120, sample=False):
        begin, finish = time_window(range_key,tz_name,start,end)
        context_begin = utc_iso((datetime.fromisoformat(begin.replace("Z","+00:00")) - timedelta(days=1)).isoformat()) if begin else None
        context_end = utc_iso((datetime.fromisoformat(finish.replace("Z","+00:00")) + timedelta(days=1)).isoformat()) if finish else None
        context_events = self.events(device_id,context_begin,context_end,limit=None,sample=sample)
        events = [e for e in context_events if (not begin or e["timestamp"] >= begin) and (not finish or e["timestamp"] < finish)]
        grouped = defaultdict(list)
        for event in context_events:
            grouped[event.get("device_id")].append(event)
        raw_apps, raw_phones = [], []
        for group in grouped.values():
            group_apps, group_phones = reconstruct(group)
            raw_apps.extend(group_apps)
            raw_phones.extend(group_phones)
        apps = [part for session in raw_apps if (part := _clip_session(session,begin,finish))]
        phones = [part for session in raw_phones if (part := _clip_session(session,begin,finish))]
        apps.sort(key=lambda session:session["start"])
        phones.sort(key=lambda session:session["start"])
        by_app = defaultdict(lambda: {"seconds":0,"launches":0,"longest_seconds":0,"first_use":None,"last_use":None})
        names = {}
        for event in events:
            if event["event_type"] == "app_foreground" and event["package_name"]:
                app = by_app[event["package_name"]]; app["launches"] += 1
                app["first_use"] = min(app["first_use"] or event["timestamp"],event["timestamp"])
                app["last_use"] = max(app["last_use"] or event["timestamp"],event["timestamp"])
                names[event["package_name"]] = event["app_name"] or event["package_name"]
        for session in apps:
            if session["package_name"]:
                app = by_app[session["package_name"]]
                names.setdefault(session["package_name"],session.get("app_name") or session["package_name"])
                app["seconds"] += session["seconds"]
                app["longest_seconds"] = max(app["longest_seconds"],session["seconds"])
        app_rows = [{"package_name": key,"app_name":names.get(key,key),**value,
                     "average_seconds":value["seconds"]/value["launches"] if value["launches"] else 0}
                    for key,value in by_app.items()]
        app_rows.sort(key=lambda row: (-row["seconds"],row["app_name"]))
        with self._connect() as db:
            registry = {row["package_name"]:row["icon_base64"] for row in db.execute(
                "SELECT package_name,icon_base64 FROM apps WHERE icon_base64 IS NOT NULL" +
                (" AND device_id=?" if device_id else ""), (device_id,) if device_id else ())}
        for row in app_rows:
            row["icon_base64"] = registry.get(row["package_name"])
        total = sum(row["seconds"] for row in app_rows)
        hour_usage = [0.0]*24
        daily_usage = defaultdict(float)
        heatmap = [[0.0]*24 for _ in range(7)]
        zone = _tz(tz_name)
        for session in apps:
            cursor = datetime.fromisoformat(session["start"].replace("Z","+00:00"))
            session_end = datetime.fromisoformat(session["end"].replace("Z","+00:00"))
            while cursor < session_end:
                local = cursor.astimezone(zone)
                next_minute = cursor.replace(second=0,microsecond=0) + timedelta(minutes=1)
                piece_end = min(session_end,next_minute)
                seconds = (piece_end-cursor).total_seconds()
                hour_usage[local.hour] += seconds
                daily_usage[local.date().isoformat()] += seconds
                heatmap[local.weekday()][local.hour] += seconds
                cursor = piece_end
        selected_by_device = defaultdict(list)
        for event in events:
            selected_by_device[event.get("device_id")].append(event)
        matches = [match for group in selected_by_device.values()
                   for match in notification_attribution(group,attribution_seconds)]
        count = Counter(e["event_type"] for e in events)
        notifications_by_app = Counter((e["app_name"] or e["package_name"] or "Unknown")
            for e in events if e["event_type"] == "notification_posted")
        notification_hourly = [0]*24
        for event in events:
            if event["event_type"] == "notification_posted":
                notification_hourly[datetime.fromisoformat(event["timestamp"].replace("Z","+00:00")).astimezone(zone).hour] += 1
        with self._connect() as db:
            if device_id:
                place_names = {row["cluster_key"]:row["label"] for row in db.execute(
                    "SELECT cluster_key,label FROM place_names WHERE device_id=?",(device_id,))}
            else:
                place_names = {}
        locations = location_breakdown(events,apps,place_names)
        battery_samples = [{"timestamp":e["timestamp"],"percent":e["metadata"].get("percent"),
                            "charging":e["metadata"].get("charging")}
                           for e in events if e["event_type"] == "battery"]
        patterns_by_device = [behavior_patterns(group,[app for app in apps if app.get("device_id")==device],zone)
                              for device,group in selected_by_device.items()]
        patterns = {"doomscroll_sessions":sum(p["doomscroll_sessions"] for p in patterns_by_device),
                    "doomscroll_threshold_minutes":20,
                    "rapid_switch_windows":sum(p["rapid_switch_windows"] for p in patterns_by_device),
                    "rapid_switch_threshold":{"opens":12,"minutes":10},
                    "late_night_seconds":sum(p["late_night_seconds"] for p in patterns_by_device),
                    "first_app":next((e["package_name"] for e in events if e["event_type"]=="app_foreground"),None)}
        return {"range":range_key,"timezone":tz_name,"source":"sample" if sample else "live","start":begin,"end":finish,
                "data_quality":{"truncated":False,"session_source":"derived from explicit events"},
                "event_count":len(events),"screen_time_seconds":total,"unlocks":count["unlock"],"notifications":count["notification_posted"],
                "phone_sessions":len(phones),"average_phone_session_seconds":sum(p["seconds"] for p in phones)/len(phones) if phones else 0,
                "longest_phone_session_seconds":max((p["seconds"] for p in phones),default=0),
                "first_unlock":next((e["timestamp"] for e in events if e["event_type"]=="unlock"),None),
                "last_activity":events[-1]["timestamp"] if events else None,
                "apps":app_rows,"hourly_usage_seconds":hour_usage,
                "daily_usage_seconds":[{"day":day,"seconds":value} for day,value in sorted(daily_usage.items())],
                "heatmap_weekday_hour_seconds":heatmap,
                "notification_attribution":{"window_seconds":attribution_seconds,"matched":len(matches),
                                            "response_rate":len(matches)/count["notification_posted"] if count["notification_posted"] else None,
                                            "average_latency_seconds":sum(m["latency_seconds"] for m in matches)/len(matches) if matches else None},
                "notifications_by_app":[{"app_name":name,"count":value} for name,value in notifications_by_app.most_common()],
                "notification_hourly":notification_hourly,
                "app_sessions":apps,"sessions":phones,"locations":locations,
                "battery_samples":battery_samples,"battery_exposure":battery_exposure(events,apps),
                "session_facts":session_facts(events,apps,phones),"patterns":patterns}

    def insights(self, tz_name="UTC", device_id=None, days=30, sample=False,
                 metric="notifications", operator=">=", threshold=100, outcome="screen_time"):
        from phone_tracker_insights import daily_facts, streaks_for_rules, conditional_comparison
        zone = _tz(tz_name)
        try:
            days = int(days)
        except (TypeError,ValueError) as exc:
            raise PhoneTrackerError("days must be an integer") from exc
        if not 7 <= days <= 90:
            raise PhoneTrackerError("days must be 7 to 90")
        today = datetime.now(zone).date()
        start = utc_iso(datetime.combine(today-timedelta(days=91),datetime.min.time(),zone).isoformat())
        events = self.events(device_id,start,None,limit=None,sample=sample)
        daily = daily_facts(events,tz_name)
        complete_days = {day:row for day,row in daily.items() if day < today.isoformat() and
                         day >= (today-timedelta(days=days)).isoformat()}
        with self._connect() as db:
            categories = {row["package_name"]:row["category"] for row in db.execute(
                "SELECT package_name,category FROM apps WHERE device_id=?",(device_id,))} if device_id else {}
        rule_streaks = streaks_for_rules(self.rules(device_id),daily,tz_name,categories,today) if device_id else []
        comparison = conditional_comparison(complete_days,metric,operator,threshold,outcome)
        trend = [{"day":day,"screen_time_seconds":row["screen_time_seconds"],
                  "unlocks":row["unlocks"],"notifications":row["notifications"],
                  "coverage":row["usage_signal"]} for day,row in sorted(daily.items())
                 if day >= (today-timedelta(days=days-1)).isoformat()]
        return {"timezone":tz_name,"days":days,"daily":trend,"streaks":rule_streaks,
                "comparison":comparison,"source":"sample" if sample else "live"}

    def delete_events(self, range_key, tz_name, start=None, end=None, sample=False):
        begin, finish = time_window(range_key,tz_name,start,end)
        if not begin or not finish:
            raise PhoneTrackerError("Use delete_all for all data")
        with self._connect() as db:
            cur = db.execute("""DELETE FROM events WHERE timestamp>=? AND timestamp<?
                AND device_id IN (SELECT device_id FROM devices WHERE is_sample=?)""",(begin,finish,int(sample)))
            return {"deleted":cur.rowcount}

    def delete_all(self):
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            db.execute("DELETE FROM sync_batches")
            db.execute("DELETE FROM external_conditions")
            db.execute("DELETE FROM place_names")
            db.execute("DELETE FROM devices")
            db.execute("UPDATE settings SET value_json='30' WHERE key='raw_notification_text_days'")
            db.execute("UPDATE settings SET value_json='null' WHERE key='usage_events_days'")
            db.execute("DELETE FROM settings WHERE key='last_retention_prune'")
            return {"deleted_events":count,"devices_revoked":True}

    def generate_sample(self, days=1, tz_name="UTC"):
        if days not in {1,7}:
            raise PhoneTrackerError("Sample supports one day or one week")
        zone = _tz(tz_name)
        sample_id = "00000000-0000-4000-8000-000000000001"
        labels = [("com.instagram.android","Instagram"),("com.android.chrome","Chrome"),
                  ("com.google.android.youtube","YouTube")]
        today = datetime.now(zone).date()
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO devices(device_id,label,token_hash,created_at,is_sample) VALUES(?,?,?,?,1)",
                       (sample_id,"Sample phone","",_now()))
            sample_rule = {"rule_id":"00000000-0000-4000-8000-000000000002","name":"Instagram under 45 min",
                           "target":"com.instagram.android","action":"block","enabled":True,
                           "when":{"metric":"app_usage_today","operator":">=","value":45,"unit":"minutes"}}
            db.execute("""INSERT OR IGNORE INTO rules(rule_id,device_id,name,target,enabled,definition_json,updated_at)
                VALUES(?,?,?,?,?,?,?)""",(sample_rule["rule_id"],sample_id,sample_rule["name"],sample_rule["target"],
                1,json.dumps(sample_rule),_now()))
            db.execute("""INSERT OR IGNORE INTO place_names(device_id,cluster_key,label) VALUES(?,?,?)""",
                       (sample_id,f"{sample_id}:{_cluster_key(52.2297,21.0122)}","Home"))
            for offset in range(days):
                day = today - timedelta(days=offset)
                base = datetime.combine(day,datetime.min.time(),zone)
                entries = [(8,0,"screen_on",None,None),(8,0,"battery",None,None),
                           (8,0,"location",None,None),(8,1,"unlock",None,None),
                           (9,0,"location",None,None)]
                for i, (package,name) in enumerate(labels):
                    hour = 8 + i * 3
                    entries.extend([(hour,3,"app_foreground",package,name),
                                    (hour,8,"notification_posted",package,name),
                                    (hour,38,"app_background",package,name)])
                entries.extend([(17,0,"block",labels[0][0],labels[0][1]),
                                (17,5,"override",labels[0][0],labels[0][1]),
                                (18,0,"location",None,None),(18,15,"screen_off",None,None),
                                (19,0,"location",None,None),(19,0,"battery",None,None)])
                for hour,minute,kind,package,name in entries:
                    stamp = utc_iso((base+timedelta(hours=hour,minutes=minute)).isoformat())
                    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL,f"sample:{day}:{hour}:{minute}:{kind}:{package}"))
                    metadata = {"sample":True}
                    if kind == "notification_posted": metadata["title"] = "Sample notification"
                    if kind == "location": metadata.update({"latitude":52.2297,"longitude":21.0122,"accuracy_m":100})
                    if kind == "battery": metadata.update({"percent":82 if hour==8 else 74,"charging":False})
                    db.execute("""INSERT OR IGNORE INTO events(event_id,device_id,timestamp,event_type,package_name,
                        app_name,metadata_json,received_at) VALUES(?,?,?,?,?,?,?,?)""",
                        (event_id,sample_id,stamp,kind,package,name,json.dumps(metadata),_now()))
                    if package and name:
                        db.execute("INSERT OR IGNORE INTO apps(device_id,package_name,app_name) VALUES(?,?,?)",(sample_id,package,name))
        return {"device_id":sample_id,"days":days,"source":"sample"}

    def clear_sample(self):
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM events WHERE device_id IN (SELECT device_id FROM devices WHERE is_sample=1)").fetchone()[0]
            db.execute("DELETE FROM external_conditions WHERE device_id IN (SELECT device_id FROM devices WHERE is_sample=1)")
            db.execute("DELETE FROM place_names WHERE device_id IN (SELECT device_id FROM devices WHERE is_sample=1)")
            db.execute("DELETE FROM devices WHERE is_sample=1")
            return {"deleted":count}
