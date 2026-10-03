"""Daily, device-local app access budgets backed by Reading and Cleaning.

The canonical books and cleaning actions stay in their own stores. This module
only persists policies, the Cleaning widget's daily target, and day snapshots.
"""

from __future__ import annotations

import json
import math
import statistics
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from phone_tracker import PhoneTrackerError, reconstruct, time_window

WARSAW = ZoneInfo("Europe/Warsaw")
SOURCES = ("reading", "cleaning")
RECOVERY_DAY_AFTER_ACTIONS = 10
FORMULAS = {"minimum", "average", "weighted", "all_or_nothing"}
PROTECTED = {"com.android.settings", "com.android.systemui", "com.miui.home",
             "com.cleaningdashboard.phonetracker", "com.android.dialer", "com.google.android.dialer"}


def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def reward_progress(values: list[tuple[float, float]], formula: str = "minimum") -> float:
    if not values:
        return 1.0
    progress = [clamp(value) for value, _ in values]
    if formula == "minimum":
        return min(progress)
    if formula == "all_or_nothing":
        return 1.0 if all(value >= 1.0 for value in progress) else 0.0
    if formula == "average":
        return sum(progress) / len(progress)
    if formula == "weighted":
        weight = sum(max(0.0, float(item[1])) for item in values)
        return sum(clamp(value) * max(0.0, float(item_weight)) for value, item_weight in values) / weight if weight else 0.0
    raise PhoneTrackerError("Unsupported reward formula")


def reduced_baseline(start: float, elapsed_days: int, mode: str, percentage: float,
                     fixed_minutes: float, floor: float) -> float:
    """Use the original snapshot for every day, avoiding cumulative rounding drift."""
    days = max(0, elapsed_days)
    if mode == "compound_percentage":
        value = start * ((1 - percentage / 100) ** days)
    elif mode == "fixed_minutes":
        value = start - fixed_minutes * days
    else:
        value = start
    return max(floor, value)


def extra_reading_bonus(read: int, target: int | None, settings: dict) -> tuple[int, float]:
    if not settings.get("enabled", True) or target is None or target <= 0 or read < target:
        return 0, 0.0
    extra = max(0, read - target)
    threshold = settings["pages_per_reward"]
    blocks = extra / threshold if settings.get("partial_rewards", False) else extra // threshold
    return extra, round(min(settings["daily_bonus_cap"], blocks * settings["minutes_per_reward"]), 4)


def default_policy(target: str = "com.instagram.android") -> dict:
    return {
        "policy_id": str(uuid.uuid4()), "target": target, "enabled": True,
        "baseline": {"mode": "automatic", "window_days": 7, "calculation": "average",
                     "manual_minutes": 50, "hard_max_minutes": None},
        "sources": {"reading": {"enabled": True, "weight": 50, "no_plan": "fulfilled"},
                    "cleaning": {"enabled": True, "weight": 50, "no_plan": "fulfilled"}},
        "formula": "minimum",
        "notifications": {"enabled": True, "minimum_increase": 1, "milestones_enabled": True,
                          "milestones": [25, 50, 75, 100], "debounce_seconds": 30,
                          "show_baseline": True, "show_reading": True, "show_cleaning": True,
                          "show_used": True, "show_remaining": True,
                          "extra_reading_enabled": True, "full_plan_enabled": True,
                          "reduction_enabled": False},
        "reduction": {"enabled": True, "start_source": "automatic", "manual_start_minutes": 50,
                      "type": "compound_percentage", "percentage_per_day": 10,
                      "fixed_minutes_per_day": 5, "floor_minutes": 15},
        "extra_reading": {"enabled": True, "pages_per_reward": 10,
                          "minutes_per_reward": 2, "daily_bonus_cap": 10,
                          "partial_rewards": False, "allow_above_base": True,
                          "standalone_target_pages": None},
        "session": {"max_minutes": 15, "cooldown_minutes": 20},
        "night": {"enabled": False, "from": "23:30", "until": "09:00"},
        "override": {"enabled": True, "duration_minutes": 5, "cooldown_minutes": 60,
                     "max_per_day": 1},
        "unused_rollover": False,
    }


