import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server


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


class WeightValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scale_dir = Path(self.temp.name)
        self.latest_path = self.scale_dir / "latest.json"
        self.csv_path = self.scale_dir / "scale_measurements.csv"
        self.patches = [
            mock.patch.object(server, "SCALE_DATA_DIR", self.scale_dir),
            mock.patch.object(server, "SCALE_LATEST_JSON", self.latest_path),
            mock.patch.object(server, "SCALE_SIGNAL_JSON", self.scale_dir / "signal.json"),
            mock.patch.object(server, "SCALE_MEASUREMENTS_CSV", self.csv_path),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def write_csv(self, rows):
        with self.csv_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_rejects_weights_outside_the_broad_human_range(self):
        self.assertIsNone(server.parse_realistic_weight_kg(14.05))
        self.assertIsNone(server.parse_realistic_weight_kg(301))
        self.assertEqual(server.parse_realistic_weight_kg("92,5"), 92.5)

    def test_latest_invalid_reading_falls_back_to_latest_valid_history(self):
        self.latest_path.write_text(
            json.dumps({
                "ok": True,
                "timestamp": "2026-07-24T14:59:39",
                "weight_kg": 14.05,
                "has_weight": True,
            }),
            encoding="utf-8",
        )
        self.write_csv([
            {
                "timestamp": "2026-07-24T10:05:07",
                "type": "181D",
                "weight_kg": "92.5",
                "stable": "True",
                "unit": "kg",
            },
            {
                "timestamp": "2026-07-24T14:59:39",
                "type": "181D",
                "weight_kg": "14.05",
                "stable": "True",
                "unit": "kg",
            },
        ])

        result = server.read_latest_weight_measurement()

        self.assertTrue(result["ok"])
        self.assertEqual(result["weight_kg"], 92.5)
        self.assertEqual(result["timestamp"], "2026-07-24T10:05:07")

    def test_history_ignores_invalid_readings_in_daily_average(self):
        self.write_csv([
            {
                "timestamp": "2026-07-24T10:05:07",
                "weight_kg": "92.5",
                "stable": "True",
                "unit": "kg",
            },
            {
                "timestamp": "2026-07-24T14:59:39",
                "weight_kg": "14.05",
                "stable": "True",
                "unit": "kg",
            },
        ])

        result = server.read_weight_history(limit_days=30)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["daily"][0]["avg_weight_kg"], 92.5)
        self.assertEqual(result["daily"][0]["count"], 1)

    def test_missing_latest_file_uses_latest_valid_csv_reading(self):
        self.write_csv([
            {
                "timestamp": "2026-07-24T10:05:07",
                "weight_kg": "92.5",
                "stable": "True",
                "unit": "kg",
            },
            {
                "timestamp": "2026-07-24T14:59:39",
                "weight_kg": "14.05",
                "stable": "True",
                "unit": "kg",
            },
        ])

        result = server.read_latest_weight_measurement()

        self.assertTrue(result["ok"])
        self.assertEqual(result["weight_kg"], 92.5)
        self.assertEqual(result["timestamp"], "2026-07-24T10:05:07")

    def test_stats_include_highest_and_lowest_weights_since_may_1(self):
        self.write_csv([
            {
                "timestamp": "2026-04-30T08:00:00",
                "weight_kg": "110.0",
                "stable": "True",
                "unit": "kg",
            },
            {
                "timestamp": "2026-05-01T08:00:00",
                "weight_kg": "96.5",
                "stable": "True",
                "unit": "kg",
            },
            {
                "timestamp": "2026-06-10T08:00:00",
                "weight_kg": "90.2",
                "stable": "True",
                "unit": "kg",
            },
            {
                "timestamp": "2026-07-24T08:00:00",
                "weight_kg": "92.1",
                "stable": "True",
                "unit": "kg",
            },
        ])

        stats = server.read_weight_stats()["stats"]

        self.assertEqual(stats["highest_weight_kg"], 110.0)
        self.assertEqual(stats["highest_weight_kg_since_may_1_2026"], 96.5)
        self.assertEqual(stats["highest_timestamp_since_may_1_2026"], "2026-05-01T08:00:00")
        self.assertEqual(stats["lowest_weight_kg_since_may_1_2026"], 90.2)
        self.assertEqual(stats["lowest_timestamp_since_may_1_2026"], "2026-06-10T08:00:00")


if __name__ == "__main__":
    unittest.main()
