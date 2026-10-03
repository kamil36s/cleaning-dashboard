import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from journal_htr_runtime import JournalHtrRuntimeController


class JournalHtrRuntimeControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "journal_htr_bootstrap.py").write_text(
            "# test\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_stopped_snapshot_does_not_launch_a_process(self):
        controller = JournalHtrRuntimeController(self.root)
        with patch.object(controller, "_probe", return_value=False), patch(
            "journal_htr_runtime.subprocess.run"
        ) as run:
            snapshot = controller.snapshot()

        self.assertEqual(snapshot["state"], "stopped")
        self.assertTrue(snapshot["canStart"])
        run.assert_not_called()

    def test_start_and_stop_actions_update_state_and_callbacks(self):
        started = Mock()
        stopped = Mock()
        controller = JournalHtrRuntimeController(
            self.root, on_started=started, on_stopped=stopped
        )
        completed = subprocess.CompletedProcess([], 0, "gotowe", "")

        with patch.object(controller, "_probe", return_value=True), patch(
            "journal_htr_runtime.subprocess.run", return_value=completed
        ):
            controller._run_action("start")
            self.assertEqual(controller.snapshot(probe=False)["state"], "online")
            controller._run_action("stop")

        self.assertEqual(controller.snapshot(probe=False)["state"], "stopped")
        started.assert_called_once_with()
        stopped.assert_called_once_with()

    def test_failed_start_keeps_an_actionable_error(self):
        controller = JournalHtrRuntimeController(self.root)
        failed = subprocess.CompletedProcess([], 1, "", "Docker unavailable")

        with patch.object(controller, "_probe", return_value=False), patch(
            "journal_htr_runtime.subprocess.run", return_value=failed
        ):
            controller._run_action("start")
            snapshot = controller.snapshot()

        self.assertEqual(snapshot["state"], "error")
        self.assertIn("Docker unavailable", snapshot["detail"])
        self.assertTrue(snapshot["canStart"])


if __name__ == "__main__":
    unittest.main()