def validate_policy(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise PhoneTrackerError("App access policy must be an object")
    policy = default_policy(str(raw.get("target") or ""))
    target = policy["target"]
    if not target or len(target) > 256 or target in PROTECTED or not all(part for part in target.split(".")):
        raise PhoneTrackerError("Invalid or protected target app")
    policy["enabled"] = bool(raw.get("enabled", True))
    baseline = raw.get("baseline") or {}
    if baseline.get("mode", "automatic") not in {"automatic", "manual"}:
        raise PhoneTrackerError("Invalid baseline mode")
    if baseline.get("window_days", 7) not in {7, 14, 30}:
        raise PhoneTrackerError("Baseline window must be 7, 14, or 30 days")
    if baseline.get("calculation", "average") not in {"average", "median"}:
        raise PhoneTrackerError("Invalid baseline calculation")
    policy["baseline"].update(baseline)
    for key in ("manual_minutes", "hard_max_minutes"):
        value = policy["baseline"].get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1440):
            raise PhoneTrackerError(f"Invalid {key}")
    sources = raw.get("sources") or {}
    if not isinstance(sources, dict) or any(key not in SOURCES for key in sources):
        raise PhoneTrackerError("Unsupported reward source")
    for key in SOURCES:
        settings = sources.get(key) or {}
        if not isinstance(settings, dict):
            raise PhoneTrackerError("Invalid reward source settings")
        if settings.get("no_plan", "fulfilled") not in {"fulfilled", "zero", "ignore"}:
            raise PhoneTrackerError("Invalid no-plan behavior")
        weight = settings.get("weight", 50)
        if not isinstance(weight, (int, float)) or not 0 <= weight <= 100:
            raise PhoneTrackerError("Invalid reward source weight")
        policy["sources"][key].update(settings)
    if raw.get("formula", "minimum") not in FORMULAS:
        raise PhoneTrackerError("Invalid reward formula")
    policy["formula"] = raw.get("formula", "minimum")
    for section in ("notifications", "session", "night", "override", "reduction", "extra_reading"):
        patch = raw.get(section) or {}
        if not isinstance(patch, dict):
            raise PhoneTrackerError(f"Invalid {section} settings")
        policy[section].update(patch)
    reduction = policy["reduction"]
    if reduction["start_source"] not in {"automatic", "manual"} or reduction["type"] not in {
            "compound_percentage", "fixed_minutes", "none"}:
        raise PhoneTrackerError("Invalid reduction plan")
    for key, lower, upper in (("manual_start_minutes", 1, 1440), ("percentage_per_day", 0, 99),
                              ("fixed_minutes_per_day", 0, 1440), ("floor_minutes", 1, 1440)):
        value = reduction.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper:
            raise PhoneTrackerError(f"Invalid reduction {key}")
    bonus = policy["extra_reading"]
    for key, lower, upper in (("pages_per_reward", 1, 10000), ("minutes_per_reward", 0.1, 1440),
                              ("daily_bonus_cap", 0, 1440)):
        value = bonus.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper
                or (key == "pages_per_reward" and not isinstance(value, int))):
            raise PhoneTrackerError(f"Invalid extra reading {key}")
    target_pages = bonus.get("standalone_target_pages")
    if target_pages is not None and (not isinstance(target_pages, int) or isinstance(target_pages, bool)
                                    or not 1 <= target_pages <= 10000):
        raise PhoneTrackerError("Invalid standalone reading target")
    note = policy["notifications"]
    if not 1 <= int(note["minimum_increase"]) <= 60 or not 0 <= int(note["debounce_seconds"]) <= 300:
        raise PhoneTrackerError("Invalid notification threshold")
    if not isinstance(note["milestones"], list) or any(not isinstance(x, int) or not 1 <= x <= 100 for x in note["milestones"]):
        raise PhoneTrackerError("Invalid notification milestones")
    if not 1 <= int(policy["session"]["max_minutes"]) <= 240 or not 0 <= int(policy["session"]["cooldown_minutes"]) <= 1440:
        raise PhoneTrackerError("Invalid session limits")
    if not 1 <= int(policy["override"]["duration_minutes"]) <= 60 or not 0 <= int(policy["override"]["cooldown_minutes"]) <= 1440 or not 0 <= int(policy["override"]["max_per_day"]) <= 50:
        raise PhoneTrackerError("Invalid override limits")
    for field in ("from", "until"):
        try:
            time.fromisoformat(policy["night"][field])
        except (TypeError, ValueError) as exc:
            raise PhoneTrackerError("Night rule needs HH:MM times") from exc
    policy["policy_id"] = str(raw.get("policy_id") or policy["policy_id"])
    try:
        uuid.UUID(policy["policy_id"])
    except ValueError as exc:
        raise PhoneTrackerError("policy_id must be a UUID") from exc
    return policy


