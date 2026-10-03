import asyncio
import argparse
import csv
import json
import os
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bleak import BleakScanner


SCALE_MAC = "70:87:9E:AA:FB:CB"
DEFAULT_SCAN_SECONDS = 0
SCANNER_SESSION_SEC = 65
SCANNER_RETRY_SEC = 5
MEASUREMENT_SAVE_COOLDOWN_SEC = 15

UUID_WEIGHT_SCALE = "0000181d-0000-1000-8000-00805f9b34fb"
UUID_BODY_COMPOSITION = "0000181b-0000-1000-8000-00805f9b34fb"

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "scale"
RAW_LOG = DATA_DIR / "scale_raw.jsonl"
MEASUREMENTS_CSV = DATA_DIR / "scale_measurements.csv"
MEASUREMENTS_JSONL = DATA_DIR / "scale_measurements.jsonl"
LATEST_JSON = DATA_DIR / "latest.json"
SIGNAL_JSON = DATA_DIR / "signal.json"
SIGNAL_WRITE_INTERVAL_SEC = 60
REALISTIC_WEIGHT_MIN_KG = 30.0
REALISTIC_WEIGHT_MAX_KG = 300.0
CONSOLE_SUMMARY_INTERVAL_SEC = 5 * 60

last_saved_at = 0.0
last_signal_write = 0.0
console_stats = {
    "started_at": None,
    "packets": 0,
    "decoded_packets": 0,
    "stable_readings": 0,
    "saved_measurements": 0,
    "last_weight": None,
    "last_rssi": None,
}

SENSOR_MAC = "A4:C1:38:4D:C9:81"
SENSOR_ID = "desk"
UUID_BTHOME = "0000fcd2-0000-1000-8000-00805f9b34fb"

SENSOR_DATA_DIR = ROOT / "data" / "sensor"
SENSOR_LATEST_JSON = SENSOR_DATA_DIR / "latest.json"
SENSOR_READINGS_JSONL = SENSOR_DATA_DIR / "readings.jsonl"
SENSOR_HISTORY_COOLDOWN_SEC = 60

sensor_last_payload: bytes | None = None
sensor_last_history_at = 0.0


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def normalize_mac(address: str | None) -> str:
    return (address or "").upper()


def bytes_to_hex(data: bytes) -> str:
    return data.hex(" ")


_BTHOME_OBJ: dict[int, tuple[str, int, str]] = {
    # obj_id -> (field_name, byte_count, struct_fmt)
    0x00: ("packet_id",   1, "B"),
    0x01: ("battery_pct", 1, "B"),
    0x02: ("temp_raw",    2, "h"),   # s16, 0.01 °C
    0x03: ("hum_raw",     2, "H"),   # u16, 0.01 %
    0x0C: ("battery_mv",  2, "H"),   # u16, mV
}


def parse_bthome_v2(data: bytes) -> dict[str, Any] | None:
    """Decode a BTHome v2 service-data payload (UUID 0xFCD2, unencrypted).

    Returns a dict with temp_c, hum_pct and optionally battery_pct /
    battery_mv, or None if the payload is not a valid unencrypted v2 frame
    or lacks temperature + humidity.
    """
    if not data or len(data) < 3:
        return None
    dev_info = data[0]
    if dev_info & 0x01:          # bit 0 = encryption enabled
        return None
    version = (dev_info >> 5) & 0x07
    if version != 2:
        return None

    fields: dict[str, Any] = {}
    i = 1
    while i < len(data):
        obj_id = data[i]
        i += 1
        spec = _BTHOME_OBJ.get(obj_id)
        if spec is None:
            break
        name, byte_count, fmt = spec
        if i + byte_count > len(data):
            break
        raw = data[i: i + byte_count]
        i += byte_count
        val = struct.unpack_from("<" + fmt, raw)[0]
        fields[name] = val

    temp_raw = fields.get("temp_raw")
    hum_raw  = fields.get("hum_raw")
    if temp_raw is None or hum_raw is None:
        return None

    result: dict[str, Any] = {
        "temp_c":    round(temp_raw / 100.0, 2),
        "hum_pct":   round(hum_raw  / 100.0, 2),
    }
    if "battery_pct" in fields:
        result["battery_pct"] = fields["battery_pct"]
    if "battery_mv" in fields:
        result["battery_mv"] = fields["battery_mv"]
    if "packet_id" in fields:
        result["packet_id"] = fields["packet_id"]
    return result


