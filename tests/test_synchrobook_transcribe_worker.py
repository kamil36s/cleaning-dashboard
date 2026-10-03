import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import synchrobook_transcribe_worker as worker


class SynchrobookTranscribeWorkerTests(unittest.TestCase):
    def test_status_write_survives_a_transient_windows_file_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            status = Path(temporary) / "worker-status.json"
            original_replace = worker.os.replace
            attempts = 0

            def flaky_replace(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError(5, "Access is denied", str(destination))
                return original_replace(source, destination)

            with (
                mock.patch.object(worker.os, "replace", side_effect=flaky_replace),
                mock.patch.object(worker.time, "sleep") as sleep,
            ):
                worker.write_status(status, {"stage": "transcribing", "progress": 25})

            self.assertEqual(attempts, 2)
            sleep.assert_called_once_with(worker.WINDOWS_REPLACE_RETRY_DELAYS[0])
            self.assertEqual(json.loads(status.read_text(encoding="utf-8"))["progress"], 25)
            self.assertEqual(list(status.parent.glob("*.tmp")), [])

    def test_status_write_does_not_abort_work_when_lock_persists(self):
        with tempfile.TemporaryDirectory() as temporary:
            status = Path(temporary) / "worker-status.json"
            with (
                mock.patch.object(worker.os, "replace", side_effect=PermissionError(5, "Access is denied")),
                mock.patch.object(worker.time, "sleep"),
            ):
                worker.write_status(status, {"stage": "transcribing", "progress": 25})

            self.assertFalse(status.exists())
            self.assertEqual(list(status.parent.glob("*.tmp")), [])

    def test_chunk_checkpoint_is_reused_only_for_the_same_input_and_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "chunk.wav"
            audio.write_bytes(b"audio")
            chunk = {"path": str(audio), "offset": 300}
            signature = worker.chunk_signature(
                chunk, engine="faster-whisper", model="small", language="auto",
            )
            checkpoint = root / "chunk-results" / "00000.json"
            rows = [{"text": "hello", "start": 0.0, "end": 1.0}]

            worker.save_checkpoint(checkpoint, signature, rows, "en")

            self.assertEqual(worker.load_checkpoint(checkpoint, signature), (rows, "en"))
            changed = worker.chunk_signature(
                chunk, engine="faster-whisper", model="small", language="pl",
            )
            self.assertIsNone(worker.load_checkpoint(checkpoint, changed))

    def test_corrupt_checkpoint_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "00000.json"
            checkpoint.write_text("not-json", encoding="utf-8")

            self.assertIsNone(worker.load_checkpoint(checkpoint, "signature"))

    def test_memory_guard_waits_until_commit_headroom_is_available(self):
        gibibyte = 1024 * 1024 * 1024
        with tempfile.TemporaryDirectory() as temporary:
            status = Path(temporary) / "status.json"
            readings = iter([
                (2 * gibibyte, 1 * gibibyte),
                (2 * gibibyte, 3 * gibibyte),
            ])
            with (
                mock.patch.object(worker, "available_windows_memory", side_effect=lambda: next(readings)),
                mock.patch.object(worker.time, "sleep") as sleep,
            ):
                worker.wait_for_memory(status, poll_seconds=0)

            sleep.assert_called_once_with(0)
            self.assertEqual(
                json.loads(status.read_text(encoding="utf-8"))["stage"],
                "waiting_for_memory",
            )

    def test_quiet_hours_are_only_from_one_until_six(self):
        self.assertFalse(worker.is_night_window(0))
        self.assertTrue(worker.is_night_window(1))
        self.assertTrue(worker.is_night_window(5))
        self.assertFalse(worker.is_night_window(6))

    def test_daytime_resource_guard_pauses_until_user_is_idle(self):
        gibibyte = 1024 * 1024 * 1024
        with tempfile.TemporaryDirectory() as temporary:
            status = Path(temporary) / "status.json"
            idle_readings = iter([5, 121])
            with (
                mock.patch.object(worker, "is_night_window", return_value=False),
                mock.patch.object(worker, "windows_user_idle_seconds", side_effect=lambda: next(idle_readings)),
                mock.patch.object(worker, "available_windows_memory", return_value=(5 * gibibyte, 6 * gibibyte)),
                mock.patch.object(worker, "set_resource_priority") as set_priority,
                mock.patch.object(worker.time, "sleep") as sleep,
            ):
                worker.wait_for_resources(status, progress=25, poll_seconds=0)

            sleep.assert_called_once_with(0)
            self.assertTrue(all(call.kwargs == {"night": False} for call in set_priority.call_args_list))
            saved = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(saved["stage"], "paused_for_user")
            self.assertEqual(saved["progress"], 25)

    def test_high_memory_mode_skips_idle_pause_and_uses_smaller_reserve(self):
        gibibyte = 1024 * 1024 * 1024
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status = root / "status.json"
            settings = root / "processing-settings.json"
            settings.write_text('{"highMemory": true}', encoding="utf-8")
            with (
                mock.patch.object(worker, "is_night_window", return_value=False),
                mock.patch.object(worker, "windows_user_idle_seconds", return_value=0),
                mock.patch.object(worker, "available_windows_memory", return_value=(1 * gibibyte, 2 * gibibyte)),
                mock.patch.object(worker, "set_resource_priority") as set_priority,
                mock.patch.object(worker.time, "sleep") as sleep,
            ):
                worker.wait_for_resources(
                    status, progress=40, poll_seconds=0, resource_settings=settings,
                )

            sleep.assert_not_called()
            set_priority.assert_called_once_with(night=True)
            self.assertFalse(worker.should_release_model(settings))


if __name__ == "__main__":
    unittest.main()
