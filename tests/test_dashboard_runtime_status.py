import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from dashboard_runtime_status import read_dashboard_runtime_status


class DashboardRuntimeStatusTests(unittest.TestCase):
    def test_reads_start_marker_and_system_boot(self):
        boot = datetime(2026, 9, 29, 8, tzinfo=timezone.utc)
        started = boot + timedelta(hours=2)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "data" / "settings" / "dashboard-started-at.txt"
            marker.parent.mkdir(parents=True)
            marker.write_text(started.isoformat(), encoding="utf-8")
            with mock.patch("dashboard_runtime_status.system_boot_time", return_value=boot):
                status = read_dashboard_runtime_status(Path(directory))
        self.assertEqual(status["dashboard_started_at"], started.isoformat())
        self.assertEqual(status["system_booted_at"], boot.isoformat())

    def test_missing_or_old_marker_is_not_reported_as_current_dashboard(self):
        boot = datetime.now(timezone.utc) - timedelta(hours=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch("dashboard_runtime_status.system_boot_time", return_value=boot):
                self.assertIsNone(read_dashboard_runtime_status(root)["dashboard_started_at"])
                marker = root / "data" / "settings" / "dashboard-started-at.txt"
                marker.parent.mkdir(parents=True)
                marker.write_text((boot - timedelta(days=1)).isoformat(), encoding="utf-8")
                self.assertIsNone(read_dashboard_runtime_status(root)["dashboard_started_at"])


if __name__ == "__main__":
    unittest.main()