def write_sensor_latest(reading: dict[str, Any]) -> None:
    """Atomically update data/sensor/latest.json."""
    SENSOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SENSOR_LATEST_JSON.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(reading, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, SENSOR_LATEST_JSON)


def handle_sensor_reading(reading: dict[str, Any]) -> None:
    """Persist the latest reading and, at most once per minute, append to history."""
    global sensor_last_history_at

    write_sensor_latest(reading)

    now = time.monotonic()
    if sensor_last_history_at and now - sensor_last_history_at < SENSOR_HISTORY_COOLDOWN_SEC:
        return

    SENSOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp":    reading["timestamp"],
        "sensor_id":    reading["sensor_id"],
        "temperature_c": reading["temp_c"],
        "humidity_percent": reading["hum_pct"],
    }
    if "battery_pct" in reading:
        row["battery_pct"] = reading["battery_pct"]
    if "battery_mv" in reading:
        row["battery_mv"] = reading["battery_mv"]

    with SENSOR_READINGS_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    sensor_last_history_at = now


def on_sensor_advertisement(device: Any, adv: Any) -> None:
    """Process a BTHome v2 advertisement from the env sensor."""
    global sensor_last_payload

    service_data = adv.service_data or {}
    raw = next(
        (
            value
            for uuid, value in service_data.items()
            if str(uuid).lower() == UUID_BTHOME
        ),
        None,
    )
    if not raw:
        return

    payload = bytes(raw)
    if payload == sensor_last_payload:
        return

    parsed = parse_bthome_v2(payload)
    if parsed is None:
        return

    ts = now_iso()
    reading: dict[str, Any] = {
        "timestamp": ts,
        "sensor_id": SENSOR_ID,
        "mac": SENSOR_MAC,
        "rssi": adv.rssi,
        "source": "BLE_BTHOME_V2",
        **parsed,
    }

    try:
        handle_sensor_reading(reading)
        sensor_last_payload = payload
    except Exception as exc:
        print(f"[sensor] write error: {exc}", flush=True)




def rssi_to_percent(rssi: int | float | None) -> int | None:
    if rssi is None:
        return None
    try:
        value = float(rssi)
    except (TypeError, ValueError):
        return None
    percent = (value - (-100.0)) / ((-50.0) - (-100.0)) * 100.0
    return max(0, min(100, round(percent)))


def is_realistic_weight_kg(value: Any) -> bool:
    try:
        weight_kg = float(value)
    except (TypeError, ValueError):
        return False
    return REALISTIC_WEIGHT_MIN_KG <= weight_kg <= REALISTIC_WEIGHT_MAX_KG


def unit_from_v1_flags(flags: int) -> str:
    if flags & (1 << 4):
        return "jin"
    if flags & (1 << 2):
        return "lb"
    if flags & (1 << 1):
        return "kg"
    return "unknown"


def convert_v1_weight_to_kg(weight_raw: int, unit: str) -> float | None:
    weight = weight_raw / 100.0
    if unit == "kg":
        return weight / 2.0
    if unit == "lb":
        return weight * 0.453592
    if unit == "jin":
        return weight * 0.6
    return None


def parse_weight_scale_181d(data: bytes) -> dict[str, Any] | None:
    if len(data) < 3:
        return None

    flags = data[0]
    has_weight = (flags & (1 << 7)) == 0
    stable = (flags & (1 << 5)) != 0
    unit = unit_from_v1_flags(flags)
    weight_raw = int.from_bytes(data[1:3], "little", signed=False)
    weight_kg = convert_v1_weight_to_kg(weight_raw, unit)

    if weight_kg is None:
        return None

    return {
        "type": "181D",
        "weight_kg": round(weight_kg, 2),
        "stable": stable,
        "has_weight": has_weight,
        "unit": unit,
        "flags": flags,
        "raw_weight": weight_raw,
    }


def parse_body_composition_181b(data: bytes) -> dict[str, Any] | None:
    if len(data) < 13:
        return None

    unit_code = data[0]
    status = data[1]
    has_impedance = (status & (1 << 1)) != 0
    stable = (status & (1 << 5)) != 0
    load_removed = (status & (1 << 7)) != 0
    impedance = int.from_bytes(data[9:11], "little", signed=False)
    weight_raw = int.from_bytes(data[11:13], "little", signed=False)

    if unit_code == 0x02:
        unit = "kg"
        weight_kg = weight_raw * 0.01 / 2.0
    elif unit_code == 0x03:
        unit = "lb"
        weight_kg = weight_raw * 0.01 * 0.453592
    else:
        unit = f"unknown:{unit_code}"
        weight_kg = None

    if weight_kg is None:
        return None

    return {
        "type": "181B",
        "weight_kg": round(weight_kg, 2),
        "stable": stable and not load_removed,
        "has_weight": not load_removed,
        "unit": unit,
        "flags": status,
        "raw_weight": weight_raw,
        "impedance": impedance if has_impedance else None,
        "has_impedance": has_impedance,
        "load_removed": load_removed,
    }


