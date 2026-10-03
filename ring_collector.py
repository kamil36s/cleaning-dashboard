"""Persistent COLMI R10 BLE collector for Windows using Bleak/WinRT."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Coroutine

from ring_store import RingStore, utc_now
from ring_protocol import (
    BIG_DATA_NOTIFY_UUID,
    BIG_DATA_SERVICE_UUID,
    BIG_DATA_SLEEP_ID,
    BIG_DATA_SPO2_ID,
    BIG_DATA_WRITE_UUID,
    CMD_ACTIVITY_HISTORY,
    CMD_HEART_RATE_HISTORY,
    CMD_HEART_RATE_SETTINGS,
    CMD_HRV_HISTORY,
    CMD_REALTIME_HEART_RATE,
    CMD_REALTIME_START,
    REALTIME_KIND_HEART_RATE,
    REALTIME_KIND_SPO2,
    ActivityHistoryParser,
    BigDataReassembler,
    HeartRateHistoryParser,
    HrvHistoryParser,
    NO_DATA,
    big_data_request,
    parse_heart_rate_settings,
    parse_realtime_heart_rate,
    parse_realtime_reading,
    parse_sleep_history,
    parse_spo2_history,
    read_activity_packet,
    read_heart_rate_packet,
    read_heart_rate_settings_packet,
    read_hrv_packet,
    realtime_heart_rate_poll_packet,
    realtime_start_packet,
    realtime_stop_packet,
    write_heart_rate_settings_packet,
)

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # The dashboard remains usable before ring dependencies are installed.
    BleakClient = None
    BleakScanner = None


UART_SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
UART_WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_NOTIFY_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
DEVICE_FIRMWARE_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
DEVICE_HARDWARE_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
DEVICE_MODEL_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
CMD_SET_TIME = 1
CMD_BATTERY = 3
COMPATIBLE_NAME = re.compile(r"(?:^|\b)(?:COLMI[ _-]*)?R(?:02|03|06|10|12)(?=$|[^0-9A-Za-z])|QRING", re.I)

CAPABILITIES = {
    "battery": "supported",
    "charging": "supported",
    "ringTime": "supported",
    "deviceInformation": "supported",
    "heartRateRealtime": "supported",
    "heartRateHistory": "supported",
    "wearDetection": "supported",
    "spo2Realtime": "supported",
    "spo2History": "experimental",
    "activity": "supported",
    "sleep": "experimental",
    "hrv": "experimental",
    "stress": "unknown",
    "rawPpg": "unknown",
    "rawAccelerometer": "unknown",
}


class RingError(RuntimeError):
    def __init__(self, message: str, *, code: str = "ring_error", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status

    def as_payload(self) -> dict[str, Any]:
        return {"ok": False, "error": str(self), "code": self.code}


def make_packet(command: int, data: bytes | bytearray = b"") -> bytes:
    if not 0 <= command <= 255:
        raise ValueError("command must fit in one byte")
    if len(data) > 14:
        raise ValueError("COLMI command payload cannot exceed 14 bytes")
    packet = bytearray(16)
    packet[0] = command
    packet[1:1 + len(data)] = data
    packet[15] = sum(packet[:15]) & 0xFF
    return bytes(packet)


def byte_to_bcd(value: int) -> int:
    if not 0 <= value < 100:
        raise ValueError("BCD value must be between 0 and 99")
    return ((value // 10) << 4) | (value % 10)


def set_time_packet(target: datetime) -> bytes:
    target_utc = target.astimezone(timezone.utc)
    data = bytes(
        [
            byte_to_bcd(target_utc.year % 2000),
            byte_to_bcd(target_utc.month),
            byte_to_bcd(target_utc.day),
            byte_to_bcd(target_utc.hour),
            byte_to_bcd(target_utc.minute),
            byte_to_bcd(target_utc.second),
            1,
        ]
    )
    return make_packet(CMD_SET_TIME, data)


def parse_battery(packet: bytes | bytearray) -> dict[str, Any]:
    raw = bytes(packet)
    if len(raw) != 16 or (raw[0] & 0x7F) != CMD_BATTERY:
        raise ValueError("Not a COLMI battery packet")
    if sum(raw[:15]) & 0xFF != raw[15]:
        raise ValueError("Battery packet checksum failed")
    level = int(raw[1])
    if not 0 <= level <= 100:
        raise ValueError("Battery percentage is outside 0..100")
    return {"battery_percentage": level, "charging": bool(raw[2])}


def is_compatible(name: str | None, service_uuids: list[str] | None = None) -> bool:
    services = {str(value).lower() for value in (service_uuids or [])}
    return UART_SERVICE_UUID in services or bool(COMPATIBLE_NAME.search(str(name or "")))


class AsyncLoopRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="colmi-ring-collector", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, coroutine: Coroutine[Any, Any, Any], timeout: float = 35) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise RingError("Operacja ringa przekroczyła limit czasu", code="timeout", status=504) from exc


class RingCollector:
    def __init__(
        self,
        root: str | Path,
        *,
        mode: str | None = None,
        store: RingStore | None = None,
        automatic: bool = True,
    ):
        self.root = Path(root).resolve()
        requested_mode = str(mode or os.environ.get("RING_COLLECTOR_MODE") or "real").strip().lower()
        self.mode = requested_mode if requested_mode in {"real", "mock"} else "real"
        default_db = self.root / "data" / ("ring-mock.sqlite" if self.mode == "mock" else "ring.sqlite")
        self.store = store or RingStore(os.environ.get("RING_DB_PATH") or default_db)
        self.runner = AsyncLoopRunner()
        self._lock = threading.RLock()
        self._client = None
        self._active_device_id: str | None = None
        self._status = "disconnected"
        self._status_message = "Brak połączonego pierścienia COLMI"
        self._devices: dict[str, Any] = {}
        self._ble_handles: dict[str, Any] = {}
        self._services: list[dict[str, Any]] = []
        self._pending: dict[int, asyncio.Queue[bytes]] = {}
        self._big_data_queue: asyncio.Queue[bytes] | None = None
        self._big_data_available = False
        self._last_error: dict[str, Any] | None = None
        self._heart_rate_settings: dict[str, Any] | None = None
        self._automatic = bool(automatic)
        self._supervisor_future = None
        self._stopping = False
        self._last_sync_monotonic = 0.0
        self._last_live_monotonic = 0.0
        self._ui_active_until = 0.0
        self._phone_bridge_active_until = 0.0
        self._phone_collection_profile = "unknown"
        self._phone_watch_last_seen: str | None = None
        self._phone_profile_reason: str | None = None
        self._sync_interval_seconds = max(300, int(os.environ.get("RING_SYNC_INTERVAL_SECONDS", "900")))
        self._history_days = max(1, min(30, int(os.environ.get("RING_HISTORY_DAYS", "7"))))
        self._hr_interval_minutes = max(1, min(60, int(os.environ.get("RING_HR_INTERVAL_MINUTES", "5"))))
        self._live_cycle_interval = max(30, int(os.environ.get("RING_LIVE_CYCLE_SECONDS", "60")))
        self._fixture = self._load_fixture() if self.mode == "mock" else None
        self.store.record_event("info", "collector_started", f"COLMI collector started in {self.mode} mode")

    def start(self) -> None:
        if not self._automatic or self._supervisor_future is not None:
            return
        self._stopping = False
        self._supervisor_future = asyncio.run_coroutine_threadsafe(self._supervisor(), self.runner.loop)
        self.store.record_event("info", "automation_started", "Automatic discovery and synchronization enabled")

    def stop(self) -> None:
        self._stopping = True
        future = self._supervisor_future
        self._supervisor_future = None
        if future is not None:
            future.cancel()
        try:
            self.runner.call(self._disconnect(), timeout=10)
        except Exception:
            pass

    def presence(self) -> dict[str, Any]:
        with self._lock:
            self._ui_active_until = time.monotonic() + 45
        return {"ok": True, "liveUntil": utc_now(), "state": self.state()}

    def phone_bridge_heartbeat(self, active: bool) -> None:
        with self._lock:
            self._phone_bridge_active_until = time.monotonic() + 20 * 60 if active else 0.0
            should_disconnect = active and self._client is not None
        if should_disconnect:
            asyncio.run_coroutine_threadsafe(self._disconnect(), self.runner.loop)

    def phone_bridge_profile(self, profile: str, watch_last_seen: str | None, reason: str | None) -> None:
        with self._lock:
            self._phone_collection_profile = profile
            self._phone_watch_last_seen = watch_last_seen
            self._phone_profile_reason = reason

    @property
    def dependency_available(self) -> bool:
        return self.mode == "mock" or (BleakClient is not None and BleakScanner is not None)

    def _load_fixture(self) -> dict[str, Any]:
        path = self.root / "fixtures" / "ring" / "phase-b.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RingError(f"Could not load ring fixture: {exc}", code="mock_fixture_error", status=500) from exc

    def _set_status(self, status: str, message: str, error: RingError | None = None) -> None:
        with self._lock:
            self._status = status
            self._status_message = message
            self._last_error = (
                {"code": error.code, "message": str(error), "at": utc_now()} if error else None
            )

    def state(self) -> dict[str, Any]:
        overview = self.store.overview()
        with self._lock:
            status = self._status
            message = self._status_message
            active_device_id = self._active_device_id
            services = list(self._services)
            last_error = dict(self._last_error) if self._last_error else None
            ui_active = time.monotonic() < self._ui_active_until
            phone_bridge_active = time.monotonic() < self._phone_bridge_active_until
        return {
            "ok": True,
            "mode": self.mode,
            "collector": {
                "status": status,
                "message": message,
                "bleDependencyAvailable": self.dependency_available,
                "activeDeviceId": active_device_id,
                "lastError": last_error,
                "recovery": self._recovery(last_error),
                "automatic": self._automatic,
                "syncIntervalSeconds": self._sync_interval_seconds,
                "historyDays": self._history_days,
                "uiLiveActive": ui_active,
                "heartRateSettings": self._heart_rate_settings,
                "bigDataAvailable": self._big_data_available,
                "phoneBridgeActive": phone_bridge_active,
                "phoneCollectionProfile": self._phone_collection_profile,
                "phoneWatchLastSeenAt": self._phone_watch_last_seen,
                "phoneProfileReason": self._phone_profile_reason,
            },
            "device": overview["device"],
            "latest": overview["latest"],
            "capabilities": dict(CAPABILITIES),
            "services": services,
            "devices": self.store.list_devices(),
            "storage": {"database": str(self.store.db_path)},
        }

    @staticmethod
    def _recovery(last_error: dict[str, Any] | None) -> str | None:
        if not last_error:
            return None
        code = last_error.get("code")
        if code == "bleak_not_installed":
            return "Uruchom: py -m pip install -r requirements-ring.txt, a potem ponownie npm run dev:all."
        if code in {"device_not_visible", "ble_scan_failed", "connect_timeout", "connect_failed"}:
            return (
                "Collector spróbuje ponownie sam. Zbliż ring do komputera, zamknij QRing w telefonie "
                "i sprawdź, czy Bluetooth Windows jest włączony."
            )
        if code in {"connection_lost", "not_connected"}:
            return "Trwa automatyczne ponowne łączenie. Jeśli stan się nie zmieni, zbliż lub doładuj ring."
        if code in {"command_timeout", "history_timeout", "sync_failed"}:
            return "Dane już zapisane są bezpieczne. Zostaw ring blisko komputera; kolejna synchronizacja ponowi odczyt."
        return "Collector będzie próbował dalej. Jeśli błąd się powtarza, uruchom ponownie npm run dev:all i sprawdź Diagnostykę."

    def diagnostics(self, limit: int = 100) -> dict[str, Any]:
        payload = self.store.diagnostics(limit)
        payload.update({
            "ok": True,
            "mode": self.mode,
            "collector": self.state()["collector"],
            "services": self.state()["services"],
            "capabilities": dict(CAPABILITIES),
        })
        return payload

    async def _supervisor(self) -> None:
        """Own discovery/reconnect/sync while the dashboard backend is running."""
        retry_seconds = 5
        await asyncio.sleep(1)
        while not self._stopping:
            try:
                if time.monotonic() < self._phone_bridge_active_until:
                    if self._client is not None:
                        await self._disconnect()
                    profile = self._phone_collection_profile
                    message = (
                        "Pierścień jest głównym źródłem tętna i danych snu"
                        if profile == "ring_primary"
                        else "Smartwatch mierzy tętno · pierścień uzupełnia dane"
                        if profile == "watch_present"
                        else "Telefon zbiera dane z pierścienia · sprawdzam źródła"
                    )
                    self._set_status("phone-bridge", message)
                    await asyncio.sleep(5)
                    continue
                if self._client is None:
                    selected = self.store.selected_device()
                    scan = await self._scan(6)
                    candidates = scan.get("devices") or []
                    target = None
                    if selected:
                        target = next(
                            (item for item in candidates if item["deviceId"] == selected["deviceId"]),
                            None,
                        )
                        if target is None and selected.get("advertisedName"):
                            target = next(
                                (
                                    item for item in candidates
                                    if item.get("advertisedName") == selected.get("advertisedName")
                                ),
                                None,
                            )
                    elif len(candidates) == 1:
                        target = candidates[0]
                    if target is None:
                        self._set_status(
                            "searching",
                            "Automatycznie szukam zapamiętanego ringa · sprawdź Bluetooth i zbliż ring",
                        )
                        await asyncio.sleep(retry_seconds)
                        retry_seconds = min(300, retry_seconds * 2)
                        continue
                    await self._connect(target["deviceId"])
                    retry_seconds = 5
                    await self._sync_all()
                    continue

                now = time.monotonic()
                if now - self._last_sync_monotonic >= self._sync_interval_seconds:
                    await self._sync_all()
                    continue
                if (
                    now < self._ui_active_until
                    and now - self._last_live_monotonic >= self._live_cycle_interval
                ):
                    await self._collect_live_cycle()
                    self._last_live_monotonic = time.monotonic()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                code = exc.code if isinstance(exc, RingError) else "automation_error"
                self.store.record_event(
                    "warning",
                    "automation_retry",
                    str(exc),
                    {"code": code, "retrySeconds": retry_seconds},
                )
                if self._client is not None and not getattr(self._client, "is_connected", True):
                    self._client = None
                    self._active_device_id = None
                await asyncio.sleep(retry_seconds)
                retry_seconds = min(300, retry_seconds * 2)

    def scan(self, timeout_seconds: float = 8) -> dict[str, Any]:
        timeout = max(2.0, min(20.0, float(timeout_seconds)))
        return self.runner.call(self._scan(timeout), timeout=timeout + 10)

    async def _scan(self, timeout_seconds: float) -> dict[str, Any]:
        self._set_status("scanning", "Skanowanie w poszukiwaniu ringa COLMI…")
        self.store.record_event("info", "scan_started", "BLE scan started", {"timeoutSeconds": timeout_seconds})
        try:
            if self.mode == "mock":
                raw_devices = [(item, item.get("serviceUuids", []), None) for item in self._fixture.get("devices", [])]
            else:
                if BleakScanner is None:
                    raise RingError(
                        "Python package 'bleak' is not installed. Run: py -m pip install -r requirements-ring.txt",
                        code="bleak_not_installed",
                        status=503,
                    )
                try:
                    found = await BleakScanner.discover(timeout=timeout_seconds, return_adv=True)
                    raw_devices = []
                    for device, advertisement in found.values():
                        raw_devices.append(({
                            "bleId": device.address,
                            "name": advertisement.local_name or device.name,
                            "rssi": advertisement.rssi,
                        }, list(advertisement.service_uuids or []), device))
                except TypeError:
                    found = await BleakScanner.discover(timeout=timeout_seconds)
                    raw_devices = [
                        ({"bleId": item.address, "name": item.name, "rssi": getattr(item, "rssi", None)}, [], item)
                        for item in found
                    ]

            compatible = []
            for raw, services, ble_handle in raw_devices:
                ble_id = str(raw.get("bleId") or raw.get("address") or "").strip()
                name = str(raw.get("name") or "").strip() or None
                if not ble_id or not is_compatible(name, services):
                    continue
                device = self.store.upsert_device(
                    ble_id=ble_id,
                    advertised_name=name,
                    rssi=raw.get("rssi"),
                    source_mode=self.mode,
                )
                self._devices[device["deviceId"]] = {**device, "serviceUuids": services}
                if ble_handle is not None:
                    self._ble_handles[device["deviceId"]] = ble_handle
                compatible.append(device)
            self._set_status(
                "connected" if self._client else "disconnected",
                f"Znaleziono zgodne ringi: {len(compatible)}" if compatible else "Nie znaleziono ringa",
            )
            self.store.record_event("info", "scan_finished", f"BLE scan found {len(compatible)} compatible ring(s)")
            return {"ok": True, "mode": self.mode, "devices": compatible}
        except RingError as exc:
            self._set_status("error", str(exc), exc)
            self.store.record_event("error", "scan_failed", str(exc), {"code": exc.code})
            raise
        except Exception as exc:
            error = RingError(f"Skanowanie BLE nie powiodło się: {exc}", code="ble_scan_failed", status=503)
            self._set_status("error", str(error), error)
            self.store.record_event("error", "scan_failed", str(error))
            raise error from exc

    def connect(self, device_id: str) -> dict[str, Any]:
        return self.runner.call(self._connect(str(device_id)), timeout=40)

    async def _connect(self, device_id: str) -> dict[str, Any]:
        device = self.store.get_device(device_id)
        if not device:
            raise RingError("Najpierw wybierz ring znaleziony przez skanowanie", code="device_not_found", status=404)
        if self._client is not None:
            await self._disconnect()
        self._set_status("connecting", f"Connecting to {device.get('advertisedName') or 'COLMI ring'}…")
        self.store.record_event("info", "connect_started", "Connecting to ring", {"deviceId": device_id})
        try:
            if self.mode == "mock":
                self._client = object()
                self._services = list(self._fixture.get("services", []))
            else:
                if BleakClient is None:
                    raise RingError(
                        "Python package 'bleak' is not installed. Run: py -m pip install -r requirements-ring.txt",
                        code="bleak_not_installed",
                        status=503,
                    )
                ble_handle = self._ble_handles.get(device_id)
                if ble_handle is None:
                    self._set_status("connecting", "Odświeżanie obecności ringa…")
                    ble_handle = await BleakScanner.find_device_by_address(device["bleId"], timeout=12)
                    if ble_handle is None:
                        raise RingError(
                            "Ring nie nadaje teraz sygnału BLE. Połóż go blisko komputera i przeskanuj ponownie.",
                            code="device_not_visible",
                            status=404,
                        )
                    self._ble_handles[device_id] = ble_handle
                client = BleakClient(ble_handle, disconnected_callback=self._on_disconnect, timeout=20)
                await asyncio.wait_for(client.connect(), timeout=20)
                service = client.services.get_service(UART_SERVICE_UUID)
                if service is None:
                    await client.disconnect()
                    raise RingError("Device does not expose the COLMI command service", code="unsupported_device", status=422)
                self._client = client
                await client.start_notify(UART_NOTIFY_UUID, self._on_notification)
                big_data_service = client.services.get_service(BIG_DATA_SERVICE_UUID)
                self._big_data_available = big_data_service is not None
                if self._big_data_available:
                    self._big_data_queue = asyncio.Queue()
                    await client.start_notify(BIG_DATA_NOTIFY_UUID, self._on_big_data_notification)
                self._services = self._service_payload(client.services)
            self._active_device_id = device_id
            self.store.select_device(device_id)
            self._set_status("connected", "Połączono")
            self.store.record_event("info", "connected", "Ring connection established", {"deviceId": device_id})
            sync = await self._sync_phase_b()
            return {"ok": True, "state": self.state(), "sync": sync}
        except RingError as error:
            self._set_status("error", str(error), error)
            self.store.record_event("error", "connect_failed", str(error), {"code": error.code})
            self._client = None
            self._active_device_id = None
            raise
        except asyncio.TimeoutError as exc:
            error = RingError("Połączenie z ringiem przekroczyło limit czasu", code="connect_timeout", status=504)
            self._set_status("error", str(error), error)
            self.store.record_event("error", "connect_failed", str(error))
            raise error from exc
        except Exception as exc:
            error = RingError(f"Nie udało się połączyć z ringiem: {exc}", code="connect_failed", status=503)
            self._set_status("error", str(error), error)
            self.store.record_event("error", "connect_failed", str(error))
            self._client = None
            self._active_device_id = None
            raise error from exc

    def disconnect(self) -> dict[str, Any]:
        return self.runner.call(self._disconnect(), timeout=15)

    async def _disconnect(self) -> dict[str, Any]:
        device_id = self._active_device_id
        client = self._client
        self._client = None
        self._active_device_id = None
        try:
            if self.mode != "mock" and client is not None and getattr(client, "is_connected", False):
                await client.disconnect()
        finally:
            if device_id:
                self.store.update_device_info(device_id, last_disconnected=utc_now())
            self._pending.clear()
            self._big_data_queue = None
            self._big_data_available = False
            self._services = []
            self._set_status("disconnected", "Rozłączono")
            self.store.record_event("info", "disconnected", "Ring disconnected", {"deviceId": device_id})
        return {"ok": True, "state": self.state()}

    def sync(self) -> dict[str, Any]:
        return self.runner.call(self._sync_all(), timeout=180)

    async def _sync_phase_b(self) -> dict[str, Any]:
        if self._client is None or not self._active_device_id:
            raise RingError("Przed synchronizacją połącz ring COLMI", code="not_connected", status=409)
        device_id = self._active_device_id
        requested = ["device-info", "battery", "ring-time"]
        sync_id = self.store.start_sync(device_id, requested, self.mode)
        self._set_status("syncing", "Odczyt informacji o urządzeniu…")
        self.store.update_sync_progress(sync_id, "device-info", {})
        try:
            if self.mode == "mock":
                info = dict(self._fixture.get("deviceInfo", {}))
                battery = dict(self._fixture.get("battery", {}))
            else:
                info = await self._read_device_info()
                self._set_status("syncing", "Odczyt baterii…")
                self.store.update_sync_progress(sync_id, "battery", {"deviceInfo": len(info)})
                battery = parse_battery(await self._request(make_packet(CMD_BATTERY), CMD_BATTERY, "battery"))
                self._set_status("syncing", "Synchronizacja zegara ringa…")
                self.store.update_sync_progress(sync_id, "ring-time", {"deviceInfo": len(info), "battery": 1})
                await self._send(set_time_packet(datetime.now(timezone.utc)), "set-time")
            self.store.update_device_info(device_id, **info, **battery, last_successful_sync=utc_now())
            self.store.finish_sync(sync_id, success=True, records={"deviceInfo": len(info), "battery": 1, "ringTime": 1})
            self._set_status("connected", "Połączono · zsynchronizowano dane urządzenia")
            self.store.record_event("info", "sync_finished", "Phase B sync completed", {"syncId": sync_id})
            return {"ok": True, "syncId": sync_id, "records": {"deviceInfo": len(info), "battery": 1, "ringTime": 1}}
        except Exception as exc:
            error = exc if isinstance(exc, RingError) else RingError(str(exc), code="sync_failed", status=503)
            self.store.finish_sync(sync_id, success=False, error_code=error.code, error_message=str(error))
            self._set_status("error", str(error), error)
            self.store.record_event("error", "sync_failed", str(error), {"syncId": sync_id})
            raise error

    async def _sync_all(self) -> dict[str, Any]:
        if self._client is None or not self._active_device_id:
            raise RingError("Przed synchronizacją połącz ring COLMI", code="not_connected", status=409)
        if self.mode == "mock":
            self._last_sync_monotonic = time.monotonic()
            return await self._sync_phase_b()

        device_id = self._active_device_id
        requested = [
            "battery", "ring-time", "heart-rate-settings", "heart-rate-history",
            "activity", "hrv", "sleep", "spo2-history",
        ]
        sync_id = self.store.start_sync(device_id, requested, self.mode)
        counts: dict[str, int] = {}
        errors: list[dict[str, str]] = []

        async def attempt(dataset: str, operation: Any) -> Any:
            self._set_status("syncing", f"Automatyczna synchronizacja · {dataset}")
            self.store.update_sync_progress(sync_id, dataset, counts)
            try:
                return await operation
            except Exception as exc:
                errors.append({"dataset": dataset, "error": str(exc)})
                self.store.record_event("warning", "dataset_sync_failed", f"{dataset}: {exc}")
                return NO_DATA

        try:
            battery_packet = await attempt(
                "battery",
                self._request(make_packet(CMD_BATTERY), CMD_BATTERY, "battery"),
            )
            if battery_packet is not NO_DATA:
                battery = parse_battery(battery_packet)
                self.store.update_device_info(device_id, **battery)
                counts["battery"] = 1

            await self._send(set_time_packet(datetime.now(timezone.utc)), "set-time")
            counts["ringTime"] = 1

            settings_packet = await attempt(
                "heart-rate-settings",
                self._request(
                    read_heart_rate_settings_packet(),
                    CMD_HEART_RATE_SETTINGS,
                    "heart-rate-settings",
                ),
            )
            if settings_packet is not NO_DATA:
                settings = parse_heart_rate_settings(settings_packet)
                desired = {"enabled": True, "intervalMinutes": self._hr_interval_minutes}
                if settings != desired:
                    try:
                        await self._request(
                            write_heart_rate_settings_packet(True, self._hr_interval_minutes),
                            CMD_HEART_RATE_SETTINGS,
                            "heart-rate-settings-write",
                        )
                        settings = desired
                        self.store.record_event(
                            "info", "heart_rate_schedule_enabled",
                            f"Periodic HR enabled every {self._hr_interval_minutes} minutes",
                        )
                    except Exception as exc:
                        errors.append({"dataset": "heart-rate-settings-write", "error": str(exc)})
                self._heart_rate_settings = settings
                counts["heartRateSettings"] = 1

            for day_offset in range(self._history_days):
                target = datetime.now(timezone.utc) - timedelta(days=day_offset)
                result = await attempt(
                    f"heart-rate-history:{day_offset}",
                    self._request_parsed(
                        read_heart_rate_packet(target),
                        CMD_HEART_RATE_HISTORY,
                        "heart-rate-history",
                        HeartRateHistoryParser(target),
                    ),
                )
                if result is not NO_DATA:
                    decoded = result.get("samples") or []
                    counts["heartRateReceived"] = counts.get("heartRateReceived", 0) + len(decoded)
                    counts["heartRateInserted"] = counts.get("heartRateInserted", 0) + self.store.ingest_heart_rate(device_id, decoded)

            for day_offset in range(self._history_days):
                result = await attempt(
                    f"activity:{day_offset}",
                    self._request_parsed(
                        read_activity_packet(day_offset),
                        CMD_ACTIVITY_HISTORY,
                        "activity-history",
                        ActivityHistoryParser(day_offset),
                    ),
                )
                if result is not NO_DATA:
                    counts["activityReceived"] = counts.get("activityReceived", 0) + len(result)
                    counts["activityInserted"] = counts.get("activityInserted", 0) + self.store.ingest_activity(device_id, result)

            hrv_result = await attempt(
                "hrv",
                self._request_hrv_history(datetime.now(timezone.utc)),
            )
            if hrv_result is not NO_DATA:
                counts["hrvReceived"] = len(hrv_result)
                counts["hrvInserted"] = self.store.ingest_hrv(device_id, hrv_result)

            sleep_payload = await attempt(
                "sleep",
                self._request_big_data(BIG_DATA_SLEEP_ID, "sleep-big-data"),
            )
            if sleep_payload not in {NO_DATA, None}:
                nights = parse_sleep_history(sleep_payload)
                counts["sleepReceived"] = len(nights)
                counts["sleepInserted"] = self.store.ingest_sleep(device_id, nights)

            spo2_payload = await attempt(
                "spo2-history",
                self._request_big_data(BIG_DATA_SPO2_ID, "spo2-big-data"),
            )
            if spo2_payload not in {NO_DATA, None}:
                spo2_records = parse_spo2_history(spo2_payload)
                counts["spo2Received"] = len(spo2_records)
                counts["spo2Inserted"] = self.store.ingest_spo2(device_id, spo2_records)

            completed_at = utc_now()
            self.store.update_device_info(device_id, last_successful_sync=completed_at)
            self.store.finish_sync(
                sync_id,
                success=True,
                records=counts,
                error_code="partial_sync" if errors else None,
                error_message=json.dumps(errors, ensure_ascii=False) if errors else None,
            )
            self._last_sync_monotonic = time.monotonic()
            message = "Połączono · historia zsynchronizowana"
            if errors:
                message = "Połączono · synchronizacja częściowa, szczegóły w Diagnostyce"
            self._set_status("connected", message)
            self.store.record_event(
                "info" if not errors else "warning",
                "automatic_sync_finished",
                message,
                {"syncId": sync_id, "records": counts, "errors": errors},
            )
            return {"ok": True, "syncId": sync_id, "records": counts, "errors": errors}
        except Exception as exc:
            error = exc if isinstance(exc, RingError) else RingError(str(exc), code="sync_failed", status=503)
            self.store.finish_sync(sync_id, success=False, records=counts, error_code=error.code, error_message=str(error))
            self._set_status("error", str(error), error)
            raise error

    async def _collect_live_cycle(self) -> None:
        if self.mode == "mock" or self._client is None or not self._active_device_id:
            return
        device_id = self._active_device_id
        self._set_status("measuring", "Pomiar na żywo · załóż ring i pozostań nieruchomo")
        self.store.record_event("info", "live_cycle_started", "Live HR and SpO2 cycle started")
        heart_records: list[dict[str, Any]] = []
        spo2_records: list[dict[str, Any]] = []

        try:
            await self._send(realtime_start_packet(REALTIME_KIND_HEART_RATE), "heart-rate-live-start")
            await asyncio.sleep(3)
            for _ in range(8):
                if time.monotonic() >= self._ui_active_until or self._client is None:
                    break
                try:
                    packet = await self._request(
                        realtime_heart_rate_poll_packet(),
                        CMD_REALTIME_HEART_RATE,
                        "heart-rate-live-poll",
                    )
                    bpm = parse_realtime_heart_rate(packet)
                    if 30 <= bpm <= 220:
                        heart_records.append({
                            "timestampUtc": utc_now(), "bpm": bpm, "sourceMode": "realtime",
                            "source": "colmi-r10", "parser": "openring-compatible-realtime-hr-v1",
                            "protocolConfidence": "stable",
                        })
                except Exception as exc:
                    self.store.record_event("warning", "live_hr_poll_failed", str(exc))
                await asyncio.sleep(2)
        finally:
            try:
                await self._send(realtime_stop_packet(REALTIME_KIND_HEART_RATE), "heart-rate-live-stop")
            except Exception:
                pass
        if heart_records:
            self.store.ingest_heart_rate(device_id, heart_records)

        if time.monotonic() < self._ui_active_until and self._client is not None:
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            self._pending[CMD_REALTIME_START] = queue
            try:
                await self._send(realtime_start_packet(REALTIME_KIND_SPO2), "spo2-live-start")
                attempts = 0
                while len(spo2_records) < 4 and attempts < 15:
                    try:
                        packet = await asyncio.wait_for(queue.get(), timeout=2)
                        reading = parse_realtime_reading(packet)
                        value = reading["value"]
                        if (
                            reading["kind"] == REALTIME_KIND_SPO2
                            and reading["errorCode"] == 0
                            and 70 <= value <= 100
                        ):
                            spo2_records.append({
                                "timestampUtc": utc_now(), "spo2": value,
                                "spo2Min": value, "spo2Max": value,
                                "sourceMode": "realtime", "source": "colmi-r10",
                                "parser": "openring-compatible-realtime-spo2-v1",
                                "protocolConfidence": "stable",
                            })
                    except asyncio.TimeoutError:
                        attempts += 1
            finally:
                self._pending.pop(CMD_REALTIME_START, None)
                try:
                    await self._send(realtime_stop_packet(REALTIME_KIND_SPO2), "spo2-live-stop")
                except Exception:
                    pass
        if spo2_records:
            self.store.ingest_spo2(device_id, spo2_records)
        self._set_status("connected", "Połączono · podgląd live aktywny")
        self.store.record_event(
            "info",
            "live_cycle_finished",
            f"Live cycle saved HR={len(heart_records)}, SpO2={len(spo2_records)}",
        )

    async def _send(self, packet: bytes, parsed_type: str) -> None:
        if self._client is None:
            raise RingError("Ring is disconnected", code="not_connected", status=409)
        self.store.record_packet(
            device_id=self._active_device_id,
            direction="TX",
            service_uuid=UART_SERVICE_UUID,
            characteristic_uuid=UART_WRITE_UUID,
            payload=packet,
            parsed_type=parsed_type,
            parser_status="sent",
        )
        await self._client.write_gatt_char(UART_WRITE_UUID, packet, response=False)

    async def _request(self, packet: bytes, response_opcode: int, parsed_type: str) -> bytes:
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._pending[response_opcode] = queue
        try:
            await self._send(packet, parsed_type)
            return await asyncio.wait_for(queue.get(), timeout=6)
        except asyncio.TimeoutError as exc:
            raise RingError(
                f"Ring did not answer command {response_opcode}",
                code="command_timeout",
                status=504,
            ) from exc
        finally:
            self._pending.pop(response_opcode, None)

    async def _request_parsed(
        self,
        packet: bytes,
        response_opcode: int,
        parsed_type: str,
        parser: Any,
        timeout: float = 8,
    ) -> Any:
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._pending[response_opcode] = queue
        try:
            await self._send(packet, parsed_type)
            while True:
                incoming = await asyncio.wait_for(queue.get(), timeout=timeout)
                result = parser.parse(incoming)
                if result is not None:
                    return result
        except asyncio.TimeoutError as exc:
            raise RingError(
                f"Ring nie zakończył odpowiedzi dla {parsed_type}",
                code="history_timeout",
                status=504,
            ) from exc
        finally:
            self._pending.pop(response_opcode, None)

    async def _request_hrv_history(self, day: datetime) -> Any:
        """Drive command 57 page by page; the ring does not stream pages itself."""
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        parser = HrvHistoryParser(day)
        self._pending[CMD_HRV_HISTORY] = queue
        try:
            for index in range(256):
                await self._send(read_hrv_packet(index), f"hrv-history:{index}")
                incoming = await asyncio.wait_for(queue.get(), timeout=8)
                result = parser.parse(incoming)
                if result is not None:
                    return result
            raise RingError("HRV history exceeded 255 pages", code="history_invalid", status=502)
        except asyncio.TimeoutError as exc:
            raise RingError(
                "Ring nie odpowiedział na kolejną stronę historii HRV",
                code="history_timeout",
                status=504,
            ) from exc
        finally:
            self._pending.pop(CMD_HRV_HISTORY, None)

    async def _request_big_data(self, data_id: int, parsed_type: str) -> bytes | None:
        if not self._big_data_available or self._big_data_queue is None or self._client is None:
            return None
        while not self._big_data_queue.empty():
            try:
                self._big_data_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        request = big_data_request(data_id)
        self.store.record_packet(
            device_id=self._active_device_id,
            direction="TX",
            service_uuid=BIG_DATA_SERVICE_UUID,
            characteristic_uuid=BIG_DATA_WRITE_UUID,
            payload=request,
            parsed_type=parsed_type,
            parser_status="sent",
        )
        await self._client.write_gatt_char(BIG_DATA_WRITE_UUID, request, response=False)
        reassembler = BigDataReassembler()
        try:
            while True:
                chunk = await asyncio.wait_for(self._big_data_queue.get(), timeout=12)
                message = reassembler.push(chunk)
                if message is None:
                    continue
                if message["dataId"] != data_id:
                    self.store.record_event(
                        "warning", "big_data_mismatch",
                        f"Expected Big Data {data_id}, received {message['dataId']}",
                    )
                    continue
                return message["payload"]
        except asyncio.TimeoutError:
            self.store.record_event("warning", "big_data_timeout", f"No response for {parsed_type}")
            return None

    def _on_notification(self, _sender: Any, data: bytearray) -> None:
        packet = bytes(data)
        opcode = (packet[0] & 0x7F) if packet else None
        parser_status = "received"
        error_message = None
        if len(packet) == 16 and (sum(packet[:15]) & 0xFF) != packet[15]:
            parser_status = "checksum-error"
            error_message = "Packet checksum does not match"
        elif packet and packet[0] & 0x80:
            parser_status = "device-error"
            error_message = "COLMI error bit is set"
        self.store.record_packet(
            device_id=self._active_device_id,
            direction="RX",
            service_uuid=UART_SERVICE_UUID,
            characteristic_uuid=UART_NOTIFY_UUID,
            payload=packet,
            parsed_type={
                1: "set-time",
                3: "battery",
                21: "heart-rate-history",
                22: "heart-rate-settings",
                30: "heart-rate-live",
                57: "hrv-history",
                67: "activity-history",
                105: "realtime-stream",
                106: "realtime-stop",
            }.get(opcode, "unhandled"),
            parser_status=parser_status,
            error_message=error_message,
        )
        if parser_status == "received" and opcode in self._pending:
            self._pending[opcode].put_nowait(packet)

    def _on_big_data_notification(self, _sender: Any, data: bytearray) -> None:
        chunk = bytes(data)
        self.store.record_packet(
            device_id=self._active_device_id,
            direction="RX",
            service_uuid=BIG_DATA_SERVICE_UUID,
            characteristic_uuid=BIG_DATA_NOTIFY_UUID,
            payload=chunk,
            parsed_type="big-data-fragment",
            parser_status="received",
        )
        if self._big_data_queue is not None:
            self._big_data_queue.put_nowait(chunk)

    def _on_disconnect(self, _client: Any) -> None:
        device_id = self._active_device_id
        self._client = None
        self._active_device_id = None
        self._pending.clear()
        self._big_data_queue = None
        self._big_data_available = False
        if device_id:
            self.store.update_device_info(device_id, last_disconnected=utc_now())
        error = RingError("Utracono połączenie z ringiem", code="connection_lost", status=503)
        self._set_status("disconnected", str(error), error)
        self.store.record_event("warning", "connection_lost", str(error), {"deviceId": device_id})

    async def _read_device_info(self) -> dict[str, Any]:
        if self._client is None:
            return {}
        fields = {
            "model": DEVICE_MODEL_UUID,
            "firmware_version": DEVICE_FIRMWARE_UUID,
            "hardware_version": DEVICE_HARDWARE_UUID,
        }
        result: dict[str, Any] = {}
        for key, characteristic in fields.items():
            try:
                raw = bytes(await self._client.read_gatt_char(characteristic))
                self.store.record_packet(
                    device_id=self._active_device_id,
                    direction="RX",
                    service_uuid="0000180a-0000-1000-8000-00805f9b34fb",
                    characteristic_uuid=characteristic,
                    payload=raw,
                    parsed_type=key.replace("_", "-"),
                    parser_status="parsed",
                )
                value = raw.decode("utf-8", errors="replace").strip("\x00 \r\n")
                if value:
                    result[key] = value
            except Exception as exc:
                self.store.record_event("warning", "device_info_unavailable", f"{key}: {exc}")
        return result

    @staticmethod
    def _service_payload(services: Any) -> list[dict[str, Any]]:
        payload = []
        for service in services:
            payload.append({
                "uuid": str(service.uuid).lower(),
                "description": getattr(service, "description", None),
                "characteristics": [
                    {
                        "uuid": str(characteristic.uuid).lower(),
                        "description": getattr(characteristic, "description", None),
                        "properties": list(getattr(characteristic, "properties", []) or []),
                    }
                    for characteristic in service.characteristics
                ],
            })
        return payload


def create_ring_collector(root: str | Path) -> RingCollector:
    return RingCollector(root)