class RewardSource:
    id = ""
    label = ""

    def snapshot(self, day: str, settings: dict) -> dict:
        raise NotImplementedError

    def result(self, current: int, target: int | None, settings: dict, updated_at: str | None = None) -> dict:
        if target is None:
            progress, available = 0.0, False
        elif target <= 0:
            behavior = settings.get("no_plan", "fulfilled")
            progress, available = (0.0 if behavior == "zero" else 1.0), behavior != "ignore"
        else:
            progress, available = clamp(current / target), True
        return {"id": self.id, "label": self.label, "progress": progress,
                "current_value": current, "target_value": target, "unit": "pages" if self.id == "reading" else "tasks",
                "updated_at": updated_at, "available": available}


class ReadingProgressSource(RewardSource):
    id, label = "reading", "Reading"

    def __init__(self, reading_store):
        self.store = reading_store

    def snapshot(self, day: str, settings: dict) -> dict:
        state = self.store.state()
        stats = state["dailyStats"]
        return self.result(int(stats["todayRead"]), int(stats["todayTarget"]), settings)


class CleaningProgressSource(RewardSource):
    id, label = "cleaning", "Cleaning"

    def __init__(self, cleaning_store, access_store):
        self.cleaning_store, self.access_store = cleaning_store, access_store

    def snapshot(self, day: str, settings: dict) -> dict:
        target = self.access_store.cleaning_target(day)
        current = self.cleaning_store.count_actions_for_day(self.access_store.apartment_id(), day)
        return self.result(current, target, settings)


class ExternalBooleanSource(RewardSource):
    id, label = "external", "External condition"

    def snapshot(self, day: str, settings: dict) -> dict:
        return self.result(int(bool(settings.get("value"))), 1, settings)


class MetricProgressSource(RewardSource):
    id, label = "metric", "Metric"

    def snapshot(self, day: str, settings: dict) -> dict:
        return self.result(int(settings.get("current", 0)), int(settings.get("target", 0)), settings)


