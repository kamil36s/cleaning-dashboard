"""Authenticated Android BLE bridge ingestion for the isolated COLMI store."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ring_protocol import BIG_DATA_SLEEP_ID, BIG_DATA_SPO2_ID, parse_sleep_history, parse_spo2_history
from ring_store import RingStore, utc_now
from ring_wear import RingWearDetector


UART_SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
UART_WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_NOTIFY_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
BIG_DATA_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
BIG_DATA_WRITE_UUID = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
BIG_DATA_NOTIFY_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"


class RingPhoneBridgeError(ValueError):
    pass


def _text(value: Any, name: str, maximum: int = 128) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise RingPhoneBridgeError(f"{name} must contain 1..{maximum} characters")
    return result


def _timestamp(value: Any, name: str = "timestampUtc") -> tuple[str, datetime]:
    raw = _text(value, name, 64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RingPhoneBridgeError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RingPhoneBridgeError(f"{name} must include a timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"), utc


def _hex(value: Any, name: str, maximum_bytes: int) -> bytes:
    compact = "".join(str(value or "").split())
    if not compact or len(compact) > maximum_bytes * 2 or len(compact) % 2:
        raise RingPhoneBridgeError(f"{name} has an invalid length")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise RingPhoneBridgeError(f"{name} must be hexadecimal") from exc


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise RingPhoneBridgeError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RingPhoneBridgeError(f"{name} must be an integer") from exc
    if not minimum <= number <= maximum:
        raise RingPhoneBridgeError(f"{name} must be between {minimum} and {maximum}")
    return number


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise RingPhoneBridgeError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RingPhoneBridgeError(f"{name} must be a number") from exc
    if not minimum <= number <= maximum:
        raise RingPhoneBridgeError(f"{name} must be between {minimum} and {maximum}")
    return number


class RingPhoneBridge:
    def __init__(
        self,
        store: RingStore,
        on_presence: Callable[[bool], None] | None = None,
        on_profile: Callable[[str, str | None, str | None], None] | None = None,
        wear_detector: RingWearDetector | None = None,
    ):
        self.store = store
        self.on_presence = on_presence
        self.on_profile = on_profile
        self.wear_detector = wear_detector or RingWearDetector()

    def wear_state(self, device_id: str | None = None) -> dict[str, Any]:
        return self.wear_detector.status(device_id)

    def status(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            raise RingPhoneBridgeError("schemaVersion must be 1")
        phone_id = _text(payload.get("phoneId"), "phoneId")
        active = bool(payload.get("bridgeActive"))
        profile = str(payload.get("collectionProfile") or "unknown")[:32]
        if profile not in {"ring_primary", "watch_present", "unknown"}:
            raise RingPhoneBridgeError("collectionProfile is invalid")
        watch_last_seen = str(payload.get("watchLastSeenAt") or "").strip()[:64] or None
        reason = str(payload.get("profileReason") or "").strip()[:128] or None
        if self.on_presence:
            self.on_presence(active)
        if self.on_profile:
            self.on_profile(profile, watch_last_seen, reason)
        self.store.record_event(
            "info",
            "phone_bridge_status",
            "Android ring bridge active" if active else "Android ring bridge stopped",
            {"phoneId": phone_id, "collectionProfile": profile, "watchLastSeenAt": watch_last_seen, "reason": reason},
        )
        return {"ok": True, "phoneBridgeActive": active, "collectionProfile": profile}

    def ingest(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RingPhoneBridgeError("JSON payload must be an object")
        if payload.get("schemaVersion") != 1:
            raise RingPhoneBridgeError("schemaVersion must be 1")
        phone_id = _text(payload.get("phoneId"), "phoneId")
        bridge_active = bool(payload.get("bridgeActive"))
        if self.on_presence:
            self.on_presence(bridge_active)
        ring = payload.get("ring")
        if not isinstance(ring, dict):
            raise RingPhoneBridgeError("ring must be an object")
        ble_id = _text(ring.get("bleId"), "ring.bleId")
        advertised_name = str(ring.get("advertisedName") or "COLMI R10").strip()[:128]
        rssi = ring.get("rssi")
        if rssi is not None:
            rssi = _integer(rssi, "ring.rssi", -127, 20)

        packets = payload.get("packets") or []
        observations = payload.get("observations") or []
        if not isinstance(packets, list) or len(packets) > 500:
            raise RingPhoneBridgeError("packets must be an array with at most 500 items")
        if not isinstance(observations, list) or len(observations) > 1000:
            raise RingPhoneBridgeError("observations must be an array with at most 1000 items")

        device = self.store.upsert_device(
            ble_id=ble_id,
            advertised_name=advertised_name,
            rssi=rssi,
            source_mode="phone-bridge",
        )
        if self.store.selected_device() is None:
            self.store.select_device(device["deviceId"])

        processed: list[str] = []
        rejected: list[dict[str, str]] = []
        packet_count = 0
        wear_transitions: list[dict[str, Any]] = []
        for item in packets:
            external = None
            try:
                if not isinstance(item, dict):
                    raise RingPhoneBridgeError("packet must be an object")
                raw_id = _text(item.get("id"), "packet.id")
                external = f"{phone_id}:packet:{raw_id}"
                captured_at, _ = _timestamp(item.get("capturedAt"), "packet.capturedAt")
                direction = _text(item.get("direction"), "packet.direction", 2).upper()
                if direction not in {"RX", "TX"}:
                    raise RingPhoneBridgeError("packet.direction must be RX or TX")
                channel = _text(item.get("channel"), "packet.channel", 16)
                if channel not in {"uart", "big-data"}:
                    raise RingPhoneBridgeError("packet.channel must be uart or big-data")
                raw = _hex(item.get("payloadHex"), "packet.payloadHex", 4096)
                wear = self.wear_detector.observe_packet(
                    device["deviceId"], captured_at, direction, str(item.get("context") or ""), raw
                )
                if wear and wear["changed"]:
                    wear_transitions.append(wear)
                service = UART_SERVICE_UUID if channel == "uart" else BIG_DATA_SERVICE_UUID
                characteristic = (
                    UART_NOTIFY_UUID if direction == "RX" else UART_WRITE_UUID
                ) if channel == "uart" else (
                    BIG_DATA_NOTIFY_UUID if direction == "RX" else BIG_DATA_WRITE_UUID
                )
                packet_count += self.store.record_packet(
                    device_id=device["deviceId"],
                    direction=direction,
                    service_uuid=service,
                    characteristic_uuid=characteristic,
                    payload=raw,
                    parsed_type=str(item.get("context") or "phone-bridge")[:128],
                    parser_status="phone-buffered",
                    timestamp_utc=captured_at,
                    source_transport="android-ble",
                    external_id=external,
                )
                processed.append(raw_id)
            except RingPhoneBridgeError as exc:
                if external:
                    processed.append(external.rsplit(":", 1)[-1])
                rejected.append({"id": str(item.get("id") if isinstance(item, dict) else ""), "error": str(exc)})

        grouped: dict[str, list[dict[str, Any]]] = {
            "heartRate": [], "watchHeartRate": [], "spo2": [], "activity": [], "hrv": [], "sleep": [],
        }
        observation_counts: dict[str, int] = {}
        for item in observations:
            raw_id = ""
            try:
                if not isinstance(item, dict):
                    raise RingPhoneBridgeError("observation must be an object")
                raw_id = _text(item.get("id"), "observation.id")
                kind = _text(item.get("type"), "observation.type", 32)
                timestamp_utc, captured = _timestamp(
                    item.get("timestampUtc") or item.get("capturedAt"), "observation.timestampUtc"
                )
                common = {
                    "timestampUtc": timestamp_utc,
                    "source": "colmi-r10-via-android",
                    "parser": "android-phone-bridge-v1",
                    "raw": {"phoneId": phone_id, "externalId": raw_id},
                }
                if kind == "heartRate":
                    record = {
                        **common,
                        "bpm": _integer(item.get("bpm"), "bpm", 30, 220),
                        "sourceMode": str(item.get("sourceMode") or "realtime")[:16],
                        "sourceSlot": item.get("sourceSlot"),
                        "sourceDayOffset": item.get("sourceDayOffset"),
                        "protocolConfidence": "stable",
                    }
                    if self.wear_detector.accepts_heart_rate(device["deviceId"], timestamp_utc):
                        grouped[kind].append(record)
                    else:
                        observation_counts["heartRateFilteredOffWrist"] = (
                            observation_counts.get("heartRateFilteredOffWrist", 0) + 1
                        )
                elif kind == "watchHeartRate":
                    grouped[kind].append({
                        "timestampUtc": timestamp_utc,
                        "bpm": _integer(item.get("bpm"), "bpm", 30, 240),
                        "dataOrigin": str(item.get("dataOrigin") or "health-connect")[:255],
                        "deviceType": item.get("deviceType"),
                        "manufacturer": str(item.get("manufacturer") or "")[:128] or None,
                        "model": str(item.get("model") or "")[:128] or None,
                    })
                elif kind == "spo2":
                    value = _integer(item.get("spo2"), "spo2", 70, 100)
                    record = {
                        **common, "spo2": value,
                        "spo2Min": _integer(item.get("spo2Min", value), "spo2Min", 50, 100),
                        "spo2Max": _integer(item.get("spo2Max", value), "spo2Max", 50, 100),
                        "sourceMode": str(item.get("sourceMode") or "realtime")[:16],
                        "sourceSlot": item.get("sourceSlot"),
                        "sourceDayOffset": item.get("sourceDayOffset"),
                        "protocolConfidence": str(item.get("protocolConfidence") or "stable")[:32],
                    }
                    if self.wear_detector.accepts_measurement(device["deviceId"], timestamp_utc, "spo2"):
                        grouped[kind].append(record)
                    else:
                        observation_counts["spo2FilteredOffWrist"] = (
                            observation_counts.get("spo2FilteredOffWrist", 0) + 1
                        )
                elif kind == "activity":
                    grouped[kind].append({
                        **common,
                        "steps": _integer(item.get("steps", 0), "steps", 0, 1_000_000),
                        "distanceM": _integer(item.get("distanceM", 0), "distanceM", 0, 1_000_000),
                        "caloriesKcal": _number(item.get("caloriesKcal", 0), "caloriesKcal", 0, 10_000),
                        "sourceSlot": item.get("sourceSlot"),
                        "sourceDayOffset": item.get("sourceDayOffset"),
                        "protocolConfidence": "stable",
                    })
                elif kind == "hrv":
                    record = {
                        **common,
                        "ringValue": _integer(item.get("ringValue"), "ringValue", 1, 255),
                        "sourceSlot": item.get("sourceSlot"),
                        "sourceDayOffset": item.get("sourceDayOffset"),
                        "protocolConfidence": "experimental",
                    }
                    if self.wear_detector.accepts_measurement(device["deviceId"], timestamp_utc, "hrv"):
                        grouped[kind].append(record)
                    else:
                        observation_counts["hrvFilteredOffWrist"] = (
                            observation_counts.get("hrvFilteredOffWrist", 0) + 1
                        )
                elif kind == "battery":
                    self.store.update_device_info(
                        device["deviceId"],
                        battery_percentage=_integer(item.get("percentage"), "percentage", 0, 100),
                        charging=bool(item.get("charging")),
                    )
                    observation_counts["battery"] = observation_counts.get("battery", 0) + 1
                elif kind == "bigData":
                    data_id = _integer(item.get("dataId"), "dataId", 0, 255)
                    raw = _hex(item.get("payloadHex"), "payloadHex", 1024 * 1024)
                    if data_id == BIG_DATA_SLEEP_ID:
                        grouped["sleep"].extend(parse_sleep_history(raw, now=captured))
                    elif data_id == BIG_DATA_SPO2_ID:
                        grouped["spo2"].extend(parse_spo2_history(raw, now=captured))
                    else:
                        raise RingPhoneBridgeError("unsupported Big Data id")
                else:
                    raise RingPhoneBridgeError(f"unsupported observation type: {kind}")
                processed.append(raw_id)
            except (RingPhoneBridgeError, ValueError) as exc:
                if raw_id:
                    processed.append(raw_id)
                rejected.append({"id": raw_id, "error": str(exc)})

        ingestors = {
            "heartRate": self.store.ingest_heart_rate,
            "watchHeartRate": self.store.ingest_watch_heart_rate_reference,
            "spo2": self.store.ingest_spo2,
            "activity": self.store.ingest_activity,
            "hrv": self.store.ingest_hrv,
            "sleep": self.store.ingest_sleep,
        }
        for kind, records in grouped.items():
            if records:
                observation_counts[kind] = ingestors[kind](device["deviceId"], records)

        for wear in wear_transitions:
            self.store.record_event(
                "warning" if wear["state"] == "off_wrist" else "info",
                "ring_wear_state",
                "Ring zdjęty — pomiary HR odfiltrowane" if wear["state"] == "off_wrist"
                else "Ring ponownie założony — pomiary HR wznowione",
                wear,
            )

        self.store.update_device_info(device["deviceId"], last_successful_sync=utc_now())
        self.store.record_event(
            "info" if not rejected else "warning",
            "phone_bridge_ingest",
            f"Android bridge processed packets={len(packets)}, observations={len(observations)}",
            {"phoneId": phone_id, "insertedPackets": packet_count, "inserted": observation_counts, "rejected": rejected},
        )
        return {
            "ok": True,
            "deviceId": device["deviceId"],
            "processedIds": list(dict.fromkeys(processed)),
            "insertedPackets": packet_count,
            "inserted": observation_counts,
            "rejected": rejected,
            "phoneBridgeActive": bridge_active,
            "wear": self.wear_detector.status(device["deviceId"]),
        }
