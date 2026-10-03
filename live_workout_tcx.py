import hashlib
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


def _text(element, path, default=None):
    found = element.find(path) if element is not None else None
    if found is None or found.text is None:
        return default
    return found.text.strip()


def _number(value, cast=float):
    if value in (None, ""):
        return None
    return cast(value)


def _parse_timestamp(value, creator, mi_fitness_timezone):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("TCX activity has no Id timestamp")
    if creator.lower() == "mi fitness" and mi_fitness_timezone:
        local_value = raw.removesuffix("Z")
        parsed = datetime.fromisoformat(local_value)
        parsed = parsed.replace(tzinfo=ZoneInfo(mi_fitness_timezone))
    else:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1000)


def parse_tcx(data, source_name="workout.tcx", mi_fitness_timezone="Europe/Warsaw"):
    root = ElementTree.fromstring(data)
    creator = str(root.attrib.get("creator") or "").strip()
    activity = root.find(".//{*}Activity")
    if activity is None:
        raise ValueError("TCX file has no Activity")
    lap = activity.find("{*}Lap")
    if lap is None:
        raise ValueError("TCX activity has no Lap")

    external_id = _text(activity, "{*}Id")
    started_at = _parse_timestamp(external_id, creator, mi_fitness_timezone)
    duration = _number(_text(lap, "{*}TotalTimeSeconds"), float)
    active_calories = _number(_text(lap, "{*}Calories"), int)
    total_calories = _number(_text(activity, "{*}Calories"), int)
    avg_hr = _number(
        _text(lap, "{*}HeartRateBpm")
        or _text(lap, "{*}AverageHeartRateBpm/{*}Value"),
        int,
    )
    max_hr = _number(
        _text(lap, "{*}MaximumHeartRateBpm/{*}Value")
        or _text(lap, "{*}MaximumHeartRateBpm"),
        int,
    )
    samples = []
    for point in activity.findall(".//{*}Trackpoint"):
        point_time = _text(point, "{*}Time")
        heart_rate = _number(
            _text(point, "{*}HeartRateBpm/{*}Value")
            or _text(point, "{*}HeartRateBpm"),
            int,
        )
        if not point_time or heart_rate is None:
            continue
        samples.append(
            {
                "timestamp": _parse_timestamp(point_time, creator, mi_fitness_timezone),
                "heart_rate": heart_rate,
            }
        )

    stable_key = external_id or f"{source_name}:{started_at}"
    return {
        "id": f"tcx-{hashlib.sha256(stable_key.encode('utf-8')).hexdigest()[:20]}",
        "title": "Indoor cycling",
        "started_at": started_at,
        "status": "finished",
        "duration_seconds": duration,
        "active_calories": active_calories,
        "total_calories": total_calories,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "external_id": external_id,
        "source": f"{creator or 'TCX'} · TCX",
        "import_file": Path(source_name).name,
        "samples": samples,
        "data_quality": {
            "summary": "tcx",
            "max_hr": "tcx" if max_hr is not None else "unavailable",
            "samples": "tcx" if samples else "unavailable",
        },
    }


def read_tcx_source(path, mi_fitness_timezone="Europe/Warsaw"):
    source = Path(path)
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            return [
                parse_tcx(
                    archive.read(name),
                    source_name=name,
                    mi_fitness_timezone=mi_fitness_timezone,
                )
                for name in archive.namelist()
                if name.lower().endswith(".tcx") and not name.endswith("/")
            ]
    return [
        parse_tcx(
            source.read_bytes(),
            source_name=source.name,
            mi_fitness_timezone=mi_fitness_timezone,
        )
    ]
