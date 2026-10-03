import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import server
from ring_collector import RingCollector, make_packet, parse_battery, set_time_packet
from ring_protocol import (
    ActivityHistoryParser,
    BigDataReassembler,
    HeartRateHistoryParser,
    parse_sleep_history,
    parse_spo2_history,
)
from ring_phone_bridge import RingPhoneBridge, RingPhoneBridgeError
from ring_store import RingStore
from ring_wear import RingWearDetector


class RingProtocolTests(unittest.TestCase):
    @staticmethod
    def response(command, payload):
        packet = bytearray(16)
        packet[0] = command
        packet[1:1 + len(payload)] = payload
        packet[15] = sum(packet[:15]) & 0xFF
        return bytes(packet)

    def test_packet_checksum_and_battery_parser(self):
        request = make_packet(3)
        self.assertEqual(len(request), 16)
        self.assertEqual(request[-1], 3)

        response = bytearray(16)
        response[0] = 3
        response[1] = 64
        response[2] = 1
        response[15] = sum(response[:15]) & 0xFF
        self.assertEqual(parse_battery(response), {"battery_percentage": 64, "charging": True})

    def test_set_time_is_bcd_encoded_in_utc(self):
        packet = set_time_packet(datetime(2026, 9, 2, 14, 5, 9, tzinfo=timezone.utc))
        self.assertEqual(packet[:8], bytes([1, 0x26, 0x09, 0x02, 0x14, 0x05, 0x09, 1]))
        self.assertEqual(packet[-1], sum(packet[:15]) & 0xFF)

    def test_heart_rate_history_is_reassembled_and_invalid_values_are_skipped(self):
        parser = HeartRateHistoryParser(
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            now=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )
        self.assertIsNone(parser.parse(self.response(21, bytes([0, 3, 5]))))
        epoch = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
        first = bytes([1]) + epoch.to_bytes(4, "little") + bytes([60, 0, 72, 73, 74, 75, 76, 77, 78])
        self.assertIsNone(parser.parse(self.response(21, first)))
        result = parser.parse(self.response(21, bytes([2, 79, 80, 250])))
        self.assertEqual(result["intervalMinutes"], 5)
        self.assertEqual(result["samples"][0]["bpm"], 60)
        self.assertEqual(result["samples"][1]["timestampUtc"], "2026-09-01T00:10:00Z")
        self.assertNotIn(250, [sample["bpm"] for sample in result["samples"]])

    def test_activity_slots_use_warsaw_time_and_stable_units(self):
        parser = ActivityHistoryParser(day_offset=0)
        self.assertIsNone(parser.parse(self.response(67, bytes([0xF0, 0, 1]))))
        detail = bytearray(14)
        detail[0:6] = bytes([0x26, 0x09, 0x02, 40, 0, 1])
        detail[6:8] = (12).to_bytes(2, "little")
        detail[8:10] = (1234).to_bytes(2, "little")
        detail[10:12] = (876).to_bytes(2, "little")
        result = parser.parse(self.response(67, detail))
        self.assertEqual(result[0]["timestampUtc"], "2026-09-02T08:00:00Z")
        self.assertEqual(result[0]["steps"], 1234)
        self.assertEqual(result[0]["caloriesKcal"], 0.12)
        self.assertEqual(result[0]["distanceM"], 876)

    def test_big_data_sleep_and_spo2_payloads(self):
        payload = bytes([0, 98, 94]) + bytes(46)
        frame = bytes([0xBC, 0x2A, len(payload), 0, 0xFF, 0xFF]) + payload
        reassembler = BigDataReassembler()
        self.assertIsNone(reassembler.push(frame[:8]))
        assembled = reassembler.push(frame[8:])
        self.assertEqual(assembled["dataId"], 0x2A)
        spo2 = parse_spo2_history(
            assembled["payload"], now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
        )
        self.assertEqual((spo2[0]["spo2Min"], spo2[0]["spo2Max"]), (94, 98))

        start = (22 * 60).to_bytes(2, "little", signed=True)
        end = (7 * 60).to_bytes(2, "little", signed=True)
        sleep_payload = bytes([1, 0, 10]) + start + end + bytes([2, 120, 3, 240, 4, 60])
        sleep = parse_sleep_history(
            sleep_payload, now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
        )
        self.assertEqual([stage["stage"] for stage in sleep[0]["stages"]], ["light", "deep", "rem"])
        self.assertEqual(sleep[0]["totalMinutes"], 420)
        self.assertEqual(sleep[0]["sleepDate"], "2026-09-02")
        self.assertEqual(sleep[0]["sleepStartUtc"], "2026-09-01T20:00:00Z")
        self.assertEqual(sleep[0]["sleepEndUtc"], "2026-09-02T05:00:00Z")

    def test_sleep_history_does_not_copy_yesterdays_night_after_midnight(self):
        start = (22 * 60 + 28).to_bytes(2, "little", signed=True)
        end = (6 * 60 + 29).to_bytes(2, "little", signed=True)
        sleep_payload = bytes([1, 0, 10]) + start + end + bytes([2, 120, 3, 240, 4, 60])

        sleep = parse_sleep_history(
            sleep_payload, now=datetime(2026, 9, 3, 22, 3, tzinfo=timezone.utc)
        )

        self.assertEqual(sleep[0]["sleepDate"], "2026-09-03")
        self.assertEqual(sleep[0]["sleepStartUtc"], "2026-09-02T20:28:00Z")
        self.assertEqual(sleep[0]["sleepEndUtc"], "2026-09-03T04:29:00Z")


class RingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = RingStore(Path(self.temp_dir.name) / "ring.sqlite")
        self.device = self.store.upsert_device(
            ble_id="AA:BB:CC:DD:EE:FF", advertised_name="R10_1234", rssi=-51, source_mode="real"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_device_and_heart_rate_ingestion_are_idempotent(self):
        self.store.select_device(self.device["deviceId"])
        records = [{
            "timestampUtc": "2026-09-02T10:00:00.000Z",
            "bpm": 71,
            "sourceMode": "history",
            "sourceSlot": 120,
        }]
        self.assertEqual(self.store.ingest_heart_rate(self.device["deviceId"], records), 1)
        self.assertEqual(self.store.ingest_heart_rate(self.device["deviceId"], records), 0)
        overview = self.store.overview()
        self.assertEqual(overview["latest"]["heartRate"]["bpm"], 71)

    def test_heart_rate_archive_supports_timestamp_ranges(self):
        self.store.select_device(self.device["deviceId"])
        self.store.ingest_heart_rate(self.device["deviceId"], [
            {"timestampUtc": "2026-09-02T10:00:00.000Z", "bpm": 71},
            {"timestampUtc": "2026-09-02T10:01:00.000Z", "bpm": 72},
        ])

        archive = self.store.heart_rate_archive(
            from_timestamp=1_788_343_260_000,
            to_timestamp=1_788_343_319_999,
        )

        self.assertEqual([sample["bpm"] for sample in archive["heartRate"]], [72])

    def test_all_history_tables_dedupe_and_sleep_segments_have_real_windows(self):
        self.store.select_device(self.device["deviceId"])
        device_id = self.device["deviceId"]
        spo2 = [{"timestampUtc": "2026-09-02T10:00:00Z", "spo2": 97, "spo2Min": 95, "spo2Max": 98}]
        activity = [{"timestampUtc": "2026-09-02T10:00:00Z", "sourceSlot": 40, "steps": 500, "distanceM": 350, "caloriesKcal": 20}]
        hrv = [{"timestampUtc": "2026-09-02T10:00:00Z", "sourceSlot": 120, "ringValue": 42}]
        sleep = [{
            "sleepDate": "2026-09-01",
            "sleepStartUtc": "2026-09-01T20:00:00Z",
            "sleepEndUtc": "2026-09-02T03:00:00Z",
            "totalMinutes": 420,
            "awakeMinutes": 0,
            "lightMinutes": 120,
            "deepMinutes": 300,
            "remMinutes": 0,
            "stages": [
                {"stage": "light", "durationMinutes": 120},
                {"stage": "deep", "durationMinutes": 300},
            ],
        }]
        for ingestor, records in (
            (self.store.ingest_spo2, spo2),
            (self.store.ingest_activity, activity),
            (self.store.ingest_hrv, hrv),
            (self.store.ingest_sleep, sleep),
        ):
            self.assertEqual(ingestor(device_id, records), 1)
            self.assertEqual(ingestor(device_id, records), 0)
        history = self.store.history()
        self.assertEqual((len(history["spo2"]), len(history["activity"]), len(history["hrv"])), (1, 1, 1))
        self.assertIn("createdAt", history["sleep"][0])
        segments = history["sleep"][0]["stages"]
        self.assertEqual(segments[0]["endUtc"], "2026-09-01T22:00:00Z")
        self.assertEqual(segments[1]["startUtc"], "2026-09-01T22:00:00Z")
        self.assertEqual(segments[1]["endUtc"], "2026-09-02T03:00:00Z")

    def test_latest_sleep_prefers_newer_snapshot_over_longer_stale_copy(self):
        self.store.select_device(self.device["deviceId"])
        stale = {
            "sleepDate": "2026-09-04",
            "sleepStartUtc": "2026-09-03T20:28:00Z",
            "sleepEndUtc": "2026-09-04T04:29:00Z",
            "totalMinutes": 481,
            "stages": [{"stage": "light", "durationMinutes": 481}],
        }
        actual = {
            "sleepDate": "2026-09-04",
            "sleepStartUtc": "2026-09-03T20:06:00Z",
            "sleepEndUtc": "2026-09-04T04:03:00Z",
            "totalMinutes": 477,
            "stages": [{"stage": "light", "durationMinutes": 477}],
        }
        with mock.patch("ring_store.utc_now", side_effect=[
            "2026-09-03T22:03:23.000Z",
            "2026-09-04T06:17:05.000Z",
        ]):
            self.store.ingest_sleep(self.device["deviceId"], [stale])
            self.store.ingest_sleep(self.device["deviceId"], [actual])

        latest = self.store.overview()["latest"]["sleep"]

        self.assertEqual(latest["sleep_start_utc"], actual["sleepStartUtc"])
        self.assertEqual(latest["total_minutes"], 477)

    def test_mock_collector_runs_vertical_slice_without_ble(self):
        collector = RingCollector(Path(__file__).resolve().parents[1], mode="mock", store=self.store)
        scan = collector.scan(2)
        self.assertEqual(len(scan["devices"]), 1)
        connected = collector.connect(scan["devices"][0]["deviceId"])
        self.assertEqual(connected["state"]["collector"]["status"], "connected")
        self.assertEqual(connected["state"]["device"]["batteryPercentage"], 76)
        self.assertEqual(connected["state"]["device"]["sourceMode"], "mock")

    def test_real_collector_connects_with_handle_returned_by_scan(self):
        class FakeDevice:
            address = "32:32:43:33:CE:01"
            name = "COLMI R10 CE01"

        class FakeAdvertisement:
            local_name = "COLMI R10 CE01"
            rssi = -55
            service_uuids = ["6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"]

        class FakeService:
            uuid = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
            description = "COLMI UART"
            characteristics = []

        class FakeServices(list):
            def get_service(self, uuid):
                return self[0] if uuid.lower() == self[0].uuid else None

        fake_device = FakeDevice()

        class FakeScanner:
            @staticmethod
            async def discover(**_kwargs):
                return {fake_device.address: (fake_device, FakeAdvertisement())}

            @staticmethod
            async def find_device_by_address(*_args, **_kwargs):
                raise AssertionError("cached BLEDevice should avoid a second scan")

        class FakeClient:
            received_target = None

            def __init__(self, target, disconnected_callback=None, **_kwargs):
                FakeClient.received_target = target
                self.disconnected_callback = disconnected_callback
                self.services = FakeServices([FakeService()])
                self.is_connected = False
                self.notification = None

            async def connect(self):
                self.is_connected = True

            async def disconnect(self):
                self.is_connected = False

            async def start_notify(self, _uuid, callback):
                self.notification = callback

            async def read_gatt_char(self, _uuid):
                raise RuntimeError("optional Device Information characteristic is absent")

            async def write_gatt_char(self, _uuid, packet, response=False):
                if packet[0] == 3:
                    battery = bytearray(16)
                    battery[0] = 3
                    battery[1] = 82
                    battery[2] = 0
                    battery[15] = sum(battery[:15]) & 0xFF
                    self.notification(None, battery)

        collector = RingCollector(Path(__file__).resolve().parents[1], mode="real", store=self.store)
        with (
            mock.patch("ring_collector.BleakScanner", FakeScanner),
            mock.patch("ring_collector.BleakClient", FakeClient),
        ):
            scan = collector.scan(2)
            connected = collector.connect(scan["devices"][0]["deviceId"])

        self.assertIs(FakeClient.received_target, fake_device)
        self.assertEqual(connected["state"]["device"]["batteryPercentage"], 82)

    def test_android_phone_bridge_persists_raw_and_deduplicates_observations(self):
        presence = []
        bridge = RingPhoneBridge(self.store, presence.append)
        payload = {
            "schemaVersion": 1,
            "phoneId": "phone-test",
            "bridgeActive": True,
            "ring": {"bleId": "AA:BB:CC:DD:EE:FF", "advertisedName": "COLMI R10"},
            "packets": [{
                "id": "packet-1",
                "capturedAt": "2026-09-02T12:30:50Z",
                "direction": "RX",
                "channel": "uart",
                "context": "heart-rate-live",
                "payloadHex": "69 01 00 4A 00 00 0C 03 00 00 00 00 00 00 00 C3",
            }],
            "observations": [
                {"id": "hr-1", "type": "heartRate", "timestampUtc": "2026-09-02T12:30:50Z", "bpm": 74},
                {"id": "watch-hr-1", "type": "watchHeartRate", "timestampUtc": "2026-09-02T12:30:51Z", "bpm": 75,
                 "dataOrigin": "com.example.watch", "deviceType": 1, "manufacturer": "Example", "model": "Watch"},
                {"id": "spo2-1", "type": "spo2", "timestampUtc": "2026-09-02T12:31:10Z", "spo2": 97},
                {"id": "hrv-1", "type": "hrv", "timestampUtc": "2026-09-02T12:32:00Z", "ringValue": 45},
            ],
        }
        first = bridge.ingest(payload)
        second = bridge.ingest(payload)
        self.assertEqual(first["insertedPackets"], 1)
        self.assertEqual(first["inserted"], {"heartRate": 1, "watchHeartRate": 1, "spo2": 1, "hrv": 1})
        self.assertEqual(second["insertedPackets"], 0)
        self.assertEqual(second["inserted"], {"heartRate": 0, "watchHeartRate": 0, "spo2": 0, "hrv": 0})
        self.assertEqual(set(first["processedIds"]), {"packet-1", "hr-1", "watch-hr-1", "spo2-1", "hrv-1"})
        self.assertEqual(self.store.history()["watchHeartRateReference"][0]["bpm"], 75)
        self.assertEqual(presence, [True, True])
        diagnostics = self.store.diagnostics()
        self.assertEqual(diagnostics["packets"][0]["source_transport"], "android-ble")
        self.assertEqual(diagnostics["packets"][0]["timestamp_utc"], "2026-09-02T12:30:50.000Z")

    def test_android_phone_bridge_rejects_an_invalid_schema(self):
        with self.assertRaises(RingPhoneBridgeError):
            RingPhoneBridge(self.store).ingest({"schemaVersion": 2})


class RingWearDetectorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = RingStore(Path(self.temp_dir.name) / "ring.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_detects_removed_ring_from_failed_optical_cycle_and_resumes_on_contact(self):
        detector = RingWearDetector(minimum_zero_frames=3, minimum_valid_frames=2)
        device_id = "ring-test"
        start = "2026-09-03T10:53:23.000Z"
        detector.observe_packet(device_id, start, "TX", "heart-rate-live", make_packet(0x69, bytes([1, 1])))
        detector.observe_packet(device_id, "2026-09-03T10:53:24.000Z", "RX", "heart-rate-live", make_packet(0x69, bytes([1, 0, 0])))
        detector.observe_packet(device_id, "2026-09-03T10:53:25.000Z", "RX", "heart-rate-live", make_packet(0x69, bytes([1, 0, 0])))
        detector.observe_packet(device_id, "2026-09-03T10:53:26.000Z", "RX", "heart-rate-live", make_packet(0x69, bytes([1, 0, 0])))
        removed = detector.observe_packet(device_id, "2026-09-03T10:53:27.000Z", "RX", "heart-rate-live", make_packet(0x69, bytes([1, 1, 0])))

        self.assertEqual(removed["state"], "off_wrist")
        self.assertTrue(removed["changed"])
        self.assertFalse(detector.accepts_heart_rate(device_id, "2026-09-03T10:54:00Z"))
        self.assertTrue(detector.accepts_heart_rate(device_id, "2026-09-03T10:50:00Z"))

        detector.observe_packet(device_id, "2026-09-03T11:00:00.000Z", "TX", "heart-rate-live", make_packet(0x69, bytes([1, 1])))
        detector.observe_packet(device_id, "2026-09-03T11:00:05.000Z", "RX", "heart-rate-live", make_packet(0x69, bytes([1, 0, 78])))
        worn = detector.observe_packet(device_id, "2026-09-03T11:00:06.000Z", "RX", "heart-rate-live", make_packet(0x69, bytes([1, 0, 79])))

        self.assertEqual(worn["state"], "worn")
        self.assertTrue(worn["changed"])
        self.assertTrue(detector.accepts_heart_rate(device_id, "2026-09-03T11:00:07Z"))

    def test_phone_bridge_filters_hr_observations_inside_off_wrist_interval(self):
        bridge = RingPhoneBridge(self.store, wear_detector=RingWearDetector(3, 2))
        packets = [
            ("p0", "2026-09-03T10:53:23Z", "TX", make_packet(0x69, bytes([1, 1]))),
            ("p1", "2026-09-03T10:53:24Z", "RX", make_packet(0x69, bytes([1, 0, 0]))),
            ("p2", "2026-09-03T10:53:25Z", "RX", make_packet(0x69, bytes([1, 0, 0]))),
            ("p3", "2026-09-03T10:53:26Z", "RX", make_packet(0x69, bytes([1, 0, 0]))),
            ("p4", "2026-09-03T10:53:27Z", "RX", make_packet(0x69, bytes([1, 1, 0]))),
        ]
        payload = {
            "schemaVersion": 1,
            "phoneId": "phone-test",
            "bridgeActive": True,
            "ring": {"bleId": "AA:BB:CC:DD:EE:FF", "advertisedName": "COLMI R10"},
            "packets": [{
                "id": packet_id,
                "capturedAt": captured_at,
                "direction": direction,
                "channel": "uart",
                "context": "heart-rate-live",
                "payloadHex": packet.hex(),
            } for packet_id, captured_at, direction, packet in packets],
            "observations": [{
                "id": "bad-table-reading",
                "type": "heartRate",
                "timestampUtc": "2026-09-03T10:54:00Z",
                "bpm": 180,
            }],
        }

        result = bridge.ingest(payload)

        self.assertEqual(result["wear"]["state"], "off_wrist")
        self.assertEqual(result["inserted"]["heartRateFilteredOffWrist"], 1)
        self.assertEqual(self.store.history()["heartRate"], [])


class FakeRingCollector:
    class FakeStore:
        @staticmethod
        def history(limit):
            return {"deviceId": None, "heartRate": [], "spo2": [], "activity": [], "hrv": [], "sleep": [], "limit": limit}

        @staticmethod
        def heart_rate_archive(**_kwargs):
            return {"deviceId": None, "heartRate": [], "watchHeartRateReference": []}

    store = FakeStore()

    def state(self):
        return {
            "ok": True,
            "mode": "real",
            "collector": {"status": "disconnected", "message": "No COLMI ring connected", "bleDependencyAvailable": True},
            "device": None,
            "latest": {},
            "capabilities": {"battery": "supported"},
            "services": [],
            "devices": [],
            "storage": {"database": "test.sqlite"},
        }

    def diagnostics(self, limit):
        return {"ok": True, "packets": [], "events": [], "syncRuns": [], "limit": limit}

    def scan(self, timeout):
        return {"ok": True, "devices": [], "timeout": timeout}

    def connect(self, device_id):
        return {"ok": True, "deviceId": device_id}

    def disconnect(self):
        return {"ok": True}

    def sync(self):
        return {"ok": True, "records": {"battery": 1}}

    def presence(self):
        return {"ok": True, "liveUntil": "2026-09-02T10:00:00Z", "state": self.state()}


class FakeRingPhoneBridge:
    def wear_state(self, _device_id=None):
        return {"state": "unknown", "since": None, "updatedAt": None, "reason": "test", "filteredHeartRate": 0, "filteredMeasurements": {}}

    def ingest(self, payload):
        return {"ok": True, "processedIds": [item["id"] for item in payload.get("packets", [])]}

    def status(self, payload):
        return {"ok": True, "phoneBridgeActive": bool(payload.get("bridgeActive"))}


class RingApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_collector = server.RING_COLLECTOR
        self.previous_phone_bridge = server.RING_PHONE_BRIDGE
        server.RING_COLLECTOR = FakeRingCollector()
        server.RING_PHONE_BRIDGE = FakeRingPhoneBridge()
        self.httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.RING_COLLECTOR = self.previous_collector
        server.RING_PHONE_BRIDGE = self.previous_phone_bridge

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, data

    def test_state_scan_connect_sync_and_diagnostics_routes(self):
        status, state = self.request("GET", "/api/ring/state")
        self.assertEqual(status, 200)
        self.assertIsNone(state["device"])

        status, scan = self.request("POST", "/api/ring/scan", {"timeoutSeconds": 3})
        self.assertEqual((status, scan["timeout"]), (200, 3))

        status, connected = self.request("POST", "/api/ring/connect", {"deviceId": "colmi_test"})
        self.assertEqual((status, connected["deviceId"]), (200, "colmi_test"))

        status, synced = self.request("POST", "/api/ring/sync", {})
        self.assertEqual((status, synced["records"]["battery"]), (200, 1))

        status, diagnostics = self.request("GET", "/api/ring/diagnostics?limit=12")
        self.assertEqual((status, diagnostics["limit"]), (200, 12))

        status, history = self.request("GET", "/api/ring/history?limit=321")
        self.assertEqual((status, history["limit"]), (200, 321))

        status, presence = self.request("POST", "/api/ring/presence", {})
        self.assertEqual((status, presence["state"]["collector"]["status"]), (200, "disconnected"))
        self.assertEqual(presence["state"]["wear"]["state"], "unknown")

        status, phone = self.request("POST", "/api/ring/phone/ingest", {
            "schemaVersion": 1,
            "packets": [{"id": "phone-packet-1"}],
        })
        self.assertEqual((status, phone["processedIds"]), (200, ["phone-packet-1"]))

        status, bridge_status = self.request("POST", "/api/ring/phone/status", {
            "schemaVersion": 1,
            "phoneId": "phone-test",
            "bridgeActive": True,
        })
        self.assertEqual((status, bridge_status["phoneBridgeActive"]), (200, True))


if __name__ == "__main__":
    unittest.main()
