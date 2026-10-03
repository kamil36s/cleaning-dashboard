"""Optical-contact state for COLMI ring measurements."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any


CMD_REALTIME_START = 0x69
CMD_REALTIME_STOP = 0x6A
REALTIME_KIND_HEART_RATE = 1


def _timestamp_ms(value: str) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("wear timestamp must include a timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _iso_utc(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc) \
        .isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RingWearDetector:
    """Infer finger contact from complete realtime optical measurement cycles.

    COLMI sends zero-valued HR frames while the optical sensor is acquiring a
    signal. A removed ring ends that cycle with a non-zero error code and no
    valid HR value. A worn ring produces at least two valid HR frames.
    """

    def __init__(self, minimum_zero_frames: int = 3, minimum_valid_frames: int = 2):
        self.minimum_zero_frames = max(1, int(minimum_zero_frames))
        self.minimum_valid_frames = max(1, int(minimum_valid_frames))
        self._lock = threading.RLock()
        self._devices: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _new_state() -> dict[str, Any]:
        return {
            "state": "unknown",
            "sinceMs": None,
            "updatedMs": None,
            "reason": "awaiting_optical_measurement",
            "attemptStartMs": None,
            "zeroFrames": 0,
            "validFrames": 0,
            "lastPacketMs": None,
            "intervals": [],
            "filtered": {},
        }

    def _device(self, device_id: str) -> dict[str, Any]:
        return self._devices.setdefault(device_id, self._new_state())

    def _set_state(self, state: dict[str, Any], value: str, at_ms: int, reason: str) -> bool:
        changed = state["state"] != value
        previous = state["state"]
        if changed:
            if value == "off_wrist":
                start_ms = state["attemptStartMs"] or at_ms
                state["intervals"].append({"startMs": start_ms, "endMs": None})
                state["sinceMs"] = start_ms
            elif previous == "off_wrist":
                active = next(
                    (item for item in reversed(state["intervals"]) if item["endMs"] is None),
                    None,
                )
                if active:
                    active["endMs"] = at_ms
                state["sinceMs"] = at_ms
            else:
                state["sinceMs"] = at_ms
        state["state"] = value
        state["updatedMs"] = at_ms
        state["reason"] = reason
        return changed

    def observe_packet(
        self,
        device_id: str,
        captured_at: str,
        direction: str,
        context: str,
        packet: bytes,
    ) -> dict[str, Any] | None:
        raw = bytes(packet)
        if len(raw) != 16 or (raw[0] & 0x7F) not in {CMD_REALTIME_START, CMD_REALTIME_STOP}:
            return None
        if sum(raw[:15]) & 0xFF != raw[15]:
            return None
        if not str(context).startswith("heart-rate-live"):
            return None

        at_ms = _timestamp_ms(captured_at)
        direction = str(direction).upper()
        with self._lock:
            state = self._device(device_id)
            if state["lastPacketMs"] is not None and at_ms <= state["lastPacketMs"]:
                return {**self.status(device_id), "changed": False}
            state["lastPacketMs"] = at_ms
            changed = False
            opcode = raw[0] & 0x7F
            if direction == "TX" and opcode == CMD_REALTIME_START and raw[1] == REALTIME_KIND_HEART_RATE:
                state["attemptStartMs"] = at_ms
                state["zeroFrames"] = 0
                state["validFrames"] = 0
            elif direction == "RX" and opcode == CMD_REALTIME_START and raw[1] == REALTIME_KIND_HEART_RATE:
                error_code = int(raw[2])
                value = int(raw[3])
                if error_code == 0 and 30 <= value <= 220:
                    state["validFrames"] += 1
                    if state["validFrames"] >= self.minimum_valid_frames:
                        changed = self._set_state(state, "worn", at_ms, "optical_pulse_detected")
                elif value == 0:
                    state["zeroFrames"] += 1
                if (
                    error_code != 0
                    and state["validFrames"] == 0
                    and state["zeroFrames"] >= self.minimum_zero_frames
                ):
                    changed = self._set_state(state, "off_wrist", at_ms, "optical_measurement_failed")

            return {**self.status(device_id), "changed": changed}

    def accepts_measurement(self, device_id: str, timestamp_utc: str, metric: str) -> bool:
        at_ms = _timestamp_ms(timestamp_utc)
        with self._lock:
            state = self._device(device_id)
            for interval in state["intervals"]:
                if at_ms >= interval["startMs"] and (
                    interval["endMs"] is None or at_ms <= interval["endMs"]
                ):
                    state["filtered"][metric] = state["filtered"].get(metric, 0) + 1
                    return False
            return True

    def accepts_heart_rate(self, device_id: str, timestamp_utc: str) -> bool:
        return self.accepts_measurement(device_id, timestamp_utc, "heartRate")

    def status(self, device_id: str | None) -> dict[str, Any]:
        with self._lock:
            state = self._device(device_id) if device_id else self._new_state()
            return {
                "state": state["state"],
                "since": _iso_utc(state["sinceMs"]) if state["sinceMs"] is not None else None,
                "updatedAt": _iso_utc(state["updatedMs"]) if state["updatedMs"] is not None else None,
                "reason": state["reason"],
                "filteredHeartRate": state["filtered"].get("heartRate", 0),
                "filteredMeasurements": dict(state["filtered"]),
            }
