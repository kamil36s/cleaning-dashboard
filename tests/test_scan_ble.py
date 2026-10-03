import unittest
from types import SimpleNamespace
from unittest import mock

from scripts import scan_ble


class ScanBleValidationTests(unittest.TestCase):
    def setUp(self):
        scan_ble.last_saved_at = 0.0
        scan_ble.sensor_last_history_at = 0.0
        scan_ble.sensor_last_payload = None
        scan_ble.console_stats.update({
            "started_at": None,
            "packets": 0,
            "decoded_packets": 0,
            "stable_readings": 0,
            "saved_measurements": 0,
            "last_weight": None,
            "last_rssi": None,
        })

    def test_console_packets_are_summarized_after_five_minutes(self):
        with mock.patch("builtins.print") as print_line:
            self.assertIsNone(scan_ble.record_console_packet(True, 1, 1, 92.5, -90, now=100))
            self.assertIsNone(scan_ble.record_console_packet(False, last_rssi=-96, now=399))
            message = scan_ble.record_console_packet(True, 1, 0, 92.6, -85, now=400)

        self.assertIn("packets=3", message)
        self.assertIn("decoded=66.7%", message)
        self.assertIn("stable=2", message)
        self.assertIn("saved=1", message)
        print_line.assert_called_once_with(message)

    def test_unrealistic_stable_measurement_is_not_saved(self):
        row = {
            "timestamp": "2026-07-24T14:59:39",
            "weight_kg": 14.05,
            "stable": True,
            "has_weight": True,
            "rssi": -96,
            "type": "181D",
        }

        with (
            mock.patch.object(scan_ble, "append_measurement_csv") as append_csv,
            mock.patch.object(scan_ble, "append_measurement_jsonl") as append_jsonl,
            mock.patch.object(scan_ble, "write_latest_json") as write_latest,
            mock.patch.object(scan_ble, "write_signal_json") as write_signal,
            mock.patch("builtins.print"),
        ):
            scan_ble.handle_measurement(row)

        append_csv.assert_not_called()
        append_jsonl.assert_not_called()
        write_latest.assert_not_called()
        write_signal.assert_not_called()

    def test_normal_stable_measurement_is_saved(self):
        row = {
            "timestamp": "2026-07-24T10:05:07",
            "weight_kg": 92.5,
            "stable": True,
            "has_weight": True,
            "rssi": -96,
            "type": "181D",
        }

        with (
            mock.patch.object(scan_ble, "append_measurement_csv") as append_csv,
            mock.patch.object(scan_ble, "append_measurement_jsonl") as append_jsonl,
            mock.patch.object(scan_ble, "write_latest_json") as write_latest,
            mock.patch.object(scan_ble, "write_signal_json") as write_signal,
            mock.patch("builtins.print"),
        ):
            scan_ble.handle_measurement(row)

        append_csv.assert_called_once()
        append_jsonl.assert_called_once()
        write_latest.assert_called_once()
        write_signal.assert_called_once()

    def test_parses_observed_bthome_temperature_packet(self):
        payload = bytes.fromhex("40 00 2d 01 45 02 54 09 03 90 13")

        self.assertEqual(scan_ble.parse_bthome_v2(payload), {
            "temp_c": 23.88,
            "hum_pct": 50.08,
            "battery_pct": 69,
            "packet_id": 45,
        })

    def test_ignores_bthome_status_packet_without_temperature(self):
        payload = bytes.fromhex("40 00 2d 0c c4 0a 10 00 11 01")

        self.assertIsNone(scan_ble.parse_bthome_v2(payload))

    def test_sensor_callback_routes_bthome_packet_and_deduplicates_repeats(self):
        payload = bytes.fromhex("40 00 2d 01 45 02 54 09 03 90 13")
        device = SimpleNamespace(address=scan_ble.SENSOR_MAC, name="ATC_4DC981")
        advertisement = SimpleNamespace(
            service_data={scan_ble.UUID_BTHOME.upper(): payload},
            service_uuids=[],
            manufacturer_data={},
            rssi=-87,
        )

        with mock.patch.object(scan_ble, "handle_sensor_reading") as handle_reading:
            scan_ble.callback(device, advertisement)
            scan_ble.callback(device, advertisement)

        handle_reading.assert_called_once()
        reading = handle_reading.call_args.args[0]
        self.assertEqual(reading["temp_c"], 23.88)
        self.assertEqual(reading["hum_pct"], 50.08)
        self.assertEqual(reading["battery_pct"], 69)
        self.assertEqual(reading["rssi"], -87)
        self.assertEqual(reading["source"], "BLE_BTHOME_V2")


if __name__ == "__main__":
    unittest.main()
