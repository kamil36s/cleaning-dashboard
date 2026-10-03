import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


ROOT = Path(__file__).resolve().parents[1]
SCALE_DATA_DIR = ROOT / "data" / "scale"
MEASUREMENTS_JSONL = SCALE_DATA_DIR / "scale_measurements.jsonl"
MEASUREMENTS_CSV = SCALE_DATA_DIR / "scale_measurements.csv"
CSV_FIELDS = [
    "timestamp",
    "address",
    "name",
    "rssi",
    "type",
    "weight_kg",
    "stable",
    "unit",
    "impedance",
    "raw_hex",
]


def local_tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Europe/Warsaw")
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def parse_body_timestamp(value):
    dt = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S%z")
    return dt.astimezone(local_tz()).replace(tzinfo=None).isoformat(timespec="milliseconds")


def parse_number(value):
    raw = str(value or "").strip()
    if not raw or raw.lower() == "null":
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def event_key(row):
    weight = row.get("weight_kg")
    try:
        weight = round(float(weight), 2)
    except (TypeError, ValueError):
        weight = ""
    return (str(row.get("timestamp") or ""), str(row.get("type") or ""), weight)


def sort_key(row):
    timestamp = str(row.get("timestamp") or "")
    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return datetime.min


def body_row_to_event(row, source_name):
    timestamp = parse_body_timestamp(row.get("time"))
    weight = parse_number(row.get("weight"))
    if weight is None:
        return None

    event = {
        "type": "BODY_CSV",
        "source": source_name,
        "weight_kg": round(weight, 2),
        "stable": True,
        "has_weight": True,
        "unit": "kg",
        "timestamp": timestamp,
        "address": None,
        "name": "BODY CSV",
        "rssi": None,
        "raw_hex": "",
        "source_timestamp": str(row.get("time") or "").strip(),
    }

    height = parse_number(row.get("height"))
    bmi = parse_number(row.get("bmi"))
    if height is not None:
        event["height_cm"] = height
    if bmi is not None:
        event["bmi"] = bmi
    return event


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp_path, path)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})
    os.replace(tmp_path, path)


def import_body_csv(source):
    source = Path(source).resolve()
    existing = load_jsonl(MEASUREMENTS_JSONL)
    seen = {event_key(row) for row in existing}
    imported = []

    with source.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            event = body_row_to_event(row, source.name)
            if not event:
                continue
            key = event_key(event)
            if key in seen:
                continue
            seen.add(key)
            imported.append(event)

    merged = sorted(existing + imported, key=sort_key)
    write_jsonl(MEASUREMENTS_JSONL, merged)
    write_csv(MEASUREMENTS_CSV, merged)
    return len(imported), len(merged)


def main():
    parser = argparse.ArgumentParser(description="Import BODY CSV weight history into dashboard scale data.")
    parser.add_argument("csv_path")
    args = parser.parse_args()
    imported, total = import_body_csv(args.csv_path)
    print(f"Imported {imported} BODY CSV rows. Total measurement rows: {total}.")


if __name__ == "__main__":
    main()
