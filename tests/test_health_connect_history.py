import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server


class HealthConnectSleepHistoryTests(unittest.TestCase):
    def test_returns_the_richest_snapshot_for_every_recorded_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest_path = root / "latest.json"
            history_path = root / "snapshots.jsonl"
            snapshots = [
                {
                    "day": "2026-09-04",
                    "received_at": "2026-09-04T06:00:00",
                    "payload": {
                        "day": "2026-09-04",
                        "sleep": {"sessions": []},
                        "heart_rate": {"samples": []},
                    },
                },
                {
                    "day": "2026-09-04",
                    "received_at": "2026-09-04T07:00:00",
                    "payload": {
                        "day": "2026-09-04",
                        "sleep": {"sessions": [{
                            "start": "2026-09-03T20:00:00Z",
                            "end": "2026-09-04T04:00:00Z",
                            "stages": [],
                        }]},
                        "heart_rate": {"samples": [{"time": "2026-09-04T00:00:00Z", "bpm": 55}]},
                        "exercise": {"sessions": [{"route": {"points": [1, 2, 3]}}]},
                    },
                },
                {
                    "day": "2026-09-05",
                    "received_at": "2026-09-05T07:00:00",
                    "payload": {
                        "day": "2026-09-05",
                        "sleep": {"sessions": [{
                            "start": "2026-09-04T21:00:00Z",
                            "end": "2026-09-05T05:00:00Z",
                            "stages": [],
                        }]},
                        "heart_rate": {"samples": []},
                    },
                },
            ]
            history_path.write_text(
                "\n".join(json.dumps(snapshot) for snapshot in snapshots) + "\ninvalid\n",
                encoding="utf-8",
            )
            latest_path.write_text(json.dumps(snapshots[-1]), encoding="utf-8")

            with mock.patch.object(server, "HEALTH_LATEST_JSON", latest_path), mock.patch.object(
                server, "HEALTH_SNAPSHOTS_JSONL", history_path
            ):
                result = server.read_health_sleep_history()

        self.assertTrue(result["ok"])
        self.assertEqual(result["latestReceivedAt"], "2026-09-05T07:00:00")
        self.assertEqual([row["day"] for row in result["snapshots"]], ["2026-09-05", "2026-09-04"])
        self.assertEqual(result["snapshots"][1]["payload"]["sleep"]["sessions"][0]["end"], "2026-09-04T04:00:00Z")
        self.assertNotIn("exercise", result["snapshots"][1]["payload"])


if __name__ == "__main__":
    unittest.main()
