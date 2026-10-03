import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import server


class SensorApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.latest_path = data_dir / "latest.json"
        self.history_path = data_dir / "readings.jsonl"
        self.patches = [
            mock.patch.object(server, "SENSOR_LATEST_JSON", self.latest_path),
            mock.patch.object(server, "SENSOR_READINGS_JSONL", self.history_path),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp_dir.cleanup()

    def test_latest_sensor_reading_includes_age(self):
        timestamp = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="milliseconds")
        self.latest_path.write_text(json.dumps({
            "timestamp": timestamp,
            "temp_c": 23.88,
            "hum_pct": 50.08,
            "battery_pct": 69,
        }), encoding="utf-8")

        payload = server.read_sensor_latest()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["temp_c"], 23.88)
        self.assertGreaterEqual(payload["age_seconds"], 4)

    def test_history_filters_old_and_malformed_rows(self):
        recent = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="milliseconds")
        old = (datetime.now() - timedelta(hours=30)).isoformat(timespec="milliseconds")
        self.history_path.write_text(
            json.dumps({"timestamp": old, "temperature_c": 20, "humidity_percent": 40})
            + "\nnot-json\n"
            + json.dumps({"timestamp": recent, "temperature_c": 23.88, "humidity_percent": 50.08})
            + "\n",
            encoding="utf-8",
        )

        rows = server.read_sensor_history(hours=24)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temperature_c"], 23.88)

    def test_history_filters_exact_local_day(self):
        self.history_path.write_text(
            "\n".join([
                json.dumps({"timestamp": "2026-09-11T23:59:59", "temperature_c": 19}),
                json.dumps({"timestamp": "2026-09-12T00:00:00", "temperature_c": 20}),
                json.dumps({"timestamp": "2026-09-12T23:59:59", "temperature_c": 21}),
                json.dumps({"timestamp": "2026-09-13T00:00:00", "temperature_c": 22}),
            ]) + "\n",
            encoding="utf-8",
        )

        rows = server.read_sensor_history(date_value="2026-09-12")

        self.assertEqual([row["temperature_c"] for row in rows], [20, 21])

    def test_history_filters_exact_calendar_month(self):
        self.history_path.write_text(
            "\n".join([
                json.dumps({"timestamp": "2026-08-31T23:59:59", "humidity_percent": 40}),
                json.dumps({"timestamp": "2026-09-01T00:00:00", "humidity_percent": 41}),
                json.dumps({"timestamp": "2026-09-30T23:59:59", "humidity_percent": 42}),
                json.dumps({"timestamp": "2026-10-01T00:00:00", "humidity_percent": 43}),
            ]) + "\n",
            encoding="utf-8",
        )

        rows = server.read_sensor_history(month_value="2026-09")

        self.assertEqual([row["humidity_percent"] for row in rows], [41, 42])


if __name__ == "__main__":
    unittest.main()
