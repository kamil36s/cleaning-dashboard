"""Descriptive daily facts, streaks, and conditional comparisons from raw events."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from phone_tracker import PhoneTrackerError, reconstruct


def _instant(value):
    return datetime.fromisoformat(value.replace("Z","+00:00"))


def daily_facts(events, tz_name):
    zone = ZoneInfo(tz_name)
    by_day = defaultdict(lambda: {"event_count":0,"usage_signal":False,"screen_time_seconds":0.0,
                                 "unlocks":0,"notifications":0,"app_seconds":defaultdict(float),
                                 "app_launches":defaultdict(int)})
    grouped = defaultdict(list)
    for event in events:
        grouped[event.get("device_id")].append(event)
        day = _instant(event["timestamp"]).astimezone(zone).date().isoformat()
        row = by_day[day]
        row["event_count"] += 1
        kind = event["event_type"]
        if kind in {"app_background","screen_off","unlock"}:
            row["usage_signal"] = True
        if kind == "unlock":
            row["unlocks"] += 1
        elif kind == "notification_posted":
            row["notifications"] += 1
        elif kind == "app_foreground" and event.get("package_name"):
            row["app_launches"][event["package_name"]] += 1
    for group in grouped.values():
        sessions,_ = reconstruct(group)
        for session in sessions:
            if not session.get("package_name"):
                continue
            cursor,end = _instant(session["start"]),_instant(session["end"])
            while cursor < end:
                local = cursor.astimezone(zone)
                next_day = datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),zone).astimezone(timezone.utc)
                piece_end = min(end,next_day)
                if piece_end <= cursor:
                    break
                seconds = (piece_end-cursor).total_seconds()
                row = by_day[local.date().isoformat()]
                row["screen_time_seconds"] += seconds
                row["app_seconds"][session["package_name"]] += seconds
                cursor = piece_end
    return {day:{**row,"app_seconds":dict(row["app_seconds"]),
                 "app_launches":dict(row["app_launches"])} for day,row in by_day.items()}


def streaks_for_rules(rules, daily, zone, category_by_package=None, today=None):
    category_by_package = category_by_package or {}
    today = today or datetime.now(ZoneInfo(zone)).date()
    results = []
    for rule in rules:
        if not rule.get("enabled",True):
            continue
        condition = rule.get("when",{})
        metric = condition.get("metric")
        if metric not in {"app_usage_today","app_launches_today","category_usage_today","category_launches_today"}:
            continue
        if condition.get("operator") != ">=":
            continue
        target,threshold = rule["target"],condition["value"]
        length = 0
        stopped = "no_coverage"
        for offset in range(1,91):
            day = (today-timedelta(days=offset)).isoformat()
            row = daily.get(day)
            if not row or not row["usage_signal"]:
                stopped = "no_coverage"
                break
            if metric == "app_usage_today":
                observed = row["app_seconds"].get(target,0)/60
            elif metric == "app_launches_today":
                observed = row["app_launches"].get(target,0)
            else:
                category = condition.get("category")
                source = row["app_seconds"] if metric == "category_usage_today" else row["app_launches"]
                observed = sum(value for package,value in source.items() if category_by_package.get(package)==category)
                if metric == "category_usage_today": observed /= 60
            if observed >= threshold:
                stopped = "limit_reached"
                break
            length += 1
        results.append({"rule_id":rule["rule_id"],"name":rule["name"],"days":length,
                        "through":(today-timedelta(days=1)).isoformat(),"stop_reason":stopped})
    return results


def _metric(row, name):
    if name == "screen_time": return row["screen_time_seconds"]/60
    if name == "notifications": return row["notifications"]
    if name == "unlocks": return row["unlocks"]
    if name.startswith("app_usage:"):
        return row["app_seconds"].get(name.split(":",1)[1],0)/60
    if name.startswith("app_launches:"):
        return row["app_launches"].get(name.split(":",1)[1],0)
    raise PhoneTrackerError("Unknown correlation metric")


def conditional_comparison(daily, metric, operator, threshold, outcome):
    if operator not in {">",">=","<","<="}:
        raise PhoneTrackerError("Unsupported comparison operator")
    try:
        threshold = float(threshold)
    except (TypeError,ValueError) as exc:
        raise PhoneTrackerError("Comparison threshold must be numeric") from exc
    empty = {"screen_time_seconds":0,"notifications":0,"unlocks":0,"app_seconds":{},"app_launches":{}}
    _metric(empty,metric)
    _metric(empty,outcome)
    selected,other = [],[]
    for row in daily.values():
        if not row["usage_signal"]:
            continue
        value = _metric(row,metric)
        outcome_value = _metric(row,outcome)
        match = {">":value>threshold,">=":value>=threshold,
                 "<":value<threshold,"<=":value<=threshold}[operator]
        (selected if match else other).append(outcome_value)
    return {"metric":metric,"operator":operator,"threshold":threshold,"outcome":outcome,
            "selected_days":len(selected),"other_days":len(other),
            "selected_mean":sum(selected)/len(selected) if selected else None,
            "other_mean":sum(other)/len(other) if other else None,
            "unit":"minutes" if outcome in {"screen_time"} or outcome.startswith("app_usage:") else "count",
            "quality":"descriptive association; not causal"}
