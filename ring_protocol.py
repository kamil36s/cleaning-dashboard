"""COLMI R02-family protocol codecs used by the isolated ring collector.

Wire formats are independently implemented from the MIT-licensed openring and
colmi_r02_client protocol references. Stable and experimental decoders remain
explicitly separated so unknown bytes are never presented as health values.
"""

from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


WARSAW = ZoneInfo("Europe/Warsaw")
PACKET_LENGTH = 16

CMD_SET_TIME = 1
CMD_BATTERY = 3
CMD_HEART_RATE_HISTORY = 21
CMD_HEART_RATE_SETTINGS = 22
CMD_REALTIME_HEART_RATE = 30
CMD_HRV_HISTORY = 57
CMD_ACTIVITY_HISTORY = 67
CMD_REALTIME_START = 105
CMD_REALTIME_STOP = 106

REALTIME_KIND_HEART_RATE = 1
REALTIME_KIND_SPO2 = 3
REALTIME_ACTION_START = 1
REALTIME_ACTION_CONTINUE = 3

BIG_DATA_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
BIG_DATA_WRITE_UUID = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
BIG_DATA_NOTIFY_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"
BIG_DATA_SLEEP_ID = 0x27
BIG_DATA_SPO2_ID = 0x2A

NO_DATA = object()


def make_packet(command: int, data: bytes | bytearray = b"") -> bytes:
    if not 0 <= int(command) <= 255:
        raise ValueError("command must fit in one byte")
    if len(data) > 14:
        raise ValueError("COLMI command payload cannot exceed 14 bytes")
    packet = bytearray(PACKET_LENGTH)
    packet[0] = int(command)
    packet[1:1 + len(data)] = data
    packet[15] = sum(packet[:15]) & 0xFF
    return bytes(packet)


def validate_command_packet(packet: bytes | bytearray, expected: int | None = None) -> bytes:
    raw = bytes(packet)
    if len(raw) != PACKET_LENGTH:
        raise ValueError(f"Expected a 16-byte COLMI packet, got {len(raw)}")
    if sum(raw[:15]) & 0xFF != raw[15]:
        raise ValueError("COLMI packet checksum failed")
    opcode = raw[0] & 0x7F
    if raw[0] & 0x80:
        raise ValueError(f"COLMI device returned an error for command {opcode}")
    if expected is not None and opcode != expected:
        raise ValueError(f"Expected command {expected}, got {opcode}")
    return raw