def parse_scale_service_data(uuid: str, data: bytes) -> dict[str, Any] | None:
    uuid = uuid.lower()
    if uuid == UUID_WEIGHT_SCALE:
        return parse_weight_scale_181d(data)
    if uuid == UUID_BODY_COMPOSITION:
        return parse_body_composition_181b(data)
    return None


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_measurement_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    fields = [
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
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field) for field in fields})


def append_measurement_jsonl(path: Path, row: dict[str, Any]) -> None:
    append_jsonl(path, row)


def write_latest_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    payload = {
        "ok": True,
        "timestamp": row.get("timestamp"),
        "address": row.get("address"),
        "name": row.get("name"),
        "rssi": row.get("rssi"),
        "type": row.get("type"),
        "weight_kg": row.get("weight_kg"),
        "stable": bool(row.get("stable")),
        "has_weight": bool(row.get("has_weight", True)),
        "unit": row.get("unit"),
        "impedance": row.get("impedance"),
        "raw_hex": row.get("raw_hex"),
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def write_signal_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    payload = {
        "ok": True,
        "timestamp": row.get("timestamp"),
        "address": row.get("address"),
        "name": row.get("name"),
        "rssi": row.get("rssi"),
        "signal_percent": rssi_to_percent(row.get("rssi")),
        "source": "BLE_ADV",
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def maybe_update_signal(row: dict[str, Any]) -> None:
    global last_signal_write

    current = time.monotonic()
    if last_signal_write and current - last_signal_write < SIGNAL_WRITE_INTERVAL_SEC:
        return
    write_signal_json(SIGNAL_JSON, row)
    last_signal_write = current


def record_console_packet(
    decoded: bool,
    stable_readings: int = 0,
    saved_measurements: int = 0,
    last_weight: float | None = None,
    last_rssi: int | None = None,
    now: float | None = None,
) -> str | None:
    current = time.monotonic() if now is None else float(now)
    if console_stats["started_at"] is None:
        console_stats["started_at"] = current
    console_stats["packets"] += 1
    console_stats["decoded_packets"] += int(decoded)
    console_stats["stable_readings"] += max(0, int(stable_readings))
    console_stats["saved_measurements"] += max(0, int(saved_measurements))
    if last_weight is not None:
        console_stats["last_weight"] = float(last_weight)
    if last_rssi is not None:
        console_stats["last_rssi"] = int(last_rssi)

    elapsed = current - console_stats["started_at"]
    if elapsed < CONSOLE_SUMMARY_INTERVAL_SEC:
        return None

    snapshot = dict(console_stats)
    console_stats.update({
        "started_at": current,
        "packets": 0,
        "decoded_packets": 0,
        "stable_readings": 0,
        "saved_measurements": 0,
        "last_weight": None,
        "last_rssi": None,
    })
    decoded_rate = snapshot["decoded_packets"] / snapshot["packets"] * 100
    elapsed_minutes = max(1, round(elapsed / 60))
    last_weight_text = (
        f"{snapshot['last_weight']:.2f}kg"
        if snapshot["last_weight"] is not None
        else "-"
    )
    last_rssi_text = snapshot["last_rssi"] if snapshot["last_rssi"] is not None else "-"
    message = (
        f"BLE summary {elapsed_minutes}m | packets={snapshot['packets']} | "
        f"decoded={decoded_rate:.1f}% | stable={snapshot['stable_readings']} | "
        f"saved={snapshot['saved_measurements']} | last={last_weight_text} | "
        f"RSSI={last_rssi_text}"
    )
    print(message)
    return message


def handle_measurement(row: dict[str, Any]) -> bool:
    global last_saved_at

    weight = row["weight_kg"]
    status = "STABLE" if row["stable"] else "moving"
    impedance = row.get("impedance")
    impedance_text = f", impedance={impedance}" if impedance is not None else ""
    summary = (
        f"{weight:.2f} kg {status} | RSSI {row['rssi']} | "
        f"{row['type']}{impedance_text}"
    )

    if not row["stable"] or not row.get("has_weight", True):
        return False
    if not is_realistic_weight_kg(weight):
        print(f"{summary} | ignored: outside realistic range")
        return False

    current = time.monotonic()
    if last_saved_at and current - last_saved_at < MEASUREMENT_SAVE_COOLDOWN_SEC:
        return False

    append_measurement_csv(MEASUREMENTS_CSV, row)
    append_measurement_jsonl(MEASUREMENTS_JSONL, row)
    write_latest_json(LATEST_JSON, row)
    write_signal_json(SIGNAL_JSON, row)
    last_saved_at = current
    return True


def callback(device, advertisement_data) -> None:
    addr = normalize_mac(device.address)

    if addr == normalize_mac(SENSOR_MAC):
        on_sensor_advertisement(device, advertisement_data)
        return

    if addr != normalize_mac(SCALE_MAC):
        return

    timestamp = now_iso()
    service_data = advertisement_data.service_data or {}
    manufacturer_data = advertisement_data.manufacturer_data or {}

    raw_row = {
        "timestamp": timestamp,
        "name": device.name,
        "address": device.address,
        "rssi": advertisement_data.rssi,
        "service_uuids": advertisement_data.service_uuids,
        "service_data": {uuid: bytes_to_hex(bytes(data)) for uuid, data in service_data.items()},
        "manufacturer_data": {
            str(key): bytes_to_hex(bytes(data)) for key, data in manufacturer_data.items()
        },
    }
    append_jsonl(RAW_LOG, raw_row)
    maybe_update_signal(raw_row)

    decoded = False
    stable_readings = 0
    saved_measurements = 0
    last_weight = None
    for uuid, data in service_data.items():
        payload = bytes(data)
        parsed = parse_scale_service_data(uuid, payload)
        if parsed is None:
            continue

        decoded = True
        stable_readings += int(parsed["stable"] and parsed.get("has_weight", True))
        last_weight = parsed["weight_kg"]
        saved_measurements += int(handle_measurement({
            **parsed,
            "timestamp": timestamp,
            "address": device.address,
            "name": device.name,
            "rssi": advertisement_data.rssi,
            "raw_hex": bytes_to_hex(payload),
        }))

    record_console_packet(
        decoded,
        stable_readings=stable_readings,
        saved_measurements=saved_measurements,
        last_weight=last_weight,
        last_rssi=advertisement_data.rssi,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Listen for Xiaomi Mi Scale 2 BLE readings.")
    parser.add_argument(
        "--seconds",
        type=int,
        default=DEFAULT_SCAN_SECONDS,
        help="How long to listen. Use 0 for continuous live mode.",
    )
    args = parser.parse_args()
    seconds = max(0, int(args.seconds or 0))

    duration = "continuously" if seconds == 0 else f"for {seconds} seconds"
    print(f"Listening for Mi Scale 2 {duration}.")
    print(f"Target MAC: {SCALE_MAC}")
    print("Stand on the scale and wait until the displayed result stabilizes.")
    print(f"Raw packets: {RAW_LOG}")
    print(f"Stable measurements: {MEASUREMENTS_CSV}")
    print(f"Stable measurement events: {MEASUREMENTS_JSONL}")
    print(f"Latest stable measurement: {LATEST_JSON}")
    print(f"Signal snapshot: {SIGNAL_JSON}")
    print(f"Env sensor MAC: {SENSOR_MAC}  (LYWSD03MMC BTHome v2, sensor_id={SENSOR_ID!r})")
    print(f"Sensor latest: {SENSOR_LATEST_JSON}")
    print(f"Sensor history: {SENSOR_READINGS_JSONL}")

    if seconds:
        await run_scan_session(seconds)
        return

    while True:
        await run_scan_session(SCANNER_SESSION_SEC)


async def run_scan_session(seconds: int) -> None:
    scanner = BleakScanner(detection_callback=callback)
    started = False
    try:
        await scanner.start()
        started = True
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"BLE scanner error: {type(exc).__name__}: {exc}")
        print(f"Retrying scanner in {SCANNER_RETRY_SEC} seconds.")
        await asyncio.sleep(SCANNER_RETRY_SEC)
    finally:
        if started:
            try:
                await scanner.stop()
            except Exception as exc:
                print(f"BLE scanner stop error: {type(exc).__name__}: {exc}")
                await asyncio.sleep(SCANNER_RETRY_SEC)


if __name__ == "__main__":
    asyncio.run(main())