class PhoneAccessStore:
    def __init__(self, tracker, reading_store, cleaning_store):
        self.tracker, self.reading_store, self.cleaning_store = tracker, reading_store, cleaning_store
        with tracker._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS app_access_policies(
                    policy_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, target TEXT NOT NULL,
                    config_json TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(device_id,target), FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS app_access_days(
                    device_id TEXT NOT NULL, target TEXT NOT NULL, day TEXT NOT NULL,
                    baseline_minutes INTEGER NOT NULL, baseline_source TEXT NOT NULL,
                    highest_unlocked INTEGER NOT NULL DEFAULT 0, state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL, PRIMARY KEY(device_id,target,day),
                    FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS app_access_cleaning_goals(
                    apartment_id TEXT NOT NULL, day TEXT NOT NULL, target INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, PRIMARY KEY(apartment_id,day));
                CREATE TABLE IF NOT EXISTS app_access_reduction_plans(
                    device_id TEXT NOT NULL, target TEXT NOT NULL, policy_id TEXT NOT NULL,
                    start_baseline_minutes REAL NOT NULL, start_date TEXT NOT NULL,
                    paused INTEGER NOT NULL DEFAULT 0, paused_at TEXT,
                    paused_cap_minutes REAL,
                    total_paused_days INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(device_id,target),
                    FOREIGN KEY(policy_id) REFERENCES app_access_policies(policy_id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS app_access_reward_events(
                    event_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, target TEXT NOT NULL,
                    policy_id TEXT NOT NULL, day TEXT NOT NULL, source TEXT NOT NULL,
                    threshold INTEGER NOT NULL, reward_minutes REAL NOT NULL,
                    created_at TEXT NOT NULL, sync_status TEXT NOT NULL DEFAULT 'local',
                    UNIQUE(policy_id,day,source,threshold));
                CREATE TABLE IF NOT EXISTS app_access_day_corrections(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
                    target TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
                    old_value REAL, new_value REAL, created_at TEXT NOT NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(app_access_reduction_plans)")}
            if "paused_cap_minutes" not in columns:
                db.execute("ALTER TABLE app_access_reduction_plans ADD COLUMN paused_cap_minutes REAL")

    @staticmethod
    def day(now: datetime | None = None) -> str:
        return (now or datetime.now(WARSAW)).astimezone(WARSAW).date().isoformat()

    def apartment_id(self) -> str:
        settings = self.cleaning_store.get_settings()
        return settings.get("activeApartmentId") or "aleja-pokoju6"

    def set_cleaning_target(self, apartment_id: str, day: str, target: int) -> None:
        self.cleaning_store.get_state(apartment_id)
        if target < 0 or target > 10000:
            raise PhoneTrackerError("Invalid cleaning target")
        with self.tracker._connect() as db:
            db.execute("""INSERT INTO app_access_cleaning_goals(apartment_id,day,target,updated_at)
                VALUES(?,?,?,?) ON CONFLICT(apartment_id,day) DO UPDATE SET
                target=excluded.target,updated_at=excluded.updated_at""",
                (apartment_id,day,target,datetime.now(timezone.utc).isoformat()))

    def cleaning_target(self, day: str) -> int | None:
        apartment_id = self.apartment_id()
        with self.tracker._connect() as db:
            row = db.execute("SELECT target FROM app_access_cleaning_goals WHERE apartment_id=? AND day=?",
                             (apartment_id,day)).fetchone()
        if not row:
            return None
        previous_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        if self.cleaning_store.count_actions_for_day(apartment_id,previous_day) >= RECOVERY_DAY_AFTER_ACTIONS:
            return 1
        return int(row[0])

    def policies(self, device_id: str) -> list[dict]:
        with self.tracker._connect() as db:
            rows = db.execute("SELECT config_json,version,updated_at FROM app_access_policies WHERE device_id=? ORDER BY target",
                              (device_id,)).fetchall()
        if not rows and any(item["device_id"] == device_id and not item["is_sample"] for item in self.tracker.devices()):
            self.save_policy(device_id, default_policy(), create_default=True)
            return self.policies(device_id)
        if any("reduction" not in json.loads(row[0]) or "extra_reading" not in json.loads(row[0]) for row in rows):
            for row in rows:
                raw = json.loads(row[0])
                if "reduction" not in raw or "extra_reading" not in raw:
                    self.save_policy(device_id, raw)
            return self.policies(device_id)
        return [{**json.loads(row[0]), "version": row[1], "updated_at": row[2]} for row in rows]

    def save_policy(self, device_id: str, raw: dict, create_default: bool = False) -> dict:
        policy = validate_policy(raw)
        with self.tracker._connect() as db:
            if not db.execute("SELECT 1 FROM devices WHERE device_id=? AND is_sample=0", (device_id,)).fetchone():
                raise PhoneTrackerError("Unknown device", 404)
            existing = db.execute("SELECT policy_id,version,config_json FROM app_access_policies WHERE device_id=? AND target=?",
                                  (device_id,policy["target"])).fetchone()
            if existing:
                policy["policy_id"] = existing["policy_id"]
            version = (existing["version"] + 1) if existing else 1
            updated_at = datetime.now(timezone.utc).isoformat()
            db.execute("""INSERT INTO app_access_policies(policy_id,device_id,target,config_json,version,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(device_id,target) DO UPDATE SET
                config_json=excluded.config_json,version=excluded.version,updated_at=excluded.updated_at""",
                (policy["policy_id"],device_id,policy["target"],json.dumps(policy),version,updated_at))
            if create_default and policy["target"] == "com.instagram.android":
                # Replace only the exact one-off Cleaning gate from the previous implementation.
                for row in db.execute("SELECT rule_id,definition_json FROM rules WHERE device_id=? AND target=?",
                                      (device_id,policy["target"])):
                    rule = json.loads(row["definition_json"])
                    if rule.get("when") == {"not":{"metric":"external:cleaning_done_today","operator":"==","value":True}}:
                        db.execute("DELETE FROM rules WHERE rule_id=?",(row["rule_id"],))
            if existing and policy["baseline"]["mode"] == "manual":
                old = json.loads(existing["config_json"])["baseline"]
                if old != policy["baseline"]:
                    baseline = int(policy["baseline"]["manual_minutes"])
                    db.execute("UPDATE app_access_days SET baseline_minutes=?,baseline_source='manual' WHERE device_id=? AND target=? AND day=?",
                               (baseline,device_id,policy["target"],self.day()))
        if policy["reduction"]["enabled"]:
            self._ensure_plan(device_id,policy)
        return {**policy,"version":version,"updated_at":updated_at}

    def _reference_baseline(self, device_id: str, policy: dict, day: str,
                            force_automatic: bool = False) -> tuple[float, str]:
        settings = policy["baseline"]
        if settings["mode"] == "manual" and not force_automatic:
            value, source = float(settings["manual_minutes"]), "manual"
        else:
            days = settings["window_days"]
            values, covered = self._usage_days(device_id,policy["target"],day,days)
            if covered < days:
                value, source = 50.0, f"temporary: {covered}/{days} covered days"
            else:
                value = max(1.0, float(statistics.median(values) if settings["calculation"] == "median"
                                       else statistics.mean(values)))
                source = f"{days}-day {settings['calculation']}"
        hard_max = settings.get("hard_max_minutes")
        return (min(value,float(hard_max)) if hard_max else value), source

    def _ensure_plan(self, device_id: str, policy: dict) -> dict:
        target = policy["target"]
        with self.tracker._connect() as db:
            row = db.execute("SELECT * FROM app_access_reduction_plans WHERE device_id=? AND target=?",
                             (device_id,target)).fetchone()
        if row:
            return dict(row)
        settings = policy["reduction"]
        today = self.day()
        baseline = (self._reference_baseline(device_id,policy,today,force_automatic=True)[0]
                    if settings["start_source"] == "automatic" else float(settings["manual_start_minutes"]))
        now = datetime.now(timezone.utc).isoformat()
        with self.tracker._connect() as db:
            db.execute("""INSERT OR IGNORE INTO app_access_reduction_plans
                (device_id,target,policy_id,start_baseline_minutes,start_date,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""",(device_id,target,policy["policy_id"],baseline,today,now,now))
            return dict(db.execute("SELECT * FROM app_access_reduction_plans WHERE device_id=? AND target=?",
                                   (device_id,target)).fetchone())

    def plan_action(self, device_id: str, target: str, action: str) -> dict:
        policy = next((item for item in self.policies(device_id) if item["target"] == target),None)
        if not policy:
            raise PhoneTrackerError("Unknown access rule",404)
        if action not in {"pause","resume","restart"}:
            raise PhoneTrackerError("Invalid reduction action")
        plan = self._ensure_plan(device_id,policy)
        today = self.day()
        now = datetime.now(timezone.utc).isoformat()
        with self.tracker._connect() as db:
            if action == "pause" and not plan["paused"]:
                frozen = self._plan_state(plan,policy["reduction"],today)["effective_base_cap_minutes"]
                db.execute("""UPDATE app_access_reduction_plans SET paused=1,paused_at=?,
                    paused_cap_minutes=?,updated_at=? WHERE device_id=? AND target=?""",
                    (today,frozen,now,device_id,target))
            elif action == "resume" and plan["paused"]:
                paused_days = max(0,(date.fromisoformat(today)-date.fromisoformat(plan["paused_at"])).days)
                db.execute("""UPDATE app_access_reduction_plans SET paused=0,paused_at=NULL,paused_cap_minutes=NULL,
                    total_paused_days=total_paused_days+?,updated_at=? WHERE device_id=? AND target=?""",
                    (paused_days,now,device_id,target))
            elif action == "restart":
                settings = policy["reduction"]
                baseline = (self._reference_baseline(device_id,policy,today,force_automatic=True)[0]
                            if settings["start_source"] == "automatic" else float(settings["manual_start_minutes"]))
                db.execute("""UPDATE app_access_reduction_plans SET start_baseline_minutes=?,start_date=?,
                    paused=0,paused_at=NULL,paused_cap_minutes=NULL,total_paused_days=0,updated_at=? WHERE device_id=? AND target=?""",
                    (baseline,today,now,device_id,target))
            db.execute("UPDATE app_access_policies SET version=version+1,updated_at=? WHERE device_id=? AND target=?",
                       (now,device_id,target))
        return self.state(device_id,{**policy,"version":policy["version"]+1})

    def _usage_days(self, device_id: str, target: str, day: str, days: int) -> tuple[list[float], int]:
        start_day = date.fromisoformat(day) - timedelta(days=days)
        begin, end = time_window("custom", "Europe/Warsaw", start_day.isoformat(),
                                 (date.fromisoformat(day)-timedelta(days=1)).isoformat())
        context = (datetime.fromisoformat(begin.replace("Z","+00:00"))-timedelta(days=1)).isoformat()
        events = self.tracker.events(device_id,context,end,limit=None)
        covered = set()
        for event in events:
            if event["event_type"] in {"app_foreground","app_background","screen_on","screen_off","unlock"}:
                local = datetime.fromisoformat(event["timestamp"].replace("Z","+00:00")).astimezone(WARSAW).date()
                if start_day <= local < date.fromisoformat(day):
                    covered.add(local.isoformat())
        sessions, _ = reconstruct(events)
        daily = []
        for offset in range(days):
            current = start_day + timedelta(days=offset)
            start = datetime.combine(current,time.min,tzinfo=WARSAW).astimezone(timezone.utc)
            finish = datetime.combine(current+timedelta(days=1),time.min,tzinfo=WARSAW).astimezone(timezone.utc)
            seconds = sum(max(0,(min(finish,datetime.fromisoformat(item["end"].replace("Z","+00:00"))) -
                                 max(start,datetime.fromisoformat(item["start"].replace("Z","+00:00")))).total_seconds())
                          for item in sessions if item.get("package_name") == target)
            daily.append(seconds/60)
        return daily, len(covered)

    def _baseline(self, device_id: str, policy: dict, day: str) -> tuple[int,str]:
        value, source = self._reference_baseline(device_id,policy,day)
        return max(1,math.floor(value+0.5)), source

    @staticmethod
    def _plan_state(plan: dict, settings: dict, day: str) -> dict:
        start = date.fromisoformat(plan["start_date"])
        current = date.fromisoformat(day)
        paused_days = max(0,(current-date.fromisoformat(plan["paused_at"])).days) if plan["paused"] else 0
        elapsed = max(0,(current-start).days-int(plan["total_paused_days"])-paused_days)
        floor = float(settings["floor_minutes"])
        calculated = reduced_baseline(float(plan["start_baseline_minutes"]),elapsed,settings["type"],
                                float(settings["percentage_per_day"]),float(settings["fixed_minutes_per_day"]),floor)
        base = float(plan["paused_cap_minutes"]) if plan["paused"] and plan.get("paused_cap_minutes") is not None else calculated
        def forecast(offset: int) -> int:
            value = base if plan["paused"] else reduced_baseline(
                float(plan["start_baseline_minutes"]),elapsed+offset,settings["type"],
                float(settings["percentage_per_day"]),float(settings["fixed_minutes_per_day"]),floor)
            return math.floor(value+0.5)
        start_value = float(plan["start_baseline_minutes"])
        floor_day = None
        if start_value <= floor:
            floor_day = 0
        elif settings["type"] == "compound_percentage" and 0 < settings["percentage_per_day"] < 100:
            floor_day = math.ceil(math.log(floor/start_value)/math.log(1-settings["percentage_per_day"]/100))
        elif settings["type"] == "fixed_minutes" and settings["fixed_minutes_per_day"] > 0:
            floor_day = math.ceil((start_value-floor)/settings["fixed_minutes_per_day"])
        estimated = ((start+timedelta(days=floor_day+int(plan["total_paused_days"]))).isoformat()
                     if floor_day is not None and not plan["paused"] else None)
        return {"enabled":True,"start_baseline_minutes":round(start_value,4),"start_date":plan["start_date"],
                "day":elapsed,"paused":bool(plan["paused"]),"paused_at":plan["paused_at"],
                "total_paused_days":int(plan["total_paused_days"]),"floor_reached":base <= floor+1e-8,
                "effective_base_cap_minutes":round(base,4),"estimated_floor_date":estimated,
                "forecast":{"yesterday":forecast(-1) if elapsed > 0 else forecast(0),
                            "today":forecast(0),"tomorrow":forecast(1),
                            "plus_3_days":forecast(3),"plus_7_days":forecast(7),"floor":floor}}

    def _used_minutes(self, device_id: str, target: str, day: str) -> float:
        summary = self.tracker.summary("custom","Europe/Warsaw",device_id,start=day,end=day)
        return next((row["seconds"]/60 for row in summary["apps"] if row["package_name"] == target),0.0)

    def state(self, device_id: str, policy: dict, day: str | None = None) -> dict:
        day = day or self.day()
        with self.tracker._connect() as db:
            row = db.execute("SELECT * FROM app_access_days WHERE device_id=? AND target=? AND day=?",
                             (device_id,policy["target"],day)).fetchone()
        previous = json.loads(row["state_json"]) if row else {}
        if row:
            reference, source = row["baseline_minutes"], row["baseline_source"]
            highest = row["highest_unlocked"]
        else:
            reference, source = self._baseline(device_id,policy,day)
            highest = 0
        sources = {}
        if day == self.day():
            implementations = {"reading":ReadingProgressSource(self.reading_store),
                               "cleaning":CleaningProgressSource(self.cleaning_store,self)}
            for key in SOURCES:
                sources[key] = implementations[key].snapshot(day,policy["sources"][key])
        elif row:
            sources = previous.get("sources",{})
        else:
            sources = {key:{"id":key,"progress":0,"current_value":0,"target_value":None,
                            "available":False} for key in SOURCES}
        active = [(value["progress"],policy["sources"][key]["weight"])
                  for key,value in sources.items() if policy["sources"][key]["enabled"] and value["available"]]
        unknown = any(policy["sources"][key]["enabled"] and not value["available"] and
                      value["target_value"] is None for key,value in sources.items())
        progress = 0.0 if unknown else reward_progress(active,policy["formula"])
        historical = self._reference_baseline(device_id,policy,day,force_automatic=True)[0] if day == self.day() else previous.get(
            "historical_baseline_minutes",reference)
        plan = self._ensure_plan(device_id,policy) if policy["reduction"]["enabled"] else None
        plan_state = self._plan_state(plan,policy["reduction"],day) if plan else {
            "enabled":False,"start_baseline_minutes":reference,"day":0,"paused":False,
            "effective_base_cap_minutes":reference,"floor_reached":False,
            "forecast":{"today":reference,"tomorrow":reference,"plus_3_days":reference,
                        "plus_7_days":reference,"floor":policy["reduction"]["floor_minutes"]}}
        base_cap_exact = float(plan_state["effective_base_cap_minutes"])
        base_cap = math.floor(base_cap_exact+0.5)
        normal = math.floor(base_cap*progress+1e-9)
        reading = sources.get("reading",{})
        reading_target = reading.get("target_value")
        if not reading_target:
            reading_target = policy["extra_reading"].get("standalone_target_pages")
        extra_pages, bonus = extra_reading_bonus(int(reading.get("current_value") or 0),reading_target,
                                                 policy["extra_reading"])
        if not policy["extra_reading"]["allow_above_base"]:
            bonus = min(bonus,max(0,base_cap-normal))
        total = round(normal+bonus,4)
        used = self._used_minutes(device_id,policy["target"],day)
        effective = max(total,round(used,4))
        target_snapshot = previous.get("reading_target_snapshot") or reading_target
        state = {"day":day,"baseline_minutes":math.floor(base_cap+0.5),"baseline_source":source,
                 "reference_baseline_minutes":plan_state["start_baseline_minutes"],
                 "historical_baseline_minutes":round(historical,4),
                 "effective_base_cap_minutes":base_cap,
                 "effective_base_cap_exact_minutes":round(base_cap_exact,4),"reduction_plan":plan_state,
                 "progress":progress,"sources":sources,"normal_unlocked_minutes":normal,
                 "extra_reading_pages":extra_pages,"extra_reading_bonus_minutes":bonus,
                 "reading_target_snapshot":target_snapshot,"reading_target_current":reading_target,
                 "total_unlocked_minutes":total,"unlocked_minutes":total,
                 "effective_unlocked_minutes":effective,"used_minutes":round(used,2),
                 "remaining_minutes":max(0,round(total-used,2)),
                 "highest_unlocked_minutes":max(highest,total),"updated_at":datetime.now(timezone.utc).isoformat()}
        if day == self.day():
            with self.tracker._connect() as db:
                old_target = previous.get("reading_target_current")
                if old_target is not None and old_target != reading_target:
                    db.execute("""INSERT INTO app_access_day_corrections
                        (device_id,target,day,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?,?)""",
                        (device_id,policy["target"],day,"reading_target",old_target,reading_target,state["updated_at"]))
                old_bonus = previous.get("extra_reading_bonus_minutes")
                if old_bonus is not None and bonus < old_bonus:
                    db.execute("""INSERT INTO app_access_day_corrections
                        (device_id,target,day,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?,?)""",
                        (device_id,policy["target"],day,"bonus_rollback",old_bonus,bonus,state["updated_at"]))
                if policy["extra_reading"]["enabled"] and reading_target and reading_target > 0:
                    step = int(policy["extra_reading"]["pages_per_reward"])
                    cap = float(policy["extra_reading"]["daily_bonus_cap"])
                    count = min(extra_pages//step, math.ceil(cap/float(policy["extra_reading"]["minutes_per_reward"])))
                    for block in range(1,count+1):
                        threshold = block*step
                        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                            f"phone-access:{policy['policy_id']}:{day}:reading_extra_pages:{threshold}"))
                        db.execute("""INSERT OR IGNORE INTO app_access_reward_events
                            (event_id,device_id,target,policy_id,day,source,threshold,reward_minutes,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?)""",
                            (event_id,device_id,policy["target"],policy["policy_id"],day,
                             "reading_extra_pages",threshold,
                             min(float(policy["extra_reading"]["minutes_per_reward"]),
                                 max(0,cap-(block-1)*float(policy["extra_reading"]["minutes_per_reward"]))),
                             state["updated_at"]))
                db.execute("""INSERT INTO app_access_days(device_id,target,day,baseline_minutes,baseline_source,
                    highest_unlocked,state_json,updated_at) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(device_id,target,day) DO UPDATE SET highest_unlocked=MAX(highest_unlocked,excluded.highest_unlocked),
                    state_json=excluded.state_json,updated_at=excluded.updated_at""",
                    (device_id,policy["target"],day,reference,source,max(highest,total),json.dumps(state),state["updated_at"]))
        return state

    def config(self, device_id: str) -> dict:
        policies = self.policies(device_id)
        return {"config_id": str(uuid.uuid5(uuid.NAMESPACE_URL,f"phone-access:{device_id}")),
                "version":sum(item["version"] for item in policies),
                "updated_at":max((item["updated_at"] for item in policies),default=None),
                "policies":[{**item,"state":self.state(device_id,item)} for item in policies]}

    def overview(self, device_id: str) -> dict:
        return self.config(device_id)

    def history(self, device_id: str, target: str, days: int = 30) -> list[dict]:
        policy = next((item for item in self.policies(device_id) if item["target"] == target),None)
        if policy:
            self.state(device_id,policy)
        with self.tracker._connect() as db:
            rows = db.execute("""SELECT day,state_json,baseline_minutes FROM app_access_days
                WHERE device_id=? AND target=? ORDER BY day DESC LIMIT ?""",
                (device_id,target,max(1,min(days,365)))).fetchall()
        result = []
        for row in rows:
            snapshot = json.loads(row["state_json"])
            used = round(self._used_minutes(device_id,target,row["day"]),2)
            start,end = time_window("custom","Europe/Warsaw",row["day"],row["day"])
            events = self.tracker.events(device_id,start,end,limit=None,types={"block","override"})
            relevant = [item for item in events if item["package_name"] == target]
            with self.tracker._connect() as db:
                rewards = db.execute("""SELECT event_id,source,threshold,reward_minutes,created_at
                    FROM app_access_reward_events WHERE device_id=? AND target=? AND day=? ORDER BY threshold""",
                    (device_id,target,row["day"])).fetchall()
                corrections = db.execute("""SELECT kind,old_value,new_value,created_at
                    FROM app_access_day_corrections WHERE device_id=? AND target=? AND day=? ORDER BY id""",
                    (device_id,target,row["day"])).fetchall()
            result.append({**snapshot,"used_minutes":used,
                           "blocked_attempts":sum(item["event_type"]=="block" for item in relevant),
                           "override_count":sum(item["event_type"]=="override" for item in relevant),
                           "override_minutes":sum(float(item.get("metadata",{}).get("minutes",0)) for item in relevant
                                                  if item["event_type"]=="override"),
                           "reward_events":[dict(item) for item in rewards],
                           "corrections":[dict(item) for item in corrections],
                           "remaining_minutes_at_day_end":max(0,round(snapshot["unlocked_minutes"]-used,2)),
                           "unused_minutes":max(0,round(snapshot["unlocked_minutes"]-used,2))})
        return result
