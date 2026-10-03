import copy
import json
from datetime import date
from pathlib import Path


ZONE_KEYS = ("light", "intensive", "aerobic", "anaerobic", "vo2max")
WORKOUT_TYPES = {"recovery", "base", "tempo", "intervals", "long", "rest"}
WEEK_META = (
    ("Tydzień 1", "Adaptacja", 0, 7),
    ("Tydzień 2", "Objętość", 7, 14),
    ("Tydzień 3", "Szczyt", 14, 21),
    ("Tydzień 4", "Deload", 21, 28),
    ("Wyjazd", "Reset", 28, 30),
    ("Nowy blok · Tydzień 1", "Objętość aerobowa", 30, 37),
    ("Nowy blok · Tydzień 2", "Progres objętości", 37, 44),
)


def _split_minutes(total, pieces):
    if total <= 0 or pieces <= 0:
        return []
    units = round(float(total) * 2)
    base, extra = divmod(units, pieces)
    return [(base + (1 if index < extra else 0)) / 2 for index in range(pieces)]


def build_intervals(workout):
    if workout["type"] == "rest":
        return []
    zones = workout["zones"]
    labels = {
        "light": "Rozgrzewka",
        "intensive": "Spokojne tempo",
        "aerobic": "Praca aerobowa",
        "anaerobic": "Mocny wysiłek",
        "vo2max": "VO₂ Max — opcjonalny limit",
    }
    if workout["type"] != "intervals":
        return [
            {"name": labels[key], "duration_minutes": zones[key], "target_zone": key}
            for key in ZONE_KEYS
            if zones[key] > 0
        ]

    intervals = []
    for key in ("light", "intensive"):
        if zones[key] > 0:
            intervals.append({"name": labels[key], "duration_minutes": zones[key], "target_zone": key})
    repetitions = 4
    aerobic_parts = _split_minutes(zones["aerobic"], repetitions)
    hard_parts = _split_minutes(zones["anaerobic"], repetitions)
    vo2_parts = _split_minutes(zones["vo2max"], repetitions)
    for index in range(repetitions):
        if hard_parts[index] > 0:
            intervals.append({
                "name": f"Interwał {index + 1}/4 — mocno",
                "duration_minutes": hard_parts[index],
                "target_zone": "anaerobic",
            })
        if index < len(vo2_parts) and vo2_parts[index] > 0:
            intervals.append({
                "name": f"Interwał {index + 1}/4 — VO₂ opcjonalnie",
                "duration_minutes": vo2_parts[index],
                "target_zone": "vo2max",
                "optional": True,
            })
        if aerobic_parts[index] > 0:
            intervals.append({
                "name": f"Regeneracja {index + 1}/4",
                "duration_minutes": aerobic_parts[index],
                "target_zone": "aerobic",
            })
    return intervals


class LiveWorkoutPlan:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        with self.path.open("r", encoding="utf-8") as handle:
            plan = json.load(handle)
        workouts = plan.get("workouts") or []
        if not workouts:
            raise ValueError("Live Workout plan must contain at least one day")
        dates = []
        for workout in workouts:
            workout_date = date.fromisoformat(workout["date"])
            dates.append(workout_date)
            if workout.get("type") not in WORKOUT_TYPES:
                raise ValueError(f"Invalid workout type for {workout['date']}")
            if set(workout.get("zones") or {}) != set(ZONE_KEYS):
                raise ValueError(f"Invalid HR zones for {workout['date']}")
            if sum(workout["zones"].values()) != workout["duration"]:
                raise ValueError(f"Zone total differs from duration for {workout['date']}")
        if dates != [date.fromordinal(dates[0].toordinal() + index) for index in range(len(dates))]:
            raise ValueError("Live Workout plan dates must be consecutive")
        if plan["start_date"] != dates[0].isoformat() or plan["end_date"] != dates[-1].isoformat():
            raise ValueError("Live Workout plan boundaries do not match workouts")
        return plan

    def response(self, day=None):
        plan = self.load()
        selected_date = str(day or date.today().isoformat())
        workouts = copy.deepcopy(plan["workouts"])
        current = next((item for item in workouts if item["date"] == selected_date), None)
        if current is None:
            current = next((item for item in workouts if item["type"] != "rest"), workouts[0])
        current["intervals"] = build_intervals(current)
        weeks = []
        for label, theme, start, end in WEEK_META:
            days = workouts[start:end]
            if not days:
                continue
            weeks.append({
                "label": label,
                "theme": theme,
                "start_date": days[0]["date"],
                "end_date": days[-1]["date"],
                "planned_minutes": sum(item["duration"] for item in days),
            })
        return {
            "plan_id": plan["id"],
            "plan_title": current["purpose"] if current["type"] == "rest" else f"{plan['title']} · {current['date']}",
            "total_duration_minutes": current["duration"],
            "target_zones": current["zones"],
            "intervals": current["intervals"],
            "current_workout": current,
            "schedule": workouts,
            "weeks": weeks,
            "summary": {
                "calendar_days": len(workouts),
                "training_days": sum(item["type"] != "rest" for item in workouts),
                "rest_days": sum(item["type"] == "rest" for item in workouts),
                "planned_minutes": sum(item["duration"] for item in workouts),
                "zone_minutes": {
                    key: sum(item["zones"][key] for item in workouts) for key in ZONE_KEYS
                },
            },
        }