def byte_to_bcd(value: int) -> int:
    if not 0 <= value < 100:
        raise ValueError("BCD value must be between 0 and 99")
    return ((value // 10) << 4) | (value % 10)


def bcd_to_int(value: int) -> int:
    return ((value >> 4) * 10) + (value & 0x0F)


def set_time_packet(target: datetime) -> bytes:
    target_utc = target.astimezone(timezone.utc)
    return make_packet(CMD_SET_TIME, bytes([
        byte_to_bcd(target_utc.year % 2000),
        byte_to_bcd(target_utc.month),
        byte_to_bcd(target_utc.day),
        byte_to_bcd(target_utc.hour),
        byte_to_bcd(target_utc.minute),
        byte_to_bcd(target_utc.second),
        1,
    ]))


def parse_battery(packet: bytes | bytearray) -> dict[str, Any]:
    raw = validate_command_packet(packet, CMD_BATTERY)
    level = int(raw[1])
    if not 0 <= level <= 100:
        raise ValueError("Battery percentage is outside 0..100")
    return {"battery_percentage": level, "charging": bool(raw[2])}


def _u16le(raw: bytes, offset: int) -> int:
    return raw[offset] | (raw[offset + 1] << 8)


def _u32le(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset:offset + 4], "little", signed=False)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_midnight(day: date | datetime) -> datetime:
    selected = day.date() if isinstance(day, datetime) else day
    return datetime.combine(selected, datetime_time.min, tzinfo=timezone.utc)


def read_heart_rate_packet(day: date | datetime) -> bytes:
    epoch = int(utc_midnight(day).timestamp())
    return make_packet(CMD_HEART_RATE_HISTORY, epoch.to_bytes(4, "little", signed=False))


class HeartRateHistoryParser:
    def __init__(self, requested_day: date | datetime, now: datetime | None = None):
        self.requested_day = utc_midnight(requested_day)
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.reset()

    def reset(self) -> None:
        self.size = 0
        self.interval_minutes = 5
        self.timestamp = self.requested_day
        self.values: list[int] = []

    def parse(self, packet: bytes | bytearray) -> dict[str, Any] | object | None:
        raw = validate_command_packet(packet, CMD_HEART_RATE_HISTORY)
        subtype = raw[1]
        if subtype == 0xFF:
            self.reset()
            return NO_DATA
        if subtype == 0:
            self.size = raw[2]
            self.interval_minutes = raw[3] or 5
            self.values = []
            return None
        if subtype == 1:
            epoch = _u32le(raw, 2)
            if epoch > 0:
                self.timestamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
            self.values.extend(raw[6:15])
        else:
            self.values.extend(raw[2:15])
        if self.size and subtype >= self.size - 1:
            values = self.values[:1440]
            samples = []
            base = utc_midnight(self.timestamp)
            for slot, bpm in enumerate(values):
                if 30 <= int(bpm) <= 220:
                    samples.append({
                        "timestampUtc": _iso_utc(base + timedelta(minutes=slot * self.interval_minutes)),
                        "bpm": int(bpm),
                        "sourceMode": "history",
                        "sourceSlot": slot,
                        "sourceDayOffset": (datetime.now(timezone.utc).date() - base.date()).days,
                        "source": "colmi-r10",
                        "parser": "openring-compatible-heart-rate-v1",
                        "protocolConfidence": "stable",
                    })
            result = {"samples": samples, "intervalMinutes": self.interval_minutes}
            self.reset()
            return result
        return None


def read_heart_rate_settings_packet() -> bytes:
    return make_packet(CMD_HEART_RATE_SETTINGS, bytes([1]))


def parse_heart_rate_settings(packet: bytes | bytearray) -> dict[str, Any]:
    raw = validate_command_packet(packet, CMD_HEART_RATE_SETTINGS)
    return {"enabled": raw[2] == 1, "intervalMinutes": int(raw[3])}


def write_heart_rate_settings_packet(enabled: bool, interval_minutes: int) -> bytes:
    interval = int(interval_minutes)
    if not 1 <= interval <= 255:
        raise ValueError("Heart-rate interval must be between 1 and 255 minutes")
    return make_packet(CMD_HEART_RATE_SETTINGS, bytes([2, 1 if enabled else 2, interval]))


def read_activity_packet(day_offset: int = 0) -> bytes:
    if not 0 <= int(day_offset) <= 255:
        raise ValueError("day offset must fit in one byte")
    return make_packet(CMD_ACTIVITY_HISTORY, bytes([int(day_offset), 0x0F, 0x00, 0x5F, 0x01]))


class ActivityHistoryParser:
    def __init__(self, day_offset: int):
        self.day_offset = int(day_offset)
        self.reset()

    def reset(self) -> None:
        self.is_header = True
        self.new_calorie_protocol = False
        self.records: list[dict[str, Any]] = []

    def parse(self, packet: bytes | bytearray) -> list[dict[str, Any]] | object | None:
        raw = validate_command_packet(packet, CMD_ACTIVITY_HISTORY)
        if self.is_header and raw[1] == 0xFF:
            self.reset()
            return NO_DATA
        if self.is_header and raw[1] == 0xF0:
            self.new_calorie_protocol = raw[3] == 1
            self.is_header = False
            return None
        year = bcd_to_int(raw[1]) + 2000
        month = bcd_to_int(raw[2])
        day = bcd_to_int(raw[3])
        slot = int(raw[4])
        try:
            local_dt = datetime(year, month, day, slot // 4, (slot % 4) * 15, tzinfo=WARSAW)
        except ValueError as exc:
            raise ValueError(f"Invalid activity timestamp in ring packet: {exc}") from exc
        # R10 stores activity energy in hundredths of a kcal.
        calories = round(_u16le(raw, 7) / 100.0, 2)
        self.records.append({
            "timestampUtc": _iso_utc(local_dt),
            "sourceSlot": slot,
            "sourceDayOffset": self.day_offset,
            "steps": _u16le(raw, 9),
            "caloriesKcal": calories,
            "distanceM": _u16le(raw, 11),
            "source": "colmi-r10",
            "parser": "openring-compatible-activity-v1",
            "protocolConfidence": "stable",
        })
        if raw[6] > 0 and raw[5] == raw[6] - 1:
            result = list(self.records)
            self.reset()
            return result
        return None


def read_hrv_packet(index: int = 0) -> bytes:
    return make_packet(CMD_HRV_HISTORY, bytes([int(index) & 0xFF]))


class HrvHistoryParser:
    def __init__(self, day: date | datetime):
        self.day = utc_midnight(day)
        self.reset()

    def reset(self) -> None:
        self.total = 0
        self.interval_minutes = 5
        self.next_index = 0
        self.samples: list[dict[str, Any]] = []

    def parse(self, packet: bytes | bytearray) -> list[dict[str, Any]] | object | None:
        raw = validate_command_packet(packet, CMD_HRV_HISTORY)
        index = raw[1]
        if index == 0xFF:
            self.reset()
            return NO_DATA
        if index != self.next_index:
            expected = self.next_index
            self.reset()
            raise ValueError(f"HRV packets out of order: expected {expected}, got {index}")
        if index == 0:
            self.total = raw[2]
            self.interval_minutes = raw[3] or 5
            self.next_index = 1
            return NO_DATA if self.total == 0 else None
        first_slot = raw[2]
        for position, value in enumerate(raw[3:15]):
            if value in {0, 0xFF}:
                continue
            slot = first_slot + position
            self.samples.append({
                "timestampUtc": _iso_utc(self.day + timedelta(minutes=slot * self.interval_minutes)),
                "sourceSlot": slot,
                "sourceDayOffset": (datetime.now(timezone.utc).date() - self.day.date()).days,
                "ringValue": int(value),
                "source": "colmi-r10",
                "parser": "openring-compatible-hrv-v1",
                "protocolConfidence": "experimental",
            })
        self.next_index += 1
        if index >= self.total:
            result = list(self.samples)
            self.reset()
            return result
        return None


def realtime_start_packet(kind: int) -> bytes:
    return make_packet(CMD_REALTIME_START, bytes([kind, REALTIME_ACTION_START]))


def realtime_continue_packet(kind: int) -> bytes:
    return make_packet(CMD_REALTIME_START, bytes([kind, REALTIME_ACTION_CONTINUE]))


def realtime_stop_packet(kind: int) -> bytes:
    return make_packet(CMD_REALTIME_STOP, bytes([kind, 0, 0]))


def realtime_heart_rate_poll_packet() -> bytes:
    return make_packet(CMD_REALTIME_HEART_RATE, bytes([3]))


def parse_realtime_heart_rate(packet: bytes | bytearray) -> int:
    raw = validate_command_packet(packet, CMD_REALTIME_HEART_RATE)
    return int(raw[1])


def parse_realtime_reading(packet: bytes | bytearray) -> dict[str, Any]:
    raw = validate_command_packet(packet, CMD_REALTIME_START)
    return {"kind": int(raw[1]), "errorCode": int(raw[2]), "value": int(raw[3])}


def big_data_request(data_id: int) -> bytes:
    return bytes([0xBC, int(data_id) & 0xFF, 0x01, 0x00, 0xFF, 0x00, 0xFF])


class BigDataReassembler:
    def __init__(self):
        self.buffer = bytearray()

    def push(self, chunk: bytes | bytearray) -> dict[str, Any] | None:
        self.buffer.extend(chunk)
        if len(self.buffer) < 6:
            return None
        data_length = self.buffer[2] | (self.buffer[3] << 8)
        total = 6 + data_length
        if len(self.buffer) < total:
            return None
        raw = bytes(self.buffer[:total])
        self.buffer = bytearray(self.buffer[total:])
        return {
            "dataId": raw[1],
            "payload": raw[6:],
            "crcSentinel": (raw[4] | (raw[5] << 8)) == 0xFFFF,
        }


def _local_day(days_ago: int, now: datetime | None = None) -> date:
    current = (now or datetime.now(WARSAW)).astimezone(WARSAW).date()
    return current - timedelta(days=int(days_ago))


def parse_spo2_history(payload: bytes | bytearray, now: datetime | None = None) -> list[dict[str, Any]]:
    raw = bytes(payload)
    record_length = 49
    samples = []
    for base in range(0, len(raw) - record_length + 1, record_length):
        days_ago = int(raw[base])
        local_midnight = datetime.combine(_local_day(days_ago, now), datetime_time.min, tzinfo=WARSAW)
        for slot in range(24):
            maximum = int(raw[base + 1 + slot * 2])
            minimum = int(raw[base + 2 + slot * 2])
            if maximum <= 0 and minimum <= 0:
                continue
            samples.append({
                "timestampUtc": _iso_utc(local_midnight + timedelta(hours=slot)),
                "sourceSlot": slot,
                "sourceDayOffset": days_ago,
                "spo2": maximum or minimum,
                "spo2Min": minimum or maximum,
                "spo2Max": maximum or minimum,
                "sourceMode": "history",
                "source": "colmi-r10",
                "parser": "openring-compatible-spo2-big-data-v1",
                "protocolConfidence": "experimental",
            })
    return samples


SLEEP_STAGES = {2: "light", 3: "deep", 4: "rem", 5: "awake"}


def _i16le(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset:offset + 2], "little", signed=True)


def parse_sleep_history(payload: bytes | bytearray, now: datetime | None = None) -> list[dict[str, Any]]:
    raw = bytes(payload)
    local_now = (now or datetime.now(WARSAW)).astimezone(WARSAW)
    night_count = raw[0] if raw else 0
    nights = []
    cursor = 1
    for _ in range(night_count):
        if cursor + 6 > len(raw):
            break
        days_ago = int(raw[cursor])
        record_bytes = int(raw[cursor + 1])
        record_end = min(len(raw), cursor + 2 + record_bytes)
        start_minutes = _i16le(raw, cursor + 2)
        end_minutes = _i16le(raw, cursor + 4)
        stages = []
        for offset in range(cursor + 6, record_end - 1, 2):
            stage = SLEEP_STAGES.get(raw[offset])
            duration = int(raw[offset + 1])
            if stage and duration > 0:
                stages.append({"stage": stage, "durationMinutes": duration})
        if stages:
            local_midnight = datetime.combine(_local_day(days_ago, now), datetime_time.min, tzinfo=WARSAW)
            start = local_midnight + timedelta(minutes=start_minutes)
            end = local_midnight + timedelta(minutes=end_minutes)
            if end <= start:
                # The protocol's day offset identifies the wake-up day. For a
                # night crossing midnight, the start therefore belongs to the
                # previous calendar day, not the following wake-up day.
                start -= timedelta(days=1)
            if days_ago == 0 and end > local_now + timedelta(minutes=15):
                # Shortly after midnight the ring can still expose yesterday's
                # completed night as day 0. Its wake time then lands implausibly
                # in the future and used to be stored again under today's date.
                local_midnight -= timedelta(days=1)
                start -= timedelta(days=1)
                end -= timedelta(days=1)
            totals = {name: 0 for name in ("awake", "light", "deep", "rem")}
            for segment in stages:
                totals[segment["stage"]] += segment["durationMinutes"]
            nights.append({
                "sleepDate": local_midnight.date().isoformat(),
                "sleepStartUtc": _iso_utc(start),
                "sleepEndUtc": _iso_utc(end),
                "totalMinutes": sum(segment["durationMinutes"] for segment in stages),
                "awakeMinutes": totals["awake"],
                "lightMinutes": totals["light"],
                "deepMinutes": totals["deep"],
                "remMinutes": totals["rem"],
                "sourceDayOffset": days_ago,
                "source": "colmi-r10",
                "parser": "openring-compatible-sleep-big-data-v1",
                "protocolConfidence": "experimental",
                "stages": stages,
                "raw": {"sleepStartMin": start_minutes, "sleepEndMin": end_minutes},
            })
        cursor = record_end if record_end > cursor else cursor + 6
    return nights
